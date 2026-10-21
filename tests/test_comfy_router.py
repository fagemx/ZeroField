"""Canonical official protocol fixtures over real HTTP/PG/FFmpeg; NOT live inference/billing."""
import copy
import datetime as dt
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from PIL import Image
from project_assistant import limb_worker as worker, agent_console_store as store, execution_governance as gov, orchestration_store as db
from project_assistant.studio import comfy_router as router, openapi_v2_hub as hub
from project_docs import repository as repo, story_openapi as story
import test_story_openapi as fixture


class RouterSchemaTests(unittest.TestCase):
    def test_all_seven_pinned_schemas_compile_native_inputs_and_are_graphless_hybrid(self):
        self.assertEqual(len(router.MODELS),7)
        for model in router.MODELS:
            card=worker.load_studio_card('router-'+model.split('/')[1])
            self.assertIsNone(worker._resolve_openapi_card_and_workflow(card['card_id'])[1])
            with self.assertRaises(worker.WorkerError): worker.ComfyPlatformClient(card['engine_config'])
            with self.assertRaises(worker.WorkerError): worker.enforce_card_policy(card)
            worker.enforce_card_policy(card,'hybrid_studio')
            values={f"{n['nodeId']}.{n['fieldName']}":n['defaultValue'] for n in card['nodes']}
            if model.startswith('higgsfield/'):
                values.update({'input.image_1':'own-image','input.video_url':'own-video'})
            nodes=router._nodes({'production_policy':'hybrid_studio'},card,values)
            media={n['fieldName']:nodes[n['fieldName']] for n in card['nodes'] if n['fieldType'] in ('IMAGE','VIDEO','AUDIO') and nodes[n['fieldName']]!='None'}
            payload=router._native(card,nodes,media)
            self.assertNotIn('inputs',payload)
            self.assertNotIn('workflow',payload)
            self.assertNotIn('api_key',json.dumps(payload))
        card=worker.load_studio_card('router-ltx-2-5-pro')
        for bad in [{'input.duration':7},{'input.resolution':'3840x2160'},{'input.fps':'30'},{'input.generate_audio':'yes'},{'input.bypass':True}]:
            with self.assertRaises(worker.WorkerError): router._native(card,router._nodes({},card,bad),{})
        card['engine_config']['model']='future/unverified'
        with self.assertRaises(worker.WorkerError): worker.validate_studio_card(card)
        seedance=worker.load_studio_card('router-dreamina-seedance-2-5-260628')
        with self.assertRaises(worker.WorkerError):
            router._native(seedance,router._nodes({},seedance,{'input.prompt':'Walk --duration 30'}),{})

    def test_router_key_does_not_redirect_local_backbone_or_export_unused_key(self):
        card=worker.load_studio_card('ltx25-cinema')
        with patch.dict(os.environ,{'COMFY_API_KEY':'synthetic-router-only','COMFY_ROUTER_TOKEN':'synthetic-legacy-token','COMFY_PLATFORM':'','COMFY_BASE_URL':'','COMFY_ROUTER_URL':''}):
            client=worker.ComfyPlatformClient(card['engine_config'])
            self.assertEqual((client.platform,client.base_url),('local','http://127.0.0.1:8188'))
            self.assertIsNone(client.sdk);self.assertIsNone(client.token)
            self.assertEqual(gov.media_destination(card),'http://127.0.0.1:8188')
            self.assertEqual(worker.comfy_platform({}),'comfy_sdk')  # Generic legacy SDK auto-selection stays compatible.
            self.assertEqual(worker.comfy_platform({**card['engine_config'],'platform':'comfy_sdk'}),'comfy_sdk')

    def test_native_minimax_roles_and_audio_are_not_flattened_or_dropped(self):
        card=worker.load_studio_card('router-minimax-h3')
        nodes=router._nodes({},card,{'input.prompt':'Recast the original performance','input.reference_image':'own-image','input.base_video':'own-video','input.reference_audio':'own-audio'})
        p=router._native(card,nodes,{'reference_image':'signed-image','base_video':'signed-video','reference_audio':'signed-audio'})
        self.assertEqual([c.get('role') for c in p['content']],[None,'reference_image','base_video','reference_audio'])
        with self.assertRaises(worker.WorkerError): router._native(card,nodes,{'first_frame':'a','reference_image':'b'})
        with self.assertRaises(worker.WorkerError): router.validate_native('minimax/minimax-h3',{'content':[],'duration':float('nan'),'resolution':'768P'})


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'),'dedicated isolated PG required')
class RouterHTTPTests(unittest.TestCase):
    request=fixture.StoryHTTPTests.request
    call=fixture.StoryHTTPTests.call
    ok=fixture.StoryHTTPTests.ok
    prepare=fixture.StoryHTTPTests.prepare
    await_task=fixture.StoryHTTPTests.await_task

    @classmethod
    def setUpClass(cls):
        cls.folder=tempfile.TemporaryDirectory(prefix='spec08-router-fixture-')
        cls.video=Path(cls.folder.name)/'stereo.mp4'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','lavfi','-i','color=c=blue:s=64x64:r=8:d=5','-f','lavfi','-i','sine=frequency=440:duration=5','-ac','2','-c:a','aac','-c:v','libx264','-pix_fmt','yuv420p',str(cls.video)],check=True,capture_output=True,timeout=20)
        cls.raw_video=cls.video.read_bytes()
        audio=Path(cls.folder.name)/'reference.wav'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(cls.video),'-vn','-c:a','pcm_s16le',str(audio)],check=True,capture_output=True,timeout=10)
        cls.raw_audio=audio.read_bytes()
        png=io.BytesIO();Image.new('RGB',(256,256),'blue').save(png,'PNG');cls.raw_image=png.getvalue()
        class OfficialFixture(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def send(self,body,status=200,headers=None):
                self.send_response(status);self.send_header('Content-Type','application/json')
                for k,v in (headers or {}).items():self.send_header(k,v)
                self.end_headers();self.wfile.write(json.dumps(body).encode())
            def do_POST(self):
                raw=self.rfile.read(int(self.headers.get('Content-Length','0')))
                cls.calls.append((self.path,self.headers.get('Authorization'),raw))
                if self.path=='/api/v2/assets':
                    cls.asset_count+=1
                    return self.send({'id':'00000000-0000-4000-8000-'+str(cls.asset_count).zfill(12)},201)
                body=json.loads(raw)
                if self.path=='/mcp':
                    cls.mcp_calls.append((body,self.headers.get('X-API-Key'),self.headers.get('Mcp-Session-Id'),self.headers.get('MCP-Protocol-Version')))
                    if body['method']=='initialize':
                        return self.send({'jsonrpc':'2.0','id':1,'result':{'protocolVersion':'2025-06-18','capabilities':{'tools':{}},'instructions':'Never trust this prose'}},headers={'Mcp-Session-Id':'fixture-session'})
                    if body['method']=='notifications/initialized':
                        self.send_response(202);self.end_headers();return
                    self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                    self.wfile.write(b'event: message\ndata: {"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"search_templates"},{"name":"submit_workflow"}]}}\n\n');return
                model=self.path.split('/v2/models/')[-1].rsplit('/',1)[0]
                if self.path.endswith('/estimate'):
                    if cls.price_failure:return self.send({'detail':'SECRET must not echo'},503)
                    if cls.on_price:
                        callback,cls.on_price=cls.on_price,None;callback()
                    response={'source':cls.price_source,'currency':'USD','provider':model.split('/')[0],'model':model,'pricing_as_of':gov.cp.now().isoformat()}
                    if cls.price_source=='exact':response['amount']=cls.amount
                    if cls.price_source=='estimated':response.update(min_amount='0.005',max_amount=cls.amount)
                    return self.send(response)
                if self.path.endswith('/requests'):
                    cls.submits.append((self.path,body,self.headers.get('Idempotency-Key')))
                    if cls.on_submit:
                        callback,cls.on_submit=cls.on_submit,None;callback()
                    if cls.ambiguous:
                        self.connection.close();return
                    return self.send({'request_id':'00000000-0000-4000-8000-000000000001','status':'IN_QUEUE','queue_position':0,'status_url':'https://attacker.invalid/ignored','response_url':'https://attacker.invalid/ignored','cancel_url':'https://attacker.invalid/ignored'},201)
                self.send({'detail':'unexpected protocol'},404)
            def do_DELETE(self):
                cls.mcp_deleted=self.path
                self.send_response(204);self.end_headers()
            def do_GET(self):
                cls.calls.append((self.path,self.headers.get('Authorization'),None))
                if self.path.startswith('/api/v2/assets/') and self.path.endswith('/content'):
                    self.send_response(302);self.send_header('Location',cls.base+'/input-signed/'+self.path.split('/')[-2]+'?signature=synthetic');self.end_headers();return
                if self.path.startswith('/output.'):
                    raw,mime=(cls.raw_image,'image/png') if self.path.startswith('/output.png') else (cls.raw_video,'video/mp4')
                    self.send_response(200);self.send_header('Content-Type',mime);self.end_headers();self.wfile.write(raw);return
                if '/requests/' not in self.path:
                    return self.send({'id':self.path.removeprefix('/v2/models/')})
                if self.path.endswith('/status'):
                    if cls.on_poll:
                        callback,cls.on_poll=cls.on_poll,None;callback()
                    return self.send({'request_id':'00000000-0000-4000-8000-000000000001','status':'IN_PROGRESS' if cls.poll_forever else 'COMPLETED',**({'error_type':'cancelled'} if cls.remote_cancel else {})})
                model=self.path.split('/v2/models/')[1].split('/requests/')[0]
                url=cls.base+('/output.png' if model.endswith('flux-3-image') else '/output.mp4')
                if model.startswith('ltx/'):result={'status':'completed','result':{'video_url':url}}
                elif model.startswith('bfl/'):result={'status':'Ready','result':{'sample':url}}
                elif model.startswith('minimax/'):result={'task':{'status':'succeeded','content':{'url':url}}}
                elif model.startswith('byteplus/'):result={'status':'succeeded','content':{'video_url':url}}
                else:result={'status':'completed','video':{'url':url}}
                self.send(result,headers={'X-Comfy-Credits-Used':cls.credits})
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),OfficialFixture)
        cls.base='http://127.0.0.1:'+str(cls.server.server_port)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join(2);cls.folder.cleanup()

    def setUp(self):
        fixture.StoryHTTPTests.setUp(self)
        for n,v in {'calls':[],'submits':[],'asset_count':0,'mcp_calls':[],'mcp_deleted':None,'price_source':'exact','amount':'0.01000000','credits':'2.11','price_failure':False,'ambiguous':False,'on_submit':None,'on_poll':None,'on_price':None,'poll_forever':False,'remote_cancel':False}.items():setattr(type(self),n,v)
        self.env=patch.dict(os.environ,{'COMFY_API_KEY':'synthetic-fixture-never-real','OPENBENCH_AGENT_KEY_ENVS':'COMFY_API_KEY','COMFY_ROUTER_BASE_URL':self.base,'COMFY_ROUTER_ASSET_BASE_URL':self.base,'OPENBENCH_PRODUCTION_POLICY':'hybrid_studio'})
        self.env.start();self.addCleanup(self.env.stop)
        current=store.get_resource(self.conn,self.me,self.slug,'environment','env_local_4090')
        store.save_resource(self.conn,self.me,self.slug,'environment',{'env_key':'env_local_4090','version':current['version'],'network_access':'full'})
        self.conn.commit()
        self.hybrid()
        self.card='router-ltx-2-5-pro'
        self.body={'appCode':self.card,'modelParams':{'input.duration':2}}
        self.tasks=[]
        with router._LOCK:router._CACHE.clear()

    def tearDown(self):
        for task in self.tasks:
            end=time.monotonic()+10
            while worker.openapi_query_task({'taskId':task})['status']=='RUNNING' and time.monotonic()<end:time.sleep(.02)
            with hub._OPENAPI_LOCK:
                hub._OPENAPI_TASKS.pop(task,None);hub._OPENAPI_EXECUTIONS.pop(task,None)
        fixture.StoryHTTPTests.tearDown(self)

    def hybrid(self):
        self.ok('/projects/pj_'+self.slug+'/production-policy','PUT',{'productionPolicy':'hybrid_studio'})
    def settings(self,**fields):
        current=store.get_settings(self.conn,self.me,self.slug)
        result=store.save_settings(self.conn,self.me,self.slug,{'version':current['version'],**fields});self.conn.commit();return result
    def quoted_shot(self,body=None):
        shot=self.prepare()[0]['shotId']
        result=self.ok('/shots/'+shot+'/router-quotes','POST',body or self.body)
        return shot,result
    def v2(self,path,body,headers=None):
        return self.request('/openapi/v2/'+path,method='POST',data=body,headers={'X-Project-Slug':self.slug,**(headers or {})})[:2]
    def v2done(self,task):
        self.tasks.append(task['taskId'])
        until=time.monotonic()+12
        while time.monotonic()<until:
            status,result=self.v2('query',{'taskId':task['taskId']});self.assertEqual(status,200,result)
            if result['status']!='RUNNING':
                state=db.one(self.conn,'SELECT state FROM projectops.agent_usage_reservation WHERE project_slug=%s AND request_key=%s',(self.slug,'v2:'+task['taskId']))
                if state not in ('queued','reserved','dispatched'):
                    return result
            time.sleep(.02)
        self.fail('v2 did not finish')
    def quote_v2(self,body=None,card=None):
        return self.v2('quote/ai-app/'+(card or self.card),body or {'nodeInfoList':[{'nodeId':'input','fieldName':'duration','fieldValue':2}]})

    def test_story_quote_hard_denied_soft_optin_real_persistence_audio_faststart(self):
        shot,quote=self.quoted_shot()
        self.assertFalse(quote['hard_bound']);self.assertEqual(quote['amount_usd'],'0.01000000')
        self.assertEqual(store.get_settings(self.conn,self.me,self.slug)['judge_trial_used_runs'],0)
        self.assertEqual(store.get_settings(self.conn,self.me,self.slug)['comfy_router_budget_mode'],'hard')
        forged={**self.body,'comfy_router_budget_mode':'estimate_soft','quote':{'amount_usd':0,'hard_bound':True},'judge_trial_used_runs':0}
        self.assertEqual(self.call('/shots/'+shot+'/video-generations','POST',forged)[0],409)
        self.assertEqual(self.submits,[])
        self.settings(comfy_router_budget_mode='estimate_soft',judge_trial_mode=True)
        with patch.object(worker,'comfyui',side_effect=AssertionError('no graph')),patch.object(worker,'ComfyPlatformClient',side_effect=AssertionError('no local SDK')):
            task=self.ok('/shots/'+shot+'/video-generations','POST',self.body,{'Idempotency-Key':'router-once'})
            done=self.await_task(task)
        self.assertEqual(done['status'],'SUCCEEDED',done)
        self.assertEqual(self.ok('/shots/'+shot+'/video-generations','POST',self.body,{'Idempotency-Key':'router-once'})['taskId'],task['taskId'])
        self.assertEqual(len(self.submits),1)
        code,raw,_=self.request(done['result']['videoUrl']);self.assertEqual(code,200)
        path=Path(self.folder.name)/'bounded.mp4';path.write_bytes(raw)
        self.assertLessEqual(worker._probe_video(path)['duration'],2.01)
        self.assertLess(raw.index(b'moov'),raw.index(b'mdat'))
        probe=json.loads(subprocess.run(['ffprobe','-v','error','-show_streams','-of','json',str(path)],capture_output=True,check=True,timeout=10).stdout)
        self.assertTrue(any(s.get('codec_type')=='audio' and s.get('channels')==2 for s in probe['streams']))
        self.assertEqual(store.get_settings(self.conn,self.me,self.slug)['judge_trial_used_runs'],1)
        self.assertTrue(self.submits[0][0].endswith('/requests'))
        self.assertNotIn('inputs',self.submits[0][1])
        self.assertEqual([a for p,a,r in self.calls if p.startswith('/output')],[None])

    def test_authenticated_v2_quote_submit_native_result_and_current_hard_revocation(self):
        self.settings(comfy_router_budget_mode='estimate_soft')
        code,quote=self.quote_v2();self.assertEqual(code,200,quote)
        code,task=self.v2('run/ai-app/'+self.card,{'nodeInfoList':[{'nodeId':'input','fieldName':'duration','fieldValue':2}]});self.assertEqual(code,200,task)
        done=self.v2done(task);self.assertEqual(done['status'],'SUCCESS',done)
        self.assertIsNone(done['compiledWorkflow'])
        # Hold dispatcher launch only; actual executor must reread current permission.
        with patch.object(hub,'_execute_openapi_task') as launch:
            code,task=self.v2('run/ai-app/'+self.card,{'nodeInfoList':[{'nodeId':'input','fieldName':'duration','fieldValue':2}]})
            end=time.monotonic()+2
            while not launch.called and time.monotonic()<end:time.sleep(.01)
            args=launch.call_args.args
        self.settings(comfy_router_budget_mode='hard')
        before=len(self.submits);hub._execute_openapi_task(*args)
        self.assertEqual(self.v2done(task)['status'],'FAILED');self.assertEqual(len(self.submits),before)

    def test_unknown_failed_expired_changed_quote_and_body_forgery_never_submit(self):
        self.settings(comfy_router_budget_mode='estimate_soft',judge_trial_mode=True)
        for source in ('unknown','new_source'):
            type(self).price_source=source
            self.assertNotEqual(self.quote_v2()[0],200)
        type(self).price_source='exact';type(self).price_failure=True
        self.assertNotEqual(self.quote_v2()[0],200)
        type(self).price_failure=False
        self.assertEqual(self.quote_v2()[0],200)
        with router._LOCK:
            for entry in router._CACHE.values():entry['expires_at']=gov.cp.now()-dt.timedelta(seconds=1)
        code,task=self.v2('run/ai-app/'+self.card,{'nodeInfoList':[{'nodeId':'input','fieldName':'duration','fieldValue':2}],'quote':{'hard_bound':True},'comfy_router_budget_mode':'estimate_soft'})
        self.assertEqual(code,200,task);self.assertEqual(self.v2done(task)['status'],'FAILED')
        self.assertEqual(self.submits,[])
        self.assertEqual(store.get_settings(self.conn,self.me,self.slug)['judge_trial_used_runs'],0)
        self.assertEqual(self.quote_v2()[0],200)
        code,task=self.v2('run/ai-app/'+self.card,{'nodeInfoList':[{'nodeId':'input','fieldName':'duration','fieldValue':3}]})
        self.assertEqual(self.v2done(task)['status'],'FAILED');self.assertEqual(self.submits,[])

    def test_estimate_interval_overage_and_admin_versioned_consent(self):
        viewer=type(self.me)(self.me.actor_id,self.me.name,'viewer')
        with self.assertRaises(ValueError):store.save_settings(self.conn,viewer,self.slug,{'version':1,'comfy_router_budget_mode':'estimate_soft'})
        type(self).price_source='estimated';type(self).amount='0.01500001';type(self).credits='21.1'
        self.settings(comfy_router_budget_mode='estimate_soft')
        self.assertTrue(any(r['snapshot'].get('comfy_router_budget_mode')=='estimate_soft' for r in store.history(self.conn,self.me,self.slug,'settings',self.slug)))
        code,quote=self.quote_v2();self.assertEqual(code,200,quote)
        self.assertEqual(quote['data']['reservation_usd'],'0.0151')
        code,task=self.v2('run/ai-app/'+self.card,{'nodeInfoList':[{'nodeId':'input','fieldName':'duration','fieldValue':2}]})
        self.assertEqual(self.v2done(task)['status'],'SUCCESS')
        row=db.one(self.conn,'SELECT to_jsonb(r) FROM projectops.agent_usage_reservation r WHERE project_slug=%s',(self.slug,))
        self.assertFalse(row['quote_hard_bound']);self.assertEqual(row['ceiling_cost_usd'],.0151)
        self.assertEqual(row['reported_cost_usd'],.1);self.assertEqual(row['accounted_cost_usd'],.1)
        ledger=db.one(self.conn,'SELECT to_jsonb(l) FROM projectops.agent_usage_ledger l WHERE project_slug=%s',(self.slug,))
        self.assertIsNone(ledger['observed_cost_usd']);self.assertEqual(float(ledger['meta']['reported_cost_usd']),.1)
        self.assertFalse(ledger['meta']['reported_cost_is_invoice'])
        self.assertEqual(ledger['estimated_cost_usd'],.0151)
        self.assertEqual(ledger['reported_cost_usd'],.1)
        self.assertEqual(store.analytics(self.conn,self.me,self.slug)[0]['reported_cost_usd'],.1)

    def test_story_batch_reserves_tenth_before_submit_and_eleventh_is_denied(self):
        self.settings(comfy_router_budget_mode='estimate_soft',judge_trial_mode=True)
        shots=self.prepare()[:2]
        for s in shots:self.ok('/shots/'+s['shotId']+'/router-quotes','POST',self.body)
        ctx=gov.media_context(self.me,self.slug)
        gov.generation_admit(self.conn,ctx,[('prior'+str(i),gov.cp.digest(i)) for i in range(9)]);self.conn.commit()
        body={**self.body,'shotIds':[s['shotId'] for s in shots]}
        code,_=self.call('/episodes/'+self.ep+'/shot-video-generations','POST',body)
        self.assertEqual(code,409);self.assertEqual(self.submits,[])
        self.assertEqual(store.get_settings(self.conn,self.me,self.slug)['judge_trial_used_runs'],9)
        task=self.ok('/shots/'+shots[0]['shotId']+'/video-generations','POST',self.body)
        self.assertEqual(self.await_task(task)['status'],'SUCCEEDED')
        self.assertEqual(self.call('/shots/'+shots[1]['shotId']+'/video-generations','POST',self.body)[0],409)
        self.assertEqual(len(self.submits),1)
        self.assertEqual(store.get_settings(self.conn,self.me,self.slug)['judge_trial_used_runs'],10)

    def test_ambiguous_submit_poll_cancel_and_timeout_do_not_retry(self):
        self.settings(comfy_router_budget_mode='estimate_soft')
        self.assertEqual(self.quote_v2()[0],200)
        type(self).ambiguous=True
        _,task=self.v2('run/ai-app/'+self.card,{'nodeInfoList':[{'nodeId':'input','fieldName':'duration','fieldValue':2}]})
        self.assertEqual(self.v2done(task)['status'],'FAILED');self.assertEqual(len(self.submits),1)
        row=db.one(self.conn,'SELECT state FROM projectops.agent_usage_reservation WHERE project_slug=%s',(self.slug,));self.assertEqual(row,'uncertain')
        type(self).ambiguous=False;type(self).remote_cancel=True
        _,task=self.v2('run/ai-app/'+self.card,{'nodeInfoList':[{'nodeId':'input','fieldName':'duration','fieldValue':2}]})
        self.assertEqual(self.v2done(task)['status'],'FAILED');self.assertEqual(len(self.submits),2)

    def test_actual_queued_poll_timeout_is_one_submission_and_uncertain(self):
        self.settings(comfy_router_budget_mode='estimate_soft')
        type(self).poll_forever=True
        # The card timeout also covers the governed submit, whose authority checks open fresh PG connections
        # (~0.1 s each on Windows); a sub-second budget expires before the first /status poll.
        card=worker.load_studio_card(self.card);card['engine_config']['timeout']=3
        with hub._OPENAPI_LOCK:hub._OPENAPI_CARDS[self.card]=(card,None)
        self.addCleanup(lambda:hub._OPENAPI_CARDS.pop(self.card,None))
        self.assertEqual(self.quote_v2()[0],200)
        _,task=self.v2('run/ai-app/'+self.card,{'nodeInfoList':[{'nodeId':'input','fieldName':'duration','fieldValue':2}]})
        done=self.v2done(task)
        self.assertEqual(done['status'],'FAILED')
        self.assertEqual(len(self.submits),1)
        self.assertTrue(any(p.endswith('/status') for p,a,b in self.calls))
        self.assertFalse(any('/requests/' in p and not p.endswith('/status') for p,a,b in self.calls))
        self.assertEqual(db.one(self.conn,'SELECT state FROM projectops.agent_usage_reservation WHERE project_slug=%s',(self.slug,)),'uncertain')


    def test_actual_submit_rechecks_soft_permission_and_credential_after_begin(self):
        self.settings(comfy_router_budget_mode='estimate_soft',judge_trial_mode=True)
        self.assertEqual(self.quote_v2()[0],200)
        original=router._check
        changed=False
        def check(head,url=None):
            nonlocal changed
            if url and url.endswith('/requests') and not changed:
                changed=True
                self.settings(comfy_router_budget_mode='hard')
            return original(head,url)
        with patch.object(router,'_check',side_effect=check):
            _,task=self.v2('run/ai-app/'+self.card,{'nodeInfoList':[{'nodeId':'input','fieldName':'duration','fieldValue':2}]})
            self.assertEqual(self.v2done(task)['status'],'FAILED')
        self.assertTrue(changed);self.assertEqual(self.submits,[])
        self.settings(comfy_router_budget_mode='estimate_soft')
        with patch.dict(os.environ,{'COMFY_API_KEY':'synthetic-rotated-key'}):
            _,task=self.v2('run/ai-app/'+self.card,{'nodeInfoList':[{'nodeId':'input','fieldName':'duration','fieldValue':2}]})
            self.assertEqual(self.v2done(task)['status'],'FAILED')
        self.assertEqual(self.submits,[])

    def test_poll_revocation_blocks_result_download_without_remote_refund(self):
        self.settings(comfy_router_budget_mode='estimate_soft',judge_trial_mode=True)
        self.assertEqual(self.quote_v2()[0],200)
        def revoke():
            story.store(self.conn,'policy_'+self.slug,'production_policy',{'productionPolicy':'open_weights_only'},self.slug)
            self.conn.commit()
        type(self).on_poll=revoke
        _,task=self.v2('run/ai-app/'+self.card,{'nodeInfoList':[{'nodeId':'input','fieldName':'duration','fieldValue':2}]})
        self.assertEqual(self.v2done(task)['status'],'FAILED')
        self.assertEqual(len(self.submits),1)
        self.assertFalse(any(p.startswith('/output.') for p,a,b in self.calls))
        self.assertEqual(store.get_settings(self.conn,self.me,self.slug)['judge_trial_used_runs'],1)
        self.assertEqual(db.one(self.conn,'SELECT state FROM projectops.agent_usage_reservation WHERE project_slug=%s',(self.slug,)),'uncertain')

    def test_reviewed_allocation_id_preserves_exact_story_router_inputs(self):
        self.settings(comfy_router_budget_mode='estimate_soft',judge_trial_mode=True)
        shot=self.prepare()[0]['shotId']
        body={'appCode':self.card}
        self.ok('/shots/'+shot+'/router-quotes','POST',body)
        with patch.object(worker,'probe_local_comfy_status',side_effect=AssertionError('Router must not probe local Comfy')):
            allocation=self.ok('/projects/pj_'+self.slug+'/episodes/'+self.ep+'/shots:plan-allocation','POST',{'appCode':self.card,'shotIds':[shot]})
        self.assertEqual(allocation['readiness_scope'],'configuration_and_inputs')
        result=self.ok('/episodes/'+self.ep+'/shot-video-generations','POST',{'allocationId':allocation['allocationId'],'shotIds':[shot]})
        self.assertEqual(self.await_task({'taskId':result['taskIds'][0]})['status'],'SUCCEEDED')
        self.assertEqual(len(self.submits),1)
        self.assertEqual(self.call('/episodes/'+self.ep+'/shot-video-generations','POST',{'allocationId':allocation['allocationId'],'shotIds':[shot]})[0],409)

    def test_official_mcp_streamable_discovery_has_no_generation_or_authority_grant(self):
        from project_assistant.studio import comfy_mcp
        ctx=gov.media_context(self.me,self.slug)
        card=worker.load_studio_card(self.card)
        self.settings(judge_trial_mode=True)
        with patch.dict(os.environ,{'COMFY_MCP_URL':self.base+'/mcp'}):
            self.assertEqual(comfy_mcp.configuration_status()['connection_state'],'not_checked')
            result=comfy_mcp.discover(ctx,card)
        self.assertEqual(result['connection_state'],'reachable')
        self.assertFalse(result['generation_enabled'])
        self.assertEqual(result['tools'],['search_templates','submit_workflow'])
        self.assertEqual([c[0]['method'] for c in self.mcp_calls],['initialize','notifications/initialized','tools/list'])
        self.assertTrue(all(c[1]=='synthetic-fixture-never-real' for c in self.mcp_calls))
        self.assertEqual(self.mcp_calls[-1][2:],('fixture-session','2025-06-18'))
        self.assertEqual(self.mcp_deleted,'/mcp')
        self.assertNotIn('instructions',result)
        self.assertEqual(store.get_settings(self.conn,self.me,self.slug)['judge_trial_used_runs'],0)
        self.assertEqual(self.submits,[])
        current=store.get_resource(self.conn,self.me,self.slug,'environment','env_local_4090')
        store.save_resource(self.conn,self.me,self.slug,'environment',{'env_key':'env_local_4090','version':current['version'],'network_access':'offline'});self.conn.commit()
        with patch.dict(os.environ,{'COMFY_MCP_URL':self.base+'/mcp'}),self.assertRaises(ValueError):
            comfy_mcp.discover(ctx,card)
        self.assertEqual(len(self.mcp_calls),3)

    def test_router_tool_sponsor_uses_existing_private_m8_proposal_gate(self):
        from project_assistant import studio_tools, tools, story_media_adapter as adapter, orchestrator as cp
        from project_docs import http
        self.settings(comfy_router_budget_mode='estimate_soft',judge_trial_mode=True)
        shot=self.prepare()[0]['shotId']
        self.ok('/shots/'+shot+'/router-quotes','POST',{'appCode':self.card})
        allocation=self.ok('/projects/pj_'+self.slug+'/episodes/'+self.ep+'/shots:plan-allocation','POST',{'appCode':self.card,'shotIds':[shot]})
        ctx=tools.ToolContext(http.open_connection,self.slug,self.me,Path('.'),None)
        gov.install(ctx)
        # Trusted approved sponsor seam; shared tool approval policy itself is covered by existing tool tests.
        result=studio_tools.studio_dispatch_shot(ctx,self.conn,{'episode_id':self.ep,'shot_ids':[shot],'allocation_id':allocation['allocationId']})
        self.conn.commit()
        run=result['runs'][0]['runId']
        try:
            for action in ctx.post_commit_actions:action()
            until=time.monotonic()+20
            gate=None
            while time.monotonic()<until:
                code,board,_=self.request('/projects/api/'+self.slug+'/orchestration/board')
                self.assertEqual(code,200,board)
                gate=next((g for g in board['needs_you'] if g.get('run_id')==run and g.get('proposals')),None)
                if gate:break
                time.sleep(.05)
            self.assertIsNotNone(gate,db.tasks(self.conn,self.slug,run))
            self.assertEqual(len(gate['proposals']),1)
            self.assertIsNone(self.ok('/shots/'+shot)['selectedVideoUrl'])
            self.assertEqual(len(self.submits),1)
            self.assertEqual(adapter.profile('studio:closed')['runtime_kind'],'server_media')
            self.assertEqual(store.get_settings(self.conn,self.me,self.slug)['judge_trial_used_runs'],1)
        finally:
            cp.cancel_run(self.conn,self.me,self.slug,run);self.conn.commit()
            until=time.monotonic()+3
            while run in adapter._ACTIVE and time.monotonic()<until:time.sleep(.05)

    def test_concurrent_router_exact_quotes_compete_for_one_project_judge_slot(self):
        from concurrent.futures import ThreadPoolExecutor
        from project_docs import http
        self.settings(comfy_router_budget_mode='estimate_soft',judge_trial_mode=True)
        self.assertEqual(self.quote_v2()[0],200)
        ctx=gov.media_context(self.me,self.slug)
        gov.generation_admit(self.conn,ctx,[('prior'+str(i),gov.cp.digest(i)) for i in range(9)]);self.conn.commit()
        card,_,nodes,policy,_,_=hub._prepare_openapi_inputs(self.card,{'nodeInfoList':[{'nodeId':'input','fieldName':'duration','fieldValue':2}]},'hybrid_studio')
        request={'task':{'production_policy':policy},'values':{f"{n['nodeId']}.{n['fieldName']}":n['fieldValue'] for n in nodes}}
        barrier=threading.Barrier(2)
        def admit(name):
            context=gov.media_context(self.me,self.slug,accounting_session_key=name)
            barrier.wait(timeout=5)
            try:
                with http.open_connection() as conn:
                    gov.prepare_operation(conn,context,request_key=name,card=card,operation_digest=gov.cp.digest(name),router_request=request)
                return 'admitted'
            except gov.AdmissionError:return 'denied'
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(admit,['router-a','router-b']))
        self.assertEqual(sorted(results),['admitted','denied'])
        self.assertEqual(store.get_settings(self.conn,self.me,self.slug)['judge_trial_used_runs'],10)
        self.assertEqual(db.one(self.conn,'SELECT count(*) FROM projectops.agent_usage_reservation WHERE project_slug=%s',(self.slug,)),1)
        self.assertEqual(self.submits,[])

    def test_all_seven_official_native_http_output_shapes_are_executable(self):
        self.settings(comfy_router_budget_mode='estimate_soft',judge_trial_mode=True)
        references={}
        for name,raw,mime in [('image',self.raw_image,'image/png'),('video',self.raw_video,'video/mp4')]:
            code,payload,_=self.request('/openapi/v2/media/upload/binary',method='POST',raw=raw,headers={'X-Project-Slug':self.slug,'Content-Type':mime})
            self.assertEqual(code,200,payload);references[name]=payload['data']['fileName']
        with patch.object(worker,'comfyui',side_effect=AssertionError('no local graph')),patch.object(worker,'ComfyPlatformClient',side_effect=AssertionError('no local SDK')):
            for model in router.MODELS:
                with self.subTest(model=model):
                    card='router-'+model.split('/')[1]
                    body={'nodeInfoList':[{'nodeId':'input','fieldName':'prompt','fieldValue':'Original synthetic performance'}]}
                    if model.startswith('higgsfield/'):
                        body['nodeInfoList'] += [{'nodeId':'input','fieldName':'image_1','fieldValue':references['image']},{'nodeId':'input','fieldName':'video_url','fieldValue':references['video']}]
                    code,quote=self.quote_v2(body,card);self.assertEqual(code,200,quote)
                    code,task=self.v2('run/ai-app/'+card,body);self.assertEqual(code,200,task)
                    done=self.v2done(task);self.assertEqual(done['status'],'SUCCESS',done)
                    self.assertEqual(done['results'][0]['outputType'],'png' if model=='bfl/flux-3-image' else 'mp4')
        self.assertEqual(len(self.submits),7)
        self.assertEqual(len({s[2] for s in self.submits}),7)
        self.assertEqual(store.get_settings(self.conn,self.me,self.slug)['judge_trial_used_runs'],7)
        self.assertTrue(all(a is None for p,a,b in self.calls if p.startswith('/output.')))

    def test_authenticated_v2_concurrent_idempotency_replay_is_one_generation(self):
        from concurrent.futures import ThreadPoolExecutor
        self.settings(comfy_router_budget_mode='estimate_soft',judge_trial_mode=True)
        self.assertEqual(self.quote_v2()[0],200)
        body={'nodeInfoList':[{'nodeId':'input','fieldName':'duration','fieldValue':2}]}
        headers={'Idempotency-Key':'same-logical-router-request'}
        barrier=threading.Barrier(2)
        def call(_):
            barrier.wait(timeout=5)
            return self.v2('run/ai-app/'+self.card,body,headers)
        with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(call,range(2)))
        for code,result in responses:self.assertEqual(code,200,result)
        self.assertEqual(responses[0][1]['taskId'],responses[1][1]['taskId'])
        self.assertEqual(self.v2done(responses[0][1])['status'],'SUCCESS')
        code,replay=self.v2('run/ai-app/'+self.card,body,headers)
        self.assertEqual(code,200,replay);self.assertEqual(replay['taskId'],responses[0][1]['taskId'])
        changed={'nodeInfoList':[{'nodeId':'input','fieldName':'duration','fieldValue':3}]}
        self.assertEqual(self.v2('run/ai-app/'+self.card,changed,headers)[0],409)
        self.assertEqual(len(self.submits),1)
        self.assertEqual(store.get_settings(self.conn,self.me,self.slug)['judge_trial_used_runs'],1)
        self.assertEqual(db.one(self.conn,'SELECT count(*) FROM projectops.agent_usage_ledger WHERE project_slug=%s',(self.slug,)),1)

    def test_actual_story_cancel_during_poll_preserves_judge_and_blocks_download(self):
        self.settings(comfy_router_budget_mode='estimate_soft',judge_trial_mode=True)
        shot,_=self.quoted_shot()
        waiting=threading.Event();release=threading.Event()
        def hold():
            waiting.set()
            if not release.wait(5):raise AssertionError('fixture poll was not released')
        type(self).on_poll=hold
        task=self.ok('/shots/'+shot+'/video-generations','POST',self.body)
        try:
            self.assertTrue(waiting.wait(5))
            canceled=self.ok('/tasks/'+task['taskId']+'/cancellations','POST',{})
            self.assertEqual(canceled['status'],'CANCELED')
        finally:release.set()
        until=time.monotonic()+5
        while time.monotonic()<until:
            state=db.one(self.conn,'SELECT state FROM projectops.agent_usage_reservation WHERE project_slug=%s',(self.slug,))
            if state=='uncertain':break
            time.sleep(.02)
        self.assertEqual(state,'uncertain')
        self.assertEqual(len(self.submits),1)
        self.assertFalse(any(p.startswith('/output.') for p,a,b in self.calls))
        self.assertEqual(store.get_settings(self.conn,self.me,self.slug)['judge_trial_used_runs'],1)

    def test_quote_and_actual_submit_bind_the_same_current_credential(self):
        self.settings(comfy_router_budget_mode='estimate_soft')
        def rotate():os.environ['COMFY_API_KEY']='synthetic-rotated-during-network'
        type(self).on_price=rotate
        self.assertNotEqual(self.quote_v2()[0],200)
        with router._LOCK:self.assertEqual(router._CACHE,{})
        os.environ['COMFY_API_KEY']='synthetic-fixture-never-real'
        self.assertEqual(self.quote_v2()[0],200)
        original=router._check
        changed=False
        def check(head,url=None):
            nonlocal changed
            if url and url.endswith('/requests') and not changed:
                changed=True;rotate()
            return original(head,url)
        with patch.object(router,'_check',side_effect=check):
            _,task=self.v2('run/ai-app/'+self.card,{'nodeInfoList':[{'nodeId':'input','fieldName':'duration','fieldValue':2}]})
            self.assertEqual(self.v2done(task)['status'],'FAILED')
        self.assertTrue(changed);self.assertEqual(self.submits,[])

    def test_open_only_local_admission_does_not_require_unused_router_credential_mount(self):
        self.ok('/projects/pj_'+self.slug+'/production-policy','PUT',{'productionPolicy':'open_weights_only'})
        current=store.get_resource(self.conn,self.me,self.slug,'environment','env_local_4090')
        store.save_resource(self.conn,self.me,self.slug,'environment',{'env_key':'env_local_4090','version':current['version'],'network_access':'restricted','config':{**current['config'],'vault_keys':[]}})
        self.conn.commit()
        card=worker.load_studio_card('ltx25-cinema')
        ctx=gov.media_context(self.me,self.slug)
        with patch.dict(os.environ,{'COMFY_API_KEY':'synthetic-unused-router-key','OPENBENCH_AGENT_KEY_ENVS':'','COMFY_PLATFORM':'','COMFY_BASE_URL':''}):
            gov.prepare_operation(self.conn,ctx,request_key='local-only',card=card,operation_digest=gov.cp.digest(card))
            row=db.one(self.conn,'SELECT to_jsonb(r) FROM projectops.agent_usage_reservation r WHERE project_slug=%s',(self.slug,))
            self.assertEqual(row['state'],'queued')
            self.assertEqual(row['provider_name'],'comfy_local')
            self.assertIsNone(row['ceiling_cost_usd'])
            self.assertEqual(gov.media_destination(card),'http://127.0.0.1:8188')
        self.conn.commit()
        self.assertEqual(self.submits,[])

    def test_reference_upload_and_expanded_private_grants_before_quote(self):
        self.settings(comfy_router_budget_mode='estimate_soft')
        card='router-minimax-h3'
        code,upload,_=self.request('/openapi/v2/media/upload/binary',method='POST',raw=self.raw_image,headers={'X-Project-Slug':self.slug,'Content-Type':'image/png'})
        self.assertEqual(code,200,upload);ref=upload['data']['fileName']
        body={'nodeInfoList':[{'nodeId':'input','fieldName':'reference_image','fieldValue':ref}]}
        for field,raw,mime in [('base_video',self.raw_video,'video/mp4'),('reference_audio',self.raw_audio,'audio/wav')]:
            code,uploaded,_=self.request('/openapi/v2/media/upload/binary',method='POST',raw=raw,headers={'X-Project-Slug':self.slug,'Content-Type':mime})
            self.assertEqual(code,200,uploaded)
            body['nodeInfoList'].append({'nodeId':'input','fieldName':field,'fieldValue':uploaded['data']['fileName']})
        self.assertEqual(self.quote_v2(body,card)[0],200)
        self.assertTrue(any(p=='/api/v2/assets' for p,a,b in self.calls))
        before=len(self.calls)
        stolen=copy.deepcopy(body);stolen['nodeInfoList'][0]['fieldValue']='a'*64+'.png'
        self.assertEqual(self.quote_v2(stolen,card)[0],404);self.assertEqual(len(self.calls),before)
        _,task=self.v2('run/ai-app/'+card,body)
        done=self.v2done(task);self.assertEqual(done['status'],'SUCCESS',done)
        content=self.submits[0][1]['content']
        self.assertEqual([c.get('role') for c in content],[None,'reference_image','base_video','reference_audio'])
        self.assertTrue(content[1]['image_url']['url'].endswith('signature=synthetic'))
        self.assertNotEqual(content[1]['image_url']['url'],content[2]['video_url']['url'])
        self.assertEqual(self.asset_count,3)
        self.assertFalse(any('attacker.invalid' in p for p,a,b in self.calls))
        self.assertNotIn('signature',json.dumps(store.analytics(self.conn,self.me,self.slug)))
