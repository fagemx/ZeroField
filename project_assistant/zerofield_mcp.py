"""zerofield-mcp: the ZeroField MCP server for external agents over stdio (SPEC_20 R30). Standard library only.

It is a thin client of the running ZeroField server. tools/list and tools/call go over loopback HTTP to
/agent-mcp/v1 with a service-account token (SPEC_20 R31), and the server decides everything: which tools
the token sees, scope and policy checks, proposals, generation gates and the audit. This process keeps no
project state.

Protocol: MCP 2026-07-28, stateless (server/discover; each request carries its protocol version and client
capabilities in _meta), and the initialize handshake of 2025-11-25, 2025-06-18 and 2025-03-26 for older
clients. The JSON-RPC handling lives in project_assistant.mcp_protocol, shared with the server's Streamable
HTTP endpoint (POST /mcp, SPEC_20 R33). One JSON-RPC message per line on stdin and stdout; logs go to stderr.
MCP Apps cards (SPEC_20 R34, project_assistant.mcp_apps) work in both eras here: resources come from
/agent-mcp/v1/resources with the same token, and a card's "Open in ZeroField" link is built on ZEROFIELD_URL.

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

from project_assistant import mcp_protocol
from project_assistant.mcp_protocol import (  # noqa: F401 - re-exported for callers of the stdio module
    HEADER_MISMATCH, INSTRUCTIONS, INTERNAL_ERROR, INVALID_PARAMS, INVALID_REQUEST, LEGACY_VERSIONS, LOCAL_ONLY,
    META_CAPABILITIES, META_CLIENT, META_SERVER, META_VERSION, METHOD_NOT_FOUND, MODERN_VERSIONS, PARSE_ERROR,
    SERVER_INFO, SERVER_UNREACHABLE, SUPPORTED_VERSIONS, TOKEN_REFUSED, UNSUPPORTED_VERSION, BackendError, RpcError,
    error_message as _error, result_message as _result, tool_spec as _tool)

DEFAULT_URL = 'http://127.0.0.1:3020'
LOCAL_HOSTS = ('127.0.0.1', 'localhost', '::1')
TOKEN_ENV, URL_ENV, PROJECT_ENV = 'ZEROFIELD_MCP_TOKEN', 'ZEROFIELD_URL', 'ZEROFIELD_PROJECT'


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

    def call_tool(self, name, arguments, client=None, card=False):
        body = {'arguments': arguments}
        if client:
            body['client'] = client
        if card:
            body['card'] = True  # an MCP Apps client: the server adds the card's data (SPEC_20 R34)
        return self._request('POST', '/agent-mcp/v1/tools/' + quote(name, safe=''), body)

    def list_resources(self):
        return self._request('GET', '/agent-mcp/v1/resources').get('resources', [])

    def read_resource(self, uri, client=None):
        body = {'uri': uri}
        if client:
            body['client'] = client
        return self._request('POST', '/agent-mcp/v1/resources/read', body)


class Server(mcp_protocol.Server):
    """The shared dual-era MCP handling (project_assistant.mcp_protocol), framed as JSON lines on stdio."""

    def __init__(self, backend, *, config_error=None, url=DEFAULT_URL):
        super().__init__(backend, config_error=config_error, url=url)

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
