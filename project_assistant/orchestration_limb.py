"""Remote adapter queue using fenced orchestration handles and existing limb auth."""
import json
import copy
from pathlib import Path

from project_assistant import orchestrator as cp,orchestration_store as db,orchestration_flow,privacy,tools
from project_docs import repository as repo,service,media


def context(conn,worker,body):
    dispatch=cp.leased_dispatch(conn,worker,body.get('dispatch_handle'),body.get('lease_token'))
    if str(body.get('task_id'))!=dispatch['id']:
        raise cp.OrchestrationError(409,"Task and dispatch credentials do not match.",'STALE_DISPATCH')
    run=db.get_run(conn,dispatch['project_slug'],dispatch['run_id'])
    member=next((m for m in repo.active_members(conn) if m['actor_id']==run['created_by']),None)
    if not member:
        raise cp.OrchestrationError(403,"The initiator is disabled.")
    me=service.Identity(member['actor_id'],member['name'],member['role'])
    task=db.get_task(conn,dispatch['project_slug'],dispatch['task_id'])
    execution_binding(conn,me,dispatch,worker)
    ctx=tools.ToolContext(lambda:None,dispatch['project_slug'],me,Path('.'),None,agent_key=dispatch['agent_key'],
        dispatch_id=dispatch['id'],admission_no=dispatch['admission_no'],lease_token=body['lease_token'],
        write_mode=task['write_mode'],scope=cp.effective_scope(conn,dispatch,task),worker_id=worker,run_id=run['id'],deadline_at=dispatch['deadline_at'])
    from project_assistant import execution_governance
    execution_governance.install(ctx)
    ctx.original_objective=task['spec']
    ctx.allowed_tools=set(dispatch['profile_snapshot'].get('allowed_tools',[]))
    return dispatch,task,ctx


def execution_binding(conn, me, dispatch, worker):
    if dispatch['agent_key'].startswith('limb:'):
        return  # Existing standalone limb protocol is not a persisted Console profile.
    from project_assistant import agent_console_store as resources
    bindings=resources.execution_resources(conn,me,dispatch['project_slug'],dispatch['agent_key'])
    bound=bindings['environment']['config'].get('worker_id')
    if bound and bound != worker['id']:
        raise cp.OrchestrationError(403,'This environment does not authorize the claiming worker.','POLICY_DENIED')


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
    run=db.get_run(conn,dispatch['project_slug'],dispatch['run_id'])
    execution_binding(conn,service.Identity(run['created_by'],'Production crew','member'),dispatch,worker)
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
    mounted = ''
    if not dispatch['agent_key'].startswith('limb:'):
        from project_assistant import prompting
        run = db.get_run(conn, dispatch['project_slug'], dispatch['run_id'])
        me = service.Identity(run['created_by'], 'Production crew', 'member')
        episode_id = prompting.episode_context(conn, dispatch['project_slug'], cp.effective_scope(conn, dispatch, task))
        mounted = prompting.mounted_context(conn, me, dispatch['project_slug'], dispatch['profile_snapshot'], episode_id=episode_id)
    profile = privacy.sanitize({k: dispatch['profile_snapshot'].get(k) for k in ('system_prompt','knowledge_pack','allowed_tools','role_kind')}, mode)
    profile['system_prompt'] = (profile.get('system_prompt') or '') + '\n' + mounted
    return {'task':{'id':dispatch['id'],'orchestration_task_id':task['id'],'dispatch_handle':dispatch['handle'],
        'lease_token':dispatch['lease_token'],'project_slug':dispatch['project_slug'],'capability':capability,
        'agent_key':dispatch['agent_key'],'profile':profile,
        'deadline_at':dispatch['deadline_at'],'input':payload,'continuation':privacy.sanitize(dispatch['continuation'] or {},mode)},'lease_seconds':120}


def renew(conn,worker,body):
    dispatch,task,ctx=context(conn,worker,body)
    return cp.renew_dispatch(conn,worker,body['dispatch_handle'],body['lease_token'])


def complete(conn,worker,body):
    outcome=body.get('outcome','succeeded')
    if outcome not in ('succeeded','awaiting_gate'):
        raise cp.OrchestrationError(400,"Unsupported completion status.")
    previous=cp._authenticated_dispatch(conn,worker,body.get('dispatch_handle'),body.get('lease_token'))
    if str(body.get('task_id'))!=previous['id']:
        raise cp.OrchestrationError(409,"Task and dispatch credentials do not match.",'STALE_DISPATCH')
    if previous['output_digest'] and previous.get('outcome_candidate_digest'):
        if previous['outcome_candidate_digest'] != cp.digest(body.get('output')):
            raise cp.OrchestrationError(409, 'This graded dispatch already reported a different candidate.', 'STALE_DISPATCH')
        return {'id':previous['id'],'handle':body['dispatch_handle'],'status':previous['status']}
    if previous['output_digest']:
        proposals=db.many(conn,'SELECT id FROM projectops.assistant_proposal WHERE dispatch_id=%s ORDER BY id',(previous['id'],))
        return cp.complete_dispatch(conn,worker,body['dispatch_handle'],body['lease_token'],outcome=outcome,output=body.get('output'),proposal_ids=proposals)
    if outcome=='awaiting_gate':
        gate=db.one(conn,"SELECT id FROM projectops.orchestration_gate WHERE dispatch_id=%s AND status='open' AND gate_kind='question'",(previous['id'],))
        if not gate or previous['status']!='awaiting_gate':
            raise cp.OrchestrationError(409,"No committed decision gate exists for this turn.",'STALE_DISPATCH')
        proposals=db.many(conn,'SELECT id FROM projectops.assistant_proposal WHERE dispatch_id=%s ORDER BY id',(previous['id'],))
        return cp.complete_dispatch(conn,worker,body['dispatch_handle'],body['lease_token'],outcome=outcome,output=body.get('output'),proposal_ids=proposals)
    dispatch,task,ctx=context(conn,worker,body)
    output=body.get('output')
    if not isinstance(output,dict):
        raise cp.OrchestrationError(400,"output must be a JSON object.")
    runtime=body.get('runtime',{})
    if not isinstance(runtime,dict) or set(runtime)-{'model','adapter'} or any(not isinstance(v,str) or len(v)>120 for v in runtime.values()):
        raise cp.OrchestrationError(400,"Invalid runtime summary.")
    if runtime:
        db.execute(conn,'UPDATE projectops.orchestration_dispatch SET executed_model=%s,executed_provider=%s WHERE id=%s',
                   (runtime.get('model'),runtime.get('adapter'),dispatch['id']))
    from project_assistant import agent_registry, outcome_grader, execution_governance as governance
    profile=agent_registry.get_agent(conn,ctx.slug,ctx.agent_key)
    if profile and profile.get('outcome_grader',{}).get('enabled'):
        cp.lock_project(conn,ctx.slug)
        begun=db.one(conn, 'UPDATE projectops.orchestration_dispatch SET outcome_grading_started=TRUE,outcome_candidate_digest=%s WHERE id=%s AND NOT outcome_grading_started RETURNING id', (cp.digest(output),dispatch['id']))
        if not begun:
            raise cp.OrchestrationError(409,'Outcome grading already started; reconcile the existing attempt before retry.','STALE_DISPATCH')
        conn.commit()  # Never hold the HTTP transaction/lease lock across inference.
        from project_docs import http
        ctx.connection_factory=http.open_connection
        ctx.original_objective=task['spec']
        from project_assistant import prompting
        ctx.episode_id=governance.transaction(ctx, lambda c: prompting.episode_context(c,ctx.slug,ctx.scope))
        def trace(entry):
            def save(c):
                governance.live(c,ctx)
                db.execute(c,'UPDATE projectops.orchestration_dispatch SET tools_trace=tools_trace||%s::jsonb WHERE id=%s',(json.dumps([entry]),dispatch['id']))
            governance.transaction(ctx,save)
        candidate,card=outcome_grader.grade_candidate(ctx=ctx,profile=profile,candidate={'answer':json.dumps(output),'proposals':[]},
            timeout=max(0,(cp.instant(dispatch['deadline_at'])-cp.now()).total_seconds()),on_trace=trace)
        if not card['passed']:
            outcome_grader.needs_you(ctx,card)
            return cp.complete_dispatch(conn,worker,body['dispatch_handle'],body['lease_token'],outcome='awaiting_gate',
                output={'text':'Needs You: independent outcome check failed.','outcome_grader':card},proposal_ids=[])
        output=json.loads(candidate['answer'])
        if not isinstance(output,dict):
            raise cp.OrchestrationError(400,'Graded remote candidate must remain an object.')
        output['outcome_grader']=card
    proposals=cp.prepare_dispatch_output(conn,ctx,output)
    return cp.complete_dispatch(conn,worker,body['dispatch_handle'],body['lease_token'],outcome='succeeded',output=output,proposal_ids=proposals)


def fail(conn,worker,body):
    context(conn,worker,body)
    return cp.complete_dispatch(conn,worker,body['dispatch_handle'],body['lease_token'],outcome='failed',
        output={'error':'Remote execution failed; reconcile accepted requests before retry.','retryable':False},proposal_ids=[])


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
        raise cp.OrchestrationError(403,"The agent is disabled.",'POLICY_DENIED')
    return {'tools':[spec for spec in agent_policy.tool_specs_for(profile) if spec['name'] in ctx.allowed_tools]}


def tool(conn,worker,body,connection_factory):
    dispatch,task,ctx=context(conn,worker,body)
    ctx.connection_factory=connection_factory
    # tools.call owns its short, journaled transaction and revalidates the lease.
    # Release this HTTP transaction before entering it (no nested row locks).
    conn.rollback()
    try:
        result = tools.call(ctx,body.get('name'),body.get('arguments'))
        return {'text':str(result), 'images':getattr(result, 'images', [])}
    except tools.ToolError as exc:
        code='STALE_DISPATCH' if 'STALE_DISPATCH' in str(exc) else 'POLICY_DENIED'
        raise cp.OrchestrationError(409 if code=='STALE_DISPATCH' else 403,str(exc),code) from None
