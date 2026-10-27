"""Start ZeroField with original playable fixtures and local/Comfy SDK workers."""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import threading

from openbench_data import resource_path
from project_assistant import flow_runner, limb_worker, limbs, local_workers, worker as assistant_worker
from project_docs import auth, doc_schema, http, repository as repo, service, templates
import server

SHOWCASE_SLUG = "zerofield-showcase"
SAMPLE_FILES = ("cast_kael.png", "set_observatory.png", "keyframe_s01.png", "shot_s01.mp4",
                "keyframe_s02.png", "shot_s02.mp4", "openjutsu_source.mp4",
                "openjutsu_remastered.mp4", "openjutsu_split.mp4", "first_frame_vfx01.png",
                "motion_structure_vfx01.mp4", "anchor_keyframe_vfx01.png")
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


def seed_showcase_media(conn, slug=SHOWCASE_SLUG, *, samples_dir=None, actor_id=None):
    """Fill only empty demo cells once; never rewrite an existing take or user prompt.

    Caller owns the transaction. Raw template calls remain empty planning slates.
    """
    actor_id = actor_id or server.DEMO_MEMBERS[0]["actor_id"]
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("zerofield-showcase-seed:" + slug,))
        cur.execute("SELECT 1 FROM projectops.audit_log WHERE project_slug=%s AND action='studio_showcase_seed'", (slug,))
        if cur.fetchone():
            return seed_showcase_reference_pack(conn, slug, samples_dir=samples_dir, actor_id=actor_id)
    if not repo.get_project(conn, slug):
        return {"seeded": False, "reason": "project_missing"}
    root = Path(samples_dir) if samples_dir else resource_path("samples")
    missing = [name for name in SAMPLE_FILES if not (root / name).is_file()]
    if missing:
        raise FileNotFoundError("Showcase files missing: " + ", ".join(missing))
    urls = {}
    for name in SAMPLE_FILES:
        mime = "image/png" if name.endswith(".png") else "video/mp4"
        identifier = repo.put_asset(conn, slug, data=(root / name).read_bytes(), content_type=mime, actor_id=actor_id)
        urls[name] = f"/projects/api/{slug}/assets/{identifier}"
    targets = {
        "soul-cast": {"CAST-01": {3: "cast_kael.png"}, "SET-01": {3: "set_observatory.png"}},
        "cinema-studio": {"S01": {4: "keyframe_s01.png", 5: "shot_s01.mp4"},
                          "S02": {4: "keyframe_s02.png", 5: "shot_s02.mp4"}},
        "openjutsu-lab": {"VFX-01": {2: "openjutsu_source.mp4", 4: "openjutsu_remastered.mp4", 5: "openjutsu_split.mp4"}},
    }
    values = repo.field_values(conn, slug)
    changed, review_row = [], None
    for key, row_targets in targets.items():
        tab = repo.get_tab_for_update(conn, slug, key)
        if not tab:
            continue
        doc = copy.deepcopy(tab["doc"])
        dirty = False
        for table in doc.get("content", []):
            if table["type"] != "table":
                continue
            for row in table.get("content", [])[1:]:
                cells = row.get("content", [])
                label = _text(cells[0]) if cells else ""
                if label not in row_targets or len(cells) < 7:
                    continue
                pristine = not any(_text(cells[col], values.get(key)) for col in row_targets[label])
                added = False
                for col, name in row_targets[label].items():
                    if not _text(cells[col], values.get(key)):
                        _set_text(cells[col], urls[name])
                        added = dirty = True
                if not added:
                    continue
                status_col = 5 if key == "soul-cast" else 6
                status = next((n for p in cells[status_col].get("content", []) for n in p.get("content", []) if n["type"] == "status"), None)
                if pristine and status and _text(status, values.get(key)) == "Queued":
                    label_status = "Pending Review" if label in ("S02", "VFX-01") else "Approved"
                    status["attrs"]["label"] = label_status
                    repo.set_field_value(conn, slug, key, status["attrs"]["fid"], kind="status", value=label_status, actor_id=actor_id)
                if key == "cinema-studio" and label == "S02" and pristine:
                    review_row = (row["attrs"]["bid"], table["attrs"]["bid"])
        if dirty:
            clean, _ = doc_schema.validate_doc(doc, slug=slug)
            repo.save_tab_doc(conn, slug, key, doc=clean, title=tab["title"], actor_id=actor_id,
                              session_id="studio-showcase-seed", base_revision=tab["revision"], force_revision=True)
            changed.append(key)
    if review_row:
        rid, table_id = review_row
        annotation_id = repo.row_annotation_id(conn, slug, "cinema-studio", rid, actor_id)
        repo.add_activity(conn, slug, "cinema-studio", rid, kind="comment", actor_id=actor_id,
            body="@Cinematographer Please re-shoot S02 with a slower signal pulse and hold the recorder close-up. Procedural playback fixture; review continuity before approving.",
            annotation_id=annotation_id)
    repo.add_audit(conn, slug, action="studio_showcase_seed", actor_id=actor_id,
                   detail={"tabs": changed, "provenance": "Original procedural CC0 playback fixtures; not model renders"})
    seed_showcase_reference_pack(conn, slug, samples_dir=samples_dir, actor_id=actor_id)
    return {"seeded": True, "tabs": changed}


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
    """Append prepared reference stages once, retaining existing column IDs and media."""
    actor_id = actor_id or server.DEMO_MEMBERS[0]["actor_id"]
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM projectops.audit_log WHERE project_slug=%s AND action='studio_reference_pack_seed'", (slug,))
        if cur.fetchone():
            return {"seeded": False, "reason": "already_seeded"}
    tab = repo.get_tab_for_update(conn, slug, "openjutsu-lab")
    if not tab:
        return {"seeded": False, "reason": "page_missing"}
    root = Path(samples_dir) if samples_dir else resource_path("samples")
    stages = [("First Frame", "image", "first_frame_vfx01.png"),
              ("Motion Structure", "video", "motion_structure_vfx01.mp4"),
              ("Anchor Keyframe", "image", "anchor_keyframe_vfx01.png")]
    doc = copy.deepcopy(tab["doc"])
    dirty = False
    for table in doc.get("content", []):
        if table["type"] != "table":
            continue
        rows = table.get("content", [])
        if not rows:
            continue
        if not any(_text(row.get("content", [{}])[0]) == "VFX-01" for row in rows[1:]):
            continue
        headers, added = _append_columns(table, [(name, kind) for name, kind, _ in stages])
        dirty = dirty or added
        for name, kind, filename in stages:
            col = headers.index(name)
            for row in rows[1:]:
                if _text(row["content"][0]) != "VFX-01" or _text(row["content"][col]):
                    continue
                mime = "image/png" if kind == "image" else "video/mp4"
                identifier = repo.put_asset(conn, slug, data=(root / filename).read_bytes(), content_type=mime, actor_id=actor_id)
                _set_text(row["content"][col], f"/projects/api/{slug}/assets/{identifier}")
                dirty = True
    if dirty:
        clean, _ = doc_schema.validate_doc(doc, slug=slug)
        repo.save_tab_doc(conn, slug, "openjutsu-lab", doc=clean, title=tab["title"], actor_id=actor_id,
                         session_id="studio-reference-pack-seed", base_revision=tab["revision"], force_revision=True)
    brief = repo.get_tab_for_update(conn, slug, "director-brief")
    old_note = "The slate below is a planning template. Media cells are empty. Image and video generation require configured workers and validated workflows."
    if brief:
        brief_doc = copy.deepcopy(brief["doc"])
        updated = False
        for block in brief_doc.get("content", []):
            if block.get("type") == "paragraph" and _text(block) == old_note:
                block["content"] = [{"type": "text", "text": "This showcase uses original procedural playback fixtures, including a source-derived PNG and edge motion guide. The illustrative anchor is not a model-generated character swap. Configure Comfy models and an external image-edit workflow to generate production takes."}]
                updated = True
        if updated:
            repo.save_tab_doc(conn, slug, "director-brief", doc=brief_doc, title=brief["title"], actor_id=actor_id,
                session_id="studio-reference-pack-seed", base_revision=brief["revision"], force_revision=True)
    repo.add_audit(conn, slug, action="studio_reference_pack_seed", actor_id=actor_id,
                   detail={"provenance": "Source-derived first frame/edge guide; illustrative anchor, not model output"})
    return {"seeded": dirty, "tabs": ["openjutsu-lab"] if dirty else []}


def seed_showcase_previs(conn, slug=SHOWCASE_SLUG, *, samples_dir=None, actor_id=None):
    """Add the Previs, Actor Matte and Pose Skeleton columns to the cinema slate once and give S03 its grey blockout,
    keeping user media.

    The 3D Stage writes all three on Render previs; the matte frees the actor in the Layout Render and the skeleton
    carries the acting (SPEC_10 §7.7)."""
    actor_id = actor_id or server.DEMO_MEMBERS[0]["actor_id"]
    tab = repo.get_tab_for_update(conn, slug, "cinema-studio")
    if not tab:
        return {"seeded": False, "reason": "page_missing"}
    root = Path(samples_dir) if samples_dir else resource_path("samples")
    doc = copy.deepcopy(tab["doc"])
    dirty = False
    for table in doc.get("content", []):
        if table["type"] != "table" or not table.get("content"):
            continue
        headers, dirty = _append_columns(table, [("Previs", "video"), ("Actor Matte", "video"), ("Pose Skeleton", "video")])
        col = headers.index("Previs")
        for row in table["content"][1:]:
            if _text(row["content"][0]) == "S03" and not _text(row["content"][col]) and (root / "previs_s03_blockout.mp4").is_file():
                identifier = repo.put_asset(conn, slug, data=(root / "previs_s03_blockout.mp4").read_bytes(), content_type="video/mp4", actor_id=actor_id)
                _set_text(row["content"][col], f"/projects/api/{slug}/assets/{identifier}")
                dirty = True
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
        # Union-Control IC-LoRA takes his acting from the stage's pose skeleton (SPEC_10 §7.7).
        "layoutkey": {"image_gen": comfy("flux3_klein_look_key.json", prompt_node=None, output_node="9", reference_role="anchor_keyframe",
                                         input_bindings={"20.video": {"source": "previs_video", "upload": "video"},
                                                         "20.frame_load_cap": {"literal": 1},
                                                         "23.batch_index": {"literal": 0},
                                                         "6.text": {"literal": LAYOUT_KEY_PROMPT},
                                                         "21.image": {"source": "asset_images.0", "upload": "image"},
                                                         "22.image": {"source": "asset_images.1", "upload": "image", "optional": True}})},
        "layout": {"video_gen": comfy("ltx25_layout_render.json", output_node="12", prompt_node="30", prompt_input="string_a",
                                      seed_node="50", seed_input="noise_seed",
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
        known.append(default)
    lanes = []  # (audit action, chain) appended once to a pipeline the user has rearranged
    if "motion" in registered:
        # Fourth lane: previs-driven shots (grey blockout -> motion pass -> look key -> look pass).
        known.append(normalized)
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
        known.append(normalized)
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
        known.append(normalized)
        layout_chain = [node("layoutkey", "Layout Key", "image_gen", "cinema-studio", 4),
                        node("layout", "Layout Render", "video_gen", "cinema-studio", 5)]
        for depth, item in enumerate(layout_chain):
            item.update(x=300 + depth * 340, y=1360)
        nodes = nodes + layout_chain
        edges = edges + [{"source": "layoutkey", "target": "layout"}]
        graph = {"nodes": nodes, "edges": edges}
        normalized = flow_runner.validate_definition(graph)
        lanes.append(("studio_layout_lane_seed", layout_chain))
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
            print("The Last Signal includes original procedural playback fixtures; generation requires Comfy models and workflows.", flush=True)
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
