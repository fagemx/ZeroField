// Agent Console role x model matrix (SPEC_20 R37): pure view logic. Wire values (tiers, denial codes, agent
// keys) stay exactly as the server sends them; everything a person reads goes through console.matrix.* messages.
import { t } from '../i18n/index.js';

export const TIERS = ['local_open', 'hosted_open', 'closed'];
export const TIER_TONE = { local_open: 'ok', hosted_open: 'warn', closed: 'bad' };
// Why a model cannot be used right now, as the server names it (project_assistant/console_model_matrix.py).
export const DENIALS = ['hosted_open_disabled', 'closed_needs_hybrid', 'pricing_missing', 'key_not_allowed', 'unknown_tier', 'not_in_catalog'];
export const CAPABILITIES = ['tools', 'json_schema', 'vision'];
export const READY_TONE = { ready: 'ok', blocked: 'bad', untested: 'muted', off: 'muted' };
export const INHERIT = '__inherit__';

/** Plain-language reason for one denial code; a code from a newer server still reads as a sentence. */
export function denialText(code, subject = {}) {
  const known = DENIALS.includes(code);
  return t('console.matrix.denial.' + (known ? code : 'unknown'),
    { model: subject.model || '', env: subject.apiKeyEnv || '', code: code || '' });
}
/** Every reason a model is not usable, then the soft warning when its key variable is allowed but empty. */
export function choiceNotes(choice) {
  const notes = (choice?.denials || []).map(code => ({ tone: 'bad', text: denialText(code, choice) }));
  if (choice && choice.local === false && choice.keyConfigured === false && !(choice.denials || []).includes('key_not_allowed')) {
    notes.push({ tone: 'warn', text: t('console.matrix.keyNotSet', { env: choice.apiKeyEnv || '' }) });
  }
  if (choice && choice.listed === false) notes.push({ tone: 'warn', text: t('console.matrix.notInstalled') });
  return notes;
}

/** "16k", "1M": the context length as people say it. */
export function contextSize(tokens) {
  if (!Number.isFinite(tokens) || tokens <= 0) return '?';
  if (tokens < 1024) return String(tokens);
  if (tokens < 1_000_000) return Math.round(tokens / 1024) + 'k';
  return (tokens / (1024 * 1024)).toFixed(1).replace(/\.0$/, '') + 'M';
}
/** The ability chips for a model: tools, JSON schema, vision, each on or off, plus the context size. */
export function abilities(model) {
  const caps = model?.capabilities || {};
  return { chips: CAPABILITIES.map(key => ({ key, on: caps[key] === true, name: t('console.matrix.cap.' + key) })),
    context: contextSize(model?.contextTokens), assumed: model?.assumed === true };
}

/** Where the model runs, in words. */
export function whereLine(model) {
  if (!model) return '';
  return model.local ? t('console.matrix.onThisComputer', { host: model.host, port: model.port }) : t('console.matrix.onHost', { host: model.host });
}

/** The state pill and problem lines for a row's "ready to work?" cell. */
export function readyView(row) {
  if (row.state && row.state !== 'ok') return { state: 'blocked', tone: 'bad', label: t('console.matrix.ready.blocked'), setup: t('console.matrix.state.' + row.state, { defaultValue: t('console.matrix.noModel') }) };
  const state = row.readiness?.state || 'untested';
  return { state, tone: READY_TONE[state] || 'muted', label: t('console.matrix.ready.' + (READY_TONE[state] ? state : 'untested')), setup: '' };
}

/** The listing of one local endpoint becomes a group; everything else is the catalog group. */
export function groupChoices(choices = [], endpoints = []) {
  const groups = [];
  for (const endpoint of endpoints) {
    const items = choices.filter(choice => choice.source === 'listing' && choice.baseUrl === endpoint.baseUrl);
    groups.push({ id: 'endpoint:' + endpoint.baseUrl, kind: 'listing', endpoint, items });
  }
  const catalog = choices.filter(choice => choice.source !== 'listing');
  if (catalog.length) groups.push({ id: 'catalog', kind: 'catalog', endpoint: null, items: catalog });
  return groups;
}
/** What an endpoint that cannot list models says, or '' when it listed fine. */
export function endpointNote(endpoint) {
  if (!endpoint || endpoint.state === 'ok') return '';
  const key = ['down', 'bad', 'unlisted'].includes(endpoint.state) ? endpoint.state : 'bad';
  return t('console.matrix.endpoint.' + key, { host: endpoint.host, port: endpoint.port });
}

/** Is this choice the model the row already uses? (Same endpoint for a local model, same catalog entry for a hosted one.) */
export function isCurrent(row, choice) {
  const now = row?.current;
  if (!now || !choice || now.model !== choice.model) return false;
  return choice.local ? now.local === true && now.baseUrl === choice.baseUrl : now.local === false && now.host === choice.host;
}

/** The request body that applies a choice (or the default model) to a row. */
export function changeBody(row, choice) {
  const base = { agent_key: row.agentKey, version: row.version };
  if (choice === INHERIT || choice === null) return { ...base, inherit: true };
  if (choice.local) return { ...base, base_url: choice.baseUrl, model: choice.model };
  return { ...base, catalog_id: choice.catalogId };
}
export const hostedBody = (policy, enabled) => ({ hosted_open_enabled: enabled === true, version: policy?.settingsVersion ?? 0 });

/** A saved change that failed, in words: a policy reason when the server names one, else the stale-page hint. */
export function applyProblem(error, choice) {
  const code = error?.data?.code;
  if (DENIALS.includes(code)) return denialText(code, choice);
  if (error?.status === 409 && code === 'VERSION_CONFLICT') return t('console.matrix.stale');
  return '';
}
