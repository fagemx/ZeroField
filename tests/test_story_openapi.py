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
        with patch.object(worker, "execute_story_card", side_effect=render):
            done = self.await_task(self.ok(f"/shots/{identifier}/video-generations", "POST", {"appCode": "2109942725885075458"}))
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
        queued = []
        with patch.object(story._POOL, "submit", side_effect=lambda *args: queued.append(args)):
            task = self.ok(f"/shots/{identifier}/video-generations", "POST", {"appCode": "h3-reference"})
            self.ok("/tasks/" + task["taskId"] + "/cancellations", "POST", {})
            retry = self.ok("/tasks/" + task["taskId"] + "/retries", "POST", {})
        self.assertNotEqual(task["taskId"], retry["taskId"])
        self.assertEqual(self.ok("/tasks/" + task["taskId"])["status"], "CANCELED")
        self.assertEqual(len(queued), 2)
