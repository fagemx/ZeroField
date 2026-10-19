"""Mechanical Studio extraction compatibility; routing is covered by its component owner."""
import ast
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import tempfile
import threading
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from project_assistant import limb_worker as worker, studio
from project_assistant.studio import (
    _compat, card_engine, context_compiler, ffmpeg_runtime, media_prep,
    openapi_v2_hub, runtime, model_router,
)


LEGACY_FUNCTIONS = """
WorkerError TransientWorkerError NoRedirect fetch json_fetch configured_token Head
prompt_text llm _media_urls _studio_row snap_dimensions snap_frame_count
validate_studio_card load_studio_card aspect_for slot_plan build_node_info
convert_litegraph_to_api _unlink_node_and_dependents inject_node_info_into_workflow
compute_request_fingerprint compile_h3_agent_instruction_prompt compile_h3_context_ir
compile_ltx_ingredients_prompt resolve_studio_context resolve_pass2_source
_context_value _shot_media_candidates bind_external_workflow
parse_runninghub_curl_or_payload extract_studio_card_from_workflow ComfyPlatformClient
_build_card_form_values _normalize_comfy_error comfyui execute_story_card
ffmpeg_binary _probe_video _run_preparation bound_output_video_duration
build_video_frame_sheet build_ingredients_sheet solve_ik _compute_rig_pose
_draw_pose_on_canvas render_lineworlds_media prepare_reference_media bridge speech
assemble_files assemble_side_by_side ffmpeg acp_stdio _parse_multipart_file
openapi_upload_binary openapi_get_media openapi_register_card openapi_list_cards
_resolve_openapi_card_and_workflow _execute_openapi_task openapi_run_app
openapi_query_task process_one main
""".split()
LEGACY_STATE = """
MAX_MEDIA MAX_MATERIALS NON_TAKE_KINDS CARD_FIELD_TYPES CARD_SLOTS CARD_OUTPUT_MODES
CARDS_DIR _PASSTHROUGH_IMAGE_CLASSES _KNOWN_WIDGET_NAMES _MISSING _SDK_ENV_LOCK
ADAPTERS _OPENAPI_LOCK _OPENAPI_SEQ _OPENAPI_MEDIA_STORE _OPENAPI_CARDS _OPENAPI_TASKS
""".split()


class ModularCompatibilityTests(unittest.TestCase):
    def test_limb_worker_backward_compat_exports(self):
        self.assertLess(len(Path(worker.__file__).read_text(encoding="utf-8").splitlines()), 300)
        for name in LEGACY_FUNCTIONS + LEGACY_STATE:
            with self.subTest(name=name):
                self.assertIn(name, studio.__all__)
                self.assertIs(getattr(worker, name), getattr(studio, name))
        self.assertEqual(worker.resolve_studio_context.__module__, context_compiler.__name__)
        self.assertEqual(worker.ComfyPlatformClient.__module__, card_engine.__name__)
        self.assertEqual(worker.ffmpeg.__module__, media_prep.__name__)
        self.assertEqual(worker.openapi_run_app.__module__, openapi_v2_hub.__name__)
        for namespace in (studio, worker):
            self.assertIs(namespace.snap_dimensions_32, worker.snap_dimensions)
            self.assertIs(namespace.build_slot_plan, worker.slot_plan)
            self.assertIs(namespace.render_line_worlds_structure, worker.render_lineworlds_media)
            self.assertIs(namespace.openapi_run_ai_app, worker.openapi_run_app)
            self.assertIs(namespace.trim_video_duration_bounded, worker.bound_output_video_duration)

    def test_private_registry_and_sequence_are_live_not_copied(self):
        for name in ("_OPENAPI_LOCK", "_OPENAPI_CARDS", "_OPENAPI_TASKS", "_OPENAPI_MEDIA_STORE"):
            self.assertIs(getattr(worker, name), getattr(openapi_v2_hub, name))
        with patch.object(openapi_v2_hub, "_OPENAPI_SEQ", 123):
            self.assertEqual(worker._OPENAPI_SEQ, 123)
            self.assertEqual(studio._OPENAPI_SEQ, 123)
        self.assertIs(worker._context_value({}, "missing"), studio._MISSING)

    def test_package_and_facade_transport_patches_reach_extracted_client(self):
        for namespace in (worker, studio):
            with self.subTest(namespace=namespace.__name__), patch.object(namespace, "json_fetch", return_value={"prompt_id": "fixture-job"}) as request:
                client = card_engine.ComfyPlatformClient({"platform": "local", "base_url": "http://fixture.invalid"})
                self.assertEqual(client.submit_workflow({}, "test"), "fixture-job")
                request.assert_called_once()

    def test_media_limit_patch_reaches_client_and_head_without_rebinding(self):
        output = Mock(name="take.mp4", content_type="video/mp4")
        output.to_stream.side_effect = lambda stream: stream.write(b"12345")
        client = object.__new__(card_engine.ComfyPlatformClient)
        owners = dict(_compat.OWNERS)
        for namespace in (worker, studio):
            with self.subTest(namespace=namespace.__name__), patch.object(namespace, "MAX_MEDIA", 4):
                with self.assertRaisesRegex(worker.WorkerError, "exceeds 64 MB"):
                    client.download_output({"sdk_output": output})
                with self.assertRaisesRegex(worker.WorkerError, "64 MB"):
                    runtime.Head("http://fixture.invalid", "test").upload({}, b"12345", "video/mp4")
                self.assertEqual(runtime.MAX_MEDIA, 64 * 1024 * 1024)
        self.assertEqual(_compat.OWNERS, owners)
        self.assertEqual(worker.MAX_MEDIA, 64 * 1024 * 1024)

    def test_story_executor_uses_both_facade_and_package_comfy_seams(self):
        card = worker.load_studio_card("local-smoke")
        graph = {"1": {"class_type": "SaveImage", "inputs": {}}}
        for namespace in (worker, studio):
            with self.subTest(namespace=namespace.__name__), patch.object(namespace, "comfyui", return_value={"asset_url": "fixture"}) as execute:
                self.assertEqual(studio.execute_story_card({"workflow": graph}, card, {}, None), {"asset_url": "fixture"})
                path = Path(execute.call_args.args[1]["workflow"])
                self.assertFalse(path.exists(), "temporary workflow must be cleaned up")

    def test_owner_patch_and_missing_compat_name(self):
        with patch.object(runtime, "json_fetch", return_value={"prompt_id": "owner-patch"}):
            client = card_engine.ComfyPlatformClient({"platform": "local"})
            self.assertEqual(client.submit_workflow({}, "test"), "owner-patch")
        for namespace in (_compat, studio, worker):
            with self.assertRaises(AttributeError):
                getattr(namespace, "not_a_studio_api")

    def test_context_compiler_has_no_io_and_preserves_input(self):
        tree = ast.parse(Path(context_compiler.__file__).read_text(encoding="utf-8"))
        imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        self.assertFalse(any("subprocess" in ast.unparse(node) or "tempfile" in ast.unparse(node) for node in imports))
        task = {"input": {"prompt": "An original empty observatory"}}
        original = copy.deepcopy(task)
        with patch.object(runtime, "fetch", side_effect=AssertionError("no network")), patch.object(ffmpeg_runtime, "_run_preparation", side_effect=AssertionError("no media I/O")):
            self.assertIn("observatory", context_compiler.resolve_studio_context(task)["compiled_prompt"])
        self.assertEqual(task, original)

    def test_import_orders_wildcard_and_cli_help(self):
        commands = [
            "from project_assistant.studio import *; assert callable(main); assert callable(_probe_video)",
            "from project_assistant import limb_worker; from project_assistant.studio import card_engine; assert limb_worker.ComfyPlatformClient is card_engine.ComfyPlatformClient",
            "from project_assistant.studio import context_compiler; from project_assistant import limb_worker; assert context_compiler.resolve_studio_context is limb_worker.resolve_studio_context",
        ]
        for code in commands:
            result = subprocess.run([sys.executable, "-X", "utf8", "-c", code], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([sys.executable, "-X", "utf8", "-m", "project_assistant.limb_worker", "--help"], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--config", result.stdout)
        self.assertIn("--once", result.stdout)


class RouterTests(unittest.TestCase):
    """Real loopback HTTP/FFmpeg, synthetic inference; no GPU or vendor credentials."""
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.folder.cleanup)
        cls.video = Path(cls.folder.name) / "synthetic.mp4"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "color=c=blue:s=64x64:r=8:d=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(cls.video)],
                       check=True, capture_output=True, timeout=20)
        cls.raw = cls.video.read_bytes()
        cls.requests = []
        cls.mode = "success"

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # Signed URLs and authorization headers must not enter logs.

            def send(self, payload, status=200):
                raw = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                cls.get_requests.append((self.path, self.headers.get("Authorization")))
                if self.path.startswith("/openapi/v2/media/output/"):
                    raw, mime = worker.openapi_get_media(self.path.rsplit("/", 1)[1])
                    self.send_response(200)
                    self.send_header("Content-Type", mime)
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                if cls.mode == "redirect":
                    self.send_response(302)
                    self.send_header("Location", "http://169.254.169.254/secret")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.end_headers()
                self.wfile.write(cls.raw)

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                payload = json.loads(raw) if self.headers.get_content_type() == "application/json" else raw
                cls.requests.append((self.path, payload, self.headers.get("Authorization")))
                if self.path == "/product/upload":
                    self.send(worker.openapi_upload_binary(raw, self.headers.get_content_type()))
                elif self.path.startswith("/product/run/"):
                    try:
                        # Fixture stands in for an authorized HTTP integration, not real provider inference.
                        result = worker.openapi_run_app(self.path.rsplit("/", 1)[1], payload, base_url=cls.base,
                                                       sync=True, production_policy=payload.get("production_policy"))
                        self.send(result)
                    except worker.WorkerError as exc:
                        self.send({"error": str(exc)}, 400)
                elif self.path == "/product/query":
                    self.send(worker.openapi_query_task(payload))
                elif self.path.endswith("/media/upload/binary"):
                    self.send({"code": 0, "data": {"fileName": "uploaded-ref"}})
                elif cls.mode == "http-failure":
                    self.send({"secret": "fixture-credential", "url": "?signed=secret"}, 503)
                elif self.path.endswith("/query"):
                    if cls.mode == "failure":
                        self.send({"code": 0, "status": "FAILED", "errorMessage": "fixture-credential ?signed=secret"})
                    elif cls.mode == "bad-envelope":
                        self.send({"code": "0", "status": "SUCCESS"})
                    elif cls.mode == "pending":
                        self.send({"code": 0, "status": "RUNNING", "taskId": "fixture-job"})
                    else:
                        url = "http://169.254.169.254/secret" if cls.mode == "private-output" else cls.base + "/synthetic.mp4?signed=secret"
                        if cls.mode == "other-origin":
                            url = url.replace("127.0.0.1", "localhost")
                        self.send({"code": 0, "status": "SUCCESS", "results": [{"url": url, "outputType": "mp4"}]})
                else:
                    self.send({"code": 0, "status": "RUNNING", "taskId": "fixture-job"})

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = "http://127.0.0.1:" + str(cls.server.server_port)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.addClassCleanup(cls.server.server_close)
        cls.addClassCleanup(cls.server.shutdown)

    def setUp(self):
        type(self).requests = []
        type(self).get_requests = []
        type(self).mode = "success"
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"SEEDANCE_API_URL": self.base + "/vendor", "SEEDANCE_API_KEY": "fixture-credential",
                               "RUNNINGHUB_API_URL": self.base + "/cloud", "RUNNINGHUB_API_KEY": "fixture-credential"}).start()
        patch.dict(os.environ, {"OPENBENCH_PRODUCTION_POLICY": "hybrid_studio"}).start()
        patch.object(worker, "ComfyPlatformClient", side_effect=AssertionError("Comfy must not be touched")).start()
        patch.object(worker, "comfyui", side_effect=AssertionError("Comfy must not be touched")).start()
        patch.object(worker, "probe_local_comfy_status", side_effect=AssertionError("No health dependency")).start()
        self.card = worker.load_studio_card("seedance-20-pro")
        self.card["engine_config"]["poll_interval"] = .01
        self.head = Mock()
        self.head.lease_lost.return_value = False
        self.head.asset.return_value = (self.raw, "video/mp4")
        self.head.upload.side_effect = lambda task, raw, mime: {"asset_url": "/saved", "content_type": mime}
        self.task = {"id": "router-fixture", "production_policy": "hybrid_studio", "input": {"prompt": "Original empty observatory"}}

    def test_graphless_checkpoint_real_http_ffmpeg_dispatch_and_retrieval(self):
        card, graph = worker._resolve_openapi_card_and_workflow("2108000000000000001")
        self.assertIsNone(graph)
        output = worker.execute_story_card(self.task, self.card, {"duration.duration": 1}, self.head)
        self.assertEqual(output["asset_url"], "/saved")
        bounded = self.head.upload.call_args.args[1]
        path = Path(self.folder.name) / "bounded.mp4"
        path.write_bytes(bounded)
        meta = worker._probe_video(path)
        self.assertEqual(meta["frames"], 8)
        self.assertLessEqual(meta["duration"], 1.01)
        self.assertLess(bounded.index(b"moov"), bounded.index(b"mdat"))
        payload = next(p for url, p, _ in self.requests if url == "/vendor/run")
        self.assertEqual(payload["inputs"]["duration"], 1)
        self.assertNotIn("image_url", payload["inputs"])
        self.assertEqual(len([r for r in self.requests if r[0] == "/vendor/run"]), 1)
        with worker._OPENAPI_LOCK:
            old = worker._OPENAPI_CARDS.get("fixture-direct")
            worker._OPENAPI_CARDS["fixture-direct"] = (dict(self.card, card_id="fixture-direct"), None)
        self.addCleanup(lambda: worker._OPENAPI_CARDS.pop("fixture-direct", None) if old is None else worker._OPENAPI_CARDS.__setitem__("fixture-direct", old))
        run = worker.json_fetch(self.base + "/product/run/fixture-direct", payload={"production_policy": "hybrid_studio",
            "nodeInfoList": [{"nodeId": "duration", "fieldName": "duration", "fieldValue": "1"},
                             {"nodeId": "prompt", "fieldName": "prompt", "fieldValue": "Original empty observatory"}]})
        query = worker.json_fetch(self.base + "/product/query", payload={"taskId": run["taskId"]})
        self.assertEqual(query["status"], "SUCCESS")
        self.assertIsNone(query["compiledWorkflow"])
        saved = query["results"][0]["url"].rsplit("/", 1)[1]
        raw, mime = worker.fetch(query["results"][0]["url"])
        self.assertEqual(raw, worker.openapi_get_media(saved)[0])
        self.assertEqual(mime, "video/mp4")
        self.assertTrue(all(token is None for _, token in self.get_requests))
        self.assertLess(raw.index(b"moov"), raw.index(b"mdat"))

    def test_self_hosted_cloud_uses_binary_store_without_graph(self):
        from PIL import Image
        import io
        image = io.BytesIO()
        Image.new("RGB", (2, 2), "blue").save(image, format="PNG")
        source = worker.json_fetch(self.base + "/product/upload", data=self.raw, mime="video/mp4")["data"]["fileName"]
        reference = worker.json_fetch(self.base + "/product/upload", data=image.getvalue(), mime="image/png")["data"]["fileName"]
        run = worker.json_fetch(self.base + "/product/run/rh-cloud-h3-burst", payload={"production_policy": "hybrid_studio", "nodeInfoList": [
            {"nodeId": "27", "fieldName": "video", "fieldValue": source},
            {"nodeId": "51", "fieldName": "image", "fieldValue": reference},
            {"nodeId": "259", "fieldName": "value", "fieldValue": 1}]})
        result = worker.json_fetch(self.base + "/product/query", payload={"taskId": run["taskId"]})
        self.assertEqual(result["status"], "SUCCESS", result)
        self.assertIsNone(result["compiledWorkflow"])
        raw, _ = worker.fetch(result["results"][0]["url"])
        output = Path(self.folder.name) / "selfhost-cloud.mp4"
        output.write_bytes(raw)
        self.assertLessEqual(worker._probe_video(output)["duration"], 1.01)

    def test_default_policy_and_deployment_lock_cannot_be_relaxed(self):
        for task, env in [({"id": "x"}, "hybrid_studio"), (self.task, "open_weights_only")]:
            with patch.dict(os.environ, {"OPENBENCH_PRODUCTION_POLICY": env}):
                for execute in (worker.execute_story_card, worker.execute_vendor_card):
                    with self.assertRaisesRegex(worker.WorkerError, "open_weights_only"):
                        execute(task, self.card, {}, self.head)
        with self.assertRaisesRegex(worker.WorkerError, "open_weights_only"):
            worker.openapi_run_app(self.card["card_id"], {"nodeInfoList": [{"nodeId": "duration", "fieldName": "duration", "fieldValue": 1}]})
        with self.assertRaisesRegex(worker.WorkerError, "open_weights_only"):
            worker.openapi_run_app(self.card["card_id"], {"production_policy": "hybrid_studio", "nodeInfoList": [
                {"nodeId": "duration", "fieldName": "duration", "fieldValue": 1}]})
        self.assertEqual(self.requests, [])
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(worker.effective_production_policy(), "open_weights_only")
        self.assertEqual(worker.effective_production_policy("hybrid_studio"), "hybrid_studio")
        for invalid in ("invalid", False, {}):
            with self.assertRaises(worker.WorkerError):
                worker.effective_production_policy(invalid)

    def test_cloud_binary_upload_submit_query_and_source_bound(self):
        card = worker.load_studio_card("rh-cloud-h3-burst")
        card["engine_config"]["poll_interval"] = .01
        source = Path(self.folder.name) / "source.mp4"
        source.write_bytes(worker.bound_output_video_duration(self.raw, 1))
        self.head.asset.side_effect = lambda task, url: (source.read_bytes(), "video/mp4") if url == "source-ref" else (b"synthetic-image", "image/png")
        output = worker.execute_story_card(self.task, card, {"27.video": "source-ref", "51.image": "image-ref", "259.value": 2}, self.head)
        self.assertEqual(output["reference_role"], "output_video")
        paths = [r[0] for r in self.requests]
        self.assertEqual(paths.count("/cloud/media/upload/binary"), 2)
        submit = next(p for path, p, _ in self.requests if path.startswith("/cloud/run/"))
        self.assertEqual(submit["webappId"], "2109942725885075459")
        self.assertEqual(next(n["fieldValue"] for n in submit["nodeInfoList"] if n["nodeId"] == "27"), "uploaded-ref")
        bounded = Path(self.folder.name) / "cloud.mp4"
        bounded.write_bytes(self.head.upload.call_args.args[1])
        self.assertLessEqual(worker._probe_video(bounded)["duration"], 1.01)
        self.assertTrue(all(token == "Bearer fixture-credential" for _, _, token in self.requests))

    def test_keyframe_context_never_becomes_an_inferred_driving_video(self):
        image_url = "/projects/api/demo/assets/pa_" + "1" * 32
        task = dict(self.task, input={"prompt": "Original observatory",
            "rows": [{"row_id": "s1", "tab_key": "cinema-studio", "table_id": "shots", "cells": [image_url]}],
            "tabs": [{"tab_key": "cinema-studio", "tables": [{"table_id": "shots", "headers": ["Keyframe"]}]}]})
        self.head.asset.return_value = (b"synthetic-image", "image/png")
        worker.execute_story_card(task, self.card, {"duration.duration": 1}, self.head)
        submit = next(p for path, p, _ in self.requests if path == "/vendor/run")
        self.assertEqual(submit["inputs"]["image_url"], "uploaded-ref")
        self.assertNotIn("driving_video_url", submit["inputs"])
        with self.assertRaisesRegex(worker.WorkerError, "incompatible types"):
            worker.execute_story_card(task, self.card, {"motion_ref.driving_video_url": image_url}, self.head)

    def test_media_origin_allowlist_and_canceled_dispatch_state(self):
        type(self).mode = "other-origin"
        with self.assertRaisesRegex(worker.WorkerError, "origin is not authorized"):
            worker.execute_story_card(self.task, self.card, {}, self.head)
        self.card["engine_config"]["media_origins"] = [self.base.replace("127.0.0.1", "localhost")]
        worker.execute_story_card(self.task, self.card, {}, self.head)
        self.assertTrue(all(token is None for _, token in self.get_requests))
        task_id = "fixture-canceled"
        with worker._OPENAPI_LOCK:
            worker._OPENAPI_TASKS[task_id] = {"status": "CANCELED", "production_policy": "hybrid_studio"}
        self.addCleanup(lambda: worker._OPENAPI_TASKS.pop(task_id, None))
        worker._execute_openapi_task(task_id, self.card, None,
            [{"nodeId": "prompt", "fieldName": "prompt", "fieldValue": "Original observatory"}], self.base)
        self.assertEqual(worker._OPENAPI_TASKS[task_id]["status"], "CANCELED")

    def test_invalid_semantic_values_fail_before_provider_submission(self):
        for values in ({"duration.duration": "NaN"}, {"duration.duration": 1.5}, {"duration.duration": 0},
                       {"aspect_ratio.aspect_ratio": "invalid"}, {"prompt.prompt": ""}, {"unknown.key": "x"},
                       {"duration.duration": True}, {"prompt.prompt": {"secret": 1}}):
            with self.subTest(values=values), self.assertRaises(worker.WorkerError):
                worker.execute_story_card(self.task, self.card, values, self.head)
        self.assertEqual(self.requests, [])
        self.head.upload.assert_not_called()

    def test_provider_failures_redacted_no_automatic_resubmission(self):
        for mode in ("failure", "http-failure", "bad-envelope", "private-output", "redirect"):
            type(self).mode = mode
            type(self).requests = []
            with self.subTest(mode=mode), self.assertRaises(worker.WorkerError) as caught:
                worker.execute_story_card(self.task, self.card, {}, self.head)
            self.assertNotIn("fixture-credential", str(caught.exception))
            self.assertNotIn("signed=", str(caught.exception))
            self.assertNotIsInstance(caught.exception, worker.TransientWorkerError)
            self.assertEqual(len([r for r in self.requests if r[0] == "/vendor/run"]), 1)
        self.head.upload.assert_not_called()

    def test_lease_cancellation_before_submit_poll_and_upload(self):
        for stage in ("before", "poll", "download"):
            type(self).requests = []
            self.head.lease_lost.side_effect = lambda: stage == "before" or (stage == "poll" and any(r[0] == "/vendor/run" for r in self.requests))
            if stage == "download":
                original = runtime.fetch
                def lose_after_download(url, **kwargs):
                    result = original(url, **kwargs)
                    if "synthetic.mp4" in url:
                        self.head.lease_lost.side_effect = None
                        self.head.lease_lost.return_value = True
                    return result
                with patch.object(worker, "fetch", side_effect=lose_after_download), self.assertRaisesRegex(worker.WorkerError, "Lease"):
                    worker.execute_story_card(self.task, self.card, {}, self.head)
            else:
                with self.assertRaisesRegex(worker.WorkerError, "Lease"):
                    worker.execute_story_card(self.task, self.card, {}, self.head)
        self.head.upload.assert_not_called()

    def test_output_and_input_limits_and_project_reference_boundary(self):
        with patch.object(worker, "MAX_MEDIA", 100), self.assertRaisesRegex(worker.WorkerError, "size limit"):
            worker.execute_story_card(self.task, self.card, {}, self.head)
        self.head.asset.return_value = (b"too big", "image/png")
        with patch.object(worker, "MAX_MEDIA", 2), self.assertRaisesRegex(worker.WorkerError, "oversized"):
            worker.execute_story_card(self.task, self.card, {"ref_1.image_url": "input"}, self.head)
        self.head.asset.side_effect = runtime.Head("http://127.0.0.1:1", "project-secret").asset
        with self.assertRaisesRegex(worker.WorkerError, "asset in the task project"):
            worker.execute_story_card(dict(self.task, project_slug="demo"), self.card, {"ref_1.image_url": "https://example.com/private.png"}, self.head)
        self.head.upload.assert_not_called()

    def test_late_upload_failure_is_terminal_and_worker_honors_no_retry(self):
        self.head.upload.side_effect = worker.TransientWorkerError("private transport detail")
        with self.assertRaises(worker.NonRetryableWorkerError) as error:
            worker.execute_story_card(self.task, self.card, {}, self.head)
        self.assertTrue(error.exception.no_retry)
        self.assertNotIn("private transport detail", str(error.exception))
        for submitted in (False, True):
            head = Mock()
            head.action.side_effect = [{"task": {"id": "t", "lease_token": "test", "capability": "video_gen"}, "lease_seconds": 30}, {}]
            ambiguous = worker.TransientWorkerError("fixture ambiguous")
            ambiguous.no_retry = not submitted
            def fail_after_submit(task, config, head):
                head.paid_request_submitted = submitted
                raise ambiguous
            with patch.dict(worker.ADAPTERS, {"fixture": fail_after_submit}):
                worker.process_one(head, {"capabilities": {"video_gen": {"adapter": "fixture"}}})
            self.assertFalse(head.action.call_args.args[1]["retryable"])
        self.assertEqual(len([r for r in self.requests if r[0] == "/vendor/run"]), 1)

    def test_configuration_and_health_checks_do_not_imply_inference(self):
        self.assertEqual(worker.provider_configuration_status(self.card), {"configured": True, "requires_comfyui": False})
        with patch.dict(os.environ, {"SEEDANCE_API_URL": ""}):
            self.assertFalse(worker.provider_configuration_status(self.card)["configured"])
        with patch.object(worker, "json_fetch", side_effect=worker.WorkerError("offline")) as request:
            self.assertFalse(model_router.probe_local_comfy_status()["online"])
            self.assertEqual(request.call_args.kwargs["timeout"], .5)
        with patch.object(worker, "json_fetch", return_value={"system": {}}):
            self.assertTrue(model_router.probe_local_comfy_status()["online"])
        self.assertEqual(self.requests, [])

    def test_non_mp4_video_normalizes_and_both_paths_keep_faststart(self):
        webm = Path(self.folder.name) / "synthetic.webm"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(self.video),
                        "-c:v", "libvpx-vp9", str(webm)], check=True, capture_output=True, timeout=20)
        original = runtime.fetch
        def download_webm(url, **kwargs):
            return (webm.read_bytes(), "video/webm") if "synthetic.mp4" in url else original(url, **kwargs)
        with patch.object(worker, "fetch", side_effect=download_webm):
            worker.execute_story_card(self.task, self.card, {"duration.duration": 1}, self.head)
        self.assertEqual(self.head.upload.call_args.args[2], "video/mp4")
        raw = self.head.upload.call_args.args[1]
        self.assertLess(raw.index(b"moov"), raw.index(b"mdat"))
        worker.execute_story_card(self.task, self.card, {"duration.duration": 5}, self.head)
        raw = self.head.upload.call_args.args[1]
        self.assertLess(raw.index(b"moov"), raw.index(b"mdat"))

    def test_missing_configuration_timeout_and_unconfigured_contract(self):
        with patch.dict(os.environ, {"SEEDANCE_API_URL": ""}), self.assertRaisesRegex(worker.WorkerError, "not configured"):
            worker.execute_story_card(self.task, self.card, {}, self.head)
        bad = copy.deepcopy(self.card)
        bad["engine_config"].pop("adapter_contract")
        with self.assertRaisesRegex(worker.WorkerError, "adapter contract"):
            worker.execute_story_card(self.task, bad, {}, self.head)
        type(self).mode = "pending"
        self.card["engine_config"].update(timeout=.05, poll_interval=.01)
        with self.assertRaisesRegex(worker.WorkerError, "timed out"):
            worker.execute_story_card(self.task, self.card, {}, self.head)
        self.assertEqual(len([r for r in self.requests if r[0] == "/vendor/run"]), 1)

    def test_catalog_ten_driver_profiles_and_named_vendor_inputs(self):
        cards = [worker.load_studio_card(p) for p in worker.CARDS_DIR.glob("*.json")]
        self.assertEqual(len(cards), 10)
        for card in cards:
            config = card["engine_config"]
            self.assertIn(config["driver"], ("comfy_local", "vendor_api", "runninghub_cloud"))
            if config["driver"] == "comfy_local":
                self.assertTrue(config["requires_comfyui"])
                self.assertEqual(config["tier"], "open_weights")
                self.assertIsInstance(worker._resolve_openapi_card_and_workflow(card["card_id"])[1], dict)
            else:
                self.assertFalse(config["requires_comfyui"])
                self.assertIsNone(worker._resolve_openapi_card_and_workflow(card["card_id"])[1])
        for changed in ({"tier": "open_weights"}, {"requires_comfyui": True}, {"driver": "unsupported"}):
            invalid = copy.deepcopy(self.card)
            invalid["engine_config"].update(changed)
            with self.assertRaises(worker.WorkerError):
                worker.validate_studio_card(invalid)
        invalid = copy.deepcopy(self.card)
        invalid["nodes"][0]["nodeId"] = "12"
        with self.assertRaisesRegex(worker.WorkerError, "named semantic"):
            worker.validate_studio_card(invalid)
        for bounds in ({"min": "NaN"}, {"step": 0}, {"min": 20, "max": 1}, {"max": "bad"}, {"defaultValue": "1.5"}):
            invalid = copy.deepcopy(self.card)
            next(n for n in invalid["nodes"] if n.get("slot") == "duration").update(bounds)
            with self.assertRaises(worker.WorkerError):
                worker.validate_studio_card(invalid)

    def test_partner_explicit_hybrid_and_frozen_graph_legacy_seam(self):
        card = worker.load_studio_card("local-smoke")
        card["engine_config"].update(driver="comfy_partner", tier="closed_hybrid", requires_comfyui=True)
        graph = {"1": {"class_type": "Test", "inputs": {}}}
        with patch.object(worker, "comfyui", return_value={"asset_url": "/partner"}) as execute:
            with self.assertRaisesRegex(worker.WorkerError, "open_weights_only"):
                worker.execute_story_card({"workflow": graph}, card, {}, self.head)
            self.assertEqual(worker.execute_story_card(dict(self.task, workflow=graph), card, {}, self.head)["asset_url"], "/partner")
            self.assertEqual(execute.call_args.args[1]["production_policy"], "hybrid_studio")
        with self.assertRaisesRegex(worker.WorkerError, "open_weights_only"):
            card_engine.comfyui({"workflow": graph}, {"card": card}, self.head)
        self.assertEqual(graph, {"1": {"class_type": "Test", "inputs": {}}})


if __name__ == "__main__":
    unittest.main()
