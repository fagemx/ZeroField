import test from 'node:test';
import assert from 'node:assert/strict';
import { MAX_START_TEXT, acknowledgeStart, peekStart, rememberStart, slugOfEpisode, startPlan, storyProductionRequest, takeStart, titleFrom } from '../src/startModel.js';

const withStorage = (storage, run) => {
  const before = Object.getOwnPropertyDescriptor(globalThis, 'sessionStorage');
  Object.defineProperty(globalThis, 'sessionStorage', {value: storage, configurable: true, writable: true});
  try { return run(); } finally { before ? Object.defineProperty(globalThis, 'sessionStorage', before) : delete globalThis.sessionStorage; }
};
const fakeStorage = (seed = {}) => {
  const data = {...seed};
  return {data, getItem: key => key in data ? data[key] : null, setItem: (key, value) => {data[key] = String(value);}, removeItem: key => {delete data[key];}};
};

test('an unnamed production is named after the first line written, without its markup, cut at 40 characters', () => {
  assert.equal(titleFrom('A lone astronomer discovers a countdown and reaches for a brass dial.'), 'A lone astronomer discovers a countdown');
  assert.equal(titleFrom('\n\n# The Last Signal\nINT. OBSERVATORY - NIGHT'), 'The Last Signal');
  assert.equal(titleFrom('> - *Quiet*'), 'Quiet');
  assert.equal(titleFrom('一個孤獨的天文學家發現倒數計時，伸手去握黃銅轉盤，這時外面的雨停了，燈亮了起來，所有人都在等'), '一個孤獨的天文學家發現倒數計時，伸手去握黃銅轉盤，這時外面的雨停了，燈亮了起來，');
  assert.equal(Array.from(titleFrom('一個孤獨的天文學家發現倒數計時，伸手去握黃銅轉盤，這時外面的雨停了，燈亮了起來，所有人都在等')).length, 40, 'forty characters, counting each one once');
  assert.equal(titleFrom('   \n  ', 'Untitled story'), 'Untitled story', 'nothing written, the fallback');
  assert.equal(titleFrom(undefined), '');
});

test('what to hand over needs a known mode and some text, trims it, and falls back to a known ratio', () => {
  assert.deepEqual(startPlan({mode: 'idea', text: '  A countdown.  \n', ratio: '9:16', style: '88124'}), {ok: true, start: {mode: 'idea', text: 'A countdown.', ratio: '9:16', style: '88124'}});
  assert.equal(startPlan({mode: 'script', text: 'x', ratio: '4:3'}).start.ratio, '16:9', 'a ratio nobody offers becomes the first one');
  assert.equal(startPlan({mode: 'novel', text: 'x'}).start.style, '', 'no style chosen is said as empty, so the episode keeps its own');
  assert.deepEqual(startPlan({mode: 'idea', text: ' \n '}), {ok: false, reason: 'empty'});
  assert.deepEqual(startPlan({mode: 'video', text: 'x'}), {ok: false, reason: 'mode'});
  assert.deepEqual(startPlan({mode: 'script', text: 'x'.repeat(MAX_START_TEXT + 1)}), {ok: false, reason: 'long'});
  assert.equal(startPlan({mode: 'script', text: 'x'.repeat(MAX_START_TEXT)}).ok, true, 'exactly the limit is allowed');
});

test('the production an episode belongs to is read from its id', () => {
  assert.equal(slugOfEpisode('ep_project-1a2b3c4d_01'), 'project-1a2b3c4d');
  assert.equal(slugOfEpisode('ep_zerofield-showcase_12'), 'zerofield-showcase');
  for (const bad of ['', null, undefined, 'ep__01', 'project-1', 'ep_UPPER_01', 'ep_a_b']) assert.equal(slugOfEpisode(bad), '', String(bad));
});

test('the text a production was started with is handed over once, to that production only', () => {
  const storage = fakeStorage();
  withStorage(storage, () => {
    const start = {mode: 'idea', text: 'A countdown.', ratio: '16:9', style: ''};
    assert.equal(rememberStart('project-aaaa1111', start), true);
    assert.ok(storage.data['zf.start:project-aaaa1111'], 'it waits in this tab for the next page load');
    assert.equal(takeStart('ep_project-bbbb2222_01'), null, 'another production finds nothing');
    assert.ok(start.handoffId, 'remembering adds the stable retry identity to the caller’s start');
    assert.deepEqual(takeStart('ep_project-aaaa1111_01'), start);
    assert.equal(takeStart('ep_project-aaaa1111_01'), null, 'and only once');
    assert.deepEqual(storage.data, {}, 'nothing is left behind');
  });
});

test('peek is non-destructive; only the matching server-saved and loaded start can be acknowledged', () => {
  const storage = fakeStorage(), epId = 'ep_peek-11223344_01';
  withStorage(storage, () => {
    const start = {mode:'idea', text:'Keep until saved.'};
    rememberStart('peek-11223344', start);
    const first = peekStart(epId);
    assert.deepEqual(peekStart(epId), first, 'retry sees the same text and retry identity');
    first.handoff = {stage:'done', ref:{kind:'source',mode:'idea'}};
    rememberStart('peek-11223344', first);
    assert.equal(acknowledgeStart(epId, start), true, 'checkpoint changes do not turn this into a new start');
    assert.equal(peekStart(epId), null);
    assert.deepEqual(storage.data, {});
  });
});

test('compare-and-delete rejects another production, a replacement with identical text, and changed text under the same identity', () => {
  const storage = fakeStorage(), epId = 'ep_newer-11223344_01';
  withStorage(storage, () => {
    const old = {mode:'script',text:'Same words.'};
    rememberStart('newer-11223344', old);
    const newer = {mode:'script',text:'Same words.'};
    rememberStart('newer-11223344', newer);
    assert.notEqual(old.handoffId, newer.handoffId);
    assert.equal(acknowledgeStart(epId, old), false);
    assert.equal(acknowledgeStart('ep_other-11223344_01', newer), false);
    assert.equal(peekStart(epId).handoffId, newer.handoffId);
    rememberStart('newer-11223344', {...newer, text:'Revised words.'});
    assert.equal(acknowledgeStart(epId, newer), false, 'identity alone never authorizes deleting changed input');
    assert.equal(peekStart(epId).text, 'Revised words.');
    acknowledgeStart(epId, peekStart(epId));
  });
});

test('read-only storage does not keep minting new retry identities for an old pending start', () => {
  const storage = fakeStorage({'zf.start:readonly-11223344':JSON.stringify({mode:'idea',text:'Keep this.'})});
  storage.setItem = () => {throw new Error('Read only');};
  withStorage(storage, () => {
    const first = peekStart('ep_readonly-11223344_01');
    assert.equal(peekStart('ep_readonly-11223344_01').handoffId, first.handoffId);
    assert.equal(rememberStart('readonly-11223344', first), false, 'caller must refuse server mutations without a durable checkpoint');
  });
});

test('failed durable deletion leaves the matching pending start available rather than claiming acknowledgement', () => {
  const storage = fakeStorage(), epId = 'ep_delete-11223344_01';
  withStorage(storage, () => {
    const start = {mode:'novel',text:'Do not lose this.'};rememberStart('delete-11223344', start);
    const remove = storage.removeItem;storage.removeItem = () => {throw new Error('Read only');};
    assert.equal(acknowledgeStart(epId, start), false);
    assert.equal(peekStart(epId).handoffId, start.handoffId);
    storage.removeItem = remove;
    assert.equal(acknowledgeStart(epId, start), true);
  });
});

test('after a page load the hand-off comes from storage alone', () => {
  const saved = {'zf.start:project-cccc3333': JSON.stringify({mode: 'script', text: 'INT. ROOM', ratio: '21:9', style: '88125'})};
  const storage = fakeStorage(saved);
  withStorage(storage, () => {
    const first = peekStart('ep_project-cccc3333_01');
    assert.ok(first.handoffId, 'legacy pending text receives an identity before server mutations');
    assert.equal(JSON.parse(storage.data['zf.start:project-cccc3333']).handoffId, first.handoffId, 'migration is persisted across reload');
    assert.deepEqual(takeStart('ep_project-cccc3333_01'), first);
  });
});

test('without storage the hand-off survives inside one page load, and broken or unusable saves are ignored', () => {
  withStorage(undefined, () => {
    assert.equal(rememberStart('project-dddd4444', {mode: 'novel', text: 'Chapter one.', ratio: '16:9', style: ''}), false, 'memory fallback does not claim durable storage');
    assert.equal(takeStart('ep_project-dddd4444_01').text, 'Chapter one.');
    assert.equal(takeStart('ep_project-dddd4444_01'), null);
  });
  const throwing = {getItem() {throw new Error('blocked');}, setItem() {throw new Error('blocked');}, removeItem() {throw new Error('blocked');}};
  withStorage(throwing, () => {
    assert.equal(rememberStart('project-eeee5555', {mode: 'idea', text: 'Rain.', ratio: '16:9', style: ''}), false);
    assert.equal(takeStart('ep_project-eeee5555_01').text, 'Rain.', 'a blocked storage falls back to memory');
  });
  for (const junk of ['not json', JSON.stringify({mode: 'video', text: 'x'}), JSON.stringify({mode: 'idea', text: '  '}), 'null', JSON.stringify(['idea'])]) {
    withStorage(fakeStorage({'zf.start:project-ffff6666': junk}), () => assert.equal(takeStart('ep_project-ffff6666_01'), null, junk));
  }
});

test('a story start asks for the studio template without its sample content (R44-1, R44-2)', () => {
  assert.deepEqual(storyProductionRequest('Spillway', 'project-0a1b2c3d'),
    {slug: 'project-0a1b2c3d', title: 'Spillway', template: 'zerofield_studio', status: 'planning', summary: '', samples: false});
  assert.match(storyProductionRequest('Spillway').slug, /^project-[0-9a-f]{8}$/);
});
