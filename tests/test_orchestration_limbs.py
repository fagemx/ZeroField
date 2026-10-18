import io
import os
import unittest
from urllib.parse import urlencode
from unittest.mock import patch

import test_product_http as fixture
from project_assistant import orchestrator as cp,orchestration_limb,orchestration_store as db,agent_registry,limb_worker


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'),'set OPENBENCH_TEST_DB_URI')
class OrchestrationLimbTests(unittest.TestCase):
    setUp=fixture.ProductHTTPTests.setUp
    tearDown=fixture.ProductHTTPTests.tearDown
    request=fixture.ProductHTTPTests.request

    def queued(self,*,strategy='single',scope=None,allowed_tools=None):
        agent_registry.save_agent(self.conn,self.me,self.slug,{'agent_key':'external_text','runtime_kind':'remote_limb',
            'bound_limb_id':self.worker['id'],'capabilities':['llm'],'allowed_tools':allowed_tools or ['propose_table_edit']})
        run=cp.create_run(self.conn,self.me,self.slug,'Remote test',client_request_id='remote')
        task=cp.create_task(self.conn,self.me,self.slug,run['id'],objective='Fill output',agent_key='external_text',
                            target={'tab_key':'shots','kind':'table','row_id':'b_shot1','col_index':1},strategy=strategy,scope=scope)
        for slot in (['row:'+rid for rid in scope['row_ids']] if strategy=='fanout_rows' else ['single']):
            cp.spawn_dispatch(self.conn,self.slug,task['id'],agent_key='external_text',slot_key=slot)
        self.conn.commit()
        return run,task

    def call_worker(self,action,data=None,**kwargs):
        return self.request('/projects/api/limbs/orchestration/'+action,method='POST',data=data,
            authenticated=False,headers={'Authorization':'Bearer '+self.token,**kwargs.pop('headers',{})},**kwargs)

    def test_remote_claim_complete_produces_proposal_not_direct_write(self):
        run,task=self.queued()
        code,result,_=self.call_worker('claim',{})
        self.assertEqual(code,200,result)
        claim=result['task']
        self.assertIsNotNone(claim)
        self.assertIn('dispatch_handle',claim)
        self.assertEqual(claim['capability'],'llm')
        code,result,_=self.call_worker('complete',{'task_id':claim['id'],'dispatch_handle':claim['dispatch_handle'],
                                                  'lease_token':claim['lease_token'],'output':{'text':'remote'}})
        self.assertEqual(code,200,result)
        self.assertEqual(result['status'],'awaiting_gate')
        self.assertEqual(db.get_task(self.conn,self.slug,task['id'])['status'],'awaiting_gate')

    def test_limb_late_upload_does_not_create_asset(self):
        from PIL import Image
        run,task=self.queued()
        code,result,_=self.call_worker('claim',{})
        self.assertEqual(code,200)
        claim=result['task']
        cp.cancel_dispatch(self.conn,self.me,self.slug,claim['dispatch_handle'],'cancel')
        self.conn.commit()
        before=db.one(self.conn,'SELECT count(*) FROM projectops.asset WHERE project_slug=%s',(self.slug,))
        image=io.BytesIO(); Image.new('RGB',(2,2),'red').save(image,format='PNG')
        query=urlencode({'task_id':claim['id'],'dispatch_handle':claim['dispatch_handle'],'lease_token':claim['lease_token']})
        code,result,_=self.call_worker('upload-cell-asset?'+query,raw=image.getvalue(),headers={'Content-Type':'image/png'})
        self.assertEqual(code,409,result)
        self.assertEqual(db.one(self.conn,'SELECT count(*) FROM projectops.asset WHERE project_slug=%s',(self.slug,)),before)

    def test_old_limb_worker_protocol_unchanged(self):
        self.queued()
        code,result,_=self.request('/projects/api/limbs/claim',method='POST',data={},authenticated=False,
            headers={'Authorization':'Bearer '+self.token})
        self.assertEqual(code,200,result)
        self.assertIsNone(result['task'])

    def test_opt_in_worker_processes_the_orchestration_queue(self):
        run,task=self.queued()
        head=limb_worker.Head(f'http://127.0.0.1:{self.server.server_port}',self.token)
        with patch.dict(limb_worker.ADAPTERS,{'fixture':lambda task,config,head:{'text':'adapter result'}}):
            self.assertTrue(limb_worker.process_one(head,{'orchestration_enabled':True,'capabilities':{'llm':{'adapter':'fixture'}}}))
        self.assertEqual(db.get_task(self.conn,self.slug,task['id'])['status'],'awaiting_gate')

    def test_remote_completion_replay_returns_saved_result(self):
        self.queued()
        code,result,_=self.call_worker('claim',{})
        claim=result['task']
        body={'task_id':claim['id'],'dispatch_handle':claim['dispatch_handle'],'lease_token':claim['lease_token'],'output':{'text':'once'}}
        self.assertEqual(self.call_worker('complete',body)[0],200)
        code,result,_=self.call_worker('complete',body)
        self.assertEqual(code,200,result)

    def test_remote_tools_recheck_frozen_policy_and_canceled_lease(self):
        self.queued(allowed_tools=['read_page','propose_table_edit'])
        _,result,_=self.call_worker('claim',{})
        claim=result['task']
        lease={key:claim[key] for key in ('dispatch_handle','lease_token')}; lease['task_id']=claim['id']
        code,result,_=self.call_worker('tool_list',lease)
        self.assertEqual(code,200,result)
        self.assertEqual({s['name'] for s in result['tools']},{'read_page','propose_table_edit'})
        code,result,_=self.call_worker('tool',dict(lease,name='read_page',arguments={'key':'shots'}))
        self.assertEqual(code,200,result)
        self.assertIn('Shot 1',result['text'])
        agent_registry.save_agent(self.conn,self.me,self.slug,{'agent_key':'external_text','allowed_tools':['read_page','propose_table_edit','offer_document']})
        self.conn.commit()
        self.assertEqual(self.call_worker('tool',dict(lease,name='offer_document',arguments={}))[0],403)
        cp.cancel_dispatch(self.conn,self.me,self.slug,claim['dispatch_handle'],'test cancel'); self.conn.commit()
        self.assertEqual(self.call_worker('tool',dict(lease,name='propose_table_edit',arguments={}))[0],409)

    def test_remote_question_releases_runtime_and_completes_once(self):
        _,task=self.queued(allowed_tools=['ask_decision_gate','propose_table_edit'])
        _,result,_=self.call_worker('claim',{})
        claim=result['task']; lease={key:claim[key] for key in ('dispatch_handle','lease_token')}; lease['task_id']=claim['id']
        code,result,_=self.call_worker('tool',dict(lease,name='ask_decision_gate',arguments={'question':'採哪個版本？','options':['A','B']}))
        self.assertEqual(code,200,result)
        self.assertTrue(__import__('json').loads(result['text'])['awaiting_gate'])
        body=dict(lease,outcome='awaiting_gate',output={})
        self.assertEqual(self.call_worker('complete',body)[0],200)
        self.assertEqual(self.call_worker('complete',body)[0],200)
        count=db.one(self.conn,"SELECT count(*) FROM projectops.orchestration_message WHERE dispatch_id=%s AND msg_type='worker_done'",(claim['id'],))
        self.assertEqual(count,1)

    def test_fanout_remote_input_contains_only_the_claimed_row(self):
        from project_docs import repository as repo
        from project_docs.doc_schema import column_ids
        tab=repo.get_tab(self.conn,self.slug,'shots')
        scope={'target_tab':'shots','table_id':'b_table','base_revision':tab['revision'],
               'row_ids':['b_shot1','b_shot2'],'column_ids':column_ids(tab['doc']['content'][0])}
        run,task=self.queued(strategy='fanout_rows',scope=scope)
        code,result,_=self.call_worker('claim',{})
        self.assertEqual(code,200,result)
        source=result['task']['input']
        self.assertEqual([row['row_id'] for row in source['rows']],['b_shot1'])
        self.assertEqual(source['rows'][0]['cells'],['Shot 1','original'])
        self.assertNotIn('Shot 2',source['tabs'][0]['text'])
        self.assertNotIn('fingerprint',source['request_scope'])
        for expected in ('b_shot1','b_shot2'):
            claim=result['task']
            self.assertEqual(claim['input']['rows'][0]['row_id'],expected)
            code,completed,_=self.call_worker('complete',{'task_id':claim['id'],'dispatch_handle':claim['dispatch_handle'],
                'lease_token':claim['lease_token'],'output':{'text':'generated '+expected}})
            self.assertEqual(code,200,completed)
            code,result,_=self.call_worker('claim',{})
