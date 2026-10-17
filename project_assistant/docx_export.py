"""把專案頁整份轉成 Word 檔（.docx）。只用標準函式庫：正式機的 Python 環境不為這個另外裝套件。

只有有人跟專案助理要文件、助理在回答下方放了下載按鈕時才會用到；畫面上沒有其他下載入口。
內容在下載當下照專案頁最新版產生：狀態、可填格、勾選都帶目前的值；站內連結指回專案頁。

XML 元素的順序照 WordprocessingML 的規格寫（rPr、pPr、tcPr…），順序錯了 Word 會說檔案損毀。
"""
from __future__ import annotations

import datetime as dt
import io
import re
import struct
import zipfile
from xml.sax.saxutils import escape, quoteattr

from project_docs.doc_schema import node_text

FONT = "Microsoft JhengHei"
CODE_FONT = "Consolas"
PAGE_TEXT_WIDTH = 9638                # twips：A4 寬 11906，左右邊界各 1134
MAX_IMAGE_EMU = PAGE_TEXT_WIDTH * 635  # 圖最寬就是內文寬（1 twip＝635 EMU）
EMU_PER_PX = 9525                     # 96 DPI
TAIPEI = dt.timezone(dt.timedelta(hours=8))
STATUS_FILL = {"未開始": "F1F0EB", "進行中": "E3EEFB", "等待回覆": "FFF3D6", "卡住": "FBE3E3", "已完成": "E1F4E7"}
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

REL_STYLES = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles"
REL_LINK = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
REL_IMAGE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
W_NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _x(text) -> str:
    return escape(_CONTROL.sub("", str(text)))


def _attr(text) -> str:
    return quoteattr(_CONTROL.sub("", str(text)))


def filename(title: str, when: dt.datetime) -> str:
    safe = _UNSAFE_NAME.sub("", str(title or "專案文件")).strip() or "專案文件"
    return f"{safe}_{when.astimezone(TAIPEI):%Y%m%d}.docx"


# ---------- 圖片尺寸（PNG／GIF／JPEG 自己讀檔頭，不靠 Pillow） ----------

def image_size(data: bytes):
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        return struct.unpack("<HH", data[6:10])
    if data[:2] == b"\xff\xd8":
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                height, width = struct.unpack(">HH", data[index + 5:index + 9])
                return width, height
            length = struct.unpack(">H", data[index + 2:index + 4])[0]
            index += 2 + length
    return None


IMAGE_EXT = {"image/png": "png", "image/jpeg": "jpeg", "image/gif": "gif"}


# ---------- 段落與文字 ----------

def _rpr(*, style=None, font=None, bold=False, italic=False, strike=False, color=None, size=None,
         underline=False, fill=None) -> str:
    parts = []
    if style:
        parts.append(f'<w:rStyle w:val="{style}"/>')
    if font:
        parts.append(f'<w:rFonts w:ascii="{font}" w:hAnsi="{font}"/>')
    if bold:
        parts.append("<w:b/>")
    if italic:
        parts.append("<w:i/>")
    if strike:
        parts.append("<w:strike/>")
    if color:
        parts.append(f'<w:color w:val="{color}"/>')
    if size:
        parts.append(f'<w:sz w:val="{size}"/>')
    if underline:
        parts.append('<w:u w:val="single"/>')
    if fill:
        parts.append(f'<w:shd w:val="clear" w:color="auto" w:fill="{fill}"/>')
    return f"<w:rPr>{''.join(parts)}</w:rPr>" if parts else ""


def run(text, **fmt) -> str:
    return f'<w:r>{_rpr(**fmt)}<w:t xml:space="preserve">{_x(text)}</w:t></w:r>'


def para(runs: str, *, style=None, keep_next=False, page_break=False, quote=False, indent=0, hanging=False) -> str:
    ppr = []
    if style:
        ppr.append(f'<w:pStyle w:val="{style}"/>')
    if keep_next:
        ppr.append("<w:keepNext/>")
    if page_break:
        ppr.append("<w:pageBreakBefore/>")
    if quote:
        ppr.append('<w:pBdr><w:left w:val="single" w:sz="12" w:space="8" w:color="DCD9D0"/></w:pBdr>')
    if indent:
        ppr.append(f'<w:ind w:left="{360 * indent}"' + (' w:hanging="300"' if hanging else "") + "/>")
    return f"<w:p>{('<w:pPr>' + ''.join(ppr) + '</w:pPr>') if ppr else ''}{runs}</w:p>"


def _mark_fmt(marks) -> dict:
    fmt = {}
    for mark in marks or []:
        kind = mark.get("type")
        if kind == "bold":
            fmt["bold"] = True
        elif kind == "italic":
            fmt["italic"] = True
        elif kind == "strike":
            fmt["strike"] = True
        elif kind == "underline":
            fmt["underline"] = True
        elif kind == "code":
            fmt.update(font=CODE_FONT, fill="F5F4EF")
    return fmt


class _Builder:
    def __init__(self, image_loader, base_url):
        self.image_loader = image_loader
        self.base_url = base_url
        self.rels: list[tuple[str, str, str, bool]] = [("rId1", REL_STYLES, "styles.xml", False)]
        self.media: list[tuple[str, bytes]] = []
        self._links: dict[str, str] = {}
        self._pictures = 0

    def _rel(self, kind: str, target: str, external: bool) -> str:
        rid = f"rId{len(self.rels) + 1}"
        self.rels.append((rid, kind, target, external))
        return rid

    def link_target(self, href: str):
        href = str(href or "").strip()
        if re.match(r"^https?://", href):
            return href
        if href.startswith("#") and self.base_url:
            return self.base_url + href
        return None

    def hyperlink(self, href: str, text: str, fmt: dict) -> str:
        target = self.link_target(href)
        if not target:
            return run(text, **fmt)
        rid = self._links.get(target)
        if rid is None:
            rid = self._links[target] = self._rel(REL_LINK, target, True)
        fmt = dict(fmt, style="Hyperlink")
        return f'<w:hyperlink r:id="{rid}" w:history="1">{run(text, **fmt)}</w:hyperlink>'

    def picture(self, attrs: dict) -> str:
        alt = attrs.get("alt") or attrs.get("title") or "圖"
        loaded = self.image_loader(attrs.get("src") or "") if self.image_loader else None
        if not loaded:
            return run(f"（圖：{alt}）", color="74726B")
        content_type, data = loaded
        ext = IMAGE_EXT.get(str(content_type).split(";")[0].strip().lower())
        size = image_size(data) if ext else None
        if not size or not size[0] or not size[1]:
            return run(f"（圖：{alt}）", color="74726B")
        cx, cy = size[0] * EMU_PER_PX, size[1] * EMU_PER_PX
        if cx > MAX_IMAGE_EMU:
            cy = int(cy * MAX_IMAGE_EMU / cx)
            cx = MAX_IMAGE_EMU
        self._pictures += 1
        n = self._pictures
        name = f"image{n}.{ext}"
        self.media.append((name, data))
        rid = self._rel(REL_IMAGE, f"media/{name}", False)
        return ("<w:r><w:drawing>"
                f'<wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
                f'<wp:docPr id="{n}" name="圖 {n}" descr={_attr(alt)}/>'
                '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
                f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{n}" name="{name}"/><pic:cNvPicPr/></pic:nvPicPr>'
                f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
                f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
                '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
                "</a:graphicData></a:graphic></wp:inline></w:drawing></w:r>")

    # ---- 行內 ----
    def inline(self, nodes, values: dict) -> str:
        out = []
        for node in nodes or []:
            kind = node.get("type")
            attrs = node.get("attrs") or {}
            if kind == "text":
                marks = node.get("marks") or []
                fmt = _mark_fmt(marks)
                link = next((m for m in marks if m.get("type") == "link"), None)
                text = node.get("text") or ""
                out.append(self.hyperlink((link.get("attrs") or {}).get("href"), text, fmt) if link else run(text, **fmt))
            elif kind == "hardBreak":
                out.append("<w:r><w:br/></w:r>")
            elif kind == "status":
                label = values.get(attrs.get("fid")) or attrs.get("label") or "未開始"
                out.append(run(f"〔{label}〕", bold=True, fill=STATUS_FILL.get(label)))
            elif kind == "fill":
                value = values.get(attrs.get("fid"))
                out.append(run(value) if value else run("（空白）", italic=True, color="A3A19A"))
            elif kind == "image":
                out.append(self.picture(attrs))
        return "".join(out)

    # ---- 區塊 ----
    def blocks(self, nodes, values: dict, indent: int = 0, quote: bool = False) -> list[str]:
        out: list[str] = []
        for node in nodes or []:
            kind = node.get("type")
            attrs = node.get("attrs") or {}
            if kind == "heading":
                level = min(max(int(attrs.get("level") or 2), 1), 3)
                out.append(para(self.inline(node.get("content"), values), style=f"Heading{level}"))
            elif kind == "paragraph":
                out.append(para(self.inline(node.get("content"), values), indent=indent, quote=quote))
            elif kind in ("bulletList", "orderedList", "taskList"):
                out += self._list(node, values, indent)
            elif kind == "blockquote":
                out += self.blocks(node.get("content"), values, indent=indent + 1, quote=True)
            elif kind == "table":
                out.append(self._table(node, values))
            elif kind == "image":
                out.append(para(self.picture(attrs)))
            elif kind == "horizontalRule":
                out.append('<w:p><w:pPr><w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="DCD9D0"/>'
                           "</w:pBdr></w:pPr></w:p>")
        return out

    def _list(self, node, values: dict, indent: int) -> list[str]:
        out: list[str] = []
        kind = node.get("type")
        start = int((node.get("attrs") or {}).get("start") or 1)
        for number, item in enumerate(node.get("content") or [], start=start):
            item_attrs = item.get("attrs") or {}
            if kind == "orderedList":
                mark = f"{number}."
            elif kind == "taskList":
                stored = values.get(item_attrs.get("fid"))
                done = stored == "true" if stored is not None else bool(item_attrs.get("checked"))
                mark = "☑" if done else "☐"
            else:
                mark = "•"
            first = True
            for child in item.get("content") or []:
                if first and child.get("type") == "paragraph":
                    out.append(para(run(mark + " ") + self.inline(child.get("content"), values), indent=indent + 1,
                                    hanging=True))
                    first = False
                else:
                    out += self.blocks([child], values, indent=indent + 1)
        return out

    def _table(self, node, values: dict) -> str:
        rows = node.get("content") or []
        columns = max((sum(int((c.get("attrs") or {}).get("colspan") or 1) for c in r.get("content") or [])
                       for r in rows), default=1) or 1
        width = PAGE_TEXT_WIDTH // columns
        out = ['<w:tbl><w:tblPr><w:tblStyle w:val="ProjectTable"/><w:tblW w:w="5000" w:type="pct"/>'
               '<w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="0" w:lastColumn="0" '
               'w:noHBand="1" w:noVBand="1"/></w:tblPr><w:tblGrid>'
               + f'<w:gridCol w:w="{width}"/>' * columns + "</w:tblGrid>"]
        for index, row in enumerate(rows):
            cells = row.get("content") or []
            header = index == 0 and bool(cells) and all(c.get("type") == "tableHeader" for c in cells)
            out.append("<w:tr><w:trPr><w:cantSplit/>" + ("<w:tblHeader/>" if header else "") + "</w:trPr>")
            used = 0
            for cell in cells:
                span = int((cell.get("attrs") or {}).get("colspan") or 1)
                used += span
                tcpr = f'<w:tcW w:w="{width * span}" w:type="dxa"/>' + (f'<w:gridSpan w:val="{span}"/>' if span > 1 else "")
                inner = self.blocks(cell.get("content"), values)
                if not inner or not inner[-1].startswith("<w:p"):
                    inner.append("<w:p/>")
                out.append(f"<w:tc><w:tcPr>{tcpr}</w:tcPr>{''.join(inner)}</w:tc>")
            for _ in range(columns - used):  # 短少的格子補空的，Word 才不會說表格壞了
                out.append(f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/></w:tcPr><w:p/></w:tc>')
            out.append("</w:tr>")
        out.append("</w:tbl>")
        return "".join(out)


# ---------- 固定的部分 ----------

STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="{FONT}" w:eastAsia="{FONT}" w:hAnsi="{FONT}" w:cs="{FONT}"/>
<w:sz w:val="21"/><w:szCs w:val="21"/><w:lang w:val="en-US" w:eastAsia="zh-TW"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="300" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:spacing w:after="80"/></w:pPr><w:rPr><w:b/><w:color w:val="1F1E1C"/><w:sz w:val="40"/><w:szCs w:val="40"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:rPr><w:color w:val="74726B"/><w:sz w:val="19"/><w:szCs w:val="19"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr>
<w:rPr><w:b/><w:color w:val="1F1E1C"/><w:sz w:val="32"/><w:szCs w:val="32"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:keepNext/><w:spacing w:before="240" w:after="80"/><w:outlineLvl w:val="1"/></w:pPr>
<w:rPr><w:b/><w:color w:val="1F1E1C"/><w:sz w:val="26"/><w:szCs w:val="26"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:keepNext/><w:spacing w:before="200" w:after="60"/><w:outlineLvl w:val="2"/></w:pPr>
<w:rPr><w:b/><w:color w:val="34332F"/><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:style>
<w:style w:type="character" w:default="1" w:styleId="DefaultParagraphFont"><w:name w:val="Default Paragraph Font"/>
<w:uiPriority w:val="1"/><w:semiHidden/><w:unhideWhenUsed/></w:style>
<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/><w:basedOn w:val="DefaultParagraphFont"/>
<w:rPr><w:color w:val="2F6FD0"/><w:u w:val="single"/></w:rPr></w:style>
<w:style w:type="table" w:default="1" w:styleId="TableNormal"><w:name w:val="Normal Table"/><w:uiPriority w:val="99"/><w:semiHidden/>
<w:unhideWhenUsed/><w:tblPr><w:tblInd w:w="0" w:type="dxa"/><w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left w:w="108" w:type="dxa"/>
<w:bottom w:w="0" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>
<w:style w:type="table" w:styleId="ProjectTable"><w:name w:val="Project Table"/><w:basedOn w:val="TableNormal"/>
<w:pPr><w:spacing w:before="40" w:after="40" w:line="264" w:lineRule="auto"/></w:pPr><w:rPr><w:sz w:val="19"/><w:szCs w:val="19"/></w:rPr>
<w:tblPr><w:tblBorders><w:top w:val="single" w:sz="4" w:space="0" w:color="DCD9D0"/><w:left w:val="single" w:sz="4" w:space="0" w:color="DCD9D0"/>
<w:bottom w:val="single" w:sz="4" w:space="0" w:color="DCD9D0"/><w:right w:val="single" w:sz="4" w:space="0" w:color="DCD9D0"/>
<w:insideH w:val="single" w:sz="4" w:space="0" w:color="DCD9D0"/><w:insideV w:val="single" w:sz="4" w:space="0" w:color="DCD9D0"/></w:tblBorders>
<w:tblCellMar><w:top w:w="60" w:type="dxa"/><w:left w:w="100" w:type="dxa"/><w:bottom w:w="60" w:type="dxa"/><w:right w:w="100" w:type="dxa"/></w:tblCellMar></w:tblPr>
<w:tblStylePr w:type="firstRow"><w:rPr><w:b/></w:rPr><w:tcPr><w:shd w:val="clear" w:color="auto" w:fill="F5F4EF"/></w:tcPr></w:tblStylePr></w:style>
</w:styles>"""

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Default Extension="png" ContentType="image/png"/>
<Default Extension="jpeg" ContentType="image/jpeg"/>
<Default Extension="gif" ContentType="image/gif"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""

PACKAGE_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""


def build(*, title: str, tabs: list[dict], values: dict, image_loader=None, base_url=None, now=None) -> bytes:
    """tabs：照專案頁順序的 [{key, title, doc}]；values：{tab_key: {field_id: 值}}；
    image_loader(src) -> (content_type, bytes) | None；base_url：站內連結 #key 要接在哪個網址後面。"""

    builder = _Builder(image_loader, base_url)
    stamp = (now or dt.datetime.now(TAIPEI)).astimezone(TAIPEI)
    body = [para(run(title), style="Title"),
            para(run(f"下載時間：{stamp:%Y-%m-%d %H:%M}（台北）｜內容是專案頁當下的版本"), style="Subtitle")]
    for index, tab in enumerate(tabs):
        nodes = list((tab.get("doc") or {}).get("content") or [])
        first = nodes[0] if nodes else None
        own_h1 = bool(first and first.get("type") == "heading" and int((first.get("attrs") or {}).get("level") or 2) == 1)
        if index:
            body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
        if own_h1 and node_text(first).strip() == str(title).strip():
            nodes = nodes[1:]  # 跟文件標題一樣，不重複
        elif not own_h1:
            body.append(para(run(tab["title"]), style="Heading1"))
        body += builder.blocks(nodes, values.get(tab["key"], {}))
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document {W_NS}><w:body>{"".join(body)}'
                '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" '
                'w:left="1134" w:header="567" w:footer="567" w:gutter="0"/></w:sectPr></w:body></w:document>')
    rels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
    for rid, kind, target, external in builder.rels:
        rels.append(f'<Relationship Id="{rid}" Type="{kind}" Target={_attr(target)}'
                    + (' TargetMode="External"' if external else "") + "/>")
    rels.append("</Relationships>")
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f"<dc:title>{_x(title)}</dc:title><dc:creator>專案助理</dc:creator>"
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{stamp.astimezone(dt.timezone.utc):%Y-%m-%dT%H:%M:%SZ}</dcterms:created>'
            "</cp:coreProperties>")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", CONTENT_TYPES)
        package.writestr("_rels/.rels", PACKAGE_RELS)
        package.writestr("docProps/core.xml", core)
        package.writestr("word/document.xml", document)
        package.writestr("word/styles.xml", STYLES)
        package.writestr("word/_rels/document.xml.rels", "".join(rels))
        for name, data in builder.media:
            package.writestr(f"word/media/{name}", data)
    return buffer.getvalue()
