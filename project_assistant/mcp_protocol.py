"""The ZeroField MCP protocol layer, shared by zerofield-mcp (stdio, SPEC_20 R30) and POST /mcp (Streamable HTTP, R33).

Standard library only. A backend answers list_tools() and call_tool(name, arguments, client) and raises
BackendError with the agent API's HTTP status, message and code; the stdio client reaches the agent API
over loopback HTTP, the HTTP endpoint calls the same service-account functions in-process. Either way the
JSON-RPC handling, the tool list and the call results come from this module.

Protocol: MCP 2026-07-28, stateless (server/discover; each request carries its protocol version and client
capabilities in _meta), and the initialize handshake of 2025-11-25, 2025-06-18 and 2025-03-26 for older
clients.
"""
from __future__ import annotations

import json
import sys

MODERN_VERSIONS = ('2026-07-28',)
LEGACY_VERSIONS = ('2025-11-25', '2025-06-18', '2025-03-26')
SUPPORTED_VERSIONS = MODERN_VERSIONS + LEGACY_VERSIONS
META_VERSION = 'io.modelcontextprotocol/protocolVersion'
META_CAPABILITIES = 'io.modelcontextprotocol/clientCapabilities'
META_CLIENT = 'io.modelcontextprotocol/clientInfo'
META_SERVER = 'io.modelcontextprotocol/serverInfo'

# JSON-RPC and MCP codes; this server's own codes sit outside the reserved -32768..-32000 range.
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603
HEADER_MISMATCH, UNSUPPORTED_VERSION = -32020, -32022
TOKEN_REFUSED, SERVER_UNREACHABLE, LOCAL_ONLY = -31001, -31002, -31003

INSTRUCTIONS = ('ZeroField Studio tools for one production. Edits are proposals that a crew member reviews and '
                'adopts in ZeroField. request_generation, when your token allows it, submits only free local '
                'open-weights renders, whose takes also wait for review; paid generation is refused. Call '
                'get_workflow to read the crew workflow guides before planning.')


def _version():
    try:
        from importlib.metadata import version
        return version('openbench')
    except Exception:  # noqa: BLE001 - a source checkout without installed metadata
        return '0.0.0'


SERVER_INFO = {'name': 'zerofield-mcp', 'title': 'ZeroField Studio', 'version': _version()}


class RpcError(Exception):
    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


class BackendError(Exception):
    """An agent API refusal: its HTTP status (0 when unreachable), message and code."""

    def __init__(self, status, message, code=None):
        super().__init__(message)
        self.status, self.message, self.code = status, message, code


def tool_spec(spec):
    """An MCP Tool from the server's registry spec."""
    tool = {key: spec[key] for key in ('name', 'title', 'description', 'inputSchema', 'annotations') if key in spec}
    tool.setdefault('inputSchema', {'type': 'object', 'additionalProperties': False})
    return tool


def backend_failure(exc, *, tool=None, url=None):
    """The MCP outcome of an agent API refusal: a tool result the model can act on, or a raised RpcError."""
    data = {'code': exc.code} if exc.code else None
    if exc.status == 0:
        raise RpcError(SERVER_UNREACHABLE, f'ZeroField is not reachable at {url}. Start it with '
                       'run_studio.py and check ZEROFIELD_URL.') from None
    if exc.status == 401 or (exc.status == 403 and exc.code != 'LOCAL_ONLY'):
        raise RpcError(TOKEN_REFUSED, 'ZeroField refused the service-account token: ' + exc.message, data) from None
    if exc.status == 403:
        raise RpcError(LOCAL_ONLY, exc.message, data) from None
    if exc.status == 404 and tool:
        raise RpcError(INVALID_PARAMS, f'Unknown tool: {tool}', data) from None
    if exc.status == 429 and tool:
        return {'text': exc.message, 'isError': True}  # the model can wait and retry
    raise RpcError(INTERNAL_ERROR, f'ZeroField returned HTTP {exc.status}: {exc.message}', data) from None


class Server:
    """Dual-era MCP request handling; state is only the legacy version negotiated by initialize.

    A transport without a connection (Streamable HTTP) passes the legacy version of each request instead."""

    def __init__(self, backend, *, config_error=None, url=None, legacy=None):
        self.backend, self.config_error, self.url = backend, config_error, url
        self.legacy = legacy if legacy in LEGACY_VERSIONS else None

    # ---------- JSON-RPC ----------

    def handle(self, message):
        """One decoded JSON-RPC message in; the response object, or None for notifications and responses."""
        if not isinstance(message, dict):
            return error_message(None, INVALID_REQUEST, 'Invalid JSON-RPC message.')
        if 'method' not in message:
            return None  # a response; this server never sends requests
        ident = message.get('id')
        if 'id' not in message:
            return None  # notification (notifications/initialized, notifications/cancelled, ...)
        if (message.get('jsonrpc') != '2.0' or not isinstance(message.get('method'), str)
                or isinstance(ident, bool) or not isinstance(ident, (str, int))):
            return error_message(ident if isinstance(ident, (str, int)) and not isinstance(ident, bool) else None,
                                 INVALID_REQUEST, 'Invalid JSON-RPC request.')
        params = message.get('params', {})
        try:
            if not isinstance(params, dict):
                raise RpcError(INVALID_PARAMS, 'params must be an object.')
            method = message['method']
            if method == 'initialize':
                return result_message(ident, self._initialize(params), modern=False)
            modern = self._modern(params)
            return result_message(ident, self._dispatch(method, params, modern), modern=modern)
        except RpcError as exc:
            return error_message(ident, exc.code, exc.message, exc.data)
        except Exception as exc:  # noqa: BLE001 - one bad request never stops the server
            print(f'zerofield-mcp: {type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
            return error_message(ident, INTERNAL_ERROR, 'Internal error.')

    def _initialize(self, params):
        requested = params.get('protocolVersion')
        self.legacy = requested if requested in LEGACY_VERSIONS else LEGACY_VERSIONS[0]
        return {'protocolVersion': self.legacy, 'capabilities': {'tools': {'listChanged': False}},
                'serverInfo': SERVER_INFO, 'instructions': INSTRUCTIONS}

    def _modern(self, params):
        """True for a 2026-07-28 request (per-request _meta), False for a request after initialize."""
        meta = params.get('_meta') if isinstance(params.get('_meta'), dict) else {}
        version = meta.get(META_VERSION)
        if version is None:
            if self.legacy:
                return False
            raise RpcError(INVALID_PARAMS, f'Missing _meta["{META_VERSION}"]: send it with every request '
                           f'(2026-07-28), or call initialize first (2025-11-25 and earlier).',
                           {'supported': list(SUPPORTED_VERSIONS)})
        if version in MODERN_VERSIONS:
            if not isinstance(meta.get(META_CAPABILITIES), dict):
                raise RpcError(INVALID_PARAMS, f'Missing _meta["{META_CAPABILITIES}"].')
            return True
        if self.legacy and version == self.legacy:
            return False
        raise unsupported_version(version)

    # ---------- methods ----------

    def _dispatch(self, method, params, modern):
        if method == 'server/discover':
            return {'supportedVersions': list(SUPPORTED_VERSIONS), 'capabilities': {'tools': {'listChanged': False}},
                    'instructions': INSTRUCTIONS}
        if method == 'ping':
            return {}
        if method == 'tools/list':
            return {'tools': [tool_spec(spec) for spec in self._backend(lambda: self.backend.list_tools())]}
        if method == 'tools/call':
            return self._call(params, modern)
        raise RpcError(METHOD_NOT_FOUND, f'Method not found: {method}')

    def _call(self, params, modern):
        name, arguments = params.get('name'), params.get('arguments', {})
        if not isinstance(name, str) or not name:
            raise RpcError(INVALID_PARAMS, 'tools/call needs a tool name.')
        if not isinstance(arguments, dict):
            raise RpcError(INVALID_PARAMS, 'tools/call arguments must be an object.')
        meta = params.get('_meta') if isinstance(params.get('_meta'), dict) else {}
        client = meta.get(META_CLIENT) if modern and isinstance(meta.get(META_CLIENT), dict) else None
        reply = self._backend(lambda: self.backend.call_tool(name, arguments, client), tool=name)
        text = str(reply.get('text', ''))
        content = [{'type': 'text', 'text': text}]
        for image in reply.get('images') or []:
            if isinstance(image, str) and image.startswith('data:image/png;base64,'):
                content.append({'type': 'image', 'mimeType': 'image/png', 'data': image.split(',', 1)[1]})
        result = {'content': content, 'isError': bool(reply.get('isError'))}
        if not result['isError']:
            try:
                structured = json.loads(text)
            except ValueError:
                structured = None
            if isinstance(structured, dict):
                result['structuredContent'] = structured
        return result

    def _backend(self, operation, tool=None):
        if self.config_error:
            raise RpcError(TOKEN_REFUSED, self.config_error)
        try:
            return operation()
        except BackendError as exc:
            return backend_failure(exc, tool=tool, url=self.url)


def unsupported_version(requested):
    return RpcError(UNSUPPORTED_VERSION, 'Unsupported protocol version',
                    {'supported': list(SUPPORTED_VERSIONS), 'requested': requested})


def result_message(ident, result, *, modern):
    if modern:
        result = {'resultType': 'complete', **result, '_meta': {META_SERVER: SERVER_INFO}}
    return {'jsonrpc': '2.0', 'id': ident, 'result': result}


def error_message(ident, code, message, data=None):
    error = {'code': code, 'message': message}
    if data is not None:
        error['data'] = data
    return {'jsonrpc': '2.0', 'id': ident, 'error': error}
