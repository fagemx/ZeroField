"""Role x model matrix and the hosted open-weights switch for the Agent Console (SPEC_20 R37). Showrunner only.

The matrix has one row per built-in crew role and custom agent that runs a language model. Each row shows
the model it resolves to, the model's usage tier (local open weights, hosted open weights, closed), what the
model can do (tools, JSON schema, vision, context, from the provider catalog), and whether the crew can use
it right now (the crew_readiness blockers for that agent).

Choices for a change come from two places and nowhere else:
  * the live `/models` listing of every local endpoint (127.0.0.1, localhost, ::1), probed with the same
    2 s, no-proxy, no-redirect rules as crew_readiness; and
  * the provider catalog presets the effective production policy offers (closed presets only under
    hybrid_studio). A non-local endpoint is never contacted: catalog entries are all it gets.
Every choice says why it cannot be used: the usage tier is not allowed (`hosted_open_disabled`,
`closed_needs_hybrid`), the model has no price ceiling (`pricing_missing`) or its key reference is not on
the deployment allowlist (`key_not_allowed`).

A change goes through agent_registry.save_agent, so the existing validation, version check and audit apply,
after the same policy, price and allowlist checks the matrix shows. `provider_policy.hosted_open_enabled` is
saved through resources.save_settings with the settings version. Nothing here stores or returns a key; a
non-local endpoint is reported by host only.
"""
from __future__ import annotations

import os
import re
import threading
import time
from types import SimpleNamespace

from project_assistant import agent_console_store as resources, agent_registry, crew_readiness
from project_assistant import execution_governance as governance, provider_catalog, tools
from project_assistant.console_model_check import describe
from project_assistant.console_ops import stamp
from project_assistant.providers import ProviderConfig, local_url
from project_docs import repository as repo

LISTING_SECONDS, MAX_LISTED, MAX_ENDPOINTS = 10, 100, 6
MODEL_ID = re.compile(r'[a-zA-Z0-9_.:/-]{1,160}')
DENIAL_TEXT = {**provider_catalog.DENIALS,
               'pricing_missing': 'Needs You: this model has no price ceiling. The showrunner sets one in Agent Console, Spend & Rate Limits.',
               'key_not_allowed': 'Needs You: the deployment does not allow this model\'s API key variable (OPENBENCH_AGENT_KEY_ENVS).'}
_LOCK = threading.Lock()
_LISTINGS = {}  # base url -> (monotonic time, state, sorted model ids | None)
_clock = time.monotonic


def forget():
    with _LOCK:
        _LISTINGS.clear()


# ---------- facts ----------

def _allowlist():
    return {n.strip() for n in os.environ.get('OPENBENCH_AGENT_KEY_ENVS', '').split(',') if n.strip()}


def _production(conn, slug):
    from project_docs import story_openapi as story
    try:
        return story.production_policy(conn, slug)  # includes the OPENBENCH_PRODUCTION_POLICY ceiling
    except Exception:  # an invalid deployment policy blocks like the strictest one
        return 'open_weights_only'


def _hosted(settings):
    return ((settings or {}).get('provider_policy') or {}).get('hosted_open_enabled') is True


def _policy(production, settings):
    hybrid = production == 'hybrid_studio'
    return {'production': production, 'hybrid': hybrid, 'hostedOpenEnabled': _hosted(settings),
            'settingsVersion': (settings or {}).get('version', 0),
            'closedHidden': 0 if hybrid else sum(1 for e in provider_catalog.catalog()['entries'] if e.tier == 'closed')}


def _models(conn, slug):
    """Crew roles and custom agents that run a language model, roster order first."""
    rows = [a for a in agent_registry.list_agents(conn, slug) if a['runtime_kind'] == 'builtin_llm' and a['role_kind'] != 'observer']
    order = {key: n for n, key in enumerate(crew_readiness.CREW)}
    return sorted(rows, key=lambda a: order.get(a['agent_key'], len(order)))


def _denials(entry, config, settings, production, *, api_key_env=None, check_key=False):
    """Why this model cannot be used now, in the order a person fixes it; [] when nothing stops it."""
    reasons = []
    tier = provider_catalog.denial(entry.tier, production, hosted_open_enabled=_hosted(settings))
    if tier:
        reasons.append(tier)
    if not local_url(config.base_url):
        if check_key and api_key_env not in _allowlist():
            reasons.append('key_not_allowed')
        try:
            ceiling = governance.price_bound(settings or {}, config, {})[0]
        except Exception:  # a price entry bound to another endpoint is no ceiling for this one
            ceiling = None
        if ceiling is None:
            reasons.append('pricing_missing')
    return reasons


def _model_view(entry, config):
    where = describe(config)
    return {'model': config.model, 'label': entry.label if entry.matched else None, 'catalogId': entry.id if entry.matched else None,
            'local': where['local'], 'host': where['host'], 'port': where['port'], 'baseUrl': where['baseUrl'], 'tier': entry.tier,
            'capabilities': {name: entry.can(name) for name in provider_catalog.CAPABILITIES}, 'assumed': not entry.matched,
            'contextTokens': entry.context_tokens}


def _listed(model, ids):
    tagged = lambda name: name if ':' in name else name + ':latest'  # Ollama lists untagged pulls as :latest
    return tagged(model) in {tagged(name) for name in ids}


def _listing(base, *, refresh=False):
    """('ok', ids|None) | ('bad', None) | ('down', None) for a loopback endpoint's /models; never a remote host."""
    if not local_url(base):
        raise ValueError('Only local endpoints are probed.')
    with _LOCK:
        known = _LISTINGS.get(base)
        if known and not refresh and _clock() - known[0] < LISTING_SECONDS:
            return known[1], known[2]
    state, ids = crew_readiness._probe(base)  # same probe as the readiness check; it refreshes the roster's memory too
    ids = sorted(ids)[:MAX_LISTED] if ids is not None else None
    with _LOCK:
        _LISTINGS[base] = (_clock(), state, ids)
    return state, ids


# ---------- the matrix ----------

def _row(conn, agent, settings, production):
    """One matrix row, plus the resolved provider configuration the caller needs for endpoints."""
    from project_assistant.agent_runtime import provider_for
    key = agent['agent_key']
    row = {'agentKey': key, 'displayName': agent['display_name'], 'custom': key not in crew_readiness.CREW,
           'enabled': agent['enabled'], 'version': agent['version'], 'inherits': agent['provider_config'] == {},
           'state': 'ok', 'current': None, 'denials': []}
    config = None
    try:
        config = provider_for(agent_registry.effective_profile(conn, agent))
    except agent_registry.AgentError as exc:
        row['state'] = 'kind_removed' if exc.code == 'kind_removed' else 'configuration_required'
    except (ValueError, tools.ToolError):
        row['state'] = 'configuration_required'
    else:
        if config.kind != 'openai_compat':
            row['state'] = 'kind_removed' if config.kind in ('responses', 'direct') else 'unsupported_kind'
            config = None
        else:
            entry = provider_catalog.match(config)
            row['current'] = _model_view(entry, config)
            row['denials'] = _denials(entry, config, settings, production)
    return row, config


def _readiness(row, agent, payload):
    """The roster's readiness for this agent: ready, blocked (with the blockers), untested, or off."""
    key = row['agentKey']
    blockers = [b for b in payload['blockers'] if b['agentKey'] == key]
    known = next((p for p in payload['providers'] if key in p['agents']), None)
    if not agent['enabled']:
        state = 'off'
    elif blockers:
        state = 'blocked'
    elif known and known['reachable'] is True and known['modelPresent'] is True:
        state = 'ready'
    else:
        state = 'untested'  # a hosted endpoint is never probed here; the health check tests it
    return {'state': state, 'blockers': blockers, 'reachable': known['reachable'] if known else None,
            'modelPresent': known['modelPresent'] if known else None}


def _choices(bases, settings, production, listings):
    """Every model an admin may pick: what each local endpoint lists now, plus the catalog presets the policy offers."""
    keys, out = set(), []

    def add(entry, config, *, source, listed):
        ident = (config.base_url.rstrip('/'), config.model)
        if ident in keys:
            return
        keys.add(ident)
        view = _model_view(entry, config)
        denials = _denials(entry, config, settings, production, api_key_env=entry.api_key_env, check_key=not view['local'])
        out.append({**view, 'key': (view['catalogId'] or '') + '|' + config.base_url.rstrip('/') + '|' + config.model, 'source': source,
                    'listed': listed, 'denials': denials, 'allowed': not denials, 'apiKeyEnv': entry.api_key_env if not view['local'] else None,
                    'keyConfigured': bool(entry.api_key_env and os.environ.get(entry.api_key_env)) if not view['local'] else None})

    for base in bases:
        state, ids = listings[base]
        for model in ids or []:
            config = SimpleNamespace(kind='openai_compat', base_url=base, model=model)
            add(provider_catalog.match(config), ProviderConfig('openai_compat', base, '', model), source='listing', listed=True)
    for entry in provider_catalog.entries(production):
        base = entry.base_url.rstrip('/')
        listed = None
        if local_url(base):
            state, ids = listings.get(base, ('down', None))
            listed = _listed(entry.model, ids) if state == 'ok' and ids is not None else None
            if listed:
                continue  # already offered by name from the live listing
        add(entry, ProviderConfig('openai_compat', base, '', entry.model), source='catalog', listed=listed)
    return out


def _endpoint(base, state, ids):
    where = describe(SimpleNamespace(kind='openai_compat', base_url=base, model=''))
    # 'ok' with no list means the server answered but wants a key before it lists its models.
    return {'baseUrl': base, 'host': where['host'], 'port': where['port'], 'state': state if state != 'ok' or ids is not None else 'unlisted',
            'count': len(ids or [])}


def matrix(conn, me, slug, *, refresh=False):
    """Showrunner only. Ends the request's read transaction before it probes, like crew_readiness."""
    resources.authorize(conn, me, slug, admin=True)
    settings = resources.get_settings(conn, me, slug) or {}
    production = _production(conn, slug)
    agents = _models(conn, slug)
    built = [_row(conn, agent, settings, production) for agent in agents]
    conn.rollback()
    payload = crew_readiness.readiness(conn, me, slug, refresh=refresh)
    bases = []
    for base in [config.base_url.rstrip('/') for _, config in built if config] + [e.base_url.rstrip('/') for e in provider_catalog.entries(production)]:
        if local_url(base) and base not in bases:
            bases.append(base)
    bases = bases[:MAX_ENDPOINTS]
    listings = {base: _listing(base, refresh=refresh) for base in bases}
    rows = [{**row, 'readiness': _readiness(row, agent, payload)} for (row, _), agent in zip(built, agents)]
    return {'checkedAt': stamp(), 'policy': _policy(production, settings), 'rows': rows,
            'choices': _choices(bases, settings, production, listings),
            'endpoints': [_endpoint(base, *listings[base]) for base in bases]}


# ---------- changes ----------

def _fields(body, allowed, required):
    from project_assistant.agent_console_service import fields
    return fields(body, allowed, required)


def _config_for(production, settings, body):
    """The provider configuration a change request asks for, or AgentError saying why it cannot be had."""
    modes = [n for n in ('inherit', 'catalog_id', 'model') if n in body]
    if len(modes) != 1 or ('base_url' in body) != ('model' in body):
        resources.bad('Choose exactly one model: inherit, a catalog_id, or a local base_url with a model.')
    if 'inherit' in body:
        if body['inherit'] is not True:
            resources.bad('inherit must be true.')
        return {}, None
    if 'catalog_id' in body:
        found = [e for e in provider_catalog.catalog()['entries'] if e.id == body['catalog_id']]
        if not isinstance(body['catalog_id'], str) or not found:
            resources.bad('Unknown catalog model.')
        entry = found[0]
        if entry not in provider_catalog.entries(production):
            raise agent_registry.AgentError(409, DENIAL_TEXT['closed_needs_hybrid'], 'closed_needs_hybrid')
        config = {'kind': 'openai_compat', 'base_url': entry.base_url, 'model': entry.model}
        if entry.api_key_env and not local_url(entry.base_url):
            config['api_key_env'] = entry.api_key_env
        return config, entry
    if not isinstance(body['base_url'], str) or not isinstance(body['model'], str) or not MODEL_ID.fullmatch(body['model']):
        resources.bad('Invalid model name or endpoint.')
    if not local_url(body['base_url']):
        raise agent_registry.AgentError(400, 'Only local endpoints take a model by name; choose a hosted model from the catalog.', 'not_in_catalog')
    config = {'kind': 'openai_compat', 'base_url': body['base_url'].rstrip('/'), 'model': body['model']}
    return config, provider_catalog.match(SimpleNamespace(**config))


def apply(conn, me, slug, body):
    """Point one role at a model. Policy, price and key checks first; then the ordinary agent save."""
    resources.authorize(conn, me, slug, admin=True)
    _fields(body, {'agent_key', 'version', 'inherit', 'catalog_id', 'base_url', 'model'}, {'agent_key', 'version'})
    agent = agent_registry.get_agent(conn, slug, resources.key(body['agent_key']), effective=False)
    if not agent or agent['runtime_kind'] != 'builtin_llm' or agent['role_kind'] == 'observer':
        raise agent_registry.AgentError(404, 'Model-driven agent not found.')
    settings = resources.get_settings(conn, me, slug) or {}
    production = _production(conn, slug)
    config, entry = _config_for(production, settings, {k: v for k, v in body.items() if k not in ('agent_key', 'version')})
    if entry is not None:
        probe = ProviderConfig('openai_compat', config['base_url'], '', config['model'])
        reasons = _denials(entry, probe, settings, production, api_key_env=config.get('api_key_env'), check_key=not local_url(probe.base_url))
        if reasons:
            raise agent_registry.AgentError(409, DENIAL_TEXT[reasons[0]], reasons[0])
    saved = agent_registry.save_agent(conn, me, slug, {'agent_key': agent['agent_key'], 'version': body['version'], 'provider_config': config})
    if entry is not None:
        repo.add_audit(conn, slug, action='console_agent_model', actor_id=me.actor_id, target=agent['agent_key'],
                       detail={'tier': entry.tier, 'model': config['model'], 'host': describe(ProviderConfig('openai_compat', config['base_url'], '', config['model']))['host']})
    crew_readiness.forget(slug)
    return {'agent': {'agentKey': saved['agent_key'], 'version': saved['version'], 'inherits': saved['provider_config'] == {}}}


def set_hosted_open(conn, me, slug, body):
    """The showrunner's switch for provider_policy.hosted_open_enabled; the settings version guards against a stale page."""
    resources.authorize(conn, me, slug, admin=True)
    _fields(body, {'hosted_open_enabled', 'version'}, {'hosted_open_enabled', 'version'})
    if type(body['hosted_open_enabled']) is not bool:
        resources.bad('hosted_open_enabled must be true or false.')
    settings = resources.save_settings(conn, me, slug, {'version': body['version'], 'provider_policy': {'hosted_open_enabled': body['hosted_open_enabled']}})
    repo.add_audit(conn, slug, action='console_hosted_open', actor_id=me.actor_id, target=slug,
                   detail={'hosted_open_enabled': body['hosted_open_enabled']})
    crew_readiness.forget(slug)
    return {'policy': _policy(_production(conn, slug), settings)}
