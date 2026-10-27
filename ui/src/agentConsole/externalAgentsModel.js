// External agents in the Agent Console (SPEC_20 R41): pure view logic for the token form, the connection
// snippets, the account list and the audit trail. Wire values stay as the server sends them; everything a
// person reads goes through console.external.* messages.
import { currentLocale, t } from '../i18n/index.js';
import { consoleError } from './model.js';

export const COMMAND = 'zerofield-mcp';
export const TOKEN_ENV = 'ZEROFIELD_MCP_TOKEN';
export const PROJECT_ENV = 'ZEROFIELD_PROJECT';
export const URL_ENV = 'ZEROFIELD_URL';
export const DEFAULT_URL = 'http://127.0.0.1:3020';
// Shell-safe on purpose: "<token>" would be read as a redirect by PowerShell and bash.
export const TOKEN_PLACEHOLDER = 'zfsa_...';
export const WRITE_MODES = ['propose_only', 'generate'];
export const EXPIRY_DAYS = [1, 7, 30, 90, 180, 365];
export const DEFAULT_DAYS = 30;
export const MAX_DAYS = 365;
export const KEY_PATTERN = /^[a-z][a-z0-9_-]{0,47}$/;
export const AUDIT_STEPS = [25, 50, 100];
export const KINDS = ['read', 'guide', 'propose', 'generate'];
// Tools with a one-line explanation in the message files; a newer tool falls back to its category line.
export const KNOWN_TOOLS = ['list_pages', 'read_page', 'read_episode', 'read_scene', 'read_shot', 'read_cast', 'list_takes',
  'get_workflow', 'propose_table_edit', 'request_generation'];
const DAY = 24 * 60 * 60 * 1000;

// ---------- the token form ----------

/** read: looks only; guide: reads a workflow guide; propose: writes a proposal; generate: asks for renders. */
export const toolKind = tool => (tool.generation ? 'generate' : tool.writes ? 'propose' : tool.category === 'workflow' ? 'guide' : 'read');

/** The offered tools by kind, in the order the registry lists them; empty kinds are left out. */
export function toolGroups(available) {
  return KINDS.map(kind => ({ kind, tools: (available || []).filter(tool => toolKind(tool) === kind) })).filter(group => group.tools.length);
}

const named = (available, kinds) => (available || []).filter(tool => kinds.includes(toolKind(tool))).map(tool => tool.name);

/** Presets the form offers; "all" respects the write mode, so propose_only never selects a generation tool. */
export function presetTools(available, preset, mode) {
  if (preset === 'read') return named(available, ['read', 'guide']);
  if (preset === 'all') return named(available, mode === 'generate' ? KINDS : ['read', 'guide', 'propose']);
  return named(available, ['read', 'guide', 'propose']);
}

/** Lower-case key for the audit log from a display name; '' when the name has no Latin letters to keep. */
export function slugKey(name) {
  const base = String(name ?? '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-').replace(/-{2,}/g, '-').replace(/^[^a-z]+/, '').replace(/[-_]+$/, '');
  return base.slice(0, 48).replace(/[-_]+$/, '');
}

export function newForm(available) {
  return { name: '', key: '', keyEdited: false, mode: 'propose_only', tools: presetTools(available, 'propose', 'propose_only'), days: DEFAULT_DAYS };
}
export function setName(form, name) {
  return { ...form, name, key: form.keyEdited ? form.key : slugKey(name) };
}
export const setKey = (form, key) => ({ ...form, key, keyEdited: true });
export function toggleTool(form, name) {
  return { ...form, tools: form.tools.includes(name) ? form.tools.filter(tool => tool !== name) : [...form.tools, name] };
}
/** Choosing generate also ticks the generation tools (the point of that mode); going back removes them. */
export function setMode(form, mode, available) {
  const generation = (available || []).filter(tool => tool.generation).map(tool => tool.name);
  const tools = mode === 'generate' ? [...new Set([...form.tools, ...generation])] : form.tools.filter(tool => !generation.includes(tool));
  return { ...form, mode, tools };
}

/** Problems the server would refuse, found first so the button can wait; each value is a message code or ''. */
export function validateForm(form, accounts, available) {
  const generation = new Set((available || []).filter(tool => tool.generation).map(tool => tool.name));
  const name = form.name.trim();
  const days = Number(form.days);
  return {
    name: !name ? 'nameRequired' : name.length > 120 ? 'nameLong' : '',
    key: !form.key ? 'keyRequired' : !KEY_PATTERN.test(form.key) ? 'keyInvalid' : (accounts || []).some(account => account.accountKey === form.key) ? 'keyTaken' : '',
    tools: form.tools.length === 0 ? 'noTools' : form.mode !== 'generate' && form.tools.some(tool => generation.has(tool)) ? 'generationNeedsMode' : '',
    days: Number.isInteger(days) && days >= 1 && days <= MAX_DAYS ? '' : 'daysInvalid',
  };
}
export const formValid = errors => Object.values(errors).every(code => !code);

/** The POST body; tools keep the registry's order so the stored scope reads the same as the list. */
export function createBody(form, available) {
  const order = (available || []).map(tool => tool.name);
  const tools = [...form.tools].sort((a, b) => order.indexOf(a) - order.indexOf(b));
  return { accountKey: form.key, displayName: form.name.trim(), tools, writeMode: form.mode, expiresInDays: Number(form.days) };
}

export const daysLabel = days => (days === 1 ? t('console.external.day') : t('console.external.days', { n: days }));
export const dateText = (value, options = { dateStyle: 'medium' }) => {
  const date = value ? new Date(value) : null;
  return date && !Number.isNaN(date.getTime()) ? date.toLocaleString(currentLocale(), options) : '';
};
export const dateTimeText = value => dateText(value, { dateStyle: 'medium', timeStyle: 'short' });
export const expiryPreview = (days, now = Date.now()) => dateText(now + Number(days) * DAY);

// ---------- connecting ----------

/** The address zerofield-mcp should use: this page's own address when it is local, otherwise the default. */
export function serverUrl(location = globalThis.location) {
  const host = location?.hostname || '';
  const local = location?.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]', '::1'].includes(host);
  if (!local) return { url: DEFAULT_URL, local: false, host };
  return { url: 'http://' + host + (location.port ? ':' + location.port : ''), local: true, host };
}

/** Ready-to-paste setup for one agent. `http` is whatever the server reports for Streamable HTTP, or nothing. */
export function connectionSnippets({ token = TOKEN_PLACEHOLDER, project, url = DEFAULT_URL, http = null }) {
  const env = [[TOKEN_ENV, token], [PROJECT_ENV, project], [URL_ENV, url]];
  const claude = 'claude mcp add zerofield ' + env.map(([key, value]) => `-e ${key}=${value}`).join(' ') + ' -- ' + COMMAND;
  const json = JSON.stringify({ mcpServers: { zerofield: { command: COMMAND, env: Object.fromEntries(env) } } }, null, 2);
  const server = http && typeof http.url === 'string' && http.url ? { url: http.url, header: 'Authorization: Bearer ' + token } : null;
  return { claude, json, env, http: server };
}

// A token only exists in the response that created it. Keeping it in this module (memory only, never storage)
// lets a showrunner leave the page and come back before copying it; a reload drops it, which is the intent.
const held = new Map();
export const holdIssued = (slug, issued) => { held.set(slug, issued); };
export const heldIssued = slug => held.get(slug) || null;
export const releaseIssued = slug => { held.delete(slug); };

// ---------- the account list ----------

/** Status the page shows now: a token whose expiry passed since the list loaded counts as expired. */
export function effectiveStatus(account, now = Date.now()) {
  if (account.status !== 'active') return account.status;
  const expires = Date.parse(account.expiresAt);
  return Number.isFinite(expires) && expires <= now ? 'expired' : 'active';
}
export const STATUS_TONE = { active: 'ok', expired: 'warn', revoked: 'bad', disabled: 'warn' };

export function expiryLine(account, now = Date.now()) {
  const status = effectiveStatus(account, now);
  if (status === 'revoked') return t('console.external.expires.revoked', { date: dateText(account.revokedAt) });
  if (status !== 'active') return t('console.external.expires.expired', { date: dateText(account.expiresAt) });
  const left = Math.ceil((Date.parse(account.expiresAt) - now) / DAY);
  return t('console.external.expires.active', { date: dateText(account.expiresAt), left: left <= 1 ? t('console.external.leftToday') : t('console.external.leftDays', { n: left }) });
}

/** The latest sign of life: the token's last authentication or its last audited call, whichever is newer. */
export function lastActivity(account) {
  const times = [account.lastUsedAt, account.usage?.lastCallAt].map(value => Date.parse(value)).filter(Number.isFinite);
  return times.length ? new Date(Math.max(...times)).toISOString() : null;
}
export const lastUsedLine = account => {
  const last = lastActivity(account);
  return last ? t('console.external.lastUsed', { when: dateTimeText(last) }) : t('console.external.neverUsed');
};
export function usageLine(account) {
  const usage = account.usage || {};
  const calls = Number(usage.calls) || 0;
  if (!calls) return t('console.external.noCalls');
  const base = t('console.external.calls', { total: calls, ok: Number(usage.succeeded) || 0, refused: Number(usage.refused) || 0 });
  return usage.generationRequests ? base + ' · ' + t('console.external.renders', { n: usage.generationRequests }) : base;
}
/** Display names of an account's tools; a tool the registry no longer offers keeps its wire name. */
export function toolLabels(account, available) {
  const labels = Object.fromEntries((available || []).map(tool => [tool.name, tool.label]));
  return (account.tools || []).map(name => ({ name, label: labels[name] || name }));
}

// ---------- the audit trail ----------

const KNOWN_CODES = ['NOT_IN_SCOPE', 'RATE_LIMITED', 'TOKEN_REVOKED', 'TOKEN_EXPIRED', 'TOKEN_DISABLED', 'WRONG_PROJECT', 'ISSUER_REVOKED',
  'INVALID_ARGUMENTS', 'POLICY_DENIED', 'TOOL_FAILED', 'REFUSED'];
const OUTCOME_TONE = { ok: 'ok', error: 'bad', denied: 'warn' };

/** One audit row as plain lines: when, who, what ran, how it ended and anything it produced. */
export function auditLine(entry, account, available) {
  const labels = Object.fromEntries((available || []).map(tool => [tool.name, tool.label]));
  const actor = entry.actor?.name || '';
  const client = entry.client?.name ? entry.client.name + (entry.client.version ? ' ' + entry.client.version : '') : '';
  const base = { id: entry.id, at: dateTimeText(entry.at), kind: entry.kind };
  if (entry.kind === 'issued') {
    return { ...base, who: actor ? t('console.external.audit.by', { name: actor }) : '', what: t('console.external.audit.issued'),
      detail: t('console.external.audit.issuedDetail', { n: (entry.tools || []).length, mode: t('console.external.mode.' + (entry.writeMode || 'propose_only') + '.title') }), result: null };
  }
  if (entry.kind === 'revoked') {
    return { ...base, who: actor ? t('console.external.audit.by', { name: actor }) : '', what: t('console.external.audit.revoked'), detail: '', result: null };
  }
  const code = entry.code && KNOWN_CODES.includes(entry.code) ? t('console.external.code.' + entry.code) : entry.code || '';
  const proposals = (entry.proposalIds || []).map(id => t('console.external.audit.proposal', { id }));
  return { ...base,
    who: client || account?.displayName || account?.accountKey || '',
    actingFor: actor ? t('console.external.audit.actingFor', { name: actor }) : '',
    what: entry.tool ? labels[entry.tool] || entry.tool : t('console.external.audit.connect'),
    tool: entry.tool || '',
    result: { tone: OUTCOME_TONE[entry.outcome] || 'muted', label: t('console.external.audit.result.' + (OUTCOME_TONE[entry.outcome] ? entry.outcome : 'unknown')) },
    detail: [code, ...proposals].filter(Boolean).join(' · ') };
}

/** A load or action failure in words: the account key clash and rejected input are specific, the rest generic. */
export function externalError(error) {
  const data = error?.data || {};
  if (error?.status === 409 && data.code === 'ACCOUNT_EXISTS') return t('console.external.error.keyTaken');
  if (error?.status === 400 && data.code === 'INVALID_REQUEST' && typeof data.error === 'string') return data.error;
  if (error?.status === 429) return t('console.external.error.busy');
  return consoleError(error);
}
