"""專案助理的資料庫存取。每個函式拿一條連線，commit／rollback 由呼叫端決定。

對話表同時是工作佇列：Mia每送一句，就多一列她的話（done）和一列待回答（role=assistant、queued）。
worker 用租約領待回答那一列；租約過期沒做完會被重新領，同一輪最多試 MAX_ATTEMPTS 次。
"""
from __future__ import annotations

import json

MAX_ATTEMPTS = 2


def _iso(value):
    return value.isoformat() if value is not None else None


def _loads(value):
    return json.loads(value) if isinstance(value, (str, bytes)) else value


def _dicts(cursor) -> list[dict]:
    names = [d.name for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _clean(row: dict | None) -> dict | None:
    if row is None:
        return None
    out = {}
    for key, value in row.items():
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        elif key in ("tools", "notes", "target", "result", "request_scope"):
            value = _loads(value)
        elif key in ("owner_id", "author_id", "target_id", "actor_id", "decided_by", "answered_by", "updated_by"):
            value = str(value) if value is not None else None  # UUID → 字串；message_id、proposal_id 維持整數
        elif key == "seconds" and value is not None:
            value = float(value)
        out[key] = value
    return out


# ---------- 成員 ----------

def is_member_enabled(conn, slug: str, actor_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT enabled FROM projectops.assistant_member WHERE project_slug = %s AND actor_id = %s",
                    (slug, actor_id))
        row = cur.fetchone()
        return True if row is None else bool(row[0])


def set_member_enabled(conn, slug: str, actor_id: str, enabled: bool, by: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO projectops.assistant_member (project_slug, actor_id, enabled, updated_by)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (project_slug, actor_id)
               DO UPDATE SET enabled = EXCLUDED.enabled, updated_by = EXCLUDED.updated_by, updated_at = NOW()""",
            (slug, actor_id, bool(enabled), by),
        )


def member_flags(conn, slug: str) -> dict[str, bool]:
    with conn.cursor() as cur:
        cur.execute("SELECT actor_id::text, enabled FROM projectops.assistant_member WHERE project_slug = %s", (slug,))
        return {r[0]: bool(r[1]) for r in cur.fetchall()}


# ---------- 對話與租約 ----------

MESSAGE_COLUMNS = """id, project_slug AS slug, owner_id, role, body, status, reply_to, attempts, lease_owner,
    error_kind, seconds, tools, notes, model, codex_version, created_at, finished_at, conversation_id, request_scope,
    agent_key, agent_snapshot, lease_until, source_ref"""


# ---------- 一段一段的對話 ----------
# 「目前這段」是 active_at 最新的那段：開新對話、接著舊的聊都會把那段的 active_at 設成現在。
# 用 clock_timestamp() 不用 NOW()：同一個交易裡先接舊的、再開新的，也要分得出先後。

def current_conversation(conn, slug: str, owner_id: str, *, create: bool = True) -> int | None:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id FROM projectops.assistant_conversation WHERE project_slug = %s AND owner_id = %s
               ORDER BY active_at DESC, id DESC LIMIT 1""",
            (slug, owner_id),
        )
        row = cur.fetchone()
        if row or not create:
            return row[0] if row else None
        cur.execute("""INSERT INTO projectops.assistant_conversation (project_slug, owner_id, active_at)
                       VALUES (%s, %s, clock_timestamp()) RETURNING id""", (slug, owner_id))
        return cur.fetchone()[0]


def new_conversation(conn, slug: str, owner_id: str) -> int:
    """開一段新的；目前這段還是空的就直接沿用（一直按「新對話」不會留下一堆空的）。"""

    current = current_conversation(conn, slug, owner_id, create=False)
    with conn.cursor() as cur:
        if current is not None:
            cur.execute("SELECT 1 FROM projectops.assistant_message WHERE conversation_id = %s LIMIT 1", (current,))
            if cur.fetchone() is None:
                cur.execute("UPDATE projectops.assistant_conversation SET active_at = clock_timestamp() WHERE id = %s",
                            (current,))
                return current
        cur.execute("""INSERT INTO projectops.assistant_conversation (project_slug, owner_id, active_at)
                       VALUES (%s, %s, clock_timestamp()) RETURNING id""", (slug, owner_id))
        return cur.fetchone()[0]


def resume_conversation(conn, slug: str, owner_id: str, conversation_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE projectops.assistant_conversation SET active_at = clock_timestamp()
               WHERE id = %s AND project_slug = %s AND owner_id = %s RETURNING id""",
            (conversation_id, slug, owner_id),
        )
        return cur.fetchone() is not None


def conversations(conn, slug: str, owner_id: str, limit: int = 60) -> list[dict]:
    """這個人的每一段對話：目前這段排第一，其他照最後說話的時間。空的只留目前這段。"""

    current = current_conversation(conn, slug, owner_id, create=False)
    with conn.cursor() as cur:
        cur.execute(
            """SELECT c.id, c.created_at, c.active_at,
                      (SELECT COALESCE(NULLIF(m.body, ''), '（附檔）' || (
                                SELECT string_agg(a.name, '、' ORDER BY a.id) FROM projectops.assistant_attachment a
                                 WHERE a.message_id = m.id))
                         FROM projectops.assistant_message m
                        WHERE m.conversation_id = c.id AND m.role = 'user' ORDER BY m.id LIMIT 1) AS first_text,
                      (SELECT count(*) FROM projectops.assistant_message m
                        WHERE m.conversation_id = c.id AND m.status = 'done') AS messages,
                      (SELECT max(m.created_at) FROM projectops.assistant_message m
                        WHERE m.conversation_id = c.id) AS last_at
                 FROM projectops.assistant_conversation c
                WHERE c.project_slug = %s AND c.owner_id = %s
                ORDER BY c.active_at DESC, c.id DESC LIMIT %s""",
            (slug, owner_id, limit),
        )
        rows = [_clean(r) for r in _dicts(cur)]
    for row in rows:
        row["current"] = row["id"] == current
        row["first_text"] = row["first_text"] or ""
    head = [r for r in rows if r["current"]]
    rest = sorted((r for r in rows if not r["current"] and r["messages"]),
                  key=lambda r: r["last_at"] or r["created_at"], reverse=True)
    return head + rest


def conversation_messages(conn, slug: str, owner_id: str, conversation_id: int, limit: int = 200) -> list[dict] | None:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM projectops.assistant_conversation WHERE id = %s AND project_slug = %s AND owner_id = %s",
                    (conversation_id, slug, owner_id))
        if cur.fetchone() is None:
            return None
        cur.execute(
            f"""SELECT {MESSAGE_COLUMNS} FROM projectops.assistant_message
                WHERE conversation_id = %s ORDER BY id DESC LIMIT %s""",
            (conversation_id, limit),
        )
        rows = [_clean(r) for r in reversed(_dicts(cur))]
    return _with_attachments(conn, rows)


def add_user_message(conn, slug: str, owner_id: str, body: str, notes: list[str], request_scope=None, *, agent_key='coordinator',source_ref=None) -> tuple[int, int]:
    from project_assistant import agent_registry
    profile = agent_registry.get_agent(conn,slug,agent_key)
    snapshot = {k:v for k,v in (profile or {}).items() if k not in ('created_by','created_at','updated_at')}
    conversation = current_conversation(conn, slug, owner_id)
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO projectops.assistant_message (project_slug, owner_id, role, body, status, notes, conversation_id, request_scope,agent_key,source_ref)
               VALUES (%s, %s, 'user', %s, 'done', %s::jsonb, %s, %s::jsonb,%s,%s) RETURNING id""",
            (slug, owner_id, body, json.dumps(notes or [], ensure_ascii=False), conversation, json.dumps(request_scope, ensure_ascii=False),agent_key,source_ref),
        )
        user_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO projectops.assistant_message (project_slug, owner_id, role, status, reply_to, conversation_id,agent_key,agent_snapshot)
               VALUES (%s, %s, 'assistant', 'queued', %s, %s,%s,%s::jsonb) RETURNING id""",
            (slug, owner_id, user_id, conversation,agent_key,json.dumps(snapshot,ensure_ascii=False)),
        )
        return user_id, cur.fetchone()[0]


def add_lead_message(conn, slug: str, owner_id: str, body: str) -> int:
    """負責人的回覆放進那個人目前這段，她打開就看得到。"""

    conversation = current_conversation(conn, slug, owner_id)
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO projectops.assistant_message (project_slug, owner_id, role, body, status, finished_at,
                                                         conversation_id)
               VALUES (%s, %s, 'lead', %s, 'done', NOW(), %s) RETURNING id""",
            (slug, owner_id, body, conversation),
        )
        return cur.fetchone()[0]


def open_reply(conn, slug: str, owner_id: str, agent_key=None) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT {MESSAGE_COLUMNS} FROM projectops.assistant_message
                WHERE project_slug = %s AND owner_id = %s AND role = 'assistant' AND status IN ('queued', 'running')
                  AND (%s::text IS NULL OR agent_key=%s)
                ORDER BY id DESC LIMIT 1""",
            (slug, owner_id,agent_key,agent_key),
        )
        rows = _dicts(cur)
        return _clean(rows[0]) if rows else None


def _abandon_expired(cur) -> None:
    cur.execute(
        """UPDATE projectops.assistant_message
           SET status = 'failed', error_kind = 'abandoned', lease_owner = NULL, lease_until = NULL,
               body = '這次沒答完，請再送一次；一直這樣的話，請直接留言給負責人。', finished_at = NOW()
           WHERE role = 'assistant' AND status = 'running' AND lease_until < NOW() AND attempts >= %s""",
        (MAX_ATTEMPTS,),
    )


def claim_next(conn, worker: str, lease_seconds: int) -> dict | None:
    from project_assistant import orchestrator as cp,orchestration_store as db,agent_registry
    import uuid
    candidates=db.many(conn,'''SELECT to_jsonb(m) FROM projectops.assistant_message m WHERE role='assistant'
        AND attempts<%s AND (status='queued' OR (status='running' AND lease_until<NOW())) ORDER BY project_slug,id LIMIT 100''',(MAX_ATTEMPTS,))
    for candidate in candidates:
        slug=candidate['project_slug']
        if not db.one(conn,'SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0))',('openbench-orchestration:'+slug,)):
            continue
        profile=agent_registry.get_agent(conn,slug,candidate['agent_key'])
        if not profile or not profile['enabled'] or profile['role_kind']=='observer':
            db.execute(conn,"UPDATE projectops.assistant_message SET status='failed',error_kind='not_member',body='此代理已停用。',finished_at=NOW(),lease_owner=NULL,lease_until=NULL WHERE id=%s",(candidate['id'],))
            continue
        active=db.one(conn,"SELECT count(*) FROM projectops.assistant_message WHERE project_slug=%s AND agent_key=%s AND role='assistant' AND status='running' AND lease_until>NOW()",(slug,candidate['agent_key']))
        active+=db.one(conn,"SELECT count(*) FROM projectops.orchestration_dispatch WHERE project_slug=%s AND agent_key=%s AND status='running' AND lease_until>NOW()",(slug,candidate['agent_key']))
        if active>=profile['max_concurrency']:
            continue
        lease_owner=worker+':'+uuid.uuid4().hex[:16]
        claimed=db.one(conn,'''WITH next AS (SELECT id FROM projectops.assistant_message
            WHERE id=%s AND attempts<%s AND (status='queued' OR (status='running' AND lease_until<NOW())) FOR UPDATE SKIP LOCKED)
            UPDATE projectops.assistant_message m SET status='running',attempts=m.attempts+1,lease_owner=%s,
            lease_until=NOW()+make_interval(secs=>%s),error_kind=NULL,body=''
            FROM next WHERE m.id=next.id RETURNING to_jsonb(m)''',(candidate['id'],MAX_ATTEMPTS,lease_owner,lease_seconds))
        if claimed:
            return {'id':claimed['id'],'slug':slug,'owner_id':claimed['owner_id'],'reply_to':claimed['reply_to'],
                    'attempts':claimed['attempts'],'agent_key':claimed['agent_key'],'agent_snapshot':claimed['agent_snapshot'],
                    'lease_owner':lease_owner}
    # Exhausted leases cannot remain visible as permanently running answers.
    with conn.cursor() as cur:
        _abandon_expired(cur)
    return None


def renew(conn, message_id: int, worker: str, lease_seconds: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE projectops.assistant_message SET lease_until = NOW() + make_interval(secs => %s)
               WHERE id = %s AND lease_owner = %s AND status = 'running' RETURNING id""",
            (lease_seconds, message_id, worker),
        )
        return cur.fetchone() is not None


def write_partial(conn, message_id: int, worker: str, body: str) -> bool:
    """邊寫邊顯示：回答還在寫的時候，把目前寫到的字存進去；只有拿著租約、還在跑的那一個寫得進去。"""

    with conn.cursor() as cur:
        cur.execute(
            """UPDATE projectops.assistant_message SET body = %s
               WHERE id = %s AND lease_owner = %s AND status = 'running' RETURNING id""",
            (body, message_id, worker),
        )
        return cur.fetchone() is not None


def append_tool(conn, message_id: int, entry: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE projectops.assistant_message SET tools = tools || jsonb_build_array(%s::jsonb)
               WHERE id = %s AND status = 'running'""",
            (json.dumps(entry, ensure_ascii=False), message_id),
        )


def finish(conn, message_id: int, worker: str, *, body: str, seconds: float, model: str, codex_version: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE projectops.assistant_message
               SET status = 'done', body = %s, seconds = %s, model = %s, codex_version = %s, finished_at = NOW(),
                   lease_owner = NULL, lease_until = NULL, error_kind = NULL
               WHERE id = %s AND lease_owner = %s AND status = 'running' RETURNING id""",
            (body, round(float(seconds), 1), model, codex_version, message_id, worker),
        )
        return cur.fetchone() is not None


def fail(conn, message_id: int, worker: str, *, kind: str, body: str, retry: bool) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT attempts FROM projectops.assistant_message WHERE id = %s AND lease_owner = %s",
                    (message_id, worker))
        row = cur.fetchone()
        if not row:
            return "lost"
        if retry and row[0] < MAX_ATTEMPTS:
            cur.execute(
                """UPDATE projectops.assistant_message
                   SET status = 'queued', error_kind = %s, lease_owner = NULL, lease_until = NULL, tools = '[]'::jsonb,
                       body = ''
                   WHERE id = %s""",
                (kind, message_id),
            )
            return "queued"
        cur.execute(
            """UPDATE projectops.assistant_message
               SET status = 'failed', error_kind = %s, body = %s, lease_owner = NULL, lease_until = NULL,
                   finished_at = NOW()
               WHERE id = %s""",
            (kind, body, message_id),
        )
        return "failed"


def message(conn, message_id: int) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(f"SELECT {MESSAGE_COLUMNS} FROM projectops.assistant_message WHERE id = %s", (message_id,))
        rows = _dicts(cur)
        return _clean(rows[0]) if rows else None


def thread(conn, slug: str, owner_id: str, limit: int = 60) -> list[dict]:
    """目前這段對話。"""

    conversation = current_conversation(conn, slug, owner_id, create=False)
    if conversation is None:
        return []
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT {MESSAGE_COLUMNS} FROM projectops.assistant_message
                WHERE conversation_id = %s ORDER BY id DESC LIMIT %s""",
            (conversation, limit),
        )
        rows = [_clean(r) for r in reversed(_dicts(cur))]
    return _with_attachments(conn, rows)


def history(conn, slug: str, owner_id: str, before_id: int, turns: int = 12) -> list[dict]:
    """給提示用的先前對話：只有 before_id 那一句所在的這段；附過的檔案只留檔名。"""

    with conn.cursor() as cur:
        cur.execute(
            """SELECT m.role, m.body,
                      COALESCE((SELECT array_agg(a.name ORDER BY a.id) FROM projectops.assistant_attachment a
                                 WHERE a.message_id = m.id), ARRAY[]::text[]) AS files
                 FROM projectops.assistant_message m
                WHERE m.project_slug = %s AND m.owner_id = %s AND m.id < %s AND m.status = 'done'
                  AND m.conversation_id = (SELECT conversation_id FROM projectops.assistant_message WHERE id = %s)
                  AND (m.body <> '' OR EXISTS (SELECT 1 FROM projectops.assistant_attachment a WHERE a.message_id = m.id))
                ORDER BY m.id DESC LIMIT %s""",
            (slug, owner_id, before_id, before_id, turns * 2 + 4),
        )
        return [{"role": r[0], "body": r[1], "files": list(r[2] or [])} for r in reversed(cur.fetchall())]


# ---------- 附件 ----------

ATTACHMENT_COLUMNS = """id, project_slug AS slug, owner_id, message_id, kind, name, content_type, byte_size, notes,
    created_at, (thumb IS NOT NULL) AS has_thumb"""
BYTES_COLUMNS = {"data": "content_type", "thumb": "'image/webp'", "preview": "'image/webp'"}


def add_attachment(conn, slug: str, owner_id: str, *, kind: str, name: str, content_type: str, data: bytes,
                   thumb, preview, extracted: str, notes: list[str]) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO projectops.assistant_attachment
                 (project_slug, owner_id, kind, name, content_type, byte_size, data, thumb, preview, extracted, notes)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb) RETURNING id""",
            (slug, owner_id, kind, name, content_type, len(data), data, thumb, preview, extracted,
             json.dumps(notes or [], ensure_ascii=False)),
        )
        return cur.fetchone()[0]


def attachment(conn, attachment_id: int) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(f"SELECT {ATTACHMENT_COLUMNS} FROM projectops.assistant_attachment WHERE id = %s", (attachment_id,))
        rows = _dicts(cur)
        return _clean(rows[0]) if rows else None


def attachment_bytes(conn, attachment_id: int, which: str) -> tuple[str, bytes] | None:
    if which not in BYTES_COLUMNS:
        raise ValueError(which)
    with conn.cursor() as cur:
        cur.execute(f"SELECT {BYTES_COLUMNS[which]}, {which} FROM projectops.assistant_attachment WHERE id = %s",
                    (attachment_id,))
        row = cur.fetchone()
        if not row or row[1] is None:
            return None
        return row[0], bytes(row[1])


def unsent_attachments(conn, slug: str, owner_id: str, ids) -> list[dict]:
    ids = [int(i) for i in ids]
    if not ids:
        return []
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT {ATTACHMENT_COLUMNS} FROM projectops.assistant_attachment
                WHERE id = ANY(%s) AND project_slug = %s AND owner_id = %s AND message_id IS NULL ORDER BY id""",
            (ids, slug, owner_id),
        )
        return [_clean(r) for r in _dicts(cur)]


def bind_attachments(conn, ids, message_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE projectops.assistant_attachment SET message_id = %s WHERE id = ANY(%s) AND message_id IS NULL",
                    (message_id, [int(i) for i in ids]))


def delete_unsent_attachment(conn, slug: str, owner_id: str, attachment_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """DELETE FROM projectops.assistant_attachment
               WHERE id = %s AND project_slug = %s AND owner_id = %s AND message_id IS NULL RETURNING id""",
            (attachment_id, slug, owner_id),
        )
        return cur.fetchone() is not None


def message_attachments(conn, message_ids) -> dict[int, list[dict]]:
    ids = [int(i) for i in message_ids]
    if not ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(f"""SELECT {ATTACHMENT_COLUMNS} FROM projectops.assistant_attachment
                        WHERE message_id = ANY(%s) ORDER BY id""", (ids,))
        out: dict[int, list[dict]] = {}
        for row in _dicts(cur):
            out.setdefault(row["message_id"], []).append(_clean(row))
        return out


def turn_attachments(conn, message_id: int) -> list[dict]:
    """worker 用：這一句附的檔案，給助理的文字和圖片（預覽那張）。"""

    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, kind, name, extracted, notes, preview FROM projectops.assistant_attachment
               WHERE message_id = %s ORDER BY id""",
            (message_id,),
        )
        return [{"id": r[0], "kind": r[1], "name": r[2], "extracted": r[3], "notes": _loads(r[4]) or [],
                 "preview": bytes(r[5]) if r[5] is not None else None} for r in cur.fetchall()]


def _with_attachments(conn, rows: list[dict]) -> list[dict]:
    found = message_attachments(conn, [r["id"] for r in rows if r["role"] == "user"])
    for row in rows:
        row["attachments"] = found.get(row["id"], [])
    return rows


# ---------- 提案 ----------

PROPOSAL_COLUMNS = """id, project_slug AS slug, owner_id, message_id, action, target, content, status, result, error,
    created_at, decided_at, decided_by, agent_key, dispatch_id::text, race_group_task_id::text"""


def revise_pending_proposal(conn, proposal_id, target, content, error=None):
    with conn.cursor() as cur:
        cur.execute("""UPDATE projectops.assistant_proposal SET target=%s::jsonb, content=%s, error=%s
                       WHERE id=%s AND status='pending'""", (json.dumps(target, ensure_ascii=False), content, error, proposal_id))


def create_proposal(conn, slug: str, owner_id: str, message_id, action: str, target: dict, content: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO projectops.assistant_proposal (project_slug, owner_id, message_id, action, target, content,agent_key)
               VALUES (%s, %s, %s, %s, %s::jsonb, %s,(SELECT agent_key FROM projectops.assistant_message WHERE id=%s)) RETURNING id""",
            (slug, owner_id, message_id, action, json.dumps(target, ensure_ascii=False), content,message_id),
        )
        return cur.fetchone()[0]


def proposal(conn, proposal_id: int, *, for_update=False) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(f"SELECT {PROPOSAL_COLUMNS} FROM projectops.assistant_proposal WHERE id = %s" + (" FOR UPDATE" if for_update else ""), (proposal_id,))
        rows = _dicts(cur)
        return _clean(rows[0]) if rows else None


def proposals(conn, slug: str, *, owner_id=None, status=None, limit: int = 50) -> list[dict]:
    where, args = ["project_slug = %s"], [slug]
    if owner_id:
        where.append("owner_id = %s")
        args.append(owner_id)
    if status:
        where.append("status = %s")
        args.append(status)
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT {PROPOSAL_COLUMNS} FROM projectops.assistant_proposal WHERE {' AND '.join(where)}
                ORDER BY id DESC LIMIT %s""",
            (*args, limit),
        )
        return [_clean(r) for r in reversed(_dicts(cur))]


def decide_proposal(conn, proposal_id: int, *, status: str, by: str, content=None, result=None, error=None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE projectops.assistant_proposal
               SET status = %s, decided_by = %s, decided_at = NOW(), content = COALESCE(%s, content),
                   result = %s::jsonb, error = %s
               WHERE id = %s""",
            (status, by, content, json.dumps(result, ensure_ascii=False) if result is not None else None, error,
             proposal_id),
        )


# ---------- 負責人交代、私下轉問 ----------

def add_note(conn, slug: str, author_id: str, body: str, target_id=None) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO projectops.assistant_note (project_slug, author_id, target_id, body)
               VALUES (%s, %s, %s, %s) RETURNING id""",
            (slug, author_id, target_id, body),
        )
        return cur.fetchone()[0]


def notes(conn, slug: str, status=None) -> list[dict]:
    with conn.cursor() as cur:
        if status:
            cur.execute("""SELECT id, author_id, target_id, body, status, created_at, done_at FROM projectops.assistant_note
                           WHERE project_slug = %s AND status = %s ORDER BY id""", (slug, status))
        else:
            cur.execute("""SELECT id, author_id, target_id, body, status, created_at, done_at FROM projectops.assistant_note
                           WHERE project_slug = %s ORDER BY id""", (slug,))
        return [_clean(r) for r in _dicts(cur)]


def set_note_status(conn, note_id: int, status: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE projectops.assistant_note SET status = %s,
                   done_at = CASE WHEN %s = 'done' THEN NOW() ELSE NULL END WHERE id = %s""",
            (status, status, note_id),
        )


FORWARD_COLUMNS = "id, project_slug AS slug, owner_id, proposal_id, question, status, answer, answered_by, answered_at, created_at"


def create_forward(conn, slug: str, owner_id: str, proposal_id, question: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO projectops.assistant_forward (project_slug, owner_id, proposal_id, question)
               VALUES (%s, %s, %s, %s) RETURNING id""",
            (slug, owner_id, proposal_id, question),
        )
        return cur.fetchone()[0]


def forwards(conn, slug: str, *, owner_id=None, status=None) -> list[dict]:
    where, args = ["project_slug = %s"], [slug]
    if owner_id:
        where.append("owner_id = %s")
        args.append(owner_id)
    if status:
        where.append("status = %s")
        args.append(status)
    with conn.cursor() as cur:
        cur.execute(f"SELECT {FORWARD_COLUMNS} FROM projectops.assistant_forward WHERE {' AND '.join(where)} ORDER BY id",
                    args)
        return [_clean(r) for r in _dicts(cur)]


def answer_forward(conn, forward_id: int, by: str, answer: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            f"""UPDATE projectops.assistant_forward
                SET status = 'answered', answer = %s, answered_by = %s, answered_at = NOW()
                WHERE id = %s RETURNING {FORWARD_COLUMNS}""",
            (answer, by, forward_id),
        )
        rows = _dicts(cur)
        return _clean(rows[0]) if rows else None


# ---------- 設定 ----------

def get_setting(conn, slug: str, key: str, default=None):
    with conn.cursor() as cur:
        cur.execute("SELECT value FROM projectops.assistant_setting WHERE project_slug = %s AND key = %s", (slug, key))
        row = cur.fetchone()
        return row[0] if row else default


def set_setting(conn, slug: str, key: str, value: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO projectops.assistant_setting (project_slug, key, value) VALUES (%s, %s, %s)
               ON CONFLICT (project_slug, key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()""",
            (slug, key, value),
        )


def slugs_with_setting(conn, key: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT project_slug FROM projectops.assistant_setting WHERE key = %s ORDER BY project_slug", (key,))
        return [r[0] for r in cur.fetchall()]


# ---------- 統計與部署閘門 ----------

def stats(conn, slug: str, since) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT
                 count(*) FILTER (WHERE role = 'user'),
                 count(*) FILTER (WHERE role = 'assistant' AND status = 'done'),
                 count(*) FILTER (WHERE role = 'assistant' AND status = 'failed'),
                 count(DISTINCT owner_id) FILTER (WHERE role = 'user'),
                 count(DISTINCT (EXTRACT(EPOCH FROM created_at)::bigint + 28800) / 86400) FILTER (WHERE role = 'user'),
                 count(*) FILTER (WHERE role = 'assistant' AND error_kind = 'lockdown')
               FROM projectops.assistant_message WHERE project_slug = %s AND created_at >= %s""",
            (slug, since),
        )
        q, answered, failed, people, days, lockdown = cur.fetchone()
        # 私下轉給負責人的提案確認後是轉問、不是改專案頁，只算在下面的 forwarded（10/15）
        cur.execute(
            """SELECT status, count(*) FROM projectops.assistant_proposal
               WHERE project_slug = %s AND created_at >= %s AND action <> '私下轉給負責人' GROUP BY status""",
            (slug, since),
        )
        by_status = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute(
            """SELECT count(*) FROM projectops.assistant_forward WHERE project_slug = %s AND created_at >= %s""",
            (slug, since),
        )
        forwarded = cur.fetchone()[0]
    return {"questions": q, "answered": answered, "failed": failed, "people": people, "days": days, "lockdown": lockdown,
            "proposals_applied": by_status.get("applied", 0), "proposals_dismissed": by_status.get("dismissed", 0),
            "proposals_pending": by_status.get("pending", 0), "proposals_failed": by_status.get("failed", 0),
            "forwarded": forwarded}


def codex_versions(conn, slug: str) -> list[dict]:
    """這個專案用過的 Codex 版本，照第一次出現排；負責人的視角用來看「Codex 從 A 升到 B」。"""

    with conn.cursor() as cur:
        cur.execute(
            """SELECT codex_version, min(finished_at), max(finished_at), count(*) FROM projectops.assistant_message
               WHERE project_slug = %s AND role = 'assistant' AND status = 'done' AND codex_version IS NOT NULL
               GROUP BY codex_version ORDER BY min(finished_at), min(id)""",
            (slug,),
        )
        return [{"version": r[0], "first_at": _iso(r[1]), "last_at": _iso(r[2]), "turns": r[3]} for r in cur.fetchall()]


def running_count(conn) -> int:
    """部署閘門用：正在回答的則數。表還不存在（第一次部署這個功能前）回 0。"""

    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('projectops.assistant_message')")
        if cur.fetchone()[0] is None:
            return 0
        cur.execute("SELECT count(*) FROM projectops.assistant_message WHERE status = 'running'")
        return int(cur.fetchone()[0])
