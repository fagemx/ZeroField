"""SPEC_18 pack B, storyboard estimates (B09): the numbers shown before a build are the numbers the build produces.

Real HTTP and PostgreSQL; the estimate is pure computation, so no model or provider is involved.
"""
import os
import time
import unittest
from unittest.mock import patch

from project_assistant import limb_worker as worker, providers
from project_docs import repository as repo, story_estimates as planner, story_openapi as story
from project_docs.story_adaptation import infer_shot_grammar
from story_pack_b_fixture import PackBFixture

MODES = ("auto", "scene", "cinematic", "cinematic_multi")
SCRIPT = ('## Scene 01: Observatory\n@CAST-01 enters the observatory. @CAST-01 stops at the console.\n\n'
          '@CAST-01: "The signal is back."\n\nClose-up of @CAST-01 eyes.\n\n'
          '## Scene 02: Departure\n@CAST-01 leaves. The dome closes behind @CAST-01.\n\n'
          '## Scene 03: Silence\n@CAST-01 waits.\n')
# Plain headings, soft-wrapped lines, bullets, "Shot n:" cues and a dialogue line: everything saving converts first.
DRAFT = ('Scene 01: Observatory\n@CAST-01 enters the observatory\nand stops at the console.\n\n'
         '@CAST-01: "The signal is back."\n- Close-up of @CAST-01 eyes.\n- @CAST-01 turns to the dome.\n\n'
         'Scene 02: Departure\nShot 1: @CAST-01 leaves.\nShot 2: The dome closes.\n\n'
         'Scene 03: Silence\n@CAST-01 waits.\n\n'
         'Scene 04: Return\n@CAST-01 returns. @CAST-01 smiles.\n')
EMPTY = {"shotCount": 0, "newShots": 0, "keptShots": 0, "plannedSeconds": 0}


class PlannerPureTests(unittest.TestCase):
    scene = {"sceneId": "sc_x_01_S01", "title": "Scene 01: Roof", "content": "@CAST-01 runs.\n\n@CAST-01 jumps."}

    def shot(self, name, scene="sc_x_01_S01", tab="cinema-studio"):
        return {"shotId": name, "sceneId": scene, "tabKey": tab}

    def test_existing_slate_shots_answer_the_first_beats_and_later_beats_add(self):
        slate = [self.shot("a"), self.shot("b"), self.shot("elsewhere", "sc_x_01_S02"), self.shot("lab", tab="openjutsu-lab")]
        steps, surplus = planner.scene_steps(self.scene, ["x", "y", "z"], slate)
        self.assertEqual([(a, i, b, s and s["shotId"]) for a, i, b, s in steps], [("keep", 0, "x", "a"), ("keep", 1, "y", "b"), ("add", 2, "z", None)])
        self.assertEqual(surplus, [])
        steps, surplus = planner.scene_steps(self.scene, ["x"], slate)  # a build never deletes the shot a shorter scene leaves over
        self.assertEqual([(a, s and s["shotId"]) for a, _, _, s in steps], [("keep", "a")])
        self.assertEqual([s["shotId"] for s in surplus], ["b"])
        steps, _ = planner.scene_steps(self.scene, ["x", "y", "z"], slate, rebuild=True)  # a one-scene rebuild rewrites them
        self.assertEqual([a for a, *_ in steps], ["rewrite", "rewrite", "add"])
        self.assertEqual([a for a, *_ in planner.scene_steps(self.scene, ["x"], [])[0]], ["add"])

    def test_beats_come_from_the_shared_cutter_and_only_scene_narrows_them(self):
        second = {"sceneId": "sc_x_01_S02", "title": "Scene 02: Bare", "content": ""}
        plans = planner.beat_plans([self.scene, second], "auto")
        self.assertEqual([(s["sceneId"], beats) for s, beats in plans], [("sc_x_01_S01", ["@CAST-01 runs.", "@CAST-01 jumps."]), ("sc_x_01_S02", ["Scene 02: Bare"])])
        self.assertEqual([len(beats) for _, beats in planner.beat_plans([self.scene, second], "scene")], [1, 1])
        self.assertEqual([s["sceneId"] for s, _ in planner.beat_plans([self.scene, second], "auto", "sc_x_01_S02")], ["sc_x_01_S02"])
        with self.assertRaises(ValueError):
            planner.beat_plans([self.scene], "bogus")

    def test_planned_seconds_come_from_the_shot_grammar(self):
        grammar = infer_shot_grammar("@CAST-01 runs.", 0, 2)["previsPlan"]["seconds"]
        self.assertEqual(planner.default_shot_seconds(), grammar)
        self.assertEqual(planner.planned_seconds({"seconds": 6}), 6)
        self.assertEqual(planner.planned_seconds({"seconds": 4.5}), 4.5)
        for plan in (None, {}, {"seconds": 0}, {"seconds": -2}, {"seconds": True}, {"seconds": "4"}, {"seconds": float("nan")}, "x"):
            self.assertEqual(planner.planned_seconds(plan), grammar, plan)
        self.assertEqual([planner.whole(n) for n in (12, 12.0, 4.5, 4.504, 0)], [12, 12, 4.5, 4.5, 0])


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "set OPENBENCH_TEST_DB_URI for Story HTTP tests")
class StoryboardEstimateHTTPTests(PackBFixture, unittest.TestCase):
    path = property(lambda self: f"/episodes/{self.ep}/storyboard-estimates")

    def estimate(self, **body):
        return self.ok(self.path, "POST", body)

    def plans(self):
        """{shotId: planned seconds} of the shots that belong to a scene, as the storyboard shows them."""
        default = infer_shot_grammar("x", 0, 1)["previsPlan"]["seconds"]  # a shot without a plan counts what the grammar plans
        return {s["shotId"]: (s.get("previsPlan") or {}).get("seconds", default) for s in self.scene_shots()}

    def confirm(self, script):
        self.ok(f"/episodes/{self.ep}/script", "PUT", {"scriptContent": script})
        self.ok(f"/episodes/{self.ep}/asset-extractions", "POST", {})

    def check(self, mode, **draft):
        """The estimate of one mode, then the real build of it: same shots, same planned seconds."""
        before = self.plans()
        expected = self.estimate(breakdownModes=[mode], **draft)["modes"][0]
        built = self.ok(f"/episodes/{self.ep}/storyboards", "POST", {"breakdownMode": mode})["result"]["shotsCount"]
        after = self.plans()
        self.assertEqual(expected["breakdownMode"], mode)
        self.assertEqual(expected["shotCount"], built, expected)  # what the build reports
        self.assertEqual(expected["shotCount"], len(after), expected)  # what it left on the slate
        self.assertEqual(expected["keptShots"], len(before), expected)
        self.assertEqual(expected["newShots"], len(set(after) - set(before)), expected)
        self.assertTrue(set(before) <= set(after))
        self.assertEqual(expected["plannedSeconds"], sum(after.values()), expected)
        return expected

    def test_estimate_equals_what_the_build_creates_for_every_mode(self):
        self.confirm(SCRIPT)
        everything = self.estimate(breakdownModes=list(MODES))
        self.assertEqual(everything["targetSeconds"], None)
        self.assertEqual({m["breakdownMode"]: (m["shotCount"], m["newShots"], m["keptShots"]) for m in everything["modes"]},
                         {"scene": (3, 3, 0), "auto": (5, 5, 0), "cinematic": (7, 7, 0), "cinematic_multi": (8, 8, 0)})
        seconds = infer_shot_grammar("x", 0, 1)["previsPlan"]["seconds"]  # what the shot grammar plans for a new shot
        self.assertEqual({m["breakdownMode"]: m["plannedSeconds"] for m in everything["modes"]},
                         {mode: seconds * count for mode, count in (("scene", 3), ("auto", 5), ("cinematic", 7), ("cinematic_multi", 8))})
        for entry in everything["modes"]:  # asking for several modes at once answers each exactly as asking alone
            self.assertEqual(entry, self.estimate(breakdownModes=[entry["breakdownMode"]])["modes"][0])
        self.assertEqual([m["breakdownMode"] for m in self.estimate()["modes"]], ["auto", "scene", "cinematic"])  # the default list
        # the slate grows, stays when a coarser mode follows, and the numbers keep matching the build
        results = [self.check(mode) for mode in ("scene", "auto", "cinematic", "cinematic_multi", "scene", "auto")]
        self.assertEqual([(r["keptShots"], r["newShots"]) for r in results], [(0, 3), (3, 2), (5, 2), (7, 1), (8, 0), (8, 0)])

    def test_kept_shots_count_their_own_planned_seconds_and_a_shot_without_a_plan_counts_the_default(self):
        shots = self.prepare(SCRIPT)  # built with the episode's default mode
        meta = story.shot_meta(self.conn, shots[0]["shotId"])
        story.store(self.conn, "meta_" + shots[0]["shotId"], "shot_meta", meta | {"previsPlan": {**meta["previsPlan"], "seconds": 6.5}}, self.slug)
        self.conn.commit()
        hand = self.ok("/scenes/" + self.ok(f"/episodes/{self.ep}/scenes")["items"][2]["sceneId"] + "/shots", "POST", {"description": "A hand-made insert."})
        self.assertNotIn("previsPlan", hand)
        grammar = infer_shot_grammar("x", 0, 1)["previsPlan"]["seconds"]
        auto = self.estimate(breakdownModes=["auto", "cinematic"])["modes"][0]
        self.assertEqual((auto["keptShots"], auto["newShots"], auto["shotCount"]), (6, 0, 6))
        self.assertEqual(auto["plannedSeconds"], 6.5 + 4 * grammar + grammar)  # five planned shots, one edited, plus the hand-made one
        self.assertEqual(auto["plannedSeconds"], sum(self.plans().values()))
        self.check("auto")
        self.check("cinematic")

    def test_a_draft_is_estimated_as_saving_it_would_store_it(self):
        self.prepare(SCRIPT)
        saved = self.ok(f"/episodes/{self.ep}")["scriptContent"]
        drafted = self.estimate(breakdownModes=list(MODES), scriptContent=DRAFT)
        self.assertEqual(self.ok(f"/episodes/{self.ep}")["scriptContent"], saved)  # a draft is never saved by asking
        self.assertNotEqual(drafted, self.estimate(breakdownModes=list(MODES)))  # and it is not the saved script that was counted
        self.confirm(DRAFT)
        self.assertEqual(self.estimate(breakdownModes=list(MODES)), drafted)  # the saved draft answers the same numbers
        self.assertEqual(self.estimate(breakdownModes=list(MODES), scriptContent=DRAFT), drafted)
        for mode in MODES:
            self.check(mode)
        self.assertEqual(self.estimate(breakdownModes=["auto"], scriptContent="   \n")["modes"], [{"breakdownMode": "auto", **EMPTY}])  # nothing to shoot

    def test_estimates_follow_a_script_with_more_beats_than_shots(self):
        self.prepare(SCRIPT)  # auto: five shots on the slate
        self.assertEqual(self.estimate(breakdownModes=["scene"])["modes"][0]["newShots"], 0)  # every scene already has a shot
        self.assertEqual(self.estimate(breakdownModes=["scene"])["modes"][0]["keptShots"], 5)  # the extra ones stay
        self.check("scene")
        scene = self.ok(f"/episodes/{self.ep}/scenes")["items"][0]
        self.ok("/scenes/" + scene["sceneId"], "PATCH", {"content": '@CAST-01 enters.\n\n@CAST-01: "Wait."\n\nClose-up of @CAST-01 eyes.\n\nWide shot of the dome.\n\nThe light goes out.'})
        self.ok(f"/episodes/{self.ep}/asset-extractions", "POST", {})
        result = self.check("auto")
        self.assertEqual((result["keptShots"], result["newShots"]), (5, 2))

    def test_a_mode_the_build_would_refuse_is_flagged_and_the_others_are_not(self):
        self.confirm("## Scene 01: Many\n" + "\n\n".join(f"@CAST-01 does action {i}." for i in range(201)))
        auto, scene = self.estimate(breakdownModes=["auto", "scene"])["modes"]
        self.assertEqual((auto["shotCount"], auto["overLimit"]), (201, True))
        self.assertEqual((scene["shotCount"], "overLimit" in scene), (1, False))
        self.assertEqual(self.call(f"/episodes/{self.ep}/storyboards", "POST", {"breakdownMode": "auto"})[0], 422)  # the build refuses exactly that
        self.assertEqual(self.check("scene")["shotCount"], 1)

    def test_the_request_is_validated(self):
        self.prepare(SCRIPT)
        for value in (9, 1801, 0, -5, True, "45", 45.5, [], {}, 10 ** 12):
            status, payload = self.call(self.path, "POST", {"targetSeconds": value})
            self.assertEqual((status, payload["code"]), (400, "DRAMA_REQUEST_FAILED"), value)
        for value in (10, 45, 1800):
            self.assertEqual(self.estimate(targetSeconds=value)["targetSeconds"], value)  # echoed, never used to change a number
            self.assertEqual(self.estimate(targetSeconds=value)["modes"], self.estimate()["modes"])
        self.assertIsNone(self.estimate(targetSeconds=None)["targetSeconds"])
        for body in ({"breakdownModes": []}, {"breakdownModes": "auto"}, {"breakdownModes": ["bogus"]}, {"breakdownModes": [5]},
                     {"breakdownModes": [["auto"]]}, {"breakdownModes": ["auto"] * 17}, {"scriptContent": 5}, {"scriptContent": "x" * 500001}):
            self.assertEqual(self.call(self.path, "POST", body)[0], 422, body)
        self.assertEqual([m["breakdownMode"] for m in self.estimate(breakdownModes=["scene", "auto", "scene"])["modes"]], ["scene", "auto"])
        self.assertEqual(self.estimate(breakdownModes=["cinematic_multi"])["modes"][0]["breakdownMode"], "cinematic_multi")
        self.assertEqual(self.request(story.BASE + self.path, method="POST", data={}, authenticated=False)[0], 401)
        self.assertEqual(self.call(f"/episodes/ep_{self.slug}_09/storyboard-estimates", "POST", {})[0], 404)
        self.assertEqual(self.call(self.path, "GET")[0], 404)  # estimates are asked for, not listed

    def test_viewers_may_ask_but_still_cannot_build(self):
        self.prepare(SCRIPT)
        repo.upsert_member(self.conn, self.actor, "Viewer", "viewer")
        self.conn.commit()
        self.assertEqual(self.estimate(breakdownModes=["scene"])["modes"][0]["keptShots"], 5)
        self.assertEqual(self.call(f"/episodes/{self.ep}/storyboards", "POST", {})[0], 409)
        self.assertEqual(self.call(f"/episodes/{self.ep}/script", "PUT", {"scriptContent": "Scene 01: x\n@CAST-01"})[0], 409)

    def test_an_estimate_writes_nothing_locks_nothing_and_calls_no_model(self):
        self.prepare(SCRIPT)
        slug = self.slug

        def state():
            with self.conn.cursor() as cur:
                cur.execute("SELECT DISTINCT table_name FROM information_schema.columns WHERE table_schema='projectops' AND column_name='project_slug'")
                counts = {}
                for (table,) in cur.fetchall():
                    cur.execute(f"SELECT count(*) FROM projectops.{table} WHERE project_slug=%s", (slug,))
                    counts[table] = cur.fetchone()[0]
                cur.execute("SELECT coalesce(max(updated_at)::text, '') FROM projectops.story_record WHERE project_slug=%s", (slug,))
                counts["story_record.updated_at"] = cur.fetchone()[0]
            revisions = {t["key"]: t["revision"] for t in repo.list_tabs(self.conn, slug)}
            self.conn.rollback()
            return counts, revisions
        before = state()
        import psycopg
        writer = psycopg.connect(os.environ["OPENBENCH_TEST_DB_URI"])  # a build in progress: tab row locked, story write lock held
        try:
            repo.get_tab_for_update(writer, slug, story.episode(self.conn, self.ep)["tabKey"])
            with writer.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("story-write:" + slug,))
            with patch.object(providers, "run_openai_compat_turn", side_effect=AssertionError("model call")), \
                    patch.object(story._POOL, "submit", side_effect=AssertionError("queued work")), \
                    patch.object(worker, "execute_story_card", side_effect=AssertionError("rendered")), \
                    patch.dict(os.environ, {"OPENBENCH_MODEL": "must-not-call", "OPENBENCH_API_BASE": "https://example.invalid"}):
                started = time.monotonic()
                self.estimate(breakdownModes=list(MODES))
                self.estimate(breakdownModes=list(MODES), scriptContent=DRAFT, targetSeconds=90)
                self.assertLess(time.monotonic() - started, 8)  # it did not wait for either lock
        finally:
            writer.rollback()
            writer.close()
        self.assertEqual(state(), before)

    def test_the_real_build_and_the_estimate_ask_the_same_planner(self):
        self.confirm(SCRIPT)
        with patch.object(planner, "scene_steps", wraps=planner.scene_steps) as spy:
            self.estimate(breakdownModes=["auto"])
            asked = spy.call_count
            self.assertEqual(asked, 3)  # once per scene
            self.ok(f"/episodes/{self.ep}/storyboards", "POST", {})
            self.assertEqual(spy.call_count, 2 * asked)  # the build consults the very same function, scene by scene
        with patch.object(planner, "scene_steps", wraps=planner.scene_steps) as spy:
            scene = self.ok(f"/episodes/{self.ep}/scenes")["items"][1]
            self.ok("/scenes/" + scene["sceneId"] + "/shot-rebuilds", "POST", {})
            self.assertEqual(spy.call_count, 1)  # a one-scene rebuild plans only that scene


if __name__ == "__main__":
    unittest.main()
