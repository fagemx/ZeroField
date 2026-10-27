"""RH STORY facade over the live production tabs and the Studio Card compiler.

Only API metadata is stored separately. Mutations run in the caller's transaction;
network/GPU work starts after commit and never holds a document lock.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import hmac
from http.client import HTTPSConnection
import ipaddress
import json
import os
import re
import secrets
import socket
import ssl
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from project_docs import blocks, markdown_import, media, repository as repo, service
from project_docs.doc_schema import column_ids, doc_text, new_id, node_text, validate_doc
from project_assistant import limb_worker as worker
from project_assistant.table_edits import _cell, cell_value, validate_value
from project_docs.story_adaptation import (adapt_source_to_script, source_mode, scene_shot_beats,
    infer_shot_grammar, extract_asset_details, BREAKDOWN_MODES, asset_code, screenplay_markdown,
    composition_lenses, choice_trace_input, compute_choice_contrast, propose_story_collisions,
    audit_narrative_voice, script_medium_lens)

BASE = "/aivideo/open/v1"
STAGES = ["PROJECT", "EPISODE", "SCRIPT", "ASSETS", "SCENES", "STORYBOARD", "SHOTS", "FILM_EXPORT"]
ALIASES = {"H3_SHORT_VIDEO_V3": "h3-short-video-v3", "H3_REF2VA_PASS1": "h3-reference",
           "SEEDANCE_2_FAST_MULTIMODAL_VIDEO": "seedance-20-pro", "H3_OPTIMIZE_4K": "h3-optimize",
           "LTX25_OPENJUTSU_V2V": "ltx25-openjutsu", "LTX25_CINEMA_SHOT": "ltx25-cinema",
           "FLUX3_SOUL_CAST": "flux-soul-cast", "NANO_PRO_G2_I2I_OFFICIAL": "flux-soul-cast",
           "LOCAL_SDXL_SMOKE": "local-smoke"}
# (name, sample slug): the samples ship with the UI build, served from static/projects/assets/style-samples/<slug>.svg
STYLE_SAMPLES = [("Sci-Fi Noir Anamorphic", "sci-fi-noir"), ("Cel-Shaded Anime Drama", "cel-shaded-anime"),
                 ("Dark Fantasy Concept", "dark-fantasy"), ("High-Contrast Neo-Noir", "neo-noir")]
STYLES = [{"stylePresetId": str(88123 + i), "name": name, "sampleImage": f"/projects/assets/style-samples/{slug}.svg"}
          for i, (name, slug) in enumerate(STYLE_SAMPLES)]
RATIOS = ["16:9", "9:16", "1:1", "21:9"]
USAGE_SCOPES = ("CHARACTER", "SCENE_PROP", "SCENE_PROP_EDIT", "FREE_CREATION_T2I", "FREE_CREATION_I2I")
LOOK_KINDS = ("OUTFIT", "POSE", "LOOK")
ASSET_RE = re.compile(r"@?\b((?:CAST|SET|LOC|PROP|STYLE)-\d+(?:[:#][a-z0-9_-]+)?)\b", re.I)
_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="story")
_PROCESS = uuid.uuid4().hex


class StoryError(ValueError):
    def __init__(self, status, code, message, details=None):
        super().__init__(message)
        self.status, self.code, self.details = status, code, details


def invalid(message):
    raise StoryError(422, "DRAMA_VALIDATION_FAILED", message)


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def record(conn, identifier, *, required=True, lock=False):
    with conn.cursor() as cur:
        cur.execute("SELECT data FROM projectops.story_record WHERE id=%s" + (" FOR UPDATE" if lock else ""), (identifier,))
        row = cur.fetchone()
    if not row and required:
        raise StoryError(404, "DRAMA_NOT_FOUND", "Resource not found.")
    return repo._loads(row[0]) if row else None


def store(conn, identifier, kind, data, slug=None, owner=None):
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO projectops.story_record(id,kind,project_slug,owner_id,data)
                       VALUES(%s,%s,%s,%s,%s::jsonb) ON CONFLICT(id) DO UPDATE
                       SET data=EXCLUDED.data, updated_at=NOW()""", (identifier, kind, slug, owner, repo._doc_param(data)))
    return data


def records(conn, kind, slug=None, owner=None):
    with conn.cursor() as cur:
        cur.execute("""SELECT data FROM projectops.story_record WHERE kind=%s
                       AND (%s::text IS NULL OR project_slug=%s)
                       AND (%s::uuid IS NULL OR owner_id=%s) ORDER BY id""", (kind, slug, slug, owner, owner))
        return [repo._loads(row[0]) for row in cur.fetchall()]


def remove(conn, identifier):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM projectops.story_record WHERE id=%s", (identifier,))


def page(items, query):
    try:
        limit = int(query.get("limit", "20"))
        if not 1 <= limit <= 100:
            raise ValueError()
        cursor = query.get("cursor")
        start = int(base64.urlsafe_b64decode(cursor.encode()).decode()) if cursor else 0
        if start < 0 or start > len(items):
            raise ValueError()
    except (ValueError, TypeError, UnicodeError):
        invalid("Use a valid cursor and limit between 1 and 100.")
    end = start + limit
    return {"items": items[start:end], "nextCursor": base64.urlsafe_b64encode(str(end).encode()).decode() if end < len(items) else None}


def text(body, key, default="", maximum=10000):
    value = body.get(key, default)
    if not isinstance(value, str) or len(value) > maximum:
        invalid(f"{key} must be text with at most {maximum} characters.")
    return value


def production_policy(conn, slug):
    saved = record(conn, "policy_" + slug, required=False) or {}
    return worker.effective_production_policy(saved.get("productionPolicy"))


def authorize(conn, me, slug, *, write=False):
    from project_assistant import orchestrator
    try:
        orchestrator.actor(conn, slug, me, write=write)
    except orchestrator.OrchestrationError as exc:
        raise StoryError(exc.status, "DRAMA_OPERATION_NOT_ALLOWED", str(exc)) from None


def authorize_card(conn, slug, card):
    from project_assistant import orchestrator
    orchestrator.lock_project(conn, slug)
    worker.enforce_card_policy(card, production_policy(conn, slug))
    from project_assistant import privacy
    if privacy.mode(conn, slug) == "mask_numbers" and worker.card_execution_profile(card)["driver"] != "comfy_local":
        raise StoryError(403, "DRAMA_OPERATION_NOT_ALLOWED", "Original media and prompts are not exported to commercial providers in numeric masking mode.")


def project(conn, identifier):
    slug = identifier[3:] if identifier.startswith("pj_") else identifier
    found = repo.get_project(conn, slug)
    if not found:
        raise StoryError(404, "DRAMA_NOT_FOUND", "Production not found.")
    return {**found, "projectId": "pj_" + slug, "description": found["summary"],
            "productionPolicy": production_policy(conn, slug)}


def episodes(conn, slug):
    found = records(conn, "episode", slug)
    if not any(e.get('episodeId') == f'ep_{slug}_01' for e in found) and repo.get_tab(conn, slug, "director-brief"):
        # The legacy first episode is implicit until an old mutation persists it.
        # Creating episode 2 must not make already-saved episode-1 writing resources unreachable.
        found = [{"episodeId": f"ep_{slug}_01", "projectId": "pj_" + slug, "slug": slug,
                  "episodeIndex": 1, "title": "Episode 1", "tabKey": "director-brief", "settings": {}}] + found
    return sorted(found, key=lambda e: e["episodeIndex"])


def episode(conn, identifier):
    found = record(conn, identifier, required=False)
    if not found:
        match = re.fullmatch(r"ep_([a-z0-9-]{1,41})_(\d+)", identifier)
        if match:
            found = next((e for e in episodes(conn, match[1]) if e["episodeId"] == identifier), None)
    if not found or not repo.get_tab(conn, found["slug"], found["tabKey"]):
        raise StoryError(404, "DRAMA_NOT_FOUND", "Episode not found.")
    return found


def script(conn, ep):
    tab = repo.get_tab(conn, ep["slug"], ep["tabKey"])
    return doc_text(tab["doc"])


def scene_sections(content):
    lines = content.splitlines()
    scenes, current = [], None
    for line in lines:
        heading = re.match(r"^\s*(?:#{1,6}\s*)?((?:Scene\s*\d+|場景\s*[一二三四五六七八九十\d]+|场景\s*[一二三四五六七八九十\d]+|INT\.|EXT\.).*)$", line, re.I)
        if heading:
            current = {"title": heading[1].strip(), "content": ""}
            scenes.append(current)
        elif current is not None:
            current["content"] += line + "\n"
    return scenes or ([{"title": "Scene 01", "content": content}] if content.strip() else [])


def scenes_of_doc(ep, doc):
    from project_docs import writing_structure
    # Scene boundaries are document blocks, exactly as in the stable structure. A
    # heading-looking line after a hardBreak is still inside its original block.
    # Keep hardBreaks and paragraph spacing in the content for the shot cutter.
    items = []
    for part in writing_structure.sections(doc):
        bodies = [doc_text({"content": [node]}) for node in part['nodes']]
        heading = part['heading']
        title = 'Scene 01'
        if heading is not None:
            # 只拆標題文字投影，不拆穩定 block 邊界。R16 可把整份劇本放在
            # 同一 paragraph；hardBreak 後的正文仍屬此場，不能丟失或混入場名。
            first_line, separator, inline_body = doc_text({"content": [heading]}).lstrip().partition('\n')
            title = scene_sections(first_line)[0]['title']
            if separator:
                bodies.insert(0, inline_body)
        content = "\n\n".join(bodies)
        if heading is None and not content.strip():
            continue
        items.append({'title': title, 'content': content})
    return [{**item, "sceneId": f"sc_{ep['slug']}_{ep['episodeIndex']:02d}_S{i:02d}",
             "episodeId": ep["episodeId"], "sceneIndex": i} for i, item in enumerate(items, 1)]


def scenes(conn, ep):
    return scenes_of_doc(ep, repo.get_tab(conn, ep["slug"], ep["tabKey"])["doc"])


def choice_traces(conn, ep):
    """P3 decision traces of one episode, oldest first."""
    return sorted((t for t in records(conn, "choice_trace", ep["slug"]) if t["episodeId"] == ep["episodeId"]), key=lambda t: t["createdAt"])


def episode_view(conn, ep):
    content = script(conn, ep)
    return {**{k: v for k, v in ep.items() if k not in ("confirmedHash",)}, "scriptContent": content,
            "scriptDirty": ep.get("confirmedHash") != digest(content), "scenes": scenes(conn, ep),
            "missingAssetCodes": missing_episode_assets(conn, ep)[0]}


def save_doc(conn, me, slug, key, doc):
    """Explicit Story edits retain block ownership, locks, revisions and annotations."""
    tab = repo.get_tab_for_update(conn, slug, key)
    if not tab:
        raise StoryError(404, "DRAMA_NOT_FOUND", "Production page not found.")
    old_nodes = {n["attrs"]["bid"]: n for n in tab["doc"]["content"] if n.get("attrs", {}).get("bid")}
    new_nodes = {n["attrs"]["bid"]: n for n in doc["content"] if n.get("attrs", {}).get("bid")}
    locks = repo.tab_locks(conn, slug, key)
    for bid in old_nodes.keys() | new_nodes.keys():
        before, after = old_nodes.get(bid), new_nodes.get(bid)
        if before == after:
            continue
        touched = {bid}
        if before and before.get("type") == "table":
            after_rows = {r.get("attrs", {}).get("bid"): r for r in (after or {}).get("content", [])}
            touched.update(r.get("attrs", {}).get("bid") for r in before.get("content", [])
                           if r != after_rows.get(r.get("attrs", {}).get("bid")))
            if after and column_ids(before) != column_ids(after):
                invalid("Story operations cannot change column identities.")
        if any(locks.get(unit) not in (None, me.actor_id) for unit in touched):
            raise StoryError(409, "DRAMA_OPERATION_NOT_ALLOWED", "A crew member is editing this content.")
        owner = (before or {}).get("attrs", {}).get("owner")
        if owner and owner != me.actor_id and not me.can_edit:
            raise StoryError(409, "DRAMA_OPERATION_NOT_ALLOWED", "This content belongs to another crew member.")
    doc, _ = validate_doc(doc, slug=slug)
    repo.save_tab_doc(conn, slug, key, doc=doc, title=tab["title"], actor_id=me.actor_id,
                      session_id="story-" + uuid.uuid4().hex, base_revision=tab["revision"], force_revision=True, trusted_writer=me)
    repo.add_audit(conn, slug, action="edit", actor_id=me.actor_id, tab_key=key,
                   detail={"source": "rh_story", "changes": service.doc_changes(tab["doc"], doc)})
    service.reanchor_tab(conn, slug, key, doc, actor_id=me.actor_id)


def script_doc(slug, content):
    """The document a saved script becomes (what scenes and storyboard builds read back); nothing is written."""
    doc, _ = markdown_import.markdown_to_doc(screenplay_markdown(content), tab_keys=set(), image_src=lambda _: None)
    return validate_doc(doc, slug=slug)[0]


def set_script(conn, me, ep, content):
    if not content.strip():
        raise StoryError(422, "DRAMA_SCRIPT_INVALID", "The script cannot be empty.")
    save_doc(conn, me, ep["slug"], ep["tabKey"], script_doc(ep["slug"], content))
    store(conn, ep["episodeId"], "episode", ep, ep["slug"])
    return episode_view(conn, ep)


def table_rows(conn, slug, key):
    tab = repo.get_tab(conn, slug, key)
    if not tab:
        return []
    values = repo.field_values(conn, slug).get(key, {})
    result = []
    for table in tab["doc"].get("content", []):
        if table.get("type") != "table":
            continue
        rows = table.get("content", [])
        headers = [node_text(c) for c in rows[0].get("content", [])] if rows else []
        for row in rows[1:]:
            result.append({"rid": row["attrs"]["bid"], "cells": [cell_value(c, values) for c in row["content"]],
                           "headers": headers, "tableId": table["attrs"]["bid"], "tabKey": key})
    return result


def mutate_row(conn, me, slug, key, rid=None, cells=None, *, after=None, delete=False):
    tab = repo.get_tab_for_update(conn, slug, key)
    if not tab:
        raise StoryError(404, "DRAMA_NOT_FOUND", "Production sheet not found.")
    doc = copy.deepcopy(tab["doc"])
    table = next((t for t in doc["content"] if t.get("type") == "table" and
                  (rid is None or any(r.get("attrs", {}).get("bid") == rid for r in t.get("content", [])))), None)
    if table is None:
        raise StoryError(404, "DRAMA_NOT_FOUND", "Shot or asset row not found.")
    if rid:
        row = next(r for r in table["content"] if r.get("attrs", {}).get("bid") == rid)
        if delete:
            table["content"].remove(row)
    else:
        rid = new_id("b")
        row = {"type": "tableRow", "attrs": {"bid": rid}, "content": [_cell("") for _ in table["content"][0]["content"]]}
        at = next((i + 1 for i, r in enumerate(table["content"]) if r.get("attrs", {}).get("bid") == after), len(table["content"]))
        table["content"].insert(at, row)
    for index, value in (cells or {}).items():
        index = int(index)
        if not 0 <= index < len(row["content"]):
            invalid("The production sheet columns have changed.")
        validate_value(table, index, value)
        row["content"][index] = _cell(value)
    save_doc(conn, me, slug, key, doc)
    return rid


def shot_id(slug, row):
    return f"sh_{slug}_{row['rid']}"


def asset_id(slug, row):
    return f"as_{slug}_{row['rid']}"


def media_url(value):
    return next(iter(worker._media_urls(value)), None)


def media_column(row, kind):
    patterns = {"image": r"keyframe|reference.*image|anchor", "video": r"cinema.*shot|remastered.*video"}
    index = next((i for i, h in enumerate(row["headers"]) if re.search(patterns[kind], h, re.I)), None)
    if index is None:
        invalid(f"This row has no {kind} output column.")
    return index


def look_kind(cells):
    """OUTFIT/POSE/LOOK of a look-variant row (CAST-01:night); a look keeps its kind in the notes cell, so that cell is not free text."""
    note = cells[6] if len(cells) > 6 else ""
    return note if ":" in asset_code(cells[0]) and note in LOOK_KINDS else None


def asset_view(slug, row):
    cells = row["cells"]
    code = cells[0].lstrip("@").upper().replace("#", ":")
    note = cells[6] if len(cells) > 6 else ""
    kind = look_kind(cells)
    return {"assetId": asset_id(slug, row), "assetCode": code, "name": cells[1], "prompt": cells[2],
            "type": "CHARACTER" if code.startswith("CAST") else "PROP" if code.startswith("PROP") else "SCENE",
            "isDefault": ":" not in code, "kind": kind,
            "voice": cells[4] if len(cells) > 4 else "", "status": cells[5] if len(cells) > 5 else "", "notes": "" if kind else note,
            "selectedImageUrl": media_url(cells[3]), "rowId": row["rid"], "tabKey": "soul-cast"}


def assets(conn, ep):
    return [asset_view(ep["slug"], r) for r in table_rows(conn, ep["slug"], "soul-cast")]


def missing_episode_assets(conn, ep):
    """One exact-reference scope for pre-storyboard readiness and batch generation."""
    refs = [asset_code(m[1]) for m in ASSET_RE.finditer(script(conn, ep))]
    refs.extend(ep.get("extractedAssetCodes", []))
    for key in ("cinema-studio", "openjutsu-lab"):
        for row in table_rows(conn, ep["slug"], key):
            meta = shot_meta(conn, shot_id(ep["slug"], row))
            # Seed/template shots have no episode metadata and are not this script's extraction.
            if meta.get("episodeId") == ep["episodeId"]:
                refs.extend(asset_code(m[1]) for m in ASSET_RE.finditer(" ".join(row["cells"])))
    known = {a["assetCode"]: a for a in assets(conn, ep)}
    missing = [c for c in dict.fromkeys(refs) if c.startswith(("CAST-", "SET-", "LOC-")) and not known.get(c, {}).get("selectedImageUrl")]
    return missing, known


def find_row(conn, identifier, kind):
    prefix = "sh_" if kind == "shot" else "as_"
    match = re.fullmatch(prefix + r"([a-z0-9-]{1,41})_(b[A-Za-z0-9_-]+)", identifier)
    if not match:
        raise StoryError(404, "DRAMA_NOT_FOUND", "Row not found.")
    slug, rid = match.groups()
    for key in (("cinema-studio", "openjutsu-lab") if kind == "shot" else ("soul-cast",)):
        row = next((r for r in table_rows(conn, slug, key) if r["rid"] == rid), None)
        if row:
            return slug, row
    raise StoryError(404, "DRAMA_NOT_FOUND", "Row not found.")


def shot_meta(conn, identifier):
    return record(conn, "meta_" + identifier, required=False) or {}


def shot_view(conn, slug, row, *, takes=None):
    """A shot's API payload. ``adoption`` is always present (SPEC_19); ``takeSummary`` needs the take history, so only
    callers answering a client pass ``takes`` (a story_adoption.Takes shared by the whole response)."""
    from project_docs import story_adoption, story_trim
    identifier = shot_id(slug, row)
    meta = shot_meta(conn, identifier)
    fields = dict(zip(row["headers"], row["cells"]))
    def output(kind):
        try:
            return media_url(row["cells"][media_column(row, kind)])
        except StoryError:
            return None
    status = next((v for k, v in fields.items() if k.casefold() == "status"), "Queued")
    mapped = {"Approved": "READY", "Pending Review": "READY", "已完成": "READY", "等待審核": "READY",
              "Rendering Video": "RUNNING", "Rendering Image": "RUNNING", "In Progress": "RUNNING", "進行中": "RUNNING"}
    refs = list(dict.fromkeys(m[1].upper().replace("#", ":") for m in ASSET_RE.finditer(" ".join(row["cells"]))))
    known = {a["assetCode"]: a for a in (asset_view(slug, r) for r in table_rows(conn, slug, "soul-cast"))}
    missing = [c for c in refs if c.startswith(("CAST-", "SET-", "LOC-")) and not known.get(c, {}).get("selectedImageUrl")]
    has_previs = any(media_url(v) for k, v in fields.items() if re.search(r"previs|pose.*skeleton", k, re.I))
    previs = next((media_url(v) for k, v in fields.items() if re.search(r"previs|blockout", k, re.I) and media_url(v)), None)
    view = {**meta, "shotId": identifier, "rowId": row["rid"], "tabKey": row["tabKey"], "shotIndex": row["cells"][0],
            "description": next((v for k, v in fields.items() if re.search("prompt", k, re.I)), ""),
            "opticalRig": next((v for k, v in fields.items() if re.search(r"optical|rig", k, re.I)), ""),
            "cameraMotion": next((v for k, v in fields.items() if re.search(r"camera.*motion", k, re.I)), ""),
            "assets": refs, "status": mapped.get(status, "PENDING"), "reviewStatus": status,
            "complexity": worker.evaluate_shot_complexity({**fields, "reviewStatus": status}),
            "readiness": {"ready": bool(output("image") or has_previs or not missing), "missingAssets": missing,
                          "hasPrevis": has_previs, "hasDialogue": bool(meta.get("dialogue"))},
            "selectedImageUrl": output("image"), "selectedVideoUrl": output("video"), "previsVideoUrl": previs,
            "trim": story_trim.view(meta, output("video"))}
    view["adoption"] = story_adoption.adoption_view(meta, status, output("video"))
    if takes is not None:
        from project_docs import story_take_refs
        view["takeSummary"] = story_adoption.take_summary(takes, row, view["adoption"])
        # SPEC_19 R16: the shots the adopted take quoted, and whether each tag still resolves to the quoted frame.
        view["takeRefs"] = story_take_refs.view_refs(conn, slug, identifier, view["adoption"], takes)
    return view


FILM_SELECTIONS = ("selected", "adopted")
FILM_FILLS = ("previs", "latest", "skip")


def film_plan(items, selection="selected", fill="skip"):
    """(shot, video URL, source) of an episode film in shot order; source is "adopted", "latest" or "previs".

    selection "selected" (the RH-compatible default): the cinema slate is the cut, every slate take in it; a lab clip joins
    once it is approved. selection "adopted" (SPEC_19): only adopted shots are the cut. ``fill`` decides what a slate shot
    outside the cut plays: "latest" its newest take (the one in its cell), "previs" its grey previs, "skip" nothing. A lab
    clip never fills. In "selected" mode every slate take is already in, so only "previs" adds anything.
    """
    from project_docs.story_adoption import ADOPTED
    ordered = sorted(items, key=lambda s: tuple((0, int(part)) if part.isdigit() else (1, part.casefold()) for part in re.split(r"(\d+)", str(s["shotIndex"]))))
    result = []
    for shot in ordered:
        slate, adopted, take = shot["tabKey"] == "cinema-studio", shot.get("reviewStatus") in ADOPTED, shot["selectedVideoUrl"]
        previs = slate and fill == "previs" and shot.get("previsVideoUrl")
        if take and (adopted or (slate and (selection == "selected" or fill == "latest"))):
            result.append((shot, take, "adopted" if adopted else "latest"))
        elif previs:
            result.append((shot, previs, "previs"))
    return result


def film_shots(items, fill_previs=False, *, selection="selected", fill=None):
    """(shot, video URL) of an episode film in shot order (see film_plan).
    fill_previs: a slate shot without a take plays its grey previs, so the whole episode can be watched before it is shot."""
    return [(shot, url) for shot, url, _ in film_plan(items, selection, fill or ("previs" if fill_previs else "skip"))]


def film_cut(items, fill_previs=False):
    """Video URLs of an episode film in shot order (see film_shots)."""
    return [url for _, url in film_shots(items, fill_previs)]


def film_options(body):
    """(selection, fill) of POST /episodes/{id}/films; without the new fields the RH request means exactly what it meant."""
    selection = body.get("selection", "selected")
    if selection not in FILM_SELECTIONS:
        invalid("selection must be selected or adopted.")
    if "fill" not in body:
        return selection, "previs" if body.get("fillPrevis") is True else "skip"
    if body["fill"] not in FILM_FILLS:
        invalid("fill must be previs, latest or skip.")
    if body.get("fillPrevis") is True and body["fill"] != "previs":
        invalid("fillPrevis: true means fill: previs; send one of them.")
    return selection, body["fill"]


def shots(conn, ep, *, takes=None):
    result = []
    for key in ("cinema-studio", "openjutsu-lab"):
        for row in table_rows(conn, ep["slug"], key):
            view = shot_view(conn, ep["slug"], row, takes=takes)
            if view.get("episodeId", f"ep_{ep['slug']}_01") == ep["episodeId"]:
                result.append(view)
    return result


def locate_scene(conn, identifier):
    match = re.fullmatch(r"sc_([a-z0-9-]{1,41})_(\d+)_S\d+", identifier)
    if match:
        ep = episode(conn, f"ep_{match[1]}_{int(match[2]):02d}")
        scene = next((s for s in scenes(conn, ep) if s["sceneId"] == identifier), None)
        if scene:
            return ep, scene
    raise StoryError(404, "DRAMA_NOT_FOUND", "Scene not found.")


def write_scenes(conn, me, ep, items, redirects=None):
    from project_docs import writing_structure
    with writing_structure.deferred_reconciliation(conn,ep['slug'],ep['tabKey']):
        return _write_scenes(conn,me,ep,items,redirects)


def _write_scenes(conn, me, ep, items, redirects=None):
    from project_docs import writing_store, writing_structure
    writing_scope = writing_store.scope_for(conn, me, ep['episodeId'], write=True)
    writing_store.lock_project(conn, writing_scope)
    # This legacy operation supplies explicit old scene IDs, unlike blind whole-script writes.
    before_structure = writing_structure.read_structure(conn, writing_scope)
    old_stable = {s['legacySceneId']: s['sceneKey'] for s in before_structure['scenes']} if before_structure['initialized'] else {}
    mapping = {s['sceneId']: (f"sc_{ep['slug']}_{ep['episodeIndex']:02d}_S{i:02d}", i)
               for i, s in enumerate(items, 1) if s.get('sceneId')}
    content = []
    for i, item in enumerate(items, 1):
        title = re.sub(r"^Scene\s*\d+\s*[:：.-]?\s*", "", item['title'], flags=re.I) or "Scene"
        content.append(f"## Scene {i:02d}: {title}\n\n{item['content'].strip()}")
    result = set_script(conn, me, ep, "\n\n".join(content))
    if old_stable:
        current_doc = repo.get_tab(conn, ep['slug'], ep['tabKey'])['doc']
        current_sections = writing_structure.sections(current_doc)
        lineage = {writing_structure.bid(section['heading']): old_stable[item['sceneId']]
                   for section, item in zip(current_sections, items)
                   if section['heading'] and item.get('sceneId') in old_stable}
        lineage.update({old_stable[old]: old_stable[new] for old, new in (redirects or {}).items()
                        if old in old_stable and new in old_stable})
        reconciled = writing_structure.reconcile_structure(current_doc, before_structure, lineage=lineage)
        writing_structure.finalize_structure_change(conn, writing_scope, before_structure, reconciled)
        return result
    for shot in shots(conn, ep):
        old = shot.get('sceneId')
        new = mapping.get((redirects or {}).get(old, old))
        if not new:
            if old:
                from project_docs import writing_impact
                writing_impact._check_row(conn, writing_scope, shot)
                meta = shot_meta(conn, shot['shotId']) | {'sceneId': None,
                    'detachedScene': {'legacySceneId': old, 'sceneKeys': [], 'state': 'source_removed'}}
                store(conn, 'meta_' + shot['shotId'], 'shot_meta', meta, ep['slug'])
            continue
        if new[0] == old:
            continue
        meta = shot_meta(conn, shot['shotId']) | {'sceneId': new[0]}
        store(conn, 'meta_' + shot['shotId'], 'shot_meta', meta, ep['slug'])
        index = re.sub(r'^SC\d+', f'SC{new[1]:02d}', shot['shotIndex'], flags=re.I)
        mutate_row(conn, me, ep['slug'], shot['tabKey'], shot['rowId'], {0: index})
    return result


def completed_task(conn, me, slug, kind, result):
    identifier = "tk_" + uuid.uuid4().hex
    task = {"taskId": identifier, "type": kind, "status": "SUCCEEDED", "result": result,
            "error": None, "cost": None, "progress": None, "createdAt": now(), "finishedAt": now()}
    store(conn, identifier, "task", task, slug, me.actor_id)
    return task


def extract(conn, me, ep):
    from project_assistant.orchestrator import lock_project
    lock_project(conn, ep['slug'])
    for key in sorted({ep['tabKey'], 'soul-cast'}):
        repo.get_tab_for_update(conn, ep['slug'], key)
    content = script(conn, ep)
    if not content.strip():
        raise StoryError(422, "DRAMA_STAGE_INPUT_EMPTY", "Write a script before extracting assets.")
    existing = {a["assetCode"]: a for a in assets(conn, ep)}
    current_rows = {asset_code(r["cells"][0]): r for r in table_rows(conn, ep["slug"], "soul-cast")}
    details = extract_asset_details(content, scenes(conn, ep))
    if len(details) > 200:
        invalid("An extraction supports at most 200 assets; split the script into episodes.")
    for code, item in details.items():
        cells = {0: code, 1: item["name"], 2: item["prompt"][:10000], 5: "Queued"}
        if item.get("kind"):
            cells[6] = item["kind"]
        if code not in existing:
            rid = mutate_row(conn, me, ep["slug"], "soul-cast", cells=cells)
            store(conn, f"extracted_as_{ep['slug']}_{rid}", "asset_extraction", {"name": cells[1], "prompt": cells[2]}, ep["slug"])
        elif not existing[code]["selectedImageUrl"] and current_rows[code]["cells"][5] in ("Queued", "待處理"):
            previous = record(conn, "extracted_" + existing[code]["assetId"], required=False)
            draft = {"name": existing[code]["name"], "prompt": existing[code]["prompt"]}
            placeholder = draft["name"] in ("", code) and draft["prompt"] in ("", code, f"Reference for @{code}")
            untouched = previous == draft if previous is not None else placeholder
            if untouched:
                # Only drafts we generated (still untouched), or placeholders, may be enriched.
                mutate_row(conn, me, ep["slug"], "soul-cast", existing[code]["rowId"], {1: cells[1], 2: cells[2], **({6: item["kind"]} if item.get("kind") else {})})
                store(conn, "extracted_" + existing[code]["assetId"], "asset_extraction", {"name": cells[1], "prompt": cells[2]}, ep["slug"])
    ep["extractedAssetCodes"] = list(details)
    ep["confirmedHash"] = digest(content)
    store(conn, ep["episodeId"], "episode", ep, ep["slug"])
    from project_docs import writing_store, writing_versions
    writing_scope = writing_store.scope_for(conn, me, ep['episodeId'], write=True)
    writing_versions.confirm_baseline(conn, writing_scope, expected_doc_hash=writing_store.doc_hash(repo.get_tab(conn, ep['slug'], ep['tabKey'])['doc']), extracted=True)
    ep.update(episode(conn, ep['episodeId']))
    return completed_task(conn, me, ep["slug"], "ASSET_EXTRACT", {"assetsCount": len(existing.keys() | details.keys()), "scenesCount": len(scenes(conn, ep))})


def scene_claim(conn, me, ep, *, write=False):
    """(shot, scene) -> 'own', 'extra' or None: what a build of this scene does with a slate shot.

    'own': the shot occupies a place on the scene's slate, not necessarily an exact beat. Once the writing structure exists that rests on the
    stable scene relationship, never on a positional scene id (a reorder can reuse one); before it exists it is the old positional check.
    'extra': no scene can claim the shot (a hand-made insert, an old shot without a proven origin), but its positional id says this scene,
    so it is counted here and kept as it is: it
    never answers a beat and is never rewritten. The build and its estimate both ask this, so the numbers shown before a build are the slate after it.
    """
    from project_docs import writing_store, writing_structure
    structure = writing_structure.read_structure(conn, writing_store.scope_for(conn, me, ep['episodeId'], write=write))
    stable = {s['legacySceneId']: s['sceneKey'] for s in structure['scenes']}

    def claim(shot, scene):
        if shot.get('detachedScene'):
            return None
        if not structure['initialized']:
            return 'own' if shot.get('sceneId') == scene['sceneId'] else None
        keys, _, missing = writing_structure.compatibility_relationship(structure, shot)
        origin = shot.get('storyOrigin') or {}
        if missing == 'ambiguous' and origin.get('mapping') == 'ambiguous' and not origin.get('beatKeys'):
            # Repeated generated descriptions cannot prove which beat produced a
            # row, but their frozen scene key can still prove slate occupancy.
            # Resolve only that key (including split/merge rules), never a row
            # label or description. This does not certify an exact beat origin.
            keys, _, missing = writing_structure.shot_relationship(structure,
                shot | {'storyOrigin': origin | {'mapping': 'scene_only'}})
        if not missing:
            return 'own' if keys == [stable.get(scene['sceneId'])] else None
        return 'extra' if missing == 'unbound' and shot.get('sceneId') == scene['sceneId'] else None
    return claim


def build_shots(conn, me, ep, only_scene=None, breakdown_mode=None):
    from project_docs import story_estimates as planner  # the estimate asks the same planner what this build would do
    mode = ep.get("breakdownMode", ep.get("settings", {}).get("breakdownMode", "auto")) if breakdown_mode is None else breakdown_mode
    if not isinstance(mode, str) or mode not in BREAKDOWN_MODES:
        invalid("Unknown breakdownMode.")
    from project_assistant.orchestrator import lock_project
    lock_project(conn, ep['slug'])
    for key in sorted({ep['tabKey'], 'cinema-studio'}):
        repo.get_tab_for_update(conn, ep['slug'], key)
    scene_list = scenes(conn, ep)
    if ep.get("confirmedHash") != digest(script(conn, ep)) or not scene_list:
        raise StoryError(409, "DRAMA_STAGE_PRECONDITION", "Confirm Script & Extract Assets before building storyboards.")
    previous = shots(conn, ep)
    claim = scene_claim(conn, me, ep, write=True)
    medium = script_medium_lens(script(conn, ep))  # a composed script carries its Lens line
    plans = planner.beat_plans(scene_list, mode, only_scene)
    if sum(len(beats) for _, beats in plans) > planner.MAX_BUILD_SHOTS:
        invalid("A storyboard build supports at most 200 shots; split the script into episodes.")
    created = []
    origin_updated = []
    for scene, beats in plans:
        steps, surplus = planner.scene_steps(scene, beats, previous, rebuild=bool(only_scene), claim=claim)
        scene_refs = [asset_code(m[1]) for m in ASSET_RE.finditer(scene["content"]) if m[1].upper().startswith(("SET-", "LOC-"))]
        scene_refs = list(dict.fromkeys(scene_refs)) or [f"SET-{scene['sceneIndex']:02d}"]
        cast = {a["name"].casefold(): a["assetCode"] for a in assets(conn, ep) if a["type"] == "CHARACTER" and a["isDefault"]}
        for action, index, beat, previous_shot in steps:
            if action == "keep" or (action == "rewrite" and (previous_shot.get('storyOrigin') or {}).get('mapping') == 'ambiguous'):
                created.append(previous_shot)
                # A normal build fills only missing slate places. Even an explicit
                # rebuild cannot rewrite a row whose beat origin is ambiguous.
                continue
            grammar = infer_shot_grammar(beat, index, len(beats), medium)
            refs = scene_refs + [code for name, code in cast.items() if re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", beat, re.I)]
            prompt = beat + " " + " ".join("@" + c for c in dict.fromkeys(refs) if c not in {asset_code(m[1]) for m in ASSET_RE.finditer(beat)})
            cells = {0: f"SC{scene['sceneIndex']:02d}-S{index + 1:02d}", 1: grammar["opticalRig"], 2: grammar["cameraMotion"], 3: prompt[:10000]}
            if action == "rewrite":
                # Explicit narrative rebuilds retain the established label, optics and media.
                rid = mutate_row(conn, me, ep["slug"], previous_shot["tabKey"], previous_shot["rowId"], {3: prompt[:10000]})
                if previous_shot.get("previsPlan"):
                    grammar["previsPlan"] = {**grammar["previsPlan"], **{key: previous_shot["previsPlan"][key]
                        for key in ("lens", "move") if key in previous_shot["previsPlan"]}}
            else:
                rid = mutate_row(conn, me, ep["slug"], "cinema-studio", cells=cells | {6: "Queued"})
            identifier = f"sh_{ep['slug']}_{rid}"
            meta = shot_meta(conn, identifier) | {"episodeId": ep["episodeId"], "sceneId": scene["sceneId"], "dialogue": grammar["dialogue"], "previsPlan": grammar["previsPlan"]}
            meta.pop('detachedScene', None)  # Only an actual current derivation clears the detach marker.
            store(conn, "meta_" + identifier, "shot_meta", meta, ep["slug"])
            created.append({"shotId": identifier})
            origin_updated.append(identifier)
        created.extend(surplus)  # Never delete existing takes when a scene becomes shorter.
    if origin_updated and ep.get('productionScriptVersionId'):
        from project_docs import writing_store
        from importlib.util import find_spec
        if find_spec('project_docs.writing_impact') is not None:
            from project_docs import writing_impact
            writing_impact.bind_generated_shots(conn, writing_store.scope_for(conn, me, ep['episodeId'], write=True), origin_updated, version_id=ep['productionScriptVersionId'])
    return completed_task(conn, me, ep["slug"], "STORYBOARD_GENERATE", {"shotsCount": len(created)})


def candidate_list(conn, identifier, kind):
    entity = "shot" if identifier.startswith("sh_") else "asset"
    slug, row = find_row(conn, identifier, entity)
    column = media_column(row, kind)
    urls = []
    # Revisions include uploaded/selected cells, not only API-generated takes.
    for revision in repo.revision_rows(conn, slug, tab_key=row["tabKey"]):
        for table in revision["doc"].get("content", []):
            if table.get("type") == "table":
                for old in table.get("content", [])[1:]:
                    if old.get("attrs", {}).get("bid") == row["rid"] and column < len(old.get("content", [])):
                        url = media_url(cell_value(old["content"][column], {}))
                        if url:
                            urls.append(url)
    current = media_url(row["cells"][column])
    if current:
        urls.append(current)
    from project_docs.story_adoption import latest_created
    stored = [c for c in records(conn, "candidate", slug) if c["entityId"] == identifier and c["kind"] == kind]
    urls.extend(c["url"] for c in stored)
    created = latest_created(stored)  # SPEC_19: null for history, uploads and candidates written before createdAt
    prefix, key = ("im_", "imageId") if kind == "image" else ("vd_", "videoId")
    result = [{key: prefix + digest([identifier, url])[:24], "url": url, kind + "Url": url, "selected": url == current,
               "createdAt": created.get(url)} for url in dict.fromkeys(urls)]
    if entity == 'shot':
        from project_docs import writing_impact
        evidence = [c for c in records(conn, 'candidate', slug) + records(conn, 'story_media_receipt', slug)
                    if c['entityId'] == identifier and c['kind'] == kind]
        result = [writing_impact.candidate_view(c, writing_impact.candidate_evidence(evidence, c['url'])) for c in result]
    return result


def select_candidate(conn, me, identifier, kind, body):
    key = kind + "Id"
    chosen = next((c for c in candidate_list(conn, identifier, kind) if c[key] == body.get(key)), None)
    if not chosen:
        raise StoryError(404, "DRAMA_NOT_FOUND", "Candidate does not belong to this row.")
    slug, row = find_row(conn, identifier, "shot" if identifier.startswith("sh_") else "asset")
    column = media_column(row, kind)
    mutate_row(conn, me, slug, row["tabKey"], row["rid"], {column: f"[{'Image' if kind == 'image' else 'Video'}]({chosen['url']})"})
    if kind == "video" and identifier.startswith("sh_"):
        from project_docs import story_trim
        story_trim.reset(conn, slug, identifier)
    return chosen


def restore_cards(conn):
    for saved in records(conn, "card"):
        card = saved["card"]
        with worker._OPENAPI_LOCK:
            worker._OPENAPI_CARDS[card["card_id"]] = (card, saved["workflow"])
            worker._OPENAPI_CARDS[str(card["engine_config"]["webappId"])] = (card, saved["workflow"])


def register_card(conn, me, body):
    if not me.can_write:
        raise StoryError(409, "DRAMA_OPERATION_NOT_ALLOWED", "Read-only crew members cannot import workflows.")
    if not isinstance(body.get("workflow"), dict):
        invalid("Upload workflow JSON, not a server filesystem path.")
    card = worker.extract_studio_card_from_workflow(body["workflow"], card_id=body.get("card_id"), label=body.get("label"),
        runninghub_spec=body.get("curl") or body.get("nodeInfoList"), webapp_id=body.get("webappId"))
    builtins = [worker.load_studio_card(path) for path in worker.CARDS_DIR.glob("*.json")]
    reserved = {c["card_id"] for c in builtins} | {str(c["engine_config"]["webappId"]) for c in builtins if c["engine_config"].get("webappId")}
    if card["card_id"] in reserved or str(card["engine_config"].get("webappId")) in reserved:
        invalid("Imported cards cannot replace a built-in card or webappId.")
    card["engine_config"]["webappId"] = str(card["engine_config"].get("webappId") or card["card_id"])
    graph = worker.convert_litegraph_to_api(body["workflow"])
    store(conn, "card_" + card["card_id"], "card", {"card": card, "workflow": graph}, owner=me.actor_id)
    return {"code": 0, "msg": "success", "webappId": card["engine_config"]["webappId"], "card": card,
            "nodeInfoList": worker.build_node_info(card)}


def catalog_entries():
    """(card, catalog item) pairs: the primary appCode of every registered card, then the card's other aliases."""
    result = []
    for card in worker.openapi_list_cards():
        ec = card.get("engine_config", {})
        code = next((a for a, cid in ALIASES.items() if cid == card["card_id"]), card["card_id"])
        item = {"appCode": code, "card_id": card["card_id"], "name": card["label"], "capability": card["output_mode"].upper(),
                "webappId": str(ec.get("webappId", card["card_id"])), "skuId": str(ec.get("webappId", "0")),
                "imageMode": "T2I" if card["card_id"] == "local-smoke" else "I2I", "nodes": card["nodes"],
                "frameRule": ec.get("frame_rule", ec.get("frame_formula", "none")),
                **worker.card_execution_profile(card), "configuration": worker.provider_configuration_status(card)}
        result.append((card, item))
        result.extend((card, dict(item, appCode=alias)) for alias, cid in ALIASES.items() if cid == card["card_id"] and alias != code)
    return result


def catalog():
    return [item for _, item in catalog_entries()]


def resolve_app(code, kind, policy=None):
    card_id = ALIASES.get(code, code)
    if code == "SEEDANCE_2_FAST_MULTIMODAL_VIDEO":
        seedance = worker.load_studio_card("seedance-20-pro")
        if worker.effective_production_policy(policy) == "open_weights_only" or not worker.provider_configuration_status(seedance)["configured"]:
            card_id = "h3-reference"
    card = next((c for c in worker.openapi_list_cards() if card_id in (c["card_id"], str(c.get("engine_config", {}).get("webappId")))), None)
    if not card or card["output_mode"] != kind:
        invalid("Select a registered appCode matching the output capability.")
    return card


def snapshot(conn, slug, row):
    return {"rows": [{"row_id": row["rid"], "tab_key": row["tabKey"], "cells": row["cells"]}],
            "tabs": [{"tab_key": key, "tables": [{"headers": row["headers"], "rows": [{"row_id": row["rid"], "cells": row["cells"]}]}]}
                     for key in [row["tabKey"]]] + [{"tab_key": "soul-cast", "tables": [{"headers": r["headers"],
                     "rows": [{"cells": r["cells"]} for r in table_rows(conn, slug, "soul-cast")]}]}
                     for r in table_rows(conn, slug, "soul-cast")[:1]]}


def public_task(task):
    return {k: v for k, v in task.items() if not k.startswith("_")}


def queue_task(conn, me, slug, kind, job, actions):
    identifier = "tk_" + uuid.uuid4().hex
    task = {"taskId": identifier, "type": kind, "status": "QUEUED", "progress": None, "error": None,
            "result": None, "cost": None, "createdAt": now(), "finishedAt": None, "_job": job,
            "_actor": me.actor_id, "_slug": slug, "_process": _PROCESS}
    from project_assistant import execution_governance as governance
    if job.get('card'):
        context = governance.media_context(me, slug, episode_id=job.get('episodeId'), accounting_session_key=identifier)
        if job.get('allocation'):
            operations = job.pop('_accounting_operations', [])
        else:
            operations = [dict(request_key=identifier + ':generate', card=job['card'], operation_digest=governance.cp.digest(job))]
        for operation in operations:
            if operation['card']['engine_config']['driver'] == 'comfy_router':
                if job.get('allocation') and any(s.get('inputs') for s in job['allocation']['stages'] if s['kind'] == 'generate'):
                    raise governance.AdmissionError('Future generated Router references cannot be prequoted; review and quote the completed source first.')
                operation['router_request'] = {'task': {'input': job['input'], 'production_policy': job['production_policy']}, 'values': job['values']}
            governance.prepare_operation(conn, context, **operation)
        if not job.get('allocation'):
            job['_accounting_keys'] = {o['request_key'].split(':')[-1]: o['request_key'] for o in operations}
        else:
            job['_accounting_keys'] = {step['step_id']: job['_accounting_prefix'] + ':' + step['step_id'] for step in job['allocation']['stages'] if step['kind'] != 'approval'}
    store(conn, identifier, "task", task, slug, me.actor_id)
    actions.append(lambda: _POOL.submit(execute_task, identifier))
    return public_task(task)


def take_refs(conn, shot, episode_id, prompt, uses):
    """SPEC_19 R15: snapshots of the @S02.end / @S02.start tags in a shot's prompt (story_take_refs.resolve)."""
    from project_docs import story_take_refs
    if not story_take_refs.tokens(prompt):
        return story_take_refs.resolve(prompt, [], shot, uses)  # no tag: only takeRefUses is checked
    return story_take_refs.resolve(prompt, shots(conn, episode(conn, episode_id)), shot, uses)


def prepare_take_refs(identifier, slug, job, head):
    """SPEC_19 R15 worker preparation: cut each quoted frame from its take (extract_frame with source_url) before the
    generation, and freeze frameUrl/at into the task's job; a retry keeps the frames it already has."""
    from project_docs import http, story_take_refs, writing_impact
    refs = story_take_refs.frozen(job)
    if not refs or all(ref.get('frameUrl') for ref in refs):
        return refs
    from project_assistant import execution_governance as governance
    refs = story_take_refs.prepare_frames(identifier, slug, refs, head,
        operation=lambda key, action: governance.run_operation(head.accounting_context, identifier + ':' + key, action))
    with http.open_connection() as conn:
        current = record(conn, identifier, lock=True)
        if current['status'] != 'RUNNING':
            raise worker.WorkerError('Story operation ended before generation.')
        current['_job']['storyProvenance'] = writing_impact.with_take_refs(current['_job'].get('storyProvenance'), refs)
        store(conn, identifier, 'task', current)
    job['storyProvenance'] = writing_impact.with_take_refs(job.get('storyProvenance'), refs)
    return refs


def generation_job(conn, me, identifier, kind, body):
    slug, row = find_row(conn, identifier, "shot" if identifier.startswith("sh_") else "asset")
    authorize(conn, me, slug, write=True)
    policy = production_policy(conn, slug)
    if "productionPolicy" in body and body["productionPolicy"] != policy:
        invalid("Change the production policy explicitly before generation.")
    frozen = body.get("_frozenCard")
    card = frozen[0] if frozen else resolve_app(text(body, "appCode"), kind, policy)
    authorize_card(conn, slug, card)
    tier = body.get("engineTier")
    if tier is not None and tier != worker.card_execution_profile(card)["tier"]:
        invalid("engineTier does not match the selected card.")
    if body.get("budgetMode") == "lab_economical" and worker.card_execution_profile(card)["tier"] != "open_weights":
        invalid("Lab mode cannot dispatch commercial cards.")
    if body.get("budgetMode", "hybrid_balanced") not in ("lab_economical", "hybrid_balanced", "deadline_rush"):
        invalid("Invalid budgetMode.")
    params = body.get("modelParams", {})
    if not isinstance(params, dict) or len(params) > 50:
        invalid("modelParams must contain at most 50 inputs.")
    allowed = {f"{n['nodeId']}.{n['fieldName']}": n for n in card["nodes"] if not n.get("hidden")}
    values = {}
    for key, value in params.items():
        node = allowed.get(key) or next((n for n in card["nodes"] if n.get("slot") == key), None)
        if node is None or isinstance(value, (dict, list, bool)) or value is None:
            invalid(f"Unknown or invalid card input: {key}")
        values[f"{node['nodeId']}.{node['fieldName']}"] = value
    prompt = text(body, "promptOverride")
    if prompt:
        values.update({f"{n['nodeId']}.{n['fieldName']}": prompt for n in card["nodes"] if n.get("slot") == "prompt"})
    source = body.get("referenceSourceVideoId")
    if source:
        chosen = next((c for c in candidate_list(conn, identifier, "video") if c["videoId"] == source), None)
        if not chosen:
            invalid("referenceSourceVideoId must be a video candidate from this shot.")
        values.update({f"{n['nodeId']}.{n['fieldName']}": chosen["url"] for n in card["nodes"] if n.get("slot") == "driving_video"})
    column = media_column(row, kind)
    workflow = frozen[1] if frozen else worker._resolve_openapi_card_and_workflow(card["card_id"])[1]
    shot = shot_view(conn, slug, row) if identifier.startswith('sh_') else None
    episode_id = shot.get('episodeId', 'ep_' + slug + '_01') if shot else None
    job = {"episodeId": episode_id, "entityId": identifier, "kind": kind, "row": row, "input": snapshot(conn, slug, row),
           "card": card, "workflow": workflow, "values": values, "column": column, "production_policy": policy}
    refs = []
    if identifier.startswith('sh_'):
        from project_docs import writing_impact, story_take_refs
        job['storyProvenance'] = writing_impact.freeze_for_shot(conn, me, identifier)
        writing_impact.validate_frozen_row(job['storyProvenance'], job['row']['cells'])
        # SPEC_19 R15: @S02.end / @S02.start in the prompt sent are frozen now, into the job and the new take's provenance.
        refs = take_refs(conn, shot, episode_id, prompt or shot['description'], body.get('takeRefUses'))
        if refs:
            job['storyProvenance'] = writing_impact.with_take_refs(job['storyProvenance'], refs)
            if prompt:
                # An override replaces the compiled prompt, so its tags become their sentences here (the same function).
                values.update({f"{n['nodeId']}.{n['fieldName']}": story_take_refs.expand(prompt, refs) for n in card["nodes"] if n.get("slot") == "prompt"})
    elif body.get('takeRefUses') is not None:
        invalid('takeRefUses applies to shot generations only.')
    if body.get("_allocation"):
        job["allocation"] = copy.deepcopy(body["_allocation"])
        job['_accounting_prefix'] = body.get('_accountingPrefix') or 'generation:' + uuid.uuid4().hex
        from project_assistant import execution_governance as context
        job['_accounting_operations'] = context.allocation_operations(job['allocation'], job['_accounting_prefix'])
        for step in job["allocation"]["stages"]:
            if step["kind"] == "generate":
                step["card"], step["workflow"] = (card, workflow) if step["card_id"] == card["card_id"] else worker._resolve_openapi_card_and_workflow(step["card_id"])
    if refs and any(c["engine_config"]["driver"] == "comfy_router" for c in
                    [card] + [s["card"] for s in job.get("allocation", {}).get("stages", []) if s["kind"] == "generate"]):
        # Like any future generated Router reference: the quoted frame is cut after admission and cannot be quoted before.
        raise StoryError(409, "DRAMA_STAGE_PRECONDITION", "A quoted take's frame is cut after admission, so an official Router card cannot quote it in advance; use a local card for this shot.")
    if identifier.startswith('sh_') and not job.get('allocation'):
        from project_docs import story_allocation
        step={'step_id':'generate','kind':'generate','card_id':card['card_id'],'depends_on':[],'inputs':{},'output_role':'output_'+kind}
        sources = None
        if any(ref['use'] == 'first_frame' for ref in refs):
            # The worker cuts the quoted frame; until then it is a planned image in the shot's first-frame roles.
            step['inputs'] = {role: {'approved_source_id': 'take-ref'} for role in ('first_frame', 'anchor_keyframe')}
            sources = {'approved:take-ref': {'planned_output': True, 'content_type': 'image/png', 'output_role': 'first_frame'}}
        readiness={'stages':[step],'configuration_blockers':[]}
        story_allocation.preflight_inputs(conn,slug,identifier,readiness,{card['card_id']:(card,workflow)},sources,card_values=values)
        if not readiness['ready']:
            raise StoryError(409,'DRAMA_STAGE_PRECONDITION','Resolve required generation inputs before batch admission: ' + ', '.join(readiness['input_blockers']))
    return slug,job


def generation(conn, me, identifier, kind, body, actions):
    slug,job=generation_job(conn,me,identifier,kind,body)
    return queue_task(conn, me, slug, ("SHOT_" if identifier.startswith("sh_") else "ASSET_") + kind.upper() + "_GENERATE", job, actions)


def router_quote(me, identifier, body):
    """Quote a native Story job outside transactions; this never queues generation."""
    from project_docs import http
    from project_assistant import execution_governance as governance
    from project_assistant.studio import comfy_router
    allowed = {'appCode','kind','modelParams','promptOverride','referenceSourceVideoId','budgetMode','engineTier','productionPolicy'}
    if set(body)-allowed or body.get('kind','video') not in ('image','video'):
        invalid('Invalid Router quote fields.')
    with http.open_connection() as conn:
        slug, job = generation_job(conn, me, identifier, body.get('kind','video'), body)
        if job['card']['engine_config']['driver'] != 'comfy_router':
            invalid('Select an official Router card for this quote.')
        ctx = governance.media_context(me,slug)
        binding=governance.live(conn,ctx,destination=governance.media_destination(job['card']))
        ctx.operation_deadline_at=(governance.cp.now()+timedelta(seconds=binding['environment']['config'].get('timeout_seconds',300))).isoformat()
        governance.media_credentials(conn,ctx,job['card'])
        source = digest(job['input'])
    task = {'input':job['input'], 'production_policy':job['production_policy']}
    class QuoteHead:
        def lease_lost(self):
            try:
                with http.open_connection() as conn:
                    governance.live(conn,ctx)
                    governance.media_credentials(conn,ctx,job['card'])
                    authorize_card(conn,slug,job['card'])
                    _, current = find_row(conn,identifier,'shot' if identifier.startswith('sh_') else 'asset')
                    if digest(snapshot(conn,slug,current)) != source or production_policy(conn,slug) != job['production_policy']:
                        return True
                return False
            except (ValueError,worker.WorkerError):
                return True
        def outbound_check(self,url):
            governance.check_destination(ctx,url)
        def outbound_timeout(self,seconds):
            return governance.remaining(ctx,seconds)
        def asset(self,task,url):
            if self.lease_lost():
                raise worker.WorkerError('Quote source or authority changed.')
            match=re.fullmatch(r'/projects/api/'+re.escape(slug)+r'/assets/(pa_[0-9a-f]{32})',url)
            if not match:
                raise worker.WorkerError('Router references must be authorized production assets.')
            with http.open_connection() as conn:
                found=repo.get_asset(conn,slug,match[1])
            if not found:
                raise worker.WorkerError('Router reference is unavailable.')
            return found[1],found[0]
    return comfy_router.quote(ctx,task,job['card'],job['values'],QuoteHead())


class StoryHead:
    def __init__(self, task):
        self.task = task
        from project_assistant import execution_governance as governance
        if 'taskId' not in task:
            return
        self.accounting_context = governance.media_context(service.Identity(task['_actor'], 'Story worker', 'member'), task['_slug'],
            accounting_session_key=task.get('taskId', 'story'), episode_id=task.get('_job',{}).get('episodeId'), authority_check=self.accounting_check)
        self.accounting_keys = task.get('_job', {}).get('_accounting_keys', {})

    def accounting_check(self, conn):
        current = record(conn, self.task['taskId'], required=False)
        if not current or current['status'] != 'RUNNING':
            raise worker.WorkerError('Story operation ended before outbound work.')
        authorize(conn, self.accounting_context.me, self.task['_slug'], write=True)
        card = current['_job'].get('card')
        if card:
            authorize_card(conn, self.task['_slug'], card)
            if card['engine_config']['driver'] == 'comfy_router':
                job=current['_job']
                _,row=find_row(conn,job['entityId'],'shot' if job['entityId'].startswith('sh_') else 'asset')
                if digest(snapshot(conn,self.task['_slug'],row)) != digest(job['input']):
                    raise worker.WorkerError('Router source changed before outbound work; obtain a new reviewed quote.')

    def outbound_check(self, url):
        from project_assistant import execution_governance as governance
        if hasattr(self, 'accounting_context'):
            governance.check_destination(self.accounting_context, url)

    def outbound_timeout(self, requested):
        from project_assistant import execution_governance as governance
        return governance.remaining(self.accounting_context, requested) if hasattr(self, 'accounting_context') else requested

    @property
    def paid_request_submitted(self):
        return getattr(self, "_paid_submitted", False)

    @paid_request_submitted.setter
    def paid_request_submitted(self, value):
        self._paid_submitted = bool(value)
        if value and self.task.get("taskId"):
            from project_docs import http
            with http.open_connection() as conn:
                current = record(conn, self.task["taskId"], lock=True)
                if current["status"] != "RUNNING":
                    raise worker.WorkerError("Task ended before paid submission.")
                current["_paid_ambiguous"] = True
                store(conn, current["taskId"], "task", current)

    def lease_lost(self):
        from project_docs import http
        try:
            with http.open_connection() as conn:
                current = record(conn, self.task["taskId"], required=False)
                if not current or current["status"] != "RUNNING":
                    return True
                authorize(conn, service.Identity(self.task["_actor"], "Story worker", "member"), self.task["_slug"], write=True)
                card = current["_job"].get("card")
                if card:
                    authorize_card(conn, self.task["_slug"], card)
                from project_assistant import execution_governance as governance
                governance.live(conn, self.accounting_context, destination=getattr(self, 'accounting_destination', None))
                if getattr(self, 'accounting_card', None):
                    governance.media_credentials(conn,self.accounting_context,self.accounting_card)
                return False
        except (ValueError, worker.WorkerError):
            return True

    def asset(self, task, url):
        from project_docs import http
        if self.lease_lost():
            raise worker.WorkerError("Media execution was canceled or its authority changed.")
        match = re.fullmatch(r"/projects/api/([a-z0-9-]+)/assets/(pa_[0-9a-f]{32})", url)
        if not match or match[1] != self.task["_slug"]:
            raise worker.WorkerError("Only media from this production may be used as references.")
        with http.open_connection() as conn:
            found = repo.get_asset(conn, *match.groups())
        if not found:
            raise worker.WorkerError("Reference media no longer exists.")
        return found[1], found[0]

    def upload(self, task, data, mime, filename=None):
        from project_docs import http
        mime = media.validate(data, mime)
        if self.lease_lost():
            raise worker.WorkerError("Media execution was canceled before upload.")
        with http.open_connection() as conn:
            identifier = repo.put_asset(conn, self.task["_slug"], data=data, content_type=mime, actor_id=self.task["_actor"])
        return {"asset_id": identifier, "asset_url": f"/projects/api/{self.task['_slug']}/assets/{identifier}", "content_type": mime}


def execute_task(identifier):
    from project_docs import http
    from project_assistant.execution_governance import AdmissionError
    try:
        with http.open_connection() as conn:
            task = record(conn, identifier, lock=True)
            if task["status"] != "QUEUED":
                return
            task["status"] = "RUNNING"
            store(conn, identifier, "task", task)
        me = service.Identity(task["_actor"], "Story worker", "member")
        job, slug = task["_job"], task["_slug"]
        head = StoryHead(task)
        if task["type"] == "SCRIPT_REFINE":
            from project_assistant import providers
            from project_assistant import execution_governance as governance, agent_registry
            config = providers.provider_from_env()
            with http.open_connection() as conn:
                profile = agent_registry.get_agent(conn, slug, 'coordinator')
            result = providers.run_openai_compat_turn(config=config, admission=governance.ProviderAdmission(head.accounting_context, profile, config),
                instructions="Rewrite the supplied screenplay according to the instruction. Preserve asset tags and scene headings. Return only the complete screenplay, without commentary.",
                turn_text=job["instruction"] + "\n\nSCREENPLAY:\n" + job["script"], call_tool=lambda *args: "Unavailable", timeout=180, tool_specs=[])
            if result.status != "ok" or not result.answer.strip():
                raise worker.WorkerError("Script refinement failed; verify the configured model endpoint.")
            output = {"scriptContent": result.answer}
        elif task["type"] == "FILM_EXPORT":
            from project_assistant import execution_governance as governance
            from project_docs import story_trim
            output = governance.run_operation(head.accounting_context, identifier + ':export', lambda: worker.ffmpeg({"id": identifier, "project_slug": slug, "input": {"rows": story_trim.film_rows(job)}},
                                   dict(job["config"], timeout=head.outbound_timeout(job['config'].get('timeout',1800)),
                                        probe_timeout=head.outbound_timeout(job['config'].get('probe_timeout',60))), head))
        else:
            with http.open_connection() as conn:
                authorize(conn, me, slug, write=True)
                authorize_card(conn, slug, job["card"])
            from project_docs import story_take_refs
            refs = prepare_take_refs(identifier, slug, job, head)
            # project_slug lets the worker check that media it is pointed at (extract_frame source_url) is this production's.
            execution = {"id": identifier, "project_slug": slug, "capability": job["kind"] + "_gen",
                         "input": story_take_refs.worker_input(job["input"], refs),
                         "workflow": job["workflow"], "production_policy": job.get("production_policy")}
            if job.get("allocation"):
                from project_docs import story_allocation
                output = story_allocation.execute_steps(execution, job["allocation"]["stages"], head, job["values"])
            else:
                from project_assistant import execution_governance as governance
                head.accounting_card = job['card']
                head.accounting_destination = governance.media_destination(job['card'])
                output = governance.run_operation(head.accounting_context, job['_accounting_keys']['generate'],
                    lambda: worker.execute_story_card(execution, job['card'], job['values'], head), card=job['card'],
                    wait_for_capacity=task['type'] == 'ASSET_IMAGE_GENERATE')
        with http.open_connection() as conn:
            current = record(conn, identifier, lock=True)
            if current["status"] != "RUNNING":
                return
            member = next((m for m in repo.active_members(conn) if m["actor_id"] == me.actor_id), None)
            if not member or member.get("role") == "viewer":
                raise worker.WorkerError("The requesting crew member no longer has write access.")
            me = service.Identity(me.actor_id, me.name, member["role"])
            authorize(conn, me, slug, write=True)
            if job.get("card"):
                authorize_card(conn, slug, job["card"])
            if task["type"] == "SCRIPT_REFINE":
                ep = episode(conn, job["episodeId"])
                repo.get_tab_for_update(conn, slug, ep["tabKey"])
                if script(conn, ep) != job["script"]:
                    raise worker.WorkerError("The script changed while refinement was running; the newer script was preserved.")
                set_script(conn, me, ep, output["scriptContent"])
                result = {"episodeId": ep["episodeId"]}
            elif task["type"] == "FILM_EXPORT":
                # segments: where every clip came from (SPEC_19); a job queued before they existed has none to report.
                result = {"fileId": output["asset_id"], "videoUrl": output["asset_url"],
                          **({"segments": job["segments"]} if "segments" in job else {})}
                store(conn, "fl_" + identifier, "film", {**result, "episodeId": job["episodeId"], "filmId": "fl_" + identifier}, slug)
            else:
                if not output["content_type"].startswith(job["kind"] + "/"):
                    raise worker.WorkerError("The card produced the wrong media type.")
                result = {job["kind"] + "Url": output["asset_url"]}
                from project_docs import writing_impact
                evidence = job.get('storyProvenance')
                if job['entityId'].startswith('sh_'):
                    result = writing_impact.candidate_view(result, evidence)
                store(conn, "ca_" + identifier, "candidate", {"entityId": job["entityId"], "kind": job["kind"], "url": output["asset_url"],
                      "createdAt": now(), **({'storyProvenance': evidence} if job['entityId'].startswith('sh_') else {})}, slug)
                repo.get_tab_for_update(conn, slug, job["row"]["tabKey"])
                _, row = find_row(conn, job["entityId"], "shot" if job["entityId"].startswith("sh_") else "asset")
                from project_docs import story_adoption
                # An adopted shot keeps the take that is in the cut: a new render only joins its candidates (SPEC_19 R2).
                adopted = job['entityId'].startswith('sh_') and story_adoption.row_status(row) in story_adoption.ADOPTED
                # A delayed render is kept as a candidate, not allowed to overwrite a newer selection.
                if not adopted and row["cells"] == job["row"]["cells"] and (not job['entityId'].startswith('sh_') or writing_impact.provenance_matches(conn, me, job['entityId'], evidence)):
                    mutate_row(conn, me, slug, row["tabKey"], row["rid"], {job["column"]: f"[{job['kind']}]({output['asset_url']})"})
                    if job["kind"] == "video" and job["entityId"].startswith("sh_"):
                        from project_docs import story_trim
                        story_trim.reset(conn, slug, job["entityId"])
                    result["selected"] = True
                else:
                    result["selected"] = False
            current.update(status="SUCCEEDED", result=result, finishedAt=now())
            store(conn, identifier, "task", current)
        notify(task["_actor"], public_task(current))
    except Exception as exc:
        try:
            with http.open_connection() as conn:
                current = record(conn, identifier, required=False, lock=True)
                if not current or current["status"] == "CANCELED":
                    return
                message = str(exc) if isinstance(exc, (StoryError, worker.WorkerError, AdmissionError)) else "Execution failed; check worker deployment and media inputs."
                current["_paid_ambiguous"] = bool(getattr(exc, "no_retry", False) or getattr(locals().get("head"), "paid_request_submitted", False))
                from project_assistant.execution_governance import release_unstarted
                release_unstarted(conn,current['_slug'],current.get('_job',{}).get('_accounting_keys',{}).values())
                current.update(status="FAILED", error={"code": "DRAMA_REQUEST_FAILED", "message": message[:500]}, finishedAt=now())
                store(conn, identifier, "task", current)
            notify(current["_actor"], public_task(current))
        except Exception:
            pass  # A lost database connection must not leak credentials through the HTTP response.


def task_for(conn, me, identifier):
    task = record(conn, identifier)
    with conn.cursor() as cur:
        cur.execute("SELECT owner_id::text FROM projectops.story_record WHERE id=%s", (identifier,))
        owner = cur.fetchone()[0]
    if owner != me.actor_id:
        raise StoryError(404, "DRAMA_NOT_FOUND", "Task not found.")
    if task.get("_process") not in (None, _PROCESS) and task["status"] in ("QUEUED", "RUNNING"):
        task.update(status="FAILED", error={"code": "DRAMA_REQUEST_FAILED", "message": "Server restarted; explicitly retry this interrupted task."}, finishedAt=now())
        store(conn, identifier, "task", task)
    return task


def owned(conn, me, identifier, kind):
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM projectops.story_record WHERE id=%s AND kind=%s AND owner_id=%s", (identifier, kind, me.actor_id))
        if not cur.fetchone():
            raise StoryError(404, "DRAMA_NOT_FOUND", "Resource not found.")
    return record(conn, identifier)


def file_bytes(conn, identifier):
    with conn.cursor() as cur:
        cur.execute("SELECT blob FROM projectops.story_record WHERE id=%s AND kind='file'", (identifier,))
        row = cur.fetchone()
    if not row or row[0] is None:
        raise StoryError(404, "DRAMA_NOT_FOUND", "File content not found.")
    return bytes(row[0])


def webhook_address(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.fragment or parts.port not in (None, 443):
        invalid("Webhook URL must be a public HTTPS address on port 443.")
    try:
        addresses = [info[4][0] for info in socket.getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)]
    except OSError:
        invalid("Webhook host could not be resolved.")
    if not addresses or any(not ipaddress.ip_address(addr).is_global for addr in addresses):
        invalid("Private, loopback and reserved webhook addresses are not allowed.")
    return parts, addresses[0]


def retry_delivery(identifier, delay):
    timer = threading.Timer(max(0, delay), lambda: _POOL.submit(deliver, identifier))
    timer.daemon = True
    timer.start()


def resume_deliveries(conn):
    for item in records(conn, "delivery"):
        if item["status"] in ("QUEUED", "RUNNING"):
            retry_delivery(item["deliveryId"], item.get("nextAttemptAt", time.time()) - time.time())


def deliver(delivery_id):
    from project_docs import http
    with http.open_connection() as conn:
        item = record(conn, delivery_id, required=False, lock=True)
        if not item or item["status"] not in ("QUEUED", "RUNNING") or item.get("_process") == _PROCESS and item["status"] == "RUNNING":
            return
        hook = record(conn, item["webhookId"], required=False)
        if not hook:
            item.update(status="DEAD", finishedAt=now())
            store(conn, delivery_id, "delivery", item)
            return
        item.update(status="RUNNING", attempts=item.get("attempts", 0) + 1, _process=_PROCESS)
        store(conn, delivery_id, "delivery", item)
        event = item["event"]
    status = "FAILED"
    try:
        parts, address = webhook_address(hook["url"])
        raw = json.dumps(event, separators=(",", ":")).encode()
        stamp = str(int(time.time()))
        signature = hmac.new(hook["secret"].encode(), stamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
        connection = HTTPSConnection(parts.hostname, timeout=10)
        # Pin the validated address; preserve TLS SNI and never follow redirects.
        connection.sock = ssl.create_default_context().wrap_socket(socket.create_connection((address, 443), timeout=10), server_hostname=parts.hostname)
        try:
            connection.request("POST", parts.path + ("?" + parts.query if parts.query else ""), raw,
                {"Content-Type": "application/json", "X-RH-Signature": f"t={stamp},v1={signature}",
                 "X-RH-Event-Id": event["eventId"], "X-RH-Event-Type": event["eventType"]})
            response = connection.getresponse()
            status = "SUCCEEDED" if 200 <= response.status < 300 else "FAILED"
        finally:
            connection.close()
    except Exception:
        pass
    delay = None
    with http.open_connection() as conn:
        item = record(conn, delivery_id, required=False, lock=True)
        if item:
            backoff = [60, 300, 1800, 7200, 43200]
            if status == "FAILED" and item["attempts"] <= len(backoff):
                delay = backoff[item["attempts"] - 1]
                item.update(status="QUEUED", nextAttemptAt=time.time() + delay)
            else:
                item.update(status="SUCCEEDED" if status == "SUCCEEDED" else "DEAD", finishedAt=now())
            store(conn, delivery_id, "delivery", item)
    if delay is not None:
        retry_delivery(delivery_id, delay)


def schedule_delivery(conn, me, hook, event, actions):
    identifier = "dl_" + uuid.uuid4().hex
    item = {"deliveryId": identifier, "webhookId": hook["webhookId"], "event": event, "status": "QUEUED", "createdAt": now()}
    store(conn, identifier, "delivery", item, owner=me.actor_id)
    actions.append(lambda: _POOL.submit(deliver, identifier))
    return item


def notify(owner, task):
    from project_docs import http
    actions = []
    with http.open_connection() as conn:
        for hook in records(conn, "webhook", owner=owner):
            event = {"eventId": str(uuid.uuid4()), "eventType": "task." + task["status"].lower(), "version": 1, "occurredAt": now(), "data": task}
            schedule_delivery(conn, service.Identity(owner, "", "member"), hook, event, actions)
    for action in actions:
        action()


def auto_cut_checks(conn, me, slug, shot_id, actions):
    """SPEC_19 decision 8: with auto grading on, a new adoption or trim queues the cut checks next to the shot."""
    from project_assistant import take_grader
    from project_docs import story_cuts
    if story_cuts.on_adoption_changed(conn, slug, shot_id, me.actor_id):
        actions.append(take_grader.kick)


def dispatch(conn, me, method, path, body, query, actions):
    """Return unwrapped data; callers own commit, rollback and post-commit launches."""
    from project_docs import story_alignment, story_estimates
    previewed = story_alignment.dispatch(conn, me, method, path, body)  # read-only previews, open to viewers
    if previewed is None:
        previewed = story_estimates.dispatch(conn, me, method, path, body)
    if previewed is not None:
        return previewed
    from project_docs import writing_http, writing_store
    writing_match = writing_http.ROUTE.fullmatch(path)
    if writing_match:
        tail = writing_match[2] or 'workspace'
        scope = writing_store.scope_for(conn, me, writing_match[1], write=not (method == 'GET' or (method == 'POST' and tail in ('search','compare','exports'))))
        return writing_http.dispatch(conn, scope, method, tail, body, query)
    if method != "GET" and not me.can_write:
        raise StoryError(409, "DRAMA_OPERATION_NOT_ALLOWED", "Read-only crew members cannot modify productions.")
    parts = path.strip("/").split("/")
    if any(k.startswith("_") for k in body):
        invalid("Private execution inputs cannot be supplied by clients.")
    from project_docs import story_allocation
    integrated = story_allocation.dispatch(conn, me, method, parts, body, actions)
    if integrated is not None:
        return integrated
    if method != "GET":
        target = parts[1] if len(parts) > 1 else str(body.get("slug", "new-production"))
        match = re.match(r"(?:pj_|ep_|as_|sh_|sc_)([a-z0-9-]+)(?:_|$)", target)
        scope = match[1] if match else target
        from project_assistant.orchestrator import lock_project
        lock_project(conn, scope)
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("story-write:" + scope,))
    if path == "/capabilities" and method == "GET":
        return {"version": "v1", "site": "AI", "baseUrl": BASE, "stages": STAGES,
                "rateLimit": {"replenishRatePerSecond": 50, "burstCapacity": 100},
                "features": {k: True for k in ["files", "projectImport", "scriptTools", "editing", "assetEditing", "batchGeneration", "taskRetry", "webhookDeliveries", "usage"]} | {"sandbox": False}}
    if parts[0] == "catalog" and method == "GET":
        if path == "/catalog/apps":
            capability = query.get("capability")
            if capability not in ("IMAGE", "VIDEO"):
                invalid("capability must be IMAGE or VIDEO.")
            scope = query.get("usageScope")
            if scope and scope not in USAGE_SCOPES:
                invalid("Unknown usageScope.")
            from project_docs import story_generation_options as options
            return page([item for card, item in catalog_entries() if item["capability"] == capability
                         and (not scope or options.in_scope(card, scope))], query)
        if path == "/catalog/styles":
            return page(STYLES, query)
        if path == "/catalog/director-styles":
            return page([{"directorStyleId": str(i + 1), "name": name} for i, name in enumerate(["ARRI Alexa 65 / 35mm Anamorphic", "RED V-Raptor / 85mm Prime", "16mm Bolex"])], query)
        if path == "/catalog/aspect-ratios":
            return page([{"aspectRatio": r} for r in RATIOS], query)
    if path in ("/project-imports", "/project-generations") and method == "POST":
        if ("scriptContent" in body) == ("scriptFileId" in body):
            raise StoryError(400, "DRAMA_REQUEST_FAILED", "Provide exactly one of scriptContent or scriptFileId.")
        content = text(body, "scriptContent", maximum=500000) if "scriptContent" in body else owned(conn, me, body["scriptFileId"], "file").get("content", "")
        if not content.strip():
            raise StoryError(422, "DRAMA_SCRIPT_INVALID", "The script cannot be empty.")
        created = dispatch(conn, me, "POST", "/projects", body, {}, actions)
        slug = created["projectId"][3:]
        chunks = re.split(r"(?mi)^\s*(?:#{1,3}\s*)?(?:Episode\s+\d+|第[一二三四五六七八九十\d]+[集話话])[^\n]*\n", content)
        chunks = [c for c in chunks if c.strip()]
        all_ep = []
        for i, chunk in enumerate(chunks or [content], 1):
            ep = episodes(conn, slug)[0] if i == 1 else dispatch(conn, me, "POST", f"/projects/pj_{slug}/episodes", {"title": f"Episode {i}"}, {}, actions)
            set_script(conn, me, ep, chunk)
            if "aspectRatio" in body or "stylePresetId" in body:
                settings = {k: body[k] for k in ("aspectRatio", "stylePresetId") if k in body}
                dispatch(conn, me, "PUT", f"/episodes/{ep['episodeId']}/settings", settings, {}, actions)
            all_ep.append(ep)
        return completed_task(conn, me, slug, "PROJECT_IMPORT" if path.endswith("imports") else "PROJECT_GENERATE",
                              {"projectId": created["projectId"], "episodeId": all_ep[0]["episodeId"], "episodeCount": len(all_ep), "episodes": all_ep})
    if path == "/projects":
        if method == "GET":
            return page([project(conn, p["slug"]) for p in repo.list_projects(conn)], query)
        if method == "POST":
            title = text(body, "title", maximum=200).strip()
            if not title:
                invalid("A production title is required.")
            slug = text(body, "slug", "story-" + uuid.uuid4().hex[:12], 41)
            status, result = service.create_project(conn, me, {"slug": slug, "title": title, "summary": text(body, "description", maximum=400), "template": "zerofield_studio"})
            if status != 200:
                invalid(result["error"])
            # The planning template remains unchanged; API-created productions start without demo rows.
            for key in ("soul-cast", "cinema-studio", "openjutsu-lab"):
                tab = repo.get_tab(conn, slug, key)
                doc = copy.deepcopy(tab["doc"])
                for table in doc["content"]:
                    if table.get("type") == "table":
                        table["content"] = table["content"][:1]
                save_doc(conn, me, slug, key, doc)
            save_doc(conn, me, slug, "director-brief", {"type": "doc", "content": [{"type": "paragraph", "attrs": {"bid": new_id('b')}}]})
            ep = episodes(conn, slug)[0]
            store(conn, ep["episodeId"], "episode", ep, slug)
            return project(conn, slug)
    if parts[0] == "projects" and len(parts) >= 2:
        p = project(conn, parts[1]); slug = p["slug"]
        authorize(conn, me, slug, write=method != "GET")
        if len(parts) == 2:
            if method == "GET":
                return p
            if method == "PATCH":
                update = {k: body[src] for k, src in (("title", "title"), ("summary", "description")) if src in body}
                status, result = service.update_project(conn, me, slug, update)
                if status != 200:
                    invalid(result["error"])
                return project(conn, slug)
            if method == "DELETE":
                if not me.can_edit:
                    raise StoryError(409, "DRAMA_OPERATION_NOT_ALLOWED", "Only the showrunner may delete a production.")
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM projectops.limb_task WHERE project_slug=%s", (slug,))
                    cur.execute("DELETE FROM projectops.flow_run WHERE project_slug=%s", (slug,))
                    cur.execute("DELETE FROM projectops.flow_definition WHERE project_slug=%s", (slug,))
                    cur.execute("DELETE FROM projectops.project WHERE slug=%s", (slug,))
                return {"deleted": True}
        if len(parts) == 3 and parts[2] == "grading" and method in ("GET", "PUT"):
            from project_assistant import take_grader
            if method == "PUT":
                if not isinstance(body.get("autoGrade"), bool):
                    invalid("autoGrade must be true or false.")
                take_grader.set_auto(conn, slug, body["autoGrade"])
            return {"autoGrade": take_grader.auto_enabled(conn, slug)}
        if len(parts) == 3 and parts[2] == "episodes":
            if method == "GET":
                return page([episode_view(conn, e) for e in episodes(conn, slug)], query)
            if method == "POST":
                i = max((e["episodeIndex"] for e in episodes(conn, slug)), default=0) + 1
                key = f"director-brief-ep{i:02d}"
                title = text(body, "title", f"Episode {i}", 200)
                doc, _ = markdown_import.markdown_to_doc(f"# {title}\n", tab_keys=set(), image_src=lambda _: None)
                doc, _ = validate_doc(doc, slug=slug)
                repo.create_tab(conn, slug, key=key, title=title, parent_key=None, doc=doc, actor_id=me.actor_id)
                ep = {"episodeId": f"ep_{slug}_{i:02d}", "slug": slug, "projectId": p["projectId"], "episodeIndex": i, "title": title, "tabKey": key, "settings": {}}
                return store(conn, ep["episodeId"], "episode", ep, slug)
    if parts[0] == "episodes" and len(parts) >= 2:
        ep = episode(conn, parts[1]); slug = ep["slug"]
        authorize(conn, me, slug, write=method != "GET")
        tail = "/".join(parts[2:])
        if tail in ("cuts", "cut-checks"):
            from project_docs import story_cuts
            result = story_cuts.dispatch(conn, me, method, tail, ep, body, actions)
            if result is not None:
                return result
        if not tail:
            if method == "GET":
                return episode_view(conn, ep)
            if method == "PATCH":
                ep["title"] = text(body, "title", ep["title"], 200)
                store(conn, ep["episodeId"], "episode", ep, slug)
                return episode_view(conn, ep)
        if tail == "script" and method == "PUT":
            if "breakdownMode" in body:
                ep["breakdownMode"] = text(body, "breakdownMode")
                if ep["breakdownMode"] not in BREAKDOWN_MODES:
                    invalid("Unknown breakdownMode.")
            return set_script(conn, me, ep, text(body, "scriptContent", maximum=500000))
        if tail == "script-adaptations" and method == "POST":
            raw = text(body, "sourceText", maximum=500000)
            mode = text(body, "sourceMode", "auto")
            breakdown = text(body, "breakdownMode", "auto")
            if breakdown not in BREAKDOWN_MODES:
                invalid("Unknown breakdownMode.")
            style = next((s["name"] for s in STYLES if s["stylePresetId"] == str(ep.get("settings", {}).get("stylePresetId", "88123"))), STYLES[0]["name"])
            # Without a lens or choice trace the request is the SPEC_13 adaptation and its response is unchanged.
            composed = any(body.get(key) is not None for key in ("mediumLens", "genreLens", "choiceTrace"))
            trace = contrast = None
            try:
                if composed:
                    medium, genre = composition_lenses(body.get("mediumLens"), body.get("genreLens"))
                    if body.get("choiceTrace") is not None:
                        trace = choice_trace_input(body["choiceTrace"])
                        contrast = compute_choice_contrast(choice_traces(conn, ep), trace["focus"])
                    content = adapt_source_to_script(raw, mode, body.get("targetScenes", 3), style, medium, genre, trace, contrast)
                else:
                    content = adapt_source_to_script(raw, mode, body.get("targetScenes", 3), style)
            except ValueError as exc:
                invalid(str(exc))
            ep["breakdownMode"] = breakdown
            ep.pop("extractedAssetCodes", None)
            set_script(conn, me, ep, content)
            result = {"episodeId": ep["episodeId"], "script": {"content": content}, "sourceMode": source_mode(raw, mode),
                      "breakdownMode": breakdown, "engine": "deterministic"}
            if composed:
                result |= {"mediumLens": medium, "genreLens": genre, "voiceAudit": audit_narrative_voice(content)}
            if trace:
                trace_id = "ctr_" + uuid.uuid4().hex
                result["choiceTrace"] = store(conn, trace_id, "choice_trace", {
                    "traceId": trace_id, "episodeId": ep["episodeId"], "mediumLens": medium, "genreLens": genre, **trace,
                    "contrastDetected": contrast["contrastDetected"], "contrastCue": contrast["contrastCue"], "createdAt": now()}, slug, me.actor_id)
            return result
        if tail == "story-collisions" and method == "POST":
            try:
                proposal = propose_story_collisions(text(body, "sourceText", maximum=500000), body.get("mediumLens", "manju"), body.get("genreLens", "general"))
            except ValueError as exc:
                invalid(str(exc))
            return {**proposal, "recentTraces": choice_traces(conn, ep)[-5:]}
        if tail == "choice-traces" and method == "GET":
            return page(choice_traces(conn, ep), query)
        if tail == "script/versions" and method == "GET":
            return page([{"versionId": str(r["revision"]), "scriptContent": doc_text(r["doc"])} for r in repo.revision_rows(conn, slug, tab_key=ep["tabKey"])], query)
        if tail == "script-refinements" and method == "POST":
            instruction = text(body, "instruction").strip()
            if not instruction:
                invalid("A script refinement instruction is required.")
            if not os.environ.get("OPENBENCH_MODEL") or not os.environ.get("OPENBENCH_API_BASE"):
                raise StoryError(409, "DRAMA_STAGE_PRECONDITION", "Configure OPENBENCH_MODEL and OPENBENCH_API_BASE for script refinement.")
            return queue_task(conn, me, slug, "SCRIPT_REFINE", {"episodeId": ep["episodeId"], "instruction": instruction, "script": script(conn, ep)}, actions)
        if tail == "settings":
            if method == "PUT":
                if "breakdownMode" in body:
                    value = text(body, "breakdownMode")
                    if value not in BREAKDOWN_MODES:
                        invalid("Unknown breakdownMode.")
                    ep["breakdownMode"] = value
                if body.get("aspectRatio", "16:9") not in RATIOS:
                    invalid("Unsupported aspectRatio.")
                if str(body.get("stylePresetId", "88123")) not in {s["stylePresetId"] for s in STYLES}:
                    raise StoryError(422, "DRAMA_STYLE_NOT_FOUND", "Unknown style preset.")
                ep["settings"] = body
                store(conn, ep["episodeId"], "episode", ep, slug)
            if method in ("GET", "PUT"):
                return ep.get("settings", {})
        if tail == "asset-extractions" and method == "POST":
            return extract(conn, me, ep)
        if tail == "storyboards" and method == "POST":
            return build_shots(conn, me, ep, breakdown_mode=text(body, "breakdownMode") if "breakdownMode" in body else None)
        if tail == "asset-image-generations" and method == "POST":
            repo.get_tab_for_update(conn, slug, ep["tabKey"])
            if ep.get("confirmedHash") != digest(script(conn, ep)):
                raise StoryError(409, "DRAMA_STAGE_PRECONDITION", "Confirm Script & Extract Assets before generating reference sheets.")
            missing, known = missing_episode_assets(conn, ep)
            if any(code not in known for code in missing):
                raise StoryError(409, "DRAMA_STAGE_PRECONDITION", "Extract script assets before generating missing reference sheets.")
            if len(missing) > 200:
                invalid("Generate at most 200 missing assets in one batch.")
            request = {"appCode": "flux-soul-cast", **body}
            # Validate every source before admission; queue_task retains budget and authority checks.
            jobs = [generation_job(conn, me, known[code]["assetId"], "image", request) for code in missing]
            for _, job in jobs:
                job["episodeId"] = ep["episodeId"]
            tasks = [queue_task(conn, me, job_slug, "ASSET_IMAGE_GENERATE", job, actions) for job_slug, job in jobs]
            identifier = "tg_" + uuid.uuid4().hex
            return store(conn, identifier, "taskGroup", {"taskGroupId": identifier, "taskIds": [t["taskId"] for t in tasks],
                         "assetCodes": missing}, slug, me.actor_id)
        if tail == "assets":
            if method == "GET":
                from project_docs import story_asset_edit
                everything = assets(conn, ep)
                return page(story_asset_edit.with_looks([a for a in everything if a["isDefault"]], everything), query)
            if method == "POST":
                prefix = {"CHARACTER": "CAST", "SCENE": "SET", "PROP": "PROP"}.get(body.get("type", "CHARACTER"))
                if not prefix:
                    invalid("Asset type must be CHARACTER, SCENE or PROP.")
                codes = {a["assetCode"] for a in assets(conn, ep)}
                i = 1
                while f"{prefix}-{i:02d}" in codes:
                    i += 1
                rid = mutate_row(conn, me, slug, "soul-cast", cells={0: f"{prefix}-{i:02d}", 1: text(body, "name"), 2: text(body, "prompt"), 5: "Queued"})
                return asset_view(slug, find_row(conn, f"as_{slug}_{rid}", "asset")[1])
        if tail == "scenes":
            if method == "GET":
                return page(scenes(conn, ep), query)
            if method == "POST":
                items = scenes(conn, ep) + [{"title": text(body, "title", "Scene"), "content": text(body, "content")}]
                write_scenes(conn, me, ep, items)
                return scenes(conn, ep)[-1]
        if tail == "scene-order" and method == "PUT":
            items = scenes(conn, ep); order = body.get("sceneIds")
            if not isinstance(order, list) or len(order) != len(items) or set(order) != {s["sceneId"] for s in items}:
                invalid("sceneIds must contain every scene exactly once.")
            write_scenes(conn, me, ep, [next(s for s in items if s["sceneId"] == sid) for sid in order])
            return {"items": scenes(conn, ep)}
        if tail == "shots" and method == "GET":
            from project_docs import story_adoption
            return page(shots(conn, ep, takes=story_adoption.Takes(conn, slug)), query)
        if tail in ("shot-image-generations", "shot-video-generations") and method == "POST":
            chosen = shots(conn, ep)
            if "shotIds" in body:
                ids = body["shotIds"]
                if not isinstance(ids, list) or not set(ids) <= {s["shotId"] for s in chosen}:
                    invalid("shotIds must belong to this episode.")
                chosen = [s for s in chosen if s["shotId"] in ids]
            if not chosen or len(chosen) > 200:
                invalid("Select between 1 and 200 shots.")
            kind = "image" if tail == "shot-image-generations" else "video"
            if body.get("allocationId"):
                tasks = story_allocation.apply_batch(conn, me, ep, chosen, kind, body, actions)
            else:
                jobs=[generation_job(conn,me,s['shotId'],kind,body) for s in chosen]
                tasks=[queue_task(conn,me,job_slug,'SHOT_'+kind.upper()+'_GENERATE',job,actions) for job_slug,job in jobs]
            identifier = "tg_" + uuid.uuid4().hex
            group = {"taskGroupId": identifier, "taskIds": [t["taskId"] for t in tasks]}
            return store(conn, identifier, "taskGroup", group, slug, me.actor_id)
        if tail == "films":
            if method == "GET":
                return page([f for f in records(conn, "film", slug) if f["episodeId"] == ep["episodeId"]], query)
            if method == "POST":
                from project_docs import story_trim
                selection, fill = film_options(body)
                plan = film_plan(shots(conn, ep), selection, fill)
                if not plan:
                    raise StoryError(409, "DRAMA_STAGE_PRECONDITION", "Adopt at least one shot before exporting a film." if selection == "adopted"
                                     else "Select at least one shot video before exporting a film.")
                clips = [(shot, url) for shot, url, _ in plan]
                return queue_task(conn, me, slug, "FILM_EXPORT", {"episodeId": ep["episodeId"], "urls": [url for _, url in clips],
                                                                   "trims": story_trim.film_trims(clips), "config": {},
                                                                   "segments": [{"shotId": shot["shotId"], "source": source} for shot, _, source in plan]}, actions)
    if parts[0] in ("assets", "shots") and len(parts) >= 2:
        identifier = parts[1]; entity = "asset" if parts[0] == "assets" else "shot"
        slug, row = find_row(conn, identifier, entity); tail = "/".join(parts[2:])
        authorize(conn, me, slug, write=method != "GET")
        from project_docs import story_adoption
        view = lambda: asset_view(slug, find_row(conn, identifier, entity)[1]) if entity == "asset" else shot_view(conn, slug, find_row(conn, identifier, entity)[1], takes=story_adoption.Takes(conn, slug))
        if not tail:
            if method == "GET":
                result = view()
                if entity == "asset":
                    result["variants"] = [asset_view(slug, r) | {"variantId": "vr_" + r["rid"]} for r in table_rows(conn, slug, "soul-cast") if r["cells"][0].upper().startswith(result["assetCode"] + ":")]
                    usages = [s for ep in episodes(conn, slug) for s in shots(conn, ep)
                              if any(code == result["assetCode"] or code.startswith(result["assetCode"] + ":") for code in s["assets"])]
                    result["shotIds"] = [s["shotId"] for s in usages]
                    result["sceneIds"] = list(dict.fromkeys(s["sceneId"] for s in usages if s.get("sceneId")))
                return result
            if method == "PATCH":
                mapping = {"name": 1, "prompt": 2} if entity == "asset" else {"shotIndex": 0, **{key: next((i for i, h in enumerate(row["headers"]) if re.search(pattern, h, re.I)), -1)
                    for key, pattern in (("opticalRig", r"optical|rig"), ("cameraMotion", r"camera.*motion"), ("description", r"prompt"))}}
                if any(index < 0 for key, index in mapping.items() if key in body):
                    invalid("This production sheet has no matching column for the requested field.")
                edits = {index: text(body, key) for key, index in mapping.items() if key in body}
                if entity == "asset":
                    from project_docs import story_asset_edit
                    edits |= story_asset_edit.extra_edits(row, body)  # voice, status, notes
                mutate_row(conn, me, slug, row["tabKey"], row["rid"], edits)
                return view()
            if method == "DELETE":
                mutate_row(conn, me, slug, row["tabKey"], row["rid"], delete=True)
                return {"deleted": True}
        if tail == "generation-options" and method == "GET":
            from project_docs import story_generation_options as options
            return options.describe(conn, slug, identifier, entity, row, query)
        if tail in ("image-generations", "video-generations") and method == "POST":
            return generation(conn, me, identifier, "image" if tail == "image-generations" else "video", body, actions)
        if tail in ("images", "videos") and method == "GET":
            return page(candidate_list(conn, identifier, "image" if tail == "images" else "video"), query)
        if tail == "images" and method == "POST":
            file = owned(conn, me, text(body, "fileId"), "file")
            if file["purpose"] != "IMAGE":
                invalid("An IMAGE file is required.")
            raw = file_bytes(conn, file["fileId"])
            aid = repo.put_asset(conn, slug, data=raw, content_type=file["contentType"], actor_id=me.actor_id)
            url = f"/projects/api/{slug}/assets/{aid}"
            store(conn, "ca_" + uuid.uuid4().hex, "candidate", {"entityId": identifier, "kind": "image", "url": url, "createdAt": now()}, slug)
            return next(c for c in candidate_list(conn, identifier, "image") if c["url"] == url)
        if tail in ("selected-image", "selected-video") and method == "PUT":
            return select_candidate(conn, me, identifier, "image" if tail.endswith("image") else "video", body)
        if entity == "shot" and tail == "adoptions" and method == "POST":
            adopted = story_adoption.adopt(conn, me, identifier, body)
            if "imageId" not in body:  # a first frame does not change the cut
                auto_cut_checks(conn, me, slug, identifier, actions)
            return adopted
        if entity == "shot" and tail == "adoption" and method == "DELETE":
            return story_adoption.unadopt(conn, me, identifier)
        if entity == "shot" and tail == "trim" and method == "PUT":
            from project_docs import story_trim
            story_trim.set_trim(conn, slug, identifier, row, body)
            auto_cut_checks(conn, me, slug, identifier, actions)
            return view()
        if entity == "shot" and tail == "grades":
            from project_assistant import take_grader
            if method == "GET":
                return page(take_grader.grades(conn, slug, identifier), query) | {"autoGrade": take_grader.auto_enabled(conn, slug)}
            if method == "POST":
                # A listed take (videoId) or a worker output still waiting for approval (assetUrl).
                take = next((c for c in candidate_list(conn, identifier, "video") if c["videoId"] == body.get("videoId")), None) if "videoId" in body else None
                if "videoId" in body and not take:
                    raise StoryError(404, "DRAMA_NOT_FOUND", "Take does not belong to this row.")
                try:
                    grade = take_grader.enqueue(conn, slug, identifier, take["url"] if take else text(body, "assetUrl"), me.actor_id)
                except take_grader.GradeError as exc:
                    invalid(str(exc))
                actions.append(take_grader.kick)
                return grade
        if entity == "asset" and tail == "variants":
            base = row["cells"][0].upper().split(":")[0]
            variants = [asset_view(slug, r) | {"variantId": "vr_" + r["rid"]} for r in table_rows(conn, slug, "soul-cast") if r["cells"][0].upper().startswith(base + ":")]
            if method == "GET":
                return page(variants, query)
            if method == "POST":
                if body.get("kind", "OUTFIT") not in ("OUTFIT", "POSE", "LOOK"):
                    invalid("Variant kind must be OUTFIT, POSE or LOOK.")
                name = text(body, "name").strip()
                key = text(body, "key", re.sub(r"[^a-z0-9_-]", "-", name.lower()).strip("-") or uuid.uuid4().hex[:8], 60)
                if not re.fullmatch(r"[a-z0-9_-]+", key) or any(v["assetCode"] == base + ":" + key.upper() for v in variants):
                    invalid("Use a unique variant key containing letters, digits, underscores or hyphens.")
                rid = mutate_row(conn, me, slug, "soul-cast", cells={0: base + ":" + key, 1: name, 2: text(body, "prompt"), 5: "Queued", 6: body.get("kind", "OUTFIT")})
                return asset_view(slug, find_row(conn, f"as_{slug}_{rid}", "asset")[1]) | {"variantId": "vr_" + rid}
        if entity == "asset" and tail.startswith("variants/") and method in ("PATCH", "DELETE"):
            rid = parts[3].removeprefix("vr_")
            variant = next((r for r in table_rows(conn, slug, "soul-cast") if r["rid"] == rid and r["cells"][0].upper().startswith(row["cells"][0].upper().split(":")[0] + ":")), None)
            if not variant:
                raise StoryError(404, "DRAMA_NOT_FOUND", "Variant does not belong to this asset.")
            mutate_row(conn, me, slug, "soul-cast", rid, {i: text(body, k) for k, i in (("name", 1), ("prompt", 2)) if k in body}, delete=method == "DELETE")
            return {"variantId": parts[3], "deleted": method == "DELETE"}
        if entity == "shot" and tail == "assets" and method == "PUT":
            codes = body.get("assetCodes", body.get("assetIds", []))
            known = {a["assetCode"]: a["assetCode"] for ep in episodes(conn, slug)[:1] for a in assets(conn, ep)}
            known.update({a["assetId"]: a["assetCode"] for ep in episodes(conn, slug)[:1] for a in assets(conn, ep)})
            if not isinstance(codes, list) or any(c not in known for c in codes):
                invalid("Bind assets from this production only.")
            column = next((i for i, h in enumerate(row["headers"]) if re.search("prompt", h, re.I)), 3)
            content = ASSET_RE.sub("", row["cells"][column]).strip() + " " + " ".join("@" + known[c] for c in codes)
            mutate_row(conn, me, slug, row["tabKey"], row["rid"], {column: content.strip()})
            return view()
        if entity == "asset" and tail == "scenes" and method == "PUT":
            ids = body.get("sceneIds", [])
            if not isinstance(ids, list):
                invalid("sceneIds must be an array.")
            for sid in ids:
                ep, _ = locate_scene(conn, sid)
                if ep["slug"] != slug:
                    invalid("Scene belongs to another production.")
            code = row["cells"][0]
            for ep in episodes(conn, slug):
                for shot in shots(conn, ep):
                    bound = [item for item in shot["assets"] if item != code]
                    if shot.get("sceneId") in ids:
                        bound.append(code)
                    if bound != shot["assets"]:
                        dispatch(conn, me, "PUT", f"/shots/{shot['shotId']}/assets", {"assetCodes": list(dict.fromkeys(bound))}, {}, actions)
            return {"sceneIds": ids}
        if entity == "shot" and tail == "splits" and method == "POST":
            original = row["cells"]
            first, second = original.copy(), original.copy()
            first[0], second[0] = original[0] + "A", original[0] + "B"
            for kind in ("image", "video"):
                try:
                    second[media_column(row, kind)] = ""
                except StoryError:
                    pass
            mutate_row(conn, me, slug, row["tabKey"], row["rid"], dict(enumerate(first)))
            rid = mutate_row(conn, me, slug, row["tabKey"], cells=dict(enumerate(second)), after=row["rid"])
            other = f"sh_{slug}_{rid}"
            from project_docs import story_trim
            # The new half has no take yet: neither the cut nor the adoption of the original carries over.
            store(conn, "meta_" + other, "shot_meta", {k: v for k, v in story_trim.strip(shot_meta(conn, identifier)).items() if k != "adoption"}, slug)
            from project_docs import writing_impact
            writing_impact.split_lineage(conn, slug, identifier, other)
            return {"shots": [view(), shot_view(conn, slug, find_row(conn, other, "shot")[1], takes=story_adoption.Takes(conn, slug))]}
    if parts[0] == "scenes" and len(parts) >= 2:
        ep, scene = locate_scene(conn, parts[1]); tail = "/".join(parts[2:])
        if not tail and method == "GET":
            return scene
        if not tail and method == "PATCH":
            items = scenes(conn, ep)
            items[scene["sceneIndex"] - 1].update({k: text(body, k) for k in ("title", "content") if k in body})
            write_scenes(conn, me, ep, items)
            return scenes(conn, ep)[scene["sceneIndex"] - 1]
        if tail == "shot-rebuilds" and method == "POST":
            return build_shots(conn, me, ep, scene["sceneId"], breakdown_mode=text(body, "breakdownMode") if "breakdownMode" in body else None)
        if tail == "shots" and method == "POST":
            rid = mutate_row(conn, me, ep["slug"], "cinema-studio", cells={0: text(body, "shotIndex", f"SC{scene['sceneIndex']:02d}-S{len(shots(conn, ep)) + 1:02d}"), 3: text(body, "description"), 6: "Queued"})
            identifier = f"sh_{ep['slug']}_{rid}"
            store(conn, "meta_" + identifier, "shot_meta", {"episodeId": ep["episodeId"], "sceneId": scene["sceneId"]}, ep["slug"])
            from project_docs import story_adoption
            return shot_view(conn, ep["slug"], find_row(conn, identifier, "shot")[1], takes=story_adoption.Takes(conn, ep["slug"]))
    if path in ("/shot-merges", "/scene-merges") and method == "POST":
        key = "shotIds" if path == "/shot-merges" else "sceneIds"
        ids = body.get(key, [])
        if not isinstance(ids, list) or not 2 <= len(ids) <= 200 or len(set(ids)) != len(ids):
            invalid(f"{key} requires 2–200 distinct IDs.")
        if key == "shotIds":
            found = [find_row(conn, i, "shot") for i in ids]
            if len({(s, r["tabKey"]) for s, r in found}) != 1 or len({shot_meta(conn, i).get("episodeId") for i in ids}) != 1:
                invalid("Merged shots must belong to one episode and sheet.")
            slug, row = found[0]
            column = next((i for i, h in enumerate(row["headers"]) if re.search("prompt", h, re.I)), 3)
            mutate_row(conn, me, slug, row["tabKey"], row["rid"], {column: "\n".join(r["cells"][column] for _, r in found)})
            from project_docs import writing_impact
            writing_impact.merge_lineage(conn, slug, ids)
            for lost_id, (_, other) in zip(ids[1:], found[1:]):
                for kind in ('image', 'video'):
                    try:
                        candidates = candidate_list(conn, lost_id, kind)
                    except StoryError:
                        candidates = []
                    for candidate in candidates:
                        store(conn, 'ca_merge_' + digest([ids[0], kind, candidate['url']]), 'candidate',
                              {'entityId': ids[0], 'kind': kind, 'url': candidate['url'],
                               'storyProvenance': candidate.get('storyProvenance')}, slug)
                mutate_row(conn, me, slug, row["tabKey"], other["rid"], delete=True)
            from project_docs import story_adoption
            return shot_view(conn, slug, find_row(conn, ids[0], "shot")[1], takes=story_adoption.Takes(conn, slug))
        found = [locate_scene(conn, i) for i in ids]
        if len({ep["episodeId"] for ep, _ in found}) != 1:
            invalid("Merged scenes must belong to one episode.")
        ep = found[0][0]
        first = found[0][1] | {"content": "\n".join(s["content"] for _, s in found)}
        items = [first if s["sceneId"] == ids[0] else s for s in scenes(conn, ep) if s["sceneId"] == ids[0] or s["sceneId"] not in ids]
        write_scenes(conn, me, ep, items, {sid: ids[0] for sid in ids[1:]})
        return {"items": scenes(conn, ep)}
    if parts[0] == "tasks":
        if len(parts) == 1 and method == "GET":
            return page([public_task(task_for(conn, me, t["taskId"])) for t in records(conn, "task", owner=me.actor_id)], query)
        if len(parts) >= 2:
            task = task_for(conn, me, parts[1])
            if len(parts) == 2 and method == "GET":
                return public_task(task)
            if len(parts) == 3 and method == "POST":
                if parts[2] == "cancellations":
                    if task["status"] not in ("QUEUED", "RUNNING"):
                        raise StoryError(409, "DRAMA_OPERATION_NOT_ALLOWED", "Only active tasks can be canceled.")
                    from project_assistant.execution_governance import release_unstarted
                    release_unstarted(conn, task['_slug'], task.get('_job',{}).get('_accounting_keys',{}).values())
                    task.update(status="CANCELED", finishedAt=now())
                    store(conn, task["taskId"], "task", task)
                    return public_task(task)
                if parts[2] == "retries":
                    if task["status"] not in ("FAILED", "CANCELED") or not task.get("_job"):
                        raise StoryError(409, "DRAMA_OPERATION_NOT_ALLOWED", "Only failed or canceled execution tasks can be retried.")
                    if task.get("_paid_ambiguous") and body.get("confirmPaidResubmit") is not True:
                        raise StoryError(409, "DRAMA_OPERATION_NOT_ALLOWED", "Reconcile the provider job and explicitly confirm paid resubmission.")
                    if task['_job'].get('allocation'):
                        raise StoryError(409, 'DRAMA_STAGE_PRECONDITION', 'Create a new source-bound reviewed allocation before retrying an allocation job.')
                    authorize(conn, me, task["_slug"], write=True)
                    return queue_task(conn, me, task["_slug"], task["type"], task["_job"], actions)
    if parts[0] == "task-groups" and len(parts) == 2 and method == "GET":
        group = owned(conn, me, parts[1], "taskGroup")
        tasks = [public_task(task_for(conn, me, i)) for i in group["taskIds"]]
        counts = {"total": str(len(tasks)), **{name: str(sum(t["status"] == status for t in tasks)) for name, status in
                  [("succeeded", "SUCCEEDED"), ("failed", "FAILED"), ("running", "RUNNING"), ("queued", "QUEUED"), ("canceled", "CANCELED")]}}
        return {**group, "counts": counts, "tasks": tasks}
    if path in ("/usage", "/balance", "/quota") and method == "GET":
        return {"mode": "self-hosted", "unlimited": True, "balance": "0", "taskCount": str(len(records(conn, "task", owner=me.actor_id))),
                "inputTokens": "0", "outputTokens": "0", "counts": {"total": "0"}}
    if path == "/bills" and method == "GET":
        return page([], query)
    if parts[0] == "files" and len(parts) >= 2:
        file = owned(conn, me, parts[1], "file")
        if method == "DELETE" and len(parts) == 2:
            remove(conn, parts[1]); return {"deleted": True}
        if method == "GET" and len(parts) == 2:
            return {k: v for k, v in file.items() if k not in ("raw", "content")}
        if method == "GET" and len(parts) == 3 and parts[2] == "url":
            return {"url": file["url"]}
    if path == "/webhooks":
        if method == "GET":
            return page([{**h, "secret": h["secret"][:8] + "****"} for h in records(conn, "webhook", owner=me.actor_id)], query)
        if method == "POST":
            url = text(body, "url", maximum=2048)
            webhook_address(url)
            if len(records(conn, "webhook", owner=me.actor_id)) >= 5:
                invalid("At most five webhooks may be registered.")
            identifier = "wh_" + uuid.uuid4().hex
            return store(conn, identifier, "webhook", {"webhookId": identifier, "url": url, "secret": secrets.token_urlsafe(32)}, owner=me.actor_id)
    if parts[0] == "webhooks" and len(parts) >= 2:
        hook = owned(conn, me, parts[1], "webhook")
        if len(parts) == 2 and method == "DELETE":
            remove(conn, parts[1]); return {"deleted": True}
        if len(parts) == 3 and parts[2] == "deliveries" and method == "GET":
            return page([{k: v for k, v in d.items() if not k.startswith('_')} for d in records(conn, "delivery", owner=me.actor_id) if d["webhookId"] == parts[1]], query)
        if len(parts) == 3 and parts[2] == "test-deliveries" and method == "POST":
            return schedule_delivery(conn, me, hook, {"eventId": str(uuid.uuid4()), "eventType": "webhook.test", "version": 1, "occurredAt": now(), "data": {"message": "ping"}}, actions)
    raise StoryError(404, "DRAMA_NOT_FOUND", "Story API endpoint not found.")


def upload_file(conn, me, handler, raw):
    mime = handler.headers.get("Content-Type", "")
    purpose = "SCRIPT"
    name = unquote(handler.headers.get("X-File-Name", "script.txt"))
    if mime.startswith("multipart/"):
        from email.parser import BytesParser
        from email.policy import default
        message = BytesParser(policy=default).parsebytes(b"Content-Type: " + mime.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + raw)
        files = [p for p in message.iter_parts() if p.get_param("name", header="content-disposition") == "file"]
        if len(files) != 1:
            invalid("Upload exactly one multipart file field.")
        purpose = next((p.get_payload(decode=True).decode() for p in message.iter_parts() if p.get_param("name", header="content-disposition") == "purpose"), "SCRIPT")
        part = files[0]; raw = part.get_payload(decode=True); name = part.get_filename() or name; mime = part.get_content_type()
    else:
        purpose = handler.headers.get("X-File-Purpose", "SCRIPT")
    content = ""
    if purpose == "SCRIPT":
        if Path(name).suffix.lower() not in (".txt", ".md"):
            invalid("Scripts must be .txt or .md files.")
        try:
            content = raw.decode("utf-8-sig")
        except UnicodeError:
            invalid("Script files must use UTF-8.")
        if not content.strip() or len(content) > 500000:
            raise StoryError(422, "DRAMA_SCRIPT_INVALID", "The script must contain 1–500,000 characters.")
        mime = "text/plain; charset=utf-8"
    elif purpose in ("IMAGE", "AUDIO", "VIDEO"):
        mime = media.validate(raw, mime)
        if not mime.startswith(purpose.lower() + "/"):
            invalid("File type does not match its purpose.")
    else:
        invalid("Unknown file purpose.")
    identifier = "up_" + uuid.uuid4().hex
    item = {"fileId": identifier, "name": Path(name).name, "purpose": purpose, "size": str(len(raw)),
            "contentType": mime, "content": content, "url": BASE + "/files/" + identifier + "/content"}
    store(conn, identifier, "file", item, owner=me.actor_id)
    with conn.cursor() as cur:
        cur.execute("UPDATE projectops.story_record SET blob=%s WHERE id=%s", (raw, identifier))
    return {k: v for k, v in item.items() if k not in ("raw", "content")}


def handle(handler, parsed, method):
    from project_docs import http
    from project_assistant.execution_governance import AdmissionError
    conn = None
    actions = []
    try:
        identity, problem = handler.project_docs_identity()
        me = service.identity_from(identity) if not problem else None
        if not me:
            auth = handler.headers.get("Authorization", "")
            raise StoryError(401, "DRAMA_AUTH_MISSING" if not auth else "DRAMA_AUTH_INVALID", "Sign in or supply a valid Bearer token.")
        if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            raise StoryError(400, "DRAMA_REQUEST_FAILED", "Unsupported method.")
        from project_docs import writing_http
        if writing_http.handle(handler, parsed, method, me):
            return True
        if method != "GET":
            if not me.can_write and not re.fullmatch(BASE + r"/episodes/[^/]+/(?:script-impact|storyboard-estimates)/?", parsed.path):  # read-only previews
                raise StoryError(409, "DRAMA_OPERATION_NOT_ALLOWED", "Read-only crew members cannot modify productions.")
            # Explicit bearer credentials are not ambient cookies; browser writes retain CSRF checks.
            if not handler.headers.get("Authorization", "").startswith("Bearer "):
                refused = http._write_allowed(handler)
                if refused:
                    raise StoryError(400, "DRAMA_REQUEST_FAILED", refused)
        # Bound authoring callers also use legacy tools. Check their expectation before
        # body-driven work, early responses or idempotency replay; header-less clients
        # keep the existing legacy contract. Authentication and CSRF remain independent.
        writing_http.validate_expected_actor(handler, me.actor_id)
        path = parsed.path[len(BASE):] or "/"
        body, raw = {}, b""
        is_file = path == "/files" and method == "POST"
        if method in ("POST", "PUT", "PATCH"):
            if is_file:
                raw, error = http._raw_body(handler)
            elif int(handler.headers.get("Content-Length") or "0") == 0:
                error = None
            else:
                body, error = http._json_body(handler)
            if error:
                raise StoryError(400, "DRAMA_REQUEST_FAILED", error[1]["error"])
        if any(key.startswith('_') for key in body):
            invalid('Reserved internal request fields are not accepted.')
        quote_match = re.fullmatch(r'/(?:shots|assets)/([A-Za-z0-9_-]+)/router-quotes', path)
        if quote_match and method == 'POST':
            data = router_quote(me, quote_match[1], body)
            handler.send_json(200, {'code':0,'msg':'success','errorMessages':None,'data':data})
            return True
        conn = http.open_connection()
        http._ensure_schema(conn)
        restore_cards(conn)
        key = handler.headers.get("Idempotency-Key") if method == "POST" else None
        identifier = None
        fingerprint = digest(body) if not is_file else digest([hashlib.sha256(raw).hexdigest(), handler.headers.get("Content-Type"), handler.headers.get("X-File-Purpose"), handler.headers.get("X-File-Name")])
        cached = None
        if key is not None:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM projectops.story_record WHERE kind='idempotency' AND owner_id=%s AND (data->>'expires')::double precision < %s", (me.actor_id, time.time()))
            if not 1 <= len(key) <= 128:
                invalid("Idempotency-Key must contain 1–128 characters.")
            identifier = "ik_" + digest([me.actor_id, digest(handler.headers.get("Authorization", "cookie")), path, key])
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (identifier,))
            cached = record(conn, identifier, required=False)
            if cached and cached["expires"] > time.time():
                if cached["hash"] != fingerprint:
                    raise StoryError(409, "DRAMA_IDEMPOTENCY_CONFLICT", "This Idempotency-Key was already used with a different body.")
                conn.commit(); handler.send_json(200, cached["response"]); return True
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        if path.startswith("/files/") and path.endswith("/content") and method == "GET":
            file = owned(conn, me, path.split("/")[2], "file")
            raw = file_bytes(conn, file["fileId"])
            conn.commit()
            handler.send_skillops_bytes(200, file["contentType"], raw, cache_control="private, no-store")
            return True
        data = upload_file(conn, me, handler, raw) if is_file else dispatch(conn, me, method, path, body, query, actions)
        if method == "POST" and isinstance(data, dict) and data.get("taskId") and data.get("status") in ("SUCCEEDED", "CANCELED", "FAILED"):
            actions.append(lambda: notify(me.actor_id, public_task(data)))
        payload = {"code": 0, "msg": "success", "errorMessages": None, "data": data}
        if identifier:
            store(conn, identifier, "idempotency", {"hash": fingerprint, "response": payload, "expires": time.time() + 86400}, owner=me.actor_id)
        conn.commit()
        for action in actions:
            action()
        handler.send_json(200, payload)
    except Exception as exc:
        if conn:
            conn.rollback()
        if isinstance(exc, AdmissionError):
            status, code, message = 409, "DRAMA_STAGE_PRECONDITION", str(exc)
        elif isinstance(exc, StoryError):
            status, code, message = exc.status, exc.code, str(exc)
        elif isinstance(exc, (ValueError, TypeError, KeyError, worker.WorkerError, media.MediaError, blocks.OpsError)):
            status, code, message = 422, "DRAMA_VALIDATION_FAILED", "Invalid request or incompatible production sheet."
        else:
            status, code, message = 500, "DRAMA_REQUEST_FAILED", "Story service unavailable; check server deployment."
        payload = {"code": code, "message": message, "requestId": "req_" + uuid.uuid4().hex[:16]}
        if isinstance(exc, StoryError) and exc.details is not None:
            payload['details'] = exc.details
        handler.send_json(status, payload)
    finally:
        if conn:
            conn.close()
    return True
