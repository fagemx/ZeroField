// SPEC_20 R9/R12: failed model calls read as plain language, and a forbidden usage tier says how to fix it.
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
  temporary = await mkdtemp(join(root, 'tests/.provider-failures-'));
  const result = await build({stdin: {contents: "export {AgentBoard, readinessLines} from './src/assistant/AgentBoard.jsx'; export {providerFailureText, PROVIDER_FAILURES} from './src/assistant/providerFailures.js'; export {setLocale} from './src/i18n/index.js';",
    resolveDir: root, sourcefile: 'provider-failures.jsx', loader: 'jsx'}, bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', packages: 'external', loader: {'.css': 'empty'}});
  const output = join(temporary, 'components.mjs');
  await writeFile(output, result.outputFiles[0].text);
  ui = await import(pathToFileURL(output));
});
after(async () => {if (temporary) await rm(temporary, {recursive: true, force: true});});

test('every failure class has a plain line; anything else falls back to the stored text', async () => {
  assert.deepEqual(ui.PROVIDER_FAILURES, ['local', 'quota', 'auth', 'provider', 'timeout', 'empty', 'output', 'gpu_busy']);
  assert.equal(ui.providerFailureText('gpu_busy'), "The GPU is busy with a render, so the local model couldn't start. Try again shortly.");
  assert.equal(ui.providerFailureText('local'), "The local model isn't answering. Start Ollama (or the local model server) on the studio computer, then try again.");
  for (const kind of ui.PROVIDER_FAILURES) assert.ok(ui.providerFailureText(kind) && !ui.providerFailureText(kind).includes('providerFailures'), kind);
  assert.equal(ui.providerFailureText('unavailable'), '');
  assert.equal(ui.providerFailureText(undefined), '');
  await ui.setLocale('zh-TW');
  try {
    assert.equal(ui.providerFailureText('quota'), '模型服務的額度用完了，或暫時限制了這個工作室的用量：請稍等一下再試。');
  } finally {
    await ui.setLocale('en');
  }
});

test('a usage tier the production forbids names the switch that fixes it', () => {
  const lines = ui.readinessLines({ready: false, blockers: [
    {code: 'network_policy', agentKey: 'coordinator', fix: 'enable_hosted_open', host: 'openrouter.ai', model: 'qwen/qwen3.8-27b', tier: 'hosted_open'},
    {code: 'network_policy', agentKey: 'sheet_ops', fix: 'use_hybrid_policy', host: 'models.example.test', model: 'closed-model', tier: 'closed'},
  ]}, []);
  assert.deepEqual(lines.map(line => line.text), [
    'qwen/qwen3.8-27b runs on a hosted open-weights service (openrouter.ai), which is off for this production. The showrunner can turn on hosted open weights in Agent Console settings, or you can switch back to the local model.',
    'closed-model on models.example.test is a closed model, and this production allows open weights only. Switch back to the local model, or the showrunner can choose the hybrid production policy.',
  ]);
});

test('a failed task on the board shows its failure class in plain language', () => {
  const done = [{id: 'task:1', kind: 'task', title: 'Shot list', status: 'failed', failure: 'local', error: null, target: {}, created_at: '2026-10-27T00:00:00Z'}];
  const assistant = {slug: 'demo', board: {needs_you: [], working: [], done, idle: [], counts: {done: 1}, cursor: null, ui: {drafts: {}, selected: null}},
    setBoardOpen() {}, reloadBoard: async () => null};
  const html = renderToStaticMarkup(React.createElement(ui.AgentBoard, {assistant, me: {can_write: true}, onOpenTarget() {}}));
  assert.match(html, /<p class="error">The local model isn&#x27;t answering\. Start Ollama \(or the local model server\) on the studio computer, then try again\.<\/p>/);
});
