"""SPEC_21 package A (A1-A2): the reference-key and Klein-edit cards and graphs, their compiled graphs with 0, 1 and 6
references, the width/height inputs, and which compiled text each card's prompt takes. No ComfyUI, GPU or network."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from project_assistant import limb_worker as worker
from project_assistant.studio import card_engine

ROOT = Path(__file__).resolve().parents[1]
ASSET = lambda n: '/projects/api/demo/assets/pa_' + format(n, '032x')
KLEIN_LOADERS = ('1', '2', '4')  # UNET, CLIP and VAE loaders shared with the GPU-proven look-key graph


def graph_of(card):
    return json.loads((ROOT / card['engine_config']['workflow']).read_text(encoding='utf-8'))


def form(card, ctx=None, values=None, **config):
    return worker._build_card_form_values(card, dict(ctx or {}), dict(card['engine_config'], card_values=values or {}, **config),
                                          {'id': 'task', 'project_slug': 'demo'}, None)


def compile_graph(card_id, ctx=None, values=None):
    card = worker.load_studio_card(card_id)
    info = worker.build_node_info(card, form(card, ctx, values))
    return worker.inject_node_info_into_workflow(graph_of(card), info, card)


def plan(*numbers):
    roles = ('character_face', 'character_body', 'location', 'prop')
    return [{'url': ASSET(n), 'assetCode': f'CAST-{n:02d}', 'role': roles[i % 4], 'panel': 'face'} for i, n in enumerate(numbers)]


class GraphChecks:
    def assert_valid_graph(self, graph):
        links = [(node_id, key, value) for node_id, node in graph.items() for key, value in node['inputs'].items()
                 if isinstance(value, list) and len(value) == 2]
        for node_id, key, value in links:
            self.assertIn(value[0], graph, (node_id, key))  # no dangling link
            self.assertIsInstance(value[1], int, (node_id, key))
        consumed = {value[0] for _, _, value in links}
        for node_id, node in graph.items():
            if node['class_type'] == 'ReferenceMultiLatent':
                keys = [k for k in node['inputs'] if k.startswith('images.')]
                self.assertTrue(keys, 'a ReferenceMultiLatent with no image must be routed around')
                self.assertEqual(sorted(keys, key=lambda k: int(k.rsplit('image', 1)[1])), [f'images.image{i}' for i in range(len(keys))])
            if node['class_type'] == 'LoadImage':
                self.assertIn(node_id, consumed)  # no loader left feeding nothing
                self.assertNotIn(str(node['inputs']['image']).lower(), ('', 'none'))

    def images(self, graph):
        node = next((n for n in graph.values() if n['class_type'] == 'ReferenceMultiLatent'), None)
        if node is None:
            return []
        keys = sorted((k for k in node['inputs'] if k.startswith('images.')), key=lambda k: int(k.rsplit('image', 1)[1]))
        return [(node['inputs'][k][0], graph[node['inputs'][k][0]]['inputs']['image']) for k in keys]


class CardAndGraphFileTests(GraphChecks, unittest.TestCase):
    def test_reference_key_graph_is_the_look_key_graph_with_six_loaders_and_no_source_frame(self):
        look = json.loads((ROOT / 'workflows/flux3_klein_look_key.json').read_text(encoding='utf-8'))
        for name, count, prefix in (('flux3_klein_reference_key.json', 6, 'zerofield_reference_key'),
                                    ('flux3_klein_edit.json', 3, 'zerofield_klein_edit')):
            with self.subTest(name=name):
                graph = json.loads((ROOT / 'workflows' / name).read_text(encoding='utf-8'))
                self.assert_valid_graph(graph)
                for node_id in KLEIN_LOADERS + ('5', '8'):
                    self.assertEqual(graph[node_id], look[node_id])
                classes = [n['class_type'] for n in graph.values()]
                self.assertNotIn('VHS_LoadVideo', classes)
                self.assertNotIn('ImageFromBatch', classes)
                self.assertEqual(classes.count('LoadImage'), count)
                self.assertEqual(self.images(graph), [(str(21 + i), f'reference_{i}.png') for i in range(count)])
                rml = graph['11']['inputs']
                self.assertEqual((rml['positive'], rml['negative'], rml['vae']), (['6', 0], ['5', 0], ['4', 0]))
                self.assertEqual((rml['resolution'], rml['resolution.megapixels']), ('resize', 1.0))
                sampler = graph['3']['inputs']
                self.assertEqual((sampler['steps'], sampler['cfg'], sampler['positive'], sampler['negative'], sampler['model'],
                                  sampler['latent_image']), (50, 4.0, ['11', 0], ['11', 1], ['7', 0], ['10', 0]))
                self.assertEqual(graph['10']['class_type'], 'EmptyFlux2LatentImage')
                self.assertEqual(graph['7']['class_type'], 'ModelSamplingFlux')
                self.assertEqual((graph['7']['inputs']['width'], graph['7']['inputs']['height']),
                                 (graph['10']['inputs']['width'], graph['10']['inputs']['height']))
                self.assertEqual(graph['9'], {'class_type': 'SaveImage', 'inputs': {'images': ['8', 0], 'filename_prefix': prefix}})
                self.assertFalse(any('api_key' in json.dumps(n).lower() or 'partner' in n['class_type'].lower() for n in graph.values()))

    def test_cards_are_open_weight_local_cards_whose_inputs_exist_in_their_graphs(self):
        expected = {'flux-reference-key': ('reference_image', ['21', '22', '23', '24', '25', '26'], '10', '2105000000000000005'),
                    'flux-klein-edit': ('edit', ['21', '22', '23'], '10', '2105000000000000006'),
                    'flux-soul-cast': ('asset_panel', [], '5', '2105000000000000003'),
                    'ltx25-cinema': ('video_skeleton', ['2'], None, '2105000000000000002')}
        for card_id, (compile_name, refs, size_node, webapp) in expected.items():
            with self.subTest(card_id=card_id):
                card = worker.load_studio_card(card_id)
                config = card['engine_config']
                self.assertEqual((config['driver'], config['tier'], config['requires_comfyui']), ('comfy_local', 'open_weights', True))
                self.assertEqual((config['prompt_compile'], config['webappId']), (compile_name, webapp))
                self.assertEqual(worker.load_studio_card(webapp)['card_id'], card['card_id'])  # webappId resolves to this card
                graph = graph_of(card)
                self.assertIsInstance(worker._resolve_openapi_card_and_workflow(card_id)[1], dict)
                for node in card['nodes']:
                    self.assertIn(node['fieldName'], graph[node['nodeId']]['inputs'], node)
                self.assertEqual([n['nodeId'] for n in card['nodes'] if n.get('slot') == 'ref' and n['fieldType'] == 'IMAGE'], refs)
                self.assertEqual([n['slot'] for n in card['nodes'] if n.get('slot') in ('prompt', 'seed')], ['prompt', 'seed'])
                if size_node:
                    sizes = {n['fieldName']: n for n in card['nodes'] if n['fieldName'] in ('width', 'height')}
                    self.assertEqual({n['nodeId'] for n in sizes.values()}, {size_node})
                    self.assertEqual({n['fieldType'] for n in sizes.values()}, {'INT'})
                    self.assertEqual([sizes[k]['defaultValue'] for k in ('width', 'height')],
                                     [str(graph[size_node]['inputs'][k]) for k in ('width', 'height')])
        edit = worker.load_studio_card('flux-klein-edit')
        self.assertEqual([n['required'] for n in edit['nodes'] if n.get('slot') == 'ref'], [True, False, False])  # image 1 is edited
        # Panels and shot keyframes pick these cards by id; the generic Character / Scene & prop bar keeps Soul Cast as the
        # first image card it can fall back to (an edit cannot run without a picture to edit).
        self.assertEqual(edit['engine_config']['usage_scopes'], ['SCENE_PROP_EDIT', 'FREE_CREATION_I2I'])
        self.assertEqual(worker.load_studio_card('flux-reference-key')['engine_config']['usage_scopes'],
                         ['FREE_CREATION_T2I', 'FREE_CREATION_I2I'])
        self.assertFalse(any(n['required'] for n in worker.load_studio_card('flux-reference-key')['nodes'] if n.get('slot') == 'ref'))
        webapps = [json.loads(p.read_text(encoding='utf-8')).get('engine_config', {}).get('webappId') for p in worker.CARDS_DIR.glob('*.json')]
        webapps = [w for w in webapps if w]
        self.assertEqual(len(webapps), len(set(webapps)))

    def test_prompt_compile_and_mirror_inputs_are_validated(self):
        card = json.loads((ROOT / 'workflows/cards/flux-reference-key.json').read_text(encoding='utf-8'))
        for bad in ('video', ['edit'], {'edit': 1}, ''):
            invalid = copy.deepcopy(card)
            invalid['engine_config']['prompt_compile'] = bad
            with self.assertRaisesRegex(worker.WorkerError, 'prompt_compile'):
                worker.validate_studio_card(invalid)
        for bad in (['7.width'], {'7.width': 10}, {'7width': '10.width'}, {'7.width': '10'}):
            invalid = copy.deepcopy(card)
            invalid['engine_config']['mirror_inputs'] = bad
            with self.assertRaisesRegex(worker.WorkerError, 'mirror_inputs'):
                worker.validate_studio_card(invalid)
        router = json.loads((ROOT / 'workflows/cards/router-flux-3-image.json').read_text(encoding='utf-8'))
        router['engine_config']['mirror_inputs'] = {'7.width': '10.width'}
        with self.assertRaisesRegex(worker.WorkerError, 'graph node mutations'):
            worker.validate_studio_card(router)
        self.assertEqual(worker.CARD_PROMPT_COMPILE, {'reference_image': 'image_reference_prompt', 'video_skeleton': 'video_skeleton_prompt',
                                                      'asset_panel': 'asset_panel_prompt', 'edit': 'edit_prompt'})


class ReferenceGraphCompileTests(GraphChecks, unittest.TestCase):
    """A1: 0, 1 and 6 references, gaps closed, width and height applied."""

    def test_zero_references_compile_to_plain_text_to_image(self):
        for card_id in ('flux-reference-key',):
            for ctx in ({}, {'reference_plan': []}, {'reference_plan': [{'assetCode': 'CAST-01', 'url': ''}]}):
                with self.subTest(card_id=card_id, ctx=ctx):
                    graph = compile_graph(card_id, ctx)
                    self.assert_valid_graph(graph)
                    self.assertEqual(sorted(graph, key=int), ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10'])
                    self.assertNotIn('ReferenceMultiLatent', json.dumps(graph))
                    sampler = graph['3']['inputs']
                    self.assertEqual((sampler['positive'], sampler['negative'], sampler['model']), (['6', 0], ['5', 0], ['7', 0]))

    def test_one_reference_fills_image_zero_and_drops_the_other_loaders(self):
        graph = compile_graph('flux-reference-key', {'reference_plan': plan(7)})
        self.assert_valid_graph(graph)
        self.assertEqual(self.images(graph), [('21', ASSET(7))])
        for node_id in ('22', '23', '24', '25', '26'):
            self.assertNotIn(node_id, graph)
        self.assertEqual((graph['3']['inputs']['positive'], graph['3']['inputs']['negative']), (['11', 0], ['11', 1]))

    def test_six_references_follow_the_plan_order_and_extra_entries_are_left_out(self):
        graph = compile_graph('flux-reference-key', {'reference_plan': plan(6, 1, 5, 2, 4, 3, 9)})
        self.assert_valid_graph(graph)
        self.assertEqual(self.images(graph), [(str(21 + i), ASSET(n)) for i, n in enumerate((6, 1, 5, 2, 4, 3))])

    def test_empty_references_between_filled_ones_leave_no_gap(self):
        graph = compile_graph('flux-reference-key', values={'21.image': ASSET(1), '22.image': 'None', '23.image': ASSET(3),
                                                            '24.image': '', '25.image': 'none', '26.image': ASSET(6)})
        self.assert_valid_graph(graph)
        self.assertEqual(self.images(graph), [('21', ASSET(1)), ('23', ASSET(3)), ('26', ASSET(6))])
        self.assertEqual(sorted(k for k in graph['11']['inputs'] if k.startswith('images.')),
                         ['images.image0', 'images.image1', 'images.image2'])
        # A plan entry without a picture is an empty input too; the pictures after it move up.
        holes = plan(1, 2, 3)
        holes[1]['url'] = None
        graph = compile_graph('flux-reference-key', {'reference_plan': holes})
        self.assertEqual(self.images(graph), [('21', ASSET(1)), ('23', ASSET(3))])
        # Only the first image unlinked: the rest renumber from image0 in order.
        graph = compile_graph('flux-reference-key', values={'21.image': 'None', '22.image': ASSET(2), '23.image': ASSET(3)})
        self.assertEqual(self.images(graph), [('22', ASSET(2)), ('23', ASSET(3))])

    def test_width_and_height_set_the_latent_and_the_sampler_shift_together(self):
        for card_id in ('flux-reference-key', 'flux-klein-edit'):
            with self.subTest(card_id=card_id):
                ctx = {'reference_plan': plan(1)}
                default = compile_graph(card_id, ctx)
                self.assertEqual([default[n]['inputs'][k] for n in ('10', '7') for k in ('width', 'height')], [1280, 704, 1280, 704])
                sized = compile_graph(card_id, ctx, {'10.width': '768', '10.height': 1344})
                self.assertEqual([sized[n]['inputs'][k] for n in ('10', '7') for k in ('width', 'height')], [768, 1344, 768, 1344])
                self.assertIs(type(sized['7']['inputs']['width']), int)
        cast = worker.load_studio_card('flux-soul-cast')
        raw = graph_of(cast)
        default = compile_graph('flux-soul-cast')
        self.assertEqual((default['5']['inputs']['width'], default['5']['inputs']['height']), (1280, 720))
        for node_id in raw:  # the defaults leave the text-to-image graph as it was, apart from prompt and seed
            if node_id not in ('6', '3'):
                self.assertEqual(default[node_id], raw[node_id], node_id)
        sized = compile_graph('flux-soul-cast', values={'5.width': 896, '5.height': '1184'})
        self.assertEqual((sized['5']['inputs']['width'], sized['5']['inputs']['height']), (896, 1184))
        self.assertEqual(worker.validate_direct_card_values(cast, {'5.width': 1344, '5.height': 768})[1:3],
                         [{'nodeId': '5', 'fieldName': 'width', 'fieldValue': '1344', 'description': None},
                          {'nodeId': '5', 'fieldName': 'height', 'fieldValue': '768', 'description': None}])
        with self.assertRaisesRegex(worker.WorkerError, 'outside its allowed range'):
            worker.validate_direct_card_values(cast, {'5.width': 4096})

    def test_edit_card_edits_image_one_with_up_to_two_more_references(self):
        graph = compile_graph('flux-klein-edit', {'reference_plan': plan(4)})
        self.assert_valid_graph(graph)
        self.assertEqual(self.images(graph), [('21', ASSET(4))])
        graph = compile_graph('flux-klein-edit', {'reference_plan': plan(4, 5, 6, 7)})
        self.assertEqual(self.images(graph), [('21', ASSET(4)), ('22', ASSET(5)), ('23', ASSET(6))])
        with self.assertRaisesRegex(worker.WorkerError, r'Required card media slot 21\.image'):
            compile_graph('flux-klein-edit', values={'22.image': ASSET(5)})

    def test_comfy_run_uploads_the_plan_pictures_in_order_with_the_reference_prompt(self):
        ctx = {'reference_plan': plan(3, 1, 2), 'image_reference_prompt': 'The person in image 1 and image 2 is Noa.',
               'compiled_prompt': 'legacy text', 'seed': 77, 'anchor_keyframe': ASSET(40), 'resolved_assets': []}
        head = Mock()
        head.lease_lost.return_value = False
        head.asset.side_effect = lambda task, url: (url.encode(), 'image/png')
        head.upload.side_effect = lambda task, raw, mime: {'asset_url': ASSET(90), 'content_type': mime}
        config = {'card_id': 'flux-reference-key', 'platform': 'local', 'base_url': 'http://comfy.test', 'poll_seconds': 0,
                  'card_values': {'10.width': 768, '10.height': 1344},
                  'workflow': str(ROOT / 'workflows/flux3_klein_reference_key.json')}
        with patch.object(worker, 'resolve_studio_context', return_value=ctx), \
                patch.object(worker, 'ComfyPlatformClient') as factory:
            client = factory.return_value
            client.upload_media.side_effect = lambda raw, mime, prefix: prefix + '-' + raw.decode()[-2:] + '.png'
            client.submit_workflow.return_value = 'job'
            client.fetch_history.return_value = {'job': {'outputs': {'9': {'images': [{'filename': 'key.png'}]}}}}
            client.download_output.return_value = (b'png', 'image/png')
            result = worker.comfyui({'id': 'task', 'project_slug': 'demo', 'input': {}}, config, head)
        graph = client.submit_workflow.call_args.args[0]
        self.assert_valid_graph(graph)
        self.assertEqual(self.images(graph), [('21', 'reference-03.png'), ('22', 'reference-01.png'), ('23', 'reference-02.png')])
        self.assertEqual([c.args[1] for c in head.asset.call_args_list], [ASSET(3), ASSET(1), ASSET(2)])  # never the old keyframe
        self.assertEqual(graph['6']['inputs']['text'], 'The person in image 1 and image 2 is Noa.')
        self.assertEqual((graph['3']['inputs']['seed'], graph['10']['inputs']['width'], graph['7']['inputs']['height']), (77, 768, 1344))
        self.assertEqual(result['content_type'], 'image/png')


class PromptCompileTests(unittest.TestCase):
    """A2: each card takes its compiled text; without it, and on cards without prompt_compile, nothing changes."""
    COMPILED = {'image_reference_prompt': 'REFERENCE IMAGE TEXT', 'video_skeleton_prompt': 'SCENE CONTEXT\nVIDEO SKELETON',
                'asset_panel_prompt': 'ASSET PANEL TEXT', 'edit_prompt': 'Edit image 1. CHANGE: wet.'}
    CONTEXTS = ({}, {'compiled_prompt': 'compiled'},
                {'compiled_prompt': 'compiled', 'ingredients_sheet': ASSET(8), 'ltx_ingredients_prompt': 'ingredients'},
                {'compiled_prompt': 'compiled', 'h3_context_ir_prompt': 'context ir', 'anchor_keyframe': ASSET(9), 'seed': 5,
                 'resolved_assets': [{'asset_id': 'CAST-01', 'reference_urls': [ASSET(1)]},
                                     {'asset_id': 'SET-01', 'reference_urls': [ASSET(2)]}]})

    @staticmethod
    def prompt(card, values):
        return next(values[f"{n['nodeId']}.{n['fieldName']}"] for n in card['nodes'] if n.get('slot') == 'prompt')

    @staticmethod
    def without_compile(card):
        plain = copy.deepcopy(card)
        plain['engine_config'].pop('prompt_compile')
        return plain

    def test_each_card_takes_the_text_its_prompt_compile_names(self):
        for card_id, key in (('flux-reference-key', 'image_reference_prompt'), ('ltx25-cinema', 'video_skeleton_prompt'),
                             ('flux-soul-cast', 'asset_panel_prompt'), ('flux-klein-edit', 'edit_prompt')):
            card = worker.load_studio_card(card_id)
            for ctx in self.CONTEXTS:
                with self.subTest(card_id=card_id, ctx=ctx):
                    self.assertEqual(self.prompt(card, form(card, dict(ctx, **self.COMPILED))), self.COMPILED[key])
                    # An explicit prompt value still wins over every compiled text.
                    prompt_key = next(f"{n['nodeId']}.{n['fieldName']}" for n in card['nodes'] if n.get('slot') == 'prompt')
                    self.assertEqual(self.prompt(card, form(card, dict(ctx, **self.COMPILED), {prompt_key: 'override'})), 'override')

    def test_missing_or_blank_compiled_text_falls_back_to_the_current_rules_exactly(self):
        for card_id, key in (('flux-reference-key', 'image_reference_prompt'), ('ltx25-cinema', 'video_skeleton_prompt'),
                             ('flux-soul-cast', 'asset_panel_prompt'), ('flux-klein-edit', 'edit_prompt')):
            card = worker.load_studio_card(card_id)
            plain = self.without_compile(card)
            others = {k: v for k, v in self.COMPILED.items() if k != key}
            for ctx in self.CONTEXTS:
                for missing in ({}, {key: ''}, {key: '   \n'}, {key: None}, {key: ['not', 'text']}):
                    with self.subTest(card_id=card_id, ctx=ctx, missing=missing):
                        full = dict(ctx, **others, **missing)
                        self.assertEqual(form(card, full), form(plain, ctx))
        # The fallback for a video card is the ingredients prompt when a sheet is the frame, else the compiled prompt.
        cinema = worker.load_studio_card('ltx25-cinema')
        self.assertEqual(self.prompt(cinema, form(cinema, self.CONTEXTS[2])), 'ingredients')
        self.assertEqual(self.prompt(cinema, form(cinema, self.CONTEXTS[1])), 'compiled')
        self.assertEqual(self.prompt(cinema, form(cinema, {})), cinema['nodes'][2]['defaultValue'])

    def test_cards_without_prompt_compile_ignore_the_new_context(self):
        extra = dict(self.COMPILED, reference_plan=plan(11, 12, 13))
        for path in sorted(worker.CARDS_DIR.glob('*.json')):
            card = worker.load_studio_card(path)
            if card['engine_config'].get('prompt_compile'):
                continue
            for ctx in self.CONTEXTS:
                ctx = dict(ctx, output_video=ASSET(30), anchor_keyframe=ASSET(9))  # what the h3-optimize second pass reads
                with self.subTest(card_id=card['card_id'], ctx=ctx):
                    self.assertEqual(form(card, dict(ctx, **extra)), form(card, ctx))

    def test_only_image_prompt_cards_take_their_references_from_the_plan(self):
        ctx = {'reference_plan': plan(11, 12), 'anchor_keyframe': ASSET(9), 'compiled_prompt': 'compiled',
               'resolved_assets': [{'asset_id': 'CAST-01', 'reference_urls': [ASSET(1)]},
                                   {'asset_id': 'SET-01', 'reference_urls': [ASSET(2)]}]}
        key = worker.load_studio_card('flux-reference-key')
        refs = lambda card, values: [values[f"{n['nodeId']}.{n['fieldName']}"] for n in card['nodes'] if n.get('slot') == 'ref']
        self.assertEqual(refs(key, form(key, ctx)), [ASSET(11), ASSET(12), 'None', 'None', 'None', 'None'])
        # Without a plan the refs come from slot_plan as before (the row's keyframe first, then the pictured assets).
        no_plan = {k: v for k, v in ctx.items() if k != 'reference_plan'}
        self.assertEqual(refs(key, form(key, no_plan)), [ASSET(9), ASSET(2), 'None', 'None', 'None', 'None'])
        self.assertEqual(form(key, dict(no_plan, reference_plan=[])), form(key, no_plan))
        self.assertEqual(form(key, dict(no_plan, reference_plan='CAST-01')), form(key, no_plan))
        # The video skeleton card keeps its first frame in its one reference input.
        cinema = worker.load_studio_card('ltx25-cinema')
        self.assertEqual(refs(cinema, form(cinema, ctx)), [ASSET(9)])
        # Explicit reference values still win over the plan.
        self.assertEqual(refs(key, form(key, ctx, {'22.image': ASSET(5)}))[:2], [ASSET(11), ASSET(5)])

    def test_a_job_config_may_name_another_compiled_text(self):
        key = worker.load_studio_card('flux-reference-key')
        ctx = dict(self.COMPILED, reference_plan=plan(1, 2))
        values = form(key, ctx, prompt_compile='asset_panel')  # e.g. a Front panel rendered on the reference-key card
        self.assertEqual(values['6.text'], 'ASSET PANEL TEXT')
        self.assertEqual((values['21.image'], values['22.image']), (ASSET(1), ASSET(2)))
        self.assertEqual(form(key, ctx, prompt_compile='unknown')['6.text'], 'REFERENCE IMAGE TEXT')


class UnlinkCompactionTests(GraphChecks, unittest.TestCase):
    def test_only_reference_multi_latent_images_are_renumbered(self):
        graph = {'1': {'class_type': 'LoadImage', 'inputs': {'image': 'a.png'}},
                 '2': {'class_type': 'LoadImage', 'inputs': {'image': 'b.png'}},
                 '3': {'class_type': 'MiniMaxH3ReferenceToVideo', 'inputs': {'ref_images.ref_image_0': ['1', 0], 'ref_images.ref_image_1': ['2', 0]}},
                 '4': {'class_type': 'ReferenceMultiLatent', 'inputs': {'positive': ['9', 0], 'negative': ['9', 1],
                                                                      'images.image0': ['1', 0], 'images.image1': ['2', 0]}},
                 '9': {'class_type': 'Conditioning', 'inputs': {}},
                 '10': {'class_type': 'KSampler', 'inputs': {'positive': ['4', 0], 'negative': ['4', 1]}}}
        card_engine._unlink_node_and_dependents(graph, '1')
        self.assertEqual(graph['3']['inputs'], {'ref_images.ref_image_1': ['2', 0]})  # other node types keep their numbering
        self.assertEqual(graph['4']['inputs']['images.image0'], ['2', 0])
        self.assertNotIn('images.image1', graph['4']['inputs'])
        self.assertNotIn('1', graph)
        card_engine._unlink_node_and_dependents(graph, '2')
        self.assertNotIn('4', graph)  # no picture left: the conditioning goes straight to the sampler
        self.assertEqual(graph['10']['inputs'], {'positive': ['9', 0], 'negative': ['9', 1]})
        self.assertNotIn('2', graph)


if __name__ == '__main__':
    unittest.main()
