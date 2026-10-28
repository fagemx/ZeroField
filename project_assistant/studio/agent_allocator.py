"""Deterministic media recommendations, not a scheduler or permission to spend.

All results are plans, never completed media. Supply a trusted availability snapshot
(local_comfy_online from the router's opt-in probe, availability by card ID). No
network, database writes, subprocesses or inference occur here. Configuration is
checked separately from availability; execution must recheck policy and authority.
"""
from __future__ import annotations

import math
import re

from . import card_engine, model_router, runtime

__all__ = ["evaluate_shot_complexity", "select_card_for_shot", "plan_allocation",
           "escalate_shot_on_retake", "plan_shot_chain", "required_model_files", "missing_model_files"]

BUDGET_MODES = ("lab_economical", "hybrid_balanced", "deadline_rush")
_ACTION = re.compile(r"\b(?:fight\w*|clash\w*|embrac\w*|hands?|fingers?|water|explosion\w*|danc\w*|crying|micro[- ]expression\w*)\b|打鬥|打斗|特寫|特写|擁抱|拥抱|手部", re.I)
_CAMERA = re.compile(r"handheld|whip[ -]?pan|orbit|steadicam|tracking|crane|手持|環繞|环绕|甩鏡|跟拍|升降", re.I)
_CAST = re.compile(r"\bCAST-\d+\b", re.I)
_MODEL_FILE = re.compile(r"\.(?:safetensors|sft|ckpt|pt|pth|gguf|bin)$", re.I)
# Open cards tried, in order, when the recommended open card's model files are not installed.
_OPEN_FALLBACKS = ("ltx25-cinema",)
_RETAKE = {"retake", "rejected", "重抽", "重拍", "退回", "拒絕", "拒绝", "不通過", "不通过"}


def _choice(value, choices, name):
    if not isinstance(value, str) or value not in choices:
        raise runtime.WorkerError(f"Invalid {name}")
    return value


def _fields(shot):
    if not isinstance(shot, dict) or any(not isinstance(k, str) for k in shot):
        raise runtime.WorkerError("Shot must be an object, not an unresolved shot ID")
    result = dict(shot)
    if "headers" in shot or "cells" in shot:
        headers, cells = shot.get("headers"), shot.get("cells")
        if not isinstance(headers, list) or not isinstance(cells, list) or not all(isinstance(h, str) for h in headers):
            raise runtime.WorkerError("Shot row requires headers and cells")
        result.update(zip(headers, cells))
    return result


def _status(value):
    return str(value or "").strip().casefold().replace("_", " ")


def required_model_files(workflow):
    """Model files an API-format ComfyUI graph loads, as sorted (class_type, input, file) triples."""
    found = set()
    for node in (workflow.values() if isinstance(workflow, dict) else ()):
        inputs = node.get("inputs") if isinstance(node, dict) else None
        if not isinstance(inputs, dict) or not isinstance(node.get("class_type"), str):
            continue
        for key, value in inputs.items():
            if isinstance(value, str) and _MODEL_FILE.search(value):
                found.add((node["class_type"], str(key), value))
    return sorted(found)


def _model_key(name):
    return str(name).replace("\\", "/").rsplit("/", 1)[-1].casefold()


def missing_model_files(workflow, installed):
    """Files the graph needs that a trusted ComfyUI listing does not offer.

    installed maps class_type -> {input_name: [file names]} as read from /object_info;
    a class that is absent from it counts as missing (custom node not installed).
    None means the listing is unknown, which never blocks. Pure: no network here.
    """
    if installed is None:
        return []
    missing = []
    for class_type, key, value in required_model_files(workflow):
        offered = {_model_key(n) for n in (installed.get(class_type) or {}).get(key) or ()}
        if _model_key(value) not in offered and value not in missing:
            missing.append(value)
    return missing


def _retakes(fields):
    count = fields.get("retake_count", fields.get("retakeCount", 0))
    if type(count) is not int or count < 0:
        raise runtime.WorkerError("retake_count must be a nonnegative integer")
    candidates = fields.get("candidates", fields.get("videos", []))
    if not isinstance(candidates, list) or any(not isinstance(c, dict) for c in candidates):
        raise runtime.WorkerError("Shot candidates must be a list of objects")
    rejected = set()
    for i, item in enumerate(candidates):
        if _status(item.get("kind", item.get("output_mode", "video"))) != "video":
            continue
        if item.get("rejected") is True or _status(item.get("reviewStatus", item.get("status"))) in _RETAKE:
            rejected.add(str(item.get("videoId", item.get("id", i))))
    status = fields.get("review_status", fields.get("reviewStatus", fields.get("status", fields.get("Status", fields.get("狀態")))))
    # Counts, candidate history and current status may describe the same rejection.
    return max(count, len(rejected), int(_status(status) in _RETAKE))


def evaluate_shot_complexity(row_or_shot):
    """Accept a Story shot or {headers,cells} row; wardrobe variants share a cast ID.

    Explicit SPEC_07 retake acceptance wins over the illustrative sum: a retake
    adds 20 each, then floors the score at 65 so hero always means score >= 65.
    """
    fields = _fields(row_or_shot)
    parts = []
    for key, value in fields.items():
        if re.search(r"prompt|description|dialogue|action|camera|optical|rig|assets|cast|motion|動作|運鏡|角色|提示", key, re.I):
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, list):
                parts.extend(v if isinstance(v, str) else str(v.get("assetCode", "")) for v in value if isinstance(v, (str, dict)))
    text = " ".join(parts)
    actors = sorted(set(m.upper() for m in _CAST.findall(text)))
    score = 10 if not actors else 30 if len(actors) == 1 else 55
    reasons = ["empty_set_or_b_roll" if not actors else "single_character" if len(actors) == 1 else "multi_character_interaction (" + ", ".join("@" + a for a in actors) + ")"]
    action = _ACTION.search(text)
    if action:
        score += 25
        reasons.append("complex_motion_keywords")
    dynamic = bool(_CAMERA.search(text))
    score += 15 if dynamic else 5
    reasons.append("dynamic_camera_rig" if dynamic else "static_or_slow_camera")
    retakes = _retakes(fields)
    if retakes:
        score += 20 * retakes
        reasons.append(f"retake_history ({retakes})")
        if score < 65:
            score = 65
            reasons.append("retake_hero_floor (65)")
    score = min(score, 100)
    tier = "b_roll" if score < 35 else "standard" if score < 65 else "hero"
    return {"complexity_score": score, "complexity_tier": tier, "reasons": reasons,
            "cast_count": len(actors), "retake_count": retakes,
            "recommended_open_card": "ltx25-cinema" if tier == "b_roll" else "h3-short-video-v3",
            "recommended_closed_card": "seedance-20-pro"}


def _options(budget_mode, production_policy, time_pressure, local_comfy_online, availability, model_gaps=None):
    _choice(budget_mode, BUDGET_MODES, "budget_mode")
    _choice(time_pressure, ("low", "normal", "high"), "time_pressure")
    policy = model_router.effective_production_policy(production_policy)
    if local_comfy_online is not None and type(local_comfy_online) is not bool:
        raise runtime.WorkerError("local_comfy_online must be boolean or None")
    if availability is not None and (not isinstance(availability, dict) or any(not isinstance(k, str) or type(v) is not bool for k, v in availability.items())):
        raise runtime.WorkerError("availability must map card IDs to booleans")
    if model_gaps is not None and (not isinstance(model_gaps, dict) or any(
            not isinstance(k, str) or not isinstance(v, (list, tuple)) or not all(isinstance(f, str) for f in v)
            for k, v in model_gaps.items())):
        raise runtime.WorkerError("model_gaps must map card IDs to lists of missing model files")
    return policy


def _card_state(card_id, policy, local_comfy_online, availability, model_gaps=None):
    card = card_engine.load_studio_card(card_id)
    model_router.enforce_card_policy(card, policy)
    profile = card_engine.card_execution_profile(card)
    blockers = []
    if not model_router.provider_configuration_status(card)["configured"]:
        blockers.append("provider_not_configured")
    if profile["requires_comfyui"]:
        if local_comfy_online is not True:
            blockers.append("local_comfy_offline" if local_comfy_online is False else "local_comfy_availability_unknown")
    if (availability or {}).get(card["card_id"]) is False:
        blockers.append("card_unavailable")
    missing = (model_gaps or {}).get(card["card_id"])
    if missing:
        # code:card:files, the shape the Story UI turns into a readable sentence.
        blockers.append(f"models_not_installed:{card['card_id']}:" + ", ".join(missing))
    return card, profile, blockers


def _pick(card_ids, policy, local_comfy_online, availability, model_gaps=None):
    first = None
    for card_id in dict.fromkeys(card_ids):
        state = _card_state(card_id, policy, local_comfy_online, availability, model_gaps)
        if first is None:
            first = state
        if not state[2]:
            return state
    return first


def _pick_open(open_id, policy, local_comfy_online, availability, model_gaps):
    """The recommended open card, or the best installed one when its models are missing."""
    state = _card_state(open_id, policy, local_comfy_online, availability, model_gaps)
    if not any(b.startswith("models_not_installed") for b in state[2]):
        return state
    for card_id in _OPEN_FALLBACKS:
        if card_id != open_id:
            fallback = _card_state(card_id, policy, local_comfy_online, availability, model_gaps)
            if not fallback[2]:
                return fallback
    return state


def _structure():
    return [{"step_id": "structure", "kind": "prepare", "adapter": "ffmpeg",
             "config": {"mode": "motion_structure", "structure_type": "layout_silhouette"},
             "depends_on": [], "output_role": "motion_structure_video"},
            {"step_id": "frame_sheet", "kind": "prepare", "adapter": "ffmpeg",
             "config": {"mode": "frame_sheet"}, "depends_on": ["structure"],
             "inputs": {"source_video": {"from_step": "structure", "output_role": "motion_structure_video"}},
             "output_role": "frame_sheet"}]


def _assignment(shot, state, profile, reasons, policy, preparation_steps=None):
    card, execution, blockers = state
    prep = preparation_steps or []
    stage = {"step_id": "generate", "kind": "generate", "card_id": card["card_id"],
             **execution, "depends_on": [s["step_id"] for s in prep], "inputs": {},
             "output_role": "output_video", "configuration_blockers": list(blockers)}
    if prep:
        slot = "motion_structure_video" if any(n.get("slot") == "structure_video" for n in card["nodes"]) else "source_video"
        stage["inputs"][slot] = {"from_step": "structure", "output_role": "motion_structure_video"}
        stage["inputs"]["frame_sheet"] = {"from_step": "frame_sheet", "output_role": "frame_sheet"}
    fields = _fields(shot)
    return {**profile, "shot_id": fields.get("shotId", fields.get("shot_id", fields.get("rid", fields.get("rowId")))),
            "assigned_card_id": card["card_id"], **execution, "production_policy": policy,
            "reasons": list(profile["reasons"]) + reasons, "status": "planned",
            "readiness_scope": "configuration_and_availability", "ready": not blockers, "configuration_blockers": list(blockers),
            "preparation_steps": prep, "stages": prep + [stage], "handoffs": [],
            "requires_user_confirmation": True}


def select_card_for_shot(shot, *, budget_mode="hybrid_balanced", production_policy=None,
                         time_pressure="normal", local_comfy_online=None, availability=None,
                         b_roll_index=0, remote_index=0, model_gaps=None):
    """Select one plan; use plan_allocation for the deadline batch's local cap.

    None policy means contest-safe router default. Hybrid must be an authorized
    project choice. Unavailable remote recommendations may use their catalogued
    open fallback, never escalate an economical/contest request to paid media.
    model_gaps (card ID -> model files not installed) is a trusted snapshot like
    availability: a card with gaps is never the recommendation while an installed
    open card can do the shot, and otherwise stays listed with a readable blocker.
    """
    policy = _options(budget_mode, production_policy, time_pressure, local_comfy_online, availability, model_gaps)
    if any(type(n) is not int or n < 0 for n in (b_roll_index, remote_index)):
        raise runtime.WorkerError("Allocation indices must be nonnegative integers")
    profile = evaluate_shot_complexity(shot)
    tier, open_id = profile["complexity_tier"], profile["recommended_open_card"]
    reasons = ["budget_mode:" + budget_mode]
    prep = []
    if policy == "open_weights_only" or budget_mode == "lab_economical":
        reasons.append("contest_open_weights_override" if policy == "open_weights_only" else "economical_local_only")
        state = _pick_open(open_id, policy, local_comfy_online, availability, model_gaps)
        if tier == "hero":
            prep = _structure()
    elif budget_mode == "deadline_rush":
        if tier == "b_roll" and b_roll_index < 2 and local_comfy_online is True and (availability or {}).get(open_id, True) and not (model_gaps or {}).get(open_id):
            state = _card_state(open_id, policy, local_comfy_online, availability, model_gaps)
            reasons.append("deadline_first_two_local_b_roll")
        else:
            remote = ["seedance-20-pro", "kling-v2-master", "rh-cloud-h3-burst"]
            offset = remote_index % len(remote)
            state = _pick(remote[offset:] + remote[:offset], policy, local_comfy_online, availability, model_gaps)
            reasons.append("deadline_remote_distribution")
    elif tier == "hero" or (tier == "standard" and time_pressure == "high") or local_comfy_online is False:
        state = _pick([profile["recommended_closed_card"], "kling-v2-master"], policy, local_comfy_online, availability, model_gaps)
        reasons.append("hero_or_time_pressure" if local_comfy_online is not False else "local_offline_remote_route")
        if state[2] and local_comfy_online is not False:
            fallback = state[0]["engine_config"].get("fallback_open_card_id")
            if fallback:
                fallback_state = _pick_open(fallback, "open_weights_only", local_comfy_online, availability, model_gaps)
                if not fallback_state[2]:
                    state = fallback_state
                    reasons.append("configured_open_fallback")
                    if tier == "hero":
                        prep = _structure()
    else:
        state = _pick_open(open_id, policy, local_comfy_online, availability, model_gaps)
        reasons.append("local_draft_or_b_roll")
        if state[2]:
            remote = _pick([profile["recommended_closed_card"], "kling-v2-master"], policy, local_comfy_online, availability, model_gaps)
            if not remote[2]:
                state = remote
                reasons.append("local_unavailable_remote_route")
    if state[0]["card_id"] != (open_id if state[1]["tier"] == "open_weights" else profile["recommended_closed_card"]):
        reasons.append("available_alternative:" + state[0]["card_id"])
    return _assignment(shot, state, profile, reasons, policy, prep)


def _duration(shot):
    value = shot.get("durationSeconds", shot.get("duration_seconds", 5))
    if isinstance(value, bool):
        raise runtime.WorkerError("Shot duration must be positive and finite")
    try:
        value = float(value)
    except (ValueError, TypeError):
        raise runtime.WorkerError("Shot duration must be positive and finite") from None
    if not math.isfinite(value) or value <= 0:
        raise runtime.WorkerError("Shot duration must be positive and finite")
    return value


def plan_allocation(shots, **options):
    """Ordered batch plan with at most two local b-roll slots in hybrid deadline.

    Resource units = output seconds * catalog cost_weight (default 1), NOT billed
    credits or measured GPU seconds. Missing duration assumes five output seconds.
    Blocked assignments remain visible and included in planned resource estimates.
    """
    if not isinstance(shots, list):
        raise runtime.WorkerError("shots must be a list")
    if set(options) - {"budget_mode", "production_policy", "time_pressure", "local_comfy_online", "availability", "model_gaps"}:
        raise runtime.WorkerError("Unknown allocation option")
    _options(options.get("budget_mode", "hybrid_balanced"), options.get("production_policy"),
             options.get("time_pressure", "normal"), options.get("local_comfy_online"), options.get("availability"),
             options.get("model_gaps"))
    allocations, b_roll_index, remote_index = [], 0, 0
    counts = {"open_weights": 0, "closed_hero": 0, "cloud_burst": 0, "closed_hybrid": 0}
    local_seconds, remote_units = 0.0, 0.0
    for shot in shots:
        duration = _duration(_fields(shot))
        item = select_card_for_shot(shot, b_roll_index=b_roll_index, remote_index=remote_index, **options)
        b_roll_index += int(item["complexity_tier"] == "b_roll")
        remote_index += int(not item["requires_comfyui"])
        counts[item["tier"]] += 1
        if item["requires_comfyui"]:
            local_seconds += duration
        else:
            card = card_engine.load_studio_card(item["assigned_card_id"])
            weight = card["engine_config"].get("cost_weight", 1)
            if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(weight) or weight < 0:
                raise runtime.WorkerError("Card cost_weight must be nonnegative and finite")
            remote_units += duration * weight
        allocations.append(item)
    return {"status": "planned", "readiness_scope": "configuration_and_availability",
            "ready": all(a["ready"] for a in allocations), "allocations": allocations,
            "summary": {"open_weights_shot_count": counts["open_weights"],
                        "closed_hero_shot_count": counts["closed_hero"], "cloud_burst_shot_count": counts["cloud_burst"],
                        "estimated_local_output_seconds": local_seconds, "estimated_cloud_resource_units": remote_units,
                        "estimated_local_gpu_seconds": None if local_seconds else 0,
                        "estimated_cloud_credits": None if remote_units else 0,
                        "estimate_basis": "Planned output seconds * catalog cost_weight; default duration 5s. GPU time and billed credits are uncalibrated; preparation overhead excluded."}}


def _forced_plan(shot, card_ids, policy, local_comfy_online, availability, reason, structural=False, model_gaps=None):
    state = _pick(card_ids, policy, local_comfy_online, availability, model_gaps)
    return _assignment(shot, state, evaluate_shot_complexity(shot), [reason], policy, _structure() if structural else None)


def plan_shot_chain(shot, *, chain_mode, production_policy=None, budget_mode="hybrid_balanced",
                    local_comfy_online=None, availability=None, approved_source=None, model_gaps=None):
    """Plan two stages with a director approval barrier, or optimize an approved ID.

    approved_source is an opaque authorized candidate/asset ID, NOT a URL. Caller
    must resolve its project ownership and approval before dispatch. Never pass
    signed URLs; future step outputs use symbolic from_step bindings, not media.
    """
    _choice(chain_mode, ("open_previz_to_closed_hero", "closed_hero_to_open_4k_optimize"), "chain_mode")
    policy = _options(budget_mode, production_policy, "normal", local_comfy_online, availability, model_gaps)
    if approved_source is not None and (not isinstance(approved_source, str) or not re.fullmatch(r"(?:vd_|im_|pa_)[A-Za-z0-9_-]{1,200}", approved_source)):
        raise runtime.WorkerError("approved_source must be an authorized opaque media ID")
    if chain_mode == "closed_hero_to_open_4k_optimize" and approved_source and not approved_source.startswith(("vd_", "pa_")):
        raise runtime.WorkerError("4K optimize requires an approved video source")
    if policy == "open_weights_only" or budget_mode == "lab_economical":
        result = select_card_for_shot(shot, budget_mode=budget_mode, production_policy=policy,
                                      local_comfy_online=local_comfy_online, availability=availability, model_gaps=model_gaps)
        result["ready"] = False
        result["configuration_blockers"].append("chain_requires_hybrid_paid_permission")
        result["chain_mode"] = chain_mode
        return result
    if chain_mode == "open_previz_to_closed_hero":
        first = _forced_plan(shot, ["ltx25-cinema"], policy, local_comfy_online, availability, "open_previz", structural=True, model_gaps=model_gaps)
        second = _forced_plan(shot, ["seedance-20-pro", "kling-v2-master"], policy, local_comfy_online, availability, "closed_final", model_gaps=model_gaps)
        binding, gate = "anchor_keyframe", "composition_approved"
    else:
        first = _forced_plan(shot, ["seedance-20-pro", "kling-v2-master"], policy, local_comfy_online, availability, "closed_acting", model_gaps=model_gaps)
        second = _forced_plan(shot, ["h3-optimize"], policy, local_comfy_online, availability, "open_4k_optimize", model_gaps=model_gaps)
        binding, gate = "source_video", "take_approved"
    result = dict(second, chain_mode=chain_mode)
    first_steps = first["stages"] if approved_source is None else []
    if first_steps:
        first_steps[-1] = dict(first_steps[-1], step_id="draft" if binding == "anchor_keyframe" else "hero")
    source = {"approved_source_id": approved_source} if approved_source else {"from_step": first_steps[-1]["step_id"], "output_role": "output_video"}
    prep = []
    if binding == "anchor_keyframe":
        if approved_source and approved_source.startswith("im_"):
            target = source
        else:
            prep = [{"step_id": "approved_keyframe", "kind": "prepare", "adapter": "ffmpeg", "config": {"mode": "extract_frame"},
                     "depends_on": ["approval"], "inputs": {"source_video": source}, "output_role": "first_frame"}]
            target = {"from_step": "approved_keyframe", "output_role": "first_frame"}
    else:
        target = source
        prep = [{"step_id": "ingredients", "kind": "prepare", "adapter": "ffmpeg", "config": {"mode": "ingredients_sheet"},
                 "depends_on": ["approval"], "output_role": "ingredients_sheet"}]
    final = dict(second["stages"][-1], depends_on=[p["step_id"] for p in prep] or ["approval"], inputs={binding: target})
    if binding == "source_video":
        final["inputs"]["ingredients_sheet"] = {"from_step": "ingredients", "output_role": "ingredients_sheet"}
    approval = {"step_id": "approval", "kind": "approval", "condition": gate,
                "depends_on": [first_steps[-1]["step_id"]] if first_steps else [], "satisfied": approved_source is not None}
    result.update(stages=first_steps + [approval] + prep + [final],
                  preparation_steps=first["preparation_steps"] + prep if first_steps else prep,
                  handoffs=[{"token": "@source" if binding == "source_video" else "approved_keyframe",
                             "source": source, "target_step": "generate", "target_input": binding, "requires_approval": True}],
                  configuration_blockers=list(dict.fromkeys((first["configuration_blockers"] if first_steps else []) + second["configuration_blockers"])),
                  reasons=first["reasons"] + second["reasons"] + ["director_approval_required"])
    result["ready"] = not result["configuration_blockers"]
    return result


def escalate_shot_on_retake(shot, *, strategy="closed_hero", production_policy=None,
                            budget_mode="hybrid_balanced", local_comfy_online=None, availability=None, model_gaps=None):
    """Return a resolved shot's escalation plan; never look up an ID or enqueue.

    A/B is all-or-nothing preflight, not two independent fallback submissions.
    Explicit closed strategies are blocked, not silently replaced, under lab or
    contest restrictions. open_structural_lock is always a permitted alternative.
    """
    _choice(strategy, ("closed_hero", "open_structural_lock", "ab_race", "closed_to_open_4k"), "strategy")
    fields = _fields(shot)
    fields["retake_count"] = max(1, _retakes(fields))
    policy = _options(budget_mode, production_policy, "normal", local_comfy_online, availability, model_gaps)
    if strategy == "closed_to_open_4k":
        return plan_shot_chain(fields, chain_mode="closed_hero_to_open_4k_optimize", production_policy=policy,
                               budget_mode=budget_mode, local_comfy_online=local_comfy_online, availability=availability,
                               model_gaps=model_gaps)
    if strategy == "open_structural_lock" or policy == "open_weights_only" or budget_mode == "lab_economical":
        result = _forced_plan(fields, ["h3-reference", "ltx25-openjutsu"], policy, local_comfy_online, availability, "open_structural_lock", structural=True, model_gaps=model_gaps)
        if strategy != "open_structural_lock":
            result["configuration_blockers"].append("strategy_requires_hybrid_paid_permission")
            result["ready"] = False
    else:
        result = _forced_plan(fields, ["seedance-20-pro", "kling-v2-master"], policy, local_comfy_online, availability, "retake_closed_hero", model_gaps=model_gaps)
        if strategy == "ab_race":
            open_plan = _forced_plan(fields, ["h3-reference", "ltx25-openjutsu"], policy, local_comfy_online, availability, "open_race_candidate", structural=True, model_gaps=model_gaps)
            result["race_plans"] = [open_plan, dict(result)]
            result["configuration_blockers"] = list(dict.fromkeys(open_plan["configuration_blockers"] + result["configuration_blockers"]))
            result["ready"] = not result["configuration_blockers"]
            result["reasons"].append("blind_ab_director_selection")
    result["strategy"] = strategy
    return result
