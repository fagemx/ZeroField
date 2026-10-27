"""SPEC_19 R17: the cuts of an episode film and their continuity checks.

A cut is two neighbouring shots of the film. The order is the film's (``film_plan``): shots sorted by shot index, every
slate shot (``cinema-studio``) plus each lab clip (``openjutsu-lab``) once it is adopted, because a lab clip only joins
the film then. Every neighbouring pair is listed; only a pair whose two shots both have an adopted take can be checked.

The check itself is ``take_grader``'s second question (record kind ``cut_check``): the outgoing take's out frame and the
incoming take's in frame side by side, sent to the Continuity Supervisor through the same queue and GPU hand-off as a
take grade. Its key is both shots, both take URLs and both cut points, so adopting another take or changing a trim on
either side leaves the cut without a result (``state: "none"``); going back to the earlier take and trim shows the earlier
result again. A check is information: it never blocks adoption or export (SPEC_19 fixed decision 13).

Routes, served from ``story_openapi.py``'s episode branch through :func:`dispatch` (the drop-in handler). The Story
envelope ``{code: 0, msg: "success", data}`` wraps both results; errors use the existing codes:

``GET /episodes/{id}/cuts`` -> :func:`list_cuts`, open to every member who can read the production.
    404 DRAMA_NOT_FOUND  the episode does not exist (raised by ``story.episode`` before this module runs).

``POST /episodes/{id}/cut-checks`` body ``{pairs?: [[fromShotId, toShotId], ...]}`` -> :func:`queue_cut_checks`.
    409 DRAMA_OPERATION_NOT_ALLOWED  read-only crew member, or not an active member of this production (403 from
                                     ``story.authorize`` when the membership check refuses).
    422 DRAMA_VALIDATION_FAILED      pairs is not a non-empty list of [fromShotId, toShotId] pairs (at most 200), a pair is
                                     not two neighbouring shots of this episode, a named cut's take is not a video of this
                                     production, or the production masks numbers (frames may not leave).
    409 DRAMA_STAGE_PRECONDITION     a named pair does not have an adopted take on both sides.
    After a 200 with ``queued > 0`` the route calls ``take_grader.kick()`` once the transaction has committed.

Nothing here commits; the Story handler commits or rolls back the request.
"""
from __future__ import annotations

import re

from project_assistant import take_grader as grader
from project_docs import story_openapi as story
from project_docs.story_adoption import ADOPTED

SLATE = "cinema-studio"
MAX_PAIRS = 200


def _film_order(shot):
    # The same natural shot-index order as story_openapi.film_plan (S2 before S10).
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold()) for part in re.split(r"(\d+)", str(shot["shotIndex"])))


def _adopted(shot):
    return shot.get("reviewStatus") in ADOPTED and bool(shot.get("selectedVideoUrl"))


def sequence(conn, ep):
    """The episode's shots in film order: every slate shot and each adopted lab clip."""
    return sorted((s for s in story.shots(conn, ep) if s["tabKey"] == SLATE or _adopted(s)), key=_film_order)


def _production_asset(slug, url):
    return bool(re.fullmatch(r"/projects/api/" + re.escape(slug) + r"/assets/pa_[0-9a-f]{32}", url or ""))


def _out_at(shot):
    """The trim's out point in seconds, or None: the take plays to its own end."""
    out = (shot.get("trim") or {}).get("out")
    return None if out is None else float(out)


def _in_at(shot):
    return float((shot.get("trim") or {}).get("in") or 0)


def _blocker(slug, shot):
    if not _adopted(shot):
        return "not_adopted"
    if not _production_asset(slug, shot["selectedVideoUrl"]):
        return "external_take"  # adopted, but not a video asset of this production: no frames can be read from it
    return None


def cuts(conn, ep):
    """Every neighbouring pair of the episode film, in film order (see the module docstring for the item shape)."""
    slug, shots = ep["slug"], sequence(conn, ep)
    checks = {record["checkId"]: record for record in story.records(conn, grader.CUT_KIND, slug)}
    result = []
    for index, (before, after) in enumerate(zip(shots, shots[1:])):
        out_ok, in_ok = _adopted(before), _adopted(after)
        cut = {"index": index, "fromShotId": before["shotId"], "toShotId": after["shotId"],
               "fromShotIndex": before["shotIndex"], "toShotIndex": after["shotIndex"],
               "fromTakeUrl": before["selectedVideoUrl"] if out_ok else None,
               "toTakeUrl": after["selectedVideoUrl"] if in_ok else None,
               "outAt": _out_at(before) if out_ok else None, "inAt": _in_at(after) if in_ok else None}
        blocked = [{"shotId": shot["shotId"], "reason": reason}
                   for shot, reason in ((before, _blocker(slug, before)), (after, _blocker(slug, after))) if reason]
        cut["checkable"] = not blocked
        cut["blockedBy"] = blocked
        cut["check"] = grader.cut_check_view(checks.get(grader.cut_record_id(cut)) if not blocked else None)
        result.append(cut)
    return result


def _episode(conn, slug, episode_id):
    ep = story.episode(conn, episode_id)
    if ep["slug"] != slug:
        raise story.StoryError(404, "DRAMA_NOT_FOUND", "Episode not found.")
    return ep


def list_cuts(conn, slug, episode_id):
    """GET /episodes/{id}/cuts -> ``{"items": [cut, ...]}``, one item per neighbouring pair of shots in film order.

    cut = {index, fromShotId, toShotId, fromShotIndex, toShotIndex,
           fromTakeUrl, toTakeUrl,     # the adopted take on that side, or None when that side has none
           outAt,                      # outgoing trim out point (seconds); None = the take's own end, or no adopted take
           inAt,                       # incoming trim in point (seconds, 0 untrimmed); None without an adopted take
           checkable,                  # both sides have an adopted video take of this production
           blockedBy: [{shotId, reason: "not_adopted" | "external_take"}],   # empty when checkable
           check: {state: "none" | "queued" | "done" | "failed", checkId, score, passed, issues: [str], feedback,
                   frameSheetUrl, frames: {outSeconds, inSeconds}, error, auto, requestedAt, checkedAt}}

    ``check`` always has every key; what does not apply is None (issues []). An uncheckable cut is always ``none``.
    Read access is the route's ``story.authorize``; this function does not check membership.
    """
    return {"items": cuts(conn, _episode(conn, slug, episode_id))}


def parse_pairs(value):
    """[(fromShotId, toShotId), ...] in request order without repeats; None (omitted or null) means every cut."""
    if value is None:
        return None
    if (not isinstance(value, list) or not 1 <= len(value) <= MAX_PAIRS
            or not all(isinstance(p, list) and len(p) == 2 and all(isinstance(s, str) and s for s in p) for p in value)):
        story.invalid(f"pairs must be a list of 1 to {MAX_PAIRS} [fromShotId, toShotId] pairs; omit it to check every unchecked cut.")
    return list(dict.fromkeys(tuple(p) for p in value))


def _enqueue_all(conn, slug, ep, chosen, actor_id, *, auto=False, strict=True):
    """Queue each cut; returns (queued records, skipped). strict: a cut that cannot be sent is a 422, else it is skipped."""
    queued, skipped = [], []
    for cut in chosen:
        try:
            queued.append(grader.enqueue_cut(conn, slug, ep["episodeId"], cut, actor_id, auto=auto))
        except grader.GradeError as exc:
            if strict:
                story.invalid(f"{cut['fromShotIndex']} -> {cut['toShotIndex']}: {exc}")
            skipped.append({"fromShotId": cut["fromShotId"], "toShotId": cut["toShotId"], "message": str(exc)})
    return queued, skipped


def queue_cut_checks(conn, me, slug, episode_id, pairs=None):
    """POST /episodes/{id}/cut-checks -> ``{"queued": n, "checkIds": [...], "skipped": [{fromShotId, toShotId, message}]}``.

    ``pairs`` is the request's ``pairs`` value as sent (:func:`parse_pairs` validates it). Omitted: every checkable cut whose
    check is ``none`` (never checked for these takes and points, or abandoned), skipping any whose take cannot be sent.
    Given: exactly those cuts, which must be neighbours of this episode with adopted takes on both sides; one already in
    flight is returned as it is, and one already done or failed is checked again. ``queued`` counts every cut now in the
    queue. Permission follows the take grade route: read-only crew members cannot queue. The caller commits, then calls
    ``take_grader.kick()``.
    """
    from project_assistant import privacy
    if not me.can_write:
        raise story.StoryError(409, "DRAMA_OPERATION_NOT_ALLOWED", "Read-only crew members cannot queue cut checks.")
    story.authorize(conn, me, slug, write=True)
    ep = _episode(conn, slug, episode_id)
    wanted = parse_pairs(pairs)
    listed = cuts(conn, ep)
    if wanted is None:
        chosen = [cut for cut in listed if cut["checkable"] and cut["check"]["state"] == "none"]
    else:
        by_pair = {(cut["fromShotId"], cut["toShotId"]): cut for cut in listed}
        unknown = [pair for pair in wanted if pair not in by_pair]
        if unknown:
            story.invalid("Each pair must be two neighbouring shots of this episode, in film order: "
                          + ", ".join(" -> ".join(pair) for pair in unknown[:5]))
        chosen = [by_pair[pair] for pair in wanted]
        blocked = [cut for cut in chosen if not cut["checkable"]]
        if blocked:
            raise story.StoryError(409, "DRAMA_STAGE_PRECONDITION", "Adopt a take on both sides of a cut before checking it: "
                                   + ", ".join(f"{c['fromShotIndex']} -> {c['toShotIndex']}" for c in blocked[:5]))
    if chosen and privacy.mode(conn, slug) != "full_access":
        story.invalid(grader.MASKED)
    queued, skipped = _enqueue_all(conn, slug, ep, chosen, me.actor_id, strict=wanted is not None)
    return {"queued": len(queued), "checkIds": [record["checkId"] for record in queued], "skipped": skipped}


def on_adoption_changed(conn, slug, shot_id, owner_id):
    """Queue the (at most two) cuts next to a shot whose adoption or trim just changed, when auto grading is on.

    SPEC_19 decision 8: the adoption and trim routes call this (story_openapi.auto_cut_checks). Off (the default ``auto_grade_takes`` setting):
    nothing happens. On: each neighbouring cut that is checkable and has no result for its current takes and points is
    queued as an automatic check; a cut whose take cannot be sent, or a masked production, is skipped quietly (as
    ``take_grader.on_take`` does). Returns how many were queued; the caller commits, then calls ``take_grader.kick()``.
    """
    from project_assistant import privacy
    if not grader.auto_enabled(conn, slug) or privacy.mode(conn, slug) != "full_access":
        return 0
    meta = story.shot_meta(conn, shot_id)
    try:
        ep = _episode(conn, slug, meta.get("episodeId") or f"ep_{slug}_01")
    except story.StoryError:
        return 0
    chosen = [cut for cut in cuts(conn, ep) if shot_id in (cut["fromShotId"], cut["toShotId"])
              and cut["checkable"] and cut["check"]["state"] == "none"]
    return len(_enqueue_all(conn, slug, ep, chosen, owner_id, auto=True, strict=False)[0])


def dispatch(conn, me, method, tail, ep, body, actions):
    """Drop-in for story_openapi's episode branch (after ``authorize``); None when the route is not a cut route.

        result = story_cuts.dispatch(conn, me, method, tail, ep, body, actions)
        if result is not None:
            return result
    """
    if tail == "cuts" and method == "GET":
        return list_cuts(conn, ep["slug"], ep["episodeId"])
    if tail == "cut-checks" and method == "POST":
        result = queue_cut_checks(conn, me, ep["slug"], ep["episodeId"], body.get("pairs"))
        if result["queued"]:
            actions.append(grader.kick)
        return result
    return None
