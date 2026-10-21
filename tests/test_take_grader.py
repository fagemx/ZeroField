"""Continuity grading of sheet-row takes: rubric, GPU hand-off and the one-click retake prompt.

The vision model, Ollama and ComfyUI are one local fake HTTP server; FFmpeg and PostgreSQL are real.
"""
import functools
import json
import os
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import unittest.mock
from unittest.mock import patch

from project_assistant import providers, take_grader as grader

ANSWER = json.dumps({"score": 58, "passed": False, "issues": ["Hand leaves the dial late (2.8s)."],
                     "feedback": "Push-in lands; the hand withdraws early.", "retake_prompt": "Kael keeps his hand on the dial to the final frame."})


def fake_gpu(answer=ANSWER, busy_polls=0):
    """ComfyUI (/queue, /free, /system_stats), the OpenAI-compatible vision endpoint and Ollama's /api/generate."""
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def send(self, value):
            raw = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        def do_GET(self):
            calls.append(("GET", self.path, None))
            if self.path == "/queue":
                busy = sum(c[1] == "/queue" for c in calls) <= busy_polls
                self.send({"queue_running": [["render"]] if busy else [], "queue_pending": []})
            else:
                self.send({"devices": [{"vram_free": 22e9, "vram_total": 24e9}]})
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
            calls.append(("POST", self.path, body))
            self.send({"choices": [{"message": {"content": answer}}]} if self.path == "/v1/chat/completions" else {})
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}", calls


class GraderUnitTests(unittest.TestCase):
    def test_scorecard_reads_thinking_models_and_keeps_asset_tags(self):
        card = grader.scorecard('<think>{"draft": 1}</think>\n```json\n' + ANSWER + '\n```', "Kael reaches. @CAST-01 @SET-01")
        self.assertEqual((card["score"], card["passed"]), (58, False))
        self.assertEqual(card["retakePrompt"], "Kael keeps his hand on the dial to the final frame. @CAST-01 @SET-01")
        self.assertEqual(grader.scorecard(json.dumps({"score": 84, "passed": True}), "")["issues"], [])
        for bad in ("no json", '{"score": "84", "passed": true}', '{"score": 140, "passed": true}', '{"score": 70}'):
            with self.assertRaises(grader.GradeError):
                grader.scorecard(bad, "")

    def test_hand_off_waits_for_renders_then_frees_comfy(self):
        calls, waits = [], []
        def opener(url, body=None, timeout=10):
            calls.append((url, body))
            if url.endswith("/queue"):
                return {"queue_running": [["r"]] if sum(u.endswith("/queue") for u, _ in calls) <= 2 else [], "queue_pending": []}
            return {"devices": [{"vram_free": 20, "vram_total": 24}]} if url.endswith("/system_stats") else {}
        gpu = grader.hand_off("http://c", on_wait=lambda: waits.append(1), opener=opener, sleep=lambda s: None)
        urls = [u for u, _ in calls]
        self.assertEqual(urls, ["http://c/queue"] * 3 + ["http://c/free", "http://c/system_stats"])
        self.assertEqual(calls[3][1], {"unload_models": True, "free_memory": True})
        self.assertEqual(waits, [1])  # marked waiting once, never interrupted
        self.assertEqual(gpu, {"comfyFreed": True, "comfyOnline": True, "waitedForRenders": True, "vramFree": 0.83})
        def offline(url, body=None, timeout=10):
            raise OSError("refused")
        self.assertEqual(grader.hand_off("http://c", opener=offline), {"comfyFreed": False, "comfyOnline": False})
        def busy(url, body=None, timeout=10):
            return {"queue_running": [["r"]], "queue_pending": []}
        with self.assertRaises(grader.GradeError):
            grader.hand_off("http://c", opener=busy, timeout=0, sleep=lambda s: None)

    def test_unload_only_targets_local_ollama_style_endpoints(self):
        sent = []
        opener = lambda url, body=None, timeout=10: sent.append((url, body))
        local = providers.ProviderConfig("openai_compat", "http://127.0.0.1:11434/v1", "", "qwen3.8:27b-16k")
        self.assertTrue(grader.unload(local, opener))
        self.assertEqual(sent, [("http://127.0.0.1:11434/api/generate", {"model": "qwen3.8:27b-16k", "keep_alive": 0})])
        self.assertFalse(grader.unload(providers.ProviderConfig("openai_compat", "https://api.example.com/v1", "k", "m"), opener))
        self.assertEqual(len(sent), 1)

    def test_local_renders_hold_the_gpu_lock_so_grades_queue_behind_them(self):
        from test_studio_worker import studio_task
        from project_assistant import limb_worker as worker
        held = []
        with tempfile.TemporaryDirectory() as folder:
            workflow = Path(folder) / "workflow.json"
            workflow.write_text(json.dumps({str(i): {"class_type": "Test", "inputs": {}} for i in range(1, 13)}))
            for base, locked in (("http://127.0.0.1:8188", True), ("https://cloud.comfy.org", False)):
                with patch.object(worker, "ComfyPlatformClient") as factory:
                    client = factory.return_value
                    client.submit_workflow.side_effect = lambda *a: held.append(grader.GPU_LOCK.locked()) or "job"
                    client.fetch_history.return_value = {"job": {"outputs": {"12": {"videos": [{"filename": "take.mp4"}]}}}}
                    client.download_output.return_value = (b"movie", "video/mp4")
                    head = unittest.mock.Mock(**{"lease_lost.return_value": False, "upload.return_value": {"asset_url": "saved"}})
                    worker.comfyui(studio_task(), {"workflow": str(workflow), "platform": "local", "base_url": base, "output_node": "12",
                                                   "prompt_node": "6", "seed_node": "3", "poll_seconds": 0}, head)
                self.assertEqual(held.pop(), locked)
                self.assertFalse(grader.GPU_LOCK.locked())

    def test_vision_sends_the_rubric_and_the_sheet_without_tools(self):
        server, base, calls = fake_gpu()
        try:
            config = providers.ProviderConfig("openai_compat", base + "/v1", "", "qwen-test", "high")
            self.assertEqual(grader.vision(config, "S03, Slow Dolly Push-In", "Kael reaches @CAST-01", b"png"), ANSWER)
        finally:
            server.shutdown(); server.server_close()
        body = calls[0][2]
        self.assertEqual(body["messages"][0]["content"], grader.RUBRIC)
        self.assertIn("Brief: S03, Slow Dolly Push-In", body["messages"][1]["content"][0]["text"])
        self.assertTrue(body["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertNotIn("tools", body)
        self.assertEqual((body["model"], body["reasoning_effort"]), ("qwen-test", "low"))


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "set OPENBENCH_TEST_DB_URI for grading HTTP tests")
class GradeHTTPTests(unittest.TestCase):
    from test_story_openapi import StoryHTTPTests as fixture
    request, call, ok = fixture.request, fixture.call, fixture.ok

    def setUp(self):
        self.fixture.setUp(self)
        from project_docs import repository as repo, story_openapi as story
        self.repo, self.story = repo, story
        self.row = next(r for r in story.table_rows(self.conn, self.slug, "cinema-studio") if r["cells"][0] == "S03")
        self.shot = f"sh_{self.slug}_{self.row['rid']}"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "take.mp4"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=64x48:rate=12:duration=1",
                            "-pix_fmt", "yuv420p", str(path)], check=True)
            self.take = f"/projects/api/{self.slug}/assets/" + repo.put_asset(self.conn, self.slug, data=path.read_bytes(), content_type="video/mp4", actor_id=self.actor)
        story.mutate_row(self.conn, self.me, self.slug, "cinema-studio", self.row["rid"], {5: f"[Video]({self.take})"})
        self.conn.commit()
        self.patches = [patch.object(grader, "kick", lambda: None)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.fixture.tearDown(self)

    def run_grader(self, **fake):
        import psycopg
        server, base, calls = fake_gpu(**fake)
        env = {"OPENBENCH_PROVIDER": "openai_compat", "OPENBENCH_API_BASE": base + "/v1", "OPENBENCH_MODEL": "qwen-test"}
        try:
            with patch.dict(os.environ, env), patch.object(grader, "comfy_url", lambda conn, slug: base), \
                    patch.object(grader, "hand_off", functools.partial(grader.hand_off, poll=0)):
                ran = grader.drain(lambda: psycopg.connect(os.environ["OPENBENCH_TEST_DB_URI"]))
        finally:
            server.shutdown(); server.server_close()
        return ran, calls

    def test_grade_from_shot_review_hands_off_the_gpu_and_keeps_a_one_click_retake(self):
        take = next(v for v in self.ok(f"/shots/{self.shot}/videos")["items"] if v["selected"])
        queued = self.ok(f"/shots/{self.shot}/grades", "POST", {"videoId": take["videoId"]})
        self.assertEqual((queued["status"], queued["assetUrl"], queued["auto"]), ("queued", self.take, False))
        self.assertEqual(self.ok(f"/shots/{self.shot}/grades", "POST", {"videoId": take["videoId"]})["gradeId"], queued["gradeId"])  # in flight once
        ran, calls = self.run_grader(busy_polls=1)
        self.assertEqual(ran, 1)
        paths = [c[1] for c in calls]
        self.assertNotIn("/interrupt", paths)
        order = [paths.index(p) for p in ("/queue", "/free", "/v1/chat/completions", "/api/generate")]
        self.assertEqual(order, sorted(order))  # wait, free ComfyUI, grade, then unload the vision model
        self.assertEqual(calls[paths.index("/api/generate")][2], {"model": "qwen-test", "keep_alive": 0})
        self.assertIn("S03", calls[paths.index("/v1/chat/completions")][2]["messages"][1]["content"][0]["text"])

        listing = self.ok(f"/shots/{self.shot}/grades")
        self.assertFalse(listing["autoGrade"])
        grade = listing["items"][0]
        self.assertEqual((grade["status"], grade["score"], grade["passed"], grade["model"]), ("graded", 58, False, "qwen-test"))
        self.assertEqual(grade["issues"], ["Hand leaves the dial late (2.8s)."])
        self.assertTrue(grade["gpu"]["comfyFreed"] and grade["gpu"]["waitedForRenders"] and grade["gpu"]["visionUnloaded"])
        self.assertEqual(self.repo.get_asset_meta(self.conn, self.slug, grade["sheetUrl"].rsplit("/", 1)[1])[0], "image/png")

        retake = "Kael keeps his hand on the dial to the final frame. @CAST-01 @SET-01"
        self.assertEqual(grade["retakePrompt"], retake)
        self.assertNotIn("proposalId", grade)  # grading is information: no proposal waits for approval
        self.conn.rollback()
        row = lambda: next(r for r in self.story.table_rows(self.conn, self.slug, "cinema-studio") if r["rid"] == self.row["rid"])
        self.assertEqual(row()["cells"][3], self.row["cells"][3])  # grading alone never edits the shot
        self.ok(f"/shots/{self.shot}", "PATCH", {"description": retake})  # Retake with this prompt, step one
        self.conn.rollback()
        self.assertEqual(row()["cells"][3], retake)

    def test_passing_grade_stages_nothing_and_bad_answers_fail_visibly(self):
        self.ok(f"/shots/{self.shot}/grades", "POST", {"assetUrl": self.take})
        self.run_grader(answer=json.dumps({"score": 84, "passed": True, "issues": [], "feedback": "Holds.", "retake_prompt": ""}))
        grade = self.ok(f"/shots/{self.shot}/grades")["items"][0]
        self.assertEqual((grade["score"], grade["passed"], grade["retakePrompt"]), (84, True, ""))
        self.ok(f"/shots/{self.shot}/grades", "POST", {"assetUrl": self.take})
        self.run_grader(answer="I cannot see the image.")
        grade = self.ok(f"/shots/{self.shot}/grades")["items"][0]
        self.assertEqual((grade["status"], grade["error"]), ("failed", "The vision model returned an unreadable scorecard."))

    def test_only_this_productions_videos_are_graded(self):
        image = f"/projects/api/{self.slug}/assets/" + self.repo.put_asset(self.conn, self.slug, data=b"\x89PNG\r\n\x1a\n" + b"0" * 64, content_type="image/png", actor_id=self.actor)
        self.conn.commit()
        for body in ({"assetUrl": image}, {"assetUrl": "/projects/api/other/assets/pa_" + "0" * 32}):
            code, payload = self.call(f"/shots/{self.shot}/grades", "POST", body)
            self.assertEqual((code, payload["code"]), (422, "DRAMA_VALIDATION_FAILED"))
        self.assertEqual(self.call(f"/shots/{self.shot}/grades", "POST", {"videoId": "vd_missing"})[0], 404)

    def test_auto_grade_is_off_until_the_production_opts_in(self):
        tab, rid = "cinema-studio", self.row["rid"]
        self.assertIsNone(grader.on_take(self.conn, self.slug, tab, rid, {"asset_url": self.take}, self.actor))
        self.assertEqual(self.ok(f"/projects/pj_{self.slug}/grading", "PUT", {"autoGrade": True}), {"autoGrade": True})
        queued = grader.on_take(self.conn, self.slug, tab, rid, {"asset_url": self.take}, self.actor)
        self.assertEqual((queued["status"], queued["auto"], queued["shotId"]), ("queued", True, self.shot))
        self.assertIsNone(grader.on_take(self.conn, self.slug, "soul-cast", rid, {"asset_url": self.take}, self.actor))
        self.assertEqual(self.ok(f"/projects/pj_{self.slug}/grading"), {"autoGrade": True})


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "set OPENBENCH_TEST_DB_URI")
class TakeLandsHookTests(unittest.TestCase):
    import test_execution as legacy
    setUp, tearDown = legacy.PostgreSQLExecutionTests.setUp, legacy.PostgreSQLExecutionTests.tearDown

    def test_a_worker_output_on_a_row_reaches_the_auto_grade_hook(self):
        from project_assistant import flow_runner
        flow_runner.save_definition(self.conn, self.me, self.slug, "flow", {"revision": 0, "definition": {"edges": [], "nodes": [
            {"id": "shot", "scope": "rows", "capability": "llm", "row_source": {"tab_key": "shots", "table_id": "b_table"},
             "target": {"tab_key": "shots", "col_index": 1}}]}})
        flow_runner.start(self.conn, self.me, self.slug, "flow", {})
        task = flow_runner.claim(self.conn, self.worker)["task"]
        url = f"/projects/api/{self.slug}/assets/" + self.legacy_asset()
        with patch.object(grader, "on_take", return_value=None) as hook:
            done = flow_runner.complete(self.conn, self.worker, {"task_id": task["id"], "lease_token": task["lease_token"], "output": {"asset_url": url}})
        self.assertEqual(done["status"], "awaiting_approval")  # the take still waits for the director
        hook.assert_called_once_with(self.conn, self.slug, "shots", task["row_id"], {"asset_url": url}, self.actor)

    def legacy_asset(self):
        from project_docs import repository as repo
        return repo.put_asset(self.conn, self.slug, data=b"\x00\x00\x00\x18ftypmp42" + b"0" * 64, content_type="video/mp4", actor_id=self.actor)


if __name__ == "__main__":
    unittest.main()
