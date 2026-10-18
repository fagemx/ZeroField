"""Workspace member management. Roles are global across this workspace."""
import uuid
from project_docs import repository as repo

from project_docs.service import ROLE_LABEL as ROLES


def list_members(conn, me):
    if not me.can_edit:
        return 403, {"error": "Only the showrunner can manage crew accounts."}
    with conn.cursor() as cur:
        cur.execute("SELECT actor_id::text, display_name, role, email, status FROM projectops.member ORDER BY display_name")
        rows = [dict(zip(("actor_id", "name", "role", "email", "status"), r)) for r in cur.fetchall()]
    return 200, {"members": rows, "roles": ROLES}


def save_member(conn, me, body):
    if not me.can_edit:
        return 403, {"error": "Only the showrunner can manage crew accounts."}
    try:
        actor = str(uuid.UUID(str(body.get("actor_id") or uuid.uuid4())))
    except ValueError:
        return 400, {"error": "Invalid crew account ID."}
    name = str(body.get("name") or "").strip()
    role, status = body.get("role", "member"), body.get("status", "active")
    email = str(body.get("email") or f"{actor}@openbench.local").strip()
    if not 1 <= len(name) <= 100 or role not in ROLES or status not in ("active", "inactive") or len(email) > 254 or "@" not in email:
        return 400, {"error": "Provide a name, valid role, email, and account status."}
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext('openbench-members'))")
        cur.execute("SELECT actor_id::text FROM projectops.member WHERE role='admin' AND status='active' FOR UPDATE")
        admins = [r[0] for r in cur.fetchall()]
        if actor in admins and len(admins) == 1 and (role != "admin" or status != "active"):
            return 409, {"error": "Keep at least one active showrunner."}
        cur.execute("SELECT 1 FROM projectops.member WHERE email=%s AND actor_id<>%s::uuid", (email, actor))
        if cur.fetchone():
            return 409, {"error": "This email address is already in use."}
    repo.upsert_member(conn, actor, name, role, email, status)
    return list_members(conn, me)
