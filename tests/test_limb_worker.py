import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest import mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image
from project_assistant import limb_worker as worker


class Fixture(BaseHTTPRequestHandler):
    events = []
    image = b""
    def log_message(self, *_):
        pass
    def send(self, value, mime="application/json", status=200):
        raw = json.dumps(value).encode() if mime == "application/json" else value
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        body = json.loads(raw)
        type(self).events.append((self.path, body, self.headers.get("Authorization")))
        if self.path == "/chat/completions":
            self.send({"choices": [{"message": {"content": '{"text":"actual fixture response"}'}}]})
        elif self.path == "/prompt":
            self.send({"prompt_id": "job-1"})
        elif self.path == "/jobs":
            self.send({"id": "job-1", "status": "running"})
        elif self.path == "/audio/speech":
            self.send(b"ID3fixture", "audio/mpeg")
        else:
            self.send({}, status=404)
    def do_GET(self):
        if self.path == "/history/job-1":
            self.send({"job-1": {"outputs": {"9": {"images": [{"filename": "result.png", "type": "output"}]}}, "status": {"completed": True}}})
        elif self.path.startswith("/view?") or self.path == "/media/result.png":
            self.send(self.image, "image/png")
        elif self.path == "/jobs/job-1":
            self.send({"status": "succeeded", "output": {"media_url": "/media/result.png"}})
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/media/result.png")
            self.end_headers()
        else:
            self.send({}, status=404)


class FakeHead:
    def __init__(self, data):
        self.data, self.outputs = data, []
    def asset(self, task, url):
        return self.data, "image/png"
    def upload(self, task, data, mime):
        self.outputs.append((data, mime))
        return {"asset_url": "/projects/api/test/assets/pa_" + "a" * 32, "content_type": mime}


class WorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = io.BytesIO()
        Image.new("RGB", (64, 48), "blue").save(data, "PNG")
        Fixture.image = data.getvalue()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
    def setUp(self):
        Fixture.events = []
        self.head = FakeHead(Fixture.image)
        self.task = {"id": "task", "project_slug": "test", "capability": "image_gen", "lease_token": "private-lease", "input": {"prompt": "blue square", "rows": [{"cells": ["Shot 1", "blue square"]}]}}
    def test_llm_structured_contract_and_no_lease_transmitted(self):
        result = worker.llm(self.task, {"model": "fixture", "base_url": self.url}, self.head)
        self.assertEqual(result, {"text": "actual fixture response"})
        self.assertNotIn("private-lease", json.dumps(Fixture.events))
        self.assertEqual(Fixture.events[0][1]["response_format"], {"type": "json_object"})
    def test_comfy_executes_exported_graph_and_downloads_image(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "workflow.json"
            path.write_text(json.dumps({"6": {"inputs": {"text": "old"}}}))
            result = worker.comfyui(self.task, {"base_url": self.url, "workflow": str(path), "prompt_node": "6", "prompt_column": 1}, self.head)
        self.assertEqual(result["content_type"], "image/png")
        self.assertEqual(Fixture.events[0][1]["prompt"]["6"]["inputs"]["text"], "blue square")
        self.assertEqual(self.head.outputs[0][0], Fixture.image)
    def test_bridge_polls_and_uploads_without_credentials(self):
        result = worker.bridge(self.task, {"base_url": self.url, "poll_seconds": 0}, self.head)
        self.assertEqual(result["content_type"], "image/png")
        self.assertNotIn("private-lease", json.dumps(Fixture.events))
    def test_head_refuses_cross_project_and_external_asset_requests(self):
        head = worker.Head(self.url, "private-head-token")
        for url in ["https://example.com/media.png", "/projects/api/other/assets/pa_" + "a" * 32, "/projects/api/test/assets/pa_" + "a" * 32 + "?x=1"]:
            with self.subTest(url=url), self.assertRaises(worker.WorkerError):
                head.asset(self.task, url)
    def test_redirects_never_forward_authorization(self):
        with self.assertRaises(worker.WorkerError):
            worker.fetch(self.url + "/redirect", token="private")
    def test_oversize_download_rejected(self):
        with self.assertRaises(worker.WorkerError):
            worker.fetch(self.url + "/media/result.png", limit=5)
    def test_text_predecessor_does_not_hide_sheet_media_or_narration(self):
        video = "/projects/api/test/assets/pa_" + "b" * 32
        audio = "/projects/api/test/assets/pa_" + "c" * 32
        self.task["input"] = {"rows": [{"row_id": "r1", "cells": [video, audio]}],
                              "predecessor_tasks": [{"row_id": "r1", "node_id": "review", "output": {"text": "approved"}}]}
        self.head.asset = lambda task, url: (b"fixture", "video/mp4" if url == video else "audio/mpeg")
        captured = []
        def render(clips, destination, config):
            captured.extend(clips)
            destination.write_bytes(b"fixture")
        with mock.patch.object(worker, "assemble_files", side_effect=render):
            worker.ffmpeg(self.task, {}, self.head)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0][1], "video/mp4")
        self.assertIsNotNone(captured[0][2])
    def test_lost_lease_prevents_upload_and_comfy_poll(self):
        head = worker.Head(self.url, "token")
        head.lease_lost = lambda: True
        with self.assertRaisesRegex(worker.WorkerError, "Lease was lost"):
            head.upload(self.task, b"output", "image/png")
    def test_transient_provider_failure_is_retryable(self):
        calls = []
        def action(name, payload=None):
            calls.append((name, payload))
            return {"task": self.task, "lease_seconds": 120} if name == "claim" else {}
        self.head.action = action
        with mock.patch.dict(worker.ADAPTERS, {"temporary": mock.Mock(side_effect=worker.TransientWorkerError("503"))}):
            worker.process_one(self.head, {"capabilities": {"image_gen": {"adapter": "temporary"}}})
        self.assertTrue(next(body for name, body in calls if name == "fail")["retryable"])
    def test_transient_renewal_failure_preserves_retryability(self):
        calls = []
        def action(name, payload=None):
            calls.append((name, payload))
            if name == "claim": return {"task": self.task, "lease_seconds": 3}
            if name == "renew": raise worker.TransientWorkerError("HTTP 503")
            return {}
        def waiting(task, config, head):
            deadline = worker.time.monotonic() + 3
            while worker.time.monotonic() < deadline:
                if head.lease_lost(): raise worker.WorkerError("Lease was lost")
                worker.time.sleep(.02)
            self.fail("heartbeat did not run")
        self.head.action = action
        with mock.patch.dict(worker.ADAPTERS, {"waiting": waiting}):
            worker.process_one(self.head, {"capabilities": {"image_gen": {"adapter": "waiting"}}})
        self.assertTrue(next(body for name, body in calls if name == "fail")["retryable"])
    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg and FFprobe needed for real media integration")
    def test_real_ffmpeg_two_shot_movie_has_correct_duration_resolution_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            first, second = Path(folder) / "one.png", Path(folder) / "two.png"
            first.write_bytes(Fixture.image)
            Image.new("RGB", (80, 64), "red").save(second)
            result = Path(folder) / "movie.mp4"
            worker.assemble_files([(first, "image/png", None), (second, "image/png", None)], result,
                                  {"width": 160, "height": 90, "fps": 12, "still_seconds": .5})
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(result)], check=True, capture_output=True)
            metadata = json.loads(probe.stdout)
            video = next(s for s in metadata["streams"] if s["codec_type"] == "video")
            self.assertEqual((video["width"], video["height"]), (160, 90))
            self.assertTrue(any(s["codec_type"] == "audio" for s in metadata["streams"]))
            self.assertAlmostEqual(float(metadata["format"]["duration"]), 1, delta=.15)


if __name__ == "__main__":
    unittest.main()
