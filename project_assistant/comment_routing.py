"""Atomic human comment → persona chat, using the existing queue and review boundary."""
import re

from project_assistant import agent_registry,request_scope,service as assistant
from project_docs import repository as repo,anchoring
from project_docs.doc_schema import column_ids,doc_text,TEXTBLOCKS


def _tokens(text):
    plain=re.sub(r'```[\s\S]*?```|`[^`]*`|(?m:^\s*>[^\n]*)','',text)
    return re.findall(r'(?<![\w@])@([a-zA-Z][a-zA-Z0-9_-]*|[\u3400-\u9fff]+)',plain)


def prepare(conn,me,slug,body,annotation_id=None):
    if not isinstance(body.get('body',''),str):
        return None
    text=str(body.get('body') or '').strip()
    tokens=_tokens(text)
    if not tokens:
        return None
    profiles=agent_registry.list_agents(conn,slug)
    named={p['agent_key'] for p in profiles if any(token in (p['agent_key'],p['display_name']) for token in tokens)}
    if not named:
        return None  # Social references, email, and plain text are not agent commands.
    if len(named)!=1:
        raise agent_registry.AgentError(400,"Mention one agent per comment. Use the table’s candidate comparison for multiple agents.")
    key=agent_registry.resolve_mention(conn,slug,'',next(iter(named)))
    with conn.cursor() as cur:
        cur.execute('SELECT actor_id FROM projectops.member WHERE actor_id=%s FOR UPDATE',(me.actor_id,))
    annotation=None
    if annotation_id is not None:
        found=repo.list_annotations(conn,slug,annotation_id=annotation_id)
        if not found:
            raise agent_registry.AgentError(404,"Source annotation not found.")
        annotation=found[0]
    tab_key=annotation['tab_key'] if annotation else body.get('tab_key')
    tab=repo.get_tab_for_update(conn,slug,tab_key)
    if not tab:
        raise agent_registry.AgentError(404,"The source page no longer exists.")
    tab={**tab,'key':tab_key}
    if type(body.get('source_revision')) is not int or body['source_revision']!=tab['revision']:
        raise agent_registry.AgentError(409,"The source changed. Save and review it before assigning the task.",'SOURCE_CHANGED')
    rid=annotation['anchor']['rid'] if annotation and annotation['kind']=='row' else body.get('row')
    if rid:
        table=next((t for t in tab['doc'].get('content',[]) if t.get('type')=='table' and any(r.get('attrs',{}).get('bid')==rid for r in t.get('content',[]))),None)
        if not table:
            raise agent_registry.AgentError(409,"The source row no longer exists.",'SOURCE_CHANGED')
        raw={'target_tab':tab_key,'table_id':table['attrs']['bid'],'base_revision':tab['revision'],'row_ids':[rid],'column_ids':column_ids(table)}
    else:
        anchor=annotation['anchor'] if annotation else anchoring.clean_anchor(body.get('anchor'))
        resolved=anchoring.resolve(doc_text(tab['doc']),anchor or {})
        if not resolved or not resolved[2]:
            raise agent_registry.AgentError(409,"The source passage cannot be located precisely. Select it again.",'SOURCE_CHANGED')
        start,end,_=resolved
        selected=[]; offset=0; preceding=False
        def has_textblock(node):
            return node.get('type') in TEXTBLOCKS or any(has_textblock(child) for child in node.get('content',[]))
        for block in tab['doc'].get('content',[]):
            contains=has_textblock(block)
            begin=offset+(1 if preceding and contains else 0)
            finish=begin+len(doc_text({'type':'doc','content':[block]}))
            if contains and begin<end and finish>start:
                selected.append(block.get('attrs',{}).get('bid'))
            if contains: offset=finish; preceding=True
        raw={'kind':'doc','target_tab':tab_key,'base_revision':tab['revision'],'block_ids':selected}
    scope=request_scope.validate_scope(raw,tab,repo.field_values(conn,slug).get(tab_key,{}))
    return {'agent_key':key,'scope':scope,'text':text}


def route_result(conn,me,slug,prepared,payload):
    if not prepared:
        return 200,payload
    comment_id=payload.get('comment_id')
    if type(comment_id) is not int:
        raise agent_registry.AgentError(409,"The comment was not completed; no agent task was created.")
    source_ref='activity:'+str(comment_id)
    code,result=assistant.send(conn,me,slug,{'text':prepared['text'],'agent_key':prepared['agent_key'],'scope':prepared['scope']},source_ref=source_ref)
    if code>=400:
        return code,result
    payload['annotation']['agent_request']={'agent_key':prepared['agent_key'],'source_ref':source_ref,
        'message_id':result['message']['id'],'reply_id':result['reply']['id']}
    return 200,payload
