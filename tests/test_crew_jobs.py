"""SPEC_20 R7, R19, R20 (fixed decision 12): crew planning jobs, the beat sheet and camera contracts, their tools and
the crew evaluation adapter.

The pure tests need nothing. The rest run the real projects and story servers on PostgreSQL (OPENBENCH_TEST_DB_URI)
with the job executed inline on a fake OpenAI-compatible opener: no test reaches a model, Ollama or a GPU. A socket
guard refuses port 11434 in this module, so a stray probe or call fails loudly instead of reaching a local Ollama.
"""
import datetime as dt
import importlib.util
import json
import os
import re
import socket
import tempfile
import unittest
import urllib.error
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from project_assistant import crew_jobs, crew_planning as planning, crew_readiness, headless_previs, tool_registry
from project_docs import story_previs
import test_story_openapi as fixture

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location('crew_eval_for_tests', ROOT / 'scripts' / 'crew_eval.py')
crew_eval = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(crew_eval)
OLLAMA_PORT = 11434
_connect = socket.socket.connect


def _guarded(sock, address, *args, **kwargs):
    if isinstance(address, tuple) and len(address) >= 2 and address[1] == OLLAMA_PORT:
        raise ConnectionRefusedError('test socket guard: nothing may reach the local Ollama')
    return _connect(sock, address, *args, **kwargs)


_GUARD = patch.object(socket.socket, 'connect', _guarded)


def setUpModule():
    _GUARD.start()


def tearDownModule():
    _GUARD.stop()


SHOT = {'shot': {'id': 'S03', 'seconds': 4, 'text': 'Kael reaches for the dial as a light answers outside. @CAST-01 @SET-01',
                 'optical_rig': 'ARRI Alexa 65 / 35mm Anamorphic', 'camera_motion': 'Slow Dolly Push-In'},
        'cast': [{'code': '@CAST-01', 'name': 'Kael', 'look': 'charcoal field jacket'}],
        'set': {'code': '@SET-01', 'name': 'Observatory', 'look': 'glass dome at dawn'}, 'props': [],
        'previous_shot': None, 'next_shot': None}


def sheet(**change):
    value = {'setup': 'One continuous 4-second shot in @SET-01 at dawn; rain on the glass. @CAST-01 stands at the console, facing the camera.',
             'beats': [{'from': 0, 'to': 1.5, 'camera': 'wide view from the left', 'action': 'Kael turns from the glass toward the console'},
                       {'from': 1.5, 'to': 2.5, 'camera': 'the camera dollies in and arcs right', 'action': 'he reaches out with his right hand'},
                       {'from': 2.5, 'to': 4, 'camera': 'over-the-shoulder close shot', 'action': 'his hand rests on the brass dial; he holds still'}],
             'sound': 'rain on glass, the click of the dial', 'constraints': ['One person only', 'No text']}
    value.update(change)
    return value


def calls(*replies):
    """A call_model that answers with these Replies in turn and records what it was sent."""
    sent = []

    def call(instructions, text, history):
        sent.append({'instructions': instructions, 'text': text, 'history': list(history)})
        reply = replies[len(sent) - 1]
        return reply if isinstance(reply, crew_jobs.Reply) else crew_jobs.Reply(ok=True, answer=json.dumps(reply), model='fake')
    call.sent = sent
    return call


class BeatSheetContractTests(unittest.TestCase):
    def test_a_valid_sheet_passes_and_compiles_to_the_phase2_format(self):
        self.assertEqual(planning.validate_beats(sheet(), SHOT), [])
        text = planning.compile_beats(sheet())
        self.assertEqual(text.splitlines(), [
            'One continuous 4-second shot in @SET-01 at dawn; rain on the glass. @CAST-01 stands at the console, facing the camera.',
            '0-1.5s: wide view from the left; Kael turns from the glass toward the console.',
            '1.5-2.5s: the camera dollies in and arcs right; he reaches out with his right hand.',
            '2.5-4s: over-the-shoulder close shot; his hand rests on the brass dial; he holds still.',
            'Sound: rain on glass, the click of the dial. One person only. No text.'])

    def test_compiling_reproduces_the_hand_written_prompt_s03(self):
        lines = (ROOT / 'research' / 'motion_lab' / 'prompt_s03.txt').read_text(encoding='utf-8').strip().splitlines()
        setup = lines[0]
        written = {'setup': setup, 'sound': 'rain on glass, the click of the dial, a low radio tone', 'constraints': ['One person only', 'No text'],
                   'beats': [{'from': 0, 'to': 1.5, 'camera': 'wide view from the left', 'action': 'Kael turns from the glass toward the console.'},
                             {'from': 1.5, 'to': 2.5, 'camera': 'the camera dollies in and arcs right, behind his shoulder', 'action': 'as he reaches out with his right hand.'},
                             {'from': 2.5, 'to': 4, 'camera': 'over-the-shoulder close shot',
                              'action': 'his hand rests on the large brass dial and turns it; far beyond the rain-streaked glass a beacon blinks on. He holds still.'}]}
        compiled = planning.compile_beats(written).splitlines()
        self.assertEqual([compiled[i] for i in (0, 1, 3, 4)], [lines[i] for i in (0, 1, 3, 4)])
        self.assertRegex(compiled[2], r'^1\.5-2\.5s: [^;]+; .+\.$')
        self.assertEqual((planning.seconds_text(2.0), planning.seconds_text(1.25), planning.seconds_text(0)), ('2', '1.25', '0'))

    def test_validation_names_each_broken_rule(self):
        def errors(**change):
            return ' '.join(planning.validate_beats(sheet(**change), SHOT))
        beats = sheet()['beats']
        gap = [beats[0], {**beats[1], 'from': 1.8}, beats[2]]
        self.assertRegex(errors(beats=gap), r'Beat 2 starts at 1\.8 s but beat 1 ends at 1\.5 s: a gap')
        overlap = [beats[0], {**beats[1], 'from': 1.2}, beats[2]]
        self.assertRegex(errors(beats=overlap), r'they overlap')
        self.assertRegex(errors(beats=[beats[0], beats[1], {**beats[2], 'to': 3.5}]), r'last beat ends at 3\.5 s; the shot is 4 seconds long')
        self.assertRegex(errors(beats=[{**beats[0], 'from': 0.5}, *beats[1:]]), r'first beat starts at 0\.5 s')
        self.assertRegex(errors(beats=[{**beats[0], 'to': 0.3}, {**beats[1], 'from': 0.3}, beats[2]]), r'at least 0\.5 s')
        lost = sheet(setup='One continuous 4-second shot in @SET-01. Kael stands at the console.')
        self.assertRegex(' '.join(planning.validate_beats(lost, SHOT)), r'Dropped the tag\(s\) @CAST-01')
        self.assertRegex(errors(setup=sheet()['setup'] + ' @CAST-02 watches.'), r'Added the tag\(s\) @CAST-02')
        brand = [{**beats[0], 'camera': 'wide view on an ARRI Alexa 65'}, *beats[1:]]
        self.assertRegex(errors(beats=brand), r'brand\(s\) ARRI, Alexa')
        self.assertRegex(errors(sound='a RED camera hum'), r'brand\(s\) RED')
        self.assertEqual(errors(sound='a red warning light hums'), '', 'the colour is fine')
        self.assertRegex(errors(setup=sheet()['setup'] + ' Shot on a 40mm lens.'), r'lens\(es\) 40mm')
        self.assertRegex(' '.join(planning.validate_beats({**sheet(), 'camera': 'x'}, SHOT)), r'Unexpected field "camera"')
        self.assertRegex(' '.join(planning.validate_beats({**sheet(), 'beats': [{'from': '0', 'to': 4, 'camera': 'a', 'action': 'b'}]}, SHOT)),
                         r'must be numbers')
        self.assertRegex(' '.join(planning.validate_beats(sheet(), {**SHOT, 'shot': {**SHOT['shot'], 'seconds': 5}})), r'4, 6, 8 or 10')
        variant = {**SHOT, 'shot': {**SHOT['shot'], 'text': 'Mira @CAST-02:coat lunges at @CAST-01. @SET-01'},
                   'cast': [{'code': '@CAST-02'}, {'code': '@CAST-01'}]}
        self.assertRegex(' '.join(planning.validate_beats(sheet(setup='One shot in @SET-01; @CAST-02 faces @CAST-01.'), variant)),
                         r'Dropped the tag\(s\) @CAST-02:coat', 'a look suffix is part of the tag')

    def test_reference_answers_of_the_evaluation_set_pass_and_rule_fallbacks_validate(self):
        cases = crew_eval.load_cases(['beats'])
        self.assertEqual(len(cases), 8)
        for case in cases:
            with self.subTest(case=case['id']):
                self.assertEqual(planning.validate_beats(case['reference'], case['input']), [])
                fallback = planning.beats_fallback(case['input'])
                self.assertEqual(planning.validate_beats(fallback, case['input']), [])
                self.assertEqual(len(fallback['beats']), 1)
                self.assertEqual(fallback['beats'][0]['to'], case['input']['shot']['seconds'])

    def test_tag_and_brand_rules_match_the_evaluation_set_and_manuals(self):
        self.assertEqual(planning.TAG.pattern, crew_eval.TAG.pattern)
        self.assertEqual(planning.LENS_MENTION.pattern, crew_eval.LENS_MENTION.pattern)
        for brand in ('ARRI', 'Alexa', 'Panavision', 'V-Raptor', 'RED Komodo', 'Cooke', 'Zeiss', 'Sony', 'Bolex', 'Steadicam'):
            self.assertTrue(planning.brands_in('shot on ' + brand), brand)
        self.assertEqual(planning._scrub('ARRI Alexa 65 / 35mm Anamorphic f/1.4', rig=True), '35mm Anamorphic f/1.4')
        self.assertEqual(planning._scrub('RED V-Raptor XL / 90mm Macro', rig=True), 'Macro')


class CameraContractTests(unittest.TestCase):
    def test_vocabulary_is_the_stage_and_the_evaluation_set(self):
        source = (ROOT / 'ui' / 'src' / 'previs' / 'plan.js').read_text(encoding='utf-8')
        self.assertEqual((planning.LENSES, planning.MOVES, planning.DURATIONS), (story_previs.LENSES, story_previs.MOVES, story_previs.DURATIONS))
        self.assertEqual((tuple(crew_eval.LENSES), tuple(crew_eval.MOVES)), (planning.LENSES, planning.MOVES))
        self.assertEqual((planning.SIZES, planning.ANGLES), (crew_eval.SIZES, crew_eval.ANGLES))
        for move, pattern in planning.SLATE_MOVES:  # the port of planFromSlate's move chain, in its order
            self.assertIn(f"/{pattern}/.test(m) ? '{move}'", source)
        positions = [source.index(f"/{pattern}/.test(m)") for _, pattern in planning.SLATE_MOVES]
        self.assertEqual(positions, sorted(positions))
        tool = tool_registry.get('propose_camera').schema['properties']
        self.assertEqual((tuple(tool['lens']['enum']), tuple(tool['move']['enum'])), (planning.LENSES, planning.MOVES))
        self.assertEqual((tuple(tool['size']['enum']), tuple(tool['angle']['enum'])), (planning.SIZES, planning.ANGLES))
        self.assertEqual(planning.CAMERA_SCHEMA['properties']['lens']['enum'], list(planning.LENSES))

    def test_texts_must_read_back_as_the_chosen_lens_and_move(self):
        for move in planning.MOVES:
            answer = planning.camera_answer(50, move)
            self.assertEqual(planning.validate_camera(answer), [], move)
            self.assertEqual((planning.slate_move(answer['cameraMotion']), planning.slate_lens(answer['opticalRig'])), (move, 50))
        good = planning.camera_answer(85, 'pushin', 'close', 'low', reason='The hand matters.')
        self.assertEqual(planning.validate_camera(good), [])
        check = lambda **c: ' '.join(planning.validate_camera({**good, **c}))  # noqa: E731
        self.assertRegex(check(lens=40), r'"lens" must be one of 24, 35, 50, 85')
        self.assertRegex(check(move='zoom'), r'"move" must be one of')
        self.assertRegex(check(size='cowboy'), r'"size" must be one of')
        self.assertRegex(check(opticalRig='ARRI Alexa / 85mm Prime'), r'brand\(s\) ARRI, Alexa')
        self.assertRegex(check(opticalRig='Prime lens, shallow focus'), r'must name the lens in millimetres')
        self.assertRegex(check(opticalRig='50mm prime'), r'names 50mm but the lens is 85mm')
        self.assertRegex(check(cameraMotion='Static tripod, locked off'), r'reads as static, not pushin')
        self.assertRegex(check(cameraMotion='Gentle drift toward him'), r'names no move the 3D stage reads')
        self.assertRegex(' '.join(planning.validate_camera({**good, 'lens': True})), r'"lens" must be one of')

    def test_rule_fallback_keeps_the_plan_else_uses_the_storyboard_rules(self):
        stored = planning.camera_fallback({**SHOT, 'plan': {'lens': 24, 'move': 'crane', 'source': 'stored'}})
        self.assertEqual((stored['lens'], stored['move'], stored['angle']), (24, 'crane', 'high'))
        self.assertIn('stored 3D plan', stored['reason'])
        ruled = planning.camera_fallback({**SHOT, 'plan': {}})
        from project_docs.story_adaptation import infer_shot_grammar
        seed = infer_shot_grammar(SHOT['shot']['text'], 0, 3)['previsPlan']
        self.assertEqual((ruled['lens'], ruled['move']), (seed['lens'], seed['move']))
        self.assertEqual(planning.validate_camera(ruled), [])
        self.assertFalse(planning.brands_in(ruled['opticalRig']), 'the rules choose the lens; the brand of the old rig stays out')


class PipelineTests(unittest.TestCase):
    def test_a_valid_answer_is_the_model_output(self):
        call = calls(sheet())
        outcome = crew_jobs.run_pipeline(planning.BEATS, SHOT, call)
        self.assertEqual((outcome.source, outcome.output, len(outcome.attempts)), ('model', sheet(), 1))
        self.assertTrue(outcome.attempts[0]['valid'])
        self.assertIn('@CAST-01 @SET-01', call.sent[0]['text'])
        self.assertNotIn('ARRI', call.sent[0]['text'], 'the maker of the current rig is not shown to the model')

    def test_an_invalid_answer_is_retried_once_with_the_errors(self):
        broken = sheet(beats=[*sheet()['beats'][:2], {**sheet()['beats'][2], 'to': 3.5}])
        call = calls(broken, sheet())
        outcome = crew_jobs.run_pipeline(planning.BEATS, SHOT, call)
        self.assertEqual((outcome.source, [a['valid'] for a in outcome.attempts]), ('model', [False, True]))
        retry = call.sent[1]
        self.assertIn('last beat ends at 3.5 s', retry['text'])
        self.assertEqual([m['role'] for m in retry['history']], ['user', 'assistant'])
        self.assertEqual(json.loads(retry['history'][1]['content']), broken)

    def test_invalid_twice_falls_back_to_rules_and_says_so(self):
        broken = sheet(setup='One continuous 4-second shot.')
        call = calls(crew_jobs.Reply(ok=False, answer='Here is the sheet: maybe', failure='output', error='not JSON'), broken)
        outcome = crew_jobs.run_pipeline(planning.BEATS, SHOT, call)
        self.assertEqual(outcome.source, 'rule_fallback')
        self.assertEqual(outcome.output, planning.beats_fallback(SHOT))
        self.assertEqual(outcome.attempts[0]['errors'], ['The answer is not one JSON object.'])
        self.assertRegex(' '.join(outcome.errors), r'Dropped the tag')
        self.assertEqual(len(call.sent), 2, 'at most one retry')

    def test_a_missing_model_is_not_bad_output_and_never_falls_back(self):
        call = calls(crew_jobs.Reply(ok=False, failure='local', error='Local model endpoint is not reachable.'))
        with self.assertRaises(crew_jobs.ModelUnavailable) as raised:
            crew_jobs.run_pipeline(planning.BEATS, SHOT, call)
        self.assertEqual(raised.exception.attempts[0]['failure'], 'local')
        with self.assertRaises(crew_jobs.Canceled):
            crew_jobs.run_pipeline(planning.BEATS, SHOT, calls(sheet()), cancelled=lambda: True)

    def test_answers_with_thinking_or_fences_are_read(self):
        self.assertEqual(crew_jobs.parse_answer('<think>{"draft": 1}</think>\n```json\n{"a": 1}\n```'), ({'a': 1}, ''))
        self.assertEqual(crew_jobs.parse_answer('Sure: {"a": 2} done'), ({'a': 2}, ''))
        self.assertEqual(crew_jobs.parse_answer('[1, 2]')[1], 'The answer is not one JSON object.')


class EvalAdapterTests(unittest.TestCase):
    def test_the_adapter_runs_the_real_beats_job_on_two_cases(self):
        cases = [c for c in crew_eval.load_cases(['beats']) if c['id'].startswith(('beats-01', 'beats-07'))]
        self.assertEqual(len(cases), 2)
        answers = {cases[0]['input']['shot']['id']: [cases[0]['reference']],
                   cases[1]['input']['shot']['id']: [{'setup': 'no tags'}, {'setup': 'still no tags'}]}
        seen = []

        def model(instructions, text, history):
            shot = re.match(r'Shot (\S+),', text if not history else history[0]['content'])[1]
            seen.append(shot)
            return crew_jobs.Reply(ok=True, answer=json.dumps(answers[shot][len(history) // 2]), model='fake')
        report = crew_eval.run(cases, planning.eval_adapter(model), label='fake model')
        first, second = report['types']['beats']['results']
        self.assertEqual((first['hard_ok'], first['score']), (True, 1.0))
        self.assertFalse(second['hard_ok'], 'the rule fallback is what the user would get, and it is scored')
        self.assertEqual(seen, ['S06', 'S24', 'S24'])
        with self.assertRaises(NotImplementedError):
            planning.eval_adapter(model)('blocking-01', 'blocking', {})

    def test_the_cli_adapter_refuses_a_hosted_model(self):
        with self.assertRaises(RuntimeError):
            planning.local_model_caller({'OPENBENCH_API_BASE': 'https://openrouter.example/v1', 'OPENBENCH_MODEL': 'x'})
        self.assertTrue(callable(planning.local_model_caller({})))


# ---------- against the real servers ----------

class FakeResponse:
    def __init__(self, raw):
        self.raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, limit=-1):
        return self.raw


PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32


def fake_solver(request, *, title='', files=None, render=True, timeout=None):
    """The headless solve of a camera op, faked (tests/test_previs_ops.py and the golden file pin the real one): the shot's
    stored plan or seed with the op's lens and move and a two-key path, plus a contact sheet."""
    camera = next(op for op in request['ops'] if op['op'] == 'camera')
    seed = {key: value for key, value in (request['shot'].get('previsPlan') or {}).items() if key in ('set', 'action', 'facing', 'seconds')}
    base = request['stored'] or {'set': 'observatory', 'move': 'pushin', 'lens': 35, 'action': 'stand', 'facing': 'console',
                                 'mood': 'grey', 'seconds': 4, **seed}
    plan = {**base, 'lens': camera['lens'], 'move': camera['move'], 'keys': [[0, [1.0, 1.4, -2.5], [0, 1.4, 0]], [96, [-1.0, 1.4, -2.5], [0, 1.4, 0]]]}
    return {'solved': {'version': 1, 'plan': plan, 'warnings': [], 'base': {}}, 'image': PNG, 'renderError': None, 'browser': 'fake',
            'sheet': {'width': 1944, 'height': 818, 'frames': [{'frame': 0, 'seconds': 0}]}, 'seconds': 0.1}


class FakeEndpoint:
    """An OpenAI-compatible endpoint behind an opener: answers in order and records each request body."""

    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def __call__(self, request, timeout=None):
        self.requests.append(json.loads(request.data.decode('utf-8')))
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        content = answer if isinstance(answer, str) else json.dumps(answer)
        return FakeResponse(json.dumps({'model': 'qwen3.8:27b', 'choices': [{'message': {'role': 'assistant', 'content': content}}],
                                        'usage': {'prompt_tokens': 900, 'completion_tokens': 300}}).encode())


LOCAL_ENV = {key: '' for key in ('OPENBENCH_PROVIDER', 'PROJECT_ASSISTANT_ENGINE', 'OPENBENCH_API_BASE', 'OPENBENCH_MODEL',
                                 'PROJECT_ASSISTANT_MODEL', 'OPENBENCH_API_KEY', 'OPENAI_API_KEY', 'OPENBENCH_REASONING_EFFORT')}

@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'set OPENBENCH_TEST_DB_URI for crew job tests')
class CrewJobServerTests(unittest.TestCase):
    request = fixture.StoryHTTPTests.request
    call = fixture.StoryHTTPTests.call
    ok = fixture.StoryHTTPTests.ok
    prepare = fixture.StoryHTTPTests.prepare

    def setUp(self):
        fixture.StoryHTTPTests.setUp(self)
        import psycopg
        from project_assistant import agent_registry, orchestrator as cp, store
        self.connect = lambda: psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI'])
        env = patch.dict(os.environ, LOCAL_ENV)
        env.start()
        for key in LOCAL_ENV:
            os.environ.pop(key, None)
        self.addCleanup(env.stop)
        crew_readiness.forget()
        self.addCleanup(crew_readiness.forget)
        self.probe = patch.object(crew_readiness, '_probe', return_value=('ok', {'qwen3.8:27b'}))
        self.probe.start()
        self.addCleanup(self.probe.stop)
        solver = patch.object(headless_previs, 'run', fake_solver)  # R27: no browser in unit tests
        solver.start()
        self.addCleanup(solver.stop)
        agent_registry.ensure_default_agents(self.conn, self.slug)
        store.set_setting(self.conn, self.slug, 'builtin_worker_seen_at', cp.now().isoformat())
        self.conn.commit()
        self.shots = self.prepare()

    def tearDown(self):
        self.conn.rollback()
        with self.conn.cursor() as cur:
            cur.execute('DELETE FROM projectops.story_record WHERE project_slug=%s', (self.slug,))
        self.conn.commit()
        fixture.StoryHTTPTests.tearDown(self)

    # ---- helpers ----
    def ask(self, shot, kind='beat', body=None, expect=200):
        code, payload = self.call(f"/shots/{shot['shotId']}/{kind}-proposals", 'POST', body or {})
        self.assertEqual(code, expect, payload)
        return payload['data'] if expect == 200 else payload

    def run_job(self, endpoint, worker='test-worker'):
        claimed = crew_jobs.claim(self.conn, worker, slug=self.slug)
        self.conn.commit()
        self.assertIsNotNone(claimed)
        status = crew_jobs.execute(self.connect, claimed, worker, opener=endpoint)
        return status, crew_jobs.public(crew_jobs._load(self.conn, claimed['crewJob']))

    def proposal(self, proposal_id):
        from project_assistant import store
        self.conn.rollback()
        return store.proposal(self.conn, proposal_id)

    def decide(self, proposal_id, verb='apply', body=None):
        code, payload, _ = self.request(f'/projects/api/{self.slug}/assistant/proposals/{proposal_id}/{verb}', method='POST', data=body or {})
        return code, payload

    def cell(self, shot, header):
        from project_docs import story_openapi as story
        self.conn.rollback()
        _, row = story.find_row(self.conn, shot['shotId'], 'shot')
        return row['cells'][next(i for i, h in enumerate(row['headers']) if re.search(header, h, re.I))]

    def counted(self, sql):
        self.conn.rollback()
        with self.conn.cursor() as cur:
            cur.execute(sql, (self.slug,))
            return cur.fetchone()[0]

    def beats_for(self, shot, seconds=4):
        text = self.cell(shot, 'prompt')
        tags = ' '.join(sorted(planning.tags_in(text), key=text.find))
        half = seconds / 2
        return {'setup': f'One continuous {seconds}-second shot. {tags} in frame, facing the camera.',
                'beats': [{'from': 0, 'to': half, 'camera': 'medium shot at eye level', 'action': 'he looks up into the lens'},
                          {'from': half, 'to': seconds, 'camera': 'slow push in', 'action': 'his eyes widen; he holds still'}],
                'sound': 'rain on glass', 'constraints': ['One person only', 'No text']}

    # ---- R7: no model, nothing written ----
    def test_without_a_usable_model_the_crew_answers_409_and_writes_nothing(self):
        shot = self.shots[0]
        self.probe.stop()
        with patch.object(crew_readiness, '_probe', return_value=('down', None)):
            crew_readiness.forget()
            refused = self.ask(shot, expect=409)
        self.probe.start()
        self.assertEqual(refused['code'], crew_jobs.NOT_READY)
        self.assertIn("The crew can't work yet: the model server is not reachable", refused['message'])
        self.assertIn('Nothing was written', refused['message'])
        self.assertEqual(refused['details']['agentKey'], 'sheet_ops')
        self.assertEqual({b['code'] for b in refused['details']['blockers']}, {'provider_unreachable'})
        self.assertEqual(self.counted("SELECT count(*) FROM projectops.story_record WHERE kind='crew_job' AND project_slug=%s"), 0)
        self.assertEqual(self.counted('SELECT count(*) FROM projectops.assistant_proposal WHERE project_slug=%s'), 0)
        self.assertEqual(self.counted('SELECT count(*) FROM projectops.agent_usage_reservation WHERE project_slug=%s'), 0)
        from project_assistant import orchestrator as cp, store
        store.set_setting(self.conn, self.slug, 'builtin_worker_seen_at', (cp.now() - dt.timedelta(hours=1)).isoformat())
        self.conn.commit()
        crew_readiness.forget()
        self.assertEqual(self.ask(shot, 'camera', expect=409)['details']['blockers'][0]['code'], 'worker_not_running')
        self.assertEqual(self.ask(shot, body={'seconds': 5}, expect=422)['code'], 'DRAMA_VALIDATION_FAILED')

    # ---- R7/R19: a beat sheet becomes a cell-scoped proposal ----
    def test_a_valid_sheet_becomes_a_proposal_that_writes_only_when_adopted(self):
        shot = self.shots[0]
        before = self.cell(shot, 'prompt')
        job = self.ask(shot)
        self.assertEqual((job['kind'], job['role'], job['status'], job['shotId']), ('beats', 'sheet_ops', 'queued', shot['shotId']))
        self.assertEqual(self.ask(shot)['jobId'], job['jobId'], 'an active job is returned, not doubled')
        answer = self.beats_for(shot)
        endpoint = FakeEndpoint(answer)
        status, done = self.run_job(endpoint)
        self.assertEqual((status, done['status'], done['source']), ('succeeded', 'succeeded', 'model'), done)
        request = endpoint.requests[0]
        self.assertEqual((request['model'], request['reasoning_effort']), ('qwen3.8:27b', 'medium'))
        self.assertEqual(request['response_format']['json_schema']['name'], 'crew_beats')
        self.assertNotIn('tools', request)
        [proposal_id] = done['result']['proposalIds']
        proposal = self.proposal(proposal_id)
        self.assertEqual((proposal['action'], proposal['status'], proposal['agent_key']), ('table_edit', 'pending', 'sheet_ops'))
        self.assertEqual(proposal['target']['crew'], {'jobId': job['jobId'], 'kind': 'beats', 'source': 'model', 'role': 'sheet_ops'})
        [group] = proposal['target']['review']['groups']
        self.assertEqual((group['row_id'], [c['column'] for c in group['changes']]), (shot['rowId'], ['Action & Audio Prompt']))
        self.assertEqual(group['changes'][0]['after'], planning.compile_beats(answer))
        self.assertEqual(self.cell(shot, 'prompt'), before, 'a proposal writes nothing')
        listed = self.ok(f"/shots/{shot['shotId']}/crew-jobs")['items']
        self.assertEqual((listed[0]['jobId'], listed[0]['result']['compiled']), (job['jobId'], planning.compile_beats(answer)))
        code, applied = self.decide(proposal_id)
        self.assertEqual(code, 200, applied)
        self.assertEqual(self.cell(shot, 'prompt'), planning.compile_beats(answer))
        # Attribution and governance: one governed, unbilled local call charged to the Cinematographer for the requester.
        self.conn.rollback()
        with self.conn.cursor() as cur:
            cur.execute("""SELECT agent_key, owner_id::text, usage_kind, state, model_name, session_key, accounted_cost_usd
                           FROM projectops.agent_usage_reservation WHERE project_slug=%s""", (self.slug,))
            reservations = cur.fetchall()
            cur.execute("SELECT action, detail FROM projectops.audit_log WHERE project_slug=%s AND action LIKE %s ORDER BY id", (self.slug, '%crew%'))
            audits = cur.fetchall()
            cur.execute("SELECT count(*) FROM projectops.audit_log WHERE project_slug=%s AND action='agent_context_read' AND detail->>'agentKey'='sheet_ops'", (self.slug,))
            reads = cur.fetchone()[0]
        self.assertEqual(len(reservations), 1)
        agent, owner, kind, state, model, session, cost = reservations[0]
        self.assertEqual((agent, owner, kind, state, model, session), ('sheet_ops', self.actor, 'llm_turn', 'finalized', 'qwen3.8:27b', 'crew:' + job['jobId']))
        self.assertFalse(cost, 'a local model is unbilled')
        self.assertEqual([a for a, _ in audits], ['crew_job_requested', 'crew_job_finished'])
        self.assertEqual(audits[1][1]['proposalIds'], [proposal_id])
        self.assertEqual(reads, 2, 'read_shot and read_cast, audited as the Cinematographer')
        self.assertEqual(done['usage'], {'prompt_tokens': 900, 'completion_tokens': 300})
        self.assertEqual(done['model'], 'qwen3.8:27b')
        self.assertEqual([r['tool'] for r in crew_jobs._load(self.conn, job['jobId'])['context']], ['read_shot', 'read_cast'])

    def test_an_invalid_sheet_is_retried_then_a_second_failure_falls_back_to_rules(self):
        first, second = self.shots[:2]
        answer = self.beats_for(first)
        gap = {**answer, 'beats': [answer['beats'][0], {**answer['beats'][1], 'from': 2.5}]}
        self.ask(first)
        endpoint = FakeEndpoint(gap, answer)
        status, done = self.run_job(endpoint)
        self.assertEqual((status, done['source'], [a['valid'] for a in done['attempts']]), ('succeeded', 'model', [False, True]))
        self.assertRegex(done['attempts'][0]['errors'][0], 'a gap')
        retry = endpoint.requests[1]['messages']
        self.assertEqual([m['role'] for m in retry], ['system', 'user', 'assistant', 'user'])
        self.assertIn('a gap', retry[-1]['content'])
        # Twice invalid (a malformed answer, then a brand name): the rule fallback, marked on the job and the proposal.
        self.ask(second, body={'seconds': 6, 'note': 'Keep it quiet.'})
        branded = {**self.beats_for(second, 6), 'setup': 'One continuous 6-second shot on an ARRI Alexa. ' + ' '.join(planning.tags_in(self.cell(second, 'prompt')))}
        endpoint = FakeEndpoint('I would rather describe it in prose.', branded)
        status, done = self.run_job(endpoint)
        self.assertEqual((status, done['source']), ('succeeded', 'rule_fallback'), done)
        self.assertIn("Director's note: Keep it quiet.", endpoint.requests[0]['messages'][-1]['content'])
        self.assertEqual(done['result']['sheet']['beats'][0]['to'], 6)
        proposal = self.proposal(done['result']['proposalIds'][0])
        self.assertEqual(proposal['target']['crew']['source'], 'rule_fallback')
        self.assertTrue(proposal['content'].startswith(planning.FALLBACK_NOTE))
        board = self.request(f'/projects/api/{self.slug}/orchestration/board?limit=50')[1]
        item = next(i for i in board['done'] if i.get('job_id') == done['jobId'])
        self.assertEqual((item['kind'], item['agent_key'], item['status']), ('crew_job', 'sheet_ops', 'succeeded'))
        self.assertTrue(item['summary'].startswith('Rule fallback, not model-written'))

    def test_a_model_that_goes_away_fails_the_job_without_a_fallback(self):
        shot = self.shots[0]
        self.ask(shot)
        refused = urllib.error.URLError(ConnectionRefusedError('down'))
        status, done = self.run_job(FakeEndpoint(refused))
        self.assertEqual((status, done['status'], done['failure']), ('failed', 'failed', 'local'))
        self.assertIn('Start Ollama', done['error'])
        self.assertEqual(self.counted('SELECT count(*) FROM projectops.assistant_proposal WHERE project_slug=%s'), 0)

    # ---- R17: proposals pin their cells, not the page ----
    def test_proposals_are_cell_scoped_and_survive_edits_to_other_rows(self):
        from project_docs import story_openapi as story
        first, second = self.shots[:2]
        made = []
        for shot in (first, second, first):
            self.ask(shot)
            status, done = self.run_job(FakeEndpoint(self.beats_for(shot)))
            self.assertEqual(status, 'succeeded', done)
            made.append(done['result']['proposalIds'][0])
            if shot is first and len(made) == 1:
                code, refused = self.decide(made[0], 'dismiss')
                self.assertEqual(code, 200, refused)
        prompt = next(i for i, h in enumerate(story.find_row(self.conn, first['shotId'], 'shot')[1]['headers']) if 'Prompt' in h)
        story.mutate_row(self.conn, self.me, self.slug, 'cinema-studio', second['rowId'], {prompt: 'Rewritten by the director. @CAST-01'})
        self.conn.commit()
        code, applied = self.decide(made[2])
        self.assertEqual(code, 200, 'an edit to another row does not fail this proposal')
        self.assertEqual(self.cell(first, 'prompt'), applied['proposal']['target']['review']['groups'][0]['changes'][0]['after'])
        code, refused = self.decide(made[1])
        self.assertEqual(code, 409, 'the same cell changed: this one fails and says so')
        self.assertIn('changed after this proposal was made', refused['error'])

    # ---- R20: camera and optics ----
    def test_a_camera_job_proposes_both_text_cells_in_the_stage_vocabulary(self):
        shot = self.shots[0]
        self.ask(shot, 'camera')
        answer = {'size': 'close', 'angle': 'low', 'lens': 85, 'move': 'orbit', 'opticalRig': '85mm prime, shallow focus, low angle close-up',
                  'cameraMotion': 'Slow orbit from his left to his right', 'reason': 'The decision reads on his face.'}
        endpoint = FakeEndpoint(answer)
        status, done = self.run_job(endpoint)
        self.assertEqual((status, done['source']), ('succeeded', 'model'), done)
        self.assertEqual(endpoint.requests[0]['reasoning_effort'], 'low')
        self.assertEqual(done['result']['previsOps'], [{'op': 'camera', 'size': 'close', 'angle': 'low', 'lens': 85, 'move': 'orbit'}])
        # R27: the camera op also becomes a 3D plan proposal (the ghost camera in the 3D Stage), next to the cell proposal.
        previs = self.proposal(done['result']['previsProposalId'])
        self.assertEqual((previs['action'], previs['status'], previs['agent_key'], previs['target']['field'], previs['target']['ops']),
                         ('shot_meta', 'pending', 'sheet_ops', 'previsPlan', done['result']['previsOps']))
        self.assertEqual((previs['target']['value']['lens'], previs['target']['value']['move'], previs['target']['solve']['status']),
                         (85, 'orbit', 'solved'))
        self.assertTrue(previs['target']['preview']['url'].startswith(f'/projects/api/{self.slug}/assets/pa_'))
        proposal = self.proposal(done['result']['proposalIds'][0])
        [group] = proposal['target']['review']['groups']
        changes = {c['column']: c['after'] for c in group['changes']}
        self.assertEqual(changes, {'Optical Rig (Camera & Lens)': answer['opticalRig'], 'Camera Motion': answer['cameraMotion']})
        # The same camera again proposes nothing; brand names twice fall back to the 3D plan or the storyboard rules.
        self.decide(proposal['id'])
        self.ask(shot, 'camera')
        self.assertTrue(self.run_job(FakeEndpoint(answer))[1]['result']['unchanged'])
        self.ask(shot, 'camera')
        branded = {**answer, 'opticalRig': 'Panavision 85mm'}
        status, done = self.run_job(FakeEndpoint(branded, branded))
        self.assertEqual(done['source'], 'rule_fallback')
        self.assertFalse(planning.brands_in(done['result']['camera']['opticalRig']))

    def test_a_camera_job_keeps_its_cells_when_the_3d_plan_cannot_take_the_camera(self):
        shot = self.shots[0]
        answer = {'size': 'medium', 'angle': 'eye', 'lens': 50, 'move': 'static', 'opticalRig': '50mm prime, medium shot at eye level',
                  'cameraMotion': 'Static tripod, locked off', 'reason': 'Hold on the standoff.'}
        shot_meta = "SELECT count(*) FROM projectops.assistant_proposal WHERE project_slug=%s AND action='shot_meta'"
        self.ask(shot, 'camera')
        with patch.object(headless_previs, 'run', side_effect=headless_previs.Refused('ops[0].to', 'ops[0].to must be the key a static camera holds.')):
            status, done = self.run_job(FakeEndpoint(answer))
        self.assertEqual(status, 'succeeded', done)
        self.assertEqual((done['result']['previsProposalId'], len(done['result']['proposalIds'])), (None, 1))
        self.assertIn('static camera', done['result']['previsError'])
        self.assertEqual(self.counted(shot_meta), 0, 'the refused 3D proposal left nothing behind')
        self.assertEqual(self.proposal(done['result']['proposalIds'][0])['status'], 'pending')
        # Without a headless browser the camera op waits as operations only, for the 3D Stage to solve.
        self.ask(shot, 'camera')
        with patch.object(headless_previs, 'run', side_effect=headless_previs.Unavailable('no_browser', 'No browser.')):
            status, done = self.run_job(FakeEndpoint({**answer, 'lens': 85, 'opticalRig': '85mm prime, close-up at eye level'}))
        previs = self.proposal(done['result']['previsProposalId'])
        self.assertEqual((previs['target']['value'], previs['target']['solve']['status']), (None, 'ops_only'))

    # ---- cancel ----
    def test_a_job_can_be_canceled_queued_or_running_and_then_writes_nothing(self):
        first, second = self.shots[:2]
        queued = self.ask(first)
        path = f'/projects/api/{self.slug}/orchestration/crew-jobs/{queued["jobId"]}/cancel'
        code, canceled = self.request(path, method='POST', data={})[:2]
        self.assertEqual((code, canceled['job']['status']), (200, 'canceled'), canceled)
        self.assertIsNone(crew_jobs.claim(self.conn, 'test-worker', slug=self.slug))
        self.conn.rollback()
        self.assertEqual(self.request(path, method='POST', data={})[0], 409, 'a finished job stays finished')
        running = self.ask(second)
        claimed = crew_jobs.claim(self.conn, 'test-worker', slug=self.slug)
        self.conn.commit()
        board = self.request(f'/projects/api/{self.slug}/orchestration/board?limit=50')[1]
        item = next(i for i in board['working'] if i.get('job_id') == running['jobId'])
        self.assertEqual((item['status'], item['agent_key'], item['title']), ('running', 'sheet_ops', 'Beat sheet · ' + second['shotIndex']))
        roster = next(a for a in board['idle'] if a['agent_key'] == 'sheet_ops')
        self.assertEqual(roster['active_dispatches'], 1)
        code, _ = self.request(f'/projects/api/{self.slug}/orchestration/crew-jobs/{running["jobId"]}/cancel', method='POST', data={})[:2]
        self.assertEqual(code, 200)
        endpoint = FakeEndpoint(self.beats_for(second))
        self.assertEqual(crew_jobs.execute(self.connect, claimed, 'test-worker', opener=endpoint), 'canceled')
        self.assertEqual(endpoint.requests, [], 'canceled before the model call')
        # Canceled while the model answers: the call cannot be interrupted, but its answer is dropped.
        late = self.ask(second)
        claimed = crew_jobs.claim(self.conn, 'test-worker', slug=self.slug)
        self.conn.commit()
        answer = self.beats_for(second)

        def cancel_then_answer(request, timeout=None):
            self.assertEqual(self.request(f'/projects/api/{self.slug}/orchestration/crew-jobs/{late["jobId"]}/cancel', method='POST', data={})[0], 200)
            return FakeEndpoint(answer)(request, timeout)
        self.assertEqual(crew_jobs.execute(self.connect, claimed, 'test-worker', opener=cancel_then_answer), 'canceled')
        self.assertEqual(crew_jobs.public(crew_jobs._load(self.conn, late['jobId']))['status'], 'canceled')
        self.assertEqual(self.counted('SELECT count(*) FROM projectops.assistant_proposal WHERE project_slug=%s'), 0)
        self.assertEqual(self.request(f'/projects/api/{self.slug}/orchestration/crew-jobs/cj_{"0" * 32}/cancel', method='POST', data={})[0], 404)

    # ---- the model-facing tools ----
    def test_tools_check_the_sheet_and_the_camera_and_create_the_same_proposals(self):
        from project_assistant import tools
        from project_docs.service import Identity
        shot = self.shots[0]
        ctx = tools.ToolContext(self.connect, self.slug, Identity(self.actor, 'Tool test', 'admin'), Path(tempfile.gettempdir()), None,
                                agent_key='sheet_ops')
        with self.assertRaises(tools.ToolError) as refused:
            tools.call(ctx, 'propose_shot_prompt', {'shot_id': shot['shotId'], 'sheet': {**self.beats_for(shot), 'setup': 'No tags here.'}})
        self.assertIn('INVALID_SHEET: Dropped the tag', str(refused.exception))
        out = tools.call(ctx, 'propose_shot_prompt', {'shot_id': shot['shotId'], 'sheet': self.beats_for(shot)})
        self.assertRegex(out, r'Created proposal #\d+ for .+ Action & Audio Prompt')
        self.assertIn('0-2s: medium shot at eye level; he looks up into the lens.', out)
        with self.assertRaises(tools.ToolError):
            tools.call(ctx, 'propose_camera', {'shot_id': shot['shotId'], 'lens': 85, 'move': 'static', 'camera_motion': 'Slow push in'})
        with self.assertRaises(tools.ToolError):
            tools.call(ctx, 'propose_camera', {'shot_id': shot['shotId'], 'lens': 40, 'move': 'static'})
        out = tools.call(ctx, 'propose_camera', {'shot_id': shot['shotId'], 'lens': 24, 'move': 'track', 'size': 'wide'})
        self.assertIn('Optical Rig: 24mm prime, wide shot, eye level', out)
        self.conn.rollback()
        with self.conn.cursor() as cur:
            cur.execute("SELECT target->'crew'->>'source', agent_key FROM projectops.assistant_proposal WHERE project_slug=%s ORDER BY id", (self.slug,))
            self.assertEqual(cur.fetchall(), [('tool', 'sheet_ops'), ('tool', 'sheet_ops')])
        with self.assertRaises(tools.ToolError):
            tools.call(ctx, 'propose_shot_prompt', {'shot_id': f'sh_{self.slug}_bnothere', 'sheet': self.beats_for(shot)})


if __name__ == '__main__':
    unittest.main()
