"""畫面上的「修改紀錄」：誰在什麼時候改了哪幾處，以及「改回這一段」要怎麼改。

10/15 起大家一起編輯（負責人：「共同編輯的專案系統」）：大家都能改字，所以大家都要看得到誰改了什麼，改錯了能改回。

資料來源是每一筆版本（tab_revision，整份內文）：同一個人連續改的存在同一筆，換人就是新的一筆。
所以「這一次改了什麼」＝這次的最後一筆跟這次之前那一筆比；改回一段＝拿之前那一筆裡的那一段放回去，
粗體、連結都一起回來。狀態、可填格、勾選不在內文裡，從欄位紀錄（activity）來。

這裡全是純函式；讀資料庫、權限、寫回在 service.history_payload／revert_change。
"""
from __future__ import annotations

import copy
import difflib
import json
import re
from datetime import timedelta

from project_docs.doc_schema import doc_text

GAP = timedelta(minutes=10)  # 同一個人停超過 10 分鐘，算新的一次
CONTEXT = 16  # 改的地方前後各留幾個字
LIMIT = 280  # 一處最多顯示幾個字
TINY = 2  # 兩處修改中間只隔這麼少的相同字：併成一處，不要切成碎片

WHAT = {"heading": "一個標題", "table": "一個表格", "image": "一張圖", "horizontalRule": "一條分隔線"}
THIS = {"heading": "這個標題", "table": "這個表格", "image": "這張圖", "horizontalRule": "這條分隔線"}
EMPTY = {"image": "（圖片）", "horizontalRule": "（分隔線）", "table": "（空白表格）"}
CHECK = {"true": "已勾", "false": "沒勾"}
SPECIAL_SESSIONS = (("revert-", "revert"), ("restore-", "restore"), ("rewrite-", "rewrite"))


# ---------- 小工具 ----------

def _attrs(node) -> dict:
    return node.get("attrs") if isinstance(node, dict) and isinstance(node.get("attrs"), dict) else {}


def _bid(node):
    return _attrs(node).get("bid")


def _children(node) -> list:
    return [(_bid(child), child) for child in (node or {}).get("content") or []]


def _norm(node):
    """比內容用：拿掉「誰加的、什麼時候加的」（owner／created 不算內容）。"""

    if not isinstance(node, dict):
        return node
    out = copy.deepcopy(node)
    for item in [out] + (out.get("content") or [] if out.get("type") == "table" else []):
        attrs = _attrs(item)
        if attrs:
            item["attrs"] = {k: v for k, v in attrs.items() if k not in ("owner", "created")}
    return out


def _same(a, b) -> bool:
    return json.dumps(_norm(a), ensure_ascii=False, sort_keys=True) == json.dumps(_norm(b), ensure_ascii=False, sort_keys=True)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def row_text(row) -> str:
    return "｜".join(doc_text(cell).replace("\n", " ").strip() for cell in (row or {}).get("content") or [])


def block_text(node) -> str:
    if not node:
        return ""
    if node.get("type") == "table":
        return "\n".join(row_text(r) for r in node.get("content") or [])
    return doc_text({"type": "doc", "content": [node]}).strip()


def _shown(text: str, kind=None) -> str:
    return text if text.strip() else EMPTY.get(kind, "（空白一行）")


def _block(document, bid):
    return next((node for key, node in _children(document) if key == bid), None)


def _row(table, rid):
    return next((node for key, node in _children(table) if key == rid), None)


def locate(document, bid, rid=None):
    node = _block(document, bid)
    return _row(node, rid) if rid is not None else node


# ---------- 改前改後對照 ----------

def text_segments(before: str, after: str) -> list[list[str]]:
    """[["=", 沒變的], ["-", 刪掉的], ["+", 加上的], …]；沒變的只留改動前後幾個字。"""

    if before == after:
        return [["=", _clip(before, 120)]]
    chunks: list[list[str]] = []  # ["=", 字] 或 ["~", 刪掉的, 加上的]
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, before, after, autojunk=False).get_opcodes():
        if tag == "equal":
            chunks.append(["=", before[i1:i2]])
        elif chunks and chunks[-1][0] == "~":
            chunks[-1][1] += before[i1:i2]
            chunks[-1][2] += after[j1:j2]
        else:
            chunks.append(["~", before[i1:i2], after[j1:j2]])
    merged: list[list[str]] = []
    for chunk in chunks:
        if (chunk[0] == "~" and len(merged) >= 2 and merged[-1][0] == "=" and len(merged[-1][1]) <= TINY
                and merged[-2][0] == "~"):
            same_text = merged.pop()[1]
            merged[-1][1] += same_text + chunk[1]
            merged[-1][2] += same_text + chunk[2]
        else:
            merged.append(chunk)
    out: list[list[str]] = []
    last = len(merged) - 1
    for index, chunk in enumerate(merged):
        if chunk[0] == "~":
            if chunk[1]:
                out.append(["-", chunk[1]])
            if chunk[2]:
                out.append(["+", chunk[2]])
            continue
        text = chunk[1]
        if index == 0 and len(text) > CONTEXT:
            text = "…" + text[-CONTEXT:]
        elif index == last and len(text) > CONTEXT:
            text = text[:CONTEXT] + "…"
        elif 0 < index < last and len(text) > 2 * CONTEXT:
            text = text[:CONTEXT] + "…" + text[-CONTEXT:]
        out.append(["=", text])
    kept, total = [], 0
    for kind, text in out:
        if total + len(text) > LIMIT:
            if LIMIT - total > 0:
                kept.append([kind, text[:LIMIT - total]])
            kept.append(["=", "…"])
            break
        kept.append([kind, text])
        total += len(text)
    return kept


def _block_change(change, bid, old, new) -> dict:
    node = new or old
    kind = node.get("type")
    what, this = WHAT.get(kind, "一段"), THIS.get(kind, "這一段")
    if change == "added":
        label, button = "新增" + what, "拿掉" + this
        segments = [["+", _clip(_shown(block_text(new), kind), 160)]]
    elif change == "removed":
        label, button = "刪掉" + what, "加回" + this
        segments = [["-", _clip(_shown(block_text(old), kind), 160)]]
    else:
        a, b = block_text(old), block_text(new)
        label, button = ("改了" + what if a != b else "改了" + what + "的格式"), "改回" + this
        segments = text_segments(_shown(a, kind), _shown(b, kind))
    return {"key": bid, "bid": bid, "change": change, "label": label, "button": button, "segments": segments}


def _table_title(document, bid) -> str:
    title = ""
    for key, node in _children(document):
        if key == bid:
            return title
        if node.get("type") == "heading":
            title = block_text(node)
    return title


def _shell(table) -> dict:
    return {k: v for k, v in _norm(table).items() if k != "content"}


def _row_changes(old_table, new_table, bid, title):
    olds, news = _children(old_table), _children(new_table)
    if any(key is None for key, _ in olds + news) or not _same(_shell(old_table), _shell(new_table)):
        return None  # 改到表格本身（欄數、欄寬）：整個表格算一處
    name = f"表格「{title}」" if title else "表格"
    before, after = dict(olds), dict(news)
    out = []

    def item(rid, change, label, button, segments):
        return {"key": f"{bid}/{rid}", "bid": bid, "rid": rid, "change": change, "label": label,
                "button": button, "segments": segments, **_media_versions(before.get(rid), after.get(rid))}

    removed_after = _removed_positions(olds, after)
    for rid in removed_after.get(None, []):
        out.append(item(rid, "removed", f"{name}刪掉一列", "加回這一列", [["-", _clip(row_text(before[rid]), 160)]]))
    for rid, row in news:
        prev = before.get(rid)
        if prev is None:
            out.append(item(rid, "added", f"{name}新增一列", "拿掉這一列", [["+", _clip(row_text(row), 160)]]))
        elif not _same(prev, row):
            a, b = row_text(prev), row_text(row)
            label = f"{name}改了一列" if a != b else f"{name}一列改了格式"
            out.append(item(rid, "changed", label, "改回這一列", text_segments(a, b)))
        for gone in removed_after.get(rid, []):
            out.append(item(gone, "removed", f"{name}刪掉一列", "加回這一列", [["-", _clip(row_text(before[gone]), 160)]]))
    if [k for k, _ in olds if k in after] != [k for k, _ in news if k in before]:
        out.append({"key": f"{bid}/order", "label": f"調整了{name}的列順序", "button": None, "segments": []})
    return out


def _media_versions(before, after):
    def urls(value):
        return list(dict.fromkeys(re.findall(r"/projects/api/[a-z0-9-]+/assets/pa_[0-9a-f]{32}", json.dumps(value, ensure_ascii=False))))
    old, new = urls(before), urls(after)
    return {"media_before": old, "media_after": new} if old != new else {}


def _removed_positions(olds, after) -> dict:
    """刪掉的東西排在原本的位置：{前一個還在的 id（最前面是 None）: [刪掉的 id, …]}。"""

    out, anchor = {}, None
    for key, _ in olds:
        if key in after:
            anchor = key
        else:
            out.setdefault(anchor, []).append(key)
    return out


def block_changes(old_doc, new_doc) -> list[dict]:
    """這次改了哪幾處（照頁面上的順序）。每一處：key、label（給人看）、button（改回的按鈕字，不能改回是 None）、segments。"""

    olds, news = _children(old_doc), _children(new_doc)
    if any(key is None for key, _ in olds + news):
        if _same(old_doc, new_doc):
            return []
        a, b = doc_text(old_doc or {}), doc_text(new_doc or {})
        return [{"key": "doc", "label": "改了內文" if a != b else "改了格式", "button": None,
                 "segments": text_segments(a, b)}]
    before, after = dict(olds), dict(news)
    removed_after = _removed_positions(olds, after)
    out = [_block_change("removed", bid, before[bid], None) for bid in removed_after.get(None, [])]
    for bid, node in news:
        old = before.get(bid)
        if old is None:
            out.append(_block_change("added", bid, None, node))
        elif not _same(old, node):
            rows = None
            if node.get("type") == "table" and old.get("type") == "table":
                rows = _row_changes(old, node, bid, _table_title(new_doc, bid))
            out.extend(rows if rows is not None else [_block_change("changed", bid, old, node)])
        for gone in removed_after.get(bid, []):
            out.append(_block_change("removed", gone, before[gone], None))
    if [k for k, _ in olds if k in after] != [k for k, _ in news if k in before]:
        out.append({"key": "order", "label": "調整了段落順序", "button": None, "segments": []})
    return out


def _field_value(kind, value) -> str:
    if kind == "check":
        return CHECK.get(str(value), str(value))
    return str(value) if str(value or "").strip() else "（空白）"


def _field_changes(events, row_labels) -> list[dict]:
    """同一次裡同一格改了好幾次：只看最早的舊值和最後的新值；改回原樣就不列。"""

    order, first, last = [], {}, {}
    for event in events:
        fid = event["field_id"]
        if fid not in first:
            order.append(fid)
            first[fid] = event
        last[fid] = event
    out = []
    for fid in order:
        start, end = first[fid], last[fid]
        if start["old"] == end["new"]:
            continue
        kind = end["kind"]
        place = (row_labels or {}).get(end.get("anchor_id")) or ""
        label = "勾選" if kind == "check" else (end.get("field_label") or "這一格")
        segments = [["=", f"「{place}」"]] if place else []
        segments += [["-", _field_value(kind, start["old"])], ["=", " → "], ["+", _field_value(kind, end["new"])]]
        out.append({"key": f"f:{fid}", "field_id": fid, "anchor_id": end.get("anchor_id"), "label": label,
                    "button": "改回", "segments": segments, "value": start["old"], "after_activity": end["id"],
                    **_media_versions(start["old"], end["new"])})
    return out


# ---------- 排成一筆一筆 ----------

def _kind(session_id: str) -> str:
    for prefix, kind in SPECIAL_SESSIONS:
        if (session_id or "").startswith(prefix):
            return kind
    return "edit"


def build_groups(revisions, field_events, names, *, starts=None, titles=None, row_labels=None) -> list[dict]:
    """一筆＝同一個人連續改的一次（停 10 分鐘以上、或中間有別人改，就是新的一筆），新的在前。

    revisions：版本（tab_key、revision、doc、session_id、actor_id、at＝最後一次存的時間）；
    field_events：欄位紀錄（id、tab_key、kind、field_id、anchor_id、field_label、old、new、actor_id、at）；
    starts：{(tab_key, revision): 這一筆第一次存的時間}（系統紀錄有記，沒有就用 at）；
    row_labels：{tab_key: {列的 id: 那一列的名字}}。
    """

    starts, titles, row_labels = starts or {}, titles or {}, row_labels or {}
    by_tab: dict = {}
    for item in revisions:
        by_tab.setdefault(item["tab_key"], []).append(item)
    fields_by_tab: dict = {}
    for event in field_events:
        fields_by_tab.setdefault(event["tab_key"], []).append(event)
    groups = []
    for tab_key in sorted(set(by_tab) | set(fields_by_tab)):
        revs = sorted(by_tab.get(tab_key, []), key=lambda r: r["revision"])
        events = []
        for index, item in enumerate(revs):
            if index == 0:
                events.append({"type": "rev", "kind": "create", "i": 0, "actor": item["actor_id"],
                               "start": item["at"], "end": item["at"]})
            elif item["actor_id"]:  # 系統自己存的（補段落編號）不列
                events.append({"type": "rev", "kind": _kind(item["session_id"]), "i": index, "actor": item["actor_id"],
                               "start": min(starts.get((tab_key, item["revision"]), item["at"]), item["at"]),
                               "end": item["at"]})
        for event in fields_by_tab.get(tab_key, []):
            events.append({"type": "field", "kind": "edit", "actor": event["actor_id"], "start": event["at"],
                           "end": event["at"], "event": event})
        events.sort(key=lambda e: (e["start"], 0 if e["type"] == "rev" else 1))
        current = None
        for event in events:
            if (current and current["kind"] == "edit" and event["kind"] == "edit"
                    and current["actor"] == event["actor"] and event["start"] - current["end"] < GAP):
                current["end"] = max(current["end"], event["end"])
            else:
                current = {"tab": tab_key, "kind": event["kind"], "actor": event["actor"], "first": None, "last": None,
                           "fields": [], "end": event["end"]}
                groups.append((current, revs))
            if event["type"] == "rev":
                if current["first"] is None:
                    current["first"] = event["i"]
                current["last"] = event["i"]
            else:
                current["fields"].append(event["event"])
    out = []
    for group, revs in groups:
        changes, from_rev, to_rev = [], None, None
        if group["kind"] != "create" and group["first"] is not None:
            before, after = revs[group["first"] - 1], revs[group["last"]]
            from_rev, to_rev = before["revision"], after["revision"]
            changes = block_changes(before["doc"], after["doc"])
        changes += _field_changes(group["fields"], row_labels.get(group["tab"]))
        actor = group["actor"]
        out.append({
            "id": f"{group['tab']}:{group['kind']}:{from_rev}-{to_rev}:{group['end'].isoformat()}",
            "tab_key": group["tab"], "tab_title": titles.get(group["tab"], ""), "kind": group["kind"],
            "actor_id": actor, "name": names.get(actor or "") or ("系統" if not actor else "（不在名單）"),
            "at": group["end"].isoformat(), "from_rev": from_rev, "to_rev": to_rev, "changes": changes,
        })
    out.sort(key=lambda g: g["at"], reverse=True)
    return out


# ---------- 改回 ----------

def _before_anchor(document, current, key, *, rid_of=None):
    """要放回去的東西原本接在誰後面：往前找第一個現在還在的。"""

    items = _children(_block(document, rid_of) if rid_of else document)
    present = {k for k, _ in _children(_block(current, rid_of) if rid_of else current)}
    previous = None
    for k, _ in items:
        if k == key:
            return previous
        if k in present:
            previous = k
    return previous


def revert_plan(before_doc, after_doc, current_doc, bid, rid=None) -> dict:
    """把 before 裡的那一段（或那一列）放回現在的內文。回 {"state", "ops", "preview"}。

    state：ok／already（現在已經是改之前的樣子）／later（之後又有人改過，要先問）／gone（那個表格不在了）。
    ops 交給 blocks.apply_ops，跟平常存檔同一套規則（別人拿著編輯鎖就不會套用）。
    """

    if rid is None:
        target, was, now = _block(before_doc, bid), _block(after_doc, bid), _block(current_doc, bid)
        kind = (target or was or now or {}).get("type")
        preview = _shown(block_text(target), kind) if target else "（拿掉" + THIS.get(kind, "這一段") + "）"
        if _same(now, target):
            return {"state": "already", "ops": [], "preview": preview}
        if target is None:
            ops = [{"op": "del", "bid": bid, "base": now}]
        elif now is not None:
            ops = [{"op": "put", "bid": bid, "node": target, "base": now}]
        else:
            ops = [{"op": "put", "bid": bid, "node": target, "after": _before_anchor(before_doc, current_doc, bid)}]
    else:
        table_now = _block(current_doc, bid)
        if not table_now or table_now.get("type") != "table":
            return {"state": "gone", "ops": [], "preview": ""}
        target, was, now = _row(_block(before_doc, bid), rid), _row(_block(after_doc, bid), rid), _row(table_now, rid)
        preview = row_text(target) if target else "（拿掉這一列）"
        if _same(now, target):
            return {"state": "already", "ops": [], "preview": preview}
        if target is None:
            ops = [{"op": "del_row", "table": bid, "rid": rid, "base": now}]
        elif now is not None:
            ops = [{"op": "put_row", "table": bid, "rid": rid, "node": target, "base": now}]
        else:
            ops = [{"op": "put_row", "table": bid, "rid": rid, "node": target,
                    "after": _before_anchor(before_doc, current_doc, rid, rid_of=bid)}]
    return {"state": "ok" if _same(now, was) else "later", "ops": ops, "preview": preview}


def later_edits(revisions, bid, rid, was) -> list[dict]:
    """那一段（或那一列）在 was 之後又被誰改過：[{actor_id, at}]，照時間。revisions 是之後的版本，照版本號排。"""

    out, previous = [], was
    for item in revisions:
        node = locate(item["doc"], bid, rid)
        if not _same(node, previous):
            out.append({"actor_id": item["actor_id"], "at": item["at"]})
            previous = node
    return out
