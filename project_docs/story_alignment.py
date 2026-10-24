"""Read-only script -> shot alignment for the Story screen.

``build_shots`` pairs beat i of scene s with the i-th cinema-studio shot whose meta.sceneId is s, in sheet-row
order. This module replays that rule without writing anything: it shows which shot each screenplay beat became,
and which shots a script draft would touch. It never calls a model and never persists a draft.
"""
from __future__ import annotations

import re

from project_docs import story_openapi as story
from project_docs.story_adaptation import BREAKDOWN_MODES, scene_shot_beats

ROUTE = re.compile(r"/episodes/([^/]+)/(script-alignment|script-impact)")
PROMPT_LIMIT = 10000  # build_shots cuts a shot prompt here


def normal(text):
    """Comparison form: @CODE asset references dropped, whitespace collapsed, case ignored."""
    return re.sub(r"\s+", " ", story.ASSET_RE.sub(" ", text or "")).strip().casefold()


def matches(beat, description):
    """A shot still follows its beat while its prompt starts with the beat's text."""
    wanted, prompt = normal(beat), normal(description)
    if not wanted:
        return not prompt
    # A beat past the prompt limit is clipped (possibly mid reference), so only the head can agree.
    return prompt.startswith(wanted) or (len(description) >= PROMPT_LIMIT and wanted.startswith(prompt[:-16]))


def breakdown_mode(ep):
    mode = ep.get("breakdownMode", ep.get("settings", {}).get("breakdownMode", "auto"))
    return mode if mode in BREAKDOWN_MODES else "auto"


def scene_plans(scene_list, mode):
    """[(scene, beats)] exactly as build_shots derives them."""
    return [(scene, scene_shot_beats(scene["content"], mode) or [scene["title"]]) for scene in scene_list]


def locate(text, plans):
    """1-based line of every beat's first line (None when absent), by a forward search through the text."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    row = col = 0

    def find(needle):
        for at in range(row, len(lines)):
            hit = lines[at].find(needle, col if at == row else 0)
            if hit >= 0:
                return at, hit
        return None

    result = []
    for _, beats in plans:
        numbers = []
        for beat in beats:
            first = next((line.strip() for line in beat.splitlines() if line.strip()), "")
            hit = find(first) if first else None
            if hit:
                row, col = hit[0], hit[1] + len(first)
            elif ": " in first and (hit := find(first.split(": ", 1)[1].strip())):
                # A labelled beat ("Close-up detail: ...") is found by its text; sibling beats share that line.
                row, col = hit
            numbers.append(hit[0] + 1 if hit else None)
        result.append(numbers)
    return result


def align(plans, text, shots):
    """([scene entries], [orphan shots]) of a script against the episode's current shots."""
    slate = [s for s in shots if s["tabKey"] == "cinema-studio"]
    numbers, paired, result = locate(text, plans), set(), []
    for (scene, beats), lines in zip(plans, numbers):
        mine = [s for s in slate if s.get("sceneId") == scene["sceneId"]]
        items = []
        for index, beat in enumerate(beats):
            shot = mine[index] if index < len(mine) else None
            paired.update([shot["shotId"]] if shot else [])
            items.append({"index": index, "text": beat, "line": lines[index],
                          "shotId": shot["shotId"] if shot else None, "shotIndex": shot["shotIndex"] if shot else None,
                          "rowId": shot["rowId"] if shot else None,
                          "state": "no_shot" if not shot else "linked" if matches(beat, shot["description"]) else "changed"})
        result.append({"sceneId": scene["sceneId"], "sceneIndex": scene["sceneIndex"], "title": scene["title"], "beats": items})
    # Template or hand-added rows without a scene were never built from the script and cannot lose their beat.
    orphans = [{"shotId": s["shotId"], "shotIndex": s["shotIndex"], "rowId": s["rowId"], "sceneId": s["sceneId"]}
               for s in slate if s.get("sceneId") and s["shotId"] not in paired]
    return result, orphans


def facing(aligned):
    """shotId -> (normalised beat text it now faces, state); an orphan faces nothing."""
    scenes_out, orphans = aligned
    found = {o["shotId"]: (None, "orphan") for o in orphans}
    for scene in scenes_out:
        for beat in scene["beats"]:
            if beat["shotId"]:
                found[beat["shotId"]] = (normal(beat["text"]), beat["state"])
    return found


def affected(before, after, shots):
    """Shots (in sheet order) that the draft leaves out of step: facing a new beat their prompt no longer follows, or none."""
    old, new = facing(before), facing(after)
    hit = {shot for shot, (text, state) in new.items() if state != "linked" and old.get(shot, (None, None))[0] != text}
    return [s["shotId"] for s in shots if s["shotId"] in hit]


def alignment(conn, ep):
    content = story.script(conn, ep)
    scenes_out, orphans = align(scene_plans(story.scenes(conn, ep), breakdown_mode(ep)), content, story.shots(conn, ep))
    return {"scriptDirty": ep.get("confirmedHash") != story.digest(content), "scenes": scenes_out, "orphans": orphans}


def impact(conn, ep, draft):
    """The alignment of a draft that was not saved, plus the shots saving it would leave out of step."""
    mode, shots = breakdown_mode(ep), story.shots(conn, ep)
    before = align(scene_plans(story.scenes(conn, ep), mode), story.script(conn, ep), shots)
    drafted = [{**item, "sceneId": f"sc_{ep['slug']}_{ep['episodeIndex']:02d}_S{i:02d}", "episodeId": ep["episodeId"], "sceneIndex": i}
               for i, item in enumerate(story.scene_sections(draft), 1)]
    after = align(scene_plans(drafted, mode), draft, shots)
    return {"scriptDirty": ep.get("confirmedHash") != story.digest(draft), "scenes": after[0], "orphans": after[1],
            "affectedShotIds": affected(before, after, [s for s in shots if s["tabKey"] == "cinema-studio"])}


def dispatch(conn, me, method, path, body):
    """GET script-alignment and POST script-impact; None for any other request. Both only read."""
    match = ROUTE.fullmatch(path.rstrip("/"))
    if not match or (method, match[2]) not in (("GET", "script-alignment"), ("POST", "script-impact")):
        return None
    ep = story.episode(conn, match[1])
    story.authorize(conn, me, ep["slug"])
    if match[2] == "script-alignment":
        return alignment(conn, ep)
    if "scriptContent" not in body:
        story.invalid("scriptContent is required.")
    return impact(conn, ep, story.text(body, "scriptContent", maximum=500000))
