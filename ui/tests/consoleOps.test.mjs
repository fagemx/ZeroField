import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { setLocale, t } from '../src/i18n/index.js';
import { GROUPS, PAGES } from '../src/agentConsole/model.js';
import { CONTEXT_COMMAND, HEALTH_STEPS, QUEUE_GROUPS, gib, gpuShare, offPreset, pauseLine, providerLine, queueLine, queueTotals,
  remainingSteps, stepText, turnReason, validCost, vram } from '../src/agentConsole/opsModel.js';

test('operations stay inside the existing pages: still four groups and twelve pages', async () => {
  assert.equal(PAGES.length, 12);
  assert.deepEqual(Object.keys(GROUPS), ['workspace', 'build', 'managed_agents', 'analytics']);
  const app = await readFile(new URL('../src/agentConsole/AgentConsoleApp.jsx', import.meta.url), 'utf8');
  const managed = await readFile(new URL('../src/agentConsole/ConsoleManagedViews.jsx', import.meta.url), 'utf8');
  assert.match(app, /<PausedBanner\/>/, 'the paused banner shows on every Console page');
  assert.match(app, /<AutomationSwitch\/><GpuPanel\/><\/div><QueuePanel\/>/, 'Dashboard carries the switch, GPU panel and queue');
  assert.match(managed, /<ModelSetup\/>/, 'Providers & API Keys carries model setup');
});

test('the health check runs in order and stops repeating a failure the user already has to fix', () => {
  assert.deepEqual(HEALTH_STEPS, ['model', 'chat', 'tools', 'json', 'vision', 'context']);
  assert.deepEqual(remainingSteps({ step: 'model', status: 'pass' }), ['chat', 'tools', 'json', 'vision', 'context']);
  assert.deepEqual(remainingSteps({ step: 'model', status: 'warn', code: 'list_unavailable' }), ['chat', 'tools', 'json', 'vision', 'context']);
  assert.deepEqual(remainingSteps({ step: 'model', status: 'fail', code: 'unreachable' }), [], 'nothing answers: nothing else to try');
  assert.deepEqual(remainingSteps({ step: 'model', status: 'fail', code: 'model_missing' }), ['context'], 'the server still reports context');
  assert.deepEqual(remainingSteps({ step: 'chat', status: 'fail', code: 'governance' }), []);
  assert.deepEqual(remainingSteps({ step: 'chat', status: 'fail', code: 'timeout' }), ['context']);
  // A capability failure does not stop the other capabilities from being tried.
  assert.deepEqual(remainingSteps({ step: 'tools', status: 'fail', code: 'no_tool_call' }), ['json', 'vision', 'context']);
  assert.deepEqual(remainingSteps({ step: 'vision', status: 'fail', code: 'rejected' }), ['context']);
  assert.deepEqual(remainingSteps({ step: 'context', status: 'warn', code: 'context_4096' }), []);
});

test('each step result reads as what happened plus the fix, with a command where one helps', async () => {
  await setLocale('en');
  const missing = stepText({ step: 'model', status: 'fail', code: 'model_missing', fix: 'ollama_pull', detail: { model: 'qwen3.8:27b', host: '127.0.0.1', port: 11434 } });
  assert.equal(missing.summary, 'qwen3.8:27b is not installed on the model server.');
  assert.match(missing.fix, /^Pull the model/);
  assert.equal(missing.command, 'ollama pull qwen3.8:27b');
  const context = stepText({ step: 'context', status: 'warn', code: 'context_4096', fix: 'ollama_context_length', detail: { contextLength: 4096 } });
  assert.match(context.summary, /only 4096 tokens/);
  assert.equal(context.command, CONTEXT_COMMAND);
  assert.match(CONTEXT_COMMAND, /OLLAMA_CONTEXT_LENGTH=16384/);
  const down = stepText({ status: 'fail', code: 'unreachable', fix: 'start_ollama', detail: { host: '127.0.0.1', port: 11434 } });
  assert.equal(down.summary, 'Nothing answered at 127.0.0.1:11434.');
  assert.equal(down.command, '');
  const future = stepText({ status: 'fail', code: 'brand_new_code', fix: 'brand_new_fix', detail: {} });
  assert.equal(future.summary, 'The check ended with brand_new_code.');
  assert.equal(future.fix, 'See the message below.');
  await setLocale('zh-TW');
  assert.equal(stepText({ status: 'pass', code: 'replied' }).summary, '模型有回覆。');
  assert.equal(stepText({ status: 'fail', code: 'model_missing', fix: 'ollama_pull', detail: { model: 'qwen3.8:27b' } }).summary, '模型伺服器上沒有 qwen3.8:27b。');
  await setLocale('en');
});

test('every code, fix, failure kind and state the server can send has words in both languages', async () => {
  const codes = ['model_present', 'list_unavailable', 'unreachable', 'not_model_server', 'model_missing', 'auth', 'governance', 'kind_removed',
    'unsupported_kind', 'auth_missing', 'replied', 'empty_reply', 'tool_called', 'no_tool_call', 'tool_arguments', 'json_valid', 'json_invalid',
    'image_described', 'vision_wrong', 'rejected', 'timeout', 'quota', 'model_error', 'context_ok', 'context_4096', 'context_small',
    'context_server_default', 'context_remote', 'context_unknown_server'];
  const fixes = ['start_ollama', 'start_model_server', 'check_endpoint', 'ollama_pull', 'load_model', 'set_api_key', 'allow_host', 'review_agent',
    'reconfigure_provider', 'use_builtin_provider', 'configure_provider', 'tool_model', 'json_model', 'vision_model', 'retry_when_idle',
    'wait_or_raise_quota', 'ollama_context_length', 'server_context'];
  for (const locale of ['en', 'zh-TW']) {
    await setLocale(locale);
    for (const code of codes) assert.notEqual(t('console.ops.check.code.' + code), 'console.ops.check.code.' + code, code);
    for (const fix of fixes) assert.notEqual(t('console.ops.check.fix.' + fix), 'console.ops.check.fix.' + fix, fix);
    for (const step of HEALTH_STEPS) for (const prefix of ['step', 'about']) assert.notEqual(t(`console.ops.check.${prefix}.${step}`), `console.ops.check.${prefix}.${step}`);
    for (const status of ['pending', 'running', 'pass', 'warn', 'fail', 'skip', 'skipped']) assert.notEqual(t('console.ops.check.status.' + status), 'console.ops.check.status.' + status);
    for (const group of QUEUE_GROUPS) assert.notEqual(t('console.ops.queue.group.' + group), 'console.ops.queue.group.' + group);
    for (const state of ['queued', 'running', 'awaiting_gate', 'waiting_gpu', 'grading', 'failed', 'timeout']) assert.notEqual(t('console.ops.queue.state.' + state), 'console.ops.queue.state.' + state);
    for (const state of ['down', 'bad', 'not_local']) assert.notEqual(t('console.ops.gpu.comfy.' + state), 'console.ops.gpu.comfy.' + state);
  }
  await setLocale('en');
});

test('queue lines speak plainly, keep other members private and keep failure classes from newer servers', async () => {
  await setLocale('en');
  assert.equal(turnReason({ errorKind: 'timeout' }), 'The model took too long to answer. Try again, or ask for something smaller.', 'an R12 failure class reads as its providerFailures line');
  assert.equal(turnReason({ errorKind: 'crash' }), 'The worker stopped unexpectedly during this turn.');
  assert.equal(turnReason({ errorKind: 'provider_overloaded' }), 'Failed (provider_overloaded).');
  const mine = queueLine('turns', { status: 'failed', errorKind: 'admission', detail: 'Agent concurrency limit reached.', agentKey: 'coordinator', mine: true, finishedAt: '2026-10-27T10:00:00Z' });
  assert.deepEqual([mine.who, mine.state, mine.reason, mine.detail, mine.mine], ['coordinator', 'Failed', 'Governance refused the call before it was sent.', 'Agent concurrency limit reached.', true]);
  const theirs = queueLine('dispatches', { status: 'running', agentKey: 'sheet_ops', error: null, mine: false, createdAt: '2026-10-27T10:00:00Z' });
  assert.deepEqual([theirs.who, theirs.state, theirs.reason, theirs.detail], ['sheet_ops', 'Running', '', '']);
  assert.equal(queueLine('tasks', { status: 'failed', nodeId: 'render', tabKey: 'cinema-studio', error: 'ComfyUI rejected the workflow' }).who, 'render on cinema-studio');
  assert.equal(queueLine('grades', { status: 'waiting_gpu', auto: true, shotId: 'sh_1' }).state, 'Waiting for the GPU');
  assert.equal(queueLine('grades', { status: 'failed', auto: false, shotId: 'sh_1', error: 'The vision model did not answer.' }).who, 'Grade of sh_1');
  assert.deepEqual(queueTotals({ counts: { turns: { active: 1, failed: 2 }, dispatches: { active: 1, failed: 0 }, tasks: { active: 0, failed: 1 }, grades: { active: 2, failed: 0 } } }), { active: 4, failed: 3 });
  assert.deepEqual(queueTotals(null), { active: 0, failed: 0 });
});

test('reconcile amounts match what the server accepts', () => {
  for (const ok of ['0', '0.0123', '12', ' 1.5 ', '999999.9999']) assert.ok(validCost(ok), ok);
  for (const bad of ['', '-1', '0.00001', '1e3', 'abc', '1,5', '1234567', null, undefined]) assert.equal(validCost(bad), false, String(bad));
});

test('GPU figures stay honest: unknown memory is not zero', () => {
  assert.deepEqual(vram({ vramTotal: 24 * 1024 ** 3, vramFree: 6 * 1024 ** 3 }), { free: '6.0', total: '24.0', used: '18.0', share: 0.75 });
  assert.equal(vram({ vramTotal: null, vramFree: 1 }), null);
  assert.equal(vram({ vramTotal: 0, vramFree: 0 }), null);
  assert.equal(gib(null), '—');
  assert.equal(gpuShare({ gpuShare: 0.873 }), 87);
  assert.equal(gpuShare({ gpuShare: null }), null);
});

test('the pause line names who paused, when and why; running automation has no line', async () => {
  await setLocale('en');
  assert.equal(pauseLine({ paused: false }), '');
  assert.equal(pauseLine(null), '');
  const line = pauseLine({ paused: true, byName: 'Maya Lin', at: '2026-10-27T10:00:00Z', reason: 'Demo render' });
  assert.match(line, /^Paused by Maya Lin on .+: Demo render$/);
  assert.match(pauseLine({ paused: true, byName: null, at: 'not a date', reason: '' }), /^Paused by a showrunner on \.$/);
  await setLocale('zh-TW');
  assert.match(pauseLine({ paused: true, byName: 'Maya Lin', at: '2026-10-27T10:00:00Z', reason: '' }), /^Maya Lin 於 .+ 暫停。$/);
  await setLocale('en');
});

test('setup marks crew members off the local preset and shows hosted endpoints by host only', async () => {
  await setLocale('en');
  const setup = { agents: [{ agentKey: 'coordinator', matchesPreset: true }, { agentKey: 'sheet_ops', matchesPreset: false }] };
  assert.deepEqual(offPreset(setup).map(a => a.agentKey), ['sheet_ops']);
  assert.deepEqual(offPreset(null), []);
  assert.equal(providerLine({ local: true, model: 'qwen3.8:27b', baseUrl: 'http://127.0.0.1:11434/v1' }), 'qwen3.8:27b at http://127.0.0.1:11434/v1');
  assert.equal(providerLine({ local: false, model: 'qwen/qwen3.8-27b', host: 'openrouter.ai', baseUrl: null }), 'qwen/qwen3.8-27b on openrouter.ai (hosted)');
  assert.equal(providerLine(null), 'These model settings cannot be used.');
});
