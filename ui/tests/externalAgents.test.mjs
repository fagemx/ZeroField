import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { setLocale, t } from '../src/i18n/index.js';
import { GROUPS, PAGES } from '../src/agentConsole/model.js';
import { COMMAND, DEFAULT_URL, KNOWN_TOOLS, auditLine, connectionSnippets, createBody, effectiveStatus, expiryLine, expiryPreview, externalError,
  formValid, heldIssued, holdIssued, lastActivity, newForm, presetTools, releaseIssued, serverUrl, setKey, setMode, setName, slugKey,
  toggleTool, toolGroups, toolKind, toolLabels, usageLine, validateForm } from '../src/agentConsole/externalAgentsModel.js';

// What GET service-accounts reports as availableTools today: nine tools for propose_only, ten for generate.
const AVAILABLE = [
  { name: 'propose_table_edit', label: 'Propose Slate Changes', category: 'legacy', writes: true, generation: false },
  { name: 'list_pages', label: 'Production Pages', category: 'legacy', writes: false, generation: false },
  { name: 'read_page', label: 'Production Page', category: 'legacy', writes: false, generation: false },
  { name: 'read_episode', label: 'Episode', category: 'context', writes: false, generation: false },
  { name: 'get_workflow', label: 'Workflow Guide', category: 'workflow', writes: false, generation: false },
  { name: 'request_generation', label: 'Request Generation', category: 'generation', writes: true, generation: true },
];
const NOW = Date.parse('2026-10-27T12:00:00Z');
const account = (extra = {}) => ({ accountKey: 'claude-code', displayName: 'Claude Code', project: 'film', tools: ['read_page', 'propose_table_edit'],
  writeMode: 'propose_only', expiresAt: '2026-11-26T12:00:00Z', createdAt: '2026-10-27T10:00:00Z', revokedAt: null, status: 'active', lastUsedAt: null,
  usage: { calls: 0, succeeded: 0, refused: 0, lastCallAt: null, generationRequests: 0 }, ...extra });

test('the connection page lives inside Environments & Bridges: still four groups and twelve pages', async () => {
  assert.equal(PAGES.length, 12);
  assert.deepEqual(Object.keys(GROUPS), ['workspace', 'build', 'managed_agents', 'analytics']);
  assert.ok(GROUPS.managed_agents.includes('environments'));
  const managed = await readFile(new URL('../src/agentConsole/ConsoleManagedViews.jsx', import.meta.url), 'utf8');
  assert.match(managed, /<ExternalAgents\/>/, 'Environments & Bridges carries the external agent section');
  const view = await readFile(new URL('../src/agentConsole/ConsoleExternalAgents.jsx', import.meta.url), 'utf8');
  assert.doesNotMatch(view, /sessionStorage|localStorage|useDraft/, 'a token is never written to browser storage');
});

test('tools group by what they do and the presets never include generation in propose-only mode', () => {
  assert.deepEqual(AVAILABLE.map(toolKind), ['propose', 'read', 'read', 'read', 'guide', 'generate']);
  assert.deepEqual(toolGroups(AVAILABLE).map(group => [group.kind, group.tools.length]), [['read', 3], ['guide', 1], ['propose', 1], ['generate', 1]]);
  assert.deepEqual(toolGroups([]), []);
  assert.deepEqual(presetTools(AVAILABLE, 'read', 'propose_only'), ['list_pages', 'read_page', 'read_episode', 'get_workflow']);
  assert.deepEqual(presetTools(AVAILABLE, 'propose', 'propose_only'), ['propose_table_edit', 'list_pages', 'read_page', 'read_episode', 'get_workflow']);
  assert.ok(!presetTools(AVAILABLE, 'all', 'propose_only').includes('request_generation'));
  assert.ok(presetTools(AVAILABLE, 'all', 'generate').includes('request_generation'));
  assert.deepEqual(newForm(AVAILABLE), { name: '', key: '', keyEdited: false, mode: 'propose_only', days: 30, tools: presetTools(AVAILABLE, 'propose', 'propose_only') });
});

test('the key follows the name until it is edited; names without Latin letters leave it for the person to type', () => {
  assert.equal(slugKey('Claude Code'), 'claude-code');
  assert.equal(slugKey('  Goose / Desktop 2 '), 'goose-desktop-2');
  assert.equal(slugKey('Éclair Agent'), 'eclair-agent');
  assert.equal(slugKey('9 lives'), 'lives');
  assert.equal(slugKey('我的代理'), '');
  assert.equal(slugKey('a'.repeat(80)).length, 48);
  let form = setName(newForm(AVAILABLE), 'Claude Code');
  assert.equal(form.key, 'claude-code');
  form = setKey(form, 'cc');
  form = setName(form, 'Claude Code Desktop');
  assert.equal(form.key, 'cc', 'an edited key is left alone');
});

test('switching the write mode ticks or drops the generation tools and the form catches what the server would refuse', () => {
  let form = setName(newForm(AVAILABLE), 'Claude Code');
  assert.ok(formValid(validateForm(form, [], AVAILABLE)));
  form = setMode(form, 'generate', AVAILABLE);
  assert.ok(form.tools.includes('request_generation'));
  assert.ok(formValid(validateForm(form, [], AVAILABLE)));
  const back = setMode(form, 'propose_only', AVAILABLE);
  assert.ok(!back.tools.includes('request_generation'));
  assert.equal(validateForm({ ...back, tools: ['request_generation'] }, [], AVAILABLE).tools, 'generationNeedsMode');
  assert.equal(validateForm({ ...form, tools: [] }, [], AVAILABLE).tools, 'noTools');
  assert.equal(validateForm({ ...form, name: '   ' }, [], AVAILABLE).name, 'nameRequired');
  assert.equal(validateForm({ ...form, name: 'x'.repeat(121) }, [], AVAILABLE).name, 'nameLong');
  assert.equal(validateForm({ ...form, key: '' }, [], AVAILABLE).key, 'keyRequired');
  for (const bad of ['Claude', '1abc', 'a b', 'a'.repeat(49)]) assert.equal(validateForm({ ...form, key: bad }, [], AVAILABLE).key, 'keyInvalid', bad);
  assert.equal(validateForm(form, [account()], AVAILABLE).key, 'keyTaken');
  for (const days of [0, 366, 2.5, 'x']) assert.equal(validateForm({ ...form, days }, [], AVAILABLE).days, 'daysInvalid', String(days));
  assert.equal(validateForm({ ...form, days: 365 }, [], AVAILABLE).days, '');
  assert.deepEqual(toggleTool({ ...form, tools: ['read_page'] }, 'read_page').tools, []);
});

test('the request body keeps registry order and sends exactly the fields the server accepts', () => {
  const form = { ...setName(newForm(AVAILABLE), ' Claude Code '), tools: ['get_workflow', 'read_page', 'propose_table_edit'], days: '7' };
  assert.deepEqual(createBody(form, AVAILABLE), { accountKey: 'claude-code', displayName: 'Claude Code', tools: ['propose_table_edit', 'read_page', 'get_workflow'],
    writeMode: 'propose_only', expiresInDays: 7 });
});

test('the snippet carries the command, the token variable, the production and the server address', () => {
  const snippets = connectionSnippets({ token: 'zfsa_abc', project: 'film', url: 'http://127.0.0.1:3020' });
  assert.equal(snippets.claude, 'claude mcp add zerofield -e ZEROFIELD_MCP_TOKEN=zfsa_abc -e ZEROFIELD_PROJECT=film -e ZEROFIELD_URL=http://127.0.0.1:3020 -- zerofield-mcp');
  assert.deepEqual(JSON.parse(snippets.json), { mcpServers: { zerofield: { command: COMMAND, env: { ZEROFIELD_MCP_TOKEN: 'zfsa_abc', ZEROFIELD_PROJECT: 'film', ZEROFIELD_URL: 'http://127.0.0.1:3020' } } } });
  assert.equal(snippets.http, null, 'stdio only until the server reports an HTTP endpoint');
  const placeholder = connectionSnippets({ project: 'film' });
  assert.match(placeholder.claude, /ZEROFIELD_MCP_TOKEN=zfsa_\.\.\. /);
  assert.doesNotMatch(placeholder.claude, /[<>]/, 'a placeholder must not be a shell redirect');
  assert.equal(placeholder.env.find(([key]) => key === 'ZEROFIELD_URL')[1], DEFAULT_URL);
  const http = connectionSnippets({ token: 'zfsa_abc', project: 'film', http: { url: 'http://127.0.0.1:3020/mcp' } });
  assert.deepEqual(http.http, { url: 'http://127.0.0.1:3020/mcp', header: 'Authorization: Bearer zfsa_abc' });
  assert.equal(connectionSnippets({ project: 'film', http: {} }).http, null);
});

test('the server address is this page when it is local and the default otherwise', () => {
  assert.deepEqual(serverUrl({ protocol: 'http:', hostname: '127.0.0.1', port: '3055' }), { url: 'http://127.0.0.1:3055', local: true, host: '127.0.0.1' });
  assert.equal(serverUrl({ protocol: 'http:', hostname: 'localhost', port: '' }).url, 'http://localhost');
  assert.equal(serverUrl({ protocol: 'http:', hostname: '[::1]', port: '3020' }).url, 'http://[::1]:3020');
  const tunnel = serverUrl({ protocol: 'https:', hostname: 'studio.example.com', port: '' });
  assert.deepEqual(tunnel, { url: DEFAULT_URL, local: false, host: 'studio.example.com' });
  assert.equal(serverUrl({ protocol: 'http:', hostname: '192.168.1.8', port: '3020' }).local, false);
  assert.equal(serverUrl(undefined).local, false);
});

test('a freshly issued token can be recovered from memory until the person hides it', () => {
  assert.equal(heldIssued('film'), null);
  holdIssued('film', { token: 'zfsa_x' });
  assert.deepEqual(heldIssued('film'), { token: 'zfsa_x' });
  assert.equal(heldIssued('other'), null);
  releaseIssued('film');
  assert.equal(heldIssued('film'), null);
});

test('accounts read as status, expiry, last use and call counts in plain words', async () => {
  await setLocale('en');
  assert.equal(effectiveStatus(account(), NOW), 'active');
  assert.equal(effectiveStatus(account({ expiresAt: '2026-10-27T11:00:00Z' }), NOW), 'expired', 'expiry passed since the list loaded');
  assert.equal(effectiveStatus(account({ status: 'revoked' }), NOW), 'revoked');
  assert.match(expiryLine(account(), NOW), /^Expires .*2026.* \(30 days left\)$/);
  assert.match(expiryLine(account({ expiresAt: '2026-10-27T20:00:00Z' }), NOW), /less than a day left/);
  assert.match(expiryLine(account({ status: 'revoked', revokedAt: '2026-10-28T00:00:00Z' }), NOW), /^Revoked /);
  assert.match(expiryLine(account({ status: 'expired', expiresAt: '2026-10-01T00:00:00Z' }), NOW), /^Expired /);
  assert.match(expiryPreview(7, NOW), /Nov 3, 2026/);
  assert.equal(usageLine(account()), 'No tool calls yet');
  assert.equal(usageLine(account({ usage: { calls: 12, succeeded: 10, refused: 2, generationRequests: 3 } })), '12 calls: 10 done, 2 refused or failed · 3 render requests');
  assert.equal(lastActivity(account()), null);
  assert.equal(lastActivity(account({ lastUsedAt: '2026-10-27T11:00:00Z', usage: { lastCallAt: '2026-10-27T11:30:00Z' } })), '2026-10-27T11:30:00.000Z');
  assert.deepEqual(toolLabels(account(), AVAILABLE), [{ name: 'read_page', label: 'Production Page' }, { name: 'propose_table_edit', label: 'Propose Slate Changes' }]);
  assert.deepEqual(toolLabels(account({ tools: ['gone_tool'] }), AVAILABLE), [{ name: 'gone_tool', label: 'gone_tool' }]);
});

test('audit rows show who, what, when and how it ended, never raw wire codes for the known ones', async () => {
  await setLocale('en');
  const acct = account();
  const ok = auditLine({ id: 4, kind: 'call', at: '2026-10-27T10:30:00Z', tool: 'read_page', outcome: 'ok', code: null, client: { name: 'Claude Code', version: '2.1' },
    actor: { id: 'a', name: 'Mei' }, proposalIds: [], writeMode: 'propose_only' }, acct, AVAILABLE);
  assert.deepEqual([ok.what, ok.tool, ok.who, ok.actingFor, ok.result], ['Production Page', 'read_page', 'Claude Code 2.1', 'acting for Mei', { tone: 'ok', label: 'Done' }]);
  const proposal = auditLine({ id: 5, kind: 'call', at: '2026-10-27T10:31:00Z', tool: 'propose_table_edit', outcome: 'ok', proposalIds: [12, 13] }, acct, AVAILABLE);
  assert.equal(proposal.detail, 'proposal #12 · proposal #13');
  assert.equal(proposal.who, 'Claude Code', 'without a client name the account is the actor');
  const refused = auditLine({ id: 6, kind: 'call', at: '2026-10-27T10:32:00Z', tool: 'spawn_agent', outcome: 'denied', code: 'NOT_IN_SCOPE' }, acct, AVAILABLE);
  assert.deepEqual([refused.what, refused.result.label, refused.detail], ['spawn_agent', 'Refused', "Tool is not in this token's scope"]);
  assert.equal(refused.result.tone, 'warn');
  const failed = auditLine({ id: 7, kind: 'call', at: '2026-10-27T10:33:00Z', tool: 'read_page', outcome: 'error', code: 'SOMETHING_NEW' }, acct, AVAILABLE);
  assert.deepEqual([failed.result, failed.detail], [{ tone: 'bad', label: 'Failed' }, 'SOMETHING_NEW']);
  const connect = auditLine({ id: 8, kind: 'call', at: '2026-10-27T10:34:00Z', tool: null, outcome: 'denied', code: 'TOKEN_REVOKED' }, acct, AVAILABLE);
  assert.deepEqual([connect.what, connect.detail], ['Connection attempt', 'Token was revoked']);
  const issued = auditLine({ id: 1, kind: 'issued', at: '2026-10-27T10:00:00Z', actor: { name: 'Mei' }, tools: ['a', 'b', 'c'], writeMode: 'generate' }, acct, AVAILABLE);
  assert.deepEqual([issued.what, issued.who, issued.detail, issued.result], ['Token created', 'by Mei', '3 tools, Propose and generate', null]);
  const revoked = auditLine({ id: 9, kind: 'revoked', at: '2026-10-28T10:00:00Z', actor: { id: 'a', name: null } }, acct, AVAILABLE);
  assert.deepEqual([revoked.what, revoked.who], ['Token revoked', '']);
});

test('errors name the key clash and rejected input, and fall back to the Console wording', async () => {
  await setLocale('en');
  assert.match(externalError({ status: 409, data: { code: 'ACCOUNT_EXISTS', error: 'x' } }), /already has an agent with that key/);
  assert.equal(externalError({ status: 400, data: { code: 'INVALID_REQUEST', error: 'tools must list the tools this agent may use, each once.' } }), 'tools must list the tools this agent may use, each once.');
  assert.match(externalError({ status: 429, data: {} }), /Too many requests/);
  assert.equal(externalError({ status: 403, data: {} }), t('console.denied'));
});

test('every message has English and Traditional Chinese text and the tool lines cover the exposed tools', async () => {
  const [en, zh] = await Promise.all(['en', 'zh-TW'].map(async locale => JSON.parse(await readFile(new URL(`../src/i18n/locales/${locale}.json`, import.meta.url), 'utf8')).console));
  const keys = Object.keys(en).filter(key => key.startsWith('external.'));
  assert.ok(keys.length > 100);
  assert.deepEqual(keys, Object.keys(zh).filter(key => key.startsWith('external.')));
  for (const tool of KNOWN_TOOLS) assert.ok(en['external.tool.' + tool] && zh['external.tool.' + tool], tool);
  for (const kind of ['read', 'guide', 'propose', 'generate']) assert.ok(en['external.kindHelp.' + kind] && en['external.kind.' + kind], kind);
  const sameInBoth = ['external.form.namePlaceholder', 'external.setup.http.title'];  // product names stay as they are
  for (const key of keys.filter(key => !sameInBoth.includes(key))) assert.notEqual(zh[key], en[key], key + ' is untranslated');
  await setLocale('zh-TW');
  assert.equal(t('console.external.title'), '外部代理');
  assert.match(t('console.external.mode.noMoney'), /無法花錢/);
  assert.equal(t('console.external.days', { n: 30 }), '30 天');
  await setLocale('en');
  assert.equal(t('console.external.days', { n: 30 }), '30 days');
});
