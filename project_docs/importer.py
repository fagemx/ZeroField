"""第一次把一份專案的文字稿匯入資料庫。

    python -m project_docs.importer --manifest <資料夾>/manifest.json            # 預演：整包跑一遍再 rollback
    python -m project_docs.importer --manifest <資料夾>/manifest.json --apply    # 真的寫入

manifest.json：
    {"project": {"slug": "ad-data", "title": "廣告數據專案總覽"},
     "actor_email": "alex@openbench.dev",
     "fill_headers": ["請填", "內容或位置", "確認日期"],
     "tabs": [{"key": "overview", "title": "總覽", "parent": null, "file": "01_overview.md"}, ...],
     "images": {"arch": "arch.png"}}

專案已經有分頁就不寫（之後的修改一律在頁面上編輯），不會覆蓋任何東西。
連線用 OPENBENCH_DB_* 環境變數。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from project_docs import repository
from project_docs.doc_schema import index_doc, validate_doc
from project_docs.markdown_import import markdown_to_doc

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".gif": "image/gif", ".webp": "image/webp"}


def import_project(connection, manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    base = manifest_path.parent
    slug = manifest["project"]["slug"]
    title = manifest["project"]["title"]
    repository.ensure_schema(connection)
    actor = next((m for m in repository.active_members(connection)
                  if m["email"] == manifest["actor_email"]), None)
    if not actor:
        raise SystemExit(f"名單裡找不到 {manifest['actor_email']}")
    repository.upsert_project(connection, slug, title)
    existing = repository.list_tabs(connection, slug) + repository.list_tabs(connection, slug, deleted=True)
    if existing:
        raise SystemExit(f"{slug} 已經有 {len(existing)} 個分頁，不匯入（請改用頁面編輯）")

    sources = {}
    for key, name in (manifest.get("images") or {}).items():
        path = base / name
        content_type = IMAGE_TYPES[path.suffix.lower()]
        asset_id = repository.put_asset(connection, slug, data=path.read_bytes(),
                                        content_type=content_type, actor_id=actor["actor_id"])
        sources[key] = f"/projects/api/{slug}/assets/{asset_id}"

    tab_keys = {tab["key"] for tab in manifest["tabs"]}
    fill_headers = tuple(manifest.get("fill_headers") or ("請填", "內容或位置", "確認日期"))
    summary = []
    for position, tab in enumerate(manifest["tabs"], start=1):
        md = (base / tab["file"]).read_text(encoding="utf-8")
        doc, values = markdown_to_doc(md, tab_keys=tab_keys, image_src=sources.get, fill_headers=fill_headers)
        doc, _ = validate_doc(doc, slug=slug)
        repository.create_tab(connection, slug, key=tab["key"], title=tab["title"],
                              parent_key=tab.get("parent"), doc=doc, actor_id=actor["actor_id"],
                              position=position * 10)
        for fid, (kind, value) in values.items():
            repository.set_field_value(connection, slug, tab["key"], fid, kind=kind, value=value,
                                       actor_id=actor["actor_id"])
        fields, anchors = index_doc(doc)
        summary.append({"key": tab["key"], "title": tab["title"], "blocks": len(doc["content"]),
                        "fields": len(fields), "anchors": len(anchors), "filled": len(values)})
    return {"project": slug, "title": title, "actor": actor["name"], "images": sorted(sources),
            "tabs": summary}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    from trend_migration import open_connection

    connection = open_connection()
    try:
        report = import_project(connection, args.manifest)
        if args.apply:
            connection.commit()
        else:
            connection.rollback()
        report["mode"] = "apply" if args.apply else "dry-run"
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
