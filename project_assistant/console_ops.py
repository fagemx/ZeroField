"""Agent Console operations: GPU panel (SPEC_20 R38) and the project-wide queue (R39).

The GPU panel is read-only. It probes local endpoints only (127.0.0.1, localhost, ::1) with a
2 s timeout, no proxy and no redirects, the same rules as crew_readiness: ComfyUI /system_stats
and /queue, and Ollama /api/ps. Queue entries are counted, never returned, because a ComfyUI
queue carries whole workflows and prompts. No transaction is held while it probes.

The queue lists queued, running and failed chat turns, orchestration dispatches, pipeline tasks
and take grades, plus uncertain spend reservations. Other members' turns and sessions stay
private: they appear without their run, message or text, only as status and failure class.
"""
from __future__ import annotations

import datetime as dt
import http.client
import json
import re
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from project_assistant import agent_console_store as resources, orchestration_store as db
from project_assistant.providers import local_url

PROBE_SECONDS, MAX_BODY, CACHE_SECONDS = 2, 1024 * 1024, 3
DEFAULT_COMFY = 'http://127.0.0.1:8188'
QUEUE_LIMIT, ERROR_LIMIT, MAX_DAYS = 50, 300, 30
_LOCK = threading.Lock()
_CACHE = {}  # slug -> (monotonic, payload)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def local_json(url, *, body=None, timeout=None):
    """GET (or POST JSON) a loopback endpoint: no proxy, no redirects, bounded body.

    Returns ('ok', value), ('bad', None) when something other than the expected JSON answered,
    or ('down', None) when nothing answered. Never contacts a non-local host.
    """
    if not local_url(url):
        return 'not_local', None
    request = urllib.request.Request(url, headers={'Accept': 'application/json', **({'Content-Type': 'application/json'} if body is not None else {})},
                                     data=None if body is None else json.dumps(body).encode(), method='GET' if body is None else 'POST')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout or PROBE_SECONDS) as response:
            raw = response.read(MAX_BODY + 1)
    except urllib.error.HTTPError as exc:
        exc.close()
        return 'bad', None
    except http.client.HTTPException:
        return 'bad', None  # something that is not an HTTP JSON server answered
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return 'down', None
    if len(raw) > MAX_BODY:
        return 'bad', None
    try:
        return 'ok', json.loads(raw)
    except ValueError:
        return 'bad', None


def stamp(moment=None):
    moment = moment or dt.datetime.now(dt.timezone.utc)
    return moment.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _where(url):
    parts = urlsplit(url)
    return {'host': (parts.hostname or '').lower(), 'port': parts.port or (443 if parts.scheme == 'https' else 80)}


def api_root(base_url):
    return re.sub(r'/v1/?$', '', base_url.rstrip('/'))


def _int(value):
    return value if type(value) is int and value >= 0 else None


# ---------- GPU panel (R38) ----------

def gpu_owner(conn, comfy_url):
    """SLOT for the cross-process GPU arbiter (SPEC_20 R13, package W2b).

    Shows nothing until project_assistant.gpu_arbiter exists. After that merge the panel lights up
    when the module offers current_owner(conn, host_url) -> {'holder', 'purpose', 'since'} | None.
    Any failure or other shape keeps the slot empty; the panel never depends on it.
    """
    try:
        from project_assistant import gpu_arbiter  # noqa: F401 (W2b)
    except ImportError:
        return {'available': False, 'owner': None}
    probe = getattr(gpu_arbiter, 'current_owner', None)
    try:
        owner = probe(conn, comfy_url) if callable(probe) else None
    except Exception:
        owner = None
    if not isinstance(owner, dict):
        owner = None
    return {'available': callable(probe), 'owner': {k: owner.get(k) for k in ('holder', 'purpose', 'since')} if owner else None}


def _gpu_facts(conn, slug):
    from project_assistant import agent_registry, providers
    from project_assistant.agent_runtime import provider_for
    config = db.one(conn, "SELECT config FROM projectops.agent_environment WHERE project_slug=%s AND env_key='env_local_4090'", (slug,))
    comfy = ((config or {}).get('comfy_url') or DEFAULT_COMFY).rstrip('/')
    roots = {}
    for agent in agent_registry.list_agents(conn, slug):
        if agent['runtime_kind'] != 'builtin_llm' or not agent['enabled']:
            continue
        try:
            base = provider_for(agent_registry.effective_profile(conn, agent)).base_url
        except Exception:  # a revoked reference or removed kind is the readiness banner's business
            continue
        if local_url(base):
            roots.setdefault(api_root(base), None)
    if not roots:
        try:
            base = providers.provider_from_env().base_url
        except ValueError:
            base = providers.DEFAULT_BASE_URL
        if local_url(base):
            roots[api_root(base)] = None
    return {'comfy': comfy, 'roots': list(roots), 'owner': gpu_owner(conn, comfy)}


def _comfy(url):
    where = _where(url)
    if not local_url(url):
        return {**where, 'state': 'not_local'}
    state, stats = local_json(url + '/system_stats')
    if state != 'ok' or not isinstance(stats, dict) or not isinstance(stats.get('devices'), list):
        return {**where, 'state': 'down' if state == 'down' else 'bad'}
    devices = [{'name': str(d.get('name') or '')[:120], 'type': str(d.get('type') or '')[:20],
                'vramTotal': _int(d.get('vram_total')), 'vramFree': _int(d.get('vram_free')),
                'torchVramTotal': _int(d.get('torch_vram_total')), 'torchVramFree': _int(d.get('torch_vram_free'))}
               for d in stats['devices'][:8] if isinstance(d, dict)]
    system = stats.get('system') if isinstance(stats.get('system'), dict) else {}
    queue_state, queue = local_json(url + '/queue')
    counts = None
    if queue_state == 'ok' and isinstance(queue, dict):
        counts = {'running': len(queue.get('queue_running') or []), 'pending': len(queue.get('queue_pending') or [])}
    return {**where, 'state': 'ok', 'version': str(system.get('comfyui_version') or '')[:40] or None,
            'devices': devices, 'queue': counts}


def _ollama(root):
    where = _where(root)
    state, listing = local_json(root + '/api/ps')
    if state != 'ok' or not isinstance(listing, dict) or not isinstance(listing.get('models'), list):
        return {**where, 'state': 'down' if state == 'down' else 'bad', 'models': []}
    models = []
    for item in listing['models'][:16]:
        if not isinstance(item, dict):
            continue
        size, vram = _int(item.get('size')), _int(item.get('size_vram'))
        details = item.get('details') if isinstance(item.get('details'), dict) else {}
        models.append({'name': str(item.get('name') or item.get('model') or '')[:160], 'sizeBytes': size, 'vramBytes': vram,
                       'gpuShare': round(vram / size, 3) if size and vram is not None else None,
                       'contextLength': _int(item.get('context_length')), 'expiresAt': str(item.get('expires_at') or '')[:40] or None,
                       'parameterSize': str(details.get('parameter_size') or '')[:20] or None,
                       'quantization': str(details.get('quantization_level') or '')[:20] or None})
    return {**where, 'state': 'ok', 'models': models}


def gpu_panel(conn, me, slug):
    """Any production member. Ends the request's read transaction before it probes."""
    resources.authorize(conn, me, slug)
    with _LOCK:
        entry = _CACHE.get(slug)
        if entry and time.monotonic() - entry[0] < CACHE_SECONDS:
            return entry[1]
    facts = _gpu_facts(conn, slug)
    conn.rollback()  # no transaction, snapshot or lock is held during network probes
    payload = {'checkedAt': stamp(), 'comfy': _comfy(facts['comfy']), 'modelServers': [_ollama(root) for root in facts['roots']],
               'gpuOwner': facts['owner']}
    with _LOCK:
        _CACHE[slug] = (time.monotonic(), payload)
    return payload


def forget(slug=None):
    with _LOCK:
        if slug is None:
            _CACHE.clear()
        else:
            _CACHE.pop(slug, None)


# ---------- Queue and failures (R39) ----------

# name -> (row object, FROM/WHERE scoped to %(slug)s, status, active states, failed states, failure time, order)
QUEUES = {
    'turns': ("""jsonb_build_object('id',m.id,'agentKey',m.agent_key,'status',m.status,'attempts',m.attempts,'errorKind',m.error_kind,
                 'detail',CASE WHEN m.status='failed' AND m.error_kind='admission' THEN m.body END,
                 'createdAt',m.created_at,'finishedAt',m.finished_at,'mine',m.owner_id::text=%(mine)s)""",
              "projectops.assistant_message m WHERE m.project_slug=%(slug)s AND m.role='assistant'",
              'm.status', ('queued', 'running'), ('failed',), 'COALESCE(m.finished_at,m.created_at)', 'm.id DESC'),
    'dispatches': ("""jsonb_build_object('id',d.id,'agentKey',d.agent_key,'status',d.status,'attempt',d.attempt_no,'error',d.error,
                      'createdAt',d.created_at,'finishedAt',d.finished_at,'mine',r.created_by::text=%(mine)s,
                      'runId',CASE WHEN r.created_by::text=%(mine)s THEN r.id::text END)""",
                   """projectops.orchestration_dispatch d JOIN projectops.orchestration_run r ON r.id=d.run_id AND r.project_slug=d.project_slug
                      WHERE d.project_slug=%(slug)s AND d.superseded_by IS NULL""",
                   'd.status', ('queued', 'running', 'awaiting_gate'), ('failed', 'timeout'), 'COALESCE(d.finished_at,d.updated_at)', 'd.created_at DESC'),
    'tasks': ("""jsonb_build_object('id',t.id,'runId',t.run_id,'tabKey',r.tab_key,'nodeId',t.node_id,'rowId',t.row_id,
                 'capability',t.capability,'status',t.status,'attempts',t.attempts,'maxAttempts',t.max_attempts,'error',t.error,
                 'createdAt',t.created_at,'updatedAt',t.updated_at)""",
              "projectops.limb_task t JOIN projectops.flow_run r ON r.id=t.run_id WHERE t.project_slug=%(slug)s",
              't.status', ('queued', 'running'), ('failed',), 't.updated_at', 't.updated_at DESC'),
    'grades': ("""jsonb_build_object('id',g.id,'shotId',g.data->>'shotId','status',g.data->>'status','auto',(g.data->>'auto')::boolean,
                  'error',g.data->>'error','requestedAt',g.data->>'requestedAt','updatedAt',g.updated_at)""",
               "projectops.story_record g WHERE g.kind='take_grade' AND g.project_slug=%(slug)s",
               "g.data->>'status'", ('queued', 'waiting_gpu', 'grading'), ('failed',), 'g.updated_at', 'g.updated_at DESC'),
}


def _clip(text):
    text = (text or '').strip()
    return text if len(text) <= ERROR_LIMIT else text[:ERROR_LIMIT - 1] + '…'


def _states(values):
    return '(' + ','.join("'" + v + "'" for v in values) + ')'  # fixed identifiers above, never input


def queue(conn, me, slug, *, days=7):
    """Any member: queued/running/failed work across the production; failures from the last `days`."""
    member = resources.authorize(conn, me, slug)
    admin = me.can_edit and member['role'] == 'admin'
    resources.integer(days, 1, MAX_DAYS)
    params = {'slug': slug, 'mine': str(me.actor_id), 'since': f'{days} days', 'limit': QUEUE_LIMIT}
    result, counts = {}, {}
    for name, (row, source, status, active, failed, when, order) in QUEUES.items():
        recent = f'{status} IN {_states(failed)} AND {when}>NOW()-%(since)s::interval'
        counts[name] = db.one(conn, f"""SELECT jsonb_build_object('active',count(*) FILTER (WHERE {status} IN {_states(active)}),
            'failed',count(*) FILTER (WHERE {recent})) FROM {source}""", params)
        result[name] = {
            'active': db.many(conn, f'SELECT {row} FROM {source} AND {status} IN {_states(active)} ORDER BY {order} LIMIT %(limit)s', params),
            'failed': db.many(conn, f'SELECT {row} FROM {source} AND {recent} ORDER BY {order} LIMIT %(limit)s', params)}
        for item in result[name]['active'] + result[name]['failed']:
            for field in ('detail', 'error'):
                if field in item:
                    item[field] = _clip(item[field]) or None
    hold = resources.get_settings(conn, me, slug)['rate_limits']['uncertain_hold_seconds']
    uncertain = db.many(conn, """SELECT jsonb_build_object('requestKey',request_key,'agentKey',agent_key,'usageKind',usage_kind,
            'category',category,'provider',provider_name,'model',model_name,'tier',tier,'ceilingUsd',ceiling_cost_usd,
            'accountedUsd',accounted_cost_usd,'startedAt',COALESCE(started_at,created_at),
            'holdsSlot',COALESCE(started_at,created_at)>NOW()-%(hold)s*INTERVAL '1 second')
        FROM projectops.agent_usage_reservation WHERE project_slug=%(slug)s AND state='uncertain'
        ORDER BY COALESCE(started_at,created_at) DESC LIMIT %(limit)s""", {**params, 'hold': hold})
    counts['uncertain'] = db.one(conn, "SELECT count(*) FROM projectops.agent_usage_reservation WHERE project_slug=%s AND state='uncertain'", (slug,))
    from project_assistant.automation import state as automation_state
    return {'checkedAt': stamp(), 'days': days, 'canReconcile': admin, 'counts': counts, 'automation': automation_state(conn, slug),
            **result,
            # Reservation identities are for the showrunner who settles them; other members see the count.
            'uncertain': uncertain if admin else []}
