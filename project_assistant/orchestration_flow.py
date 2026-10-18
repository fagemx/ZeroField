"""Bridge Flow-owned DAG tasks to profile-owned execution; never duplicate the DAG."""
import datetime as dt
import json
import uuid

from project_assistant import orchestrator as cp,orchestration_store as db,flow_runner as flows,agent_registry,store,request_scope
from project_docs import repository as repo,service
from project_docs.doc_schema import column_ids


def profile_connected(conn,slug,key):
    profile=agent_registry.get_agent(conn,slug,key)
    if not profile or not profile['enabled']:
        return False
    if profile['runtime_kind']=='builtin_llm':
        seen=store.get_setting(conn,slug,'builtin_worker_seen_at')
        return bool(seen and cp.instant(seen)>cp.now()-dt.timedelta(seconds=90))
    from project_assistant import limbs
    return any(w['id']==profile['bound_limb_id'] for w in limbs.connected_workers(conn,slug))


def attach_flow_task(conn,flow_run,limb_task,node):
    slug=flow_run['project_slug']
    cp.lock_project(conn,slug)
    existing=db.one(conn,'SELECT to_jsonb(t) FROM projectops.orchestration_task t WHERE flow_task_id=%s',(limb_task['id'],))
    if existing:
        return existing
    flow_run=flows._get_run(conn,flow_run['id'],lock=True)
    if flow_run['status'] in ('failed','canceled','succeeded') or limb_task['status']!='queued':
        return None
    if flow_run.get('execution',{}).get('mode')=='single_step':
        flows._check_source_revisions(conn,slug,flow_run['execution']['source_revisions'])
    me=flows._creator(conn,flow_run)
    run=db.one(conn,'SELECT to_jsonb(r) FROM projectops.orchestration_run r WHERE project_slug=%s AND flow_run_id=%s AND status<>%s',
               (slug,flow_run['id'],'canceled'))
    if not run:
        generation=flow_run.get('execution',{}).get('orchestration_generation',0)
        run=cp.create_run(conn,me,slug,'執行工作流：'+flow_run['tab_key'],client_request_id=f'flow:{flow_run["id"]}:{generation}')
        db.execute(conn,'UPDATE projectops.orchestration_run SET flow_run_id=%s WHERE id=%s',(flow_run['id'],run['id']))
    elif run['status']=='failed':
        db.execute(conn,"UPDATE projectops.orchestration_run SET status='active',finished_at=NULL WHERE id=%s",(run['id'],))
    target={k:v for k,v in limb_task['target'].items() if k in ('tab_key','kind','mode','row_id','col_index','table_id','after_block_id')}
    scope=None
    if target.get('tab_key') and limb_task['row_id']:
        tab=cp.freeze_tab(conn,slug,target['tab_key'])
        table=next((t for t in tab['doc'].get('content',[]) if t.get('type')=='table' and any(r.get('attrs',{}).get('bid')==limb_task['row_id'] for r in t.get('content',[]))),None)
        if table:
            ids=column_ids(table)
            writable_ids=[ids[target['col_index']]] if 'col_index' in target else ids
            scope={'target_tab':tab['key'],'table_id':table['attrs']['bid'],'base_revision':tab['revision'],
                   'row_ids':[limb_task['row_id']],'column_ids':writable_ids}
    task=cp.create_task(conn,me,slug,run['id'],objective=node['prompt'] or node['title'],agent_key=node['agent_key'],scope=scope,
                        target=target,write_mode='proposal' if target.get('tab_key') else 'analysis_only')
    snapshots=task['input_snapshot']
    for key in node['input_tabs']:
        snapshots['tabs'].setdefault(key,cp.freeze_tab(conn,slug,key))
    source=node.get('row_source')
    if source:
        snapshots['tabs'].setdefault(source['tab_key'],cp.freeze_tab(conn,slug,source['tab_key']))
    snapshots['flow_input']=flows._inputs(conn,flow_run,limb_task,node)
    if source and limb_task['row_id']:
        source_tab=snapshots['tabs'][source['tab_key']]
        source_table=next((table for table in source_tab['doc'].get('content',[]) if table.get('type')=='table'
            and (not source.get('table_id') or table.get('attrs',{}).get('bid')==source['table_id'])),None)
        if source_table:
            snapshots['source_scopes']=[request_scope.validate_scope({'target_tab':source_tab['key'],
                'table_id':source_table['attrs']['bid'],'base_revision':source_tab['revision'],
                'row_ids':[limb_task['row_id']],'column_ids':column_ids(source_table)},source_tab,source_tab['values'])]
    snapshots['flow_run_id']=flow_run['id']
    snapshots['capability']=node['capability']
    if flow_run.get('execution',{}).get('mode')=='single_step':
        snapshots['source_revisions']=flow_run['execution']['source_revisions']
    db.execute(conn,'UPDATE projectops.orchestration_task SET flow_task_id=%s,input_snapshot=%s::jsonb WHERE id=%s',
               (limb_task['id'],json.dumps(snapshots),task['id']))
    db.execute(conn,"UPDATE projectops.limb_task SET status='running',updated_at=NOW() WHERE id=%s",(limb_task['id'],))
    cp.spawn_dispatch(conn,slug,task['id'],agent_key=node['agent_key'],slot_key='single')
    return db.get_task(conn,slug,task['id'])


def finish_profile_task(conn,flow_task_id,dispatch_result=None):
    task=db.one(conn,'SELECT to_jsonb(t) FROM projectops.orchestration_task t WHERE flow_task_id=%s',(flow_task_id,))
    if not task:
        return
    limb_task=db.one(conn,'SELECT to_jsonb(t) FROM projectops.limb_task t WHERE id=%s',(flow_task_id,))
    if not limb_task:
        return
    flow_run=flows._get_run(conn,limb_task['run_id'],lock=True)
    if flow_run['status']=='canceled':
        return
    dispatches=[d for d in db.dispatches(conn,task['project_slug'],task['id']) if not d['superseded_by']]
    latest=dispatches[-1] if dispatches else None
    status={'completed':'succeeded','failed':'failed','canceled':'canceled','awaiting_gate':'awaiting_approval'}.get(task['status'],'running')
    proposals=db.many(conn,'''SELECT p.id FROM projectops.assistant_proposal p JOIN projectops.orchestration_dispatch d ON d.id=p.dispatch_id
        WHERE d.task_id=%s AND d.superseded_by IS NULL ORDER BY p.id''',(task['id'],))
    output=(latest or {}).get('output_json')
    db.execute(conn,'''UPDATE projectops.limb_task SET status=%s,attempts=%s,output=%s::jsonb,proposal_id=%s,error=%s,
        lease_hash=NULL,lease_until=NULL,updated_at=NOW() WHERE id=%s''',
        (status,(latest or {}).get('attempt_no',0),json.dumps(output),proposals[0] if proposals else None,
         (latest or {}).get('error'),flow_task_id))
    flows._advance(conn,flow_run)


def sync_project(conn,slug):
    cp.lock_project(conn,slug)
    runs=db.many(conn,"SELECT to_jsonb(r) FROM projectops.flow_run r WHERE project_slug=%s AND status IN ('queued','running','awaiting_approval') ORDER BY created_at",(slug,))
    created=0
    for run in runs:
        nodes={n['id']:n for n in run['definition']['nodes'] if n.get('agent_key')}
        if not nodes:
            continue
        for task in db.many(conn,"SELECT to_jsonb(t) FROM projectops.limb_task t WHERE run_id=%s AND status='queued' ORDER BY created_at,node_id,row_id",(run['id'],)):
            if task['node_id'] in nodes:
                try:
                    if attach_flow_task(conn,run,task,nodes[task['node_id']]):
                        created+=1
                except (cp.OrchestrationError,flows.ExecutionError) as exc:
                    db.execute(conn,"UPDATE projectops.limb_task SET status='failed',error=%s,updated_at=NOW() WHERE id=%s",(str(exc),task['id']))
                    flows._advance(conn,run)
    for run in db.many(conn,'SELECT to_jsonb(r) FROM projectops.orchestration_run r WHERE project_slug=%s AND flow_run_id IS NOT NULL AND status IN (%s,%s)',(slug,'active','awaiting_gate')):
        flow=flows._get_run(conn,run['flow_run_id'])
        if flow['status'] in ('failed','canceled'):
            for dispatch in db.dispatches(conn,slug,run_id=run['id']):
                cp._cancel_one(conn,dispatch,'工作流已停止')
            db.execute(conn,"UPDATE projectops.orchestration_task SET status='canceled' WHERE run_id=%s AND status NOT IN ('completed','failed')",(run['id'],))
            db.execute(conn,'UPDATE projectops.orchestration_run SET status=%s,finished_at=NOW() WHERE id=%s',('canceled' if flow['status']=='canceled' else 'failed',run['id']))
        elif flow['status']=='succeeded':
            cp.refresh_run(conn,slug,run['id'])
    return created


def reset_for_flow_retry(conn,slug,flow_run_id):
    cp.lock_project(conn,slug)
    for run in db.many(conn,'SELECT to_jsonb(r) FROM projectops.orchestration_run r WHERE project_slug=%s AND flow_run_id=%s',(slug,flow_run_id)):
        for dispatch in db.dispatches(conn,slug,run_id=run['id']):
            cp._cancel_one(conn,dispatch,'工作流重新交辦')
        db.execute(conn,"UPDATE projectops.orchestration_task SET flow_task_id=NULL,status='canceled',updated_at=NOW() WHERE run_id=%s AND status<>'completed'",(run['id'],))
        db.execute(conn,"UPDATE projectops.orchestration_run SET flow_run_id=NULL,status=CASE WHEN status='succeeded' THEN status ELSE 'canceled' END,finished_at=NOW() WHERE id=%s",(run['id'],))
    db.execute(conn,"UPDATE projectops.flow_run SET execution=jsonb_set(execution,'{orchestration_generation}',to_jsonb(COALESCE((execution->>'orchestration_generation')::integer,0)+1)) WHERE id=%s",(flow_run_id,))
