"""MCP over Streamable HTTP on the ZeroField server (SPEC_20 R33): POST /mcp, local clients only.

The JSON-RPC handling is project_assistant.mcp_protocol.Server, the same one zerofield-mcp runs on stdio, and
the backend is the agent API's service-account code in-process (agent_http.authenticate, rate_limit and
call_tool), so a token sees the same tools and gets the same results over either transport.

Transport (2026-07-28 binding, dual-era, stateless):
- One endpoint, POST only. GET and DELETE answer 405: no standalone SSE stream and no sessions; an
  Mcp-Session-Id or Last-Event-ID a client sends is ignored, and none is minted.
- Each POST carries one JSON-RPC message. A request gets one application/json response (never SSE); a
  notification or response gets 202 with no body. Batches are refused.
- 2026-07-28 requests mirror their metadata in headers: MCP-Protocol-Version must equal
  _meta["io.modelcontextprotocol/protocolVersion"], Mcp-Method the method, and Mcp-Name (plain or
  =?base64?...?=) the tool name of tools/call; a missing or different header is 400 HeaderMismatch (-32020).
  An unsupported version is 400 (-32022) and an unknown method 404 (-32601).
- Legacy requests (2025-11-25, 2025-06-18, 2025-03-26): initialize answers the negotiated version; every later
  request is framed by its MCP-Protocol-Version header, or 2025-03-26 when it has none.

Security: the client address must be loopback, the Host header must name this machine (localhost, 127.0.0.1
or [::1]) and an Origin header, when present, must be a loopback origin (DNS-rebinding protection); a request
relayed by a proxy or tunnel (Forwarded, X-Forwarded-*, X-Real-IP, Cf-*) is refused. Every request, discovery
included, needs a service-account Bearer token with the agent API's scope, expiry, revocation, audit and
per-account rate limit. Cookies are neither read nor set and no CORS headers are sent. Bodies are capped at
MAX_BODY and read with a timeout; a response over MAX_RESPONSE is replaced by an error.
"""
from __future__ import annotations

import base64
import binascii
import ipaddress
import json
import re
from urllib.parse import urlsplit

from project_assistant import mcp_protocol as protocol, service_accounts
from project_assistant.agent_registry import AgentError
from project_docs import agent_http

PATH = '/mcp'
MAX_BODY = 1024 * 1024
MAX_RESPONSE = 16 * 1024 * 1024
BODY_TIMEOUT = 30
DEFAULT_LEGACY = '2025-03-26'  # the version of a request without MCP-Protocol-Version (2025-06-18 transport rule)
PROXY_HEADERS = ('forwarded', 'x-forwarded-for', 'x-forwarded-host', 'x-forwarded-proto', 'x-real-ip')
NAMED = {'tools/call': 'name', 'prompts/get': 'name', 'resources/read': 'uri'}  # methods that mirror Mcp-Name
_HEADER_TEXT = re.compile(r'[\x20-\x7e\t]*')
_SENTINEL = re.compile(r'=\?base64\?([A-Za-z0-9+/]*={0,2})\?=')
LOCAL_MESSAGE = ('The ZeroField MCP endpoint accepts clients on this machine only: a loopback address, a local '
                 'Host and no foreign Origin.')
MISSING_TOKEN = 'Send a ZeroField service-account token (zfsa_...) as the Bearer credential.'


# ---------- local only ----------

def _loopback(value) -> bool:
    try:
        address = ipaddress.ip_address(str(value).split('%', 1)[0])
    except ValueError:
        return False
    return (getattr(address, 'ipv4_mapped', None) or address).is_loopback


def _local_authority(value) -> bool:
    """localhost, a loopback IPv4 address or [::1], with an optional port and nothing else."""
    try:
        parts = urlsplit('//' + value)
        parts.port  # noqa: B018 - raises ValueError for a malformed port
    except ValueError:
        return False
    if not parts.hostname or parts.username is not None or parts.path or parts.query or parts.fragment:
        return False
    return parts.hostname == 'localhost' or _loopback(parts.hostname)


def _local_origin(value) -> bool:
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return (parts.scheme in ('http', 'https') and parts.path in ('', '/') and not parts.query
            and not parts.fragment and _local_authority(parts.netloc))


def local_request(handler) -> bool:
    """A process on this machine talking to us directly; never a browser page elsewhere, a proxy or a tunnel."""
    headers = handler.headers
    hosts, origins = headers.get_all('Host') or [], headers.get_all('Origin') or []
    return (_loopback((handler.client_address or ('',))[0])
            and len(hosts) == 1 and _local_authority(hosts[0].strip())
            and all(_local_origin(origin.strip()) for origin in origins)
            and not any(key.lower().startswith('cf-') or key.lower() in PROXY_HEADERS for key in headers.keys()))


# ---------- the request ----------

def _accepts_json(value) -> bool:
    if not value:
        return True
    return any(part.split(';', 1)[0].strip().lower() in ('application/json', 'application/*', '*/*')
               for part in value.split(','))


def _transport_error(status, message, code=protocol.INVALID_REQUEST):
    return status, protocol.error_message(None, code, message)


def _read_message(handler):
    """The decoded JSON body, or (None, (status, JSON-RPC error)) for a request the transport refuses."""
    headers = handler.headers
    if headers.get('Transfer-Encoding'):
        return None, _transport_error(411, 'Send the message with a Content-Length.')
    try:
        length = int(headers.get('Content-Length') or '')
    except ValueError:
        return None, _transport_error(411, 'Send the message with a Content-Length.')
    if length > MAX_BODY:
        return None, _transport_error(413, f'A message may be at most {MAX_BODY} bytes.')
    if length <= 0:
        return None, _transport_error(400, 'Send one JSON-RPC message.')
    if (headers.get('Content-Type') or '').split(';', 1)[0].strip().lower() != 'application/json':
        return None, _transport_error(415, 'Send the message as application/json.')
    if not _accepts_json(headers.get('Accept')):
        return None, _transport_error(406, 'Accept application/json; this server answers with JSON.')
    connection = getattr(handler, 'connection', None)
    previous = connection.gettimeout() if connection else None
    try:
        if connection:
            connection.settimeout(BODY_TIMEOUT)
        raw = handler.rfile.read(length)
    except OSError:
        raw = b''
    finally:
        handler._body_consumed = True
        if connection:
            connection.settimeout(previous)
    if len(raw) != length:
        return None, _transport_error(400, 'The message is incomplete.')
    try:
        return json.loads(raw.decode('utf-8')), None
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None, _transport_error(400, 'Invalid JSON.', protocol.PARSE_ERROR)


def _ident(message):
    ident = message.get('id') if isinstance(message, dict) else None
    return ident if isinstance(ident, (str, int)) and not isinstance(ident, bool) else None


def _mismatch(text):
    return protocol.RpcError(protocol.HEADER_MISMATCH, 'Header mismatch: ' + text)


def _header(handler, name):
    """One header value, or None when absent; repeated or non-ASCII values are a mismatch."""
    values = handler.headers.get_all(name) or []
    if len(values) > 1:
        raise _mismatch(f'{name} is sent more than once.')
    if not values:
        return None
    if not _HEADER_TEXT.fullmatch(values[0]):
        raise _mismatch(f'{name} carries characters a header value cannot hold.')
    return values[0].strip()


def _decoded(name, value):
    match = _SENTINEL.fullmatch(value)
    if not match:
        return value
    try:
        return base64.b64decode(match[1], validate=True).decode('utf-8')
    except (binascii.Error, UnicodeDecodeError):
        raise _mismatch(f'{name} is not valid =?base64?...?= text.') from None


def era(handler, message):
    """(legacy version or None, modern) of one JSON-RPC request; header problems raise RpcError."""
    method = message['method']
    params = message.get('params') if isinstance(message.get('params'), dict) else {}
    meta = params.get('_meta') if isinstance(params.get('_meta'), dict) else {}
    header = _header(handler, 'MCP-Protocol-Version')
    if method == 'initialize':
        return None, False  # the legacy handshake negotiates from its body
    version = meta.get(protocol.META_VERSION)
    if version is None:
        version = header or DEFAULT_LEGACY
        if version in protocol.LEGACY_VERSIONS:
            return version, False
        if version in protocol.MODERN_VERSIONS:
            raise _mismatch(f'MCP-Protocol-Version is {version} but the body has no _meta["{protocol.META_VERSION}"].')
        raise protocol.unsupported_version(version)
    if header is None:
        raise _mismatch('MCP-Protocol-Version is required.')
    if header != version:
        raise _mismatch(f"MCP-Protocol-Version header value '{header}' does not match body value '{version}'.")
    if version not in protocol.MODERN_VERSIONS:
        return (version if version in protocol.LEGACY_VERSIONS else None), False
    mirrored = _header(handler, 'Mcp-Method')
    if mirrored is None:
        raise _mismatch('Mcp-Method is required.')
    if mirrored != method:
        raise _mismatch(f"Mcp-Method header value '{mirrored}' does not match body value '{method}'.")
    if method in NAMED:
        name = _header(handler, 'Mcp-Name')
        if name is None:
            raise _mismatch(f'Mcp-Name is required for {method}.')
        body = params.get(NAMED[method])
        if _decoded('Mcp-Name', name) != body:
            raise _mismatch(f'Mcp-Name does not match body value {NAMED[method]}.')
    return None, True


# ---------- the account ----------

class AccountBackend:
    """The agent API's service-account checks in-process, for one token authenticated by this request."""

    def __init__(self, account):
        self.account = account

    def list_tools(self):
        return service_accounts.visible_specs(self.account)

    def call_tool(self, name, arguments, client=None):
        try:
            agent_http.rate_limit(self.account, name)
            return agent_http.call_tool(self.account, name, arguments, client)
        except Exception as exc:  # noqa: BLE001 - the same refusals the agent API answers over HTTP
            raise _backend_error(exc) from None


def _backend_error(exc):
    if isinstance(exc, AgentError):
        return protocol.BackendError(exc.status, str(exc), exc.code)
    print(f'zerofield mcp http: {type(exc).__name__}: {exc}', flush=True)
    return protocol.BackendError(503, agent_http.UNAVAILABLE, 'UNAVAILABLE')


def _bearer(handler):
    values = handler.headers.get_all('Authorization') or []
    if len(values) != 1 or not values[0].startswith('Bearer '):
        return ''
    return values[0][7:].strip()


# ---------- the response ----------

def _encode(message):
    return json.dumps(message, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def _reply(handler, status, message=None, headers=None, *, data=None):
    drain = getattr(handler, '_drain_unread_body', None)
    if drain:
        drain()
    if data is None:
        data = b'' if message is None else _encode(message)
    handler.send_response(status)
    if data:
        handler.send_header('Content-Type', 'application/json')
    handler.send_header('Content-Length', str(len(data)))
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('X-Content-Type-Options', 'nosniff')
    for name, value in (headers or {}).items():
        handler.send_header(name, value)
    handler.end_headers()
    if data:
        handler.wfile.write(data)


def _status(reply, modern):
    code = (reply.get('error') or {}).get('code')
    if code in (protocol.PARSE_ERROR, protocol.INVALID_REQUEST, protocol.HEADER_MISMATCH, protocol.UNSUPPORTED_VERSION):
        return 400
    if code == protocol.METHOD_NOT_FOUND and modern:
        return 404
    return 200


def _refused(handler, ident, exc):
    """A token the agent API refuses: 401, 403 or 503 with the JSON-RPC error zerofield-mcp would show."""
    failure = _backend_error(exc)
    rpc = protocol.RpcError(protocol.INTERNAL_ERROR, f'ZeroField returned HTTP {failure.status}: {failure.message}')
    try:
        protocol.backend_failure(failure)  # with no tool named, every refusal raises
    except protocol.RpcError as error:
        rpc = error
    headers = {'WWW-Authenticate': 'Bearer realm="zerofield-mcp", error="invalid_token"'} if failure.status == 401 else None
    _reply(handler, failure.status, protocol.error_message(ident, rpc.code, rpc.message, rpc.data), headers)


def handle(handler, method):
    if not local_request(handler):
        _reply(handler, 403, protocol.error_message(None, protocol.LOCAL_ONLY, LOCAL_MESSAGE, {'code': 'LOCAL_ONLY'}))
        return
    if method != 'POST':
        _reply(handler, 405, protocol.error_message(None, protocol.INVALID_REQUEST, 'Send each MCP message with POST; '
               'this endpoint opens no SSE stream and keeps no sessions.'), {'Allow': 'POST'})
        return
    message, problem = _read_message(handler)
    if problem:
        _reply(handler, *problem)
        return
    if isinstance(message, list):
        _reply(handler, 400, protocol.error_message(None, protocol.INVALID_REQUEST, 'JSON-RPC batches are not supported.'))
        return
    ident, token = _ident(message), _bearer(handler)
    try:
        if not token:
            raise AgentError(401, MISSING_TOKEN, 'TOKEN_INVALID')
        account = agent_http.authenticate(token, handler.headers.get('X-ZeroField-Project') or None)
    except Exception as exc:  # noqa: BLE001
        _refused(handler, ident, exc)
        return
    legacy, modern = None, False
    if (isinstance(message, dict) and isinstance(message.get('method'), str) and ident is not None
            and message.get('jsonrpc') == '2.0'):
        try:
            legacy, modern = era(handler, message)
        except protocol.RpcError as exc:
            _reply(handler, 400, protocol.error_message(ident, exc.code, exc.message, exc.data))
            return
    reply = protocol.Server(AccountBackend(account), legacy=legacy).handle(message)
    if reply is None:
        _reply(handler, 202)
        return
    data = _encode(reply)
    if len(data) > MAX_RESPONSE:
        reply = protocol.error_message(ident, protocol.INTERNAL_ERROR, f'The result is over the {MAX_RESPONSE} byte '
                                       'response limit; ask for less, for example one page at a time.')
        data = _encode(reply)
    _reply(handler, _status(reply, modern), data=data)
