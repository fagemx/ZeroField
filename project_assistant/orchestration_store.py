"""Small SQL accessors; transaction boundaries belong to callers."""
import json
import uuid

TABLES={'run','task','dispatch','gate'}


def identifier(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError,TypeError,AttributeError):
        from project_assistant.agent_registry import AgentError
        raise AgentError(400,"Invalid task identity.") from None


def one(conn,sql,params=()):
    with conn.cursor() as cur:
        cur.execute(sql,params)
        row=cur.fetchone()
        return row[0] if row else None


def many(conn,sql,params=()):
    with conn.cursor() as cur:
        cur.execute(sql,params)
        return [row[0] for row in cur.fetchall()]


def execute(conn,sql,params=()):
    with conn.cursor() as cur:
        cur.execute(sql,params)
        return cur.rowcount


def get(conn,kind,slug,key,lock=False):
    if kind not in TABLES:
        raise ValueError('Unknown orchestration table')
    return one(conn,'SELECT to_jsonb(t) FROM projectops.orchestration_'+kind+' t WHERE project_slug=%s AND id=%s'+
               (' FOR UPDATE' if lock else ''),(slug,identifier(key)))


def get_run(conn,slug,key,lock=False):
    return get(conn,'run',slug,key,lock)


def get_task(conn,slug,key,lock=False):
    return get(conn,'task',slug,key,lock)


def get_dispatch(conn,slug,key,lock=False):
    return get(conn,'dispatch',slug,key,lock)


def get_gate(conn,slug,key,lock=False):
    return get(conn,'gate',slug,key,lock)


def tasks(conn,slug,run_id):
    return many(conn,'SELECT to_jsonb(t) FROM projectops.orchestration_task t WHERE project_slug=%s AND run_id=%s ORDER BY created_at,id',
                (slug,identifier(run_id)))


def dispatches(conn,slug,task_id=None,run_id=None):
    return many(conn,'''SELECT to_jsonb(d) FROM projectops.orchestration_dispatch d WHERE project_slug=%s
        AND (%s::uuid IS NULL OR task_id=%s) AND (%s::uuid IS NULL OR run_id=%s) ORDER BY admission_no''',
        (slug,task_id,task_id,run_id,run_id))


def event(conn,dispatch,kind,body='',payload=None):
    execute(conn,'''INSERT INTO projectops.orchestration_message
        (run_id,task_id,dispatch_id,admission_no,project_slug,sender,recipient,msg_type,body,payload)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT DO NOTHING''',
        (dispatch['run_id'],dispatch['task_id'],dispatch['id'],dispatch['admission_no'],dispatch['project_slug'],
         'agent:'+dispatch['agent_key'],'run:'+dispatch['run_id'],kind,body,json.dumps(payload or {},ensure_ascii=False)))
