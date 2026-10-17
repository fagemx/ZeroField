"""專案文件內容（ProseMirror／TipTap JSON）的白名單檢查與索引。

存進資料庫前一定過 validate_doc：
- 不認得的節點 → DocError（只有被改過的瀏覽器才送得出來）。
- 不認得的屬性、標記丟掉；不安全的連結拿掉連結；不是本專案上傳的圖片拿掉。
- 錨點 bid（第一層區塊、標題、表格列）與欄位 fid（狀態、可填格、勾選項）缺了或重複就補新的。
  有修過就回傳 repaired=True，呼叫端要把修過的內容交回編輯器。
- 第一層區塊與表格列另有 owner（誰新增的；null＝管理者寫的本文）與 created（新增時間）。10/15 起只記誰加的，不決定誰能改。
"""
from __future__ import annotations

import json
import re
import secrets
import hashlib

STATUSES = ("未開始", "進行中", "生圖中", "生影片中", "等待審核", "重抽", "等待回覆", "卡住", "已完成")
DEFAULT_STATUS = STATUSES[0]
MAX_DOC_BYTES = 2_000_000
MAX_DEPTH = 40
ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,40}$")
TAB_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
PAGE_ANCHOR = "_page"

LEAF_NODES = {"text", "hardBreak", "image", "horizontalRule", "status", "fill"}
NODE_TYPES = {
    "doc", "paragraph", "heading", "text", "hardBreak", "bulletList", "orderedList", "listItem",
    "taskList", "taskItem", "table", "tableRow", "tableHeader", "tableCell", "image",
    "horizontalRule", "blockquote", "status", "fill",
}
MARK_TYPES = {"bold", "italic", "strike", "code", "underline", "link"}
ID_ATTR = {"heading": "bid", "tableRow": "bid", "taskItem": "fid", "status": "fid", "fill": "fid"}
ID_PREFIX = {"bid": "b", "fid": "f"}
BLOCK_TYPES = frozenset({"paragraph", "heading", "bulletList", "orderedList", "taskList", "table",
                         "blockquote", "image", "horizontalRule"})
TEXTBLOCKS = frozenset({"paragraph", "heading"})
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2})?$")


class DocError(ValueError):
    """內容不符合白名單，整份不收。"""


def new_id(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(6)


def column_ids(table: dict) -> list[str]:
    """Stable legacy fallback; persisted IDs keep identity through later moves."""
    attrs = table.get("attrs", {})
    width = max((len(row.get("content", [])) for row in table.get("content", [])), default=0)
    existing = attrs.get("column_ids", [])
    return [existing[i] if i < len(existing) else "c" + hashlib.sha256(f"{attrs.get('bid', '')}:{i}".encode()).hexdigest()[:20]
            for i in range(width)]


def safe_href(href) -> str | None:
    if not isinstance(href, str):
        return None
    value = href.strip()
    if not value or len(value) > 2000:
        return None
    lowered = value.lower()
    if lowered.startswith(("http://", "https://", "mailto:")):
        return value
    if value.startswith("#") and TAB_KEY_RE.match(value[1:]):
        return value
    if value.startswith("/projects/") and "//" not in value[1:]:
        return value
    return None


def asset_src_re(slug: str) -> re.Pattern:
    return re.compile(r"^/projects/api/" + re.escape(slug) + r"/assets/pa_[0-9a-f]{32}$")


def _int(value, low, high, default):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(number, low), high)


def _text(value, limit):
    return value[:limit] if isinstance(value, str) else None


class _Cleaner:
    def __init__(self, slug: str):
        self.image_src = asset_src_re(slug)
        self.seen: set[str] = set()
        self.repaired = False

    def _id(self, attr: str, value) -> str:
        if isinstance(value, str) and ID_RE.match(value) and value not in self.seen:
            self.seen.add(value)
            return value
        self.repaired = True
        fresh = new_id(ID_PREFIX[attr])
        while fresh in self.seen:
            fresh = new_id(ID_PREFIX[attr])
        self.seen.add(fresh)
        return fresh

    def fresh(self, attr: str) -> str:
        fresh = new_id(ID_PREFIX[attr])
        while fresh in self.seen:
            fresh = new_id(ID_PREFIX[attr])
        self.seen.add(fresh)
        return fresh

    def _attrs(self, kind: str, attrs: dict, depth: int = 0) -> dict | None:
        out: dict = {}
        if kind == "heading":
            out["level"] = _int(attrs.get("level"), 1, 3, 2)
        elif kind == "orderedList":
            out["start"] = _int(attrs.get("start"), 1, 10_000, 1)
        elif kind == "taskItem":
            out["checked"] = bool(attrs.get("checked"))
        elif kind in ("tableHeader", "tableCell"):
            out["colspan"] = _int(attrs.get("colspan"), 1, 50, 1)
            out["rowspan"] = _int(attrs.get("rowspan"), 1, 200, 1)
            widths = attrs.get("colwidth")
            if isinstance(widths, list) and all(isinstance(w, int) and 0 < w < 5000 for w in widths):
                out["colwidth"] = widths[:50]
            else:
                out["colwidth"] = None
        elif kind == "table":
            name = attrs.get("worksheet_name")
            if isinstance(name, str) and 0 < len(name) <= 100:
                out["worksheet_name"] = name
            sheet_name = attrs.get("sheet_name")
            if isinstance(sheet_name, str) and 0 < len(sheet_name) <= 100:
                out["sheet_name"] = sheet_name
            column_types = attrs.get("column_types")
            allowed = {"text", "number", "formula", "image", "video", "audio", "status"}
            if isinstance(column_types, list) and len(column_types) <= 100 and all(
                    isinstance(value, str) and value in allowed for value in column_types):
                out["column_types"] = column_types
            ids = attrs.get("column_ids")
            if isinstance(ids, list) and len(ids) <= 100 and all(isinstance(v, str) and ID_RE.fullmatch(v) for v in ids) and len(set(ids)) == len(ids):
                out["column_ids"] = ids
            options = attrs.get("column_options")
            if isinstance(options, dict):
                out["column_options"] = {key: {"options": value["options"]} for key, value in options.items()
                    if isinstance(key, str) and isinstance(value, dict) and isinstance(value.get("options"), list)
                    and len(value["options"]) <= 100 and all(isinstance(v, str) and 0 < len(v) <= 100 for v in value["options"])}
            for key in ("source_header_row", "source_start_column", "source_data_start_row", "mapping_revision"):
                if type(attrs.get(key)) is int and 0 <= attrs[key] <= 10000:
                    out[key] = attrs[key]
        elif kind == "image":
            src = attrs.get("src")
            if not isinstance(src, str) or not self.image_src.match(src):
                return None
            out["src"] = src
            out["alt"] = _text(attrs.get("alt"), 300)
            out["title"] = _text(attrs.get("title"), 300)
        elif kind == "status":
            label = attrs.get("label")
            if not isinstance(label, str) or not 0 < len(label) <= 100:
                self.repaired = True
                label = DEFAULT_STATUS
            out["label"] = label
        elif kind == "fill":
            out["label"] = _text(attrs.get("label"), 100) or ""
        id_attr = ID_ATTR.get(kind)
        if id_attr:
            out[id_attr] = self._id(id_attr, attrs.get(id_attr))
        if (depth == 1 and kind in BLOCK_TYPES) or kind == "tableRow":
            if "bid" not in out:
                out["bid"] = self._id("bid", attrs.get("bid"))
            owner = attrs.get("owner")
            out["owner"] = owner if isinstance(owner, str) and UUID_RE.match(owner) else None
            created = attrs.get("created")
            out["created"] = created if isinstance(created, str) and TIME_RE.match(created) else None
        return out

    def _marks(self, marks) -> list:
        out, kinds = [], set()
        for mark in marks if isinstance(marks, list) else []:
            if not isinstance(mark, dict) or mark.get("type") not in MARK_TYPES:
                continue
            kind = mark["type"]
            if kind in kinds:
                continue
            if kind == "link":
                href = safe_href((mark.get("attrs") or {}).get("href"))
                if href is None:
                    continue
                out.append({"type": "link", "attrs": {"href": href}})
            else:
                out.append({"type": kind})
            kinds.add(kind)
        return out

    def clean(self, node, depth: int = 0):
        if depth > MAX_DEPTH:
            raise DocError("內容巢狀太深")
        if not isinstance(node, dict) or node.get("type") not in NODE_TYPES:
            kind = node.get("type") if isinstance(node, dict) else type(node).__name__
            raise DocError(f"不支援的內容：{kind}")
        kind = node["type"]
        if kind == "text":
            text = node.get("text")
            if not isinstance(text, str) or not text:
                return None
            out = {"type": "text", "text": text}
            marks = self._marks(node.get("marks"))
            if marks:
                out["marks"] = marks
            return out
        attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        clean_attrs = self._attrs(kind, attrs, depth)
        if clean_attrs is None:  # 不是本專案的圖片
            self.repaired = True
            return None
        out: dict = {"type": kind}
        if clean_attrs:
            out["attrs"] = clean_attrs
        if kind not in LEAF_NODES:
            children = []
            for child in node.get("content") or []:
                cleaned = self.clean(child, depth + 1)
                if cleaned is not None:
                    children.append(cleaned)
            if children:
                out["content"] = children
            if kind == "table":
                width = max((len(row.get("content", [])) for row in children), default=0)
                ids = out.setdefault("attrs", {}).get("column_ids", [])
                if len(ids) != width:
                    out["attrs"]["column_ids"] = column_ids(out)
                    self.repaired = True
        return out


def validate_doc(doc, *, slug: str) -> tuple[dict, bool]:
    try:
        size = len(json.dumps(doc, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise DocError("內容不是合法的 JSON") from exc
    if size > MAX_DOC_BYTES:
        raise DocError("這一頁內容太大（超過 2 MB），請拆成兩頁")
    if not isinstance(doc, dict) or doc.get("type") != "doc":
        raise DocError("內容最外層必須是 doc")
    cleaner = _Cleaner(slug)
    clean = cleaner.clean(doc) or {"type": "doc"}
    content = clean.setdefault("content", [])
    # 最後一定是段落：表格或清單後面才放得了游標。編輯器打開時也會自己補，
    # 存的內容先補好，補的那一下就不會被當成修改、多出一個版本。
    if not content or content[-1].get("type") != "paragraph":
        content.append({"type": "paragraph",
                        "attrs": {"bid": cleaner.fresh("bid"), "owner": None, "created": None}})
    return clean, cleaner.repaired


# ---------- 索引：欄位在哪一列、叫什麼 ----------

def node_text(node) -> str:
    if not isinstance(node, dict):
        return ""
    if node.get("type") == "text":
        return node.get("text", "")
    if node.get("type") == "status":
        return (node.get("attrs") or {}).get("label", "")
    if node.get("type") == "hardBreak":
        return " "
    return "".join(node_text(child) for child in node.get("content") or [])


def _row_label(row) -> str:
    cells = row.get("content") or []
    first = node_text(cells[0]).strip() if cells else ""
    if re.fullmatch(r"\d+", first) and len(cells) > 1:
        return f"{first}. {node_text(cells[1]).strip()}"
    return first


def _header_texts(table) -> list[str]:
    rows = table.get("content") or []
    if not rows:
        return []
    first = rows[0].get("content") or []
    if first and all(cell.get("type") == "tableHeader" for cell in first):
        return [node_text(cell).strip() for cell in first]
    return []


def _walk_fields(node, ctx, out, anchors):
    kind = node.get("type")
    attrs = node.get("attrs") or {}
    if kind == "heading":
        bid = attrs.get("bid")
        if bid:
            anchors[bid] = node_text(node).strip()
            ctx["heading"] = bid
    if kind == "table":
        ctx = dict(ctx, headers=_header_texts(node))
    if kind == "tableRow":
        bid = attrs.get("bid")
        if bid:
            anchors[bid] = _row_label(node)
        ctx = dict(ctx, row=bid)
    if kind in ("tableHeader", "tableCell"):
        ctx = dict(ctx, column=ctx.get("cell_index", 0))
    anchor = ctx.get("row") or ctx.get("heading") or PAGE_ANCHOR
    headers = ctx.get("headers") or []
    column_label = headers[ctx["column"]] if "column" in ctx and ctx["column"] < len(headers) else ""
    if kind == "status":
        out[attrs.get("fid")] = {"kind": "status", "anchor_id": anchor, "label": column_label or "狀態",
                                 "default": attrs.get("label", DEFAULT_STATUS)}
    elif kind == "fill":
        out[attrs.get("fid")] = {"kind": "fill", "anchor_id": anchor,
                                 "label": column_label or attrs.get("label") or "這一格", "default": ""}
    elif kind == "taskItem":
        out[attrs.get("fid")] = {"kind": "check", "anchor_id": anchor,
                                 "label": node_text(node).strip()[:40] or "勾選項",
                                 "default": "true" if attrs.get("checked") else "false"}
    children = node.get("content") or []
    for index, child in enumerate(children):
        child_ctx = dict(ctx, cell_index=index) if kind == "tableRow" else ctx
        _walk_fields(child, child_ctx, out, anchors)
        if child.get("type") == "heading" and (child.get("attrs") or {}).get("bid"):
            ctx["heading"] = child["attrs"]["bid"]


def index_doc(doc) -> tuple[dict, dict]:
    """回傳 (fields, anchors)：fields[fid] = {kind, anchor_id, label, default}；anchors[bid] = 顯示用名稱。"""

    fields: dict = {}
    anchors: dict = {}
    _walk_fields(doc, {}, fields, anchors)
    fields.pop(None, None)
    return fields, anchors


# ---------- 文字（標註對位用；跟前端 src/anchoring.js 的 docTextJSON 一致） ----------

def doc_text(doc) -> str:
    """依文件順序接起每個文字區塊（段落、標題），區塊之間一個換行；hardBreak 是換行，小元件不算字。"""

    parts: list[str] = []
    first = [True]

    def inline(node):
        kind = node.get("type")
        if kind == "text":
            parts.append(node.get("text") or "")
        elif kind == "hardBreak":
            parts.append("\n")

    def walk(node):
        if not isinstance(node, dict):
            return
        if node.get("type") in TEXTBLOCKS:
            if not first[0]:
                parts.append("\n")
            first[0] = False
            for child in node.get("content") or []:
                if isinstance(child, dict):
                    inline(child)
            return
        for child in node.get("content") or []:
            walk(child)

    walk(doc)
    return "".join(parts)


def table_row_ids(doc) -> set[str]:
    out: set[str] = set()

    def walk(node):
        if not isinstance(node, dict):
            return
        if node.get("type") == "tableRow" and (node.get("attrs") or {}).get("bid"):
            out.add(node["attrs"]["bid"])
        for child in node.get("content") or []:
            walk(child)

    walk(doc)
    return out
