"""Legacy Story expected-actor consistency: actual token/cookie HTTP and root UI."""
import json
import os
from pathlib import Path
import unittest
import uuid
import test_writing_core as core
import test_writing_review_identity as identity
from project_docs import repository as repo


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'assigned isolated PG required')
class WritingReviewLegacyIdentityTests(unittest.TestCase):
    setUp=identity.WritingReviewIdentityTests.setUp
    tearDown=identity.WritingReviewIdentityTests.tearDown
    context=identity.WritingReviewIdentityTests.context

    def collision_body(self):
        return {'sourceText':'Character: SyntheticPrivateCollisionMarker\nA custodian holds a brass dial at the lighthouse.',
                'mediumLens':'cinema','genreLens':'general'}

    def cache_rows(self,actor):
        self.f.conn.rollback()
        return self.f.conn.execute("select data from projectops.story_record where owner_id=%s and kind='idempotency'",(actor,)).fetchall()

    def test_root_collision_shared_cookie_switch_refuses_private_response_and_B_cache(self):
        from playwright.sync_api import sync_playwright, expect
        marker='SyntheticPrivateCollisionMarker'
        body=self.collision_body()
        self.f.writing('sources/novel','PUT',{'baseVersion':0,'clientMutationId':uuid.uuid4().hex,
            'doc':core.document(*body['sourceText'].split('\n')),'structure':{},
            'composition':{'mediumLens':'cinema','genreLens':'general'}})
        with sync_playwright() as p:
            browser=p.chromium.launch()
            try:
                context=self.context(browser)
                context.request.post(self.base+'/login',form={'token':self.f.member_token})
                page=context.new_page();other=context.new_page()
                page.goto(self.base+'/projects/'+self.f.slug+'/#story-world')
                editor=page.get_by_role('textbox',name='Manuscript editor');editor.wait_for(timeout=30000)
                page.get_by_role('combobox',name='Manuscript',exact=True).select_option('source:novel')
                expect(editor).to_contain_text(marker)
                page.get_by_text('Lenses & condition choices',exact=True).click()
                page.wait_for_load_state('networkidle')
                held=[];sent=[];responses=[]
                def preflight(route):
                    if held:route.continue_()
                    else:held.append((route,route.fetch()))
                page.route('**/projects/api/'+self.f.slug,preflight)
                page.on('request',lambda req:sent.append(req) if req.url.endswith('/story-collisions') and req.method=='POST' else None)
                page.on('response',lambda response:responses.append(response) if response.url.endswith('/story-collisions') else None)
                page.get_by_role('button',name='Collide Conditions (L1→L2)',exact=True).click()
                for _ in range(100):
                    if held:break
                    page.wait_for_timeout(30)
                self.assertTrue(held,'No root collision identity preflight was held')
                other.goto(self.base+'/login');other.locator('input[name=token]').fill(self.token_b)
                other.locator('form button').click();other.wait_for_load_state()
                self.assertEqual(context.request.get(self.base+'/projects/api/'+self.f.slug).json()['me']['actor_id'],self.actor_b)
                held[0][0].fulfill(response=held[0][1])
                for _ in range(100):
                    if responses:break
                    page.wait_for_timeout(30)
                self.assertTrue(sent and responses,'No actual legacy collision request/response')
                response=responses[0];payload=response.json();rows=self.cache_rows(self.actor_b)
                evidence={'requestExpectedActorMatchesA':sent[0].headers.get('x-writing-expected-actor')==self.f.actor,
                    'syntheticPrivateMarkerSent':marker in (sent[0].post_data or ''),'responseStatus':response.status,
                    'responseContainsMarker':marker in json.dumps(payload),'BIdempotencyRows':len(rows),
                    'BCacheContainsMarker':any(marker in json.dumps(row[0]) for row in rows)}
                artifacts=Path('.cache/review1-auth-legacy');artifacts.mkdir(parents=True,exist_ok=True)
                (artifacts/'root-collision-last.json').write_text(json.dumps(evidence,indent=2),encoding='utf8')
                self.assertTrue(evidence['requestExpectedActorMatchesA']);self.assertTrue(evidence['syntheticPrivateMarkerSent'])
                self.assertEqual(response.status,401,evidence)
                self.assertEqual(payload['code'],'DRAMA_WRITING_IDENTITY_MISMATCH')
                self.assertFalse(evidence['responseContainsMarker']);self.assertEqual(rows,[])
                expect(page.locator('.authoring-workspace')).to_have_count(0)
                page.wait_for_load_state('networkidle')
            finally:browser.close()

    def test_legacy_matching_header_and_no_header_cookie_or_bearer_remain_compatible(self):
        from playwright.sync_api import sync_playwright
        path=f'/aivideo/open/v1/episodes/{self.f.ep}/story-collisions'
        body=self.collision_body()
        with sync_playwright() as p:
            browser=p.chromium.launch()
            try:
                context=self.context(browser);context.request.post(self.base+'/login',form={'token':self.f.member_token})
                headers={'X-Requested-With':'projects','Idempotency-Key':'legacy-matching','X-Writing-Expected-Actor':self.f.actor}
                response=context.request.post(self.base+path,data=body,headers=headers)
                self.assertEqual(response.status,200,response.text());self.assertIn('SyntheticPrivateCollisionMarker',response.text())
                first=response.json()
                self.assertEqual(context.request.post(self.base+path,data=body,headers=headers).json(),first)
                response=context.request.post(self.base+path,data=body,headers={'X-Requested-With':'projects','Idempotency-Key':'legacy-no-header'})
                self.assertEqual(response.status,200,response.text())
                self.assertIn('SyntheticPrivateCollisionMarker',response.text())
                # Legacy bearer clients need no consistency header; matching optional binding works too.
                for extra in ({},{'X-Writing-Expected-Actor':self.f.actor}):
                    status,payload,_=self.f.request(path,method='POST',data=body,headers={'Idempotency-Key':uuid.uuid4().hex}|extra)
                    self.assertEqual(status,200,payload)
                # Supplying an expectation never authenticates an otherwise anonymous request.
                anonymous=self.f.request(path,method='POST',data=body,authenticated=False,headers={'X-Writing-Expected-Actor':self.f.actor})
                self.assertEqual(anonymous[0],401,anonymous[1])
                # Preserve the legacy cookie CSRF status and reject even a cached replay.
                forbidden=headers|{'Origin':'https://foreign.invalid'}
                response=context.request.post(self.base+path,data=body,headers=forbidden)
                self.assertEqual(response.status,400,response.text());self.assertNotIn('SyntheticPrivateCollisionMarker',response.text())
                repo.upsert_member(self.f.conn,self.actor_b,'Synthetic read-only author','viewer');self.f.conn.commit()
                context.request.post(self.base+'/login',form={'token':self.token_b})
                for expected in (self.actor_b,self.f.actor):
                    denied=context.request.post(self.base+path,data=body,headers=headers|{'X-Writing-Expected-Actor':expected})
                    self.assertEqual(denied.status,409,denied.text())
                    self.assertEqual(denied.json()['code'],'DRAMA_OPERATION_NOT_ALLOWED')
                    self.assertNotIn('SyntheticPrivateCollisionMarker',denied.text())
                self.assertEqual(self.cache_rows(self.actor_b),[])
            finally:browser.close()

    def test_legacy_mismatch_before_body_action_cached_replay_and_get_response(self):
        from playwright.sync_api import sync_playwright
        path=f'/aivideo/open/v1/episodes/{self.f.ep}/story-collisions'
        body=self.collision_body()
        with sync_playwright() as p:
            browser=p.chromium.launch()
            try:
                context=self.context(browser);context.request.post(self.base+'/login',form={'token':self.token_b})
                headers={'X-Requested-With':'projects','Idempotency-Key':'B-legacy-replay','X-Writing-Expected-Actor':self.actor_b}
                created=context.request.post(self.base+path,data=body,headers=headers)
                self.assertEqual(created.status,200,created.text())
                before=self.cache_rows(self.actor_b)
                mismatch=headers|{'X-Writing-Expected-Actor':self.f.actor}
                replay=context.request.post(self.base+path,data=body,headers=mismatch)
                self.assertEqual(replay.status,401,replay.text());self.assertNotIn('SyntheticPrivateCollisionMarker',replay.text())
                self.assertEqual(self.cache_rows(self.actor_b),before)
                # A mismatched body-driven legacy mutation creates neither the project nor a receipt.
                projects=self.f.conn.execute('select count(*) from projectops.project').fetchone()[0]
                refused=context.request.post(self.base+'/aivideo/open/v1/projects',data={'title':'Must not create'},headers=mismatch|{'Idempotency-Key':'B-mismatch-no-write'})
                self.assertEqual(refused.status,401,refused.text())
                self.f.conn.rollback();self.assertEqual(self.f.conn.execute('select count(*) from projectops.project').fetchone()[0],projects)
                self.assertEqual(self.cache_rows(self.actor_b),before)
                # Consistency is checked before JSON parsing/validation, not merely collision dispatch.
                invalid=context.request.post(self.base+path,data='not json',headers=mismatch|{'Content-Type':'application/json'})
                self.assertEqual(invalid.status,401,invalid.text())
                for tail in ('/catalog/styles',f'/episodes/{self.f.ep}'):
                    response=context.request.get(self.base+'/aivideo/open/v1'+tail,headers=mismatch)
                    self.assertEqual(response.status,401,response.text())
                self.assertEqual(context.request.get(self.base+'/aivideo/open/v1/catalog/styles').status,200)
                status,payload,_=self.f.request(path,method='POST',data=body,headers={'X-Writing-Expected-Actor':self.actor_b,'Idempotency-Key':'bearer-mismatch'})
                self.assertEqual(status,401,payload)
            finally:browser.close()
