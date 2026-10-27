"""zerofield-mcp: the ZeroField MCP server for external agents over stdio (SPEC_20 R30). Standard library only.

It is a thin client of the running ZeroField server. tools/list and tools/call go over loopback HTTP to
/agent-mcp/v1 with a service-account token (SPEC_20 R31), and the server decides everything: which tools
the token sees, scope and policy checks, proposals, generation gates and the audit. This process keeps no
project state.

Protocol: MCP 2026-07-28, stateless (server/discover; each request carries its protocol version and client
capabilities in _meta), and the initialize handshake of 2025-11-25, 2025-06-18 and 2025-03-26 for older
clients. One JSON-RPC message per line on stdin and stdout; logs go to stderr.

Environment:
  ZEROFIELD_MCP_TOKEN  the zfsa_ service-account token (required)
  ZEROFIELD_URL        the ZeroField server, loopback only (default http://127.0.0.1:3020)
  ZEROFIELD_PROJECT    optional production slug; a token issued for another production is refused
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from urllib.parse import quote, urlsplit

MODERN_VERSIONS = ('2026-07-28',)
LEGACY_VERSIONS = ('2025-11-25', '2025-06-18', '2025-03-26')
SUPPORTED_VERSIONS = MODERN_VERSIONS + LEGACY_VERSIONS
META_VERSION = 'io.modelcontextprotocol/protocolVersion'
META_CAPABILITIES = 'io.modelcontextprotocol/clientCapabilities'
META_CLIENT = 'io.modelcontextprotocol/clientInfo'
META_SERVER = 'io.modelcontextprotocol/serverInfo'
DEFAULT_URL = 'http://127.0.0.1:3020'
LOCAL_HOSTS = ('127.0.0.1', 'localhost', '::1')
TOKEN_ENV, URL_ENV, PROJECT_ENV = 'ZEROFIELD_MCP_TOKEN', 'ZEROFIELD_URL', 'ZEROFIELD_PROJECT'

# JSON-RPC and MCP codes; this server's own codes sit outside the reserved -32768..-32000 range.
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603
UNSUPPORTED_VERSION = -32022
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
    def __init__(self, status, message, code=None):
        super().__init__(message)
        self.status, self.message, self.code = status, message, code


def local_url(url) -> bool:
    try:
        parts = urlsplit(url)
        return parts.scheme == 'http' and parts.hostname in LOCAL_HOSTS and not parts.username
    except ValueError:
        return False


class HttpBackend:
    """The ZeroField agent API over loopback HTTP; proxies are bypassed so the token never leaves the machine."""

    def __init__(self, url, token, project=None, *, timeout=120):
        self.url, self.token, self.project, self.timeout = url.rstrip('/'), token, project, timeout
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _request(self, method, path, body=None):
        headers = {'Authorization': 'Bearer ' + self.token, 'Accept': 'application/json'}
        if self.project:
            headers['X-ZeroField-Project'] = self.project
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(self.url + path, data=data, method=method, headers=headers)
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode('utf-8'))
            except ValueError:
                payload = {}
            raise BackendError(exc.code, str(payload.get('error') or f'HTTP {exc.code}'), payload.get('code')) from None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise BackendError(0, f'{type(exc).__name__}') from None

    def list_tools(self):
        return self._request('GET', '/agent-mcp/v1/tools').get('tools', [])

    def call_tool(self, name, arguments, client=None):
        body = {'arguments': arguments}
        if client:
            body['client'] = client
        return self._request('POST', '/agent-mcp/v1/tools/' + quote(name, safe=''), body)


def _tool(spec):
    """An MCP Tool from the server's registry spec."""
    tool = {key: spec[key] for key in ('name', 'title', 'description', 'inputSchema', 'annotations') if key in spec}
    tool.setdefault('inputSchema', {'type': 'object', 'additionalProperties': False})
    return tool


class Server:
    """Dual-era MCP request handling; state is only the legacy version negotiated by initialize."""

    def __init__(self, backend, *, config_error=None, url=DEFAULT_URL):
        self.backend, self.config_error, self.url = backend, config_error, url
        self.legacy = None

    # ---------- JSON-RPC ----------

    def handle(self, message):
        """One decoded JSON-RPC message in; the response object, or None for notifications and responses."""
        if not isinstance(message, dict):
            return _error(None, INVALID_REQUEST, 'Invalid JSON-RPC message.')
        if 'method' not in message:
            return None  # a response; this server never sends requests
        ident = message.get('id')
        if 'id' not in message:
            return None  # notification (notifications/initialized, notifications/cancelled, ...)
        if (message.get('jsonrpc') != '2.0' or not isinstance(message.get('method'), str)
                or isinstance(ident, bool) or not isinstance(ident, (str, int))):
            return _error(ident if isinstance(ident, (str, int)) and not isinstance(ident, bool) else None,
                          INVALID_REQUEST, 'Invalid JSON-RPC request.')
        params = message.get('params', {})
        try:
            if not isinstance(params, dict):
                raise RpcError(INVALID_PARAMS, 'params must be an object.')
            method = message['method']
            if method == 'initialize':
                return _result(ident, self._initialize(params), modern=False)
            modern = self._modern(params)
            return _result(ident, self._dispatch(method, params, modern), modern=modern)
        except RpcError as exc:
            return _error(ident, exc.code, exc.message, exc.data)
        except Exception as exc:  # noqa: BLE001 - one bad request never stops the server
            print(f'zerofield-mcp: {type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
            return _error(ident, INTERNAL_ERROR, 'Internal error.')

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
        raise RpcError(UNSUPPORTED_VERSION, 'Unsupported protocol version',
                       {'supported': list(SUPPORTED_VERSIONS), 'requested': version})

    # ---------- methods ----------

    def _dispatch(self, method, params, modern):
        if method == 'server/discover':
            return {'supportedVersions': list(SUPPORTED_VERSIONS), 'capabilities': {'tools': {'listChanged': False}},
                    'instructions': INSTRUCTIONS}
        if method == 'ping':
            return {}
        if method == 'tools/list':
            return {'tools': [_tool(spec) for spec in self._backend(lambda: self.backend.list_tools())]}
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
            data = {'code': exc.code} if exc.code else None
            if exc.status == 0:
                raise RpcError(SERVER_UNREACHABLE, f'ZeroField is not reachable at {self.url}. Start it with '
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

    # ---------- stdio ----------

    def serve(self, stdin, stdout):
        for raw in stdin:
            line = raw.decode('utf-8', 'replace').strip() if isinstance(raw, bytes) else raw.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                _write(stdout, _error(None, PARSE_ERROR, 'Invalid JSON.'))
                continue
            if isinstance(message, list):
                _write(stdout, _error(None, INVALID_REQUEST, 'JSON-RPC batches are not supported.'))
                continue
            response = self.handle(message)
            if response is not None:
                _write(stdout, response)


def _result(ident, result, *, modern):
    if modern:
        result = {'resultType': 'complete', **result, '_meta': {META_SERVER: SERVER_INFO}}
    return {'jsonrpc': '2.0', 'id': ident, 'result': result}


def _error(ident, code, message, data=None):
    error = {'code': code, 'message': message}
    if data is not None:
        error['data'] = data
    return {'jsonrpc': '2.0', 'id': ident, 'error': error}


def _write(stdout, message):
    stdout.write((json.dumps(message, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8'))
    stdout.flush()


def configuration(url, token):
    """A problem that keeps every tool call from working, or None."""
    if not token:
        return f'Set {TOKEN_ENV} to a ZeroField service-account token (zfsa_...); a showrunner issues one per production.'
    if not local_url(url):
        return f'{URL_ENV} must be a local http URL such as {DEFAULT_URL}; the token is never sent to another host.'
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(prog='zerofield-mcp', description='ZeroField Studio MCP server (stdio) for external agents.')
    parser.add_argument('--url', default=os.environ.get(URL_ENV) or DEFAULT_URL, help=f'ZeroField server, loopback only (default {DEFAULT_URL})')
    parser.add_argument('--project', default=os.environ.get(PROJECT_ENV) or None, help='refuse a token issued for another production')
    parser.add_argument('--version', action='version', version='zerofield-mcp ' + SERVER_INFO['version'])
    args = parser.parse_args(argv)
    token = os.environ.get(TOKEN_ENV, '').strip()
    problem = configuration(args.url, token)
    if problem:
        print('zerofield-mcp: ' + problem, file=sys.stderr, flush=True)
    server = Server(HttpBackend(args.url, token, args.project), config_error=problem, url=args.url)
    server.serve(sys.stdin.buffer, sys.stdout.buffer)
    return 0


if __name__ == '__main__':
    sys.exit(main())
