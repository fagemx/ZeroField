"""v2 authority regressions: real authenticated HTTP/PG/executor; inference substituted."""
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
import unittest
import uuid
from unittest.mock import Mock, patch

from PIL import Image
from project_assistant import limb_worker as worker
from project_assistant.studio import openapi_v2_hub as hub
from project_docs import repository as repo, story_openapi as story
import test_product_http as fixture


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "isolated PostgreSQL required")
class V2AuthorityTests(unittest.TestCase):
    request = fixture.ProductHTTPTests.request

    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory()
        cls.addClassCleanup(folder.cleanup)
        video = Path(folder.name) / "synthetic.mp4"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "color=c=blue:s=64x64:r=8:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)],
                       check=True, capture_output=True, timeout=15)
        cls.video = video.read_bytes()
        class Provider(BaseHTTPRequestHandler):
            def log_message(self, *unused):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                cls.provider_calls.append(self.path)
                if self.path.endswith("/media/upload/binary"):
                    if cls.on_upload:
                        callback, cls.on_upload = cls.on_upload, None
                        callback()
                    result = {"code": 0, "data": {"fileName": "synthetic-reference"}}
                elif self.path.endswith("/query"):
                    result = {"code": 0, "status": "SUCCESS", "results": [
                        {"url": cls.provider_base + "/output.mp4", "outputType": "mp4"}]}
                else:
                    result = {"code": 0, "status": "RUNNING", "taskId": "synthetic-provider"}
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.end_headers()
                self.wfile.write(cls.video)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        cls.provider_base = "http://127.0.0.1:" + str(server.server_port)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        cls.addClassCleanup(server.server_close)
        cls.addClassCleanup(server.shutdown)

    def setUp(self):
        fixture.ProductHTTPTests.setUp(self)
        from governance_fixture import authorize_synthetic_media
        authorize_synthetic_media(self)
        self.policy_env = patch.dict(os.environ, {"OPENBENCH_PRODUCTION_POLICY": "hybrid_studio"})
        self.policy_env.start()
        self.other = str(uuid.uuid4())
        self.other_slug = "v2-other-" + uuid.uuid4().hex[:12]
        repo.upsert_member(self.conn, self.other, "Other synthetic crew", "member")
        repo.upsert_project(self.conn, self.other_slug, "Other synthetic production")
        self.conn.commit()
        stream = io.BytesIO()
        Image.new("RGB", (2, 2), "blue").save(stream, "PNG")
        self.raw = stream.getvalue()
        self.card_ids = []
        self.tasks = []
        type(self).provider_calls = []
        type(self).on_upload = None
        self.client = Mock()
        self.client.upload_media.return_value = "comfy-reference.png"
        self.client.submit_workflow.return_value = "synthetic-job"
        self.client.fetch_history.return_value = {"synthetic-job": {"status": {"completed": True}, "outputs": {
            "2": {"images": [{"filename": "synthetic.png"}]}}}}
        self.client.download_output.return_value = (self.raw, "image/png")
        self.comfy = patch.object(worker, "ComfyPlatformClient", return_value=self.client)
        self.comfy.start()

    def tearDown(self):
        self.comfy.stop()
        self.policy_env.stop()
        with worker._OPENAPI_LOCK:
            for key, (card, _) in list(worker._OPENAPI_CARDS.items()):
                if card["card_id"] in self.card_ids:
                    worker._OPENAPI_CARDS.pop(key)
            for task in self.tasks:
                worker._OPENAPI_TASKS.pop(task[0], None)
                getattr(hub, "_OPENAPI_EXECUTIONS", {}).pop(task[0], None)
        self.conn.rollback()
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM projectops.story_record WHERE owner_id IN (%s,%s)", (self.actor, self.other))
            cur.execute("DELETE FROM projectops.project WHERE slug=%s", (self.other_slug,))
            cur.execute("DELETE FROM projectops.member WHERE actor_id=%s", (self.other,))
        self.conn.commit()
        fixture.ProductHTTPTests.tearDown(self)

    def upload(self, *, actor=None, slug=None, raw=None, mime="image/png"):
        raw = self.raw if raw is None else raw
        headers = {"X-Project-Slug": slug or self.slug, "Content-Type": mime}
        if actor:
            tokens = json.loads(os.environ["OPENBENCH_TOKENS"])
            tokens["synthetic-victim-fixture-token"] = actor
            headers["Authorization"] = "Bearer synthetic-victim-fixture-token"
            with patch.dict(os.environ, {"OPENBENCH_TOKENS": json.dumps(tokens)}):
                code, payload, _ = self.request("/openapi/v2/media/upload/binary", method="POST", raw=raw, headers=headers)
        else:
            code, payload, _ = self.request("/openapi/v2/media/upload/binary", method="POST", raw=raw, headers=headers)
        self.assertEqual(code, 200, payload)
        return payload["data"]["fileName"]

    def imported(self, reference, *, exposed=True):
        identifier = "v2-default-" + uuid.uuid4().hex[:12]
        graph = {"1": {"class_type": "LoadImage", "inputs": {"image": reference}},
                 "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": "synthetic"}}}
        body = {"card_id": identifier, "workflow": graph, "webappId": identifier, "nodeInfoList": [
            {"nodeId": "1", "fieldName": "image", "fieldValue": reference},
            {"nodeId": "2", "fieldName": "filename_prefix", "fieldValue": "synthetic"}]}
        if not exposed:
            body["nodeInfoList"] = body["nodeInfoList"][1:]
        code, payload, _ = self.request("/openapi/v2/cards/register", method="POST", data=body)
        self.assertEqual(code, 200, payload)
        self.card_ids.append(identifier)
        return identifier

    def admit(self, identifier, body=None):
        captured = []
        # Hold only the dispatcher launch, not the real HTTP handler or executor.
        with patch.object(hub, "_execute_openapi_task", side_effect=lambda *args: captured.append(args)):
            code, result, _ = self.request("/openapi/v2/run/ai-app/" + identifier, method="POST",
                data=body or {"nodeInfoList": [{"nodeId": "2", "fieldName": "filename_prefix", "fieldValue": "own-output"}]},
                headers={"X-Project-Slug": self.slug})
            if code == 200:
                until = time.monotonic() + 2
                while not captured and time.monotonic() < until:
                    time.sleep(.01)
                self.assertTrue(captured, result)
                self.tasks.append(captured[0])
        return code, result, captured[0] if captured else None

    def execute(self, args):
        hub._execute_openapi_task(*args)
        return worker.openapi_query_task({"taskId": args[0]})

    def hybrid(self):
        story.store(self.conn, "policy_" + self.slug, "production_policy", {"productionPolicy": "hybrid_studio"}, self.slug)
        self.conn.commit()

    def vendor(self):
        self.hybrid()
        return self.admit("seedance-20-pro", {"nodeInfoList": [
            {"nodeId": "prompt", "fieldName": "prompt", "fieldValue": "Original synthetic set"}]})

    def test_imported_victim_default_is_rejected_before_admission(self):
        identifier = self.imported(self.upload(actor=self.other))
        code, result, _ = self.admit(identifier)
        self.assertEqual(code, 404, result)
        self.client.upload_media.assert_not_called()
        self.client.submit_workflow.assert_not_called()

    def test_imported_same_actor_wrong_project_default_is_rejected(self):
        identifier = self.imported(self.upload(slug=self.other_slug))
        code, result, _ = self.admit(identifier)
        self.assertEqual(code, 403, result)
        self.client.upload_media.assert_not_called()

    def test_queued_policy_revocation_prevents_graphless_export(self):
        code, result, args = self.vendor()
        self.assertEqual(code, 200, result)
        story.store(self.conn, "policy_" + self.slug, "production_policy", {"productionPolicy": "open_weights_only"}, self.slug)
        self.conn.commit()
        with patch.object(worker, "execute_vendor_card", return_value={"asset_url": "/fake", "content_type": "video/mp4"}) as vendor:
            done = self.execute(args)
        self.assertEqual(done["status"], "FAILED", done)
        vendor.assert_not_called()

    def test_media_expansion_distinguishes_links_and_nested_upload_handles(self):
        identifier = "a" * 64 + ".png"
        reference = "b" * 64 + ".png"
        graph = {identifier: {"inputs": {}}, "2": {"inputs": {"images": [identifier, 0], "nested": {"refs": [reference]}}}}
        slots = list(hub._media_slots({"nodes": []}, graph, []))
        self.assertEqual([value for _, _, value in slots], [reference])

    def test_unexposed_and_hidden_defaults_are_authorized_without_reading_bytes(self):
        reference = self.upload(actor=self.other)
        for exposed in (False, True):
            identifier = self.imported(reference, exposed=exposed)
            if exposed:
                with worker._OPENAPI_LOCK:
                    worker._OPENAPI_CARDS[identifier][0]["nodes"][0]["hidden"] = True
            with patch.object(worker, "openapi_get_media", side_effect=AssertionError("No blob before grant")):
                code, result, _ = self.admit(identifier)
            self.assertEqual(code, 404, result)
        self.client.submit_workflow.assert_not_called()

    def test_own_project_default_frozen_once_and_executor_replay_is_inert(self):
        reference = self.upload()
        identifier = self.imported(reference, exposed=False)
        with patch.object(worker, "_resolve_openapi_card_and_workflow", wraps=worker._resolve_openapi_card_and_workflow) as resolve:
            code, result, args = self.admit(identifier)
        self.assertEqual(code, 200, result)
        self.assertEqual(resolve.call_count, 1)
        # Mutating every public copy cannot replace the private, authorized execution plan.
        with worker._OPENAPI_LOCK:
            worker._OPENAPI_CARDS[identifier][1]["1"]["inputs"]["image"] = "ungranted.png"
            worker._OPENAPI_TASKS[args[0]]["compiled_workflow"]["1"]["inputs"]["image"] = "ungranted.png"
        args[2]["1"]["inputs"]["image"] = "ungranted.png"
        done = self.execute(args)
        self.assertEqual(done["status"], "SUCCESS", done)
        self.client.upload_media.assert_called_once_with(self.raw, "image/png", "openapi")
        self.assertEqual(self.client.submit_workflow.call_args.args[0]["1"]["inputs"]["image"], "comfy-reference.png")
        self.execute(args)
        self.client.submit_workflow.assert_called_once()
        code, queried, _ = self.request("/openapi/v2/query", method="POST", data={"taskId": args[0]})
        self.assertEqual(code, 200, queried)
        from urllib.parse import urlsplit
        self.assertEqual(self.request(urlsplit(queried["results"][0]["url"]).path)[1], self.raw)

    def test_queued_privacy_member_and_project_access_revocation(self):
        from project_assistant import store
        changes = ("mask", "viewer", "inactive", "project-access")
        for change in changes:
            code, result, args = self.vendor()
            self.assertEqual(code, 200, result)
            if change == "mask":
                repo.update_project_meta(self.conn, self.slug, privacy_mode="mask_numbers")
            elif change == "project-access":
                store.set_member_enabled(self.conn, self.slug, self.actor, False, self.actor)
            else:
                repo.upsert_member(self.conn, self.actor, "Synthetic crew", "viewer" if change == "viewer" else "admin",
                                   status="inactive" if change == "inactive" else "active")
            self.conn.commit()
            with patch.object(worker, "execute_vendor_card") as vendor:
                self.assertEqual(self.execute(args)["status"], "FAILED", change)
                vendor.assert_not_called()
            repo.upsert_member(self.conn, self.actor, "Synthetic crew", "admin")
            repo.update_project_meta(self.conn, self.slug, privacy_mode="full_access")
            store.set_member_enabled(self.conn, self.slug, self.actor, True, self.actor)
            self.conn.commit()

    def test_reference_grant_rechecked_at_execution_and_before_submit(self):
        reference = self.upload()
        identifier = self.imported(reference)
        _, _, args = self.admit(identifier)
        grant = "v2_" + story.digest([self.actor, "media", reference])
        story.remove(self.conn, grant)
        self.conn.commit()
        self.assertEqual(self.execute(args)["status"], "FAILED")
        self.client.upload_media.assert_not_called()
        self.upload()
        _, _, args = self.admit(identifier)
        original_read = hub.openapi_get_media
        def revoke_after_read(reference):
            result = original_read(reference)
            story.remove(self.conn, grant)
            self.conn.commit()
            return result
        with patch.object(hub, "openapi_get_media", side_effect=revoke_after_read):
            self.assertEqual(self.execute(args)["status"], "FAILED")
        self.client.upload_media.assert_not_called()
        # Revocation during a completed upload cannot be reversed, but prevents submission.
        self.upload()
        _, _, args = self.admit(identifier)
        def revoke_after_upload(*unused):
            story.remove(self.conn, grant)
            self.conn.commit()
            return "uploaded.png"
        self.client.upload_media.side_effect = revoke_after_upload
        self.assertEqual(self.execute(args)["status"], "FAILED")
        self.client.upload_media.assert_called_once()
        self.client.submit_workflow.assert_not_called()

    def test_current_authority_blocks_late_result_publication_and_cancel_replay(self):
        from project_assistant import store
        reference = self.upload()
        identifier = self.imported(reference)
        _, _, args = self.admit(identifier)
        def revoke_before_result(*unused):
            store.set_member_enabled(self.conn, self.slug, self.actor, False, self.actor)
            self.conn.commit()
            return self.raw, "image/png"
        self.client.download_output.side_effect = revoke_before_result
        done = self.execute(args)
        self.assertEqual((done["status"], done["results"]), ("FAILED", []))
        self.execute(args)
        self.client.submit_workflow.assert_called_once()
        store.set_member_enabled(self.conn, self.slug, self.actor, True, self.actor)
        self.conn.commit()
        _, _, canceled = self.admit(identifier)
        with worker._OPENAPI_LOCK:
            worker._OPENAPI_TASKS[canceled[0]]["status"] = "CANCELED"
        self.execute(canceled)
        self.assertEqual(worker._OPENAPI_TASKS[canceled[0]]["status"], "CANCELED")
        self.client.submit_workflow.assert_called_once()

    def test_http_fields_and_missing_capability_cannot_forge_execution_authority(self):
        body = {"production_policy": "hybrid_studio", "http_bound": False,
                "_authority": {"check": "always-authorize", "actor_id": self.actor},
                "nodeInfoList": [{"nodeId": "prompt", "fieldName": "prompt", "fieldValue": "Original synthetic set"}]}
        code, result, _ = self.admit("seedance-20-pro", body)
        self.assertEqual(code, 400, result)
        with self.assertRaisesRegex(worker.WorkerError, "in-process"):
            worker.openapi_run_app("seedance-20-pro", body, _authority=body["_authority"])
        identifier = self.imported(self.upload())
        _, _, args = self.admit(identifier)
        hub._OPENAPI_EXECUTIONS.pop(args[0])
        done = self.execute(args)
        self.assertEqual(done["status"], "FAILED", done)
        self.client.submit_workflow.assert_not_called()

    def test_http_executor_errors_do_not_echo_secrets_or_provider_urls(self):
        identifier = self.imported(self.upload())
        _, _, args = self.admit(identifier)
        self.client.submit_workflow.side_effect = ValueError("fixture-secret https://provider.invalid/take?signed=secret")
        self.client.close.side_effect = ValueError("cleanup fixture-secret ?signed=secret")
        done = self.execute(args)
        self.assertEqual(done["status"], "FAILED")
        self.assertNotIn("fixture-secret", json.dumps(done))
        self.assertNotIn("signed=", json.dumps(done))

    def test_official_sdk_uses_authorized_default_and_no_real_service(self):
        from types import SimpleNamespace
        identifier = self.imported(self.upload())
        with worker._OPENAPI_LOCK:
            worker._OPENAPI_CARDS[identifier][0]["engine_config"]["platform"] = "comfy_sdk"
        _, _, args = self.admit(identifier)
        sdk = Mock()
        sdk.assets.from_bytes.return_value = "sdk-reference"
        sdk.submit.return_value.id = "synthetic-sdk"
        output = SimpleNamespace(node_id="2", name="synthetic.png", content_type="image/png", to_stream=lambda stream: stream.write(self.raw))
        sdk.jobs.get.return_value = SimpleNamespace(status="succeeded", outputs=[output])
        self.comfy.stop()
        with patch.dict("sys.modules", {"comfy_sdk": SimpleNamespace(Comfy=Mock(return_value=sdk))}), patch.dict(os.environ, {
                "COMFY_API_KEY": "", "COMFY_ROUTER_TOKEN": "", "COMFY_BASE_URL": "https://synthetic.invalid"}):
            done = self.execute(args)
        self.assertEqual(done["status"], "SUCCESS", done)
        self.assertEqual(sdk.assets.from_bytes.call_args.args[0], self.raw)
        sdk.submit.assert_called_once()
        sdk.close.assert_called_once()

    def provider_env(self):
        return patch.dict(os.environ, {"SEEDANCE_API_URL": self.provider_base + "/vendor", "SEEDANCE_API_KEY": "synthetic-credential",
                                      "RUNNINGHUB_API_URL": self.provider_base + "/cloud", "RUNNINGHUB_API_KEY": "synthetic-credential"})

    def test_graphless_vendor_and_cloud_keep_current_http_authority(self):
        from urllib.parse import urlsplit
        self.hybrid()
        image = self.upload()
        video = self.upload(raw=self.video, mime="video/mp4")
        bodies = {
            "seedance-20-pro": [{"nodeId": "prompt", "fieldName": "prompt", "fieldValue": "Original synthetic set"},
                                {"nodeId": "ref_1", "fieldName": "image_url", "fieldValue": image},
                                {"nodeId": "duration", "fieldName": "duration", "fieldValue": 1}],
            "rh-cloud-h3-burst": [{"nodeId": "27", "fieldName": "video", "fieldValue": video},
                                  {"nodeId": "51", "fieldName": "image", "fieldValue": image},
                                  {"nodeId": "259", "fieldName": "value", "fieldValue": 1}]}
        with self.provider_env():
            for identifier, nodes in bodies.items():
                code, result, args = self.admit(identifier, {"nodeInfoList": nodes})
                self.assertEqual(code, 200, result)
                with patch.object(worker, "comfyui", side_effect=AssertionError("Comfy must stay offline")):
                    done = self.execute(args)
                self.assertEqual(done["status"], "SUCCESS", done)
                self.assertIsNone(done["compiledWorkflow"])
                code, result, _ = self.request("/openapi/v2/query", method="POST", data={"taskId": args[0]})
                self.assertEqual(code, 200, result)
                code, raw, _ = self.request(urlsplit(result["results"][0]["url"]).path)
                self.assertEqual(code, 200)
                self.assertLess(raw.index(b"moov"), raw.index(b"mdat"))
        self.client.submit_workflow.assert_not_called()
        self.assertIn("/cloud/run/ai-app/2109942725885075459", self.provider_calls)
        self.assertIn("/vendor/run", self.provider_calls)

    def test_remote_upload_revocation_prevents_paid_submit_and_output(self):
        self.hybrid()
        image = self.upload()
        def revoke():
            story.store(self.conn, "policy_" + self.slug, "production_policy", {"productionPolicy": "open_weights_only"}, self.slug)
            self.conn.commit()
        type(self).on_upload = revoke
        body = {"nodeInfoList": [{"nodeId": "prompt", "fieldName": "prompt", "fieldValue": "Original synthetic set"},
                                  {"nodeId": "ref_1", "fieldName": "image_url", "fieldValue": image}]}
        with self.provider_env():
            code, result, args = self.admit("seedance-20-pro", body)
            self.assertEqual(code, 200, result)
            done = self.execute(args)
        self.assertEqual((done["status"], done["results"]), ("FAILED", []))
        self.assertEqual(self.provider_calls, ["/vendor/media/upload/binary"])


if __name__ == "__main__":
    unittest.main()
