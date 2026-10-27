"""Service-account tokens for external agents (SPEC_20 R31) and their scoped tool calls (R30).

A showrunner (project admin) issues a token for one production, scoped as
{project, tools: [...], writeMode: "propose_only" | "generate", expiresAt}. Only the token's SHA-256 is
stored, in agent_service_token, outside the versioned account row, so Console history and every listing
never carry it; the plaintext is returned once. Tokens always expire and can be revoked.

zerofield-mcp is a thin stdio client of this server, so every decision is made here. A token sees the tools
the registry exposes to zerofield-mcp (tool_registry.ZEROFIELD_MCP) that its scope lists; propose_only
tokens never see generation tools. A call runs through tools.call with the issuing showrunner's live
authority, and agent_policy narrows it to the token's scope (policy_profile), so argument validation,
proposals, the production policy and governance are the same ones the internal crew passes. Every call is
audited (audit_log, action service_account_call) with the service-account identity, and the usage summary
attributes generation reservations to the account through its allocations.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import re
import secrets
import tempfile
from pathlib import Path

from project_assistant import tool_registry
from project_assistant.agent_registry import AgentError

TOKEN_PREFIX = 'zfsa_'
WRITE_MODES = ('propose_only', 'generate')
DEFAULT_DAYS, MAX_DAYS = 30, 365
DEFAULT_RPM = 30  # agent_console_settings.rate_limits.rpm_per_agent default
ACCOUNT_KEY = re.compile(r'^[a-z][a-z0-9_-]{0,47}$')
AGENT_PREFIX = 'svc-'  # ctx.agent_key of a service-account call; never a crew agent profile
CALL_ACTION = 'service_account_call'
FIELDS = {'accountKey', 'displayName', 'tools', 'writeMode', 'expiresAt', 'expiresInDays'}
_COLUMNS = ('project_slug, account_key, display_name, tools, write_mode, expires_at, created_by, created_at, '
            'revoked_at, enabled, limb_id')


def token_hash(token) -> str:
    return hashlib.sha256(str(token).encode('utf-8')).hexdigest()


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _iso(value):
    return value.isoformat().replace('+00:00', 'Z') if value else None


# ---------- what a token may see ----------

def exposed_tools(write_mode=None) -> list[str]:
    """Registry-ordered tools zerofield-mcp may list; for propose_only, without generation tools."""
    return [t.name for t in tool_registry.all_tools() if t.name in tool_registry.ZEROFIELD_MCP
            and (write_mode != 'propose_only' or t.name not in tool_registry.GENERATION)]


def visible_specs(account) -> list[dict]:
    """The MCP tool specs one token sees: registry exposure, then its scope, then its write mode."""
    scope = set(account.get('tools') or ())
    allowed = set(exposed_tools(account.get('writeMode')))
    specs = []
    for tool in tool_registry.all_tools():
        if tool.name in scope and tool.name in allowed:
            spec = copy.deepcopy(tool.spec())
            if tool.label:
                spec['title'] = tool.label
            specs.append(spec)
    return specs


# ---------- account rows ----------

def _status(row, now=None):
    if row['revoked_at']:
        return 'revoked'
    if not row['enabled']:
        return 'disabled'
    if not row['expires_at'] or row['expires_at'] <= (now or _now()):
        return 'expired'
    return 'active'


def _row(conn, slug, account_key, *, lock=False):
    with conn.cursor() as cur:
        cur.execute(f'SELECT {_COLUMNS} FROM projectops.agent_service_account WHERE project_slug=%s AND account_key=%s'
                    + (' FOR UPDATE' if lock else ''), (slug, account_key))
        row = cur.fetchone()
    return dict(zip([c.strip() for c in _COLUMNS.split(',')], row)) if row else None


def public(row, last_used_at=None) -> dict:
    """An account as admins and the agent API see it; never the token or its hash."""
    tools = row['tools'] if isinstance(row['tools'], list) else json.loads(row['tools'] or '[]')
    return {'accountKey': row['account_key'], 'displayName': row['display_name'], 'project': row['project_slug'],
            'tools': tools, 'writeMode': row['write_mode'], 'expiresAt': _iso(row['expires_at']),
            'createdAt': _iso(row['created_at']), 'createdBy': str(row['created_by']) if row['created_by'] else None,
            'revokedAt': _iso(row['revoked_at']), 'status': _status(row), 'lastUsedAt': _iso(last_used_at)}


def _admin(conn, me, slug):
    from project_assistant import agent_console_store as resources
    resources.authorize(conn, me, slug, admin=True)


def _bad(message, code='INVALID_REQUEST'):
    raise AgentError(400, message, code)


def _expiry(body):
    if 'expiresAt' in body and 'expiresInDays' in body:
        _bad('Send expiresAt or expiresInDays, not both.')
    now = _now()
    if 'expiresAt' in body:
        value = body['expiresAt']
        try:
            expires = dt.datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) and len(value) <= 40 else None
        except ValueError:
            expires = None
        if expires is None or expires.tzinfo is None:
            _bad('expiresAt must be an ISO 8601 time with a time zone.')
    else:
        days = body.get('expiresInDays', DEFAULT_DAYS)
        if type(days) is not int or not 1 <= days <= MAX_DAYS:
            _bad(f'expiresInDays must be an integer from 1 to {MAX_DAYS}.')
        expires = now + dt.timedelta(days=days)
    if not now < expires <= now + dt.timedelta(days=MAX_DAYS, minutes=5):
        _bad(f'A token must expire in the future and within {MAX_DAYS} days.')
    return expires


def create(conn, me, slug, body) -> dict:
    """Issue a token. The plaintext token is in this result only; the database keeps its SHA-256."""
    _admin(conn, me, slug)
    if not isinstance(body, dict) or set(body) - FIELDS:
        _bad('Unknown service-account field. Use ' + ', '.join(sorted(FIELDS)) + '.')
    key = body.get('accountKey')
    if not isinstance(key, str) or not ACCOUNT_KEY.fullmatch(key):
        _bad('accountKey must be 1-48 lower-case letters, digits, "-" or "_", starting with a letter.')
    name = body.get('displayName', key)
    if not isinstance(name, str) or not name.strip() or len(name) > 120 or '\x00' in name:
        _bad('displayName must be 1-120 characters.')
    mode = body.get('writeMode', 'propose_only')
    if mode not in WRITE_MODES:
        _bad('writeMode must be propose_only or generate.')
    tools = body.get('tools')
    if (not isinstance(tools, list) or not tools or len(tools) > 64 or any(not isinstance(t, str) for t in tools)
            or len(set(tools)) != len(tools)):
        _bad('tools must list the tools this agent may use, each once.')
    unknown = [t for t in tools if t not in exposed_tools()]
    if unknown:
        _bad('Not available to external agents: ' + ', '.join(unknown) + '. Available: ' + ', '.join(exposed_tools()) + '.')
    generation = [t for t in tools if t in tool_registry.GENERATION]
    if mode == 'propose_only' and generation:
        _bad('propose_only tokens cannot include ' + ', '.join(generation) + '; use writeMode generate.')
    expires = _expiry(body)
    from project_assistant.orchestrator import lock_project
    from project_docs import repository as repo
    lock_project(conn, slug)
    if _row(conn, slug, key):
        raise AgentError(409, 'This production already has a service account with that key.', 'ACCOUNT_EXISTS')
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    with conn.cursor() as cur:
        cur.execute('''INSERT INTO projectops.agent_service_account
                       (project_slug, account_key, display_name, tools, write_mode, expires_at, created_by)
                       VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s)''',
                    (slug, key, name.strip(), json.dumps(tools), mode, expires, me.actor_id))
        cur.execute('INSERT INTO projectops.agent_service_token(token_hash, project_slug, account_key) VALUES (%s, %s, %s)',
                    (token_hash(token), slug, key))
    repo.add_audit(conn, slug, action='service_account_create', actor_id=me.actor_id, target=key,
                   detail={'tools': tools, 'writeMode': mode, 'expiresAt': _iso(expires)})
    return {'account': public(_row(conn, slug, key)), 'token': token,
            'note': 'Store this token now; ZeroField keeps only its hash and cannot show it again.'}


def list_accounts(conn, me, slug) -> dict:
    _admin(conn, me, slug)
    with conn.cursor() as cur:
        cur.execute(f'''SELECT {", ".join("a." + c.strip() for c in _COLUMNS.split(","))}, t.last_used_at
                        FROM projectops.agent_service_account a JOIN projectops.agent_service_token t
                          ON t.project_slug=a.project_slug AND t.account_key=a.account_key
                        WHERE a.project_slug=%s ORDER BY a.created_at, a.account_key''', (slug,))
        rows = cur.fetchall()
    names = [c.strip() for c in _COLUMNS.split(',')]
    items = []
    for row in rows:
        record = dict(zip(names, row[:-1]))
        items.append({**public(record, row[-1]), 'usage': usage(conn, slug, record['account_key'])})
    return {'items': items, 'availableTools': available_tools()}


def available_tools() -> list[dict]:
    """What the token form may offer: the MCP-exposed tools in registry order, with label, category and write flags."""
    exposed = set(exposed_tools())
    return [{'name': tool.name, 'label': tool.label or tool.name, 'category': tool.category,
             'writes': tool.name in tool_registry.MUTATING, 'generation': tool.name in tool_registry.GENERATION}
            for tool in tool_registry.all_tools() if tool.name in exposed]


def revoke(conn, me, slug, account_key) -> dict:
    _admin(conn, me, slug)
    from project_docs import repository as repo
    row = _row(conn, slug, account_key, lock=True)
    if not row or not _has_token(conn, slug, account_key):
        raise AgentError(404, 'Service account not found.', 'NOT_FOUND')
    if not row['revoked_at']:
        with conn.cursor() as cur:
            cur.execute('''UPDATE projectops.agent_service_account SET enabled=FALSE, revoked_at=NOW(), revoked_by=%s
                           WHERE project_slug=%s AND account_key=%s''', (me.actor_id, slug, account_key))
        repo.add_audit(conn, slug, action='service_account_revoke', actor_id=me.actor_id, target=account_key, detail={})
    return {'account': public(_row(conn, slug, account_key))}


def _has_token(conn, slug, account_key):
    with conn.cursor() as cur:
        cur.execute('SELECT 1 FROM projectops.agent_service_token WHERE project_slug=%s AND account_key=%s', (slug, account_key))
        return cur.fetchone() is not None


def usage(conn, slug, account_key) -> dict:
    """Calls from the audit log and the generation reservations of the account's allocations."""
    with conn.cursor() as cur:
        cur.execute('''SELECT count(*), count(*) FILTER (WHERE detail->>'outcome'='ok'),
                              count(*) FILTER (WHERE detail->>'outcome'<>'ok'), max(created_at)
                       FROM projectops.audit_log WHERE project_slug=%s AND action=%s AND target=%s''',
                    (slug, CALL_ACTION, account_key))
        calls, succeeded, refused, last = cur.fetchone()
        cur.execute('''SELECT result->>'allocationId' FROM projectops.agent_service_request
                       WHERE project_slug=%s AND account_key=%s AND tool_name='request_generation' ''', (slug, account_key))
        allocations = [r[0] for r in cur.fetchall() if r[0]]
        cur.execute('''SELECT count(*), COALESCE(sum(accounted_cost_usd), 0) FROM projectops.agent_usage_reservation
                       WHERE project_slug=%s AND session_key = ANY(%s::text[])''', (slug, allocations))
        reservations, cost = cur.fetchone()
    return {'calls': calls, 'succeeded': succeeded, 'refused': refused, 'lastCallAt': _iso(last),
            'generationRequests': len(allocations), 'renderReservations': reservations, 'accountedCostUsd': str(cost)}


AUDIT_KIND = {CALL_ACTION: 'call', 'service_account_create': 'issued', 'service_account_revoke': 'revoked'}
AUDIT_DEFAULT, AUDIT_MAX = 25, 100


def audit_entries(conn, me, slug, account_key, limit=None) -> dict:
    """Newest-first audit rows of one account for its admins: every call, the issue and the revoke.

    A call row's actor is the showrunner whose authority the token runs under; an issue or revoke row's actor
    is the showrunner who did it. Argument hashes stay in the log and are never returned."""
    _admin(conn, me, slug)
    try:
        limit = AUDIT_DEFAULT if limit in (None, '') else int(limit)
    except (TypeError, ValueError):
        limit = 0
    if not 1 <= limit <= AUDIT_MAX:
        _bad(f'limit must be an integer from 1 to {AUDIT_MAX}.')
    if not _row(conn, slug, account_key) or not _has_token(conn, slug, account_key):
        raise AgentError(404, 'Service account not found.', 'NOT_FOUND')
    from project_docs import repository as repo
    with conn.cursor() as cur:
        cur.execute('''SELECT id, actor_id::text, action, detail, created_at FROM projectops.audit_log
                       WHERE project_slug=%s AND target=%s AND action = ANY(%s::text[])
                       ORDER BY created_at DESC, id DESC LIMIT %s''', (slug, account_key, list(AUDIT_KIND), limit))
        rows = cur.fetchall()
    names = repo.member_names(conn)
    items = []
    for row_id, actor, action, detail, created_at in rows:
        detail = detail if isinstance(detail, dict) else json.loads(detail or '{}')
        item = {'id': row_id, 'at': _iso(created_at), 'kind': AUDIT_KIND[action],
                'actor': {'id': actor, 'name': names.get(actor)} if actor else None, 'writeMode': detail.get('writeMode')}
        if action == CALL_ACTION:
            client = detail.get('client') if isinstance(detail.get('client'), dict) else None
            item.update({'tool': detail.get('tool'), 'outcome': detail.get('outcome'), 'code': detail.get('code'),
                         'client': client, 'requestId': detail.get('requestId'), 'resource': detail.get('resource'),
                         'proposalIds': [n for n in detail.get('proposalIds') or [] if type(n) is int],
                         'allocationId': detail.get('allocationId')})
        elif action == 'service_account_create':
            item.update({'tools': detail.get('tools') or [], 'expiresAt': detail.get('expiresAt')})
        items.append(item)
    return {'accountKey': account_key, 'limit': limit, 'items': items}


# ---------- authenticating a token ----------

def _issuer(conn, row):
    """The issuing showrunner's live authority, or None once they are no longer an enabled project admin."""
    from project_assistant import store
    from project_docs import repository as repo
    actor = str(row['created_by']) if row['created_by'] else None
    member = next((m for m in repo.active_members(conn) if m['actor_id'] == actor), None) if actor else None
    if (not member or member['role'] != 'admin' or not repo.get_project(conn, row['project_slug'])
            or not store.is_member_enabled(conn, row['project_slug'], actor)):
        return None
    return {'actor_id': member['actor_id'], 'name': member['name'], 'role': member['role']}


def audit(conn, account, tool, outcome, *, code=None, args=None, extra=None):
    from project_docs import repository as repo
    detail = {'tool': tool, 'outcome': outcome, 'code': code, 'writeMode': account.get('writeMode')}
    if args is not None:
        detail['argsSha256'] = hashlib.sha256(json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
                                              .encode('utf-8')).hexdigest()
        if isinstance(args, dict) and isinstance(args.get('request_id'), str):
            detail['requestId'] = args['request_id'][:128]
    detail.update(extra or {})
    repo.add_audit(conn, account['project'], action=CALL_ACTION, actor_id=account.get('createdBy'),
                   target=account['accountKey'], detail=detail)


def authenticate(conn, token, project=None) -> dict:
    """The active account of a token, with its issuer; refusals of a known account are audited.

    Callers commit after an AgentError too, so the refusal's audit row is kept."""
    if not isinstance(token, str) or not token.startswith(TOKEN_PREFIX) or not 20 <= len(token) <= 200:
        raise AgentError(401, 'Send a ZeroField service-account token (zfsa_...) as the Bearer credential.', 'TOKEN_INVALID')
    with conn.cursor() as cur:
        cur.execute('SELECT project_slug, account_key FROM projectops.agent_service_token WHERE token_hash=%s',
                    (token_hash(token),))
        found = cur.fetchone()
    row = _row(conn, *found) if found else None
    if not row:
        raise AgentError(401, 'The service-account token is not recognized.', 'TOKEN_INVALID')
    account = public(row)
    refusal = None
    if account['status'] != 'active':
        refusal = AgentError(401, f"The service-account token is {account['status']}. Ask a showrunner for a new one.",
                             'TOKEN_' + account['status'].upper())
    elif project is not None and project != account['project']:
        refusal = AgentError(403, 'This token belongs to another production.', 'WRONG_PROJECT')
    else:
        issuer = _issuer(conn, row)
        if issuer is None:
            refusal = AgentError(403, 'The showrunner who issued this token no longer administers the production; '
                                      'ask a showrunner for a new token.', 'ISSUER_REVOKED')
    if refusal:
        audit(conn, account, None, 'denied', code=refusal.code)
        raise refusal
    with conn.cursor() as cur:
        cur.execute('UPDATE projectops.agent_service_token SET last_used_at=NOW() WHERE token_hash=%s', (token_hash(token),))
    return {**account, 'issuer': issuer}


def rate_limit(conn, account, tool=None) -> None:
    """At most the project's rpm_per_agent calls per minute per service account (Spend & Rate Limits).

    A refused call is audited too, but does not count against the next minute."""
    with conn.cursor() as cur:
        cur.execute("SELECT rate_limits->>'rpm_per_agent' FROM projectops.agent_console_settings WHERE project_slug=%s",
                    (account['project'],))
        row = cur.fetchone()
        try:
            limit = int(row[0]) if row and row[0] is not None else DEFAULT_RPM
        except ValueError:
            limit = DEFAULT_RPM
        cur.execute('''SELECT count(*) FROM projectops.audit_log WHERE project_slug=%s AND action=%s AND target=%s
                       AND created_at > NOW() - INTERVAL '1 minute' AND detail->>'code' IS DISTINCT FROM 'RATE_LIMITED' ''',
                    (account['project'], CALL_ACTION, account['accountKey']))
        recent = cur.fetchone()[0]
    if recent >= limit:
        audit(conn, account, tool, 'denied', code='RATE_LIMITED')
        raise AgentError(429, f'Rate limit reached: at most {limit} tool calls per minute for this service account. '
                              'Wait a minute and retry.', 'RATE_LIMITED')


def policy_profile(conn, ctx) -> dict:
    """The live policy profile of a service-account call, read by agent_policy instead of an agent profile.

    Rechecked inside the tool's own transaction: a token revoked, expired or narrowed after authentication,
    or an issuer who lost admin access, leaves no tools."""
    account = ctx.service_account
    row = _row(conn, ctx.slug, account['accountKey'])
    issuer = _issuer(conn, row) if row and _status(row) == 'active' and row['project_slug'] == ctx.slug else None
    live = bool(issuer and issuer['actor_id'] == str(ctx.me.actor_id))
    names = [s['name'] for s in visible_specs(public(row))] if live else []
    return {'agent_key': ctx.agent_key, 'enabled': live, 'role_kind': 'worker', 'runtime_kind': 'service_account',
            'allowed_tools': names, 'tool_policies': {}, 'multiagent_config': {}}


# ---------- calling a tool ----------

def context(connection_factory, account):
    from project_assistant import tools
    from project_docs.service import Identity
    issuer = account['issuer']
    ctx = tools.ToolContext(connection_factory, account['project'], Identity(issuer['actor_id'], issuer['name'], issuer['role']),
                            Path(tempfile.gettempdir()), None, agent_key=AGENT_PREFIX + account['accountKey'],
                            write_mode='generate' if account['writeMode'] == 'generate' else 'proposal')
    ctx.service_account = {'project': account['project'], 'accountKey': account['accountKey'],
                           'writeMode': account['writeMode']}
    return ctx


def _probe_local_comfy() -> bool:
    from project_assistant import limb_worker
    return bool(limb_worker.probe_local_comfy_status()['online'])


_CODE = re.compile(r'^([A-Z][A-Z0-9_]{2,40})\s*[:：]')


def _error_code(text):
    """The leading code of a tool error ('POLICY_DENIED: ...'); registry argument errors carry none."""
    match = _CODE.match(text)
    if match:
        return match[1]
    return 'INVALID_ARGUMENTS' if text.startswith(('Invalid ', 'Unknown or missing ', 'Duplicate ')) else 'REFUSED'


def _client(value):
    if not isinstance(value, dict):
        return None
    return {k: value[k][:80] for k in ('name', 'version') if isinstance(value.get(k), str)} or None


def call_tool(connection_factory, account, name, args, *, client=None, card=False) -> dict:
    """Run one tool for an authenticated account; the result says whether the tool refused or failed.

    card: the client renders MCP Apps cards (SPEC_20 R34); a successful call of a tool with a card also returns the
    card's data ("card"), read after the tool's transaction and never failing the call (mcp_apps.card_for)."""
    from project_assistant import tools
    if name not in {spec['name'] for spec in visible_specs(account)}:
        _audit_call(connection_factory, account, name, 'denied', code='NOT_IN_SCOPE', args=args, client=client)
        raise AgentError(404, f'Tool {name} is not available to this service account.', 'UNKNOWN_TOOL')
    if not isinstance(args, dict):
        _audit_call(connection_factory, account, name, 'error', code='INVALID_ARGUMENTS', args=None, client=client)
        return {'text': 'Tool arguments must be a JSON object.', 'isError': True, 'code': 'INVALID_ARGUMENTS', 'images': []}
    ctx = context(connection_factory, account)
    if name in tool_registry.GENERATION:
        ctx.local_comfy_online = _probe_local_comfy()  # before the transaction: no network under the project lock
    images, extra = [], {}
    try:
        result = tools.call(ctx, name, args)
        text, images, is_error, code = str(result), list(getattr(result, 'images', []) or []), False, None
    except tools.ToolError as exc:
        text, is_error = str(exc), True
        code = _error_code(text)
    except Exception as exc:  # noqa: BLE001 - a broken tool is reported to the agent, never raised
        print(f'zerofield-mcp: tool {name} failed: {type(exc).__name__}: {exc}', flush=True)
        text, is_error, code = 'The tool failed. Try another approach or ask a crew member.', True, 'TOOL_FAILED'
    if not is_error and name in tool_registry.MUTATING:
        extra['proposalIds'] = [int(n) for n in re.findall(r'#(\d+)', text)][:20] if name not in tool_registry.GENERATION else []
        try:
            submitted = json.loads(text)
            extra.update({k: submitted[k] for k in ('allocationId', 'taskGroupId', 'replayed') if k in submitted})
        except (ValueError, TypeError):
            pass
    _audit_call(connection_factory, account, name, 'error' if is_error else 'ok', code=code, args=args, client=client, extra=extra)
    reply = {'text': text, 'isError': is_error, 'code': code, 'images': images}
    if card and not is_error:
        from project_assistant import mcp_apps
        data = mcp_apps.card_for(connection_factory, account, name, args, text)
        if data:
            reply['card'] = data
    return reply


# ---------- MCP Apps resources (SPEC_20 R34) ----------

RESOURCE_READ = 'resources/read'  # the "tool" of a resource read in the audit log and the rate limit


def visible_resources(account) -> list[dict]:
    """The card resources a token may list: those whose related tools it sees (mcp_apps.RESOURCE_TOOLS)."""
    from project_assistant import mcp_apps
    return mcp_apps.resources_for(spec['name'] for spec in visible_specs(account))


def read_resource(connection_factory, account, uri, *, client=None) -> dict:
    """Read one resource for an authenticated account: {"contents": [...]}, else AgentError 404 RESOURCE_NOT_FOUND
    (outside the token's scope or not there; both look the same). Audited like a tool call, with the resource."""
    from project_assistant import mcp_apps
    names = [spec['name'] for spec in visible_specs(account)]
    extra = {'resource': str(uri)[:300]}
    conn = connection_factory()
    try:
        contents = mcp_apps.read(conn, account, uri, names)
    except mcp_apps.NotFound as exc:
        conn.rollback()
        _audit_call(connection_factory, account, RESOURCE_READ, 'denied', code=exc.code, client=client, extra=extra)
        raise AgentError(404, 'Resource not found.', 'RESOURCE_NOT_FOUND') from None
    except Exception:
        conn.rollback()
        _audit_call(connection_factory, account, RESOURCE_READ, 'error', code='UNAVAILABLE', client=client, extra=extra)
        raise
    else:
        conn.rollback()  # read only
    finally:
        conn.close()
    _audit_call(connection_factory, account, RESOURCE_READ, 'ok', client=client, extra=extra)
    return {'contents': contents}


def _audit_call(connection_factory, account, name, outcome, *, code=None, args=None, client=None, extra=None):
    """One audit row per call in its own short transaction, after the tool's transaction ended."""
    conn = connection_factory()
    try:
        audit(conn, account, name, outcome, code=code, args=args,
              extra={**(extra or {}), **({'client': _client(client)} if _client(client) else {})})
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        print(f'zerofield-mcp: audit failed: {type(exc).__name__}: {exc}', flush=True)
    finally:
        conn.close()
