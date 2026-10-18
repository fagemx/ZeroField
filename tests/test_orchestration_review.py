"""Adversarial regressions from the one independent M8 branch review."""
import copy
import json
import os
from pathlib import Path
import unittest

from orchestration_fixture import OrchestrationFixture
from project_assistant import orchestrator as cp, orchestration_store as db, tools, store, service, agent_registry, delegation_tools
from project_docs import repository as repo


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'),'set OPENBENCH_TEST_DB_URI')
class ReviewRegressions(OrchestrationFixture,unittest.TestCase):
    def context(self,claim):
        import psycopg
        return tools.ToolContext(lambda:psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI']),self.slug,self.me,Path('.'),None,
            agent_key=claim['agent_key'],dispatch_id=claim['id'],admission_no=claim['admission_no'],lease_token=claim['lease_token'],
            worker_id='review-worker',run_id=claim['run_id'],scope=cp.effective_scope(self.conn,claim))

    def prepare(self,claim,text):
        ctx=self.context(claim)
        ids=cp.prepare_dispatch_output(self.conn,ctx,{'text':text})
        cp.complete_dispatch(self.conn,'review-worker',claim['handle'],claim['lease_token'],outcome='succeeded',output={'text':text},proposal_ids=ids)
        return ids[0]

    def edit_input(self,row_id,text):
        tab=repo.get_tab(self.conn,self.slug,'shots');doc=copy.deepcopy(tab['doc'])
        row=next(row for row in doc['content'][0]['content'] if row['attrs']['bid']==row_id)
        row['content'][0]['content'][0]['content'][0]['text']=text
        repo.save_tab_doc(self.conn,self.slug,'shots',doc=doc,title=tab['title'],actor_id=self.actor,session_id='human',base_revision=tab['revision'])

    def test_accepting_fanout_a_does_not_bless_changed_source_of_b(self):
        run=self.run_record();task=self.task_record(run,strategy='fanout_rows',scope=self.sheet_scope(),
            target={'kind':'table','tab_key':'shots','table_id':'b_table','row_id':'b_shot1','col_index':1})
        for rid in ('b_shot1','b_shot2'):cp.spawn_dispatch(self.conn,self.slug,task['id'],agent_key='sheet_ops',slot_key='row:'+rid)
        proposals={}
        for _ in range(2):
            claim=cp.claim_dispatch(self.conn,'review-worker',['sheet_ops'],allowed_projects=[self.slug])
            proposals[claim['row_id']]=self.prepare(claim,'suggestion '+claim['row_id'])
        self.edit_input('b_shot2','Human revised the source')
        self.assertEqual(service.apply_proposal(self.conn,self.me,self.slug,proposals['b_shot1'],{})[0],200)
        code,result=service.apply_proposal(self.conn,self.me,self.slug,proposals['b_shot2'],{})
        self.assertEqual(code,409,result)
        self.assertEqual(store.proposal(self.conn,proposals['b_shot2'])['status'],'pending')

    def test_disabled_dependent_profile_does_not_stop_unrelated_scheduling(self):
        run=self.run_record();upstream=self.task_record(run,write_mode='analysis_only')
        blocked=self.task_record(run,depends_on=[upstream['id']],write_mode='analysis_only')
        healthy=self.task_record(run,agent_key='doc_writer',write_mode='analysis_only')
        agent_registry.save_agent(self.conn,self.me,self.slug,{'agent_key':'sheet_ops','enabled':False})
        db.execute(self.conn,"UPDATE projectops.orchestration_task SET status='completed' WHERE id=%s",(upstream['id'],))
        cp.refresh_run(self.conn,self.slug,run['id'])
        cp.schedule_ready(self.conn,self.slug)
        self.assertEqual(db.get_task(self.conn,self.slug,blocked['id'])['status'],'failed')
        claim=cp.claim_dispatch(self.conn,'review-worker',['doc_writer'],allowed_projects=[self.slug])
        self.assertEqual(claim['task_id'],healthy['id'])

    def test_sibling_reference_revision_does_not_absorb_a_human_edit(self):
        doc=copy.deepcopy(self.doc);doc['content'][0]['attrs']['bid']='b_other'
        for index,row in enumerate(doc['content'][0]['content']):row['attrs']['bid']='b_other'+str(index)
        repo.create_tab(self.conn,self.slug,key='other',title='Other',parent_key=None,doc=doc,actor_id=self.actor,surface_type='sheet')
        run=self.run_record();task=self.task_record(run)
        cp.spawn_dispatch(self.conn,self.slug,task['id'],agent_key='sheet_ops',slot_key='single')
        claim=cp.claim_dispatch(self.conn,'review-worker',['sheet_ops'],allowed_projects=[self.slug]);ctx=self.context(claim)
        for key,table,row in [('shots','b_table','b_shot1'),('other','b_other','b_other1')]:
            tools.propose_table_edit(ctx,self.conn,{'tab_key':key,'table_id':table,'row_edits':[{'row_id':row,'cells':{'1':'suggested'}}]})
        proposals={p['target']['tab_key']:p for p in store.proposals(self.conn,self.slug,owner_id=self.actor)}
        self.assertIn('shots',proposals['other']['target']['source_revisions'])
        cp.complete_dispatch(self.conn,'review-worker',claim['handle'],claim['lease_token'],outcome='succeeded',output={},proposal_ids=[p['id'] for p in proposals.values()])
        self.edit_input('b_shot2','Unrelated source edit')
        self.assertEqual(service.apply_proposal(self.conn,self.me,self.slug,proposals['shots']['id'],{})[0],200)
        self.assertEqual(service.apply_proposal(self.conn,self.me,self.slug,proposals['other']['id'],{})[0],409)

    def test_dependent_race_retains_candidates_before_ready(self):
        run=self.run_record();upstream=self.task_record(run,write_mode='analysis_only')
        ctx=tools.ToolContext(lambda:None,self.slug,self.me,Path('.'),None);ctx.run_id=run['id']
        result=json.loads(delegation_tools.spawn_agent(ctx,self.conn,{'objective':'Race after upstream','target_agent':'sheet_ops',
            'strategy':'race','race_agents':['sheet_ops','coordinator'],'depends_on':[upstream['id']],
            'scope':self.sheet_scope(),'target':{'kind':'table','tab_key':'shots','table_id':'b_table'}}))
        task=db.get_task(self.conn,self.slug,result['task_id'])
        self.assertEqual(task['race_agents'],['sheet_ops','coordinator'])
        self.assertEqual(db.dispatches(self.conn,self.slug,task['id']),[])
        db.execute(self.conn,"UPDATE projectops.orchestration_task SET status='completed' WHERE id=%s",(upstream['id'],))
        cp.refresh_run(self.conn,self.slug,run['id']);cp.schedule_ready(self.conn,self.slug)
        self.assertEqual(len(db.dispatches(self.conn,self.slug,task['id'])),2)

    def test_dependent_reads_accepted_upstream_values(self):
        run=self.run_record();scope=self.sheet_scope(rows=['b_shot1'])
        target={'kind':'table','tab_key':'shots','table_id':'b_table','row_id':'b_shot1','col_index':1}
        first=self.task_record(run,scope=scope,target=target)
        second=self.task_record(run,scope=scope,target=target,depends_on=[first['id']])
        cp.spawn_dispatch(self.conn,self.slug,first['id'],agent_key='sheet_ops',slot_key='single')
        claim=cp.claim_dispatch(self.conn,'review-worker',['sheet_ops'],allowed_projects=[self.slug])
        identifier=self.prepare(claim,'Accepted upstream value')
        self.assertEqual(service.apply_proposal(self.conn,self.me,self.slug,identifier,{})[0],200)
        cp.schedule_ready(self.conn,self.slug)
        downstream=cp.claim_dispatch(self.conn,'review-worker',['sheet_ops'],allowed_projects=[self.slug])
        self.assertEqual(downstream['task_id'],second['id'])
        self.assertIn('Accepted upstream value',tools.read_page(self.context(downstream),self.conn,{'key':'shots'}))
        identifier=self.prepare(downstream,'Reviewed downstream value')
        self.assertEqual(service.apply_proposal(self.conn,self.me,self.slug,identifier,{})[0],200)
        self.assertEqual(store.proposal(self.conn,identifier)['status'],'applied')

    def test_dependent_does_not_absorb_unrelated_human_edits(self):
        run=self.run_record();first=self.task_record(run,scope=self.sheet_scope(rows=['b_shot1']),
            target={'kind':'table','tab_key':'shots','table_id':'b_table','row_id':'b_shot1','col_index':1})
        second=self.task_record(run,scope=self.sheet_scope(rows=['b_shot2']),
            target={'kind':'table','tab_key':'shots','table_id':'b_table','row_id':'b_shot2','col_index':1},depends_on=[first['id']])
        cp.spawn_dispatch(self.conn,self.slug,first['id'],agent_key='sheet_ops',slot_key='single')
        claim=cp.claim_dispatch(self.conn,'review-worker',['sheet_ops'],allowed_projects=[self.slug]);identifier=self.prepare(claim,'Upstream')
        self.edit_input('b_shot2','Unrelated manual source edit')
        self.assertEqual(service.apply_proposal(self.conn,self.me,self.slug,identifier,{})[0],200)
        cp.schedule_ready(self.conn,self.slug)
        task=db.get_task(self.conn,self.slug,second['id'])
        self.assertEqual(task['status'],'failed')
        self.assertIn('來源',task['error'])

    def test_chat_gate_resume_reuses_the_original_completed_tool_journal(self):
        _,sent=service.send(self.conn,self.me,self.slug,{'text':'Create one child, ask, then continue','agent_key':'coordinator'})
        reply=sent['reply'];ctx=tools.ToolContext(lambda:None,self.slug,self.me,Path('.'),reply['id'])
        import psycopg
        ctx.connection_factory=lambda:psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI'])
        ctx.turn_context='Synthetic complete chat context'
        self.conn.commit()
        args={'objective':'Only one child','target_agent':'sheet_ops','write_mode':'analysis_only'}
        first=json.loads(tools.call(ctx,'spawn_agent',args))
        gate=json.loads(tools.call(ctx,'ask_decision_gate',{'question':'Choose','options':['A','B']}))
        cp.resolve_gate(self.conn,self.me,self.slug,gate['gate_id'],resolution='0',client_request_id='answer')
        claim=cp.claim_dispatch(self.conn,'review-worker',['coordinator'],allowed_projects=[self.slug]);self.conn.commit()
        self.assertEqual(claim['continuation'].get('chat_context'),'Synthetic complete chat context')
        second=json.loads(tools.call(self.context(claim),'spawn_agent',args))
        self.assertEqual(first['task_id'],second['task_id'])
