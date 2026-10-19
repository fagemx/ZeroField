"""Unified media dispatch and production-policy boundary.

Direct endpoints are trusted deployment configuration, never inferred vendor APIs.
See ADAPTER_CONTRACT below before enabling a commercial template.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import urlsplit

from . import card_engine, runtime
from . import _compat as legacy

__all__ = ["ModelRouter", "execute_story_card", "execute_vendor_card",
           "execute_runninghub_cloud_card", "probe_local_comfy_status",
           "effective_production_policy", "enforce_card_policy", "provider_configuration_status", "ADAPTER_CONTRACT"]

ADAPTER_CONTRACT = """
Vendor templates require adapter_contract=zerofield_media_v1: an operator-managed
HTTP adapter, NOT a claim about Seedance/Kling's official wire protocol. Configure
base_url_env and api_key_env on the server. POST /media/upload/binary accepts raw
media with its Content-Type; returns {code:0,data:{fileName:string}} (an opaque
adapter reference). POST /run accepts {model,inputs:{semantic_field:value}}.
It returns {code:0,status:'SUCCESS',results:[{url,outputType}]} or
{code:0,status:'RUNNING',taskId:string}. POST /query accepts {taskId} and returns
that same status/results envelope. FAILED/CANCELED are terminal; provider messages
are never propagated. Numbers in inputs are JSON numbers; optional absent media
is omitted. Upload handles become media input values. No implicit retry/resubmit.

runninghub_cloud uses configured /openapi/v2 base, POST /media/upload/binary,
/run/ai-app/{webappId} with {webappId,nodeInfoList}, and /query with {taskId}.
Upload response is {code:0,data:{fileName}}; run/query use top-level taskId,
status (QUEUED/RUNNING/SUCCESS/FAILED/CANCELED), results:[{url,outputType}].
Deployment must verify this contract against its actual RunningHub service.

All HTTP redirects are forbidden. Provider bases and media_origins (origin-only
HTTP(S) strings) are trusted operator configuration, not request inputs. HTTPS is
required except explicit loopback endpoints for deterministic development tests.
Outputs must be on the configured origin or media_origins; download requests NEVER
carry provider or project credentials. Cross-origin signed URLs require an explicit
media_origins entry. Input references must be authorized head.asset references;
external URLs and local paths are not fetched. Output/input sizes are bounded at
64 MB; only one matching take is downloaded. The cloud template reuses the local
H3 reference field schema; its actual deployed WebApp mapping is NOT verified and
must be confirmed by the operator before use. Polling observes lease cancellation,
but does not promise remote job termination. Timeout/transport ambiguity requires
operator reconciliation and explicit retry, not an automatic second paid request.

Policy: effective_production_policy(project_policy=None) defaults to
open_weights_only. An explicitly set OPENBENCH_PRODUCTION_POLICY is a deployment
lock (open_weights_only or hybrid_studio); a project may further restrict it, never
relax an open-only lock. A hybrid deployment does NOT opt projects into hybrid.
Pass an authorized project choice as task['production_policy']; never trust a card
or model input to grant permission. Self-hosted openapi_run_app accepts the same
choice ONLY as the trusted production_policy keyword, not from its JSON body.
All v2 HTTP routes require crew authentication. HTTP dispatch binds a server-only
actor/project authority to frozen effective inputs and rechecks current membership,
policy, privacy and media grants at execution/export checkpoints. JSON authority or
callback fields grant nothing. Trusted standalone Python calls remain separate.
enforce_card_policy is reusable by preflight/allocator and at execution boundaries.
provider_configuration_status(card) reports configuration only, never health or
inference success, and never returns endpoint URLs or credentials.
""".strip()


def effective_production_policy(project_policy=None):
    policies = ("open_weights_only", "hybrid_studio")
    lock = os.environ.get("OPENBENCH_PRODUCTION_POLICY")
    if lock is not None and lock not in policies:
        raise runtime.WorkerError("Invalid deployment production policy")
    if project_policy is not None and project_policy not in policies:
        raise runtime.WorkerError("Invalid project production policy")
    if lock == "open_weights_only":
        return lock
    return project_policy or "open_weights_only"


def enforce_card_policy(card, project_policy=None):
    policy = effective_production_policy(project_policy)
    profile = card_engine.card_execution_profile(card)
    if policy == "open_weights_only" and (profile["tier"] != "open_weights" or profile["driver"] != "comfy_local"):
        raise runtime.WorkerError("Production policy open_weights_only forbids this card")
    return policy


def probe_local_comfy_status(base_url="http://127.0.0.1:8188"):
    """Opt-in bounded health probe; dispatch never depends on this probe."""
    try:
        response = legacy.json_fetch(base_url.rstrip("/") + "/system_stats", timeout=0.5)
        return {"online": isinstance(response, dict), "requires_comfyui": True}
    except Exception:
        return {"online": False, "requires_comfyui": True}


class ModelRouter:
    def execute_card(self, task, card, values, head):
        card = card_engine.validate_studio_card(card)
        enforce_card_policy(card, task.get("production_policy"))
        driver = card["engine_config"]["driver"]
        if driver == "vendor_api":
            return legacy.execute_vendor_card(task, card, values, head)
        if driver == "runninghub_cloud":
            return legacy.execute_runninghub_cloud_card(task, card, values, head)
        graph = task.get("workflow")
        if graph is None:
            _, graph = legacy._resolve_openapi_card_and_workflow(card["card_id"])
        with tempfile.TemporaryDirectory(prefix="zerofield-story-card-") as folder:
            path = Path(folder) / "workflow.json"
            path.write_text(json.dumps(graph), encoding="utf-8")
            config = dict(card["engine_config"], card=card, workflow=str(path), card_values=values,
                          production_policy=task.get("production_policy"))
            try:
                return legacy.comfyui(task, config, head)
            except runtime.WorkerError as exc:
                if driver == "comfy_partner":
                    raise runtime.NonRetryableWorkerError(str(exc)) from None
                raise


def execute_story_card(task, card, values, head):
    return ModelRouter().execute_card(task, card, values, head)


def _check_lease(head):
    if getattr(head, "lease_lost", lambda: False)():
        raise runtime.WorkerError("Lease was lost; stop waiting for provider")


def _endpoint(url):
    try:
        parts = urlsplit(url)
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        raise runtime.WorkerError("Invalid provider endpoint") from None
    if (parts.scheme not in ("https", "http") or not parts.hostname or parts.username or parts.password
            or parts.fragment or (parts.scheme == "http" and parts.hostname not in ("127.0.0.1", "localhost", "::1"))):
        raise runtime.WorkerError("Provider requires HTTPS or an explicit loopback endpoint")
    return parts.scheme, parts.hostname.lower(), port


def _provider_config(card):
    config = card["engine_config"]
    base = os.environ.get(config.get("base_url_env", ""), "").rstrip("/")
    if not base:
        raise runtime.WorkerError("Provider endpoint is not configured; configure the card base_url_env")
    _endpoint(base)
    if urlsplit(base).query:
        raise runtime.WorkerError("Provider base URL cannot contain a query")
    token = runtime.configured_token(config)
    return config, base, token


def provider_configuration_status(card):
    """Safe no-network preflight for allocator/catalog; not proof of provider health."""
    profile = card_engine.card_execution_profile(card)
    if profile["requires_comfyui"]:
        return {"configured": True, "requires_comfyui": True}
    try:
        config, _, _ = _provider_config(card)
        if profile["driver"] == "vendor_api" and config.get("adapter_contract") != "zerofield_media_v1":
            raise runtime.WorkerError("Vendor requires configured zerofield_media_v1 adapter contract")
    except runtime.WorkerError as exc:
        return {"configured": False, "requires_comfyui": False, "reason": str(exc)}
    return {"configured": True, "requires_comfyui": False}


def _request(url, head, **kwargs):
    _check_lease(head)
    if callable(getattr(type(head), 'outbound_check', None)):
        head.outbound_check(url)
    if callable(getattr(type(head), 'outbound_timeout', None)):
        kwargs['timeout'] = head.outbound_timeout(kwargs.get('timeout', 60))
    try:
        result = legacy.json_fetch(url, **kwargs)
    except runtime.TransientWorkerError:
        # A POST may already have been accepted; worker retries would duplicate spend.
        raise runtime.WorkerError("Provider transport ambiguous; reconcile the remote task before explicit retry") from None
    if not isinstance(result, dict) or type(result.get("code")) is not int or result["code"] != 0:
        raise runtime.WorkerError("Provider rejected the request or returned an invalid envelope")
    _check_lease(head)
    return result


def _inputs(task, card, values, head):
    config = dict(card["engine_config"], card_values=values)
    ctx = legacy.resolve_studio_context(task)
    # Legacy headerless fallback must not turn a known keyframe into driving video.
    if ctx.get("source_video") and ctx["source_video"] in (ctx.get("anchor_keyframe"), ctx.get("first_frame")):
        ctx = dict(ctx, source_video=None)
    # The shared compiler resolves @assets and explicit values; no graph is needed.
    if not ctx.get("anchor_keyframe") and ctx.get("first_frame"):
        ctx = dict(ctx, anchor_keyframe=ctx["first_frame"])
    form = card_engine._build_card_form_values(card, ctx, config, task, head)
    return card_engine.validate_direct_card_values(card, form)


def _execute_remote(task, card, values, head, driver):
    card = card_engine.validate_studio_card(card)
    enforce_card_policy(card, task.get("production_policy"))
    if card["engine_config"]["driver"] != driver:
        raise runtime.WorkerError("Card driver does not match executor")
    if driver == "vendor_api" and card["engine_config"].get("adapter_contract") != "zerofield_media_v1":
        raise runtime.WorkerError("Vendor requires configured zerofield_media_v1 adapter contract")
    nodes = _inputs(task, card, values, head)
    config, base, token = _provider_config(card)
    config = dict(config, _lease_lost=lambda: getattr(head, "lease_lost", lambda: False)())
    timeout = _positive(config.get("timeout", 600), "timeout")
    poll = _positive(config.get("poll_interval", 0.5), "poll_interval")
    request_timeout = min(_positive(config.get("request_timeout", 60), "request_timeout"), timeout)
    if callable(getattr(type(head), 'outbound_timeout', None)):
        request_timeout = head.outbound_timeout(request_timeout)
    deadline = time.monotonic() + timeout
    cache, source_duration, requested = {}, None, None
    for node, item in zip(card["nodes"], nodes):
        _check_lease(head)
        value = item["fieldValue"]
        if node.get("slot") == "duration":
            requested = float(value)
        if node["fieldType"] not in ("IMAGE", "VIDEO", "AUDIO") or value == "None":
            continue
        if value in cache:
            handle, cached_mime = cache[value]
            if not cached_mime.startswith(node["fieldType"].lower() + "/"):
                raise runtime.WorkerError("Provider media reference used with incompatible types")
            item["fieldValue"] = handle
            continue
        raw, mime = head.asset(task, value)
        if not raw or len(raw) > legacy.MAX_MEDIA or not mime.startswith(node["fieldType"].lower() + "/"):
            raise runtime.WorkerError("Unsupported or oversized provider input media")
        if node.get("slot") == "driving_video":
            with tempfile.TemporaryDirectory(prefix="zerofield-source-") as folder:
                source = Path(folder) / "source.mp4"
                source.write_bytes(raw)
                source_duration = legacy._probe_video(source, config)["duration"]
        uploaded = _request(base + "/media/upload/binary", head, data=raw, mime=mime,
                            token=token, timeout=request_timeout)
        handle = (uploaded.get("data") or {}).get("fileName")
        if not isinstance(handle, str) or not handle or len(handle) > 4096:
            raise runtime.WorkerError("Provider upload returned no valid media reference")
        cache[value] = (handle, mime)
        item["fieldValue"] = handle
    if time.monotonic() >= deadline:
        raise runtime.WorkerError("Provider input preparation timed out; no generation submitted")
    if driver == "vendor_api":
        inputs = {}
        for node, item in zip(card["nodes"], nodes):
            value = item["fieldValue"]
            if node["fieldType"] in ("IMAGE", "VIDEO", "AUDIO") and value == "None":
                continue
            if node["fieldType"] in ("INT", "FLOAT"):
                value = int(value) if node["fieldType"] == "INT" else float(value)
            inputs[node["fieldName"]] = value
        payload = {"model": config.get("model"), "inputs": inputs}
        path = "/run"
    else:
        app = str(config.get("webappId") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", app):
            raise runtime.WorkerError("Cloud card requires a valid webappId")
        payload = {"webappId": app, "nodeInfoList": nodes}
        path = "/run/ai-app/" + app
    # Retained on the Head so late worker heartbeat/completion errors cannot resubmit.
    head.paid_request_submitted = True
    result = _request(base + path, head, payload=payload, token=token, timeout=request_timeout)
    task_id = result.get("taskId")
    while True:
        _check_lease(head)
        if time.monotonic() >= deadline:
            raise runtime.WorkerError("Provider timed out; reconcile the remote task before explicit retry")
        status = result.get("status")
        if status == "SUCCESS":
            break
        if status in ("FAILED", "CANCELED", "CANCELLED"):
            raise runtime.WorkerError("Provider media generation failed or was canceled")
        if status not in (None, "QUEUED", "RUNNING") or not isinstance(task_id, str) or not task_id:
            raise runtime.WorkerError("Provider returned invalid task status")
        time.sleep(min(poll, max(0, deadline - time.monotonic())))
        if time.monotonic() >= deadline:
            raise runtime.WorkerError("Provider timed out; reconcile the remote task before explicit retry")
        result = _request(base + "/query", head, payload={"taskId": task_id}, token=token, timeout=request_timeout)
    results = result.get("results")
    expected = {"video": ("mp4", "webm", "mov"), "image": ("png", "jpg", "jpeg", "webp"), "audio": ("wav", "mp3")}[card["output_mode"]]
    item = next((r for r in results if isinstance(r, dict) and r.get("outputType") in expected), None) if isinstance(results, list) else None
    if item is None or not isinstance(item.get("url"), str):
        raise runtime.WorkerError("Provider completed without a supported media output")
    origin = _endpoint(item["url"])
    allowed = {_endpoint(base)}
    for entry in config.get("media_origins", []):
        if urlsplit(entry).path not in ("", "/") or urlsplit(entry).query:
            raise runtime.WorkerError("media_origins must contain origins only")
        allowed.add(_endpoint(entry))
    if origin not in allowed:
        raise runtime.WorkerError("Provider output origin is not authorized")
    _check_lease(head)
    if callable(getattr(type(head), 'outbound_check', None)):
        head.outbound_check(item['url'])
    try:
        raw, mime = legacy.fetch(item["url"], timeout=request_timeout, limit=legacy.MAX_MEDIA)
    except runtime.TransientWorkerError:
        raise runtime.WorkerError("Provider output unavailable; reconcile before explicit retry") from None
    if not raw or len(raw) > legacy.MAX_MEDIA or not mime.startswith(card["output_mode"] + "/"):
        raise runtime.WorkerError("Provider returned unsupported or oversized output media")
    _check_lease(head)
    if card["output_mode"] == "video":
        limit = min(v for v in (requested, source_duration) if v is not None) if requested is not None or source_duration is not None else None
        if limit is None:
            raise runtime.WorkerError("Video card requires requested or source duration")
        if mime != "video/mp4":
            with tempfile.TemporaryDirectory(prefix="zerofield-normalize-") as folder:
                source, target = Path(folder) / "input.video", Path(folder) / "output.mp4"
                source.write_bytes(raw)
                legacy._run_preparation(["-i", str(source), "-map", "0:v:0", "-map", "0:a:0?",
                    "-c:v", "libx264", "-crf", "16", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-t", str(limit), "-movflags", "+faststart", str(target)], config)
                if target.stat().st_size > legacy.MAX_MEDIA:
                    raise runtime.WorkerError("Normalized output exceeds the 64 MB asset limit")
                raw, mime = target.read_bytes(), "video/mp4"
        raw = legacy.bound_output_video_duration(raw, limit, config)
        # The trimmer may return a short source unchanged; remote MP4 still needs faststart.
        with tempfile.TemporaryDirectory(prefix="zerofield-faststart-") as folder:
            source, target = Path(folder) / "input.mp4", Path(folder) / "output.mp4"
            source.write_bytes(raw)
            legacy._run_preparation(["-i", str(source), "-map", "0:v:0", "-map", "0:a:0?",
                                     "-c", "copy", "-movflags", "+faststart", str(target)], config)
            if target.stat().st_size > legacy.MAX_MEDIA:
                raise runtime.WorkerError("Normalized output exceeds the 64 MB asset limit")
            raw = target.read_bytes()
    if len(raw) > legacy.MAX_MEDIA:
        raise runtime.WorkerError("Normalized output exceeds the 64 MB asset limit")
    _check_lease(head)
    output = head.upload(task, raw, mime)
    return dict(output, reference_role="output_video") if card["output_mode"] == "video" else output


def _positive(value, name):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise runtime.WorkerError(f"Provider {name} must be positive and finite") from None
    if not math.isfinite(number) or number <= 0:
        raise runtime.WorkerError(f"Provider {name} must be positive and finite")
    return number


def execute_vendor_card(task, card, values, head):
    try:
        return _execute_remote(task, card, values, head, "vendor_api")
    except runtime.TransientWorkerError:
        raise runtime.NonRetryableWorkerError("Media transport ambiguous; reconcile before explicit retry") from None
    except runtime.WorkerError as exc:
        raise runtime.NonRetryableWorkerError(str(exc)) from None
    except Exception:
        raise runtime.NonRetryableWorkerError("Vendor adapter failed; verify deployment and response contract") from None


def execute_runninghub_cloud_card(task, card, values, head):
    try:
        return _execute_remote(task, card, values, head, "runninghub_cloud")
    except runtime.TransientWorkerError:
        raise runtime.NonRetryableWorkerError("Media transport ambiguous; reconcile before explicit retry") from None
    except runtime.WorkerError as exc:
        raise runtime.NonRetryableWorkerError(str(exc)) from None
    except Exception:
        raise runtime.NonRetryableWorkerError("RunningHub adapter failed; verify deployment and response contract") from None
