"""Project agent configuration, seeded personas, and explicit mention routing."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from project_docs import repository as repo
from project_assistant import tool_specs

AGENT_KEY = re.compile(r'^[a-z][a-z0-9_-]{0,63}$')
QA_ACTIONS = ('在段落加標註', '寫進那一題的討論', '留言問負責人')
ROSTER = (
    ('coordinator', 'Showrunner', '🧭', 'primary', 'general'),
    ('doc_writer', 'Screenwriter', '✍️', 'worker', 'writing'),
    ('sheet_ops', 'Cinematographer', '📊', 'worker', 'sheet'),
    ('qa_critic', 'Continuity Supervisor', '🔍', 'worker', 'review'),
)


class AgentError(ValueError):
    def __init__(self, status, message, code='POLICY_DENIED'):
        super().__init__(message)
        self.status, self.code = status, code


def recommend_agent_provider_tier(agent_key, budget_mode="hybrid_balanced", *, task_kind="script_breakdown"):
    """Advisory product-runtime capabilities only; never rewrites or runs a model.

    Families are examples, not executable provider settings or a CLI command.
    An administrator must retain/select an authorized configured runtime/model.
    """
    from project_assistant.studio.agent_allocator import BUDGET_MODES
    if not isinstance(agent_key, str) or agent_key not in {row[0] for row in ROSTER}:
        raise AgentError(400, "Unknown specialist agent.")
    if budget_mode not in BUDGET_MODES or task_kind not in ("script_breakdown", "formatting", "translation", "shot_triage"):
        raise AgentError(400, "Invalid agent recommendation mode or task.")
    economical = agent_key == 'doc_writer' and task_kind in ('formatting', 'translation')
    vision = agent_key == 'qa_critic'
    return {'agent_key': agent_key, 'budget_mode': budget_mode, 'advisory_only': True,
            'provider_tier': 'economical_local' if economical else 'vision_reasoning' if vision else 'flagship_reasoning',
            'required_capabilities': ['vision', 'reasoning'] if vision else ['text', 'reasoning'],
            'provider_kind_hint': 'openai_compat' if economical else None,
            'model_family_examples': ['local open-weights'] if economical else ['Claude', 'GPT', 'Gemini'],
            'reasons': ['bulk_formatting_or_translation' if economical else 'frame_sheet_failure_diagnosis' if vision else 'story_structure_and_shot_triage'],
            'reference_media': {'kind': 'frame_sheet', 'frames': 8, 'width': 1600, 'height': 600} if vision else None,
            'requires_admin_configuration': True, 'changes_configuration': False,
            'launches_external_cli': False}


def default_tools(key,orchestration=True):
    reads = ['list_pages', 'read_page', 'search_pages']
    reports = sorted(n for n in tool_specs.TOOL_NAMES if n.startswith('report_'))
    if key == 'coordinator':
        return sorted(tool_specs.TOOL_NAMES if orchestration else tool_specs.TOOL_NAMES-tool_specs.DELEGATION_TOOLS)
    if key == 'doc_writer':
        return reads + ['propose', 'offer_document'] + (['ask_decision_gate'] if orchestration else [])
    if key == 'sheet_ops':
        return reads + reports + ['propose_table_edit'] + (['ask_decision_gate'] if orchestration else [])
    return reads + reports + ['propose'] + (['ask_decision_gate'] if orchestration else [])


def ensure_default_agents(conn, slug):
    with conn.cursor() as cur:
        for key, name, icon, role, domain in ROSTER:
            prompt = (Path(__file__).parent / 'prompts' / (key + '.md')).read_text(encoding='utf-8')
            cur.execute('''INSERT INTO projectops.agent_profile
                (project_slug,agent_key,display_name,icon,role_kind,system_prompt,capabilities,labels,allowed_tools)
                VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb) ON CONFLICT DO NOTHING''',
                (slug, key, name, icon, role, prompt, json.dumps(['llm','orchestrate'] if role=='primary' else ['llm']),
                 json.dumps({'domain': domain}), json.dumps(default_tools(key))))
            cur.execute('''UPDATE projectops.agent_profile SET allowed_tools=%s::jsonb,updated_at=NOW()
                WHERE project_slug=%s AND agent_key=%s AND allowed_tools=%s::jsonb''',
                (json.dumps(default_tools(key)),slug,key,json.dumps(default_tools(key,False))))


def get_agent(conn, slug, key):
    with conn.cursor() as cur:
        cur.execute('SELECT to_jsonb(p) FROM projectops.agent_profile p WHERE project_slug=%s AND agent_key=%s', (slug, key))
        row = cur.fetchone()
        return row[0] if row else None


def list_agents(conn, slug, *, capability=None, labels=None):
    with conn.cursor() as cur:
        cur.execute('SELECT to_jsonb(p) FROM projectops.agent_profile p WHERE project_slug=%s ORDER BY created_at,agent_key', (slug,))
        rows = [r[0] for r in cur.fetchall()]
    return [p for p in rows if (not capability or capability in p['capabilities'])
            and all(p['labels'].get(k) == v for k, v in (labels or {}).items())]


def validate_provider(value):
    allowed = {'kind', 'base_url', 'api_key_env', 'model', 'effort'}
    if not isinstance(value, dict) or set(value) - allowed or any(not isinstance(v, str) for v in value.values()):
        raise AgentError(400, "Model settings support kind/base_url/api_key_env/model/effort only. Do not store credentials here.")
    if value.get('kind', 'openai_compat') not in ('openai_compat', 'responses', 'codex_cli'):
        raise AgentError(400, "Unsupported model runtime.")
    if any(len(v) > 2000 for v in value.values()):
        raise AgentError(400, "Model configuration is too long.")
    if value.get('base_url'):
        url = urlsplit(value['base_url'])
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise AgentError(400, "The model endpoint must be an HTTP(S) URL without embedded credentials.")
    if value.get('api_key_env') not in (None, ''):
        permitted = {n.strip() for n in os.environ.get('OPENBENCH_AGENT_KEY_ENVS', '').split(',') if n.strip()}
        if value['api_key_env'] not in permitted:
            raise AgentError(400, "This credential reference is not allowed by the deployment.")
    if value.get('kind') in ('responses', 'codex_cli') and (value.get('base_url') or value.get('api_key_env')):
        raise AgentError(400, "This runtime uses local credentials and does not accept a custom endpoint or api_key_env.")
    return dict(value)


def save_agent(conn, me, slug, body):
    if not me.can_edit:
        raise AgentError(403, "Only the showrunner can configure agents.")
    if not repo.get_project(conn, slug):
        raise AgentError(404, "Production not found.")
    if not isinstance(body, dict) or not isinstance(body.get('agent_key'), str) or not AGENT_KEY.fullmatch(body['agent_key']):
        raise AgentError(400, "Invalid agent key.")
    fields = {'display_name','icon','role_kind','runtime_kind','description','system_prompt','knowledge_pack',
              'capabilities','labels','allowed_tools','provider_config','bound_limb_id','max_concurrency','enabled'}
    if set(body) - fields - {'agent_key'}:
        raise AgentError(400, "Agent configuration contains unsupported fields.")
    key = body['agent_key']
    profile = get_agent(conn, slug, key) or dict(display_name=key, icon='🤖', role_kind='worker', runtime_kind='builtin_llm',
        description='', system_prompt='', knowledge_pack='', capabilities=['llm'], labels={}, allowed_tools=[],
        provider_config={}, bound_limb_id=None, max_concurrency=2, enabled=True)
    profile.update({k: v for k, v in body.items() if k in fields})
    if profile['role_kind'] not in ('primary','worker','observer') or profile['runtime_kind'] not in ('builtin_llm','acp_stdio','remote_limb'):
        raise AgentError(400, "Invalid agent role or runtime.")
    if type(profile['max_concurrency']) is not int or not 1 <= profile['max_concurrency'] <= 32 or type(profile['enabled']) is not bool:
        raise AgentError(400, "Concurrency must be an integer from 1 to 32; enabled must be a boolean.")
    for name, maximum in [('display_name',120),('icon',20),('description',2000),('system_prompt',30000),('knowledge_pack',50000)]:
        if not isinstance(profile[name], str) or len(profile[name]) > maximum or (name == 'display_name' and not profile[name].strip()):
            raise AgentError(400, f"Invalid format or length for {name}.")
    allowed = profile['allowed_tools']
    if not isinstance(allowed, list) or any(not isinstance(n, str) or n not in tool_specs.TOOL_NAMES for n in allowed):
        raise AgentError(400, "The tool list contains an unknown tool.")
    caps, labels = profile['capabilities'], profile['labels']
    if not isinstance(caps,list) or not caps or any(c not in ('llm','image_gen','video_gen','media_assemble','acp_cli','orchestrate') for c in caps):
        raise AgentError(400, "Invalid agent capabilities.")
    if not isinstance(labels,dict) or len(labels)>30 or any(not isinstance(k,str) or not isinstance(v,str) or len(k)>80 or len(v)>120 for k,v in labels.items()):
        raise AgentError(400, "Capability labels must map short strings to short strings.")
    profile['provider_config'] = validate_provider(profile['provider_config'])
    if profile['bound_limb_id']:
        from project_assistant import limbs
        if not any(w['id'] == profile['bound_limb_id'] and w['enabled'] for w in limbs.list_workers(conn, slug)):
            raise AgentError(400, "This worker does not exist, is disabled, or cannot access this production.")
    if profile['runtime_kind'] != 'builtin_llm' and not profile['bound_limb_id']:
        raise AgentError(400, "External runtimes must be bound to a worker in this production.")
    columns = sorted(fields)
    encoded = {'capabilities','labels','allowed_tools','provider_config'}
    values = [json.dumps(profile[n],ensure_ascii=False) if n in encoded else profile[n] for n in columns]
    placeholders = [('%s::jsonb' if n in encoded else '%s') for n in columns]
    with conn.cursor() as cur:
        cur.execute('INSERT INTO projectops.agent_profile(project_slug,agent_key,' + ','.join(columns) + ',created_by) VALUES(%s,%s,' +
                    ','.join(placeholders) + ',%s) ON CONFLICT(project_slug,agent_key) DO UPDATE SET ' +
                    ','.join(n+'=EXCLUDED.'+n for n in columns) + ',updated_at=NOW()', [slug,key]+values+[me.actor_id])
    repo.add_audit(conn,slug,action='agent_profile',actor_id=me.actor_id,target=key,
                   detail={'fields':sorted(set(body)-{'system_prompt','knowledge_pack','provider_config'})})
    return get_agent(conn,slug,key)


def resolve_mention(conn, slug, text, explicit_key=None):
    if explicit_key is not None and not isinstance(explicit_key,str):
        raise AgentError(400, "Invalid agent key.")
    # Quotes and code are source material, not routing instructions.
    plain = re.sub(r'```[\s\S]*?```|`[^`]*`|(?m:^\s*>[^\n]*)', '', str(text))
    tokens = re.findall(r'(?<![\w@])@([a-zA-Z][a-zA-Z0-9_-]*|[\u3400-\u9fff]+)', plain)
    profiles = list_agents(conn,slug)
    matches = set()
    for token in tokens:
        found = [p for p in profiles if token in (p['agent_key'],p['display_name'])]
        if len(found)!=1:
            raise AgentError(400, f"No unique agent matches @{token}. Use the agent key.")
        matches.add(found[0]['agent_key'])
    if len(matches)>1 or (matches and explicit_key and explicit_key not in matches):
        raise AgentError(400, "Select one agent for chat. Use batch delegation for multiple agents.")
    key = explicit_key or next(iter(matches), 'coordinator')
    profile = next((p for p in profiles if p['agent_key']==key), None)
    if not profile or not profile['enabled'] or profile['role_kind']=='observer':
        raise AgentError(400, "This agent does not exist, is disabled, or has an observer role.")
    if profile['runtime_kind']!='builtin_llm':
        raise AgentError(400, "Run external workers through a pipeline or agent delegation.")
    return key


def roster(conn, me, slug):
    if not repo.get_project(conn,slug):
        raise AgentError(404, "Production not found.")
    rows = list_agents(conn,slug)
    for row in rows:
        from project_assistant import orchestration_store as db
        from project_assistant.orchestration_flow import profile_connected
        row['active_dispatches']=db.one(conn,"SELECT count(*) FROM projectops.orchestration_dispatch WHERE project_slug=%s AND agent_key=%s AND status='running'",(slug,row['agent_key']))
        row['active_dispatches']+=db.one(conn,"SELECT count(*) FROM projectops.assistant_message WHERE project_slug=%s AND agent_key=%s AND role='assistant' AND status='running'",(slug,row['agent_key']))
        connected=profile_connected(conn,slug,row['agent_key'])
        row['status']='busy' if connected and row['active_dispatches']>=row['max_concurrency'] else 'online' if connected else 'offline'
        from project_assistant.agent_policy import can_propose_output
        row['can_propose_table']=can_propose_output(row,{'kind':'table'})
        row['can_propose_document']=can_propose_output(row,{'kind':'doc'})
        if not me.can_edit:
            for field in ('system_prompt','knowledge_pack','provider_config','created_by'):
                row.pop(field,None)
    from project_assistant import limbs
    connected = {w['id'] for w in limbs.connected_workers(conn,slug)}
    for limb in limbs.list_workers(conn,slug):
        rows.append({'agent_key':'limb:'+limb['id'],'display_name':limb['name'],'icon':'🔌','role_kind':'worker',
                     'runtime_kind':'remote_limb','capabilities':limb['capabilities'],'enabled':limb['enabled'],
                     'labels':{},'status':'online' if limb['id'] in connected else 'offline','active_dispatches':0,
                     'bound_limb_id':limb['id'],'max_concurrency':1})
        rows[-1]['can_propose_table']=True
        rows[-1]['can_propose_document']=True
    return rows
