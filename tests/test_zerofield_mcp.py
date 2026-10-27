"""SPEC_20 R30/R31: the zerofield-mcp stdio server (both protocol eras) and service-account tokens.

Protocol tests use a fake backend. Database tests use the disposable PostgreSQL in OPENBENCH_TEST_DB_URI.
No model, GPU or ComfyUI is called: the allocation planner, the Story dispatch and the ComfyUI probe are fakes.
"""
import copy
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import tomllib
import types
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from project_assistant import external_tools, service_accounts, tool_registry, zerofield_mcp as mcp
from project_assistant.agent_registry import AgentError

ROOT = Path(__file__).resolve().parents[1]
MODERN = {mcp.META_VERSION: '2026-07-28', mcp.META_CAPABILITIES: {}, mcp.META_CLIENT: {'name': 'test-client', 'version': '1'}}
READ_PAGE = {'name': 'read_page', 'title': 'Production Page', 'description': 'Read a page.',
             'inputSchema': {'type': 'object', 'properties': {'key': {'type': 'string'}}, 'additionalProperties': False},
             'annotations': {'readOnlyHint': True}}


def rpc(method, ident=1, meta=MODERN, **params):
    if meta is not None:
        params['_meta'] = meta
    return {'jsonrpc': '2.0', 'id': ident, 'method': method, 'params': params}


class FakeBackend:
    def __init__(self, tools=None, reply=None, error=None):
        self.tools = [READ_PAGE] if tools is None else tools
        self.reply = reply or {'text': '{"ok": true}', 'isError': False, 'images': []}
        self.error, self.calls = error, []

    def list_tools(self):
        if self.error:
            raise self.error
        return self.tools

    def call_tool(self, name, arguments, client=None):
        self.calls.append((name, arguments, client))
        if self.error:
            raise self.error
        return self.reply


class ProtocolTests(unittest.TestCase):
    def test_discovery_is_modern_and_needs_no_handshake(self):
        server = mcp.Server(FakeBackend())
        reply = server.handle(rpc('server/discover'))['result']
        self.assertEqual(reply['resultType'], 'complete')
        self.assertEqual(reply['supportedVersions'][0], '2026-07-28')
        self.assertIn('2025-11-25', reply['supportedVersions'])
        self.assertEqual(reply['capabilities'], {'tools': {'listChanged': False}})
        self.assertEqual(reply['_meta'][mcp.META_SERVER]['name'], 'zerofield-mcp')
        self.assertIn('proposals', reply['instructions'])
        listed = server.handle(rpc('tools/list', 2))['result']
        self.assertEqual((listed['resultType'], [t['name'] for t in listed['tools']]), ('complete', ['read_page']))
        self.assertEqual(listed['tools'][0]['title'], 'Production Page')
        self.assertEqual(server.handle(rpc('ping', 3))['result']['resultType'], 'complete')

    def test_every_modern_request_carries_its_version_and_capabilities(self):
        server = mcp.Server(FakeBackend())
        server.handle(rpc('server/discover'))
        missing = server.handle(rpc('tools/list', 2, meta=None))['error']  # no state carried from discover
        self.assertEqual(missing['code'], mcp.INVALID_PARAMS)
        self.assertIn('2026-07-28', missing['data']['supported'])
        no_caps = server.handle(rpc('tools/list', 3, meta={mcp.META_VERSION: '2026-07-28'}))['error']
        self.assertEqual(no_caps['code'], mcp.INVALID_PARAMS)
        unsupported = server.handle(rpc('tools/list', 4, meta={**MODERN, mcp.META_VERSION: '1900-01-01'}))['error']
        self.assertEqual((unsupported['code'], unsupported['message']), (-32022, 'Unsupported protocol version'))
        self.assertEqual(unsupported['data']['requested'], '1900-01-01')
        self.assertIn('2026-07-28', unsupported['data']['supported'])
        legacy_in_modern_framing = server.handle(rpc('tools/list', 5, meta={**MODERN, mcp.META_VERSION: '2025-11-25'}))
        self.assertEqual(legacy_in_modern_framing['error']['code'], -32022)
        self.assertEqual(server.handle(rpc('resources/list', 6))['error']['code'], mcp.METHOD_NOT_FOUND)

    def test_legacy_initialize_handshake(self):
        backend = FakeBackend()
        server = mcp.Server(backend)
        init = server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                              'params': {'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'old', 'version': '1'}}})
        self.assertEqual(init['result']['protocolVersion'], '2025-11-25')
        self.assertEqual(init['result']['capabilities'], {'tools': {'listChanged': False}})
        self.assertEqual(init['result']['serverInfo']['name'], 'zerofield-mcp')
        self.assertNotIn('resultType', init['result'])
        self.assertIsNone(server.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'}))
        listed = server.handle({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})['result']
        self.assertEqual([t['name'] for t in listed['tools']], ['read_page'])
        self.assertNotIn('resultType', listed)
        self.assertNotIn('_meta', listed)
        called = server.handle({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                                'params': {'name': 'read_page', 'arguments': {'key': 'shots'}}})['result']
        self.assertEqual(called['content'][0]['type'], 'text')
        self.assertEqual(backend.calls, [('read_page', {'key': 'shots'}, None)])
        self.assertEqual(server.handle({'jsonrpc': '2.0', 'id': 4, 'method': 'ping'})['result'], {})
        # A dual-era process still answers modern requests statelessly.
        self.assertEqual(server.handle(rpc('tools/list', 5))['result']['resultType'], 'complete')
        for requested, chosen in (('2025-06-18', '2025-06-18'), ('2025-03-26', '2025-03-26'), ('2024-11-05', '2025-11-25')):
            with self.subTest(requested=requested):
                reply = mcp.Server(FakeBackend()).handle({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                                                          'params': {'protocolVersion': requested, 'capabilities': {}}})
                self.assertEqual(reply['result']['protocolVersion'], chosen)

    def test_tool_results_and_backend_errors_map_to_mcp(self):
        backend = FakeBackend(reply={'text': '{"status": "submitted"}', 'isError': False,
                                     'images': ['data:image/png;base64,AAAA', 'https://not-inline.example/x.png']})
        server = mcp.Server(backend)
        result = server.handle(rpc('tools/call', name='read_page', arguments={'key': 'shots'}))['result']
        self.assertEqual(result['structuredContent'], {'status': 'submitted'})
        self.assertEqual(result['content'][1], {'type': 'image', 'mimeType': 'image/png', 'data': 'AAAA'})
        self.assertEqual(len(result['content']), 2)
        self.assertFalse(result['isError'])
        self.assertEqual(backend.calls[-1][2], {'name': 'test-client', 'version': '1'})
        refused = mcp.Server(FakeBackend(reply={'text': 'POLICY_DENIED: no', 'isError': True}))
        result = refused.handle(rpc('tools/call', name='read_page', arguments={}))['result']
        self.assertEqual((result['isError'], 'structuredContent' in result), (True, False))
        self.assertEqual(server.handle(rpc('tools/call', name='read_page', arguments=['x']))['error']['code'], mcp.INVALID_PARAMS)
        self.assertEqual(server.handle(rpc('tools/call', arguments={}))['error']['code'], mcp.INVALID_PARAMS)
        cases = [(mcp.BackendError(404, 'not available', 'UNKNOWN_TOOL'), mcp.INVALID_PARAMS, 'Unknown tool: nope'),
                 (mcp.BackendError(401, 'The service-account token is expired.', 'TOKEN_EXPIRED'), mcp.TOKEN_REFUSED, 'expired'),
                 (mcp.BackendError(403, 'another production', 'WRONG_PROJECT'), mcp.TOKEN_REFUSED, 'another production'),
                 (mcp.BackendError(403, 'local only', 'LOCAL_ONLY'), mcp.LOCAL_ONLY, 'local only'),
                 (mcp.BackendError(0, 'URLError'), mcp.SERVER_UNREACHABLE, 'not reachable'),
                 (mcp.BackendError(500, 'boom'), mcp.INTERNAL_ERROR, 'HTTP 500')]
        for exc, code, text in cases:
            with self.subTest(code=code, status=exc.status):
                error = mcp.Server(FakeBackend(error=exc)).handle(rpc('tools/call', name='nope', arguments={}))['error']
                self.assertEqual(error['code'], code)
                self.assertIn(text, error['message'])
        self.assertEqual(mcp.Server(FakeBackend(error=mcp.BackendError(401, 'revoked', 'TOKEN_REVOKED'))).handle(
            rpc('tools/list'))['error']['data'], {'code': 'TOKEN_REVOKED'})
        limited = mcp.Server(FakeBackend(error=mcp.BackendError(429, 'Rate limit reached.', 'RATE_LIMITED')))
        result = limited.handle(rpc('tools/call', name='read_page', arguments={}))['result']
        self.assertEqual((result['isError'], result['content'][0]['text']), (True, 'Rate limit reached.'))

    def test_stdio_lines_notifications_bad_json_and_batches(self):
        lines = [rpc('server/discover', 'a'), {'jsonrpc': '2.0', 'method': 'notifications/cancelled', 'params': {'requestId': 'a'}},
                 'not json', [rpc('ping', 9)], rpc('tools/list', 2), {'jsonrpc': '2.0', 'id': 7, 'result': {}},
                 {'jsonrpc': '2.0', 'id': True, 'method': 'ping'}]
        stdin = io.BytesIO(b''.join((item if isinstance(item, str) else json.dumps(item)).encode() + b'\n\n' for item in lines))
        stdout = io.BytesIO()
        mcp.Server(FakeBackend()).serve(stdin, stdout)
        out = stdout.getvalue().decode('utf-8').splitlines()
        replies = [json.loads(line) for line in out]
        self.assertEqual(len(replies), 5)
        self.assertEqual(replies[0]['id'], 'a')
        self.assertEqual((replies[1]['id'], replies[1]['error']['code']), (None, mcp.PARSE_ERROR))
        self.assertEqual(replies[2]['error']['code'], mcp.INVALID_REQUEST)
        self.assertEqual(replies[3]['result']['tools'][0]['name'], 'read_page')
        self.assertEqual((replies[4]['id'], replies[4]['error']['code']), (None, mcp.INVALID_REQUEST))

    def test_configuration_problems_still_answer_discovery(self):
        self.assertIn(mcp.TOKEN_ENV, mcp.configuration('http://127.0.0.1:3020', ''))
        for url in ('http://example.com:3020', 'https://127.0.0.1:3020', 'http://user@127.0.0.1:3020', 'not a url'):
            with self.subTest(url=url):
                self.assertIn(mcp.URL_ENV, mcp.configuration(url, 'zfsa_token'))
        self.assertIsNone(mcp.configuration('http://localhost:3020', 'zfsa_token'))
        backend = FakeBackend()
        server = mcp.Server(backend, config_error='Set ZEROFIELD_MCP_TOKEN.')
        self.assertIn('supportedVersions', server.handle(rpc('server/discover'))['result'])
        error = server.handle(rpc('tools/list', 2))['error']
        self.assertEqual((error['code'], error['message']), (mcp.TOKEN_REFUSED, 'Set ZEROFIELD_MCP_TOKEN.'))
        self.assertEqual(backend.calls, [])

    def test_http_backend_sends_the_token_to_loopback_without_a_proxy(self):
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def _reply(self, status, payload):
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):  # noqa: N802
                seen.append(('GET', self.path, {k.lower(): v for k, v in self.headers.items()}, None))
                self._reply(200, {'tools': [READ_PAGE]})

            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                seen.append(('POST', self.path, {k.lower(): v for k, v in self.headers.items()}, body))
                if self.path.endswith('/nope'):
                    self._reply(404, {'error': 'not available', 'code': 'UNKNOWN_TOOL'})
                else:
                    self._reply(200, {'text': 'ok', 'isError': False, 'images': []})

            def log_message(self, *args):
                pass

        httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ, {'HTTP_PROXY': 'http://127.0.0.1:9', 'http_proxy': 'http://127.0.0.1:9', 'NO_PROXY': ''}):
                backend = mcp.HttpBackend(f'http://127.0.0.1:{httpd.server_port}/', 'zfsa_secret', 'prod-a', timeout=5)
                self.assertEqual(backend.list_tools(), [READ_PAGE])
                self.assertEqual(backend.call_tool('read_page', {'key': 'shots'}, {'name': 'c'})['text'], 'ok')
                with self.assertRaises(mcp.BackendError) as caught:
                    backend.call_tool('nope', {})
        finally:
            httpd.shutdown()
            httpd.server_close()
        self.assertEqual((caught.exception.status, caught.exception.code), (404, 'UNKNOWN_TOOL'))
        method, path, headers, _ = seen[0]
        self.assertEqual((method, path), ('GET', '/agent-mcp/v1/tools'))
        self.assertEqual(headers['authorization'], 'Bearer zfsa_secret')
        self.assertEqual(headers['x-zerofield-project'], 'prod-a')
        self.assertEqual(seen[1][1:2] + (seen[1][3],), ('/agent-mcp/v1/tools/read_page', {'arguments': {'key': 'shots'}, 'client': {'name': 'c'}}))
        with self.assertRaises(mcp.BackendError) as caught:
            mcp.HttpBackend('http://127.0.0.1:9', 'zfsa_secret', timeout=2).list_tools()
        self.assertEqual(caught.exception.status, 0)

    def test_console_script_speaks_stdio(self):
        scripts = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']['scripts']
        self.assertEqual(scripts['zerofield-mcp'], 'project_assistant.zerofield_mcp:main')
        env = {k: v for k, v in os.environ.items() if not k.startswith('ZEROFIELD_')}
        env['PYTHONPATH'] = str(ROOT)
        stdin = '\n'.join(json.dumps(m) for m in (rpc('server/discover'), rpc('tools/list', 2))) + '\n'
        done = subprocess.run([sys.executable, '-m', 'project_assistant.zerofield_mcp'], input=stdin.encode(),
                              capture_output=True, env=env, cwd=ROOT, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        replies = [json.loads(line) for line in done.stdout.decode().splitlines()]
        self.assertEqual(replies[0]['result']['supportedVersions'][0], '2026-07-28')
        self.assertEqual(replies[1]['error']['code'], mcp.TOKEN_REFUSED)
        self.assertIn(b'ZEROFIELD_MCP_TOKEN', done.stderr)


class TokenScopeTests(unittest.TestCase):
    def names(self, **account):
        return [s['name'] for s in service_accounts.visible_specs(account)]

    def test_visible_tools_are_registry_exposure_then_scope_then_write_mode(self):
        scope = ['request_generation', 'read_page', 'get_workflow', 'propose_table_edit', 'spawn_agent', 'search_pages', 'nope']
        self.assertEqual(self.names(tools=scope, writeMode='generate'),
                         ['propose_table_edit', 'read_page', 'get_workflow', 'request_generation'])
        self.assertEqual(self.names(tools=scope, writeMode='propose_only'), ['propose_table_edit', 'read_page', 'get_workflow'])
        self.assertEqual(self.names(tools=[], writeMode='generate'), [])
        with patch.object(tool_registry, 'ZEROFIELD_MCP', tool_registry.ZEROFIELD_MCP - {'read_page'}):
            self.assertNotIn('read_page', self.names(tools=scope, writeMode='generate'))
        spec = service_accounts.visible_specs({'tools': ['request_generation'], 'writeMode': 'generate'})[0]
        self.assertEqual(spec['title'], 'Request Generation')
        self.assertEqual(spec['inputSchema'], tool_registry.get('request_generation').schema)
        self.assertNotIn('request_generation', service_accounts.exposed_tools('propose_only'))
        self.assertIn('request_generation', service_accounts.exposed_tools('generate'))

    def test_get_workflow_reads_the_packaged_manuals_and_pages_them(self):
        from openbench_data import resource_path
        manuals = ('continuity-check', 'crew-preproduction', 'previs-blocking', 'shot-beats')
        listing = json.loads(external_tools.get_workflow(None, None, {}))
        self.assertEqual(listing['status'], 'ok')
        self.assertEqual([w['name'] for w in listing['workflows']], list(manuals))
        for name in manuals:
            with self.subTest(name=name):
                text = resource_path('skills', name, 'SKILL.md').read_text(encoding='utf-8')
                description = next(w['description'] for w in listing['workflows'] if w['name'] == name)
                self.assertTrue(description)
                self.assertIn(description[:60], text)
                pages, offset = [], 0
                while True:
                    page = external_tools.get_workflow(None, None, {'name': name, 'offset': offset} if offset else {'name': name})
                    body, _, note = page.partition('\n\n[The guide continues:')
                    pages.append(body)
                    if not note:
                        break
                    self.assertIn(f'offset {offset + external_tools.PAGE_CHARS}', note)
                    offset += external_tools.PAGE_CHARS
                self.assertEqual(''.join(pages), text)
                self.assertGreater(len(pages), 1)
        for args, code in (({'name': 'missing'}, 'NOT_FOUND'), ({'name': 'shot-beats', 'offset': 999999}, 'INVALID_REQUEST')):
            with self.subTest(args=args), self.assertRaises(external_tools.Refusal) as caught:
                external_tools.get_workflow(None, None, args)
            self.assertEqual(caught.exception.code, code)
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(external_tools, '_resource', side_effect=lambda *parts: Path(directory, 'absent', *parts)):
            self.assertEqual(json.loads(external_tools.get_workflow(None, None, {}))['status'], 'unavailable')
            with self.assertRaises(external_tools.Refusal):
                external_tools.get_workflow(None, None, {'name': 'shot-beats'})
        for bad in ('../secrets', 'a/b', 'UPPER', ''):
            with self.subTest(name=bad), self.assertRaises(ValueError):
                tool_registry.validate_args('get_workflow', {'name': bad})

    def test_context_read_tools_reach_zerofield_mcp_by_the_default_rule(self):
        context = ['read_episode', 'read_scene', 'read_shot', 'read_cast', 'list_takes']
        for name in context:
            with self.subTest(name=name):
                tool = tool_registry.get(name)
                self.assertIsNone(tool.zerofield_mcp)  # no flag: derived as a read-only tool
                self.assertTrue(tool_registry.zerofield_exposed(tool))
        for mode in ('propose_only', 'generate'):
            self.assertLessEqual(set(context), set(service_accounts.exposed_tools(mode)))
        self.assertEqual(self.names(tools=context + ['spawn_agent'], writeMode='propose_only'), context)

    def test_only_free_local_open_weights_plans_may_be_submitted(self):
        from project_assistant import execution_governance
        local = {'engine_config': {'driver': 'comfy_local'}, '_dest': 'http://127.0.0.1:8188'}
        remote = {'engine_config': {'driver': 'comfy_local'}, '_dest': 'https://gpu.example.com'}
        stage = {'kind': 'generate', 'card_id': 'local'}

        def saved(*allocations, cards=None):
            return {'plan': {'allocations': list(allocations), 'summary': {}}, 'cards': cards if cards is not None else {'local': local, 'remote': remote}}

        free = {'shot_id': 's1', 'tier': 'open_weights', 'driver': 'comfy_local', 'stages': [stage]}
        with patch.object(execution_governance, 'media_destination', side_effect=lambda card: card['_dest']):
            self.assertEqual(external_tools.spend_reasons(saved(free)), [])
            for allocation in ({**free, 'tier': 'closed_hero', 'driver': 'vendor_api'},
                               {**free, 'tier': 'cloud_burst', 'driver': 'comfy_router'},
                               {**free, 'stages': [{'kind': 'approval'}, stage]},
                               {**free, 'stages': [{'kind': 'generate', 'card_id': 'remote'}]},
                               {**free, 'stages': [{'kind': 'generate', 'card_id': 'unknown'}]}):
                with self.subTest(allocation=allocation):
                    reasons = external_tools.spend_reasons(saved(free, allocation))
                    self.assertEqual(len(reasons), 1)
            closed = saved({**free, 'tier': 'closed_hero', 'driver': 'vendor_api'})
            self.assertEqual(external_tools.estimate(closed, ['x'])['costUsd'], None)
            self.assertEqual(external_tools.estimate(saved(free), [])['costUsd'], '0.00')


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'set OPENBENCH_TEST_DB_URI')
class ServiceAccountDatabaseTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        import test_execution as execution_fixture
        self.fixture = execution_fixture.PostgreSQLExecutionTests
        self.fixture.setUp(self)
        self.conn.commit()
        self.connect = lambda: psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI'])
        self.cleanup_members, self.cleanup_projects = [], []

    def tearDown(self):
        self.conn.rollback()
        with self.conn.cursor() as cur:
            for slug in self.cleanup_projects:
                cur.execute('DELETE FROM projectops.project WHERE slug=%s', (slug,))
            for actor in self.cleanup_members:
                cur.execute('DELETE FROM projectops.member WHERE actor_id=%s', (actor,))
        self.conn.commit()
        self.fixture.tearDown(self)

    def issue(self, key='claude', tools=('read_page', 'propose_table_edit'), mode='propose_only', **extra):
        try:
            return service_accounts.create(self.conn, self.me, self.slug, {'accountKey': key, 'tools': list(tools), 'writeMode': mode, **extra})
        finally:
            self.conn.commit()

    def auth(self, token, project=None):
        try:
            return service_accounts.authenticate(self.conn, token, project)
        finally:
            self.conn.commit()

    def refused(self, status, code, fn, *args):
        with self.assertRaises(AgentError) as caught:
            fn(*args)
        self.conn.commit()
        self.assertEqual((caught.exception.status, caught.exception.code), (status, code))

    def audits(self, key):
        with self.conn.cursor() as cur:
            cur.execute('''SELECT actor_id::text, detail FROM projectops.audit_log WHERE project_slug=%s AND action=%s AND target=%s
                           ORDER BY id''', (self.slug, service_accounts.CALL_ACTION, key))
            rows = cur.fetchall()
        self.conn.commit()
        return rows

    def member(self, role):
        from project_docs import repository as repo, service
        identity = service.Identity(str(uuid.uuid4()), 'Crew ' + role, role)
        repo.upsert_member(self.conn, identity.actor_id, identity.name, role)
        self.conn.commit()
        self.cleanup_members.append(identity.actor_id)
        return identity

    def test_token_is_returned_once_and_only_its_hash_is_stored(self):
        from project_assistant import agent_console_store as console
        issued = self.issue(tools=['read_page', 'get_workflow'], expiresInDays=7)
        token = issued['token']
        self.assertTrue(token.startswith('zfsa_'))
        self.assertEqual(issued['account']['status'], 'active')
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.conn.cursor() as cur:
            cur.execute('SELECT token_hash FROM projectops.agent_service_token WHERE project_slug=%s', (self.slug,))
            self.assertEqual(cur.fetchall(), [(digest,)])
            cur.execute('SELECT to_jsonb(a) FROM projectops.agent_service_account a WHERE project_slug=%s', (self.slug,))
            row = json.dumps(cur.fetchall())
        listed = service_accounts.list_accounts(self.conn, self.me, self.slug)
        history = console.history(self.conn, self.me, self.slug, 'service_account', 'claude')
        self.conn.commit()
        for text in (row, json.dumps(listed), json.dumps(history, default=str), json.dumps(issued['account'])):
            self.assertNotIn(token, text)
            self.assertNotIn(digest, text)
        item = listed['items'][0]
        self.assertEqual((item['accountKey'], item['tools'], item['writeMode'], item['status']), ('claude', ['read_page', 'get_workflow'], 'propose_only', 'active'))
        self.assertEqual(item['usage']['calls'], 0)
        self.assertIn(('request_generation', True), [(t['name'], t['generation']) for t in listed['availableTools']])
        self.refused(409, 'ACCOUNT_EXISTS', self.issue)
        crew = self.member('member')
        self.refused(403, 'POLICY_DENIED', service_accounts.create, self.conn, crew, self.slug, {'accountKey': 'mine', 'tools': ['read_page']})
        self.refused(403, 'POLICY_DENIED', service_accounts.list_accounts, self.conn, crew, self.slug)
        for body in ({'tools': ['request_generation']}, {'tools': ['spawn_agent']}, {'tools': []}, {'tools': ['read_page', 'read_page']},
                     {'tools': ['read_page'], 'expiresInDays': 400}, {'tools': ['read_page'], 'expiresAt': '2001-01-01T00:00:00Z'},
                     {'tools': ['read_page'], 'expiresAt': '2099-01-01T00:00:00'}, {'tools': ['read_page'], 'writeMode': 'admin'},
                     {'tools': ['read_page'], 'token': 'mine'}, {'tools': ['read_page'], 'accountKey': 'Bad Key'}):
            with self.subTest(body=body):
                self.refused(400, 'INVALID_REQUEST', service_accounts.create, self.conn, self.me, self.slug, {'accountKey': 'other', **body})

    def test_expired_revoked_wrong_project_and_demoted_issuer_tokens_are_refused(self):
        from project_docs import repository as repo
        alpha, beta, gamma = (self.issue(key)['token'] for key in ('alpha', 'beta', 'gamma'))
        account = self.auth(alpha)
        self.assertEqual((account['project'], account['issuer']['actor_id']), (self.slug, self.actor))
        self.assertEqual(self.auth(alpha, self.slug)['accountKey'], 'alpha')
        other = 'other-' + uuid.uuid4().hex[:8]
        repo.upsert_project(self.conn, other, 'Other production')
        self.conn.commit()
        self.cleanup_projects.append(other)
        self.refused(403, 'WRONG_PROJECT', service_accounts.authenticate, self.conn, alpha, other)
        with self.conn.cursor() as cur:
            cur.execute("UPDATE projectops.agent_service_account SET expires_at=NOW()-INTERVAL '1 minute' WHERE project_slug=%s AND account_key='alpha'", (self.slug,))
        self.conn.commit()
        self.refused(401, 'TOKEN_EXPIRED', service_accounts.authenticate, self.conn, alpha)
        revoked = service_accounts.revoke(self.conn, self.me, self.slug, 'beta')
        self.conn.commit()
        self.assertEqual(revoked['account']['status'], 'revoked')
        self.assertEqual(service_accounts.revoke(self.conn, self.me, self.slug, 'beta')['account']['status'], 'revoked')
        self.conn.commit()
        self.refused(401, 'TOKEN_REVOKED', service_accounts.authenticate, self.conn, beta)
        self.refused(404, 'NOT_FOUND', service_accounts.revoke, self.conn, self.me, self.slug, 'missing')
        repo.upsert_member(self.conn, self.actor, 'Execution test', 'member')
        self.conn.commit()
        self.refused(403, 'ISSUER_REVOKED', service_accounts.authenticate, self.conn, gamma)
        repo.upsert_member(self.conn, self.actor, 'Execution test', 'admin')
        self.conn.commit()
        self.assertEqual(self.auth(gamma)['accountKey'], 'gamma')
        self.refused(401, 'TOKEN_INVALID', service_accounts.authenticate, self.conn, 'zfsa_' + 'x' * 43)
        self.refused(401, 'TOKEN_INVALID', service_accounts.authenticate, self.conn, 'test-member-token')
        denied = {key: [d['code'] for actor, d in self.audits(key) if d['outcome'] == 'denied'] for key in ('alpha', 'beta', 'gamma')}
        self.assertEqual(denied, {'alpha': ['WRONG_PROJECT', 'TOKEN_EXPIRED'], 'beta': ['TOKEN_REVOKED'], 'gamma': ['ISSUER_REVOKED']})
        self.assertEqual({actor for actor, _ in self.audits('alpha')}, {self.actor})

    def test_proposals_go_through_the_shared_tool_layer_and_are_audited(self):
        from project_docs import repository as repo
        account = self.auth(self.issue()['token'])
        revision = repo.get_tab(self.conn, self.slug, 'shots')['revision']
        self.conn.commit()
        result = service_accounts.call_tool(self.connect, account, 'propose_table_edit',
                                            {'tab_key': 'shots', 'row_edits': [{'row_id': 'b_shot2', 'cells': {'1': 'late'}}]},
                                            client={'name': 'Claude Code', 'version': '2.1'})
        self.assertFalse(result['isError'], result)
        with self.conn.cursor() as cur:
            cur.execute("SELECT id, owner_id::text, status, action FROM projectops.assistant_proposal WHERE project_slug=%s", (self.slug,))
            proposals = cur.fetchall()
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0][1:], (self.actor, 'pending', 'table_edit'))
        self.assertEqual(repo.get_tab(self.conn, self.slug, 'shots')['revision'], revision)  # nothing is written before adoption
        self.conn.commit()
        read = service_accounts.call_tool(self.connect, account, 'read_page', {'key': 'shots'})
        self.assertFalse(read['isError'], read)
        self.assertIn('Shot 1', read['text'])
        bad = service_accounts.call_tool(self.connect, account, 'read_page', {'tab': 'shots'})
        self.assertEqual((bad['isError'], bad['code']), (True, 'INVALID_ARGUMENTS'))
        for name in ('get_workflow', 'spawn_agent', 'request_generation'):
            with self.subTest(name=name), self.assertRaises(AgentError) as caught:
                service_accounts.call_tool(self.connect, account, name, {})
            self.assertEqual((caught.exception.status, caught.exception.code), (404, 'UNKNOWN_TOOL'))
        service_accounts.revoke(self.conn, self.me, self.slug, 'claude')
        self.conn.commit()
        stale = service_accounts.call_tool(self.connect, account, 'read_page', {'key': 'shots'})  # rechecked in the tool's transaction
        self.assertEqual((stale['isError'], stale['code']), (True, 'POLICY_DENIED'))
        rows = [detail for _, detail in self.audits('claude')]
        self.assertEqual([(d['tool'], d['outcome']) for d in rows],
                         [('propose_table_edit', 'ok'), ('read_page', 'ok'), ('read_page', 'error'), ('get_workflow', 'denied'),
                          ('spawn_agent', 'denied'), ('request_generation', 'denied'), ('read_page', 'error')])
        self.assertEqual(rows[0]['proposalIds'], [proposals[0][0]])
        self.assertEqual(rows[0]['client'], {'name': 'Claude Code', 'version': '2.1'})
        self.assertEqual(rows[0]['writeMode'], 'propose_only')
        self.assertTrue(all(len(d.get('argsSha256', '')) == 64 for d in rows))
        usage = service_accounts.usage(self.conn, self.slug, 'claude')
        self.conn.commit()
        self.assertEqual((usage['calls'], usage['succeeded'], usage['refused']), (7, 2, 5))

    def test_calls_are_rate_limited_per_service_account(self):
        account = self.auth(self.issue()['token'])
        with self.conn.cursor() as cur:
            cur.execute('''INSERT INTO projectops.agent_console_settings(project_slug, rate_limits) VALUES (%s, %s::jsonb)
                           ON CONFLICT (project_slug) DO UPDATE SET rate_limits=EXCLUDED.rate_limits''',
                        (self.slug, json.dumps({'rpm_per_agent': 2, 'max_concurrent_renders': 2, 'max_concurrent_llm': 4})))
        self.conn.commit()
        for _ in range(2):
            service_accounts.rate_limit(self.conn, account, 'read_page')
            self.conn.commit()
            self.assertFalse(service_accounts.call_tool(self.connect, account, 'read_page', {'key': 'shots'})['isError'])
        for _ in range(2):  # a refusal is audited but does not extend the limit
            self.refused(429, 'RATE_LIMITED', service_accounts.rate_limit, self.conn, account, 'read_page')
        self.assertEqual([(d['tool'], d['outcome'], d['code']) for _, d in self.audits('claude')],
                         [('read_page', 'ok', None), ('read_page', 'ok', None),
                          ('read_page', 'denied', 'RATE_LIMITED'), ('read_page', 'denied', 'RATE_LIMITED')])

    def test_propose_only_tokens_and_crew_turns_cannot_generate(self):
        account = self.auth(self.issue('drafts', tools=['read_page'])['token'])
        with self.conn.cursor() as cur:  # even a scope edited to name the tool stays hidden in propose_only
            cur.execute('''UPDATE projectops.agent_service_account SET tools='["read_page","request_generation"]'::jsonb
                           WHERE project_slug=%s AND account_key='drafts' ''', (self.slug,))
        self.conn.commit()
        account = self.auth_key('drafts', account)
        self.assertNotIn('request_generation', [s['name'] for s in service_accounts.visible_specs(account)])
        with self.assertRaises(AgentError) as caught:
            service_accounts.call_tool(self.connect, account, 'request_generation',
                                       {'episode_id': 'ep', 'shot_ids': ['s1'], 'request_id': 'req-00000001'})
        self.assertEqual(caught.exception.code, 'UNKNOWN_TOOL')
        crew = types.SimpleNamespace(slug=self.slug, write_mode='proposal', service_account=None)
        with self.assertRaises(external_tools.Refusal) as refused:
            external_tools.request_generation(crew, self.conn, {'episode_id': 'ep', 'shot_ids': ['s1'], 'request_id': 'req-00000001'})
        self.assertEqual(refused.exception.code, 'POLICY_DENIED')

    def auth_key(self, key, account):
        """Re-read an account after a direct row edit (the token is unchanged)."""
        row = service_accounts._row(self.conn, self.slug, key)
        self.conn.commit()
        return {**service_accounts.public(row), 'issuer': account['issuer']}

    def test_generation_refuses_closed_or_paid_plans_and_replays_request_ids(self):
        from project_assistant import execution_governance
        account = self.auth(self.issue('render', tools=['request_generation'], mode='generate')['token'])
        cards = {'local': {'engine_config': {'driver': 'comfy_local'}}}
        free = {'shot_id': 's1', 'tier': 'open_weights', 'driver': 'comfy_local', 'stages': [{'kind': 'generate', 'card_id': 'local'}],
                'configuration_blockers': []}
        plans = {'paid': ({'shot_id': 's1', 'tier': 'closed_hero', 'driver': 'vendor_api', 'stages': []}, True),
                 'free': (free, True), 'blocked': ({**free, 'configuration_blockers': ['comfyui_offline']}, False)}
        state = {'plan': 'paid', 'saved': {}, 'dispatched': []}

        def plan(ctx, conn, ep, request):
            allocation, ready = plans[state['plan']]
            identifier = 'al_' + uuid.uuid4().hex
            state['saved'][identifier] = {'plan': {'allocations': [copy.deepcopy(allocation)], 'summary': {'estimate_basis': 'fixture'}, 'ready': ready},
                                          'cards': cards}
            return {'allocationId': identifier, 'ready': ready}

        def dispatch(ctx, conn, ep, request, allocation_id):
            state['dispatched'].append((allocation_id, request['shot_ids']))
            return {'taskGroupId': 'tg_' + allocation_id, 'taskIds': ['task_' + s for s in request['shot_ids']]}

        def call(request_id, shots=('s1',)):
            return service_accounts.call_tool(self.connect, account, 'request_generation',
                                              {'episode_id': 'ep_fixture_01', 'shot_ids': list(shots), 'request_id': request_id})

        with patch.object(external_tools, '_episode', side_effect=lambda ctx, conn, ident: {'episodeId': ident, 'slug': ctx.slug}), \
             patch.object(external_tools, '_plan', side_effect=plan), \
             patch.object(external_tools, '_allocation', side_effect=lambda ctx, conn, identifier: state['saved'][identifier]), \
             patch.object(external_tools, '_dispatch', side_effect=dispatch), \
             patch.object(service_accounts, '_probe_local_comfy', return_value=True) as probe, \
             patch.object(execution_governance, 'media_destination', return_value='http://127.0.0.1:8188'):
            paid = call('req-paid-0001')
            self.assertEqual((paid['isError'], paid['code']), (True, 'NEEDS_HUMAN'))
            self.assertIn('"free": false', paid['text'])
            self.assertEqual(state['dispatched'], [])
            state['plan'] = 'free'
            first = call('req-free-0001', ('s1', 's2'))
            self.assertFalse(first['isError'], first)
            submitted = json.loads(first['text'])
            self.assertEqual((submitted['status'], submitted['estimate']['free'], submitted['estimate']['costUsd'], submitted['reviewRequired']),
                             ('submitted', True, '0.00', True))
            again = json.loads(call('req-free-0001', ('s2', 's1'))['text'])
            self.assertEqual((again['replayed'], again['taskGroupId']), (True, submitted['taskGroupId']))
            self.assertEqual(len(state['dispatched']), 1)
            conflict = call('req-free-0001', ('s1',))
            self.assertEqual((conflict['isError'], conflict['code']), (True, 'IDEMPOTENCY_CONFLICT'))
            state['plan'] = 'blocked'
            blocked = call('req-blocked-01')
            self.assertEqual((blocked['isError'], blocked['code']), (True, 'NOT_READY'))
            self.assertIn('comfyui_offline', blocked['text'])
            self.assertEqual(len(state['dispatched']), 1)
            self.assertEqual(probe.call_count, 5)
        with self.conn.cursor() as cur:
            cur.execute('SELECT request_id, result->>\'allocationId\' FROM projectops.agent_service_request WHERE project_slug=%s', (self.slug,))
            self.assertEqual(cur.fetchall(), [('req-free-0001', submitted['allocationId'])])
        self.conn.commit()
        rows = [d for _, d in self.audits('render')]
        self.assertEqual([(d['requestId'], d['outcome'], d.get('code')) for d in rows],
                         [('req-paid-0001', 'error', 'NEEDS_HUMAN'), ('req-free-0001', 'ok', None), ('req-free-0001', 'ok', None),
                          ('req-free-0001', 'error', 'IDEMPOTENCY_CONFLICT'), ('req-blocked-01', 'error', 'NOT_READY')])
        self.assertEqual((rows[1]['allocationId'], rows[2]['replayed']), (submitted['allocationId'], True))
        usage = service_accounts.usage(self.conn, self.slug, 'render')
        self.conn.commit()
        self.assertEqual((usage['generationRequests'], usage['renderReservations']), (1, 0))


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'set OPENBENCH_TEST_DB_URI')
class AgentHttpTests(unittest.TestCase):
    def setUp(self):
        import test_product_http as product_fixture
        self.fixture = product_fixture.ProductHTTPTests
        self.fixture.setUp(self)

    def tearDown(self):
        self.fixture.tearDown(self)

    def request(self, *args, **kwargs):
        return self.fixture.request(self, *args, **kwargs)

    def agent(self, path, token, *, method='GET', data=None, headers=None):
        return self.request(path, method=method, data=data, authenticated=False,
                            headers={'Authorization': 'Bearer ' + token, **(headers or {})})

    def test_admin_routes_agent_api_and_stdio_client_end_to_end(self):
        base = f'/projects/api/{self.slug}/service-accounts'
        body = {'accountKey': 'claude-code', 'displayName': 'Claude Code',
                'tools': ['list_pages', 'read_page', 'propose_table_edit', 'get_workflow'],
                'expiresInDays': 3}
        self.assertEqual(self.request(base, method='POST', data=body, authenticated=False)[0], 401)
        self.assertEqual(self.request(base, method='POST', data=body, headers={'X-Requested-With': ''})[0], 403)
        code, issued, _ = self.request(base, method='POST', data=body)
        self.assertEqual(code, 200, issued)
        token = issued['token']
        code, listed, _ = self.request(base)
        self.assertEqual((code, [i['accountKey'] for i in listed['items']]), (200, ['claude-code']))
        self.assertNotIn(token, json.dumps(listed))
        self.assertNotIn(hashlib.sha256(token.encode()).hexdigest(), json.dumps(listed))
        code, tools, _ = self.agent('/agent-mcp/v1/tools', token)
        self.assertEqual((code, [t['name'] for t in tools['tools']]), (200, ['propose_table_edit', 'list_pages', 'read_page', 'get_workflow']))
        self.assertEqual(self.agent('/agent-mcp/v1/tools', token, headers={'Origin': 'http://evil.example'})[1]['code'], 'LOCAL_ONLY')
        self.assertEqual(self.agent('/agent-mcp/v1/tools', token, headers={'Cf-Connecting-Ip': '1.2.3.4'})[0], 403)
        self.assertEqual(self.agent('/agent-mcp/v1/tools', token, headers={'X-ZeroField-Project': 'another-one'})[1]['code'], 'WRONG_PROJECT')
        self.assertEqual(self.agent('/agent-mcp/v1/tools', self.member_token)[0], 401)  # a crew login is not an agent token
        self.assertEqual(self.agent('/agent-mcp/v1/tools/read_page', token)[0], 405)
        code, read, _ = self.agent('/agent-mcp/v1/tools/read_page', token, method='POST', data={'arguments': {'key': 'shots'}})
        self.assertEqual((code, read['isError']), (200, False))
        self.assertIn('Shot 1', read['text'])
        self.assertEqual(self.agent('/agent-mcp/v1/tools/spawn_agent', token, method='POST', data={'arguments': {}})[1]['code'], 'UNKNOWN_TOOL')
        server = mcp.Server(mcp.HttpBackend(f'http://127.0.0.1:{self.server.server_port}', token, self.slug, timeout=30))
        self.assertIn('2026-07-28', server.handle(rpc('server/discover'))['result']['supportedVersions'])
        self.assertEqual([t['name'] for t in server.handle(rpc('tools/list', 2))['result']['tools']],
                         ['propose_table_edit', 'list_pages', 'read_page', 'get_workflow'])
        manual = server.handle(rpc('tools/call', 6, name='get_workflow', arguments={'name': 'shot-beats'}))['result']
        self.assertFalse(manual['isError'])
        self.assertIn('name: shot-beats', manual['content'][0]['text'])
        self.assertIn('[The guide continues', manual['content'][0]['text'])
        legacy = mcp.Server(mcp.HttpBackend(f'http://127.0.0.1:{self.server.server_port}', token, timeout=30))
        legacy.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-11-25', 'capabilities': {}}})
        called = legacy.handle({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'list_pages', 'arguments': {}}})['result']
        self.assertFalse(called['isError'])
        self.assertIn('shots', called['content'][0]['text'])
        self.assertEqual(server.handle(rpc('tools/call', 3, name='spawn_agent', arguments={}))['error']['code'], mcp.INVALID_PARAMS)
        code, revoked, _ = self.request(base + '/claude-code/revoke', method='POST', data={})
        self.assertEqual((code, revoked['account']['status']), (200, 'revoked'))
        self.assertEqual(self.agent('/agent-mcp/v1/tools', token)[1]['code'], 'TOKEN_REVOKED')
        error = server.handle(rpc('tools/list', 4))['error']
        self.assertEqual((error['code'], error['data']['code']), (mcp.TOKEN_REFUSED, 'TOKEN_REVOKED'))


if __name__ == '__main__':
    unittest.main()
