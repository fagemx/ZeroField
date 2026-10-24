"""N1/N2/N3 through real root/production assets/token auth/PostgreSQL."""
import copy
import json
import os
import unittest
import uuid
from pathlib import Path
import test_writing_core as core
import test_writing_product_browser as product_fixture

@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'),'dedicated review2 PG required')
class WritingReview2ProductTests(unittest.TestCase):
    setUp=product_fixture.WritingProductBrowserTests.setUp
    tearDown=product_fixture.WritingProductBrowserTests.tearDown
    browser=product_fixture.WritingProductBrowserTests.browser
    tools=product_fixture.WritingProductBrowserTests.tools

    def saved(self,page):
        from playwright.sync_api import expect
        page.keyboard.press('Control+s')
        expect(page.locator('.writing-status > span').first).to_contain_text('Saved on server',timeout=15000)

    def at(self,editor,bid,end=True,text=None,before=None):
        editor.evaluate("(el,x)=>{const e=el.editor;let at;e.state.doc.forEach((n,p)=>{if(n.attrs.bid===x.bid)at=p+(x.end?n.nodeSize-1:0)});if(at===undefined)throw new Error('Missing expected fixture block');if(x.before)e.commands.insertContentAt(at,{type:'paragraph',content:[{type:'text',text:x.before}]});else{e.commands.setTextSelection(at);e.view.focus();if(x.text)e.commands.insertContent(x.text);}}",{'bid':bid,'end':end,'text':text,'before':before})

    def test_N1_scene_full_scene_saved_order_and_delayed_navigation(self):
        from playwright.sync_api import expect
        self.f.init();self.f.save_doc(core.document('Scene 01: A','Before.','Scene 02: B','Existing B action.','Scene 03: C','After.'))
        initial=self.f.writing('workspace')['doc'];body=initial['content'][3]['attrs']['bid']
        with self.browser() as (page,context,base):
            editor=page.get_by_role('textbox',name='Manuscript editor')
            page.get_by_role('button',name='Scene 02: B',exact=True).click();expect(editor).not_to_contain_text('Before.')
            self.at(editor,body,text=' First saved edit.');self.saved(page)
            page.get_by_role('button',name='Full manuscript',exact=True).click();expect(editor).to_contain_text('Before.')
            self.at(editor,body,end=False,before='FIRST inserted action.');self.saved(page)
            before=self.f.writing('workspace')['doc'];order=[n['attrs']['bid'] for n in before['content']]
            page.get_by_role('button',name='Scene 02: B',exact=True).click();expect(editor).to_contain_text('FIRST inserted action.')
            self.assertLess(editor.inner_text().index('FIRST inserted action.'),editor.inner_text().index('Existing B action.'))
            held=[]
            def delay(route):
                if held:route.continue_()
                else:held.append((route,route.fetch()))
            page.route('**/writing/script/ops',delay)
            self.at(editor,body,text=' Re-entry edit.');page.keyboard.press('Control+s')
            for _ in range(100):
                if held:break
                page.wait_for_timeout(30)
            self.assertTrue(held)
            page.get_by_role('button',name='Full manuscript',exact=True).click();expect(editor).not_to_contain_text('Before.')
            held[0][0].fulfill(response=held[0][1]);expect(editor).to_contain_text('Before.');expect(editor).to_contain_text('Re-entry edit.')
            after=self.f.writing('workspace')['doc'];self.assertEqual([n['attrs']['bid'] for n in after['content']],order)
            page.get_by_role('button',name='Scene 02: B',exact=True).click();expect(editor).to_contain_text('FIRST inserted action.')
            self.at(editor,body,text=' Final scene edit.');self.saved(page)
            final=self.f.writing('workspace')['doc'];self.assertEqual([n['attrs']['bid'] for n in final['content']],order);self.assertEqual(len(order),len(set(order)))
            self.assertEqual(final['content'][:2],initial['content'][:2]);self.assertEqual(final['content'][-2:],initial['content'][-2:])

    def test_N3_codirty_save_and_genuine_concurrent_metadata_review(self):
        from playwright.sync_api import expect
        self.f.init();self.f.save_doc(core.document('Scene 01: Joint','Existing action.'))
        ws=self.f.writing('workspace');body=ws['doc']['content'][1]['attrs']['bid'];key=ws['structure']['scenes'][0]['sceneKey']
        with self.browser() as (page,context,base):
            editor=page.get_by_role('textbox',name='Manuscript editor');page.get_by_role('button',name='Plot overview',exact=True).click()
            held=[];patches=[]
            def delay(route):
                if held:route.continue_()
                else:held.append((route,route.fetch()))
            page.route('**/writing/script/ops',delay)
            page.on('request',lambda req:patches.append(req.post_data_json) if req.method=='PATCH' and req.url.endswith('/writing/structure/metadata') else None)
            self.at(editor,body,text=' Own manuscript advance.')
            page.get_by_role('textbox',name='Summary',exact=True).fill('Co-dirty summary')
            page.keyboard.press('Control+s')
            for _ in range(100):
                if held:break
                page.wait_for_timeout(30)
            self.assertTrue(held);self.assertEqual(patches,[])
            page.get_by_role('textbox',name='Summary',exact=True).fill('Co-dirty summary updated during ACK')
            held[0][0].fulfill(response=held[0][1])
            expect(page.locator('.writing-status')).not_to_contain_text('Conflict',timeout=10000)
            expect(page.locator('.writing-outline-recovery')).to_have_count(0,timeout=15000)
            current=self.f.writing('workspace');self.assertEqual(current['structure']['scenes'][0]['summary'],'Co-dirty summary updated during ACK')
            self.assertIn('Own manuscript advance.',json.dumps(current['doc']));self.assertEqual(len(patches),1)
            # Real remote metadata, not a fabricated ACK, must still conflict.
            self.at(editor,body,text=' Another manuscript change.')
            page.get_by_role('textbox',name='Summary',exact=True).fill('Private concurrent summary')
            self.f.writing('structure/metadata','PATCH',{'baseVersion':current['structure']['version'],'clientMutationId':uuid.uuid4().hex,'scenePatches':[{'sceneKey':key,'summary':'Remote concurrent summary','payoff':'Unrelated remote payoff'}],'lanePatches':[]})
            page.keyboard.press('Control+s')
            expect(page.locator('.writing-outline-recovery')).to_contain_text('Conflict',timeout=15000)
            expect(page.get_by_role('textbox',name='Summary',exact=True)).to_have_value('Private concurrent summary')
            self.assertEqual(len(patches),1)
            page.get_by_role('button',name='Read current outline for reviewed merge',exact=True).click()
            form=page.get_by_role('form',name='Review outline metadata merge',exact=True)
            expect(form).to_contain_text('Remote concurrent summary');expect(form).to_contain_text('Private concurrent summary')
            form.get_by_label('Value to keep scenePatches:'+key+':summary',exact=True).select_option('local')
            form.get_by_role('button',name='Save explicitly reviewed outline merge',exact=True).click()
            expect(page.locator('.writing-outline-recovery')).to_have_count(0,timeout=15000)
            final=self.f.writing('workspace');self.assertEqual(final['structure']['scenes'][0]['summary'],'Private concurrent summary');self.assertEqual(final['structure']['scenes'][0]['payoff'],'Unrelated remote payoff')
            self.assertEqual(len(patches),2)

    def prepare_abc(self):
        from project_docs import story_openapi as story
        self.f.init();self.f.save_doc(core.document('Scene 01: A','@CAST-01 opens.','Scene 02: B','@CAST-02 waits.','Scene 03: C','@CAST-03 leaves.'))
        for shot in self.f.ok('/episodes/'+self.f.ep+'/shots')['items']:self.f.ok('/shots/'+shot['shotId'],'DELETE')
        self.f.ok('/episodes/'+self.f.ep+'/asset-extractions','POST',{});self.f.ok('/episodes/'+self.f.ep+'/storyboards','POST',{})
        self.ws=self.f.writing('workspace');self.shots=self.f.ok('/episodes/'+self.f.ep+'/shots')['items'];self.assertEqual(len(self.shots),3)
        code,uploaded,_=self.f.request('/projects/api/'+self.f.slug+'/assets',method='POST',raw=Path('samples/shot_s01.mp4').read_bytes(),headers={'Content-Type':'video/mp4'});self.assertEqual(code,200)
        self.url=uploaded['src'];self.origins={s['shotId']:copy.deepcopy(s['storyOrigin']) for s in self.shots}
        for shot in self.shots:
            _,row=story.find_row(self.f.conn,shot['shotId'],'shot');story.mutate_row(self.f.conn,self.f.me,self.f.slug,row['tabKey'],row['rid'],{5:'[video]('+self.url+')'})
        self.f.conn.commit()

    def assert_associations(self,all_removed=False):
        from project_docs import story_openapi as story
        ws=self.f.writing('workspace');active={s['legacySceneId'] for s in ws['structure']['scenes']};current={s['shotId']:s for s in self.f.ok('/episodes/'+self.f.ep+'/shots')['items']}
        for index,shot in enumerate(self.shots):
            self.assertEqual(current[shot['shotId']]['selectedVideoUrl'],self.url);self.assertEqual(current[shot['shotId']]['storyOrigin'],self.origins[shot['shotId']])
            if all_removed or index==1:
                raw=story.shot_meta(self.f.conn,shot['shotId']);self.assertIsNone(raw.get('sceneId'));self.assertNotIn(raw.get('sceneId'),active)
        if not all_removed:self.assertEqual(current[self.shots[2]['shotId']]['sceneId'],ws['structure']['scenes'][1]['legacySceneId'])
        return ws

    def adoption_journey(self,mode):
        from playwright.sync_api import expect
        self.prepare_abc();branch=None
        if mode in ('whole','selected'):
            branch=self.f.writing('branches','POST',{'sourceRef':{'kind':'working'},'expectedSourceHash':self.ws['docHash'],'name':'Root A/C'})
            doc=copy.deepcopy(branch['doc']);del doc['content'][2:4]
            self.f.writing('branches/'+branch['branchId'],'PUT',{'baseVersion':branch['version'],'clientMutationId':uuid.uuid4().hex,'doc':doc,'structure':branch['structure']})
        elif mode=='adaptation':
            self.f.writing('sources/idea','PUT',{'baseVersion':0,'clientMutationId':uuid.uuid4().hex,'doc':core.document('A keeper opens a door and later leaves.'),'structure':{},'composition':{}})
        with self.browser() as (page,context,base):
            editor=page.get_by_role('textbox',name='Manuscript editor')
            if mode=='direct':
                bids=[n['attrs']['bid'] for n in self.ws['doc']['content'][2:4]]
                editor.evaluate("(el,bids)=>{const e=el.editor;let from,to;e.state.doc.forEach((n,p)=>{if(n.attrs.bid===bids[0])from=p;if(n.attrs.bid===bids[1])to=p+n.nodeSize});e.commands.deleteRange({from,to});}",bids)
                self.saved(page)
            elif mode=='adaptation':
                page.get_by_role('combobox',name='Manuscript',exact=True).select_option('source:idea');expect(editor).to_contain_text('A keeper')
                page.get_by_role('button',name='Preview adaptation',exact=True).click();page.locator('.writing-preview-action input[type=checkbox]').first.check();page.get_by_role('button',name='Apply selected content',exact=True).click();expect(page.get_by_role('combobox',name='Manuscript',exact=True)).to_have_value('working:main')
            else:
                page.get_by_role('button',name='Versions',exact=True).click();page.get_by_role('button',name='Compare with working screenplay',exact=True).last.click()
                if mode=='whole':page.get_by_role('button',name='Preview adopting whole manuscript',exact=True).click()
                else:
                    article=page.locator('.writing-versions article').filter(has_text=self.ws['structure']['scenes'][1]['sceneKey'])
                    if not article.count():article=page.locator('.writing-versions article').filter(has_text='Scene 02: B')
                    article.get_by_role('checkbox').check();page.get_by_role('button',name='Preview adopting selected scenes',exact=True).click()
                page.locator('.writing-preview-action input[type=checkbox]').first.check();page.get_by_role('button',name='Apply selected content',exact=True).click();expect(page.locator('.writing-preview')).not_to_be_visible()
            ws=self.assert_associations(all_removed=mode=='adaptation')
            page.get_by_role('button',name='Plot overview',exact=True).click()
            if mode!='adaptation':
                row=page.locator('.writing-scene-metadata').last;expect(row).to_contain_text('CAST-03');expect(row.get_by_role('button',name='1 linked shots',exact=True)).to_be_visible();row.get_by_role('button',name='1 linked shots',exact=True).click()
            else:page.get_by_role('button',name='Shot Stage',exact=False).first.click()
            expect(page.locator('.shot-list')).to_be_visible()
            # Group headings come from current live shot metadata, not a hidden alias filter.
            self.assertNotIn(self.shots[1]['shotId'],[sid for s in ws['structure']['scenes'] for sid in s.get('shotIds',[])])
            alignment=self.f.writing('alignment');item=next(i for i in alignment['items'] if i['shotId']==self.shots[1]['shotId']);self.assertEqual(item['storyAlignment']['state'],'source_removed')

    def test_N2_whole_adoption(self):self.adoption_journey('whole')
    def test_N2_selected_adoption(self):self.adoption_journey('selected')
    def test_N2_adaptation_adoption(self):self.adoption_journey('adaptation')
    def test_N2_direct_root_block_removal(self):self.adoption_journey('direct')
