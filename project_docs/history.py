"""專案文件的系統紀錄：算出每次存檔改了哪幾段，並把所有紀錄排成一條時間線給工程查。

畫面上不顯示這些細節；要知道「誰在什麼時候改了什麼」時，在正式機跑：

    python -m project_docs.history ad-data                              # 全部分頁、全部時間
    python -m project_docs.history ad-data --tab handoff --since 2026-10-14
    python -m project_docs.history ad-data --diff                       # 另外印出每一筆版本跟上一筆差在哪

連線用 OPENBENCH_DB_* 環境變數。只讀，不寫任何東西。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from project_docs import repository as repo
from project_docs.doc_schema import doc_text

TAIPEI = timezone(timedelta(hours=8))
MAX_TEXT = 2000  # 一段最多記這麼多字，超過的截斷並寫出原本幾個字


# ---------- 這次存檔改了哪幾段 ----------

def _clip(text: str) -> str:
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + f"…（共 {len(text)} 字）"


def _bid(node):
    return (node.get("attrs") or {}).get("bid") if isinstance(node, dict) else None


def _same(a, b) -> bool:
    return json.dumps(a, ensure_ascii=False, sort_keys=True) == json.dumps(b, ensure_ascii=False, sort_keys=True)


def _row_text(row) -> str:
    return " | ".join(doc_text(cell).replace("\n", " / ") for cell in row.get("content") or [])


def _block_text(node) -> str:
    if node.get("type") == "table":
        return "\n".join(_row_text(row) for row in node.get("content") or [])
    return doc_text({"type": "doc", "content": [node]})


def _items(node) -> list:
    return [(_bid(child), child) for child in (node or {}).get("content") or []]


def _order(items, other) -> list:
    return [key for key, _ in items if key in other]


def _row_changes(old_table, new_table) -> list[dict] | None:
    old_rows, new_rows = _items(old_table), _items(new_table)
    if any(key is None for key, _ in old_rows + new_rows):
        return None
    before, after = dict(old_rows), dict(new_rows)
    rows = []
    for rid, row in new_rows:
        prev = before.get(rid)
        if prev is None:
            rows.append({"row": rid, "change": "added", "after": _clip(_row_text(row))})
        elif not _same(row, prev):
            a, b = _row_text(prev), _row_text(row)
            rows.append({"row": rid, "change": "changed" if a != b else "format", "before": _clip(a), "after": _clip(b)})
    for rid, row in old_rows:
        if rid not in after:
            rows.append({"row": rid, "change": "removed", "before": _clip(_row_text(row))})
    if _order(old_rows, after) != _order(new_rows, before):
        rows.append({"change": "reordered"})
    return rows


def doc_changes(old_doc, new_doc) -> list[dict]:
    """兩份內文差在哪：一段一段比，表格再一列一列比。只記字，格式改了記「只改格式」。"""

    old_blocks, new_blocks = _items(old_doc), _items(new_doc)
    if any(key is None for key, _ in old_blocks + new_blocks):
        # 還沒有段落編號的舊內容：整頁比
        if _same(old_doc, new_doc):
            return []
        a, b = doc_text(old_doc or {}), doc_text(new_doc or {})
        return [{"type": "doc", "change": "changed" if a != b else "format", "before": _clip(a), "after": _clip(b)}]
    before, after = dict(old_blocks), dict(new_blocks)
    out = []
    for bid, node in new_blocks:
        old = before.get(bid)
        if old is None:
            out.append({"bid": bid, "type": node.get("type"), "change": "added", "after": _clip(_block_text(node))})
        elif not _same(node, old):
            if node.get("type") == "table" and old.get("type") == "table":
                rows = _row_changes(old, node)
                if rows is not None:
                    out.append({"bid": bid, "type": "table", "change": "changed", "rows": rows})
                    continue
            a, b = _block_text(old), _block_text(node)
            out.append({"bid": bid, "type": node.get("type"), "change": "changed" if a != b else "format",
                        "before": _clip(a), "after": _clip(b)})
    for bid, node in old_blocks:
        if bid not in after:
            out.append({"bid": bid, "type": node.get("type"), "change": "removed", "before": _clip(_block_text(node))})
    if _order(old_blocks, after) != _order(new_blocks, before):
        out.append({"change": "reordered"})
    return out


# ---------- 時間線（給工程查） ----------

TYPE_LABEL = {"paragraph": "段落", "heading": "標題", "bulletList": "清單", "orderedList": "編號清單",
              "taskList": "勾選清單", "table": "表格", "image": "圖片", "blockquote": "引用", "horizontalRule": "分隔線",
              "doc": "整頁"}
CHANGE_LABEL = {"added": "新增", "removed": "刪除", "changed": "修改", "format": "只改格式"}


def _local(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.astimezone(TAIPEI).strftime("%Y-%m-%d %H:%M:%S")


def _quote(text) -> str:
    text = str(text or "").replace("\n", " / ")
    if not text.strip():
        return "「（空白）」"
    return "「" + (text if len(text) <= 120 else text[:120] + "…") + "」"


def _pair(item) -> str:
    if item["change"] == "added":
        return _quote(item.get("after"))
    if item["change"] == "removed":
        return _quote(item.get("before"))
    if item["change"] == "format":
        return _quote(item.get("after"))
    return f"{_quote(item.get('before'))} → {_quote(item.get('after'))}"


def describe_changes(changes, indent="      ") -> list[str]:
    lines = []
    for change in changes or []:
        if change.get("change") == "reordered":
            lines.append(indent + "調整了段落順序")
            continue
        label = TYPE_LABEL.get(change.get("type"), change.get("type") or "")
        if change.get("type") == "doc" and change.get("change") == "format":
            lines.append(indent + "字沒有變，只有格式或段落編號不同")
            continue
        if "rows" in change:
            lines.append(f"{indent}改了表格：")
            for row in change["rows"]:
                if row.get("change") == "reordered":
                    lines.append(indent + "  調整了列的順序")
                else:
                    lines.append(f"{indent}  {CHANGE_LABEL[row['change']]}一列：{_pair(row)}")
            continue
        lines.append(f"{indent}{CHANGE_LABEL.get(change['change'], change['change'])}{label}：{_pair(change)}")
    return lines


def _audit_sentence(row, tabs) -> str:
    d, action = row["detail"], row["action"]
    tab = tabs.get(row["tab_key"] or "", row["tab_key"] or "")
    if action == "edit":
        how = "整份改寫" if d.get("via") == "rewrite" else "改了"
        return f"{how}「{tab}」的內文（第 {d.get('revision', '?')} 筆）"
    if action == "revision_restore":
        return f"把「{tab}」換回第 {d.get('from_revision')} 筆的內容（存成第 {d.get('new_revision')} 筆）"
    if action == "tab_create":
        parent = f"，放在「{tabs.get(d.get('parent_key'), d.get('parent_key'))}」底下" if d.get("parent_key") else ""
        return f"新增分頁「{d.get('title')}」{parent}"
    if action == "tab_update":
        parts = []
        if "title" in d:
            parts.append(f"改名 {_quote(d['title'][0])} → {_quote(d['title'][1])}")
        if "parent_key" in d:
            old, new = (tabs.get(k, k) if k else "第一層" for k in d["parent_key"])
            parts.append(f"搬到「{new}」（原本在「{old}」）")
        if "move" in d:
            parts.append("往上移" if d["move"] == "up" else "往下移")
        return f"調整分頁「{tab}」：" + "、".join(parts)
    if action == "tab_delete":
        return f"刪除分頁「{d.get('title') or tab}」"
    if action == "tab_restore":
        return f"復原分頁「{d.get('title') or tab}」"
    if action == "annotation_delete":
        what = _quote(d.get("quote")) if d.get("quote") else f"整列對話（{d.get('row')}）"
        return (f"刪除標註 #{row['target']} {what}（原本是 {d.get('created_by_name') or '?'} 標的，"
                f"留言 {d.get('comments', 0)} 則）")
    if action == "annotation_resolve":
        return f"把標註 #{row['target']} {_quote(d.get('quote'))} 按了解決"
    if action == "annotation_reopen":
        return f"把標註 #{row['target']} {_quote(d.get('quote'))} 改回未解決"
    if action == "annotation_reconfirm":
        return f"重新確認標註 #{row['target']} {_quote(d.get('quote'))}"
    if action == "annotation_reattach":
        return f"把標註 #{row['target']} 從 {_quote(d.get('from'))} 換到 {_quote(d.get('to'))}"
    if action == "annotation_style":
        return f"把標註 #{row['target']} 的樣式從 {d.get('from')} 改成 {d.get('to')}"
    if action == "comment_delete":
        return f"刪除自己的留言 #{row['target']} {_quote(d.get('body'))}"
    if action == "annotations_reanchored":
        parts = []
        for key, label in (("removed", "拿掉螢光筆／劃線"), ("orphaned", "標註找不到原文"),
                           ("moved", "標註跟著字移動"), ("reconfirm", "已確認的字被改、要重新確認"),
                           ("rows_gone", "整列對話的那一列被刪"), ("rows_back", "整列對話的那一列回來了")):
            if d.get(key):
                parts.append(f"{label} {len(d[key])} 則")
        return f"改內文時，「{tab}」的標註跟著調整：" + "、".join(parts)
    return f"{action} {json.dumps(d, ensure_ascii=False)[:200]}"


SESSION_LABEL = (("create", "建立分頁"), ("system-ids", "系統補上段落編號"), ("restore-", "換回舊版"),
                 ("rewrite-", "整份改寫"))


def _session_label(session_id: str) -> str:
    for prefix, label in SESSION_LABEL:
        if session_id == prefix or (prefix.endswith("-") and session_id.startswith(prefix)):
            return f"（{label}）"
    return ""


def timeline(conn, slug: str, *, tab_key=None, since=None, diff=False) -> list[str]:
    """所有紀錄排成一條時間線。同一個交易裡的事件時間相同，照「標註 → 版本 → 系統紀錄 → 留言與欄位」排。"""

    names = repo.member_names(conn)
    tabs = {t["key"]: t["title"] for t in repo.list_tabs(conn, slug) + repo.list_tabs(conn, slug, deleted=True)}

    def who(actor_id):
        return names.get(actor_id or "", "系統" if not actor_id else "（不在名單）")

    audits = repo.audit_rows(conn, slug, tab_key=tab_key, since=since)
    # 有系統紀錄的版本，紀錄裡已經寫了第幾筆和改了什麼，不再另外列一次
    covered = {(r["tab_key"], (r["detail"] or {}).get("revision") or (r["detail"] or {}).get("new_revision"))
               for r in audits if r["action"] in ("edit", "revision_restore")}
    events = []  # (時間, 排序, 序號, 文字行)
    previous = {}
    for rev in repo.revision_rows(conn, slug, tab_key=tab_key):
        prev = previous.get(rev["tab_key"])
        previous[rev["tab_key"]] = rev
        if (since is not None and rev["at"] < since) or (rev["tab_key"], rev["revision"]) in covered:
            continue
        lines = [f"{who(rev['actor_id'])} 存了「{tabs.get(rev['tab_key'], rev['tab_key'])}」"
                 f"第 {rev['revision']} 筆{_session_label(rev['session_id'])}"]
        if diff and prev is not None:
            lines += describe_changes(doc_changes(prev["doc"], rev["doc"])) or ["      （內文沒有差別）"]
        events.append((rev["at"], 1, rev["revision"], lines))
    for row in audits:
        lines = [f"{who(row['actor_id'])} {_audit_sentence(row, tabs)}"]
        if row["action"] in ("edit", "revision_restore"):
            lines += describe_changes(row["detail"].get("changes"))
        events.append((row["at"], 2, row["id"], lines))
    for act in repo.activity_rows(conn, slug, tab_key=tab_key, since=since):
        tab = tabs.get(act["tab_key"], act["tab_key"])
        if act["kind"] == "comment":
            gone = f"（{_local(act['deleted_at'])} 刪除）" if act["deleted_at"] else ""
            text = f"在「{tab}」留言 {_quote(act['body'])}{gone}"
        else:
            text = f"把「{tab}」的「{act['field_label'] or '欄位'}」從 {_quote(act['old'])} 改成 {_quote(act['new'])}"
        events.append((act["at"], 3, act["id"], [f"{who(act['actor_id'])} {text}"]))
    for ann in repo.annotation_rows(conn, slug, tab_key=tab_key):
        tab = tabs.get(ann["tab_key"], ann["tab_key"])
        what = _quote(ann["anchor"].get("quote")) if ann["kind"] == "text" else f"第 {ann['anchor'].get('rid')} 列的整列對話"
        kind = "、".join(x for x in (
            {"hl": "螢光筆", "ul": "劃線"}.get(ann["style"] or ""),
            {"q": "問題", "fix": "要修改", "ok": "已確認"}.get(ann["label"] or ""),
        ) if x) or "說明"
        if since is None or ann["at"] >= since:
            gone = f"（{_local(ann['deleted_at'])} 已刪除）" if ann["deleted_at"] else ""
            events.append((ann["at"], 0, ann["id"], [f"{who(ann['actor_id'])} 在「{tab}」標註 #{ann['id']} {what}（{kind}）{gone}"]))
        if ann["resolved_at"] and (since is None or ann["resolved_at"] >= since):
            events.append((ann["resolved_at"], 0, ann["id"], [f"{who(ann['resolved_by'])} 把標註 #{ann['id']} 按了解決（目前狀態）"]))
    events.sort(key=lambda e: (e[0], e[1], e[2]))
    out = []
    for at, _, _, lines in events:
        out.append(f"{_local(at)}  {lines[0]}")
        out.extend(lines[1:])
    return out


def _parse_since(value: str | None):
    if not value:
        return None
    day = datetime.strptime(value, "%Y-%m-%d")
    return day.replace(tzinfo=TAIPEI)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="專案文件的系統紀錄（只讀）")
    parser.add_argument("slug")
    parser.add_argument("--tab")
    parser.add_argument("--since", help="YYYY-MM-DD（台北時間）")
    parser.add_argument("--diff", action="store_true", help="另外印出每一筆版本跟上一筆差在哪")
    args = parser.parse_args(argv)
    from trend_migration import open_connection

    conn = open_connection()
    try:
        lines = timeline(conn, args.slug, tab_key=args.tab, since=_parse_since(args.since), diff=args.diff)
    finally:
        conn.rollback()
        conn.close()
    print("\n".join(lines) if lines else "（沒有紀錄）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
