"""Remote execution routes, isolated from the document HTTP dispatcher."""
import re
from urllib.parse import parse_qs

from project_assistant import flow_runner as flows, limbs
from project_docs import repository as repo, service

FLOW = re.compile(r"^/projects/api/([a-z0-9][a-z0-9-]{0,40})/tabs/([a-z0-9][a-z0-9-]{0,40})/flow(?:/runs(?:/([0-9a-f-]{36})(?:/(cancel|retry))?)?)?$")
PREFLIGHT = re.compile(r"^/projects/api/([a-z0-9][a-z0-9-]{0,40})/tabs/([a-z0-9][a-z0-9-]{0,40})/flow/preflight$")
TASKS = re.compile(r"^/projects/api/([a-z0-9][a-z0-9-]{0,40})/tasks$")
WORKER_ACTIONS = {"claim", "renew", "complete", "fail", "upload-cell-asset"}
ASSET = re.compile(r"^/projects/api/([a-z0-9][a-z0-9-]{0,40})/assets/(pa_[0-9a-f]{32})$")


def handle(handler, parsed, method):
    """Return True only for owned routes; enforce member or worker identity independently."""
    asset = ASSET.fullmatch(parsed.path)
    bearer = handler.headers.get("Authorization", "")
    if asset and method == "GET" and bearer.startswith("Bearer "):
        from project_docs import auth
        if not auth.token_actor(bearer[7:], auth.config()):
            return _worker_asset(handler, asset[1], asset[2], bearer[7:])
    flow = FLOW.fullmatch(parsed.path)
    preflight = PREFLIGHT.fullmatch(parsed.path)
    tasks = TASKS.fullmatch(parsed.path)
    limb_path = parsed.path == "/projects/api/limbs" or parsed.path.startswith("/projects/api/limbs/")
    if not flow and not preflight and not limb_path and not tasks:
        return False
    from project_docs import http
    action = parsed.path.rsplit("/", 1)[-1] if limb_path else None
    worker_action = limb_path and action in WORKER_ACTIONS
    me, body, raw = None, {}, b""
    if method not in ("GET", "POST") or (worker_action and method != "POST"):
        handler.send_json(405, {"error": "不支援這個操作"})
        return True
    if not worker_action:
        identity, problem = handler.project_docs_identity()
        me = service.identity_from(identity) if not problem else None
        if not me:
            handler.send_json(401, {"error": "需要有效成員登入"})
            return True
    if method == "POST":
        if not worker_action:
            refused = http._write_allowed(handler)
            if refused:
                handler.send_json(403, {"error": refused})
                return True
        if action == "upload-cell-asset":
            from project_docs import media
            try:
                size = int(handler.headers.get("Content-Length") or "0")
            except ValueError:
                size = -1
            if size <= 0 or size > media.MAX_BYTES:
                handler.send_json(413 if size > 0 else 400, {"error": "媒體檔案大小無效或超過上限"})
                return True
            raw = handler.rfile.read(size)
            handler._body_consumed = True
            if len(raw) != size:
                handler.send_json(400, {"error": "檔案未完整送達"})
                return True
        else:
            body, error = http._json_body(handler)
            if error:
                handler.send_json(*error)
                return True
    conn = None
    try:
        conn = http.open_connection()
        http._ensure_schema(conn)
        query = parse_qs(parsed.query)
        if worker_action:
            auth = handler.headers.get("Authorization", "")
            worker = limbs.authenticate(conn, auth[7:] if auth.startswith("Bearer ") else "")
            if action == "claim":
                payload = flows.claim(conn, worker)
            elif action == "upload-cell-asset":
                from project_docs import media
                identifier = (query.get("task_id") or [None])[0]
                lease = (query.get("lease_token") or [None])[0]
                run, task = flows.leased_task(conn, worker, identifier, lease)
                mime = media.validate(raw, handler.headers.get("Content-Type", ""))
                # Attribute the upload to the active run creator, never a user id from the worker.
                me = flows._creator(conn, run)
                asset_id = repo.put_asset(conn, run["project_slug"], data=raw, content_type=mime, actor_id=me.actor_id)
                payload = {"asset_id": asset_id, "asset_url": f"/projects/api/{run['project_slug']}/assets/{asset_id}", "content_type": mime}
            else:
                payload = {"renew": flows.renew, "complete": flows.complete, "fail": flows.fail}[action](conn, worker, body)
        elif preflight:
            if method != "POST":
                raise limbs.ExecutionError(405, "不支援這個操作")
            payload = flows.preflight(conn, me, *preflight.groups(), body)
        elif tasks:
            if method != "GET":
                raise limbs.ExecutionError(405, "不支援這個操作")
            payload = flows.recent_tasks(conn, tasks[1], (query.get("target_tab") or [None])[0])
        elif limb_path:
            if method == "GET" and parsed.path == "/projects/api/limbs":
                payload = {"limbs": limbs.list_workers(conn, (query.get("project_slug") or [None])[0])}
            elif method == "POST" and action == "register":
                payload = limbs.register(conn, me, body)
            elif method == "POST" and action == "revoke":
                payload = limbs.revoke(conn, me, body.get("limb_id"))
            else:
                raise limbs.ExecutionError(404, "找不到手腳 API")
        else:
            slug, key, identifier, control = flow.groups()
            if identifier:
                if method == "POST" and control:
                    payload = flows.control(conn, me, slug, key, identifier, control)
                elif method == "GET" and not control:
                    payload = flows.detail(conn, slug, key, identifier)
                else:
                    raise limbs.ExecutionError(405, "不支援這個操作")
            elif parsed.path.endswith("/runs"):
                payload = flows.list_runs(conn, slug, key) if method == "GET" else flows.start(conn, me, slug, key, body)
            else:
                payload = flows.definition(conn, slug, key) if method == "GET" else flows.save_definition(conn, me, slug, key, body)
        conn.commit()
        handler.send_json(200, payload)
    except limbs.ExecutionError as exc:
        if conn:
            conn.rollback()
        handler.send_json(exc.status, {"error": str(exc)})
    except Exception as exc:
        if conn:
            conn.rollback()
        from project_docs import media
        if isinstance(exc, media.MediaError):
            handler.send_json(exc.status, {"error": str(exc)})
        elif isinstance(exc, (ValueError, TypeError, KeyError)) or type(exc).__name__ in ("InvalidTextRepresentation",):
            handler.send_json(400, {"error": "請求內容無效：" + str(exc)[:200]})
        else:
            print(f"execution API: {type(exc).__name__}: {exc}", flush=True)
            handler.send_json(503 if conn is None else 500, {"error": "執行服務暫時無法使用"})
    finally:
        if conn:
            conn.close()
    return True


def _worker_asset(handler, slug, asset_id, token):
    from project_docs import http
    from project_assistant import privacy
    conn = http.open_connection()
    try:
        worker = limbs.authenticate(conn, token)
        if slug not in worker["allowed_projects"]:
            raise limbs.ExecutionError(403, "Worker 無權存取此專案")
        if privacy.mode(conn, slug) == "mask_numbers":
            raise limbs.ExecutionError(403, "數值遮罩模式不提供原始媒體給遠端手腳")
        found = repo.get_asset(conn, slug, asset_id)
        if not found:
            raise limbs.ExecutionError(404, "找不到媒體")
        conn.commit()
        handler.send_skillops_bytes(200, found[0], found[1], cache_control="private, no-store")
    except limbs.ExecutionError as exc:
        conn.rollback()
        handler.send_json(exc.status, {"error": str(exc)})
    finally:
        conn.close()
    return True
