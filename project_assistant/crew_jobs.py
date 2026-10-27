"""Crew planning jobs (SPEC_20 fixed decisions 9, 10, 12; R7, R19, R20, R21, R22, R23).

A crew job is one judgment step a built-in crew role makes for one target: a shot (the Cinematographer writing a beat
sheet or choosing the camera; who is in the shot), an asset (Art writing a locked appearance description or a new
look), a scene (who is in each of its shots) or an episode (the Screenwriter's adaptation and shot breakdown
candidates). Every job has the four things of fixed decision 12: a JSON output schema, a validator in code, at most
one retry, and a rule fallback. A job declares them once (:class:`CrewJob`, registered in ``JOBS``):

    kind          'beats' | 'camera' (crew_planning); 'description' | 'look' | 'appearances' (crew_art);
                  'adaptation' | 'breakdown' (crew_writing); 'continuity' (crew_continuity)
    role          the built-in crew agent that does it (agent_registry.ROSTER key)
    targets       the target kinds it is asked on: ('shot',) by default; see TARGETS
    schema        the JSON Schema the model answers with (``response_format`` on a tool-free round, else in the prompt)
    effort        the job's own reasoning_effort (SPEC_20 R10)
    gather        (ctx, conn, target_id, request) -> {'input', 'reads', ...}: context from the R16 read tools
    instructions  (input) -> system prompt          prompt  (input) -> the user turn
    validate      (output, input) -> [errors]       fallback  (input) -> an output built by rules
    propose       (ctx, conn, gathered, outcome) -> result: proposals only, never a write (decision 9). Table
                  proposals are cell-scoped (R17); the Screenwriter's candidates are writing previews.
    check_row     (row) -> a sentence when the job cannot apply to this sheet row (shot and asset targets)
    check         (conn, me, target) -> a sentence when the job cannot apply to this target (any target)
    summary       (record) -> the crew board's line for a finished job, when the default does not fit

Targets (one API; the pre-production flow, R24, drives it)::

    {'kind': 'shot',    'id': 'sh_<slug>_<rowId>'}     a slate row (cinema-studio or openjutsu-lab)
    {'kind': 'asset',   'id': 'as_<slug>_<rowId>'}     a Soul Cast row (a cast member, set, prop or one of its looks)
    {'kind': 'scene',   'id': 'sc_<slug>_<NN>_S<NN>'}  a scene of an episode's working script
    {'kind': 'episode', 'id': 'ep_<slug>_<NN>'}        an episode

    request(conn, me, slug, kind, target, body, *, automatic=False, flow=None) -> the public job record
        target is a {kind, id} dict, or a bare shot id (the shot routes' form, kept). 422 when the job is not asked
        on that kind of target or the target cannot take it; 404 for a target of another production; 409
        DRAMA_CREW_NOT_READY / DRAMA_AUTOMATION_PAUSED as below. The same member's active job of one kind for one
        target is returned instead of a second one. flow ({flowId, stage}) marks a job of the pre-production flow
        (crew_preproduction, R24), which checked the role's readiness itself before writing anything.
    listing(conn, me, slug, target_id) -> this member's jobs for one target, newest first.

A job record carries ``target`` ({kind, id}), ``targetId`` and ``targetLabel``; a shot job also keeps ``shotId`` and
``shotLabel`` as before, so the shot routes, listings and the crew board read old and new records alike. The routes
for each target live in project_docs/story_crew.py.

Runner (:func:`run_pipeline`): one governed model call asking for the schema, validate, at most one retry that shows
the model its answer and the validation errors, and if that is still invalid the rule fallback, marked
``source: 'rule_fallback'`` in the job result and on the proposal. A malformed or empty answer counts as invalid
output. A missing model is not invalid output: when the crew cannot work (a readiness blocker for the role:
no worker, model unreachable or missing, policy, pricing, credentials) :func:`request` answers 409
``DRAMA_CREW_NOT_READY`` and writes nothing (R7); when the model goes away mid-job the job fails with its failure
class (SPEC_20 R12) and proposes nothing. The rule fallback stands in for bad output only.

Pre-production (R24, crew_preproduction): a flow's stage jobs are ordinary jobs asked with ``automatic=True`` and
marked with the flow (``flowId``, ``flowStage``). The worker asks the flow before a flow job calls its model and again
before it proposes; a flow that ended, or whose locked content changed, cancels the job and nothing is proposed. While
the production's automatic work is paused (R40) no automatic job is claimed: queued ones wait, running ones finish.

States of a job record (``projectops.story_record`` kind ``crew_job``)::

    queued -> running -> succeeded | failed        queued | running -> canceled (by the requester or an admin)

Jobs run on the assistant worker (worker.poll_once claims them before chat turns and dispatches), one at a time per
claim, with a lease; a job whose worker died fails when its lease runs out. Canceling cannot interrupt a model call
already in flight (SPEC_20 pitfall M): the runner checks before every call and before it proposes, so a canceled
job never writes. Every model call is governed (ProviderAdmission: reserved, attributed to the role and the
requester, accounted under the session ``crew:<jobId>``, a loopback model unbilled), every context read is audited by
the read tools, and the job record keeps the attempts, usage, the answering model and the context hashes. Manual
jobs are never blocked by the automation switch; ``automatic=True`` callers (R25, a later wave) are.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Callable

KIND = 'crew_job'  # projectops.story_record kind
ACTIVE = ('queued', 'running')
FINISHED = ('succeeded', 'failed', 'canceled')
LEASE_SECONDS = 15 * 60
MODEL_TIMEOUT = 300
SOURCE_MODEL, SOURCE_FALLBACK = 'model', 'rule_fallback'
NOT_READY = 'DRAMA_CREW_NOT_READY'
PAUSED = 'DRAMA_AUTOMATION_PAUSED'
BAD_OUTPUT = ('empty', 'output')  # failure classes that describe the answer, not the transport: they count as invalid
JOB_ID = re.compile(r'cj_[0-9a-f]{32}')
BOARD_LIMIT = 100
TARGETS = ('shot', 'asset', 'scene', 'episode')
TARGET_NOUN = {'shot': 'the shot', 'asset': 'the asset card', 'scene': "the scene's shots", 'episode': 'the episode'}
JOB_MODULES = ('crew_planning', 'crew_art', 'crew_writing', 'crew_continuity')  # the modules that declare the built-in jobs
PAUSED_SETTING = r'"paused"\s*:\s*true'  # automation.KEY's JSON value while paused (read in SQL by claim)
RETRY_NOTE = ('Your answer did not pass validation:\n{errors}\n'
              'Fix exactly these problems and answer again with the whole JSON object, nothing else.')
# Readiness blockers in words, for the 409 sentence (the UI shows its own text for each fix hint).
BLOCKER_TEXT = {
    'worker_not_running': 'the crew worker is not running',
    'provider_unreachable': 'the model server is not reachable',
    'model_missing': 'the model is not installed',
    'kind_removed': 'the model runtime was removed',
    'cli_blocked': 'the role runs on a command-line agent',
    'auth_missing': 'the model credentials are missing',
    'network_policy': 'the network or production policy does not allow this model',
    'pricing_missing': 'the model has no price limit',
    'agent_disabled': 'the role is disabled',
    'reservations_stuck': 'earlier model calls are still unsettled',
}


class Canceled(Exception):
    """The job was canceled; nothing more is written."""


class Refused(Exception):
    """Governance or configuration refused the model call (not a model failure)."""


class ModelUnavailable(Exception):
    """The model could not answer (transport, quota, auth, timeout, GPU): no rule fallback, no proposal."""

    def __init__(self, reply, attempts):
        super().__init__(reply.error or reply.failure)
        self.reply, self.attempts = reply, attempts


class FallbackFailed(Exception):
    """Even the rule fallback does not pass the job's validation (the shot itself is unusable)."""

    def __init__(self, errors, attempts):
        super().__init__('; '.join(errors))
        self.errors, self.attempts = errors, attempts


def no_options(body):
    if body:
        raise ValueError('This crew request takes no fields: ' + ', '.join(sorted(body)) + '.')
    return {}


@dataclass(frozen=True)
class CrewJob:
    kind: str
    role: str
    title: str
    schema: dict
    effort: str
    gather: Callable
    instructions: Callable
    prompt: Callable
    validate: Callable
    fallback: Callable
    propose: Callable
    options: Callable = no_options  # (request body) -> normalized options, or raise ValueError
    check_row: Callable | None = None  # (sheet row) -> a sentence when the job cannot apply to this sheet, else None
    timeout: int = MODEL_TIMEOUT
    targets: tuple = ('shot',)  # the target kinds it is asked on (TARGETS)
    check: Callable | None = None  # (conn, me, Target) -> a sentence when the job cannot apply to this target
    summary: Callable | None = None  # (record) -> the crew board line of a succeeded job


JOBS: dict[str, CrewJob] = {}


def declare(job: CrewJob) -> CrewJob:
    if job.kind in JOBS:
        raise ValueError(f'Crew job {job.kind!r} is declared twice.')
    if job.effort not in ('low', 'medium', 'high'):
        raise ValueError('A crew job effort is low, medium or high.')
    if not job.targets or set(job.targets) - set(TARGETS):
        raise ValueError('A crew job is asked on targets among ' + ', '.join(TARGETS) + '.')
    JOBS[job.kind] = job
    return job


def job(kind) -> CrewJob:
    if kind not in JOBS:
        import importlib
        for module in JOB_MODULES:  # each declares its built-in jobs on import
            importlib.import_module('project_assistant.' + module)
    return JOBS[kind]


# ---------- targets ----------

@dataclass(frozen=True)
class Target:
    """One resolved job target: what it is, where it lives and how the crew board names it."""
    kind: str
    id: str
    slug: str
    label: str
    tab_key: str | None = None
    row_id: str | None = None
    row: dict | None = None        # shot and asset targets: the sheet row (story_openapi.table_rows shape)
    episode: dict | None = None    # scene and episode targets
    scene: dict | None = None      # scene targets

    def ref(self):
        return {'kind': self.kind, 'id': self.id}


def target_ref(target):
    """{kind, id} of a request's target: a dict, or a bare shot id (the shot routes' form)."""
    if isinstance(target, str):
        return {'kind': 'shot', 'id': target}
    if not isinstance(target, dict) or target.get('kind') not in TARGETS or not isinstance(target.get('id'), str) or not target['id']:
        raise ValueError('A crew target is {"kind": "' + '|'.join(TARGETS) + '", "id": text}.')
    return {'kind': target['kind'], 'id': target['id']}


def resolve_target(conn, ref):
    """The Target of a {kind, id}; story_openapi.StoryError 404 when it does not exist."""
    from project_docs import story_openapi as story
    kind, identifier = ref['kind'], ref['id']
    if kind in ('shot', 'asset'):
        slug, row = story.find_row(conn, identifier, kind)
        cells = row['cells'] or ['']
        label = cells[0] or identifier
        if kind == 'asset' and len(cells) > 1 and cells[1].strip() and cells[1].strip() != cells[0]:
            label = f'{label} {cells[1].strip()}'
        return Target(kind, identifier, slug, label[:160], row['tabKey'], row['rid'], row=row)
    if kind == 'scene':
        ep, scene = story.locate_scene(conn, identifier)
        title = re.sub(r'^Scene\s*\d+\s*[:：.-]?\s*', '', scene['title'], flags=re.I).strip()
        label = f"Scene {scene['sceneIndex']:02d}" + (f': {title}' if title else '')
        return Target(kind, identifier, ep['slug'], label[:160], ep['tabKey'], episode=ep, scene=scene)
    ep = story.episode(conn, identifier)
    return Target('episode', identifier, ep['slug'], (ep.get('title') or f"Episode {ep['episodeIndex']}")[:160],
                  ep['tabKey'], episode=ep)


def target_of(record):
    """A record's {kind, id}; records from before targets were general are shot jobs."""
    return record.get('target') or {'kind': 'shot', 'id': record['shotId']}


# ---------- the pipeline: call, validate, retry once, fall back ----------

@dataclass
class Reply:
    ok: bool
    answer: str = ''        # the text the model sent, also when it was malformed
    failure: str = ''       # model_client.FAILURE_CLASSES when not ok
    error: str = ''
    usage: dict = field(default_factory=dict)
    model: str = ''
    seconds: float = 0.0


@dataclass
class Outcome:
    source: str             # SOURCE_MODEL | SOURCE_FALLBACK
    output: dict
    attempts: list
    errors: list            # the last validation errors (a fallback's reason)


def parse_answer(answer):
    """(object, problem): the answer's one JSON object, thinking and code fences removed."""
    text = re.sub(r'(?s)<think>.*?</think>', '', answer or '').strip()
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text).strip()
    try:
        value = json.loads(text)
    except ValueError:
        start, end = text.find('{'), text.rfind('}')
        try:
            value = json.loads(text[start:end + 1]) if 0 <= start < end else None
        except ValueError:
            value = None
    if not isinstance(value, dict):
        return None, 'The answer is not one JSON object.'
    return value, ''


def run_pipeline(crew_job, job_input, call_model, *, cancelled=None):
    """Run one job on its input: the model's answer if it validates (first or after one retry), else the rule fallback.

    call_model(instructions, turn_text, history) -> Reply. Raises ModelUnavailable when the model cannot answer,
    Canceled when cancelled() turns true before a call or before the fallback, FallbackFailed when even the rule
    output is invalid."""
    instructions = crew_job.instructions(job_input)
    text, history, attempts, errors = crew_job.prompt(job_input), [], [], []
    for number in (1, 2):
        if cancelled and cancelled():
            raise Canceled()
        reply = call_model(instructions, text, history)
        entry = {'attempt': number, 'model': reply.model, 'seconds': reply.seconds, 'usage': dict(reply.usage)}
        if not reply.ok and reply.failure not in BAD_OUTPUT:
            attempts.append({**entry, 'valid': False, 'failure': reply.failure or 'provider', 'error': reply.error[:300]})
            raise ModelUnavailable(reply, attempts)
        if reply.answer.strip():
            output, problem = parse_answer(reply.answer)
            errors = [problem] if problem else list(crew_job.validate(output, job_input))
        else:
            output, errors = None, ['The answer was empty.']
        attempts.append({**entry, 'valid': not errors, 'errors': [e[:300] for e in errors[:8]]})
        if not errors:
            return Outcome(SOURCE_MODEL, output, attempts, [])
        history = history + [{'role': 'user', 'content': text},
                             {'role': 'assistant', 'content': reply.answer.strip() or '(no answer)'}]
        text = RETRY_NOTE.format(errors='\n'.join('- ' + e for e in errors[:12]))
    if cancelled and cancelled():
        raise Canceled()
    output = crew_job.fallback(job_input)
    problems = list(crew_job.validate(output, job_input))
    if problems:
        raise FallbackFailed(problems, attempts)
    return Outcome(SOURCE_FALLBACK, output, attempts, errors)


def model_caller(config, *, admission=None, effort=None, schema_name, schema, timeout=MODEL_TIMEOUT, opener=None):
    """call_model for run_pipeline: one tool-free OpenAI-compatible call asking for the schema (SPEC_20 R8, R10)."""
    from project_assistant import agent_registry, providers, tools
    from project_assistant.execution_governance import AdmissionError

    def no_tools(*_):
        raise ValueError('Crew jobs call no tools.')

    def call(instructions, text, history):
        seen = []
        try:
            result = providers.run_openai_compat_turn(
                config=config, instructions=instructions, turn_text=text, history=history, call_tool=no_tools,
                timeout=timeout, tool_specs=[], reasoning_effort=effort, on_text=seen.append,
                json_schema={'name': schema_name, 'schema': schema},
                **({'admission': admission} if admission is not None else {}), **({'opener': opener} if opener else {}))
        except (AdmissionError, agent_registry.AgentError, tools.ToolError) as exc:
            raise Refused('Model governance refused the call: ' + str(exc)) from None
        ok = result.status == 'ok'
        # A tool call where none was offered ('lockdown') is a malformed answer, not a transport failure.
        failure = '' if ok else (result.failure or ('output' if result.status == 'lockdown' else 'provider'))
        return Reply(ok=ok, answer=(result.answer if ok else (seen[-1] if seen else '')) or '',
                     failure=failure, error=result.error or ('The model called a tool instead of answering.' if result.status == 'lockdown' else ''),
                     usage=dict(result.usage), model=result.model or config.model, seconds=result.seconds)
    return call


# ---------- records ----------

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _load(conn, job_id, *, lock=False):
    with conn.cursor() as cur:
        cur.execute('SELECT data, project_slug FROM projectops.story_record WHERE id=%s AND kind=%s'
                    + (' FOR UPDATE' if lock else ''), (job_id, KIND))
        row = cur.fetchone()
    return (dict(row[0], slug=row[1]) if row else None)


def _save(conn, record):
    from project_docs import story_openapi as story
    data = {k: v for k, v in record.items() if k != 'slug'}
    story.store(conn, record['jobId'], KIND, data, record['slug'], record['requestedBy'])
    return record


def public(record):
    keys = ('jobId', 'kind', 'role', 'shotId', 'shotLabel', 'status', 'source', 'requestedBy', 'requestedAt', 'startedAt',
            'finishedAt', 'request', 'result', 'error', 'failure', 'attempts', 'model', 'usage', 'automatic', 'flowId', 'flowStage')
    target = target_of(record)
    return {**{k: record.get(k) for k in keys}, 'target': target, 'targetId': target['id'],
            'targetLabel': record.get('targetLabel') or record.get('shotLabel')}


def _records(conn, slug, *, owner=None, target_id=None, limit=BOARD_LIMIT):
    with conn.cursor() as cur:
        cur.execute("""SELECT data FROM projectops.story_record WHERE kind=%s AND project_slug=%s
                       AND (%s::uuid IS NULL OR owner_id=%s::uuid)
                       AND (%s::text IS NULL OR COALESCE(data->>'targetId', data->>'shotId')=%s)
                       ORDER BY data->>'requestedAt' DESC, id DESC LIMIT %s""",
                    (KIND, slug, owner, owner, target_id, target_id, limit))
        return [dict(row[0], slug=slug) for row in cur.fetchall()]


def listing(conn, me, slug, target_id):
    """This member's crew jobs for one target (a shot, asset, scene or episode id), newest first."""
    return [public(r) for r in _records(conn, slug, owner=me.actor_id, target_id=target_id, limit=20)]


def running_count(conn, slug, role):
    """Running crew jobs of one role: the roster counts them with its dispatches."""
    with conn.cursor() as cur:
        cur.execute("""SELECT count(*) FROM projectops.story_record WHERE kind=%s AND project_slug=%s
                       AND data->>'status'='running' AND data->>'role'=%s""", (KIND, slug, role))
        return cur.fetchone()[0]


# ---------- requesting a job ----------

def readiness_blockers(conn, me, slug, role):
    """The readiness blockers that stop this role (crew_readiness probes local endpoints; it ends the transaction)."""
    from project_assistant import agent_registry, crew_readiness
    profile = agent_registry.get_agent(conn, slug, role, effective=False)
    if not profile:
        return [{'code': 'agent_disabled', 'agentKey': role, 'fix': 'enable_agent'}]
    payload = crew_readiness.readiness(conn, me, slug)
    return crew_readiness.blocks(payload, profile)


def not_ready_message(blockers, role_name):
    reasons = list(dict.fromkeys(BLOCKER_TEXT.get(b['code'], b['code'].replace('_', ' ')) for b in blockers))
    return (f"The crew can't work yet: {'; '.join(reasons)}. The {role_name} needs a working model before it can "
            "propose anything; the crew board lists each fix. Nothing was written.")


def _relock(conn, slug):
    from project_assistant import orchestrator as cp
    cp.lock_project(conn, slug)
    with conn.cursor() as cur:
        cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('story-write:' + slug,))


def request(conn, me, slug, kind, target, body, *, automatic=False, flow=None):
    """Queue one crew job for a target (manual unless automatic), or explain with 409 why the crew cannot work.

    target is {'kind': 'shot'|'asset'|'scene'|'episode', 'id'} or a bare shot id. Raises story_openapi.StoryError:
    422 for a bad request or a target the job does not take, 404 for an unknown target or one of another production,
    409 DRAMA_CREW_NOT_READY (nothing written) when a readiness blocker stops the role, 409 DRAMA_AUTOMATION_PAUSED
    for an automatic request while paused. The same member's active job of the same kind for the same target is
    returned instead of a second one. flow: {'flowId', 'stage'} of the pre-production flow asking; it has checked the
    role's readiness before writing anything (a readiness probe ends the transaction), so it is not checked here."""
    from project_assistant import agent_registry, automation
    from project_docs import repository as repo, story_openapi as story
    crew_job = job(kind)
    if not isinstance(body, dict):
        story.invalid('Send the crew request as a JSON object.')
    try:
        ref = target_ref(target)
        options = crew_job.options(body)
    except ValueError as exc:
        story.invalid(str(exc))
    if ref['kind'] not in crew_job.targets:
        story.invalid(f"{crew_job.title} is asked on {' or '.join('a ' + t for t in crew_job.targets)}, not on a {ref['kind']}.")
    if automatic and automation.automation_paused(conn, slug):
        raise story.StoryError(409, PAUSED, 'Automatic crew work is paused for this production.')
    resolved = resolve_target(conn, ref)
    if resolved.slug != slug:
        raise story.StoryError(404, 'DRAMA_NOT_FOUND', 'Resource not found.')
    problem = crew_job.check_row(resolved.row) if crew_job.check_row and resolved.row is not None else None
    problem = problem or (crew_job.check(conn, me, resolved) if crew_job.check else None)
    if problem:
        story.invalid(problem)
    if flow is None:
        blockers = readiness_blockers(conn, me, slug, crew_job.role)  # may end the transaction: lock again below
        _relock(conn, slug)
        if blockers:
            name = next((r[1] for r in agent_registry.ROSTER if r[0] == crew_job.role), crew_job.role)
            raise story.StoryError(409, NOT_READY, not_ready_message(blockers, name),
                                   details={'agentKey': crew_job.role, 'blockers': blockers})
    for record in _records(conn, slug, owner=me.actor_id, target_id=resolved.id, limit=20):
        if record['kind'] == kind and record['status'] in ACTIVE and target_of(record) == resolved.ref():
            return public(record)
    job_id = 'cj_' + uuid.uuid4().hex
    record = {'jobId': job_id, 'kind': kind, 'role': crew_job.role, 'target': resolved.ref(), 'targetId': resolved.id,
              'targetLabel': resolved.label, 'tabKey': resolved.tab_key, 'rowId': resolved.row_id, 'status': 'queued',
              'requestedBy': me.actor_id, 'requestedAt': now(), 'request': options, 'automatic': bool(automatic),
              'attempts': [], 'usage': {}, 'slug': slug}
    detail = {'kind': kind, 'role': crew_job.role, 'target': resolved.ref(), 'request': options}
    if flow is not None:
        record.update(flowId=flow['flowId'], flowStage=flow['stage'])
        detail.update(flowId=flow['flowId'], flowStage=flow['stage'])
    if resolved.kind == 'shot':
        record.update(shotId=resolved.id, shotLabel=resolved.label)
        detail['shotId'] = resolved.id
    _save(conn, record)
    repo.add_audit(conn, slug, action='crew_job_requested', actor_id=me.actor_id, tab_key=resolved.tab_key, target=job_id,
                   detail=detail)
    return public(record)


def cancel(conn, me, slug, job_id):
    """Cancel a queued or running job (its requester or a showrunner); a finished job answers 409."""
    from project_assistant import orchestrator as cp
    from project_docs import repository as repo
    cp.actor(conn, slug, me, write=True)
    record = _load(conn, job_id, lock=True) if JOB_ID.fullmatch(job_id or '') else None
    if not record or record['slug'] != slug or (record['requestedBy'] != me.actor_id and getattr(me, 'role', '') != 'admin'):
        raise cp.OrchestrationError(404, 'Crew job not found.')
    if record['status'] not in ACTIVE:
        raise cp.OrchestrationError(409, 'This crew job has already finished.')
    record.update(status='canceled', finishedAt=now(), canceledBy=me.actor_id)
    _save(conn, record)
    repo.add_audit(conn, slug, action='crew_job_canceled', actor_id=me.actor_id, tab_key=record.get('tabKey'),
                   target=job_id, detail={'kind': record['kind'], 'target': target_of(record)})
    return public(record)


def cancel_jobs(conn, slug, job_ids, *, by=None, reason=''):
    """Cancel the flow's jobs among these that are still queued or running (the pre-production flow's stop and
    cancel, R24); a member's own job the flow reused stays theirs. Returns the ids canceled."""
    from project_docs import repository as repo
    canceled = []
    for job_id in dict.fromkeys(job_ids):
        record = _load(conn, job_id, lock=True)
        if not record or record['slug'] != slug or record['status'] not in ACTIVE or not record.get('flowId'):
            continue
        record.update(status='canceled', finishedAt=now(), canceledBy=by, cancelReason=(reason or '')[:300])
        _save(conn, record)
        repo.add_audit(conn, slug, action='crew_job_canceled', actor_id=by, tab_key=record.get('tabKey'), target=job_id,
                       detail={'kind': record['kind'], 'target': target_of(record), 'flowId': record['flowId'], 'reason': (reason or '')[:300]})
        canceled.append(job_id)
    return canceled


def cancel_request(conn, me, slug, job_id, body):
    """POST /projects/api/{slug}/orchestration/crew-jobs/{jobId}/cancel (the crew board's cancel)."""
    from project_assistant import orchestration_service as control
    def action():
        control.object_body(body or {}, ('reason', 'client_request_id'))
        return {'job': cancel(conn, me, slug, job_id)}
    return control.result(action)


# ---------- the worker side ----------

def _expire(conn):
    """Running jobs past their lease: their worker stopped. They fail; nothing was proposed."""
    with conn.cursor() as cur:
        cur.execute("""SELECT id FROM projectops.story_record WHERE kind=%s AND data->>'status'='running'
                       AND (data->>'leaseUntil')::timestamptz < NOW() FOR UPDATE SKIP LOCKED""", (KIND,))
        stale = [row[0] for row in cur.fetchall()]
    for job_id in stale:
        record = _load(conn, job_id)
        record.update(status='failed', finishedAt=now(), error='The crew worker stopped while this job ran. Ask the crew again.')
        _save(conn, record)


def claim(conn, worker_id, *, slug=None):
    """The oldest queued crew job (of one production when slug is given), leased to this worker; None when there is
    none. An automatic job (the pre-production flow's) waits while its production's automatic work is paused (R40).
    The caller commits."""
    from project_assistant import automation
    _expire(conn)
    with conn.cursor() as cur:
        cur.execute("""SELECT id FROM projectops.story_record r WHERE kind=%s AND data->>'status'='queued'
                       AND (%s::text IS NULL OR project_slug=%s)
                       AND NOT (COALESCE(data->>'automatic', 'false') = 'true' AND EXISTS (
                           SELECT 1 FROM projectops.assistant_setting s WHERE s.project_slug=r.project_slug
                           AND s.key=%s AND s.value ~ %s))
                       ORDER BY data->>'requestedAt', id LIMIT 1 FOR UPDATE SKIP LOCKED""", (KIND, slug, slug, automation.KEY, PAUSED_SETTING))
        row = cur.fetchone()
    if not row:
        return None
    record = _load(conn, row[0])
    started = dt.datetime.now(dt.timezone.utc)
    record.update(status='running', startedAt=started.isoformat(), leaseOwner=worker_id,
                  leaseUntil=(started + dt.timedelta(seconds=LEASE_SECONDS)).isoformat())
    _save(conn, record)
    return {'crewJob': record['jobId'], 'slug': record['slug']}


def _identity(conn, actor_id):
    from project_docs import repository as repo
    from project_docs.service import Identity
    member = next((m for m in repo.active_members(conn) if m['actor_id'] == actor_id), None)
    return Identity(member['actor_id'], member['name'], member['role']) if member else None


def _status(connection_factory, job_id):
    conn = connection_factory()
    try:
        record = _load(conn, job_id)
        conn.rollback()
        return record['status'] if record else 'canceled'
    finally:
        conn.close()


def _finish(conn, job_id, worker_id, **changes):
    """Settle the job in a fresh transaction unless it was canceled or taken over meanwhile."""
    conn.rollback()
    record = _load(conn, job_id, lock=True)
    if not record or record['status'] != 'running' or record.get('leaseOwner') != worker_id:
        conn.rollback()
        return None
    record.update(finishedAt=now(), **changes)
    _save(conn, record)
    conn.commit()
    return record


def _flow_ended(conn, record):
    """A pre-production flow job whose flow ended or whose locked content changed: canceled now (crew_preproduction
    stops the flow and cancels its jobs); True means nothing more happens for this job."""
    if not record.get('flowId'):
        return False
    from project_assistant import crew_preproduction
    return crew_preproduction.guard(conn, record)


def _usage(attempts):
    total = {}
    for attempt in attempts:
        for key, value in (attempt.get('usage') or {}).items():
            if type(value) is int:
                total[key] = total.get(key, 0) + value
    return total


def execute(connection_factory, claimed, worker_id, *, opener=None):
    """Run one claimed job to its end: context, governed model calls, validation, retry, fallback, proposals.

    Returns the final status ('succeeded', 'failed', 'canceled' or 'skipped' when the lease is not ours)."""
    from project_assistant import agent_registry, tools
    from project_assistant import execution_governance as governance
    from project_assistant.agent_runtime import provider_for
    from project_docs import repository as repo, story_openapi as story
    job_id = claimed['crewJob']
    conn = connection_factory()
    attempts = []
    try:
        record = _load(conn, job_id)
        if not record or record['status'] != 'running' or record.get('leaseOwner') != worker_id:
            conn.rollback()
            return 'canceled' if record and record['status'] == 'canceled' else 'skipped'
        slug, crew_job = record['slug'], job(record['kind'])
        if _flow_ended(conn, record):  # R24: the flow stopped or was canceled, or a lock it depends on changed
            conn.commit()
            return 'canceled'
        me = _identity(conn, record['requestedBy'])
        if me is None:
            _finish(conn, job_id, worker_id, status='failed', error='The member who asked is no longer on this production.')
            return 'failed'
        ctx = tools.ToolContext(connection_factory, slug, me, None, None, agent_key=crew_job.role)
        gathered = crew_job.gather(ctx, conn, target_of(record)['id'], record.get('request') or {})
        profile = agent_registry.get_agent(conn, slug, crew_job.role)
        if not profile or not profile.get('enabled', True):
            raise Refused('The crew role that does this job is disabled.')
        try:
            config = provider_for(profile)
        except (ValueError, tools.ToolError) as exc:
            raise Refused(str(exc)) from None
        if config.kind != 'openai_compat':
            raise Refused('Crew jobs need an OpenAI-compatible model for this role.')
        record.update(context=gathered['reads'], model=config.model)
        _save(conn, record)
        conn.commit()  # no transaction across inference
        governed = governance.media_context(me, slug, agent_key=crew_job.role, accounting_session_key='crew:' + job_id,
                                            execution_key='crew:%s:%s' % (job_id, record.get('startedAt')))
        governed.connection_factory = connection_factory
        admission = governance.ProviderAdmission(governed, profile, config, 'llm_turn', purpose='crew_' + crew_job.kind)
        call = model_caller(config, admission=admission, effort=crew_job.effort, schema_name='crew_' + crew_job.kind,
                            schema=crew_job.schema, timeout=crew_job.timeout, opener=opener)
        outcome = run_pipeline(crew_job, gathered['input'], call,
                               cancelled=lambda: _status(connection_factory, job_id) != 'running')
        attempts = outcome.attempts
        conn.rollback()
        if _flow_ended(conn, record):  # checked again: the locks may have changed while the model answered
            conn.commit()
            return 'canceled'
        record = _load(conn, job_id, lock=True)
        if not record or record['status'] != 'running' or record.get('leaseOwner') != worker_id:
            conn.rollback()
            return 'canceled'
        result = crew_job.propose(ctx, conn, gathered, outcome, job_id=job_id)
        record.update(status='succeeded', finishedAt=now(), source=outcome.source, result=result, attempts=attempts,
                      usage=_usage(attempts), model=next((a['model'] for a in reversed(attempts) if a.get('model')), config.model),
                      **({'fallbackReason': outcome.errors[:8]} if outcome.source == SOURCE_FALLBACK else {}))
        _save(conn, record)
        repo.add_audit(conn, slug, action='crew_job_finished', actor_id=me.actor_id, tab_key=record.get('tabKey'), target=job_id,
                       detail={'kind': crew_job.kind, 'role': crew_job.role, 'source': outcome.source,
                               'proposalIds': result.get('proposalIds', []), 'attempts': len(attempts)})
        conn.commit()
        return 'succeeded'
    except Canceled:
        conn.rollback()
        return 'canceled'
    except ModelUnavailable as exc:
        from project_assistant.model_client import FAILURE_TEXT
        failure = exc.reply.failure or 'provider'
        done = _finish(conn, job_id, worker_id, status='failed', failure=failure, attempts=exc.attempts, usage=_usage(exc.attempts),
                       error=FAILURE_TEXT.get(failure, exc.reply.error or 'The model did not answer.'))
        return 'failed' if done else 'canceled'
    except FallbackFailed as exc:
        done = _finish(conn, job_id, worker_id, status='failed', attempts=exc.attempts, usage=_usage(exc.attempts),
                       error='The model answer failed validation twice and the rule fallback is not usable for this '
                             + target_of(record)['kind'] + ': ' + '; '.join(exc.errors[:3]))
        return 'failed' if done else 'canceled'
    except Refused as exc:
        done = _finish(conn, job_id, worker_id, status='failed', attempts=attempts, error=str(exc)[:500])
        return 'failed' if done else 'canceled'
    except story.StoryError as exc:
        done = _finish(conn, job_id, worker_id, status='failed', attempts=attempts, error=str(exc)[:500])
        return 'failed' if done else 'canceled'
    except Exception as exc:  # noqa: BLE001 - one broken job must not stop the worker
        print(f'crew job {job_id} failed: {type(exc).__name__}: {exc}', flush=True)
        done = _finish(conn, job_id, worker_id, status='failed', attempts=attempts,
                       error='The crew job failed on the server. Ask again; if it keeps failing, check the server log.')
        return 'failed' if done else 'canceled'
    finally:
        conn.close()


# ---------- the crew board ----------

def _summary(record):
    result = record.get('result') or {}
    if record['status'] != 'succeeded':
        return None
    crew_job = job(record['kind'])
    if crew_job.summary:
        return crew_job.summary(record)
    noun = TARGET_NOUN[target_of(record)['kind']]
    if result.get('unchanged'):
        return f'No change: {noun} already says this.'
    proposals = result.get('proposalIds', [])
    ids = ', '.join('#' + str(i) for i in proposals)
    waiting = ('proposals ' + ids + ' are' if len(proposals) > 1 else 'proposal ' + ids + ' is') + ' waiting on ' + noun + '.'
    if record.get('source') == SOURCE_FALLBACK:
        return 'Rule fallback, not model-written: ' + waiting
    return waiting[:1].upper() + waiting[1:]


def board_item(record):
    target = target_of(record)
    title = job(record['kind']).title + ' · ' + (record.get('targetLabel') or record.get('shotLabel') or target['id'])
    return {'id': 'crew:' + record['jobId'], 'kind': 'crew_job', 'job_id': record['jobId'],
            'shot_id': target['id'] if target['kind'] == 'shot' else None,
            'target_kind': target['kind'], 'target_id': target['id'],
            'title': title, 'status': record['status'], 'agent_key': record['role'],
            'target': {k: v for k, v in (('tab_key', record.get('tabKey')), ('row_id', record.get('rowId'))) if v},
            'created_at': record['requestedAt'], 'summary': _summary(record), 'source': record.get('source'),
            'error': record.get('error'), 'failure': record.get('failure'), 'tools_trace': []}


def board(conn, me, slug):
    """(working, done) board items of this member's crew jobs, and the production's pre-production flows (R24)."""
    from project_assistant import crew_preproduction
    records = _records(conn, slug, owner=me.actor_id)
    flows_working, flows_done = crew_preproduction.board_items(conn, me, slug)
    return (flows_working + [board_item(r) for r in records if r['status'] in ACTIVE],
            flows_done + [board_item(r) for r in records if r['status'] in FINISHED])


def counts(conn, me, slug):
    from project_assistant import crew_preproduction
    with conn.cursor() as cur:
        cur.execute("""SELECT count(*) FILTER (WHERE data->>'status' IN ('queued','running')),
                              count(*) FILTER (WHERE data->>'status' IN ('succeeded','failed','canceled'))
                       FROM projectops.story_record WHERE kind=%s AND project_slug=%s AND owner_id=%s::uuid""",
                    (KIND, slug, me.actor_id))
        working, done = cur.fetchone()
    flows_working, flows_done = crew_preproduction.counts(conn, slug)
    return working + flows_working, min(done, BOARD_LIMIT) + flows_done


