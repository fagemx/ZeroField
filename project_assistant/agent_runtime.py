"""Shared profile execution for chat turns, delegated work and flow personas."""
from __future__ import annotations

import os
import shutil
import tempfile
import json
from dataclasses import dataclass
from pathlib import Path

from project_assistant import providers,model_client,codex_runner,tools,agent_policy
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
            raise tools.ToolError('POLICY_DENIED：模型憑證參照已撤銷')
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


def run_agent(*,profile,ctx,instructions,turn_text,timeout,on_text=None,on_tool=None,images=(),settings=None,on_round=None):
    ctx.turn_context=turn_text
    config=provider_for(profile)
    specs=agent_policy.tool_specs_for(profile)
    ctx.allowed_tools={s['name'] for s in specs}
    def call_tool(name,args):
        summary=summarize(name,args)
        try:
            result=tools.call(ctx,name,args)
            summary['ok']=True
        except tools.ToolError as exc:
            result='工具錯誤：'+str(exc)
            summary['ok']=False
        if on_tool:
            on_tool(summary)
        if name in ('ask_decision_gate','trigger_flow_run'):
            try:
                pending=json.loads(result)
            except (ValueError,TypeError):
                pending={}
            if pending.get('awaiting_gate') is True:
                raise DecisionPending()
        return result
    if config.kind=='codex_cli':
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
    common=dict(instructions=instructions,turn_text=turn_text,call_tool=call_tool,timeout=timeout,
                on_text=on_text,on_round=on_round,images=images,tool_specs=specs)
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
                   result.error,config.kind,config.model)
