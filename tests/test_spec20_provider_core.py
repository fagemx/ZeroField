"""SPEC_20 provider core: failure settlement (R1), local defaults (R2), no ChatGPT transport (R3), Ollama rounds (R4).

Loopback fake servers and synthetic openers only; no real model provider is called.
"""
import http.client
import io
import json
import os
import socket
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

from project_assistant import agent_registry, agent_runtime, model_client, providers, tools, tool_specs
from project_assistant import agent_console_store as console, execution_governance as gov, orchestration_store as db

REMOTE = 'https://priced-provider.invalid/v1'


def closed_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def reply(message, usage=None):
    return io.BytesIO(json.dumps({'choices': [{'message': message}], **({'usage': usage} if usage else {})}).encode())


class Recorder:
    """Duck-typed admission: records how each admitted round settled, no-op once settled."""
    response_limit = 2 * 1024 * 1024

    def __init__(self):
        self.active, self.settled = False, []

    def before(self, payload):
        self.active = True

    def after(self, usage, outcome='succeeded', *, known_terminated=False, observed_cost=None):
        if self.active:
            self.active = False
            self.settled.append((outcome, known_terminated, observed_cost))


class ProviderCoreTests(unittest.TestCase):
    def turn(self, base, opener=None, *, key='', admission=None, specs=(), call_tool=lambda *_: 'row'):
        return providers.run_openai_compat_turn(config=providers.ProviderConfig('openai_compat', base, key, 'fixture'),
            instructions='Fixture', turn_text='Plan', call_tool=call_tool, timeout=10, tool_specs=list(specs),
            admission=admission, **({'opener': opener} if opener else {}))

    def test_a5_local_defaults_and_effort_only_for_the_complete_default(self):
        config = providers.provider_from_env({})
        self.assertEqual((config.kind, config.base_url, config.model, config.effort, config.api_key),
                         ('openai_compat', 'http://127.0.0.1:11434/v1', 'qwen3.8:27b', 'medium', ''))
        for env in ({'OPENBENCH_API_BASE': 'http://10.0.0.8:8000/v1'}, {'OPENBENCH_MODEL': 'custom'}, {'PROJECT_ASSISTANT_MODEL': 'legacy'}):
            with self.subTest(env=env):
                self.assertIsNone(providers.provider_from_env(env).effort)
        self.assertEqual(providers.provider_from_env({'OPENBENCH_REASONING_EFFORT': 'high'}).effort, 'high')
        self.assertEqual(providers.provider_from_env({'OPENBENCH_MODEL': 'custom', 'OPENBENCH_REASONING_EFFORT': 'Low'}).effort, 'low')
        with self.assertRaises(ValueError):
            providers.provider_from_env({'OPENBENCH_REASONING_EFFORT': 'max'})
        # The removed alias is no longer translated into a transport.
        self.assertEqual(providers.provider_from_env({'OPENBENCH_PROVIDER': 'direct'}).kind, 'direct')
        self.assertTrue({'direct', 'responses'} <= providers.REMOVED_KINDS)
        # Agents on the deployment default inherit its effort; custom endpoints do not.
        self.assertEqual(agent_runtime.provider_for({'provider_config': {}}, env={}).effort, 'medium')
        self.assertIsNone(agent_runtime.provider_for({'provider_config': {'model': 'other'}}, env={}).effort)
        self.assertEqual(agent_runtime.provider_for({'provider_config': {}, 'effort': 'high', 'effort_configured': True}, env={}).effort, 'high')

    def test_a6_keyless_rule_reads_the_hostname_only(self):
        self.assertIs(gov.local_url, providers.local_url)
        for url in ('http://127.0.0.1:11434/v1', 'http://localhost:11434/v1', 'http://[::1]:11434/v1', 'http://LOCALHOST:1/v1'):
            self.assertTrue(providers.local_url(url), url)
        for url in ('https://example.com/localhost', 'https://localhost.example.com/v1', 'http://127.0.0.1.example.com/v1',
                    'https://example.com/v1?host=127.0.0.1', 'http://localhost@example.com/v1', 'http://[::1'):
            self.assertFalse(providers.local_url(url), url)
        for base in ('http://[::1]:11434/v1', 'http://localhost:11434/v1'):
            sent = []
            result = self.turn(base, lambda request, timeout: sent.append(request.full_url) or reply({'content': 'ok'}))
            self.assertEqual((result.status, sent), ('ok', [base + '/chat/completions']))
        sent = []
        result = self.turn('https://example.com/localhost', lambda *a, **k: sent.append(1))
        self.assertEqual((result.status, result.error_kind, sent), ('error', 'auth', []))

    def test_a13_no_tool_choice_and_the_last_round_offers_no_tools(self):
        bodies = []
        class Model(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                bodies.append(body)
                message = ({'content': '', 'tool_calls': [{'id': 'c%d' % len(bodies), 'type': 'function',
                            'function': {'name': 'read_page', 'arguments': '{"key":"shots"}'}}]} if 'tools' in body
                           else {'content': 'Answer from what was found'})
                raw = json.dumps({'choices': [{'message': message}]}).encode()
                self.send_response(200); self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Model)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        calls = []
        spec = [s for s in tool_specs.TOOLS if s['name'] == 'read_page']
        result = self.turn(f'http://127.0.0.1:{server.server_port}/v1', specs=spec, call_tool=lambda *a: calls.append(a) or 'row')
        self.assertEqual((result.status, result.answer, result.rounds), ('ok', 'Answer from what was found', model_client.MAX_ROUNDS))
        self.assertEqual((len(bodies), len(calls)), (16, 15))
        self.assertTrue(all('tool_choice' not in body for body in bodies))
        self.assertTrue(all('tools' in body for body in bodies[:15]))
        self.assertNotIn('tools', bodies[15])
        self.assertEqual(bodies[15]['messages'][-1], {'role': 'user', 'content': model_client.LAST_ROUND_NOTE})
        # A model that still emits calls on the last round never reaches the handlers again.
        calls.clear()
        stubborn = lambda request, timeout: reply({'content': '', 'tool_calls': [{'id': 'x', 'function': {'name': 'read_page', 'arguments': '{}'}}]})
        result = self.turn('http://127.0.0.1:9/v1', stubborn, specs=spec, call_tool=lambda *a: calls.append(a) or 'row')
        self.assertEqual((result.status, result.error_kind, len(calls)), ('error', 'bad_response', 15))

    def test_r1_failure_settlement_follows_the_destination_and_the_evidence(self):
        refused = urllib.error.URLError(ConnectionRefusedError(10061, 'refused'))
        dns = urllib.error.URLError(socket.gaierror(11001, 'getaddrinfo failed'))
        def raising(error):
            def opener(request, timeout):
                raise error
            return opener
        def http_error(code):
            return raising(urllib.error.HTTPError(REMOTE, code, 'fixture', {}, io.BytesIO(b'echoed synthetic-secret')))
        terminated, uncertain, local = ('failed', True, 0), ('unknown', False, None), ('failed', True, None)
        cases = [('remote refused', REMOTE, raising(refused), terminated, 'unavailable'),
                 ('remote dns', REMOTE, raising(dns), terminated, 'unavailable'),
                 *[(f'remote {code}', REMOTE, http_error(code), terminated, kind) for code, kind in
                   ((400, 'unavailable'), (401, 'auth'), (403, 'auth'), (404, 'unavailable'), (413, 'unavailable'), (422, 'unavailable'), (429, 'quota'))],
                 *[(f'remote {code}', REMOTE, http_error(code), uncertain, 'unavailable') for code in (500, 502, 503, 408)],
                 ('remote timeout', REMOTE, raising(TimeoutError('read')), uncertain, 'timeout'),
                 ('remote connect timeout', REMOTE, raising(urllib.error.URLError(TimeoutError('connect'))), uncertain, 'timeout'),
                 ('remote reset after send', REMOTE, raising(http.client.RemoteDisconnected('closed')), uncertain, 'unavailable'),
                 ('remote reset', REMOTE, raising(ConnectionResetError()), uncertain, 'unavailable'),
                 ('remote truncated', REMOTE, raising(http.client.IncompleteRead(b'')), uncertain, 'unavailable'),
                 ('remote oversize', REMOTE, lambda request, timeout: io.BytesIO(b' ' * (Recorder.response_limit + 1)), uncertain, 'bad_response'),
                 ('remote malformed', REMOTE, lambda request, timeout: io.BytesIO(b'not json'), uncertain, 'bad_response'),
                 ('local timeout', 'http://127.0.0.1:11434/v1', raising(TimeoutError('read')), local, 'timeout'),
                 ('local 500', 'http://localhost:11434/v1', http_error(500), local, 'unavailable'),
                 ('local reset', 'http://[::1]:11434/v1', raising(http.client.RemoteDisconnected('closed')), local, 'unavailable')]
        for name, base, opener, settled, kind in cases:
            with self.subTest(name):
                admission = Recorder()
                result = self.turn(base, opener, key='synthetic-secret', admission=admission)
                self.assertEqual(admission.settled, [settled])
                self.assertEqual(result.error_kind, kind)
                self.assertNotIn('synthetic-secret', result.error)
        admission = Recorder()
        result = self.turn('http://127.0.0.1:%d/v1' % closed_port(), admission=admission)
        self.assertEqual((admission.settled, result.error_kind), ([local], 'unavailable'))
        self.assertIn('not reachable', result.error); self.assertIn('Ollama', result.error)
        admission = Recorder()
        result = self.turn(REMOTE, lambda request, timeout: reply({'content': 'done'}, {'prompt_tokens': 3}), key='k', admission=admission)
        self.assertEqual((result.status, admission.settled), ('ok', [('succeeded', False, None)]))

    def test_r3_responses_kind_is_removed_everywhere(self):
        for name in ('URL', 'USER_AGENT', 'credentials', 'forget_credentials', 'request_body', 'stream_once', '_stream_with_retry', 'run_turn'):
            self.assertFalse(hasattr(model_client, name), name)
        for kind in ('responses', 'direct'):
            with self.subTest(kind=kind), self.assertRaises(agent_registry.AgentError) as raised:
                agent_registry.validate_provider({'kind': kind, 'model': 'fixture'})
            self.assertEqual((raised.exception.status, raised.exception.code), (400, 'kind_removed'))
            self.assertIn('removed', str(raised.exception))
        self.assertEqual(agent_registry.validate_provider({'kind': 'openai_compat', 'model': 'fixture'})['kind'], 'openai_compat')
        with self.assertRaises(agent_registry.AgentError):
            agent_registry.validate_provider({'kind': 'codex_cli', 'base_url': 'http://127.0.0.1:9/v1'})


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'set OPENBENCH_TEST_DB_URI')
class GovernedSettlementTests(unittest.TestCase):
    from orchestration_fixture import OrchestrationFixture as _fixture
    setUp = _fixture.setUp
    tearDown = _fixture.tearDown

    def factory(self):
        import psycopg
        return psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI'], connect_timeout=3)

    def context(self, name):
        ctx = tools.ToolContext(self.factory, self.slug, self.me, Path('.'), None)
        ctx.accounting_session_key = name
        return ctx

    def reservations(self):
        return db.many(self.conn, "SELECT jsonb_build_object('state',state,'cost',accounted_cost_usd,'ceiling',ceiling_cost_usd) FROM projectops.agent_usage_reservation WHERE project_slug=%s ORDER BY created_at", (self.slug,))

    def remote_agent(self):
        import governance_fixture
        governance_fixture.authorize_synthetic_media(self)  # full-network environment
        env = patch.dict(os.environ, {'OPENBENCH_AGENT_KEY_ENVS': 'SPEC20_FIXTURE_KEY', 'SPEC20_FIXTURE_KEY': 'synthetic-credential'})
        env.start(); self.addCleanup(env.stop)
        profile = agent_registry.save_agent(self.conn, self.me, self.slug, {'agent_key': 'coordinator', 'provider_config':
            {'kind': 'openai_compat', 'base_url': REMOTE, 'model': 'priced-fixture', 'api_key_env': 'SPEC20_FIXTURE_KEY'}})
        settings = console.get_settings(self.conn, self.me, self.slug)
        console.save_settings(self.conn, self.me, self.slug, {'version': settings['version'], 'model_pricing': {'priced-fixture': dict(
            kind='openai_compat', base_url=REMOTE, input_usd_per_million=1, output_usd_per_million=2, max_input_tokens=100000,
            max_output_tokens=10, byte_bounded_tokenizer=True)}})
        self.conn.commit()
        self.assertEqual(profile['max_concurrency'], 2)
        return profile

    def remote_turn(self, profile, name, opener):
        config = agent_runtime.provider_for(profile)
        return providers.run_openai_compat_turn(config=config, instructions='Fixture', turn_text='Plan', call_tool=lambda *_: '',
            timeout=10, tool_specs=[], opener=opener, admission=gov.ProviderAdmission(self.context(name), profile, config))

    def test_a1_local_endpoint_down_never_locks_the_role(self):
        profile = agent_registry.save_agent(self.conn, self.me, self.slug, {'agent_key': 'coordinator', 'provider_config':
            {'kind': 'openai_compat', 'base_url': 'http://127.0.0.1:%d/v1' % closed_port(), 'model': 'fixture'}})
        self.conn.commit()
        self.assertEqual(profile['max_concurrency'], 2)
        for turn in range(4):
            outcome = agent_runtime.run_agent(profile=profile, ctx=self.context('chat-%d' % turn), instructions='Fixture',
                                              turn_text='Plan the episode', timeout=20)
            self.assertEqual((outcome.status, outcome.kind), ('error', 'unavailable'), outcome.detail)
            self.assertIn('not reachable', outcome.detail)
        self.assertEqual([r['state'] for r in self.reservations()], ['finalized'] * 4)
        ledger = db.many(self.conn, "SELECT meta->>'outcome' FROM projectops.agent_usage_ledger WHERE project_slug=%s", (self.slug,))
        self.assertEqual(ledger, ['failed'] * 4)

    def test_a2_remote_rejections_settle_at_zero_and_hold_no_slot(self):
        profile = self.remote_agent()
        sent = []
        def rejected(code):
            def opener(request, timeout):
                sent.append(code)
                raise urllib.error.HTTPError(REMOTE, code, 'fixture', {}, io.BytesIO(b''))
            return opener
        for number, code in enumerate((401, 429, 401)):
            result = self.remote_turn(profile, 'reject-%d' % number, rejected(code))
            self.assertEqual(result.error_kind, 'auth' if code == 401 else 'quota')
        self.assertEqual([(r['state'], r['cost']) for r in self.reservations()], [('finalized', 0)] * 3)
        self.assertTrue(all(r['ceiling'] > 0 for r in self.reservations()))
        ledger = db.many(self.conn, "SELECT jsonb_build_object('observed',observed_cost_usd,'outcome',meta->>'outcome') FROM projectops.agent_usage_ledger WHERE project_slug=%s", (self.slug,))
        self.assertEqual(ledger, [{'observed': 0, 'outcome': 'failed'}] * 3)
        result = self.remote_turn(profile, 'after-rejections', lambda request, timeout: reply({'content': 'ok'}, {'prompt_tokens': 5, 'completion_tokens': 2}))
        self.assertEqual(result.status, 'ok')
        self.assertEqual(len(sent), 3)

    def test_a3_remote_timeout_stays_uncertain_and_frees_its_slot_after_the_hold(self):
        profile = self.remote_agent()
        def timeout(request, timeout):
            raise TimeoutError('synthetic read timeout')
        for number in range(2):
            self.assertEqual(self.remote_turn(profile, 'timeout-%d' % number, timeout).error_kind, 'timeout')
        rows = self.reservations()
        self.assertEqual([r['state'] for r in rows], ['uncertain'] * 2)
        self.assertTrue(all(r['cost'] == r['ceiling'] and r['cost'] > 0 for r in rows))
        success = lambda request, timeout: reply({'content': 'ok'})
        with self.assertRaisesRegex(gov.AdmissionError, 'concurrency'):
            self.remote_turn(profile, 'blocked', success)
        def age(seconds):
            db.execute(self.conn, "UPDATE projectops.agent_usage_reservation SET started_at=NOW()-%s*INTERVAL '1 second' WHERE project_slug=%s AND state='uncertain'", (seconds, self.slug))
            self.conn.commit()
        age(590)
        with self.assertRaisesRegex(gov.AdmissionError, 'concurrency'):
            self.remote_turn(profile, 'still-held', success)
        age(610)
        self.assertEqual(self.remote_turn(profile, 'after-hold', success).status, 'ok')
        budget = console.budget_summary(self.conn, self.me, self.slug)
        self.assertAlmostEqual(budget['uncertain_usd'], sum(r['ceiling'] for r in rows))  # spend stays until reconciled
        # The hold is an admin setting; zero frees uncertain slots at once, spend is unchanged.
        settings = console.get_settings(self.conn, self.me, self.slug)
        self.assertEqual(settings['rate_limits']['uncertain_hold_seconds'], 600)
        for bad in (-1, 86401, True, '600'):
            with self.subTest(bad=bad), self.assertRaises(agent_registry.AgentError):
                console.save_settings(self.conn, self.me, self.slug, {'version': settings['version'], 'rate_limits': {**settings['rate_limits'], 'uncertain_hold_seconds': bad}})
        saved = console.save_settings(self.conn, self.me, self.slug, {'version': settings['version'], 'rate_limits': {**settings['rate_limits'], 'uncertain_hold_seconds': 0}})
        self.assertEqual(saved['rate_limits']['uncertain_hold_seconds'], 0)
        # A draft written before the hold existed keeps the current hold.
        legacy = {k: v for k, v in saved['rate_limits'].items() if k != 'uncertain_hold_seconds'}
        saved = console.save_settings(self.conn, self.me, self.slug, {'version': saved['version'], 'rate_limits': legacy})
        self.assertEqual(saved['rate_limits']['uncertain_hold_seconds'], 0)
        self.conn.commit()

    def test_a11_stored_responses_kind_reports_kind_removed_without_network(self):
        from project_assistant import agent_console_service as app
        db.execute(self.conn, "UPDATE projectops.agent_profile SET provider_config='{\"kind\":\"responses\",\"model\":\"legacy\"}'::jsonb WHERE project_slug=%s AND agent_key='coordinator'", (self.slug,))
        self.conn.commit()
        profile = agent_registry.get_agent(self.conn, self.slug, 'coordinator')
        with patch('urllib.request.urlopen', side_effect=AssertionError('no network')), \
             patch.object(providers, 'run_openai_compat_turn', side_effect=AssertionError('no transport')):
            for check in (lambda: console.execution_resources(self.conn, self.me, self.slug, 'coordinator'),
                          lambda: app._profile(self.conn, self.me, self.slug, 'coordinator'),
                          lambda: agent_runtime.run_agent(profile=profile, ctx=self.context('removed'), instructions='', turn_text='Plan', timeout=5)):
                with self.assertRaises(agent_registry.AgentError) as raised:
                    check()
                self.assertEqual(raised.exception.code, 'kind_removed')
        self.assertEqual(self.reservations(), [])
        # A stale priced transport cannot be saved again either.
        settings = console.get_settings(self.conn, self.me, self.slug)
        with self.assertRaises(agent_registry.AgentError) as raised:
            console.save_settings(self.conn, self.me, self.slug, {'version': settings['version'], 'model_pricing': {'legacy': dict(
                kind='responses', base_url=REMOTE, input_usd_per_million=1, output_usd_per_million=2, max_input_tokens=10,
                max_output_tokens=10, byte_bounded_tokenizer=True)}})
        self.assertEqual(raised.exception.code, 'kind_removed')


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'set OPENBENCH_TEST_DB_URI')
class ReconcileHTTPTests(unittest.TestCase):
    from test_product_http import ProductHTTPTests as _fixture
    setUp = _fixture.setUp
    tearDown = _fixture.tearDown
    request = _fixture.request

    def uncertain(self, key, ceiling='.5000'):
        ctx = tools.ToolContext(lambda: None, self.slug, self.me, Path('.'), None)
        ctx.accounting_session_key = 'reconcile-fixture'
        gov.reserve(self.conn, ctx, request_key=key, agent_key='coordinator', usage_kind='llm_turn',
                    provider_name='openai_compat', model_name='priced-fixture', ceiling=ceiling)
        gov.dispatched(self.conn, self.slug, key)
        self.assertEqual(gov.finalize(self.conn, self.slug, key, outcome='unknown')['state'], 'uncertain')
        self.conn.commit()

    def reconcile(self, key, body, status):
        code, payload, _ = self.request(f'/projects/api/{self.slug}/agent-console/reservations/{quote(key, safe="")}/reconcile', method='POST', data=body)
        self.assertEqual(code, status, payload)
        return payload

    def row(self, key):
        return db.one(self.conn, 'SELECT to_jsonb(r) FROM projectops.agent_usage_reservation r WHERE project_slug=%s AND request_key=%s', (self.slug, key))

    def test_a4_admin_reconciles_uncertain_once_with_a_ledger_adjustment(self):
        key = 'call:spec20/uncertain'
        self.uncertain(key)
        for body in ({}, {'observedCostUsd': 0.0123}, {'observedCostUsd': '-1'}, {'observedCostUsd': '0.00001'}, {'observedCostUsd': '1', 'note': 'x'}):
            with self.subTest(body=body):
                self.reconcile(key, body, 400)
        result = self.reconcile(key, {'observedCostUsd': '0.0123'}, 200)['reservation']
        self.assertEqual((result['request_key'], result['state'], result['accounted_cost_usd']), (key, 'finalized', 0.0123))
        self.assertNotIn('owner_id', result); self.assertNotIn('session_key', result)
        self.conn.rollback()
        ledger = db.many(self.conn, 'SELECT to_jsonb(l) FROM projectops.agent_usage_ledger l WHERE project_slug=%s ORDER BY id', (self.slug,))
        self.assertEqual([l['event_key'] for l in ledger], [key, 'reconcile:' + key])
        original, adjustment = ledger
        self.assertEqual((original['meta']['outcome'], original['estimated_cost_usd']), ('unknown', 0.5))
        self.assertEqual((adjustment['meta']['outcome'], adjustment['observed_cost_usd'], adjustment['estimated_cost_usd'], adjustment['pricing_provenance']),
                         ('reconciled', 0.0123, 0, 'operator_reconciled'))
        self.assertEqual(adjustment['owner_id'], original['owner_id'])
        self.assertEqual(console.budget_summary(self.conn, self.me, self.slug)['uncertain_usd'], None)
        self.reconcile(key, {'observedCostUsd': '0.0100'}, 409)
        self.reconcile('call:missing', {'observedCostUsd': '0'}, 404)
        self.assertEqual(self.row(key)['accounted_cost_usd'], 0.0123)

    def test_a4_crew_member_cannot_reconcile(self):
        from project_docs import repository as repo
        self.uncertain('call:member')
        repo.upsert_member(self.conn, self.actor, 'Crew', 'member'); self.conn.commit()
        self.assertEqual(self.reconcile('call:member', {'observedCostUsd': '0'}, 403)['code'], 'POLICY_DENIED')
        self.assertEqual(self.row('call:member')['state'], 'uncertain')


if __name__ == '__main__':
    unittest.main()
