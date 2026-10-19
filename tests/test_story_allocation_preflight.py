"""Authorized Story input preflight; real isolated PG/HTTP and local preparation.

No model inference: the bulk consumer substitutes only the final local render.
"""
import copy
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
import test_story_openapi as fixture
from project_docs import repository as repo, story_openapi as story, story_allocation
from project_assistant import limb_worker as worker


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "dedicated PostgreSQL URI required")
class AllocationPreflightTests(unittest.TestCase):
    request = fixture.StoryHTTPTests.request
    call = fixture.StoryHTTPTests.call
    ok = fixture.StoryHTTPTests.ok

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(prefix="allocation-preflight-")
        path = Path(cls.folder.name) / "synthetic.mp4"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "color=c=blue:s=64x64:r=8:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart", str(path)], check=True, capture_output=True, timeout=20)
        cls.video = path.read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        fixture.StoryHTTPTests.setUp(self)
        self.env = patch.dict(os.environ, {"OPENBENCH_PRODUCTION_POLICY": "hybrid_studio",
            "SEEDANCE_API_URL": "http://127.0.0.1:1/fixture", "SEEDANCE_API_KEY": "fixture-not-a-real-key",
            "KLING_API_URL": "http://127.0.0.1:1/fixture", "KLING_API_KEY": "fixture-not-a-real-key",
            "RUNNINGHUB_API_URL": "http://127.0.0.1:1/fixture", "RUNNINGHUB_API_KEY": "fixture-not-a-real-key"})
        self.env.start()
        self.health = patch.object(worker, "probe_local_comfy_status", return_value={"online": True})
        self.health.start()

    def tearDown(self):
        self.health.stop()
        self.env.stop()
        fixture.StoryHTTPTests.tearDown(self)

    def rows(self, count=1, prompt="@SET-01 empty room"):
        result = []
        for i in range(count):
            rid = story.mutate_row(self.conn, self.me, self.slug, "cinema-studio",
                cells={0: f"TEST-{i}", 1: "35mm", 2: "Static Tripod", 3: prompt, 6: "Queued"})
            result.append(f"sh_{self.slug}_{rid}")
        self.conn.commit()
        return result

    def media(self, mime="image/png", slug=None, *, color="green"):
        if mime.startswith("image/"):
            stream = io.BytesIO(); Image.new("RGB", (16, 16), color).save(stream, format="PNG")
            raw = stream.getvalue()
        else:
            raw = self.video
        slug = slug or self.slug
        aid = repo.put_asset(self.conn, slug, data=raw, content_type=mime, actor_id=self.actor)
        self.conn.commit()
        return f"/projects/api/{slug}/assets/{aid}"

    def set_inputs(self, identifier, *, image=None, video=None, prompt="@CAST-01 walks"):
        _, row = story.find_row(self.conn, identifier, "shot")
        cells = {3: prompt + (f" [Video]({video})" if video else ""), 4: f"![Image]({image})" if image else ""}
        story.mutate_row(self.conn, self.me, self.slug, row["tabKey"], row["rid"], cells)
        self.conn.commit()

    def preview(self, ids, **body):
        return self.ok(f"/projects/pj_{self.slug}/episodes/{self.ep}/shots:plan-allocation", "POST", {"shotIds": ids, **body})

    def hybrid(self):
        self.ok(f"/projects/pj_{self.slug}/production-policy", "PUT", {"productionPolicy": "hybrid_studio"})

    def test_offline_deadline_missing_cloud_inputs_blocks_entire_batch_before_dispatch(self):
        ids = self.rows(5); self.hybrid()
        with patch.object(worker, "probe_local_comfy_status", return_value={"online": False}), \
             patch.object(repo, "get_asset", side_effect=AssertionError("preflight must not read blobs")), \
             patch.object(worker, "ffmpeg", side_effect=AssertionError("preflight must not render")):
            plan = self.preview(ids, budgetMode="deadline_rush")
        cloud = next(a for a in plan["allocations"] if a["assignedCardId"] == "rh-cloud-h3-burst")
        self.assertFalse(cloud["ready"])
        self.assertTrue(any("27.video" in b for b in cloud["input_blockers"]))
        self.assertTrue(any("51.image" in b for b in cloud["input_blockers"]))
        self.assertFalse(plan["ready"])
        self.assertTrue(plan["allocations"][0]["ready"])
        with patch.object(story, "generation", side_effect=AssertionError("no partial batch")):
            code, _ = self.call(f"/episodes/{self.ep}/shot-video-generations", "POST", {"allocationId": plan["allocationId"], "shotIds": ids})
        self.assertEqual(code, 409)
        self.assertFalse(story.record(self.conn, plan["allocationId"]).get("consumed", False))

    def test_bulk_structural_generation_consumer_receives_contact_sheet_and_structure(self):
        identifier = self.rows(prompt="@CAST-01 @CAST-02 fight with hands")[0]
        self.set_inputs(identifier, image=self.media(), prompt="@CAST-01 @CAST-02 fight with hands")
        plan = self.preview([identifier], budgetMode="lab_economical")
        self.assertTrue(plan["ready"], plan)
        seen = []
        def render(task, config, head):
            ctx = worker.resolve_studio_context(task)
            self.assertTrue(ctx["source_video"])
            self.assertTrue(ctx["frame_sheet"])
            self.assertNotEqual(ctx["source_video"], ctx["frame_sheet"])
            seen.append(ctx)
            return head.upload(task, self.video, "video/mp4")
        with patch.object(story._POOL, "submit"):
            group = self.ok(f"/episodes/{self.ep}/shot-video-generations", "POST", {"allocationId": plan["allocationId"], "shotIds": [identifier]})
        with patch.object(worker, "comfyui", side_effect=render):
            story.execute_task(group["taskIds"][0])
        task = story.record(self.conn, group["taskIds"][0])
        self.assertEqual(task["status"], "SUCCEEDED", task["error"])
        self.assertEqual(len(seen), 1)

    def test_deleted_required_input_rechecked_for_all_shots_before_any_task(self):
        ids = self.rows(2)
        image, second_image, video = self.media(), self.media(color="purple"), self.media("video/mp4")
        self.set_inputs(ids[0], image=image, video=video)
        self.set_inputs(ids[1], image=second_image, video=video)
        plan = self.preview(ids, appCode="h3-short-video-v3")
        self.assertTrue(plan["ready"], plan)
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM projectops.asset WHERE project_slug=%s AND asset_id=%s", (self.slug, second_image.rsplit("/", 1)[-1]))
        self.conn.commit()
        with patch.object(story, "generation", side_effect=AssertionError("must validate all shots before scheduling")):
            code, _ = self.call(f"/episodes/{self.ep}/shot-video-generations", "POST", {"allocationId": plan["allocationId"], "shotIds": ids})
        self.assertEqual(code, 409)
        self.assertFalse(story.record(self.conn, plan["allocationId"]).get("consumed", False))

    def test_explicit_cloud_and_local_cards_report_each_required_media_slot(self):
        identifier = self.rows()[0]; self.hybrid()
        for card, keys in (("rh-cloud-h3-burst", ("27.video", "51.image")), ("h3-short-video-v3", ("3.video", "1.image"))):
            with self.subTest(card=card):
                plan = self.preview([identifier], appCode=card)
                self.assertFalse(plan["ready"])
                shot = plan["allocations"][0]
                self.assertEqual(shot["readiness_scope"], "configuration_and_inputs")
                self.assertEqual(len(shot["input_blockers"]), 2)
                for key in keys:
                    self.assertTrue(any(key in b for b in shot["input_blockers"]))
                self.assertTrue(set(shot["input_blockers"]) <= set(shot["configuration_blockers"]))

    def test_keyframe_is_not_a_required_driving_video(self):
        identifier = self.rows()[0]
        self.set_inputs(identifier, image=self.media())
        plan = self.preview([identifier], appCode="h3-short-video-v3")
        self.assertFalse(plan["ready"])
        self.assertIn("media_type_mismatch:generate:3.video", plan["allocations"][0]["input_blockers"])
        self.assertFalse(any("1.image" in b for b in plan["allocations"][0]["input_blockers"]))

    def test_owned_cloud_inputs_ready_without_blob_upload_or_inference(self):
        identifier = self.rows()[0]; self.hybrid()
        self.set_inputs(identifier, image=self.media(), video=self.media("video/mp4"))
        with patch.object(repo, "get_asset", side_effect=AssertionError("no blob preflight")), \
             patch.object(worker, "ffmpeg", side_effect=AssertionError("no preparation during preflight")), \
             patch.object(worker, "execute_story_card", side_effect=AssertionError("no inference")), \
             patch.object(worker, "json_fetch", side_effect=AssertionError("no provider calls")):
            plan = self.preview([identifier], appCode="rh-cloud-h3-burst")
        self.assertTrue(plan["ready"], plan)
        self.assertEqual(plan["allocations"][0]["input_blockers"], [])

    def test_foreign_missing_wrong_type_and_oversized_media_are_blocked(self):
        identifier = self.rows()[0]
        own_image, own_video = self.media(), self.media("video/mp4")
        foreign = self.slug + "-foreign"
        repo.upsert_project(self.conn, foreign, "Synthetic foreign production"); self.conn.commit()
        self.extra_projects.append(foreign)
        foreign_image = self.media(slug=foreign)
        cases = [(foreign_image, own_video, "media_not_owned"),
                 (f"/projects/api/{self.slug}/assets/pa_" + "0" * 32, own_video, "media_missing"),
                 (own_video, own_video, "media_type_mismatch"),
                 (own_image, "https://example.invalid/signed?token=must-not-echo", "media_type_mismatch")]
        for image, video, blocker in cases:
            with self.subTest(blocker=blocker):
                self.set_inputs(identifier, image=image, video=video)
                plan = self.preview([identifier], appCode="h3-short-video-v3")
                self.assertFalse(plan["ready"])
                self.assertTrue(any(b.startswith(blocker) for b in plan["allocations"][0]["input_blockers"]), plan["allocations"][0]["input_blockers"])
                self.assertNotIn("must-not-echo", str(plan["allocations"][0]["input_blockers"]))
        self.set_inputs(identifier, image=own_image, video=own_video)
        with self.conn.cursor() as cur:
            cur.execute("UPDATE projectops.asset SET byte_size=%s WHERE project_slug=%s AND asset_id=%s", (worker.MAX_MEDIA + 1, self.slug, own_image.rsplit("/", 1)[-1]))
        self.conn.commit()
        self.assertTrue(any(b.startswith("media_size_invalid") for b in self.preview([identifier], appCode="h3-short-video-v3")["allocations"][0]["input_blockers"]))

    def test_variant_cast_reference_and_real_row_video_satisfy_card(self):
        identifier = self.rows()[0]
        image, video = self.media(), self.media("video/mp4")
        cast = next(r for r in story.table_rows(self.conn, self.slug, "soul-cast") if r["cells"][0] == "CAST-01")
        story.mutate_row(self.conn, self.me, self.slug, "soul-cast", cast["rid"], {3: f"![Reference]({image})"})
        self.set_inputs(identifier, video=video, prompt="@CAST-01:night speaks")
        plan = self.preview([identifier], appCode="h3-short-video-v3")
        self.assertTrue(plan["ready"], plan)
        self.assertEqual(plan["allocations"][0]["cast_count"], 1)

    def test_procedural_preparation_is_typed_future_media_not_an_existing_asset(self):
        identifier = self.rows(prompt="@CAST-01 @CAST-02 fight")[0]
        self.set_inputs(identifier, image=self.media(), prompt="@CAST-01 @CAST-02 fight")
        real_lookup = repo.get_asset_meta
        looked_up = []
        def lookup(conn, slug, aid):
            looked_up.append(aid)
            self.assertRegex(aid, r"^pa_[0-9a-f]{32}$")
            return real_lookup(conn, slug, aid)
        with patch.object(repo, "get_asset_meta", side_effect=lookup), \
             patch.object(worker, "ffmpeg", side_effect=AssertionError("symbolic preflight only")):
            plan = self.preview([identifier], budgetMode="lab_economical")
        self.assertTrue(plan["ready"], plan)
        self.assertTrue(looked_up)
        inputs = plan["allocations"][0]["stages"][-1]["inputs"]
        self.assertEqual(inputs["frame_sheet"], {"from_step": "frame_sheet", "output_role": "frame_sheet"})
        self.assertEqual(inputs["source_video"]["from_step"], "structure")
        self.assertNotIn("planned_output", str(plan))
        # Structure supplies motion, not a missing character/reference image.
        self.set_inputs(identifier, prompt="@CAST-01 @CAST-02 fight")
        missing = self.preview([identifier], budgetMode="lab_economical")
        self.assertFalse(missing["ready"])
        self.assertTrue(any("1.image" in b for b in missing["allocations"][0]["input_blockers"]))

    def test_broken_preparation_dependencies_roles_and_source_are_not_ready(self):
        identifier = self.rows(prompt="@CAST-01 @CAST-02 fight")[0]
        self.set_inputs(identifier, image=self.media(), prompt="@CAST-01 @CAST-02 fight")
        _, row = story.find_row(self.conn, identifier, "shot")
        original = worker.select_card_for_shot(story.shot_view(self.conn, self.slug, row), budget_mode="lab_economical", local_comfy_online=True)
        cards = {original["assigned_card_id"]: worker._resolve_openapi_card_and_workflow(original["assigned_card_id"])}
        for defect in ("missing_step", "wrong_role", "wrong_dependency", "unbound_dependency", "missing_source", "invalid_mode"):
            with self.subTest(defect=defect):
                allocation = copy.deepcopy(original)
                if defect == "missing_step":
                    allocation["stages"][-1]["inputs"]["frame_sheet"]["from_step"] = "not_created"
                elif defect == "wrong_role":
                    allocation["stages"][-1]["inputs"]["frame_sheet"]["output_role"] = "output_video"
                elif defect == "wrong_dependency":
                    allocation["stages"][1]["depends_on"] = ["generate"]
                elif defect == "unbound_dependency":
                    allocation["stages"][-1]["depends_on"] = []
                elif defect == "missing_source":
                    allocation["stages"][0]["config"] = {"mode": "motion_structure", "structure_type": "edge_lineart"}
                else:
                    allocation["stages"][0]["config"] = {"mode": "not_a_supported_mode"}
                story_allocation.preflight_inputs(self.conn, self.slug, identifier, allocation, cards)
                self.assertFalse(allocation["ready"])
                self.assertTrue(allocation["input_blockers"])

    def test_imported_custom_card_required_inputs_share_preflight_and_freeze(self):
        identifier = self.rows()[0]
        card_id = "test-card-" + self.slug
        graph = {"1": {"class_type": "LoadImage", "inputs": {"image": "None"}},
                 "2": {"class_type": "VHS_VideoCombine", "inputs": {"images": ["1", 0], "filename_prefix": "custom"}}}
        code, result, _ = self.request("/openapi/v2/cards/register", method="POST", data={"card_id": card_id, "workflow": graph, "label": "Required image fixture"})
        self.assertEqual(code, 200, result)
        missing = self.preview([identifier], appCode=card_id)
        self.assertFalse(missing["ready"])
        self.assertTrue(any("1.image" in b for b in missing["allocations"][0]["input_blockers"]))
        self.set_inputs(identifier, image=self.media())
        valid = self.preview([identifier], appCode=card_id)
        self.assertTrue(valid["ready"], valid)
        frozen = story.record(self.conn, valid["allocationId"])["cards"][card_id]
        self.assertEqual(frozen[1], graph)

    def test_escalation_validates_later_preparation_before_any_m8_enqueue(self):
        from project_assistant import story_media_adapter
        identifier = self.rows()[0]; self.hybrid()
        path = f"/projects/pj_{self.slug}/episodes/{self.ep}/shots/{identifier}:escalate"
        with patch.object(story_media_adapter, "enqueue", side_effect=AssertionError("no partial paid/structural chain")):
            for strategy in ("open_structural_lock", "closed_to_open_4k", "ab_race"):
                code, payload = self.call(path, "POST", {"strategy": strategy})
                self.assertEqual(code, 409, payload)
        self.set_inputs(identifier, image=self.media())
        with patch.object(story_media_adapter, "enqueue", return_value={"runId": "synthetic-not-executed", "status": "QUEUED"}) as enqueue:
            self.assertEqual(self.call(path, "POST", {"strategy": "open_structural_lock"})[0], 200)
            self.assertTrue(enqueue.call_args.args[4]["ready"])

    def test_configuration_readiness_stays_distinct_from_input_readiness(self):
        identifier = self.rows()[0]; self.hybrid()
        with patch.dict(os.environ, {"SEEDANCE_API_KEY": ""}):
            plan = self.preview([identifier], appCode="seedance-20-pro")
        self.assertFalse(plan["ready"])
        self.assertEqual(plan["allocations"][0]["input_blockers"], [])
        self.assertIn("selected_card_unavailable", plan["allocations"][0]["configuration_blockers"])
        pure = worker.select_card_for_shot({"shotId": identifier}, local_comfy_online=True)
        self.assertTrue(pure["ready"])
        self.assertEqual(pure["readiness_scope"], "configuration_and_availability")
        self.assertNotIn("input_blockers", pure)
