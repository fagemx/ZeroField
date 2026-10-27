"""專案文件的資料庫存取。每個函式拿一條連線，commit／rollback 由呼叫端決定。

actor_id 都是 projectops.member 的 actor_id；名字一律讀的時候 join 名單，名單改名就跟著改。
"""
from __future__ import annotations

import hashlib
import json
from openbench_data import resource_path

SCHEMA_DIR = resource_path("db")
SCHEMA_FILES = ("149_project_docs_schema.sql", "151_project_docs_annotations.sql", "153_project_docs_audit.sql",
                "154_project_assistant.sql", "156_project_assistant_conversations.sql", "157_execution.sql", "158_agent_profiles.sql",
                "159_agent_orchestration.sql", "160_agent_races.sql", "161_agent_comment_routes.sql", "162_story_workbench.sql", "163_agent_console.sql",
                "164_agent_service_accounts.sql")
_UNSET = object()
PROJECT_STATUSES = ("planning", "active", "recurring", "blocked", "archived")
PRIVACY_MODES = ("full_access", "mask_numbers")
SURFACE_TYPES = ("doc", "sheet", "flow", "board")


def _iso(value):
    return value.isoformat() if value is not None else None


def _doc_param(doc) -> str:
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":"))


def _loads(value):
    # psycopg 會把 jsonb 解成 Python 值；退回 psycopg2 或文字時再自己解。
    return json.loads(value) if isinstance(value, (str, bytes)) else value


def ensure_schema(connection) -> None:
    with connection.cursor() as cursor:
        # 兩個行程同時第一次建表會撞 pg_type 的唯一鍵；拿交易層級的鎖排隊。
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext('projectops-schema'))")
        for name in SCHEMA_FILES:
            cursor.execute((SCHEMA_DIR / name).read_text(encoding="utf-8"))
        cursor.execute('SELECT slug FROM projectops.project')
        slugs = [row[0] for row in cursor.fetchall()]
    from project_assistant.agent_registry import ensure_default_agents
    for slug in slugs:
        ensure_default_agents(connection, slug)


# ---------- 專案與分頁 ----------

def upsert_project(connection, slug: str, title: str, *, status: str = "active", summary: str = "") -> None:
    if status not in PROJECT_STATUSES:
        status = "active"
    with connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO projectops.project (slug, title, status, summary) VALUES (%s, %s, %s, %s)
               ON CONFLICT (slug) DO UPDATE SET
                 title = EXCLUDED.title,
                 status = COALESCE(NULLIF(EXCLUDED.status, ''), projectops.project.status),
                 summary = CASE WHEN EXCLUDED.summary <> '' THEN EXCLUDED.summary ELSE projectops.project.summary END,
                 updated_at = NOW()""",
            (slug, title, status, summary),
        )
    from project_assistant.agent_registry import ensure_default_agents
    ensure_default_agents(connection, slug)


def update_project_meta(connection, slug: str, *, title=_UNSET, status=_UNSET, summary=_UNSET,
                        privacy_mode=_UNSET) -> dict | None:
    sets, params = ["updated_at = NOW()"], []
    if title is not _UNSET:
        sets.append("title = %s")
        params.append(title)
    if status is not _UNSET and status in PROJECT_STATUSES:
        sets.append("status = %s")
        params.append(status)
    if summary is not _UNSET:
        sets.append("summary = %s")
        params.append(summary)
    if privacy_mode is not _UNSET:
        if privacy_mode not in PRIVACY_MODES:
            raise ValueError("unsupported privacy mode")
        sets.append("privacy_mode = %s")
        params.append(privacy_mode)
    params.append(slug)
    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE projectops.project SET {', '.join(sets)} WHERE slug = %s", params)
    return get_project(connection, slug)


def list_projects(connection) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT p.slug, p.title, p.status, p.summary, p.updated_at,
                      (SELECT COUNT(*) FROM projectops.tab t WHERE t.project_slug = p.slug AND t.deleted_at IS NULL),
                      p.privacy_mode
               FROM projectops.project p ORDER BY p.updated_at DESC, p.slug"""
        )
        return [
            {"slug": r[0], "title": r[1], "status": r[2] or "active", "summary": r[3] or "",
             "updated_at": _iso(r[4]), "tab_count": int(r[5] or 0), "privacy_mode": r[6]}
            for r in cursor.fetchall()
        ]


def get_project(connection, slug: str) -> dict | None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT slug, title, status, summary, updated_at, privacy_mode FROM projectops.project WHERE slug = %s", (slug,)
        )
        row = cursor.fetchone()
    return ({"slug": row[0], "title": row[1], "status": row[2] or "active",
             "summary": row[3] or "", "updated_at": _iso(row[4]), "privacy_mode": row[5]} if row else None)


# created_by：誰新增這一頁＝第一筆版本是誰存的（自己加的分頁自己可以改名、移動、刪除）
_TAB_COLUMNS = (
    "t.tab_key, t.parent_key, t.title, t.position, t.revision, t.updated_at, "
    "t.updated_by::text, m.display_name, t.deleted_at, "
    "(SELECT r.saved_by::text FROM projectops.tab_revision r "
    "WHERE r.project_slug = t.project_slug AND r.tab_key = t.tab_key ORDER BY r.revision LIMIT 1), "
    "COALESCE(t.surface_type, 'doc'), t.source_filename, t.source_mime"
)


def _tab_row(row) -> dict:
    return {
        "key": row[0], "parent_key": row[1], "title": row[2], "position": row[3],
        "revision": row[4], "updated_at": _iso(row[5]), "updated_by": row[6],
        "updated_by_name": row[7] or "", "deleted_at": _iso(row[8]), "created_by": row[9],
        "surface_type": row[10] if len(row) > 10 else "doc",
        "source_filename": row[11] if len(row) > 11 else None,
        "source_mime": row[12] if len(row) > 12 else None,
    }


def list_tabs(connection, slug: str, *, deleted: bool = False) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute(
            f"""SELECT {_TAB_COLUMNS}
                FROM projectops.tab t
                LEFT JOIN projectops.member m ON m.actor_id = t.updated_by
                WHERE t.project_slug = %s AND (t.deleted_at IS NOT NULL) = %s
                ORDER BY t.position, t.tab_key""",
            (slug, deleted),
        )
        return [_tab_row(r) for r in cursor.fetchall()]


def get_tab(connection, slug: str, key: str, *, include_deleted: bool = False) -> dict | None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"""SELECT {_TAB_COLUMNS}, t.doc
                FROM projectops.tab t
                LEFT JOIN projectops.member m ON m.actor_id = t.updated_by
                WHERE t.project_slug = %s AND t.tab_key = %s""",
            (slug, key),
        )
        row = cursor.fetchone()
    if not row:
        return None
    tab = _tab_row(row)
    if tab["deleted_at"] and not include_deleted:
        return None
    tab["doc"] = _loads(row[13])
    return tab


def get_tab_for_update(connection, slug: str, key: str) -> dict | None:
    """存 ops 用：鎖住這一頁直到交易結束，同時只有一個人在套 ops。"""

    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT doc, revision, title, updated_at, COALESCE(surface_type, 'doc'), source_filename FROM projectops.tab
               WHERE project_slug = %s AND tab_key = %s AND deleted_at IS NULL FOR UPDATE""",
            (slug, key),
        )
        row = cursor.fetchone()
    if not row:
        return None
    return {"doc": _loads(row[0]), "revision": row[1], "title": row[2],
            "updated_at": _iso(row[3]), "surface_type": row[4], "source_filename": row[5]}


def get_tab_source(connection, slug: str, key: str) -> dict | None:
    """Private file body and coordinate map; do not add these to public tab payloads."""
    with connection.cursor() as cursor:
        cursor.execute("""SELECT source_filename, source_mime, source_blob, source_meta
                          FROM projectops.tab WHERE project_slug = %s AND tab_key = %s
                          AND deleted_at IS NULL""", (slug, key))
        row = cursor.fetchone()
    if not row:
        return None
    return {"filename": row[0], "mime": row[1], "blob": bytes(row[2]) if row[2] is not None else None,
            "metadata": _loads(row[3]) if row[3] is not None else {}}


def set_tab_source(connection, slug: str, key: str, *, filename: str, mime: str,
                   blob: bytes, metadata: dict, surface_type: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute("""UPDATE projectops.tab SET source_filename = %s, source_mime = %s,
                          source_blob = %s, source_meta = %s::jsonb, surface_type = %s
                          WHERE project_slug = %s AND tab_key = %s""",
                       (filename, mime, blob, _doc_param(metadata), surface_type, slug, key))


def create_tab(connection, slug: str, *, key: str, title: str, parent_key: str | None,
               doc: dict, actor_id: str | None, position: int | None = None,
               surface_type: str = "doc") -> dict:
    if surface_type not in SURFACE_TYPES:
        surface_type = "doc"
    with connection.cursor() as cursor:
        if position is None:
            cursor.execute(
                "SELECT COALESCE(MAX(position), 0) + 10 FROM projectops.tab WHERE project_slug = %s",
                (slug,),
            )
            position = cursor.fetchone()[0]
        cursor.execute(
            """INSERT INTO projectops.tab
                 (project_slug, tab_key, parent_key, title, surface_type, position, doc, revision, updated_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, 1, %s)""",
            (slug, key, parent_key, title, surface_type, position, _doc_param(doc), actor_id),
        )
        cursor.execute(
            """INSERT INTO projectops.tab_revision
                 (project_slug, tab_key, revision, title, doc, session_id, saved_by)
               VALUES (%s, %s, 1, %s, %s::jsonb, 'create', %s)""",
            (slug, key, title, _doc_param(doc), actor_id),
        )
    return get_tab(connection, slug, key)


def save_tab_doc(connection, slug: str, key: str, *, doc: dict, title: str, actor_id: str,
                 session_id: str, base_revision: int | None, force_revision: bool = False,
                 trusted_writer=None) -> dict:
    """Save source/history and any enrolled Story associations in one savepoint.

    trusted_writer is internal caller context, not reconstructed from actor_id.
    Explicit lineage operations defer this hook only in connection-local state.
    """
    from project_docs import writing_structure, writing_store
    from psycopg.errors import LockNotAvailable
    try:
        with writing_structure.savepoint(connection):
            tab=get_tab_for_update(connection,slug,key)
            if not tab: raise LookupError('tab not found')
            plan=(writing_structure.prepare_tab_save(connection,slug,key,tab['doc'],doc,trusted_writer)
                if tab['doc']!=doc else None)
            result=_save_tab_doc(connection,slug,key,doc=doc,title=title,actor_id=actor_id,
                session_id=session_id,base_revision=base_revision,force_revision=force_revision)
            writing_structure.finish_tab_save(connection,plan)
            return result
    except LockNotAvailable:
        writing_store.fail('LOCKED','An affected production page is busy; nothing was saved.')


def _save_tab_doc(connection, slug: str, key: str, *, doc: dict, title: str, actor_id: str,
                 session_id: str, base_revision: int | None, force_revision: bool = False) -> dict:
    """存一次。同一個人、同一個 session 的自動儲存覆寫同一個版本；換 session、或停了 10 分鐘以上就是新版本
    （修改紀錄「停 10 分鐘以上算新的一筆」，改回才能只回到那一次之前）。

    別人在你打開之後存過（base_revision 比現在舊），照樣存進去（不擋），但回 overwrote=True，
    對方那一版留在版本紀錄裡，要的話可以還原。
    """

    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT revision, doc, title, updated_at FROM projectops.tab
               WHERE project_slug = %s AND tab_key = %s AND deleted_at IS NULL FOR UPDATE""",
            (slug, key),
        )
        row = cursor.fetchone()
        if not row:
            raise LookupError("tab not found")
        current = row[0]
        if not force_revision and _loads(row[1]) == doc and row[2] == title:
            # 內容跟現在一模一樣：不寫、不算版本（打開頁面、游標移動都不該變成一個版本）。
            return {"revision": current, "saved_at": _iso(row[3]), "overwrote": False, "unchanged": True}
        cursor.execute(
            """SELECT id, session_id, saved_by::text, saved_at >= NOW() - INTERVAL '10 minutes'
               FROM projectops.tab_revision
               WHERE project_slug = %s AND tab_key = %s ORDER BY revision DESC LIMIT 1""",
            (slug, key),
        )
        last = cursor.fetchone()
        same_session = not force_revision and bool(
            last and session_id and last[1] == session_id and last[2] == str(actor_id) and last[3]
        )
        overwrote = base_revision is not None and int(base_revision) != current and not same_session
        if same_session:
            revision = current
            cursor.execute(
                """UPDATE projectops.tab_revision SET doc = %s::jsonb, title = %s, saved_at = NOW()
                   WHERE id = %s""",
                (_doc_param(doc), title, last[0]),
            )
        else:
            revision = current + 1
            cursor.execute(
                """INSERT INTO projectops.tab_revision
                     (project_slug, tab_key, revision, title, doc, session_id, saved_by)
                   VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)""",
                (slug, key, revision, title, _doc_param(doc), session_id or "", actor_id),
            )
        cursor.execute(
            """UPDATE projectops.tab
               SET doc = %s::jsonb, title = %s, revision = %s, updated_by = %s, updated_at = NOW()
               WHERE project_slug = %s AND tab_key = %s
               RETURNING updated_at""",
            (_doc_param(doc), title, revision, actor_id, slug, key),
        )
        saved_at = cursor.fetchone()[0]
    return {"revision": revision, "saved_at": _iso(saved_at), "overwrote": overwrote, "unchanged": False}


def update_tab_meta(connection, slug: str, key: str, *, title=_UNSET, parent_key=_UNSET,
                    position=_UNSET) -> bool:
    sets, params = [], []
    if title is not _UNSET:
        sets.append("title = %s")
        params.append(title)
    if parent_key is not _UNSET:
        sets.append("parent_key = %s")
        params.append(parent_key)
    if position is not _UNSET:
        sets.append("position = %s")
        params.append(position)
    if not sets:
        return True
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE projectops.tab SET {', '.join(sets)} "
            "WHERE project_slug = %s AND tab_key = %s",
            (*params, slug, key),
        )
        return cursor.rowcount == 1


def set_tab_deleted(connection, slug: str, key: str, deleted: bool) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            """UPDATE projectops.tab SET deleted_at = CASE WHEN %s THEN NOW() ELSE NULL END
               WHERE project_slug = %s AND tab_key = %s""",
            (deleted, slug, key),
        )
        return cursor.rowcount == 1


def normalize_positions(connection, slug: str, ordered_keys: list[str]) -> None:
    with connection.cursor() as cursor:
        for index, key in enumerate(ordered_keys):
            cursor.execute(
                "UPDATE projectops.tab SET position = %s WHERE project_slug = %s AND tab_key = %s",
                ((index + 1) * 10, slug, key),
            )


def list_revisions(connection, slug: str, key: str, limit: int = 100) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT r.revision, r.title, r.saved_at, r.saved_by::text, m.display_name, r.session_id
               FROM projectops.tab_revision r
               LEFT JOIN projectops.member m ON m.actor_id = r.saved_by
               WHERE r.project_slug = %s AND r.tab_key = %s
               ORDER BY r.revision DESC LIMIT %s""",
            (slug, key, limit),
        )
        return [
            {"revision": r[0], "title": r[1], "saved_at": _iso(r[2]), "saved_by": r[3],
             "saved_by_name": r[4] or "", "restored": (r[5] or "").startswith("restore-")}
            for r in cursor.fetchall()
        ]


def get_revision(connection, slug: str, key: str, revision: int) -> dict | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT revision, title, doc FROM projectops.tab_revision
               WHERE project_slug = %s AND tab_key = %s AND revision = %s""",
            (slug, key, revision),
        )
        row = cursor.fetchone()
    return {"revision": row[0], "title": row[1], "doc": _loads(row[2])} if row else None


# ---------- 狀態、可填格、勾選 ----------

def field_values(connection, slug: str) -> dict[str, dict]:
    """{tab_key: {field_id: {kind, value, by, by_name, at}}}"""

    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT f.tab_key, f.field_id, f.kind, f.value, f.updated_by::text, m.display_name, f.updated_at
               FROM projectops.field_value f
               LEFT JOIN projectops.member m ON m.actor_id = f.updated_by
               WHERE f.project_slug = %s""",
            (slug,),
        )
        out: dict[str, dict] = {}
        for r in cursor.fetchall():
            out.setdefault(r[0], {})[r[1]] = {
                "kind": r[2], "value": r[3], "by": r[4], "by_name": r[5] or "", "at": _iso(r[6]),
            }
        return out


def get_field_value(connection, slug: str, tab_key: str, field_id: str) -> str | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT value FROM projectops.field_value
               WHERE project_slug = %s AND tab_key = %s AND field_id = %s""",
            (slug, tab_key, field_id),
        )
        row = cursor.fetchone()
    return row[0] if row else None


def set_field_value(connection, slug: str, tab_key: str, field_id: str, *, kind: str,
                    value: str, actor_id: str) -> str | None:
    """寫入目前值，回傳舊值（沒寫過回 None）。"""

    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT value FROM projectops.field_value
               WHERE project_slug = %s AND tab_key = %s AND field_id = %s FOR UPDATE""",
            (slug, tab_key, field_id),
        )
        row = cursor.fetchone()
        cursor.execute(
            """INSERT INTO projectops.field_value
                 (project_slug, tab_key, field_id, kind, value, updated_by)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (project_slug, tab_key, field_id) DO UPDATE SET
                 kind = EXCLUDED.kind, value = EXCLUDED.value,
                 updated_by = EXCLUDED.updated_by, updated_at = NOW()""",
            (slug, tab_key, field_id, kind, value, actor_id),
        )
    return row[0] if row else None


# ---------- 對話（留言與欄位變更；v2 起都掛在標註上） ----------

def add_activity(connection, slug: str, tab_key: str, anchor_id: str, *, kind: str, actor_id: str,
                 body: str = "", mentions=(), field_id=None, field_label=None,
                 old_value=None, new_value=None, annotation_id=None) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO projectops.activity
                 (project_slug, tab_key, anchor_id, kind, body, mentions, field_id, field_label,
                  old_value, new_value, actor_id, annotation_id)
               VALUES (%s, %s, %s, %s, %s, %s::uuid[], %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (slug, tab_key, anchor_id, kind, body, list(mentions), field_id, field_label,
             old_value, new_value, actor_id, annotation_id),
        )
        return cursor.fetchone()[0]


_ACTIVITY_COLUMNS = """
    a.id, a.tab_key, a.anchor_id, a.kind, a.body, a.mentions::text[] AS mentions, a.field_id,
    a.field_label, a.old_value, a.new_value, a.actor_id::text AS actor_id, m.display_name, m.role,
    a.created_at, a.annotation_id
"""
_ACTIVITY_FROM = """
    FROM projectops.activity a
    LEFT JOIN projectops.member m ON m.actor_id = a.actor_id
"""
_ACTIVITY_SELECT = "SELECT " + _ACTIVITY_COLUMNS + _ACTIVITY_FROM


def _activity_row(r) -> dict:
    item = {
        "id": r[0], "tab_key": r[1], "anchor_id": r[2], "kind": r[3],
        "actor": {"actor_id": r[10], "name": r[11] or "（已不在名單）", "role": r[12] or ""},
        "at": _iso(r[13]), "annotation_id": r[14],
    }
    if r[3] == "comment":
        item["body"] = r[4]
        item["mentions"] = list(r[5] or [])
    else:
        item["field"] = {"field_id": r[6], "label": r[7] or "", "old": r[8], "new": r[9]}
    return item


def get_activity(connection, slug: str, activity_id: int) -> dict | None:
    with connection.cursor() as cursor:
        cursor.execute(
            _ACTIVITY_SELECT + " WHERE a.project_slug = %s AND a.id = %s AND a.deleted_at IS NULL",
            (slug, activity_id),
        )
        row = cursor.fetchone()
    return _activity_row(row) if row else None


def delete_comment(connection, slug: str, comment_id: int, actor_id: str) -> bool:
    """只能刪自己的留言（標 deleted_at）。"""

    with connection.cursor() as cursor:
        cursor.execute(
            """UPDATE projectops.activity SET deleted_at = NOW()
               WHERE project_slug = %s AND id = %s AND kind = 'comment'
                 AND actor_id = %s::uuid AND deleted_at IS NULL""",
            (slug, comment_id, actor_id),
        )
        return cursor.rowcount == 1


# ---------- 標註 ----------

_ANN_SELECT = """
    SELECT a.id, a.tab_key, a.kind, a.anchor, a.style, a.color, a.label, a.label_by::text, a.label_at,
           a.created_by::text, a.created_at, a.resolved_by::text, a.resolved_at, a.orphaned_at,
           a.moved, a.reconfirm, cm.display_name
    FROM projectops.annotation a
    LEFT JOIN projectops.member cm ON cm.actor_id = a.created_by
"""


def _ann_row(r) -> dict:
    return {
        "id": r[0], "tab_key": r[1], "kind": r[2], "anchor": _loads(r[3]), "style": r[4], "color": r[5],
        "label": r[6], "label_by": r[7], "label_at": _iso(r[8]), "created_by": r[9],
        "created_by_name": r[16] or "（已不在名單）", "created_at": _iso(r[10]), "resolved_by": r[11],
        "resolved_at": _iso(r[12]), "orphaned_at": _iso(r[13]),
        "moved": _loads(r[14]) if r[14] is not None else None,
        "reconfirm": _loads(r[15]) if r[15] is not None else None,
        "messages": [],
    }


def create_annotation(connection, slug: str, tab_key: str, *, kind: str, anchor: dict, actor_id: str,
                      style=None, color=None, label=None) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO projectops.annotation
                 (project_slug, tab_key, kind, anchor, style, color, label, label_by, label_at, created_by)
               VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, CASE WHEN %s THEN NOW() END, %s)
               RETURNING id""",
            (slug, tab_key, kind, _doc_param(anchor), style, color, label,
             actor_id if label else None, bool(label), actor_id),
        )
        return cursor.fetchone()[0]


def row_annotation_id(connection, slug: str, tab_key: str, rid: str, actor_id: str) -> int:
    """這一列的整列對話：沒有就建一筆（一列只有一筆）。"""

    with connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO projectops.annotation (project_slug, tab_key, kind, anchor, created_by)
               VALUES (%s, %s, 'row', %s::jsonb, %s)
               ON CONFLICT (project_slug, tab_key, (anchor->>'rid')) WHERE kind = 'row' AND deleted_at IS NULL
               DO NOTHING
               RETURNING id""",
            (slug, tab_key, _doc_param({"rid": rid}), actor_id),
        )
        row = cursor.fetchone()
        if row:
            return row[0]
        cursor.execute(
            """SELECT id FROM projectops.annotation
               WHERE project_slug = %s AND tab_key = %s AND kind = 'row' AND anchor->>'rid' = %s
                 AND deleted_at IS NULL""",
            (slug, tab_key, rid),
        )
        return cursor.fetchone()[0]


def list_annotations(connection, slug: str, *, tab_key=None, annotation_id=None) -> list[dict]:
    where, params = ["a.project_slug = %s", "a.deleted_at IS NULL"], [slug]
    if tab_key is not None:
        where.append("a.tab_key = %s")
        params.append(tab_key)
    if annotation_id is not None:
        where.append("a.id = %s")
        params.append(annotation_id)
    with connection.cursor() as cursor:
        cursor.execute(_ANN_SELECT + " WHERE " + " AND ".join(where) + " ORDER BY a.id", params)
        items = [_ann_row(r) for r in cursor.fetchall()]
        if not items:
            return []
        by_id = {item["id"]: item for item in items}
        cursor.execute(
            _ACTIVITY_SELECT
            + """ WHERE a.project_slug = %s AND a.annotation_id = ANY(%s) AND a.deleted_at IS NULL
                  ORDER BY a.created_at, a.id""",
            (slug, list(by_id)),
        )
        for r in cursor.fetchall():
            message = _activity_row(r)
            by_id[message["annotation_id"]]["messages"].append(message)
    return items


def annotations_for_anchoring(connection, slug: str, tab_key: str) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT a.id, a.kind, a.anchor, a.label, a.style, a.resolved_at, a.orphaned_at, a.moved, a.reconfirm,
                      EXISTS (SELECT 1 FROM projectops.activity c
                              WHERE c.annotation_id = a.id AND c.kind = 'comment' AND c.deleted_at IS NULL)
               FROM projectops.annotation a
               WHERE a.project_slug = %s AND a.tab_key = %s AND a.deleted_at IS NULL
               ORDER BY a.id""",
            (slug, tab_key),
        )
        return [
            {"id": r[0], "kind": r[1], "anchor": _loads(r[2]), "label": r[3], "style": r[4],
             "resolved_at": _iso(r[5]), "orphaned_at": _iso(r[6]),
             "moved": _loads(r[7]) if r[7] is not None else None,
             "reconfirm": _loads(r[8]) if r[8] is not None else None, "has_comments": bool(r[9])}
            for r in cursor.fetchall()
        ]


def set_resolved(connection, annotation_id: int, actor_id) -> None:
    with connection.cursor() as cursor:
        if actor_id:
            cursor.execute(
                "UPDATE projectops.annotation SET resolved_by = %s, resolved_at = NOW() WHERE id = %s",
                (actor_id, annotation_id),
            )
        else:
            cursor.execute(
                "UPDATE projectops.annotation SET resolved_by = NULL, resolved_at = NULL WHERE id = %s",
                (annotation_id,),
            )


def confirm_label(connection, annotation_id: int, actor_id: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """UPDATE projectops.annotation
               SET label_by = %s, label_at = NOW(), reconfirm = NULL, moved = NULL WHERE id = %s""",
            (actor_id, annotation_id),
        )


def set_style(connection, annotation_id: int, style, color) -> None:
    with connection.cursor() as cursor:
        cursor.execute("UPDATE projectops.annotation SET style = %s, color = %s WHERE id = %s",
                       (style, color, annotation_id))


def update_anchor(connection, annotation_id: int, anchor: dict, *, moved=_UNSET, reconfirm=_UNSET) -> None:
    sets, params = ["anchor = %s::jsonb"], [_doc_param(anchor)]
    if moved is not _UNSET:
        sets.append("moved = %s::jsonb")
        params.append(_doc_param(moved) if moved is not None else None)
    if reconfirm is not _UNSET:
        sets.append("reconfirm = %s::jsonb")
        params.append(_doc_param(reconfirm) if reconfirm is not None else None)
    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE projectops.annotation SET {', '.join(sets)} WHERE id = %s",
                       (*params, annotation_id))


def set_orphaned(connection, annotation_id: int, orphaned: bool) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """UPDATE projectops.annotation
               SET orphaned_at = CASE WHEN %s THEN COALESCE(orphaned_at, NOW()) ELSE NULL END WHERE id = %s""",
            (orphaned, annotation_id),
        )


def reattach(connection, annotation_id: int, anchor: dict) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """UPDATE projectops.annotation
               SET anchor = %s::jsonb, orphaned_at = NULL, moved = NULL WHERE id = %s""",
            (_doc_param(anchor), annotation_id),
        )


def delete_annotation(connection, annotation_id: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute("UPDATE projectops.annotation SET deleted_at = NOW() WHERE id = %s AND deleted_at IS NULL",
                       (annotation_id,))


# ---------- 編輯鎖 ----------

def take_lock(connection, slug: str, tab_key: str, unit_id: str, actor_id: str, seconds: int = 90) -> str:
    """搶鎖或續約；回傳現在拿著鎖的人（拿到就是自己）。"""

    with connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO projectops.block_lock (project_slug, tab_key, unit_id, actor_id, expires_at)
               VALUES (%s, %s, %s, %s, NOW() + make_interval(secs => %s))
               ON CONFLICT (project_slug, tab_key, unit_id) DO UPDATE
                 SET actor_id = EXCLUDED.actor_id, expires_at = EXCLUDED.expires_at
                 WHERE projectops.block_lock.actor_id = EXCLUDED.actor_id
                    OR projectops.block_lock.expires_at <= NOW()
               RETURNING actor_id::text""",
            (slug, tab_key, unit_id, actor_id, seconds),
        )
        row = cursor.fetchone()
        if row:
            return row[0]
        cursor.execute(
            """SELECT actor_id::text FROM projectops.block_lock
               WHERE project_slug = %s AND tab_key = %s AND unit_id = %s""",
            (slug, tab_key, unit_id),
        )
        return cursor.fetchone()[0]


def release_lock(connection, slug: str, tab_key: str, unit_id: str, actor_id: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """DELETE FROM projectops.block_lock
               WHERE project_slug = %s AND tab_key = %s AND unit_id = %s AND actor_id = %s""",
            (slug, tab_key, unit_id, actor_id),
        )


def tab_locks(connection, slug: str, tab_key: str) -> dict[str, str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT unit_id, actor_id::text FROM projectops.block_lock
               WHERE project_slug = %s AND tab_key = %s AND expires_at > NOW()""",
            (slug, tab_key),
        )
        return {r[0]: r[1] for r in cursor.fetchall()}


def active_locks(connection, slug: str) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT l.tab_key, l.unit_id, l.actor_id::text, m.display_name
               FROM projectops.block_lock l
               LEFT JOIN projectops.member m ON m.actor_id = l.actor_id
               WHERE l.project_slug = %s AND l.expires_at > NOW()
               ORDER BY l.tab_key, l.unit_id""",
            (slug,),
        )
        return [{"tab_key": r[0], "unit_id": r[1], "actor_id": r[2], "name": r[3] or "別人"}
                for r in cursor.fetchall()]


# ---------- 圖片 ----------

def asset_id_for(data: bytes) -> str:
    return "pa_" + hashlib.sha256(data).hexdigest()[:32]


def put_asset(connection, slug: str, *, data: bytes, content_type: str, actor_id: str) -> str:
    asset_id = asset_id_for(data)
    with connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO projectops.asset
                 (project_slug, asset_id, content_type, data, byte_size, uploaded_by)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (project_slug, asset_id) DO NOTHING""",
            (slug, asset_id, content_type, data, len(data), actor_id),
        )
    return asset_id


def get_asset(connection, slug: str, asset_id: str) -> tuple[str, bytes] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT content_type, data FROM projectops.asset WHERE project_slug = %s AND asset_id = %s",
            (slug, asset_id),
        )
        row = cursor.fetchone()
    return (row[0], bytes(row[1])) if row else None


def get_asset_meta(connection, slug: str, asset_id: str) -> tuple[str, int] | None:
    """Read MIME type and size without loading the media bytea."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT content_type, byte_size FROM projectops.asset WHERE project_slug = %s AND asset_id = %s",
            (slug, asset_id),
        )
        row = cursor.fetchone()
    return (row[0], int(row[1])) if row else None


# ---------- 名單 ----------

def upsert_member(connection, actor_id: str, display_name: str, role: str = "member",
                  email: str = "", status: str = "active") -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO projectops.member (actor_id, display_name, role, email, status)
               VALUES (%s::uuid, %s, %s, %s, %s)
               ON CONFLICT (actor_id) DO UPDATE SET
                 display_name = EXCLUDED.display_name,
                 role = EXCLUDED.role,
                 email = EXCLUDED.email,
                 status = EXCLUDED.status,
                 updated_at = NOW()""",
            (actor_id, display_name, role, email or f"{actor_id[:8]}@openbench.local", status),
        )


def active_members(connection) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT actor_id::text, display_name, role, email FROM projectops.member
               WHERE status = 'active' ORDER BY display_name"""
        )
        return [
            {"actor_id": r[0], "name": r[1], "role": r[2], "email": r[3]}
            for r in cursor.fetchall()
        ]


def member_names(connection) -> dict[str, str]:
    """名單上所有人（含已停用的）actor_id → 名字；查歷史紀錄用。"""

    with connection.cursor() as cursor:
        cursor.execute("SELECT actor_id::text, display_name FROM projectops.member")
        return {r[0]: r[1] for r in cursor.fetchall()}


# ---------- 系統紀錄（只給工程查，畫面上不顯示） ----------

def add_audit(connection, slug: str, *, action: str, actor_id=None, tab_key=None, target=None,
              detail=None) -> None:
    """記一筆：誰、什麼時候、做了什麼。跟那個動作同一個交易，動作失敗就一起不算。"""

    with connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO projectops.audit_log (project_slug, tab_key, actor_id, action, target, detail)
               VALUES (%s, %s, %s, %s, %s, %s::jsonb)""",
            (slug, tab_key, actor_id, action, None if target is None else str(target),
             _doc_param(detail or {})),
        )


def _since_clause(column: str, tab_key, since, params: list) -> str:
    where = ""
    if tab_key is not None:
        where += " AND tab_key = %s"
        params.append(tab_key)
    if since is not None:
        where += f" AND {column} >= %s"
        params.append(since)
    return where


def audit_rows(connection, slug: str, *, tab_key=None, since=None) -> list[dict]:
    params: list = [slug]
    where = _since_clause("created_at", tab_key, since, params)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, tab_key, actor_id::text, action, target, detail, created_at FROM projectops.audit_log"
            " WHERE project_slug = %s" + where + " ORDER BY created_at, id",
            params,
        )
        return [
            {"id": r[0], "tab_key": r[1], "actor_id": r[2], "action": r[3], "target": r[4],
             "detail": _loads(r[5]) or {}, "at": r[6]}
            for r in cursor.fetchall()
        ]


def revision_rows(connection, slug: str, *, tab_key=None) -> list[dict]:
    """每一頁的每一筆版本（含整份內文），照分頁、版本號排；比對前後兩筆用。"""

    params: list = [slug]
    where = _since_clause("saved_at", tab_key, None, params)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tab_key, revision, title, doc, session_id, saved_by::text, saved_at FROM projectops.tab_revision"
            " WHERE project_slug = %s" + where + " ORDER BY tab_key, revision",
            params,
        )
        return [
            {"tab_key": r[0], "revision": r[1], "title": r[2], "doc": _loads(r[3]), "session_id": r[4] or "",
             "actor_id": r[5], "at": r[6]}
            for r in cursor.fetchall()
        ]


def activity_rows(connection, slug: str, *, tab_key=None, since=None) -> list[dict]:
    """留言與欄位變更，連已刪除的留言也列（標 deleted_at）。"""

    params: list = [slug]
    where = _since_clause("created_at", tab_key, since, params)
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT id, tab_key, kind, body, field_label, old_value, new_value, actor_id::text, created_at,
                      deleted_at, annotation_id, field_id, anchor_id
               FROM projectops.activity WHERE project_slug = %s""" + where + " ORDER BY created_at, id",
            params,
        )
        return [
            {"id": r[0], "tab_key": r[1], "kind": r[2], "body": r[3], "field_label": r[4], "old": r[5],
             "new": r[6], "actor_id": r[7], "at": r[8], "deleted_at": r[9], "annotation_id": r[10],
             "field_id": r[11], "anchor_id": r[12]}
            for r in cursor.fetchall()
        ]


def annotation_rows(connection, slug: str, *, tab_key=None, since=None) -> list[dict]:
    """標註（連已刪除的），給歷史紀錄用。"""

    params: list = [slug]
    where = _since_clause("created_at", tab_key, since, params)
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT id, tab_key, kind, anchor, style, color, label, created_by::text, created_at,
                      resolved_by::text, resolved_at, deleted_at
               FROM projectops.annotation WHERE project_slug = %s""" + where + " ORDER BY created_at, id",
            params,
        )
        return [
            {"id": r[0], "tab_key": r[1], "kind": r[2], "anchor": _loads(r[3]) or {}, "style": r[4],
             "color": r[5], "label": r[6], "actor_id": r[7], "at": r[8], "resolved_by": r[9],
             "resolved_at": r[10], "deleted_at": r[11]}
            for r in cursor.fetchall()
        ]
