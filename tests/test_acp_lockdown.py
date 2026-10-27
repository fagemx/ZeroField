"""SPEC_20 R35: the optional ACP worker's lock-down, tested against fake ACP agents (never a real CLI or model).

Rules: one MCP server and no user config, scrubbed environment, confirmed session mode, default-deny one-shot
permissions, process-tree kill on any unexpected tool call (with the failure settled at the Head), slash
command blocking, and the offline tool listing in scripts/audit_tool_surface.py.
"""
import copy
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from project_assistant import acp_bridge, acp_lockdown, limb_worker

ROOT = Path(__file__).resolve().parents[1]
AGENT = Path(__file__).parent / 'fixtures' / 'fake_acp_lockdown_agent.py'
MOCK = Path(__file__).parent / 'fixtures' / 'mock_acp_agent.py'
_SPEC = importlib.util.spec_from_file_location('audit_tool_surface', ROOT / 'scripts' / 'audit_tool_surface.py')
audit = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(audit)

SECRETS = {'OPENBENCH_LIMB_TOKEN': 'head-bearer-0123456789', 'OPENBENCH_DB_URI': 'postgresql://zf:pw-0123456789@db/zf',
           'OPENAI_API_KEY': 'sk-ambient-0123456789', 'ANTHROPIC_API_KEY': 'sk-ant-0123456789',
           'AWS_ACCESS_KEY_ID': 'AKIA0123456789ABCD', 'AWS_SECRET_ACCESS_KEY': 'aws-secret-0123456789',
           'AWS_SESSION_TOKEN': 'aws-session-0123456789', 'AZURE_CLIENT_SECRET': 'azure-secret-0123456789',
           'GOOGLE_APPLICATION_CREDENTIALS': 'C:/creds/gcp-0123456789.json', 'GITHUB_TOKEN': 'ghp_0123456789abcdef',
           'GH_TOKEN': 'gho_0123456789abcdef', 'NPM_TOKEN': 'npm_0123456789abcdef', 'HF_TOKEN': 'hf_0123456789abcdef',
           'DATABASE_URL': 'postgres://u:p-0123456789@h/d', 'COMFY_API_KEY': 'comfy-0123456789',
           'PGPASSWORD': 'pg-password-0123456789', 'SSH_AUTH_SOCK': '/tmp/ssh-agent.sock', 'KUBECONFIG': 'C:/kube/config'}


class Proxy:
    def __init__(self, names=('read_page',)):
        self.names, self.calls, self.pending = list(names), [], threading.Event()
    def list_tools(self):
        return [{'name': name, 'description': name, 'inputSchema': {'type': 'object'}} for name in self.names]
    def call(self, name, args):
        self.calls.append((name, args))
        return 'scoped page'


def run(scenario, *args, folder, prompt='Synthetic task', env=None, proxy=None, timeout=20, mode=None, command=None):
    return acp_bridge.run_acp(command=command or [sys.executable, str(AGENT.resolve()), scenario, *args], cwd=folder,
        env={**os.environ, **(env or {})}, prompt=prompt, tool_proxy=proxy or Proxy(),
        deadline_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=timeout),
        cancel_event=threading.Event(), required_mode=mode)


def alive(pid, wait=5.0):
    """Whether a process still runs after waiting up to `wait` seconds for it to end."""
    if os.name == 'nt':
        import ctypes
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.OpenProcess.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_uint]; api.OpenProcess.restype = ctypes.c_void_p
        api.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]; api.WaitForSingleObject.restype = ctypes.c_uint
        api.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = api.OpenProcess(0x100000 | 0x1000, False, pid)  # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            return api.WaitForSingleObject(handle, int(wait * 1000)) != 0
        finally:
            api.CloseHandle(handle)
    until = time.monotonic() + wait
    while time.monotonic() < until:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        time.sleep(.05)
    return True


def assert_no_secrets(test, env):
    """No ambient credential name or value; OPENAI_API_KEY may only hold the configured adapter key."""
    for name, value in SECRETS.items():
        if name != 'OPENAI_API_KEY':
            test.assertNotIn(name, env)
        test.assertFalse(any(value in v for v in env.values()), name)


def pid(folder, name):
    path = Path(folder) / name
    assert path.exists() and path.read_text().strip(), f'the fake agent did not record {name}'
    return int(path.read_text())


class PolicyTests(unittest.TestCase):
    """The pure rules in acp_lockdown."""

    def test_environment_is_an_allowlist_without_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            source = {**SECRETS, 'PATH': os.environ.get('PATH', ''), 'SYSTEMROOT': 'C:/Windows', 'PYTHONPATH': 'C:/private',
                      'HOME': 'C:/Users/me', 'CODEX_HOME': 'C:/Users/me/.codex', 'CLAUDE_CONFIG_DIR': 'C:/Users/me/.claude',
                      'ACP_MODEL_API_KEY': 'configured-key-0123456789',
                      'CODEX_CONFIG': json.dumps({'model': 'local-model', 'mcp_servers': {'evil': {'command': 'evil'}},
                          'profiles': {'p': {}}, 'hooks': {'x': 1}, 'model_providers': {'local': {'base_url': 'http://127.0.0.1:11434/v1',
                          'env_key': 'OPENAI_API_KEY', 'http_headers': {'X-Key': 'leak'}, 'experimental_bearer_token': 'leak-token'}}})}
            env = acp_lockdown.clean_env(source, folder)
            assert_no_secrets(self, env)
            self.assertEqual(env['OPENAI_API_KEY'], 'configured-key-0123456789')  # only the configured key, mapped
            self.assertNotIn('PYTHONPATH', env)
            self.assertEqual(env['PATH'], source['PATH'])
            for name in acp_lockdown.CONFIG_HOMES:
                self.assertTrue(Path(env[name]).resolve().is_relative_to(Path(folder).resolve()), name)
            self.assertEqual(env['CODEX_HOME'], str(Path(folder) / '.codex'))
            self.assertEqual(env['INITIAL_AGENT_MODE'], 'read-only')
            config = json.loads(env['CODEX_CONFIG'])
            self.assertEqual(config['model'], 'local-model')
            self.assertEqual(set(config) - {'model', 'model_providers'}, {'approval_policy', 'sandbox_mode', 'web_search', 'features'})
            self.assertEqual(config['model_providers'], {'local': {'base_url': 'http://127.0.0.1:11434/v1', 'env_key': 'OPENAI_API_KEY'}})
            self.assertEqual(config['sandbox_mode'], 'read-only')
            self.assertFalse(any(config['features'].values()))
            self.assertIn('shell_tool', config['features'])

    def test_codex_config_carrying_a_credential_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            for config in ({'model_providers': {'p': {'base_url': 'https://user:pass@models.example/v1'}}},
                           {'model': 'sk-ambient-0123456789'}):
                with self.subTest(config=config), self.assertRaises(ValueError):
                    acp_lockdown.clean_env({**SECRETS, 'CODEX_CONFIG': json.dumps(config)}, folder)
            with self.assertRaises(ValueError):
                acp_lockdown.clean_env({'CODEX_CONFIG': '["not an object"]'}, folder)

    def test_required_mode_cannot_be_permissive(self):
        for mode in ('read-only', 'plan', 'ask', 'default'):
            self.assertEqual(acp_lockdown.required_mode(mode), mode)
        self.assertEqual(acp_lockdown.required_mode(None), 'read-only')
        for mode in ('full-access', 'Full_Access', 'bypassPermissions', 'BYPASS-PERMISSIONS', 'yolo', 'acceptEdits',
                     'auto', 'agent', '', ' read-only', '../x', 5):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                acp_lockdown.required_mode(mode)

    def test_session_mode_from_modes_and_config_options(self):
        self.assertEqual(acp_lockdown.session_mode({'modes': {'currentModeId': 'read-only', 'availableModes': [{'id': 'read-only'}, {'id': 'auto'}]}}),
                         ('read-only', ('mode', None), {'read-only', 'auto'}))
        option = {'id': 'mode', 'type': 'select', 'currentValue': 'auto',
                  'options': [{'group': 'g', 'name': 'G', 'options': [{'value': 'read-only', 'name': 'RO'}]}, {'value': 'auto', 'name': 'A'}]}
        self.assertEqual(acp_lockdown.session_mode({'configOptions': [{'id': 'model', 'currentValue': 'x'}, option]}),
                         ('auto', ('config', 'mode'), {'read-only', 'auto'}))
        self.assertEqual(acp_lockdown.session_mode({'sessionId': 's'}), (None, None, set()))

    def test_slash_commands_are_found_at_the_start_and_on_command_lines(self):
        for text in ('/logout', '  /compact now', '\u200b\ufeff/init', '\uff0finit', '\n\n/review',
                     'Plan the shot.\n/mcp:evil:run x', 'Notes\n   /logout', '/'):
            with self.subTest(text=text):
                self.assertIsNotNone(acp_lockdown.slash_command(text))
        for text in ('Plan the shot.', 'Read /usr/local/bin/tool output', 'Path:\n/usr/local/bin/tool',
                     json.dumps({'input': 'line\n/logout'}), 'a/b', 'Ratio 1/2'):
            with self.subTest(text=text):
                self.assertIsNone(acp_lockdown.slash_command(text))

    def test_tool_targets_of_both_adapters(self):
        target = acp_lockdown.tool_target
        self.assertEqual(target({'rawInput': {'server': 'openbench', 'tool': 'read_page'}, '_meta': {'is_mcp_tool_call': True}}),
                         ('mcp', 'openbench', 'read_page'))
        self.assertEqual(target({'_meta': {'claudeCode': {'toolName': 'mcp__openbench__read_page'}}}), ('mcp', 'openbench', 'read_page'))
        self.assertEqual(target({'_meta': {'claudeCode': {'toolName': 'Bash'}}, 'kind': 'think'}), ('tool', 'Bash'))
        self.assertEqual(target({'rawInput': {'server': 'openbench', 'tool': 'read_page'}}), ('kind', 'other'))  # no MCP marker
        allowed = frozenset({'read_page'})
        self.assertTrue(acp_lockdown.tool_allowed(('mcp', 'openbench', 'read_page'), allowed))
        self.assertTrue(acp_lockdown.tool_allowed(('mcp', 'codex', 'list_mcp_resources'), allowed))
        self.assertTrue(acp_lockdown.tool_allowed(('kind', 'think'), allowed))
        for bad in (('mcp', 'openbench', 'propose'), ('mcp', 'evil', 'read_page'), ('mcp', 'codex', 'shell'),
                    ('kind', 'execute'), ('kind', 'other'), ('tool', 'Bash')):
            self.assertFalse(acp_lockdown.tool_allowed(bad, allowed), bad)

    def test_turn_folder_must_start_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / '.mcp.json').write_text('{"mcpServers": {"evil": {}}}')
            with self.assertRaises(ValueError):
                acp_lockdown.prepare_folder(Path(folder))


class AgentProcessTests(unittest.TestCase):
    """The bridge against fake ACP agents over real stdio."""

    def test_agent_sees_only_openbench_scrubbed_env_and_empty_config_homes(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as home:
            # A user home with config every agent CLI would otherwise load.
            for relative, text in (('.codex/config.toml', '[mcp_servers.evil]\ncommand = "evil"\n'),
                                   ('.claude/settings.json', '{"enabledPlugins": {"evil": true}}'),
                                   ('.claude.json', '{"mcpServers": {"evil": {}}}'), ('.mcp.json', '{"mcpServers": {"evil": {}}}')):
                (Path(home) / relative).parent.mkdir(parents=True, exist_ok=True)
                (Path(home) / relative).write_text(text)
            planted = {name: home for name in ('HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'XDG_CONFIG_HOME')}
            planted.update(CODEX_HOME=str(Path(home) / '.codex'), CLAUDE_CONFIG_DIR=str(Path(home) / '.claude'),
                           CODEX_CONFIG=json.dumps({'model': 'local-model', 'mcp_servers': {'evil': {'command': 'evil'}}}),
                           ACP_MODEL_API_KEY='configured-key-0123456789')
            result = run('env', folder=folder, env={**SECRETS, **planted})
            self.assertEqual(result['status'], 'succeeded', result)
            seen = json.loads(result['output']['text'])
        env = seen['env']
        assert_no_secrets(self, env)
        self.assertEqual(env['OPENAI_API_KEY'], 'configured-key-0123456789')
        self.assertLessEqual({k.upper() for k in env} - {'OPENAI_API_KEY', 'CODEX_CONFIG', 'NO_BROWSER', 'INITIAL_AGENT_MODE',
                              'PYTHONIOENCODING'} - set(acp_lockdown.CONFIG_HOMES), set(acp_lockdown.ENV_KEEP) | {'SYSTEMROOT'})
        for name in acp_lockdown.CONFIG_HOMES:
            self.assertNotIn(home, env[name], name)
        self.assertNotIn('mcp_servers', json.loads(env['CODEX_CONFIG']))
        self.assertEqual(seen['files'], ['agent.started', 'prompted'])  # no config file in any home the agent reads
        servers = seen['session_new']['mcpServers']
        self.assertEqual([s['name'] for s in servers], ['openbench'])
        self.assertEqual(servers[0]['command'], sys.executable)
        self.assertEqual(Path(servers[0]['args'][-1]).name, 'mcp_stdio.py')
        self.assertEqual({item['name'] for item in servers[0]['env']}, {'PA_TOOL_URL', 'PA_TOKEN'})
        self.assertEqual(seen['initialize']['clientCapabilities'], {'fs': {'readTextFile': False, 'writeTextFile': False}, 'terminal': False})
        self.assertEqual(seen['requests'], ['initialize', 'authenticate', 'session/new', 'session/prompt'])

    def test_work_is_sent_only_after_the_reported_mode_matches(self):
        cases = [
            ((), 'read-only', 'succeeded', None),                                    # codex-acp started read-only
            (('mode', 'auto', 'auto,full-access'), None, 'failed', 'mode_mismatch'),  # required mode not offered
            (('mode', 'none', '-'), None, 'failed', 'mode_mismatch'),                 # nothing reported
            (('mode', 'default', 'default,plan', 'notify'), 'plan', 'succeeded', None),  # switched once, agent confirms
            (('mode', 'default', 'default,plan'), 'plan', 'failed', 'mode_mismatch'),    # switch never confirmed
            (('config_mode', 'auto', 'read-only,auto'), None, 'succeeded', None),        # session config option
        ]
        for args, mode, status, reason in cases:
            with self.subTest(args=args, mode=mode), tempfile.TemporaryDirectory() as folder:
                scenario, rest = (args[0], args[1:]) if args else ('echo', ())
                result = run(scenario, *rest, folder=folder, mode=mode)
                self.assertEqual(result['status'], status, result)
                self.assertEqual(result.get('reason'), reason)
                self.assertEqual((Path(folder) / 'prompted').exists(), status == 'succeeded')
                if reason:
                    self.assertIn('restricted session mode', result['error'])

    def test_permissive_required_mode_is_refused_before_start(self):
        with tempfile.TemporaryDirectory() as folder:
            for mode in ('full-access', 'bypassPermissions'):
                with self.assertRaises(ValueError):
                    run('echo', folder=folder, mode=mode)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_permissions_default_deny_and_grant_allow_once_one_shot(self):
        with tempfile.TemporaryDirectory() as folder:
            result = run('permission', folder=folder)
        self.assertEqual(result['status'], 'succeeded', result)
        answers = json.loads(result['output']['text'])
        cancelled = {'outcome': {'outcome': 'cancelled'}}
        self.assertEqual(answers['first'], {'outcome': {'outcome': 'selected', 'optionId': 'ao'}})  # never allow_always
        self.assertEqual(answers['replay'], cancelled)        # one-shot per tool call
        self.assertEqual(answers['always_only'], cancelled)   # no allow_once offered
        self.assertEqual(answers['no_tool_call'], cancelled)
        self.assertEqual(answers['unannounced'], cancelled)   # not a tracked call
        self.assertEqual(answers['claude'], {'outcome': {'outcome': 'selected', 'optionId': 'once'}})

    def test_unexpected_tool_call_kills_the_whole_tree_at_once(self):
        variants = ('native', 'claude_native', 'other_server', 'unlisted', 'update', 'permission', 'fs', 'terminal', 'orphan')
        for variant in variants:
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as folder:
                start = time.monotonic()
                result = run('trip', variant, folder=folder, timeout=60)
                elapsed = time.monotonic() - start
                self.assertEqual(result['status'], 'failed', result)
                self.assertEqual(result['reason'], 'unexpected_tool_call')
                self.assertIn("outside this turn's allowed list", result['error'])
                self.assertTrue((Path(folder) / 'violation.sent').exists())
                self.assertLess(elapsed, 15)  # the fake agent would sleep 60 s; the deadline is 60 s
                for name in ('child.pid', 'grandchild.pid'):
                    self.assertFalse(alive(pid(folder, name)), f'{variant}: {name} survived')

    def test_leaving_the_mode_mid_turn_kills_the_tree(self):
        with tempfile.TemporaryDirectory() as folder:
            result = run('drift', folder=folder, timeout=60)
            self.assertEqual((result['status'], result['reason']), ('failed', 'mode_changed'), result)
            self.assertIn('full-access', result['error'])
            for name in ('child.pid', 'grandchild.pid'):
                self.assertFalse(alive(pid(folder, name)), name)

    def test_slash_commands_never_reach_the_agent(self):
        for prompt in ('/logout', '  \u200b/compact now', '\uff0finit', 'Plan the shot.\n/mcp:evil:run'):
            with self.subTest(prompt=prompt), tempfile.TemporaryDirectory() as folder:
                result = run('echo', folder=folder, prompt=prompt)
                self.assertEqual((result['status'], result['reason']), ('failed', 'slash_command'), result)
                self.assertEqual(list(Path(folder).iterdir()), [])  # the agent was never started
        with tempfile.TemporaryDirectory() as folder:
            prompt = 'Plan the shot.\n' + json.dumps({'input': {'note': 'cell text\n/logout'}}) + '\nRead /usr/local/bin/tool'
            result = run('echo', folder=folder, prompt=prompt)
            self.assertEqual(result['status'], 'succeeded', result)
            self.assertEqual(result['output']['text'], prompt)

    def test_turn_tools_are_frozen_at_start(self):
        class Growing(Proxy):
            def list_tools(self):
                listed = super().list_tools()
                self.names.append('propose')  # a grant appearing mid-turn never reaches the agent
                return listed
        with tempfile.TemporaryDirectory() as folder:
            proxy = Growing()
            result = run('tools', folder=folder, proxy=proxy, command=[sys.executable, str(MOCK.resolve()), 'tools'])
        self.assertEqual(result['status'], 'succeeded', result)
        self.assertEqual(proxy.calls, [('read_page', {'key': 'overview'})])


class FakeHead:
    """The Head's worker API without a database: one ACP dispatch, recorded reports."""
    def __init__(self, system_prompt=''):
        self.reports, self.prefer_orchestration = [], True
        self.task = {'id': 'd1', 'dispatch_handle': 'dsp_d1_1', 'lease_token': 'lease', 'capability': 'llm',
                     'deadline_at': (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=60)).isoformat(),
                     'input': {'prompt': 'Fill the shot'}, 'profile': {'system_prompt': system_prompt, 'knowledge_pack': ''}}
    def action(self, name, payload=None):
        if name == 'orchestration/claim':
            task, self.task = self.task, None
            return {'task': task, 'lease_seconds': 120}
        if name == 'orchestration/tool_list':
            return {'tools': [{'name': 'read_page', 'description': 'Read', 'inputSchema': {'type': 'object'}}]}
        self.reports.append((name, payload))
        return {}


class WorkerReportTests(unittest.TestCase):
    """limb_worker reports a lock-down stop as a non-retryable failure with its reason."""

    def process(self, scenario, *args, system_prompt=''):
        head = FakeHead(system_prompt)
        config = {'orchestration_enabled': True, 'capabilities': {'llm': {'adapter': 'acp_stdio', 'model': 'fake',
                  'command': [sys.executable, str(AGENT.resolve()), scenario, *args]}}}
        with patch('builtins.print'):
            self.assertTrue(limb_worker.process_one(head, config))
        return head.reports

    def test_unexpected_tool_call_reports_failure_with_reason(self):
        reports = self.process('trip', 'native')
        self.assertEqual([name for name, _ in reports], ['orchestration/fail'])
        body = reports[0][1]
        self.assertEqual(body['reason'], 'unexpected_tool_call')
        self.assertIs(body['retryable'], False)
        self.assertIn("outside this turn's allowed list", body['error'])
        self.assertEqual(body['dispatch_handle'], 'dsp_d1_1')

    def test_slash_command_in_mounted_instructions_reports_failure(self):
        reports = self.process('echo', system_prompt='Crew notes\n/logout')
        self.assertEqual(reports[0][0], 'orchestration/fail')
        self.assertEqual(reports[0][1]['reason'], 'slash_command')

    def test_clean_turn_completes(self):
        reports = self.process('echo')
        self.assertEqual([name for name, _ in reports], ['orchestration/complete'])


class OfflineListingTests(unittest.TestCase):
    """The ACP tool surface is listed through the real mount without an agent, and a new entry fails the audit."""

    def test_acp_listing_matches_the_mcp_server_and_the_snapshot(self):
        from project_assistant import tool_registry
        actual = audit.surface()
        self.assertEqual(actual['acp']['ceiling'], [t.name for t in tool_registry.all_tools() if t.mcp])
        self.assertEqual(actual['acp']['mcp_servers'], ['openbench'])
        expected = json.loads(audit.SNAPSHOT.read_text(encoding='utf-8'))
        self.assertEqual(audit.differences(expected, actual), [])

    def test_listing_follows_the_turn_grants(self):
        listed = acp_bridge.list_turn_tools({'reader': Proxy(['read_page', 'not_a_tool']).list_tools,
                                             'none': Proxy([]).list_tools})
        self.assertEqual(listed, {'reader': ['read_page'], 'none': []})

    def test_any_widening_of_the_acp_surface_fails(self):
        base = audit.surface()
        changes = {
            'ceiling': lambda acp: acp['ceiling'].append('shell_exec'),
            'mcp_servers': lambda acp: acp['mcp_servers'].append('evil'),
            'agent_builtins': lambda acp: acp['agent_builtins'].append('codex/shell'),
            'grant_kinds': lambda acp: acp['grant_kinds'].append('allow_always'),
            'env_keep': lambda acp: acp['env_keep'].append('GITHUB_TOKEN'),
            'forbidden_modes': lambda acp: acp['forbidden_modes'].remove('full-access'),
            'config_homes': lambda acp: acp['config_homes'].remove('CLAUDE_CONFIG_DIR'),
            'codex_features_disabled': lambda acp: acp['codex_features_disabled'].remove('shell_tool'),
            'client_capabilities': lambda acp: acp['client_capabilities'].update(terminal=True),
            'default_mode': lambda acp: acp.update(default_mode='auto'),
        }
        for key, change in changes.items():
            with self.subTest(key=key):
                actual = copy.deepcopy(base)
                change(actual['acp'])
                lines = audit.differences(base, actual)
                self.assertTrue(lines and lines[0].startswith(f'acp {key}: '), lines)
                self.assertTrue('unexpected' in lines[0] or 'changed' in lines[0], lines)
        narrowed = copy.deepcopy(base)
        narrowed['acp']['ceiling'].remove('read_page')
        self.assertEqual(audit.differences(base, narrowed), ['acp ceiling: no longer listed read_page'])



@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'set OPENBENCH_TEST_DB_URI')
class HeadSettlementTests(unittest.TestCase):
    """End to end on PostgreSQL: a real worker runs the ACP adapter; the trip settles the dispatch at the Head."""

    def setUp(self):
        import test_product_http as fixture
        fixture.ProductHTTPTests.setUp(self)

    def tearDown(self):
        import test_product_http as fixture
        fixture.ProductHTTPTests.tearDown(self)

    def test_tripped_turn_is_failed_with_reason_lease_released_and_proposals_dismissed(self):
        from project_assistant import orchestrator as cp, orchestration_store as db, agent_registry
        agent_registry.save_agent(self.conn, self.me, self.slug, {'agent_key': 'acp_writer', 'runtime_kind': 'acp_stdio',
            'bound_limb_id': self.worker['id'], 'capabilities': ['llm'], 'allowed_tools': ['read_page', 'propose_table_edit']})
        run_ = cp.create_run(self.conn, self.me, self.slug, 'ACP lock-down', client_request_id='acp-trip')
        task = cp.create_task(self.conn, self.me, self.slug, run_['id'], objective='Fill output', agent_key='acp_writer',
                              target={'tab_key': 'shots', 'kind': 'table', 'row_id': 'b_shot1', 'col_index': 1})
        cp.spawn_dispatch(self.conn, self.slug, task['id'], agent_key='acp_writer', slot_key='single')
        self.conn.commit()
        head = limb_worker.Head(f'http://127.0.0.1:{self.server.server_port}', self.token)
        config = {'orchestration_enabled': True, 'capabilities': {'llm': {'adapter': 'acp_stdio', 'model': 'fake',
                  'command': [sys.executable, str(AGENT.resolve()), 'db_trip']}}}
        with patch('builtins.print'):
            self.assertTrue(limb_worker.process_one(head, config))
        self.conn.rollback()
        dispatch = db.one(self.conn, "SELECT to_jsonb(d) FROM projectops.orchestration_dispatch d WHERE task_id=%s", (task['id'],))
        self.assertEqual(dispatch['status'], 'failed')
        self.assertEqual(dispatch['error'], acp_lockdown.FAILURES['unexpected_tool_call'])
        self.assertEqual(dispatch['output_json']['reason'], 'unexpected_tool_call')
        self.assertIsNone(dispatch['lease_until'])
        self.assertIsNotNone(dispatch['finished_at'])
        proposals = db.many(self.conn, "SELECT status FROM projectops.assistant_proposal WHERE dispatch_id=%s", (dispatch['id'],))
        self.assertEqual(proposals, ['dismissed'])  # made before the trip, settled with the failure
        done = db.one(self.conn, "SELECT count(*) FROM projectops.orchestration_message WHERE dispatch_id=%s AND msg_type='worker_done'",
                      (dispatch['id'],))
        self.assertEqual(done, 1)
        self.assertNotEqual(db.get_task(self.conn, self.slug, task['id'])['status'], 'dispatched')
