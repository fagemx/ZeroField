"""Short, atomic admission transactions; no inference or network under locks.

Reservations are application accounting, not a provider billing guarantee or OS
sandbox. Unknown local pricing stays unknown. Commercial adapters without a hard
request bound must pause, not infer a free call or reroute a reviewed allocation.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from dataclasses import dataclass
from types import SimpleNamespace
from decimal import Decimal, ROUND_CEILING
from urllib.parse import urlsplit

from project_assistant import agent_console_store as resources, orchestration_store as db
from project_assistant import orchestrator as cp, privacy, store


class AdmissionError(ValueError):
    pass


def transaction(ctx, action):
    conn = ctx.connection_factory()
    try:
        result = action(conn)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def live(conn, ctx, agent_key=None, destination=None):
    """Recheck original execution lease even when the caller is a grader/advisor."""
    resources.authorize(conn, ctx.me, ctx.slug, write=True)
    origin = getattr(ctx, 'governance_origin', ctx)
    if origin is not ctx:
        live(conn, origin)
    if origin is ctx and getattr(ctx, 'dispatch_id', None):
        cp.leased_dispatch(conn, ctx.worker_id, f'dsp_{ctx.dispatch_id}_{ctx.admission_no}', ctx.lease_token)
    elif origin is ctx and getattr(ctx, 'lease_owner', None) and getattr(ctx, 'message_id', None):
        message = store.message(conn, ctx.message_id)
        if not message or message['owner_id'] != str(ctx.me.actor_id) or message['status'] != 'running' or message['lease_owner'] != ctx.lease_owner or not message['lease_until'] or cp.instant(message['lease_until']) <= cp.now():
            raise AdmissionError('The original turn lease ended; no further dispatch is allowed.')
    if getattr(ctx, 'operation_deadline_at', None) and cp.instant(ctx.operation_deadline_at) <= cp.now():
        raise AdmissionError('Execution environment timeout expired.')
    if getattr(ctx, 'deadline_at', None) and cp.instant(ctx.deadline_at) <= cp.now():
        raise AdmissionError('The turn deadline expired.')
    if callable(getattr(ctx, 'authority_check', None)):
        ctx.authority_check(conn)
    key = agent_key or ctx.agent_key
    binding = resources.execution_resources(conn, ctx.me, ctx.slug, key, destination=destination)
    if getattr(ctx, 'episode_id', None):
        resources._episode(conn, ctx.slug, ctx.episode_id)
    if privacy.mode(conn, ctx.slug) == 'mask_numbers' and destination and not local_url(destination):
        raise AdmissionError('Numeric masking forbids commercial export.')
    return binding


def local_url(url):
    return urlsplit(url).hostname in ('127.0.0.1', 'localhost', '::1')


def session_key(ctx):
    return getattr(ctx, 'accounting_session_key', None) or ('run:' + str(ctx.run_id) if getattr(ctx, 'run_id', None) else
        'message:' + str(ctx.message_id) if getattr(ctx, 'message_id', None) else 'turn:' + str(id(ctx)))


def reserve(conn, ctx, *, request_key, agent_key, usage_kind, provider_name, model_name,
            ceiling=None, provenance='unknown', tier='open_weights', commercial=False, destination=None, queued=False, operation_digest=None):
    """Commit before outbound. Same identity never grants a second submission.

    Reserved-only expirations release capacity; submitted expirations retain their
    ceiling as uncertain spend until reconciliation. No paid auto retry is granted.
    """
    binding = live(conn, ctx, agent_key, destination)
    resources.text(request_key, 160, required=True)
    for identifier in (provider_name, model_name):
        if not isinstance(identifier,str) or not re.fullmatch(r'[a-zA-Z0-9_.:/-]{1,160}',identifier):
            raise AdmissionError('Invalid provider/model identifier for accounting.')
    if ceiling is not None:
        ceiling = resources.money(ceiling)
    if commercial and ceiling is None:
        raise AdmissionError('Needs You: configure a bounded provider price/token limit before commercial dispatch. Reviewed allocations are not silently downgraded.')
    cp.lock_project(conn, ctx.slug)
    existing = db.one(conn, 'SELECT to_jsonb(r) FROM projectops.agent_usage_reservation r WHERE project_slug=%s AND request_key=%s', (ctx.slug, request_key))
    if existing:
        raise AdmissionError('This outbound request was already admitted; reconcile its recorded outcome rather than submitting twice.')
    expired = db.many(conn, "SELECT request_key FROM projectops.agent_usage_reservation WHERE project_slug=%s AND state IN ('reserved','dispatched') AND lease_until<=NOW()", (ctx.slug,))
    for stale_key in expired:
        finalize(conn, ctx.slug, stale_key, outcome='unknown')
    settings = resources.get_settings(conn, ctx.me, ctx.slug)
    limits = settings['rate_limits']
    category = 'render' if usage_kind in ('image_gen', 'video_gen', 'frame_prep') else 'llm'
    active = db.one(conn, "SELECT count(*) FROM projectops.agent_usage_reservation WHERE project_slug=%s AND category=%s AND state IN ('reserved','dispatched','uncertain')", (ctx.slug, category))
    per_agent = db.one(conn, "SELECT count(*) FROM projectops.agent_usage_reservation WHERE project_slug=%s AND agent_key=%s AND state IN ('reserved','dispatched','uncertain')", (ctx.slug,agent_key))
    if not queued and per_agent >= binding['profile']['max_concurrency']:
        raise AdmissionError('Agent concurrency limit reached.')
    if not queued and active >= limits['max_concurrent_renders' if category == 'render' else 'max_concurrent_llm']:
        raise AdmissionError('Needs You: concurrent execution limit reached; retry only after the active request ends.')
    recent = db.one(conn, "SELECT count(*) FROM projectops.agent_usage_reservation WHERE project_slug=%s AND agent_key=%s AND started_at>NOW()-INTERVAL '1 minute'", (ctx.slug, agent_key))
    if not queued and recent >= limits['rpm_per_agent']:
        raise AdmissionError('Needs You: agent request rate limit reached.')
    if ceiling is not None:
        for clause, params, cap in (
            ("(COALESCE(started_at,created_at)>=date_trunc('month',NOW()) OR state IN ('queued','reserved','dispatched','uncertain'))", [], settings['spend_limit_monthly_usd']),
            ('session_key=%s', [session_key(ctx)], settings['spend_limit_session_usd']),
            ('episode_id=%s', [getattr(ctx, 'episode_id', None)], settings['spend_limit_episode_usd']),
        ):
            if clause == 'episode_id=%s' and params[0] is None:
                continue
            used = db.one(conn, "SELECT COALESCE(sum(accounted_cost_usd),0) FROM projectops.agent_usage_reservation WHERE project_slug=%s AND state<>'released' AND " + clause, [ctx.slug] + params)
            if Decimal(str(used)) + ceiling > Decimal(str(cap)):
                raise AdmissionError('Needs You: currency cap reached. Pause or explicitly create a new permitted open-weights allocation; no commercial fallback was dispatched.')
        custom = getattr(ctx, 'budget_cap_usd', None)
        if custom is not None:
            used = db.one(conn, "SELECT COALESCE(sum(accounted_cost_usd),0) FROM projectops.agent_usage_reservation WHERE project_slug=%s AND session_key=%s AND state<>'released'", (ctx.slug, session_key(ctx)))
            if Decimal(str(used)) + ceiling > resources.money(custom):
                raise AdmissionError('Needs You: deployment/session currency cap reached.')
    seconds = min(86400, binding['environment']['config'].get('timeout_seconds', 300))
    if getattr(ctx, 'deadline_at', None):
        seconds = max(1, min(seconds, (cp.instant(ctx.deadline_at)-cp.now()).total_seconds()))
    db.execute(conn, '''INSERT INTO projectops.agent_usage_reservation
        (project_slug,request_key,session_key,episode_id,run_id,owner_id,agent_key,usage_kind,category,
         provider_name,model_name,tier,ceiling_cost_usd,accounted_cost_usd,pricing_provenance,lease_until,state,operation_digest)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
        (ctx.slug, request_key, session_key(ctx), getattr(ctx, 'episode_id', None), getattr(ctx, 'run_id', None),
         ctx.me.actor_id, agent_key, usage_kind, category, provider_name, model_name, tier, ceiling, ceiling, provenance, cp.now()+dt.timedelta(seconds=seconds), 'queued' if queued else 'reserved', operation_digest))
    if getattr(ctx, 'budget_cap_usd', None) is not None:
        db.execute(conn,'UPDATE projectops.agent_usage_reservation SET session_cap_usd=%s WHERE project_slug=%s AND request_key=%s',(resources.money(ctx.budget_cap_usd),ctx.slug,request_key))
    return request_key


def dispatched(conn, slug, request_key):
    cp.lock_project(conn, slug)
    if db.one(conn, "UPDATE projectops.agent_usage_reservation SET state='dispatched',started_at=NOW() WHERE project_slug=%s AND request_key=%s AND state='reserved' AND lease_until>NOW() RETURNING request_key", (slug, request_key)) is None:
        raise AdmissionError('Reservation expired or was already submitted.')


def finalize(conn, slug, request_key, *, outcome, usage=None, estimated_cost=None, observed_cost=None, fingerprint=None, known_terminated=False):
    """Idempotent settlement, including after access/lease revocation. Never log errors.

    Provider-reported tokens are observations, configured-rate arithmetic remains an
    estimate. Missing metrics are not invented. Accepted/ambiguous effects retain the
    full reservation until an operator reconciles the provider, never free on cancel.
    """
    cp.lock_project(conn, slug)
    if fingerprint is not None and (not isinstance(fingerprint,str) or not re.fullmatch('[a-f0-9]{64}',fingerprint)):
        raise AdmissionError('Invalid operation fingerprint.')
    row = db.one(conn, 'SELECT to_jsonb(r) FROM projectops.agent_usage_reservation r WHERE project_slug=%s AND request_key=%s FOR UPDATE', (slug, request_key))
    if not row or row['state'] in ('finalized', 'released', 'uncertain'):
        return row
    if outcome not in ('succeeded', 'failed', 'canceled', 'unknown'):
        raise AdmissionError('Invalid execution outcome.')
    usage = usage or {}
    values = {n: usage.get(n, 0) for n in ('input_tokens', 'output_tokens', 'cached_tokens')}
    for n, v in values.items():
        resources.integer(v)
    if values['cached_tokens'] > values['input_tokens']:
        raise AdmissionError('Invalid provider cache usage.')
    if estimated_cost is not None:
        estimated_cost = resources.money(estimated_cost)
    if observed_cost is not None:
        observed_cost = resources.money(observed_cost)
    uncertain = outcome != 'succeeded' and not known_terminated and row['state'] in ('dispatched', 'uncertain')
    released = outcome != 'succeeded' and row['state'] in ('queued', 'reserved')
    cost = (None if released else row['ceiling_cost_usd'] if uncertain else
            observed_cost if observed_cost is not None else estimated_cost if estimated_cost is not None else row['ceiling_cost_usd'])
    state = 'released' if released else 'uncertain' if uncertain else 'finalized'
    db.execute(conn, 'UPDATE projectops.agent_usage_reservation SET state=%s,accounted_cost_usd=%s WHERE project_slug=%s AND request_key=%s', (state, cost, slug, request_key))
    db.execute(conn, '''INSERT INTO projectops.agent_usage_ledger
        (project_slug,event_key,session_key,episode_id,run_id,owner_id,agent_key,usage_kind,provider_name,model_name,tier,
         input_tokens,output_tokens,cached_tokens,estimated_cost_usd,observed_cost_usd,pricing_provenance,meta,fingerprint)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s) ON CONFLICT(project_slug,event_key) DO NOTHING''',
        (slug, request_key, row['session_key'], row['episode_id'], row['run_id'], row['owner_id'], row['agent_key'], row['usage_kind'], row['provider_name'], row['model_name'], row['tier'],
         values['input_tokens'], values['output_tokens'], values['cached_tokens'], cost, observed_cost, row['pricing_provenance'],
         json.dumps({'estimated': observed_cost is None, 'reservation_key': request_key, 'outcome': 'unknown' if uncertain else outcome, 'metrics_reported': bool(usage)}), fingerprint))
    return db.one(conn, 'SELECT to_jsonb(r) FROM projectops.agent_usage_reservation r WHERE project_slug=%s AND request_key=%s', (slug, request_key))


def normalized_usage(raw):
    raw = raw or {}
    values = {}
    for name, alias in (('input_tokens','prompt_tokens'),('output_tokens','completion_tokens'),('cached_tokens','cached_tokens')):
        value = raw.get(name, raw.get(alias))
        if name == 'cached_tokens' and value is None:
            value = (raw.get('prompt_tokens_details') or raw.get('input_tokens_details') or {}).get(name)
        if value is not None:
            resources.integer(value)
            values[name] = value
    if values.get('cached_tokens',0) > values.get('input_tokens',0):
        raise AdmissionError('Provider returned invalid cache counters.')
    return values


def price_bound(settings, config, payload):
    """Operator-maintained rates; UTF-8 byte ceiling for byte-tokenized models.

    Only explicitly attested byte-bounded models may use this estimate for hard
    admission. Vision requests have no such bound here and pause if commercial.
    """
    price = settings.get('model_pricing', {}).get(config.model)
    if not price:
        return None, None
    if price.get('base_url', config.base_url).rstrip('/') != model_destination(config).rstrip('/') or price.get('kind', config.kind) != config.kind:
        raise AdmissionError('Needs You: price configuration does not bind this provider endpoint.')
    text = json.dumps(payload, ensure_ascii=False)
    # shortcut: conservative vision markers can reject text mentions; replace with native vision pricing when supported.
    if 'image_url' in text or 'input_image' in text:
        if local_url(model_destination(config)):
            return None, None
        raise AdmissionError('Needs You: commercial vision pricing has no enforceable bound in this adapter.')
    size = len(text.encode('utf-8'))
    if size > price['max_input_tokens']:
        raise AdmissionError('Needs You: request exceeds the configured conservative input-token ceiling.')
    cost = (Decimal(price['max_input_tokens']) * Decimal(str(price['input_usd_per_million'])) + Decimal(price['max_output_tokens']) * Decimal(str(price['output_usd_per_million']))) / 1000000
    return cost.quantize(Decimal('.0001'), rounding=ROUND_CEILING), price


def model_destination(config):
    if config.kind == 'responses':
        from project_assistant import model_client
        return model_client.URL
    return config.base_url


class ProviderAdmission:
    def __init__(self, ctx, profile, config, kind='llm_turn', purpose=None):
        self.ctx, self.profile, self.config, self.kind = ctx, profile, config, kind
        self.active = None
        self.price = None
        self.ordinal = 0
        self.purpose = purpose or getattr(ctx, 'governance_phase', 'worker')
        self.destination = model_destination(config)

    def before(self, payload):
        from project_assistant.agent_runtime import provider_for
        def admit(conn):
            binding = live(conn, self.ctx, self.profile['agent_key'], self.destination)
            current = binding['profile']
            if 'max_cpu_seconds' in binding['environment']['config']:
                raise AdmissionError('Built-in HTTP inference cannot enforce provider/OS CPU quotas; use timeout_seconds or an externally constrained worker.')
            self.timeout_limit = min(binding['environment']['config'].get('timeout_seconds', 86400), binding['environment']['config'].get('max_cpu_seconds', 86400))
            self.response_limit = min(2*1024*1024, binding['environment']['config'].get('max_memory_mb', 2)*1024*1024)
            if len(json.dumps(payload, ensure_ascii=False).encode()) > self.response_limit:
                raise AdmissionError('Request exceeds the configured environment memory/transport limit.')
            actual = provider_for(current)
            credential_binding(conn, self.ctx, current, actual, binding['environment'])
            if actual != self.config:
                raise AdmissionError('Provider or credential changed; start a new authorized turn.')
            ceiling, self.price = price_bound(resources.get_settings(conn, self.ctx.me, self.ctx.slug), self.config, payload)
            if self.price:
                payload['max_completion_tokens' if self.config.kind == 'openai_compat' else 'max_output_tokens'] = self.price['max_output_tokens']
            self.ordinal += 1
            origin = getattr(self.ctx, 'governance_origin', self.ctx)
            execution_key = getattr(origin,'execution_key',None) or (None if getattr(origin,'dispatch_id',None) or getattr(origin,'message_id',None) else 'turn:' + str(id(origin)))
            request_key = 'call:' + cp.digest([session_key(self.ctx), execution_key, getattr(origin,'dispatch_id', None), getattr(origin,'admission_no', None), getattr(origin,'message_id', None), self.profile['agent_key'], self.purpose, self.ordinal])
            reserve(conn, self.ctx, request_key=request_key, agent_key=current['agent_key'], usage_kind=self.kind,
                provider_name=self.config.kind, model_name=self.config.model, ceiling=ceiling,
                provenance='configured_byte_token_ceiling' if self.price else 'unknown',
                commercial=not local_url(self.destination), destination=self.destination,
                tier='open_weights' if local_url(self.destination) else 'closed_flagship')
            dispatched(conn, self.ctx.slug, request_key)
            return request_key
        self.active = transaction(self.ctx, admit)

    def after(self, usage, outcome='succeeded'):
        if self.active is None:
            return
        usage = normalized_usage(usage)
        cost = None
        if self.price and usage and 'input_tokens' in usage and 'output_tokens' in usage:
            cost = ((Decimal(usage['input_tokens']) * Decimal(str(self.price['input_usd_per_million'])) + Decimal(usage['output_tokens']) * Decimal(str(self.price['output_usd_per_million']))) / 1000000).quantize(Decimal('.0001'), rounding=ROUND_CEILING)
        transaction(self.ctx, lambda conn: finalize(conn, self.ctx.slug, self.active, outcome=outcome, usage=usage, estimated_cost=cost))
        self.active = None
        if outcome == 'succeeded':
            transaction(self.ctx, lambda conn: live(conn, self.ctx, self.profile['agent_key'], self.destination))


def install(ctx):
    if not getattr(ctx, 'accounting_session_key', None):
        ctx.accounting_session_key = session_key(ctx)
    if not getattr(ctx, 'execution_guard', None):
        ctx.execution_guard = execution_guard
    if not getattr(ctx, 'runtime_cost_hook', None):
        ctx.runtime_cost_hook = cost_hook


def cost_hook(ctx, conn, kind, payload):
    # Advisor inference is accounted at each actual provider round, not twice here.
    live(conn, ctx, payload['profile']['agent_key'] if kind == 'advisor_result' else payload['agent_key'])


def execution_guard(ctx, conn, kind, payload):
    live(conn, ctx)
    if kind == 'media_dispatch':
        for allocation in payload['plan']['allocations']:
            for operation in allocation_operations(allocation, payload['allocationId'] + ':' + allocation['shot_id'], payload['cards']):
                prepare_operation(conn, ctx, **operation)
    elif kind != 'film_export':
        raise AdmissionError('Unsupported execution admission.')


_QUOTE_PROVIDERS = {}
_QUOTE_PROOF = object()


@dataclass(frozen=True)
class TrustedQuote:
    amount_usd: Decimal
    operation_digest: str
    expires_at: object
    provenance: str
    hard_bound: bool
    _proof: object


def trusted_quote(*, amount_usd, operation_digest, expires_at, provenance, hard_bound=False):
    """Trusted adapter only, after verifying a quote for these exact frozen inputs.

    An estimate cannot bound a hard cap: attest a fixed/max-charge contract. This
    in-process object is not a JSON schema, approval or an execution principal.
    """
    if not isinstance(provenance,str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,160}',provenance):
        raise AdmissionError('Quote provenance must be a semantic source identifier, not an error or URL.')
    return TrustedQuote(resources.money(amount_usd), operation_digest, cp.instant(expires_at),
                        resources.text(provenance, 160, required=True), hard_bound is True, _QUOTE_PROOF)


def register_quote_provider(driver, resolver):
    """Trusted resolver(card,digest)->TrustedQuote|None; no DB/network under locks.

    Obtain /price outside transactions, cache against exact frozen inputs, and
    return a still-current bound. This is deployment code, never a request field.
    """
    _QUOTE_PROVIDERS[driver] = resolver


def media_destination(card):
    from project_assistant import limb_worker
    config = card['engine_config']
    driver = limb_worker.card_execution_profile(card)['driver']
    if driver in ('comfy_local', 'comfy_partner'):
        platform = config.get('platform') or os.environ.get('COMFY_PLATFORM') or ('comfy_sdk' if os.environ.get('COMFY_API_KEY') else 'local')
        return config.get('base_url') or os.environ.get('COMFY_BASE_URL') or ('http://127.0.0.1:8188' if platform == 'local' else 'https://cloud.comfy.org')
    return os.environ.get(config.get('base_url_env', ''), '')


def generation_admit(conn, ctx, operations):
    """Project-wide all-or-none generation admissions, not successful renders.

    Never auto-refund admissions/ambiguous acceptance. Read/price/chat/grader/prep/
    cache hits do not call this. Replay is not authority to execute a second time.
    """
    cp.lock_project(conn, ctx.slug)
    resources.authorize(conn, ctx.me, ctx.slug, write=True)
    if not isinstance(operations, list) or not 1 <= len(operations) <= 1000 or len({o[0] for o in operations}) != len(operations):
        raise AdmissionError('Invalid generation batch.')
    new, upgrades = [], []
    for key, digest in operations:
        resources.text(key, 160, required=True)
        if not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}',digest):
            raise AdmissionError('Invalid operation digest.')
        old = db.one(conn, 'SELECT to_jsonb(a) FROM projectops.agent_generation_admission a WHERE project_slug=%s AND operation_key=%s', (ctx.slug, key))
        if old and (old['owner_id'] != str(ctx.me.actor_id) or old['operation_digest'] != digest):
            raise AdmissionError('Generation identity conflicts with the original admission.')
        if not old:
            new.append((key, digest))
        elif not old['protected']:
            upgrades.append(key)
    settings = resources.get_settings(conn, ctx.me, ctx.slug)
    protected = settings['judge_trial_mode']
    needed = len(new) + len(upgrades)
    if protected and settings['judge_trial_used_runs'] + needed > settings['judge_trial_cap_runs']:
        raise AdmissionError('Needs You: Judge Live-Link generation cap reached; no batch item was submitted.')
    for key, digest in new:
        db.execute(conn, 'INSERT INTO projectops.agent_generation_admission(project_slug,operation_key,owner_id,operation_digest,protected) VALUES(%s,%s,%s,%s,%s)', (ctx.slug,key,ctx.me.actor_id,digest,protected))
    if protected:
        for key in upgrades:
            db.execute(conn, 'UPDATE projectops.agent_generation_admission SET protected=TRUE WHERE project_slug=%s AND operation_key=%s', (ctx.slug,key))
        if needed:
            db.execute(conn, 'UPDATE projectops.agent_console_settings SET judge_trial_used_runs=judge_trial_used_runs+%s WHERE project_slug=%s', (needed,ctx.slug))
    return len(new)


def allocation_operations(allocation, prefix, cards=None):
    from project_assistant import limb_worker
    result = []
    for index, branch in enumerate(allocation.get('race_plans') or [allocation]):
        for step in branch['stages']:
            if step['kind'] != 'generate':
                continue
            name = ('branch' + str(index) + ':' if allocation.get('race_plans') else '') + step['step_id']
            card = step.get('card') or (cards[step['card_id']][0] if cards else limb_worker._resolve_openapi_card_and_workflow(step['card_id'])[0])
            result.append(dict(request_key=prefix + ':' + name, card=card,
                operation_digest=cp.digest({'prefix':prefix,'name':name,'step':step,'card':card})))
    return result


def prepare_operation(conn, ctx, *, request_key, card, operation_digest):
    """Reserve frozen generation currency and Judge admission before scheduling."""
    from project_assistant import limb_worker
    from project_docs import story_openapi as story
    story.authorize_card(conn, ctx.slug, card)
    profile = limb_worker.card_execution_profile(card)
    destination = media_destination(card)
    live(conn, ctx, destination=destination)
    media_credentials(conn, ctx, card)
    old = db.one(conn, 'SELECT to_jsonb(r) FROM projectops.agent_usage_reservation r WHERE project_slug=%s AND request_key=%s', (ctx.slug,request_key))
    if old:
        if old['operation_digest'] != operation_digest or old['owner_id'] != str(ctx.me.actor_id):
            raise AdmissionError('Media reservation identity changed.')
        return
    quote = _QUOTE_PROVIDERS.get(profile['driver'], lambda *_:None)(card, operation_digest)
    if quote is not None and (not isinstance(quote, TrustedQuote) or quote._proof is not _QUOTE_PROOF or quote.operation_digest != operation_digest or quote.expires_at <= cp.now()):
        raise AdmissionError('Media quote expired or does not match the frozen operation.')
    commercial = profile['driver'] != 'comfy_local' or not local_url(destination)
    if commercial and (quote is None or not quote.hard_bound):
        raise AdmissionError('Needs You: configure a verified fixed/max-charge media quote before commercial dispatch. No reviewed allocation was silently downgraded.')
    reserve(conn, ctx, request_key=request_key, agent_key=ctx.agent_key, usage_kind=card['output_mode']+'_gen',
        provider_name=profile['driver'], model_name=card['card_id'], ceiling=quote.amount_usd if quote else None,
        provenance=quote.provenance if quote else 'unknown_local_hardware', tier='open_weights' if not commercial else 'closed_flagship',
        commercial=commercial, destination=destination, queued=True, operation_digest=operation_digest)
    if quote:
        db.execute(conn, 'UPDATE projectops.agent_usage_reservation SET quote_expires_at=%s WHERE project_slug=%s AND request_key=%s', (quote.expires_at,ctx.slug,request_key))
    generation_admit(conn, ctx, [(request_key,operation_digest)])


def begin_operation(conn, ctx, request_key, *, card=None):
    cp.lock_project(conn, ctx.slug)
    limits = live(conn, ctx, destination=media_destination(card) if card else None)['environment']['config']
    if 'max_memory_mb' in limits or 'max_cpu_seconds' in limits:
        raise AdmissionError('This media runtime cannot enforce OS CPU/memory quotas; choose an externally constrained worker or remove unsupported quotas.')
    if 'timeout_seconds' in limits:
        ctx.operation_deadline_at = (cp.now()+dt.timedelta(seconds=limits['timeout_seconds'])).isoformat()
    row = db.one(conn, 'SELECT to_jsonb(r) FROM projectops.agent_usage_reservation r WHERE project_slug=%s AND request_key=%s', (ctx.slug, request_key))
    if not row or row['state'] not in ('queued','reserved') or row['owner_id'] != str(ctx.me.actor_id):
        raise AdmissionError('Media operation already executed or reservation unavailable; reconcile before retry.')
    if row['quote_expires_at'] and cp.instant(row['quote_expires_at']) <= cp.now():
        raise AdmissionError('Needs You: media quote expired before dispatch; obtain a new reviewed request.')
    if card:
        from project_docs import story_openapi as story
        story.authorize_card(conn, ctx.slug, card)
        media_credentials(conn, ctx, card)
    settings = resources.get_settings(conn, ctx.me, ctx.slug)
    if settings['judge_trial_mode'] and card:
        queued = db.many(conn, "SELECT jsonb_build_array(request_key,operation_digest) FROM projectops.agent_usage_reservation WHERE project_slug=%s AND session_key=%s AND state='queued' AND operation_digest IS NOT NULL", (ctx.slug,row['session_key']))
        generation_admit(conn,ctx,queued or [(request_key,row['operation_digest'])])
    if card and (row['model_name'] != card['card_id'] or row['provider_name'] != card['engine_config']['driver']):
        raise AdmissionError('Frozen media operation no longer matches its reservation.')
    for clause, params, cap in (("(COALESCE(started_at,created_at)>=date_trunc('month',NOW()) OR state IN ('queued','reserved','dispatched','uncertain'))",[],settings['spend_limit_monthly_usd']),
        ('session_key=%s',[row['session_key']],settings['spend_limit_session_usd']),('episode_id=%s',[row['episode_id']],settings['spend_limit_episode_usd'])):
        total = db.one(conn,"SELECT COALESCE(sum(accounted_cost_usd),0) FROM projectops.agent_usage_reservation WHERE project_slug=%s AND state<>'released' AND "+clause,[ctx.slug]+params)
        if Decimal(str(total)) > Decimal(str(cap)):
            raise AdmissionError('Currency cap was reduced; dispatch paused.')
    if row['session_cap_usd'] is not None:
        total = db.one(conn,"SELECT COALESCE(sum(accounted_cost_usd),0) FROM projectops.agent_usage_reservation WHERE project_slug=%s AND session_key=%s AND state<>'released'",(ctx.slug,row['session_key']))
        cap = min(Decimal(str(row['session_cap_usd'])),resources.money(getattr(ctx,'budget_cap_usd',row['session_cap_usd'])))
        if total > cap:
            raise AdmissionError('Session/deployment currency cap reached.')
    active = db.one(conn, "SELECT count(*) FROM projectops.agent_usage_reservation WHERE project_slug=%s AND category=%s AND state IN ('dispatched','uncertain')", (ctx.slug,row['category']))
    per_agent = db.one(conn, "SELECT count(*) FROM projectops.agent_usage_reservation WHERE project_slug=%s AND agent_key=%s AND state IN ('dispatched','uncertain')", (ctx.slug,row['agent_key']))
    if per_agent >= live(conn,ctx)['profile']['max_concurrency']:
        raise AdmissionError('Agent concurrency limit reached.')
    if active >= settings['rate_limits']['max_concurrent_renders' if row['category']=='render' else 'max_concurrent_llm']:
        raise AdmissionError('Execution concurrency limit reached.')
    recent = db.one(conn, "SELECT count(*) FROM projectops.agent_usage_reservation WHERE project_slug=%s AND agent_key=%s AND state<>'queued' AND started_at>NOW()-INTERVAL '1 minute'", (ctx.slug,row['agent_key']))
    if recent >= settings['rate_limits']['rpm_per_agent']:
        raise AdmissionError('Agent rate limit reached.')
    db.execute(conn, "UPDATE projectops.agent_usage_reservation SET state='dispatched',started_at=NOW(),lease_until=%s WHERE project_slug=%s AND request_key=%s", (cp.now()+dt.timedelta(minutes=30),ctx.slug,request_key))


def media_context(me, slug, *, agent_key='coordinator', **fields):
    from project_docs import http
    return SimpleNamespace(connection_factory=http.open_connection, me=me, slug=slug, agent_key=agent_key, **fields)


def run_operation(ctx, request_key, action, *, card=None, model_name='ffmpeg', fingerprint=None):
    """Actual media/prep boundary; caller's M8/Story authority_check stays live."""
    def begin(conn):
        if card is None:
            limits = live(conn, ctx)['environment']['config']
            if 'max_memory_mb' in limits or 'max_cpu_seconds' in limits:
                raise AdmissionError('Local preparation cannot enforce OS CPU/memory quotas; use an externally constrained worker or remove unsupported quotas.')
            if 'timeout_seconds' in limits:
                ctx.operation_deadline_at = (cp.now()+dt.timedelta(seconds=limits['timeout_seconds'])).isoformat()
            reserve(conn, ctx, request_key=request_key, agent_key=ctx.agent_key, usage_kind='frame_prep', provider_name='local', model_name=model_name, provenance='unknown_local_hardware')
            dispatched(conn, ctx.slug, request_key)
        else:
            begin_operation(conn, ctx, request_key, card=card)
    try:
        transaction(ctx, begin)
    except Exception:
        transaction(ctx, lambda conn: release_unstarted(conn, ctx.slug, [request_key]))
        ctx.operation_deadline_at = None
        raise
    try:
        result = action()
        transaction(ctx, lambda conn: live(conn, ctx, destination=media_destination(card) if card else None))
    except Exception:
        transaction(ctx, lambda conn: finalize(conn, ctx.slug, request_key, outcome='unknown' if card else 'failed',fingerprint=fingerprint,known_terminated=card is None))
        ctx.operation_deadline_at = None
        raise
    transaction(ctx, lambda conn: finalize(conn, ctx.slug, request_key, outcome='succeeded',fingerprint=fingerprint))
    ctx.operation_deadline_at = None
    return result


def media_credentials(conn, ctx, card):
    config = card['engine_config']
    if any(config.get(n) for n in ('api_key', 'token', 'authorization')):
        raise AdmissionError('Governed media accepts allowlisted credential references only.')
    names = [config.get('api_key_env')]
    if config.get('driver') in ('comfy_local', 'comfy_partner'):
        names += [name for name in ('COMFY_API_KEY','COMFY_ROUTER_TOKEN') if os.environ.get(name)]
    allowed = {n.strip() for n in os.environ.get('OPENBENCH_AGENT_KEY_ENVS','').split(',') if n.strip()}
    environment = live(conn, ctx)['environment']
    platform = config.get('platform') or os.environ.get('COMFY_PLATFORM') or ('comfy_sdk' if os.environ.get('COMFY_API_KEY') else 'local')
    if config.get('driver') in ('comfy_local','comfy_partner') and platform == 'comfy_sdk' and environment['network_access'] != 'full':
        raise AdmissionError('SDK internal output networking requires an explicitly full-network environment; host-restricted deployments must use a bounded HTTP adapter.')
    for name in filter(None,names):
        if os.environ.get(name) and name not in allowed:
            raise AdmissionError('Media credential reference was revoked from the deployment allowlist.')
        if 'vault_keys' in environment['config'] and os.environ.get(name):
            refs = [resources._get(conn,'vault',ctx.slug,key) for key in environment['config']['vault_keys']]
            if not any(r and r['enabled'] and ctx.agent_key in r['allowed_agent_keys'] and r['provider_config'].get('api_key_env')==name and r['provider_config'].get('base_url') in (None,media_destination(card)) for r in refs):
                raise AdmissionError('Environment credential mounts deny this media reference.')


def check_destination(ctx, url):
    # Signed query strings stay in memory and never enter settings/errors/ledger.
    parsed = urlsplit(url)
    destination = parsed._replace(query='',fragment='').geturl()
    transaction(ctx, lambda conn: live(conn, ctx, destination=destination))


def remaining(ctx, requested=86400):
    deadlines = [cp.instant(getattr(ctx,n)) for n in ('deadline_at','operation_deadline_at') if getattr(ctx,n,None)]
    return max(.1,min([requested]+[(d-cp.now()).total_seconds() for d in deadlines]))


def lease_ended(ctx):
    try:
        transaction(ctx, lambda conn: live(conn, ctx))
        return False
    except Exception:
        return True


def credential_binding(conn, ctx, profile, config, environment):
    if 'vault_keys' not in environment['config'] or (not config.api_key and config.kind != 'responses'):
        return
    reference_name = profile.get('provider_config',{}).get('api_key_env')
    if not reference_name:
        raise AdmissionError('Environment credential mounts require an explicit allowlisted provider reference; implicit global/OAuth credentials are not mounted.')
    refs = [resources._get(conn,'vault',ctx.slug,key) for key in environment['config']['vault_keys']]
    for reference in refs:
        if not reference or not reference['enabled'] or profile['agent_key'] not in reference['allowed_agent_keys']:
            continue
        provider = reference['provider_config']
        if provider.get('api_key_env') == reference_name and all(provider.get(field) in (None,getattr(config,field)) for field in ('kind','base_url','model')):
            return
    raise AdmissionError('Current credential mounts deny this provider endpoint/model.')


def release_unstarted(conn, slug, keys):
    for key in set(keys):
        state=db.one(conn,'SELECT state FROM projectops.agent_usage_reservation WHERE project_slug=%s AND request_key=%s',(slug,key))
        if state in ('queued','reserved'):
            finalize(conn,slug,key,outcome='canceled')


def release_run_operations(conn, slug, run_id):
    keys=[key for task in db.tasks(conn,slug,run_id) for key in task['input_snapshot'].get('story_media',{}).get('operation_keys',{}).values()]
    release_unstarted(conn,slug,keys)
