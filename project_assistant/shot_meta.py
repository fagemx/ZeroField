"""Crew proposals that change a shot's meta instead of a sheet cell (SPEC_20 R18, decision 5): action ``shot_meta``.

A proposal is pinned by the revision of the one field it changes, never by a page. Its target:

    {"shotId": "sh_<slug>_<rid>", "field": "previsPlan", "baseRevision": 3, "value": {...the proposed plan...},
     "shot": {"label": "S03", "tabKey": "cinema-studio", "rowId": "b..."},   # for people: where the shot is
     "author": {"kind": "agent", "key": "sheet_ops"} | {"kind": "member", "id": "<actor id>"},
     "display": "S03"}

The proposal's ``content`` is its short summary. ``shot`` only tells the stage and the proposal cards where to open the
shot; it pins nothing. Approving writes the value through the field's own revisioned writer with ``baseRevision``
(``story_previs.put`` for ``previsPlan``); if the stored field moved since, nothing is written and the decision answers
409 with a sentence that names the shot (localized through ``project_docs.error_messages``), so the proposal stays
pending like any other conflicting chat or dispatch proposal.

The fields a proposal may change are ``FIELDS``. ``previsPlan`` is the first. ``look`` joins once SPEC_19's
``project_docs/story_look.py`` is on main: give it a ``Field`` with its revision reader, validator, revisioned writer
and its own conflict and invalid sentences (each with a pattern in ``project_docs/error_messages.py``).

``propose`` (or ``propose_from_tool`` with a tool context) is the one way in, and it validates the value when the
proposal is made. The crew's way in is ``propose_previs_ops`` (SPEC_20 R27, ``project_assistant/previs_ops.py``): its
proposals also carry ``details`` in the target, ``ops`` (the operations), ``opsHash``, ``solve`` ({status: "solved" |
"ops_only", by: "headless" | "stage", version, warnings, ...}), ``preview`` (a contact sheet {url, assetId, width,
height, frames} or null) and later ``vision`` (an optional model note). A ``previsPlan`` proposal made of operations
without a headless browser has ``value`` null until the reviewer's 3D Stage attaches its solve
(``previs_ops.attach_solution``); ``write`` refuses it until then, so an approval never writes an unsolved plan.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from project_assistant import privacy, store
from project_docs import repository as repo
from project_docs import story_openapi as story
from project_docs import story_previs

ACTION = "shot_meta"
MAX_SUMMARY = 500
READ_ONLY = "Read-only crew members cannot modify a production."
NOT_EDITABLE = "A shot proposal is applied as proposed; it cannot be edited first. Generate a new proposal."
UNKNOWN_FIELD = "This proposal changes a shot field that cannot be proposed."
SHOT_NOT_FOUND = "Shot not found."
SHOT_DELETED = "Shot {label} was deleted after this proposal was made. Nothing was applied; generate a new proposal."
NEEDS_SOLVE = ("The 3D plan proposed for shot {label} is still operations only. Open it in the 3D Stage to solve and "
               "preview it before approving; nothing was applied.")
DETAIL_KEYS = ("ops", "opsHash", "solve", "preview", "vision")  # what a proposal made of 3D operations adds (R27, R28)


class ProposalError(Exception):
    """A shot meta proposal that cannot be made; status is the HTTP status a caller would answer with."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Field:
    """One shot meta field a proposal may change, and how to read, check and write it by revision."""
    name: str
    noun: str                                  # for the people reading a refusal at creation ("3D plan")
    revision: Callable                         # (conn, shot_id) -> the stored revision (0 before the first write)
    validate: Callable                         # (conn, slug, value) -> None, or raise story.StoryError
    write: Callable                            # (conn, slug, shot_id, value, base, actor_id) -> the new revision
    conflict_code: str                         # the StoryError code the writer raises for a stale base revision
    conflict: str                              # "...{label}...{base}...{current}..." (catalogued, localized)
    invalid: str                               # "...{label}...{reason}..." (catalogued, localized)


def _plan_revision(conn, shot_id):
    return story_previs.stored(story.shot_meta(conn, shot_id))["planRevision"]


def _plan_validate(conn, slug, value):
    if not isinstance(value, dict):
        story.invalid("A proposed 3D plan must be a plan object; a proposal cannot clear the stored plan.")
    story_previs.validate(value, {option["code"] for option in story_previs.cast_options(conn, slug)})


def _plan_write(conn, slug, shot_id, value, base, actor_id):
    if not isinstance(value, dict):  # put() would take None as "clear the plan"
        story.invalid("A proposed 3D plan must be a plan object; a proposal cannot clear the stored plan.")
    return story_previs.put(conn, slug, shot_id, value, base, actor_id)["planRevision"]  # validates against the cast sheet


FIELDS = {
    story_previs.FIELD: Field(
        name=story_previs.FIELD, noun="3D plan", revision=_plan_revision, validate=_plan_validate, write=_plan_write,
        conflict_code=story_previs.CONFLICT,
        conflict=("The 3D plan of shot {label} changed after this proposal was made (revision {base}, now {current}). "
                  "Nothing was applied; generate a new proposal."),
        invalid="The 3D plan proposed for shot {label} no longer fits the production: {reason} Nothing was applied; generate a new proposal."),
    # "look": Field(...) once SPEC_19's story_look.py is on main (see the module docstring).
}


# ---------- the shot ----------

def _shot_row(conn, slug, shot_id):
    """The shot's sheet row in this production, or None (unknown id, another production's shot, a deleted row)."""
    if not isinstance(shot_id, str):
        return None
    try:
        found, row = story.find_row(conn, shot_id, "shot")
    except story.StoryError:
        return None
    return row if found == slug else None


def _label(row, shot_id):
    return str(row["cells"][0] if row["cells"] else "").strip() or shot_id


def _where(row, shot_id):
    return {"label": _label(row, shot_id), "tabKey": row["tabKey"], "rowId": row["rid"]}


# ---------- making a proposal ----------

def _author(conn, owner_id, message_id, agent_key, author_id):
    if agent_key:
        return {"kind": "agent", "key": str(agent_key)}
    if author_id:
        if str(author_id) not in repo.member_names(conn):
            raise ProposalError(400, "The proposal's author is not on the crew.")
        return {"kind": "member", "id": str(author_id)}
    if message_id is not None:
        message = store.message(conn, message_id)
        if message and message.get("agent_key"):
            return {"kind": "agent", "key": message["agent_key"]}
    return {"kind": "member", "id": str(owner_id)}


def propose(conn, slug, owner_id, shot_id, value, *, field=story_previs.FIELD, base_revision=None, summary="",
            agent_key=None, author_id=None, message_id=None, details=None):
    """Create a pending ``shot_meta`` proposal for owner_id to decide, in the caller's transaction; return it.

    value is checked by the field's validator now, so a proposal is never made of something that could not be
    written. base_revision is the revision the value was worked out from (default: the stored one); a proposal
    already behind the stored field is refused. The author is the agent (agent_key, or the agent of message_id)
    or a crew member (author_id); without either it is the owner. details: the DETAIL_KEYS of a proposal made of
    3D operations (previs_ops); with operations, a ``previsPlan`` value may be None (solved later in the 3D Stage).
    Raises ProposalError."""
    spec = FIELDS.get(field)
    if spec is None:
        raise ProposalError(400, f"Shot proposals can change {', '.join(FIELDS)}, not {field!r}.")
    row = _shot_row(conn, slug, shot_id)
    if row is None:
        raise ProposalError(404, SHOT_NOT_FOUND)
    where = _where(row, shot_id)
    current = spec.revision(conn, shot_id)
    base = current if base_revision is None else base_revision
    if isinstance(base, bool) or not isinstance(base, int) or base < 0:
        raise ProposalError(400, "baseRevision must be a whole number of at least 0.")
    if base != current:
        raise ProposalError(409, f"The {spec.noun} of shot {where['label']} is at revision {current}, not {base}. "
                                 "Read it again before proposing.")
    extra = {key: details[key] for key in DETAIL_KEYS if isinstance(details, dict) and key in details}
    if value is None and spec.name == story_previs.FIELD and isinstance(extra.get("ops"), list) and extra["ops"]:
        pass  # operations only: solved and checked by the 3D Stage before anyone can approve it
    else:
        try:
            spec.validate(conn, slug, value)
        except story.StoryError as exc:
            raise ProposalError(422, f"The proposed {spec.noun} for shot {where['label']} is not valid: {exc}") from None
    if not isinstance(summary, str) or len(summary.strip()) > MAX_SUMMARY:
        raise ProposalError(400, f"summary must be text of at most {MAX_SUMMARY} characters.")
    text = privacy.sanitize(summary.strip(), privacy.mode(conn, slug))
    author = _author(conn, owner_id, message_id, agent_key, author_id)
    target = {"shotId": shot_id, "field": spec.name, "baseRevision": base, "value": value, "shot": where,
              "author": author, "display": where["label"], **extra}
    proposal_id = store.create_proposal(conn, slug, owner_id, message_id, ACTION, target, text)
    if author["kind"] == "agent":
        with conn.cursor() as cur:
            cur.execute("UPDATE projectops.assistant_proposal SET agent_key=%s WHERE id=%s", (author["key"], proposal_id))
    return store.proposal(conn, proposal_id)


def propose_from_tool(ctx, conn, shot_id, value, **options):
    """``propose`` for a crew tool: the owner and conversation come from the tool context, and a dispatched turn
    attaches the proposal to its dispatch like every other proposal (orchestrator.attach_proposal)."""
    proposal = propose(conn, ctx.slug, ctx.me.actor_id, shot_id, value, message_id=getattr(ctx, "message_id", None), **options)
    if getattr(ctx, "dispatch_id", None):
        from project_assistant.orchestrator import attach_proposal
        attach_proposal(conn, ctx, proposal["id"])
        proposal = store.proposal(conn, proposal["id"])
    return proposal


# ---------- approving one ----------

def write(conn, me, slug, target):
    """Write an approved proposal's value as me, pinned by its field revision. Returns (status, payload) like
    ``project_assistant.service._write``: 409 (the proposal stays pending) when the shot or its field moved on."""
    if not me.can_write:
        return 403, {"error": READ_ONLY}
    spec = FIELDS.get(target.get("field"))
    if spec is None:
        return 400, {"error": UNKNOWN_FIELD}
    shot_id = target.get("shotId")
    row = _shot_row(conn, slug, shot_id)
    if row is None:
        return 409, {"error": SHOT_DELETED.format(label=(target.get("shot") or {}).get("label") or shot_id)}
    label, base = _label(row, shot_id), target.get("baseRevision")
    if target.get("value") is None:  # operations not solved yet (SPEC_20 R27): never write an unsolved plan
        return 409, {"error": NEEDS_SOLVE.format(label=label)}
    try:
        revision = spec.write(conn, slug, shot_id, target.get("value"), base, me.actor_id)
    except story.StoryError as exc:
        if exc.code == spec.conflict_code:
            current = (exc.details or {}).get("currentRevision")
            return 409, {"error": spec.conflict.format(label=label, base=base, current=current)}
        if exc.code == "DRAMA_VALIDATION_FAILED":  # e.g. a cast code was taken off the cast sheet since
            return 409, {"error": spec.invalid.format(label=label, reason=str(exc))}
        return exc.status, {"error": str(exc)}
    return 200, {"shot_meta": {"shotId": shot_id, "field": spec.name, "revision": revision}}


# ---------- reading them ----------

def card_target(target):
    """The target as proposal lists carry it: everything but the value (up to 64 KB of plan, read by shot)."""
    return {key: value for key, value in (target or {}).items() if key != "value"}


def pending(conn, slug, shot_id, *, owner_id=None):
    """Pending shot_meta proposals for one shot, oldest first; owner_id keeps only that person's."""
    with conn.cursor() as cur:
        cur.execute(f"""SELECT {store.PROPOSAL_COLUMNS} FROM projectops.assistant_proposal
                        WHERE project_slug=%s AND action=%s AND status='pending' AND target->>'shotId'=%s
                          AND (%s::uuid IS NULL OR owner_id=%s::uuid) ORDER BY id""",
                    (slug, ACTION, shot_id, owner_id, owner_id))
        return [store._clean(row) for row in store._dicts(cur)]


def _author_view(conn, slug, author, names, agents):
    author = author if isinstance(author, dict) else {}
    if author.get("kind") == "agent":
        key = str(author.get("key") or "")
        if key not in agents:
            from project_assistant import agent_registry
            profile = agent_registry.get_agent(conn, slug, key, effective=False) or {}
            agents[key] = profile.get("display_name") or key
        return {"kind": "agent", "key": key, "name": agents[key]}
    actor = str(author.get("id") or "")
    return {"kind": "member", "id": actor, "name": names.get(actor, "")}


def listing(conn, me, slug, shot_id):
    """GET /projects/api/{slug}/assistant/shots/{shotId}/proposals: my pending proposals for this shot.

    Like the assistant state and the orchestration board, a person sees the proposals made for them; canDecide says
    whether this person may approve or reject one (a read-only crew member sees theirs, read-only)."""
    row = _shot_row(conn, slug, shot_id)
    if row is None:
        return 404, {"error": SHOT_NOT_FOUND}
    names, agents = repo.member_names(conn), {}
    revisions = {name: spec.revision(conn, shot_id) for name, spec in FIELDS.items()}
    items = []
    for proposal in pending(conn, slug, shot_id, owner_id=me.actor_id):
        target = proposal.get("target") or {}
        field = target.get("field")
        items.append({
            "id": proposal["id"], "action": ACTION, "status": proposal["status"], "shotId": shot_id, "field": field,
            "baseRevision": target.get("baseRevision"), "currentRevision": revisions.get(field), "value": target.get("value"),
            "summary": proposal.get("content") or "", "shot": target.get("shot") or _where(row, shot_id),
            "author": _author_view(conn, slug, target.get("author"), names, agents), "createdAt": proposal.get("created_at"),
            **{key: target.get(key) for key in DETAIL_KEYS if key in target},
            "canDecide": bool(me.can_write and proposal["owner_id"] == me.actor_id and not proposal.get("race_group_task_id")),
        })
    return 200, {"shotId": shot_id, "shot": _where(row, shot_id), "revisions": revisions, "proposals": items}
