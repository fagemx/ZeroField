"""Continuity grading of sheet-row takes.

The Continuity Supervisor's vision model grades the product's 8-frame contact sheet of a take with the rubric the
Phase 2 hand grading used. LTX-2.5 and a local vision model do not fit on one 24 GB GPU together, so a grade takes the
cross-process GPU arbiter (SPEC_20 R13): when ComfyUI held the GPU last, it waits for ComfyUI to go idle (it never
interrupts a render) and frees ComfyUI's models; takes of one shot are graded together in one hold, and the vision model
stays loaded until a render needs the GPU. The vision call is governed like an agent turn (SPEC_20 R11): a loopback
endpoint is unbilled, any other must pass the environment, credential and price checks before frames leave.
A failing grade carries the grader's rewritten prompt; Retake with it in shot review applies it and re-shoots in one click.
"""
from __future__ import annotations

import base64
import dataclasses
import json
import re
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from project_assistant import gpu_arbiter

RUBRIC = ("You are the continuity grader. The image is an 8-frame timestamped contact sheet of one generated shot. "
          "Score 0-100 against the brief and list concrete issues (identity drift, wardrobe, set, lighting direction, "
          "temporal artifacts, camera move matches brief). Reply JSON only: "
          '{"score": int, "passed": bool, "issues": [str], "feedback": str, "retake_prompt": str}. '
          'When the take fails, retake_prompt is the shot prompt rewritten to fix the issues, keeping its @asset tags; '
          'otherwise "".')
KIND = 'take_grade'
SETTING = 'auto_grade_takes'
SHOT_TABS = ('cinema-studio', 'openjutsu-lab')
ACTIVE = ('queued', 'waiting_gpu', 'grading')
STALE_SECONDS = 15 * 60
VISION_TIMEOUT = 600
GPU_WAIT = 3600  # longest a grade waits for renders holding the GPU
# Compatibility name: the cross-process arbiter replaced this process-local lock (SPEC_20 R13).
GPU_LOCK = gpu_arbiter.CompatLock()
FREE_TARGET = gpu_arbiter.FREE_TARGET

_wake = threading.Event()
_guard = threading.Lock()
_started = False


class GradeError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def record_id(shot_id, asset_id):
    return f'grade_{shot_id}_{asset_id}'


def auto_enabled(conn, slug):
    from project_assistant import store
    return store.get_setting(conn, slug, SETTING) == 'on'


def set_auto(conn, slug, enabled):
    from project_assistant import store
    store.set_setting(conn, slug, SETTING, 'on' if enabled else 'off')


def grades(conn, slug, shot_id):
    from project_docs import story_openapi as story
    items = [g for g in story.records(conn, KIND, slug) if g['shotId'] == shot_id]
    return sorted(items, key=lambda g: g['requestedAt'], reverse=True)


def enqueue(conn, slug, shot_id, asset_url, owner_id, *, auto=False):
    """Queue (or return the in-flight) grade of one take; the caller commits, then calls kick()."""
    from project_docs import repository as repo, story_openapi as story
    from project_assistant import privacy
    from project_assistant.studio.runtime import MAX_MEDIA
    match = re.fullmatch(r'/projects/api/' + re.escape(slug) + r'/assets/(pa_[0-9a-f]{32})', asset_url or '')
    meta = repo.get_asset_meta(conn, slug, match[1]) if match else None
    if not meta or not meta[0].startswith('video/') or not 0 < meta[1] <= MAX_MEDIA:
        raise GradeError('Choose a video take from this production to grade.')
    if privacy.mode(conn, slug) != 'full_access':
        raise GradeError('Numeric masking does not permit sending frames to the vision model.')
    key = record_id(shot_id, match[1])
    current = story.record(conn, key, required=False, lock=True)
    if current and current['status'] in ACTIVE and time.time() - datetime.fromisoformat(current['requestedAt']).timestamp() < STALE_SECONDS:
        return current
    return story.store(conn, key, KIND, {'gradeId': key, 'shotId': shot_id, 'assetId': match[1], 'assetUrl': asset_url,
                                         'status': 'queued', 'auto': auto, 'requestedBy': owner_id, 'requestedAt': now()}, slug)


def on_take(conn, slug, tab_key, row_id, output, owner_id):
    """Auto-grade hook for a worker output that lands on a shot row (off unless the production opts in)."""
    url = (output or {}).get('asset_url')
    from project_assistant.automation import automation_paused  # SPEC_20 R40: the Console's automation switch
    if tab_key not in SHOT_TABS or not url or not auto_enabled(conn, slug) or automation_paused(conn, slug):
        return None
    try:
        return enqueue(conn, slug, f'sh_{slug}_{row_id}', url, owner_id, auto=True)
    except GradeError:
        return None  # images, foreign or masked media are simply not auto-graded


def kick():
    """Wake the process grader; it also polls, so a record committed after this call is still picked up."""
    global _started
    with _guard:
        _wake.set()
        if not _started:
            _started = True
            threading.Thread(target=_loop, name='take-grader', daemon=True).start()


def _loop():
    from project_docs import http
    while True:
        _wake.wait(5)
        _wake.clear()
        try:
            drain(http.open_connection)
        except Exception:
            pass  # a database outage must not end the grader; the next poll retries


def drain(connect):
    """Grade every queued take, oldest first; the queued takes of one shot are graded together in one GPU hold
    (SPEC_20 R13), and the GPU is released between shots so waiting renders get their turn. Returns how many ran."""
    count = 0
    while True:
        conn = connect()
        try:
            job = _claim(conn)
            if not job:
                return count
            with _Phase() as phase:
                while job:
                    try:
                        _grade(conn, job, connect=connect, phase=phase)
                    except Exception as exc:
                        conn.rollback()
                        _save(conn, job, status='failed', error=str(exc)[:500] if isinstance(exc, GradeError) else
                              'Grading failed; check the Continuity Supervisor model endpoint and retry.')
                    count += 1
                    job = _claim(conn, shot_id=job['shotId'])
        finally:
            conn.close()


class _Phase:
    """One GPU hold for consecutive grades; the first grade that needs the GPU takes it."""

    def __init__(self):
        self.grant = None

    def hold(self, config, comfy, *, on_wait):
        """GPU facts for the scorecard: what was freed, whether the grade waited, whether it joined a running phase."""
        key = gpu_arbiter.gpu_key(config.base_url)
        if key != gpu_arbiter.LOCAL_KEY:
            return {}  # a hosted endpoint does not use this machine's GPU
        if self.grant is not None and self.grant.key == key:
            return {'comfyFreed': False, 'batched': True}
        self.release()
        freed = {}

        def switch(previous):
            # ComfyUI (or nothing known) held the GPU last: free the ComfyUI on this machine; never interrupt a render.
            if gpu_arbiter.gpu_key(comfy) == key:
                freed.update(hand_off(comfy, on_wait=on_wait))
            return freed
        try:
            self.grant = gpu_arbiter.acquire(gpu_arbiter.LLM, config.base_url, model=config.model, label='grade',
                                             timeout=GPU_WAIT, on_wait=on_wait, on_switch=switch)
        except gpu_arbiter.GpuBusy as exc:
            raise GradeError(str(exc)) from None
        return {'comfyFreed': False, **freed, 'waitedForGpu': self.grant.waited, 'batched': not self.grant.switched}

    def release(self):
        if self.grant is not None:
            grant, self.grant = self.grant, None
            grant.release()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()


def _claim(conn, shot_id=None):
    with conn.cursor() as cur:
        cur.execute("""SELECT data, project_slug FROM projectops.story_record WHERE kind=%s AND data->>'status'='queued'
                       AND (%s::text IS NULL OR data->>'shotId'=%s)
                       ORDER BY updated_at LIMIT 1 FOR UPDATE SKIP LOCKED""", (KIND, shot_id, shot_id))
        row = cur.fetchone()
    if not row:
        conn.rollback()
        return None
    job = dict(row[0], slug=row[1])
    _save(conn, job, status='grading', startedAt=now())
    return job


def _save(conn, job, **changes):
    from project_docs import story_openapi as story
    job.update(changes)
    story.store(conn, job['gradeId'], KIND, {k: v for k, v in job.items() if k != 'slug'}, job['slug'])
    conn.commit()


def _grade(conn, job, *, connect=None, phase=None):
    from project_docs import repository as repo, story_openapi as story
    from project_assistant import agent_registry, agent_runtime, privacy
    from project_assistant import execution_governance as governance
    slug = job['slug']
    _, row = story.find_row(conn, job['shotId'], 'shot')
    if privacy.mode(conn, slug) != 'full_access':
        raise GradeError('Numeric masking does not permit sending frames to the vision model.')
    profile = agent_registry.get_agent(conn, slug, 'qa_critic')
    if not profile:
        raise GradeError('This production has no Continuity Supervisor.')
    if not profile.get('enabled', True):
        raise GradeError('The Continuity Supervisor is disabled for this production.')
    config = agent_runtime.provider_for(profile)
    if config.kind != 'openai_compat':
        raise GradeError('Continuity grading needs an OpenAI-compatible vision endpoint for the Continuity Supervisor.')
    found = repo.get_asset(conn, slug, job['assetId'])
    if not found:
        raise GradeError('The take is no longer in this production.')
    comfy = comfy_url(conn, slug)
    view = story.shot_view(conn, slug, row)
    conn.commit()  # no transaction across FFmpeg, the GPU wait or inference
    sheet, timing = frame_sheet(bytes(found[1]))
    # Governed like an agent turn (SPEC_20 R11): reserved, attributed to the Continuity Supervisor, settled per §4.1.
    admission = governance.ProviderAdmission(grading_context(job, connect), profile, config, 'grader_check', purpose='continuity_grade')
    own = phase is None
    phase = phase or _Phase()
    try:
        gpu = phase.hold(config, comfy, on_wait=lambda: _save(conn, job, status='waiting_gpu'))
        _save(conn, job, status='grading')
        started = time.monotonic()  # seconds = model load + grading, not the wait for renders
        answer = vision(config, brief(view), view['description'], sheet, admission=admission)
    finally:
        if own:
            phase.release()
    card = scorecard(answer, view['description'])
    sheet_id = repo.put_asset(conn, slug, data=sheet, content_type='image/png', actor_id=job['requestedBy'])
    _save(conn, job, status='graded', **card, gradedAt=now(),
          sheetUrl=f'/projects/api/{slug}/assets/{sheet_id}', timing=timing, model=config.model,
          seconds=round(time.monotonic() - started, 1), gpu=gpu)


def grading_context(job, connect=None):
    """Admission context for one grading attempt: the requester's authority, the Continuity Supervisor's environment,
    and a session key the console groups grading spend by."""
    from project_docs import service
    from project_assistant import execution_governance as governance
    session = 'grade:' + job['gradeId']
    ctx = governance.media_context(service.Identity(job['requestedBy'], 'Continuity grader', 'member'), job['slug'],
                                   agent_key='qa_critic', accounting_session_key=session if len(session) <= 160 else
                                   'grade:' + governance.cp.digest(job['gradeId']),
                                   execution_key='grade:%s:%s' % (job['gradeId'], job.get('startedAt') or now()))
    if connect is not None:
        ctx.connection_factory = connect
    return ctx


def brief(view):
    return ', '.join(v for v in (view['shotIndex'], view['cameraMotion'], view['opticalRig']) if v) + '. ' + view['description']


def frame_sheet(raw):
    from project_assistant import limb_worker
    from project_assistant.studio.media_prep import build_video_frame_sheet
    with tempfile.TemporaryDirectory(prefix='take-grade-') as folder:
        path = Path(folder) / 'take.mp4'
        path.write_bytes(raw)
        media = limb_worker._probe_video(path, {'probe_timeout': 60})
        image, timing = build_video_frame_sheet(path, media['duration'], Path(folder), {'timeout': 120})
        return image.read_bytes(), timing


def comfy_url(conn, slug):
    """The ComfyUI behind the local worker: the Local 4090 environment's comfy_url."""
    from project_assistant import orchestration_store as db
    config = db.one(conn, "SELECT config FROM projectops.agent_environment WHERE project_slug=%s AND env_key='env_local_4090'", (slug,))
    return ((config or {}).get('comfy_url') or 'http://127.0.0.1:8188').rstrip('/')


_http = gpu_arbiter._http


def hand_off(comfy, *, on_wait=None, timeout=3600, poll=5, opener=_http, sleep=time.sleep):
    """Wait for ComfyUI's queue to empty (never interrupt a render), then POST /free and wait for the VRAM."""
    try:
        return gpu_arbiter.free_comfy(comfy, on_wait=on_wait, timeout=timeout, poll=poll, opener=opener, sleep=sleep)
    except gpu_arbiter.GpuBusy:
        raise GradeError('ComfyUI stayed busy; grade again once the renders finish.') from None


def vision(config, brief_text, prompt, sheet, *, opener=None, admission=None):
    """One governed vision call. The admission binds the Continuity Supervisor's configured endpoint; the grader's
    own low effort is a request setting, not a different provider."""
    from project_assistant import agent_registry, providers
    from project_assistant.execution_governance import AdmissionError
    text = 'Brief: ' + brief_text + '\nShot prompt: ' + prompt
    try:
        result = providers.run_openai_compat_turn(
            config=dataclasses.replace(config, effort='low'), instructions=RUBRIC, turn_text=text, timeout=VISION_TIMEOUT,
            tool_specs=[], call_tool=lambda *_: (_ for _ in ()).throw(ValueError('The grader cannot call tools.')),
            images=['data:image/png;base64,' + base64.b64encode(sheet).decode('ascii')],
            **({'opener': opener} if opener else {}), **({'admission': admission} if admission else {}))
    except (AdmissionError, agent_registry.AgentError) as exc:
        raise GradeError('Model governance refused the grading call: ' + str(exc)) from None
    if result.status != 'ok':
        raise GradeError('The vision model did not answer: ' + (result.error or result.status))
    return result.answer


def unload(config, opener=_http):
    """keep_alive 0 on an Ollama-style local endpoint; other endpoints manage their own memory."""
    return gpu_arbiter.unload_model(config.base_url, config.model, opener)


def scorecard(answer, prompt):
    text = re.sub(r'(?s)<think>.*?</think>', '', answer or '')
    match = re.search(r'(?s)\{.*\}', text)
    try:
        value = json.loads(match[0]) if match else None
    except ValueError:
        value = None
    if (not isinstance(value, dict) or type(value.get('score')) is not int or not 0 <= value['score'] <= 100
            or type(value.get('passed')) is not bool):
        raise GradeError('The vision model returned an unreadable scorecard.')
    issues = [str(i)[:500] for i in value.get('issues') or [] if isinstance(i, str)][:12]
    retake = str(value.get('retake_prompt') or '').strip()[:4000]
    if retake:
        tags = [t for t in re.findall(r'@[A-Z]+-\d+(?::[A-Z0-9_-]+)?', prompt, re.I) if t not in retake]
        retake = ' '.join([retake, *tags])
    return {'score': value['score'], 'passed': value['passed'], 'issues': issues,
            'feedback': str(value.get('feedback') or '')[:3000], 'retakePrompt': retake}
