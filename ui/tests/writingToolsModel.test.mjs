import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {frozenRequest, toolsErrorKey, retryable, serverFlush, previewUsable, safeFilename, downloadBlob} from '../src/writing/writingToolsModel.js';

test('network retries preserve exact body and idempotency identity; errors never force retry', async () => {
  const calls = [];
  const body = {selection: {actionIds: ['a']}};
  const request = frozenRequest(async (...args) => {calls.push(args); return {ok: true};}, 'previews/p/apply', 'POST', body);
  body.selection.actionIds.push('not-frozen');
  await request(); await request();
  assert.deepEqual(calls[0], calls[1]);
  assert.deepEqual(calls[0][2], {selection: {actionIds: ['a']}});
  assert.ok(calls[0][3].idempotencyKey);
  for (const status of [401,403,409,422]) assert.equal(retryable({status}), false);
  assert.equal(toolsErrorKey({status: 409, code: 'DRAMA_WRITING_PREVIEW_STALE'}), 'stale');
  assert.equal(toolsErrorKey({status: 409, data: {code: 'DRAMA_WRITING_LOCKED'}}), 'locked');
});

test('server flush rejects device-only recovery and preview checks expiry/stale status', async () => {
  let options;
  await serverFlush(async value => {options = value; return true;});
  assert.deepEqual(options, {requireServer: true});
  await assert.rejects(serverFlush(async () => false), {code: 'WRITING_FLUSH_REQUIRED'});
  await assert.rejects(serverFlush(undefined), {code: 'WRITING_FLUSH_REQUIRED'});
  const p = {previewId: 'p', status: 'pending', expiresAt: '2030-01-01T00:00:00Z'};
  assert.equal(previewUsable(p, 0), true);
  assert.equal(previewUsable({...p, expiresAt: 2}, 1000), true);
  assert.equal(previewUsable({...p, expiresAt: 2}, 3000), false);
  assert.equal(previewUsable({...p, stale: true}, 0), false);
  assert.equal(previewUsable({...p, status: 'applied'}, 0), false);
  assert.equal(previewUsable(p, Date.parse('2031-01-01')), false);
});

test('an aborted tool instance cannot send a late mutation after identity/navigation changes', async () => {
  let sent = false;
  const controller = new AbortController();
  const request = frozenRequest(async () => {sent = true;}, 'exports', 'POST', {sourceRef:{kind:'working'}});
  controller.abort();
  assert.throws(() => request(controller.signal), {name:'AbortError'});
  assert.equal(sent, false);
});

test('download uses a private blob, sanitized filename, and releases its URL', async () => {
  const events = [];
  const a = {click(){events.push('clicked');}, remove(){events.push('removed');}};
  downloadBlob(new Blob(['稿件']), '../secret\\story\u0000.txt', {createElement(){return a;}, body:{appendChild(){events.push('added');}}},
    {createObjectURL(){return 'blob:private';}, revokeObjectURL(url){events.push(url);}});
  assert.equal(a.download, 'story.txt');
  assert.equal(a.href, 'blob:private');
  assert.deepEqual(events, ['added','clicked','removed']);
  await new Promise(resolve => setTimeout(resolve, 1050));
  assert.equal(events.at(-1), 'blob:private');
  assert.equal(safeFilename('../../'), 'manuscript.txt');
});

test('locale fragments have identical semantic leaves and interpolation parameters', async () => {
  const en = JSON.parse(await readFile(new URL('../src/writing/locales/tools.en.json', import.meta.url)));
  const zh = JSON.parse(await readFile(new URL('../src/writing/locales/tools.zh-TW.json', import.meta.url)));
  assert.deepEqual(Object.keys(en).sort(), Object.keys(zh).sort());
  for (const key of Object.keys(en)) {
    assert.ok(en[key] && zh[key]);
    assert.deepEqual(en[key].match(/{{\w+}}/g), zh[key].match(/{{\w+}}/g), key);
  }
});
