"""Pure authorized-snapshot context, slot and prompt compilation; no media or network I/O."""
from __future__ import annotations

import hashlib
import json
import math
import re

from . import runtime
from .runtime import MAX_MATERIALS

__all__ = [
    'prompt_text',
    '_media_urls',
    '_studio_row',
    'snap_dimensions',
    'snap_frame_count',
    'aspect_for',
    'slot_plan',
    'compute_request_fingerprint',
    'compile_h3_agent_instruction_prompt',
    'compile_h3_context_ir',
    'compile_ltx_ingredients_prompt',
    'resolve_studio_context',
    '_MISSING',
    '_context_value',
    '_shot_media_candidates',
]


def prompt_text(task, config):
    source = task.get("input", {})
    column = config.get("prompt_column")
    rows = source.get("rows", [])
    if column is not None and rows:
        if type(column) is not int or column < 0:
            raise runtime.WorkerError("prompt_column must be a zero-based integer")
        return "\n".join(str(row.get("cells", [])[column]) for row in rows if len(row.get("cells", [])) > column)
    return source.get("prompt", "") + "\n" + "\n".join(t.get("text", "") for t in source.get("tabs", []))


def _media_urls(value):
    """Ordered and de-duplicated project asset references, never remote model URLs."""
    found = []
    def visit(item):
        if isinstance(item, dict):
            if isinstance(item.get("asset_url"), str):
                visit(item["asset_url"])
            for key, child in item.items():
                if key != "asset_url":
                    visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)
        elif isinstance(item, str):
            for url in re.findall(r"/projects/api/[a-z0-9-]+/assets/pa_[0-9a-f]{32}", item):
                if url not in found:
                    found.append(url)
    visit(value)
    return found


def _studio_row(task):
    source = task.get("input", {})
    rows = source.get("structured_rows") or source.get("rows", [])
    row_id = task.get("row_id") or source.get("row_id")
    target = source.get("target") or task.get("target") or {}
    matches = [row for row in rows if not row_id or row.get("row_id") == row_id]
    preferred = [row for row in matches if (not target.get("tab_key") or row.get("tab_key") == target["tab_key"])
                 and (not target.get("table_id") or row.get("table_id") == target["table_id"])]
    if preferred:
        matches = preferred
    if row_id and not matches:
        raise runtime.WorkerError("The requested studio row is missing from the task input")
    # A missing requested row must never silently bind a different shot.
    row = next(iter(matches), {})
    table = next((table for tab in source.get("tabs", []) if tab.get("tab_key") == row.get("tab_key")
                  for table in tab.get("tables", []) if table.get("table_id") == row.get("table_id")), {})
    return row, table


def snap_dimensions(width: int, height: int, grid_size: int = 32) -> tuple[int, int]:
    """Snap spatial dimensions to an exact multiple of grid_size (default 32px)."""
    w, h, g = int(width), int(height), int(grid_size)
    if w <= 0 or h <= 0 or g < 2:
        raise runtime.WorkerError("Dimensions and grid_size must be positive integers")
    snapped_w = min(4096, max(g, int(round(w / float(g))) * g))
    snapped_h = min(4096, max(g, int(round(h / float(g))) * g))
    return snapped_w, snapped_h


def snap_frame_count(frames: int, frame_rule: str = "none") -> int:
    """Align frame count to engine temporal formula ('none', '8n+1' for LTX-2.5, '17n+5' for MiniMax H3)."""
    n = int(frames)
    if n < 1:
        raise runtime.WorkerError("Frame count must be positive")
    rule = str(frame_rule or "none").strip().lower()
    if rule in ("", "none", "passthrough"):
        return n
    if rule == "8n+1":
        base = max(9, n)
        return base + (1 - (base % 8)) % 8
    if rule == "17n+5":
        base = max(5, n)
        return base + (5 - (base % 17)) % 17
    raise runtime.WorkerError(f"Unsupported frame_rule: {frame_rule}")


def aspect_for(media: dict, options: list[str]) -> str:
    """Pick the closest aspect_ratio option by log-ratio distance."""
    w_media = float(media.get("width") or 0)
    h_media = float(media.get("height") or 0)
    if w_media <= 0 or h_media <= 0 or not options:
        raise runtime.WorkerError("Valid media dimensions and aspect_ratio options are required")
    ratio = w_media / h_media
    def distance(option: str) -> float:
        prefix = str(option).split(" ")[0]
        w, h = map(float, prefix.split(":"))
        return abs(math.log(ratio / (w / h)))
    return min(options, key=distance)


def slot_plan(assets: list, slot_count: int, *, limit: int = MAX_MATERIALS,
              excluded_ids: set[str] | list[str] | None = None) -> list:
    """Allocate pictured @Assets to reference image slots, excluding forbidden or text-only items."""
    excluded = {str(x).strip().lstrip("@").upper() for x in (excluded_ids or ()) if str(x).strip()}
    pictured = []
    for index, asset in enumerate(assets or ()):
        get = asset.get if isinstance(asset, dict) else lambda k, d=None: getattr(asset, k, d)
        asset_id = str(get("asset_id", "") or "").strip().lstrip("@").upper()
        if asset_id and asset_id in excluded:
            continue
        if bool(get("offstage", False)) or bool(get("excluded", False)):
            continue
        has_image = bool(get("reference_urls") or get("url") or str(get("status", "") or "") == "local")
        if not has_image:
            continue
        anchor_rank = 0 if get("anchor_priority", False) else 1
        appear = int(get("appear_count", 1) if get("appear_count") is not None else 1)
        cast_order = int(get("cast_order", 1_000_000) if get("cast_order") is not None else 1_000_000)
        pictured.append((anchor_rank, -appear, cast_order, index, asset))
    pictured.sort(key=lambda item: item[:4])
    target_count = max(0, int(slot_count))
    chosen = [item[4] for item in pictured[:max(0, min(int(limit), target_count))]]
    return chosen + [None] * max(0, target_count - len(chosen))


def compute_request_fingerprint(project_slug: str, row_id: str, card_id: str, values: dict) -> str:
    """Compute a deterministic SHA-256 fingerprint locking media inputs, duration, and aspect ratio."""
    normalized = {str(k): str(v if v is not None else "None") for k, v in sorted((values or {}).items())}
    payload = [str(project_slug or ""), str(row_id or ""), str(card_id or ""), normalized]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def compile_h3_agent_instruction_prompt(request: dict, times: list[float]) -> str:
    """Build the role-separated agent prompt for 8-frame timestamped contact-sheet analysis."""
    pictures = request.get("pictures") or []
    values = request.get("values") or {}
    names = "\n".join(
        f"Attachment {idx + 1} = Reference Image {pic.get('slot', idx + 1)} (<Picture {pic.get('slot', idx + 1)}> / 圖片素材{pic.get('slot', idx + 1)}: {pic.get('name', '')})"
        for idx, pic in enumerate(pictures)
    )
    return (
        "You are the ZeroField H3 Motion-Reference Instruction Agent. Return JSON only: "
        "{\"instruction\": \"...\", \"summary\": \"...\"}.\n"
        "Strict Role Separation Rule:\n"
        "- Reference Images (<Picture 1..N> / 圖片素材1..N) define ONLY character identity, face, wardrobe, props, art style, scene geometry, and lighting.\n"
        "- Reference Video 1 (<Video 1> / 參考影片1) defines ONLY motion timing, movement sequence, displacement direction, center-of-gravity shift, and camera trajectory. Never inherit source video blur, compression artifacts, noise, or original actor identity.\n"
        "- The final attachment is an 8-frame timestamped overview (motion-frames) at seconds "
        f"{list(times)} for action comprehension only; never cite the contact sheet as a generation image slot.\n"
        f"Target duration: {values.get('259.value', '5')}s, Aspect ratio: {values.get('252.aspect_ratio', '16:9 (Widescreen)')}.\n"
        f"{names}\n"
        f"Director notes: {str(request.get('directions') or '')[:4000]}"
    )


def compile_h3_context_ir(ctx: dict, config: dict | None = None) -> str:
    """Compile the 6-section H3-Context-IR structured prompt for MiniMax H3 Ref2VA."""
    config = config or {}
    resolved = ctx.get("resolved_assets") or []
    subj_lines = []
    if resolved:
        for idx, asset in enumerate(resolved, 1):
            subj_lines.append(
                f"<Subject {idx}> is the entity ({asset['asset_id']} - {asset['name']}) represented by <Picture {idx}>: "
                f"{asset['appearance_prompt']}. Reference sheet backgrounds, multi-view borders, and UI labels in <Picture {idx}> are not part of <Subject {idx}>."
            )
    else:
        subj_lines.append("<Subject 1> is the primary subject represented by <Picture 1>. Reference sheet borders and backdrop are not part of <Subject 1>.")
    subj_lines.append(
        "<Video 1> supplies the original video to be edited: source performance, head and body orientation, camera trajectory, source timing, scene, physical objects and subtitle placement. Source appearance follows the replacement scope below."
    )
    subj_lines.append(
        "<Audio 1> supplies the synchronized production audio, dialogue timing, and room ambience."
    )
    subj_refs = ", ".join(f"<Subject {i}>" for i in range(1, max(1, len(resolved)) + 1))
    summary = (
        f"[video editing + reference generation] Replace each bound source role in <Video 1> with its corresponding identity {subj_refs}. "
        "The bound roles keep their source positions and performance; reference identities replace them throughout, with source appearance retained where required by the replacement scope."
    )
    retention = (
        "<Subject 1>: fully_preserved for the supplied identity attributes only. "
        "<Video 1>: partially_preserved; preserve source action, orientation, camera, scene, lighting, visual style and timing. "
        "Replacement mode: identity-and-appearance. Preserve appearance attributes not covered by the current identity references. "
        "Reference backgrounds, sheet layouts, poses and unrelated props do not enter the scene. "
        "Facial geometry and physique follow the supplied reference attributes, without inheriting the source actor facial proportions. "
        "Preserve attributes not covered by the identity references."
    )
    raw_action = str(ctx.get("action_prompt") or ctx.get("compiled_prompt") or "Performs the choreography from <Video 1>.").strip()
    for idx, asset in enumerate(resolved, 1):
        raw_action = re.sub(rf"@?\b{re.escape(asset['asset_id'])}\b", f"<Subject {idx}> ({asset['name']})", raw_action, flags=re.I)
    dialogue_match = re.search(r'"([^"]+)"|「([^」]+)」', raw_action)
    if "<d>" not in raw_action:
        spoken = dialogue_match.group(1) or dialogue_match.group(2) if dialogue_match else str(config.get("dialogue") or "Hold position and advance on mark.")
        raw_action = f"{raw_action} <d>[English] {spoken}</d>"
    rig_desc = " ".join(p for p in (ctx.get("optical_rig"), ctx.get("camera_motion")) if p)
    shot_prefix = f"[Shot 1] At 00:00.000, {rig_desc + ': ' if rig_desc else ''}"
    detailed = shot_prefix + raw_action
    soundscape = str(config.get("soundscape") or "Coherent room tone and synchronized foley footsteps/cloth movement aligned with <Video 1> and <Audio 1>.")
    music = str(config.get("non_diegetic_music") or "N/A")
    return (
        "subject_definitions:\n" + "\n".join(subj_lines) + "\n"
        "summary:\n" + summary + "\n"
        "retention_analysis:\n" + retention + "\n"
        "detailed_description:\n" + detailed + "\n"
        "overall_soundscape:\n" + soundscape + "\n"
        "non_diegetic_music:\n" + music + "\n"
    )


def compile_ltx_ingredients_prompt(ctx: dict) -> str:
    """Compile spatial panel tags for LTX-2.5 Ingredients IC-LoRA multi-asset reference sheets."""
    base = str(ctx.get("compiled_prompt") or "").strip()
    resolved = [a for a in (ctx.get("resolved_assets") or []) if a.get("reference_urls")]
    if not resolved:
        resolved = list(ctx.get("resolved_assets") or [])
    if not resolved:
        return base
    if len(resolved) == 1:
        labels = ["Center panel"]
    elif len(resolved) == 2:
        labels = ["Left panel", "Right panel"]
    else:
        labels = ["Left panel", "Center panel", "Right panel"] + [f"Panel {i}" for i in range(4, len(resolved) + 1)]
    panels = [f"[{label}: {a['asset_id']} ({a['name']}) — {a['appearance_prompt']}]" for label, a in zip(labels, resolved)]
    return (base + "\nReference Sheet Layout: " + " ".join(panels)).strip()


def _appearance(text):
    """The lock text describes the subject; its seed is a parameter, not words to draw."""
    return re.sub(r"[;,.]?\s*\bseed[:\s=]+\d+\b", "", str(text), flags=re.I).strip(" ;,.")


def _reference_framing(asset_id):
    """Reference renders frame by asset kind, so framing never leaks into shot prompts."""
    kind = re.match(r"@?([A-Z]+)-", str(asset_id).upper())
    kind = kind[1] if kind else ""
    if kind in ("SET", "LOC", "SCENE"):
        return "Environment reference, wide, no people."
    if kind == "PROP":
        return "Isolated prop reference, neutral backdrop, soft key light."
    return "Character reference portrait, waist-up, neutral backdrop, soft key light."


def _take_seed(base, take):
    """Take 1 keeps the asset's identity seed; each re-shoot of the same cell advances it."""
    return None if base is None else base + (take if isinstance(take, int) and take > 0 else 0)


def resolve_studio_context(task: dict) -> dict:
    """Compile the authorized shot snapshot without I/O or cross-row fallbacks."""
    source = task.get("input", {})
    row, table = _studio_row(task)
    cells = row.get("cells", [])
    columns = list(zip(table.get("headers", []), cells))
    def column(pattern):
        return next((str(value).strip() for header, value in columns
                     if re.search(pattern, str(header), re.I) and value is not None), "")
    excluded_refs = []
    for header, value in columns:
        if isinstance(value, str) and re.search(r"exclude|forbid|ban|禁用|排除", str(header), re.I):
            for match in re.finditer(r"@?\b((?:CAST|SET|LOC|PROP|CHAR|SCENE|STYLE)-\d+(?:[:#][a-z0-9_-]+)?)\b", value, re.I):
                ident = match[1].upper()
                if ident not in excluded_refs:
                    excluded_refs.append(ident)
    for cell in cells:
        if isinstance(cell, str):
            for match in re.finditer(r"(?:!-@?|!@|-@)\b((?:CAST|SET|LOC|PROP|CHAR|SCENE|STYLE)-\d+(?:[:#][a-z0-9_-]+)?)\b", cell, re.I):
                ident = match[1].upper()
                if ident not in excluded_refs:
                    excluded_refs.append(ident)
    excluded_set = set(excluded_refs)
    mentions = []
    appear_counts = {}
    for cell in cells:
        if isinstance(cell, str):
            cleaned = re.sub(r"(?:!-@?|!@|-@)\b(?:CAST|SET|LOC|PROP|CHAR|SCENE|STYLE)-\d+(?:[:#][a-z0-9_-]+)?\b", " ", cell, flags=re.I)
            for match in re.finditer(r"@?\b((?:CAST|SET|LOC|PROP|CHAR|SCENE|STYLE)-\d+(?:[:#][a-z0-9_-]+)?)\b", cleaned, re.I):
                identifier = match[1].upper().replace("#", ":")
                if identifier in excluded_set:
                    continue
                appear_counts[identifier] = appear_counts.get(identifier, 0) + 1
                if identifier not in mentions:
                    mentions.append(identifier)
    assets = {}
    cast_idx = 0
    for tab in source.get("tabs", []):
        for asset_table in tab.get("tables", []):
            headers = asset_table.get("headers", [])
            if tab.get("tab_key") not in ("soul-cast", "assets", "asset-sheet") and not (
                    headers and str(headers[0]).strip().casefold() in ("asset id", "資產代號")):
                continue
            for asset_row in asset_table.get("rows", []):
                values = asset_row.get("cells", [])
                if len(values) < 3:
                    continue
                identifier = str(values[0]).strip().lstrip("@").upper().replace("#", ":")
                cast_idx += 1
                if identifier in mentions and identifier not in assets and identifier not in excluded_set:
                    appearance = str(values[2])
                    seed = re.search(r"seed[:\s=]+(\d+)", appearance, re.I)
                    ref_urls = _media_urls(values)
                    assets[identifier] = {"asset_id": identifier, "name": str(values[1]),
                        "appearance_prompt": appearance, "seed": int(seed[1]) if seed else None,
                        "reference_urls": ref_urls, "appear_count": appear_counts.get(identifier, 1),
                        "cast_order": cast_idx}
    # An unpictured wardrobe variant inherits the base image, never its wardrobe prompt.
    for identifier in mentions:
        base = re.split(r"[:#]", identifier)[0]
        if base in excluded_set:
            assets.pop(identifier, None)
            continue
        if ":" in identifier and not assets.get(identifier, {}).get("reference_urls"):
            for tab in source.get("tabs", []):
                for asset_table in tab.get("tables", []):
                    if tab.get("tab_key") not in ("soul-cast", "assets", "asset-sheet"):
                        continue
                    base_row = next((r for r in asset_table.get("rows", []) if r.get("cells") and str(r["cells"][0]).lstrip("@").upper() == base), None)
                    if base_row and _media_urls(base_row["cells"]):
                        assets.setdefault(identifier, {"asset_id": identifier, "name": str(base_row["cells"][1]), "appearance_prompt": str(base_row["cells"][2]), "seed": None, "appear_count": appear_counts.get(identifier, 1), "cast_order": 1000000})["reference_urls"] = _media_urls(base_row["cells"])
    resolved = [assets[identifier] for identifier in mentions if identifier in assets]
    optical = column(r"optical|rig|camera.*lens|film\s*setup")
    motion = column(r"camera\s*motion|movement|景別|運鏡")
    mode = column(r"jutsu\s*mode|^mode$")
    action = column(r"action.*prompt|swap\s*prompt|prompt|appearance")
    still = task.get("capability") == "image_gen"
    # Text-to-image encoders read "Optical Rig: RED ..." / "Static Tripod" as props to draw; a still has no camera move.
    parts = [f"{label}: {value.rstrip('.')}." for label, value in
             (("Optical Rig", "" if still else optical), ("Camera Movement", "" if still else motion), ("Mode", mode)) if value]
    if still and optical:
        # Image models letter camera brands onto props ("RED V-RAPTOR" on a recorder); keep the lens look only.
        lens = optical.split("/")[-1].strip().rstrip(".")
        parts.insert(0, f"Cinematic film still, {lens} lens look; no camera equipment or brand text in frame.")
    asset_row = row.get("tab_key") in ("soul-cast", "assets", "asset-sheet")
    if resolved and not asset_row:
        parts.append("References: " + "; ".join(f"{a['asset_id']} ({a['name']}): {_appearance(a['appearance_prompt'])}" for a in resolved) + ".")
    # Fallback is scoped to this row; full tab text can include unrelated shots/assets.
    fallback = source.get("prompt", "") + ("\n" + " ".join(str(v) for v in cells) if row else "")
    if asset_row and action and cells:
        parts.append(f"{_appearance(action)}. {_reference_framing(cells[0])}")
    else:
        parts.append(action or fallback.strip() or prompt_text(task, {}))
    predecessors = [p for p in source.get("predecessor_tasks", [])
                    if not row.get("row_id") or not p.get("row_id") or p["row_id"] == row["row_id"]]
    row_urls = _media_urls(cells)
    predecessor_urls = _media_urls(predecessors)
    references = list(dict.fromkeys(url for asset in resolved for url in asset["reference_urls"]))
    roles = {}
    patterns = {
        "source_video": r"source.*video|driving.*video|original.*video|原片",
        "first_frame": r"first\s*frame|extracted\s*frame|source\s*frame|第一幀|首幀原圖",
        "motion_structure_video": r"motion\s*structure|structure.*video|control.*video|pose|depth|動作結構",
        "anchor_keyframe": r"anchor.*frame|swapped.*frame|keyframe|關鍵幀|首幀|定錨",
        "output_video": r"cinema\s*shot|remastered.*video|output.*video|成品",
        "ingredients_sheet": r"ingredients.*sheet|composite.*sheet|multi.*ref.*sheet|組合圖",
        "frame_sheet": r"frame.*sheet|contact.*sheet|motion.*frames|畫格總覽",
        "time_strata": r"time.*strata|onion.*skin|時間摺層",
    }
    for header, value in columns:
        urls = _media_urls(value)
        if not urls:
            continue
        for role, pattern in patterns.items():
            if re.search(pattern, str(header), re.I):
                roles.setdefault(role, urls[0])
                break  # First Frame must not also become an anchor keyframe.
    aliases = {"source_video_url": "source_video", "first_frame_url": "first_frame",
               "structure_video": "motion_structure_video", "motion_structure": "motion_structure_video",
               "keyframe": "anchor_keyframe", "primary_image_url": "anchor_keyframe",
               "remastered_video": "output_video", "cinema_shot": "output_video"}
    predecessor_images = []
    for predecessor in predecessors:
        output = predecessor.get("output") or {}
        urls = _media_urls(output)
        role = output.get("reference_role") or predecessor.get("reference_role")
        role = aliases.get(role, role)
        if role in patterns and urls:
            roles[role] = urls[0]
        for name in patterns:
            direct = _media_urls(output.get(name, ""))
            if direct:
                roles[name] = direct[0]
        if role not in ("source_video", "motion_structure_video", "output_video") and not str(output.get("content_type", "")).startswith(("video/", "audio/")):
            predecessor_images.extend(urls)
    if not roles.get("source_video"):
        # Legacy headerless row inputs still work; actual MIME is checked before upload.
        roles["source_video"] = next(iter(row_urls), None)
    asset_map = {asset["asset_id"]: dict(asset, url=next(iter(asset["reference_urls"]), None)) for asset in resolved}
    compiled_prompt = "\n".join(p for p in parts if p)
    planned_slots = slot_plan(resolved, 6, limit=runtime.MAX_MATERIALS, excluded_ids=excluded_refs)
    ctx = {"compiled_prompt": compiled_prompt,
           "action_prompt": action,
           "seed": _take_seed(next((a["seed"] for a in resolved if a["seed"] is not None), None), source.get("take")),
           "optical_rig": optical, "camera_motion": motion, "jutsu_mode": mode,
           "resolved_assets": resolved, "asset_map": asset_map,
           "excluded_refs": excluded_refs, "slot_plan": planned_slots,
           "asset_images": references, "reference_image_urls": references,
           "primary_image_url": roles.get("anchor_keyframe") or roles.get("ingredients_sheet") or roles.get("first_frame") or
                                next(iter(predecessor_images or references), None),
           **{role: roles.get(role) for role in patterns},
           "source_video_url": roles.get("source_video")}
    ctx["h3_context_ir_prompt"] = compile_h3_context_ir(ctx)
    ctx["ltx_ingredients_prompt"] = compile_ltx_ingredients_prompt(ctx)
    return ctx


_MISSING = object()


def _context_value(ctx, path):
    value = ctx
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part, _MISSING)
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return _MISSING
    return value


def _shot_media_candidates(task):
    source = task.get("input", {})
    row, _ = _studio_row(task)
    predecessors = [p for p in source.get("predecessor_tasks", []) if not row.get("row_id") or not p.get("row_id") or p["row_id"] == row["row_id"]]
    urls = _media_urls(predecessors) + _media_urls(row.get("cells", []))
    if not (source.get("structured_rows") or source.get("rows")):
        urls += _media_urls({k: v for k, v in source.items() if k != "tabs"})
    return list(dict.fromkeys(urls))
