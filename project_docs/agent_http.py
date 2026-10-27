"""Service-account routes (SPEC_20 R30, R31), isolated from the document and Console dispatchers.

Admin token management (signed-in project showrunners):
  GET  /projects/api/{slug}/service-accounts                 accounts, usage and the tools a token may list
  POST /projects/api/{slug}/service-accounts                 issue a token (returned once)
  POST /projects/api/{slug}/service-accounts/{key}/revoke    revoke it
  GET  /projects/api/{slug}/service-accounts/{key}/audit     recent calls, issue and revoke of one account (?limit=1..100)

Agent API for zerofield-mcp (Bearer service-account token, loopback clients only, no browser origin):
  GET  /agent-mcp/v1/tools                                   the tools this token sees
  POST /agent-mcp/v1/tools/{name}  {"arguments": {...}}      call one; {"text", "isError", "code", "images"}
An optional X-ZeroField-Project header refuses a token issued for another production.
"""
import re
from urllib.parse import parse_qs

from project_assistant import service_accounts
from project_assistant.agent_registry import AgentError
from project_docs import service

ADMIN = re.compile(r'^/projects/api/([a-z0-9][a-z0-9-]{0,40})/service-accounts(?:/([a-z][a-z0-9_-]{0,47})/(revoke|audit))?$')
AGENT = re.compile(r'^/agent-mcp/v1/tools(?:/([a-z][a-z0-9_]{0,63}))?$')
LOOPBACK = {'127.0.0.1', '::1', '::ffff:127.0.0.1'}


def handle(handler, parsed, method):
    """Return True only for owned routes."""
    agent = AGENT.fullmatch(parsed.path)
    if agent:
        _agent(handler, agent[1], method)
        return True
    admin = ADMIN.fullmatch(parsed.path)
    if admin:
        _admin(handler, *admin.groups(), method, parsed.query)
        return True
    return False


def _fail(handler, exc):
    if isinstance(exc, AgentError):
        handler.send_json(exc.status, {'error': str(exc), 'code': exc.code})
    else:
        print(f'service accounts: {type(exc).__name__}: {exc}', flush=True)
        handler.send_json(503, {'error': 'Service accounts are temporarily unavailable.', 'code': 'UNAVAILABLE'})


def _admin(handler, slug, account_key, action, method, query=''):
    from project_docs import http
    identity, problem = handler.project_docs_identity()
    me = service.identity_from(identity) if not problem else None
    if not me:
        handler.send_json(401, {'error': 'Sign in with an active crew account.', 'code': 'AUTH_REQUIRED'})
        return
    if method not in {'revoke': ('POST',), 'audit': ('GET',)}.get(action, ('GET', 'POST')):
        handler.send_json(405, {'error': 'Unsupported method.'})
        return
    body = {}
    if method == 'POST':
        refused = http._write_allowed(handler)
        if refused:
            handler.send_json(403, {'error': refused, 'code': 'POLICY_DENIED'})
            return
        body, error = http._json_body(handler)
        if error:
            handler.send_json(*error)
            return
    conn = http.open_connection()
    try:
        http._ensure_schema(conn)
        if action == 'audit':
            payload = service_accounts.audit_entries(conn, me, slug, account_key, (parse_qs(query).get('limit') or [None])[0])
        elif action:
            payload = service_accounts.revoke(conn, me, slug, account_key)
        elif method == 'POST':
            payload = service_accounts.create(conn, me, slug, body)
        else:
            payload = service_accounts.list_accounts(conn, me, slug)
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        _fail(handler, exc)
        return
    finally:
        conn.close()
    handler.send_json(200, payload)


def _local_only(handler):
    """The agent API serves processes on this machine, never a browser page or a tunnel."""
    address = (handler.client_address or ('',))[0]
    return (address not in LOOPBACK or handler.headers.get('Origin')
            or any(key.lower().startswith('cf-') for key in handler.headers.keys()))


def _agent(handler, name, method):
    from project_docs import http
    if _local_only(handler):
        handler.send_json(403, {'error': 'The agent API accepts local zerofield-mcp clients only.', 'code': 'LOCAL_ONLY'})
        return
    if method != ('POST' if name else 'GET'):
        handler.send_json(405, {'error': 'Unsupported method.'})
        return
    bearer = handler.headers.get('Authorization', '')
    token = bearer[7:].strip() if bearer.startswith('Bearer ') else ''
    project = handler.headers.get('X-ZeroField-Project') or None
    body = {}
    if name:
        body, error = http._json_body(handler)
        if error:
            handler.send_json(*error)
            return
    conn = http.open_connection()
    try:
        http._ensure_schema(conn)
        account = service_accounts.authenticate(conn, token, project)
        if name:
            service_accounts.rate_limit(conn, account, name)
        conn.commit()
    except Exception as exc:  # noqa: BLE001 - commit keeps the audit row of a refused known account
        if isinstance(exc, AgentError):
            conn.commit()
        else:
            conn.rollback()
        _fail(handler, exc)
        return
    finally:
        conn.close()
    if not name:
        handler.send_json(200, {'project': account['project'], 'account': account['accountKey'],
                                'writeMode': account['writeMode'], 'expiresAt': account['expiresAt'],
                                'tools': service_accounts.visible_specs(account)})
        return
    try:
        payload = service_accounts.call_tool(http.open_connection, account, name, body.get('arguments', {}),
                                             client=body.get('client'))
    except Exception as exc:  # noqa: BLE001
        _fail(handler, exc)
        return
    handler.send_json(200, payload)
