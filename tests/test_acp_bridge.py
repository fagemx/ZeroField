import datetime as dt
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

from project_assistant import acp_bridge

FIXTURE = Path(__file__).parent / 'fixtures' / 'mock_acp_agent.py'

class Proxy:
    def __init__(self):
        self.calls = []
        self.pending = threading.Event()
    def list_tools(self):
        return [{'name': 'read_page', 'description': 'Read scoped page', 'inputSchema': {'type': 'object', 'properties': {'key': {'type': 'string'}}}}]
    def call(self, name, args):
        self.calls.append((name, args))
        return 'scoped page'

class ACPBridgeTests(unittest.TestCase):
    def run_agent(self, mode='split', *, timeout=8, cancel=None, proxy=None):
        with tempfile.TemporaryDirectory() as folder:
            return acp_bridge.run_acp(command=[sys.executable, str(FIXTURE.resolve()), mode], cwd=folder,
                env={**os.environ, 'OPENBENCH_LIMB_TOKEN': 'head-secret', 'OPENBENCH_DB_URI': 'db-secret'},
                prompt='Synthetic task', tool_proxy=proxy or Proxy(),
                deadline_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=timeout),
                cancel_event=cancel or threading.Event())

    def test_v1_split_frames_ignore_thoughts_and_unrelated_response(self):
        result = self.run_agent()
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(result['output']['text'], '已完成合成工作。')
        self.assertNotIn('PRIVATE', str(result))
        self.assertEqual(result['agent_info']['name'], 'wire-fixture')

    def test_mcp_is_really_mounted_and_forwards_only_allowed_tools(self):
        proxy = Proxy()
        result = self.run_agent('tools', proxy=proxy)
        self.assertEqual(result['status'], 'succeeded', result)
        self.assertEqual(proxy.calls, [('read_page', {'key': 'overview'})])

    def test_native_files_terminal_permissions_and_unknown_requests_denied(self):
        self.assertEqual(self.run_agent('deny')['status'], 'succeeded')

    def test_committed_mcp_question_stops_the_process_and_releases_turn(self):
        import json
        class Question(Proxy):
            def list_tools(self):
                return [{'name':'ask_decision_gate','description':'Ask','inputSchema':{'type':'object'}}]
            def call(self,name,args):
                return json.dumps({'gate_id':'fixture','awaiting_gate':True})
        self.assertEqual(self.run_agent('question',proxy=Question())['status'],'awaiting_gate')

    def test_invalid_json_eof_and_oversized_frames_fail_closed(self):
        for mode in ('invalid', 'eof', 'oversize'):
            with self.subTest(mode=mode):
                result = self.run_agent(mode)
                self.assertEqual(result['status'], 'failed')
                self.assertNotIn('head-secret', str(result))

    def test_timeout_and_lease_loss_stop_owned_processes_promptly(self):
        start = time.monotonic()
        self.assertEqual(self.run_agent('timeout', timeout=.5)['status'], 'timeout')
        self.assertLess(time.monotonic() - start, 8)
        cancel = threading.Event(); cancel.set()
        self.assertEqual(self.run_agent(cancel=cancel)['status'], 'canceled')

    def test_clean_environment_does_not_inherit_head_credentials_or_user_home(self):
        with tempfile.TemporaryDirectory() as folder:
            env = acp_bridge.clean_env({**os.environ, 'OPENBENCH_LIMB_TOKEN': 'secret', 'OPENAI_API_KEY': 'other-key',
                'CODEX_HOME': 'C:/private', 'PYTHONPATH': 'C:/private'}, folder)
            self.assertNotIn('OPENBENCH_LIMB_TOKEN', env)
            self.assertNotIn('OPENAI_API_KEY', env)
            self.assertNotIn('PYTHONPATH', env)
            self.assertEqual(env['CODEX_HOME'], str(Path(folder) / '.codex'))

    def test_lease_loss_kills_an_already_spawned_descendant(self):
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool:
            cancel=threading.Event()
            future=pool.submit(acp_bridge.run_acp,command=[sys.executable,str(FIXTURE.resolve()),'timeout'],cwd=folder,
                env=os.environ,prompt='descendant fixture',tool_proxy=Proxy(),
                deadline_at=dt.datetime.now(dt.timezone.utc)+dt.timedelta(seconds=15),cancel_event=cancel)
            marker=Path(folder)/'child.pid'
            until=time.monotonic()+7
            while not marker.exists() and time.monotonic()<until: time.sleep(.02)
            self.assertTrue(marker.exists(),'fixture must spawn a child before cancellation')
            child=int(marker.read_text()); cancel.set()
            self.assertEqual(future.result(timeout=8)['status'],'canceled')
            if os.name=='nt':
                import ctypes
                api=ctypes.WinDLL('kernel32',use_last_error=True)
                api.OpenProcess.argtypes=[ctypes.c_uint,ctypes.c_int,ctypes.c_uint]; api.OpenProcess.restype=ctypes.c_void_p
                api.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint]
                api.CloseHandle.argtypes=[ctypes.c_void_p]
                handle=api.OpenProcess(0x100000,False,child)
                if handle:
                    self.assertEqual(api.WaitForSingleObject(handle,2000),0)
                    api.CloseHandle(handle)
            else:
                with self.assertRaises(ProcessLookupError): os.kill(child,0)

    def test_child_not_reading_a_large_prompt_cannot_bypass_deadline(self):
        start=time.monotonic()
        with tempfile.TemporaryDirectory() as folder:
            result=acp_bridge.run_acp(command=[sys.executable,str(FIXTURE.resolve()),'blocked_write'],cwd=folder,
                env=os.environ,prompt='x'*500000,tool_proxy=Proxy(),
                deadline_at=dt.datetime.now(dt.timezone.utc)+dt.timedelta(seconds=1),cancel_event=threading.Event())
        self.assertEqual(result['status'],'timeout')
        # Includes Python startup, owned process teardown and HTTP server shutdown.
        # The timeout status is what distinguishes watchdog cancellation from EOF.
        self.assertLess(time.monotonic()-start,8)
