"""SPEC_20 R18 (decision 5): crew proposals of a shot's stored 3D plan, action ``shot_meta``, pinned by the plan's revision.

The message tests need nothing; the rest run the real projects and story servers on PostgreSQL (OPENBENCH_TEST_DB_URI):
a proposal is made with ``shot_meta.propose`` (the crew tools come with R27), listed by shot, and decided through the
assistant's own proposal endpoints.
"""
import json
import os
import re
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

from project_assistant import service as assistant, shot_meta, store
from project_docs import locale, repository as repo, service as docs_service, story_previs
from test_story_previs import DEFAULT
import test_story_openapi as fixture

ROOT = Path(__file__).resolve().parents[1]


def dictionaries():
    root = ROOT / "ui" / "src" / "i18n" / "locales"
    return [json.loads((root / name).read_text(encoding="utf-8"))["errors"] for name in ("en.json", "zh-TW.json")]


def fill(template, params):
    return re.sub(r"\{\{(\w+)\}\}", lambda m: params[m[1]], template)


class ShotMetaMessageTests(unittest.TestCase):
    def test_refusals_name_the_shot_and_are_localized(self):
        field = shot_meta.FIELDS["previsPlan"]
        en, zh = dictionaries()
        shapes = [(field.conflict.format(label="S03", base=2, current=5), "shotProposalPlanChanged", {"v0": "S03", "v1": "2", "v2": "5"}),
                  (field.invalid.format(label="S 04", reason="plan.code names @CAST-03, which is not on the cast sheet."), "shotProposalPlanInvalid",
                   {"v0": "S 04", "v1": "plan.code names @CAST-03, which is not on the cast sheet."}),
                  (shot_meta.SHOT_DELETED.format(label="S05"), "shotProposalShotDeleted", {"v0": "S05"}),
                  (shot_meta.NOT_EDITABLE, "shotProposalNotEditable", {}),
                  (shot_meta.UNKNOWN_FIELD, "shotProposalUnknownField", {}),
                  (shot_meta.SHOT_NOT_FOUND, "shotNotFound", {})]
        for message, key, params in shapes:
            result = locale.error_details({"error": message})
            self.assertEqual((result["message_key"], result["message_params"]), ("errors." + key, params), message)
            self.assertEqual(fill(en[key], params), message)
        self.assertEqual(fill(zh["shotProposalPlanChanged"], shapes[0][2]),
                         "鏡頭 S03 的 3D 計畫在提案建立後已被修改（提案依據第 2 版，現在是第 5 版）；未套用任何變更，請重新產生提案。")
        self.assertEqual(fill(zh["shotProposalShotDeleted"], shapes[2][2]), "鏡頭 S05 在提案建立後已被刪除；未套用任何變更，請重新產生提案。")

    def test_look_refusals_name_the_shot_and_carry_message_keys(self):
        """SPEC_19 R11: the look field's sentences have their own patterns (the locale files add the keys at integration)."""
        field = shot_meta.FIELDS["look"]
        reason = "Unknown palette option 'teal'; choose an option from the look catalog."
        shapes = [(field.conflict.format(label="SC01-S02", base=3, current=4), "shotProposalLookChanged", {"v0": "SC01-S02", "v1": "3", "v2": "4"}),
                  (field.invalid.format(label="S 04", reason=reason), "shotProposalLookInvalid", {"v0": "S 04", "v1": reason})]
        for message, key, params in shapes:
            result = locale.error_details({"error": message})
            self.assertEqual((result["message_key"], result["message_params"]), ("errors." + key, params), message)
        self.assertEqual((field.name, field.conflict_code), ("look", "DRAMA_LOOK_REVISION_CONFLICT"))


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "set OPENBENCH_TEST_DB_URI for shot proposal tests")
class ShotMetaProposalTests(unittest.TestCase):
    setUp = fixture.StoryHTTPTests.setUp
    request = fixture.StoryHTTPTests.request
    call = fixture.StoryHTTPTests.call
    ok = fixture.StoryHTTPTests.ok
    prepare = fixture.StoryHTTPTests.prepare

    def tearDown(self):
        self.conn.rollback()
        with self.conn.cursor() as cur:
            for actor in getattr(self, "others", []):
                cur.execute("DELETE FROM projectops.member WHERE actor_id=%s", (actor,))
        self.conn.commit()
        fixture.StoryHTTPTests.tearDown(self)

    # ---- helpers ----
    def plan(self, shot):
        return self.ok(f"/shots/{shot['shotId']}/previs-plan")

    def save(self, shot, plan, revision):
        return self.ok(f"/shots/{shot['shotId']}/previs-plan", "PUT", {"plan": plan, "baseRevision": revision})

    def listed(self, shot, expect=200):
        code, payload, _ = self.request(f"/projects/api/{self.slug}/assistant/shots/{shot['shotId']}/proposals")
        self.assertEqual(code, expect, payload)
        return payload

    def decide(self, proposal, verb, body=None):
        code, payload, _ = self.request(f"/projects/api/{self.slug}/assistant/proposals/{proposal['id']}/{verb}", method="POST", data=body or {})
        return code, payload

    def propose(self, shot, plan, owner=None, **options):
        proposal = shot_meta.propose(self.conn, self.slug, owner or self.actor, shot["shotId"], plan, **options)
        self.conn.commit()
        return proposal

    def member(self, role="director"):
        actor = str(uuid.uuid4())
        repo.upsert_member(self.conn, actor, "Crew " + actor[:4], role)
        self.others = [*getattr(self, "others", []), actor]
        self.conn.commit()
        return actor

    # ---- the contract ----
    def test_create_then_approve_writes_the_plan_and_bumps_its_revision(self):
        shot = self.prepare()[0]
        self.save(shot, DEFAULT, 0)
        proposed = {**DEFAULT, "lens": 85, "move": "orbit", "seconds": 6, "code": "@CAST-01", "mark": [0.4, -0.6]}
        made = self.propose(shot, proposed, summary="  Orbit on an 85 so the dial reads.  ", agent_key="sheet_ops")
        self.assertEqual((made["action"], made["status"], made["content"], made["agent_key"]), ("shot_meta", "pending", "Orbit on an 85 so the dial reads.", "sheet_ops"))
        target = made["target"]
        self.assertEqual({k: target[k] for k in ("shotId", "field", "baseRevision", "value", "author", "display")},
                         {"shotId": shot["shotId"], "field": "previsPlan", "baseRevision": 1, "value": proposed,
                          "author": {"kind": "agent", "key": "sheet_ops"}, "display": shot["shotIndex"]})
        self.assertEqual(target["shot"], {"label": shot["shotIndex"], "tabKey": "cinema-studio", "rowId": shot["rowId"]})
        self.assertNotIn("tab_key", target, "pinned by the plan revision, never by the page")
        # The assistant's own list carries the proposal without its value; the shot's list carries the value.
        code, state, _ = self.request(f"/projects/api/{self.slug}/assistant")
        self.assertEqual(code, 200, state)
        card = next(p for p in state["proposals"] if p["id"] == made["id"])
        self.assertNotIn("value", card["target"])
        self.assertEqual(card["target"]["shot"]["rowId"], shot["rowId"])
        listed = self.listed(shot)
        self.assertEqual((listed["shotId"], listed["revisions"], listed["shot"]["label"]), (shot["shotId"], {"previsPlan": 1, "look": 0}, shot["shotIndex"]))
        [item] = listed["proposals"]
        self.assertEqual({k: item[k] for k in ("id", "action", "field", "baseRevision", "currentRevision", "value", "summary", "canDecide")},
                         {"id": made["id"], "action": "shot_meta", "field": "previsPlan", "baseRevision": 1, "currentRevision": 1,
                          "value": proposed, "summary": "Orbit on an 85 so the dial reads.", "canDecide": True})
        self.assertEqual((item["author"]["kind"], item["author"]["key"]), ("agent", "sheet_ops"))
        self.assertTrue(item["author"]["name"])
        # A shot proposal is applied as it was proposed.
        code, refused = self.decide(made, "apply", {"content": "Something else"})
        self.assertEqual((code, refused["error"]), (400, shot_meta.NOT_EDITABLE))
        self.assertEqual(store.proposal(self.conn, made["id"])["status"], "pending")
        code, applied = self.decide(made, "apply", {"content": made["content"]})
        self.assertEqual(code, 200, applied)
        self.assertEqual((applied["proposal"]["status"], applied["proposal"]["result"]),
                         ("applied", {"shotId": shot["shotId"], "field": "previsPlan", "revision": 2}))
        stored = self.plan(shot)
        self.assertEqual((stored["plan"], stored["planRevision"], stored["updatedBy"]), (proposed, 2, self.actor))
        self.assertEqual(self.ok("/shots/" + shot["shotId"])["previsPlanRevision"], 2)
        self.assertEqual(self.listed(shot)["proposals"], [])
        self.assertEqual(self.decide(made, "apply")[0], 409, "a decided proposal stays decided")

    def test_approving_after_the_stored_plan_moved_fails_with_the_named_message_and_stays_pending(self):
        first, second = self.prepare()[:2]
        made = self.propose(first, {**DEFAULT, "lens": 24})
        self.assertEqual(made["target"]["baseRevision"], 0)
        other = {**DEFAULT, "lens": 50, "move": "track"}
        self.save(first, other, 0)  # someone stores another plan while the proposal waits
        self.assertEqual(self.listed(first)["proposals"][0]["currentRevision"], 1, "the stage can tell the proposal is behind")
        code, refused = self.decide(made, "apply")
        self.assertEqual(code, 409, refused)
        message = f"The 3D plan of shot {first['shotIndex']} changed after this proposal was made (revision 0, now 1). Nothing was applied; generate a new proposal."
        self.assertEqual(refused["error"], message)
        self.assertEqual((refused["message_key"], refused["message_params"]), ("errors.shotProposalPlanChanged", {"v0": first["shotIndex"], "v1": "0", "v2": "1"}))
        self.assertEqual(refused["proposal"]["status"], "pending")
        self.assertEqual(store.proposal(self.conn, made["id"])["status"], "pending", "the proposal waits to be rejected or replaced")
        self.assertEqual((self.plan(first)["plan"], self.plan(first)["planRevision"]), (other, 1), "nothing was written")
        self.assertEqual([p["id"] for p in self.listed(first)["proposals"]], [made["id"]])
        # A plan that no longer fits the production (its cast code left the cast sheet) is refused the same way.
        fitted = self.propose(second, {**DEFAULT, "code": "@CAST-01"})
        cast = next(a for a in self.ok(f"/episodes/{self.ep}/assets")["items"] if a["assetCode"] == "CAST-01")
        self.ok("/assets/" + cast["assetId"], "DELETE")
        code, refused = self.decide(fitted, "apply")
        self.assertEqual((code, refused["message_key"]), (409, "errors.shotProposalPlanInvalid"), refused)
        self.assertIn("@CAST-01", refused["message_params"]["v1"])
        self.assertEqual((store.proposal(self.conn, fitted["id"])["status"], self.plan(second)["planRevision"]), ("pending", 0))
        # A deleted shot is named by the label it had.
        self.ok("/shots/" + second["shotId"], "DELETE")
        code, refused = self.decide(fitted, "apply")
        self.assertEqual((code, refused["error"]), (409, shot_meta.SHOT_DELETED.format(label=second["shotIndex"])))
        self.assertEqual(store.proposal(self.conn, fitted["id"])["status"], "pending")

    def test_reject_writes_nothing(self):
        shot = self.prepare()[0]
        made = self.propose(shot, {**DEFAULT, "lens": 85})
        code, dismissed = self.decide(made, "dismiss")
        self.assertEqual((code, dismissed["proposal"]["status"]), (200, "dismissed"), dismissed)
        self.assertEqual((self.plan(shot)["plan"], self.plan(shot)["planRevision"]), (None, 0))
        self.assertEqual(self.listed(shot)["proposals"], [])
        self.assertEqual(self.decide(made, "apply")[0], 409)

    def test_a_viewer_sees_the_proposal_read_only_and_cannot_decide(self):
        shot = self.prepare()[0]
        made = self.propose(shot, {**DEFAULT, "lens": 85})
        repo.upsert_member(self.conn, self.actor, "Viewer", "viewer")
        self.conn.commit()
        [item] = self.listed(shot)["proposals"]
        self.assertEqual((item["id"], item["canDecide"]), (made["id"], False))
        for verb in ("apply", "dismiss"):
            self.assertEqual(self.decide(made, verb)[0], 403, verb)
        viewer = docs_service.Identity(self.actor, "Viewer", "viewer")
        for decide in (lambda: assistant.apply_proposal(self.conn, viewer, self.slug, made["id"], {}),
                       lambda: assistant.dismiss_proposal(self.conn, viewer, self.slug, made["id"])):
            self.assertEqual(decide()[0], 403)
            self.conn.rollback()
        self.assertEqual(store.proposal(self.conn, made["id"])["status"], "pending")
        self.assertEqual(self.plan(shot)["planRevision"], 0)

    def test_list_by_shot_holds_my_pending_proposals_oldest_first(self):
        first, second = self.prepare()[:2]
        a = self.propose(first, {**DEFAULT, "lens": 24}, summary="Wide")
        b = self.propose(first, {**DEFAULT, "lens": 50}, author_id=self.actor)
        c = self.propose(second, {**DEFAULT, "lens": 85})
        someone = self.member()
        theirs = self.propose(first, {**DEFAULT, "move": "crane"}, owner=someone)
        done = self.propose(first, {**DEFAULT, "move": "static"})
        self.decide(done, "dismiss")
        listed = self.listed(first)["proposals"]
        self.assertEqual([p["id"] for p in listed], [a["id"], b["id"]], "my pending ones for this shot; not someone else's, not decided ones")
        self.assertEqual((listed[0]["summary"], listed[1]["author"]["kind"], listed[1]["author"]["id"]), ("Wide", "member", self.actor))
        self.assertEqual([p["id"] for p in self.listed(second)["proposals"]], [c["id"]])
        self.assertEqual([p["id"] for p in shot_meta.pending(self.conn, self.slug, first["shotId"])], [a["id"], b["id"], theirs["id"]],
                         "the service can list everyone's (for crew context later)")
        self.listed({"shotId": f"sh_{self.slug}_bmissing"}, expect=404)
        self.listed({"shotId": "sh_some-other-production_" + first["rowId"]}, expect=404)
        self.assertEqual(self.request(f"/projects/api/{self.slug}/assistant/shots/{first['shotId']}/proposals", authenticated=False)[0], 401)
        # The proposal for someone else is theirs to decide.
        self.assertEqual(self.decide(theirs, "apply")[0], 404)

    def test_an_invalid_plan_is_refused_when_the_proposal_is_made(self):
        shot = self.prepare()[0]
        cases = [({**DEFAULT, "lens": 40}, {}, 422, "plan.lens"),
                 ({**DEFAULT, "code": "@CAST-77"}, {}, 422, "not on the cast sheet"),
                 (None, {}, 422, "cannot clear the stored plan"),
                 ([DEFAULT], {}, 422, "must be a plan object"),
                 (DEFAULT, {"field": "dialogue"}, 400, "not 'dialogue'"),
                 (DEFAULT, {"field": "look"}, 422, "The proposed look for shot"),  # a plan is not a look
                 (DEFAULT, {"base_revision": 3}, 409, "is at revision 0, not 3"),
                 (DEFAULT, {"base_revision": True}, 400, "baseRevision"),
                 (DEFAULT, {"summary": "x" * 501}, 400, "summary"),
                 (DEFAULT, {"author_id": str(uuid.uuid4())}, 400, "not on the crew")]
        for plan, options, status, fragment in cases:
            with self.assertRaises(shot_meta.ProposalError) as caught:
                shot_meta.propose(self.conn, self.slug, self.actor, shot["shotId"], plan, **options)
            self.assertEqual(caught.exception.status, status, (plan, options))
            self.assertIn(fragment, str(caught.exception))
        for missing in (f"sh_{self.slug}_bmissing", "sh_other-production_" + shot["rowId"], None):
            with self.assertRaises(shot_meta.ProposalError) as caught:
                shot_meta.propose(self.conn, self.slug, self.actor, missing, DEFAULT)
            self.assertEqual(caught.exception.status, 404)
        self.conn.rollback()
        self.assertEqual(shot_meta.pending(self.conn, self.slug, shot["shotId"]), [])

    # ---- the look field (SPEC_19 R11) ----
    def test_a_look_proposal_is_written_by_the_look_writer_when_approved(self):
        shot = self.prepare()[0]
        self.ok(f"/shots/{shot['shotId']}/look", "PUT", {"palette": "midnight-slate", "light": "window-side"})  # lookRevision 1
        change = {"palette": "lamp-amber", "light": None, "tempo": "still-hold"}
        made = self.propose(shot, change, field="look", summary="Warm the console scene", agent_key="sheet_ops")
        self.assertEqual({k: made["target"][k] for k in ("shotId", "field", "baseRevision", "value")},
                         {"shotId": shot["shotId"], "field": "look", "baseRevision": 1, "value": change})
        listed = self.listed(shot)
        self.assertEqual(listed["revisions"], {"previsPlan": 0, "look": 1})
        [item] = listed["proposals"]
        self.assertEqual((item["field"], item["baseRevision"], item["currentRevision"], item["value"]), ("look", 1, 1, change))
        code, applied = self.decide(made, "apply", {"content": made["content"]})
        self.assertEqual(code, 200, applied)
        self.assertEqual(applied["proposal"]["result"], {"shotId": shot["shotId"], "field": "look", "revision": 2})
        view = self.ok("/shots/" + shot["shotId"])
        self.assertEqual((view["look"], view["lookRevision"]), ({"palette": "lamp-amber", "tempo": "still-hold"}, 2))
        self.assertEqual(self.listed(shot)["proposals"], [])

    def test_a_look_proposal_after_the_look_moved_conflicts_and_stays_pending(self):
        from unittest.mock import patch
        from project_docs import story_openapi as story
        first, second = self.prepare()[:2]
        made = self.propose(first, {"palette": "bone-ink"}, field="look")
        self.assertEqual(made["target"]["baseRevision"], 0)
        self.ok(f"/shots/{first['shotId']}/look", "PUT", {"light": "hard-top"})  # someone sets the light meanwhile
        code, refused = self.decide(made, "apply")
        self.assertEqual(code, 409, refused)
        self.assertEqual(refused["error"], f"The look of shot {first['shotIndex']} changed after this proposal was made (revision 0, now 1). "
                                           "Nothing was applied; generate a new proposal.")
        self.assertEqual((refused["message_key"], refused["message_params"]), ("errors.shotProposalLookChanged", {"v0": first["shotIndex"], "v1": "0", "v2": "1"}))
        self.assertEqual(store.proposal(self.conn, made["id"])["status"], "pending")
        view = self.ok("/shots/" + first["shotId"])
        self.assertEqual((view["look"], view["lookRevision"]), ({"light": "hard-top"}, 1), "nothing was written")
        # A look that no longer fits the catalog when it is approved (an option taken out since) gets the invalid sentence.
        fitted = self.propose(second, {"era": "tape-era"}, field="look")
        refusal = story.StoryError(400, "DRAMA_VALIDATION_FAILED", "Unknown era option 'tape-era'; choose an option from the look catalog.")
        with patch.object(story, "put_shot_look", side_effect=refusal):
            code, refused = self.decide(fitted, "apply")
        self.assertEqual((code, refused["message_key"]), (409, "errors.shotProposalLookInvalid"), refused)
        self.assertEqual(refused["message_params"]["v1"], "Unknown era option 'tape-era'; choose an option from the look catalog.")
        self.assertEqual(store.proposal(self.conn, fitted["id"])["status"], "pending")

    def test_an_invalid_look_is_refused_when_the_proposal_is_made(self):
        shot = self.prepare()[0]
        for value, fragment in (({"palette": "teal"}, "Unknown palette option 'teal'"), ({"camera": {"body": "film-35mm"}}, "Unknown look setting 'camera'"),
                                (None, "must be an object"), ({"light": 3}, "Unknown light option '3'")):
            with self.subTest(value=value), self.assertRaises(shot_meta.ProposalError) as caught:
                shot_meta.propose(self.conn, self.slug, self.actor, shot["shotId"], value, field="look")
            self.assertEqual(caught.exception.status, 422)
            self.assertIn(fragment, str(caught.exception))
        with self.assertRaises(shot_meta.ProposalError) as caught:
            shot_meta.propose(self.conn, self.slug, self.actor, shot["shotId"], {"palette": "auto"}, field="look", base_revision=2)
        self.assertEqual(caught.exception.status, 409)
        self.conn.rollback()
        self.assertEqual(shot_meta.pending(self.conn, self.slug, shot["shotId"]), [])

    def test_a_crew_tool_makes_the_proposal_in_its_conversation(self):
        shot = self.prepare()[0]
        _, reply = store.add_user_message(self.conn, self.slug, self.actor, "Block this shot", [], agent_key="sheet_ops")
        ctx = SimpleNamespace(slug=self.slug, me=self.me, message_id=reply)
        made = shot_meta.propose_from_tool(ctx, self.conn, shot["shotId"], {**DEFAULT, "move": "pullout"}, summary="Pull out")
        self.conn.commit()
        self.assertEqual((made["message_id"], made["agent_key"], made["target"]["author"], made["owner_id"]),
                         (reply, "sheet_ops", {"kind": "agent", "key": "sheet_ops"}, self.actor))
        self.assertEqual([p["id"] for p in self.listed(shot)["proposals"]], [made["id"]])


if __name__ == "__main__":
    unittest.main()
