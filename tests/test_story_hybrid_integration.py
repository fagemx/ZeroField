"""Real Story HTTP/PostgreSQL/FFmpeg; loopback substitutes commercial inference.

Structural/chain cases additionally substitute local model inference (no GPU),
while preparation, M8 leases/proposals/review and media persistence remain real.
"""
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

import test_story_openapi as fixture
from project_docs import repository as repo, story_openapi as story
from project_assistant import limb_worker as worker, story_media_adapter as adapter, orchestrator as cp, orchestration_store as db


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "dedicated PostgreSQL URI required")
class StoryHybridIntegrationTests(unittest.TestCase):
    request = fixture.StoryHTTPTests.request
    call = fixture.StoryHTTPTests.call
    ok = fixture.StoryHTTPTests.ok
    prepare = fixture.StoryHTTPTests.prepare
    await_task = fixture.StoryHTTPTests.await_task

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(prefix="spec07-fixture-")
        cls.video = Path(cls.folder.name) / "synthetic.mp4"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=8:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(cls.video)], check=True, capture_output=True, timeout=20)
        cls.raw = cls.video.read_bytes()
        cls.submits = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def send(self, value):
                raw = json.dumps(value).encode(); self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(raw)
            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                if self.path.endswith("/media/upload/binary"):
                    return self.send({"code": 0, "data": {"fileName": "fixture-reference"}})
                body = json.loads(raw)
                if self.path.endswith("/query"):
                    return self.send({"code": 0, "status": "SUCCESS", "results": [{"url": cls.base + "/synthetic.mp4", "outputType": "mp4"}]})
                cls.submits.append((self.path, body))
                self.send({"code": 0, "status": "RUNNING", "taskId": "synthetic-inference"})
            def do_GET(self):
                self.send_response(200); self.send_header("Content-Type", "video/mp4"); self.end_headers(); self.wfile.write(cls.raw)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = "http://127.0.0.1:" + str(cls.server.server_port)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True); cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(2); cls.folder.cleanup()

    def setUp(self):
        fixture.StoryHTTPTests.setUp(self)
        from governance_fixture import authorize_synthetic_media
        authorize_synthetic_media(self)
        type(self).submits = []
        self.provider_env = patch.dict(os.environ, {"OPENBENCH_PRODUCTION_POLICY": "hybrid_studio", "SEEDANCE_API_URL": self.base + "/vendor", "SEEDANCE_API_KEY": "synthetic-fixture-not-real", "RUNNINGHUB_API_URL": self.base + "/cloud", "RUNNINGHUB_API_KEY": "synthetic-fixture-not-real"})
        self.provider_env.start()
        self.health = patch.object(worker, "probe_local_comfy_status", return_value={"online": True}); self.health.start()
        self.runs = []

    def tearDown(self):
        self.conn.rollback()
        for run in self.runs:
            try:
                cp.cancel_run(self.conn, self.me, self.slug, run); self.conn.commit()
            except ValueError:
                self.conn.rollback()
        deadline = time.monotonic() + 3
        while any(r in adapter._ACTIVE for r in self.runs) and time.monotonic() < deadline: time.sleep(.1)
        self.health.stop(); self.provider_env.stop()
        fixture.StoryHTTPTests.tearDown(self)

    def hybrid(self):
        return self.ok(f"/projects/pj_{self.slug}/production-policy", "PUT", {"productionPolicy": "hybrid_studio"})

    def nested(self, identifier=None):
        root = f"/projects/pj_{self.slug}/episodes/{self.ep}"
        return root + ("/shots/" + identifier + ":escalate" if identifier else "/shots:plan-allocation")

    def escalate(self, identifier, body):
        result = self.ok(self.nested(identifier), "POST", body)
        self.runs.append(result["runId"])
        return result

    def gate(self, run_id, count=1):
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            code, board, _ = self.request(f"/projects/api/{self.slug}/orchestration/board")
            self.assertEqual(code, 200, board)
            found = next((g for g in board["needs_you"] if g.get("run_id") == run_id and len(g.get("proposals", [])) >= count), None)
            if found: return found
            time.sleep(.1)
        tasks = db.tasks(self.conn, self.slug, run_id)
        self.fail("No media review gate: " + repr([(t['status'],t.get('error'),[(d['status'],d.get('error')) for d in db.dispatches(self.conn,self.slug,t['id'])]) for t in tasks]))

    def resolve(self, gate, proposal=None):
        chosen = proposal or gate["proposals"][0]
        code, payload, _ = self.request(f"/projects/api/{self.slug}/orchestration/gates/{gate['gate_id']}/resolve", method="POST", data={"client_request_id": os.urandom(8).hex(), "resolution": {"proposal_id": chosen["id"]}})
        self.assertEqual(code, 200, payload)
        return payload

    def image(self, identifier, *, cast_reference=False):
        from PIL import Image
        image = io.BytesIO(); Image.new('RGB', (16,16), 'green').save(image, format='PNG')
        aid = repo.put_asset(self.conn, self.slug, data=image.getvalue(), content_type='image/png', actor_id=self.actor)
        if cast_reference:
            row = next(r for r in story.table_rows(self.conn, self.slug, 'soul-cast') if r['cells'][0] == 'CAST-01')
        else:
            _, row = story.find_row(self.conn, identifier, 'shot')
        story.mutate_row(self.conn, self.me, self.slug, row['tabKey'], row['rid'], {story.media_column(row,'image'):f'![Image](/projects/api/{self.slug}/assets/{aid})'})
        self.conn.commit()

    def local_inference(self, task, config, head):
        return head.upload(task, self.raw, "video/mp4")

    def test_graphless_story_http_vendor_candidate_writeback_and_default_denial(self):
        selected = self.prepare()[0]; identifier = selected['shotId']
        path = f'/shots/{identifier}/video-generations'
        self.assertEqual(self.call(path,'POST',{'appCode':'seedance-20-pro','productionPolicy':'hybrid_studio'})[0],422)
        self.assertEqual(self.call(path,'POST',{'appCode':'seedance-20-pro'})[0],422)
        self.assertEqual(self.submits,[])
        self.hybrid()
        with patch.object(worker,'ComfyPlatformClient',side_effect=AssertionError('Comfy unavailable')), patch.object(worker,'comfyui',side_effect=AssertionError('Comfy unavailable')):
            done = self.await_task(self.ok(path,'POST',{'appCode':'SEEDANCE_2_FAST_MULTIMODAL_VIDEO','modelParams':{'duration':1}}))
        self.assertEqual(done['status'],'SUCCEEDED',done)
        self.assertTrue(done['result']['selected'])
        self.assertTrue(self.submits[0][0].endswith('/vendor/run'))
        takes=self.ok('/shots/'+identifier+'/videos')['items'];self.assertTrue(takes[-1]['selected'])
        code, raw, _=self.request(takes[-1]['url']); self.assertEqual(code,200)
        output=Path(self.folder.name)/'story.mp4';output.write_bytes(raw)
        self.assertLessEqual(worker._probe_video(output)['duration'],1.01)
        self.assertLess(raw.index(b'moov'),raw.index(b'mdat'))
        self.assertEqual(self.request(story.BASE+path,method='POST',data={'appCode':'seedance-20-pro'},authenticated=False)[0],401)
        with patch.dict(os.environ,{'OPENBENCH_PRODUCTION_POLICY':'open_weights_only'}):
            self.assertEqual(self.call(f'/projects/pj_{self.slug}/production-policy','PUT',{'productionPolicy':'hybrid_studio'})[0],409)
        self.assertEqual(story.resolve_app('SEEDANCE_2_FAST_MULTIMODAL_VIDEO','video','open_weights_only')['card_id'],'h3-reference')

    def test_allocation_snapshot_actual_batch_policy_scope_and_stale_guard(self):
        selected=self.prepare()[:2];ids=[s['shotId'] for s in selected];self.hybrid()
        with patch.object(worker,'probe_local_comfy_status',return_value={'online':False}):
            allocation=self.ok(self.nested(),'POST',{'budgetMode':'hybrid_balanced','shotIds':ids})
        self.assertTrue(all(a['assignedCardId']=='seedance-20-pro' for a in allocation['allocations']))
        self.assertIsNone(allocation['summary']['estimatedCloudCredits'])
        body={'allocationId':allocation['allocationId'],'shotIds':ids}
        group=self.ok(f'/episodes/{self.ep}/shot-video-generations','POST',body)
        for task in group['taskIds']:
            self.assertEqual(self.await_task({'taskId':task})['status'],'SUCCEEDED')
            self.assertEqual(story.record(self.conn,task)['_job']['card']['card_id'],'seedance-20-pro')
        self.assertEqual(self.call(f'/episodes/{self.ep}/shot-video-generations','POST',body)[0],409)
        allocation=self.ok(self.nested(),'POST',{'appCode':'seedance-20-pro','shotIds':ids})
        self.ok('/shots/'+ids[0],'PATCH',{'description':'Newer authoritative prompt'})
        self.assertEqual(self.call(f'/episodes/{self.ep}/shot-video-generations','POST',{'allocationId':allocation['allocationId'],'shotIds':ids})[0],409)
        other=self.ok('/projects','POST',{'title':'Other production','slug':self.slug+'-i'});self.extra_projects.append(self.slug+'-i')
        wrong=f"/projects/{other['projectId']}/episodes/{self.ep}/shots:plan-allocation"
        self.assertEqual(self.call(wrong,'POST',{})[0],404)
        ep2=self.ok(f'/projects/pj_{self.slug}/episodes','POST',{'title':'Other episode'})
        self.assertEqual(self.call(self.nested(ids[0]).replace(self.ep,ep2['episodeId']),'POST',{'strategy':'closed_hero'})[0],404)

    def test_structural_preparation_real_ffmpeg_and_review_before_writeback(self):
        selected=self.prepare()[0];identifier=selected['shotId'];before=self.ok('/shots/'+identifier)['selectedVideoUrl']
        self.image(identifier, cast_reference=True)
        seen=[]
        def infer(task,config,head):
            context=worker.resolve_studio_context(task);seen.append(context)
            self.assertTrue(context['source_video']);self.assertTrue(context['frame_sheet'])
            return self.local_inference(task,config,head)
        with patch.object(worker,'comfyui',side_effect=infer):
            run=self.escalate(identifier,{'strategy':'open_structural_lock'})
            gate=self.gate(run['runId'])
            self.assertEqual(self.ok('/shots/'+identifier)['selectedVideoUrl'],before)
            tasks=db.tasks(self.conn,self.slug,run['runId']);self.assertEqual(sum(t['status']=='completed' for t in tasks),2)
            self.resolve(gate)
        self.assertEqual(len(seen),1)
        self.assertTrue(self.ok('/shots/'+identifier)['selectedVideoUrl'])
        usage=db.many(self.conn,'SELECT usage_kind FROM projectops.agent_usage_ledger WHERE project_slug=%s',(self.slug,))
        self.assertEqual(usage.count('frame_prep'),2)
        self.assertIn('video_gen',usage)

    def test_real_m8_ab_candidates_winner_and_internal_principal_cannot_be_forged(self):
        identifier=self.prepare()[0]['shotId'];self.image(identifier, cast_reference=True);self.hybrid()
        with patch.object(worker,'comfyui',side_effect=self.local_inference):
            run=self.escalate(identifier,{'strategy':'ab_race'});gate=self.gate(run['runId'],2)
            self.assertIsNone(self.ok('/shots/'+identifier)['selectedVideoUrl'])
            self.assertEqual(gate['kind'],'race_select')
            proposal=gate['proposals'][0]
            self.assertEqual(self.request(f"/projects/api/{self.slug}/assistant/proposals/{proposal['id']}/apply",method='POST',data={})[0],409)
            result=self.resolve(gate,proposal)
            self.assertTrue(result['winning_dispatch_id'])
        self.assertTrue(self.ok('/shots/'+identifier)['selectedVideoUrl'])
        code,payload,_=self.request(f'/projects/api/{self.slug}/orchestration/runs',method='POST',data={'client_request_id':'forged','objective':'forged','agent_key':'studio:closed'})
        self.assertEqual(code,403,payload)
        with patch.object(adapter,'wake'):
            queued=self.escalate(identifier,{'strategy':'closed_hero'})
        self.assertIsNone(cp.claim_dispatch(self.conn,str(adapter._PRINCIPAL),list(adapter.KEYS),allowed_projects=[self.slug]))
        self.assertIsNone(cp.claim_dispatch(self.conn,{'id':'forged','allowed_projects':[self.slug],'capabilities':['video_gen']},list(adapter.KEYS),allowed_projects=[self.slug]))
        self.conn.rollback()
        cp.cancel_run(self.conn,self.me,self.slug,queued['runId']);self.conn.commit()

    def test_chain_review_source_handoff_and_cancellation_no_late_overwrite(self):
        identifier=self.prepare()[0]['shotId'];self.image(identifier);self.hybrid()
        seen=[]
        def infer(task,config,head):
            context=worker.resolve_studio_context(task);seen.append(context)
            self.assertTrue(context['source_video']);self.assertTrue(context['ingredients_sheet'])
            return self.local_inference(task,config,head)
        with patch.object(worker,'comfyui',side_effect=infer):
            run=self.escalate(identifier,{'strategy':'closed_to_open_4k'});first=self.gate(run['runId'])
            self.assertEqual(seen,[])
            self.resolve(first)
            second=self.gate(run['runId'])
            self.assertNotEqual(first['gate_id'],second['gate_id'])
            self.assertEqual(len(seen),1)
            selected=self.ok('/shots/'+identifier)['selectedVideoUrl']
            code,_,_=self.request(f"/projects/api/{self.slug}/orchestration/runs/{run['runId']}/cancel",method='POST',data={'client_request_id':'cancel-chain'})
            self.assertEqual(code,200)
            self.assertEqual(self.ok('/shots/'+identifier)['selectedVideoUrl'],selected)
            self.assertEqual(self.request(f"/projects/api/{self.slug}/orchestration/gates/{second['gate_id']}/resolve",method='POST',data={'client_request_id':'late','resolution':{'proposal_id':second['proposals'][0]['id']}})[0],409)

    def test_v2_authentication_trusted_project_policy_and_media_grants(self):
        self.prepare()
        self.assertEqual(self.request('/openapi/v2/cards',authenticated=False)[0],401)
        body={'nodeInfoList':[{'nodeId':'prompt','fieldName':'prompt','fieldValue':'Original empty set'}],'production_policy':'hybrid_studio'}
        header={'X-Project-Slug':self.slug}
        self.assertEqual(self.request('/openapi/v2/run/ai-app/seedance-20-pro',method='POST',data=body,headers=header)[0],400)
        self.assertEqual(self.submits,[])
        self.hybrid()
        code,run,_=self.request('/openapi/v2/run/ai-app/seedance-20-pro',method='POST',data=body,headers=header);self.assertEqual(code,200,run)
        until=time.monotonic()+15
        while time.monotonic()<until:
            code,done,_=self.request('/openapi/v2/query',method='POST',data={'taskId':run['taskId']})
            if done['status'] not in ('RUNNING','QUEUED'):break
            time.sleep(.1)
        self.assertEqual(done['status'],'SUCCESS',done)
        from urllib.parse import urlsplit
        url=urlsplit(done['results'][0]['url']).path
        self.assertEqual(self.request(url)[0],200)
        self.assertEqual(self.request('/openapi/v2/query',method='POST',data={'taskId':'unknown'})[0],404)
        self.assertEqual(self.request(url,authenticated=False)[0],401)

    def test_expired_internal_lease_never_auto_retries_and_scope_policy_are_rechecked(self):
        identifier=self.prepare()[0]['shotId'];self.hybrid()
        with patch.object(adapter,'wake'):
            run=self.escalate(identifier,{'strategy':'closed_hero'})
        dispatch=cp.claim_dispatch(self.conn,adapter._PRINCIPAL,list(adapter.KEYS),allowed_projects=[self.slug]);self.assertIsNotNone(dispatch)
        task=db.get_task(self.conn,self.slug,dispatch['task_id'])
        altered={**task,'target':{**task['target'],'col_index':0}}
        with self.assertRaises(cp.OrchestrationError):adapter.verify_task(self.conn,altered)
        with self.conn.cursor() as cur:cur.execute("UPDATE projectops.orchestration_dispatch SET lease_until=NOW()-INTERVAL '1 second' WHERE id=%s",(dispatch['id'],))
        self.conn.commit()
        cp.sweep(self.conn,self.slug);self.conn.commit()
        self.assertEqual(len(db.dispatches(self.conn,self.slug,task['id'])),1)
        with self.assertRaises(cp.OrchestrationError):cp.complete_dispatch(self.conn,adapter._PRINCIPAL,dispatch['handle'],dispatch['lease_token'],outcome='succeeded',output={'asset_url':'late'},proposal_ids=[])
        self.conn.rollback()
        self.assertIsNone(self.ok('/shots/'+identifier)['selectedVideoUrl'])
        self.assertEqual(self.submits,[])

    def test_review_rejects_changed_sources_or_policy_and_closed_cloud_story_is_graphless(self):
        identifier=self.prepare()[0]['shotId'];self.image(identifier);self.hybrid()
        with patch.object(worker,'comfyui',side_effect=self.local_inference):
            run=self.escalate(identifier,{'strategy':'ab_race'});gate=self.gate(run['runId'],2)
        self.ok('/shots/'+identifier,'PATCH',{'description':'Newer human direction'})
        code,_,_=self.request(f"/projects/api/{self.slug}/orchestration/gates/{gate['gate_id']}/resolve",method='POST',data={'client_request_id':'stale','resolution':{'proposal_id':gate['proposals'][0]['id']}})
        self.assertEqual(code,409)
        self.assertIsNone(self.ok('/shots/'+identifier)['selectedVideoUrl'])
        cp.cancel_run(self.conn,self.me,self.slug,run['runId']);self.conn.commit()
        # The cloud card requires a driving video, supplied as an authorized fixture asset.
        source_id=repo.put_asset(self.conn,self.slug,data=self.raw,content_type='video/mp4',actor_id=self.actor);self.conn.commit()
        source_url=f'/projects/api/{self.slug}/assets/{source_id}'
        # The real Story cloud route is also graphless; only remote inference is synthetic.
        with patch.object(worker,'comfyui',side_effect=AssertionError('Comfy offline')),patch.object(worker,'ComfyPlatformClient',side_effect=AssertionError('Comfy offline')):
            done=self.await_task(self.ok('/shots/'+identifier+'/video-generations','POST',{'appCode':'rh-cloud-h3-burst','modelParams':{'duration':1,'driving_video':source_url}}))
        self.assertEqual(done['status'],'SUCCEEDED',done)
        self.assertTrue(any('/cloud/run/ai-app/' in path for path,_ in self.submits))

    def test_policy_permissions_other_actor_grants_and_source_candidate_isolation(self):
        import uuid
        identifier=self.prepare()[0]['shotId']
        repo.upsert_member(self.conn,self.actor,'Crew','member');self.conn.commit()
        self.assertEqual(self.call(f'/projects/pj_{self.slug}/production-policy','PUT',{'productionPolicy':'hybrid_studio'})[0],403)
        repo.upsert_member(self.conn,self.actor,'Viewer','viewer');self.conn.commit()
        self.assertEqual(self.call(self.nested(),'POST',{})[0],409)
        repo.upsert_member(self.conn,self.actor,'Showrunner','admin');self.conn.commit()
        self.hybrid()
        self.assertEqual(self.call('/shots/'+identifier+'/video-generations','POST',{'appCode':'seedance-20-pro','referenceSourceVideoId':'vd_foreign'})[0],422)
        code,up,_=self.request('/openapi/v2/media/upload/binary',method='POST',raw=self.raw,headers={'Content-Type':'video/mp4','X-File-Name':'own.mp4','X-Project-Slug':self.slug});self.assertEqual(code,200)
        other=str(uuid.uuid4());other_token='isolated-test-token-'+other
        repo.upsert_member(self.conn,other,'Other crew','member');self.conn.commit()
        try:
            tokens=json.loads(os.environ['OPENBENCH_TOKENS']);tokens[other_token]=other
            with patch.dict(os.environ,{'OPENBENCH_TOKENS':json.dumps(tokens)}):
                self.assertEqual(self.request('/openapi/v2/media/input/'+up['data']['fileName'],headers={'Authorization':'Bearer '+other_token})[0],404)
        finally:
            with self.conn.cursor() as cur:cur.execute('DELETE FROM projectops.member WHERE actor_id=%s',(other,))
            self.conn.commit()
        self.assertEqual(self.submits,[])

    def test_late_chain_output_canceled_before_proposal_cannot_overwrite(self):
        identifier=self.prepare()[0]['shotId'];self.image(identifier);self.hybrid()
        started=threading.Event();release=threading.Event();finished=threading.Event()
        def delayed(task,config,head):
            output=self.local_inference(task,config,head)
            started.set()
            try:
                if not release.wait(15):raise AssertionError('fixture release timed out')
                return output
            finally:finished.set()
        with patch.object(worker,'comfyui',side_effect=delayed):
            run=self.escalate(identifier,{'strategy':'closed_to_open_4k'})
            self.resolve(self.gate(run['runId']))
            self.assertTrue(started.wait(15))
            before=self.ok('/shots/'+identifier)['selectedVideoUrl']
            code,_,_=self.request(f"/projects/api/{self.slug}/orchestration/runs/{run['runId']}/cancel",method='POST',data={'client_request_id':'cancel-running'})
            self.assertEqual(code,200)
            release.set();self.assertTrue(finished.wait(3));time.sleep(.3)
            self.assertEqual(self.ok('/shots/'+identifier)['selectedVideoUrl'],before)
            self.assertTrue(all(d['status']!='awaiting_gate' for d in db.dispatches(self.conn,self.slug,run_id=run['runId'])))

    def test_existing_approved_source_skips_draft_and_uses_real_vendor_handoff(self):
        identifier=self.prepare()[0]['shotId'];self.image(identifier);self.hybrid()
        source=self.ok('/shots/'+identifier+'/images')['items'][-1]['imageId']
        body={'chainMode':'open_previz_to_closed_hero','referenceSourceImageId':source}
        self.assertEqual(self.call(self.nested(identifier),'POST',body)[0],409)
        _,row=story.find_row(self.conn,identifier,'shot')
        story.mutate_row(self.conn,self.me,self.slug,row['tabKey'],row['rid'],{6:'Approved'});self.conn.commit()
        with patch.object(worker,'comfyui',side_effect=AssertionError('approved keyframe skips draft inference')):
            run=self.escalate(identifier,body);gate=self.gate(run['runId'])
            self.assertEqual(len(db.tasks(self.conn,self.slug,run['runId'])),1)
            self.assertEqual(self.submits[-1][1]['inputs']['image_url'],'fixture-reference')
            self.resolve(gate)

    def test_masking_blocks_commercial_export_and_custom_video_choice_keeps_frozen_graph(self):
        identifier=self.prepare()[0]['shotId'];self.image(identifier);self.hybrid()
        repo.update_project_meta(self.conn,self.slug,privacy_mode='mask_numbers');self.conn.commit()
        self.assertEqual(self.call('/shots/'+identifier+'/video-generations','POST',{'appCode':'seedance-20-pro'})[0],403)
        self.assertEqual(self.submits,[])
        repo.update_project_meta(self.conn,self.slug,privacy_mode='full_access');self.conn.commit()
        card_id='test-card-'+self.slug
        graph={'1':{'class_type':'LoadImage','inputs':{'image':'None'}},'2':{'class_type':'VHS_VideoCombine','inputs':{'images':['1',0],'filename_prefix':'custom'}}}
        code,saved,_=self.request('/openapi/v2/cards/register',method='POST',data={'card_id':card_id,'workflow':graph,'label':'My Custom Video'})
        self.assertEqual(code,200,saved)
        plan=self.ok(self.nested(),'POST',{'appCode':card_id,'shotIds':[identifier]})
        self.assertEqual(plan['allocations'][0]['assignedCardId'],card_id)
        changed=story.record(self.conn,'card_'+card_id)
        changed['workflow']={'unexpected':{'class_type':'ChangedAfterPreflight','inputs':{}}}
        story.store(self.conn,'card_'+card_id,'card',changed);self.conn.commit()
        paths=[]
        def local(task,config,head):
            paths.append(Path(config['workflow']));self.assertEqual(json.loads(paths[-1].read_text()),graph)
            return self.local_inference(task,config,head)
        with patch.object(story._POOL,'submit'):
            group=self.ok(f'/episodes/{self.ep}/shot-video-generations','POST',{'allocationId':plan['allocationId'],'shotIds':[identifier]})
        with worker._OPENAPI_LOCK:
            old_card,_=worker._OPENAPI_CARDS[card_id];worker._OPENAPI_CARDS[card_id]=(old_card,{'unexpected':{'class_type':'Changed','inputs':{}}})
        with patch.object(worker,'comfyui',side_effect=local):story.execute_task(group['taskIds'][0])
        self.assertEqual(self.ok('/tasks/'+group['taskIds'][0])['status'],'SUCCEEDED')
        self.assertTrue(paths);self.assertFalse(paths[0].exists())

    def test_open_previz_actual_structure_review_extract_then_vendor_final(self):
        identifier=self.prepare()[0]['shotId'];self.image(identifier, cast_reference=True);self.hybrid()
        with patch.object(worker,'comfyui',side_effect=self.local_inference):
            run=self.escalate(identifier,{'chainMode':'open_previz_to_closed_hero'})
            first=self.gate(run['runId'])
            self.assertEqual(self.submits,[])
            self.resolve(first)
            second=self.gate(run['runId'])
            self.assertNotEqual(first['gate_id'],second['gate_id'])
            tasks=db.tasks(self.conn,self.slug,run['runId'])
            extracted=[d['output_json'] for t in tasks if t['input_snapshot']['story_media']['name']=='approved_keyframe' for d in db.dispatches(self.conn,self.slug,t['id'])]
            self.assertEqual(extracted[0]['content_type'],'image/png')
            self.assertEqual(self.submits[-1][1]['inputs']['image_url'],'fixture-reference')
            self.resolve(second)

    def test_v2_identity_exception_returns_safe_response_before_dispatch(self):
        with patch.object(self.server.RequestHandlerClass, 'project_docs_identity', side_effect=RuntimeError('fixture-sensitive-identity-detail')):
            code,payload,_=self.request('/openapi/v2/cards')
        self.assertEqual(code,500,payload)
        self.assertEqual(payload['msg'],'Media API unavailable; check deployment configuration.')
        self.assertNotIn('fixture-sensitive-identity-detail',json.dumps(payload))
        self.assertEqual(self.submits,[])


    def media_grader_case(self, always_fail=False):
        from project_assistant import agent_registry, tools, outcome_grader, execution_governance as governance
        import psycopg
        requests=[];grades=[];owner=self
        class Model(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append(request)
                content=request['messages'][1]['content']
                text=content[0]['text'] if isinstance(content,list) else content
                payload=json.loads(text)
                if request['messages'][0]['content']==outcome_grader.GRADE_INSTRUCTIONS:
                    owner.assertIsInstance(content,list)
                    owner.assertTrue(content[1]['image_url']['url'].startswith('data:image/png;base64,'))
                    owner.assertEqual(payload['objective'],'Check the actual courier candidate.')
                    owner.assertNotIn('PRIVATE SPONSOR PROMPT',json.dumps(request))
                    owner.assertNotIn('tools',request)
                    with psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI']) as conn:
                        owner.assertEqual(db.one(conn,'SELECT count(*) FROM projectops.assistant_proposal WHERE project_slug=%s',(owner.slug,)),0)
                    media=json.loads(payload['candidate']['answer'])['media']
                    if grades: owner.assertEqual(media,grades[0])
                    grades.append(media)
                    passed=len(grades)>1 and not always_fail
                    answer={'passed':passed,'score':90 if passed else 25,'feedback':'Improve the evidence note, not the render.',
                            'checklist':[{'criterion':'Candidate evidence','passed':passed}]}
                else:
                    owner.assertEqual(request['messages'][0]['content'],outcome_grader.REVISION_INSTRUCTIONS)
                    candidate=payload['candidate'];value=json.loads(candidate['answer']);value['review_note']='Revised evidence note'
                    candidate['answer']=json.dumps(value);answer=candidate
                raw=json.dumps({'choices':[{'message':{'content':json.dumps(answer)}}],
                    'usage':{'prompt_tokens':15,'completion_tokens':5}}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        server=ThreadingHTTPServer(('127.0.0.1',0),Model)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        for key in ('coordinator','qa_critic'):
            agent_registry.save_agent(self.conn,self.me,self.slug,{'agent_key':key,'system_prompt':'PRIVATE SPONSOR PROMPT',
                'provider_config':{'kind':'openai_compat','model':'synthetic-grading','base_url':f'http://127.0.0.1:{server.server_port}/v1'}})
        agent_registry.save_agent(self.conn,self.me,self.slug,{'agent_key':'coordinator','tool_policies':{'studio_dispatch_shot':'auto'},
            'outcome_grader':{'enabled':True,'criteria':'Inspect actual media evidence','grader_agent_key':'qa_critic','max_revisions':1}})
        self.conn.commit()
        identifier=self.prepare()[0]['shotId'];self.image(identifier);self.image(identifier,cast_reference=True)
        ctx=tools.ToolContext(lambda:psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI']),self.slug,self.me,Path('.'),None)
        ctx.episode_id=self.ep;ctx.original_objective='Check the actual courier candidate.';ctx.accounting_session_key='original-tool-session';governance.install(ctx)
        plan=json.loads(tools.call(ctx,'studio_plan_allocation',{'episode_id':self.ep,'shot_ids':[identifier],'app_code':'ltx25-cinema'}))
        self.assertTrue(plan['ready'],plan)
        with patch.object(worker,'comfyui',side_effect=self.local_inference) as inference:
            queued=json.loads(tools.call(ctx,'studio_dispatch_shot',{'episode_id':self.ep,'shot_ids':[identifier],'allocation_id':plan['allocationId']}))
            run=queued['runs'][0]['runId'];self.runs.append(run)
            until=time.monotonic()+20
            dispatch=None
            while time.monotonic()<until:
                items=db.dispatches(self.conn,self.slug,run_id=run)
                dispatch=items[0] if items else None
                if dispatch and dispatch['status'] in ('awaiting_gate','failed') and dispatch.get('output_json'): break
                time.sleep(.05)
            self.assertIsNotNone(dispatch)
            self.assertEqual(dispatch['status'],'awaiting_gate',dispatch)
            self.assertEqual(inference.call_count,1)
            self.assertEqual(len(grades),2)
            self.assertEqual(len(requests),3)
            self.assertEqual(dispatch['output_json']['outcome_grader']['passed'],not always_fail)
            proposals=db.many(self.conn,'SELECT id FROM projectops.assistant_proposal WHERE dispatch_id=%s',(dispatch['id'],))
            self.assertEqual(len(proposals),0 if always_fail else 1)
            if always_fail:
                gate=db.one(self.conn,"SELECT to_jsonb(g) FROM projectops.orchestration_gate g WHERE dispatch_id=%s AND status='open'",(dispatch['id'],))
                cp.resolve_gate(self.conn,self.me,self.slug,gate['id'],resolution='0',client_request_id='ack-failed-media');self.conn.commit()
                self.assertEqual(len(db.dispatches(self.conn,self.slug,run_id=run)),1)
                self.assertEqual(inference.call_count,1)
            kinds=db.many(self.conn,'SELECT usage_kind FROM projectops.agent_usage_ledger WHERE project_slug=%s',(self.slug,))
            self.assertEqual(kinds.count('video_gen'),1)
            self.assertEqual(kinds.count('grader_check'),2)
            self.assertEqual(kinds.count('frame_prep'),1)
            self.assertEqual(kinds.count('llm_turn'),1)
            self.assertEqual(db.many(self.conn,'SELECT DISTINCT session_key FROM projectops.agent_usage_ledger WHERE project_slug=%s',(self.slug,)),['original-tool-session'])

    def test_actual_async_media_is_graded_before_review_without_rerender(self):
        self.media_grader_case()

    def test_failed_async_media_scorecard_gate_cannot_resume_paid_side_effects(self):
        self.media_grader_case(always_fail=True)
