"""Per-shot trim: frame-accurate in/out points inside the selected take.

A trim lives in the shot's story meta (record ``meta_<shotId>``) next to the URL of the take it was cut for. Picking a
take or re-shooting resets it; the URL covers every other way a take can change (a sheet edit), which then reads back
as untrimmed instead of cutting a different clip. Film export receives the trims as plain data; the FFmpeg worker
never imports this module.
"""
from __future__ import annotations

import math

from project_docs import story_openapi as story

MIN_SPAN = 0.04     # seconds: at least one frame at 24 fps
MAX_SECONDS = 600
UNTRIMMED = {"in": 0, "out": None}


def _seconds(body, key):
    value = body.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        story.invalid(f"{key} must be a number of seconds.")
    try:
        number = float(value)
    except OverflowError:
        number = math.inf
    if not math.isfinite(number):
        story.invalid(f"{key} must be a finite number of seconds.")
    return number


def parse(body):
    """Validated {'in', 'out'}; omitted keys mean 0 and null, so an empty body clears the trim."""
    start = _seconds(body, "in") if "in" in body else 0.0
    end = None if body.get("out") is None else _seconds(body, "out")
    if not 0 <= start <= MAX_SECONDS:
        story.invalid(f"in must be between 0 and {MAX_SECONDS} seconds.")
    # The tolerance keeps a decimal literal such as in 1 / out 1.04 on the invalid side of "out > in + 0.04".
    if end is not None and not start + MIN_SPAN + 1e-9 < end <= MAX_SECONDS:
        story.invalid(f"out must be null or between in + {MIN_SPAN} and {MAX_SECONDS} seconds.")
    return {"in": start, "out": end}


def take_url(row):
    """URL of the video currently selected in a shot row (None without one)."""
    try:
        return story.media_url(row["cells"][story.media_column(row, "video")])
    except story.StoryError:
        return None


def view(meta, selected_video_url):
    """The payload's trim: the saved one while its take is still the selected one, otherwise untrimmed."""
    saved = meta.get("trim")
    if isinstance(saved, dict) and saved.get("takeUrl") == selected_video_url:
        return {"in": saved.get("in", 0), "out": saved.get("out")}
    return dict(UNTRIMMED)


def strip(meta):
    return {key: value for key, value in meta.items() if key != "trim"}


def set_trim(conn, slug, identifier, row, body):
    """Replace the shot's trim (PUT semantics); the untrimmed value removes it."""
    trim = parse(body)
    meta = story.record(conn, "meta_" + identifier, required=False, lock=True) or {}
    if trim == UNTRIMMED and "trim" not in meta:
        return
    meta = strip(meta)
    if trim != UNTRIMMED:
        meta["trim"] = {**trim, "takeUrl": take_url(row)}
    story.store(conn, "meta_" + identifier, "shot_meta", meta, slug)


def reset(conn, slug, identifier):
    """A newly selected or re-shot take starts untrimmed, even when the render happens to be the same asset."""
    meta = story.record(conn, "meta_" + identifier, required=False, lock=True)
    if meta and "trim" in meta:
        story.store(conn, "meta_" + identifier, "shot_meta", strip(meta), slug)


def film_trims(clips):
    """One entry per film clip: the shot's {'in', 'out'}, or None when the whole clip plays.

    Only a shot's own take is ever cut; the previs standing in for a take that has not been shot is not.
    """
    result = []
    for shot, url in clips:
        trim = shot.get("trim") or UNTRIMMED
        cut = url == shot.get("selectedVideoUrl") and (trim.get("in") or trim.get("out") is not None)
        result.append({"in": trim.get("in") or 0, "out": trim.get("out")} if cut else None)
    return result


def film_rows(job):
    """Rows for the FFmpeg worker; jobs queued before trims existed have no ``trims`` and play whole."""
    trims = job.get("trims") or []
    return [{"row_id": str(i), "cells": [url], **({"trim": trims[i]} if i < len(trims) and trims[i] else {})}
            for i, url in enumerate(job["urls"])]
