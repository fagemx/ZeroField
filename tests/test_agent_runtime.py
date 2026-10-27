"""Every transport uses the same profile policy and persona-scoped queue."""
import io
import json
import os
import threading
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

import test_agent_registry as registry_fixture
from project_assistant import agent_registry, agent_policy, agent_runtime, service, store, tools, providers, mcp_stdio
from project_assistant import prompting


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'set OPENBENCH_TEST_DB_URI')
class AgentRuntimeTests(unittest.TestCase):
    setUp = registry_fixture.AgentRegistryTests.setUp
    def tearDown(self):
        self.conn.rollback()
        if getattr(self,'committed',False):
            with self.conn.cursor() as cur:
                for table in ('assistant_attachment','assistant_proposal','assistant_message','assistant_conversation','agent_profile'):
                    cur.execute('DELETE FROM projectops.'+table+' WHERE project_slug=%s',(self.slug,))
                cur.execute('DELETE FROM projectops.project WHERE slug=%s',(self.slug,))
                cur.execute('DELETE FROM projectops.member WHERE actor_id=%s',(self.actor,))
            self.conn.commit()
        self.conn.close()

    def test_concurrent_same_role_has_one_reply(self):
        import psycopg
        self.conn.commit()
        self.committed=True
        barrier=threading.Barrier(2)
        def send():
            with psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI']) as connection:
                barrier.wait(timeout=5)
                return service.send(connection,self.me,self.slug,{'text':'只執行一次','agent_key':'doc_writer'})[0]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:send(),range(2)))
        self.assertEqual(sorted(results),[200,409])
        self.assertEqual(len(store.thread(self.conn,self.slug,self.actor)),2)

    def test_two_roles_can_queue_same_owner(self):
        for key in ('doc_writer','sheet_ops'):
            status, result = service.send(self.conn,self.me,self.slug,{'text':'請核對來源','agent_key':key})
            self.assertEqual(status,200,result)
            self.assertEqual(result['reply']['agent_key'],key)
        self.assertEqual(service.send(self.conn,self.me,self.slug,{'text':'再寫一段','agent_key':'doc_writer'})[0],409)
        self.assertEqual(service.new_conversation(self.conn,self.me,self.slug)[0],409)
        self.assertIsNone(store.open_reply(self.conn,self.slug,self.actor,'qa_critic'))

    def test_unknown_or_conflicting_mention_does_not_enqueue(self):
        for payload in ({'text':'@missing 工作'}, {'text':'@doc_writer 工作','agent_key':'sheet_ops'}):
            self.assertEqual(service.send(self.conn,self.me,self.slug,payload)[0],400)
        self.assertEqual(store.thread(self.conn,self.slug,self.actor),[])

    def test_profile_snapshot_preserves_executed_persona(self):
        status, sent = service.send(self.conn,self.me,self.slug,{'text':'寫作','agent_key':'doc_writer'})
        self.assertEqual(status,200)
        snapshot = sent['reply']['agent_snapshot']
        agent_registry.save_agent(self.conn,self.me,self.slug,{'agent_key':'doc_writer','display_name':'Renamed'})
        self.assertEqual(store.message(self.conn,sent['reply']['id'])['agent_snapshot'],snapshot)
        self.assertEqual(snapshot['display_name'],'Screenwriter')

    def test_profile_credentials_are_resolved_only_in_runtime(self):
        with patch.dict(os.environ,{'OPENBENCH_AGENT_KEY_ENVS':'TEST_AGENT_KEY','TEST_AGENT_KEY':'private-fixture-key'}):
            profile = agent_registry.save_agent(self.conn,self.me,self.slug,{'agent_key':'doc_writer',
                'provider_config':{'kind':'openai_compat','base_url':'http://127.0.0.1:9/v1','model':'writer-model','api_key_env':'TEST_AGENT_KEY'}})
            config = agent_runtime.provider_for(profile)
            self.assertEqual((config.model,config.api_key),('writer-model','private-fixture-key'))
            self.assertNotIn('private-fixture-key',json.dumps(profile))

    def test_disabled_profile_is_rechecked_at_tool_call(self):
        ctx = type('Ctx',(),{'slug':self.slug,'me':self.me,'agent_key':'doc_writer'})()
        agent_registry.save_agent(self.conn,self.me,self.slug,{'agent_key':'doc_writer','enabled':False})
        with self.assertRaises(tools.ToolError):
            agent_policy.authorize_tool(ctx,self.conn,'read_page',{'key':'overview'})


class TransportPolicyTests(unittest.TestCase):
    def test_legacy_codex_engine_keeps_the_cli_transport(self):
        from project_assistant.worker import settings_from_env
        profile={'agent_key':'coordinator','role_kind':'primary','allowed_tools':[],'provider_config':{}}
        ctx=type('Ctx',(),{'slug':'fixture','me':type('Me',(),{'actor_id':'actor'})()})()
        with patch.dict(os.environ,{'PROJECT_ASSISTANT_ENGINE':'codex','OPENBENCH_PROVIDER':'','OPENBENCH_ENGINE':''}), \
             patch.object(agent_runtime,'run_cli',return_value=agent_runtime.Outcome('ok')) as cli, \
             patch.object(providers,'run_openai_compat_turn',side_effect=AssertionError('legacy codex must not invoke the HTTP transport')):
            agent_runtime.run_agent(profile=profile,ctx=ctx,instructions='',turn_text='fixture',timeout=1,settings=settings_from_env())
        cli.assert_called_once()

    def test_cli_committed_question_returns_awaiting_gate(self):
        from types import SimpleNamespace
        from project_assistant import codex_runner
        from project_assistant.tool_host import ToolHost
        from project_assistant.worker import settings_from_env
        host=ToolHost(list_tools=lambda:[])
        def waiting(*args,**kwargs):
            self.assertIs(kwargs['cancel_event'],host.pending)
            host.pending.set()
            return codex_runner.CodexResult(status='error')
        with patch.object(codex_runner,'run',side_effect=waiting):
            result=agent_runtime.run_cli(settings_from_env(),host,'question fixture')
        host.stop()
        self.assertEqual(result.status,'awaiting_gate')

    def test_custom_profile_prompt_and_knowledge_do_not_inherit_unrelated_business_context(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            (folder/'system.md').write_text('unrelated-default-role',encoding='utf-8')
            (folder/'knowledge.md').write_text('unrelated-business-knowledge',encoding='utf-8')
            (folder/'runtime.md').write_text('shared-canvas-safety',encoding='utf-8')
            with patch.object(prompting,'PROMPTS',folder):
                system,knowledge=prompting.load_agent({'system_prompt':'custom-writer','knowledge_pack':'writer-knowledge'})
            self.assertIn('shared-canvas-safety',system)
            self.assertIn('custom-writer',system)
            self.assertNotIn('unrelated-default-role',system)
            self.assertEqual(knowledge,'writer-knowledge')

    def test_chat_transport_exposes_and_accepts_only_selected_tools(self):
        captured = []
        def opener(request,**kwargs):
            captured.append(json.loads(request.data))
            return io.BytesIO(json.dumps({'choices':[{'message':{'content':'','tool_calls':[
                {'id':'bad','function':{'name':'propose_table_edit','arguments':'{}'}}]}}]}).encode())
        allowed = [s for s in providers.tool_specs.TOOLS if s['name']=='read_page']
        result = providers.run_openai_compat_turn(config=providers.ProviderConfig('openai_compat','http://127.0.0.1/v1','','fixture'),
            instructions='test',turn_text='read',call_tool=lambda *_: self.fail('forbidden tool reached handler'),
            timeout=5,opener=opener,tool_specs=allowed)
        self.assertEqual(result.status,'lockdown')
        self.assertEqual([s['function']['name'] for s in captured[0]['tools']],['read_page'])

    def test_removed_responses_kind_is_a_configuration_error_without_network(self):
        ctx=type('Ctx',(),{'slug':'fixture','me':type('Me',(),{'actor_id':'actor'})()})()
        for env,kind in (({},'responses'),({'OPENBENCH_PROVIDER':'direct'},None)):
            profile={'agent_key':'coordinator','role_kind':'primary','allowed_tools':[],'provider_config':{'kind':kind} if kind else {}}
            with self.subTest(kind=kind or env),patch.dict(os.environ,env), \
                 patch.object(providers,'run_openai_compat_turn',side_effect=AssertionError('removed kinds must not reach a transport')), \
                 patch('urllib.request.urlopen',side_effect=AssertionError('no network')):
                outcome=agent_runtime.run_agent(profile=profile,ctx=ctx,instructions='',turn_text='fixture',timeout=1)
            self.assertEqual((outcome.status,outcome.kind),('error','kind_removed'))
            self.assertIn('removed',outcome.detail)

    def test_mcp_list_and_call_share_authoritative_host_policy(self):
        allowed = [s for s in providers.tool_specs.TOOLS if s['name']=='read_page']
        with patch.object(mcp_stdio,'_host_tools',return_value=allowed):
            self.assertEqual([s['name'] for s in mcp_stdio.handle({'method':'tools/list'})['tools']],['read_page'])
            with self.assertRaises(LookupError):
                mcp_stdio.handle({'method':'tools/call','params':{'name':'propose','arguments':{}}})
