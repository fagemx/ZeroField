"""Shared chat/managed journeys against deterministic HTTP models and real PG."""
import json
import os
from pathlib import Path
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from orchestration_fixture import OrchestrationFixture
from project_assistant import outcome_grader as grading, agent_registry, worker, service, store
from project_assistant import orchestration_store as db, orchestrator as cp, tools, agent_runtime


class ScorecardTests(unittest.TestCase):
    def test_strict_scorecard_schema_and_contradictions(self):
        good={'passed':False,'score':30,'feedback':'Fix timing','checklist':[{'criterion':'Timing','passed':False}]}
        self.assertEqual(grading.scorecard(json.dumps(good)),good)
        for change in ({'passed':1},{'score':True},{'score':101},{'passed':True},{'extra':'bad'},{'checklist':[{'criterion':'x','passed':'yes'}]}):
            with self.subTest(change=change),self.assertRaises(ValueError): grading.scorecard({**good,**change})


class OutcomeJourneyTests(OrchestrationFixture,unittest.TestCase):
    def factory(self):
        import psycopg
        return psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI'],connect_timeout=3)

    def fixture(self, *, always_fail=False, malformed=False, stage=False, pending=False, revoke=False, advisor=False, cancel=False, expire=False):
        self.requests=[];self.grades=0
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.requests.append(request)
                system=request['messages'][0]['content']
                text=request['messages'][1]['content']
                if system == grading.GRADE_INSTRUCTIONS:
                    owner.grades+=1
                    # No staged proposal has become reviewable at either grade pass.
                    with owner.factory() as conn:
                        if stage: owner.assertEqual(db.one(conn,'SELECT count(*) FROM projectops.assistant_proposal WHERE project_slug=%s',(owner.slug,)),0)
                    card={'passed':not always_fail and owner.grades>1,'score':25 if owner.grades==1 or always_fail else 95,
                          'feedback':'Improve the candidate','checklist':[{'criterion':'Evidence','passed':not always_fail and owner.grades>1}]}
                    message={'content':'not-json' if malformed else json.dumps(card)}
                    if cancel:
                        with owner.factory() as conn:
                            cp.cancel_dispatch(conn,owner.me,owner.slug,owner.cancel_claim['handle'],'Cancel during independent grading')
                    if expire:
                        time.sleep(expire)
                    if revoke:
                        with owner.factory() as conn: agent_registry.save_agent(conn,owner.me,owner.slug,{'agent_key':'sheet_ops','enabled':False})
                elif system == grading.REVISION_INSTRUCTIONS:
                    payload=json.loads(text)
                    candidate=payload['candidate'];candidate['answer']='Revised candidate'
                    if candidate['proposals']:
                        candidate['proposals'][0]['args']['row_edits'][0]['cells']['1']='revised staged text'
                    message={'content':json.dumps(candidate)}
                elif advisor and request['model'] == 'grader-fixture':
                    message={'content':'Advisor critique'}
                elif advisor and len(owner.requests)==1:
                    message={'content':'','tool_calls':[{'id':'advisor','type':'function','function':{'name':'consult_advisor','arguments':json.dumps({'question':'Check evidence','candidate':'Candidate'})}}]}
                elif pending and len(owner.requests)==1:
                    message={'content':'','tool_calls':[{'id':'gate','type':'function','function':{'name':'ask_decision_gate','arguments':json.dumps({'question':'Choose style','options':['A','B']})}}]}
                elif stage and not any(m.get('role')=='tool' for m in request['messages']):
                    args={'tab_key':'shots','row_edits':[{'row_id':'b_shot1','cells':{'1':'discarded draft'}}]}
                    message={'content':'','tool_calls':[{'id':'proposal','type':'function','function':{'name':'propose_table_edit','arguments':json.dumps(args)}}]}
                else:
                    message={'content':'Initial candidate'}
                data=json.dumps({'choices':[{'message':message}],'usage':{'prompt_tokens':20,'completion_tokens':5,'prompt_tokens_details':{'cached_tokens':3}}}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers()
                try: self.wfile.write(data)
                except (BrokenPipeError,ConnectionAbortedError,ConnectionResetError): pass
            def log_message(self,*args): pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        for key,model in [('sheet_ops','worker-fixture'),('qa_critic','grader-fixture')]:
            agent_registry.save_agent(self.conn,self.me,self.slug,{'agent_key':key,
                'provider_config':{'kind':'openai_compat','base_url':f'http://127.0.0.1:{server.server_port}/v1','model':model},
                'system_prompt':'PRIVATE WORKER PROMPT' if key=='sheet_ops' else 'PRIVILEGED GRADER PERSONA'})
        return server

    def enable(self, revisions=1):
        agent_registry.save_agent(self.conn,self.me,self.slug,{'agent_key':'sheet_ops',
            'outcome_grader':{'enabled':True,'criteria':'Evidence rubric','grader_agent_key':'qa_critic','max_revisions':revisions}})

    def chat(self):
        result=service.send(self.conn,self.me,self.slug,{'text':'Original objective','agent_key':'sheet_ops'})
        self.assertEqual(result[0],200,result)
        claim=store.claim_next(self.conn,'grader-chat',worker.LEASE_SECONDS)
        self.conn.commit()
        status=worker.execute(self.factory,claim,worker.settings_from_env(),'grader-chat')
        return status,store.message(self.conn,claim['id'])

    def test_actual_chat_fail_revise_pass_isolated_inputs_tokens_and_trace(self):
        self.fixture();self.enable()
        # Hidden conversation is deliberately supplied only to the worker.
        service.send(self.conn,self.me,self.slug,{'text':'PRIVATE CONVERSATION SENTINEL','agent_key':'doc_writer'})
        prior=store.claim_next(self.conn,'prior',300)
        store.finish(self.conn,prior['id'],'prior',body='PRIVATE TOOL CONTEXT',seconds=0,model='fixture',codex_version='fixture')
        status,reply=self.chat()
        self.assertEqual(status,'done',reply)
        self.assertEqual(reply['body'],'Revised candidate')
        grade_requests=[r for r in self.requests if r['messages'][0]['content']==grading.GRADE_INSTRUCTIONS]
        self.assertEqual(len(grade_requests),2)
        for request in grade_requests:
            self.assertNotIn('tools',request)
            payload=json.loads(request['messages'][1]['content'])
            self.assertEqual(set(payload),{'objective','rubric','candidate','allowed_memory'})
            self.assertEqual(payload['objective'],'Original objective')
            for secret in ('PRIVATE WORKER PROMPT','PRIVATE CONVERSATION SENTINEL','PRIVATE TOOL CONTEXT','PRIVILEGED GRADER PERSONA'):
                self.assertNotIn(secret,json.dumps(request))
        entries=db.many(self.conn,'SELECT to_jsonb(l) FROM projectops.agent_usage_ledger l WHERE project_slug=%s',(self.slug,))
        self.assertEqual(len(entries),4)
        self.assertEqual(sum(e['input_tokens'] for e in entries),80)
        self.assertEqual(sum(e['cached_tokens'] for e in entries),12)
        self.assertEqual(sum(e['usage_kind']=='grader_check' for e in entries),2)
        self.assertTrue(all(e['estimated_cost_usd'] is None for e in entries))
        self.assertEqual(sum(t.get('name')=='outcome_grader' for t in reply['tools']),2)

    def test_actual_managed_limit_is_needs_you_failed_scorecard_not_success(self):
        self.fixture(always_fail=True);self.enable(revisions=0)
        run=self.run_record();task=self.task_record(run,write_mode='analysis_only')
        cp.spawn_dispatch(self.conn,self.slug,task['id'],agent_key='sheet_ops',slot_key='single')
        claim=cp.claim_dispatch(self.conn,'grader-managed',['sheet_ops'],allowed_projects=[self.slug]);self.conn.commit()
        self.assertEqual(worker.execute_dispatch(self.factory,claim,worker.settings_from_env(),'grader-managed'),'awaiting_gate')
        dispatch=db.get_dispatch(self.conn,self.slug,claim['id'])
        self.assertFalse(dispatch['output_json']['outcome_grader']['passed'])
        self.assertEqual(db.get_task(self.conn,self.slug,task['id'])['status'],'awaiting_gate')
        self.assertEqual(self.grades,1)
        self.assertEqual(db.one(self.conn,'SELECT count(*) FROM projectops.assistant_proposal WHERE project_slug=%s',(self.slug,)),0)

    def test_actual_staged_proposal_discard_revision_and_review_only_after_pass(self):
        self.fixture(stage=True);self.enable()
        status,reply=self.chat()
        self.assertEqual(status,'done',reply)
        proposals=store.proposals(self.conn,self.slug,owner_id=self.actor)
        self.assertEqual(len(proposals),1)
        self.assertIn('revised staged text',proposals[0]['content'])
        self.assertNotIn('discarded draft',proposals[0]['content'])
        self.assertEqual(proposals[0]['status'],'pending')

    def test_actual_malformed_grader_fails_safe_and_no_revision_dispatch(self):
        self.fixture(malformed=True);self.enable()
        status,reply=self.chat()
        self.assertEqual(status,'done',reply)
        self.assertIn('Needs You',reply['body'])
        self.assertEqual(self.grades,1)
        self.assertEqual(len(self.requests),2)
        self.assertEqual(db.one(self.conn,"SELECT count(*) FROM projectops.orchestration_gate WHERE project_slug=%s AND status='open'",(self.slug,)),1)

    def test_pending_human_tool_action_is_not_graded_or_reexecuted(self):
        self.fixture(pending=True);self.enable()
        status,reply=self.chat()
        self.assertEqual(status,'done',reply)
        self.assertEqual(self.grades,0)
        self.assertEqual(len(self.requests),1)
        self.assertEqual(db.one(self.conn,'SELECT count(*) FROM projectops.agent_usage_ledger WHERE project_slug=%s',(self.slug,)),1)

    def test_current_revocation_after_grader_cannot_publish(self):
        self.fixture(revoke=True);self.enable(revisions=0)
        status,reply=self.chat()
        self.assertNotEqual(reply['body'],'Initial candidate')
        self.assertNotEqual(status,'queued')
        self.assertEqual(db.one(self.conn,'SELECT count(*) FROM projectops.assistant_proposal WHERE project_slug=%s',(self.slug,)),0)


    def test_max_three_revisions_exhausted_remains_failed_needs_you(self):
        self.fixture(always_fail=True);self.enable(revisions=3)
        status,reply=self.chat()
        self.assertEqual(status,'done',reply)
        self.assertIn('Needs You',reply['body'])
        self.assertEqual(self.grades,4)
        self.assertEqual(len(self.requests),8)
        self.assertEqual(db.one(self.conn,'SELECT count(*) FROM projectops.agent_usage_ledger WHERE project_slug=%s',(self.slug,)),8)

    def test_actual_advisor_round_usage_and_session_budget_before_advisor_dispatch(self):
        self.fixture(advisor=True)
        status,reply=self.chat()
        self.assertEqual(status,'done',reply)
        entries=db.many(self.conn,'SELECT agent_key FROM projectops.agent_usage_ledger WHERE project_slug=%s',(self.slug,))
        self.assertEqual(entries.count('qa_critic'),1)
        self.assertEqual(entries.count('sheet_ops'),2)

    def test_advisor_budget_denied_before_outbound_and_never_replayed(self):
        self.fixture(advisor=True)
        from project_assistant import agent_console_store as console
        endpoint=agent_registry.get_agent(self.conn,self.slug,'sheet_ops')['provider_config']['base_url']
        def price(rate):
            return dict(base_url=endpoint,kind='openai_compat',input_usd_per_million=rate,output_usd_per_million=rate,max_input_tokens=50000,max_output_tokens=5,byte_bounded_tokenizer=True)
        old=console.get_settings(self.conn,self.me,self.slug)
        console.save_settings(self.conn,self.me,self.slug,{'version':old['version'],'spend_limit_session_usd':'.01',
            'model_pricing':{'worker-fixture':price(.01),'grader-fixture':price(1)}})
        status,reply=self.chat()
        self.assertEqual(status,'done',reply)
        self.assertEqual(sum(r['model']=='grader-fixture' for r in self.requests),0)
        self.assertEqual(len(self.requests),2)


    def test_remote_completion_is_graded_once_before_publication_and_replay_is_inert(self):
        self.fixture()
        from project_assistant import orchestration_limb
        from project_docs import http
        agent_registry.save_agent(self.conn,self.me,self.slug,{'agent_key':'external_text','runtime_kind':'remote_limb',
            'bound_limb_id':self.worker['id'],'capabilities':['llm'],'allowed_tools':['propose_table_edit'],
            'outcome_grader':{'enabled':True,'criteria':'Evidence','grader_agent_key':'qa_critic','max_revisions':0}})
        run=self.run_record();task=cp.create_task(self.conn,self.me,self.slug,run['id'],objective='Remote objective',agent_key='external_text',write_mode='analysis_only')
        cp.spawn_dispatch(self.conn,self.slug,task['id'],agent_key='external_text',slot_key='single')
        claim=cp.claim_dispatch(self.conn,self.worker,['external_text'],allowed_projects=[self.slug]);self.conn.commit()
        body={'task_id':claim['id'],'dispatch_handle':claim['handle'],'lease_token':claim['lease_token'],'output':{'text':'Remote candidate'}}
        with patch.object(http,'open_connection',side_effect=self.factory):
            first=orchestration_limb.complete(self.conn,self.worker,body);self.conn.commit()
            second=orchestration_limb.complete(self.conn,self.worker,body);self.conn.commit()
        self.assertEqual(first,second)
        self.assertEqual(first['status'],'awaiting_gate')
        self.assertEqual(self.grades,1)
        self.assertEqual(db.one(self.conn,'SELECT count(*) FROM projectops.assistant_proposal WHERE project_slug=%s',(self.slug,)),0)


    def test_managed_cancel_during_grader_cannot_publish_or_revise(self):
        self.fixture(cancel=True);self.enable(revisions=3)
        run=self.run_record();task=self.task_record(run,write_mode='analysis_only')
        cp.spawn_dispatch(self.conn,self.slug,task['id'],agent_key='sheet_ops',slot_key='single')
        claim=cp.claim_dispatch(self.conn,'cancel-grader',['sheet_ops'],allowed_projects=[self.slug]);self.cancel_claim=claim;self.conn.commit()
        self.assertEqual(worker.execute_dispatch(self.factory,claim,worker.settings_from_env(),'cancel-grader'),'lost')
        self.assertEqual(db.get_dispatch(self.conn,self.slug,claim['id'])['status'],'canceled')
        self.assertEqual(len(self.requests),2)
        self.assertEqual(db.one(self.conn,'SELECT count(*) FROM projectops.assistant_proposal WHERE project_slug=%s',(self.slug,)),0)
        self.assertEqual(db.one(self.conn,'SELECT count(*) FROM projectops.agent_usage_ledger WHERE project_slug=%s',(self.slug,)),2)

    def test_whole_chat_deadline_includes_grader_and_prevents_revision(self):
        from dataclasses import replace
        # The governed worker turn opens ~10 fresh PG connections before the grader is admitted (~1 s on Windows),
        # so the budget must leave room to reach the grader; grading then outlasts the whole budget.
        self.fixture(expire=3.2);self.enable(revisions=3)
        sent=service.send(self.conn,self.me,self.slug,{'text':'Deadline objective','agent_key':'sheet_ops'})
        self.assertEqual(sent[0],200)
        claim=store.claim_next(self.conn,'deadline-grader',worker.LEASE_SECONDS);self.conn.commit()
        worker.execute(self.factory,claim,replace(worker.settings_from_env(),timeout=3),'deadline-grader')
        reply=store.message(self.conn,claim['id'])
        self.assertEqual(reply['status'],'failed')
        self.assertEqual(len(self.requests),2)
        self.assertEqual(self.grades,1)
        self.assertEqual(db.one(self.conn,'SELECT count(*) FROM projectops.assistant_proposal WHERE project_slug=%s',(self.slug,)),0)


    def test_grader_cannot_silently_drop_required_images_after_privacy_revocation(self):
        self.fixture()
        db.execute(self.conn,"UPDATE projectops.project SET privacy_mode='mask_numbers' WHERE slug=%s",(self.slug,))
        self.conn.commit()
        ctx=tools.ToolContext(self.factory,self.slug,self.me,Path('.'),None,agent_key='sheet_ops')
        grader=agent_registry.get_agent(self.conn,self.slug,'qa_critic')
        with self.assertRaises(ValueError):
            grading.evaluate_outcome(ctx=ctx,objective='Check visual candidate',rubric='See media',candidate={'answer':'Candidate','proposals':[]},
                grader=grader,timeout=2,images=['data:image/png;base64,synthetic-fixture'])
        self.assertEqual(self.requests,[])
