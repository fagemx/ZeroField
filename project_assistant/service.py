"""給 3013 用的專案助理功能：旗標、對話、送出、確認／作廢提案、管理視角。

每個函式回傳 (HTTP 狀態碼, JSON)，跟 project_docs.service 一樣。
確認提案時用使用者本人的身分呼叫 project_docs.service，所以她自己做不到的事，經助理也做不到。
"""
from __future__ import annotations

import datetime as dt
import json
import re

from project_assistant import attachments, privacy, prompting, store, table_edits, todo, request_scope, proposal_review
from project_assistant.masking import guard_input
from project_docs import repository as repo
from project_docs import service as pd_service
from project_docs.doc_schema import STATUSES

MAX_MESSAGE = 4000
MAX_NOTE = 1000
ASSISTANT_SLUGS = set(todo.SOURCES)
WINDOWS_PATH = re.compile(r"^(?:[A-Za-z]:\\|\\\\)[^\x00-\x1f]{1,400}$")


def _error(status: int, message: str):
    return status, {"error": message}


def flags(conn, me, slug) -> dict:
    available = bool(repo.get_project(conn, slug))
    member_map = store.member_flags(conn, slug) if available else {}
    enabled = available and (me.can_edit or member_map.get(me.actor_id, True))
    return {"enabled": bool(enabled), "manager": bool(available and me.can_edit)}


def _gate(conn, me, slug):
    if not repo.get_project(conn, slug):
        return _error(404, "Production not found.")
    if not flags(conn, me, slug)["enabled"]:
        return _error(403, "Assistant access is not enabled for your account. Contact the showrunner.")
    return None


def _manager_gate(me, slug):
    if not slug:
        return _error(404, "Production not found.")
    if not me.can_edit:
        return _error(403, "Only the showrunner can view this.")
    return None


ASSET_SRC = re.compile(r"/assets/(pa_[0-9a-f]{32})$")


def document(conn, me, slug, message_id, *, base_url=None):
    """助理在回答裡放了「下載 Word 檔」時才拿得到：只限那則回答的主人、那則回答真的用過 offer_document。
    回傳 (200, {"filename", "data"}) 或 (錯誤碼, {"error"})；內容是下載當下的專案頁最新版。"""

    from project_assistant import docx_export

    problem = _gate(conn, me, slug)
    if problem:
        return problem
    msg = store.message(conn, message_id)
    offered = msg and any(t.get("tool") == "offer_document" and t.get("ok") for t in msg.get("tools") or [])
    if not (msg and msg["slug"] == slug and msg["owner_id"] == me.actor_id and msg["role"] == "assistant"
            and msg["status"] == "done" and offered):
        return _error(404, "Document not found. Ask the assistant for a download.")
    project = repo.get_project(conn, slug) or {"title": slug}
    tabs = [repo.get_tab(conn, slug, t["key"]) for t in repo.list_tabs(conn, slug)]

    def load_image(src):
        found = ASSET_SRC.search(str(src or ""))
        return repo.get_asset(conn, slug, found.group(1)) if found else None

    now = dt.datetime.now(docx_export.TAIPEI)
    data = docx_export.build(title=project["title"], tabs=[t for t in tabs if t], values=todo.plain_values(conn, slug),
                             image_loader=load_image, base_url=base_url, now=now)
    return 200, {"filename": docx_export.filename(project["title"], now), "data": data}


def state(conn, me, slug):
    problem = _gate(conn, me, slug)
    if problem:
        return problem
    _, knowledge = prompting.load()
    payload = {
        "flags": flags(conn, me, slug),
        "thread": store.thread(conn, slug, me.actor_id),
        "proposals": store.proposals(conn, slug, owner_id=me.actor_id),
        "todo": todo.todo_items(conn, slug, me),
        "criteria": {str(n): v for n, v in prompting.question_criteria(knowledge).items()},
    }
    from project_assistant import agent_registry
    payload['agents'] = agent_registry.roster(conn,me,slug)
    from project_assistant import orchestration_store as db
    payload['active_runs']=db.many(conn,"SELECT jsonb_build_object('id',id,'objective',objective,'status',status) FROM projectops.orchestration_run WHERE project_slug=%s AND created_by=%s AND status IN ('active','awaiting_gate') ORDER BY created_at DESC LIMIT 20",(slug,me.actor_id))
    payload['open_gates']=db.many(conn,"SELECT jsonb_build_object('id',g.id,'run_id',g.run_id,'question',g.question,'gate_kind',g.gate_kind) FROM projectops.orchestration_gate g JOIN projectops.orchestration_run r ON r.id=g.run_id WHERE r.project_slug=%s AND r.created_by=%s AND g.status='open' ORDER BY g.created_at DESC LIMIT 20",(slug,me.actor_id))
    if payload["flags"]["manager"]:  # 負責人：大家私下轉給他、還沒回覆的問題數，頂列數字和側邊欄提示用
        payload["forwards_open"] = len(store.forwards(conn, slug, status="open"))
    from project_assistant import shot_meta
    for proposal in payload["proposals"]:
        if proposal["action"] == "table_edit":
            target = proposal.get("target") or {}
            tab = repo.get_tab(conn, slug, target.get("tab_key"))
            proposal["review"] = target.get("review") or proposal_review.describe(target, tab, partial_allowed=proposal.get("message_id") is not None)
            proposal["review"] = {**proposal["review"], "version": proposal_review.version(target)}
        elif proposal["action"] == shot_meta.ACTION:  # the stage reads the proposed value by shot (SPEC_20 R18)
            proposal["target"] = shot_meta.card_target(proposal.get("target"))
    return 200, payload


def send(conn, me, slug, body,*,source_ref=None):
    problem = _gate(conn, me, slug)
    if problem:
        return problem
    if not isinstance(body,dict):
        return _error(400,"The message must be a JSON object.")
    if source_ref:
        from project_assistant import orchestration_store as db
        prior=db.one(conn,"SELECT id FROM projectops.assistant_message WHERE project_slug=%s AND owner_id=%s AND role='user' AND source_ref=%s",(slug,me.actor_id,source_ref))
        if prior:
            reply=db.one(conn,"SELECT id FROM projectops.assistant_message WHERE reply_to=%s AND role='assistant' ORDER BY id LIMIT 1",(prior,))
            return 200,{'message':store.message(conn,prior),'reply':store.message(conn,reply),'notes':[]}
    raw = str(body.get("text") or "").strip()
    ids = body.get("attachments") or []
    if not isinstance(ids, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        return _error(400, "Invalid attachment format.")
    if len(set(ids)) > attachments.MAX_PER_MESSAGE:
        return _error(400, f"Attach up to {attachments.MAX_PER_MESSAGE} files per message.")
    if not raw and not ids:
        return _error(400, "Enter a message first.")
    if len(raw) > MAX_MESSAGE:
        return _error(400, f"Messages support up to {MAX_MESSAGE} characters.")
    from project_assistant import agent_registry
    try:
        agent_key = agent_registry.resolve_mention(conn,slug,'' if source_ref else raw,body.get('agent_key'))
    except agent_registry.AgentError as exc:
        return _error(exc.status,str(exc))
    with conn.cursor() as cur:
        cur.execute('SELECT actor_id FROM projectops.member WHERE actor_id=%s FOR UPDATE',(me.actor_id,))
    if store.open_reply(conn, slug, me.actor_id,agent_key):
        return _error(409, "This agent is still responding. Wait or choose another agent.")
    files = store.unsent_attachments(conn, slug, me.actor_id, ids)
    if len(files) != len(set(ids)):
        return _error(400, "An attachment is missing or was already sent. Attach it again.")
    text, notes = privacy.text(conn, slug, raw) if raw else ("", [])
    notes = notes + [note for f in files for note in f.get("notes") or []]
    scope = None
    if body.get("scope") is not None:
        try:
            raw_scope = body["scope"]
            tab = repo.get_tab_for_update(conn, slug, raw_scope.get("target_tab")) if isinstance(raw_scope, dict) else None
            if tab:
                tab["key"] = raw_scope["target_tab"]
            scope = request_scope.validate_scope(raw_scope, tab, repo.field_values(conn, slug).get(tab["key"], {}) if tab else {})
        except ValueError as exc:
            return _error(409, str(exc))
    user_id, reply_id = store.add_user_message(conn, slug, me.actor_id, text, notes, agent_key=agent_key,source_ref=source_ref,
                                               **({"request_scope": scope} if scope else {}))
    if files:
        store.bind_attachments(conn, [f["id"] for f in files], user_id)
    return 200, {"message": store.message(conn, user_id), "reply": store.message(conn, reply_id), "notes": notes}


# ---------- 一段一段的對話 ----------

def conversations(conn, me, slug):
    problem = _gate(conn, me, slug)
    if problem:
        return problem
    return 200, {"conversations": store.conversations(conn, slug, me.actor_id)}


def conversation(conn, me, slug, conversation_id):
    problem = _gate(conn, me, slug)
    if problem:
        return problem
    messages = store.conversation_messages(conn, slug, me.actor_id, conversation_id)
    if messages is None:
        return _error(404, "Conversation not found.")
    ids = {m["id"] for m in messages}
    proposals = [p for p in store.proposals(conn, slug, owner_id=me.actor_id, limit=200) if p["message_id"] in ids]
    return 200, {"id": conversation_id, "messages": messages, "proposals": proposals}


def new_conversation(conn, me, slug):
    problem = _gate(conn, me, slug)
    if problem:
        return problem
    if store.open_reply(conn, slug, me.actor_id):
        return _error(409, "Wait for the current response before starting a new conversation.")
    store.new_conversation(conn, slug, me.actor_id)
    return state(conn, me, slug)


def resume_conversation(conn, me, slug, conversation_id):
    problem = _gate(conn, me, slug)
    if problem:
        return problem
    if store.open_reply(conn, slug, me.actor_id):
        return _error(409, "Wait for the current response before switching conversations.")
    if not store.resume_conversation(conn, slug, me.actor_id, conversation_id):
        return _error(404, "Conversation not found.")
    return state(conn, me, slug)


# ---------- 附件 ----------

def upload_attachment(conn, me, slug, data: bytes, content_type: str, filename: str):
    problem = _gate(conn, me, slug)
    if problem:
        return problem
    try:
        row = attachments.process(filename, content_type, data, mask_numbers=privacy.mode(conn, slug) == "mask_numbers")
    except attachments.AttachmentError as exc:
        return _error(exc.status, str(exc))
    attachment_id = store.add_attachment(conn, slug, me.actor_id, **row)
    return 200, {"attachment": store.attachment(conn, attachment_id), "notes": row["notes"]}


def delete_attachment(conn, me, slug, attachment_id):
    problem = _gate(conn, me, slug)
    if problem:
        return problem
    if not store.delete_unsent_attachment(conn, slug, me.actor_id, attachment_id):
        return _error(404, "Attachment not found. Sent attachments cannot be removed.")
    return 200, {"ok": True}


def attachment_file(conn, me, slug, attachment_id, which):
    """縮圖、預覽、原檔：只有上傳的人拿得到。回傳 (200, {"content_type", "data", "name"})。"""

    problem = _gate(conn, me, slug)
    if problem:
        return problem
    found = store.attachment(conn, attachment_id)
    if not found or found["slug"] != slug or found["owner_id"] != me.actor_id:
        return _error(404, "Attachment not found.")
    content = store.attachment_bytes(conn, attachment_id, {"file": "data"}.get(which, which))
    if not content:
        return _error(404, "This attachment version is not available.")
    return 200, {"content_type": content[0], "data": content[1], "name": found["name"]}


# ---------- 提案 ----------

def _admins(conn) -> list[str]:
    return [m["actor_id"] for m in repo.active_members(conn) if m["role"] == "admin"]


def _with_mentions(conn, text: str, target: dict) -> str:
    if not target.get("mention_admin"):
        return text
    tags = " ".join(f"@{{{actor_id}}}" for actor_id in _admins(conn))
    return f"{text}\n{tags}" if tags else text


def _check_sources(conn, slug, target):
    """Pins shared by every non-table action (SPEC_20 R17).

    Reference pages in ``source_revisions`` stay pinned by revision and a ``request_scope`` keeps its
    input fingerprint. The proposal's own page is not pinned as a whole: each action checks its own
    target (a row, an anchor, a field) when it writes. Targets without a page (``tab_key``) are fine.
    Returns an error tuple, or None.
    """
    sources = target.get('source_revisions') or {}
    if not target.get('request_scope') and not sources:
        return None
    own = target.get('tab_key')
    locked = {key: repo.get_tab_for_update(conn, slug, key) for key in sorted(set(sources) | ({own} if own else set()))}
    try:
        if own and not locked[own]:
            raise ValueError("The source page was deleted.")
        if any(not locked[key] or (key != own and locked[key]['revision'] != revision) for key, revision in sources.items()):
            raise ValueError("A reference source changed. Review it again.")
        if target.get('request_scope'):
            if not own:
                raise ValueError("The source page was deleted.")
            request_scope.verify_source(target['request_scope'], {**locked[own], 'key': own}, repo.field_values(conn, slug).get(own, {}))
    except ValueError as exc:
        return _error(409, str(exc))
    return None


def _write(conn, me, slug, proposal, content):
    """Perform one approved proposal as the approving user. Each action pins only its own target.

    ``table_edit`` pins the cells and rows it writes (``table_edits.apply``). Other actions run
    ``_check_sources`` first, then write through the matching service, which checks the target.
    ``shot_meta`` (SPEC_20 R18) is pinned by the revision of the shot field it changes (``shot_meta.write``).
    """
    action, target = proposal["action"], proposal["target"] or {}
    if action == "table_edit":
        return table_edits.apply(conn, me, slug, target)
    problem = _check_sources(conn, slug, target)
    if problem:
        return problem
    if action == "shot_meta":
        from project_assistant import shot_meta
        return shot_meta.write(conn, me, slug, target)
    if action == "私下轉給負責人":
        if not content:
            return _error(400, "The question for the owner is empty.")
        return 200, {"forward_id": store.create_forward(conn, slug, me.actor_id, proposal["id"], content)}
    if action in ("改狀態", "填交接追蹤"):
        if action == "改狀態" and content not in STATUSES:
            return _error(400, "Allowed statuses:" + "、".join(STATUSES))
        return pd_service.set_field(conn, me, slug, {"tab_key": target.get("tab_key"), "field_id": target.get("fid"),
                                                      "value": content})
    request = {"tab_key": target.get("tab_key")}
    if action in ("寫進那一題的討論", "留言問負責人"):
        if not content:
            return _error(400, "The proposed content is empty.")
        request["body"] = _with_mentions(conn, content, target)
        if target.get("rid"):
            request["row"] = target["rid"]
        else:
            request.update({"anchor": target.get("anchor"), "label": "q"})
    elif action == "在段落加標註":
        request.update({"anchor": target.get("anchor"), "label": target.get("label")})
        if content:
            request["body"] = content
    else:
        return _error(400, "Unknown proposal type.")
    return pd_service.create_annotation(conn, me, slug, request)


def _summary(result: dict) -> dict:
    if "shot_meta" in result:
        return result["shot_meta"]
    if result.get("annotation"):
        return {"annotation_id": result["annotation"]["id"], "tab_key": result["annotation"].get("tab_key")}
    if "forward_id" in result:
        return {"forward_id": result["forward_id"]}
    return {"value": result.get("value")}


def _own_pending(conn, me, slug, proposal_id):
    from project_assistant import orchestrator as cp,orchestration_store as db
    bound=db.one(conn,'''SELECT to_jsonb(d) FROM projectops.orchestration_dispatch d
        JOIN projectops.assistant_proposal p ON p.dispatch_id=d.id WHERE p.id=%s''',(proposal_id,))
    if bound:
        if bound['project_slug']!=slug:
            return None,_error(404,"Proposal not found.")
        cp.lock_project(conn,slug)
        try:
            run=cp.own_run(conn,me,slug,bound['run_id'],lock=True)
        except cp.OrchestrationError as exc:
            return None,_error(exc.status,str(exc))
        if bound['superseded_by'] or bound['status'] in ('canceled','failed','timeout') or run['status']=='canceled' or cp.instant(bound['deadline_at'])<=cp.now():
            return None,_error(409,"This proposal’s dispatch was canceled, expired, or reassigned.")
        if bound['status']!='awaiting_gate' or db.one(conn,"SELECT id FROM projectops.orchestration_gate WHERE dispatch_id=%s AND gate_kind='question' AND status='open'",(bound['id'],)):
            return None,_error(409,"The agent has not completed all outputs. Resolve open decisions or wait for completion.")
    # Scheduler lock order: run, proposal, then target tab.
    with conn.cursor() as cur:
        cur.execute("SELECT run_id FROM projectops.limb_task WHERE proposal_id=%s", (proposal_id,))
        row = cur.fetchone()
        if row:
            cur.execute("SELECT id FROM projectops.flow_run WHERE id=%s FOR UPDATE", (row[0],))
    proposal = store.proposal(conn, proposal_id, for_update=True)
    if not proposal or proposal["slug"] != slug or proposal["owner_id"] != me.actor_id:
        return None, _error(404, "Proposal not found.")
    if proposal["status"] != "pending":
        return None, _error(409, "This proposal has already been handled.")
    if proposal["action"] == "shot_meta" and not me.can_write:  # SPEC_20 R18: a viewer sees it on the stage, read-only
        return None, _error(403, "Read-only crew members cannot modify a production.")
    proposal["_flow_bound"] = bool(row)
    proposal['_orchestration_bound']=bool(bound)
    return proposal, None


def apply_proposal(conn, me, slug, proposal_id, body,*,_race_task_id=None):
    problem = _gate(conn, me, slug)
    if problem:
        return problem
    proposal, problem = _own_pending(conn, me, slug, proposal_id)
    if problem:
        return problem
    if proposal.get('race_group_task_id') and proposal['race_group_task_id']!=_race_task_id:
        return _error(409,"Select a version through candidate comparison; candidates cannot be applied individually.")
    if proposal.get('dispatch_id'):
        from project_assistant import orchestration_store,story_media_adapter
        dispatch=orchestration_store.get_dispatch(conn,slug,proposal['dispatch_id'])
        if dispatch and dispatch['profile_snapshot'].get('runtime_kind')=='server_media':
            try:
                story_media_adapter.verify_task(conn,orchestration_store.get_task(conn,slug,dispatch['task_id']))
            except ValueError:
                return _error(409,"The media source or production policy changed; create a new allocation.")
    content, notes = proposal["content"], []
    if "content" in body:
        edited = str(body.get("content") or "").strip()
        if edited != proposal["content"]:
            if proposal["action"] == "table_edit":
                return _error(400, "Regenerate this table proposal; editing preview text alone is not supported.")
            if proposal["action"] == "shot_meta":
                from project_assistant import shot_meta
                return _error(400, shot_meta.NOT_EDITABLE)
            content, notes = privacy.text(conn, slug, edited)
    remaining = None
    original = proposal
    if "groups" in body:
        if proposal["action"] != "table_edit" or proposal.get("_flow_bound") or proposal.get('_orchestration_bound') or proposal.get("message_id") is None:
            return _error(400, "These outputs must be reviewed and applied together.")
        if body.get("review_version") != proposal_review.version(proposal["target"]):
            return 409, {"error": "The proposal changed. Review the current change list before applying it.", "proposal": proposal}
        try:
            selected = body["groups"]
            target = proposal_review.select_target(proposal["target"], selected)
            rest = [i for i in range(len(proposal["target"]["ops"])) if i not in selected]
            remaining = proposal_review.select_target(proposal["target"], rest) if rest else None
            proposal = {**proposal, "target": target}
        except ValueError as exc:
            return _error(400, str(exc))
    source_key=(proposal.get('target') or {}).get('tab_key')
    source_before=repo.get_tab_for_update(conn,slug,source_key) if source_key else None
    if source_before:
        source_before={**source_before,'key':source_key,'values':repo.field_values(conn,slug).get(source_key,{})}
    status, result = _write(conn, me, slug, proposal, content)
    if status == 409 and (not proposal.get("_flow_bound") or proposal.get('_orchestration_bound')):
        # The HTTP layer rolls back rejected writes. Keep this conflict explicit
        # in the response; the existing pending proposal remains untouched.
        return status, {**result, "proposal": original}
    if status < 400 and remaining:
        tab = repo.get_tab(conn, slug, remaining["tab_key"])
        if remaining.get("request_scope"):
            remaining["request_scope"] = request_scope.validate_scope(
                {**remaining["request_scope"], "base_revision": tab["revision"]}, tab,
                repo.field_values(conn, slug).get(tab["key"], {}))
        remaining["source_revision"] = tab["revision"]
        remaining["review"] = proposal_review.describe(remaining, tab, partial_allowed=True)
        preview = "\n".join(f"{g['label']} / {c['column']}：{c['before']} → {c['after']}" for g in remaining["review"]["groups"] for c in g["changes"])
        store.revise_pending_proposal(conn, proposal_id, remaining, preview)
        repo.add_audit(conn, slug, action="assistant_apply", actor_id=me.actor_id, tab_key=remaining["tab_key"],
                       target=str(proposal_id), detail={"via": "assistant", "groups": body["groups"], "partial": True})
        return 200, {"proposal": store.proposal(conn, proposal_id), "notes": ["已套用選取修改，其餘項目保留待核對"], "partial": True}
    if status >= 400:
        store.decide_proposal(conn, proposal_id, status="failed", by=me.actor_id, content=content,
                              error=(result or {}).get("error") or "沒放上去")
    else:
        store.decide_proposal(conn, proposal_id, status="applied", by=me.actor_id, content=content,
                              result=_summary(result))
        target = proposal["target"] or {}
        repo.add_audit(conn, slug, action="assistant_apply", actor_id=me.actor_id, tab_key=target.get("tab_key"),
                       target=str(proposal_id), detail={"via": "assistant", "action": proposal["action"],
                                                        "display": target.get("display"), "content": content[:500]})
    from project_assistant.flow_runner import proposal_decided
    proposal_decided(conn, proposal_id, status < 400)
    from project_assistant.orchestrator import on_proposal_decided
    on_proposal_decided(conn,proposal_id,status<400,source_before=source_before)
    return 200, {"proposal": store.proposal(conn, proposal_id), "notes": notes}


def dismiss_proposal(conn, me, slug, proposal_id):
    problem = _gate(conn, me, slug)
    if problem:
        return problem
    proposal, problem = _own_pending(conn, me, slug, proposal_id)
    if problem:
        return problem
    if proposal.get('race_group_task_id'):
        return _error(409,"Select a version through candidate comparison or cancel the whole batch.")
    store.decide_proposal(conn, proposal["id"], status="dismissed", by=me.actor_id)
    from project_assistant.flow_runner import proposal_decided
    proposal_decided(conn, proposal["id"], False)
    from project_assistant.orchestrator import on_proposal_decided
    on_proposal_decided(conn,proposal['id'],False)
    return 200, {"proposal": store.proposal(conn, proposal["id"]), "notes": []}


def shot_proposals(conn, me, slug, shot_id):
    """My pending shot_meta proposals for one shot, with the proposed values (SPEC_20 R18, decision 5)."""
    problem = _gate(conn, me, slug)
    if problem:
        return problem
    from project_assistant import shot_meta
    return shot_meta.listing(conn, me, slug, shot_id)


def attach_shot_solution(conn, me, slug, proposal_id, body):
    """The 3D Stage's solve of an operations-only 3D plan proposal, attached before approval (SPEC_20 R27)."""
    problem = _gate(conn, me, slug)
    if problem:
        return problem
    from project_assistant import previs_ops
    return previs_ops.attach_solution(conn, me, slug, proposal_id, body)


# ---------- 管理視角 ----------

def manager(conn, me, slug):
    problem = _manager_gate(me, slug)
    if problem:
        return problem
    names = repo.member_names(conn)
    flags_by_actor = store.member_flags(conn, slug)
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)
    status_raw = store.get_setting(conn, slug, "report_status")
    forwards = [dict(f, owner_name=names.get(f["owner_id"], "")) for f in store.forwards(conn, slug)]
    # 「經助理放上專案頁的」：私下轉給負責人的沒有放上專案頁，只列在上面的「私下轉給你的問題」
    applied = [dict(p, owner_name=names.get(p["owner_id"], "")) for p in store.proposals(conn, slug, status="applied",
                                                                                         limit=30)
               if p["action"] != "私下轉給負責人"]
    members = [{"actor_id": m["actor_id"], "name": m["name"], "role": m["role"],
                "role_label": pd_service.ROLE_LABEL.get(m["role"], "行銷"),
                "enabled": bool(flags_by_actor.get(m["actor_id"]))}
               for m in repo.active_members(conn) if m["role"] != "admin"]
    return 200, {
        "notes": store.notes(conn, slug),
        "forwards": forwards,
        "applied": applied,
        "stats": store.stats(conn, slug, since),
        "codex": store.codex_versions(conn, slug),
        "members": members,
        "report": {"source": store.get_setting(conn, slug, "report_source"),
                   "status": json.loads(status_raw) if status_raw else None},
    }


def add_note(conn, me, slug, body):
    problem = _manager_gate(me, slug)
    if problem:
        return problem
    text = str(body.get("body") or "").strip()
    if not text:
        return _error(400, "The assignment is empty.")
    if len(text) > MAX_NOTE:
        return _error(400, f"Assignments support up to {MAX_NOTE} characters.")
    target = str(body.get("target_id") or "") or None
    if target and not any(m["actor_id"] == target and m["role"] != "admin" for m in repo.active_members(conn)):
        return _error(404, "This person is not on the crew.")
    store.add_note(conn, slug, me.actor_id, text, target_id=target)
    return 200, {"notes": store.notes(conn, slug)}


def finish_note(conn, me, slug, note_id):
    problem = _manager_gate(me, slug)
    if problem:
        return problem
    if not any(n["id"] == note_id for n in store.notes(conn, slug)):
        return _error(404, "Assignment not found.")
    store.set_note_status(conn, note_id, "done")
    return 200, {"notes": store.notes(conn, slug)}


def answer_forward(conn, me, slug, forward_id, body):
    problem = _manager_gate(me, slug)
    if problem:
        return problem
    text = str(body.get("answer") or "").strip()
    if not text:
        return _error(400, "The reply is empty.")
    if len(text) > MAX_MESSAGE:
        return _error(400, f"Messages support up to {MAX_MESSAGE} characters.")
    current = next((f for f in store.forwards(conn, slug) if f["id"] == forward_id), None)
    if not current:
        return _error(404, "Question not found.")
    if current["status"] == "answered":
        return _error(409, "This question already has a reply.")
    answered = store.answer_forward(conn, forward_id, me.actor_id, text)
    store.add_lead_message(conn, slug, answered["owner_id"], f"關於你私下問的「{answered['question'][:40]}」：\n{text}")
    return manager(conn, me, slug)


def set_member(conn, me, slug, body):
    problem = _manager_gate(me, slug)
    if problem:
        return problem
    actor_id = str(body.get("actor_id") or "")
    member = next((m for m in repo.active_members(conn) if m["actor_id"] == actor_id), None)
    if not member or member["role"] == "admin":
        return _error(404, "This person is not on the crew.")
    enabled = bool(body.get("enabled"))
    store.set_member_enabled(conn, slug, actor_id, enabled, me.actor_id)
    repo.add_audit(conn, slug, action="assistant_member", actor_id=me.actor_id, target=actor_id,
                   detail={"enabled": enabled})
    return manager(conn, me, slug)


def set_report_source(conn, me, slug, body):
    problem = _manager_gate(me, slug)
    if problem:
        return problem
    path = str(body.get("report_source") or "").strip()
    if not WINDOWS_PATH.match(path):
        return _error(400, "Enter an absolute folder path, for example C:\\Projects\\Reports.")
    store.set_setting(conn, slug, "report_source", path)
    repo.add_audit(conn, slug, action="assistant_setting", actor_id=me.actor_id, target="report_source",
                   detail={"value": path})
    return manager(conn, me, slug)
