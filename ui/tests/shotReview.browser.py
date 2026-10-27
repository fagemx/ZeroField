"""Real same-component review interactions; handoff admission is mocked, not inference.

Run with the dedicated OPENBENCH_TEST_DB_URI and installed Python Playwright.
The HTTP/DB fixture persists ordinary status/media edits; only escalation and
allocation-preview responses are intercepted. No model/provider is contacted.
"""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
import test_story_openapi as story_fixture
from project_docs import repository as repo, story_openapi as story
from playwright.sync_api import sync_playwright, expect
from PIL import Image


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'dedicated PostgreSQL URI required')
class ShotReviewInteractions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)
        cls.temp = tempfile.TemporaryDirectory(prefix='spec07-shot-review-')
        cls.evidence = Path(os.environ.get('OPENBENCH_UI_EVIDENCE_DIR', cls.temp.name))
        cls.evidence.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.temp.cleanup()

    def setUp(self):
        self.fixture = story_fixture.StoryHTTPTests('test_catalog_envelope_validation_and_auth')
        self.fixture.setUp()
        self.shot = self.fixture.prepare()[0]
        self.id = self.shot['shotId']
        self.handoffs, self.errors = [], []
        self.context = self.browser.new_context(viewport={'width':1440,'height':1000},
            extra_http_headers={'Authorization':'Bearer ' + self.fixture.member_token})
        self.page = self.context.new_page()
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.route('**/*:escalate', self.mock_handoff)

    def tearDown(self):
        self.context.close()
        self.fixture.tearDown()
        self.assertEqual(self.errors, [])

    def mock_handoff(self, route):
        self.handoffs.append(route.request.post_data_json)
        route.fulfill(json={'code':0,'data':{'runId':None,'status':'QUEUED'}})

    def image(self, color):
        content = io.BytesIO()
        Image.new('RGB',(32,32),color).save(content,format='PNG')
        aid = repo.put_asset(self.fixture.conn,self.fixture.slug,data=content.getvalue(),content_type='image/png',actor_id=self.fixture.actor)
        return f'/projects/api/{self.fixture.slug}/assets/{aid}'

    def prepare_row(self, status, video=False):
        self.image_url = self.image('green')
        edits = {4:f'![Image]({self.image_url})',6:status}
        if video:
            raw = (ROOT/'samples/shot_s01.mp4').read_bytes()
            aid = repo.put_asset(self.fixture.conn,self.fixture.slug,data=raw,content_type='video/mp4',actor_id=self.fixture.actor)
            edits[5] = f'[video](/projects/api/{self.fixture.slug}/assets/{aid})'
        story.mutate_row(self.fixture.conn,self.fixture.me,self.fixture.slug,'cinema-studio',self.shot['rowId'],edits)
        self.fixture.conn.commit()
        self.page.goto(f'http://127.0.0.1:{self.fixture.server.server_port}/projects/{self.fixture.slug}/#cinema-studio')
        # SPEC_15 Shot Stage: pick the shot in the overview, then open it in Review; its controls stand in the detail column.
        self.page.locator('.sheet-view-switch').get_by_role('button',name='Overview',exact=True).click()
        self.page.get_by_role('button',name=self.shot['shotIndex'],exact=True).click()
        self.page.locator('.sheet-view-switch').get_by_role('button',name='Review',exact=True).click()
        self.tools = self.page.locator('.story-shot-tools')
        expect(self.tools.locator('.story-takes figure').first).to_be_visible()
        # SPEC_19 R3: the shot column has no status menu any more. Its status moves through "Retake (R)", a take's ✓ (adoption) and
        # the folded "…" menu (Mark as blocked / Unblock / Remove from the cut, Replace Upload and the other rarer actions).
        self.column = self.page.locator('.shot-detail.shot-film')
        self.hero = self.tools.get_by_role('button',name='Approved composition → Closed Hero',exact=True)
        self.page.evaluate('window.__sameReview=document.querySelector(".story-shot-tools")')
        self.tools.locator('details summary').click()
        self.draft = self.tools.locator('details input').first
        expect(self.draft).to_be_visible()
        self.draft.fill('Keep my unsent card override')

    def assert_same_review(self):
        self.assertTrue(self.page.evaluate('window.__sameReview === document.querySelector(".story-shot-tools")'))
        expect(self.draft).to_have_value('Keep my unsent card override')

    def shot_menu(self, name):
        """Run one action of the shot column's folded "…" menu."""
        self.column.locator('.shot-menu > summary').click()
        item = self.column.locator('.shot-menu').get_by_role('menuitem',name=name,exact=True)
        expect(item).to_be_enabled()
        item.click()

    def set_status(self, name):
        """Mark as blocked / Unblock through the "…" menu: one table edit of the status cell."""
        with self.page.expect_response(lambda response: response.url.endswith('/table-edit') and response.request.method=='POST') as saved:
            self.shot_menu(name)
        self.assertEqual(saved.value.status,200)

    def retake(self):
        button = self.column.get_by_role('button',name='Retake (R)',exact=True)
        expect(button).to_be_enabled()
        with self.page.expect_response(lambda response: response.url.endswith('/table-edit') and response.request.method=='POST') as saved:
            button.click()
        self.assertEqual(saved.value.status,200)

    def adopt(self, number):
        """The take's ✓: POST /shots/{id}/adoptions puts it in the cut and writes Approved."""
        button = self.column.get_by_role('button',name=f'Adopt Take {number}',exact=True)
        expect(button).to_be_enabled()
        with self.page.expect_response(lambda response: response.url.endswith('/adoptions') and response.request.method=='POST') as adopted:
            button.click()
        self.assertEqual(adopted.value.status,200)

    def click_handoff(self, expected):
        with self.page.expect_request(lambda request: request.url.endswith(':escalate') and request.method=='POST') as sent:
            self.hero.click()
        self.assertEqual(sent.value.post_data_json,expected)
        expect(self.hero).to_be_enabled()
        self.assertEqual(self.handoffs,[expected])

    def test_status_changes_update_actions_without_reopen_and_keep_video_source(self):
        self.prepare_row('Queued',video=True)
        expect(self.tools.locator('.story-escalation')).to_have_count(0)
        self.retake()
        expect(self.tools.locator('.story-escalation')).to_be_visible(timeout=4000)
        expect(self.hero).to_be_disabled()
        self.assert_same_review()
        self.set_status('Mark as blocked')
        expect(self.tools.locator('.story-escalation')).to_have_count(0,timeout=4000)
        self.set_status('Unblock')
        self.adopt(1)  # the take already in the cell, now adopted: Approved
        expect(self.hero).to_be_enabled(timeout=4000)
        self.assert_same_review()
        selected = next(c for c in self.fixture.ok('/shots/'+self.id+'/videos')['items'] if c['selected'])
        self.click_handoff({'chainMode':'open_previz_to_closed_hero','referenceSourceVideoId':selected['videoId']})
        self.assert_same_review()
        self.page.screenshot(path=str(self.evidence/'status-video-review.png'),full_page=True)

    def test_approved_image_only_handoff_and_localized_preflight_blockers(self):
        self.prepare_row('Approved')
        self.assertEqual(self.fixture.ok('/shots/'+self.id+'/videos')['items'],[])
        expect(self.hero).to_be_enabled(timeout=4000)
        selected = next(c for c in self.fixture.ok('/shots/'+self.id+'/images')['items'] if c['selected'])
        self.click_handoff({'chainMode':'open_previz_to_closed_hero','referenceSourceImageId':selected['imageId']})
        self.assert_same_review()
        self.page.locator('.sheet-review header button').first.click()
        card = self.page.locator('.sheet-card').filter(has=self.page.get_by_role('button',name=self.shot['shotIndex'],exact=True))
        card.get_by_role('checkbox').check()
        allocation = {'ready':False,'allocationId':'fixture-plan','summary':{'openWeightsShotCount':1,'closedHeroShotCount':0,'cloudBurstShotCount':0},'allocations':[{'shotId':self.id,'complexityTier':'standard','assignedCardId':'h3-reference','tier':'open_weights','ready':False,'configuration_blockers':['required_media_missing:generate:51.image','unrecognized_internal_blocker']} ]}
        self.page.route('**/shots:plan-allocation',lambda route: route.fulfill(json={'code':0,'data':allocation}))
        self.page.get_by_role('button',name='Preview allocation',exact=True).click()
        preview = self.page.locator('.story-allocation')
        expect(preview).to_contain_text('Required media is missing')
        expect(preview).not_to_contain_text('required_media_missing')
        expect(preview).not_to_contain_text('unrecognized_internal_blocker')
        expect(preview).to_contain_text('51.image')
        self.page.get_by_role('button',name='繁體中文',exact=True).click()
        expect(preview).to_contain_text('缺少必要媒體')
        self.page.screenshot(path=str(self.evidence/'image-handoff-zh-blockers.png'),full_page=True)

    def test_media_refresh_ignores_an_older_inflight_candidate_response(self):
        # An image-only shot has no video to adopt, so the status moves through Retake and the "…" menu; what matters here is that
        # the first, late answer for the takes never replaces the newer first frame.
        self.prepare_row('Queued')
        old_images = self.fixture.ok('/shots/'+self.id+'/images')
        held = []
        def delay_first(route):
            if not held:
                held.append(route)
            else:
                route.continue_()
        self.page.route('**/shots/'+self.id+'/images**',delay_first)
        self.retake()
        self.page.wait_for_timeout(150)
        self.assertEqual(len(held),1)
        self.set_status('Mark as blocked')
        self.set_status('Unblock')
        replacement = io.BytesIO()
        Image.new('RGB',(32,32),'blue').save(replacement,format='PNG')
        with self.page.expect_file_chooser() as chooser:
            self.shot_menu('Replace Upload')
        with self.page.expect_response(lambda response: response.url.endswith('/table-edit') and response.request.method=='POST') as saved:
            chooser.value.set_files({'name':'new-keyframe.png','mimeType':'image/png','buffer':replacement.getvalue()})
        self.assertEqual(saved.value.status,200)
        # Wait for the persisted media edit, not merely the upload's local preview.
        selected = next(c for c in self.fixture.ok('/shots/'+self.id+'/images')['items'] if c['selected'])
        self.assertNotEqual(selected['url'],self.image_url)
        frame = self.tools.locator('figure').filter(has=self.page.locator('img[src="'+selected['url']+'"]'))
        expect(frame).to_be_visible()
        held[0].fulfill(json={'code':0,'data':old_images})
        self.page.wait_for_timeout(150)
        expect(frame).to_be_visible()
        expect(frame.get_by_role('button',name='Selected Take',exact=True)).to_have_attribute('aria-pressed','true')
        self.assert_same_review()
        self.page.screenshot(path=str(self.evidence/'media-refresh-stale-response.png'),full_page=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
