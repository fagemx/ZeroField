"""Remote execution routes, isolated from the document HTTP dispatcher."""
import re
import time
from datetime import timedelta
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
    from project_docs import console_http
    if console_http.handle(handler, parsed, method):
        return True
    from project_docs import agent_http  # service accounts and the zerofield-mcp agent API (SPEC_20 R30, R31)
    if agent_http.handle(handler, parsed, method):
        return True
    if parsed.path == "/aivideo/open/v1" or parsed.path.startswith("/aivideo/open/v1/"):
        from project_docs import story_openapi
        return story_openapi.handle(handler, parsed, method)
    if parsed.path.startswith("/openapi/v2/"):
        return _handle_openapi(handler, parsed, method)
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
    orchestration_path=bool(re.fullmatch(r'/projects/api/limbs/orchestration/(claim|renew|complete|fail|upload-cell-asset|tool_list|tool)',parsed.path))
    worker_action = parsed.path in {'/projects/api/limbs/'+name for name in WORKER_ACTIONS} or orchestration_path
    me, body, raw = None, {}, b""
    if method not in ("GET", "POST") or (worker_action and method != "POST"):
        handler.send_json(405, {"error": "Unsupported operation."})
        return True
    if not worker_action:
        identity, problem = handler.project_docs_identity()
        me = service.identity_from(identity) if not problem else None
        if not me:
            handler.send_json(401, {"error": "Sign in with an active crew account."})
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
                handler.send_json(413 if size > 0 else 400, {"error": "The media size is invalid or exceeds the limit."})
                return True
            raw = handler.rfile.read(size)
            handler._body_consumed = True
            if len(raw) != size:
                handler.send_json(400, {"error": "The file upload is incomplete."})
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
            if orchestration_path:
                from project_assistant import orchestration_limb
                if action=='upload-cell-asset':
                    payload=orchestration_limb.upload(conn,worker,{k:(query.get(k) or [None])[0] for k in ('task_id','dispatch_handle','lease_token')},raw,handler.headers.get('Content-Type',''))
                elif action=='tool':
                    payload=orchestration_limb.tool(conn,worker,body,http.open_connection)
                else:
                    payload=getattr(orchestration_limb,action)(conn,worker,body) if action!='claim' else orchestration_limb.claim(conn,worker)
            elif action == "claim":
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
                raise limbs.ExecutionError(405, "Unsupported operation.")
            payload = flows.preflight(conn, me, *preflight.groups(), body)
        elif tasks:
            if method != "GET":
                raise limbs.ExecutionError(405, "Unsupported operation.")
            payload = flows.recent_tasks(conn, tasks[1], (query.get("target_tab") or [None])[0])
        elif limb_path:
            if method == "GET" and parsed.path == "/projects/api/limbs":
                payload = {"limbs": limbs.list_workers(conn, (query.get("project_slug") or [None])[0])}
            elif method == "POST" and action == "register":
                payload = limbs.register(conn, me, body)
            elif method == "POST" and action == "revoke":
                payload = limbs.revoke(conn, me, body.get("limb_id"))
            else:
                raise limbs.ExecutionError(404, "Worker API endpoint not found.")
        else:
            slug, key, identifier, control = flow.groups()
            if identifier:
                if method == "POST" and control:
                    payload = flows.control(conn, me, slug, key, identifier, control)
                elif method == "GET" and not control:
                    payload = flows.detail(conn, slug, key, identifier)
                else:
                    raise limbs.ExecutionError(405, "Unsupported operation.")
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
        from project_assistant.agent_registry import AgentError
        if isinstance(exc,AgentError):
            handler.send_json(exc.status,{'error':str(exc),'code':exc.code})
        elif isinstance(exc, media.MediaError):
            handler.send_json(exc.status, {"error": str(exc)})
        elif isinstance(exc, (ValueError, TypeError, KeyError)) or type(exc).__name__ in ("InvalidTextRepresentation",):
            handler.send_json(400, {"error": "Invalid request:" + str(exc)[:200]})
        else:
            print(f"execution API: {type(exc).__name__}: {exc}", flush=True)
            handler.send_json(503 if conn is None else 500, {"error": "The worker service is temporarily unavailable."})
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
            raise limbs.ExecutionError(403, "This worker cannot access the production.")
        if privacy.mode(conn, slug) == "mask_numbers":
            raise limbs.ExecutionError(403, "Original media is not shared with remote workers in numeric masking mode.")
        found = repo.get_asset(conn, slug, asset_id)
        if not found:
            raise limbs.ExecutionError(404, "Media not found.")
        conn.commit()
        handler.send_skillops_bytes(200, found[0], found[1], cache_control="private, no-store")
    except limbs.ExecutionError as exc:
        conn.rollback()
        handler.send_json(exc.status, {"error": str(exc)})
    finally:
        conn.close()
    return True


OPENAPI_RUN = re.compile(r"^/openapi/v2/run/(?:ai-app|workflow)/([A-Za-z0-9_.-]{1,80})$")
OPENAPI_MEDIA = re.compile(r"^/openapi/v2/media/(?:output|input)/([A-Za-z0-9._-]{1,120})$")


def _v2_authority(actor_id, slug):
    """Mint a server-only actor/project capability, never from serialized task fields."""
    from project_assistant.studio.openapi_v2_hub import _OpenAPIAuthority

    class Authority(_OpenAPIAuthority):
        def context(self, card):
            from project_assistant import execution_governance as governance
            self.accounting_context = governance.media_context(service.Identity(actor_id, 'Media API', 'member'), slug)
            self.accounting_destination = governance.media_destination(card)
            from project_docs import http
            with http.open_connection() as conn:
                binding=governance.live(conn,self.accounting_context,destination=self.accounting_destination)
                self.accounting_context.operation_deadline_at=(governance.cp.now()+timedelta(seconds=binding['environment']['config'].get('timeout_seconds',300))).isoformat()
                governance.media_credentials(conn,self.accounting_context,card)
            return self.accounting_context

        def prepare(self, card, inputs, key):
            from project_assistant import execution_governance as governance
            from project_docs import http, story_openapi as story
            ctx = governance.media_context(service.Identity(actor_id, 'Media API', 'member'), slug,
                accounting_session_key='v2:' + key)
            with http.open_connection() as conn:
                governance.prepare_operation(conn, ctx, request_key='v2:' + key, card=card,
                    operation_digest=story.digest(inputs), router_request={'task':{'production_policy':story.production_policy(conn,slug)},
                    'values':{f"{n['nodeId']}.{n['fieldName']}":n['fieldValue'] for n in inputs[2]}} if card['engine_config']['driver']=='comfy_router' else None)
            self.accounting_context = ctx
            self.accounting_destination = governance.media_destination(card)
            return ctx, 'v2:' + key

        def check_destination(self, url):
            from project_assistant import execution_governance as governance
            governance.check_destination(self.accounting_context,url)

        def check(self, card, references):
            from project_docs import http, story_openapi as story
            with http.open_connection() as conn:
                story.authorize(conn, service.Identity(actor_id, "Media API", "member"), slug, write=True)
                story.authorize_card(conn, slug, card)
                from project_assistant import execution_governance as governance
                if hasattr(self, 'accounting_context'):
                    governance.live(conn, self.accounting_context, destination=self.accounting_destination)
                    governance.media_credentials(conn,self.accounting_context,card)
                for reference in references:
                    saved = story.record(conn, "v2_" + story.digest([actor_id, "media", reference]), required=False)
                    if not saved:
                        raise story.StoryError(404, "DRAMA_NOT_FOUND", "Reference media does not belong to this account.")
                    if saved.get("slug") != slug:
                        raise story.StoryError(403, "DRAMA_OPERATION_NOT_ALLOWED", "Reference media belongs to another production.")

    return Authority()


def _handle_openapi(handler, parsed, method: str) -> bool:
    """Self-hosted RunningHub OpenAPI v2 compatible endpoints."""
    from project_docs import http, media, story_openapi as story
    from project_assistant import limb_worker as worker
    path = parsed.path
    try:
        identity, problem = handler.project_docs_identity()
        me = service.identity_from(identity) if not problem else None
        if not me:
            handler.send_json(401, {"code": 401, "msg": "Sign in with an active crew account."})
            return True
        if method != "GET":
            if not me.can_write or (not handler.headers.get("Authorization", "").startswith("Bearer ") and http._write_allowed(handler)):
                handler.send_json(403, {"code": 403, "msg": "Write access and a same-origin write header are required."})
                return True
        from project_docs import story_openapi as story
        def grant(kind, value, slug=None):
            with http.open_connection() as conn:
                http._ensure_schema(conn)
                if slug:
                    story.authorize(conn, me, slug, write=True)
                story.store(conn, "v2_" + story.digest([me.actor_id, kind, value]), "v2_grant", {"value": value, "slug": slug}, slug, me.actor_id)
        def require(kind, value):
            with http.open_connection() as conn:
                http._ensure_schema(conn)
                saved = story.record(conn, "v2_" + story.digest([me.actor_id, kind, value]), required=False)
                if not saved:
                    raise story.StoryError(404, "DRAMA_NOT_FOUND", "Media or task does not belong to this account.")
                if saved.get("slug"):
                    story.authorize(conn, me, saved["slug"], write=method != "GET")
                return saved
        media_match = OPENAPI_MEDIA.fullmatch(path)
        if media_match and method == "GET":
            require("media", media_match.group(1))
            found = worker.openapi_get_media(media_match.group(1))
            if not found:
                handler.send_json(404, {"code": 404, "msg": "Media not found"})
                return True
            raw_bytes, mime = found
            handler.send_skillops_bytes(200, mime, raw_bytes, cache_control="private, max-age=3600")
            return True
        if path == "/openapi/v2/cards" and method == "GET":
            from project_docs import story_openapi as story
            with http.open_connection() as conn:
                http._ensure_schema(conn)
                story.restore_cards(conn)
            handler.send_json(200, {"code": 0, "msg": "success", "cards": worker.openapi_list_cards()})
            return True
        if method != "POST":
            handler.send_json(405, {"code": 405, "msg": "Method not allowed"})
            return True
        if path == "/openapi/v2/media/upload/binary":
            slug = handler.headers.get("X-Project-Slug", "")
            with http.open_connection() as conn:
                http._ensure_schema(conn)
                story.authorize(conn, me, slug, write=True)
            try:
                size = int(handler.headers.get("Content-Length") or "0")
            except ValueError:
                size = -1
            if size <= 0 or size > media.MAX_BYTES:
                handler.send_json(413 if size > 0 else 400, {"code": 400, "msg": "Invalid or oversized media body"})
                return True
            raw = handler.rfile.read(size)
            handler._body_consumed = True
            payload = worker.openapi_upload_binary(
                raw,
                handler.headers.get("Content-Type") or "",
                handler.headers.get("X-File-Name") or "",
            )
            grant("media", payload["data"]["fileName"], slug)
            handler.send_json(200, payload)
            return True
        body, err = http._json_body(handler)
        if err:
            handler.send_json(err[0], {"code": err[0], "msg": err[1].get("error", "Invalid JSON")})
            return True
        if path == "/openapi/v2/cards/register":
            from project_docs import story_openapi as story
            identity, problem = handler.project_docs_identity()
            me = service.identity_from(identity) if not problem else None
            if not me:
                handler.send_json(401, {"code": 401, "msg": "Sign in to import a workflow."})
                return True
            if not handler.headers.get("Authorization", "").startswith("Bearer ") and http._write_allowed(handler):
                handler.send_json(403, {"code": 403, "msg": "A same-origin write header is required."})
                return True
            try:
                with http.open_connection() as conn:
                    http._ensure_schema(conn)
                    result = story.register_card(conn, me, body)
                with http.open_connection() as conn:
                    story.restore_cards(conn)
            except story.StoryError as exc:
                handler.send_json(exc.status, {"code": exc.code, "msg": str(exc)})
                return True
            handler.send_json(200, result)
            return True
        if path == "/openapi/v2/query":
            saved = require("task", str(body.get("taskId", "")))
            result = worker.openapi_query_task(body)
            for item in result.get("results", []):
                grant("media", item["url"].rsplit("/", 1)[-1], saved.get("slug"))
            handler.send_json(200, result)
            return True
        quote_match = re.fullmatch(r'/openapi/v2/quote/ai-app/([A-Za-z0-9_.-]{1,80})',path)
        if quote_match:
            from project_assistant.studio import openapi_v2_hub as hub, comfy_router
            if set(body)-{'nodeInfoList'}:
                raise story.StoryError(422,'DRAMA_VALIDATION_FAILED','Quote accepts native card inputs only.')
            slug=handler.headers.get('X-Project-Slug','')
            with http.open_connection() as conn:
                http._ensure_schema(conn)
                story.authorize(conn,me,slug,write=True)
                policy=story.production_policy(conn,slug)
            card, graph, nodes, policy, _, references=hub._prepare_openapi_inputs(quote_match[1],body,policy)
            if card['engine_config']['driver']!='comfy_router':
                raise story.StoryError(422,'DRAMA_VALIDATION_FAILED','Select an official Router card.')
            authority=_v2_authority(me.actor_id,slug)
            ctx=authority.context(card)
            authority.check(card,references)
            class QuoteHead:
                def lease_lost(self):
                    try:
                        authority.check(card,references)
                        return False
                    except (ValueError,worker.WorkerError):
                        return True
                def outbound_check(self,url):
                    authority.check_destination(url)
                def outbound_timeout(self,seconds):
                    from project_assistant import execution_governance as governance
                    return governance.remaining(ctx,seconds)
                def asset(self,task,reference):
                    authority.check(card,references)
                    if reference not in references:
                        raise worker.WorkerError('Reference is outside the expanded quote inputs.')
                    found=worker.openapi_get_media(reference)
                    if found is None:
                        raise worker.WorkerError('Reference unavailable.')
                    return found
            result=comfy_router.quote(ctx,{'production_policy':policy},card,{f"{n['nodeId']}.{n['fieldName']}":n['fieldValue'] for n in nodes},QuoteHead())
            handler.send_json(200,{'code':0,'msg':'success','data':result})
            return True
        run_match = OPENAPI_RUN.fullmatch(path)
        if run_match:
            host = (handler.headers.get("Host") or "127.0.0.1:8000").strip()
            base_url = f"http://{host}"
            slug = handler.headers.get("X-Project-Slug", "")
            actions=[]
            with http.open_connection() as conn:
                http._ensure_schema(conn)
                story.authorize(conn, me, slug, write=True)
                policy = story.production_policy(conn, slug)
                key=handler.headers.get('Idempotency-Key')
                identifier=None
                fingerprint=story.digest(body)
                if key is not None:
                    if not 1<=len(key)<=128:
                        raise story.StoryError(422,'DRAMA_VALIDATION_FAILED','Idempotency-Key must contain 1–128 characters.')
                    identifier='v2ik_'+story.digest([me.actor_id,slug,path,story.digest(handler.headers.get('Authorization','cookie')),key])
                    with conn.cursor() as cur:
                        cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(identifier,))
                    saved=story.record(conn,identifier,required=False)
                    if saved and saved['expires']>time.time():
                        if saved['hash']!=fingerprint:
                            raise story.StoryError(409,'DRAMA_IDEMPOTENCY_CONFLICT','Idempotency-Key was already used with different inputs.')
                        handler.send_json(200,saved['response'])
                        return True
                # Freeze/grant/persist before any executor launch; replay is never paid resubmission.
                result=worker.openapi_run_app(run_match.group(1),body,base_url=base_url,production_policy=policy,
                    _authority=_v2_authority(me.actor_id,slug),_post_commit_actions=actions)
                story.store(conn,'v2_'+story.digest([me.actor_id,'task',result['taskId']]),'v2_grant',{'value':result['taskId'],'slug':slug},slug,me.actor_id)
                if identifier:
                    story.store(conn,identifier,'v2_idempotency',{'hash':fingerprint,'response':result,'expires':time.time()+86400},slug,me.actor_id)
            for action in actions:
                action()
            handler.send_json(200, result)
            return True
        handler.send_json(404, {"code": 404, "msg": "OpenAPI v2 endpoint not found"})
        return True
    except story.StoryError as exc:
        handler.send_json(exc.status, {"code": exc.code, "msg": str(exc)})
        return True
    except worker.WorkerError as exc:
        handler.send_json(400, {"code": 400, "msg": str(exc), "errorMessage": str(exc)})
        return True
    except Exception as exc:  # noqa: BLE001
        handler.send_json(500, {"code": 500, "msg": "Media API unavailable; check deployment configuration."})
        return True
