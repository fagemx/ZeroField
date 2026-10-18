import copy
import os
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from orchestration_fixture import OrchestrationFixture
from project_assistant import orchestrator as cp,orchestration_store as db,tools,store,service,agent_registry
from project_docs import repository as repo
from project_docs.doc_schema import node_text


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'),'set OPENBENCH_TEST_DB_URI')
class RaceTests(OrchestrationFixture,unittest.TestCase):
    def context(self,claim):
        return tools.ToolContext(lambda:None,self.slug,self.me,Path('.'),None,agent_key=claim['agent_key'],dispatch_id=claim['id'],
            admission_no=claim['admission_no'],lease_token=claim['lease_token'],worker_id=claim['lease_owner'])

    def race(self,finish=True):
        run=self.run_record()
        task=self.task_record(run,strategy='race',scope=self.sheet_scope(['b_shot1']),
                              target={'tab_key':'shots','kind':'table','row_id':'b_shot1','col_index':1})
        join=self.task_record(run,depends_on=[task['id']],write_mode='analysis_only')
        admitted=cp.start_race(self.conn,self.me,self.slug,task['id'],['coordinator','sheet_ops'])
        proposals=[]
        if finish:
            for key in ('coordinator','sheet_ops'):
                claim=cp.claim_dispatch(self.conn,key,[key],allowed_projects=[self.slug])
                ids=cp.prepare_dispatch_output(self.conn,self.context(claim),{'text':key+' version'})
                cp.complete_dispatch(self.conn,key,claim['handle'],claim['lease_token'],outcome='succeeded',output={'text':key+' version'},proposal_ids=ids)
                proposals+=ids
        return run,task,join,admitted,proposals

    def gate(self,task):
        return db.one(self.conn,"SELECT to_jsonb(g) FROM projectops.orchestration_gate g WHERE task_id=%s AND gate_kind='race_select' AND status='open'",(task['id'],))

    def test_two_active_race_admissions_are_both_valid(self):
        run,task,join,admitted,proposals=self.race()
        self.assertEqual(len(proposals),2)
        self.assertNotEqual(admitted[0]['admission_no'],admitted[1]['admission_no'])
        self.assertEqual(set(self.gate(task)['options']),set(proposals))
        self.assertEqual(db.get_task(self.conn,self.slug,join['id'])['status'],'pending')

    def test_regular_apply_cannot_bypass_race_selection(self):
        run,task,join,admitted,proposals=self.race()
        self.assertEqual(service.apply_proposal(self.conn,self.me,self.slug,proposals[0],{})[0],409)
        self.assertEqual(service.apply_proposal(self.conn,self.me,self.slug,proposals[0],{'_race_task_id':task['id']})[0],409)
        self.assertEqual(service.dismiss_proposal(self.conn,self.me,self.slug,proposals[0])[0],409)
        self.assertTrue(all(store.proposal(self.conn,p)['status']=='pending' for p in proposals))

    def test_select_winner_applies_once_dismisses_loser_and_unblocks_join(self):
        run,task,join,admitted,proposals=self.race()
        gate=self.gate(task)
        result=cp.select_race_winner(self.conn,self.me,self.slug,gate['id'],proposals[0],client_request_id='choose')
        again=cp.select_race_winner(self.conn,self.me,self.slug,gate['id'],proposals[0],client_request_id='choose')
        self.assertEqual(result['winning_dispatch_id'],again['winning_dispatch_id'])
        self.assertEqual(store.proposal(self.conn,proposals[0])['status'],'applied')
        self.assertEqual(store.proposal(self.conn,proposals[1])['status'],'dismissed')
        self.assertEqual(db.get_task(self.conn,self.slug,task['id'])['status'],'completed')
        self.assertEqual(db.get_task(self.conn,self.slug,join['id'])['status'],'ready')

    def test_concurrent_winners_apply_once(self):
        import psycopg
        run,task,join,admitted,proposals=self.race()
        gate=self.gate(task)
        self.conn.commit()
        barrier=threading.Barrier(2)
        def choose(index):
            with psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI']) as connection:
                barrier.wait(timeout=5)
                try:
                    cp.select_race_winner(connection,self.me,self.slug,gate['id'],proposals[index],client_request_id='choose-'+str(index))
                    return 200
                except cp.OrchestrationError as exc:
                    return exc.status
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses=list(pool.map(choose,range(2)))
        self.assertEqual(sorted(statuses),[200,409])
        self.assertEqual(sorted(store.proposal(self.conn,p)['status'] for p in proposals),['applied','dismissed'])

    def test_changed_snapshot_rolls_back_winner_and_loser_dismissals(self):
        run,task,join,admitted,proposals=self.race()
        gate=self.gate(task)
        tab=repo.get_tab(self.conn,self.slug,'shots'); changed=copy.deepcopy(tab['doc'])
        changed['content'][0]['content'][1]['content'][1]['content'][0]['content'][0]['text']='new live edit'
        repo.save_tab_doc(self.conn,self.slug,'shots',doc=changed,title=tab['title'],actor_id=self.actor,session_id='changed',base_revision=tab['revision'])
        with self.assertRaises(cp.OrchestrationError) as raised:
            cp.select_race_winner(self.conn,self.me,self.slug,gate['id'],proposals[0],client_request_id='stale')
        self.assertEqual(raised.exception.status,409)
        self.assertTrue(all(store.proposal(self.conn,p)['status']=='pending' for p in proposals))
        self.assertIsNone(db.get_task(self.conn,self.slug,task['id'])['winning_dispatch_id'])
        self.assertEqual(self.gate(task)['status'],'open')

    def test_retry_only_supersedes_same_agent_slot(self):
        run,task,join,admitted,proposals=self.race(finish=False)
        first=cp.claim_dispatch(self.conn,'coordinator',['coordinator'],allowed_projects=[self.slug])
        cp.cancel_dispatch(self.conn,self.me,self.slug,first['handle'],'retry one candidate')
        retry=cp.spawn_dispatch(self.conn,self.slug,task['id'],agent_key='coordinator',slot_key='agent:coordinator')
        other=cp.claim_dispatch(self.conn,'sheet_ops',['sheet_ops'],allowed_projects=[self.slug])
        ids=cp.prepare_dispatch_output(self.conn,self.context(other),{'text':'still valid'})
        self.assertEqual(cp.complete_dispatch(self.conn,'sheet_ops',other['handle'],other['lease_token'],outcome='succeeded',output={'text':'still valid'},proposal_ids=ids)['status'],'awaiting_gate')
        self.assertGreater(retry['admission_no'],other['admission_no'])
        with self.assertRaises(cp.OrchestrationError):
            cp.complete_dispatch(self.conn,'coordinator',first['handle'],first['lease_token'],outcome='succeeded',output={'text':'late'},proposal_ids=[])

    def test_read_only_profile_cannot_bypass_tool_policy_via_structured_output(self):
        agent_registry.save_agent(self.conn,self.me,self.slug,{'agent_key':'read_only','allowed_tools':['read_page']})
        task=self.task_record(agent_key='read_only',target={'tab_key':'shots','row_id':'b_shot1','col_index':1})
        cp.spawn_dispatch(self.conn,self.slug,task['id'],agent_key='read_only',slot_key='single')
        claim=cp.claim_dispatch(self.conn,'readonly',['read_only'],allowed_projects=[self.slug])
        with self.assertRaises(cp.OrchestrationError):
            cp.prepare_dispatch_output(self.conn,self.context(claim),{'text':'unauthorized write'})
        self.assertEqual(db.one(self.conn,'SELECT count(*) FROM projectops.assistant_proposal WHERE project_slug=%s',(self.slug,)),0)

    def test_race_rejects_observer_qa_and_duplicate_agents(self):
        task=self.task_record(strategy='race',target={'tab_key':'shots','row_id':'b_shot1','col_index':1})
        for agents in (['sheet_ops'],['sheet_ops','sheet_ops'],['coordinator','qa_critic']):
            with self.assertRaises(ValueError):
                cp.start_race(self.conn,self.me,self.slug,task['id'],agents)

    def test_explicit_output_target_cannot_be_bypassed_without_scope(self):
        task=self.task_record(strategy='race',target={'tab_key':'shots','row_id':'b_shot1','col_index':1})
        cp.start_race(self.conn,self.me,self.slug,task['id'],['coordinator','sheet_ops'])
        claim=cp.claim_dispatch(self.conn,'coordinator',['coordinator'],allowed_projects=[self.slug])
        with self.assertRaises((tools.ToolError,cp.OrchestrationError)),self.conn.transaction():
            tools.propose_table_edit(self.context(claim),self.conn,{'tab_key':'shots','row_edits':[{'row_id':'b_shot2','cells':{'1':'outside target'}}]})

    def test_losing_last_candidate_closes_unactionable_gate(self):
        run,task,join,admitted,proposals=self.race()
        for dispatch in admitted:
            cp.cancel_dispatch(self.conn,self.me,self.slug,dispatch['handle'],'cancel candidates')
        self.assertIsNone(self.gate(task))

    def test_locked_target_leaves_both_candidates_pending(self):
        run,task,join,admitted,proposals=self.race()
        other=str(uuid.uuid4())
        repo.upsert_member(self.conn,other,'Other editor','member')
        repo.take_lock(self.conn,self.slug,'shots','b_shot1',other)
        with self.assertRaises(cp.OrchestrationError):
            cp.select_race_winner(self.conn,self.me,self.slug,self.gate(task)['id'],proposals[0],client_request_id='locked')
        self.assertTrue(all(store.proposal(self.conn,p)['status']=='pending' for p in proposals))

    def test_child_cannot_expand_explicit_parent_output_target(self):
        run=self.run_record()
        parent=self.task_record(run,agent_key='coordinator',scope=self.sheet_scope(),
            target={'tab_key':'shots','row_id':'b_shot1','col_index':1})
        cp.spawn_dispatch(self.conn,self.slug,parent['id'],agent_key='coordinator',slot_key='single')
        claim=cp.claim_dispatch(self.conn,'parent',['coordinator'],allowed_projects=[self.slug])
        with self.assertRaises(cp.OrchestrationError):
            cp.create_task(self.conn,self.me,self.slug,run['id'],objective='Escape',agent_key='sheet_ops',
                target={'tab_key':'shots','row_id':'b_shot1','col_index':0},parent_dispatch_id=claim['id'])
