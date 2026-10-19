"""Explicit bounded read-only health/discovery and Router quotes outside DB locks."""
import datetime as dt
import json
import urllib.error
import urllib.request
from pathlib import Path

from project_assistant import agent_console_service as app, agent_console_store as resources
from project_assistant import execution_governance as governance, orchestrator as cp
from project_assistant import orchestration_store as db, tools
from project_assistant.studio import comfy_router, comfy_mcp, model_router
from project_docs import repository as repo, story_openapi as story, story_allocation


def context(factory, me, slug, agent_key):
    ctx = tools.ToolContext(factory, slug, me, Path('.'), None, agent_key=agent_key,
                            deadline_at=(cp.now() + dt.timedelta(seconds=30)).isoformat())
    governance.transaction(ctx, lambda c: app._profile(c, me, slug, agent_key))
    return ctx


class Head:
    def __init__(self, ctx, card, check=None):
        self.ctx, self.card, self.check = ctx, card, check

    def lease_lost(self):
        def validate(conn):
            governance.live(conn, self.ctx)
            governance.media_credentials(conn, self.ctx, self.card)
            story.authorize_card(conn, self.ctx.slug, self.card)
            if self.check:
                self.check(conn)
        governance.transaction(self.ctx, validate)
        return False

    def outbound_check(self, url):
        governance.check_destination(self.ctx, url)

    def outbound_timeout(self, seconds):
        return governance.remaining(self.ctx, min(15, seconds))

    def asset(self, task, url):
        self.lease_lost()
        import re
        match = re.fullmatch(r'/projects/api/' + re.escape(self.ctx.slug) + r'/assets/(pa_[a-f0-9]{32})', url)
        if not match:
            resources.bad('Quote references must be current production assets.')
        found = governance.transaction(self.ctx, lambda conn: repo.get_asset(conn, self.ctx.slug, match[1]))
        if not found:
            resources.bad('Quote reference is unavailable.')
        return found[1], found[0]


def health(factory, me, slug, body):
    app.fields(body, {'agent_key', 'kind', 'model'}, {'agent_key', 'kind'})
    ctx = context(factory, me, slug, body['agent_key'])
    governance.transaction(ctx, lambda c: resources.authorize(c, me, slug, admin=True))
    if body['kind'] in ('router', 'mcp'):
        from project_assistant import limb_worker
        model = body.get('model', 'ltx/ltx-2-5-pro')
        if not isinstance(model, str) or model not in comfy_router.MODELS:
            resources.bad('Select a verified Router model ID for discovery.')
        card = limb_worker.load_studio_card('router-' + model.split('/')[-1])
        if body['kind'] == 'mcp':
            return comfy_mcp.discover(ctx, card)
        return comfy_router.health(Head(ctx, card), model)
    if body['kind'] != 'llm':
        resources.bad('Health supports llm, router or discovery-only mcp.')
    from project_assistant.agent_runtime import provider_for
    profile = governance.transaction(ctx, lambda conn: governance.live(conn, ctx)['profile'])
    config = provider_for(profile)
    if config.kind != 'openai_compat':
        resources.bad('No health probe is available for this runtime; no CLI or login is launched.')
    destination = config.base_url.rstrip('/') + '/models'
    def validate(conn):
        binding = governance.live(conn, ctx, destination=destination)
        actual = provider_for(binding['profile'])
        governance.credential_binding(conn, ctx, binding['profile'], actual, binding['environment'])
        if actual != config:
            raise governance.AdmissionError('Provider changed during health check.')
    governance.transaction(ctx, validate)
    request = urllib.request.Request(destination, headers={'Authorization': 'Bearer ' + config.api_key} if config.api_key else {})
    try:
        with urllib.request.build_opener(comfy_router._NoRedirect).open(request, timeout=5) as response:
            raw = response.read(65537)
            if len(raw) > 65536:
                resources.bad('Health response exceeded the bounded read.')
            value = json.loads(raw)
        governance.transaction(ctx, validate)
        reachable = isinstance(value, dict) and isinstance(value.get('data'), list)
        return {'connection_state': 'reachable' if reachable else 'unavailable', 'generation_verified': False, 'billing_verified': False}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return {'connection_state': 'unavailable', 'generation_verified': False, 'billing_verified': False,
                'notice': 'Bounded catalog probe failed; provider errors and credentials are not echoed.'}


def quote(factory, me, slug, run_id, body):
    """Current owner's session + frozen allocation or exact Story form -> native quote."""
    app.fields(body, {'allocation_id', 'shot_id', 'appCode', 'kind', 'modelParams', 'promptOverride', 'referenceSourceVideoId'})
    if bool(body.get('allocation_id')) == bool(body.get('shot_id')):
        resources.bad('Select one owner-bound allocation or one exact shot form.')
    def load(conn):
        cp.own_run(conn, me, slug, run_id)
        tasks = db.tasks(conn, slug, run_id)
        if not tasks:
            resources.bad('Session has no agent task.')
        profile = app._profile(conn, me, slug, tasks[0]['target_agent_key'])
        if body.get('allocation_id'):
            saved = story.owned(conn, me, body['allocation_id'], 'allocation')
            if saved['slug'] != slug or saved.get('consumed'):
                resources.bad('Allocation is foreign or consumed; preview again.')
            ep = resources._episode(conn, slug, saved['episodeId'])
            items = story_allocation.current_shots(conn, ep, [a['shot_id'] for a in saved['plan']['allocations']])
            if saved['guards'] != story_allocation.source_guard(conn, items) or saved['options']['production_policy'] != story.production_policy(conn, slug):
                resources.bad('Allocation source or policy changed; preview again.')
            jobs = []
            for assignment in saved['plan']['allocations']:
                story_allocation.preflight_inputs(conn, slug, assignment['shot_id'], assignment, saved['cards'])
                for operation in governance.allocation_operations(assignment, saved['allocationId'] + ':' + assignment['shot_id'], saved['cards']):
                    card = operation['card']
                    if card['engine_config']['driver'] != 'comfy_router':
                        continue
                    if any(s.get('inputs') for branch in assignment.get('race_plans') or [assignment] for s in branch['stages'] if s['kind'] == 'generate' and s['card_id'] == card['card_id']):
                        resources.bad('Future Router references are unsupported. Persist and review the source, then preview/re-quote.')
                    _, row = story.find_row(conn, assignment['shot_id'], 'shot')
                    jobs.append((assignment['shot_id'], card, {'input': story.snapshot(conn, slug, row), 'production_policy': story.production_policy(conn, slug)}, {}))
        else:
            form = {k: v for k, v in body.items() if k != 'shot_id'}
            actual_slug, job = story.generation_job(conn, me, body['shot_id'], body.get('kind', 'video'), form)
            if actual_slug != slug or job['card']['engine_config']['driver'] != 'comfy_router':
                resources.bad('Select a Router form in this production.')
            jobs = [(body['shot_id'], job['card'], {'input': job['input'], 'production_policy': job['production_policy']}, job['values'])]
        if not jobs:
            resources.bad('Allocation has no hosted Router generation to quote.')
        for identifier, _, _, _ in jobs:
            _, row = story.find_row(conn, identifier, 'shot')
            scope = tasks[0]['request_scope']
            if scope and (row['tabKey'] != scope['target_tab'] or row['rid'] not in scope.get('row_ids', [])):
                resources.bad('Quote exceeds this session selected source scope.')
        for key in tasks[0]['input_snapshot']['tabs']:
            cp._task_source_matches(tasks[0], key, cp.freeze_tab(conn, slug, key))
        return profile, jobs
    temporary = tools.ToolContext(factory, slug, me, Path('.'), None)
    profile, jobs = governance.transaction(temporary, load)
    ctx = context(factory, me, slug, profile['agent_key'])
    results = []
    for identifier, card, task, values in jobs:
        stamp = story.digest(task['input'])
        def check(conn):
            cp.own_run(conn, me, slug, run_id)
            current = app._profile(conn, me, slug, profile['agent_key'])
            if current['version'] != profile['version'] or current.get('provider_binding') != profile.get('provider_binding'):
                resources.bad('Session agent configuration changed; start a fresh reviewed request.')
            _, row = story.find_row(conn, identifier, 'shot')
            if story.digest(story.snapshot(conn, slug, row)) != stamp or story.production_policy(conn, slug) != task['production_policy']:
                resources.bad('Quote source or policy changed; preview again.')
        head = Head(ctx, card, check)
        head.lease_lost()
        result = comfy_router.quote(ctx, task, card, values, head)
        results.append({'shot_id': identifier, 'appCode': card['card_id'], **result})
    return {'quotes': results, 'warning': app.WARNING, 'expires_in_seconds': 120, 'generation_admitted': False,
            'next_action': 'Dispatch the identical reviewed allocation/form before expiry. Expiry or restart requires explicit preview/re-quote, never paid auto replay.'}
