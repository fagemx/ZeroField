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
CONSOLE_DEFAULTS = {
    'effort': 'medium', 'skill_keys': [], 'tool_policies': {},
    'multiagent_config': {'allow_subagents': False, 'allow_workflows': False, 'advisor_agent_key': None},
    'outcome_grader': {'enabled': False, 'criteria': '', 'grader_agent_key': 'qa_critic', 'max_revisions': 1},
    'memory_mounts': [], 'default_environment_key': 'env_local_4090',
}
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
    from project_assistant import tool_registry
    # Grants are declared per tool in the registry; other keys keep the historic reviewer set.
    return tool_registry.default_grants(key if key in tool_registry.BUILTIN_ROLES else 'qa_critic', orchestration)


LEGACY_SEED_PROMPTS = {'coordinator': 'You are the Showrunner. Understand the production goal, pages, and selected scope. Delegate to available specialists when useful. Break complex work into tasks with clear outputs and dependencies, read the source, and prepare proposals for review. Only approved proposals count as applied changes. Report pending, queued, canceled, and failed work honestly. Media generation requires configured workers and validated workflows; do not promise an unavailable capability.\n', 'doc_writer': 'You are the Screenwriter. Organize production briefs, revise scenes and dialogue, and preserve the established voice and continuity. Read sources before writing. When no body-editing tool is available, provide a draft or annotation without claiming the document changed. Keep every proposal inside the selected passages and submit it for review.\n', 'sheet_ops': 'You are the Cinematographer and slate specialist. Read headers and stable row and column IDs before editing shot prompts, production data, or formulas. Preserve cast IDs, appearance references, optical choices, and continuity. Respect the selected scope; do not invent masked values or expand the batch. Produce structured table proposals with before/after values and reasons. Unproduced shots stay Queued with empty media cells until real assets are returned.\n', 'qa_critic': "You are the Continuity Supervisor. Check source consistency, cast continuity, calculation definitions, and delivery requirements. Locate each issue precisely. Use only permitted question annotations or discussions. Do not change statuses, numbers, body text, or another person's decisions. Distinguish verified facts, inferences, and unverified work; human approval remains with the crew.\n"}
LEGACY_SEED_TOOLS = {'coordinator': ['ask_decision_gate', 'cancel_delegation', 'check_delegation', 'list_agents', 'list_pages', 'my_todo', 'offer_document', 'propose', 'propose_table_edit', 'read_page', 'report_cell', 'report_find', 'report_list', 'report_overview', 'report_sheet', 'search_pages', 'spawn_agent', 'trigger_flow_run'], 'doc_writer': ['list_pages', 'read_page', 'search_pages', 'propose', 'offer_document', 'ask_decision_gate'], 'sheet_ops': ['list_pages', 'read_page', 'search_pages', 'report_cell', 'report_find', 'report_list', 'report_overview', 'report_sheet', 'propose_table_edit', 'ask_decision_gate'], 'qa_critic': ['list_pages', 'read_page', 'search_pages', 'report_cell', 'report_find', 'report_list', 'report_overview', 'report_sheet', 'propose', 'ask_decision_gate']}


def seed_mounts(key):
    return {'skill_keys': {'coordinator':['shotgen','character-continuity','docx'], 'doc_writer':['shotgen','character-continuity','pdf'],
                          'sheet_ops':['shotgen','h3-context-ir','xlsx'], 'qa_critic':['shotcheck','character-continuity']}[key],
            'multiagent_config': {'allow_subagents':key=='coordinator', 'allow_workflows':key=='coordinator',
                                  'advisor_agent_key':'qa_critic' if key!='qa_critic' else None},
            'memory_mounts':[{'store_key':'style_rules','access':'read_only'}]}


def ensure_default_agents(conn, slug):
    with conn.cursor() as cur:
        for key, name, icon, role, domain in ROSTER:
            prompt = (Path(__file__).parent / 'prompts' / (key + '.md')).read_text(encoding='utf-8')
            mounted = seed_mounts(key)
            cur.execute('''INSERT INTO projectops.agent_profile
                (project_slug,agent_key,display_name,icon,role_kind,system_prompt,capabilities,labels,allowed_tools,skill_keys,multiagent_config,memory_mounts)
                VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb) ON CONFLICT DO NOTHING''',
                (slug,key,name,icon,role,prompt,json.dumps(['llm','orchestrate'] if role=='primary' else ['llm']),json.dumps({'domain':domain}),
                 json.dumps(default_tools(key)),json.dumps(mounted['skill_keys']),json.dumps(mounted['multiagent_config']),json.dumps(mounted['memory_mounts'])))
            # Match the entire pristine seed, not just the prompt; never rewrite customization.
            profile = get_agent(conn, slug, key, effective=False)
            pristine = (profile['created_by'] is None and not profile.get('effort_configured') and profile['system_prompt'] in (LEGACY_SEED_PROMPTS[key], prompt) and
                profile['allowed_tools'] in (LEGACY_SEED_TOOLS[key], [t for t in LEGACY_SEED_TOOLS[key] if t not in tool_specs.DELEGATION_TOOLS], default_tools(key, False)) and
                all(profile.get(k)==v for k,v in CONSOLE_DEFAULTS.items()) and
                all(profile.get(k)==v for k,v in dict(display_name=name,icon=icon,role_kind=role,runtime_kind='builtin_llm',description='',
                    provider_config={},knowledge_pack='',enabled=True,bound_limb_id=None,max_concurrency=2,labels={'domain':domain},
                    capabilities=['llm','orchestrate'] if role=='primary' else ['llm']).items()))
            if pristine:
                cur.execute('''UPDATE projectops.agent_profile SET system_prompt=%s,allowed_tools=%s::jsonb,
                    skill_keys=%s::jsonb,multiagent_config=%s::jsonb,memory_mounts=%s::jsonb WHERE project_slug=%s AND agent_key=%s''',
                    (prompt,json.dumps(default_tools(key)),json.dumps(mounted['skill_keys']),json.dumps(mounted['multiagent_config']),json.dumps(mounted['memory_mounts']),slug,key))
    from project_assistant.agent_console_store import ensure_defaults
    ensure_defaults(conn, slug)


def effective_profile(conn, profile):
    """Resolve only empty built-in settings; never materialize inheritance on save."""
    if not profile or profile['runtime_kind'] != 'builtin_llm' or profile['provider_config'] != {}:
        return profile
    from project_assistant import store, orchestration_store as db, orchestrator as cp
    saved = store.get_setting(conn, profile['project_slug'], 'console_default_provider')
    if not saved:
        return profile
    default = json.loads(saved)
    if default['vault_key'] is None:
        return {**profile, 'provider_binding': cp.digest(default)}
    reference = db.one(conn, 'SELECT to_jsonb(v) FROM projectops.agent_vault_reference v WHERE project_slug=%s AND vault_key=%s',
                       (profile['project_slug'], default['vault_key']))
    if not reference or not reference['enabled'] or profile['agent_key'] not in reference['allowed_agent_keys']:
        raise AgentError(409, 'Project default provider was revoked; configure a current LLM reference.', 'PROVIDER_CHANGED')
    config = validate_provider(reference['provider_config'])
    if config.get('kind', 'openai_compat') != 'openai_compat' or not config.get('model') or not config.get('base_url'):
        raise AgentError(409, 'Project default is not a configured LLM reference.', 'PROVIDER_CHANGED')
    return {**profile, 'provider_config': config, 'provider_binding': cp.digest([default, reference['version'], config])}


def get_agent(conn, slug, key, *, effective=True):
    with conn.cursor() as cur:
        cur.execute('SELECT to_jsonb(p) FROM projectops.agent_profile p WHERE project_slug=%s AND agent_key=%s', (slug, key))
        row = cur.fetchone()
    profile = row[0] if row else None
    return effective_profile(conn, profile) if effective else profile


def list_agents(conn, slug, *, capability=None, labels=None, effective=False):
    with conn.cursor() as cur:
        cur.execute('SELECT to_jsonb(p) FROM projectops.agent_profile p WHERE project_slug=%s ORDER BY created_at,agent_key', (slug,))
        rows = [r[0] for r in cur.fetchall()]
    if effective:
        rows = [effective_profile(conn, p) for p in rows]
    return [p for p in rows if (not capability or capability in p['capabilities'])
            and all(p['labels'].get(k) == v for k, v in (labels or {}).items())]


def validate_provider(value):
    allowed = {'kind', 'base_url', 'api_key_env', 'model', 'effort'}
    if not isinstance(value, dict) or set(value) - allowed or any(not isinstance(v, str) for v in value.values()):
        raise AgentError(400, "Model settings support kind/base_url/api_key_env/model/effort only. Do not store credentials here.")
    if value.get('kind', 'openai_compat') not in ('openai_compat', 'responses', 'codex_cli'):
        raise AgentError(400, "Unsupported model runtime.")
    if any(len(v) > 2000 or '\x00' in v for v in value.values()):
        raise AgentError(400, "Model configuration is too long or malformed.")
    if value.get('effort', 'medium') not in ('low', 'medium', 'high'):
        raise AgentError(400, "Invalid model effort.")
    if any(re.search(r'(?i)(?:\bbearer\s+|\bsk-[a-z0-9_-]{8,})', v) for v in value.values()):
        raise AgentError(400, "Provider settings must not contain credential values.")
    if value.get('base_url'):
        if any(c.isspace() or ord(c) < 32 for c in value['base_url']):
            raise AgentError(400, "Model endpoints cannot contain whitespace or control characters.")
        try:
            url = urlsplit(value['base_url'])
            url.port
        except ValueError:
            raise AgentError(400, "Invalid model endpoint.") from None
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise AgentError(400, "The model endpoint must be an HTTP(S) URL without embedded credentials.")
    if value.get('api_key_env') not in (None, ''):
        permitted = {n.strip() for n in os.environ.get('OPENBENCH_AGENT_KEY_ENVS', '').split(',') if n.strip()}
        if not re.fullmatch(r'[A-Z_][A-Z0-9_]{0,127}', value['api_key_env']) or value['api_key_env'] not in permitted:
            raise AgentError(400, "This credential reference is not allowed by the deployment.")
    if value.get('kind') in ('responses', 'codex_cli') and (value.get('base_url') or value.get('api_key_env')):
        raise AgentError(400, "This runtime uses local credentials and does not accept a custom endpoint or api_key_env.")
    return dict(value)


def save_agent(conn, me, slug, body):
    if not me.can_edit:
        raise AgentError(403, "Only the showrunner can configure agents.")
    from project_assistant.agent_console_store import authorize, _lock, STUDIO_TOOLS
    authorize(conn, me, slug, admin=True)
    if not isinstance(body, dict) or not isinstance(body.get('agent_key'), str) or not AGENT_KEY.fullmatch(body['agent_key']):
        raise AgentError(400, "Invalid agent key.")
    fields = {'display_name','icon','role_kind','runtime_kind','description','system_prompt','knowledge_pack',
              'capabilities','labels','allowed_tools','provider_config','bound_limb_id','max_concurrency','enabled'}
    fields |= set(CONSOLE_DEFAULTS)
    if set(body) - fields - {'agent_key', 'version'}:
        raise AgentError(400, "Agent configuration contains unsupported fields.")
    key = body['agent_key']
    _lock(conn, slug)
    existing = get_agent(conn, slug, key, effective=False)
    if 'version' in body and (type(body['version']) is not int or body['version'] != (existing['version'] if existing else 0)):
        raise AgentError(409, "Agent version changed; reload before saving.", 'VERSION_CONFLICT')
    profile = existing or dict(display_name=key, icon='🤖', role_kind='worker', runtime_kind='builtin_llm',
        description='', system_prompt='', knowledge_pack='', capabilities=['llm'], labels={}, allowed_tools=[],
        provider_config={}, bound_limb_id=None, max_concurrency=2, enabled=True)
    profile = {**CONSOLE_DEFAULTS, **profile}
    profile.update({k: v for k, v in body.items() if k in fields})
    validate_console_fields(conn, me, slug, key, profile)
    if profile['role_kind'] not in ('primary','worker','observer') or profile['runtime_kind'] not in ('builtin_llm','acp_stdio','remote_limb'):
        raise AgentError(400, "Invalid agent role or runtime.")
    if type(profile['max_concurrency']) is not int or not 1 <= profile['max_concurrency'] <= 32 or type(profile['enabled']) is not bool:
        raise AgentError(400, "Concurrency must be an integer from 1 to 32; enabled must be a boolean.")
    for name, maximum in [('display_name',120),('icon',20),('description',2000),('system_prompt',30000),('knowledge_pack',50000)]:
        if not isinstance(profile[name], str) or len(profile[name]) > maximum or '\x00' in profile[name] or (name == 'display_name' and not profile[name].strip()):
            raise AgentError(400, f"Invalid format or length for {name}.")
    allowed = profile['allowed_tools']
    if not isinstance(allowed, list) or len(allowed) > 128 or any(not isinstance(n, str) or n not in tool_specs.TOOL_NAMES | STUDIO_TOOLS for n in allowed):
        raise AgentError(400, "The tool list contains an unknown tool.")
    caps, labels = profile['capabilities'], profile['labels']
    if not isinstance(caps,list) or not caps or any(c not in ('llm','image_gen','video_gen','media_assemble','acp_cli','orchestrate') for c in caps):
        raise AgentError(400, "Invalid agent capabilities.")
    if not isinstance(labels,dict) or len(labels)>30 or any(not isinstance(k,str) or not isinstance(v,str) or len(k)>80 or len(v)>120 for k,v in labels.items()):
        raise AgentError(400, "Capability labels must map short strings to short strings.")
    profile['provider_config'] = validate_provider(profile['provider_config'])
    if profile['bound_limb_id'] is not None:
        from project_assistant.orchestration_store import identifier
        profile['bound_limb_id'] = identifier(profile['bound_limb_id'])
        from project_assistant import limbs
        if not any(w['id'] == profile['bound_limb_id'] and w['enabled'] for w in limbs.list_workers(conn, slug)):
            raise AgentError(400, "This worker does not exist, is disabled, or cannot access this production.")
    if profile['runtime_kind'] != 'builtin_llm' and not profile['bound_limb_id']:
        raise AgentError(400, "External runtimes must be bound to a worker in this production.")
    profile['effort_configured'] = 'effort' in body or profile.get('effort_configured', False)
    columns = sorted(fields | {'effort_configured'})
    encoded = {'capabilities','labels','allowed_tools','provider_config','skill_keys','tool_policies','multiagent_config','outcome_grader','memory_mounts'}
    values = [json.dumps(profile[n],ensure_ascii=False) if n in encoded else profile[n] for n in columns]
    placeholders = [('%s::jsonb' if n in encoded else '%s') for n in columns]
    with conn.cursor() as cur:
        cur.execute('INSERT INTO projectops.agent_profile(project_slug,agent_key,' + ','.join(columns) + ',created_by) VALUES(%s,%s,' +
                    ','.join(placeholders) + ',%s) ON CONFLICT(project_slug,agent_key) DO UPDATE SET ' +
                    ','.join(n+'=EXCLUDED.'+n for n in columns) + ',updated_at=NOW()', [slug,key]+values+[me.actor_id])
    repo.add_audit(conn,slug,action='agent_profile',actor_id=me.actor_id,target=key,
                   detail={'fields':sorted(set(body)-{'system_prompt','knowledge_pack','provider_config'})})
    return get_agent(conn,slug,key,effective=False)


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


def validate_console_fields(conn, me, slug, agent_key, profile):
    from project_assistant import agent_console_store as console
    if profile['effort'] not in ('low', 'medium', 'high'):
        raise AgentError(400, 'Invalid reasoning effort.')
    console.strings(profile['skill_keys'], 32, check=console.key)
    from project_assistant.skills_registry import get_skill
    if any(not get_skill(conn, slug, k) for k in profile['skill_keys']):
        raise AgentError(400, 'Unknown project skill.')
    policies = profile['tool_policies']
    if not isinstance(policies, dict) or len(policies) > 128 or any(
        not isinstance(k, str) or k not in tool_specs.TOOL_NAMES | console.STUDIO_TOOLS or
        v not in ('auto', 'always_ask', 'disabled') for k, v in policies.items()):
        raise AgentError(400, 'Invalid per-tool permission policy.')
    multi = profile['multiagent_config']
    if not isinstance(multi, dict) or set(multi) != set(CONSOLE_DEFAULTS['multiagent_config']) or any(
        type(multi[n]) is not bool for n in ('allow_subagents', 'allow_workflows')):
        raise AgentError(400, 'Invalid multiagent configuration.')
    advisor = multi['advisor_agent_key']
    if advisor is not None:
        console.key(advisor)
        if advisor == agent_key or not get_agent(conn, slug, advisor, effective=False):
            raise AgentError(400, 'Advisor must be another project agent.')
    grader = profile['outcome_grader']
    if not isinstance(grader, dict) or set(grader) != set(CONSOLE_DEFAULTS['outcome_grader']) or type(grader['enabled']) is not bool:
        raise AgentError(400, 'Invalid outcome grader.')
    console.text(grader['criteria'], 4000)
    console.integer(grader['max_revisions'], 0, 3)
    console.key(grader['grader_agent_key'])
    if grader['enabled'] and (grader['grader_agent_key'] == agent_key or not get_agent(conn, slug, grader['grader_agent_key'], effective=False)):
        raise AgentError(400, 'Enabled grader must be a separate project agent.')
    mounts = profile['memory_mounts']
    if not isinstance(mounts, list) or len(mounts) > 32:
        raise AgentError(400, 'Invalid memory mounts.')
    seen = set()
    for mount in mounts:
        if not isinstance(mount, dict) or set(mount) != {'store_key', 'access'} or mount['access'] not in ('read_only', 'read_write'):
            raise AgentError(400, 'Invalid memory mount permission.')
        store_key = console.key(mount['store_key'])
        if store_key in seen:
            raise AgentError(400, 'Duplicate memory mount.')
        seen.add(store_key)
        store = console._get(conn, 'memory_store', slug, store_key)
        if not store:
            raise AgentError(400, 'Unknown project memory store.')
        console.authorize_scope(conn, me, slug, store, episode_id=store['scope_id'] if store['scope_kind'] == 'episode' else None)
    console.key(profile['default_environment_key'])
    if not console._get(conn, 'environment', slug, profile['default_environment_key']):
        raise AgentError(400, 'Unknown project environment.')


def console_profiles(conn, slug):
    """Display-only descriptors: never use this accessor for admission/claims."""
    from project_assistant import story_media_adapter as media
    return [dict(p, read_only=False) for p in list_agents(conn, slug, effective=False)] + [
        dict(media.profile(k), read_only=True, project_slug=slug) for k in media.KEYS]
