"""Authenticated lean Console routes. Long polling holds no DB connection/lock."""
import re
import time
from urllib.parse import parse_qs

from project_assistant import agent_console_service as app, agent_console_store as resources
from project_assistant import console_deployments as deployments, console_connections as connections
from project_assistant import agent_registry as agents
from project_docs import service

ROUTE = re.compile(r'^/projects/api/([a-z0-9][a-z0-9-]{0,40})/agent-console(?:/(.*))?$')
RESOURCE = {'skills': 'skill', 'environments': 'environment', 'providers': 'vault', 'memory-stores': 'memory_store'}


def dispatch(conn, me, slug, path, method, body, query):
    resources.authorize(conn, me, slug, write=method != 'GET')
    episode = query.get('episode_id')
    parts = path.split('/') if path else []
    if method == 'GET':
        if path in ('', 'dashboard'):
            return app.overview(conn, me, slug)
        if path == 'quickstart':
            return app.templates(conn, me, slug)
        if path == 'agents':
            return app.profiles(conn, me, slug)
        if path == 'api-keys':
            return app.provider_settings(conn, me, slug)
        if path == 'environments':
            return app.environment_list(conn, me, slug)
        if path == 'spend-rate-limits':
            return app.limits(conn, me, slug)
        if path == 'usage-cost':
            try:
                days = int(query.get('days', 30))
            except (ValueError, TypeError):
                resources.bad('days must be an integer from 1 to 366.')
            return app.usage(conn, me, slug, days)
        if path == 'sessions':
            return app.session_list(conn, me, slug)
        if len(parts) == 2 and parts[0] == 'sessions':
            return app.session_detail(conn, me, slug, parts[1], query.get('cursor'))
        if path == 'deployments':
            return deployments.listing(conn, me, slug)
        if parts and parts[0] in RESOURCE:
            kind = RESOURCE[parts[0]]
            if len(parts) == 1:
                return {'items': resources.list_resources(conn, me, slug, kind, episode_id=episode)}
            if len(parts) == 2:
                item = resources.get_resource(conn, me, slug, kind, parts[1], episode_id=episode)
                if not item:
                    raise agents.AgentError(404, 'Resource not found.')
                return {'item': item}
            if len(parts) == 3 and parts[2] == 'history':
                return {'history': resources.history(conn, me, slug, kind, parts[1], episode_id=episode)}
            if parts[0] == 'memory-stores' and len(parts) == 3 and parts[2] == 'entries':
                return {'entries': resources.memory_entries(conn, me, slug, parts[1], episode_id=episode)}
        if len(parts) == 3 and parts[0] == 'memory-entries' and parts[2] == 'history':
            return {'history': resources.history(conn, me, slug, 'memory_entry', parts[1], episode_id=episode)}
        if len(parts) == 3 and parts[0] == 'agents' and parts[2] == 'history':
            return {'history': resources.history(conn, me, slug, 'profile', parts[1])}
    if method in ('POST', 'PUT', 'PATCH'):
        if path == 'quickstart/draft' and method == 'POST':
            return app.draft(conn, me, slug, body)
        if path == 'agents':
            return {'agent': app.save_profile(conn, me, slug, body)}
        if path == 'api-keys/default':
            return app.set_default_provider(conn, me, slug, body)
        if path == 'spend-rate-limits':
            return app.limits(conn, me, slug, body)
        if path == 'playground' and method == 'POST':
            return app.playground(conn, me, slug, body)
        if path == 'sessions' and method == 'POST':
            return app.launch(conn, me, slug, body)
        if len(parts) == 3 and parts[0] == 'sessions' and parts[2] in ('cancel', 'interrupt', 'resolve', 'resume') and method == 'POST':
            return app.session_action(conn, me, slug, parts[1], parts[2], body)
        if path == 'deployments':
            return deployments.save(conn, me, slug, body)
        if len(parts) == 3 and parts[0] == 'deployments' and parts[2] == 'trigger' and method == 'POST':
            return deployments.trigger(conn, me, slug, parts[1], body)
        if path in RESOURCE:
            return {'item': resources.save_resource(conn, me, slug, RESOURCE[path], body, episode_id=episode)}
        if path == 'memory-entries':
            return {'entry': resources.save_memory_entry(conn, me, slug, body, episode_id=episode)}
        if path == 'memory-stores/consolidate' and method == 'POST':
            return app.consolidate(conn, me, slug, body)
    if method == 'DELETE':
        if len(parts) == 2 and parts[0] in RESOURCE:
            app.fields(body, {'version'}, {'version'})
            kind = RESOURCE[parts[0]]
            column = resources.RESOURCES[kind][1]
            flag = {'archived': True} if kind == 'memory_store' else {'enabled': False}
            return {'item': resources.save_resource(conn, me, slug, kind, {column: parts[1], 'version': body['version'], **flag}, episode_id=episode)}
        if len(parts) == 2 and parts[0] == 'memory-entries':
            from project_assistant import orchestration_store as db
            app.fields(body, {'version'}, {'version'})
            entry = db.one(conn, 'SELECT to_jsonb(e) FROM projectops.agent_memory_entry e WHERE project_slug=%s AND id=%s', (slug, db.identifier(parts[1])))
            if not entry:
                raise agents.AgentError(404, 'Memory entry not found.')
            return {'entry': resources.save_memory_entry(conn, me, slug, {'store_key': entry['store_key'], 'entry_key': entry['entry_key'], 'version': body['version'], 'archived': True}, episode_id=episode)}
        if len(parts) == 2 and parts[0] == 'agents':
            app.fields(body, {'version'}, {'version'})
            return {'agent': app.save_profile(conn, me, slug, {'agent_key': parts[1], 'version': body['version'], 'enabled': False})}
        if len(parts) == 2 and parts[0] == 'deployments':
            app.fields(body, {'version'}, {'version'})
            return deployments.save(conn, me, slug, {'deployment_key': parts[1], 'version': body['version'], 'enabled': False})
    raise agents.AgentError(404, 'Console endpoint not found.')


def handle(handler, parsed, method):
    match = ROUTE.fullmatch(parsed.path)
    if not match:
        return False
    from project_docs import http
    identity, problem = handler.project_docs_identity()
    me = service.identity_from(identity) if not problem else None
    if not me:
        handler.send_json(401, {'error': 'Sign in with an active crew account.', 'code': 'AUTH_REQUIRED'})
        return True
    if method not in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE'):
        handler.send_json(405, {'error': 'Unsupported method.'})
        return True
    body = {}
    if method != 'GET':
        refused = http._write_allowed(handler)
        if refused:
            handler.send_json(403, {'error': refused, 'code': 'POLICY_DENIED'})
            return True
        body, error = http._json_body(handler)
        if error:
            handler.send_json(*error)
            return True
    slug, path = match.groups(); path = path or ''
    query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    conn = None
    try:
        # Network operations open their own short, currently-authorized transactions.
        if method == 'POST' and (path == 'connections/health' or re.fullmatch(r'sessions/[0-9a-f-]{36}/router-quotes', path)):
            with http.open_connection() as c:
                http._ensure_schema(c)
                resources.authorize(c, me, slug, write=True)
            payload = (connections.health(http.open_connection, me, slug, body) if path == 'connections/health' else
                       connections.quote(http.open_connection, me, slug, path.split('/')[1], body))
        elif method == 'GET' and re.fullmatch(r'sessions/[0-9a-f-]{36}/events', path):
            wait = float(query.get('wait', '0'))
            if not 0 <= wait <= 15 or len(query.get('cursor', '')) > 2048:
                resources.bad('wait must be 0..15 seconds; cursor must be bounded.')
            until = time.monotonic() + wait
            while True:
                with http.open_connection() as c:
                    http._ensure_schema(c)
                    payload = app.session_detail(c, me, slug, path.split('/')[1], query.get('cursor'))
                if payload['changed'] or payload['has_more'] or time.monotonic() >= until:
                    break
                time.sleep(min(.2, max(0, until - time.monotonic())))
        else:
            conn = http.open_connection()
            http._ensure_schema(conn)
            payload = dispatch(conn, me, slug, path, method, body, query)
            conn.commit()
        handler.send_json(200, payload)
    except Exception as exc:
        if conn:
            conn.rollback()
        from project_assistant.execution_governance import AdmissionError
        from project_assistant.limb_worker import WorkerError
        from project_docs.story_openapi import StoryError
        if isinstance(exc, agents.AgentError):
            status, message, code = exc.status, str(exc), exc.code
        elif isinstance(exc, (AdmissionError, WorkerError, StoryError)):
            status, message, code = 409, str(exc), 'NEEDS_YOU'
        elif isinstance(exc, (ValueError, TypeError, KeyError)):
            status, message, code = 400, 'Invalid Console request.', 'INVALID_REQUEST'
        else:
            status, message, code = 503, 'Console temporarily unavailable.', 'UNAVAILABLE'
            print('Console service failure: ' + type(exc).__name__, flush=True)
        handler.send_json(status, {'error': message, 'code': code})
    finally:
        if conn:
            conn.close()
    return True
