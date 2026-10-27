"""A shot's 3D previs plan, stored in the project with a revision (SPEC_20 R26, R29).

Before SPEC_20 the full plan (camera keys, marks, acting, lens) lived only in the browser (a localStorage draft) and
in the title of the rendered previs WebM; the backend kept just the storyboard's six-field seed in
``meta_<shotId>.previsPlan``. The full plan is now stored in the same shot meta record, under its own key:

    meta_<shotId>.previsPlanFull = {"plan": {...} | None, "planRevision": 3, "updatedAt": "<ISO>", "updatedBy": "<actor id>"}

The seed key is left alone on purpose: a storyboard (re)build rewrites ``previsPlan``, and a director's stored plan
must survive that. The browser draft is now only an unsaved draft; the WebM title is a legacy backup.

Routes (registered in story_openapi.dispatch, the story envelope {code: 0, msg, data} on success):

    GET /aivideo/open/v1/shots/{shotId}/previs-plan
        data: {"shotId", "plan" (null when nothing is stored), "planRevision" (0 before the first save),
               "updatedAt", "updatedBy", "castOptions": [{"code": "@CAST-01", "name": "..."}]}
        castOptions are the production's cast (default CHARACTER rows of the cast sheet): the codes plan.code (the
        plan's own actor) and plan.cast[].code (everyone else on set) may name (R29).
    PUT /aivideo/open/v1/shots/{shotId}/previs-plan
        body {"plan": {...} | null, "baseRevision": n}, or the revision as an ``If-Match: "n"`` header (both may be sent
        when they agree). data: as GET, after the write. A changed plan gets revision n + 1; the same plan again keeps
        its revision; null clears the stored plan (the stage falls back to the seed) and still moves the revision on,
        so a writer holding the old revision conflicts.

Errors ({code, message, requestId, details?}):
    401 DRAMA_AUTH_MISSING / DRAMA_AUTH_INVALID   not signed in (story_openapi.handle)
    404 DRAMA_NOT_FOUND                           unknown shot (any row outside the cinema and lab sheets)
    409 DRAMA_OPERATION_NOT_ALLOWED               a read-only crew member writes (story_openapi.dispatch)
    409 DRAMA_PREVIS_REVISION_CONFLICT            the revision sent is not the stored one; nothing is written.
                                                  details: {"currentRevision": int, "baseRevision": int}
    422 DRAMA_VALIDATION_FAILED                   no or malformed revision, an unknown body field, or an invalid plan
                                                  (unknown key, enum, number range, cast code) or one over 64 KB

DRAMA_PREVIS_REVISION_CONFLICT is the one code this module adds; like DRAMA_WRITING_*, it names its module so the
stage can tell a lost update from any other refusal.
"""
from __future__ import annotations

import json
import math
import re

from project_docs import story_openapi as story

KEY = "previsPlanFull"  # the stored plan's record in meta_<shotId>
FIELD = "previsPlan"     # what proposals and tools call this field (SPEC_20 decision 5: target {shotId, field, baseRevision})
CONFLICT = "DRAMA_PREVIS_REVISION_CONFLICT"
MAX_BYTES = 64 * 1024    # the plan as compact UTF-8 JSON

# ui/src/previs/plan.js (tests/test_story_previs.py checks these against the JS module, so they cannot drift apart).
SETS = ("observatory", "parallax", "empty")
MOVES = ("pushin", "pullout", "orbit", "crane", "track", "static")
LENSES = (24, 35, 50, 85)
ACTIONS = ("turnreach", "stand", "walkin")
MOODS = ("grey", "night")
FACINGS = ("console", "room")
DURATIONS = (4, 6, 8, 10)
CLOCK = 96               # camera keys are written on a 0..96 beat clock, whatever the shot's length
LAST_FRAME = 240         # frames are counted on the longest shot (10 s at 24 fps, 241 frames)
FIGURE_OPTIONS = {"build": ("man", "woman", "child", "elder"), "outfit": ("jacket", "longcoat", "dress", "robe"),
                  "hair": ("short", "long", "bun")}
POSES = ("stand", "lean", "recoil", "slump", "lookup", "lookdown", "face", "crossed", "open", "kneel", "push", "walk")
EXPRESSIONS = ("neutral", "tense", "rage", "scream", "cry", "fear", "shock")
MSFLOW_JOINTS = ("pelvis", "hipL", "hipR", "spine1", "kneeL", "kneeR", "spine2", "ankleL", "ankleR", "spine3", "footL",
                 "footR", "neck", "collarL", "collarR", "head", "shoulderL", "shoulderR", "elbowL", "elbowR", "wristL", "wristR")
SCENE_ANCHORS = ("dial", "recorder", "console_edge", "window_glass")
SKILLS = ("standIdle", "walkTo", "reachGrip", "turnLook", "kneelDown")
LAYER_ROLES = ("far", "mid", "near")

REQUIRED = ("set", "move", "lens", "action", "facing", "mood", "seconds")
PLAN_KEYS = REQUIRED + ("keys", "easing", "mark", "turn", "figure", "code", "cast", "acts", "pins", "use", "fix",
                        "layers", "beacon", "props", "presentation", "demo")
MAX_KEYS, MAX_CAST, MAX_ACTS, MAX_PINS, MAX_USE, MAX_LAYERS, MAX_PROPS = 64, 8, 512, 2048, 64, 8, 32
REACH = 100.0            # metres: no stage point, camera or prop is further from the mark than this
TURNS = 100.0            # radians (yaw, heading): a few full turns either way
CAST_CODE = re.compile(r"@CAST-\d{1,4}")
COLOR = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})")
SOURCE = re.compile(r"(?:/(?!/)|https?://)[^\s\"'<>\\]{1,2047}")  # a card image: this server's path or a web URL


# ---------- reading ----------

def stored(meta):
    """The stored plan's record from shot meta, normalised: revision 0 and plan None before the first save."""
    saved = meta.get(KEY) if isinstance(meta, dict) else None
    saved = saved if isinstance(saved, dict) else {}
    revision = saved.get("planRevision")
    revision = revision if isinstance(revision, int) and not isinstance(revision, bool) and revision >= 0 else 0
    plan = saved.get("plan")
    return {"plan": plan if isinstance(plan, dict) else None, "planRevision": revision,
            "updatedAt": saved.get("updatedAt"), "updatedBy": saved.get("updatedBy")}


def shot_fields(meta):
    """Shot meta as a shot payload carries it: the stored plan's revision and whether one is stored, never the plan
    itself (up to 64 KB per shot in every shot list; the stage reads it from the previs-plan route)."""
    state = stored(meta)
    return {**{key: value for key, value in meta.items() if key != KEY},
            "previsPlanRevision": state["planRevision"], "previsPlanStored": state["plan"] is not None}


def cast_options(conn, slug):
    """The production's cast as plan codes: one entry per default CHARACTER row of the cast sheet, in sheet order."""
    options = {}
    for row in story.table_rows(conn, slug, "soul-cast"):
        asset = story.asset_view(slug, row)
        if asset["type"] == "CHARACTER" and asset["isDefault"] and re.fullmatch(r"CAST-\d{1,4}", asset["assetCode"]):
            options.setdefault("@" + asset["assetCode"], asset["name"])
    return [{"code": code, "name": name} for code, name in options.items()]


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


# ---------- validation ----------

def _fail(path, message):
    story.invalid(f"{path} {message}.")


def _number(value, path, low, high, *, ranged=False, whole=False):
    """A finite number in [low, high]; ranged also takes an open value {"range": [lo, hi]} (plan.js withRanges)."""
    if ranged and isinstance(value, dict):
        pair = value.get("range")
        if set(value) != {"range"} or not isinstance(pair, list) or len(pair) != 2:
            _fail(path, 'must be a number or {"range": [low, high]}')
        for index, end in enumerate(pair):
            _number(end, f"{path}.range[{index}]", low, high, whole=whole)
        if pair[0] > pair[1]:
            _fail(path + ".range", "must run from low to high")
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (isinstance(value, float) and not math.isfinite(value)):
        _fail(path, "must be a number")
    if not low <= value <= high:
        _fail(path, f"must be between {low:g} and {high:g}")
    if whole and value != int(value):
        _fail(path, "must be a whole number")


def _vector(value, path, size, low, high, *, ranged=False):
    sizes = size if isinstance(size, tuple) else (size,)
    if not isinstance(value, list) or len(value) not in sizes:
        _fail(path, f"must be a list of {' or '.join(map(str, sizes))} numbers")
    for index, item in enumerate(value):
        _number(item, f"{path}[{index}]", low, high, ranged=ranged)


def _choice(value, path, options):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)) or value not in options:
        _fail(path, "must be one of " + ", ".join(map(str, options)))


def _flag(value, path):
    if not isinstance(value, bool):
        _fail(path, "must be true or false")


def _text(value, path, maximum, pattern=None):
    if not isinstance(value, str) or not 0 < len(value) <= maximum or (pattern and not pattern.fullmatch(value)):
        _fail(path, f"must be valid text of at most {maximum} characters")


def _items(value, path, maximum):
    if not isinstance(value, list) or len(value) > maximum:
        _fail(path, f"must be a list of at most {maximum} entries")
    return [(f"{path}[{index}]", item) for index, item in enumerate(value)]


def _fields(value, path, allowed, required=()):
    """A JSON object with only known keys; a null optional value counts as absent."""
    if not isinstance(value, dict):
        _fail(path, "must be an object")
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        _fail(path, "has unknown keys: " + ", ".join(unknown))
    missing = [key for key in required if value.get(key) is None]
    if missing:
        _fail(path, "needs " + ", ".join(missing))
    return {key: item for key, item in value.items() if item is not None}


def _color(value, path):
    if isinstance(value, str):
        _text(value, path, 9, COLOR)
    else:
        _number(value, path, 0, 0xFFFFFFFF, whole=True)


def _figure(value, path):
    figure = _fields(value, path, (*FIGURE_OPTIONS, "tone"))
    for key, options in FIGURE_OPTIONS.items():
        if key in figure:
            _choice(figure[key], f"{path}.{key}", options)
    if "tone" in figure:
        _number(figure["tone"], path + ".tone", 0, 63, whole=True)


def _acts(value, path):
    for at, act in _items(value, path, MAX_ACTS):
        act = _fields(act, at, ("at", "yaw", "reach", "back", "side", "body", "face", "headYaw", "armSwing", "sway", "bounce"), ("at",))
        _number(act["at"], at + ".at", 0, 1)
        for key, limit in (("yaw", TURNS), ("headYaw", TURNS), ("back", REACH), ("side", REACH),
                           ("reach", 10), ("armSwing", 10), ("sway", 10), ("bounce", 10)):
            if key in act:
                _number(act[key], f"{at}.{key}", -limit, limit)
        if "body" in act:
            _choice(act["body"], at + ".body", POSES)
        if "face" in act:
            _choice(act["face"], at + ".face", EXPRESSIONS)


def _anchor(value, path):
    if isinstance(value, str):
        _choice(value, path, SCENE_ANCHORS)
    else:
        _vector(value, path, 3, -REACH, REACH, ranged=True)


SKILL_ARGS = {  # plan.js compileMotionSkills: what each skill reads from its args
    "standIdle": {"at": lambda v, p: _vector(v, p, 2, -REACH, REACH, ranged=True), "heading": lambda v, p: _number(v, p, -TURNS, TURNS, ranged=True),
                  "until": lambda v, p: _number(v, p, 0, LAST_FRAME, ranged=True), "plant": _flag},
    "walkTo": {"from": lambda v, p: _vector(v, p, 2, -REACH, REACH, ranged=True), "to": lambda v, p: _vector(v, p, 2, -REACH, REACH, ranged=True),
               "steps": lambda v, p: _number(v, p, 1, 64, ranged=True), "vary": lambda v, p: _number(v, p, 0, 10, ranged=True)},
    "reachGrip": {"anchor": _anchor, "side": lambda v, p: _choice(v, p, ("L", "R")),
                  **{key: (lambda v, p: _number(v, p, 0, LAST_FRAME, ranged=True)) for key in ("reach", "hold", "release")}},
    "turnLook": {"anchor": _anchor, "at": lambda v, p: _vector(v, p, (2, 3), -REACH, REACH, ranged=True),
                 "heading": lambda v, p: _number(v, p, -TURNS, TURNS, ranged=True)},
    "kneelDown": {"duration": lambda v, p: _number(v, p, 0, LAST_FRAME, ranged=True), "face": lambda v, p: _choice(v, p, EXPRESSIONS)},
}


def _use(value, path):
    for at, step in _items(value, path, MAX_USE):
        step = _fields(step, at, ("skill", "f0", "frames", "args"), ("skill",))
        _choice(step["skill"], at + ".skill", SKILLS)
        for key in ("f0", "frames"):
            if key in step:
                _number(step[key], f"{at}.{key}", 0, LAST_FRAME + 1, ranged=True)
        readers = SKILL_ARGS[step["skill"]]
        for key, arg in _fields(step.get("args", {}), at + ".args", readers).items():
            readers[key](arg, f"{at}.args.{key}")


def _pins(value, path):
    for at, pin in _items(value, path, MAX_PINS):
        pin = _fields(pin, at, ("at", "joint", "pos", "radius", "skill"), ("at", "joint", "pos"))
        _number(pin["at"], at + ".at", 0, 1, ranged=True)
        _choice(pin["joint"], at + ".joint", MSFLOW_JOINTS)
        _vector(pin["pos"], at + ".pos", 3, -REACH, REACH, ranged=True)
        if "radius" in pin:
            _number(pin["radius"], at + ".radius", 1e-6, 1, ranged=True)
        if "skill" in pin:
            _choice(pin["skill"], at + ".skill", SKILLS)


def _keys(value, path):
    keys = _items(value, path, MAX_KEYS)
    if len(keys) < 2:
        _fail(path, "must hold at least two camera keys, or be null for the move's preset")
    last = -1
    for at, key in keys:
        if not isinstance(key, list) or len(key) != 3:
            _fail(at, "must be [beat, [x, y, z] position, [x, y, z] aim]")
        _number(key[0], at + "[0]", 0, CLOCK)
        if key[0] < last:
            _fail(at + "[0]", "must not come before the key before it")
        last = key[0]
        _vector(key[1], at + "[1]", 3, -REACH, REACH)
        _vector(key[2], at + "[2]", 3, -REACH, REACH)


def _layers(value, path):
    for at, layer in _items(value, path, MAX_LAYERS):
        layer = _fields(layer, at, ("id", "role", "x", "y", "z", "scale", "billboard", "src", "color", "opacity"), ("id",))
        _text(layer["id"], at + ".id", 64)
        if "role" in layer:
            _choice(layer["role"], at + ".role", LAYER_ROLES)
        for key in ("x", "y", "z"):
            if key in layer:
                _number(layer[key], f"{at}.{key}", -REACH, REACH)
        if "scale" in layer:
            _number(layer["scale"], at + ".scale", 0.01, 100)
        if "billboard" in layer and layer["billboard"] != "full":
            _flag(layer["billboard"], at + ".billboard")
        if "src" in layer:
            _text(layer["src"], at + ".src", 2048, SOURCE)
        if "color" in layer:
            _color(layer["color"], at + ".color")
        if "opacity" in layer:
            _number(layer["opacity"], at + ".opacity", 0, 1)


def _props(value, path):
    for at, prop in _items(value, path, MAX_PROPS):
        prop = _fields(prop, at, ("id", "shape", "radius", "height", "size", "position", "color", "contact"), ("id",))
        _text(prop["id"], at + ".id", 64)
        if "shape" in prop:
            _choice(prop["shape"], at + ".shape", ("cylinder", "box"))
        for key in ("radius", "height"):
            if key in prop:
                _number(prop[key], f"{at}.{key}", 0.001, REACH)
        if "size" in prop:
            _vector(prop["size"], at + ".size", 3, 0.001, REACH)
        if "position" in prop:
            _vector(prop["position"], at + ".position", 3, -REACH, REACH)
        if "color" in prop:
            _color(prop["color"], at + ".color")
        if "contact" in prop:
            _flag(prop["contact"], at + ".contact")


def _code(value, path, codes):
    if not isinstance(value, str) or not CAST_CODE.fullmatch(value):
        _fail(path, "must be a cast code such as @CAST-01")
    if codes is not None and value not in codes:
        _fail(path, f"names {value}, which is not on the cast sheet")


def validate(plan, codes=None):
    """Raise DRAMA_VALIDATION_FAILED unless plan is a previs plan the stage can play (plan.js) within 64 KB.

    codes: the production's cast codes (cast_options); plan.code and every plan.cast[].code must be one of them, and
    nobody stands on set twice. None skips that lookup (the format alone)."""
    try:
        size = len(canonical(plan).encode("utf-8"))
    except (TypeError, ValueError):
        size = None
    if size is None:
        story.invalid("plan must be JSON.")
    if size > MAX_BYTES:
        story.invalid(f"plan is {size} bytes; a previs plan holds at most {MAX_BYTES} bytes (64 KB).")
    plan = _fields(plan, "plan", PLAN_KEYS, REQUIRED)
    for key, options in (("set", SETS), ("move", MOVES), ("lens", LENSES), ("action", ACTIONS), ("facing", FACINGS),
                         ("mood", MOODS), ("seconds", DURATIONS)):
        _choice(plan[key], "plan." + key, options)
    if "keys" in plan:
        _keys(plan["keys"], "plan.keys")
    if "easing" in plan:
        easing = plan["easing"]
        if not isinstance(easing, list) or len(easing) != 4:
            _fail("plan.easing", "must be a cubic-bezier [x1, y1, x2, y2]")
        for index, (low, high) in enumerate(((0, 1), (-1, 2), (0, 1), (-1, 2))):
            _number(easing[index], f"plan.easing[{index}]", low, high)
    if "mark" in plan:
        _vector(plan["mark"], "plan.mark", 2, -REACH, REACH, ranged=True)
    if "turn" in plan:
        _number(plan["turn"], "plan.turn", -720, 720, ranged=True)
    if "figure" in plan:
        _figure(plan["figure"], "plan.figure")
    named = []
    if "code" in plan:
        _code(plan["code"], "plan.code", codes)
        named.append(plan["code"])
    for at, member in _items(plan.get("cast", []), "plan.cast", MAX_CAST):
        member = _fields(member, at, ("mark", "turn", "figure", "acts", "code"))
        if "mark" in member:
            _vector(member["mark"], at + ".mark", 2, -REACH, REACH, ranged=True)
        if "turn" in member:
            _number(member["turn"], at + ".turn", -720, 720, ranged=True)
        if "figure" in member:
            _figure(member["figure"], at + ".figure")
        if "acts" in member:
            _acts(member["acts"], at + ".acts")
        if "code" in member:
            _code(member["code"], at + ".code", codes)
            named.append(member["code"])
    twice = sorted({code for code in named if named.count(code) > 1})
    if twice:
        story.invalid(f"{', '.join(twice)} can stand on set only once per shot.")
    if "acts" in plan:
        _acts(plan["acts"], "plan.acts")
    if "pins" in plan:
        _pins(plan["pins"], "plan.pins")
    if "use" in plan:
        _use(plan["use"], "plan.use")
    if "fix" in plan and not isinstance(plan["fix"], bool):
        for key, value in _fields(plan["fix"], "plan.fix", ("ground", "slide", "penetration", "retime")).items():
            _flag(value, "plan.fix." + key)
    if "layers" in plan:
        _layers(plan["layers"], "plan.layers")
    if "beacon" in plan:
        _flag(plan["beacon"], "plan.beacon")
    if "props" in plan:
        _props(plan["props"], "plan.props")
    if "presentation" in plan:
        _choice(plan["presentation"], "plan.presentation", ("rehearsal",))
    if "demo" in plan:
        _text(plan["demo"], "plan.demo", 64)


def base_revision(body, if_match=None):
    """The revision a write is based on: body baseRevision and/or an If-Match header ("3" or 3), which must agree."""
    named = []
    if "baseRevision" in body:
        value = body["baseRevision"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            story.invalid("baseRevision must be a whole number of at least 0.")
        named.append(value)
    if if_match is not None:
        match = re.fullmatch(r'\s*(?:"(\d{1,15})"|(\d{1,15}))\s*', if_match)
        if not match:
            story.invalid('If-Match must name one plan revision, such as "3".')
        named.append(int(match[1] or match[2]))
    if not named:
        story.invalid("Send the plan revision you edited as baseRevision or an If-Match header (0 before the first save).")
    if len(set(named)) > 1:
        story.invalid("If-Match and baseRevision name different revisions.")
    return named[0]


# ---------- writing ----------

def put(conn, slug, identifier, plan, revision, actor_id, codes=None):
    """Store a shot's plan (None clears it) when revision is the stored revision, in the caller's transaction.

    Shared by the route and by anything that writes the plan for a person who decided it (an adopted crew proposal
    carries its baseRevision, SPEC_20 decision 5). Returns the stored record; a plan equal to the stored one is not
    written again and keeps its revision."""
    if plan is not None:
        validate(plan, {option["code"] for option in cast_options(conn, slug)} if codes is None else codes)
    with conn.cursor() as cur:  # the first save of a shot has no row to lock yet
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("previs-plan:" + identifier,))
    meta = story.record(conn, "meta_" + identifier, required=False, lock=True) or {}
    current = stored(meta)
    if revision != current["planRevision"]:
        raise story.StoryError(409, CONFLICT, f"This shot's 3D plan has changed since revision {revision} (it is now revision "
                               f"{current['planRevision']}). Reload it before saving.",
                               details={"currentRevision": current["planRevision"], "baseRevision": revision})
    if canonical(plan) == canonical(current["plan"]):
        return current
    saved = {"plan": plan, "planRevision": current["planRevision"] + 1, "updatedAt": story.now(), "updatedBy": actor_id}
    story.store(conn, "meta_" + identifier, "shot_meta", {**meta, KEY: saved}, slug)
    return saved


def route(conn, me, method, slug, identifier, body, headers=None):
    """GET or PUT /shots/{shotId}/previs-plan; the dispatcher has found the shot and checked the crew member."""
    options = cast_options(conn, slug)
    if method == "PUT":
        unknown = sorted(set(body) - {"plan", "baseRevision"})
        if unknown:
            story.invalid("Unknown previs plan fields: " + ", ".join(unknown) + ".")
        if "plan" not in body:
            story.invalid("plan is required (null clears the stored plan).")
        revision = base_revision(body, headers.get("If-Match") if headers is not None else None)
        state = put(conn, slug, identifier, body["plan"], revision, me.actor_id, {option["code"] for option in options})
    else:
        state = stored(story.shot_meta(conn, identifier))
    return {"shotId": identifier, **state, "castOptions": options}
