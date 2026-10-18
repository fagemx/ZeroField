import copy
import os
import unittest
from pathlib import Path

from orchestration_fixture import OrchestrationFixture
from project_assistant import flow_runner as flows,orchestration_flow as bridge,orchestrator as cp,orchestration_store as db,tools,service,store
from project_assistant import delegation_tools
from project_docs import repository as repo


def profile_graph():
    return {'nodes':[{'id':'fill','title':'Fill','capability':'llm','agent_key':'sheet_ops','scope':'rows',
        'row_source':{'tab_key':'shots','table_id':'b_table'},'input_tabs':['shots'],'prompt':'Fill output',
        'target':{'tab_key':'shots','col_index':1},'write_mode':'proposal'},
        {'id':'join','title':'Summary','capability':'llm','agent_key':'qa_critic','scope':'aggregate',
         'row_source':{'tab_key':'shots','table_id':'b_table'},'input_tabs':['shots'],'prompt':'Summarize','target':{},'write_mode':'proposal'}],
         'edges':[{'source':'fill','target':'join'}]}


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'),'set OPENBENCH_TEST_DB_URI')
class OrchestrationFlowTests(OrchestrationFixture,unittest.TestCase):
    def start_profile_flow(self,body=None):
        store.set_setting(self.conn,self.slug,'builtin_worker_seen_at',cp.now().isoformat())
        flows.save_definition(self.conn,self.me,self.slug,'flow',{'definition':profile_graph(),'revision':0})
        if body and body.get('execution_mode')=='single_step':
            body={**body,'definition_revision':flows.definition(self.conn,self.slug,'flow')['revision']}
            body={**body,'source_revisions':flows.preflight(self.conn,self.me,self.slug,'flow',body)['source_revisions']}
        return flows.start(self.conn,self.me,self.slug,'flow',body or {'row_ids':['b_shot1']})['run']

    def finish(self,claim,output):
        ctx=tools.ToolContext(lambda:None,self.slug,self.me,Path('.'),None,agent_key=claim['agent_key'],dispatch_id=claim['id'],
            admission_no=claim['admission_no'],lease_token=claim['lease_token'],worker_id=claim['lease_owner'])
        proposals=cp.prepare_dispatch_output(self.conn,ctx,output)
        cp.complete_dispatch(self.conn,claim['lease_owner'],claim['handle'],claim['lease_token'],outcome='succeeded',output=output,proposal_ids=proposals)
        return proposals

    def test_profile_node_claimed_once(self):
        run=self.start_profile_flow()
        bridge.sync_project(self.conn,self.slug)
        bridge.sync_project(self.conn,self.slug)
        self.assertIsNone(flows.claim(self.conn,self.worker)['task'])
        claim=cp.claim_dispatch(self.conn,'builtin',['sheet_ops'],allowed_projects=[self.slug])
        self.assertIsNotNone(claim)
        self.assertIsNone(cp.claim_dispatch(self.conn,'second',['sheet_ops'],allowed_projects=[self.slug]))
        task=db.get_task(self.conn,self.slug,claim['task_id'])
        self.assertIsNotNone(task['flow_task_id'])

    def test_builtin_profile_flow_starts_without_a_remote_limb(self):
        db.execute(self.conn,'UPDATE projectops.agent_limb SET last_seen_at=NULL WHERE id=%s',(self.worker['id'],))
        run=self.start_profile_flow({'row_ids':['b_shot1','b_shot2']})
        self.assertEqual(run['status'],'running')
        bridge.sync_project(self.conn,self.slug)
        self.assertIsNotNone(cp.claim_dispatch(self.conn,'builtin',['sheet_ops'],allowed_projects=[self.slug]))

    def test_fanout_selected_rows_only_and_join_after_review(self):
        run=self.start_profile_flow()
        bridge.sync_project(self.conn,self.slug)
        claim=cp.claim_dispatch(self.conn,'builtin',['sheet_ops'],allowed_projects=[self.slug])
        self.assertEqual(db.get_task(self.conn,self.slug,claim['task_id'])['request_scope']['row_ids'],['b_shot1'])
        proposals=self.finish(claim,{'text':'generated'})
        self.assertEqual(flows.detail(self.conn,self.slug,'flow',run['id'])['run']['status'],'awaiting_approval')
        self.assertIsNone(cp.claim_dispatch(self.conn,'join',['qa_critic'],allowed_projects=[self.slug]))
        self.assertEqual(service.apply_proposal(self.conn,self.me,self.slug,proposals[0],{})[0],200)
        bridge.sync_project(self.conn,self.slug)
        joined=cp.claim_dispatch(self.conn,'join',['qa_critic'],allowed_projects=[self.slug])
        self.assertIsNotNone(joined)
        self.finish(joined,{'text':'summary'})
        self.assertEqual(flows.detail(self.conn,self.slug,'flow',run['id'])['run']['status'],'succeeded')

    def test_profile_node_preserves_single_step_source_check(self):
        run=self.start_profile_flow({'execution_mode':'single_step','node_id':'fill','input_mode':'current_sources','sample_row_id':'b_shot1'})
        bridge.sync_project(self.conn,self.slug)
        claim=cp.claim_dispatch(self.conn,'builtin',['sheet_ops'],allowed_projects=[self.slug])
        tab=repo.get_tab(self.conn,self.slug,'shots')
        changed=copy.deepcopy(tab['doc'])
        changed['content'][0]['content'][1]['content'][0]['content'][0]['content'][0]['text']='changed source'
        repo.save_tab_doc(self.conn,self.slug,'shots',doc=changed,title=tab['title'],actor_id=self.actor,session_id='change',base_revision=tab['revision'])
        with self.assertRaises(cp.OrchestrationError):
            self.finish(claim,{'text':'late'})

    def test_profile_and_limb_binding_is_ambiguous(self):
        value=profile_graph()
        value['nodes'][0]['limb_id']=self.worker['id']
        with self.assertRaises(ValueError):
            flows.validate_definition(value)

    def test_flow_cancel_fences_dispatch_immediately(self):
        run=self.start_profile_flow()
        bridge.sync_project(self.conn,self.slug)
        claim=cp.claim_dispatch(self.conn,'builtin',['sheet_ops'],allowed_projects=[self.slug])
        flows.control(self.conn,self.me,self.slug,'flow',run['id'],'cancel')
        with self.assertRaises(cp.OrchestrationError):
            self.finish(claim,{'text':'late'})

    def test_profile_cannot_write_outside_configured_target_column(self):
        self.start_profile_flow()
        bridge.sync_project(self.conn,self.slug)
        claim=cp.claim_dispatch(self.conn,'builtin',['sheet_ops'],allowed_projects=[self.slug])
        ctx=tools.ToolContext(lambda:None,self.slug,self.me,Path('.'),None,agent_key='sheet_ops',dispatch_id=claim['id'],
            admission_no=claim['admission_no'],lease_token=claim['lease_token'],worker_id=claim['lease_owner'])
        with self.assertRaises(tools.ToolError):
            tools.propose_table_edit(ctx,self.conn,{'tab_key':'shots','row_edits':[{'row_id':'b_shot1','cells':{'0':'escaped'}}]})

    def test_legacy_branch_is_claimable_before_profile_bridge_poll(self):
        store.set_setting(self.conn,self.slug,'builtin_worker_seen_at',cp.now().isoformat())
        value=profile_graph()
        value['nodes'].append({'id':'legacy','capability':'llm','scope':'once','prompt':'Legacy','target':{},'write_mode':'proposal'})
        flows.save_definition(self.conn,self.me,self.slug,'flow',{'definition':value,'revision':0})
        flows.start(self.conn,self.me,self.slug,'flow',{'row_ids':['b_shot1']})
        claimed=flows.claim(self.conn,self.worker)['task']
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed['node_id'],'legacy')

    def test_profile_rejects_changed_input_in_same_row_before_review(self):
        self.start_profile_flow()
        bridge.sync_project(self.conn,self.slug)
        claim=cp.claim_dispatch(self.conn,'builtin',['sheet_ops'],allowed_projects=[self.slug])
        proposals=self.finish(claim,{'text':'generated'})
        tab=repo.get_tab(self.conn,self.slug,'shots')
        changed=copy.deepcopy(tab['doc'])
        changed['content'][0]['content'][1]['content'][0]['content'][0]['content'][0]['text']='changed prompt'
        repo.save_tab_doc(self.conn,self.slug,'shots',doc=changed,title=tab['title'],actor_id=self.actor,session_id='source-change',base_revision=tab['revision'])
        self.assertEqual(service.apply_proposal(self.conn,self.me,self.slug,proposals[0],{})[0],409)

    def test_flow_retry_gets_new_run_and_admission(self):
        run=self.start_profile_flow()
        bridge.sync_project(self.conn,self.slug)
        first=cp.claim_dispatch(self.conn,'builtin',['sheet_ops'],allowed_projects=[self.slug])
        flows.control(self.conn,self.me,self.slug,'flow',run['id'],'cancel')
        flows.control(self.conn,self.me,self.slug,'flow',run['id'],'retry')
        bridge.sync_project(self.conn,self.slug)
        second=cp.claim_dispatch(self.conn,'builtin',['sheet_ops'],allowed_projects=[self.slug])
        self.assertIsNotNone(second)
        self.assertNotEqual(first['run_id'],second['run_id'])
        self.assertGreater(second['admission_no'],first['admission_no'])

    def test_trigger_direct_flow_requires_gate_before_start(self):
        import json
        definition={'nodes':[{'id':'direct','title':'Write','capability':'llm','scope':'once','input_tabs':['shots'],
            'prompt':'Write','write_mode':'direct','target':{'tab_key':'shots','row_id':'b_shot1','col_index':1}}],'edges':[]}
        flows.save_definition(self.conn,self.me,self.slug,'flow',{'definition':definition,'revision':0})
        run=self.run_record()
        ctx=tools.ToolContext(lambda:None,self.slug,self.me,Path('.'),None,agent_key='coordinator',run_id=run['id'])
        result=json.loads(delegation_tools.trigger_flow_run(ctx,self.conn,{'flow_tab_key':'flow'}))
        self.assertTrue(result['awaiting_gate'])
        self.assertEqual(db.one(self.conn,'SELECT count(*) FROM projectops.flow_run WHERE project_slug=%s',(self.slug,)),0)
        cp.resolve_gate(self.conn,self.me,self.slug,result['gate_id'],resolution='0',client_request_id='approve-flow')
        self.assertEqual(db.one(self.conn,'SELECT count(*) FROM projectops.flow_run WHERE project_slug=%s',(self.slug,)),1)
        cp.resolve_gate(self.conn,self.me,self.slug,result['gate_id'],resolution='0',client_request_id='approve-flow')
        self.assertEqual(db.one(self.conn,'SELECT count(*) FROM projectops.flow_run WHERE project_slug=%s',(self.slug,)),1)
