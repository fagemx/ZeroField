"""Shared snapshot and structured-output conversion for reviewed Flow and agent results."""
import re
from project_docs import repository as repo
from project_assistant import table_edits
from project_assistant.limbs import ExecutionError


def snapshot_target(conn, slug, target):
    if not target.get("tab_key"):
        return None
    tab = repo.get_tab(conn, slug, target["tab_key"])
    if not tab:
        raise ExecutionError(409, "輸出分頁已刪除")
    return {"doc": tab["doc"], "revision": tab["revision"], "title": tab["title"],
            "values": repo.field_values(conn, slug).get(target["tab_key"], {})}



def prepare_output(target,snapshot,output,*,conn=None,slug=None,row_id="",scope=None):
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
        selected=set(scope['block_ids']) if scope and scope.get('kind')=='doc' else None
        if selected is not None and (not selected or not selected.issubset({b.get('attrs',{}).get('bid') for b in before})):
            raise ExecutionError(409,'選取段落已不存在')
        ops = []
        if target.get("mode", "append") == "replace":
            replaced=[b for b in before if selected is None or b['attrs']['bid'] in selected]
            ops = [{"op": "del", "bid": b["attrs"]["bid"], "base": b} for b in replaced]
            index=before.index(replaced[0]) if replaced else 0
            previous=before[index-1]['attrs']['bid'] if index else None
        else:
            if selected is not None:
                previous=next(b['attrs']['bid'] for b in reversed(before) if b['attrs']['bid'] in selected)
            else:
                previous=target.get('after_block_id') or (before[-1].get('attrs',{}).get('bid') if before else None)
                if previous and previous not in {b.get('attrs',{}).get('bid') for b in before}:
                    raise ExecutionError(409,'插入位置已不存在')
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
                "ops": ops, "field_edits": [],
                **({'request_scope':scope,'source_revision':snapshot['revision']} if scope else {'expected_revision':snapshot['revision']})}, preview
    if target.get("row_id") and "col_index" in target:
        text = output.get("asset_url") if "asset_url" in output else output.get("text")
        if not isinstance(text, (str, int, float)):
            raise ExecutionError(400, "儲存格輸出需要 text 或已上傳的 asset_url")
        if "asset_url" in output:
            prefix = f"/projects/api/{slug}/assets/"
            asset_id = str(text)[len(prefix):] if str(text).startswith(prefix) else ""
            if not re.fullmatch(r"pa_[0-9a-f]{32}", asset_id) or not repo.get_asset(conn, slug, asset_id):
                raise ExecutionError(400, "asset_url 必須指向已上傳至本專案的媒體")
            mime, _ = repo.get_asset(conn, slug, asset_id)
            kind = mime.split("/", 1)[0]
            text = f"![圖片]({text})" if kind == "image" else f"[{kind}]({text})"
        row_edits, new_rows = [{"row_id": target["row_id"], "cells": {str(target["col_index"]): text}}], []
    else:
        row_edits, new_rows = output.get("row_edits", []), output.get("new_rows", [])
        # A selected-row run cannot write other rows or append unrelated rows.
        if row_id and (new_rows or any(e.get("row_id") != row_id for e in row_edits if isinstance(e, dict))):
            raise ExecutionError(400, "批次任務只能寫入自己選取的列")
    try:
        from project_assistant.request_scope import guard_edits
        table_id=output.get('table_id') or target.get('table_id') or (scope or {}).get('table_id')
        guard_edits(scope,{'key':target['tab_key'],'doc':snapshot['doc'],'revision':snapshot['revision']},snapshot['values'],row_edits,new_rows,table_id)
        ops, fields, preview = table_edits.prepare(snapshot["doc"], row_edits, new_rows, snapshot["values"], table_id)
    except ValueError as exc:
        raise ExecutionError(400, str(exc)) from exc
    return {"tab_key": target["tab_key"], "tab_title": snapshot["title"], "display": snapshot["title"],
            "ops": ops, "field_edits": fields,
            **({'request_scope':scope,'source_revision':snapshot['revision']} if scope else {}),
            **({"expected_revision": snapshot["revision"]} if new_rows else {})}, preview
