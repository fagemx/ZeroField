"""專案助理的工具：讀頁、搜尋、待辦、報表結構、提案。

每次呼叫自己開一條連線；只有 propose 會寫（寫提案表，不動專案頁）。
ToolError 的訊息會原文回給模型，讓它改參數再試，所以要寫得讓它看得懂下一步。
"""
from __future__ import annotations

import copy
import json
import re
import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from project_assistant import privacy, report_index, store, table_edits, todo, request_scope, proposal_review
from project_assistant.masking import absolute
from project_assistant.tool_specs import LABELS, PROPOSE_ACTIONS, TOOL_NAMES
from project_docs import anchoring
from project_docs import repository as repo
from project_docs.doc_schema import DEFAULT_STATUS, STATUSES, doc_text, index_doc, node_text

MAX_OUT = 7000
MAX_CONTENT = 2000


class ToolError(Exception):
    """給模型看的錯誤。"""


@dataclass
class ToolContext:
    connection_factory: Callable[[], object]
    slug: str
    me: object
    report_dir: Path
    message_id: int | None
    agent_key: str = 'coordinator'
    lease_owner: str | None = None
    dispatch_id: str | None = None
    admission_no: int | None = None
    lease_token: str | None = None
    scope: dict | None = None
    write_mode: str = 'proposal'
    worker_id: str | None = None
    run_id: str | None = None
    deadline_at: str | None = None
    episode_id: str | None = None
    execution_guard: Callable | None = None
    runtime_cost_hook: Callable | None = None
    pending_images: list = field(default_factory=list)
    post_commit_actions: list = field(default_factory=list)


def _clip(text: str) -> str:
    return text if len(text) <= MAX_OUT else text[:MAX_OUT] + "\n…（內容太長，已截斷；請縮小範圍再查）"


# ---------- 專案頁轉成文字 ----------

def render_doc(doc: dict, values: dict) -> str:
    lines: list[str] = []

    def inline(node) -> str:
        kind = node.get("type")
        attrs = node.get("attrs") or {}
        if kind == "text":
            return node.get("text") or ""
        if kind == "hardBreak":
            return " / "
        if kind == "status":
            return f"〔{values.get(attrs.get('fid')) or attrs.get('label') or DEFAULT_STATUS}〕"
        if kind == "fill":
            return values.get(attrs.get("fid")) or "（空白，可填）"
        if kind == "image":
            return f"（圖：{attrs.get('alt') or attrs.get('title') or '圖'}）"
        return "".join(inline(child) for child in node.get("content") or [])

    def block(node, indent: str = "") -> None:
        kind = node.get("type")
        attrs = node.get("attrs") or {}
        if kind == "heading":
            lines.append("#" * int(attrs.get("level") or 2) + " " + inline(node).strip())
        elif kind == "paragraph":
            text = inline(node).strip()
            if text:
                lines.append(indent + text)
        elif kind in ("bulletList", "orderedList", "taskList"):
            for number, item in enumerate(node.get("content") or [], start=1):
                if kind == "orderedList":
                    mark = f"{number}."
                elif kind == "taskList":
                    checked = values.get((item.get("attrs") or {}).get("fid"))
                    done = checked == "true" if checked is not None else (item.get("attrs") or {}).get("checked")
                    mark = "- [x]" if done else "- [ ]"
                else:
                    mark = "-"
                first = True
                for child in item.get("content") or []:
                    if child.get("type") == "paragraph" and first:
                        lines.append(f"{indent}{mark} {inline(child).strip()}")
                        first = False
                    else:
                        block(child, indent + "  ")
        elif kind == "table":
            for index, row in enumerate(node.get("content") or []):
                cells = [inline(cell).strip().replace("|", "／") for cell in row.get("content") or []]
                lines.append(indent + "| " + " | ".join(cells) + " |")
                if index == 0:
                    lines.append(indent + "|" + " --- |" * len(cells))
        elif kind == "blockquote":
            for child in node.get("content") or []:
                block(child, indent + "> ")
        elif kind == "image":
            lines.append(indent + inline(node))
        elif kind == "horizontalRule":
            lines.append(indent + "---")

    for child in doc.get("content") or []:
        block(child)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _tabs(conn, slug):
    return repo.list_tabs(conn, slug)


def _find_tab(conn, slug, page):
    page = str(page or "").strip()
    tabs = _tabs(conn, slug)
    hit = next((t for t in tabs if t["key"] == page), None) or next((t for t in tabs if t["title"] == page), None) \
        or next((t for t in tabs if page and page in t["title"]), None)
    if not hit:
        raise ToolError(f"找不到分頁「{page}」。分頁有：" + "、".join(f"{t['key']}（{t['title']}）" for t in tabs))
    return repo.get_tab(conn, slug, hit["key"])


def _rendered(conn, slug, tab) -> str:
    values = tab.get('_plain_values') if '_plain_values' in tab else todo.plain_values(conn, slug).get(tab["key"], {})
    return render_doc(tab["doc"], values)


def _context_tab(ctx,conn,page):
    if not getattr(ctx,'dispatch_id',None):
        return _find_tab(conn,ctx.slug,page)
    from project_assistant import orchestrator as cp,orchestration_store as db
    dispatch=db.get_dispatch(conn,ctx.slug,ctx.dispatch_id)
    task=db.get_task(conn,ctx.slug,dispatch['task_id'])
    cached=task['input_snapshot']['tabs']
    key=next((key for key,tab in cached.items() if page in (key,tab['title'])),None)
    if key is None:
        key=_find_tab(conn,ctx.slug,page)['key']
    tab=cp.snapshot_tab(conn,ctx.slug,ctx.dispatch_id,key)
    tab['_field_values']=tab['values']
    tab['_plain_values']={fid:value.get('value','') if isinstance(value,dict) else value for fid,value in tab['values'].items()}
    return tab


def list_pages(ctx, conn, args):
    out = []
    for t in _tabs(conn, ctx.slug):
        tab = _context_tab(ctx,conn,t['key'])
        body = [ln for ln in _rendered(conn, ctx.slug, tab).splitlines() if ln.strip() and not ln.startswith("#")]
        prefix = "  " if t.get("parent_key") else ""
        out.append(f"{prefix}- {t['key']}：{t['title']}——{(body[0] if body else '')[:80]}")
    return "\n".join(out)


def read_page(ctx, conn, args):
    tab = _context_tab(ctx,conn,args.get('key'))
    if tab.get("surface_type") == "sheet" or "offset" in args:
        try:
            offset, limit = max(0, int(args.get("offset", 0))), max(1, min(30, int(args.get("limit", 15))))
        except (ValueError, TypeError):
            raise ToolError("offset/limit must be integers.") from None
        values = tab.get('_plain_values') if '_plain_values' in tab else todo.plain_values(conn, ctx.slug).get(tab["key"], {})
        items = []
        for table in tab["doc"].get("content", []):
            if table.get("type") == "table":
                for row in table.get("content", []):
                    rendered = render_doc({"content": [{"type": "table", "content": [row]}]}, values).splitlines()[0]
                    items.append(f"table_id={table['attrs']['bid']} row_id={row['attrs']['bid']} {rendered[:2200]}")
        lines, size = [], 0
        for item in items[offset:offset + limit]:
            if lines and size + len(item) > 5800:
                break
            lines.append(item)
            size += len(item)
        end = offset + len(lines)
        return f"# {tab['title']} ({tab['key']})\n欄號從 0 開始。共 {len(items)} 列（含表頭）。\n" + "\n".join(lines) + (f"\n尚有更多列：請 read_page key={tab['key']} offset={end}" if end < len(items) else "\n已讀完")
    text = _rendered(conn, ctx.slug, tab)
    section = str(args.get("section") or "").strip()
    if section:
        parts = re.split(r"(?m)^(?=#{2,3} )", text)
        hit = [p for p in parts if p.strip() and section in p.splitlines()[0]]
        text = "\n".join(hit) if hit else f"（「{tab['title']}」沒有標題含「{section}」的段落，以下是全文）\n" + text
    tables = []
    for table in tab["doc"].get("content", []):
        if table.get("type") == "table":
            rows = [f"{r.get('attrs', {}).get('bid')}: " + " | ".join(node_text(c) for c in r.get("content", [])) for r in table.get("content", [])]
            tables.append(f"table_id={table.get('attrs', {}).get('bid')}\n" + "\n".join(rows))
    return f"# 分頁：{tab['title']}（{tab['key']}）\n" + text + ("\n可編輯列 ID：\n" + "\n".join(tables) if tables else "")


def search_pages(ctx, conn, args):
    query = str(args.get("query") or "").strip()
    if not query:
        raise ToolError("query cannot be empty.")
    hits = []
    for t in _tabs(conn, ctx.slug):
        tab = _context_tab(ctx,conn,t['key'])
        heading = t["title"]
        for line in _rendered(conn, ctx.slug, tab).splitlines():
            if line.startswith("#"):
                heading = line.lstrip("# ").strip()
            if query.casefold() in line.casefold():
                hits.append(f"- {t['title']}〈{heading}〉：{line.strip()[:180]}")
    out = "\n".join(hits[:15]) or f"專案頁沒有出現「{query}」。"
    if len(hits) > 15:
        out += f"\n…還有 {len(hits) - 15} 處"
    return out


def my_todo(ctx, conn, args):
    items = todo.todo_items(conn, ctx.slug, ctx.me)
    out = []
    notes = [i for i in items if i["kind"] == "note"]
    if notes:
        out.append("負責人交代的：")
        out += [f"- {i['text']}" for i in notes]
    questions = [i for i in items if i["kind"] == "question"]
    if questions:
        out.append("\n待確認問題（請行銷回答）：")
        out += [f"- 第 {i['number']} 題〔{i['status']}〕{i['text']}" for i in questions]
    handoff = [i for i in items if i["kind"] == "handoff"]
    if handoff:
        out.append("\n交接追蹤上行銷要交的：")
        out += [f"- {i['text']}〔{i['status']}〕：{i['what']}" for i in handoff]
    mentions = [i for i in items if i["kind"] == "mention"]
    if mentions:
        out.append("\n@ 你、還沒解決的討論：")
        out += [f"- {i['text']}" for i in mentions]
    return "\n".join(out).strip() or "目前沒有待辦。"


# ---------- 報表（只有結構，沒有數字） ----------

def _book(ctx, code):
    path = Path(ctx.report_dir) / f"{code}.json"
    with report_index.LOCK:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _catalog(ctx):
    path = Path(ctx.report_dir) / "catalog.json"
    with report_index.LOCK:
        if not path.exists():
            raise ToolError("No workbook index exists. Add workbooks to the configured folder or ask the owner to check its settings.")
        return json.loads(path.read_text(encoding="utf-8"))


def _sheet(book, sheet):
    return next((s for s in book["sheets"] if s["name"] == sheet), None) or \
        next((s for s in book["sheets"] if sheet and sheet in s["name"]), None)


def _in(row_ranges, row):
    return any(a <= row <= b for a, b in row_ranges)


def report_list(ctx, conn, args):
    return "\n".join(f"- {b['code']}：{b['purpose'] or b['file']}（{len(b['sheets'])} 張：{'、'.join(b['sheets'])}）"
                     for b in _catalog(ctx))


def report_overview(ctx, conn, args):
    code = str(args.get("code") or "")
    book = _book(ctx, code)
    if not book:
        raise ToolError(f"Workbook {code} not found.")
    return overview_text(book, code)


def overview_text(book: dict, code: str) -> str:
    """一本報表（或使用者附的 Excel）的總覽：工作表、日期範圍、欄名。只有結構。"""

    out = [f"# {book['file']}（{code}）"]
    if book.get("purpose"):
        out.append(f"用途：{book['purpose']}")
    if book.get("package"):
        out.append("檔案：" + "；".join(f"{k} {v}" for k, v in book["package"].items()))
    for sh in book["sheets"]:
        labels = [f"{L}:{c['label']}" for L, c in sh["columns"].items() if c.get("label")][:40]
        out.append(f"\n## {sh['name']}{'（隱藏）' if sh['hidden'] else ''}　{sh['rows']} 列 × {sh['cols']} 欄")
        if sh["date_range"]:
            out.append(f"日期欄 {sh['date_col']}：{sh['date_range'][0]} ～ {sh['date_range'][1]}；有手動填數字的最後一天 {sh['last_filled_date']}")
        if sh["titles"]:
            out.append("表頭上方的文字：" + "｜".join(sh["titles"][:6]))
        if labels:
            out.append("欄位：" + "｜".join(labels))
    for pq in book["power_query"]:
        out.append(f"\nPower Query（{pq['part']}）：\n{pq['code'][:1500]}")
    return "\n".join(out)


def report_sheet(ctx, conn, args):
    from openpyxl.utils import column_index_from_string as idx

    code, sheet, columns = (str(args.get(k) or "") for k in ("code", "sheet", "columns"))
    book = _book(ctx, code)
    if not book:
        raise ToolError(f"Workbook {code} not found.")
    sh = _sheet(book, sheet)
    if not sh:
        raise ToolError(f"Workbook {code} has no worksheet {sheet}. Available: {', '.join(s['name'] for s in book['sheets'])}")
    wanted = None
    if columns:
        wanted = set()
        try:
            for part in columns.replace(" ", "").split(","):
                if ":" in part:
                    a, b = part.split(":", 1)
                    wanted.update(range(idx(a.upper()), idx(b.upper()) + 1))
                elif part:
                    wanted.add(idx(part.upper()))
        except ValueError:
            raise ToolError("Write columns as a range such as A:K or a list such as B,F,AA.") from None
    return sheet_text(book, sh, wanted)


def sheet_text(book: dict, sh: dict, wanted=None) -> str:
    """一張工作表每一欄是手填還是公式、公式怎麼寫。wanted 是要看的欄（欄號集合），None＝全部。"""

    from openpyxl.utils import column_index_from_string as idx

    dates = sh["dates_by_row"]
    out = [f"# {book['file']}〈{sh['name']}〉{'（隱藏）' if sh['hidden'] else ''}",
           f"表頭在第 {sh['header_row']} 列；日期欄 {sh['date_col']}；日期 {sh['date_range'][0] + ' ～ ' + sh['date_range'][1] if sh['date_range'] else '無'}；有手動填數字的最後一天 {sh['last_filled_date']}"]
    if sh["refs_out"]:
        out.append("公式引用了其他工作表：" + "、".join(f"{k}（{v} 格）" for k, v in sh["refs_out"].items()))
    for L, c in sh["columns"].items():
        if wanted is not None and idx(L) not in wanted:
            continue
        parts = [f"\n{L} 欄「{c.get('label') or '（沒有欄名）'}」"]
        if c.get("manual"):
            m = c["manual"]
            parts.append(f"  手動輸入的數字 {m['n']} 格（數值不提供），日期 {m['first_date']} ～ {m['last_date']}")
        for f in c.get("formulas", [])[:3]:
            r0 = f["rows"][0][0]
            when = f"，例如第 {r0} 列（{dates.get(str(r0), '無日期')}）" if r0 else ""
            parts.append(f"  公式 {f['n']} 格：{f['pattern']}{when}")
        if len(c.get("formulas", [])) > 3:
            parts.append(f"  另外還有 {len(c['formulas']) - 3} 種公式寫法")
        if c.get("formula_hand_typed_numbers"):
            parts.append(f"  公式裡有 {c['formula_hand_typed_numbers']} 個手打的數字（已遮成 ▢）")
        if c.get("texts"):
            t = c["texts"]
            parts.append(f"  文字 {t['distinct']} 種：" + "、".join(x for x, _ in t["top"][:8]))
        if c.get("error_cells"):
            parts.append(f"  錯誤值 {c['error_cells']} 格（例如 #DIV/0!）")
        out.append("\n".join(parts))
    return "\n".join(out)


def report_cell(ctx, conn, args):
    code, sheet, cell = (str(args.get(k) or "") for k in ("code", "sheet", "cell"))
    book = _book(ctx, code)
    sh = _sheet(book, sheet) if book else None
    if not sh:
        raise ToolError("Workbook or worksheet not found.")
    m = re.fullmatch(r"\$?([A-Za-z]{1,3})\$?(\d+)", cell.strip())
    if not m:
        raise ToolError("Use a cell reference such as F12.")
    L, row = m.group(1).upper(), int(m.group(2))
    col = sh["columns"].get(L, {})
    date = sh["dates_by_row"].get(str(row), "這一列沒有日期")
    head = f"{book['file']}〈{sh['name']}〉{L}{row}：欄名「{col.get('label') or '（沒有欄名）'}」，這一列的日期 {date}"
    for f in col.get("formulas", []):
        if _in(f["rows"], row):
            return f"{head}\n公式：{absolute(f['pattern'], row)}\n（同一欄有 {f['n']} 格是這種寫法）"
    if col.get("manual") and _in(col["manual"]["rows"], row):
        return f"{head}\n這格是手動輸入的數字，數值不提供。"
    ref = f"{L}{row}"
    text = next((t for r, t in sh["texts_all"] if r == ref), None)
    if text is not None:
        return f"{head}\n文字：{text}"
    return f"{head}\n這格是空的，或是日期。"


def report_find(ctx, conn, args):
    text, code = str(args.get("text") or ""), str(args.get("code") or "")
    if not text:
        raise ToolError("text cannot be empty.")
    hits = []
    for b in _catalog(ctx):
        if code and b["code"] != code:
            continue
        book = _book(ctx, b["code"])
        if not book:
            continue
        for sh in book["sheets"]:
            where = f"{book['code']}〈{sh['name']}〉"
            if text in sh["name"]:
                hits.append(f"- {where}：工作表名稱")
            for L, c in sh["columns"].items():
                if text in (c.get("label") or ""):
                    hits.append(f"- {where} {L} 欄：欄名「{c['label']}」")
                for f in c.get("formulas", []):
                    if text in f["pattern"]:
                        r0 = f["rows"][0][0]
                        hits.append(f"- {where} {L} 欄（{f['n']} 格，例如 {L}{r0}）：公式 {f['pattern']}")
            for ref, t in sh["texts_all"]:
                if text in t:
                    hits.append(f"- {where} {ref}：文字「{t}」")
    out = "\n".join(dict.fromkeys(hits[:25])) or f"報表裡沒有找到「{text}」。"
    if len(hits) > 25:
        out += f"\n…還有 {len(hits) - 25} 處，請加上報表代號縮小範圍"
    return out


# ---------- 提出修改 ----------

def _rows_of(tab):
    """[(bid, 顯示名稱, 第一格文字, 段落標題)]"""

    _, anchors = index_doc(tab["doc"])
    out = []
    for heading, _, rows in todo.table_rows(tab["doc"]):
        for bid, cells in rows:
            if bid:
                out.append((bid, anchors.get(bid, ""), cells[0] if cells else "", heading))
    return out


def _find_row(tab, row):
    row = str(row or "").strip()
    if not row:
        raise ToolError("Provide row as a question number or the first cell’s exact value.")
    rows = _rows_of(tab)
    numbered = re.fullmatch(r"(.*?)\s*第?\s*(\d+)\s*題?", row)
    if numbered:
        section, number = numbered.group(1).strip(), numbered.group(2)
        hits = [r for r in rows if r[2] == number and (not section or section in r[3])]
        if hits:
            return hits[0]  # 預設文件順序第一張表（ad-data 是「請行銷回答」）
    hits = [r for r in rows if r[2] == row] or [r for r in rows if row in r[1]]
    if len(hits) == 1:
        return hits[0]
    names = "、".join(r[1][:20] for r in rows[:30])
    raise ToolError(("找到不只一列" if hits else "找不到這一列") + f"「{row}」。這一頁的列有：{names}")


def _row_field(tab, rid, kind, column=""):
    fields, _ = index_doc(tab["doc"])
    hits = [(fid, f) for fid, f in fields.items() if f["kind"] == kind and f["anchor_id"] == rid]
    if column:
        hits = [h for h in hits if column in h[1]["label"]] or hits
    if not hits:
        raise ToolError("這一列沒有" + ("狀態" if kind == "status" else "可以填的格子"))
    if len(hits) > 1 and not column:
        raise ToolError("這一列有好幾個可填的格子：" + "、".join(h[1]["label"] for h in hits) + "；請加 column")
    return hits[0]


def _quote_anchor(tab, quote):
    quote = str(quote or "").strip()
    if len(quote) < 4:
        raise ToolError("quote must exactly match at least four characters on the page.")
    text = doc_text(tab["doc"])
    start = text.find(quote)
    if start < 0:
        raise ToolError("The quote was not found. Use read_page to copy its exact text.")
    if text.find(quote, start + 1) >= 0:
        raise ToolError("This quote occurs more than once. Select a longer, unique passage.")
    return anchoring.anchor_at(text, start, quote), quote


def _display(action, target):
    if action == "私下轉給負責人":
        return "負責人（私下）"
    where = target["tab_title"]
    label = target.get("row_label") or ""
    numbered = re.match(r"^(\d+)\. ", label)
    if numbered:
        where += f" 第 {numbered.group(1)} 題"
    elif label:
        where += f"〈{label[:24]}〉"
    elif target.get("quote"):
        where += f"「{target['quote'][:24]}」"
    if target.get("field_label"):
        where += " " + target["field_label"]
    return where


def propose(ctx, conn, args):
    scope=_request_scope(ctx,conn)
    if scope and args.get('action') not in ('在段落加標註','寫進那一題的討論','留言問負責人'):
        raise ToolError("This task has a fixed scope. Use structured edits or annotate / discuss the selected data.")
    action = args.get("action")
    if action not in PROPOSE_ACTIONS:
        raise ToolError("action 只能是：" + "、".join(PROPOSE_ACTIONS))
    content = str(args.get("content") or "").strip()
    if len(content) > MAX_CONTENT:
        raise ToolError(f"content supports up to {MAX_CONTENT} characters.")
    target: dict = {}
    tab = None
    if action != "私下轉給負責人":
        tab = _context_tab(ctx,conn,args.get('page'))
        target.update({"tab_key": tab["key"], "tab_title": tab["title"]})
    if action in ("寫進那一題的討論", "改狀態", "填交接追蹤") or (action == "留言問負責人" and args.get("row")):
        bid, label, _, _ = _find_row(tab, args.get("row"))
        target.update({"rid": bid, "row_label": label})
    if action == "改狀態":
        status = args.get("status")
        if status not in STATUSES:
            raise ToolError("status 只能是：" + "、".join(STATUSES))
        fid, _ = _row_field(tab, target["rid"], "status")
        target["fid"] = fid
        content = status
    elif action == "填交接追蹤":
        if not content:
            raise ToolError("content must contain the value to enter in the field.")
        fid, field = _row_field(tab, target["rid"], "fill", str(args.get("column") or ""))
        target.update({"fid": fid, "field_label": field["label"]})
    elif action in ("寫進那一題的討論", "留言問負責人"):
        if not content:
            raise ToolError("content must contain the proposed text in the user’s voice.")
        if "rid" not in target:
            target["anchor"], target["quote"] = _quote_anchor(tab, args.get("quote"))
        target["mention_admin"] = True
    elif action == "在段落加標註":
        label = args.get("label")
        if label not in LABELS:
            raise ToolError("label 只能是：" + "、".join(LABELS))
        target["anchor"], target["quote"] = _quote_anchor(tab, args.get("quote"))
        target["label"] = LABELS[label]
    elif not content:
        raise ToolError("content must contain the question for the owner.")
    target["display"] = _display(action, target)
    if scope:
        if tab['key']!=scope['target_tab']:
            raise ToolError("POLICY_DENIED: The annotation exceeds the selected page.")
        if scope.get('kind')=='doc':
            selected=[block for block in tab['doc'].get('content',[]) if block.get('attrs',{}).get('bid') in scope['block_ids']]
            if target.get('rid') or not target.get('quote') or target['quote'] not in doc_text({'type':'doc','content':selected}):
                raise ToolError("POLICY_DENIED: The annotation exceeds the selected passages.")
        elif target.get('rid') not in scope['row_ids']:
            raise ToolError("POLICY_DENIED: Discuss a selected row.")
        target['request_scope']=scope
    proposal_id = store.create_proposal(conn, ctx.slug, ctx.me.actor_id, ctx.message_id, action, target, content)
    if getattr(ctx,'dispatch_id',None):
        from project_assistant.orchestrator import attach_proposal
        attach_proposal(conn,ctx,proposal_id)
    return (f"已建立提案 #{proposal_id}：{action} → {target['display']}。"
            "畫面上會出現確認卡，等使用者按確認才會生效。")


def offer_document(ctx, conn, args):
    from project_assistant import docx_export

    project = repo.get_project(conn, ctx.slug) or {"title": ctx.slug}
    tabs = _tabs(conn, ctx.slug)
    name = docx_export.filename(project["title"], dt.datetime.now(docx_export.TAIPEI))
    return (f"已在這則回答下方放「下載 Word 檔」按鈕：{name}，共 {len(tabs)} 個分頁"
            f"（{'、'.join(t['title'] for t in tabs)}）。檔案內容是對方按下載當下的專案頁最新版，狀態和可填格都帶目前的值。"
            "回答時請說「請按下面的按鈕下載」，不要自己貼網址，也不用把內容再貼一次。")


def _request_scope(ctx, conn):
    if getattr(ctx,'dispatch_id',None):
        from project_assistant import orchestrator as cp,orchestration_store as db
        return cp.effective_scope(conn,db.get_dispatch(conn,ctx.slug,ctx.dispatch_id))
    if getattr(ctx,'scope',None):
        return ctx.scope
    if not getattr(ctx, "message_id", None): return None
    reply = store.message(conn, ctx.message_id)
    question = store.message(conn, reply["reply_to"]) if reply and reply.get("reply_to") else reply
    return question.get("request_scope") if question else None


def propose_table_edit(ctx, conn, args):
    tab = _context_tab(ctx,conn,args.get('tab_key'))
    values = tab.get('_field_values') if '_field_values' in tab else repo.field_values(conn, ctx.slug).get(tab["key"], {})
    try:
        edits = privacy.sanitize(args.get("row_edits", []), privacy.mode(conn, ctx.slug))
        rows = privacy.sanitize(args.get("new_rows", []), privacy.mode(conn, ctx.slug))
        scope = _request_scope(ctx, conn)
        request_scope.guard_edits(scope, tab, values, edits, rows, args.get("table_id"))
        ops, fields, preview = table_edits.prepare(tab["doc"], edits, rows, values, args.get("table_id"))
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    target = {"tab_key": tab["key"], "tab_title": tab["title"], "display": tab["title"], "ops": ops, "field_edits": fields,
              "source_revision": tab["revision"], **({"expected_revision": tab["revision"]} if rows else {})}
    target["review"] = proposal_review.describe(target, tab, partial_allowed=not bool(getattr(ctx,'dispatch_id',None)))
    if scope: target["request_scope"] = scope
    proposal_id = store.create_proposal(conn, ctx.slug, ctx.me.actor_id, ctx.message_id, "table_edit", target, preview)
    if getattr(ctx,'dispatch_id',None):
        from project_assistant.orchestrator import attach_proposal
        attach_proposal(conn,ctx,proposal_id)
    return f"已建立表格修改提案 #{proposal_id}（{len(ops)} 列）。等使用者確認才會寫入。\n{preview}"


HANDLERS = {
    "list_pages": list_pages, "read_page": read_page, "search_pages": search_pages, "my_todo": my_todo,
    "report_list": report_list, "report_overview": report_overview, "report_sheet": report_sheet,
    "report_cell": report_cell, "report_find": report_find, "propose": propose,
    "offer_document": offer_document, "propose_table_edit": propose_table_edit,
}
from project_assistant import delegation_tools
HANDLERS.update(delegation_tools.HANDLERS)
from project_assistant import studio_tools
HANDLERS.update(studio_tools.HANDLERS)
from project_assistant import context_tools
HANDLERS.update(context_tools.HANDLERS)
from project_assistant import previs_ops  # SPEC_20 R27: propose_previs_ops (text result, like propose_table_edit)
HANDLERS.update(previs_ops.HANDLERS)
# Results that are structured JSON, already sanitized and bounded by their handlers: never re-masked as text
# (that would break the JSON) nor clipped.
_STRUCTURED = frozenset(studio_tools.HANDLERS) | frozenset(context_tools.HANDLERS)


class ToolResult(str):
    def __new__(cls, text, images=()):
        obj = super().__new__(cls, text)
        obj.images = list(images)
        return obj


def call(ctx: ToolContext, name: str, args) -> str:
    if name not in TOOL_NAMES:
        raise ToolError(f"Tool {name} does not exist.")
    args = args if isinstance(args, dict) else {}
    from project_assistant import agent_policy, orchestrator as cp, orchestration_store as db
    from project_assistant.tool_specs import MUTATING_TOOLS, DELEGATION_TOOLS, validate_studio_args
    try:
        validate_studio_args(name, args)
    except ValueError as exc:
        raise ToolError(str(exc)) from None
    ctx.pending_images = []
    ctx.post_commit_actions = []
    conn = ctx.connection_factory()
    actions = []
    try:
        agent_policy.authorize_tool(ctx, conn, name, args)
        if name == 'studio_plan_allocation':
            conn.rollback()
            from project_assistant import limb_worker
            ctx.local_comfy_online = bool(limb_worker.probe_local_comfy_status()['online'])
        cp.lock_project(conn, ctx.slug)
        agent_policy.authorize_tool(ctx, conn, name, args)
        if name in {'propose','propose_table_edit','offer_document'} and getattr(ctx, 'graded_source_stamp', None) is not None:
            if studio_tools.source_stamp(ctx, conn) != ctx.graded_source_stamp:
                raise ToolError('Proposal source changed during grading; request another reviewed candidate.')
        if name in {'propose','propose_table_edit','offer_document'} and not getattr(ctx, 'grading_enabled', False) and getattr(ctx, 'worker_id', None) and isinstance(ctx.worker_id, dict):
            current = agent_policy.agent_registry.get_agent(conn, ctx.slug, ctx.agent_key)
            if current.get('outcome_grader', {}).get('enabled'):
                raise ToolError('Return the candidate in your completion report; graded remote proposals are published only after the independent scorecard.')
        mode = agent_policy.permission_mode(ctx, conn, name, args)
        journal_owner = None
        journal = {}
        cache_key = cp.digest({'tool': name, 'args': args})
        if getattr(ctx, 'dispatch_id', None):
            dispatch = db.get_dispatch(conn, ctx.slug, ctx.dispatch_id)
            continuation = dispatch['continuation'] or {}
            journal = copy.deepcopy(continuation.get('journal', {}))
            journal_owner = ('dispatch', ctx.dispatch_id, continuation)
        elif ctx.message_id:
            message = store.message(conn, ctx.message_id)
            if not message or message['slug'] != ctx.slug or message['owner_id'] != ctx.me.actor_id:
                raise ToolError('POLICY_DENIED: Invalid private conversation context.')
            journal = db.one(conn, 'SELECT tool_journal FROM projectops.assistant_message WHERE id=%s FOR UPDATE', (ctx.message_id,)) or {}
            journal_owner = ('message', ctx.message_id, None)
        cached = journal.get(cache_key)
        if mode == 'auto' and name in {'studio_plan_allocation', 'studio_inspect_frames'}:
            cached = None  # Read previews follow current sources; fingerprint storage deduplicates FFmpeg.
        if cached and cached.get('in_progress'):
            raise ToolError('Ambiguous prior tool execution; reconcile it before a new request.')
        if cached and 'result' in cached:
            out = cached['result']
            images = []
            if name == 'studio_inspect_frames' and 'frame_sheet_asset_id' in json.loads(out):
                images = studio_tools.cached_frame_images(ctx, conn, args, out)
            conn.rollback()
            return delegation_tools.wait_for_task(ctx, out) if name == 'spawn_agent' and args.get('wait') is True else ToolResult(out, images)
        approved = None
        if cached and cached.get('approved_gate_id'):
            approved = db.get_gate(conn, ctx.slug, cached['approved_gate_id'])
            if not approved or approved['status'] != 'resolved' or approved['resolution'] != '0' or not getattr(ctx, 'dispatch_id', None) or approved['task_id'] != dispatch['task_id']:
                raise ToolError('POLICY_DENIED: Invalid action approval.')
            studio_tools.validate_review(ctx, conn, approved)
        if mode == 'always_ask' and not approved:
            if not journal_owner:
                raise ToolError('Crew review requires a private conversation or M8 context.')
            out = studio_tools.request_review(ctx, conn, name, args)
        else:
            if name in studio_tools.EXTERNAL_TOOLS:
                # Save an attempt before releasing locks; ambiguous inference is never automatically repeated.
                if journal_owner and name == 'consult_advisor':
                    journal[cache_key] = {'tool': name, 'in_progress': True}
                    _save_journal(conn, journal_owner, journal)
                    conn.commit()
                else:
                    conn.rollback()
                agent_policy.authorize_tool(ctx, conn, name, args)
            value = HANDLERS[name](ctx, conn, args)
            out = json.dumps(studio_tools.public_result(conn, ctx.slug, value), ensure_ascii=False) if name in studio_tools.HANDLERS else value
            if approved and name in {'studio_inspect_frames', 'consult_advisor'}:
                studio_tools.validate_review(ctx, conn, approved)
        if name not in DELEGATION_TOOLS and name not in _STRUCTURED:
            out = privacy.text(conn, ctx.slug, out)[0]
        if journal_owner and (name in MUTATING_TOOLS or mode == 'always_ask'):
            journal[cache_key] = {'tool': name, 'result': out}
            try:
                pending = json.loads(out)
                if pending.get('awaiting_gate'): journal[cache_key]['gate_id'] = pending['gate_id']
            except (ValueError, AttributeError):
                pass
            _save_journal(conn, journal_owner, journal)
        actions = list(ctx.post_commit_actions)
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        raise ToolError(getattr(exc, 'code', 'INVALID_REQUEST') + ': ' + str(exc)) from None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    for action in actions:
        action()
    if name == 'spawn_agent' and args.get('wait') is True:
        return delegation_tools.wait_for_task(ctx, out)
    return ToolResult(out if name in DELEGATION_TOOLS or name in _STRUCTURED else _clip(out), ctx.pending_images)


def _save_journal(conn, owner, journal):
    from project_assistant import orchestration_store as db
    kind, identifier, continuation = owner
    if kind == 'dispatch':
        db.execute(conn, 'UPDATE projectops.orchestration_dispatch SET continuation=%s::jsonb WHERE id=%s',
                   (json.dumps({**continuation, 'journal': journal}, ensure_ascii=False), identifier))
    else:
        db.execute(conn, 'UPDATE projectops.assistant_message SET tool_journal=%s::jsonb WHERE id=%s',
                   (json.dumps(journal, ensure_ascii=False), identifier))
