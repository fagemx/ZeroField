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
        raise ValueError("The task scope could not be found. Select the data again.")
    if type(raw.get("base_revision")) is not int or raw["base_revision"] != tab.get("revision"):
        raise ValueError("The source changed. Return to the table and select the scope again.")
    if raw.get('kind')=='doc':
        ids=raw.get('block_ids')
        blocks={b.get('attrs',{}).get('bid'):b for b in tab['doc'].get('content',[])}
        if not isinstance(ids,list) or not 0<len(ids)<=200 or any(not isinstance(k,str) or k not in blocks for k in ids) or len(set(ids))!=len(ids):
            raise ValueError("The selected passages changed or no longer exist. Select them again.")
        selected=[blocks[k] for k in ids]
        fids=set()
        def visit(node):
            fid=node.get('attrs',{}).get('fid')
            if fid: fids.add(fid)
            for child in node.get('content',[]): visit(child)
        for block in selected: visit(block)
        fingerprint=hashlib.sha256(json.dumps([selected,{k:values.get(k) for k in sorted(fids)}],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        return {'kind':'doc','target_tab':tab['key'],'tab_title':tab.get('title',tab['key']),
                'base_revision':tab['revision'],'block_ids':list(ids),'fingerprint':fingerprint}
    if raw.get('kind') not in (None,'sheet'):
        raise ValueError("Invalid task scope type.")
    table = _tables(tab).get(raw.get("table_id"))
    if not table: raise ValueError("The selected worksheet no longer exists.")
    rows = {r.get("attrs", {}).get("bid"): r for r in table.get("content", []) if not all(c.get("type") == "tableHeader" for c in r.get("content", []))}
    ids = raw.get("row_ids")
    if not isinstance(ids, list) or not 0 < len(ids) <= 200 or any(not isinstance(r, str) or r not in rows for r in ids) or len(set(ids)) != len(ids):
        raise ValueError("The selected rows changed or no longer exist. Select them again.")
    columns = column_ids(table)
    requested = raw.get("column_ids", columns)
    if not isinstance(requested, list) or not requested or any(not isinstance(c, str) or c not in columns for c in requested) or len(set(requested)) != len(requested):
        raise ValueError("The selected columns changed. Select them again.")
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
    if current["fingerprint"] != scope.get("fingerprint") or current.get("column_indices") != scope.get("column_indices"):
        raise ValueError("The selected source changed. Review it before generating another proposal.")
    return current


def guard_edits(scope, tab, values, row_edits, new_rows, table_id):
    if not scope: return
    if scope.get('kind')=='doc':
        raise ValueError("This task is limited to selected passages and cannot edit tables.")
    current = validate_scope(scope, tab, values)
    if current["fingerprint"] != scope.get("fingerprint"):
        raise ValueError("The selected content changed. Review the source before proposing changes.")
    if table_id not in (None, scope["table_id"]) or new_rows:
        raise ValueError("This task only edits selected data. Adding rows or editing other worksheets requires a separate request.")
    allowed = {str(c) for c in scope["column_indices"]}
    for edit in row_edits:
        if edit.get("row_id") not in scope["row_ids"] or not set(edit.get("cells", {})).issubset(allowed):
            raise ValueError("Changes exceed the user’s selected rows or columns. Keep edits within the selected data.")


def guard_child_scope(parent,child):
    if not parent:
        return
    if not child or parent.get('kind','sheet')!=child.get('kind','sheet') or parent['target_tab']!=child['target_tab']:
        raise ValueError("A child task cannot expand its parent’s scope.")
    if parent.get('kind')=='doc':
        if not set(child['block_ids']).issubset(parent['block_ids']):
            raise ValueError("A child task cannot edit unselected passages.")
    elif (parent['table_id']!=child['table_id'] or not set(child['row_ids']).issubset(parent['row_ids'])
          or not set(child['column_ids']).issubset(parent['column_ids'])):
        raise ValueError("A child task cannot edit unselected rows or columns.")


def for_model(scope):
    """Keep the server's content fingerprint out of model and adapter payloads."""
    return {key:value for key,value in scope.items() if key!='fingerprint'} if scope else None
