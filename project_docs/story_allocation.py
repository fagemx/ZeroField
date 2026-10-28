"""Authorized Story allocation snapshots and bindings to existing media executors."""
from __future__ import annotations

import copy
import re
import uuid

from project_assistant import limb_worker as worker
from project_docs import repository as repo, story_openapi as story


COMFY_URL = "http://127.0.0.1:8188"


def _combo_names(spec):
    """Choices of one /object_info input spec, in either the list or the COMBO form."""
    if isinstance(spec, list) and spec:
        head = spec[0]
        if isinstance(head, list):
            return [str(n) for n in head]
        if head == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):
            return [str(n) for n in spec[1].get("options", ())]
    return []


def installed_model_gaps(local_comfy_online, *, base_url=COMFY_URL):
    """Card ID -> model files the local ComfyUI does not offer, so the allocator can route around them.

    Asks the running ComfyUI which files each loader node lists (/object_info/<node>),
    the same list its own UI shows. Empty when ComfyUI is offline or cannot be asked:
    an unknown answer never blocks a card.
    """
    if local_comfy_online is not True:
        return {}
    listings, gaps = {}, {}
    try:
        for path in sorted(worker.CARDS_DIR.glob("*.json")):
            try:
                card, graph = worker._resolve_openapi_card_and_workflow(path.stem)
            except worker.WorkerError:
                continue
            if not graph:
                continue
            for class_type in {c for c, _, _ in worker.required_model_files(graph)} - listings.keys():
                info = worker.json_fetch(f"{base_url}/object_info/{class_type}", timeout=2)
                inputs = (info.get(class_type) or {}).get("input") or {} if isinstance(info, dict) else {}
                listings[class_type] = {key: _combo_names(spec) for group in ("required", "optional")
                                        for key, spec in (inputs.get(group) or {}).items()}
            missing = worker.missing_model_files(graph, listings)
            if missing:
                gaps[card["card_id"]] = missing
    except Exception:
        return {}
    return gaps


def options(conn, slug, body, *, local_comfy_online=None):
    policy = story.production_policy(conn, slug)
    if body.get("productionPolicy", policy) != policy:
        story.invalid("Select the project production policy explicitly before planning.")
    if local_comfy_online is None and body.get('appCode'):
        selected=story.resolve_app(body['appCode'],'video',policy)
        if selected['engine_config']['driver']=='comfy_router':
            local_comfy_online=False  # Official model requests never need local graph health.
    online = worker.probe_local_comfy_status()["online"] if local_comfy_online is None else local_comfy_online
    return {"budget_mode": body.get("budgetMode", "hybrid_balanced"), "production_policy": policy,
            "time_pressure": body.get("timePressure", "normal"), "local_comfy_online": online,
            "model_gaps": installed_model_gaps(online)}


def current_shots(conn, ep, ids=None):
    items = story.shots(conn, ep)
    if ids is not None:
        if not isinstance(ids, list) or not ids or len(ids) > 200 or not all(isinstance(i, str) for i in ids) or len(set(ids)) != len(ids) or not set(ids) <= {s["shotId"] for s in items}:
            story.invalid("shotIds must be distinct shots from this episode.")
        items = [s for s in items if s["shotId"] in ids]
    if not 1 <= len(items) <= 200:
        story.invalid("Select between 1 and 200 shots.")
    return items


def source_guard(conn, items):
    from project_docs import writing_impact
    return {s['shotId']: story.digest([story.snapshot(conn, *story.find_row(conn, s['shotId'], 'shot')),
                                      writing_impact.allocation_source_guard(conn, s)]) for s in items}


def public_plan(plan):
    allocations = [{**a, "shotId": a["shot_id"], "complexityTier": a["complexity_tier"],
                    "complexityScore": a["complexity_score"], "assignedCardId": a["assigned_card_id"]} for a in plan["allocations"]]
    return {**plan, "allocations": allocations,
            "summary": {re.sub(r"_([a-z])", lambda m: m[1].upper(), k): v for k, v in plan["summary"].items()}}


def preflight_inputs(conn, slug, identifier, allocation, cards, sources=None, *, card_values=None):
    """Validate real media metadata and typed future outputs, never render/upload.

    Pure allocator readiness covers configuration only. This authorized boundary
    adds executable input readiness; execution still rechecks MIME and ownership.
    """
    row_slug, row = story.find_row(conn, identifier, "shot")
    if row_slug != slug:
        story.invalid("Allocation shot belongs to another production.")
    task = {"input": story.snapshot(conn, slug, row)}
    base = worker.resolve_studio_context(task)
    candidates = worker._shot_media_candidates(task)
    metadata = {}

    def media_type(value):
        if isinstance(value, dict) and value.get("planned_output"):
            return value["content_type"], None
        if isinstance(value, dict):
            value = value.get("asset_url")
        if not isinstance(value, str) or not value or value.lower() in ("none", "@source"):
            return None, "missing_media"
        match = re.fullmatch(r"/projects/api/" + re.escape(slug) + r"/assets/(pa_[0-9a-f]{32})", value)
        if not match:
            return None, "media_not_owned"
        if value not in metadata:
            found = repo.get_asset_meta(conn, slug, match[1])
            if not found:
                metadata[value] = None, "media_missing"
            elif not 0 < found[1] <= worker.MAX_MEDIA:
                metadata[value] = None, "media_size_invalid"
            else:
                metadata[value] = found[0], None
        return metadata[value]

    def branch(plan):
        blockers, outputs, ancestors = [], dict(sources or {}), {}
        for step in plan["stages"]:
            name = step["step_id"]
            dependencies = set(step.get("depends_on", []))
            errors = []
            if name in ancestors or not dependencies <= ancestors.keys():
                errors.append("invalid_dependencies:" + name)
            ancestors[name] = dependencies | {a for dep in dependencies for a in ancestors.get(dep, set())}
            ctx = dict(base)
            for role, binding in step.get("inputs", {}).items():
                source = outputs.get("approved:" + binding["approved_source_id"]) if "approved_source_id" in binding else outputs.get(binding.get("from_step"))
                if source is None or ("from_step" in binding and (binding["from_step"] not in ancestors[name] or source.get("output_role") != binding.get("output_role"))):
                    errors.append("invalid_preparation_binding:" + name + ":" + role)
                else:
                    mime, error = media_type(source)
                    expected = "video/" if role in ("source_video", "motion_structure_video", "output_video") else "image/"
                    if error or not mime.startswith(expected):
                        errors.append((error or "media_type_mismatch") + ":" + name + ":" + role)
                    ctx[role] = source if source.get("planned_output") else source.get("asset_url")
            if step["kind"] == "approval":
                blockers.extend(errors)
                continue  # Existing M8 director gates, not preflight, grant approval.
            if step["kind"] == "prepare":
                config = step["config"]
                mode = config.get("mode")
                procedural = mode in ("motion_structure", "time_strata") and (mode == "time_strata" or config.get("structure_type") in ("layout_silhouette", "sparse_tracks", "time_strata"))
                if mode == "ingredients_sheet":
                    refs = ctx.get("asset_images") or [ctx.get("anchor_keyframe"), ctx.get("first_frame"), *candidates]
                    required_kind, output_kind, role = "image/", "image/png", "ingredients_sheet"
                else:
                    refs = [ctx.get("source_video"), *candidates]
                    required_kind = "video/"
                    output_kind, role = {"motion_structure": ("video/mp4", "motion_structure_video"),
                                         "frame_sheet": ("image/png", "frame_sheet"),
                                         "extract_frame": ("image/png", "first_frame")}.get(mode, ("image/png", "time_strata"))
                    if mode == "motion_structure" and config.get("structure_type") == "time_strata":
                        output_kind, role = "image/png", "time_strata"
                found_kind = False
                for ref in (r for r in refs if r):
                    mime, error = media_type(ref)
                    if error:
                        errors.append(error + ":" + name + ":preparation_source")
                    if mime and mime.startswith(required_kind):
                        found_kind = True
                        if mode != "ingredients_sheet":
                            break
                if not procedural and not found_kind:
                    errors.append("missing_preparation_source:" + name)
                if mode not in ("motion_structure", "time_strata", "frame_sheet", "extract_frame", "ingredients_sheet") or role != step.get("output_role"):
                    errors.append("invalid_preparation_output:" + name)
            else:
                card, _ = cards[step["card_id"]]
                story.authorize_card(conn, slug, card)
                # Match direct-router protection against the legacy image-as-video fallback.
                if not worker.card_execution_profile(card)["requires_comfyui"]:
                    if ctx.get("source_video") and ctx["source_video"] in (ctx.get("anchor_keyframe"), ctx.get("first_frame")):
                        ctx["source_video"] = None
                    if not ctx.get("anchor_keyframe") and ctx.get("first_frame"):
                        ctx["anchor_keyframe"] = ctx["first_frame"]
                try:
                    values = worker._build_card_form_values(card, ctx, dict(card["engine_config"], card_values=card_values or {}), task, None)
                except worker.WorkerError:
                    values = {}
                    errors.append("invalid_card_inputs:" + name)
                locked = card["engine_config"].get("locked_nodes", {})
                for node in card["nodes"]:
                    if node["fieldType"] not in ("IMAGE", "VIDEO", "AUDIO"):
                        continue
                    key = f"{node['nodeId']}.{node['fieldName']}"
                    value = locked.get(key, values.get(key, node.get("defaultValue")))
                    mime, error = media_type(value)
                    if error == "missing_media" and not node.get("required"):
                        continue
                    if error:
                        errors.append(("required_media_missing" if error == "missing_media" else error) + ":" + name + ":" + key)
                    elif not mime.startswith(node["fieldType"].lower() + "/"):
                        errors.append("media_type_mismatch:" + name + ":" + key)
                output_kind, role = card["output_mode"] + "/" + ("mp4" if card["output_mode"] == "video" else "png"), "output_" + card["output_mode"]
                if role != step.get("output_role"):
                    errors.append("invalid_generation_output:" + name)
            blockers.extend(errors)
            if not errors:
                outputs[name] = {"planned_output": True, "content_type": output_kind, "output_role": role}
        return blockers

    blockers = branch(allocation) if not allocation.get("race_plans") else [b for p in allocation["race_plans"] for b in branch(p)]
    # Keep the existing UI blocker list compatible while exposing input-only detail.
    config = [b for b in allocation["configuration_blockers"] if b not in allocation.get("input_blockers", [])]
    allocation["input_blockers"] = list(dict.fromkeys(blockers))
    allocation["configuration_blockers"] = list(dict.fromkeys(config + blockers))
    allocation["readiness_scope"] = "configuration_and_inputs"
    allocation["ready"] = not allocation["configuration_blockers"]
    return allocation


def plan(conn, me, ep, body, *, local_comfy_online=None):
    opts = options(conn, ep["slug"], body, local_comfy_online=local_comfy_online)
    items = current_shots(conn, ep, body.get("shotIds"))
    result = worker.plan_allocation(items, **opts)
    # An explicit card choice is preserved; automatic allocation is opt-in.
    if body.get("appCode"):
        card = story.resolve_app(story.text(body, "appCode"), "video", opts["production_policy"])
        worker.enforce_card_policy(card, opts["production_policy"])
        execution = worker.card_execution_profile(card)
        if opts["budget_mode"] == "lab_economical" and execution["tier"] != "open_weights":
            story.invalid("Lab mode cannot dispatch commercial cards.")
        gap = opts["model_gaps"].get(card["card_id"])
        ready = worker.provider_configuration_status(card)["configured"] and (not execution["requires_comfyui"] or opts["local_comfy_online"]) and not gap
        blockers = [] if ready else ["models_not_installed:%s:%s" % (card["card_id"], ", ".join(gap))] if gap else ["selected_card_unavailable"]
        for a in result["allocations"]:
            a.update(assigned_card_id=card["card_id"], **execution, preparation_steps=[],
                     stages=[{"step_id": "generate", "kind": "generate", "card_id": card["card_id"], "depends_on": [], "inputs": {}, "output_role": "output_video"}],
                     ready=bool(ready), configuration_blockers=list(blockers))
        counts = {tier: sum(a["tier"] == tier for a in result["allocations"]) for tier in ("open_weights", "closed_hero", "cloud_burst")}
        result["summary"].update(open_weights_shot_count=counts["open_weights"], closed_hero_shot_count=counts["closed_hero"], cloud_burst_shot_count=counts["cloud_burst"],
                                  estimated_local_gpu_seconds=None, estimated_cloud_credits=None,
                                  estimated_local_output_seconds=None, estimated_cloud_resource_units=None,
                                  estimate_basis="Explicit card selection; GPU time, credits and resource units are not calibrated.")
        result["ready"] = bool(ready)
    if body.get("engineTier") and any(a["tier"] != body["engineTier"] for a in result["allocations"]):
        story.invalid("engineTier does not match the allocation.")
    cards = {step["card_id"]: copy.deepcopy(worker._resolve_openapi_card_and_workflow(step["card_id"]))
             for a in result["allocations"] for step in a["stages"] if step["kind"] == "generate"}
    for allocation in result["allocations"]:
        preflight_inputs(conn, ep["slug"], allocation["shot_id"], allocation, cards)
    result["ready"] = all(a["ready"] for a in result["allocations"])
    result["readiness_scope"] = "configuration_and_inputs"
    identifier = "al_" + uuid.uuid4().hex
    from project_docs import writing_impact
    saved = {"allocationId": identifier, "episodeId": ep["episodeId"], "slug": ep["slug"], "options": opts,
             "guards": source_guard(conn, items), "plan": result,
             "storyProvenance": {s['shotId']: writing_impact.freeze_for_shot(conn, me, s['shotId']) for s in items},
             "cards": cards}
    story.store(conn, identifier, "allocation", saved, ep["slug"], me.actor_id)
    return {"allocationId": identifier, "productionPolicy": opts["production_policy"], **public_plan(result)}


def apply_batch(conn, me, ep, items, kind, body, actions):
    saved = story.owned(conn, me, story.text(body, "allocationId"), "allocation")
    if kind != "video" or saved["episodeId"] != ep["episodeId"] or saved["slug"] != ep["slug"]:
        story.invalid("Allocation belongs to a different episode or output capability.")
    if saved.get("consumed"):
        raise story.StoryError(409, "DRAMA_OPERATION_NOT_ALLOWED", "This allocation was already dispatched; create a new preflight.")
    if saved["options"]["production_policy"] != story.production_policy(conn, ep["slug"]) or saved["guards"] != source_guard(conn, items):
        raise story.StoryError(409, "DRAMA_STAGE_PRECONDITION", "Allocation sources or policy changed; run preflight again.")
    for allocation in saved["plan"]["allocations"]:
        preflight_inputs(conn, ep["slug"], allocation["shot_id"], allocation, saved["cards"])
    if not saved["plan"]["ready"] or any(not a["ready"] for a in saved["plan"]["allocations"]):
        raise story.StoryError(409, "DRAMA_STAGE_PRECONDITION", "Resolve allocation configuration/media input blockers before dispatch.")
    if any(body.get(k, v) != v for k, v in (("budgetMode", saved["options"]["budget_mode"]), ("productionPolicy", saved["options"]["production_policy"]))):
        story.invalid("Dispatch options must match the reviewed allocation.")
    if body.get("engineTier") and any(a["tier"] != body["engineTier"] for a in saved["plan"]["allocations"]):
        story.invalid("engineTier must match the reviewed allocation.")
    if body.get("appCode"):
        selected = story.resolve_app(body["appCode"], "video", saved["options"]["production_policy"])
        if any(a["assigned_card_id"] != selected["card_id"] for a in saved["plan"]["allocations"]):
            story.invalid("appCode must match the reviewed allocation.")
    from project_assistant import execution_governance as governance
    context = governance.media_context(me, ep['slug'], episode_id=ep['episodeId'], accounting_session_key=saved['allocationId'])
    for allocation in saved['plan']['allocations']:
        for operation in governance.allocation_operations(allocation, saved['allocationId'] + ':' + allocation['shot_id'], saved['cards']):
            if operation['card']['engine_config']['driver'] != 'comfy_router':
                governance.prepare_operation(conn, context, **operation)
    tasks = []
    for allocation in saved["plan"]["allocations"]:
        tasks.append(story.generation(conn, me, allocation["shot_id"], "video",
            {"appCode": allocation["assigned_card_id"], "budgetMode": saved["options"]["budget_mode"], "_allocation": allocation,
             "_frozenCard": saved["cards"][allocation["assigned_card_id"]], "_accountingPrefix": saved["allocationId"] + ":" + allocation["shot_id"]}, actions))
        meta = story.shot_meta(conn, allocation["shot_id"]) | {"allocation": allocation}
        story.store(conn, "meta_" + allocation["shot_id"], "shot_meta", meta, ep["slug"])
    saved["consumed"] = True
    story.store(conn, saved["allocationId"], "allocation", saved)
    return tasks


def bind_inputs(task, inputs, outputs):
    task = copy.deepcopy(task)
    predecessors = task.setdefault("input", {}).setdefault("predecessor_tasks", [])
    for role, binding in inputs.items():
        if "approved_source_id" in binding:
            output = outputs["approved:" + binding["approved_source_id"]]
        else:
            output = outputs[binding["from_step"]]
        predecessors.append({"output": {"asset_url": output["asset_url"], "content_type": output["content_type"], "reference_role": role}})
    return task


def execute_steps(task, steps, head, values=None, outputs=None):
    outputs = {} if outputs is None else outputs
    for step in steps:
        if head.lease_lost():
            raise worker.WorkerError("Media execution was canceled or its lease expired.")
        if step["kind"] == "approval":
            if not step.get("satisfied"):
                raise worker.WorkerError("Director approval is required before continuing.")
            continue
        current = bind_inputs(task, step.get("inputs", {}), outputs)
        if step["kind"] == "prepare":
            def action():
                config = dict(step['config'])
                if callable(getattr(type(head),'outbound_timeout',None)):
                    config['timeout'] = head.outbound_timeout(config.get('timeout',1800))
                    config['probe_timeout'] = head.outbound_timeout(config.get('probe_timeout',60))
                return worker.ffmpeg(current, config, head)
            if hasattr(head, 'accounting_context'):
                from project_assistant import execution_governance as governance
                output = governance.run_operation(head.accounting_context, head.accounting_keys[step['step_id']], action)
            else:
                output = action()
        else:
            if "card" in step:
                card, workflow = step["card"], step["workflow"]
            else:
                card, workflow = worker._resolve_openapi_card_and_workflow(step["card_id"])
            current["workflow"] = workflow
            action = lambda: worker.execute_story_card(current, card, values or {}, head)
            if hasattr(head, 'accounting_context'):
                from project_assistant import execution_governance as governance
                head.accounting_card = card
                head.accounting_destination = governance.media_destination(card)
                output = governance.run_operation(head.accounting_context, head.accounting_keys[step['step_id']], action, card=card)
            else:
                output = action()
        outputs[step["step_id"]] = output
    return output


def approved_source(conn, identifier, source):
    # A selected cell is not itself approval: require the authoritative row status.
    slug, row = story.find_row(conn, identifier, "shot")
    view = story.shot_view(conn, slug, row)
    if view["reviewStatus"] not in ("Approved", "已完成"):
        raise story.StoryError(409, "DRAMA_STAGE_PRECONDITION", "Approve the shot composition/take before handing it to the next engine.")
    for kind in ("video", "image"):
        chosen = next((c for c in story.candidate_list(conn, identifier, kind) if c[kind + "Id"] == source and c["selected"]), None)
        if chosen:
            match = re.fullmatch(r"/projects/api/" + re.escape(slug) + r"/assets/(pa_[0-9a-f]{32})", chosen["url"])
            found = repo.get_asset_meta(conn, slug, match[1]) if match else None
            if found and found[0].startswith(kind + "/"):
                return {"asset_url": chosen["url"], "content_type": found[0]}
    story.invalid("Use the selected, approved candidate from this shot.")


def dispatch(conn, me, method, parts, body, actions):
    if len(parts) == 3 and parts[0] == "projects" and parts[2] == "production-policy":
        p = story.project(conn, parts[1]); slug = p["slug"]
        story.authorize(conn, me, slug, write=method != "GET")
        if method == "PUT":
            from project_assistant import orchestrator
            orchestrator.lock_project(conn, slug)
            if not me.can_edit:
                raise story.StoryError(403, "DRAMA_OPERATION_NOT_ALLOWED", "Only production editors may change commercial-generation policy.")
            value = story.text(body, "productionPolicy")
            effective = worker.effective_production_policy(value)
            if value != effective:
                raise story.StoryError(409, "DRAMA_OPERATION_NOT_ALLOWED", "Deployment policy locks this production to open weights.")
            story.store(conn, "policy_" + slug, "policy", {"productionPolicy": effective}, slug, me.actor_id)
        elif method != "GET":
            story.invalid("Use GET or PUT for production policy.")
        return {"productionPolicy": story.production_policy(conn, slug), "deploymentPolicy": worker.effective_production_policy("hybrid_studio")}
    if len(parts) >= 5 and parts[0] == "projects" and parts[2] == "episodes":
        p = story.project(conn, parts[1]); ep = story.episode(conn, parts[3])
        if ep["slug"] != p["slug"]:
            raise story.StoryError(404, "DRAMA_NOT_FOUND", "Episode does not belong to this production.")
        story.authorize(conn, me, p["slug"], write=method != "GET")
        if method == "POST" and len(parts) == 5 and parts[4] == "shots:plan-allocation":
            return plan(conn, me, ep, body)
        if method == "POST" and len(parts) == 6 and parts[4] == "shots" and parts[5].endswith(":escalate"):
            identifier = parts[5][:-9]
            shot = next((s for s in story.shots(conn, ep) if s["shotId"] == identifier), None)
            if shot is None:
                raise story.StoryError(404, "DRAMA_NOT_FOUND", "Shot does not belong to this episode.")
            opts = options(conn, ep["slug"], body)
            opts.pop("time_pressure")
            sources = {}
            if body.get("chainMode"):
                source = body.get("referenceSourceVideoId") or body.get("referenceSourceImageId")
                if source:
                    sources["approved:" + source] = approved_source(conn, identifier, source)
                allocation = worker.plan_shot_chain(shot, chain_mode=body["chainMode"], approved_source=source, **opts)
            else:
                allocation = worker.escalate_shot_on_retake(shot, strategy=body.get("strategy", "closed_hero"), **opts)
            plans = allocation.get("race_plans") or [allocation]
            cards = {s["card_id"]: worker._resolve_openapi_card_and_workflow(s["card_id"])
                     for p in plans for s in p["stages"] if s["kind"] == "generate"}
            preflight_inputs(conn, ep["slug"], identifier, allocation, cards, sources)
            if not allocation["ready"]:
                raise story.StoryError(409, "DRAMA_STAGE_PRECONDITION", "Resolve strategy configuration/policy/media blockers: " + ", ".join(allocation["configuration_blockers"]))
            from project_assistant import story_media_adapter
            return story_media_adapter.enqueue(conn, me, ep["slug"], identifier, allocation, sources, actions)
    return None
