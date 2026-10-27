"""Service-account routes (SPEC_20 R30, R31), isolated from the document and Console dispatchers.

Admin token management (signed-in project showrunners):
  GET  /projects/api/{slug}/service-accounts                 accounts, usage and the tools a token may list
  POST /projects/api/{slug}/service-accounts                 issue a token (returned once)
  POST /projects/api/{slug}/service-accounts/{key}/revoke    revoke it
  GET  /projects/api/{slug}/service-accounts/{key}/audit     recent calls, issue and revoke of one account (?limit=1..100)

Agent API for zerofield-mcp (Bearer service-account token, loopback clients only, no browser origin):
  GET  /agent-mcp/v1/tools                                   the tools this token sees
  POST /agent-mcp/v1/tools/{name}  {"arguments": {...}}      call one; {"text", "isError", "code", "images"}
       with "card": true (an MCP Apps client, SPEC_20 R34) a tool with a card also returns "card", its data
  GET  /agent-mcp/v1/resources                               the MCP Apps card resources this token may list
  POST /agent-mcp/v1/resources/read  {"uri": "..."}          read one: {"contents": [...]}, else 404 RESOURCE_NOT_FOUND;
       audited and rate limited like a tool call
An optional X-ZeroField-Project header refuses a token issued for another production.

MCP over Streamable HTTP (SPEC_20 R33, project_docs.mcp_http):
  POST /mcp                                                  one JSON-RPC message; the same tokens and checks
"""
import re
from urllib.parse import parse_qs

from project_assistant import service_accounts
from project_assistant.agent_registry import AgentError
from project_docs import service

ADMIN = re.compile(r'^/projects/api/([a-z0-9][a-z0-9-]{0,40})/service-accounts(?:/([a-z][a-z0-9_-]{0,47})/(revoke|audit))?$')
AGENT = re.compile(r'^/agent-mcp/v1/tools(?:/([a-z][a-z0-9_]{0,63}))?$')
RESOURCES = re.compile(r'^/agent-mcp/v1/resources(/read)?$')
LOOPBACK = {'127.0.0.1', '::1', '::ffff:127.0.0.1'}
UNAVAILABLE = 'Service accounts are temporarily unavailable.'


def handle(handler, parsed, method):
    """Return True only for owned routes."""
    from project_docs import mcp_http
    if parsed.path == mcp_http.PATH:
        mcp_http.handle(handler, method)
        return True
    agent = AGENT.fullmatch(parsed.path)
    if agent:
        _agent(handler, agent[1], method)
        return True
    resources = RESOURCES.fullmatch(parsed.path)
    if resources:
        _resources(handler, bool(resources[1]), method)
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
        handler.send_json(503, {'error': UNAVAILABLE, 'code': 'UNAVAILABLE'})


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
            payload = {**service_accounts.list_accounts(conn, me, slug), 'connect': _connect(handler)}
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        _fail(handler, exc)
        return
    finally:
        conn.close()
    handler.send_json(200, payload)


def _connect(handler):
    """Where an agent on this machine reaches MCP over Streamable HTTP (R33), for the R41 setup snippet."""
    host, port = (getattr(getattr(handler, 'server', None), 'server_address', None) or ('', 0))[:2]
    return {'http': {'url': f"http://{'[::1]' if host == '::1' else '127.0.0.1'}:{port}/mcp"}} if port else {}


def _local_only(handler):
    """The agent API serves processes on this machine, never a browser page or a tunnel."""
    address = (handler.client_address or ('',))[0]
    return (address not in LOOPBACK or handler.headers.get('Origin')
            or any(key.lower().startswith('cf-') for key in handler.headers.keys()))


def _refusals_kept(work):
    """Run work(conn) in one transaction; a refusal (AgentError) commits too, so its audit row is kept."""
    from project_docs import http
    conn = http.open_connection()
    try:
        result = work(conn)
        conn.commit()
        return result
    except AgentError:
        conn.commit()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def authenticate(token, project=None, tool=None):
    """The active account of a token, rate limited when it calls a tool; raises AgentError on a refusal.

    Shared by the agent API and POST /mcp."""
    from project_docs import http

    def work(conn):
        http._ensure_schema(conn)
        account = service_accounts.authenticate(conn, token, project)
        if tool:
            service_accounts.rate_limit(conn, account, tool)
        return account
    return _refusals_kept(work)


def rate_limit(account, tool):
    """The per-account tool-call limit for a request authenticated earlier (POST /mcp)."""
    _refusals_kept(lambda conn: service_accounts.rate_limit(conn, account, tool))


def call_tool(account, name, arguments, client=None, card=False):
    from project_docs import http
    return service_accounts.call_tool(http.open_connection, account, name, arguments, client=client, card=card)


def read_resource(account, uri, client=None):
    from project_docs import http
    return service_accounts.read_resource(http.open_connection, account, uri, client=client)


def _resources(handler, read, method):
    """GET /agent-mcp/v1/resources and POST /agent-mcp/v1/resources/read (SPEC_20 R34), same checks as the tools."""
    from project_docs import http
    if _local_only(handler):
        handler.send_json(403, {'error': 'The agent API accepts local zerofield-mcp clients only.', 'code': 'LOCAL_ONLY'})
        return
    if method != ('POST' if read else 'GET'):
        handler.send_json(405, {'error': 'Unsupported method.'})
        return
    bearer = handler.headers.get('Authorization', '')
    token = bearer[7:].strip() if bearer.startswith('Bearer ') else ''
    project = handler.headers.get('X-ZeroField-Project') or None
    body = {}
    if read:
        body, error = http._json_body(handler)
        if error:
            handler.send_json(*error)
            return
    try:
        account = authenticate(token, project, service_accounts.RESOURCE_READ if read else None)
    except Exception as exc:  # noqa: BLE001
        _fail(handler, exc)
        return
    if not read:
        handler.send_json(200, {'resources': service_accounts.visible_resources(account)})
        return
    uri = body.get('uri') if isinstance(body, dict) else None
    if not isinstance(uri, str) or not uri or len(uri) > 2048:
        handler.send_json(400, {'error': 'Send {"uri": "..."} with the resource to read.', 'code': 'INVALID_REQUEST'})
        return
    try:
        payload = read_resource(account, uri, body.get('client'))
    except Exception as exc:  # noqa: BLE001
        _fail(handler, exc)
        return
    handler.send_json(200, payload)


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
    try:
        account = authenticate(token, project, name)
    except Exception as exc:  # noqa: BLE001
        _fail(handler, exc)
        return
    if not name:
        handler.send_json(200, {'project': account['project'], 'account': account['accountKey'],
                                'writeMode': account['writeMode'], 'expiresAt': account['expiresAt'],
                                'tools': service_accounts.visible_specs(account)})
        return
    try:
        payload = call_tool(account, name, body.get('arguments', {}), client=body.get('client'), card=body.get('card') is True)
    except Exception as exc:  # noqa: BLE001
        _fail(handler, exc)
        return
    handler.send_json(200, payload)
