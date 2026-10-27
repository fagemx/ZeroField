"""Owner-filtered orchestration API and lightweight board projections."""
import base64
import json
import uuid

from project_assistant import orchestrator as cp,orchestration_store as db,agent_registry,store
from project_docs import repository as repo


def result(action):
    try:
        return 200,action()
    except cp.OrchestrationError as exc:
        return exc.status,{'error':str(exc),'code':exc.code}
    except (ValueError,TypeError,KeyError) as exc:
        return 400,{'error':"Invalid request:"+str(exc)[:200],'code':'INVALID_REQUEST'}


def object_body(body,allowed):
    if not isinstance(body,dict) or set(body)-set(allowed):
        raise cp.OrchestrationError(400,"Invalid request fields.")
    return body


def create_run_request(conn,me,slug,body):
    def action():
        object_body(body,('client_request_id','objective','scope','target','agent_key','label_selector','strategy','race_agents',
                          'write_mode','limits','conversation_id','deadline_at','depends_on'))
        if body.get('depends_on'):
            raise cp.OrchestrationError(400,"An initial task cannot depend on tasks from another run.")
        strategy=body.get('strategy','single')
        if strategy=='race' and not hasattr(cp,'start_race'):
            raise cp.OrchestrationError(400,"Race mode is not enabled.")
        if body.get('conversation_id') is not None and type(body['conversation_id']) is not int:
            raise cp.OrchestrationError(400,"Invalid conversation ID.")
        run=cp.create_run(conn,me,slug,body.get('objective'),client_request_id=body.get('client_request_id'),
            limits=body.get('limits'),conversation_id=body.get('conversation_id'),deadline_at=body.get('deadline_at'),
            request_payload={k:v for k,v in body.items() if k!='client_request_id'})
        existing=db.tasks(conn,slug,run['id'])
        if existing:
            task=existing[0]
        else:
            task=cp.create_task(conn,me,slug,run['id'],objective=body['objective'],agent_key=body.get('agent_key'),
                label_selector=body.get('label_selector'),scope=body.get('scope'),target=body.get('target'),strategy=strategy,
                write_mode=body.get('write_mode','proposal'))
            if strategy=='race':
                cp.start_race(conn,me,slug,task['id'],body.get('race_agents'))
            else:
                slots=['row:'+rid for rid in task['request_scope']['row_ids']] if strategy=='fanout_rows' else ['single']
                for slot in slots:
                    cp.spawn_dispatch(conn,slug,task['id'],agent_key=task['target_agent_key'],slot_key=slot)
        return {'run':db.get_run(conn,slug,run['id']),'task':db.get_task(conn,slug,task['id']),
                'dispatch_handles':[cp.handle(d) for d in db.dispatches(conn,slug,task['id']) if not d['superseded_by']]}
    return result(action)


def public_dispatch(dispatch):
    hidden={'lease_owner','lease_hash','profile_snapshot','continuation','output_digest'}
    return {k:v for k,v in dispatch.items() if k not in hidden}


def _failure(dispatches,task):
    """The plain-language failure class of a task's latest failed model call (SPEC_20 R12), if any."""
    from project_assistant.model_client import FAILURE_CLASSES
    failed=[d for d in dispatches if d['task_id']==task['id'] and d['status']=='failed' and not d['superseded_by']]
    found=(max(failed,key=lambda d:d['admission_no']).get('output_json') or {}).get('failure') if failed else None
    return found if found in FAILURE_CLASSES else None


def task_target(task):
    scope=task.get('request_scope') or {}
    target={**task['target']}
    if not target.get('tab_key') and scope:
        target['tab_key']=scope['target_tab']
    if scope.get('table_id'):
        target.setdefault('table_id',scope['table_id'])
    if scope.get('row_ids'):
        target.setdefault('row_id',scope['row_ids'][0])
    if scope.get('block_ids'):
        target.setdefault('block_id',scope['block_ids'][0])
    return target


def run_detail(conn,me,slug,run_id,*,cursor=None):
    def action():
        run=cp.own_run(conn,me,slug,run_id,write=False)
        after=0 if cursor is None else int(cursor)
        if after<0:
            raise ValueError("Invalid cursor.")
        messages=db.many(conn,'SELECT to_jsonb(m) FROM projectops.orchestration_message m WHERE run_id=%s AND id>%s ORDER BY id LIMIT 201',(run_id,after))
        return {'run':run,'tasks':db.tasks(conn,slug,run_id),
            'dispatches':[public_dispatch(d) for d in db.dispatches(conn,slug,run_id=run_id)],
            'gates':db.many(conn,'SELECT to_jsonb(g)-%s FROM projectops.orchestration_gate g WHERE run_id=%s ORDER BY created_at',('continuation',run_id)),
            'messages':messages[:200],'cursor':str(messages[199]['id']) if len(messages)>200 else None}
    return result(action)


def _counts(conn,me,slug):
    params=(slug,me.actor_id)
    gates=db.one(conn,"SELECT count(*) FROM projectops.orchestration_gate g JOIN projectops.orchestration_run r ON r.id=g.run_id WHERE r.project_slug=%s AND r.created_by=%s AND g.status='open'",params)
    proposals=db.one(conn,"SELECT count(*) FROM projectops.assistant_proposal WHERE project_slug=%s AND owner_id=%s AND status='pending' AND dispatch_id IS NULL",params)
    dispatches=db.one(conn,"SELECT count(*) FROM projectops.orchestration_dispatch d JOIN projectops.orchestration_run r ON r.id=d.run_id WHERE r.project_slug=%s AND r.created_by=%s AND d.status IN ('queued','running') AND d.superseded_by IS NULL",params)
    flows=db.one(conn,"""SELECT count(*) FROM projectops.flow_run f WHERE f.project_slug=%s AND f.status IN ('queued','running')
        AND NOT EXISTS(SELECT 1 FROM projectops.orchestration_run r JOIN projectops.orchestration_dispatch d ON d.run_id=r.id
            WHERE r.flow_run_id=f.id AND r.created_by=%s AND d.status IN ('queued','running') AND d.superseded_by IS NULL)""",params)
    finished_runs=db.one(conn,"SELECT count(*) FROM projectops.orchestration_run WHERE project_slug=%s AND created_by=%s AND status IN ('succeeded','failed','canceled')",params)
    finished_tasks=db.one(conn,"SELECT count(*) FROM projectops.orchestration_task t JOIN projectops.orchestration_run r ON r.id=t.run_id WHERE r.project_slug=%s AND r.created_by=%s AND t.status IN ('completed','failed','canceled')",params)
    roster=db.one(conn,'SELECT count(*) FROM projectops.agent_profile WHERE project_slug=%s',(slug,))
    roster+=db.one(conn,'SELECT count(*) FROM projectops.agent_limb WHERE allowed_projects ? %s',(slug,))
    return {'needs_you':gates+proposals,'working':dispatches+flows,'done':finished_runs+finished_tasks,'idle':roster}


def _page(groups,limit,cursor):
    try:
        anchors=json.loads(base64.urlsafe_b64decode(cursor+'='*((-len(cursor))%4))) if cursor else {}
    except (ValueError,TypeError):
        raise cp.OrchestrationError(400,"Invalid board cursor.") from None
    if not isinstance(anchors,dict) or set(anchors)-set(groups) or any(not isinstance(v,list) or len(v)!=2 or any(not isinstance(n,str) for n in v) for v in anchors.values()):
        raise cp.OrchestrationError(400,"Invalid board cursor.")
    next_anchors={**anchors}
    paged={}
    more=False
    for group,items in groups.items():
        items=sorted(items,key=lambda row:(row.get('created_at',''),row['id']),reverse=True)
        if group in anchors:
            items=[row for row in items if (row.get('created_at',''),row['id'])<tuple(anchors[group])]
        selected=items[:limit]
        paged[group]=selected
        if selected:
            next_anchors[group]=[selected[-1].get('created_at',''),selected[-1]['id']]
        more=more or len(items)>limit
    encoded=base64.urlsafe_b64encode(json.dumps(next_anchors).encode()).decode().rstrip('=') if more else None
    return paged,encoded


def board(conn,me,slug,*,cursor=None,limit=50,counts_only=False):
    def action():
        cp.actor(conn,slug,me,write=False)
        page_size=int(limit)
        if not 1<=page_size<=200 or (cursor and (not isinstance(cursor,str) or len(cursor)>4096)):
            raise cp.OrchestrationError(400,"Invalid board pagination parameters.")
        counts=_counts(conn,me,slug)
        groups={'needs_you':[],'working':[],'done':[],'idle':[]}
        if counts_only:
            return {**groups,'counts':counts,'cursor':None}
        runs=db.many(conn,'SELECT to_jsonb(r) FROM projectops.orchestration_run r WHERE project_slug=%s AND created_by=%s ORDER BY created_at',(slug,me.actor_id))
        run_ids=[r['id'] for r in runs]
        tasks=db.many(conn,'SELECT to_jsonb(t) FROM projectops.orchestration_task t WHERE project_slug=%s AND run_id=ANY(%s::uuid[])',(slug,run_ids)) if run_ids else []
        by_task={task['id']:task for task in tasks}
        dispatches=db.many(conn,'SELECT to_jsonb(d) FROM projectops.orchestration_dispatch d WHERE project_slug=%s AND run_id=ANY(%s::uuid[])',(slug,run_ids)) if run_ids else []
        by_dispatch={d['id']:d for d in dispatches}
        proposals={p['id']:p for p in store.proposals(conn,slug,owner_id=me.actor_id,limit=10000)}
        gates=db.many(conn,"SELECT to_jsonb(g) FROM projectops.orchestration_gate g WHERE project_slug=%s AND run_id=ANY(%s::uuid[]) AND status='open'",(slug,run_ids)) if run_ids else []
        for gate in gates:
            task=by_task[gate['task_id']]
            dispatch=by_dispatch.get(gate['dispatch_id'],{})
            ids=([p['id'] for p in proposals.values() if p.get('race_group_task_id')==task['id'] and p['status']=='pending'
                    and by_dispatch.get(p.get('dispatch_id'),{}).get('status')=='awaiting_gate' and not by_dispatch.get(p.get('dispatch_id'),{}).get('superseded_by')]
                 if gate['gate_kind']=='race_select' else [p for p in gate['options'] if type(p) is int and p in proposals and proposals[p]['status']=='pending']
                 if gate['gate_kind']=='proposal_review' else [])
            groups['needs_you'].append({'id':'gate:'+gate['id'],'kind':gate['gate_kind'],'gate_id':gate['id'],'run_id':gate['run_id'],
                'task_id':task['id'],'agent_key':dispatch.get('agent_key',task['target_agent_key']),'title':task['title'],
                'question':gate['question'],'options':gate['options'],'status':'awaiting_gate','target':task['target'],
                'proposal_ids':ids,'proposals':[proposals[p] for p in ids],'created_at':gate['created_at'],
                'context':(gate['continuation'] or {}).get('action',{}).get('preview'),
                'candidates':[{ 'agent_key':key,**next(({'status':d['status'],'error':d['error'],
                    'model':d.get('executed_model') or d['profile_snapshot'].get('provider_config',{}).get('model',''),
                    'display_name':d['profile_snapshot'].get('display_name',key),'icon':d['profile_snapshot'].get('icon','✦')}
                    for d in sorted(dispatches,key=lambda row:row['admission_no'],reverse=True) if d['task_id']==task['id'] and d['agent_key']==key and not d['superseded_by']),{'status':'queued'})}
                    for key in task.get('race_agents',[])]})
        for proposal in proposals.values():
            if proposal['status']=='pending' and not proposal.get('dispatch_id'):
                groups['needs_you'].append({'id':'proposal:'+str(proposal['id']),'kind':'proposal_review','proposal_ids':[proposal['id']],
                    'proposals':[proposal],'target':proposal['target'],'title':proposal['target'].get('tab_title','待核對修改'),
                    'status':'awaiting_gate','created_at':proposal['created_at']})
        for dispatch in dispatches:
            if dispatch['status'] in ('queued','running') and not dispatch['superseded_by']:
                task=by_task[dispatch['task_id']]
                groups['working'].append({'id':'dispatch:'+dispatch['id'],'kind':'dispatch','run_id':dispatch['run_id'],'task_id':task['id'],
                    'dispatch_id':dispatch['id'],'admission_no':dispatch['admission_no'],'dispatch_handle':cp.handle(dispatch),
                    'title':task['title'],'status':dispatch['status'],'agent_key':dispatch['agent_key'],'target':{**task_target(task),**({'row_id':dispatch['row_id']} if dispatch['row_id'] else {})},
                    'tools_trace':dispatch['tools_trace'][-10:],'created_at':dispatch['created_at'],'error':dispatch['error']})
        flows=db.many(conn,"""SELECT to_jsonb(f) FROM projectops.flow_run f WHERE f.project_slug=%s AND f.status IN ('queued','running')
            AND NOT EXISTS(SELECT 1 FROM projectops.orchestration_run r JOIN projectops.orchestration_dispatch d ON d.run_id=r.id
                WHERE r.flow_run_id=f.id AND r.created_by=%s AND d.status IN ('queued','running') AND d.superseded_by IS NULL)""",(slug,me.actor_id))
        for flow in flows:
            tab=repo.get_tab(conn,slug,flow['tab_key'])
            groups['working'].append({'id':'flow:'+flow['id'],'kind':'flow','flow_run_id':flow['id'],'title':tab['title'] if tab else flow['tab_key'],
                'status':flow['status'],'target':{'tab_key':flow['tab_key']},'created_at':flow['created_at'],'can_cancel':flow['created_by']==me.actor_id or me.can_edit})
        for task in tasks:
            if task['status'] in ('completed','failed','canceled'):
                groups['done'].append({'id':'task:'+task['id'],'kind':'task','run_id':task['run_id'],'task_id':task['id'],
                    'title':task['title'],'status':task['status'],'summary':task['result_summary'],'target':task_target(task),
                    'flow_bound':bool(task.get('flow_task_id') or task['input_snapshot'].get('flow_run_id')),
                    'error':task['error'],'failure':_failure(dispatches,task) if task['status']=='failed' else None,'created_at':task['created_at']})
        for run in runs:
            if run['status'] in ('succeeded','failed','canceled'):
                target=next((t['target'] for t in reversed(tasks) if t['run_id']==run['id'] and t['target'].get('tab_key')), {})
                groups['done'].append({'id':'run:'+run['id'],'kind':'run','run_id':run['id'],'title':run['objective'],
                    'status':run['status'],'summary':run['summary'],'target':target,'created_at':run['created_at']})
        for agent in agent_registry.roster(conn,me,slug):
            groups['idle'].append({k:agent.get(k) for k in ('agent_key','display_name','icon','role_kind','runtime_kind','capabilities','labels','status','active_dispatches','max_concurrency','enabled','can_propose_table','can_propose_document')}|
                                 {'id':'agent:'+agent['agent_key'],'kind':'agent','created_at':''})
        pages,next_cursor=_page(groups,page_size,cursor)
        return {**pages,'counts':counts,'cursor':next_cursor}
    return result(action)


def cancel_run_request(conn,me,slug,run_id,body):
    def action():
        object_body(body,('reason','client_request_id'))
        reason=body.get('reason','已取消整批工作')
        if not isinstance(reason,str) or len(reason)>1000:
            raise cp.OrchestrationError(400,"Cancellation reasons support up to 1,000 characters.")
        return cp.cancel_run(conn,me,slug,run_id,reason)
    return result(action)


def cancel_dispatch_request(conn,me,slug,dispatch_id,body):
    def action():
        object_body(body,('admission_no','reason','client_request_id'))
        if type(body.get('admission_no')) is not int or body['admission_no']<=0:
            raise cp.OrchestrationError(400,"Cancellation requires the exact admission_no.")
        reason=body.get('reason','已取消')
        if not isinstance(reason,str) or len(reason)>1000:
            raise cp.OrchestrationError(400,"Cancellation reasons support up to 1,000 characters.")
        return cp.cancel_dispatch(conn,me,slug,f'dsp_{db.identifier(dispatch_id)}_{body["admission_no"]}',reason)
    return result(action)


def resolve_gate_request(conn,me,slug,gate_id,body):
    def action():
        object_body(body,('client_request_id','resolution'))
        nonce=body.get('client_request_id')
        if not isinstance(nonce,str) or not 1<=len(nonce)<=128:
            raise cp.OrchestrationError(400,"Provide a client_request_id for this decision.")
        cp.lock_project(conn,slug)
        gate=db.get_gate(conn,slug,gate_id)
        if not gate:
            raise cp.OrchestrationError(404,"Question not found.")
        cp.own_run(conn,me,slug,gate['run_id'])
        if gate['gate_kind']=='race_select':
            value=body.get('resolution')
            if not isinstance(value,dict) or type(value.get('proposal_id')) is not int:
                raise cp.OrchestrationError(400,"Select a candidate proposal.")
            return cp.select_race_winner(conn,me,slug,gate_id,value['proposal_id'],client_request_id=body.get('client_request_id'))
        if gate['gate_kind']=='proposal_review':
            from project_assistant import service
            value=body.get('resolution')
            if (not isinstance(value,dict) or set(value)-{'proposal_id','decision'} or type(value.get('proposal_id')) is not int
                or value['proposal_id'] not in gate['options'] or value.get('decision','apply') not in ('apply','dismiss')):
                raise cp.OrchestrationError(400,"Review a proposal listed by this gate.")
            fingerprint=cp.digest(value)
            prior=db.one(conn,"SELECT payload FROM projectops.orchestration_message WHERE run_id=%s AND msg_type='system' AND payload->>'gate_id'=%s AND payload->>'gate_resolution_request_id'=%s",
                         (gate['run_id'],gate_id,nonce))
            if prior:
                if prior['decision_hash']!=fingerprint:
                    raise cp.OrchestrationError(409,"This request ID already has a different review decision.")
                return {'gate':db.get_gate(conn,slug,gate_id),'proposal':store.proposal(conn,prior['proposal_id'])}
            code,payload=service.apply_proposal(conn,me,slug,value['proposal_id'],{}) if value.get('decision','apply')=='apply' else service.dismiss_proposal(conn,me,slug,value['proposal_id'])
            if code>=400:
                raise cp.OrchestrationError(code,payload.get('error','核對失敗'))
            dispatch=db.get_dispatch(conn,slug,gate['dispatch_id'])
            db.event(conn,dispatch,'system','使用者完成提案核對',{'gate_id':gate_id,'gate_resolution_request_id':nonce,
                'decision_hash':fingerprint,'proposal_id':value['proposal_id'],'actor_id':me.actor_id})
            return {'gate':db.get_gate(conn,slug,gate_id),**payload}
        return {'gate':cp.resolve_gate(conn,me,slug,gate_id,resolution=body.get('resolution'),client_request_id=body.get('client_request_id'))}
    return result(action)


def retry_task_request(conn,me,slug,task_id,body):
    def action():
        object_body(body,('client_request_id','reason'))
        nonce=body.get('client_request_id')
        if not isinstance(nonce,str) or not 1<=len(nonce)<=128:
            raise cp.OrchestrationError(400,"Provide a retry request ID.")
        cp.lock_project(conn,slug)
        task=db.get_task(conn,slug,task_id)
        if not task:
            raise cp.OrchestrationError(404,"Task not found.")
        run=cp.own_run(conn,me,slug,task['run_id'],cancel=True)
        prior=db.one(conn,"SELECT payload FROM projectops.orchestration_message WHERE task_id=%s AND msg_type='system' AND payload->>'retry_request_id'=%s",(task_id,nonce))
        if prior:
            return prior
        if run['status']=='canceled' or task['status'] not in ('failed','canceled'):
            raise cp.OrchestrationError(409,"Canceled batches and tasks that have not failed cannot be retried here. Create a new assignment.")
        if task['input_snapshot'].get('story_media'):
            raise cp.OrchestrationError(409,"Reconcile any provider job, then create a new reviewed media allocation; internal media is never automatically resubmitted.")
        if task.get('flow_task_id'):
            raise cp.OrchestrationError(409,"Retry this step from pipeline history to preserve dependency order.")
        latest=[d for d in db.dispatches(conn,slug,task_id) if not d['superseded_by'] and d['status'] in ('failed','timeout','canceled')]
        if not latest:
            raise cp.OrchestrationError(409,"This task has not been dispatched. Resolve upstream issues first.")
        admitted=[cp.spawn_dispatch(conn,slug,task_id,agent_key=d['agent_key'],slot_key=d['slot_key']) for d in latest]
        descendants={task_id}
        for candidate in db.tasks(conn,slug,run['id']):
            if descendants.intersection(candidate['depends_on']) and not db.dispatches(conn,slug,candidate['id']):
                descendants.add(candidate['id'])
                db.execute(conn,"UPDATE projectops.orchestration_task SET status='pending',error=NULL WHERE id=%s",(candidate['id'],))
        payload={'task_id':task_id,'dispatch_handles':[cp.handle(d) for d in admitted],'retry_request_id':nonce}
        db.event(conn,admitted[0],'system','使用者要求重試',payload)
        cp.refresh_run(conn,slug,run['id'])
        repo.add_audit(conn,slug,action='orchestration_retry',actor_id=me.actor_id,target=task_id,detail={'client_request_id':nonce})
        return payload
    return result(action)
