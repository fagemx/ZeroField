"""Every transport uses the same profile policy and persona-scoped queue."""
import io
import json
import os
import unittest
from unittest.mock import patch

from test_agent_registry import AgentRegistryTests
from project_assistant import agent_registry, agent_policy, agent_runtime, service, store, tools, providers, model_client, mcp_stdio


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'set OPENBENCH_TEST_DB_URI')
class AgentRuntimeTests(unittest.TestCase):
    setUp = AgentRegistryTests.setUp
    tearDown = AgentRegistryTests.tearDown

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
        self.assertEqual(snapshot['display_name'],'企劃與劇本代理')

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

    def test_responses_request_uses_filtered_tools(self):
        allowed = [s for s in providers.tool_specs.TOOLS if s['name']=='read_page']
        body = model_client.request_body(model='fixture',effort='low',instructions='',items=[],cache_key='test',tool_specs=allowed)
        self.assertEqual([s['name'] for s in body['tools']],['read_page'])

    def test_mcp_list_and_call_share_authoritative_host_policy(self):
        allowed = [s for s in providers.tool_specs.TOOLS if s['name']=='read_page']
        with patch.object(mcp_stdio,'_host_tools',return_value=allowed):
            self.assertEqual([s['name'] for s in mcp_stdio.handle({'method':'tools/list'})['tools']],['read_page'])
            with self.assertRaises(LookupError):
                mcp_stdio.handle({'method':'tools/call','params':{'name':'propose','arguments':{}}})
