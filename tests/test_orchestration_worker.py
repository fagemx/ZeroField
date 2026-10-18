import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch

from orchestration_fixture import OrchestrationFixture
from project_assistant import orchestrator as cp,orchestration_store as db,worker,agent_registry,agent_runtime,service,store


class CredentialBoundaryTests(unittest.TestCase):
    def test_custom_endpoint_does_not_inherit_another_endpoint_secret(self):
        profile={'provider_config':{'kind':'openai_compat','base_url':'https://other.invalid/v1','model':'custom'}}
        config=agent_runtime.provider_for(profile,{'OPENBENCH_API_BASE':'https://original.invalid/v1','OPENBENCH_API_KEY':'original-secret'})
        self.assertEqual(config.api_key,'')


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'),'set OPENBENCH_TEST_DB_URI')
class OrchestrationWorkerTests(OrchestrationFixture,unittest.TestCase):
    def fixture(self):
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append(value)
                text=value['messages'][1]['content']
                if 'Delegation fixture' in text and not any(m.get('role')=='tool' for m in value['messages']):
                    message={'content':'','tool_calls':[{'id':'spawn','type':'function','function':{'name':'spawn_agent',
                        'arguments':json.dumps({'objective':'Check selected rows','target_agent':'sheet_ops'})}}]}
                elif 'Decision fixture' in text and '"answers"' not in text:
                    message={'content':'','tool_calls':[{'id':'gate','type':'function','function':{'name':'ask_decision_gate',
                        'arguments':json.dumps({'question':'Choose style','options':['A','B']})}}]}
                else:
                    message={'content':'Checked by fixture'}
                data=json.dumps({'choices':[{'message':message}]}).encode()
                self.send_response(200); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
            def log_message(self,*args): pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        agent_registry.save_agent(self.conn,self.me,self.slug,{'agent_key':'sheet_ops',
            'provider_config':{'kind':'openai_compat','model':'sheet-fixture','base_url':f'http://127.0.0.1:{server.server_port}/v1'}})
        return requests

    def factory(self):
        import psycopg
        return psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI'])

    def test_runtime_question_releases_slot_and_resumes_with_answer(self):
        requests=self.fixture()
        run=self.run_record()
        task=cp.create_task(self.conn,self.me,self.slug,run['id'],objective='Decision fixture',agent_key='sheet_ops',write_mode='analysis_only')
        cp.spawn_dispatch(self.conn,self.slug,task['id'],agent_key='sheet_ops',slot_key='single')
        claim=cp.claim_dispatch(self.conn,'runtime-worker',['sheet_ops'],allowed_projects=[self.slug])
        self.conn.commit()
        self.assertEqual(worker.execute_dispatch(self.factory,claim,worker.settings_from_env(),'runtime-worker'),'awaiting_gate')
        gate=db.one(self.conn,"SELECT to_jsonb(g) FROM projectops.orchestration_gate g WHERE run_id=%s AND status='open'",(run['id'],))
        self.assertIsNotNone(gate)
        self.assertIsNone(db.get_dispatch(self.conn,self.slug,claim['id'])['lease_until'])
        cp.resolve_gate(self.conn,self.me,self.slug,gate['id'],resolution='1',client_request_id='resume')
        resumed=cp.claim_dispatch(self.conn,'runtime-worker',['sheet_ops'],allowed_projects=[self.slug])
        self.conn.commit()
        self.assertEqual(worker.execute_dispatch(self.factory,resumed,worker.settings_from_env(),'runtime-worker'),'succeeded')
        self.assertEqual(db.get_task(self.conn,self.slug,task['id'])['status'],'completed')
        self.assertEqual(len(requests),2)
        self.assertEqual(requests[1]['model'],'sheet-fixture')
        self.assertIn('Choose style',requests[1]['messages'][1]['content'])
        self.assertIn('"answer": "B"',requests[1]['messages'][1]['content'])

    def test_poll_shares_one_budget_between_chat_and_dispatch(self):
        run=self.run_record()
        task=self.task_record(run,write_mode='analysis_only')
        cp.spawn_dispatch(self.conn,self.slug,task['id'],agent_key='sheet_ops',slot_key='single')
        self.assertEqual(service.send(self.conn,self.me,self.slug,{'text':'Write','agent_key':'doc_writer'})[0],200)
        self.conn.commit()
        submitted=[]
        count=worker.poll_once(self.factory,worker.settings_from_env(), 'poll-worker',submitted.append,busy=0)
        self.assertEqual(count,2)
        self.assertEqual({('dispatch' if 'admission_no' in c else 'chat') for c in submitted},{'dispatch','chat'})

    def test_chat_delegation_inherits_fixed_scope(self):
        self.fixture()
        configuration=agent_registry.get_agent(self.conn,self.slug,'sheet_ops')['provider_config']
        agent_registry.save_agent(self.conn,self.me,self.slug,{'agent_key':'coordinator','provider_config':configuration})
        status,result=service.send(self.conn,self.me,self.slug,{'text':'Delegation fixture','scope':self.sheet_scope(['b_shot1'])})
        self.assertEqual(status,200,result)
        claim=store.claim_next(self.conn,'chat-worker',worker.LEASE_SECONDS)
        self.conn.commit()
        self.assertEqual(worker.execute(self.factory,claim,worker.settings_from_env(),'chat-worker'),'done')
        task=db.one(self.conn,'SELECT to_jsonb(t) FROM projectops.orchestration_task t WHERE project_slug=%s ORDER BY created_at DESC LIMIT 1',(self.slug,))
        self.assertIsNotNone(task)
        self.assertIsNotNone(task['request_scope'])
        self.assertEqual(task['request_scope']['row_ids'],['b_shot1'])

    def test_model_prompt_excludes_private_scope_fingerprint(self):
        requests=self.fixture()
        run=self.run_record()
        task=cp.create_task(self.conn,self.me,self.slug,run['id'],objective='Read source',agent_key='sheet_ops',
                            scope=self.sheet_scope(['b_shot1']),write_mode='analysis_only')
        cp.spawn_dispatch(self.conn,self.slug,task['id'],agent_key='sheet_ops',slot_key='single')
        claim=cp.claim_dispatch(self.conn,'runtime-worker',['sheet_ops'],allowed_projects=[self.slug])
        self.conn.commit()
        self.assertEqual(worker.execute_dispatch(self.factory,claim,worker.settings_from_env(),'runtime-worker'),'succeeded')
        self.assertNotIn(task['request_scope']['fingerprint'],json.dumps(requests))
