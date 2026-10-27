"""SPEC_20 R36/R38/R39/R40 Agent Console operations over real HTTP and PostgreSQL.

Every model, Ollama and ComfyUI endpoint here is a loopback fake; nothing reaches a real model or GPU.
"""
import datetime as dt
import json
import os
import socket
import sys
import threading
import time
import types
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.parse import quote

from project_assistant import automation, console_ops as ops, crew_readiness, execution_governance as gov
from project_assistant import orchestration_store as db, take_grader, tools
from project_docs import repository as repo

ENV = ('OPENBENCH_PROVIDER', 'PROJECT_ASSISTANT_ENGINE', 'OPENBENCH_API_BASE', 'OPENBENCH_API_KEY', 'OPENAI_API_KEY',
       'OPENBENCH_MODEL', 'PROJECT_ASSISTANT_MODEL', 'OPENBENCH_REASONING_EFFORT', 'OPENBENCH_AGENT_KEY_ENVS',
       'HTTP_PROXY', 'http_proxy', 'NO_PROXY', 'no_proxy')
MODEL = 'qwen3.8:27b'


def closed_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class Fake:
    """One loopback server: an Ollama-style model server and/or a ComfyUI, with switchable behaviour."""

    def __init__(self, **behaviour):
        self.models, self.tool_call, self.json_reply, self.vision_status = [MODEL], True, '{"status":"ok","checks":3}', None
        self.show = {'parameters': 'num_ctx 4096\ntemperature 0.6', 'model_info': {'qwen3.context_length': 262144}}
        self.ps = {'models': [{'name': MODEL, 'model': MODEL, 'size': 20_000_000_000, 'size_vram': 20_000_000_000, 'context_length': 4096,
                               'expires_at': '2026-10-27T12:00:00Z', 'details': {'parameter_size': '27B', 'quantization_level': 'Q4_K_M'}}]}
        self.stats = {'system': {'comfyui_version': '0.42.1'}, 'devices': [{'name': 'cuda:0 NVIDIA GeForce RTX 4090', 'type': 'cuda',
                      'vram_total': 25_757_220_864, 'vram_free': 20_000_000_000, 'torch_vram_total': 1_000, 'torch_vram_free': 500}]}
        self.queue = {'queue_running': [[0, 'p1', {'1': {'inputs': {'text': 'SECRET PROMPT'}}}]], 'queue_pending': [[1, 'p2', {}], [2, 'p3', {}]]}
        self.redirect, self.delay = None, 0
        self.__dict__.update(behaviour)
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, value, headers=()):
                data = json.dumps(value).encode()
                self.send_response(status)
                for name, header in headers:
                    self.send_header(name, header)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except ConnectionError:
                    pass  # the timeout test's client has already given up

            def do_GET(self):
                owner.requests.append(('GET', self.path, None))
                time.sleep(owner.delay)
                if owner.redirect:
                    return self.reply(302, {}, [('Location', owner.redirect + self.path)])
                routes = {'/v1/models': {'object': 'list', 'data': [{'id': m} for m in owner.models]}, '/api/ps': owner.ps,
                          '/system_stats': owner.stats, '/queue': owner.queue}
                self.reply(200, routes[self.path]) if self.path in routes else self.reply(404, {'error': 'not found'})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.requests.append(('POST', self.path, body))
                if self.path == '/api/show':
                    return self.reply(200, owner.show) if body.get('model') in owner.models else self.reply(404, {'error': 'model not found'})
                if self.path != '/v1/chat/completions':
                    return self.reply(404, {'error': 'not found'})
                if body['model'] not in owner.models:
                    return self.reply(404, {'error': 'model not found, try pulling it first'})
                messages, message = body['messages'], {'content': '<think>checking</think>READY'}
                if 'tools' in body:
                    message = ({'content': 'DONE'} if any(m.get('role') == 'tool' for m in messages) else
                               {'content': '', 'tool_calls': [{'id': 'c1', 'type': 'function', 'function': {'name': 'report_health', 'arguments': '{"status":"ok"}'}}]}
                               if owner.tool_call else {'content': 'I answer without tools.'})
                elif 'response_format' in body:
                    message = {'content': owner.json_reply}
                elif isinstance(messages[-1]['content'], list):
                    if owner.vision_status:
                        return self.reply(owner.vision_status, {'error': 'this model does not support images'})
                    message = {'content': '<think>a flat colour</think>Red'}
                self.reply(200, {'choices': [{'message': message}], 'usage': {'prompt_tokens': 21, 'completion_tokens': 3}})

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.base = self.url + '/v1'

    def chats(self):
        return [body for method, path, body in self.requests if path == '/v1/chat/completions']

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'set OPENBENCH_TEST_DB_URI')
class OperationsFixture(unittest.TestCase):
    from test_product_http import ProductHTTPTests as _fixture
    request = _fixture.request

    def setUp(self):
        self._fixture.setUp(self)
        crew_readiness.forget()
        ops.forget()
        self.addCleanup(crew_readiness.forget)
        self.addCleanup(ops.forget)
        self.fake = Fake()
        self.addCleanup(self.fake.close)
        self.use_model(self.fake.base)
        self.base = f'/projects/api/{self.slug}/agent-console'

    def tearDown(self):
        self._fixture.tearDown(self)

    def use_model(self, base, model=MODEL, **extra):
        values = {'OPENBENCH_API_BASE': base, 'OPENBENCH_MODEL': model, **extra}
        patcher = patch.dict(os.environ, values)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ENV:
            if name not in values:
                os.environ.pop(name, None)

    def api(self, path, method='GET', body=None, status=200):
        code, payload, _ = self.request(self.base + path, method=method, data=body)
        self.assertEqual(code, status, payload)
        return payload

    def role(self, role):
        repo.upsert_member(self.conn, self.actor, 'Operations test', role)
        self.conn.commit()

    def reservations(self):
        self.conn.rollback()
        return db.many(self.conn, 'SELECT to_jsonb(r) FROM projectops.agent_usage_reservation r WHERE project_slug=%s ORDER BY created_at', (self.slug,))


class ModelCheckTests(OperationsFixture):
    def step(self, step, agent='coordinator', status=200):
        return self.api('/model-check', 'POST', {'agent_key': agent, 'step': step}, status)

    def test_setup_lists_the_crew_on_the_local_preset_and_points_an_agent_back(self):
        setup = self.api('/model-setup')
        self.assertEqual((setup['preset']['base_url'], setup['preset']['model']), ('http://127.0.0.1:11434/v1', MODEL))
        self.assertEqual(setup['steps'], ['model', 'chat', 'tools', 'json', 'vision', 'context'])
        crew = {a['agentKey']: a for a in setup['agents']}
        self.assertEqual(set(crew), {'coordinator', 'doc_writer', 'sheet_ops', 'qa_critic'})
        self.assertEqual(crew['coordinator']['provider'], {'kind': 'openai_compat', 'local': True, 'host': '127.0.0.1',
            'port': self.fake.server.server_port, 'model': MODEL, 'baseUrl': self.fake.base})
        self.assertFalse(crew['coordinator']['matchesPreset'], 'a fake port is not the Ollama preset')
        # With the deployment default on the preset, pointing an agent back restores inheritance.
        self.use_model('http://127.0.0.1:11434/v1')
        from project_assistant import agent_registry
        agent_registry.save_agent(self.conn, self.me, self.slug, {'agent_key': 'sheet_ops', 'provider_config': {'kind': 'openai_compat', 'base_url': 'http://127.0.0.1:8000/v1', 'model': 'other'}})
        self.conn.commit()
        crew = {a['agentKey']: a for a in self.api('/model-setup')['agents']}
        self.assertEqual((crew['sheet_ops']['matchesPreset'], crew['coordinator']['matchesPreset']), (False, True))
        stale = crew['sheet_ops']['version']
        result = self.api('/model-setup', 'POST', {'agent_key': 'sheet_ops', 'version': stale})['agent']
        self.assertTrue(result['inherits'])
        self.api('/model-setup', 'POST', {'agent_key': 'sheet_ops', 'version': stale}, 409)
        self.assertTrue({a['agentKey']: a for a in self.api('/model-setup')['agents']}['sheet_ops']['matchesPreset'])

    def test_every_step_passes_against_a_capable_local_model_and_each_call_is_governed(self):
        results = {name: self.step(name) for name in ('model', 'chat', 'tools', 'json', 'vision', 'context')}
        for name in ('model', 'chat', 'tools', 'json', 'vision'):
            self.assertEqual(results[name]['status'], 'pass', results[name])
        self.assertEqual(results['model']['code'], 'model_present')
        self.assertEqual((results['chat']['detail']['reply'], results['chat']['detail']['followed']), ('READY', True))
        self.assertEqual(results['tools']['detail']['calls'], 1)
        self.assertEqual(results['json']['detail']['value'], {'status': 'ok', 'checks': 3})
        self.assertEqual(results['vision']['detail']['reply'], 'Red')
        for name in ('chat', 'tools', 'json', 'vision'):
            self.assertEqual((results[name]['governed'], results[name]['billed']), (True, False), name)
        self.assertEqual((results['model']['governed'], results['context']['governed']), (False, False))
        # The requests carried what each step tests: tools, a JSON schema, and an inline base64 image.
        chats = self.fake.chats()
        self.assertEqual(len(chats), 5)  # tools takes a second round to answer after its call
        self.assertNotIn('tool_choice', json.dumps(chats))
        self.assertEqual(chats[1]['tools'][0]['function']['name'], 'report_health')
        self.assertEqual(chats[3]['response_format']['json_schema']['schema']['required'], ['status', 'checks'])
        image = chats[4]['messages'][-1]['content'][1]['image_url']['url']
        self.assertTrue(image.startswith('data:image/png;base64,'))
        # Every model call was admitted, settled and recorded; local calls are never priced.
        rows = self.reservations()
        self.assertEqual(len(rows), 5)
        self.assertEqual({(r['agent_key'], r['usage_kind'], r['state'], r['model_name'], r['tier']) for r in rows},
                         {('coordinator', 'llm_turn', 'finalized', MODEL, 'local_open')})  # SPEC_20 R9 usage tier
        self.assertEqual({r['accounted_cost_usd'] for r in rows}, {None})
        ledger = db.one(self.conn, 'SELECT count(*) FROM projectops.agent_usage_ledger WHERE project_slug=%s', (self.slug,))
        self.assertEqual(ledger, 5)
        # Context: the running model reports 4096, which is flagged with the OLLAMA_CONTEXT_LENGTH fix.
        self.assertEqual((results['context']['status'], results['context']['code'], results['context']['fix']), ('warn', 'context_4096', 'ollama_context_length'))
        self.assertEqual(results['context']['detail'], {'contextLength': 4096, 'source': 'running', 'numCtx': 4096, 'modelMax': 262144, 'target': 16384})
        self.fake.ps['models'][0]['context_length'] = 16384
        self.assertEqual(self.step('context')['code'], 'context_ok')
        self.fake.ps['models'] = []
        self.fake.show['parameters'] = 'temperature 0.6'
        self.assertEqual(self.step('context')['code'], 'context_server_default')

    def test_failing_steps_name_the_problem_and_the_fix(self):
        self.fake.models = ['qwen3:8b']
        missing = self.step('model')
        self.assertEqual((missing['status'], missing['code'], missing['fix'], missing['detail']['available']), ('fail', 'model_missing', 'ollama_pull', ['qwen3:8b']))
        self.assertEqual(self.step('chat')['code'], 'model_missing', 'Ollama 404s an unpulled model')
        self.fake.models = [MODEL]
        self.fake.tool_call = False
        tools_step = self.step('tools')
        self.assertEqual((tools_step['code'], tools_step['fix']), ('no_tool_call', 'tool_model'))
        self.fake.json_reply = 'status: ok'
        self.assertEqual(self.step('json')['code'], 'json_invalid')
        self.fake.vision_status = 400
        vision = self.step('vision')
        self.assertEqual((vision['code'], vision['fix']), ('rejected', 'vision_model'))
        self.assertNotIn('does not support', json.dumps(vision), 'provider bodies are never echoed')
        port = closed_port()
        self.use_model(f'http://127.0.0.1:{port}/v1')
        for name in ('model', 'chat'):
            down = self.step(name)
            self.assertEqual((down['status'], down['code'], down['fix']), ('fail', 'unreachable', 'start_ollama'), name)
        # Local failures end their reservation cleanly: nothing is left uncertain to block the crew.
        self.assertEqual({r['state'] for r in self.reservations()}, {'finalized'})

    def test_a_hosted_endpoint_is_governed_before_any_request_is_sent(self):
        self.use_model('https://models.example.test/v1', OPENBENCH_API_KEY='sk-zf20-test-0001')
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('no outbound request')):
            for name in ('model', 'chat', 'vision'):
                result = self.step(name)
                self.assertEqual((result['status'], result['code']), ('fail', 'governance'), name)
                self.assertIn('network policy', result['message'])
            self.assertEqual(self.step('context')['code'], 'context_remote')
        self.assertEqual(self.reservations(), [])
        self.assertNotIn('sk-zf20', json.dumps(self.step('chat')))

    def test_only_the_showrunner_runs_setup_and_checks(self):
        self.step('bogus', status=400)
        self.api('/model-check', 'POST', {'agent_key': 'coordinator'}, 400)
        self.role('member')
        self.assertEqual(self.step('chat', status=403)['code'], 'POLICY_DENIED')
        self.api('/model-setup', status=403)
        self.api('/model-setup', 'POST', {'agent_key': 'coordinator', 'version': 1}, 403)
        self.assertEqual(self.fake.chats(), [])
        self.assertEqual(self.reservations(), [])


class GPUPanelTests(OperationsFixture):
    def comfy(self, url):
        db.execute(self.conn, "UPDATE projectops.agent_environment SET config=jsonb_set(config,'{comfy_url}',to_jsonb(%s::text)) WHERE project_slug=%s AND env_key='env_local_4090'", (url, self.slug))
        self.conn.commit()
        ops.forget()

    def test_vram_queue_and_loaded_models_from_local_endpoints_without_prompts(self):
        self.comfy(self.fake.url)
        panel = self.api('/gpu')
        comfy = panel['comfy']
        self.assertEqual((comfy['state'], comfy['version'], comfy['queue']), ('ok', '0.42.1', {'running': 1, 'pending': 2}))
        self.assertEqual(comfy['devices'][0]['vramTotal'], 25_757_220_864)
        self.assertEqual(comfy['devices'][0]['vramFree'], 20_000_000_000)
        self.assertNotIn('SECRET PROMPT', json.dumps(panel), 'queue entries are counted, never returned')
        server = panel['modelServers'][0]
        self.assertEqual((server['state'], server['port']), ('ok', self.fake.server.server_port))
        self.assertEqual(server['models'][0], {'name': MODEL, 'sizeBytes': 20_000_000_000, 'vramBytes': 20_000_000_000, 'gpuShare': 1.0,
            'contextLength': 4096, 'expiresAt': '2026-10-27T12:00:00Z', 'parameterSize': '27B', 'quantization': 'Q4_K_M'})
        self.assertEqual(panel['gpuOwner'], {'available': False, 'owner': None}, 'the arbiter slot is empty until W2b merges')
        # A crew member reads it too; it is read-only.
        self.role('member')
        ops.forget()
        self.assertEqual(self.api('/gpu')['comfy']['state'], 'ok')

    def test_probes_ignore_proxies_refuse_redirects_and_time_out_quickly(self):
        target = Fake()
        self.addCleanup(target.close)
        self.fake.redirect = target.url
        self.comfy(self.fake.url)
        self.assertEqual(self.api('/gpu')['comfy']['state'], 'bad')
        self.assertEqual(target.requests, [], 'a redirect is never followed')
        self.fake.redirect = None
        self.use_model(self.fake.base, HTTP_PROXY=f'http://127.0.0.1:{closed_port()}', http_proxy=f'http://127.0.0.1:{closed_port()}')
        ops.forget()
        self.assertEqual(self.api('/gpu')['comfy']['state'], 'ok', 'an environment proxy never sees a loopback probe')
        slow = Fake(delay=1.0)
        self.addCleanup(slow.close)
        self.comfy(slow.url)
        with patch.object(ops, 'PROBE_SECONDS', 0.2):
            started = time.monotonic()
            panel = self.api('/gpu')
        self.assertEqual(panel['comfy']['state'], 'down')
        self.assertLess(time.monotonic() - started, 1.0)
        self.comfy(f'http://127.0.0.1:{closed_port()}')
        self.assertEqual(self.api('/gpu')['comfy']['state'], 'down')

    def test_hosted_endpoints_are_reported_by_host_and_never_probed(self):
        self.comfy('http://gpu-box.example.test:8188')
        self.use_model('https://models.example.test/v1', OPENBENCH_API_KEY='sk-zf20-test-0001')
        with patch('urllib.request.build_opener', side_effect=AssertionError('no probe')):
            panel = self.api('/gpu')
        self.assertEqual(panel['comfy'], {'host': 'gpu-box.example.test', 'port': 8188, 'state': 'not_local'})
        self.assertEqual(panel['modelServers'], [])

    def test_gpu_owner_slot_lights_up_when_the_arbiter_module_exists(self):
        arbiter = types.ModuleType('project_assistant.gpu_arbiter')
        arbiter.current_owner = lambda conn, url: {'holder': 'take_grader', 'purpose': 'continuity grading', 'since': '2026-10-27T10:00:00Z', 'pid': 1}
        with patch.dict(sys.modules, {'project_assistant.gpu_arbiter': arbiter}):
            panel = self.api('/gpu')
        self.assertEqual(panel['gpuOwner'], {'available': True, 'owner': {'holder': 'take_grader', 'purpose': 'continuity grading', 'since': '2026-10-27T10:00:00Z'}})


class QueueTests(OperationsFixture):
    def seed(self):
        other = str(uuid.uuid4())
        old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=20)
        rows = [(self.actor, 'queued', None, '', None), (self.actor, 'failed', 'admission', 'Agent concurrency limit reached.', None),
                (other, 'failed', 'timeout', 'private words from another member', None), (self.actor, 'failed', 'crash', 'old', old)]
        for owner, status, kind, body, when in rows:
            db.execute(self.conn, """INSERT INTO projectops.assistant_message(project_slug,owner_id,role,body,status,error_kind,finished_at,created_at)
                VALUES(%s,%s,'assistant',%s,%s,%s,COALESCE(%s,NOW()),COALESCE(%s,NOW()))""", (self.slug, owner, body, status, kind, when, when))
        for creator, status, error in ((self.actor, 'failed', 'Lease expired before the worker answered.'), (other, 'running', None)):
            run, task = str(uuid.uuid4()), str(uuid.uuid4())
            db.execute(self.conn, """INSERT INTO projectops.orchestration_run(id,project_slug,created_by,client_request_id,request_hash,objective)
                VALUES(%s,%s,%s,%s,'h','Private objective')""", (run, self.slug, creator, run))
            db.execute(self.conn, "INSERT INTO projectops.orchestration_task(id,run_id,project_slug,title,spec) VALUES(%s,%s,%s,'t','s')", (task, run, self.slug))
            db.execute(self.conn, """INSERT INTO projectops.orchestration_dispatch(id,run_id,task_id,project_slug,admission_no,agent_key,slot_key,profile_snapshot,deadline_at,status,error,finished_at)
                VALUES(%s,%s,%s,%s,%s,'sheet_ops','main','{}',NOW()+INTERVAL '1 hour',%s,%s,NOW())""",
                       (str(uuid.uuid4()), run, task, self.slug, int(uuid.uuid4().int % 1_000_000_000), status, error))
        flow = str(uuid.uuid4())
        db.execute(self.conn, """INSERT INTO projectops.flow_run(id,project_slug,tab_key,definition,definition_revision,created_by,status)
            VALUES(%s,%s,'cinema-studio','{}',1,%s,'failed')""", (flow, self.slug, self.actor))
        db.execute(self.conn, """INSERT INTO projectops.limb_task(id,run_id,project_slug,node_id,row_id,capability,status,attempts,error)
            VALUES(%s,%s,%s,'render','r1','video_gen','failed',3,%s)""", (str(uuid.uuid4()), flow, self.slug, 'ComfyUI rejected the workflow: ' + 'x' * 400))
        db.execute(self.conn, """INSERT INTO projectops.story_record(id,kind,project_slug,data) VALUES(%s,'take_grade',%s,%s::jsonb)""",
                   ('grade_test_' + self.slug, self.slug, json.dumps({'gradeId': 'g', 'shotId': 'sh_1', 'status': 'failed', 'auto': True,
                                                                       'error': 'The vision model did not answer.', 'requestedAt': '2026-10-27T10:00:00Z'})))
        ctx = tools.ToolContext(lambda: None, self.slug, self.me, None, None)
        ctx.accounting_session_key = 'queue-fixture'
        gov.reserve(self.conn, ctx, request_key='call:queue/uncertain', agent_key='coordinator', usage_kind='llm_turn',
                    provider_name='openai_compat', model_name='priced-fixture', ceiling='.2500')
        gov.dispatched(self.conn, self.slug, 'call:queue/uncertain')
        gov.finalize(self.conn, self.slug, 'call:queue/uncertain', outcome='unknown')
        self.conn.commit()

    def test_one_view_of_queued_running_and_failed_work_with_private_details_withheld(self):
        self.seed()
        view = self.api('/queue')
        self.assertEqual(view['counts'], {'turns': {'active': 1, 'failed': 2}, 'dispatches': {'active': 1, 'failed': 1},
                                          'tasks': {'active': 0, 'failed': 1}, 'grades': {'active': 0, 'failed': 1}, 'uncertain': 1})
        failed = {t['errorKind']: t for t in view['turns']['failed']}
        self.assertEqual(set(failed), {'admission', 'timeout'}, 'failures older than the window are left out')
        self.assertEqual((failed['admission']['detail'], failed['admission']['mine']), ('Agent concurrency limit reached.', True))
        self.assertEqual((failed['timeout']['detail'], failed['timeout']['mine']), (None, False))
        self.assertNotIn('private words', json.dumps(view))
        self.assertNotIn('Private objective', json.dumps(view))
        dispatch = view['dispatches']['failed'][0]
        self.assertEqual((dispatch['agentKey'], dispatch['error'], dispatch['mine']), ('sheet_ops', 'Lease expired before the worker answered.', True))
        self.assertIsNotNone(dispatch['runId'])
        self.assertIsNone(view['dispatches']['active'][0]['runId'], "another member's session stays private")
        task = view['tasks']['failed'][0]
        self.assertEqual((task['tabKey'], task['capability'], task['attempts'], len(task['error'])), ('cinema-studio', 'video_gen', 3, 300))
        self.assertEqual(view['grades']['failed'][0]['error'], 'The vision model did not answer.')
        self.assertEqual(self.api('/queue?days=30')['counts']['turns']['failed'], 3)
        self.api('/queue?days=0', status=400)
        self.api('/queue?days=x', status=400)
        uncertain = view['uncertain'][0]
        self.assertEqual((view['canReconcile'], uncertain['requestKey'], uncertain['ceilingUsd'], uncertain['holdsSlot']), (True, 'call:queue/uncertain', 0.25, True))
        self.assertNotIn('owner_id', uncertain)

    def test_reconcile_from_the_view_and_members_see_only_the_count(self):
        self.seed()
        key = self.api('/queue')['uncertain'][0]['requestKey']
        self.role('member')
        member = self.api('/queue')
        self.assertEqual((member['canReconcile'], member['uncertain'], member['counts']['uncertain']), (False, [], 1))
        self.api(f'/reservations/{quote(key, safe="")}/reconcile', 'POST', {'observedCostUsd': '0.0100'}, 403)
        self.role('admin')
        self.api(f'/reservations/{quote(key, safe="")}/reconcile', 'POST', {'observedCostUsd': '0.0100'})
        view = self.api('/queue')
        self.assertEqual((view['uncertain'], view['counts']['uncertain']), ([], 0))


class AutomationPauseTests(OperationsFixture):
    def test_pause_switch_is_the_showrunners_and_records_who_and_when(self):
        self.assertEqual(self.api('/automation')['automation'], {'paused': False, 'by': None, 'byName': None, 'at': None, 'reason': ''})
        paused = self.api('/automation', 'POST', {'paused': True, 'reason': 'GPU reserved for the demo render'})['automation']
        self.assertEqual((paused['paused'], paused['by'], paused['byName'], paused['reason']), (True, self.actor, 'Execution test', 'GPU reserved for the demo render'))
        self.assertRegex(paused['at'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$')
        self.assertTrue(self.api('/dashboard')['automation']['paused'])
        self.assertTrue(self.api('/queue')['automation']['paused'])
        for body in ({}, {'paused': 'yes'}, {'paused': True, 'extra': 1}, {'paused': True, 'reason': 'x' * 301}):
            self.api('/automation', 'POST', body, 400)
        self.role('member')
        self.api('/automation', 'POST', {'paused': False}, 403)
        self.assertTrue(self.api('/automation')['automation']['paused'], 'members can see the pause')
        self.role('admin')
        resumed = self.api('/automation', 'POST', {'paused': False, 'reason': 'ignored when resuming'})['automation']
        self.assertEqual((resumed['paused'], resumed['reason']), (False, ''))
        self.conn.rollback()
        audit = db.many(self.conn, "SELECT action FROM projectops.audit_log WHERE project_slug=%s AND action LIKE 'automation_%%' ORDER BY id", (self.slug,))
        self.assertEqual(audit, ['automation_pause', 'automation_resume'])

    def test_pause_stops_automatic_grading_but_never_a_manual_grade(self):
        take_grader.set_auto(self.conn, self.slug, True)
        asset = repo.put_asset(self.conn, self.slug, data=b'\x00\x00\x00\x18ftypmp42 synthetic take', content_type='video/mp4', actor_id=self.actor)
        url = f'/projects/api/{self.slug}/assets/{asset}'
        self.conn.commit()
        self.api('/automation', 'POST', {'paused': True})
        self.conn.rollback()
        self.assertIsNone(take_grader.on_take(self.conn, self.slug, 'cinema-studio', 'r1', {'asset_url': url}, self.actor))
        self.assertEqual(db.one(self.conn, "SELECT count(*) FROM projectops.story_record WHERE kind='take_grade' AND project_slug=%s", (self.slug,)), 0)
        manual = take_grader.enqueue(self.conn, self.slug, 'sh_manual', url, self.actor)
        self.assertEqual((manual['status'], manual['auto']), ('queued', False), 'a grade asked for by hand still queues')
        self.conn.commit()
        self.api('/automation', 'POST', {'paused': False})
        self.conn.rollback()
        automatic = take_grader.on_take(self.conn, self.slug, 'cinema-studio', 'r1', {'asset_url': url}, self.actor)
        self.assertEqual((automatic['status'], automatic['auto']), ('queued', True))
        self.conn.rollback()

    def test_helper_reads_unset_or_damaged_state_as_running(self):
        self.assertFalse(automation.automation_paused(self.conn, self.slug))
        from project_assistant import store
        store.set_setting(self.conn, self.slug, automation.KEY, 'not json')
        self.assertFalse(automation.paused(self.conn, self.slug))
        store.set_setting(self.conn, self.slug, automation.KEY, json.dumps({'paused': 'true'}))
        self.assertFalse(automation.paused(self.conn, self.slug), 'only a real true pauses')
        self.conn.rollback()


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'set OPENBENCH_TEST_DB_URI')
class PausedDeploymentTests(unittest.TestCase):
    """Scheduled deployments skip while paused; a manual trigger still runs."""
    import test_agent_console as _console
    request, prepare, call, ok = _console.ConsoleHTTPTests.request, _console.ConsoleHTTPTests.prepare, _console.ConsoleHTTPTests.call, _console.ConsoleHTTPTests.ok
    setUp, tearDown = _console.ConsoleHTTPTests.setUp, _console.ConsoleHTTPTests.tearDown
    api, draft, connect = _console.ConsoleHTTPTests.api, _console.ConsoleHTTPTests.draft, _console.ConsoleHTTPTests.connect

    def test_due_slots_are_skipped_while_paused_and_manual_triggers_run(self):
        from project_assistant import console_deployments as deployments
        key = self.api('/agents', 'POST', self.draft())['agent']['agent_key']
        deployment = self.api('/deployments', 'POST', {'deployment_key': 'nightly', 'version': 0, 'agent_key': key, 'initial_prompt': 'Synthetic deployment',
                                                       'schedule_kind': 'cron', 'cron_expr': '* * * * *', 'timezone': 'UTC', 'budget_cap_usd': '1.00'})['deployment']
        self.api('/automation', 'POST', {'paused': True, 'reason': 'Demo render'})
        instant = dt.datetime(2026, 10, 27, 8, 1, tzinfo=dt.timezone.utc)
        self.assertEqual(deployments.produce_due(self.conn, self.slug, instant=instant), 0)
        self.conn.commit()
        self.assertEqual(db.one(self.conn, 'SELECT count(*) FROM projectops.agent_deployment_trigger WHERE project_slug=%s', (self.slug,)), 0)
        manual = self.api('/deployments/nightly/trigger', 'POST', {'version': deployment['version'], 'client_request_id': 'by-hand'})
        self.assertFalse(manual['replay'])
        self.assertTrue(manual['session_id'])
        self.api('/automation', 'POST', {'paused': False})
        self.assertEqual(deployments.produce_due(self.conn, self.slug, instant=instant + dt.timedelta(minutes=1)), 1)
        self.conn.commit()


if __name__ == '__main__':
    unittest.main()
