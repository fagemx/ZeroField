"""Create synthetic media-review fixtures only; never overwrite an existing tab.

Run with OPENBENCH_TEST_DB_URI pointing at the local QA database. All PNGs and
the silent WAV are generated in memory. No model, network service, or user image
is used. The whole seed is one transaction and skips an existing fixture.
"""
import io
import json
import os
import wave

import psycopg
from PIL import Image, ImageDraw

from project_assistant import table_edits
from project_docs import page_history, repository as repo, service
from project_docs.doc_schema import column_ids, validate_doc

SLUG = "ux-usability-1016"
KEY = "media-review-60"
TITLE = "素材審核60筆"
TABLE_ID = "b_qa_media_table"
STATUS_OPTIONS = ["待審核", "需調整", "已完成"]


def png(width, height, color, label):
    image = Image.new("RGB", (width, height), color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((12, 12, width - 13, height - 13), outline="white", width=5)
    draw.line((0, 0, width, height), fill="white", width=3)
    draw.line((0, height, width, 0), fill="white", width=3)
    draw.rectangle((22, 22, min(width - 22, 290), 87), fill="#17202a")
    draw.text((32, 34), f"QA SYNTHETIC / {label}\n{width} x {height}", fill="white")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def silent_wav():
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(b"\0\0" * 2000)
    return output.getvalue()


def cell(text, header=False):
    return {"type": "tableHeader" if header else "tableCell", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": text}]} if text else {"type": "paragraph"}
    ]}


def upload(conn, me, data, mime):
    status, result = service.upload_asset(conn, me, SLUG, data, mime)
    if status != 200:
        raise RuntimeError(result)
    return result["src"]


def seed(conn):
    if not repo.get_project(conn, SLUG):
        raise RuntimeError("Create the synthetic QA project first")
    # Serialize fixture creation without schema DDL or changing any existing data.
    with conn.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (SLUG + "/" + KEY,))
        cursor.execute("SELECT 1 FROM projectops.tab WHERE project_slug=%s AND tab_key=%s", (SLUG, KEY))
        if cursor.fetchone():
            return {"status": "preserved_existing", "project": SLUG, "tab_key": KEY}
    members = repo.active_members(conn)
    actor = next((member for member in members if member["actor_id"] == "11111111-1111-4111-8111-111111111111"),
                 next(member for member in members if member["role"] == "admin"))
    me = service.Identity(actor["actor_id"], actor["name"], actor["role"])
    shapes = [
        ("橫圖", 640, 360, "#285f80", "LANDSCAPE V1"),
        ("直圖", 360, 640, "#776b36", "PORTRAIT"),
        ("方圖", 480, 480, "#66517d", "SQUARE"),
    ]
    images = [upload(conn, me, png(width, height, color, label), "image/png") for _, width, height, color, label in shapes]
    replacement = upload(conn, me, png(640, 360, "#a95d31", "LANDSCAPE V2"), "image/png")
    attachment = upload(conn, me, silent_wav(), "audio/wav")
    headers = ["素材", "圖片", "狀態", "說明", "附件", "規格", "覆核備註"]
    rows = [{"type": "tableRow", "attrs": {"bid": "b_qa_media_header"}, "content": [cell(text, True) for text in headers]}]
    for index in range(60):
        kind = index % 3
        shape, width, height, _, _ = shapes[kind]
        empty = index % 8 == 1
        description = "這是本機產生的合成 QA 素材，用於檢查圖片比例、空圖、狀態、長文與返回焦點。"
        if index % 5 == 0:
            description += "\n" + "長文核對：確認完整顯示、捲動以及修改後仍能找到原本的項目。" * 12
        values = [f"QA 素材 {index + 1:02d} · {'空圖' if empty else shape}",
                  "" if empty else f"![本機 QA {shape}]({images[kind]})",
                  STATUS_OPTIONS[index % 3], description,
                  f"[audio]({attachment})" if index % 4 == 0 else "",
                  "尚無圖片" if empty else f"{width} × {height}",
                  "第1筆有 V1 → V2 換圖紀錄，可在媒體歷史核對。" if index == 0 else ""]
        rows.append({"type": "tableRow", "attrs": {"bid": f"b_qa_media_{index + 1:03d}"}, "content": [cell(text) for text in values]})
    table = {"type": "table", "attrs": {"bid": TABLE_ID, "column_types": ["text", "image", "status", "text", "text", "text", "text"]}, "content": rows}
    table["attrs"]["column_ids"] = column_ids(table)
    table["attrs"]["column_options"] = {table["attrs"]["column_ids"][2]: {"options": STATUS_OPTIONS}}
    doc, _ = validate_doc({"type": "doc", "content": [table]}, slug=SLUG)
    repo.create_tab(conn, SLUG, key=KEY, title=TITLE, parent_key=None, doc=doc, actor_id=me.actor_id, surface_type="sheet")
    ops, fields, _ = table_edits.prepare(doc, [{"row_id": "b_qa_media_001", "cells": {"1": f"![本機 QA 橫圖 V2]({replacement})"}}], [], {}, TABLE_ID)
    status, changed = table_edits.apply(conn, me, SLUG, {"tab_key": KEY, "ops": ops, "field_edits": fields})
    if status != 200:
        raise RuntimeError(changed)
    status, annotation = service.create_annotation(conn, me, SLUG, {
        "tab_key": KEY, "row": "b_qa_media_001", "body": "合成 QA 註記：第一版藍色橫圖已換為第二版橘色橫圖；可核對歷史，這不是模型產出。"})
    if status != 200:
        raise RuntimeError(annotation)
    differences = page_history.block_changes(doc, changed["doc"])
    assert len(changed["doc"]["content"][0]["content"]) == 61
    assert any(change.get("media_before") and change.get("media_after") for change in differences)
    assert changed["revision"] == 2
    return {"status": "created", "project": SLUG, "tab_key": KEY, "rows": 60, "revision": changed["revision"],
            "empty_images": 8, "attachments": 15, "versioned_row": "b_qa_media_001", "image_assets": 4}


if __name__ == "__main__":
    with psycopg.connect(os.environ["OPENBENCH_TEST_DB_URI"]) as connection:
        result = seed(connection)
    print(json.dumps(result, ensure_ascii=False))
