"""/projects/ 的路由：頁面、前端資產、API。

server.py 的 do_GET／do_POST 只呼叫 handle_projects(handler, parsed, method)。handler 需要：
project_docs_identity()、send_json()、send_skillops_bytes()、read_json_body()、headers、rfile。
"""
from __future__ import annotations

import html
import re
import threading
from urllib.parse import parse_qs, quote, unquote
from openbench_data import resource_path

from project_assistant import service as assistant_service
from project_docs import repository as repo
from project_docs import service, members, media

STATIC_DIR = resource_path("static", "projects")
SLUG = r"([a-z0-9][a-z0-9-]{0,40})"
KEY = r"([a-z0-9][a-z0-9-]{0,40})"
MAX_JSON_BODY = 3 * 1024 * 1024
MAX_UPLOAD_BODY = media.MAX_BYTES
STATIC_TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2"}

_SCHEMA_READY = False
_SCHEMA_LOCK = threading.Lock()
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_HOST = re.compile(r"^[A-Za-z0-9.-]{1,200}(:\d{1,5})?$")


def _public_base(handler, slug: str):
    """Word 檔裡的站內連結要指回專案頁：用這個請求的網址當基準。"""

    host = (handler.headers.get("Host") or "").strip()
    if not _HOST.match(host):
        return None
    local = host.split(":")[0] in ("localhost", "127.0.0.1")
    return f"{'http' if local else 'https'}://{host}/projects/{slug}/"


def _attachment(slug: str, filename: str) -> str:
    suffix = re.sub(r"[^A-Za-z0-9._-]", "_", filename.rsplit('_', 1)[-1])
    fallback = f"{slug}_{suffix}"  # RFC 5987 carries the original UTF-8 name below.
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"


_CONN_FACTORY = None


def set_connection_factory(factory) -> None:
    global _CONN_FACTORY
    _CONN_FACTORY = factory


def open_connection():
    if _CONN_FACTORY is not None:
        return _CONN_FACTORY()
    import os
    import psycopg
    uri = os.environ.get("OPENBENCH_DB_URI") or os.environ.get("DATABASE_URL")
    if uri:
        return psycopg.connect(uri, autocommit=False)
    return psycopg.connect(
        host=os.environ.get("OPENBENCH_DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("OPENBENCH_DB_PORT", "5432")),
        dbname=os.environ.get("OPENBENCH_DB_NAME", "openbench"),
        user=os.environ.get("OPENBENCH_DB_USER", "postgres"),
        password=os.environ.get("OPENBENCH_DB_PASSWORD", "postgres"),
        autocommit=False,
    )


def _ensure_schema(conn) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        repo.ensure_schema(conn)
        conn.commit()
        _SCHEMA_READY = True


# ---------- 回應 ----------

def _redirect(handler, location: str) -> None:
    handler.send_response(302)
    handler.send_header("Location", location)
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", "0")
    handler.end_headers()


PROBLEM_PAGES = {
    "login": (401, "請先登入", "請先登入工作台帳號後再打開這個網址。"),
    "membership": (403, "還沒開放給你", "這裡只開放給專案名單上的成員。你的帳號還沒加入名單，請聯絡專案管理員。"),
    "unavailable": (503, "暫時無法確認身分", "登入驗證暫時連不上，請稍後重新整理。"),
}


def _problem_page(handler, problem: str, identity=None) -> None:
    status, title, message = PROBLEM_PAGES[problem]
    email = html.escape(str((identity or {}).get("email") or ""))
    who = f"<p class=who>目前登入：{email}</p>" if email else ""
    body = (
        "<!doctype html><html lang=zh-Hant><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{title}</title><style>body{{font-family:'Noto Sans TC','Microsoft JhengHei',sans-serif;"
        "color:#34332f;background:#fff;margin:0;display:flex;min-height:100vh;align-items:center;justify-content:center}"
        "main{max-width:460px;padding:24px}h1{font-size:22px;color:#1f1e1c}p{line-height:1.7}.who{color:#74726b;font-size:14px}"
        f"</style><main><h1>{title}</h1><p>{message}</p>{who}<a href='/login'>前往登入</a></main></html>"
    )
    handler.send_skillops_bytes(status, "text/html; charset=utf-8", body.encode("utf-8"))


def _send_static(handler, relative: str) -> None:
    target = (STATIC_DIR / "assets" / relative).resolve()
    assets_root = (STATIC_DIR / "assets").resolve()
    if assets_root not in target.parents or not target.is_file() or target.suffix not in STATIC_TYPES:
        handler.send_skillops_bytes(404, "text/plain; charset=utf-8", b"Not found")
        return
    handler.send_skillops_bytes(200, STATIC_TYPES[target.suffix], target.read_bytes(),
                                cache_control="public, max-age=31536000, immutable")


def _send_index(handler) -> None:
    index = STATIC_DIR / "index.html"
    if not index.is_file():
        handler.send_skillops_bytes(503, "text/plain; charset=utf-8", "專案工作台的前端還沒建置。".encode("utf-8"))
        return
    handler.send_skillops_bytes(200, "text/html; charset=utf-8", index.read_bytes(),
                                cache_control="no-store, no-cache, must-revalidate")


# ---------- 請求檢查 ----------

def _write_allowed(handler) -> str | None:
    """非 GET 的請求：要帶 X-Requested-With: projects；有 Origin 就要是同一個網站。"""

    headers = handler.headers
    if (headers.get("X-Requested-With") or "").strip().lower() != "projects":
        return "缺少必要的請求標頭"
    origin = (headers.get("Origin") or "").strip()
    if origin:
        host = (headers.get("Host") or "").strip().lower()
        allowed = {f"https://{host}", f"http://{host}"}
        if origin.lower() not in allowed:
            return "不接受從別的網站送來的請求"
    return None


def _json_body(handler):
    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        return None, (400, {"error": "請求長度不對"})
    if length < 0:
        return None, (400, {"error": "請求長度不對"})
    if length > MAX_JSON_BODY:
        return None, (413, {"error": "內容太大"})
    content_type = (handler.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return None, (415, {"error": "請用 JSON 送出"})
    try:
        body = handler.read_json_body()
    except ValueError:
        return None, (400, {"error": "JSON 格式不對"})
    return (body if isinstance(body, dict) else {}), None


def _raw_body(handler, too_big="圖片最大 8 MB"):
    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        return None, (400, {"error": "請求長度不對"})
    if length < 0:
        return None, (400, {"error": "請求長度不對"})
    if length > MAX_UPLOAD_BODY:
        return None, (413, {"error": too_big})
    data = handler.rfile.read(length) if length else b""
    handler._body_consumed = True
    if len(data) != length:
        return None, (400, {"error": "檔案未完整送達"})
    return data, None


# ---------- API 分派 ----------

GET_ROUTES = [
    (re.compile(rf"/projects/api/{SLUG}/agents"), "agents"),
    (re.compile(r"/projects/api/members"), "members"),
    (re.compile(rf"/projects/api/{SLUG}/tabs/{KEY}/export"), "export_tab"),
    (re.compile(r"/projects/api/me"), "me"),
    (re.compile(r"/projects/api/projects"), "projects"),
    (re.compile(rf"/projects/api/{SLUG}"), "project"),
    (re.compile(rf"/projects/api/{SLUG}/tabs/{KEY}"), "tab"),
    (re.compile(rf"/projects/api/{SLUG}/tabs/{KEY}/revisions"), "revisions"),
    (re.compile(rf"/projects/api/{SLUG}/deleted-tabs"), "deleted_tabs"),
    (re.compile(rf"/projects/api/{SLUG}/history"), "history"),
    (re.compile(rf"/projects/api/{SLUG}/assets/(pa_[0-9a-f]{{32}})"), "asset"),
    (re.compile(rf"/projects/api/{SLUG}/assets/(pa_[0-9a-f]{{32}})/meta"), "asset_meta"),
    (re.compile(rf"/projects/api/{SLUG}/assistant"), "assistant_state"),
    (re.compile(rf"/projects/api/{SLUG}/assistant/manager"), "assistant_manager"),
    (re.compile(rf"/projects/api/{SLUG}/assistant/messages/(\d{{1,18}})/document"), "assistant_document"),
    (re.compile(rf"/projects/api/{SLUG}/assistant/conversations"), "assistant_conversations"),
    (re.compile(rf"/projects/api/{SLUG}/assistant/conversations/(\d{{1,18}})"), "assistant_conversation"),
    (re.compile(rf"/projects/api/{SLUG}/assistant/attachments/(\d{{1,18}})/(thumb|preview|file)"),
     "assistant_attachment"),
]
ANN = r"(\d{1,18})"
POST_ROUTES = [
    (re.compile(rf"/projects/api/{SLUG}/agents"), "save_agent"),
    (re.compile(rf"/projects/api/{SLUG}/agents/([a-z][a-z0-9_-]{{0,63}})/toggle"), "toggle_agent"),
    (re.compile(rf"/projects/api/{SLUG}/tabs/{KEY}/table-edit"), "table_edit"),
    (re.compile(rf"/projects/api/{SLUG}/tabs/{KEY}/table-schema"), "table_schema"),
    (re.compile(rf"/projects/api/{SLUG}/tabs/import-preview"), "import_preview"),
    (re.compile(r"/projects/api/members"), "save_member"),
    (re.compile(rf"/projects/api/{SLUG}/tabs/import"), "import_tab"),
    (re.compile(r"/projects/api/projects"), "create_project"),
    (re.compile(rf"/projects/api/{SLUG}/meta"), "update_project"),
    (re.compile(rf"/projects/api/{SLUG}/tabs"), "create_tab"),
    (re.compile(rf"/projects/api/{SLUG}/tabs/{KEY}/ops"), "ops"),
    (re.compile(rf"/projects/api/{SLUG}/tabs/{KEY}/meta"), "update_tab"),
    (re.compile(rf"/projects/api/{SLUG}/tabs/{KEY}/delete"), "delete_tab"),
    (re.compile(rf"/projects/api/{SLUG}/tabs/{KEY}/restore"), "restore_tab"),
    (re.compile(rf"/projects/api/{SLUG}/tabs/{KEY}/revisions/(\d{{1,9}})/restore"), "restore_revision"),
    (re.compile(rf"/projects/api/{SLUG}/tabs/{KEY}/revert"), "revert"),
    (re.compile(rf"/projects/api/{SLUG}/fields"), "set_field"),
    (re.compile(rf"/projects/api/{SLUG}/annotations"), "create_annotation"),
    (re.compile(rf"/projects/api/{SLUG}/annotations/{ANN}/comments"), "comment_annotation"),
    (re.compile(rf"/projects/api/{SLUG}/annotations/{ANN}/resolve"), "resolve_annotation"),
    (re.compile(rf"/projects/api/{SLUG}/annotations/{ANN}/reconfirm"), "reconfirm_annotation"),
    (re.compile(rf"/projects/api/{SLUG}/annotations/{ANN}/reattach"), "reattach_annotation"),
    (re.compile(rf"/projects/api/{SLUG}/annotations/{ANN}/style"), "style_annotation"),
    (re.compile(rf"/projects/api/{SLUG}/annotations/{ANN}/delete"), "delete_annotation"),
    (re.compile(rf"/projects/api/{SLUG}/comments/(\d{{1,18}})/delete"), "remove_comment"),
    (re.compile(rf"/projects/api/{SLUG}/locks"), "lock"),
    (re.compile(rf"/projects/api/{SLUG}/assets"), "upload_asset"),
    (re.compile(rf"/projects/api/{SLUG}/assistant/messages"), "assistant_send"),
    (re.compile(rf"/projects/api/{SLUG}/assistant/proposals/(\d{{1,18}})/apply"), "assistant_apply"),
    (re.compile(rf"/projects/api/{SLUG}/assistant/proposals/(\d{{1,18}})/dismiss"), "assistant_dismiss"),
    (re.compile(rf"/projects/api/{SLUG}/assistant/notes"), "assistant_note"),
    (re.compile(rf"/projects/api/{SLUG}/assistant/notes/(\d{{1,18}})/done"), "assistant_note_done"),
    (re.compile(rf"/projects/api/{SLUG}/assistant/forwards/(\d{{1,18}})/answer"), "assistant_answer"),
    (re.compile(rf"/projects/api/{SLUG}/assistant/members"), "assistant_member"),
    (re.compile(rf"/projects/api/{SLUG}/assistant/settings"), "assistant_settings"),
    (re.compile(rf"/projects/api/{SLUG}/assistant/conversations"), "assistant_new_conversation"),
    (re.compile(rf"/projects/api/{SLUG}/assistant/conversations/(\d{{1,18}})/resume"), "assistant_resume_conversation"),
    (re.compile(rf"/projects/api/{SLUG}/assistant/attachments"), "assistant_upload"),
    (re.compile(rf"/projects/api/{SLUG}/assistant/attachments/(\d{{1,18}})/delete"), "assistant_attachment_delete"),
]
RAW_UPLOADS = {"upload_asset": "媒體檔案最大 64 MB", "assistant_upload": "檔案最大 8 MB", "import_tab": "檔案最大 8 MB", "import_preview": "檔案最大 8 MB"}
WRITES = {name for _, name in POST_ROUTES}
COMMIT_READS = {"tab"}  # 讀舊內容時會補 bid 並存回


def _route(method: str, path: str):
    for pattern, name in GET_ROUTES if method == "GET" else POST_ROUTES:
        match = pattern.fullmatch(path)
        if match:
            return name, match.groups()
    return None, ()


def _assistant_call(name, conn, me, args, body, raw=b""):
    slug = args[0]
    if name == "assistant_conversations":
        return assistant_service.conversations(conn, me, slug)
    if name == "assistant_conversation":
        return assistant_service.conversation(conn, me, slug, int(args[1]))
    if name == "assistant_new_conversation":
        return assistant_service.new_conversation(conn, me, slug)
    if name == "assistant_resume_conversation":
        return assistant_service.resume_conversation(conn, me, slug, int(args[1]))
    if name == "assistant_upload":
        return assistant_service.upload_attachment(conn, me, slug, raw, str(body.get("content_type") or ""),
                                                   str(body.get("filename") or ""))
    if name == "assistant_attachment_delete":
        return assistant_service.delete_attachment(conn, me, slug, int(args[1]))
    if name == "assistant_state":
        return assistant_service.state(conn, me, slug)
    if name == "assistant_manager":
        return assistant_service.manager(conn, me, slug)
    if name == "assistant_send":
        return assistant_service.send(conn, me, slug, body)
    if name == "assistant_apply":
        return assistant_service.apply_proposal(conn, me, slug, int(args[1]), body)
    if name == "assistant_dismiss":
        return assistant_service.dismiss_proposal(conn, me, slug, int(args[1]))
    if name == "assistant_note":
        return assistant_service.add_note(conn, me, slug, body)
    if name == "assistant_note_done":
        return assistant_service.finish_note(conn, me, slug, int(args[1]))
    if name == "assistant_answer":
        return assistant_service.answer_forward(conn, me, slug, int(args[1]), body)
    if name == "assistant_member":
        return assistant_service.set_member(conn, me, slug, body)
    if name == "assistant_settings":
        return assistant_service.set_report_source(conn, me, slug, body)
    raise LookupError(name)


def _call(name, conn, me, args, query, body, raw):
    if name in ('agents','save_agent','toggle_agent'):
        from project_assistant import agent_registry
        try:
            if name == 'agents':
                return 200, {'agents':agent_registry.roster(conn,me,args[0])}
            if name == 'toggle_agent':
                profile = agent_registry.get_agent(conn,args[0],args[1])
                if not profile:
                    return 404, {'error':'找不到這個代理'}
                body = {'agent_key':args[1], 'enabled':body.get('enabled',not profile['enabled'])}
            return 200, {'agent':agent_registry.save_agent(conn,me,args[0],body)}
        except agent_registry.AgentError as exc:
            return exc.status, {'error':str(exc),'code':exc.code}
    if name == "table_schema":
        from project_docs import table_schema
        return table_schema.apply(conn, me, args[0], args[1], body)
    if name == "import_preview":
        return service.preview_import_file(conn, me, args[0], str(body.get("filename") or ""), raw,
            tab_key=(query.get("tab_key") or [None])[0], base_revision=(query.get("base_revision") or [None])[0],
            header_row=(query.get("header_row") or [1])[0], worksheet=(query.get("worksheet") or [None])[0],
            delivery_mode=(query.get("delivery_mode") or ["original_patch"])[0])
    if name == "table_edit":
        from project_assistant import table_edits
        tab = repo.get_tab_for_update(conn, args[0], args[1])
        if not tab:
            return 404, {"error": "找不到分頁"}
        edits = body.get("row_edits", [])
        cas = isinstance(edits, list) and bool(edits) and all(isinstance(edit, dict) and "expected_cells" in edit for edit in edits)
        if body.get("base_revision") != tab["revision"] and (not cas or body.get("new_rows")):
            return 409, {"error": "分頁已更新，請重新整理後再貼上"}
        if body.get("base_revision") != tab["revision"] and any(set(edit.get("column_ids", {})) != set(edit["cells"]) for edit in edits):
            return 409, {"error": "分頁已更新，跨版本修改需包含每個儲存格的穩定欄位身分"}
        try:
            values = repo.field_values(conn, args[0]).get(args[1], {})
            if cas:
                table_edits.check_expected(tab["doc"], edits, values, body.get("table_id"))
            ops, fields, _ = table_edits.prepare(tab["doc"], body.get("row_edits", []), body.get("new_rows", []), values, body.get("table_id"))
            return table_edits.apply(conn, me, args[0], {"tab_key": args[1], "ops": ops, "field_edits": fields, "delivery_mode": body.get("delivery_mode")})
        except table_edits.CellConflict as exc:
            return 409, {"error": str(exc), "conflicts": exc.conflicts}
        except ValueError as exc:
            return 400, {"error": str(exc)}
    if name == "members":
        return members.list_members(conn, me)
    if name == "save_member":
        return members.save_member(conn, me, body)
    if name == "import_tab":
        return service.import_tab_file(conn, me, args[0], str(body.get("filename") or ""), raw,
                                       tab_key=(query.get("tab_key") or [None])[0],
                                       base_revision=(query.get("base_revision") or [None])[0],
                                       header_row=(query.get("header_row") or [1])[0], worksheet=(query.get("worksheet") or [None])[0],
                                       delivery_mode=(query.get("delivery_mode") or ["original_patch"])[0],
                                       confirm_replace=(query.get("confirm_replace") or [""])[0] == "true")
    if name.startswith("assistant_"):
        return _assistant_call(name, conn, me, args, body, raw)
    if name == "me":
        return service.me_payload(me)
    if name == "projects":
        return service.projects_payload(conn, me)
    if name == "create_project":
        return service.create_project(conn, me, body)
    if name == "update_project":
        return service.update_project(conn, me, args[0], body)
    if name == "project":
        status, payload = service.project_payload(conn, me, args[0])
        if status == 200:
            payload["assistant"] = assistant_service.flags(conn, me, args[0])
        return status, payload
    if name == "tab":
        return service.tab_payload(conn, me, *args)
    if name == "revisions":
        return service.revisions_payload(conn, me, *args)
    if name == "deleted_tabs":
        return service.deleted_tabs_payload(conn, me, args[0])
    if name == "history":
        return service.history_payload(conn, me, args[0], (query.get("tab") or [None])[0])
    if name == "revert":
        return service.revert_change(conn, me, args[0], args[1], body)
    if name == "create_tab":
        return service.create_tab(conn, me, args[0], body)
    if name == "ops":
        return service.apply_tab_ops(conn, me, args[0], args[1], body)
    if name == "update_tab":
        return service.update_tab(conn, me, args[0], args[1], body)
    if name == "delete_tab":
        return service.delete_tab(conn, me, *args)
    if name == "restore_tab":
        return service.restore_tab(conn, me, *args)
    if name == "restore_revision":
        return service.restore_revision(conn, me, args[0], args[1], int(args[2]))
    if name == "set_field":
        return service.set_field(conn, me, args[0], body)
    if name == "create_annotation":
        return service.create_annotation(conn, me, args[0], body)
    if name == "comment_annotation":
        return service.comment_annotation(conn, me, args[0], int(args[1]), body)
    if name == "resolve_annotation":
        return service.resolve_annotation(conn, me, args[0], int(args[1]), body)
    if name == "reconfirm_annotation":
        return service.reconfirm_annotation(conn, me, args[0], int(args[1]))
    if name == "reattach_annotation":
        return service.reattach_annotation(conn, me, args[0], int(args[1]), body)
    if name == "style_annotation":
        return service.style_annotation(conn, me, args[0], int(args[1]), body)
    if name == "delete_annotation":
        return service.delete_annotation(conn, me, args[0], int(args[1]))
    if name == "remove_comment":
        return service.remove_comment(conn, me, args[0], int(args[1]))
    if name == "lock":
        return service.lock_unit(conn, me, args[0], body)
    if name == "upload_asset":
        return service.upload_asset(conn, me, args[0], raw, str(body.get("content_type") or ""))
    raise LookupError(name)


def _api(handler, parsed, method: str) -> None:
    name, args = _route(method, parsed.path)
    if not name:
        handler.send_json(404, {"error": "沒有這個功能"})
        return
    identity, problem = handler.project_docs_identity()
    if problem:
        status, title, message = PROBLEM_PAGES[problem]
        handler.send_json(status, {"error": message, "code": f"projects_{problem}"})
        return
    me = service.identity_from(identity)
    if not me:
        handler.send_json(403, {"error": PROBLEM_PAGES["membership"][2], "code": "projects_membership"})
        return
    body, raw = {}, b""
    if name in WRITES:
        if not me.can_write:
            handler.send_json(403, {"error": "唯讀成員不能修改專案"})
            return
        refused = _write_allowed(handler)
        if refused:
            handler.send_json(403, {"error": refused})
            return
        if name in RAW_UPLOADS:
            raw, problem_response = _raw_body(handler, RAW_UPLOADS[name])
            body = {"content_type": handler.headers.get("Content-Type") or "",
                    "filename": unquote(handler.headers.get("X-File-Name") or "")}
        else:
            body, problem_response = _json_body(handler)
        if problem_response:
            handler.send_json(*problem_response)
            return
    query = parse_qs(parsed.query)
    try:
        conn = open_connection()
    except Exception as exc:  # noqa: BLE001
        print(f"projects: database unavailable: {type(exc).__name__}: {exc}", flush=True)
        handler.send_json(503, {"error": "資料庫暫時連不上，請稍後再試"})
        return
    try:
        _ensure_schema(conn)
        if name == "export_tab":
            status, payload = service.export_tab_file(conn, me, *args, (query.get("format") or [""])[0], (query.get("mode") or ["original_patch"])[0])
            conn.rollback()
            if status != 200:
                handler.send_json(status, payload)
                return
            handler.send_skillops_bytes(200, payload["content_type"], payload["data"],
                                        cache_control="private, no-store",
                                        disposition=_attachment(args[0], payload["filename"]))
            return
        if name == "asset_meta":
            found = repo.get_asset(conn, args[0], args[1])
            conn.rollback()
            handler.send_json(200 if found else 404, {"content_type": found[0], "bytes": len(found[1])} if found else {"error": "找不到媒體"})
            return
        if name == "asset":
            found = repo.get_asset(conn, args[0], args[1])
            conn.rollback()
            if not found:
                handler.send_json(404, {"error": "找不到這張圖"})
                return
            handler.send_skillops_bytes(200, found[0], found[1],
                                        cache_control="private, max-age=31536000, immutable",
                                        etag=f'"{args[1]}"')
            return
        if name == "assistant_attachment":
            status, payload = assistant_service.attachment_file(conn, me, args[0], int(args[1]), args[2])
            conn.rollback()
            if status != 200:
                handler.send_json(status, payload)
                return
            if payload["content_type"].startswith("image/"):
                handler.send_skillops_bytes(200, payload["content_type"], payload["data"],
                                            cache_control="private, max-age=86400")
            else:  # 使用者上傳的其他檔一律當下載，不在我們的網域上直接打開
                handler.send_skillops_bytes(200, "application/octet-stream", payload["data"],
                                            cache_control="private, no-store",
                                            disposition=_attachment(args[0], payload["name"]))
            return
        if name == "assistant_document":
            status, payload = assistant_service.document(conn, me, args[0], int(args[1]),
                                                         base_url=_public_base(handler, args[0]))
            conn.rollback()
            if status != 200:
                handler.send_json(status, payload)
                return
            handler.send_skillops_bytes(200, DOCX_TYPE, payload["data"], cache_control="private, no-store",
                                        disposition=_attachment(args[0], payload["filename"]))
            return
        status, payload = _call(name, conn, me, args, query, body, raw)
        if (name in WRITES or name in COMMIT_READS) and status < 400:
            conn.commit()
        else:
            conn.rollback()
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        print(f"projects: {name} failed: {type(exc).__name__}: {exc}", flush=True)
        handler.send_json(500, {"error": "伺服器出錯了，請稍後再試；一直這樣請聯絡專案管理員"})
        return
    finally:
        conn.close()
    handler.send_json(status, payload)


def handle_projects(handler, parsed, method: str) -> bool:
    """是 /projects 底下的請求就處理並回 True；否則回 False 交給其他路由。"""

    path = parsed.path
    from project_docs import runtime_http
    if runtime_http.handle(handler, parsed, method):
        return True
    if path == "/projects":
        if method == "GET":
            _redirect(handler, "/projects/")
            return True
        return False
    if not path.startswith("/projects/"):
        return False
    if path.startswith("/projects/api/"):
        _api(handler, parsed, method)
        return True
    if method != "GET":
        handler.send_json(405, {"error": "不支援這個操作"})
        return True
    if path.startswith("/projects/assets/"):
        _send_static(handler, unquote(path[len("/projects/assets/"):]))
        return True
    page = re.fullmatch(rf"/projects/(?:{SLUG}/)?", path)
    if not page:
        bare = re.fullmatch(rf"/projects/{SLUG}", path)
        if bare:
            _redirect(handler, path + "/" + (f"?{parsed.query}" if parsed.query else ""))
            return True
        handler.send_skillops_bytes(404, "text/plain; charset=utf-8", "找不到這個頁面".encode("utf-8"))
        return True
    identity, problem = handler.project_docs_identity(record_login=True)
    if problem:
        _problem_page(handler, problem, identity)
        return True
    if not service.identity_from(identity):
        _problem_page(handler, "membership", identity)
        return True
    _send_index(handler)
    return True
