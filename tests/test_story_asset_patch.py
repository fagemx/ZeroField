"""SPEC_18 pack B, PATCH /assets/{id} beyond name and prompt (B08): voice, status and notes, never a look's kind marker."""
import os
import unittest

from project_docs import repository as repo, story_asset_edit as edit, story_openapi as story
from project_docs.doc_schema import STATUSES
from story_pack_b_fixture import PackBFixture

VOICE, STATUS, NOTES = 4, 5, 6


class AssetEditPureTests(unittest.TestCase):
    def row(self, code, notes=""):
        return {"cells": [code, "Name", "Prompt", "", "Voice", "Queued", notes]}

    def test_only_the_fields_sent_produce_edits_and_name_prompt_are_left_alone(self):
        self.assertEqual(edit.extra_edits(self.row("CAST-01"), {"name": "N", "prompt": "P"}), {})
        self.assertEqual(edit.extra_edits(self.row("CAST-01"), {"voice": "Low", "status": "Approved", "notes": "n"}),
                         {VOICE: "Low", STATUS: "Approved", NOTES: "n"})
        self.assertEqual(edit.extra_edits(self.row("CAST-01"), {"notes": ""}), {NOTES: ""})  # a base asset's notes can be cleared

    def test_every_status_of_the_whitelist_is_accepted_and_nothing_else(self):
        for status in STATUSES:
            self.assertEqual(edit.extra_edits(self.row("CAST-01"), {"status": status}), {STATUS: status})
        for status in ("approved", "Done", "", " Approved", None, 5, ["Approved"], {"a": 1}):
            with self.assertRaises(story.StoryError) as caught:
                edit.extra_edits(self.row("CAST-01"), {"status": status})
            self.assertEqual((caught.exception.status, caught.exception.code), (400, "DRAMA_REQUEST_FAILED"), status)
        self.assertIn("Approved", str(caught.exception))

    def test_a_look_variant_never_loses_its_kind_marker(self):
        marked = self.row("CAST-01:NIGHT", "OUTFIT")
        self.assertEqual(story.look_kind(marked["cells"]), "OUTFIT")
        self.assertEqual(edit.extra_edits(marked, {"notes": ""}), {})  # the empty notes a look shows: a no-op, the cell is untouched
        self.assertEqual(edit.extra_edits(marked, {"voice": "Low", "status": "Approved", "notes": ""}), {VOICE: "Low", STATUS: "Approved"})
        for notes in ("remember the hat", "OUTFIT", "LOOK"):
            with self.assertRaises(story.StoryError) as caught:
                edit.extra_edits(marked, {"notes": notes})
            self.assertEqual(caught.exception.status, 400, notes)
        for code in ("CAST-01#night", "@cast-01:night"):  # the other spellings of a variant code
            with self.assertRaises(story.StoryError):
                edit.extra_edits(self.row(code, "POSE"), {"notes": "x"})

    def test_a_variant_without_a_kind_cannot_be_given_one_by_accident(self):
        bare = self.row("SET-01:NIGHT")
        self.assertIsNone(story.look_kind(bare["cells"]))
        self.assertEqual(edit.extra_edits(bare, {"notes": "dusk light"}), {NOTES: "dusk light"})  # free text on a look with no kind
        for word in story.LOOK_KINDS:  # these words would be read back as a kind
            with self.assertRaises(story.StoryError):
                edit.extra_edits(bare, {"notes": word})
        self.assertEqual(edit.extra_edits(self.row("CAST-01", "OUTFIT"), {"notes": "OUTFIT"}), {NOTES: "OUTFIT"})  # a base asset: plain text


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "set OPENBENCH_TEST_DB_URI for Story HTTP tests")
class AssetPatchHTTPTests(PackBFixture, unittest.TestCase):
    def cells(self, asset):
        return story.find_row(self.conn, asset["assetId"], "asset")[1]["cells"]

    def patch(self, asset, body):
        return self.call("/assets/" + asset["assetId"], "PATCH", body)

    def test_voice_status_and_notes_land_in_their_cells_and_come_back_in_the_view(self):
        self.prepare()
        asset = self.asset()
        self.assertEqual(self.cells(asset)[:3], [asset["assetCode"], asset["name"], asset["prompt"]])
        view = self.ok("/assets/" + asset["assetId"], "PATCH", {"voice": "Dry, low and slow", "status": "Approved", "notes": "Locked after review"})
        self.assertEqual(self.cells(asset)[VOICE:], ["Dry, low and slow", "Approved", "Locked after review"])
        self.assertEqual((view["voice"], view["status"], view["notes"]), ("Dry, low and slow", "Approved", "Locked after review"))
        self.assertEqual((view["name"], view["prompt"]), (asset["name"], asset["prompt"]))  # nothing else moved
        for field, value in (("voice", "Warm"), ("status", "Pending Review"), ("notes", "")):  # each alone, and clearing notes
            self.ok("/assets/" + asset["assetId"], "PATCH", {field: value})
        self.assertEqual(self.cells(asset)[VOICE:], ["Warm", "Pending Review", ""])
        self.assertEqual(self.ok("/assets/" + asset["assetId"], "PATCH", {"status": "已完成"})["status"], "已完成")  # a legacy status stays valid
        self.assertEqual(self.ok(f"/episodes/{self.ep}/assets")["items"][0]["voice"], "Warm")  # the list shows what the sheet holds

    def test_a_request_with_only_name_and_prompt_behaves_as_before(self):
        self.prepare()
        asset = self.asset()
        self.ok("/assets/" + asset["assetId"], "PATCH", {"voice": "Calm", "status": "Retake", "notes": "keep"})
        before = self.cells(asset)
        view = self.ok("/assets/" + asset["assetId"], "PATCH", {"name": "Director Mara", "prompt": "Cropped hair, blue coat"})
        self.assertEqual(self.cells(asset), [before[0], "Director Mara", "Cropped hair, blue coat", *before[3:]])
        self.assertEqual((view["name"], view["prompt"], view["voice"], view["status"], view["notes"]), ("Director Mara", "Cropped hair, blue coat", "Calm", "Retake", "keep"))
        self.ok("/assets/" + asset["assetId"], "PATCH", {})  # an empty body stays a no-op
        self.assertEqual(self.cells(asset), [before[0], "Director Mara", "Cropped hair, blue coat", *before[3:]])
        self.ok("/assets/" + asset["assetId"], "PATCH", {"name": "Director Mara", "unknown": "ignored"})
        for body in ({"name": 5}, {"prompt": "x" * 10001}, {"voice": 5}, {"notes": ["a"]}, {"voice": "x" * 10001}):
            self.assertEqual(self.patch(asset, body)[0], 422, body)  # the existing text validation, unchanged

    def test_a_status_outside_the_whitelist_is_a_400_and_changes_nothing(self):
        self.prepare()
        asset = self.asset()
        before = self.cells(asset)
        for status in ("Done", "approved", "", None, 7):
            code, payload = self.patch(asset, {"name": "Never saved", "voice": "Never saved", "status": status})
            self.assertEqual((code, payload["code"]), (400, "DRAMA_REQUEST_FAILED"), status)
            self.assertIn("Approved", payload["message"])  # the message names the statuses that are accepted
        self.assertEqual(self.cells(asset), before)  # the whole request was refused, not half applied
        self.assertEqual(self.request(story.BASE + "/assets/" + asset["assetId"], method="PATCH", data={"status": "Approved"}, authenticated=False)[0], 401)

    def test_a_look_variant_keeps_its_kind_whatever_the_patch_sends(self):
        self.prepare()
        base = self.asset()
        look = self.ok(f"/assets/{base['assetId']}/variants", "POST", {"name": "Night", "key": "night", "kind": "POSE", "prompt": "Night jacket"})
        self.assertEqual((look["assetCode"], look["kind"]), ("CAST-01:NIGHT", "POSE"))
        self.assertEqual(self.cells(look)[NOTES], "POSE")  # the kind lives in the notes cell
        view = self.ok("/assets/" + look["assetId"], "PATCH", {"name": "Night v2", "voice": "Hushed", "status": "Approved", "notes": ""})
        self.assertEqual((view["name"], view["voice"], view["status"], view["kind"], view["notes"]), ("Night v2", "Hushed", "Approved", "POSE", ""))
        self.assertEqual(self.cells(look)[NOTES], "POSE")
        for notes in ("remember the hat", "OUTFIT", "LOOK", "POSE"):
            code, payload = self.patch(look, {"notes": notes})
            self.assertEqual((code, payload["code"]), (400, "DRAMA_REQUEST_FAILED"), notes)
            self.assertEqual(self.cells(look)[NOTES], "POSE", notes)
        code, _ = self.patch(look, {"name": "Never saved", "notes": "x"})
        self.assertEqual((code, self.cells(look)[1]), (400, "Night v2"))  # the whole request is refused
        self.ok("/assets/" + look["assetId"], "PATCH", {"prompt": "Night jacket, collar up"})
        self.assertEqual(self.ok("/assets/" + look["assetId"])["kind"], "POSE")
        self.assertEqual([v["kind"] for v in self.ok("/assets/" + base["assetId"])["variants"]], ["POSE"])  # the base asset still lists it as a look
        self.assertEqual(self.ok(f"/assets/{base['assetId']}/variants", "POST", {"name": "Plain", "key": "plain"})["kind"], "OUTFIT")  # the variants API is unaffected
        # a variant without a kind (an extracted SET look) takes notes, but not the words that would turn them into one
        scene = self.asset("SET-01")
        bare = story.mutate_row(self.conn, self.me, self.slug, "soul-cast", cells={0: "SET-01:night", 1: "Observatory at night", 5: "Queued"})
        self.conn.commit()
        bare = {"assetId": f"as_{self.slug}_{bare}"}
        self.assertEqual(self.ok("/assets/" + bare["assetId"], "PATCH", {"notes": "dusk light"})["notes"], "dusk light")
        self.assertEqual(self.patch(bare, {"notes": "LOOK"})[0], 400)
        self.assertIsNone(self.ok("/assets/" + bare["assetId"])["kind"])
        self.assertEqual(self.ok("/assets/" + scene["assetId"], "PATCH", {"notes": "OUTFIT"})["notes"], "OUTFIT")  # a base asset: plain text

    def test_read_only_crew_cannot_patch_and_other_edits_are_unchanged(self):
        self.prepare()
        asset, shot = self.asset(), self.scene_shots()[0]
        self.ok("/shots/" + shot["shotId"], "PATCH", {"description": "A new instruction @CAST-01"})
        self.assertEqual(self.ok("/shots/" + shot["shotId"])["description"], "A new instruction @CAST-01")
        code, _ = self.call("/shots/" + shot["shotId"], "PATCH", {"status": "Approved", "voice": "x"})
        self.assertEqual(code, 200)  # a shot has no such fields: ignored as before
        self.assertEqual(self.ok("/shots/" + shot["shotId"])["reviewStatus"], "Queued")
        repo.upsert_member(self.conn, self.actor, "Viewer", "viewer")
        self.conn.commit()
        self.assertEqual(self.patch(asset, {"status": "Approved"})[0], 409)
        self.assertEqual(self.cells(asset)[STATUS], "Queued")


if __name__ == "__main__":
    unittest.main()
