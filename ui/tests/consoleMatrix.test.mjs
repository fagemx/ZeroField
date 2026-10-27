// SPEC_20 R37: the role x model matrix, the hosted open-weights switch and the R12 failure classes in the queue.
import test, {before, after} from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {build} from 'esbuild';
import {mkdtemp, readFile, writeFile, rm} from 'node:fs/promises';
import {join, dirname, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {setLocale, t} from '../src/i18n/index.js';
import {GROUPS, PAGES} from '../src/agentConsole/model.js';
import {providerFailureText, PROVIDER_FAILURES} from '../src/assistant/providerFailures.js';
import {DENIALS, INHERIT, TIERS, abilities, applyProblem, changeBody, choiceNotes, contextSize, denialText, endpointNote, groupChoices,
  hostedBody, isCurrent, readyView, whereLine} from '../src/agentConsole/matrixModel.js';
import {queueLine, turnReason} from '../src/agentConsole/opsModel.js';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
let temporary, ui;
before(async () => {
  temporary = await mkdtemp(join(root, 'tests/.console-matrix-'));
  const result = await build({stdin: {contents: "export {MatrixBody, ModelMatrix} from './src/agentConsole/ConsoleModelMatrix.jsx'; export {ConsoleContext} from './src/agentConsole/shared.jsx'; export {setLocale} from './src/i18n/index.js';",
    resolveDir: root, sourcefile: 'console-matrix.jsx', loader: 'jsx'}, bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', packages: 'external', loader: {'.css': 'empty'}});
  const output = join(temporary, 'components.mjs');
  await writeFile(output, result.outputFiles[0].text);
  ui = await import(pathToFileURL(output));
});
after(async () => {if (temporary) await rm(temporary, {recursive: true, force: true});});

const PRESET = 'http://127.0.0.1:11434/v1';
const caps = (extra = {}) => ({tools: true, tool_choice: false, json_schema: true, vision: true, image_url: false, ...extra});
const local = {model: 'qwen3.8:27b', label: 'Qwen3.8 27B (local, Ollama)', catalogId: 'ollama-qwen3.8-27b', local: true, host: '127.0.0.1', port: 11434, baseUrl: PRESET,
  tier: 'local_open', capabilities: caps(), assumed: false, contextTokens: 16384};
const hosted = {model: 'qwen/qwen3.8-27b', label: 'Qwen3.8 27B (hosted open weights, OpenRouter)', catalogId: 'openrouter-qwen3.8-27b', local: false, host: 'openrouter.ai', port: 443,
  baseUrl: null, tier: 'hosted_open', capabilities: caps({tool_choice: true, image_url: true}), assumed: false, contextTokens: 32768};
const unknown = {model: 'mistral:7b', label: null, catalogId: null, local: true, host: '127.0.0.1', port: 11434, baseUrl: PRESET, tier: 'local_open',
  capabilities: caps({json_schema: false}), assumed: true, contextTokens: 8192};
const row = (agentKey, displayName, current, extra = {}) => ({agentKey, displayName, custom: false, enabled: true, version: 4, inherits: false, state: 'ok',
  current, denials: [], readiness: {state: 'ready', blockers: [], reachable: true, modelPresent: true}, ...extra});
const choices = [
  {...unknown, key: '|' + PRESET + '|mistral:7b', source: 'listing', listed: true, denials: [], allowed: true, apiKeyEnv: null, keyConfigured: null},
  {...local, key: 'ollama-qwen3.8-27b|' + PRESET + '|qwen3.8:27b', source: 'listing', listed: true, denials: [], allowed: true, apiKeyEnv: null, keyConfigured: null},
  {...hosted, key: 'openrouter-qwen3.8-27b|https://openrouter.ai/api/v1|qwen/qwen3.8-27b', source: 'catalog', listed: null,
    denials: ['hosted_open_disabled', 'key_not_allowed', 'pricing_missing'], allowed: false, apiKeyEnv: 'OPENROUTER_API_KEY', keyConfigured: false},
];
const data = (hostedOpenEnabled = false) => ({
  policy: {production: 'open_weights_only', hybrid: false, hostedOpenEnabled, settingsVersion: 3, closedHidden: 2},
  endpoints: [{baseUrl: PRESET, host: '127.0.0.1', port: 11434, state: 'ok', count: 2}],
  rows: [
    row('coordinator', 'Showrunner', local, {inherits: true}),
    row('sheet_ops', 'Cinematographer', hosted, {denials: ['hosted_open_disabled'], readiness: {state: 'blocked', reachable: null, modelPresent: null, blockers: [
      {code: 'network_policy', agentKey: 'sheet_ops', fix: 'enable_hosted_open', host: 'openrouter.ai', model: 'qwen/qwen3.8-27b', tier: 'hosted_open'}]}}),
    row('continuity_notes', 'Continuity Notes', unknown, {custom: true, readiness: {state: 'untested', blockers: [], reachable: null, modelPresent: null}}),
    row('qa_critic', 'Continuity Supervisor', local, {enabled: false, inherits: true, readiness: {state: 'off', blockers: [], reachable: null, modelPresent: null}}),
    row('doc_writer', 'Screenwriter', null, {state: 'kind_removed', readiness: {state: 'blocked', reachable: null, modelPresent: null, blockers: []}}),
  ],
  choices,
});
const rows0 = () => data().rows[0];
const render = (payload, open = null, canEdit = true) => renderToStaticMarkup(React.createElement(ui.ConsoleContext.Provider,
  {value: {canEdit, request: async () => ({}), action: async fn => fn(), refresh() {}}}, React.createElement(ui.MatrixBody, {data: payload, open, onToggle() {}})));

test('the matrix lives on Providers & API Keys: still four groups and twelve pages', async () => {
  assert.equal(PAGES.length, 12);
  assert.deepEqual(Object.keys(GROUPS), ['workspace', 'build', 'managed_agents', 'analytics']);
  const managed = await readFile(new URL('../src/agentConsole/ConsoleManagedViews.jsx', import.meta.url), 'utf8');
  assert.match(managed, /<ModelSetup\/><ModelMatrix\/>/, 'the matrix sits right under model setup on the existing page');
});

test('every role row names its model, tier, abilities and readiness; a denied tier says why', async () => {
  await setLocale('en');
  const html = render(data());
  for (const text of ['Showrunner', 'Cinematographer', 'Continuity Notes', 'Continuity Supervisor', 'Screenwriter', 'Custom', 'Turned off']) assert.ok(html.includes(text), text);
  assert.ok(html.includes('<code class="ac-model">qwen3.8:27b</code>'));
  assert.ok(html.includes('On this computer (127.0.0.1:11434)') && html.includes('Hosted on openrouter.ai'));
  assert.ok(html.includes('Local open weights') && html.includes('Hosted open weights'));
  assert.ok(html.includes('16k context') && html.includes('32k context') && html.includes('8k context'));
  assert.match(html, /aria-label="JSON schema: no"[^>]*>JSON schema</, 'an ability the model lacks reads as no');
  assert.match(html, /aria-label="Vision: yes"/);
  assert.ok(html.includes('assumed'), 'a model outside the catalog has assumed abilities');
  assert.ok(html.includes('Hosted open weights are off. Turn on the switch above first.'), 'the tier reason shows in the row');
  assert.ok(html.includes('runs on a hosted open-weights service (openrouter.ai)'), 'the readiness blocker is the plain crew line');
  assert.ok(html.includes('Ready') && html.includes('Blocked') && html.includes('Not tested') && html.includes('Off'));
  assert.ok(html.includes('uses the default model'));
  assert.ok(html.includes('removed ChatGPT connection'), 'a role with unusable settings says what to do');
  assert.ok(html.includes('2 closed models are not listed because this production allows open weights only'));
  assert.ok(!html.includes('<tr class="ac-matrix-panel">'), 'no change panel until a row is opened');
});

test('the hosted open-weights switch explains it is outside the contest demo path and reflects the setting', async () => {
  await setLocale('en');
  const off = render(data(false));
  assert.match(off, /<button type="button" role="switch" aria-checked="false"/);
  assert.ok(off.includes('not part of the contest demo path') && off.includes('Off: the crew uses models on this computer only.'));
  assert.ok(off.includes('each hosted model still needs an allowed host, an API key reference and a price ceiling'));
  assert.ok(!off.includes('class="ac-hosted on"'));
  const on = render(data(true));
  assert.match(on, /role="switch" aria-checked="true"/);
  assert.ok(on.includes('class="ac-hosted on"') && on.includes('On: hosted open-weights models can be chosen below.'));
  const hybrid = data(false);
  hybrid.policy = {...hybrid.policy, production: 'hybrid_studio', hybrid: true, closedHidden: 0};
  const hybridHtml = render(hybrid);
  assert.ok(hybridHtml.includes('already allows hosted open-weights models') && !hybridHtml.includes('Off: the crew uses models on this computer only.'),
    'under the hybrid policy the switch does not claim the crew is local-only');
  assert.ok(!hybridHtml.includes('closed models are not listed'), 'the hybrid policy lists closed models, so nothing is hidden');
  assert.deepEqual(hostedBody({settingsVersion: 3}, true), {hosted_open_enabled: true, version: 3});
  assert.deepEqual(hostedBody({settingsVersion: 3}, 'yes'), {hosted_open_enabled: false, version: 3}, 'only a real true turns it on');
});

test('opening a row lists local models and catalog models; denied ones are disabled with the reason', async () => {
  await setLocale('en');
  const html = render(data(), 'sheet_ops');
  assert.ok(html.includes('Choose a model for Cinematographer'));
  assert.ok(html.includes('Models on this computer (127.0.0.1:11434)') && html.includes('Catalog models') && html.includes('Use the default model'));
  const denied = html.split('<label class="ac-choice').filter(part => part.includes('openrouter.ai') && part.includes('denied'));
  assert.equal(denied.length, 1);
  assert.match(denied[0], /disabled=""/, 'a denied choice cannot be picked');
  for (const reason of ['Hosted open weights are off. Turn on the switch above first.', 'qwen/qwen3.8-27b has no price ceiling yet. Add one in Spend &amp; Rate Limits first.',
    'does not allow the key variable OPENROUTER_API_KEY yet']) assert.ok(denied[0].includes(reason), reason);
  const allowed = html.split('<label class="ac-choice').filter(part => part.includes('mistral:7b') && part.includes('<input'));
  assert.ok(allowed.length >= 1 && !/disabled=""/.test(allowed[0].split('</label>')[0]), 'a listed local model can be picked');
  assert.match(html, /<button type="button" class="qs-primary" disabled="">Use this model<\/button>/, 'nothing is picked yet');
  assert.ok(html.includes('Showrunner') && html.indexOf('<tr class="ac-matrix-panel">') > html.indexOf('Cinematographer'));
});

test('the matrix, switch and reasons read in Traditional Chinese too', async () => {
  await setLocale('zh-TW');
  await ui.setLocale('zh-TW');  // the bundled components carry their own i18n instance
  try {
    const html = render(data(), 'sheet_ops');
    for (const text of ['本機開放權重', '託管開放權重', '允許託管開放權重模型', '不在比賽展示路徑上', '託管開放權重目前是關閉的。請先打開上方的開關。',
      '替「Cinematographer」選模型', '這台電腦上的模型（127.0.0.1:11434）', '目錄裡的模型', '改用這個模型']) assert.ok(html.includes(text), text);
    assert.equal(abilities(local).chips.map(chip => chip.name).join('/'), '工具呼叫/JSON 格式輸出/看圖');
  } finally {
    await setLocale('en');
    await ui.setLocale('en');
  }
});

test('abilities, context sizes and locations read plainly', async () => {
  await setLocale('en');
  assert.deepEqual([16384, 8192, 32768, 1047576, 1048576, 512, 0, null].map(contextSize), ['16k', '8k', '32k', '1M', '1M', '512', '?', '?']);
  const mark = abilities(unknown);
  assert.deepEqual(mark.chips.map(chip => [chip.key, chip.on]), [['tools', true], ['json_schema', false], ['vision', true]]);
  assert.deepEqual([mark.context, mark.assumed], ['8k', true]);
  assert.equal(abilities(null).assumed, false);
  assert.equal(whereLine(local), 'On this computer (127.0.0.1:11434)');
  assert.equal(whereLine(hosted), 'Hosted on openrouter.ai');
  assert.equal(whereLine(null), '');
});

test('readiness: blocked, untested and off rows, and roles whose model settings cannot be used', async () => {
  await setLocale('en');
  const rows = data().rows;
  assert.deepEqual(rows.map(r => readyView(r).state), ['ready', 'blocked', 'untested', 'off', 'blocked']);
  assert.deepEqual(rows.map(r => readyView(r).tone), ['ok', 'bad', 'muted', 'muted', 'bad']);
  assert.match(readyView(rows[4]).setup, /removed ChatGPT connection/);
  assert.match(readyView({...rows[4], state: 'configuration_required'}).setup, /can no longer be used/);
  assert.match(readyView({...rows[4], state: 'something_new'}).setup, /cannot be used/, 'an unknown state from a newer server still reads as a sentence');
});

test('choices are grouped by endpoint listing and catalog; an endpoint that cannot list says so', async () => {
  await setLocale('en');
  const endpoints = [{baseUrl: PRESET, host: '127.0.0.1', port: 11434, state: 'ok', count: 2}];
  const groups = groupChoices(choices, endpoints);
  assert.deepEqual(groups.map(g => [g.kind, g.items.map(i => i.model)]), [['listing', ['mistral:7b', 'qwen3.8:27b']], ['catalog', ['qwen/qwen3.8-27b']]]);
  assert.deepEqual(groupChoices([], []), []);
  assert.equal(endpointNote(endpoints[0]), '');
  assert.equal(endpointNote({...endpoints[0], state: 'down'}), 'Nothing answered at 127.0.0.1:11434. Start Ollama or your model server, then check again.');
  assert.match(endpointNote({...endpoints[0], state: 'bad'}), /not like a model server/);
  assert.match(endpointNote({...endpoints[0], state: 'unlisted'}), /did not list its models/);
  assert.match(endpointNote({...endpoints[0], state: 'brand_new'}), /not like a model server/);
  assert.ok(isCurrent(rows0(), choices[1]) && !isCurrent(rows0(), choices[0]) && !isCurrent(rows0(), choices[2]));
  assert.ok(isCurrent(row('sheet_ops', 'C', hosted), choices[2]), 'a hosted model is the same by host and name');
  assert.equal(isCurrent(row('x', 'X', null), choices[0]), false);
});
test('a change is sent as a local model, a catalog entry or the default, with the row version', () => {
  const r = row('sheet_ops', 'Cinematographer', local);
  assert.deepEqual(changeBody(r, choices[0]), {agent_key: 'sheet_ops', version: 4, base_url: PRESET, model: 'mistral:7b'});
  assert.deepEqual(changeBody(r, choices[2]), {agent_key: 'sheet_ops', version: 4, catalog_id: 'openrouter-qwen3.8-27b'});
  assert.deepEqual(changeBody(r, INHERIT), {agent_key: 'sheet_ops', version: 4, inherit: true});
  assert.ok(!JSON.stringify(changeBody(r, choices[2])).includes('api_key'), 'no key or key variable travels from the page');
});

test('every denial code, tier, ready state and endpoint state has words in both languages', async () => {
  for (const locale of ['en', 'zh-TW']) {
    await setLocale(locale);
    for (const code of DENIALS) assert.notEqual(t('console.matrix.denial.' + code), 'console.matrix.denial.' + code, code);
    for (const tier of TIERS) assert.notEqual(t('console.matrix.tier.' + tier), 'console.matrix.tier.' + tier, tier);
    for (const state of ['ready', 'blocked', 'untested', 'off']) assert.notEqual(t('console.matrix.ready.' + state), 'console.matrix.ready.' + state, state);
    for (const state of ['kind_removed', 'configuration_required', 'unsupported_kind']) assert.notEqual(t('console.matrix.state.' + state), 'console.matrix.state.' + state, state);
    for (const state of ['down', 'bad', 'unlisted']) assert.notEqual(t('console.matrix.endpoint.' + state), 'console.matrix.endpoint.' + state, state);
    for (const policy of ['open_weights_only', 'hybrid_studio']) assert.notEqual(t('console.matrix.policy.' + policy), 'console.matrix.policy.' + policy, policy);
    assert.ok(denialText('from_a_newer_server').includes('from_a_newer_server'));
  }
  await setLocale('en');
});

test('denial reasons name the model and key variable; warnings never block', async () => {
  await setLocale('en');
  assert.match(denialText('pricing_missing', {model: 'qwen/qwen3.8-27b'}), /^qwen\/qwen3\.8-27b has no price ceiling yet/);
  assert.match(denialText('key_not_allowed', {apiKeyEnv: 'OPENROUTER_API_KEY'}), /OPENROUTER_API_KEY/);
  const notes = choiceNotes({...hosted, denials: [], keyConfigured: false, apiKeyEnv: 'OPENROUTER_API_KEY', listed: null});
  assert.deepEqual(notes.map(n => n.tone), ['warn']);
  assert.match(notes[0].text, /has no value on the server yet/);
  assert.deepEqual(choiceNotes({...hosted, denials: ['key_not_allowed'], keyConfigured: false, apiKeyEnv: 'X'}).map(n => n.tone), ['bad'], 'the key warning is not repeated under a key denial');
  assert.deepEqual(choiceNotes({...local, denials: [], listed: false}).map(n => n.text), ['Not installed on this server yet. Pull or load it first.']);
  assert.deepEqual(choiceNotes(null), []);
});

test('a refused change says why: a policy reason, a stale page, or nothing for the generic message', async () => {
  await setLocale('en');
  const refused = code => ({status: 409, data: {code}});
  assert.equal(applyProblem(refused('hosted_open_disabled'), choices[2]), 'Hosted open weights are off. Turn on the switch above first.');
  assert.match(applyProblem(refused('pricing_missing'), choices[2]), /no price ceiling yet/);
  assert.match(applyProblem(refused('VERSION_CONFLICT'), choices[2]), /changed somewhere else/);
  assert.equal(applyProblem({status: 503, data: null}, choices[2]), '');
  assert.equal(applyProblem(null, null), '');
});

test('the queue shows the R12 failure class in plain words instead of the raw error kind', async () => {
  await setLocale('en');
  for (const kind of PROVIDER_FAILURES) {
    assert.equal(turnReason({errorKind: kind}), providerFailureText(kind), kind);
    assert.ok(!turnReason({errorKind: kind}).includes('Failed ('), kind);
  }
  assert.match(turnReason({errorKind: 'gpu_busy'}), /^The GPU is busy with a render/);
  assert.equal(turnReason({errorKind: 'admission'}), 'Governance refused the call before it was sent.', 'kinds that are not classes keep their own line');
  assert.equal(turnReason({errorKind: 'abandoned'}), 'The turn did not finish after several tries. Send it again.');
  assert.equal(turnReason({errorKind: 'brand_new_kind'}), 'Failed (brand_new_kind).');
  const failed = queueLine('dispatches', {status: 'failed', agentKey: 'sheet_ops', failure: 'quota', error: 'HTTP 429 Too Many Requests from the provider', mine: true});
  assert.equal(failed.reason, providerFailureText('quota'));
  assert.ok(!failed.reason.includes('429'), 'the raw error stays in the run log');
  assert.equal(queueLine('dispatches', {status: 'failed', agentKey: 'sheet_ops', failure: null, error: 'Lease expired before the worker answered.'}).reason, 'Lease expired before the worker answered.');
  assert.equal(queueLine('dispatches', {status: 'failed', agentKey: 'sheet_ops', failure: 'not_a_class', error: 'odd'}).reason, 'odd');
  assert.equal(queueLine('tasks', {status: 'failed', nodeId: 'render', tabKey: 'cinema-studio', failure: 'local', error: 'ComfyUI rejected the workflow'}).reason, 'ComfyUI rejected the workflow',
    'pipeline tasks are not model calls');
  await setLocale('zh-TW');
  try {
    assert.equal(turnReason({errorKind: 'local'}), providerFailureText('local'));
    assert.match(turnReason({errorKind: 'gpu_busy'}), /^顯示卡正在算圖/);
    assert.equal(queueLine('dispatches', {status: 'failed', agentKey: 'a', failure: 'timeout'}).reason, providerFailureText('timeout'));
  } finally {
    await setLocale('en');
  }
});

test('only the showrunner sees the matrix page content', async () => {
  await setLocale('en');
  const html = renderToStaticMarkup(React.createElement(ui.ConsoleContext.Provider, {value: {canEdit: false}}, React.createElement(ui.ModelMatrix)));
  assert.ok(html.includes('Only the showrunner can see and change which model each role uses.'));
  assert.ok(!html.includes('role="switch"'));
});
