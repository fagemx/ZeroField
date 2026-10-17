"""Explicit schema commands and conservative dependency checks.

Column identities survive renames/moves. Unsupported positional dependencies are
reported before a change; this module does not pretend to rewrite Excel formulas.
"""
import copy

from project_docs import repository as repo
from project_docs.doc_schema import DocError, column_ids, new_id, node_text


def tables(doc):
    return {n.get("attrs", {}).get("bid"): n for n in doc.get("content", []) if n.get("type") == "table"}


def shifts_columns(before, after):
    old, new = column_ids(before), column_ids(after)
    old_rows = [row.get("attrs", {}).get("bid") for row in before.get("content", [])]
    new_rows = [row.get("attrs", {}).get("bid") for row in after.get("content", [])]
    return new[:len(old)] != old or new_rows[:len(old_rows)] != old_rows


def dependencies(conn, slug, key, table_id, before, after):
    if not shifts_columns(before, after):
        return []
    found = []
    for tab in repo.list_tabs(conn, slug):
        doc = repo.get_tab(conn, slug, tab["key"])["doc"]
        for table in tables(doc).values():
            for row in table.get("content", []):
                for index, cell in enumerate(row.get("content", [])):
                    if node_text(cell).startswith("="):
                        found.append({"kind": "formula", "tab_key": tab["key"], "row_id": row.get("attrs", {}).get("bid"), "col_index": index})
    with conn.cursor() as cursor:
        cursor.execute("SELECT tab_key, definition FROM projectops.flow_definition WHERE project_slug = %s", (slug,))
        definitions = cursor.fetchall()
        cursor.execute("SELECT tab_key, definition FROM projectops.flow_run WHERE project_slug = %s AND status IN ('queued','running','awaiting_approval')", (slug,))
        definitions += cursor.fetchall()
    for flow_key, definition in definitions:
        for node in repo._loads(definition).get("nodes", []):
            for binding in (node.get("target", {}), node.get("row_source", {})):
                if binding.get("tab_key") == key and binding.get("table_id", table_id) == table_id:
                    found.append({"kind": "flow", "tab_key": flow_key, "node_id": node.get("id")})
    return found


def guard_schema_change(conn, slug, key, before_doc, after_doc):
    old, new = tables(before_doc), tables(after_doc)
    for bid, before in old.items():
        after = new.get(bid, {"content": []})
        refs = dependencies(conn, slug, key, bid, before, after)
        if refs:
            error = DocError("欄位移動或刪除會影響公式／工作流；請先解除相關引用。" + "、".join(dict.fromkeys(ref["tab_key"] for ref in refs)))
            error.dependencies = refs
            raise error


def edit_table(table, body, values=None):
    from project_assistant.table_edits import _cell, cell_value, validate_value
    result = copy.deepcopy(table)
    attrs = result.setdefault("attrs", {})
    ids = column_ids(table)
    attrs["column_ids"] = ids.copy()
    width = len(ids)
    attrs["column_types"] = (attrs.get("column_types", []) + ["text"] * width)[:width]
    operation = body.get("operation")
    identifier = body.get("column_id")
    if operation not in ("add", "reorder", "restore") and identifier not in ids:
        raise ValueError("欄位已不存在，請重新讀取")
    index = ids.index(identifier) if identifier in ids else None
    if operation == "restore":
        if body.get("expected_table") != table or not isinstance(body.get("table"), dict):
            raise ValueError("表格已有後續修改，不能撤銷欄位操作")
        if body["table"].get("attrs", {}).get("bid") != table.get("attrs", {}).get("bid"):
            raise ValueError("撤銷表格身分不符")
        return copy.deepcopy(body["table"])
    if operation == "rename":
        name = str(body.get("name", "")).strip()
        if not name or len(name) > 100:
            raise ValueError("欄名需要 1～100 字")
        first = result.get("content", [{}])[0]
        if not first.get("content") or not all(c.get("type") == "tableHeader" for c in first["content"]):
            raise ValueError("這張表格沒有標題列")
        first["content"][index] = {**_cell(name), "type": "tableHeader"}
    elif operation == "add":
        if width >= 100:
            raise ValueError("最多 100 欄")
        name = str(body.get("name") or f"欄 {width + 1}")[:100]
        attrs["column_ids"].append(new_id("c"))
        attrs["column_types"].append("text")
        for row in result.get("content", []):
            header = bool(row.get("content")) and all(c.get("type") == "tableHeader" for c in row["content"])
            row.setdefault("content", []).append({**_cell(name if header else ""), "type": "tableHeader" if header else "tableCell"})
    elif operation == "delete":
        if width <= 1:
            raise ValueError("至少保留一個欄位")
        attrs["column_ids"].pop(index)
        attrs["column_types"].pop(index)
        attrs.get("column_options", {}).pop(identifier, None)
        for row in result.get("content", []):
            row["content"].pop(index)
    elif operation == "reorder":
        order = body.get("order")
        if not isinstance(order, list) or len(order) != width or set(order) != set(ids):
            raise ValueError("欄位順序必須完整包含每個欄位一次")
        positions = [ids.index(cid) for cid in order]
        attrs["column_ids"] = order.copy()
        attrs["column_types"] = [attrs["column_types"][i] for i in positions]
        for row in result.get("content", []):
            row["content"] = [row["content"][i] for i in positions]
    elif operation in ("change_type", "configure"):
        if operation == "configure" and "name" in body:
            result = edit_table(result, {"operation": "rename", "column_id": identifier, "name": body["name"]}, values)
            attrs = result["attrs"]
        if operation == "change_type" or "column_type" in body:
            kind = body.get("column_type")
            if kind not in ("text", "number", "formula", "image", "video", "audio", "status"):
                raise ValueError("不支援的欄位型態")
            attrs["column_types"][index] = kind
        if "options" in body:
            options = body["options"]
            if not isinstance(options, list) or not options or len(options) > 100 or any(not isinstance(v, str) or not 0 < len(v) <= 100 for v in options) or len(set(options)) != len(options):
                raise ValueError("狀態選項需要不重複的 1～100 字文字")
            attrs.setdefault("column_options", {})[identifier] = {"options": options}
        for row in result.get("content", []):
            if row.get("content") and row["content"][index].get("type") != "tableHeader":
                validate_value(result, index, cell_value(row["content"][index], values or {}))
    else:
        raise ValueError("不支援的欄位操作")
    return result


def apply(conn, me, slug, key, body):
    from project_docs import service
    tab = repo.get_tab_for_update(conn, slug, key)
    if not tab:
        return 404, {"error": "找不到分頁"}
    table = tables(tab["doc"]).get(body.get("table_id"))
    if not table:
        return 404, {"error": "找不到表格"}
    if body.get("base_revision") != tab["revision"] or body.get("expected_column_ids") != column_ids(table):
        return 409, {"error": "表格已變更，請重新核對欄位操作"}
    try:
        after = edit_table(table, body, repo.field_values(conn, slug).get(key, {}))
        op = {"op": "put", "bid": body["table_id"], "base": table, "node": after}
        result, doc, revision, saved_at = service._run_ops(conn, me, slug, key, tab, [op], "schema-" + new_id("s"), atomic=True, delivery_mode=body.get("delivery_mode"))
        if result.conflicts:
            return 409, {"error": "表格已變更或正在編輯", "conflicts": result.conflicts}
        return 200, {"doc": doc, "revision": revision, "saved_at": saved_at, "schema_patch": {"before": table, "after": tables(doc)[body["table_id"]]}}
    except ValueError as exc:
        return 400, {"error": str(exc), "dependencies": getattr(exc, "dependencies", [])}
