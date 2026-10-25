"""Accepted SPEC16 review regressions through the actual root, PG, auth and built UI."""
import copy
import json
import os
import unittest
import uuid
from pathlib import Path
import test_writing_core as core
from writing_browser_nav import open_space
import test_writing_product_browser as product_fixture


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'dedicated review integration PG required')
class WritingReviewProductTests(unittest.TestCase):
    setUp=product_fixture.WritingProductBrowserTests.setUp
    tearDown=product_fixture.WritingProductBrowserTests.tearDown
    browser=product_fixture.WritingProductBrowserTests.browser
    tools=product_fixture.WritingProductBrowserTests.tools

    def test_J1_real_scene_insert_paste_delete_and_delayed_ack(self):
        from playwright.sync_api import expect
        self.f.init();doc=core.document('Scene 01: Before','Surrounding before.','Scene 02: Selected','Selected action.','Scene 03: After','Surrounding after.')
        doc['content'][3]['content'][0]['marks']=[{'type':'bold'}]
        self.f.save_doc(doc);initial=self.f.writing('workspace')['doc']
        with self.browser() as (page,context,base):
            page.get_by_role('button',name='Scene 02: Selected',exact=True).click()
            editor=page.get_by_role('textbox',name='Manuscript editor')
            expect(editor).not_to_contain_text('Surrounding before.')
            held=[]
            def delay(route):
                if not held:held.append((route,route.fetch()))
                else:route.continue_()
            page.route('**/writing/script/ops',delay)
            editor.evaluate("el=>{const e=el.editor;let at;e.state.doc.forEach((n,p)=>{if(n.type.name==='paragraph')at=p+n.nodeSize-1});e.commands.setTextSelection(at);e.view.focus();}")
            page.keyboard.press('Enter');expect(editor.locator('p')).to_have_count(2)
            page.keyboard.type('New paragraph. Again.')
            editor.evaluate("el=>{const d=new DataTransfer();d.setData('text/plain','Pasted one.\\n\\nPasted two.');el.dispatchEvent(new ClipboardEvent('paste',{clipboardData:d,bubbles:true,cancelable:true}));}")
            expect(editor).to_contain_text('Pasted two.')
            editor.evaluate("el=>{el.editor.commands.setTextSelection(3);el.editor.view.focus();}");page.keyboard.press('Enter');page.keyboard.type('Split heading.')
            expect(editor.locator('h2')).to_have_count(2)
            editor.evaluate("el=>{const e=el.editor;let range;e.state.doc.forEach((n,p)=>{if(n.type.name==='paragraph')range={from:p+1,to:p+n.nodeSize-1}});e.commands.setTextSelection(range);e.view.focus();}")
            page.keyboard.press('Backspace');page.keyboard.press('Backspace');expect(editor).not_to_contain_text('Pasted two.')
            page.keyboard.press('Control+s')
            for _ in range(100):
                if held:break
                page.wait_for_timeout(30)
            self.assertTrue(held)
            editor.evaluate("el=>{const e=el.editor;let at;e.state.doc.forEach((n,p)=>{if(at===undefined&&n.type.name==='paragraph')at=p+n.nodeSize-1});e.commands.setTextSelection(at);e.view.focus();}")
            page.keyboard.press('Enter');page.keyboard.type('Typed during ACK.')
            editor.dispatch_event('compositionstart');page.keyboard.insert_text('中文')
            route,response=held[0];route.fulfill(response=response)
            page.wait_for_timeout(200);expect(editor).to_contain_text('Typed during ACK.中文')
            editor.dispatch_event('compositionend');page.keyboard.press('Control+s')
            expect(page.locator('.writing-status > span').first).to_contain_text('Saved on server',timeout=15000)
            current=self.f.writing('workspace')['doc'];ids=[n['attrs']['bid'] for n in current['content']]
            self.assertEqual(len(ids),len(set(ids)))
            self.assertEqual(current['content'][:2],initial['content'][:2]);self.assertEqual(current['content'][-2:],initial['content'][-2:])
            self.assertIn('Typed during ACK.中文',json.dumps(current,ensure_ascii=False))
            self.assertEqual(next(n for n in current['content'] if n['attrs']['bid']==initial['content'][3]['attrs']['bid'])['content'][0]['marks'],[{'type':'bold'}])
            page.get_by_role('button',name='Full manuscript',exact=True).click();expect(editor).to_contain_text('Surrounding after.')

    def test_J3_real_failed_outline_checkpoint_navigation_and_stale_recovery(self):
        from playwright.sync_api import expect
        self.f.init();self.f.save_doc(core.document('Scene 01: Outline','An action.'))
        before=self.f.writing('workspace');scene=before['structure']['scenes'][0]
        with self.browser() as (page,context,base):
            page.get_by_role('button',name='Plot overview',exact=True).click()
            page.evaluate("() => {window.originalTransaction=IDBDatabase.prototype.transaction;IDBDatabase.prototype.transaction=function(stores,mode,...rest){if(mode==='readwrite')throw new Error('Injected outline storage denied');return window.originalTransaction.call(this,stores,mode,...rest);};}")
            attempted=[]
            def offline(route):attempted.append(route.request.post_data_json);route.abort('internetdisconnected')
            page.route('**/writing/structure/metadata',offline)
            summary=page.get_by_role('textbox',name='Summary',exact=True);summary.fill('Never lose this outline draft.')
            page.keyboard.press('Control+s')
            expect(page.get_by_text('Device recovery is unavailable.',exact=False)).to_be_visible()
            open_space(page,'Shot Stage');expect(page.get_by_role('textbox',name='Manuscript editor')).to_be_visible()
            self.assertTrue(page.url.endswith('#story-world'))
            with page.expect_download() as download:page.get_by_role('button',name='Download outline draft',exact=True).click()
            self.assertIn('Never lose',Path(download.value.path()).read_text(encoding='utf8'))
            page.evaluate('() => {IDBDatabase.prototype.transaction=window.originalTransaction;}')
            open_space(page,'Shot Stage')
            expect(page.get_by_role('textbox',name='Manuscript editor')).not_to_be_visible()
            self.assertEqual(self.f.writing('workspace')['structure']['version'],before['structure']['version'])
            remote=self.f.writing('structure/metadata','PATCH',{'baseVersion':before['structure']['version'],'clientMutationId':uuid.uuid4().hex,'scenePatches':[{'sceneKey':scene['sceneKey'],'summary':'Remote summary'}],'lanePatches':[]})
            open_space(page,'Story & World')
            page.get_by_role('button',name='Restore outline draft for review',exact=True).click()
            expect(page.get_by_text('This draft keeps base version',exact=False)).to_be_visible()
            page.get_by_role('button',name='Plot overview',exact=True).click();expect(page.get_by_role('textbox',name='Summary',exact=True)).to_have_value('Never lose this outline draft.')
            sent=len(attempted);page.keyboard.press('Control+s');page.wait_for_timeout(700)
            self.assertEqual(len(attempted),sent)
            open_space(page,'Shot Stage');expect(page.get_by_role('textbox',name='Manuscript editor')).to_be_visible()
            self.assertEqual(self.f.writing('workspace')['structure']['scenes'][0]['summary'],'Remote summary')
            self.assertEqual(self.f.writing('workspace')['docHash'],before['docHash'])

    def test_J2_J4_real_remove_merge_retains_media_and_populates_outline_navigation(self):
        from playwright.sync_api import expect
        from project_docs import story_openapi as story
        self.f.init();self.f.save_doc(core.document('Scene 01: A','@CAST-01 opens.','Scene 02: B','@CAST-02 waits.','Scene 03: C','@CAST-03 leaves.'))
        for shot in self.f.ok('/episodes/'+self.f.ep+'/shots')['items']:self.f.ok('/shots/'+shot['shotId'],'DELETE')
        self.f.ok('/episodes/'+self.f.ep+'/asset-extractions','POST',{});self.f.ok('/episodes/'+self.f.ep+'/storyboards','POST',{})
        shots=self.f.ok('/episodes/'+self.f.ep+'/shots')['items'];self.assertEqual(len(shots),3)
        code,upload,_=self.f.request('/projects/api/'+self.f.slug+'/assets',method='POST',raw=Path('samples/shot_s01.mp4').read_bytes(),headers={'Content-Type':'video/mp4'});self.assertEqual(code,200)
        for shot in shots:
            _,row=story.find_row(self.f.conn,shot['shotId'],'shot');story.mutate_row(self.f.conn,self.f.me,self.f.slug,row['tabKey'],row['rid'],{5:'[video]('+upload['src']+')'})
        self.f.conn.commit();origin=copy.deepcopy(shots[1]['storyOrigin'])
        with self.browser() as (page,context,base):
            page.get_by_role('button',name='Plot overview',exact=True).click()
            rows=page.locator('.writing-scene-metadata');expect(rows.nth(2)).to_contain_text('CAST-03');expect(rows.nth(2).get_by_role('button',name='1 linked shots',exact=True)).to_be_visible()
            page.get_by_role('button',name='Remove scene (keep shots)',exact=True).nth(1).click();page.locator('.writing-preview-action input[type=checkbox]').first.check();page.get_by_role('button',name='Apply selected content',exact=True).click();expect(page.locator('.writing-preview')).not_to_be_visible()
            current={s['shotId']:s for s in self.f.ok('/episodes/'+self.f.ep+'/shots')['items']}
            removed=current[shots[1]['shotId']];self.assertIsNone(removed['sceneId']);self.assertEqual(removed['storyOrigin'],origin)
            self.assertEqual(removed['selectedVideoUrl'],upload['src']);self.assertNotEqual(removed['sceneId'],current[shots[2]['shotId']]['sceneId'])
            # Authorized projection navigates the surviving stable C shot, never removed B.
            row=page.locator('.writing-scene-metadata').last;expect(row).to_contain_text('CAST-03');row.get_by_role('button',name='1 linked shots',exact=True).click()
            expect(page.locator('.shot-detail')).to_be_visible();open_space(page,'Story & World')
            page.get_by_role('button',name='Merge with next',exact=True).first.click();page.locator('.writing-preview-action input[type=checkbox]').first.check();page.get_by_role('button',name='Apply selected content',exact=True).click();expect(page.locator('.writing-preview')).not_to_be_visible()
            current={s['shotId']:s for s in self.f.ok('/episodes/'+self.f.ep+'/shots')['items']};self.assertIsNone(current[shots[1]['shotId']]['sceneId'])
            self.assertEqual(current[shots[1]['shotId']]['storyOrigin'],origin)
            self.assertTrue(all(current[s['shotId']]['selectedVideoUrl']==upload['src'] for s in shots))
            self.assertEqual(current[shots[0]['shotId']]['sceneId'],current[shots[2]['shotId']]['sceneId'])

    def test_J5_real_root_sanitized_print_preserves_hard_breaks(self):
        from playwright.sync_api import expect
        self.f.init();doc=core.document('Scene 01: Print','First','', 'Top','甲　乙','<script>neverExecute()</script>')
        doc['content'][1]['content'] += [{'type':'hardBreak'},{'type':'text','text':'Second'}]
        doc['content'][3]['content'] += [{'type':'hardBreak'},{'type':'hardBreak'},{'type':'text','text':'Bottom'}]
        doc['content'][4]['content'] += [{'type':'hardBreak'},{'type':'text','text':'丙 😀'}]
        self.f.save_doc(doc)
        with self.browser(1280) as (page,context,base):
            self.tools(page,'Import & export');page.get_by_label('Export format').select_option('print');page.get_by_role('button',name='Prepare fixed export',exact=True).click();page.get_by_role('button',name='Open clean print view',exact=True).click()
            frame=page.frame_locator('iframe');expect(frame.locator('body')).to_contain_text('Second')
            result=[]
            for media in ('screen','print'):
                page.emulate_media(media=media)
                metrics=frame.locator('body').evaluate("body=>{const paragraphs=[...body.querySelectorAll('p')];const find=t=>paragraphs.find(p=>p.textContent.includes(t));const y=(p,s)=>{const w=document.createTreeWalker(p,NodeFilter.SHOW_TEXT);let n;while(n=w.nextNode()){const at=n.textContent.indexOf(s);if(at>=0){const r=document.createRange();r.setStart(n,at);r.setEnd(n,at+s.length);return r.getBoundingClientRect().y;}}};const a=find('First'),b=find('Top'),c=find('甲');return {whiteSpace:getComputedStyle(a).whiteSpace,hard:y(a,'Second')-y(a,'First'),blank:y(b,'Bottom')-y(b,'Top'),empty:paragraphs.find(p=>!p.textContent).getBoundingClientRect().height,cjk:y(c,'丙')-y(c,'甲'),active:body.querySelectorAll('script,img,iframe,svg').length};}")
                self.assertEqual(metrics['whiteSpace'],'pre-wrap');self.assertGreater(metrics['hard'],20);self.assertGreater(metrics['blank'],45);self.assertGreater(metrics['empty'],20);self.assertGreater(metrics['cjk'],20);self.assertEqual(metrics['active'],0);result.append({'media':media,**metrics})
            (self.artifacts/'review-print-layout.json').write_text(json.dumps(result,indent=2))

    def test_S1_real_late_ack_after_external_identity_disposal_keeps_newer_A_journal(self):
        from playwright.sync_api import sync_playwright,expect
        from project_docs import repository as repo
        actor=str(uuid.uuid4());token='review-late-'+uuid.uuid4().hex;repo.upsert_member(self.f.conn,actor,'Late ACK second author','admin');self.f.conn.commit();tokens=json.loads(os.environ['OPENBENCH_TOKENS']);tokens[token]=actor;os.environ['OPENBENCH_TOKENS']=json.dumps(tokens)
        try:
            with self.browser() as (page,context,base):
                editor=page.get_by_role('textbox',name='Manuscript editor');page.get_by_role('combobox',name='Manuscript',exact=True).select_option('source:novel');expect(page.locator('.writing-scope')).to_contain_text('Private')
                held=[]
                def delay(route):held.append((route,route.fetch()))
                page.route('**/writing/sources/novel',lambda route:delay(route) if route.request.method=='PUT' else route.continue_())
                editor.fill('A older request');page.keyboard.press('Control+s')
                for _ in range(100):
                    if held:break
                    page.wait_for_timeout(30)
                self.assertTrue(held);editor.fill('A newer unsynced text survives late ACK');page.wait_for_timeout(300)
                other=context.new_page();other.goto(base+'/login');other.locator('input[name=token]').fill(token);other.locator('form button').click();other.wait_for_load_state();page.bring_to_front()
                expect(page.locator('.authoring-workspace')).to_have_count(0,timeout=25000)
                try:held[0][0].fulfill(response=held[0][1])
                except Exception as error:
                    self.assertTrue('cancel' in str(error).lower() or 'handled' in str(error).lower() or 'closed' in str(error).lower(),str(error))
                page.evaluate("window.dispatchEvent(new Event('online'))");page.wait_for_timeout(300)
                path=base+'/aivideo/open/v1/episodes/'+self.f.ep+'/writing/sources/novel'
                self.assertIsNone(context.request.get(path,headers={'X-Writing-Expected-Actor':actor}).json()['data'])
                context.request.post(base+'/login',form={'token':self.f.member_token});page.reload();editor.wait_for();page.get_by_role('combobox',name='Manuscript',exact=True).select_option('source:novel')
                expect(page.locator('.writing-recovery')).to_contain_text('A newer unsynced text survives late ACK')
        finally:
            self.f.conn.execute('delete from projectops.story_record where owner_id=%s',(actor,));self.f.conn.execute('delete from projectops.member where actor_id=%s',(actor,));self.f.conn.commit()
