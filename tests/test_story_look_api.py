"""SPEC_19 package C on the Story API: the episode look in the episode settings, a shot's look override (PUT
/shots/{id}/look) with its revision, the look in the shot view, prompt previews, and the same Film, Color and Lighting
lines from the Story API and the M8 pipeline (SPEC_19 C2-C4).

Real HTTP and PostgreSQL (OPENBENCH_TEST_DB_URI), on the Story API fixture.
"""
import os
import unittest

from project_assistant import flow_runner, limb_worker as worker
from project_docs import repository as repo, story_look, story_openapi as story
import test_story_openapi as fixture

EPISODE_LOOK = {"genre": "rain-mystery", "era": "grain-film", "tempo": "slow-drift",
                "camera": {"body": "film-35mm", "lens": "anamorphic"}, "palette": "midnight-slate", "light": "window-side"}


def look_lines(prompt):
    return [line for line in prompt.splitlines() if line.startswith(("Film: ", "Color: ", "Lighting: "))]


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "set OPENBENCH_TEST_DB_URI for Story look tests")
class StoryLookHTTPTests(unittest.TestCase):
    setUp, tearDown = fixture.StoryHTTPTests.setUp, fixture.StoryHTTPTests.tearDown
    request, call, ok, prepare = fixture.StoryHTTPTests.request, fixture.StoryHTTPTests.call, fixture.StoryHTTPTests.ok, fixture.StoryHTTPTests.prepare
    generation_inputs, render_bytes = fixture.StoryHTTPTests.generation_inputs, fixture.StoryHTTPTests.render_bytes

    def refused(self, path, method, body, status=400):
        code, payload = self.call(path, method, body)
        self.assertEqual(code, status, payload)
        return payload

    def meta(self, shot):
        self.conn.rollback()
        return story.shot_meta(self.conn, shot["shotId"])

    # ---------- the episode look (R12) ----------

    def test_episode_settings_keep_the_look_until_a_put_replaces_or_clears_it(self):
        path = f"/episodes/{self.ep}/settings"
        saved = self.ok(path, "PUT", {"aspectRatio": "16:9", "stylePresetId": "88124",
                                      "look": dict(EPISODE_LOOK, light=None, camera=dict(EPISODE_LOOK["camera"], aperture=None))})
        self.assertEqual(saved, {"aspectRatio": "16:9", "stylePresetId": "88124", "look": {k: v for k, v in EPISODE_LOOK.items() if k != "light"}})
        self.assertEqual(self.ok(path), saved)
        self.assertEqual(self.ok("/episodes/" + self.ep)["settings"], saved)
        # StoryWorld's ratio and style dialog sends no look: the stored one stays.
        kept = self.ok(path, "PUT", {"aspectRatio": "21:9", "stylePresetId": "88123"})
        self.assertEqual(kept, {"aspectRatio": "21:9", "stylePresetId": "88123", "look": saved["look"]})
        # A look is replaced as a whole; {} clears it.
        self.assertEqual(self.ok(path, "PUT", {"aspectRatio": "21:9", "look": {"palette": "bone-ink"}})["look"], {"palette": "bone-ink"})
        cleared = self.ok(path, "PUT", {"aspectRatio": "21:9", "look": {}})
        self.assertEqual(cleared, {"aspectRatio": "21:9"})
        self.assertNotIn("look", self.ok(path))

    def test_an_unknown_look_setting_or_id_is_a_400_with_a_message_key_and_nothing_is_stored(self):
        path = f"/episodes/{self.ep}/settings"
        self.ok(path, "PUT", {"look": {"palette": "midnight-slate"}})
        cases = [({"palette": "teal"}, "errors.unknownLookOption", {"setting": "palette", "id": "teal"}),
                 ({"light": "lamp-amber"}, "errors.unknownLookOption", {"setting": "light", "id": "lamp-amber"}),
                 ({"camera": {"lens": "film-35mm"}}, "errors.unknownLookOption", {"setting": "camera lens", "id": "film-35mm"}),
                 ({"colour": "auto"}, "errors.unknownLookSetting", {"key": "colour", "keys": "genre, era, tempo, camera, palette, light"}),
                 ({"camera": {"iso": "800"}}, "errors.unknownLookSetting", {"key": "camera.iso", "keys": "body, lens, aperture"}),
                 ("noir", "errors.lookNotObject", {"setting": "look"})]
        for look, key, params in cases:
            with self.subTest(look=look):
                payload = self.refused(path, "PUT", {"aspectRatio": "9:16", "look": look})
                self.assertEqual((payload["code"], payload["message_key"], payload["message_params"]), ("DRAMA_VALIDATION_FAILED", key, params))
                self.assertEqual(self.ok(path), {"look": {"palette": "midnight-slate"}})

    # ---------- a shot's override (R11) ----------

    def test_a_shot_look_sets_and_clears_overrides_and_every_write_moves_the_revision(self):
        first, second = self.prepare()[:2]
        path = f"/shots/{first['shotId']}/look"
        view = self.ok("/shots/" + first["shotId"])
        self.assertEqual((view["look"], view["lookRevision"]), ({}, 0))
        listed = self.ok(f"/episodes/{self.ep}/shots?limit=100")["items"]
        self.assertTrue(listed and all(s["look"] == {} and s["lookRevision"] == 0 for s in listed))
        view = self.ok(path, "PUT", {"palette": "lamp-amber", "light": "practical-lamp"})
        self.assertEqual((view["shotId"], view["look"], view["lookRevision"]), (first["shotId"], {"palette": "lamp-amber", "light": "practical-lamp"}, 1))
        self.assertEqual(self.meta(first)["look"], {"palette": "lamp-amber", "light": "practical-lamp"})
        # A kind left out is kept, null removes one, and Auto is an override of its own.
        view = self.ok(path, "PUT", {"light": None, "tempo": "auto"})
        self.assertEqual((view["look"], view["lookRevision"]), ({"palette": "lamp-amber", "tempo": "auto"}, 2))
        view = self.ok(path, "PUT", {"palette": None, "tempo": None})
        self.assertEqual((view["look"], view["lookRevision"]), ({}, 3))
        self.assertNotIn("look", self.meta(first))
        self.assertEqual(self.meta(first)["lookRevision"], 3)
        self.assertEqual(self.ok(path, "PUT", {})["lookRevision"], 4)
        self.assertEqual(self.ok("/shots/" + second["shotId"])["lookRevision"], 0, "one shot's look is its own")
        # The look sits next to the other meta the view already carried, never instead of it.
        self.assertEqual(self.ok("/shots/" + first["shotId"])["episodeId"], self.ep)

    def test_a_stale_base_revision_is_a_409_that_names_the_shot_and_writes_nothing(self):
        shot = self.prepare()[0]
        path = f"/shots/{shot['shotId']}/look"
        self.assertEqual(self.ok(path, "PUT", {"palette": "bone-ink", "baseRevision": 0})["lookRevision"], 1)
        payload = self.refused(path, "PUT", {"palette": "sugar-paper", "baseRevision": 0}, 409)
        self.assertEqual(payload["code"], "DRAMA_LOOK_REVISION_CONFLICT")
        self.assertEqual(payload["message"], f"The look of shot {shot['shotIndex']} has changed since revision 0 (it is now revision 1). Reload it before saving.")
        self.assertEqual((payload["message_key"], payload["message_params"], payload["details"]),
                         ("errors.shotLookRevisionConflict", {"shot": shot["shotIndex"], "base": 0, "current": 1}, {"currentRevision": 1, "baseRevision": 0}))
        view = self.ok("/shots/" + shot["shotId"])
        self.assertEqual((view["look"], view["lookRevision"]), ({"palette": "bone-ink"}, 1))
        self.assertEqual(self.ok(path, "PUT", {"palette": "sugar-paper", "baseRevision": 1})["look"], {"palette": "sugar-paper"})
        for base in (True, -1, "2", 1.5):
            with self.subTest(base=base):
                self.assertEqual(self.refused(path, "PUT", {"palette": "auto", "baseRevision": base})["code"], "DRAMA_VALIDATION_FAILED")
        self.assertEqual(self.ok("/shots/" + shot["shotId"])["lookRevision"], 2)

    def test_unknown_overrides_are_a_400_and_read_only_crew_cannot_write(self):
        shot = self.prepare()[0]
        path = f"/shots/{shot['shotId']}/look"
        cases = [({"palette": "teal"}, "errors.unknownLookOption", {"setting": "palette", "id": "teal"}),
                 ({"camera": {"body": "film-35mm"}}, "errors.unknownLookSetting", {"key": "camera", "keys": "genre, era, tempo, palette, light"}),
                 ({"genre": ["rain-mystery"]}, "errors.unknownLookOption", {"setting": "genre", "id": '["rain-mystery"]'})]
        for body, key, params in cases:
            with self.subTest(body=body):
                payload = self.refused(path, "PUT", body)
                self.assertEqual((payload["code"], payload["message_key"], payload["message_params"]), ("DRAMA_VALIDATION_FAILED", key, params))
        self.assertEqual(self.ok("/shots/" + shot["shotId"])["lookRevision"], 0)
        self.assertEqual(self.call(f"/shots/sh_{self.slug}_bmissing/look", "PUT", {"palette": "auto"})[0], 404)
        repo.upsert_member(self.conn, self.actor, "Viewer", "viewer")
        self.conn.commit()
        payload = self.refused(path, "PUT", {"palette": "auto"}, 409)
        self.assertEqual(payload["code"], "DRAMA_OPERATION_NOT_ALLOWED")
        self.assertEqual(self.ok("/shots/" + shot["shotId"])["lookRevision"], 0)

    # ---------- what generation sends (C3) ----------

    def test_a_prompt_preview_shows_the_film_color_and_light_it_compiles(self):
        shot = self.prepare()[0]
        self.generation_inputs(shot["shotId"])
        body = {"appCode": "LTX25_CINEMA_SHOT"}
        preview = self.ok(f"/shots/{shot['shotId']}/prompt-previews", "POST", body)
        self.assertEqual({k: preview["look"][k] for k in ("film", "color", "light")}, {"film": "", "color": "", "light": ""})
        self.assertEqual(look_lines(preview["compiledPrompt"]), [])
        self.ok(f"/episodes/{self.ep}/settings", "PUT", {"look": EPISODE_LOOK})
        self.ok(f"/shots/{shot['shotId']}/look", "PUT", {"light": "low-sun", "tempo": "auto"})
        expected = story_look.compile_look(EPISODE_LOOK, {"light": "low-sun", "tempo": "auto"})
        preview = self.ok(f"/shots/{shot['shotId']}/prompt-previews", "POST", body)
        self.assertEqual(sorted(preview["look"]), ["cameraMovement", "color", "film", "light", "moves", "opticalRig"])
        self.assertEqual({k: preview["look"][k] for k in ("film", "color", "light")},
                         {"film": expected["film"], "color": expected["color"], "light": expected["light"]})
        self.assertNotIn(story_look.option("tempo", "slow-drift")["promptText"], preview["look"]["film"], "the shot's Auto tempo wins")
        self.assertEqual(look_lines(preview["compiledPrompt"]),
                         [f"Film: {expected['film']}.", f"Color: {expected['color']}.", f"Lighting: {expected['light']}."])
        self.assertEqual(preview["look"]["opticalRig"], self.ok("/shots/" + shot["shotId"])["opticalRig"], "the shot's own Optical Rig cell wins")
        # An empty Optical Rig cell takes the episode camera.
        self.ok("/shots/" + shot["shotId"], "PATCH", {"opticalRig": ""})
        preview = self.ok(f"/shots/{shot['shotId']}/prompt-previews", "POST", body)
        camera = story_look.camera_text("film-35mm", "anamorphic")
        self.assertEqual(preview["look"]["opticalRig"], camera)
        self.assertIn(f"Optical Rig: {camera}\n", preview["compiledPrompt"])

    def test_the_story_api_and_the_m8_pipeline_write_the_same_look_lines(self):
        """SPEC_19 C3: both paths take the look from story_openapi.source_look, so the compiler writes the same text."""
        shot = self.prepare()[0]
        self.generation_inputs(shot["shotId"])
        self.ok(f"/episodes/{self.ep}/settings", "PUT", {"look": EPISODE_LOOK})
        self.ok(f"/shots/{shot['shotId']}/look", "PUT", {"palette": "wet-glass-neon"})
        preview = self.ok(f"/shots/{shot['shotId']}/prompt-previews", "POST", {"appCode": "LTX25_CINEMA_SHOT"})
        # The pipeline: a per-row step over the shot sheet run on this shot, claimed as the Studio worker claims one.
        self.conn.rollback()
        _, row = story.find_row(self.conn, shot["shotId"], "shot")
        nodes = [{"id": "shot", "capability": "llm", "scope": "rows", "row_source": {"tab_key": row["tabKey"]}, "input_tabs": ["soul-cast"],
                  "target": {"tab_key": row["tabKey"], "col_index": story.media_column(row, "video")}}]
        current = flow_runner.definition(self.conn, self.slug, "flow")["revision"]
        flow_runner.save_definition(self.conn, self.me, self.slug, "flow", {"revision": current, "definition": {"nodes": nodes, "edges": []}})
        flow_runner.start(self.conn, self.me, self.slug, "flow", {"row_ids": [row["rid"]]})
        task = flow_runner.claim(self.conn, self.worker)["task"]
        self.conn.commit()
        self.assertEqual((task["node_id"], task["row_id"]), ("shot", row["rid"]))
        self.assertEqual(task["input"]["look"], story_look.source_look(EPISODE_LOOK, {"palette": "wet-glass-neon"}))
        story_source = story.snapshot(self.conn, self.slug, row)
        self.assertEqual(task["input"]["look"], story_source["look"])
        pipeline = worker.resolve_studio_context({"input": task["input"], "row_id": row["rid"], "capability": "video_gen"})
        self.assertEqual(look_lines(pipeline["compiled_prompt"]), look_lines(preview["compiledPrompt"]))
        self.assertEqual(len(look_lines(preview["compiledPrompt"])), 3)
        # A still from either path: the same lines, the Film line without tempo.
        stills = [look_lines(worker.resolve_studio_context({"input": source, "row_id": row["rid"], "capability": "image_gen"})["compiled_prompt"])
                  for source in (story_source, task["input"])]
        self.assertEqual(stills[0], stills[1])
        self.assertEqual(stills[0][0], "Film: " + story_look.compile_look(EPISODE_LOOK, {}, still=True)["film"] + ".")

    def test_a_shot_without_a_look_keeps_its_old_generation_source(self):
        """A digest of the source guards Router quotes and batches; a shot with no look must keep the one it had."""
        shot = self.prepare()[0]
        self.conn.rollback()
        _, row = story.find_row(self.conn, shot["shotId"], "shot")
        before = story.snapshot(self.conn, self.slug, row)
        self.assertNotIn("look", before)
        self.ok(f"/episodes/{self.ep}/settings", "PUT", {"look": {"genre": "auto", "camera": {"body": "auto-body"}}})
        self.conn.rollback()
        self.assertEqual(story.snapshot(self.conn, self.slug, row), before, "a look of Auto choices adds nothing")
        self.ok(f"/shots/{shot['shotId']}/look", "PUT", {"light": "hard-top"})
        self.conn.rollback()
        after = story.snapshot(self.conn, self.slug, row)
        self.assertEqual({k: v for k, v in after.items() if k != "look"}, before)
        self.assertEqual(after["look"]["light"], story_look.option("light", "hard-top")["promptText"])
        self.assertNotEqual(story.digest(after), story.digest(before), "a look change is a source change for quotes")
        # An asset's source never carries a look.
        cast = next(r for r in story.table_rows(self.conn, self.slug, "soul-cast"))
        self.assertNotIn("look", story.snapshot(self.conn, self.slug, cast))


if __name__ == "__main__":
    unittest.main()
