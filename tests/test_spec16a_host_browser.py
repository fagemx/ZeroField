"""SPEC16A host boundaries through the built root app, authorized HTTP and isolated PG."""
import json
import os
import unittest
import test_writing_core as core
import test_writing_product_browser as fixture
from writing_browser_nav import open_space


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'isolated PG required')
class StoryHostBrowserTests(unittest.TestCase):
    setUp = fixture.WritingProductBrowserTests.setUp
    tearDown = fixture.WritingProductBrowserTests.tearDown
    browser = fixture.WritingProductBrowserTests.browser
    tools = fixture.WritingProductBrowserTests.tools

    def prepare(self):
        self.f.init()
        self.f.save_doc(core.document('Scene 01: Room', '@CAST-01 opens the door.', 'Scene 02: Signal', 'The keeper waits.'))
        self.f.ok('/episodes/'+self.f.ep+'/asset-extractions', 'POST', {})

    def test_quick_asset_card_flushes_unsaved_manuscript(self):
        from playwright.sync_api import expect
        self.prepare()
        with self.browser() as (page, context, base):
            editor = page.get_by_role('textbox', name='Manuscript editor')
            editor.click();page.keyboard.press('Control+End');page.keyboard.type(' Saved before the quick asset card.')
            page.locator('.world-asset').first.click()
            expect(page.locator('.world-wall')).to_be_visible()
            self.assertIn('Saved before the quick asset card.', json.dumps(self.f.writing('workspace')['doc']))
            page.get_by_role('button', name='By scene', exact=True).click()
            expect(editor).to_contain_text('Saved before the quick asset card.')

    def test_wall_toggle_and_quick_card_cannot_drop_uncheckpointed_outline(self):
        from playwright.sync_api import expect
        self.prepare()
        with self.browser() as (page, context, base):
            page.get_by_role('button', name='Plot overview', exact=True).click()
            page.evaluate("""() => {window.originalTransaction=IDBDatabase.prototype.transaction;
                IDBDatabase.prototype.transaction=function(stores,mode,...rest){if(mode==='readwrite')throw new Error('Injected storage denied');
                return window.originalTransaction.call(this,stores,mode,...rest);};}""")
            page.route('**/writing/structure/metadata', lambda route: route.abort('internetdisconnected'))
            page.get_by_role('textbox', name='Summary', exact=True).first.fill('Keep this outline when the wall is refused.')
            page.get_by_role('button', name='Cast & sets', exact=True).click()
            expect(page.get_by_role('textbox', name='Manuscript editor')).to_be_visible()
            page.locator('.world-asset').first.click()
            expect(page.get_by_role('textbox', name='Manuscript editor')).to_be_visible()
            expect(page.get_by_role('textbox', name='Summary', exact=True).first).to_have_value('Keep this outline when the wall is refused.')
            page.evaluate('() => {IDBDatabase.prototype.transaction=window.originalTransaction;}')
            page.get_by_role('button', name='Cast & sets', exact=True).click()
            expect(page.locator('.world-wall')).to_be_visible()

    def test_source_jump_forces_script_and_is_not_replayed_after_another_visit(self):
        from playwright.sync_api import expect
        self.prepare()
        self.f.ok('/episodes/'+self.f.ep+'/storyboards', 'POST', {})
        with self.browser() as (page, context, base):
            page.get_by_role('button', name='Cast & sets', exact=True).click()
            expect(page.locator('.world-wall')).to_be_visible()
            open_space(page, 'Shot Stage')
            page.locator('.shot-list li button').filter(has_text='SC01-S01').click()
            page.get_by_role('button', name='Go to source', exact=True).click()
            expect(page.get_by_role('textbox', name='Manuscript editor')).to_be_visible()
            page.get_by_role('button', name='Scene 02: Signal', exact=True).click()
            expect(page.get_by_role('textbox', name='Manuscript editor')).to_contain_text('The keeper waits.')
            open_space(page, 'Shot Stage');open_space(page, 'Story & World')
            page.get_by_role('button', name='Full manuscript', exact=True).click()
            expect(page.get_by_role('textbox', name='Manuscript editor')).to_contain_text('The keeper waits.')

    def test_pending_novel_survives_lost_ack_and_reloads_without_a_second_write(self):
        from playwright.sync_api import expect
        self.prepare()
        with self.browser() as (page, context, base):
            page.evaluate("slug=>sessionStorage.setItem('zf.start:'+slug,JSON.stringify({mode:'novel',text:'Original pending prose. Never lose this.',ratio:'16:9',style:'88123'}))", self.f.slug)
            sent = []
            def lose_ack(route):
                sent.append(route.request.post_data_json)
                response = route.fetch()
                self.assertEqual(response.status, 200)
                route.abort('internetdisconnected')
            page.route('**/writing/sources/novel', lambda route: lose_ack(route) if route.request.method == 'PUT' else route.continue_())
            page.reload()
            expect(page.locator('.writing-start-recovery')).to_contain_text('could not be opened')
            pending = page.evaluate("slug=>JSON.parse(sessionStorage.getItem('zf.start:'+slug))", self.f.slug)
            self.assertEqual(pending['text'], 'Original pending prose. Never lose this.')
            self.assertEqual(pending['handoff']['stage'], 'source-save')
            self.assertIn('Original pending prose.', json.dumps(self.f.writing('sources/novel')['doc']))
            page.unroute('**/writing/sources/novel')
            page.reload()
            expect(page.get_by_role('combobox', name='Manuscript', exact=True)).to_have_value('source:novel')
            expect(page.get_by_role('textbox', name='Manuscript editor')).to_contain_text('Original pending prose.')
            expect(page.locator('.writing-start-recovery')).not_to_be_visible()
            self.assertIsNone(page.evaluate("slug=>sessionStorage.getItem('zf.start:'+slug)", self.f.slug))
            self.assertEqual(self.f.writing('sources/novel')['version'], 1)
            self.assertEqual(len(sent), 1)

    def test_pending_screenplay_keeps_existing_working_script_and_opens_private_branch(self):
        from playwright.sync_api import expect
        self.prepare()
        before = self.f.writing('workspace')['docHash']
        with self.browser() as (page, context, base):
            page.evaluate("slug=>sessionStorage.setItem('zf.start:'+slug,JSON.stringify({mode:'script',text:'Scene 01: Alternate\\nA different screenplay.',ratio:'16:9',style:'88123'}))", self.f.slug)
            page.reload()
            expect(page.get_by_role('combobox', name='Manuscript', exact=True)).to_have_value(__import__('re').compile('branch:'))
            expect(page.get_by_role('textbox', name='Manuscript editor')).to_contain_text('A different screenplay.')
            expect(page.locator('.writing-start-recovery')).not_to_be_visible()
            self.assertEqual(self.f.writing('workspace')['docHash'], before)
            self.assertIsNone(page.evaluate("slug=>sessionStorage.getItem('zf.start:'+slug)", self.f.slug))

    def test_identity_change_during_build_stops_before_extraction_and_storyboards(self):
        from playwright.sync_api import expect
        from project_docs import repository as repo
        import uuid
        self.prepare()
        actor, token = str(uuid.uuid4()), 'test-host-'+uuid.uuid4().hex
        repo.upsert_member(self.f.conn, actor, 'Second host author', 'admin');self.f.conn.commit()
        tokens = json.loads(os.environ['OPENBENCH_TOKENS']);tokens[token] = actor
        os.environ['OPENBENCH_TOKENS'] = json.dumps(tokens)
        try:
            with self.browser() as (page, context, base):
                later = []
                def change_identity(route):
                    if route.request.method != 'PUT':
                        route.continue_();return
                    self.assertEqual(route.request.headers.get('x-writing-expected-actor'), self.f.actor)
                    response = route.fetch()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(context.request.post(base+'/login', form={'token':token}, max_redirects=0).status, 303)
                    route.fulfill(response=response)
                page.route('**/episodes/'+self.f.ep+'/settings', change_identity)
                page.on('request', lambda request: later.append(request.url) if request.method=='POST' and any(request.url.endswith('/'+tail) for tail in ('asset-extractions','storyboards')) else None)
                page.locator('.studio-primary').click()
                page.locator('.breakdown-dialog button[type=submit]').click()
                expect(page.locator('.center-note[role=alert]')).to_be_visible()
                self.assertEqual(later, [])
        finally:
            self.f.conn.execute('delete from projectops.member where actor_id=%s', (actor,));self.f.conn.commit()

    def test_structure_limit_keeps_server_text_downloadable_and_allows_exit(self):
        from pathlib import Path
        from playwright.sync_api import sync_playwright, expect
        original = '\n\n'.join(['Scene 01: Long manuscript'] + ['Line '+str(i) for i in range(1002)])
        saved = self.f.ok('/episodes/'+self.f.ep+'/script', 'PUT', {'scriptContent':original})
        # The legacy import converts paragraph separators; download must match the
        # authoritative episode text, not reconstruct the pre-import formatting.
        server_text = saved['scriptContent']
        self.assertIn('Line 1001', server_text)
        status, payload = self.f.call('/episodes/'+self.f.ep+'/writing/workspace')
        self.assertEqual(status, 413, payload)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(accept_downloads=True)
            base = f'http://127.0.0.1:{self.f.server.server_port}'
            context.request.post(base+'/login', form={'token':self.f.member_token})
            page = context.new_page()
            page.goto(base+'/projects/'+self.f.slug+'/#story-world')
            expect(page.locator('.authoring-workspace')).to_contain_text('1,000 structure units')
            with page.expect_download() as downloaded:
                page.get_by_role('button', name='Download current draft', exact=True).click()
            self.assertEqual(Path(downloaded.value.path()).read_text(encoding='utf8'), server_text)
            open_space(page, 'Shot Stage')
            expect(page.locator('.studio-space-btn')).to_contain_text('Shot Stage')
            browser.close()

    def test_initial_workspace_read_failure_does_not_trap_navigation(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context()
            base = f'http://127.0.0.1:{self.f.server.server_port}'
            context.request.post(base+'/login', form={'token':self.f.member_token})
            page = context.new_page()
            page.route('**/writing/workspace', lambda route: route.fulfill(status=413, content_type='application/json', body=json.dumps({'message':'Injected structure limit'})))
            page.goto(base+'/projects/'+self.f.slug+'/#story-world')
            expect(page.locator('.authoring-workspace')).to_contain_text('Injected structure limit')
            open_space(page, 'Shot Stage')
            expect(page.locator('.studio-space-btn')).to_contain_text('Shot Stage')
            browser.close()


if __name__ == '__main__':
    unittest.main()
