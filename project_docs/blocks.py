"""一塊一塊存：把前端送來的 ops 套到文件上（純函式；資料庫在 repository）。

ops 的格式見 docs/superpowers/specs/2026-10-13-project-docs-annotations-design.md「一塊一塊存」。
base 是送出的人上次從伺服器拿到的那一塊；跟現在的不一樣＝剛被別人改過，這一筆不套用、回 conflict，
其他筆照樣套用。owner／created 一律由這裡決定，送來的值不算。

2026-10-15 起大家一起編輯（負責人：「共同編輯的專案系統」）：名單上的人都能改、刪任何一塊和任何一列，
也能貼圖、調順序。擋的只剩別人正拿著編輯鎖、和 base 過期；誰改了什麼記在系統紀錄（audit_log）。
owner／created 只記「這一塊是誰加的」，不再決定誰能改。
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from project_docs.doc_schema import BLOCK_TYPES, ID_RE

MAX_OPS = 200


class OpsError(ValueError):
    """ops 本身格式不對（回 400）。"""


@dataclass(frozen=True)
class Actor:
    actor_id: str
    is_admin: bool


@dataclass
class OpsResult:
    doc: dict
    applied: int = 0
    conflicts: list = field(default_factory=list)


def _attrs(node) -> dict:
    return node.get("attrs") if isinstance(node, dict) and isinstance(node.get("attrs"), dict) else {}


def _bid(node):
    return _attrs(node).get("bid")


def _own(node, owner, created) -> None:
    attrs = dict(_attrs(node))
    attrs["owner"], attrs["created"] = owner, created
    node["attrs"] = attrs


def _keep_row_owners(old_table, new_table, new_owner) -> None:
    """整張表換掉時（管理者改表頭或欄數），原本就有的列保留原本的 owner／created。"""

    old = {_bid(row): _attrs(row) for row in old_table.get("content") or []}
    for row in new_table.get("content") or []:
        before = old.get(_bid(row))
        if before is not None:
            _own(row, before.get("owner"), before.get("created"))
        else:
            _own(row, *new_owner)


def apply_ops(doc: dict, ops, actor: Actor, *, locks: dict, now: str) -> OpsResult:
    if not isinstance(ops, list) or len(ops) > MAX_OPS:
        raise OpsError("ops 格式不對")
    doc = copy.deepcopy(doc)
    blocks = doc.setdefault("content", [])
    result = OpsResult(doc=doc)
    new_owner = (None, None) if actor.is_admin else (actor.actor_id, now)

    def find(bid) -> int:
        for index, block in enumerate(blocks):
            if _bid(block) == bid:
                return index
        return -1

    def conflict(unit, reason, node=None, owner=None) -> None:
        item = {"unit": unit, "reason": reason}
        if node is not None:
            item["node"] = node
        if owner:
            item["owner"] = owner
        result.conflicts.append(item)

    def held_by_other(unit):
        holder = locks.get(unit)
        return holder if holder and holder != actor.actor_id else None

    def insert_at(after) -> int:
        if after is None:
            return 0
        index = find(after) if isinstance(after, str) else -1
        if index >= 0:
            return index + 1
        # 前面那一塊不在了：接在最後（最後一個空段落之前）
        last = blocks[-1] if blocks else None
        if last and last.get("type") == "paragraph" and not last.get("content"):
            return len(blocks) - 1
        return len(blocks)

    for op in ops:
        if not isinstance(op, dict):
            raise OpsError("ops 格式不對")
        kind = op.get("op")
        if kind == "put":
            bid, node = op.get("bid"), op.get("node")
            if not isinstance(bid, str) or not ID_RE.match(bid) or not isinstance(node, dict):
                raise OpsError("區塊格式不對")
            if node.get("type") not in BLOCK_TYPES:
                conflict(bid, "forbidden")
                continue
            node = copy.deepcopy(node)
            index = find(bid)
            if index >= 0:
                current = blocks[index]
                holder = held_by_other(bid)
                if current.get("type") == "table":
                    holder = holder or next((held_by_other(_bid(r)) for r in current.get("content", []) if held_by_other(_bid(r))), None)
                if holder:
                    conflict(bid, "locked", current, holder)
                    continue
                if op.get("base") != current:
                    conflict(bid, "changed", current)
                    continue
                before = _attrs(current)
                attrs = dict(_attrs(node))
                attrs.update(bid=bid, owner=before.get("owner"), created=before.get("created"))
                node["attrs"] = attrs
                if node.get("type") == "table":
                    _keep_row_owners(current, node, new_owner)
                blocks[index] = node
            else:
                if op.get("base") is not None:
                    conflict(bid, "gone")
                    continue
                attrs = dict(_attrs(node))
                attrs["bid"] = bid
                node["attrs"] = attrs
                _own(node, *new_owner)
                if node.get("type") == "table":
                    for row in node.get("content") or []:
                        _own(row, *new_owner)
                blocks.insert(insert_at(op.get("after")), node)
            result.applied += 1
        elif kind == "del":
            bid = op.get("bid")
            index = find(bid) if isinstance(bid, str) else -1
            if index < 0:
                continue  # 已經不在了
            current = blocks[index]
            holder = held_by_other(bid)
            if current.get("type") == "table":
                holder = holder or next((held_by_other(_bid(r)) for r in current.get("content", []) if held_by_other(_bid(r))), None)
            if holder:
                conflict(bid, "locked", current, holder)
                continue
            if op.get("base") != current:
                conflict(bid, "changed", current)
                continue
            del blocks[index]
            result.applied += 1
        elif kind in ("put_row", "del_row"):
            table_bid, rid = op.get("table"), op.get("rid")
            if not isinstance(table_bid, str) or not isinstance(rid, str) or not ID_RE.match(rid):
                raise OpsError("表格列格式不對")
            index = find(table_bid)
            if index < 0 or blocks[index].get("type") != "table":
                conflict(rid, "gone")
                continue
            table = blocks[index]
            rows = table.setdefault("content", [])
            position = next((i for i, row in enumerate(rows) if _bid(row) == rid), -1)
            holder = held_by_other(rid) or held_by_other(table_bid)
            if kind == "del_row":
                if position < 0:
                    continue
                current = rows[position]
                if holder:
                    conflict(rid, "locked", current, holder)
                    continue
                if op.get("base") != current:
                    conflict(rid, "changed", current)
                    continue
                del rows[position]
                result.applied += 1
                continue
            node = op.get("node")
            if not isinstance(node, dict) or node.get("type") != "tableRow":
                raise OpsError("表格列格式不對")
            width = len(rows[0].get("content") or []) if rows else 0
            if width and len(node.get("content") or []) != width:
                conflict(rid, "shape")
                continue
            node = copy.deepcopy(node)
            if position >= 0:
                current = rows[position]
                if holder:
                    conflict(rid, "locked", current, holder)
                    continue
                if op.get("base") != current:
                    conflict(rid, "changed", current)
                    continue
                before = _attrs(current)
                attrs = dict(_attrs(node))
                attrs.update(bid=rid, owner=before.get("owner"), created=before.get("created"))
                node["attrs"] = attrs
                rows[position] = node
            else:
                if holder:
                    conflict(rid, "locked", owner=holder)
                    continue
                if op.get("base") is not None:
                    conflict(rid, "gone")
                    continue
                attrs = dict(_attrs(node))
                attrs["bid"] = rid
                node["attrs"] = attrs
                _own(node, *new_owner)
                after = op.get("after")
                at = next((i for i, row in enumerate(rows) if _bid(row) == after), None)
                rows.insert(at + 1 if at is not None else len(rows), node)
            result.applied += 1
        elif kind == "order":
            wanted = op.get("bids")
            if not isinstance(wanted, list):
                raise OpsError("排序格式不對")
            remaining = {_bid(block): block for block in blocks}
            ordered = [remaining.pop(bid) for bid in wanted if isinstance(bid, str) and bid in remaining]
            ordered.extend(block for block in blocks if _bid(block) in remaining)  # 沒列到的照原本順序接在後面
            blocks[:] = ordered
            result.applied += 1
        else:
            raise OpsError("不認得的 op")
    return result
