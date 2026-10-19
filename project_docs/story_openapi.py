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
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from project_docs import blocks, markdown_import, media, repository as repo, service
from project_docs.doc_schema import column_ids, doc_text, new_id, node_text, validate_doc
from project_assistant import limb_worker as worker
from project_assistant.table_edits import _cell, cell_value, validate_value

BASE = "/aivideo/open/v1"
STAGES = ["PROJECT", "EPISODE", "SCRIPT", "ASSETS", "SCENES", "STORYBOARD", "SHOTS", "FILM_EXPORT"]
ALIASES = {"H3_SHORT_VIDEO_V3": "h3-short-video-v3", "H3_REF2VA_PASS1": "h3-reference",
           "SEEDANCE_2_FAST_MULTIMODAL_VIDEO": "seedance-20-pro", "H3_OPTIMIZE_4K": "h3-optimize",
           "LTX25_OPENJUTSU_V2V": "ltx25-openjutsu", "LTX25_CINEMA_SHOT": "ltx25-cinema",
           "FLUX3_SOUL_CAST": "flux-soul-cast", "NANO_PRO_G2_I2I_OFFICIAL": "flux-soul-cast",
           "LOCAL_SDXL_SMOKE": "local-smoke"}
STYLES = [{"stylePresetId": str(88123 + i), "name": name} for i, name in enumerate([
    "Sci-Fi Noir Anamorphic", "Cel-Shaded Anime Drama", "Dark Fantasy Concept", "High-Contrast Neo-Noir"])]
RATIOS = ["16:9", "9:16", "1:1", "21:9"]
ASSET_RE = re.compile(r"@?\b((?:CAST|SET|LOC|PROP|STYLE)-\d+(?:[:#][a-z0-9_-]+)?)\b", re.I)
_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="story")
_PROCESS = uuid.uuid4().hex


class StoryError(ValueError):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code = status, code


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
    if not found and repo.get_tab(conn, slug, "director-brief"):
        found = [{"episodeId": f"ep_{slug}_01", "projectId": "pj_" + slug, "slug": slug,
                  "episodeIndex": 1, "title": "Episode 1", "tabKey": "director-brief", "settings": {}}]
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


def scenes(conn, ep):
    return [{**item, "sceneId": f"sc_{ep['slug']}_{ep['episodeIndex']:02d}_S{i:02d}",
             "episodeId": ep["episodeId"], "sceneIndex": i} for i, item in enumerate(scene_sections(script(conn, ep)), 1)]


def episode_view(conn, ep):
    content = script(conn, ep)
    return {**{k: v for k, v in ep.items() if k not in ("confirmedHash",)}, "scriptContent": content,
            "scriptDirty": ep.get("confirmedHash") != digest(content), "scenes": scenes(conn, ep)}


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
                      session_id="story-" + uuid.uuid4().hex, base_revision=tab["revision"], force_revision=True)
    repo.add_audit(conn, slug, action="edit", actor_id=me.actor_id, tab_key=key,
                   detail={"source": "rh_story", "changes": service.doc_changes(tab["doc"], doc)})
    service.reanchor_tab(conn, slug, key, doc, actor_id=me.actor_id)


def set_script(conn, me, ep, content):
    if not content.strip():
        raise StoryError(422, "DRAMA_SCRIPT_INVALID", "The script cannot be empty.")
    doc, _ = markdown_import.markdown_to_doc(content, tab_keys=set(), image_src=lambda _: None)
    doc, _ = validate_doc(doc, slug=ep["slug"])
    save_doc(conn, me, ep["slug"], ep["tabKey"], doc)
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


def asset_view(slug, row):
    cells = row["cells"]
    code = cells[0].lstrip("@").upper().replace("#", ":")
    return {"assetId": asset_id(slug, row), "assetCode": code, "name": cells[1], "prompt": cells[2],
            "type": "CHARACTER" if code.startswith("CAST") else "PROP" if code.startswith("PROP") else "SCENE",
            "isDefault": ":" not in code, "kind": cells[6] if ":" in code and len(cells)>6 and cells[6] in ("OUTFIT", "POSE", "LOOK") else None,
            "selectedImageUrl": media_url(cells[3]), "rowId": row["rid"], "tabKey": "soul-cast"}


def assets(conn, ep):
    return [asset_view(ep["slug"], r) for r in table_rows(conn, ep["slug"], "soul-cast")]


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


def shot_view(conn, slug, row):
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
    return {**meta, "shotId": identifier, "rowId": row["rid"], "tabKey": row["tabKey"], "shotIndex": row["cells"][0],
            "description": next((v for k, v in fields.items() if re.search("prompt", k, re.I)), ""),
            "opticalRig": next((v for k, v in fields.items() if re.search(r"optical|rig", k, re.I)), ""),
            "cameraMotion": next((v for k, v in fields.items() if re.search(r"camera.*motion", k, re.I)), ""),
            "assets": refs, "status": mapped.get(status, "PENDING"), "reviewStatus": status,
            "complexity": worker.evaluate_shot_complexity({**fields, "reviewStatus": status}),
            "selectedImageUrl": output("image"), "selectedVideoUrl": output("video")}


def shots(conn, ep):
    result = []
    for key in ("cinema-studio", "openjutsu-lab"):
        for row in table_rows(conn, ep["slug"], key):
            view = shot_view(conn, ep["slug"], row)
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
    mapping = {s['sceneId']: (f"sc_{ep['slug']}_{ep['episodeIndex']:02d}_S{i:02d}", i)
               for i, s in enumerate(items, 1) if s.get('sceneId')}
    content = []
    for i, item in enumerate(items, 1):
        title = re.sub(r"^Scene\s*\d+\s*[:：.-]?\s*", "", item['title'], flags=re.I) or "Scene"
        content.append(f"## Scene {i:02d}: {title}\n\n{item['content'].strip()}")
    result = set_script(conn, me, ep, "\n\n".join(content))
    for shot in shots(conn, ep):
        old = shot.get('sceneId')
        new = mapping.get((redirects or {}).get(old, old))
        if not new or new[0] == old:
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
    repo.get_tab_for_update(conn, ep["slug"], ep["tabKey"])
    content = script(conn, ep)
    if not content.strip():
        raise StoryError(422, "DRAMA_STAGE_INPUT_EMPTY", "Write a script before extracting assets.")
    existing = {a["assetCode"] for a in assets(conn, ep)}
    refs = list(dict.fromkeys(m[1].upper().replace("#", ":") for m in ASSET_RE.finditer(content)))
    # Offline fallback recognizes explicit asset tags and screenplay speaker cues.
    names = re.findall(r"(?m)^\s*(?:Character|角色)\s*:\s*([^\n]+)|^\s*([A-Z][A-Z ]{1,35})\s*:", content)
    for i, name in enumerate(dict.fromkeys(a or b for a, b in names), 1):
        code = f"CAST-{i:02d}"
        if code not in existing and code not in refs:
            refs.append(code)
        if code not in existing:
            mutate_row(conn, me, ep["slug"], "soul-cast", cells={0: code, 1: name.strip(), 2: name.strip(), 5: "Queued"})
            existing.add(code)
    refs += [f"SET-{i:02d}" for i, _ in enumerate(scenes(conn, ep), 1)]
    for code in dict.fromkeys(refs):
        if code not in existing:
            mutate_row(conn, me, ep["slug"], "soul-cast", cells={0: code, 1: code, 2: f"Reference for @{code}", 5: "Queued"})
            existing.add(code)
    ep["confirmedHash"] = digest(content)
    store(conn, ep["episodeId"], "episode", ep, ep["slug"])
    return completed_task(conn, me, ep["slug"], "ASSET_EXTRACT", {"assetsCount": len(existing), "scenesCount": len(scenes(conn, ep))})


def build_shots(conn, me, ep, only_scene=None):
    repo.get_tab_for_update(conn, ep["slug"], ep["tabKey"])
    if ep.get("confirmedHash") != digest(script(conn, ep)) or not scenes(conn, ep):
        raise StoryError(409, "DRAMA_STAGE_PRECONDITION", "Confirm Script & Extract Assets before building storyboards.")
    previous = shots(conn, ep)
    created = []
    for scene in scenes(conn, ep):
        if only_scene and scene["sceneId"] != only_scene:
            continue
        matches = [s for s in previous if s.get("sceneId") == scene["sceneId"]]
        prompt = scene["content"].strip() or scene["title"]
        prompt += f" @SET-{scene['sceneIndex']:02d}"
        if matches:
            if only_scene:
                for shot in matches:
                    _, row = find_row(conn, shot["shotId"], "shot")
                    column = next((i for i, h in enumerate(row["headers"]) if re.search("prompt", h, re.I)), 3)
                    mutate_row(conn, me, ep["slug"], row["tabKey"], row["rid"], {column: prompt[:10000]})
            created.extend(matches)  # Rebuilding narrative never deletes candidate media.
            continue
        rid = mutate_row(conn, me, ep["slug"], "cinema-studio", cells={0: f"SC{scene['sceneIndex']:02d}-S01",
            1: "ARRI Alexa 65 / 35mm Anamorphic f/1.4", 2: "Static Tripod", 3: prompt[:10000], 6: "Queued"})
        identifier = f"sh_{ep['slug']}_{rid}"
        store(conn, "meta_" + identifier, "shot_meta", {"episodeId": ep["episodeId"], "sceneId": scene["sceneId"]}, ep["slug"])
        created.append({"shotId": identifier})
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
    urls.extend(c["url"] for c in records(conn, "candidate", slug) if c["entityId"] == identifier and c["kind"] == kind)
    prefix, key = ("im_", "imageId") if kind == "image" else ("vd_", "videoId")
    return [{key: prefix + digest([identifier, url])[:24], "url": url, kind + "Url": url, "selected": url == current}
            for url in dict.fromkeys(urls)]


def select_candidate(conn, me, identifier, kind, body):
    key = kind + "Id"
    chosen = next((c for c in candidate_list(conn, identifier, kind) if c[key] == body.get(key)), None)
    if not chosen:
        raise StoryError(404, "DRAMA_NOT_FOUND", "Candidate does not belong to this row.")
    slug, row = find_row(conn, identifier, "shot" if identifier.startswith("sh_") else "asset")
    column = media_column(row, kind)
    mutate_row(conn, me, slug, row["tabKey"], row["rid"], {column: f"[{'Image' if kind == 'image' else 'Video'}]({chosen['url']})"})
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
    reserved = {c["card_id"] for c in builtins} | {str(c["engine_config"].get("webappId")) for c in builtins}
    if card["card_id"] in reserved or str(card["engine_config"].get("webappId")) in reserved:
        invalid("Imported cards cannot replace a built-in card or webappId.")
    card["engine_config"]["webappId"] = str(card["engine_config"].get("webappId") or card["card_id"])
    graph = worker.convert_litegraph_to_api(body["workflow"])
    store(conn, "card_" + card["card_id"], "card", {"card": card, "workflow": graph}, owner=me.actor_id)
    return {"code": 0, "msg": "success", "webappId": card["engine_config"]["webappId"], "card": card,
            "nodeInfoList": worker.build_node_info(card)}


def catalog():
    result = []
    for card in worker.openapi_list_cards():
        ec = card.get("engine_config", {})
        code = next((a for a, cid in ALIASES.items() if cid == card["card_id"]), card["card_id"])
        item = {"appCode": code, "card_id": card["card_id"], "name": card["label"], "capability": card["output_mode"].upper(),
                "webappId": str(ec.get("webappId", card["card_id"])), "skuId": str(ec.get("webappId", "0")),
                "imageMode": "T2I" if card["card_id"] == "local-smoke" else "I2I", "nodes": card["nodes"],
                "frameRule": ec.get("frame_rule", ec.get("frame_formula", "none")),
                **worker.card_execution_profile(card), "configuration": worker.provider_configuration_status(card)}
        result.append(item)
        result.extend(dict(item, appCode=alias) for alias, cid in ALIASES.items() if cid == card["card_id"] and alias != code)
    return result


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
    store(conn, identifier, "task", task, slug, me.actor_id)
    actions.append(lambda: _POOL.submit(execute_task, identifier))
    return public_task(task)


def generation(conn, me, identifier, kind, body, actions):
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
    job = {"entityId": identifier, "kind": kind, "row": row, "input": snapshot(conn, slug, row),
           "card": card, "workflow": workflow, "values": values, "column": column, "production_policy": policy}
    if body.get("_allocation"):
        job["allocation"] = copy.deepcopy(body["_allocation"])
        for step in job["allocation"]["stages"]:
            if step["kind"] == "generate":
                step["card"], step["workflow"] = (card, workflow) if step["card_id"] == card["card_id"] else worker._resolve_openapi_card_and_workflow(step["card_id"])
    return queue_task(conn, me, slug, ("SHOT_" if identifier.startswith("sh_") else "ASSET_") + kind.upper() + "_GENERATE", job, actions)


class StoryHead:
    def __init__(self, task):
        self.task = task

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
            result = providers.run_openai_compat_turn(config=providers.provider_from_env(),
                instructions="Rewrite the supplied screenplay according to the instruction. Preserve asset tags and scene headings. Return only the complete screenplay, without commentary.",
                turn_text=job["instruction"] + "\n\nSCREENPLAY:\n" + job["script"], call_tool=lambda *args: "Unavailable", timeout=180, tool_specs=[])
            if result.status != "ok" or not result.answer.strip():
                raise worker.WorkerError("Script refinement failed; verify the configured model endpoint.")
            output = {"scriptContent": result.answer}
        elif task["type"] == "FILM_EXPORT":
            output = worker.ffmpeg({"id": identifier, "input": {"rows": [{"row_id": str(i), "cells": [url]} for i, url in enumerate(job["urls"])]}},
                                   job["config"], head)
        else:
            with http.open_connection() as conn:
                authorize(conn, me, slug, write=True)
                authorize_card(conn, slug, job["card"])
            execution = {"id": identifier, "capability": job["kind"] + "_gen", "input": job["input"],
                         "workflow": job["workflow"], "production_policy": job.get("production_policy")}
            if job.get("allocation"):
                from project_docs import story_allocation
                output = story_allocation.execute_steps(execution, job["allocation"]["stages"], head, job["values"])
            else:
                output = worker.execute_story_card(execution, job["card"], job["values"], head)
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
                result = {"fileId": output["asset_id"], "videoUrl": output["asset_url"]}
                store(conn, "fl_" + identifier, "film", {**result, "episodeId": job["episodeId"], "filmId": "fl_" + identifier}, slug)
            else:
                if not output["content_type"].startswith(job["kind"] + "/"):
                    raise worker.WorkerError("The card produced the wrong media type.")
                result = {job["kind"] + "Url": output["asset_url"]}
                store(conn, "ca_" + identifier, "candidate", {"entityId": job["entityId"], "kind": job["kind"], "url": output["asset_url"]}, slug)
                repo.get_tab_for_update(conn, slug, job["row"]["tabKey"])
                _, row = find_row(conn, job["entityId"], "shot" if job["entityId"].startswith("sh_") else "asset")
                # A delayed render is kept as a candidate, not allowed to overwrite a newer selection.
                if row["cells"] == job["row"]["cells"]:
                    mutate_row(conn, me, slug, row["tabKey"], row["rid"], {job["column"]: f"[{job['kind']}]({output['asset_url']})"})
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
                message = str(exc) if isinstance(exc, (StoryError, worker.WorkerError)) else "Execution failed; check worker deployment and media inputs."
                current["_paid_ambiguous"] = bool(getattr(exc, "no_retry", False) or getattr(locals().get("head"), "paid_request_submitted", False))
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


def dispatch(conn, me, method, path, body, query, actions):
    """Return unwrapped data; callers own commit, rollback and post-commit launches."""
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
            if scope and scope not in ("CHARACTER", "SCENE_PROP", "SCENE_PROP_EDIT", "FREE_CREATION_T2I", "FREE_CREATION_I2I"):
                invalid("Unknown usageScope.")
            return page([c for c in catalog() if c["capability"] == capability], query)
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
        if not tail:
            if method == "GET":
                return episode_view(conn, ep)
            if method == "PATCH":
                ep["title"] = text(body, "title", ep["title"], 200)
                store(conn, ep["episodeId"], "episode", ep, slug)
                return episode_view(conn, ep)
        if tail == "script" and method == "PUT":
            return set_script(conn, me, ep, text(body, "scriptContent", maximum=500000))
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
            return build_shots(conn, me, ep)
        if tail == "assets":
            if method == "GET":
                return page([a for a in assets(conn, ep) if a["isDefault"]], query)
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
            return page(shots(conn, ep), query)
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
                tasks = [generation(conn, me, s["shotId"], kind, body, actions) for s in chosen]
            identifier = "tg_" + uuid.uuid4().hex
            group = {"taskGroupId": identifier, "taskIds": [t["taskId"] for t in tasks]}
            return store(conn, identifier, "taskGroup", group, slug, me.actor_id)
        if tail == "films":
            if method == "GET":
                return page([f for f in records(conn, "film", slug) if f["episodeId"] == ep["episodeId"]], query)
            if method == "POST":
                ordered = sorted(shots(conn, ep), key=lambda s: tuple((0, int(part)) if part.isdigit() else (1, part.casefold()) for part in re.split(r"(\d+)", str(s["shotIndex"]))))
                urls = [s["selectedVideoUrl"] for s in ordered if s["selectedVideoUrl"]]
                if not urls:
                    raise StoryError(409, "DRAMA_STAGE_PRECONDITION", "Select at least one shot video before exporting a film.")
                return queue_task(conn, me, slug, "FILM_EXPORT", {"episodeId": ep["episodeId"], "urls": urls, "config": {}}, actions)
    if parts[0] in ("assets", "shots") and len(parts) >= 2:
        identifier = parts[1]; entity = "asset" if parts[0] == "assets" else "shot"
        slug, row = find_row(conn, identifier, entity); tail = "/".join(parts[2:])
        authorize(conn, me, slug, write=method != "GET")
        view = lambda: asset_view(slug, find_row(conn, identifier, entity)[1]) if entity == "asset" else shot_view(conn, slug, find_row(conn, identifier, entity)[1])
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
                mutate_row(conn, me, slug, row["tabKey"], row["rid"], edits)
                return view()
            if method == "DELETE":
                mutate_row(conn, me, slug, row["tabKey"], row["rid"], delete=True)
                return {"deleted": True}
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
            store(conn, "ca_" + uuid.uuid4().hex, "candidate", {"entityId": identifier, "kind": "image", "url": url}, slug)
            return next(c for c in candidate_list(conn, identifier, "image") if c["url"] == url)
        if tail in ("selected-image", "selected-video") and method == "PUT":
            return select_candidate(conn, me, identifier, "image" if tail.endswith("image") else "video", body)
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
            store(conn, "meta_" + other, "shot_meta", shot_meta(conn, identifier), slug)
            return {"shots": [view(), shot_view(conn, slug, find_row(conn, other, "shot")[1])]}
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
            return build_shots(conn, me, ep, scene["sceneId"])
        if tail == "shots" and method == "POST":
            rid = mutate_row(conn, me, ep["slug"], "cinema-studio", cells={0: text(body, "shotIndex", f"SC{scene['sceneIndex']:02d}-S{len(shots(conn, ep)) + 1:02d}"), 3: text(body, "description"), 6: "Queued"})
            identifier = f"sh_{ep['slug']}_{rid}"
            store(conn, "meta_" + identifier, "shot_meta", {"episodeId": ep["episodeId"], "sceneId": scene["sceneId"]}, ep["slug"])
            return shot_view(conn, ep["slug"], find_row(conn, identifier, "shot")[1])
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
            for lost_id, (_, other) in zip(ids[1:], found[1:]):
                for kind in ('image', 'video'):
                    try:
                        candidates = candidate_list(conn, lost_id, kind)
                    except StoryError:
                        candidates = []
                    for candidate in candidates:
                        store(conn, 'ca_merge_' + digest([ids[0], kind, candidate['url']]), 'candidate',
                              {'entityId': ids[0], 'kind': kind, 'url': candidate['url']}, slug)
                mutate_row(conn, me, slug, row["tabKey"], other["rid"], delete=True)
            return shot_view(conn, slug, find_row(conn, ids[0], "shot")[1])
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
                    task.update(status="CANCELED", finishedAt=now())
                    store(conn, task["taskId"], "task", task)
                    return public_task(task)
                if parts[2] == "retries":
                    if task["status"] not in ("FAILED", "CANCELED") or not task.get("_job"):
                        raise StoryError(409, "DRAMA_OPERATION_NOT_ALLOWED", "Only failed or canceled execution tasks can be retried.")
                    if task.get("_paid_ambiguous") and body.get("confirmPaidResubmit") is not True:
                        raise StoryError(409, "DRAMA_OPERATION_NOT_ALLOWED", "Reconcile the provider job and explicitly confirm paid resubmission.")
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
        if method != "GET":
            if not me.can_write:
                raise StoryError(409, "DRAMA_OPERATION_NOT_ALLOWED", "Read-only crew members cannot modify productions.")
            # Explicit bearer credentials are not ambient cookies; browser writes retain CSRF checks.
            if not handler.headers.get("Authorization", "").startswith("Bearer "):
                refused = http._write_allowed(handler)
                if refused:
                    raise StoryError(400, "DRAMA_REQUEST_FAILED", refused)
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
        if isinstance(exc, StoryError):
            status, code, message = exc.status, exc.code, str(exc)
        elif isinstance(exc, (ValueError, TypeError, KeyError, worker.WorkerError, media.MediaError, blocks.OpsError)):
            status, code, message = 422, "DRAMA_VALIDATION_FAILED", "Invalid request or incompatible production sheet."
        else:
            status, code, message = 500, "DRAMA_REQUEST_FAILED", "Story service unavailable; check server deployment."
        handler.send_json(status, {"code": code, "message": message, "requestId": "req_" + uuid.uuid4().hex[:16]})
    finally:
        if conn:
            conn.close()
    return True
