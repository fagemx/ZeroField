"""SPEC_20 R44-1 and R44-2: a production created "From a story" is the studio template without its samples.

It keeps the five planning pages, their columns and the pipeline, but has no sample brief, cast, sets, shots or
clips, and the pasted screenplay becomes the working screenplay through the real browser start helper
(ui/src/writing/writingStartHandoff.js, run in Node against a real server). No model, GPU or provider is called.
"""
import json
import os
from pathlib import Path
import subprocess
import unittest

from project_docs import doc_schema, markdown_import, repository as repo, story_openapi as story, templates
from project_docs.doc_schema import doc_text
import test_product_http as product_fixture

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ('The Last Signal', 'Kael', 'Observatory', 'observatory', 'CAST-01', 'SET-01', 'VFX-01', 'S01', 'Queued')
SPILLWAY = ('SPILLWAY\n\n'
            '1. INT. DAM CONTROL ROOM - NIGHT\n'
            'Rain hammers the glass. NORA VESK (40s) faces the gauges.\n\n'
            'NORA\n"The gate is jammed."\n\n'
            '2. EXT. DAM WALKWAY - NIGHT\n'
            'ELI VESK (20s) grips the rail and looks straight at us.\n\n'
            '3. INT. DAM CONTROL ROOM - NIGHT\n'
            'Nora pulls the lever as the water rises.')
SHEETS = ('soul-cast', 'cinema-studio', 'openjutsu-lab')
# The real start helper, with a transport shaped like the browser's story request (envelope, bearer, idempotency).
START = r'''
import {readFileSync} from 'node:fs';
import {persistStartHandoff} from './ui/src/writing/writingStartHandoff.js';
const {url, token, episode, text} = JSON.parse(readFileSync(0, 'utf8'));
const transport = async (tail, method = 'GET', body, options = {}) => {
  const headers = {'Authorization': 'Bearer ' + token, 'X-Requested-With': 'projects'};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (options.idempotencyKey) headers['Idempotency-Key'] = options.idempotencyKey;
  const response = await fetch(`${url}/episodes/${episode}/writing/${tail}`, {method, headers, body: body === undefined ? undefined : JSON.stringify(body)});
  const payload = await response.json();
  if (!response.ok || payload.code !== 0) throw Object.assign(new Error(JSON.stringify(payload)), {status: response.status, code: payload.code});
  return payload.data;
};
const ref = await persistStartHandoff({transport, start: {mode: 'script', text}, name: 'Story start', actorId: 'r44-start',
  idempotencyKey: 'r44-start-' + episode, onCheckpoint: () => true});
console.log(JSON.stringify(ref));
'''


def table_headers(doc):
    table = next(node for node in doc['content'] if node['type'] == 'table')
    return [doc_text({'type': 'doc', 'content': cell.get('content', [])}) for cell in table['content'][0]['content']], len(table['content'])


class StoryStartTemplateTests(unittest.TestCase):
    def test_story_start_keeps_the_pages_and_columns_but_no_sample_content(self):
        full = templates.tab_specs('zerofield_studio', 'Spillway', '')
        bare = templates.tab_specs('zerofield_studio', 'Spillway', '', samples=False)
        self.assertEqual([s[:3] for s in bare], [s[:3] for s in full], 'the same five pages, titles and surfaces')
        by_key = {s[0]: s for s in bare}
        self.assertEqual(by_key['director-brief'][3], '', 'the brief is blank, so the story becomes the working screenplay')
        self.assertEqual(by_key['comfy-pipeline'][3], {s[0]: s for s in full}['comfy-pipeline'][3], 'the pipeline page is structure')
        for key in SHEETS:
            with self.subTest(sheet=key):
                md = by_key[key][3]
                for word in SAMPLES:
                    self.assertNotIn(word, md)
                doc, values = markdown_import.markdown_to_doc(md, tab_keys=set(), image_src=lambda _: None)
                templates.configure_doc(key, doc)
                doc, _ = doc_schema.validate_doc(doc, slug='r44-start')
                sample_doc, _ = markdown_import.markdown_to_doc({s[0]: s for s in full}[key][3], tab_keys=set(), image_src=lambda _: None)
                headers, rows = table_headers(doc)
                self.assertEqual(rows, 1, 'only the header row')
                self.assertEqual(headers, table_headers(sample_doc)[0])
                self.assertEqual(next(n for n in doc['content'] if n['type'] == 'table')['attrs']['column_types'], templates.COLUMN_TYPES[key])
                self.assertEqual(values, {})

    def test_the_template_itself_still_carries_its_samples(self):
        md = ''.join(s[3] for s in templates.tab_specs('zerofield_studio', 'Test Film', ''))
        for word in ('Updraft', 'Noa', 'The Canyon at Sunrise', 'VFX-01'):
            self.assertIn(word, md)


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'set OPENBENCH_TEST_DB_URI')
class StoryStartProductionTests(unittest.TestCase):
    request = product_fixture.ProductHTTPTests.request

    def setUp(self):
        product_fixture.ProductHTTPTests.setUp(self)
        self.created = []

    def tearDown(self):
        from psycopg import sql
        self.conn.rollback()
        with self.conn.cursor() as cur:
            cur.execute("SELECT table_name FROM information_schema.columns WHERE table_schema='projectops' AND column_name='project_slug'")
            tables = [r[0] for r in cur.fetchall() if r[0] not in ('agent_resource_revision', 'agent_usage_ledger')]
            for slug in self.created:
                for name in tables:
                    cur.execute(sql.SQL('DELETE FROM projectops.{} WHERE project_slug=%s').format(sql.Identifier(name)), (slug,))
                cur.execute('DELETE FROM projectops.project WHERE slug=%s', (slug,))
            cur.execute('DELETE FROM projectops.story_record WHERE owner_id=%s', (self.actor,))
        self.conn.commit()
        product_fixture.ProductHTTPTests.tearDown(self)

    def create(self, **extra):
        slug = 'r44-' + os.urandom(5).hex()
        self.created.append(slug)
        code, payload, _ = self.request('/projects/api/projects', method='POST', data={
            'slug': slug, 'title': 'Spillway', 'template': 'zerofield_studio', 'status': 'planning', 'summary': '', **extra})
        self.assertEqual(code, 200, payload)
        self.conn.rollback()
        return slug

    def start(self, slug):
        result = subprocess.run(['node', '--input-type=module', '-e', START], cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=60,
                                input=json.dumps({'url': f'http://127.0.0.1:{self.server.server_port}{story.BASE}', 'token': self.member_token,
                                                  'episode': f'ep_{slug}_01', 'text': SPILLWAY}))
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def writing(self, slug, tail):
        code, payload, _ = self.request(f'{story.BASE}/episodes/ep_{slug}_01/writing/{tail}')
        self.assertEqual(code, 200, payload)
        return payload['data']

    def pipeline(self, slug):
        with self.conn.cursor() as cur:
            cur.execute('SELECT definition FROM projectops.flow_definition WHERE project_slug=%s AND tab_key=%s', (slug, 'comfy-pipeline'))
            return cur.fetchone()[0]

    def test_a_story_production_has_no_template_samples_and_keeps_its_structure(self):
        slug, template = self.create(samples=False), self.create()
        self.assertEqual([t['key'] for t in repo.list_tabs(self.conn, slug)], [t['key'] for t in repo.list_tabs(self.conn, template)])
        for key in SHEETS:
            with self.subTest(sheet=key):
                self.assertEqual(story.table_rows(self.conn, slug, key), [])
                self.assertTrue(story.table_rows(self.conn, template, key), 'a production made from the template keeps its rows')
                self.assertEqual(table_headers(repo.get_tab(self.conn, slug, key)['doc'])[0],
                                 table_headers(repo.get_tab(self.conn, template, key)['doc'])[0])
        brief = json.dumps(repo.get_tab(self.conn, slug, 'director-brief')['doc'])
        for word in ('The Last Signal', 'Kael', 'Observatory'):
            self.assertNotIn(word, brief)
        code, payload, _ = self.request(f'{story.BASE}/episodes/ep_{slug}_01/shots?limit=100')
        self.assertEqual(code, 200, payload)
        self.assertEqual(payload['data']['items'], [], 'no template shot rows or VFX clips to keep')
        self.assertEqual(self.pipeline(slug), self.pipeline(template), 'the same pipeline, default steps included')
        self.assertEqual(repo.field_values(self.conn, slug).get('soul-cast', {}), {})
        code, payload, _ = self.request('/projects/api/projects', method='POST', data={'slug': 'r44-bad', 'title': 'Bad', 'samples': 'no'})
        self.assertEqual(code, 400, payload)

    def test_the_pasted_screenplay_is_the_working_screenplay_without_an_adopt_step(self):
        slug = self.create(samples=False)
        self.assertEqual(self.start(slug), {'kind': 'working'})
        working = doc_text(self.writing(slug, 'workspace')['doc'])
        for line in ('1. INT. DAM CONTROL ROOM - NIGHT', 'The gate is jammed.', 'Nora pulls the lever as the water rises.'):
            self.assertIn(line, working)
        self.assertNotIn('The Last Signal', working)
        self.assertEqual(self.writing(slug, 'branches')['items'], [], 'no private draft to adopt')
        self.assertEqual(len(self.writing(slug, 'workspace')['structure']['scenes']), 3)

    def test_a_production_made_from_the_template_still_keeps_its_brief(self):
        slug = self.create()
        ref = self.start(slug)
        self.assertEqual(ref['kind'], 'branch', 'the template brief is occupied text, so the start stays a private draft')
        self.assertIn('Over a red canyon at sunrise', doc_text(self.writing(slug, 'workspace')['doc']))


if __name__ == '__main__':
    unittest.main()
