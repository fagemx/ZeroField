"""SPEC_20 R13 cross-process GPU arbiter and R11 governed Quickstart builder.

Loopback fake servers, synthetic openers and a child Python process only: no test reaches a real model, Ollama or
ComfyUI (the arbiter's HTTP is guarded against their ports), and nothing uses the GPU.
"""
import io
import json
import os
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from project_assistant import gpu_arbiter as arbiter, providers
from test_take_grader import fake_gpu

ROOT = Path(__file__).resolve().parents[1]
REAL_PORTS = {11434, 8188, 8189}


def guarded_http(url, body=None, timeout=10):
    if urlsplit(url).port in REAL_PORTS:
        raise AssertionError('a test reached a real GPU service: ' + url)
    return GUARDED(url, body, timeout)


GUARDED = arbiter._http


def reply(message):
    return io.BytesIO(json.dumps({'choices': [{'message': message}]}).encode())


class Recorder:
    """Duck-typed admission: records how each admitted round settled."""
    response_limit = 2 * 1024 * 1024

    def __init__(self):
        self.active, self.settled = False, []

    def before(self, payload):
        self.active = True

    def after(self, usage, outcome='succeeded', *, known_terminated=False, observed_cost=None):
        if self.active:
            self.active = False
            self.settled.append((outcome, known_terminated, observed_cost))


class Holder(threading.Thread):
    """Holds a GPU in another thread until told to let go."""

    def __init__(self, workload=arbiter.LLM, url='http://127.0.0.1:1/v1', **options):
        super().__init__(daemon=True)
        self.args, self.options = (workload, url), options
        self.held, self.done, self.error = threading.Event(), threading.Event(), None

    def run(self):
        try:
            grant = arbiter.acquire(*self.args, **self.options)
        except BaseException as exc:  # noqa: BLE001 - reported to the test
            self.error = exc
            self.held.set()
            return
        self.held.set()
        self.done.wait(30)
        grant.release()

    def __enter__(self):
        self.start()
        self.assertion = self.held.wait(10)
        return self

    def __exit__(self, *exc):
        self.done.set()
        self.join(10)


class ProcessCase(unittest.TestCase):
    """No database configured: the arbiter is process-local; its HTTP is guarded."""

    def setUp(self):
        for target in (patch.object(arbiter, '_connector', lambda: None), patch.object(arbiter, '_http', guarded_http),
                       patch.dict(os.environ, {arbiter.SWITCHING_ENV: ''})):
            target.start()
            self.addCleanup(target.stop)
        arbiter._memory.pop(arbiter.LOCAL_KEY, None)
        self.addCleanup(arbiter._memory.pop, arbiter.LOCAL_KEY, None)


class ArbiterUnitTests(ProcessCase):
    def test_lock_key_is_the_machine_that_owns_the_gpu(self):
        for url in ('http://127.0.0.1:11434/v1', 'http://localhost:8188', 'http://[::1]:8189', 'http://127.0.0.2:1'):
            self.assertEqual(arbiter.gpu_key(url), arbiter.LOCAL_KEY, url)
        self.assertEqual(arbiter.gpu_key('http://192.168.1.20:8188'), 'gpu:192.168.1.20')
        self.assertEqual(arbiter.gpu_key('http://render-box:8188'), 'gpu:render-box')
        self.assertEqual(arbiter.gpu_key('http://studio.lan:8188'), 'gpu:studio.lan')
        for url in ('https://cloud.comfy.org', 'https://openrouter.ai/api/v1', 'https://example.com/localhost', '', 'http://[::1'):
            self.assertIsNone(arbiter.gpu_key(url), url)
        with patch.dict(os.environ, {arbiter.HOSTS_ENV: 'gpu.example.com'}):
            self.assertEqual(arbiter.gpu_key('https://gpu.example.com:8188'), 'gpu:gpu.example.com')
        self.assertIsNone(arbiter.render('https://cloud.comfy.org'))  # a hosted runner is not this deployment's GPU

    def test_holders_serialize_waits_are_bounded_and_reentrant(self):
        waited = []
        with Holder(label='first') as holder:
            self.assertTrue(holder.assertion and holder.error is None)
            started = time.monotonic()
            with self.assertRaises(arbiter.GpuBusy):
                arbiter.acquire(arbiter.COMFY, 'http://localhost:8188', label='second', timeout=0.4, on_wait=lambda: waited.append(1))
            self.assertLess(time.monotonic() - started, 3)
            self.assertEqual(waited, [1])
            with self.assertRaisesRegex(arbiter.GpuBusy, 'canceled'):
                arbiter.acquire(arbiter.COMFY, 'http://localhost:8188', timeout=30, cancelled=lambda: True)
            view = arbiter.status()
            self.assertEqual(view['mode'], 'process')
            self.assertEqual(view['gpus'][0]['owner']['label'], 'first')
        # Free again; the same thread may nest holds without deadlocking itself.
        with arbiter.hold(arbiter.LLM, 'http://127.0.0.1:1/v1', model='m', timeout=1) as outer:
            with arbiter.hold(arbiter.LLM, 'http://localhost:1/v1', model='m', timeout=0) as inner:
                self.assertEqual(inner.key, outer.key)
            self.assertTrue(arbiter.held_in_process())
        self.assertFalse(arbiter.held_in_process())
        self.assertIsNone(arbiter.status()['gpus'][0]['owner'])

    def test_waiters_are_listed_oldest_first_for_the_console(self):
        with Holder(label='render-1', workload=arbiter.COMFY, url='http://127.0.0.1:8188') as holder:
            self.assertTrue(holder.assertion)
            waiter = Holder(label='grade-1', timeout=10)
            waiter.start()
            deadline = time.monotonic() + 5
            while not arbiter.status()['gpus'][0]['waiters'] and time.monotonic() < deadline:
                time.sleep(0.02)
            gpu = arbiter.status()['gpus'][0]
            self.assertEqual((gpu['owner']['workload'], gpu['owner']['label']), ('comfy', 'render-1'))
            self.assertEqual([(w['workload'], w['label']) for w in gpu['waiters']], [('llm', 'grade-1')])
            self.assertTrue(gpu['owner']['since'])
        self.assertTrue(waiter.held.wait(10))  # the waiter gets the GPU as soon as the render lets go
        waiter.done.set(); waiter.join(10)

    def test_owner_switches_only_on_a_workload_change(self):
        server, base, calls = fake_gpu()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        llm, comfy = base + '/v1', base
        def run(workload, url, **options):
            calls.clear()
            grant = arbiter.acquire(workload, url, timeout=5, **options)
            grant.release()
            return grant, [(c[0], c[1], c[2]) for c in calls]
        with patch.dict(os.environ, {arbiter.SWITCHING_ENV: 'on'}):
            grant, sent = run(arbiter.LLM, llm, model='planner')
            self.assertEqual((grant.switched, sent), (True, []))  # nothing known to free yet
            for model in ('planner', 'grader'):  # consecutive planning and grading rounds keep the model loaded
                grant, sent = run(arbiter.LLM, llm, model=model)
                self.assertEqual((grant.switched, sent), (False, []))
            grant, sent = run(arbiter.COMFY, comfy)
            self.assertTrue(grant.switched)
            self.assertEqual(sent, [('POST', '/api/generate', {'model': 'planner', 'keep_alive': 0}),
                                    ('POST', '/api/generate', {'model': 'grader', 'keep_alive': 0})])
            self.assertEqual(grant.switch, {'unloaded': ['planner', 'grader']})
            grant, sent = run(arbiter.COMFY, comfy)
            self.assertEqual((grant.switched, sent), (False, []))  # render after render: ComfyUI keeps its models
            grant, sent = run(arbiter.LLM, llm, model='planner')
            self.assertEqual([p for _, p, _ in sent], ['/queue', '/free', '/system_stats'])
            self.assertEqual(grant.switch['comfy']['comfyFreed'], True)
        # Library use (no launcher) serializes and remembers phases, but never calls a GPU service.
        grant, sent = run(arbiter.COMFY, comfy)
        self.assertEqual((grant.switched, sent), (True, []))
        resident = arbiter.status()['gpus'][0]['resident']
        self.assertEqual((resident['workload'], resident['comfy']), ('comfy', base))

    def test_a_failing_switch_leaves_nothing_held(self):
        def refuse(previous):
            raise arbiter.GpuBusy('ComfyUI stayed busy')
        with self.assertRaises(arbiter.GpuBusy):
            arbiter.acquire(arbiter.LLM, 'http://127.0.0.1:1/v1', model='m', on_switch=refuse, timeout=1)
        self.assertFalse(arbiter.held_in_process())
        arbiter.acquire(arbiter.LLM, 'http://127.0.0.1:1/v1', model='m', timeout=0).release()

    def test_compatibility_lock_keeps_the_old_shape(self):
        from project_assistant import take_grader
        lock = take_grader.GPU_LOCK
        self.assertTrue(lock.acquire(blocking=False))
        self.assertTrue(lock.locked())
        with Holder(label='other-thread', timeout=0.3) as other:
            self.assertIsInstance(other.error, arbiter.GpuBusy)
        lock.release()
        self.assertFalse(lock.locked())


class GateTests(ProcessCase):
    def turn(self, base, opener, *, timeout=10, admission=None, specs=(), call_tool=lambda *_: 'row'):
        return providers.run_openai_compat_turn(config=providers.ProviderConfig('openai_compat', base, '', 'fixture'),
            instructions='Fixture', turn_text='Plan', call_tool=call_tool, timeout=timeout, tool_specs=list(specs),
            admission=admission, opener=opener)

    def test_each_local_round_holds_the_gpu_only_for_its_request(self):
        held = []
        def opener(request, timeout):
            held.append(arbiter.held_in_process())
            return reply({'content': 'ok'})
        self.assertEqual(self.turn('http://127.0.0.1:11434/v1', opener).status, 'ok')
        self.assertEqual(held, [True])
        self.assertFalse(arbiter.held_in_process())
        # A tool round releases the GPU before the tool runs, and takes it again for the next request.
        from project_assistant import tool_specs
        spec = [s for s in tool_specs.TOOLS if s['name'] == 'read_page']
        answers = iter([{'content': '', 'tool_calls': [{'id': 'c1', 'function': {'name': 'read_page', 'arguments': '{}'}}]}, {'content': 'done'}])
        during_tool = []
        held.clear()
        result = self.turn('http://localhost:11434/v1', lambda request, timeout: held.append(arbiter.held_in_process()) or reply(next(answers)),
                           specs=spec, call_tool=lambda *_: during_tool.append(arbiter.held_in_process()) or 'row')
        self.assertEqual((result.status, held, during_tool), ('ok', [True, True], [False]))
        # Hosted endpoints are not this machine's GPU: the opener is not wrapped.
        remote = providers.ProviderConfig('openai_compat', 'https://openrouter.ai/api/v1', 'k', 'm')
        self.assertIs(arbiter.gate(opener, remote), opener)

    def test_a_busy_gpu_times_out_within_the_turn_and_settles_locally(self):
        sent = []
        with Holder(workload=arbiter.COMFY, url='http://127.0.0.1:8188', label='render') as holder:
            self.assertTrue(holder.assertion)
            admission = Recorder()
            started = time.monotonic()
            result = self.turn('http://127.0.0.1:11434/v1', lambda request, timeout: sent.append(1) or reply({'content': 'x'}),
                               timeout=0.5, admission=admission)
            self.assertLess(time.monotonic() - started, 4)
        self.assertEqual((result.status, result.error_kind, sent), ('error', 'timeout', []))
        self.assertEqual(admission.settled, [('failed', True, 0)])  # local: finalized, never charged (§4.1)
        self.assertFalse(arbiter.held_in_process())

    def test_the_first_round_after_a_render_frees_comfyui_once(self):
        server, base, calls = fake_gpu()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        with patch.dict(os.environ, {arbiter.SWITCHING_ENV: 'on'}):
            arbiter.render(base, label='render').release()
            from project_assistant import tool_specs
            spec = [s for s in tool_specs.TOOLS if s['name'] == 'read_page']
            answers = iter([{'content': '', 'tool_calls': [{'id': 'c1', 'function': {'name': 'read_page', 'arguments': '{}'}}]}, {'content': 'done'}])
            result = self.turn(base + '/v1', lambda request, timeout: reply(next(answers)), specs=spec)
        self.assertEqual(result.status, 'ok')
        self.assertEqual([c[1] for c in calls], ['/queue', '/free', '/system_stats'])  # round two keeps the model


DB_URI = os.environ.get('OPENBENCH_TEST_DB_URI')
CHILD = '''
import os, sys, time
sys.path.insert(0, sys.argv[1])
import psycopg
from project_assistant import gpu_arbiter
gpu_arbiter.CONNECT = lambda: psycopg.connect(os.environ["ZF_GPU_TEST_DB"])
grant = gpu_arbiter.acquire("llm", "http://127.0.0.1:1/v1", model="child-model", label="child", timeout=20)
print("held", flush=True)
time.sleep(120)
'''


@unittest.skipUnless(DB_URI, 'set OPENBENCH_TEST_DB_URI')
class DatabaseArbiterTests(unittest.TestCase):
    def connect(self):
        import psycopg
        return psycopg.connect(DB_URI)

    def setUp(self):
        from project_docs import repository as repo
        with self.connect() as conn:
            repo.ensure_schema(conn)
            conn.execute('DELETE FROM projectops.assistant_setting WHERE project_slug=%s', (arbiter.STATE_SLUG,))
        for target in (patch.object(arbiter, 'CONNECT', self.connect), patch.object(arbiter, '_http', guarded_http),
                       patch.dict(os.environ, {arbiter.SWITCHING_ENV: ''})):
            target.start()
            self.addCleanup(target.stop)

    def child(self):
        proc = subprocess.Popen([sys.executable, '-X', 'utf8', '-c', CHILD, str(ROOT)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env={**os.environ, 'ZF_GPU_TEST_DB': DB_URI}, text=True)
        self.addCleanup(proc.stderr.close); self.addCleanup(proc.stdout.close)
        self.addCleanup(lambda: proc.poll() is None and (proc.kill(), proc.wait(10)))
        lines = []
        reader = threading.Thread(target=lambda: lines.append(proc.stdout.readline()), daemon=True)
        reader.start(); reader.join(60)
        self.assertEqual(lines, ['held\n'], proc.stderr.read() if proc.poll() is not None else 'child did not report')
        return proc

    def test_processes_serialize_and_a_dead_holder_releases(self):
        proc = self.child()
        started = time.monotonic()
        with self.assertRaises(arbiter.GpuBusy):  # another process holds it: a bounded wait ends cleanly
            arbiter.acquire(arbiter.COMFY, 'http://localhost:8188', label='render', timeout=0.6)
        self.assertLess(time.monotonic() - started, 4)
        gpu = next(g for g in arbiter.status()['gpus'] if g['key'] == arbiter.LOCAL_KEY)
        self.assertEqual((gpu['owner']['workload'], gpu['owner']['label']), ('llm', 'child'))
        self.assertEqual(gpu['waiters'], [])
        waiter = Holder(workload=arbiter.COMFY, url='http://localhost:8188', label='render-2', timeout=40)
        waiter.start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            gpu = next(g for g in arbiter.status()['gpus'] if g['key'] == arbiter.LOCAL_KEY)
            if gpu['waiters']:
                break
            time.sleep(0.05)
        self.assertEqual([(w['workload'], w['label']) for w in gpu['waiters']], [('comfy', 'render-2')])
        self.assertFalse(waiter.held.is_set())
        proc.kill(); proc.wait(10)  # the holder dies without releasing: its session goes, and so does the lock
        self.assertTrue(waiter.held.wait(30), 'the lock of a dead holder was not released')
        self.assertIsNone(waiter.error)
        gpu = next(g for g in arbiter.status()['gpus'] if g['key'] == arbiter.LOCAL_KEY)
        self.assertEqual((gpu['owner']['label'], gpu['resident']['workload']), ('render-2', 'comfy'))
        waiter.done.set(); waiter.join(10)
        gpu = next(g for g in arbiter.status()['gpus'] if g['key'] == arbiter.LOCAL_KEY)
        self.assertIsNone(gpu['owner'])

    def test_resident_workload_is_shared_through_the_database(self):
        server, base, calls = fake_gpu()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        with patch.dict(os.environ, {arbiter.SWITCHING_ENV: 'on'}):
            arbiter.acquire(arbiter.LLM, base + '/v1', model='planner', timeout=5).release()
            with self.connect() as conn:
                row = conn.execute('SELECT value FROM projectops.assistant_setting WHERE project_slug=%s AND key=%s',
                                   (arbiter.STATE_SLUG, arbiter.STATE_PREFIX + arbiter.LOCAL_KEY)).fetchone()
            state = json.loads(row[0])
            self.assertEqual((state['workload'], state['llm'], state['owner']), ('llm', [{'base_url': base + '/v1', 'model': 'planner'}], None))
            # Another process's render reads the same state: it unloads the model this process left loaded.
            arbiter._memory.clear()
            calls.clear()
            arbiter.acquire(arbiter.COMFY, base, label='render', timeout=5).release()
            self.assertEqual([(c[1], c[2]) for c in calls], [('/api/generate', {'model': 'planner', 'keep_alive': 0})])
        resident = next(g for g in arbiter.status()['gpus'] if g['key'] == arbiter.LOCAL_KEY)['resident']
        self.assertEqual(resident, {'workload': 'comfy', 'since': resident['since'], 'models': [], 'comfy': base})


@unittest.skipUnless(DB_URI, 'set OPENBENCH_TEST_DB_URI')
class QuickstartGovernanceTests(unittest.TestCase):
    """The Agent Console Quickstart builder is admitted like an agent turn (SPEC_20 R11)."""
    import test_agent_console as _console
    setUp, tearDown = _console.ConsoleHTTPTests.setUp, _console.ConsoleHTTPTests.tearDown
    request, prepare, call, ok = (_console.ConsoleHTTPTests.request, _console.ConsoleHTTPTests.prepare,
                                  _console.ConsoleHTTPTests.call, _console.ConsoleHTTPTests.ok)
    api = _console.ConsoleHTTPTests.api

    ASK = {'messages': [{'role': 'user', 'content': 'An agent that checks continuity on every finished shot.'}], 'template_key': 'blank'}

    def reservations(self):
        self.conn.rollback()
        return [r[0] for r in self.conn.execute("""SELECT jsonb_build_object('state',state,'cost',accounted_cost_usd,'agent',agent_key,
            'kind',usage_kind,'session',session_key,'model',model_name) FROM projectops.agent_usage_reservation
            WHERE project_slug=%s ORDER BY created_at""", (self.slug,)).fetchall()]

    def coordinator(self, config):
        from project_assistant import agent_registry
        agent_registry.save_agent(self.conn, self.me, self.slug, {'agent_key': 'coordinator', 'provider_config': config})
        self.conn.commit()

    def test_local_builder_is_admitted_unbilled_and_attributed(self):
        self.coordinator(self.config)
        self.responses.append({'content': json.dumps({'reply': 'Drafted.', 'changes': {'display_name': 'Continuity checker'}})})
        with patch.object(arbiter, '_http', guarded_http):
            result = self.api('/quickstart/converse', 'POST', self.ASK)
        self.assertEqual((result['mode'], result['draft']['display_name']), ('model', 'Continuity checker'))
        [row] = self.reservations()
        self.assertEqual((row['state'], row['cost'], row['agent'], row['kind'], row['model']),
                         ('finalized', None, 'coordinator', 'llm_turn', 'console-fixture'))
        self.assertTrue(row['session'].startswith('quickstart:'))
        ledger = self.conn.execute("SELECT input_tokens, output_tokens, meta->>'outcome' FROM projectops.agent_usage_ledger WHERE project_slug=%s",
                                   (self.slug,)).fetchall()
        self.assertEqual(ledger, [(42, 8, 'succeeded')])

    def test_hosted_builder_is_refused_without_an_allowlisted_host_or_a_price(self):
        import governance_fixture
        from project_assistant import agent_console_service as app
        hosted = 'https://builder.invalid/v1'
        env = patch.dict(os.environ, {'OPENBENCH_AGENT_KEY_ENVS': 'SPEC20_BUILDER_KEY', 'SPEC20_BUILDER_KEY': 'synthetic-credential'})
        env.start(); self.addCleanup(env.stop)
        self.coordinator({'kind': 'openai_compat', 'base_url': hosted, 'model': 'hosted-builder', 'api_key_env': 'SPEC20_BUILDER_KEY'})
        sent = []
        def turn(**kwargs):
            return providers.run_openai_compat_turn(**kwargs, opener=lambda request, timeout: sent.append(request.full_url) or reply({'content': '{}'}))
        refused = app.converse(self.conn, self.me, self.slug, self.ASK, turn=turn)  # the restricted environment reaches loopback only
        governance_fixture.authorize_synthetic_media(self)
        unpriced = app.converse(self.conn, self.me, self.slug, self.ASK, turn=turn)  # full network, but no price ceiling
        for result in (refused, unpriced):
            self.assertEqual((result['mode'], result['error_kind'], result['changed'], result['persisted']),
                             ('deterministic_preview', 'policy', [], False))
            self.assertTrue(result['error'])
            self.assertNotIn('synthetic-credential', json.dumps(result))
        self.assertEqual((sent, self.reservations()), ([], []))  # nothing left the server, nothing was reserved

if __name__ == '__main__':
    unittest.main()
