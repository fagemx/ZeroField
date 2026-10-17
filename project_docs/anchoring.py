"""標註怎麼找回原文：記住選到的字＋前後文，內文改了再找回來。

跟前端 project_docs_ui/src/anchoring.js 同一套規則，兩邊用 tests/fixtures/project_docs_anchor_cases.json 對照。
文字的算法在 doc_schema.doc_text。
"""
from __future__ import annotations

CONTEXT = 32
MAX_QUOTE = 300


def anchor_at(text: str, start: int, quote: str) -> dict:
    end = start + len(quote)
    return {"quote": quote, "start": start,
            "prefix": text[max(0, start - CONTEXT):start], "suffix": text[end:end + CONTEXT]}


def _score(text: str, index: int, anchor: dict) -> int:
    """前後文吻合幾個字（從選取的邊緣往外數，遇到不一樣就停）。"""

    prefix, suffix = anchor.get("prefix") or "", anchor.get("suffix") or ""
    score = 0
    k = 1
    while k <= len(prefix) and index - k >= 0 and text[index - k] == prefix[-k]:
        score += 1
        k += 1
    end = index + len(anchor["quote"])
    k = 0
    while k < len(suffix) and end + k < len(text) and text[end + k] == suffix[k]:
        score += 1
        k += 1
    return score


def resolve(text: str, anchor: dict):
    """找回錨點：(start, end, 原文沒變)；找不到回 None。

    1. 所有完全相同的 quote 裡，選前後文最吻合的；平手選離舊位置最近的（再平手選前面的）。
    2. 原文有改字：前文最後 10 字與後文最前 10 字都還在，就抓夾在中間那一段（不超過原本兩倍加 12 字）。
    """

    quote = anchor.get("quote") or ""
    if not quote:
        return None
    old = anchor.get("start") or 0
    best = None
    index = text.find(quote)
    while index != -1:
        key = (_score(text, index, anchor), -abs(index - old))
        if best is None or key > best[0]:
            best = (key, index)
        index = text.find(quote, index + 1)
    if best is not None:
        return best[1], best[1] + len(quote), True
    prefix = (anchor.get("prefix") or "")[-10:]
    suffix = (anchor.get("suffix") or "")[:10]
    if len(prefix) >= 4 and len(suffix) >= 4:
        index = text.find(prefix)
        while index != -1:
            begin = index + len(prefix)
            end = text.find(suffix, begin)
            if begin < end <= begin + len(quote) * 2 + 12:
                return begin, end, False
            index = text.find(prefix, index + 1)
    return None


def clean_anchor(raw) -> dict | None:
    """前端送來的錨點：只收 quote、start、prefix、suffix，型別與長度要對。"""

    if not isinstance(raw, dict):
        return None
    quote, start = raw.get("quote"), raw.get("start")
    prefix, suffix = raw.get("prefix", ""), raw.get("suffix", "")
    if not isinstance(quote, str) or not quote.strip() or len(quote) > MAX_QUOTE:
        return None
    if not isinstance(start, int) or isinstance(start, bool) or start < 0:
        return None
    if not isinstance(prefix, str) or not isinstance(suffix, str):
        return None
    if len(prefix) > CONTEXT or len(suffix) > CONTEXT:
        return None
    return {"quote": quote, "start": start, "prefix": prefix, "suffix": suffix}
