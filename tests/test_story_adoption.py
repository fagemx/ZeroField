"""SPEC_19 R1: adopting a take puts it in the cut.

Pure rules for the shot view's adoption and take summary, then real HTTP + PostgreSQL for the three adoption paths
(Story candidate, pipeline proposal, first frame), refusals, undo, legacy rows and the existing ``Approved`` consumers.
The database tests need OPENBENCH_TEST_DB_URI pointing at a throwaway database; no GPU or provider is called.
"""
import copy
import os
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from project_docs import repository as repo, story_adoption as adoption, story_openapi as story, story_trim
import test_story_openapi as fixture

UNTRIMMED = {"in": 0, "out": None}


def asset(letter, slug="demo"):
    return f"/projects/api/{slug}/assets/pa_" + letter * 32


class FakeTakes:
    """The two reads take_summary needs: the cell's revision history and this shot's candidate records."""
    slug = "demo"

    def __init__(self, history=(), records=()):
        self._history, self._records = list(history), list(records)

    def history(self, tab_key):
        return {"bshot": self._history}

    def records(self, identifier):
        assert identifier == "sh_demo_bshot"
        return self._records


def shot_row(take, status=""):
    return {"rid": "bshot", "tabKey": "cinema-studio", "headers": ["Shot", "Cinema Shot", "Status"],
            "cells": ["S01", f"[Video]({take})" if take else "", status]}


class AdoptionRuleTests(unittest.TestCase):
    AT = "2026-10-27T10:00:00+00:00"

    def test_adoption_view_reads_status_record_and_legacy_rows(self):
        record = {"adoption": {"url": asset("a"), "at": self.AT, "by": "crew"}}
        self.assertEqual(adoption.adoption_view(record, "Approved", asset("a")), {"adopted": True, "url": asset("a"), "at": self.AT, "by": "crew"})
        # A legacy approval (or a sheet edit that swapped the cell) adopted the cell's take at an unknown time.
        self.assertEqual(adoption.adoption_view({}, "Approved", asset("a")), {"adopted": True, "url": asset("a"), "at": None, "by": None})
        self.assertEqual(adoption.adoption_view(record, "Approved", asset("b")), {"adopted": True, "url": asset("b"), "at": None, "by": None})
        self.assertEqual(adoption.adoption_view({}, "已完成", asset("a"))["adopted"], True)
        # Sent to Retake after an adoption: not adopted, but the last adoption still dates newer takes.
        self.assertEqual(adoption.adoption_view(record, "Retake", asset("a")), {"adopted": False, "url": asset("a"), "at": self.AT, "by": "crew"})
        for status in ("", "Queued", "Pending Review", "Retake", "Blocked"):
            self.assertIsNone(adoption.adoption_view({}, status, asset("a")))
        self.assertIsNone(adoption.adoption_view({"adoption": "broken"}, "Retake", asset("a")))

    def test_take_summary_counts_the_take_list_and_what_is_newer_than_the_adoption(self):
        later, earlier = "2026-10-27T11:00:00+00:00", "2026-10-27T09:00:00+00:00"
        takes = FakeTakes(history=[asset("h"), asset("a")], records=[
            {"url": asset("a"), "createdAt": earlier},          # the adopted take itself never counts
            {"url": asset("b"), "createdAt": later},            # newer: counts
            {"url": asset("c"), "createdAt": earlier},          # older: does not
            {"url": asset("d")},                                # no createdAt: older than any adoption
            {"url": asset("b"), "createdAt": earlier}])         # same bytes rendered twice: the newest time wins
        adopted = adoption.adoption_view({"adoption": {"url": asset("a"), "at": self.AT, "by": "crew"}}, "Approved", asset("a"))
        self.assertEqual(adoption.take_summary(takes, shot_row(asset("a"), "Approved"), adopted), {"total": 5, "newSinceAdoption": 1})
        # A legacy approval has no time: only takes that carry a createdAt can be newer.
        legacy = adoption.adoption_view({}, "Approved", asset("a"))
        self.assertEqual(adoption.take_summary(takes, shot_row(asset("a"), "Approved"), legacy), {"total": 5, "newSinceAdoption": 2})
        old = FakeTakes(history=[asset("h")], records=[{"url": asset("d")}])
        self.assertEqual(adoption.take_summary(old, shot_row(asset("a"), "Approved"), adoption.adoption_view({}, "Approved", asset("a"))),
                         {"total": 3, "newSinceAdoption": 0})
        # Never adopted: every take is still waiting to be chosen; no take at all is an empty shot.
        self.assertEqual(adoption.take_summary(takes, shot_row(asset("a")), None), {"total": 5, "newSinceAdoption": 5})
        self.assertEqual(adoption.take_summary(FakeTakes(), shot_row(None), None), {"total": 0, "newSinceAdoption": 0})

    def test_latest_created_ignores_missing_and_unreadable_times(self):
        records = [{"url": "x", "createdAt": "2026-10-27T10:00:00+00:00"}, {"url": "x", "createdAt": "2026-10-27T10:00:00.5+00:00"},
                   {"url": "y"}, {"url": "z", "createdAt": "yesterday"}, {"url": "w", "createdAt": "2026-10-27T10:00:00"}]
        self.assertEqual(adoption.latest_created(records), {"x": "2026-10-27T10:00:00.5+00:00"})


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "set OPENBENCH_TEST_DB_URI (a throwaway database) for adoption HTTP tests")
class AdoptionHTTPTests(unittest.TestCase):
    setUp, tearDown = fixture.StoryHTTPTests.setUp, fixture.StoryHTTPTests.tearDown
    request, call, ok, prepare = fixture.StoryHTTPTests.request, fixture.StoryHTTPTests.call, fixture.StoryHTTPTests.ok, fixture.StoryHTTPTests.prepare

    # ---------- helpers ----------

    def video(self, tag):
        """A distinct (content-addressed) MP4 asset of this production."""
        data = b"\x00\x00\x00\x18ftypmp42" + tag.encode() * 32
        identifier = repo.put_asset(self.conn, self.slug, data=data, content_type="video/mp4", actor_id=self.actor)
        self.conn.commit()
        return f"/projects/api/{self.slug}/assets/{identifier}"

    def image(self, tag):
        data = b"\x89PNG\r\n\x1a\n" + tag.encode() * 32
        identifier = repo.put_asset(self.conn, self.slug, data=data, content_type="image/png", actor_id=self.actor)
        self.conn.commit()
        return f"/projects/api/{self.slug}/assets/{identifier}"

    def row(self, shot):
        self.conn.rollback()
        return story.find_row(self.conn, shot["shotId"], "shot")[1]

    def cell(self, shot, kind):
        row = self.row(shot)
        return story.media_url(row["cells"][story.media_column(row, kind)])

    def status(self, shot):
        return adoption.row_status(self.row(shot))

    def put(self, shot, kind, url, status=None):
        """Write a cell as a manual sheet edit would (it becomes a revision-history take)."""
        row = self.row(shot)
        cells = {story.media_column(row, kind): f"[{kind.title()}]({url})"}
        if status is not None:
            cells[adoption.status_index(row)] = status
        story.mutate_row(self.conn, self.me, self.slug, row["tabKey"], row["rid"], cells)
        self.conn.commit()

    def candidate(self, shot, url, created=None):
        story.store(self.conn, "ca_" + uuid.uuid4().hex, "candidate", {"entityId": shot["shotId"], "kind": "video", "url": url,
                    **({"createdAt": created} if created else {})}, self.slug)
        self.conn.commit()

    def take_id(self, shot, url, kind="video"):
        items = self.ok(f"/shots/{shot['shotId']}/{kind}s?limit=100")["items"]
        return next(item[kind + "Id"] for item in items if item["url"] == url)

    def adopt(self, shot, body):
        return self.call(f"/shots/{shot['shotId']}/adoptions", "POST", body)

    def meta(self, shot):
        self.conn.rollback()
        return story.shot_meta(self.conn, shot["shotId"])

    def pipeline_take(self, shot, url, kind="video"):
        """A pipeline render waiting for the director: a two-node run whose first node proposes ``url`` for the shot's cell."""
        from project_assistant import flow_runner
        row = self.row(shot)
        nodes = [{"id": "shot", "capability": "llm", "target": {"tab_key": row["tabKey"], "row_id": row["rid"], "col_index": story.media_column(row, kind)}},
                 {"id": "after", "capability": "llm", "target": {}}]
        current = flow_runner.definition(self.conn, self.slug, "flow")["revision"]
        flow_runner.save_definition(self.conn, self.me, self.slug, "flow", {"revision": current, "definition": {"nodes": nodes, "edges": [{"source": "shot", "target": "after"}]}})
        run = flow_runner.start(self.conn, self.me, self.slug, "flow", {})["run"]
        task = flow_runner.claim(self.conn, self.worker)["task"]
        self.assertEqual(task["node_id"], "shot")
        done = flow_runner.complete(self.conn, self.worker, {"task_id": task["id"], "lease_token": task["lease_token"], "output": {"asset_url": url}})
        self.conn.commit()
        self.assertEqual(done["status"], "awaiting_approval")
        return done["proposal_id"], run["id"]

    def flow_state(self, run_id):
        self.conn.rollback()
        with self.conn.cursor() as cur:
            cur.execute("SELECT node_id, status FROM projectops.limb_task WHERE run_id=%s", (run_id,))
            return dict(cur.fetchall())

    def proposal_status(self, proposal_id):
        from project_assistant import store
        self.conn.rollback()
        return store.proposal(self.conn, proposal_id)["status"]

    # ---------- A1: a Story candidate ----------

    def test_adopting_a_candidate_puts_it_in_the_cut_in_one_step(self):
        shot = self.prepare()[0]
        a, b = self.video("a"), self.video("b")
        self.put(shot, "video", a)
        self.candidate(shot, b, story.now())
        self.ok(f"/shots/{shot['shotId']}/trim", "PUT", {"in": 0.1, "out": 0.4})
        before = datetime.now(timezone.utc)
        view = self.ok(f"/shots/{shot['shotId']}/adoptions", "POST", {"videoId": self.take_id(shot, b)})
        self.assertEqual((view["selectedVideoUrl"], view["reviewStatus"], view["trim"]), (b, "Approved", UNTRIMMED))
        self.assertEqual({k: view["adoption"][k] for k in ("adopted", "url", "by")}, {"adopted": True, "url": b, "by": self.actor})
        self.assertGreaterEqual(datetime.fromisoformat(view["adoption"]["at"]), before)
        self.assertEqual(view["takeSummary"], {"total": 2, "newSinceAdoption": 0})
        self.assertEqual((self.cell(shot, "video"), self.status(shot)), (b, "Approved"))
        saved = self.meta(shot)
        self.assertEqual(saved["adoption"], {"url": b, "at": view["adoption"]["at"], "by": self.actor})
        self.assertNotIn("trim", saved)
        self.assertEqual(saved["sceneId"], shot["sceneId"])  # the rest of the meta is kept
        # The cell and the status were one sheet edit: a single new revision.
        revisions = [r for r in repo.revision_rows(self.conn, self.slug, tab_key="cinema-studio")]
        last = revisions[-1]["doc"]
        cells = next(r for t in last["content"] if t.get("type") == "table" for r in t["content"] if r.get("attrs", {}).get("bid") == shot["rowId"])
        self.assertIn(b, str(cells))
        self.assertIn("Approved", str(cells))
        self.assertNotIn(b, str(revisions[-2]["doc"]))

        # A newer take arrives: it is new; an older candidate (no createdAt) is not.
        self.candidate(shot, self.video("c"), story.now())
        self.candidate(shot, self.video("d"))
        current = self.ok("/shots/" + shot["shotId"])
        self.assertEqual(current["takeSummary"], {"total": 4, "newSinceAdoption": 1})
        self.assertEqual(current["takeSummary"]["total"], len(self.ok(f"/shots/{shot['shotId']}/videos?limit=100")["items"]))
        listed = next(s for s in self.ok(f"/episodes/{self.ep}/shots?limit=100")["items"] if s["shotId"] == shot["shotId"])
        self.assertEqual((listed["adoption"], listed["takeSummary"]), (current["adoption"], current["takeSummary"]))
        dated = {t["url"]: t["createdAt"] for t in self.ok(f"/shots/{shot['shotId']}/videos?limit=100")["items"]}
        self.assertEqual((dated[a], dated[self.cell(shot, "video")] is not None), (None, True))
        # Adopting again replaces the record; the earlier "new" take is now older than the adoption.
        again = self.ok(f"/shots/{shot['shotId']}/adoptions", "POST", {"videoId": self.take_id(shot, a)})
        self.assertEqual((again["selectedVideoUrl"], again["adoption"]["url"]), (a, a))
        self.assertGreater(datetime.fromisoformat(again["adoption"]["at"]), datetime.fromisoformat(view["adoption"]["at"]))
        self.assertEqual(again["takeSummary"], {"total": 4, "newSinceAdoption": 0})

    # ---------- A2: a pipeline proposal ----------

    def test_adopting_a_pipeline_take_applies_the_proposal_and_advances_the_flow(self):
        from project_assistant import flow_runner
        shot = self.prepare()[0]
        take = self.video("pipeline")
        proposal, run = self.pipeline_take(shot, take)
        self.assertIsNone(self.cell(shot, "video"))
        self.assertEqual(self.flow_state(run), {"shot": "awaiting_approval", "after": "blocked"})
        view = self.ok(f"/shots/{shot['shotId']}/adoptions", "POST", {"proposalId": proposal})
        self.assertEqual((view["selectedVideoUrl"], view["reviewStatus"], view["adoption"]["url"], view["adoption"]["by"]),
                         (take, "Approved", take, self.actor))
        self.assertEqual(self.proposal_status(proposal), "applied")
        self.assertEqual(self.flow_state(run), {"shot": "succeeded", "after": "queued"})
        self.assertEqual(flow_runner.claim(self.conn, self.worker)["task"]["node_id"], "after")
        self.conn.commit()
        self.assertEqual(self.meta(shot)["adoption"]["url"], take)
        # A decided proposal cannot be adopted again.
        code, payload = self.adopt(shot, {"proposalId": proposal})
        self.assertEqual((code, payload["code"]), (409, "DRAMA_OPERATION_NOT_ALLOWED"))

    def test_a_failure_after_either_step_leaves_no_half_adoption(self):
        shot = self.prepare()[0]
        a, b = self.video("a"), self.video("b")
        self.put(shot, "video", a)
        self.candidate(shot, b, story.now())
        refused = story.StoryError(409, "DRAMA_OPERATION_NOT_ALLOWED", "injected")
        with patch.object(story_trim, "reset", side_effect=refused):
            code, payload = self.adopt(shot, {"videoId": self.take_id(shot, b)})
        self.assertEqual((code, payload["code"], payload["message"]), (409, "DRAMA_OPERATION_NOT_ALLOWED", "injected"))
        self.assertEqual((self.cell(shot, "video"), self.status(shot)), (a, "Queued"))
        self.assertNotIn("adoption", self.meta(shot))

        take = self.video("pipeline")
        proposal, run = self.pipeline_take(shot, take)
        with patch.object(adoption, "_record", side_effect=refused):  # after the proposal and the status were written
            code, _ = self.adopt(shot, {"proposalId": proposal})
        self.assertEqual(code, 409)
        self.assertEqual((self.cell(shot, "video"), self.status(shot)), (a, "Queued"))
        self.assertEqual(self.proposal_status(proposal), "pending")
        self.assertEqual(self.flow_state(run), {"shot": "awaiting_approval", "after": "blocked"})
        self.assertNotIn("adoption", self.meta(shot))

        # The proposal's own write fails (the cell changed since it was rendered): apply_proposal would record a failed
        # proposal and fail the flow task; the adoption refuses and keeps the proposal pending for review instead.
        manual = self.video("manual")
        self.put(shot, "video", manual)
        code, payload = self.adopt(shot, {"proposalId": proposal})
        self.assertEqual((code, payload["code"]), (409, "DRAMA_OPERATION_NOT_ALLOWED"))
        self.assertEqual((self.cell(shot, "video"), self.status(shot)), (manual, "Queued"))
        self.assertEqual(self.proposal_status(proposal), "pending")
        self.assertEqual(self.flow_state(run), {"shot": "awaiting_approval", "after": "blocked"})

    # ---------- A3: a first frame ----------

    def test_choosing_a_first_frame_changes_only_the_keyframe(self):
        shot = self.prepare()[0]
        first, second = self.image("first"), self.image("second")
        self.put(shot, "image", first)
        self.put(shot, "image", second)
        # The video it may queue (§7 decision 1, test_a_first_frame_starts_the_shots_video...) never runs here.
        with patch.object(story._POOL, "submit"):
            view = self.ok(f"/shots/{shot['shotId']}/adoptions", "POST", {"imageId": self.take_id(shot, first, "image")})
        self.assertEqual((view["selectedImageUrl"], view["reviewStatus"], view["adoption"]), (first, "Queued", None))
        self.assertEqual(self.status(shot), "Queued")
        self.assertNotIn("adoption", self.meta(shot))
        # A first-frame pipeline proposal is applied the same way: through apply_proposal, without a status change.
        proposed = self.image("pipeline")
        proposal, run = self.pipeline_take(shot, proposed, "image")
        view = self.ok(f"/shots/{shot['shotId']}/adoptions", "POST", {"proposalId": proposal})
        self.assertEqual((view["selectedImageUrl"], view["reviewStatus"], view["adoption"]), (proposed, "Queued", None))
        self.assertEqual((self.proposal_status(proposal), self.flow_state(run)["shot"]), ("applied", "succeeded"))

    # ---------- refusals ----------

    def test_takes_from_another_row_unknown_takes_and_bad_bodies_are_refused(self):
        shot, other = self.prepare()[:2]
        mine, theirs = self.video("mine"), self.video("theirs")
        self.put(shot, "video", mine)
        self.put(other, "video", theirs)
        for body in ({"videoId": self.take_id(other, theirs)}, {"videoId": "vd_unknown"}, {"proposalId": 999999999},
                     {"imageId": "im_unknown"}):
            code, payload = self.adopt(shot, body)
            self.assertEqual((code, payload["code"]), (404, "DRAMA_NOT_FOUND"), body)
        proposal, _ = self.pipeline_take(other, self.video("other-pipeline"))
        code, payload = self.adopt(shot, {"proposalId": proposal})
        self.assertEqual((code, payload["code"]), (404, "DRAMA_NOT_FOUND"))
        self.assertEqual(self.proposal_status(proposal), "pending")
        for body in ({}, {"videoId": self.take_id(shot, mine), "imageId": "im_x"}, {"proposalId": "first"}, {"proposalId": True}):
            code, payload = self.adopt(shot, body)
            self.assertEqual((code, payload["code"]), (422, "DRAMA_VALIDATION_FAILED"), body)
        self.assertEqual(self.call(f"/shots/sh_{self.slug}_bmissing/adoptions", "POST", {"videoId": "vd_x"})[0], 404)
        asset_row = self.ok(f"/episodes/{self.ep}/assets")["items"][0]
        self.assertEqual(self.call(f"/assets/{asset_row['assetId']}/adoptions", "POST", {"videoId": "vd_x"})[0], 404)
        self.assertEqual((self.cell(shot, "video"), self.status(shot)), (mine, "Queued"))

    def test_read_only_crew_cannot_adopt_or_undo(self):
        shot = self.prepare()[0]
        take = self.video("a")
        self.put(shot, "video", take)
        video_id = self.take_id(shot, take)
        repo.upsert_member(self.conn, self.actor, "Viewer", "viewer"); self.conn.commit()
        for path, method, body in ((f"/shots/{shot['shotId']}/adoptions", "POST", {"videoId": video_id}),
                                   (f"/shots/{shot['shotId']}/adoption", "DELETE", None)):
            code, payload = self.call(path, method, body)
            self.assertEqual((code, payload["code"]), (409, "DRAMA_OPERATION_NOT_ALLOWED"))
        self.assertEqual(self.status(shot), "Queued")

    def test_a_sheet_without_a_status_column_cannot_record_an_adoption(self):
        shot = self.prepare()[0]
        take = self.video("a")
        self.put(shot, "video", take)
        video_id = self.take_id(shot, take)
        tab = repo.get_tab(self.conn, self.slug, "cinema-studio")
        doc = copy.deepcopy(tab["doc"])
        table = next(t for t in doc["content"] if t.get("type") == "table")
        index = adoption.status_index(self.row(shot))
        table["content"][0]["content"][index]["content"][0]["content"] = [{"type": "text", "text": "Review state"}]
        story.save_doc(self.conn, self.me, self.slug, "cinema-studio", doc)
        self.conn.commit()
        self.assertIsNone(adoption.status_index(self.row(shot)))
        for path, method, body in ((f"/shots/{shot['shotId']}/adoptions", "POST", {"videoId": video_id}),
                                   (f"/shots/{shot['shotId']}/adoption", "DELETE", None)):
            code, payload = self.call(path, method, body)
            self.assertEqual((code, payload["code"]), (409, "DRAMA_STAGE_PRECONDITION"))
        proposal, _ = self.pipeline_take(shot, self.video("pipeline"))
        self.assertEqual(self.adopt(shot, {"proposalId": proposal})[0], 409)
        self.assertEqual(self.proposal_status(proposal), "pending")  # refused before anything was applied
        self.assertNotIn("adoption", self.meta(shot))

    # ---------- undo ----------

    def test_undoing_an_adoption_clears_status_and_record_but_keeps_the_take(self):
        shot = self.prepare()[0]
        take = self.video("a")
        self.put(shot, "video", take)
        self.ok(f"/shots/{shot['shotId']}/adoptions", "POST", {"videoId": self.take_id(shot, take)})
        view = self.ok(f"/shots/{shot['shotId']}/adoption", "DELETE")
        self.assertEqual((view["selectedVideoUrl"], view["reviewStatus"], view["adoption"]), (take, "", None))
        self.assertNotIn("adoption", self.meta(shot))
        self.assertEqual(self.ok(f"/shots/{shot['shotId']}/adoption", "DELETE")["reviewStatus"], "")  # safe to repeat
        # A Retake after an adoption is not an adoption: undo drops the record and leaves the Retake alone.
        adopted = self.ok(f"/shots/{shot['shotId']}/adoptions", "POST", {"videoId": self.take_id(shot, take)})["adoption"]
        self.put(shot, "video", take, status="Retake")  # the R key writes Retake through the sheet: the record stays
        self.assertEqual(self.meta(shot)["adoption"], {k: adopted[k] for k in ("url", "at", "by")})
        self.assertEqual(self.ok("/shots/" + shot["shotId"])["adoption"], dict(adopted, adopted=False))
        view = self.ok(f"/shots/{shot['shotId']}/adoption", "DELETE")
        self.assertEqual((view["reviewStatus"], view["adoption"], view["selectedVideoUrl"]), ("Retake", None, take))

    def test_a_split_keeps_the_adoption_on_the_first_half_only(self):
        shot = self.prepare()[0]
        take = self.video("a")
        self.put(shot, "video", take)
        self.ok(f"/shots/{shot['shotId']}/adoptions", "POST", {"videoId": self.take_id(shot, take)})
        first, second = self.ok(f"/shots/{shot['shotId']}/splits", "POST", {})["shots"]
        self.assertEqual((first["adoption"]["url"], first["adoption"]["adopted"]), (take, True))
        self.assertNotIn("adoption", self.meta(second))
        self.assertIsNone(second["selectedVideoUrl"])

    # ---------- A14: old data ----------

    def test_legacy_approved_rows_read_as_adopted_without_new_takes(self):
        shot = self.prepare()[0]
        old, older = self.video("old"), self.video("older")
        self.candidate(shot, older)                       # written before candidates had createdAt
        self.put(shot, "video", old, status="Approved")   # approved through the sheet: no adoption record
        view = self.ok("/shots/" + shot["shotId"])
        self.assertEqual(view["adoption"], {"adopted": True, "url": old, "at": None, "by": None})
        self.assertEqual(view["takeSummary"], {"total": 2, "newSinceAdoption": 0})
        self.candidate(shot, self.video("fresh"), story.now())
        self.assertEqual(self.ok("/shots/" + shot["shotId"])["takeSummary"], {"total": 3, "newSinceAdoption": 1})
        never = self.ok(f"/episodes/{self.ep}/shots?limit=100")["items"]
        unshot = next(s for s in never if s["shotId"] != shot["shotId"] and s.get("sceneId"))
        self.assertEqual((unshot["adoption"], unshot["takeSummary"]), (None, {"total": 0, "newSinceAdoption": 0}))

    def test_template_rows_with_a_field_status_are_adopted_too(self):
        row = next(r for r in story.table_rows(self.conn, self.slug, "cinema-studio") if r["cells"][0] == "S01")
        shot = {"shotId": story.shot_id(self.slug, row)}
        take = self.video("template")
        self.put(shot, "video", take)
        view = self.ok(f"/shots/{shot['shotId']}/adoptions", "POST", {"videoId": self.take_id(shot, take)})
        self.assertEqual((view["reviewStatus"], view["adoption"]["url"]), ("Approved", take))
        self.assertEqual(self.ok(f"/shots/{shot['shotId']}/adoption", "DELETE")["reviewStatus"], "")

    # ---------- A13: consumers of Approved ----------

    def test_an_adopted_take_feeds_the_existing_approved_consumers(self):
        from project_docs import story_allocation
        shot, other = self.prepare()[:2]
        take, unadopted = self.video("hero"), self.video("draft")
        self.put(shot, "video", take)
        self.put(other, "video", unadopted)
        video_id = self.take_id(shot, take)
        self.conn.rollback()
        with self.assertRaises(story.StoryError):
            story_allocation.approved_source(self.conn, shot["shotId"], video_id)
        self.conn.rollback()
        self.ok(f"/shots/{shot['shotId']}/adoptions", "POST", {"videoId": video_id})
        self.conn.rollback()
        self.assertEqual(story_allocation.approved_source(self.conn, shot["shotId"], video_id), {"asset_url": take, "content_type": "video/mp4"})
        self.conn.rollback()
        with patch.object(story._POOL, "submit"):
            task = self.ok(f"/episodes/{self.ep}/films", "POST", {"selection": "adopted"})
        job = story.record(self.conn, task["taskId"])["_job"]
        segments = [{k: s[k] for k in ("shotId", "source")} for s in job["segments"]]  # SPEC_19 D10 adds more per segment
        self.assertEqual((job["urls"], segments), ([take], [{"shotId": shot["shotId"], "source": "adopted"}]))

    # ---------- §7 decision 1: a first frame starts the shot's video ----------

    def generations(self, shot):
        """The Story video generations queued for a shot: (task id, card id, first-frame URL in the frozen row). The earlier
        generations a test writes by hand (no frozen row) are not queued work."""
        self.conn.rollback()
        found = []
        for task in story.records(self.conn, "task", self.slug):
            job = task.get("_job") or {}
            if task["type"] == "SHOT_VIDEO_GENERATE" and job.get("entityId") == shot["shotId"] and "row" in job:
                row = job["row"]
                found.append((task["taskId"], job["card"]["card_id"], story.media_url(row["cells"][story.media_column(row, "image")])))
        return found

    def choose_frame(self, shot, url):
        with patch.object(story._POOL, "submit") as submit:
            view = self.ok(f"/shots/{shot['shotId']}/adoptions", "POST", {"imageId": self.take_id(shot, url, "image")})
        return view, submit.call_count

    def test_a_first_frame_starts_the_shots_video_on_a_local_open_weights_card(self):
        shot = self.prepare()[0]
        first, second = self.image("first"), self.image("second")
        self.put(shot, "image", first)
        self.put(shot, "image", second)
        project = self.ok(f"/projects/pj_{self.slug}")
        self.assertIs(project["autoVideoAfterFirstFrame"], True)  # on unless the production turns it off
        view, launched = self.choose_frame(shot, first)
        auto = view["autoVideo"]
        self.assertEqual({k: auto[k] for k in ("queued", "reason", "appCode", "message")},
                         {"queued": True, "reason": None, "appCode": "LTX25_CINEMA_SHOT", "message": None})
        self.assertEqual((auto["task"]["type"], auto["task"]["status"], launched), ("SHOT_VIDEO_GENERATE", "QUEUED", 1))
        # One video, on the production's default local card, rendered from the frame just chosen; the shot is not adopted.
        self.assertEqual(self.generations(shot), [(auto["task"]["taskId"], "ltx25-cinema", first)])
        self.assertEqual((view["selectedImageUrl"], view["reviewStatus"], view["adoption"]), (first, "Queued", None))
        # Choosing the frame the shot already has renders nothing new.
        again, launched = self.choose_frame(shot, first)
        self.assertEqual((again["autoVideo"]["queued"], again["autoVideo"]["reason"], launched), (False, "unchanged", 0))
        self.assertEqual(len(self.generations(shot)), 1)
        # Another frame renders again, now on the card the shot's last video used.
        view, launched = self.choose_frame(shot, second)
        self.assertEqual((view["autoVideo"]["queued"], launched), (True, 1))
        self.assertEqual(sorted(g[1:] for g in self.generations(shot)), sorted([("ltx25-cinema", first), ("ltx25-cinema", second)]))

    def test_the_production_switch_router_cards_and_video_adoptions_never_start_a_video(self):
        shot = self.prepare()[0]
        first, second = self.image("first"), self.image("second")
        self.put(shot, "image", first)
        self.put(shot, "image", second)
        # Off: the frame is chosen and nothing is queued.
        self.assertIs(self.ok(f"/projects/pj_{self.slug}", "PATCH", {"autoVideoAfterFirstFrame": False})["autoVideoAfterFirstFrame"], False)
        self.assertIs(self.ok(f"/projects/pj_{self.slug}")["autoVideoAfterFirstFrame"], False)
        view, launched = self.choose_frame(shot, first)
        self.assertEqual((view["selectedImageUrl"], view["autoVideo"]["queued"], view["autoVideo"]["reason"], launched), (first, False, "disabled", 0))
        self.assertEqual(self.generations(shot), [])
        for bad in ("yes", 1, None):
            code, payload = self.call(f"/projects/pj_{self.slug}", "PATCH", {"autoVideoAfterFirstFrame": bad})
            self.assertEqual((code, payload["code"]), (422, "DRAMA_VALIDATION_FAILED"), bad)
        self.assertIs(self.ok(f"/projects/pj_{self.slug}", "PATCH", {"autoVideoAfterFirstFrame": True})["autoVideoAfterFirstFrame"], True)
        # A shot whose video card is an official Router card: never sent by a chained action (fixed decision 8).
        story.store(self.conn, "tk_" + uuid.uuid4().hex, "task", {"taskId": "tk_router", "type": "SHOT_VIDEO_GENERATE", "status": "FAILED",
                    "createdAt": story.now(), "_job": {"entityId": shot["shotId"], "kind": "video", "card": {"card_id": "router-ltx-2-5-pro"},
                    "values": {}}}, self.slug, self.actor)
        self.conn.commit()
        view, launched = self.choose_frame(shot, second)
        self.assertEqual({k: view["autoVideo"][k] for k in ("queued", "reason", "appCode", "task")},
                         {"queued": False, "reason": "router_card", "appCode": "router-ltx-2-5-pro", "task": None})
        self.assertEqual((view["selectedImageUrl"], launched), (second, 0))
        # A closed (paid) card is not sent either.
        story.store(self.conn, "tk_" + uuid.uuid4().hex, "task", {"taskId": "tk_closed", "type": "SHOT_VIDEO_GENERATE", "status": "FAILED",
                    "createdAt": story.now(), "_job": {"entityId": shot["shotId"], "kind": "video", "card": {"card_id": "seedance-20-pro"},
                    "values": {}}}, self.slug, self.actor)
        self.conn.commit()
        view, launched = self.choose_frame(shot, first)
        self.assertEqual((view["autoVideo"]["reason"], view["autoVideo"]["appCode"], launched), ("closed_card", "SEEDANCE_2_FAST_MULTIMODAL_VIDEO", 0))
        self.assertEqual(self.generations(shot), [])
        # Adopting a video never starts one.
        take = self.video("take")
        self.put(shot, "video", take)
        with patch.object(story._POOL, "submit") as submit:
            adopted = self.ok(f"/shots/{shot['shotId']}/adoptions", "POST", {"videoId": self.take_id(shot, take)})
        self.assertEqual((adopted["reviewStatus"], "autoVideo" in adopted, submit.call_count), ("Approved", False, 0))
        self.assertEqual(self.generations(shot), [])

    def test_a_video_that_cannot_start_leaves_the_first_frame_chosen(self):
        shot = self.prepare()[0]
        first, second = self.image("first"), self.image("second")
        self.put(shot, "image", first)
        self.put(shot, "image", second)
        refused = story.StoryError(409, "DRAMA_STAGE_PRECONDITION", "Resolve required generation inputs before batch admission: x")
        with patch.object(story, "generation_job", side_effect=refused):
            view, launched = self.choose_frame(shot, first)
        self.assertEqual({k: view["autoVideo"][k] for k in ("queued", "reason", "message", "appCode")},
                         {"queued": False, "reason": "not_ready", "message": str(refused), "appCode": "LTX25_CINEMA_SHOT"})
        self.assertEqual((view["selectedImageUrl"], launched, self.cell(shot, "image")), (first, 0, first))
        self.assertEqual(self.generations(shot), [])
        # A video sent from the shot's own last generation keeps that card and its frame settings, never its prompt or media.
        story.store(self.conn, "tk_" + uuid.uuid4().hex, "task", {"taskId": "tk_last", "type": "SHOT_VIDEO_GENERATE", "status": "SUCCEEDED",
                    "createdAt": story.now(), "_job": {"entityId": shot["shotId"], "kind": "video", "card": {"card_id": "h3-reference"},
                    "values": {"252.aspect_ratio": "9:16 (Portrait Widescreen)", "263.text": "old words", "27.video": "/old.mp4"}}},
                    self.slug, self.actor)
        self.conn.commit()
        self.conn.rollback()
        _, row = story.find_row(self.conn, shot["shotId"], "shot")
        card, params = adoption.shot_video_request(self.conn, self.slug, shot["shotId"], row)
        self.assertEqual((card["card_id"], params), ("h3-reference", {"252.aspect_ratio": "9:16 (Portrait Widescreen)"}))


if __name__ == "__main__":
    unittest.main()
