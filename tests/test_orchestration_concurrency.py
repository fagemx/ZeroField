import datetime as dt
import os
import unittest
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from orchestration_fixture import OrchestrationFixture
from project_assistant import orchestrator as cp,orchestration_store as db


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'),'set OPENBENCH_TEST_DB_URI')
class AdmissionTests(OrchestrationFixture,unittest.TestCase):
    def dispatch(self,task=None,**kwargs):
        task=task or self.task_record(write_mode='analysis_only')
        return cp.spawn_dispatch(self.conn,self.slug,task['id'],agent_key=task['target_agent_key'],slot_key='single',**kwargs)

    def claim(self,worker='worker-1',keys=None):
        return cp.claim_dispatch(self.conn,worker,keys or ['coordinator','sheet_ops','qa_critic','doc_writer'],allowed_projects=[self.slug])

    def finish(self,dispatch,output=None):
        return cp.complete_dispatch(self.conn,dispatch['lease_owner'],dispatch['handle'],dispatch['lease_token'],
                                    outcome='succeeded',output=output or {'text':'done'},proposal_ids=[])

    def test_stale_completion_after_retry(self):
        task=self.task_record(write_mode='analysis_only')
        first=self.dispatch(task)
        claimed=self.claim()
        cp.cancel_dispatch(self.conn,self.me,self.slug,first['handle'],'reassign')
        second=self.dispatch(task)
        self.assertGreater(second['admission_no'],first['admission_no'])
        with self.assertRaises(cp.OrchestrationError) as raised:
            self.finish(claimed)
        self.assertEqual(raised.exception.code,'STALE_DISPATCH')
        self.assertEqual(db.get_dispatch(self.conn,self.slug,second['id'])['status'],'queued')

    def test_worker_done_is_written_once(self):
        self.dispatch()
        claim=self.claim()
        self.assertEqual(self.finish(claim)['status'],'succeeded')
        self.assertEqual(self.finish(claim)['status'],'succeeded')
        count=db.one(self.conn,"SELECT count(*) FROM projectops.orchestration_message WHERE dispatch_id=%s AND msg_type='worker_done'",(claim['id'],))
        self.assertEqual(count,1)
        with self.assertRaises(cp.OrchestrationError):
            self.finish(claim,{'text':'different'})

    def test_claim_capacity_is_enforced_by_database(self):
        run=self.run_record(limits={'max_parallel_dispatches':2})
        for _ in range(3):
            self.dispatch(self.task_record(run,write_mode='analysis_only'))
        a,b=self.claim('a'),self.claim('b')
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertIsNone(self.claim('c'))
        self.finish(a)
        self.assertIsNotNone(self.claim('c'))

    def test_claim_capacity_across_two_connections(self):
        import psycopg
        run=self.run_record()
        for _ in range(4):
            self.dispatch(self.task_record(run,write_mode='analysis_only'))
        self.conn.commit()
        barrier=threading.Barrier(4)
        def claim(index):
            barrier.wait(timeout=5)
            for _ in range(8):
                with psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI']) as connection:
                    value=cp.claim_dispatch(connection,'parallel-'+str(index),['sheet_ops'],allowed_projects=[self.slug])
                if value:
                    return value
                time.sleep(.01)
            return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            claimed=list(pool.map(claim,range(4)))
        self.assertEqual(len([v for v in claimed if v]),2)
        self.assertEqual(db.one(self.conn,"SELECT count(*) FROM projectops.orchestration_dispatch WHERE run_id=%s AND status='running'",(run['id'],)),2)

    def test_renew_cannot_resurrect_expired_lease(self):
        self.dispatch()
        claimed=self.claim()
        db.execute(self.conn,"UPDATE projectops.orchestration_dispatch SET lease_until=NOW()-INTERVAL '1 second' WHERE id=%s",(claimed['id'],))
        with self.assertRaises(cp.OrchestrationError) as raised:
            cp.renew_dispatch(self.conn,'worker-1',claimed['handle'],claimed['lease_token'])
        self.assertEqual(raised.exception.code,'STALE_DISPATCH')

    def test_expired_lease_requeues_with_new_admission(self):
        first=self.dispatch()
        claimed=self.claim()
        db.execute(self.conn,"UPDATE projectops.orchestration_dispatch SET lease_until=NOW()-INTERVAL '1 second' WHERE id=%s",(first['id'],))
        cp.sweep(self.conn)
        next_claim=self.claim()
        self.assertIsNotNone(next_claim)
        self.assertGreater(next_claim['admission_no'],first['admission_no'])
        with self.assertRaises(cp.OrchestrationError):
            self.finish(claimed)

    def test_child_deadline_cannot_exceed_parent(self):
        parent_task=self.task_record(agent_key='coordinator',write_mode='analysis_only')
        parent=self.dispatch(parent_task,requested_deadline=cp.now()+dt.timedelta(seconds=120))
        parent_claim=self.claim()
        child=self.task_record(db.get_run(self.conn,self.slug,parent['run_id']),agent_key='qa_critic',
                               write_mode='analysis_only',parent_dispatch_id=parent['id'])
        dispatch=self.dispatch(child,caller_dispatch_id=parent['id'],requested_deadline=cp.now()+dt.timedelta(hours=1))
        self.assertLessEqual(cp.instant(dispatch['deadline_at']),cp.instant(parent['deadline_at']))
        self.assertEqual(dispatch['chain'],['user:'+self.actor,'agent:coordinator','agent:qa_critic'])
        child_claim=self.claim()
        grandchild=self.task_record(db.get_run(self.conn,self.slug,parent['run_id']),agent_key='doc_writer',write_mode='analysis_only')
        with self.assertRaises(cp.OrchestrationError) as denied:
            self.dispatch(grandchild,caller_dispatch_id=child_claim['id'])
        self.assertEqual(denied.exception.code,'POLICY_DENIED')

    def test_parent_cancel_stops_descendants(self):
        parent_task=self.task_record(agent_key='coordinator',write_mode='analysis_only')
        parent=self.dispatch(parent_task)
        self.claim()
        child=self.task_record(db.get_run(self.conn,self.slug,parent['run_id']),write_mode='analysis_only',parent_dispatch_id=parent['id'])
        dispatched=self.dispatch(child,caller_dispatch_id=parent['id'])
        cp.cancel_dispatch(self.conn,self.me,self.slug,parent['handle'],'stop')
        self.assertEqual(db.get_dispatch(self.conn,self.slug,dispatched['id'])['status'],'canceled')

    def test_second_failure_is_terminal(self):
        first=self.dispatch()
        claimed=self.claim()
        cp.complete_dispatch(self.conn,'worker-1',claimed['handle'],claimed['lease_token'],outcome='failed',
                             output={'error':'temporary','retryable':True},proposal_ids=[])
        second=self.claim()
        self.assertIsNotNone(second)
        cp.complete_dispatch(self.conn,'worker-1',second['handle'],second['lease_token'],outcome='failed',
                             output={'error':'temporary','retryable':True},proposal_ids=[])
        self.assertIsNone(self.claim())
        self.assertEqual(db.get_task(self.conn,self.slug,first['task_id'])['status'],'failed')
