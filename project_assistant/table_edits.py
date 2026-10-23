"""Build reviewable, optimistic, all-or-nothing edits for any tab's tables."""
import copy
import re

from project_docs import blocks, repository as repo
from project_docs.doc_schema import STATUSES, column_ids, index_doc, new_id, node_text


def _plain(value):
    if value is None:
        return ""
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        text = str(value)
        if len(text) <= 10000:
            return text
    raise ValueError("Cell content must be text or a number with at most 10,000 characters.")


def _cell(value):
    text = _plain(value)
    return {"type": "tableCell", "content": [{"type": "paragraph", **({"content": [{"type": "text", "text": text}]} if text else {})}]}


def _field(cell):
    if cell.get("type") in ("fill", "status"):
        return cell
    for child in cell.get("content", []):
        found = _field(child)
        if found:
            return found
    return None


def _cell_base(cell):
    """Account for schema defaults materialized by the first validated save."""
    value = copy.deepcopy(cell)
    if value.get("type") in ("tableCell", "tableHeader"):
        value["attrs"] = {"colspan": 1, "rowspan": 1, "colwidth": None, **value.get("attrs", {})}
    return value


class CellConflict(ValueError):
    def __init__(self, conflicts):
        super().__init__("這些儲存格已變更，草稿尚未套用")
        self.conflicts = conflicts


def cell_value(cell, values):
    text = ""
    def walk(node):
        nonlocal text
        kind, attrs = node.get("type"), node.get("attrs", {})
        if kind == "text":
            text += node.get("text", "")
        elif kind == "hardBreak":
            text += "\n"
        elif kind == "image":
            text = f"![{attrs.get('alt') or '圖片'}]({attrs.get('src')})"
        elif kind in ("fill", "status"):
            value = values.get(attrs.get("fid"))
            text = _plain(value.get("value", "") if isinstance(value, dict) else value if value is not None else attrs.get("label", "未開始") if kind == "status" else "")
        for child in node.get("content", []):
            walk(child)
    walk(cell)
    return text


def validate_value(table, index, text):
    attrs = table.get("attrs", {})
    types = attrs.get("column_types", [])
    kind = types[index] if index < len(types) else "text"
    ids = attrs.get("column_ids", [])
    options = attrs.get("column_options", {}).get(ids[index] if index < len(ids) else "", {}).get("options", [])
    if text and kind == "number" and not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", text):
        raise ValueError(f"Column {index + 1} requires a number. Nothing was applied.")
    if text and kind == "formula" and not text.startswith("="):
        raise ValueError(f"Column {index + 1} requires a formula starting with =.")
    if text and kind == "status" and options and text not in options:
        raise ValueError(f"The status in column {index + 1} is not among its configured options.")


def check_expected(doc, edits, values, table_id=None):
    """Check all bases before preparing any mutation, including field-backed cells."""
    rows = {r.get("attrs", {}).get("bid"): (t, r) for t in doc.get("content", [])
            if t.get("type") == "table" and (not table_id or t.get("attrs", {}).get("bid") == table_id)
            for r in t.get("content", [])}
    conflicts = []
    for edit in edits:
        if not isinstance(edit, dict) or not isinstance(edit.get("cells"), dict):
            raise ValueError("row_edits must include cells.")
        expected = edit.get("expected_cells")
        if not isinstance(expected, dict) or set(expected) != set(edit["cells"]):
            raise ValueError("Each changed cell requires its original value in expected_cells.")
        table, row = rows.get(edit.get("row_id"), ({}, {}))
        for col, mine in edit["cells"].items():
            if not str(col).isdigit():
                raise ValueError("Column indices must be zero-based integers.")
            index = int(col)
            cells = row.get("content", [])
            current = cell_value(cells[index], values) if index < len(cells) else None
            ids = table.get("attrs", {}).get("column_ids", [])
            expected_ids = edit.get("column_ids", {})
            identity_changed = col in expected_ids and (index >= len(ids) or expected_ids[col] != ids[index])
            if current != _plain(expected[col]) or identity_changed:
                conflicts.append({"row_id": edit.get("row_id"), "col_index": index, "before": expected[col], "mine": mine, "current": current,
                                  "reason": "column_changed" if identity_changed else "value_changed"})
    if conflicts:
        raise CellConflict(conflicts)


def _row_meta(row):
    return {**{k: v for k, v in row.items() if k not in ("content", "attrs")},
            "attrs": {"owner": None, "created": None, **row.get("attrs", {})}}


def prepare(doc, row_edits, new_rows, values, table_id=None):
    if not isinstance(row_edits, list) or not isinstance(new_rows, list) or not 0 < len(row_edits) + len(new_rows) <= 200:
        raise ValueError("Provide changes or additions for 1–200 rows.")
    tables = [n for n in doc.get("content", []) if n.get("type") == "table"]
    if table_id:
        tables = [t for t in tables if t.get("attrs", {}).get("bid") == table_id]
    if not tables:
        raise ValueError("Table not found.")
    if new_rows and len(tables) != 1:
        raise ValueError("This page contains multiple tables. Specify table_id when adding rows.")
    rows = {}
    for table in tables:
        for row in table.get("content", []):
            if row.get("content") and all(c.get("type") == "tableHeader" for c in row["content"]):
                continue
            rows[row.get("attrs", {}).get("bid")] = (table, row)
    ops, fields, preview, touched = [], [], [], set()
    for edit in row_edits:
        if not isinstance(edit, dict) or not isinstance(edit.get("cells"), dict) or not edit["cells"]:
            raise ValueError("row_edits must include row_id and cells mapping zero-based column indices to content.")
        rid = edit.get("row_id")
        if rid not in rows or rid in touched:
            raise ValueError("A row is missing or duplicated. Read the page’s row IDs again.")
        touched.add(rid)
        table, before = rows[rid]
        after = copy.deepcopy(before)
        for col, value in edit["cells"].items():
            if not str(col).isdigit() or int(col) >= len(after.get("content", [])):
                raise ValueError("The zero-based column index is outside the table.")
            index, text = int(col), _plain(value)
            validate_value(table, index, text)
            old_cell = before["content"][index]
            field = _field(after["content"][index])
            old = cell_value(old_cell, values)
            if field:
                attrs = field["attrs"]
                fid, kind = attrs["fid"], field["type"]
                ids = table.get("attrs", {}).get("column_ids", [])
                options = table.get("attrs", {}).get("column_options", {}).get(ids[index] if index < len(ids) else "", {}).get("options", STATUSES)
                if kind == "status" and text not in options:
                    raise ValueError("Unsupported status.")
                base = values.get(fid)
                fields.append({"fid": fid, "kind": kind, "base": base, "value": text})
                if kind == "status":
                    attrs["label"] = text
            else:
                after["content"][index] = dict(_cell(text), attrs=copy.deepcopy(old_cell.get("attrs", {})))
            preview.append(f"{rid} / 欄 {index + 1}：{old} → {text}")
        ops.append({"op": "put_row", "table": table["attrs"]["bid"], "rid": rid, "base": before, "node": after,
                    "edited_cols": [int(col) for col in edit["cells"]], "column_ids": column_ids(table)})
    if new_rows:
        table = tables[0]
        width = len(table["content"][0].get("content", []))
        previous = table["content"][-1]["attrs"]["bid"]
        for row in new_rows:
            if not isinstance(row, list) or len(row) != width:
                raise ValueError(f"New rows require {width} cells.")
            for index, value in enumerate(row):
                validate_value(table, index, _plain(value))
            rid = new_id("b")
            node = {"type": "tableRow", "attrs": {"bid": rid}, "content": [_cell(v) for v in row]}
            ops.append({"op": "put_row", "table": table["attrs"]["bid"], "rid": rid, "base": None, "after": previous, "node": node})
            previous = rid
            preview.append("新增列：" + " | ".join(_plain(v) for v in row))
    return ops, fields, "\n".join(preview)


def apply(conn, me, slug, target):
    from project_docs import service
    key = target["tab_key"]
    versions = target.get("source_revisions")
    source_scopes=target.get('source_scopes',[])
    if not isinstance(source_scopes,list) or len(source_scopes)>100 or any(not isinstance(s,dict) or not isinstance(s.get('target_tab'),str) for s in source_scopes):
        return 400,{'error':"Invalid source scope."}
    if versions is not None or source_scopes:
        versions={} if versions is None else versions
        if not isinstance(versions, dict) or len(versions) > 100 or any(not isinstance(k, str) or type(v) is not int or v < 0 for k, v in versions.items()):
            return 400, {"error": "Invalid source revision for this test run."}
        # Consistent key order prevents reciprocal source/target lock deadlocks.
        locked = {source_key: repo.get_tab_for_update(conn, slug, source_key) for source_key in sorted(set(versions) | {s['target_tab'] for s in source_scopes} | {key})}
        if any(not locked[source_key] or locked[source_key]["revision"] != expected for source_key, expected in versions.items()):
            return 409, {"error": "The test source changed or was deleted. Review it and test again."}
        tab = locked[key]
    else:
        tab = repo.get_tab_for_update(conn, slug, key)
    if not tab:
        return 404, {"error": "The page was deleted."}
    if target.get("expected_revision") is not None and target["expected_revision"] != tab["revision"]:
        return 409, {"error": "The page changed. Generate a new proposal for added rows."}
    ops = copy.deepcopy(target.get("ops", []))
    # Parallel branches may update different cells of the same row. Rebase only
    # explicitly edited columns whose own bases are unchanged. Row structure,
    # metadata and locks retain the normal optimistic checks.
    rows = {(table.get("attrs", {}).get("bid"), row.get("attrs", {}).get("bid")): row
            for table in tab["doc"].get("content", []) if table.get("type") == "table"
            for row in table.get("content", [])}
    tables = {table.get("attrs", {}).get("bid"): table for table in tab["doc"].get("content", []) if table.get("type") == "table"}
    for op in ops:
        if op.get("column_ids") and op["column_ids"] != column_ids(tables.get(op.get("table"), {})):
            return 409, {"error": "The column structure changed. Review the edit targets again."}
        if op.get("op") != "put_row" or not op.get("edited_cols") or not op.get("base"):
            continue
        before, after = op["base"], op.get("node", {})
        current = rows.get((op.get("table"), op.get("rid")))
        if current is None or current == before:
            continue
        before_cells, current_cells, after_cells = before.get("content", []), current.get("content", []), after.get("content", [])
        cols = op["edited_cols"]
        if (len(before_cells) != len(current_cells) or len(after_cells) != len(current_cells)
                or _row_meta(before) != _row_meta(current)
                or any(type(i) is not int or not 0 <= i < len(current_cells) or _cell_base(before_cells[i]) != _cell_base(current_cells[i]) for i in cols)):
            continue
        merged = copy.deepcopy(current)
        for index in cols:
            merged["content"][index] = after_cells[index]
        op["base"], op["node"] = current, merged
    checked = blocks.apply_ops(tab["doc"], ops, blocks.Actor(me.actor_id, me.can_edit), locks=repo.tab_locks(conn, slug, key), now=service._now())
    if checked.conflicts:
        return 409, {"error": "The data changed or is being edited. Generate a new proposal.", "conflicts": checked.conflicts}
    values = repo.field_values(conn, slug).get(key, {})
    if source_scopes:
        from project_assistant.request_scope import verify_source
        all_values=repo.field_values(conn,slug)
        try:
            for scope in source_scopes:
                if not locked[scope['target_tab']]:
                    raise ValueError("The source page was deleted.")
                verify_source(scope,{**locked[scope['target_tab']],'key':scope['target_tab']},all_values.get(scope['target_tab'],{}))
        except ValueError as exc:
            return 409,{'error':str(exc)}
    if target.get("request_scope"):
        from project_assistant.request_scope import verify_source
        try:
            verify_source(target["request_scope"], {**tab, "key": key}, values)
        except ValueError as exc:
            return 409, {"error": str(exc)}
    for edit in target.get("field_edits", []):
        if values.get(edit["fid"]) != edit.get("base"):
            return 409, {"error": "The column changed. Generate a new proposal."}
    after_values = {**values, **{edit["fid"]: {"value": edit["value"]} for edit in target.get("field_edits", [])}}
    try:
        for op in ops:
            table = tables.get(op.get("table"), {})
            for index in op.get("edited_cols", range(len(op.get("node", {}).get("content", [])))):
                validate_value(table, index, cell_value(op["node"]["content"][index], after_values))
    except ValueError as exc:
        return 400, {"error": str(exc)}
    patches = [{"row_id": op["rid"], "col_index": index,
                "column_id": (op.get("column_ids") or [None] * len(op["base"]["content"]))[index],
                "before": cell_value(op["base"]["content"][index], values),
                "after": cell_value(op["node"]["content"][index], after_values)}
               for op in ops if op.get("base") for index in op.get("edited_cols", [])]
    from project_docs.story_openapi import StoryError
    try:
        result, doc, revision, saved_at = service._run_ops(conn, me, slug, key, tab, ops, "table-" + new_id("s"), atomic=True,
                                                         delivery_mode=target.get("delivery_mode"))
    except StoryError as exc:
        # StoryError is a ValueError: preserve 409 before the legacy 400 handler.
        if exc.code not in ('DRAMA_WRITING_LOCKED','DRAMA_WRITING_CONFLICT'): raise
        return exc.status, {"error": str(exc), "code": exc.code}
    except ValueError as exc:
        return 400, {"error": str(exc), "dependencies": getattr(exc, "dependencies", [])}
    if result.conflicts:
        return 409, {"error": "The data changed or is being edited. Generate a new proposal.", "conflicts": result.conflicts}
    changed_fields = False
    for edit in target.get("field_edits", []):
        repo.set_field_value(conn, slug, key, edit["fid"], kind=edit["kind"], value=edit["value"], actor_id=me.actor_id)
        field = index_doc(doc)[0].get(edit["fid"])
        prior = edit.get("base")
        before_field = index_doc(tab["doc"])[0].get(edit["fid"], {})
        before_value = prior.get("value", "") if isinstance(prior, dict) else prior if prior is not None else before_field.get("default", "")
        if field and before_value != edit["value"]:
            changed_fields = True
            repo.add_activity(conn, slug, key, field["anchor_id"], kind=edit["kind"], actor_id=me.actor_id,
                              field_id=edit["fid"], field_label=field["label"], old_value=before_value, new_value=edit["value"])
    if changed_fields and revision == tab["revision"]:
        saved = repo.save_tab_doc(conn, slug, key, doc=doc, title=tab["title"], actor_id=me.actor_id,
                                  session_id="table-fields-" + new_id("s"), base_revision=None, force_revision=True)
        revision, saved_at = saved["revision"], saved["saved_at"]
    return 200, {"applied": result.applied, "revision": revision, "doc": doc, "saved_at": saved_at,
                 "cell_patches": patches, "values": repo.field_values(conn, slug).get(key, {})}
