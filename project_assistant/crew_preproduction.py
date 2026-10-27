"""The crew's pre-production flow for one episode, with the director's locks between stages (SPEC_20 R24, R25, R13, R40).

Four stages run in order, each as ordinary crew jobs (project_assistant.crew_jobs, asked with ``automatic=True`` so the
production's automation switch stops them), and three human locks sit between them (skills/crew-preproduction):

    screenwriter     adaptation and breakdown candidates on the episode                 (doc_writer)
        SCRIPT LOCK
    art              a description for every cast member, set and prop the episode       (doc_writer, labelled Art)
                     names; a new look the script names but the cast sheet lacks; who
                     is in each shot, scene by scene (the manual's Stage 2 propose_cast)
        LIST LOCK
    cinematographer  a beat sheet and a camera (with its 3D ghost plan) for every shot   (sheet_ops)
        STORYBOARD LOCK
    continuity       a continuity check of every scene with a join                       (qa_critic)

Who is in each shot runs with Art, before the list lock, not with the Cinematographer: the beat sheet must keep the
shot's tags exactly, and both write the same prompt cell, so binding the cast first keeps the two from proposing over
each other (the manual puts propose_cast in Art's stage for the same reason).

A stage never starts before the lock that precedes it. A lock is set only by the director or the showrunner (member
role director or admin), only once the stage before it has finished (every job succeeded, failed or was canceled), and
records who set it, when, a snapshot of what it covers and that snapshot's hash (context_tools.content_hash, the hash
of the context tools' envelopes). The director locks exactly what the panel showed: the request carries that hash and
a lock whose content changed since is refused (409 DRAMA_PREPRODUCTION_CHANGED). The script lock needs the script
confirmed and the storyboard built (Art reads the extracted cast, the Cinematographer the shots).

    script      the episode's script: its scenes (titles and text) and the whole text
    list        every cast, set and prop card the episode names (name, description, kind, looks included) and the
                @ tags of every slate shot (who and what is in it)
    storyboard  every slate shot: its prompt, Optical Rig, Camera Motion, scene and stored 3D plan revision

If locked content changes while the flow is active, the flow stops: its status becomes ``stopped``, ``stop`` says
which lock and what changed (scenes, cards, shots by name), the flow's queued and running jobs are canceled and the
pending proposals of the stages after that lock are listed as stale. The check runs whenever the flow is read or acted
on, and in the worker before a flow job calls its model and again before it proposes (crew_jobs.execute), so a stale
job never proposes. A stopped, canceled or completed flow is history; starting again makes a new flow.

Flow states (``projectops.story_record`` kind ``crew_flow``, one active flow per episode)::

    running   a stage's jobs are queued or running
    waiting   the stage finished; waitingFor names the lock the director sets next
    blocked   a stage could not start: automatic crew work is paused (R40), or the stage's role is not ready (a
              readiness blocker). Nothing was requested; POST .../resumptions tries again.
    completed the continuity stage finished
    stopped   locked content changed (see above)
    canceled  canceled as a whole: by its starter, the director or the showrunner (the crew board, or the panel)

No stage requests generation, and nothing is generated when the flow completes: every stage plans, and all planning of
the episode finishes before anything is rendered (R13 batching; fixed decision 10, no auto-spend). Every job's output is
a proposal the director adopts or dismisses (fixed decision 9).

Routes (story_crew, under /aivideo/open/v1/episodes/{episodeId}):
    GET  preproduction                 {flow (the newest, or null), next (the lock to set, its hash and summary, while
                                       waiting), canLock, canStart}
    POST preproduction                 body {"scriptFinal"?: bool} start (the active flow is returned instead of a second);
                                       scriptFinal skips the Screenwriter: the flow waits for the script lock at once
    POST preproduction/locks           body {"lock": "script"|"list"|"storyboard", "hash": "sha256:..."}
    POST preproduction/resumptions     retry the blocked stage
    POST preproduction/cancellations   body {"reason"?}
The crew board lists flows beside their jobs and cancels one through
POST /projects/api/{slug}/orchestration/crew-flows/{flowId}/cancel.
"""
from __future__ import annotations

import re
import uuid

from project_assistant import crew_jobs

KIND = 'crew_flow'
STAGES = ('screenwriter', 'art', 'cinematographer', 'continuity')
LOCKS = ('script', 'list', 'storyboard')
GATE = {'art': 'script', 'cinematographer': 'list', 'continuity': 'storyboard'}       # the lock a stage waits for
OPENS = {lock: stage for stage, lock in GATE.items()}                                # the stage a lock opens
CLOSES = {'script': 'screenwriter', 'list': 'art', 'storyboard': 'cinematographer'}  # the stage a lock closes
ROLES = {'screenwriter': ('doc_writer',), 'art': ('doc_writer',), 'cinematographer': ('sheet_ops',), 'continuity': ('qa_critic',)}
STAGE_NAME = {'screenwriter': 'Screenwriter', 'art': 'Art department', 'cinematographer': 'Cinematographer', 'continuity': 'Continuity Supervisor'}
LOCK_NOUN = {'script': 'script', 'list': 'cast and sets list', 'storyboard': 'storyboard'}
LOCKERS = ('admin', 'director')  # service.ROLE_LABEL: the showrunner and the director
ACTIVE = ('running', 'waiting', 'blocked')
FINISHED = ('completed', 'stopped', 'canceled')
FLOW_ID = re.compile(r'cf_[0-9a-f]{32}')
TAILS = ('preproduction', 'preproduction/locks', 'preproduction/resumptions', 'preproduction/cancellations')
LIST_CODES = ('CAST-', 'SET-', 'LOC-', 'PROP-')
JOBS_SHOWN = 20
BOARD_FLOWS = 20
CHANGED = 'DRAMA_PREPRODUCTION_CHANGED'
STOPPED = 'DRAMA_PREPRODUCTION_STOPPED'
STATE = 'DRAMA_PREPRODUCTION_STATE'


class _Paused(Exception):
    """Automatic crew work was paused while a stage was being requested."""


def _story():
    from project_docs import story_openapi as story
    return story


def _natural(label):
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold()) for part in re.split(r'(\d+)', str(label)))


def _short(value):
    return _story().digest(value)[:16]


def _hash(snapshot):
    from project_assistant import context_tools
    return context_tools.content_hash(snapshot)


# ---------- what a lock covers ----------

def episode_shots(conn, ep):
    """The episode's slate shots (the cinema slate) in cut order."""
    return sorted((s for s in _story().shots(conn, ep) if s['tabKey'] == 'cinema-studio'), key=lambda s: _natural(s['shotIndex']))


def _codes_in(text):
    from project_docs.story_adaptation import asset_code
    return [asset_code(m[1]) for m in _story().ASSET_RE.finditer(text or '')]


def episode_codes(conn, ep, shots):
    """Every cast, set and prop code the episode names: its script, its extraction and its slate shots."""
    codes = _codes_in(_story().script(conn, ep)) + [str(c).upper() for c in ep.get('extractedAssetCodes') or []]
    for shot in shots:
        codes += _codes_in(shot['description'])
    return [c for c in dict.fromkeys(codes) if c.startswith(LIST_CODES)]


def content(conn, ep, lock, shots=None):
    """(snapshot, summary) of what a lock covers now; the lock's hash is the snapshot's content_hash. shots: the
    episode's slate shots when the caller has read them already."""
    story = _story()
    if lock == 'script':
        text, scenes = story.script(conn, ep), story.scenes(conn, ep)
        snapshot = {'script': _short(text),
                    'scenes': [{'sceneId': s['sceneId'], 'title': s['title'][:120], 'text': _short(s['content'])} for s in scenes]}
        return snapshot, {'scenes': len(scenes), 'chars': len(text), 'items': [s['title'][:80] for s in scenes[:8]]}
    shots = episode_shots(conn, ep) if shots is None else shots
    if lock == 'list':
        from project_assistant import crew_art
        codes = episode_codes(conn, ep, shots)
        bases = {code.split(':')[0] for code in codes}
        rows = crew_art.cast_rows(conn, ep['slug'])
        assets = {code: {'name': view['name'][:80], 'hash': _short([view['name'], view['prompt'], view['type'], view.get('kind')])}
                  for code, (_, view) in rows.items() if code.split(':')[0] in bases}
        snapshot = {'assets': assets,
                    'shots': {s['shotId']: {'label': s['shotIndex'], 'tags': sorted(set(_codes_in(s['description'])))} for s in shots}}
        missing = sorted(code for code in codes if code not in rows and code.split(':')[0] not in rows)
        return snapshot, {'assets': sum(1 for code in assets if ':' not in code), 'looks': sum(1 for code in assets if ':' in code),
                          'shots': len(shots), 'missing': missing,
                          'items': [f"{code} {item['name']}".strip() for code, item in list(assets.items())[:8]]}
    snapshot = {'shots': {s['shotId']: {'label': s['shotIndex'], 'sceneId': s.get('sceneId'), 'text': _short(s['description']),
                                        'rig': _short(s['opticalRig']), 'motion': _short(s['cameraMotion']),
                                        'plan': s.get('previsPlanRevision', 0)} for s in shots}}
    return snapshot, {'shots': len(shots), 'withPlan': sum(1 for s in shots if s.get('previsPlanStored')),
                      'items': [s['shotIndex'] for s in shots[:8]]}


def changes(lock, old, new):
    """What changed in a lock's content, as sentences (at most 12)."""
    lines = []
    if lock == 'script':
        before, after = {s['sceneId']: s for s in old['scenes']}, {s['sceneId']: s for s in new['scenes']}
        lines += [f"Scene \"{s['title']}\" was added." for key, s in after.items() if key not in before]
        lines += [f"Scene \"{s['title']}\" was removed." for key, s in before.items() if key not in after]
        for key in [k for k in before if k in after]:
            if before[key]['title'] != after[key]['title']:
                lines.append(f"Scene \"{before[key]['title']}\" was renamed to \"{after[key]['title']}\".")
            if before[key]['text'] != after[key]['text']:
                lines.append(f"The text of scene \"{after[key]['title']}\" changed.")
        if not lines and old['script'] != new['script']:
            lines.append('The script text changed outside its scenes.')
    elif lock == 'list':
        before, after = old['assets'], new['assets']
        lines += [f"{code} {after[code]['name']} was added to the cast sheet.".replace('  ', ' ') for code in after if code not in before]
        lines += [f"{code} {before[code]['name']} was removed from the cast sheet.".replace('  ', ' ') for code in before if code not in after]
        lines += [f"{code} {after[code]['name']}'s card changed (name or description).".replace('  ', ' ')
                  for code in after if code in before and before[code]['hash'] != after[code]['hash']]
        lines += _shot_changes(old['shots'], new['shots'], lambda a, b: (
            [f"{b['label']}'s cast and sets changed: {' '.join('@' + t for t in a['tags']) or 'none'} -> "
             f"{' '.join('@' + t for t in b['tags']) or 'none'}."] if a['tags'] != b['tags'] else []))
    else:
        def shot(a, b):
            found = []
            if a['text'] != b['text']:
                found.append(f"{b['label']}'s prompt changed.")
            if a['rig'] != b['rig'] or a['motion'] != b['motion']:
                found.append(f"{b['label']}'s camera changed.")
            if a['plan'] != b['plan']:
                found.append(f"{b['label']}'s 3D plan changed.")
            if a['sceneId'] != b['sceneId']:
                found.append(f"{b['label']} moved to another scene.")
            return found
        lines += _shot_changes(old['shots'], new['shots'], shot)
    return lines[:12] + ([f'And {len(lines) - 12} more changes.'] if len(lines) > 12 else [])


def _shot_changes(before, after, compare):
    lines = [f"Shot {s['label']} was added." for key, s in after.items() if key not in before]
    lines += [f"Shot {s['label']} was removed." for key, s in before.items() if key not in after]
    for key in [k for k in before if k in after]:
        lines += compare(before[key], after[key])
    return lines


def lock_problem(conn, ep, lock, summary):
    """Why a lock cannot be set on this content yet, or None."""
    story = _story()
    if lock == 'script':
        text = story.script(conn, ep)
        if not text.strip():
            return 'Write the script first.'
        if ep.get('confirmedHash') != story.digest(text) or not episode_shots(conn, ep):
            return ('Confirm the script and build the storyboard first: Art reads the extracted cast, and the Cinematographer '
                    'reads the shots.')
        return None
    if not summary['shots']:
        return 'The storyboard has no shots yet; build it first.'
    if lock == 'list' and summary.get('missing'):
        return ('These codes have no card on the cast sheet: ' + ', '.join('@' + c for c in summary['missing'][:8])
                + '. Extract the assets again, or add the cards, before locking the list.')
    return None


# ---------- records ----------

def _load(conn, flow_id, *, lock=False):
    with conn.cursor() as cur:
        cur.execute('SELECT data, project_slug FROM projectops.story_record WHERE id=%s AND kind=%s' + (' FOR UPDATE' if lock else ''),
                    (flow_id, KIND))
        row = cur.fetchone()
    return dict(row[0], slug=row[1]) if row else None


def _latest(conn, slug, episode_id, *, lock=False):
    with conn.cursor() as cur:
        cur.execute("""SELECT id FROM projectops.story_record WHERE kind=%s AND project_slug=%s AND data->>'episodeId'=%s
                       ORDER BY data->>'startedAt' DESC, id DESC LIMIT 1""", (KIND, slug, episode_id))
        row = cur.fetchone()
    return _load(conn, row[0], lock=lock) if row else None


def _save(conn, flow):
    flow['updatedAt'] = crew_jobs.now()
    _story().store(conn, flow['flowId'], KIND, {k: v for k, v in flow.items() if k != 'slug'}, flow['slug'], flow['startedBy'])
    return flow


def _jobs(conn, ids):
    if not ids:
        return {}
    with conn.cursor() as cur:
        cur.execute('SELECT id, data FROM projectops.story_record WHERE kind=%s AND id = ANY(%s)', (crew_jobs.KIND, list(ids)))
        return {row[0]: row[1] for row in cur.fetchall()}


def _audit(conn, flow, action, actor_id, **detail):
    from project_docs import repository as repo
    repo.add_audit(conn, flow['slug'], action=action, actor_id=actor_id, tab_key=flow.get('tabKey'), target=flow['flowId'],
                   detail={'episodeId': flow['episodeId'], **detail})


def _member(conn, me, slug, *, write):
    from project_assistant import orchestrator
    story = _story()
    try:
        return orchestrator.actor(conn, slug, me, write=write)
    except orchestrator.OrchestrationError as exc:
        raise story.StoryError(exc.status, 'DRAMA_OPERATION_NOT_ALLOWED', str(exc)) from None


def can_lock(member):
    return bool(member) and member.get('role') in LOCKERS


def _may_cancel(flow, me, member):
    return flow['startedBy'] == me.actor_id or can_lock(member)


# ---------- deriving and checking ----------

def _current(flow):
    """The stage the flow is at: running, blocked, or the one the next lock opens."""
    if flow['status'] == 'blocked':
        return flow['blocked']['stage']
    if flow['status'] == 'waiting':
        return OPENS[flow['waitingFor']]
    return next((key for key in STAGES if flow['stages'][key]['status'] == 'running'), None)


def derive(conn, flow):
    """Settle the running stage from its jobs: done when every job finished; then wait for the next lock or complete.
    Returns True when something changed (in memory only)."""
    if flow['status'] != 'running':
        return False
    stage = next((key for key in STAGES if flow['stages'][key]['status'] == 'running'), None)
    if stage is None:
        return False
    jobs = _jobs(conn, flow['stages'][stage]['jobs'])
    if any(jobs.get(job_id, {}).get('status') in crew_jobs.ACTIVE for job_id in flow['stages'][stage]['jobs']):
        return False
    flow['stages'][stage].update(status='done', finishedAt=crew_jobs.now())
    if stage == STAGES[-1]:
        flow.update(status='completed', finishedAt=crew_jobs.now(), waitingFor=None)
    else:
        flow.update(status='waiting', waitingFor=GATE[STAGES[STAGES.index(stage) + 1]])
    return True


def verify(conn, ep, flow):
    """None while every lock still holds; else the stop: which lock, what changed."""
    shots = None
    for lock in LOCKS:
        held = (flow.get('locks') or {}).get(lock)
        if not held:
            continue
        if lock != 'script' and shots is None:
            shots = episode_shots(conn, ep)
        snapshot, _ = content(conn, ep, lock, shots)
        if _hash(snapshot) != held['hash']:
            changed = changes(lock, held['snapshot'], snapshot) or [f'The {LOCK_NOUN[lock]} changed.']
            return {'code': 'lock_changed', 'lock': lock, 'changed': changed, 'hash': _hash(snapshot),
                    'message': f"The {LOCK_NOUN[lock]} changed after the {lock} lock, so the flow stopped: the crew's later work "
                               f"would plan from content you did not lock. Start pre-production again to plan from the new {LOCK_NOUN[lock]}."}
    return None


def _flow_job_ids(flow, stages=STAGES):
    return [job_id for key in stages for job_id in flow['stages'][key]['jobs']]


def _pending_proposals(conn, slug, job_ids):
    if not job_ids:
        return []
    with conn.cursor() as cur:
        cur.execute("""SELECT id FROM projectops.assistant_proposal WHERE project_slug=%s AND status='pending'
                       AND target->'crew'->>'jobId' = ANY(%s) ORDER BY id""", (slug, list(job_ids)))
        return [row[0] for row in cur.fetchall()]


def _end_jobs(conn, flow, actor_id, reason):
    return crew_jobs.cancel_jobs(conn, flow['slug'], _flow_job_ids(flow), by=actor_id, reason=reason)


def stop(conn, flow, found, actor_id=None):
    """Stop the flow on a changed lock: cancel its active jobs, list the proposals that are now stale."""
    later = STAGES[STAGES.index(OPENS[found['lock']]):]
    canceled = _end_jobs(conn, flow, actor_id, 'The pre-production flow stopped: ' + found['message'])
    for key in STAGES:
        if flow['stages'][key]['status'] == 'running':
            flow['stages'][key].update(status='stopped', finishedAt=crew_jobs.now())
    flow.update(status='stopped', finishedAt=crew_jobs.now(), waitingFor=None, blocked=None,
                stop={**found, 'at': crew_jobs.now(), 'canceledJobs': canceled,
                      'staleProposals': _pending_proposals(conn, flow['slug'], _flow_job_ids(flow, later))})
    _audit(conn, flow, 'crew_flow_stopped', actor_id, lock=found['lock'], changed=found['changed'], canceledJobs=len(canceled))
    return flow


def _settle(conn, ep, flow, actor_id=None):
    """Under the production lock, with the flow row locked: stop it on a changed lock, else settle its stage."""
    if flow['status'] not in ACTIVE:
        return flow, False
    found = verify(conn, ep, flow)
    if found:
        _save(conn, stop(conn, flow, found, actor_id))
        return flow, True
    if derive(conn, flow):
        _save(conn, flow)
    return flow, False


# ---------- starting a stage ----------

def _blockers(conn, me, slug, stage):
    """The readiness blockers of a stage's roles. Call before writing anything: a stale readiness cache is refreshed
    with a probe that ends the transaction (crew_readiness.readiness)."""
    found = []
    for role in ROLES[stage]:
        found += [b for b in crew_jobs.readiness_blockers(conn, me, slug, role) if b not in found]
    return found


def targets(conn, ep, stage):
    """[(job kind, target, body)] a stage asks for, and [(kind, target, reason)] it leaves out."""
    story = _story()
    slug, episode = ep['slug'], {'kind': 'episode', 'id': ep['episodeId']}
    if stage == 'screenwriter':
        return [('adaptation', episode, {}), ('breakdown', episode, {})], []
    shots = episode_shots(conn, ep)
    scenes = story.scenes(conn, ep)
    placed = {scene['sceneId']: [s for s in shots if s.get('sceneId') == scene['sceneId']] for scene in scenes}
    asked, left = [], []
    if stage == 'art':
        from project_assistant import crew_art
        rows = crew_art.cast_rows(conn, slug)
        codes = episode_codes(conn, ep, shots)
        for code in codes:
            if ':' not in code and code in rows:
                asked.append(('description', {'kind': 'asset', 'id': story.asset_id(slug, rows[code][0])}, {}))
        looked = set()
        for code in codes:
            base, _, key = code.partition(':')
            if not key or code in rows or base not in rows or not base.startswith('CAST'):
                continue
            target = {'kind': 'asset', 'id': story.asset_id(slug, rows[base][0])}
            if base in looked:
                left.append(('look', target, f'{code}: one new look per cast member a pass; ask Art for the next one on the card.'))
                continue
            looked.add(base)
            asked.append(('look', target, {'key': key.lower()[:40]}))
        asked += [('appearances', {'kind': 'scene', 'id': scene['sceneId']}, {}) for scene in scenes if placed[scene['sceneId']]]
    elif stage == 'cinematographer':
        for shot in shots:
            if shot.get('sceneId') in placed:
                target = {'kind': 'shot', 'id': shot['shotId']}
                asked += [('beats', target, {}), ('camera', target, {})]
    else:
        asked = [('continuity', {'kind': 'scene', 'id': scene['sceneId']}, {}) for scene in scenes if len(placed[scene['sceneId']]) >= 2]
        if not asked:
            left.append(('continuity', episode, 'No scene has two shots, so there is no join to check.'))
    return asked, left


def _paused(flow, stage):
    flow.update(status='blocked', waitingFor=None, blocked={
        'stage': stage, 'code': 'paused', 'at': crew_jobs.now(), 'blockers': [],
        'message': 'Automatic crew work is paused for this production. Resume it, then try again.'})
    return flow


def start_stage(conn, me, ep, flow, stage, blockers):
    """Ask for a stage's jobs (automatic, so the automation switch stops them), or mark the flow blocked."""
    from project_assistant import automation
    story = _story()
    now = crew_jobs.now()
    if automation.automation_paused(conn, flow['slug']):
        return _paused(flow, stage)
    if blockers:
        flow.update(status='blocked', waitingFor=None, blocked={
            'stage': stage, 'code': 'not_ready', 'at': now, 'blockers': blockers,
            'message': crew_jobs.not_ready_message(blockers, STAGE_NAME[stage])})
        return flow
    asked, left = targets(conn, ep, stage)
    jobs, skipped = [], [{'kind': kind, 'target': target, 'reason': reason} for kind, target, reason in left]
    try:
        with conn.transaction():  # a pause that lands while asking undoes the whole stage
            for kind, target, body in asked:
                try:
                    with conn.transaction():
                        job = crew_jobs.request(conn, me, flow['slug'], kind, target, body, automatic=True,
                                                flow={'flowId': flow['flowId'], 'stage': stage})
                except story.StoryError as exc:
                    if exc.code == crew_jobs.PAUSED:
                        raise _Paused() from None
                    skipped.append({'kind': kind, 'target': target, 'reason': str(exc)[:300]})
                else:
                    if job['jobId'] not in jobs:
                        jobs.append(job['jobId'])
    except _Paused:
        return _paused(flow, stage)
    flow['stages'][stage].update(status='running', startedAt=now, startedBy=me.actor_id, jobs=jobs, skipped=skipped[:200])
    flow.update(status='running', waitingFor=None, blocked=None)
    derive(conn, flow)  # a stage with nothing to ask for is done at once
    return flow


# ---------- the routes' actions ----------

def _require(flow, message):
    if flow is None or flow['status'] not in ACTIVE:
        raise _story().StoryError(409, STATE, message)


def _no_body(body, allowed=()):
    """The request body, refused (422) when it is not an object or has a field this action does not take."""
    story = _story()
    if not isinstance(body, dict):
        story.invalid('Send the request as a JSON object.')
    unknown = sorted(set(body) - set(allowed))
    if unknown:
        story.invalid('Unknown fields: ' + ', '.join(unknown) + '.')
    return body


def start(conn, me, slug, episode_id, body):
    story = _story()
    _no_body(body, ('scriptFinal',))
    if 'scriptFinal' in body and not isinstance(body['scriptFinal'], bool):
        story.invalid('scriptFinal must be true or false.')
    final = body.get('scriptFinal') is True
    member = _member(conn, me, slug, write=True)
    ep = story.episode(conn, episode_id)
    if ep['slug'] != slug:
        raise story.StoryError(404, 'DRAMA_NOT_FOUND', 'Resource not found.')
    blockers = [] if final else _blockers(conn, me, slug, 'screenwriter')  # may end the transaction: nothing written yet
    crew_jobs._relock(conn, slug)
    current = _latest(conn, slug, episode_id, lock=True)
    if current and current['status'] in ACTIVE:
        current, _ = _settle(conn, ep, current, me.actor_id)
        if current['status'] in ACTIVE:
            return payload(conn, me, member, ep, current)
    now = crew_jobs.now()
    flow = {'flowId': 'cf_' + uuid.uuid4().hex, 'episodeId': ep['episodeId'], 'tabKey': ep['tabKey'],
            'episodeLabel': (ep.get('title') or f"Episode {ep['episodeIndex']}")[:120], 'slug': slug, 'status': 'running',
            'startedBy': me.actor_id, 'startedByName': getattr(me, 'name', None) or member.get('name'), 'startedAt': now,
            'scriptFinal': final, 'waitingFor': None, 'blocked': None, 'stop': None, 'locks': {},
            'stages': {key: {'status': 'pending', 'jobs': [], 'skipped': []} for key in STAGES}}
    if final:
        flow['stages']['screenwriter'].update(status='skipped', finishedAt=now)
        flow.update(status='waiting', waitingFor='script')
    else:
        start_stage(conn, me, ep, flow, 'screenwriter', blockers)
    _save(conn, flow)
    _audit(conn, flow, 'crew_flow_started', me.actor_id, scriptFinal=final, status=flow['status'])
    return payload(conn, me, member, ep, flow)


def _stopped(conn, flow):
    """The flow stopped while acting on it: keep the stop (commit it) and refuse the action."""
    conn.commit()
    raise _story().StoryError(409, STOPPED, flow['stop']['message'], details={'flow': {'flowId': flow['flowId'], 'stop': flow['stop']}})


def set_lock(conn, me, slug, episode_id, body):
    story = _story()
    _no_body(body, ('lock', 'hash'))
    lock, wanted = body.get('lock'), body.get('hash')
    if lock not in LOCKS:
        story.invalid('lock must be script, list or storyboard.')
    if not isinstance(wanted, str) or not wanted.startswith('sha256:'):
        story.invalid('hash must be the "sha256:..." hash of what you are locking (GET preproduction gives it as next.hash).')
    member = _member(conn, me, slug, write=True)
    if not can_lock(member):
        raise story.StoryError(403, 'DRAMA_OPERATION_NOT_ALLOWED', 'Only the director or the showrunner sets pre-production locks.')
    ep = story.episode(conn, episode_id)
    if ep['slug'] != slug:
        raise story.StoryError(404, 'DRAMA_NOT_FOUND', 'Resource not found.')
    blockers = _blockers(conn, me, slug, OPENS[lock])  # may end the transaction: nothing written yet
    crew_jobs._relock(conn, slug)
    flow = _latest(conn, slug, episode_id, lock=True)
    _require(flow, 'Start pre-production first: a lock belongs to a running flow.')
    flow, stopped = _settle(conn, ep, flow, me.actor_id)
    if stopped:
        _stopped(conn, flow)
    _require(flow, 'This pre-production flow has ended; start it again.')
    if (flow.get('locks') or {}).get(lock):
        raise story.StoryError(409, STATE, f'The {lock} is already locked.')
    if flow['status'] != 'waiting' or flow['waitingFor'] != lock:
        closing = CLOSES[lock]
        if flow['stages'][closing]['status'] == 'running':
            open_jobs = sum(1 for j in _jobs(conn, flow['stages'][closing]['jobs']).values() if j['status'] in crew_jobs.ACTIVE)
            raise story.StoryError(409, STATE, f"The {STAGE_NAME[closing]} is still working ({open_jobs} job"
                                               f"{'s' if open_jobs != 1 else ''} open). Lock the {LOCK_NOUN[lock]} once they "
                                               'finish, or cancel them on the crew board.')
        earlier = next((name for name in LOCKS[:LOCKS.index(lock)] if not (flow.get('locks') or {}).get(name)), None)
        raise story.StoryError(409, STATE, f'Lock the {LOCK_NOUN[earlier]} first.' if earlier else
                               'The flow is not waiting for this lock.')
    snapshot, summary = content(conn, ep, lock)
    problem = lock_problem(conn, ep, lock, summary)
    if problem:
        raise story.StoryError(409, 'DRAMA_STAGE_PRECONDITION', problem)
    current = _hash(snapshot)
    if current != wanted:
        raise story.StoryError(409, CHANGED, f'The {LOCK_NOUN[lock]} changed since you looked at it. Review it again, then lock.',
                               details={'lock': lock, 'hash': current})
    flow.setdefault('locks', {})[lock] = {'by': me.actor_id, 'byName': getattr(me, 'name', None) or member.get('name'),
                                          'role': member.get('role'), 'at': crew_jobs.now(), 'hash': current,
                                          'snapshot': snapshot, 'summary': summary}
    flow.update(waitingFor=None)
    start_stage(conn, me, ep, flow, OPENS[lock], blockers)
    _save(conn, flow)
    _audit(conn, flow, 'crew_flow_locked', me.actor_id, lock=lock, hash=current, status=flow['status'])
    return payload(conn, me, member, ep, flow)


def resume(conn, me, slug, episode_id, body):
    story = _story()
    _no_body(body)
    member = _member(conn, me, slug, write=True)
    ep = story.episode(conn, episode_id)
    if ep['slug'] != slug:
        raise story.StoryError(404, 'DRAMA_NOT_FOUND', 'Resource not found.')
    flow = _latest(conn, slug, episode_id)
    if flow is None or flow['status'] != 'blocked':
        raise story.StoryError(409, STATE, 'Nothing to resume: the flow is not blocked.')
    if not _may_cancel(flow, me, member):
        raise story.StoryError(403, 'DRAMA_OPERATION_NOT_ALLOWED', 'Only who started the flow, the director or the showrunner resumes it.')
    stage = flow['blocked']['stage']
    blockers = _blockers(conn, me, slug, stage)  # may end the transaction: nothing written yet
    crew_jobs._relock(conn, slug)
    flow = _load(conn, flow['flowId'], lock=True)
    flow, stopped = _settle(conn, ep, flow, me.actor_id)
    if stopped:
        _stopped(conn, flow)
    if flow['status'] == 'blocked' and flow['blocked']['stage'] == stage:
        start_stage(conn, me, ep, flow, stage, blockers)
        _save(conn, flow)
        _audit(conn, flow, 'crew_flow_resumed', me.actor_id, stage=stage, status=flow['status'])
    return payload(conn, me, member, ep, flow)


def cancel(conn, me, slug, flow, reason=''):
    """Cancel the flow as a whole: its queued and running jobs are canceled, nothing else changes."""
    story = _story()
    member = _member(conn, me, slug, write=True)
    if not _may_cancel(flow, me, member):
        raise story.StoryError(403, 'DRAMA_OPERATION_NOT_ALLOWED', 'Only who started the flow, the director or the showrunner cancels it.')
    _require(flow, 'This pre-production flow has already ended.')
    canceled = _end_jobs(conn, flow, me.actor_id, 'The pre-production flow was canceled.')
    for key in STAGES:
        if flow['stages'][key]['status'] == 'running':
            flow['stages'][key].update(status='canceled', finishedAt=crew_jobs.now())
    flow.update(status='canceled', finishedAt=crew_jobs.now(), canceledBy=me.actor_id, cancelReason=(reason or '')[:300],
                waitingFor=None, blocked=None)
    _save(conn, flow)
    _audit(conn, flow, 'crew_flow_canceled', me.actor_id, canceledJobs=len(canceled))
    return flow


def cancel_episode(conn, me, slug, episode_id, body):
    story = _story()
    _no_body(body, ('reason',))
    if 'reason' in body and (not isinstance(body['reason'], str) or len(body['reason']) > 300):
        story.invalid('reason must be text of at most 300 characters.')
    ep = story.episode(conn, episode_id)
    if ep['slug'] != slug:
        raise story.StoryError(404, 'DRAMA_NOT_FOUND', 'Resource not found.')
    crew_jobs._relock(conn, slug)
    flow = _latest(conn, slug, episode_id, lock=True)
    _require(flow, 'There is no running pre-production flow to cancel.')
    cancel(conn, me, slug, flow, body.get('reason', ''))
    return payload(conn, me, _member(conn, me, slug, write=False), ep, flow)


def cancel_request(conn, me, slug, flow_id, body):
    """POST /projects/api/{slug}/orchestration/crew-flows/{flowId}/cancel (the crew board's cancel)."""
    from project_assistant import orchestration_service as control, orchestrator as cp

    def action():
        control.object_body(body or {}, ('reason', 'client_request_id'))
        story = _story()
        cp.actor(conn, slug, me, write=True)
        crew_jobs._relock(conn, slug)
        flow = _load(conn, flow_id, lock=True) if FLOW_ID.fullmatch(flow_id or '') else None
        if not flow or flow['slug'] != slug:
            raise cp.OrchestrationError(404, 'Pre-production flow not found.')
        try:
            cancel(conn, me, slug, flow, (body or {}).get('reason', ''))
        except story.StoryError as exc:
            raise cp.OrchestrationError(exc.status, str(exc)) from None
        return {'flow': {'flowId': flow['flowId'], 'status': flow['status']}}
    return control.result(action)


def view(conn, me, slug, episode_id):
    story = _story()
    member = _member(conn, me, slug, write=False)
    ep = story.episode(conn, episode_id)
    if ep['slug'] != slug:
        raise story.StoryError(404, 'DRAMA_NOT_FOUND', 'Resource not found.')
    flow = _latest(conn, slug, episode_id)
    if flow and flow['status'] in ACTIVE:
        crew_jobs._relock(conn, slug)
        flow, _ = _settle(conn, ep, _load(conn, flow['flowId'], lock=True), None)
    return payload(conn, me, member, ep, flow)


def route(conn, me, method, slug, episode_id, tail, body):
    story = _story()
    actions = {('GET', 'preproduction'): lambda: view(conn, me, slug, episode_id),
               ('POST', 'preproduction'): lambda: start(conn, me, slug, episode_id, body or {}),
               ('POST', 'preproduction/locks'): lambda: set_lock(conn, me, slug, episode_id, body or {}),
               ('POST', 'preproduction/resumptions'): lambda: resume(conn, me, slug, episode_id, body or {}),
               ('POST', 'preproduction/cancellations'): lambda: cancel_episode(conn, me, slug, episode_id, body or {})}
    action = actions.get((method, tail))
    if action is None:
        raise story.StoryError(404, 'DRAMA_NOT_FOUND', 'Resource not found.')
    return action()


# ---------- the worker's check (crew_jobs.execute) ----------

def guard(conn, record):
    """True when a flow job must not go on: its flow has ended, or a lock it depends on changed (the flow is stopped
    now and its jobs canceled, this one included). Reads only, unless it has something to stop."""
    flow = _load(conn, record['flowId'])
    if flow is None:
        return False
    story = _story()
    if flow['status'] in ACTIVE:
        try:
            ep = story.episode(conn, flow['episodeId'])
        except story.StoryError:
            ep = None
        if ep is not None and verify(conn, ep, flow) is None:
            return False
    crew_jobs._relock(conn, flow['slug'])
    flow = _load(conn, flow['flowId'], lock=True)
    if flow['status'] in ACTIVE:
        try:
            ep = story.episode(conn, flow['episodeId'])
        except story.StoryError:
            ep = None
        found = verify(conn, ep, flow) if ep is not None else {
            'code': 'episode_missing', 'lock': 'script', 'changed': ['The episode was removed.'], 'hash': None,
            'message': 'The episode was removed, so the flow stopped.'}
        if found is None:
            return False
        _save(conn, stop(conn, flow, found))
    else:
        crew_jobs.cancel_jobs(conn, flow['slug'], [record['jobId']], reason='The pre-production flow has ended.')
    return True


# ---------- what the panel and the crew board show ----------

def _job_line(job_id, job):
    return {'jobId': job_id, 'kind': job.get('kind'), 'status': job.get('status'), 'role': job.get('role'),
            'targetLabel': job.get('targetLabel') or job.get('shotLabel'), 'target': crew_jobs.target_of(job),
            'source': job.get('source'), 'failure': job.get('failure'), 'error': (job.get('error') or '')[:200] or None,
            'proposals': len((job.get('result') or {}).get('proposalIds') or [])}


ORDER = {'running': 0, 'queued': 1, 'failed': 2, 'succeeded': 3, 'canceled': 4}


def public(conn, flow, *, me=None, member=None):
    stages = []
    for key in STAGES:
        stage = flow['stages'][key]
        jobs = _jobs(conn, stage['jobs'])
        lines = [_job_line(job_id, jobs[job_id]) for job_id in stage['jobs'] if job_id in jobs]
        counts = {status: sum(1 for line in lines if line['status'] == status) for status in ('queued', 'running', 'succeeded', 'failed', 'canceled')}
        counts.update(total=len(lines), fallback=sum(1 for line in lines if line['source'] == crew_jobs.SOURCE_FALLBACK),
                      proposals=sum(line['proposals'] for line in lines), skipped=len(stage['skipped']))
        stages.append({'key': key, 'status': stage['status'], 'gate': GATE.get(key), 'startedAt': stage.get('startedAt'),
                       'finishedAt': stage.get('finishedAt'), 'counts': counts,
                       'jobs': sorted(lines, key=lambda line: ORDER.get(line['status'], 9))[:JOBS_SHOWN],
                       'skipped': [{'kind': s['kind'], 'target': s['target'], 'reason': s['reason']} for s in stage['skipped'][:JOBS_SHOWN]]})
    locks = {name: ({k: held[k] for k in ('by', 'byName', 'role', 'at', 'hash', 'summary')} if held else None)
             for name in LOCKS for held in [(flow.get('locks') or {}).get(name)]}
    result = {k: flow.get(k) for k in ('flowId', 'episodeId', 'episodeLabel', 'status', 'waitingFor', 'blocked', 'stop',
                                        'startedBy', 'startedByName', 'startedAt', 'finishedAt', 'scriptFinal', 'canceledBy')}
    result.update(stages=stages, locks=locks, current=_current(flow))
    if me is not None:
        result['canCancel'] = flow['status'] in ACTIVE and _may_cancel(flow, me, member)
    return result


def payload(conn, me, member, ep, flow):
    """GET preproduction: the newest flow, the lock to set next (while waiting), and what this member may do."""
    lockable = can_lock(member)
    result = {'episodeId': ep['episodeId'], 'stages': list(STAGES), 'locks': list(LOCKS), 'canLock': lockable,
              'canStart': member.get('role') != 'viewer' and (flow is None or flow['status'] not in ACTIVE),
              'flow': public(conn, flow, me=me, member=member) if flow else None, 'next': None}
    if flow and flow['status'] == 'waiting':
        lock = flow['waitingFor']
        snapshot, summary = content(conn, ep, lock)
        closing = CLOSES[lock]
        result['next'] = {'lock': lock, 'hash': _hash(snapshot), 'summary': summary, 'stage': OPENS[lock],
                          'problem': lock_problem(conn, ep, lock, summary),
                          'pendingProposals': len(_pending_proposals(conn, flow['slug'], flow['stages'][closing]['jobs']))}
    return result


def _board_state(flow):
    status = flow['status']
    if status == 'running':
        stage = next((k for k in STAGES if flow['stages'][k]['status'] == 'running'), None)
        return f"the {STAGE_NAME.get(stage, 'crew')} is working"
    if status == 'waiting':
        return f"waiting for the {flow['waitingFor']} lock"
    if status == 'blocked':
        return 'blocked: ' + flow['blocked']['message']
    if status == 'completed':
        return 'finished: every stage planned, nothing generated'
    if status == 'stopped':
        return 'stopped: ' + '; '.join(flow['stop'].get('changed') or [])[:300]
    return 'canceled'


def board_items(conn, me, slug):
    """(working, done) crew board items of the production's pre-production flows (every member sees them)."""
    from project_assistant import orchestrator
    with conn.cursor() as cur:
        cur.execute("""SELECT data, project_slug FROM projectops.story_record WHERE kind=%s AND project_slug=%s
                       ORDER BY data->>'startedAt' DESC, id DESC LIMIT %s""", (KIND, slug, BOARD_FLOWS))
        flows = [dict(row[0], slug=row[1]) for row in cur.fetchall()]
    try:
        member = orchestrator.actor(conn, slug, me, write=False)
    except orchestrator.OrchestrationError:
        member = None
    working, done = [], []
    for flow in flows:
        derive(conn, flow)  # the board shows the settled state; the panel and the worker persist it
        active = flow['status'] in ACTIVE
        stage = _current(flow)
        item = {'id': 'crewflow:' + flow['flowId'], 'kind': 'crew_flow', 'flow_id': flow['flowId'],
                'episode_id': flow['episodeId'], 'title': f"Pre-production · {flow['episodeLabel']} · {_board_state(flow)}"[:300],
                'status': 'running' if active else {'completed': 'succeeded', 'stopped': 'failed'}.get(flow['status'], 'canceled'),
                'flow_status': flow['status'], 'agent_key': ROLES[stage][0] if stage else None, 'target': {},
                'created_at': flow['startedAt'], 'summary': _board_state(flow) if not active else None,
                'error': flow['stop']['message'] if flow['status'] == 'stopped' else None, 'failure': None,
                'can_cancel': active and _may_cancel(flow, me, member), 'tools_trace': []}
        (working if active else done).append(item)
    return working, done


def counts(conn, slug):
    with conn.cursor() as cur:
        cur.execute("""SELECT count(*) FILTER (WHERE data->>'status' IN ('running','waiting','blocked')),
                              count(*) FILTER (WHERE data->>'status' IN ('completed','stopped','canceled'))
                       FROM projectops.story_record WHERE kind=%s AND project_slug=%s""", (KIND, slug))
        working, done = cur.fetchone()
    return working, min(done, BOARD_FLOWS)
