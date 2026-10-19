"""Authoritative per-call authorization, shared by every model transport."""
from project_assistant import agent_registry, tool_specs


def tool_specs_for(profile):
    allowed = set(profile.get('allowed_tools', []))
    if profile.get('role_kind') == 'observer':
        return []
    if profile.get('role_kind') != 'primary':
        allowed -= {'spawn_agent','cancel_delegation','trigger_flow_run','check_delegation','list_agents'}
    policies = profile.get('tool_policies') or {}
    multi = profile.get('multiagent_config') or {}
    if not multi.get('allow_subagents'): allowed.discard('spawn_agent')
    if not multi.get('allow_workflows'): allowed.discard('trigger_flow_run')
    if not multi.get('advisor_agent_key'): allowed.discard('consult_advisor')
    return [s for s in tool_specs.TOOLS if s['name'] in allowed and policies.get(s['name']) != 'disabled']


def can_propose_output(profile,target):
    if not profile.get('enabled') or profile.get('role_kind')=='observer' or profile.get('agent_key')=='qa_critic':
        return False
    if profile.get('runtime_kind')=='remote_limb' and 'llm' not in profile.get('capabilities',[]):
        return True  # Media adapters have a narrow, administrator-bound artifact output contract.
    required='propose' if target.get('kind')=='doc' else 'propose_table_edit'
    return required in profile.get('allowed_tools',[]) and profile.get('tool_policies', {}).get(required) != 'disabled'


def authorize_tool(ctx, conn, name, args):
    from project_assistant.tools import ToolError
    from project_assistant import store
    profile = agent_registry.get_agent(conn, ctx.slug, getattr(ctx,'agent_key','coordinator'))
    if not profile or not profile['enabled'] or name not in {s['name'] for s in tool_specs_for(profile)}:
        raise ToolError("POLICY_DENIED: This agent cannot use this tool.")
    frozen=getattr(ctx,'allowed_tools',None)
    if frozen is not None and name not in frozen:
        raise ToolError("POLICY_DENIED: This tool is not granted for this turn.")
    if getattr(ctx,'lease_owner',None) and getattr(ctx,'message_id',None):
        import datetime as dt
        message=store.message(conn,ctx.message_id)
        if (not message or message['status']!='running' or message['lease_owner']!=ctx.lease_owner
            or not message.get('lease_until') or dt.datetime.fromisoformat(message['lease_until'])<=dt.datetime.now(dt.timezone.utc)):
            raise ToolError("STALE_DISPATCH: This turn’s lease is no longer valid.")
    members = repo_members(conn)
    current = next((m for m in members if m['actor_id']==ctx.me.actor_id),None)
    if not current or not store.is_member_enabled(conn,ctx.slug,ctx.me.actor_id):
        raise ToolError("POLICY_DENIED: The account is disabled or assistant access was revoked.")
    from project_assistant import orchestrator
    if getattr(ctx.me, 'can_edit', False) and current['role'] != 'admin':
        from project_docs.service import Identity
        ctx.me = Identity(ctx.me.actor_id, ctx.me.name, current['role'])
    orchestrator.actor(conn, ctx.slug, ctx.me, write=True)
    multi = profile.get('multiagent_config') or {}
    if name == 'spawn_agent' and args.get('strategy', 'single') != 'single' and not multi.get('allow_workflows'):
        raise ToolError('POLICY_DENIED: Workflows are disabled for this agent.')
    if getattr(ctx, 'advisor_call', False):
        raise ToolError('POLICY_DENIED: Advisor contexts cannot call tools.')
    mutating = name in tool_specs.MUTATING_TOOLS
    if mutating and current['role']=='viewer':
        raise ToolError("POLICY_DENIED: Read-only crew members cannot perform this operation.")
    if (name in ('propose','propose_table_edit','trigger_flow_run','studio_ingest_script','studio_manage_asset','studio_dispatch_shot','studio_edit_timeline')) and getattr(ctx,'write_mode',None)=='analysis_only':
        raise ToolError("POLICY_DENIED: This task allows read-only analysis.")
    if getattr(ctx,'dispatch_id',None):
        from project_assistant import orchestrator
        try:
            dispatch=orchestrator.leased_dispatch(conn,ctx.worker_id,
                f'dsp_{ctx.dispatch_id}_{ctx.admission_no}',ctx.lease_token)
        except agent_registry.AgentError as exc:
            raise ToolError(exc.code+'：'+str(exc)) from exc
        if dispatch['agent_key']!=ctx.agent_key:
            raise ToolError("POLICY_DENIED: Dispatch role mismatch.")
        if name in {'studio_ingest_script','studio_manage_asset','studio_dispatch_shot','studio_edit_timeline'}:
            from project_assistant import orchestration_store as db
            task = db.get_task(conn, ctx.slug, dispatch['task_id'])
            if task['strategy'] == 'race':
                raise ToolError('POLICY_DENIED: Race candidates cannot execute production actions before winner review.')
            for key in task['input_snapshot']['tabs']:
                orchestrator._task_source_matches(task, key, orchestrator.freeze_tab(conn, ctx.slug, key))
    if profile['agent_key']=='qa_critic' and name=='propose' and args.get('action') not in agent_registry.QA_ACTIONS:
        raise ToolError("POLICY_DENIED: Review agents can only propose annotations or discussions.")


def repo_members(conn):
    from project_docs import repository
    return repository.active_members(conn)


def permission_mode(ctx, conn, name, args):
    profile = agent_registry.get_agent(conn, ctx.slug, ctx.agent_key)
    mode = (profile.get('tool_policies') or {}).get(name, tool_specs.DEFAULT_POLICIES.get(name, 'auto'))
    if name == 'studio_dispatch_shot' and mode == 'auto':
        from project_docs import story_openapi as story
        saved = story.owned(conn, ctx.me, args['allocation_id'], 'allocation')
        # Auto is only an explicitly configured local, non-escalated open-weights batch.
        if profile.get('tool_policies', {}).get(name) != 'auto' or any(
            a.get('tier') != 'open_weights' or a.get('driver') != 'comfy_local' or a.get('race_plans') or
            any(s['kind'] == 'approval' for s in a['stages']) for a in saved['plan']['allocations']):
            mode = 'always_ask'
    return mode
