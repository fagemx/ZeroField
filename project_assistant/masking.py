"""專案助理的遮罩規則：報表索引、使用者打的字、外洩檢查都用這一份。

原則：廣告數字（花費、收入、安裝等的實際數值）一律換成 ▢；
留下的只有看懂結構需要的東西：比例（≤ 1，例如 0.65）、100 以內的整數（天數、第幾欄）、
年份與日期、版本號（例如 Google 2.5）、名稱裡的編號（例如 AD101、BC-iOS-260814-…）。
"""
from __future__ import annotations

import re

MASK = "▢"

# 文字裡的數字：前後不能黏著英數字、底線、連字號、點（那是名稱或編號的一部分）。
# 只認 ASCII 英數字：\w 會把中文也算進去，「花費1234」就會漏遮。
_NUM_IN_TEXT = re.compile(r"(?<![A-Za-z0-9_\.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(%?)(?![A-Za-z0-9_\-]|\.\d)")
_DATE_LIKE = re.compile(r"\d{4}[/\-.]\d{1,2}[/\-.]\d{1,2}|\d{1,2}[/\-]\d{1,2}(?:[/\-]\d{2,4})?|\d{1,2}:\d{2}")
_WHOLE_NUMERIC = re.compile(r"^[\s$＄¥€]*(?:NT\$|US\$|NTD|USD)?\s*[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*%?\s*(?:元|美金|台幣)?\s*$")


def keep_number(raw: str) -> bool:
    """這個數字可以留下嗎（給公式裡的常數與文字裡的數字共用）。"""
    text = raw.replace(",", "")
    try:
        value = float(text)
    except ValueError:
        return False
    if "," in raw:
        return False  # 有千分位的一定是金額或數量
    if abs(value) <= 1:
        return True  # 比例
    if "." in text:
        whole, frac = text.lstrip("+-").split(".", 1)
        return len(whole) == 1 and len(frac) == 1  # 版本號：1.0、2.5、3.0
    if 1990 <= value <= 2099:
        return True  # 年份
    return abs(value) <= 100  # 天數、第幾欄、第幾題（負數也一樣看大小）


def mask_text(value) -> tuple[str, int]:
    """儲存格文字、表頭、Mia打的字：整格是數字就整格遮；句子裡的數字照 keep_number 判斷。"""
    text = str(value)
    if text.lstrip().startswith("="):
        return mask_formula(text.lstrip())
    text = re.sub(r"\b(USD|NTD|TWD|CNY|RMB|EUR|JPY)(?=[-+]?\d)", r"\1 ", text, flags=re.I)
    if _WHOLE_NUMERIC.match(text) and not _DATE_LIKE.fullmatch(text.strip()):
        stripped = re.sub(r"[^\d.,]", "", text)
        if not keep_number(stripped):
            return MASK, 1
    count = 0
    protected = {}

    def protect(m):
        key = f"\x00{len(protected)}\x00"
        protected[key] = m.group(0)
        return key

    # Inline formulas in Markdown tables must not treat 2000 as a calendar year.
    def inline_formula(match):
        nonlocal count
        masked, n = mask_formula(match.group(0))
        count += n
        key = f"\x00f{len(protected)}\x00"
        protected[key] = masked
        return key

    work = re.sub(r"(?<![A-Za-z0-9_])=[^\s|`]+", inline_formula, text)
    work = _DATE_LIKE.sub(protect, work)

    def repl(m):
        nonlocal count
        number, percent = m.group(1), m.group(2)
        if percent:
            # 百分比只留 100 以內的整數（例如抽成 35%）；帶小數的多半是 CTR、ROAS 這類成效
            if "." in number or "," in number or float(number) > 100:
                count += 1
                return MASK + percent
            return m.group(0)
        if keep_number(number):
            return m.group(0)
        count += 1
        return MASK + percent

    work = _NUM_IN_TEXT.sub(repl, work)
    for key, original in protected.items():
        work = work.replace(key, original)
    return work, count


def mask_formula(formula: str, row: int | None = None) -> tuple[str, int]:
    """公式：常數照 keep_number 遮；文字常數照 mask_text 遮；
    同欄的相對參照換成 [r]、[r-1]…，同一種寫法才歸得在一起。"""
    from openpyxl.formula.tokenizer import Token, Tokenizer

    try:
        tokens = Tokenizer(formula).items
    except Exception:
        return "=（這格公式解析不了，已略過）", 0
    out, masked = [], 0
    for tok in tokens:
        if tok.type == Token.OPERAND and tok.subtype == Token.NUMBER:
            if abs(float(tok.value)) <= 100:
                out.append(tok.value)
            else:
                out.append(MASK)
                masked += 1
        elif tok.type == Token.OPERAND and tok.subtype == Token.TEXT:
            inner = tok.value[1:-1] if len(tok.value) >= 2 else tok.value
            text, n = mask_text(inner)
            masked += n
            out.append('"' + text + '"')
        elif tok.type == Token.OPERAND and tok.subtype == Token.RANGE and row is not None:
            out.append(_relative(tok.value, row))
        else:
            out.append(tok.value)
    return "=" + "".join(out), masked


_REF = re.compile(r"(?<![A-Za-z_\d])(\$?)([A-Z]{1,3})(\$?)(\d+)(?!\d)")


def _relative(ref: str, row: int) -> str:
    # 工作表名稱在 ! 前面，原樣保留；只換 ! 後面的列號
    if "!" in ref:
        sheet, _, cells = ref.rpartition("!")
        return sheet + "!" + _relative(cells, row)

    def repl(m):
        col_abs, col, row_abs, num = m.groups()
        if row_abs:
            return m.group(0)
        offset = int(num) - row
        mark = "[r]" if offset == 0 else f"[r{offset:+d}]"
        return f"{col_abs}{col}{mark}"

    return _REF.sub(repl, ref)


def absolute(pattern: str, row: int) -> str:
    """把 [r]、[r-1] 換回某一列的實際列號。"""
    return re.sub(r"\[r([+-]\d+)?\]", lambda m: str(row + int(m.group(1) or 0)), pattern)


# ---------- 權杖、金鑰 ----------

_SECRETS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"), "私鑰"),
    (re.compile(r'"private_key"\s*:\s*"[^"]*"'), "金鑰檔內容"),
    (re.compile(r"\bEAA[A-Za-z0-9]{20,}"), "Meta 權杖"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}"), "權杖"),
    (re.compile(r"(?<![A-Za-z0-9_])(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{32,}(?![A-Za-z0-9_])"), "像密碼的長字串"),
]


def guard_input(text: str, *, mask_numbers: bool = True) -> tuple[str, list[str]]:
    """Mia打的字在存起來、送給 AI 之前先過這一關：遮掉權杖和數字，回傳要讓她看到的說明。"""
    notes = []
    for pattern, label in _SECRETS:
        found = pattern.findall(text)
        if found:
            text = pattern.sub(f"〔已遮掉的{label}〕", text)
            notes.append(f"已遮掉 {len(found)} 段{label}。權杖和金鑰請放到保管位置，不要貼在這裡。")
    text, count = mask_text(text) if mask_numbers else (text, 0)
    if count:
        notes.append(f"已遮掉 {count} 個數字。廣告數字不會交給助理，助理只看公式和結構。")
    return text, notes
