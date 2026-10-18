"""Project agent routing and policy isolation, backed by real PostgreSQL."""
import os
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from project_docs import repository as repo, service
from project_assistant import agent_registry, agent_policy, tools


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'set OPENBENCH_TEST_DB_URI')
class AgentRegistryTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.conn = psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI'])
        repo.ensure_schema(self.conn)
        self.slug = 'agent-test-' + uuid.uuid4().hex[:12]
        self.actor = str(uuid.uuid4())
        self.me = service.Identity(self.actor, 'Agent test', 'admin')
        repo.upsert_member(self.conn, self.actor, 'Agent test', 'admin')
        repo.upsert_project(self.conn, self.slug, 'Agent test')
        agent_registry.ensure_default_agents(self.conn, self.slug)

    def tearDown(self):
        self.conn.rollback()
        self.conn.close()

    def test_defaults_are_idempotent(self):
        agent_registry.ensure_default_agents(self.conn, self.slug)
        profiles = agent_registry.list_agents(self.conn, self.slug)
        self.assertEqual({p['agent_key'] for p in profiles},
                         {'coordinator', 'doc_writer', 'sheet_ops', 'qa_critic'})
        changed = agent_registry.save_agent(self.conn, self.me, self.slug,
                                           {'agent_key': 'doc_writer', 'system_prompt': 'Custom prompt', 'enabled': False})
        self.assertFalse(changed['enabled'])
        agent_registry.ensure_default_agents(self.conn, self.slug)
        self.assertEqual(agent_registry.get_agent(self.conn, self.slug, 'doc_writer')['system_prompt'], 'Custom prompt')

    def test_profile_validation(self):
        for value in (0, 33, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                agent_registry.save_agent(self.conn, self.me, self.slug, {'agent_key': 'custom', 'max_concurrency': value})
        with self.assertRaises(ValueError):
            agent_registry.save_agent(self.conn, self.me, self.slug, {'agent_key': 'custom', 'allowed_tools': ['shell']})
        member = service.Identity(self.actor, 'Member', 'member')
        with self.assertRaises(agent_registry.AgentError) as denied:
            agent_registry.save_agent(self.conn, member, self.slug, {'agent_key': 'custom'})
        self.assertEqual(denied.exception.status, 403)
        with self.assertRaises(ValueError):
            agent_registry.save_agent(self.conn, self.me, self.slug,
                                      {'agent_key': 'custom', 'provider_config': {'api_key': 'must-not-store'}})
        with patch.dict(os.environ, {'OPENBENCH_AGENT_KEY_ENVS': 'TEST_AGENT_KEY'}):
            with self.assertRaises(ValueError):
                agent_registry.save_agent(self.conn, self.me, self.slug,
                                          {'agent_key': 'custom', 'provider_config': {'api_key_env': 'PATH'}})

    def test_mentions_route_only_explicit_agent_tokens(self):
        for text, expected in [('hello', 'coordinator'), ('@doc_writer 請整理', 'doc_writer'),
                               ('@Cinematographer 請核對', 'sheet_ops'), ('mail@example.com', 'coordinator'),
                               ('`@doc_writer`', 'coordinator'), ('> @doc_writer\nhello', 'coordinator'),
                               ('@{' + self.actor + '}', 'coordinator')]:
            with self.subTest(text=text):
                self.assertEqual(agent_registry.resolve_mention(self.conn, self.slug, text), expected)
        for text in ('@missing 請整理', '@doc_writer @sheet_ops 請整理'):
            with self.assertRaises(ValueError):
                agent_registry.resolve_mention(self.conn, self.slug, text)
        with self.assertRaises(ValueError):
            agent_registry.resolve_mention(self.conn, self.slug, '@doc_writer 工作', 'sheet_ops')

    def test_qa_cannot_change_status(self):
        ctx = SimpleNamespace(slug=self.slug, me=self.me, agent_key='qa_critic')
        with self.assertRaises(tools.ToolError):
            agent_policy.authorize_tool(ctx, self.conn, 'propose', {'action': '改狀態'})
        agent_policy.authorize_tool(ctx, self.conn, 'propose', {'action': '在段落加標註'})
        with self.assertRaises(tools.ToolError):
            agent_policy.authorize_tool(ctx, self.conn, 'propose_table_edit', {})
        profile = agent_registry.get_agent(self.conn, self.slug, 'qa_critic')
        self.assertNotIn('propose_table_edit', {s['name'] for s in agent_policy.tool_specs_for(profile)})

    def test_observer_and_disabled_agents_cannot_execute(self):
        agent_registry.save_agent(self.conn, self.me, self.slug,
                                  {'agent_key': 'watch', 'role_kind': 'observer', 'allowed_tools': []})
        with self.assertRaises(ValueError):
            agent_registry.resolve_mention(self.conn, self.slug, '@watch inspect')
        agent_registry.save_agent(self.conn, self.me, self.slug, {'agent_key': 'sheet_ops', 'enabled': False})
        with self.assertRaises(ValueError):
            agent_registry.resolve_mention(self.conn, self.slug, '@sheet_ops inspect')
