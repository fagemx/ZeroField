"""Project-scoped Console resources. Callers own short transactions/commit.

save_resource/save_settings/save_memory_entry use version=0 for creation and the
last read version for updates (409 on conflict). history returns immutable SQL
snapshots. All identity-taking helpers recheck live membership; admin authority
never expands user memory scope. No helper performs inference or networking.
"""
from __future__ import annotations

import json
import re
import uuid
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from project_assistant import orchestration_store as db
from project_assistant.agent_registry import AgentError, AGENT_KEY, validate_provider
from project_docs import repository as repo

# New tools are validated before their registration by the next component owner.
STUDIO_TOOLS = {'studio_ingest_script', 'studio_manage_asset', 'studio_plan_allocation',
                'studio_dispatch_shot', 'studio_inspect_frames', 'studio_edit_timeline', 'consult_advisor'}
RESOURCES = {
    'skill': ('agent_skill', 'skill_key', {'display_name', 'category', 'summary', 'instructions_md', 'recommended_tools', 'enabled'}),
    'environment': ('agent_environment', 'env_key', {'display_name', 'env_kind', 'config', 'network_access', 'allowed_hosts', 'packages', 'enabled'}),
    'memory_store': ('agent_memory_store', 'store_key', {'display_name', 'scope_kind', 'scope_id', 'description'}),
    'vault': ('agent_vault_reference', 'vault_key', {'display_name', 'provider_config', 'allowed_agent_keys', 'enabled'}),
    'service_account': ('agent_service_account', 'account_key', {'display_name', 'limb_id', 'enabled'}),
}
JSON_FIELDS = {'recommended_tools', 'config', 'allowed_hosts', 'packages', 'provider_config', 'allowed_agent_keys',
               'tags', 'rate_limits', 'retention_policy', 'otel_config', 'webhooks'}
DEFAULTS = {
    'skill': dict(category='custom', summary='', instructions_md='', recommended_tools=[], enabled=True),
    'environment': dict(env_kind='local_sandbox', config={}, network_access='restricted', allowed_hosts=[], packages=[], enabled=True),
    'memory_store': dict(scope_kind='project', scope_id='', description=''),
    'vault': dict(provider_config={}, allowed_agent_keys=[], enabled=True),
    'service_account': dict(enabled=True),
}
SETTINGS = {
    'spend_limit_monthly_usd': 100, 'spend_limit_session_usd': 5, 'spend_limit_episode_usd': 15,
    'on_spend_limit': 'downgrade_open_weights',
    'rate_limits': {'rpm_per_agent': 30, 'max_concurrent_renders': 2, 'max_concurrent_llm': 4},
    'retention_policy': {'session_logs_days': 90, 'temp_media_days': 14, 'zero_data_retention_notice': True},
    'otel_config': {'enabled': False, 'endpoint': '', 'service_name': 'zerofield-studio'}, 'webhooks': [],
}


def bad(message='Invalid Console resource.'):
    raise AgentError(400, message)


def key(value):
    if not isinstance(value, str) or not AGENT_KEY.fullmatch(value):
        bad('Invalid or reserved resource key.')
    return value


def text(value, maximum, *, required=False):
    if not isinstance(value, str) or len(value) > maximum or '\x00' in value or (required and not value.strip()):
        bad('Invalid text format or length.')
    return value


def integer(value, low=0, high=1000000000):
    if type(value) is not int or not low <= value <= high:
        bad('Counter is outside its permitted range.')
    return value


def money(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)) or (isinstance(value, str) and len(value) > 64):
        bad('Money must be a finite nonnegative amount.')
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        bad('Money must be a finite nonnegative amount.')
    if not amount.is_finite() or not 0 <= amount < 1000000 or amount.as_tuple().exponent < -4:
        bad('Money must be finite, nonnegative, below 1000000 and at most four decimal places.')
    return amount


def strings(value, maximum=64, *, check=None):
    if not isinstance(value, list) or len(value) > maximum or any(not isinstance(v, str) or len(v) > 160 for v in value):
        bad('Expected a bounded string list.')
    if len(set(value)) != len(value):
        bad('Duplicate list entries are not permitted.')
    for v in value:
        if check:
            check(v)
    return value


def tools(value):
    from project_assistant.tool_specs import TOOL_NAMES
    strings(value, 128)
    if any(v not in TOOL_NAMES | STUDIO_TOOLS for v in value):
        bad('Unknown product tool.')


def endpoint(value):
    text(value, 2000, required=True)
    if any(c.isspace() or ord(c) < 32 for c in value):
        bad('Endpoints cannot contain whitespace or control characters.')
    try:
        url = urlsplit(value)
        url.port
    except ValueError:
        bad('Invalid endpoint.')
    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
        bad('Endpoints must be HTTP(S) URLs without credentials, queries or fragments.')
    return value


def authorize(conn, me, slug, *, write=False, admin=False):
    from project_assistant import orchestrator as cp
    member = cp.actor(conn, slug, me, write=write or admin)
    if admin and (not me.can_edit or member['role'] != 'admin'):
        raise AgentError(403, 'Only the showrunner can configure Console resources.')
    return member


def _lock(conn, slug):
    from project_assistant.orchestrator import lock_project
    lock_project(conn, slug)


def _spec(kind):
    if kind not in RESOURCES:
        bad('Unknown resource kind.')
    return RESOURCES[kind]


def _get(conn, kind, slug, resource_key):
    table, column, _ = _spec(kind)
    return db.one(conn, f'SELECT to_jsonb(r) FROM projectops.{table} r WHERE project_slug=%s AND {column}=%s', (slug, key(resource_key)))


def authorize_scope(conn, me, slug, store, *, episode_id=None, write=False):
    authorize(conn, me, slug, write=write)
    scope, scope_id = store['scope_kind'], store['scope_id']
    if scope == 'user' and scope_id != str(me.actor_id):
        raise AgentError(404, 'Memory store not found.')
    if scope == 'episode':
        if episode_id != scope_id:
            raise AgentError(404, 'Memory store not found in this episode.')
        _episode(conn, slug, scope_id)
    return store


def _episode(conn, slug, identifier):
    from project_docs import story_openapi as story
    text(identifier, 160, required=True)
    try:
        ep = story.episode(conn, identifier)
    except story.StoryError:
        bad('Episode is not accessible in this production.')
    if ep['slug'] != slug:
        bad('Episode is not accessible in this production.')
    return ep


def get_resource(conn, me, slug, kind, resource_key, *, episode_id=None):
    authorize(conn, me, slug)
    found = _get(conn, kind, slug, resource_key)
    if found and kind == 'memory_store':
        authorize_scope(conn, me, slug, found, episode_id=episode_id)
    return found


def list_resources(conn, me, slug, kind, *, episode_id=None):
    authorize(conn, me, slug)
    table, column, _ = _spec(kind)
    rows = db.many(conn, f'SELECT to_jsonb(r) FROM projectops.{table} r WHERE project_slug=%s ORDER BY {column} LIMIT 500', (slug,))
    if kind == 'memory_store':
        rows = [r for r in rows if r['scope_kind'] == 'project' or
                (r['scope_kind'] == 'user' and r['scope_id'] == str(me.actor_id)) or
                (r['scope_kind'] == 'episode' and r['scope_id'] == episode_id)]
        for row in rows:
            authorize_scope(conn, me, slug, row, episode_id=episode_id)
    return rows


def _validate(conn, me, slug, kind, value):
    text(value['display_name'], 120, required=True)
    if 'enabled' in value and type(value['enabled']) is not bool:
        bad('enabled must be boolean.')
    if kind == 'skill':
        if value['category'] not in ('cinema', 'document', 'data', 'custom'):
            bad('Invalid skill category.')
        text(value['summary'], 2000)
        text(value['instructions_md'], 30000)
        tools(value['recommended_tools'])
    elif kind == 'environment':
        if value['env_kind'] not in ('local_sandbox', 'hybrid_cloud', 'acp_cli', 'remote_worker') or value['network_access'] not in ('offline', 'restricted', 'allowlist', 'full'):
            bad('Invalid environment kind or network policy.')
        def host(v):
            if not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9.-]{0,251}[a-zA-Z0-9])?', v):
                bad('Hosts must be exact DNS names or IPv4 addresses, not URLs or wildcard patterns.')
        strings(value['allowed_hosts'], check=host)
        def package(v):
            if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}(?:==[a-zA-Z0-9_.+-]{1,40})?', v):
                bad('Packages must be names or pinned versions, not commands, URLs or scripts.')
        strings(value['packages'], check=package)
        cfg = value['config']
        if not isinstance(cfg, dict) or set(cfg) - {'comfy_url', 'worker_id', 'vault_keys', 'timeout_seconds', 'max_memory_mb', 'max_cpu_seconds'}:
            bad('Unsupported environment configuration; executable commands and secrets are forbidden.')
        if 'comfy_url' in cfg:
            endpoint(cfg['comfy_url'])
        if 'worker_id' in cfg:
            _limb(conn, slug, cfg['worker_id'])
        for n in ('timeout_seconds', 'max_memory_mb', 'max_cpu_seconds'):
            if n in cfg:
                integer(cfg[n], 1, 1048576 if n == 'max_memory_mb' else 86400)
        if 'vault_keys' in cfg:
            strings(cfg['vault_keys'], check=key)
            if any(not _get(conn, 'vault', slug, k) for k in cfg['vault_keys']):
                bad('Unknown vault reference.')
    elif kind == 'memory_store':
        text(value['description'], 2000)
        if value['scope_kind'] not in ('project', 'episode', 'user'):
            bad('Invalid memory scope.')
        text(value['scope_id'], 160)
        if value['scope_kind'] == 'project' and value['scope_id'] != '':
            bad('Project memory must not bind another scope.')
        if value['scope_kind'] == 'user' and value['scope_id'] != str(me.actor_id):
            raise AgentError(403, 'User memory must belong to the requesting crew member.')
        if value['scope_kind'] == 'episode':
            _episode(conn, slug, value['scope_id'])
    elif kind == 'vault':
        value['provider_config'] = validate_provider(value['provider_config'])
        if not value['provider_config'].get('api_key_env'):
            bad('Vault stores an allowlisted environment reference, never credential values.')
        strings(value['allowed_agent_keys'], check=key)
        from project_assistant.agent_registry import get_agent
        if any(not get_agent(conn, slug, k) for k in value['allowed_agent_keys']):
            bad('Unknown agent in vault access rule.')
    elif kind == 'service_account':
        _limb(conn, slug, value.get('limb_id'))


def _limb(conn, slug, identifier):
    identifier = db.identifier(identifier)
    from project_assistant import limbs
    if not any(w['id'] == identifier and w['enabled'] for w in limbs.list_workers(conn, slug)):
        bad('Worker must be enabled and scoped to this production.')
    return identifier


def _save(conn, table, column, slug, resource_key, values, expected, existing):
    integer(expected, 0, 2147483646)
    if (existing and existing['version'] != expected) or (not existing and expected != 0):
        raise AgentError(409, 'Resource version changed; reload before saving.', 'VERSION_CONFLICT')
    columns = sorted(values)
    encoded = [json.dumps(values[n], ensure_ascii=False, allow_nan=False) if n in JSON_FIELDS else values[n] for n in columns]
    placeholders = ','.join('%s::jsonb' if n in JSON_FIELDS else '%s' for n in columns)
    if existing:
        sets = ','.join(n + '=%s' + ('::jsonb' if n in JSON_FIELDS else '') for n in columns)
        db.execute(conn, f'UPDATE projectops.{table} SET {sets} WHERE project_slug=%s AND {column}=%s AND version=%s', encoded + [slug, resource_key, expected])
    else:
        db.execute(conn, f'INSERT INTO projectops.{table}(project_slug,{column},' + ','.join(columns) + f') VALUES(%s,%s,{placeholders})', [slug, resource_key] + encoded)
    return db.one(conn, f'SELECT to_jsonb(r) FROM projectops.{table} r WHERE project_slug=%s AND {column}=%s', (slug, resource_key))


def save_resource(conn, me, slug, kind, body, *, episode_id=None):
    table, column, fields = _spec(kind)
    authorize(conn, me, slug, write=True, admin=kind != 'memory_store')
    if not isinstance(body, dict) or set(body) - fields - {column, 'version'} or column not in body or 'version' not in body:
        bad('Supply a resource key, version and supported fields only.')
    resource_key = key(body[column])
    _lock(conn, slug)
    existing = _get(conn, kind, slug, resource_key)
    if existing and kind == 'memory_store':
        authorize_scope(conn, me, slug, existing, episode_id=episode_id, write=True)
        if any(n in body and body[n] != existing[n] for n in ('scope_kind', 'scope_id')):
            bad('Memory scope cannot be rebound; create another store.')
    values = {**DEFAULTS[kind], **({n: existing[n] for n in fields} if existing else {}), **{n: body[n] for n in fields if n in body}}
    if 'display_name' not in values:
        values['display_name'] = resource_key
    _validate(conn, me, slug, kind, values)
    if kind == 'memory_store':
        if values['scope_kind'] != 'user':
            authorize(conn, me, slug, admin=True)
        authorize_scope(conn, me, slug, values, episode_id=episode_id, write=True)
    result = _save(conn, table, column, slug, resource_key, values, body['version'], existing)
    repo.add_audit(conn, slug, action='console_resource', actor_id=me.actor_id, target=resource_key, detail={'kind': kind, 'version': result['version']})
    return result


def authorize_mount(conn, me, slug, profile, store_key, *, write=False, episode_id=None):
    """Use a current persisted profile, never a client-supplied profile/grant."""
    from project_assistant.agent_registry import get_agent
    current = get_agent(conn, slug, profile['agent_key'])
    if not current or not current['enabled']:
        raise AgentError(403, 'Agent is unavailable.')
    mount = next((m for m in current['memory_mounts'] if m['store_key'] == store_key), None)
    if not mount or (write and mount['access'] != 'read_write'):
        raise AgentError(403, 'Memory mount does not permit this operation.')
    store = get_resource(conn, me, slug, 'memory_store', store_key, episode_id=episode_id)
    if not store:
        raise AgentError(404, 'Memory store not found.')
    return authorize_scope(conn, me, slug, store, episode_id=episode_id, write=write)


def memory_entries(conn, me, slug, store_key, *, episode_id=None, profile=None):
    found = (authorize_mount(conn, me, slug, profile, store_key, episode_id=episode_id) if profile is not None
             else get_resource(conn, me, slug, 'memory_store', store_key, episode_id=episode_id))
    if not found:
        raise AgentError(404, 'Memory store not found.')
    return db.many(conn, '''SELECT to_jsonb(e) FROM projectops.agent_memory_entry e
        WHERE project_slug=%s AND store_key=%s ORDER BY entry_key LIMIT 500''', (slug, store_key))


def save_memory_entry(conn, me, slug, body, *, episode_id=None, profile=None):
    fields = {'store_key', 'entry_key', 'title', 'content_md', 'tags', 'version'}
    if not isinstance(body, dict) or set(body) - fields or not {'store_key', 'entry_key', 'version'} <= set(body):
        bad('Invalid memory entry.')
    store_key, entry_key = key(body['store_key']), key(body['entry_key'])
    if profile is not None:
        authorize_mount(conn, me, slug, profile, store_key, write=True, episode_id=episode_id)
    else:
        store = get_resource(conn, me, slug, 'memory_store', store_key, episode_id=episode_id)
        if not store:
            raise AgentError(404, 'Memory store not found.')
        authorize_scope(conn, me, slug, store, write=True, episode_id=episode_id)
    _lock(conn, slug)
    existing = db.one(conn, '''SELECT to_jsonb(e) FROM projectops.agent_memory_entry e
        WHERE project_slug=%s AND store_key=%s AND entry_key=%s''', (slug, store_key, entry_key))
    values = {'store_key': store_key, 'entry_key': entry_key, 'title': entry_key, 'content_md': '', 'tags': [],
              **({n: existing[n] for n in ('title', 'content_md', 'tags')} if existing else {}),
              **{n: body[n] for n in ('title', 'content_md', 'tags') if n in body}, 'updated_by': str(me.actor_id)}
    text(values['title'], 200, required=True)
    text(values['content_md'], 30000)
    strings(values['tags'], 32, check=key)
    return _save(conn, 'agent_memory_entry', 'id', slug, existing['id'] if existing else str(uuid.uuid4()), values, body['version'], existing)


def history(conn, me, slug, kind, resource_key, *, episode_id=None):
    authorize(conn, me, slug)
    if kind == 'memory_entry':
        found = db.one(conn, 'SELECT store_key FROM projectops.agent_memory_entry WHERE project_slug=%s AND id=%s', (slug, db.identifier(resource_key)))
        if not found or not get_resource(conn, me, slug, 'memory_store', found, episode_id=episode_id):
            raise AgentError(404, 'Memory entry not found.')
    elif kind in RESOURCES:
        if not get_resource(conn, me, slug, kind, resource_key, episode_id=episode_id):
            raise AgentError(404, 'Resource not found.')
    elif kind not in ('profile', 'settings'):
        bad('Unknown history kind.')
    if kind not in ('memory_store', 'memory_entry', 'skill'):
        authorize(conn, me, slug, admin=True)
    return db.many(conn, '''SELECT to_jsonb(r) FROM projectops.agent_resource_revision r
        WHERE project_slug=%s AND resource_kind=%s AND resource_key=%s ORDER BY version DESC LIMIT 100''', (slug, kind, resource_key))


def ensure_defaults(conn, slug):
    from project_assistant.skills_registry import ensure_default_skills
    ensure_default_skills(conn, slug)
    for env_key, name, kind, enabled in (
        ('env_local_4090', 'Local 4090', 'local_sandbox', True),
        ('env_hybrid_cloud', 'Hybrid Cloud Pool', 'hybrid_cloud', False),
        ('env_acp_local', 'Local ACP CLI', 'acp_cli', False),
    ):
        db.execute(conn, '''INSERT INTO projectops.agent_environment(project_slug,env_key,display_name,env_kind,enabled)
            VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''', (slug, env_key, name, kind, enabled))
    for store_key, name in (('style_rules', 'Style Rules'), ('continuity_bible', 'Continuity Bible'), ('retake_learnings', 'Retake Learnings')):
        db.execute(conn, '''INSERT INTO projectops.agent_memory_store(project_slug,store_key,display_name)
            VALUES(%s,%s,%s) ON CONFLICT DO NOTHING''', (slug, store_key, name))
    db.execute(conn, 'INSERT INTO projectops.agent_console_settings(project_slug) VALUES(%s) ON CONFLICT DO NOTHING', (slug,))


def get_settings(conn, me, slug):
    authorize(conn, me, slug)
    return db.one(conn, 'SELECT to_jsonb(s) FROM projectops.agent_console_settings s WHERE project_slug=%s', (slug,))


def save_settings(conn, me, slug, body):
    authorize(conn, me, slug, admin=True)
    if not isinstance(body, dict) or set(body) - set(SETTINGS) - {'version'} or 'version' not in body:
        bad('Invalid settings fields or missing version.')
    _lock(conn, slug)
    existing = get_settings(conn, me, slug)
    values = {**SETTINGS, **({n: existing[n] for n in SETTINGS} if existing else {}), **{n: body[n] for n in SETTINGS if n in body}}
    for n in ('spend_limit_monthly_usd', 'spend_limit_session_usd', 'spend_limit_episode_usd'):
        values[n] = money(values[n])
        if values[n].as_tuple().exponent < -2:
            bad('Spend limits permit cents only.')
    if values['on_spend_limit'] not in ('pause', 'downgrade_open_weights'):
        bad('Invalid spend policy.')
    for name in ('rate_limits', 'retention_policy', 'otel_config'):
        v = values[name]
        if not isinstance(v, dict) or set(v) != set(SETTINGS[name]):
            bad('Invalid settings object.')
    for n, v in values['rate_limits'].items():
        integer(v, 1, 10000 if n == 'rpm_per_agent' else 32)
    retention = values['retention_policy']
    for n in ('session_logs_days', 'temp_media_days'):
        integer(retention[n], 1, 3650)
    if type(retention['zero_data_retention_notice']) is not bool:
        bad('Invalid retention notice.')
    otel = values['otel_config']
    if type(otel['enabled']) is not bool:
        bad('Invalid telemetry flag.')
    text(otel['service_name'], 120, required=True)
    text(otel['endpoint'], 2000)
    if otel['endpoint']:
        endpoint(otel['endpoint'])
    elif otel['enabled']:
        bad('Enabled telemetry requires an endpoint.')
    strings(values['webhooks'], 5)
    # Existing Story webhooks own signing, SSRF checks and delivery history.
    for identifier in values['webhooks']:
        hook = db.one(conn, "SELECT owner_id::text FROM projectops.story_record WHERE id=%s AND kind='webhook'", (identifier,))
        if hook != str(me.actor_id):
            bad('Webhook must be an existing reference owned by the requesting showrunner.')
    integer(body['version'], 0, 2147483646)
    if (existing and existing['version'] != body['version']) or (not existing and body['version'] != 0):
        raise AgentError(409, 'Settings version changed.', 'VERSION_CONFLICT')
    cols = sorted(values)
    params = [json.dumps(values[n], allow_nan=False) if n in JSON_FIELDS else values[n] for n in cols]
    if existing:
        db.execute(conn, 'UPDATE projectops.agent_console_settings SET ' + ','.join(n+'=%s'+('::jsonb' if n in JSON_FIELDS else '') for n in cols) + ' WHERE project_slug=%s AND version=%s', params+[slug, body['version']])
    else:
        db.execute(conn, 'INSERT INTO projectops.agent_console_settings(project_slug,'+','.join(cols)+') VALUES(%s,'+','.join('%s::jsonb' if n in JSON_FIELDS else '%s' for n in cols)+')', [slug]+params)
    return get_settings(conn, me, slug)


def append_usage(conn, slug, event):
    """Trusted runtime writer only; immutable event_key makes duplicate recording safe.

    This records estimates, not payment/billing enforcement. Reserve before outbound
    operations in the runtime layer; never treat this function as an admission grant.
    """
    defaults = dict(run_id=None, episode_id=None, owner_id=None, agent_key='coordinator', provider_name='local',
                    model_name='default', tier='open_weights', input_tokens=0, output_tokens=0, cached_tokens=0,
                    cache_hit=False, fingerprint=None, duration_ms=0, estimated_cost_usd=0, estimated_saved_usd=0, meta={})
    if not isinstance(event, dict) or set(event) - set(defaults) - {'event_key', 'usage_kind'} or not {'event_key', 'usage_kind'} <= set(event):
        bad('Invalid usage event.')
    v = {**defaults, **event}
    text(v['event_key'], 160, required=True)
    if v['agent_key'] not in ('studio:prepare', 'studio:open', 'studio:closed'):
        key(v['agent_key'])
    if v['usage_kind'] not in ('llm_turn', 'image_gen', 'video_gen', 'frame_prep', 'grader_check') or v['tier'] not in ('open_weights', 'closed_flagship', 'cloud_comfy'):
        bad('Invalid usage category.')
    for n in ('provider_name', 'model_name'):
        if not isinstance(v[n], str) or not re.fullmatch(r'[a-zA-Z0-9_.:/-]{1,160}', v[n]):
            bad('Invalid provider/model identifier.')
    for n in ('input_tokens', 'output_tokens', 'cached_tokens', 'duration_ms'):
        integer(v[n])
    if type(v['cache_hit']) is not bool or v['cached_tokens'] > v['input_tokens']:
        bad('Invalid cache counters.')
    if v['fingerprint'] is not None and (not isinstance(v['fingerprint'], str) or not re.fullmatch('[a-f0-9]{64}', v['fingerprint'])):
        bad('Invalid request fingerprint.')
    for n in ('estimated_cost_usd', 'estimated_saved_usd'):
        v[n] = money(v[n])
    if v['run_id'] is not None:
        run = db.get_run(conn, slug, v['run_id'])
        if not run or (v['owner_id'] is not None and str(v['owner_id']) != run['created_by']):
            bad('Usage run must belong to this production and owner.')
        v['run_id'], v['owner_id'] = run['id'], run['created_by']
    if v['owner_id'] is not None:
        v['owner_id'] = db.identifier(v['owner_id'])
        from project_assistant import store
        if not any(m['actor_id'] == v['owner_id'] for m in repo.active_members(conn)) or not store.is_member_enabled(conn, slug, v['owner_id']):
            bad('Invalid usage owner.')
    if v['episode_id'] is not None:
        _episode(conn, slug, v['episode_id'])
    if not isinstance(v['meta'], dict) or set(v['meta']) - {'estimated', 'reservation_key', 'outcome', 'revision_attempt'}:
        bad('Usage metadata cannot contain prompts, errors or credentials.')
    if 'estimated' in v['meta'] and type(v['meta']['estimated']) is not bool:
        bad('Invalid estimate marker.')
    if 'reservation_key' in v['meta']:
        text(v['meta']['reservation_key'], 160, required=True)
    if 'outcome' in v['meta'] and v['meta']['outcome'] not in ('succeeded', 'failed', 'canceled', 'unknown'):
        bad('Invalid usage outcome.')
    if 'revision_attempt' in v['meta']:
        integer(v['meta']['revision_attempt'], 0, 3)
    _lock(conn, slug)
    old = db.one(conn, 'SELECT to_jsonb(l) FROM projectops.agent_usage_ledger l WHERE project_slug=%s AND event_key=%s', (slug, v['event_key']))
    # Normalize through JSON numbers for comparison with PostgreSQL to_jsonb numeric values.
    compare = {**v, 'estimated_cost_usd': float(v['estimated_cost_usd']), 'estimated_saved_usd': float(v['estimated_saved_usd'])}
    if old:
        if any(old[n] != compare[n] for n in compare):
            raise AgentError(409, 'Usage event identity was already recorded with different values.')
        return old
    cols = sorted(v)
    params = [json.dumps(v[n], allow_nan=False) if n == 'meta' else v[n] for n in cols]
    db.execute(conn, 'INSERT INTO projectops.agent_usage_ledger(project_slug,'+','.join(cols)+') VALUES(%s,'+','.join('%s::jsonb' if n == 'meta' else '%s' for n in cols)+')', [slug]+params)
    return db.one(conn, 'SELECT to_jsonb(l) FROM projectops.agent_usage_ledger l WHERE project_slug=%s AND event_key=%s', (slug, v['event_key']))


def analytics(conn, me, slug, *, days=30):
    """Aggregates only: admin configuration/cancellation is not private trace access."""
    authorize(conn, me, slug)
    integer(days, 1, 366)
    return db.many(conn, '''SELECT jsonb_build_object('date',created_at::date,'agent_key',agent_key,
        'provider_name',provider_name,'model_name',model_name,'usage_kind',usage_kind,
        'input_tokens',sum(input_tokens),'output_tokens',sum(output_tokens),'cached_tokens',sum(cached_tokens),
        'events',count(*),'cache_hits',count(*) FILTER (WHERE cache_hit),
        'estimated_cost_usd',sum(estimated_cost_usd),'estimated_saved_usd',sum(estimated_saved_usd))
        FROM projectops.agent_usage_ledger WHERE project_slug=%s AND created_at>=NOW()-(%s * INTERVAL '1 day')
        GROUP BY created_at::date,agent_key,provider_name,model_name,usage_kind ORDER BY created_at::date''', (slug, days))


def execution_resources(conn, me, slug, agent_key, *, destination=None, vault_key=None):
    """Revalidate execution bindings; runtime must apply returned resource limits.

    Network policy checks a destination's host, not DNS rebinding or an OS sandbox.
    Call again at each outbound boundary; never serialize this result as authority.
    Production policy, privacy, spend/admission and lease checks remain mandatory.
    """
    authorize(conn, me, slug, write=True)
    from project_assistant.agent_registry import get_agent
    profile = get_agent(conn, slug, key(agent_key))
    if not profile or not profile['enabled'] or profile['role_kind'] == 'observer':
        raise AgentError(403, 'Agent is unavailable.')
    environment = _get(conn, 'environment', slug, profile['default_environment_key'])
    if not environment or not environment['enabled']:
        raise AgentError(403, 'Execution environment is unavailable.')
    provider = None
    if vault_key is not None:
        reference = _get(conn, 'vault', slug, vault_key)
        if not reference or not reference['enabled'] or agent_key not in reference['allowed_agent_keys'] or vault_key not in environment['config'].get('vault_keys', []):
            raise AgentError(403, 'Credential reference is not mounted for this agent and environment.')
        provider = validate_provider(reference['provider_config'])
        destination = destination or provider.get('base_url')
    elif profile.get('provider_config'):
        provider = validate_provider(profile['provider_config'])
        destination = destination or provider.get('base_url')
    if destination is not None:
        endpoint(destination)
        host = urlsplit(destination).hostname.lower()
        access = environment['network_access']
        if access == 'offline' or (access == 'restricted' and host not in ('localhost', '127.0.0.1', '::1')) or (access == 'allowlist' and host not in [h.lower() for h in environment['allowed_hosts']]):
            raise AgentError(403, 'Environment network policy denies this destination.')
    worker_id = environment['config'].get('worker_id')
    if worker_id:
        _limb(conn, slug, worker_id)
    return {'profile': profile, 'environment': environment, 'provider_config': provider}
