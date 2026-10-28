"""Generation options of one asset or shot: the workflow cards it can use, whether each can run now, and what recent runs say about time.

Read-only. Nothing here queues work, prices a job, reserves budget or contacts a provider, and nothing it returns is a
credential, an endpoint or an environment name: a card that cannot run says why with a short code.
"""
from __future__ import annotations

import math
from datetime import datetime
from statistics import median

from project_assistant import limb_worker as worker, privacy
from project_docs import story_openapi as story

DEFAULT_CARDS = {"image": "flux-soul-cast", "video": "ltx25-cinema"}  # what the studio generates with until another app is chosen
SHOT_IMAGE_CARD = "flux-reference-key"  # SPEC_21: a first frame carries the pictures of the assets it names
ASSET_SCOPES = {"CHARACTER": "CHARACTER", "SCENE": "SCENE_PROP", "PROP": "SCENE_PROP"}  # asset type -> usageScope
RATIO_FIELDS = ("aspect_ratio", "ratio")
SAMPLE_WINDOW, MIN_SAMPLES = 20, 3

# Last runs per card of one project. Allocation jobs run several cards in one task, so their time is not one card's.
RECENT_RUNS = """
SELECT card_id, created, finished FROM (
    SELECT data->'_job'->'card'->>'card_id' AS card_id, data->>'createdAt' AS created, data->>'finishedAt' AS finished,
           row_number() OVER (PARTITION BY data->'_job'->'card'->>'card_id' ORDER BY data->>'finishedAt' DESC) AS rank_in_card
      FROM projectops.story_record
     WHERE kind = 'task' AND project_slug = %s AND data->>'status' = 'SUCCEEDED'
       AND data->'_job'->'card'->>'card_id' IS NOT NULL AND data->'_job'->'allocation' IS NULL
       AND data->>'finishedAt' IS NOT NULL) runs
 WHERE rank_in_card <= %s"""


def declared_scopes(card):
    """The usage_scopes a card declares in its engine_config (the card loader keeps no other custom key).

    None when it declares none (missing, empty or malformed): such a card is offered in every scope."""
    scopes = (card.get("engine_config") or {}).get("usage_scopes")
    return {str(scope).upper() for scope in scopes} or None if isinstance(scopes, (list, tuple)) else None


def in_scope(card, scope):
    declared = declared_scopes(card)
    return declared is None or scope in declared


def tier_of(card):
    profile = worker.card_execution_profile(card)
    if profile["driver"] == "comfy_router":
        return "router"
    return "open_weights" if profile["driver"] == "comfy_local" and profile["tier"] == "open_weights" else "closed"


def availability(card, item, policy, privacy_mode):
    """(configured, reason); reason is a short code. Configuration only: no health probe, no network."""
    try:
        worker.enforce_card_policy(card, policy)
    except worker.WorkerError:
        return False, "blocked_by_policy"
    if privacy_mode == "mask_numbers" and worker.card_execution_profile(card)["driver"] != "comfy_local":
        return False, "blocked_by_privacy"
    return (True, None) if item["configuration"]["configured"] else (False, "not_configured")


def slot_params(card):
    """{"aspectRatio" | "resolution": {"key", "options"}}: the visible inputs a generation bar can set, the modelParams key
    (nodeId.fieldName) that sets each, and the allowed values of a LIST input."""
    found = {}
    for node in card["nodes"]:
        field = node["fieldName"]
        name = "aspectRatio" if node.get("slot") == "aspect_ratio" or field in RATIO_FIELDS else "resolution" if field == "resolution" else None
        if name and not node.get("hidden") and name not in found:
            found[name] = {"key": f"{node['nodeId']}.{field}", "options": list(node["options"]) if node["fieldType"] == "LIST" else None}
    return found


def slots_of(params):
    slots = {}
    if "aspectRatio" in params:
        slots["aspectRatio"] = True
    if "resolution" in params:
        slots["resolution"] = params["resolution"]["options"] or True
    return slots


def elapsed(created, finished):
    """Seconds from submission to completion (queue time included); None for a record that cannot say."""
    try:
        seconds = (datetime.fromisoformat(finished) - datetime.fromisoformat(created)).total_seconds()
    except (TypeError, ValueError):
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def estimates(conn, slug):
    """{card_id: {"seconds", "samples"}} for the cards this project ran successfully at least MIN_SAMPLES times lately.

    The median of the last SAMPLE_WINDOW runs. It includes time spent queued, which is why the sample count is shown; it is
    never below one second.
    """
    with conn.cursor() as cur:
        cur.execute(RECENT_RUNS, (slug, SAMPLE_WINDOW))
        rows = cur.fetchall()
    samples = {}
    for card_id, created, finished in rows:
        seconds = elapsed(created, finished)
        if seconds is not None:
            samples.setdefault(card_id, []).append(seconds)
    return {card_id: {"seconds": max(1, int(median(values) + 0.5)), "samples": len(values)}
            for card_id, values in samples.items() if len(values) >= MIN_SAMPLES}


def style_of(conn, slug, entity, identifier, requested):
    """The global style of the episode the target belongs to: the shot's own episode, the asked one, else the first."""
    if entity == "shot":
        wanted = story.shot_meta(conn, identifier).get("episodeId", f"ep_{slug}_01")
        ep = next((e for e in story.episodes(conn, slug) if e["episodeId"] == wanted), None)
    elif requested:
        ep = story.episode(conn, requested)
        if ep["slug"] != slug:
            raise story.StoryError(404, "DRAMA_NOT_FOUND", "Episode not found.")
    else:
        ep = next(iter(story.episodes(conn, slug)), None)
    settings = (ep or {}).get("settings")
    chosen = next((s for s in story.STYLES if s["stylePresetId"] == str((settings or {}).get("stylePresetId", ""))), story.STYLES[0])
    return {"stylePresetId": chosen["stylePresetId"], "name": chosen["name"]}


def default_card(entity, kind):
    """The card the studio prefers: a shot's first frame the reference card, an asset's picture and a shot's video the
    DEFAULT_CARDS ones."""
    return SHOT_IMAGE_CARD if entity == "shot" and kind == "image" else DEFAULT_CARDS[kind]


def fallback_card(entity, kind):
    """The card a generation request without an appCode uses: the preferred one while it is registered, else the
    studio's image or video card."""
    wanted = default_card(entity, kind)
    return wanted if any(card["card_id"] == wanted for card in worker.openapi_list_cards()) else DEFAULT_CARDS[kind]


def describe(conn, slug, identifier, entity, row, query):
    """GET /assets/{id}/generation-options and /shots/{id}/generation-options.

    A shot lists its video cards; ``?kind=image`` lists the cards of its first frame (SPEC_21: the reference card first)."""
    kind = "image" if entity == "asset" else query.get("kind") or "video"  # an asset gets a reference image, a shot a video
    if kind not in ("image", "video"):
        story.invalid("kind must be image or video.")
    scope = ASSET_SCOPES.get(story.asset_view(slug, row)["type"]) if entity == "asset" else None
    policy, privacy_mode, measured = story.production_policy(conn, slug), privacy.mode(conn, slug), estimates(conn, slug)
    listed, seen = [], set()
    for card, item in story.catalog_entries():
        if card["output_mode"] != kind or card["card_id"] in seen or (scope and not in_scope(card, scope)):
            continue
        seen.add(card["card_id"])
        configured, reason = availability(card, item, policy, privacy_mode)
        params = slot_params(card)
        app = {"appCode": item["appCode"], "name": card["label"], "tier": tier_of(card), "configured": configured, "reason": reason,
               "outputs": ["REFERENCE" if entity == "asset" else "IMAGE" if kind == "image" else "VIDEO"]}
        if params:
            app["slots"], app["slotParams"] = slots_of(params), params
        app |= {"estimate": measured.get(card["card_id"]), "quotable": item["driver"] == "comfy_router"}
        listed.append((card["card_id"], app))
    apps = [app for _, app in listed]
    preferred = next((app for wanted in (default_card(entity, kind), DEFAULT_CARDS[kind])
                      for card_id, app in listed if card_id == wanted and app["configured"]), None)
    default = preferred or next((app for app in apps if app["configured"]), None)
    return {"apps": apps, "defaultAppCode": default["appCode"] if default else None,
            "style": style_of(conn, slug, entity, identifier, query.get("episodeId"))}
