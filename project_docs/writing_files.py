"""Owner-scoped manuscript intake and immutable real-file/print exports.

Uses file_handoff's bounded ZIP/XML primitives, never fetches relationships.
The conversion is explicitly text-oriented, not a Word fidelity promise.
"""
from __future__ import annotations

import base64
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import html
import re
import uuid
import unicodedata

from project_docs import file_handoff, story_openapi as story
from project_docs.doc_schema import new_id, node_text
from project_docs.writing_tools import (MAX_TEXT, checked_doc, fail, fingerprint, fresh_scope,
                                        selected_actions, sequence, strict, text, _store,
                                        _structure_scenes, block_text)

MAX_TEXT_BYTES = 2_000_000
MIME = {"txt": "text/plain; charset=utf-8", "md": "text/markdown; charset=utf-8",
        "docx": file_handoff.MIME["docx"], "print": "text/html; charset=utf-8"}


def safe_filename(value):
    value = text(value, maximum=500, empty=False)
    # Upload paths are not accepted, not silently opened or used as paths.
    if any(unicodedata.category(c) in {"Cc", "Cf", "Cs"} for c in value) or any(c in value for c in '/\\:'):
        fail("Use a filename without paths or control characters.")
    if len(value) > 200:
        fail("Filename exceeds 200 characters.")
    return value


def _xml(raw):
    root = file_handoff._xml(raw)
    # Also catches UTF-16 DTD encodings that an ASCII byte substring cannot.
    if root.getroottree().docinfo.doctype:
        raise file_handoff.HandoffError("Office XML declarations/entities are not supported")
    return root


def _docx_text(raw):
    W = file_handoff.W
    warnings, paragraphs, headings = {"DOCX is converted to manuscript text; pagination, page layout and Word style fidelity are not retained."}, [], []
    with file_handoff._archive(raw) as archive:
        names = archive.namelist()
        for name in names:
            normalized = name.replace("\\", "/")
            if "\\" in name or any(ord(c) < 32 or ord(c) == 127 for c in name) or re.match(r"^[A-Za-z]:", name) or any(p in {"..", "."} for p in normalized.split("/")):
                raise file_handoff.HandoffError("Unsafe Office part path")
            low = name.lower()
            if any(s in low for s in ("vbaproject", "vba", "activex/")) or low.endswith((".bin", ".exe")):
                raise file_handoff.HandoffError("Macros and embedded executable content are not supported")
            if name.endswith((".xml", ".rels")):
                root = _xml(archive.read(name))
                if name.endswith(".rels") and any(e.get("TargetMode", "").lower() == "external" or
                        re.match(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:|//|\\\\)", e.get("Target", "")) for e in root):
                    raise file_handoff.HandoffError("External Office relationships are not supported")
                if name == "[Content_Types].xml" and any("macroenabled" in e.get("ContentType", "").lower() for e in root):
                    raise file_handoff.HandoffError("Macro-enabled Office content is not supported")
            if re.search(r"word/(?:footnotes|endnotes|comments|header\d*|footer\d*)\.xml$", name):
                warnings.add("Headers, footers, footnotes, endnotes and comments are not imported; review the original file.")
        root = _xml(archive.read("word/document.xml"))
        body = root.find(f"{{{W}}}body")
        if body is None:
            raise file_handoff.HandoffError("DOCX has no document body")
        all_paragraphs = body.findall(f".//{{{W}}}p")
        if len(all_paragraphs) > 10_000:
            fail("DOCX exceeds 10,000 paragraphs.", status=413, code="DRAMA_WRITING_LIMIT_EXCEEDED")
        if body.find(f".//{{{W}}}tbl") is not None:
            warnings.add("Tables are converted to plain paragraphs; cell layout and table formatting are not retained.")
        unsupported = {"drawing": "Images and drawings are not retained.", "object": "Embedded objects are not retained.",
                       "ins": "Tracked revisions are flattened, including inserted and deleted text; review the original file.",
                       "del": "Tracked revisions are flattened, including inserted and deleted text; review the original file.",
                       "commentRangeStart": "Comments are not retained.",
                       "footnoteReference": "Footnote/endnote text and reference markers are not imported; review the original file.",
                       "endnoteReference": "Footnote/endnote text and reference markers are not imported; review the original file.",
                       "fldChar": "Field instructions are not retained; visible field text only.",
                       "instrText": "Field instructions are not retained; visible field text only.",
                       "sdt": "Content controls are flattened; control semantics are not retained.",
                       "altChunk": "Alternative-format embedded content is not imported; review the original file.",
                       "sym": "Special symbol glyphs are not imported; review the original file.",
                       "numPr": "List numbering and bullets are not retained as formatting.",
                       "hyperlink": "Hyperlink text is retained, link targets are not.",
                       "rPr": "Rich text and special Word formatting are not retained."}
        for tag, warning in unsupported.items():
            if body.find(f".//{{{W}}}{tag}") is not None:
                warnings.add(warning)
        if any(isinstance(node.tag, str) and node.tag.rsplit("}", 1)[-1] in {"oMath", "oMathPara"} for node in body.iter()):
            warnings.add("Equations are not converted to manuscript text; review the original file.")
        text_offset = 0
        for paragraph in all_paragraphs:
            chars = []
            def inline_nodes(container):
                for child in container:
                    if child.tag == f"{{{W}}}p":
                        continue  # nested text-box paragraph is processed once separately
                    yield child
                    yield from inline_nodes(child)
            for child in inline_nodes(paragraph):
                if child.tag in {f"{{{W}}}t", f"{{{W}}}delText"}:
                    chars.append(child.text or "")
                elif child.tag == f"{{{W}}}tab":
                    chars.append("\t")
                elif child.tag in {f"{{{W}}}br", f"{{{W}}}cr"}:
                    chars.append("\n")
                elif child.tag == f"{{{W}}}noBreakHyphen":
                    chars.append("\u2011")
                elif child.tag == f"{{{W}}}softHyphen":
                    chars.append("\u00ad")
            value = "".join(chars)
            style = paragraph.find(f"{{{W}}}pPr/{{{W}}}pStyle")
            style_name = style.get(f"{{{W}}}val", "") if style is not None else ""
            if re.fullmatch(r"Heading[123]", style_name, re.I):
                headings.append({"offset": text_offset, "level": int(style_name[-1]), "title": value})
            elif style_name and style_name.lower() != "normal":
                if style_name.lower().startswith(("listnumber", "listbullet")):
                    warnings.add("List numbering and bullets are not retained as formatting.")
                warnings.add("Custom paragraph styles are flattened; unrecognized headings require manual boundary correction.")
            paragraphs.append(value)
            text_offset += len(value) + 1
    return "\n".join(paragraphs), sorted(warnings), headings


def section_preview(value, purpose, headings=()):
    """Purpose-specific heading grammar; no heading means one complete section."""
    starts, offset = [], 0
    paragraph_headings = {h["offset"]: h["title"] for h in headings}
    for index, line in enumerate(value.splitlines(keepends=True)):
        content = line.rstrip("\r\n")
        if purpose == "script":
            match = re.match(r"^\s*(?:#{1,3}\s*)?(?:Scene\s*\d+|INT\.|EXT\.|場景\s*[一二三四五六七八九十\d]+)", content, re.I)
        elif purpose == "novel":
            match = re.match(r"^\s*(?:#{1,3}\s+|Chapter\s+(?:\d+|[IVXLCDM]+)\b|第[^\s]{1,12}[章节章節回])", content, re.I)
        else:
            match = re.match(r"^#{1,2}\s+", content)
        if match or offset in paragraph_headings:
            starts.append((offset, paragraph_headings.get(offset, content.strip())))
        offset += len(line)
    if not starts:
        starts = [(0, "Imported manuscript")]
    elif starts[0][0] != 0:
        starts.insert(0, (0, "Opening text"))
    if len(starts) > 1000:
        fail("More than 1,000 manuscript sections; split the source.", status=413, code="DRAMA_WRITING_LIMIT_EXCEEDED")
    return [{"sectionId": f"sec_{i + 1}", "title": title[:200], "start": start,
             "end": starts[i + 1][0] if i + 1 < len(starts) else len(value), "included": True}
            for i, (start, title) in enumerate(starts)]


def parse_upload(filename, raw, purpose):
    filename = safe_filename(filename)
    if not isinstance(purpose, str) or purpose not in {"idea", "novel", "script"}:
        fail("Writing purpose must be idea, novel or script.")
    extension = filename.rsplit(".", 1)[-1].lower()
    if extension not in {"txt", "md", "docx"}:
        fail("Supported manuscript formats are TXT, Markdown and DOCX.")
    if not isinstance(raw, bytes) or not raw:
        fail("Upload must contain file bytes.")
    maximum = file_handoff.MAX_FILE_BYTES if extension == "docx" else MAX_TEXT_BYTES
    if len(raw) > maximum:
        fail("Manuscript file exceeds the format's byte limit.", status=413, code="DRAMA_WRITING_LIMIT_EXCEEDED")
    headings, warnings = [], []
    try:
        if extension == "docx":
            value, warnings, headings = _docx_text(raw)
        else:
            value = raw.decode("utf-8-sig")
            if extension == "md":
                warnings.append("Markdown is imported as literal manuscript text; markup is preserved, not rendered or fetched.")
    except story.StoryError:
        raise
    except Exception:
        fail("Cannot read manuscript: malformed, unsafe or unsupported content.")
    if "\x00" in value:
        fail("Manuscripts must not contain NUL characters.")
    if len(value) > MAX_TEXT:
        fail("Manuscript exceeds 500,000 Unicode code points; split it.", status=413, code="DRAMA_WRITING_LIMIT_EXCEEDED")
    return {"filename": filename, "format": extension, "purpose": purpose, "text": value,
            "uploadHash": "sha256:" + hashlib.sha256(raw).hexdigest(), "warnings": warnings,
            "sections": section_preview(value, purpose, headings)}


def _proposal(parsed, *, origin_preview_id=None):
    sections = parsed["sections"]
    excluded = [{"start": s["start"], "end": s["end"], "sectionId": s["sectionId"]} for s in sections if not s.get("included", True)]
    warnings = list(parsed.get("warnings", []))
    if excluded:
        warnings.append("Explicitly excluded sections are not copied into the new draft; the upload preview retains the full source text until expiry.")
    if parsed["purpose"] == "script" and len(sections) > 1 and sections[0]["title"] == "Opening text":
        warnings.append("Opening text is retained in the screenplay document as preamble, outside the production scene list.")
    action = {"actionId": "import_document", "kind": "create_branch" if parsed["purpose"] == "script" else "create_source", "purpose": parsed["purpose"]}
    return {"kind": "import", "filename": parsed["filename"], "purpose": parsed["purpose"], "uploadHash": parsed["uploadHash"],
            "sections": sections, "sourceFingerprints": [{"uploadHash": parsed["uploadHash"], "uploadPreviewId": origin_preview_id}],
            "targetFingerprints": [], "allowedActions": [{"actionId": "import_document"}],
            "proposedChanges": {"actions": [action], "text": parsed["text"], "sections": sections,
                                "excludedRanges": excluded, "sourceFormat": parsed["format"]}, "warnings": warnings}


def upload(conn, scope, raw, headers):
    scope = fresh_scope(conn, scope, write=True)
    normalized = {str(k).lower(): v for k, v in (headers or {}).items()}
    def alias(primary, legacy, default):
        if primary in normalized and legacy in normalized and normalized[primary] != normalized[legacy]:
            fail("Conflicting manuscript upload header aliases.")
        return normalized.get(primary, normalized.get(legacy, default))
    from urllib.parse import unquote
    try:
        filename = unquote(alias("x-filename", "x-file-name", ""), encoding="utf-8", errors="strict")
    except (UnicodeError, TypeError):
        fail("Upload filename must use valid percent-encoded UTF-8.")
    purpose = alias("x-writing-purpose", "x-file-purpose", "novel")
    parsed = parse_upload(filename, raw, purpose)
    # Parse fixed bytes before the project lock; then reauthorize before any
    # metadata/receipt persistence. Core also authorizes on receipt replay.
    _store().lock_project(conn, scope)
    scope = fresh_scope(conn, scope, write=True)
    return _store().create_preview(conn, scope, "import", _proposal(parsed))


def _correct_sections(value, sections):
    sequence(sections, 1000)
    if not sections:
        fail("Keep at least one explicit manuscript section.")
    result, offset, ids = [], 0, set()
    for section in sections:
        strict(section, {"sectionId", "title", "start", "end", "included"}, {"sectionId", "title", "start", "end"})
        text(section["sectionId"], maximum=100, empty=False)
        text(section["title"], maximum=200, empty=False)
        start, end = section["start"], section["end"]
        if type(start) is not int or type(end) is not int or start != offset or not start <= end <= len(value):
            fail("Sections must cover the entire source in order without gaps or overlaps; explicitly exclude unwanted ranges.")
        if start == end and value:
            fail("Empty manuscript boundaries are not supported.")
        if (start and value[start - 1] != "\n") or (end < len(value) and end and value[end - 1] != "\n"):
            fail("Section boundaries must fall at line starts; the original text is never split or rewritten implicitly.")
        if section["sectionId"] in ids or type(section.get("included", True)) is not bool:
            fail("Section IDs must be unique and included must be boolean.")
        ids.add(section["sectionId"])
        result.append({**section, "included": section.get("included", True)})
        offset = end
    if offset != len(value) or not any(s["included"] for s in result):
        fail("Preserve all source ranges and select at least one section.")
    return result


def build_preview(conn, scope, body):
    scope = fresh_scope(conn, scope, write=True)
    strict(body, {"kind", "uploadPreviewId", "uploadHash", "sections"}, {"kind", "uploadPreviewId", "uploadHash", "sections"})
    if body["kind"] != "import":
        fail("Unsupported preview kind.")
    previous = _store().get_preview(conn, scope, body["uploadPreviewId"])
    if previous.get("kind") != "import" or previous.get("uploadHash") != body["uploadHash"]:
        fail("Upload preview changed or is unavailable.", status=409, code="DRAMA_WRITING_PREVIEW_STALE")
    changes = previous["proposedChanges"]
    sections = _correct_sections(changes["text"], body["sections"])
    parsed = {"filename": previous["filename"], "format": changes["sourceFormat"], "purpose": previous["purpose"],
              "text": changes["text"], "uploadHash": previous["uploadHash"], "sections": sections, "warnings": previous.get("warnings", [])}
    return _proposal(parsed, origin_preview_id=body["uploadPreviewId"])


def literal_doc(value, slug):
    # split('\n'), not splitlines/strip: preserve dialogue newlines, blank lines,
    # trailing whitespace, CRLF and psychology prose exactly in source doc.
    content = []
    for line in value.split("\n"):
        node = {"type": "paragraph", "attrs": {"bid": new_id("b")}}
        if line:
            node["content"] = [{"type": "text", "text": line}]
        content.append(node)
    return checked_doc({"type": "doc", "content": content}, slug)


def apply_preview(conn, scope, preview, selection):
    scope = fresh_scope(conn, scope, write=True)
    actions = selected_actions(preview, selection)
    if len(actions) != 1 or actions[0]["actionId"] != "import_document":
        fail("Select the frozen manuscript import action.")
    changes = preview["proposedChanges"]
    sections = _correct_sections(changes["text"], changes["sections"])
    retained = "".join(changes["text"][s["start"]:s["end"]] for s in sections if s["included"])
    doc = literal_doc(retained, scope.slug)
    # Manuscript chapter metadata is intentionally not screenplay reconciliation:
    # original prose is never sanitized or rewritten by the adapter.
    structure, retained_offset = {"sections": []}, 0
    block_offsets, offset = [], 0
    for node in doc["content"]:
        block_offsets.append((offset, node["attrs"]["bid"]))
        offset += len(block_text(node)) + 1
    for section in sections:
        if not section["included"]:
            continue
        size = section["end"] - section["start"]
        structure["sections"].append({"key": section["sectionId"], "title": section["title"],
                                      "blockBids": [bid for at, bid in block_offsets if retained_offset <= at < retained_offset + size]})
        retained_offset += size
    metadata = {"filename": preview["filename"], "format": changes["sourceFormat"], "uploadHash": preview["uploadHash"],
                "conversionWarnings": preview.get("warnings", []), "excludedRanges": changes.get("excludedRanges", [])}
    if preview["purpose"] in {"idea", "novel"}:
        from project_docs import writing_service
        source_structure = {"chapters": structure["sections"]} if preview["purpose"] == "novel" else structure
        saved = writing_service.save_source(conn, scope, preview["purpose"], {
            "baseVersion": 0, "clientMutationId": "import-" + preview["previewId"], "doc": doc,
            "structure": source_structure, "composition": {}})
        identifier = saved.get("resourceId") or saved.get("sourceId")
        saved = _store().cas_record(conn, scope, "writing_source", identifier,
                                    base_version=saved["version"], changes={"sourceFile": metadata})
        ref = {"kind": "source", "mode": preview["purpose"]}
        # Metadata CAS is in this same import transaction, never a later partial
        # save. No original-file download is advertised without a retained blob.
    else:
        # Corrected screenplay boundaries become explicit private branch scene
        # metadata. Keep all original lines; an import is not a source rewrite.
        from project_docs import writing_structure
        by_bid = {n["attrs"]["bid"]: n for n in doc["content"]}
        imported_scenes = []
        for position, section in enumerate(structure["sections"]):
            if position == 0 and len(structure["sections"]) > 1 and section["title"] == "Opening text":
                continue
            index = len(imported_scenes) + 1
            nodes = [by_bid[bid] for bid in section["blockBids"]]
            heading = nodes[0] if nodes and writing_structure.HEADING.match(block_text(nodes[0])) else None
            prose_nodes = nodes[1:] if heading else nodes
            imported_scenes.append({"sceneKey": "wsc_" + uuid.uuid4().hex, "headingBid": heading["attrs"]["bid"] if heading else None,
                                    "blockBids": [n["attrs"]["bid"] for n in prose_nodes], "title": section["title"], "order": index,
                                    "mapping": "exact", "contentHash": writing_structure._content_hash(nodes),
                                    "beats": [{"beatKey": "wbt_" + uuid.uuid4().hex, "blockBids": [n["attrs"]["bid"]],
                                               "textHash": _store().hash_value(block_text(n)), "contentHash": writing_structure._content_hash([n]), "mapping": "exact"}
                                              for n in prose_nodes if block_text(n).strip()]})
        if sum(len(scene["beats"]) for scene in imported_scenes) > 1000:
            fail("Split screenplays above 1,000 narrative units into smaller episodes.", status=413, code="DRAMA_WRITING_LIMIT_EXCEEDED")
        structure = {"scenes": imported_scenes, "lanes": [], "tombstones": [], "lineage": {}, "docHash": _store().doc_hash(doc)}
        structure["structureHash"] = writing_structure.fingerprint(structure)
        identifier = "wbr_" + uuid.uuid4().hex
        saved = _store().insert_record(conn, scope, "writing_branch", identifier, {
            "branchId": identifier, "name": preview["filename"].rsplit(".", 1)[0], "doc": doc, "docHash": _store().doc_hash(doc),
            "structure": structure, "structureHash": structure["structureHash"], "composition": _store().composition(doc), "locked": False, "archived": False,
            "sourceFile": metadata, "baseFingerprint": {"uploadHash": preview["uploadHash"]}, "visibility": "private"})
        ref = {"kind": "branch", "id": identifier}
    return {"sourceRef": ref, "resourceId": saved.get("resourceId") or saved.get("sourceId") or saved.get("branchId"),
            "docHash": saved.get("docHash", _store().doc_hash(doc)), "version": saved.get("version"), "uploadHash": preview["uploadHash"]}


def _packet(conn, scope, resolved, scene_keys, include):
    doc = copy.deepcopy(resolved["doc"])
    scenes = _structure_scenes(resolved)
    chosen = scenes
    if scene_keys is not None:
        sequence(scene_keys, 1000)
        for key in scene_keys:
            text(key, maximum=200, empty=False)
        if not scene_keys or len(set(scene_keys)) != len(scene_keys) or set(scene_keys) - {s["sceneKey"] for s in scenes}:
            fail("Choose existing stable source scenes.")
        chosen = [s for s in scenes if s["sceneKey"] in scene_keys]
        bids = {b for s in chosen for b in [s.get("headingBid"), *s.get("blockBids", []),
                                             *(bid for beat in s.get("beats", []) for bid in beat.get("blockBids", []))] if b}
        doc["content"] = [n for n in doc.get("content", []) if n.get("attrs", {}).get("bid") in bids]
        if not doc["content"]:
            fail("Source scene boundaries are unresolved.", status=409, code="DRAMA_WRITING_MAPPING_REQUIRED")
    strict(include, {"summaries", "bibleIds"})
    if type(include.get("summaries", False)) is not bool:
        fail("summaries must be boolean.")
    if include.get("summaries"):
        for scene in chosen:
            if scene.get("summary"):
                doc.setdefault("content", []).append({"type": "paragraph", "attrs": {"bid": new_id("b")},
                                                     "content": [{"type": "text", "text": "Summary: " + scene["summary"]}]})
    from project_docs.writing_tools import bible_view, TEXT_FIELDS
    for identifier in sequence(include.get("bibleIds", []), 20):
        text(identifier, maximum=200, empty=False)
        record = _store().get_record(conn, scope, "writing_bible", identifier)
        view = bible_view(conn, scope, record)
        title = view.get("asset", {}).get("name") or view.get("title", "Setting")
        doc.setdefault("content", []).append({"type": "heading", "attrs": {"bid": new_id("b"), "level": 2},
                                             "content": [{"type": "text", "text": title}]})
        values = [(key, record[key]) for key in sorted(TEXT_FIELDS) if record.get(key)]
        if record.get("aliases"):
            values.append(("aliases", ", ".join(record["aliases"])))
        values.extend(("event " + event["episodeId"] + "/" + event["sceneKey"], event["note"])
                      for event in record.get("events", []))
        for key, value in values:
            doc["content"].append({"type": "paragraph", "attrs": {"bid": new_id("b")},
                                   "content": [{"type": "text", "text": key + ": " + value}]})
    return checked_doc(doc, scope.slug)


def _plain(doc):
    return "\n".join(block_text(n) for n in doc.get("content", []))


def render_export(doc, fmt, *, title):
    """Pure, fixed-input rendering. Print is HTML, never fabricated PDF bytes."""
    if fmt == "txt":
        return (title + "\n\n" + _plain(doc)).encode("utf-8")
    if fmt == "md":
        lines = ["# " + title, ""]
        for node in doc.get("content", []):
            prefix = "#" * node.get("attrs", {}).get("level", 2) + " " if node.get("type") == "heading" else ""
            lines.append(prefix + block_text(node))
        return ("\n".join(lines) + "\n").encode("utf-8")
    if fmt == "docx":
        titled = {"type": "doc", "content": [{"type": "heading", "attrs": {"level": 1},
                                                   "content": [{"type": "text", "text": title}]}, *copy.deepcopy(doc.get("content", []))]}
        def materialize_breaks(node):
            if node.get("type") == "hardBreak":
                node.clear()
                node.update(type="text", text="\n")
            for child in node.get("content", []):
                materialize_breaks(child)
        materialize_breaks(titled)
        return file_handoff.export_file(titled, fmt, mode="new_workbook")
    if fmt != "print":
        fail("Unsupported manuscript export format.")
    elements = []
    for node in doc.get("content", []):
        tag = "h2" if node.get("type") == "heading" else "p"
        elements.append(f"<{tag}>" + html.escape(block_text(node)) + f"</{tag}>")
    value = ("<!doctype html><html><head><meta charset=\"utf-8\"><meta name=\"referrer\" content=\"no-referrer\">"
             "<title>" + html.escape(title) + "</title><style>body{max-width:48rem;margin:2rem auto;font:12pt serif;line-height:1.6}"
             "p{white-space:pre-wrap}h2{break-before:page}h1,h2{break-after:avoid}@media print{body{margin:0;max-width:none}}</style>"
             "</head><body><h1>" + html.escape(title) + "</h1>" + "".join(elements) + "</body></html>")
    return value.encode("utf-8")


def create_export(conn, scope, body):
    scope = fresh_scope(conn, scope)
    strict(body, {"sourceRef", "expectedHash", "sceneKeys", "format", "include"}, {"sourceRef", "expectedHash", "format"})
    fmt = body["format"]
    if not isinstance(fmt, str) or fmt not in MIME:
        fail("Export formats are txt, md, docx and print (Print / Save as PDF).")
    resolved = _store().resolve_ref(conn, scope, body["sourceRef"])
    if resolved["docHash"] != body["expectedHash"]:
        fail("Source changed before export.", status=409, code="DRAMA_WRITING_PREVIEW_STALE")
    include = body.get("include", {})
    doc = _packet(conn, scope, resolved, body.get("sceneKeys"), include)
    source_name = resolved.get("name") or resolved.get("catalog", {}).get("name")
    if body["sourceRef"].get("kind") == "version":
        source_name = _store().get_record(conn, scope, "writing_version", body["sourceRef"]["id"])["name"]
    elif body["sourceRef"].get("kind") == "source":
        source_name = source_name or resolved.get("sourceFile", {}).get("filename") or body["sourceRef"]["mode"].title() + " source"
    else:
        source_name = source_name or ("Working screenplay" if body["sourceRef"].get("kind") == "working" else "Private branch")
    title = scope.episode.get("title", "Episode") + (" — " + source_name if source_name else "")
    if body.get("sceneKeys"):
        titles = [s.get("title", s["sceneKey"]) for s in _structure_scenes(resolved) if s["sceneKey"] in body["sceneKeys"]]
        title += " — Selected scenes (" + str(len(titles)) + "): " + ", ".join(t[:80] for t in titles[:5]) + (" …" if len(titles) > 5 else "")
    raw = render_export(doc, fmt, title=title)
    identifier = "wexp_" + uuid.uuid4().hex
    filename = re.sub(r"[^\w .-]", "_", title, flags=re.UNICODE).strip(" .")[:150] or "Manuscript"
    filename += ".html" if fmt == "print" else "." + fmt
    expires = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    warnings = []
    if any(node.get("type") not in {"paragraph", "heading"} for node in doc.get("content", [])):
        warnings.append("This is a manuscript text conversion; non-text content and complex document layout are not reproduced.")
    record = {"exportId": identifier, "visibility": "private", "sourceRef": body["sourceRef"], "sourceHash": resolved["docHash"],
              "snapshot": {"doc": doc, "title": title, "sceneKeys": body.get("sceneKeys")}, "format": fmt,
              "bytesBase64": base64.b64encode(raw).decode("ascii"), "filename": filename, "contentType": MIME[fmt],
              "expiresAt": expires, "include": include}
    # The fixed-input renderer runs before locking. Reauthorize all referenced
    # inputs and check the source content again before persisting this handle.
    _store().lock_project(conn, scope)
    scope = fresh_scope(conn, scope)
    current = _store().resolve_ref(conn, scope, body["sourceRef"])
    if current["docHash"] != resolved["docHash"]:
        fail("Source changed while preparing export.", status=409, code="DRAMA_WRITING_PREVIEW_STALE")
    for bible_id in include.get("bibleIds", []):
        _store().get_record(conn, scope, "writing_bible", bible_id)
    _store().insert_record(conn, scope, "writing_export", identifier, record)
    return {k: record[k] for k in ("exportId", "sourceRef", "sourceHash", "format", "filename", "contentType", "expiresAt")} | {
        "contentPath": f"exports/{identifier}/content", "delivery": "print" if fmt == "print" else "download", "warnings": warnings}


def export_content(conn, scope, identifier):
    scope = fresh_scope(conn, scope)
    record = _store().get_record(conn, scope, "writing_export", identifier)
    # Owner+current membership first, recursively authorize references before
    # touching bytes, regardless of the handle's unguessability or expiry.
    _store().resolve_ref(conn, scope, record["sourceRef"])
    for bible_id in record.get("include", {}).get("bibleIds", []):
        _store().get_record(conn, scope, "writing_bible", bible_id)
    try:
        expired = datetime.fromisoformat(record["expiresAt"]) <= datetime.now(timezone.utc)
    except (ValueError, TypeError):
        expired = True
    if expired:
        fail("Export expired; create a new export.", status=404, code="DRAMA_NOT_FOUND")
    from project_docs.writing_http import BinaryResponse
    raw = base64.b64decode(record["bytesBase64"], validate=True)
    # RFC5987 for multilingual names; ASCII fallback cannot inject headers.
    from urllib.parse import quote
    filename = safe_filename(record["filename"])
    fallback = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
    headers = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
               "Content-Disposition": ("inline" if record["format"] == "print" else "attachment") +
               f"; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"}
    if record["format"] == "print":
        headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'; sandbox allow-modals"
    return BinaryResponse(raw, record["contentType"], headers=headers)


def dispatch(conn, scope, method, tail, body, query, *, raw=None, headers=None):
    if method == "POST" and tail == "imports":
        return upload(conn, scope, raw, headers)
    if method == "POST" and tail == "exports":
        return create_export(conn, scope, body)
    match = re.fullmatch(r"exports/([A-Za-z0-9_-]{1,150})/content", tail)
    if method == "GET" and match:
        return export_content(conn, scope, match[1])
    return _store().UNHANDLED
