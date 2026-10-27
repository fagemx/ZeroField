"""SPEC_20 R15/R43: one declarative tool registry, the tables derived from it, argument validation for
every tool, and the offline tool-surface audit against tests/fixtures/tool_surface.json."""
import copy
import importlib.util
import json
import os
import re
import sys
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from project_assistant import (agent_console_store, agent_policy, agent_registry, delegation_tools, mcp_stdio,
                               studio_tools, tool_host, tool_registry, tool_specs, tools)

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location('audit_tool_surface', ROOT / 'scripts' / 'audit_tool_surface.py')
audit = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(audit)

# The pre-registry default grants, verbatim: seeded allowed_tools are compared as ordered lists.
READS = ['list_pages', 'read_page', 'search_pages']
REPORTS = ['report_cell', 'report_find', 'report_list', 'report_overview', 'report_sheet']
HISTORIC_GRANTS = {
    'doc_writer': READS + ['propose', 'offer_document', 'studio_ingest_script', 'studio_manage_asset', 'consult_advisor'],
    'sheet_ops': READS + REPORTS + ['propose_table_edit', 'studio_plan_allocation', 'studio_dispatch_shot',
                                    'studio_inspect_frames', 'studio_edit_timeline', 'consult_advisor'],
    'qa_critic': READS + REPORTS + ['propose', 'studio_inspect_frames'],
}
EXTERNAL_ONLY = {'get_workflow', 'request_generation'}  # declared for zerofield-mcp; no built-in grant


class ToolSurfaceAuditTests(unittest.TestCase):
    def test_surface_matches_checked_in_snapshot(self):
        self.assertTrue(audit.SNAPSHOT.exists(), 'Missing snapshot; run ' + audit.UPDATE)
        lines = audit.differences(json.loads(audit.SNAPSHOT.read_text(encoding='utf-8')), audit.surface())
        self.assertFalse(lines, audit.report(lines) if lines else '')

    def test_one_extra_tool_fails_with_instructions(self):
        actual = audit.surface()
        expected = copy.deepcopy(actual)
        actual['roles']['qa_critic']['mcp'].append('spawn_agent')
        actual['catalog']['shell_exec'] = {'category': 'legacy'}
        lines = audit.differences(expected, actual)
        self.assertEqual(lines[:2], ['qa_critic mcp: unexpected tool(s) spawn_agent',
                                     'catalog: unexpected tool shell_exec ({"category": "legacy"})'])
        self.assertIn(audit.UPDATE, audit.report(lines))
        expected['roles']['doc_writer']['grants'].reverse()
        self.assertIn('order changed', '\n'.join(audit.differences(expected, audit.surface())))

    def test_mcp_listing_is_the_internal_surface_of_exposed_tools(self):
        for role, view in audit.surface()['roles'].items():
            with self.subTest(role=role):
                self.assertEqual(view['mcp'], [n for n in view['internal'] if n in tool_registry.MCP])
                self.assertLessEqual(set(view['internal']), set(view['grants']))

    def test_zerofield_token_view_is_exposure_then_write_mode(self):
        views = audit.surface()['zerofield_mcp']
        self.assertEqual(set(views), {'propose_only', 'generate'})
        for mode, names in views.items():
            with self.subTest(mode=mode):
                self.assertEqual(names, [t.name for t in tool_registry.all_tools() if t.name in tool_registry.ZEROFIELD_MCP
                                         and (mode == 'generate' or t.name not in tool_registry.GENERATION)])
                self.assertFalse(set(names) & {'spawn_agent', 'trigger_flow_run', 'studio_dispatch_shot', 'search_pages', 'my_todo'})
        self.assertIn('request_generation', views['generate'])
        self.assertNotIn('request_generation', views['propose_only'])
        actual = audit.surface()
        expected = copy.deepcopy(actual)
        actual['zerofield_mcp']['propose_only'].append('spawn_agent')
        self.assertEqual(audit.differences(expected, actual)[:1], ['zerofield-mcp propose_only token: unexpected tool(s) spawn_agent'])

    def test_script_compares_without_writing(self):
        with patch('sys.stdout'), patch('sys.stderr'):
            self.assertEqual(audit.main([]), 0)
        with patch.object(audit, 'surface', return_value={'catalog': {}, 'roles': {}, 'ui_catalog': []}), \
             patch('sys.stdout'), patch('sys.stderr'):
            self.assertEqual(audit.main([]), 1)


class RegistryDerivationTests(unittest.TestCase):
    def test_tool_specs_tables_are_derived(self):
        declared = tool_registry.all_tools()
        self.assertEqual(tool_specs.TOOLS, [t.spec() for t in declared])
        self.assertEqual(tool_specs.TOOL_NAMES, {t.name for t in declared})
        self.assertEqual(set(tool_specs.STUDIO_SCHEMAS), {t.name for t in declared if t.category in ('studio', 'advisor')})
        self.assertEqual(tool_specs.DELEGATION_TOOLS, {'list_agents', 'spawn_agent', 'check_delegation', 'cancel_delegation',
                                                       'ask_decision_gate', 'trigger_flow_run'})
        self.assertEqual(tool_specs.MUTATING_TOOLS, {'propose', 'propose_table_edit', 'spawn_agent', 'cancel_delegation',
                                                     'ask_decision_gate', 'trigger_flow_run', 'request_generation'}
                         | set(tool_specs.STUDIO_SCHEMAS))
        self.assertEqual({n for n, p in tool_specs.DEFAULT_POLICIES.items() if p != 'auto'},
                         {'studio_ingest_script', 'studio_manage_asset', 'studio_dispatch_shot', 'studio_edit_timeline'})
        self.assertEqual(agent_console_store.STUDIO_TOOLS, set(tool_specs.STUDIO_SCHEMAS))
        self.assertEqual(set(tool_host.LABELS), tool_specs.TOOL_NAMES - set(tool_specs.STUDIO_SCHEMAS))
        self.assertEqual(tool_specs.LABELS, {'問題': 'q', '要修改': 'fix'})
        copies = tool_registry.specs()  # callers get copies and cannot corrupt the declared schemas
        copies[0]['inputSchema']['properties'].clear()
        self.assertTrue(tool_registry.get(copies[0]['name']).schema['properties'])

    def test_policy_deny_lists_are_derived(self):
        self.assertEqual(tool_registry.PRIMARY_ONLY, {'spawn_agent', 'cancel_delegation', 'trigger_flow_run',
                                                      'check_delegation', 'list_agents'})
        self.assertEqual(tool_registry.ANALYSIS_ONLY_DENIED, {'propose', 'propose_table_edit', 'trigger_flow_run',
                                                              'studio_ingest_script', 'studio_manage_asset',
                                                              'studio_dispatch_shot', 'studio_edit_timeline',
                                                              'request_generation'})
        self.assertEqual(tool_registry.RACE_DENIED, {'studio_ingest_script', 'studio_manage_asset',
                                                     'studio_dispatch_shot', 'studio_edit_timeline', 'request_generation'})
        self.assertEqual(dict(tool_registry.REQUIRES), {'spawn_agent': ('allow_subagents',),
                                                        'trigger_flow_run': ('allow_workflows',),
                                                        'consult_advisor': ('advisor_agent_key',)})

    def test_dispatch_tables_resolve_every_declared_handler(self):
        self.assertEqual(set(tools.HANDLERS), tool_specs.TOOL_NAMES, 'tools.HANDLERS must dispatch every declared tool')
        for name in tool_specs.TOOL_NAMES:
            with self.subTest(name=name):
                self.assertIs(tools.HANDLERS[name], tool_registry.handler(name))
        self.assertEqual(set(studio_tools.HANDLERS), set(tool_specs.STUDIO_SCHEMAS))
        self.assertEqual(set(delegation_tools.HANDLERS), tool_specs.DELEGATION_TOOLS)
        self.assertEqual(studio_tools.EXTERNAL_TOOLS, {'studio_plan_allocation', 'studio_inspect_frames', 'consult_advisor'})
        with self.assertRaises(LookupError):
            tool_registry.handlers('project_assistant.studio_tools', {})

    def test_default_grants_keep_the_historic_seed_lists(self):
        self.assertEqual(set(tool_registry.BUILTIN_ROLES), {row[0] for row in agent_registry.ROSTER})
        self.assertEqual(set(tool_registry.PRIMARY_ROLES), {row[0] for row in agent_registry.ROSTER if row[3] == 'primary'})
        # The Showrunner receives every tool except the external-agent ones (SPEC_20 R30), which no role gets by default.
        self.assertEqual(agent_registry.default_tools('coordinator'), sorted(tool_specs.TOOL_NAMES - EXTERNAL_ONLY))
        self.assertEqual(agent_registry.default_tools('coordinator', False),
                         sorted(tool_specs.TOOL_NAMES - tool_specs.DELEGATION_TOOLS - EXTERNAL_ONLY))
        self.assertFalse(any(tool_registry.get(name).grants for name in EXTERNAL_ONLY))
        for key, grants in HISTORIC_GRANTS.items():
            with self.subTest(key=key):
                self.assertEqual(agent_registry.default_tools(key), grants + ['ask_decision_gate'])
                self.assertEqual(agent_registry.default_tools(key, False), grants)
        self.assertEqual(agent_registry.default_tools('custom_agent'), agent_registry.default_tools('qa_critic'))

    def test_ui_catalog_matches_console_model(self):
        source = (ROOT / 'ui' / 'src' / 'agentConsole' / 'model.js').read_text(encoding='utf-8')
        listed = re.search(r'export const STUDIO_TOOLS = \[([^\]]*)\]', source)
        self.assertIsNotNone(listed, 'STUDIO_TOOLS is no longer a literal in ui/src/agentConsole/model.js')
        self.assertEqual(re.findall(r"'([a-z0-9_]+)'", listed.group(1)), list(tool_registry.UI),
                         'Update STUDIO_TOOLS in ui/src/agentConsole/model.js to the registry tools with ui=True.')

    def test_declarations_are_checked_and_the_registry_is_sealed(self):
        good = dict(name='fixture_tool', description='Fixture.', schema=tool_registry._obj({'q': {'type': 'string'}}),
                    category='context', handler='fixture.module:fixture_tool', grants=['qa_critic'])
        self.assertEqual(tool_registry.declare(good).grants, ('qa_critic',))
        for change in ({'schema': tool_registry._obj({'q': {'type': 'string', 'format': 'uri'}})},
                       {'schema': tool_registry._obj({'q': {'type': 'number'}})},
                       {'schema': tool_registry._obj({'q': {'type': 'array'}})},
                       {'schema': {'type': 'object', 'properties': {}}},
                       {'schema': tool_registry._obj({}, ['q'])},
                       {'policy': 'sometimes'}, {'grants': ['intern']}, {'requires': ['allow_everything']},
                       {'handler': 'no-colon'}, {'name': 'Bad Name'}, {'description': ' '}, {'mutating': 1},
                       {'ui': True, 'console': False}, {'console': False},
                       {'primary_only': True, 'grants': ['doc_writer']},
                       {'zerofield_mcp': 1}, {'zerofield_mcp': True, 'mcp': False},
                       {'zerofield_mcp': True, 'policy': 'always_ask'},
                       {'zerofield_mcp': True, 'requires': ['allow_subagents']}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                tool_registry.declare({**good, **change})
        # zerofield-mcp exposure: read-only tools of new categories appear, writes and legacy tools opt in.
        exposed = lambda **change: tool_registry.zerofield_exposed(tool_registry.declare({**good, **change}))  # noqa: E731
        self.assertTrue(exposed())
        self.assertFalse(exposed(mutating=True))
        self.assertTrue(exposed(mutating=True, zerofield_mcp=True))
        self.assertFalse(exposed(category='legacy'))
        self.assertFalse(exposed(category='delegation'))
        self.assertFalse(exposed(external=True))
        self.assertFalse(exposed(mcp=False))
        self.assertFalse(exposed(policy='always_ask'))
        self.assertFalse(exposed(zerofield_mcp=False))
        with self.assertRaises(RuntimeError):
            tool_registry.register(good)
        self.assertNotIn('fixture_tool', tool_specs.TOOL_NAMES)

    def test_extension_modules_add_tools_without_editing_the_declarations(self):
        marker = 'EXTENSIONS: tuple[str, ...] = ()'
        source = Path(tool_registry.__file__).read_text(encoding='utf-8')
        self.assertIn(marker, source)
        extension = types.ModuleType('fixture_tool_extension')
        extension.TOOLS = [dict(name='read_fixture', description='Read one fixture.', category='context',
                                schema={'type': 'object', 'properties': {'id': {'type': 'string'}}, 'required': ['id'],
                                        'additionalProperties': False},
                                handler='fixture_tool_extension:read_fixture', grants=['coordinator', 'qa_critic'])]
        fresh = types.ModuleType('tool_registry_fixture_copy')
        with patch.dict(sys.modules, {'fixture_tool_extension': extension, fresh.__name__: fresh}):
            code = compile(source.replace(marker, "EXTENSIONS: tuple[str, ...] = ('fixture_tool_extension',)"),
                           tool_registry.__file__, 'exec')
            exec(code, fresh.__dict__)  # noqa: S102 - a private copy of the registry, never the live one
        self.assertEqual(fresh.all_tools()[-1].name, 'read_fixture')
        self.assertEqual(fresh.default_grants('qa_critic'), agent_registry.default_tools('qa_critic') + ['read_fixture'])
        self.assertIn('read_fixture', fresh.default_grants('coordinator'))
        fresh.validate_args('read_fixture', {'id': 'shot-1'})
        with self.assertRaises(ValueError):
            fresh.validate_args('read_fixture', {})
        self.assertNotIn('read_fixture', tool_registry.NAMES)


class ArgumentValidationTests(unittest.TestCase):
    def rejects(self, name, args, message):
        with self.assertRaises(ValueError) as caught:
            tool_registry.validate_args(name, args)
        self.assertEqual(str(caught.exception), message)

    def test_every_declared_tool_rejects_unknown_arguments_and_non_objects(self):
        for tool in tool_registry.all_tools():
            noun = 'Studio tool' if tool.category in ('studio', 'advisor') else 'tool'
            with self.subTest(name=tool.name):
                self.rejects(tool.name, {'unexpected_argument': 'x'}, f'Unknown or missing {noun} arguments.')
                self.rejects(tool.name, ['not', 'an', 'object'], f'Unknown or missing {noun} arguments.')

    def test_legacy_and_delegation_arguments_follow_their_schemas(self):
        valid = [('read_page', {'key': 'shots', 'section': 'Scene', 'offset': 0, 'limit': 30}),
                 ('propose', {'action': '改狀態', 'page': 'shots', 'row': '1', 'status': 'Approved'}),
                 ('propose_table_edit', {'tab_key': 'shots', 'row_edits': [{'row_id': 'b1', 'cells': {'1': 'x'}}]}),
                 ('propose_table_edit', {'tab_key': 'shots', 'table_id': 't', 'row_edits': [], 'new_rows': [['a', 'b']]}),
                 ('spawn_agent', {'objective': 'Read', 'label_selector': {'domain': 'sheet'}, 'scope': {'tab_key': 'shots', 'row_ids': ['r']},
                                  'strategy': 'race', 'race_agents': ['a', 'b'], 'wait': True}),
                 ('ask_decision_gate', {'question': 'Which?', 'options': ['A', 'B']}),
                 ('list_pages', {}), ('my_todo', {})]
        for name, args in valid:
            with self.subTest(name=name, args=args):
                tool_registry.validate_args(name, args)
        invalid = [('read_page', {'section': 'x'}, 'Unknown or missing tool arguments.'),
                   ('read_page', {'key': 'shots', 'limit': 31}, 'Invalid tool option.'),
                   ('read_page', {'key': 'shots', 'offset': -1}, 'Invalid tool option.'),
                   ('read_page', {'key': 'shots', 'offset': '2'}, 'Invalid tool option.'),
                   ('read_page', {'key': 'shots', 'limit': True}, 'Invalid tool option.'),
                   ('read_page', {'key': 'shots', 'section': None}, 'Invalid tool string length.'),
                   ('read_page', {'key': 'sh\x00ots'}, 'Invalid tool string length.'),
                   ('search_pages', {'query': 'x' * 10001}, 'Invalid tool string length.'),
                   ('propose', {'action': 'delete everything'}, 'Invalid tool option.'),
                   ('propose', {'action': '改狀態', 'status': 'Done'}, 'Invalid tool option.'),
                   ('propose_table_edit', {'tab_key': 'shots', 'row_edits': [{'row_id': 'b1', 'cells': {'1': 2}}]}, 'Invalid tool string length.'),
                   ('propose_table_edit', {'tab_key': 'shots', 'row_edits': [{'row_id': 'b1'}]}, 'Unknown or missing tool arguments.'),
                   ('propose_table_edit', {'tab_key': 'shots', 'row_edits': {}}, 'Invalid tool selection.'),
                   ('spawn_agent', {'objective': 'Read', 'label_selector': {'domain': 1}}, 'Invalid tool string length.'),
                   ('spawn_agent', {'objective': 'Read', 'scope': ['rows']}, 'Unknown or missing tool arguments.'),
                   ('spawn_agent', {'objective': 'Read', 'wait': 'yes'}, 'Invalid tool option.'),
                   ('spawn_agent', {'objective': 'Read', 'strategy': 'swarm'}, 'Invalid tool option.'),
                   ('ask_decision_gate', {'question': 'Which?', 'options': ['A']}, 'Invalid tool selection.'),
                   ('ask_decision_gate', {'question': 'Which?', 'options': ['A', 'B', 'C', 'D', 'E', 'F']}, 'Invalid tool selection.'),
                   ('cancel_delegation', {'reason': 'stop'}, 'Unknown or missing tool arguments.')]
        for name, args, message in invalid:
            with self.subTest(name=name, args=args):
                self.rejects(name, args, message)

    def test_studio_messages_and_fail_fast_scope_are_unchanged(self):
        self.rejects('studio_dispatch_shot', {'episode_id': 'ep', 'shot_ids': ['a', 'a'], 'allocation_id': 'al'}, 'Duplicate Studio selection.')
        self.rejects('studio_dispatch_shot', {'episode_id': 'ep', 'shot_ids': [], 'allocation_id': 'al'}, 'Invalid Studio selection.')
        self.rejects('studio_manage_asset', {'episode_id': 'ep', 'operation': 'delete', 'name': 'n', 'prompt': 'p'}, 'Invalid Studio option.')
        self.rejects('studio_ingest_script', {'episode_id': '', 'script': 's'}, 'Invalid Studio string length.')
        self.rejects('consult_advisor', {}, 'Unknown or missing Studio tool arguments.')
        with self.assertRaises(ValueError):
            tool_specs.validate_studio_args('studio_plan_allocation', {'episode_id': True})
        tool_specs.validate_studio_args('read_page', {'bogus': True})  # Studio-only fail-fast; authorize_tool checks the rest
        with self.assertRaises(ValueError):
            tool_registry.validate_args('shell', {})


class McpExposureTests(unittest.TestCase):
    def test_mcp_server_lists_and_calls_only_exposed_tools(self):
        specs = [s for s in tool_specs.TOOLS if s['name'] in ('read_page', 'propose')]
        with patch.object(mcp_stdio, '_host_tools', return_value=specs), \
             patch.object(mcp_stdio, 'MCP_TOOLS', frozenset({'read_page'})), \
             patch.object(mcp_stdio, '_call_tool', return_value=('ok', False)) as call:
            self.assertEqual([s['name'] for s in mcp_stdio.handle({'method': 'tools/list'})['tools']], ['read_page'])
            with self.assertRaises(LookupError):
                mcp_stdio.handle({'method': 'tools/call', 'params': {'name': 'propose', 'arguments': {'action': '改狀態'}}})
            self.assertFalse(call.called)
            mcp_stdio.handle({'method': 'tools/call', 'params': {'name': 'read_page', 'arguments': {'key': 'shots'}}})
            call.assert_called_once()

    def test_tool_host_specs_drop_unexposed_and_unfrozen_tools(self):
        profile = audit.seeded_profile('sheet_ops')
        names = [s['name'] for s in tool_host.mcp_specs_for(profile)]
        self.assertEqual(names, [s['name'] for s in agent_policy.tool_specs_for(profile)])
        with patch.object(tool_registry, 'MCP', frozenset(names) - {'propose_table_edit'}):
            self.assertNotIn('propose_table_edit', [s['name'] for s in tool_host.mcp_specs_for(profile)])
        self.assertEqual([s['name'] for s in tool_host.mcp_specs_for(profile, {'read_page'})], ['read_page'])
        self.assertEqual(tool_host.mcp_specs_for({**profile, 'enabled': False}), [])
        self.assertEqual(tool_host.mcp_specs_for(None), [])

    def test_default_disabled_policy_hides_a_tool_until_enabled(self):
        profile = audit.seeded_profile('qa_critic')
        disabled = {**tool_specs.DEFAULT_POLICIES, 'studio_inspect_frames': 'disabled'}
        with patch.object(tool_specs, 'DEFAULT_POLICIES', disabled):
            self.assertNotIn('studio_inspect_frames', [s['name'] for s in agent_policy.tool_specs_for(profile)])
            enabled = {**profile, 'tool_policies': {'studio_inspect_frames': 'always_ask'}}
            self.assertIn('studio_inspect_frames', [s['name'] for s in agent_policy.tool_specs_for(enabled)])


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'set OPENBENCH_TEST_DB_URI')
class RegistryDatabaseTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from project_docs import repository as repo, service
        self.conn = psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI'])
        repo.ensure_schema(self.conn)
        self.slug = 'tool-registry-' + uuid.uuid4().hex[:12]
        self.actor = str(uuid.uuid4())
        self.me = service.Identity(self.actor, 'Registry test', 'admin')
        repo.upsert_member(self.conn, self.actor, 'Registry test', 'admin')
        repo.upsert_project(self.conn, self.slug, 'Registry test')
        agent_registry.ensure_default_agents(self.conn, self.slug)

    def tearDown(self):
        self.conn.rollback()
        self.conn.close()

    def test_seeded_agents_see_the_audited_surface(self):
        roles = audit.surface()['roles']
        for key in tool_registry.BUILTIN_ROLES:
            with self.subTest(key=key):
                profile = agent_registry.get_agent(self.conn, self.slug, key)
                self.assertEqual(profile['allowed_tools'], roles[key]['grants'])
                self.assertEqual([s['name'] for s in agent_policy.tool_specs_for(profile)], roles[key]['internal'])

    def test_authorize_tool_validates_every_tool_after_policy(self):
        ctx = types.SimpleNamespace(slug=self.slug, me=self.me, agent_key='sheet_ops')
        agent_policy.authorize_tool(ctx, self.conn, 'read_page', {'key': 'shots', 'limit': 5})
        for name, args, message in [('read_page', {'key': 'shots', 'limit': 50}, 'Invalid tool option.'),
                                    ('read_page', {'tab_key': 'shots'}, 'Unknown or missing tool arguments.'),
                                    ('ask_decision_gate', {'question': 'Which?', 'options': 'A or B'}, 'Invalid tool selection.')]:
            with self.subTest(name=name), self.assertRaises(tools.ToolError) as caught:
                agent_policy.authorize_tool(ctx, self.conn, name, args)
            self.assertEqual(str(caught.exception), message)
        # Policy still decides first: an ungranted tool is denied whatever its arguments.
        with self.assertRaises(tools.ToolError) as caught:
            agent_policy.authorize_tool(ctx, self.conn, 'propose', {'bogus': True})
        self.assertIn('POLICY_DENIED', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
