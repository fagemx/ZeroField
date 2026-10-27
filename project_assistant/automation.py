"""One switch for the production's automatic work (SPEC_20 R40).

While paused, nothing starts on its own: automatic take grading (take_grader.on_take), scheduled
deployments (console_deployments.produce_due) and, once they exist, crew pre-production jobs, which
must call automation_paused() before they start. Work a person asks for by hand is never blocked:
grading a take from shot review, triggering a deployment, sending a chat turn, running a pipeline.
Work that is already running finishes; pausing does not cancel it.

The state is a project setting ('automation.paused'), JSON with who paused it, when and why.
"""
from __future__ import annotations

import datetime as dt
import json

KEY = 'automation.paused'
REASON_LIMIT = 300


def state(conn, slug):
    """{'paused', 'by', 'byName', 'at', 'reason'}; anything unreadable counts as running."""
    from project_assistant import store
    try:
        value = json.loads(store.get_setting(conn, slug, KEY) or '{}')
    except ValueError:
        value = {}
    if not isinstance(value, dict):
        value = {}
    return {'paused': value.get('paused') is True, 'by': value.get('by'), 'byName': value.get('byName'),
            'at': value.get('at'), 'reason': value.get('reason') or ''}


def automation_paused(conn, slug):
    """The check every automatic job makes before it starts."""
    return state(conn, slug)['paused']


paused = automation_paused


def set_paused(conn, me, slug, body):
    """Showrunner only. Body {'paused': bool, 'reason'?: str}; the caller commits."""
    from project_assistant import agent_console_store as resources, store
    from project_docs import repository as repo
    resources.authorize(conn, me, slug, admin=True)
    if not isinstance(body, dict) or set(body) - {'paused', 'reason'} or type(body.get('paused')) is not bool:
        resources.bad('Send {"paused": true|false} and an optional reason.')
    reason = resources.text(body.get('reason', ''), REASON_LIMIT).strip()
    value = {'paused': body['paused'], 'by': str(me.actor_id), 'byName': getattr(me, 'name', None) or None,
             'at': dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
             'reason': reason if body['paused'] else ''}
    store.set_setting(conn, slug, KEY, json.dumps(value, ensure_ascii=False))
    repo.add_audit(conn, slug, action='automation_pause' if body['paused'] else 'automation_resume',
                   actor_id=me.actor_id, target=KEY, detail={'reason': value['reason']})
    return state(conn, slug)
