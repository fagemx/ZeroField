"""SPEC_20 R26/R29: a shot's 3D previs plan stored in the project, with a revision every write must name.

Rule tests need nothing; the parity test runs the stage's own plan.js in node (skipped without node); the HTTP tests
use PostgreSQL through the real story server (OPENBENCH_TEST_DB_URI).
"""
import copy
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

from project_docs import repository as repo, story_openapi as story, story_previs
import test_story_openapi as fixture

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = {"set": "observatory", "move": "pushin", "lens": 35, "action": "turnreach", "facing": "console", "mood": "grey",
           "seconds": 4, "keys": None}
# Everything the stage can put in a plan: framed keys and easing, marks, the cast with codes, acting keys, pins, skills
# with an open range, fixes, the parallax cards and props.
RICH = {**DEFAULT, "set": "parallax", "seconds": 8, "lens": 50, "move": "orbit", "mood": "night", "facing": "room",
        "keys": [[0, [1.4, 1.45, -5.8], [-0.2, 2.75, 0.4]], [48.5, [0.55, 1.8, -2.6], [-0.1, 1.5, 0.5]], [96, [-0.75, 1.95, -0.85], [0, 1.3, 0.5]]],
        "easing": [0.16, 1.4, 0.3, 1], "mark": [0.5, -1], "turn": 15, "code": "@CAST-01",
        "figure": {"build": "woman", "outfit": "longcoat", "hair": "bun", "tone": 2},
        "cast": [{"code": "@CAST-02", "mark": [1.5, 0.35], "turn": -111.8, "figure": {"build": "elder"},
                  "acts": [{"at": 0, "body": "stand"}, {"at": 1, "body": "lean", "face": "tense", "headYaw": 0.4}]}],
        "acts": [{"at": 0, "yaw": 3.14, "reach": 0}, {"at": 0.6, "reach": 1.16, "body": "kneel", "face": "cry", "armSwing": 0.2, "sway": 0.02, "bounce": -0.01}],
        "pins": [{"at": 0.5, "joint": "wristL", "pos": [-0.25, 1.03, 0.56], "radius": 0.1, "skill": "reachGrip"}],
        "use": [{"skill": "walkTo", "f0": 0, "frames": 96, "args": {"from": [0, -2.4], "to": [{"range": [-0.3, 0.3]}, -0.25], "steps": 6, "vary": 0.5}},
                {"skill": "standIdle", "f0": 96, "frames": 24, "args": {"at": [0, -0.25], "plant": True, "until": 120, "heading": 0.5}},
                {"skill": "reachGrip", "args": {"anchor": "dial", "side": "L", "reach": 12, "hold": 24, "release": 12}},
                {"skill": "turnLook", "frames": 16, "args": {"anchor": [0, 1.45, 3.8]}},
                {"skill": "kneelDown", "args": {"duration": 24, "face": "fear"}}],
        "fix": {"ground": True, "slide": True, "penetration": True, "retime": False},
        "layers": [{"id": "far", "src": "/projects/api/demo/assets/pa_" + "a" * 32}, {"id": "mid", "role": "mid", "z": 2.2, "billboard": "full", "color": "#6c7179", "opacity": 0.8},
                   {"id": "near", "billboard": False, "color": 0x26282c, "scale": 0.55}],
        "beacon": False, "props": [{"id": "pad", "shape": "cylinder", "radius": 0.11, "height": 0.115, "position": [0.25, 1.0175, 0.245], "color": "#d4aa65", "contact": True},
                                   {"id": "crate", "size": [0.4, 0.4, 0.4], "position": [1, 0.2, 0]}],
        "presentation": "rehearsal"}
CODES = {"@CAST-01", "@CAST-02"}
BIG_ACT = {"at": 0.123456789012, "yaw": 1.23456789012, "reach": 0.5, "back": 0.1, "side": 0.1, "headYaw": 0.2,
           "armSwing": 0.1, "sway": 0.01, "bounce": 0.01, "body": "stand", "face": "neutral"}  # ~150 bytes of acting


class PlanRuleTests(unittest.TestCase):
    def refused(self, plan, fragment="", codes=None):
        with self.assertRaises(story.StoryError) as caught:
            story_previs.validate(plan, codes)
        self.assertEqual((caught.exception.status, caught.exception.code), (422, "DRAMA_VALIDATION_FAILED"), plan)
        self.assertIn(fragment, str(caught.exception))

    def test_plans_the_stage_writes_are_accepted(self):
        for plan in (DEFAULT, RICH, {**DEFAULT, "keys": [[0, [1, 2, 3], [0, 0, 0]], [96, [1, 2, 3], [0, 0, 0]]]},
                     {**DEFAULT, "fix": True}, {**DEFAULT, "fix": False}, {**DEFAULT, "easing": None, "layers": None},
                     {**DEFAULT, "cast": [{"mark": [2, 0]}]}, {**DEFAULT, "lens": 85.0}):
            story_previs.validate(plan, CODES)
        story_previs.validate(RICH)  # no cast sheet lookup: the format alone

    def test_unknown_keys_missing_keys_and_enums_are_refused(self):
        self.refused({**DEFAULT, "zoom": 2}, "unknown keys: zoom")
        for key in story_previs.REQUIRED:
            self.refused({k: v for k, v in DEFAULT.items() if k != key}, "needs " + key)
        for key, value in (("set", "studio"), ("move", "zoom"), ("lens", 40), ("lens", "35"), ("lens", True), ("action", "run"),
                           ("facing", "camera"), ("mood", "day"), ("seconds", 5), ("seconds", 4.5), ("presentation", "final")):
            self.refused({**DEFAULT, key: value}, "plan." + key)
        self.refused([DEFAULT], "plan must be an object")
        self.refused({**RICH, "figure": {"build": "giant"}}, "plan.figure.build")
        self.refused({**RICH, "figure": {"tone": 1.5}}, "plan.figure.tone")
        self.refused({**RICH, "acts": [{"yaw": 1}]}, "plan.acts[0] needs at")
        self.refused({**RICH, "acts": [{"at": 0, "body": "dance"}]}, "plan.acts[0].body")
        self.refused({**RICH, "acts": [{"at": 0, "wink": 1}]}, "unknown keys: wink")
        self.refused({**RICH, "pins": [{"at": 0.5, "joint": "tail", "pos": [0, 0, 0]}]}, "plan.pins[0].joint")
        self.refused({**RICH, "pins": [{"at": 0.5, "joint": "head", "pos": [0, 0, 0], "radius": 0}]}, "plan.pins[0].radius")
        self.refused({**RICH, "use": [{"skill": "fly"}]}, "plan.use[0].skill")
        self.refused({**RICH, "use": [{"skill": "walkTo", "args": {"anchor": "dial"}}]}, "plan.use[0].args has unknown keys: anchor")
        self.refused({**RICH, "use": [{"skill": "reachGrip", "args": {"anchor": "door"}}]}, "plan.use[0].args.anchor")
        self.refused({**RICH, "use": [{"skill": "reachGrip", "args": {"side": "left"}}]}, "plan.use[0].args.side")
        self.refused({**RICH, "fix": {"ground": "yes"}}, "plan.fix.ground")
        self.refused({**RICH, "fix": {"gravity": True}}, "plan.fix has unknown keys")
        self.refused({**RICH, "props": [{"id": "x", "shape": "sphere"}]}, "plan.props[0].shape")
        self.refused({**RICH, "props": [{"shape": "box"}]}, "plan.props[0] needs id")
        self.refused({**RICH, "layers": [{"id": "far", "role": "sky"}]}, "plan.layers[0].role")
        self.refused({**RICH, "layers": [{"id": "far", "billboard": "half"}]}, "plan.layers[0].billboard")
        self.refused({**RICH, "beacon": 1}, "plan.beacon")
        self.refused({**RICH, "cast": [{"name": "Kael"}]}, "plan.cast[0] has unknown keys: name")
        self.refused({**RICH, "cast": [{"mark": [0, 0]}] * 9}, "at most 8")

    def test_numbers_must_be_finite_and_in_range(self):
        for value in (float("nan"), float("inf"), -float("inf"), 10 ** 400, "1", True, None, [1]):
            self.refused({**DEFAULT, "mark": [value, 0]}, "plan.mark[0]")
        self.refused({**DEFAULT, "mark": [0, 101]}, "between -100 and 100")
        self.refused({**DEFAULT, "mark": [0]}, "list of 2 numbers")
        self.refused({**DEFAULT, "turn": 721}, "plan.turn")
        self.refused({**DEFAULT, "easing": [1.2, 0, 0.5, 1]}, "plan.easing[0]")
        self.refused({**DEFAULT, "easing": [0.2, 2.5, 0.5, 1]}, "plan.easing[1]")
        self.refused({**DEFAULT, "easing": [0.2, 1]}, "cubic-bezier")
        self.refused({**RICH, "layers": [{"id": "far", "opacity": 1.5}]}, "plan.layers[0].opacity")
        self.refused({**RICH, "use": [{"skill": "standIdle", "f0": 400}]}, "plan.use[0].f0")
        self.refused({**RICH, "acts": [{"at": 1.5}]}, "plan.acts[0].at")

    def test_camera_keys_run_forward_on_the_beat_clock(self):
        key = lambda beat: [beat, [0, 1.6, -2], [0, 1.4, 0.4]]
        self.refused({**DEFAULT, "keys": [key(0)]}, "at least two camera keys")
        self.refused({**DEFAULT, "keys": []}, "at least two camera keys")
        self.refused({**DEFAULT, "keys": [key(0), key(97)]}, "plan.keys[1][0]")
        self.refused({**DEFAULT, "keys": [key(-1), key(96)]}, "plan.keys[0][0]")
        self.refused({**DEFAULT, "keys": [key(60), key(30)]}, "must not come before")
        self.refused({**DEFAULT, "keys": [key(0), [96, [0, 1], [0, 0, 0]]]}, "plan.keys[1][1]")
        self.refused({**DEFAULT, "keys": [key(0), [96, [0, 1, 2]]]}, "plan.keys[1] must be [beat")
        self.refused({**DEFAULT, "keys": [key(beat) for beat in range(65)]}, "at most 64")
        story_previs.validate({**DEFAULT, "keys": [key(0), key(0), key(96)]})  # a held key is still a path

    def test_cast_codes_come_from_the_cast_sheet_and_stand_on_set_once(self):
        for code in ("CAST-01", "@cast-01", "@SET-01", "@CAST-01:night", "@CAST-", 1, ""):
            self.refused({**DEFAULT, "cast": [{"code": code}]}, "must be a cast code such as @CAST-01")
        self.refused({**DEFAULT, "code": "@CAST-03"}, "@CAST-03, which is not on the cast sheet", CODES)
        self.refused({**DEFAULT, "cast": [{"code": "@CAST-09"}]}, "plan.cast[0].code names @CAST-09", CODES)
        self.refused({**DEFAULT, "code": "@CAST-01", "cast": [{"code": "@CAST-01"}]}, "@CAST-01 can stand on set only once", CODES)
        self.refused({**DEFAULT, "cast": [{"code": "@CAST-02"}, {"code": "@CAST-02"}]}, "@CAST-02 can stand on set only once", CODES)
        story_previs.validate({**DEFAULT, "code": "@CAST-02", "cast": [{"code": "@CAST-01"}, {"mark": [1, 1]}]}, CODES)
        self.refused({**DEFAULT, "code": "@CAST-01"}, "not on the cast sheet", set())

    def test_open_ranges_are_taken_where_the_motion_search_reads_them(self):
        story_previs.validate({**DEFAULT, "mark": [{"range": [-0.5, 0.5]}, 0], "pins": [{"at": {"range": [0.2, 0.4]}, "joint": "head", "pos": [0, 1.7, 0]}]})
        self.refused({**DEFAULT, "mark": [{"range": [0.5, -0.5]}, 0]}, "must run from low to high")
        self.refused({**DEFAULT, "mark": [{"range": [0]}, 0]}, '{"range": [low, high]}')
        self.refused({**DEFAULT, "mark": [{"range": [0, 1], "step": 1}, 0]}, '{"range": [low, high]}')
        self.refused({**DEFAULT, "lens": {"range": [24, 85]}}, "plan.lens")  # enums and camera keys are never open
        self.refused({**DEFAULT, "keys": [[0, [{"range": [0, 1]}, 1, 1], [0, 0, 0]], [96, [0, 1, 1], [0, 0, 0]]]}, "plan.keys[0][1][0]")

    def test_card_images_load_from_this_server_or_the_web_only(self):
        for src in ("/projects/api/demo/assets/pa_1", "https://example.com/set.png", "http://127.0.0.1:3020/a.png"):
            story_previs.validate({**DEFAULT, "layers": [{"id": "far", "src": src}]})
        for src in ("javascript:alert(1)", "data:image/png;base64,AAAA", "//evil.example/x.png", "ftp://x/y.png", "/a b.png", "", "/" + "a" * 2048):
            self.refused({**DEFAULT, "layers": [{"id": "far", "src": src}]}, "plan.layers[0].src")

    def test_a_plan_holds_at_most_64_kb(self):
        size = lambda plan: len(story_previs.canonical(plan).encode())
        plan = {**DEFAULT, "acts": []}
        while size({**plan, "acts": plan["acts"] + [BIG_ACT]}) <= story_previs.MAX_BYTES:
            plan["acts"].append(BIG_ACT)
        self.assertGreater(size(plan), story_previs.MAX_BYTES - 200)
        story_previs.validate(plan)  # right under the limit
        self.refused({**plan, "acts": plan["acts"] + [BIG_ACT]}, "at most 65536 bytes (64 KB)")
        self.refused({**DEFAULT, "demo": "x" * 70000}, "64 KB")  # measured before anything else

    def test_the_revision_comes_from_the_body_or_if_match_and_both_must_agree(self):
        revision = story_previs.base_revision
        self.assertEqual(revision({"baseRevision": 0}), 0)
        self.assertEqual(revision({}, '"3"'), 3)
        self.assertEqual(revision({}, " 3 "), 3)
        self.assertEqual(revision({"baseRevision": 3}, '"3"'), 3)
        for body, header, fragment in (({}, None, "baseRevision or an If-Match"), ({"baseRevision": -1}, None, "at least 0"),
                                       ({"baseRevision": 1.0}, None, "whole number"), ({"baseRevision": True}, None, "whole number"),
                                       ({"baseRevision": "2"}, None, "whole number"), ({"baseRevision": None}, None, "whole number"),
                                       ({}, "*", "If-Match"), ({}, 'W/"3"', "If-Match"), ({}, '"3", "4"', "If-Match"), ({}, '"x"', "If-Match"),
                                       ({}, '"3', "If-Match"), ({"baseRevision": 2}, '"3"', "different revisions")):
            with self.assertRaises(story.StoryError) as caught:
                revision(body, header)
            self.assertEqual(caught.exception.status, 422)
            self.assertIn(fragment, str(caught.exception))

    def test_a_shot_payload_carries_the_revision_and_never_the_plan(self):
        meta = {"episodeId": "ep", "previsPlan": {"lens": 50}, story_previs.KEY: {"plan": RICH, "planRevision": 4, "updatedAt": "t", "updatedBy": "a"}}
        fields = story_previs.shot_fields(meta)
        self.assertNotIn(story_previs.KEY, fields)
        self.assertEqual((fields["previsPlanRevision"], fields["previsPlanStored"], fields["previsPlan"]), (4, True, {"lens": 50}))
        self.assertEqual(meta[story_previs.KEY]["planRevision"], 4, "the shot's meta itself is not changed")
        cleared = story_previs.shot_fields({story_previs.KEY: {"plan": None, "planRevision": 5}})
        self.assertEqual((cleared["previsPlanRevision"], cleared["previsPlanStored"]), (5, False))
        for corrupt in ({}, {story_previs.KEY: "x"}, {story_previs.KEY: {"plan": [1], "planRevision": "7"}}, {story_previs.KEY: {"planRevision": True}}):
            self.assertEqual({k: story_previs.shot_fields(corrupt)[k] for k in ("previsPlanRevision", "previsPlanStored")},
                             {"previsPlanRevision": 0, "previsPlanStored": False}, corrupt)


@unittest.skipUnless(shutil.which("node"), "node runs the stage's plan.js")
class StagePlanParityTests(unittest.TestCase):
    """The validator's enums are the stage's, and every plan the stage itself makes passes it."""
    SCRIPT = """
import * as plan from './src/previs/plan.js';
import * as blocking from './src/previs/blocking.js';
import { createMotionDemoPlan } from './src/previs/demoPlan.js';
import { resolveShotPlan } from './src/previs/storyPlan.js';
const base = plan.defaultPlan(), walk = { ...base, action: 'walkin', seconds: 8 };
const dragged = blocking.moveDummy(blocking.moveDummy({ ...createMotionDemoPlan(), demo: undefined }, 'actor', [0.7, -1.3]), 'cast:0', [2.2, 0.4]);
const plans = [base, plan.planFromSlate({ motion: 'Crane up', rig: 'ARRI / 85mm', action: 'She walks in' }),
  plan.planFromSlate({ motion: 'Static tripod', rig: '24mm', action: 'waits' }), createMotionDemoPlan(), dragged,
  blocking.moveCameraKey(base, 1, [0.4, -2.2]), blocking.retimeCameraKey({ ...base, move: 'orbit' }, 1, 30.25),
  blocking.setCameraRange(base, { start: 12, end: 80 }), blocking.resizeBeat(walk, 0, 150), blocking.moveBeat(walk, 0, 20),
  resolveShotPlan({ slate: { motion: 'orbit', rig: '50mm', action: '' }, previsPlan: { set: 'parallax' }, setAsset: { url: '/projects/api/x/assets/pa_1' } })];
console.log(JSON.stringify({
  constants: { SETS: plan.SETS, MOVES: plan.MOVES, LENSES: plan.LENSES, ACTIONS: plan.ACTIONS, MOODS: plan.MOODS, FACINGS: plan.FACINGS,
    DURATIONS: plan.DURATIONS, FIGURE_OPTIONS: plan.FIGURE_OPTIONS, POSES: Object.keys(plan.POSES), EXPRESSIONS: Object.keys(plan.EXPRESSIONS),
    MSFLOW_JOINTS: plan.MSFLOW_JOINTS, SCENE_ANCHORS: Object.keys(plan.SCENE_ANCHORS), CLOCK: blocking.CLOCK },
  plans }));
"""

    def test_enums_match_the_stage_and_the_stages_own_plans_validate(self):
        done = subprocess.run(["node", "--input-type=module", "-e", self.SCRIPT], cwd=ROOT / "ui", capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        stage = json.loads(done.stdout)
        constants = stage["constants"]
        for name in ("SETS", "MOVES", "LENSES", "ACTIONS", "MOODS", "FACINGS", "DURATIONS", "POSES", "EXPRESSIONS", "MSFLOW_JOINTS", "SCENE_ANCHORS"):
            self.assertEqual(list(getattr(story_previs, name)), constants[name], name)
        self.assertEqual({k: list(v) for k, v in story_previs.FIGURE_OPTIONS.items()}, constants["FIGURE_OPTIONS"])
        self.assertEqual(story_previs.CLOCK, constants["CLOCK"])
        self.assertEqual(len(stage["plans"]), 11)
        for plan in stage["plans"]:
            story_previs.validate(plan)


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "set OPENBENCH_TEST_DB_URI for Story HTTP tests")
class PrevisPlanHTTPTests(unittest.TestCase):
    setUp = fixture.StoryHTTPTests.setUp
    tearDown = fixture.StoryHTTPTests.tearDown
    request = fixture.StoryHTTPTests.request
    call = fixture.StoryHTTPTests.call
    ok = fixture.StoryHTTPTests.ok
    prepare = fixture.StoryHTTPTests.prepare

    def path(self, shot):
        return f"/shots/{shot['shotId']}/previs-plan"

    def put(self, shot, plan, revision=None, if_match=None, expect=200):
        body = {"plan": plan, **({"baseRevision": revision} if revision is not None else {})}
        code, payload = self.call(self.path(shot), "PUT", body, {"If-Match": if_match} if if_match is not None else None)
        self.assertEqual(code, expect, payload)
        return payload["data"] if code == 200 else payload

    def shot(self, shot):
        return self.ok("/shots/" + shot["shotId"])

    def listed(self, shot):
        return next(s for s in self.ok(f"/episodes/{self.ep}/shots?limit=100")["items"] if s["shotId"] == shot["shotId"])

    def test_a_saved_plan_reads_back_and_shot_payloads_carry_only_its_revision(self):
        shot = self.prepare()[0]
        empty = self.ok(self.path(shot))
        self.assertEqual({k: empty[k] for k in ("shotId", "plan", "planRevision", "updatedAt", "updatedBy")},
                         {"shotId": shot["shotId"], "plan": None, "planRevision": 0, "updatedAt": None, "updatedBy": None})
        self.assertIn({"code": "@CAST-01", "name": next(a["name"] for a in self.ok(f"/episodes/{self.ep}/assets")["items"] if a["assetCode"] == "CAST-01")},
                      empty["castOptions"])
        self.assertTrue(all(o["code"].startswith("@CAST-") for o in empty["castOptions"]))
        self.assertEqual((shot["previsPlanRevision"], shot["previsPlanStored"]), (0, False))
        plan = {**DEFAULT, "lens": 85, "move": "orbit", "mark": [0.4, -0.6], "code": "@CAST-01",
                "keys": [[0, [2.3, 1.7, -1.6], [0, 1.4, 0.15]], [96, [-2.1, 1.7, -1.4], [0, 1.4, 0.15]]]}
        saved = self.put(shot, plan, revision=0)
        self.assertEqual((saved["plan"], saved["planRevision"], saved["updatedBy"], saved["shotId"]), (plan, 1, self.actor, shot["shotId"]))
        self.assertTrue(saved["updatedAt"])
        self.assertEqual(self.ok(self.path(shot)), saved)
        for view in (self.shot(shot), self.listed(shot)):
            self.assertEqual((view["previsPlanRevision"], view["previsPlanStored"]), (1, True))
            self.assertNotIn(story_previs.KEY, view)
            self.assertNotIn("planRevision", view)
            self.assertEqual(view["previsPlan"], shot["previsPlan"], "the storyboard seed is still there")
        again = self.put(shot, plan, if_match='"1"')  # the same plan again: nothing new to store
        self.assertEqual((again["planRevision"], again["updatedAt"]), (1, saved["updatedAt"]))
        moved = self.put(shot, {**plan, "lens": 50}, revision=1, if_match="1")
        self.assertEqual((moved["planRevision"], moved["plan"]["lens"]), (2, 50))
        meta = story.shot_meta(self.conn, shot["shotId"])
        self.assertEqual((meta[story_previs.KEY]["planRevision"], meta["sceneId"], meta["previsPlan"]), (2, shot["sceneId"], shot["previsPlan"]))

    def test_a_stale_revision_conflicts_and_writes_nothing(self):
        shot = self.prepare()[0]
        first = self.put(shot, {**DEFAULT, "lens": 24}, revision=0)
        self.put(shot, {**DEFAULT, "lens": 50}, if_match='"1"')
        for revision, header in ((1, None), (0, None), (None, '"1"'), (7, None)):
            refused = self.put(shot, {**DEFAULT, "lens": 85}, revision=revision, if_match=header, expect=409)
            self.assertEqual(refused["code"], story_previs.CONFLICT)
            self.assertEqual(refused["details"], {"currentRevision": 2, "baseRevision": revision if revision is not None else 1})
            self.assertIn("Reload", refused["message"])
        self.assertEqual(self.put(shot, {**DEFAULT, "lens": 24}, revision=1, expect=409)["code"], story_previs.CONFLICT,
                         "a stale writer conflicts even when it repeats an earlier plan")
        current = self.ok(self.path(shot))
        self.assertEqual((current["planRevision"], current["plan"]["lens"]), (2, 50))
        self.assertNotEqual(current["updatedAt"], None)
        self.assertEqual(first["planRevision"], 1)

    def test_a_write_needs_a_revision_and_a_valid_plan_and_refusals_change_nothing(self):
        shot = self.prepare()[0]
        self.put(shot, DEFAULT, revision=0)
        path = self.path(shot)
        for body, headers, fragment in (({"plan": DEFAULT}, None, "baseRevision or an If-Match"),
                                        ({"baseRevision": 1}, None, "plan is required"),
                                        ({"plan": DEFAULT, "baseRevision": 1, "note": "x"}, None, "Unknown previs plan fields: note"),
                                        ({"plan": DEFAULT, "baseRevision": 1}, {"If-Match": '"2"'}, "different revisions"),
                                        ({"plan": DEFAULT}, {"If-Match": "*"}, "If-Match"),
                                        ({"plan": {**DEFAULT, "lens": 40}, "baseRevision": 1}, None, "plan.lens"),
                                        ({"plan": {**DEFAULT, "code": "@CAST-77"}, "baseRevision": 1}, None, "not on the cast sheet"),
                                        ({"plan": {**DEFAULT, "acts": [BIG_ACT] * 500}, "baseRevision": 1}, None, "64 KB"),
                                        ({"plan": "pushin", "baseRevision": 1}, None, "plan must be an object")):
            code, payload = self.call(path, "PUT", body, headers)
            self.assertEqual((code, payload["code"]), (422, "DRAMA_VALIDATION_FAILED"), body)
            self.assertIn(fragment, payload["message"])
        for token in (b'{"plan": {"set": "observatory", "move": "pushin", "lens": 35, "action": "stand", "facing": "console", "mood": "grey", "seconds": 4, "mark": [NaN, 0]}, "baseRevision": 1}',
                      b'{"plan": {"set": "observatory", "move": "pushin", "lens": 35, "action": "stand", "facing": "console", "mood": "grey", "seconds": 4, "turn": Infinity}, "baseRevision": 1}'):
            code, payload, _ = self.request(story.BASE + path, method="PUT", raw=token, headers={"Content-Type": "application/json"})
            self.assertEqual((code, payload["code"]), (422, "DRAMA_VALIDATION_FAILED"), token)
        self.assertEqual(self.ok(path)["planRevision"], 1)
        self.assertEqual(self.ok(path)["plan"], DEFAULT)

    def test_unknown_shots_other_routes_and_crew_who_cannot_write_are_refused(self):
        shot = self.prepare()[0]
        for method in ("GET", "PUT"):
            self.assertEqual(self.call(f"/shots/sh_{self.slug}_bmissing/previs-plan", method, {"plan": DEFAULT, "baseRevision": 0})[0], 404)
        asset = self.ok(f"/episodes/{self.ep}/assets")["items"][0]
        self.assertEqual(self.call(f"/assets/{asset['assetId']}/previs-plan")[0], 404)
        for method in ("POST", "PATCH", "DELETE"):
            self.assertEqual(self.call(self.path(shot), method, {"plan": DEFAULT, "baseRevision": 0})[0], 404, method)
        self.assertEqual(self.request(story.BASE + self.path(shot), authenticated=False)[0], 401)
        self.assertEqual(self.request(story.BASE + self.path(shot), method="PUT", data={"plan": DEFAULT, "baseRevision": 0}, authenticated=False)[0], 401)
        repo.upsert_member(self.conn, self.actor, "Viewer", "viewer"); self.conn.commit()
        code, payload = self.call(self.path(shot), "PUT", {"plan": DEFAULT, "baseRevision": 0})
        self.assertEqual((code, payload["code"]), (409, "DRAMA_OPERATION_NOT_ALLOWED"))
        self.assertEqual(self.ok(self.path(shot))["planRevision"], 0, "a viewer still reads the plan")

    def test_clearing_rebuilding_trimming_and_splitting_keep_the_right_plan(self):
        first, second = self.prepare()
        plan = {**DEFAULT, "move": "track", "lens": 24, "keys": [[0, [2.4, 1.6, -2.2], [0.6, 1.4, 0.4]], [96, [-2.2, 1.6, -2.2], [-0.6, 1.4, 0.4]]]}
        self.put(first, plan, revision=0)
        # Mark the seed, then rebuild the scene from new text: the rebuild rewrites the seed (it is the storyboard's)
        # and must leave the director's stored plan exactly as it was.
        meta = story.shot_meta(self.conn, first["shotId"])
        story.store(self.conn, "meta_" + first["shotId"], "shot_meta", meta | {"previsPlan": {**meta["previsPlan"], "set": "empty"}}, self.slug)
        self.conn.commit()
        self.ok("/scenes/" + first["sceneId"], "PATCH", {"content": "@CAST-01 turns from the glass to the brass dial."})
        self.ok(f"/episodes/{self.ep}/asset-extractions", "POST", {})
        self.ok(f"/scenes/{first['sceneId']}/shot-rebuilds", "POST", {})
        self.assertEqual(self.shot(first)["previsPlan"]["set"], "parallax", "the rebuild rewrote the storyboard seed")
        rebuilt = self.ok(self.path(first))
        self.assertEqual((rebuilt["plan"], rebuilt["planRevision"]), (plan, 1), "a storyboard rebuild only rewrites the seed")
        self.ok(f"/shots/{first['shotId']}/trim", "PUT", {"in": 1})
        self.assertEqual(self.ok(self.path(first))["plan"], plan, "a trim leaves the plan alone")
        self.assertEqual(self.put(first, {**plan, "lens": 35}, revision=1)["planRevision"], 2)
        self.assertEqual(self.shot(first)["trim"]["in"], 1, "a plan leaves the trim alone")
        halves = self.ok(f"/shots/{first['shotId']}/splits", "POST", {})["shots"]
        self.assertEqual([(h["previsPlanRevision"], h["previsPlanStored"]) for h in halves], [(2, True), (2, True)], "both halves start from the same blocking")
        cleared = self.put(first, None, revision=2)
        self.assertEqual((cleared["plan"], cleared["planRevision"]), (None, 3))
        self.assertEqual((self.shot(first)["previsPlanRevision"], self.shot(first)["previsPlanStored"]), (3, False))
        self.assertEqual(self.put(first, None, revision=3)["planRevision"], 3, "clearing an empty plan writes nothing")
        self.assertEqual(self.put(first, DEFAULT, revision=2, expect=409)["details"]["currentRevision"], 3)
        self.assertEqual(self.ok(self.path(second))["planRevision"], 0, "another shot keeps its own revision")
        self.assertEqual(self.put(second, copy.deepcopy(RICH) | {"code": "@CAST-01", "cast": [{"mark": [1, 0]}]}, revision=0)["planRevision"], 1)


if __name__ == "__main__":
    unittest.main()
