"""In-process media adapter for M8; no new run, race or selection authority.

Reserved profiles are computed, never administrator-editable or remote-worker
bindings. Only this module's object principal may claim their existing M8 leases.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import threading
import time
import uuid
from types import SimpleNamespace

from project_assistant import orchestrator as cp, orchestration_store as db
from project_assistant import limb_worker as worker
from project_docs import repository as repo, service, story_openapi as story, story_allocation
from project_docs.doc_schema import column_ids

_PRINCIPAL = object()
KEYS = ("studio:prepare", "studio:open", "studio:closed")
_ACTIVE = set()
_LOCK = threading.Lock()


def is_principal(identity):
    return identity is _PRINCIPAL


def profile(key):
    if key not in KEYS:
        raise cp.OrchestrationError(403, "Unknown internal media profile.")
    return {"agent_key": key, "display_name": "Studio media " + key.split(":")[1], "icon": "◈",
            "enabled": True, "role_kind": "worker", "runtime_kind": "server_media", "capabilities": ["video_gen"],
            "allowed_tools": ["propose_table_edit"], "provider_config": {}, "system_prompt": "", "knowledge_pack": "", "max_concurrency": 2}


def verify_task(conn, task):
    cp.lock_project(conn, task["project_slug"])
    job = task["input_snapshot"].get("story_media")
    if not job or task["target_agent_key"] not in KEYS or job.get("slug") != task["project_slug"]:
        raise cp.OrchestrationError(403, "Invalid internal media binding.")
    run = db.get_run(conn, task["project_slug"], task["run_id"])
    me = service.Identity(run["created_by"], "Studio media", "member")
    cp.actor(conn, job["slug"], me)
    slug, row = story.find_row(conn, job["entityId"], "shot")
    target = task["target"]
    if slug != job["slug"] or target.get("tab_key") != row["tabKey"] or target.get("row_id") != row["rid"] or target.get("col_index") != story.media_column(row, "video"):
        raise cp.OrchestrationError(403, "The media output exceeds its production/shot/video scope.")
    policy = story.production_policy(conn, slug)
    if job["production_policy"] != policy:
        raise cp.OrchestrationError(409, "Production policy changed; create a new allocation.")
    try:
        for step in job["steps"].values():
            if step["kind"] == "generate":
                story.authorize_card(conn, slug, step["card"])
    except (worker.WorkerError, story.StoryError):
        raise cp.OrchestrationError(409, "Production policy no longer permits this media task.") from None
    try:
        for key in task["input_snapshot"]["tabs"]:
            cp._task_source_matches(task, key, cp.freeze_tab(conn, slug, key))
    except ValueError:
        raise cp.OrchestrationError(409, "Media source changed; the newer row was preserved.", "SOURCE_CHANGED") from None
    return job


def enqueue(conn, me, slug, identifier, allocation, sources, actions, *, frozen_cards=None, accounting_prefix=None, execution_agent_key='coordinator', grading_objective=None, accounting_session_key=None, budget_cap_usd=None):
    cp.actor(conn, slug, me)
    _, row = story.find_row(conn, identifier, "shot")
    tab = cp.freeze_tab(conn, slug, row["tabKey"])
    table = next(t for t in tab["doc"]["content"] if t.get("type") == "table" and any(r.get("attrs", {}).get("bid") == row["rid"] for r in t["content"]))
    target = {"tab_key": row["tabKey"], "row_id": row["rid"], "table_id": table["attrs"]["bid"], "col_index": story.media_column(row, "video")}
    scope = {"target_tab": row["tabKey"], "table_id": table["attrs"]["bid"], "base_revision": tab["revision"], "row_ids": [row["rid"]], "column_ids": column_ids(table)}
    run = cp.create_run(conn, me, slug, "Studio media review: " + identifier, client_request_id="studio:" + uuid.uuid4().hex,
                        deadline_at=(cp.now() + dt.timedelta(minutes=30)).isoformat())
    from project_assistant import execution_governance as governance
    prefix = accounting_prefix or 'media:' + run['id']
    episode_id = story.shot_view(conn, slug, row).get('episodeId', 'ep_' + slug + '_01')
    accounting_session_key = accounting_session_key or 'run:' + run['id']
    accounting = governance.media_context(me, slug, agent_key=execution_agent_key, episode_id=episode_id, accounting_session_key=accounting_session_key, budget_cap_usd=budget_cap_usd)
    operations = governance.allocation_operations(allocation, prefix, frozen_cards)
    for operation in operations:
        if operation['card']['engine_config']['driver'] == 'comfy_router':
            branches = allocation.get('race_plans') or [allocation]
            stages = [s for b in branches for s in b['stages'] if s['kind'] == 'generate' and s['card_id'] == operation['card']['card_id']]
            if any(s.get('inputs') for s in stages):
                raise governance.AdmissionError('Future generated Router references cannot be prequoted; quote the reviewed source first.')
            operation['router_request'] = {'task': {'input': story.snapshot(conn, slug, row), 'production_policy': story.production_policy(conn,slug)}, 'values': {}}
        governance.prepare_operation(conn, accounting, **operation)
    operation_keys = {o['request_key'].removeprefix(prefix + ':'): o['request_key'] for o in operations}
    from project_assistant import agent_registry
    sponsor=agent_registry.get_agent(conn,slug,execution_agent_key)
    envelope=sponsor['outcome_grader'] if grading_objective is not None else None
    job = {"accounting_session_key": accounting_session_key, "budget_cap_usd": str(budget_cap_usd) if budget_cap_usd is not None else None, "grading_objective": grading_objective, "outcome_grader": envelope, "episode_id": episode_id, "execution_agent_key": execution_agent_key, "operation_keys": operation_keys, "slug": slug, "entityId": identifier, "production_policy": story.production_policy(conn, slug), "sources": sources, "steps": {}}
    mapped = {}
    plans = allocation.get("race_plans")
    if plans:
        # Both branches include their own actual preparation; only the final media task races.
        branches = []
        for index, branch in enumerate(plans):
            deps = []
            for step in branch["stages"][:-1]:
                name = f"branch{index}:" + step["step_id"]
                fixed = copy.deepcopy(step)
                fixed["inputs"] = {k: {**v, "from_step": f"branch{index}:" + v["from_step"]} for k, v in fixed.get("inputs", {}).items()}
                task = add_task(conn, me, slug, run, target, scope, job, name, fixed, deps, frozen_cards=frozen_cards)
                deps = [task["id"]]
                mapped[name] = task["id"]
            final = copy.deepcopy(branch["stages"][-1])
            final["inputs"] = {k: {**v, "from_step": f"branch{index}:" + v["from_step"]} for k, v in final.get("inputs", {}).items()}
            branches.append((final, deps))
        steps = {"studio:open": branches[0][0], "studio:closed": branches[1][0]}
        task = add_task(conn, me, slug, run, target, scope, job, "race", steps, list(dict.fromkeys(d for _, deps in branches for d in deps)), race=True, frozen_cards=frozen_cards)
        cp.start_race(conn, me, slug, task["id"], ["studio:open", "studio:closed"])
    else:
        for step in allocation["stages"]:
            name = step["step_id"]
            dependencies = list(dict.fromkeys(d for dep in step.get("depends_on", []) for d in mapped.get(dep, [])))
            if step["kind"] == "approval":
                # Upstream generation completes only after its existing proposal is applied.
                mapped[name] = dependencies
                continue
            task = add_task(conn, me, slug, run, target, scope, job, name, step, dependencies, frozen_cards=frozen_cards)
            mapped[name] = [task["id"]]
    cp.schedule_ready(conn, slug)
    actions.append(lambda: wake(slug, run["id"]))
    meta = story.shot_meta(conn, identifier) | {"allocation": allocation, "mediaRunId": run["id"]}
    story.store(conn, "meta_" + identifier, "shot_meta", meta, slug)
    return {"runId": run["id"], "status": "QUEUED", "reviewRequired": True, "allocation": allocation}


def add_task(conn, me, slug, run, target, scope, base, name, step, dependencies, race=False, *, frozen_cards=None):
    steps = copy.deepcopy(step if race else {"single": step})
    for value in steps.values():
        if value["kind"] == "generate":
            value["card"], value["workflow"] = (copy.deepcopy(frozen_cards[value["card_id"]]) if frozen_cards is not None
                                                  else worker._resolve_openapi_card_and_workflow(value["card_id"]))
    key = "studio:open" if race else "studio:prepare" if step["kind"] == "prepare" else "studio:open" if worker.card_execution_profile(steps['single']['card'])['tier'] == 'open_weights' else "studio:closed"
    job = copy.deepcopy(base) | {"name": name, "steps": steps}
    task = cp.create_task(conn, me, slug, run["id"], objective="Studio " + name, agent_key=key, scope=scope, target=target,
                          depends_on=dependencies, strategy="race" if race else "single", write_mode="analysis_only" if not race and step["kind"] == "prepare" else "proposal",
                          _media_principal=_PRINCIPAL, _media_job=job)
    snapshots = task["input_snapshot"]
    if repo.get_tab(conn, slug, "soul-cast"):
        snapshots["tabs"]["soul-cast"] = cp.freeze_tab(conn, slug, "soul-cast")
        db.execute(conn, "UPDATE projectops.orchestration_task SET input_snapshot=%s::jsonb WHERE id=%s", (json.dumps(snapshots), task["id"]))
    return task


class MediaHead(story.StoryHead):
    def __init__(self, dispatch, task, actor):
        super().__init__({"_slug": task["project_slug"], "_actor": actor})
        self.dispatch = dispatch

    def lease_lost(self):
        from project_docs import http
        try:
            with http.open_connection() as conn:
                cp.renew_dispatch(conn, _PRINCIPAL, self.dispatch["handle"], self.dispatch["lease_token"])
                if hasattr(self, 'accounting_context'):
                    from project_assistant import execution_governance as governance
                    governance.live(conn, self.accounting_context, destination=getattr(self, 'accounting_destination', None))
                    if getattr(self, 'accounting_card', None):
                        governance.media_credentials(conn,self.accounting_context,self.accounting_card)
            return False
        except Exception:
            return True

    def upload(self, task, data, mime, filename=None):
        if self.lease_lost():
            raise worker.WorkerError("The media lease ended before upload.")
        return super().upload(task, data, mime, filename)


def execute(dispatch):
    from project_docs import http
    head = None
    try:
        with http.open_connection() as conn:
            current = cp.leased_dispatch(conn, _PRINCIPAL, dispatch["handle"], dispatch["lease_token"])
            task = db.get_task(conn, current["project_slug"], current["task_id"])
            job = verify_task(conn, task)
            run = db.get_run(conn, task["project_slug"], task["run_id"])
            _, row = story.find_row(conn, job["entityId"], "shot")
            execution = {"id": dispatch["id"], "capability": "video_gen", "production_policy": job["production_policy"], "input": story.snapshot(conn, job["slug"], row)}
            outputs = dict(job["sources"])
            for predecessor in db.tasks(conn, job["slug"], run["id"]):
                if predecessor["status"] != "completed":
                    continue
                for previous in db.dispatches(conn, job["slug"], predecessor["id"]):
                    if previous["status"] == "succeeded" and previous.get("output_json"):
                        outputs[predecessor["input_snapshot"]["story_media"]["name"]] = previous["output_json"]
            execution["input"]["predecessor_tasks"] = [{"output": value} for value in outputs.values()]
            step = job["steps"].get(current["agent_key"], job["steps"].get("single"))
        head = MediaHead(dispatch, task, run["created_by"])
        from project_assistant import execution_governance as governance
        accounting = governance.media_context(service.Identity(run['created_by'], 'Studio media', 'member'), job['slug'],
            agent_key=job.get('execution_agent_key', 'coordinator'), episode_id=job.get('episode_id'), run_id=run['id'],
            accounting_session_key=job.get('accounting_session_key') or 'run:' + run['id'], budget_cap_usd=job.get('budget_cap_usd'), dispatch_id=dispatch['id'],
            admission_no=dispatch['admission_no'], lease_token=dispatch['lease_token'], worker_id=_PRINCIPAL,
            deadline_at=dispatch['deadline_at'], authority_check=lambda conn: verify_task(conn, task))
        name = job['name']
        if name == 'race':
            name = ('branch0:' if current['agent_key'] == 'studio:open' else 'branch1:') + step['step_id']
        head.accounting_context = accounting
        head.accounting_keys = {step['step_id']: job.get('operation_keys', {}).get(name, 'prep:' + dispatch['id'])}
        output = story_allocation.execute_steps(execution, [step], head, outputs=outputs)
        if step['kind'] == 'generate' and job.get('grading_objective') is not None:
            from project_assistant import agent_registry, outcome_grader
            with http.open_connection() as conn:
                sponsor=agent_registry.get_agent(conn,job['slug'],accounting.agent_key)
            config=job.get('outcome_grader') or {}
            if not config.get('enabled'):
                config=sponsor.get('outcome_grader') or {}
            if config.get('enabled'):
                accounting.original_objective=job['grading_objective']
                def trace(entry):
                    def save(conn):
                        governance.live(conn,accounting)
                        cp.renew_dispatch(conn,_PRINCIPAL,dispatch['handle'],dispatch['lease_token'])
                        db.execute(conn,'UPDATE projectops.orchestration_dispatch SET tools_trace=tools_trace||%s::jsonb WHERE id=%s',
                                   (json.dumps([entry]),dispatch['id']))
                    governance.transaction(accounting,save)
                card=outcome_grader.grade_media(accounting,{**sponsor,'outcome_grader':config},output,on_trace=trace)
                if not card['passed']:
                    outcome_grader.needs_you(accounting,card,terminal=True)
                    with http.open_connection() as conn:
                        cp.complete_dispatch(conn,_PRINCIPAL,dispatch['handle'],dispatch['lease_token'],outcome='awaiting_gate',
                            output={'text':'Needs You: media outcome check failed.','outcome_grader':card,'candidate':output},proposal_ids=[])
                    return
                output={**output,'outcome_grader':card}
        with http.open_connection() as conn:
            cp.leased_dispatch(conn, _PRINCIPAL, dispatch["handle"], dispatch["lease_token"])
            ctx = SimpleNamespace(worker_id=_PRINCIPAL, slug=job["slug"], dispatch_id=dispatch["id"], admission_no=dispatch["admission_no"], lease_token=dispatch["lease_token"], me=service.Identity(run["created_by"], "Studio media", "member"))
            proposals = cp.prepare_dispatch_output(conn, ctx, output)
            cp.complete_dispatch(conn, _PRINCIPAL, dispatch["handle"], dispatch["lease_token"], outcome="succeeded", output=output, proposal_ids=proposals)
    except Exception:
        # Never auto-resubmit a failed/ambiguous paid media request or echo provider details.
        try:
            with http.open_connection() as conn:
                cp.complete_dispatch(conn, _PRINCIPAL, dispatch["handle"], dispatch["lease_token"], outcome="failed", output={"error": "Media execution failed or its source/authority changed; reconcile any provider job before a new request.", "retryable": False}, proposal_ids=[])
        except Exception:
            pass


def wake(slug, run_id):
    with _LOCK:
        if run_id in _ACTIVE:
            return
        _ACTIVE.add(run_id)
    def poll():
        from project_docs import http
        try:
            # This is a worker for the existing M8 queue, not a second task scheduler.
            until = time.monotonic() + 1800
            while time.monotonic() < until:
                with http.open_connection() as conn:
                    run = db.get_run(conn, slug, run_id)
                    if not run or run["status"] not in cp.ACTIVE_RUNS:
                        return
                    cp.sweep(conn, slug)
                    cp.schedule_ready(conn, slug)
                    dispatch = cp.claim_dispatch(conn, _PRINCIPAL, list(KEYS), allowed_projects=[slug])
                if dispatch:
                    thread = threading.Thread(target=execute, args=(dispatch,), daemon=True, name="studio-media")
                    thread.start()
                time.sleep(.2 if dispatch else 1)
        except Exception:
            return  # A restart/connection loss requires explicit resume, never paid resubmission.
        finally:
            with _LOCK:
                _ACTIVE.discard(run_id)
    threading.Thread(target=poll, daemon=True, name="studio-media-queue").start()
