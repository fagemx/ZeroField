"""Script -> shot alignment is read-only: pure rules first, then the real HTTP routes over PostgreSQL."""
import os
import unittest
from unittest.mock import patch

from project_docs import repository as repo, story_alignment as alignment, story_openapi as story
import test_story_openapi as fixture

SCRIPT = """## Scene 01: Observatory

@CAST-01 walks past @PROP-01.

@CAST-02: "We are out of time."

Close-up of @CAST-01 hand on the dial.

## Scene 02: Corridor

@CAST-02 runs down the corridor.

@CAST-01 follows with the dial.

## Scene 03: Departure

@CAST-01 leaves the station."""


def plan(text, mode="auto", slug="demo"):
    scenes = [{**item, "sceneId": f"sc_{slug}_01_S{i:02d}", "sceneIndex": i} for i, item in enumerate(story.scene_sections(text), 1)]
    return alignment.scene_plans(scenes, mode)


class AlignmentRuleTests(unittest.TestCase):
    def test_comparison_drops_asset_codes_whitespace_and_case(self):
        self.assertEqual(alignment.normal("@CAST-01   walks past @PROP-01:night.  @SET-01"), "walks past .")
        self.assertEqual(alignment.normal("CLOSE-UP of\n  the Dial"), "close-up of the dial")
        self.assertEqual(alignment.normal(None), "")
        self.assertTrue(alignment.matches("@CAST-01 walks past @PROP-01.", "@CAST-01 walks past @PROP-01. @SET-01 @CAST-02"))
        self.assertTrue(alignment.matches("@CAST-01 walks across\nthe room.", "@cast-02 WALKS across the room. @SET-01"))
        self.assertFalse(alignment.matches("@CAST-01 leaves.", "@CAST-01 arrives. @SET-01"))
        # a beat that is only references follows a prompt that is only references
        self.assertTrue(alignment.matches("@CAST-01", "@CAST-01 @SET-01"))
        self.assertFalse(alignment.matches("@CAST-01", "A hand-written prompt"))
        # build_shots cuts prompts at 10,000 characters, so a huge beat can only agree with the head it kept
        beat = "word " * 4000
        self.assertTrue(alignment.matches(beat, (beat + " @SET-01")[:alignment.PROMPT_LIMIT]))
        self.assertFalse(alignment.matches("short beat", "x" * alignment.PROMPT_LIMIT))

    def test_lines_follow_the_beats_through_blank_and_wrapped_lines(self):
        text = "Scene 01: A\n\n\n@CAST-01 walks across\nthe room.\n\nShot 2: Close-up of the dial.\n- @CAST-02: \"Wait.\"\n\nScene 02: B\nShe leaves."
        plans = plan(text)
        beats = [b for _, bs in plans for b in bs]
        self.assertEqual(beats, ["@CAST-01 walks across\nthe room.", "Close-up of the dial.", '@CAST-02: "Wait."', "She leaves."])
        self.assertEqual(alignment.locate(text, plans), [[4, 7, 8], [11]])
        # CRLF text numbers the same lines
        self.assertEqual(alignment.locate(text.replace("\n", "\r\n"), plans), [[4, 7, 8], [11]])

    def test_repeated_beats_take_successive_lines_and_unfound_beats_are_null(self):
        text = "Scene 01: A\nHe nods.\n\nHe nods.\n\nHe nods."
        self.assertEqual(alignment.locate(text, plan(text)), [[2, 4, 6]])
        # sentence beats share their paragraph's line; an empty scene's beat is its heading
        text = "Scene 01: Sentences\n@CAST-01 enters. @CAST-01 stops. @CAST-01 turns.\n\nScene 02: Empty"
        plans = plan(text, "cinematic")
        self.assertEqual([len(bs) for _, bs in plans], [3, 1])
        self.assertEqual(alignment.locate(text, plans), [[2, 2, 2], [4]])
        # text that does not contain the plan (a stale plan against other text) finds nothing, and never crashes
        self.assertEqual(alignment.locate("nothing here", plans), [[None, None, None], [None]])

    def test_coverage_beats_share_the_line_of_the_paragraph_they_multiply(self):
        text = "Scene 01: Single\n@CAST-01 enters the room."
        plans = plan(text, "cinematic_multi")
        self.assertEqual(len(plans[0][1]), 2)
        self.assertEqual(alignment.locate(text, plans), [[2, 2]])

    def test_affected_ignores_what_was_already_out_of_step(self):
        shots = [{"shotId": f"sh_{i}", "shotIndex": f"SC01-S0{i}", "rowId": f"b{i}", "sceneId": "sc_demo_01_S01", "tabKey": "cinema-studio",
                  "description": text} for i, text in enumerate(["@CAST-01 enters. @SET-01", "hand edited prompt", "@CAST-01 sits. @SET-01"], 1)]
        before = alignment.align(plan("Scene 01: A\n@CAST-01 enters.\n\n@CAST-01 speaks.\n\n@CAST-01 sits."), "", shots)
        self.assertEqual([b["state"] for b in before[0][0]["beats"]], ["linked", "changed", "linked"])
        same = alignment.align(plan("Scene 01: A\n@CAST-01 enters.\n\n@CAST-01 speaks.\n\n@CAST-01 sits."), "", shots)
        self.assertEqual(alignment.affected(before, same, shots), [])  # the hand edit predates the draft
        edited = alignment.align(plan("Scene 01: A\n@CAST-01 enters.\n\n@CAST-01 shouts.\n\n@CAST-01 sits."), "", shots)
        self.assertEqual(alignment.affected(before, edited, shots), ["sh_2"])
        dropped = alignment.align(plan("Scene 01: A\n@CAST-01 enters."), "", shots)
        self.assertEqual(alignment.affected(before, dropped, shots), ["sh_2", "sh_3"])
        self.assertEqual([o["shotId"] for o in dropped[1]], ["sh_2", "sh_3"])
        self.assertEqual(alignment.affected(dropped, dropped, shots), [])  # already orphans stay unaffected


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "set OPENBENCH_TEST_DB_URI for Story HTTP tests")
class ScriptAlignmentHTTPTests(unittest.TestCase):
    setUp = fixture.StoryHTTPTests.setUp
    tearDown = fixture.StoryHTTPTests.tearDown
    request = fixture.StoryHTTPTests.request
    call = fixture.StoryHTTPTests.call
    ok = fixture.StoryHTTPTests.ok

    def build(self, script=SCRIPT, **settings):
        if settings:
            self.ok(f"/episodes/{self.ep}/settings", "PUT", settings)
        self.ok(f"/episodes/{self.ep}/script", "PUT", {"scriptContent": script})
        self.ok(f"/episodes/{self.ep}/asset-extractions", "POST", {})
        self.ok(f"/episodes/{self.ep}/storyboards", "POST", {})
        return {s["shotId"]: s for s in self.ok(f"/episodes/{self.ep}/shots?limit=100")["items"] if s["tabKey"] == "cinema-studio" and s.get("sceneId")}

    def impact(self, draft):
        return self.ok(f"/episodes/{self.ep}/script-impact", "POST", {"scriptContent": draft})

    def states(self, result):
        return [[beat["state"] for beat in scene["beats"]] for scene in result["scenes"]]

    def test_untouched_build_links_every_beat_to_its_shot_in_sheet_order(self):
        shots = self.build()
        result = self.ok(f"/episodes/{self.ep}/script-alignment")
        self.assertEqual(set(result), {"scriptDirty", "scenes", "orphans"})
        self.assertFalse(result["scriptDirty"])
        self.assertEqual(result["orphans"], [])
        self.assertEqual([(s["sceneIndex"], s["title"], len(s["beats"])) for s in result["scenes"]],
                         [(1, "Scene 01: Observatory", 3), (2, "Scene 02: Corridor", 2), (3, "Scene 03: Departure", 1)])
        self.assertEqual(self.states(result), [["linked"] * 3, ["linked"] * 2, ["linked"]])
        beats = [b for scene in result["scenes"] for b in scene["beats"]]
        self.assertEqual([b["index"] for b in beats], [0, 1, 2, 0, 1, 0])
        self.assertEqual([b["shotIndex"] for b in beats], ["SC01-S01", "SC01-S02", "SC01-S03", "SC02-S01", "SC02-S02", "SC03-S01"])
        self.assertEqual({b["shotId"] for b in beats}, set(shots))
        for beat in beats:
            self.assertEqual(beat["rowId"], shots[beat["shotId"]]["rowId"])
            self.assertEqual(beat["state"], "linked")
        self.assertEqual(beats[1]["text"], '@CAST-02: "We are out of time."')
        # lines number the saved screenplay exactly as the editor shows it
        lines = self.ok(f"/episodes/{self.ep}")["scriptContent"].split("\n")
        self.assertEqual([b["line"] for b in beats], [2, 3, 4, 6, 7, 9])
        for beat in beats:
            self.assertIn(beat["text"].splitlines()[0], lines[beat["line"] - 1])

    def test_script_edits_after_confirmation_mark_the_script_dirty(self):
        self.build()
        self.ok(f"/episodes/{self.ep}/script", "PUT", {"scriptContent": SCRIPT + "\n\n@CAST-01 returns."})
        result = self.ok(f"/episodes/{self.ep}/script-alignment")
        self.assertTrue(result["scriptDirty"])
        self.assertEqual(self.states(result), [["linked"] * 3, ["linked"] * 2, ["linked", "no_shot"]])
        self.assertEqual(result["scenes"][2]["beats"][1]["shotId"], None)
        self.assertEqual(result["orphans"], [])

    def test_untouched_draft_changes_nothing_and_numbers_the_draft_lines(self):
        self.build()
        result = self.impact(SCRIPT)
        self.assertEqual((result["affectedShotIds"], result["orphans"]), ([], []))
        self.assertEqual(self.states(result), [["linked"] * 3, ["linked"] * 2, ["linked"]])
        lines = SCRIPT.split("\n")
        for beat in (b for scene in result["scenes"] for b in scene["beats"]):
            self.assertIn(beat["text"].splitlines()[0], lines[beat["line"] - 1])
        self.assertEqual([b["line"] for s in result["scenes"] for b in s["beats"]], [3, 5, 7, 11, 13, 17])
        # the dirty flag compares the draft with the confirmed text itself
        saved = self.ok(f"/episodes/{self.ep}")["scriptContent"]
        self.assertFalse(self.impact(saved)["scriptDirty"])
        self.assertTrue(self.impact(saved + "\n\n@CAST-01 returns.")["scriptDirty"])

    def test_edited_line_marks_only_its_shot_changed(self):
        shots = self.build()
        draft = SCRIPT.replace('@CAST-02: "We are out of time."', '@CAST-02: "There is still time."')
        result = self.impact(draft)
        self.assertEqual(self.states(result), [["linked", "changed", "linked"], ["linked"] * 2, ["linked"]])
        changed = result["scenes"][0]["beats"][1]
        self.assertEqual(result["affectedShotIds"], [changed["shotId"]])
        self.assertEqual(shots[changed["shotId"]]["shotIndex"], "SC01-S02")
        self.assertEqual(changed["text"], '@CAST-02: "There is still time."')
        self.assertEqual(result["orphans"], [])
        self.assertTrue(result["scriptDirty"])

    def test_asset_codes_case_and_spacing_do_not_count_as_edits(self):
        self.build()
        draft = SCRIPT.replace("@CAST-01 walks past @PROP-01.", "@CAST-02  walks   past   @PROP-03:night.").replace("Close-up of", "CLOSE-UP  of")
        result = self.impact(draft)
        self.assertEqual(self.states(result), [["linked"] * 3, ["linked"] * 2, ["linked"]])
        self.assertEqual(result["affectedShotIds"], [])

    def test_inserted_beat_shifts_the_shots_after_it(self):
        shots = self.build()
        draft = SCRIPT.replace('@CAST-02: "We are out of time."', '@CAST-02 slams the door.\n\n@CAST-02: "We are out of time."')
        result = self.impact(draft)
        first = result["scenes"][0]["beats"]
        self.assertEqual([b["state"] for b in first], ["linked", "changed", "changed", "no_shot"])
        self.assertEqual([b["shotIndex"] for b in first], ["SC01-S01", "SC01-S02", "SC01-S03", None])
        self.assertEqual(first[3]["shotId"], None)
        self.assertEqual(first[3]["rowId"], None)
        by_index = {s["shotIndex"]: s["shotId"] for s in shots.values()}
        self.assertEqual(result["affectedShotIds"], [by_index["SC01-S02"], by_index["SC01-S03"]])
        self.assertEqual(self.states(result)[1:], [["linked"] * 2, ["linked"]])
        self.assertEqual(result["orphans"], [])

    def test_deleted_scenes_leave_orphans(self):
        shots = self.build()
        by_index = {s["shotIndex"]: s for s in shots.values()}
        blocks = SCRIPT.split("\n\n## Scene ")
        last_gone = "\n\n## Scene ".join(blocks[:2])
        result = self.impact(last_gone)
        self.assertEqual(len(result["scenes"]), 2)
        self.assertEqual(result["orphans"], [{"shotId": by_index["SC03-S01"]["shotId"], "shotIndex": "SC03-S01",
                                              "rowId": by_index["SC03-S01"]["rowId"], "sceneId": by_index["SC03-S01"]["sceneId"]}])
        self.assertEqual(result["affectedShotIds"], [by_index["SC03-S01"]["shotId"]])
        # the saved script is untouched: it still aligns completely
        self.assertEqual(self.ok(f"/episodes/{self.ep}/script-alignment")["orphans"], [])
        # dropping the middle scene renumbers the last one onto scene 02's shots
        middle_gone = "\n\n## Scene ".join([blocks[0], blocks[2].replace("03: Departure", "02: Departure")])
        result = self.impact(middle_gone)
        self.assertEqual(self.states(result), [["linked"] * 3, ["changed"]])
        self.assertEqual([o["shotIndex"] for o in result["orphans"]], ["SC02-S02", "SC03-S01"])
        self.assertEqual(result["affectedShotIds"], [by_index[i]["shotId"] for i in ("SC02-S01", "SC02-S02", "SC03-S01")])
        everything = self.impact("")
        self.assertEqual((everything["scenes"], len(everything["orphans"])), ([], 6))
        self.assertEqual(len(everything["affectedShotIds"]), 6)

    def test_hand_edited_prompts_are_changed_but_not_blamed_on_the_draft(self):
        shots = self.build()
        target = next(s for s in shots.values() if s["shotIndex"] == "SC02-S01")
        self.ok("/shots/" + target["shotId"], "PATCH", {"description": "Director rewrote this prompt @CAST-02"})
        saved = self.ok(f"/episodes/{self.ep}/script-alignment")
        self.assertEqual(self.states(saved), [["linked"] * 3, ["changed", "linked"], ["linked"]])
        self.assertEqual(self.impact(SCRIPT)["affectedShotIds"], [])
        self.assertEqual(self.impact(SCRIPT.replace("runs down the corridor", "sprints down the corridor"))["affectedShotIds"], [target["shotId"]])

    def test_wrapped_and_blank_lines_keep_their_line_numbers(self):
        self.build()
        draft = ("## Scene 01: Observatory\n\n\n@CAST-01 walks past\n@PROP-01.\n\n@CAST-02: \"We are out of time.\"\n\n\n\n"
                 "Close-up of @CAST-01 hand\non the dial.\n\n## Scene 02: Corridor\n@CAST-02 runs down the corridor.\n\n"
                 "@CAST-01 follows with the dial.\n\n## Scene 03: Departure\n\n@CAST-01 leaves the station.")
        result = self.impact(draft)
        self.assertEqual(self.states(result), [["linked"] * 3, ["linked"] * 2, ["linked"]])
        self.assertEqual(result["affectedShotIds"], [])
        self.assertEqual([b["line"] for s in result["scenes"] for b in s["beats"]], [4, 7, 11, 15, 17, 21])
        self.assertEqual(result["scenes"][0]["beats"][0]["text"], "@CAST-01 walks past\n@PROP-01.")

    def test_cinematic_breakdown_pairs_sentence_beats_in_the_same_order_as_the_build(self):
        script = "## Scene 01: Station\n\n@CAST-01 enters. @CAST-01 stops. @CAST-01 turns.\n\n@CAST-02: \"Wait.\""
        self.build(script, breakdownMode="cinematic")
        saved = self.ok(f"/episodes/{self.ep}/script-alignment")
        self.assertEqual(self.states(saved), [["linked"] * 4])
        self.assertEqual([b["line"] for b in saved["scenes"][0]["beats"]], [2, 2, 2, 3])
        self.assertEqual([b["text"] for b in saved["scenes"][0]["beats"]][:2], ["@CAST-01 enters.", "@CAST-01 stops."])
        self.assertEqual(self.impact(script)["affectedShotIds"], [])

    def test_nothing_is_linked_before_the_storyboard_exists_and_an_empty_scene_is_its_own_beat(self):
        self.ok(f"/episodes/{self.ep}/script", "PUT", {"scriptContent": "## Scene 01: Station\n\n@CAST-01 enters.\n\n## Scene 02: Silence"})
        before = self.ok(f"/episodes/{self.ep}/script-alignment")
        self.assertEqual((self.states(before), before["orphans"]), ([["no_shot"], ["no_shot"]], []))
        self.assertTrue(before["scriptDirty"])
        self.assertEqual([b["shotId"] for s in before["scenes"] for b in s["beats"]], [None, None])
        self.ok(f"/episodes/{self.ep}/asset-extractions", "POST", {})
        self.ok(f"/episodes/{self.ep}/storyboards", "POST", {})
        after = self.ok(f"/episodes/{self.ep}/script-alignment")
        self.assertEqual(self.states(after), [["linked"], ["linked"]])
        silence = after["scenes"][1]["beats"][0]
        self.assertEqual((silence["text"], silence["line"]), ("Scene 02: Silence", 3))
        self.assertEqual(self.impact("## Scene 01: Station\n\n@CAST-01 enters.")["orphans"][0]["shotIndex"], "SC02-S01")

    def test_lab_clips_and_template_rows_are_not_part_of_the_slate(self):
        self.build()
        scene = self.ok(f"/episodes/{self.ep}/scenes")["items"][0]
        rid = story.mutate_row(self.conn, self.me, self.slug, "openjutsu-lab", cells={0: "VFX-01"})
        story.store(self.conn, f"meta_sh_{self.slug}_{rid}", "shot_meta", {"episodeId": self.ep, "sceneId": scene["sceneId"]}, self.slug)
        self.conn.commit()
        listed = self.ok(f"/episodes/{self.ep}/shots?limit=100")["items"]
        self.assertTrue(any(s["tabKey"] == "openjutsu-lab" and s.get("sceneId") == scene["sceneId"] for s in listed))
        result = self.ok(f"/episodes/{self.ep}/script-alignment")
        self.assertEqual((self.states(result), result["orphans"]), ([["linked"] * 3, ["linked"] * 2, ["linked"]], []))
        self.assertEqual(self.impact(SCRIPT)["affectedShotIds"], [])

    def test_shots_outside_the_script_are_neither_beats_nor_orphans(self):
        self.build()
        # a hand-added shot has a scene and rides along as a trailing orphan of its scene's beats
        scene = self.ok(f"/episodes/{self.ep}/scenes")["items"][2]
        added = self.ok("/scenes/" + scene["sceneId"] + "/shots", "POST", {"description": "Insert shot"})
        result = self.ok(f"/episodes/{self.ep}/script-alignment")
        self.assertEqual([o["shotId"] for o in result["orphans"]], [added["shotId"]])
        # template rows without a scene never appear
        template = [s for s in self.ok(f"/episodes/{self.ep}/shots?limit=100")["items"] if not s.get("sceneId")]
        self.assertFalse({o["shotId"] for o in result["orphans"]} & {s["shotId"] for s in template})

    def test_previews_never_write_or_call_a_model_and_stay_open_to_viewers(self):
        from project_assistant import providers
        self.build()
        before = (self.ok(f"/episodes/{self.ep}")["scriptContent"], len(story.records(self.conn, "task", owner=self.actor)),
                  len(story.records(self.conn, "shot_meta")))
        with patch.dict(os.environ, {"OPENBENCH_MODEL": "must-not-call", "OPENBENCH_API_BASE": "https://example.invalid"}), \
                patch.object(providers, "run_openai_compat_turn", side_effect=AssertionError("a preview must not call a model")):
            self.impact(SCRIPT.replace("leaves the station", "stays"))
            repo.upsert_member(self.conn, self.actor, "Viewer", "viewer"); self.conn.commit()
            self.assertEqual(self.ok(f"/episodes/{self.ep}/script-alignment")["orphans"], [])
            self.assertEqual(len(self.impact("")["affectedShotIds"]), 6)
        self.assertEqual(self.call(f"/episodes/{self.ep}/script", "PUT", {"scriptContent": "x"})[0], 409)
        repo.upsert_member(self.conn, self.actor, "Admin", "admin"); self.conn.commit()
        self.assertEqual(before, (self.ok(f"/episodes/{self.ep}")["scriptContent"], len(story.records(self.conn, "task", owner=self.actor)),
                                  len(story.records(self.conn, "shot_meta"))))

    def test_requests_are_authenticated_and_validated(self):
        self.build()
        path = f"/episodes/{self.ep}/script-impact"
        self.assertEqual(self.request(story.BASE + path, method="POST", data={"scriptContent": SCRIPT}, authenticated=False)[0], 401)
        self.assertEqual(self.request(story.BASE + path.replace("impact", "alignment"), authenticated=False)[0], 401)
        for body in ({}, {"scriptContent": None}, {"scriptContent": 7}, {"scriptContent": ["a"]}, {"scriptContent": "x" * 500001}):
            code, payload = self.call(path, "POST", body)
            self.assertEqual((code, payload["code"]), (422, "DRAMA_VALIDATION_FAILED"), body)
        self.assertEqual(self.call(f"/episodes/ep_{self.slug}_09/script-alignment")[0], 404)
        self.assertEqual(self.call(f"/episodes/ep_{self.slug}_09/script-impact", "POST", {"scriptContent": "x"})[0], 404)
        # the alignment is a read and the impact a preview: other verbs are not routes
        self.assertEqual(self.call(f"/episodes/{self.ep}/script-alignment", "POST", {})[0], 404)
        self.assertEqual(self.call(path)[0], 404)
