"""Authoritative per-call authorization, shared by every model transport."""
from project_assistant import agent_registry, tool_specs


def tool_specs_for(profile):
    allowed = set(profile.get('allowed_tools', []))
    if profile.get('role_kind') == 'observer':
        return []
    if profile.get('role_kind') != 'primary':
        allowed -= {'spawn_agent','cancel_delegation','trigger_flow_run','check_delegation','list_agents'}
    return [s for s in tool_specs.TOOLS if s['name'] in allowed]


def can_propose_output(profile,target):
    if not profile.get('enabled') or profile.get('role_kind')=='observer' or profile.get('agent_key')=='qa_critic':
        return False
    if profile.get('runtime_kind')=='remote_limb' and 'llm' not in profile.get('capabilities',[]):
        return True  # Media adapters have a narrow, administrator-bound artifact output contract.
    required='propose' if target.get('kind')=='doc' else 'propose_table_edit'
    return required in profile.get('allowed_tools',[])


def authorize_tool(ctx, conn, name, args):
    from project_assistant.tools import ToolError
    from project_assistant import store
    profile = agent_registry.get_agent(conn, ctx.slug, getattr(ctx,'agent_key','coordinator'))
    if not profile or not profile['enabled'] or name not in {s['name'] for s in tool_specs_for(profile)}:
        raise ToolError('POLICY_DENIED：此代理沒有此工具權限')
    frozen=getattr(ctx,'allowed_tools',None)
    if frozen is not None and name not in frozen:
        raise ToolError('POLICY_DENIED：此回合未授予此工具')
    if getattr(ctx,'lease_owner',None) and getattr(ctx,'message_id',None):
        import datetime as dt
        message=store.message(conn,ctx.message_id)
        if (not message or message['status']!='running' or message['lease_owner']!=ctx.lease_owner
            or not message.get('lease_until') or dt.datetime.fromisoformat(message['lease_until'])<=dt.datetime.now(dt.timezone.utc)):
            raise ToolError('STALE_DISPATCH：此回合租約已失效')
    members = repo_members(conn)
    current = next((m for m in members if m['actor_id']==ctx.me.actor_id),None)
    if not current or not store.is_member_enabled(conn,ctx.slug,ctx.me.actor_id):
        raise ToolError('POLICY_DENIED：成員已停用或助理權限已撤銷')
    mutating = name in {'propose','propose_table_edit','spawn_agent','cancel_delegation','ask_decision_gate','trigger_flow_run'}
    if mutating and current['role']=='viewer':
        raise ToolError('POLICY_DENIED：唯讀成員不能執行此操作')
    if name in ('propose','propose_table_edit','trigger_flow_run') and getattr(ctx,'write_mode',None)=='analysis_only':
        raise ToolError('POLICY_DENIED：此工作只允許讀取分析')
    if getattr(ctx,'dispatch_id',None):
        from project_assistant import orchestrator
        try:
            dispatch=orchestrator.leased_dispatch(conn,ctx.worker_id,
                f'dsp_{ctx.dispatch_id}_{ctx.admission_no}',ctx.lease_token)
        except agent_registry.AgentError as exc:
            raise ToolError(exc.code+'：'+str(exc)) from exc
        if dispatch['agent_key']!=ctx.agent_key:
            raise ToolError('POLICY_DENIED：派發角色不相符')
    if profile['agent_key']=='qa_critic' and name=='propose' and args.get('action') not in agent_registry.QA_ACTIONS:
        raise ToolError('POLICY_DENIED：審核代理只能提出標註或討論')


def repo_members(conn):
    from project_docs import repository
    return repository.active_members(conn)
