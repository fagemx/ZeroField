"""The six orchestration tools, using the same transaction as the tool host."""
import copy
import json
import time
import uuid

from project_assistant import orchestrator as cp,orchestration_store as db,agent_registry,store,request_scope


def run_for(ctx,conn):
    if getattr(ctx,'dispatch_id',None):
        return cp.own_run(conn,ctx.me,ctx.slug,db.get_dispatch(conn,ctx.slug,ctx.dispatch_id)['run_id'])
    if getattr(ctx,'run_id',None):
        return cp.own_run(conn,ctx.me,ctx.slug,ctx.run_id)
    reply=store.message(conn,ctx.message_id) if ctx.message_id else None
    if not reply or reply['owner_id']!=ctx.me.actor_id or reply['slug']!=ctx.slug:
        raise cp.OrchestrationError(403,"This tool requires a valid conversation or execution context.")
    question=store.message(conn,reply['reply_to']) if reply.get('reply_to') else reply
    run=cp.create_run(conn,ctx.me,ctx.slug,question['body'] or '附件工作',client_request_id='message:'+str(ctx.message_id),conversation_id=reply['conversation_id'])
    db.execute(conn,'UPDATE projectops.orchestration_run SET coordinator_key=%s,trigger_message_id=%s WHERE id=%s',(ctx.agent_key,ctx.message_id,run['id']))
    db.execute(conn,'UPDATE projectops.assistant_message SET run_id=%s WHERE id=%s',(run['id'],ctx.message_id))
    return db.get_run(conn,ctx.slug,run['id'])


def list_agents(ctx,conn,args):
    rows=agent_registry.roster(conn,ctx.me,ctx.slug)
    keys=('agent_key','display_name','icon','role_kind','runtime_kind','capabilities','labels','status','active_dispatches','max_concurrency')
    return json.dumps([{k:a.get(k) for k in keys} for a in rows
        if (not args.get('capability') or args['capability'] in a['capabilities'])
        and (not args.get('domain') or a['labels'].get('domain')==args['domain'])],ensure_ascii=False)


def spawn_agent(ctx,conn,args):
    run=run_for(ctx,conn)
    strategy=args.get('strategy','single')
    if strategy=='race' and not hasattr(cp,'start_race'):
        raise cp.OrchestrationError(400,"Candidate comparison must be enabled for race mode.")
    target=args.get('target_agent')
    if target==ctx.agent_key:
        raise cp.OrchestrationError(403,"An agent cannot delegate to itself.",'POLICY_DENIED')
    scope=args.get('scope',getattr(ctx,'scope',None))
    if scope and 'tab_key' in scope:
        scope={**scope,'target_tab':scope['tab_key']}
    if getattr(ctx,'scope',None):
        request_scope.guard_child_scope(ctx.scope,scope)
    parent=db.get_dispatch(conn,ctx.slug,ctx.dispatch_id) if getattr(ctx,'dispatch_id',None) else None
    if parent:
        parent_task=db.get_task(conn,ctx.slug,parent['task_id'])
        if parent_task['request_scope']:
            scope=scope or parent_task['request_scope']
            request_scope.guard_child_scope(parent_task['request_scope'],scope)
    mode=args.get('write_mode',getattr(ctx,'write_mode','proposal'))
    task=cp.create_task(conn,ctx.me,ctx.slug,run['id'],objective=args.get('objective'),agent_key=target,
        label_selector=args.get('label_selector'),scope=scope,target=args.get('target'),depends_on=args.get('depends_on',[]),
        strategy=strategy,write_mode=mode,parent_dispatch_id=parent['id'] if parent else None)
    if task['target_agent_key']==ctx.agent_key:
        raise cp.OrchestrationError(403,"The label selector matches the caller and would create a delegation cycle.",'POLICY_DENIED')
    dispatches=[]
    if strategy=='race':
        dispatches=cp.start_race(conn,ctx.me,ctx.slug,task['id'],args.get('race_agents'))
    elif task['status']=='ready':
        slots=['row:'+rid for rid in task['request_scope']['row_ids']] if strategy=='fanout_rows' else ['single']
        dispatches=[cp.spawn_dispatch(conn,ctx.slug,task['id'],agent_key=task['target_agent_key'],slot_key=slot,
                                     caller_dispatch_id=parent['id'] if parent else None) for slot in slots]
    return json.dumps({'run_id':run['id'],'task_id':task['id'],'dispatch_handles':[d['handle'] for d in dispatches[:6]],
                       'dispatch_count':len(dispatches)},ensure_ascii=False)


def check_delegation(ctx,conn,args):
    cp.actor(conn,ctx.slug,ctx.me,write=False)
    run_id=args.get('run_id')
    if args.get('dispatch_handle'):
        identifier,admission=cp.parse_handle(args['dispatch_handle'])
        dispatch=db.get_dispatch(conn,ctx.slug,identifier)
        if not dispatch or dispatch['admission_no']!=admission:
            raise cp.OrchestrationError(404,"Dispatch not found.")
        run_id=dispatch['run_id']
    if not run_id and getattr(ctx,'dispatch_id',None):
        run_id=db.get_dispatch(conn,ctx.slug,ctx.dispatch_id)['run_id']
    if not run_id and getattr(ctx,'run_id',None):
        run_id=ctx.run_id
    if not run_id and getattr(ctx,'message_id',None):
        run_id=db.one(conn,'SELECT run_id::text FROM projectops.assistant_message WHERE id=%s AND project_slug=%s AND owner_id=%s',
                      (ctx.message_id,ctx.slug,ctx.me.actor_id))
    if not run_id:
        recent=db.many(conn,'''SELECT jsonb_build_object('id',id,'objective',objective,'status',status,'summary',summary)
            FROM projectops.orchestration_run WHERE project_slug=%s AND created_by=%s ORDER BY created_at DESC LIMIT 20''',(ctx.slug,ctx.me.actor_id))
        return json.dumps({'runs':recent},ensure_ascii=False)
    run=cp.own_run(conn,ctx.me,ctx.slug,run_id,write=False)
    tasks=db.tasks(conn,ctx.slug,run['id'])
    gates=db.many(conn,"SELECT to_jsonb(g) FROM projectops.orchestration_gate g WHERE run_id=%s AND status='open' ORDER BY created_at LIMIT 20",(run['id'],))
    return json.dumps({'run_id':run['id'],'status':run['status'],'tasks':[{k:t[k] for k in ('id','title','status','result_summary','error')} for t in tasks[:20]],
        'task_count':len(tasks),'open_gates':[{k:g[k] for k in ('id','question','options','gate_kind')} for g in gates]},ensure_ascii=False)


def cancel_delegation(ctx,conn,args):
    return json.dumps(cp.cancel_dispatch(conn,ctx.me,ctx.slug,args.get('dispatch_handle'),args.get('reason','由主控取消')),ensure_ascii=False)


def ask_decision_gate(ctx,conn,args,*,control_only=False):
    execution=ctx
    if not getattr(ctx,'dispatch_id',None):
        from types import SimpleNamespace
        import hashlib
        run=run_for(ctx,conn)
        task=cp.create_task(conn,ctx.me,ctx.slug,run['id'],objective=run['objective'],agent_key=ctx.agent_key,
                            scope=getattr(ctx,'scope',None),write_mode='analysis_only' if control_only else getattr(ctx,'write_mode','proposal'))
        journal=db.one(conn,'SELECT tool_journal FROM projectops.assistant_message WHERE id=%s',(ctx.message_id,)) or {}
        continuation={'journal':copy.deepcopy(journal),
            'chat_context':getattr(ctx,'turn_context',run['objective']),'origin_message_id':ctx.message_id}
        dispatch=cp.spawn_dispatch(conn,ctx.slug,task['id'],agent_key=ctx.agent_key,slot_key='single',continuation=continuation)
        token=uuid.uuid4().hex
        identity='chat:'+str(ctx.message_id)
        db.execute(conn,"UPDATE projectops.orchestration_dispatch SET status='running',lease_owner=%s,lease_hash=%s,lease_until=%s WHERE id=%s",
                   (identity,hashlib.sha256(token.encode()).hexdigest(),cp.instant(dispatch['deadline_at']),dispatch['id']))
        execution=SimpleNamespace(slug=ctx.slug,me=ctx.me,agent_key=ctx.agent_key,dispatch_id=dispatch['id'],admission_no=dispatch['admission_no'],lease_token=token,worker_id=identity)
    gate=cp.open_gate(conn,execution,question=args.get('question'),options=args.get('options'),blocking_task_ids=args.get('blocking_task_ids',[]))
    if gate.get('awaiting_gate') is False:
        return json.dumps(gate,ensure_ascii=False)
    if execution is not ctx:
        cp.complete_dispatch(conn,execution.worker_id,f'dsp_{execution.dispatch_id}_{execution.admission_no}',execution.lease_token,
                             outcome='awaiting_gate',output={},proposal_ids=[])
    return json.dumps({'gate_id':gate['id'],'run_id':gate['run_id'],'awaiting_gate':True},ensure_ascii=False)


def trigger_flow_run(ctx,conn,args):
    from project_assistant import flow_runner
    key=args.get('flow_tab_key')
    body={k:v for k,v in args.items() if k!='flow_tab_key'}
    if body.get('execution_mode')=='single_step':
        body['input_mode']='current_sources'
    elif getattr(ctx,'scope',None) and ctx.scope.get('kind')!='doc' and 'row_ids' not in body:
        body['row_ids']=ctx.scope['row_ids']
    preview=flow_runner.preflight(conn,ctx.me,ctx.slug,key,body)
    if preview.get('errors'):
        raise cp.OrchestrationError(409,"Resolve source or worker issues before running this pipeline.")
    definition=flow_runner.definition(conn,ctx.slug,key)
    run=run_for(ctx,conn)
    if run.get('flow_run_id'):
        raise cp.OrchestrationError(409,"This task already started a pipeline. Create a separate task for another pipeline.")
    body['definition_revision']=preview['definition_revision']
    body['source_revisions']=preview['source_revisions']
    direct=any(node.get('write_mode')=='direct' for node in preview['nodes'])
    if direct or getattr(ctx,'scope',None):
        outputs='、'.join(dict.fromkeys(node.get('target_title') or '保留結果' for node in preview['nodes']))[:2000]
        question=f'確認啟動 {len(preview["nodes"])} 個工作流步驟？輸出：{outputs}。'
        question+=('包含直接寫入，確認後會執行。' if direct else '')
        question+=('流程實際輸出可能涵蓋原選取範圍以外的資料，請核對流程範圍。' if getattr(ctx,'scope',None) else '')
        pending=json.loads(ask_decision_gate(ctx,conn,{'question':question,'options':['確認啟動','取消此流程']},control_only=True))
        if pending.get('awaiting_gate'):
            gate=db.get_gate(conn,ctx.slug,pending['gate_id'])
            continuation={**(gate['continuation'] or {}),'action':{'kind':'flow_start','flow_tab_key':key,'body':body,
                'preview':preview,'control_only':not bool(getattr(ctx,'dispatch_id',None)),
                'tool_cache_key':cp.digest({'tool':'trigger_flow_run','args':args})}}
            db.execute(conn,'UPDATE projectops.orchestration_gate SET continuation=%s::jsonb WHERE id=%s',(json.dumps(continuation,ensure_ascii=False),gate['id']))
        return json.dumps(pending,ensure_ascii=False)
    result=flow_runner.start(conn,ctx.me,ctx.slug,key,body)
    flow_id=result.get('run',result).get('id')
    db.execute(conn,'UPDATE projectops.orchestration_run SET flow_run_id=%s WHERE id=%s',(flow_id,run['id']))
    return json.dumps({'flow_run_id':flow_id,'run_id':run['id']},ensure_ascii=False)


def wait_for_task(ctx,result):
    payload=json.loads(result)
    remaining=max(0,(cp.instant(ctx.deadline_at)-cp.now()).total_seconds()) if getattr(ctx,'deadline_at',None) else 5
    until=time.monotonic()+min(5,remaining)
    while time.monotonic()<until:
        conn=ctx.connection_factory()
        try:
            task=db.get_task(conn,ctx.slug,payload['task_id'])
            run=db.get_run(conn,ctx.slug,payload['run_id'])
            active=db.one(conn,"SELECT count(*) FROM projectops.orchestration_dispatch WHERE run_id=%s AND status='running'",(run['id'],))
            if task['status'] in ('completed','failed','canceled','awaiting_gate') or active>=run['max_parallel_dispatches']:
                payload.update(status=task['status'],summary=task['result_summary'])
                return json.dumps(payload,ensure_ascii=False)
        finally:
            conn.close()
        time.sleep(.05)
    return result


HANDLERS={fn.__name__:fn for fn in (list_agents,spawn_agent,check_delegation,cancel_delegation,ask_decision_gate,trigger_flow_run)}
