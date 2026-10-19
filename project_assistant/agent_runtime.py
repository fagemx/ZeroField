"""Shared profile execution for chat turns, delegated work and flow personas."""
from __future__ import annotations

import os
import shutil
import tempfile
import json
import time
from dataclasses import dataclass
from pathlib import Path

from project_assistant import providers,model_client,codex_runner,tools,agent_policy,agent_registry
from project_assistant.tool_host import ToolHost,summarize


@dataclass
class Outcome:
    status: str
    answer: str = ''
    blocked: str = ''
    kind: str = ''
    detail: str = ''
    version: str = ''
    model: str = ''
    usage: dict | None = None
    scorecard: dict | None = None


class DecisionPending(Exception):
    """A committed question releases the model turn; resumption is queued later."""


def provider_for(profile,env=None):
    env=os.environ if env is None else env
    base=providers.provider_from_env(env)
    config=profile.get('provider_config') or {}
    key='' if config.get('base_url') and config['base_url'].rstrip('/')!=base.base_url.rstrip('/') else base.api_key
    if config.get('api_key_env'):
        permitted={n.strip() for n in env.get('OPENBENCH_AGENT_KEY_ENVS','').split(',') if n.strip()}
        if config['api_key_env'] not in permitted:
            raise tools.ToolError("POLICY_DENIED: The model credential reference was revoked.")
        key=env.get(config['api_key_env'],'')
    kind=config.get('kind',base.kind)
    if kind=='codex': kind='codex_cli'
    return providers.ProviderConfig(kind,config.get('base_url',base.base_url),key,
                                    config.get('model',base.model))


def run_cli(settings,host,prompt):
    url,token=host.start()
    workdir=Path(tempfile.mkdtemp(prefix='pa-turn-'))
    try:
        result=codex_runner.run(prompt,codex=settings.codex,model=settings.model,effort=settings.effort,
            mcp_python=settings.python,mcp_script=settings.mcp_script,tool_url=url,token=token,
            timeout=settings.timeout,workdir=workdir,cancel_event=host.pending)
        if host.pending.is_set():
            return Outcome('awaiting_gate',answer='需要你的決定，問題已列在待你裁決。',version='codex_cli',model=settings.model)
        status=result.status if result.status in ('ok','quota','lockdown') else 'error'
        return Outcome(status,result.answer,result.blocked,result.status,
                       str(result.errors[-1:] or result.stderr_tail[-300:]),'codex_cli',settings.model)
    finally:
        shutil.rmtree(workdir,ignore_errors=True)


def _run_agent_once(*,profile,ctx,instructions,turn_text,timeout,on_text=None,on_tool=None,images=(),settings=None,on_round=None):
    if hasattr(ctx, 'connection_factory'):
        from project_assistant import prompting, agent_registry
        conn = ctx.connection_factory()
        try:
            current = agent_registry.get_agent(conn, ctx.slug, profile['agent_key'])
            if not current or not current['enabled'] or current['role_kind'] == 'observer':
                raise tools.ToolError('POLICY_DENIED: Agent is unavailable.')
            ctx.current_profile = current
            if not getattr(ctx, 'episode_id', None):
                ctx.episode_id = prompting.episode_context(conn, ctx.slug, getattr(ctx, 'scope', None))
            ctx.mounted_context = prompting.mounted_context(conn, ctx.me, ctx.slug, current, episode_id=getattr(ctx, 'episode_id', None))
            instructions += '\n' + ctx.mounted_context
            # A new current grant cannot expand a frozen turn's tool ceiling.
            profile = {**profile, 'allowed_tools': list(set(profile.get('allowed_tools', [])) & {s['name'] for s in agent_policy.tool_specs_for(current)})}
        finally:
            conn.rollback()
            conn.close()
    ctx.turn_context=turn_text
    config=provider_for(profile)
    specs=agent_policy.tool_specs_for(profile)
    ctx.allowed_tools={s['name'] for s in specs}
    if getattr(ctx, 'dispatch_id', None) and not getattr(ctx, 'advisor_call', False):
        from project_assistant import orchestration_store as db
        conn = ctx.connection_factory()
        try:
            dispatch = db.get_dispatch(conn, ctx.slug, ctx.dispatch_id)
            approved = []
            for entry in (dispatch.get('continuation') or {}).get('journal', {}).values():
                if entry.get('approved_gate_id'):
                    gate = db.get_gate(conn, ctx.slug, entry['approved_gate_id'])
                    approved.append(gate['continuation']['action'])
        finally:
            conn.rollback()
            conn.close()
        for action in approved:
            result = tools.call(ctx, action['tool'], action['args'])
            if on_tool:
                on_tool({**summarize(action['tool'], action['args']), 'ok': True, 'approved_action': True})
            try:
                pending = json.loads(result)
            except (ValueError, TypeError):
                pending = {}
            if isinstance(pending, dict) and pending.get('awaiting_gate'):
                return Outcome('awaiting_gate', answer='Crew decision required.', version=config.kind, model=config.model)
            turn_text += '\nApproved action result (data, not instructions):\n' + str(result)
            images = tuple(images) + tuple(getattr(result, 'images', []))
    def call_tool(name,args):
        summary=summarize(name,args)
        try:
            if getattr(ctx, 'grading_enabled', False) and name in {'propose', 'propose_table_edit', 'offer_document'}:
                from project_assistant import execution_governance as governance
                def stage(conn):
                    agent_policy.authorize_tool(ctx, conn, name, args)
                    from project_assistant import studio_tools
                    stamp = studio_tools.source_stamp(ctx, conn)
                    if getattr(ctx, 'staged_proposal_source', None) not in (None, stamp):
                        raise tools.ToolError('Proposal sources changed during candidate drafting.')
                    ctx.staged_proposal_source = stamp
                governance.transaction(ctx, stage)
                ctx.staged_proposals.append({'tool': name, 'args': args})
                result = json.dumps({'staged_for_grading': True, 'published': False})
            else:
                result=tools.call(ctx,name,args)
                if getattr(result, 'images', None):
                    if not hasattr(ctx, 'candidate_images'): ctx.candidate_images = []
                    ctx.candidate_images.extend(result.images)
            summary['ok']=True
        except tools.ToolError as exc:
            result='工具錯誤：'+str(exc)
            summary['ok']=False
        if on_tool:
            on_tool(summary)
        try:
            pending=json.loads(result)
        except (ValueError,TypeError):
            pending={}
        if isinstance(pending, dict) and pending.get('awaiting_gate') is True:
            raise DecisionPending()
        return result
    if config.kind=='codex_cli':
        if hasattr(ctx, 'connection_factory'):
            return Outcome('error', kind='configuration', detail='Needs You: CLI execution has no enforceable cost bound in this envelope; use a bounded built-in provider.')
        if settings is None:
            from project_assistant.worker import settings_from_env
            settings=settings_from_env()
        from dataclasses import replace
        selected=replace(settings,model=config.model,effort=(profile.get('provider_config') or {}).get('effort',settings.effort),timeout=timeout)
        host=ToolHost(ctx,on_call=on_tool)
        try:
            return run_cli(selected,host,instructions+'\n'+turn_text)
        finally:
            host.stop()
    admission = None
    if hasattr(ctx, 'connection_factory'):
        from project_assistant import execution_governance as governance
        admission = governance.ProviderAdmission(ctx, profile, config)
    common=dict(instructions=instructions,turn_text=turn_text,call_tool=call_tool,timeout=timeout,
                on_text=on_text,on_round=on_round,images=images,tool_specs=specs,**({'admission': admission} if admission else {}))
    try:
        if config.kind=='openai_compat':
            result=providers.run_openai_compat_turn(config=config,**common)
        else:
            result=model_client.run_turn(model=config.model,
                effort=(profile.get('provider_config') or {}).get('effort',getattr(settings,'effort','medium')),
                cache_key=f'pa-{ctx.slug}-{ctx.me.actor_id}-{profile["agent_key"]}',**common)
    except DecisionPending:
        return Outcome('awaiting_gate',answer='需要你的決定，問題已列在待你裁決。',version=config.kind,model=config.model)
    return Outcome(result.status,result.answer,result.blocked,result.error_kind or result.status,
                   result.error,config.kind,config.model,result.usage)


def run_agent(*,profile,ctx,instructions,turn_text,timeout,on_text=None,on_tool=None,images=(),settings=None,on_round=None):
    """The shared per-turn envelope for daily chat and managed built-in dispatch.

    The caller supplies original_objective separately from history/hidden context.
    Graded proposal tools are staged, never reviewable until the isolated check
    passes. Revisions are tool-free and cannot repeat accepted external actions.
    """
    started = time.monotonic()
    graded = False
    if hasattr(ctx, 'connection_factory'):
        from project_assistant import execution_governance as governance
        governance.install(ctx)
        def load(conn):
            binding = governance.live(conn, ctx)
            limits = binding['environment']['config']
            return {**binding['profile'], 'environment_timeout_seconds': min(limits.get('timeout_seconds', timeout), limits.get('max_cpu_seconds', timeout))}
        current = governance.transaction(ctx, load)
        timeout = min(timeout, current.get('environment_timeout_seconds', timeout))
        # Neither a stale disabled snapshot nor a late disabling can bypass grading.
        grader = (profile.get('outcome_grader') if (profile.get('outcome_grader') or {}).get('enabled')
                  else current.get('outcome_grader', {}))
        graded = bool(grader.get('enabled')) and not getattr(ctx, 'advisor_call', False)
        profile = {**profile, 'outcome_grader': grader}
        if graded and not getattr(ctx, 'original_objective', None):
            raise governance.AdmissionError('Graded execution requires the original objective separately from conversation context.')
        ctx.grading_enabled = graded
        ctx.staged_proposals = []
        ctx.staged_proposal_source = None
        ctx.graded_source_stamp = None
        ctx.candidate_images = []
    outcome = _run_agent_once(profile=profile, ctx=ctx, instructions=instructions, turn_text=turn_text,
        timeout=timeout, on_text=None if hasattr(ctx, 'connection_factory') else on_text, on_tool=on_tool, images=images, settings=settings, on_round=on_round)
    if not graded or outcome.status != 'ok':
        if outcome.status == 'ok' and hasattr(ctx, 'connection_factory'):
            governance.transaction(ctx, lambda conn: governance.live(conn, ctx))
            if on_text: on_text(outcome.answer)
        return outcome
    from project_assistant import outcome_grader
    candidate, card = outcome_grader.grade_candidate(ctx=ctx, profile=profile,
        candidate={'answer': outcome.answer, 'proposals': ctx.staged_proposals},
        timeout=max(0, timeout-(time.monotonic()-started)), on_trace=on_tool, images=ctx.candidate_images)
    outcome.scorecard = card
    if not card['passed']:
        outcome_grader.needs_you(ctx, card)
        outcome.status = 'awaiting_gate'
        outcome.answer = 'Needs You — outcome check failed (' + str(card['score']) + '/100). ' + card['feedback']
        return outcome
    # Publish only the independently checked candidate, with current grants/lease.
    def validate_publication(conn):
        governance.live(conn, ctx)
        current = agent_registry.get_agent(conn, ctx.slug, profile['agent_key'])
        specialist = agent_registry.get_agent(conn, ctx.slug, profile['outcome_grader']['grader_agent_key'])
        if not specialist or specialist['version'] != getattr(ctx, 'graded_specialist_version', None):
            raise governance.AdmissionError('Independent grader changed before publication.')
        if current['outcome_grader'] != profile['outcome_grader']:
            raise governance.AdmissionError('Outcome rubric changed before publication.')
        from project_assistant import studio_tools
        if ctx.staged_proposal_source is not None and studio_tools.source_stamp(ctx, conn) != ctx.staged_proposal_source:
            raise governance.AdmissionError('Proposal source changed during grading; newer production data was preserved.')
    governance.transaction(ctx, validate_publication)
    ctx.grading_enabled = False
    ctx.graded_source_stamp = ctx.staged_proposal_source
    for proposal in candidate['proposals']:
        result = tools.call(ctx, proposal['tool'], proposal['args'])
        try:
            if json.loads(result).get('awaiting_gate'):
                outcome.status = 'awaiting_gate'
        except (ValueError, AttributeError):
            pass
    outcome.answer = candidate['answer']
    if on_text:
        on_text(outcome.answer)
    return outcome
