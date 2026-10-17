"""待辦：負責人交代的事、待確認問題、交接追蹤項目、@ 我還沒解決的討論。工具 my_todo 和畫面左欄共用。"""
from __future__ import annotations

from project_assistant import store
from project_docs import repository as repo
from project_docs.doc_schema import index_doc, node_text

SOURCES = {"ad-data": {"questions": "questions", "question_heading": "請行銷回答", "handoff": "handoff",
                       "provider": "行銷"}}


def table_rows(doc) -> list[tuple[str, list[str], list[tuple[str, list[str]]]]]:
    """每張表：前面最近的段落標題、表頭文字、[(列的 bid, 每格文字)]。"""

    out, heading = [], ""
    for node in doc.get("content") or []:
        if node.get("type") == "heading":
            heading = node_text(node).strip()
        if node.get("type") != "table":
            continue
        headers, body = [], []
        for index, row in enumerate(node.get("content") or []):
            cells = row.get("content") or []
            texts = [node_text(cell).strip() for cell in cells]
            if index == 0 and cells and all(cell.get("type") == "tableHeader" for cell in cells):
                headers = texts
                continue
            body.append(((row.get("attrs") or {}).get("bid"), texts))
        out.append((heading, headers, body))
    return out


def plain_values(conn, slug: str) -> dict[str, dict[str, str]]:
    """{tab_key: {field_id: 值}}。repo.field_values 每一格是 {kind, value, by, …}，這裡只留值。"""

    return {tab: {fid: entry.get("value") for fid, entry in fields.items()}
            for tab, fields in repo.field_values(conn, slug).items()}


def _status_by_row(doc, values: dict) -> dict:
    fields, _ = index_doc(doc)
    out = {}
    for fid, field in fields.items():
        if field["kind"] == "status":
            out.setdefault(field["anchor_id"], values.get(fid) or field["default"])
    return out


def todo_items(conn, slug: str, me) -> list[dict]:
    items: list[dict] = []
    if not me.can_edit:  # 交代是給助理帶使用者做的；管理員自己在管理視角看
        for note in store.notes(conn, slug, status="open"):
            if note["target_id"] not in (None, me.actor_id):
                continue
            items.append({"kind": "note", "id": note["id"], "text": note["body"], "at": note["created_at"]})
    source = SOURCES.get(slug)
    values = plain_values(conn, slug)
    if source:
        tab = repo.get_tab(conn, slug, source["questions"])
        if tab:
            statuses = _status_by_row(tab["doc"], values.get(tab["key"], {}))
            for heading, _, rows in table_rows(tab["doc"]):
                if source["question_heading"] not in heading:
                    continue
                for bid, cells in rows:
                    if bid in statuses and cells and cells[0].isdigit():
                        items.append({"kind": "question", "tab_key": tab["key"], "rid": bid, "number": int(cells[0]),
                                      "text": cells[1] if len(cells) > 1 else "",
                                      "why": cells[2] if len(cells) > 2 else "", "status": statuses[bid]})
        tab = repo.get_tab(conn, slug, source["handoff"])
        if tab:
            statuses = _status_by_row(tab["doc"], values.get(tab["key"], {}))
            for _, headers, rows in table_rows(tab["doc"]):
                col = next((i for i, text in enumerate(headers) if "提供" in text), None)
                if col is None:
                    continue
                for bid, cells in rows:
                    if bid in statuses and len(cells) > col and cells[col].startswith(source["provider"]):
                        items.append({"kind": "handoff", "tab_key": tab["key"], "rid": bid, "text": cells[0],
                                      "what": cells[1] if len(cells) > 1 else "", "status": statuses[bid]})
    else:
        # 通用多專案模式：自動掃描各分頁帶有狀態膠囊的表格列（編號列歸為待確認問題，其餘歸為交接／追蹤項目）
        for t in repo.list_tabs(conn, slug):
            tab = repo.get_tab(conn, slug, t["key"])
            if not tab:
                continue
            statuses = _status_by_row(tab["doc"], values.get(tab["key"], {}))
            if not statuses:
                continue
            for _, _, rows in table_rows(tab["doc"]):
                for bid, cells in rows:
                    if bid not in statuses or not cells:
                        continue
                    if cells[0].isdigit():
                        items.append({"kind": "question", "tab_key": tab["key"], "rid": bid, "number": int(cells[0]),
                                      "text": cells[1] if len(cells) > 1 else "",
                                      "why": cells[2] if len(cells) > 2 else "", "status": statuses[bid]})
                    else:
                        items.append({"kind": "handoff", "tab_key": tab["key"], "rid": bid, "text": cells[0],
                                      "what": cells[1] if len(cells) > 1 else "", "status": statuses[bid]})
    for ann in repo.list_annotations(conn, slug):
        if ann.get("resolved_at") or ann.get("orphaned_at"):
            continue
        comments = [m for m in ann.get("messages") or [] if m.get("kind") == "comment"]
        if any(me.actor_id in (m.get("mentions") or []) for m in comments):
            items.append({"kind": "mention", "annotation_id": ann["id"], "tab_key": ann["tab_key"],
                          "text": (comments[-1].get("body") or "")[:120]})
    return items
