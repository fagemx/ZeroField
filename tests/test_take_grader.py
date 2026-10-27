"""Continuity grading of sheet-row takes: rubric, GPU hand-off and the one-click retake prompt; cut checks between shots.

The vision model, Ollama and ComfyUI are one local fake HTTP server; FFmpeg and PostgreSQL are real.
"""
import base64
import functools
import io
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

from project_assistant import gpu_arbiter, providers, take_grader as grader

ANSWER = json.dumps({"score": 58, "passed": False, "issues": ["Hand leaves the dial late (2.8s)."],
                     "feedback": "Push-in lands; the hand withdraws early.", "retake_prompt": "Kael keeps his hand on the dial to the final frame."})
CUT_ANSWER = json.dumps({"score": 62, "passed": False, "feedback": "Light flips sides across the cut.",
                         "issues": ["S01 ends with the recorder in the left hand; S02 starts with it in the right hand."]})


def two_tone(first, second, folder, name):
    """A 1 s, 12 fps MP4 whose first half is one colour and second half another, so each cut point has its own colour."""
    path = Path(folder) / name
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-filter_complex",
                    f"color=c={first}:s=64x48:r=12:d=0.5[a];color=c={second}:s=64x48:r=12:d=0.5[b];[a][b]concat=n=2:v=1:a=0",
                    "-pix_fmt", "yuv420p", str(path)], check=True)
    return path.read_bytes()


def panels(png):
    """(left, right) centre pixels of a cut sheet."""
    from PIL import Image
    image = Image.open(io.BytesIO(png)).convert("RGB")
    width, height = grader.CUT_PANEL
    return image.size, image.getpixel((width // 2, 24 + height // 2)), image.getpixel((width + 8 + width // 2, 24 + height // 2))


def colour(pixel):
    names = {"red": (255, 0, 0), "green": (0, 128, 0), "blue": (0, 0, 255), "yellow": (255, 255, 0)}
    return min(names, key=lambda n: sum((a - b) ** 2 for a, b in zip(pixel, names[n])))


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

    def test_cut_sheet_puts_the_out_frame_left_and_the_in_frame_right(self):
        with tempfile.TemporaryDirectory() as folder:
            outgoing, incoming = two_tone("red", "green", folder, "a.mp4"), two_tone("blue", "yellow", folder, "b.mp4")
            # Untrimmed: the outgoing take's own last frame, the incoming take's first.
            png, frames = grader.cut_sheet(outgoing, None, incoming, 0.0, ("S01", "S02"))
            size, left, right = panels(png)
            self.assertEqual((size, colour(left), colour(right)), ((2 * 640 + 8, 24 + 360), "green", "blue"))
            self.assertEqual(frames, {"outSeconds": 0.917, "inSeconds": 0.0})
            # Trimmed: the last frame before the out point, the first frame at the in point; an out past the end is the end.
            for out_at, in_at, expected in ((0.5, 0.5, ("red", "yellow")), (5.0, 0.0, ("green", "blue"))):
                png, _ = grader.cut_sheet(outgoing, out_at, incoming, in_at, ("S01", "S02"))
                self.assertEqual(tuple(colour(p) for p in panels(png)[1:]), expected, (out_at, in_at))

    def test_cut_question_has_its_own_rubric_and_no_retake_prompt(self):
        server, base, calls = fake_gpu(answer=CUT_ANSWER)
        try:
            config = providers.ProviderConfig("openai_compat", base + "/v1", "", "qwen-test", "high")
            answer = grader.cut_vision(config, "Cut from S01 to S02.", b"png")
        finally:
            server.shutdown(); server.server_close()
        body = calls[0][2]
        self.assertEqual((body["messages"][0]["content"], body["messages"][1]["content"][0]["text"]), (grader.CUT_RUBRIC, "Cut from S01 to S02."))
        self.assertNotIn("tools", body)
        self.assertEqual(grader.cut_scorecard(answer), {"score": 62, "passed": False, "feedback": "Light flips sides across the cut.",
                                                        "issues": ["S01 ends with the recorder in the left hand; S02 starts with it in the right hand."]})
        self.assertNotIn("retakePrompt", grader.cut_scorecard(ANSWER))
        with self.assertRaises(grader.GradeError):
            grader.cut_scorecard('{"score": 62}')


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
        # The GPU arbiter remembers the resident workload per machine; start each test from "unknown".
        self.conn.execute("DELETE FROM projectops.assistant_setting WHERE project_slug=%s", (gpu_arbiter.STATE_SLUG,))
        self.conn.commit()
        self.patches = [patch.object(grader, "kick", lambda: None)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.fixture.tearDown(self)

    def run_grader(self, server=None, env=None, **fake):
        import psycopg
        own = server is None
        server, base, calls = server or fake_gpu(**fake)
        env = env or {"OPENBENCH_PROVIDER": "openai_compat", "OPENBENCH_API_BASE": base + "/v1", "OPENBENCH_MODEL": "qwen-test"}
        try:
            with patch.dict(os.environ, env), patch.object(grader, "comfy_url", lambda conn, slug: base), \
                    patch.object(grader, "hand_off", functools.partial(grader.hand_off, poll=0)):
                ran = grader.drain(lambda: psycopg.connect(os.environ["OPENBENCH_TEST_DB_URI"]))
        finally:
            if own:
                server.shutdown(); server.server_close()
        return ran, calls

    def reservations(self):
        self.conn.rollback()
        return [r[0] for r in self.conn.execute("""SELECT jsonb_build_object('state',state,'cost',accounted_cost_usd,'agent',agent_key,
            'kind',usage_kind,'session',session_key,'model',model_name) FROM projectops.agent_usage_reservation
            WHERE project_slug=%s ORDER BY created_at""", (self.slug,)).fetchall()]

    def test_grade_from_shot_review_hands_off_the_gpu_and_keeps_a_one_click_retake(self):
        take = next(v for v in self.ok(f"/shots/{self.shot}/videos")["items"] if v["selected"])
        queued = self.ok(f"/shots/{self.shot}/grades", "POST", {"videoId": take["videoId"]})
        self.assertEqual((queued["status"], queued["assetUrl"], queued["auto"]), ("queued", self.take, False))
        self.assertEqual(self.ok(f"/shots/{self.shot}/grades", "POST", {"videoId": take["videoId"]})["gradeId"], queued["gradeId"])  # in flight once
        ran, calls = self.run_grader(busy_polls=1)
        self.assertEqual(ran, 1)
        paths = [c[1] for c in calls]
        self.assertNotIn("/interrupt", paths)
        order = [paths.index(p) for p in ("/queue", "/free", "/v1/chat/completions")]
        self.assertEqual(order, sorted(order))  # wait for renders, free ComfyUI, then grade
        self.assertNotIn("/api/generate", paths)  # the vision model stays loaded until a render needs the GPU (SPEC_20 R13)
        self.assertIn("S03", calls[paths.index("/v1/chat/completions")][2]["messages"][1]["content"][0]["text"])

        listing = self.ok(f"/shots/{self.shot}/grades")
        self.assertFalse(listing["autoGrade"])
        grade = listing["items"][0]
        self.assertEqual((grade["status"], grade["score"], grade["passed"], grade["model"]), ("graded", 58, False, "qwen-test"))
        self.assertEqual(grade["issues"], ["Hand leaves the dial late (2.8s)."])
        self.assertTrue(grade["gpu"]["comfyFreed"] and grade["gpu"]["waitedForRenders"])
        self.assertFalse(grade["gpu"]["batched"])
        # Governed like an agent turn (SPEC_20 R11): admitted for the Continuity Supervisor, local so unbilled.
        self.assertEqual(self.reservations(), [{"state": "finalized", "cost": None, "agent": "qa_critic", "kind": "grader_check",
                                                "session": "grade:" + queued["gradeId"], "model": "qwen-test"}])
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

    def second_take(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "take2.mp4"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=64x48:rate=12:duration=2",
                            "-pix_fmt", "yuv420p", str(path)], check=True)
            url = f"/projects/api/{self.slug}/assets/" + self.repo.put_asset(self.conn, self.slug, data=path.read_bytes(), content_type="video/mp4", actor_id=self.actor)
        self.conn.commit()
        return url

    def test_same_shot_takes_grade_in_one_phase_and_the_model_stays_until_a_render(self):
        other = self.second_take()
        first = self.ok(f"/shots/{self.shot}/grades", "POST", {"assetUrl": self.take})
        second = self.ok(f"/shots/{self.shot}/grades", "POST", {"assetUrl": other})
        fake = fake_gpu()
        server, base, calls = fake
        try:
            self.assertEqual(self.run_grader(fake)[0], 2)
            paths = [c[1] for c in calls]
            self.assertEqual(paths.count("/free"), 1)  # ComfyUI is freed once for both takes of the shot
            self.assertEqual(paths.count("/v1/chat/completions"), 2)
            self.assertNotIn("/api/generate", paths)
            grades = {g["gradeId"]: g for g in self.ok(f"/shots/{self.shot}/grades")["items"]}
            self.assertFalse(grades[first["gradeId"]]["gpu"]["batched"])
            self.assertTrue(grades[second["gradeId"]]["gpu"]["batched"])
            # A render is the other workload: only now is the vision model unloaded (launchers enable switching).
            calls.clear()
            with patch.dict(os.environ, {gpu_arbiter.SWITCHING_ENV: "on"}):
                gpu_arbiter.render(base, label="render:test").release()
            self.assertEqual([(c[1], c[2]) for c in calls], [("/api/generate", {"model": "qwen-test", "keep_alive": 0})])
            # The next grade switches back: ComfyUI is freed again before the vision call.
            calls.clear()
            self.ok(f"/shots/{self.shot}/grades", "POST", {"assetUrl": self.take})
            self.run_grader(fake)
            self.assertEqual([c[1] for c in calls if c[1] in ("/free", "/v1/chat/completions")], ["/free", "/v1/chat/completions"])
        finally:
            server.shutdown(); server.server_close()
        self.assertEqual([r["state"] for r in self.reservations()], ["finalized"] * 3)

    def test_hosted_vision_is_refused_without_an_allowlisted_host_or_a_price(self):
        import governance_fixture
        from project_assistant import agent_console_store as console, agent_registry
        hosted = "https://vision.invalid/v1"
        env = {"OPENBENCH_AGENT_KEY_ENVS": "SPEC20_VISION_KEY", "SPEC20_VISION_KEY": "synthetic-credential"}
        with patch.dict(os.environ, env):
            agent_registry.save_agent(self.conn, self.me, self.slug, {"agent_key": "qa_critic", "provider_config": {
                "kind": "openai_compat", "base_url": hosted, "model": "hosted-vision", "api_key_env": "SPEC20_VISION_KEY"}})
        self.conn.commit()
        fake = fake_gpu()
        server, base, calls = fake
        errors = []
        try:
            def attempt():
                self.ok(f"/shots/{self.shot}/grades", "POST", {"assetUrl": self.take})
                self.run_grader(fake, env=env)
                grade = self.ok(f"/shots/{self.shot}/grades")["items"][0]
                self.assertEqual(grade["status"], "failed")
                errors.append(grade["error"])
            attempt()  # the restricted environment only reaches loopback
            governance_fixture.authorize_synthetic_media(self)
            attempt()  # full network, but no price ceiling for the hosted model
            settings = console.get_settings(self.conn, self.me, self.slug)
            console.save_settings(self.conn, self.me, self.slug, {"version": settings["version"], "model_pricing": {"hosted-vision": dict(
                kind="openai_compat", base_url=hosted, input_usd_per_million=1, output_usd_per_million=2, max_input_tokens=100000,
                max_output_tokens=10, byte_bounded_tokenizer=True)}})
            self.conn.commit()
            attempt()  # priced, yet a commercial vision request has no enforceable bound here
        finally:
            server.shutdown(); server.server_close()
        self.assertEqual(len(errors), 3)
        self.assertTrue(all(e.startswith("Model governance refused the grading call") for e in errors), errors)
        self.assertFalse(any("synthetic-credential" in e for e in errors))
        self.assertEqual(calls, [])  # no frames left, no ComfyUI hand-off for a GPU this grade does not use
        self.assertEqual(self.reservations(), [])

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


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "set OPENBENCH_TEST_DB_URI for cut check tests")
class CutCheckTests(unittest.TestCase):
    """SPEC_19 R17: the out frame of S01's adopted take and the in frame of S02's, checked through the grader's queue."""
    from test_story_openapi import StoryHTTPTests as fixture
    request, call, ok = fixture.request, fixture.call, fixture.ok
    run_grader, reservations = GradeHTTPTests.run_grader, GradeHTTPTests.reservations

    def setUp(self):
        self.fixture.setUp(self)
        from project_docs import repository as repo, story_cuts, story_openapi as story
        self.repo, self.story, self.story_cuts = repo, story, story_cuts
        self.conn.execute("DELETE FROM projectops.assistant_setting WHERE project_slug=%s", (gpu_arbiter.STATE_SLUG,))
        self.conn.commit()
        with tempfile.TemporaryDirectory() as folder:
            self.takes = {code: self.asset(two_tone(*tones, folder, code + ".mp4"))
                          for code, tones in (("S01", ("red", "green")), ("S02", ("blue", "yellow")), ("S02b", ("yellow", "red")))}
        self.patches = [patch.object(grader, "kick", lambda: None)]
        for p in self.patches:
            p.start()
        self.adopt("S01", self.takes["S01"])
        self.adopt("S02", self.takes["S02"])

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.fixture.tearDown(self)

    def asset(self, data):
        url = f"/projects/api/{self.slug}/assets/" + self.repo.put_asset(self.conn, self.slug, data=data, content_type="video/mp4", actor_id=self.actor)
        self.conn.commit()
        return url

    def shot(self, code):
        self.conn.rollback()
        return self.story.shot_id(self.slug, next(r for r in self.story.table_rows(self.conn, self.slug, "cinema-studio") if r["cells"][0] == code))

    def adopt(self, code, url):
        """A Story candidate adopted with POST /shots/{id}/adoptions, as the shot panel's check mark does."""
        import uuid
        shot = self.shot(code)
        self.story.store(self.conn, "ca_" + uuid.uuid4().hex, "candidate", {"entityId": shot, "kind": "video", "url": url, "createdAt": self.story.now()}, self.slug)
        self.conn.commit()
        video = next(v["videoId"] for v in self.ok(f"/shots/{shot}/videos?limit=100")["items"] if v["url"] == url)
        self.assertEqual(self.ok(f"/shots/{shot}/adoptions", "POST", {"videoId": video})["reviewStatus"], "Approved")

    def cuts(self):
        self.conn.rollback()
        return self.story_cuts.list_cuts(self.conn, self.slug, f"ep_{self.slug}_01")["items"]

    def queue(self):
        result = self.story_cuts.queue_cut_checks(self.conn, self.me, self.slug, f"ep_{self.slug}_01")
        self.conn.commit()
        return result["queued"]

    def test_a_cut_check_sends_both_frames_side_by_side_after_the_renders_and_keeps_the_result(self):
        self.assertEqual(self.queue(), 1)  # S01 -> S02; S02 -> S03 has no adopted take on S03
        self.assertEqual(self.cuts()[0]["check"]["state"], "queued")
        ran, calls = self.run_grader(answer=CUT_ANSWER, busy_polls=1)
        self.assertEqual(ran, 1)
        paths = [c[1] for c in calls]
        self.assertNotIn("/interrupt", paths)
        order = [paths.index(p) for p in ("/queue", "/free", "/v1/chat/completions")]
        self.assertEqual(order, sorted(order))  # wait for the renders, free ComfyUI, then ask
        self.assertEqual(paths.count("/queue"), 2)  # busy once: waited, never interrupted
        self.assertNotIn("/api/generate", paths)  # the vision model stays loaded until a render needs the GPU (SPEC_20 R13)

        chat = calls[paths.index("/v1/chat/completions")][2]
        self.assertEqual(chat["messages"][0]["content"], grader.CUT_RUBRIC)
        text, image = chat["messages"][1]["content"][0]["text"], chat["messages"][1]["content"][1]["image_url"]["url"]
        self.assertIn("Cut from S01 to S02.", text)
        self.assertIn("Kael notices the pulsing recorder", text)  # the incoming shot's prompt, so intended changes are not issues
        sent = base64.b64decode(image.split(",", 1)[1])
        size, left, right = panels(sent)
        self.assertEqual((size, colour(left), colour(right)), ((1288, 384), "green", "blue"))  # S01's last frame | S02's first

        check = self.cuts()[0]["check"]
        self.assertEqual((check["state"], check["score"], check["passed"], check["error"]), ("done", 62, False, None))
        self.assertEqual(check["issues"], ["S01 ends with the recorder in the left hand; S02 starts with it in the right hand."])
        self.assertEqual((check["frames"], check["auto"]), ({"outSeconds": 0.917, "inSeconds": 0.0}, False))
        sheet = self.repo.get_asset(self.conn, self.slug, check["frameSheetUrl"].rsplit("/", 1)[1])
        self.assertEqual((sheet[0], bytes(sheet[1])), ("image/png", sent))  # the saved sheet is what the model saw
        [record] = self.story.records(self.conn, grader.CUT_KIND, self.slug)
        self.assertEqual((record["checkId"], record["status"], record["model"]), (check["checkId"], "graded", "qwen-test"))
        self.assertTrue(record["gpu"]["comfyFreed"] and record["gpu"]["waitedForRenders"])
        self.assertFalse(record["gpu"]["batched"])
        self.assertNotIn("retakePrompt", record)
        # Governed like a grade (SPEC_20 R11): admitted for the Continuity Supervisor under its own session, local so unbilled.
        self.assertEqual(self.reservations(), [{"state": "finalized", "cost": None, "agent": "qa_critic", "kind": "grader_check",
                                                "session": "cut:" + check["checkId"], "model": "qwen-test"}])
        self.assertEqual(self.story.records(self.conn, grader.KIND, self.slug), [])  # a cut check is not a take grade

        # S02 adopts another take: the result no longer describes the cut, and nothing is re-checked by itself.
        self.adopt("S02", self.takes["S02b"])
        self.assertEqual(self.cuts()[0]["check"]["state"], "none")
        self.assertEqual([r["status"] for r in self.story.records(self.conn, grader.CUT_KIND, self.slug)], ["graded"])
        self.assertEqual(self.queue(), 1)
        self.run_grader(answer=CUT_ANSWER)
        check = self.cuts()[0]["check"]
        self.assertEqual(check["state"], "done")
        sheet = bytes(self.repo.get_asset(self.conn, self.slug, check["frameSheetUrl"].rsplit("/", 1)[1])[1])
        self.assertEqual(colour(panels(sheet)[2]), "yellow")  # the new take's first frame
        self.assertEqual(len(self.story.records(self.conn, grader.CUT_KIND, self.slug)), 2)

    def test_cut_checks_and_take_grades_share_one_queue_and_one_gpu_switch(self):
        s01 = self.shot("S01")
        self.ok(f"/shots/{s01}/trim", "PUT", {"in": 0, "out": 0.5})
        self.assertEqual(self.ok(f"/shots/{s01}/grades", "POST", {"assetUrl": self.takes["S01"]})["status"], "queued")
        self.assertEqual(self.queue(), 1)
        ran, calls = self.run_grader(answer=CUT_ANSWER)
        self.assertEqual(ran, 2)
        marks = [c[1] for c in calls if c[1] in ("/free", "/v1/chat/completions", "/api/generate")]
        # The grade frees ComfyUI; the cut check after it finds the vision model still resident (SPEC_20 R13).
        self.assertEqual(marks, ["/free", "/v1/chat/completions", "/v1/chat/completions"])
        chats = [c[2] for c in calls if c[1] == "/v1/chat/completions"]
        self.assertEqual({c["messages"][0]["content"] for c in chats}, {grader.RUBRIC, grader.CUT_RUBRIC})
        cut = next(c for c in chats if c["messages"][0]["content"] == grader.CUT_RUBRIC)
        left = panels(base64.b64decode(cut["messages"][1]["content"][1]["image_url"]["url"].split(",", 1)[1]))[1]
        self.assertEqual(colour(left), "red")  # the trimmed out point: the last frame before 0.5 s
        self.assertEqual(self.ok(f"/shots/{s01}/grades")["items"][0]["status"], "graded")
        self.assertEqual((self.cuts()[0]["outAt"], self.cuts()[0]["check"]["state"]), (0.5, "done"))

        # A check that cannot run fails visibly on the cut and leaves the GPU alone.
        self.adopt("S02", self.takes["S02b"])
        self.assertEqual(self.queue(), 1)
        self.repo.update_project_meta(self.conn, self.slug, privacy_mode="mask_numbers")
        self.conn.commit()
        ran, calls = self.run_grader(answer=CUT_ANSWER)
        self.assertEqual((ran, calls), (1, []))
        check = self.cuts()[0]["check"]
        self.assertEqual((check["state"], check["error"], check["score"]), ("failed", grader.MASKED, None))


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
