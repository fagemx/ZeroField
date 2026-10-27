"""Handlers of the external-agent tools declared in tool_registry (SPEC_20 R30, R32, §4.7).

get_workflow reads the workflow guides in skills/<name>/SKILL.md. request_generation plans video takes with
the Story allocation planner under the production policy and submits only free local open-weights renders
(fixed decision 10: the crew may propose generation but never spends on its own). A plan with closed,
hosted or paid generation is refused with its estimate, so a crew member can review it in ZeroField.

Both run inside tools.call, which owns the transaction, the project lock, argument validation and the
policy checks (agent_policy narrows a service account to its token scope).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from project_assistant import tool_registry

SKILL_FILE = 'SKILL.md'
PAGE_CHARS = 5000  # stays below tools.MAX_OUT with the continuation note
MAX_GUIDE_BYTES = 512 * 1024
FREE_TIER, FREE_DRIVER = 'open_weights', 'comfy_local'
_GUIDE = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')


class Refusal(ValueError):
    """A refused request: tools.call reports '<code>: <message>' and rolls the transaction back."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


# ---------- get_workflow (R32) ----------

def _resource(*parts) -> Path:
    """A packaged resource: the checkout's file, else the installed wheel's (openbench_data)."""
    from openbench_data import resource_path
    return resource_path(*parts)


def guides() -> dict:
    """{name: SKILL.md path} of the installed manuals, read as resource_path('skills', name, 'SKILL.md') (R32).

    A missing or unreadable skills folder simply has none."""
    root = _resource('skills')
    try:
        names = sorted(entry.name for entry in root.iterdir() if entry.is_dir()) if root.is_dir() else []
        base = root.resolve()
    except OSError:
        return {}
    found = {}
    for name in names:
        if not _GUIDE.fullmatch(name):
            continue
        path = _resource('skills', name, SKILL_FILE)
        try:
            if path.is_file() and path.resolve().is_relative_to(base) and path.stat().st_size <= MAX_GUIDE_BYTES:
                found[name] = path
        except OSError:
            continue
    return found


def _read(path) -> str:
    try:
        return Path(path).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        raise Refusal('UNAVAILABLE', 'The workflow guide could not be read.') from None


def _description(text) -> str:
    """The description line of a SKILL.md front matter block, if any."""
    if not text.startswith('---'):
        return ''
    end = text.find('\n---', 3)
    for line in text[3:end if end > 0 else 0].splitlines():
        key, sep, value = line.partition(':')
        if sep and key.strip() == 'description':
            return value.strip().strip('"\'')[:500]
    return ''


def get_workflow(ctx, conn, args):
    found = guides()
    name = args.get('name')
    if name is None:
        if not found:
            return json.dumps({'status': 'unavailable', 'workflows': [],
                               'message': 'No workflow guides are installed on this server (skills/ is missing or empty).'})
        items = [{'name': key, 'description': _description(_read(path))} for key, path in found.items()]
        return json.dumps({'status': 'ok', 'workflows': items}, ensure_ascii=False)
    if name not in found:
        raise Refusal('NOT_FOUND', f'Workflow guide "{name}" is not installed. Available: {", ".join(found) or "none"}.')
    text = _read(found[name])
    offset = args.get('offset', 0)
    if offset and offset >= len(text):
        raise Refusal('INVALID_REQUEST', f'offset is past the end of the guide ({len(text)} characters).')
    end = min(len(text), offset + PAGE_CHARS)
    page = text[offset:end]
    if end < len(text):
        page += (f'\n\n[The guide continues: call get_workflow with name "{name}" and offset {end} '
                 f'({len(text)} characters in total).]')
    return page


# ---------- request_generation (R30, fixed decision 10) ----------

def _episode(ctx, conn, identifier):
    from project_docs import story_openapi as story
    ep = story.episode(conn, identifier)
    if ep['slug'] != ctx.slug:
        raise Refusal('POLICY_DENIED', 'The episode belongs to another production.')
    return ep


def _story_body(request):
    body = {'shotIds': request['shot_ids'], 'budgetMode': request['budget_mode']}
    if request.get('app_code'):
        body['appCode'] = request['app_code']
    return body


def _plan(ctx, conn, ep, request):
    from project_docs import story_allocation
    return story_allocation.plan(conn, ctx.me, ep, _story_body(request),
                                 local_comfy_online=getattr(ctx, 'local_comfy_online', None))


def _allocation(ctx, conn, identifier):
    from project_docs import story_openapi as story
    return story.owned(conn, ctx.me, identifier, 'allocation')


def _dispatch(ctx, conn, ep, request, allocation_id):
    """The Story API's own batch route: allocation revalidation, governance admission, queued tasks."""
    from project_docs import story_openapi as story
    return story.dispatch(conn, ctx.me, 'POST', f"/episodes/{ep['episodeId']}/shot-video-generations",
                          {**_story_body(request), 'allocationId': allocation_id}, {}, ctx.post_commit_actions)


def spend_reasons(saved) -> list[str]:
    """Why a saved allocation is not a free local open-weights render; empty when every shot is one."""
    from project_assistant import execution_governance as governance
    from project_assistant.providers import local_url
    from project_assistant.studio.card_engine import card_execution_profile
    reasons = []
    for allocation in saved['plan']['allocations']:
        shot = allocation.get('shot_id') or allocation.get('shotId')
        if allocation.get('tier') != FREE_TIER or allocation.get('driver') != FREE_DRIVER:
            reasons.append(f"{shot}: {allocation.get('tier')} generation through {allocation.get('driver')}")
            continue
        if allocation.get('race_plans') or any(s.get('kind') == 'approval' for s in allocation.get('stages', [])):
            reasons.append(f'{shot}: the plan needs a director approval stage or a race')
            continue
        for step in allocation.get('stages', []):
            if step.get('kind') != 'generate':
                continue
            card = (saved.get('cards') or {}).get(step.get('card_id'))
            try:
                profile = card_execution_profile(card) if card else None
                destination = governance.media_destination(card) if card else ''
            except Exception:  # noqa: BLE001 - an unreadable card is never treated as free
                profile, destination = None, ''
            if not profile or (profile['driver'], profile['tier']) != (FREE_DRIVER, FREE_TIER) or not local_url(destination):
                reasons.append(f"{shot}: card {step.get('card_id')} does not render on a local open-weights ComfyUI")
    return reasons


def estimate(saved, reasons) -> dict:
    allocations = saved['plan']['allocations']
    summary = saved['plan'].get('summary') or {}
    tiers = {}
    for allocation in allocations:
        tiers[allocation.get('tier')] = tiers.get(allocation.get('tier'), 0) + 1
    free = not reasons
    return {'free': free, 'costUsd': '0.00' if free else None,
            'billing': 'Local GPU time; nothing is billed.' if free else 'Not quoted here; a crew member reviews paid generation in ZeroField.',
            'shots': len(allocations), 'tiers': tiers,
            'estimatedLocalOutputSeconds': summary.get('estimated_local_output_seconds'),
            'estimatedCloudResourceUnits': summary.get('estimated_cloud_resource_units'),
            'basis': summary.get('estimate_basis')}


def _replay(conn, slug, account_key, request_id):
    with conn.cursor() as cur:
        cur.execute('''SELECT args_digest, result FROM projectops.agent_service_request
                       WHERE project_slug=%s AND account_key=%s AND tool_name='request_generation' AND request_id=%s''',
                    (slug, account_key, request_id))
        row = cur.fetchone()
    return {'args_digest': row[0], 'result': row[1]} if row else None


def _remember(conn, slug, account_key, request_id, digest, result):
    with conn.cursor() as cur:
        cur.execute('''INSERT INTO projectops.agent_service_request(project_slug, account_key, tool_name, request_id, args_digest, result)
                       VALUES(%s, %s, 'request_generation', %s, %s, %s::jsonb)''',
                    (slug, account_key, request_id, digest, json.dumps(result, ensure_ascii=False)))


def request_generation(ctx, conn, args):
    account = getattr(ctx, 'service_account', None)
    if not account or getattr(ctx, 'write_mode', None) != 'generate':
        raise Refusal('POLICY_DENIED', 'request_generation needs a service-account token with writeMode "generate". '
                                       'Crew members request renders through the reviewed Studio tools.')
    from project_assistant import orchestrator as cp
    from project_assistant.studio.runtime import WorkerError
    ep = _episode(ctx, conn, args['episode_id'])
    request = {'episode_id': ep['episodeId'], 'shot_ids': list(args['shot_ids']),
               'budget_mode': args.get('budget_mode', 'lab_economical'), 'app_code': args.get('app_code')}
    digest = cp.digest({**request, 'shot_ids': sorted(request['shot_ids'])})
    first = _replay(conn, ctx.slug, account['accountKey'], args['request_id'])
    if first:
        if first['args_digest'] != digest:
            raise Refusal('IDEMPOTENCY_CONFLICT', 'This request_id was already used with different arguments; send a new request_id.')
        return json.dumps({**first['result'], 'replayed': True}, ensure_ascii=False)
    try:
        plan = _plan(ctx, conn, ep, request)
        saved = _allocation(ctx, conn, plan['allocationId'])
    except WorkerError as exc:
        raise Refusal('NOT_READY', f'Not submitted: {exc}') from None
    reasons = spend_reasons(saved)
    cost = estimate(saved, reasons)
    if reasons:
        raise Refusal('NEEDS_HUMAN', 'Not submitted: this plan includes closed, hosted or paid generation, which an '
                      'external agent cannot start. Ask a crew member to review it in ZeroField. '
                      + json.dumps({'estimate': cost, 'reasons': reasons[:20]}, ensure_ascii=False))
    if not plan.get('ready'):
        blockers = sorted({b for a in saved['plan']['allocations'] for b in a.get('configuration_blockers') or []})
        raise Refusal('NOT_READY', 'Not submitted: the shots are not ready to render. '
                      + json.dumps({'blockers': blockers, 'estimate': cost}, ensure_ascii=False))
    try:
        group = _dispatch(ctx, conn, ep, request, plan['allocationId'])
    except WorkerError as exc:
        raise Refusal('NOT_READY', f'Not submitted: {exc}') from None
    result = {'status': 'submitted', 'requestId': args['request_id'], 'episodeId': ep['episodeId'],
              'shotIds': request['shot_ids'], 'allocationId': plan['allocationId'],
              'taskGroupId': group.get('taskGroupId'), 'taskIds': group.get('taskIds', []), 'estimate': cost,
              'reviewRequired': True, 'note': 'Takes arrive as candidates; a crew member reviews and adopts them.'}
    _remember(conn, ctx.slug, account['accountKey'], args['request_id'], digest, result)
    return json.dumps(result, ensure_ascii=False)


HANDLERS = tool_registry.handlers(__name__, globals())
