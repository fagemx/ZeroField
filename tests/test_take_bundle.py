"""Take evidence bundles: submit-time provenance through the real worker protocol, ZIP contents and secrets."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from PIL import Image, PngImagePlugin
from project_assistant import flow_runner, limb_worker, limbs
from project_docs import repository as repo, take_bundle
from project_docs.markdown_import import markdown_to_doc
from project_docs.doc_schema import validate_doc
import test_product_http as http_fixture

SECRET = "comfyui-" + "s3cr3tK3y" * 4
GRAPH = {
    "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors"}},
    "2": {"class_type": "LoadImage", "inputs": {"image": "placeholder.png"}},
    "3": {"class_type": "KSampler", "inputs": {"seed": 1, "model": ["1", 0]}},
    "4": {"class_type": "PartnerNode", "inputs": {"api_key_comfy_org": "", "prompt": ""}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
    "9": {"class_type": "SaveImage", "inputs": {"images": ["3", 0]}},
}


def png(color, prompt=None):
    data = io.BytesIO()
    info = PngImagePlugin.PngInfo()
    if prompt is not None:
        info.add_text("prompt", json.dumps(prompt))
    Image.new("RGB", (32, 24), color).save(data, "PNG", pnginfo=info)
    return data.getvalue()


def entries(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


class EmbeddedGraphTests(unittest.TestCase):
    def test_png_text_chunk_and_scrub(self):
        graph = {"6": {"class_type": "CLIPTextEncode", "inputs": {"text": "rain"}}}
        self.assertEqual(take_bundle.embedded_graph(png("red", graph), "image/png"), graph)
        self.assertIsNone(take_bundle.embedded_graph(png("red"), "image/png"))
        self.assertIsNone(take_bundle.embedded_graph(png("red", {"nodes": [], "links": []}), "image/png"))
        scrubbed = take_bundle.scrub({"token": "x", "a": ["Bearer abcdefghijkl", "keep " + SECRET, "sha 0123456789abcdef" * 4]}, [SECRET])
        self.assertEqual(scrubbed["token"], take_bundle.REDACTED)
        self.assertNotIn("abcdefghijkl", json.dumps(scrubbed))
        self.assertNotIn(SECRET, json.dumps(scrubbed))
        self.assertIn("0123456789abcdef", json.dumps(scrubbed))  # hashes survive

    @unittest.skipUnless(shutil.which("ffmpeg"), "Requires FFmpeg")
    def test_mp4_metadata_written_like_comfyui_save_video(self):
        graph = {"12": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "S03 — rain"}}}
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "take.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x48:d=0.2", "-metadata",
                            "prompt=" + json.dumps(graph, ensure_ascii=False), "-movflags", "use_metadata_tags", str(target)],
                           check=True, capture_output=True, timeout=60)
            self.assertEqual(take_bundle.embedded_graph(target.read_bytes(), "video/mp4"), graph)

    def test_model_sources_come_from_the_workflows_readme(self):
        folder, source = take_bundle.model_sources()["ltx-2.5-22b-ic-lora-layout-to-render-1.0.safetensors"]
        self.assertEqual(folder, "loras/ltx")
        self.assertEqual(source, "https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render")

    def test_any_file_holding_a_configured_credential_withholds_the_bundle(self):
        with self.assertRaises(take_bundle.BundleError) as caught:
            take_bundle._zip([("output.mp4", b"\x00moov" + SECRET.encode())], [SECRET])
        self.assertEqual(caught.exception.status, 409)


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "Requires PostgreSQL")
class TakeBundleHTTPTests(unittest.TestCase):
    setUp = http_fixture.ProductHTTPTests.setUp
    tearDown = http_fixture.ProductHTTPTests.tearDown
    request = http_fixture.ProductHTTPTests.request

    def test_generated_take_bundle_reproduces_the_submitted_graph_without_secrets(self):
        keyframe = png("blue")
        keyframe_id = repo.put_asset(self.conn, self.slug, data=keyframe, content_type="image/png", actor_id=self.actor)
        keyframe_url = f"/projects/api/{self.slug}/assets/{keyframe_id}"
        markdown = ("| Shot | Prompt | Keyframe | Cinema Shot | Status |\n| --- | --- | --- | --- | --- |\n"
                    f"| S01 | Kael reaches for the dial | {keyframe_url} | | {{{{s:Approved}}}} |\n")
        raw, _ = markdown_to_doc(markdown, tab_keys=set(), image_src=lambda _: None)
        doc, _ = validate_doc(raw, slug=self.slug)
        repo.create_tab(self.conn, self.slug, key="cinema", title="Cinema", parent_key=None, doc=doc, actor_id=self.actor, surface_type="sheet")
        definition = {"nodes": [{"id": "cinema", "title": "Shots", "capability": "image_gen", "scope": "rows", "prompt": "Render.",
                                 "input_tabs": ["cinema"], "target": {"tab_key": "cinema", "col_index": 3}, "write_mode": "direct",
                                 "x": 0, "y": 0, "row_source": {"tab_key": "cinema"}}], "edges": []}
        flow_runner.save_definition(self.conn, self.me, self.slug, "flow", {"definition": definition, "revision": 0})
        issued = limbs.register(self.conn, self.me, {"name": "Studio 4090", "capabilities": ["image_gen"], "project_slug": self.slug})
        self.conn.commit()
        output = png("green")
        submitted = []

        class Comfy(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def send(self, value, mime="application/json"):
                body = json.dumps(value).encode() if mime == "application/json" else value
                self.send_response(200); self.send_header("Content-Type", mime); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                if self.path == "/upload/image":
                    self.send({"name": "input-keyframe.png", "subfolder": ""})
                elif self.path == "/prompt":
                    submitted.append(json.loads(body)["prompt"])
                    self.send({"prompt_id": "job-7"})
            def do_GET(self):
                if self.path == "/system_stats":
                    self.send({"system": {"comfyui_version": "0.42.1"}})
                elif self.path == "/history/job-7":
                    self.send({"job-7": {"outputs": {"9": {"images": [{"filename": "out.png", "type": "output"}]}}, "status": {"completed": True}}})
                elif self.path.startswith("/view?"):
                    self.send(output, "image/png")

        comfy = ThreadingHTTPServer(("127.0.0.1", 0), Comfy)
        thread = threading.Thread(target=comfy.serve_forever, daemon=True); thread.start()
        try:
            with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"COMFY_API_KEY": SECRET}):
                graph = json.loads(json.dumps(GRAPH))
                graph["4"]["inputs"].update(api_key_comfy_org=SECRET, prompt=f"inline {SECRET} key")
                workflow = Path(folder) / "ltx25_cinema_shot.json"
                workflow.write_text(json.dumps(graph))
                config = {"capabilities": {"image_gen": {"adapter": "comfyui", "platform": "local", "poll_seconds": 0,
                    "base_url": f"http://127.0.0.1:{comfy.server_port}", "workflow": str(workflow), "output_node": "9",
                    "prompt_node": "6", "prompt_column": 1, "seed_node": "3", "seed": 42, "image_node": "2"}}}
                head = limb_worker.Head(f"http://127.0.0.1:{self.server.server_port}", issued["token"])
                self.assertFalse(limb_worker.process_one(head, {"capabilities": {}}))  # the worker connects
                code, run, _ =self.request(f"/projects/api/{self.slug}/tabs/flow/flow/runs", method="POST", data={})
                self.assertEqual(code, 200, run)
                self.assertTrue(limb_worker.process_one(head, config))
                code, detail, _ = self.request(f"/projects/api/{self.slug}/tabs/flow/flow/runs/" + run["run"]["id"])
                task = detail["tasks"][0]
                self.assertEqual(task["status"], "succeeded", task)
                self.assertNotIn("provenance", task["output"])  # polled run payloads stay small
                take_url = task["output"]["asset_url"]

                code, bundle, headers = self.request(take_url + "/bundle")
                self.assertEqual(code, 200, bundle)
                self.assertEqual(headers["Content-Type"], "application/zip")
                self.assertIn("attachment;", headers["Content-Disposition"])
                self.assertEqual(self.request(take_url + "/bundle", authenticated=False)[0], 401)
                files = entries(bundle)
                code, export, _ = self.request(f"/projects/api/{self.slug}/takes/export")
                self.assertEqual(code, 200, export)
                exported = entries(export)
        finally:
            comfy.shutdown(); comfy.server_close(); thread.join()

        self.assertEqual(set(files), {"output.png", "workflow.json", "take.json", "README.md", "checksums.sha256", "inputs/input-keyframe.png"})
        self.assertEqual(files["output.png"], output)
        self.assertEqual(files["inputs/input-keyframe.png"], keyframe)
        executed = json.loads(files["workflow.json"])
        self.assertEqual(executed["2"]["inputs"]["image"], "input-keyframe.png")
        self.assertEqual(executed["3"]["inputs"]["seed"], 42)
        self.assertEqual(executed["6"]["inputs"]["text"], "Kael reaches for the dial")
        self.assertEqual({k: v for k, v in executed.items() if k != "4"}, {k: v for k, v in submitted[0].items() if k != "4"})
        take = json.loads(files["take.json"])
        self.assertEqual(take["provenance"], "recorded_at_submit")
        self.assertEqual(take["seed"], 42)
        self.assertEqual(take["shot"]["label"], "S01")
        self.assertEqual(take["shot"]["column"], "Cinema Shot")
        self.assertEqual(take["inputs"][0]["sha256"], hashlib.sha256(keyframe).hexdigest())
        self.assertEqual(take["inputs"][0]["asset_id"], keyframe_id)
        self.assertEqual(take["output"]["sha256"], hashlib.sha256(output).hexdigest())
        self.assertEqual(take["models"][0]["source"], "https://huggingface.co/Lightricks/LTX-2.5")
        self.assertEqual(take["platform"]["platform"], "local")
        self.assertEqual(take["platform"]["comfyui_version"], "0.42.1")
        self.assertEqual(take["platform"]["worker"], "Studio 4090")
        self.assertEqual(take["workflow_file"], "ltx25_cinema_shot.json")
        self.assertIsNotNone(take["timing"]["render_seconds"])
        self.assertIn("comfy_sdk import Comfy", files["README.md"].decode())
        for line in files["checksums.sha256"].decode().splitlines():
            digest, name = line.split("  ", 1)
            self.assertEqual(hashlib.sha256(files[name]).hexdigest(), digest)

        manifest = json.loads(exported["manifest.json"])
        self.assertEqual(len(manifest["takes"]), 1)  # the uploaded keyframe is a source, not a generated take
        folder = manifest["takes"][0]["folder"]
        self.assertEqual(manifest["takes"][0]["seed"], 42)
        self.assertEqual(exported[folder + "output.png"], output)
        self.assertIn(folder + "workflow.json", exported)

        for name, data in {**files, **exported, "bundle.zip": bundle, "export.zip": export}.items():
            for secret in (SECRET, self.member_token, issued["token"]):
                self.assertNotIn(secret.encode(), data, name)
        self.assertEqual(executed["4"]["inputs"]["api_key_comfy_org"], take_bundle.REDACTED)


if __name__ == "__main__":
    unittest.main()
