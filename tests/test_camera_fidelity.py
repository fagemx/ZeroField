"""Camera fidelity on synthetic clips, the take-landing hook and the stored result (PostgreSQL opts in)."""
import os
from pathlib import Path
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

from project_assistant import camera_fidelity as cf, flow_runner


def clip(path, seed, pan=0.0, zoom=0.0, frames=33, size=(320, 180)):
    """A textured plane filmed by a camera that pans `pan` px and zooms `zoom` (log) per frame."""
    import cv2
    import numpy as np
    noise = (np.random.default_rng(seed).random((540, 960)) * 255).astype(np.uint8)
    texture = cv2.cvtColor(cv2.GaussianBlur(noise, (0, 0), 1.5), cv2.COLOR_GRAY2BGR)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 24, size)
    for k in range(frames):
        centre = (480 + pan * k, 270.0)
        m = cv2.getRotationMatrix2D(centre, 0, float(np.exp(zoom * k)))
        m[:, 2] += (size[0] / 2 - centre[0], size[1] / 2 - centre[1])
        writer.write(cv2.warpAffine(texture, m, size))
    writer.release()
    return path


class CameraFidelityScoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        root = Path(cls.folder.name)
        cls.previs = clip(root / "previs.mp4", 1, pan=2.0, zoom=0.005)
        cls.matched = clip(root / "matched.mp4", 2, pan=1.6, zoom=0.004)  # same move on another set, 80% of the travel
        cls.mismatched = clip(root / "mismatched.mp4", 3, pan=-2.0)  # pans the other way and never zooms

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_matched_move_scores_high_with_travel_ratios(self):
        result = cf.score(self.previs, self.matched)
        self.assertGreater(result["score"], 0.9)
        self.assertAlmostEqual(result["pan"]["travel"], 0.8, delta=0.1)
        self.assertAlmostEqual(result["zoom"]["travel"], 0.8, delta=0.1)
        self.assertIsNone(result["tilt"]["travel"])  # the previs holds tilt: no ratio, scored by stillness
        self.assertEqual(result["tilt"]["score"], 1.0)
        self.assertEqual(result["frames"], 33)

    def test_mismatched_move_scores_low(self):
        result = cf.score(self.previs, self.mismatched)
        self.assertLess(result["score"], 0.3)
        self.assertLess(result["pan"]["travel"], 0)

    def test_previs_asset_is_read_from_the_previs_column(self):
        url = "/projects/api/film/assets/pa_" + "b" * 32
        self.assertEqual(cf.previs_asset(["Shot", "Cinema Shot", "Previs"], ["S03", "[video](x)", f"[video]({url})"]), "pa_" + "b" * 32)
        self.assertIsNone(cf.previs_asset(["Shot", "Previs"], ["S03", ""]))


class TakeLandingTests(unittest.TestCase):
    def task(self, headers, cells):
        def cell(text, kind="tableCell"):
            return {"type": kind, "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}
        doc = {"type": "doc", "content": [{"type": "table", "attrs": {"bid": "b_table"}, "content": [
            {"type": "tableRow", "attrs": {"bid": "b_head"}, "content": [cell(h, "tableHeader") for h in headers]},
            {"type": "tableRow", "attrs": {"bid": "b_s03"}, "content": [cell(c) for c in cells]}]}]}
        return {"row_id": "b_s03", "target_snapshot": {"doc": doc}}

    def land(self, task, mime="video/mp4"):
        output = {"asset_url": "/projects/api/film/assets/pa_" + "a" * 32}
        with patch.object(flow_runner.repo, "get_asset_meta", return_value=(mime, 10)), \
                patch.object(cf, "schedule") as schedule:
            flow_runner._measure_camera(None, "film", task, output)
        return schedule

    def test_video_take_in_a_previs_row_is_measured_in_the_background(self):
        previs = "/projects/api/film/assets/pa_" + "b" * 32
        schedule = self.land(self.task(["Shot", "Cinema Shot", "Previs"], ["S03", "", f"[video]({previs})"]))
        schedule.assert_called_once_with("film", "pa_" + "b" * 32, "pa_" + "a" * 32)

    def test_rows_without_previs_and_image_takes_are_not_measured(self):
        self.land(self.task(["Shot", "Cinema Shot", "Previs"], ["S03", "", ""])).assert_not_called()
        previs = "/projects/api/film/assets/pa_" + "b" * 32
        self.land(self.task(["Shot", "Keyframe", "Previs"], ["S03", "", f"[video]({previs})"]), "image/png").assert_not_called()


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "set OPENBENCH_TEST_DB_URI for PostgreSQL tests")
class StoredFidelityTests(unittest.TestCase):
    def test_status_queues_once_then_returns_the_stored_result(self):
        import psycopg
        from project_docs import http, repository as repo
        factory = lambda: psycopg.connect(os.environ["OPENBENCH_TEST_DB_URI"])
        slug, actor = "fidelity-" + uuid.uuid4().hex[:12], str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as folder, factory() as conn:
            repo.ensure_schema(conn)
            repo.upsert_project(conn, slug, "Fidelity test")
            previs = repo.put_asset(conn, slug, data=clip(Path(folder) / "p.mp4", 1, pan=2.0).read_bytes(), content_type="video/mp4", actor_id=actor)
            take = repo.put_asset(conn, slug, data=clip(Path(folder) / "t.mp4", 2, pan=2.0).read_bytes(), content_type="video/mp4", actor_id=actor)
            still = repo.put_asset(conn, slug, data=b"\x89PNG\r\n\x1a\n", content_type="image/png", actor_id=actor)
            conn.commit()
            try:
                with patch.object(http, "_CONN_FACTORY", factory):
                    self.assertEqual(cf.status(conn, slug, previs, still)[0], 404)
                    self.assertEqual(cf.status(conn, slug, previs, take), (200, {"status": "pending"}))
                    deadline = time.monotonic() + 60
                    while (slug, previs, take) in cf._PENDING and time.monotonic() < deadline:
                        time.sleep(0.1)
                    conn.rollback()
                    code, result = cf.status(conn, slug, previs, take)
                self.assertEqual((code, result["status"], result["take"]), (200, "done", take))
                self.assertGreater(result["score"], 0.9)
                self.assertAlmostEqual(result["pan"]["travel"], 1.0, delta=0.1)
            finally:
                conn.rollback()
                conn.execute("DELETE FROM projectops.project WHERE slug=%s", (slug,))
                conn.commit()


if __name__ == "__main__":
    unittest.main()
