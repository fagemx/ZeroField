import test from 'node:test';
import assert from 'node:assert/strict';
import { startPolling } from '../src/polling.js';
import { reviewColumnLabel, reviewGroupLabel, reviewMedia } from '../src/assistant/reviewLabels.js';
import { allocationBlockerLabel } from '../src/storyModel.js';
import { setLocale } from '../src/i18n/index.js';
import en from '../src/i18n/locales/en.json' with {type:'json'};
import zh from '../src/i18n/locales/zh-TW.json' with {type:'json'};

// A clock the test drives by hand, plus a document that can be hidden and shown again.
function fakeEnv() {
  const listeners = {}, timers = new Map();
  let next = 1, now = 0;
  const env = {
    setTimeout: (fn, ms) => { const id = next++; timers.set(id, {fn, at: now + ms}); return id; },
    clearTimeout: id => { timers.delete(id); },
    addEventListener: (type, fn) => { (listeners[type] ||= new Set()).add(fn); },
    removeEventListener: (type, fn) => { listeners[type]?.delete(fn); },
    document: {visibilityState: 'visible',
      addEventListener: (type, fn) => { (listeners['doc:' + type] ||= new Set()).add(fn); },
      removeEventListener: (type, fn) => { listeners['doc:' + type]?.delete(fn); }},
  };
  const settle = () => new Promise(resolve => setImmediate(resolve));
  return {env, listeners, timers,
    pending: () => [...timers.values()].map(timer => timer.at - now),
    async advance(ms) { // run every timer due within ms, one at a time, letting async loads settle
      const end = now + ms;
      for (;;) {
        const due = [...timers.entries()].filter(([, timer]) => timer.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        now = due[1].at; timers.delete(due[0]); due[1].fn(); await settle();
      }
      now = end;
    }};
}

test('polling goes on after a failed load, backs off, and returns to the normal pace on success', async () => {
  const clock = fakeEnv();
  const outcomes = [true, false, false, true, true];
  let calls = 0;
  const stop = startPolling(async () => { const ok = outcomes[calls++]; if (!ok) throw new Error('Connection lost'); },
    3000, {env: clock.env, maxDelay: 30000});
  assert.deepEqual(clock.pending(), [3000]);
  await clock.advance(3000);                       // ok -> normal pace
  assert.equal(calls, 1); assert.deepEqual(clock.pending(), [3000]);
  await clock.advance(3000);                       // failure 1 -> 6 s
  assert.equal(calls, 2); assert.deepEqual(clock.pending(), [6000]);
  await clock.advance(6000);                       // failure 2 -> 12 s
  assert.equal(calls, 3); assert.deepEqual(clock.pending(), [12000]);
  await clock.advance(12000);                      // success again -> 3 s
  assert.equal(calls, 4); assert.deepEqual(clock.pending(), [3000]);
  stop();
  assert.deepEqual(clock.pending(), []);
  await clock.advance(60000);
  assert.equal(calls, 4);
});

test('the backoff is capped and a hidden page waits until it is shown again', async () => {
  const clock = fakeEnv();
  let calls = 0;
  const stop = startPolling(async () => { calls++; throw new Error('down'); }, 3000, {env: clock.env, maxDelay: 10000});
  await clock.advance(3000); await clock.advance(6000); await clock.advance(10000);
  assert.deepEqual(clock.pending(), [10000]);
  assert.equal(calls, 3);
  clock.env.document.visibilityState = 'hidden';
  for (const fn of clock.listeners['doc:visibilitychange']) fn();
  await clock.advance(0);
  assert.equal(calls, 3);                          // hidden: no extra load
  clock.env.document.visibilityState = 'visible';
  for (const fn of clock.listeners['doc:visibilitychange']) fn();
  await clock.advance(0);
  assert.equal(calls, 4);                          // visible again: loads at once, loop still armed
  assert.equal(clock.pending().length, 1);
  stop();
  assert.equal(clock.listeners['doc:visibilitychange'].size, 0);
  assert.equal(clock.listeners.online.size, 0);
});

test('proposal review wording comes from the locale and the zh-TW text is unchanged', async () => {
  const group = {kind: 'row', row_number: 3, context: 'Lena runs', label: 'Row 3 · Lena runs'};
  const nameless = {kind: 'row', row_number: 2, context: '', label: 'Row 2 · New data'};
  const structure = {kind: 'structure', row_number: null, context: '', label: 'Structural change'};
  const cjk = /[一-鿿]/;
  await setLocale('en');
  assert.equal(reviewGroupLabel(group), 'Row 3 · Lena runs');
  assert.equal(reviewGroupLabel(nameless), 'Row 2 · New data');
  assert.equal(reviewGroupLabel(structure), 'Structural change');
  assert.equal(reviewColumnLabel({column: 'Column 4', column_kind: 'index', column_index: 3}), 'Column 4');
  assert.equal(reviewColumnLabel({column: 'Document / structure', column_kind: 'structure'}), 'Document / structure');
  assert.equal(reviewColumnLabel({column: 'Shot', column_kind: 'header'}), 'Shot');
  assert.deepEqual(reviewMedia('![image](/projects/api/x/assets/pa_0123456789abcdef0123456789abcdef)'),
    {kind: 'image', url: '/projects/api/x/assets/pa_0123456789abcdef0123456789abcdef', label: 'Image'});
  assert.equal(reviewMedia('plain text'), null);
  for (const text of [reviewGroupLabel(group), reviewGroupLabel(nameless), reviewGroupLabel(structure), reviewMedia('![image](/projects/api/x/assets/pa_0123456789abcdef0123456789abcdef)').label,
    allocationBlockerLabel('models_not_installed:h3-short-video-v3:a.safetensors, b.safetensors')]) assert.ok(!cjk.test(text), text);
  assert.equal(allocationBlockerLabel('models_not_installed:h3-short-video-v3:a.safetensors, b.safetensors'),
    "This card's model files are not installed on the local ComfyUI: a.safetensors, b.safetensors.");
  await setLocale('zh-TW');
  assert.equal(reviewGroupLabel(group), '第 3 列 · Lena runs');
  assert.equal(reviewGroupLabel(nameless), '第 2 列 · 新增資料');
  assert.equal(reviewGroupLabel(structure), '結構修改');
  assert.equal(reviewColumnLabel({column_kind: 'index', column_index: 3}), '欄 4');
  assert.equal(reviewColumnLabel({column_kind: 'structure'}), '文件／結構');
  assert.equal(reviewGroupLabel({label: '第 1 列 · 舊資料'}), '第 1 列 · 舊資料'); // reviews saved before `kind` keep their text
  await setLocale('en');
});

test('the strings that used to come from the server in Chinese now live in both locale files', () => {
  const keys = [['agentBoard', 'changesToReview'], ['flowPanels', 'effectsSingleStep'], ['flowPanels', 'effectsWorkflow'], ['flowPanels', 'keepResultNoWriteBack'],
    ['tableProposalReview', 'rowNumber'], ['tableProposalReview', 'newData'], ['tableProposalReview', 'structureChange'], ['tableProposalReview', 'documentStructure'],
    ['tableProposalReview', 'columnNumber'], ['tableProposalReview', 'imageCell'], ['allocation', 'blockerModelsMissing'], ['sheetWorkspace', 'episodeLoadFailed'],
    ['errors', 'saveAValidPipelineFirst'], ['errors', 'createAndSaveAValidPipelineFirst']];
  const cjk = /[一-鿿]/;
  for (const [group, key] of keys) {
    assert.ok(en[group][key], `en ${group}.${key}`);
    assert.ok(zh[group][key], `zh-TW ${group}.${key}`);
    assert.ok(!cjk.test(en[group][key]), `English ${group}.${key} has CJK text`);
    assert.ok(cjk.test(zh[group][key]), `zh-TW ${group}.${key} is not Chinese`);
  }
});
