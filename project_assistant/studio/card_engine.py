"""Declarative Studio Cards, workflow conversion/binding and official Comfy execution."""
from __future__ import annotations

from openbench_data import resource_path
from pathlib import Path
import copy
import io
import json
import mimetypes
import math
import os
import re
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from . import context_compiler, runtime
from . import _compat as legacy

__all__ = [
    'CARD_FIELD_TYPES',
    'CARD_SLOTS',
    'CARD_OUTPUT_MODES',
    'CARDS_DIR',
    'validate_studio_card',
    'card_execution_profile',
    'validate_direct_card_values',
    'load_studio_card',
    'build_node_info',
    '_PASSTHROUGH_IMAGE_CLASSES',
    '_KNOWN_WIDGET_NAMES',
    'convert_litegraph_to_api',
    '_unlink_node_and_dependents',
    'inject_node_info_into_workflow',
    'resolve_pass2_source',
    'bind_external_workflow',
    '_SDK_ENV_LOCK',
    'parse_runninghub_curl_or_payload',
    'extract_studio_card_from_workflow',
    'ComfyPlatformClient',
    'comfy_platform',
    '_build_card_form_values',
    '_normalize_comfy_error',
    'comfyui',
]


CARD_FIELD_TYPES = frozenset({"IMAGE", "AUDIO", "VIDEO", "STRING", "LIST", "INT", "FLOAT"})


CARD_SLOTS = frozenset({None, "ref", "prompt", "driving_video", "structure_video", "duration", "aspect_ratio", "seed"})


CARD_OUTPUT_MODES = frozenset({"video", "image", "audio"})


CARDS_DIR = resource_path("workflows", "cards")


def card_execution_profile(card: dict) -> dict:
    """Legacy graphs default to local open weights; explicit drivers have fixed tiers."""
    config = card.get("engine_config") or {}
    driver = config.get("driver") or ("comfy_local" if card.get("engine", "comfyui") == "comfyui" else "vendor_api")
    tiers = {"comfy_local": "open_weights", "comfy_partner": "closed_hybrid",
             "vendor_api": "closed_hero", "runninghub_cloud": "cloud_burst", "comfy_router": "cloud_burst"}
    if not isinstance(driver, str) or driver not in tiers:
        raise runtime.WorkerError("Unsupported Studio card driver")
    tier = config.get("tier", tiers[driver])
    requires = driver in ("comfy_local", "comfy_partner")
    if tier != tiers[driver] or ("requires_comfyui" in config and config["requires_comfyui"] is not requires):
        raise runtime.WorkerError("Studio card driver, tier and requires_comfyui disagree")
    return {"driver": driver, "tier": tier, "requires_comfyui": requires}


def validate_direct_card_values(card: dict, values: dict) -> list[dict]:
    """Validate semantic API inputs without inspecting or compiling graph nodes."""
    if not isinstance(values, dict):
        raise runtime.WorkerError("Card inputs must be an object")
    nodes = {f"{n['nodeId']}.{n['fieldName']}": n for n in card["nodes"]}
    if set(values) - set(nodes):
        raise runtime.WorkerError("Unknown direct card input")
    result = build_node_info(card, values)
    for item in result:
        key = f"{item['nodeId']}.{item['fieldName']}"
        node = nodes[key]
        value = values.get(key)
        if value is None:
            value = node.get("defaultValue", "")
        if isinstance(value, (dict, list, tuple, bool)):
            raise runtime.WorkerError("Invalid direct card input type")
        text = str(value).strip()
        kind = node["fieldType"]
        missing = not text or (kind in ("IMAGE", "VIDEO", "AUDIO") and text.lower() == "none")
        if node.get("required") and missing:
            raise runtime.WorkerError("Required direct card input is missing")
        if kind in ("INT", "FLOAT"):
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise runtime.WorkerError("Direct card numeric input is invalid") from None
            if (not math.isfinite(number) or (kind == "INT" and not number.is_integer())
                    or (node.get("min") is not None and number < node["min"])
                    or (node.get("max") is not None and number > node["max"])):
                raise runtime.WorkerError("Direct card numeric input is outside its allowed range")
            item["fieldValue"] = str(int(number)) if kind == "INT" else str(number)
        elif kind == "LIST" and text not in node["options"]:
            raise runtime.WorkerError("Direct card selection is not an allowed option")
        elif kind in ("IMAGE", "VIDEO", "AUDIO"):
            item["fieldValue"] = "None" if missing else text
        elif len(text) > 64000:
            raise runtime.WorkerError("Direct card text exceeds the input limit")
    return result


def validate_studio_card(card: dict) -> dict:
    """Validate and normalize a RunningHub-style declarative Studio Card."""
    if not isinstance(card, dict):
        raise runtime.WorkerError("Studio card must be an object")
    card_id = str(card.get("card_id") or "").strip()
    label = str(card.get("label") or "").strip()
    output_mode = str(card.get("output_mode") or "").strip().lower()
    if not card_id or not label:
        raise runtime.WorkerError("Studio card requires card_id and label")
    if output_mode not in CARD_OUTPUT_MODES:
        raise runtime.WorkerError(f"Unsupported card output_mode: {output_mode}")
    engine_config = card.get("engine_config")
    if not isinstance(engine_config, dict):
        raise runtime.WorkerError("Studio card engine_config must be an object")
    engine_config = dict(engine_config, **card_execution_profile(card))
    direct = engine_config["driver"] in ("vendor_api", "runninghub_cloud", "comfy_router")
    if direct and any(engine_config.get(k) for k in ("locked_nodes", "disabled_loras")):
        raise runtime.WorkerError("Direct cards cannot configure graph node mutations")
    if engine_config["driver"] == "comfy_router":
        from .comfy_router import validate_config
        validate_config(engine_config, output_mode)
    raw_nodes = card.get("nodes")
    if not isinstance(raw_nodes, (list, tuple)) or not raw_nodes:
        raise runtime.WorkerError("Studio card nodes must be a non-empty list")
    normalized_nodes = []
    seen = set()
    for idx, raw in enumerate(raw_nodes):
        if not isinstance(raw, dict):
            raise runtime.WorkerError(f"nodes[{idx}] must be an object")
        node_id = str(raw.get("nodeId") or "").strip()
        field_name = str(raw.get("fieldName") or "").strip()
        field_type = str(raw.get("fieldType") or "").strip().upper()
        node_label = str(raw.get("label") or "").strip()
        if not node_id or not field_name or not node_label:
            raise runtime.WorkerError(f"nodes[{idx}] requires nodeId, fieldName and label")
        if engine_config["driver"] in ("vendor_api", "comfy_router"):
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", node_id) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", field_name):
                raise runtime.WorkerError("Vendor card requires named semantic input identifiers, not graph node IDs")
            if any(n["fieldName"] == field_name for n in normalized_nodes):
                raise runtime.WorkerError("Vendor semantic field names must be unique")
        if field_type not in CARD_FIELD_TYPES:
            raise runtime.WorkerError(f"nodes[{idx}].fieldType is not supported: {field_type}")
        if (node_id, field_name) in seen:
            raise runtime.WorkerError(f"Duplicate card node field pair: {node_id}.{field_name}")
        seen.add((node_id, field_name))
        slot = raw.get("slot")
        if slot is not None:
            slot = str(slot).strip()
        if slot not in CARD_SLOTS:
            raise runtime.WorkerError(f"nodes[{idx}].slot is not supported: {slot}")
        if slot == "duration" and field_type not in ("INT", "FLOAT"):
            raise runtime.WorkerError(f"nodes[{idx}].slot duration requires a numeric fieldType")
        node = {
            "nodeId": node_id,
            "fieldName": field_name,
            "fieldType": field_type,
            "label": node_label,
            "required": bool(raw.get("required", False)),
            "hidden": bool(raw.get("hidden", False)),
        }
        if slot is not None:
            node["slot"] = slot
        if raw.get("defaultValue") is not None:
            node["defaultValue"] = str(raw["defaultValue"])
        if raw.get("projectDefaults") is not None:
            if not isinstance(raw["projectDefaults"], dict):
                raise runtime.WorkerError(f"nodes[{idx}].projectDefaults must be an object")
            node["projectDefaults"] = {str(k): str(v) for k, v in raw["projectDefaults"].items()}
        if field_type == "LIST":
            options = raw.get("options")
            if not isinstance(options, (list, tuple)) or not options:
                raise runtime.WorkerError(f"nodes[{idx}].options is required for LIST")
            node["options"] = [str(opt) for opt in options]
            if raw.get("optionLabels") is not None:
                labels = raw["optionLabels"]
                if not isinstance(labels, (list, tuple)) or len(labels) != len(node["options"]):
                    raise runtime.WorkerError(f"nodes[{idx}].optionLabels must match options length")
                node["optionLabels"] = [str(lbl) for lbl in labels]
            if "defaultValue" in node and node["defaultValue"] not in node["options"]:
                raise runtime.WorkerError(f"nodes[{idx}].defaultValue is not one of options")
            for val in node.get("projectDefaults", {}).values():
                if val not in node["options"]:
                    raise runtime.WorkerError(f"nodes[{idx}].projectDefaults value is not one of options")
        if field_type in ("INT", "FLOAT"):
            for bound in ("min", "max", "step"):
                if raw.get(bound) is not None:
                    try:
                        number = float(raw[bound])
                    except (TypeError, ValueError):
                        raise runtime.WorkerError(f"nodes[{idx}] numeric bounds must be finite") from None
                    if not math.isfinite(number) or (bound == "step" and number <= 0):
                        raise runtime.WorkerError(f"nodes[{idx}] numeric bounds must be finite with positive step")
                    node[bound] = number
            if node.get("min", -math.inf) > node.get("max", math.inf):
                raise runtime.WorkerError(f"nodes[{idx}] min cannot exceed max")
            check_vals = []
            if "defaultValue" in node:
                check_vals.append(node["defaultValue"])
            check_vals.extend(node.get("projectDefaults", {}).values())
            for raw_val in check_vals:
                try:
                    num = float(raw_val)
                except (TypeError, ValueError):
                    raise runtime.WorkerError(f"nodes[{idx}] default value must be numeric") from None
                if not math.isfinite(num) or (field_type == "INT" and not num.is_integer()):
                    raise runtime.WorkerError(f"nodes[{idx}] default value must be finite and match fieldType")
                if node.get("min") is not None and num < node["min"]:
                    raise runtime.WorkerError(f"nodes[{idx}] default value is below min")
                if node.get("max") is not None and num > node["max"]:
                    raise runtime.WorkerError(f"nodes[{idx}] default value is above max")
        normalized_nodes.append(node)
    return {
        "card_id": card_id,
        "label": label,
        "sublabel": str(card.get("sublabel") or ""),
        "group_label": str(card.get("group_label") or ""),
        "icon": str(card.get("icon") or ""),
        "output_mode": output_mode,
        "engine_key": str(card.get("engine_key") or "comfy-webapp/1"),
        "engine_config": copy.deepcopy(engine_config),
        "nodes": normalized_nodes,
        "status": str(card.get("status") or "active"),
        "sort_order": int(card.get("sort_order") or 0),
    }


def load_studio_card(card_id_or_path: str | Path) -> dict:
    """Load and validate a Studio Card by card_id, webappId/workflowId, or Path object.

    Strings are identifiers resolved inside CARDS_DIR only: HTTP/task supplied IDs such
    as ``.env`` must never be read as files relative to the process working directory.
    """
    candidate = card_id_or_path if isinstance(card_id_or_path, Path) else None
    if candidate is None or not candidate.is_file():
        stem = str(card_id_or_path).strip().removesuffix(".json")
        candidate = legacy.CARDS_DIR / f"{stem}.json"
        if not candidate.is_file() and legacy.CARDS_DIR.is_dir():
            for card_file in sorted(legacy.CARDS_DIR.glob("*.json")):
                try:
                    raw = json.loads(card_file.read_text(encoding="utf-8-sig"))
                except (OSError, ValueError):
                    continue
                ecfg = raw.get("engine_config") or {}
                if str(raw.get("card_id") or "") == stem or str(ecfg.get("webappId") or "") == stem or str(ecfg.get("workflowId") or "") == stem:
                    candidate = card_file
                    break
    if not candidate.is_file():
        raise runtime.WorkerError(f"Studio card not found: {card_id_or_path}")
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise runtime.WorkerError(f"Invalid studio card JSON: {candidate.name}") from None
    return validate_studio_card(payload)


def build_node_info(card: dict, form_values: dict | None = None) -> list[dict]:
    """Compile a Studio Card + form values into RunningHub-compatible nodeInfoList."""
    values = dict(form_values or {})
    locked = {str(k): str(v) for k, v in (card.get("engine_config", {}).get("locked_nodes") or {}).items()}
    disabled_loras = {}
    for node in card.get("nodes", ()):
        if node.get("fieldName") != "lora_name":
            continue
        key = f"{node['nodeId']}.{node['fieldName']}"
        val = values.get(key)
        if val is None:
            val = node.get("defaultValue", "")
        if str(val).lower() != "none":
            continue
        fallback = str(node.get("defaultValue", ""))
        if fallback.lower() == "none":
            fallback = next((str(opt) for opt in node.get("options", ()) if str(opt).lower() != "none"), "")
        disabled_loras[str(node["nodeId"])] = fallback

    result = []
    seen_keys = set()
    for node in card.get("nodes", ()):
        node_id = str(node["nodeId"])
        field_name = str(node["fieldName"])
        key = f"{node_id}.{field_name}"
        seen_keys.add(key)
        if key in locked:
            value = locked[key]
        else:
            value = values.get(key)
            if value is None:
                value = node.get("defaultValue", "")
        if node_id in disabled_loras:
            if field_name == "lora_name":
                value = disabled_loras[node_id]
            elif field_name == "strength_model":
                value = "0"
        result.append({
            "nodeId": node_id,
            "fieldName": field_name,
            "fieldValue": str(value),
            "description": None,
        })
    for lock_key, lock_val in locked.items():
        if lock_key not in seen_keys and "." in lock_key:
            nid, fname = lock_key.split(".", 1)
            result.append({
                "nodeId": nid,
                "fieldName": fname,
                "fieldValue": str(lock_val),
                "description": None,
            })
    return result


_PASSTHROUGH_IMAGE_CLASSES = {
    "LayerUtility: ImageScaleByAspectRatio V2",
    "ImageScale",
    "ImageScaleBy",
    "ImageScaleToTotalPixels",
}


_KNOWN_WIDGET_NAMES = {
    "LoadImage": ("image", "upload"),
    "LoadAudio": ("audio", "upload"),
    "CLIPTextEncode": ("text",),
    "JjkText": ("text",),
    "PrimitiveStringMultiline": ("value",),
    "CheckpointLoaderSimple": ("ckpt_name",),
    "UNETLoader": ("unet_name", "weight_dtype"),
    "CLIPLoader": ("clip_name", "type", "device"),
    "VAELoader": ("vae_name",),
    "LoraLoaderModelOnly": ("lora_name", "strength_model"),
    "LoraLoader": ("lora_name", "strength_model", "strength_clip"),
    "KSampler": ("seed", "steps", "cfg", "sampler_name", "scheduler", "denoise"),
    "SaveImage": ("filename_prefix",),
    "SaveLatent": ("filename_prefix",),
    "DuckDecodeNode": ("password", "教学视频合集", "本地编码/解码工具下载", "在线解码工具", "交流群", "text_display"),
}


def convert_litegraph_to_api(data: dict) -> dict:
    """Convert a ComfyUI LiteGraph UI workflow JSON (with SetNode/GetNode/Reroute/mode:4 bypass) into flat API prompt format."""
    if not isinstance(data, dict) or "nodes" not in data or not isinstance(data.get("nodes"), list):
        return data
    nodes_by_id = {str(n["id"]): n for n in data["nodes"] if isinstance(n, dict) and "id" in n}
    links_by_id = {}
    for link in data.get("links") or ():
        if isinstance(link, list) and len(link) >= 5:
            links_by_id[int(link[0])] = (str(link[1]), int(link[2]), str(link[3]), int(link[4]))

    set_sources = {}
    for nid, node in nodes_by_id.items():
        if node.get("type") == "SetNode":
            wv = node.get("widgets_values") or []
            var_name = str(wv[0]).strip() if isinstance(wv, list) and wv else ""
            in_links = [inp.get("link") for inp in (node.get("inputs") or ()) if inp.get("link") is not None]
            if var_name and in_links and int(in_links[0]) in links_by_id:
                orig_id, orig_slot, _, _ = links_by_id[int(in_links[0])]
                set_sources[var_name] = (orig_id, orig_slot)

    def resolve_source(orig_id: str, orig_slot: int, seen: set[str] | None = None) -> tuple[str, int]:
        seen = seen or set()
        if orig_id in seen:
            return (orig_id, orig_slot)
        seen.add(orig_id)
        node = nodes_by_id.get(orig_id)
        if not node:
            return (orig_id, orig_slot)
        ntype = node.get("type")
        if ntype == "GetNode":
            wv = node.get("widgets_values") or []
            var_name = str(wv[0]).strip() if isinstance(wv, list) and wv else ""
            if var_name in set_sources:
                s_id, s_slot = set_sources[var_name]
                return resolve_source(s_id, s_slot, seen)
        elif ntype == "Reroute":
            in_links = [inp.get("link") for inp in (node.get("inputs") or ()) if inp.get("link") is not None]
            if in_links and int(in_links[0]) in links_by_id:
                s_id, s_slot, _, _ = links_by_id[int(in_links[0])]
                return resolve_source(s_id, s_slot, seen)
        elif node.get("mode") == 4:
            # Mode 4 = Bypass in ComfyUI LiteGraph: pass through matching input link
            outputs = node.get("outputs") or []
            out_type = outputs[orig_slot].get("type") if orig_slot < len(outputs) else None
            inps = node.get("inputs") or []
            chosen_link = None
            if orig_slot < len(inps) and inps[orig_slot].get("link") is not None:
                if not out_type or inps[orig_slot].get("type") in (out_type, "*"):
                    chosen_link = inps[orig_slot].get("link")
            if chosen_link is None and out_type:
                for inp in inps:
                    if inp.get("link") is not None and inp.get("type") in (out_type, "*"):
                        chosen_link = inp.get("link")
                        break
            if chosen_link is None:
                for inp in inps:
                    if inp.get("link") is not None:
                        chosen_link = inp.get("link")
                        break
            if chosen_link is not None and int(chosen_link) in links_by_id:
                s_id, s_slot, _, _ = links_by_id[int(chosen_link)]
                return resolve_source(s_id, s_slot, seen)
        return (orig_id, orig_slot)

    control_after_generate = {"fixed", "increment", "decrement", "randomize"}
    ui_only_keys = {"videopreview", "choose video to upload", "upload"}
    api = {}
    for nid, node in nodes_by_id.items():
        ntype = node.get("type")
        if not ntype or ntype in ("SetNode", "GetNode", "Reroute", "Note", "PrimitiveNode"):
            continue
        if node.get("mode") in (2, 4):
            continue
        inputs_out = {}
        wv = node.get("widgets_values")
        if isinstance(wv, dict):
            for k, v in wv.items():
                if k not in ui_only_keys:
                    inputs_out[k] = v
        elif isinstance(wv, list):
            widget_inputs = [
                (inp.get("widget") or {}).get("name") or inp.get("name")
                for inp in (node.get("inputs") or ())
                if inp.get("widget")
            ]
            known = list(_KNOWN_WIDGET_NAMES.get(ntype, ()))
            if len(known) > len(widget_inputs):
                widget_names = known
            else:
                widget_names = widget_inputs
            w_idx = 0
            for w_name in widget_names:
                if w_name in ui_only_keys:
                    if w_idx < len(wv):
                        w_idx += 1
                    continue
                if w_idx < len(wv):
                    val = wv[w_idx]
                    w_idx += 1
                    inputs_out[w_name] = val
                    if w_name in ("seed", "noise_seed") and w_idx < len(wv) and wv[w_idx] in control_after_generate:
                        w_idx += 1
        for inp in node.get("inputs") or ():
            link_id = inp.get("link")
            if link_id is not None and int(link_id) in links_by_id:
                orig_id, orig_slot, _, _ = links_by_id[int(link_id)]
                r_id, r_slot = resolve_source(orig_id, orig_slot)
                inputs_out[inp["name"]] = [str(r_id), int(r_slot)]
        entry = {"class_type": ntype, "inputs": inputs_out}
        if node.get("title"):
            entry["_meta"] = {"title": node["title"]}
        api[str(nid)] = entry
    return api


def _unlink_node_and_dependents(workflow: dict, node_id: str) -> None:
    """Unlink a node from all downstream inputs and cascade-prune orphaned image scale/passthrough nodes."""
    node_id = str(node_id)
    orphaned_passthroughs = []
    for other_id, other in list(workflow.items()):
        if not isinstance(other, dict) or not isinstance(other.get("inputs"), dict):
            continue
        inputs = other["inputs"]
        removed_keys = []
        for in_key, in_val in list(inputs.items()):
            if isinstance(in_val, list) and len(in_val) == 2 and str(in_val[0]) == node_id:
                del inputs[in_key]
                removed_keys.append(in_key)
            elif isinstance(in_val, dict):
                for sub_k, sub_v in list(in_val.items()):
                    if isinstance(sub_v, list) and len(sub_v) == 2 and str(sub_v[0]) == node_id:
                        del in_val[sub_k]
        if "image" in removed_keys and other.get("class_type") in _PASSTHROUGH_IMAGE_CLASSES:
            orphaned_passthroughs.append(str(other_id))
    if node_id in workflow and (
        workflow[node_id].get("class_type") in ("LoadImage", "VHS_LoadVideo", "LoadVideo", "LoadAudio")
        or workflow[node_id].get("class_type") in _PASSTHROUGH_IMAGE_CLASSES
    ):
        still_linked = any(
            isinstance(v, list) and len(v) == 2 and str(v[0]) == node_id
            for n in workflow.values() if isinstance(n, dict)
            for v in (n.get("inputs") or {}).values()
        )
        if not still_linked:
            workflow.pop(node_id, None)
    for orphan_id in orphaned_passthroughs:
        _unlink_node_and_dependents(workflow, orphan_id)


def inject_node_info_into_workflow(workflow: dict, node_info_list: list[dict],
                                   card: dict | None = None, task: dict | None = None,
                                   head=None, client=None) -> dict:
    """Inject a RunningHub nodeInfoList into a ComfyUI API workflow JSON, unlinking 'None' optional media slots."""
    workflow = convert_litegraph_to_api(workflow)
    card_nodes = {(str(n["nodeId"]), str(n["fieldName"])): n for n in (card or {}).get("nodes", ())}
    media_cache, uploaded = {}, {}
    for entry in node_info_list or ():
        node_id = str(entry["nodeId"])
        field_name = str(entry["fieldName"])
        raw_value = entry.get("fieldValue")
        cnode = card_nodes.get((node_id, field_name), {})
        field_type = str(cnode.get("fieldType") or "").upper()
        if not field_type:
            if field_name in ("image", "video", "audio"):
                field_type = field_name.upper()
            elif workflow.get(node_id, {}).get("class_type") in ("LoadImage", "VHS_LoadVideo", "LoadVideo", "LoadAudio"):
                field_type = "VIDEO" if "Video" in workflow[node_id]["class_type"] else "AUDIO" if "Audio" in workflow[node_id]["class_type"] else "IMAGE"
        is_empty_media = field_type in ("IMAGE", "VIDEO", "AUDIO") and (
            raw_value is None or str(raw_value).strip() in ("", "None", "none")
        )
        if is_empty_media:
            if cnode.get("required", False):
                raise runtime.WorkerError(f"Required card media slot {node_id}.{field_name} is missing")
            _unlink_node_and_dependents(workflow, node_id)
            continue
        if node_id not in workflow or not isinstance(workflow[node_id], dict) or not isinstance(workflow[node_id].get("inputs"), dict):
            raise runtime.WorkerError(f"Configured card node {node_id}.{field_name} does not exist in workflow")
        if field_type in ("IMAGE", "VIDEO", "AUDIO"):
            val_str = str(raw_value).strip()
            if head is not None and client is not None and task is not None and context_compiler._media_urls(val_str) == [val_str]:
                if val_str not in media_cache:
                    media_cache[val_str] = head.asset(task, val_str)
                raw_bytes, mime = media_cache[val_str]
                expected_prefix = field_type.lower() + "/"
                if not mime.startswith(expected_prefix):
                    raise runtime.WorkerError(f"Card media slot {node_id}.{field_name} expected {expected_prefix}* but got {mime}")
                if val_str not in uploaded:
                    prefix = "source_video" if field_type == "VIDEO" else "reference"
                    uploaded[val_str] = client.upload_media(raw_bytes, mime, prefix)
                val_str = uploaded[val_str]
            workflow[node_id]["inputs"][field_name] = val_str
        else:
            existing = workflow[node_id]["inputs"].get(field_name)
            if field_type == "INT" or type(existing) is int:
                coerced = int(float(raw_value))
            elif field_type == "FLOAT" or type(existing) is float:
                coerced = float(raw_value)
            elif type(existing) is bool:
                coerced = str(raw_value).strip().lower() in ("true", "1", "yes")
            else:
                coerced = str(raw_value)
            workflow[node_id]["inputs"][field_name] = coerced
    return workflow


def resolve_pass2_source(task: dict, ctx: dict | None = None, card: dict | None = None,
                         config: dict | None = None, head=None) -> dict:
    """Resolve @source Pass 1 video and composite reference image for Pass 2 (h3-optimize) restoration."""
    ctx = ctx or legacy.resolve_studio_context(task)
    config = config or {}
    video_url = ctx.get("output_video") or ctx.get("source_video")
    image_url = (ctx.get("ingredients_sheet") or ctx.get("anchor_keyframe")
                 or next(iter(ctx.get("asset_images") or ()), None) or ctx.get("primary_image_url"))
    if not video_url:
        raise runtime.WorkerError("Pass 2 @source requires a Pass 1 output_video or source_video in the active row")
    if not image_url:
        raise runtime.WorkerError("Pass 2 @source requires a reference image (ingredients_sheet, anchor_keyframe, or @Asset)")
    media = config.get("source_media")
    if media is None and head is not None:
        raw, mime = head.asset(task, video_url)
        if not mime.startswith("video/"):
            raise runtime.WorkerError("Pass 2 @source video asset must have video/* MIME")
        with tempfile.TemporaryDirectory(prefix="zerofield-pass2-") as folder:
            video_path = Path(folder) / "pass1.mp4"
            video_path.write_bytes(raw)
            media = legacy._probe_video(video_path, config)
    ratio_options = [
        "1:1 (Square)", "2:3 (Portrait Photo)", "3:2 (Photo)", "3:4 (Portrait Standard)",
        "4:3 (Standard)", "9:16 (Portrait Widescreen)", "16:9 (Widescreen)", "21:9 (Ultrawide)"
    ]
    if card:
        ratio_node = next((n for n in card.get("nodes", ()) if n.get("fieldName") == "aspect_ratio"), None)
        if ratio_node and ratio_node.get("options"):
            ratio_options = ratio_node["options"]
    duration_str = f"{float(media['duration']):.6f}".rstrip("0").rstrip(".") if media else str(config.get("duration_sec", "5"))
    aspect = context_compiler.aspect_for(media, ratio_options) if media else str(config.get("aspect_ratio", "16:9 (Widescreen)"))
    prompt_default = (
        "4K video restoration and upscale, strictly preserve original composition, subject identity, "
        "facial features, expression, pose, lighting and scene. Remove compression artifacts, noise, "
        "motion blur. Recover fine texture: hair, fabric and skin details. Natural sharp edges, accurate "
        "color correction, stable between frames, no flicker. Do not invent new elements, only enhance image quality."
    )
    if card:
        pnode = next((n for n in card.get("nodes", ()) if n.get("fieldName") == "text"), None)
        if pnode:
            proj = str(config.get("project_style") or "default")
            prompt_default = (pnode.get("projectDefaults") or {}).get(proj, pnode.get("defaultValue", prompt_default))
    values = {
        "27.video": video_url,
        "51.image": image_url,
        "49.image": "None",
        "50.image": "None",
        "43.image": "None",
        "19.image": "None",
        "23.image": "None",
        "259.value": duration_str,
        "252.aspect_ratio": aspect,
        "263.text": prompt_default,
    }
    return {
        "video_url": video_url,
        "image_url": image_url,
        "duration_sec": duration_str,
        "aspect_ratio": aspect,
        "media": media,
        "values": values,
    }


def bind_external_workflow(workflow: dict, ctx: dict, config: dict, task: dict, head, client) -> dict:
    """Bind semantic sources into arbitrary external API graph slots.

    Source-to-slot objects and slot-to-source/literal mappings may be mixed.
    Explicit input_bindings take precedence over legacy settings/param_bindings.
    """
    workflow = convert_litegraph_to_api(workflow)
    ctx = dict(ctx)
    if config.get("prompt_column") is not None or config.get("use_studio_compiler") is False:
        ctx["compiled_prompt"] = context_compiler.prompt_text(task, config)
    if config.get("seed") is not None:
        ctx["seed"] = int(config["seed"])
    bindings = {}
    scoped = context_compiler._shot_media_candidates(task)
    is_h3_v3 = (
        isinstance(workflow.get("26"), dict)
        and workflow["26"].get("class_type") == "MiniMaxH3ReferenceToVideo"
        and isinstance(workflow.get("57"), dict)
        and workflow["57"].get("class_type") == "JjkText"
    )
    def legacy(key, source, default_input, upload=None, candidates=None):
        if config.get(key):
            target = str(config[key]) + "." + config.get(key.removesuffix("_node") + "_input", default_input)
            bindings[target] = {"source": source, **({"upload": upload} if upload else {}),
                                **({"candidates": candidates} if candidates is not None else {}), "label": key}
    if is_h3_v3 and not config.get("input_bindings") and not config.get("param_bindings"):
        prompt_source = "h3_context_ir_prompt" if config.get("use_h3_context_ir", True) else "compiled_prompt"
        p_node = str(config.get("prompt_node") or "57")
        if p_node == "6" and workflow.get("6", {}).get("class_type") == "LoraLoaderModelOnly":
            p_node = "57"
        s_node = str(config.get("seed_node") or "42")
        if s_node == "3" and workflow.get("3", {}).get("class_type") == "VHS_LoadVideo":
            s_node = "42"
        v_node = str(config.get("video_node") or "3")
        img1_node = str(config.get("image_node") or "1")
        img2_node = str(config.get("reference_image_node") or "61")
        bindings[f"{p_node}.text"] = {"source": prompt_source, "label": "prompt_node"}
        bindings[f"{s_node}.seed"] = {"source": "seed", "label": "seed_node"}
        bindings[f"{v_node}.video"] = {"source": "source_video", "upload": "video",
                                       "candidates": [ctx.get("source_video")] + scoped, "label": "video_node"}
        img_candidates = list(dict.fromkeys(
            [u for u in ([ctx.get("ingredients_sheet"), ctx.get("anchor_keyframe")] + list(ctx.get("asset_images") or []) + [ctx.get("primary_image_url")] + scoped) if u]
        ))
        bindings[f"{img1_node}.image"] = {"source": "primary_image_url", "upload": "image",
                                          "candidates": img_candidates, "label": "image_node"}
        if img2_node in workflow:
            second_candidates = list(dict.fromkeys((ctx.get("asset_images") or [])[1:]))
            if second_candidates:
                bindings[f"{img2_node}.image"] = {"source": "asset_images.1", "upload": "image",
                                                  "candidates": second_candidates, "optional": True, "label": "reference_image_node"}
            else:
                _unlink_node_and_dependents(workflow, img2_node)
        if config.get("aspect_ratio") and "4" in workflow and "aspect_ratio" in (workflow["4"].get("inputs") or {}):
            bindings["4.aspect_ratio"] = {"literal": str(config["aspect_ratio"]), "optional": True}
    else:
        legacy("prompt_node", "compiled_prompt", "text")
        legacy("seed_node", "seed", "seed")
        legacy("image_node", "primary_image_url", "image", "image", [ctx.get("primary_image_url")] + scoped + ctx.get("asset_images", []))
        legacy("reference_image_node", "asset_images.0", "image", "image", ctx.get("asset_images", []))
        legacy("video_node", "source_video", "video", "video", [ctx.get("source_video")] + scoped)
        legacy("structure_video_node", "motion_structure_video", "video", "video")
        legacy("first_frame_node", "first_frame", "image", "image")
    for name in ("param_bindings", "input_bindings"):
        mapping = config.get(name, {})
        if not isinstance(mapping, dict):
            raise runtime.WorkerError(f"{name} must be an object")
        for path, spec in mapping.items():
            if isinstance(spec, dict) and "node" in spec and "input" in spec:
                target = str(spec["node"]) + "." + str(spec["input"])
                bindings[target] = dict(spec, source=path)
            else:
                if not isinstance(path, str) or "." not in path:
                    raise runtime.WorkerError("Input binding requires a source-to-slot object or node_id.input_name target")
                if isinstance(spec, dict):
                    bindings[path] = dict(spec)
                elif isinstance(spec, str) and spec.split(".")[0] in ctx:
                    bindings[path] = {"source": spec, "optional": name == "param_bindings"}
                else:
                    bindings[path] = {"literal": spec}
    media_cache, uploaded = {}, {}
    for target, binding in bindings.items():
        node_id, input_name = target.split(".", 1)
        if node_id not in workflow or not isinstance(workflow[node_id], dict) or not isinstance(workflow[node_id].get("inputs"), dict) or not input_name:
            raise runtime.WorkerError("Configured Comfy binding does not exist in the workflow")
        optional = binding.get("optional", False)
        source = binding.get("source")
        value = context_compiler._context_value(ctx, source) if isinstance(source, str) else binding.get("literal", binding.get("value", context_compiler._MISSING))
        if source == "seed" and (value is context_compiler._MISSING or value is None):
            value = int(uuid.uuid4().hex[:12], 16)
        candidates = binding.get("candidates")
        upload = binding.get("upload")
        if upload not in (None, "auto", "image", "video"):
            raise runtime.WorkerError("Input binding upload must be image, video or auto")
        if candidates is not None:
            value = context_compiler._MISSING
            for url in dict.fromkeys(url for url in candidates if url):
                if url not in media_cache:
                    media_cache[url] = head.asset(task, url)
                if media_cache[url][1].startswith(upload + "/"):
                    value = url
                    break
        if value is context_compiler._MISSING or value is None or value == "":
            if optional:
                continue
            label = binding.get("label", source or target)
            if upload:
                raise runtime.WorkerError(f"ComfyUI {label} needs an input {upload} asset")
            raise runtime.WorkerError(f"ComfyUI binding source is missing: {label}")
        asset_url = isinstance(value, str) and context_compiler._media_urls(value) == [value]
        if asset_url or upload:
            if not isinstance(value, str):
                raise runtime.WorkerError("Media binding must reference a project asset URL")
            if value not in media_cache:
                media_cache[value] = head.asset(task, value)
            raw, mime = media_cache[value]
            if not mime.startswith(("image/", "video/")) or upload in ("image", "video") and not mime.startswith(upload + "/"):
                raise runtime.WorkerError("Media binding MIME does not match its configured upload type")
            if value not in uploaded:
                prefix = "source_video" if mime.startswith("video/") else "reference" if source and source.startswith("asset_") else "input"
                uploaded[value] = client.upload_media(raw, mime, prefix)
            value = uploaded[value]
        workflow[node_id]["inputs"][input_name] = value
    return workflow


_SDK_ENV_LOCK = threading.Lock()


def parse_runninghub_curl_or_payload(spec: str | dict | list) -> dict:
    """Parse a RunningHub curl command or OpenAPI v2 JSON payload into {webappId, endpoint_kind, nodeInfoList, instanceType, usePersonalQueue}."""
    webapp_id = ""
    endpoint_kind = "ai-app"
    payload = {}
    if isinstance(spec, list):
        payload = {"nodeInfoList": spec}
    elif isinstance(spec, dict):
        payload = dict(spec)
        webapp_id = str(payload.get("webappId") or payload.get("workflowId") or "").strip()
    elif isinstance(spec, str):
        text = spec.strip()
        url_match = re.search(r"/openapi/v2/run/(ai-app|workflow)/([A-Za-z0-9_-]+)", text)
        if url_match:
            endpoint_kind = url_match.group(1)
            webapp_id = url_match.group(2)
        if text.startswith("{") or text.startswith("["):
            parsed = json.loads(text)
            payload = {"nodeInfoList": parsed} if isinstance(parsed, list) else parsed
        else:
            data_flag = re.search(r"(?:--data-raw|--data-binary|--data|-d)\s+['\"]?(\{)", text)
            start = data_flag.start(1) if data_flag else text.find('{"nodeInfoList"')
            if start < 0:
                start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                payload = json.loads(text[start:end + 1])
            else:
                raise runtime.WorkerError("Could not find JSON payload in RunningHub curl command")
        if not webapp_id:
            webapp_id = str(payload.get("webappId") or payload.get("workflowId") or "").strip()
    else:
        raise runtime.WorkerError("runninghub_spec must be a curl string, JSON dict, or nodeInfoList array")

    raw_list = payload.get("nodeInfoList") or ()
    if not isinstance(raw_list, (list, tuple)) or not raw_list:
        raise runtime.WorkerError("RunningHub payload must contain a non-empty nodeInfoList")
    normalized_list = []
    for idx, item in enumerate(raw_list):
        if not isinstance(item, dict):
            raise runtime.WorkerError(f"nodeInfoList[{idx}] must be an object")
        nid = str(item.get("nodeId") or "").strip()
        fname = str(item.get("fieldName") or "").strip()
        if not nid or not fname:
            raise runtime.WorkerError(f"nodeInfoList[{idx}] requires nodeId and fieldName")
        normalized_list.append({
            "nodeId": nid,
            "fieldName": fname,
            "fieldValue": item.get("fieldValue"),
            "description": item.get("description"),
        })
    return {
        "webappId": webapp_id,
        "endpoint_kind": endpoint_kind,
        "nodeInfoList": normalized_list,
        "instanceType": str(payload.get("instanceType") or "default"),
        "usePersonalQueue": str(payload.get("usePersonalQueue") or "false"),
    }


def extract_studio_card_from_workflow(workflow_or_path: dict | str | Path, *,
                                      card_id: str | None = None,
                                      label: str | None = None,
                                      runninghub_spec: str | dict | list | None = None,
                                      webapp_id: str | None = None) -> dict:
    """Reverse-engineer a self-hosted Studio Card from any RunningHub/ComfyUI workflow JSON and optional curl/nodeInfoList."""
    workflow_path_str = None
    if isinstance(workflow_or_path, (str, Path)):
        p = Path(workflow_or_path)
        workflow_path_str = str(p)
        raw = json.loads(p.read_text(encoding="utf-8-sig"))
        stem = p.stem
    elif isinstance(workflow_or_path, dict):
        raw = copy.deepcopy(workflow_or_path)
        stem = "custom-workflow"
    else:
        raise runtime.WorkerError("Workflow must be a JSON object or file path")
    api = convert_litegraph_to_api(raw)
    if not isinstance(api, dict) or not api:
        raise runtime.WorkerError("Workflow JSON produced no executable ComfyUI API nodes")
    cid = str(card_id or re.sub(r"[^a-zA-Z0-9_-]+", "-", stem).strip("-").lower() or "custom-card")
    title = str(label or stem)
    default_ratios = [
        "1:1 (Square)", "2:3 (Portrait Photo)", "3:2 (Photo)", "3:4 (Portrait Standard)",
        "4:3 (Standard)", "9:16 (Portrait Widescreen)", "16:9 (Widescreen)", "21:9 (Ultrawide)"
    ]
    nodes_out = []
    output_node = None
    output_mode = "image"
    frame_formula = "none"
    ref_img_idx = 0

    def _sort_key(nid: str):
        return (0, int(nid)) if nid.isdigit() else (1, nid)

    for nid in sorted(api, key=_sort_key):
        entry = api[nid]
        if not isinstance(entry, dict):
            continue
        ctype = str(entry.get("class_type") or "")
        inputs = entry.get("inputs") or {}
        if ctype in ("VHS_VideoCombine", "SaveVideo", "SaveAnimatedWEBP", "CreateVideo"):
            output_node = nid
            output_mode = "video"
        elif ctype in ("SaveImage", "PreviewImage") and output_node is None:
            output_node = nid
        if ctype == "MathExpression|pysssss":
            expr = str(inputs.get("expression") or "")
            if "% 17" in expr:
                frame_formula = "17n+5"
            elif "% 8" in expr:
                frame_formula = "8n+1"
        elif ctype in ("MiniMaxH3ReferenceToVideo", "EmptyMiniMaxH3LatentAV", "MiniMaxH3ImageToVideo"):
            frame_formula = "17n+5"
        elif ctype.startswith("LTXV"):
            if frame_formula == "none":
                frame_formula = "8n+1"

    parsed_rh = parse_runninghub_curl_or_payload(runninghub_spec) if runninghub_spec is not None else None
    resolved_webapp_id = str(webapp_id or (parsed_rh or {}).get("webappId") or "").strip()

    if parsed_rh is not None:
        has_prompt = False
        for item in parsed_rh["nodeInfoList"]:
            nid = item["nodeId"]
            fname = item["fieldName"]
            fval = item.get("fieldValue")
            desc = str(item.get("description") or "").strip()
            entry = api.get(nid) or {}
            ctype = str(entry.get("class_type") or "")
            inputs = entry.get("inputs") or {}
            default_val = fval if fval is not None else inputs.get(fname, "")
            if fname == "video" or ctype in ("VHS_LoadVideo", "LoadVideo"):
                nodes_out.append({
                    "nodeId": nid,
                    "fieldName": fname,
                    "fieldType": "VIDEO",
                    "label": desc or f"Source Video ({nid})",
                    "slot": "driving_video",
                    "required": True,
                    "defaultValue": str(default_val if default_val is not None else "None"),
                })
            elif fname == "image" or ctype == "LoadImage":
                ref_img_idx += 1
                nodes_out.append({
                    "nodeId": nid,
                    "fieldName": fname,
                    "fieldType": "IMAGE",
                    "label": desc or f"Reference Image {ref_img_idx} ({nid})",
                    "slot": "ref",
                    "required": ref_img_idx == 1,
                    "defaultValue": str(default_val if default_val is not None else "None"),
                })
            elif fname == "audio" or ctype in ("LoadAudio", "VHS_LoadAudio"):
                nodes_out.append({
                    "nodeId": nid,
                    "fieldName": fname,
                    "fieldType": "AUDIO",
                    "label": desc or f"Reference Audio ({nid})",
                    "required": False,
                    "defaultValue": str(default_val if default_val is not None else "None"),
                })
            elif fname == "aspect_ratio" or (ctype == "ResolutionSelector" and fname == "aspect_ratio"):
                cur_ar = str(default_val or "16:9 (Widescreen)")
                opts = list(default_ratios) if cur_ar in default_ratios else [cur_ar] + default_ratios
                nodes_out.append({
                    "nodeId": nid,
                    "fieldName": fname,
                    "fieldType": "LIST",
                    "label": desc or f"Aspect Ratio ({nid})",
                    "slot": "aspect_ratio",
                    "defaultValue": cur_ar,
                    "options": opts,
                })
            elif isinstance(default_val, int) or fname in ("seed", "noise_seed", "steps", "width", "height"):
                nodes_out.append({
                    "nodeId": nid,
                    "fieldName": fname,
                    "fieldType": "INT",
                    "label": desc or f"{fname} ({nid})",
                    **({"slot": "seed"} if fname in ("seed", "noise_seed") else {}),
                    "defaultValue": str(int(float(default_val or 0))),
                })
            elif isinstance(default_val, float) or fname in ("cfg", "denoise", "strength_model", "megapixels"):
                nodes_out.append({
                    "nodeId": nid,
                    "fieldName": fname,
                    "fieldType": "FLOAT",
                    "label": desc or f"{fname} ({nid})",
                    "defaultValue": str(float(default_val or 0.0)),
                })
            else:
                nodes_out.append({
                    "nodeId": nid,
                    "fieldName": fname,
                    "fieldType": "STRING",
                    "label": desc or f"Prompt ({nid})",
                    **({"slot": "prompt"} if not has_prompt else {}),
                    "required": not has_prompt,
                    "defaultValue": str(default_val or ""),
                })
                has_prompt = True
    else:
        for nid in sorted(api, key=_sort_key):
            entry = api[nid]
            if not isinstance(entry, dict):
                continue
            ctype = str(entry.get("class_type") or "")
            inputs = entry.get("inputs") or {}
            if ctype in ("VHS_LoadVideo", "LoadVideo") and "video" in inputs and not isinstance(inputs.get("video"), list):
                nodes_out.append({
                    "nodeId": nid,
                    "fieldName": "video",
                    "fieldType": "VIDEO",
                    "label": f"Source Video ({nid})",
                    "slot": "driving_video",
                    "required": True,
                    "defaultValue": "None",
                })
            elif ctype == "LoadImage" and "image" in inputs and not isinstance(inputs.get("image"), list):
                ref_img_idx += 1
                nodes_out.append({
                    "nodeId": nid,
                    "fieldName": "image",
                    "fieldType": "IMAGE",
                    "label": f"Reference Image {ref_img_idx} ({nid})",
                    "slot": "ref",
                    "required": ref_img_idx == 1,
                    "defaultValue": "None",
                })
            elif ctype in ("LoadAudio", "VHS_LoadAudio") and "audio" in inputs and not isinstance(inputs.get("audio"), list):
                nodes_out.append({
                    "nodeId": nid,
                    "fieldName": "audio",
                    "fieldType": "AUDIO",
                    "label": f"Reference Audio ({nid})",
                    "required": False,
                    "defaultValue": "None",
                })
            elif ctype in ("JjkText", "PrimitiveStringMultiline", "CLIPTextEncode"):
                for fname in ("text", "value", "prompt"):
                    if fname in inputs and isinstance(inputs[fname], str):
                        has_prompt = any(n.get("slot") == "prompt" for n in nodes_out)
                        nodes_out.append({
                            "nodeId": nid,
                            "fieldName": fname,
                            "fieldType": "STRING",
                            "label": f"Prompt ({nid})",
                            **({"slot": "prompt"} if not has_prompt else {}),
                            "required": not has_prompt,
                            "defaultValue": str(inputs[fname]),
                        })
                        break
            elif ctype == "ResolutionSelector":
                if "aspect_ratio" in inputs and not isinstance(inputs["aspect_ratio"], list):
                    cur_ar = str(inputs["aspect_ratio"])
                    opts = list(default_ratios) if cur_ar in default_ratios else [cur_ar] + default_ratios
                    nodes_out.append({
                        "nodeId": nid,
                        "fieldName": "aspect_ratio",
                        "fieldType": "LIST",
                        "label": f"Aspect Ratio ({nid})",
                        "slot": "aspect_ratio",
                        "defaultValue": cur_ar,
                        "options": opts,
                    })
                if "megapixels" in inputs and not isinstance(inputs["megapixels"], list):
                    nodes_out.append({
                        "nodeId": nid,
                        "fieldName": "megapixels",
                        "fieldType": "FLOAT",
                        "label": f"Megapixels ({nid})",
                        "defaultValue": str(inputs["megapixels"]),
                        "hidden": True,
                    })
            elif ctype in ("LoraLoaderModelOnly", "LoraLoader"):
                if "lora_name" in inputs and not isinstance(inputs["lora_name"], list):
                    cur_lora = str(inputs["lora_name"])
                    opts = [cur_lora, "none"] if cur_lora.lower() != "none" else ["none"]
                    nodes_out.append({
                        "nodeId": nid,
                        "fieldName": "lora_name",
                        "fieldType": "LIST",
                        "label": f"LoRA ({nid})",
                        "defaultValue": cur_lora,
                        "options": opts,
                    })
                if "strength_model" in inputs and not isinstance(inputs["strength_model"], list):
                    nodes_out.append({
                        "nodeId": nid,
                        "fieldName": "strength_model",
                        "fieldType": "FLOAT",
                        "label": f"LoRA Strength ({nid})",
                        "defaultValue": str(inputs["strength_model"]),
                    })
            elif ctype in ("SelfLiftAvatarH3Sampler", "KSampler", "RandomNoise", "SamplerCustomAdvanced"):
                for sfield in ("seed", "noise_seed"):
                    if sfield in inputs and not isinstance(inputs[sfield], list):
                        has_seed = any(n.get("slot") == "seed" for n in nodes_out)
                        nodes_out.append({
                            "nodeId": nid,
                            "fieldName": sfield,
                            "fieldType": "INT",
                            "label": f"Seed ({nid})",
                            **({"slot": "seed"} if not has_seed else {}),
                            "defaultValue": str(int(inputs[sfield])),
                        })
                        break
            elif ctype == "BasicScheduler" and "steps" in inputs and not isinstance(inputs["steps"], list):
                nodes_out.append({
                    "nodeId": nid,
                    "fieldName": "steps",
                    "fieldType": "INT",
                    "label": f"Steps ({nid})",
                    "defaultValue": str(int(inputs["steps"])),
                    "min": 1,
                    "max": 100,
                })

    engine_cfg = {
        "frame_formula": frame_formula,
        "grid_size": 32,
    }
    if resolved_webapp_id:
        engine_cfg["webappId"] = resolved_webapp_id
    if workflow_path_str:
        engine_cfg["workflow"] = workflow_path_str
    if output_node:
        engine_cfg["output_node"] = output_node

    return validate_studio_card({
        "card_id": cid,
        "label": title,
        "sublabel": f"Self-Hosted Local ComfyUI Card ({len(api)} API nodes)",
        "group_label": "Video" if output_mode == "video" else "Image",
        "output_mode": output_mode,
        "engine_key": "comfy-webapp/1",
        "engine_config": engine_cfg,
        "nodes": nodes_out,
    })


def comfy_platform(config):
    explicit=config.get('platform') or os.environ.get('COMFY_PLATFORM')
    return explicit or ('local' if config.get('driver')=='comfy_local' or not os.environ.get('COMFY_API_KEY') else 'comfy_sdk')


class ComfyPlatformClient:
    """Local ComfyUI v1 or official Comfy SDK API v2 execution."""
    def __init__(self, config):
        self.config = config
        self.platform = comfy_platform(config)
        if config.get('driver') == 'comfy_router' or self.platform == "comfy_router" or config.get("router_url") or os.environ.get("COMFY_ROUTER_URL"):
            raise runtime.WorkerError("Comfy Router does not execute workflow graphs; use platform=comfy_sdk and COMFY_BASE_URL")
        if self.platform not in ("local", "comfy_sdk"):
            raise runtime.WorkerError("Comfy platform must be local or comfy_sdk")
        default_base = "https://cloud.comfy.org" if self.platform == "comfy_sdk" else "http://127.0.0.1:8188"
        self.base_url = (config.get("base_url") or os.environ.get("COMFY_BASE_URL") or default_base).rstrip("/")
        self.token = runtime.configured_token(config)
        if config.get('driver')!='comfy_local' or self.platform!='local':
            self.token = self.token or os.environ.get('COMFY_API_KEY') or os.environ.get('COMFY_ROUTER_TOKEN')
        self.sdk = None
        if self.platform == "comfy_sdk":
            try:
                from comfy_sdk import Comfy
            except ImportError:
                raise runtime.WorkerError("Install openbench[comfy] to use the official Comfy SDK") from None
            with _SDK_ENV_LOCK:
                previous = os.environ.get("COMFY_BASE_URL")
                os.environ["COMFY_BASE_URL"] = self.base_url
                try:
                    self.sdk = Comfy(api_key=self.token, timeout=config.get("request_timeout", 60), client_info="zerofield-studio")
                except Exception:
                    raise runtime.WorkerError("Comfy SDK configuration failed; verify deployment and credentials") from None
                finally:
                    if previous is None:
                        os.environ.pop("COMFY_BASE_URL", None)
                    else:
                        os.environ["COMFY_BASE_URL"] = previous

    def upload_media(self, raw, mime, filename_prefix="input"):
        if getattr(self, 'config', {}).get('_lease_lost', lambda:False)():
            raise runtime.WorkerError('Execution authority ended before Comfy outbound work.')
        extensions = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "video/mp4": ".mp4", "video/webm": ".webm"}
        if mime not in extensions or len(raw) > legacy.MAX_MEDIA:
            raise runtime.WorkerError("Unsupported or oversized Comfy input media")
        filename = filename_prefix + "-" + uuid.uuid4().hex + extensions[mime]
        if self.sdk:
            return self.sdk.assets.from_bytes(raw, filename=filename, content_type=mime)
        boundary = "ZeroField" + uuid.uuid4().hex
        data = (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'.encode() + raw + f"\r\n--{boundary}--\r\n".encode())
        result = legacy.json_fetch(self.base_url + "/upload/image", data=data, mime="multipart/form-data; boundary=" + boundary, token=self.token)
        if not result.get("name"):
            raise runtime.WorkerError("ComfyUI upload returned no filename")
        return (result.get("subfolder", "").strip("/") + "/" + result["name"]).lstrip("/")

    def submit_workflow(self, workflow, client_id, metadata=None):
        if getattr(self, 'config', {}).get('_lease_lost', lambda:False)():
            raise runtime.WorkerError('Execution authority ended before Comfy outbound work.')
        if self.sdk:
            return self.sdk.submit(self.sdk.workflows.from_json(workflow), **({"metadata": metadata} if metadata else {})).id
        result = legacy.json_fetch(self.base_url + "/prompt", token=self.token, payload={"prompt": workflow, "client_id": client_id, **({"extra_data": metadata} if metadata else {})})
        if result.get("node_errors") or not result.get("prompt_id"):
            raise runtime.WorkerError("ComfyUI rejected the configured workflow")
        return str(result["prompt_id"])

    def fetch_history(self, prompt_id):
        if getattr(self, 'config', {}).get('_lease_lost', lambda:False)():
            raise runtime.WorkerError('Execution authority ended before Comfy outbound work.')
        if self.sdk:
            job = self.sdk.jobs.get(prompt_id)
            outputs = {}
            if job.status == "succeeded":
                for output in job.outputs:
                    outputs.setdefault(str(output.node_id), {}).setdefault("media", []).append({"sdk_output": output})
            return {prompt_id: {"status": {"status_str": "error" if job.status in ("failed", "cancelled", "canceled") else job.status, "completed": job.status == "succeeded"}, "outputs": outputs}}
        return legacy.json_fetch(self.base_url + "/history/" + urllib.parse.quote(prompt_id, safe=""), token=self.token)

    def download_output(self, item):
        if getattr(self, 'config', {}).get('_lease_lost', lambda:False)():
            raise runtime.WorkerError('Execution authority ended before Comfy outbound work.')
        if "sdk_output" in item:
            output = item["sdk_output"]
            class LimitedBuffer(io.BytesIO):
                def write(self, data):
                    if self.tell() + len(data) > legacy.MAX_MEDIA:
                        raise runtime.WorkerError("Comfy output exceeds 64 MB")
                    return super().write(data)
            with LimitedBuffer() as stream:
                output.to_stream(stream)
                return stream.getvalue(), output.content_type or mimetypes.guess_type(output.name)[0] or "application/octet-stream"
        query = urllib.parse.urlencode({k: item[k] for k in ("filename", "subfolder", "type") if k in item})
        data, mime = legacy.fetch(self.base_url + "/view?" + query, token=self.token)
        return data, mimetypes.guess_type(item["filename"])[0] or mime

    def close(self):
        if self.sdk:
            self.sdk.close()


def _build_card_form_values(card: dict, ctx: dict, config: dict, task: dict, head) -> dict:
    """Populate Studio Card form values from resolved shot context and explicit overrides."""
    values = {}
    proj = str(config.get("project_style") or "default")
    for node in card.get("nodes", ()):
        key = f"{node['nodeId']}.{node['fieldName']}"
        pdefs = node.get("projectDefaults") or {}
        if proj in pdefs:
            values[key] = pdefs[proj]
        elif "default" in pdefs:
            values[key] = pdefs["default"]
        elif "defaultValue" in node:
            values[key] = node["defaultValue"]
    ref_nodes = [n for n in card.get("nodes", ()) if n.get("slot") == "ref" and n.get("fieldType") == "IMAGE"]
    if ref_nodes:
        planned = context_compiler.slot_plan(ctx.get("resolved_assets") or [], len(ref_nodes), limit=legacy.MAX_MATERIALS,
                            excluded_ids=ctx.get("excluded_refs"))
        primary_sheet = ctx.get("ingredients_sheet") or ctx.get("anchor_keyframe")
        if primary_sheet and len(ref_nodes) == 1:
            values[f"{ref_nodes[0]['nodeId']}.{ref_nodes[0]['fieldName']}"] = primary_sheet
        else:
            for idx, rnode in enumerate(ref_nodes):
                rkey = f"{rnode['nodeId']}.{rnode['fieldName']}"
                if idx == 0 and primary_sheet:
                    values[rkey] = primary_sheet
                else:
                    asset = planned[idx] if idx < len(planned) else None
                    url = next(iter((asset or {}).get("reference_urls") or ()), None) if asset else None
                    values[rkey] = url or "None"
    for node in card.get("nodes", ()):
        key = f"{node['nodeId']}.{node['fieldName']}"
        slot = node.get("slot")
        if slot == "driving_video":
            values[key] = ctx.get("source_video") or values.get(key, "None")
        elif slot == "structure_video":
            values[key] = ctx.get("motion_structure_video") or values.get(key, "None")
        elif slot == "prompt":
            is_h3_card = card.get("engine_config", {}).get("frame_formula") == "17n+5"
            use_ir = config.get("use_h3_context_ir", card.get("card_id") != "h3-reference") if is_h3_card else False
            if use_ir:
                values[key] = ctx.get("h3_context_ir_prompt") or ctx.get("compiled_prompt") or values.get(key, "")
            elif card.get("card_id", "").startswith("ltx25") and ctx.get("ingredients_sheet"):
                values[key] = ctx.get("ltx_ingredients_prompt") or ctx.get("compiled_prompt") or values.get(key, "")
            elif ctx.get("compiled_prompt"):
                values[key] = ctx["compiled_prompt"]
        elif slot == "seed" and ctx.get("seed") is not None:
            values[key] = str(ctx["seed"])
        elif slot == "duration" and config.get("duration_sec") is not None:
            values[key] = str(config["duration_sec"])
        elif slot == "aspect_ratio" and config.get("aspect_ratio") is not None:
            values[key] = str(config["aspect_ratio"])
    explicit = config.get("card_values") or {}
    for k, v in explicit.items():
        values[str(k)] = v
    if card.get("card_id") == "h3-optimize" or any(v == "@source" for v in values.values()):
        pass2 = resolve_pass2_source(task, ctx, card=card, config=config, head=head)
        for k, v in pass2["values"].items():
            if k not in explicit or explicit.get(k) == "@source":
                values[k] = v
    return values


def _normalize_comfy_error(result: dict) -> str:
    status = result.get("status") or {}
    raw = json.dumps(status, ensure_ascii=False)
    if re.search(r"OutOfMemoryError|VRAM OOM|CUDA out of memory", raw, re.I):
        return "ComfyUI workflow failed: GPU VRAM out of memory (OOM); reduce duration or resolution"
    if re.search(r"queue limit|并发数", raw, re.I):
        return "ComfyUI workflow rejected: provider concurrent queue limit reached"
    return "ComfyUI workflow execution failed"


def comfyui(task, config, head):
    card = None
    card_spec = config.get("card") or config.get("card_id")
    if card_spec and str(card_spec).lower() != "auto":
        card = validate_studio_card(card_spec) if isinstance(card_spec, dict) else legacy.load_studio_card(card_spec)
    from .model_router import enforce_card_policy
    profile = card_execution_profile(card or {"engine_config": config})
    enforce_card_policy(card or {"engine_config": config}, task.get("production_policy", config.get("production_policy")))
    if profile["driver"] not in ("comfy_local", "comfy_partner"):
        raise runtime.WorkerError("Direct cards must execute through ModelRouter, not ComfyUI")
    workflow_path = config.get("workflow") or (card.get("engine_config", {}).get("workflow") if card else None)
    if not workflow_path:
        raise runtime.WorkerError("ComfyUI execution requires a workflow path or studio card")
    raw_workflow = copy.deepcopy(json.loads(Path(workflow_path).read_text(encoding="utf-8-sig")))
    if card is None and (str(card_spec or "").lower() == "auto" or config.get("auto_card")):
        card = extract_studio_card_from_workflow(raw_workflow, label=Path(workflow_path).stem)
    workflow = convert_litegraph_to_api(raw_workflow)
    ctx = legacy.resolve_studio_context(task)
    config = dict(config, _lease_lost=lambda: getattr(head, 'lease_lost', lambda:False)())
    if callable(getattr(type(head),'outbound_timeout',None)):
        config['timeout'] = head.outbound_timeout(config.get('timeout',1800))
        config['probe_timeout'] = head.outbound_timeout(config.get('probe_timeout',60))
    client = legacy.ComfyPlatformClient(config)
    try:
        if card is not None:
            form_values = _build_card_form_values(card, ctx, config, task, head)
            node_info = build_node_info(card, form_values)
            workflow = inject_node_info_into_workflow(workflow, node_info, card, task, head, client)
            for item in node_info:
                nid, fname = item["nodeId"], item["fieldName"]
                if nid in workflow and fname in (workflow[nid].get("inputs") or {}):
                    item["fieldValue"] = str(workflow[nid]["inputs"][fname])
            client.node_info_list = node_info
            if any(config.get(k) for k in ("input_bindings", "param_bindings", "prompt_node", "seed_node",
                                           "image_node", "reference_image_node", "video_node",
                                           "structure_video_node", "first_frame_node")):
                workflow = bind_external_workflow(workflow, ctx, config, task, head, client)
        else:
            workflow = bind_external_workflow(workflow, ctx, config, task, head, client)
        if profile["driver"] == "comfy_partner":
            head.paid_request_submitted = True
        identifier = client.submit_workflow(workflow, str(task["id"]), config.get("metadata"))
        deadline = time.monotonic() + config.get("timeout", (card.get("engine_config", {}).get("timeout", 1800) if card else 1800))
        output_node = config.get("output_node") or (card.get("engine_config", {}).get("output_node") if card else None)
        if output_node and str(output_node) not in workflow:
            output_node = next(
                (nid for nid, n in workflow.items() if isinstance(n, dict)
                 and n.get("class_type") in ("VHS_VideoCombine", "SaveVideo", "CreateVideo", "SaveImage")),
                None
            )
        while time.monotonic() < deadline:
            if getattr(head, "lease_lost", lambda: False)():
                raise runtime.WorkerError("Lease was lost; stop waiting for ComfyUI")
            result = client.fetch_history(identifier).get(identifier, {})
            if result.get("status", {}).get("status_str") == "error":
                raise runtime.WorkerError(_normalize_comfy_error(result))
            outputs = result.get("outputs", {})
            if output_node:
                outputs = {str(output_node): outputs.get(str(output_node), {})}
            raw_items = [item for output in outputs.values() for key in ("media", "videos", "gifs", "images", "audio")
                         for item in output.get(key, []) if isinstance(item, dict) and ("filename" in item or "sdk_output" in item)]
            def _item_name(item):
                return str(item.get("filename", getattr(item.get("sdk_output"), "name", ""))).lower()
            items = [item for item in raw_items
                     if not _item_name(item).endswith(tuple(s for s in runtime.NON_TAKE_KINDS if s.startswith(".")))
                     and str(item.get("outputType", "")).lower() not in runtime.NON_TAKE_KINDS]
            items.sort(key=lambda item: 0 if _item_name(item).endswith((".mp4", ".webm", ".mov")) else 1)
            if items:
                data, mime = client.download_output(items[0])
                max_sec = config.get("max_duration_sec") or config.get("duration_sec")
                if max_sec is not None and mime == "video/mp4" and config.get("bound_to_source_duration", True):
                    data = legacy.bound_output_video_duration(data, float(max_sec), config)
                asset = head.upload(task, data, mime)
                role = config.get("reference_role") or ("output_video" if task.get("capability") == "video_gen" else None)
                if role:
                    asset = dict(asset, reference_role=role)
                return asset
            if result.get("status", {}).get("completed"):
                raise runtime.WorkerError("ComfyUI completed without a supported saved media output")
            time.sleep(config.get("poll_seconds", 2))
        raise runtime.WorkerError("ComfyUI workflow timed out")
    except runtime.WorkerError as exc:
        if profile["driver"] == "comfy_partner":
            raise runtime.NonRetryableWorkerError(str(exc)) from None
        raise
    except Exception:
        error = runtime.NonRetryableWorkerError if profile["driver"] == "comfy_partner" else runtime.WorkerError
        raise error("Comfy execution failed; verify deployment, workflow nodes and model files") from None
    finally:
        client.close()
