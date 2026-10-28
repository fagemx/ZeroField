"""SPEC_20 R21, R22, R23 (fixed decision 12): crew jobs beyond one shot. Art's appearance descriptions and looks, who is
in each shot, the Screenwriter's adaptation and breakdown candidates, the general job target, the proposal tools and
the proposal-only grant top-up.

The pure tests need nothing. The rest run the real story server on PostgreSQL (OPENBENCH_TEST_DB_URI) with each job
executed inline on a fake OpenAI-compatible opener: no test reaches a model, Ollama or a GPU, and the socket guard of
test_crew_jobs refuses port 11434 here too.
"""
import json
import os
import re
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from project_assistant import crew_art as art, crew_jobs, crew_planning, crew_readiness, crew_writing as writing, tool_registry
import test_crew_jobs as crew_fixture
from test_crew_jobs import FakeEndpoint

SCRIPT = ('## Scene 01: Observatory\nCharacter: Kael @CAST-01\nCharacter: Mira @CAST-02\nEnvironment: @SET-01\n\n'
          'Kael enters the observatory. Rain runs down the glass.\n\nHe reaches for the brass dial.\n\n'
          'Insert: a hand turns the dial. @CAST-01\n\nMira watches from the door.\n\n## Scene 02: Departure\nKael leaves.')


def setUpModule():
    crew_fixture.setUpModule()


def tearDownModule():
    crew_fixture.tearDownModule()


ASSET = {'code': 'CAST-01', 'name': 'Kael', 'type': 'CHARACTER', 'isLook': False,
         'description': 'original fictional courier, charcoal field jacket, analog recorder; seed 48291'}


class DescriptionContractTests(unittest.TestCase):
    def test_composition_words_tags_seeds_and_brands_are_refused(self):
        good = 'Kael, a lean courier in his thirties with short dark hair, a charcoal field jacket and a brass analog recorder.'
        self.assertEqual(art.appearance_problems(good, 'Kael'), [])
        for text, pattern in (('Kael, waist-up portrait of a courier, grey backdrop', r'waist-up, portrait, grey backdrop'),
                              ('An empty observatory, wide shot, no people, cinematic', r'wide shot, no people, cinematic'),
                              ('A courier at eye level, 85mm lens, shallow focus', r'eye level, 85mm, lens, shallow focus'),
                              ('Kael in a field jacket, studio lighting, rim light, 8k', r'studio lighting, rim light, 8k'),
                              ('A courier in a jacket, seed 48291', r'seed')):
            with self.subTest(text=text):
                self.assertRegex(' '.join(art.appearance_problems(text, 'Kael')), 'composition or rendering words: ' + pattern)
        self.assertRegex(' '.join(art.appearance_problems('Kael in a jacket with @CAST-02 beside him', 'Kael')), r'@ tag')
        self.assertRegex(' '.join(art.appearance_problems('A courier holding a recorder, 48291', 'Kael')), r'seed-like number \(48291\)')
        self.assertRegex(' '.join(art.appearance_problems('A courier with an ARRI Alexa slung over a shoulder', 'Kael')), r'brand\(s\) ARRI, Alexa')
        self.assertRegex(' '.join(art.appearance_problems('Kael', 'Kael')), r'too short')
        self.assertEqual(art.appearance_problems('A battered brass camera with a dented body.', 'Brass Camera'), [],
                         "a word of the asset's own name is allowed")
        self.assertEqual(art.composition_words('A battered brass camera with a dented body.', 'Kael'), ['camera'])

    def test_the_rule_fallback_keeps_appearance_clauses_only(self):
        fallback = art.description_fallback({'asset': ASSET})
        self.assertEqual(fallback['description'], 'Kael, original fictional courier, charcoal field jacket, analog recorder.')
        self.assertEqual(art.validate_description(fallback, {'asset': ASSET}), [])
        extracted = {**ASSET, 'description': 'Kael, tall courier, cinematic character portrait, consistent facial structure, neutral studio rim lighting'}
        self.assertEqual(art.description_fallback({'asset': extracted})['description'], 'Kael, tall courier, consistent facial structure.')
        plate = {'code': 'SET-01', 'name': 'Observatory', 'type': 'SCENE', 'isLook': False,
                 'description': 'Reference for @SET-01 — Observatory, rain on glass, wide cinematic environment plate, clear foreground/midground/background depth layers, no characters'}
        self.assertEqual(art.description_fallback({'asset': plate})['description'], 'Observatory, rain on glass.')
        empty = {'code': 'PROP-01', 'name': 'PROP-01', 'type': 'PROP', 'isLook': False, 'description': 'Reference for @PROP-01'}
        result = art.description_fallback({'asset': empty, 'traits': ''})
        self.assertEqual(result['description'], 'an original object with a consistent shape, material and colour.')
        self.assertEqual(art.validate_description(result, {'asset': empty}), [])
        traits = art.description_fallback({'asset': empty | {'name': 'Brass Dial'}, 'traits': 'palm-sized, green verdigris, seed 7'})
        self.assertEqual(traits['description'], 'Brass Dial, palm-sized, green verdigris.')

    def test_answers_are_retried_with_the_errors_then_fall_back(self):
        bad = {'description': 'Kael, waist-up portrait, grey backdrop.', 'reason': 'x'}
        call = crew_fixture.calls(bad, bad)
        outcome = crew_jobs.run_pipeline(art.DESCRIPTION, {'asset': ASSET}, call)
        self.assertEqual(outcome.source, 'rule_fallback')
        self.assertIn('waist-up, portrait, grey backdrop', call.sent[1]['text'])
        self.assertEqual(outcome.output, art.description_fallback({'asset': ASSET}))


class LookContractTests(unittest.TestCase):
    INPUT = {'asset': ASSET, 'looks': [{'key': 'night', 'name': 'Kael - night'}], 'wanted': ['rain'], 'request': {}}

    def answer(self, **change):
        return {'key': 'rain', 'name': 'Kael - rain', 'kind': 'OUTFIT',
                'description': 'Kael, a lean courier with short dark hair, in a soaked black rain coat over the field jacket.',
                'reason': 'Scene 2 is in the rain.', **change}

    def test_a_look_is_a_new_unused_key_and_differs_from_the_base(self):
        self.assertEqual(art.validate_look(self.answer(), self.INPUT), [])
        errors = lambda **c: ' '.join(art.validate_look(self.answer(**c), self.INPUT))  # noqa: E731
        self.assertRegex(errors(key='night'), r'already a look of CAST-01')
        self.assertRegex(errors(key='Night Coat'), r'lower-case')
        self.assertRegex(errors(kind='COSTUME'), r'OUTFIT, POSE or LOOK')
        self.assertRegex(errors(description=ASSET['description']), r'seed|repeats the base')
        self.assertRegex(errors(description='Kael in a rain coat, full-body shot, white background'), r'composition or rendering words')
        asked = {**self.INPUT, 'request': {'key': 'storm', 'kind': 'POSE'}}
        self.assertRegex(' '.join(art.validate_look(self.answer(), asked)), r'"key" must be storm.*"kind" must be POSE')

    def test_the_rule_fallback_takes_a_free_key_and_the_note(self):
        fallback = art.look_fallback({**self.INPUT, 'request': {'note': 'soaked rain coat'}})
        self.assertEqual((fallback['key'], fallback['kind']), ('rain', 'OUTFIT'), 'the look the script names comes first')
        self.assertIn('in this look: soaked rain coat', fallback['description'])
        self.assertEqual(art.validate_look(fallback, self.INPUT), [])
        taken = {**self.INPUT, 'wanted': [], 'request': {'note': 'night'}}
        self.assertEqual(art.look_fallback(taken)['key'], 'night-2')
        self.assertEqual(art.validate_look(art.look_fallback(taken), taken), [])


SCENE_INPUT = {
    'scene': {'id': 'sc_x_01_S01', 'title': 'Scene 01: Observatory', 'text': ''},
    'characters': [{'code': '@CAST-01', 'name': 'Kael', 'look': ''}, {'code': '@CAST-02', 'name': 'Mira', 'look': ''}],
    'looks': ['@CAST-01:NIGHT'], 'sets': ['@SET-01'],
    'shots': [{'shotId': 's1', 'label': 'SC01-S01', 'text': 'Kael enters the observatory. @SET-01 @CAST-01'},
              {'shotId': 's2', 'label': 'SC01-S02', 'text': 'He reaches for the brass dial. @SET-01'},
              {'shotId': 's3', 'label': 'SC01-S03', 'text': 'Insert: a hand turns the dial. @CAST-01 @SET-01'},
              {'shotId': 's4', 'label': 'SC01-S04', 'text': 'Mira watches from the door. @SET-01 @CAST-02'}]}


class AppearanceContractTests(unittest.TestCase):
    def test_pronouns_resolve_and_inserts_bind_only_the_scene(self):
        fallback = art.appearances_fallback(SCENE_INPUT)
        self.assertEqual([(s['cast'], s['insert']) for s in fallback['shots']],
                         [(['@CAST-01'], False), (['@CAST-01'], False), ([], True), (['@CAST-02'], False)])
        self.assertEqual(art.validate_appearances(fallback, SCENE_INPUT), [])
        one = {**SCENE_INPUT, 'shots': SCENE_INPUT['shots'][1:2], 'earlier': [SCENE_INPUT['shots'][0]['text']]}
        self.assertEqual(art.appearances_fallback(one)['shots'][0]['cast'], ['@CAST-01'], 'one shot reads who was named before it')
        alone = {**one, 'earlier': []}
        self.assertEqual(art.appearances_fallback(alone)['shots'][0]['cast'], [], 'two people and nobody named: no guess')

    def test_validation_names_each_broken_rule(self):
        good = art.appearances_fallback(SCENE_INPUT)
        def errors(index, **change):
            shots = [dict(s) for s in good['shots']]
            shots[index].update(change)
            return ' '.join(art.validate_appearances({'shots': shots}, SCENE_INPUT))
        self.assertRegex(errors(2, cast=['@CAST-01']), r's3 is an insert: an insert binds only the scene')
        self.assertRegex(errors(0, cast=['@CAST-03']), r'CAST-03 is not a character of this scene')
        self.assertRegex(errors(0, cast=['@CAST-01:rain']), r'not an existing look')
        self.assertEqual(errors(0, cast=['@CAST-01:night']), '', 'an existing look is fine')
        self.assertRegex(errors(0, shotId='s9'), r"'s9' is not one of the shots given")
        self.assertRegex(' '.join(art.validate_appearances({'shots': good['shots'][:3]}, SCENE_INPUT)), r'Missing shot\(s\): s4')
        self.assertRegex(errors(1, insert='no'), r'"insert" must be true or false')

    def test_rebinding_keeps_the_words_and_the_set_tag(self):
        self.assertEqual(art.rebind('He reaches for the brass dial. @SET-01', ['@CAST-01'], False, ['@SET-01']),
                         'He reaches for the brass dial. @SET-01 @CAST-01')
        self.assertEqual(art.rebind('Insert: a hand turns the dial. @CAST-01 @SET-01', [], True, ['@SET-01']),
                         'Insert: a hand turns the dial. @SET-01')
        self.assertEqual(art.rebind('@CAST-02 lunges at @CAST-01, who falls.', ['CAST-01'], False, ['@SET-02']),
                         'lunges at @CAST-01, who falls. @SET-02')
        self.assertEqual(art.rebind('@CAST-01 waits.', ['@CAST-01:night'], False, []), '@CAST-01:night waits.')


SOURCE = {'episode': {'id': 'ep_x_01', 'title': 'Episode 1'}, 'mode': 'idea', 'cut': False, 'targetScenes': 2,
          'source': 'A lone courier @CAST-01 finds a brass dial that answers.', 'tags': ['CAST-01'], 'cast': [], 'note': ''}


class AdaptationContractTests(unittest.TestCase):
    def answer(self, **change):
        return {'scenes': [{'title': 'The Signal', 'content': 'Environment: @SET-01\n\n@CAST-01 crosses the wet roof toward the dome.'},
                           {'title': 'The Dial', 'content': '@CAST-01 turns the brass dial; a light answers outside.'}],
                'notes': 'Two beats: arrival and answer.', **change}

    def test_scenes_keep_the_source_tags_and_film_only_what_shows(self):
        self.assertEqual(writing.validate_adaptation(self.answer(), SOURCE), [])
        self.assertTrue(writing.compile_scenes(self.answer()['scenes']).startswith('## Scene 01: The Signal\n\nEnvironment: @SET-01'))
        errors = lambda answer: ' '.join(writing.validate_adaptation(answer, SOURCE))  # noqa: E731
        three = self.answer(scenes=self.answer()['scenes'] + [{'title': 'More', 'content': '@CAST-01 leaves the dome behind.'}])
        self.assertRegex(errors(three), r'1 to 2 scenes')
        heading = self.answer(scenes=[{'title': 'A', 'content': '@CAST-01 waits.\n## Scene 02: B\nMore text here.'}])
        self.assertRegex(errors(heading), r'scene heading inside')
        dropped = self.answer(scenes=[{'title': 'A', 'content': 'A courier finds a dial that answers.'}])
        self.assertRegex(errors(dropped), r'Dropped the source tag\(s\) @CAST-01')
        inner = self.answer(scenes=[{'title': 'A', 'content': '@CAST-01 feels deep inside that the dial is alive.'}])
        self.assertRegex(errors(inner), r'Inner-voice label')

    def test_the_rule_fallback_is_the_storyboard_adaptation_and_validates(self):
        fallback = writing.adaptation_fallback(SOURCE)
        self.assertEqual(writing.validate_adaptation(fallback, SOURCE), [])
        self.assertEqual(fallback['notes'], writing.RULE_NOTE)
        self.assertTrue(fallback['scenes'][0]['content'].startswith('Character:'), 'the declarations lead scene 1')


BREAKDOWN = {'episode': {'id': 'ep_x_01', 'title': ''}, 'mode': 'auto', 'note': '',
             'scenes': [{'sceneId': 'a', 'title': 'A', 'units': ['One.', 'Two.', 'Three.', 'Four.'], 'paragraphs': [[1, 2], [3], [4]]},
                        {'sceneId': 'b', 'title': 'B', 'units': ['Five.'], 'paragraphs': [[1]]}]}


class BreakdownContractTests(unittest.TestCase):
    def answer(self, first=((1, 1), (2, 3), (4, 4))):
        return {'scenes': [{'sceneId': 'a', 'shots': [{'from': a, 'to': b, 'reason': 'cut'} for a, b in first]},
                           {'sceneId': 'b', 'shots': [{'from': 1, 'to': 1, 'reason': 'one'}]}]}

    def test_shots_cover_each_scene_in_order(self):
        self.assertEqual(writing.validate_breakdown(self.answer(), BREAKDOWN), [])
        errors = lambda first: ' '.join(writing.validate_breakdown(self.answer(first), BREAKDOWN))  # noqa: E731
        self.assertRegex(errors(((1, 1), (3, 4))), r'shot 2 starts at sentence 3, not 2: a gap')
        self.assertRegex(errors(((1, 2), (2, 4))), r'an overlap')
        self.assertRegex(errors(((1, 3),)), r'ends at sentence 3; the scene has 4 sentences')
        self.assertRegex(errors(((1, 5),)), r'must end between 1 and 4')
        swapped = {'scenes': list(reversed(self.answer()['scenes']))}
        self.assertRegex(' '.join(writing.validate_breakdown(swapped, BREAKDOWN)), r'in order')

    def test_rules_follow_the_breakdown_mode_and_reblocking_keeps_the_words(self):
        groups = lambda mode: [[(s['from'], s['to']) for s in scene['shots']] for scene in writing.breakdown_fallback({**BREAKDOWN, 'mode': mode})['scenes']]  # noqa: E731
        self.assertEqual(groups('auto'), [[(1, 2), (3, 3), (4, 4)], [(1, 1)]])
        self.assertEqual(groups('scene'), [[(1, 4)], [(1, 1)]])
        self.assertEqual(groups('cinematic'), [[(1, 1), (2, 2), (3, 3), (4, 4)], [(1, 1)]])
        for mode in ('auto', 'scene', 'cinematic'):
            self.assertEqual(writing.validate_breakdown(writing.breakdown_fallback({**BREAKDOWN, 'mode': mode}), BREAKDOWN), [])
        self.assertTrue(writing._same_as_paragraphs(writing.breakdown_fallback(BREAKDOWN), BREAKDOWN))
        scene = {'sceneId': 'a', 'title': 'Scene 01: A', 'content': 'Environment: @SET-01\nOne. Two.\n\nThree.\n\nFour.'}
        units, paragraphs, declarations = writing.scene_units(scene)
        self.assertEqual((units, paragraphs, declarations), (['One.', 'Two.', 'Three.', 'Four.'], [[1, 2], [3], [4]], ['Environment: @SET-01']))
        text = writing.reblocked_script([(scene, units, paragraphs, declarations)], {'scenes': [self.answer()['scenes'][0]]})
        self.assertEqual(text, '## Scene 01: A\n\nEnvironment: @SET-01\n\nOne.\n\nTwo. Three.\n\nFour.')


class TargetTests(unittest.TestCase):
    def test_targets_are_typed_and_a_bare_id_is_a_shot(self):
        self.assertEqual(crew_jobs.target_ref('sh_demo_b1'), {'kind': 'shot', 'id': 'sh_demo_b1'})
        self.assertEqual(crew_jobs.target_ref({'kind': 'scene', 'id': 'sc_demo_01_S01'}), {'kind': 'scene', 'id': 'sc_demo_01_S01'})
        for bad in ({'kind': 'tab', 'id': 'x'}, {'kind': 'shot'}, {'kind': 'shot', 'id': ''}, 7):
            with self.assertRaises(ValueError):
                crew_jobs.target_ref(bad)
        self.assertEqual(crew_jobs.target_of({'shotId': 'sh_old_b1'}), {'kind': 'shot', 'id': 'sh_old_b1'}, 'records from before')
        self.assertEqual({k: crew_jobs.job(k).targets for k in ('beats', 'camera', 'description', 'look', 'appearances', 'adaptation', 'breakdown')},
                         {'beats': ('shot',), 'camera': ('shot',), 'description': ('asset',), 'look': ('asset',),
                          'appearances': ('shot', 'scene'), 'adaptation': ('episode',), 'breakdown': ('episode',)})
        with self.assertRaises(ValueError):
            crew_jobs.declare(crew_jobs.CrewJob(kind='fixture', role='doc_writer', title='x', schema={}, effort='low', gather=None,
                                                instructions=None, prompt=None, validate=None, fallback=None, propose=None,
                                                targets=('tab',)))
        self.assertNotIn('fixture', crew_jobs.JOBS)


# ---------- against the real servers ----------

@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'set OPENBENCH_TEST_DB_URI for crew job tests')
class CrewStoryJobServerTests(unittest.TestCase):
    request = crew_fixture.fixture.StoryHTTPTests.request
    call = crew_fixture.fixture.StoryHTTPTests.call
    ok = crew_fixture.fixture.StoryHTTPTests.ok
    setUp = crew_fixture.CrewJobServerTests.setUp
    tearDown = crew_fixture.CrewJobServerTests.tearDown
    run_job = crew_fixture.CrewJobServerTests.run_job
    proposal = crew_fixture.CrewJobServerTests.proposal
    decide = crew_fixture.CrewJobServerTests.decide
    counted = crew_fixture.CrewJobServerTests.counted

    def prepare(self, script=SCRIPT):
        # These scripts name Kael and Mira: the template's Noa and Ines take those names (the rest of Updraft stays).
        from project_docs import story_openapi as story
        self.conn.rollback()
        for row in story.table_rows(self.conn, self.slug, 'soul-cast'):
            if row['cells'][0] in ('CAST-01', 'CAST-02'):
                kael = row['cells'][0] == 'CAST-01'
                story.mutate_row(self.conn, self.me, self.slug, 'soul-cast', row['rid'],
                                 {1: 'Kael' if kael else 'Mira', 2: ASSET['description'] if kael else ''})
        self.conn.commit()
        self.ok(f"/episodes/{self.ep}/script", "PUT", {"scriptContent": script})
        self.ok(f"/episodes/{self.ep}/asset-extractions", "POST", {})
        self.ok(f"/episodes/{self.ep}/storyboards", "POST", {})
        return [s for s in self.ok(f"/episodes/{self.ep}/shots?limit=100")["items"] if s['tabKey'] == 'cinema-studio' and s.get('sceneId')]

    def ask(self, path, body=None, expect=200):
        code, payload = self.call(path, 'POST', body or {})
        self.assertEqual(code, expect, payload)
        return payload['data'] if expect == 200 else payload

    def asset(self, code):
        return next(a for a in self.ok(f'/episodes/{self.ep}/assets?limit=100')['items'] if a['assetCode'] == code)

    def cell(self, asset_or_shot_id, header):
        from project_docs import story_openapi as story
        self.conn.rollback()
        _, row = story.find_row(self.conn, asset_or_shot_id, 'asset' if asset_or_shot_id.startswith('as_') else 'shot')
        return row['cells'][next(i for i, h in enumerate(row['headers']) if re.search(header, h, re.I))]

    def writing(self, tail, method='GET', body=None):
        headers = {'Idempotency-Key': uuid.uuid4().hex} if method == 'POST' else None
        return self.ok(f'/episodes/{self.ep}/writing/' + tail, method, body, headers)

    def scene_shots(self, index=1):
        return sorted((s for s in self.shots if s['sceneId'].endswith(f'_S{index:02d}')), key=lambda s: s['shotIndex'])

    # ---- the general target keeps shot jobs intact ----
    def test_jobs_are_listed_and_deduplicated_per_target(self):
        kael, shot = self.asset('CAST-01'), self.shots[0]
        first = self.ask(f"/assets/{kael['assetId']}/description-proposals")
        self.assertEqual((first['kind'], first['role'], first['target'], first['targetLabel'], first['shotId']),
                         ('description', 'doc_writer', {'kind': 'asset', 'id': kael['assetId']}, 'CAST-01 Kael', None))
        self.assertEqual(self.ask(f"/assets/{kael['assetId']}/description-proposals")['jobId'], first['jobId'])
        beat = self.ask(f"/shots/{shot['shotId']}/beat-proposals")
        self.assertEqual((beat['shotId'], beat['target'], beat['targetId']), (shot['shotId'], {'kind': 'shot', 'id': shot['shotId']}, shot['shotId']))
        self.assertEqual([j['kind'] for j in self.ok(f"/shots/{shot['shotId']}/crew-jobs")['items']], ['beats'])
        self.assertEqual([j['kind'] for j in self.ok(f"/assets/{kael['assetId']}/crew-jobs")['items']], ['description'])
        board = self.request(f'/projects/api/{self.slug}/orchestration/board?limit=50')[1]
        item = next(i for i in board['working'] if i.get('job_id') == first['jobId'])
        self.assertEqual((item['title'], item['target_kind'], item['shot_id'], item['agent_key']),
                         ('Appearance description · CAST-01 Kael', 'asset', None, 'doc_writer'))
        self.assertEqual(next(i for i in board['working'] if i.get('job_id') == beat['jobId'])['shot_id'], shot['shotId'])
        from project_docs import story_openapi as story
        self.conn.rollback()
        with self.assertRaises(story.StoryError) as refused:
            crew_jobs.request(self.conn, self.me, self.slug, 'beats', {'kind': 'asset', 'id': kael['assetId']}, {})
        self.assertEqual(refused.exception.status, 422)
        self.conn.rollback()
        self.assertEqual(self.ask(f"/assets/{self.asset('SET-01')['assetId']}/look-proposals", expect=422)['code'], 'DRAMA_VALIDATION_FAILED')
        self.assertEqual(self.ask(f"/assets/{kael['assetId']}/description-proposals", {'seconds': 4}, expect=422)['code'], 'DRAMA_VALIDATION_FAILED')
        self.assertEqual(self.ask(f"/assets/as_{self.slug}_bmissing/description-proposals", expect=404)['code'], 'DRAMA_NOT_FOUND')

    def test_without_a_usable_model_every_new_job_answers_409_and_writes_nothing(self):
        kael, scene = self.asset('CAST-01'), self.shots[0]['sceneId']
        self.probe.stop()
        try:
            with patch.object(crew_readiness, '_probe', return_value=('down', None)):
                for path in (f"/assets/{kael['assetId']}/description-proposals", f"/assets/{kael['assetId']}/look-proposals",
                             f"/scenes/{scene}/appearance-proposals", f"/shots/{self.shots[1]['shotId']}/appearance-proposals",
                             f"/episodes/{self.ep}/breakdown-proposals"):
                    crew_readiness.forget()
                    refused = self.ask(path, expect=409)
                    self.assertEqual((refused['code'], refused['details']['agentKey']), (crew_jobs.NOT_READY, 'doc_writer'), path)
        finally:
            self.probe.start()
        self.assertEqual(self.counted("SELECT count(*) FROM projectops.story_record WHERE kind='crew_job' AND project_slug=%s"), 0)
        self.assertEqual(self.counted('SELECT count(*) FROM projectops.assistant_proposal WHERE project_slug=%s'), 0)

    # ---- R21 descriptions ----
    def test_a_description_is_appearance_only_and_writes_only_when_adopted(self):
        kael = self.asset('CAST-01')
        before = self.cell(kael['assetId'], 'appearance')
        self.ask(f"/assets/{kael['assetId']}/description-proposals", {'note': 'He is in his thirties.'})
        good = {'description': 'Kael, a lean courier in his thirties with short dark hair, a charcoal field jacket and a brass analog recorder.',
                'reason': 'Kept the jacket and recorder; added age and hair.'}
        endpoint = FakeEndpoint({'description': 'Kael, waist-up portrait, grey backdrop, charcoal jacket.', 'reason': 'x'}, good)
        status, done = self.run_job(endpoint)
        self.assertEqual((status, done['source'], [a['valid'] for a in done['attempts']]), ('succeeded', 'model', [False, True]), done)
        self.assertIn('waist-up, portrait, grey backdrop', endpoint.requests[1]['messages'][-1]['content'])
        self.assertIn("Director's note: He is in his thirties.", endpoint.requests[0]['messages'][-1]['content'])
        self.assertEqual(endpoint.requests[0]['response_format']['json_schema']['name'], 'crew_description')
        proposal = self.proposal(done['result']['proposalIds'][0])
        [group] = proposal['target']['review']['groups']
        self.assertEqual((proposal['agent_key'], group['row_id'], [c['column'] for c in group['changes']]),
                         ('doc_writer', kael['rowId'], ['Locked Appearance Prompt / Seed']))
        self.assertEqual(proposal['target']['crew']['assetRowId'], kael['rowId'])
        self.assertEqual(self.cell(kael['assetId'], 'appearance'), before, 'a proposal writes nothing')
        code, applied = self.decide(proposal['id'])
        self.assertEqual(code, 200, applied)
        self.assertEqual(self.cell(kael['assetId'], 'appearance'), good['description'])

    def test_composition_words_twice_fall_back_to_the_clean_clauses(self):
        kael = self.asset('CAST-01')
        self.ask(f"/assets/{kael['assetId']}/description-proposals")
        bad = {'description': 'Kael, cinematic character portrait, 85mm lens, neutral backdrop.', 'reason': 'x'}
        status, done = self.run_job(FakeEndpoint(bad, bad))
        self.assertEqual((status, done['source']), ('succeeded', 'rule_fallback'), done)
        self.assertTrue(done['result']['description'].startswith('Kael, original fictional courier'))
        proposal = self.proposal(done['result']['proposalIds'][0])
        self.assertTrue(proposal['content'].startswith(crew_planning.FALLBACK_NOTE))
        board = self.request(f'/projects/api/{self.slug}/orchestration/board?limit=50')[1]
        item = next(i for i in board['done'] if i.get('job_id') == done['jobId'])
        self.assertEqual(item['summary'], f"Rule fallback, not model-written: proposal #{proposal['id']} is waiting on the asset card.")

    # ---- R21 looks ----
    def test_a_look_is_a_proposal_that_adds_a_variant_row(self):
        kael = self.asset('CAST-01')
        self.ask(f"/assets/{kael['assetId']}/look-proposals", {'note': 'soaked rain coat for the night', 'key': 'night', 'kind': 'OUTFIT'})
        answer = {'key': 'night', 'name': 'Kael - night', 'kind': 'OUTFIT',
                  'description': 'Kael, a lean courier with short dark hair, in a soaked black rain coat over the charcoal field jacket.',
                  'reason': 'The second scene is at night in the rain.'}
        status, done = self.run_job(FakeEndpoint(answer))
        self.assertEqual((status, done['source'], done['result']['lookCode']), ('succeeded', 'model', 'CAST-01:night'), done)
        proposal = self.proposal(done['result']['proposalIds'][0])
        [group] = proposal['target']['review']['groups']
        self.assertEqual(proposal['target']['crew']['assetRowId'], kael['rowId'])
        self.assertEqual({c['column']: c['after'] for c in group['changes']},
                         {'Asset ID': 'CAST-01:night', 'Character / Set': 'Kael - night', 'Locked Appearance Prompt / Seed': answer['description'],
                          'Status': 'Queued', 'Notes': 'OUTFIT'})
        self.assertFalse(self.ok(f"/assets/{kael['assetId']}")['variants'], 'nothing is added until adopted')
        code, applied = self.decide(proposal['id'])
        self.assertEqual(code, 200, applied)
        [look] = self.ok(f"/assets/{kael['assetId']}")['variants']
        self.assertEqual((look['assetCode'], look['kind'], look['prompt']), ('CAST-01:NIGHT', 'OUTFIT', answer['description']))
        self.ask(f"/assets/{kael['assetId']}/look-proposals", {'key': 'night'})
        status, done = self.run_job(FakeEndpoint(answer, answer))
        self.assertEqual(status, 'failed', 'the asked key is taken now: even the rule look is not usable')
        self.assertIn('already a look of CAST-01', done['error'])

    # ---- R22 appearances ----
    def test_a_scene_resolves_pronouns_and_inserts_bind_only_the_scene(self):
        # setUp built the storyboard of SCRIPT (self.shots)
        first, second, insert, fourth = self.scene_shots(1)
        self.assertEqual(insert['description'], 'Insert: a hand turns the dial. @CAST-01 @SET-01')
        self.ask(f"/scenes/{first['sceneId']}/appearance-proposals")
        wrong = {'shots': [{'shotId': s['shotId'], 'cast': ['@CAST-01'], 'insert': s is insert, 'reason': 'x'} for s in (first, second, insert, fourth)]}
        right = {'shots': [{'shotId': first['shotId'], 'cast': ['@CAST-01'], 'insert': False, 'reason': 'Kael enters.'},
                           {'shotId': second['shotId'], 'cast': ['@CAST-01'], 'insert': False, 'reason': '"He" is Kael.'},
                           {'shotId': insert['shotId'], 'cast': [], 'insert': True, 'reason': 'A hand on the dial.'},
                           {'shotId': fourth['shotId'], 'cast': ['@CAST-02'], 'insert': False, 'reason': 'Mira watches.'}]}
        endpoint = FakeEndpoint(wrong, right)
        status, done = self.run_job(endpoint)
        self.assertEqual((status, done['source']), ('succeeded', 'model'), done)
        self.assertRegex(done['attempts'][0]['errors'][0], r'is an insert: an insert binds only the scene')
        self.assertIn('@CAST-02 Mira', endpoint.requests[0]['messages'][-1]['content'])
        self.assertEqual(len(done['result']['proposalIds']), 2, 'only the shots whose tags change')
        by_shot = {s['shotId']: s for s in done['result']['shots']}
        self.assertTrue(by_shot[first['shotId']]['unchanged'] and by_shot[fourth['shotId']]['unchanged'])
        self.assertEqual(by_shot[second['shotId']]['text'], 'He reaches for the brass dial. @SET-01 @CAST-01')
        self.assertEqual(by_shot[insert['shotId']]['text'], 'Insert: a hand turns the dial. @SET-01')
        self.assertEqual(self.cell(insert['shotId'], 'prompt'), insert['description'], 'nothing written yet')
        code, applied = self.decide(by_shot[insert['shotId']]['proposalId'])
        self.assertEqual(code, 200, applied)
        self.assertNotIn('@CAST', self.cell(insert['shotId'], 'prompt'))
        self.assertEqual(self.ok(f"/shots/{insert['shotId']}")['assets'], ['SET-01'])
        # One shot, its scene as context, the rule fallback after two malformed answers.
        self.ask(f"/shots/{second['shotId']}/appearance-proposals")
        status, done = self.run_job(FakeEndpoint('not json', 'still not json'))
        self.assertEqual((status, done['source'], done['target']['kind']), ('succeeded', 'rule_fallback', 'shot'), done)
        [only] = done['result']['shots']
        self.assertEqual((only['shotId'], only['cast']), (second['shotId'], ['@CAST-01']))

    # ---- R23 breakdown ----
    def test_a_breakdown_candidate_is_a_writing_preview_with_its_storyboard_impact(self):
        # setUp built the storyboard of SCRIPT (self.shots)
        job = self.ask(f'/episodes/{self.ep}/breakdown-proposals')
        self.assertEqual((job['kind'], job['target']['kind'], job['role']), ('breakdown', 'episode', 'doc_writer'))
        scenes = [s['sceneId'] for s in self.ok(f'/episodes/{self.ep}')['scenes']]
        answer = {'scenes': [{'sceneId': scenes[0], 'shots': [{'from': a, 'to': b, 'reason': 'cut'} for a, b in ((1, 1), (2, 2), (3, 3), (4, 5), (6, 6))]},
                             {'sceneId': scenes[1], 'shots': [{'from': 1, 'to': 1, 'reason': 'one beat'}]}]}
        endpoint = FakeEndpoint({'scenes': answer['scenes'][:1]}, answer)
        status, done = self.run_job(endpoint)
        self.assertEqual((status, done['source']), ('succeeded', 'model'), done)
        self.assertIn('1. Kael enters the observatory.', endpoint.requests[0]['messages'][-1]['content'])
        model, rule = done['result']['candidates']
        self.assertEqual((model['source'], model['shots'], rule['source'], rule['shots'], rule['previewId']), ('model', 6, 'rule', 5, None))
        self.assertEqual(rule['impact'], {'breakdownMode': 'auto', 'shotCount': 5, 'newShots': 0, 'keptShots': 5, 'plannedSeconds': 20})
        self.assertEqual((model['impact']['shotCount'], model['impact']['newShots'], model['impact']['keptShots']), (6, 1, 5))
        preview = self.writing('previews/' + model['previewId'])
        self.assertEqual((preview['kind'], preview['status'], preview['stale']), ('promotion', 'pending', False))
        self.assertIn('Kael enters the observatory. Rain runs down the glass.', self.ok(f'/episodes/{self.ep}')['scriptContent'],
                      'a candidate writes nothing')
        self.assertEqual(self.counted('SELECT count(*) FROM projectops.assistant_proposal WHERE project_slug=%s'), 0)
        applied = self.writing(f"previews/{model['previewId']}/apply", 'POST',
                               {'expectedPreviewVersion': preview['version'], 'selection': {'actions': [{'actionId': 'whole'}]}})
        self.assertTrue(applied['docHash'])
        after = self.ok(f'/episodes/{self.ep}')['scriptContent']
        self.assertNotIn('observatory. Rain', after)
        self.assertRegex(after, r'Kael enters the observatory\.\s+Rain runs down the glass\.\s+He reaches for the brass dial\.')
        rebuilt = self.ok(f'/episodes/{self.ep}/storyboard-estimates', 'POST', {'breakdownModes': ['auto']})['modes'][0]
        self.assertEqual(rebuilt['shotCount'], 6, 'the adopted script builds the candidate shots')
        board = self.request(f'/projects/api/{self.slug}/orchestration/board?limit=50')[1]
        item = next(i for i in board['done'] if i.get('job_id') == done['jobId'])
        self.assertEqual(item['summary'], "The crew's breakdown (6 shots) is waiting in the script view beside the rule version (5 shots). Pick one.")

    def test_a_breakdown_that_fails_twice_leaves_the_rules_and_proposes_nothing(self):
        # setUp built the storyboard of SCRIPT (self.shots)
        self.ask(f'/episodes/{self.ep}/breakdown-proposals')
        status, done = self.run_job(FakeEndpoint({'scenes': []}, {'scenes': []}))
        self.assertEqual((status, done['source'], [c['source'] for c in done['result']['candidates']]), ('succeeded', 'rule_fallback', ['rule']))
        self.assertEqual(done['result']['previewIds'], [])

    # ---- R23 adaptation ----
    def test_adaptation_candidates_are_the_crew_draft_and_the_rule_version(self):
        self.assertRegex(self.ask(f'/episodes/{self.ep}/adaptation-proposals', expect=422)['message'], r'Save your idea or novel')
        from project_docs import story_openapi as story
        doc = story.script_doc(self.slug, 'A lone courier @CAST-01 finds a brass dial that answers.')
        self.writing('sources/idea', 'PUT', {'baseVersion': 0, 'clientMutationId': 'idea-' + uuid.uuid4().hex, 'doc': doc,
                                             'structure': {}, 'composition': {}})
        self.assertEqual(self.ask(f'/episodes/{self.ep}/adaptation-proposals', {'targetScenes': 13}, expect=422)['code'], 'DRAMA_VALIDATION_FAILED')
        self.ask(f'/episodes/{self.ep}/adaptation-proposals', {'targetScenes': 2})
        answer = {'scenes': [{'title': 'The Signal', 'content': 'Environment: @SET-01\n\n@CAST-01 crosses the wet roof toward the dome.'},
                             {'title': 'The Dial', 'content': '@CAST-01 turns the brass dial; a light answers outside.'}],
                  'notes': 'Arrival, then the answer.'}
        endpoint = FakeEndpoint(answer)
        status, done = self.run_job(endpoint)
        self.assertEqual((status, done['source']), ('succeeded', 'model'), done)
        self.assertIn('A lone courier @CAST-01 finds a brass dial', endpoint.requests[0]['messages'][-1]['content'])
        model, rule = done['result']['candidates']
        self.assertEqual((model['source'], model['scenes'], rule['source']), ('model', ['Scene 01: The Signal', 'Scene 02: The Dial'], 'rule'))
        self.assertTrue(model['branchId'] and rule['branchId'] and model['previewId'] != rule['previewId'])
        self.assertEqual(self.writing('previews/' + rule['previewId'])['kind'], 'adaptation')
        for candidate in (model, rule):
            self.assertEqual(set(candidate['impact']), {'breakdownMode', 'shotCount', 'newShots', 'keptShots', 'plannedSeconds'})
        self.assertNotIn('crosses the wet roof', self.ok(f'/episodes/{self.ep}')['scriptContent'], 'a candidate writes nothing')
        preview = self.writing('previews/' + model['previewId'])
        self.writing(f"previews/{model['previewId']}/apply", 'POST',
                     {'expectedPreviewVersion': preview['version'], 'selection': {'actions': [{'actionId': 'whole'}]}})
        self.assertIn('crosses the wet roof toward the dome', self.ok(f'/episodes/{self.ep}')['scriptContent'])
        board = self.request(f'/projects/api/{self.slug}/orchestration/board?limit=50')[1]
        self.assertEqual(next(i for i in board['done'] if i.get('job_id') == done['jobId'])['summary'],
                         "2 candidates are waiting in the script view: the crew's draft and the rule version. Pick one to adopt.")

    # ---- the model-facing tools ----
    def test_tools_check_and_create_the_same_proposals(self):
        from project_assistant import tools
        from project_docs.service import Identity
        # setUp built the storyboard of SCRIPT (self.shots)
        ctx = tools.ToolContext(self.connect, self.slug, Identity(self.actor, 'Tool test', 'admin'), Path(tempfile.gettempdir()), None,
                                agent_key='doc_writer')
        with self.assertRaises(tools.ToolError) as refused:
            tools.call(ctx, 'propose_asset_description', {'asset': 'CAST-01', 'description': 'Kael, waist-up portrait, grey backdrop.'})
        self.assertIn('INVALID_DESCRIPTION', str(refused.exception))
        out = tools.call(ctx, 'propose_asset_description', {'asset': '@CAST-02', 'description': 'Mira, a tall engineer with cropped grey hair and an oil-stained canvas apron.'})
        self.assertRegex(out, r"Created proposal #\d+ for CAST-02 Mira's locked appearance")
        out = tools.call(ctx, 'propose_look', {'asset': 'CAST-01', 'key': 'rain', 'description': 'Kael, a lean courier in a soaked black rain coat.'})
        self.assertIn('adds the look CAST-01:rain (OUTFIT)', out)
        with self.assertRaises(tools.ToolError):
            tools.call(ctx, 'propose_look', {'asset': 'SET-01', 'key': 'night', 'description': 'The observatory at night with frost on the dome.'})
        _, second, insert, _ = self.scene_shots(1)
        with self.assertRaises(tools.ToolError) as refused:
            tools.call(ctx, 'propose_cast', {'shot_id': insert['shotId'], 'cast': ['@CAST-01'], 'insert': True})
        self.assertIn('INVALID_CAST', str(refused.exception))
        out = tools.call(ctx, 'propose_cast', {'shot_id': insert['shotId'], 'cast': [], 'insert': True})
        self.assertIn('Action & Audio Prompt: Insert: a hand turns the dial. @SET-01', out)
        self.conn.rollback()
        with self.conn.cursor() as cur:
            cur.execute("SELECT target->'crew'->>'kind', target->'crew'->>'source', agent_key FROM projectops.assistant_proposal WHERE project_slug=%s ORDER BY id", (self.slug,))
            self.assertEqual(cur.fetchall(), [('description', 'tool', 'doc_writer'), ('look', 'tool', 'doc_writer'), ('appearances', 'tool', 'doc_writer')])


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'set OPENBENCH_TEST_DB_URI')
class ProposalTopUpTests(unittest.TestCase):
    def setUp(self):
        import test_execution as execution_fixture
        from project_assistant import agent_registry
        execution_fixture.PostgreSQLExecutionTests.setUp(self)
        agent_registry.ensure_default_agents(self.conn, self.slug)

    def tearDown(self):
        import test_execution as execution_fixture
        execution_fixture.PostgreSQLExecutionTests.tearDown(self)

    def profiles(self):
        from project_assistant import agent_registry
        return {key: agent_registry.get_agent(self.conn, self.slug, key, effective=False) for key in tool_registry.BUILTIN_ROLES}

    def test_existing_crews_get_proposal_tools_once_and_never_a_direct_write(self):
        from project_assistant import agent_registry, context_tools, store
        from project_docs import service
        recorded = json.loads(store.get_setting(self.conn, self.slug, context_tools.PROPOSAL_TOPUP_SETTING))
        self.assertEqual(recorded['doc_writer'], ['propose_asset_description', 'propose_look', 'propose_cast'], 'the seed is recorded as offered')
        writes = {'studio_manage_asset', 'studio_ingest_script', 'propose_table_edit', 'request_generation', 'spawn_agent'}
        old = {key: [t for t in agent_registry.default_tools(key) if t not in tool_registry.PROPOSAL_ONLY and t not in writes]
               for key in tool_registry.BUILTIN_ROLES}
        with self.conn.cursor() as cur:
            for key, allowed in old.items():
                cur.execute('UPDATE projectops.agent_profile SET allowed_tools=%s::jsonb WHERE project_slug=%s AND agent_key=%s',
                            (json.dumps(allowed), self.slug, key))
            cur.execute('DELETE FROM projectops.assistant_setting WHERE project_slug=%s AND key=%s', (self.slug, context_tools.PROPOSAL_TOPUP_SETTING))
        before = {key: p['version'] for key, p in self.profiles().items()}
        agent_registry.ensure_default_agents(self.conn, self.slug)
        after = self.profiles()
        for key in tool_registry.BUILTIN_ROLES:
            with self.subTest(key=key):
                added = [t.name for t in tool_registry.all_tools() if t.name in tool_registry.PROPOSAL_ONLY and key in t.grants]
                self.assertEqual(after[key]['allowed_tools'], old[key] + added)
                self.assertFalse(set(after[key]['allowed_tools']) & writes, 'a tool that writes or spends is never added')
                self.assertEqual(after[key]['version'], before[key] + (1 if added else 0))
        self.assertEqual(after['doc_writer']['allowed_tools'][-3:], ['propose_asset_description', 'propose_look', 'propose_cast'])
        self.assertEqual(after['sheet_ops']['allowed_tools'][-2:], ['propose_shot_prompt', 'propose_camera'])
        if tool_registry.get('propose_previs_ops'):  # SPEC_20 R27 (W3b): registry-driven, so it reaches existing crews too
            self.assertIn('propose_previs_ops', after['sheet_ops']['allowed_tools'])
        with self.conn.cursor() as cur:
            cur.execute("SELECT target, detail FROM projectops.audit_log WHERE project_slug=%s AND action=%s AND detail->>'category'='proposal' ORDER BY target",
                        (self.slug, context_tools.TOPUP_ACTION))
            audits = dict(cur.fetchall())
        self.assertEqual(audits['doc_writer']['added'], ['propose_asset_description', 'propose_look', 'propose_cast'])
        self.assertNotIn('qa_critic', audits)
        agent_registry.ensure_default_agents(self.conn, self.slug)  # idempotent: nothing more to add, no new version
        self.assertEqual({k: (p['allowed_tools'], p['version']) for k, p in self.profiles().items()},
                         {k: (p['allowed_tools'], p['version']) for k, p in after.items()})
        me = service.Identity(self.actor, 'Execution test', 'admin')
        current = self.profiles()['doc_writer']['allowed_tools']
        agent_registry.save_agent(self.conn, me, self.slug, {'agent_key': 'doc_writer', 'allowed_tools': [t for t in current if t != 'propose_look']})
        agent_registry.ensure_default_agents(self.conn, self.slug)
        self.assertNotIn('propose_look', self.profiles()['doc_writer']['allowed_tools'], 'a removed tool stays removed')


if __name__ == '__main__':
    unittest.main()
