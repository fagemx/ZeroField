"""Real isolated PostgreSQL admission, no provider/CLI inference or credentials."""
import datetime as dt
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from orchestration_fixture import OrchestrationFixture
from project_assistant import execution_governance as gov, agent_console_store as console
from project_assistant import agent_registry, orchestrator as cp, orchestration_store as db, tools, providers


class GovernanceTests(OrchestrationFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.ctx = tools.ToolContext(self.factory, self.slug, self.me, Path('.'), None)
        self.ctx.accounting_session_key = 'session-one'

    def factory(self):
        import psycopg
        return psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI'], connect_timeout=3)

    def settings(self, **fields):
        old = console.get_settings(self.conn, self.me, self.slug)
        return console.save_settings(self.conn, self.me, self.slug, {'version':old['version'], **fields})

    def admit(self, key, amount=None, **fields):
        return gov.reserve(self.conn, self.ctx, request_key=key, agent_key='coordinator', usage_kind='llm_turn',
            provider_name='fixture', model_name='fixture', ceiling=amount, **fields)

    def judge(self, count, prefix='g'):
        return gov.generation_admit(self.conn, self.ctx, [(prefix+str(i), cp.digest([prefix,i])) for i in range(count)])

    def test_judge_exact_tenth_eleventh_batch_replay_and_readonly_counter(self):
        self.settings(judge_trial_mode=True)
        self.assertEqual(self.judge(8), 8)
        with self.assertRaises(gov.AdmissionError), self.conn.transaction():
            self.judge(3, 'too-many')
        self.assertEqual(console.get_settings(self.conn,self.me,self.slug)['judge_trial_used_runs'], 8)
        self.assertEqual(self.judge(2, 'last'), 2)
        self.assertEqual(self.judge(2, 'last'), 0)
        with self.assertRaises(gov.AdmissionError): self.judge(1, 'eleventh')
        with self.assertRaises(agent_registry.AgentError): self.settings(judge_trial_used_runs=0)
        self.settings(judge_trial_mode=False)
        self.settings(judge_trial_mode=True)
        self.assertEqual(console.get_settings(self.conn,self.me,self.slug)['judge_trial_used_runs'], 10)
        viewer = type(self.me)(self.me.actor_id, self.me.name, 'viewer')
        with self.assertRaises(agent_registry.AgentError):
            console.set_judge_protection(self.conn,viewer,self.slug,enabled=False,version=console.get_settings(self.conn,self.me,self.slug)['version'])

    def test_concurrent_project_judge_last_slot_has_one_winner(self):
        self.settings(judge_trial_mode=True)
        self.judge(9)
        self.conn.commit()
        barrier=threading.Barrier(2)
        def attempt(n):
            with self.factory() as conn:
                barrier.wait(timeout=5)
                try:
                    return gov.generation_admit(conn,self.ctx,[(str(n),cp.digest(n))])
                except gov.AdmissionError: return 'denied'
        with ThreadPoolExecutor(max_workers=2) as pool: result=list(pool.map(attempt, ['a','b']))
        self.assertEqual(sorted(map(str,result)), ['1','denied'])
        self.assertEqual(console.get_settings(self.conn,self.me,self.slug)['judge_trial_used_runs'],10)

    def test_atomic_currency_across_concurrent_sessions(self):
        self.settings(spend_limit_monthly_usd=1, spend_limit_session_usd=1)
        self.conn.commit()
        barrier=threading.Barrier(2)
        def attempt(key):
            context=tools.ToolContext(self.factory,self.slug,self.me,Path('.'),None)
            context.accounting_session_key=key
            with self.factory() as conn:
                barrier.wait(timeout=5)
                try:
                    gov.reserve(conn,context,request_key=key,agent_key='coordinator',usage_kind='llm_turn',provider_name='fixture',model_name='fixture',ceiling='.6000')
                    return 'admitted'
                except gov.AdmissionError: return 'denied'
        with ThreadPoolExecutor(max_workers=2) as pool: result=list(pool.map(attempt,['one','two']))
        self.assertEqual(sorted(result),['admitted','denied'])

    def test_unknown_prices_not_free_and_chat_prep_do_not_debit_judge(self):
        self.settings(judge_trial_mode=True)
        with self.assertRaises(gov.AdmissionError): self.admit('commercial',commercial=True)
        self.admit('local')
        gov.dispatched(self.conn,self.slug,'local')
        gov.finalize(self.conn,self.slug,'local',outcome='succeeded',usage={'input_tokens':12,'output_tokens':3,'cached_tokens':4})
        gov.finalize(self.conn,self.slug,'local',outcome='succeeded',usage={'input_tokens':12,'output_tokens':3,'cached_tokens':4})
        row=db.one(self.conn,'SELECT to_jsonb(l) FROM projectops.agent_usage_ledger l WHERE project_slug=%s',(self.slug,))
        self.assertIsNone(row['estimated_cost_usd'])
        self.assertEqual(row['cached_tokens'],4)
        self.assertEqual(console.get_settings(self.conn,self.me,self.slug)['judge_trial_used_runs'],0)
        self.assertEqual(db.one(self.conn,'SELECT count(*) FROM projectops.agent_usage_ledger WHERE project_slug=%s',(self.slug,)),1)
        self.assertEqual(console.analytics(self.conn,self.me,self.slug)[0]['unknown_price_events'],1)

    def test_cancel_and_ambiguous_submission_keep_ceiling_no_replay(self):
        self.admit('not-sent','.5')
        self.assertEqual(gov.finalize(self.conn,self.slug,'not-sent',outcome='canceled')['state'],'released')
        self.admit('sent','.5')
        gov.dispatched(self.conn,self.slug,'sent')
        result=gov.finalize(self.conn,self.slug,'sent',outcome='canceled')
        self.assertEqual((result['state'],result['accounted_cost_usd']),('uncertain',.5))
        with self.assertRaises(gov.AdmissionError): self.admit('sent','.5')
        # Repeated settlement cannot erase uncertain accepted spend or charge twice.
        gov.finalize(self.conn,self.slug,'sent',outcome='succeeded',estimated_cost='.2')
        self.assertEqual(db.one(self.conn,'SELECT count(*) FROM projectops.agent_usage_ledger WHERE project_slug=%s AND event_key=%s',(self.slug,'sent')),1)

    def test_current_environment_credential_actor_and_lease_revocation(self):
        self.admit('ok')
        old=console.get_resource(self.conn,self.me,self.slug,'environment','env_local_4090')
        console.save_resource(self.conn,self.me,self.slug,'environment',{'env_key':'env_local_4090','version':old['version'],'network_access':'offline'})
        with self.assertRaises(agent_registry.AgentError): self.admit('offline',destination='http://127.0.0.1:9')
        with self.assertRaises(agent_registry.AgentError): self.admit('remote',destination='https://forbidden.invalid')
        run=self.run_record();task=self.task_record(run,write_mode='analysis_only')
        cp.spawn_dispatch(self.conn,self.slug,task['id'],agent_key='sheet_ops',slot_key='single')
        claim=cp.claim_dispatch(self.conn,'governance-worker',['sheet_ops'],allowed_projects=[self.slug])
        self.ctx.dispatch_id=claim['id'];self.ctx.admission_no=claim['admission_no'];self.ctx.lease_token=claim['lease_token'];self.ctx.worker_id='governance-worker'
        cp.cancel_dispatch(self.conn,self.me,self.slug,claim['handle'],'stop')
        with self.assertRaises(cp.OrchestrationError): self.admit('canceled')

    def test_rate_and_session_caps_and_both_spend_modes_pause_before_dispatch(self):
        for mode in ('pause','downgrade_open_weights'):
            self.settings(spend_limit_session_usd=0,on_spend_limit=mode)
            with self.assertRaises(gov.AdmissionError): self.admit(mode,'.1')
        self.settings(spend_limit_session_usd=5,rate_limits={'rpm_per_agent':1,'max_concurrent_renders':2,'max_concurrent_llm':1})
        self.admit('first')
        with self.assertRaises(gov.AdmissionError): self.admit('second')

    def test_token_bound_enforced_and_quote_is_not_json_authority(self):
        cfg=providers.ProviderConfig('openai_compat','https://fixture.invalid/v1','','model')
        self.assertEqual(gov.price_bound({},cfg,{}),(None,None))
        prices={'model_pricing':{'model':{'input_usd_per_million':1,'output_usd_per_million':2,'max_input_tokens':100,'max_output_tokens':5}}}
        amount,price=gov.price_bound(prices,cfg,{'text':'hello'})
        self.assertGreater(amount,0)
        with self.assertRaises(gov.AdmissionError): gov.price_bound(prices,cfg,{'text':'x'*200})
        from project_assistant import limb_worker
        card=limb_worker.load_studio_card('ltx25-cinema')
        self.settings(judge_trial_mode=True)
        op=dict(request_key='render',card=card,operation_digest=cp.digest(card))
        gov.prepare_operation(self.conn,self.ctx,**op)
        self.assertEqual(console.get_settings(self.conn,self.me,self.slug)['judge_trial_used_runs'],1)
        gov.prepare_operation(self.conn,self.ctx,**op)
        self.assertEqual(console.get_settings(self.conn,self.me,self.slug)['judge_trial_used_runs'],1)
        gov.begin_operation(self.conn,self.ctx,'render',card=card)
        with self.assertRaises(gov.AdmissionError): gov.begin_operation(self.conn,self.ctx,'render',card=card)

    def test_invalid_money_and_private_analytics_redaction(self):
        for value in (True,-1,float('nan'),float('inf'),'1.00001'):
            with self.subTest(value=value),self.assertRaises(agent_registry.AgentError): self.admit('bad',value)
        self.admit('safe','.1');gov.dispatched(self.conn,self.slug,'safe');gov.finalize(self.conn,self.slug,'safe',outcome='succeeded')
        public=str(console.analytics(self.conn,self.me,self.slug))
        for private in ('owner_id','session_key','reservation_key'): self.assertNotIn(private,public)


    def test_compat_actual_usage_hook_no_ambiguous_retry_or_duplicate_charge(self):
        import http.client, io, json
        from project_assistant import agent_runtime
        env=patch.dict(os.environ,{'OPENBENCH_AGENT_KEY_ENVS':'GOVERNANCE_FIXTURE_KEY','GOVERNANCE_FIXTURE_KEY':'synthetic-credential','OPENBENCH_PRODUCTION_POLICY':'hybrid_studio'})
        env.start();self.addCleanup(env.stop)
        from project_docs import story_openapi as story
        story.store(self.conn,'policy_'+self.slug,'policy',{'productionPolicy':'hybrid_studio'},self.slug)  # unknown remote = closed (SPEC_20 R9)
        base='https://priced-provider.invalid/v1'
        profile=agent_registry.save_agent(self.conn,self.me,self.slug,{'agent_key':'coordinator',
            'provider_config':{'kind':'openai_compat','base_url':base,'model':'priced-fixture','api_key_env':'GOVERNANCE_FIXTURE_KEY'}})
        environment=console.get_resource(self.conn,self.me,self.slug,'environment','env_local_4090')
        console.save_resource(self.conn,self.me,self.slug,'environment',{'env_key':'env_local_4090','version':environment['version'],'network_access':'full'})
        self.settings(model_pricing={'priced-fixture':dict(kind='openai_compat',base_url=base,input_usd_per_million=1,
            output_usd_per_million=2,max_input_tokens=100000,max_output_tokens=10,byte_bounded_tokenizer=True)})
        self.conn.commit()
        config=agent_runtime.provider_for(profile)
        sent=[]
        def run(admission,reply):
            def opener(request,timeout):
                sent.append(json.loads(request.data))
                return reply()
            return providers.run_openai_compat_turn(config=config,instructions='Fixture',turn_text='Objective',call_tool=lambda *_:None,
                timeout=5,tool_specs=[],opener=opener,admission=admission)
        success=lambda:io.BytesIO(json.dumps({'choices':[{'message':{'content':'Candidate'}}],
            'usage':{'prompt_tokens':7,'completion_tokens':3,'prompt_tokens_details':{'cached_tokens':2}}}).encode())
        self.assertEqual(run(gov.ProviderAdmission(self.ctx,profile,config),success).status,'ok')
        self.assertEqual(sent[0]['max_completion_tokens'],10)
        with self.assertRaises(gov.AdmissionError): run(gov.ProviderAdmission(self.ctx,profile,config),success)
        self.assertEqual(len(sent),1)
        def reset():
            raise http.client.RemoteDisconnected('fixture reset after send')
        result=run(gov.ProviderAdmission(self.ctx,profile,config,purpose='independent-failure'),reset)
        self.assertEqual((result.status,result.error_kind),('error','unavailable'))
        self.assertEqual(len(sent),2)
        ledger=db.many(self.conn,'SELECT to_jsonb(l) FROM projectops.agent_usage_ledger l WHERE project_slug=%s',(self.slug,))
        self.assertEqual(len(ledger),2)
        self.assertEqual(sum(l['cached_tokens'] for l in ledger),2)
        self.assertTrue(any(l['meta']['outcome']=='unknown' and l['estimated_cost_usd']>0 for l in ledger))

    def test_expiry_and_provider_configuration_revocation_are_enforced(self):
        self.admit('reserved','.1')
        db.execute(self.conn,"UPDATE projectops.agent_usage_reservation SET lease_until=NOW()-INTERVAL '1 second' WHERE project_slug=%s",(self.slug,))
        self.admit('next')
        self.assertEqual(db.one(self.conn,'SELECT state FROM projectops.agent_usage_reservation WHERE project_slug=%s AND request_key=%s',(self.slug,'reserved')),'released')
        from project_assistant import agent_runtime
        profile=agent_registry.save_agent(self.conn,self.me,self.slug,{'agent_key':'coordinator',
            'provider_config':{'kind':'openai_compat','base_url':'http://127.0.0.1:9/v1','model':'original'}})
        admission=gov.ProviderAdmission(self.ctx,profile,agent_runtime.provider_for(profile))
        agent_registry.save_agent(self.conn,self.me,self.slug,{'agent_key':'coordinator','provider_config':{'model':'revoked-model'}})
        self.conn.commit()
        with self.assertRaises(gov.AdmissionError): admission.before({'messages':[]})



    def test_activation_rechecks_entire_queued_session_before_partial_submit(self):
        from project_assistant import limb_worker
        card=limb_worker.load_studio_card('ltx25-cinema')
        for n in range(11):
            gov.prepare_operation(self.conn,self.ctx,request_key='queued'+str(n),card=card,operation_digest=cp.digest([card,n]))
        self.assertEqual(console.get_settings(self.conn,self.me,self.slug)['judge_trial_used_runs'],0)
        self.settings(judge_trial_mode=True)
        with self.assertRaises(gov.AdmissionError): gov.begin_operation(self.conn,self.ctx,'queued0',card=card)
        self.assertEqual(console.get_settings(self.conn,self.me,self.slug)['judge_trial_used_runs'],0)
        self.assertEqual(db.one(self.conn,"SELECT count(*) FROM projectops.agent_usage_reservation WHERE project_slug=%s AND state='dispatched'",(self.slug,)),0)
        gov.release_unstarted(self.conn,self.slug,['queued'+str(n) for n in range(11)])
        self.assertEqual(db.one(self.conn,"SELECT count(*) FROM projectops.agent_usage_reservation WHERE project_slug=%s AND state='released'",(self.slug,)),11)



    def test_local_preparation_failure_releases_concurrency_without_claiming_free_cost(self):
        self.conn.commit()
        def failed():
            raise ValueError('Synthetic terminated local process')
        with self.assertRaises(ValueError): gov.run_operation(self.ctx,'failed-prep',failed)
        row=db.one(self.conn,'SELECT to_jsonb(r) FROM projectops.agent_usage_reservation r WHERE project_slug=%s AND request_key=%s',(self.slug,'failed-prep'))
        self.assertEqual(row['state'],'finalized')
        self.assertIsNone(row['accounted_cost_usd'])
        self.assertEqual(console.budget_summary(self.conn,self.me,self.slug)['active_operations'],0)



class MediaBoundaryTests(unittest.TestCase):
    def setUp(self):
        import test_story_openapi as fixture
        fixture.StoryHTTPTests.setUp(self)
        self.ctx=tools.ToolContext(self.factory,self.slug,self.me,Path('.'),None)
        old=console.get_settings(self.conn,self.me,self.slug)
        console.set_judge_protection(self.conn,self.me,self.slug,enabled=True,version=old['version'])
        self.conn.commit()

    def tearDown(self):
        import test_story_openapi as fixture
        fixture.StoryHTTPTests.tearDown(self)

    def factory(self):
        import psycopg
        return psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI'],connect_timeout=3)

    from test_story_openapi import StoryHTTPTests as _fixture
    request=_fixture.request
    call=_fixture.call
    ok=_fixture.ok
    prepare=_fixture.prepare

    def test_http_batch_all_or_none_exact_tenth_replay_and_eleventh_before_launch(self):
        shots=self.prepare();ids=[s['shotId'] for s in shots]
        gov.generation_admit(self.conn,self.ctx,[(str(n),cp.digest(n)) for n in range(9)]);self.conn.commit()
        from project_docs import story_openapi as story
        baseline=db.one(self.conn,"SELECT count(*) FROM projectops.story_record WHERE project_slug=%s AND kind='task'",(self.slug,))
        self.conn.commit()
        with patch.object(story._POOL,'submit') as submit:
            code,payload=self.call(f'/episodes/{self.ep}/shot-image-generations','POST',{'shotIds':ids,'appCode':'local-smoke'})
            self.assertEqual(code,409,payload)
            self.assertIn('Judge',payload['message'])
            submit.assert_not_called()
            self.assertEqual(db.one(self.conn,"SELECT count(*) FROM projectops.story_record WHERE project_slug=%s AND kind='task'",(self.slug,)),baseline)
            path='/shots/'+ids[0]+'/image-generations'
            first=self.ok(path,'POST',{'appCode':'local-smoke'},{'Idempotency-Key':'tenth'})
            replay=self.ok(path,'POST',{'appCode':'local-smoke'},{'Idempotency-Key':'tenth'})
            self.assertEqual(first,replay)
            self.assertEqual(submit.call_count,1)
            code,payload=self.call(path,'POST',{'appCode':'local-smoke'})
            self.assertEqual(code,409,payload)
            self.assertEqual(submit.call_count,1)
        self.assertEqual(console.get_settings(self.conn,self.me,self.slug)['judge_trial_used_runs'],10)
        reserved_fields=self.call(path,'POST',{'appCode':'local-smoke','_frozenCard':[{},{}]})
        self.assertEqual(reserved_fields[0],422)

    def test_unknown_commercial_price_cannot_spend_trial_or_override_policy(self):
        from project_assistant import limb_worker
        from project_docs import story_openapi as story
        card=limb_worker.load_studio_card('seedance-20-pro')
        op=dict(request_key='commercial',card=card,operation_digest=cp.digest(card))
        with patch.dict(os.environ,{'OPENBENCH_PRODUCTION_POLICY':'hybrid_studio','SEEDANCE_API_URL':'http://127.0.0.1:9'}):
            with self.assertRaises(Exception): gov.prepare_operation(self.conn,self.ctx,**op)
            story.store(self.conn,'policy_'+self.slug,'policy',{'productionPolicy':'hybrid_studio'},self.slug)
            with self.assertRaises(gov.AdmissionError): gov.prepare_operation(self.conn,self.ctx,**op)
            self.assertEqual(console.get_settings(self.conn,self.me,self.slug)['judge_trial_used_runs'],0)
            fake=lambda *_:{'amount_usd':0,'hard_bound':True}
            with patch.dict(gov._QUOTE_PROVIDERS,{'vendor_api':fake}),self.assertRaises(gov.AdmissionError): gov.prepare_operation(self.conn,self.ctx,**op)
            quote=lambda card,digest:gov.trusted_quote(amount_usd='.01',operation_digest=digest,expires_at=cp.now()+dt.timedelta(seconds=30),provenance='synthetic_fixed_price',hard_bound=True)
            with patch.dict(gov._QUOTE_PROVIDERS,{'vendor_api':quote}):
                gov.prepare_operation(self.conn,self.ctx,**op)
                self.assertEqual(console.get_settings(self.conn,self.me,self.slug)['judge_trial_used_runs'],1)
                gov.begin_operation(self.conn,self.ctx,'commercial',card=card)
                gov.finalize(self.conn,self.slug,'commercial',outcome='unknown')
                self.assertEqual(db.one(self.conn,'SELECT accounted_cost_usd FROM projectops.agent_usage_reservation WHERE project_slug=%s AND request_key=%s',(self.slug,'commercial')),__import__('decimal').Decimal('.01'))


    def test_v2_unknown_quote_reports_actionable_blocker_without_provider_submit(self):
        import time
        from project_assistant import limb_worker
        with patch.dict(os.environ,{'OPENBENCH_PRODUCTION_POLICY':'hybrid_studio','SEEDANCE_API_URL':'http://127.0.0.1:9','SEEDANCE_API_KEY':''}), patch.dict(gov._QUOTE_PROVIDERS,{},clear=True), patch.object(limb_worker,'execute_vendor_card',side_effect=AssertionError('No unbounded provider submit')):
            self.ok('/projects/pj_'+self.slug+'/production-policy','PUT',{'productionPolicy':'hybrid_studio'})
            code,started,_=self.request('/openapi/v2/run/ai-app/seedance-20-pro',method='POST',data={'nodeInfoList':[{'nodeId':'prompt','fieldName':'prompt','fieldValue':'Synthetic scene'}]},headers={'X-Project-Slug':self.slug})
            self.assertEqual(code,200,started)
            for _ in range(100):
                code,result,_=self.request('/openapi/v2/query',method='POST',data={'taskId':started['taskId']})
                self.assertEqual(code,200,result)
                if result['status']!='RUNNING': break
                time.sleep(.02)
            self.assertEqual(result['status'],'FAILED',result)
            self.assertIn('verified fixed/max-charge media quote',result['errorMessage'])
            self.assertEqual(console.get_settings(self.conn,self.me,self.slug)['judge_trial_used_runs'],0)


    def test_legacy_direct_batch_preflights_all_inputs_before_any_reservation(self):
        import io
        from PIL import Image
        from project_docs import story_openapi as story, repository as repo, story_allocation
        shots=self.prepare();ids=[s['shotId'] for s in shots]
        image=io.BytesIO();Image.new('RGB',(16,16),'blue').save(image,format='PNG')
        asset=repo.put_asset(self.conn,self.slug,data=image.getvalue(),content_type='image/png',actor_id=self.actor)
        for index,identifier in enumerate(ids):
            _,row=story.find_row(self.conn,identifier,'shot')
            updates={3:'An empty blue room'}
            if index==0: updates[4]=f'![Image](/projects/api/{self.slug}/assets/{asset})'
            story.mutate_row(self.conn,self.me,self.slug,row['tabKey'],row['rid'],updates)
        self.conn.commit()
        with patch.object(story_allocation,'preflight_inputs',wraps=story_allocation.preflight_inputs) as preflight, patch.object(gov,'prepare_operation',side_effect=AssertionError('No partial batch reservation')) as admission:
            code,result=self.call(f'/episodes/{self.ep}/shot-video-generations','POST',{'shotIds':ids,'appCode':'ltx25-cinema'})
            self.assertEqual(code,409,result)
            self.assertEqual(preflight.call_count,2)
            self.assertTrue(preflight.call_args_list[0].args[3]['ready'])
            self.assertFalse(preflight.call_args_list[1].args[3]['ready'])
            admission.assert_not_called()
        self.assertEqual(console.get_settings(self.conn,self.me,self.slug)['judge_trial_used_runs'],0)
