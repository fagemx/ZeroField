"""Self-hosted OpenAPI v2 card registry, binary media store and task execution."""
from __future__ import annotations

from pathlib import Path
import copy
import hashlib
import json
import mimetypes
import re
import threading
import time

from . import card_engine, runtime, model_router
from . import _compat as legacy

__all__ = [
    '_OPENAPI_LOCK',
    '_OPENAPI_SEQ',
    '_OPENAPI_MEDIA_STORE',
    '_OPENAPI_CARDS',
    '_OPENAPI_TASKS',
    '_parse_multipart_file',
    'openapi_upload_binary',
    'openapi_get_media',
    'openapi_register_card',
    'openapi_list_cards',
    '_resolve_openapi_card_and_workflow',
    '_execute_openapi_task',
    'openapi_run_app',
    'openapi_query_task',
]


_OPENAPI_LOCK = threading.Lock()


_OPENAPI_SEQ = 100000


_OPENAPI_MEDIA_STORE: dict[str, tuple[bytes, str]] = {}


_OPENAPI_CARDS: dict[str, tuple[dict, dict | None]] = {}


_OPENAPI_TASKS: dict[str, dict] = {}

# Execution capabilities and frozen inputs never enter serializable task/wire data.
_OPENAPI_EXECUTIONS: dict[str, dict] = {}


class _OpenAPIAuthority:
    """Trusted in-process HTTP binding; JSON/callable-shaped inputs are not authority."""
    def check(self, card, references):
        raise NotImplementedError


def _media_slots(card, workflow, node_info):
    """All consumed media literals, including hidden/unexposed graph defaults."""
    media_fields = {(str(n["nodeId"]), n["fieldName"]) for n in card["nodes"]
                    if n["fieldType"] in ("IMAGE", "VIDEO", "AUDIO")}
    if workflow is None:
        for item in node_info:
            if (str(item["nodeId"]), item["fieldName"]) in media_fields:
                value = item["fieldValue"]
                if str(value).strip().lower() not in ("", "none"):
                    yield item, "fieldValue", str(value)
        return

    def literals(container, key, media=False):
        value = container[key]
        if isinstance(value, str):
            if value.strip().lower() not in ("", "none") and (media or re.fullmatch(r"[0-9a-f]{64}\.[A-Za-z0-9]+", value)):
                yield container, key, value
        elif isinstance(value, (dict, list)):
            if (isinstance(value, list) and len(value) == 2 and isinstance(value[0], str)
                    and value[0] in workflow and type(value[1]) is int):
                return  # A Comfy link is not a media literal, even with a filename-shaped node ID.
            for child in (value if isinstance(value, dict) else range(len(value))):
                yield from literals(value, child)

    for nid, node in workflow.items():
        inputs = node.get("inputs") or {}
        for field in inputs:
            yield from literals(inputs, field, (str(nid), field) in media_fields or field in ("image", "video", "audio"))


def _parse_multipart_file(raw_bytes: bytes, content_type: str) -> tuple[bytes, str, str]:
    """Extract (file_bytes, mime, filename) from a multipart/form-data upload or raw binary body."""
    m = re.search(r'boundary=(?:"([^"]+)"|([^;\s]+))', content_type or "", re.I)
    if not m:
        return raw_bytes, content_type.split(";")[0].strip() or "application/octet-stream", "upload.bin"
    boundary = (m.group(1) or m.group(2)).encode("utf-8")
    parts = raw_bytes.split(b"--" + boundary)
    for part in parts[1:]:
        if part.startswith(b"--") or not part.strip():
            continue
        part = part.lstrip(b"\r\n")
        sep = b"\r\n\r\n" if b"\r\n\r\n" in part else b"\n\n"
        if sep not in part:
            continue
        header_bytes, payload = part.split(sep, 1)
        if payload.endswith(b"\r\n"):
            payload = payload[:-2]
        elif payload.endswith(b"\n"):
            payload = payload[:-1]
        headers_text = header_bytes.decode("utf-8", errors="replace")
        if "name=" in headers_text:
            fn_m = re.search(r'filename="([^"]*)"', headers_text, re.I)
            ct_m = re.search(r'Content-Type:\s*([^\r\n;]+)', headers_text, re.I)
            fname = fn_m.group(1) if fn_m else "upload.bin"
            mime = ct_m.group(1).strip() if ct_m else (mimetypes.guess_type(fname)[0] or "application/octet-stream")
            return payload, mime, fname
    raise runtime.WorkerError("Multipart body did not contain a file part")


def openapi_upload_binary(raw_bytes: bytes, content_type: str = "", filename: str = "") -> dict:
    """Self-hosted RunningHub-compatible POST /openapi/v2/media/upload/binary handler."""
    if not raw_bytes:
        raise runtime.WorkerError("Upload body is empty")
    if "multipart/form-data" in (content_type or "").lower():
        file_bytes, mime, orig_name = _parse_multipart_file(raw_bytes, content_type)
        filename = filename or orig_name
    else:
        file_bytes = raw_bytes
        mime = (content_type or "").split(";")[0].strip()
    if not file_bytes or len(file_bytes) > legacy.MAX_MEDIA:
        raise runtime.WorkerError("Media must be between 1 byte and 64 MB")
    ext = Path(filename).suffix.lower() if filename else ""
    if not ext:
        ext_map = {
            "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif",
            "video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm",
            "audio/mpeg": ".mp3", "audio/wav": ".wav",
        }
        ext = ext_map.get(mime.lower(), "")
    if not ext:
        if file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            ext, mime = ".png", "image/png"
        elif file_bytes.startswith(b"\xff\xd8\xff"):
            ext, mime = ".jpg", "image/jpeg"
        elif len(file_bytes) >= 12 and file_bytes[4:8] == b"ftyp":
            ext, mime = ".mp4", "video/mp4"
        else:
            ext = ".bin"
    if not mime or mime == "application/octet-stream":
        mime = mimetypes.guess_type("file" + ext)[0] or "application/octet-stream"
    file_name = hashlib.sha256(file_bytes).hexdigest() + ext
    with _OPENAPI_LOCK:
        _OPENAPI_MEDIA_STORE[file_name] = (file_bytes, mime)
    return {
        "code": 0,
        "msg": "success",
        "data": {
            "fileName": file_name,
            "fileType": "input",
        },
    }


def openapi_get_media(file_name: str) -> tuple[bytes, str] | None:
    with _OPENAPI_LOCK:
        return _OPENAPI_MEDIA_STORE.get(str(file_name or "").strip())


def openapi_register_card(body: dict) -> dict:
    """Register a RunningHub/ComfyUI workflow JSON + optional curl/nodeInfoList as a self-hosted AI App."""
    if not isinstance(body, dict) or not body.get("workflow"):
        raise runtime.WorkerError("workflow (JSON object or file path) is required")
    wf_input = body["workflow"]
    if isinstance(wf_input, (str, Path)):
        raw_wf = json.loads(Path(wf_input).read_text(encoding="utf-8-sig"))
    elif isinstance(wf_input, dict):
        raw_wf = copy.deepcopy(wf_input)
    else:
        raise runtime.WorkerError("workflow must be a JSON object or file path")
    rh_spec = body.get("runninghub_spec") or body.get("curl") or body.get("nodeInfoList")
    card = card_engine.extract_studio_card_from_workflow(
        wf_input,
        card_id=body.get("card_id"),
        label=body.get("label"),
        runninghub_spec=rh_spec,
        webapp_id=body.get("webappId") or body.get("workflowId"),
    )
    api_wf = card_engine.convert_litegraph_to_api(raw_wf)
    webapp_id = str(card.get("engine_config", {}).get("webappId") or card["card_id"])
    card["engine_config"]["webappId"] = webapp_id
    with _OPENAPI_LOCK:
        _OPENAPI_CARDS[card["card_id"]] = (card, api_wf)
        _OPENAPI_CARDS[webapp_id] = (card, api_wf)
    sample_node_info = [
        {"nodeId": n["nodeId"], "fieldName": n["fieldName"], "fieldValue": n.get("defaultValue", "None"), "description": None}
        for n in card["nodes"] if not n.get("hidden")
    ]
    return {
        "code": 0,
        "msg": "success",
        "webappId": webapp_id,
        "card": card,
        "nodeInfoList": sample_node_info,
    }


def openapi_list_cards() -> list[dict]:
    cards_by_id = {}
    if legacy.CARDS_DIR.is_dir():
        for f in sorted(legacy.CARDS_DIR.glob("*.json")):
            try:
                c = legacy.load_studio_card(f)
                cards_by_id[c["card_id"]] = c
            except Exception:
                continue
    with _OPENAPI_LOCK:
        for cid, (c, _) in _OPENAPI_CARDS.items():
            cards_by_id[c["card_id"]] = c
    return list(cards_by_id.values())


def _resolve_openapi_card_and_workflow(webapp_id: str) -> tuple[dict, dict | None]:
    key = str(webapp_id or "").strip()
    with _OPENAPI_LOCK:
        if key in _OPENAPI_CARDS:
            card, wf = _OPENAPI_CARDS[key]
            return copy.deepcopy(card), copy.deepcopy(wf) if card_engine.card_execution_profile(card)["requires_comfyui"] else None
    card = legacy.load_studio_card(key)
    if not card_engine.card_execution_profile(card)["requires_comfyui"]:
        return card, None
    wf_ref = card.get("engine_config", {}).get("workflow")
    if not wf_ref:
        raise runtime.WorkerError(f"Card {card['card_id']} has no workflow configured")
    wf_path = Path(wf_ref) if Path(wf_ref).is_absolute() else (legacy.CARDS_DIR.parents[1] / wf_ref)
    if not wf_path.is_file():
        raise runtime.WorkerError(f"Configured workflow file not found: {wf_ref}")
    wf = json.loads(wf_path.read_text(encoding="utf-8-sig"))
    return card, card_engine.convert_litegraph_to_api(wf)


def _execute_openapi_task(task_id: str, card: dict, compiled_workflow: dict,
                          node_info: list[dict], base_url: str) -> None:
    client, authority, accounting, gpu = None, None, None, None
    try:
        with _OPENAPI_LOCK:
            record = _OPENAPI_TASKS[task_id]
            if record["status"] != "RUNNING":
                return
            execution = _OPENAPI_EXECUTIONS.get(task_id)
            if execution is not None:
                if execution["started"]:
                    return
                execution["started"] = True
                card, compiled_workflow, node_info = copy.deepcopy(execution["inputs"])
                authority, references = execution["authority"], execution["references"]
            elif record.get("http_bound"):
                raise runtime.WorkerError("HTTP media execution authority is unavailable")
            else:
                references = ()  # Retain trusted standalone/private-helper compatibility.
            policy = record.get("production_policy")

        def checkpoint():
            with _OPENAPI_LOCK:
                if _OPENAPI_TASKS.get(task_id, {}).get("status") != "RUNNING":
                    raise runtime.WorkerError("Media execution was canceled")
            if authority is not None:
                try:
                    authority.check(card, references)
                except Exception:
                    raise runtime.WorkerError("Media execution authority changed or reference access was revoked") from None

        def read_reference(reference):
            checkpoint()
            if authority is not None and reference not in references:
                raise runtime.WorkerError("Reference is outside the frozen media inputs")
            stored = openapi_get_media(reference)
            if stored is None:
                raise runtime.WorkerError("OpenAPI inputs require an uploaded media reference")
            return stored

        checkpoint()
        model_router.enforce_card_policy(card, policy)
        if authority is not None:
            from project_assistant import execution_governance as governance
            accounting = authority.prepare(card, [card, compiled_workflow, node_info], task_id)
            governance.transaction(accounting[0], lambda conn: governance.begin_operation(conn, accounting[0], accounting[1], card=card))
        if not card_engine.card_execution_profile(card)["requires_comfyui"]:
            class MediaHead:
                def outbound_timeout(self, requested):
                    if accounting is not None:
                        from project_assistant import execution_governance as governance
                        return governance.remaining(accounting[0], requested)
                    return requested

                def outbound_check(self, url):
                    if authority is not None:
                        authority.check_destination(url)

                def lease_lost(self):
                    try:
                        checkpoint()
                        return False
                    except runtime.WorkerError:
                        return True

                def asset(self, task, reference):
                    return read_reference(reference)

                def upload(self, task, raw, mime):
                    checkpoint()
                    saved = openapi_upload_binary(raw, mime)["data"]["fileName"]
                    return {"asset_url": f"{base_url.rstrip('/')}/openapi/v2/media/output/{saved}", "content_type": mime}

            media_head = MediaHead()
            if accounting is not None:
                media_head.accounting_context = accounting[0]
                accounting[0].active_operation_key = accounting[1]
            output = legacy.execute_story_card({"id": task_id, "production_policy": policy}, card,
                {f"{n['nodeId']}.{n['fieldName']}": n["fieldValue"] for n in node_info}, media_head)
            checkpoint()
            with _OPENAPI_LOCK:
                if _OPENAPI_TASKS[task_id]["status"] == "RUNNING":
                    _OPENAPI_TASKS[task_id].update(status="SUCCESS", results=[{
                        "url": output["asset_url"], "outputType": "mp4" if card["output_mode"] == "video" else output["content_type"].split("/")[-1],
                        "nodeId": "output"}])
            return
        ecfg = dict(card.get("engine_config") or {})
        client = legacy.ComfyPlatformClient(ecfg)
        wf_to_send = copy.deepcopy(compiled_workflow)
        if authority is not None:
            for container, key, reference in _media_slots(card, wf_to_send, node_info):
                raw_bytes, mime = read_reference(reference)
                checkpoint()
                container[key] = client.upload_media(raw_bytes, mime, "openapi")
        else:
            for item in node_info:
                nid, fname = str(item["nodeId"]), str(item["fieldName"])
                stored = openapi_get_media(str(item.get("fieldValue") or "").strip())
                if stored is not None and nid in wf_to_send and fname in (wf_to_send[nid].get("inputs") or {}):
                    checkpoint()
                    wf_to_send[nid]["inputs"][fname] = client.upload_media(*stored, "openapi")
        checkpoint()
        from project_assistant import gpu_arbiter  # SPEC_20 R13: renders on an owned GPU take the cross-process arbiter
        gpu = gpu_arbiter.render(card_engine.comfy_base_url(ecfg, card_engine.comfy_platform(ecfg)), label="render:" + task_id,
                                 timeout=float(ecfg.get("timeout", 600)))
        prompt_id = client.submit_workflow(wf_to_send, task_id)
        deadline = time.monotonic() + float(ecfg.get("timeout", 600))
        poll = float(ecfg.get("poll_interval", 0.5))
        while time.monotonic() < deadline:
            checkpoint()
            history = client.fetch_history(prompt_id)
            checkpoint()
            entry = history.get(prompt_id) if isinstance(history, dict) else None
            status_obj = entry.get("status", {}) if isinstance(entry, dict) else {}
            if isinstance(entry, dict) and (status_obj.get("status_str") == "error" or status_obj.get("error")):
                err_msg = card_engine._normalize_comfy_error(entry)
                raise runtime.WorkerError(err_msg)
            if isinstance(entry, dict) and (entry.get("outputs") or status_obj.get("completed")):
                out_node = str(ecfg.get("output_node") or "")
                outputs = entry.get("outputs") or {}
                if not out_node or out_node not in outputs:
                    out_node = next(iter(outputs.keys()), "")
                if not out_node:
                    raise runtime.WorkerError("ComfyUI finished without output nodes")
                node_output = outputs.get(out_node, {})
                raw_items = [
                    item
                    for key in ("media", "videos", "gifs", "images", "audio")
                    for item in node_output.get(key, [])
                    if isinstance(item, dict) and ("filename" in item or "sdk_output" in item)
                ]
                if not raw_items:
                    raise runtime.WorkerError(f"Output node {out_node} produced no media items")
                first_item = raw_items[0]
                out_filename = str(first_item.get("filename", getattr(first_item.get("sdk_output"), "name", "output.mp4")))
                checkpoint()
                raw_out, out_mime = client.download_output(first_item)
                checkpoint()
                if not raw_out or len(raw_out) > legacy.MAX_MEDIA:
                    raise runtime.WorkerError("Comfy output exceeds the 64 MB asset limit or is empty")
                ext = Path(out_filename).suffix.lower() or (".mp4" if out_mime.startswith("video/") else ".png")
                out_type = ext.lstrip(".")
                saved_name = hashlib.sha256(raw_out).hexdigest() + ext
                with _OPENAPI_LOCK:
                    if _OPENAPI_TASKS[task_id]["status"] != "RUNNING":
                        return
                    _OPENAPI_MEDIA_STORE[saved_name] = (raw_out, out_mime)
                    _OPENAPI_TASKS[task_id].update({
                        "status": "SUCCESS",
                        "results": [
                            {
                                "url": f"{base_url.rstrip('/')}/openapi/v2/media/output/{saved_name}",
                                "outputType": out_type,
                                "nodeId": out_node,
                            }
                        ],
                    })
                return
            time.sleep(max(0.01, poll))
        raise runtime.WorkerError("Local ComfyUI workflow timed out")
    except Exception as exc:
        from project_assistant.execution_governance import AdmissionError
        message = (str(exc) if isinstance(exc, AdmissionError) else
                   "Media execution failed or its authority changed; reconcile any accepted provider job."
                   if authority is not None else str(exc))
        with _OPENAPI_LOCK:
            if task_id in _OPENAPI_TASKS and _OPENAPI_TASKS[task_id]["status"] == "RUNNING":
                _OPENAPI_TASKS[task_id].update({
                    "status": "FAILED",
                    "errorMessage": message,
                    "failedReason": {"exception_message": message},
                })
    finally:
        if gpu is not None:
            gpu.release()
        if accounting is not None:
            from project_assistant import execution_governance as governance
            with _OPENAPI_LOCK:
                succeeded = _OPENAPI_TASKS.get(task_id, {}).get('status') == 'SUCCESS'
            governance.transaction(accounting[0], lambda conn: governance.finalize(conn, accounting[0].slug, accounting[1], outcome='succeeded' if succeeded else 'unknown'))
        if client is not None:
            try:
                client.close()
            except Exception:
                if authority is None:
                    raise  # Keep standalone diagnostics; HTTP cleanup must not leak provider details.


def _prepare_openapi_inputs(webapp_id, body, production_policy):
    parsed = card_engine.parse_runninghub_curl_or_payload(body)
    target_id = str(webapp_id or parsed.get("webappId") or "").strip()
    if not target_id:
        raise runtime.WorkerError("webappId or workflowId is required")
    card, raw_workflow = legacy._resolve_openapi_card_and_workflow(target_id)
    # Permission is supplied by the authenticated caller, never by untrusted wire inputs.
    policy = model_router.enforce_card_policy(card, production_policy)
    direct = not card_engine.card_execution_profile(card)["requires_comfyui"]
    form_values = {
        f"{item['nodeId']}.{item['fieldName']}": item.get("fieldValue")
        for item in parsed["nodeInfoList"]
    }
    node_info = (card_engine.validate_direct_card_values(card, form_values) if direct
                 else card_engine.build_node_info(card, form_values))
    known_keys = {f"{item['nodeId']}.{item['fieldName']}" for item in node_info}
    for item in parsed["nodeInfoList"]:
        k = f"{item['nodeId']}.{item['fieldName']}"
        if k not in known_keys:
            node_info.append({
                "nodeId": str(item["nodeId"]),
                "fieldName": str(item["fieldName"]),
                "fieldValue": str(item.get("fieldValue") if item.get("fieldValue") is not None else ""),
                "description": item.get("description"),
            })
    compiled_workflow = None if direct else card_engine.inject_node_info_into_workflow(raw_workflow, node_info, card)
    references = tuple(sorted({value for _, _, value in _media_slots(card, compiled_workflow, node_info)}))
    return card, compiled_workflow, node_info, policy, target_id, references


def openapi_run_app(webapp_id: str, body: dict, *,
                    base_url: str = "http://127.0.0.1:8000",
                    sync: bool = False, production_policy=None, _authority=None, _post_commit_actions=None) -> dict:
    """Freeze one execution plan. HTTP passes a server-minted _authority, never body callbacks.

    Without _authority this remains the trusted standalone Python API. HTTP always
    supplies a live actor/project binding; task status/policy snapshots cannot grant it.
    """
    global _OPENAPI_SEQ
    if _authority is not None and not isinstance(_authority, _OpenAPIAuthority):
        raise runtime.WorkerError("Invalid in-process media execution authority")
    parsed = card_engine.parse_runninghub_curl_or_payload(body)
    card, compiled_workflow, node_info, policy, target_id, references = _prepare_openapi_inputs(webapp_id, body, production_policy)
    if _authority is not None:
        _authority.check(card, references)
    frozen = copy.deepcopy((card, compiled_workflow, node_info))
    with _OPENAPI_LOCK:
        _OPENAPI_SEQ += 1
        task_id = f"{int(time.time() * 1000)}{_OPENAPI_SEQ}"
        _OPENAPI_TASKS[task_id] = {
            "taskId": task_id,
            "webappId": target_id,
            "card_id": card["card_id"],
            "status": "RUNNING",
            "errorCode": "",
            "errorMessage": "",
            "failedReason": None,
            "results": [],
            "nodeInfoList": node_info,
            "compiled_workflow": compiled_workflow,
            "production_policy": policy,
            "http_bound": _authority is not None,
            "instanceType": parsed.get("instanceType", "default"),
            "usePersonalQueue": parsed.get("usePersonalQueue", "false"),
        }
        _OPENAPI_EXECUTIONS[task_id] = {"inputs": frozen, "authority": _authority, "references": references, "started": False}
    if sync:
        _execute_openapi_task(task_id, card, compiled_workflow, node_info, base_url)
    else:
        def start():
            threading.Thread(target=_execute_openapi_task,
                args=(task_id, card, compiled_workflow, node_info, base_url), daemon=True).start()
        if _post_commit_actions is None:
            start()
        else:
            _post_commit_actions.append(start)
    return {
        "code": 0,
        "msg": "success",
        "taskId": task_id,
        "status": _OPENAPI_TASKS[task_id]["status"] if sync else "RUNNING",
        "clientId": "zerofield-local",
        "promptTips": "{}",
    }


def openapi_query_task(body: dict) -> dict:
    """Self-hosted RunningHub-compatible POST /openapi/v2/query handler."""
    if not isinstance(body, dict):
        raise runtime.WorkerError("Query body must be a JSON object")
    task_id = str(body.get("taskId") or "").strip()
    if not task_id:
        raise runtime.WorkerError("taskId is required")
    with _OPENAPI_LOCK:
        record = _OPENAPI_TASKS.get(task_id)
        if not record:
            raise runtime.WorkerError(f"Task not found: {task_id}")
        snapshot = copy.deepcopy(record)
    return {
        "code": 0,
        "msg": "success",
        "taskId": snapshot["taskId"],
        "status": snapshot["status"],
        "errorCode": snapshot.get("errorCode", ""),
        "errorMessage": snapshot.get("errorMessage", ""),
        "failedReason": snapshot.get("failedReason"),
        "results": snapshot.get("results", []),
        "compiledWorkflow": snapshot.get("compiled_workflow", {}),
    }
