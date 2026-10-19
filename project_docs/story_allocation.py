"""Authorized Story allocation snapshots and bindings to existing media executors."""
from __future__ import annotations

import copy
import re
import uuid

from project_assistant import limb_worker as worker
from project_docs import repository as repo, story_openapi as story


def options(conn, slug, body):
    policy = story.production_policy(conn, slug)
    if body.get("productionPolicy", policy) != policy:
        story.invalid("Select the project production policy explicitly before planning.")
    return {"budget_mode": body.get("budgetMode", "hybrid_balanced"), "production_policy": policy,
            "time_pressure": body.get("timePressure", "normal"),
            "local_comfy_online": worker.probe_local_comfy_status()["online"]}


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
    return {s["shotId"]: story.digest(story.snapshot(conn, *story.find_row(conn, s["shotId"], "shot"))) for s in items}


def public_plan(plan):
    allocations = [{**a, "shotId": a["shot_id"], "complexityTier": a["complexity_tier"],
                    "complexityScore": a["complexity_score"], "assignedCardId": a["assigned_card_id"]} for a in plan["allocations"]]
    return {**plan, "allocations": allocations,
            "summary": {re.sub(r"_([a-z])", lambda m: m[1].upper(), k): v for k, v in plan["summary"].items()}}


def plan(conn, me, ep, body):
    opts = options(conn, ep["slug"], body)
    items = current_shots(conn, ep, body.get("shotIds"))
    result = worker.plan_allocation(items, **opts)
    # An explicit card choice is preserved; automatic allocation is opt-in.
    if body.get("appCode"):
        card = story.resolve_app(story.text(body, "appCode"), "video", opts["production_policy"])
        worker.enforce_card_policy(card, opts["production_policy"])
        execution = worker.card_execution_profile(card)
        if opts["budget_mode"] == "lab_economical" and execution["tier"] != "open_weights":
            story.invalid("Lab mode cannot dispatch commercial cards.")
        ready = worker.provider_configuration_status(card)["configured"] and (not execution["requires_comfyui"] or opts["local_comfy_online"])
        for a in result["allocations"]:
            a.update(assigned_card_id=card["card_id"], **execution, preparation_steps=[],
                     stages=[{"step_id": "generate", "kind": "generate", "card_id": card["card_id"], "depends_on": [], "inputs": {}, "output_role": "output_video"}],
                     ready=bool(ready), configuration_blockers=[] if ready else ["selected_card_unavailable"])
        counts = {tier: sum(a["tier"] == tier for a in result["allocations"]) for tier in ("open_weights", "closed_hero", "cloud_burst")}
        result["summary"].update(open_weights_shot_count=counts["open_weights"], closed_hero_shot_count=counts["closed_hero"], cloud_burst_shot_count=counts["cloud_burst"],
                                  estimated_local_gpu_seconds=None, estimated_cloud_credits=None,
                                  estimated_local_output_seconds=None, estimated_cloud_resource_units=None,
                                  estimate_basis="Explicit card selection; GPU time, credits and resource units are not calibrated.")
        result["ready"] = bool(ready)
    if body.get("engineTier") and any(a["tier"] != body["engineTier"] for a in result["allocations"]):
        story.invalid("engineTier does not match the allocation.")
    for allocation in result["allocations"]:
        story.authorize_card(conn, ep["slug"], worker._resolve_openapi_card_and_workflow(allocation["assigned_card_id"])[0])
    identifier = "al_" + uuid.uuid4().hex
    saved = {"allocationId": identifier, "episodeId": ep["episodeId"], "slug": ep["slug"], "options": opts,
             "guards": source_guard(conn, items), "plan": result,
             "cards": {a["assigned_card_id"]: copy.deepcopy(worker._resolve_openapi_card_and_workflow(a["assigned_card_id"])) for a in result["allocations"]}}
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
    if not saved["plan"]["ready"]:
        raise story.StoryError(409, "DRAMA_STAGE_PRECONDITION", "Resolve allocation configuration blockers before dispatch.")
    if any(body.get(k, v) != v for k, v in (("budgetMode", saved["options"]["budget_mode"]), ("productionPolicy", saved["options"]["production_policy"]))):
        story.invalid("Dispatch options must match the reviewed allocation.")
    if body.get("engineTier") and any(a["tier"] != body["engineTier"] for a in saved["plan"]["allocations"]):
        story.invalid("engineTier must match the reviewed allocation.")
    if body.get("appCode"):
        selected = story.resolve_app(body["appCode"], "video", saved["options"]["production_policy"])
        if any(a["assigned_card_id"] != selected["card_id"] for a in saved["plan"]["allocations"]):
            story.invalid("appCode must match the reviewed allocation.")
    tasks = []
    for allocation in saved["plan"]["allocations"]:
        tasks.append(story.generation(conn, me, allocation["shot_id"], "video",
            {"appCode": allocation["assigned_card_id"], "budgetMode": saved["options"]["budget_mode"], "_allocation": allocation,
             "_frozenCard": saved["cards"][allocation["assigned_card_id"]]}, actions))
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
            output = worker.ffmpeg(current, step["config"], head)
        else:
            if "card" in step:
                card, workflow = step["card"], step["workflow"]
            else:
                card, workflow = worker._resolve_openapi_card_and_workflow(step["card_id"])
            current["workflow"] = workflow
            output = worker.execute_story_card(current, card, values or {}, head)
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
            if not allocation["ready"]:
                raise story.StoryError(409, "DRAMA_STAGE_PRECONDITION", "Resolve strategy configuration/policy blockers: " + ", ".join(allocation["configuration_blockers"]))
            from project_assistant import story_media_adapter
            return story_media_adapter.enqueue(conn, me, ep["slug"], identifier, allocation, sources, actions)
    return None
