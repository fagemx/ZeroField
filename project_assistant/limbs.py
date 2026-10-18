"""Authenticated workers and expiring leases. The head never executes worker code."""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import secrets
import uuid

from project_docs import repository as repo

CAPABILITIES = ("llm", "image_gen", "video_gen", "media_assemble")
LEASE_SECONDS = 120


class ExecutionError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def token_hash(token):
    return hashlib.sha256(str(token).encode()).hexdigest()


def check_lease(task, limb_id, token, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    until = task.get("lease_until")
    if isinstance(until, str):
        until = dt.datetime.fromisoformat(until)
    if (task.get("status") != "running" or str(task.get("limb_id")) != str(limb_id)
            or not token or not hmac.compare_digest(task.get("lease_hash") or "", token_hash(token))
            or not until or until <= now):
        raise ExecutionError(409, "The task lease expired, was canceled, or belongs to another worker. Claim the task again.")


def _worker(row):
    return {"id": str(row[0]), "name": row[1], "capabilities": repo._loads(row[2]),
            "allowed_projects": repo._loads(row[3]), "enabled": row[4], "last_seen_at": repo._iso(row[5])}


def register(conn, me, body):
    if me.role != "admin":
        raise ExecutionError(403, "Only the showrunner can register remote workers.")
    name = str(body.get("name") or "").strip()
    caps = body.get("capabilities")
    projects = body.get("allowed_projects") or ([body["project_slug"]] if body.get("project_slug") else [])
    if not name or len(name) > 120 or not isinstance(caps, list) or not caps or any(c not in CAPABILITIES for c in caps):
        raise ExecutionError(400, "Provide a name and an llm / image_gen / video_gen / media_assemble capability.")
    if not isinstance(projects, list) or not projects or len(projects) > 100 or any(not isinstance(p, str) or not repo.get_project(conn, p) for p in projects):
        raise ExecutionError(400, "Provide an existing project_slug or allowed_projects.")
    identifier, token = str(uuid.uuid4()), secrets.token_urlsafe(32)
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO projectops.agent_limb(id,name,capabilities,allowed_projects,token_hash,created_by)
                       VALUES(%s,%s,%s::jsonb,%s::jsonb,%s,%s)
                       RETURNING id,name,capabilities,allowed_projects,enabled,last_seen_at""",
                    (identifier, name, json.dumps(list(dict.fromkeys(caps))), json.dumps(list(dict.fromkeys(projects))), token_hash(token), me.actor_id))
        worker = _worker(cur.fetchone())
    return {"limb": worker, "token": token}


def authenticate(conn, token):
    if not token:
        raise ExecutionError(401, "A worker Bearer token is required.")
    with conn.cursor() as cur:
        cur.execute("""UPDATE projectops.agent_limb SET last_seen_at=NOW()
                       WHERE token_hash=%s AND enabled
                       RETURNING id,name,capabilities,allowed_projects,enabled,last_seen_at""", (token_hash(token),))
        row = cur.fetchone()
    if not row:
        raise ExecutionError(401, "The worker token is invalid or disabled.")
    return _worker(row)


def list_workers(conn, slug=None):
    with conn.cursor() as cur:
        cur.execute("""SELECT id,name,capabilities,allowed_projects,enabled,last_seen_at
                       FROM projectops.agent_limb WHERE (%s::text IS NULL OR allowed_projects ? %s)
                       ORDER BY created_at""", (slug, slug))
        return [_worker(row) for row in cur.fetchall()]


def enabled_workers(conn, slug):
    return [w for w in list_workers(conn, slug) if w["enabled"]]


def connected_workers(conn, slug):
    """A registered worker becomes connected after its first authenticated poll."""
    with conn.cursor() as cur:
        cur.execute("""SELECT id,name,capabilities,allowed_projects,enabled,last_seen_at FROM projectops.agent_limb
                       WHERE enabled AND allowed_projects ? %s AND last_seen_at>=NOW()-INTERVAL '5 minutes'""", (slug,))
        return [_worker(row) for row in cur.fetchall()]


def revoke(conn, me, identifier):
    if me.role != "admin":
        raise ExecutionError(403, "Only the showrunner can disable workers.")
    with conn.cursor() as cur:
        cur.execute("UPDATE projectops.agent_limb SET enabled=FALSE WHERE id=%s", (identifier,))
        if not cur.rowcount:
            raise ExecutionError(404, "Worker not found.")
    return {"revoked": True}
