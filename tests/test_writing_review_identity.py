"""S1/S2 review regressions: real assigned PG, token auth, HTTP and root browser."""
import json
import os
import unittest
import uuid
import test_writing_core as core
from project_docs import repository as repo


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'assigned isolated PG required')
class WritingReviewIdentityTests(unittest.TestCase):
    def setUp(self):
        self.f=core.WritingHTTPTests('test_early_save_reload_sources_and_mainline');self.f.setUp()
        self.actor_b=str(uuid.uuid4());self.token_b='review-identity-'+uuid.uuid4().hex
        repo.upsert_member(self.f.conn,self.actor_b,'Second review author','admin');self.f.conn.commit()
        tokens=json.loads(os.environ['OPENBENCH_TOKENS']);tokens[self.token_b]=self.actor_b;os.environ['OPENBENCH_TOKENS']=json.dumps(tokens)
        self.base=f'http://127.0.0.1:{self.f.server.server_port}'
        self.path=f'/aivideo/open/v1/episodes/{self.f.ep}/writing/'

    def tearDown(self):
        self.f.conn.rollback()
        self.f.conn.execute('delete from projectops.story_record where owner_id=%s',(self.actor_b,))
        self.f.conn.execute('delete from projectops.member where actor_id=%s',(self.actor_b,));self.f.conn.commit()
        self.f.tearDown()

    def context(self,browser):
        context=browser.new_context()
        context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(self.base+'/') else route.abort())
        return context

    def body(self):
        return {'baseVersion':0,'clientMutationId':uuid.uuid4().hex,'doc':core.document('A private novel'),'structure':{},'composition':{}}

    def test_cookie_binding_before_execution_and_receipt_or_post_replay(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser=p.chromium.launch()
            try:
                context=self.context(browser);context.request.post(self.base+'/login',form={'token':self.f.member_token})
                headers={'X-Requested-With':'projects','X-Writing-Expected-Actor':self.f.actor}
                body=self.body();created=context.request.put(self.base+self.path+'sources/novel',data=body,headers=headers)
                self.assertEqual(created.status,200,created.text())
                post={'sourceRef':{'kind':'source','mode':'novel'},'expectedSourceHash':created.json()['data']['docHash'],'name':'A private branch'}
                post_headers=headers|{'Idempotency-Key':'review-identity-replay'}
                self.assertEqual(context.request.post(self.base+self.path+'branches',data=post,headers=post_headers).status,200)
                # Even the same actor/credential cannot replay with a wrong expectation.
                mismatch=headers|{'X-Writing-Expected-Actor':self.actor_b}
                response=context.request.put(self.base+self.path+'sources/novel',data=body,headers=mismatch)
                self.assertEqual(response.status,401,response.text());self.assertNotIn('A private novel',response.text())
                response=context.request.post(self.base+self.path+'branches',data=post,headers=post_headers|mismatch)
                self.assertEqual(response.status,401,response.text());self.assertNotIn('A private branch',response.text())
                missing_replay=context.request.post(self.base+self.path+'branches',data=post,headers={'X-Requested-With':'projects','Idempotency-Key':'review-identity-replay'})
                self.assertEqual(missing_replay.status,401,missing_replay.text());self.assertNotIn('A private branch',missing_replay.text())
                bearer_mismatch=self.f.request(self.path+'sources/novel',headers={'X-Writing-Expected-Actor':self.actor_b})
                self.assertEqual(bearer_mismatch[0],401,bearer_mismatch[1])
                context.request.post(self.base+'/login',form={'token':self.token_b})
                for method,tail,data,sent in [('PUT','sources/novel',body,headers),('POST','branches',post,post_headers),('GET','sources/novel',None,headers)]:
                    response=context.request.fetch(self.base+self.path+tail,method=method,data=data,headers=sent)
                    self.assertEqual(response.status,401,response.text());self.assertNotIn('A private',response.text())
                missing=context.request.put(self.base+self.path+'sources/novel',data=self.body(),headers={'X-Requested-With':'projects'})
                self.assertEqual(missing.status,401,missing.text())
                self.assertIsNone(context.request.get(self.base+self.path+'sources/novel',headers={'X-Writing-Expected-Actor':self.actor_b}).json()['data'])
                # Explicit bearer API remains compatible, and binding never grants membership.
                self.assertIsNotNone(self.f.writing('sources/novel'))
                forbidden=headers|{'Origin':'https://foreign.invalid'}
                self.assertEqual(context.request.put(self.base+self.path+'sources/novel',data=body,headers=forbidden).status,403)
                repo.upsert_member(self.f.conn,self.actor_b,'Second review author','viewer');self.f.conn.commit()
                for expected in (self.actor_b,self.f.actor):
                    denied=context.request.put(self.base+self.path+'sources/novel',data=body,headers={'X-Requested-With':'projects','X-Writing-Expected-Actor':expected})
                    self.assertEqual(denied.status,403,denied.text())
            finally:browser.close()

    def test_same_context_two_tab_switch_between_preflight_and_pending_save(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as p:
            browser=p.chromium.launch()
            try:
                context=self.context(browser);context.request.post(self.base+'/login',form={'token':self.f.member_token})
                page=context.new_page();other=context.new_page();errors=[];page.on('pageerror',lambda err:errors.append(str(err)))
                page.goto(self.base+'/projects/'+self.f.slug+'/#story-world')
                editor=page.get_by_role('textbox',name='Manuscript editor');editor.wait_for(timeout=30000)
                page.get_by_role('combobox',name='Manuscript',exact=True).select_option('source:novel')
                expect(page.locator('.writing-scope')).to_contain_text('Private')
                held=[];intercepted=[]
                def preflight(route):
                    if intercepted:
                        route.continue_();return
                    intercepted.append(True);held.append((route,route.fetch()))
                page.route('**/projects/api/'+self.f.slug,preflight)
                responses=[];page.on('response',lambda r:responses.append(r.status) if r.url.endswith('/writing/sources/novel') and r.request.method=='PUT' else None)
                editor.fill('Only actor A may recover this pending private novel.')
                page.keyboard.press('Control+s')
                for _ in range(100):
                    if held:break
                    page.wait_for_timeout(30)
                self.assertTrue(held,'Save did not reach identity preflight')
                other.goto(self.base+'/login');other.locator('input[name=token]').fill(self.token_b);other.locator('form button').click();other.wait_for_load_state()
                route,response=held.pop();route.fulfill(response=response)
                for _ in range(100):
                    if responses:break
                    page.wait_for_timeout(30)
                self.assertEqual(responses,[401],responses)
                expect(page.locator('.authoring-workspace')).to_have_count(0)
                page.evaluate("window.dispatchEvent(new Event('online'))")
                page.wait_for_timeout(1200);self.assertEqual(responses,[401])
                self.assertIsNone(context.request.get(self.base+self.path+'sources/novel',headers={'X-Writing-Expected-Actor':self.actor_b}).json()['data'])
                # B must not see A's private recovery. A can sign back in and explicitly recover it.
                page.reload();editor.wait_for();page.get_by_role('combobox',name='Manuscript',exact=True).select_option('source:novel')
                self.assertNotIn('Only actor A',page.locator('body').inner_text())
                self.assertEqual(page.locator('.writing-recovery').count(),0)
                context.request.post(self.base+'/login',form={'token':self.f.member_token});page.reload();editor.wait_for()
                page.get_by_role('combobox',name='Manuscript',exact=True).select_option('source:novel')
                expect(page.locator('.writing-recovery')).to_contain_text('Only actor A may recover')
                self.assertEqual(errors,[])
            finally:browser.close()

    def test_same_context_reconnect_before_and_after_root_poll_disposal(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as p:
            browser=p.chromium.launch()
            try:
                for detect_by_poll in (False,True):
                    with self.subTest(detect_by_poll=detect_by_poll):
                        context=self.context(browser);context.request.post(self.base+'/login',form={'token':self.f.member_token})
                        page=context.new_page();other=context.new_page()
                        page.goto(self.base+'/projects/'+self.f.slug+'/#story-world')
                        editor=page.get_by_role('textbox',name='Manuscript editor');editor.wait_for(timeout=30000)
                        page.get_by_role('combobox',name='Manuscript',exact=True).select_option('source:novel')
                        expect(page.locator('.writing-scope')).to_contain_text('Private')
                        sent=[]
                        def disconnect(route):
                            if route.request.method=='PUT':sent.append(route.request.headers);route.abort('internetdisconnected')
                            else:route.continue_()
                        page.route('**/writing/sources/novel',disconnect)
                        editor.fill('Actor A offline novel, never upload as B.');page.keyboard.press('Control+s')
                        expect(page.locator('.writing-status')).to_contain_text('Saved on this device only')
                        self.assertEqual(len(sent),1);self.assertEqual(sent[0].get('x-writing-expected-actor'),self.f.actor)
                        other.goto(self.base+'/login');other.locator('input[name=token]').fill(self.token_b);other.locator('form button').click();other.wait_for_load_state()
                        page.bring_to_front()
                        if detect_by_poll:expect(page.locator('.authoring-workspace')).to_have_count(0,timeout=25000)
                        page.evaluate("window.dispatchEvent(new Event('online'))")
                        expect(page.locator('.authoring-workspace')).to_have_count(0,timeout=10000)
                        page.evaluate("window.dispatchEvent(new Event('online'))");page.wait_for_timeout(1000)
                        self.assertEqual(len(sent),1,'A disposed reconnect listener attempted another upload')
                        self.assertIsNone(context.request.get(self.base+self.path+'sources/novel',headers={'X-Writing-Expected-Actor':self.actor_b}).json()['data'])
                        page.wait_for_load_state('networkidle');context.close()
            finally:browser.close()

    def test_root_metadata_only_journal_requires_explicit_choice_before_real_save(self):
        from playwright.sync_api import sync_playwright, expect
        body=self.body()|{'composition':{'mediumLens':'cinema','genreLens':'general'}}
        initial=self.f.writing('sources/novel','PUT',body)
        with sync_playwright() as p:
            browser=p.chromium.launch()
            try:
                context=self.context(browser);context.request.post(self.base+'/login',form={'token':self.f.member_token})
                page=context.new_page();page.goto(self.base+'/projects/'+self.f.slug+'/#story-world')
                editor=page.get_by_role('textbox',name='Manuscript editor');editor.wait_for(timeout=30000)
                page.get_by_role('combobox',name='Manuscript',exact=True).select_option('source:novel');expect(editor).to_contain_text('A private novel')
                # Keep this journal pre-pending: IME suppresses debounce/network, but metadata checkpoints still persist.
                editor.dispatch_event('compositionstart')
                page.get_by_text('Lenses & condition choices',exact=True).click()
                page.locator('.writing-source-tools select').first.select_option('manju');page.wait_for_timeout(1000)
                self.assertEqual(self.f.writing('sources/novel')['version'],1)
                changed=self.f.writing('sources/novel','PUT',body|{'baseVersion':1,'clientMutationId':'remote-metadata','composition':{'mediumLens':'storybook','genreLens':'suspense'}})
                self.assertEqual(changed['docHash'],initial['docHash'])
                page.reload();editor.wait_for();page.get_by_role('combobox',name='Manuscript',exact=True).select_option('source:novel')
                expect(page.locator('.writing-recovery')).to_contain_text('metadata changed after this device checkpoint')
                writes=[];page.on('request',lambda req:writes.append(req.post_data_json) if req.method=='PUT' and req.url.endswith('/writing/sources/novel') else None)
                page.get_by_role('button',name='Restore this device copy',exact=True).click()
                expect(page.locator('.writing-conflict')).to_contain_text('private metadata or its version has changed')
                page.wait_for_timeout(1000);self.assertEqual(writes,[])
                page.get_by_role('button',name='Load current server copy for merge',exact=True).click()
                expect(page.get_by_role('checkbox',name='Explicitly keep device chapter structure and lens choices instead of the server metadata')).not_to_be_checked()
                page.get_by_role('button',name='Save explicitly selected merge',exact=True).click()
                expect(page.locator('.writing-status')).to_contain_text('Saved on server')
                self.assertEqual(writes[0]['baseVersion'],2)
                saved=self.f.writing('sources/novel');self.assertEqual(saved['composition'],changed['composition']);self.assertEqual(saved['docHash'],initial['docHash'])
                page.wait_for_load_state('networkidle')
            finally:browser.close()

    def test_metadata_only_stale_private_cas_rejected_by_real_server(self):
        body=self.body();saved=self.f.writing('sources/novel','PUT',body)
        remote=body|{'baseVersion':saved['version'],'clientMutationId':'remote-lens','composition':{'mediumLens':'storybook'}}
        changed=self.f.writing('sources/novel','PUT',remote)
        self.assertEqual(changed['docHash'],saved['docHash']);self.assertEqual(changed['version'],2)
        stale=body|{'baseVersion':saved['version'],'clientMutationId':'device-old','composition':{'mediumLens':'cinema'}}
        self.f.error('sources/novel','PUT',stale,409)
        self.assertEqual(self.f.writing('sources/novel')['composition']['mediumLens'],'storybook')
        branch=self.f.writing('branches','POST',{'sourceRef':{'kind':'source','mode':'novel'},'expectedSourceHash':changed['docHash'],'name':'Private metadata CAS'})
        tail='branches/'+branch['branchId']
        next_branch=self.f.writing(tail,'PUT',{'baseVersion':1,'clientMutationId':'branch-remote-meta','doc':branch['doc'],'structure':branch['structure'],'composition':{'mediumLens':'manju'}})
        self.assertEqual(next_branch['docHash'],branch['docHash']);self.assertEqual(next_branch['version'],2)
        self.f.error(tail,'PUT',{'baseVersion':1,'clientMutationId':'branch-stale-meta','doc':branch['doc'],'structure':branch['structure'],'composition':branch['composition']},409)
        self.assertEqual(self.f.writing(tail)['composition']['mediumLens'],'manju')
