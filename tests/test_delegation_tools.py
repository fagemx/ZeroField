import os
import time
import unittest
import uuid
from pathlib import Path

from orchestration_fixture import OrchestrationFixture
from project_assistant import orchestrator as cp,orchestration_store as db,tools,store,agent_registry
from project_assistant import delegation_tools,service as assistant_service


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'),'set OPENBENCH_TEST_DB_URI')
class DelegationToolTests(OrchestrationFixture,unittest.TestCase):
    def context(self,dispatch=None,run=None):
        import psycopg
        ctx=tools.ToolContext(lambda:psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI']),self.slug,self.me,Path('.'),None,
                              agent_key=dispatch['agent_key'] if dispatch else 'coordinator')
        ctx.run_id=(dispatch or run)['run_id' if dispatch else 'id']
        if dispatch:
            ctx.dispatch_id,ctx.admission_no,ctx.lease_token=dispatch['id'],dispatch['admission_no'],dispatch['lease_token']
            ctx.worker_id=dispatch['lease_owner']
            ctx.write_mode=db.get_task(self.conn,self.slug,dispatch['task_id'])['write_mode']
        return ctx

    def running(self,key='coordinator',limits=None):
        run=self.run_record(limits=limits)
        task=self.task_record(run,agent_key=key,write_mode='analysis_only')
        cp.spawn_dispatch(self.conn,self.slug,task['id'],agent_key=key,slot_key='single')
        claim=cp.claim_dispatch(self.conn,'test-worker',[key],allowed_projects=[self.slug])
        return run,task,claim

    def test_tool_spawn_survives_connection_close(self):
        import json
        run,task,claim=self.running()
        ctx=self.context(claim)
        self.conn.commit()
        result=json.loads(tools.call(ctx,'spawn_agent',{'objective':'Read the table','target_agent':'sheet_ops','write_mode':'analysis_only'}))
        self.assertEqual(result['run_id'],run['id'])
        self.assertEqual(db.get_task(self.conn,self.slug,result['task_id'])['status'],'dispatched')
        # Replayed tool args use the persisted journal rather than billing twice.
        again=json.loads(tools.call(ctx,'spawn_agent',{'objective':'Read the table','target_agent':'sheet_ops','write_mode':'analysis_only'}))
        self.assertEqual(result['task_id'],again['task_id'])

    def test_wait_with_full_pool_returns_handle(self):
        import json
        run,task,claim=self.running(limits={'max_parallel_dispatches':1})
        ctx=self.context(claim)
        self.conn.commit()
        started=time.monotonic()
        result=json.loads(tools.call(ctx,'spawn_agent',{'objective':'Read','target_agent':'sheet_ops','write_mode':'analysis_only','wait':True}))
        self.assertIn('task_id',result)
        self.assertLess(time.monotonic()-started,1)

    def test_gate_resume_uses_new_admission(self):
        run,task,claim=self.running('sheet_ops')
        gate=cp.open_gate(self.conn,self.context(claim),question='Choose style',options=['A','B'])
        cp.complete_dispatch(self.conn,'test-worker',claim['handle'],claim['lease_token'],outcome='awaiting_gate',output={},proposal_ids=[])
        old=claim['admission_no']
        result=cp.resolve_gate(self.conn,self.me,self.slug,gate['id'],resolution='0',client_request_id='answer-once')
        resumed=cp.claim_dispatch(self.conn,'resumed',['sheet_ops'],allowed_projects=[self.slug])
        self.assertGreater(resumed['admission_no'],old)
        self.assertEqual(resumed['continuation']['answers'][-1]['answer'],'A')
        self.assertEqual(cp.resolve_gate(self.conn,self.me,self.slug,gate['id'],resolution='0',client_request_id='answer-once')['id'],result['id'])
        self.assertEqual(len(db.dispatches(self.conn,self.slug,task['id'])),2)
        with self.assertRaises(cp.OrchestrationError):
            cp.resolve_gate(self.conn,self.me,self.slug,gate['id'],resolution='1',client_request_id='different')

    def test_question_options_and_blocking_scope_are_validated(self):
        run,task,claim=self.running()
        for options in (['A'],list('ABCDEF')):
            with self.assertRaises(ValueError):
                cp.open_gate(self.conn,self.context(claim),question='Choose',options=options)
        with self.assertRaises(ValueError):
            cp.open_gate(self.conn,self.context(claim),question='Choose',options=['A','B'],blocking_task_ids=[str(uuid.uuid4())])

    def test_coordinator_receives_one_summary_in_original_conversation(self):
        conversation=store.current_conversation(self.conn,self.slug,self.actor)
        run=self.run_record(conversation_id=conversation)
        task=self.task_record(run,write_mode='analysis_only')
        cp.spawn_dispatch(self.conn,self.slug,task['id'],agent_key='sheet_ops',slot_key='single')
        claim=cp.claim_dispatch(self.conn,'test-worker',['sheet_ops'],allowed_projects=[self.slug])
        cp.complete_dispatch(self.conn,'test-worker',claim['handle'],claim['lease_token'],outcome='succeeded',output={'text':'Checked'},proposal_ids=[])
        store.new_conversation(self.conn,self.slug,self.actor)
        first=cp.finish_run_notice(self.conn,run['id'])
        self.assertEqual(cp.finish_run_notice(self.conn,run['id']),first)
        self.assertEqual(store.message(self.conn,first)['conversation_id'],conversation)

    def test_upgrade_preserves_custom_tool_policy(self):
        agent_registry.save_agent(self.conn,self.me,self.slug,{'agent_key':'doc_writer','allowed_tools':['read_page']})
        agent_registry.ensure_default_agents(self.conn,self.slug)
        self.assertEqual(agent_registry.get_agent(self.conn,self.slug,'doc_writer')['allowed_tools'],['read_page'])

    def test_progress_query_without_run_lists_recent_work_without_creating_a_run(self):
        import json
        run=self.run_record()
        code,sent=assistant_service.send(self.conn,self.me,self.slug,{'text':'What is the background progress?'})
        self.assertEqual(code,200)
        ctx=tools.ToolContext(lambda:None,self.slug,self.me,Path('.'),sent['reply']['id'])
        result=json.loads(delegation_tools.check_delegation(ctx,self.conn,{}))
        self.assertEqual(result['runs'][0]['id'],run['id'])
        self.assertEqual(db.one(self.conn,'SELECT count(*) FROM projectops.orchestration_run WHERE project_slug=%s',(self.slug,)),1)
