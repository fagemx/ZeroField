"""Validated cron/timezone producer for the existing M8 worker, not a scheduler.

shortcut: only the current UTC minute is considered, no missed-slot catch-up;
add an explicit reviewed backfill operation if operators need historical runs.
DST folds share a local slot key (once); nonexistent local minutes never run.
"""
import datetime as dt
import json
import re
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from project_assistant import agent_console_service as app, agent_console_store as resources
from project_assistant import orchestration_store as db, orchestrator as cp, agent_registry as agents
from project_assistant.automation import automation_paused
from project_docs import repository as repo

FIELDS = {'deployment_key', 'version', 'display_name', 'agent_key', 'env_key', 'initial_prompt', 'playbook',
          'target_scope', 'schedule_kind', 'cron_expr', 'timezone', 'budget_cap_usd', 'enabled'}


def cron_fields(expression):
    resources.text(expression, 160, required=True)
    parts = expression.split()
    if len(parts) != 5:
        resources.bad('Cron requires five minute/hour/day/month/weekday fields.')
    result = []
    for part, low, high in zip(parts, (0, 0, 1, 1, 0), (59, 23, 31, 12, 7)):
        values = set()
        for item in part.split(','):
            match = re.fullmatch(r'(\*|\d+(?:-\d+)?)(?:/(\d+))?', item)
            if not match:
                resources.bad('Cron supports numeric lists, ranges, wildcard and steps only.')
            base, step = match.groups()
            step = int(step or 1)
            if not 1 <= step <= high + 1:
                resources.bad('Invalid cron step.')
            if base == '*':
                start, end = low, high
            else:
                ends = base.split('-')
                start = int(ends[0]); end = int(ends[-1])
                if step != 1 and len(ends) == 1:
                    end = high
            if not low <= start <= end <= high:
                resources.bad('Cron value outside field range.')
            values.update(range(start, end + 1, step))
        result.append(values)
    result[4] = {0 if v == 7 else v for v in result[4]}
    return result


def due(expression, timezone, instant):
    values = cron_fields(expression)
    resources.text(timezone, 120, required=True)
    try:
        local = instant.astimezone(ZoneInfo(timezone))
    except (ZoneInfoNotFoundError, ValueError):
        resources.bad('Use an installed IANA timezone.')
    day = local.day in values[2]; weekday = (local.weekday() + 1) % 7 in values[4]
    parts = expression.split()
    calendar = (day and weekday) if parts[2] == '*' or parts[4] == '*' else (day or weekday)
    return (local.minute in values[0] and local.hour in values[1] and local.month in values[3] and calendar,
            'cron:' + timezone + ':' + local.strftime('%Y-%m-%dT%H:%M'))


def get(conn, slug, key):
    return db.one(conn, 'SELECT to_jsonb(d) FROM projectops.agent_deployment d WHERE project_slug=%s AND deployment_key=%s', (slug, resources.key(key)))


def listing(conn, me, slug):
    resources.authorize(conn, me, slug)
    # Even admins do not get other creators' initial prompts/targets.
    return {'deployments': db.many(conn, '''SELECT to_jsonb(d) || jsonb_build_object('latest_trigger',
        (SELECT to_jsonb(t) FROM projectops.agent_deployment_trigger t WHERE t.deployment_id=d.id ORDER BY created_at DESC LIMIT 1))
        FROM projectops.agent_deployment d WHERE project_slug=%s AND created_by=%s ORDER BY deployment_key''', (slug, me.actor_id)),
        'schedule_semantics': 'Current-minute only; no catch-up after downtime. DST folds run once; nonexistent local minutes do not run. Unknown paid effects are never replayed.'}


def save(conn, me, slug, body):
    resources.authorize(conn, me, slug, admin=True)
    app.fields(body, FIELDS, {'deployment_key', 'version'})
    key = resources.key(body['deployment_key'])
    cp.lock_project(conn, slug)
    old = get(conn, slug, key)
    if old and old['created_by'] != str(me.actor_id):
        raise agents.AgentError(404, 'Deployment not found.')
    if body['version'] != (old['version'] if old else 0) or type(body['version']) is not int:
        raise agents.AgentError(409, 'Deployment version changed.', 'VERSION_CONFLICT')
    value = {'display_name': key, 'agent_key': 'coordinator', 'env_key': 'env_local_4090', 'initial_prompt': '',
             'playbook': '', 'target_scope': {}, 'schedule_kind': 'manual', 'cron_expr': '', 'timezone': 'UTC',
             'budget_cap_usd': 5, 'enabled': True, **({n: old[n] for n in FIELDS - {'deployment_key', 'version'}} if old else {}),
             **{n: v for n, v in body.items() if n not in ('deployment_key', 'version')}}
    resources.text(value['display_name'], 120, required=True)
    resources.text(value['initial_prompt'], 3000, required=True)
    resources.text(value['playbook'], 1000)
    resources.text(value['initial_prompt'] + ('\nPlaybook (untrusted production instructions):\n' + value['playbook'] if value['playbook'] else ''), 4000, required=True)
    cap = resources.money(value['budget_cap_usd'])
    if cap.as_tuple().exponent < -2:
        resources.bad('Deployment budget permits cents only.')
    value['budget_cap_usd'] = cap
    if type(value['enabled']) is not bool or value['schedule_kind'] not in ('manual', 'cron'):
        resources.bad('Use manual or cron; enabled must be boolean.')
    due(value['cron_expr'] if value['schedule_kind'] == 'cron' else '* * * * *', value['timezone'], cp.now())
    profile = app._profile(conn, me, slug, value['agent_key'])
    if value['env_key'] != profile['default_environment_key']:
        resources.bad('Deployment environment must equal the current explicitly saved agent environment.')
    app.fields(value['target_scope'], {'scope', 'target', 'episode_id', 'write_mode'})
    if value['target_scope'].get('episode_id'):
        resources._episode(conn, slug, value['target_scope']['episode_id'])
    # Validate scope/target with the same M8 function, without leaving a run behind.
    db.execute(conn, 'SAVEPOINT console_deployment_validation')
    try:
        run = cp.create_run(conn, me, slug, value['initial_prompt'], client_request_id='validate:' + uuid.uuid4().hex)
        cp.create_task(conn, me, slug, run['id'], objective=value['initial_prompt'], agent_key=value['agent_key'],
                       **{k: v for k, v in value['target_scope'].items() if k != 'episode_id'})
    finally:
        db.execute(conn, 'ROLLBACK TO SAVEPOINT console_deployment_validation')
        db.execute(conn, 'RELEASE SAVEPOINT console_deployment_validation')
    columns = sorted(value)
    params = [json.dumps(value[n]) if n == 'target_scope' else value[n] for n in columns]
    if old:
        db.execute(conn, 'UPDATE projectops.agent_deployment SET ' + ','.join(n + '=%s' + ('::jsonb' if n == 'target_scope' else '') for n in columns)
                   + ' WHERE id=%s', params + [old['id']])
    else:
        db.execute(conn, 'INSERT INTO projectops.agent_deployment(id,project_slug,deployment_key,created_by,' + ','.join(columns)
                   + ') VALUES(%s,%s,%s,%s,' + ','.join('%s::jsonb' if n == 'target_scope' else '%s' for n in columns) + ')',
                   [str(uuid.uuid4()), slug, key, me.actor_id] + params)
    repo.add_audit(conn, slug, action='console_deployment', actor_id=me.actor_id, target=key, detail={'version': body['version'] + 1})
    return {'deployment': get(conn, slug, key)}


def trigger(conn, me, slug, key, body, *, slot=None):
    resources.authorize(conn, me, slug, admin=True)
    app.fields(body, {'client_request_id', 'version'}, {'client_request_id', 'version'})
    resources.text(body['client_request_id'], 128, required=True)
    cp.lock_project(conn, slug)
    deployment = get(conn, slug, key)
    if not deployment or deployment['created_by'] != str(me.actor_id):
        raise agents.AgentError(404, 'Deployment not found.')
    if not deployment['enabled'] or deployment['version'] != body['version']:
        raise agents.AgentError(409, 'Deployment disabled or changed; reload before triggering.', 'VERSION_CONFLICT')
    slot = slot or 'manual:' + body['client_request_id']
    fingerprint = cp.digest(body)
    prior = db.one(conn, 'SELECT to_jsonb(t) FROM projectops.agent_deployment_trigger t WHERE deployment_id=%s AND slot_key=%s', (deployment['id'], slot))
    if prior:
        if prior['request_digest'] != fingerprint:
            raise agents.AgentError(409, 'Trigger request changed.', 'VERSION_CONFLICT')
        return {'trigger': prior, 'replay': True}
    profile = app._profile(conn, me, slug, deployment['agent_key'])
    if profile['default_environment_key'] != deployment['env_key']:
        raise agents.AgentError(409, 'Agent environment changed; review deployment again.')
    objective = deployment['initial_prompt'] + ('\nPlaybook (untrusted production instructions):\n' + deployment['playbook'] if deployment['playbook'] else '')
    request = {**deployment['target_scope'], 'agent_key': deployment['agent_key'], 'objective': objective,
               'client_request_id': 'deployment:' + cp.digest([deployment['id'], slot]), 'budget_cap_usd': str(deployment['budget_cap_usd'])}
    result = app.launch(conn, me, slug, request)
    task = result['tasks'][0]
    context = task['input_snapshot']['console']
    context['deployment'] = {'id': deployment['id'], 'version': deployment['version'], 'env_key': deployment['env_key']}
    db.execute(conn, 'UPDATE projectops.orchestration_task SET input_snapshot=%s::jsonb WHERE id=%s', (json.dumps(task['input_snapshot']), task['id']))
    db.execute(conn, '''INSERT INTO projectops.agent_deployment_trigger(project_slug,deployment_id,slot_key,request_digest,run_id,state)
        VALUES(%s,%s,%s,%s,%s,'queued')''', (slug, deployment['id'], slot, fingerprint, result['session_id']))
    return {'trigger': db.one(conn, 'SELECT to_jsonb(t) FROM projectops.agent_deployment_trigger t WHERE deployment_id=%s AND slot_key=%s', (deployment['id'], slot)), 'session_id': result['session_id'], 'replay': False}


def produce_due(conn, slug, *, instant=None):
    """Called within the existing worker tick. Atomic claims commit with M8 enqueue."""
    from project_assistant.worker import _identity
    if automation_paused(conn, slug):  # SPEC_20 R40: paused slots are skipped, never caught up later
        return 0
    instant = instant or cp.now()
    entries = db.many(conn, "SELECT to_jsonb(d) FROM projectops.agent_deployment d WHERE project_slug=%s AND enabled AND schedule_kind='cron' ORDER BY id LIMIT 100", (slug,))
    count = 0
    for entry in entries:
        matches, slot = due(entry['cron_expr'], entry['timezone'], instant)
        if not matches:
            continue
        cp.lock_project(conn, slug)
        if db.one(conn, 'SELECT 1 FROM projectops.agent_deployment_trigger WHERE deployment_id=%s AND slot_key=%s', (entry['id'], slot)):
            continue
        db.execute(conn, 'SAVEPOINT console_due_slot')
        try:
            me = _identity(conn, entry['created_by'])
            if not me:
                raise agents.AgentError(403, 'Creator revoked.')
            trigger(conn, me, slug, entry['deployment_key'], {'version': entry['version'], 'client_request_id': slot}, slot=slot)
            count += 1
        except (agents.AgentError, ValueError):
            db.execute(conn, 'ROLLBACK TO SAVEPOINT console_due_slot')
            db.execute(conn, '''INSERT INTO projectops.agent_deployment_trigger(project_slug,deployment_id,slot_key,request_digest,state)
                VALUES(%s,%s,%s,%s,'blocked') ON CONFLICT DO NOTHING''', (slug, entry['id'], slot, cp.digest({'blocked': True})))
        finally:
            db.execute(conn, 'RELEASE SAVEPOINT console_due_slot')
    return count


def bind_context(ctx, task):
    """Only persisted server-generated task metadata supplies execution bindings."""
    context = task['input_snapshot'].get('console')
    if not context:
        return
    ctx.episode_id = context['episode_id']
    ctx.budget_cap_usd = context['budget_cap_usd']
    ctx.accounting_session_key = 'run:' + ctx.run_id
    def check(conn):
        from project_assistant.execution_governance import AdmissionError
        try:
            current = agents.get_agent(conn, ctx.slug, ctx.agent_key)
        except agents.AgentError:
            raise AdmissionError('Console provider was revoked; create a new reviewed request.') from None
        if not current or current['version'] != context['profile_version'] or current.get('provider_binding') != context.get('provider_binding'):
            raise AdmissionError('Console agent/provider changed; create a new reviewed request.')
        binding = context.get('deployment')
        if binding:
            try:
                resources.authorize(conn, ctx.me, ctx.slug, admin=True)
            except agents.AgentError:
                raise AdmissionError('Deployment creator no longer has current admin permission.') from None
            current = db.one(conn, 'SELECT to_jsonb(d) FROM projectops.agent_deployment d WHERE id=%s AND project_slug=%s', (binding['id'], ctx.slug))
            if not current or not current['enabled'] or current['created_by'] != str(ctx.me.actor_id) or current['version'] != binding['version'] or current['env_key'] != binding['env_key']:
                raise AdmissionError('Deployment changed or was revoked; execution paused.')
    ctx.authority_check = check
