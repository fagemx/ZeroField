"""SPEC_20 R27/R28: 3D blocking as structured operations, solved by the 3D Stage's own JavaScript into a proposal.

Rule tests need nothing (the golden file tests/fixtures/previs_ops_golden.json is the JS solver's own output, made by
scripts/previs_ops_golden.mjs; ui/tests/previsOps.test.mjs re-solves it). The parity test runs blocking.js in node
(skipped without node). The production tests use PostgreSQL (OPENBENCH_TEST_DB_URI) with a fake headless runner: the
real browser is exercised by scripts/previs_headless_check.py, not here.
"""
import base64
import copy
import json
import os
import re
import shutil
import subprocess
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from project_assistant import headless_previs, previs_ops, shot_meta, store, tool_registry, tools
from project_docs import story_previs

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = json.loads((ROOT / 'tests' / 'fixtures' / 'previs_ops_golden.json').read_text(encoding='utf-8'))
OPS_JS = (ROOT / 'ui' / 'src' / 'previs' / 'ops.js').read_text(encoding='utf-8')
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64
CLOSEUP = GOLDEN['cases'][0]  # front-closeup-from-the-seed: one place op and a 50 mm push-in
SEEDED = next(c for c in GOLDEN['cases'] if c['id'] == 'parallax-crane-with-set-image')  # what a storyboard seeds: the parallax set


def js_array(name):
    match = re.search(r'export const %s = \[([^\]]*)\]' % name, OPS_JS)
    return [json.loads(item.strip().replace("'", '"')) for item in match.group(1).split(',') if item.strip()]


def js_object(name):
    match = re.search(r'export const %s = (\{.*?\});' % name, OPS_JS)
    text = re.sub(r"([{,]\s*)([A-Za-z_]\w*)\s*:", r'\1"\2":', match.group(1).replace("'", '"'))
    return json.loads(text)


def facts_of(case):
    inp = case['input']
    return previs_ops.base_facts(inp['stored'], inp['shot'])


def validate_case(case):
    facts = facts_of(case)
    return previs_ops.validate_ops(case['input']['ops'], base_set=facts['set'], on_set=facts['onSet'],
                                   acting=facts['actingBeats'], cast_codes=case['input']['castCodes'])


class VocabularyTests(unittest.TestCase):
    def test_python_mirrors_ops_js_and_the_tool_schema(self):
        self.assertEqual(GOLDEN['version'], previs_ops.OPS_VERSION)
        self.assertEqual(int(re.search(r'export const OPS_VERSION = (\d+)', OPS_JS)[1]), previs_ops.OPS_VERSION)
        for name in ('OP_TYPES', 'SIZES', 'ANGLES', 'FACE_LENS'):
            self.assertEqual(tuple(js_array(name)), getattr(previs_ops, name), name)
        self.assertEqual(int(re.search(r'export const MAX_OPS = (\d+)', OPS_JS)[1]), previs_ops.MAX_OPS)
        self.assertEqual(int(re.search(r'export const MAX_OFFSET = (\d+)', OPS_JS)[1]), previs_ops.MAX_OFFSET)
        self.assertEqual(js_object('MOVE_KEYS'), previs_ops.MOVE_KEYS)
        self.assertEqual({k: tuple(v) for k, v in js_object('STAGE_TARGETS').items()}, previs_ops.STAGE_TARGETS)
        self.assertEqual(js_object('TARGET_ALIASES'), previs_ops.TARGET_ALIASES)
        self.assertEqual(set(previs_ops.MOVE_KEYS), set(story_previs.MOVES))
        self.assertEqual(set(previs_ops.STAGE_TARGETS), set(story_previs.SETS))
        # The tool's declared schema says the same.
        schema = tool_registry.get(previs_ops.TOOL).schema
        op = schema['properties']['ops']['items']['properties']
        self.assertEqual(schema['properties']['ops']['maxItems'], previs_ops.MAX_OPS)
        self.assertEqual(tuple(op['op']['enum']), previs_ops.OP_TYPES)
        self.assertEqual(tuple(op['size']['enum']), previs_ops.SIZES)
        self.assertEqual(tuple(op['angle']['enum']), previs_ops.ANGLES)
        self.assertEqual(tuple(op['lens']['enum']), story_previs.LENSES)
        self.assertEqual(tuple(op['move']['enum']), story_previs.MOVES)
        self.assertEqual((op['offset']['items']['minimum'], op['offset']['items']['maximum']), (-previs_ops.MAX_OFFSET, previs_ops.MAX_OFFSET))
        self.assertEqual(set(op), {key for fields in previs_ops.OP_FIELDS.values() for group in fields for key in group})

    def test_the_crew_evaluation_set_assumes_the_same_operations(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('crew_eval', ROOT / 'scripts' / 'crew_eval.py')
        crew = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(crew)
        self.assertEqual((crew.SIZES, crew.ANGLES, crew.RETIME_BEAT_BASE, crew.MAX_OPS, crew.MAX_OFFSET),
                         (previs_ops.SIZES, previs_ops.ANGLES, 1, previs_ops.MAX_OPS, previs_ops.MAX_OFFSET))
        self.assertEqual({stage: set(names) - {'window'} for stage, names in crew.STAGE_TARGETS.items()},
                         {stage: set(names) for stage, names in previs_ops.STAGE_TARGETS.items()})
        self.assertEqual(crew.ALIASES, previs_ops.TARGET_ALIASES)
        self.assertEqual({name: tuple(fields) for name, fields in crew.OP_FIELDS.items()},
                         {name: tuple(fields) for name, fields in previs_ops.OP_FIELDS.items()})
        self.assertEqual(crew.SKILLS, story_previs.SKILLS)

    def test_every_blocking_reference_passes_the_servers_validation(self):
        """A reference answer scores full marks in crew_eval and is also a request the server accepts (final §4.6)."""
        cases = json.loads((ROOT / 'research' / 'crew_eval' / 'cases' / 'blocking.json').read_text(encoding='utf-8'))['cases']
        for case in cases:
            with self.subTest(case=case['id']):
                inp, ref = case['input'], case['reference']
                previs_ops.validate_request({'shotId': 'sh_x', 'baseRevision': ref['baseRevision'], 'ops': ref['ops']})
                previs_ops.validate_ops(ref['ops'], base_set=inp['set']['stage'], on_set=(), acting=len(inp.get('beats') or []),
                                        cast_codes=[member['code'] for member in inp['cast']])


class GoldenTests(unittest.TestCase):
    """The checked-in JS output: Python validation agrees with it, and every solved plan is storable and consistent."""

    def test_base_facts_match_the_js_resolution_of_every_case(self):
        for case in GOLDEN['cases']:
            with self.subTest(case=case['id']):
                self.assertEqual(facts_of(case), case['expect']['base'])

    def test_every_valid_case_passes_and_its_plan_is_storable_and_consistent(self):
        for case in GOLDEN['cases']:
            with self.subTest(case=case['id']):
                validate_case(case)
                plan = case['expect']['plan']
                story_previs.validate(plan, set(case['input']['castCodes']))
                self.assertEqual(previs_ops.consistent(case['input']['ops'], plan, facts_of(case), case['input']['stored']), [])

    def test_every_invalid_case_is_refused_at_the_path_the_js_validator_names(self):
        self.assertGreaterEqual(len(GOLDEN['invalid']), 20)
        for case in GOLDEN['invalid']:
            with self.subTest(case=case['id']), self.assertRaises(previs_ops.OpsRefusal) as caught:
                validate_case(case)
            self.assertEqual((caught.exception.status, caught.exception.path), (422, case['path']))
            self.assertEqual(str(caught.exception), case['message'], 'the agent reads the same sentence on either path')

    def test_consistency_names_what_a_wrong_solve_gets_wrong(self):
        case = GOLDEN['cases'][1]  # two-shot-stored-plan
        plan, ops, facts, stored = case['expect']['plan'], case['input']['ops'], facts_of(case), case['input']['stored']
        wrong = {**plan, 'lens': 85, 'seconds': 8, 'set': 'empty', 'cast': []}
        problems = previs_ops.consistent(ops, wrong, facts, stored)
        self.assertEqual(len(problems), 4, problems)
        self.assertTrue(any('@CAST-02' in p for p in problems))
        self.assertEqual(previs_ops.consistent(ops, {**plan, 'keys': None}, facts, stored), ['the plan has no camera keys'])


class RequestRuleTests(unittest.TestCase):
    def refused(self, call, path, fragment=''):
        with self.assertRaises(previs_ops.OpsRefusal) as caught:
            call()
        self.assertEqual((caught.exception.status, caught.exception.path), (422, path))
        self.assertIn(fragment, str(caught.exception))

    def test_requests_are_closed_objects_with_a_shot_and_a_revision(self):
        self.assertEqual(previs_ops.validate_request({'shotId': 'sh_x', 'baseRevision': 0, 'ops': []}), ('sh_x', 0, []))
        self.refused(lambda: previs_ops.validate_request([]), 'request')
        self.refused(lambda: previs_ops.validate_request({'shotId': 'sh', 'baseRevision': 1, 'ops': [], 'code': 'x'}), 'request', 'code')
        self.refused(lambda: previs_ops.validate_request({'baseRevision': 1, 'ops': []}), 'shotId')
        for revision in (None, -1, 1.0, True, '3'):
            self.refused(lambda: previs_ops.validate_request({'shotId': 'sh', 'baseRevision': revision, 'ops': []}), 'baseRevision')

    def test_python_is_stricter_than_json_about_numbers(self):
        ops = [{'op': 'camera', 'size': 'close', 'angle': 'eye', 'lens': True, 'move': 'static'}]
        self.refused(lambda: previs_ops.validate_ops(ops), 'ops[0].lens')
        self.refused(lambda: previs_ops.validate_ops([{**ops[0], 'lens': 35.0}]), 'ops[0].lens')
        self.refused(lambda: previs_ops.validate_ops([{'op': 'place', 'cast': '@CAST-01', 'relativeTo': 'mark', 'offset': [float('nan'), 0],
                                                       'facing': 'room'}]), 'ops[0].offset')
        self.refused(lambda: previs_ops.validate_ops([{'op': 'retime', 'beat': True, 'at': 0.5}], acting=2), 'ops[0].beat')
        previs_ops.validate_ops([{'op': 'place', 'cast': '@CAST-01', 'relativeTo': 'window', 'offset': [0, -1], 'facing': 'window'}])
        self.refused(lambda: previs_ops.validate_ops([{'op': 'place', 'cast': '@CAST-01', 'relativeTo': 'console', 'offset': [0, 0], 'facing': 'room'}],
                                                     base_set='parallax'), 'ops[0].relativeTo', 'parallax set (far, mid, near, mark)')

    def test_the_same_operations_always_hash_and_read_the_same(self):
        ops = CLOSEUP['input']['ops']
        reordered = [dict(reversed(list(op.items()))) for op in ops]
        self.assertEqual(previs_ops.ops_hash('sh_a', 3, ops), previs_ops.ops_hash('sh_a', 3, reordered))
        self.assertNotEqual(previs_ops.ops_hash('sh_a', 3, ops), previs_ops.ops_hash('sh_a', 4, ops))
        self.assertEqual(previs_ops.describe(ops),
                         '3D blocking: @CAST-01 at console +0, -0.55 m, facing camera; close eye-angle 50mm pushin K1→K2.')
        self.assertEqual(previs_ops.describe([{'op': 'retime', 'beat': 2, 'at': 0.6}]), '3D blocking: acting beat 2 at 60%.')


def fake_runner(result=None, error=None, calls=None):
    def run(request, *, title='', files=None, render=True, timeout=None):
        if calls is not None:
            calls.append({'request': copy.deepcopy(request), 'title': title, 'files': files, 'render': render})
        if error:
            raise error
        return result
    return run


def golden_result(case, image=PNG):
    return {'solved': copy.deepcopy(case['expect']), 'image': image, 'renderError': None if image else 'blank',
            'sheet': {'width': 1944, 'height': 818, 'frames': [{'frame': f, 'seconds': f / 24} for f in (0, 19, 38, 58, 77, 96)]} if image else None,
            'browser': 'msedge.exe', 'seconds': 2.5}


class SolveStepTests(unittest.TestCase):
    """previs_ops.solve with a fake runner: what the browser's answers become."""

    def prepared(self, case=CLOSEUP):
        inp = case['input']
        return previs_ops.Prepared('golden', 'sh_golden_b1', 'S01', 0, inp['ops'], inp['stored'], facts_of(case), inp['castCodes'],
                                   {'stored': inp['stored'], 'shot': inp['shot'], 'ops': inp['ops'], 'castCodes': inp['castCodes']}, {})

    def test_a_solved_and_rendered_answer_is_kept_with_its_warnings(self):
        calls = []
        solved = previs_ops.solve(self.prepared(), runner=fake_runner(golden_result(CLOSEUP), calls=calls))
        self.assertEqual(solved['plan'], CLOSEUP['expect']['plan'])
        self.assertEqual(solved['image'], PNG)
        self.assertEqual((solved['solve']['status'], solved['solve']['by'], solved['solve']['version']), ('solved', 'headless', 1))
        self.assertEqual(calls[0]['request']['ops'], CLOSEUP['input']['ops'])
        self.assertEqual(calls[0]['title'](CLOSEUP['expect']['plan']), 'S01 · proposed 3D plan · 50mm pushin · 4 s')

    def test_no_browser_means_operations_only(self):
        for code in ('no_browser', 'no_page', 'disabled', 'launch_failed', 'timeout'):
            solved = previs_ops.solve(self.prepared(), runner=fake_runner(error=headless_previs.Unavailable(code, 'nothing here')))
            self.assertEqual((solved['plan'], solved['image'], solved['solve']['status'], solved['solve']['reason']), (None, None, 'ops_only', code))

    def test_a_refusal_unstorable_or_inconsistent_plan_is_a_422(self):
        with self.assertRaises(previs_ops.OpsRefusal) as caught:
            previs_ops.solve(self.prepared(), runner=fake_runner(error=headless_previs.Refused('ops[0].beat', 'ops[0].beat must be an acting beat from 1 to 1.')))
        self.assertEqual((caught.exception.status, caught.exception.path), (422, 'ops[0].beat'))
        broken = golden_result(CLOSEUP)
        broken['solved']['plan'] = {**broken['solved']['plan'], 'lens': 40}
        with self.assertRaises(previs_ops.OpsRefusal) as caught:
            previs_ops.solve(self.prepared(), runner=fake_runner(broken))
        self.assertIn('cannot be stored', str(caught.exception))
        wrong = golden_result(CLOSEUP)
        wrong['solved']['plan'] = {**wrong['solved']['plan'], 'lens': 85}
        with self.assertRaises(previs_ops.OpsRefusal) as caught:
            previs_ops.solve(self.prepared(), runner=fake_runner(wrong))
        self.assertIn('does not match its operations', str(caught.exception))

    def test_a_failed_render_keeps_the_solve(self):
        solved = previs_ops.solve(self.prepared(), runner=fake_runner(golden_result(CLOSEUP, image=None)))
        self.assertEqual((solved['plan'], solved['image'], solved['solve']['renderError']), (CLOSEUP['expect']['plan'], None, 'blank'))


class HeadlessBoundaryTests(unittest.TestCase):
    """What the browser session serves and refuses, without starting a browser."""

    def test_only_this_build_and_the_handed_files_are_served(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'projects'
            (root / 'assets').mkdir(parents=True)
            (root / 'previs-solver.html').write_text('<!doctype html>', encoding='utf-8')
            (root / 'assets' / 'solver.js').write_text('1', encoding='utf-8')
            (root / 'assets' / 'notes.txt').write_text('x', encoding='utf-8')
            (Path(folder) / 'secret.js').write_text('2', encoding='utf-8')
            page = headless_previs.Session(root=root, files={'/projects/api/s/assets/pa_' + 'a' * 32: ('image/png', PNG)})
            origin = headless_previs.ORIGIN
            self.assertEqual(page._resolve(origin + '/projects/assets/solver.js'), ('text/javascript; charset=utf-8', b'1'))
            self.assertEqual(page._resolve(origin + '/projects/api/s/assets/pa_' + 'a' * 32), ('image/png', PNG))
            for url in (origin + '/projects/../secret.js', origin + '/projects/%2e%2e/secret.js', origin + '/projects/assets/notes.txt',
                        origin + '/projects/assets/missing.js', origin + '/secret.js', 'https://example.com/projects/assets/solver.js',
                        'http://127.0.0.1:3020/projects/assets/solver.js', 'file:///etc/passwd', origin + '/projects/assets\\..\\..\\secret.js'):
                self.assertIsNone(page._resolve(url), url)

    def test_switching_headless_off_or_missing_the_page_reports_why(self):
        with patch.dict(os.environ, {headless_previs.BROWSER_ENV: 'off'}):
            self.assertEqual(headless_previs.availability(), (False, 'disabled'))
            self.assertIsNone(headless_previs.browser_path())
            with self.assertRaises(headless_previs.Unavailable) as caught, headless_previs.Session():
                pass
            self.assertEqual(caught.exception.code, 'disabled')
        with patch.object(headless_previs, 'browser_path', lambda: __file__), self.assertRaises(headless_previs.Unavailable) as caught, \
                headless_previs.Session(root=ROOT / 'tests' / 'fixtures'):
            pass
        self.assertEqual(caught.exception.code, 'no_page')

    def test_websocket_masking_round_trips(self):
        for data in (b'', b'x', b'{"id":1}' * 300):
            key = os.urandom(4)
            self.assertEqual(headless_previs._mask(headless_previs._mask(data, key), key), data)


@unittest.skipUnless(shutil.which('node'), "node runs the stage's blocking.js")
class ActingBeatParityTests(unittest.TestCase):
    SCRIPT = """
import { actingBeats } from './src/previs/blocking.js';
import { defaultPlan } from './src/previs/plan.js';
const plans = JSON.parse(process.argv[1]);
console.log(JSON.stringify(plans.map(p => actingBeats({ ...defaultPlan(), ...p }).length)));
"""

    def test_the_python_count_of_acting_beats_matches_the_stage(self):
        from test_story_previs import RICH
        plans = [RICH, {'action': 'walkin'}, {'action': 'walkin', 'acts': [{'at': 0, 'yaw': 1}]}, {'action': 'stand'},
                 {'use': [{'skill': 'standIdle', 'args': {'until': 0}}, {'skill': 'turnLook', 'frames': 0}, {'skill': 'walkTo', 'args': {}},
                          {'skill': 'reachGrip', 'args': {'anchor': 'window'}}, {'skill': 'kneelDown', 'args': {'duration': 12}}]},
                 {'mark': [1, 1], 'use': [{'skill': 'walkTo', 'args': {'to': [1, 1]}}, {'skill': 'standIdle', 'args': {'until': 10}},
                                          {'skill': 'standIdle', 'f0': {'range': [10, 30]}, 'frames': 4}]}]
        done = subprocess.run(['node', '--input-type=module', '-e', self.SCRIPT, json.dumps(plans)], cwd=ROOT / 'ui',
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual([previs_ops.acting_beats({'action': 'turnreach', **p}) for p in plans], json.loads(done.stdout))

    SOLVE = """
import { solveRequest } from './src/previs/ops.js';
import { actingBeats } from './src/previs/blocking.js';
const { plan, warnings } = solveRequest(JSON.parse(process.argv[1]));
console.log(JSON.stringify({ warnings, starts: actingBeats(plan).map(b => b.start) }));
"""

    def test_the_crew_eval_retime_case_solves_on_a_plan_with_its_acting_beats(self):
        """blocking-03: the reference's retime moves the shove (acting beat 2) to 0.6 of the shot without hitting beat 3."""
        case = next(c for c in json.loads((ROOT / 'research' / 'crew_eval' / 'cases' / 'blocking.json').read_text(encoding='utf-8'))['cases']
                    if c['id'].startswith('blocking-03'))
        frames = lambda seconds: round(seconds * 24)  # noqa: E731
        args = {'standIdle': {}, 'walkTo': {'to': [0, 0.1]}, 'reachGrip': {'anchor': 'console_edge', 'reach': 6, 'hold': 7, 'release': 6}}
        use = [{'skill': b['skill'], 'f0': frames(b['from']), **({'frames': frames(b['to']) - frames(b['from'])} if b['skill'] != 'reachGrip' else {}),
                'args': args[b['skill']]} for b in case['input']['beats']]
        stored = {'set': 'observatory', 'move': 'static', 'lens': 35, 'action': 'stand', 'facing': 'console', 'mood': 'grey',
                  'seconds': case['input']['shot']['seconds'], 'code': '@CAST-01', 'use': use}
        self.assertEqual(previs_ops.acting_beats(stored), len(case['input']['beats']))
        request = {'stored': stored, 'shot': {}, 'ops': case['reference']['ops'], 'castCodes': [m['code'] for m in case['input']['cast']]}
        done = subprocess.run(['node', '--input-type=module', '-e', self.SOLVE, json.dumps(request)], cwd=ROOT / 'ui',
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        solved = json.loads(done.stdout)
        self.assertEqual([w for w in solved['warnings'] if 'Acting beat' in w], [])
        self.assertEqual(solved['starts'][1], round(0.6 * 96))


class ToolDeclarationTests(unittest.TestCase):
    def test_the_tool_is_a_proposal_only_external_tool_for_the_showrunner_and_cinematographer(self):
        tool = tool_registry.get(previs_ops.TOOL)
        self.assertEqual((tool.category, tool.policy, tool.mutating, tool.external, tool.analysis_only, tool.ui, tool.mcp),
                         ('previs', 'auto', True, True, False, True, True))
        self.assertEqual(tool.grants, ('coordinator', 'sheet_ops'))
        self.assertIs(tools.HANDLERS[previs_ops.TOOL], previs_ops.propose_previs_ops)
        self.assertNotIn(previs_ops.TOOL, tools._STRUCTURED, 'a text result, sanitized and clipped like propose_table_edit')

    def test_numbers_are_a_validated_schema_type(self):
        good = {'shotId': 'sh_x', 'baseRevision': 2, 'ops': [{'op': 'place', 'cast': '@CAST-01', 'relativeTo': 'mark', 'offset': [0, -0.55], 'facing': 'camera'},
                                                             {'op': 'retime', 'beat': 1, 'at': 1}]}
        tool_registry.validate_args(previs_ops.TOOL, good)
        for offset in ([0, 8.01], [True, 0], [0, float('inf')], [0, float('nan')], ['0', 0], [0]):
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                tool_registry.validate_args(previs_ops.TOOL, {**good, 'ops': [{**good['ops'][0], 'offset': offset}]})
        for change in ({'script': 'x'}, {'lens': 40}, {'from': 'start'}, {'cast': 'Kael'}, {'at': -0.1}, {'beat': 0}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                tool_registry.validate_args(previs_ops.TOOL, {**good, 'ops': [{**good['ops'][1], **change}]})
        for bounds in ({'minimum': True}, {'maximum': float('inf')}, {'minimum': '0'}):
            with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                tool_registry.declare(dict(name='fixture_number', description='Fixture.', category='context', handler='fixture.module:x',
                                           schema=tool_registry._obj({'q': {'type': 'number', **bounds}})))


class ProductionFixture:
    """A real production with a storyboard and the built-in crew (no tests of its own)."""

    def setUp(self):
        import psycopg
        import test_execution as execution_fixture
        from project_assistant import agent_registry
        from project_docs import markdown_import, repository as repo, story_openapi as story, templates
        from project_docs.doc_schema import validate_doc
        execution_fixture.PostgreSQLExecutionTests.setUp(self)
        self.repo, self.story = repo, story
        self.connect = lambda: psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI'])
        for key, title, surface, md in templates.tab_specs('zerofield_studio', 'Previs Ops Test', ''):
            doc, _ = markdown_import.markdown_to_doc(md, tab_keys=set(), image_src=lambda _: None)
            doc, _ = validate_doc(doc, slug=self.slug)
            templates.configure_doc(key, doc)
            repo.create_tab(self.conn, self.slug, key=key, title=title, parent_key=None, doc=doc, actor_id=self.actor, surface_type=surface)
        self.ep = f'ep_{self.slug}_01'
        for method, path, body in (('PUT', f'/episodes/{self.ep}/script', {'scriptContent': '## Scene 01: Observatory\n@CAST-01 turns to the dial as @CAST-02 waits.\n\n## Scene 02: Exit\n@CAST-01 leaves.'}),
                                   ('POST', f'/episodes/{self.ep}/asset-extractions', {}), ('POST', f'/episodes/{self.ep}/storyboards', {})):
            story.dispatch(self.conn, self.me, method, path, body, {}, [])
        shots = [s for s in story.shots(self.conn, story.episode(self.conn, self.ep)) if s.get('sceneId') and s['tabKey'] == 'cinema-studio']
        self.shot, self.other = shots[0], shots[1]
        agent_registry.ensure_default_agents(self.conn, self.slug)
        self.conn.commit()

    def tearDown(self):
        import test_execution as execution_fixture
        execution_fixture.PostgreSQLExecutionTests.tearDown(self)

    # ---- helpers ----
    def body(self, ops=None, revision=0, shot=None):
        return {'shotId': (shot or self.shot)['shotId'], 'baseRevision': revision, 'ops': ops or SEEDED['input']['ops']}

    def stored(self, shot=None):
        self.conn.rollback()
        return story_previs.stored(self.story.shot_meta(self.conn, (shot or self.shot)['shotId']))

    def solved_result(self, plan_changes=None):
        """What the browser answers for SEEDED on this shot's seed (fakes the JS; the golden tests pin the JS itself)."""
        result = golden_result(SEEDED)
        result['solved']['plan'] = {**result['solved']['plan'], **(plan_changes or {})}
        return result

    def propose(self, body=None, runner=None, **options):
        proposal = previs_ops.propose_ops(self.conn, self.slug, self.actor, body or self.body(),
                                          runner=runner or fake_runner(self.solved_result()), agent_key='sheet_ops', **options)
        self.conn.commit()
        return proposal

    def listing(self, shot=None):
        code, payload = shot_meta.listing(self.conn, self.me, self.slug, (shot or self.shot)['shotId'])
        self.assertEqual(code, 200, payload)
        return payload['proposals']

    def apply(self, proposal):
        from project_assistant import service
        code, payload = service.apply_proposal(self.conn, self.me, self.slug, proposal['id'], {})
        if code < 400:
            self.conn.commit()
        else:
            self.conn.rollback()
        return code, payload


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'set OPENBENCH_TEST_DB_URI')
class PrevisOpsProductionTests(ProductionFixture, unittest.TestCase):
    """Proposals made, listed, solved by the stage and approved through the assistant."""

    def test_solved_operations_become_a_proposal_with_its_preview_and_approval_writes_the_plan(self):
        calls = []
        proposal = self.propose(runner=fake_runner(self.solved_result(), calls=calls))
        target = proposal['target']
        self.assertEqual((proposal['action'], proposal['status'], proposal['agent_key'], target['field'], target['baseRevision']),
                         ('shot_meta', 'pending', 'sheet_ops', 'previsPlan', 0))
        self.assertEqual(target['value'], SEEDED['expect']['plan'])
        self.assertEqual(target['ops'], SEEDED['input']['ops'])
        self.assertEqual(target['opsHash'], previs_ops.ops_hash(self.shot['shotId'], 0, SEEDED['input']['ops']))
        self.assertEqual((target['solve']['status'], target['solve']['by'], target['solve']['browser']), ('solved', 'headless', 'msedge.exe'))
        self.assertEqual(proposal['content'], previs_ops.describe(SEEDED['input']['ops']))
        preview = target['preview']
        self.assertEqual((preview['kind'], preview['url'], len(preview['frames'])),
                         ('contact_sheet', f"/projects/api/{self.slug}/assets/{preview['assetId']}", 6))
        self.assertEqual(self.repo.get_asset(self.conn, self.slug, preview['assetId']), ('image/png', PNG))
        # The solver page was given the shot as the stage seeds it and the production's cast codes.
        request = calls[0]['request']
        self.assertEqual((request['stored'], request['ops'], request['castCodes']), (None, SEEDED['input']['ops'], ['@CAST-01', '@CAST-02']))
        self.assertEqual(set(request['shot']), {'slate', 'previsPlan', 'setAsset'})
        self.assertEqual(request['shot']['previsPlan'], self.story.shot_meta(self.conn, self.shot['shotId'])['previsPlan'])
        # Listed for the stage with the operations and the preview; the assistant's own list leaves the plan out.
        [item] = self.listing()
        self.assertEqual((item['value'], item['ops'], item['preview'], item['solve']['status']),
                         (target['value'], target['ops'], preview, 'solved'))
        code, applied = self.apply(proposal)
        self.assertEqual(code, 200, applied)
        state = self.stored()
        self.assertEqual((state['plan'], state['planRevision']), (SEEDED['expect']['plan'], 1))

    def test_a_stale_base_revision_is_a_409_and_nothing_is_proposed(self):
        story_previs.put(self.conn, self.slug, self.shot['shotId'], {**SEEDED['expect']['plan'], 'lens': 85}, 0, self.actor)
        self.conn.commit()
        before = len(store.proposals(self.conn, self.slug, owner_id=self.actor))
        with self.assertRaises(previs_ops.OpsRefusal) as caught:
            self.propose(self.body(revision=0))
        self.assertEqual((caught.exception.status, caught.exception.code, caught.exception.details),
                         (409, 'DRAMA_PREVIS_REVISION_CONFLICT', {'currentRevision': 1, 'baseRevision': 0}))
        self.conn.rollback()
        self.assertEqual(len(store.proposals(self.conn, self.slug, owner_id=self.actor)), before)

    def test_a_plan_saved_while_the_browser_solved_is_a_409_at_commit(self):
        prepared = previs_ops.prepare(self.conn, self.slug, self.body())
        self.conn.rollback()
        with self.connect() as other:  # someone saves the shot's plan meanwhile
            story_previs.put(other, self.slug, self.shot['shotId'], {**SEEDED['expect']['plan'], 'lens': 24}, 0, self.actor)
        solved = previs_ops.solve(prepared, runner=fake_runner(self.solved_result()))
        with self.assertRaises(previs_ops.OpsRefusal) as caught:
            previs_ops.commit(self.conn, prepared, solved, self.actor)
        self.assertEqual((caught.exception.status, caught.exception.code), (409, 'DRAMA_PREVIS_REVISION_CONFLICT'))

    def test_operations_are_checked_against_this_production(self):
        cases = [([{'op': 'place', 'cast': '@CAST-07', 'relativeTo': 'mark', 'offset': [0, 0], 'facing': 'room'}], 'ops[0].cast'),
                 ([{'op': 'place', 'cast': '@CAST-01', 'relativeTo': 'desk', 'offset': [0, 0], 'facing': 'room'}], 'ops[0].relativeTo'),
                 ([{'op': 'retime', 'beat': 2, 'at': 0.5}], 'ops[0].beat')]
        for ops, path in cases:
            with self.subTest(path=path), self.assertRaises(previs_ops.OpsRefusal) as caught:
                previs_ops.prepare(self.conn, self.slug, self.body(ops))
            self.assertEqual((caught.exception.status, caught.exception.path), (422, path))
        with self.assertRaises(previs_ops.OpsRefusal) as caught:
            previs_ops.prepare(self.conn, self.slug, {**self.body(), 'shotId': f'sh_{self.slug}_bnothere'})
        self.assertEqual(caught.exception.status, 404)

    def test_without_a_browser_the_operations_wait_for_the_stage_and_approval_never_writes_them_unsolved(self):
        proposal = self.propose(runner=fake_runner(error=headless_previs.Unavailable('no_browser', 'No headless browser.')))
        target = proposal['target']
        self.assertEqual((target['value'], target['preview'], target['solve']['status'], target['solve']['reason']),
                         (None, None, 'ops_only', 'no_browser'))
        [item] = self.listing()
        self.assertEqual((item['value'], item['ops']), (None, SEEDED['input']['ops']))
        code, refused = self.apply(proposal)
        self.assertEqual((code, refused['error']), (409, shot_meta.NEEDS_SOLVE.format(label=self.shot['shotIndex'])))
        self.assertEqual((self.stored()['plan'], store.proposal(self.conn, proposal['id'])['status']), (None, 'pending'))
        # The 3D Stage solves them and attaches its solve; a solve that does not fit the operations is refused.
        attach = lambda body, me=self.me: previs_ops.attach_solution(self.conn, me, self.slug, proposal['id'], body)  # noqa: E731
        plan = SEEDED['expect']['plan']
        self.assertEqual(attach({'plan': {**plan, 'lens': 85}, 'version': 1})[0], 409)
        self.assertEqual(attach({'plan': {**plan, 'lens': 40}, 'version': 1})[0], 409)
        self.assertEqual(attach({'plan': plan, 'version': 99})[0], 400)
        self.assertEqual(attach({'plan': plan, 'version': 1, 'extra': 1})[0], 400)
        from project_docs import service as docs_service
        viewer = docs_service.Identity(str(uuid.uuid4()), 'Viewer', 'viewer')
        self.assertEqual(attach({'plan': plan, 'version': 1}, viewer)[0], 403)
        self.conn.rollback()
        code, payload = attach({'plan': plan, 'version': 1})
        self.assertEqual(code, 200, payload)
        self.conn.commit()
        self.assertEqual(attach({'plan': plan, 'version': 1})[0], 409, 'a solve is attached once')
        self.conn.rollback()
        target = store.proposal(self.conn, proposal['id'])['target']
        self.assertEqual((target['value'], target['solve']['status'], target['solve']['by'], target['solve']['actorId']),
                         (plan, 'solved', 'stage', self.actor))
        code, applied = self.apply(proposal)
        self.assertEqual(code, 200, applied)
        self.assertEqual((self.stored()['plan'], self.stored()['planRevision']), (plan, 1))

    def test_a_stage_solve_after_the_plan_moved_is_refused(self):
        proposal = self.propose(runner=fake_runner(error=headless_previs.Unavailable('no_page', 'No page.')))
        story_previs.put(self.conn, self.slug, self.shot['shotId'], SEEDED['expect']['plan'], 0, self.actor)
        self.conn.commit()
        code, payload = previs_ops.attach_solution(self.conn, self.me, self.slug, proposal['id'], {'plan': SEEDED['expect']['plan'], 'version': 1})
        self.assertEqual(code, 409)
        self.assertIn('changed after this proposal was made', payload['error'])

    def test_the_solution_route_is_registered(self):
        from project_docs import http
        self.assertEqual(http._route('POST', f'/projects/api/{self.slug}/assistant/proposals/12/solution'), ('assistant_solution', (self.slug, '12')))

    def test_the_crew_tool_releases_the_transaction_for_the_browser_and_attaches_the_preview(self):
        ctx = tools.ToolContext(self.connect, self.slug, self.me, Path('.'), None, agent_key='sheet_ops')
        seen = []

        def run(request, **options):
            with self.connect() as probe:  # the tool holds no project lock while the browser runs
                free = probe.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))', ('openbench-orchestration:' + self.slug,)).fetchone()[0]
                seen.append('free' if free else 'locked')
            return self.solved_result()
        with patch.object(headless_previs, 'run', run):
            text = tools.call(ctx, previs_ops.TOOL, self.body())
        self.assertEqual(seen, ['free'])
        self.assertRegex(text, r'^Proposal #\d+ for shot ')
        self.assertIn('Preview: contact sheet /projects/api/', text)
        self.assertEqual(text.images, ['data:image/png;base64,' + base64.b64encode(PNG).decode('ascii')])
        [item] = self.listing()
        self.assertEqual((item['author']['key'], item['solve']['status']), ('sheet_ops', 'solved'))
        with patch.dict(os.environ, {headless_previs.BROWSER_ENV: 'off'}):
            text = tools.call(ctx, previs_ops.TOOL, self.body(shot=self.other))
        self.assertIn('Operations only', text)
        with self.assertRaises(tools.ToolError) as caught:
            tools.call(ctx, previs_ops.TOOL, self.body(revision=5))
        self.assertTrue(str(caught.exception).startswith('DRAMA_PREVIS_REVISION_CONFLICT: '), str(caught.exception))
        with self.assertRaises(tools.ToolError):
            tools.call(ctx, previs_ops.TOOL, {**self.body(), 'ops': [{'op': 'teleport'}]})

    def test_the_optional_vision_check_only_annotates_through_governance_and_the_gpu_arbiter(self):
        from project_assistant import model_client, providers, take_grader
        proposal = self.propose()
        holds, sent = [], {}

        class Phase:
            def __enter__(self): return self
            def __exit__(self, *exc): holds.append('released')
            def hold(self, config, comfy, on_wait): holds.append(('hold', config.base_url))

        def turn(**kwargs):
            sent.update(kwargs)
            return model_client.TurnResult('ok', answer='<think>x</think>{"faceReadable": true, "issues": ["K1 starts behind his head"], "note": "Face reads from 1.6 s."}')
        env = {'OPENBENCH_PROVIDER': 'openai_compat', 'OPENBENCH_API_BASE': 'http://127.0.0.1:11434/v1', 'OPENBENCH_MODEL': 'qwen-test'}
        with patch.dict(os.environ, env), patch.object(take_grader, '_Phase', Phase), patch.object(providers, 'run_openai_compat_turn', turn):
            note = previs_ops.vision_check(self.connect, self.slug, proposal['id'])
        self.assertEqual((note['status'], note['faceReadable'], note['issues'], note['model']),
                         ('checked', True, ['K1 starts behind his head'], 'qwen-test'))
        self.assertEqual(holds[0], ('hold', 'http://127.0.0.1:11434/v1'))
        self.assertEqual((sent['admission'].kind, sent['admission'].purpose, sent['config'].effort), ('grader_check', 'previs_check', 'low'))
        self.assertTrue(sent['images'][0].startswith('data:image/png;base64,'))
        self.conn.rollback()
        after = store.proposal(self.conn, proposal['id'])
        self.assertEqual((after['status'], after['target']['vision']['status'], after['target']['value']),
                         ('pending', 'checked', proposal['target']['value']), 'a note, never a decision')
        self.assertIsNone(store.get_setting(self.conn, self.slug, previs_ops.VISION_SETTING), 'off unless a production turns it on')


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'set OPENBENCH_TEST_DB_URI')
class DispatchAttachTests(ProductionFixture, unittest.TestCase):
    """A crew dispatch can return a shot's 3D plan proposal when its output is the shot's page or row (SPEC_20 R18 gap)."""

    def dispatched(self, target):
        from project_assistant import orchestrator as cp
        run = cp.create_run(self.conn, self.me, self.slug, 'Block the shot', client_request_id=uuid.uuid4().hex)
        task = cp.create_task(self.conn, self.me, self.slug, run['id'], objective='Block the shot', agent_key='sheet_ops', target=target)
        cp.spawn_dispatch(self.conn, self.slug, task['id'], agent_key='sheet_ops', slot_key='single')
        claim = cp.claim_dispatch(self.conn, 'previs-worker', ['sheet_ops'], allowed_projects=[self.slug])
        ctx = tools.ToolContext(self.connect, self.slug, self.me, Path('.'), None, agent_key='sheet_ops', dispatch_id=claim['id'],
                                admission_no=claim['admission_no'], lease_token=claim['lease_token'], worker_id='previs-worker', run_id=run['id'])
        return run, task, claim, ctx

    def proposed(self, ctx, revision=0):
        prepared = previs_ops.prepare(self.conn, self.slug, self.body(revision=revision))
        solved = previs_ops.solve(prepared, runner=fake_runner(self.solved_result()))
        return previs_ops.commit(self.conn, prepared, solved, self.actor, ctx=ctx, agent_key='sheet_ops')

    def test_a_task_on_the_shots_page_or_row_takes_the_proposal_and_approval_completes_it(self):
        from project_assistant import orchestrator as cp, orchestration_store as db
        for target in ({'tab_key': 'cinema-studio', 'kind': 'table'}, {'tab_key': 'cinema-studio', 'kind': 'table', 'row_id': self.shot['rowId']}):
            revision = self.stored()['planRevision']
            with self.subTest(target=target):
                run, task, claim, ctx = self.dispatched(target)
                proposal = self.proposed(ctx, revision)
                self.assertEqual(proposal['dispatch_id'], claim['id'])
                self.assertNotIn('request_scope', proposal['target'])
                self.assertNotIn('cinema-studio', proposal['target'].get('source_revisions', {}), 'pinned by the plan revision, not the page')
                cp.complete_dispatch(self.conn, 'previs-worker', claim['handle'], claim['lease_token'], outcome='succeeded',
                                     output={'text': 'blocked'}, proposal_ids=[proposal['id']])
                self.conn.commit()
                code, applied = self.apply(proposal)
                self.assertEqual(code, 200, applied)
                self.assertEqual(db.get_task(self.conn, self.slug, task['id'])['status'], 'completed')
                story_previs.put(self.conn, self.slug, self.shot['shotId'], None, self.stored()['planRevision'], self.actor)
                self.conn.commit()

    def test_a_task_elsewhere_refuses_it(self):
        from project_assistant import orchestrator as cp
        for target, fragment in (({'tab_key': 'soul-cast', 'kind': 'table'}, 'outside the task'),
                                 ({'tab_key': 'cinema-studio', 'kind': 'table', 'row_id': self.other['rowId']}, 'exceeds'),
                                 ({'tab_key': 'cinema-studio', 'kind': 'table', 'row_id': self.shot['rowId'], 'col_index': 2}, 'one cell')):
            with self.subTest(target=target):
                run, task, claim, ctx = self.dispatched(target)
                with self.assertRaises(cp.OrchestrationError) as caught:
                    self.proposed(ctx)
                self.assertEqual(caught.exception.status, 403)
                self.assertIn(fragment, str(caught.exception))
                self.conn.rollback()

    def test_a_sibling_shot_proposal_survives_an_applied_table_edit(self):
        from project_assistant import orchestrator as cp
        run, task, claim, ctx = self.dispatched({'tab_key': 'cinema-studio', 'kind': 'table'})
        row = next(r for r in self.story.table_rows(self.conn, self.slug, 'cinema-studio') if r['rid'] == self.other['rowId'])
        tools.propose_table_edit(ctx, self.conn, {'tab_key': 'cinema-studio', 'table_id': row['tableId'],
                                                  'row_edits': [{'row_id': row['rid'], 'cells': {'1': '50mm Prime'}}]})
        meta = self.proposed(ctx)
        # Pin the sibling to the page like a reference source, so the applied edit rebases it (the R18 crash path).
        tab = self.repo.get_tab(self.conn, self.slug, 'cinema-studio')
        store.revise_pending_proposal(self.conn, meta['id'], {**meta['target'], 'source_revisions': {'cinema-studio': tab['revision']}}, meta['content'])
        edit = next(p for p in store.proposals(self.conn, self.slug, owner_id=self.actor) if p['action'] == 'table_edit')
        cp.complete_dispatch(self.conn, 'previs-worker', claim['handle'], claim['lease_token'], outcome='succeeded',
                             output={'text': 'blocked'}, proposal_ids=[edit['id'], meta['id']])
        self.conn.commit()
        self.assertEqual(self.apply(edit)[0], 200)
        rebased = store.proposal(self.conn, meta['id'])
        self.assertEqual(rebased['status'], 'pending')
        self.assertNotIn('review', rebased['target'])
        self.assertEqual(rebased['target']['source_revisions']['cinema-studio'], self.repo.get_tab(self.conn, self.slug, 'cinema-studio')['revision'])
        self.assertEqual(self.apply(rebased)[0], 200)



if __name__ == '__main__':
    unittest.main()
