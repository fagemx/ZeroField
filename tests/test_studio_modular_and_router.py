"""Mechanical Studio extraction compatibility; routing is covered by its component owner."""
import ast
import copy
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from project_assistant import limb_worker as worker, studio
from project_assistant.studio import (
    _compat, card_engine, context_compiler, ffmpeg_runtime, media_prep,
    openapi_v2_hub, runtime,
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


if __name__ == "__main__":
    unittest.main()
