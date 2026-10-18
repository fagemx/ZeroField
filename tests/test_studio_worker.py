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
        self.assertNotIn('unrelated', prompt)
        self.assertEqual(task, before)

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
        self.assertEqual(ctx['compiled_prompt'], 'original courier; seed 48291')
        self.assertNotIn('References:', ctx['compiled_prompt'])


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
        for name, output in [('flux3_klein_soul_cast.json', '9'), ('ltx25_cinema_shot.json', '12'), ('ltx25_openjutsu_v2v.json', '12')]:
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


if __name__ == '__main__':
    unittest.main()
