"""SPEC_20 R2 crew readiness on real PostgreSQL; only loopback fake model servers are ever probed."""
import datetime as dt
import json
import os
import socket
import threading
import unittest
import uuid
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from project_assistant import agent_console_store as console, agent_registry, agent_runtime, crew_readiness, store
from project_assistant import orchestrator as cp
from project_docs import repository as repo, service

CREW = ['coordinator', 'doc_writer', 'qa_critic', 'sheet_ops']  # list_agents order: seeded together, then by key
ENV = ('OPENBENCH_PROVIDER', 'PROJECT_ASSISTANT_ENGINE', 'OPENBENCH_API_BASE', 'OPENBENCH_API_KEY', 'OPENAI_API_KEY',
       'OPENBENCH_MODEL', 'PROJECT_ASSISTANT_MODEL', 'OPENBENCH_REASONING_EFFORT', 'OPENBENCH_AGENT_KEY_ENVS')
SECRET = 'sk-zf20-readiness-secret-0001'


class FakeModels:
    """An OpenAI-compatible /v1/models listing on loopback, in Ollama's shape."""

    def __init__(self, *ids, status=200, body=None):
        owner, self.ids, self.status, self.body, self.paths = self, list(ids), status, body, []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                owner.paths.append(self.path)
                data = owner.body if owner.body is not None else json.dumps({'object': 'list', 'data': [
                    {'id': name, 'object': 'model', 'owned_by': 'library'} for name in owner.ids]}).encode()
                self.send_response(owner.status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port
        self.base = f'http://127.0.0.1:{self.port}/v1'

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)


def closed_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'set OPENBENCH_TEST_DB_URI')
class ReadinessFixture(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.conn = psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI'])
        repo.ensure_schema(self.conn)
        self.conn.commit()
        self.slug = 'crew-ready-' + uuid.uuid4().hex[:12]
        self.actor = str(uuid.uuid4())
        self.me = service.Identity(self.actor, 'Readiness test', 'admin')
        repo.upsert_member(self.conn, self.actor, 'Readiness test', 'admin')
        repo.upsert_project(self.conn, self.slug, 'Readiness test')
        self.conn.commit()
        crew_readiness.forget()
        self.addCleanup(crew_readiness.forget)
        self.models = FakeModels('qwen3.8:27b')
        self.addCleanup(self.models.close)
        self.model_env(self.models.base)

    def tearDown(self):
        from psycopg import sql
        self.conn.rollback()
        with self.conn.cursor() as cur:
            cur.execute("SELECT table_name FROM information_schema.columns WHERE table_schema='projectops' AND column_name='project_slug'")
            for name in [r[0] for r in cur.fetchall() if r[0] not in ('agent_resource_revision', 'agent_usage_ledger')]:
                cur.execute(sql.SQL('DELETE FROM projectops.{} WHERE project_slug=%s').format(sql.Identifier(name)), (self.slug,))
            cur.execute('DELETE FROM projectops.project WHERE slug=%s', (self.slug,))
            cur.execute('DELETE FROM projectops.member WHERE actor_id=%s', (self.actor,))
        self.conn.commit()
        self.conn.close()

    def model_env(self, base, model='qwen3.8:27b', **extra):
        values = {'OPENBENCH_API_BASE': base, 'OPENBENCH_MODEL': model, **extra}
        patcher = patch.dict(os.environ, values)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ENV:
            if name not in values:
                os.environ.pop(name, None)

    def beat(self, seconds_ago=0):
        store.set_setting(self.conn, self.slug, 'builtin_worker_seen_at', (cp.now() - dt.timedelta(seconds=seconds_ago)).isoformat())
        self.conn.commit()

    def check(self):
        self.conn.commit()
        crew_readiness.forget(self.slug)
        return crew_readiness.readiness(self.conn, self.me, self.slug)

    def statuses(self):
        return {r['agent_key']: r['status'] for r in agent_registry.roster(self.conn, self.me, self.slug) if not r['agent_key'].startswith('limb:')}

    @staticmethod
    def found(payload, *fields):
        return [tuple(b.get(f) for f in fields) for b in payload['blockers']]


class ReadinessTests(ReadinessFixture):
    def test_a7_stopped_worker_blocks_the_crew_and_the_roster_needs_setup(self):
        payload = self.check()
        self.assertFalse(payload['ready'])
        self.assertEqual(payload['worker'], {'running': False, 'lastSeenAt': None})
        self.assertEqual(payload['blockers'], [{'code': 'worker_not_running', 'agentKey': None, 'fix': 'restart_without_no_worker'}])
        self.assertEqual(payload['providers'], [{'model': 'qwen3.8:27b', 'destination': 'local', 'host': '127.0.0.1', 'port': self.models.port,
            'tier': 'local_open', 'reachable': True, 'modelPresent': True, 'agents': CREW}])
        self.assertRegex(payload['checkedAt'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$')
        self.assertEqual(self.statuses(), dict.fromkeys(CREW, 'needs_setup'), 'never online without the worker')
        self.beat(100)
        self.assertEqual(self.found(self.check(), 'code'), [('worker_not_running',)], 'a stale heartbeat is no heartbeat')
        self.beat()
        payload = self.check()
        self.assertEqual((payload['ready'], payload['blockers'], payload['worker']['running']), (True, [], True))
        self.assertTrue(payload['worker']['lastSeenAt'].endswith('Z'))
        self.assertEqual(self.statuses(), dict.fromkeys(CREW, 'online'))

    def test_a8_unreachable_endpoint_missing_model_and_wrong_endpoint(self):
        self.beat()
        port = closed_port()
        self.model_env(f'http://127.0.0.1:{port}/v1')
        payload = self.check()
        self.assertEqual(self.found(payload, 'code', 'agentKey', 'fix', 'port'), [('provider_unreachable', k, 'start_ollama', port) for k in CREW])
        self.assertEqual((payload['providers'][0]['reachable'], payload['providers'][0]['modelPresent']), (False, None))
        self.assertEqual(self.statuses(), dict.fromkeys(CREW, 'needs_setup'), 'a heartbeat alone is not online')
        self.model_env(self.models.base)
        self.models.ids = ['llama3:latest']
        payload = self.check()
        self.assertEqual(self.found(payload, 'code', 'agentKey', 'fix', 'model'), [('model_missing', k, 'ollama_pull', 'qwen3.8:27b') for k in CREW])
        self.assertEqual((payload['providers'][0]['reachable'], payload['providers'][0]['modelPresent']), (True, False))
        self.model_env(self.models.base, 'llama3')
        self.assertTrue(self.check()['ready'], 'Ollama lists an untagged pull as :latest')
        self.model_env(self.models.base, 'served-model')
        self.assertEqual(self.found(self.check(), 'code', 'fix'), [('model_missing', 'load_model')] * 4, 'not an Ollama name or port')
        self.model_env(f'http://127.0.0.1:{port}/v1', 'served-model')
        self.assertEqual(self.found(self.check(), 'fix'), [('start_model_server',)] * 4)
        self.model_env(self.models.base)
        self.models.status = 404
        self.assertEqual(self.found(self.check(), 'code', 'fix'), [('provider_unreachable', 'check_endpoint')] * 4)
        self.models.status, self.models.body = 200, b'<html>not a model server</html>'
        self.assertEqual(self.found(self.check(), 'fix'), [('check_endpoint',)] * 4)
        self.models.status, self.models.body = 401, None
        payload = self.check()
        self.assertEqual((payload['ready'], payload['providers'][0]['modelPresent']), (True, None), 'up but private: nothing to block on')
        self.assertTrue(all(path == '/v1/models' for path in self.models.paths))

    def test_a9_remote_endpoint_reports_host_only_and_no_keys(self):
        self.beat()
        self.model_env('https://models.example.test/v1', 'hosted-model', OPENBENCH_API_KEY=SECRET)
        with patch.object(crew_readiness, '_open', side_effect=AssertionError('non-local endpoints are never probed')):
            payload = self.check()
        self.assertEqual(payload['providers'], [{'model': 'hosted-model', 'destination': 'remote', 'host': 'models.example.test',
            'tier': 'closed', 'reachable': None, 'modelPresent': None, 'agents': CREW}])
        # SPEC_20 R9: an endpoint the catalog doesn't know is closed, which open_weights_only forbids first.
        self.assertEqual(self.found(payload, 'code', 'agentKey', 'fix', 'host'),
            [('network_policy', k, 'use_hybrid_policy', 'models.example.test') for k in CREW] + [('pricing_missing', k, 'set_model_pricing', 'models.example.test') for k in CREW])
        from project_docs import story_openapi as story
        story.store(self.conn, 'policy_' + self.slug, 'policy', {'productionPolicy': 'hybrid_studio'}, self.slug)
        with patch.object(crew_readiness, '_open', side_effect=AssertionError('non-local endpoints are never probed')):
            payload = self.check()
        self.assertEqual(self.found(payload, 'code', 'agentKey', 'fix', 'host'),
            [('network_policy', k, 'allow_host', 'models.example.test') for k in CREW] + [('pricing_missing', k, 'set_model_pricing', 'models.example.test') for k in CREW])
        text = json.dumps(payload)
        for leaked in (SECRET, 'https://', '/v1', 'api_key'):
            self.assertNotIn(leaked, text)
        self.model_env('https://models.example.test/v1', 'hosted-model')
        self.assertIn(('auth_missing', 'set_api_key'), self.found(self.check(), 'code', 'fix'))
        self.model_env('https://models.example.test/v1', 'hosted-model', OPENBENCH_API_KEY=SECRET)
        env = console.get_resource(self.conn, self.me, self.slug, 'environment', 'env_local_4090')
        env = console.save_resource(self.conn, self.me, self.slug, 'environment', {'env_key': 'env_local_4090', 'version': env['version'],
            'network_access': 'allowlist', 'allowed_hosts': ['models.example.test']})
        settings = console.get_settings(self.conn, self.me, self.slug)
        console.save_settings(self.conn, self.me, self.slug, {'version': settings['version'], 'model_pricing': {'hosted-model': {
            'input_usd_per_million': 1, 'output_usd_per_million': 2, 'max_input_tokens': 8000, 'max_output_tokens': 1000,
            'byte_bounded_tokenizer': True, 'base_url': 'https://models.example.test/v1', 'kind': 'openai_compat'}}})
        self.assertTrue(self.check()['ready'], 'allowed host, key and a bound price: nothing left to fix')
        repo.update_project_meta(self.conn, self.slug, privacy_mode='mask_numbers')
        self.assertEqual(self.found(self.check(), 'code', 'fix'), [('network_policy', 'keep_local')] * 4)
        repo.update_project_meta(self.conn, self.slug, privacy_mode='full_access')
        console.save_resource(self.conn, self.me, self.slug, 'environment', {'env_key': 'env_local_4090', 'version': env['version'], 'enabled': False})
        self.assertEqual(self.found(self.check(), 'code', 'fix'), [('network_policy', 'enable_environment')] * 4)

    def test_a11_removed_kind_cli_disabled_crew_and_held_reservations(self):
        self.beat()
        with self.conn.cursor() as cur:
            cur.execute('''UPDATE projectops.agent_profile SET provider_config='{"kind":"responses"}'::jsonb WHERE project_slug=%s''', (self.slug,))
        calls = []
        with patch.object(crew_readiness, '_open', side_effect=lambda request, timeout: calls.append(request.full_url)):
            payload = self.check()
        self.assertEqual(self.found(payload, 'code', 'agentKey', 'fix'), [('kind_removed', k, 'reconfigure_provider') for k in CREW])
        self.assertEqual((calls, payload['providers']), ([], []), 'a stored responses transport is never contacted')
        with self.conn.cursor() as cur:
            cur.execute('''UPDATE projectops.agent_profile SET provider_config='{}'::jsonb WHERE project_slug=%s''', (self.slug,))
        self.model_env(self.models.base, OPENBENCH_PROVIDER='direct')
        self.assertEqual(self.found(self.check(), 'code'), [('kind_removed',)] * 4, 'the deployment alias of the removed transport')
        self.model_env(self.models.base)
        original = agent_registry.effective_profile
        def validated(conn, profile):  # how a validating reader may refuse a stored removed transport
            if profile['agent_key'] == 'qa_critic':
                raise agent_registry.AgentError(409, 'Stored model settings use a removed transport.', 'kind_removed')
            return original(conn, profile)
        with patch.object(agent_registry, 'effective_profile', side_effect=validated):
            self.assertEqual(self.found(self.check(), 'code', 'agentKey'), [('kind_removed', 'qa_critic')])
        with patch.object(agent_runtime, 'provider_for', side_effect=ValueError('Unsupported model runtime: responses')):
            self.assertEqual(self.found(self.check(), 'code'), [('kind_removed',)] * 4)
        agent_registry.save_agent(self.conn, self.me, self.slug, {'agent_key': 'doc_writer', 'provider_config': {'kind': 'codex_cli'}})
        agent_registry.save_agent(self.conn, self.me, self.slug, {'agent_key': 'qa_critic', 'enabled': False})
        agent_registry.save_agent(self.conn, self.me, self.slug, {'agent_key': 'custom_off', 'enabled': False})
        payload = self.check()
        self.assertEqual(self.found(payload, 'code', 'agentKey', 'fix'), [('cli_blocked', 'doc_writer', 'use_builtin_provider'), ('agent_disabled', 'qa_critic', 'enable_agent')])
        roster = self.statuses()
        self.assertEqual((roster['doc_writer'], roster['qa_critic'], roster['custom_off'], roster['coordinator']), ('needs_setup', 'needs_setup', 'offline', 'online'))

    def reservation(self, key, agent, seconds_ago, state='uncertain', category='llm'):
        with self.conn.cursor() as cur:
            cur.execute('''INSERT INTO projectops.agent_usage_reservation(project_slug,request_key,session_key,owner_id,agent_key,usage_kind,category,
                provider_name,model_name,tier,pricing_provenance,state,lease_until,started_at) VALUES(%s,%s,'s',%s,%s,'llm_turn',%s,'openai_compat','m','open_weights','unknown',%s,%s,%s)''',
                (self.slug, key, self.actor, agent, category, state, cp.now() - dt.timedelta(seconds=seconds_ago - 1),
                 cp.now() - dt.timedelta(seconds=seconds_ago)))

    def test_held_reservations_block_until_the_hold_expires(self):
        self.beat()
        self.reservation('a', 'sheet_ops', 30)
        self.reservation('b', 'sheet_ops', 60, state='dispatched')  # its lease ran out: settled as uncertain on next admission
        self.reservation('c', 'sheet_ops', 700)
        self.reservation('d', 'doc_writer', 10, state='dispatched', category='render')
        payload = self.check()
        self.assertEqual(payload['blockers'], [{'code': 'reservations_stuck', 'agentKey': 'sheet_ops', 'fix': 'reconcile_reservations', 'count': 2, 'minutes': 10}])
        self.assertEqual(self.statuses()['sheet_ops'], 'needs_setup')
        with self.conn.cursor() as cur:
            cur.execute('''UPDATE projectops.agent_console_settings SET rate_limits=rate_limits||'{"uncertain_hold_seconds":20}'::jsonb WHERE project_slug=%s''', (self.slug,))
        self.assertTrue(self.check()['ready'], 'past the configured hold they no longer take a slot')
        with self.conn.cursor() as cur:
            cur.execute('''UPDATE projectops.agent_console_settings SET rate_limits=rate_limits||'{"uncertain_hold_seconds":900}'::jsonb WHERE project_slug=%s''', (self.slug,))
        self.reservation('e', 'coordinator', 5)
        payload = self.check()
        self.assertEqual(self.found(payload, 'code', 'agentKey', 'count', 'minutes'), [('reservations_stuck', None, 4, 15)],
                         'four held calls fill the production model slots; one line, not one per agent')
        self.assertEqual(self.statuses(), dict.fromkeys(CREW, 'needs_setup'))

    def test_cache_refresh_limit_and_a_roster_that_never_probes(self):
        clock = [1000.0]
        self.beat()
        patcher = patch.object(crew_readiness, '_clock', lambda: clock[0])
        patcher.start()
        self.addCleanup(patcher.stop)
        read = lambda refresh=False: crew_readiness.readiness(self.conn, self.me, self.slug, refresh=refresh)
        self.assertTrue(read()['ready'])
        self.models.ids = []
        clock[0] += 10
        self.assertTrue(read()['ready'], 'served from the 30 s cache')
        self.assertEqual(len(self.models.paths), 1)
        clock[0] += 1
        self.assertFalse(read(refresh=True)['ready'], 'refresh bypasses the cache')
        self.models.ids = ['qwen3.8:27b']
        clock[0] += 3
        self.assertFalse(read(refresh=True)['ready'], 'at most one forced recheck every 5 s')
        clock[0] += 2
        self.assertTrue(read(refresh=True)['ready'])
        self.assertEqual(len(self.models.paths), 3)
        self.models.ids = []
        clock[0] += 31
        self.assertFalse(read()['ready'], 'the cache expires after 30 s')
        with patch.object(crew_readiness, '_probe', side_effect=AssertionError('the roster never probes')):
            self.assertEqual(self.statuses(), dict.fromkeys(CREW, 'needs_setup'), 'fresh cache')
            clock[0] += 100
            self.assertEqual(self.statuses(), dict.fromkeys(CREW, 'needs_setup'), 'stale cache, remembered probe')
            clock[0] += 600
            self.assertEqual(self.statuses(), dict.fromkeys(CREW, 'online'), 'nothing remembered: no probe, no guess')
        clock[0] += 31
        self.assertFalse(read()['ready'], 'an unprobed roster entry is never served as readiness')
        self.assertEqual(len(self.models.paths), 5)

    def test_any_member_reads_it_and_a_stranger_cannot(self):
        viewer = service.Identity(self.actor, 'Viewer', 'viewer')
        repo.upsert_member(self.conn, self.actor, 'Viewer', 'viewer')
        self.conn.commit()
        self.assertIn('blockers', crew_readiness.readiness(self.conn, viewer, self.slug))
        stranger = service.Identity(str(uuid.uuid4()), 'Stranger', 'admin')
        with self.assertRaises(agent_registry.AgentError) as denied:
            crew_readiness.readiness(self.conn, stranger, self.slug)
        self.assertEqual(denied.exception.status, 403)
        with self.assertRaises(agent_registry.AgentError) as missing:
            crew_readiness.readiness(self.conn, self.me, 'no-such-production')
        self.assertEqual(missing.exception.status, 404)


class ReadinessHTTPTests(ReadinessFixture):
    def setUp(self):
        super().setUp()
        import psycopg
        from project_docs import http
        from server import OpenBenchHandler
        self.token = 'crew-readiness-token-' + self.actor
        for patcher in (patch.dict(os.environ, {'OPENBENCH_AUTH_MODE': 'token', 'OPENBENCH_TOKENS': json.dumps({self.token: self.actor})}),
                        patch.object(http, '_CONN_FACTORY', lambda: psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI']))):
            patcher.start()
            self.addCleanup(patcher.stop)

        class Handler(OpenBenchHandler):
            def log_message(self, *args):
                pass
        self.app = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.app.serve_forever, daemon=True).start()
        self.addCleanup(self.app.server_close)
        self.addCleanup(self.app.shutdown)

    def get(self, path, method='GET', token=True):
        connection = HTTPConnection('127.0.0.1', self.app.server_port, timeout=10)
        try:
            connection.request(method, path, headers={'X-Requested-With': 'projects', **({'Authorization': 'Bearer ' + self.token} if token else {})})
            response = connection.getresponse()
            return response.status, json.loads(response.read() or b'null')
        finally:
            connection.close()

    def test_route_for_members_next_to_the_roster(self):
        path = f'/projects/api/{self.slug}/agents/readiness'
        status, payload = self.get(path)
        self.assertEqual(status, 200, payload)
        self.assertEqual(set(payload), {'ready', 'checkedAt', 'worker', 'providers', 'blockers'})
        self.assertEqual(payload['blockers'][0]['code'], 'worker_not_running')
        status, roster = self.get(f'/projects/api/{self.slug}/agents')
        self.assertEqual(status, 200)
        self.assertEqual({a['agent_key']: a['status'] for a in roster['agents'] if a['agent_key'] in CREW}, dict.fromkeys(CREW, 'needs_setup'))
        self.beat()
        self.assertEqual(self.get(path)[1]['blockers'][0]['code'], 'worker_not_running', 'cached for 30 s')
        self.assertTrue(self.get(path + '?refresh=1')[1]['ready'])
        repo.upsert_member(self.conn, self.actor, 'Viewer', 'viewer')
        self.conn.commit()
        self.assertEqual(self.get(path)[0], 200, 'read access is enough')
        self.assertEqual(self.get(path, method='POST')[0], 404)
        self.assertEqual(self.get(path, token=False)[0], 401)
        self.assertEqual(self.get(f'/projects/api/no-such-production/agents/readiness')[0], 404)
        repo.upsert_member(self.conn, self.actor, 'Gone', 'viewer', status='inactive')
        self.conn.commit()
        self.assertEqual(self.get(path)[0], 403)


if __name__ == '__main__':
    unittest.main()
