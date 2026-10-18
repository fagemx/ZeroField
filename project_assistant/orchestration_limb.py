"""Remote adapter queue using fenced orchestration handles and existing limb auth."""
import json
import copy
from pathlib import Path

from project_assistant import orchestrator as cp,orchestration_store as db,orchestration_flow,privacy,tools
from project_docs import repository as repo,service,media


def context(conn,worker,body):
    dispatch=cp.leased_dispatch(conn,worker,body.get('dispatch_handle'),body.get('lease_token'))
    if str(body.get('task_id'))!=dispatch['id']:
        raise cp.OrchestrationError(409,'任務與派發憑證不相符','STALE_DISPATCH')
    run=db.get_run(conn,dispatch['project_slug'],dispatch['run_id'])
    member=next((m for m in repo.active_members(conn) if m['actor_id']==run['created_by']),None)
    if not member:
        raise cp.OrchestrationError(403,'發起人已停用')
    me=service.Identity(member['actor_id'],member['name'],member['role'])
    task=db.get_task(conn,dispatch['project_slug'],dispatch['task_id'])
    ctx=tools.ToolContext(lambda:None,dispatch['project_slug'],me,Path('.'),None,agent_key=dispatch['agent_key'],
        dispatch_id=dispatch['id'],admission_no=dispatch['admission_no'],lease_token=body['lease_token'],
        write_mode=task['write_mode'],scope=cp.effective_scope(conn,dispatch,task),worker_id=worker,run_id=run['id'],deadline_at=dispatch['deadline_at'])
    ctx.allowed_tools=set(dispatch['profile_snapshot'].get('allowed_tools',[]))
    return dispatch,task,ctx


def claim(conn,worker):
    for slug in sorted(worker['allowed_projects']):
        orchestration_flow.sync_project(conn,slug)
        cp.sweep(conn,slug)
        cp.schedule_ready(conn,slug)
    keys=db.many(conn,'SELECT agent_key FROM projectops.agent_profile WHERE enabled AND bound_limb_id=%s',(worker['id'],))
    keys.append('limb:'+worker['id'])
    dispatch=cp.claim_dispatch(conn,worker,keys,allowed_projects=worker['allowed_projects'])
    if not dispatch:
        return {'task':None,'retry_after':3}
    task=db.get_task(conn,dispatch['project_slug'],dispatch['task_id'])
    mode=privacy.mode(conn,dispatch['project_slug'])
    source=task['input_snapshot']
    payload=source.get('flow_input')
    if payload is None:
        from project_assistant.table_edits import cell_value
        scope=cp.effective_scope(conn,dispatch,task)
        rows=[]; tabs=[]
        for key,tab in source['tabs'].items():
            doc=tab['doc']
            if scope and scope.get('kind')!='doc' and key==scope['target_tab']:
                table=next(t for t in doc['content'] if t.get('type')=='table' and t.get('attrs',{}).get('bid')==scope['table_id'])
                selected=[row for row in table['content'] if row.get('attrs',{}).get('bid') in scope['row_ids']]
                rows=[{'row_id':row['attrs']['bid'],'tab_key':key,'table_id':scope['table_id'],
                       'cells':[cell_value(cell,tab['values']) for cell in row['content']]} for row in selected]
                header=[row for row in table['content'] if all(cell.get('type')=='tableHeader' for cell in row['content'])]
                doc={'type':'doc','content':[{**copy.deepcopy(table),'content':header+selected}]}
            tabs.append({'key':key,'title':tab['title'],'text':tools.render_doc(doc,{fid:v.get('value','') if isinstance(v,dict) else v for fid,v in tab['values'].items()})})
        from project_assistant.request_scope import for_model
        payload={'prompt':task['spec'],'tabs':tabs,'rows':rows,'request_scope':for_model(scope)}
    payload=privacy.sanitize(payload,mode)
    capability=source.get('capability') or next((c for c in dispatch['profile_snapshot']['capabilities'] if c in worker['capabilities']),None)
    return {'task':{'id':dispatch['id'],'orchestration_task_id':task['id'],'dispatch_handle':dispatch['handle'],
        'lease_token':dispatch['lease_token'],'project_slug':dispatch['project_slug'],'capability':capability,
        'agent_key':dispatch['agent_key'],'profile':privacy.sanitize({k:dispatch['profile_snapshot'].get(k) for k in ('system_prompt','knowledge_pack','allowed_tools','role_kind')},mode),
        'deadline_at':dispatch['deadline_at'],'input':payload,'continuation':privacy.sanitize(dispatch['continuation'] or {},mode)},'lease_seconds':120}


def renew(conn,worker,body):
    dispatch,task,ctx=context(conn,worker,body)
    return cp.renew_dispatch(conn,worker,body['dispatch_handle'],body['lease_token'])


def complete(conn,worker,body):
    outcome=body.get('outcome','succeeded')
    if outcome not in ('succeeded','awaiting_gate'):
        raise cp.OrchestrationError(400,'不支援此完成狀態')
    previous=cp._authenticated_dispatch(conn,worker,body.get('dispatch_handle'),body.get('lease_token'))
    if str(body.get('task_id'))!=previous['id']:
        raise cp.OrchestrationError(409,'任務與派發憑證不相符','STALE_DISPATCH')
    if previous['output_digest']:
        proposals=db.many(conn,'SELECT id FROM projectops.assistant_proposal WHERE dispatch_id=%s ORDER BY id',(previous['id'],))
        return cp.complete_dispatch(conn,worker,body['dispatch_handle'],body['lease_token'],outcome=outcome,output=body.get('output'),proposal_ids=proposals)
    if outcome=='awaiting_gate':
        gate=db.one(conn,"SELECT id FROM projectops.orchestration_gate WHERE dispatch_id=%s AND status='open' AND gate_kind='question'",(previous['id'],))
        if not gate or previous['status']!='awaiting_gate':
            raise cp.OrchestrationError(409,'沒有本次已提交的待決問題','STALE_DISPATCH')
        proposals=db.many(conn,'SELECT id FROM projectops.assistant_proposal WHERE dispatch_id=%s ORDER BY id',(previous['id'],))
        return cp.complete_dispatch(conn,worker,body['dispatch_handle'],body['lease_token'],outcome=outcome,output=body.get('output'),proposal_ids=proposals)
    dispatch,task,ctx=context(conn,worker,body)
    output=body.get('output')
    if not isinstance(output,dict):
        raise cp.OrchestrationError(400,'output 必須是 JSON 物件')
    runtime=body.get('runtime',{})
    if not isinstance(runtime,dict) or set(runtime)-{'model','adapter'} or any(not isinstance(v,str) or len(v)>120 for v in runtime.values()):
        raise cp.OrchestrationError(400,'執行器摘要格式不正確')
    if runtime:
        db.execute(conn,'UPDATE projectops.orchestration_dispatch SET executed_model=%s,executed_provider=%s WHERE id=%s',
                   (runtime.get('model'),runtime.get('adapter'),dispatch['id']))
    proposals=cp.prepare_dispatch_output(conn,ctx,output)
    return cp.complete_dispatch(conn,worker,body['dispatch_handle'],body['lease_token'],outcome='succeeded',output=output,proposal_ids=proposals)


def fail(conn,worker,body):
    context(conn,worker,body)
    return cp.complete_dispatch(conn,worker,body['dispatch_handle'],body['lease_token'],outcome='failed',
        output={'error':str(body.get('error') or 'Worker failed')[:2000],'retryable':body.get('retryable') is True},proposal_ids=[])


def upload(conn,worker,body,raw,mime):
    dispatch,task,ctx=context(conn,worker,body)
    content_type=media.validate(raw,mime)
    asset_id=repo.put_asset(conn,ctx.slug,data=raw,content_type=content_type,actor_id=ctx.me.actor_id)
    return {'asset_id':asset_id,'asset_url':f'/projects/api/{ctx.slug}/assets/{asset_id}','content_type':content_type}


def tool_list(conn,worker,body):
    from project_assistant import agent_policy,agent_registry
    dispatch,task,ctx=context(conn,worker,body)
    profile=agent_registry.get_agent(conn,ctx.slug,ctx.agent_key)
    if not profile or not profile['enabled']:
        raise cp.OrchestrationError(403,'代理已停用','POLICY_DENIED')
    return {'tools':[spec for spec in agent_policy.tool_specs_for(profile) if spec['name'] in ctx.allowed_tools]}


def tool(conn,worker,body,connection_factory):
    dispatch,task,ctx=context(conn,worker,body)
    ctx.connection_factory=connection_factory
    # tools.call owns its short, journaled transaction and revalidates the lease.
    # Release this HTTP transaction before entering it (no nested row locks).
    conn.rollback()
    try:
        return {'text':tools.call(ctx,body.get('name'),body.get('arguments'))}
    except tools.ToolError as exc:
        code='STALE_DISPATCH' if 'STALE_DISPATCH' in str(exc) else 'POLICY_DENIED'
        raise cp.OrchestrationError(409 if code=='STALE_DISPATCH' else 403,str(exc),code) from None
