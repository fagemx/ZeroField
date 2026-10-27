"""Studio tools use current actor authority and the existing Story/M8 write boundary."""
from __future__ import annotations

import base64
import copy
import json
import re
import tempfile
from pathlib import Path

from project_assistant import agent_registry, orchestration_store as db, orchestrator as cp, privacy
from project_docs import repository as repo, story_openapi as story, story_allocation


def episode(ctx, conn, args):
    ep = story.episode(conn, args['episode_id'])
    if ep['slug'] != ctx.slug:
        raise ValueError('Episode belongs to another production.')
    cp.actor(conn, ctx.slug, ctx.me)
    return ep


def selection(ctx, conn, ep, ids):
    items = story_allocation.current_shots(conn, ep, ids)
    from project_assistant.tools import _request_scope
    scope = _request_scope(ctx, conn)
    if scope:
        for item in items:
            _, row = story.find_row(conn, item['shotId'], 'shot')
            if row['tabKey'] != scope['target_tab'] or row['rid'] not in scope.get('row_ids', []):
                raise ValueError('Studio action exceeds the selected rows.')
    return items


def unrestricted(ctx, conn):
    from project_assistant.tools import _request_scope
    if _request_scope(ctx, conn):
        raise ValueError('This production-wide action requires an unscoped crew request.')


def source_stamp(ctx, conn):
    profile = agent_registry.get_agent(conn, ctx.slug, ctx.agent_key)
    return {'profile_version': profile['version'], 'provider_binding': profile.get('provider_binding'), 'policy': story.production_policy(conn, ctx.slug),
            'privacy': privacy.mode(conn, ctx.slug),
            'tabs': {t['key']: cp.digest(cp.freeze_tab(conn, ctx.slug, t['key'])) for t in repo.list_tabs(conn, ctx.slug)}}


def request_review(ctx, conn, name, args):
    from project_assistant.delegation_tools import ask_decision_gate
    frozen = source_stamp(ctx, conn)
    preview = {'tool': name, 'arguments': privacy.sanitize(args, privacy.mode(conn, ctx.slug))}
    pending = json.loads(ask_decision_gate(ctx, conn, {'question': ('Approve ' + name + '?\n' + json.dumps(preview['arguments'], ensure_ascii=False))[:3900],
                                                    'options': ['Approve action', 'Cancel action']}))
    gate = db.get_gate(conn, ctx.slug, pending['gate_id'])
    action = {'kind': 'tool_action', 'tool': name, 'args': copy.deepcopy(args), 'source': frozen, 'preview': preview,
              'tool_cache_key': cp.digest({'tool': name, 'args': args}), 'agent_key': ctx.agent_key}
    db.execute(conn, 'UPDATE projectops.orchestration_gate SET continuation=%s::jsonb WHERE id=%s',
               (json.dumps({**(gate['continuation'] or {}), 'action': action}), gate['id']))
    return json.dumps(pending)


def validate_review(ctx, conn, gate):
    from project_assistant.agent_policy import authorize_tool
    action = gate['continuation']['action']
    run = cp.own_run(conn, ctx.me, ctx.slug, gate['run_id'])
    if run['status'] == 'canceled' or action['agent_key'] != ctx.agent_key:
        raise ValueError('Studio review is no longer authorized.')
    authorize_tool(ctx, conn, action['tool'], action['args'])
    if source_stamp(ctx, conn) != action['source']:
        raise ValueError('Studio source, policy, privacy or agent configuration changed; request a new review.')


def approve_review(conn, me, slug, gate, dispatch):
    """Called only by the existing owner-only gate resolver, before issuing a new admission."""
    from project_assistant.tools import ToolContext
    ctx = ToolContext(lambda: None, slug, me, Path('.'), None, agent_key=dispatch['agent_key'],
                      scope=cp.effective_scope(conn, dispatch), write_mode=db.get_task(conn, slug, dispatch['task_id'])['write_mode'])
    from project_assistant.tools import ToolError
    try:
        validate_review(ctx, conn, gate)
    except ToolError:
        raise cp.OrchestrationError(403, 'Current tool permission no longer permits this action.') from None
    except ValueError:
        raise cp.OrchestrationError(409, 'Source, policy or agent configuration changed; request a new review.', 'SOURCE_CHANGED') from None


def studio_ingest_script(ctx, conn, args):
    ep = episode(ctx, conn, args)
    unrestricted(ctx, conn)
    story.set_script(conn, ctx.me, ep, args['script'])
    assets = story.extract(conn, ctx.me, ep)
    shots = story.build_shots(conn, ctx.me, ep)
    return {'episode_id': ep['episodeId'], 'assets': assets, 'storyboard': shots}


def studio_manage_asset(ctx, conn, args):
    ep = episode(ctx, conn, args)
    unrestricted(ctx, conn)
    operation = args['operation']
    body = {k: args[k] for k in ('name', 'prompt', 'type', 'key', 'kind') if k in args}
    if operation == 'create':
        path, method = f"/episodes/{ep['episodeId']}/assets", 'POST'
    else:
        identifier = args.get('asset_id')
        if identifier not in {a['assetId'] for a in story.assets(conn, ep)}:
            raise ValueError('Asset must belong to the active production.')
        path, method = '/assets/' + identifier, 'PATCH'
        if operation == 'variant':
            path, method = path + '/variants', 'POST'
    return story.dispatch(conn, ctx.me, method, path, body, {}, ctx.post_commit_actions)


def studio_plan_allocation(ctx, conn, args):
    ep = episode(ctx, conn, args)
    selection(ctx, conn, ep, args.get('shot_ids'))
    body = {wire: args[key] for key, wire in [('shot_ids', 'shotIds'), ('budget_mode', 'budgetMode'), ('time_pressure', 'timePressure'), ('app_code', 'appCode')] if key in args}
    return story_allocation.plan(conn, ctx.me, ep, body, local_comfy_online=ctx.local_comfy_online)


def studio_dispatch_shot(ctx, conn, args):
    ep = episode(ctx, conn, args)
    items = selection(ctx, conn, ep, args['shot_ids'])
    saved = story.owned(conn, ctx.me, args['allocation_id'], 'allocation')
    if saved['slug'] != ctx.slug or saved['episodeId'] != ep['episodeId'] or saved.get('consumed'):
        raise ValueError('Allocation is foreign or already consumed.')
    if saved['options']['production_policy'] != story.production_policy(conn, ctx.slug) or saved['guards'] != story_allocation.source_guard(conn, items):
        raise ValueError('Allocation sources, selection or policy changed; preview again.')
    plans = saved['plan']['allocations']
    if {a['shot_id'] for a in plans} != {s['shotId'] for s in items} or saved['plan'].get('readiness_scope') != 'configuration_and_inputs':
        raise ValueError('Allocation does not bind the complete reviewed selection.')
    # Revalidate the entire batch before consuming or enqueueing even the first shot.
    for allocation in plans:
        story_allocation.preflight_inputs(conn, ctx.slug, allocation['shot_id'], allocation, saved['cards'])
    if not saved['plan'].get('ready') or not plans or any(not a['ready'] for a in plans):
        raise ValueError('Allocation has configuration or input blockers.')
    from project_assistant import story_media_adapter, execution_governance
    guard = getattr(ctx, 'execution_guard', None)
    if not callable(guard):
        raise ValueError('Runtime media budget/environment admission is unavailable.')
    accounting = copy.copy(ctx)
    accounting.episode_id = ep['episodeId']
    guard(accounting, conn, 'media_dispatch', saved)
    results = []
    for allocation in plans:
        results.append(story_media_adapter.enqueue(conn, ctx.me, ctx.slug, allocation['shot_id'], allocation, {}, ctx.post_commit_actions, frozen_cards=saved['cards'], accounting_prefix=saved['allocationId'] + ':' + allocation['shot_id'], execution_agent_key=ctx.agent_key, grading_objective=getattr(ctx,'original_objective',None), accounting_session_key=execution_governance.session_key(ctx), budget_cap_usd=getattr(ctx,'budget_cap_usd',None)))
    saved['consumed'] = True
    story.store(conn, saved['allocationId'], 'allocation', saved)
    return {'allocationId': saved['allocationId'], 'runs': results, 'reviewRequired': True}


def studio_edit_timeline(ctx, conn, args):
    ep = episode(ctx, conn, args)
    operation = args['operation']
    ids = args.get('shot_ids', [])
    if operation == 'export':
        unrestricted(ctx, conn)
        if ids:
            raise ValueError('Episode export uses the complete approved timeline.')
        path = f"/episodes/{ep['episodeId']}/films"
        guard = getattr(ctx, 'execution_guard', None)
        if not callable(guard):
            raise ValueError('Runtime export admission is unavailable.')
        guard(ctx, conn, 'film_export', args)
        body = {}
    else:
        selection(ctx, conn, ep, ids)
        if operation == 'split' and len(ids) != 1 or operation == 'merge' and len(ids) < 2:
            raise ValueError('Split needs one shot; merge needs at least two.')
        path = f'/shots/{ids[0]}/splits' if operation == 'split' else '/shot-merges'
        body = {} if operation == 'split' else {'shotIds': ids}
    return story.dispatch(conn, ctx.me, 'POST', path, body, {}, ctx.post_commit_actions)


def frame_source(ctx, conn, args):
    ep = episode(ctx, conn, args)
    item = selection(ctx, conn, ep, [args['shot_id']])[0]
    if privacy.mode(conn, ctx.slug) == 'mask_numbers':
        raise ValueError('Numeric masking does not permit image inspection/export.')
    candidates = story.candidate_list(conn, args['shot_id'], 'video')
    if args.get('candidate_id'):
        candidate = next((c for c in candidates if c['videoId'] == args['candidate_id']), None)
        url = candidate['url'] if candidate else ''
    else:
        url = item.get('selectedVideoUrl') or ''
    match = re.fullmatch(r'/projects/api/' + re.escape(ctx.slug) + r'/assets/(pa_[0-9a-f]{32})', url)
    if not match:
        raise ValueError('Choose an authorized source or candidate video from this shot.')
    meta = repo.get_asset_meta(conn, ctx.slug, match[1])
    from project_assistant.studio.runtime import MAX_MEDIA
    if not meta or not meta[0].startswith('video/') or not 0 < meta[1] <= MAX_MEDIA:
        raise ValueError('Video is missing, too large or has an invalid media type.')
    return match[1]


def studio_inspect_frames(ctx, conn, args):
    """The shared boundary releases its transaction before calling this handler."""
    identifier = frame_source(ctx, conn, args)
    content_type, raw = repo.get_asset(conn, ctx.slug, identifier)
    fingerprint = frame_fingerprint(ctx.slug, raw)
    cached = story.record(conn, 'frames_' + fingerprint, required=False)
    conn.rollback()  # No transaction/locks across FFmpeg.
    if cached and cached.get('slug') == ctx.slug:
        asset = repo.get_asset(conn, ctx.slug, cached['asset_id'])
        conn.rollback()
    else:
        asset = None
    if asset:
        sheet, timing = bytes(asset[1]), cached['timing']
    else:
        # shortcut: concurrent first cache misses may both render locally; add single-flight if measured.
        from project_assistant import limb_worker as worker, execution_governance as governance
        from project_assistant.studio.media_prep import build_video_frame_sheet
        import uuid
        def render():
            with tempfile.TemporaryDirectory(prefix='studio-inspect-') as folder:
                path = Path(folder) / 'source.mp4'
                path.write_bytes(raw)
                media = worker._probe_video(path, {'probe_timeout':governance.remaining(ctx, 60)})
                image, timing = build_video_frame_sheet(path, media['duration'], Path(folder), {'timeout':governance.remaining(ctx), '_lease_lost':lambda:governance.lease_ended(ctx)})
                return image.read_bytes(), timing
        sheet, timing = governance.run_operation(ctx, 'inspect:' + uuid.uuid4().hex, render, model_name='frame_sheet', fingerprint=fingerprint)
    from project_assistant.agent_policy import authorize_tool
    cp.lock_project(conn, ctx.slug)
    authorize_tool(ctx, conn, 'studio_inspect_frames', args)
    if frame_source(ctx, conn, args) != identifier:
        raise ValueError('Video changed during inspection.')
    if not asset:
        aid = repo.put_asset(conn, ctx.slug, data=sheet, content_type='image/png', actor_id=ctx.me.actor_id)
        story.store(conn, 'frames_' + fingerprint, 'frame_sheet', {'slug': ctx.slug, 'asset_id': aid, 'timing': timing}, ctx.slug, ctx.me.actor_id)
    else:
        aid = cached['asset_id']
    if asset:
        from project_assistant import agent_console_store as resources
        import uuid
        resources.append_usage(conn,ctx.slug,{'event_key':'frame-cache:' + uuid.uuid4().hex, 'owner_id':ctx.me.actor_id,
            'run_id':getattr(ctx,'run_id',None),'episode_id':args['episode_id'],'agent_key':ctx.agent_key,'usage_kind':'frame_prep',
            'provider_name':'local','model_name':'frame_sheet','cache_hit':True,'fingerprint':fingerprint,
            'meta':{'estimated':True,'outcome':'succeeded'}})
    ctx.pending_images.append('data:image/png;base64,' + base64.b64encode(sheet).decode('ascii'))
    return {'fingerprint': fingerprint, 'frame_sheet_asset_id': aid, 'cache_hit': bool(asset), 'timing_seconds': timing, 'frames': 8, 'width': 1600, 'height': 600}


def consult_advisor(ctx, conn, args):
    from project_assistant import agent_runtime, prompting, agent_console_store as resources
    current = agent_registry.get_agent(conn, ctx.slug, ctx.agent_key)
    key = current['multiagent_config']['advisor_agent_key']
    advisor = agent_registry.get_agent(conn, ctx.slug, key) if key else None
    if getattr(ctx, 'advisor_call', False) or not advisor or not advisor['enabled'] or advisor['role_kind'] == 'observer' or key == ctx.agent_key or advisor['runtime_kind'] != 'builtin_llm':
        raise ValueError('No independent authorized built-in advisor is configured.')
    config = agent_runtime.provider_for(advisor)
    if config.kind == 'codex_cli':
        raise ValueError('Advisor consultation cannot launch a CLI.')
    bindings = resources.execution_resources(conn, ctx.me, ctx.slug, key, destination=config.base_url or None)
    hook = getattr(ctx, 'runtime_cost_hook', None)
    if not callable(hook):
        raise ValueError('Advisor runtime cost admission is unavailable.')
    hook(ctx, conn, 'advisor_check', advisor)
    system, knowledge = prompting.load_agent(advisor)
    mode = privacy.mode(conn, ctx.slug)
    remaining = (cp.instant(ctx.deadline_at) - cp.now()).total_seconds() if getattr(ctx, 'deadline_at', None) else 45
    if remaining <= 0:
        raise ValueError('Advisor deadline expired.')
    timeout = min(45, remaining, bindings['environment']['config'].get('timeout_seconds', 45))
    version = advisor['version']
    conn.commit()  # Reservations and resource checks are short; inference is outside the transaction.
    isolated = copy.copy(ctx)
    isolated.agent_key, isolated.advisor_call = key, True
    isolated.allowed_tools = set()
    isolated.pending_images = []
    isolated.governance_phase = 'advisor:' + cp.digest(args)
    isolated.governance_origin = getattr(ctx, 'governance_origin', ctx)
    isolated.accounting_session_key = getattr(ctx, 'accounting_session_key', None)
    readonly = {**advisor, 'allowed_tools': [], 'multiagent_config': {'allow_subagents': False, 'allow_workflows': False, 'advisor_agent_key': None}}
    result = agent_runtime.run_agent(profile=readonly, ctx=isolated,
        instructions=privacy.sanitize(system + '\n' + knowledge + '\nGive one focused critique only. No actions, delegation, or conversation history.', mode),
        turn_text=privacy.sanitize(json.dumps(args, ensure_ascii=False), mode), timeout=timeout)
    from project_assistant.agent_policy import authorize_tool
    cp.lock_project(conn, ctx.slug)
    authorize_tool(ctx, conn, 'consult_advisor', args)
    live = agent_registry.get_agent(conn, ctx.slug, key)
    caller = agent_registry.get_agent(conn, ctx.slug, ctx.agent_key)
    resources.execution_resources(conn, ctx.me, ctx.slug, key, destination=config.base_url or None)
    if privacy.mode(conn, ctx.slug) != mode or caller['multiagent_config']['advisor_agent_key'] != key:
        raise ValueError('Advisor authority or privacy changed during consultation.')
    if not live or not live['enabled'] or live['version'] != version:
        raise ValueError('Advisor configuration changed during consultation.')
    hook(ctx, conn, 'advisor_result', {'profile': advisor, 'status': result.status})
    if result.status != 'ok':
        raise ValueError('Advisor did not return a critique.')
    return {'advisor_agent_key': key, 'critique': result.answer[:12000], 'isolated': True}


def public_result(conn, slug, value):
    """Sanitize production prose without masking trusted hashes, IDs or typed counters."""
    prose = {'name', 'prompt', 'description', 'opticalRig', 'cameraMotion', 'critique'}
    def clean(item, key=None):
        if isinstance(item, dict):
            return {k: clean(v, k) for k, v in item.items()}
        if isinstance(item, list):
            return [clean(v, key) for v in item]
        if isinstance(item, str):
            if key and key.lower().endswith('url') and not re.fullmatch(r'/projects/api/' + re.escape(slug) + r'/assets/pa_[0-9a-f]{32}', item):
                return None
            if key in prose:
                return re.sub(r'(?i)\bbearer\s+\S+', '[redacted credential]', privacy.text(conn, slug, item)[0])
        return item
    return clean(value)


def frame_fingerprint(slug, raw):
    import hashlib
    return cp.digest({'slug': slug, 'video': hashlib.sha256(raw).hexdigest(), 'format': 'frame_sheet-v1'})


def cached_frame_images(ctx, conn, args, result):
    source = frame_source(ctx, conn, args)
    raw = repo.get_asset(conn, ctx.slug, source)[1]
    saved = json.loads(result)
    if saved.get('fingerprint') != frame_fingerprint(ctx.slug, raw):
        raise ValueError('Reviewed inspection source changed; request another inspection.')
    image = repo.get_asset(conn, ctx.slug, saved['frame_sheet_asset_id'])
    if not image or image[0] != 'image/png':
        raise ValueError('Contact sheet is no longer available.')
    return ['data:image/png;base64,' + base64.b64encode(image[1]).decode('ascii')]


from project_assistant import tool_registry  # noqa: E402  (registration lives in the declarative registry)
HANDLERS = tool_registry.handlers(__name__, globals())
EXTERNAL_TOOLS = set(tool_registry.EXTERNAL)
