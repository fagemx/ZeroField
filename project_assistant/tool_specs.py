"""專案助理工具的名稱、說明、參數格式。純資料：MCP 伺服器（零依賴）和工具主機都讀這一份。

名稱和說明照 10/14 測試版（21 個情境測過的行為）；propose 多了正式機要的定位參數。
"""
from __future__ import annotations

PROPOSE_ACTIONS = ["寫進那一題的討論", "改狀態", "填交接追蹤", "留言問負責人", "在段落加標註", "私下轉給負責人"]
LABELS = {"問題": "q", "要修改": "fix"}
from project_docs.doc_schema import STATUSES

_S = {"type": "string"}
_RO = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}


def _obj(props: dict, required=()) -> dict:
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


TOOLS = [
    {"name": "propose_table_edit", "description": "跨分頁批次修改表格；先 read_page 取得 row_id/table_id，cells 用零起算欄號。new_rows 為完整儲存格陣列。只建立可審核提案，確認後才寫入，過期或鎖定時整批拒絕。",
     "inputSchema": _obj({"tab_key": _S, "table_id": _S,
                          "row_edits": {"type": "array", "items": _obj({"row_id": _S, "cells": {"type": "object", "additionalProperties": {"type": "string"}}}, ["row_id", "cells"])},
                          "new_rows": {"type": "array", "items": {"type": "array", "items": _S}}}, ["tab_key", "row_edits", "new_rows"]),
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}},
    {"name": "list_pages", "description": "列出專案頁所有分頁：代號、名稱、第一段說明。",
     "inputSchema": _obj({}), "annotations": _RO},
    {"name": "read_page",
     "description": "讀專案頁某一個分頁的最新內容。key 用 list_pages 的代號（也可以寫分頁名稱）；section 可以只讀某一段"
                    "（段落標題的關鍵字）。狀態會顯示成〔等待回覆〕這種樣子，可填的空格顯示成（空白，可填）。",
     "inputSchema": _obj({"key": _S, "section": _S, "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 30}}, ["key"]), "annotations": _RO},
    {"name": "search_pages", "description": "在整個專案頁搜尋關鍵字，回傳出現在哪個分頁、哪一段，以及那一行。",
     "inputSchema": _obj({"query": _S}, ["query"]), "annotations": _RO},
    {"name": "my_todo",
     "description": "目前這位使用者的待辦：負責人交代的事、要回答的待確認問題和狀態、交接追蹤上行銷要交的東西、@ 他還沒解決的討論。",
     "inputSchema": _obj({}), "annotations": _RO},
    {"name": "report_list",
     "description": "列出行銷提供的報表：代號、用途、工作表。報表裡的數字一律看不到，只有結構和公式。",
     "inputSchema": _obj({}), "annotations": _RO},
    {"name": "report_overview",
     "description": "看一本報表的總覽：每張工作表的大小、日期範圍、最後有填資料的日期、表頭、是否隱藏、Power Query。"
                    "code 用 report_list 的代號。",
     "inputSchema": _obj({"code": _S}, ["code"]), "annotations": _RO},
    {"name": "report_sheet",
     "description": "看某一張工作表每一欄的內容：欄名、是手動輸入還是公式、公式寫法（同一欄常見的寫法，[r] 代表同一列、"
                    "[r-1] 代表上一列）、最後有填的日期、文字值。columns 可以只看某幾欄，例如 \"A:K\" 或 \"B,F,AA\"。",
     "inputSchema": _obj({"code": _S, "sheet": _S, "columns": _S}, ["code", "sheet"]), "annotations": _RO},
    {"name": "report_cell",
     "description": "看某一格：它屬於哪一欄（欄名）、那一列是哪一天、是手動輸入還是公式；是公式就給公式（手打的數字已遮成 ▢）。"
                    "手動輸入的數值不提供。cell 例如 \"F12\"。",
     "inputSchema": _obj({"code": _S, "sheet": _S, "cell": _S}, ["code", "sheet", "cell"]), "annotations": _RO},
    {"name": "report_find",
     "description": "在報表裡找字：工作表名稱、表頭、文字格、公式寫法。例如找「0.65」「營運」「首日」。code 可以只找某一本。",
     "inputSchema": _obj({"text": _S, "code": _S}, ["text"]), "annotations": _RO},
    {"name": "offer_document",
     "description": "對方明確要「廣告數據專案總覽」的文件檔（Word）、要下載、或要轉寄給別人時才呼叫；呼叫後，這則回答下方會出現"
                    "下載按鈕。回答裡請說「請按下面的按鈕下載」，不要自己貼網址；對方沒要就不要呼叫。檔案內容是專案頁下載當下的最新版。",
     "inputSchema": _obj({}), "annotations": _RO},
    {"name": "propose",
     "description": "提出一項專案頁的修改，等使用者在畫面上按確認才會生效（這個工具本身不會改任何東西）。"
                    "action：寫進那一題的討論（要 page、row、content）、改狀態（page、row、status）、"
                    "填交接追蹤（page、row、content；那一列可填的格子不只一個時加 column）、"
                    "留言問負責人（page，加 row 或 quote，content）、"
                    "在段落加標註（page、quote＝頁面上一字不差的一段字、label、content 可空白）、"
                    "私下轉給負責人（只要 content，只有負責人看得到）。"
                    "page 寫分頁代號或名稱；row 寫題號（例如 1；別張表的第 1 題寫「營運 1」）或那一列第一格的名稱"
                    "（例如 AppsFlyer 事件名稱）。content 用使用者的口吻。",
     "inputSchema": _obj({"action": {"type": "string", "enum": PROPOSE_ACTIONS}, "page": _S, "row": _S, "column": _S,
                          "quote": _S, "label": {"type": "string", "enum": list(LABELS)},
                          "status": {"type": "string", "enum": list(STATUSES)}, "content": _S}, ["action"]),
     "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}},
]
TOOL_NAMES = {tool["name"] for tool in TOOLS}
