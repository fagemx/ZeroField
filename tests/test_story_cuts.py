"""SPEC_19 R17: the cuts of an episode film and which of them can be checked.

Real PostgreSQL (OPENBENCH_TEST_DB_URI, a throwaway database) with the zerofield_studio template: slate shots S01-S03 and the
lab clip VFX-01. Nothing here runs the grader; the check results are written as the grader would write them, and the
vision model is never called (test_take_grader covers the grading itself).
"""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from project_assistant import take_grader as grader
from project_docs import repository as repo, service, story_cuts, story_openapi as story, story_trim
import test_story_openapi as fixture


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "set OPENBENCH_TEST_DB_URI (a throwaway database) for cut tests")
class StoryCutsTests(unittest.TestCase):
    setUp_fixture, tearDown = fixture.StoryHTTPTests.setUp, fixture.StoryHTTPTests.tearDown

    def setUp(self):
        self.setUp_fixture()
        self.kick = patch.object(grader, "kick", side_effect=AssertionError("queueing alone never starts the grader"))
        self.kick.start()
        self.addCleanup(self.kick.stop)

    # ---------- helpers ----------

    def video(self, tag, content_type="video/mp4"):
        data = (b"\x00\x00\x00\x18ftypmp42" if content_type.startswith("video/") else b"\x89PNG\r\n\x1a\n") + tag.encode() * 32
        url = f"/projects/api/{self.slug}/assets/" + repo.put_asset(self.conn, self.slug, data=data, content_type=content_type, actor_id=self.actor)
        self.conn.commit()
        return url

    def row(self, code, tab="cinema-studio"):
        self.conn.rollback()
        return next(r for r in story.table_rows(self.conn, self.slug, tab) if r["cells"][0] == code)

    def shot(self, code, tab="cinema-studio"):
        return story.shot_id(self.slug, self.row(code, tab))

    def adopt(self, code, url, status="Approved", tab="cinema-studio"):
        """A legacy-style adoption: the take in the video cell and the status, one sheet edit."""
        row = self.row(code, tab)
        status_col = next(i for i, h in enumerate(row["headers"]) if h.casefold() == "status")
        cells = {status_col: status}
        if url is not None:
            cells[story.media_column(row, "video")] = f"[Video]({url})"
        story.mutate_row(self.conn, self.me, self.slug, tab, row["rid"], cells)
        self.conn.commit()

    def trim(self, code, body):
        row = self.row(code)
        story_trim.set_trim(self.conn, self.slug, story.shot_id(self.slug, row), row, body)
        self.conn.commit()

    def cuts(self):
        self.conn.rollback()
        return story_cuts.list_cuts(self.conn, self.slug, f"ep_{self.slug}_01")["items"]

    def queue(self, pairs=None, me=None):
        try:
            result = story_cuts.queue_cut_checks(self.conn, me or self.me, self.slug, f"ep_{self.slug}_01", pairs)
        except Exception:
            self.conn.rollback()
            raise
        self.conn.commit()
        return result

    def refused(self, pairs, me=None):
        with self.assertRaises(story.StoryError) as caught:
            self.queue(pairs, me)
        return caught.exception.status, caught.exception.code

    def finish(self, check_id, **result):
        """Write a check's result as the grader does once the vision model has answered."""
        self.conn.rollback()
        record = story.record(self.conn, check_id)
        record.update({"status": "graded", "score": 71, "passed": True, "issues": [], "feedback": "Matches.",
                       "sheetUrl": f"/projects/api/{self.slug}/assets/pa_" + "c" * 32, "gradedAt": story.now(),
                       "frames": {"outSeconds": 3.958, "inSeconds": 0.0}} | result)
        story.store(self.conn, check_id, grader.CUT_KIND, record, self.slug)
        self.conn.commit()

    def pair(self, a, b):
        return [self.shot(a), self.shot(b)]

    # ---------- tests ----------

    def test_neighbouring_shots_in_film_order_and_only_adopted_pairs_are_checkable(self):
        items = self.cuts()
        self.assertEqual([(c["fromShotIndex"], c["toShotIndex"]) for c in items], [("S01", "S02"), ("S02", "S03")])
        self.assertEqual([c["index"] for c in items], [0, 1])
        for cut in items:  # nothing adopted: listed, not checkable, never checked
            self.assertFalse(cut["checkable"])
            self.assertEqual([b["reason"] for b in cut["blockedBy"]], ["not_adopted", "not_adopted"])
            self.assertEqual((cut["fromTakeUrl"], cut["toTakeUrl"], cut["outAt"], cut["inAt"]), (None, None, None, None))
            self.assertEqual(cut["check"], grader.cut_check_view(None))
            self.assertEqual((cut["check"]["state"], cut["check"]["score"], cut["check"]["issues"], cut["check"]["frameSheetUrl"]),
                             ("none", None, [], None))

        a, b = self.video("a"), self.video("b")
        self.adopt("S01", a)
        self.adopt("S02", b)
        self.adopt("S03", self.video("c"), status="Retake")  # a take in the cell is not an adoption
        first, second = self.cuts()
        self.assertEqual((first["fromShotId"], first["toShotId"]), tuple(self.pair("S01", "S02")))
        self.assertTrue(first["checkable"])
        self.assertEqual((first["blockedBy"], first["fromTakeUrl"], first["toTakeUrl"], first["outAt"], first["inAt"]), ([], a, b, None, 0.0))
        self.assertFalse(second["checkable"])
        self.assertEqual(second["blockedBy"], [{"shotId": self.shot("S03"), "reason": "not_adopted"}])
        self.assertEqual((second["fromTakeUrl"], second["toTakeUrl"], second["outAt"], second["inAt"]), (b, None, None, None))

        # Another production's asset adopted on S03: adopted, but no frames can be read from it.
        self.adopt("S03", "/projects/api/other-production/assets/pa_" + "0" * 32)
        self.assertEqual(self.cuts()[1]["blockedBy"], [{"shotId": self.shot("S03"), "reason": "external_take"}])

        # Film order is the natural shot-index order, not the sheet order; a lab clip joins only once adopted.
        story.mutate_row(self.conn, self.me, self.slug, "cinema-studio", None, {0: "S00"})
        self.conn.commit()
        self.assertEqual([(c["fromShotIndex"], c["toShotIndex"]) for c in self.cuts()], [("S00", "S01"), ("S01", "S02"), ("S02", "S03")])
        self.adopt("VFX-01", self.video("lab"), tab="openjutsu-lab")
        self.assertEqual([(c["fromShotIndex"], c["toShotIndex"]) for c in self.cuts()][-1], ("S03", "VFX-01"))
        self.assertTrue(self.cuts()[1]["checkable"])  # S01 -> S02 is unaffected by the new neighbours

        with self.assertRaises(story.StoryError) as caught:
            story_cuts.list_cuts(self.conn, "another-production", f"ep_{self.slug}_01")
        self.assertEqual((caught.exception.status, caught.exception.code), (404, "DRAMA_NOT_FOUND"))

    def test_a_new_take_or_trim_on_either_side_leaves_the_old_check_out_of_date(self):
        a, b, c = self.video("a"), self.video("b"), self.video("c")
        self.adopt("S01", a)
        self.adopt("S02", b)
        self.adopt("S03", c)
        queued = self.queue([self.pair("S01", "S02")])
        self.assertEqual(queued["queued"], 1)
        check_id = queued["checkIds"][0]
        self.assertEqual(self.cuts()[0]["check"]["state"], "queued")
        self.finish(check_id, score=64, passed=False, issues=["S01 ends with the recorder in the left hand; S02 starts with it in the right hand."])
        done = self.cuts()[0]["check"]
        self.assertEqual((done["state"], done["checkId"], done["score"], done["passed"]), ("done", check_id, 64, False))
        self.assertEqual(done["issues"], ["S01 ends with the recorder in the left hand; S02 starts with it in the right hand."])
        self.assertTrue(done["frameSheetUrl"].startswith(f"/projects/api/{self.slug}/assets/pa_"))
        self.assertEqual(self.cuts()[1]["check"]["state"], "none")  # the other cut was never checked

        # The incoming shot adopts another take: no result for these takes yet. The old record is kept, not rewritten.
        self.adopt("S02", self.video("b2"))
        self.assertEqual(self.cuts()[0]["check"]["state"], "none")
        self.conn.rollback()
        self.assertEqual([r["checkId"] for r in story.records(self.conn, grader.CUT_KIND, self.slug)], [check_id])
        self.adopt("S02", b)  # back to the checked take: the checked result is current again
        self.assertEqual(self.cuts()[0]["check"]["state"], "done")

        # The outgoing take: a new adoption, then a trim of its out point.
        self.adopt("S01", self.video("a2"))
        self.assertEqual(self.cuts()[0]["check"]["state"], "none")
        self.adopt("S01", a)
        self.trim("S01", {"in": 0.25, "out": 0.5})
        cut = self.cuts()[0]
        self.assertEqual((cut["outAt"], cut["inAt"], cut["check"]["state"]), (0.5, 0.0, "none"))
        self.trim("S01", {"in": 0.5})  # only the outgoing in point changed: not part of this cut
        self.assertEqual((self.cuts()[0]["outAt"], self.cuts()[0]["check"]["state"]), (None, "done"))
        self.trim("S01", {})

        # The incoming in point is part of the cut; its out point belongs to the next cut.
        self.trim("S02", {"in": 0.2})
        self.assertEqual((self.cuts()[0]["inAt"], self.cuts()[0]["check"]["state"]), (0.2, "none"))
        self.trim("S02", {"in": 0, "out": 0.6})
        first, second = self.cuts()
        self.assertEqual((first["inAt"], first["check"]["state"]), (0.0, "done"))
        self.assertEqual(second["outAt"], 0.6)

        # A check queued by a grader that died long ago reads as none, so it can be queued again.
        record = story.record(self.conn, check_id)
        record.update(status="grading", requestedAt=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat())
        story.store(self.conn, check_id, grader.CUT_KIND, record, self.slug)
        self.conn.commit()
        self.assertEqual(self.cuts()[0]["check"]["state"], "none")

    def test_pairs_choose_cuts_and_no_pairs_queue_every_unchecked_cut(self):
        for code in ("S01", "S02", "S03"):
            self.adopt(code, self.video(code))
        first, second = self.cuts()
        self.assertEqual(self.queue([self.pair("S01", "S02")])["queued"], 1)
        self.assertEqual([c["check"]["state"] for c in self.cuts()], ["queued", "none"])
        # No pairs: every checkable cut without a current result; the one in flight is not queued twice.
        result = self.queue()
        self.assertEqual((result["queued"], result["checkIds"], result["skipped"]), (1, [grader.cut_record_id(second)], []))
        self.assertEqual([c["check"]["state"] for c in self.cuts()], ["queued", "queued"])
        self.assertEqual(self.queue()["queued"], 0)
        self.conn.rollback()
        records = {r["checkId"]: r for r in story.records(self.conn, grader.CUT_KIND, self.slug)}
        self.assertEqual(set(records), {grader.cut_record_id(first), grader.cut_record_id(second)})
        saved = records[grader.cut_record_id(first)]
        self.assertEqual({k: saved[k] for k in ("episodeId", "fromShotId", "toShotId", "fromTakeUrl", "toTakeUrl", "outAt", "inAt", "status", "auto", "requestedBy")},
                         {"episodeId": f"ep_{self.slug}_01", "fromShotId": first["fromShotId"], "toShotId": first["toShotId"],
                          "fromTakeUrl": first["fromTakeUrl"], "toTakeUrl": first["toTakeUrl"], "outAt": None, "inAt": 0.0,
                          "status": "queued", "auto": False, "requestedBy": self.actor})
        # A named cut already in flight is returned as it is and counted.
        again = self.queue([self.pair("S01", "S02"), self.pair("S01", "S02")])
        self.assertEqual((again["queued"], again["checkIds"]), (1, [grader.cut_record_id(first)]))

        # A failed or done check is not out of date: only a named pair checks it again.
        self.finish(grader.cut_record_id(first), status="failed", error="The vision model did not answer.")
        self.assertEqual(self.cuts()[0]["check"]["state"], "failed")
        self.assertEqual(self.cuts()[0]["check"]["error"], "The vision model did not answer.")
        self.assertEqual(self.queue()["queued"], 0)
        self.assertEqual(self.queue([self.pair("S01", "S02")])["queued"], 1)
        self.assertEqual(self.cuts()[0]["check"]["state"], "queued")

        # Refusals: not neighbours (or reversed), malformed, or a side without an adopted take.
        for pairs in ([self.pair("S01", "S03")], [self.pair("S02", "S01")], "all", [], [[self.shot("S01")]], [[1, 2]]):
            self.assertEqual(self.refused(pairs), (422, "DRAMA_VALIDATION_FAILED"), pairs)
        self.adopt("S03", None, status="Retake")
        self.assertEqual(self.refused([self.pair("S02", "S03")]), (409, "DRAMA_STAGE_PRECONDITION"))

        # A take that is not a video: named, it is refused; with no pairs it is skipped and reported.
        self.adopt("S03", self.video("still", "image/png"))
        self.assertTrue(self.cuts()[1]["checkable"])
        self.assertEqual(self.refused([self.pair("S02", "S03")]), (422, "DRAMA_VALIDATION_FAILED"))
        skipped = self.queue()
        self.assertEqual((skipped["queued"], [(s["fromShotId"], s["toShotId"]) for s in skipped["skipped"]]),
                         (0, [tuple(self.pair("S02", "S03"))]))
        self.assertIn("video takes", skipped["skipped"][0]["message"])

        # Masked numbers: frames may not leave the production.
        self.adopt("S03", self.video("S03-final"))
        repo.update_project_meta(self.conn, self.slug, privacy_mode="mask_numbers")
        self.conn.commit()
        self.assertEqual(self.refused(None), (422, "DRAMA_VALIDATION_FAILED"))

    def test_read_only_crew_members_cannot_queue_checks(self):
        self.adopt("S01", self.video("a"))
        self.adopt("S02", self.video("b"))
        viewer = service.Identity(self.actor, "Read only", "viewer")
        self.assertEqual(self.refused(None, viewer), (409, "DRAMA_OPERATION_NOT_ALLOWED"))
        self.assertEqual(self.refused([self.pair("S01", "S02")], viewer), (409, "DRAMA_OPERATION_NOT_ALLOWED"))
        # The membership is checked too: a stale writer identity of a member now read-only is refused.
        repo.upsert_member(self.conn, self.actor, "Read only", "viewer")
        self.conn.commit()
        self.assertEqual(self.refused(None)[1], "DRAMA_OPERATION_NOT_ALLOWED")
        self.assertEqual(self.cuts()[0]["check"]["state"], "none")  # nothing was queued; reading still works
        self.conn.rollback()
        self.assertEqual(story.records(self.conn, grader.CUT_KIND, self.slug), [])

    def test_the_route_handler_lists_queues_and_kicks_after_commit(self):
        self.adopt("S01", self.video("a"))
        self.adopt("S02", self.video("b"))
        ep = story.episode(self.conn, f"ep_{self.slug}_01")
        actions = []
        listed = story_cuts.dispatch(self.conn, self.me, "GET", "cuts", ep, {}, actions)
        self.assertEqual([c["toShotIndex"] for c in listed["items"]], ["S02", "S03"])
        self.assertIsNone(story_cuts.dispatch(self.conn, self.me, "GET", "films", ep, {}, actions))
        result = story_cuts.dispatch(self.conn, self.me, "POST", "cut-checks", ep, {}, actions)
        self.assertEqual((result["queued"], actions), (1, [grader.kick]))
        self.assertEqual(story_cuts.dispatch(self.conn, self.me, "POST", "cut-checks", ep, {"pairs": None}, actions)["queued"], 0)
        self.assertEqual(len(actions), 1)  # nothing new queued: no wake-up

    def test_automatic_checks_after_an_adoption_are_off_until_the_production_opts_in(self):
        for code in ("S01", "S02", "S03"):
            self.adopt(code, self.video(code))
        s02 = self.shot("S02")
        self.assertEqual(story_cuts.on_adoption_changed(self.conn, self.slug, s02, self.actor), 0)
        self.assertEqual(story.records(self.conn, grader.CUT_KIND, self.slug), [])
        grader.set_auto(self.conn, self.slug, True)
        self.assertEqual(story_cuts.on_adoption_changed(self.conn, self.slug, s02, self.actor), 2)  # both neighbouring cuts
        self.conn.commit()
        self.assertEqual([(c["check"]["state"], c["check"]["auto"]) for c in self.cuts()], [("queued", True), ("queued", True)])
        self.assertEqual(story_cuts.on_adoption_changed(self.conn, self.slug, self.shot("S01"), self.actor), 0)  # already queued
        self.adopt("S03", None, status="Retake")
        self.assertEqual(story_cuts.on_adoption_changed(self.conn, self.slug, self.shot("S03"), self.actor), 0)  # not checkable


if __name__ == "__main__":
    unittest.main()
