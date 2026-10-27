"""Studio compiler, scoped media transport and real FFmpeg regression checks."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from project_assistant import limb_worker as worker
from project_docs import story_look

ROOT = Path(__file__).resolve().parents[1]
ASSET = lambda n: '/projects/api/demo/assets/pa_' + format(n, '032x')


def studio_task():
    headers = ['Shot', 'Optical Rig (Camera & Lens)', 'Camera Motion', 'Action & Audio Prompt', 'Keyframe', 'Cinema Shot', 'Notes']
    row = {'row_id': 'shot-2', 'tab_key': 'cinema-studio', 'table_id': 'shots',
           'cells': ['S02', 'ARRI / 35mm', 'Slow dolly', '@CAST-01 enters @SET-01. CAST-01 pauses.', ASSET(3), '', '']}
    return {'id': 'task', 'row_id': 'shot-2', 'project_slug': 'demo', 'input': {
        'prompt': 'Direct the shot', 'rows': [dict(row, row_id='shot-1', cells=['unrelated']), row],
        'target': {'tab_key': 'cinema-studio', 'table_id': 'shots'},
        'tabs': [{'tab_key': 'cinema-studio', 'text': 'unrelated tab text', 'tables': [{'table_id': 'shots', 'headers': headers}]},
                 {'tab_key': 'soul-cast', 'tables': [{'table_id': 'cast', 'headers': ['Asset ID', 'Name', 'Locked Appearance Prompt / Seed', 'Reference Image'],
                  'rows': [{'cells': ['CAST-01', 'Kael', 'original courier; seed 48291', ASSET(1)]},
                           {'cells': ['SET-01', 'Observatory', 'rain on glass', ASSET(2)]},
                           {'cells': ['PROP-09', 'Unrelated', 'do not bind', ASSET(99)]}]}]}],
        'predecessor_tasks': [{'row_id': 'shot-2', 'output': {'asset_url': ASSET(4)}},
                              {'row_id': 'shot-1', 'output': {'asset_url': ASSET(98)}}]}}


class MSFlowBridgeTests(unittest.TestCase):
    def test_msflow_command_or_builtin_solver_fallback(self):
        pins = [{'at': 0.45, 'joint': 'wristL', 'pos': [-0.25, 1.03, 0.56]}]
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('MSFLOW_ROOT', None)
            self.assertEqual(worker.build_msflow_command('He turns the dial.', pins, 6),
                             {'mode': 'builtin_xyz_solver', 'frames': 145, 'pins': pins})
        with tempfile.TemporaryDirectory() as root:
            run = worker.build_msflow_command('He turns the dial.', pins, msflow_root=root)
            self.assertEqual((run['mode'], run['cwd'], run['frames'], run['pins']), ('msflow', root, 97, pins))
            self.assertEqual(run['argv'][-3:], ['sample.demo_msflow_xyz', 'name=MMDiT_xyz_pretrained', 'input_text=He turns the dial.'])
        self.assertEqual(worker.build_msflow_command('x', msflow_root=str(ROOT / 'missing-msflow'))['mode'], 'builtin_xyz_solver')


class ContextTests(unittest.TestCase):
    def test_real_flow_rows_compile_mentions_and_seed_in_order_without_mutation(self):
        task = studio_task()
        before = copy.deepcopy(task)
        ctx = worker.resolve_studio_context(task)
        self.assertEqual(ctx['seed'], 48291)
        self.assertEqual([a['asset_id'] for a in ctx['resolved_assets']], ['CAST-01', 'SET-01'])
        self.assertEqual(ctx['reference_image_urls'], [ASSET(1), ASSET(2)])
        self.assertEqual(ctx['primary_image_url'], ASSET(3))
        prompt = ctx['compiled_prompt']
        self.assertLess(prompt.index('Optical Rig:'), prompt.index('Camera Movement:'))
        self.assertLess(prompt.index('Camera Movement:'), prompt.index('References:'))
        self.assertLess(prompt.index('References:'), prompt.index('@CAST-01 enters'))
        self.assertIn('CAST-01 (Kael): original courier; SET-01', prompt)
        self.assertNotIn('seed', prompt)  # a parameter, not words to draw
        self.assertNotIn('unrelated', prompt)
        self.assertEqual(task, before)
        task['input']['take'] = 2
        self.assertEqual(worker.resolve_studio_context(task)['seed'], 48293)
        task['capability'] = 'image_gen'  # a still keyframe has no camera move to render
        still = worker.resolve_studio_context(task)['compiled_prompt']
        self.assertNotIn('Camera Movement:', still)
        # Image models letter camera brands onto props; a still keeps only the lens look.
        self.assertTrue(still.startswith('Cinematic film still, 35mm lens look; no camera equipment or brand text in frame.'))
        self.assertNotIn('ARRI', still)

    def test_structured_rows_alias_video_column_and_zero_seed(self):
        task = studio_task()
        task['input']['structured_rows'] = task['input'].pop('rows')
        row = task['input']['structured_rows'][1]
        row['cells'] = ['VFX-02', 'Motion Transfer', ASSET(5), '@CAST-01 becomes a courier', ASSET(6)]
        task['input']['tabs'][0]['tables'][0]['headers'] = ['Clip', 'Jutsu Mode', 'Source Driving Video', 'Target Cast / Swap Prompt', 'Remastered Video']
        task['input']['tabs'][1]['tables'][0]['rows'][0]['cells'][2] = 'courier; seed:0'
        ctx = worker.resolve_studio_context(task)
        self.assertEqual(ctx['source_video_url'], ASSET(5))
        self.assertEqual(ctx['seed'], 0)
        self.assertIn('Mode: Motion Transfer.', ctx['compiled_prompt'])

    def test_missing_requested_row_never_falls_back_to_another_shot(self):
        task = studio_task()
        task['row_id'] = 'missing'
        with self.assertRaisesRegex(worker.WorkerError, 'row is missing'):
            worker.resolve_studio_context(task)

    def test_soul_cast_does_not_repeat_its_own_reference_prompt(self):
        task = studio_task()
        task['row_id'] = 'cast-row'
        task['input']['target'] = {'tab_key': 'soul-cast', 'table_id': 'cast'}
        task['input']['rows'] = [{'row_id': 'cast-row', 'tab_key': 'soul-cast', 'table_id': 'cast',
                                  'cells': ['CAST-01', 'Kael', 'original courier; seed 48291', ASSET(1)]}]
        ctx = worker.resolve_studio_context(task)
        # Reference framing comes from the asset kind, so the appearance lock stays shot-safe.
        self.assertEqual(ctx['compiled_prompt'], 'original courier. Character reference portrait, waist-up, neutral backdrop, soft key light.')
        self.assertNotIn('References:', ctx['compiled_prompt'])
        self.assertEqual(ctx['seed'], 48291)
        task['input']['rows'][0]['cells'] = ['SET-01', 'Observatory', 'rain on glass', ASSET(2)]
        self.assertEqual(worker.resolve_studio_context(task)['compiled_prompt'], 'rain on glass. Environment reference, wide, no people.')


class MoveTagContextTests(unittest.TestCase):
    """SPEC_19 R10: catalog #move tags expand where they stand and replace the Camera Motion column."""
    REFERENCES = 'References: CAST-01 (Kael): original courier; SET-01 (Observatory): rain on glass.'
    PUSH, STATIC = (story_look.option('move', key)['promptText'] for key in ('push-in', 'static'))

    def task(self, action, capability=None, optical=None):
        task = studio_task()
        cells = task['input']['rows'][1]['cells']
        cells[3] = action
        if optical is not None:
            cells[1] = optical
        if capability:
            task['capability'] = capability
        return task

    def test_tagged_prompt_expands_in_place_and_drops_the_camera_movement_line(self):
        action = '[0-2s] @CAST-01 enters @SET-01. #push-in\n[2-4s] CAST-01 pauses at the dial. #static'
        ctx = worker.resolve_studio_context(self.task(action))
        expanded = f'[0-2s] @CAST-01 enters @SET-01. {self.PUSH}\n[2-4s] CAST-01 pauses at the dial. {self.STATIC}'
        self.assertEqual(ctx['compiled_prompt'], f'Optical Rig: ARRI / 35mm.\n{self.REFERENCES}\n{expanded}')
        self.assertNotIn('Camera Movement:', ctx['compiled_prompt'])
        self.assertNotIn('Slow dolly', ctx['compiled_prompt'])
        self.assertEqual((ctx['action_prompt'], ctx['camera_motion'], ctx['optical_rig']), (expanded, '', 'ARRI / 35mm'))
        self.assertEqual(ctx['camera_moves'], ['push-in', 'static'])  # the prompt preview's look.moves, in prompt order
        # The H3 path reads the same expanded action and no longer prefixes the column's move.
        self.assertIn('[Shot 1] At 00:00.000, ARRI / 35mm: [0-2s] <Subject 1> (Kael) enters <Subject 2> (Observatory). '
                      + self.PUSH, ctx['h3_context_ir_prompt'])
        self.assertNotIn('Slow dolly', ctx['h3_context_ir_prompt'])
        self.assertNotIn('#', ctx['h3_context_ir_prompt'] + ctx['ltx_ingredients_prompt'])
        self.assertEqual([a['asset_id'] for a in ctx['resolved_assets']], ['CAST-01', 'SET-01'])

    def test_untagged_prompts_keep_the_camera_motion_column_word_for_word(self):
        ctx = worker.resolve_studio_context(studio_task())
        self.assertEqual(ctx['compiled_prompt'], 'Optical Rig: ARRI / 35mm.\nCamera Movement: Slow dolly.\n'
                         f'{self.REFERENCES}\n@CAST-01 enters @SET-01. CAST-01 pauses.')
        self.assertEqual(ctx['camera_motion'], 'Slow dolly')
        # Wardrobe variants, unknown #words and tags glued to text are not moves: kept as written.
        action = '@CAST-01#night enters @SET-01. 他轉身#push-in #foo'
        ctx = worker.resolve_studio_context(self.task(action))
        self.assertEqual(ctx['compiled_prompt'], 'Optical Rig: ARRI / 35mm.\nCamera Movement: Slow dolly.\n'
                         'References: CAST-01:NIGHT (Kael): original courier; SET-01 (Observatory): rain on glass.\n' + action)
        self.assertEqual((ctx['action_prompt'], ctx['camera_motion'], ctx['camera_moves']), (action, 'Slow dolly', []))

    def test_a_still_gets_no_camera_move_from_tags_or_the_column(self):
        action = '#push-in @CAST-01 enters @SET-01. #whip-pan CAST-01 pauses. #foo'
        ctx = worker.resolve_studio_context(self.task(action, 'image_gen'))
        self.assertEqual(ctx['compiled_prompt'],
                         'Cinematic film still, 35mm lens look; no camera equipment or brand text in frame.\n'
                         f'{self.REFERENCES}\n@CAST-01 enters @SET-01. CAST-01 pauses. #foo')
        moves = [story_look.option('move', key)['promptText'] for key in ('push-in', 'whip-pan')]
        self.assertFalse(any(move in ctx['compiled_prompt'] for move in moves))
        self.assertEqual(ctx['camera_moves'], ['push-in', 'whip-pan'])  # read, though a still sends none of them
        self.assertEqual(worker.resolve_studio_context(self.task('#push-in', 'video_gen'))['action_prompt'], self.PUSH)

    def test_catalog_optical_rig_text_reaches_video_and_still_whole_and_brand_free(self):
        rig = story_look.camera_text('film-16mm', 'vintage-anamorphic', 'f1-4')
        cast = 'References: CAST-01 (Kael): original courier.'
        video = worker.resolve_studio_context(self.task('#static @CAST-01 waits.', optical=rig))['compiled_prompt']
        self.assertEqual(video, f'Optical Rig: {rig}\n{cast}\n{self.STATIC} @CAST-01 waits.')
        still = worker.resolve_studio_context(self.task('#static @CAST-01 waits.', 'image_gen', optical=rig))['compiled_prompt']
        # No "/" in catalog text, so the still keeps the whole description, never a fragment of it.
        self.assertEqual(still, f'Cinematic film still, {rig.rstrip(".")} lens look; no camera equipment or brand text in frame.\n'
                                f'{cast}\n@CAST-01 waits.')


class TakeRefContextTests(unittest.TestCase):
    """SPEC_19 R15 (D3): a quoted take's frame is this render's first frame or its last reference picture, and its tag
    becomes a sentence where it stands."""
    FIRST = {'shotIndex': 'S01', 'edge': 'end', 'use': 'first_frame', 'frameUrl': ASSET(50)}
    MATCH = {'shotIndex': 'S03', 'edge': 'start', 'use': 'reference', 'frameUrl': ASSET(51)}
    REFERENCES = 'References: CAST-01 (Kael): original courier; SET-01 (Observatory): rain on glass.'

    def task(self, action, refs, keyframe=ASSET(3)):
        task = studio_task()
        cells = task['input']['rows'][1]['cells']
        cells[3], cells[4] = action, keyframe
        task['input']['take_refs'] = refs
        return task

    def card(self, card_id):
        return worker.load_studio_card(ROOT / 'workflows' / 'cards' / (card_id + '.json'))

    def test_a_first_frame_take_replaces_the_shots_first_frame_and_keyframe(self):
        task = self.task('@S01.end @CAST-01 turns to the window in @SET-01.', [self.FIRST])
        task['input']['predecessor_tasks'].append({'row_id': 'shot-2', 'output': {'asset_url': ASSET(7), 'reference_role': 'first_frame'}})
        ctx = worker.resolve_studio_context(task)
        self.assertEqual((ctx['first_frame'], ctx['anchor_keyframe'], ctx['primary_image_url']), (ASSET(50),) * 3)
        # The cast and set references are unchanged; the frame is not a reference picture.
        self.assertEqual(ctx['asset_images'], [ASSET(1), ASSET(2)])
        self.assertEqual([a['asset_id'] for a in ctx['resolved_assets']], ['CAST-01', 'SET-01'])
        # The image-to-video card's picture input is the quoted frame, not the row's keyframe (ASSET 3).
        card = self.card('ltx25-cinema')
        values = worker._build_card_form_values(card, ctx, dict(card['engine_config']), task, None)
        self.assertEqual(values['2.image'], ASSET(50))
        # Without a quoted take the row's own keyframe stays the picture.
        plain = worker.resolve_studio_context(self.task('@CAST-01 turns.', []))
        self.assertEqual(plain['anchor_keyframe'], ASSET(3))

    def test_a_reference_take_comes_after_the_cast_and_sets(self):
        task = self.task('@CAST-01 enters @SET-01. @S03.start', [self.MATCH], keyframe='')
        ctx = worker.resolve_studio_context(task)
        self.assertEqual(ctx['asset_images'], [ASSET(1), ASSET(2), ASSET(51)])
        self.assertEqual(ctx['reference_image_urls'], ctx['asset_images'])
        self.assertIsNone(ctx['first_frame'])
        self.assertEqual([a and a['asset_id'] for a in ctx['slot_plan']], ['CAST-01', 'SET-01', 'S03.START', None, None, None])
        self.assertEqual(ctx['resolved_assets'][-1]['reference_urls'], [ASSET(51)])
        # It fills the next reference slot of a multi-reference card, after the subjects.
        card = self.card('h3-reference')
        values = worker._build_card_form_values(card, ctx, dict(card['engine_config']), task, None)
        refs = [values[f"{n['nodeId']}.{n['fieldName']}"] for n in card['nodes'] if n.get('slot') == 'ref']
        self.assertEqual(refs, [ASSET(1), ASSET(2), ASSET(51), 'None', 'None', 'None'])
        # The frame is not a subject: the compiled texts never name it.
        self.assertNotIn('S03.START', ctx['compiled_prompt'] + ctx['h3_context_ir_prompt'] + ctx['ltx_ingredients_prompt'])
        self.assertIn('References: CAST-01 (Kael)', ctx['compiled_prompt'])

    def test_the_sentence_takes_the_tags_place(self):
        action = '[0-1s] @S01.end @CAST-01 turns to the window of @SET-01.\n[1-3s] @s03.start. CAST-01 walks to the dial. @S09.end stays.'
        ctx = worker.resolve_studio_context(self.task(action, [self.FIRST, self.MATCH]))
        expanded = ('[0-1s] Continue directly from the final frame of shot S01. @CAST-01 turns to the window of @SET-01.\n'
                    '[1-3s] Match the setting and lighting of shot S03. CAST-01 walks to the dial. @S09.end stays.')
        self.assertEqual(ctx['action_prompt'], expanded)
        self.assertEqual(ctx['compiled_prompt'], f'Optical Rig: ARRI / 35mm.\nCamera Movement: Slow dolly.\n{self.REFERENCES}\n{expanded}')
        self.assertIn('[Shot 1] At 00:00.000, ARRI / 35mm Slow dolly: [0-1s] Continue directly from the final frame of shot S01. '
                      '<Subject 1> (Kael) turns', ctx['h3_context_ir_prompt'])
        # Asset codes stay asset codes next to a quoted take.
        self.assertEqual([a['asset_id'] for a in ctx['resolved_assets']], ['CAST-01', 'SET-01', 'S03.START'])

    def test_storyboard_labels_are_quoted_and_asset_codes_with_an_edge_stay_asset_codes(self):
        built = {'shotIndex': 'SC01-S02', 'edge': 'end', 'use': 'first_frame', 'frameUrl': ASSET(50)}
        ctx = worker.resolve_studio_context(self.task('@sc01-s02.end @CAST-01 turns in @SET-01. @CAST-01.end stays.', [built]))
        self.assertEqual(ctx['action_prompt'],
                         'Continue directly from the final frame of shot SC01-S02. @CAST-01 turns in @SET-01. @CAST-01.end stays.')
        self.assertEqual((ctx['first_frame'], ctx['anchor_keyframe']), (ASSET(50), ASSET(50)))
        self.assertEqual([a['asset_id'] for a in ctx['resolved_assets']], ['CAST-01', 'SET-01'])

    def test_take_refs_must_be_prepared_frames_of_this_kind(self):
        for refs in ([{**self.FIRST, 'frameUrl': 'https://example.com/frame.png'}], [{**self.FIRST, 'use': 'driving_video'}],
                     [self.FIRST, {**self.FIRST, 'frameUrl': ASSET(52)}]):
            with self.subTest(refs=refs), self.assertRaises(worker.WorkerError):
                worker.resolve_studio_context(self.task('@S01.end', refs))


class ComfyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workflow = Path(self.temp.name) / 'workflow.json'
        self.graph = {str(i): {'class_type': 'Test', 'inputs': {}} for i in range(1, 13)}
        self.workflow.write_text(json.dumps(self.graph))
        self.config = {'workflow': str(self.workflow), 'platform': 'local', 'base_url': 'http://comfy.test', 'prompt_node': '6', 'seed_node': '3', 'output_node': '12', 'poll_seconds': 0}
        self.task = studio_task()
        self.head = Mock()
        self.head.lease_lost.return_value = False
        self.head.asset.side_effect = lambda task, url: (url.encode(), 'video/mp4' if url in (ASSET(5), ASSET(6)) else 'image/png')
        self.head.upload.side_effect = lambda task, raw, mime: {'asset_url': 'saved', 'content_type': mime}

    def test_comfy_binds_video_reference_parameters_and_preserves_zero(self):
        self.task['input']['rows'][1]['cells'] += [ASSET(5)]
        config = dict(self.config, video_node='1', reference_image_node='2', seed=0,
                      param_bindings={'3.cfg': 0, '6.camera': 'camera_motion', '6.empty': 'jutsu_mode'})
        with patch.object(worker, 'ComfyPlatformClient') as factory:
            client = factory.return_value
            client.upload_media.side_effect = lambda raw, mime, prefix: prefix + ('.mp4' if mime.startswith('video') else '.png')
            client.submit_workflow.return_value = 'job'
            client.fetch_history.return_value = {'job': {'outputs': {'12': {'images': [{'filename': 'cover.png'}, {'filename': 'result.mp4'}]}}}}
            client.download_output.return_value = (b'movie', 'video/mp4')
            result = worker.comfyui(self.task, config, self.head)
            graph = client.submit_workflow.call_args.args[0]
            self.assertEqual(graph['1']['inputs']['video'], 'source_video.mp4')
            self.assertEqual(graph['2']['inputs']['image'], 'reference.png')
            self.assertEqual(graph['3']['inputs']['seed'], 0)
            self.assertEqual(graph['3']['inputs']['cfg'], 0)
            self.assertEqual(graph['6']['inputs']['camera'], 'Slow dolly')
            self.assertNotIn('empty', graph['6']['inputs'])
            self.assertEqual(client.download_output.call_args.args[0]['filename'], 'result.mp4')
            self.assertEqual(result['content_type'], 'video/mp4')
            client.close.assert_called_once()
        urls = [call.args[1] for call in self.head.asset.call_args_list]
        self.assertNotIn(ASSET(99), urls)
        self.assertNotIn(ASSET(98), urls)

    def test_missing_reference_never_uses_unmentioned_asset(self):
        self.task['input']['rows'][1]['cells'][3] = 'No mentions'
        with patch.object(worker, 'ComfyPlatformClient'), self.assertRaisesRegex(worker.WorkerError, 'reference_image_node needs'):
            worker.comfyui(self.task, dict(self.config, reference_image_node='2'), self.head)
        self.head.asset.assert_not_called()

    def test_local_transport_upload_and_bearer_auth(self):
        with patch.dict(os.environ, {'STUDIO_TEST_KEY': 'secret'}, clear=True), patch.object(worker, 'json_fetch') as request:
            request.side_effect = [{'name': 'video.mp4', 'subfolder': 'input'}, {'prompt_id': 'job'}, {'job': {}}]
            client = worker.ComfyPlatformClient({'platform': 'local', 'base_url': 'https://comfy.test', 'api_key_env': 'STUDIO_TEST_KEY'})
            self.assertEqual(client.upload_media(b'movie', 'video/mp4', 'source_video'), 'input/video.mp4')
            self.assertEqual(client.submit_workflow({}, 'task'), 'job')
            client.fetch_history('job')
            for call in request.call_args_list:
                self.assertEqual(call.kwargs['token'], 'secret')
            self.assertIn('name="image"', request.call_args_list[0].kwargs['data'].decode())
            self.assertIn('video/mp4', request.call_args_list[0].kwargs['data'].decode())

    def test_official_sdk_uses_assets_jobs_and_bounded_streaming(self):
        sdk = Mock()
        output = types.SimpleNamespace(node_id='12', name='take.mp4', content_type='video/mp4', to_stream=lambda stream: stream.write(b'movie'))
        sdk.submit.return_value.id = 'sdk-job'
        sdk.jobs.get.return_value = types.SimpleNamespace(status='succeeded', outputs=[output])
        comfy = Mock(return_value=sdk)
        with patch.dict('sys.modules', {'comfy_sdk': types.SimpleNamespace(Comfy=comfy)}), patch.dict(os.environ, {}, clear=True):
            client = worker.ComfyPlatformClient({'platform': 'comfy_sdk', 'base_url': 'https://deployment.test'})
            self.assertNotIn('COMFY_BASE_URL', os.environ)
            client.upload_media(b'image', 'image/png')
            sdk.assets.from_bytes.assert_called_once()
            self.assertEqual(client.submit_workflow({'6': {'inputs': {}}}, 'task'), 'sdk-job')
            item = client.fetch_history('sdk-job')['sdk-job']['outputs']['12']['media'][0]
            self.assertEqual(client.download_output(item), (b'movie', 'video/mp4'))
            client.close()
            sdk.close.assert_called_once()
            comfy.assert_called_once_with(api_key=None, timeout=60, client_info='zerofield-studio')

    def test_sdk_without_a_key_targets_the_self_hosted_proxy(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(worker.comfy_base_url({}, 'comfy_sdk'), 'http://127.0.0.1:8189')  # comfy-api-proxy before local ComfyUI
            self.assertEqual(worker.comfy_base_url({}, 'local'), 'http://127.0.0.1:8188')
            self.assertEqual(worker.comfy_base_url({'base_url': 'https://deployment.test/'}, 'comfy_sdk'), 'https://deployment.test')
        with patch.dict(os.environ, {'COMFY_API_KEY': 'key'}, clear=True):
            self.assertEqual(worker.comfy_base_url({}, 'comfy_sdk'), 'https://cloud.comfy.org')
        with patch.dict(os.environ, {'COMFY_BASE_URL': 'http://127.0.0.1:9000'}, clear=True):
            self.assertEqual(worker.comfy_base_url({}, 'comfy_sdk'), 'http://127.0.0.1:9000')

    def test_sdk_output_stream_enforces_media_limit(self):
        output = types.SimpleNamespace(content_type='video/mp4', name='take.mp4', to_stream=lambda stream: stream.write(b'12345'))
        client = object.__new__(worker.ComfyPlatformClient)
        with patch.object(worker, 'MAX_MEDIA', 4), self.assertRaisesRegex(worker.WorkerError, 'exceeds 64 MB'):
            client.download_output({'sdk_output': output})

    def test_missing_video_never_uses_other_rows(self):
        with patch.object(worker, 'ComfyPlatformClient'), self.assertRaisesRegex(worker.WorkerError, 'video_node needs'):
            worker.comfyui(self.task, dict(self.config, video_node='1'), self.head)
        self.assertNotIn(ASSET(98), [c.args[1] for c in self.head.asset.call_args_list])
        self.assertNotIn(ASSET(99), [c.args[1] for c in self.head.asset.call_args_list])


    def test_comfy_accepts_only_universal_bindings_and_tags_video_output(self):
        graph = {'custom': {'class_type': 'External', 'inputs': {'message': ''}}, 'save': {'class_type': 'ExternalSave', 'inputs': {}}}
        self.workflow.write_text(json.dumps(graph))
        config = {'workflow': str(self.workflow), 'platform': 'local', 'input_bindings': {'custom.message': 'compiled_prompt'}, 'output_node': 'save'}
        self.task['capability'] = 'video_gen'
        with patch.object(worker, 'ComfyPlatformClient') as factory:
            client = factory.return_value
            client.submit_workflow.return_value = 'job'
            client.fetch_history.return_value = {'job': {'outputs': {'save': {'videos': [{'filename': 'take.mp4'}]}}}}
            client.download_output.return_value = (b'video', 'video/mp4')
            result = worker.comfyui(self.task, config, self.head)
            submitted = client.submit_workflow.call_args.args[0]
            self.assertIn('Optical Rig:', submitted['custom']['inputs']['message'])
            self.assertEqual(result['reference_role'], 'output_video')

    def test_router_workflow_misconfiguration_fails_before_network(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(worker.WorkerError, 'Router does not execute'):
            worker.ComfyPlatformClient({'platform': 'comfy_router', 'router_url': 'https://api.comfy.org'})


class WorkflowTests(unittest.TestCase):
    def test_graphs_have_bound_nodes_existing_links_and_open_model_loaders(self):
        for name, output in [('flux3_klein_soul_cast.json', '9'), ('ltx25_cinema_shot.json', '12'),
                             ('ltx25_openjutsu_v2v.json', '12'), ('local_smoke_sdxl_lightning.json', '9')]:
            with self.subTest(workflow=name):
                graph = json.loads((ROOT / 'workflows' / name).read_text())
                self.assertIn(output, graph)
                self.assertEqual(graph['6']['class_type'], 'CLIPTextEncode')
                self.assertEqual(graph['3']['class_type'], 'KSampler')
                self.assertFalse(any('api_key' in str(n).lower() or 'partner' in n['class_type'].lower() for n in graph.values()))
                for node in graph.values():
                    for value in node['inputs'].values():
                        if isinstance(value, list) and len(value) == 2 and isinstance(value[1], int):
                            self.assertIn(value[0], graph)
                    if node['class_type'] == 'SaveVideo':  # ComfyUI 0.42 API form; nested dicts fail at save
                        self.assertEqual((node['inputs']['format'], node['inputs']['codec']), ('mp4', 'h264'))
        h3 = json.loads((ROOT / 'workflows/minimax_h3_ref2va.json').read_text())
        self.assertIn('12', h3)
        self.assertEqual(h3['200']['class_type'], 'MiniMaxH3ReferenceToVideo')
        for node in h3.values():
            for value in node['inputs'].values():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[1], int):
                    self.assertIn(value[0], h3)
        v2v = json.loads((ROOT / 'workflows/ltx25_openjutsu_v2v.json').read_text())
        self.assertEqual(v2v['1']['class_type'], 'VHS_LoadVideo')
        self.assertEqual(v2v['1']['inputs']['frame_load_cap'], 97)
        self.assertEqual(v2v['4']['class_type'], 'VHS_LoadVideo')
        self.assertEqual(v2v['11']['inputs']['audio'], ['1', 2])
        self.assertIn('LTXVAddGuide', {n['class_type'] for n in v2v.values()})


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and FFprobe are required')
class ComparisonTests(unittest.TestCase):
    def test_real_comparison_dimensions_colors_right_audio_and_faststart(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder) / name for name in ('left.mp4', 'right.mp4', 'out.mp4')]
            for path, color, frequency in zip(paths[:2], ['red', 'blue'], [220, 880]):
                subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', f'color=c={color}:s=64x64:r=12:d=0.5',
                                '-f', 'lavfi', '-i', f'sine=frequency={frequency}:duration=0.5', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(path)], check=True, capture_output=True)
            worker.assemble_side_by_side(*paths, {'width': 128, 'height': 64, 'fps': 12})
            metadata = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(paths[2])]))
            video = next(s for s in metadata['streams'] if s['codec_type'] == 'video')
            self.assertEqual((video['width'], video['height']), (128, 64))
            self.assertTrue(any(s['codec_type'] == 'audio' for s in metadata['streams']))
            raw = paths[2].read_bytes()
            self.assertLess(raw.index(b'moov'), raw.index(b'mdat'))
            pixels = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(paths[2]), '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
            left = pixels[(32 * 128 + 32) * 3:(32 * 128 + 32) * 3 + 3]
            right = pixels[(32 * 128 + 96) * 3:(32 * 128 + 96) * 3 + 3]
            self.assertGreater(left[0], left[2] + 100)
            self.assertGreater(right[2], right[0] + 100)
            # Zero crossings distinguish the right clip's 880Hz from left's 220Hz.
            import array
            pcm = array.array('h', subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(paths[2]), '-vn', '-ac', '1', '-ar', '8000', '-f', 's16le', '-']))
            crosses = sum(a <= 0 < b for a, b in zip(pcm, pcm[1:]))
            frequency = crosses / (len(pcm) / 8000)
            self.assertGreater(frequency, 700)

    def test_ffmpeg_adapter_uses_active_source_then_latest_predecessor(self):
        task = studio_task()
        task['input']['rows'][1]['cells'] = [ASSET(5), ASSET(6)]
        task['input']['tabs'][0]['tables'][0]['headers'] = ['Source Driving Video', 'Remastered Video']
        task['input']['predecessor_tasks'][0]['output'] = {'asset_url': ASSET(7), 'reference_role': 'output_video', 'content_type': 'video/mp4'}
        head = Mock()
        head.lease_lost.return_value = False
        head.asset.return_value = (b'video', 'video/mp4')
        def assemble(left, right, destination, config):
            self.assertEqual(left.read_bytes(), b'video')
            destination.write_bytes(b'comparison')
        with patch.object(worker, 'assemble_side_by_side', side_effect=assemble):
            worker.ffmpeg(task, {'layout': 'side_by_side'}, head)
        self.assertEqual([c.args[1] for c in head.asset.call_args_list], [ASSET(5), ASSET(7)])
        head.upload.assert_called_once_with(task, b'comparison', 'video/mp4')


class ReferencePackBindingTests(unittest.TestCase):
    def test_semantic_pack_and_same_row_role_predecessors(self):
        task = studio_task()
        task['input']['rows'][1]['cells'] = [ASSET(5), ASSET(3), ASSET(6), ASSET(4), ASSET(7), '@CAST-01 @SET-01']
        task['input']['tabs'][0]['tables'][0]['headers'] = ['Source Video', 'First Frame', 'Motion Structure', 'Anchor Keyframe', 'Remastered Video', 'Action Prompt']
        task['input']['predecessor_tasks'] = [
            {'row_id': 'shot-2', 'output': {'asset_url': ASSET(8), 'content_type': 'image/png', 'reference_role': 'first_frame'}},
            {'row_id': 'shot-1', 'output': {'asset_url': ASSET(99), 'reference_role': 'anchor_keyframe'}}]
        ctx = worker.resolve_studio_context(task)
        self.assertEqual(ctx['source_video'], ASSET(5))
        self.assertEqual(ctx['source_video_url'], ASSET(5))
        self.assertEqual(ctx['first_frame'], ASSET(8))
        self.assertEqual(ctx['motion_structure_video'], ASSET(6))
        self.assertEqual(ctx['anchor_keyframe'], ASSET(4))
        self.assertEqual(ctx['output_video'], ASSET(7))
        self.assertEqual(ctx['primary_image_url'], ASSET(4))
        self.assertEqual(ctx['asset_images'], [ASSET(1), ASSET(2)])
        self.assertEqual(ctx['asset_map']['CAST-01']['url'], ASSET(1))

    def test_universal_bindings_both_directions_arbitrary_slots_and_dotpaths(self):
        ctx = {'anchor_keyframe': ASSET(1), 'source_video': ASSET(5), 'motion_structure_video': ASSET(6),
               'first_frame': None, 'asset_images': [ASSET(2)], 'asset_map': {'CAST-01': {'url': ASSET(2)}}, 'compiled_prompt': 'Optical Rig: 35mm.', 'seed': 0}
        graph = {name: {'class_type': 'ExternalBlackBox', 'inputs': {'keep': 'default'}} for name in ('alpha', 'beta', 'gamma')}
        config = {'input_bindings': {
            'anchor_keyframe': {'node': 'alpha', 'input': 'photo', 'upload': 'image'},
            'source_video': {'node': 'alpha', 'input': 'clip', 'upload': 'video'},
            'motion_structure_video': {'node': 'beta', 'input': 'control', 'upload': 'video'},
            'asset_map.CAST-01.url': {'node': 'beta', 'input': 'face', 'upload': 'image'},
            'beta.duplicate': 'asset_images.0',
            'gamma.prompt': 'compiled_prompt', 'gamma.seed': 'seed', 'gamma.gain': 0,
            'first_frame': {'node': 'gamma', 'input': 'keep', 'upload': 'image', 'optional': True}}}
        head, client = Mock(), Mock()
        head.asset.side_effect = lambda task, url: (url.encode(), 'video/mp4' if url in (ASSET(5), ASSET(6)) else 'image/png')
        client.upload_media.side_effect = lambda raw, mime, prefix: raw.decode().rsplit('/', 1)[-1] + '.uploaded'
        worker.bind_external_workflow(graph, ctx, config, studio_task(), head, client)
        self.assertEqual(graph['alpha']['inputs']['photo'], ASSET(1).rsplit('/', 1)[-1] + '.uploaded')
        self.assertEqual(graph['beta']['inputs']['duplicate'], graph['beta']['inputs']['face'])
        self.assertEqual(client.upload_media.call_count, 4)
        self.assertEqual(graph['gamma']['inputs'], {'keep': 'default', 'prompt': 'Optical Rig: 35mm.', 'seed': 0, 'gain': 0})

    def test_required_missing_asset_and_mime_mismatch_fail(self):
        graph = {'x': {'inputs': {'image': 'default'}}}
        head, client = Mock(), Mock()
        config = {'input_bindings': {'first_frame': {'node': 'x', 'input': 'image', 'upload': 'image'}}}
        with self.assertRaisesRegex(worker.WorkerError, 'needs an input image'):
            worker.bind_external_workflow(graph, {'first_frame': None}, config, studio_task(), head, client)
        head.asset.return_value = (b'video', 'video/mp4')
        with self.assertRaisesRegex(worker.WorkerError, 'MIME'):
            worker.bind_external_workflow(graph, {'first_frame': ASSET(5)}, config, studio_task(), head, client)
        client.upload_media.assert_not_called()

    def test_legacy_first_frame_structure_and_literal_bindings(self):
        graph = {'a': {'inputs': {}}, 'b': {'inputs': {}}}
        ctx = {'first_frame': ASSET(1), 'motion_structure_video': ASSET(5)}
        head, client = Mock(), Mock()
        head.asset.side_effect = lambda task, url: (b'bytes', 'image/png' if url == ASSET(1) else 'video/mp4')
        client.upload_media.side_effect = lambda raw, mime, prefix: 'frame.png' if mime.startswith('image/') else 'edges.mp4'
        worker.bind_external_workflow(graph, ctx, {'first_frame_node': 'a', 'structure_video_node': 'b',
            'param_bindings': {'b.rate': 24}, 'input_bindings': {'a.custom': {'literal': {'enabled': True}}}}, studio_task(), head, client)
        self.assertEqual(graph['a']['inputs'], {'image': 'frame.png', 'custom': {'enabled': True}})
        self.assertEqual(graph['b']['inputs'], {'video': 'edges.mp4', 'rate': 24})


class PrevisTwoPassTests(unittest.TestCase):
    def test_previs_column_and_built_in_two_pass_bindings(self):
        import run_studio
        task = studio_task()
        task['input']['tabs'][0]['tables'][0]['headers'].append('Previs')
        task['input']['rows'][1]['cells'].append(ASSET(9))
        self.assertEqual(worker.resolve_studio_context(task)['previs_video'], ASSET(9))
        cfg = run_studio.worker_configs('http://127.0.0.1:8188')
        head, client = Mock(), Mock()
        head.asset.side_effect = lambda task, url: (b'x', 'video/mp4' if url in (ASSET(7), ASSET(9)) else 'image/png')
        client.upload_media.side_effect = lambda raw, mime, prefix: prefix + '.bin'
        load = lambda stage, cap: json.loads(Path(cfg[stage][cap]['workflow']).read_text(encoding='utf-8'))
        motion = load('motion', 'video_gen')
        worker.bind_external_workflow(motion, {'previs_video': ASSET(9), 'compiled_prompt': 'beats', 'seed': 3},
                                      cfg['motion']['video_gen'], task, head, client)
        self.assertEqual((motion['20']['inputs']['video'], motion['30']['inputs']['string_a'], motion['3']['inputs']['denoise']),
                         ('source_video.bin', 'beats', 0.75))
        # Shots up to 8 s (193 frames) load whole and decode in 64-frame chunks, so a long clip never stalls in the VAE.
        for graph in (motion, load('look', 'video_gen')):
            self.assertEqual((graph['20']['inputs']['frame_load_cap'], graph['21']['class_type'], graph['8']['class_type'], graph['8']['inputs']['temporal_size']),
                             (193, 'VAEEncodeTiled', 'VAEDecodeTiled', 64))
        self.assertEqual(load('lookkey', 'image_gen')['20']['inputs']['frame_load_cap'], 193)  # the key is the last frame of the whole shot
        # Shot beats land before the fixed live-action look lock that the encoder reads (cfg 1 ignores negatives).
        self.assertEqual(motion['6']['inputs']['text'], ['30', 0])
        self.assertIn('live-action', motion['30']['inputs']['string_b'])
        key = load('lookkey', 'image_gen'); instruction = key['6']['inputs']['text']
        worker.bind_external_workflow(key, {'output_video': ASSET(7), 'asset_images': [ASSET(1)], 'compiled_prompt': 'beats', 'seed': 5},
                                      cfg['lookkey']['image_gen'], task, head, client)
        # Only a cast reference: the empty set slot loses its loader instead of loading a placeholder file.
        self.assertNotIn('22', key)
        self.assertNotIn('images.image2', key['11']['inputs'])
        self.assertEqual(key['6']['inputs']['text'], instruction)  # the edit instruction is not replaced by shot text
        look = load('look', 'video_gen')
        worker.bind_external_workflow(look, {'output_video': ASSET(7), 'anchor_keyframe': ASSET(4), 'compiled_prompt': 'beats', 'seed': 3},
                                      cfg['look']['video_gen'], task, head, client)
        self.assertEqual((look['20']['inputs']['video'], look['2']['inputs']['image'], look['3']['inputs']['denoise']),
                         ('source_video.bin', 'input.bin', 0.5))

    def test_openjutsu_swap_bindings_key_the_first_frame_and_composite_over_the_source(self):
        import run_studio
        cfg = run_studio.worker_configs('http://127.0.0.1:8188')
        head, client = Mock(), Mock()
        head.asset.side_effect = lambda task, url: (url.encode(), 'video/mp4' if url == ASSET(5) else 'image/png')
        client.upload_media.side_effect = lambda raw, mime, prefix: raw.decode().rsplit('_', 1)[-1][-2:] + '.' + prefix
        load = lambda stage, cap: json.loads(Path(cfg[stage][cap]['workflow']).read_text(encoding='utf-8'))
        key = load('swapkey', 'image_gen')
        worker.bind_external_workflow(key, {'source_video': ASSET(5), 'asset_images': [ASSET(1)], 'compiled_prompt': 'swap', 'seed': 5},
                                      cfg['swapkey']['image_gen'], studio_task(), head, client)
        # Klein edits frame 0 of the source (not the last frame like the look key), with the cast reference only.
        self.assertEqual((key['20']['inputs']['video'], key['23']['inputs']['batch_index'], key['21']['inputs']['image']),
                         ('05.source_video', 0, '01.reference'))
        self.assertNotIn('22', key)
        self.assertEqual(cfg['swapkey']['image_gen']['reference_role'], 'anchor_keyframe')  # the swap step reads it as its anchor
        swap = load('swap', 'video_gen')
        client.upload_media.reset_mock()
        worker.bind_external_workflow(swap, {'source_video': ASSET(5), 'anchor_keyframe': ASSET(4), 'compiled_prompt': 'Mode: Object Swap.', 'seed': 7},
                                      cfg['swap']['video_gen'], studio_task(), head, client)
        # One upload feeds the LTX-size loader and the native-size composite plate; the native one loads the same frame count.
        self.assertEqual((swap['20']['inputs']['video'], swap['25']['inputs']['video'], client.upload_media.call_count), ('05.source_video', '05.source_video', 2))
        self.assertEqual(swap['25']['inputs']['frame_load_cap'], ['20', 1])
        self.assertEqual((swap['2']['inputs']['image'], swap['6']['inputs']['text'], swap['3']['inputs']['seed']), ('04.input', 'Mode: Object Swap.', 7))
        # Alpha-Gen per its model card: LoRA and reference at strength 1, empty prompt, IC-LoRA parameters on the guide.
        self.assertEqual((swap['40']['inputs']['lora_name'], swap['40']['inputs']['strength_model'], swap['45']['inputs']['strength']),
                         ('ltx-2.5-22b-ic-lora-alpha-gen-0.9.safetensors', 1.0, 1.0))
        self.assertEqual((swap['42']['inputs']['text'], swap['45']['inputs']['image'], swap['45']['inputs']['iclora_parameters']), ('', ['20', 0], ['41', 0]))
        # Regenerated frames go only inside the grown, feathered matte, over the native source, with the source audio.
        self.assertEqual({k: swap['60']['inputs'][k] for k in ('destination', 'source', 'mask', 'resize_source')},
                         {'destination': ['25', 0], 'source': ['8', 0], 'mask': ['62', 0], 'resize_source': True})
        self.assertEqual((swap['56']['class_type'], swap['58']['class_type'], swap['11']['inputs']['audio']), ('GrowMask', 'ImageBlur', ['25', 2]))
        # The matte's near-zero VAE noise is gated to exactly 0, so the source outside it is copied bit for bit.
        self.assertEqual((swap['61']['inputs']['mask'], swap['62']['inputs']['source'], swap['62']['inputs']['operation']), (['59', 0], ['61', 0], 'multiply'))

    def test_layout_render_follows_the_previs_frees_the_actor_and_takes_the_acting_from_the_skeleton(self):
        import run_studio
        task = studio_task()
        task['input']['tabs'][0]['tables'][0]['headers'] += ['Previs', 'Actor Matte', 'Pose Skeleton']
        task['input']['rows'][1]['cells'] += [ASSET(9), ASSET(8), ASSET(7)]
        ctx = worker.resolve_studio_context(task)
        self.assertEqual((ctx['previs_video'], ctx['actor_matte'], ctx['pose_skeleton']), (ASSET(9), ASSET(8), ASSET(7)))
        self.assertNotEqual(ctx.get('motion_structure_video'), ASSET(7))  # "pose" in the header is the skeleton, not a structure pass
        cfg = run_studio.worker_configs('http://127.0.0.1:8188')
        head, client = Mock(), Mock()
        head.asset.side_effect = lambda task, url: (url.encode(), 'video/webm' if url in (ASSET(7), ASSET(8), ASSET(9)) else 'image/png')
        client.upload_media.side_effect = lambda raw, mime, prefix: raw.decode()[-2:] + '.' + prefix
        load = lambda stage, cap: json.loads(Path(cfg[stage][cap]['workflow']).read_text(encoding='utf-8'))
        key = load('layoutkey', 'image_gen')
        worker.bind_external_workflow(key, {'previs_video': ASSET(9), 'asset_images': [ASSET(1), ASSET(2)], 'compiled_prompt': 'beats', 'seed': 5},
                                      cfg['layoutkey']['image_gen'], task, head, client)
        # Klein paints previs frame 0 (only that frame is loaded) with the cast and set, under the blockout-to-photo edit.
        self.assertEqual((key['20']['inputs']['video'], key['20']['inputs']['frame_load_cap'], key['23']['inputs']['batch_index']), ('09.source_video', 1, 0))
        self.assertEqual((key['21']['inputs']['image'], key['22']['inputs']['image']), ('01.reference', '02.reference'))
        self.assertEqual(key['6']['inputs']['text'], run_studio.LAYOUT_KEY_PROMPT)
        self.assertEqual(cfg['layoutkey']['image_gen']['reference_role'], 'anchor_keyframe')  # the render step reads it as its key
        layout = load('layout', 'video_gen')
        worker.bind_external_workflow(layout, {'previs_video': ASSET(9), 'actor_matte': ASSET(8), 'pose_skeleton': ASSET(7), 'anchor_keyframe': ASSET(4),
                                               'compiled_prompt': 'beats', 'seed': 7}, cfg['layout']['video_gen'], task, head, client)
        self.assertEqual((layout['20']['inputs']['video'], layout['24']['inputs']['video'], layout['44']['inputs']['video'], layout['2']['inputs']['image']),
                         ('09.source_video', '08.source_video', '07.source_video', '04.input'))
        self.assertEqual((layout['30']['inputs']['string_a'], layout['50']['inputs']['noise_seed']), ('beats', 7))
        self.assertEqual((layout['24']['inputs']['frame_load_cap'], layout['44']['inputs']['frame_load_cap']), (['20', 1], ['20', 1]))  # same frames as the previs
        # Both strengths stay 1.0 (lower copies the grey model); the previs is the IC-LoRA reference on an empty latent.
        guide = layout['40']['inputs']
        self.assertEqual((layout['60']['inputs']['lora_name'], layout['60']['inputs']['strength_model'], guide['strength']),
                         ('ltx\\ltx-2.5-22b-ic-lora-layout-to-render-1.0.safetensors', 1.0, 1.0))
        self.assertEqual((guide['image'], guide['latent'], guide['iclora_parameters'], layout['21']['class_type']),
                         (['20', 0], ['21', 0], ['61', 0], 'EmptyLTXVLatentVideo'))
        # Attention mask: the stage matte grown 24 px, feathered and inverted, so the layout binds the set and frees the
        # actor entirely: none of the mannequin's shape reaches the shot (SPEC_10 §7.6-7.7).
        self.assertEqual(guide['attention_mask'], ['34', 0])
        self.assertEqual([layout[n]['class_type'] for n in ('25', '26', '27', '28', '29', '34')],
                         ['ImageToMask', 'GrowMask', 'MaskToImage', 'ImageBlur', 'ImageToMask', 'InvertMask'])
        self.assertEqual((layout['26']['inputs']['expand'], layout['34']['inputs']['mask']), (24, ['29', 0]))
        self.assertNotIn('35', layout)
        # The acting: Union-Control stacked on Layout-To-Render, the skeleton as its own guide with its own (half-size)
        # reference parameters, after the key; the sampler runs the model carrying both LoRAs and crops every guide.
        pose = layout['42']['inputs']
        self.assertEqual((layout['62']['inputs']['model'], layout['62']['inputs']['lora_name'], layout['63']['inputs']['iclora_model']),
                         (['60', 0], 'ltx\\ltx-2.3-22b-ic-lora-union-control-ref0.5.safetensors', ['62', 0]))
        self.assertEqual((pose['image'], pose['latent'], pose['positive'], pose['iclora_parameters'], pose['strength']), (['44', 0], ['41', 2], ['41', 0], ['63', 0], 1.0))
        self.assertEqual((layout['53']['inputs']['model'], layout['53']['inputs']['positive'], layout['15']['inputs']['video_latent']), (['62', 0], ['42', 0], ['42', 2]))
        # The Klein key is an out-of-clip reference (latent_idx -1); guides are cropped before decode; distilled sampling.
        self.assertEqual((layout['41']['inputs']['guiding_latent'], layout['41']['inputs']['latent_idx'], layout['17']['inputs']['positive']),
                         (['33', 0], -1, ['42', 0]))
        self.assertEqual((layout['8']['inputs']['samples'], layout['53']['inputs']['cfg'], layout['51']['inputs']['sampler_name']), (['17', 2], 1.0, 'euler_ancestral'))


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and FFprobe are required')
class ReferencePreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.source = Path(cls.folder.name) / 'source.mp4'
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=64x48:rate=12:duration=1',
            '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(cls.source)], check=True, capture_output=True)
        cls.raw = cls.source.read_bytes()
        cls.original = worker._probe_video(cls.source, {})

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def prepare(self, config):
        task = studio_task()
        task['input']['rows'][1]['cells'] = [ASSET(5)]
        task['input']['tabs'][0]['tables'][0]['headers'] = ['Source Video']
        head = Mock()
        head.lease_lost.return_value = False
        head.asset.return_value = (self.raw, 'video/mp4')
        uploaded = {}
        def upload(task, raw, mime, filename):
            uploaded.update(raw=raw, mime=mime, filename=filename)
            return {'asset_url': ASSET(9), 'content_type': mime}
        head.upload.side_effect = upload
        result = worker.ffmpeg(task, config, head)
        return result, uploaded

    def test_extract_frame_timestamp_png_and_reference_receipt(self):
        result, asset = self.prepare({'mode': 'extract_frame', 'timestamp_sec': 0.5})
        self.assertEqual(asset['mime'], 'image/png')
        self.assertEqual(asset['filename'], 'first_frame.png')
        from PIL import Image
        import io
        with Image.open(io.BytesIO(asset['raw'])) as image:
            self.assertEqual((image.format, image.size), ('PNG', (64, 48)))
        self.assertEqual(result['reference_role'], 'first_frame')
        self.assertEqual(result['asset_id'], 'pa_' + format(9, '032x'))
        self.assertEqual(result['text'], ASSET(9))

    def test_motion_filters_preserve_all_frames_fps_duration_audio_and_faststart(self):
        for structure in ('edge_lineart', 'luma_depth', 'frame_diff'):
            with self.subTest(structure=structure):
                result, asset = self.prepare({'mode': 'motion_structure', 'structure_type': structure})
                path = Path(self.folder.name) / (structure + '.mp4')
                path.write_bytes(asset['raw'])
                output = worker._probe_video(path, {})
                self.assertEqual(output['frames'], self.original['frames'])
                self.assertAlmostEqual(output['fps'], self.original['fps'])
                self.assertAlmostEqual(output['duration'], self.original['duration'], delta=.02)
                self.assertTrue(output['audio'])
                self.assertEqual(asset['mime'], 'video/mp4')
                self.assertLess(asset['raw'].index(b'moov'), asset['raw'].index(b'mdat'))
                self.assertEqual(result['reference_role'], 'motion_structure_video')

    def test_out_of_range_timestamp_fails_before_upload(self):
        with self.assertRaisesRegex(worker.WorkerError, 'timestamp'):
            self.prepare({'layout': 'extract_frame', 'timestamp_sec': 2})


class Spec05StudioCardAndDualEngineTests(unittest.TestCase):
    def test_suite1_declarative_cards_build_node_info_and_workflow_injection(self):
        for card_id in ('h3-reference', 'h3-optimize', 'h3-short-video-v3', 'ltx25-openjutsu', 'ltx25-cinema', 'flux-soul-cast', 'local-smoke'):
            with self.subTest(card_id=card_id):
                card = worker.load_studio_card(card_id)
                self.assertEqual(card['card_id'], card_id)
                self.assertTrue(card['nodes'])

        with tempfile.TemporaryDirectory() as cwd:
            card_file = Path(cwd, 'stray.json')
            card_file.write_text(json.dumps(worker.load_studio_card('local-smoke')), encoding='utf-8')
            previous = os.getcwd()
            os.chdir(cwd)
            try:
                with self.assertRaisesRegex(worker.WorkerError, 'not found'):
                    worker.load_studio_card('stray.json')
            finally:
                os.chdir(previous)
            self.assertEqual(worker.load_studio_card(card_file)['card_id'], 'local-smoke')

        h3_card = worker.load_studio_card('h3-reference')
        info = worker.build_node_info(h3_card, {
            '27.video': 'driving.mp4',
            '51.image': 'sheet.png',
            '263.text': '',
            '159.lora_name': 'none',
            '252.megapixels': '999.0',
        })
        by_key = {f"{item['nodeId']}.{item['fieldName']}": item['fieldValue'] for item in info}
        # Empty string must not fall back to defaultValue ('is None' rule).
        self.assertEqual(by_key['263.text'], '')
        # Locked nodes override external tampering.
        self.assertEqual(by_key['252.megapixels'], '1.0')
        self.assertEqual(by_key['283.value'], '2.0')
        self.assertEqual(by_key['48.audio'], 'None')
        # disabled_loras rule: 'none' substitutes valid filename and sets strength_model='0'.
        self.assertEqual(by_key['159.lora_name'], 'minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors')
        self.assertEqual(by_key['159.strength_model'], '0')

        workflow = json.loads((ROOT / 'workflows' / 'minimax_h3_ref2va.json').read_text(encoding='utf-8'))
        injected = worker.inject_node_info_into_workflow(copy.deepcopy(workflow), info, h3_card)
        self.assertEqual(injected['27']['inputs']['video'], 'driving.mp4')
        self.assertEqual(injected['51']['inputs']['image'], 'sheet.png')
        self.assertEqual(injected['159']['inputs']['strength_model'], 0.0)
        self.assertEqual(injected['252']['inputs']['megapixels'], 1.0)
        self.assertEqual(injected['283']['inputs']['value'], 2.0)
        # Optional 'None' image (49,50,43,19,23) and audio (48,14,15) nodes are unlinked and removed.
        for unused_id in ('49', '50', '43', '19', '23', '48', '14', '15'):
            self.assertNotIn(unused_id, injected)
        for key in ('ref_image_2', 'ref_image_3', 'ref_image_4', 'ref_image_5', 'ref_image_6',
                    'ref_audio_1', 'ref_audio_2', 'ref_audio_3'):
            self.assertNotIn(key, injected['200']['inputs'])
        self.assertIn('ref_image_1', injected['200']['inputs'])

    def test_suite2_slot_plan_pictured_first_ranking_and_excluded_refs_guard(self):
        task = studio_task()
        task['input']['tabs'][1]['tables'][0]['rows'] = [
            {'cells': ['PROP-01', 'TextProp', 'ancient brass compass without image', '']},
            {'cells': ['CAST-01', 'Kael', 'courier in coat; seed 48291', ASSET(1)]},
            {'cells': ['CAST-02', 'Vex', 'forbidden rival; seed 111', ASSET(2)]},
            {'cells': ['SET-01', 'Observatory', 'rain on glass', ASSET(3)]},
        ]
        # Mention PROP-01 once, SET-01 twice, CAST-01 once, and exclude CAST-02 via !-@CAST-02.
        task['input']['rows'][1]['cells'][3] = '@PROP-01 @CAST-01 enters @SET-01 and inspects @SET-01. !-@CAST-02'
        ctx = worker.resolve_studio_context(task)
        self.assertIn('CAST-02', ctx['excluded_refs'])
        self.assertNotIn('CAST-02', [a['asset_id'] for a in ctx['resolved_assets']])
        planned = ctx['slot_plan']
        self.assertEqual(len(planned), 6)
        # SET-01 appeared twice so it ranks ahead of CAST-01 (appeared once); PROP-01 has no image so it does not consume a slot.
        self.assertEqual(planned[0]['asset_id'], 'SET-01')
        self.assertEqual(planned[1]['asset_id'], 'CAST-01')
        self.assertIsNone(planned[2])

    def test_suite3_fingerprint_lock_and_role_separated_agent_prompt(self):
        base_values = {'27.video': ASSET(5), '51.image': ASSET(1), '259.value': '4', '252.aspect_ratio': '16:9 (Widescreen)'}
        fp1 = worker.compute_request_fingerprint('demo', 'shot-2', 'h3-reference', base_values)
        fp2 = worker.compute_request_fingerprint('demo', 'shot-2', 'h3-reference', dict(base_values))
        fp_changed_dur = worker.compute_request_fingerprint('demo', 'shot-2', 'h3-reference', dict(base_values, **{'259.value': '5'}))
        fp_changed_img = worker.compute_request_fingerprint('demo', 'shot-2', 'h3-reference', dict(base_values, **{'51.image': ASSET(2)}))
        self.assertEqual(fp1, fp2)
        self.assertNotEqual(fp1, fp_changed_dur)
        self.assertNotEqual(fp1, fp_changed_img)

        prompt = worker.compile_h3_agent_instruction_prompt({
            'pictures': [{'slot': 1, 'name': 'kael_sheet.png'}],
            'values': base_values,
            'directions': 'Keep full-body framing',
        }, [0.25, 0.75, 1.25, 1.75, 2.25, 2.75, 3.25, 3.75])
        self.assertIn('<Picture 1>', prompt)
        self.assertIn('<Video 1>', prompt)
        self.assertIn('圖片素材1', prompt)
        self.assertIn('參考影片1', prompt)

    def test_suite4_h3_context_ir_6_sections_and_ltx_ingredients_prompt(self):
        task = studio_task()
        ctx = worker.resolve_studio_context(task)
        ir = ctx['h3_context_ir_prompt']
        for section in ('subject_definitions:', 'summary:', 'retention_analysis:',
                        'detailed_description:', 'overall_soundscape:', 'non_diegetic_music:'):
            self.assertIn(section, ir)
        self.assertIn('<Subject 1>', ir)
        self.assertIn('<Picture 1>', ir)
        self.assertIn('<Video 1>', ir)
        self.assertRegex(ir, r'<d>\[English\].*</d>')

        ltx_prompt = ctx['ltx_ingredients_prompt']
        self.assertIn('Reference Sheet Layout:', ltx_prompt)
        self.assertIn('[Left panel: CAST-01 (Kael)', ltx_prompt)
        self.assertIn('[Right panel: SET-01 (Observatory)', ltx_prompt)

    def test_suite5_spec_aligner_32px_grid_and_frame_formulas(self):
        self.assertEqual(worker.snap_dimensions(1270, 710, 32), (1280, 704))
        self.assertEqual(worker.snap_dimensions(20, 20, 32), (32, 32))
        self.assertEqual(worker.snap_frame_count(96, 'none'), 96)
        self.assertEqual(worker.snap_frame_count(96, '8n+1'), 97)
        self.assertEqual(worker.snap_frame_count(97, '8n+1'), 97)
        self.assertEqual(worker.snap_frame_count(96, '17n+5'), 107)
        self.assertEqual(worker.snap_frame_count(22, '17n+5'), 22)
        self.assertEqual(worker.snap_frame_count(5, '17n+5'), 5)
        self.assertEqual(worker.aspect_for({'width': 1920, 'height': 1080},
                                          ['1:1 (Square)', '9:16 (Portrait Widescreen)', '16:9 (Widescreen)']),
                         '16:9 (Widescreen)')

    def test_litegraph_ui_conversion_card_extraction_and_cascade_unlink(self):
        # Simulate a RunningHub/ComfyUI LiteGraph UI workflow (like 短视频复刻-v3.json) with SetNode/GetNode and LayerUtility passthroughs
        litegraph_ui = {
            'nodes': [
                {'id': 1, 'type': 'LoadImage', 'inputs': [{'name': 'image', 'widget': {'name': 'image'}}], 'widgets_values': ['ref1.png', 'image']},
                {'id': 54, 'type': 'LayerUtility: ImageScaleByAspectRatio V2', 'inputs': [{'name': 'image', 'link': 50}], 'widgets_values': []},
                {'id': 32, 'type': 'SetNode', 'inputs': [{'name': 'IMAGE', 'link': 51}], 'widgets_values': ['ref_image_1']},
                {'id': 67, 'type': 'GetNode', 'inputs': [], 'widgets_values': ['ref_image_1']},
                {'id': 61, 'type': 'LoadImage', 'inputs': [{'name': 'image', 'widget': {'name': 'image'}}], 'widgets_values': ['ref2.png', 'image']},
                {'id': 62, 'type': 'LayerUtility: ImageScaleByAspectRatio V2', 'inputs': [{'name': 'image', 'link': 65}], 'widgets_values': []},
                {'id': 63, 'type': 'SetNode', 'inputs': [{'name': 'IMAGE', 'link': 67}], 'widgets_values': ['ref_image_2']},
                {'id': 64, 'type': 'GetNode', 'inputs': [], 'widgets_values': ['ref_image_2']},
                {'id': 3, 'type': 'VHS_LoadVideo', 'inputs': [{'name': 'video', 'widget': {'name': 'video'}}], 'widgets_values': {'video': 'src.mp4', 'force_rate': 24, 'videopreview': {}}},
                {'id': 57, 'type': 'JjkText', 'inputs': [{'name': 'text', 'widget': {'name': 'text'}}], 'widgets_values': ['initial prompt']},
                {'id': 72, 'type': 'MathExpression|pysssss', 'inputs': [{'name': 'expression', 'widget': {'name': 'expression'}}], 'widgets_values': ['max(5, round(a * 24)) + (5 - (max(5, round(a * 24)) % 17)) % 17']},
                {'id': 26, 'type': 'MiniMaxH3ReferenceToVideo', 'inputs': [
                    {'name': 'ref_images.ref_image_0', 'link': 72},
                    {'name': 'ref_images.ref_image_1', 'link': 69},
                    {'name': 'ref_videos.ref_video_0', 'link': 62},
                    {'name': 'prompt', 'link': 52},
                ], 'widgets_values': ['', 1344, 768, 124, 'match']},
                {'id': 42, 'type': 'SelfLiftAvatarH3Sampler', 'inputs': [
                    {'name': 'seed', 'widget': {'name': 'seed'}},
                    {'name': 'cfg', 'widget': {'name': 'cfg'}},
                ], 'widgets_values': [699183786914467, 'randomize', 1.0]},
                {'id': 51, 'type': 'VHS_VideoCombine', 'inputs': [{'name': 'images', 'link': 45}], 'widgets_values': {'format': 'video/h264-mp4'}},
            ],
            'links': [
                [50, 1, 0, 54, 0, 'IMAGE'],
                [51, 54, 0, 32, 0, '*'],
                [72, 67, 0, 26, 3, 'IMAGE'],
                [65, 61, 0, 62, 0, 'IMAGE'],
                [67, 62, 0, 63, 0, '*'],
                [69, 64, 0, 26, 4, 'IMAGE'],
                [62, 3, 0, 26, 6, 'IMAGE'],
                [52, 57, 0, 26, 11, 'STRING'],
                [45, 42, 0, 51, 0, 'IMAGE'],
            ],
        }
        api_graph = worker.convert_litegraph_to_api(litegraph_ui)
        self.assertNotIn('32', api_graph)
        self.assertNotIn('67', api_graph)
        self.assertEqual(api_graph['26']['inputs']['ref_images.ref_image_0'], ['54', 0])
        self.assertEqual(api_graph['26']['inputs']['ref_images.ref_image_1'], ['62', 0])
        self.assertEqual(api_graph['42']['inputs']['seed'], 699183786914467)
        self.assertEqual(api_graph['42']['inputs']['cfg'], 1.0)

        # Reverse-engineer a Studio Card directly from the LiteGraph UI workflow
        extracted = worker.extract_studio_card_from_workflow(litegraph_ui, card_id='auto-v3', label='Auto Short Video v3')
        self.assertEqual(extracted['output_mode'], 'video')
        self.assertEqual(extracted['engine_config']['output_node'], '51')
        self.assertEqual(extracted['engine_config']['frame_formula'], '17n+5')

        # Inject with 2nd reference image set to 'None' and verify cascade unlinking of 61 -> 62 -> 26.ref_images.ref_image_1
        node_info = worker.build_node_info(extracted, {
            '3.video': 'driving.mp4',
            '1.image': 'kael.png',
            '61.image': 'None',
            '57.text': 'compiled H3-Context-IR',
        })
        injected = worker.inject_node_info_into_workflow(litegraph_ui, node_info, extracted)
        self.assertNotIn('61', injected)
        self.assertNotIn('62', injected)
        self.assertNotIn('ref_images.ref_image_1', injected['26']['inputs'])
        self.assertEqual(injected['26']['inputs']['ref_images.ref_image_0'], ['54', 0])
        self.assertEqual(injected['1']['inputs']['image'], 'kael.png')
        self.assertEqual(injected['57']['inputs']['text'], 'compiled H3-Context-IR')

        oom_msg = worker._normalize_comfy_error({'status': {'status_str': 'error', 'failedReason': {'exception_type': 'OutOfMemoryError'}}})
        self.assertIn('OOM', oom_msg)
        queue_msg = worker._normalize_comfy_error({'status': {'status_str': 'error', 'errorMessage': 'API 并发数已达上线 (queue limit)'}})
        self.assertIn('queue limit', queue_msg)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and FFprobe are required')
class Spec05MediaAndLineWorldsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.source = Path(cls.folder.name) / 'source.mp4'
        subprocess.run([
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
            '-f', 'lavfi', '-i', 'testsrc2=size=64x48:rate=24:duration=1.5',
            '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1.5',
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(cls.source)
        ], check=True, capture_output=True)
        cls.raw_video = cls.source.read_bytes()

        cls.padded = Path(cls.folder.name) / 'padded.mp4'
        subprocess.run([
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
            '-f', 'lavfi', '-i', 'testsrc2=size=64x48:rate=24:duration=2.5',
            '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2.5',
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(cls.padded)
        ], check=True, capture_output=True)
        cls.raw_padded = cls.padded.read_bytes()

        from PIL import Image
        import io
        cls.img1_bytes = io.BytesIO()
        Image.new('RGB', (120, 160), (200, 40, 40)).save(cls.img1_bytes, format='PNG')
        cls.img2_bytes = io.BytesIO()
        Image.new('RGB', (140, 160), (40, 120, 220)).save(cls.img2_bytes, format='PNG')

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_suite3_and_4_frame_sheet_and_ingredients_sheet_generation(self):
        from PIL import Image
        import io
        task = studio_task()
        task['input']['rows'][1]['cells'] = [ASSET(5), '@CAST-01 @SET-01']
        task['input']['tabs'][0]['tables'][0]['headers'] = ['Source Video', 'Action Prompt']
        head = Mock()
        head.lease_lost.return_value = False
        def asset_fetch(t, url):
            if url == ASSET(5):
                return self.raw_video, 'video/mp4'
            if url == ASSET(1):
                return self.img1_bytes.getvalue(), 'image/png'
            return self.img2_bytes.getvalue(), 'image/png'
        head.asset.side_effect = asset_fetch
        uploaded = {}
        def upload(t, raw, mime, filename=None):
            uploaded.update(raw=raw, mime=mime, filename=filename)
            return {'asset_url': ASSET(10), 'content_type': mime}
        head.upload.side_effect = upload

        # 8-frame timestamped contact sheet (1600x600)
        res_sheet = worker.ffmpeg(task, {'mode': 'frame_sheet'}, head)
        self.assertEqual(res_sheet['reference_role'], 'frame_sheet')
        self.assertEqual(len(res_sheet['timestamps']), 8)
        with Image.open(io.BytesIO(uploaded['raw'])) as img:
            self.assertEqual(img.size, (1600, 600))

        # Horizontal Ingredients Sheet (32px-aligned)
        res_ing = worker.ffmpeg(task, {'mode': 'ingredients_sheet', 'height': 160, 'grid_size': 32}, head)
        self.assertEqual(res_ing['reference_role'], 'ingredients_sheet')
        self.assertIn('[Left panel: CAST-01', res_ing['ltx_ingredients_prompt'])
        with Image.open(io.BytesIO(uploaded['raw'])) as img:
            self.assertEqual(img.width % 32, 0)
            self.assertEqual(img.height % 32, 0)

    def test_suite6_ref05_and_lineworlds_with_and_without_source_video(self):
        from PIL import Image
        import io
        task = studio_task()
        task['input']['rows'][1]['cells'] = [ASSET(5), '@CAST-01']
        task['input']['tabs'][0]['tables'][0]['headers'] = ['Source Video', 'Action Prompt']
        head = Mock()
        head.lease_lost.return_value = False
        head.asset.return_value = (self.raw_video, 'video/mp4')
        uploaded = {}
        def upload(t, raw, mime, filename=None):
            uploaded.update(raw=raw, mime=mime, filename=filename)
            return {'asset_url': ASSET(11), 'content_type': mime}
        head.upload.side_effect = upload

        # Path A: De-textured ref05_edge and ref05_depth
        for stype in ('ref05_edge', 'ref05_depth'):
            with self.subTest(structure_type=stype):
                res = worker.ffmpeg(task, {'mode': 'motion_structure', 'structure_type': stype}, head)
                self.assertEqual(res['reference_role'], 'motion_structure_video')
                out_path = Path(self.folder.name) / f'{stype}.mp4'
                out_path.write_bytes(uploaded['raw'])
                probed = worker._probe_video(out_path, {})
                self.assertEqual(probed['frames'], 36)
                self.assertTrue(probed['audio'])

        # Path B1: line-worlds Extract & Re-Rig WITH source video
        for stype in ('layout_silhouette', 'sparse_tracks'):
            with self.subTest(lineworlds_with_video=stype):
                res = worker.ffmpeg(task, {
                    'mode': 'motion_structure', 'structure_type': stype,
                    'controls': {'stride': 0.6, 'turn': 0.25, 'reach': 0.7, 'flare': 0.6}
                }, head)
                self.assertEqual(res['reference_role'], 'motion_structure_video')
                out_path = Path(self.folder.name) / f'lw_{stype}.mp4'
                out_path.write_bytes(uploaded['raw'])
                probed = worker._probe_video(out_path, {})
                self.assertEqual(probed['frames'], 36)
                self.assertTrue(probed['audio'])

        # Path B2: line-worlds Storyboard Rehearsal WITHOUT source video + time_strata PNG
        task_no_vid = studio_task()
        task_no_vid['input']['rows'][1]['cells'] = ['@CAST-01']
        task_no_vid['input']['tabs'][0]['tables'][0]['headers'] = ['Action Prompt']
        task_no_vid['input']['predecessor_tasks'] = []
        res_rehearsal = worker.ffmpeg(task_no_vid, {
            'mode': 'motion_structure', 'structure_type': 'layout_silhouette',
            'width': 128, 'height': 96, 'fps': 12, 'duration_sec': 0.5, 'frame_rule': '8n+1'
        }, head)
        self.assertEqual(res_rehearsal['reference_role'], 'motion_structure_video')
        rehearsal_path = Path(self.folder.name) / 'rehearsal.mp4'
        rehearsal_path.write_bytes(uploaded['raw'])
        probed_rehearsal = worker._probe_video(rehearsal_path, {})
        self.assertEqual((probed_rehearsal['width'], probed_rehearsal['height']), (128, 96))
        self.assertEqual(probed_rehearsal['frames'], 9)  # 6 frames snapped to 8n+1 -> 9

        res_strata = worker.ffmpeg(task_no_vid, {
            'mode': 'time_strata', 'width': 160, 'height': 128, 'controls': {'phases': 5, 'turn': 0.4}
        }, head)
        self.assertEqual(res_strata['reference_role'], 'time_strata')
        with Image.open(io.BytesIO(uploaded['raw'])) as img:
            self.assertEqual(img.size, (160, 128))

    def test_suite7_bounded_mp4_trimming_and_pass2_source_chaining(self):
        # Trim 2.5s (60 frames @ 24fps) padded render back to 1.5s (36 frames @ 24fps)
        bounded_bytes = worker.bound_output_video_duration(self.raw_padded, 1.5, {})
        bounded_path = Path(self.folder.name) / 'bounded_check.mp4'
        bounded_path.write_bytes(bounded_bytes)
        probed = worker._probe_video(bounded_path, {})
        self.assertEqual(probed['frames'], 36)
        self.assertAlmostEqual(probed['duration'], 1.5, delta=0.05)
        self.assertTrue(probed['audio'])
        self.assertLess(bounded_bytes.index(b'moov'), bounded_bytes.index(b'mdat'))

        # Pass 2 @source resolution and card execution in comfyui()
        task = studio_task()
        task['capability'] = 'video_gen'
        task['input']['rows'][1]['cells'] = [ASSET(5), ASSET(1), ASSET(7), '@CAST-01']
        task['input']['tabs'][0]['tables'][0]['headers'] = ['Source Video', 'Ingredients Sheet', 'Remastered Video', 'Action Prompt']
        head = Mock()
        head.lease_lost.return_value = False
        head.asset.side_effect = lambda t, url: (self.raw_video, 'video/mp4') if url in (ASSET(5), ASSET(7)) else (self.img1_bytes.getvalue(), 'image/png')
        head.upload.side_effect = lambda t, raw, mime: {'asset_url': ASSET(12), 'content_type': mime}

        config = {'card_id': 'h3-optimize', 'platform': 'local', 'base_url': 'http://comfy.test', 'max_duration_sec': 1.5, 'poll_seconds': 0}
        with patch.object(worker, 'ComfyPlatformClient') as factory:
            client = factory.return_value
            client.upload_media.side_effect = lambda raw, mime, prefix: f'{prefix}.mp4' if mime.startswith('video/') else f'{prefix}.png'
            client.submit_workflow.return_value = 'job-opt'
            # Include a .zip side-output to verify NON_TAKE_KINDS archive filtering
            client.fetch_history.return_value = {'job-opt': {'outputs': {'12': {'media': [
                {'filename': 'debug_bundle.zip', 'outputType': 'zip'},
                {'filename': 'restored.mp4', 'outputType': 'mp4'},
            ]}}}}
            client.download_output.return_value = (self.raw_padded, 'video/mp4')
            result = worker.comfyui(task, config, head)
            submitted = client.submit_workflow.call_args.args[0]
            self.assertEqual(submitted['27']['inputs']['video'], 'source_video.mp4')
            self.assertEqual(submitted['51']['inputs']['image'], 'reference.png')
            self.assertAlmostEqual(submitted['259']['inputs']['value'], 1.5, places=2)
            self.assertEqual(submitted['252']['inputs']['aspect_ratio'], '4:3 (Standard)')
            self.assertEqual(client.download_output.call_args.args[0]['filename'], 'restored.mp4')
            uploaded_bytes = head.upload.call_args.args[1]
            verify_path = Path(self.folder.name) / 'comfy_bounded.mp4'
            verify_path.write_bytes(uploaded_bytes)
            self.assertEqual(worker._probe_video(verify_path, {})['frames'], 36)
            self.assertEqual(result['reference_role'], 'output_video')

    @unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'authenticated v2 HTTP requires dedicated PostgreSQL')
    def test_suite8_runninghub_interoperability_and_self_hosted_openapi_v2(self):
        import threading
        import time
        import urllib.request
        import server

        # 1. LiteGraph UI -> API conversion with mode=4 (bypassed nodes) and legacy widget names
        litegraph_with_bypass = {
            'nodes': [
                {
                    'id': 36,
                    'type': 'DuckDecodeNode',
                    'mode': 0,
                    'inputs': [{'name': 'duck_image', 'type': 'IMAGE', 'link': None}],
                    'outputs': [{'name': 'IMAGE', 'type': 'IMAGE', 'links': [10]}],
                    'widgets_values': ['secret_pwd'],
                },
                {
                    'id': 186,
                    'type': 'DuckHideNode',
                    'mode': 4,  # Bypassed node — must forward input link [36, 0] to downstream
                    'inputs': [{'name': 'image', 'type': 'IMAGE', 'link': 10}],
                    'outputs': [{'name': 'IMAGE', 'type': 'IMAGE', 'links': [11]}],
                    'widgets_values': ['secret'],
                },
                {
                    'id': 37,
                    'type': 'SaveImage',
                    'mode': 0,
                    'inputs': [{'name': 'images', 'type': 'IMAGE', 'link': 11}],
                    'outputs': [],
                    'widgets_values': ['ComfyUI'],
                },
            ],
            'links': [
                [10, 36, 0, 186, 0, 'IMAGE'],
                [11, 186, 0, 37, 0, 'IMAGE'],
            ],
        }
        converted_api = worker.convert_litegraph_to_api(litegraph_with_bypass)
        self.assertNotIn('186', converted_api)
        self.assertEqual(converted_api['36']['inputs'], {'password': 'secret_pwd'})
        self.assertEqual(converted_api['37']['inputs']['images'], ['36', 0])

        # 2. Parse RunningHub curl for webappId 2109942725885075458 and extract exact 4 exposed slots
        curl_cmd = (
            "curl --location --request POST 'https://www.runninghub.ai/openapi/v2/run/ai-app/2109942725885075458' "
            '--header "Content-Type: application/json" '
            '--header "Authorization: Bearer ${RUNNINGHUB_API_KEY}" '
            '--data-raw \'{"nodeInfoList":['
            '{"nodeId":"1","fieldName":"image","fieldValue":"686c9017ad72e5a589768e34222942c4ddb7f8000251f3cb0dd8e0f8969df2a6.png","description":null},'
            '{"nodeId":"61","fieldName":"image","fieldValue":"cc5ada5a568b0400e80cc6a8ac585cfc44de0f0984ab3f596dbafbc4568783db.png","description":null},'
            '{"nodeId":"3","fieldName":"video","fieldValue":"5663418bd0e02c9104eb00cb4f4390f1dae2a0ac7b973cd6a232a36069c34f5a.mp4","description":null},'
            '{"nodeId":"57","fieldName":"text","fieldValue":"subject_definitions:\\n<Subject 1> is the person represented by <Picture 1>.","description":null}'
            '],"instanceType":"default","usePersonalQueue":"false"}\''
        )
        parsed_spec = worker.parse_runninghub_curl_or_payload(curl_cmd)
        self.assertEqual(parsed_spec['webappId'], '2109942725885075458')
        self.assertEqual(len(parsed_spec['nodeInfoList']), 4)

        card_2109 = worker.load_studio_card('2109942725885075458')
        self.assertEqual(card_2109['card_id'], 'h3-short-video-v3')
        self.assertEqual(
            [(n['nodeId'], n['fieldName'], n['fieldType'], n.get('slot')) for n in card_2109['nodes']],
            [
                ('1', 'image', 'IMAGE', 'ref'),
                ('61', 'image', 'IMAGE', 'ref'),
                ('3', 'video', 'VIDEO', 'driving_video'),
                ('57', 'text', 'STRING', 'prompt'),
            ],
        )

        # 3. End-to-end self-hosted OpenAPI v2 HTTP test (/openapi/v2/media/upload/binary -> /run/ai-app -> /query -> /media/output)
        import test_product_http
        http_fixture = test_product_http.ProductHTTPTests()
        http_fixture.setUp()
        port = http_fixture.server.server_port
        base = f'http://127.0.0.1:{port}'
        auth_headers = {'Authorization': 'Bearer ' + http_fixture.member_token, 'X-Requested-With': 'projects', 'X-Project-Slug': http_fixture.slug}
        try:
            with self.assertRaises(urllib.error.HTTPError) as denied:
                urllib.request.urlopen(base + '/openapi/v2/cards', timeout=10)
            self.assertEqual(denied.exception.code, 401)
            denied.exception.close()
            def post_json(path, obj):
                req = urllib.request.Request(
                    base + path,
                    data=json.dumps(obj).encode('utf-8'),
                    headers={**auth_headers, 'Content-Type': 'application/json'},
                    method='POST',
                )
                return json.loads(urllib.request.urlopen(req, timeout=10).read().decode('utf-8'))

            def post_bin(path, raw, mime, fname):
                req = urllib.request.Request(
                    base + path,
                    data=raw,
                    headers={**auth_headers, 'Content-Type': mime, 'X-File-Name': fname},
                    method='POST',
                )
                return json.loads(urllib.request.urlopen(req, timeout=10).read().decode('utf-8'))

            up_img = post_bin('/openapi/v2/media/upload/binary', self.img1_bytes.getvalue(), 'image/png', 'ref1.png')
            up_vid = post_bin('/openapi/v2/media/upload/binary', self.raw_video, 'video/mp4', 'drive.mp4')
            self.assertEqual(up_img['code'], 0)
            self.assertTrue(up_img['data']['fileName'].endswith('.png'))
            self.assertTrue(up_vid['data']['fileName'].endswith('.mp4'))

            with patch.object(worker.ComfyPlatformClient, 'upload_media', side_effect=lambda raw, mime, prefix='in': 'comfy_' + prefix), \
                 patch.object(worker.ComfyPlatformClient, 'submit_workflow', return_value='prompt-v3-http'), \
                 patch.object(worker.ComfyPlatformClient, 'fetch_history', return_value={
                     'prompt-v3-http': {
                         'status': {'completed': True},
                         'outputs': {'51': {'gifs': [{'filename': 'AnimateDiff_00001.mp4', 'subfolder': '', 'type': 'output'}]}},
                     }
                 }), \
                 patch.object(worker.ComfyPlatformClient, 'download_output', return_value=(self.raw_video, 'video/mp4')):
                run_res = post_json('/openapi/v2/run/ai-app/2109942725885075458', {
                    'nodeInfoList': [
                        {'nodeId': '1', 'fieldName': 'image', 'fieldValue': up_img['data']['fileName'], 'description': None},
                        {'nodeId': '61', 'fieldName': 'image', 'fieldValue': 'None', 'description': None},
                        {'nodeId': '3', 'fieldName': 'video', 'fieldValue': up_vid['data']['fileName'], 'description': None},
                        {'nodeId': '57', 'fieldName': 'text', 'fieldValue': 'subject_definitions:\n<Subject 1> is Kael from <Picture 1>.\n', 'description': None},
                    ],
                    'instanceType': 'default',
                    'usePersonalQueue': 'false',
                })
                self.assertEqual(run_res['code'], 0)
                self.assertEqual(run_res['status'], 'RUNNING')

                for _ in range(20):
                    q_res = post_json('/openapi/v2/query', {'taskId': run_res['taskId']})
                    if q_res['status'] != 'RUNNING':
                        break
                    time.sleep(0.05)

                self.assertEqual(q_res['status'], 'SUCCESS')
                self.assertEqual(len(q_res['results']), 1)
                self.assertEqual(q_res['results'][0]['outputType'], 'mp4')
                self.assertEqual(q_res['results'][0]['nodeId'], '51')
                # Verify optional Picture 2 (node 61 -> 62 -> 26.ref_images.ref_image_1) was cascade-unlinked
                self.assertNotIn('ref_images.ref_image_1', q_res['compiledWorkflow']['26']['inputs'])
                self.assertEqual(q_res['compiledWorkflow']['26']['inputs']['ref_images.ref_image_0'], ['54', 0])

                with urllib.request.urlopen(urllib.request.Request(q_res['results'][0]['url'], headers=auth_headers), timeout=10) as resp:
                    downloaded = resp.read()
                self.assertEqual(downloaded, self.raw_video)
        finally:
            http_fixture.conn.rollback()
            with http_fixture.conn.cursor() as cur:
                cur.execute('DELETE FROM projectops.story_record WHERE owner_id=%s', (http_fixture.actor,))
            http_fixture.conn.commit()
            http_fixture.tearDown()


if __name__ == '__main__':
    unittest.main()
