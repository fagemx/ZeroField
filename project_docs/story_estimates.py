"""Storyboard planning shared by the real build and its estimate.

build_shots() asks this module what to do with every beat of every scene, and POST /episodes/{id}/storyboard-estimates
asks the same question without writing: both cut the same beats, meet the same existing slate and apply the same
"keep the shots that exist, only add the missing beats" rule, so the numbers shown before a build are the numbers the
build produces. The estimate never writes, takes no lock beyond plain reads and never calls a model.
"""
from __future__ import annotations

import functools
import math
import re

from project_docs import repository as repo, story_openapi as story
from project_docs.doc_schema import doc_text
from project_docs.story_adaptation import BREAKDOWN_MODES, infer_shot_grammar, scene_shot_beats, script_medium_lens

ROUTE = re.compile(r"/episodes/([^/]+)/storyboard-estimates")
MAX_BUILD_SHOTS = 200  # a build refuses more beats than this
DEFAULT_MODES = ("auto", "scene", "cinematic")
MIN_TARGET, MAX_TARGET = 10, 1800


def beat_plans(scene_list, mode, only_scene=None):
    """[(scene, beats)] a build cuts the script into; a scene without any beat falls back to its title."""
    return [(scene, scene_shot_beats(scene["content"], mode) or [scene["title"]]) for scene in scene_list
            if not only_scene or scene["sceneId"] == only_scene]


def scene_steps(scene, beats, previous, rebuild=False):
    """(steps, surplus) for one scene; steps are (action, index, beat, shot).

    The scene's existing slate shots (previous: shot views) answer its first beats in sheet order: a normal build keeps them
    as they are, a one-scene rebuild rewrites them. Every later beat adds a shot. Slate shots beyond the last beat are the
    surplus: a build never deletes takes.
    """
    slate = [s for s in previous if s.get("sceneId") == scene["sceneId"] and s["tabKey"] == "cinema-studio"]
    steps = [(("rewrite" if rebuild else "keep"), index, beat, slate[index]) if index < len(slate) else ("add", index, beat, None)
             for index, beat in enumerate(beats)]
    return steps, slate[len(beats):]


@functools.lru_cache(maxsize=1)
def default_shot_seconds():
    """Planning seconds a shot gets from the shot grammar (4 s today); read from it, never copied."""
    return infer_shot_grammar("", 0, 1)["previsPlan"]["seconds"]


def planned_seconds(plan):
    """Planning seconds of a previs plan; a shot without a usable plan counts the default."""
    seconds = plan.get("seconds") if isinstance(plan, dict) else None
    usable = isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and math.isfinite(seconds) and seconds > 0
    return seconds if usable else default_shot_seconds()


def whole(number):
    number = round(number, 2)
    return int(number) if number == int(number) else number


def mode_estimate(scene_list, previous, medium, mode):
    """One breakdown mode against the current slate, as a whole-episode build would act."""
    plans = beat_plans(scene_list, mode)
    kept = new = 0
    seconds = 0
    for scene, beats in plans:
        steps, surplus = scene_steps(scene, beats, previous)
        for action, index, beat, shot in steps:
            if action == "add":
                new += 1
                seconds += planned_seconds(infer_shot_grammar(beat, index, len(beats), medium)["previsPlan"])
            else:
                kept += 1
                seconds += planned_seconds(shot.get("previsPlan"))
        kept += len(surplus)
        seconds += sum(planned_seconds(s.get("previsPlan")) for s in surplus)
    result = {"breakdownMode": mode, "shotCount": kept + new, "newShots": new, "keptShots": kept, "plannedSeconds": whole(seconds)}
    if sum(len(beats) for _, beats in plans) > MAX_BUILD_SHOTS:
        result["overLimit"] = True  # the build would refuse this mode
    return result


def parse_modes(body):
    modes = body.get("breakdownModes", list(DEFAULT_MODES))
    if not isinstance(modes, list) or not 1 <= len(modes) <= 16:
        story.invalid("breakdownModes must list between 1 and 16 breakdown modes.")
    if any(not isinstance(mode, str) or mode not in BREAKDOWN_MODES for mode in modes):
        story.invalid("Unknown breakdownMode.")
    return list(dict.fromkeys(modes))


def parse_target(body):
    value = body.get("targetSeconds")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not MIN_TARGET <= value <= MAX_TARGET:
        raise story.StoryError(400, "DRAMA_REQUEST_FAILED", f"targetSeconds must be a whole number of seconds between {MIN_TARGET} and {MAX_TARGET}.")
    return value


def estimate(conn, ep, body):
    modes, target = parse_modes(body), parse_target(body)
    if body.get("scriptContent") is not None:
        draft = story.text(body, "scriptContent", maximum=500000)  # an unsaved draft, converted as saving it would
        doc = story.script_doc(ep["slug"], draft) if draft.strip() else {"content": []}
    else:
        doc = repo.get_tab(conn, ep["slug"], ep["tabKey"])["doc"]
    scene_list, medium, previous = story.scenes_of_doc(ep, doc), script_medium_lens(doc_text(doc)), story.shots(conn, ep)
    return {"modes": [mode_estimate(scene_list, previous, medium, mode) for mode in modes], "targetSeconds": target}


def dispatch(conn, me, method, path, body):
    """POST /episodes/{id}/storyboard-estimates; None for any other request. Read-only, so crew viewers may ask too."""
    match = ROUTE.fullmatch(path.rstrip("/"))
    if not match or method != "POST":
        return None
    ep = story.episode(conn, match[1])
    story.authorize(conn, me, ep["slug"])
    return estimate(conn, ep, body)
