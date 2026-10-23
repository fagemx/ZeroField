"""Console interactions over real authenticated HTTP/PG and existing M8 worker.

Inference is the deterministic loopback fixture in tests/test_agent_console.py.
No paid provider, credentialed public pricing, MCP generation or CLI is used.
Only the explicitly named expired-quote browser response is intercepted.
Run with the owned OPENBENCH_TEST_DB_URI and installed Python Playwright.
"""
import datetime as dt
import json
import os
import re
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from playwright.sync_api import sync_playwright, expect
import test_agent_console as fixture
from project_assistant import agent_registry as agents, console_deployments, orchestration_store as db, orchestrator as cp
from project_docs import repository as repo, story_openapi as story


class ConsoleInteractions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.environ.get('OPENBENCH_TEST_DB_URI'):
            raise RuntimeError('Dedicated PostgreSQL URI is required (no skipped acceptance).')
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)
        cls.evidence = Path(os.environ.get('OPENBENCH_UI_EVIDENCE_DIR', tempfile.mkdtemp(prefix='spec08-console-ui-')))
        cls.evidence.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.fixture = fixture.ConsoleHTTPTests('test_exact_twelve_templates_natural_blank_explicit_cas_and_no_excluded_routes')
        self.fixture.setUp()
        self.errors = []
        self.context = self.browser.new_context(viewport={'width':1600,'height':1050}, extra_http_headers={'Authorization':'Bearer '+self.fixture.member_token})
        self.page = self.context.new_page()
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.url = f'http://127.0.0.1:{self.fixture.server.server_port}/projects/{self.fixture.slug}/'

    def tearDown(self):
        self.page.screenshot(path=str(self.evidence/(self._testMethodName+'-last.png')),full_page=True)
        self.context.close()
        self.fixture.tearDown()
        self.fixture.doCleanups()
        self.assertEqual(self.errors, [])

    def open(self, page='dashboard', resource=''):
        self.page.goto(self.url+'#/agent-console/'+page+('/'+resource if resource else ''))
        expect(self.page.locator('.agent-console')).to_be_visible()
        title={'dashboard':'Dashboard','quickstart':'Quickstart','agents':'Agents','playground':'Playground','api_keys':'Providers & API Keys','spend_rate_limits':'Spend & Rate Limits'}.get(page)
        if title:
            expect(self.page.locator('.agent-console main h1')).to_have_text(title)
        expect(self.page.locator('.agent-console main')).to_have_attribute('aria-busy','false')

    def nav(self, name):
        self.page.locator('.ac-nav nav').get_by_role('button',name=name,exact=False).click()
        expect(self.page.locator('.agent-console main h1')).to_have_text(name)

    def screenshot(self, name):
        self.page.screenshot(path=str(self.evidence/name),full_page=True)

    def test_navigation_templates_keyboard_locale_and_production_context(self):
        self.fixture.prepare()
        self.page.goto(self.url+'#cinema-studio')
        self.page.locator('.sheet-view-switch').get_by_role('button',name='Overview',exact=True).click()
        self.page.get_by_role('button',name='SC01-S01',exact=True).click()
        self.page.locator('.sheet-view-switch').get_by_role('button',name='Review',exact=True).click()
        self.page.locator('.story-shot-tools details summary').click()
        override=self.page.locator('.story-shot-tools details input').first
        override.fill('Preserve unsent shot override')
        self.page.evaluate('window.__productionReview=document.querySelector(".story-shot-tools")')
        self.open_console()
        expect(self.page.locator('.agent-console')).to_be_visible()
        self.assertTrue(self.page.locator('.workbench-app').get_attribute('inert') is not None)
        self.assertEqual(self.page.locator('.ac-nav nav section').count(),4)
        self.assertEqual(self.page.locator('.ac-nav nav button').count(),12)
        for name in ['Dashboard','Providers & API Keys','Playground','Skills','Quickstart','Agents','Sessions','Deployments','Environments & Bridges','Memory Store','Usage & Cost','Spend & Rate Limits']:
            self.nav(name)
        self.nav('Quickstart')
        expect(self.page.locator('.ac-template')).to_have_count(12)
        self.assertEqual(len(set(self.page.locator('.ac-badge').all_text_contents())),3)
        self.screenshot('quickstart-en.png')
        cards=self.page.locator('.ac-template h3').all_text_contents()
        for title in cards:
            self.page.locator('.ac-template').filter(has=self.page.get_by_role('heading',name=title,exact=True)).click()
            preview=self.page.get_by_role('dialog',name=title)
            expect(preview).to_contain_text('Agent configuration')
            preview.get_by_role('button',name='Use this template',exact=True).click()
            expect(self.page.locator('.qs-created')).to_contain_text(title)
            self.page.get_by_role('button',name='Open full editor',exact=True).click()
            expect(self.page.locator('.agent-console main h1')).to_have_text('Agents')
            expect(self.page.get_by_role('button',name='Launch saved configuration',exact=True)).to_be_disabled()
            expect(self.page.get_by_label('Display name',exact=True)).to_have_value(title)
            self.nav('Quickstart')
        self.page.get_by_role('button',name='Start from a blank agent',exact=True).click()
        self.page.get_by_role('button',name='Open full editor',exact=True).click()
        expect(self.page.get_by_role('button',name='Launch saved configuration',exact=True)).to_be_disabled()
        self.nav('Quickstart')
        self.page.get_by_label('Describe the agent requirements').fill('Literal camera assistant, no invented authority')
        self.page.get_by_role('button',name='Draft an agent',exact=True).click()
        # No model is connected for the coordinator here: the builder says so and keeps the request literally.
        expect(self.page.locator('.qs-msg.notice')).to_be_visible()
        self.page.get_by_role('button',name='Open full editor',exact=True).click()
        expect(self.page.get_by_label('System instructions')).to_have_value(re.compile('Literal camera assistant, no invented authority'))
        self.page.get_by_label('Display name',exact=True).fill('Unsaved local agent draft')
        self.page.keyboard.press('Control+k')
        dialog=self.page.get_by_role('dialog',name='Search Console…')
        expect(dialog).to_be_visible()
        dialog.get_by_role('textbox').fill('Skills')
        self.page.keyboard.press('ArrowDown')
        self.page.keyboard.press('Enter')
        expect(dialog).not_to_be_visible()
        expect(self.page.locator('.agent-console main h1')).to_have_text('Skills')
        self.page.go_back()
        expect(self.page.get_by_label('Display name',exact=True)).to_have_value('Unsaved local agent draft')
        self.page.reload()
        expect(self.page.get_by_label('Display name',exact=True)).to_have_value('Unsaved local agent draft')
        peer='browser-peer-'+uuid.uuid4().hex[:8]
        code,_,_=self.fixture.request('/projects/api/projects',method='POST',data={'slug':peer,'title':'Browser peer','template':'zerofield_studio'})
        self.assertEqual(code,200);self.fixture.extra_projects.append(peer)
        self.page.reload()
        self.page.get_by_label('Production workspace',exact=True).select_option(peer)
        expect(self.page).to_have_url(re.compile('/projects/'+peer+'/'))
        self.nav('Quickstart')
        expect(self.page.get_by_label('Describe the agent requirements')).to_have_value('')
        self.page.go_back();self.page.go_back()
        expect(self.page.get_by_label('Display name',exact=True)).to_have_value('Unsaved local agent draft')
        # Return after refresh retains the meaningful prior production page.
        self.page.get_by_role('button',name='Return to Production',exact=True).click()
        expect(self.page).to_have_url(self.url+'#cinema-studio')
        expect(self.page.locator('.story-shot-tools details input').first).to_have_value('Preserve unsent shot override')
        self.open_console()
        self.nav('Quickstart')
        self.page.locator('.agent-console').get_by_role('button',name='繁體中文',exact=True).click()
        expect(self.page.locator('.agent-console main h1')).to_have_text('快速入門')
        expect(self.page.locator('.ac-template h3').first).to_have_text('劇本拆集與分鏡總編審')
        self.screenshot('quickstart-zh.png')
        self.page.set_viewport_size({'width':900,'height':1000})
        self.screenshot('quickstart-responsive.png')
        self.page.locator('.agent-console').get_by_role('button',name='English',exact=True).click()
        self.page.get_by_role('button',name='Return to Production',exact=True).click()
        # Without a reload, Console never unmounts the production inspector/draft.
        override=self.page.locator('.story-shot-tools details input').first
        expect(override).to_have_value('Preserve unsent shot override')
        override.fill('Still the same mounted inspector')
        self.open_console()
        self.page.get_by_role('button',name='Return to Production',exact=True).click()
        expect(override).to_have_value('Still the same mounted inspector')

    def open_console(self):
        # SPEC_15: engineering tools are Ctrl K commands, not standing top-bar buttons.
        self.page.keyboard.press('Control+K')
        self.page.get_by_role('combobox',name='Search or run a command').fill('Agent Console')
        self.page.keyboard.press('Enter')

    def test_versioned_skill_memory_provider_environment_and_manual_cron_forms(self):
        self.open('skills','new')
        self.page.get_by_label('Skill ID',exact=True).fill('browser_skill')
        self.page.get_by_label('Display name',exact=True).fill('Browser skill')
        self.page.get_by_label('Markdown instructions',exact=True).fill('Use only reviewed 35mm camera sources.')
        self.page.get_by_label('Recommended tool IDs (JSON)',exact=True).fill('not json')
        expect(self.page.get_by_role('button',name='Save version',exact=True)).to_be_disabled()
        self.page.get_by_label('Recommended tool IDs (JSON)',exact=True).fill('[]')
        self.page.get_by_role('button',name='Save version',exact=True).click()
        expect(self.page.locator('.ac-list').get_by_role('button',name=re.compile('Browser skill'))).to_be_visible()
        self.page.locator('.ac-list').get_by_role('button',name=re.compile('Browser skill')).click()
        self.page.get_by_role('button',name='Version history',exact=True).click()
        expect(self.page.locator('.ac-json')).to_contain_text('reviewed 35mm camera')
        # A saved creation must not linger as the next "New resource" draft (stale version -> 409).
        self.page.locator('.ac-list').get_by_role('button',name='New resource',exact=True).click()
        expect(self.page.get_by_label('Skill ID',exact=True)).to_have_value('')
        expect(self.page.get_by_label('Skill ID',exact=True)).to_be_enabled()
        self.open('memory_store','style_rules')
        self.page.get_by_label('Entry ID',exact=True).fill('browser_lens')
        self.page.get_by_label('Title',exact=True).fill('Browser lens rule')
        self.page.get_by_label('Markdown memory content',exact=True).fill('Persisted reviewed 35mm continuity rule.')
        self.page.get_by_role('button',name='Save version',exact=True).last.click()
        expect(self.page.locator('.ac-list').get_by_role('button',name=re.compile('Browser lens rule'))).to_be_visible()
        self.assertEqual(self.fixture.api('/memory-stores/style_rules/entries')['entries'][0]['content_md'],'Persisted reviewed 35mm continuity rule.')
        selected=self.fixture.prepare()[0]
        _,row=story.find_row(self.fixture.conn,selected['shotId'],'shot')
        column=next(i for i,value in enumerate(row['cells']) if value in ('Queued','未開始'))
        story.mutate_row(self.fixture.conn,self.fixture.me,self.fixture.slug,row['tabKey'],row['rid'],{column:'Retake'});self.fixture.conn.commit()
        self.page.locator('.ac-list').get_by_role('button',name=re.compile('Browser lens rule')).click()
        self.page.get_by_label('Reviewed shot IDs (comma-separated)').fill(selected['shotId'])
        with self.page.expect_response(lambda response:response.url.endswith('/memory-stores/consolidate')) as consolidated:
            self.page.get_by_role('button',name='Consolidate into selected entry',exact=True).click()
        self.assertEqual(consolidated.value.status,200,consolidated.value.json())
        self.assertIn('source_digest',consolidated.value.json()['entry']['content_md'])
        expect(self.page.locator('.ac-list').get_by_role('button',name=re.compile('Reviewed production evidence'))).to_be_visible()
        self.page.get_by_role('button',name='Version history',exact=True).last.click()
        expect(self.page.locator('.ac-json').last).to_contain_text('source_digest')
        reference=patch.dict(os.environ,{'OPENBENCH_AGENT_KEY_ENVS':'BROWSER_FIXTURE_KEY','BROWSER_FIXTURE_KEY':uuid.uuid4().hex})
        reference.start();self.addCleanup(reference.stop)
        self.open('api_keys','new')
        self.page.get_by_label('Provider reference ID',exact=True).fill('browser_llm')
        self.page.get_by_label('Display name',exact=True).fill('Loopback configured only')
        self.page.get_by_label('Provider configuration — references only (JSON)',exact=True).fill(json.dumps({**self.fixture.config,'api_key_env':'BROWSER_FIXTURE_KEY'}))
        self.page.get_by_label('Allowed agent IDs (JSON)',exact=True).fill('["coordinator"]')
        self.page.get_by_label('Enabled',exact=True).check()
        self.page.get_by_role('button',name='Save version',exact=True).click()
        expect(self.page.get_by_label('Project-only default LLM reference')).to_contain_text('Loopback configured only')
        self.page.get_by_label('Project-only default LLM reference').select_option('browser_llm')
        expect(self.page.get_by_label('Project-only default LLM reference')).to_have_value('browser_llm')
        self.assertEqual(next(a for a in self.fixture.api('/agents')['agents'] if a['agent_key']=='coordinator')['provider_config'],{})
        self.page.get_by_label('Agent',exact=True).select_option('qa_critic')
        self.page.get_by_role('button',name='Run explicit read-only probe',exact=True).click()
        expect(self.page.locator('.ac-json').last).to_contain_text('reachable')
        self.open('environments','env_local_4090')
        expect(self.page.get_by_text('Supported bridges and availability',exact=True)).to_be_visible()
        self.page.get_by_label('Display name',exact=True).fill('Browser local application controls')
        self.page.get_by_role('button',name='Save version',exact=True).click()
        expect(self.page.locator('.ac-list').get_by_role('button',name=re.compile('Browser local application controls'))).to_be_visible()
        self.open('deployments','new')
        self.page.get_by_label('Deployment ID',exact=True).fill('browser_schedule')
        self.page.get_by_label('Display name',exact=True).fill('Browser schedule')
        self.page.get_by_label('Initial prompt',exact=True).fill('Read the current reviewed sources.')
        self.page.get_by_label('Enabled',exact=True).check()
        self.page.get_by_role('button',name='Save version',exact=True).click()
        expect(self.page.locator('.ac-list').get_by_role('button',name=re.compile('browser_schedule'))).to_be_visible()
        self.page.locator('.ac-list').get_by_role('button',name=re.compile('browser_schedule')).click()
        self.page.get_by_role('button',name='Trigger saved deployment',exact=True).click()
        expect(self.page.locator('.agent-console main h1')).to_have_text('Sessions')
        self.page.get_by_role('button',name='Cancel attempt',exact=True).click()
        expect(self.page.get_by_role('button',name='Cancel attempt',exact=True)).to_be_disabled(timeout=20000)
        self.open('deployments','browser_schedule')
        self.page.get_by_label('Trigger schedule',exact=True).select_option('cron')
        self.page.get_by_label('Five-field numeric cron',exact=True).fill('*/15 * * * *')
        self.page.get_by_label('IANA timezone',exact=True).fill('Asia/Taipei')
        with self.page.expect_response(lambda response:response.url.endswith('/agent-console/deployments') and response.request.method=='POST') as saved:
            self.page.get_by_role('button',name='Save version',exact=True).click()
        self.assertEqual(saved.value.status,200,saved.value.json())
        expect(self.page.get_by_label('Five-field numeric cron',exact=True)).to_have_value('*/15 * * * *')
        current=self.fixture.api('/deployments')['deployments'][0]
        self.assertEqual((current['schedule_kind'],current['timezone']),('cron','Asia/Taipei'))
        self.screenshot('deployment-real-manual-cron.png')
        # Invoke the existing due producer at a declared deterministic UTC minute, not a new scheduler.
        produced=console_deployments.produce_due(self.fixture.conn,self.fixture.slug,instant=dt.datetime(2026,10,19,9,0,tzinfo=dt.timezone.utc));self.fixture.conn.commit()
        self.assertEqual(produced,1)
        self.assertEqual(self.fixture.claim_execute('coordinator'),'succeeded')
        due=self.fixture.api('/deployments')['deployments'][0]['latest_trigger']
        self.open('sessions',due['run_id'])
        expect(self.page.get_by_text('Succeeded',exact=False).first).to_be_visible(timeout=20000)
        repo.upsert_member(self.fixture.conn,self.fixture.actor,'Viewer','viewer');self.fixture.conn.commit()
        self.page.reload()
        self.open('deployments','browser_schedule')
        expect(self.page.get_by_role('button',name='Save version',exact=True)).to_be_disabled()
        self.open('playground','qa_critic')
        self.page.get_by_label('Objective',exact=True).fill('Viewers cannot execute')
        expect(self.page.get_by_role('button',name='Run live saved agent',exact=True)).to_be_disabled()
        expect(self.page.get_by_role('button',name='Compile dry-run',exact=True)).to_be_disabled()

    def test_real_draft_save_conflict_mounted_gate_grader_trace_cancel_and_controls(self):
        self.fixture.api('/memory-entries','POST',{'store_key':'style_rules','entry_key':'lens','version':0,'content_md':'Browser fixture uses 35mm optics.'})
        self.open('quickstart')
        self.page.locator('.ac-template').first.click()
        self.page.get_by_role('button',name='Use this template',exact=True).click()
        self.page.get_by_role('button',name='Open full editor',exact=True).click()
        self.page.get_by_role('button',name='Raw JSON view',exact=True).click()
        raw=self.page.get_by_label('Versioned agent JSON')
        config=json.loads(raw.input_value());config.update(provider_config=self.fixture.config,outcome_grader={'enabled':True,'criteria':'Only source-backed content.','grader_agent_key':'qa_critic','max_revisions':0})
        raw.fill(json.dumps(config));key=config['agent_key']
        self.page.get_by_role('button',name='Save version',exact=True).click()
        expect(self.page.get_by_text('Saved explicitly',exact=True)).to_be_visible()
        saved=json.loads(raw.input_value());self.assertEqual(saved['version'],1)
        # A real external CAS update causes a real 409; the local draft survives.
        self.fixture.api('/agents','POST',{'agent_key':key,'version':1,'description':'Changed elsewhere'})
        changed={**saved,'description':'Unsaved version conflict draft'};raw.fill(json.dumps(changed))
        self.page.get_by_role('button',name='Save version',exact=True).click()
        expect(self.page.get_by_role('alert')).to_contain_text('Draft retained')
        self.assertEqual(json.loads(raw.input_value())['description'],'Unsaved version conflict draft')
        with self.page.expect_response(lambda response:response.url.endswith('/agent-console/agents')):
            self.page.get_by_role('button',name='Refresh current data',exact=True).click()
        self.page.once('dialog',lambda dialog:dialog.accept())
        self.page.get_by_role('button',name='Load current saved version into draft…',exact=True).click()
        self.assertEqual(json.loads(raw.input_value())['version'],2)
        self.page.get_by_role('button',name='Launch saved configuration',exact=True).click()
        expect(self.page.get_by_label('Agent',exact=True)).to_have_value(key)
        self.page.get_by_label('Objective',exact=True).fill('Build a synthetic script after explicit confirmation')
        self.page.get_by_role('button',name='Compile dry-run',exact=True).click()
        expect(self.page.get_by_text('Compiled input, tools, payload and usage',exact=True)).to_be_visible()
        self.assertIn('35mm optics',self.page.locator('.ac-json pre').inner_text())
        self.assertIn('shotgen',self.page.locator('.ac-json pre').inner_text())
        self.fixture.responses=[{'content':'','tool_calls':[{'id':'action','type':'function','function':{'name':'studio_ingest_script','arguments':json.dumps({'episode_id':self.fixture.ep,'script':'Scene 01: Browser checkpoint\n@CAST-01 enters @SET-01.'})}}]}]
        before=cp.digest([cp.freeze_tab(self.fixture.conn,self.fixture.slug,t['key']) for t in repo.list_tabs(self.fixture.conn,self.fixture.slug)]);self.fixture.conn.commit()
        with self.page.expect_response(lambda response:response.url.endswith('/playground') and response.request.method=='POST') as response:
            self.page.get_by_role('button',name='Run live saved agent',exact=True).click()
        run=response.value.json()['session_id']
        self.assertEqual(self.fixture.claim_execute(key),'awaiting_gate')
        after=cp.digest([cp.freeze_tab(self.fixture.conn,self.fixture.slug,t['key']) for t in repo.list_tabs(self.fixture.conn,self.fixture.slug)]);self.fixture.conn.commit();self.assertEqual(before,after)
        expect(self.page.get_by_role('heading',name='Needs You — explicit confirmation',exact=True)).to_be_visible(timeout=20000)
        self.page.get_by_label('Decision',exact=True).select_option('0')
        self.assertEqual(cp.digest([cp.freeze_tab(self.fixture.conn,self.fixture.slug,t['key']) for t in repo.list_tabs(self.fixture.conn,self.fixture.slug)]),before);self.fixture.conn.commit()
        self.screenshot('session-confirm-before-write.png')
        self.page.get_by_role('button',name='Confirm and resume',exact=True).click()
        expect(self.page.get_by_role('heading',name='Needs You — explicit confirmation',exact=True)).not_to_be_visible(timeout=20000)
        self.assertEqual(self.fixture.claim_execute(key),'succeeded')
        expect(self.page.locator('.ac-json').filter(has=self.page.get_by_text('Actual consumed configuration, mounts and scorecards',exact=True))).to_contain_text('"score": 95',timeout=20000)
        self.assertIn('Browser checkpoint',story.script(self.fixture.conn,story.episode(self.fixture.conn,self.fixture.ep)));self.fixture.conn.commit()
        self.screenshot('session-actual-grader-trace.png')
        # Current saved agent launch and real M8 cancellation, not OS pause.
        self.open('playground',key);self.page.get_by_label('Objective',exact=True).fill('Cancel this queued local fixture')
        self.page.get_by_role('button',name='Run live saved agent',exact=True).click()
        self.page.get_by_role('button',name='Interrupt attempt',exact=True).click()
        expect(self.page.get_by_role('button',name='Cancel attempt',exact=True)).to_be_disabled(timeout=20000)
        self.open('agents','studio:open');expect(self.page.get_by_text('Read-only system executor',exact=True)).to_have_count(3);expect(self.page.get_by_role('button',name='Save version',exact=True)).to_have_count(0)
        self.open('api_keys');expect(self.page.get_by_text('Server allowlisted credential references',exact=True)).to_be_visible();self.assertEqual(self.page.locator('input[type=password]').count(),0)
        self.open('spend_rate_limits');self.page.get_by_label('Router budget mode').select_option('estimate_soft');expect(self.page.get_by_role('button',name='Save version',exact=True)).to_be_disabled()
        self.screenshot('limits-soft-consent-default-off.png')
        self.page.get_by_label('I explicitly accept estimate-only reservations, possible overages and no guaranteed billing cap for this version.').check()
        expect(self.page.get_by_role('button',name='Save version',exact=True)).to_be_enabled()
        # Consent checkbox alone is not persisted or an execution grant.
        self.assertEqual(self.fixture.api('/spend-rate-limits')['settings']['comfy_router_budget_mode'],'hard')


class ConsoleRouterInteractions(unittest.TestCase):
    open=ConsoleInteractions.open
    nav=ConsoleInteractions.nav
    screenshot=ConsoleInteractions.screenshot

    @classmethod
    def setUpClass(cls):
        ConsoleInteractions.setUpClass.__func__(cls)
        fixture.ConsoleRouterHTTPTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        fixture.ConsoleRouterHTTPTests.tearDownClass()
        ConsoleInteractions.tearDownClass.__func__(cls)

    def setUp(self):
        self.fixture=fixture.ConsoleRouterHTTPTests('test_console_native_quote_allocation_tool_gate_m8_and_eleventh_denied')
        self.fixture.setUp()
        self.errors=[]
        self.context=self.browser.new_context(viewport={'width':1600,'height':1050},extra_http_headers={'Authorization':'Bearer '+self.fixture.member_token})
        self.page=self.context.new_page();self.page.on('pageerror',lambda error:self.errors.append(str(error)))
        self.url=f'http://127.0.0.1:{self.fixture.server.server_port}/projects/{self.fixture.slug}/'
        agents.save_agent(self.fixture.conn,self.fixture.me,self.fixture.slug,{'agent_key':'coordinator','provider_config':{'kind':'openai_compat','base_url':'http://127.0.0.1:9/v1','model':'not-called'}})
        self.fixture.conn.commit()

    tearDown=ConsoleInteractions.tearDown

    def test_native_quote_hard_default_soft_consent_preflight_tenth_eleventh_and_expiry(self):
        shot=self.fixture.prepare()[0]['shotId']
        run=self.fixture.api('/sessions',{'agent_key':'coordinator','objective':'Quote current sources only','episode_id':self.fixture.ep,'client_request_id':'browser-router'})['session_id']
        self.open('sessions',run)
        input=self.page.get_by_label('Exact quote input JSON')
        input.fill(json.dumps({'shot_id':shot,**self.fixture.body}))
        self.page.get_by_role('button',name='Obtain fresh native quote',exact=True).click()
        expect(self.page.get_by_text('Fresh quote — inspect source identity and expiry',exact=True)).to_be_visible()
        expect(self.page.get_by_role('button',name='Dispatch identical reviewed request',exact=True)).to_be_disabled()
        self.assertEqual(self.fixture.submits,[])
        self.assertEqual(self.fixture.api('/spend-rate-limits')['budget']['judge_trial_used_runs'],0)
        self.screenshot('router-hard-unlocked-quote.png')
        self.open('spend_rate_limits')
        self.page.get_by_label('Router budget mode').select_option('estimate_soft')
        self.page.get_by_label('Judge Live-Link protection — strict 10 admissions').check()
        self.page.get_by_label('I explicitly accept estimate-only reservations, possible overages and no guaranteed billing cap for this version.').check()
        self.page.get_by_role('button',name='Save version',exact=True).click()
        expect(self.page.get_by_label('I explicitly accept estimate-only reservations, possible overages and no guaranteed billing cap for this version.')).not_to_be_checked()
        self.assertEqual(self.fixture.api('/spend-rate-limits')['settings']['comfy_router_budget_mode'],'estimate_soft')
        # Nine real application submissions to the declared loopback native fixture, not forged counters.
        for n in range(9):
            self.fixture.api('/sessions/'+run+'/router-quotes',{'shot_id':shot,**self.fixture.body})
            task=self.fixture.ok('/shots/'+shot+'/video-generations','POST',self.fixture.body,{'Idempotency-Key':'browser-prior-'+str(n)})
            self.assertEqual(self.fixture.await_task(task)['status'],'SUCCEEDED')
        self.open('sessions',run)
        input=self.page.get_by_label('Exact quote input JSON')
        input.fill(json.dumps({'shot_id':shot,'appCode':self.fixture.card}))
        self.page.get_by_role('button',name='Preview current source allocation',exact=True).click()
        expect(self.page.get_by_text('All-input preflight and allocation identity',exact=True)).to_be_visible()
        self.page.get_by_role('button',name='Obtain fresh native quote',exact=True).click()
        expect(self.page.get_by_text('Fresh quote — inspect source identity and expiry',exact=True)).to_be_visible()
        self.page.get_by_label('I reviewed the exact sources, inputs, expiry and estimate-only risk for this dispatch.').check()
        self.assertEqual(len(self.fixture.submits),9)
        expect(self.page.locator('.ac-nav footer')).to_contain_text('9 / 10',timeout=10000)
        self.screenshot('router-reviewed-tenth-allocation.png')
        with self.page.expect_response(lambda response:'/shot-video-generations' in response.url and response.request.method=='POST') as response:
            self.page.get_by_role('button',name='Dispatch identical reviewed request',exact=True).click()
        receipt=response.value.json()['data']
        for task_id in receipt['taskIds']:
            self.assertEqual(self.fixture.await_task({'taskId':task_id})['status'],'SUCCEEDED')
        self.assertEqual(len(self.fixture.submits),10)
        expect(self.page.locator('.ac-native-results video')).to_be_visible(timeout=20000)
        expect(self.page.locator('.ac-native-results')).to_contain_text('Succeeded')
        self.assertEqual(self.fixture.api('/spend-rate-limits')['budget']['judge_trial_remaining_runs'],0)
        # The eleventh denial is an actual API admission failure surfaced by the UI.
        input.fill(json.dumps({'shot_id':shot,**self.fixture.body}))
        self.page.get_by_role('button',name='Obtain fresh native quote',exact=True).click()
        expect(self.page.get_by_text('Fresh quote — inspect source identity and expiry',exact=True)).to_be_visible()
        self.page.get_by_label('I reviewed the exact sources, inputs, expiry and estimate-only risk for this dispatch.').check()
        self.page.get_by_role('button',name='Dispatch identical reviewed request',exact=True).click()
        expect(self.page.get_by_role('alert')).to_contain_text('Judge generation admission denied')
        self.assertEqual(len(self.fixture.submits),10)
        self.screenshot('router-eleventh-denied.png')
        # Browser-only expired-response metadata fixture; real quoting remains untouched above.
        def expired(route):
            response=route.fetch();body=response.json()
            for quote in body['quotes']:quote['expires_at']='2000-01-01T00:00:00Z'
            route.fulfill(response=response,json=body)
        self.page.route('**/agent-console/sessions/*/router-quotes',expired)
        self.page.get_by_role('button',name='Obtain fresh native quote',exact=True).click()
        expect(self.page.get_by_text('Quote expired. Preview sources and explicitly re-quote; no automatic paid replay.',exact=True)).to_be_visible()
        expect(self.page.get_by_role('button',name='Dispatch identical reviewed request',exact=True)).to_be_disabled()
        self.assertEqual(len(self.fixture.submits),10)
        self.screenshot('router-expired-metadata-fixture.png')


if __name__=='__main__':
    unittest.main(verbosity=2)
