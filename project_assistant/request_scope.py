"""Server-validated, immutable work selections carried with a user request."""
import hashlib
import json

from project_docs.doc_schema import column_ids, node_text


def _tables(tab):
    return {t.get("attrs", {}).get("bid"): t for t in tab.get("doc", {}).get("content", []) if t.get("type") == "table"}


def cell_text(cell, values):
    from project_assistant.table_edits import cell_value
    return cell_value(cell, values)


def _fingerprint(table, rows, columns, values):
    selected = {r.get("attrs", {}).get("bid"): r for r in table.get("content", [])}
    data = [[rid, [cell_text(selected[rid]["content"][c], values) for c in columns]] for rid in rows]
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def validate_scope(raw, tab, values):
    if not isinstance(raw, dict) or not tab or raw.get("target_tab") != tab.get("key"):
        raise ValueError("找不到本次處理範圍，請重新選取資料")
    if type(raw.get("base_revision")) is not int or raw["base_revision"] != tab.get("revision"):
        raise ValueError("來源已更新，請回到表格確認並重新選取處理範圍")
    table = _tables(tab).get(raw.get("table_id"))
    if not table: raise ValueError("本次處理的工作表已不存在")
    rows = {r.get("attrs", {}).get("bid"): r for r in table.get("content", []) if not all(c.get("type") == "tableHeader" for c in r.get("content", []))}
    ids = raw.get("row_ids")
    if not isinstance(ids, list) or not 0 < len(ids) <= 200 or any(not isinstance(r, str) or r not in rows for r in ids) or len(set(ids)) != len(ids):
        raise ValueError("選取列已改變或不存在，請重新選取")
    columns = column_ids(table)
    requested = raw.get("column_ids", columns)
    if not isinstance(requested, list) or not requested or any(not isinstance(c, str) or c not in columns for c in requested) or len(set(requested)) != len(requested):
        raise ValueError("選取欄位已改變，請重新選取")
    indices = [columns.index(c) for c in requested]
    header = table.get("content", [{}])[0].get("content", [])
    result = {"target_tab": tab["key"], "tab_title": tab.get("title", tab["key"]), "table_id": table["attrs"]["bid"],
              "table_name": table["attrs"].get("sheet_name") or table["attrs"].get("worksheet_name") or tab.get("title", "表格"),
              "base_revision": tab["revision"], "row_ids": list(ids), "column_ids": list(requested), "column_indices": indices,
              "column_labels": [node_text(header[c]) for c in indices],
              "row_labels": [cell_text(rows[r]["content"][0], values)[:160] or r for r in ids]}
    result["fingerprint"] = _fingerprint(table, ids, indices, values)
    return result


def verify_source(scope, tab, values):
    """Rebase unrelated edits while retaining every selected input's fingerprint."""
    current = validate_scope({**scope, "base_revision": tab["revision"]}, tab, values)
    if current["fingerprint"] != scope.get("fingerprint") or current["column_indices"] != scope.get("column_indices"):
        raise ValueError("本次選取的來源已變更，請重新核對來源再產生提案")
    return current


def guard_edits(scope, tab, values, row_edits, new_rows, table_id):
    if not scope: return
    current = validate_scope(scope, tab, values)
    if current["fingerprint"] != scope.get("fingerprint"):
        raise ValueError("本次選取的內容已更新，請重新核對來源再提出修改")
    if table_id not in (None, scope["table_id"]) or new_rows:
        raise ValueError("這次需求只修改選取資料；新增列或其他工作表需要另一次明確需求")
    allowed = {str(c) for c in scope["column_indices"]}
    for edit in row_edits:
        if edit.get("row_id") not in scope["row_ids"] or not set(edit.get("cells", {})).issubset(allowed):
            raise ValueError("修改超出使用者固定的列／欄範圍，請限制在本次選取資料")
