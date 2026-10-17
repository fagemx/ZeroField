"""Authoritative per-call authorization, shared by every model transport."""
from project_assistant import agent_registry, tool_specs


def tool_specs_for(profile):
    allowed = set(profile.get('allowed_tools', []))
    if profile.get('role_kind') == 'observer':
        return []
    if profile.get('role_kind') != 'primary':
        allowed -= {'spawn_agent','cancel_delegation','trigger_flow_run','check_delegation','list_agents'}
    return [s for s in tool_specs.TOOLS if s['name'] in allowed]


def authorize_tool(ctx, conn, name, args):
    from project_assistant.tools import ToolError
    from project_assistant import store
    profile = agent_registry.get_agent(conn, ctx.slug, getattr(ctx,'agent_key','coordinator'))
    if not profile or not profile['enabled'] or name not in {s['name'] for s in tool_specs_for(profile)}:
        raise ToolError('POLICY_DENIED：此代理沒有此工具權限')
    members = repo_members(conn)
    current = next((m for m in members if m['actor_id']==ctx.me.actor_id),None)
    if not current or not store.is_member_enabled(conn,ctx.slug,ctx.me.actor_id):
        raise ToolError('POLICY_DENIED：成員已停用或助理權限已撤銷')
    mutating = name in {'propose','propose_table_edit','spawn_agent','cancel_delegation','ask_decision_gate','trigger_flow_run'}
    if mutating and (current['role']=='viewer' or getattr(ctx,'write_mode',None)=='analysis_only'):
        raise ToolError('POLICY_DENIED：此工作只允許讀取分析')
    if profile['agent_key']=='qa_critic' and name=='propose' and args.get('action') not in agent_registry.QA_ACTIONS:
        raise ToolError('POLICY_DENIED：審核代理只能提出標註或討論')


def repo_members(conn):
    from project_docs import repository
    return repository.active_members(conn)
