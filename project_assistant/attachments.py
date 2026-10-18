"""助理對話的附件：上傳時就處理好，送出那一句時才綁上去。

- 圖片（PNG／JPEG／GIF／WebP）：原檔照存，另做縮圖（畫面上用）和預覽（點開看、交給助理），
  尺寸跟美術台的預覽同一組。圖片原樣交給助理（10/14 負責人核可）——圖裡的數字遮不掉，
  畫面上會提醒「有廣告數字的截圖請先遮掉」，規則也叫助理不讀、不引用圖裡的數字。
- Excel（.xlsx／.xlsm）：跟報表索引同一套，只交工作表、欄名、公式；數字在這一步擋掉，
  外洩檢查不過的部分整段拿掉。
- Word（.docx）、PDF、文字檔：抽出文字，跟打字一樣先遮數字和權杖。
  PDF 使用 pypdf；缺少套件時回報格式不可讀，不影響其他附件。
  掃描型的 PDF 抽不出字，請她改用截圖附上（圖片會原樣給助理看）。
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import PurePath
from xml.etree import ElementTree

from project_assistant.masking import guard_input

MAX_BYTES = 8 * 1024 * 1024
MAX_PER_MESSAGE = 5
MAX_TEXT = 20000  # 一個檔交給助理的字數上限
NAME_LIMIT = 120
IMAGE_MAGIC = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "image/webp": (b"RIFF",),
}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
SHEET_EXT = {".xlsx", ".xlsm"}
DOC_EXT = {".docx"}
TEXT_EXT = {".txt", ".csv", ".tsv", ".md", ".json", ".log"}
SUPPORTED = "可以附圖片（PNG、JPEG、GIF、WebP）、Excel（.xlsx）、Word（.docx）、PDF、文字檔（.txt、.csv、.md）"
PDF_TYPE = "application/pdf"
PDF_PAGES = 40  # 交給助理的最多頁數
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
SHEET_NOTE = "只交了工作表、欄名和公式，數字沒有交給助理"
# 存起來的類型照我們認定的種類，不用瀏覽器說的（下載時一律當附件，不在網域上直接打開）
SHEET_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOC_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class AttachmentError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def clean_name(name: str) -> str:
    base = PurePath(str(name or "").replace("\\", "/")).name
    base = re.sub(r"[\x00-\x1f/\\:*?\"<>|]", "", base).strip(" .") or "附件"
    if len(base) <= NAME_LIMIT:
        return base
    stem, dot, ext = base.rpartition(".")
    if dot and len(ext) <= 8:
        return stem[:NAME_LIMIT - len(ext) - 1] + "." + ext
    return base[:NAME_LIMIT]


def _image_type(data: bytes) -> str | None:
    for content_type, magics in IMAGE_MAGIC.items():
        if any(data.startswith(m) for m in magics):
            if content_type == "image/webp" and data[8:12] != b"WEBP":
                continue
            return content_type
    return None


def process(name: str, content_type: str, data: bytes, *, mask_numbers: bool = False) -> dict:
    """回傳要存的欄位；不收或讀不出來就丟 AttachmentError（帶 HTTP 狀態碼和給人看的說法）。"""

    name = clean_name(name)
    data = bytes(data or b"")
    if not data:
        raise AttachmentError(400, "The file is empty.")
    if len(data) > MAX_BYTES:
        raise AttachmentError(413, "Files must be 8 MB or smaller.")
    ext = PurePath(name).suffix.lower()
    if ext in SHEET_EXT | DOC_EXT:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if len(archive.infolist()) > 5000 or sum(i.file_size for i in archive.infolist()) > 64 * 1024 * 1024:
                    raise AttachmentError(413, "The expanded Office file exceeds the size limit.")
        except zipfile.BadZipFile:
            raise AttachmentError(400, "Invalid Office file format.") from None
    claimed = (content_type or "").split(";", 1)[0].strip().lower()
    image_type = _image_type(data)
    if image_type or ext in IMAGE_EXT or claimed.startswith("image/"):
        if not image_type:
            raise AttachmentError(415, "The file content does not match PNG, JPEG, GIF, or WebP image formats.")
        thumb, preview = _image_versions(data)
        return _row("image", name, image_type, data, thumb=thumb, preview=preview)
    if ext in SHEET_EXT:
        if mask_numbers:
            return _row("sheet", name, SHEET_TYPE, data, extracted=_sheet_text(name, data), notes=[f"{name}：{SHEET_NOTE}"])
        return _row("sheet", name, SHEET_TYPE, data, extracted=_full_sheet_text(data))
    if ext in DOC_EXT:
        text, notes = guard_input(_docx_text(data), mask_numbers=mask_numbers)
        return _row("doc", name, DOC_TYPE, data, extracted=_clip(text), notes=[f"{name}：{n}" for n in notes])
    if ext == ".pdf" or claimed == PDF_TYPE or data.startswith(b"%PDF-"):
        text, notes = guard_input(_pdf_text(data), mask_numbers=mask_numbers)
        return _row("doc", name, PDF_TYPE, data, extracted=_clip(text), notes=[f"{name}：{n}" for n in notes])
    if ext in TEXT_EXT or claimed.startswith("text/"):
        text, notes = guard_input(_decode(data), mask_numbers=mask_numbers)
        if not text.strip():
            raise AttachmentError(400, "The file is empty.")
        return _row("text", name, "text/plain", data, extracted=_clip(text), notes=[f"{name}：{n}" for n in notes])
    raise AttachmentError(415, "這種檔案還不能附；" + SUPPORTED)


def _row(kind, name, content_type, data, *, thumb=None, preview=None, extracted="", notes=None) -> dict:
    return {"kind": kind, "name": name, "content_type": content_type, "data": data, "thumb": thumb,
            "preview": preview, "extracted": extracted, "notes": list(notes or [])}


def _clip(text: str) -> str:
    text = text.strip()
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + "\n（後面還有，太長先省略）"


# ---------- 圖片 ----------

def _image_versions(data: bytes) -> tuple[bytes, bytes]:
    from PIL import Image, ImageOps
    PREVIEW_SIZES = {"thumb": (320, 320, 75), "preview": (1500, 1500, 85)}

    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(data)) as opened:
            image = ImageOps.exif_transpose(opened)
            image.load()
    except (Image.DecompressionBombError, OSError, ValueError, SyntaxError):
        raise AttachmentError(400, "The image could not be read. Try another image or a new screenshot.") from None
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA" if ("A" in image.getbands() or image.mode == "P") else "RGB")

    def webp(size_key):
        width, height, quality = PREVIEW_SIZES[size_key]
        copy = image.copy()
        copy.thumbnail((width, height))
        buffer = io.BytesIO()
        copy.save(buffer, "WEBP", quality=quality, method=4)
        return buffer.getvalue()

    return webp("thumb"), webp("preview")


# ---------- Excel：只有結構 ----------

def _full_sheet_text(data):
    import openpyxl
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=False)
        lines, size = [], 0
        try:
            for sheet in workbook.worksheets:
                lines.append(f"## {sheet.title}")
                for row in sheet.iter_rows(max_row=min(sheet.max_row or 0, 5000), max_col=min(sheet.max_column or 0, 100), values_only=True):
                    line = "\t".join("" if v is None else str(v) for v in row)
                    lines.append(line)
                    size += len(line)
                    if size >= MAX_TEXT:
                        return _clip(guard_input("\n".join(lines), mask_numbers=False)[0])
            return _clip(guard_input("\n".join(lines), mask_numbers=False)[0])
        finally:
            workbook.close()
    except Exception as exc:
        raise AttachmentError(400, "The Excel workbook could not be opened.") from exc

def _sheet_text(name: str, data: bytes) -> str:
    import openpyxl

    from project_assistant import report_index, tools

    try:
        wb_f = openpyxl.load_workbook(io.BytesIO(data), data_only=False)
        wb_v = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    except Exception:  # noqa: BLE001 - 壞檔、加密檔、其實不是 Excel
        raise AttachmentError(400, "The workbook could not be opened; it may be encrypted or damaged.") from None
    try:
        book = {"code": "附件", "file": name, "purpose": "", "package": {}, "power_query": [],
                "sheets": [report_index.index_sheet(ws, wb_v[ws.title]) for ws in wb_f.worksheets]}
    finally:
        wb_f.close()
        wb_v.close()
    _drop_leaks(book)
    leaks: list = []
    report_index.walk_book(book, leaks)
    if leaks:
        raise AttachmentError(422, "This workbook contains values that cannot be masked safely. Use an indexed workbook instead.")
    parts = [tools.overview_text(book, "使用者附的 Excel")]
    parts += [tools.sheet_text(book, sh) for sh in book["sheets"]]
    return _clip("\n\n".join(parts))


def _drop_leaks(book: dict) -> None:
    """跟報表索引同一套外洩檢查；查到的那一段整段拿掉，不交給助理。"""

    from project_assistant.report_index import formula_violations, text_violations

    for sh in book["sheets"]:
        sh["titles"] = [t for t in sh.get("titles", []) if not text_violations(t)]
        sh["texts_all"] = [(ref, t) for ref, t in sh.get("texts_all", []) if not text_violations(t)]
        sh["refs_out"] = {k: v for k, v in sh.get("refs_out", {}).items() if not text_violations(k)}
        for col in sh.get("columns", {}).values():
            if text_violations(col.get("label", "")):
                col["label"] = ""
            if col.get("texts"):
                col["texts"]["top"] = [(t, n) for t, n in col["texts"].get("top", []) if not text_violations(t)]
            col["formulas"] = [f for f in col.get("formulas", []) if not formula_violations(f["pattern"])]


# ---------- Word、文字檔 ----------

def _docx_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            root = ElementTree.fromstring(package.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError):
        raise AttachmentError(400, "The Word document could not be opened; it may be encrypted or damaged.") from None
    body = root.find(W + "body")
    lines: list[str] = []

    def paragraph(node) -> str:
        out = []
        for item in node.iter():
            if item.tag == W + "t" and item.text:
                out.append(item.text)
            elif item.tag in (W + "tab",):
                out.append("\t")
            elif item.tag in (W + "br", W + "cr"):
                out.append("\n")
        return "".join(out)

    for child in list(body) if body is not None else []:
        if child.tag == W + "p":
            lines.append(paragraph(child))
        elif child.tag == W + "tbl":
            for row in child.iter(W + "tr"):
                lines.append(" | ".join(paragraph(cell).strip() for cell in row.findall(W + "tc")))
    return "\n".join(line for line in lines if line.strip())


def _pdf_text(data: bytes) -> str:
    try:
        import pypdf
    except ImportError:
        raise AttachmentError(415, "PDF support is not installed on the server. Contact the showrunner or attach a screenshot.") from None
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise AttachmentError(400, "Remove the PDF password before attaching it.")
        total = len(reader.pages)
        pages = [(page.extract_text() or "").strip() for page in list(reader.pages)[:PDF_PAGES]]
    except AttachmentError:
        raise
    except Exception:  # noqa: BLE001 - 壞檔、加密方式讀不了、不是 PDF
        raise AttachmentError(400, "The PDF could not be opened; it may be encrypted or damaged.") from None
    pages = [text for text in pages if text]
    if not pages:
        raise AttachmentError(400, "No text could be extracted from this PDF. Attach a screenshot if it is a scanned document.")
    text = "\n\n".join(pages)
    if total > PDF_PAGES:
        text += f"\n（後面還有 {total - PDF_PAGES} 頁沒讀）"
    return text


def _decode(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    for encoding in ("utf-8-sig", "cp950"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")
