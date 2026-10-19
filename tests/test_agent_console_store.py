"""Real PostgreSQL resource boundaries; no provider/CLI sessions or network calls."""
import json
import os
import threading
import time
import unittest
import uuid
from unittest.mock import patch
from pathlib import Path

from project_assistant import agent_console_store as console, agent_registry as agents
from project_assistant import orchestration_store as db, store, limbs, orchestrator as cp
from project_assistant.skills_registry import BUILTIN_SKILLS
from project_docs import repository as repo, service


class ConsoleStoreTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.conn = psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI'], connect_timeout=3)
        repo.ensure_schema(self.conn)
        self.slug = 'console-' + uuid.uuid4().hex[:10]
        self.me = service.Identity(str(uuid.uuid4()), 'Console test', 'admin')
        repo.upsert_member(self.conn, self.me.actor_id, self.me.name, 'admin')
        repo.upsert_project(self.conn, self.slug, 'Console test')

    def tearDown(self):
        self.conn.rollback()
        self.conn.close()

    def member(self, role='member'):
        me = service.Identity(str(uuid.uuid4()), 'Other crew', role)
        repo.upsert_member(self.conn, me.actor_id, me.name, role)
        return me

    def save(self, kind, resource_key, **fields):
        return console.save_resource(self.conn, self.me, self.slug, kind,
                                     {console.RESOURCES[kind][1]: resource_key, 'version': 0, **fields})

    def assert_denied(self, status, fn, *args, **kwargs):
        with self.assertRaises(agents.AgentError) as caught:
            fn(*args, **kwargs)
        self.assertEqual(caught.exception.status, status)

    def test_seeds_idempotent_and_custom_values_preserved(self):
        skills = console.list_resources(self.conn, self.me, self.slug, 'skill')
        self.assertEqual({s['skill_key'] for s in skills}, {s[0] for s in BUILTIN_SKILLS})
        self.assertEqual(len(console.list_resources(self.conn, self.me, self.slug, 'environment')), 4)
        router = console.get_resource(self.conn,self.me,self.slug,'environment','env_comfy_router')
        self.assertFalse(router['enabled'])
        self.assertEqual(router['config']['vault_keys'],[])
        self.assertEqual(len(console.list_resources(self.conn, self.me, self.slug, 'memory_store')), 3)
        changed = console.save_resource(self.conn, self.me, self.slug, 'skill',
            {'skill_key': 'shotgen', 'version': 1, 'instructions_md': 'Custom directions'})
        agents.save_agent(self.conn, self.me, self.slug, {'agent_key': 'doc_writer', 'system_prompt': 'Custom',
            'role_kind': 'observer', 'provider_config': {'model': 'custom-model'}, 'allowed_tools': ['read_page']})
        console.save_resource(self.conn, self.me, self.slug, 'environment',
            {'env_key': 'env_local_4090', 'version': 1, 'display_name': 'Custom machine'})
        console.save_resource(self.conn, self.me, self.slug, 'memory_store',
            {'store_key': 'style_rules', 'version': 1, 'description': 'Custom style'})
        for _ in range(2):
            agents.ensure_default_agents(self.conn, self.slug)
        self.assertEqual(console.get_resource(self.conn, self.me, self.slug, 'skill', 'shotgen'), changed)
        profile = agents.get_agent(self.conn, self.slug, 'doc_writer')
        self.assertEqual((profile['system_prompt'], profile['provider_config'], profile['allowed_tools'], profile['role_kind']),
                         ('Custom', {'model': 'custom-model'}, ['read_page'], 'observer'))
        self.assertEqual(console.get_resource(self.conn, self.me, self.slug, 'environment', 'env_local_4090')['display_name'], 'Custom machine')
        self.assertEqual(console.get_resource(self.conn, self.me, self.slug, 'memory_store', 'style_rules')['description'], 'Custom style')

    def test_immutable_history_and_version_conflict(self):
        first = self.save('skill', 'custom', instructions_md='First')
        second = console.save_resource(self.conn, self.me, self.slug, 'skill',
            {'skill_key': 'custom', 'version': first['version'], 'instructions_md': 'Second'})
        self.assertEqual(second['version'], 2)
        self.assert_denied(409, console.save_resource, self.conn, self.me, self.slug, 'skill',
            {'skill_key': 'custom', 'version': 1, 'instructions_md': 'Stale'})
        revisions = console.history(self.conn, self.me, self.slug, 'skill', 'custom')
        self.assertEqual([r['snapshot']['instructions_md'] for r in revisions], ['Second', 'First'])
        import psycopg
        with self.assertRaises(psycopg.Error), self.conn.transaction():
            self.conn.execute("UPDATE projectops.agent_resource_revision SET snapshot='{}' WHERE project_slug=%s", (self.slug,))
        with self.assertRaises(psycopg.Error), self.conn.transaction():
            self.conn.execute('DELETE FROM projectops.agent_resource_revision WHERE project_slug=%s', (self.slug,))

    def test_project_cascade_cleans_append_only_rows_without_touching_other_project(self):
        console.append_usage(self.conn, self.slug, {'event_key': 'cascade', 'usage_kind': 'frame_prep'})
        other_slug = self.slug + '-other'
        repo.upsert_project(self.conn, other_slug, 'Other')
        console.append_usage(self.conn, other_slug, {'event_key': 'retained', 'usage_kind': 'llm_turn'})
        for table in ('agent_resource_revision', 'agent_usage_ledger'):
            self.assertGreater(db.one(self.conn, f'SELECT count(*) FROM projectops.{table} WHERE project_slug=%s', (self.slug,)), 0)
        self.conn.execute('DELETE FROM projectops.project WHERE slug=%s', (self.slug,))
        for table in ('agent_resource_revision', 'agent_usage_ledger'):
            self.assertEqual(db.one(self.conn, f'SELECT count(*) FROM projectops.{table} WHERE project_slug=%s', (self.slug,)), 0)
            self.assertGreater(db.one(self.conn, f'SELECT count(*) FROM projectops.{table} WHERE project_slug=%s', (other_slug,)), 0)

    def test_profiles_typed_versioned_and_legacy_partial_updates(self):
        old = agents.get_agent(self.conn, self.slug, 'sheet_ops')
        result = agents.save_agent(self.conn, self.me, self.slug, {'agent_key': 'sheet_ops', 'version': old['version'],
            'effort': 'high', 'skill_keys': ['shotgen'], 'tool_policies': {'studio_dispatch_shot': 'always_ask'},
            'memory_mounts': [{'store_key': 'style_rules', 'access': 'read_only'}],
            'multiagent_config': {'allow_subagents': False, 'allow_workflows': True, 'advisor_agent_key': 'qa_critic'},
            'outcome_grader': {'enabled': True, 'criteria': 'Cite evidence', 'grader_agent_key': 'qa_critic', 'max_revisions': 3}})
        self.assertEqual(result['version'], old['version']+1)
        self.assert_denied(409, agents.save_agent, self.conn, self.me, self.slug,
            {'agent_key': 'sheet_ops', 'version': old['version'], 'effort': 'low'})
        agents.save_agent(self.conn, self.me, self.slug, {'agent_key': 'sheet_ops', 'description': 'Legacy API'})
        latest = agents.get_agent(self.conn, self.slug, 'sheet_ops')
        self.assertEqual(latest['effort'], 'high')
        self.assertEqual(latest['provider_config'], old['provider_config'])
        self.assertEqual(len(console.history(self.conn, self.me, self.slug, 'profile', 'sheet_ops')), 3)
        cases = [dict(effort=True), dict(skill_keys='shotgen'), dict(skill_keys=['missing']),
            dict(tool_policies={'shell': 'auto'}), dict(tool_policies={'read_page': True}),
            dict(multiagent_config={'allow_subagents': 1, 'allow_workflows': False, 'advisor_agent_key': None}),
            dict(outcome_grader={'enabled': True, 'criteria': '', 'grader_agent_key': 'sheet_ops', 'max_revisions': 1}),
            dict(outcome_grader={'enabled': True, 'criteria': '', 'grader_agent_key': 'qa_critic', 'max_revisions': True}),
            dict(memory_mounts=[{'store_key': 'style_rules', 'access': 'admin'}]),
            dict(memory_mounts=[{'store_key': 'style_rules', 'access': 'read_only', 'principal': {}}]),
            dict(default_environment_key='missing')]
        for fields in cases:
            with self.subTest(fields=fields):
                self.assert_denied(400, agents.save_agent, self.conn, self.me, self.slug, {'agent_key': 'sheet_ops', **fields})

    def test_reserved_media_profiles_only_computed_and_db_runtime_unchanged(self):
        for name in ('studio:open', 'studio:prepare', 'studio:closed'):
            self.assert_denied(400, agents.save_agent, self.conn, self.me, self.slug, {'agent_key': name})
            self.assertIsNone(agents.get_agent(self.conn, self.slug, name))
        self.assert_denied(400, agents.save_agent, self.conn, self.me, self.slug, {'agent_key': 'custom', 'runtime_kind': 'server_media'})
        profiles = agents.console_profiles(self.conn, self.slug)
        media = [p for p in profiles if p['runtime_kind'] == 'server_media']
        self.assertEqual(len(media), 3)
        self.assertTrue(all(p['read_only'] for p in media))
        self.assertFalse(any('_PRINCIPAL' in json.dumps(p) or 'principal' in p for p in media))
        import psycopg
        for column, value in [('agent_key', 'studio:open'), ('runtime_kind', 'server_media')]:
            with self.assertRaises(psycopg.errors.CheckViolation), self.conn.transaction():
                self.conn.execute(f'UPDATE projectops.agent_profile SET {column}=%s WHERE project_slug=%s', (value, self.slug))

    def test_non_admin_viewer_revoked_and_forged_identity(self):
        member, viewer = self.member(), self.member('viewer')
        for me in (member, viewer):
            for kind, resource_key in [('skill', 'custom'), ('environment', 'custom'), ('vault', 'custom'), ('service_account', 'custom')]:
                self.assert_denied(403, console.save_resource, self.conn, me, self.slug, kind,
                    {console.RESOURCES[kind][1]: resource_key, 'version': 0})
            self.assert_denied(403, console.save_settings, self.conn, me, self.slug, {'version': 1})
            self.assert_denied(403, agents.save_agent, self.conn, me, self.slug, {'agent_key': 'custom'})
        fake = service.Identity(member.actor_id, member.name, 'admin')
        self.assert_denied(403, console.save_settings, self.conn, fake, self.slug, {'version': 1})
        for me in (viewer, member):
            self.assert_denied(403, console.save_memory_entry, self.conn, me, self.slug,
                {'store_key': 'style_rules', 'entry_key': 'rule', 'content_md': 'x', 'version': 0})
        self.assertEqual(console.memory_entries(self.conn, member, self.slug, 'style_rules'), [])
        store.set_member_enabled(self.conn, self.slug, member.actor_id, False, self.me.actor_id)
        self.assert_denied(403, console.list_resources, self.conn, member, self.slug, 'skill')

    def test_user_memory_private_even_from_admin_and_history(self):
        member, other = self.member(), self.member()
        private = console.save_resource(self.conn, member, self.slug, 'memory_store',
            {'store_key': 'private_notes', 'version': 0, 'scope_kind': 'user', 'scope_id': member.actor_id})
        entry = console.save_memory_entry(self.conn, member, self.slug,
            {'store_key': 'private_notes', 'entry_key': 'note', 'content_md': 'Private', 'version': 0})
        revised = console.save_memory_entry(self.conn, member, self.slug,
            {'store_key': 'private_notes', 'entry_key': 'note', 'content_md': 'Private revision', 'version': 1})
        self.assertEqual(revised['version'], 2)
        self.assertEqual([h['snapshot']['content_md'] for h in console.history(self.conn, member, self.slug, 'memory_entry', entry['id'])], ['Private revision', 'Private'])
        for me in (self.me, other):
            self.assertFalse(any(r['store_key'] == private['store_key'] for r in console.list_resources(self.conn, me, self.slug, 'memory_store')))
            self.assert_denied(404, console.memory_entries, self.conn, me, self.slug, 'private_notes')
            self.assert_denied(404, console.history, self.conn, me, self.slug, 'memory_entry', entry['id'])
            self.assert_denied(404, console.history, self.conn, me, self.slug, 'memory_store', 'private_notes')
        self.assert_denied(403, console.save_resource, self.conn, self.me, self.slug, 'memory_store',
            {'store_key': 'impersonated', 'version': 0, 'scope_kind': 'user', 'scope_id': member.actor_id})
        self.assert_denied(400, console.save_resource, self.conn, member, self.slug, 'memory_store',
            {'store_key': 'private_notes', 'version': 1, 'scope_kind': 'project', 'scope_id': ''})

    def episode_fixture(self, slug, identifier):
        # Real episode metadata and collaborative tab; no media blobs.
        repo.create_tab(self.conn, slug, key='script', title='Script', parent_key=None, doc={'type': 'doc', 'content': []}, actor_id=self.me.actor_id)
        from project_docs import story_openapi as story
        story.store(self.conn, identifier, 'episode', {'slug': slug, 'episodeId': identifier,
            'projectId': 'pj_'+slug, 'episodeIndex': 1, 'title': 'Episode', 'tabKey': 'script'}, slug=slug)

    def test_episode_and_project_isolation(self):
        other_slug = self.slug + '-other'
        repo.upsert_project(self.conn, other_slug, 'Other')
        self.episode_fixture(self.slug, 'ep_test_one')
        self.episode_fixture(other_slug, 'ep_test_other')
        console.save_resource(self.conn, self.me, self.slug, 'memory_store',
            {'store_key': 'episode_notes', 'version': 0, 'scope_kind': 'episode', 'scope_id': 'ep_test_one'}, episode_id='ep_test_one')
        console.save_memory_entry(self.conn, self.me, self.slug,
            {'store_key': 'episode_notes', 'entry_key': 'rule', 'version': 0}, episode_id='ep_test_one')
        self.assert_denied(404, console.memory_entries, self.conn, self.me, self.slug, 'episode_notes', episode_id='ep_test_other')
        self.assert_denied(400, console.save_resource, self.conn, self.me, self.slug, 'memory_store',
            {'store_key': 'bad_episode', 'version': 0, 'scope_kind': 'episode', 'scope_id': 'ep_test_other'}, episode_id='ep_test_other')
        self.assertIsNone(console.get_resource(self.conn, self.me, other_slug, 'memory_store', 'episode_notes'))
        self.save('skill', 'exclusive', instructions_md='Production A')
        self.assertIsNone(console.get_resource(self.conn, self.me, other_slug, 'skill', 'exclusive'))
        self.assertEqual(console.history(self.conn, self.me, other_slug, 'profile', 'absent'), [])

    def test_mount_readonly_and_current_profile_revocation(self):
        p = agents.save_agent(self.conn, self.me, self.slug, {'agent_key': 'sheet_ops',
            'memory_mounts': [{'store_key': 'style_rules', 'access': 'read_only'}]})
        self.assertEqual(console.memory_entries(self.conn, self.me, self.slug, 'style_rules', profile=p), [])
        body = {'store_key': 'style_rules', 'entry_key': 'rule', 'version': 0, 'content_md': 'Evidence'}
        self.assert_denied(403, console.save_memory_entry, self.conn, self.me, self.slug, body, profile=p)
        agents.save_agent(self.conn, self.me, self.slug, {'agent_key': 'sheet_ops',
            'memory_mounts': [{'store_key': 'style_rules', 'access': 'read_write'}]})
        result = console.save_memory_entry(self.conn, self.me, self.slug, body, profile=p)
        self.assertEqual(result['content_md'], 'Evidence')
        agents.save_agent(self.conn, self.me, self.slug, {'agent_key': 'sheet_ops', 'memory_mounts': []})
        self.assert_denied(403, console.memory_entries, self.conn, self.me, self.slug, 'style_rules', profile=p)

    def test_vault_references_and_environment_validation(self):
        with patch.dict(os.environ, {'OPENBENCH_AGENT_KEY_ENVS': 'TEST_PROVIDER_KEY'}):
            vault = self.save('vault', 'provider', provider_config={'kind': 'openai_compat', 'api_key_env': 'TEST_PROVIDER_KEY', 'base_url': 'https://example.invalid/v1'}, allowed_agent_keys=['sheet_ops'])
            self.assertEqual(vault['provider_config']['api_key_env'], 'TEST_PROVIDER_KEY')
            env = self.save('environment', 'restricted', network_access='allowlist', allowed_hosts=['example.invalid'],
                config={'vault_keys': ['provider'], 'timeout_seconds': 60, 'max_memory_mb': 1024, 'max_cpu_seconds': 60})
            self.assertEqual(env['config']['timeout_seconds'], 60)
            for cfg in ({'api_key': 'synthetic-secret'}, {'api_key_env': 'PATH'}, {'api_key_env': 'TEST_PROVIDER_KEY', 'base_url': 'http://['}, {'api_key_env': 'TEST_PROVIDER_KEY', 'base_url': 'https://example.invalid:bad'}, {'api_key_env': 'TEST_PROVIDER_KEY', 'base_url': 'https://x.invalid/?token=secret'}, {'headers': {'Authorization': 'secret'}}, {'api_key_env': 'TEST_PROVIDER_KEY', 'model': 'Bearer syntheticsecret'}, {'api_key_env': 'TEST_PROVIDER_KEY', 'effort': 'extreme'}):
                self.assert_denied(400, self.save, 'vault', 'bad', provider_config=cfg)
            for cfg in ({'command': ['codex']}, {'env': {'TOKEN': 'secret'}}, {'timeout_seconds': True}, {'max_memory_mb': float('inf')}, {'vault_keys': ['missing']}):
                self.assert_denied(400, self.save, 'environment', 'bad', config=cfg)
            for host in ('*.example.invalid', 'https://example.invalid', 'name@host'):
                self.assert_denied(400, self.save, 'environment', 'bad', allowed_hosts=[host])
        with patch.dict(os.environ, {'OPENBENCH_AGENT_KEY_ENVS': ''}):
            self.assert_denied(400, self.save, 'vault', 'revoked', provider_config=vault['provider_config'])

    def test_live_environment_and_vault_mount_controls(self):
        with patch.dict(os.environ, {'OPENBENCH_AGENT_KEY_ENVS': 'TEST_PROVIDER_KEY'}):
            self.save('vault', 'provider', provider_config={'api_key_env': 'TEST_PROVIDER_KEY', 'base_url': 'https://example.invalid/v1'}, allowed_agent_keys=['sheet_ops'])
            console.save_resource(self.conn, self.me, self.slug, 'environment',
                {'env_key': 'env_local_4090', 'version': 1, 'network_access': 'allowlist', 'allowed_hosts': ['example.invalid'], 'config': {'vault_keys': ['provider'], 'timeout_seconds': 60}})
            checked = console.execution_resources(self.conn, self.me, self.slug, 'sheet_ops', vault_key='provider')
            self.assertEqual(checked['environment']['config']['timeout_seconds'], 60)
            self.assertNotIn('api_key', checked['provider_config'])
            self.assert_denied(403, console.execution_resources, self.conn, self.me, self.slug, 'doc_writer', vault_key='provider')
            self.assert_denied(403, console.execution_resources, self.conn, self.me, self.slug, 'sheet_ops', destination='https://other.invalid', vault_key='provider')
            console.save_resource(self.conn, self.me, self.slug, 'vault', {'vault_key': 'provider', 'version': 1, 'enabled': False})
            self.assert_denied(403, console.execution_resources, self.conn, self.me, self.slug, 'sheet_ops', vault_key='provider')
            console.save_resource(self.conn, self.me, self.slug, 'environment', {'env_key': 'env_local_4090', 'version': 2, 'enabled': False})
            self.assert_denied(403, console.execution_resources, self.conn, self.me, self.slug, 'sheet_ops')
        console.save_resource(self.conn, self.me, self.slug, 'environment', {'env_key': 'env_local_4090', 'version': 3, 'enabled': True, 'network_access': 'offline'})
        self.assert_denied(403, console.execution_resources, self.conn, self.me, self.slug, 'sheet_ops', destination='http://127.0.0.1:8188')
        self.assert_denied(400, self.save, 'environment', 'bad_package', packages=['pip; arbitrary-command'])

    def test_settings_money_bounds_and_secret_rejection(self):
        old = console.get_settings(self.conn, self.me, self.slug)
        result = console.save_settings(self.conn, self.me, self.slug, {'version': old['version'], 'spend_limit_session_usd': '2.50', 'on_spend_limit': 'pause'})
        self.assertEqual(result['spend_limit_session_usd'], 2.5)
        self.assert_denied(409, console.save_settings, self.conn, self.me, self.slug, {'version': old['version']})
        for value in (True, -1, float('nan'), float('inf'), 'NaN', 'Infinity', 1000000, '0.001'):
            self.assert_denied(400, console.save_settings, self.conn, self.me, self.slug,
                {'version': result['version'], 'spend_limit_monthly_usd': value})
        for fields in ({'otel_config': {'enabled': True, 'endpoint': 'https://x.invalid?token=x', 'service_name': 'studio'}},
                       {'otel_config': {'enabled': True, 'endpoint': 'https://x.invalid', 'service_name': 'studio', 'headers': {'Authorization': 'secret'}}},
                       {'webhooks': ['missing']}, {'rate_limits': {'rpm_per_agent': 30, 'max_concurrent_renders': True, 'max_concurrent_llm': 4}},
                       {'privacy_mode': 'full'}, {'production_policy': 'hybrid_studio'}):
            self.assert_denied(400, console.save_settings, self.conn, self.me, self.slug, {'version': result['version'], **fields})
        self.assertEqual(len(console.history(self.conn, self.me, self.slug, 'settings', self.slug)), 2)

    def test_ledger_idempotency_immutable_identity_and_project_analytics(self):
        event = {'event_key': 'turn:1', 'usage_kind': 'llm_turn', 'input_tokens': 12, 'output_tokens': 3,
                 'cached_tokens': 6, 'cache_hit': True, 'estimated_cost_usd': '0.0125', 'meta': {'estimated': True}}
        first = console.append_usage(self.conn, self.slug, event)
        self.assertEqual(console.append_usage(self.conn, self.slug, event), first)
        self.assert_denied(409, console.append_usage, self.conn, self.slug, {**event, 'output_tokens': 4})
        for fields in ({'duration_ms': True}, {'cached_tokens': 13}, {'estimated_cost_usd': 'NaN'},
                       {'estimated_cost_usd': -1}, {'meta': {'error': 'Bearer synthetic'}},
                       {'input_tokens': 2147483648}, {'agent_key': None}, {'agent_key': 'studio:fake'}, {'run_id': str(uuid.uuid4())}):
            self.assert_denied(400, console.append_usage, self.conn, self.slug, {**event, **fields})
        import psycopg
        for sql in ('UPDATE projectops.agent_usage_ledger SET output_tokens=20 WHERE project_slug=%s',
                    'DELETE FROM projectops.agent_usage_ledger WHERE project_slug=%s'):
            with self.assertRaises(psycopg.Error), self.conn.transaction():
                self.conn.execute(sql, (self.slug,))
        row = console.analytics(self.conn, self.me, self.slug)[0]
        self.assertEqual((row['events'], row['input_tokens'], row['cached_tokens']), (1, 12, 6))
        self.assertNotIn('meta', row)
        other_slug = self.slug + '-other'
        repo.upsert_project(self.conn, other_slug, 'Other')
        self.assertEqual(console.analytics(self.conn, self.me, other_slug), [])
        run = cp.create_run(self.conn, self.me, self.slug, 'Test scope', client_request_id='ledger')
        self.assert_denied(400, console.append_usage, self.conn, other_slug, {**event, 'run_id': run['id']})
        owned = console.append_usage(self.conn, self.slug, {**event, 'event_key': 'run:1', 'run_id': run['id']})
        self.assertEqual(owned['owner_id'], self.me.actor_id)

    def test_service_account_is_existing_project_limb_reference(self):
        worker = limbs.register(self.conn, self.me, {'name': 'Fixture', 'capabilities': ['llm'], 'project_slug': self.slug})
        result = self.save('service_account', 'fixture', limb_id=worker['limb']['id'])
        self.assertNotIn('token', result)
        self.assertNotIn(worker['token'], json.dumps(console.history(self.conn, self.me, self.slug, 'service_account', 'fixture')))
        self.assert_denied(400, self.save, 'service_account', 'bad', limb_id=str(uuid.uuid4()))
        self.assert_denied(400, self.save, 'service_account', 'bad', limb_id=worker['limb']['id'], token='synthetic')
        other_slug = self.slug + '-other'
        repo.upsert_project(self.conn, other_slug, 'Other')
        self.assert_denied(400, console.save_resource, self.conn, self.me, other_slug, 'service_account',
            {'account_key': 'wrong', 'version': 0, 'limb_id': worker['limb']['id']})

    def test_migration_fresh_upgrade_repeat_preserves_spec07_rows(self):
        # The cluster is disposable; transactional DDL rolls back in tearDown.
        self.conn.execute('DROP SCHEMA projectops CASCADE')
        for name in repo.SCHEMA_FILES[:-1]:
            self.conn.execute((repo.SCHEMA_DIR/name).read_text(encoding='utf8'))
        self.conn.execute("INSERT INTO projectops.project(slug,title) VALUES(%s,'Prior production')", (self.slug,))
        self.conn.execute("""INSERT INTO projectops.agent_profile(project_slug,agent_key,display_name,system_prompt,provider_config,allowed_tools)
            VALUES(%s,'custom','Custom','Keep me','{"model":"persisted-custom"}','["read_page"]')""", (self.slug,))
        self.conn.execute("INSERT INTO projectops.story_record(id,kind,project_slug,data) VALUES('fixture-shot','shot',%s,%s::jsonb)", (self.slug, json.dumps({"selected": "reviewed"})))
        for agent_key, description in (('doc_writer', 'Custom description'), ('qa_critic', '')):
            _, name, icon, role, domain = next(row for row in agents.ROSTER if row[0] == agent_key)
            prompt = (Path(agents.__file__).parent/'prompts'/(agent_key+'.md')).read_text(encoding='utf8')
            self.conn.execute('''INSERT INTO projectops.agent_profile(project_slug,agent_key,display_name,icon,role_kind,
                system_prompt,description,capabilities,labels,allowed_tools) VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb)''',
                (self.slug, agent_key, name, icon, role, prompt, description, json.dumps(['llm']), json.dumps({'domain': domain}), json.dumps(agents.default_tools(agent_key, False))))
        old = agents.get_agent(self.conn, self.slug, 'custom')
        migration = (repo.SCHEMA_DIR/'163_agent_console.sql').read_text(encoding='utf8')
        for _ in range(2):
            self.conn.execute(migration)
        current = agents.get_agent(self.conn, self.slug, 'custom')
        self.assertEqual({n: current[n] for n in old}, old)
        self.assertEqual(current['version'], 1)
        self.assertEqual(db.one(self.conn, "SELECT data FROM projectops.story_record WHERE id='fixture-shot'"), {'selected': 'reviewed'})
        agents.ensure_default_agents(self.conn, self.slug)
        self.assertEqual(agents.get_agent(self.conn, self.slug, 'doc_writer')['allowed_tools'], agents.default_tools('doc_writer', False))
        self.assertEqual(agents.get_agent(self.conn, self.slug, 'qa_critic')['allowed_tools'], agents.default_tools('qa_critic'))
        self.assertEqual(agents.get_agent(self.conn, self.slug, 'qa_critic')['version'], 2)
        repo.upsert_member(self.conn, self.me.actor_id, self.me.name, 'admin')
        self.assertEqual(len(console.history(self.conn, self.me, self.slug, 'profile', 'custom')), 1)

    def test_actual_concurrent_edit_has_one_winner(self):
        import psycopg
        self.conn.commit()
        first = agents.get_agent(self.conn, self.slug, 'doc_writer')
        # Hold writer one open while writer two attempts the exact same version.
        agents.save_agent(self.conn, self.me, self.slug, {'agent_key': 'doc_writer', 'version': first['version'], 'description': 'Winner'})
        outcomes = []
        started = threading.Event()
        def competing():
            with psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI'], connect_timeout=3) as c:
                c.execute("SET statement_timeout='5s'")
                started.set()
                try:
                    agents.save_agent(c, self.me, self.slug, {'agent_key': 'doc_writer', 'version': first['version'], 'description': 'Stale'})
                    outcomes.append('unexpected success')
                except agents.AgentError as exc:
                    outcomes.append(exc.status)
                    c.rollback()
        thread = threading.Thread(target=competing)
        try:
            thread.start()
            self.assertTrue(started.wait(3))
            time.sleep(.1)
            self.assertTrue(thread.is_alive())
            self.conn.commit()
            thread.join(6)
            self.assertFalse(thread.is_alive())
            self.assertEqual(outcomes, [409])
            self.assertEqual(agents.get_agent(self.conn, self.slug, 'doc_writer')['description'], 'Winner')
        finally:
            self.conn.rollback()
            thread.join(6)
            self.conn.execute('DELETE FROM projectops.project WHERE slug=%s', (self.slug,))
            self.conn.execute('DELETE FROM projectops.member WHERE actor_id=%s', (self.me.actor_id,))
            self.conn.commit()

    def test_resource_bounds_reserved_fields_and_unknown_versions(self):
        for kind in console.RESOURCES:
            self.assert_denied(400, self.save, kind, 'studio:open')
        for fields in ({'instructions_md': 'x'*30001}, {'version': True}, {'version': -1},
                       {'built_in': True}, {'recommended_tools': ['shell']}, {'enabled': 1}, {'summary': None}):
            self.assert_denied(400, self.save, 'skill', 'bad', **fields)
        self.assert_denied(409, self.save, 'skill', 'bad', version=1)
        self.assert_denied(400, console.save_resource, self.conn, self.me, self.slug, 'skill', {'skill_key': 'missing_version'})
        self.assert_denied(400, console.save_memory_entry, self.conn, self.me, self.slug,
            {'store_key': 'style_rules', 'entry_key': 'rule', 'version': 0, 'content_md': 'x'*30001})
