"""SPEC_20 R8 catalog and capability shaping, R9 tiers, R10 context budget, R12 failure classes.

Synthetic openers and fake configurations only. A socket guard fails any test that reaches the
live Ollama port; hosted endpoints are never contacted (every remote call goes to an opener).
"""
import io
import json
import os
import socket
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from project_assistant import agent_registry, agent_runtime, model_client, provider_catalog, providers, tools, worker
from project_assistant import agent_console_store as console, execution_governance as gov, orchestration_store as db
from project_assistant import orchestration_service

OLLAMA_PORT = 11434
OPENROUTER = 'https://openrouter.ai/api/v1'
HOSTED_MODEL = 'qwen/qwen3.8-27b'
PNG = 'data:image/png;base64,' + 'iVBORw0KGgo' * 3000  # ~33 KB of base64: estimated per image, not per byte
CAPS = dict(tools=True, tool_choice=False, json_schema=False, vision=True, image_url=False)
_connect = socket.socket.connect
_guard = None


def setUpModule():
    global _guard
    def connect(self, address):
        if isinstance(address, tuple) and len(address) >= 2 and address[1] == OLLAMA_PORT:
            raise AssertionError('A test reached the live Ollama port; use a synthetic opener.')
        return _connect(self, address)
    _guard = patch.object(socket.socket, 'connect', connect)
    _guard.start()


def tearDownModule():
    _guard.stop()


def reply(message, **extra):
    return io.BytesIO(json.dumps({'choices': [{'message': message}], **extra}).encode())


class Wire:
    """Opener that records each request body and answers from a script."""

    def __init__(self, *answers, **extra):
        self.answers, self.extra, self.bodies, self.urls = list(answers), extra, [], []

    def __call__(self, request, timeout):
        self.urls.append(request.full_url)
        self.bodies.append(json.loads(request.data))
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return reply(answer, **self.extra)


def config(base='http://127.0.0.1:11434/v1', model='qwen3.8:27b', key='', effort=None):
    return providers.ProviderConfig('openai_compat', base, key, model, effort)


def turn(cfg, wire, **kw):
    kw.setdefault('tool_specs', [])
    return providers.run_openai_compat_turn(config=cfg, instructions=kw.pop('instructions', 'System'), turn_text=kw.pop('turn_text', 'Plan'),
                                            call_tool=kw.pop('call_tool', lambda *_: 'row'), timeout=10, opener=wire, **kw)


def tiny(context_tokens, **caps):
    return provider_catalog.Entry('tiny', 'Tiny', 'openai_compat', 'http://127.0.0.1:9/v1', 'tiny', 'local_open',
                                  {**CAPS, **caps}, context_tokens, 64)


READ = [{'name': 'read_page', 'description': 'Read a page.', 'inputSchema': {'type': 'object', 'properties': {}}}]


class CatalogTests(unittest.TestCase):
    def test_presets_match_by_endpoint_and_model_and_unknowns_stay_usable(self):
        default = provider_catalog.match(providers.provider_from_env({}))
        self.assertEqual((default.id, default.tier, default.context_tokens, default.default_effort), ('ollama-qwen3.8-27b', 'local_open', 16384, 'medium'))
        self.assertEqual(default.capabilities, {'tools': True, 'tool_choice': False, 'json_schema': True, 'vision': True, 'image_url': False})
        for base, model in (('http://localhost:11434/v1/', 'qwen3.8:27b'), ('http://[::1]:11434/v1', 'qwen3.8:27b-16k')):
            self.assertEqual(provider_catalog.match(config(base, model)).id, 'ollama-qwen3.8-27b', base)
        hosted = provider_catalog.match(config(OPENROUTER, HOSTED_MODEL, 'k'))
        self.assertEqual((hosted.id, hosted.tier, hosted.api_key_env, hosted.can('tool_choice')), ('openrouter-qwen3.8-27b', 'hosted_open', 'OPENROUTER_API_KEY', True))
        self.assertIn('reference', hosted.price)
        for cfg, tier in ((config(OPENROUTER, 'openai/gpt-5', 'k'), 'closed'), (config('https://models.example.test/v1', 'x', 'k'), 'closed'),
                          (config('http://127.0.0.1:8000/v1', 'qwen3.8:27b'), 'local_open'), (config('http://127.0.0.1:11434/v2', 'qwen3.8:27b'), 'local_open')):
            entry = provider_catalog.match(cfg)
            self.assertEqual((entry.id, entry.matched, entry.tier), (None, False, tier), cfg)
            self.assertEqual((entry.capabilities, entry.context_tokens), ({'tools': True, 'tool_choice': False, 'json_schema': False, 'vision': True, 'image_url': False}, 8192))
        self.assertEqual(provider_catalog.match(config('https://openrouter.ai.evil.test/api/v1', HOSTED_MODEL, 'k')).tier, 'closed')

    def test_closed_presets_are_listed_only_under_hybrid_and_entries_validate(self):
        self.assertEqual({e.tier for e in provider_catalog.entries('open_weights_only')}, {'local_open', 'hosted_open'})
        self.assertIn('closed', {e.tier for e in provider_catalog.entries('hybrid_studio')})
        self.assertNotIn('api_key', json.dumps([e.public() for e in provider_catalog.entries('hybrid_studio')]).replace('api_key_env', ''))
        raw = json.loads(provider_catalog.PATH.read_text(encoding='utf-8'))
        good = raw['entries'][0]
        for bad in ({**good, 'base_url': 'https://remote.example.test/v1'}, {**good, 'capabilities': {**good['capabilities'], 'tools': 'yes'}},
                    {**good, 'default_effort': 'max'}, {**raw['entries'][1], 'price': None}, {**raw['entries'][1], 'base_url': 'http://openrouter.ai/api/v1'}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                provider_catalog._entry(bad)

    def test_tier_policy_matrix(self):
        cases = {('local_open', 'open_weights_only', False): None, ('local_open', 'hybrid_studio', False): None,
                 ('hosted_open', 'open_weights_only', False): 'hosted_open_disabled', ('hosted_open', 'open_weights_only', True): None,
                 ('hosted_open', 'hybrid_studio', False): None, ('closed', 'open_weights_only', True): 'closed_needs_hybrid',
                 ('closed', 'hybrid_studio', False): None}
        for (tier, policy, hosted), expected in cases.items():
            with self.subTest(tier=tier, policy=policy, hosted=hosted):
                self.assertEqual(provider_catalog.denial(tier, policy, hosted_open_enabled=hosted), expected)
        self.assertEqual(provider_catalog.denial('closed', 'nonsense'), 'unknown_tier')
        self.assertEqual(provider_catalog.denial('hosted_open', 'open_weights_only', hosted_open_enabled='true'), 'hosted_open_disabled')


class ShapingTests(unittest.TestCase):
    def test_ollama_never_gets_tool_choice_and_json_schema_uses_response_format(self):
        schema = {'name': 'beats', 'schema': {'type': 'object', 'properties': {'setup': {'type': 'string'}}}}
        wire = Wire({'content': '```json\n{"setup": "rain"}\n```'})
        result = turn(config(), wire, json_schema=schema, tool_choice='required')
        self.assertEqual((result.status, result.answer), ('ok', '{"setup": "rain"}'))
        body = wire.bodies[0]
        self.assertNotIn('tool_choice', body)
        self.assertEqual(body['response_format'], {'type': 'json_schema', 'json_schema': schema})
        self.assertNotIn('JSON Schema', body['messages'][0]['content'])
        # With tools on offer the format would block tool calls: the schema moves into the prompt instead.
        wire = Wire({'content': '', 'tool_calls': [{'id': 'c1', 'function': {'name': 'read_page', 'arguments': '{}'}}]}, {'content': '{"setup": "x"}'})
        result = turn(config(), wire, json_schema=schema, tool_specs=READ, tool_choice='required')
        self.assertEqual(result.status, 'ok')
        self.assertTrue(all('tool_choice' not in b and 'response_format' not in b for b in wire.bodies))
        self.assertIn('JSON Schema', wire.bodies[0]['messages'][0]['content'])

    def test_unknown_models_get_the_schema_in_the_prompt_and_bad_json_is_an_output_failure(self):
        schema = {'name': 'beats', 'schema': {'type': 'object'}}
        wire = Wire({'content': 'Sure! Here are the beats.'})
        result = turn(config('http://127.0.0.1:9/v1', 'custom'), wire, json_schema=schema)
        self.assertNotIn('response_format', wire.bodies[0])
        self.assertIn('JSON Schema', wire.bodies[0]['messages'][0]['content'])
        self.assertEqual((result.status, result.error_kind, result.failure), ('error', 'output', 'output'))
        with self.assertRaises(ValueError):
            turn(config(), Wire({'content': '{}'}), json_schema={'schema': 'not an object'})

    def test_hosted_tool_choice_is_sent_only_with_tools_and_only_when_asked(self):
        hosted = config(OPENROUTER, HOSTED_MODEL, 'synthetic-key')
        wire = Wire({'content': '', 'tool_calls': [{'id': 'c1', 'function': {'name': 'read_page', 'arguments': '{}'}}]}, {'content': 'done'})
        self.assertEqual(turn(hosted, wire, tool_specs=READ, tool_choice='auto').status, 'ok')
        self.assertEqual([b.get('tool_choice') for b in wire.bodies], ['auto', 'auto'])
        wire = Wire({'content': 'done'})
        turn(hosted, wire, tool_specs=READ)
        self.assertNotIn('tool_choice', wire.bodies[0])
        wire = Wire({'content': 'done'})
        turn(config('http://127.0.0.1:9/v1', 'no-tools'), wire, tool_specs=READ, entry=tiny(4096, tools=False))
        self.assertNotIn('tools', wire.bodies[0])

    def test_images_are_inlined_from_storage_and_remote_links_are_not_fetched(self):
        reads = []
        def read_media(url):
            reads.append(url)
            return 'image/png', b'\x89PNG fixture'
        studio = '/projects/api/demo/assets/pa_' + 'a' * 32
        wire = Wire({'content': 'seen'})
        result = turn(config(), wire, images=[PNG, studio, 'http://127.0.0.1:3020' + studio], read_media=read_media)
        self.assertEqual(result.status, 'ok')
        urls = [p['image_url']['url'] for p in wire.bodies[0]['messages'][1]['content'][1:]]
        self.assertEqual(urls[0], PNG)
        self.assertTrue(all(u.startswith('data:image/png;base64,') for u in urls))
        self.assertEqual(reads, [studio, 'http://127.0.0.1:3020' + studio])
        # Ollama takes no links: a remote image is refused before anything is sent.
        wire = Wire({'content': 'never'})
        result = turn(config(), wire, images=['https://cdn.example.test/still.png'], read_media=read_media)
        self.assertEqual((result.status, result.failure, wire.bodies), ('error', 'provider', []))
        # A model that fetches links gets the remote link as is; studio media is still inlined.
        wire = Wire({'content': 'seen'})
        turn(config(OPENROUTER, HOSTED_MODEL, 'k'), wire, images=['https://cdn.example.test/still.png', studio], read_media=read_media)
        urls = [p['image_url']['url'] for p in wire.bodies[0]['messages'][1]['content'][1:]]
        self.assertEqual(urls[0], 'https://cdn.example.test/still.png')
        self.assertTrue(urls[1].startswith('data:image/png;base64,'))
        # Studio media with no reader is refused rather than fetched over HTTP.
        self.assertEqual(turn(config(), Wire({'content': 'x'}), images=[studio]).failure, 'provider')
        # A model without vision gets a note instead of the pictures.
        wire = Wire({'content': 'text only'})
        turn(config('http://127.0.0.1:9/v1', 'blind'), wire, images=[PNG], entry=tiny(4096, vision=False))
        self.assertEqual(wire.bodies[0]['messages'][1]['content'], 'Plan' + providers.NO_VISION.format(n=1))


class ContextBudgetTests(unittest.TestCase):
    def test_estimate_counts_images_by_the_catalog_not_by_base64_bytes(self):
        entry = tiny(4096)
        text_only = providers.estimate_tokens({'messages': [{'role': 'user', 'content': 'hello'}]}, entry)
        with_image = providers.estimate_tokens({'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': 'hello'}, {'type': 'image_url', 'image_url': {'url': PNG}}]}]}, entry)
        self.assertLess(with_image - text_only, entry.image_tokens + 40)

    def test_oldest_history_goes_first_and_the_system_prompt_and_latest_turn_stay(self):
        history = [{'role': 'user' if n % 2 == 0 else 'assistant', 'content': f'turn {n} ' + 'h' * 300} for n in range(10)]
        wire = Wire({'content': 'answer'})
        result = turn(config('http://127.0.0.1:9/v1', 'tiny'), wire, entry=tiny(1000), history=history,
                      instructions='System rules', turn_text='The latest question')
        messages = wire.bodies[0]['messages']
        self.assertEqual((messages[0]['content'], messages[-1]['content']), ('System rules', 'The latest question'))
        kept = [m['content'].split(' ')[1] for m in messages[1:-1]]
        self.assertTrue(kept and kept == [str(n) for n in range(10 - len(kept), 10)], kept)
        self.assertEqual(result.trimmed['history'], 10 - len(kept))
        self.assertFalse(result.trimmed['over_budget'])
        self.assertLessEqual(result.trimmed['estimated_tokens'], result.trimmed['budget_tokens'])
        # Nothing is cut when everything fits.
        wire = Wire({'content': 'answer'})
        self.assertEqual(turn(config(), wire, history=history[:2]).trimmed, {})
        self.assertEqual(len(wire.bodies[0]['messages']), 4)

    def test_older_tool_outputs_are_trimmed_but_the_latest_round_is_kept(self):
        calls = [{'content': '', 'tool_calls': [{'id': f'c{n}', 'function': {'name': 'read_page', 'arguments': '{}'}}]} for n in range(3)]
        wire = Wire(*calls, {'content': 'summary'})
        outputs = iter(f'output {n} ' + 'x' * 1500 for n in range(3))
        result = turn(config('http://127.0.0.1:9/v1', 'tiny'), wire, entry=tiny(1000), tool_specs=READ, call_tool=lambda *_: next(outputs))
        self.assertEqual(result.status, 'ok')
        tools_seen = [m['content'] for m in wire.bodies[-1]['messages'] if m['role'] == 'tool']
        self.assertEqual(tools_seen[:2], [providers.TRIMMED_TOOL] * 2)
        self.assertTrue(tools_seen[2].startswith('output 2 '))
        self.assertGreaterEqual(result.trimmed['tool_outputs'], 2)
        # A prompt that cannot fit is still sent, and the result says it was over budget.
        wire = Wire({'content': 'ok'})
        result = turn(config('http://127.0.0.1:9/v1', 'tiny'), wire, entry=tiny(1000), instructions='S' * 6000)
        self.assertEqual((result.status, result.trimmed['over_budget'], len(wire.bodies)), ('ok', True, 1))


class PricingTests(unittest.TestCase):
    def test_hosted_vision_is_priced_with_the_catalog_image_bound(self):
        price = {'model_pricing': {HOSTED_MODEL: dict(kind='openai_compat', base_url=OPENROUTER, input_usd_per_million=1, output_usd_per_million=2,
                                                      max_input_tokens=20000, max_output_tokens=10, byte_bounded_tokenizer=True)}}
        hosted = config(OPENROUTER, HOSTED_MODEL, 'k')
        message = lambda n: {'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': 'look'}] + [{'type': 'image_url', 'image_url': {'url': PNG}}] * n}]}
        self.assertIsNotNone(gov.price_bound(price, hosted, message(1))[0])
        with self.assertRaisesRegex(gov.AdmissionError, 'input-token ceiling'):
            gov.price_bound(price, hosted, message(2))  # 2 x 16384 image tokens exceed 20000
        # A text mention of image_url is not a picture.
        self.assertIsNotNone(gov.price_bound(price, hosted, {'messages': [{'role': 'user', 'content': 'what is image_url?'}]})[0])
        local = {'model_pricing': {HOSTED_MODEL: {**price['model_pricing'][HOSTED_MODEL], 'base_url': 'http://127.0.0.1:9/v1'}}}
        self.assertEqual(gov.price_bound(local, config('http://127.0.0.1:9/v1', HOSTED_MODEL), message(1)), (None, None))
        closed = {'model_pricing': {'gpt-4.1': {**price['model_pricing'][HOSTED_MODEL], 'base_url': 'https://api.openai.com/v1'}}}
        with self.assertRaisesRegex(gov.AdmissionError, 'vision'):
            gov.price_bound(closed, config('https://api.openai.com/v1', 'gpt-4.1', 'k'), message(1))


class EffortTests(unittest.TestCase):
    def test_medium_only_for_the_complete_default_unless_set_or_overridden(self):
        cases = [(providers.provider_from_env({}), None, 'medium'), (providers.provider_from_env({'OPENBENCH_MODEL': 'custom'}), None, None),
                 (providers.provider_from_env({'OPENBENCH_MODEL': 'custom'}), 'low', 'low'), (providers.provider_from_env({}), 'high', 'high'),
                 (providers.provider_from_env({'OPENBENCH_MODEL': 'custom', 'OPENBENCH_REASONING_EFFORT': 'high'}), None, 'high')]
        for cfg, override, sent in cases:
            with self.subTest(model=cfg.model, override=override):
                wire = Wire({'content': 'ok'})
                turn(cfg, wire, reasoning_effort=override)
                self.assertEqual(wire.bodies[0].get('reasoning_effort'), sent)
        with self.assertRaises(ValueError):
            turn(providers.provider_from_env({}), Wire({'content': 'ok'}), reasoning_effort='max')

    def test_runtime_forwards_a_jobs_effort_and_history(self):
        seen = {}
        def fake(**kw):
            seen.update(kw)
            return model_client.TurnResult(status='ok', answer='done', model='reported-model')
        profile = {'agent_key': 'sheet_ops', 'provider_config': {'model': 'custom'}, 'allowed_tools': [], 'role_kind': 'specialist'}
        history = [{'role': 'user', 'content': 'earlier'}]
        with patch.dict(os.environ, {}, clear=False), patch.object(providers, 'run_openai_compat_turn', side_effect=fake):
            for name in ('OPENBENCH_API_BASE', 'OPENBENCH_MODEL', 'OPENBENCH_REASONING_EFFORT', 'OPENBENCH_PROVIDER'):
                os.environ.pop(name, None)
            outcome = agent_runtime.run_agent(profile=profile, ctx=SimpleNamespace(), instructions='S', turn_text='T', timeout=5,
                                              history=history, reasoning_effort='low')
        self.assertEqual((seen['reasoning_effort'], seen['history'], seen['config'].effort), ('low', history, None))
        self.assertEqual((outcome.status, outcome.model), ('ok', 'reported-model'))


class FailureTests(unittest.TestCase):
    def test_transport_failures_map_to_the_seven_classes(self):
        def raising(error):
            def opener(request, timeout):
                raise error
            return opener
        remote = config('https://models.example.test/v1', 'm', 'k')
        cases = [(config('http://127.0.0.1:9/v1', 'm'), raising(urllib.error.URLError(ConnectionRefusedError())), 'unavailable', 'local'),
                 (config('http://127.0.0.1:9/v1', 'm'), lambda r, timeout: io.BytesIO(b'<html>'), 'bad_response', 'local'),
                 (remote, raising(urllib.error.HTTPError('u', 503, 'x', {}, io.BytesIO(b''))), 'unavailable', 'provider'),
                 (remote, lambda r, timeout: io.BytesIO(b'not json'), 'bad_response', 'provider'),
                 (remote, raising(urllib.error.HTTPError('u', 429, 'x', {}, io.BytesIO(b''))), 'quota', 'quota'),
                 (remote, raising(urllib.error.HTTPError('u', 401, 'x', {}, io.BytesIO(b''))), 'auth', 'auth'),
                 (remote, raising(TimeoutError()), 'timeout', 'timeout'),
                 (config('https://models.example.test/v1', 'm', ''), Wire({'content': 'x'}), 'auth', 'auth'),
                 (config(), Wire({'content': '   '}), 'empty', 'empty'),
                 (config(), Wire({'content': '<think>hmm</think>'}), 'empty', 'empty')]
        for cfg, opener, kind, failure in cases:
            with self.subTest(kind=kind, failure=failure, base=cfg.base_url):
                result = turn(cfg, opener)
                self.assertEqual((result.status in ('error', 'quota'), result.error_kind, result.failure), (True, kind, failure))
        loop = Wire({'content': '', 'tool_calls': [{'id': 'x', 'function': {'name': 'read_page', 'arguments': '{}'}}]})
        result = turn(config('http://127.0.0.1:9/v1', 'm'), loop, tool_specs=READ)
        self.assertEqual((result.error_kind, result.failure), ('bad_response', 'output'))
        self.assertEqual(set(model_client.FAILURE_TEXT), set(model_client.FAILURE_CLASSES))
        self.assertEqual(model_client.failure_class('kind_removed'), 'provider')

    def test_chat_and_board_show_the_class_in_plain_language(self):
        for kind, failure in (('unavailable', ''), ('quota', 'quota'), ('configuration', 'provider')):
            outcome = agent_runtime.Outcome('error', kind=kind, failure=failure)
            cls, body = worker.failure_reply(outcome)
            self.assertEqual(body, model_client.FAILURE_TEXT[cls])
            self.assertIn(cls, model_client.FAILURE_CLASSES)
        dispatches = [{'task_id': 't', 'status': 'failed', 'superseded_by': None, 'admission_no': 1, 'output_json': {'failure': 'local'}},
                      {'task_id': 't', 'status': 'failed', 'superseded_by': None, 'admission_no': 2, 'output_json': {'failure': 'quota'}},
                      {'task_id': 'u', 'status': 'failed', 'superseded_by': None, 'admission_no': 3, 'output_json': {'failure': '<b>x</b>'}}]
        self.assertEqual(orchestration_service._failure(dispatches, {'id': 't'}), 'quota')
        self.assertIsNone(orchestration_service._failure(dispatches, {'id': 'u'}))
        self.assertEqual(worker.history_messages([{'role': 'user', 'body': 'hi', 'files': ['a.png']}, {'role': 'assistant', 'body': 'yo'},
                                                  {'role': 'lead', 'body': 'ok'}], 'Mia'),
                         [{'role': 'user', 'content': 'hi (attached: a.png)'}, {'role': 'assistant', 'content': 'yo'}, {'role': 'user', 'content': 'Owner reply：ok'}])

    def test_ui_dictionaries_carry_the_classes_right_after_crew_readiness(self):
        root = Path(__file__).resolve().parents[1] / 'ui' / 'src' / 'i18n' / 'locales'
        for name in ('en.json', 'zh-TW.json'):
            data = json.loads((root / name).read_text(encoding='utf-8'))
            keys = list(data)
            self.assertEqual(keys.index('providerFailures'), keys.index('crewReadiness') + 1, name)
            self.assertEqual(set(data['providerFailures']), set(model_client.FAILURE_CLASSES), name)
            self.assertTrue({'enableHostedOpen', 'useHybridPolicy'} <= set(data['crewReadiness']), name)


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'set OPENBENCH_TEST_DB_URI')
class GovernedTierTests(unittest.TestCase):
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

    def settings(self, **fields):
        current = console.get_settings(self.conn, self.me, self.slug)
        saved = console.save_settings(self.conn, self.me, self.slug, {'version': current['version'], **fields})
        self.conn.commit()
        return saved

    def agent(self, base, model, *, deployment=None, project=None):
        import governance_fixture
        from project_docs import story_openapi as story
        governance_fixture.authorize_synthetic_media(self)  # full-network environment
        env = {'OPENBENCH_AGENT_KEY_ENVS': 'OPENROUTER_API_KEY', 'OPENROUTER_API_KEY': 'synthetic-credential'}
        patcher = patch.dict(os.environ, env)
        patcher.start(); self.addCleanup(patcher.stop)
        os.environ.pop('OPENBENCH_PRODUCTION_POLICY', None)
        if deployment:
            os.environ['OPENBENCH_PRODUCTION_POLICY'] = deployment
        if project:
            story.store(self.conn, 'policy_' + self.slug, 'policy', {'productionPolicy': project}, self.slug)
        profile = agent_registry.save_agent(self.conn, self.me, self.slug, {'agent_key': 'coordinator', 'provider_config':
            {'kind': 'openai_compat', 'base_url': base, 'model': model, 'api_key_env': 'OPENROUTER_API_KEY'}})
        self.conn.commit()
        self.settings(model_pricing={model: dict(kind='openai_compat', base_url=base, input_usd_per_million=1, output_usd_per_million=2,
                                                 max_input_tokens=200000, max_output_tokens=50, byte_bounded_tokenizer=True)})
        return profile

    def run_turn(self, profile, name, wire, **kw):
        cfg = agent_runtime.provider_for(profile)
        return providers.run_openai_compat_turn(config=cfg, instructions='Fixture', turn_text='Plan', call_tool=lambda *_: '', timeout=10,
                                                tool_specs=[], opener=wire, admission=gov.ProviderAdmission(self.context(name), profile, cfg), **kw)

    def rows(self, table):
        return db.many(self.conn, f'SELECT to_jsonb(r) FROM projectops.{table} r WHERE project_slug=%s ORDER BY created_at', (self.slug,))

    def test_hosted_open_needs_the_showrunner_switch_and_records_the_actual_model(self):
        profile = self.agent(OPENROUTER, HOSTED_MODEL)
        wire = Wire({'content': 'ok'}, model='qwen/qwen3.8-27b:fp8', usage={'prompt_tokens': 9, 'completion_tokens': 2})
        with self.assertRaisesRegex(gov.AdmissionError, 'hosted open-weights'):
            self.run_turn(profile, 'off', wire)
        self.assertEqual((wire.bodies, self.rows('agent_usage_reservation')), ([], []))
        self.assertEqual(console.get_settings(self.conn, self.me, self.slug)['provider_policy'], {'hosted_open_enabled': False})
        for bad in ({'hosted_open_enabled': 'yes'}, {}, {'hosted_open_enabled': True, 'extra': 1}):
            with self.subTest(bad=bad), self.assertRaises(agent_registry.AgentError):
                self.settings(provider_policy=bad)
        self.conn.rollback()
        self.settings(provider_policy={'hosted_open_enabled': True})
        result = self.run_turn(profile, 'on', wire)
        self.assertEqual((result.status, result.model), ('ok', 'qwen/qwen3.8-27b:fp8'))
        self.assertEqual([r['tier'] for r in self.rows('agent_usage_reservation')], ['hosted_open'])
        ledger = self.rows('agent_usage_ledger')
        self.assertEqual([(l['tier'], l['model_name'], l['meta'].get('configured_model'), l['meta'].get('model_reported')) for l in ledger],
                         [('hosted_open', 'qwen/qwen3.8-27b:fp8', HOSTED_MODEL, True)])
        # Hosted vision is priced from the catalog's per-image bound instead of refused outright.
        wire = Wire({'content': 'a rainy observatory'})
        self.assertEqual(self.run_turn(profile, 'vision', wire, images=[PNG]).status, 'ok')
        self.assertTrue(wire.bodies[0]['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/png'))
        reservation = self.rows('agent_usage_reservation')[-1]
        self.assertEqual(reservation['tier'], 'hosted_open')
        self.assertGreater(reservation['ceiling_cost_usd'], 0)

    def test_closed_needs_hybrid_and_the_deployment_ceiling_caps_agents(self):
        remote = 'https://models.example.test/v1'
        profile = self.agent(remote, 'closed-model', deployment='open_weights_only', project='open_weights_only')
        self.settings(provider_policy={'hosted_open_enabled': True})  # the hosted switch never opens closed models
        with self.assertRaisesRegex(gov.AdmissionError, 'hybrid_studio'):
            self.run_turn(profile, 'ceiling', Wire({'content': 'never'}))
        os.environ['OPENBENCH_PRODUCTION_POLICY'] = 'hybrid_studio'
        with self.assertRaisesRegex(gov.AdmissionError, 'hybrid_studio'):  # the project itself is still open weights only
            self.run_turn(profile, 'project', Wire({'content': 'never'}))
        from project_docs import story_openapi as story
        story.store(self.conn, 'policy_' + self.slug, 'policy', {'productionPolicy': 'hybrid_studio'}, self.slug)
        self.conn.commit()
        self.assertEqual(self.run_turn(profile, 'hybrid', Wire({'content': 'ok'})).status, 'ok')
        self.assertEqual([r['tier'] for r in self.rows('agent_usage_reservation')], ['closed'])
        # Closed vision has no catalog bound and still pauses for a showrunner.
        with self.assertRaisesRegex(gov.AdmissionError, 'vision'):
            self.run_turn(profile, 'closed-vision', Wire({'content': 'never'}), images=[PNG])

    def test_local_default_is_local_open_and_records_the_reported_model(self):
        profile = agent_registry.save_agent(self.conn, self.me, self.slug, {'agent_key': 'coordinator', 'provider_config':
            {'kind': 'openai_compat', 'base_url': 'http://127.0.0.1:9/v1', 'model': 'qwen3.8:27b'}})
        self.conn.commit()
        cfg = agent_runtime.provider_for(profile)
        wire = Wire({'content': 'ok'}, model='qwen3.8:27b')
        result = providers.run_openai_compat_turn(config=cfg, instructions='S', turn_text='T', call_tool=lambda *_: '', timeout=10, tool_specs=[],
                                                  opener=wire, admission=gov.ProviderAdmission(self.context('local'), profile, cfg))
        self.assertEqual(result.status, 'ok')
        ledger = self.rows('agent_usage_ledger')
        self.assertEqual([(l['tier'], l['model_name'], 'configured_model' in l['meta']) for l in ledger], [('local_open', 'qwen3.8:27b', False)])


if __name__ == '__main__':
    unittest.main()
