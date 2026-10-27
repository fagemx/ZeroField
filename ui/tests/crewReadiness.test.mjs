// SPEC_20 R2: the crew board banner says, one plain line per problem, why the crew can't work and how to fix it.
import test, {before, after} from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {build} from 'esbuild';
import {mkdtemp, writeFile, rm} from 'node:fs/promises';
import {join, dirname, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
let temporary, ui;
before(async () => {
  temporary = await mkdtemp(join(root, 'tests/.crew-readiness-'));
  const result = await build({stdin: {contents: "export {AgentBoard, CrewReadinessBanner, readinessLines} from './src/assistant/AgentBoard.jsx'; export {setLocale} from './src/i18n/index.js';",
    resolveDir: root, sourcefile: 'crew-readiness.jsx', loader: 'jsx'}, bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', packages: 'external', loader: {'.css': 'empty'}});
  const output = join(temporary, 'components.mjs');
  await writeFile(output, result.outputFiles[0].text);
  ui = await import(pathToFileURL(output));
});
after(async () => {if (temporary) await rm(temporary, {recursive: true, force: true});});

const crew = [
  {id: 'agent:coordinator', kind: 'agent', agent_key: 'coordinator', display_name: 'Showrunner', icon: '🧭', status: 'needs_setup', active_dispatches: 0, max_concurrency: 2},
  {id: 'agent:sheet_ops', kind: 'agent', agent_key: 'sheet_ops', display_name: 'Cinematographer', icon: '📊', status: 'needs_setup', active_dispatches: 0, max_concurrency: 2},
  {id: 'agent:limb:w1', kind: 'agent', agent_key: 'limb:w1', display_name: 'Render box', icon: '🔌', status: 'offline', active_dispatches: 0, max_concurrency: 1},
];
const blocked = {ready: false, checkedAt: '2026-10-28T09:00:00Z', worker: {running: false, lastSeenAt: null}, providers: [], blockers: [
  {code: 'worker_not_running', agentKey: null, fix: 'restart_without_no_worker'},
  {code: 'model_missing', agentKey: 'coordinator', fix: 'ollama_pull', model: 'qwen3.8:27b'},
  {code: 'model_missing', agentKey: 'sheet_ops', fix: 'ollama_pull', model: 'qwen3.8:27b'},
  {code: 'network_policy', agentKey: 'sheet_ops', fix: 'allow_host', host: 'models.example.test'},
]};
const banner = props => renderToStaticMarkup(React.createElement(ui.CrewReadinessBanner, {agents: crew, onCheck() {}, ...props}));
const buttons = html => [...html.matchAll(/<button\b[^>]*>([^<]*)<\/button>/g)].map(match => match[1]);

test('each problem is one plain line with its fix; agents that share it are named once', () => {
  const lines = ui.readinessLines(blocked, crew);
  assert.deepEqual(lines.map(line => [line.text, line.command, line.agents]), [
    ['The background worker isn\'t running. Restart the studio without --no-worker.', '', []],
    ['qwen3.8:27b isn\'t installed in Ollama. On the studio computer, run:', 'ollama pull qwen3.8:27b', ['Showrunner', 'Cinematographer']],
    ['The agent environment doesn\'t allow models.example.test. The showrunner can allow it in Agent Console → Environments & Bridges, or you can switch back to the local model.', '', ['Cinematographer']],
  ]);
  assert.deepEqual(ui.readinessLines({...blocked, blockers: [{code: 'later_code', agentKey: 'x9', fix: 'later_fix'}]}, crew).map(l => [l.text, l.agents]),
    [['Something is blocking the crew (later_code). The showrunner can check Agent Console.', ['x9']]], 'a newer server code still reads plainly');
});

test('the banner sits above the roster with the lines, the command and one Check again button', () => {
  const html = banner({readiness: blocked});
  assert.match(html, /^<section class="crew-readiness" aria-label="Crew readiness"><header><strong>The crew can&#x27;t work yet<\/strong>/);
  assert.match(html, /<li>The background worker isn&#x27;t running\. Restart the studio without --no-worker\.<\/li>/);
  assert.match(html, /<li>qwen3\.8:27b isn&#x27;t installed in Ollama\. On the studio computer, run: <code>ollama pull qwen3\.8:27b<\/code><small>Affects: Showrunner and Cinematographer<\/small><\/li>/);
  assert.equal((html.match(/<li>/g) || []).length, 3);
  assert.deepEqual(buttons(html), ['Check again']);
  assert.match(banner({readiness: blocked, checking: true}), /<button type="button" disabled="">Checking…<\/button>/);
});

test('when everything is ready, or nothing is known yet, the banner is hidden', () => {
  assert.equal(banner({readiness: {...blocked, ready: true, blockers: []}}), '');
  assert.equal(banner({readiness: null}), '');
  const failed = banner({readiness: null, error: 'Connection lost'});
  assert.match(failed, /<p class="error" role="alert">Couldn&#x27;t check whether the crew is ready: Connection lost<\/p>/);
  assert.doesNotMatch(failed, /can&#x27;t work yet/, 'a failed check is not a claim that the crew is blocked');
  assert.deepEqual(buttons(failed), ['Check again']);
});

test('Traditional Chinese reads naturally and keeps the command and crew names', async () => {
  await ui.setLocale('zh-TW');
  try {
    const html = banner({readiness: blocked});
    assert.match(html, /劇組還不能開工/);
    assert.match(html, /背景程式沒有在跑：請不帶 --no-worker 重新啟動工作室。/);
    assert.match(html, /Ollama 裡還沒有 qwen3\.8:27b：請在工作室電腦上執行： <code>ollama pull qwen3\.8:27b<\/code><small>影響：製片總監和攝影指導<\/small>/);
    assert.deepEqual(buttons(html), ['再檢查一次']);
  } finally {
    await ui.setLocale('en');
  }
});

test('the roster labels an agent that needs setup and leaves offline workers offline', () => {
  const assistant = {slug: 'demo', board: {needs_you: [], working: [], done: [], idle: crew, counts: {}, cursor: null, ui: {drafts: {}, selected: null}},
    setBoardOpen() {}, reloadBoard: async () => null};
  const html = renderToStaticMarkup(React.createElement(ui.AgentBoard, {assistant, me: {can_write: true}, onOpenTarget() {}}));
  assert.match(html, /<strong>🧭 Showrunner<\/strong><small class="needs-setup">Needs setup · 0\/2<\/small>/);
  assert.match(html, /<strong>🔌 Render box<\/strong><small>Offline · 0\/1<\/small>/);
  assert.doesNotMatch(html, /crew-readiness/, 'readiness loads after mount; nothing is claimed before it arrives');
});
