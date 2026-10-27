"""SPEC_20 R33: MCP over Streamable HTTP (POST /mcp), loopback only, service-account tokens.

Header and local-only checks are unit tests. The HTTP tests start the real request handler against the
disposable PostgreSQL in OPENBENCH_TEST_DB_URI and compare every answer with zerofield-mcp (stdio) for the same
token. No model, GPU or ComfyUI is called.
"""
import base64
import hashlib
import json
import os
import types
import unittest
from http.client import HTTPConnection, HTTPMessage
from unittest.mock import patch

from project_assistant import mcp_protocol as protocol, zerofield_mcp as mcp
from project_docs import mcp_http

MODERN = '2026-07-28'
CLIENT = {'name': 'http-test', 'version': '1'}
META = {protocol.META_VERSION: MODERN, protocol.META_CAPABILITIES: {}, protocol.META_CLIENT: CLIENT}


def rpc(method, ident=1, meta=META, **params):
    if meta is not None:
        params['_meta'] = meta
    return {'jsonrpc': '2.0', 'id': ident, 'method': method, 'params': params}


def mirrored(message):
    """The request metadata headers a 2026-07-28 client mirrors from the body."""
    params = message.get('params') or {}
    headers = {'MCP-Protocol-Version': params.get('_meta', {}).get(protocol.META_VERSION, MODERN),
               'Mcp-Method': message['method']}
    if message['method'] == 'tools/call':
        headers['Mcp-Name'] = params.get('name')
    return headers


def fake_handler(address='127.0.0.1', headers=(('Host', '127.0.0.1:3020'),)):
    message = HTTPMessage()
    for name, value in headers:
        message[name] = value
    return types.SimpleNamespace(client_address=(address, 50000), headers=message)


class LocalOnlyTests(unittest.TestCase):
    def test_loopback_address_host_and_origin(self):
        self.assertTrue(mcp_http.local_request(fake_handler()))
        for address in ('::1', '::ffff:127.0.0.1', '127.0.0.2'):
            with self.subTest(address=address):
                self.assertTrue(mcp_http.local_request(fake_handler(address)))
        for address in ('192.168.1.5', '10.0.0.1', '::ffff:10.0.0.1', '', 'not-an-ip'):
            with self.subTest(address=address):
                self.assertFalse(mcp_http.local_request(fake_handler(address)))
        for host in ('localhost', 'localhost:3020', 'LOCALHOST:3020', '[::1]:3020', '127.0.0.1'):
            with self.subTest(host=host):
                self.assertTrue(mcp_http.local_request(fake_handler(headers=[('Host', host)])))
        for host in ('evil.example', 'evil.example:3020', '127.0.0.1.evil.example', '0.0.0.0:3020', '192.168.1.5:3020',
                     'user@127.0.0.1:3020', '127.0.0.1:3020/x', '127.0.0.1:port', ''):
            with self.subTest(host=host):
                self.assertFalse(mcp_http.local_request(fake_handler(headers=[('Host', host)])))
        self.assertFalse(mcp_http.local_request(fake_handler(headers=[])))
        self.assertFalse(mcp_http.local_request(fake_handler(headers=[('Host', '127.0.0.1'), ('Host', 'evil.example')])))
        host = ('Host', '127.0.0.1:3020')
        for origin in ('http://localhost:6274', 'http://127.0.0.1:3020', 'https://[::1]:8443', 'http://localhost'):
            with self.subTest(origin=origin):
                self.assertTrue(mcp_http.local_request(fake_handler(headers=[host, ('Origin', origin)])))
        for origin in ('http://evil.example', 'null', 'file://', 'http://127.0.0.1.evil.example', 'ftp://localhost',
                       'http://localhost:3020/path', 'http://192.168.1.5:3020'):
            with self.subTest(origin=origin):
                self.assertFalse(mcp_http.local_request(fake_handler(headers=[host, ('Origin', origin)])))
        for name, value in (('X-Forwarded-For', '1.2.3.4'), ('Forwarded', 'for=1.2.3.4'), ('X-Real-IP', '1.2.3.4'),
                            ('Cf-Connecting-Ip', '1.2.3.4'), ('CF-Ray', 'abc')):
            with self.subTest(header=name):
                self.assertFalse(mcp_http.local_request(fake_handler(headers=[host, (name, value)])))


class HeaderTests(unittest.TestCase):
    def era(self, message, *headers):
        return mcp_http.era(fake_handler(headers=list(headers)), message)

    def mismatch(self, message, *headers):
        with self.assertRaises(protocol.RpcError) as caught:
            self.era(message, *headers)
        return caught.exception

    def test_modern_requests_mirror_version_method_and_name(self):
        call = rpc('tools/call', name='read_page', arguments={})
        version, method, name = ('MCP-Protocol-Version', MODERN), ('Mcp-Method', 'tools/call'), ('Mcp-Name', 'read_page')
        self.assertEqual(self.era(call, version, method, name), (None, True))
        self.assertEqual(self.era(call, ('mcp-protocol-version', MODERN), ('MCP-METHOD', 'tools/call'), ('mcp-name', 'read_page')),
                         (None, True))  # header names are case-insensitive
        encoded = '=?base64?' + base64.b64encode('read_page'.encode()).decode() + '?='
        self.assertEqual(self.era(call, version, method, ('Mcp-Name', encoded)), (None, True))
        self.assertEqual(self.era(rpc('tools/list'), version, ('Mcp-Method', 'tools/list')), (None, True))
        cases = [((method, name), 'MCP-Protocol-Version is required'),
                 ((('MCP-Protocol-Version', '2025-11-25'), method, name), "does not match body value '2026-07-28'"),
                 ((version, name), 'Mcp-Method is required'),
                 ((version, ('Mcp-Method', 'tools/list'), name), "Mcp-Method header value 'tools/list'"),
                 ((version, method), 'Mcp-Name is required'),
                 ((version, method, ('Mcp-Name', 'read_shot')), 'Mcp-Name does not match'),
                 ((version, method, ('Mcp-Name', '=?base64?!!!?=')), 'Mcp-Name does not match'),
                 ((version, method, ('Mcp-Name', '=?base64?cmVhZA?=')), 'not valid'),
                 ((version, version, method, name), 'more than once'),
                 ((version, method, ('Mcp-Name', 'read_pagé')), 'cannot hold')]
        for headers, text in cases:
            with self.subTest(headers=headers):
                error = self.mismatch(call, *headers)
                self.assertEqual(error.code, protocol.HEADER_MISMATCH)
                self.assertIn(text, error.message)
        unsupported = rpc('tools/list', meta={**META, protocol.META_VERSION: '1900-01-01'})
        self.assertEqual(self.era(unsupported, ('MCP-Protocol-Version', '1900-01-01')), (None, False))  # the server answers -32022

    def test_legacy_requests_use_the_header_or_2025_03_26(self):
        listing = {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}
        self.assertEqual(self.era(listing), ('2025-03-26', False))
        for version in protocol.LEGACY_VERSIONS:
            with self.subTest(version=version):
                self.assertEqual(self.era(listing, ('MCP-Protocol-Version', version)), (version, False))
        initialize = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}}
        self.assertEqual(self.era(initialize), (None, False))
        self.assertEqual(self.mismatch(listing, ('MCP-Protocol-Version', MODERN)).code, protocol.HEADER_MISMATCH)
        unknown = self.mismatch(listing, ('MCP-Protocol-Version', '2024-11-05'))
        self.assertEqual((unknown.code, unknown.data['requested']), (protocol.UNSUPPORTED_VERSION, '2024-11-05'))
        self.assertIn(MODERN, unknown.data['supported'])

    def test_stdio_module_keeps_its_names(self):
        self.assertIs(mcp.BackendError, protocol.BackendError)
        self.assertTrue(issubclass(mcp.Server, protocol.Server))
        self.assertEqual((mcp.META_VERSION, mcp.SUPPORTED_VERSIONS), (protocol.META_VERSION, protocol.SUPPORTED_VERSIONS))


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'set OPENBENCH_TEST_DB_URI')
class StreamableHttpTests(unittest.TestCase):
    TOOLS = ['list_pages', 'read_page', 'propose_table_edit', 'get_workflow']

    def setUp(self):
        import test_product_http as product_fixture
        self.fixture = product_fixture.ProductHTTPTests
        self.fixture.setUp(self)

    def tearDown(self):
        self.fixture.tearDown(self)

    def request(self, *args, **kwargs):
        return self.fixture.request(self, *args, **kwargs)

    def issue(self, key='claude-code', tools=None, mode='propose_only'):
        body = {'accountKey': key, 'tools': tools or self.TOOLS, 'writeMode': mode, 'expiresInDays': 3}
        code, issued, _ = self.request(f'/projects/api/{self.slug}/service-accounts', method='POST', data=body)
        self.assertEqual(code, 200, issued)
        return issued['token']

    def stdio(self, token, project=None):
        return mcp.Server(mcp.HttpBackend(f'http://127.0.0.1:{self.server.server_port}', token, project, timeout=30))

    def http(self, message=None, token=None, *, headers=None, method='POST', raw=None, modern=None):
        """POST one message to /mcp: (status, decoded body or b'', response headers)."""
        sent = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
        if token:
            sent['Authorization'] = 'Bearer ' + token
        if message is not None and raw is None:
            raw = json.dumps(message).encode()
            if modern is None:
                modern = '_meta' in (message.get('params') or {})
            if modern:
                sent.update(mirrored(message))
        sent.update(headers or {})
        connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=30)
        try:
            connection.request(method, '/mcp', body=raw, headers={k: v for k, v in sent.items() if v is not None})
            response = connection.getresponse()
            payload, response_headers = response.read(), {k.lower(): v for k, v in response.getheaders()}
        finally:
            connection.close()
        if payload and response_headers.get('content-type') == 'application/json':
            payload = json.loads(payload)
        return response.status, payload, response_headers

    def audits(self, key):
        with self.conn.cursor() as cur:
            cur.execute('''SELECT detail FROM projectops.audit_log WHERE project_slug=%s AND action='service_account_call'
                           AND target=%s ORDER BY id''', (self.slug, key))
            rows = [r[0] for r in cur.fetchall()]
        self.conn.commit()
        return rows

    def test_both_eras_match_stdio_for_the_same_token(self):
        token = self.issue()
        stdio = self.stdio(token, self.slug)
        project = {'X-ZeroField-Project': self.slug}
        modern = [rpc('server/discover', 1), rpc('ping', 2), rpc('tools/list', 3),
                  rpc('tools/call', 4, name='read_page', arguments={'key': 'shots'}),
                  rpc('tools/call', 5, name='get_workflow', arguments={'name': 'shot-beats'}),
                  rpc('tools/call', 6, name='read_page', arguments={'tab': 'shots'}),
                  rpc('tools/call', 7, name='spawn_agent', arguments={}),
                  rpc('tools/call', 8, name='read_page', arguments=['shots'])]
        for message in modern:
            with self.subTest(method=message['method'], id=message['id']):
                status, reply, headers = self.http(message, token, headers=project)
                self.assertEqual(reply, stdio.handle(message))
                self.assertEqual(status, 200)
                self.assertEqual(headers['content-type'], 'application/json')
                self.assertNotIn('mcp-session-id', headers)
                self.assertNotIn('set-cookie', headers)
                self.assertNotIn('access-control-allow-origin', headers)
        listed = self.http(modern[2], token)[1]['result']
        self.assertEqual([t['name'] for t in listed['tools']], ['propose_table_edit', 'list_pages', 'read_page', 'get_workflow'])
        self.assertEqual(listed['resultType'], 'complete')
        read = self.http(modern[3], token)[1]['result']
        self.assertFalse(read['isError'])
        self.assertIn('Shot 1', read['content'][0]['text'])
        self.assertTrue(self.http(modern[5], token)[1]['result']['isError'])
        self.assertEqual(self.http(modern[6], token)[1]['error']['code'], protocol.INVALID_PARAMS)
        # A proposal over HTTP is written the same way: pending, nothing applied, audited with the client.
        edit = rpc('tools/call', 9, name='propose_table_edit',
                   arguments={'tab_key': 'shots', 'row_edits': [{'row_id': 'b_shot2', 'cells': {'1': 'late'}}]})
        status, proposed, _ = self.http(edit, token)
        self.assertEqual((status, proposed['result']['isError']), (200, False), proposed)
        with self.conn.cursor() as cur:
            cur.execute('SELECT status, action FROM projectops.assistant_proposal WHERE project_slug=%s', (self.slug,))
            self.assertEqual(cur.fetchall(), [('pending', 'table_edit')])
        self.conn.commit()
        # The legacy handshake, then requests framed by MCP-Protocol-Version; no session is minted.
        legacy = self.stdio(token)
        initialize = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                      'params': {'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'old', 'version': '1'}}}
        status, init, headers = self.http(initialize, token, headers={'Mcp-Session-Id': 'client-made-up'})
        self.assertEqual((status, init), (200, legacy.handle(initialize)))
        self.assertEqual(init['result']['protocolVersion'], '2025-11-25')
        self.assertNotIn('mcp-session-id', headers)
        status, body, headers = self.http({'jsonrpc': '2.0', 'method': 'notifications/initialized'}, token,
                                          headers={'MCP-Protocol-Version': '2025-11-25'})
        self.assertEqual((status, body, headers.get('content-type')), (202, b'', None))
        for ident, message in enumerate(({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
                                         {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                                          'params': {'name': 'list_pages', 'arguments': {}}},
                                         {'jsonrpc': '2.0', 'id': 4, 'method': 'ping'}), start=2):
            with self.subTest(legacy=message['method']):
                status, reply, _ = self.http(message, token, headers={'MCP-Protocol-Version': '2025-11-25'})
                self.assertEqual((status, reply), (200, legacy.handle(message)))
                self.assertNotIn('resultType', reply['result'])
        for version in ('2025-06-18', None):  # no header: 2025-03-26
            with self.subTest(version=version):
                status, reply, _ = self.http({'jsonrpc': '2.0', 'id': 5, 'method': 'tools/list'}, token,
                                             headers={'MCP-Protocol-Version': version})
                self.assertEqual((status, [t['name'] for t in reply['result']['tools']]), (200, [t['name'] for t in listed['tools']]))
        status, reply, _ = self.http({'jsonrpc': '2.0', 'id': 6, 'method': 'resources/list'}, token,
                                     headers={'MCP-Protocol-Version': '2025-11-25'})
        self.assertEqual((status, reply['error']['code']), (200, protocol.METHOD_NOT_FOUND))
        # Modern protocol errors carry their HTTP status.
        status, reply, _ = self.http(rpc('resources/list', 7), token)
        self.assertEqual((status, reply['error']['code']), (404, protocol.METHOD_NOT_FOUND))
        old = rpc('tools/list', 8, meta={**META, protocol.META_VERSION: '1900-01-01'})
        status, reply, _ = self.http(old, token)
        self.assertEqual((status, reply), (400, stdio.handle(old)))
        self.assertEqual(reply['error']['code'], protocol.UNSUPPORTED_VERSION)
        status, reply, _ = self.http(rpc('tools/call', 9, name='read_page', arguments={'key': 'shots'}), token,
                                     headers={'Mcp-Name': 'list_pages'})
        self.assertEqual((status, reply['id'], reply['error']['code']), (400, 9, protocol.HEADER_MISMATCH))
        status, reply, _ = self.http(rpc('tools/list', 10), token, modern=False)
        self.assertEqual((status, reply['error']['code']), (400, protocol.HEADER_MISMATCH))
        # No GET stream and no sessions to delete.
        for verb in ('GET', 'DELETE'):
            with self.subTest(verb=verb):
                self.assertEqual(self.http(token=token, method=verb)[0], 405)
        self.assertEqual(self.http(token=token, method='GET')[2]['allow'], 'POST')
        calls = [(d['tool'], d['outcome']) for d in self.audits('claude-code')]
        self.assertIn(('propose_table_edit', 'ok'), calls)
        modern_rows = [d for d in self.audits('claude-code') if d['tool'] == 'propose_table_edit']
        self.assertEqual(modern_rows[0]['client'], CLIENT)

    def test_origin_host_and_proxied_requests_are_refused_before_the_token(self):
        token = self.issue()
        listing = rpc('tools/list')
        self.assertEqual(self.http(listing, token, headers={'Origin': 'http://localhost:6274'})[0], 200)
        for headers in ({'Origin': 'http://evil.example'}, {'Origin': 'null'}, {'Host': 'evil.example'},
                        {'Host': f'rebound.example:{self.server.server_port}'}, {'X-Forwarded-For': '203.0.113.9'},
                        {'Cf-Connecting-Ip': '203.0.113.9'}, {'Forwarded': 'for=203.0.113.9'}):
            with self.subTest(headers=headers):
                status, reply, _ = self.http(listing, None, headers=headers)  # refused before any token check
                self.assertEqual((status, reply['error']['code'], reply['error']['data']), (403, protocol.LOCAL_ONLY, {'code': 'LOCAL_ONLY'}))
                self.assertIsNone(reply['id'])
                self.assertEqual(self.http(listing, token, headers=headers)[0], 403)
        self.assertEqual(self.http(token=token, method='GET', headers={'Origin': 'http://evil.example'})[0], 403)
        self.assertEqual(self.audits('claude-code'), [])

    def test_missing_expired_revoked_and_wrong_project_tokens(self):
        token = self.issue()
        listing = rpc('tools/list', 'r1')
        status, reply, headers = self.http(listing)
        self.assertEqual((status, reply['id'], reply['error']['code'], reply['error']['data']),
                         (401, 'r1', protocol.TOKEN_REFUSED, {'code': 'TOKEN_INVALID'}))
        self.assertTrue(headers['www-authenticate'].startswith('Bearer '))
        for bad in (self.member_token, 'zfsa_' + 'x' * 43):
            with self.subTest(token=bad[:12]):
                status, reply, _ = self.http(listing, bad)
                self.assertEqual((status, reply), (401, self.stdio(bad).handle(listing)))
        self.assertEqual(self.http(listing, token, headers={'Authorization': 'Basic abc'})[0], 401)
        status, reply, _ = self.http({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        self.assertEqual(status, 401)  # notifications need the token too
        status, reply, _ = self.http(listing, token, headers={'X-ZeroField-Project': 'another-one'})
        self.assertEqual((status, reply), (403, self.stdio(token, 'another-one').handle(listing)))
        self.assertEqual(reply['error']['data'], {'code': 'WRONG_PROJECT'})
        expiring = self.issue('expiring')
        with self.conn.cursor() as cur:
            cur.execute("""UPDATE projectops.agent_service_account SET expires_at=NOW()-INTERVAL '1 minute'
                           WHERE project_slug=%s AND account_key='expiring'""", (self.slug,))
        self.conn.commit()
        status, reply, _ = self.http(listing, expiring)
        self.assertEqual((status, reply['error']['data']), (401, {'code': 'TOKEN_EXPIRED'}))
        self.assertEqual(reply, self.stdio(expiring).handle(listing))
        self.assertEqual(self.http(rpc('server/discover'), expiring)[0], 401)  # discovery is not anonymous either
        code, revoked, _ = self.request(f'/projects/api/{self.slug}/service-accounts/claude-code/revoke', method='POST', data={})
        self.assertEqual((code, revoked['account']['status']), (200, 'revoked'))
        status, reply, _ = self.http(listing, token)
        self.assertEqual((status, reply['error']['data']), (401, {'code': 'TOKEN_REVOKED'}))
        self.assertEqual(reply, self.stdio(token).handle(listing))
        denied = {key: [d['code'] for d in self.audits(key) if d['outcome'] == 'denied'] for key in ('claude-code', 'expiring')}
        self.assertEqual(denied['claude-code'], ['WRONG_PROJECT'] * 2 + ['TOKEN_REVOKED'] * 2)  # HTTP, then stdio
        self.assertEqual(denied['expiring'], ['TOKEN_EXPIRED'] * 3)
        with self.conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM projectops.audit_log WHERE detail::text LIKE %s', ('%' + token + '%',))
            self.assertEqual(cur.fetchone()[0], 0)
            cur.execute('SELECT count(*) FROM projectops.audit_log WHERE detail::text LIKE %s',
                        ('%' + hashlib.sha256(token.encode()).hexdigest() + '%',))
            self.assertEqual(cur.fetchone()[0], 0)
        self.conn.commit()

    def test_body_and_response_limits_rate_limit_and_audit(self):
        token = self.issue('limits', tools=['read_page'])
        listing = rpc('tools/list')
        with patch.object(mcp_http, 'MAX_BODY', 64):
            status, reply, _ = self.http(rpc('tools/call', name='read_page', arguments={'key': 'shots' * 20}), token)
            self.assertEqual((status, reply['error']['code']), (413, protocol.INVALID_REQUEST))
        cases = [({'Content-Type': 'text/plain'}, None, 415), ({'Accept': 'text/html'}, None, 406),
                 ({}, b'{"jsonrpc": "2.0", "id": 1,', 400), ({}, b'[' * 200000 + b']' * 200000, 400),
                 ({}, json.dumps([listing]).encode(), 400), ({}, b'\xff\xfe', 400)]
        for headers, raw, expected in cases:
            with self.subTest(headers=headers, raw=(raw or b'')[:20]):
                status, reply, _ = self.http(listing, token, headers=headers, raw=raw)
                self.assertEqual(status, expected, reply)
        self.assertEqual(self.http(listing, token, raw=b'{]')[1]['error']['code'], protocol.PARSE_ERROR)
        connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=30)
        try:
            connection.putrequest('POST', '/mcp')
            for name, value in {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token,
                                'Transfer-Encoding': 'chunked', **mirrored(listing)}.items():
                connection.putheader(name, value)
            connection.endheaders()  # refused on its headers; the chunks are never sent
            self.assertEqual(connection.getresponse().status, 411)
        finally:
            connection.close()
        read = rpc('tools/call', 2, name='read_page', arguments={'key': 'shots'})
        with patch.object(mcp_http, 'MAX_RESPONSE', 200):
            status, reply, _ = self.http(read, token)
            self.assertEqual((status, reply['id'], reply['error']['code']), (200, 2, protocol.INTERNAL_ERROR))
            self.assertIn('response limit', reply['error']['message'])
        with self.conn.cursor() as cur:
            cur.execute('''INSERT INTO projectops.agent_console_settings(project_slug, rate_limits) VALUES (%s, %s::jsonb)
                           ON CONFLICT (project_slug) DO UPDATE SET rate_limits=EXCLUDED.rate_limits''',
                        (self.slug, json.dumps({'rpm_per_agent': 3, 'max_concurrent_renders': 2, 'max_concurrent_llm': 4})))
        self.conn.commit()
        status, reply, _ = self.http(read, token)  # the second call this minute (the oversized one counted)
        self.assertEqual((status, reply['result']['isError']), (200, False))
        self.assertEqual(self.http(listing, token)[0], 200)  # listing is not a tool call
        self.assertFalse(self.http(read, token)[1]['result']['isError'])
        limited = self.http(read, token)[1]['result']
        self.assertEqual(limited, self.stdio(token).handle(read)['result'])  # stdio maps the same 429 the same way
        self.assertTrue(limited['isError'])
        self.assertIn('Rate limit reached: at most 3 tool calls per minute', limited['content'][0]['text'])
        self.assertEqual([(d['tool'], d['outcome'], d['code']) for d in self.audits('limits')],
                         [('read_page', 'ok', None)] * 3 + [('read_page', 'denied', 'RATE_LIMITED')] * 2)
        self.assertTrue(all(d['writeMode'] == 'propose_only' for d in self.audits('limits')))
        self.assertEqual(self.audits('limits')[0]['client'], CLIENT)


if __name__ == '__main__':
    unittest.main()
