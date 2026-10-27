"""Transactional DAG scheduler, immutable run snapshots, and reviewed result delivery."""
from __future__ import annotations

import copy
import json
import re
import secrets
import uuid

from project_assistant import camera_fidelity, limbs, local_workers, privacy, store, table_edits
from project_docs import repository as repo, service
from project_docs.doc_schema import column_ids

ExecutionError = limbs.ExecutionError
_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_RUN_COLUMNS = "id,project_slug,tab_key,definition,definition_revision,created_by,status,created_at,updated_at,execution"
_TASK_COLUMNS = "id,run_id,project_slug,node_id,row_id,capability,assigned_limb,status,attempts,max_attempts,limb_id,lease_hash,lease_until,target,target_snapshot,output,proposal_id,error,created_at,updated_at"
_TASK_KEYS = _TASK_COLUMNS.split(",")


def validate_definition(value, *, allow_empty=False):
    if not isinstance(value, dict) or not isinstance(value.get("nodes"), list) or not isinstance(value.get("edges"), list):
        raise ValueError("A pipeline requires nodes and edges arrays.")
    nodes, edges = copy.deepcopy(value["nodes"]), copy.deepcopy(value["edges"])
    if not (0 if allow_empty else 1) <= len(nodes) <= 100 or len(edges) > 1000:
        raise ValueError("A pipeline requires 1–100 nodes and at most 1,000 connections.")
    ids = set()
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not _ID.fullmatch(node["id"]) or node["id"] in ids:
            raise ValueError("Node IDs must be valid and unique.")
        ids.add(node["id"])
        if node.get("capability") not in limbs.CAPABILITIES:
            raise ValueError("Unsupported node capability.")
        node.setdefault("title", node["id"])
        if not isinstance(node["title"], str) or len(node["title"]) > 200:
            raise ValueError("Node names support up to 200 characters.")
        node.setdefault("prompt", "")
        if not isinstance(node["prompt"], str) or len(node["prompt"]) > 30000:
            raise ValueError("Node instructions support up to 30,000 characters.")
        node.setdefault("write_mode", "proposal")
        if node["write_mode"] not in ("proposal", "direct"):
            raise ValueError("write_mode must be proposal or direct.")
        node.setdefault("input_tabs", [])
        if not isinstance(node["input_tabs"], list) or len(node["input_tabs"]) > 30 or any(not isinstance(k, str) for k in node["input_tabs"]):
            raise ValueError("input_tabs must be an array of at most 30 page keys.")
        if "scope" in node and node["scope"] not in ("once", "rows", "aggregate"):
            raise ValueError("scope must be once, rows, or aggregate.")
        source = node.get("row_source")
        if node.get("scope") == "rows" and not source:
            raise ValueError("Per-row nodes require row_source.tab_key.")
        if source is not None:
            _validate_source(source)
        target = node.get("target") or {}
        if not isinstance(target, dict):
            raise ValueError("target must be an object.")
        if "col_index" in target and (type(target["col_index"]) is not int or not 0 <= target["col_index"] < 256):
            raise ValueError("col_index must be a zero-based column index.")
        if ("col_index" in target or target.get("column_id")) and not target.get("tab_key"):
            raise ValueError("Cell output requires target.tab_key.")
        for key in ("tab_key", "row_id"):
            if key in target and not isinstance(target[key], str):
                raise ValueError(f"target.{key} must be a string.")
        node["target"] = target
        if target.get("kind", "table") not in ("table", "doc") or target.get("mode", "append") not in ("append", "replace"):
            raise ValueError("target.kind must be table/doc; mode must be append/replace.")
        if target.get("kind") == "doc" and ("col_index" in target or "row_id" in target):
            raise ValueError("Document output cannot target a cell.")
        if node.get("limb_id"):
            try:
                uuid.UUID(node["limb_id"])
            except (ValueError, TypeError, AttributeError):
                raise ValueError("limb_id must be a worker UUID.") from None
        if node.get('agent_key'):
            from project_assistant.agent_registry import AGENT_KEY
            if not isinstance(node['agent_key'],str) or not AGENT_KEY.fullmatch(node['agent_key']):
                raise ValueError("Invalid agent_key.")
            if node.get('limb_id') or node['write_mode']=='direct':
                raise ValueError("An agent profile cannot also bind a worker and must use proposal review.")
        for key in ("x", "y"):
            if key in node and (type(node[key]) not in (int, float) or not -100000 <= node[key] <= 100000):
                raise ValueError("Invalid node coordinates.")
        if "primary" in node and type(node["primary"]) is not bool:
            raise ValueError("primary must be true or false.")
    # R44-7: a step marked primary is the default step of the column it writes; a column has at most one.
    marked = [node for node in nodes if node.get("primary") is True]
    for i, first in enumerate(marked):
        for second in marked[i + 1:]:
            if same_output(first["target"], second["target"]):
                raise ValueError(f"Only one step can be the default for a column: “{first['title']}” and “{second['title']}” "
                                 "both write it. Turn the default off on one of them.")
    links = set()
    for edge in edges:
        if not isinstance(edge, dict) or edge.get("source") not in ids or edge.get("target") not in ids:
            raise ValueError("A connection references a missing node.")
        link = (edge["source"], edge["target"])
        if link in links:
            raise ValueError("Duplicate connection.")
        links.add(link)
    seen = set()
    while True:
        additions = {n for n in ids - seen if all(s in seen for s, t in links if t == n)}
        if not additions:
            break
        seen.update(additions)
    if seen != ids:
        raise ValueError("The pipeline contains a cycle. Remove connections that return upstream.")
    return {**copy.deepcopy(value), "nodes": nodes, "edges": edges}


def same_output(first, second):
    """Whether two step targets write the same column: same page, a compatible worksheet (an unnamed one is the page's
    first) and the same column, by id when both name one, else by index. Documents and whole tables are never a column."""
    def cell(target):
        return isinstance(target, dict) and target.get("kind", "table") != "doc" and ("col_index" in target or bool(target.get("column_id")))
    if not (cell(first) and cell(second)) or first.get("tab_key") != second.get("tab_key"):
        return False
    if first.get("table_id") and second.get("table_id") and first["table_id"] != second["table_id"]:
        return False
    if first.get("column_id") and second.get("column_id"):
        return first["column_id"] == second["column_id"]
    return "col_index" in first and "col_index" in second and first["col_index"] == second["col_index"]


def _validate_source(source):
    if not isinstance(source, dict) or not isinstance(source.get("tab_key"), str) or not source["tab_key"]:
        raise ValueError("row_source requires tab_key.")
    if "table_id" in source and (not isinstance(source["table_id"], str) or not _ID.fullmatch(source["table_id"])):
        raise ValueError("Invalid row_source.table_id.")
    if "status_col" in source and (type(source["status_col"]) is not int or not 0 <= source["status_col"] < 256):
        raise ValueError("status_col must be a zero-based column index.")
    statuses = source.get("status", [])
    if isinstance(statuses, str):
        statuses = [statuses]
    if not isinstance(statuses, list) or len(statuses) > 30 or any(not isinstance(s, str) or not s for s in statuses):
        raise ValueError("status must be a string or an array of statuses.")


def ready_nodes(definition, statuses):
    return [n["id"] for n in definition["nodes"] if statuses.get(n["id"], "blocked") == "blocked"
            and all(statuses.get(e["source"]) == "succeeded" for e in definition["edges"] if e["target"] == n["id"])]


def _write_permission(me):
    if not getattr(me, "can_write", me.role != "viewer"):
        raise ExecutionError(403, "Viewers cannot edit or run pipelines.")


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
        if isinstance(value.get("output"), dict):
            value["output"].pop("provenance", None)  # served only by the take bundle
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
        raise ExecutionError(404, "Run not found.")
    run = _run(row)
    if (slug and run["project_slug"] != slug) or (key and run["tab_key"] != key):
        raise ExecutionError(404, "Run not found.")
    return run


def _check_tabs(conn, slug, definition):
    for node in definition["nodes"]:
        if node.get('agent_key'):
            from project_assistant import agent_registry
            profile=agent_registry.get_agent(conn,slug,node['agent_key'])
            if not profile or not profile['enabled'] or profile['role_kind']=='observer' or node['capability'] not in profile['capabilities']:
                raise ExecutionError(400,"The node’s agent is missing, disabled, or lacks the required capability.")
        for key in node["input_tabs"] + ([node["target"]["tab_key"]] if node["target"].get("tab_key") else []) + ([node["row_source"]["tab_key"]] if node.get("row_source") else []):
            if not repo.get_tab(conn, slug, key):
                raise ExecutionError(400, f"Node {node['id']} cannot find page {key}.")
        if node.get("limb_id"):
            workers = limbs.enabled_workers(conn, slug)
            if not any(w["id"] == node["limb_id"] and node["capability"] in w["capabilities"] for w in workers):
                raise ExecutionError(400, f"The worker bound to node {node['id']} is missing, disabled, or incompatible.")
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
            raise ExecutionError(409, "The mapped column was deleted or is ambiguous. Select a named column again.")
        ref["table_id"], ref[index_key] = matches[0][0]["attrs"]["bid"], matches[0][1]


def _check_cell_target(conn, slug, target):
    if "col_index" in target and (not target.get("tab_key") or not target.get("row_id")):
        raise ExecutionError(400, "Cell output requires a page and output row. Per-row tasks require a source table.")
    if not target.get("tab_key") or not target.get("row_id"):
        return
    tab = repo.get_tab(conn, slug, target["tab_key"])
    if not tab:
        raise ExecutionError(409, "The output page was deleted.")
    row = next((r for t in tab["doc"].get("content", []) if t.get("type") == "table" and (not target.get("table_id") or t.get("attrs", {}).get("bid") == target["table_id"])
                for r in t.get("content", [])[_header_offset(t):] if r.get("attrs", {}).get("bid") == target["row_id"]), None)
    if row is None:
        raise ExecutionError(400, f"Output row {target['row_id']} does not exist in {target['tab_key']}.")
    if "col_index" in target and target["col_index"] >= len(row.get("content", [])):
        raise ExecutionError(400, "The output column is outside the table.")


def definition(conn, slug, key):
    tab = repo.get_tab(conn, slug, key)
    if not tab:
        raise ExecutionError(404, "Pipeline page not found.")
    with conn.cursor() as cur:
        cur.execute("SELECT definition,revision FROM projectops.flow_definition WHERE project_slug=%s AND tab_key=%s", (slug, key))
        row = cur.fetchone()
    return {"definition": repo._loads(row[0]) if row else {"nodes": [], "edges": []}, "revision": row[1] if row else 0}


def _node_connected(conn, slug, node, workers):
    if node.get('agent_key'):
        from project_assistant.orchestration_flow import profile_connected
        return profile_connected(conn,slug,node['agent_key'])
    # A launcher worker runs one fixed graph, so it serves only steps bound to it (see claim).
    return any(node['capability'] in w['capabilities'] and
               (node['limb_id']==w['id'] if node.get('limb_id') else not local_workers.is_local(w['id'])) for w in workers)


def save_definition(conn, me, slug, key, body):
    _write_permission(me)
    if not repo.get_tab_for_update(conn, slug, key):
        raise ExecutionError(404, "Pipeline page not found.")
    try:
        value = validate_definition(body.get("definition"), allow_empty=True)
    except ValueError as exc:
        raise ExecutionError(400, str(exc)) from exc
    _check_tabs(conn, slug, value)
    current = definition(conn, slug, key)
    if type(body.get("revision")) is not int or body["revision"] != current["revision"]:
        raise ExecutionError(409, "The pipeline changed. Reload it before saving.")
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
        raise ExecutionError(400, "source_revisions must map page keys to integer revisions.")
    for tab_key, revision in sorted(revisions.items()):
        tab = repo.get_tab_for_update(conn, slug, tab_key)
        if not tab or tab["revision"] != revision:
            raise ExecutionError(409, f"Source {tab_key} changed. Reload and review the sample.")


def preflight(conn, me, slug, key, body):
    """Read-only scope preview. It never queues work or calls a provider."""
    _write_permission(me)
    saved = definition(conn, slug, key)
    try:
        value = validate_definition(saved["definition"])
    except ValueError as exc:
        raise ExecutionError(400, "請先儲存有效工作流：" + str(exc)) from exc
    if "definition_revision" in body and body["definition_revision"] != saved["revision"]:
        raise ExecutionError(409, "The pipeline definition changed. Reload it.")
    if body.get("execution_mode", "workflow") not in ("workflow", "single_step"):
        raise ExecutionError(400, "execution_mode must be workflow or single_step.")
    single = body.get("execution_mode") == "single_step"
    if single and any(name in body for name in ("row_source", "target_tab", "row_ids", "start_node_id")):
        raise ExecutionError(400, "Single-step runs use the selected step’s source and output. Batch and continuation scopes cannot be mixed.")
    active = {n["id"] for n in value["nodes"]}
    start_id = body.get("node_id") if single else body.get("start_node_id")
    if start_id:
        if start_id not in active:
            raise ExecutionError(400, "Step not found.")
        active = {start_id}
        if not single:
            while True:
                grown = active | {e["target"] for e in value["edges"] if e["source"] in active}
                if grown == active:
                    break
                active = grown
    elif single:
        raise ExecutionError(400, "Testing a step requires node_id.")
    errors, warnings, sources, nodes = [], [], {}, []
    known_selection_rows = set()
    workers = limbs.connected_workers(conn, slug)
    all_values = repo.field_values(conn, slug)
    selected_rows = body.get("row_ids", [])
    if not isinstance(selected_rows, list) or len(selected_rows) > 200 or any(not isinstance(r, str) or not r for r in selected_rows) or len(set(selected_rows)) != len(selected_rows):
        raise ExecutionError(400, "row_ids must contain at most 200 unique row IDs.")
    for node in value["nodes"]:
        if node["id"] not in active:
            continue
        entry = {"node_id": node["id"], "title": node["title"], "scope": node.get("scope", "legacy"),
                 "row_count": 1, "row_ids": [], "write_mode": "proposal" if single else node["write_mode"],
                 "worker_connected": _node_connected(conn,slug,node,workers)}
        if node.get('agent_key'):
            entry['agent_key']=node['agent_key']
        nodes.append(entry)
        if not entry["worker_connected"]:
            errors.append({"node_id": node["id"], "message": "The worker is not connected. Configure and connect a compatible worker."})
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
                raise ExecutionError(400, "Select the current source explicitly. Single-step runs do not reuse historical upstream results.")
            if single and parents:
                if not source and not node["input_tabs"]:
                    raise ExecutionError(400, "This step has upstream dependencies but no current source. Select a source page or run the upstream steps too.")
                warnings.append({"node_id": node["id"], "message": "This run reads the selected current source only. It does not execute upstream steps or reuse historical results."})
            if not single and parents and node.get("scope") in ("rows", "aggregate"):
                entry["dynamic_rows"] = True
                warnings.append({"node_id": node["id"], "message": "The row count previews current data. Execution reads matching rows again after upstream tasks finish and are approved."})
            if source:
                known_selection_rows.update(r["row_id"] for r in _source_rows(conn, slug, {k: v for k, v in source.items() if k not in ("status", "status_col", "status_column_id")}))
                candidates = _source_rows(conn, slug, source)
                if selected_rows:
                    candidates = [r for r in candidates if r["row_id"] in selected_rows]
                if single:
                    sample_id = body.get("sample_row_id")
                    if not sample_id or not any(r["row_id"] == sample_id for r in candidates):
                        raise ExecutionError(400, "Select a sample row that still matches the source conditions.")
                    candidates = [r for r in candidates if r["row_id"] == sample_id]
                entry["row_count"] = len(candidates)
                entry["row_ids"] = [r["row_id"] for r in candidates]
                if len(candidates) > 200:
                    raise ExecutionError(400, "The source exceeds 200 rows. Filter or select a smaller scope.")
                if not candidates:
                    warnings.append({"node_id": node["id"], "message": "No rows currently match. Per-row scope will be recalculated after upstream changes are applied."})
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
                raise ExecutionError(400, "The output page does not exist.")
            entry["target"] = target
            entry["target_title"] = target_tab["title"] if target_tab else "保留結果，不寫回分頁"
            if target_tab:
                tables = _table_data(target_tab["doc"], all_values.get(target["tab_key"], {}))
                if not any(n.get("row_source") for n in value["nodes"] if n["id"] in active):
                    known_selection_rows.update(row["row_id"] for table in tables for row in table["rows"])
                table = next((t for t in tables if not target.get("table_id") or t["table_id"] == target["table_id"]), None)
                if target.get("kind") != "doc" and not table:
                    raise ExecutionError(400, "Table changes were selected, but the output page has no matching worksheet.")
                if "col_index" in target and table and target["col_index"] >= len(table["headers"]):
                    raise ExecutionError(400, "The output column no longer exists. Select a named column again.")
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
        errors.append({"node_id": nodes[0]["node_id"], "message": "Some selected rows no longer exist in the source. Return to the table and select them again."})
    return {"execution_mode": "single_step" if single else "workflow", "definition_revision": saved["revision"],
            "nodes": nodes, "sources": list(sources.values()), "source_revisions": {k: v["revision"] for k, v in sources.items()},
            "errors": errors, "warnings": warnings, "ready": not errors,
            "external_effects": "建立真實執行任務；服務可能呼叫付費模型。單步結果需核對後才寫回。" if single else "建立真實執行任務；依各步設定直接寫入或等待提案核對。"}


def _start_single_step(conn, me, slug, key, body):
    """One selected task, one frozen sample, no inherited upstream outputs."""
    if type(body.get("definition_revision")) is not int:
        raise ExecutionError(400, "Review the pipeline revision before testing this step.")
    if not repo.get_tab_for_update(conn, slug, key):
        raise ExecutionError(404, "Pipeline page not found.")
    preview = preflight(conn, me, slug, key, body)
    if preview["errors"]:
        raise ExecutionError(409, "；".join(e["message"] for e in preview["errors"]))
    if body.get("source_revisions") != preview["source_revisions"]:
        raise ExecutionError(409, "The source revision differs from the reviewed sample. Review it again.")
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
        raise ExecutionError(400, "execution_mode must be workflow or single_step.")
    if body.get("execution_mode") == "single_step":
        return _start_single_step(conn, me, slug, key, body)
    saved = definition(conn, slug, key)
    if "definition_revision" in body and body["definition_revision"] != saved["revision"]:
        raise ExecutionError(409, "The pipeline definition changed. Review the run scope again.")
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
        raise ExecutionError(400, "row_ids must contain at most 200 unique row IDs.")
    if any("scope" in n for n in value["nodes"]) or body.get("start_node_id") or body.get("row_source"):
        return _start_scoped(conn, me, slug, key, body, value, saved["revision"])
    _check_tabs(conn, slug, value)
    if rows:
        tab_keys = [target_tab] if target_tab else list({n["target"].get("tab_key") for n in value["nodes"] if n["target"].get("tab_key")})
        if not tab_keys:
            raise ExecutionError(400, "Row and batch execution require target_tab or the node’s target.tab_key.")
        known = set()
        for target_key in tab_keys:
            tab = repo.get_tab(conn, slug, target_key)
            for table in tab["doc"].get("content", []):
                if table.get("type") == "table":
                    known.update(r.get("attrs", {}).get("bid") for r in table.get("content", [])[_header_offset(table):])
        if not set(rows) <= known:
            raise ExecutionError(400, "The selected rows no longer exist. Reload the table.")
    workers = limbs.connected_workers(conn, slug)
    for node in value["nodes"]:
        if not _node_connected(conn,slug,node,workers):
            raise ExecutionError(409, f"No {node['capability']} worker is connected. Register and start a compatible worker.")
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
        raise ExecutionError(409, "The row source page was deleted.")
    tables = _table_data(tab["doc"], repo.field_values(conn, slug).get(source["tab_key"], {}))
    if source.get("table_id"):
        tables = [t for t in tables if t["table_id"] == source["table_id"]]
    if not tables:
        raise ExecutionError(409, "No table found in the row source.")
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
            raise ExecutionError(400, "start_node_id does not exist.")
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
            raise ExecutionError(400, "The selected rows no longer exist. Reload the table.")
        selection_tabs = list(dict.fromkeys(s["tab_key"] for s in sources))
    workers = limbs.connected_workers(conn, slug)
    for node in value["nodes"]:
        if node["id"] not in active:
            continue
        if not _node_connected(conn,slug,node,workers):
            raise ExecutionError(409, f"No {node['capability']} worker is connected. Register and start a compatible worker.")
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
                                raise ExecutionError(400, "Per-row execution supports up to 200 rows. Filter by status or select rows.")
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
        raise ExecutionError(404, "Page not found.")
    with conn.cursor() as cur:
        cur.execute(f"SELECT {_RUN_COLUMNS} FROM projectops.flow_run WHERE project_slug=%s AND tab_key=%s ORDER BY created_at DESC LIMIT 50", (slug, key))
        return {"runs": [_run(row) for row in cur.fetchall()]}


def recent_tasks(conn, slug, target_tab=None):
    if not repo.get_project(conn, slug):
        raise ExecutionError(404, "Production not found.")
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
    from project_assistant import orchestrator,orchestration_flow
    orchestrator.lock_project(conn,slug)
    run = _get_run(conn, identifier, slug, key, lock=True)
    if run["created_by"] != me.actor_id and me.role != "admin":
        raise ExecutionError(403, "Only the initiator or showrunner can control this pipeline.")
    with conn.cursor() as cur:
        if action == "cancel":
            cur.execute("UPDATE projectops.limb_task SET status='canceled',lease_hash=NULL,lease_until=NULL,updated_at=NOW() WHERE run_id=%s AND status IN ('blocked','queued','running','awaiting_approval')", (identifier,))
            cur.execute("UPDATE projectops.assistant_proposal SET status='dismissed',decided_at=NOW(),decided_by=%s WHERE id IN (SELECT proposal_id FROM projectops.limb_task WHERE run_id=%s AND proposal_id IS NOT NULL) AND status='pending'", (me.actor_id, identifier))
            cur.execute("UPDATE projectops.flow_run SET status='canceled',updated_at=NOW() WHERE id=%s", (identifier,))
        else:
            if run["status"] not in ("failed", "canceled"):
                raise ExecutionError(409, "Only failed or canceled runs can be retried.")
            orchestration_flow.reset_for_flow_retry(conn,slug,identifier)
            run['execution']=_get_run(conn,identifier)['execution']
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
        raise ExecutionError(403, "The initiator’s permissions changed or were disabled. The result cannot be applied.")
    return service.Identity(member["actor_id"], member["name"], member["role"])


def _snapshot(conn,slug,target):
    from project_assistant.proposal_output import snapshot_target
    return snapshot_target(conn,slug,target)


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
            raise ExecutionError(409, f"Input page {key} was deleted.")
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
        raise ExecutionError(409, "An input row was deleted. Select rows again.")
    # Preserve ids/coordinates, but sanitize every model-visible prompt, tab value and predecessor result.
    for tab in inputs:
        tab["title"] = privacy.sanitize(tab["title"], mode)
        tab["text"] = privacy.sanitize(tab["text"], mode)
    target_tab = repo.get_tab(conn, run["project_slug"], task["target"]["tab_key"]) if task["target"].get("tab_key") else None
    target_tables = [{"table_id": t["table_id"], "headers": privacy.sanitize(t["headers"], mode)}
                     for t in _table_data(target_tab["doc"], {})] if target_tab else []
    take = 0
    if task["row_id"] and task["target"].get("tab_key"):
        # Earlier outputs for this same cell: a re-shoot must not replay a locked identity seed.
        # Retry clears a task's own output, so its rejected takes are counted from their proposals.
        col = task["target"].get("col_index")
        cell_ops = json.dumps([{"rid": task["row_id"], "edited_cols": [col]}]) if col is not None else None
        with conn.cursor() as cur:
            cur.execute("""SELECT GREATEST((SELECT COUNT(*) FROM projectops.limb_task WHERE project_slug=%s AND row_id=%s
                AND target->>'tab_key'=%s AND target->>'col_index' IS NOT DISTINCT FROM %s
                AND output IS NOT NULL AND created_at<%s),
                (SELECT COUNT(*) FROM projectops.assistant_proposal WHERE %s::jsonb IS NOT NULL AND project_slug=%s
                AND action='table_edit' AND target->>'tab_key'=%s AND target->'ops' @> %s::jsonb))""",
                (run["project_slug"], task["row_id"], task["target"]["tab_key"], None if col is None else str(col),
                 task["created_at"], cell_ops, run["project_slug"], task["target"]["tab_key"], cell_ops))
            take = cur.fetchone()[0]
    return {"prompt": privacy.sanitize(node["prompt"], mode), "tabs": inputs, "scope": node.get("scope", "legacy"),
            "row_id": task["row_id"], "rows": structured_rows, "target": task["target"], "take": take,
            "target_tables": target_tables, "predecessors": results, "predecessor_tasks": predecessor_tasks}


def _sanitize_output(conn, slug, original, mode, keep_provenance=False):
    # Take provenance (graph, hashes) would be mangled by masking; take bundles scrub secrets on export.
    output = privacy.sanitize({k: v for k, v in original.items() if k != "provenance"}, mode)
    if keep_provenance and isinstance(original.get("provenance"), dict):
        output["provenance"] = original["provenance"]
    if "asset_url" in original:
        url = original["asset_url"]
        prefix = f"/projects/api/{slug}/assets/"
        identifier = url[len(prefix):] if isinstance(url, str) and url.startswith(prefix) else ""
        if not re.fullmatch(r"pa_[0-9a-f]{32}", identifier) or not repo.get_asset(conn, slug, identifier):
            raise ExecutionError(400, "asset_url must reference media uploaded to this production.")
        output["asset_url"] = url
    if "table_id" in original:
        if not isinstance(original["table_id"], str) or not _ID.fullmatch(original["table_id"]):
            raise ExecutionError(400, "Invalid table_id.")
        output["table_id"] = original["table_id"]
    if isinstance(original.get("row_edits"), list):
        for before, after in zip(original["row_edits"], output["row_edits"]):
            if isinstance(before, dict) and isinstance(after, dict) and "row_id" in before:
                if not isinstance(before["row_id"], str) or not _ID.fullmatch(before["row_id"]):
                    raise ExecutionError(400, "Invalid row_id.")
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
    # The launcher's workers serve every production with one fixed graph each: they take only tasks bound to them,
    # never an unbound step another production meant for a worker of its own choosing.
    bound_only = local_workers.is_local(worker["id"])
    for run in runs:
        _recover(conn, run)
        with conn.cursor() as cur:
            cur.execute(f"""SELECT {_TASK_COLUMNS} FROM projectops.limb_task WHERE run_id=%s AND status='queued'
                            AND capability=ANY(%s) AND (assigned_limb=%s OR (assigned_limb IS NULL AND NOT %s))
                            AND NOT (node_id=ANY(%s))
                            ORDER BY created_at,node_id,row_id FOR UPDATE SKIP LOCKED LIMIT 1""",
                        (run["id"], worker["capabilities"], worker["id"], bound_only, [n['id'] for n in run['definition']['nodes'] if n.get('agent_key')]))
            row = cur.fetchone()
            if not row:
                continue
            task = _task(row)
            node = next(n for n in run["definition"]["nodes"] if n["id"] == task["node_id"])
            if node.get('agent_key'):
                continue
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
        raise ExecutionError(404, "Task not found.")
    run = _get_run(conn, str(row[0]), lock=True)
    if run["project_slug"] not in worker["allowed_projects"]:
        raise ExecutionError(403, "This worker cannot access the production.")
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


def _result_target(conn,run,task,output):
    from project_assistant.proposal_output import prepare_output
    return prepare_output(task["target"],task["target_snapshot"],output,conn=conn,slug=run["project_slug"],row_id=task["row_id"])


def complete(conn, worker, body):
    run, task = leased_task(conn, worker, body.get("task_id"), body.get("lease_token"))
    output = body.get("output")
    if isinstance(output, str):
        output = {"text": output}
    try:
        size = len(json.dumps(output, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ExecutionError(400, "output must be valid JSON; numbers cannot be NaN or Infinity.") from exc
    if not isinstance(output, dict) or size > 2 * 1024 * 1024:
        raise ExecutionError(400, "output must be a JSON object no larger than 2 MB.")
    me = _creator(conn, run)
    if run.get("execution", {}).get("mode") == "single_step":
        _check_source_revisions(conn, run["project_slug"], run["execution"]["source_revisions"])
    output = _sanitize_output(conn, run["project_slug"], output, privacy.mode(conn, run["project_slug"]), keep_provenance=True)
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
        from project_assistant import take_grader
        if take_grader.on_take(conn, run["project_slug"], task["target"].get("tab_key"), task["target"].get("row_id"), output, me.actor_id):
            take_grader.kick()  # the grader polls too, so it still finds the record once this transaction commits
    with conn.cursor() as cur:
        cur.execute("""UPDATE projectops.limb_task SET status=%s,output=%s::jsonb,proposal_id=%s,lease_hash=NULL,
                       lease_until=NULL,updated_at=NOW() WHERE id=%s""", (status, json.dumps(output), proposal_id, task["id"]))
    _advance(conn, run)
    _measure_camera(conn, run["project_slug"], task, output)
    return {"task_id": task["id"], "status": status, "proposal_id": proposal_id}


def _measure_camera(conn, slug, task, output):
    """A video take in a row with a Previs is scored against it in the background; the take never waits for that."""
    take = str(output.get("asset_url") or "").rsplit("/", 1)[-1]
    meta = repo.get_asset_meta(conn, slug, take) if task["row_id"] and take.startswith("pa_") else None
    if not (meta and meta[0].startswith("video/")):
        return
    for table in _table_data((task.get("target_snapshot") or {}).get("doc", {}), {}):
        for row in table["rows"]:
            if row["row_id"] == task["row_id"]:
                previs = camera_fidelity.previs_asset(table["headers"], row["cells"])
                if previs and previs != take:
                    camera_fidelity.schedule(slug, previs, take)
                return


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
    from project_assistant.orchestration_store import one
    if one(conn,'''SELECT t.id FROM projectops.orchestration_task t JOIN projectops.limb_task l ON l.id=t.flow_task_id WHERE l.proposal_id=%s''',(proposal_id,)):
        return
    run = _get_run(conn, str(row[0]), lock=True)
    with conn.cursor() as cur:
        cur.execute("""UPDATE projectops.limb_task SET status=%s,error=%s,updated_at=NOW()
                       WHERE proposal_id=%s AND status='awaiting_approval'""",
                    ("succeeded" if applied else "failed", None if applied else "輸出提案未通過審核", proposal_id))
    _advance(conn, run)
