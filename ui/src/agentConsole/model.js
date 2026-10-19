import { t } from '../i18n/index.js';

export const GROUPS = {workspace:['dashboard','api_keys'],build:['playground','skills'],managed_agents:['quickstart','agents','sessions','deployments','environments','memory_store'],analytics:['usage_cost','spend_rate_limits']};
export const PAGES = Object.values(GROUPS).flat();
export const TEMPLATES = ['script_breakdown_director','continuity_frame_grader','hybrid_budget_dispatcher','h3_context_ir_compiler','openjutsu_motion_rig','parallel_model_racer','offpeak_4090_batch_worker','twopass_4k_mastering','episode_rough_cut_assembler','asset_vault_curator','production_sheet_analyst','comfy_card_integrator'];
export const STUDIO_TOOLS = ['studio_ingest_script','studio_manage_asset','studio_plan_allocation','studio_dispatch_shot','studio_inspect_frames','studio_edit_timeline','consult_advisor'];
export const AGENT_FIELDS = ['agent_key','version','display_name','icon','role_kind','runtime_kind','description','system_prompt','knowledge_pack','capabilities','labels','allowed_tools','provider_config','bound_limb_id','max_concurrency','enabled','effort','skill_keys','tool_policies','multiagent_config','outcome_grader','memory_mounts','default_environment_key'];
export const LIMIT_FIELDS = ['version','spend_limit_monthly_usd','spend_limit_session_usd','spend_limit_episode_usd','on_spend_limit','rate_limits','model_pricing','judge_trial_mode','comfy_router_budget_mode'];
export const RESOURCE_FIELDS = {
  skills:['skill_key','version','display_name','category','summary','instructions_md','recommended_tools','enabled'],
  environments:['env_key','version','display_name','env_kind','config','network_access','allowed_hosts','packages','enabled'],
  providers:['vault_key','version','display_name','provider_config','allowed_agent_keys','enabled'],
  'memory-stores':['store_key','version','display_name','scope_kind','scope_id','description','archived'],
  'memory-entries':['store_key','entry_key','version','title','content_md','tags','archived'],
  deployments:['deployment_key','version','display_name','agent_key','env_key','initial_prompt','playbook','target_scope','schedule_kind','cron_expr','timezone','budget_cap_usd','enabled'],
};
export const pick = (value, fields) => Object.fromEntries(fields.filter(k => Object.hasOwn(value || {}, k)).map(k => [k,value[k]]));
export const agentInput = value => pick(value, AGENT_FIELDS);
export const pretty = value => JSON.stringify(value, null, 2);
export function consoleRoute(hash) {
  const match = /^#\/agent-console(?:\/([a-z_]+))?(?:\/([^/?#]+))?$/.exec(hash || '');
  if (!match) return null;
  let resource='';try{resource=match[2] ? decodeURIComponent(match[2]):'';}catch{/* Invalid URL encoding is not a resource selection. */}
  return {page:PAGES.includes(match[1]) ? match[1] : 'dashboard',resource};
}
export const consoleHash = (page='dashboard', resource='') => '#/agent-console/' + page + (resource ? '/' + encodeURIComponent(resource) : '');
export const money = value => value === null || value === undefined || !Number.isFinite(Number(value)) ? t('console.unknown') : '$' + Number(value).toFixed(4);
export function budgetRemaining(budget) {
  if (!budget || budget.accounted_usd == null || Number(budget.unknown_price_operations) > 0) return null;
  return Math.max(0, Number(budget.spend_limit_monthly_usd) - Number(budget.accounted_usd));
}
export function consoleError(error) {
  const safeHint=error?.data?.error || error?.data?.message || '';
  const key = /judge/i.test(safeHint) ? 'judgeDenied' : /source.*changed|allocation.*consumed|preview again/i.test(safeHint) ? 'sourceChanged' : error?.status === 409 ? 'conflict' : error?.status === 401 ? 'signIn' : error?.status === 403 ? 'denied' : error instanceof SyntaxError ? 'invalidJson' : 'requestFailed';
  return t('console.' + key);
}
export function parseObject(text) {
  const value = JSON.parse(text);
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new SyntaxError('object');
  return value;
}
export function quoteCurrent(quote, now=Date.now()) {
  return Boolean(quote?.quotes?.length && quote.quotes.every(q => Number.isFinite(Date.parse(q.expires_at)) && Date.parse(q.expires_at) > now));
}
export function mergeSession(previous, next) {
  const messages = new Map((previous?.messages || []).map(m => [m.id,m]));
  for (const message of next.messages || []) messages.set(message.id,message);
  return {...next,messages:[...messages.values()]};
}
const SEARCH_KEY = {agents:'agent_key',skills:'skill_key',deployments:'deployment_key',environments:'env_key',memory_store:'store_key'};
export function resourceSearch(catalog, query) {
  const entries = PAGES.map(page => ({page,key:page,label:t('console.pages.'+page)}));
  for (const [page,items] of Object.entries(catalog)) for (const item of items || []) {
    // Deployment rows also carry agent_key, so the page decides which key identifies the row.
    const key = item[SEARCH_KEY[page]] ?? item.id;
    entries.push({page,key,label:item.display_name || item.objective || key,resource:key});
  }
  return entries.filter(e => (e.label+' '+e.key).toLowerCase().includes(query.toLowerCase())).slice(0,60);
}
