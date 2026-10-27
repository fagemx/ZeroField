"""Continuity grading of sheet-row takes.

The Continuity Supervisor's vision model grades the product's 8-frame contact sheet of a take with the rubric the
Phase 2 hand grading used. LTX-2.5 and a local vision model do not fit on one 24 GB GPU together, so a grade takes the
cross-process GPU arbiter (SPEC_20 R13): when ComfyUI held the GPU last, it waits for ComfyUI to go idle (it never
interrupts a render) and frees ComfyUI's models; takes of one shot are graded together in one hold, and the vision model
stays loaded until a render needs the GPU. The vision call is governed like an agent turn (SPEC_20 R11): a loopback
endpoint is unbilled, any other must pass the environment, credential and price checks before frames leave.
A failing grade carries the grader's rewritten prompt; Retake with it in shot review applies it and re-shoots in one click.

A cut check (SPEC_19 R17) is the second question the same supervisor answers: two frames side by side, the outgoing
shot's out point and the incoming shot's in point, judged for positions, wardrobe, props, light direction and eyeline.
It rides the same queue, the same GPU arbiter and the same governance as a grade; the queued cuts of one episode are
checked in one GPU hold. Its record (kind ``cut_check``) is keyed by both shots, both take URLs and both cut points, so
a new take or a new trim on either side simply has no result yet; ``story_cuts`` lists them. Like a grade, a cut check
is information only: it never blocks adoption or export.
"""
from __future__ import annotations

import base64
import dataclasses
import hashlib
import io
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
CUT_RUBRIC = ("You are the continuity supervisor checking a cut. The image shows two frames side by side: LEFT is the last "
              "frame of the outgoing shot, RIGHT is the first frame of the incoming shot that plays right after it. Judge "
              "whether the incoming shot can follow directly: character positions and screen direction, wardrobe, props "
              "(present or missing, which hand holds them), lighting direction, and eyeline (where each character looks). "
              "A change the shot prompts call for is not an issue. Score 0-100 and list concrete issues that name both "
              "shots and the detail (for example: \"S02 ends with the recorder in the left hand; S03 starts with it in the "
              "right hand.\"). Reply JSON only: "
              '{"score": int, "passed": bool, "issues": [str], "feedback": str}.')
KIND = 'take_grade'
CUT_KIND = 'cut_check'
SETTING = 'auto_grade_takes'
SHOT_TABS = ('cinema-studio', 'openjutsu-lab')
ACTIVE = ('queued', 'waiting_gpu', 'grading')
STALE_SECONDS = 15 * 60
VISION_TIMEOUT = 600
GPU_WAIT = 3600  # longest a grade waits for renders holding the GPU
# Compatibility name: the cross-process arbiter replaced this process-local lock (SPEC_20 R13).
GPU_LOCK = gpu_arbiter.CompatLock()
FREE_TARGET = gpu_arbiter.FREE_TARGET
MASKED = 'Numeric masking does not permit sending frames to the vision model.'
CUT_PANEL = (640, 360)  # each frame of a cut sheet is fitted into this box

_wake = threading.Event()
_guard = threading.Lock()
_started = False


class GradeError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def record_id(shot_id, asset_id):
    return f'grade_{shot_id}_{asset_id}'


def cut_record_id(cut):
    """One record per (both shots, both take URLs, out point, in point): any change on either side is a new key."""
    key = [cut['fromShotId'], cut['toShotId'], cut['fromTakeUrl'], cut['toTakeUrl'],
           None if cut['outAt'] is None else float(cut['outAt']), float(cut['inAt'] or 0)]
    return 'cut_' + hashlib.sha256(json.dumps(key, separators=(',', ':')).encode()).hexdigest()[:40]


def in_flight(record):
    """Queued, waiting for the GPU or being graded, and not abandoned by a grader that died."""
    return (bool(record) and record.get('status') in ACTIVE
            and time.time() - datetime.fromisoformat(record['requestedAt']).timestamp() < STALE_SECONDS)


def _take_asset(conn, slug, url):
    """The pa_ id of a video asset of this production within the media cap, or None."""
    from project_docs import repository as repo
    from project_assistant.studio.runtime import MAX_MEDIA
    match = re.fullmatch(r'/projects/api/' + re.escape(slug) + r'/assets/(pa_[0-9a-f]{32})', url or '')
    meta = repo.get_asset_meta(conn, slug, match[1]) if match else None
    return match[1] if meta and meta[0].startswith('video/') and 0 < meta[1] <= MAX_MEDIA else None


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
    from project_docs import story_openapi as story
    from project_assistant import privacy
    asset_id = _take_asset(conn, slug, asset_url)
    if not asset_id:
        raise GradeError('Choose a video take from this production to grade.')
    if privacy.mode(conn, slug) != 'full_access':
        raise GradeError(MASKED)
    key = record_id(shot_id, asset_id)
    current = story.record(conn, key, required=False, lock=True)
    if in_flight(current):
        return current
    return story.store(conn, key, KIND, {'gradeId': key, 'shotId': shot_id, 'assetId': asset_id, 'assetUrl': asset_url,
                                         'status': 'queued', 'auto': auto, 'requestedBy': owner_id, 'requestedAt': now()}, slug)


def enqueue_cut(conn, slug, episode_id, cut, owner_id, *, auto=False):
    """Queue (or return the in-flight) check of one cut, a ``story_cuts`` item whose two sides are adopted takes.

    The caller commits, then calls kick(). Raises GradeError when either side is not a video of this production or the
    production masks numbers.
    """
    from project_docs import story_openapi as story
    from project_assistant import privacy
    assets = [_take_asset(conn, slug, cut[key]) for key in ('fromTakeUrl', 'toTakeUrl')]
    if not all(assets):
        raise GradeError('Both sides of a cut must be adopted video takes from this production.')
    if privacy.mode(conn, slug) != 'full_access':
        raise GradeError(MASKED)
    key = cut_record_id(cut)
    current = story.record(conn, key, required=False, lock=True)
    if in_flight(current):
        return current
    return story.store(conn, key, CUT_KIND, {
        'checkId': key, 'episodeId': episode_id, 'fromShotId': cut['fromShotId'], 'toShotId': cut['toShotId'],
        'fromShotIndex': cut.get('fromShotIndex'), 'toShotIndex': cut.get('toShotIndex'),
        'fromTakeUrl': cut['fromTakeUrl'], 'toTakeUrl': cut['toTakeUrl'], 'fromAssetId': assets[0], 'toAssetId': assets[1],
        'outAt': None if cut['outAt'] is None else float(cut['outAt']), 'inAt': float(cut['inAt'] or 0),
        'status': 'queued', 'auto': auto, 'requestedBy': owner_id, 'requestedAt': now()}, slug)


def cut_check_view(record):
    """The ``check`` of a cut: state none (no result for these takes and points), queued, done or failed.

    The shape is always the same; fields that do not apply are None (issues: []). An in-flight record a dead grader
    abandoned (older than STALE_SECONDS) reads as none, so it can be queued again.
    """
    status = (record or {}).get('status')
    state = {'graded': 'done', 'failed': 'failed'}.get(status) or ('queued' if in_flight(record) else 'none')
    if state == 'none':
        record = {}
    done = state == 'done'
    return {'state': state, 'checkId': record.get('checkId'), 'score': record.get('score') if done else None,
            'passed': record.get('passed') if done else None, 'issues': list(record.get('issues') or []) if done else [],
            'feedback': record.get('feedback') if done else None, 'frameSheetUrl': record.get('sheetUrl') if done else None,
            'frames': record.get('frames') if done else None, 'error': record.get('error') if state == 'failed' else None,
            'auto': record.get('auto'), 'requestedAt': record.get('requestedAt'), 'checkedAt': record.get('gradedAt') if done else None}


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
    """Grade every queued take and check every queued cut, oldest first, one queue; the queued takes of one shot (and
    the queued cuts of one episode) run together in one GPU hold (SPEC_20 R13), and the GPU is released between them so
    waiting renders get their turn. Returns how many ran."""
    count = 0
    while True:
        conn = connect()
        try:
            job = _claim(conn)
            if not job:
                return count
            with _Phase() as phase:
                while job:
                    cut = 'checkId' in job
                    try:
                        (_check_cut if cut else _grade)(conn, job, connect=connect, phase=phase)
                    except Exception as exc:
                        conn.rollback()
                        _save(conn, job, status='failed', error=str(exc)[:500] if isinstance(exc, GradeError) else
                              ('The cut check failed' if cut else 'Grading failed') +
                              '; check the Continuity Supervisor model endpoint and retry.')
                    count += 1
                    job = _claim(conn, episode_id=job['episodeId']) if cut else _claim(conn, shot_id=job['shotId'])
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


def _claim(conn, shot_id=None, episode_id=None):
    """The oldest queued grade or cut check; with shot_id only that shot's grades, with episode_id only that episode's cuts."""
    with conn.cursor() as cur:
        cur.execute("""SELECT data, project_slug FROM projectops.story_record WHERE kind IN (%s, %s) AND data->>'status'='queued'
                       AND (%s::text IS NULL OR (kind=%s AND data->>'shotId'=%s))
                       AND (%s::text IS NULL OR (kind=%s AND data->>'episodeId'=%s))
                       ORDER BY updated_at LIMIT 1 FOR UPDATE SKIP LOCKED""",
                    (KIND, CUT_KIND, shot_id, KIND, shot_id, episode_id, CUT_KIND, episode_id))
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
    key, kind = (job['checkId'], CUT_KIND) if 'checkId' in job else (job['gradeId'], KIND)
    story.store(conn, key, kind, {k: v for k, v in job.items() if k != 'slug'}, job['slug'])
    conn.commit()


def _supervisor(conn, slug):
    """The Continuity Supervisor's profile and vision endpoint, once the production allows frames to leave."""
    from project_assistant import agent_registry, agent_runtime, privacy
    if privacy.mode(conn, slug) != 'full_access':
        raise GradeError(MASKED)
    profile = agent_registry.get_agent(conn, slug, 'qa_critic')
    if not profile:
        raise GradeError('This production has no Continuity Supervisor.')
    if not profile.get('enabled', True):
        raise GradeError('The Continuity Supervisor is disabled for this production.')
    config = agent_runtime.provider_for(profile)
    if config.kind != 'openai_compat':
        raise GradeError('Continuity grading needs an OpenAI-compatible vision endpoint for the Continuity Supervisor.')
    return profile, config


def _on_gpu(conn, job, config, comfy, phase, ask):
    """Run ask() in a GPU hold: the caller's phase, or one of its own released afterwards. Returns (answer, gpu facts,
    monotonic start of ask)."""
    own = phase is None
    phase = phase or _Phase()
    try:
        gpu = phase.hold(config, comfy, on_wait=lambda: _save(conn, job, status='waiting_gpu'))
        _save(conn, job, status='grading')
        started = time.monotonic()  # seconds = model load + grading, not the wait for renders
        answer = ask()
    finally:
        if own:
            phase.release()
    return answer, gpu, started


def _grade(conn, job, *, connect=None, phase=None):
    from project_docs import repository as repo, story_openapi as story
    from project_assistant import execution_governance as governance
    slug = job['slug']
    _, row = story.find_row(conn, job['shotId'], 'shot')
    profile, config = _supervisor(conn, slug)
    found = repo.get_asset(conn, slug, job['assetId'])
    if not found:
        raise GradeError('The take is no longer in this production.')
    comfy = comfy_url(conn, slug)
    view = story.shot_view(conn, slug, row)
    conn.commit()  # no transaction across FFmpeg, the GPU wait or inference
    sheet, timing = frame_sheet(bytes(found[1]))
    # Governed like an agent turn (SPEC_20 R11): reserved, attributed to the Continuity Supervisor, settled per §4.1.
    admission = governance.ProviderAdmission(grading_context(job, connect), profile, config, 'grader_check', purpose='continuity_grade')
    answer, gpu, started = _on_gpu(conn, job, config, comfy, phase,
                                   lambda: vision(config, brief(view), view['description'], sheet, admission=admission))
    card = scorecard(answer, view['description'])
    sheet_id = repo.put_asset(conn, slug, data=sheet, content_type='image/png', actor_id=job['requestedBy'])
    _save(conn, job, status='graded', **card, gradedAt=now(),
          sheetUrl=f'/projects/api/{slug}/assets/{sheet_id}', timing=timing, model=config.model,
          seconds=round(time.monotonic() - started, 1), gpu=gpu)


def _check_cut(conn, job, *, connect=None, phase=None):
    """Check one queued cut: both frames, side by side, in the same GPU hold and under the same governance as a grade."""
    from project_docs import repository as repo, story_openapi as story
    from project_assistant import execution_governance as governance
    slug = job['slug']
    try:
        views = [story.shot_view(conn, slug, story.find_row(conn, job[key], 'shot')[1]) for key in ('fromShotId', 'toShotId')]
    except story.StoryError:
        raise GradeError('A shot of this cut is no longer in this production.') from None
    profile, config = _supervisor(conn, slug)
    found = [repo.get_asset(conn, slug, job[key]) for key in ('fromAssetId', 'toAssetId')]
    if not all(found):
        raise GradeError('A take of this cut is no longer in this production.')
    comfy = comfy_url(conn, slug)
    conn.commit()  # no transaction across FFmpeg, the GPU wait or inference
    labels = [job.get(key) or view['shotIndex'] for key, view in zip(('fromShotIndex', 'toShotIndex'), views)]
    sheet, frames = cut_sheet(bytes(found[0][1]), job['outAt'], bytes(found[1][1]), job['inAt'], labels)
    text = cut_brief(labels, views, frames)
    admission = governance.ProviderAdmission(grading_context(job, connect), profile, config, 'grader_check', purpose='cut_check')
    answer, gpu, started = _on_gpu(conn, job, config, comfy, phase, lambda: cut_vision(config, text, sheet, admission=admission))
    card = cut_scorecard(answer)
    sheet_id = repo.put_asset(conn, slug, data=sheet, content_type='image/png', actor_id=job['requestedBy'])
    _save(conn, job, status='graded', **card, gradedAt=now(),
          sheetUrl=f'/projects/api/{slug}/assets/{sheet_id}', frames=frames, model=config.model,
          seconds=round(time.monotonic() - started, 1), gpu=gpu)


def grading_context(job, connect=None):
    """Admission context for one grading attempt or cut check: the requester's authority, the Continuity Supervisor's
    environment, and a session key the console groups the spend by (grade:<id> or cut:<id>)."""
    from project_docs import service
    from project_assistant import execution_governance as governance
    prefix, record = ('cut:', job['checkId']) if 'checkId' in job else ('grade:', job['gradeId'])
    session = prefix + record
    ctx = governance.media_context(service.Identity(job['requestedBy'], 'Continuity grader', 'member'), job['slug'],
                                   agent_key='qa_critic', accounting_session_key=session if len(session) <= 160 else
                                   prefix + governance.cp.digest(record),
                                   execution_key='%s%s:%s' % (prefix, record, job.get('startedAt') or now()))
    if connect is not None:
        ctx.connection_factory = connect
    return ctx


def brief(view):
    return ', '.join(v for v in (view['shotIndex'], view['cameraMotion'], view['opticalRig']) if v) + '. ' + view['description']


def cut_brief(labels, views, frames):
    out, into = labels
    return (f"Cut from {out} to {into}. LEFT: last frame of {out} at {frames['outSeconds']:.3f}s. "
            f"RIGHT: first frame of {into} at {frames['inSeconds']:.3f}s.\n"
            f"{out} prompt: {views[0]['description']}\n{into} prompt: {views[1]['description']}")


def frame_sheet(raw):
    from project_assistant import limb_worker
    from project_assistant.studio.media_prep import build_video_frame_sheet
    with tempfile.TemporaryDirectory(prefix='take-grade-') as folder:
        path = Path(folder) / 'take.mp4'
        path.write_bytes(raw)
        media = limb_worker._probe_video(path, {'probe_timeout': 60})
        image, timing = build_video_frame_sheet(path, media['duration'], Path(folder), {'timeout': 120})
        return image.read_bytes(), timing


def _edge_frame(path, at, edge, folder):
    """(PNG path, seconds) of the outgoing take's last played frame (edge "out") or the incoming take's first (edge "in").

    out: the frame before ``at`` (the trim's out point), or the take's own last frame when it is untrimmed (``at`` None)
    or trimmed past its end. in: the first frame at or after ``at`` (the trim's in point, 0 untrimmed), as the film
    export cuts it.
    """
    from project_assistant import limb_worker
    media = limb_worker._probe_video(path, {'probe_timeout': 60})
    step = 1 / media['fps']
    image = folder / f'{edge}.png'
    if edge == 'out' and (at is None or at >= media['duration'] - 1e-6):
        seconds = max(0.0, media['duration'] - step)
        # Seeking near the end can land past the last decodable frame; keep overwriting one image to the end instead.
        args = ['-sseof', f'-{max(4 * step, 0.25):.6f}', '-i', str(path), '-an', '-update', '1', str(image)]
    else:
        seconds = max(0.0, (at - step) if edge == 'out' else min(at or 0.0, media['duration'] - step))
        args = ['-ss', f'{max(0.0, seconds - 1e-4):.6f}', '-i', str(path), '-an', '-frames:v', '1', str(image)]
    limb_worker._run_preparation(args, {'timeout': 120})
    if not image.is_file():
        raise GradeError(f'FFmpeg could not read the frame at {seconds:.3f}s of a take in this cut.')
    return image, round(seconds, 3)


def cut_sheet(out_raw, out_at, in_raw, in_at, labels=('', '')):
    """A cut check's input: the outgoing take's out frame (left) and the incoming take's in frame (right), side by side.

    Each frame is fitted into a CUT_PANEL box under a one-line label. Returns (PNG bytes, {'outSeconds', 'inSeconds'}),
    the moments of the two frames inside their takes.
    """
    from PIL import Image, ImageDraw
    width, height = CUT_PANEL
    top, gap = 24, 8
    with tempfile.TemporaryDirectory(prefix='cut-check-') as folder:
        folder = Path(folder)
        frames = []
        for edge, raw, at in (('out', out_raw, out_at), ('in', in_raw, in_at)):
            path = folder / f'{edge}.mp4'
            path.write_bytes(raw)
            frames.append(_edge_frame(path, at, edge, folder))
        sheet = Image.new('RGB', (2 * width + gap, top + height), 'white')
        draw = ImageDraw.Draw(sheet)
        for i, ((image, seconds), title) in enumerate(zip(frames, (f'OUT  {labels[0]}  last frame', f'IN  {labels[1]}  first frame'))):
            x = i * (width + gap)
            with Image.open(image) as frame:
                frame = frame.convert('RGB')
                scale = min(width / frame.width, height / frame.height)
                size = (max(1, round(frame.width * scale)), max(1, round(frame.height * scale)))
                panel = Image.new('RGB', (width, height), 'black')
                panel.paste(frame.resize(size, Image.Resampling.LANCZOS), ((width - size[0]) // 2, (height - size[1]) // 2))
            sheet.paste(panel, (x, top))
            label = f'{title} @ {seconds:.3f}s'.encode('ascii', 'replace').decode('ascii')  # the bitmap font is ASCII
            draw.text((x + 6, 5), label, fill='black')
        buffer = io.BytesIO()
        sheet.save(buffer, format='PNG')
    return buffer.getvalue(), {'outSeconds': frames[0][1], 'inSeconds': frames[1][1]}


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
    return _ask(config, RUBRIC, 'Brief: ' + brief_text + '\nShot prompt: ' + prompt, sheet, opener, admission)


def cut_vision(config, text, sheet, *, opener=None, admission=None):
    """The cut question: CUT_RUBRIC with the two-frame sheet, governed like a grade."""
    return _ask(config, CUT_RUBRIC, text, sheet, opener, admission)


def _ask(config, instructions, text, sheet, opener=None, admission=None):
    from project_assistant import agent_registry, providers
    from project_assistant.execution_governance import AdmissionError
    try:
        result = providers.run_openai_compat_turn(
            config=dataclasses.replace(config, effort='low'), instructions=instructions, turn_text=text, timeout=VISION_TIMEOUT,
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


def cut_scorecard(answer):
    """{score, passed, issues, feedback} of a cut; a cut has no retake prompt (which side to re-shoot is the director's call)."""
    card = scorecard(answer, '')
    return {key: card[key] for key in ('score', 'passed', 'issues', 'feedback')}
