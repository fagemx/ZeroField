"""Real Head HTTP, PostgreSQL, adapter HTTP fixtures and actual FFmpeg movie."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image
from project_assistant import flow_runner, limb_worker, limbs
from project_docs import repository as repo, service, templates
from project_docs.markdown_import import markdown_to_doc
from project_docs.doc_schema import validate_doc
import test_product_http as http_fixture


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI") and shutil.which("ffmpeg") and shutil.which("ffprobe"), "Requires PostgreSQL and FFmpeg")
class ProductionPipelineTests(unittest.TestCase):
    setUp = http_fixture.ProductHTTPTests.setUp
    tearDown = http_fixture.ProductHTTPTests.tearDown
    request = http_fixture.ProductHTTPTests.request

    def test_script_to_dynamic_shots_to_one_playable_movie_via_real_worker_protocol(self):
        specs = templates.tab_specs("ai_drama", "Pipeline verification", "Two shots")
        specs.append(("deliverables", "Deliverables", "doc", "# Final movie"))
        keys = {s[0] for s in specs}
        for key, title, surface, markdown in specs:
            raw, values = markdown_to_doc(markdown, tab_keys=keys, image_src=lambda _: None)
            doc, _ = validate_doc(raw, slug=self.slug)
            if key == "storyboard":
                next(n for n in doc["content"] if n["type"] == "table")["content"] = next(n for n in doc["content"] if n["type"] == "table")["content"][:1]
            templates.configure_doc(key, doc)
            repo.create_tab(self.conn, self.slug, key=key, title=title, parent_key=None, doc=doc, actor_id=self.actor, surface_type=surface)
        definition = templates.flow_specs("ai_drama")["pipeline"]
        for node in definition["nodes"]:
            node["write_mode"] = "direct"
        flow_runner.save_definition(self.conn, self.me, self.slug, "pipeline", {"definition": definition, "revision": 0})
        issued = limbs.register(self.conn, self.me, {"name": "Integration adapters", "capabilities": list(limbs.CAPABILITIES), "project_slug": self.slug})
        self.conn.commit()
        head = limb_worker.Head(f"http://127.0.0.1:{self.server.server_port}", issued["token"])
        self.assertFalse(limb_worker.process_one(head, {"capabilities": {}}))
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "input.png"
            Image.new("RGB", (64, 48), "blue").save(image)
            movie = Path(folder) / "clip.mp4"
            limb_worker.assemble_files([(image, "image/png", None)], movie, {"width": 160, "height": 90, "fps": 12, "still_seconds": .5})
            image_bytes, movie_bytes = image.read_bytes(), movie.read_bytes()
            class Provider(BaseHTTPRequestHandler):
                def log_message(self, *_): pass
                def send(self, value, mime="application/json"):
                    raw = json.dumps(value).encode() if mime == "application/json" else value
                    self.send_response(200); self.send_header("Content-Type", mime); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
                def do_POST(self):
                    body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    if self.path == "/chat/completions":
                        source = json.loads(body["messages"][-1]["content"])
                        output = {"table_id": source["target_tables"][0]["table_id"], "new_rows": [[f"S0{i}", "Wide", "A scene", "blue square", "", "", "未開始", ""] for i in (1, 2)]}
                        self.send({"choices": [{"message": {"content": json.dumps(output)}}]})
                    elif self.path == "/prompt": self.send({"prompt_id": "fixture"})
                    elif self.path == "/jobs": self.send({"status": "succeeded", "output": {"media_url": "/clip.mp4"}})
                def do_GET(self):
                    if self.path == "/history/fixture": self.send({"fixture": {"outputs": {"9": {"images": [{"filename": "out.png", "type": "output"}]}}, "status": {"completed": True}}})
                    elif self.path.startswith("/view?"): self.send(image_bytes, "image/png")
                    elif self.path == "/clip.mp4": self.send(movie_bytes, "video/mp4")
            provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
            thread = threading.Thread(target=provider.serve_forever, daemon=True); thread.start()
            try:
                url = f"http://127.0.0.1:{provider.server_port}"
                workflow = Path(folder) / "workflow.json"
                workflow.write_text(json.dumps({"6": {"inputs": {"text": ""}}}))
                config = {"capabilities": {"llm": {"adapter": "openai_compat", "base_url": url, "model": "fixture"},
                    "image_gen": {"adapter": "comfyui", "base_url": url, "workflow": str(workflow), "prompt_node": "6", "prompt_column": 3},
                    "video_gen": {"adapter": "http_bridge", "base_url": url},
                    "media_assemble": {"adapter": "ffmpeg", "width": 160, "height": 90, "fps": 12}}}
                base = f"/projects/api/{self.slug}/tabs/pipeline/flow/runs"
                code, run, _ = self.request(base, method="POST", data={})
                self.assertEqual(code, 200, run)
                for _ in range(6):
                    self.assertTrue(limb_worker.process_one(head, config))
                code, detail, _ = self.request(base + "/" + run["run"]["id"])
                self.assertEqual(detail["run"]["status"], "succeeded", detail)
                self.assertEqual(len(detail["tasks"]), 6)
                assembled = next(t for t in detail["tasks"] if t["node_id"] == "assemble")
                code, raw, _ = self.request(assembled["output"]["asset_url"])
                self.assertEqual(code, 200)
                result = Path(folder) / "result.mp4"; result.write_bytes(raw)
                info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_format", "-of", "json", str(result)], check=True, capture_output=True).stdout)
                self.assertAlmostEqual(float(info["format"]["duration"]), 1, delta=.2)
                tab = self.request(f"/projects/api/{self.slug}/tabs/deliverables")[1]
                self.assertIn(assembled["output"]["asset_url"], json.dumps(tab))
            finally:
                provider.shutdown(); provider.server_close(); thread.join()


if __name__ == "__main__":
    unittest.main()
