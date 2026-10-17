"""Transactional DAG scheduler, immutable run snapshots, and reviewed result delivery."""
from __future__ import annotations

import copy
import json
import re
import secrets
import uuid

from project_assistant import limbs, privacy, store, table_edits
from project_docs import repository as repo, service
from project_docs.doc_schema import column_ids

ExecutionError = limbs.ExecutionError
_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_RUN_COLUMNS = "id,project_slug,tab_key,definition,definition_revision,created_by,status,created_at,updated_at,execution"
_TASK_COLUMNS = "id,run_id,project_slug,node_id,row_id,capability,assigned_limb,status,attempts,max_attempts,limb_id,lease_hash,lease_until,target,target_snapshot,output,proposal_id,error,created_at,updated_at"
_TASK_KEYS = _TASK_COLUMNS.split(",")


def validate_definition(value, *, allow_empty=False):
    if not isinstance(value, dict) or not isinstance(value.get("nodes"), list) or not isinstance(value.get("edges"), list):
        raise ValueError("工作流需要 nodes 與 edges 陣列")
    nodes, edges = copy.deepcopy(value["nodes"]), copy.deepcopy(value["edges"])
    if not (0 if allow_empty else 1) <= len(nodes) <= 100 or len(edges) > 1000:
        raise ValueError("工作流需要 1～100 個節點，最多 1000 條連線")
    ids = set()
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not _ID.fullmatch(node["id"]) or node["id"] in ids:
            raise ValueError("節點 id 無效或重複")
        ids.add(node["id"])
        if node.get("capability") not in limbs.CAPABILITIES:
            raise ValueError("節點 capability 不支援")
        node.setdefault("title", node["id"])
        if not isinstance(node["title"], str) or len(node["title"]) > 200:
            raise ValueError("節點名稱最多 200 字")
        node.setdefault("prompt", "")
        if not isinstance(node["prompt"], str) or len(node["prompt"]) > 30000:
            raise ValueError("節點指令最多 30000 字")
        node.setdefault("write_mode", "proposal")
        if node["write_mode"] not in ("proposal", "direct"):
            raise ValueError("write_mode 必須是 proposal 或 direct")
        node.setdefault("input_tabs", [])
        if not isinstance(node["input_tabs"], list) or len(node["input_tabs"]) > 30 or any(not isinstance(k, str) for k in node["input_tabs"]):
            raise ValueError("input_tabs 必須是分頁鍵陣列（最多 30 個）")
        if "scope" in node and node["scope"] not in ("once", "rows", "aggregate"):
            raise ValueError("scope 必須是 once、rows 或 aggregate")
        source = node.get("row_source")
        if node.get("scope") == "rows" and not source:
            raise ValueError("rows 節點需要 row_source.tab_key")
        if source is not None:
            _validate_source(source)
        target = node.get("target") or {}
        if not isinstance(target, dict):
            raise ValueError("target 必須是物件")
        if "col_index" in target and (type(target["col_index"]) is not int or not 0 <= target["col_index"] < 256):
            raise ValueError("col_index 必須是零起算欄號")
        if ("col_index" in target or target.get("column_id")) and not target.get("tab_key"):
            raise ValueError("儲存格輸出需要 target.tab_key")
        for key in ("tab_key", "row_id"):
            if key in target and not isinstance(target[key], str):
                raise ValueError(f"target.{key} 必須是文字")
        node["target"] = target
        if target.get("kind", "table") not in ("table", "doc") or target.get("mode", "append") not in ("append", "replace"):
            raise ValueError("target.kind 必須是 table/doc；mode 必須是 append/replace")
        if target.get("kind") == "doc" and ("col_index" in target or "row_id" in target):
            raise ValueError("doc 輸出不能指定儲存格")
        if node.get("limb_id"):
            try:
                uuid.UUID(node["limb_id"])
            except (ValueError, TypeError, AttributeError):
                raise ValueError("limb_id 必須是 Worker UUID") from None
        for key in ("x", "y"):
            if key in node and (type(node[key]) not in (int, float) or not -100000 <= node[key] <= 100000):
                raise ValueError("節點座標無效")
    links = set()
    for edge in edges:
        if not isinstance(edge, dict) or edge.get("source") not in ids or edge.get("target") not in ids:
            raise ValueError("連線指向不存在的節點")
        link = (edge["source"], edge["target"])
        if link in links:
            raise ValueError("連線重複")
        links.add(link)
    seen = set()
    while True:
        additions = {n for n in ids - seen if all(s in seen for s, t in links if t == n)}
        if not additions:
            break
        seen.update(additions)
    if seen != ids:
        raise ValueError("工作流有循環；請移除回到上游的連線")
    return {**copy.deepcopy(value), "nodes": nodes, "edges": edges}


def _validate_source(source):
    if not isinstance(source, dict) or not isinstance(source.get("tab_key"), str) or not source["tab_key"]:
        raise ValueError("row_source 需要 tab_key")
    if "table_id" in source and (not isinstance(source["table_id"], str) or not _ID.fullmatch(source["table_id"])):
        raise ValueError("row_source.table_id 無效")
    if "status_col" in source and (type(source["status_col"]) is not int or not 0 <= source["status_col"] < 256):
        raise ValueError("status_col 必須是零起算欄號")
    statuses = source.get("status", [])
    if isinstance(statuses, str):
        statuses = [statuses]
    if not isinstance(statuses, list) or len(statuses) > 30 or any(not isinstance(s, str) or not s for s in statuses):
        raise ValueError("status 必須是文字或狀態陣列")


def ready_nodes(definition, statuses):
    return [n["id"] for n in definition["nodes"] if statuses.get(n["id"], "blocked") == "blocked"
            and all(statuses.get(e["source"]) == "succeeded" for e in definition["edges"] if e["target"] == n["id"])]


def _write_permission(me):
    if not getattr(me, "can_write", me.role != "viewer"):
        raise ExecutionError(403, "檢視者不能變更或執行工作流")


def _run(row):
    value = dict(zip(_RUN_COLUMNS.split(","), row))
    for key in ("id", "created_by"):
        value[key] = str(value[key])
    value["definition"] = repo._loads(value["definition"])
    value["execution"] = repo._loads(value["execution"]) or {}
    for key in ("created_at", "updated_at"):
        value[key] = repo._iso(value[key])
    return value


def _task(row, private=False):
    value = dict(zip(_TASK_KEYS, row))
    for key in ("id", "run_id", "limb_id", "assigned_limb"):
        value[key] = str(value[key]) if value[key] else None
    for key in ("target", "target_snapshot", "output"):
        value[key] = repo._loads(value[key]) if value[key] is not None else None
    for key in ("created_at", "updated_at"):
        value[key] = repo._iso(value[key])
    context = (value.get("target_snapshot") or {}).get("_source_context")
    if context:
        value["source_context"] = copy.deepcopy(context)
    if not private:
        value.pop("lease_hash", None)
        value.pop("target_snapshot", None)
        value["lease_until"] = repo._iso(value["lease_until"])
    return value


def _fetch_tasks(conn, run_id, private=False):
    with conn.cursor() as cur:
        cur.execute(f"SELECT {_TASK_COLUMNS} FROM projectops.limb_task WHERE run_id=%s ORDER BY created_at,node_id,row_id", (run_id,))
        return [_task(r, private) for r in cur.fetchall()]


def _get_run(conn, run_id, slug=None, key=None, lock=False):
    with conn.cursor() as cur:
        cur.execute(f"SELECT {_RUN_COLUMNS} FROM projectops.flow_run WHERE id=%s" + (" FOR UPDATE" if lock else ""), (run_id,))
        row = cur.fetchone()
    if not row:
        raise ExecutionError(404, "找不到執行紀錄")
    run = _run(row)
    if (slug and run["project_slug"] != slug) or (key and run["tab_key"] != key):
        raise ExecutionError(404, "找不到執行紀錄")
    return run


def _check_tabs(conn, slug, definition):
    for node in definition["nodes"]:
        for key in node["input_tabs"] + ([node["target"]["tab_key"]] if node["target"].get("tab_key") else []) + ([node["row_source"]["tab_key"]] if node.get("row_source") else []):
            if not repo.get_tab(conn, slug, key):
                raise ExecutionError(400, f"節點 {node['id']} 找不到分頁 {key}")
        if node.get("limb_id"):
            workers = limbs.enabled_workers(conn, slug)
            if not any(w["id"] == node["limb_id"] and node["capability"] in w["capabilities"] for w in workers):
                raise ExecutionError(400, f"節點 {node['id']} 綁定的手腳不存在、已停用或能力不符")
        _resolve_column_refs(conn, slug, node)


def _resolve_column_refs(conn, slug, node):
    """Column IDs are authoritative; older definitions retain guarded indices."""
    for ref, id_key, index_key in ((node.get("target", {}), "column_id", "col_index"),
                                    (node.get("row_source") or {}, "status_column_id", "status_col")):
        if not ref.get(id_key):
            continue
        tab = repo.get_tab(conn, slug, ref.get("tab_key"))
        tables = [t for t in (tab or {}).get("doc", {}).get("content", []) if t.get("type") == "table"
                  and (not ref.get("table_id") or t.get("attrs", {}).get("bid") == ref["table_id"])]
        matches = [(t, column_ids(t).index(ref[id_key])) for t in tables if ref[id_key] in column_ids(t)]
        if len(matches) != 1:
            raise ExecutionError(409, "映射欄位已刪除或不唯一，請重新選擇具名欄位")
        ref["table_id"], ref[index_key] = matches[0][0]["attrs"]["bid"], matches[0][1]


def _check_cell_target(conn, slug, target):
    if "col_index" in target and (not target.get("tab_key") or not target.get("row_id")):
        raise ExecutionError(400, "儲存格輸出需要指定分頁與輸出列；逐列工作請設定來源表格")
    if not target.get("tab_key") or not target.get("row_id"):
        return
    tab = repo.get_tab(conn, slug, target["tab_key"])
    if not tab:
        raise ExecutionError(409, "輸出分頁已刪除")
    row = next((r for t in tab["doc"].get("content", []) if t.get("type") == "table" and (not target.get("table_id") or t.get("attrs", {}).get("bid") == target["table_id"])
                for r in t.get("content", [])[_header_offset(t):] if r.get("attrs", {}).get("bid") == target["row_id"]), None)
    if row is None:
        raise ExecutionError(400, f"輸出列 {target['row_id']} 不存在於 {target['tab_key']}")
    if "col_index" in target and target["col_index"] >= len(row.get("content", [])):
        raise ExecutionError(400, "輸出欄號超出表格範圍")


def definition(conn, slug, key):
    tab = repo.get_tab(conn, slug, key)
    if not tab:
        raise ExecutionError(404, "找不到工作流分頁")
    with conn.cursor() as cur:
        cur.execute("SELECT definition,revision FROM projectops.flow_definition WHERE project_slug=%s AND tab_key=%s", (slug, key))
        row = cur.fetchone()
    return {"definition": repo._loads(row[0]) if row else {"nodes": [], "edges": []}, "revision": row[1] if row else 0}


def save_definition(conn, me, slug, key, body):
    _write_permission(me)
    if not repo.get_tab_for_update(conn, slug, key):
        raise ExecutionError(404, "找不到工作流分頁")
    try:
        value = validate_definition(body.get("definition"), allow_empty=True)
    except ValueError as exc:
        raise ExecutionError(400, str(exc)) from exc
    _check_tabs(conn, slug, value)
    current = definition(conn, slug, key)
    if type(body.get("revision")) is not int or body["revision"] != current["revision"]:
        raise ExecutionError(409, "工作流已被修改，請重新載入再儲存")
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO projectops.flow_definition(project_slug,tab_key,definition,revision,updated_by)
                       VALUES(%s,%s,%s::jsonb,1,%s) ON CONFLICT(project_slug,tab_key)
                       DO UPDATE SET definition=EXCLUDED.definition,revision=projectops.flow_definition.revision+1,
                       updated_by=EXCLUDED.updated_by,updated_at=NOW() RETURNING revision""", (slug, key, json.dumps(value), me.actor_id))
        revision = cur.fetchone()[0]
    repo.add_audit(conn, slug, action="flow_save", actor_id=me.actor_id, tab_key=key, detail={"revision": revision})
    return {"definition": value, "revision": revision}


def _check_source_revisions(conn, slug, revisions):
    if not isinstance(revisions, dict) or any(not isinstance(k, str) or type(v) is not int for k, v in revisions.items()):
        raise ExecutionError(400, "source_revisions 必須包含分頁與整數版本")
    for tab_key, revision in sorted(revisions.items()):
        tab = repo.get_tab_for_update(conn, slug, tab_key)
        if not tab or tab["revision"] != revision:
            raise ExecutionError(409, f"來源 {tab_key} 已變更，請重新載入樣本並檢查")


def preflight(conn, me, slug, key, body):
    """Read-only scope preview. It never queues work or calls a provider."""
    _write_permission(me)
    saved = definition(conn, slug, key)
    try:
        value = validate_definition(saved["definition"])
    except ValueError as exc:
        raise ExecutionError(400, "請先儲存有效工作流：" + str(exc)) from exc
    if "definition_revision" in body and body["definition_revision"] != saved["revision"]:
        raise ExecutionError(409, "工作流設定已變更，請重新載入")
    if body.get("execution_mode", "workflow") not in ("workflow", "single_step"):
        raise ExecutionError(400, "execution_mode 必須是 workflow 或 single_step")
    single = body.get("execution_mode") == "single_step"
    if single and any(name in body for name in ("row_source", "target_tab", "row_ids", "start_node_id")):
        raise ExecutionError(400, "單步來源與輸出使用所選步驟設定；不能混用批次或續跑範圍")
    active = {n["id"] for n in value["nodes"]}
    start_id = body.get("node_id") if single else body.get("start_node_id")
    if start_id:
        if start_id not in active:
            raise ExecutionError(400, "找不到指定步驟")
        active = {start_id}
        if not single:
            while True:
                grown = active | {e["target"] for e in value["edges"] if e["source"] in active}
                if grown == active:
                    break
                active = grown
    elif single:
        raise ExecutionError(400, "試這一步需要指定 node_id")
    errors, warnings, sources, nodes = [], [], {}, []
    known_selection_rows = set()
    workers = limbs.connected_workers(conn, slug)
    all_values = repo.field_values(conn, slug)
    selected_rows = body.get("row_ids", [])
    if not isinstance(selected_rows, list) or len(selected_rows) > 200 or any(not isinstance(r, str) or not r for r in selected_rows) or len(set(selected_rows)) != len(selected_rows):
        raise ExecutionError(400, "row_ids 必須是最多 200 個不重複的列 id")
    for node in value["nodes"]:
        if node["id"] not in active:
            continue
        entry = {"node_id": node["id"], "title": node["title"], "scope": node.get("scope", "legacy"),
                 "row_count": 1, "row_ids": [], "write_mode": "proposal" if single else node["write_mode"],
                 "worker_connected": any(node["capability"] in w["capabilities"] and (not node.get("limb_id") or node["limb_id"] == w["id"]) for w in workers)}
        nodes.append(entry)
        if not entry["worker_connected"]:
            errors.append({"node_id": node["id"], "message": "執行服務尚未連接，請在工作台設定連接對應 Worker"})
        try:
            _check_tabs(conn, slug, {"nodes": [node]})
            source = body.get("row_source") or node.get("row_source")
            if source:
                try:
                    _validate_source(source)
                except ValueError as exc:
                    raise ExecutionError(400, str(exc)) from exc
            parents = [e["source"] for e in value["edges"] if e["target"] == node["id"]]
            if single and body.get("input_mode") != "current_sources":
                raise ExecutionError(400, "請明確選擇讀取目前來源；單步不會挪用歷史上游結果")
            if single and parents:
                if not source and not node["input_tabs"]:
                    raise ExecutionError(400, "這一步有上游依賴但未指定目前來源。請先選來源分頁，或執行包含上游的流程")
                warnings.append({"node_id": node["id"], "message": "本次只讀指定的目前來源；不執行上游，也不取用任何歷史上游結果"})
            if not single and parents and node.get("scope") in ("rows", "aggregate"):
                entry["dynamic_rows"] = True
                warnings.append({"node_id": node["id"], "message": "列數是目前資料的預覽；正式執行會在上游完成／核對後重新讀取符合條件的列"})
            if source:
                known_selection_rows.update(r["row_id"] for r in _source_rows(conn, slug, {k: v for k, v in source.items() if k not in ("status", "status_col", "status_column_id")}))
                candidates = _source_rows(conn, slug, source)
                if selected_rows:
                    candidates = [r for r in candidates if r["row_id"] in selected_rows]
                if single:
                    sample_id = body.get("sample_row_id")
                    if not sample_id or not any(r["row_id"] == sample_id for r in candidates):
                        raise ExecutionError(400, "請選擇一筆仍符合來源條件的樣本列")
                    candidates = [r for r in candidates if r["row_id"] == sample_id]
                entry["row_count"] = len(candidates)
                entry["row_ids"] = [r["row_id"] for r in candidates]
                if len(candidates) > 200:
                    raise ExecutionError(400, "來源超過 200 列，請篩選或選取較小範圍")
                if not candidates:
                    warnings.append({"node_id": node["id"], "message": "目前沒有符合條件的列；上游寫入後會重新計算逐列範圍"})
            target = copy.deepcopy(node["target"])
            if body.get("target_tab") and not target.get("tab_key"):
                target["tab_key"] = body["target_tab"]
            if node.get("scope") == "rows" or (not node.get("scope") and selected_rows):
                effective_rows = entry["row_ids"] if node.get("scope") == "rows" else selected_rows
                if not node.get("scope"):
                    entry["row_count"], entry["row_ids"] = len(effective_rows), effective_rows
                for rid in effective_rows:
                    _check_cell_target(conn, slug, {**target, **({"row_id": rid} if target.get("tab_key") and target.get("kind") != "doc" else {})})
            else:
                _check_cell_target(conn, slug, target)
            target_tab = repo.get_tab(conn, slug, target["tab_key"]) if target.get("tab_key") else None
            if target.get("tab_key") and not target_tab:
                raise ExecutionError(400, "輸出分頁不存在")
            entry["target"] = target
            entry["target_title"] = target_tab["title"] if target_tab else "保留結果，不寫回分頁"
            if target_tab:
                tables = _table_data(target_tab["doc"], all_values.get(target["tab_key"], {}))
                if not any(n.get("row_source") for n in value["nodes"] if n["id"] in active):
                    known_selection_rows.update(row["row_id"] for table in tables for row in table["rows"])
                table = next((t for t in tables if not target.get("table_id") or t["table_id"] == target["table_id"]), None)
                if target.get("kind") != "doc" and not table:
                    raise ExecutionError(400, "輸出選擇了表格修改，但指定分頁沒有對應工作表")
                if "col_index" in target and table and target["col_index"] >= len(table["headers"]):
                    raise ExecutionError(400, "輸出欄位已不存在，請重新選擇具名欄位")
                if "col_index" in target and table and target["col_index"] < len(table["headers"]):
                    entry["target_column"] = table["headers"][target["col_index"]]
            for source_key in dict.fromkeys(node["input_tabs"] + ([source["tab_key"]] if source else [])):
                tab = repo.get_tab(conn, slug, source_key)
                tables = _table_data(tab["doc"], all_values.get(source_key, {}))
                sources[source_key] = {"tab_key": source_key, "title": tab["title"], "revision": tab["revision"],
                                       "tables": [{"table_id": t["table_id"], "headers": t["headers"], "row_count": len(t["rows"]), "samples": t["rows"][:3]} for t in tables]}
        except ExecutionError as exc:
            errors.append({"node_id": node["id"], "message": str(exc)})
    if selected_rows and not set(selected_rows) <= known_selection_rows:
        errors.append({"node_id": nodes[0]["node_id"], "message": "部分選取列已不存在於本次來源，請回到表格重新選取"})
    return {"execution_mode": "single_step" if single else "workflow", "definition_revision": saved["revision"],
            "nodes": nodes, "sources": list(sources.values()), "source_revisions": {k: v["revision"] for k, v in sources.items()},
            "errors": errors, "warnings": warnings, "ready": not errors,
            "external_effects": "建立真實執行任務；服務可能呼叫付費模型。單步結果需核對後才寫回。" if single else "建立真實執行任務；依各步設定直接寫入或等待提案核對。"}


def _start_single_step(conn, me, slug, key, body):
    """One selected task, one frozen sample, no inherited upstream outputs."""
    if type(body.get("definition_revision")) is not int:
        raise ExecutionError(400, "試這一步需要核對工作流版本")
    if not repo.get_tab_for_update(conn, slug, key):
        raise ExecutionError(404, "找不到工作流分頁")
    preview = preflight(conn, me, slug, key, body)
    if preview["errors"]:
        raise ExecutionError(409, "；".join(e["message"] for e in preview["errors"]))
    if body.get("source_revisions") != preview["source_revisions"]:
        raise ExecutionError(409, "來源版本與已核對樣本不同，請重新檢查")
    _check_source_revisions(conn, slug, body["source_revisions"])
    saved = definition(conn, slug, key)
    node = copy.deepcopy(next(n for n in saved["definition"]["nodes"] if n["id"] == body["node_id"]))
    node["write_mode"] = "proposal"
    _resolve_column_refs(conn, slug, node)
    value = validate_definition({**saved["definition"], "nodes": [node], "edges": []})
    node = value["nodes"][0]
    row_id = body.get("sample_row_id", "") if node.get("scope") == "rows" else ""
    target = copy.deepcopy(node["target"])
    if row_id and target.get("tab_key") and target.get("kind") != "doc":
        target["row_id"] = row_id
    _check_cell_target(conn, slug, target)
    source = node.get("row_source")
    execution = {"mode": "single_step", "input_mode": "current_sources", "selected_node_id": node["id"],
                 "source_revisions": preview["source_revisions"], "sample_row_id": body.get("sample_row_id"),
                 "row_source": source, "row_sets": {json.dumps(source, sort_keys=True, ensure_ascii=False): [body["sample_row_id"]]} if source else {}}
    identifier = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO projectops.flow_run(id,project_slug,tab_key,definition,definition_revision,created_by,execution)
                       VALUES(%s,%s,%s,%s::jsonb,%s,%s,%s::jsonb)""", (identifier, slug, key, json.dumps(value), saved["revision"], me.actor_id, json.dumps(execution)))
        cur.execute("""INSERT INTO projectops.limb_task(id,run_id,project_slug,node_id,row_id,capability,assigned_limb,status,target)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,'queued',%s::jsonb)""",
                    (str(uuid.uuid4()), identifier, slug, node["id"], row_id, node["capability"], node.get("limb_id") or None, json.dumps(target)))
    repo.add_audit(conn, slug, action="flow_single_step", actor_id=me.actor_id, tab_key=key, target=identifier,
                   detail={"node_id": node["id"], "source_revisions": preview["source_revisions"], "sample_row_id": body.get("sample_row_id")})
    return detail(conn, slug, key, identifier)


def start(conn, me, slug, key, body):
    _write_permission(me)
    if body.get("execution_mode", "workflow") not in ("workflow", "single_step"):
        raise ExecutionError(400, "execution_mode 必須是 workflow 或 single_step")
    if body.get("execution_mode") == "single_step":
        return _start_single_step(conn, me, slug, key, body)
    saved = definition(conn, slug, key)
    if "definition_revision" in body and body["definition_revision"] != saved["revision"]:
        raise ExecutionError(409, "工作流設定已變更，請重新檢查執行範圍")
    try:
        value = validate_definition(saved["definition"])
    except ValueError as exc:
        raise ExecutionError(400, "請先建立並儲存有效工作流：" + str(exc)) from exc
    if "source_revisions" in body:
        _check_source_revisions(conn, slug, body["source_revisions"])
    target_tab = body.get("target_tab")
    if target_tab:
        for node in value["nodes"]:
            if not node["target"].get("tab_key"):
                node["target"]["tab_key"] = target_tab
    rows = body.get("row_ids", [])
    if not isinstance(rows, list) or len(rows) > 200 or any(not isinstance(r, str) or not r or len(r) > 100 for r in rows) or len(set(rows)) != len(rows):
        raise ExecutionError(400, "row_ids 必須是最多 200 個不重複的列 id")
    if any("scope" in n for n in value["nodes"]) or body.get("start_node_id") or body.get("row_source"):
        return _start_scoped(conn, me, slug, key, body, value, saved["revision"])
    _check_tabs(conn, slug, value)
    if rows:
        tab_keys = [target_tab] if target_tab else list({n["target"].get("tab_key") for n in value["nodes"] if n["target"].get("tab_key")})
        if not tab_keys:
            raise ExecutionError(400, "單列／批次執行需要 target_tab 或節點的 target.tab_key")
        known = set()
        for target_key in tab_keys:
            tab = repo.get_tab(conn, slug, target_key)
            for table in tab["doc"].get("content", []):
                if table.get("type") == "table":
                    known.update(r.get("attrs", {}).get("bid") for r in table.get("content", [])[_header_offset(table):])
        if not set(rows) <= known:
            raise ExecutionError(400, "選取列已不存在，請重新讀取表格")
    workers = limbs.connected_workers(conn, slug)
    for node in value["nodes"]:
        if not any(node["capability"] in w["capabilities"] and (not node.get("limb_id") or node["limb_id"] == w["id"]) for w in workers):
            raise ExecutionError(409, f"尚未連接 {node['capability']} 手腳；請先註冊並啟動對應 Worker")
    for row_id in rows or [""]:
        for node in value["nodes"]:
            target = dict(node["target"])
            if row_id and target.get("tab_key"):
                target["row_id"] = row_id
            _check_cell_target(conn, slug, target)
    identifier = str(uuid.uuid4())
    roots = set(ready_nodes(value, {}))
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO projectops.flow_run(id,project_slug,tab_key,definition,definition_revision,created_by)
                       VALUES(%s,%s,%s,%s::jsonb,%s,%s)""", (identifier, slug, key, json.dumps(value), saved["revision"], me.actor_id))
        for row_id in rows or [""]:
            for node in value["nodes"]:
                target = copy.deepcopy(node["target"])
                if row_id and target.get("tab_key"):
                    target["row_id"] = row_id
                cur.execute("""INSERT INTO projectops.limb_task(id,run_id,project_slug,node_id,row_id,capability,assigned_limb,status,target)
                               VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                            (str(uuid.uuid4()), identifier, slug, node["id"], row_id, node["capability"], node.get("limb_id") or None,
                             "queued" if node["id"] in roots else "blocked", json.dumps(target)))
    repo.add_audit(conn, slug, action="flow_start", actor_id=me.actor_id, tab_key=key, target=identifier, detail={"rows": rows})
    return detail(conn, slug, key, identifier)


def _advance(conn, run):
    """Caller holds run lock; approval and all predecessors gate downstream tasks."""
    if run.get("execution", {}).get("version") == 1:
        return _advance_scoped(conn, run)
    tasks = _fetch_tasks(conn, run["id"])
    if run["status"] == "canceled":
        return
    groups = {}
    for task in tasks:
        groups.setdefault(task["row_id"], {})[task["node_id"]] = task["status"]
    with conn.cursor() as cur:
        for row_id, statuses in groups.items():
            ready = ready_nodes(run["definition"], statuses)
            if ready:
                cur.execute("UPDATE projectops.limb_task SET status='queued',updated_at=NOW() WHERE run_id=%s AND row_id=%s AND node_id=ANY(%s) AND status='blocked'", (run["id"], row_id, ready))
        states = [t["status"] for t in _fetch_tasks(conn, run["id"])]
        if all(s == "succeeded" for s in states):
            status = "succeeded"
        elif any(s == "failed" for s in states) and not any(s in ("running", "queued", "awaiting_approval") for s in states):
            status = "failed"
        elif any(s in ("running", "queued") for s in states):
            status = "running"
        elif "awaiting_approval" in states:
            status = "awaiting_approval"
        else:
            status = "failed"
        cur.execute("UPDATE projectops.flow_run SET status=%s,updated_at=NOW() WHERE id=%s", (status, run["id"]))


def _header_offset(table):
    rows = table.get("content", [])
    return int(bool(rows and rows[0].get("content") and all(c.get("type") == "tableHeader" for c in rows[0]["content"])))


def _table_data(doc, values):
    """Stable coordinates and rendered values; never expose the private source blob."""
    tables = []
    simple = {fid: v.get("value", "") if isinstance(v, dict) else v for fid, v in values.items()}
    def text(node):
        kind, attrs = node.get("type"), node.get("attrs", {})
        if kind == "text":
            return node.get("text", "")
        if kind in ("fill", "status"):
            return str(simple.get(attrs.get("fid"), attrs.get("label", "")))
        if kind == "image":
            return attrs.get("src", "")
        if kind == "hardBreak":
            return "\n"
        return "".join(text(c) for c in node.get("content", []))
    for table in doc.get("content", []):
        if table.get("type") != "table":
            continue
        rows = table.get("content", [])
        def cells(row):
            return [text(c) for c in row.get("content", [])]
        offset = _header_offset(table)
        headers = cells(rows[0]) if offset else [f"欄 {i + 1}" for i in range(len(rows[0].get("content", [])))] if rows else []
        tables.append({"table_id": table.get("attrs", {}).get("bid"), "headers": headers, "column_ids": column_ids(table),
                       "rows": [{"row_id": r.get("attrs", {}).get("bid"), "cells": cells(r)} for r in rows[offset:]]})
    return tables


def _source_rows(conn, slug, source):
    tab = repo.get_tab(conn, slug, source["tab_key"])
    if not tab:
        raise ExecutionError(409, "列來源分頁已刪除")
    tables = _table_data(tab["doc"], repo.field_values(conn, slug).get(source["tab_key"], {}))
    if source.get("table_id"):
        tables = [t for t in tables if t["table_id"] == source["table_id"]]
    if not tables:
        raise ExecutionError(409, "列來源找不到表格")
    statuses = source.get("status", [])
    if isinstance(statuses, str):
        statuses = [statuses]
    result = []
    for table in tables:
        for row in table["rows"]:
            cells = row["cells"]
            # Without a column, match any rendered cell (including status capsules).
            candidates = [cells[source["status_col"]]] if "status_col" in source and source["status_col"] < len(cells) else cells if "status_col" not in source else []
            if not statuses or any(c in statuses for c in candidates):
                result.append(dict(row, table_id=table["table_id"], tab_key=source["tab_key"]))
    return result


def _start_scoped(conn, me, slug, key, body, value, revision):
    start_node = body.get("start_node_id")
    active = {n["id"] for n in value["nodes"]}
    if start_node:
        if not isinstance(start_node, str) or start_node not in active:
            raise ExecutionError(400, "start_node_id 不存在")
        active = {start_node}
        while True:
            grown = active | {e["target"] for e in value["edges"] if e["source"] in active}
            if grown == active:
                break
            active = grown
    _check_tabs(conn, slug, {"nodes": [n for n in value["nodes"] if n["id"] in active]})
    source = body.get("row_source")
    if source is not None:
        try:
            _validate_source(source)
        except ValueError as exc:
            raise ExecutionError(400, str(exc)) from exc
    rows = body.get("row_ids", [])
    selection_tabs = []
    if rows:
        sources = [source] if source else [n["row_source"] for n in value["nodes"] if n["id"] in active and n.get("row_source")]
        if not sources:
            keys = [body["target_tab"]] if body.get("target_tab") else [n["target"]["tab_key"] for n in value["nodes"] if n["id"] in active and n["target"].get("tab_key")]
            sources = [{"tab_key": k} for k in keys]
        known = {r["row_id"] for s in sources for r in _source_rows(conn, slug, {k: v for k, v in s.items() if k not in ("status", "status_col")})}
        if not set(rows) <= known:
            raise ExecutionError(400, "選取列已不存在，請重新讀取表格")
        selection_tabs = list(dict.fromkeys(s["tab_key"] for s in sources))
    workers = limbs.connected_workers(conn, slug)
    for node in value["nodes"]:
        if node["id"] not in active:
            continue
        if not any(node["capability"] in w["capabilities"] and (not node.get("limb_id") or node["limb_id"] == w["id"]) for w in workers):
            raise ExecutionError(409, f"尚未連接 {node['capability']} 手腳；請先註冊並啟動對應 Worker")
        if node.get("scope") != "rows":
            _check_cell_target(conn, slug, node["target"])
    execution = {"version": 1, "active_nodes": [n["id"] for n in value["nodes"] if n["id"] in active],
                 "row_ids": rows, "row_source": source, "selection_tabs": selection_tabs,
                 "expanded": {}, "row_sets": {}, "errors": {}}
    identifier = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO projectops.flow_run(id,project_slug,tab_key,definition,definition_revision,created_by,execution)
                       VALUES(%s,%s,%s,%s::jsonb,%s,%s,%s::jsonb)""", (identifier, slug, key, json.dumps(value), revision, me.actor_id, json.dumps(execution)))
    _advance(conn, _get_run(conn, identifier, lock=True))
    repo.add_audit(conn, slug, action="flow_start", actor_id=me.actor_id, tab_key=key, target=identifier,
                   detail={"rows": rows, "start_node_id": start_node})
    return detail(conn, slug, key, identifier)


def _advance_scoped(conn, run):
    """Persist each expansion under the run lock, including the empty-set case.

    Stage barriers ensure new rows are read only after approved upstream writes.
    Independent branches run concurrently; aggregate nodes always run once.
    """
    if run["status"] == "canceled":
        return
    state = run["execution"]
    active, expanded = set(state["active_nodes"]), state["expanded"]
    tasks = _fetch_tasks(conn, run["id"])
    by_node = {}
    for task in tasks:
        by_node.setdefault(task["node_id"], []).append(task)
    with conn.cursor() as cur:
        changed = True
        while changed:
            changed = False
            for node in run["definition"]["nodes"]:
                nid = node["id"]
                if nid not in active:
                    continue
                parents = {e["source"] for e in run["definition"]["edges"] if e["target"] == nid and e["source"] in active}
                if not all(p in expanded and all(t["status"] == "succeeded" for t in by_node.get(p, [])) for p in parents):
                    continue
                if nid in expanded:
                    # Retried failed/canceled tasks retain the frozen expansion set.
                    cur.execute("UPDATE projectops.limb_task SET status='queued',updated_at=NOW() WHERE run_id=%s AND node_id=%s AND status='blocked'", (run["id"], nid))
                    continue
                try:
                    if node.get("scope") == "rows" or (node.get("scope") == "aggregate" and (state.get("row_source") or node.get("row_source"))):
                        source = state.get("row_source") or node["row_source"]
                        source_key = json.dumps(source, sort_keys=True, ensure_ascii=False)
                        if source_key not in state["row_sets"]:
                            candidates = _source_rows(conn, run["project_slug"], source)
                            selected = set(state["row_ids"])
                            candidates = [r["row_id"] for r in candidates if not selected or r["row_id"] in selected]
                            if len(candidates) > 200:
                                raise ExecutionError(400, "逐列執行最多 200 列，請使用狀態篩選或選取列")
                            state["row_sets"][source_key] = candidates
                        row_ids = state["row_sets"][source_key] if node.get("scope") == "rows" else [""]
                    elif node.get("scope") in ("once", "aggregate"):
                        row_ids = [""]
                    else:
                        row_ids = state["row_ids"] or [""]
                    for rid in row_ids:
                        target = dict(node["target"])
                        if rid and target.get("tab_key") and target.get("kind") != "doc":
                            target["row_id"] = rid
                        _check_cell_target(conn, run["project_slug"], target)
                    expanded[nid] = list(row_ids)
                    by_node[nid] = []
                    for rid in row_ids:
                        target = dict(node["target"])
                        if rid and target.get("tab_key") and target.get("kind") != "doc":
                            target["row_id"] = rid
                        cur.execute("""INSERT INTO projectops.limb_task(id,run_id,project_slug,node_id,row_id,capability,assigned_limb,status,target)
                                       VALUES(%s,%s,%s,%s,%s,%s,%s,'queued',%s::jsonb)
                                       ON CONFLICT(run_id,node_id,row_id) DO NOTHING""",
                                    (str(uuid.uuid4()), run["id"], run["project_slug"], nid, rid, node["capability"], node.get("limb_id") or None, json.dumps(target)))
                        by_node[nid].append({"status": "queued"})
                    state["errors"].pop(nid, None)
                    changed = True
                except ExecutionError as exc:
                    state["errors"][nid] = str(exc)
        states = [t["status"] for t in _fetch_tasks(conn, run["id"])]
        if any(s in ("running", "queued") for s in states):
            status = "running"
        elif "awaiting_approval" in states:
            status = "awaiting_approval"
        elif not state["errors"] and active <= expanded.keys() and all(s == "succeeded" for s in states):
            status = "succeeded"
        else:
            status = "failed"
        cur.execute("UPDATE projectops.flow_run SET status=%s,execution=%s::jsonb,updated_at=NOW() WHERE id=%s", (status, json.dumps(state), run["id"]))


def _recover(conn, run):
    with conn.cursor() as cur:
        cur.execute("""UPDATE projectops.limb_task SET status=CASE WHEN attempts < max_attempts THEN 'queued' ELSE 'failed' END,
                       error='Worker 租約到期',lease_hash=NULL,lease_until=NULL,updated_at=NOW()
                       WHERE run_id=%s AND status='running' AND lease_until<=NOW()""", (run["id"],))
    _advance(conn, run)


def list_runs(conn, slug, key):
    if not repo.get_tab(conn, slug, key):
        raise ExecutionError(404, "找不到分頁")
    with conn.cursor() as cur:
        cur.execute(f"SELECT {_RUN_COLUMNS} FROM projectops.flow_run WHERE project_slug=%s AND tab_key=%s ORDER BY created_at DESC LIMIT 50", (slug, key))
        return {"runs": [_run(row) for row in cur.fetchall()]}


def recent_tasks(conn, slug, target_tab=None):
    if not repo.get_project(conn, slug):
        raise ExecutionError(404, "找不到專案")
    with conn.cursor() as cur:
        cur.execute(f"""SELECT {_TASK_COLUMNS} FROM projectops.limb_task
                        WHERE project_slug=%s AND (%s::text IS NULL OR target->>'tab_key'=%s)
                        ORDER BY created_at DESC LIMIT 200""", (slug, target_tab, target_tab))
        tasks = [_task(row) for row in cur.fetchall()]
    for task in tasks:
        task["row_id"] = task["row_id"] or task["target"].get("row_id", "")
    return {"tasks": tasks}


def detail(conn, slug, key, identifier):
    run = _get_run(conn, identifier, slug, key, lock=True)
    if run["status"] not in ("canceled", "succeeded", "failed"):
        _recover(conn, run)
    return {"run": _get_run(conn, identifier), "tasks": _fetch_tasks(conn, identifier)}


def control(conn, me, slug, key, identifier, action):
    _write_permission(me)
    run = _get_run(conn, identifier, slug, key, lock=True)
    if run["created_by"] != me.actor_id and me.role != "admin":
        raise ExecutionError(403, "只有發起人或管理者能控制此工作流")
    with conn.cursor() as cur:
        if action == "cancel":
            cur.execute("UPDATE projectops.limb_task SET status='canceled',lease_hash=NULL,lease_until=NULL,updated_at=NOW() WHERE run_id=%s AND status IN ('blocked','queued','running','awaiting_approval')", (identifier,))
            cur.execute("UPDATE projectops.assistant_proposal SET status='dismissed',decided_at=NOW(),decided_by=%s WHERE id IN (SELECT proposal_id FROM projectops.limb_task WHERE run_id=%s AND proposal_id IS NOT NULL) AND status='pending'", (me.actor_id, identifier))
            cur.execute("UPDATE projectops.flow_run SET status='canceled',updated_at=NOW() WHERE id=%s", (identifier,))
        else:
            if run["status"] not in ("failed", "canceled"):
                raise ExecutionError(409, "只能重試失敗或取消的執行")
            cur.execute("""UPDATE projectops.limb_task SET status='blocked',attempts=0,error=NULL,lease_hash=NULL,lease_until=NULL,
                           proposal_id=NULL,target_snapshot=NULL,output=NULL,updated_at=NOW()
                           WHERE run_id=%s AND status IN ('failed','canceled','blocked')""", (identifier,))
            cur.execute("UPDATE projectops.flow_run SET status='queued',updated_at=NOW() WHERE id=%s", (identifier,))
            run["status"] = "queued"
            _advance(conn, run)
    return detail(conn, slug, key, identifier)


def _creator(conn, run):
    member = next((m for m in repo.active_members(conn) if m["actor_id"] == run["created_by"]), None)
    if not member or member["role"] == "viewer":
        raise ExecutionError(403, "執行發起人的權限已停用或變更，結果不能寫入")
    return service.Identity(member["actor_id"], member["name"], member["role"])


def _snapshot(conn, slug, target):
    if not target.get("tab_key"):
        return None
    tab = repo.get_tab(conn, slug, target["tab_key"])
    if not tab:
        raise ExecutionError(409, "輸出分頁已刪除")
    return {"doc": tab["doc"], "revision": tab["revision"], "title": tab["title"],
            "values": repo.field_values(conn, slug).get(target["tab_key"], {})}


def _inputs(conn, run, task, node):
    from project_assistant.tools import render_doc
    values = repo.field_values(conn, run["project_slug"])
    inputs = []
    state = run.get("execution", {})
    source = state.get("row_source") or node.get("row_source")
    aggregate_ids = None
    if node.get("scope") == "aggregate" and source:
        aggregate_ids = set(state.get("row_sets", {}).get(json.dumps(source, sort_keys=True, ensure_ascii=False), []))
    keys = list(dict.fromkeys(node["input_tabs"] + ([source["tab_key"]] if source else [])))
    mode = privacy.mode(conn, run["project_slug"])
    structured_rows = []
    selected_aggregate_tabs = set(state.get("selection_tabs", [])) if node.get("scope") == "aggregate" and state.get("row_ids") else set()
    for key in keys:
        tab = repo.get_tab(conn, run["project_slug"], key)
        if not tab:
            raise ExecutionError(409, f"輸入分頁 {key} 已刪除")
        simple = {fid: v.get("value", "") if isinstance(v, dict) else v for fid, v in values.get(key, {}).items()}
        doc = copy.deepcopy(tab["doc"])
        if aggregate_ids is not None and key == source["tab_key"]:
            for table in doc.get("content", []):
                if table.get("type") == "table":
                    matches_table = not source.get("table_id") or table.get("attrs", {}).get("bid") == source["table_id"]
                    table["content"] = [r for i, r in enumerate(table.get("content", []))
                                        if (i == 0 and _header_offset(table)) or (matches_table and r.get("attrs", {}).get("bid") in aggregate_ids)]
        elif node.get("scope") == "aggregate" and state.get("row_ids") and key in state.get("selection_tabs", []):
            selected_ids = set(state["row_ids"])
            for table in doc.get("content", []):
                if table.get("type") == "table":
                    table["content"] = [r for i, r in enumerate(table.get("content", []))
                                        if (i == 0 and _header_offset(table)) or r.get("attrs", {}).get("bid") in selected_ids]
        # A row id belongs to its source/target table, not every reference tab.
        if task["row_id"] and (key == task["target"].get("tab_key") or key == (source or {}).get("tab_key")):
            for table in doc.get("content", []):
                if table.get("type") == "table":
                    table["content"] = [r for i, r in enumerate(table.get("content", [])) if (i == 0 and _header_offset(table)) or r.get("attrs", {}).get("bid") == task["row_id"]]
        tables = _table_data(doc, values.get(key, {}))
        for table in tables:
            table["headers"] = privacy.sanitize(table["headers"], mode)
            for row in table["rows"]:
                row["cells"] = privacy.sanitize(row["cells"], mode)
                is_source = (key == source["tab_key"] and (not source.get("table_id") or source["table_id"] == table["table_id"])) if source else (not selected_aggregate_tabs or key in selected_aggregate_tabs)
                if is_source:
                    structured_rows.append(dict(row, tab_key=key, table_id=table["table_id"]))
        inputs.append({"tab_key": key, "title": tab["title"], "revision": tab["revision"], "text": render_doc(doc, simple), "tables": tables})
    predecessors = {e["source"] for e in run["definition"]["edges"] if e["target"] == node["id"]}
    scoped = state.get("version") == 1
    parent_tasks = [t for t in _fetch_tasks(conn, run["id"]) if t["node_id"] in predecessors
                    and (not task["row_id"] or not t["row_id"] or t["row_id"] == task["row_id"]) and t["status"] == "succeeded"]
    if state.get("row_sets"):
        order = list(dict.fromkeys(r for rows in state["row_sets"].values() for r in rows))
    else:
        selected = set(state.get("row_ids", []))
        order = [r["row_id"] for r in structured_rows if r["row_id"] in selected] if selected else []
    rank = {rid: index for index, rid in enumerate(order)}
    node_rank = {n["id"]: i for i, n in enumerate(run["definition"]["nodes"])}
    parent_tasks.sort(key=lambda t: (rank.get(t["row_id"], -1), node_rank[t["node_id"]]))
    predecessor_tasks = [{"node_id": t["node_id"], "row_id": t["row_id"],
                          "output": _sanitize_output(conn, run["project_slug"], t["output"] or {}, mode)} for t in parent_tasks]
    results = {}
    for t in predecessor_tasks:
        if scoped and not task["row_id"] and t["row_id"]:
            results.setdefault(t["node_id"], []).append({"row_id": t["row_id"], "output": t["output"]})
        else:
            results[t["node_id"]] = t["output"]
    if scoped and not task["row_id"] and (state.get("row_sets") or state.get("row_ids")):
        structured_rows = [r for r in structured_rows if r["row_id"] in rank]
        structured_rows.sort(key=lambda r: rank[r["row_id"]])
    if source and task["row_id"] and not any(r["row_id"] == task["row_id"] for r in structured_rows):
        raise ExecutionError(409, "輸入列已刪除，請重新選取列")
    # Preserve ids/coordinates, but sanitize every model-visible prompt, tab value and predecessor result.
    for tab in inputs:
        tab["title"] = privacy.sanitize(tab["title"], mode)
        tab["text"] = privacy.sanitize(tab["text"], mode)
    target_tab = repo.get_tab(conn, run["project_slug"], task["target"]["tab_key"]) if task["target"].get("tab_key") else None
    target_tables = [{"table_id": t["table_id"], "headers": privacy.sanitize(t["headers"], mode)}
                     for t in _table_data(target_tab["doc"], {})] if target_tab else []
    return {"prompt": privacy.sanitize(node["prompt"], mode), "tabs": inputs, "scope": node.get("scope", "legacy"),
            "row_id": task["row_id"], "rows": structured_rows, "target": task["target"],
            "target_tables": target_tables, "predecessors": results, "predecessor_tasks": predecessor_tasks}


def _sanitize_output(conn, slug, original, mode):
    output = privacy.sanitize(original, mode)
    if "asset_url" in original:
        url = original["asset_url"]
        prefix = f"/projects/api/{slug}/assets/"
        identifier = url[len(prefix):] if isinstance(url, str) and url.startswith(prefix) else ""
        if not re.fullmatch(r"pa_[0-9a-f]{32}", identifier) or not repo.get_asset(conn, slug, identifier):
            raise ExecutionError(400, "asset_url 必須指向已上傳至本專案的媒體")
        output["asset_url"] = url
    if "table_id" in original:
        if not isinstance(original["table_id"], str) or not _ID.fullmatch(original["table_id"]):
            raise ExecutionError(400, "table_id 無效")
        output["table_id"] = original["table_id"]
    if isinstance(original.get("row_edits"), list):
        for before, after in zip(original["row_edits"], output["row_edits"]):
            if isinstance(before, dict) and isinstance(after, dict) and "row_id" in before:
                if not isinstance(before["row_id"], str) or not _ID.fullmatch(before["row_id"]):
                    raise ExecutionError(400, "row_id 無效")
                after["row_id"] = before["row_id"]
    return output


def _source_context(payload, task, node, execution):
    """Keep the row label from the exact sanitized input claimed by the worker."""
    if not task.get("row_id"):
        return None
    source = execution.get("row_source") or node.get("row_source") or task.get("target") or {}
    rows = [row for row in payload.get("rows", []) if row["row_id"] == task["row_id"]
            and (not source.get("tab_key") or row["tab_key"] == source["tab_key"])
            and (not source.get("table_id") or row["table_id"] == source["table_id"])]
    if len(rows) != 1:
        return None
    row = rows[0]
    tab = next((item for item in payload.get("tabs", []) if item["tab_key"] == row["tab_key"]), {})
    return {"tab_key": row["tab_key"], "table_id": row["table_id"], "row_id": row["row_id"],
            "title": tab.get("title", row["tab_key"]), "revision": tab.get("revision"),
            "cells": copy.deepcopy(row.get("cells", [])[:2])}


def claim(conn, worker):
    with conn.cursor() as cur:
        cur.execute(f"""SELECT {_RUN_COLUMNS} FROM projectops.flow_run WHERE status IN ('queued','running','awaiting_approval')
                        AND project_slug=ANY(%s) ORDER BY created_at FOR UPDATE SKIP LOCKED""", (worker["allowed_projects"],))
        runs = [_run(row) for row in cur.fetchall()]
    for run in runs:
        _recover(conn, run)
        with conn.cursor() as cur:
            cur.execute(f"""SELECT {_TASK_COLUMNS} FROM projectops.limb_task WHERE run_id=%s AND status='queued'
                            AND capability=ANY(%s) AND (assigned_limb IS NULL OR assigned_limb=%s)
                            ORDER BY created_at,node_id,row_id FOR UPDATE SKIP LOCKED LIMIT 1""",
                        (run["id"], worker["capabilities"], worker["id"]))
            row = cur.fetchone()
            if not row:
                continue
            task = _task(row)
            node = next(n for n in run["definition"]["nodes"] if n["id"] == task["node_id"])
            try:
                _creator(conn, run)
                if run.get("execution", {}).get("mode") == "single_step":
                    _check_source_revisions(conn, run["project_slug"], run["execution"]["source_revisions"])
                snapshot = _snapshot(conn, run["project_slug"], task["target"])
                payload = _inputs(conn, run, task, node)
                context = _source_context(payload, task, node, run.get("execution", {}))
                if context:
                    snapshot = dict(snapshot or {}, _source_context=context)
            except ExecutionError as exc:
                cur.execute("UPDATE projectops.limb_task SET status='failed',error=%s,updated_at=NOW() WHERE id=%s", (str(exc), task["id"]))
                _advance(conn, run)
                continue
            token = secrets.token_urlsafe(32)
            cur.execute(f"""UPDATE projectops.limb_task SET status='running',attempts=attempts+1,limb_id=%s,lease_hash=%s,
                            lease_until=NOW()+(%s * INTERVAL '1 second'),target_snapshot=%s::jsonb,error=NULL,updated_at=NOW()
                            WHERE id=%s RETURNING {_TASK_COLUMNS}""",
                        (worker["id"], limbs.token_hash(token), limbs.LEASE_SECONDS, json.dumps(snapshot), task["id"]))
            task = _task(cur.fetchone())
            task["lease_token"], task["input"] = token, payload
            cur.execute("UPDATE projectops.flow_run SET status='running',updated_at=NOW() WHERE id=%s", (run["id"],))
            return {"task": task, "lease_seconds": limbs.LEASE_SECONDS}
    return {"task": None, "retry_after": 3}


def leased_task(conn, worker, identifier, token):
    with conn.cursor() as cur:
        cur.execute("SELECT run_id FROM projectops.limb_task WHERE id=%s", (identifier,))
        row = cur.fetchone()
    if not row:
        raise ExecutionError(404, "找不到任務")
    run = _get_run(conn, str(row[0]), lock=True)
    if run["project_slug"] not in worker["allowed_projects"]:
        raise ExecutionError(403, "Worker 無權存取此專案")
    with conn.cursor() as cur:
        cur.execute(f"SELECT {_TASK_COLUMNS} FROM projectops.limb_task WHERE id=%s FOR UPDATE", (identifier,))
        task = _task(cur.fetchone(), private=True)
        cur.execute("SELECT NOW()")
        now = cur.fetchone()[0]
    limbs.check_lease(task, worker["id"], token, now)
    return run, task


def renew(conn, worker, body):
    run, task = leased_task(conn, worker, body.get("task_id"), body.get("lease_token"))
    with conn.cursor() as cur:
        cur.execute("UPDATE projectops.limb_task SET lease_until=NOW()+(%s * INTERVAL '1 second'),updated_at=NOW() WHERE id=%s RETURNING lease_until", (limbs.LEASE_SECONDS, task["id"]))
        until = cur.fetchone()[0]
    return {"task_id": task["id"], "lease_until": repo._iso(until)}


def _result_target(conn, run, task, output):
    target, snapshot = task["target"], task["target_snapshot"]
    if not target.get("tab_key"):
        return None, ""
    if not snapshot:
        raise ExecutionError(409, "任務缺少輸出分頁快照，請重試")
    if target.get("kind") == "doc":
        from project_docs.doc_schema import new_id, safe_href
        text = output.get("text", "")
        if not isinstance(text, str):
            raise ExecutionError(400, "文件輸出需要 text")
        asset_url = safe_href(output["asset_url"]) if output.get("asset_url") else None
        if output.get("asset_url") and not asset_url:
            raise ExecutionError(400, "文件媒體連結無效")
        preview = text + (("\n\n" if text else "") + f"[產出媒體]({asset_url})" if asset_url else "")
        if not preview.strip() or len(preview) > 100000:
            raise ExecutionError(400, "文件輸出需要 1～100000 字")
        before = snapshot["doc"].get("content", [])
        ops = []
        if target.get("mode", "append") == "replace":
            ops = [{"op": "del", "bid": b["attrs"]["bid"], "base": b} for b in before]
            previous = None
        else:
            previous = before[-1].get("attrs", {}).get("bid") if before else None
        paragraphs = [[{"type": "text", "text": line}] if line else [] for line in text.splitlines()]
        if asset_url:
            paragraphs.append([{"type": "text", "text": "產出媒體", "marks": [{"type": "link", "attrs": {"href": asset_url}}]}])
        for content in paragraphs:
            bid = new_id("b")
            ops.append({"op": "put", "bid": bid, "base": None, "after": previous,
                        "node": {"type": "paragraph", "attrs": {"bid": bid},
                                 "content": content}})
            previous = bid
        if len(ops) > 200:
            raise ExecutionError(400, "文件輸出最多 200 個區塊操作，請縮短段落數")
        return {"tab_key": target["tab_key"], "tab_title": snapshot["title"], "display": snapshot["title"],
                "ops": ops, "field_edits": [], "expected_revision": snapshot["revision"]}, preview
    if target.get("row_id") and "col_index" in target:
        text = output.get("asset_url") if "asset_url" in output else output.get("text")
        if not isinstance(text, (str, int, float)):
            raise ExecutionError(400, "儲存格輸出需要 text 或已上傳的 asset_url")
        if "asset_url" in output:
            prefix = f"/projects/api/{run['project_slug']}/assets/"
            asset_id = str(text)[len(prefix):] if str(text).startswith(prefix) else ""
            if not re.fullmatch(r"pa_[0-9a-f]{32}", asset_id) or not repo.get_asset(conn, run["project_slug"], asset_id):
                raise ExecutionError(400, "asset_url 必須指向已上傳至本專案的媒體")
            mime, _ = repo.get_asset(conn, run["project_slug"], asset_id)
            kind = mime.split("/", 1)[0]
            text = f"![圖片]({text})" if kind == "image" else f"[{kind}]({text})"
        row_edits, new_rows = [{"row_id": target["row_id"], "cells": {str(target["col_index"]): text}}], []
    else:
        row_edits, new_rows = output.get("row_edits", []), output.get("new_rows", [])
        # A selected-row run cannot write other rows or append unrelated rows.
        if task["row_id"] and (new_rows or any(e.get("row_id") != task["row_id"] for e in row_edits if isinstance(e, dict))):
            raise ExecutionError(400, "批次任務只能寫入自己選取的列")
    try:
        ops, fields, preview = table_edits.prepare(snapshot["doc"], row_edits, new_rows, snapshot["values"], output.get("table_id"))
    except ValueError as exc:
        raise ExecutionError(400, str(exc)) from exc
    return {"tab_key": target["tab_key"], "tab_title": snapshot["title"], "display": snapshot["title"],
            "ops": ops, "field_edits": fields,
            **({"expected_revision": snapshot["revision"]} if new_rows else {})}, preview


def complete(conn, worker, body):
    run, task = leased_task(conn, worker, body.get("task_id"), body.get("lease_token"))
    output = body.get("output")
    if isinstance(output, str):
        output = {"text": output}
    try:
        size = len(json.dumps(output, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ExecutionError(400, "output 必須是有效的 JSON（數字不得是 NaN 或 Infinity）") from exc
    if not isinstance(output, dict) or size > 2 * 1024 * 1024:
        raise ExecutionError(400, "output 必須是 JSON 物件，最多 2 MB")
    me = _creator(conn, run)
    if run.get("execution", {}).get("mode") == "single_step":
        _check_source_revisions(conn, run["project_slug"], run["execution"]["source_revisions"])
    output = _sanitize_output(conn, run["project_slug"], output, privacy.mode(conn, run["project_slug"]))
    node = next(n for n in run["definition"]["nodes"] if n["id"] == task["node_id"])
    target, preview = _result_target(conn, run, task, output)
    if target and run.get("execution", {}).get("mode") == "single_step":
        target["source_revisions"] = run["execution"]["source_revisions"]
    proposal_id, status = None, "succeeded"
    if target:
        if node["write_mode"] == "direct":
            code, result = table_edits.apply(conn, me, run["project_slug"], target)
            if code >= 400:
                raise ExecutionError(code, result.get("error", "結果寫入失敗"))
        else:
            proposal_id = store.create_proposal(conn, run["project_slug"], me.actor_id, None, "table_edit", target, preview)
            status = "awaiting_approval"
    with conn.cursor() as cur:
        cur.execute("""UPDATE projectops.limb_task SET status=%s,output=%s::jsonb,proposal_id=%s,lease_hash=NULL,
                       lease_until=NULL,updated_at=NOW() WHERE id=%s""", (status, json.dumps(output), proposal_id, task["id"]))
    _advance(conn, run)
    return {"task_id": task["id"], "status": status, "proposal_id": proposal_id}


def fail(conn, worker, body):
    run, task = leased_task(conn, worker, body.get("task_id"), body.get("lease_token"))
    error = privacy.sanitize(str(body.get("error") or "Worker 執行失敗")[:2000], privacy.mode(conn, run["project_slug"]))
    status = "queued" if body.get("retryable", True) and task["attempts"] < task["max_attempts"] else "failed"
    with conn.cursor() as cur:
        cur.execute("UPDATE projectops.limb_task SET status=%s,error=%s,lease_hash=NULL,lease_until=NULL,updated_at=NOW() WHERE id=%s", (status, error, task["id"]))
    _advance(conn, run)
    return {"task_id": task["id"], "status": status}


def proposal_decided(conn, proposal_id, applied):
    """Call inside the same transaction as ProposalCard apply/dismiss/failure."""
    with conn.cursor() as cur:
        cur.execute("SELECT run_id FROM projectops.limb_task WHERE proposal_id=%s", (proposal_id,))
        row = cur.fetchone()
    if not row:
        return
    run = _get_run(conn, str(row[0]), lock=True)
    with conn.cursor() as cur:
        cur.execute("""UPDATE projectops.limb_task SET status=%s,error=%s,updated_at=NOW()
                       WHERE proposal_id=%s AND status='awaiting_approval'""",
                    ("succeeded" if applied else "failed", None if applied else "輸出提案未通過審核", proposal_id))
    _advance(conn, run)
