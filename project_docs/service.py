"""專案文件的規則：誰能做什麼、輸入怎麼檢查、哪些動作要留紀錄。

每個函式回傳 (HTTP 狀態碼, JSON)。身分只從 Identity 來（伺服器驗過的登入＋名單），
請求內容裡的作者、名字、角色、owner 欄位一律不看。

會改東西的動作都另外記一筆系統紀錄（repo.add_audit）：誰、什麼時候、改了什麼。
只給工程查（python -m project_docs.history），不放進回給畫面的內容。
"""
from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from project_docs import anchoring, blocks, page_history
from project_docs import repository as repo
from project_docs.history import doc_changes
from project_docs.doc_schema import (
    ID_RE,
    STATUSES,
    TAB_KEY_RE,
    DocError,
    doc_text,
    index_doc,
    new_id,
    node_text,
    table_row_ids,
    validate_doc,
)

ROLE_LABEL = {"admin": "管理者", "director": "總監", "marketing_lead": "行銷主管", "marketer": "行銷",
              "engineer": "技術部", "writer": "編劇", "art_lead": "主美", "member": "成員", "viewer": "檢視者"}
MENTION_RE = re.compile(r"@\{([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\}")
MAX_COMMENT = 4000
MAX_FILL = 2000
MAX_IMAGE = 8 * 1024 * 1024
IMAGE_MAGIC = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "image/webp": (b"RIFF",),
}
STYLES = ("hl", "ul")
COLORS = ("y", "g", "b", "p")
LABELS = ("q", "fix", "ok")
LOCK_SECONDS = 90
HISTORY_LIMIT = 150  # 修改紀錄：這一頁最多列幾筆
HISTORY_LIMIT_ALL = 80  # 全部分頁最多列幾筆


@dataclass(frozen=True)
class Identity:
    actor_id: str
    name: str
    role: str

    @property
    def can_edit(self) -> bool:
        return self.role == "admin"

    @property
    def can_write(self) -> bool:
        return self.role != "viewer"

    def public(self) -> dict:
        return {"actor_id": self.actor_id, "name": self.name, "role": self.role,
                "role_label": ROLE_LABEL.get(self.role, "成員"), "can_edit": self.can_edit, "can_write": self.can_write,
                "auth_mode": __import__("os").environ.get("OPENBENCH_AUTH_MODE", "dev")}


def identity_from(copy_identity) -> Identity | None:
    """文案工作台驗過的身分 → Identity；不是名單上 active 的人回 None。"""

    if not isinstance(copy_identity, dict):
        return None
    if copy_identity.get("status") != "active" or not copy_identity.get("directory_registered"):
        return None
    actor_id = str(copy_identity.get("actor_id") or "").strip()
    if not actor_id:
        return None
    return Identity(actor_id=actor_id, name=str(copy_identity.get("name") or "").strip() or "（沒有名字）",
                    role=str(copy_identity.get("role") or "marketer"))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _error(status: int, message: str):
    return status, {"error": message}


def _need_editor(me: Identity):
    return None if me.can_edit else _error(403, "只有管理者可以看版本紀錄、復原刪掉的分頁")


def _need_tab_manager(me: Identity, tab: dict):
    """改名、移動、刪除一頁：管理者，或新增這一頁的人（10/15 起名單上的人都能新增分頁）。"""
    if me.can_edit or (tab.get("created_by") and tab["created_by"] == me.actor_id):
        return None
    return _error(403, "只有新增這一頁的人和管理者可以改名、移動或刪除這一頁")


def _project_or_404(conn, slug):
    project = repo.get_project(conn, slug)
    return project, (None if project else _error(404, "找不到這個專案"))


def _member_payload(member: dict) -> dict:
    return {"actor_id": member["actor_id"], "name": member["name"], "role": member["role"],
            "role_label": ROLE_LABEL.get(member["role"], "行銷"),
            "email": member["email"].split("@", 1)[0]}


def _names(conn) -> dict:
    return {m["actor_id"]: m["name"] for m in repo.active_members(conn)}


# ---------- 讀 ----------

def me_payload(me: Identity):
    return 200, {"me": me.public()}


def projects_payload(conn, me: Identity):
    return 200, {
        "projects": repo.list_projects(conn),
        "members": [_member_payload(m) for m in repo.active_members(conn)],
        "me": me.public(),
    }


def _template_tabs(template, title, summary):
    from project_docs.templates import tab_specs
    return tab_specs(template, title, summary)


def create_project(conn, me: Identity, body: dict):
    from project_docs import markdown_import, templates
    slug = str(body.get("slug") or "").strip().lower()
    if not TAB_KEY_RE.match(slug):
        return _error(400, "專案代號請用小寫英文、數字或連字號（1～41 字）")
    if repo.get_project(conn, slug):
        return _error(400, f"專案代號 {slug} 已經存在了")
    title = _clean_title(body.get("title"))
    if title is None:
        return _error(400, "專案名稱要 1～200 個字")
    privacy_mode = body.get("privacy_mode", "full_access")
    if privacy_mode not in repo.PRIVACY_MODES:
        return _error(400, "privacy_mode 必須是 full_access 或 mask_numbers")
    if privacy_mode != "full_access" and me.role != "admin":
        return _error(403, "只有管理者可以修改資料遮罩策略")
    status = str(body.get("status") or "planning").strip()
    if status not in repo.PROJECT_STATUSES:
        status = "planning"
    summary = str(body.get("summary") or "").strip()[:400]
    template = str(body.get("template") or "marketing").strip()
    repo.upsert_project(conn, slug, title, status=status, summary=summary)
    if privacy_mode != "full_access":
        repo.update_project_meta(conn, slug, privacy_mode=privacy_mode)
    specs = _template_tabs(template, title, summary)
    if template == "ai_drama":
        specs.append(("deliverables", "成片與交付", "doc", "# 成片與交付\n\n完成的影片會在審核後加入本頁。\n"))
    tab_keys = {k for k, _, _, _ in specs}
    for pos, (key, tab_title, surface_type, md) in enumerate(specs, start=1):
        raw_doc, values = markdown_import.markdown_to_doc(
            md, tab_keys=tab_keys, image_src=lambda _: None
        )
        doc, _ = validate_doc(raw_doc, slug=slug)
        templates.configure_doc(key, doc)
        repo.create_tab(conn, slug, key=key, title=tab_title, parent_key=None, doc=doc,
                        actor_id=me.actor_id, position=pos * 10, surface_type=surface_type)
        for fid, (kind, val) in values.items():
            repo.set_field_value(conn, slug, key, fid, kind=kind, value=val, actor_id=me.actor_id)
    from project_assistant import flow_runner
    for key, definition in templates.flow_specs(template).items():
        flow_runner.save_definition(conn, me, slug, key, {"definition": definition, "revision": 0})
    repo.add_audit(conn, slug, action="project_create", actor_id=me.actor_id,
                   detail={"title": title, "status": status, "template": template})
    return 200, {"project": repo.get_project(conn, slug), "projects": repo.list_projects(conn)}


def update_project(conn, me: Identity, slug: str, body: dict):
    project, problem = _project_or_404(conn, slug)
    if problem:
        return problem
    privacy_mode = body.get("privacy_mode", repo._UNSET)
    if privacy_mode is not repo._UNSET:
        if me.role != "admin":
            return _error(403, "只有管理者可以修改資料遮罩策略")
        if privacy_mode not in repo.PRIVACY_MODES:
            return _error(400, "privacy_mode 必須是 full_access 或 mask_numbers")
    title = _clean_title(body["title"]) if "title" in body else repo._UNSET
    if title is None:
        return _error(400, "專案名稱要 1～200 個字")
    status = str(body["status"]).strip() if "status" in body else repo._UNSET
    if status is not repo._UNSET and status not in repo.PROJECT_STATUSES:
        return _error(400, "不支援這個專案狀態")
    summary = str(body["summary"]).strip()[:400] if "summary" in body else repo._UNSET
    updated = repo.update_project_meta(conn, slug, title=title, status=status, summary=summary,
                                       privacy_mode=privacy_mode)
    repo.add_audit(conn, slug, action="project_update", actor_id=me.actor_id,
                   detail={k: v for k, v in body.items() if k in ("title", "status", "summary", "privacy_mode")})
    return 200, {"project": updated, "projects": repo.list_projects(conn)}


def project_payload(conn, me: Identity, slug: str):
    project, problem = _project_or_404(conn, slug)
    if problem:
        return problem
    return 200, {
        "project": project,
        "tabs": repo.list_tabs(conn, slug),
        "values": repo.field_values(conn, slug),
        "members": [_member_payload(m) for m in repo.active_members(conn)],
        "annotations": repo.list_annotations(conn, slug),
        "locks": repo.active_locks(conn, slug),
        "me": me.public(),
    }


def tab_payload(conn, me: Identity, slug: str, key: str):
    """讀一頁。第一版存的內容第一層區塊還沒有 bid／owner：補好存回去（不掛人名）。"""

    tab = repo.get_tab(conn, slug, key)
    if not tab:
        return _error(404, "找不到這個分頁")
    doc, _ = validate_doc(tab["doc"], slug=slug)
    if doc != tab["doc"]:
        repo.save_tab_doc(conn, slug, key, doc=doc, title=tab["title"], actor_id=None,
                          session_id="system-ids", base_revision=None)
        tab = repo.get_tab(conn, slug, key)
    if tab.get("source_filename"):
        from project_docs import file_handoff
        tab["source_meta"] = file_handoff.compatibility(tab["doc"], repo.get_tab_source(conn, slug, key) or {})
    return 200, {"tab": tab, "values": repo.field_values(conn, slug).get(key, {})}


def preview_import_file(conn, me: Identity, slug: str, filename: str, data: bytes, *,
                        tab_key=None, base_revision=None, header_row=1, worksheet=None, delivery_mode="original_patch"):
    from project_docs import file_handoff
    if not repo.get_project(conn, slug):
        return _error(404, "找不到這個專案")
    tab = None
    if tab_key:
        if not isinstance(tab_key, str) or not TAB_KEY_RE.fullmatch(tab_key):
            return _error(400, "分頁代號格式不對")
        tab = repo.get_tab_for_update(conn, slug, tab_key)
        if not tab:
            return _error(404, "找不到這個分頁")
        try:
            expected = int(base_revision)
        except (ValueError, TypeError):
            return _error(400, "取代既有分頁必須提供 base_revision")
        if expected != tab["revision"]:
            return 409, {"error": "分頁已更新，請重新讀取目前內容再核對匯入", "revision": tab["revision"]}
    try:
        # Raw rows remain visible so header selection always uses source coordinates.
        preview = file_handoff.preview_file(filename, data, slug=slug)
        if tab:
            imported = file_handoff.import_file(filename, data, slug=slug, header_row=header_row, worksheet=worksheet, delivery_mode=delivery_mode)
            preview["replacement"] = {**file_handoff.replacement_preview(tab["doc"], imported.doc, repo.field_values(conn, slug).get(tab_key, {})),
                                      "current_revision": tab["revision"]}
        return 200, preview
    except file_handoff.HandoffError as exc:
        return _error(400, str(exc))


def import_tab_file(conn, me: Identity, slug: str, filename: str, data: bytes, *,
                    tab_key=None, base_revision=None, header_row=1, worksheet=None, delivery_mode="original_patch", confirm_replace=False):
    """Import and replace inside the caller's transaction with a locked revision check."""
    import copy
    from project_docs import file_handoff
    if not repo.get_project(conn, slug):
        return _error(404, "找不到這個專案")
    if tab_key is not None and (not isinstance(tab_key, str) or not TAB_KEY_RE.fullmatch(tab_key)):
        return _error(400, "分頁代號格式不對")
    tab = repo.get_tab_for_update(conn, slug, tab_key) if tab_key else None
    if tab_key:
        if not tab:
            return _error(404, "找不到這個分頁")
        try:
            if isinstance(base_revision, bool) or base_revision is None:
                raise ValueError()
            revision = int(base_revision)
        except (TypeError, ValueError):
            return _error(400, "取代既有分頁必須提供 base_revision")
        if revision != tab["revision"]:
            return 409, {"error": "分頁已更新，請重新載入再匯入", "revision": tab["revision"]}
        # A whole-file replacement may change structure and ownership coordinates.
        # Require every collaborator's live lock to be released before replacing.
        if any(holder != me.actor_id for holder in repo.tab_locks(conn, slug, tab_key).values()):
            return _error(409, "分頁有其他成員正在編輯，請等候編輯鎖釋放再匯入")
        if confirm_replace is not True:
            return _error(400, "請先核對差異並確認：以此檔案取代目前內容，不進行自動合併")
    try:
        imported = file_handoff.import_file(filename, data, slug=slug, header_row=header_row, worksheet=worksheet, delivery_mode=delivery_mode)
    except file_handoff.HandoffError as exc:
        return _error(400, str(exc))
    changes = []
    replacement = None
    if tab:
        values = repo.field_values(conn, slug).get(tab_key, {})
        materialized = file_handoff.materialize_fields(tab["doc"], values)
        replacement = file_handoff.replacement_preview(tab["doc"], imported.doc, values)
        doc = file_handoff.reconcile_ids(materialized, imported.doc)
        doc, _ = validate_doc(doc, slug=slug)
        from project_docs import table_schema
        try:
            table_schema.guard_schema_change(conn, slug, tab_key, tab["doc"], doc)
        except DocError as exc:
            return _error(400, "替換內容會影響現有引用；請先解除引用，或將檔案匯入為新分頁。" + str(exc))
        changes = doc_changes(tab["doc"], doc)
        repo.save_tab_doc(conn, slug, tab_key, doc=doc, title=tab["title"], actor_id=me.actor_id,
                          session_id="import-" + secrets.token_hex(8), base_revision=tab["revision"],
                          force_revision=True)
    else:
        doc = imported.doc
        tab_key = "t-" + secrets.token_hex(8)
        title = imported.filename.rsplit(".", 1)[0] or imported.filename
        repo.create_tab(conn, slug, key=tab_key, title=title, parent_key=None, doc=doc,
                        actor_id=me.actor_id, surface_type=imported.surface_type)
        changes = doc_changes({"type": "doc", "content": []}, doc)
    imported.metadata["baseline"] = copy.deepcopy(doc)
    repo.set_tab_source(conn, slug, tab_key, filename=imported.filename, mime=imported.mime,
                        blob=data, metadata=imported.metadata, surface_type=imported.surface_type)
    repo.add_audit(conn, slug, action="file_import", actor_id=me.actor_id, tab_key=tab_key,
                   detail={"filename": imported.filename, "byte_size": len(data), "changes": changes})
    if tab:
        reanchor_tab(conn, slug, tab_key, doc, actor_id=me.actor_id)
    return 200, {"tab": repo.get_tab(conn, slug, tab_key), "tabs": repo.list_tabs(conn, slug),
                 "changes": changes, "replacement": replacement}


def export_tab_file(conn, me: Identity, slug: str, key: str, fmt: str = "", mode: str = "original_patch"):
    from project_docs import file_handoff
    tab = repo.get_tab(conn, slug, key)
    if not tab:
        return _error(404, "找不到這個分頁")
    source = repo.get_tab_source(conn, slug, key) or {}
    if mode == "source":
        if not source.get("blob"):
            return _error(404, "沒有來源原檔")
        return 200, {"data": source["blob"], "content_type": source["mime"], "filename": source["filename"]}
    fmt = str(fmt or (source.get("metadata") or {}).get("format") or
              ("xlsx" if tab["surface_type"] == "sheet" else "md")).lower().lstrip(".")
    try:
        # Materialize interactive field values into exported text without changing
        # the stored document; read-only fields are otherwise invisible in exports.
        import copy
        doc = copy.deepcopy(tab["doc"])
        values = repo.field_values(conn, slug).get(key, {})
        def materialize(node):
            attrs = node.get("attrs", {})
            field = values.get(attrs.get("fid"))
            if field and node.get("type") in ("fill", "status"):
                node.clear()
                node.update({"type": "text", "text": str(field.get("value", ""))})
                return
            for child in node.get("content", []):
                materialize(child)
        materialize(doc)
        data = file_handoff.export_file(doc, fmt, source_blob=source.get("blob"),
                                         source_meta=source.get("metadata"), mode=mode)
    except file_handoff.HandoffError as exc:
        return _error(400, str(exc))
    filename = (source.get("filename") or tab["title"]).rsplit(".", 1)[0] + "." + fmt
    if mode == "new_workbook":
        filename = filename.rsplit(".", 1)[0] + "-整理版." + fmt
    return 200, {"data": data, "content_type": file_handoff.MIME[fmt], "filename": filename}


def revisions_payload(conn, me: Identity, slug: str, key: str):
    problem = _need_editor(me)
    if problem:
        return problem
    return 200, {"revisions": repo.list_revisions(conn, slug, key)}


def deleted_tabs_payload(conn, me: Identity, slug: str):
    problem = _need_editor(me)
    if problem:
        return problem
    return 200, {"tabs": repo.list_tabs(conn, slug, deleted=True)}


# ---------- 一塊一塊存 ----------

def _run_ops(conn, me: Identity, slug: str, key: str, tab: dict, ops, session_id: str, *, audit_extra=None, atomic=False, delivery_mode=None):
    """套 ops、存檔、記系統紀錄、標註重新對位（平常存檔和「改回」都走這裡）。
    回 (result, doc, revision, saved_at)；ops 格式不對丟 OpsError／DocError。"""

    result = blocks.apply_ops(tab["doc"], ops, blocks.Actor(me.actor_id, me.can_edit),
                              locks=repo.tab_locks(conn, slug, key), now=_now())
    if atomic and result.conflicts:
        return blocks.OpsResult(doc=tab["doc"], conflicts=result.conflicts), tab["doc"], tab["revision"], tab["updated_at"]
    for table in result.doc.get("content", []):
        if table.get("type") == "table" and "column_ids" in table.get("attrs", {}):
            width = max((len(row.get("content", [])) for row in table.get("content", [])), default=0)
            if len(table["attrs"]["column_ids"]) != width:
                raise DocError("欄位身分與資料寬度不符；請使用欄位選單調整結構")
    doc, _ = validate_doc(result.doc, slug=slug)
    from project_docs import file_handoff, table_schema
    table_schema.guard_schema_change(conn, slug, key, tab["doc"], doc)
    source = repo.get_tab_source(conn, slug, key) if tab.get("source_filename") else None
    if source and source.get("metadata", {}).get("format") == "xlsx":
        mode = delivery_mode or source["metadata"].get("delivery_mode", "original_patch")
        if mode not in ("original_patch", "new_workbook"):
            raise DocError("不支援的交付方式")
        if mode == "original_patch":
            try:
                file_handoff._xlsx_patch(doc, source["blob"], source["metadata"])
            except file_handoff.HandoffError as exc:
                raise DocError("此修改超出原檔可保留範圍，請明確選擇另存新工作簿再修改：" + str(exc)) from exc
    revision, saved_at = tab["revision"], tab["updated_at"]
    if result.applied and doc != tab["doc"]:
        saved = repo.save_tab_doc(conn, slug, key, doc=doc, title=tab["title"], actor_id=me.actor_id,
                                  session_id=session_id, base_revision=None)
        revision, saved_at = saved["revision"], saved["saved_at"]
        repo.add_audit(conn, slug, action="edit", actor_id=me.actor_id, tab_key=key,
                       detail={"revision": revision, "session": session_id,
                               "changes": doc_changes(tab["doc"], doc), **(audit_extra or {})})
        reanchor_tab(conn, slug, key, doc, actor_id=me.actor_id)
        if source and delivery_mode == "new_workbook":
            repo.set_tab_source(conn, slug, key, filename=source["filename"], mime=source["mime"], blob=source["blob"],
                                metadata={**source["metadata"], "delivery_mode": "new_workbook"}, surface_type=tab["surface_type"])
    else:
        doc = tab["doc"]
    return result, doc, revision, saved_at


def apply_tab_ops(conn, me: Identity, slug: str, key: str, body: dict):
    tab = repo.get_tab_for_update(conn, slug, key)
    if not tab:
        return _error(404, "找不到這個分頁")
    session_id = str(body.get("session_id") or "")[:64]
    try:
        result, doc, revision, saved_at = _run_ops(conn, me, slug, key, tab, body.get("ops"), session_id, atomic=bool(body.get("atomic")), delivery_mode=body.get("delivery_mode"))
    except (blocks.OpsError, DocError) as exc:
        return _error(400, str(exc))
    names = _names(conn)
    conflicts = [dict(c, owner_name=names.get(c.get("owner") or "", "")) for c in result.conflicts]
    return 200, {"revision": revision, "saved_at": saved_at, "doc": doc, "applied": result.applied,
                 "conflicts": conflicts, "annotations": repo.list_annotations(conn, slug)}


def reanchor_tab(conn, slug: str, key: str, doc: dict, *, actor_id=None) -> None:
    """內文存了以後：每一則標註重新找位置。找到就更新；字變了記下來（已確認的要重新確認）；
    找不到的進「原文已修改」，只有螢光筆／劃線的直接拿掉；整列對話看那一列還在不在。
    有標註因此被拿掉、找不到或換了字，記一筆系統紀錄，算在改內文的人（actor_id）頭上。"""

    text = doc_text(doc)
    rows = table_row_ids(doc)
    now = _now()
    effects = {"removed": [], "orphaned": [], "moved": [], "reconfirm": [], "rows_gone": [], "rows_back": []}
    for ann in repo.annotations_for_anchoring(conn, slug, key):
        if ann["kind"] == "row":
            gone = ann["anchor"].get("rid") not in rows
            if gone != bool(ann["orphaned_at"]):
                repo.set_orphaned(conn, ann["id"], gone)
                effects["rows_gone" if gone else "rows_back"].append({"id": ann["id"], "row": ann["anchor"].get("rid")})
            continue
        if ann["orphaned_at"]:
            continue
        old = ann["anchor"]["quote"]
        found = anchoring.resolve(text, ann["anchor"])
        if not found:
            if not ann["label"] and not ann["has_comments"]:
                repo.delete_annotation(conn, ann["id"])
                effects["removed"].append({"id": ann["id"], "quote": old, "style": ann["style"]})
            else:
                repo.set_orphaned(conn, ann["id"], True)
                effects["orphaned"].append({"id": ann["id"], "quote": old, "label": ann["label"]})
            continue
        start, end, _ = found
        quote = text[start:end]
        anchor = anchoring.anchor_at(text, start, quote)
        if anchor == ann["anchor"]:
            continue
        if quote == old:
            repo.update_anchor(conn, ann["id"], anchor)
        elif ann["label"] == "ok" and not ann["resolved_at"]:
            first = (ann["reconfirm"] or {}).get("from") or old
            repo.update_anchor(conn, ann["id"], anchor, reconfirm={"from": first, "to": quote, "at": now})
            effects["reconfirm"].append({"id": ann["id"], "from": old, "to": quote})
        else:
            first = (ann["moved"] or {}).get("from") or old
            repo.update_anchor(conn, ann["id"], anchor, moved={"from": first, "to": quote, "at": now})
            effects["moved"].append({"id": ann["id"], "from": old, "to": quote})
    effects = {name: items for name, items in effects.items() if items}
    if effects:
        repo.add_audit(conn, slug, action="annotations_reanchored", actor_id=actor_id, tab_key=key, detail=effects)


# ---------- 修改紀錄與改回（10/15 起大家一起編輯：名單上的人都看得到、都能改回） ----------

def history_payload(conn, me: Identity, slug: str, key=None):
    """誰在什麼時候改了哪幾處（新的在前）。key＝這一頁；None＝全部分頁。刪掉的分頁不列。"""

    _, problem = _project_or_404(conn, slug)
    if problem:
        return problem
    titles = {t["key"]: t["title"] for t in repo.list_tabs(conn, slug)}
    if key is not None and key not in titles:
        return _error(404, "找不到這個分頁")
    revisions = [r for r in repo.revision_rows(conn, slug, tab_key=key) if r["tab_key"] in titles]
    fields = [a for a in repo.activity_rows(conn, slug, tab_key=key)
              if a["kind"] != "comment" and a["field_id"] and a["tab_key"] in titles]
    starts = {}  # 每一筆版本第一次存的時間（系統紀錄有記；10/14 以前的沒有，用最後存的時間）
    for row in repo.audit_rows(conn, slug, tab_key=key):
        number = row["detail"].get("revision") if row["action"] == "edit" else None
        if number:
            at = (row["tab_key"], number)
            starts[at] = min(starts.get(at, row["at"]), row["at"])
    latest = {r["tab_key"]: r["doc"] for r in revisions}  # 照分頁、版本號排，最後一筆＝現在的內容
    row_labels = {tab_key: index_doc(document)[1] for tab_key, document in latest.items()}
    groups = page_history.build_groups(revisions, fields, repo.member_names(conn), starts=starts, titles=titles,
                                       row_labels=row_labels)
    limit = HISTORY_LIMIT if key is not None else HISTORY_LIMIT_ALL
    return 200, {"groups": groups[:limit], "more": len(groups) > limit}


def _later_people(conn, edits) -> list[dict]:
    names, out = repo.member_names(conn), {}
    for edit in edits:
        actor = edit["actor_id"] or ""
        out[actor] = {"name": names.get(actor) or "系統", "at": repo._iso(edit["at"])}
    return list(out.values())


def revert_change(conn, me: Identity, slug: str, key: str, body: dict):
    """改回修改紀錄裡的一處：一段、表格的一列，或一格狀態／可填格／勾選。名單上的人都可以（跟改字同一種權限）。

    之後又有人改過那一處：先回 409（誰改過、改回後會變成什麼），畫面問過再帶 force 送一次。
    改回本身存成新的一筆（session revert-…），在修改紀錄裡也能再改回來。
    """

    body = body if isinstance(body, dict) else {}
    force = body.get("force") is True
    if body.get("field_id") is not None:
        return _revert_field(conn, me, slug, key, body, force)
    bid, rid = body.get("bid"), body.get("rid")
    if (not isinstance(bid, str) or not ID_RE.match(bid)
            or (rid is not None and (not isinstance(rid, str) or not ID_RE.match(rid)))):
        return _error(400, "缺少要改回的段落")
    try:
        from_rev, to_rev = int(body.get("from_rev")), int(body.get("to_rev"))
    except (TypeError, ValueError):
        return _error(400, "缺少要改回的是哪一次")
    tab = repo.get_tab_for_update(conn, slug, key)
    if not tab:
        return _error(404, "找不到這個分頁")
    before, after = repo.get_revision(conn, slug, key, from_rev), repo.get_revision(conn, slug, key, to_rev)
    if not before or not after or from_rev >= to_rev:
        return _error(404, "找不到那一次的紀錄，請重新整理")
    plan = page_history.revert_plan(before["doc"], after["doc"], tab["doc"], bid, rid)
    what = "這一列" if rid else "這一段"
    if plan["state"] == "gone":
        return _error(409, "這個表格已經不在頁面上了，沒辦法只改回一列")
    if plan["state"] == "already":
        return 200, {"already": True, "revision": tab["revision"], "saved_at": tab["updated_at"], "doc": tab["doc"],
                     "annotations": repo.list_annotations(conn, slug)}
    if plan["state"] == "later" and not force:
        later = [r for r in repo.revision_rows(conn, slug, tab_key=key) if r["revision"] > to_rev]
        edits = page_history.later_edits(later, bid, rid, page_history.locate(after["doc"], bid, rid))
        return 409, {"error": f"{what}之後又有人改過", "code": "changed_later", "later": _later_people(conn, edits),
                     "preview": plan["preview"]}
    try:
        result, doc, revision, saved_at = _run_ops(
            conn, me, slug, key, tab, plan["ops"], "revert-" + secrets.token_hex(6),
            audit_extra={"via": "revert", "from_revision": from_rev, "to_revision": to_rev, "unit": rid or bid})
    except (blocks.OpsError, DocError) as exc:
        return _error(400, str(exc))
    if not result.applied:
        conflict = result.conflicts[0] if result.conflicts else {}
        if conflict.get("reason") == "locked":
            return _error(409, f"{_names(conn).get(conflict.get('owner'), '別人')}正在改{what}，等改完再改回")
        if conflict.get("reason") == "shape":
            return _error(409, "這個表格的欄數改過了，沒辦法只改回一列")
        return _error(409, f"{what}剛被改過，請重新整理再試")
    return 200, {"revision": revision, "saved_at": saved_at, "doc": doc, "annotations": repo.list_annotations(conn, slug)}


def _revert_field(conn, me: Identity, slug: str, key: str, body: dict, force: bool):
    field_id = str(body.get("field_id") or "")
    try:
        after_activity = int(body.get("after_activity") or 0)
    except (TypeError, ValueError):
        return _error(400, "缺少要改回的是哪一次")
    tab = repo.get_tab(conn, slug, key)
    field = index_doc(tab["doc"])[0].get(field_id) if tab else None
    if not field:
        return _error(404, "這一格已經不在頁面上，請重新整理")
    raw = body.get("value")
    wanted = ("true" if raw in (True, "true") else "false") if field["kind"] == "check" else str(raw if raw is not None else "").strip()
    current = repo.get_field_value(conn, slug, key, field_id)
    if (current if current is not None else field["default"]) == wanted:
        return 200, {"already": True, "value": repo.field_values(conn, slug).get(key, {}).get(field_id)}
    edits = [a for a in repo.activity_rows(conn, slug, tab_key=key)
             if a["kind"] != "comment" and a["field_id"] == field_id and a["id"] > after_activity]
    if edits and not force:
        return 409, {"error": "這一格之後又有人改過", "code": "changed_later", "later": _later_people(conn, edits),
                     "preview": str(body.get("value") if body.get("value") is not None else "")}
    status, payload = set_field(conn, me, slug, {"tab_key": key, "field_id": field_id, "value": body.get("value")})
    if status == 200 and not payload.get("activity"):
        payload["already"] = True
    return status, payload


# ---------- 分頁（管理者） ----------

def _clean_title(value, fallback=None):
    title = str(value if value is not None else (fallback or "")).strip()
    if not 1 <= len(title) <= 200:
        return None
    return title


def _display_order(tabs: list[dict]) -> list[dict]:
    tops = [t for t in tabs if not t["parent_key"]]
    keys = {t["key"] for t in tabs}
    ordered = []
    for top in tops:
        ordered.append(top)
        ordered.extend(t for t in tabs if t["parent_key"] == top["key"])
    ordered.extend(t for t in tabs if t["parent_key"] and t["parent_key"] not in keys)
    return ordered


def _valid_parent(tabs, key, parent_key):
    if parent_key in (None, ""):
        return None, True
    parent = next((t for t in tabs if t["key"] == parent_key), None)
    if not parent or parent["parent_key"] or parent_key == key:
        return None, False
    return parent_key, True


def create_tab(conn, me: Identity, slug: str, body: dict):
    if not repo.get_project(conn, slug):
        return _error(404, "找不到這個專案")
    title = _clean_title(body.get("title"))
    if title is None:
        return _error(400, "分頁名稱要 1～200 個字")
    tabs = repo.list_tabs(conn, slug)
    parent_key, ok = _valid_parent(tabs, None, body.get("parent_key"))
    if not ok:
        return _error(400, "子分頁只能放在第一層分頁底下")
    key = "t-" + secrets.token_hex(3)
    while repo.get_tab(conn, slug, key, include_deleted=True):
        key = "t-" + secrets.token_hex(3)
    owner = {} if me.can_edit else {"owner": me.actor_id, "created": _now()}
    surface_type = str(body.get("surface_type") or "doc").strip()
    if surface_type not in repo.SURFACE_TYPES:
        surface_type = "doc"
    if surface_type == "sheet":
        from project_docs import markdown_import
        md = (
            f"# {title}\n\n"
            "| 日期 | 渠道／項目 | 花費 | 營收 | ROAS | 狀態 | 請填備註 |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
            "| 10/16 | Meta | 12000 | 18600 | =D1/C1 | {{s:進行中}} | 首日測試數據 |\n"
            "| 10/17 | Google | 8500 | 11900 | =D2/C2 | {{s:未開始}} | 待填寫 |\n"
        )
        raw_doc, _ = markdown_import.markdown_to_doc(md, tab_keys=set(), image_src=lambda _: None)
        doc, _ = validate_doc(raw_doc, slug=slug)
    elif surface_type == "flow":
        from project_docs import markdown_import
        md = (
            f"# {title}\n\n"
            "| 節點名稱 | 負責代理／角色 | 觸發與輸入 → 輸出 | 狀態 | 請填設定 |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| 1. 讀取日報資料 | 🤖 OpenAI · GPT-5.4 | 讀取 daily-sheet 最新數據列 | {{s:已完成}} | 自動掃描今日新增列 |\n"
            "| 2. 異常診斷與歸因 | ✨ Google · Gemini 2.5 Pro | 比對 ROAS 門檻並標記異常原因 | {{s:進行中}} | ROAS < 1.2 時觸發告警 |\n"
            "| 3. 產出修訂提案卡 | 🔌 OpenAB · 遠端代理手腳 (Limb) | 寫回 overview 總覽分頁 | {{s:未開始}} | 產生 ProposalCard 供主管確認 |\n"
        )
        raw_doc, _ = markdown_import.markdown_to_doc(md, tab_keys=set(), image_src=lambda _: None)
        doc, _ = validate_doc(raw_doc, slug=slug)
    else:
        doc, _ = validate_doc({"type": "doc", "content": [
            {"type": "heading", "attrs": {"level": 1, "bid": new_id("b"), **owner}, "content": [{"type": "text", "text": title}]},
            {"type": "paragraph", "attrs": {"bid": new_id("b"), **owner}},
        ]}, slug=slug)
    repo.create_tab(conn, slug, key=key, title=title, parent_key=parent_key, doc=doc,
                    actor_id=me.actor_id, surface_type=surface_type)
    ordered = _display_order(repo.list_tabs(conn, slug))
    repo.normalize_positions(conn, slug, [t["key"] for t in ordered])
    repo.add_audit(conn, slug, action="tab_create", actor_id=me.actor_id, tab_key=key,
                   detail={"title": title, "parent_key": parent_key, "surface_type": surface_type})
    return 200, {"tab": repo.get_tab(conn, slug, key), "tabs": repo.list_tabs(conn, slug)}


def update_tab(conn, me: Identity, slug: str, key: str, body: dict):
    tabs = repo.list_tabs(conn, slug)
    tab = next((t for t in tabs if t["key"] == key), None)
    if not tab:
        return _error(404, "找不到這個分頁")
    problem = _need_tab_manager(me, tab)
    if problem:
        return problem
    changed = {}
    if "title" in body:
        title = _clean_title(body.get("title"))
        if title is None:
            return _error(400, "分頁名稱要 1～200 個字")
        repo.update_tab_meta(conn, slug, key, title=title)
        if title != tab["title"]:
            changed["title"] = [tab["title"], title]
        tab["title"] = title
    if "parent_key" in body:
        has_children = any(t["parent_key"] == key for t in tabs)
        parent_key, ok = _valid_parent(tabs, key, body.get("parent_key"))
        if not ok or (parent_key and has_children):
            return _error(400, "子分頁只能放在第一層分頁底下，而且底下不能再有子分頁")
        repo.update_tab_meta(conn, slug, key, parent_key=parent_key)
        if parent_key != tab["parent_key"]:
            changed["parent_key"] = [tab["parent_key"], parent_key]
        tab["parent_key"] = parent_key
        # 換到別的父分頁：排到那一組的最後
        others = [t for t in tabs if t["key"] != key]
        tabs = others + [tab]
    ordered = _display_order(tabs)
    move = body.get("move")
    if move in ("up", "down"):
        siblings = [t for t in ordered if t["parent_key"] == tab["parent_key"]]
        index = siblings.index(tab)
        target = index - 1 if move == "up" else index + 1
        if 0 <= target < len(siblings):
            siblings[index], siblings[target] = siblings[target], siblings[index]
            changed["move"] = move
            if tab["parent_key"]:
                rest = [t for t in tabs if t["parent_key"] != tab["parent_key"]]
                ordered = _display_order(rest + siblings)
            else:
                children = [t for t in tabs if t["parent_key"]]
                ordered = _display_order(siblings + children)
    repo.normalize_positions(conn, slug, [t["key"] for t in ordered])
    if changed:
        repo.add_audit(conn, slug, action="tab_update", actor_id=me.actor_id, tab_key=key, detail=changed)
    if "title" in changed:
        _rename_heading(conn, me, slug, key, *changed["title"])
    return 200, {"tabs": repo.list_tabs(conn, slug)}


def _rename_heading(conn, me: Identity, slug: str, key: str, old: str, new: str) -> None:
    """改名時，第一行的大標題還是舊名稱就跟著改（以前在畫面上改，現在從左邊清單改哪一頁都可以）。
    大標題被改成別的字、或有人正在改它，就不動。"""
    tab = repo.get_tab_for_update(conn, slug, key)
    first = (tab["doc"].get("content") or [None])[0] if tab else None
    if not first or first.get("type") != "heading" or (first.get("attrs") or {}).get("level") != 1 or node_text(first) != old:
        return
    holder = repo.tab_locks(conn, slug, key).get((first.get("attrs") or {}).get("bid"))
    if holder and holder != me.actor_id:
        return
    doc = dict(tab["doc"], content=[dict(first, content=[{"type": "text", "text": new}]), *tab["doc"]["content"][1:]])
    doc, _ = validate_doc(doc, slug=slug)
    saved = repo.save_tab_doc(conn, slug, key, doc=doc, title=new, actor_id=me.actor_id,
                              session_id="rename-" + secrets.token_hex(6), base_revision=None)
    repo.add_audit(conn, slug, action="edit", actor_id=me.actor_id, tab_key=key,
                   detail={"revision": saved["revision"], "session": "rename", "changes": doc_changes(tab["doc"], doc)})
    reanchor_tab(conn, slug, key, doc, actor_id=me.actor_id)


def delete_tab(conn, me: Identity, slug: str, key: str):
    tabs = repo.list_tabs(conn, slug)
    tab = next((t for t in tabs if t["key"] == key), None)
    if not tab:
        return _error(404, "找不到這個分頁")
    problem = _need_tab_manager(me, tab)
    if problem:
        return problem
    if len(tabs) == 1:
        return _error(400, "至少要留一個分頁")
    children = [t["key"] for t in tabs if t["parent_key"] == key]
    for child in children:
        repo.update_tab_meta(conn, slug, child, parent_key=None)
    repo.set_tab_deleted(conn, slug, key, True)
    ordered = _display_order(repo.list_tabs(conn, slug))
    repo.normalize_positions(conn, slug, [t["key"] for t in ordered])
    repo.add_audit(conn, slug, action="tab_delete", actor_id=me.actor_id, tab_key=key,
                   detail={"title": tab["title"], "children_moved_up": children})
    return 200, {"tabs": repo.list_tabs(conn, slug)}


def restore_tab(conn, me: Identity, slug: str, key: str):
    problem = _need_editor(me)
    if problem:
        return problem
    deleted = repo.list_tabs(conn, slug, deleted=True)
    tab = next((t for t in deleted if t["key"] == key), None)
    if not tab:
        return _error(404, "找不到這個已刪除的分頁")
    alive = {t["key"]: t for t in repo.list_tabs(conn, slug)}
    parent = alive.get(tab["parent_key"])
    if tab["parent_key"] and (not parent or parent["parent_key"]):
        repo.update_tab_meta(conn, slug, key, parent_key=None)
    repo.set_tab_deleted(conn, slug, key, False)
    ordered = _display_order(repo.list_tabs(conn, slug))
    repo.normalize_positions(conn, slug, [t["key"] for t in ordered])
    repo.add_audit(conn, slug, action="tab_restore", actor_id=me.actor_id, tab_key=key, detail={"title": tab["title"]})
    return 200, {"tabs": repo.list_tabs(conn, slug)}


def restore_revision(conn, me: Identity, slug: str, key: str, revision: int):
    problem = _need_editor(me)
    if problem:
        return problem
    old = repo.get_revision(conn, slug, key, revision)
    if not old:
        return _error(404, "找不到這個版本")
    tab = repo.get_tab(conn, slug, key)
    if not tab:
        return _error(404, "找不到這個分頁")
    doc, _ = validate_doc(old["doc"], slug=slug)
    result = repo.save_tab_doc(conn, slug, key, doc=doc, title=old["title"], actor_id=me.actor_id,
                               session_id="restore-" + secrets.token_hex(6), base_revision=tab["revision"])
    if not result.get("unchanged"):
        repo.add_audit(conn, slug, action="revision_restore", actor_id=me.actor_id, tab_key=key,
                       detail={"from_revision": revision, "replaced_revision": tab["revision"],
                               "new_revision": result["revision"], "changes": doc_changes(tab["doc"], doc)})
    reanchor_tab(conn, slug, key, doc, actor_id=me.actor_id)
    result["doc"] = doc
    result["title"] = old["title"]
    result["annotations"] = repo.list_annotations(conn, slug)
    return 200, result


# ---------- 狀態、可填格、勾選（名單上的人都可以） ----------

def set_field(conn, me: Identity, slug: str, body: dict):
    tab_key = str(body.get("tab_key") or "")
    field_id = str(body.get("field_id") or "")
    tab = repo.get_tab_for_update(conn, slug, tab_key) if TAB_KEY_RE.match(tab_key) else None
    if not tab:
        return _error(404, "找不到這個分頁")
    fields, _ = index_doc(tab["doc"])
    field = fields.get(field_id)
    if not field:
        return _error(404, "這一格已經不在頁面上，請重新整理")
    locks = repo.tab_locks(conn, slug, tab_key)
    ancestors = [field["anchor_id"]]
    for node in tab["doc"].get("content", []):
        if any(r.get("attrs", {}).get("bid") == field["anchor_id"] for r in node.get("content", [])):
            ancestors.append(node.get("attrs", {}).get("bid"))
    if any(locks.get(unit) and locks[unit] != me.actor_id for unit in ancestors):
        return _error(409, "這一格正由其他成員編輯")
    raw = body.get("value")
    if "expected_value" in body:
        existing = repo.field_values(conn, slug).get(tab_key, {}).get(field_id)
        current = existing.get("value", "") if isinstance(existing, dict) else field["default"]
        if body["expected_value"] != current:
            return 409, {"error": "這一格已被修改，草稿尚未套用", "before": body["expected_value"], "mine": raw, "current": current}
    if field["kind"] == "status":
        if raw not in STATUSES:
            return _error(400, "狀態只能是：" + "、".join(STATUSES))
        value = raw
    elif field["kind"] == "fill":
        value = str(raw if raw is not None else "").strip()
        if len(value) > MAX_FILL:
            return _error(400, f"這一格最多 {MAX_FILL} 個字")
    else:
        value = "true" if raw in (True, "true") else "false"
    old = repo.set_field_value(conn, slug, tab_key, field_id, kind=field["kind"], value=value,
                               actor_id=me.actor_id)
    before = old if old is not None else field["default"]
    activity = None
    if before != value:
        repo.save_tab_doc(conn, slug, tab_key, doc=tab["doc"], title=tab["title"], actor_id=me.actor_id,
                          session_id="field-" + secrets.token_hex(8), base_revision=None, force_revision=True)
        annotation_id = None
        if field["anchor_id"] in table_row_ids(tab["doc"]):
            annotation_id = repo.row_annotation_id(conn, slug, tab_key, field["anchor_id"], me.actor_id)
        activity_id = repo.add_activity(
            conn, slug, tab_key, field["anchor_id"], kind=field["kind"], actor_id=me.actor_id,
            field_id=field_id, field_label=field["label"], old_value=before, new_value=value,
            annotation_id=annotation_id,
        )
        activity = repo.get_activity(conn, slug, activity_id)
    current = repo.field_values(conn, slug).get(tab_key, {}).get(field_id)
    return 200, {"value": current, "activity": activity}


# ---------- 標註 ----------

def _comment_body(conn, raw):
    text = str(raw or "").strip()
    if not text:
        return None, _error(400, "留言是空的")
    if len(text) > MAX_COMMENT:
        return None, _error(400, f"留言最多 {MAX_COMMENT} 個字")
    members = {m["actor_id"] for m in repo.active_members(conn)}
    mentions = []
    for actor_id in MENTION_RE.findall(text):
        if actor_id not in members:
            return None, _error(400, "@ 的人不在名單上")
        if actor_id not in mentions:
            mentions.append(actor_id)
    if "@{" in MENTION_RE.sub("", text):
        return None, _error(400, "@ 的格式不對，請從名單選人")
    return (text, mentions), None


def _one(conn, slug, annotation_id):
    items = repo.list_annotations(conn, slug, annotation_id=annotation_id)
    return items[0] if items else None


def _annotation_or_404(conn, slug, annotation_id):
    ann = _one(conn, slug, annotation_id)
    return ann, (None if ann else _error(404, "找不到這則標註（可能已經被刪了）"))


def _mentioned(ann) -> set:
    return {actor for m in ann["messages"] if m["kind"] == "comment" for actor in m.get("mentions") or []}


def _thread_anchor(ann) -> str:
    return ann["anchor"]["rid"] if ann["kind"] == "row" else f"ann{ann['id']}"


def create_annotation(conn, me: Identity, slug: str, body: dict):
    tab_key = str(body.get("tab_key") or "")
    tab = repo.get_tab(conn, slug, tab_key) if TAB_KEY_RE.match(tab_key) else None
    if not tab:
        return _error(404, "找不到這個分頁")
    comment = None
    if str(body.get("body") or "").strip():
        comment, problem = _comment_body(conn, body.get("body"))
        if problem:
            return problem
    rid = body.get("row")
    if rid is not None:
        if not isinstance(rid, str) or rid not in table_row_ids(tab["doc"]):
            return _error(404, "這一列已經不在頁面上，請重新整理")
        if not comment:
            return _error(400, "留言是空的")
        annotation_id = repo.row_annotation_id(conn, slug, tab_key, rid, me.actor_id)
        comment_id=repo.add_activity(conn, slug, tab_key, rid, kind="comment", actor_id=me.actor_id, body=comment[0],
                          mentions=comment[1], annotation_id=annotation_id)
        return 200, {"annotation": _one(conn, slug, annotation_id),'comment_id':comment_id}
    anchor = anchoring.clean_anchor(body.get("anchor"))
    if not anchor:
        return _error(400, "選取的字不對，請重新選一次")
    style, color, label = body.get("style"), body.get("color"), body.get("label")
    if style is not None and style not in STYLES:
        return _error(400, "螢光筆或劃線的種類不對")
    if style == "hl" and color not in COLORS:
        return _error(400, "螢光筆的顏色不對")
    if style != "hl":
        color = None
    if label is not None and label not in LABELS:
        return _error(400, "標註只能是：問題、要修改、已確認")
    if not (style or label or comment):
        return _error(400, "要畫螢光筆、劃線、標註或寫說明")
    text = doc_text(tab["doc"])
    found = anchoring.resolve(text, anchor)
    if not found:
        return _error(409, "原文已經變了，請重新選一次")
    start, end, _ = found
    anchor = anchoring.anchor_at(text, start, text[start:end])
    annotation_id = repo.create_annotation(conn, slug, tab_key, kind="text", anchor=anchor, actor_id=me.actor_id,
                                           style=style, color=color, label=label)
    comment_id=None
    if comment:
        comment_id=repo.add_activity(conn, slug, tab_key, f"ann{annotation_id}", kind="comment", actor_id=me.actor_id,
                          body=comment[0], mentions=comment[1], annotation_id=annotation_id)
    return 200, {"annotation": _one(conn, slug, annotation_id),'comment_id':comment_id}


def comment_annotation(conn, me: Identity, slug: str, annotation_id: int, body: dict):
    ann, problem = _annotation_or_404(conn, slug, annotation_id)
    if problem:
        return problem
    comment, problem = _comment_body(conn, body.get("body"))
    if problem:
        return problem
    comment_id=repo.add_activity(conn, slug, ann["tab_key"], _thread_anchor(ann), kind="comment", actor_id=me.actor_id,
                      body=comment[0], mentions=comment[1], annotation_id=annotation_id)
    return 200, {"annotation": _one(conn, slug, annotation_id),'comment_id':comment_id}


def resolve_annotation(conn, me: Identity, slug: str, annotation_id: int, body: dict):
    ann, problem = _annotation_or_404(conn, slug, annotation_id)
    if problem:
        return problem
    if not (me.can_edit or ann["created_by"] == me.actor_id or me.actor_id in _mentioned(ann)):
        return _error(403, "只有標的人、被 @ 的人或管理者能按「解決」")
    resolved = bool(body.get("resolved", True))
    repo.set_resolved(conn, annotation_id, me.actor_id if resolved else None)
    if resolved != bool(ann["resolved_at"]) or (resolved and ann["resolved_by"] != me.actor_id):
        repo.add_audit(conn, slug, action="annotation_resolve" if resolved else "annotation_reopen",
                       actor_id=me.actor_id, tab_key=ann["tab_key"], target=annotation_id, detail=_ann_summary(ann))
    return 200, {"annotation": _one(conn, slug, annotation_id)}


def _ann_summary(ann) -> dict:
    """系統紀錄裡描述一則標註：標的人、哪段字（或哪一列）、樣式、標籤、幾則留言。"""

    summary = {"kind": ann["kind"], "created_by": ann["created_by"], "created_by_name": ann.get("created_by_name"),
               "style": ann.get("style"), "color": ann.get("color"), "label": ann.get("label"),
               "comments": sum(1 for m in ann.get("messages") or [] if m["kind"] == "comment")}
    if ann["kind"] == "row":
        summary["row"] = ann["anchor"].get("rid")
    else:
        summary["quote"] = ann["anchor"].get("quote")
    return summary


def reconfirm_annotation(conn, me: Identity, slug: str, annotation_id: int):
    ann, problem = _annotation_or_404(conn, slug, annotation_id)
    if problem:
        return problem
    if ann["label"] != "ok" or not ann["reconfirm"]:
        return _error(400, "這則不需要重新確認")
    repo.confirm_label(conn, annotation_id, me.actor_id)
    repo.add_audit(conn, slug, action="annotation_reconfirm", actor_id=me.actor_id, tab_key=ann["tab_key"],
                   target=annotation_id, detail=dict(_ann_summary(ann), reconfirm=ann["reconfirm"]))
    return 200, {"annotation": _one(conn, slug, annotation_id)}


def reattach_annotation(conn, me: Identity, slug: str, annotation_id: int, body: dict):
    ann, problem = _annotation_or_404(conn, slug, annotation_id)
    if problem:
        return problem
    if ann["kind"] != "text":
        return _error(400, "整列的對話不能換位置")
    if not (me.can_edit or ann["created_by"] == me.actor_id):
        return _error(403, "只有標的人或管理者能換位置")
    anchor = anchoring.clean_anchor(body.get("anchor"))
    if not anchor:
        return _error(400, "選取的字不對，請重新選一次")
    tab = repo.get_tab(conn, slug, ann["tab_key"])
    text = doc_text(tab["doc"]) if tab else ""
    found = anchoring.resolve(text, anchor)
    if not found:
        return _error(409, "原文已經變了，請重新選一次")
    start, end, _ = found
    quote = text[start:end]
    repo.reattach(conn, annotation_id, anchoring.anchor_at(text, start, quote))
    repo.add_audit(conn, slug, action="annotation_reattach", actor_id=me.actor_id, tab_key=ann["tab_key"],
                   target=annotation_id, detail={"from": ann["anchor"].get("quote"), "to": quote,
                                                 "was_orphaned": bool(ann["orphaned_at"])})
    return 200, {"annotation": _one(conn, slug, annotation_id)}


def style_annotation(conn, me: Identity, slug: str, annotation_id: int, body: dict):
    ann, problem = _annotation_or_404(conn, slug, annotation_id)
    if problem:
        return problem
    if ann["created_by"] != me.actor_id:
        return _error(403, "只能改自己畫的螢光筆或劃線")
    style, color = body.get("style"), body.get("color")
    if style not in STYLES or (style == "hl" and color not in COLORS):
        return _error(400, "螢光筆或劃線的種類不對")
    color = color if style == "hl" else None
    repo.set_style(conn, annotation_id, style, color)
    if (style, color) != (ann["style"], ann["color"]):
        repo.add_audit(conn, slug, action="annotation_style", actor_id=me.actor_id, tab_key=ann["tab_key"],
                       target=annotation_id, detail={"quote": ann["anchor"].get("quote"),
                                                     "from": [ann["style"], ann["color"]], "to": [style, color]})
    return 200, {"annotation": _one(conn, slug, annotation_id)}


def delete_annotation(conn, me: Identity, slug: str, annotation_id: int):
    ann, problem = _annotation_or_404(conn, slug, annotation_id)
    if problem:
        return problem
    if not (me.can_edit or ann["created_by"] == me.actor_id):
        return _error(403, "只有標的人或管理者能刪除")
    repo.delete_annotation(conn, annotation_id)
    repo.add_audit(conn, slug, action="annotation_delete", actor_id=me.actor_id, tab_key=ann["tab_key"],
                   target=annotation_id, detail=_ann_summary(ann))
    return 200, {"deleted": True}


def remove_comment(conn, me: Identity, slug: str, comment_id: int):
    comment = repo.get_activity(conn, slug, comment_id)
    if repo.delete_comment(conn, slug, comment_id, me.actor_id):
        repo.add_audit(conn, slug, action="comment_delete", actor_id=me.actor_id,
                       tab_key=(comment or {}).get("tab_key"), target=comment_id,
                       detail={"annotation_id": (comment or {}).get("annotation_id"),
                               "body": (comment or {}).get("body")})
        return 200, {"deleted": True}
    return _error(403, "只能刪自己的留言")


# ---------- 編輯鎖 ----------

def lock_unit(conn, me: Identity, slug: str, body: dict):
    tab_key, unit = str(body.get("tab_key") or ""), str(body.get("unit") or "")
    if not TAB_KEY_RE.match(tab_key) or not ID_RE.match(unit):
        return _error(400, "缺少分頁或段落")
    if not repo.get_tab_for_update(conn, slug, tab_key):
        return _error(404, "找不到這個分頁")
    if body.get("release"):
        repo.release_lock(conn, slug, tab_key, unit, me.actor_id)
        return 200, {"held": False}
    holder = repo.take_lock(conn, slug, tab_key, unit, me.actor_id, LOCK_SECONDS)
    if holder == me.actor_id:
        return 200, {"held": True}
    return 200, {"held": False, "by": holder, "by_name": _names(conn).get(holder, "別人")}


# ---------- 圖片 ----------

def upload_asset(conn, me: Identity, slug: str, data: bytes, content_type: str):
    """名單上的人都能貼圖（10/15 起大家一起編輯）。"""
    if not repo.get_project(conn, slug):
        return _error(404, "找不到這個專案")
    from project_docs import media
    try:
        content_type = media.validate(data, content_type)
    except media.MediaError as exc:
        return _error(exc.status, str(exc))
    asset_id = repo.put_asset(conn, slug, data=data, content_type=content_type, actor_id=me.actor_id)
    return 200, {"asset_id": asset_id, "src": f"/projects/api/{slug}/assets/{asset_id}", "content_type": content_type}
