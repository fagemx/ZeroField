"""SPEC_21 package B: the reference plan (§3.5), the first-frame prompt (§3.3), the video skeleton (§3.2) and the asset
panel and edit prompts (§3.4) the context compiler adds. Pure: no database, model, GPU or network."""
import ast
import copy
import os
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from project_assistant import limb_worker as worker
from project_assistant.studio import context_compiler, shot_skeleton
from project_docs import story_look

ASSET = lambda n: '/projects/api/demo/assets/pa_' + format(n, '032x')
NEW_KEYS = {'reference_plan', 'image_reference_prompt', 'video_skeleton_prompt', 'dropped_blocks', 'asset_panel_prompt',
            'edit_prompt'}
OLD_KEYS = {'compiled_prompt', 'action_prompt', 'seed', 'optical_rig', 'camera_motion', 'camera_moves', 'jutsu_mode',
            'look_film', 'look_color', 'look_light', 'resolved_assets', 'asset_map', 'excluded_refs', 'slot_plan',
            'asset_images', 'reference_image_urls', 'primary_image_url', 'previs_video', 'source_video', 'pose_skeleton',
            'first_frame', 'motion_structure_video', 'anchor_keyframe', 'output_video', 'ingredients_sheet', 'frame_sheet',
            'time_strata', 'actor_matte', 'source_video_url', 'h3_context_ir_prompt', 'ltx_ingredients_prompt'}
SHOT_HEADERS = ['Shot', 'Optical Rig (Camera & Lens)', 'Camera Motion', 'Action & Audio Prompt', 'Keyframe', 'Cinema Shot',
                'Status', 'Director Take Notes']
CAST_HEADERS = ['Asset ID', 'Character / Set', 'Locked Appearance Prompt / Seed', 'Reference Image',
                'Voice / Audio Profile', 'Status', 'Notes']
CAST_ROWS = [
    ['CAST-01', 'Noa', 'trainee pilot with short dark hair, red flight jacket, leather gloves; seed 101', ASSET(1),
     'Quick and breathy, a little high', 'Queued', ''],
    ['CAST-02', 'Ines', 'An instructor with grey braided hair and a crooked nose. She wears a grey fleece over a wool '
     'sweater, a wool cap and black leather boots.', ASSET(2), 'Low and even, unhurried', 'Queued', ''],
    ['CAST-03', 'Tomas', 'ground crew with a shaved head, orange overalls', ASSET(7), 'Loud, clipped', 'Queued', ''],
    ['SET-01', 'Canyon rim', 'red sandstone canyon rim at dawn with a wicker balloon basket', ASSET(3), 'Wind', 'Queued', ''],
    ['PROP-01', 'Burner', 'twin-coil propane burner with a blue valve', ASSET(4), '', 'Queued', ''],
    ['PROP-02', 'Altimeter', 'round brass altimeter on a leather strap', ASSET(5), '', 'Queued', ''],
    ['CAST-01:WET', 'Noa', 'Same identity as @CAST-01: same face, body proportions and posture. Changed: soaked hair '
     'and a dripping jacket.', '', '', 'Queued', ''],
]
META = {
    'CAST-01': {'acting': 'Breathes through the mouth; eyes go to the envelope, then to the valve.', 'geo': '', 'light': '',
                'lock': '', 'change': '', 'panels': {'face': ASSET(11), 'front': ASSET(12), 'back': ASSET(13),
                                                     'sheet': ASSET(14)}},
    'CAST-03': {'acting': 'Plants both feet wide and pulls the line hand over hand.',
                'panels': {'face': ASSET(15), 'front': ASSET(16)}},
    'SET-01': {'geo': 'The basket hangs east of the rim; the far canyon wall is behind the camera.',
               'light': 'Low sun from the east across the basket. Long shadows run west.', 'panels': {'plate': ASSET(21)}},
    'PROP-01': {'lock': 'Two stacked steel coils over one blue valve, mounted on a square frame.',
                'panels': {'product': ASSET(31)}},
    'PROP-02': {'lock': 'A round dial with one needle.', 'panels': {'product': ASSET(32)}},
}
LOOK = {'film': 'fine organic grain, slow steady pacing', 'filmStill': 'fine organic grain', 'color': 'warm ochre and sky blue',
        'light': 'low golden side light', 'camera': ''}
NEGATIVE = re.compile(r'\b(no|not|without)\b', re.I)


def shot_task(action, *, meta=META, look=None, optical='ARRI Alexa 65 / 35mm Anamorphic', motion='', capability='video_gen',
              rows=CAST_ROWS, **source_extra):
    """A shot task in the shape the Story API snapshot sends (no table ids)."""
    row = {'row_id': 'sh_1', 'tab_key': 'cinema-studio', 'cells': ['S03', optical, motion, action, '', '', 'Queued', '']}
    source = {'rows': [row],
              'tabs': [{'tab_key': 'cinema-studio', 'tables': [{'headers': SHOT_HEADERS, 'rows': [row]}]},
                       {'tab_key': 'soul-cast', 'tables': [{'headers': CAST_HEADERS,
                                                            'rows': [{'cells': list(cells)} for cells in rows]}]}]}
    if meta is not None:
        source['asset_meta'] = copy.deepcopy(meta)
    if look is not None:
        source['look'] = dict(look)
    source.update(source_extra)
    return {'input': source, 'capability': capability}


def asset_task(code, panel=None, *, meta=META, **source_extra):
    """An asset generation task as package C builds it: the row, the soul-cast table and the §2.5 keys."""
    cells = list(next(cells for cells in CAST_ROWS if cells[0] == code))
    row = {'row_id': 'as_1', 'tab_key': 'soul-cast', 'cells': cells}
    source = {'rows': [row],
              'tabs': [{'tab_key': 'soul-cast', 'tables': [{'headers': CAST_HEADERS, 'rows': [{'row_id': 'as_1', 'cells': cells}]}]},
                       {'tab_key': 'soul-cast', 'tables': [{'headers': CAST_HEADERS,
                                                            'rows': [{'cells': list(c)} for c in CAST_ROWS]}]}],
              'asset_meta': copy.deepcopy(meta)}
    if panel is not None:
        source['panel'] = panel
    source.update(source_extra)
    return {'input': source, 'capability': 'image_gen'}


def ctx_of(task):
    return worker.resolve_studio_context(task)


def plan_rows(plan):
    return [(entry['assetCode'], entry['role'], entry['panel'], entry['url']) for entry in plan]


def blocks_of(prompt):
    """The block titles of a video skeleton, in order."""
    return [match[1] or 'ORDER' for match in re.finditer(r'^(?:([A-Z][A-Z ]+[A-Z]):$|\[ORDER: )', prompt, re.M)]


class ReferencePlanTests(unittest.TestCase):
    """A5: two pictures per character, one per place and object, mention order, at most six, exclusions, drop order."""

    def test_a_character_sends_face_and_front_a_place_its_plate_an_object_its_product(self):
        ctx = ctx_of(shot_task('[0-2s] @CAST-01 opens the valve of @PROP-01 in @SET-01.'))
        self.assertEqual(plan_rows(ctx['reference_plan']), [
            ('CAST-01', 'character_face', 'face', ASSET(11)), ('CAST-01', 'character_body', 'front', ASSET(12)),
            ('PROP-01', 'prop', 'product', ASSET(31)), ('SET-01', 'location', 'plate', ASSET(21))])
        self.assertEqual(set(ctx['reference_plan'][0]), {'assetCode', 'role', 'panel', 'url'})

    def test_without_panels_the_reference_image_stands_in(self):
        ctx = ctx_of(shot_task('@CAST-02 watches @CAST-01 at @SET-01.', meta=None))
        self.assertEqual(plan_rows(ctx['reference_plan']), [
            ('CAST-02', 'character_face', 'reference', ASSET(2)), ('CAST-01', 'character_face', 'reference', ASSET(1)),
            ('SET-01', 'location', 'reference', ASSET(3))])
        # An asset with neither a panel nor a reference image sends nothing.
        rows = [cells if cells[0] != 'CAST-02' else cells[:3] + [''] + cells[4:] for cells in CAST_ROWS]
        ctx = ctx_of(shot_task('@CAST-02 watches.', rows=rows))
        self.assertEqual(ctx['reference_plan'], [])

    def test_six_at_most_props_go_first_then_character_fronts(self):
        meta = copy.deepcopy(META)
        meta['CAST-02'] = {'panels': {'face': ASSET(17), 'front': ASSET(18)}}
        ctx = ctx_of(shot_task('@CAST-01 @PROP-01 and @CAST-02 @CAST-03 by @PROP-02 at @SET-01.', meta=meta))
        self.assertEqual(plan_rows(ctx['reference_plan']), [
            ('CAST-01', 'character_face', 'face', ASSET(11)), ('CAST-01', 'character_body', 'front', ASSET(12)),
            ('CAST-02', 'character_face', 'face', ASSET(17)), ('CAST-02', 'character_body', 'front', ASSET(18)),
            ('CAST-03', 'character_face', 'face', ASSET(15)), ('SET-01', 'location', 'plate', ASSET(21))])
        # Seven after the props: one front goes, the last mentioned character's.
        ctx = ctx_of(shot_task('@CAST-01 @CAST-02 @CAST-03 at @SET-01 with @PROP-01.', meta=meta))
        self.assertEqual([(code, role) for code, role, _, _ in plan_rows(ctx['reference_plan'])], [
            ('CAST-01', 'character_face'), ('CAST-01', 'character_body'), ('CAST-02', 'character_face'),
            ('CAST-02', 'character_body'), ('CAST-03', 'character_face'), ('SET-01', 'location')])
        self.assertTrue(all(len(shot_skeleton.reference_plan(
            [{'code': f'CAST-{i:02d}', 'kind': 'character', 'image': ASSET(100 + i), 'panels': {}} for i in range(n)])) <= 6
            for n in range(12)))

    def test_excluded_assets_and_their_variants_are_not_sent(self):
        ctx = ctx_of(shot_task('@CAST-01 at @SET-01. !@CAST-02 @CAST-02:night'))
        self.assertEqual([code for code, *_ in plan_rows(ctx['reference_plan'])], ['CAST-01', 'CAST-01', 'SET-01'])
        self.assertNotIn('Ines', ctx['image_reference_prompt'] + ctx['video_skeleton_prompt'])

    def test_a_remote_panel_url_is_never_sent(self):
        meta = copy.deepcopy(META)
        meta['CAST-01']['panels'] = {'face': 'https://example.com/face.png', 'front': {'url': ASSET(12), 'imageId': 'im_1'}}
        ctx = ctx_of(shot_task('@CAST-01 waits.', meta=meta))
        self.assertEqual(plan_rows(ctx['reference_plan']), [('CAST-01', 'character_body', 'front', ASSET(12))])

    def test_a_quoted_reference_take_takes_a_place_only_while_one_is_left(self):
        take = {'shotIndex': 'S01', 'edge': 'end', 'use': 'reference', 'frameUrl': ASSET(50)}
        ctx = ctx_of(shot_task('@S01.end @CAST-01 turns at @SET-01.', take_refs=[take]))
        self.assertEqual(plan_rows(ctx['reference_plan'])[-1], ('S01.END', 'take_frame', 'frame', ASSET(50)))
        self.assertIn('Image 4: match the setting and lighting of shot S01.', ctx['image_reference_prompt'])
        meta = copy.deepcopy(META)
        meta['CAST-02'] = {'panels': {'face': ASSET(17), 'front': ASSET(18)}}
        full = ctx_of(shot_task('@S01.end @CAST-01 @CAST-02 @CAST-03 at @SET-01.', meta=meta, take_refs=[take]))
        self.assertEqual(len(full['reference_plan']), 6)
        self.assertNotIn(ASSET(50), [entry['url'] for entry in full['reference_plan']])


class ImageReferencePromptTests(unittest.TestCase):
    """A4: image numbers follow the plan, at most 1,500 characters, positive wording only."""

    def test_image_numbers_are_the_plan_order(self):
        ctx = ctx_of(shot_task('[0-2s] @CAST-02 watches @CAST-01 open the valve of @PROP-01 at @SET-01.', look=LOOK))
        prompt, plan = ctx['image_reference_prompt'], ctx['reference_plan']
        self.assertEqual([entry['assetCode'] for entry in plan], ['CAST-02', 'CAST-01', 'CAST-01', 'PROP-01', 'SET-01'])
        self.assertIn('The person in image 1 is Ines: same face and clothes as in image 1. An instructor with grey braided '
                      'hair', prompt)
        self.assertIn('The person in image 2 and image 3 is Noa: same face from image 2, same clothes from image 3. '
                      'trainee pilot with short dark hair, red flight jacket, leather gloves.', prompt)
        self.assertIn('The Burner is the object in image 4: twin-coil propane burner with a blue valve. Two stacked steel '
                      'coils over one blue valve, mounted on a square frame.', prompt)
        self.assertIn('The place is the one in image 5: take only its space and materials', prompt)
        self.assertEqual(sorted({int(n) for n in re.findall(r'image (\d+)', prompt, re.I)}), [1, 2, 3, 4, 5])

    def test_the_prompt_reads_in_the_fixed_order(self):
        ctx = ctx_of(shot_task('[0-2s] @CAST-01 grips the valve. #push-in\n[2-4s] @CAST-01 looks up.', look=LOOK,
                               motion='Wide shot, slow dolly'))
        lines = ctx['image_reference_prompt'].split('\n')
        self.assertEqual(lines[0], 'Cinematic film still. Wide shot. 35mm Anamorphic lens.')
        self.assertEqual(lines[1], 'Noa grips the valve.')  # the first timed segment, as a state; the move tag goes
        self.assertTrue(lines[2].startswith('The person in image 1 and image 2 is Noa'))
        self.assertEqual(lines[3], 'Lighting: low golden side light.')
        self.assertEqual(lines[4], 'Film: fine organic grain. Color: warm ochre and sky blue.')
        self.assertEqual(lines[5], 'Exactly 1 person in frame.')
        self.assertNotIn('ARRI', ctx['image_reference_prompt'])
        # One prompt for a still and a clip alike.
        still = ctx_of(shot_task('[0-2s] @CAST-01 grips the valve. #push-in\n[2-4s] @CAST-01 looks up.', look=LOOK,
                                 motion='Wide shot, slow dolly', capability='image_gen'))
        self.assertEqual(still['image_reference_prompt'], ctx['image_reference_prompt'])

    def test_the_place_lights_the_frame_and_an_empty_place_says_so(self):
        ctx = ctx_of(shot_task('Dawn over @SET-01.', look=LOOK))
        self.assertIn('Low sun from the east across the basket. Lighting: low golden side light.', ctx['image_reference_prompt'])
        self.assertNotIn('Long shadows run west', ctx['image_reference_prompt'])  # the light's first sentence only
        self.assertTrue(ctx['image_reference_prompt'].endswith('An empty place with nobody in it.'))

    def test_only_positive_wording_outside_the_description_text(self):
        action = ('[0-2s] @CAST-02 says "Your balloon." to @CAST-01 by @PROP-01 at @SET-01. #whip-pan\n'
                  'PHYSICS: the basket sways.\nCHECK: Ines keeps both hands on the rail.\n[2-4s] @CAST-01 lights it.')
        for meta in (META, None):
            ctx = ctx_of(shot_task(action, look=LOOK, meta=meta, motion='Static'))
            with self.subTest(meta=bool(meta)):
                self.assertIsNone(NEGATIVE.search(ctx['image_reference_prompt']), ctx['image_reference_prompt'])
                self.assertNotIn('"', ctx['image_reference_prompt'])  # a still speaks no line
                self.assertNotIn('PHYSICS', ctx['image_reference_prompt'])
        # A negative the locked text itself writes is pasted as written.
        rows = [cells if cells[0] != 'PROP-01' else cells[:2] + ['a burner, not a lamp'] + cells[3:] for cells in CAST_ROWS]
        self.assertIn('a burner, not a lamp', ctx_of(shot_task('@PROP-01 burns.', rows=rows))['image_reference_prompt'])

    def test_over_1500_characters_it_shortens_film_light_then_descriptions(self):
        long_look = dict(LOOK, filmStill='grain ' * 260)
        ctx = ctx_of(shot_task('@CAST-01 at @SET-01.', look=long_look))
        prompt = ctx['image_reference_prompt']
        self.assertLessEqual(len(prompt), 1500)
        self.assertNotIn('Film:', prompt)
        self.assertIn('Lighting: low golden side light.', prompt)
        long_light = dict(long_look, light='gold ' * 300)
        prompt = ctx_of(shot_task('@CAST-01 at @SET-01.', look=long_light))['image_reference_prompt']
        self.assertNotIn('Lighting:', prompt)
        self.assertIn('trainee pilot with short dark hair', prompt)
        rows = [cells[:2] + [cells[2] + ', ' + 'weathered ' * 140] + cells[3:] for cells in CAST_ROWS]
        prompt = ctx_of(shot_task('@CAST-01 @CAST-02 @CAST-03 at @SET-01 with @PROP-01.', rows=rows, look=long_light)
                        )['image_reference_prompt']
        self.assertLessEqual(len(prompt), 1500)
        self.assertNotIn('weathered', prompt)
        for sentence in ('The person in image 1 and image 2 is Noa: same face from image 1, same clothes from image 2.',
                         'The person in image 3 is Ines: same face and clothes as in image 3.',
                         'The person in image 4 and image 5 is Tomas: same face from image 4, same clothes from image 5.',
                         'The place is the one in image 6', 'Exactly 3 people in frame.'):
            self.assertIn(sentence, prompt)
        # Descriptions go one asset at a time: the place first (its picture carries it), the characters last.
        rows = [cells[:2] + [cells[2] + ', ' + ('ochre ' * 70 if cells[0] == 'SET-01' else 'sun-browned ' * 30)] + cells[3:]
                for cells in CAST_ROWS]
        prompt = ctx_of(shot_task('@CAST-01 and @CAST-02 at @SET-01.', rows=rows))['image_reference_prompt']
        self.assertLessEqual(len(prompt), 1500)
        self.assertNotIn('ochre', prompt)
        self.assertIn('same clothes from image 2. trainee pilot with short dark hair', prompt)
        self.assertIn('same face and clothes as in image 3. An instructor with grey braided hair', prompt)
        # An action longer than the limit is cut at a word, after everything else has gone.
        prompt = ctx_of(shot_task('@CAST-01 ' + 'climbs ' * 400, rows=rows))['image_reference_prompt']
        self.assertLessEqual(len(prompt), 1500)
        self.assertTrue(prompt.endswith('Exactly 1 person in frame.'))
        self.assertIn('The person in image 1 and image 2 is Noa', prompt)


class VideoSkeletonTests(unittest.TestCase):
    """A3: block order, the people lock, the voice lock, the lines, the PHYSICS / CHECK / ORDER sections and the budget."""
    ACTION = ('[0-2s] @CAST-01 grips the valve of @PROP-01 as the basket drops toward @SET-01. #push-in\n'
              '[2-4s] @CAST-02 watches, hands still. Without looking up, @CAST-02 says "Your balloon."\n'
              '[4-6s] "Lighting it now." @CAST-01 pulls the valve.\n'
              'PHYSICS: the basket sways on four ropes; the flame roars up.\n'
              'CHECK: Ines keeps both hands on the rail.\n'
              'ORDER: Noa first, then Ines.')

    def skeleton(self, action=ACTION, **kwargs):
        return ctx_of(shot_task(action, look=LOOK, **kwargs))

    def test_blocks_come_in_the_fixed_order(self):
        ctx = self.skeleton()
        self.assertEqual(blocks_of(ctx['video_skeleton_prompt']), list(shot_skeleton.BLOCKS))
        self.assertEqual(ctx['dropped_blocks'], [])
        self.assertTrue(ctx['video_skeleton_prompt'].endswith('[ORDER: Noa first, then Ines.]'))
        # A shot never carries a panel or edit prompt: flux-soul-cast would prefer it over the shot's own text.
        self.assertEqual((ctx['asset_panel_prompt'], ctx['edit_prompt']), ('', ''))

    def test_scene_context_locks_the_head_count(self):
        prompt = self.skeleton()['video_skeleton_prompt']
        self.assertIn('SCENE CONTEXT:\nEXACT 2 CHARACTERS — NO DUPLICATES: Noa, Ines.\nShot S03.\n', prompt)
        self.assertIn('Location: Canyon rim.\nDuration: 6 seconds.\nOne continuous shot, no cuts.', prompt)
        self.assertIn('Exactly 2 people in frame: Noa and Ines; each appears once.', prompt)
        empty = ctx_of(shot_task('Dawn over @SET-01.'))['video_skeleton_prompt']
        self.assertTrue(empty.startswith('SCENE CONTEXT:\nNo people in frame.\n'))
        self.assertIn('The frame stays empty of people.', empty)
        one = ctx_of(shot_task('@CAST-01 waits. CUT TO the valve.'))['video_skeleton_prompt']
        self.assertIn('EXACT 1 CHARACTER — NO DUPLICATES: Noa.', one)
        self.assertIn('Hard cuts exactly where the action timing marks them.', one)

    def test_references_map_and_light_are_the_locks_word_for_word(self):
        prompt = self.skeleton()['video_skeleton_prompt']
        self.assertIn('ACTIVE REFERENCES:\n@CAST-01 (Noa) — trainee pilot with short dark hair, red flight jacket, leather '
                      'gloves.\n@PROP-01 (Burner) — twin-coil propane burner with a blue valve. Shape lock: Two stacked steel '
                      'coils over one blue valve, mounted on a square frame.\n@SET-01 (Canyon rim) — red sandstone canyon '
                      'rim at dawn with a wicker balloon basket. Take only the space and the materials.\n@CAST-02 (Ines)',
                      prompt)
        self.assertIn('LOCATION MAP:\nThe basket hangs east of the rim; the far canyon wall is behind the camera.', prompt)
        self.assertIn('LIGHTING:\nLow sun from the east across the basket. Long shadows run west.\n'
                      'Lighting: low golden side light.', prompt)
        self.assertIn('CHARACTER ACTING:\nNoa: Breathes through the mouth; eyes go to the envelope, then to the valve.', prompt)
        self.assertIn('STYLE:\nFilm: fine organic grain, slow steady pacing.\nColor: warm ochre and sky blue.', prompt)
        self.assertIn('OPTICS:\nARRI Alexa 65 / 35mm Anamorphic.', prompt)
        self.assertIn('FIRST FRAME AND BLOCKING:\nThe first frame is the given image; everyone stays where it places them.',
                      prompt)
        self.assertNotIn('seed', prompt)

    def test_audio_gives_each_speaker_their_voice_and_only_their_quoted_lines(self):
        prompt = self.skeleton()['video_skeleton_prompt']
        self.assertIn('AUDIO:\nInes voice (verbatim): "Low and even, unhurried". Line, and nothing else: "Your balloon."\n'
                      'Noa voice (verbatim): "Quick and breathy, a little high". Line, and nothing else: "Lighting it now."\n'
                      'Nobody else speaks. Only the quoted lines are spoken. Natural sound only, no music.', prompt)
        silent = ctx_of(shot_task('@CAST-01 waits.'))['video_skeleton_prompt']
        self.assertIn('AUDIO:\nNobody speaks. Natural sound only, no music.', silent)
        # The only character in the shot speaks an unattributed line; two lines of one speaker keep their order.
        alone = ctx_of(shot_task('"Steady." @CAST-01 breathes out. "Now."'))['video_skeleton_prompt']
        self.assertIn('Noa voice (verbatim): "Quick and breathy, a little high". Lines, and nothing else, in this order: '
                      '"Steady.", then "Now."', alone)

    def test_line_start_timings_and_a_she_says_line(self):
        """The Updraft way of writing a shot: "0.0–1.0s — ..." segments and a pronoun before the line."""
        noa = ctx_of(shot_task('0.0–1.0s — @CAST-01 in close-up, @CAST-02 soft behind her.\n'
                               '1.0–4.0s — she speaks fast and low, to the burner and not to Ines: "It\'s out."\n'
                               'CHECK: her face stays the face of @CAST-01.', optical='Cinema camera / 85mm close-up'))
        self.assertIn('Noa voice (verbatim): "Quick and breathy, a little high". Line, and nothing else: "It\'s out."',
                      noa['video_skeleton_prompt'])
        self.assertIn('Duration: 4 seconds.', noa['video_skeleton_prompt'])
        self.assertIn('ACTION TIMING:\n0.0–1.0s — Noa in close-up, Ines soft behind her.\n1.0–4.0s — she speaks',
                      noa['video_skeleton_prompt'])
        self.assertIn('her face stays the face of Noa.', noa['video_skeleton_prompt'])
        self.assertTrue(noa['image_reference_prompt'].startswith(
            'Cinematic film still. Close-up. 85mm lens.\nNoa in close-up, Ines soft behind her.\n'))
        ines = ctx_of(shot_task("0.0–1.5s — @CAST-02 in close-up, eyes on Noa's hands.\n"
                                '1.5–4.0s — low and slow, she says: "Your balloon."'))
        self.assertIn('Ines voice (verbatim): "Low and even, unhurried". Line, and nothing else: "Your balloon."',
                      ines['video_skeleton_prompt'])
        self.assertEqual(shot_skeleton.dialogue('Noa nods. "Go," Ines says.', [('CAST-01', 'Noa'), ('CAST-02', 'Ines')]),
                         [('CAST-02', 'Go,')])

    def test_sections_leave_the_action_and_go_to_their_blocks(self):
        prompt = self.skeleton()['video_skeleton_prompt']
        timing = prompt.split('ACTION TIMING:\n')[1].split('\n\n')[0]
        self.assertEqual(timing, '[0-2s] Noa grips the valve of Burner as the basket drops toward Canyon rim. '
                                 + story_look.option('move', 'push-in')['promptText'] + '\n'
                                 '[2-4s] Ines watches, hands still. Without looking up, Ines says "Your balloon."\n'
                                 '[4-6s] "Lighting it now." Noa pulls the valve.')
        self.assertIn('PHYSICS:\nthe basket sways on four ropes; the flame roars up.\n\nLIGHTING:', prompt)
        self.assertIn('Ines keeps both hands on the rail.\n\n[ORDER: Noa first, then Ines.]', prompt)
        self.assertIn('CAMERA:\n' + story_look.option('move', 'push-in')['promptText'], prompt)
        plain = ctx_of(shot_task('@CAST-01 waits.'))['video_skeleton_prompt']
        self.assertEqual([b for b in blocks_of(plain) if b in ('PHYSICS', 'ORDER', 'LOCATION MAP', 'STYLE')], [])

    def test_the_camera_block_takes_the_column_or_stays_put(self):
        self.assertIn('CAMERA:\nSlow crane up.\n', ctx_of(shot_task('@CAST-01 waits.', motion='Slow crane up'))['video_skeleton_prompt'])
        self.assertIn('CAMERA:\nThe camera STAYS PUT: no push, no zoom, no pan.\n',
                      ctx_of(shot_task('@CAST-01 waits.'))['video_skeleton_prompt'])

    def test_over_budget_whole_blocks_go_in_order_and_are_reported(self):
        full = self.skeleton()
        chunks = set(full['video_skeleton_prompt'].split('\n\n'))
        length = len(full['video_skeleton_prompt'])
        with patch.dict(os.environ, {shot_skeleton.VIDEO_BUDGET_ENV: str(length - 1)}):
            one = self.skeleton()
        self.assertEqual(one['dropped_blocks'], ['PHYSICS'])
        self.assertNotIn('PHYSICS:', one['video_skeleton_prompt'])
        with patch.dict(os.environ, {shot_skeleton.VIDEO_BUDGET_ENV: '200'}):
            tight = self.skeleton()
        self.assertEqual(tight['dropped_blocks'], list(shot_skeleton.DROP_ORDER))
        self.assertEqual(blocks_of(tight['video_skeleton_prompt']),
                         ['SCENE CONTEXT', 'FIRST FRAME AND BLOCKING', 'CAMERA', 'ACTION TIMING', 'LIGHTING', 'AUDIO',
                          'STYLE', 'POSITIVE CONSTRAINTS'])
        # Every block that stays is whole: no sentence is cut.
        self.assertTrue(set(tight['video_skeleton_prompt'].split('\n\n')) <= chunks)
        # Only blocks the shot has are reported.
        with patch.dict(os.environ, {shot_skeleton.VIDEO_BUDGET_ENV: '50'}):
            plain = ctx_of(shot_task('@CAST-01 waits.'))
        self.assertEqual(plain['dropped_blocks'], ['CHARACTER ACTING', 'OPTICS', 'ACTIVE REFERENCES'])

    def test_the_budget_defaults_to_4000(self):
        self.assertEqual(shot_skeleton.video_budget({}), 4000)
        self.assertEqual(shot_skeleton.video_budget({shot_skeleton.VIDEO_BUDGET_ENV: 'many'}), 4000)
        self.assertEqual(shot_skeleton.video_budget({shot_skeleton.VIDEO_BUDGET_ENV: '0'}), 4000)
        self.assertEqual(shot_skeleton.video_budget({shot_skeleton.VIDEO_BUDGET_ENV: ' 2500 '}), 2500)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(shot_skeleton.VIDEO_BUDGET_ENV, None)
            ctx = self.skeleton(self.ACTION + '\n[6-8s] ' + 'Noa holds the line. ' * 100)
        self.assertLessEqual(len(ctx['video_skeleton_prompt']), 4000)
        self.assertEqual(ctx['dropped_blocks'][0], 'PHYSICS')


class AssetPanelTests(unittest.TestCase):
    """§2.3 and §3.4: each panel's pictures and prompt; reverse, angle and variants are edits."""

    def test_face_front_and_back_are_the_gpu_proven_texts(self):
        """§3.4 as revised after the 2026-10-29 Klein trial: the build is the description's first sentence and the clothes
        the rest; the front keeps its head (the server crops it), the back takes the face alone."""
        meta = copy.deepcopy(META)
        meta['CAST-02'] = {'panels': {'face': ASSET(17)}}
        face = ctx_of(asset_task('CAST-02', 'face', meta=meta))
        self.assertEqual(face['reference_plan'], [])
        self.assertEqual(face['asset_panel_prompt'],
                         'Close-up studio photograph of an instructor with grey braided hair and a crooked nose; a grey '
                         'fleece over a wool sweater shows at the neck. Head and shoulders, face turned slightly in '
                         'three-quarter view, eyes looking just past the camera. Neutral mid-grey studio backdrop, soft flat '
                         'light from one side, real unretouched skin with visible pores, fine vellus hair and natural '
                         'asymmetry, a small catch-light in each eye. Plain documentary studio photograph, natural colour.')
        self.assertEqual(face['edit_prompt'], '')
        front = ctx_of(asset_task('CAST-02', 'front', meta=meta))
        self.assertEqual(plan_rows(front['reference_plan']), [('CAST-02', 'character_face', 'face', ASSET(17))])
        self.assertEqual(front['asset_panel_prompt'],
                         'Full-body studio photograph from the front of the person in image 1, an instructor with grey '
                         'braided hair and a crooked nose, wearing a grey fleece over a wool sweater, a wool cap and black '
                         'leather boots. She stands straight facing the camera, arms relaxed at her sides, feet slightly '
                         'apart, the whole figure from the top of the head to the boots in frame with a margin of grey above '
                         'the head and below the feet. Neutral mid-grey studio backdrop, flat even light, real fabric '
                         'texture, plain documentary studio photograph.')
        back = ctx_of(asset_task('CAST-02', 'back', meta=meta))
        self.assertEqual(plan_rows(back['reference_plan']), [('CAST-02', 'character_face', 'face', ASSET(17))])
        self.assertEqual(back['asset_panel_prompt'],
                         'Full-body studio photograph of an instructor with grey braided hair and a crooked nose seen from '
                         'directly behind, the person in image 1 turned completely away from the camera. We see the back of '
                         'the head and the hair, the back of every garment — a grey fleece over a wool sweater, a wool cap '
                         'and black leather boots — and the heels of the shoes. The arms hang relaxed at the sides with the '
                         'backs of the hands toward the camera, feet slightly apart, the whole figure in frame with a margin '
                         'of grey above the head and below the feet. Neutral mid-grey studio backdrop, flat even light, real '
                         'fabric texture, plain documentary studio photograph.')
        self.assertNotIn('outside the frame', front['asset_panel_prompt'] + back['asset_panel_prompt'])
        # A description that does not split goes whole into the clothes; no gender or footwear named, none is written.
        single = ctx_of(asset_task('CAST-01', 'front'))
        self.assertIn('the person in image 1, wearing trainee pilot with short dark hair, red flight jacket, leather '
                      'gloves. The person stands straight facing the camera, arms relaxed at their sides', single['asset_panel_prompt'])
        self.assertIn('from the top of the head to the feet in frame', single['asset_panel_prompt'])
        self.assertTrue(ctx_of(asset_task('CAST-01', 'face'))['asset_panel_prompt'].startswith(
            'Close-up studio photograph of trainee pilot with short dark hair, red flight jacket, leather gloves. Head and '))
        man = shot_skeleton.asset_panel_prompt({'code': 'CAST-09', 'kind': 'character', 'description': 'A tall man with a '
                                                'grey beard. He wears a canvas coat and work shoes.'}, 'front', [])
        self.assertIn('a tall man with a grey beard, wearing a canvas coat and work shoes. He stands straight facing the '
                      'camera, arms relaxed at his sides, feet slightly apart, the whole figure from the top of the head to '
                      'the shoes', man)
        for ctx in (face, front, back):
            self.assertEqual((ctx['video_skeleton_prompt'], ctx['dropped_blocks']), ('', []))
        # Front and back render on the reference card, which reads image_reference_prompt; the face does not.
        self.assertEqual(face['image_reference_prompt'], '')
        for ctx in (front, back):
            self.assertEqual(ctx['image_reference_prompt'], ctx['asset_panel_prompt'])

    def test_plate_and_product(self):
        plate = ctx_of(asset_task('SET-01', 'plate'))
        self.assertEqual(plate['reference_plan'], [])
        self.assertEqual(plate['asset_panel_prompt'],
                         'Wide three-quarter view of red sandstone canyon rim at dawn with a wicker balloon basket, empty of '
                         'people, camera at eye height looking diagonally across the space, Low sun from the east across the '
                         'basket, real materials, cinematic film still.')
        product = ctx_of(asset_task('PROP-01', 'product'))
        self.assertEqual(product['asset_panel_prompt'],
                         'Photorealistic three-quarter overhead product photograph of twin-coil propane burner with a blue '
                         'valve on a neutral grey surface, soft directional light, isolated object, plain unbranded '
                         'surfaces. Two stacked steel coils over one blue valve, mounted on a square frame.')

    def test_reverse_and_angle_edit_the_plate(self):
        for panel in ('reverse', 'angle'):
            with self.subTest(panel=panel):
                ctx = ctx_of(asset_task('SET-01', panel))
                self.assertEqual(plan_rows(ctx['reference_plan']), [('SET-01', 'location', 'plate', ASSET(21))])
                self.assertEqual(ctx['asset_panel_prompt'], '')
                self.assertTrue(ctx['edit_prompt'].startswith('Edit image 1. CHANGE: ' + shot_skeleton.VIEW_CHANGES[panel]))
                self.assertTrue(ctx['edit_prompt'].endswith('Only change what is named; everything else stays identical.'))
                self.assertIn('PRESERVE EXACTLY: the architecture, the materials and their wear, every fixed object',
                              ctx['edit_prompt'])
        written = ctx_of(asset_task('SET-01', 'reverse', change='the basket now in the foreground, the rim behind it'))
        self.assertIn('CHANGE: the basket now in the foreground, the rim behind it. PRESERVE', written['edit_prompt'])

    def test_stress_tests_use_the_plan_and_one_of_ten_variations(self):
        ctx = ctx_of(asset_task('CAST-01', 'stress', variation=3, stress_with=['CAST-02'], stress_set='SET-01'))
        self.assertEqual(plan_rows(ctx['reference_plan']), [
            ('CAST-01', 'character_face', 'face', ASSET(11)), ('CAST-01', 'character_body', 'front', ASSET(12)),
            ('CAST-02', 'character_face', 'reference', ASSET(2)), ('SET-01', 'location', 'plate', ASSET(21))])
        prompt = ctx['asset_panel_prompt']
        pose, light, _ = shot_skeleton.STRESS_VARIATIONS[3]
        self.assertIn('The person in image 1 and image 2 is Noa: same face from image 1, same clothes from image 2.', prompt)
        self.assertIn('The person in image 3 is Ines: same face and clothes as in image 3.', prompt)
        self.assertIn('The place is the one in image 4', prompt)
        self.assertIn(f'Noa and Ines {pose}, {light}.', prompt)
        self.assertTrue(prompt.endswith('Exactly 2 people in frame.'))
        self.assertLessEqual(len(prompt), 1500)
        self.assertEqual(ctx['edit_prompt'], '')
        self.assertEqual(ctx['image_reference_prompt'], prompt)
        prompts ={ctx_of(asset_task('CAST-01', 'stress', variation=i))['asset_panel_prompt'] for i in range(10)}
        self.assertEqual(len(prompts), 10)
        self.assertEqual(len(shot_skeleton.STRESS_VARIATIONS), 10)
        self.assertEqual(ctx_of(asset_task('CAST-01', 'stress', variation=13))['asset_panel_prompt'],
                         ctx_of(asset_task('CAST-01', 'stress', variation=3))['asset_panel_prompt'])
        prop = ctx_of(asset_task('PROP-01', 'stress', variation=1))['asset_panel_prompt']
        self.assertIn('The Burner is the object in image 1', prop)
        self.assertIn('An empty place with nobody in it.', prop)

    def test_a_variant_edits_its_base_panel(self):
        base_panels = {'face': ASSET(11), 'front': ASSET(12)}
        ctx = ctx_of(asset_task('CAST-01:WET', 'face', base_panels=base_panels, change='soaked hair, water running down the face'))
        self.assertEqual(plan_rows(ctx['reference_plan']), [('CAST-01', 'character_face', 'face', ASSET(11))])
        self.assertEqual(ctx['edit_prompt'],
                         'Edit image 1. CHANGE: soaked hair, water running down the face. PRESERVE EXACTLY: the face, hair, '
                         'body proportions, clothing not named above, the backdrop, the light direction, the colour and '
                         'grain. Only change what is named; everything else stays identical.')
        # Without a written change the description's "Changed:" is the change; a panel the base lacks edits its image.
        back = ctx_of(asset_task('CAST-01:WET', 'back', base_panels=base_panels))
        self.assertEqual(plan_rows(back['reference_plan']), [('CAST-01', 'character_body', 'reference', ASSET(1))])
        self.assertIn('CHANGE: soaked hair and a dripping jacket. PRESERVE', back['edit_prompt'])
        # Without base panels a variant row is generated like any asset.
        plain = ctx_of(asset_task('CAST-01:WET', 'face'))
        self.assertEqual((plain['reference_plan'], plain['edit_prompt']), ([], ''))
        self.assertTrue(plain['asset_panel_prompt'].startswith('Close-up studio photograph of Same identity as Noa: same face'))
        self.assertIn('soaked hair and a dripping jacket', ctx_of(asset_task('CAST-01:WET', 'front'))['asset_panel_prompt'])
        # In a shot, the variant's tag in its locked text is the base's name too.
        self.assertIn('Same identity as Noa', ctx_of(shot_task('@CAST-01:wet waits.'))['image_reference_prompt'])

    def test_keys_are_empty_where_they_do_not_apply(self):
        for task in (asset_task('CAST-01'), asset_task('CAST-01', 'sheet'), asset_task('CAST-01', 'portrait'),
                     {'input': {'prompt': 'An original empty observatory'}}):
            ctx = ctx_of(task)
            self.assertEqual({key: ctx[key] for key in NEW_KEYS if key not in ('video_skeleton_prompt',
                                                                               'image_reference_prompt')},
                             {'reference_plan': [], 'dropped_blocks': [], 'asset_panel_prompt': '', 'edit_prompt': ''})
        self.assertEqual(ctx_of(asset_task('CAST-01', 'face'))['video_skeleton_prompt'], '')


class CardContractTests(unittest.TestCase):
    """Package A's cards read these keys: the prompt their prompt_compile names, and the ref inputs in plan order."""
    ROOT = Path(__file__).resolve().parents[1]

    def form(self, card_id, task):
        card = worker.load_studio_card(self.ROOT / 'workflows' / 'cards' / (card_id + '.json'))
        ctx = ctx_of(task)
        values = worker._build_card_form_values(card, ctx, dict(card['engine_config']), task, None)
        refs = [values[f"{node['nodeId']}.{node['fieldName']}"] for node in card['nodes'] if node.get('slot') == 'ref']
        prompts = [values[f"{node['nodeId']}.{node['fieldName']}"] for node in card['nodes'] if node.get('slot') == 'prompt']
        return ctx, refs, prompts

    def test_the_reference_card_numbers_its_pictures_as_the_prompt_does(self):
        ctx, refs, prompts = self.form('flux-reference-key', shot_task('@CAST-01 opens @PROP-01 at @SET-01.', capability='image_gen'))
        self.assertEqual(refs[:len(ctx['reference_plan'])], [entry['url'] for entry in ctx['reference_plan']])
        self.assertTrue(all(ref == 'None' for ref in refs[len(ctx['reference_plan']):]))
        self.assertEqual(prompts, [ctx['image_reference_prompt']])
        # Front, back and stress panels render on the same card from their panel prompt.
        ctx, refs, prompts = self.form('flux-reference-key', asset_task('CAST-01', 'back'))
        self.assertEqual(refs[:2], [ASSET(11), 'None'])  # the back takes the face alone
        self.assertEqual(prompts, [ctx['asset_panel_prompt']])

    def test_the_video_and_edit_cards_and_a_plain_text_card(self):
        ctx, _, prompts = self.form('ltx25-cinema', shot_task('@CAST-01 at @SET-01. "Now."'))
        self.assertEqual(prompts, [ctx['video_skeleton_prompt']])
        ctx, refs, prompts = self.form('flux-klein-edit', asset_task('CAST-01:WET', 'face', base_panels={'face': ASSET(11)},
                                                                     change='soaked hair'))
        self.assertEqual((refs[0], prompts), (ASSET(11), [ctx['edit_prompt']]))
        # A shot on the soul-cast card has no panel prompt, so it keeps the compiled prompt.
        ctx, _, prompts = self.form('flux-soul-cast', shot_task('@CAST-01 waits.', capability='image_gen'))
        self.assertEqual(prompts, [ctx['compiled_prompt']])


class CompatibilityTests(unittest.TestCase):
    """The keys the compiler had stay as they were; the new module does no I/O."""

    def test_new_keys_are_only_additions(self):
        task = shot_task('[0-2s] @CAST-01 grips the valve of @PROP-01 at @SET-01. "Now."', look=LOOK)
        ctx = ctx_of(task)
        self.assertEqual(set(ctx) - NEW_KEYS, OLD_KEYS)
        self.assertTrue(NEW_KEYS <= set(ctx))
        bare = copy.deepcopy(task)
        del bare['input']['asset_meta']
        before = ctx_of(bare)
        self.assertEqual({k: v for k, v in ctx.items() if k not in NEW_KEYS}, {k: v for k, v in before.items() if k not in NEW_KEYS})
        for code, panel in (('CAST-01', 'front'), ('SET-01', 'reverse'), ('CAST-01', 'stress')):
            with_panel = ctx_of(asset_task(code, panel, stress_with=['CAST-02']))
            without = asset_task(code)
            del without['input']['asset_meta']
            plain = ctx_of(without)
            self.assertEqual({k: v for k, v in with_panel.items() if k not in NEW_KEYS},
                             {k: v for k, v in plain.items() if k not in NEW_KEYS})

    def test_the_source_is_never_changed(self):
        task = asset_task('CAST-01:WET', 'face', base_panels={'face': ASSET(11)})
        before = copy.deepcopy(task)
        ctx_of(task)
        shot = shot_task('@CAST-01 at @SET-01.', look=LOOK)
        shot_before = copy.deepcopy(shot)
        ctx_of(shot)
        self.assertEqual((task, shot), (before, shot_before))

    def test_malformed_asset_meta_is_refused(self):
        for meta in (['CAST-01'], {'CAST-01': 'acting'}):
            with self.subTest(meta=meta), self.assertRaisesRegex(worker.WorkerError, 'asset_meta'):
                ctx_of(shot_task('@CAST-01 waits.', meta=meta))

    def test_shot_skeleton_is_pure_text(self):
        tree = ast.parse(Path(shot_skeleton.__file__).read_text(encoding='utf-8'))
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertEqual(imported, {'__future__', 'os', 're'})
        self.assertNotIn('open(', Path(shot_skeleton.__file__).read_text(encoding='utf-8'))
        self.assertIs(context_compiler.shot_skeleton, shot_skeleton)


if __name__ == '__main__':
    unittest.main()
