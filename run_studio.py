"""Start ZeroField with the Updraft showcase production and local/Comfy SDK workers."""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import threading
import uuid

from openbench_data import resource_path
from project_assistant import flow_runner, limb_worker, limbs, local_workers, worker as assistant_worker
from project_docs import auth, doc_schema, http, repository as repo, service, templates
import server

SHOWCASE_SLUG = "zerofield-showcase"
# The Layout Key edit: previs frame 0 becomes a photographic still with the row's cast (image 2) and set (image 3).
# Composition comes first: with a photographic portrait as the cast reference, "same face" alone made Klein copy the
# portrait's close-up instead of the blockout's small figure.
LAYOUT_KEY_PROMPT = ("Repaint the first image, a grey 3D blockout, as a photographic live-action film still. The first image fixes "
                     "the composition: keep its exact camera angle, framing, horizon and set layout, and the figure's exact position, "
                     "size, pose and facing; do not move the camera or enlarge the figure. Paint the figure as the person of the "
                     "second image (face, hair, wardrobe) at the figure's size. Paint the set with the materials, colours and light "
                     "of the third image. Only one person. No text.")


def _text(node, values=None):
    if node.get("type") == "text":
        return node.get("text", "")
    if node.get("type") == "status":
        attrs = node.get("attrs", {})
        saved = (values or {}).get(attrs.get("fid"), {})
        return saved.get("value", attrs.get("label", ""))
    return "".join(_text(child, values) for child in node.get("content", []))


def _set_text(cell, value):
    cell["content"] = [{"type": "paragraph", "content": [{"type": "text", "text": value}]}]


UPDRAFT_DIR = ("samples", "updraft")
MEDIA_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
              ".mp4": "video/mp4", ".webm": "video/webm"}
SEED_RECORD = "updraft_seed_"  # + slug: which manifest items were already applied, so a cell the user cleared stays empty


def seed_updraft_meta(conn, slug, *, owner=None):
    """Write the asset_meta records and the episode look of the Updraft production; an existing record or look is kept. Caller owns the transaction."""
    from project_docs import story_assets, story_look, story_openapi as story
    production = templates.load_updraft()
    assets = {a["code"].upper(): a for a in production["assets"]}
    written = 0
    for row in story.table_rows(conn, slug, "soul-cast"):
        asset = assets.get(row["cells"][0].lstrip("@").upper())
        if not asset or story.record(conn, "am_" + row["rid"], required=False):
            continue
        data = story_assets.blank(row)
        locks = {**(asset.get("meta") or {}), **({"change": asset["change"]} if asset.get("change") else {})}
        data.update({key: str(locks.get(key, ""))[:story_assets.TEXT_LIMIT] for key in story_assets.TEXT_FIELDS})
        story_assets.save(conn, slug, row, data)
        written += 1
    look = False
    episode = next((e for e in story.episodes(conn, slug) if e["episodeId"] == f"ep_{slug}_01"), None)
    if episode and not (episode.get("settings") or {}).get("look"):
        style = next((s["stylePresetId"] for s in story.STYLES if s["name"] == production.get("style")), None)
        episode["settings"] = {**(episode.get("settings") or {}), "look": story_look.validate_episode_look(production["look"]),
                               **({"stylePresetId": style} if style and "stylePresetId" not in (episode.get("settings") or {}) else {})}
        story.store(conn, episode["episodeId"], "episode", episode, slug)
        look = True
    return {"meta": written, "look": look}


def _manifest(root):
    path = root / "manifest.json"
    if not path.is_file():
        return []
    items = json.loads(path.read_text(encoding="utf-8")).get("items")
    return items if isinstance(items, list) else []


def seed_updraft_media(conn, slug, root, actor_id):
    """Fill empty cells (and asset_meta panels) from samples/updraft/manifest.json. An item is applied once: a cell the user
    edited or cleared later is never touched again. Returns the tabs that changed and the items that were applied."""
    from project_docs import story_openapi as story
    items = _manifest(root)
    if not items:
        return {"tabs": [], "applied": []}
    stored = story.record(conn, SEED_RECORD + slug, required=False) or {"applied": []}
    done = set(stored["applied"])
    todo = [i for i in items if isinstance(i, dict) and f"{i.get('tab')}/{i.get('code')}/{i.get('column')}/{i.get('panel')}" not in done]
    values = repo.field_values(conn, slug)
    urls, applied, changed, missing, rids, adoptions = {}, [], [], [], {}, []
    for key in sorted({i.get("tab") for i in todo}):
        tab = repo.get_tab_for_update(conn, slug, key)
        if not tab:
            continue
        doc = copy.deepcopy(tab["doc"])
        dirty = False
        for table in doc.get("content", []):
            if table.get("type") != "table" or not table.get("content"):
                continue
            headers = [_text(c) for c in table["content"][0]["content"]]
            for item in (i for i in todo if i.get("tab") == key):
                file = root / str(item.get("file", ""))
                if not file.is_file() or file.suffix.lower() not in MEDIA_MIME:
                    missing.append(str(item.get("file")))
                    continue
                column = headers.index(item["column"]) if item.get("column") in headers else None
                row = next((r for r in table["content"][1:] if _text(r["content"][0]) == item.get("code")), None)
                # A panel picture (face, front, ...) or an earlier candidate needs no cell of its own.
                if row is None or (column is None and not (item.get("panel") or item.get("candidate"))):
                    continue
                if file.name not in urls:
                    identifier = repo.put_asset(conn, slug, data=file.read_bytes(), content_type=MEDIA_MIME[file.suffix.lower()], actor_id=actor_id)
                    urls[file.name] = f"/projects/api/{slug}/assets/{identifier}"
                rids[id(item)] = row.get("attrs", {}).get("bid")
                cells = row["content"]
                if column is not None and not item.get("candidate") and not _text(cells[column], values.get(key)):
                    _set_text(cells[column], urls[file.name])
                    dirty = True
                    status_col = 5 if key == "soul-cast" else 6
                    status = next((n for p in cells[status_col].get("content", []) for n in p.get("content", []) if n["type"] == "status"), None)
                    # The production adopted these takes (SPEC_19: adoption is Approved); anything else waits for a person's choice.
                    adopted = key == "cinema-studio" and item.get("column") == "Cinema Shot"
                    label = "Approved" if adopted else "Pending Review"
                    if status and _text(status, values.get(key)) in (("Queued", "Pending Review") if adopted else ("Queued",)):
                        status["attrs"]["label"] = label
                        repo.set_field_value(conn, slug, key, status["attrs"]["fid"], kind="status", value=label, actor_id=actor_id)
                    if adopted:
                        adoptions.append((f"sh_{slug}_{rids[id(item)]}", urls[file.name]))
                applied.append(item)
        if dirty:
            clean, _ = doc_schema.validate_doc(doc, slug=slug)
            repo.save_tab_doc(conn, slug, key, doc=clean, title=tab["title"], actor_id=actor_id,
                              session_id="studio-showcase-seed", base_revision=tab["revision"], force_revision=True)
            changed.append(key)
    # The film window counts adopted shots, so a seeded take is adopted the way POST /shots/{id}/adoptions records it.
    from project_docs import story_adoption
    for shot_id, url in adoptions:
        story_adoption._record(conn, service.Identity(actor_id, "Updraft seed", "admin"), slug, shot_id, url)
    # Panels: a face or plate picture is also the asset's own panel (an empty panel only).
    from project_docs import story_assets
    rows = {r["cells"][0]: r for r in story.table_rows(conn, slug, "soul-cast")}
    for item in applied:
        # The takes and pictures the production chose between stay listed beside the chosen one.
        if item.get("candidate") and rids.get(id(item)):
            entity = ("as_" if item["tab"] == "soul-cast" else "sh_") + f"{slug}_{rids[id(item)]}"
            kind = "video" if Path(item["file"]).suffix.lower() in (".mp4", ".webm") else "image"
            story.store(conn, "ca_" + uuid.uuid4().hex, "candidate", {"entityId": entity, "kind": kind, "url": urls[Path(item["file"]).name],
                        "panel": item.get("panel"), "createdAt": story.now()}, slug)
        row = rows.get(item.get("code")) if item.get("panel") and item.get("tab") == "soul-cast" and not item.get("candidate") else None
        if row and story.record(conn, "am_" + row["rid"], required=False) is not None:
            meta = story_assets.meta_of(conn, row)
            if item["panel"] in meta["panels"] and not meta["panels"][item["panel"]]:
                meta["panels"][item["panel"]] = {"url": urls[Path(item["file"]).name], "imageId": None}
                story_assets.save(conn, slug, row, meta)
    if applied:
        keys = [f"{i['tab']}/{i['code']}/{i['column']}/{i.get('panel')}" for i in applied]
        story.store(conn, SEED_RECORD + slug, "showcase_seed", {"applied": sorted(done | set(keys))}, slug)
    return {"tabs": changed, "applied": applied, "missing": missing}


def seed_showcase_media(conn, slug=SHOWCASE_SLUG, *, samples_dir=None, actor_id=None):
    """Seed the Updraft showcase: asset_meta records and the episode look once, then media from samples/updraft/manifest.json
    wherever a cell is empty. Never rewrites an existing take or user prompt. Caller owns the transaction."""
    actor_id = actor_id or server.DEMO_MEMBERS[0]["actor_id"]
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("zerofield-showcase-seed:" + slug,))
        cur.execute("SELECT 1 FROM projectops.audit_log WHERE project_slug=%s AND action='studio_showcase_seed'", (slug,))
        first = cur.fetchone() is None
    if not repo.get_project(conn, slug):
        return {"seeded": False, "reason": "project_missing"}
    root = Path(samples_dir) if samples_dir else resource_path(*UPDRAFT_DIR)
    meta = seed_updraft_meta(conn, slug)
    media = seed_updraft_media(conn, slug, root, actor_id)
    if first:
        repo.add_audit(conn, slug, action="studio_showcase_seed", actor_id=actor_id,
                       detail={"production": "Updraft", "provenance": "CC0 content; media, when present, generated with open-weights models (see samples/updraft/manifest.json)"})
    if media["applied"]:
        repo.add_audit(conn, slug, action="studio_updraft_media_seed", actor_id=actor_id,
                       detail={"items": [{k: i.get(k) for k in ("tab", "code", "column", "panel", "file", "card", "seed", "prompt")} for i in media["applied"]]})
    seed_showcase_reference_pack(conn, slug, actor_id=actor_id)
    return {"seeded": first or bool(media["applied"]) or bool(meta["meta"] or meta["look"]), "tabs": media["tabs"], "meta": meta["meta"], "look": meta["look"]}


def _append_columns(table, specs):
    """Append missing (name, kind) columns, keeping existing column IDs. Returns (headers, changed)."""
    rows = table.get("content", [])
    headers = [_text(cell) for cell in rows[0].get("content", [])]
    attrs = table.setdefault("attrs", {})
    attrs["column_ids"] = doc_schema.column_ids(table)
    types = attrs.setdefault("column_types", ["text"] * len(headers))
    while len(types) < len(headers):
        types.append("text")
    changed = False
    for name, kind in specs:
        if name in headers:
            continue
        headers.append(name)
        types.append(kind)
        attrs["column_ids"].append(doc_schema.new_id("c"))
        for index, row in enumerate(rows):
            cell = {"type": "tableHeader" if index == 0 else "tableCell", "content": [{"type": "paragraph"}]}
            if index == 0:
                _set_text(cell, name)
            row.setdefault("content", []).append(cell)
        changed = True
    return headers, changed


def seed_showcase_reference_pack(conn, slug=SHOWCASE_SLUG, *, samples_dir=None, actor_id=None):
    """Append the prepared-reference columns (First Frame, Motion Structure, Anchor Keyframe) to the OpenJutsu Lab once,
    retaining existing column IDs and media. The pipeline seed binds its extract and structure stages to them."""
    actor_id = actor_id or server.DEMO_MEMBERS[0]["actor_id"]
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM projectops.audit_log WHERE project_slug=%s AND action='studio_reference_pack_seed'", (slug,))
        if cur.fetchone():
            return {"seeded": False, "reason": "already_seeded"}
    tab = repo.get_tab_for_update(conn, slug, "openjutsu-lab")
    if not tab:
        return {"seeded": False, "reason": "page_missing"}
    stages = [("First Frame", "image"), ("Motion Structure", "video"), ("Anchor Keyframe", "image")]
    doc = copy.deepcopy(tab["doc"])
    dirty = False
    for table in doc.get("content", []):
        rows = table.get("content", []) if table["type"] == "table" else []
        if rows and any(_text(row.get("content", [{}])[0]) == "VFX-01" for row in rows[1:]):
            dirty = _append_columns(table, stages)[1] or dirty
    if dirty:
        clean, _ = doc_schema.validate_doc(doc, slug=slug)
        repo.save_tab_doc(conn, slug, "openjutsu-lab", doc=clean, title=tab["title"], actor_id=actor_id,
                         session_id="studio-reference-pack-seed", base_revision=tab["revision"], force_revision=True)
    repo.add_audit(conn, slug, action="studio_reference_pack_seed", actor_id=actor_id, detail={"columns": [name for name, _ in stages]})
    return {"seeded": dirty, "tabs": ["openjutsu-lab"] if dirty else []}


def seed_showcase_previs(conn, slug=SHOWCASE_SLUG, *, samples_dir=None, actor_id=None):
    """Add the Previs, Actor Matte and Pose Skeleton columns to the cinema slate once, keeping user media.

    The 3D Stage writes all three on Render previs; the matte frees the actor in the Layout Render and the skeleton
    carries the acting (SPEC_10 §7.7)."""
    actor_id = actor_id or server.DEMO_MEMBERS[0]["actor_id"]
    tab = repo.get_tab_for_update(conn, slug, "cinema-studio")
    if not tab:
        return {"seeded": False, "reason": "page_missing"}
    doc = copy.deepcopy(tab["doc"])
    dirty = False
    for table in doc.get("content", []):
        if table["type"] != "table" or not table.get("content"):
            continue
        dirty = _append_columns(table, [("Previs", "video"), ("Actor Matte", "video"), ("Pose Skeleton", "video")])[1]
        break
    if dirty:
        clean, _ = doc_schema.validate_doc(doc, slug=slug)
        repo.save_tab_doc(conn, slug, "cinema-studio", doc=clean, title=tab["title"], actor_id=actor_id,
                          session_id="studio-previs-seed", base_revision=tab["revision"], force_revision=True)
    return {"seeded": dirty}


def load_worker_configs(path, defaults):
    if not path:
        return defaults
    config_path = Path(path).resolve()
    overrides = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(overrides, dict) or set(overrides) - set(defaults) - {"anchor"}:
        raise ValueError("Worker overrides must map built-in stage names (or anchor) to capability configs")
    result = copy.deepcopy(defaults)
    for key, capabilities in overrides.items():
        if not isinstance(capabilities, dict) or not capabilities or set(capabilities) - set(limbs.CAPABILITIES):
            raise ValueError("Each stage requires a capability-to-adapter mapping")
        for config in capabilities.values():
            if not isinstance(config, dict) or config.get("adapter") not in limb_worker.ADAPTERS:
                raise ValueError("Each capability requires a supported adapter")
            if config.get("workflow"):
                config["workflow"] = str((config_path.parent / config["workflow"]).resolve())
            if key == "anchor":
                config.setdefault("reference_role", "anchor_keyframe")
        result[key] = capabilities
    return result


def worker_configs(comfy_url, *, platform="local", api_key_env=None):
    common = {"adapter": "comfyui", "platform": platform, "base_url": comfy_url,
              "prompt_node": "6", "seed_node": "3"}
    if api_key_env:
        common["api_key_env"] = api_key_env
    def comfy(name, **extra):
        return dict(common, workflow=str(resource_path("workflows", name)), **extra)
    return {
        "image": {"image_gen": comfy("flux3_klein_soul_cast.json", output_node="9")},
        "cinema": {"video_gen": comfy("ltx25_cinema_shot.json", image_node="2", output_node="12")},
        "v2v": {"video_gen": comfy("ltx25_openjutsu_v2v.json", video_node="1", image_node="2", structure_video_node="4", output_node="12")},
        # Previs-driven shot: the grey blockout drives motion, Klein restores identity, a look pass re-renders the approved motion.
        "motion": {"video_gen": comfy("ltx25_previs_motion.json", output_node="12", prompt_node="30", prompt_input="string_a",
                                      input_bindings={"20.video": {"source": "previs_video", "upload": "video"}})},
        "lookkey": {"image_gen": comfy("flux3_klein_look_key.json", prompt_node=None, output_node="9",
                                       input_bindings={"20.video": {"source": "output_video", "upload": "video"},
                                                       "21.image": {"source": "asset_images.0", "upload": "image"},
                                                       "22.image": {"source": "asset_images.1", "upload": "image", "optional": True}})},
        "look": {"video_gen": comfy("ltx25_previs_look.json", output_node="12",
                                    input_bindings={"20.video": {"source": "output_video", "upload": "video"},
                                                    "2.image": {"source": "anchor_keyframe", "upload": "image"}})},
        # OpenJutsu swap: Klein replaces the subject on the source's first frame; one LTX graph then mattes the subject
        # (Alpha-Gen IC-LoRA), regenerates it from that frame and composites it over the untouched source pixels.
        "swapkey": {"image_gen": comfy("flux3_klein_look_key.json", prompt_node=None, output_node="9", reference_role="anchor_keyframe",
                                       input_bindings={"20.video": {"source": "source_video", "upload": "video"},
                                                       "23.batch_index": {"literal": 0},
                                                       "21.image": {"source": "asset_images.0", "upload": "image"},
                                                       "22.image": {"source": "asset_images.1", "upload": "image", "optional": True}})},
        "swap": {"video_gen": comfy("ltx25_openjutsu_swap.json", output_node="12",
                                    input_bindings={"20.video": {"source": "source_video", "upload": "video"},
                                                    "25.video": {"source": "source_video", "upload": "video"},
                                                    "2.image": {"source": "anchor_keyframe", "upload": "image"}})},
        # Layout Render: Klein turns previs frame 0 into a photographic key; the Layout-To-Render IC-LoRA then keeps the
        # previs set and camera and takes the look from that key. The stage's actor matte frees the actor, which the
        # LoRA would otherwise render as the mannequin (docs/research/2026-10-20-motion-control-lab.md), and the
        # Union-Control IC-LoRA takes his acting from the stage's pose skeleton (SPEC_10 §7.7). A row with Chain In Frame /
        # Mid Key / End Key images renders a chained slice of a long take (project_assistant/studio/layout_guides.py).
        "layoutkey": {"image_gen": comfy("flux3_klein_look_key.json", prompt_node=None, output_node="9", reference_role="anchor_keyframe",
                                         input_bindings={"20.video": {"source": "previs_video", "upload": "video"},
                                                         "20.frame_load_cap": {"literal": 1},
                                                         "23.batch_index": {"literal": 0},
                                                         "6.text": {"literal": LAYOUT_KEY_PROMPT},
                                                         "21.image": {"source": "asset_images.0", "upload": "image"},
                                                         "22.image": {"source": "asset_images.1", "upload": "image", "optional": True}})},
        "layout": {"video_gen": comfy("ltx25_layout_render.json", output_node="12", prompt_node="30", prompt_input="string_a",
                                      seed_node="50", seed_input="noise_seed", chain_guides=True,
                                      input_bindings={"20.video": {"source": "previs_video", "upload": "video"},
                                                      "24.video": {"source": "actor_matte", "upload": "video"},
                                                      "44.video": {"source": "pose_skeleton", "upload": "video"},
                                                      "2.image": {"source": "anchor_keyframe", "upload": "image"}})},
        "extract": {"media_assemble": {"adapter": "ffmpeg", "mode": "extract_frame"}},
        "structure": {"media_assemble": {"adapter": "ffmpeg", "mode": "motion_structure", "structure_type": "edge_lineart"}},
        "assemble": {"media_assemble": {"adapter": "ffmpeg"}},
        "split": {"media_assemble": {"adapter": "ffmpeg", "layout": "side_by_side"}},
    }


SHOWCASE_STAGES = {"image", "cinema", "v2v", "split", "assemble", "extract", "structure"}  # seed_showcase_pipeline's base


def register_workers(conn, configs, actor_id):
    """Stable built-in worker identities serving every production on this server, with fresh in-memory credentials
    each launch (SPEC_20 R14)."""
    return local_workers.register(conn, configs, actor_id)


def _launch_actor(conn):
    """Outside development mode the earliest active showrunner (else any active member) owns the worker rows."""
    with conn.cursor() as cur:
        cur.execute("""SELECT actor_id::text FROM projectops.member WHERE status='active'
                       ORDER BY role<>'admin',created_at,actor_id LIMIT 1""")
        row = cur.fetchone()
    return row[0] if row else None


def seed_showcase_pipeline(conn, slug, registered, actor_id):
    current = flow_runner.definition(conn, slug, "comfy-pipeline")
    original = flow_runner.validate_definition(templates.flow_specs("zerofield_studio")["comfy-pipeline"])
    def node(key, title, cap, tab, col=None, *, worker=None, scope="rows"):
        target = {"tab_key": tab, "col_index": col} if col is not None else {"tab_key": "director-brief", "kind": "doc", "mode": "append"}
        return {"id": key, "title": title, "capability": cap, "scope": scope,
            "prompt": "Use the approved row context and references. Return asset_url for director review.",
            "input_tabs": [tab, "soul-cast"] if tab != "soul-cast" else [tab],
            "row_source": {"tab_key": tab}, "target": target, "write_mode": "proposal",
            "limb_id": registered[worker or key]["id"], "x": 80, "y": 80}
    nodes = [node("image", "Soul Cast References", "image_gen", "soul-cast", 3),
        node("keyframe", "Shot Keyframe", "image_gen", "cinema-studio", 4, worker="image"),
        node("cinema", "Cinema Shot", "video_gen", "cinema-studio", 5),
        node("v2v", "OpenJutsu Remaster", "video_gen", "openjutsu-lab", 4),
        node("split", "Source / Remaster Comparison", "media_assemble", "openjutsu-lab", 5),
        node("assemble", "Director Cut", "media_assemble", "cinema-studio", scope="aggregate")]
    legacy_nodes = copy.deepcopy(nodes)
    lab = repo.get_tab(conn, slug, "openjutsu-lab")
    reference_table = next((table for table in lab["doc"].get("content", []) if table["type"] == "table"
        and any(_text(row.get("content", [{}])[0]) == "VFX-01" for row in table.get("content", [])[1:])), None)
    if not reference_table:
        return False
    headers = [_text(cell) for cell in reference_table["content"][0]["content"]]
    if any(name not in headers for name in ("First Frame", "Motion Structure", "Anchor Keyframe")):
        return False
    nodes += [node("extract", "Extract First Frame", "media_assemble", "openjutsu-lab", headers.index("First Frame")),
              node("structure", "Prepare Motion Structure", "media_assemble", "openjutsu-lab", headers.index("Motion Structure"))]
    if "anchor" in registered:
        nodes.append(node("anchor", "Anchor Keyframe", "image_gen", "openjutsu-lab", headers.index("Anchor Keyframe")))
    legacy_edges = [{"source": "keyframe", "target": "cinema"}, {"source": "cinema", "target": "assemble"}, {"source": "v2v", "target": "split"}]
    for i, n in enumerate(legacy_nodes):
        n.update(x=60 + (i % 3) * 380, y=80 + (i // 3) * 250)
    legacy = flow_runner.validate_definition({"nodes": legacy_nodes, "edges": legacy_edges})
    prep_chain = ["extract"] + (["anchor"] if "anchor" in registered else []) + ["structure", "v2v", "split"]
    # Production lines read left to right (Start sits to their left in the editor): one lane per chain.
    by_id = {n["id"]: n for n in nodes}
    for top, lane in zip((60, 320, 580), (["image"], ["keyframe", "cinema", "assemble"], prep_chain)):
        for depth, key in enumerate(lane):
            by_id[key].update(x=300 + depth * 340, y=top)
    edges = [edge for edge in legacy_edges if edge["source"] != "v2v"] + [
        {"source": left, "target": right} for left, right in zip(prep_chain, prep_chain[1:])]
    graph = {"nodes": nodes, "edges": edges}
    for item in nodes:
        if item["id"] in ("extract", "structure", "anchor"):
            item["target"]["table_id"] = reference_table["attrs"]["bid"]
            item["row_source"]["table_id"] = reference_table["attrs"]["bid"]
    normalized = flow_runner.validate_definition(graph)
    # The earlier three-column seed is still an untouched showcase definition, so it upgrades too.
    snake = copy.deepcopy(nodes)
    for i, n in enumerate(snake):
        n.update(x=60 + (i % 3) * 380, y=80 + (i // 3) * 250)
    previous = flow_runner.validate_definition({"nodes": snake, "edges": edges})
    without_anchor = flow_runner.validate_definition({"nodes": [n for n in nodes if n["id"] != "anchor"],
        "edges": [edge for edge in legacy_edges if edge["source"] != "v2v"] + [
            {"source": a, "target": b} for a, b in zip(["extract", "structure", "v2v"], ["structure", "v2v", "split"])]})
    without_anchor_previous = flow_runner.validate_definition({"nodes": [n for n in snake if n["id"] != "anchor"],
        "edges": [edge for edge in legacy_edges if edge["source"] != "v2v"] + [
            {"source": a, "target": b} for a, b in zip(["extract", "structure", "v2v"], ["structure", "v2v", "split"])]})
    known = [original, legacy, without_anchor, previous, without_anchor_previous]
    default = local_workers.studio_pipeline(conn, slug, registered)  # a showcase created while local workers existed
    if default:
        known += [default, local_workers.without_primary(default)]
    lanes = []  # (audit action, chain) appended once to a pipeline the user has rearranged
    if "motion" in registered:
        # Fourth lane: previs-driven shots (grey blockout -> motion pass -> look key -> look pass).
        known += [normalized, local_workers.mark_primary(normalized)]
        previs_chain = [node("motion", "Previs Motion Pass", "video_gen", "cinema-studio", 5),
                        node("lookkey", "Look Key", "image_gen", "cinema-studio", 4),
                        node("look", "Look Pass", "video_gen", "cinema-studio", 5)]
        for depth, item in enumerate(previs_chain):
            item.update(x=300 + depth * 340, y=840)
        nodes = nodes + previs_chain
        edges = edges + [{"source": a["id"], "target": b["id"]} for a, b in zip(previs_chain, previs_chain[1:])]
        graph = {"nodes": nodes, "edges": edges}
        normalized = flow_runner.validate_definition(graph)
        lanes.append(("studio_previs_lane_seed", previs_chain))
    if "swap" in registered and {"Jutsu Mode", "Remastered Video"} <= set(headers):
        # Fifth lane, Object Swap rows only: Klein swap key -> LTX matte, regenerate and composite over the source.
        known += [normalized, local_workers.mark_primary(normalized)]
        table_id = reference_table["attrs"]["bid"]
        swap_chain = [node("swapkey", "Swap Key", "image_gen", "openjutsu-lab", headers.index("Anchor Keyframe")),
                      node("swap", "OpenJutsu Swap", "video_gen", "openjutsu-lab", headers.index("Remastered Video"))]
        for depth, item in enumerate(swap_chain):
            item.update(x=300 + depth * 340, y=1100)
            item["target"]["table_id"] = table_id
            item["row_source"] = {"tab_key": "openjutsu-lab", "table_id": table_id,
                                  "status_col": headers.index("Jutsu Mode"), "status": ["Object Swap"]}
        nodes = nodes + swap_chain
        edges = edges + [{"source": "swapkey", "target": "swap"}]
        graph = {"nodes": nodes, "edges": edges}
        normalized = flow_runner.validate_definition(graph)
        lanes.append(("studio_swap_lane_seed", swap_chain))
    if "layout" in registered:
        # Sixth lane, from the 3D Stage like the fourth: Layout Key (Klein on previs frame 0, reviewed) -> Layout Render.
        known += [normalized, local_workers.mark_primary(normalized)]
        layout_chain = [node("layoutkey", "Layout Key", "image_gen", "cinema-studio", 4),
                        node("layout", "Layout Render", "video_gen", "cinema-studio", 5)]
        for depth, item in enumerate(layout_chain):
            item.update(x=300 + depth * 340, y=1360)
        nodes = nodes + layout_chain
        edges = edges + [{"source": "layoutkey", "target": "layout"}]
        graph = {"nodes": nodes, "edges": edges}
        normalized = flow_runner.validate_definition(graph)
        lanes.append(("studio_layout_lane_seed", layout_chain))
    # SPEC_20 R44-7: the main lane is the default step of the Keyframe and Cinema Shot columns the previs and layout lanes also
    # write, so a shot's Run buttons and Run Pipeline find one step. The same graph unmarked is the seed before the marker.
    known.append(normalized)
    graph = local_workers.mark_primary(graph)
    normalized = flow_runner.validate_definition(graph)
    if current["definition"] != normalized and current["definition"] not in known and lanes:
        appended = [_append_lane(conn, slug, chain, actor_id, action) for action, chain in lanes]
        return any(appended)
    if current["definition"] == normalized or current["definition"] not in known:
        return False
    flow_runner.save_definition(conn, service.Identity(actor_id, "Alex Rivera", "admin"), slug, "comfy-pipeline",
                                {"revision": current["revision"], "definition": graph})
    return True


def _append_lane(conn, slug, chain, actor_id, action):
    """A pipeline the user has rearranged keeps every node; a new lane is added below it, once (audited as action)."""
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM projectops.audit_log WHERE project_slug=%s AND action=%s", (slug, action))
        if cur.fetchone():
            return False
    current = flow_runner.definition(conn, slug, "comfy-pipeline")
    definition = copy.deepcopy(current["definition"])
    if {n["id"] for n in definition["nodes"]} & {n["id"] for n in chain}:
        return False
    bottom = max((n.get("y", 0) for n in definition["nodes"]), default=0) + 260
    for item in chain:
        item["y"] = bottom
    definition["nodes"] += chain
    definition["edges"] += [{"source": a["id"], "target": b["id"]} for a, b in zip(chain, chain[1:])]
    flow_runner.save_definition(conn, service.Identity(actor_id, "Alex Rivera", "admin"), slug, "comfy-pipeline",
                                {"revision": current["revision"], "definition": definition})
    repo.add_audit(conn, slug, action=action, actor_id=actor_id, detail={"nodes": [n["id"] for n in chain]})
    return True


def start_media_workers(base_url, registered, shutdown):
    threads = []
    for key, config in registered.items():
        def poll(config=config):
            head = limb_worker.Head(base_url, config["token"])
            while not shutdown.is_set():
                try:
                    busy = limb_worker.process_one(head, config)
                except (limb_worker.WorkerError, OSError):
                    busy = False
                if not busy:
                    shutdown.wait(3)
        thread = threading.Thread(target=poll, name="studio-" + key, daemon=True)
        thread.start()
        threads.append(thread)
    return threads


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3020)
    parser.add_argument("--comfy-url", help="ComfyUI or SDK workflow endpoint; defaults to COMFY_BASE_URL or the selected platform")
    parser.add_argument("--router-url", help="Comfy workflow deployment/proxy URL (requires --platform comfy_sdk)")
    parser.add_argument("--platform", choices=("local", "comfy_sdk", "comfy_router"), default=os.environ.get("COMFY_PLATFORM", "local"))
    parser.add_argument("--worker-config", help="Trusted JSON stage adapter overrides; external workflows and input_bindings")
    parser.add_argument("--api-key", help="Comfy API key; COMFY_API_KEY is preferred to avoid shell history")
    parser.add_argument("--embedded-db", action="store_true", help="Use local PostgreSQL when no database URI is set (automatic)")
    parser.add_argument("--no-worker", action="store_true", help="Browse the seeded studio without agent/media workers")
    args = parser.parse_args(argv)
    cfg = auth.config()
    if cfg["mode"] == "dev" and args.host not in ("127.0.0.1", "localhost", "::1"):
        parser.error("Development authentication binds to loopback only.")
    if args.platform == "comfy_router":
        parser.error("Comfy Router serves model calls, not workflow graphs. Use --platform comfy_sdk for Comfy Developer Platform workflows.")
    if args.router_url and args.platform != "comfy_sdk":
        parser.error("--router-url requires --platform comfy_sdk and a workflow-capable deployment/proxy.")
    if args.api_key:
        os.environ["COMFY_API_KEY"] = args.api_key
    cleanup_pg = None
    shutdown = threading.Event()
    http_server = None
    registered, threads = {}, []
    from project_assistant import gpu_arbiter
    restore_gpu = gpu_arbiter.enable_switching()  # SPEC_20 R13: while serving, owner switches free ComfyUI or unload the model
    try:
        # Reserve the port before seeding or rotating any live worker credentials.
        http_server = server.OpenBenchHTTPServer((args.host, args.port), server.OpenBenchHandler)
        if not (os.environ.get("OPENBENCH_DB_URI") or os.environ.get("DATABASE_URL")):
            try:
                uri, cleanup_pg = server._start_local_postgres()
            except (ImportError, OSError, subprocess.CalledProcessError) as exc:
                parser.error("Configure DATABASE_URL / OPENBENCH_DB_URI, install .[embedded], or set OPENBENCH_PG_BIN to PostgreSQL bin "
                             "(OPENBENCH_PG_PORT picks the embedded database port; its log is .openbench_pg/postgres.log). " + type(exc).__name__)
            os.environ["OPENBENCH_DB_URI"] = uri
        conn = http.open_connection()
        try:
            if cfg["mode"] == "dev":
                server.seed_demo_data(conn)
                seed_showcase_media(conn)
                seed_showcase_previs(conn)
                actor = server.DEMO_MEMBERS[0]["actor_id"]
            else:
                repo.ensure_schema(conn)
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM projectops.member")
                    empty = cur.fetchone()[0] == 0
                if empty:
                    actor = os.environ.get("OPENBENCH_ADMIN_ID") or next(iter(cfg["tokens"].values()), None)
                    if not actor:
                        parser.error("First start in header mode requires OPENBENCH_ADMIN_ID")
                    repo.upsert_member(conn, actor, os.environ.get("OPENBENCH_ADMIN_NAME", "Admin"), "admin")
                actor = _launch_actor(conn)
            if not args.no_worker and actor:
                # One set of local media workers serves every production on this server, in every auth mode.
                configurations = worker_configs(args.router_url or args.comfy_url or limb_worker.comfy_base_url({}, args.platform),
                                                platform=args.platform,
                                               api_key_env="COMFY_API_KEY" if os.environ.get("COMFY_API_KEY") else None)
                configurations = load_worker_configs(args.worker_config, configurations)
                registered = register_workers(conn, configurations, actor)
            elif not args.no_worker:
                print("No active crew member owns the media workers; none were registered.", flush=True)
            if cfg["mode"] == "dev":
                # --no-worker leaves worker rows untouched; the showcase binds to those an earlier launch registered.
                workers = registered or local_workers.existing(conn, SHOWCASE_SLUG)
                if SHOWCASE_STAGES <= set(workers):
                    seed_showcase_pipeline(conn, SHOWCASE_SLUG, workers, actor)
            if registered:
                local_workers.adopt_template_pipelines(conn, service.Identity(actor, "ZeroField Studio", "admin"), registered)
            conn.commit()
        finally:
            conn.close()
        if not args.no_worker:
            assistant_worker.start_in_background(http.open_connection, shutdown)
            head_host = "[::1]" if args.host == "::1" else "127.0.0.1"
            threads = start_media_workers(f"http://{head_host}:{http_server.server_port}", registered, shutdown)
        print(f"ZeroField Studio: http://{args.host}:{http_server.server_port}/projects/", flush=True)
        if cfg["mode"] == "dev":
            print("Updraft is a CC0 production bible; its media, when present, come from open-weights models. Generation requires Comfy models and workflows.", flush=True)
        http_server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        shutdown.set()
        for thread in threads:
            thread.join(timeout=1)
        if http_server:
            http_server.server_close()
        if cleanup_pg:
            cleanup_pg()
        restore_gpu()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
