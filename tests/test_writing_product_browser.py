"""Real root app + compiled static + authenticated HTTP + isolated PostgreSQL journeys.
No component transport, persistence, parser or transaction results are substituted.
"""
import copy
import io
import json
import os
from pathlib import Path
import statistics
import time
import unittest
from contextlib import contextmanager
import test_writing_core as core


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'isolated PG required')
class WritingProductBrowserTests(unittest.TestCase):
    def setUp(self):
        self.f = core.WritingHTTPTests('test_early_save_reload_sources_and_mainline')
        self.f.setUp()
        self.artifacts = Path(os.environ.get('SPEC16_BROWSER_ARTIFACTS', '../integration-validation/browser')).resolve()
        self.artifacts.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.f.tearDown()

    @contextmanager
    def browser(self, width=1920):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width':width, 'height':1080 if width==1920 else 720}, accept_downloads=True)
            base = f'http://127.0.0.1:{self.f.server.server_port}'
            context.route('**/*',lambda route: route.continue_() if route.request.url.startswith(base+'/') else route.abort())
            context.request.post(base+'/login', form={'token':self.f.member_token})
            page = context.new_page()
            errors=[]
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                page.goto(base+'/projects/'+self.f.slug+'/#story-world')
                page.get_by_role('textbox',name='Manuscript editor').wait_for(timeout=30000)
                yield page, context, base
                page.wait_for_load_state('networkidle')
                self.assertEqual(errors, [])
                page.screenshot(path=str(self.artifacts/(self._testMethodName+'.png')), full_page=True)
            except Exception:
                page.screenshot(path=str(self.artifacts/(self._testMethodName+'-failure.png')), full_page=True)
                (self.artifacts/(self._testMethodName+'-failure.html')).write_text(page.content(), encoding='utf8')
                raise
            finally:
                browser.close()

    def tools(self, page, mode):
        toolbar=page.get_by_role('button',name='World, search & files',exact=True)
        if toolbar.get_attribute('aria-pressed')!='true': toolbar.click()
        page.get_by_role('button',name=mode,exact=True).click()

    def test_root_save_private_novel_compare_and_adopt(self):
        from playwright.sync_api import expect
        with self.browser() as (page,context,base):
            editor=page.get_by_role('textbox',name='Manuscript editor')
            editor.fill('Scene 01: Arrival\nThe keeper opens the brass door.')
            page.keyboard.press('Control+s')
            expect(page.locator('.writing-status')).to_contain_text('Saved')
            page.get_by_role('button',name='Shot Stage',exact=False).first.click()
            expect(editor).not_to_be_visible()
            page.get_by_role('button',name='Story & World',exact=False).first.click()
            expect(editor).to_contain_text('The keeper opens the brass door.')
            page.reload(); expect(editor).to_contain_text('The keeper opens the brass door.')
            manuscript=page.get_by_role('combobox',name='Manuscript',exact=True)
            manuscript.select_option('source:novel')
            expect(editor).not_to_contain_text('The keeper opens')
            editor.fill('她心裡仍然想著故鄉。\n  Original novel prose stays.')
            page.keyboard.press('Control+s')
            expect(page.locator('.writing-status')).to_contain_text('Saved')
            page.get_by_role('button',name='Shot Stage',exact=False).first.click()
            page.get_by_role('button',name='Story & World',exact=False).first.click()
            manuscript.select_option('source:novel'); expect(editor).to_contain_text('她心裡仍然想著故鄉。')
            manuscript.select_option('working:main')
            page.get_by_role('button',name='Versions',exact=True).click()
            page.get_by_label('Version or draft name',exact=True).fill('Alternate')
            page.get_by_role('button',name='Write another draft',exact=True).click()
            expect(manuscript).to_have_value(__import__('re').compile('branch:'))
            editor.fill('Scene 01: Arrival\nThe keeper closes the brass door.')
            page.keyboard.press('Control+s'); expect(page.locator('.writing-status')).to_contain_text('Saved')
            if page.get_by_role('button',name='Versions',exact=True).get_attribute('aria-pressed')!='true': page.get_by_role('button',name='Versions',exact=True).click()
            page.get_by_role('button',name='Compare with working screenplay',exact=True).last.click()
            page.get_by_role('button',name='Preview adopting whole manuscript',exact=True).click()
            page.locator('.writing-preview-action input[type=checkbox]').first.check()
            page.get_by_role('button',name='Apply selected content',exact=True).click()
            expect(manuscript).to_have_value('working:main');expect(editor).to_contain_text('The keeper closes the brass door.')
            self.assertIn('她心裡',json.dumps(self.f.writing('sources/novel'),ensure_ascii=False))

    def test_outline_notes_replace_office_and_print(self):
        from playwright.sync_api import expect
        from docx import Document
        self.f.init(); self.f.save_doc(core.document('Scene 01: Arrival','@CAST-01 opens the brass door.','Scene 02: Signal','The keeper waits.'))
        before=self.f.writing('workspace')
        with self.browser(1280) as (page,context,base):
            page.get_by_role('button',name='Plot overview',exact=True).click()
            page.get_by_label('Summary',exact=True).first.fill('An author summary')
            page.get_by_label('Summary',exact=True).first.press('Tab')
            page.wait_for_timeout(500)
            self.assertEqual(self.f.writing('workspace')['docHash'],before['docHash'])
            page.get_by_role('button',name='Move Scene 01: Arrival down',exact=True).click()
            page.locator('.writing-preview-action input[type=checkbox]').first.check()
            page.get_by_role('button',name='Apply selected content',exact=True).click()
            expect(page.locator('.writing-preview')).not_to_be_visible()
            after=self.f.writing('workspace');self.assertEqual(after['structure']['scenes'][1]['sceneKey'],before['structure']['scenes'][0]['sceneKey'])
            self.tools(page,'World & notes')
            page.locator('#writing-tools-bible fieldset select').first.select_option('note')
            page.get_by_label('Title',exact=True).fill('Private form, explicit shared note')
            page.get_by_label('Notes',exact=True).fill('Local note survives a space switch.')
            page.wait_for_timeout(700)
            page.get_by_role('button',name='Shot Stage',exact=False).first.click()
            page.get_by_role('button',name='Story & World',exact=False).first.click()
            self.tools(page,'World & notes')
            page.get_by_role('button',name='Restore private draft for review',exact=True).click()
            expect(page.locator('#writing-tools-bible').get_by_role('textbox',name='Notes',exact=True)).to_have_value('Local note survives a space switch.')
            page.get_by_role('button',name='Create shared entry',exact=True).click()
            expect(page.get_by_text('Saved on the server.',exact=True)).to_be_visible()
            page.get_by_role('button',name='Search & replace',exact=True).click()
            page.get_by_label('Literal search text',exact=True).fill('keeper')
            page.get_by_role('button',name='Search selected scope',exact=True).click()
            page.get_by_role('button',name='Select all eligible items',exact=True).click()
            page.get_by_label('Replacement text',exact=True).fill('watcher')
            page.get_by_role('button',name='Preview selected replacements',exact=True).click()
            page.locator('#writing-tools-search input[aria-label^="Select frozen change"]').first.check()
            page.get_by_role('button',name='Apply selected changes',exact=True).click()
            expect(page.get_by_role('textbox',name='Manuscript editor')).to_contain_text('watcher')
            page.get_by_role('button',name='Import & export',exact=True).click()
            page.get_by_role('button',name='Prepare fixed export',exact=True).click()
            with page.expect_download() as pending:
                page.get_by_role('button',name='Download file',exact=True).click()
            downloaded=pending.value;path=self.artifacts/'roundtrip.docx';downloaded.save_as(path)
            text='\n'.join(p.text for p in Document(path).paragraphs)
            self.assertIn('watcher',text);self.assertIn('@CAST-01',text);self.assertNotIn('Local note survives',text)
            page.get_by_label('Export format').select_option('print')
            page.get_by_role('button',name='Prepare fixed export',exact=True).click()
            page.get_by_role('button',name='Open clean print view',exact=True).click()
            frame=page.frame_locator('iframe');expect(frame.locator('body')).to_contain_text('watcher')
            self.assertEqual(page.locator('iframe').get_attribute('sandbox'),'allow-same-origin allow-modals')
            # Real Office intake through root raw transport; import remains private and mainline unchanged.
            stable_hash=self.f.writing('workspace')['docHash']
            page.get_by_label('Import as').select_option('script')
            page.get_by_label('Manuscript file (.txt, .md or .docx)',exact=True).set_input_files(path)
            page.get_by_role('button',name='Upload for private preview',exact=True).click()
            page.get_by_role('button',name='Confirm private import',exact=True).click()
            expect(page.get_by_text('Private import acknowledged. Adopting it into the working screenplay is a separate preview action.',exact=True)).to_be_visible()
            self.assertEqual(self.f.writing('workspace')['docHash'],stable_hash)

    def test_scoped_impact_live_alignment_and_text_only_build(self):
        from playwright.sync_api import expect
        from project_docs import story_openapi as story
        self.f.init();self.f.save_doc(core.document('Scene 01: Arrival','@CAST-01 opens the door.','Scene 02: Signal','@CAST-01 waits.'))
        for shot in self.f.ok('/episodes/'+self.f.ep+'/shots')['items']:
            self.f.ok('/shots/'+shot['shotId'],'DELETE')
        with self.browser() as (page,context,base):
            page.get_by_role('button',name='Confirm screenplay & build text storyboard',exact=True).click()
            expect(page.get_by_role('textbox',name='Manuscript editor')).not_to_be_visible(timeout=20000)
            shots=[shot for shot in self.f.ok('/episodes/'+self.f.ep+'/shots')['items'] if shot.get('storyOrigin')]
            self.assertEqual(len(shots),2);first,second=shots
            # Valid original bundled video fixture, not a generated model output.
            code,upload,_=self.f.request('/projects/api/'+self.f.slug+'/assets',method='POST',raw=Path('samples/shot_s01.mp4').read_bytes(),headers={'Content-Type':'video/mp4'})
            self.assertEqual(code,200)
            _,row=story.find_row(self.f.conn,first['shotId'],'shot')
            story.mutate_row(self.f.conn,self.f.me,self.f.slug,row['tabKey'],row['rid'],{5:'[video]('+upload['src']+')',6:'Approved'})
            self.f.conn.commit()
            doc=copy.deepcopy(self.f.writing('workspace')['doc']);doc['content'][1]['content']=[{'type':'text','text':'@CAST-01 closes the door.'}];doc['content'][3]['content']=[{'type':'text','text':'@CAST-01 leaves.'}];self.f.save_doc(doc)
            page.get_by_role('button',name='Story & World',exact=False).first.click()
            page.get_by_role('button',name='Review story impact',exact=True).click()
            page.get_by_role('button',name='Preview selected story impact',exact=True).click()
            expect(page.locator('.writing-preview-action')).not_to_have_count(0)
            # Change only an unselected row after the real frozen preview was built.
            _,other=story.find_row(self.f.conn,second['shotId'],'shot')
            story.mutate_row(self.f.conn,self.f.me,self.f.slug,other['tabKey'],other['rid'],{3:'Director preserves this unselected row'})
            self.f.conn.commit()
            page.get_by_role('button',name='Refresh preview freshness',exact=True).click()
            choice=page.locator('.writing-preview-action').filter(has_text='Update text').filter(has_text=first['shotId'])
            choice.locator('input[type=checkbox]').first.check()
            page.get_by_role('button',name='Apply selected content',exact=True).click()
            expect(page.locator('.writing-preview')).not_to_be_visible()
            current={shot['shotId']:shot for shot in self.f.ok('/episodes/'+self.f.ep+'/shots')['items']}
            self.assertEqual(current[first['shotId']]['selectedVideoUrl'],upload['src'])
            self.assertEqual(current[second['shotId']]['description'],'Director preserves this unselected row')
            page.get_by_role('button',name='Shot Stage',exact=False).first.click()
            page.get_by_role('button',name='Film',exact=False).first.click()
            expect(page.get_by_text('Story source differences or unknown provenance:',exact=False)).to_be_visible()
            self.assertTrue(self.f.writing('alignment')['items'])
            self.assertEqual(self.f.conn.execute('select count(*) from projectops.agent_usage_ledger where project_slug=%s',(self.f.slug,)).fetchone()[0],0)

    def test_two_context_conflict_offline_and_actor_privacy(self):
        from playwright.sync_api import expect
        self.f.init();self.f.save_doc(core.document('Scene 01: Room','Shared original'))
        with self.browser(768) as (page,context,base):
            other_context=context.browser.new_context()
            other_context.request.post(base+'/login',form={'token':self.f.member_token})
            other=other_context.new_page();other.goto(base+'/projects/'+self.f.slug+'/#story-world');other.get_by_role('textbox',name='Manuscript editor').wait_for()
            editor=page.get_by_role('textbox',name='Manuscript editor')
            # Hold edits offline in a real browser context, then make a conflicting real HTTP save.
            context.set_offline(True);editor.fill('Private offline edit');page.keyboard.press('Control+s')
            expect(page.locator('.writing-status')).to_contain_text('Saved on this device only')
            doc=copy.deepcopy(self.f.writing('workspace')['doc']);doc['content'][0]['content']=[{'type':'text','text':'Remote edit wins its own base'}];self.f.save_doc(doc)
            context.set_offline(False)
            page.keyboard.press('Control+s')
            expect(page.locator('.writing-status')).to_contain_text('Conflict',timeout=15000)
            expect(editor).to_contain_text('Private offline edit')
            self.assertIn('Remote edit wins its own base',json.dumps(self.f.writing('workspace')['doc']))
            # Authenticated second identity cannot read the author's private source; no replay bypass.
            source=self.f.writing('sources/novel','PUT',{'baseVersion':0,'clientMutationId':'private-browser','doc':core.document('Private novel never shared'),'structure':{},'composition':{}})
            from project_docs import repository as repo
            import uuid
            actor=str(uuid.uuid4());token='test-browser-'+uuid.uuid4().hex
            repo.upsert_member(self.f.conn,actor,'Second author','admin');self.f.conn.commit()
            tokens=json.loads(os.environ['OPENBENCH_TOKENS']);tokens[token]=actor;os.environ['OPENBENCH_TOKENS']=json.dumps(tokens)
            try:
                other_context.request.post(base+'/login',form={'token':token})
                response=other_context.request.get(base+'/aivideo/open/v1/episodes/'+self.f.ep+'/writing/sources/novel')
                self.assertEqual(response.json()['data'],None)
                response=other_context.request.post(base+'/aivideo/open/v1/episodes/'+self.f.ep+'/writing/branches',data={'sourceRef':{'kind':'source','mode':'novel'},'expectedSourceHash':source['docHash'],'name':'Not theirs'},headers={'X-Requested-With':'projects','Idempotency-Key':'other-actor'})
                self.assertNotEqual(response.status,200)
                self.assertNotIn('Private novel never shared',response.text())
            finally:
                self.f.conn.execute('delete from projectops.member where actor_id=%s',(actor,));self.f.conn.commit()
            self.assertNotIn('Private novel never shared',other.locator('body').inner_text())

    def test_real_long_script_timings_and_text_only_build(self):
        from playwright.sync_api import expect
        results=[]
        self.f.init()
        for length in (50000,500000):
            lines=[]
            for index in range(100):lines.extend([f'Scene {index+1:02}: Timing',('word '*((length//100-30)//5))])
            fixture='\n\n'.join(lines)
            fixture += 'x'*(length-len(fixture))
            # Fixture loading uses the preserved legacy whole-script endpoint; editor saves below still use real bounded block ops.
            self.f.ok('/episodes/'+self.f.ep+'/script','PUT',{'scriptContent':fixture})
            self.f.writing('initialize','POST',{'expectedDocHash':self.f.writing('workspace')['docHash']})
            with self.browser() as (page,context,base):
                editor=page.get_by_role('textbox',name='Manuscript editor');editor.click();samples=[]
                for _ in range(20):
                    elapsed=editor.evaluate("el=>new Promise(resolve=>{const start=performance.now();el.focus();document.execCommand('insertText',false,'x');requestAnimationFrame(()=>resolve(performance.now()-start));})")
                    samples.append(elapsed)
                start=time.monotonic();page.get_by_role('button',name='Scene 100: Timing',exact=True).click();switch=(time.monotonic()-start)*1000
                results.append({'codePoints':length,'scenes':100,'inputToAnimationFrameP95ms':sorted(samples)[18],'switchMs':switch,'samplesMs':samples})
                page.keyboard.press('Control+s')
                expect(page.locator('.writing-status')).to_contain_text('Saved')
        (self.artifacts/'long-script-timings.json').write_text(json.dumps(results,indent=2),encoding='utf8')
        print('REAL root production browser timings',json.dumps(results))
