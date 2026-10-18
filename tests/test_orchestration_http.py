import json
import os
import unittest
import uuid
from pathlib import Path

import test_product_http as fixture
from project_assistant import orchestration_service,orchestrator as cp,orchestration_store as db,tools
from project_docs import repository as repo


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'),'set OPENBENCH_TEST_DB_URI')
class OrchestrationHTTPTests(unittest.TestCase):
    setUp=fixture.ProductHTTPTests.setUp
    tearDown=fixture.ProductHTTPTests.tearDown
    request=fixture.ProductHTTPTests.request

    def create(self,**overrides):
        body={'client_request_id':uuid.uuid4().hex,'objective':'Check selected output','agent_key':'sheet_ops','write_mode':'analysis_only',**overrides}
        code,result,_=self.request(f'/projects/api/{self.slug}/orchestration/runs',method='POST',data=body)
        self.assertEqual(code,200,result)
        return body,result

    def test_routes_accept_underscore_agent_key(self):
        code,result,_=self.request(f'/projects/api/{self.slug}/agents/sheet_ops/toggle',method='POST',data={'enabled':False})
        self.assertEqual(code,200,result)
        self.assertFalse(result['agent']['enabled'])

    def test_post_replay_is_idempotent_and_changed_payload_conflicts(self):
        body,created=self.create()
        path=f'/projects/api/{self.slug}/orchestration/runs'
        code,replayed,_=self.request(path,method='POST',data=body)
        self.assertEqual(code,200,replayed)
        self.assertEqual(created['task']['id'],replayed['task']['id'])
        self.assertEqual(self.request(path,method='POST',data={**body,'agent_key':'doc_writer'})[0],409)

    def test_other_owner_cannot_read_private_run(self):
        body,created=self.create()
        other=str(uuid.uuid4())
        repo.upsert_member(self.conn,other,'Other admin','admin'); self.conn.commit()
        token='other-admin-'+other
        configured=json.loads(os.environ['OPENBENCH_TOKENS']); configured[token]=other
        os.environ['OPENBENCH_TOKENS']=json.dumps(configured)
        def cleanup():
            import psycopg
            with psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI']) as connection:
                connection.execute('DELETE FROM projectops.member WHERE actor_id=%s',(other,))
        self.addCleanup(cleanup)
        path=f'/projects/api/{self.slug}/orchestration/runs/'+created['run']['id']
        self.assertEqual(self.request(path,headers={'Authorization':'Bearer '+token})[0],404)
        code,board,_=self.request(f'/projects/api/{self.slug}/orchestration/board',headers={'Authorization':'Bearer '+token})
        self.assertEqual(code,200,board)
        self.assertNotIn(created['task']['id'],json.dumps(board))

    def test_wrong_project_dispatch_is_not_found(self):
        body,created=self.create()
        other=self.slug+'-other'
        repo.upsert_project(self.conn,other,'Other'); self.conn.commit()
        def cleanup():
            import psycopg
            with psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI']) as connection:
                connection.execute('DELETE FROM projectops.project WHERE slug=%s',(other,))
        self.addCleanup(cleanup)
        dispatch=db.dispatches(self.conn,self.slug,created['task']['id'])[0]
        code,result,_=self.request(f'/projects/api/{other}/orchestration/dispatches/{dispatch["id"]}/cancel',method='POST',
            data={'admission_no':dispatch['admission_no'],'reason':'wrong project'})
        self.assertEqual(code,404,result)

    def test_viewer_cannot_resolve_gate(self):
        body,created=self.create()
        claim=cp.claim_dispatch(self.conn,'http-worker',['sheet_ops'],allowed_projects=[self.slug])
        ctx=tools.ToolContext(lambda:None,self.slug,self.me,Path('.'),None,agent_key='sheet_ops',dispatch_id=claim['id'],
            admission_no=claim['admission_no'],lease_token=claim['lease_token'],worker_id='http-worker')
        gate=cp.open_gate(self.conn,ctx,question='Choose',options=['A','B'])
        repo.upsert_member(self.conn,self.actor,'Viewer','viewer'); self.conn.commit()
        code,result,_=self.request(f'/projects/api/{self.slug}/orchestration/gates/{gate["id"]}/resolve',method='POST',
            data={'client_request_id':'answer','resolution':'0'})
        self.assertEqual(code,403,result)

    def test_board_deduplicates_gate_and_proposal(self):
        body,created=self.create(write_mode='proposal',target={'tab_key':'shots','row_id':'b_shot1','col_index':1})
        claim=cp.claim_dispatch(self.conn,'http-worker',['sheet_ops'],allowed_projects=[self.slug])
        ctx=tools.ToolContext(lambda:None,self.slug,self.me,Path('.'),None,agent_key='sheet_ops',dispatch_id=claim['id'],
            admission_no=claim['admission_no'],lease_token=claim['lease_token'],worker_id='http-worker')
        proposals=cp.prepare_dispatch_output(self.conn,ctx,{'text':'candidate'})
        cp.complete_dispatch(self.conn,'http-worker',claim['handle'],claim['lease_token'],outcome='succeeded',output={'text':'candidate'},proposal_ids=proposals)
        self.conn.commit()
        code,board,_=self.request(f'/projects/api/{self.slug}/orchestration/board')
        self.assertEqual(code,200,board)
        self.assertEqual(len(board['needs_you']),1)
        self.assertEqual(board['counts']['needs_you'],1)
        self.assertEqual(board['needs_you'][0]['proposal_ids'],proposals)
        self.assertNotIn('lease_hash',json.dumps(board))
        gate=board['needs_you'][0]['gate_id']
        path=f'/projects/api/{self.slug}/orchestration/gates/{gate}/resolve'
        self.assertEqual(self.request(path,method='POST',data={'client_request_id':'typo','resolution':{'proposal_id':proposals[0],'decision':'appply'}})[0],400)
        decision={'client_request_id':'review-once','resolution':{'proposal_id':proposals[0],'decision':'apply'}}
        self.assertEqual(self.request(path,method='POST',data=decision)[0],200)
        self.assertEqual(self.request(path,method='POST',data=decision)[0],200)

    def test_post_body_schema_excludes_privilege_fields(self):
        path=f'/projects/api/{self.slug}/orchestration/runs'
        for body in ([],{'client_request_id':'x','objective':'task','chain':['agent:admin']},
                      {'client_request_id':'x','objective':'task','depends_on':[str(uuid.uuid4())]}):
            self.assertEqual(self.request(path,method='POST',data=body)[0],400)

    def test_board_pagination_and_lightweight_counts(self):
        run=cp.create_run(self.conn,self.me,self.slug,'Many tasks',client_request_id='many')
        for _ in range(51):
            task=cp.create_task(self.conn,self.me,self.slug,run['id'],objective='Check',agent_key='sheet_ops',write_mode='analysis_only')
            cp.spawn_dispatch(self.conn,self.slug,task['id'],agent_key='sheet_ops',slot_key='single')
        self.conn.commit()
        base=f'/projects/api/{self.slug}/orchestration/board'
        code,first,_=self.request(base+'?limit=50')
        self.assertEqual(code,200,first)
        self.assertEqual(len(first['working']),50)
        code,second,_=self.request(base+'?limit=50&cursor='+first['cursor'])
        self.assertEqual(code,200,second)
        self.assertEqual(len(second['working']),1)
        self.assertFalse({v['id'] for v in first['working']} & {v['id'] for v in second['working']})
        code,count,_=self.request(base+'?counts_only=true')
        self.assertEqual(code,200,count)
        self.assertEqual(count['counts']['working'],51)
        self.assertEqual(count['working'],[])

    def test_http_gate_resume_proposal_apply_and_terminal_detail(self):
        body,created=self.create(write_mode='proposal',target={'tab_key':'shots','row_id':'b_shot1','col_index':1})
        first=cp.claim_dispatch(self.conn,'http-worker',['sheet_ops'],allowed_projects=[self.slug])
        ctx=tools.ToolContext(lambda:None,self.slug,self.me,Path('.'),None,agent_key='sheet_ops',dispatch_id=first['id'],
            admission_no=first['admission_no'],lease_token=first['lease_token'],worker_id='http-worker')
        gate=cp.open_gate(self.conn,ctx,question='Choose',options=['A','B'])
        cp.complete_dispatch(self.conn,'http-worker',first['handle'],first['lease_token'],outcome='awaiting_gate',output={},proposal_ids=[])
        self.conn.commit()
        path=f'/projects/api/{self.slug}/orchestration/gates/{gate["id"]}/resolve'
        answer={'client_request_id':'same-answer','resolution':'0'}
        self.assertEqual(self.request(path,method='POST',data=answer)[0],200)
        self.assertEqual(self.request(path,method='POST',data=answer)[0],200)
        resumed=cp.claim_dispatch(self.conn,'http-worker',['sheet_ops'],allowed_projects=[self.slug])
        ctx.dispatch_id,ctx.admission_no,ctx.lease_token=resumed['id'],resumed['admission_no'],resumed['lease_token']
        proposals=cp.prepare_dispatch_output(self.conn,ctx,{'text':'approved output'})
        cp.complete_dispatch(self.conn,'http-worker',resumed['handle'],resumed['lease_token'],outcome='succeeded',output={'text':'approved output'},proposal_ids=proposals)
        self.conn.commit()
        self.assertEqual(self.request(f'/projects/api/{self.slug}/assistant/proposals/{proposals[0]}/apply',method='POST',data={})[0],200)
        code,detail,_=self.request(f'/projects/api/{self.slug}/orchestration/runs/{created["run"]["id"]}')
        self.assertEqual(code,200,detail)
        self.assertEqual(detail['run']['status'],'succeeded')
        self.assertEqual(len(detail['dispatches']),2)
        self.assertNotIn('lease_hash',json.dumps(detail))

    def test_retry_endpoint_is_idempotent_and_new_run_cancel_is_terminal(self):
        body,created=self.create()
        dispatch=db.dispatches(self.conn,self.slug,created['task']['id'])[0]
        self.conn.rollback()
        base=f'/projects/api/{self.slug}/orchestration'
        self.assertEqual(self.request(f'{base}/dispatches/{dispatch["id"]}/cancel',method='POST',data={'admission_no':dispatch['admission_no']})[0],200)
        request={'client_request_id':'retry-once'}
        code,retried,_=self.request(f'{base}/tasks/{created["task"]["id"]}/retry',method='POST',data=request)
        self.assertEqual(code,200,retried)
        code,replayed,_=self.request(f'{base}/tasks/{created["task"]["id"]}/retry',method='POST',data=request)
        self.assertEqual(code,200,replayed)
        self.assertEqual(retried['dispatch_handles'],replayed['dispatch_handles'])
        self.assertEqual(self.request(f'{base}/runs/{created["run"]["id"]}/cancel',method='POST',data={})[0],200)
        self.assertEqual(self.request(f'{base}/tasks/{created["task"]["id"]}/retry',method='POST',data={'client_request_id':'after-cancel'})[0],409)
