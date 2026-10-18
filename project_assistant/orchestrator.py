"""Durable, project-fenced orchestration with reviewable canvas writes."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import hmac
import re
import secrets
import uuid

from project_assistant import agent_registry,privacy,request_scope
from project_assistant import orchestration_store as db
from project_docs import repository as repo

OrchestrationError=agent_registry.AgentError
ACTIVE_RUNS=('active','awaiting_gate')
TERMINAL_DISPATCHES=('succeeded','failed','timeout','canceled')


def now():
    return dt.datetime.now(dt.timezone.utc)


def instant(value):
    if value is None:
        return None
    try:
        result=value if isinstance(value,dt.datetime) else dt.datetime.fromisoformat(value)
        if not result.tzinfo:
            raise ValueError()
        return result
    except (ValueError,TypeError,AttributeError):
        raise OrchestrationError(400,'截止時間必須包含時區') from None


def lock_project(conn,slug):
    # ponytail: one short control transaction per project; shard locks only if measured queue throughput requires it.
    db.execute(conn,"SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",('openbench-orchestration:'+slug,))


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()).hexdigest()


def actor(conn,slug,me,write=True):
    if not repo.get_project(conn,slug):
        raise OrchestrationError(404,'找不到這個專案')
    member=next((m for m in repo.active_members(conn) if m['actor_id']==me.actor_id),None)
    from project_assistant import store
    if not member or (write and member['role']=='viewer') or not store.is_member_enabled(conn,slug,me.actor_id):
        raise OrchestrationError(403,'目前沒有執行此工作的權限')
    return member


def own_run(conn,me,slug,run_id,*,cancel=False,lock=False,write=True):
    actor(conn,slug,me,write=write)
    run=db.get_run(conn,slug,run_id,lock)
    if not run or (run['created_by']!=me.actor_id and not (cancel and me.can_edit)):
        raise OrchestrationError(404,'找不到這個工作')
    return run


def create_run(conn,me,slug,objective,*,client_request_id,limits=None,conversation_id=None,deadline_at=None,request_payload=None):
    actor(conn,slug,me)
    if not isinstance(objective,str) or not 1<=len(objective.strip())<=4000:
        raise OrchestrationError(400,'工作描述需要 1～4000 字')
    if not isinstance(client_request_id,str) or not 1<=len(client_request_id)<=128:
        raise OrchestrationError(400,'請提供可重送的 client_request_id')
    limits={} if limits is None else limits
    if not isinstance(limits,dict) or set(limits)-{'max_depth','max_parallel_dispatches','max_tasks_per_run'}:
        raise OrchestrationError(400,'執行限制格式不對')
    values={'max_depth':1,'max_parallel_dispatches':6,'max_tasks_per_run':200,**limits}
    if any(type(v) is not int or not 1<=v<={'max_depth':2,'max_parallel_dispatches':6,'max_tasks_per_run':200}[k] for k,v in values.items()):
        raise OrchestrationError(400,'執行限制超出允許範圍')
    deadline=instant(deadline_at)
    if deadline and deadline<=now():
        raise OrchestrationError(400,'工作截止時間已過')
    if conversation_id is not None:
        found=db.one(conn,'SELECT id FROM projectops.assistant_conversation WHERE project_slug=%s AND owner_id=%s AND id=%s',
                     (slug,me.actor_id,conversation_id))
        if not found:
            raise OrchestrationError(404,'找不到這段對話')
    request_hash=digest({'objective':objective,'limits':values,'conversation_id':conversation_id,'deadline':deadline.isoformat() if deadline else None,'request_payload':request_payload})
    lock_project(conn,slug)
    existing=db.one(conn,'SELECT to_jsonb(r) FROM projectops.orchestration_run r WHERE project_slug=%s AND created_by=%s AND client_request_id=%s',
                    (slug,me.actor_id,client_request_id))
    if existing:
        if existing['request_hash']!=request_hash:
            raise OrchestrationError(409,'相同請求編號的工作內容已變更')
        return existing
    identifier=str(uuid.uuid4())
    objective=privacy.sanitize(objective,privacy.mode(conn,slug))
    db.execute(conn,'''INSERT INTO projectops.orchestration_run(id,project_slug,created_by,objective,client_request_id,request_hash,
        conversation_id,max_depth,max_parallel_dispatches,max_tasks_per_run,deadline_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
        (identifier,slug,me.actor_id,objective,client_request_id,request_hash,conversation_id,
         values['max_depth'],values['max_parallel_dispatches'],values['max_tasks_per_run'],deadline))
    repo.add_audit(conn,slug,action='orchestration_start',actor_id=me.actor_id,target=identifier,detail={'client_request_id':client_request_id})
    return db.get_run(conn,slug,identifier)


def freeze_tab(conn,slug,key):
    tab=repo.get_tab(conn,slug,key)
    if not tab:
        raise OrchestrationError(409,'來源或輸出分頁已刪除','SOURCE_CHANGED')
    return {**tab,'values':repo.field_values(conn,slug).get(key,{})}


def _locked_snapshot(conn,slug,key):
    tab=repo.get_tab_for_update(conn,slug,key)
    if not tab:
        raise OrchestrationError(409,'來源分頁已刪除','SOURCE_CHANGED')
    return {**tab,'key':key,'values':repo.field_values(conn,slug).get(key,{})}


def _task_source_matches(task,key,current):
    scope=task.get('request_scope')
    if scope and scope['target_tab']==key:
        request_scope.verify_source(scope,current,current['values'])
    elif task['input_snapshot']['tabs'][key]['revision']!=current['revision']:
        raise OrchestrationError(409,'來源版本已變更，請重新交辦','SOURCE_CHANGED')


def _save_task_sources(conn,task,tabs):
    source=copy.deepcopy(task['input_snapshot'])
    source['tabs'].update(tabs)
    scope=task['request_scope']
    if scope and scope['target_tab'] in tabs:
        tab=tabs[scope['target_tab']]
        scope=request_scope.validate_scope({**scope,'base_revision':tab['revision']},tab,tab['values'])
    target_snapshot=task['target_snapshot']
    if task['target'].get('tab_key') in tabs:
        tab=tabs[task['target']['tab_key']]
        target_snapshot={key:tab[key] for key in ('doc','title','revision','values')}
    db.execute(conn,'''UPDATE projectops.orchestration_task SET input_snapshot=%s::jsonb,target_snapshot=%s::jsonb,
        request_scope=%s::jsonb,updated_at=NOW() WHERE id=%s''',
        (json.dumps(source),json.dumps(target_snapshot),json.dumps(scope),task['id']))


def _refresh_dependency_sources(conn,task):
    """Freeze at readiness, after checking the expected, approved upstream state."""
    tabs={key:_locked_snapshot(conn,task['project_slug'],key) for key in sorted(task['input_snapshot']['tabs'])}
    for key,tab in tabs.items():
        _task_source_matches(task,key,tab)
    _save_task_sources(conn,task,tabs)


def _advance_dependent_sources(conn,completed_task,source_before):
    if not source_before:
        return
    tasks={task['id']:task for task in db.tasks(conn,completed_task['project_slug'],completed_task['run_id'])}
    key=source_before['key']
    after=None
    for task in tasks.values():
        if task['status']!='pending' or key not in task['input_snapshot']['tabs']:
            continue
        ancestors=set();queue=list(task['depends_on'])
        while queue:
            identifier=queue.pop()
            if identifier not in ancestors:
                ancestors.add(identifier);queue.extend(tasks[identifier]['depends_on'])
        if completed_task['id'] not in ancestors:
            continue
        try:
            _task_source_matches(task,key,source_before)
        except (ValueError,OrchestrationError):
            continue  # Keep the old guard: readiness must reject the unrelated edit.
        after=after or _locked_snapshot(conn,task['project_slug'],key)
        _save_task_sources(conn,task,{key:after})


def create_task(conn,me,slug,run_id,*,objective,agent_key=None,label_selector=None,scope=None,target=None,
                depends_on=(),strategy='single',write_mode='proposal',parent_dispatch_id=None):
    lock_project(conn,slug)
    run=own_run(conn,me,slug,run_id,lock=True)
    if run['status'] not in ACTIVE_RUNS:
        raise OrchestrationError(409,'工作已結束，請建立新的工作')
    if not isinstance(objective,str) or not 1<=len(objective.strip())<=4000 or strategy not in ('single','race','fanout_rows') or write_mode not in ('proposal','analysis_only'):
        raise OrchestrationError(400,'任務描述、策略或寫入模式不正確')
    existing=db.tasks(conn,slug,run_id)
    if len(existing)>=run['max_tasks_per_run']:
        raise OrchestrationError(409,'已達本次工作任務上限','CAPACITY_EXCEEDED')
    if not isinstance(depends_on,(list,tuple)) or len(depends_on)>200 or len(set(depends_on))!=len(depends_on):
        raise OrchestrationError(400,'相依任務格式不正確或重複')
    dependency_ids=[db.identifier(k) for k in depends_on]
    known={t['id']:t for t in existing}
    if any(k not in known for k in dependency_ids):
        raise OrchestrationError(400,'相依任務必須屬於同一個工作且已存在')
    # Only references to existing tasks are accepted: no mutation of a dispatched graph, so cycles cannot be introduced.
    selector=label_selector or {}
    if not isinstance(selector,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in selector.items()):
        raise OrchestrationError(400,'代理標籤格式不正確')
    if agent_key and selector:
        raise OrchestrationError(400,'請指定代理或使用標籤配對，不能同時使用')
    if agent_key and not isinstance(agent_key,str):
        raise OrchestrationError(400,'代理代號格式不正確')
    if not agent_key:
        candidates=[p for p in agent_registry.list_agents(conn,slug,labels=selector) if p['enabled'] and p['role_kind']!='observer']
        if not candidates:
            raise OrchestrationError(400,'沒有符合標籤的可用代理')
        agent_key=sorted(candidates,key=lambda p:p['agent_key'])[0]['agent_key'] if selector else 'coordinator'
    profile=agent_registry.get_agent(conn,slug,agent_key)
    if agent_key.startswith('limb:'):
        from project_assistant import limbs
        limb=next((w for w in limbs.enabled_workers(conn,slug) if 'limb:'+w['id']==agent_key),None)
        if not limb:
            raise OrchestrationError(400,'外部手腳不可用')
    elif not profile or not profile['enabled'] or profile['role_kind']=='observer':
        raise OrchestrationError(400,'指定代理不可用')
    if parent_dispatch_id:
        parent_scope_dispatch=db.get_dispatch(conn,slug,parent_dispatch_id)
        if not parent_scope_dispatch or parent_scope_dispatch['run_id']!=run_id:
            raise OrchestrationError(409,'父任務已失效','STALE_DISPATCH')
        parent_scope_task=db.get_task(conn,slug,parent_scope_dispatch['task_id'])
        parent_scope=effective_scope(conn,parent_scope_dispatch,parent_scope_task)
        if parent_scope:
            if scope is not None and not isinstance(scope,dict):
                raise OrchestrationError(400,'子任務處理範圍格式不正確')
            scope={**copy.deepcopy(parent_scope),**(scope or {})}
            request_scope.guard_child_scope(parent_scope,scope)
        parent_target=copy.deepcopy(parent_scope_task['target'])
        if parent_scope_dispatch.get('row_id') and parent_target.get('row_id'):
            parent_target['row_id']=parent_scope_dispatch['row_id']
        if write_mode=='proposal' and parent_target:
            target=copy.deepcopy(target or parent_target)
            if (not isinstance(target,dict) or target.get('tab_key')!=parent_target.get('tab_key')
                or target.get('kind','table')!=parent_target.get('kind','table')
                or any(k in parent_target and target.get(k)!=parent_target[k] for k in ('row_id','col_index','table_id'))
                or (parent_target.get('mode','append')=='append' and target.get('mode')=='replace')):
                raise OrchestrationError(403,'子任務不能擴大父任務的輸出位置或寫入方式','POLICY_DENIED')
    if target is not None and (not isinstance(target,dict) or set(target)-{'tab_key','kind','mode','row_id','col_index','table_id','after_block_id'}):
        raise OrchestrationError(400,'輸出位置格式不正確')
    target=copy.deepcopy(target or {})
    if target.get('kind','table') not in ('doc','table') or target.get('mode','append') not in ('append','replace'):
        raise OrchestrationError(400,'輸出型態或插入方式不正確')
    if 'col_index' in target and (type(target['col_index']) is not int or not 0<=target['col_index']<256):
        raise OrchestrationError(400,'輸出欄號必須為零起算整數')
    if any(k in target and not isinstance(target[k],str) for k in ('tab_key','row_id','table_id','after_block_id')):
        raise OrchestrationError(400,'輸出位置識別資料必須是文字')
    snapshots={}
    if scope is not None:
        if not isinstance(scope,dict):
            raise OrchestrationError(400,'處理範圍格式不正確')
        tab=freeze_tab(conn,slug,scope.get('target_tab'))
        scope=request_scope.validate_scope(scope,tab,tab['values'])
        snapshots[tab['key']]=tab
        if target.get('tab_key') and target['tab_key']!=scope['target_tab']:
            raise OrchestrationError(400,'輸出不能超出固定的資料範圍')
        if write_mode=='proposal' and not target:
            target={'tab_key':scope['target_tab'],'kind':'doc' if scope.get('kind')=='doc' else 'table'}
    if strategy=='fanout_rows' and (not scope or scope.get('kind')=='doc'):
        raise OrchestrationError(400,'逐列工作必須指定固定的表格列')
    if parent_dispatch_id:
        parent=db.get_dispatch(conn,slug,parent_dispatch_id)
        if not parent or parent['run_id']!=run_id or parent['status']!='running' or parent['superseded_by']:
            raise OrchestrationError(409,'父任務已失效','STALE_DISPATCH')
        parent_task=db.get_task(conn,slug,parent['task_id'])
        if parent_task['request_scope']:
            if scope is None:
                scope=copy.deepcopy(parent_task['request_scope'])
            request_scope.guard_child_scope(parent_task['request_scope'],scope)
        if parent_task['write_mode']=='analysis_only' and write_mode!='analysis_only':
            raise OrchestrationError(403,'子任務不能取得父任務沒有的寫入權限','POLICY_DENIED')
    target_snapshot=None
    if target.get('tab_key'):
        tab=snapshots.get(target['tab_key']) or freeze_tab(conn,slug,target['tab_key'])
        snapshots[tab['key']]=tab
        target_snapshot={'doc':tab['doc'],'title':tab['title'],'revision':tab['revision'],'values':tab['values']}
    identifier=str(uuid.uuid4())
    objective=privacy.sanitize(objective,privacy.mode(conn,slug))
    status='ready' if all(known[k]['status']=='completed' for k in dependency_ids) else 'pending'
    db.execute(conn,'''INSERT INTO projectops.orchestration_task(id,run_id,project_slug,title,spec,strategy,target_agent_key,label_selector,
        request_scope,target,depends_on,input_snapshot,target_snapshot,parent_dispatch_id,write_mode,status)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s,%s)''',
        (identifier,run_id,slug,objective[:160],objective,strategy,agent_key,json.dumps(selector),json.dumps(scope),json.dumps(target),
         json.dumps(dependency_ids),json.dumps({'tabs':snapshots}),json.dumps(target_snapshot),parent_dispatch_id,write_mode,status))
    return db.get_task(conn,slug,identifier)


def ready_tasks(conn,slug,run_id):
    return [task for task in db.tasks(conn,slug,run_id) if task['status']=='ready']


def handle(dispatch):
    return f'dsp_{dispatch["id"]}_{dispatch["admission_no"]}'


def parse_handle(value):
    match=re.fullmatch(r'dsp_([0-9a-f-]{36})_([1-9][0-9]{0,18})',str(value))
    if not match:
        raise OrchestrationError(400,'派發憑證格式不正確','STALE_DISPATCH')
    return db.identifier(match[1]),int(match[2])


def principal(identity):
    return str(identity['id'] if isinstance(identity,dict) else identity)


def runtime_profile(conn,slug,key):
    if key.startswith('limb:'):
        from project_assistant import limbs
        limb=next((w for w in limbs.enabled_workers(conn,slug) if 'limb:'+w['id']==key),None)
        if not limb:
            raise OrchestrationError(400,'外部手腳已停用或無權存取專案','POLICY_DENIED')
        return {'agent_key':key,'display_name':limb['name'],'icon':'🔌','enabled':True,'role_kind':'worker',
                'runtime_kind':'remote_limb','bound_limb_id':limb['id'],'allowed_tools':['propose','propose_table_edit'] if 'llm' in limb['capabilities'] else [],
                'capabilities':limb['capabilities'],'provider_config':{},'system_prompt':'','knowledge_pack':'','max_concurrency':1}
    profile=agent_registry.get_agent(conn,slug,key)
    if not profile or not profile['enabled'] or profile['role_kind']=='observer':
        raise OrchestrationError(400,'代理已停用或不可承接工作','POLICY_DENIED')
    return profile


def spawn_dispatch(conn,slug,task_id,*,agent_key,slot_key,caller_dispatch_id=None,requested_deadline=None,continuation=None):
    lock_project(conn,slug)
    task=db.get_task(conn,slug,task_id,True)
    if not task:
        raise OrchestrationError(404,'找不到任務')
    run=db.get_run(conn,slug,task['run_id'],True)
    if run['status']=='canceled' or task['status']=='completed':
        raise OrchestrationError(409,'工作已取消或完成','STALE_DISPATCH')
    if not isinstance(slot_key,str) or not 1<=len(slot_key)<=150:
        raise OrchestrationError(400,'派發槽格式不正確')
    profile=runtime_profile(conn,slug,agent_key)
    previous=db.one(conn,'''SELECT to_jsonb(d) FROM projectops.orchestration_dispatch d
        WHERE task_id=%s AND slot_key=%s ORDER BY attempt_no DESC LIMIT 1 FOR UPDATE''',(task_id,slot_key))
    if previous and previous['status'] in ('queued','running','awaiting_gate','succeeded') and continuation is None:
        return {**previous,'handle':handle(previous)}
    caller_id=caller_dispatch_id or task.get('parent_dispatch_id')
    parent=db.get_dispatch(conn,slug,caller_id) if caller_id else None
    if caller_id and (not parent or parent['run_id']!=run['id'] or parent['status'] in ('canceled','failed','timeout') or parent['superseded_by']):
        raise OrchestrationError(409,'父派發已失效','STALE_DISPATCH')
    if caller_dispatch_id and (parent['status']!='running' or not parent['lease_until'] or instant(parent['lease_until'])<=now()):
        raise OrchestrationError(409,'委派來源已失效','STALE_DISPATCH')
    if parent:
        caller_profile=runtime_profile(conn,slug,parent['agent_key'])
        if caller_profile['role_kind']!='primary':
            raise OrchestrationError(403,'只有主控代理可以委派子任務','POLICY_DENIED')
        chain=parent['chain']+['agent:'+agent_key]
        if 'agent:'+agent_key in parent['chain'] or len([v for v in chain if v.startswith('agent:')])-1>run['max_depth']:
            raise OrchestrationError(403,'委派深度超限或形成循環','POLICY_DENIED')
    else:
        chain=['user:'+run['created_by'],'agent:'+run['coordinator_key']]
        if agent_key!=run['coordinator_key']:
            chain.append('agent:'+agent_key)
    deadlines=[instant(v) for v in (requested_deadline,run.get('deadline_at'),parent.get('deadline_at') if parent else None,
                                   previous.get('deadline_at') if previous else None) if v is not None]
    deadline=min(deadlines) if deadlines else now()+dt.timedelta(seconds=240)
    if deadline<=now():
        raise OrchestrationError(409,'任務已超過截止時間','STALE_DISPATCH')
    retry_count=(previous['retry_count']+(1 if previous['status'] in ('failed','timeout') and continuation is None else 0)) if previous else 0
    if retry_count>=task['max_attempts']:
        raise OrchestrationError(409,'此派發槽已用完重試次數','POLICY_DENIED')
    identifier=str(uuid.uuid4())
    if previous:
        db.execute(conn,'UPDATE projectops.orchestration_dispatch SET superseded_by=%s WHERE id=%s',(identifier,previous['id']))
    db.execute(conn,'INSERT INTO projectops.orchestration_admission_seq(project_slug) VALUES(%s) ON CONFLICT DO NOTHING',(slug,))
    admission=db.one(conn,'UPDATE projectops.orchestration_admission_seq SET last_admission=last_admission+1 WHERE project_slug=%s RETURNING last_admission',(slug,))
    db.execute(conn,'''INSERT INTO projectops.orchestration_dispatch
        (id,run_id,task_id,project_slug,admission_no,agent_key,slot_key,attempt_no,retry_count,continuation,profile_snapshot,
         limb_id,row_id,chain,deadline_at,max_attempts) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s::jsonb,%s,%s)''',
        (identifier,run['id'],task_id,slug,admission,agent_key,slot_key,previous['attempt_no']+1 if previous else 1,retry_count,
         json.dumps(continuation),json.dumps(profile),profile.get('bound_limb_id'),slot_key[4:] if slot_key.startswith('row:') else '',
         json.dumps(chain),deadline,task['max_attempts']))
    db.execute(conn,"UPDATE projectops.orchestration_task SET status='dispatched',error=NULL,updated_at=NOW() WHERE id=%s",(task_id,))
    db.execute(conn,"UPDATE projectops.orchestration_run SET status='active',finished_at=NULL,updated_at=NOW() WHERE id=%s",(run['id'],))
    result=db.get_dispatch(conn,slug,identifier)
    db.event(conn,result,'dispatch',task['title'],{'handle':handle(result),'slot_key':slot_key})
    return {**result,'handle':handle(result)}


def claim_dispatch(conn,worker_id,supported_agent_keys,*,allowed_projects,lease_seconds=120):
    if not allowed_projects or not supported_agent_keys:
        return None
    projects=db.many(conn,'''SELECT DISTINCT project_slug FROM projectops.orchestration_dispatch
        WHERE status='queued' AND project_slug=ANY(%s) AND agent_key=ANY(%s) ORDER BY project_slug''',(allowed_projects,supported_agent_keys))
    for slug in projects:
        acquired=db.one(conn,'SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0))',('openbench-orchestration:'+slug,))
        if not acquired:
            continue
        candidates=db.many(conn,'''SELECT to_jsonb(d) FROM projectops.orchestration_dispatch d
            WHERE project_slug=%s AND status='queued' AND agent_key=ANY(%s) AND superseded_by IS NULL
            ORDER BY admission_no FOR UPDATE SKIP LOCKED''',(slug,supported_agent_keys))
        for candidate in candidates:
            run=db.get_run(conn,slug,candidate['run_id'])
            if run['status'] not in ACTIVE_RUNS or instant(candidate['deadline_at'])<=now():
                continue
            try:
                profile=runtime_profile(conn,slug,candidate['agent_key'])
                from project_docs.service import Identity
                actor(conn,slug,Identity(run['created_by'],'','member'))
            except OrchestrationError:
                continue
            if isinstance(worker_id,dict):
                if slug not in worker_id.get('allowed_projects',[]) or profile.get('bound_limb_id')!=worker_id['id']:
                    continue
                if not set(profile['capabilities']).intersection(worker_id.get('capabilities',[])):
                    continue
            elif profile['runtime_kind']!='builtin_llm':
                continue
            active=db.one(conn,"SELECT count(*) FROM projectops.orchestration_dispatch WHERE project_slug=%s AND agent_key=%s AND status='running'",(slug,candidate['agent_key']))
            active+=db.one(conn,"SELECT count(*) FROM projectops.assistant_message WHERE project_slug=%s AND agent_key=%s AND role='assistant' AND status='running'",(slug,candidate['agent_key']))
            run_count=db.one(conn,"SELECT count(*) FROM projectops.orchestration_dispatch WHERE run_id=%s AND status='running'",(run['id'],))
            if active>=profile['max_concurrency'] or run_count>=run['max_parallel_dispatches']:
                continue
            token=secrets.token_urlsafe(32)
            expiry=min(now()+dt.timedelta(seconds=max(1,min(120,lease_seconds))),instant(candidate['deadline_at']))
            token_hash=hashlib.sha256(token.encode()).hexdigest()
            db.execute(conn,"UPDATE projectops.orchestration_dispatch SET status='running',lease_owner=%s,lease_hash=%s,lease_until=%s,updated_at=NOW() WHERE id=%s",
                       (principal(worker_id),token_hash,expiry,candidate['id']))
            result=db.get_dispatch(conn,slug,candidate['id'])
            return {**result,'handle':handle(result),'lease_token':token}
    return None


def _authenticated_dispatch(conn,identity,dispatch_handle,token):
    identifier,admission=parse_handle(dispatch_handle)
    slug=db.one(conn,'SELECT project_slug FROM projectops.orchestration_dispatch WHERE id=%s',(identifier,))
    if not slug or (isinstance(identity,dict) and slug not in identity.get('allowed_projects',[])):
        raise OrchestrationError(404,'找不到這個派發')
    lock_project(conn,slug)
    dispatch=db.get_dispatch(conn,slug,identifier,True)
    if (dispatch['admission_no']!=admission or not token or dispatch['lease_owner']!=principal(identity)
        or not hmac.compare_digest(dispatch.get('lease_hash') or '',hashlib.sha256(str(token).encode()).hexdigest())):
        raise OrchestrationError(409,'派發憑證、Worker 或租約不相符','STALE_DISPATCH')
    return dispatch


def leased_dispatch(conn,identity,dispatch_handle,token):
    dispatch=_authenticated_dispatch(conn,identity,dispatch_handle,token)
    run=db.get_run(conn,dispatch['project_slug'],dispatch['run_id'])
    if (dispatch['superseded_by'] or dispatch['status']!='running' or run['status'] not in ACTIVE_RUNS
        or not dispatch['lease_until'] or instant(dispatch['lease_until'])<=now() or instant(dispatch['deadline_at'])<=now()):
        raise OrchestrationError(409,'派發已取消、過期或被重新派發','STALE_DISPATCH')
    runtime_profile(conn,dispatch['project_slug'],dispatch['agent_key'])
    task=db.get_task(conn,dispatch['project_slug'],dispatch['task_id'])
    if task.get('flow_task_id'):
        from project_assistant import flow_runner
        flow_id=db.one(conn,'SELECT run_id::text FROM projectops.limb_task WHERE id=%s',(task['flow_task_id'],))
        flow=flow_runner._get_run(conn,flow_id)
        if flow['status'] in ('failed','canceled'):
            raise OrchestrationError(409,'工作流已停止','STALE_DISPATCH')
        if flow.get('execution',{}).get('mode')=='single_step':
            try:
                flow_runner._check_source_revisions(conn,dispatch['project_slug'],flow['execution']['source_revisions'])
            except flow_runner.ExecutionError as exc:
                raise OrchestrationError(exc.status,str(exc),'SOURCE_CHANGED') from exc
    from project_docs.service import Identity
    actor(conn,dispatch['project_slug'],Identity(run['created_by'],'','member'))
    return dispatch


def renew_dispatch(conn,identity,dispatch_handle,lease_token):
    dispatch=leased_dispatch(conn,identity,dispatch_handle,lease_token)
    expiry=min(now()+dt.timedelta(seconds=120),instant(dispatch['deadline_at']))
    db.execute(conn,'UPDATE projectops.orchestration_dispatch SET lease_until=%s,updated_at=NOW() WHERE id=%s',(expiry,dispatch['id']))
    return {'handle':dispatch_handle,'lease_until':expiry.isoformat()}


def _dismiss_outputs(conn,dispatch):
    db.execute(conn,"UPDATE projectops.assistant_proposal SET status='dismissed',decided_at=NOW() WHERE dispatch_id=%s AND status='pending'",(dispatch['id'],))
    db.execute(conn,"UPDATE projectops.orchestration_gate SET status='dismissed',resolved_at=NOW() WHERE dispatch_id=%s AND status='open'",(dispatch['id'],))


def _settle_task(conn,task):
    dispatches=[d for d in db.dispatches(conn,task['project_slug'],task['id']) if not d['superseded_by']]
    if not dispatches:
        return
    expected=len(task['request_scope']['row_ids']) if task['strategy']=='fanout_rows' else 1
    statuses=[d['status'] for d in dispatches]
    winner=next((d for d in dispatches if d['id']==task['winning_dispatch_id']),None)
    if task['strategy']=='race' and winner and winner['status']=='succeeded':
        status='completed'
    elif any(s in ('queued','running') for s in statuses) or len(dispatches)<expected:
        status='dispatched'
    elif 'awaiting_gate' in statuses:
        status='awaiting_gate'
    elif all(s=='succeeded' for s in statuses):
        status='awaiting_gate' if task['strategy']=='race' and not task['winning_dispatch_id'] else 'completed'
    elif all(s=='canceled' for s in statuses):
        status='canceled'
    else:
        status='failed'
    summaries=[str((d.get('output_json') or {}).get('text',''))[:1000] for d in dispatches if d['status']=='succeeded']
    db.execute(conn,'UPDATE projectops.orchestration_task SET status=%s,result_summary=%s,updated_at=NOW() WHERE id=%s',
               (status,'\n'.join(summaries)[:4000],task['id']))


def refresh_run(conn,slug,run_id):
    tasks=db.tasks(conn,slug,run_id)
    for task in tasks:
        if task['status'] in ('dispatched','awaiting_gate'):
            _settle_task(conn,task)
    tasks=db.tasks(conn,slug,run_id)
    for task in tasks:
        if task['strategy']=='race':
            refresh_race_gate(conn,task)
        if task.get('flow_task_id'):
            from project_assistant.orchestration_flow import finish_profile_task
            finish_profile_task(conn,task['flow_task_id'])
    gates=db.many(conn,"SELECT to_jsonb(g) FROM projectops.orchestration_gate g WHERE run_id=%s AND status='open'",(run_id,))
    blocked={k for gate in gates for k in gate['blocking_task_ids']}
    changed=True
    while changed:
        changed=False
        by_id={t['id']:t for t in tasks}
        for task in tasks:
            if task['status'] not in ('pending','ready'):
                continue
            upstream=[by_id[k]['status'] for k in task['depends_on']]
            state='failed' if any(v in ('failed','canceled') for v in upstream) else 'ready' if all(v=='completed' for v in upstream) and task['id'] not in blocked else 'pending'
            if state!=task['status']:
                if state=='ready' and task['depends_on']:
                    try:
                        _refresh_dependency_sources(conn,task)
                    except (ValueError,OrchestrationError) as exc:
                        state='failed'
                        db.execute(conn,'UPDATE projectops.orchestration_task SET error=%s WHERE id=%s',('來源已變更，請重新交辦：'+str(exc),task['id']))
                task['status']=state
                db.execute(conn,'UPDATE projectops.orchestration_task SET status=%s,updated_at=NOW() WHERE id=%s',(state,task['id']))
                changed=True
    run=db.get_run(conn,slug,run_id)
    if not tasks and run.get('flow_run_id'):
        flow_status=db.one(conn,'SELECT status FROM projectops.flow_run WHERE id=%s',(run['flow_run_id'],))
        if flow_status in ('succeeded','failed','canceled'):
            db.execute(conn,'UPDATE projectops.orchestration_run SET status=%s,finished_at=NOW(),updated_at=NOW() WHERE id=%s',(flow_status,run_id))
    if not tasks or run['status']=='canceled':
        return
    states=[t['status'] for t in tasks]
    if any(v in ('ready','dispatched') for v in states):
        status='active'
    elif gates or 'awaiting_gate' in states:
        status='awaiting_gate'
    elif any(v in ('failed','canceled') for v in states):
        status='failed'
    elif all(v=='completed' for v in states):
        status='succeeded'
    else:
        status='active'
    if run.get('flow_run_id'):
        flow_status=db.one(conn,'SELECT status FROM projectops.flow_run WHERE id=%s',(run['flow_run_id'],))
        if flow_status in ('queued','running','awaiting_approval') and status=='succeeded':
            status='awaiting_gate' if flow_status=='awaiting_approval' else 'active'
        elif flow_status=='failed':
            status='failed'
        elif flow_status=='canceled':
            status='canceled'
    db.execute(conn,'''UPDATE projectops.orchestration_run SET status=%s,updated_at=NOW(),
        finished_at=CASE WHEN %s IN ('succeeded','failed','canceled') THEN COALESCE(finished_at,NOW()) ELSE NULL END WHERE id=%s''',
        (status,status,run_id))


def complete_dispatch(conn,identity,dispatch_handle,lease_token,*,outcome,output,proposal_ids):
    if outcome not in ('succeeded','failed','timeout','awaiting_gate') or not isinstance(output,dict):
        raise OrchestrationError(400,'Worker 回報格式不正確')
    try:
        encoded=json.dumps(output,ensure_ascii=False,allow_nan=False)
        fingerprint=digest({'outcome':outcome,'output':output,'proposal_ids':proposal_ids})
    except (ValueError,TypeError):
        raise OrchestrationError(400,'Worker 回報必須是有效 JSON') from None
    if len(encoded.encode())>2*1024*1024 or not isinstance(proposal_ids,list) or any(type(p) is not int for p in proposal_ids):
        raise OrchestrationError(400,'輸出過大或提案編號格式不正確')
    dispatch=_authenticated_dispatch(conn,identity,dispatch_handle,lease_token)
    if dispatch['output_digest'] and not dispatch['superseded_by'] and dispatch['status'] in ('succeeded','failed','timeout','awaiting_gate'):
        if dispatch['output_digest']!=fingerprint:
            raise OrchestrationError(409,'此派發已回報不同的結果','STALE_DISPATCH')
        return {'id':dispatch['id'],'handle':dispatch_handle,'status':dispatch['status']}
    waiting=dispatch['status']=='awaiting_gate' and outcome=='awaiting_gate' and not dispatch['superseded_by']
    if waiting and (instant(dispatch['deadline_at'])<=now() or db.get_run(conn,dispatch['project_slug'],dispatch['run_id'])['status']=='canceled'):
        raise OrchestrationError(409,'等待決策的派發已失效','STALE_DISPATCH')
    if not waiting:
        dispatch=leased_dispatch(conn,identity,dispatch_handle,lease_token)
    slug=dispatch['project_slug']
    task=db.get_task(conn,slug,dispatch['task_id'])
    safe_output=privacy.sanitize(output,privacy.mode(conn,slug))
    actual=db.many(conn,'SELECT id FROM projectops.assistant_proposal WHERE dispatch_id=%s ORDER BY id',(dispatch['id'],))
    if set(actual)!=set(proposal_ids):
        raise OrchestrationError(400,'提案必須屬於本次派發，且完整回報')
    status=outcome
    error=None
    if outcome=='succeeded':
        proposal_states=db.many(conn,'SELECT status FROM projectops.assistant_proposal WHERE dispatch_id=%s',(dispatch['id'],))
        status=('failed' if any(s in ('dismissed','failed') for s in proposal_states) else
                'succeeded' if all(s=='applied' for s in proposal_states) else 'awaiting_gate') if proposal_ids else 'succeeded'
        if status=='awaiting_gate':
            ensure_review_gate(conn,dispatch,proposal_ids)
        if not proposal_ids and task['write_mode']=='proposal' and task['target'].get('tab_key'):
            status='failed'
            error='任務沒有產生可核對的提案'
    elif outcome in ('failed','timeout'):
        error=str(safe_output.get('error') or 'Worker 執行失敗')[:2000]
        _dismiss_outputs(conn,dispatch)
    db.execute(conn,'''UPDATE projectops.orchestration_dispatch SET status=%s,output_json=%s::jsonb,output_digest=%s,error=%s,
        lease_until=NULL,finished_at=NOW(),updated_at=NOW() WHERE id=%s''',
        (status,json.dumps(safe_output,ensure_ascii=False),fingerprint,error,dispatch['id']))
    db.event(conn,dispatch,'worker_done',str(safe_output.get('text') or error or '執行回合結束')[:2000],
             {'outcome':status,'proposal_ids':proposal_ids})
    if status in ('failed','timeout') and output.get('retryable') is True and dispatch['retry_count']+1<task['max_attempts'] and instant(dispatch['deadline_at'])>now():
        spawn_dispatch(conn,slug,task['id'],agent_key=dispatch['agent_key'],slot_key=dispatch['slot_key'])
    refresh_run(conn,slug,task['run_id'])
    return {'id':dispatch['id'],'handle':dispatch_handle,'status':status}


def _cancel_one(conn,dispatch,reason):
    if dispatch['status'] in TERMINAL_DISPATCHES:
        return
    db.execute(conn,"UPDATE projectops.orchestration_dispatch SET status='canceled',error=%s,lease_until=NULL,finished_at=NOW(),updated_at=NOW() WHERE id=%s",(reason[:2000],dispatch['id']))
    _dismiss_outputs(conn,dispatch)
    db.event(conn,dispatch,'worker_done',reason[:2000],{'outcome':'canceled'})
    children=db.many(conn,'SELECT to_jsonb(t) FROM projectops.orchestration_task t WHERE parent_dispatch_id=%s',(dispatch['id'],))
    for task in children:
        for child in db.dispatches(conn,task['project_slug'],task['id']):
            _cancel_one(conn,child,reason)
        db.execute(conn,"UPDATE projectops.orchestration_task SET status='canceled',updated_at=NOW() WHERE id=%s AND status<>'completed'",(task['id'],))


def cancel_dispatch(conn,me,slug,dispatch_handle,reason):
    identifier,admission=parse_handle(dispatch_handle)
    lock_project(conn,slug)
    dispatch=db.get_dispatch(conn,slug,identifier,True)
    if not dispatch:
        raise OrchestrationError(404,'找不到派發')
    own_run(conn,me,slug,dispatch['run_id'],cancel=True)
    if dispatch['admission_no']!=admission or dispatch['superseded_by']:
        raise OrchestrationError(409,'取消指令的派發憑證已過期','STALE_DISPATCH')
    if dispatch['status']=='canceled':
        return {'canceled':True,'dispatch_handle':dispatch_handle}
    if dispatch['status'] in ('succeeded','failed','timeout'):
        raise OrchestrationError(409,'此派發已結束；取消不會復原已確認的內容')
    _cancel_one(conn,dispatch,privacy.sanitize(str(reason or '已取消'),privacy.mode(conn,slug)))
    refresh_run(conn,slug,dispatch['run_id'])
    repo.add_audit(conn,slug,action='orchestration_cancel',actor_id=me.actor_id,target=dispatch['id'],detail={'admission_no':admission})
    return {'canceled':True,'dispatch_handle':dispatch_handle}


def cancel_run(conn,me,slug,run_id,reason='已取消整批工作'):
    lock_project(conn,slug)
    run=own_run(conn,me,slug,run_id,cancel=True,lock=True)
    if run['status']=='canceled':
        return {'run_id':run_id,'status':'canceled'}
    if run['status'] in ('succeeded','failed'):
        raise OrchestrationError(409,'此工作已結束，取消不會復原已確認的內容')
    for dispatch in db.dispatches(conn,slug,run_id=run_id):
        _cancel_one(conn,dispatch,reason)
    db.execute(conn,"UPDATE projectops.orchestration_task SET status='canceled',updated_at=NOW() WHERE run_id=%s AND status NOT IN ('completed','failed','canceled')",(run_id,))
    db.execute(conn,"UPDATE projectops.orchestration_gate SET status='dismissed',resolved_at=NOW() WHERE run_id=%s AND status='open'",(run_id,))
    db.execute(conn,"UPDATE projectops.orchestration_run SET status='canceled',finished_at=NOW(),updated_at=NOW() WHERE id=%s",(run_id,))
    repo.add_audit(conn,slug,action='orchestration_cancel_run',actor_id=me.actor_id,target=run_id)
    return {'run_id':run['id'],'status':'canceled'}


def sweep(conn,project_slug=None):
    projects=db.many(conn,"SELECT DISTINCT project_slug FROM projectops.orchestration_run WHERE status IN ('active','awaiting_gate') AND (%s::text IS NULL OR project_slug=%s) ORDER BY project_slug",(project_slug,project_slug))
    changed=0
    for slug in projects:
        lock_project(conn,slug)
        runs=db.many(conn,"SELECT to_jsonb(r) FROM projectops.orchestration_run r WHERE project_slug=%s AND status IN ('active','awaiting_gate')",(slug,))
        for run in runs:
            for dispatch in db.dispatches(conn,slug,run_id=run['id']):
                if dispatch['status'] in TERMINAL_DISPATCHES or dispatch['superseded_by']:
                    continue
                expired=instant(dispatch['deadline_at'])<=now() or (run['deadline_at'] and instant(run['deadline_at'])<=now())
                abandoned=dispatch['status']=='running' and (not dispatch['lease_until'] or instant(dispatch['lease_until'])<=now())
                if expired or abandoned:
                    status='timeout' if expired else 'failed'
                    db.execute(conn,'UPDATE projectops.orchestration_dispatch SET status=%s,error=%s,lease_until=NULL,finished_at=NOW() WHERE id=%s',
                               (status,'任務逾時' if expired else 'Worker 租約失效',dispatch['id']))
                    _dismiss_outputs(conn,dispatch)
                    db.event(conn,dispatch,'worker_done','任務逾時或租約失效',{'outcome':status})
                    if abandoned and not expired and dispatch['retry_count']+1<dispatch['max_attempts']:
                        spawn_dispatch(conn,slug,dispatch['task_id'],agent_key=dispatch['agent_key'],slot_key=dispatch['slot_key'])
                    changed+=1
            refresh_run(conn,slug,run['id'])
    return changed


def open_gate(conn,ctx,*,question,options,blocking_task_ids=()):
    if not isinstance(question,str) or not 1<=len(question.strip())<=4000 or not isinstance(options,list) or not 2<=len(options)<=5:
        raise OrchestrationError(400,'問題需要文字及 2～5 個選項')
    if any(not isinstance(option,str) or not 1<=len(option.strip())<=500 for option in options) or len(set(options))!=len(options):
        raise OrchestrationError(400,'選項必須為不重複的簡短文字')
    dispatch=leased_dispatch(conn,ctx.worker_id,f'dsp_{ctx.dispatch_id}_{ctx.admission_no}',ctx.lease_token)
    known={t['id'] for t in db.tasks(conn,ctx.slug,dispatch['run_id'])}
    if not isinstance(blocking_task_ids,(tuple,list)) or any(k not in known for k in blocking_task_ids):
        raise OrchestrationError(400,'阻擋的任務必須屬於同一批工作')
    continuation=dispatch['continuation'] or {}
    for answer in continuation.get('answers',[]):
        if answer['question']==question and answer.get('options')==options:
            return {'decision':answer['answer'],'awaiting_gate':False}
    existing=db.one(conn,"SELECT to_jsonb(g) FROM projectops.orchestration_gate g WHERE dispatch_id=%s AND gate_kind='question' AND status='open'",(dispatch['id'],))
    if existing:
        return existing
    identifier=str(uuid.uuid4())
    mode=privacy.mode(conn,ctx.slug)
    choices=[{'id':str(index),'label':privacy.sanitize(label,mode)} for index,label in enumerate(options)]
    db.execute(conn,'''INSERT INTO projectops.orchestration_gate(id,run_id,task_id,dispatch_id,project_slug,question,options,blocking_task_ids,continuation)
        VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb)''',
        (identifier,dispatch['run_id'],dispatch['task_id'],dispatch['id'],ctx.slug,privacy.sanitize(question,mode),
         json.dumps(choices),json.dumps(list(blocking_task_ids)),json.dumps(continuation)))
    db.execute(conn,"UPDATE projectops.orchestration_dispatch SET status='awaiting_gate',lease_until=NULL,updated_at=NOW() WHERE id=%s",(dispatch['id'],))
    db.execute(conn,"UPDATE projectops.orchestration_task SET status='awaiting_gate',updated_at=NOW() WHERE id=%s",(dispatch['task_id'],))
    db.event(conn,dispatch,'question',privacy.sanitize(question,mode),{'gate_id':identifier})
    refresh_run(conn,ctx.slug,dispatch['run_id'])
    return db.get_gate(conn,ctx.slug,identifier)


def resolve_gate(conn,me,slug,gate_id,*,resolution,client_request_id):
    if not isinstance(client_request_id,str) or not 1<=len(client_request_id)<=128:
        raise OrchestrationError(400,'請提供決定的 client_request_id')
    lock_project(conn,slug)
    gate=db.get_gate(conn,slug,gate_id,True)
    if not gate:
        raise OrchestrationError(404,'找不到這個待決定問題')
    run=own_run(conn,me,slug,gate['run_id'],lock=True)
    if gate['status']=='resolved':
        if gate['resolution']==resolution:
            return gate
        raise OrchestrationError(409,'這個問題已經有不同決定')
    if gate['status']!='open' or run['status']=='canceled':
        raise OrchestrationError(409,'這個問題已取消')
    if gate['gate_kind']!='question':
        raise OrchestrationError(400,'請從提案核對卡選擇版本')
    choice=next((o for o in gate['options'] if o['id']==resolution),None)
    if not choice:
        raise OrchestrationError(400,'請選擇目前問題提供的選項')
    dispatch=db.get_dispatch(conn,slug,gate['dispatch_id'])
    if dispatch['superseded_by'] or instant(dispatch['deadline_at'])<=now():
        raise OrchestrationError(409,'此問題的工作已過期','STALE_DISPATCH')
    action=(gate['continuation'] or {}).get('action') or {}
    flow_id=None
    if action.get('kind')=='flow_start' and resolution=='0':
        from project_assistant import flow_runner
        preview=flow_runner.preflight(conn,me,slug,action['flow_tab_key'],action['body'])
        if preview.get('errors') or preview['definition_revision']!=action['preview']['definition_revision'] or preview['source_revisions']!=action['preview']['source_revisions']:
            raise OrchestrationError(409,'流程設定、來源或服務已改變，請重新核對','SOURCE_CHANGED')
        flow_id=flow_runner.start(conn,me,slug,action['flow_tab_key'],action['body'])['run']['id']
        db.execute(conn,'UPDATE projectops.orchestration_run SET flow_run_id=%s WHERE id=%s',(flow_id,run['id']))
    continuation=copy.deepcopy(dispatch['continuation'] or {})
    continuation.setdefault('answers',[]).append({'question':gate['question'],'options':[o['label'] for o in gate['options']],'answer':choice['label'],**({'flow_run_id':flow_id} if flow_id else {})})
    for entry in continuation.get('journal',{}).values():
        if entry.get('gate_id')==gate['id']:
            entry['result']=json.dumps({'decision':choice['label'],'awaiting_gate':False},ensure_ascii=False)
    if action.get('kind')=='flow_start':
        continuation.setdefault('journal',{})[action['tool_cache_key']]={'tool':'trigger_flow_run',
            'result':json.dumps({'flow_run_id':flow_id,'decision':choice['label'],'awaiting_gate':False},ensure_ascii=False)}
    db.execute(conn,"UPDATE projectops.orchestration_gate SET status='resolved',resolution=%s::jsonb,resolution_request_id=%s,resolved_by=%s,resolved_at=NOW() WHERE id=%s",
               (json.dumps(resolution),client_request_id,me.actor_id,gate['id']))
    if action.get('control_only'):
        state='succeeded' if flow_id else 'canceled'
        db.execute(conn,'UPDATE projectops.orchestration_dispatch SET status=%s,updated_at=NOW() WHERE id=%s',(state,dispatch['id']))
        db.execute(conn,'UPDATE projectops.orchestration_task SET status=%s,updated_at=NOW() WHERE id=%s',('completed' if flow_id else 'canceled',gate['task_id']))
        if not flow_id:
            db.execute(conn,"UPDATE projectops.orchestration_run SET status='canceled',finished_at=NOW() WHERE id=%s",(run['id'],))
        refresh_run(conn,slug,run['id'])
        return db.get_gate(conn,slug,gate['id'])
    resumed=spawn_dispatch(conn,slug,gate['task_id'],agent_key=dispatch['agent_key'],slot_key=dispatch['slot_key'],continuation=continuation)
    from project_assistant import store
    pending=db.many(conn,"SELECT to_jsonb(p) FROM projectops.assistant_proposal p WHERE dispatch_id=%s AND status='pending' ORDER BY id",(dispatch['id'],))
    replacements={}
    for proposal in pending:
        target={**proposal['target'],'source_proposal_id':proposal['id']}
        new_id=store.create_proposal(conn,slug,proposal['owner_id'],None,proposal['action'],target,proposal['content'])
        db.execute(conn,'UPDATE projectops.assistant_proposal SET dispatch_id=%s,agent_key=%s,race_group_task_id=%s WHERE id=%s',
                   (resumed['id'],dispatch['agent_key'],proposal['race_group_task_id'],new_id))
        db.execute(conn,"UPDATE projectops.assistant_proposal SET status='dismissed',decided_at=NOW() WHERE id=%s",(proposal['id'],))
        replacements[str(proposal['id'])]=str(new_id)
    if replacements:
        for entry in continuation.get('journal',{}).values():
            entry['result']=re.sub(r'#([0-9]+)',lambda match:'#'+replacements.get(match[1],match[1]),entry['result'])
        db.execute(conn,'UPDATE projectops.orchestration_dispatch SET continuation=%s::jsonb WHERE id=%s',(json.dumps(continuation,ensure_ascii=False),resumed['id']))
    db.execute(conn,'UPDATE projectops.orchestration_task SET parent_dispatch_id=%s WHERE parent_dispatch_id=%s',(resumed['id'],dispatch['id']))
    refresh_run(conn,slug,run['id'])
    return db.get_gate(conn,slug,gate['id'])


def finish_run_notice(conn,run_id):
    run=db.one(conn,'SELECT to_jsonb(r) FROM projectops.orchestration_run r WHERE id=%s',(db.identifier(run_id),))
    if not run:
        return None
    lock_project(conn,run['project_slug'])
    run=db.get_run(conn,run['project_slug'],run_id,True)
    if run['completion_message_id']:
        return run['completion_message_id']
    if run['status'] not in ('succeeded','failed','canceled') or not run['conversation_id']:
        return None
    from project_assistant import store
    if store.open_reply(conn,run['project_slug'],run['created_by'],run['coordinator_key']):
        return None
    tasks=db.tasks(conn,run['project_slug'],run_id)
    labels={'succeeded':'已完成','failed':'有工作未完成','canceled':'已取消'}
    summary=labels[run['status']]+'：'+run['objective']+'\n'+'\n'.join(f'- {t["title"]}：'+{'completed':'已完成','failed':'失敗','canceled':'已取消'}.get(t['status'],t['status']) for t in tasks)
    profile=agent_registry.get_agent(conn,run['project_slug'],run['coordinator_key']) or {}
    identifier=db.one(conn,'''INSERT INTO projectops.assistant_message
        (project_slug,owner_id,role,body,status,conversation_id,agent_key,agent_snapshot,run_id,finished_at)
        VALUES(%s,%s,'assistant',%s,'done',%s,%s,%s::jsonb,%s,NOW()) RETURNING id''',
        (run['project_slug'],run['created_by'],privacy.sanitize(summary,privacy.mode(conn,run['project_slug'])),run['conversation_id'],
         run['coordinator_key'],json.dumps({'display_name':profile.get('display_name','工作摘要'),'icon':profile.get('icon','✦')}),run_id))
    db.execute(conn,'UPDATE projectops.orchestration_run SET completion_message_id=%s,summary=%s WHERE id=%s',(identifier,summary[:4000],run_id))
    return identifier


def schedule_ready(conn,project_slug=None):
    runs=db.many(conn,"SELECT to_jsonb(r) FROM projectops.orchestration_run r WHERE status IN ('active','awaiting_gate') AND (%s::text IS NULL OR project_slug=%s) ORDER BY project_slug,created_at",(project_slug,project_slug))
    for run in runs:
        lock_project(conn,run['project_slug'])
        for task in ready_tasks(conn,run['project_slug'],run['id']):
            try:
                with conn.transaction():
                    if task['strategy']=='race':
                        if not task.get('race_agents'):
                            raise OrchestrationError(400,'競速沒有有效的候選代理')
                        from project_docs.service import Identity
                        start_race(conn,Identity(run['created_by'],'','member'),run['project_slug'],task['id'],task['race_agents'])
                    else:
                        slots=['row:'+rid for rid in task['request_scope']['row_ids']] if task['strategy']=='fanout_rows' else ['single']
                        for slot in slots:
                            spawn_dispatch(conn,run['project_slug'],task['id'],agent_key=task['target_agent_key'],slot_key=slot)
            except OrchestrationError as exc:
                db.execute(conn,"UPDATE projectops.orchestration_task SET status='failed',error=%s,updated_at=NOW() WHERE id=%s",(str(exc),task['id']))
                refresh_run(conn,run['project_slug'],run['id'])
    for run_id in db.many(conn,"SELECT id::text FROM projectops.orchestration_run WHERE status IN ('succeeded','failed','canceled') AND completion_message_id IS NULL AND conversation_id IS NOT NULL AND (%s::text IS NULL OR project_slug=%s) ORDER BY project_slug,created_at",(project_slug,project_slug)):
        finish_run_notice(conn,run_id)


def effective_scope(conn,dispatch,task=None):
    task=task or db.get_task(conn,dispatch['project_slug'],dispatch['task_id'])
    scope=copy.deepcopy(task['request_scope'])
    if scope and dispatch.get('row_id') and scope.get('kind')!='doc':
        tab=task['input_snapshot']['tabs'][scope['target_tab']]
        scope=request_scope.validate_scope({**scope,'row_ids':[dispatch['row_id']]},tab,tab['values'])
    return scope


def snapshot_tab(conn,slug,dispatch_id,key):
    lock_project(conn,slug)
    dispatch=db.get_dispatch(conn,slug,dispatch_id)
    if not dispatch:
        raise OrchestrationError(404,'找不到派發')
    task=db.get_task(conn,slug,dispatch['task_id'],True)
    snapshots=task['input_snapshot']
    if key not in snapshots['tabs']:
        if len(snapshots['tabs'])>=100:
            raise OrchestrationError(400,'參考分頁已達 100 頁，請縮小工作範圍')
        snapshots['tabs'][key]=freeze_tab(conn,slug,key)
        db.execute(conn,'UPDATE projectops.orchestration_task SET input_snapshot=%s::jsonb WHERE id=%s',(json.dumps(snapshots),task['id']))
    return copy.deepcopy(snapshots['tabs'][key])


def attach_proposal(conn,ctx,proposal_id):
    from project_assistant import store,proposal_review
    dispatch=leased_dispatch(conn,ctx.worker_id,f'dsp_{ctx.dispatch_id}_{ctx.admission_no}',ctx.lease_token)
    task=db.get_task(conn,ctx.slug,dispatch['task_id'])
    proposal=store.proposal(conn,proposal_id)
    if not proposal or proposal['slug']!=ctx.slug or proposal['owner_id']!=ctx.me.actor_id or proposal['status']!='pending':
        raise OrchestrationError(400,'提案不屬於此派發')
    if task['write_mode']=='analysis_only':
        raise OrchestrationError(403,'分析工作不能產生寫入提案','POLICY_DENIED')
    if task['strategy']=='race' and db.one(conn,"SELECT count(*) FROM projectops.assistant_proposal WHERE dispatch_id=%s AND status='pending'",(dispatch['id'],)):
        raise OrchestrationError(400,'競速的每個候選只能產生一張完整提案')
    target=proposal['target']
    expected=copy.deepcopy(task['target'])
    if dispatch.get('row_id') and expected.get('row_id'):
        expected['row_id']=dispatch['row_id']
    if expected.get('tab_key') and target.get('tab_key')!=expected['tab_key']:
        raise OrchestrationError(403,'提案不能改寫任務輸出分頁以外的內容','POLICY_DENIED')
    if expected.get('tab_key') and proposal['action']=='table_edit':
        for op in target.get('ops',[]):
            if expected.get('kind')=='doc':
                if op.get('op') not in ('put','del'):
                    raise OrchestrationError(403,'此任務的輸出是文件段落','POLICY_DENIED')
            elif (op.get('op')!='put_row' or (expected.get('row_id') and op.get('rid')!=expected['row_id'])
                  or (expected.get('table_id') and op.get('table')!=expected['table_id'])
                  or ('col_index' in expected and set(op.get('edited_cols',[]))!={expected['col_index']})):
                raise OrchestrationError(403,'提案超出任務指定的輸出列欄','POLICY_DENIED')
    elif expected.get('row_id') and (target.get('rid')!=expected['row_id'] or proposal['action'] not in agent_registry.QA_ACTIONS):
        raise OrchestrationError(403,'此儲存格任務請使用結構化修改，或在指定列提出討論','POLICY_DENIED')
    scope=effective_scope(conn,dispatch,task)
    if scope and target.get('tab_key')!=scope['target_tab']:
        raise OrchestrationError(403,'提案超出本次固定分頁','POLICY_DENIED')
    if scope:
        if proposal['action']=='table_edit':
            if scope.get('kind')=='doc':
                if any(op.get('op') not in ('put','del') or (op.get('base') and op.get('bid') not in scope['block_ids']) for op in target.get('ops',[])):
                    raise OrchestrationError(403,'文件提案超出選取段落','POLICY_DENIED')
            else:
                allowed={str(v) for v in scope['column_indices']}
                for op in target.get('ops',[]):
                    if (op.get('op')!='put_row' or op.get('rid') not in scope['row_ids'] or op.get('table')!=scope['table_id']
                        or not op.get('base') or not {str(v) for v in op.get('edited_cols',[])}.issubset(allowed)):
                        raise OrchestrationError(403,'提案超出選取的列欄','POLICY_DENIED')
        target['request_scope']=scope
    references={key:tab['revision'] for key,tab in task['input_snapshot']['tabs'].items() if key!=target.get('tab_key')}
    if references:
        target['source_revisions']=references
    if task['input_snapshot'].get('source_scopes'):
        target['source_scopes']=task['input_snapshot']['source_scopes']
    if task['input_snapshot'].get('source_revisions'):
        target['source_revisions']=task['input_snapshot']['source_revisions']
    if proposal['action']=='table_edit':
        tab=task['input_snapshot']['tabs'].get(target['tab_key'])
        target['review']=proposal_review.describe(target,tab,partial_allowed=False)
    store.revise_pending_proposal(conn,proposal_id,target,proposal['content'])
    db.execute(conn,'UPDATE projectops.assistant_proposal SET agent_key=%s,dispatch_id=%s,race_group_task_id=%s WHERE id=%s',
               (dispatch['agent_key'],dispatch['id'],task['id'] if task['strategy']=='race' else None,proposal_id))


def prepare_dispatch_output(conn,ctx,output):
    from project_assistant import proposal_output,store
    dispatch=leased_dispatch(conn,ctx.worker_id,f'dsp_{ctx.dispatch_id}_{ctx.admission_no}',ctx.lease_token)
    task=db.get_task(conn,ctx.slug,dispatch['task_id'])
    existing=db.many(conn,'SELECT id FROM projectops.assistant_proposal WHERE dispatch_id=%s ORDER BY id',(dispatch['id'],))
    if existing or task['write_mode']=='analysis_only' or not task['target'].get('tab_key'):
        return existing
    from project_assistant.agent_policy import can_propose_output
    if not can_propose_output(runtime_profile(conn,ctx.slug,dispatch['agent_key']),task['target']):
        raise OrchestrationError(403,'此代理沒有產生這類畫布修改的權限','POLICY_DENIED')
    target=copy.deepcopy(task['target'])
    if dispatch.get('row_id') and target.get('row_id'):
        target['row_id']=dispatch['row_id']
    safe_output=privacy.sanitize(output,privacy.mode(conn,ctx.slug))
    prepared,preview=proposal_output.prepare_output(target,task['target_snapshot'],safe_output,conn=conn,slug=ctx.slug,
        row_id=dispatch.get('row_id',''),scope=effective_scope(conn,dispatch,task))
    proposal_id=store.create_proposal(conn,ctx.slug,ctx.me.actor_id,None,'table_edit',prepared,preview)
    attach_proposal(conn,ctx,proposal_id)
    return [proposal_id]


def ensure_review_gate(conn,dispatch,proposal_ids):
    if db.get_task(conn,dispatch['project_slug'],dispatch['task_id'])['strategy']=='race':
        return
    if db.one(conn,"SELECT id FROM projectops.orchestration_gate WHERE dispatch_id=%s AND gate_kind='proposal_review' AND status='open'",(dispatch['id'],)):
        return
    db.execute(conn,'''INSERT INTO projectops.orchestration_gate(id,run_id,task_id,dispatch_id,project_slug,gate_kind,question,options)
        VALUES(%s,%s,%s,%s,%s,'proposal_review','請核對代理提出的修改',%s::jsonb)''',
        (str(uuid.uuid4()),dispatch['run_id'],dispatch['task_id'],dispatch['id'],dispatch['project_slug'],json.dumps(proposal_ids)))


def on_proposal_decided(conn,proposal_id,applied,*,source_before=None):
    from project_assistant import store,proposal_review
    proposal=store.proposal(conn,proposal_id)
    if not proposal or not proposal.get('dispatch_id'):
        return
    slug=proposal['slug']
    lock_project(conn,slug)
    dispatch=db.get_dispatch(conn,slug,proposal['dispatch_id'])
    if dispatch['superseded_by'] or dispatch['status'] in ('canceled','failed','timeout'):
        return
    task=db.get_task(conn,slug,dispatch['task_id'])
    siblings=db.many(conn,'SELECT to_jsonb(p) FROM projectops.assistant_proposal p WHERE dispatch_id=%s ORDER BY id',(dispatch['id'],))
    if not applied:
        db.execute(conn,"UPDATE projectops.orchestration_dispatch SET status='failed',error='提案未通過核對',lease_until=NULL,updated_at=NOW() WHERE id=%s",(dispatch['id'],))
        _dismiss_outputs(conn,dispatch)
        db.event(conn,dispatch,'worker_done','提案未通過核對',{'outcome':'failed'})
    else:
        # Rebase only remaining outputs from this same task against this known, accepted change.
        pending=db.many(conn,'''SELECT to_jsonb(p) FROM projectops.assistant_proposal p JOIN projectops.orchestration_dispatch d ON d.id=p.dispatch_id
            WHERE d.task_id=%s AND p.id<>%s AND p.status='pending' AND p.race_group_task_id IS NULL''',(task['id'],proposal_id))
        changed_key=proposal['target'].get('tab_key')
        tab=repo.get_tab(conn,slug,changed_key) if changed_key else None
        for item in pending:
            target=item['target']
            changed=False
            # Only the accepted write may advance a sibling's guard. Validate
            # against the locked pre-write document before looking at live data.
            if not source_before or source_before['key']!=changed_key:
                continue
            scopes=[target['request_scope']] if target.get('request_scope') else []
            scopes+=target.get('source_scopes',[])
            try:
                for scope in scopes:
                    if scope['target_tab']==changed_key:
                        request_scope.verify_source(scope,source_before,source_before['values'])
                expected=target.get('source_revisions',{}).get(changed_key)
                if expected is not None and expected!=source_before['revision']:
                    continue
            except ValueError:
                continue
            if tab and target.get('request_scope',{}).get('target_tab')==changed_key:
                target['request_scope']=request_scope.validate_scope({**target['request_scope'],'base_revision':tab['revision']},tab,
                    repo.field_values(conn,slug).get(changed_key,{}))
                target['source_revision']=tab['revision']
                changed=True
            if tab and changed_key in target.get('source_revisions',{}):
                target['source_revisions'][changed_key]=tab['revision']
                changed=True
            for index,source_scope in enumerate(target.get('source_scopes',[])):
                if tab and source_scope['target_tab']==changed_key:
                    target['source_scopes'][index]=request_scope.validate_scope({**source_scope,'base_revision':tab['revision']},tab,
                        repo.field_values(conn,slug).get(changed_key,{}))
                    changed=True
            if changed:
                target['review']=proposal_review.describe(target,repo.get_tab(conn,slug,target['tab_key']),partial_allowed=False)
                store.revise_pending_proposal(conn,item['id'],target,item['content'])
        _advance_dependent_sources(conn,task,source_before)
        question_open=db.one(conn,"SELECT id FROM projectops.orchestration_gate WHERE dispatch_id=%s AND gate_kind='question' AND status='open'",(dispatch['id'],))
        if dispatch['status']!='running' and not question_open and all(p['status']=='applied' for p in siblings):
            db.execute(conn,"UPDATE projectops.orchestration_dispatch SET status='succeeded',updated_at=NOW() WHERE id=%s",(dispatch['id'],))
            db.execute(conn,"UPDATE projectops.orchestration_gate SET status='resolved',resolved_at=NOW() WHERE dispatch_id=%s AND gate_kind='proposal_review' AND status='open'",(dispatch['id'],))
    refresh_run(conn,slug,dispatch['run_id'])


def start_race(conn,me,slug,task_id,agent_keys):
    from project_assistant.agent_policy import can_propose_output
    lock_project(conn,slug)
    task=db.get_task(conn,slug,task_id,True)
    if not task:
        raise OrchestrationError(404,'找不到競速任務')
    own_run(conn,me,slug,task['run_id'])
    if (task['strategy']!='race' or task['write_mode']!='proposal' or not task['target'].get('tab_key')
        or not isinstance(agent_keys,list) or not 2<=len(agent_keys)<=3 or any(not isinstance(k,str) for k in agent_keys)
        or len(set(agent_keys))!=len(agent_keys)):
        raise OrchestrationError(400,'競速需要固定的輸出位置與 2～3 個不同代理')
    for key in agent_keys:
        profile=runtime_profile(conn,slug,key)
        if not can_propose_output(profile,task['target']):
            raise OrchestrationError(400,'候選代理必須具有相同輸出類型的修改權限','POLICY_DENIED')
    if task['race_agents'] and task['race_agents']!=agent_keys:
        raise OrchestrationError(409,'已建立的候選代理不能變更')
    with conn.transaction():
        db.execute(conn,'UPDATE projectops.orchestration_task SET race_agents=%s::jsonb,target_agent_key=%s WHERE id=%s',
                   (json.dumps(agent_keys),agent_keys[0],task_id))
        if task['status']=='pending':
            return []
        return [spawn_dispatch(conn,slug,task_id,agent_key=key,slot_key='agent:'+key) for key in agent_keys]


def race_proposals(conn,task):
    return db.many(conn,'''SELECT to_jsonb(p) FROM projectops.assistant_proposal p JOIN projectops.orchestration_dispatch d ON d.id=p.dispatch_id
        WHERE p.race_group_task_id=%s AND p.status='pending' AND d.superseded_by IS NULL AND d.status='awaiting_gate' ORDER BY d.admission_no''',(task['id'],))


def refresh_race_gate(conn,task):
    if task['winning_dispatch_id']:
        return
    candidates=race_proposals(conn,task)
    gate=db.one(conn,"SELECT to_jsonb(g) FROM projectops.orchestration_gate g WHERE task_id=%s AND gate_kind='race_select' AND status='open'",(task['id'],))
    if not candidates:
        if gate:
            db.execute(conn,"UPDATE projectops.orchestration_gate SET status='dismissed',resolved_at=NOW() WHERE id=%s",(gate['id'],))
        return
    ids=[p['id'] for p in candidates]
    if gate:
        db.execute(conn,'UPDATE projectops.orchestration_gate SET options=%s::jsonb WHERE id=%s',(json.dumps(ids),gate['id']))
    else:
        db.execute(conn,'''INSERT INTO projectops.orchestration_gate(id,run_id,task_id,project_slug,gate_kind,question,options)
            VALUES(%s,%s,%s,%s,'race_select','請比較候選版本，選用其中一版後才會寫回',%s::jsonb)''',
            (str(uuid.uuid4()),task['run_id'],task['id'],task['project_slug'],json.dumps(ids)))


def select_race_winner(conn,me,slug,gate_id,proposal_id,*,client_request_id):
    from project_assistant import service,store
    if type(proposal_id) is not int or not isinstance(client_request_id,str) or not 1<=len(client_request_id)<=128:
        raise OrchestrationError(400,'候選選用資料不正確')
    lock_project(conn,slug)
    gate=db.get_gate(conn,slug,gate_id,True)
    if not gate or gate['gate_kind']!='race_select':
        raise OrchestrationError(404,'找不到候選核對問題')
    run=own_run(conn,me,slug,gate['run_id'])
    task=db.get_task(conn,slug,gate['task_id'],True)
    if gate['status']=='resolved':
        if gate['resolution']!={'proposal_id':proposal_id}:
            raise OrchestrationError(409,'此競速已選用另一個版本')
        return {'gate':gate,'proposal':store.proposal(conn,proposal_id),'winning_dispatch_id':task['winning_dispatch_id'],
                'run_id':run['id'],'task_id':task['id']}
    if gate['status']!='open' or run['status']=='canceled':
        raise OrchestrationError(409,'這組候選已取消')
    proposal=next((p for p in race_proposals(conn,task) if p['id']==proposal_id),None)
    if not proposal:
        raise OrchestrationError(409,'此候選尚未完成、已失效或不屬於這組競速')
    winner=db.get_dispatch(conn,slug,proposal['dispatch_id'])
    with conn.transaction():
        code,payload=service.apply_proposal(conn,me,slug,proposal_id,{},_race_task_id=task['id'])
        if code>=400:
            raise OrchestrationError(code,payload.get('error','候選未能套用'),'SOURCE_CHANGED' if code==409 else 'INVALID_REQUEST')
        db.execute(conn,'UPDATE projectops.orchestration_task SET winning_dispatch_id=%s WHERE id=%s',(winner['id'],task['id']))
        for dispatch in db.dispatches(conn,slug,task['id']):
            if dispatch['id']!=winner['id']:
                _cancel_one(conn,dispatch,'已選用其他候選版本')
        db.execute(conn,"UPDATE projectops.assistant_proposal SET status='dismissed',decided_at=NOW(),decided_by=%s WHERE race_group_task_id=%s AND id<>%s AND status='pending'",(me.actor_id,task['id'],proposal_id))
        db.execute(conn,"UPDATE projectops.orchestration_gate SET status='resolved',resolution=%s::jsonb,resolution_request_id=%s,resolved_by=%s,resolved_at=NOW() WHERE id=%s",
                   (json.dumps({'proposal_id':proposal_id}),client_request_id,me.actor_id,gate_id))
        refresh_run(conn,slug,run['id'])
    return {'gate':db.get_gate(conn,slug,gate_id),'proposal':store.proposal(conn,proposal_id),'winning_dispatch_id':winner['id'],
            'run_id':run['id'],'task_id':task['id']}
