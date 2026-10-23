"""Story contract tests use real HTTP, PostgreSQL tabs and FFmpeg; GPU is isolated."""
import io
import json
import os
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch

from project_docs import markdown_import, repository as repo, service, story_openapi as story, templates
from project_docs.doc_schema import validate_doc
from project_assistant import limb_worker as worker
import test_product_http as product_fixture


class StoryPureTests(unittest.TestCase):
    def test_offline_adaptation_modes_and_preserved_source(self):
        idea = story.adapt_source_to_script('A lone astronomer discovers a brass dial counting down.', mode='idea')
        self.assertEqual(idea, story.adapt_source_to_script('A lone astronomer discovers a brass dial counting down.', mode='idea'))
        self.assertEqual(len(story.scene_sections(idea)), 3)
        for tag in ('@CAST-01', '@CAST-02', '@SET-03', '@PROP-01'):
            self.assertIn(tag, idea)
        novel = 'Mira entered the station. "The signal is back."\n\nEvan replied, "Then we must leave."\n\nLater, Mira turned toward the brass dial.'
        adapted = story.adapt_source_to_script(novel, mode='novel')
        self.assertEqual(len(story.scene_sections(adapted)), 3)
        self.assertIn('Character: Mira', adapted)
        self.assertIn('Character: Evan', adapted)
        self.assertIn('@CAST-01: "The signal is back."', adapted)
        self.assertIn('@CAST-02: "Then we must leave."', adapted)
        self.assertIn('## Scene 01: INT. STATION - NIGHT', story.adapt_source_to_script('INT. STATION - NIGHT\nMIRA: "Stay."', 'script'))
        chinese = story.adapt_source_to_script('小明說：「快走！」\n\n小美回答：「等等！」\n\n小明走進房間。小美轉身關門。', 'novel')
        self.assertEqual(chinese.count('Character:'), 2)
        self.assertIn('Character: 小明 @CAST-01', chinese)
        self.assertIn('Character: 小美 @CAST-02', chinese)
        self.assertIn('@CAST-01 走進房間', chinese)
        self.assertIn('@CAST-02 轉身關門', chinese)
        for kwargs in ({'mode': 'unknown'}, {'mode': []}, {'target_scenes': 0}, {'target_scenes': 13}, {'target_scenes': True}, {'target_scenes': '3'}):
            with self.assertRaises(ValueError):
                story.adapt_source_to_script('A story.', **kwargs)
        for source in ('', ' ', None, 'x' * 500001):
            with self.assertRaises(ValueError):
                story.adapt_source_to_script(source)

    def test_character_code_allocation_and_rich_asset_descriptions(self):
        from project_docs.story_adaptation import extract_asset_details, allocated_characters
        source = 'Character: Mara @CAST-02 (silver hair)\nCharacter: Evan (green coat)\nMARA: "Wait."\nProp: Brass dial @PROP-07\n\nScene 01: Rooftop Rain\nEnvironment: @SET-07, moonlight through rain.\n@CAST-02:night approaches. @CAST-02#injured (torn sleeve) turns.'
        people = allocated_characters(source)
        self.assertEqual([(name, code) for name, _, code in people], [('Mara', 'CAST-02'), ('Evan', 'CAST-01')])
        details = extract_asset_details(source, story.scene_sections(source))
        self.assertEqual(details['CAST-02']['name'], 'Mara')
        self.assertIn('silver hair', details['CAST-02']['prompt'])
        self.assertEqual(details['CAST-02:NIGHT']['kind'], 'OUTFIT')
        self.assertIn('torn sleeve', details['CAST-02:INJURED']['prompt'])
        self.assertIn('foreground/midground/background', details['SET-07']['prompt'])
        self.assertIn('moonlight', details['SET-07']['prompt'])
        self.assertEqual(details['PROP-07']['name'], 'Brass dial')
        adapted = story.adapt_source_to_script('Character: Mara @CAST-07 (silver hair)\nA secret is discovered.', 'idea')
        self.assertIn('Shot 1: @CAST-07', adapted)
        self.assertIn('Shot 2: @CAST-01:', adapted)
        appearance = story.adapt_source_to_script('Mara (silver hair, dark coat) entered the room. "Wait."\n\nEvan replied, "Stay."', 'novel')
        self.assertIn('Character: Mara @CAST-01 (silver hair, dark coat)', appearance)

    def test_shot_beats_compatibility_dialogue_and_grammar(self):
        for mode in ('auto', 'scene', 'cinematic'):
            self.assertEqual(story.scene_shot_beats('@CAST-01 walks past @PROP-01.', mode), ['@CAST-01 walks past @PROP-01.'])
        self.assertEqual(len(story.scene_shot_beats('@CAST-01 walks across\nthe room.', 'auto')), 1)
        self.assertEqual(len(story.scene_shot_beats('@CAST-01 walks.', 'cinematic_multi')), 2)
        raw = '@CAST-01 enters.\n\n@CAST-02: "We are out of time."\n\nClose-up of tearful eyes.'
        beats = story.scene_shot_beats(raw)
        self.assertEqual(len(beats), 3)
        self.assertEqual(len(story.scene_shot_beats(raw, 'scene')), 1)
        self.assertEqual(len(story.scene_shot_beats('@CAST-01 enters. @CAST-01 stops. @CAST-01 turns.', 'cinematic')), 3)
        self.assertEqual(story.scene_shot_beats('@CAST-01 enters. @CAST-01: "Wait. Stay here." @CAST-01 turns.', 'cinematic'),
                         ['@CAST-01 enters.', '@CAST-01: "Wait. Stay here."', '@CAST-01 turns.'])
        grammar = [story.infer_shot_grammar(b, i, len(beats)) for i, b in enumerate(beats)]
        self.assertIn('ARRI Alexa', grammar[0]['opticalRig'])
        self.assertEqual([g['previsPlan']['lens'] for g in grammar], [35, 50, 85])
        self.assertEqual(grammar[0]['previsPlan']['action'], 'walkin')
        self.assertEqual(grammar[1]['dialogue'][0]['speaker'], 'CAST-02')
        self.assertEqual(grammar[1]['dialogue'][0]['line'], 'We are out of time.')
        self.assertGreater(grammar[1]['dialogue'][0]['estimatedSeconds'], 0)
        self.assertEqual(grammar[2]['cameraMotion'], 'Crane Up')
        self.assertEqual(story.infer_shot_grammar('MARA: We should leave.', 1, 2)['dialogue'][0]['line'], 'We should leave.')
        from project_docs.story_adaptation import character_details
        self.assertEqual(character_details('MARA: We should leave.\nEnvironment: Station\nProp: Key'), [('MARA', '', None)])

    def test_pagination_and_scene_parser(self):
        result = story.page(list(range(6)), {"limit": "2"})
        self.assertEqual(result["items"], [0, 1])
        self.assertEqual(story.page(list(range(6)), {"limit": "2", "cursor": result["nextCursor"]})["items"], [2, 3])
        for query in [{"limit": "0"}, {"limit": "101"}, {"cursor": "broken"}]:
            with self.assertRaises(story.StoryError):
                story.page([], query)
        self.assertEqual(len(story.scene_sections("Scene 01: Arrival\n@CAST-01 enters\nScene 02: Exit\nLeaves")), 2)

    def test_dynamic_catalog_and_aliases(self):
        apps = story.catalog()
        self.assertTrue({"h3-short-video-v3", "h3-reference", "ltx25-openjutsu", "flux-soul-cast"} <= {a["card_id"] for a in apps})
        self.assertTrue(all(isinstance(a["skuId"], str) for a in apps))
        self.assertEqual(story.resolve_app("2109942725885075458", "video")["card_id"], "h3-short-video-v3")
        with self.assertRaises(story.StoryError):
            story.resolve_app("h3-reference", "image")

    def test_worker_variant_references_and_hash_alias(self):
        task = {"input": {"rows": [{"tab_key": "cinema-studio", "cells": ["@CAST-01#night"]}], "tabs": [
            {"tab_key": "cinema-studio", "tables": [{"headers": ["Action Prompt"]}]},
            {"tab_key": "soul-cast", "tables": [{"headers": ["Asset ID", "Name", "Appearance", "Reference Image"], "rows": [
                {"cells": ["CAST-01", "Courier", "Base jacket", "![Image](/projects/api/demo/assets/pa_" + "a" * 32 + ")"]},
                {"cells": ["CAST-01:night", "Courier at night", "Night jacket", ""]}]}]}]}}
        ctx = worker.resolve_studio_context(task)
        self.assertEqual(ctx["resolved_assets"][0]["asset_id"], "CAST-01:NIGHT")
        self.assertEqual(ctx["resolved_assets"][0]["appearance_prompt"], "Night jacket")
        self.assertTrue(ctx["asset_images"])

    def test_story_adapter_uses_frozen_graph_and_card_values(self):
        graph = {'1': {'class_type': 'SaveImage', 'inputs': {}}}
        card = worker.load_studio_card('local-smoke')
        paths = []
        def execute(task, config, head):
            paths.append(Path(config['workflow']))
            self.assertEqual(json.loads(paths[0].read_text()), graph)
            self.assertEqual(config['card_values'], {'6.text': 'director prompt'})
            self.assertEqual(config['card']['card_id'], 'local-smoke')
            return {'asset_url': '/test.png'}
        with patch.object(worker, 'comfyui', side_effect=execute):
            self.assertEqual(worker.execute_story_card({'workflow': graph}, card, {'6.text': 'director prompt'}, None), {'asset_url': '/test.png'})
        self.assertFalse(paths[0].exists())

    def test_private_webhooks_rejected(self):
        for url in ["http://example.org", "https://127.0.0.1", "https://[::1]", "https://user:pass@example.org"]:
            with self.assertRaises(story.StoryError):
                story.webhook_address(url)


class FilmCutTests(unittest.TestCase):
    def test_slate_order_and_lab_clips_join_once_approved(self):
        shot = lambda index, tab, url, status="": {"shotIndex": index, "tabKey": tab, "selectedVideoUrl": url, "reviewStatus": status}
        items = [shot("VFX-01", "openjutsu-lab", "/vfx"), shot("S10", "cinema-studio", "/s10"), shot("S02", "cinema-studio", "/s02", "Retake"),
                 shot("S03", "cinema-studio", None), shot("VFX-02", "openjutsu-lab", "/vfx2", "Approved")]
        self.assertEqual(story.film_cut(items), ["/s02", "/s10", "/vfx2"])  # S02 before S10; no video, no unapproved lab sample


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "set OPENBENCH_TEST_DB_URI for Story HTTP tests")
class StoryHTTPTests(unittest.TestCase):
    request = product_fixture.ProductHTTPTests.request

    def setUp(self):
        product_fixture.ProductHTTPTests.setUp(self)
        for key, title, surface, md in templates.tab_specs("zerofield_studio", "Story Test", ""):
            doc, _ = markdown_import.markdown_to_doc(md, tab_keys=set(), image_src=lambda _: None)
            doc, _ = validate_doc(doc, slug=self.slug)
            templates.configure_doc(key, doc)
            repo.create_tab(self.conn, self.slug, key=key, title=title, parent_key=None, doc=doc,
                            actor_id=self.actor, surface_type=surface)
        self.ep = f"ep_{self.slug}_01"
        self.conn.commit()
        self.extra_projects = []

    def tearDown(self):
        # All asynchronously submitted jobs are bounded and awaited by each test.
        self.conn.rollback()
        with worker._OPENAPI_LOCK:
            for key, (card, _) in list(worker._OPENAPI_CARDS.items()):
                if card['card_id'] == 'test-card-' + self.slug:
                    worker._OPENAPI_CARDS.pop(key)
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM projectops.story_record WHERE owner_id=%s", (self.actor,))
            for slug in self.extra_projects:
                cur.execute("DELETE FROM projectops.flow_definition WHERE project_slug=%s", (slug,))
                cur.execute("DELETE FROM projectops.project WHERE slug=%s", (slug,))
        self.conn.commit()
        product_fixture.ProductHTTPTests.tearDown(self)

    def call(self, path, method="GET", body=None, headers=None):
        code, payload, _ = self.request(story.BASE + path, method=method, data=body, headers=headers)
        return code, payload

    def ok(self, path, method="GET", body=None, headers=None):
        code, payload = self.call(path, method, body, headers)
        self.assertEqual(code, 200, payload)
        self.assertEqual((payload["code"], payload["msg"], payload["errorMessages"]), (0, "success", None))
        return payload["data"]

    def prepare(self):
        self.ok(f"/episodes/{self.ep}/script", "PUT", {"scriptContent": "## Scene 01: Observatory\n@CAST-01 walks past @PROP-01.\n\n## Scene 02: Departure\n@CAST-01 leaves."})
        self.ok(f"/episodes/{self.ep}/asset-extractions", "POST", {})
        self.ok(f"/episodes/{self.ep}/storyboards", "POST", {})
        return [s for s in self.ok(f"/episodes/{self.ep}/shots")["items"] if s['tabKey'] == 'cinema-studio' and s.get('sceneId')]

    def test_adaptation_endpoint_is_offline_idempotent_and_validated(self):
        from project_assistant import providers
        path = f'/episodes/{self.ep}/script-adaptations'
        body = {'sourceText': 'A lone astronomer discovers a brass dial.', 'sourceMode': 'idea', 'targetScenes': 3, 'breakdownMode': 'cinematic'}
        with patch.dict(os.environ, {'OPENBENCH_MODEL': 'must-not-call', 'OPENBENCH_API_BASE': 'https://example.invalid'}), patch.object(providers, 'run_openai_compat_turn', side_effect=AssertionError('Offline adaptation must not call a provider')):
            result = self.ok(path, 'POST', body, {'Idempotency-Key': 'adapt-once'})
            self.assertEqual(result, self.ok(path, 'POST', body, {'Idempotency-Key': 'adapt-once'}))
        self.assertEqual(result['engine'], 'deterministic')
        self.assertIn('## Scene 03', result['script']['content'])
        self.assertEqual(self.ok('/episodes/' + self.ep)['breakdownMode'], 'cinematic')
        self.assertEqual(self.call(path, 'POST', {**body, 'targetScenes': 2}, {'Idempotency-Key': 'adapt-once'})[0], 409)
        for change in ({'sourceText': ''}, {'sourceText': []}, {'sourceMode': 'remote'}, {'targetScenes': True}, {'targetScenes': 13}, {'breakdownMode': 'bad'}):
            self.assertEqual(self.call(path, 'POST', body | change)[0], 422)
        self.assertEqual(self.request(story.BASE + path, method='POST', data=body, authenticated=False)[0], 401)
        self.ok(f'/episodes/{self.ep}/asset-extractions', 'POST', {})
        self.ok(f'/episodes/{self.ep}/storyboards', 'POST', {})
        generated = [s for s in self.ok(f'/episodes/{self.ep}/shots?limit=100')['items'] if s.get('sceneId')]
        self.assertGreaterEqual(len(generated), 9)
        self.assertTrue(all(s.get('previsPlan') for s in generated))
        repo.upsert_member(self.conn, self.actor, 'Viewer', 'viewer'); self.conn.commit()
        self.assertEqual(self.call(path, 'POST', body)[0], 409)
        self.assertEqual(self.call(f'/episodes/{self.ep}/asset-image-generations', 'POST', {})[0], 409)

    def test_multibeat_readiness_variants_and_rebuild_preserves_media(self):
        content = 'Character: Mara @CAST-88 (silver hair, red coat)\nProp: Brass dial @PROP-88\n\nScene 01: Rooftop Rain\nEnvironment: @SET-88, moonlight through rain.\n\n@CAST-88:night enters.'
        self.ok(f'/episodes/{self.ep}/script', 'PUT', {'scriptContent': content})
        self.ok(f'/episodes/{self.ep}/asset-extractions', 'POST', {})
        self.assertIn('CAST-88:NIGHT', self.ok('/episodes/' + self.ep)['missingAssetCodes'])
        self.ok(f'/episodes/{self.ep}/storyboards', 'POST', {})
        original = next(s for s in self.ok(f'/episodes/{self.ep}/shots')['items'] if s.get('sceneId'))
        self.assertEqual(original['readiness']['missingAssets'], ['CAST-88:NIGHT', 'SET-88'])
        self.assertFalse(original['readiness']['ready'])
        self.assertFalse(original['readiness']['hasPrevis'])
        base = next(a for a in story.assets(self.conn, story.episode(self.conn, self.ep)) if a['assetCode'] == 'CAST-88')
        url = f'/projects/api/{self.slug}/assets/pa_' + 'a' * 32
        story.mutate_row(self.conn, self.me, self.slug, 'soul-cast', base['rowId'], {3: f'![Image]({url})'})
        story.mutate_row(self.conn, self.me, self.slug, 'cinema-studio', original['rowId'], {8: f'[Previs]({url})'})
        self.conn.commit()
        ready = self.ok('/shots/' + original['shotId'])
        self.assertIn('CAST-88:NIGHT', ready['readiness']['missingAssets'])
        self.assertTrue(ready['readiness']['ready'])
        self.assertTrue(ready['readiness']['hasPrevis'])
        story.mutate_row(self.conn, self.me, self.slug, 'cinema-studio', original['rowId'], {4: f'![Image]({url})', 8: ''})
        self.conn.commit()
        keyframe_ready = self.ok('/shots/' + original['shotId'])
        self.assertTrue(keyframe_ready['readiness']['ready'])
        self.assertFalse(keyframe_ready['readiness']['hasPrevis'])
        story.mutate_row(self.conn, self.me, self.slug, 'cinema-studio', original['rowId'], {8: f'[Previs]({url})'})
        self.conn.commit()
        scene_id = original['sceneId']
        beats = '@CAST-88:night enters.\n\n@CAST-88:night: "Stay here."\n\nClose-up of @CAST-88:night eyes.'
        self.ok('/scenes/' + scene_id, 'PATCH', {'content': beats})
        self.ok(f'/episodes/{self.ep}/asset-extractions', 'POST', {})
        self.ok('/scenes/' + scene_id + '/shot-rebuilds', 'POST', {})
        rebuilt = [s for s in self.ok(f'/episodes/{self.ep}/shots')['items'] if s.get('sceneId') == scene_id]
        self.assertEqual([s['shotIndex'] for s in rebuilt], ['SC01-S01', 'SC01-S02', 'SC01-S03'])
        self.assertEqual(rebuilt[0]['shotId'], original['shotId'])
        self.assertTrue(rebuilt[0]['readiness']['hasPrevis'])
        self.assertTrue(rebuilt[1]['readiness']['hasDialogue'])
        self.assertEqual([s['previsPlan']['lens'] for s in rebuilt], [35, 50, 85])
        self.assertEqual(self.call(f'/episodes/{self.ep}/storyboards', 'POST', {'breakdownMode': 'invalid'})[0], 422)
        self.ok('/scenes/' + scene_id, 'PATCH', {'content': '\n\n'.join('A new action.' for _ in range(201))})
        self.ok(f'/episodes/{self.ep}/asset-extractions', 'POST', {})
        self.assertEqual(self.call(f'/episodes/{self.ep}/storyboards', 'POST', {})[0], 422)
        self.assertEqual(len([s for s in self.ok(f'/episodes/{self.ep}/shots')['items'] if s.get('sceneId') == scene_id]), 3)

    def test_missing_asset_batch_defaults_scope_accounting_and_atomic_failure(self):
        from project_assistant import execution_governance as governance
        self.prepare()
        ep = story.episode(self.conn, self.ep)
        missing, known = story.missing_episode_assets(self.conn, ep)
        self.assertEqual(set(missing), {'CAST-01', 'SET-01', 'SET-02'})
        path = f'/episodes/{self.ep}/asset-image-generations'
        before = len(story.records(self.conn, 'task', owner=self.actor))
        original_prepare = governance.prepare_operation
        calls = []
        def reject_second(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise governance.AdmissionError('Test budget exhausted')
            return original_prepare(*args, **kwargs)
        with patch.object(story._POOL, 'submit') as submit, patch.object(governance, 'prepare_operation', side_effect=reject_second):
            self.assertEqual(self.call(path, 'POST', {})[0], 409)
            submit.assert_not_called()
        self.assertEqual(len(story.records(self.conn, 'task', owner=self.actor)), before)
        with patch.object(story._POOL, 'submit') as submit:
            group = self.ok(path, 'POST', {}, {'Idempotency-Key': 'assets-once'})
            self.assertEqual(group, self.ok(path, 'POST', {}, {'Idempotency-Key': 'assets-once'}))
            self.assertEqual(set(group['assetCodes']), set(missing))
            self.assertEqual(submit.call_count, 3)
        for task_id in group['taskIds']:
            task = story.record(self.conn, task_id)
            self.assertEqual(task['_job']['card']['card_id'], 'flux-soul-cast')
            self.assertEqual(task['_job']['episodeId'], self.ep)
            self.assertTrue(task['_job']['_accounting_keys'])
            self.ok('/tasks/' + task_id + '/cancellations', 'POST', {})
        for code in missing:
            url = f'/projects/api/{self.slug}/assets/pa_' + 'a' * 32
            story.mutate_row(self.conn, self.me, self.slug, 'soul-cast', known[code]['rowId'], {3: f'![Image]({url})'})
        self.conn.commit()
        self.assertEqual(self.ok(path, 'POST', {})['taskIds'], [])
        self.assertEqual(self.ok('/episodes/' + self.ep)['missingAssetCodes'], [])

    def test_extraction_preserves_manual_drafts_and_settings_select_density(self):
        source = 'Character: Mara @CAST-88 (silver hair)\n\nScene 01: Station\n@CAST-88 enters. @CAST-88 turns.'
        self.ok(f'/episodes/{self.ep}/script', 'PUT', {'scriptContent': source})
        self.ok(f'/episodes/{self.ep}/asset-extractions', 'POST', {})
        asset = next(a for a in self.ok(f'/episodes/{self.ep}/assets')['items'] if a['assetCode'] == 'CAST-88')
        self.ok('/assets/' + asset['assetId'], 'PATCH', {'name': 'Director Mara', 'prompt': 'Custom blue coat and cropped hair'})
        self.ok(f'/episodes/{self.ep}/asset-extractions', 'POST', {})
        self.assertEqual(self.ok('/assets/' + asset['assetId'])['prompt'], 'Custom blue coat and cropped hair')
        self.assertEqual(self.ok('/assets/' + asset['assetId'])['name'], 'Director Mara')
        self.ok('/assets/' + asset['assetId'], 'PATCH', {'name': 'Director Mara', 'prompt': 'Director Mara'})
        self.ok(f'/episodes/{self.ep}/asset-extractions', 'POST', {})
        self.assertEqual(self.ok('/assets/' + asset['assetId'])['prompt'], 'Director Mara')
        self.assertEqual(self.ok('/assets/' + asset['assetId'])['name'], 'Director Mara')
        self.ok(f'/episodes/{self.ep}/settings', 'PUT', {'breakdownMode': 'cinematic'})
        self.ok(f'/episodes/{self.ep}/storyboards', 'POST', {})
        generated = [s for s in self.ok(f'/episodes/{self.ep}/shots')['items'] if s.get('sceneId')]
        self.assertEqual(len(generated), 2)
        self.assertEqual(self.call(f'/episodes/{self.ep}/settings', 'PUT', {'breakdownMode': 'unknown'})[0], 422)

    def test_storyboard_build_preserves_director_edits_and_only_appends_missing_beats(self):
        original = self.prepare()[0]
        edits = {'shotIndex': 'DIRECTOR-42', 'opticalRig': 'Director 50mm lens', 'cameraMotion': 'Director locked camera', 'description': 'A hand-edited prompt @CAST-01'}
        self.ok('/shots/' + original['shotId'], 'PATCH', edits)
        before_meta = story.shot_meta(self.conn, original['shotId'])
        self.ok(f'/episodes/{self.ep}/storyboards', 'POST', {})
        preserved = self.ok('/shots/' + original['shotId'])
        self.assertEqual({key: preserved[key] for key in edits}, edits)
        self.assertEqual(story.shot_meta(self.conn, original['shotId']), before_meta)
        self.ok('/scenes/' + original['sceneId'], 'PATCH', {'content': '@CAST-01 enters.\n\n@CAST-01: "Wait."\n\nClose-up of @CAST-01 eyes.'})
        self.ok(f'/episodes/{self.ep}/asset-extractions', 'POST', {})
        self.ok(f'/episodes/{self.ep}/storyboards', 'POST', {})
        preserved = self.ok('/shots/' + original['shotId'])
        self.assertEqual({key: preserved[key] for key in edits}, edits)
        related = [s for s in self.ok(f'/episodes/{self.ep}/shots')['items'] if s.get('sceneId') == original['sceneId']]
        self.assertEqual(len(related), 3)
        self.ok('/scenes/' + original['sceneId'] + '/shot-rebuilds', 'POST', {})
        rebuilt = self.ok('/shots/' + original['shotId'])
        self.assertEqual({key: rebuilt[key] for key in ('shotIndex', 'opticalRig', 'cameraMotion')}, {key: edits[key] for key in ('shotIndex', 'opticalRig', 'cameraMotion')})
        self.assertIn('@CAST-01 enters.', rebuilt['description'])

    def test_missing_asset_batch_completes_more_than_render_concurrency_limit(self):
        from PIL import Image
        source = self.ok(f'/episodes/{self.ep}/script-adaptations', 'POST', {'sourceText': 'A lone astronomer discovers a brass dial.', 'sourceMode': 'idea'})
        self.ok(f'/episodes/{self.ep}/asset-extractions', 'POST', {})
        data = io.BytesIO(); Image.new('RGB', (8, 8), 'green').save(data, format='PNG')
        active = maximum = 0
        lock = threading.Lock()
        def render(task, card, values, head):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            try:
                time.sleep(.4)
                return head.upload(task, data.getvalue(), 'image/png')
            finally:
                with lock:
                    active -= 1
        with patch.object(worker, 'execute_story_card', side_effect=render):
            group = self.ok(f'/episodes/{self.ep}/asset-image-generations', 'POST', {})
            self.assertEqual(len(group['taskIds']), 5)
            tasks = [self.await_task({'taskId': identifier}) for identifier in group['taskIds']]
        self.assertEqual([task['status'] for task in tasks], ['SUCCEEDED'] * 5, tasks)
        self.assertLessEqual(maximum, 2)
        self.assertEqual(self.ok('/episodes/' + self.ep)['missingAssetCodes'], [])

    def capacity_wait_case(self, cancel):
        from PIL import Image
        from project_assistant import execution_governance as governance
        self.ok(f'/episodes/{self.ep}/script-adaptations', 'POST', {'sourceText': 'A lone astronomer discovers a brass dial.', 'sourceMode': 'idea', 'targetScenes': 1})
        self.ok(f'/episodes/{self.ep}/asset-extractions', 'POST', {})
        data = io.BytesIO(); Image.new('RGB', (8, 8), 'green').save(data, format='PNG')
        release, waiting = threading.Event(), threading.Event()
        blocked, submitted = [], []
        original_begin, original_run = governance.begin_operation, governance.run_operation
        def begin(conn, ctx, request_key, **kwargs):
            try:
                return original_begin(conn, ctx, request_key, **kwargs)
            except governance.CapacityUnavailable:
                blocked.append(request_key.rsplit(':', 1)[0]); waiting.set()
                raise
        def run(*args, **kwargs):
            return original_run(*args, **kwargs, capacity_timeout=5 if cancel else .15)
        def render(task, card, values, head):
            submitted.append(task['id'])
            release.wait(10)
            return head.upload(task, data.getvalue(), 'image/png')
        with patch.object(governance, 'begin_operation', side_effect=begin), patch.object(governance, 'run_operation', side_effect=run), patch.object(worker, 'execute_story_card', side_effect=render):
            group = self.ok(f'/episodes/{self.ep}/asset-image-generations', 'POST', {})
            try:
                self.assertTrue(waiting.wait(5), 'Third asset did not reach the capacity wait')
                identifier = blocked[0]
                if cancel:
                    self.ok('/tasks/' + identifier + '/cancellations', 'POST', {})
                result = self.await_task({'taskId': identifier})
                self.assertEqual(result['status'], 'CANCELED' if cancel else 'FAILED', result)
                if not cancel:
                    self.assertIn('Timed out waiting for execution capacity', result['error']['message'])
                self.assertNotIn(identifier, submitted)
                with self.conn.cursor() as cur:
                    cur.execute('SELECT state FROM projectops.agent_usage_reservation WHERE project_slug=%s AND request_key=%s', (self.slug, identifier + ':generate'))
                    self.assertEqual(cur.fetchone()[0], 'released')
            finally:
                release.set()
                outcomes = [self.await_task({'taskId': task_id}) for task_id in group['taskIds']]
        self.assertEqual(sum(task['status'] == 'SUCCEEDED' for task in outcomes), 2, outcomes)
        self.assertEqual(len(submitted), 2)

    def test_waiting_asset_cancel_never_submits_and_releases_reservation(self):
        self.capacity_wait_case(cancel=True)

    def test_waiting_asset_deadline_never_submits_and_releases_reservation(self):
        self.capacity_wait_case(cancel=False)

    def test_asset_action_failure_is_not_retried(self):
        from project_assistant import execution_governance as governance
        self.prepare()
        asset = self.ok(f'/episodes/{self.ep}/assets')['items'][0]
        with patch.object(worker, 'execute_story_card', side_effect=governance.CapacityUnavailable('Provider action already started')) as render:
            task = self.ok('/assets/' + asset['assetId'] + '/image-generations', 'POST', {'appCode': 'flux-soul-cast'})
            result = self.await_task(task)
        self.assertEqual(result['status'], 'FAILED')
        render.assert_called_once()

    def await_task(self, task):
        end = time.monotonic() + 30
        while time.monotonic() < end:
            current = self.ok("/tasks/" + task["taskId"])
            if current["status"] not in ("QUEUED", "RUNNING"):
                return current
            time.sleep(.05)
        self.fail("Story task did not finish")

    def test_catalog_envelope_validation_and_auth(self):
        self.assertEqual(self.ok("/capabilities")["stages"], story.STAGES)
        self.assertTrue(self.ok("/catalog/apps?capability=VIDEO")["items"])
        self.assertTrue(self.ok("/catalog/apps?capability=IMAGE")["items"])
        code, payload = self.call("/catalog/apps?capability=AUDIO")
        self.assertEqual((code, payload["code"]), (422, "DRAMA_VALIDATION_FAILED"))
        code, payload, _ = self.request(story.BASE + "/capabilities", authenticated=False)
        self.assertEqual((code, payload["code"]), (401, "DRAMA_AUTH_MISSING"))
        repo.upsert_member(self.conn, self.actor, "Viewer", "viewer"); self.conn.commit()
        self.assertEqual(self.call("/projects", "POST", {"title": "denied"})[0], 409)

    def test_idempotency_is_atomic_and_persisted(self):
        slug = self.slug + "-i"; self.extra_projects.append(slug)
        body = {"title": "Checkpoint", "slug": slug}
        headers = {"Idempotency-Key": "same-project"}
        first = self.ok("/projects", "POST", body, headers)
        self.assertEqual(first, self.ok("/projects", "POST", body, headers))
        code, payload = self.call("/projects", "POST", {**body, "title": "different"}, headers)
        self.assertEqual((code, payload["code"]), (409, "DRAMA_IDEMPOTENCY_CONFLICT"))
        self.assertEqual(self.call("/projects", "POST", body, {"Idempotency-Key": "x" * 129})[0], 422)

    def test_baseline_variants_and_bidirectional_sheet_edits(self):
        code, payload = self.call(f"/episodes/{self.ep}/storyboards", "POST", {})
        self.assertEqual((code, payload["code"]), (409, "DRAMA_STAGE_PRECONDITION"))
        shots = self.prepare()
        assets = self.ok(f"/episodes/{self.ep}/assets")["items"]
        actor = next(a for a in assets if a["assetCode"] == "CAST-01")
        variant = self.ok(f"/assets/{actor['assetId']}/variants", "POST", {"name": "Night", "key": "night", "kind": "OUTFIT", "prompt": "Night jacket"})
        self.assertEqual(variant["assetCode"], "CAST-01:NIGHT")
        self.assertEqual(variant['kind'], 'OUTFIT')
        self.assertIn('ARRI Alexa', shots[0]['opticalRig'])
        self.assertEqual(len(self.ok("/assets/" + actor["assetId"])["variants"]), 1)
        selected = shots[0]
        self.ok(f"/shots/{selected['shotId']}/assets", "PUT", {"assetCodes": ["CAST-01:NIGHT"]})
        self.assertIn("@CAST-01:NIGHT", story.find_row(self.conn, selected["shotId"], "shot")[1]["cells"][3])
        story.mutate_row(self.conn, self.me, self.slug, "cinema-studio", selected["rowId"], {3: "Manual UI change @CAST-01"})
        self.conn.commit()
        self.assertEqual(self.ok("/shots/" + selected["shotId"])["description"], "Manual UI change @CAST-01")
        self.ok(f"/episodes/{self.ep}/script", "PUT", {"scriptContent": "Scene 01: Changed\n@CAST-01"})
        self.assertTrue(self.ok(f"/episodes/{self.ep}")["scriptDirty"])
        self.assertEqual(self.call(f"/episodes/{self.ep}/storyboards", "POST", {})[0], 409)
        self.ok(f"/episodes/{self.ep}/asset-extractions", "POST", {})
        self.assertFalse(self.ok(f"/episodes/{self.ep}")["scriptDirty"])
        self.assertGreaterEqual(len(self.ok(f"/episodes/{self.ep}/script/versions")["items"]), 3)

    def test_files_import_multi_episode_and_xor(self):
        self.assertEqual(self.call("/project-imports", "POST", {"title": "bad"})[0], 400)
        raw = b"Episode 1\nScene 01: Arrival\n@CAST-01\nEpisode 2\nScene 01: Exit\n@CAST-01"
        code, payload, _ = self.request(story.BASE + "/files", method="POST", raw=raw,
                                       headers={"Content-Type": "text/plain", "X-File-Name": "story.md"})
        self.assertEqual(code, 200, payload)
        file = payload["data"]
        self.assertEqual(file["size"], str(len(raw)))
        with patch.object(story, 'file_bytes', side_effect=AssertionError('metadata must not read a blob')):
            self.assertEqual(self.ok('/files/' + file['fileId'])['size'], str(len(raw)))
            self.assertEqual(self.ok('/files/' + file['fileId'] + '/url')['url'], file['url'])
        slug = self.slug + "-i"; self.extra_projects.append(slug)
        imported = self.ok("/project-imports", "POST", {"slug": slug, "title": "Episodes", "scriptFileId": file["fileId"]})
        self.assertEqual(imported["result"]["episodeCount"], 2)
        self.assertEqual(len(self.ok(f"/projects/pj_{slug}/episodes")["items"]), 2)
        self.assertEqual(self.request(file["url"])[1], raw)

    def generation_inputs(self, identifier, video=None):
        from PIL import Image
        if video is None:
            import subprocess, tempfile
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'source.mp4'
                subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=64x64:r=8:d=0.5',
                    '-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart',str(path)],check=True,timeout=15)
                video=path.read_bytes()
        image=io.BytesIO();Image.new('RGB',(16,16),'blue').save(image,format='PNG')
        aid=repo.put_asset(self.conn,self.slug,data=image.getvalue(),content_type='image/png',actor_id=self.actor)
        vid=repo.put_asset(self.conn,self.slug,data=video,content_type='video/mp4',actor_id=self.actor)
        _,row=story.find_row(self.conn,identifier,'shot')
        story.mutate_row(self.conn,self.me,self.slug,row['tabKey'],row['rid'],
            {4:f'![Image](/projects/api/{self.slug}/assets/{aid})',5:f'[Video](/projects/api/{self.slug}/assets/{vid})'})
        self.conn.commit()
        return f'/projects/api/{self.slug}/assets/{vid}'

    def test_generation_candidates_split_merge_and_real_film(self):
        import subprocess
        import tempfile
        shots = self.prepare()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "clip.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=160x96:r=24", "-t", "0.25", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)], check=True)
            raw = path.read_bytes()
        def render(task, card, values, head):
            self.assertIn(card["card_id"], ("h3-short-video-v3", "h3-optimize"))
            return head.upload(task, raw, "video/mp4")
        identifier = shots[0]["shotId"]
        source = self.generation_inputs(identifier, raw)
        with patch.object(worker, "execute_story_card", side_effect=render):
            done = self.await_task(self.ok(f"/shots/{identifier}/video-generations", "POST", {"appCode": "2109942725885075458", "modelParams":{"driving_video":source}}))
        self.assertEqual(done["status"], "SUCCEEDED", done)
        candidates = self.ok(f"/shots/{identifier}/videos")["items"]
        self.assertTrue(candidates)
        self.ok(f"/shots/{identifier}/selected-video", "PUT", {"videoId": candidates[0]["videoId"]})
        story.mutate_row(self.conn, self.me, self.slug, 'cinema-studio', shots[1]['rowId'], {5: '[video](' + candidates[0]['url'] + ')'})
        self.conn.commit()
        split = self.ok(f"/shots/{identifier}/splits", "POST", {})
        self.assertEqual(len(split["shots"]), 2)
        self.ok("/shot-merges", "POST", {"shotIds": [s["shotId"] for s in split["shots"]]})
        film = self.await_task(self.ok(f"/episodes/{self.ep}/films", "POST", {}))
        self.assertEqual(film["status"], "SUCCEEDED", film)
        output = self.request(film["result"]["videoUrl"])[1]
        self.assertLess(output.find(b"moov"), output.find(b"mdat"))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'episode.mp4'; path.write_bytes(output)
            metadata = worker._probe_video(path)
            self.assertGreaterEqual(metadata['duration'], 0.49)
        self.assertTrue(self.ok(f"/episodes/{self.ep}/films")["items"])

    def test_late_render_is_candidate_only_after_a_manual_edit(self):
        from PIL import Image
        ready, release = threading.Event(), threading.Event()
        raw = io.BytesIO(); Image.new('RGB', (8, 8), 'blue').save(raw, format='PNG')
        identifier = self.prepare()[0]["shotId"]
        def render(task, card, values, head):
            ready.set(); release.wait(10)
            return head.upload(task, raw.getvalue(), 'image/png')
        with patch.object(worker, 'execute_story_card', side_effect=render):
            task = self.ok(f'/shots/{identifier}/image-generations', 'POST', {'appCode': 'LOCAL_SDXL_SMOKE'})
            self.assertTrue(ready.wait(10))
            self.ok('/shots/' + identifier, 'PATCH', {'description': 'A newer director instruction'})
            release.set()
            done = self.await_task(task)
        self.assertEqual(done['status'], 'SUCCEEDED', done)
        self.assertFalse(done['result']['selected'])
        self.assertIsNone(self.ok('/shots/' + identifier)['selectedImageUrl'])
        self.assertTrue(self.ok('/shots/' + identifier + '/images')['items'])

    def test_imported_cards_are_authenticated_persisted_and_in_catalog(self):
        card_id = 'test-card-' + self.slug
        body = {'card_id': card_id, 'workflow': {'1': {'class_type': 'LoadImage', 'inputs': {'image': 'test.png'}}, '2': {'class_type': 'SaveImage', 'inputs': {'images': ['1', 0], 'filename_prefix': 'test'}}}}
        path = '/openapi/v2/cards/register'
        self.assertEqual(self.request(path, method='POST', data=body, authenticated=False)[0], 401)
        code, payload, _ = self.request(path, method='POST', data=body)
        self.assertEqual(code, 200, payload)
        with worker._OPENAPI_LOCK:
            worker._OPENAPI_CARDS.pop(card_id, None)
        story.restore_cards(self.conn)
        self.assertTrue(any(a['card_id'] == card_id for a in self.ok('/catalog/apps?capability=IMAGE')['items']))
        body['workflow'] = 'C:/secret.json'
        self.assertEqual(self.request(path, method='POST', data=body)[0], 422)
        with worker._OPENAPI_LOCK:
            worker._OPENAPI_CARDS.pop(card_id, None)
            worker._OPENAPI_CARDS.pop(payload['webappId'], None)

    def test_multi_episode_shots_variants_patch_and_scene_rebuild(self):
        first = self.prepare()
        ep = self.ok(f'/projects/pj_{self.slug}/episodes', 'POST', {'title': 'Second Episode'})
        second_id = ep['episodeId']
        self.ok('/episodes/' + second_id + '/script', 'PUT', {'scriptContent': 'Scene 01: Second\n@CAST-02 runs.'})
        self.ok('/episodes/' + second_id + '/asset-extractions', 'POST', {})
        self.ok('/episodes/' + second_id + '/storyboards', 'POST', {})
        second = self.ok('/episodes/' + second_id + '/shots')['items']
        self.assertEqual(len(second), 1)
        self.assertFalse({s['shotId'] for s in first} & {s['shotId'] for s in second})
        self.assertEqual(self.call('/episodes/' + second_id + '/shot-video-generations', 'POST', {'appCode': 'h3-reference', 'shotIds': [first[0]['shotId']]})[0], 422)
        scene = self.ok('/episodes/' + second_id + '/scenes')['items'][0]
        self.ok('/scenes/' + scene['sceneId'], 'PATCH', {'content': '@CAST-02 stops at the door.'})
        self.assertEqual(self.call('/scenes/' + scene['sceneId'] + '/shot-rebuilds', 'POST', {})[0], 409)
        self.ok('/episodes/' + second_id + '/asset-extractions', 'POST', {})
        self.ok('/scenes/' + scene['sceneId'] + '/shot-rebuilds', 'POST', {})
        self.assertIn('stops at the door', self.ok('/shots/' + second[0]['shotId'])['description'])

    def test_webhooks_sign_exact_bytes_mask_secrets_and_bound_retries(self):
        from urllib.parse import urlsplit
        from unittest.mock import MagicMock
        import hashlib, hmac
        with patch.object(story, 'webhook_address', return_value=(urlsplit('https://example.org/hook'), '93.184.216.34')), patch.object(story._POOL, 'submit'):
            hook = self.ok('/webhooks', 'POST', {'url': 'https://example.org/hook'})
            self.assertNotEqual(self.ok('/webhooks')['items'][0]['secret'], hook['secret'])
            delivery = self.ok('/webhooks/' + hook['webhookId'] + '/test-deliveries', 'POST', {})
        transport = MagicMock(); transport.getresponse.return_value.status = 202
        with patch.object(story, 'webhook_address', return_value=(urlsplit(hook['url']), '93.184.216.34')), patch.object(story, 'HTTPSConnection', return_value=transport), patch.object(story.socket, 'create_connection'), patch.object(story.ssl, 'create_default_context'):
            story.deliver(delivery['deliveryId'])
        method, path, raw, headers = transport.request.call_args.args
        stamp = headers['X-RH-Signature'].split(',')[0][2:]
        expected = hmac.new(hook['secret'].encode(), stamp.encode() + b'.' + raw, hashlib.sha256).hexdigest()
        self.assertEqual(headers['X-RH-Signature'], f't={stamp},v1={expected}')
        self.assertEqual(self.ok('/webhooks/' + hook['webhookId'] + '/deliveries')['items'][0]['status'], 'SUCCEEDED')
        with patch.object(story._POOL, 'submit'):
            failed = self.ok('/webhooks/' + hook['webhookId'] + '/test-deliveries', 'POST', {})
        with patch.object(story, 'webhook_address', side_effect=ValueError('offline')), patch.object(story, 'retry_delivery') as retry:
            for _ in range(6):
                story.deliver(failed['deliveryId'])
            self.assertEqual(retry.call_count, 5)
        self.assertEqual(story.record(self.conn, failed['deliveryId'])['status'], 'DEAD')

    def test_script_refinement_is_configured_async_and_invalidates_baseline(self):
        from types import SimpleNamespace
        from project_assistant import providers
        self.prepare()
        path = '/episodes/' + self.ep + '/script-refinements'
        with patch.dict(os.environ, {'OPENBENCH_MODEL': '', 'OPENBENCH_API_BASE': ''}):
            self.assertEqual(self.call(path, 'POST', {'instruction': 'Improve pacing'})[0], 409)
        with patch.dict(os.environ, {'OPENBENCH_PROVIDER': 'openai_compat', 'OPENBENCH_MODEL': 'local-test', 'OPENBENCH_API_BASE': 'http://127.0.0.1:11434/v1'}), patch.object(providers, 'run_openai_compat_turn', return_value=SimpleNamespace(status='ok', answer='Scene 01: Revised\\n@CAST-01 pauses.')):
            done = self.await_task(self.ok(path, 'POST', {'instruction': 'Improve pacing'}))
        self.assertEqual(done['status'], 'SUCCEEDED', done)
        self.assertTrue(self.ok('/episodes/' + self.ep)['scriptDirty'])
        self.assertIn('Revised', self.ok('/episodes/' + self.ep)['scriptContent'])

    def test_batch_group_counts_are_strings_and_outputs_are_per_row(self):
        from PIL import Image
        data = io.BytesIO(); Image.new('RGB', (8, 8), 'green').save(data, format='PNG')
        shots = self.prepare()
        with patch.object(worker, 'execute_story_card', side_effect=lambda task, card, values, head: head.upload(task, data.getvalue(), 'image/png')):
            group = self.ok('/episodes/' + self.ep + '/shot-image-generations', 'POST', {'appCode': 'LOCAL_SDXL_SMOKE', 'shotIds': [s['shotId'] for s in shots]})
            for identifier in group['taskIds']:
                self.assertEqual(self.await_task({'taskId': identifier})['status'], 'SUCCEEDED')
        detail = self.ok('/task-groups/' + group['taskGroupId'])
        self.assertEqual(detail['counts']['succeeded'], '2')
        self.assertTrue(all(isinstance(v, str) for v in detail['counts'].values()))

    def test_cancel_preserves_new_selection_and_explicit_retry(self):
        identifier = self.prepare()[0]["shotId"]
        source = self.generation_inputs(identifier)
        queued = []
        with patch.object(story._POOL, "submit", side_effect=lambda *args: queued.append(args)):
            task = self.ok(f"/shots/{identifier}/video-generations", "POST", {"appCode": "h3-reference", "modelParams":{"driving_video":source}})
            self.ok("/tasks/" + task["taskId"] + "/cancellations", "POST", {})
            retry = self.ok("/tasks/" + task["taskId"] + "/retries", "POST", {})
        self.assertNotEqual(task["taskId"], retry["taskId"])
        self.assertEqual(self.ok("/tasks/" + task["taskId"])["status"], "CANCELED")
        self.assertEqual(len(queued), 2)
