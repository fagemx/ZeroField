"""Crew readiness (SPEC_20 R2): can the built-in crew work, and what fixes it.

Only local model endpoints are probed: GET {base}/models with a 2 s timeout, no proxy and
no redirects, then the configured model is looked up in that list. Non-local endpoints are
reported by host only with reachable=None; a showrunner tests them in Agent Console. Keys,
URLs and provider replies never leave this module. Payloads are cached per production for
30 s and refresh forces a recheck at most once every 5 s. The roster reads the cache (or
remembered probes) and never probes.
"""
from __future__ import annotations

import datetime as dt
import http.client
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from types import SimpleNamespace
from urllib.parse import urlsplit

from project_assistant import agent_registry, orchestration_store as db, store

TTL, REFRESH_GAP, PROBE_SECONDS, PROBE_MEMORY, HEARTBEAT_SECONDS, HOLD_SECONDS = 30, 5, 2, 600, 90, 600
OLLAMA_PORT, MAX_LISTING = 11434, 1024 * 1024
CREW = tuple(row[0] for row in agent_registry.ROSTER)
# Blocker codes in the order a person should fix them, with the fix hints each may carry.
FIXES = {
    'worker_not_running': ('restart_without_no_worker',),
    'provider_unreachable': ('start_ollama', 'start_model_server', 'check_endpoint'),
    'model_missing': ('ollama_pull', 'load_model'),
    'kind_removed': ('reconfigure_provider',),
    'cli_blocked': ('use_builtin_provider',),
    'auth_missing': ('set_api_key', 'configure_provider'),
    'network_policy': ('enable_environment', 'allow_host', 'keep_local'),
    'pricing_missing': ('set_model_pricing',),
    'agent_disabled': ('enable_agent',),
    'reservations_stuck': ('reconcile_reservations',),
}
ORDER = {code: n for n, code in enumerate(FIXES)}
_LOCK = threading.Lock()
_CACHE, _FORCED, _PROBES = {}, {}, {}  # slug -> (at, probed, payload); slug -> at; base -> (at, state, ids)
_clock = time.monotonic


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _open(request, timeout):
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect()).open(request, timeout=timeout)


def readiness(conn, me, slug, *, refresh=False):
    """Any production member. Ends the request's read transaction before it probes."""
    from project_assistant.agent_console_store import authorize
    authorize(conn, me, slug)
    with _LOCK:
        now, entry = _clock(), _CACHE.get(slug)
        forced = refresh and now - _FORCED.get(slug, float('-inf')) >= REFRESH_GAP
        if forced:
            _FORCED[slug] = now
        if entry and entry[1] and now - entry[0] < TTL and not forced:
            return entry[2]
    facts = _facts(conn, slug)
    conn.rollback()  # no transaction, snapshot or lock is held during network probes
    payload = _assemble(facts, {base: _probe(base) for base in facts['endpoints']})
    with _LOCK:
        _CACHE[slug] = (_clock(), True, payload)
    return payload


def cached(conn, slug):
    """Roster view: the last payload while fresh, else one built from remembered probes."""
    with _LOCK:
        now, entry = _clock(), _CACHE.get(slug)
        if entry and now - entry[0] < TTL:
            return entry[2]
    facts = _facts(conn, slug)
    payload = _assemble(facts, {base: _recall(base, now) for base in facts['endpoints']})
    with _LOCK:
        entry = _CACHE.get(slug)
        if not entry or _clock() - entry[0] >= TTL:
            _CACHE[slug] = (now, False, payload)
    return payload


def blocks(payload, agent):
    """Blockers that stop this roster agent; production-wide ones stop enabled built-in agents."""
    builtin = agent.get('runtime_kind') == 'builtin_llm' and agent.get('enabled')
    return [b for b in payload['blockers'] if b['agentKey'] == agent['agent_key'] or (b['agentKey'] is None and builtin)]


def forget(slug=None):
    with _LOCK:
        if slug is None:
            _CACHE.clear()
            _FORCED.clear()
            _PROBES.clear()
        else:
            _CACHE.pop(slug, None)
            _FORCED.pop(slug, None)


def _blocker(code, agent_key, fix=None, **detail):
    fix = fix or FIXES[code][0]
    if fix not in FIXES[code]:
        raise ValueError('Unknown readiness fix.')
    return {'code': code, 'agentKey': agent_key, 'fix': fix, **detail}


def _stamp(moment):
    return moment.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _removed(exc):
    return getattr(exc, 'code', None) == 'kind_removed' or bool(re.search(r'\bresponses\b', str(exc), re.I))


def _retired(profile):
    """The removed ChatGPT 'responses' transport (or its 'direct' alias), stored or deployment-wide."""
    kind = (profile.get('provider_config') or {}).get('kind') or (
        os.environ.get('OPENBENCH_PROVIDER') or os.environ.get('PROJECT_ASSISTANT_ENGINE') or '')
    return kind.strip().lower() in ('responses', 'direct')


def _denied(environment, host):
    # Mirrors agent_console_store.execution_resources, which needs a writer; readiness is for every member.
    access = environment['network_access']
    return access == 'offline' or (access == 'restricted' and host not in ('localhost', '127.0.0.1', '::1')) or (
        access == 'allowlist' and host not in [h.lower() for h in environment['allowed_hosts']])


def _facts(conn, slug):
    """Database half of the check: everything except the network probes."""
    from project_assistant import execution_governance as governance, orchestrator as cp, privacy, tools
    from project_assistant.agent_runtime import provider_for
    seen = store.get_setting(conn, slug, 'builtin_worker_seen_at')
    try:
        seen = cp.instant(seen) if seen else None
    except agent_registry.AgentError:
        seen = None
    running = bool(seen and seen > cp.now() - dt.timedelta(seconds=HEARTBEAT_SECONDS))
    settings = db.one(conn, 'SELECT to_jsonb(s) FROM projectops.agent_console_settings s WHERE project_slug=%s', (slug,)) or {}
    limits = settings.get('rate_limits') or {}
    hold = limits.get('uncertain_hold_seconds', HOLD_SECONDS)
    minutes = max(1, -(-hold // 60))
    # Calls with unknown results occupy admission slots until the hold expires (SPEC_20 R1).
    held = ("project_slug=%s AND (state='uncertain' OR (state='dispatched' AND lease_until<=NOW())) "
            "AND COALESCE(started_at,created_at)>NOW()-%s*INTERVAL '1 second'")
    stuck = db.one(conn, "SELECT COALESCE(jsonb_object_agg(agent_key,n),'{}'::jsonb) FROM (SELECT agent_key,count(*) n "
                         "FROM projectops.agent_usage_reservation WHERE " + held + " GROUP BY agent_key) s", (slug, hold))
    stuck_llm = db.one(conn, "SELECT count(*) FROM projectops.agent_usage_reservation WHERE category='llm' AND " + held, (slug, hold))
    environments = {e['env_key']: e for e in db.many(conn, 'SELECT to_jsonb(e) FROM projectops.agent_environment e WHERE project_slug=%s', (slug,))}
    masked = privacy.mode(conn, slug) == 'mask_numbers'
    blockers, providers, checks = [], {}, []
    if not running:
        blockers.append(_blocker('worker_not_running', None))
    crowded = stuck_llm >= limits.get('max_concurrent_llm', 4)
    if crowded:
        blockers.append(_blocker('reservations_stuck', None, count=stuck_llm, minutes=minutes))
    for agent in agent_registry.list_agents(conn, slug):
        key = agent['agent_key']
        if not agent['enabled']:
            if key in CREW:
                blockers.append(_blocker('agent_disabled', key))
            continue
        if not crowded and stuck.get(key, 0) >= agent['max_concurrency']:
            blockers.append(_blocker('reservations_stuck', key, count=stuck[key], minutes=minutes))
        if agent['runtime_kind'] != 'builtin_llm' or agent['role_kind'] == 'observer':
            continue
        try:
            effective = agent_registry.effective_profile(conn, agent)
            if _retired(effective):
                blockers.append(_blocker('kind_removed', key))
                continue
            config = provider_for(effective)
            url = urlsplit(config.base_url)
            host, port = (url.hostname or '').lower(), url.port or (443 if url.scheme == 'https' else 80)
        except (ValueError, TypeError, KeyError, tools.ToolError) as exc:  # revoked reference or credential, removed kind
            blockers.append(_blocker('kind_removed', key) if _removed(exc) else _blocker('auth_missing', key, 'configure_provider'))
            continue
        if config.kind in ('codex_cli', 'codex'):
            blockers.append(_blocker('cli_blocked', key))
            continue
        if config.kind != 'openai_compat':  # any other retired transport is reported, never contacted
            blockers.append(_blocker('kind_removed', key))
            continue
        if not host or url.scheme not in ('http', 'https'):
            blockers.append(_blocker('auth_missing', key, 'configure_provider'))
            continue
        local = governance.local_url(config.base_url)
        environment = environments.get(agent['default_environment_key'])
        policy = (_blocker('network_policy', key, 'enable_environment') if not environment or not environment['enabled'] else
                  _blocker('network_policy', key, 'allow_host', host=host) if _denied(environment, host) else
                  _blocker('network_policy', key, 'keep_local', host=host) if masked and not local else None)
        if policy:
            blockers.append(policy)
        else:
            try:
                governance.credential_binding(conn, SimpleNamespace(slug=slug), effective, config, environment)
            except ValueError:
                blockers.append(_blocker('auth_missing', key, 'configure_provider'))
        if not local:
            if not config.api_key:
                blockers.append(_blocker('auth_missing', key, 'set_api_key', host=host))
            try:
                ceiling = governance.price_bound(settings, config, {})[0]
            except (ValueError, KeyError, TypeError):
                ceiling = None
            if ceiling is None:
                blockers.append(_blocker('pricing_missing', key, model=config.model, host=host))
        ident = (local, host, port if local else None, config.model)
        entry = providers.setdefault(ident, {'model': config.model, 'destination': 'local' if local else 'remote', 'host': host,
            **({'port': port} if local else {}), 'tier': 'local_open' if local else 'closed',  # R9 splits hosted_open from closed
            'reachable': None, 'modelPresent': None, 'agents': []})
        entry['agents'].append(key)
        if local and not policy:
            checks.append((config.base_url.rstrip('/'), key, ident))
    return {'worker': {'running': running, 'lastSeenAt': _stamp(seen) if seen else None}, 'blockers': blockers,
            'providers': providers, 'checks': checks, 'endpoints': sorted({c[0] for c in checks})}


def _assemble(facts, probes):
    blockers = list(facts['blockers'])
    providers = {ident: dict(entry, agents=list(entry['agents'])) for ident, entry in facts['providers'].items()}
    for base, key, ident in facts['checks']:
        entry, result = providers[ident], probes.get(base)
        if result is None:  # nothing known without a probe, so nothing to block on
            continue
        state, ids = result
        present = _listed(entry['model'], ids) if state == 'ok' and ids is not None else None
        entry.update(reachable=state == 'ok', modelPresent=present)
        ollama = entry['port'] == OLLAMA_PORT or ':' in entry['model']
        if state == 'down':
            blockers.append(_blocker('provider_unreachable', key, 'start_ollama' if ollama else 'start_model_server', host=entry['host'], port=entry['port']))
        elif state == 'bad':
            blockers.append(_blocker('provider_unreachable', key, 'check_endpoint', host=entry['host'], port=entry['port']))
        elif present is False:
            blockers.append(_blocker('model_missing', key, 'ollama_pull' if ollama else 'load_model', model=entry['model']))
    blockers.sort(key=lambda b: ORDER[b['code']])
    return {'ready': not blockers, 'checkedAt': _stamp(dt.datetime.now(dt.timezone.utc)), 'worker': facts['worker'],
            'providers': list(providers.values()), 'blockers': blockers}


def _listed(model, ids):
    tagged = lambda name: name if ':' in name else name + ':latest'  # Ollama lists untagged pulls as :latest
    return tagged(model) in {tagged(name) for name in ids}


def _probe(base):
    """('ok', ids|None) when the model API answered, 'bad' when something else did, 'down' when nothing did."""
    try:
        with _open(urllib.request.Request(base + '/models', headers={'Accept': 'application/json'}), PROBE_SECONDS) as response:
            raw = response.read(MAX_LISTING + 1)
    except urllib.error.HTTPError as exc:
        exc.close()
        result = ('ok', None) if exc.code in (401, 403) else ('bad', None)  # up, but the list needs a key
    except http.client.HTTPException:
        result = ('bad', None)  # something that is not an HTTP model server answered
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        result = ('down', None)
    else:
        try:
            listing = json.loads(raw) if len(raw) <= MAX_LISTING else None
            ids = {m['id'] for m in listing['data'] if isinstance(m, dict) and isinstance(m.get('id'), str)} \
                if isinstance(listing, dict) and isinstance(listing.get('data'), list) else None
        except ValueError:
            ids = None
        result = ('ok', ids) if ids is not None else ('bad', None)
    with _LOCK:
        _PROBES[base] = (_clock(), *result)
    return result


def _recall(base, now):
    with _LOCK:
        known = _PROBES.get(base)
    return known[1:] if known and now - known[0] < PROBE_MEMORY else None
