"""Readable proposal comparisons and safe independent-row selection."""
import copy
import hashlib
import json
from project_docs.doc_schema import node_text
from project_assistant.request_scope import cell_text


def _fids(node):
    result = {node["attrs"]["fid"]} if node.get("type") in ("fill", "status") and node.get("attrs", {}).get("fid") else set()
    for child in node.get("content", []): result.update(_fids(child))
    return result


def _independent(target):
    ops = target.get("ops", [])
    if not ops or any(op.get("op") != "put_row" or not op.get("base") or not op.get("edited_cols") for op in ops): return False
    seen_rows, seen_fields = set(), set()
    for op in ops:
        key = (op.get("table"), op.get("rid"))
        fields = set().union(*(_fids(op["base"]["content"][c]) for c in op["edited_cols"]))
        if key in seen_rows or fields & seen_fields: return False
        seen_rows.add(key); seen_fields.update(fields)
    return True


def version(target):
    content = {key: target.get(key) for key in ("tab_key", "ops", "field_edits", "request_scope")}
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def describe(target, tab, *, partial_allowed=False):
    tables = {t.get("attrs", {}).get("bid"): t for t in (tab or {}).get("doc", {}).get("content", []) if t.get("type") == "table"}
    before_values = {e["fid"]: e.get("base") for e in target.get("field_edits", [])}
    after_values = {e["fid"]: e.get("value") for e in target.get("field_edits", [])}
    groups = []
    for i, op in enumerate(target.get("ops", [])):
        before, after = op.get("base") or {}, op.get("node") or {}
        table = tables.get(op.get("table"), {})
        header = (table.get("content") or [{}])[0].get("content", [])
        changes = []
        if op.get("op") == "put_row":
            for c in op.get("edited_cols", range(len(after.get("content", [])))):
                old = before.get("content", [])[c] if c < len(before.get("content", [])) else {}
                new = after.get("content", [])[c] if c < len(after.get("content", [])) else {}
                changes.append({"column": node_text(header[c]) if c < len(header) else f"欄 {c + 1}", "before": cell_text(old, before_values), "after": cell_text(new, after_values)})
        else:
            changes.append({"column": "文件／結構", "before": node_text(before), "after": node_text(after)})
        label = cell_text((before.get("content") or after.get("content") or [{}])[0], before_values) if op.get("op") == "put_row" else "結構修改"
        data_rows = [row for row in table.get("content", []) if not all(cell.get("type") == "tableHeader" for cell in row.get("content", []))]
        row_number = next((n + 1 for n, row in enumerate(data_rows) if row.get("attrs", {}).get("bid") == op.get("rid")), None)
        context_cells = (before.get("content") or after.get("content") or [])[:2]
        context = " · ".join(cell_text(cell, before_values)[:80] for cell in context_cells if cell_text(cell, before_values))
        label = (f"第 {row_number} 列 · " if row_number else "") + (context or label or "新增資料")
        groups.append({"index": i, "row_id": op.get("rid"), "row_number": row_number, "context": context, "label": label[:200], "changes": changes})
    return {"groups": groups, "partial_allowed": bool(partial_allowed and _independent(target)), "source_revision": target.get("expected_revision") or target.get("source_revision"), "version": version(target)}


def select_target(target, selected):
    ops = target.get("ops", [])
    if not _independent(target) or not isinstance(selected, list) or not selected or any(type(i) is not int or i < 0 or i >= len(ops) for i in selected) or len(set(selected)) != len(selected):
        raise ValueError("這組修改有相依關係或選取無效，請整組核對")
    result = copy.deepcopy(target)
    result["ops"] = [op for i, op in enumerate(ops) if i in selected]
    fids = set().union(*(_fids(op["node"]["content"][c]) for op in result["ops"] for c in op["edited_cols"]))
    result["field_edits"] = [e for e in result.get("field_edits", []) if e["fid"] in fids]
    result.pop("review", None)
    return result
