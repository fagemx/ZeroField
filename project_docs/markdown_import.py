"""把分頁的 Markdown 文字稿轉成 TipTap 文件（只在第一次匯入時用）。

支援：# ／## ／### 標題、段落、**粗體**、[文字](網址或 #分頁)、- 與 1. 清單（四個空白縮排的子項目）、
表格、{{s:狀態}}、{{img:代號|說明}}。表頭含 fill_headers 任一個字的那一欄，格子變成「大家可填」，
原本有字就當初始值。每一行一定會往前走：不認得的行（例如 `#標籤`）當一般文字。
"""
from __future__ import annotations

import re
from typing import Callable

from project_docs.doc_schema import DEFAULT_STATUS, STATUSES, new_id, safe_href

ORDERED = re.compile(r"^(\d+)\. (.*)$")
SUB = re.compile(r"^ {4}- (.*)$")
HEADING = re.compile(r"^(#{1,3}) (.*)$")
SEPARATOR = re.compile(r"^:?-{3,}:?$")
INLINE = re.compile(r"\{\{s:([^}]+)\}\}|\[([^\]]+)\]\(([^)\s]+)\)|\*\*(.+?)\*\*")


def _text(value: str, marks=None) -> dict | None:
    if not value:
        return None
    node = {"type": "text", "text": value}
    if marks:
        node["marks"] = marks
    return node


def inline(value: str, *, tab_keys: set[str]) -> list[dict]:
    out: list[dict] = []
    position = 0
    for match in INLINE.finditer(value):
        if match.start() > position:
            out.append(_text(value[position:match.start()]))
        status, label, href, bold = match.groups()
        if status is not None:
            label_value = status if status in STATUSES else DEFAULT_STATUS
            out.append({"type": "status", "attrs": {"fid": new_id("f"), "label": label_value}})
        elif label is not None:
            target = href if not href.startswith("#") or href[1:] in tab_keys else None
            safe = safe_href(target) if target else None
            out.append(_text(label, [{"type": "link", "attrs": {"href": safe}}] if safe else None))
        else:
            out.append(_text(bold, [{"type": "bold"}]))
        position = match.end()
    if position < len(value):
        out.append(_text(value[position:]))
    return [node for node in out if node]


def _paragraph(value: str, *, tab_keys) -> dict:
    content = inline(value, tab_keys=tab_keys)
    return {"type": "paragraph", "content": content} if content else {"type": "paragraph"}


def _cells(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_block_start(line: str) -> bool:
    return bool(
        HEADING.match(line) or line.startswith("|") or line.startswith("- ")
        or line.startswith("{{img:") or ORDERED.match(line)
    )


def markdown_to_doc(md: str, *, tab_keys: set[str], image_src: Callable[[str], str | None],
                    fill_headers=("請填", "內容或位置", "確認日期")) -> tuple[dict, dict]:
    """回傳 (doc, values)；values[fid] = ("fill", 初始文字)。"""

    lines = md.splitlines()
    blocks: list[dict] = []
    values: dict[str, tuple[str, str]] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        heading = HEADING.match(line)
        if heading:
            blocks.append({
                "type": "heading",
                "attrs": {"level": len(heading.group(1)), "bid": new_id("b")},
                "content": inline(heading.group(2).strip(), tab_keys=tab_keys),
            })
            i += 1
            continue
        if line.startswith("{{img:") and line.rstrip().endswith("}}"):
            key, _, caption = line.strip()[6:-2].partition("|")
            src = image_src(key.strip())
            if src:
                blocks.append({"type": "image", "attrs": {"src": src, "alt": caption, "title": caption}})
            i += 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            blocks.append(_table(rows, tab_keys=tab_keys, fill_headers=fill_headers, values=values))
            continue
        if ORDERED.match(line) or line.startswith("- "):
            ordered = bool(ORDERED.match(line))
            items: list[tuple[str, list[str]]] = []
            while i < len(lines):
                current = lines[i]
                number = ORDERED.match(current) if ordered else None
                if number:
                    items.append((number.group(2), []))
                elif not ordered and current.startswith("- "):
                    items.append((current[2:], []))
                elif SUB.match(current) and items:
                    items[-1][1].append(SUB.match(current).group(1))
                else:
                    break
                i += 1
            blocks.append(_list(items, ordered=ordered, tab_keys=tab_keys))
            continue
        paragraph = [line.strip()]
        i += 1
        while i < len(lines) and lines[i].strip() and not _is_block_start(lines[i]):
            paragraph.append(lines[i].strip())
            i += 1
        blocks.append(_paragraph("".join(paragraph), tab_keys=tab_keys))
    blocks = blocks or [{"type": "paragraph"}]
    # 第一層區塊都要有 bid（標註、一塊一塊存靠它）；匯入時就給，存檔時才不會被當成「修過」
    for block in blocks:
        block.setdefault("attrs", {}).setdefault("bid", new_id("b"))
    return {"type": "doc", "content": blocks}, values


def _list(items, *, ordered: bool, tab_keys) -> dict:
    content = []
    for text, subs in items:
        item = {"type": "listItem", "content": [_paragraph(text, tab_keys=tab_keys)]}
        if subs:
            item["content"].append({
                "type": "bulletList",
                "content": [{"type": "listItem", "content": [_paragraph(s, tab_keys=tab_keys)]} for s in subs],
            })
        content.append(item)
    return {"type": "orderedList" if ordered else "bulletList", "content": content}


def _table(rows, *, tab_keys, fill_headers, values) -> dict:
    head = rows[0]
    body = [r for r in rows[1:] if not all(SEPARATOR.match(cell) for cell in r)]
    fill_columns = {index for index, title in enumerate(head) if any(word in title for word in fill_headers)}
    table_rows = [{
        "type": "tableRow",
        "attrs": {"bid": new_id("b")},
        "content": [
            {"type": "tableHeader", "attrs": {"colspan": 1, "rowspan": 1, "colwidth": None},
             "content": [_paragraph(title, tab_keys=tab_keys)]}
            for title in head
        ],
    }]
    for cells in body:
        if len(cells) != len(head):
            raise ValueError(f"The row has {len(cells)} cells, but its header has {len(head)}: {cells}")
        row_cells = []
        for index, value in enumerate(cells):
            if index in fill_columns:
                fid = new_id("f")
                if value:
                    values[fid] = ("fill", value)
                paragraph = {"type": "paragraph", "content": [
                    {"type": "fill", "attrs": {"fid": fid, "label": head[index]}}]}
            else:
                paragraph = _paragraph(value, tab_keys=tab_keys)
            row_cells.append({"type": "tableCell", "attrs": {"colspan": 1, "rowspan": 1, "colwidth": None},
                              "content": [paragraph]})
        table_rows.append({"type": "tableRow", "attrs": {"bid": new_id("b")}, "content": row_cells})
    return {"type": "table", "content": table_rows}
