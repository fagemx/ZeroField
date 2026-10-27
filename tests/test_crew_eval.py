"""SPEC_20 R42: the crew evaluation set. The cases are well formed, the reference answers score full marks, and a
deliberately broken output is caught by each validator. No database, network or model is used."""
import contextlib
import copy
import importlib.util
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location('crew_eval', ROOT / 'scripts' / 'crew_eval.py')
ce = importlib.util.module_from_spec(_SPEC)
sys.modules['crew_eval'] = ce
_SPEC.loader.exec_module(ce)

CASES = {case['id']: case for case in ce.load_cases()}


def failed(case_id, output):
    """(result, ids of the hard checks that failed) for one output of one case."""
    result = ce.evaluate_case(CASES[case_id], output)
    return result, {item['id'] for item in result['hard'] if not item['ok']}


def reference(case_id):
    return copy.deepcopy(CASES[case_id]['reference'])


class CaseFileTests(unittest.TestCase):
    def test_eight_cases_of_each_type(self):
        for name in ce.TYPES:
            self.assertGreaterEqual(sum(1 for case in CASES.values() if case['type'] == name), 8, name)

    def test_cases_are_well_formed(self):
        for case in CASES.values():
            self.assertEqual(ce.check_case(case['type'], case), [], case['id'])

    def test_ids_are_unique_and_name_their_type(self):
        self.assertEqual(len(CASES), len(ce.load_cases()))
        for case_id, case in CASES.items():
            self.assertTrue(case_id.startswith(case['type'] + '-'), case_id)

    def test_every_case_is_a_hard_case(self):
        for case in CASES.values():
            self.assertEqual(case['difficulty']['face'], 'front', case['id'])
            self.assertEqual(case['difficulty']['tension'], 'high', case['id'])
            self.assertTrue(case['difficulty']['emotion'] and case['difficulty']['traps'], case['id'])

    def test_beats_cases_cover_every_duration_and_keep_faces_to_the_lens(self):
        beats = [case for case in CASES.values() if case['type'] == 'beats']
        self.assertEqual({case['input']['shot']['seconds'] for case in beats}, set(ce.DURATIONS))
        for case in beats:
            ids = [spec['id'] for spec in case['expect']['soft']]
            self.assertTrue(any(i.endswith('face_to_camera') for i in ids), case['id'])
            self.assertTrue(any(i.startswith('no_back_views') for i in ids), case['id'])

    def test_blocking_cases_put_a_performer_in_front_of_the_lens(self):
        for case in (c for c in CASES.values() if c['type'] == 'blocking'):
            self.assertTrue(any(spec['check'] == 'place' and 'camera' in spec.get('facing_any', []) for spec in case['expect']['soft']), case['id'])

    def test_continuity_cases_include_clean_and_planted_seams(self):
        planted = [len(case['expect']['planted']) for case in CASES.values() if case['type'] == 'continuity']
        self.assertIn(0, planted)
        self.assertGreaterEqual(max(planted), 4)
        self.assertGreaterEqual(sum(1 for n in planted if n), 6)

    def test_a_control_character_in_a_pattern_is_caught(self):
        broken = copy.deepcopy(CASES['continuity-04-night-becomes-daylight'])
        broken['expect']['planted'][1]['evidence_any'] = ['\blit\b']  # "\b" in JSON is a backspace
        self.assertTrue(any('control characters' in line for line in ce.check_case('continuity', broken)))

    def test_a_malformed_case_is_reported(self):
        broken = copy.deepcopy(CASES['beats-01-tears-closeup'])
        broken['input']['shot']['seconds'] = 5
        broken['difficulty']['face'] = 'back'
        broken['expect']['soft'][0]['any'] = ['(unclosed']
        lines = ' | '.join(ce.check_case('beats', broken))
        for needle in ('seconds', 'cases are hard on purpose', 'bad regex'):
            self.assertIn(needle, lines)

    def test_vocabulary_is_the_stages_own(self):
        self.assertEqual((ce.LENSES, ce.MOVES, ce.DURATIONS), ((24, 35, 50, 85), ('pushin', 'pullout', 'orbit', 'crane', 'track', 'static'), (4, 6, 8, 10)))
        self.assertEqual(ce.SETS, ('observatory', 'parallax', 'empty'))
        self.assertEqual(set(ce.MOVE_WORDS), set(ce.MOVES))
        self.assertIn('room', ce.FACINGS)  # the stage's camera-side facing, which a place op may use for "toward the lens"

    def test_vocabulary_agrees_with_the_backend_validator_and_the_stage_targets(self):
        try:
            from project_docs import story_previs
        except Exception as error:  # the backend module is only a cross-check
            self.skipTest(f'project_docs.story_previs does not import here: {error}')
        self.assertEqual((ce.LENSES, ce.MOVES, ce.DURATIONS, ce.SETS), (story_previs.LENSES, story_previs.MOVES, story_previs.DURATIONS, story_previs.SETS))
        self.assertLessEqual(set(story_previs.SCENE_ANCHORS), set(ce.STAGE_TARGETS['observatory']))
        import re
        layers = tuple(re.findall(r"id: '(\w+)', role:", ce.PLAN_JS.read_text(encoding='utf-8')))
        self.assertEqual(layers, ce.STAGE_TARGETS['parallax'])


class ReferenceAnswerTests(unittest.TestCase):
    def test_reference_answers_score_full_marks(self):
        report = ce.run(list(CASES.values()), ce.reference_job(list(CASES.values())))
        self.assertEqual(report['totals']['cases'], len(CASES))
        self.assertEqual(report['totals']['percent'], 100.0)
        for name in ce.TYPES:
            block = report['types'][name]
            self.assertEqual(block['hard_pass'], block['cases'], name)
            for result in block['results']:
                self.assertEqual(result['score'], 1.0, f"{result['id']}: {[s for s in result['soft'] if s['value'] < 1]} {[h for h in result['hard'] if not h['ok']]}")
                self.assertTrue(all(item['ok'] for item in result['hard']))

    def test_the_command_line_self_check_passes(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(ce.main(['--reference']), 0)
            self.assertEqual(ce.main(['--check-cases']), 0)
        self.assertIn('TOTAL', out.getvalue())

    def test_saved_outputs_replay_from_a_canned_directory(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            saved, report_path = Path(tmp) / 'saved', Path(tmp) / 'out' / 'report.json'
            self.assertEqual(ce.main(['--reference', '--save', str(saved)]), 0)
            self.assertEqual(len(list(saved.glob('*.json'))), len(CASES))
            self.assertEqual(ce.main(['--canned', str(saved), '--label', 'replay', '--report', str(report_path)]), 0)
            report = json.loads(report_path.read_text(encoding='utf-8'))
        self.assertEqual((report['schema'], report['label'], report['totals']['percent']), (ce.REPORT_SCHEMA, 'replay', 100.0))
        self.assertEqual(set(report['types']), set(ce.TYPES))
        self.assertTrue(all(key in report['types']['beats'] for key in ('cases', 'hard_pass', 'hard_pass_rate', 'points', 'max_points', 'percent', 'mean_soft', 'results')))

    def test_a_missing_or_unreadable_output_fails_hard(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ce.main(['--canned', tmp, '--type', 'beats', '--fail-under', '50']), 1)
            self.assertEqual(ce.main(['--canned', tmp, '--type', 'beats']), 0)
            (Path(tmp) / 'beats-01-tears-closeup.json').write_text('{"setup": ', encoding='utf-8')
            report = ce.run([CASES['beats-01-tears-closeup']], ce.canned_job(tmp))
        result = report['types']['beats']['results'][0]
        self.assertFalse(result['hard_ok'])
        self.assertIn('not valid JSON', result['hard'][0]['detail'])

    def test_case_and_type_filters_select_cases(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(ce.main(['--reference', '--type', 'blocking', '--case', 'blocking-03']), 0)
        self.assertIn('blocking-03-shove-after-standoff', out.getvalue())
        self.assertNotIn('blocking-02', out.getvalue())

    def test_a_job_never_sees_the_expectations_and_cannot_change_a_case(self):
        case = copy.deepcopy(CASES['beats-01-tears-closeup'])
        seen = []

        def job(case_id, job_type, case_input):
            seen.append((case_id, job_type, sorted(case_input)))
            case_input['shot']['text'] = 'tampered'
            return reference('beats-01-tears-closeup')
        report = ce.run([case], job)
        self.assertEqual(seen, [('beats-01-tears-closeup', 'beats', ['cast', 'next_shot', 'previous_shot', 'props', 'set', 'shot'])])
        self.assertEqual(case, CASES['beats-01-tears-closeup'])
        self.assertEqual(report['totals']['percent'], 100.0)

    def test_a_job_that_raises_fails_the_case_without_stopping_the_run(self):
        calls = []

        def job(case_id, job_type, case_input):
            calls.append(case_id)
            if case_id.endswith('01-tears-closeup'):
                raise RuntimeError('model server gone')
            return reference(case_id)
        report = ce.run([CASES['beats-01-tears-closeup'], CASES['beats-02-scream-variant-tag']], job)
        first, second = report['types']['beats']['results']
        self.assertFalse(first['hard_ok'])
        self.assertIn('model server gone', first['hard'][0]['detail'])
        self.assertEqual(second['score'], 1.0)
        self.assertEqual(len(calls), 2)

    def test_a_callable_named_on_the_command_line_is_the_job(self):
        module = types.ModuleType('crew_eval_stub_adapter')
        module.job = lambda case_id, job_type, case_input: reference(case_id)
        sys.modules['crew_eval_stub_adapter'] = module
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(ce.main(['--job', 'crew_eval_stub_adapter:job', '--type', 'continuity', '--fail-under', '100']), 0)
        finally:
            del sys.modules['crew_eval_stub_adapter']
        with self.assertRaises(SystemExit):
            ce.import_job('no_colon_here')

    def test_naive_outputs_do_not_pass(self):
        """The set separates a real job from a lazy one: a one-beat sheet, a camera-only plan and 'all clear' answers."""
        def one_beat(case_id):
            case = CASES[case_id]
            return {'setup': case['input']['shot']['text'], 'beats': [{'from': 0, 'to': case['input']['shot']['seconds'], 'camera': 'static', 'action': case['input']['shot']['text']}],
                    'sound': '', 'constraints': []}

        def camera_only(case_id):
            case = CASES[case_id]
            return {'shotId': case['input']['shot']['id'], 'baseRevision': case['input']['base_revision'],
                    'ops': [{'op': 'camera', 'size': 'medium', 'angle': 'eye', 'lens': 35, 'move': 'pushin', 'from': 'K1', 'to': 'K2'}]}
        beats, blocking, continuity = ([c for c in CASES if c.startswith(name)] for name in ce.TYPES)
        self.assertEqual({c: failed(c, one_beat(c))[0]['hard_ok'] for c in beats}, {c: False for c in beats})
        self.assertEqual({c: failed(c, camera_only(c))[0]['hard_ok'] for c in blocking}, {c: False for c in blocking})
        all_clear = {'score': 100, 'findings': []}
        self.assertEqual({c for c in continuity if failed(c, all_clear)[0]['hard_ok']}, {'continuity-07-clean-match-cut'})

    def test_flagging_everything_is_not_a_continuity_strategy(self):
        for case_id in (c for c in CASES if c.startswith('continuity')):
            case = CASES[case_id]
            ids = [shot['id'] for shot in case['input']['shots']]
            findings = [{'kind': kind, 'shots': ids[:2], 'subject': 'scene', 'severity': 'major', 'detail': 'differs'} for kind in ce.KINDS]
            result, bad = failed(case_id, {'score': 10, 'findings': findings})
            self.assertEqual(result['score'], 0.0, case_id)
            self.assertIn('no_invented', bad, case_id)

    def test_text_output_is_parsed_as_json(self):
        result, bad = failed('beats-01-tears-closeup', json.dumps(reference('beats-01-tears-closeup')))
        self.assertEqual((bad, result['score']), (set(), 1.0))
        result, bad = failed('beats-01-tears-closeup', 'Here is the beat sheet: {}')
        self.assertEqual(bad, {'output'})
        self.assertEqual(result['score'], 0.0)


class HelperTests(unittest.TestCase):
    def test_tags(self):
        self.assertEqual(ce.tags_in('Mira @CAST-02:coat at @SET-01, then @S23.end. @PROP-01.'), {'@CAST-02:coat', '@SET-01', '@S23.end', '@PROP-01'})
        self.assertEqual(ce.tags_in('mail me at nobody'), set())

    def test_camera_brands_are_caught_and_colours_are_not(self):
        for text in ('shot on ARRI Alexa 65', 'a RED V-Raptor look', 'Sony Venice 2', 'Panavision anamorphic', 'on a Steadicam', 'Cooke lenses'):
            self.assertTrue(ce.BRAND.search(text), text)
        for text in ('a red velvet curtain', 'his red-rimmed eyes', 'the lens flares', 'a venice-blue sky', '35mm anamorphic look'):
            self.assertFalse(ce.BRAND.search(text), text)

    def test_moves_are_read_from_camera_words(self):
        self.assertEqual(ce.detected_moves('the slow dolly push-in begins'), {'pushin'})
        self.assertEqual(ce.detected_moves('locked-off close-up'), {'static'})
        self.assertIn('pullout', ce.detected_moves('the pull-out reveals the room'))
        self.assertIn('orbit', ce.detected_moves('the camera arcs across the console'))
        self.assertEqual(ce.detected_moves('handheld, jittery'), set())

    def test_quotes_compare_after_normalising_punctuation_and_space(self):
        self.assertEqual(ce._norm('You knew  the\nlamp ’s dark “'), 'you knew the lamp \'s dark "')


class ValidatorTests(unittest.TestCase):
    """Helpers: take a case's reference answer, break it one way, and see which hard checks object."""

    def broken(self, case_id, change):
        output = reference(case_id)
        change(output)
        return failed(case_id, output)

    def only(self, expected, result_and_failed):
        """Exactly this hard check objects (the checks a bad shape leaves unevaluated do not count as objecting)."""
        result, _ = result_and_failed
        bad = {h['id'] for h in result['hard'] if not h['ok'] and not h['detail'].startswith('not evaluated')}
        self.assertEqual(bad, {expected}, [h for h in result['hard'] if not h['ok']])
        self.assertFalse(result['hard_ok'])
        self.assertEqual(result['score'], 0.0)
        return result


class BeatsValidatorTests(ValidatorTests):
    TEARS = 'beats-01-tears-closeup'

    def test_shape(self):
        for change in (lambda o: o.pop('sound'), lambda o: o.update(notes='x'), lambda o: o.update(beats=[]), lambda o: o.update(constraints='No text'),
                       lambda o: o['beats'][0].pop('camera'), lambda o: o['beats'][0].update(**{'from': '0'}), lambda o: o['beats'][1].update(action=' ')):
            self.only('schema', self.broken(self.TEARS, change))
        self.only('schema', failed(self.TEARS, ['not', 'an', 'object']))

    def test_a_failed_shape_marks_every_other_check_unevaluated(self):
        result, bad = self.broken(self.TEARS, lambda o: o.pop('sound'))
        self.assertEqual(len(result['hard']), 1 + len(ce.BEATS_AFTER_SCHEMA))
        self.assertEqual(bad, {item['id'] for item in result['hard']})
        self.assertEqual(result['soft'], [])

    def test_beat_sheet_starts_at_zero(self):
        self.only('starts_at_zero', self.broken(self.TEARS, lambda o: o['beats'][0].update(**{'from': 0.4})))

    def test_beat_sheet_is_contiguous(self):
        self.only('contiguous', self.broken(self.TEARS, lambda o: o['beats'][1].update(**{'from': 2.2})))   # a gap
        self.only('contiguous', self.broken(self.TEARS, lambda o: o['beats'][1].update(**{'from': 1.2})))   # an overlap
        result, bad = self.broken(self.TEARS, lambda o: o['beats'][1].update(to=1.8, **{'from': 1.8}))     # a beat with no duration
        self.assertEqual(bad, {'contiguous', 'beat_length'})

    def test_beat_sheet_ends_at_the_shot_duration(self):
        self.only('ends_at_duration', self.broken(self.TEARS, lambda o: o['beats'][-1].update(to=5.5)))
        self.only('ends_at_duration', self.broken(self.TEARS, lambda o: o['beats'][-1].update(to=7)))

    def test_a_beat_must_be_long_enough(self):
        def squeeze(output):
            output['beats'][1]['to'] = 2.1
            output['beats'][2]['from'] = 2.1
        self.only('beat_length', self.broken(self.TEARS, squeeze))

    def test_beat_count_is_per_case(self):
        def merge(output):
            output['beats'][1]['to'] = 6
            del output['beats'][2]
        self.only('beat_count', self.broken(self.TEARS, merge))

        def explode(output):
            output['beats'] = [{'from': i * 1.2, 'to': (i + 1) * 1.2, 'camera': 'close-up', 'action': 'his face crumples'} for i in range(5)]
            output['beats'][-1]['to'] = 6
        self.only('beat_count', self.broken(self.TEARS, explode))

    def test_every_original_tag_must_be_kept(self):
        def drop(output):
            output['setup'] = output['setup'].replace('@SET-01', 'the observatory')
        self.only('tags_kept', self.broken(self.TEARS, drop))
        # a variant tag is kept whole, and a take reference too
        self.only('tags_kept', self.broken('beats-02-scream-variant-tag', lambda o: o.update(setup=o['setup'].replace('@CAST-02:coat', '@CAST-02'))))
        self.only('tags_kept', self.broken('beats-07-stairwell-panic-4s', lambda o: o.update(setup=o['setup'].replace('@S23.end', 'the last shot'))))
        # a tag in the sound line still counts as kept
        result, bad = self.broken(self.TEARS, lambda o: o.update(setup=o['setup'].replace('@SET-01', 'the observatory'), sound=o['sound'] + ' (@SET-01)'))
        self.assertNotIn('tags_kept', bad)

    def test_an_invented_tag_fails(self):
        self.only('no_unknown_tags', self.broken(self.TEARS, lambda o: o.update(setup=o['setup'] + ' @CAST-09 watches.')))

    def test_camera_brands_fail(self):
        for brand in ('shot on an ARRI Alexa 65', 'RED V-Raptor look', 'Panavision glass', 'Sony Venice colour'):
            self.only('no_camera_brands', self.broken(self.TEARS, lambda o, b=brand: o['beats'][0].update(camera=o['beats'][0]['camera'] + ', ' + b)))

    def test_lenses_must_be_on_the_stage(self):
        for lens in ('28mm', '135 mm', '16mm'):
            self.only('lens_in_lenses', self.broken(self.TEARS, lambda o, n=lens: o.update(setup=o['setup'] + f' A {n} lens.')))
        result, bad = self.broken(self.TEARS, lambda o: o.update(setup=o['setup'] + ' Also a 24mm and an 85 mm look.'))
        self.assertNotIn('lens_in_lenses', bad)

    def test_a_good_but_loose_sheet_loses_soft_marks_not_the_case(self):
        def loosen(output):
            output['sound'] = ''
            output['constraints'] = ['No text']
        result, bad = self.broken(self.TEARS, loosen)
        self.assertEqual(bad, set())
        lost = {s['id'] for s in result['soft'] if s['value'] < 1}
        self.assertEqual(lost, {'one_person', 'sound_breath'})
        self.assertTrue(0.8 < result['score'] < 1)

    def test_soft_checks_read_the_right_things(self):
        def backwards(output):
            for beat in output['beats']:
                beat['action'] = beat['action'].replace('Facing the camera, ', '').replace('still turned toward the camera', 'still looking down').replace('into the lens', 'down')
            output['setup'] = 'One continuous 6-second shot in @SET-01. @CAST-01 is seen from behind, silhouetted against the glass.'
            for beat in output['beats']:
                beat['camera'] = 'locked-off'
        result, bad = self.broken(self.TEARS, backwards)
        self.assertEqual(bad, set())
        lost = {s['id'] for s in result['soft'] if s['value'] < 1}
        self.assertTrue({'face_to_camera', 'no_back_views', 'push_in'} <= lost, lost)

    def test_the_spoken_line_is_checked_word_for_word(self):
        def paraphrase(output):
            output['beats'][1]['action'] = output['beats'][1]['action'].replace('You knew the lamp was dark, and you let him sail.', 'You lied about the lamp.')
        result, bad = self.broken('beats-04-accusation-dialogue', paraphrase)
        self.assertEqual(bad, set())
        self.assertEqual({s['id'] for s in result['soft'] if s['value'] < 1}, {'line_kept'})

    def test_ordered_arcs_give_partial_credit_in_order(self):
        def reverse(output):
            first, last = output['beats'][0]['action'], output['beats'][2]['action']
            output['beats'][0]['action'], output['beats'][2]['action'] = last, first
        result, bad = self.broken(self.TEARS, reverse)
        arc = next(s for s in result['soft'] if s['id'] == 'emotion_arc')
        self.assertLess(arc['value'], 1)
        self.assertGreater(arc['value'], 0)


class BlockingValidatorTests(ValidatorTests):
    PAIR = 'blocking-02-nose-to-nose'
    TRIO = 'blocking-06-triangle-argument'
    RETIME = 'blocking-03-shove-after-standoff'
    EMPTY = 'blocking-05-empty-stage-scream'

    def op(self, output, name, index=0):
        return [o for o in output['ops'] if o['op'] == name][index]

    def test_shape(self):
        for change in (lambda o: o.pop('ops'), lambda o: o.update(extra=1), lambda o: o.update(ops=[]), lambda o: o.update(ops={'op': 'place'}),
                       lambda o: o.update(ops=[1, 2]), lambda o: o.update(ops=o['ops'] * 20)):
            self.only('schema', self.broken(self.PAIR, change))
        self.only('schema', failed(self.PAIR, 'null'))

    def test_a_failed_shape_marks_every_other_check_unevaluated(self):
        result, bad = self.broken(self.PAIR, lambda o: o.pop('ops'))
        self.assertEqual(len(result['hard']), 1 + len(ce.BLOCKING_AFTER_SCHEMA))
        self.assertEqual(bad, {item['id'] for item in result['hard']})

    def test_the_job_echoes_the_shot_and_the_revision_it_was_given(self):
        self.only('shot_id', self.broken(self.PAIR, lambda o: o.update(shotId='S99')))
        self.only('base_revision', self.broken(self.PAIR, lambda o: o.update(baseRevision=8)))
        self.only('base_revision', self.broken(self.PAIR, lambda o: o.update(baseRevision='7')))
        self.only('base_revision', self.broken(self.PAIR, lambda o: o.update(baseRevision=True)))

    def test_ops_follow_the_schema(self):
        changes = [
            lambda o: o['ops'].append({'op': 'teleport', 'cast': '@CAST-01'}),
            lambda o: self.op(o, 'place').pop('facing'),
            lambda o: self.op(o, 'place').update(speed=2),
            lambda o: self.op(o, 'place').update(offset=[0.1]),
            lambda o: self.op(o, 'place').update(offset=[0.1, 99]),
            lambda o: self.op(o, 'place').update(offset=['a', 'b']),
            lambda o: self.op(o, 'camera').update(size='huge'),
            lambda o: self.op(o, 'camera').update(angle='sideways'),
            lambda o: self.op(o, 'camera').pop('size'),
            lambda o: self.op(o, 'camera').update(**{'from': 'start'}),
        ]
        for change in changes:
            self.only('op_schema', self.broken(self.PAIR, change))
        # a cast field that is not a code names nobody, and leaves the real cast member unplaced
        result, bad = self.broken(self.PAIR, lambda o: self.op(o, 'place').update(cast='Kael'))
        self.assertEqual(bad, {'op_schema', 'cast_known', 'cast_placed'})

    def test_camera_lens_is_on_the_stage(self):
        for lens in (28, 135, '35', None, 35.5):
            result, bad = self.broken(self.PAIR, lambda o, v=lens: self.op(o, 'camera').update(lens=v))
            self.assertEqual(bad, {'camera_lens'}, lens)
        result, bad = self.broken(self.PAIR, lambda o: self.op(o, 'camera').update(lens=35.0))
        self.assertEqual(bad, set())

    def test_camera_move_is_on_the_stage(self):
        for move in ('zoom', 'handheld', 'PUSHIN', None):
            self.only('camera_move', self.broken(self.PAIR, lambda o, v=move: self.op(o, 'camera').update(move=v)))

    def test_a_moving_camera_needs_two_keys_and_a_static_one_needs_at_most_one(self):
        self.only('camera_keys', self.broken(self.PAIR, lambda o: self.op(o, 'camera').pop('to')))
        self.only('camera_keys', self.broken(self.PAIR, lambda o: self.op(o, 'camera').update(to='K1')))
        self.only('camera_keys', self.broken(self.PAIR, lambda o: self.op(o, 'camera').update(move='static')))   # K1 to K2 on a locked camera
        for dropped in (('from', 'to'), ('to',)):    # a static camera has no key, or one
            def lock(output, dropped=dropped):
                camera = self.op(output, 'camera')
                camera['move'] = 'static'
                for key in dropped:
                    camera.pop(key)
            result, bad = self.broken(self.PAIR, lock)
            self.assertEqual(bad, set())

    def test_a_shot_has_exactly_one_camera(self):
        self.only('camera_single', self.broken(self.PAIR, lambda o: o['ops'].append(copy.deepcopy(self.op(o, 'camera')))))
        self.only('camera_single', self.broken(self.PAIR, lambda o: o.update(ops=[x for x in o['ops'] if x['op'] != 'camera'])))

    def test_cast_codes_must_belong_to_the_shot_and_be_placed_once(self):
        self.only('cast_known', self.broken(self.TRIO, lambda o: o['ops'].append(
            {'op': 'place', 'cast': '@CAST-03', 'relativeTo': 'console', 'offset': [0, -1], 'facing': 'camera'})))
        self.only('cast_placed', self.broken(self.TRIO, lambda o: o.update(ops=[x for x in o['ops'] if x.get('cast') != '@CAST-02'])))
        self.only('cast_placed', self.broken(self.TRIO, lambda o: o['ops'].append(copy.deepcopy(self.op(o, 'place')))))
        # the invented code is also a place for a cast member that was never in the shot: both are reported when it replaces a real one
        result, bad = self.broken(self.TRIO, lambda o: self.op(o, 'place', 1).update(cast='@CAST-03'))
        self.assertEqual(bad, {'cast_known', 'cast_placed'})

    def test_places_point_only_at_the_stage_the_job_was_given(self):
        self.only('targets_known', self.broken(self.PAIR, lambda o: self.op(o, 'place').update(relativeTo='door')))
        self.only('targets_known', self.broken(self.PAIR, lambda o: self.op(o, 'place', 1).update(facing='@CAST-77')))
        self.only('targets_known', self.broken(self.PAIR, lambda o: self.op(o, 'place').update(relativeTo='@CAST-01')))   # relative to himself
        self.only('targets_known', self.broken(self.PAIR, lambda o: self.op(o, 'place', 1).update(relativeTo='far')))     # a parallax card on the observatory
        self.only('targets_known', self.broken(self.EMPTY, lambda o: self.op(o, 'place').update(relativeTo='console')))   # the empty stage has none
        self.only('targets_known', self.broken(self.EMPTY, lambda o: self.op(o, 'place').update(facing='window_glass')))
        result, bad = self.broken('blocking-07-plinth-fear-handheld', lambda o: self.op(o, 'place').update(facing='window'))  # the 4.6 shorthand
        self.assertNotIn('targets_known', bad)
        self.assertEqual(next(s for s in result['soft'] if s['id'] == 'ines_faces_lens')['value'], 0.75)  # facing the glass loses the point

    def test_retime_must_name_a_beat_and_a_fraction(self):
        self.only('retime_valid', self.broken(self.RETIME, lambda o: self.op(o, 'retime').update(at=1.4)))
        self.only('retime_valid', self.broken(self.RETIME, lambda o: self.op(o, 'retime').update(at=-0.1)))
        self.only('retime_valid', self.broken(self.RETIME, lambda o: self.op(o, 'retime').update(beat=4)))   # the shot has three beats
        self.only('op_schema', self.broken(self.RETIME, lambda o: self.op(o, 'retime').update(beat=0)))
        self.only('op_schema', self.broken(self.RETIME, lambda o: self.op(o, 'retime').update(beat='2')))

    def test_a_requested_retime_is_required(self):
        self.only('required_ops', self.broken(self.RETIME, lambda o: o.update(ops=[x for x in o['ops'] if x['op'] != 'retime'])))

    def test_soft_criteria_score_staging_and_timing(self):
        # Mira facing the lens instead of Kael, the pair 3 m apart, the shove left at beat 2's old time
        def stage(output):
            self.op(output, 'place', 1).update(facing='camera', offset=[0, -3.0])
            self.op(output, 'retime').update(at=0.3)
        result, bad = self.broken(self.RETIME, stage)
        self.assertEqual(bad, set())
        lost = {s['id'] for s in result['soft'] if s['value'] < 1}
        self.assertEqual(lost, {'shove_starts_at_60_percent', 'mira_faces_kael', 'squaring_up'})

    def test_distance_needs_the_ops_to_say_how_far(self):
        def unrelated(output):   # Mira placed relative to the plinth: the gap to Kael is not stated
            self.op(output, 'place', 1).update(relativeTo='plinth')
        result, bad = self.broken(self.PAIR, unrelated)
        self.assertEqual(bad, set())
        self.assertEqual(next(s for s in result['soft'] if s['id'] == 'nose_to_nose')['value'], 0)

    def test_a_malformed_op_scores_nothing_in_the_soft_part(self):
        result, bad = self.broken(self.PAIR, lambda o: self.op(o, 'camera').update(lens=28))
        self.assertEqual(bad, {'camera_lens'})
        self.assertEqual(next(s for s in result['soft'] if s['id'] == 'two_shot_framing')['value'], 0)


class ContinuityValidatorTests(ValidatorTests):
    ZIP = 'continuity-01-tears-and-zipper'
    JUMP = 'continuity-06-two-hours-later-dye-job'
    CLEAN = 'continuity-07-clean-match-cut'
    STRESS = 'continuity-08-torn-photograph-three-shots'
    DAY = 'continuity-04-night-becomes-daylight'

    def finding(self, kind, shots, subject, severity='minor', detail='something differs'):
        return {'kind': kind, 'shots': shots, 'subject': subject, 'severity': severity, 'detail': detail}

    def test_shape(self):
        for change in (lambda o: o.pop('score'), lambda o: o.update(score=101), lambda o: o.update(score=-1), lambda o: o.update(score=55.5),
                       lambda o: o.update(findings={}), lambda o: o.update(findings=[{}]), lambda o: o.update(notes='x'),
                       lambda o: o['findings'][0].update(kind='color'), lambda o: o['findings'][0].update(severity='critical'),
                       lambda o: o['findings'][0].update(subject='@CAST-77'), lambda o: o['findings'][0].update(shots=['S99']),
                       lambda o: o['findings'][0].update(shots=[]), lambda o: o['findings'][0].update(detail=''), lambda o: o['findings'][0].update(extra=1),
                       lambda o: o.update(findings=o['findings'] * 11)):
            self.only('schema', self.broken(self.ZIP, change))

    def test_a_failed_shape_marks_the_other_checks_unevaluated(self):
        result, bad = self.broken(self.ZIP, lambda o: o.pop('score'))
        self.assertEqual(bad, {item['id'] for item in result['hard']})
        self.assertEqual(len(result['hard']), 1 + len(ce.CONTINUITY_AFTER_SCHEMA))

    def test_a_missed_critical_error_fails_the_case(self):
        result = self.only('critical_found', self.broken(self.ZIP, lambda o: o['findings'].pop(0)))
        self.assertIn('E1', next(h for h in result['hard'] if h['id'] == 'critical_found')['detail'])
        self.only('critical_found', self.broken(self.ZIP, lambda o: o.update(findings=[])))
        # the right kind on the wrong seam does not count, and is itself an invented finding
        result, bad = self.broken(self.STRESS, lambda o: o['findings'][0].update(shots=['S29', 'S30']))
        self.assertEqual(bad, {'critical_found', 'no_invented'})

    def test_a_missed_minor_error_costs_soft_marks_only(self):
        result, bad = self.broken(self.ZIP, lambda o: o['findings'].pop(1))
        self.assertEqual(bad, set())
        self.assertEqual({s['id'] for s in result['soft'] if s['value'] < 1}, {'planted:E2'})
        self.assertTrue(0.5 < result['score'] < 1)

    def test_an_invented_finding_fails_the_case(self):
        invented = lambda o: o['findings'].append(self.finding('gaze', ['S08', 'S09'], '@CAST-01'))
        result = self.only('no_invented', self.broken(self.ZIP, invented))
        self.assertIn('matches no planted error', next(h for h in result['hard'] if h['id'] == 'no_invented')['detail'])
        self.only('no_invented', self.broken(self.CLEAN, lambda o: o['findings'].append(self.finding('prop', ['S23', 'S24'], '@PROP-03', 'major'))))

    def test_flagging_a_justified_change_is_a_false_alarm(self):
        for kind, subject, why in (('lighting', '@SET-01', 'time jump'), ('wardrobe', '@CAST-02', 'draped over the chair'), ('body_state', '@CAST-02', 'tears have dried')):
            result = self.only('no_invented', self.broken(self.JUMP, lambda o, k=kind, s=subject: o['findings'].append(self.finding(k, ['S21', 'S22'], s, 'major'))))
            detail = next(h for h in result['hard'] if h['id'] == 'no_invented')['detail']
            self.assertIn('justified', detail)
            self.assertIn(why, detail)

    def test_a_clean_seam_must_be_reported_clean(self):
        result, bad = failed(self.CLEAN, {'score': 96, 'findings': []})
        self.assertEqual((bad, result['score']), (set(), 1.0))
        result, bad = failed(self.CLEAN, {'score': 50, 'findings': []})
        self.assertEqual((bad, result['score']), (set(), 0.0))   # right findings, wrong score band
        self.assertEqual(result['soft_score'], 0.0)

    def test_tolerated_findings_and_duplicates_are_neutral(self):
        result, bad = self.broken(self.STRESS, lambda o: o['findings'].append(self.finding('position', ['S28', 'S29'], '@CAST-02')))
        self.assertEqual((bad, result['score']), (set(), 1.0))
        result, bad = self.broken(self.ZIP, lambda o: o['findings'].append(copy.deepcopy(o['findings'][0])))
        self.assertEqual((bad, result['score']), (set(), 1.0))

    def test_a_finding_may_name_more_shots_than_the_error_needs(self):
        result, bad = self.broken(self.ZIP, lambda o: o['findings'][0].update(shots=['S09', 'S08']))
        self.assertEqual((bad, result['score']), (set(), 1.0))

    def test_the_set_and_scene_stand_for_each_other(self):
        result, bad = self.broken(self.DAY, lambda o: o['findings'][0].update(subject='scene'))
        self.assertEqual((bad, result['score']), (set(), 1.0))
        result, bad = self.broken(self.STRESS, lambda o: o['findings'][2].update(subject='scene'))   # E3 accepts either actor or the scene
        self.assertEqual((bad, result['score']), (set(), 1.0))
        result, bad = self.broken(self.DAY, lambda o: o['findings'][0].update(subject='@CAST-03'))   # a person is not the set
        self.assertEqual(bad, {'critical_found', 'no_invented'})

    def test_severity_and_evidence_shade_the_soft_score(self):
        result, bad = self.broken(self.ZIP, lambda o: o['findings'][0].update(severity='minor'))
        self.assertEqual(bad, set())
        self.assertAlmostEqual(next(s for s in result['soft'] if s['id'] == 'planted:E1')['value'], 0.8)
        result, bad = self.broken(self.ZIP, lambda o: o['findings'][0].update(detail='Something is different here.'))
        self.assertAlmostEqual(next(s for s in result['soft'] if s['id'] == 'planted:E1')['value'], 0.8)
        result, bad = self.broken(self.ZIP, lambda o: o['findings'][0].update(severity='minor', detail='Something is different here.'))
        self.assertAlmostEqual(next(s for s in result['soft'] if s['id'] == 'planted:E1')['value'], 0.6)

    def test_the_score_band_is_graded(self):
        result, bad = self.broken(self.ZIP, lambda o: o.update(score=92))
        self.assertEqual(bad, set())
        self.assertEqual(next(s for s in result['soft'] if s['id'] == 'score_band')['value'], 0.0)


if __name__ == '__main__':
    unittest.main()
