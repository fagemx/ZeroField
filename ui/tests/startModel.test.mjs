import test from 'node:test';
import assert from 'node:assert/strict';
import { MAX_START_TEXT, rememberStart, slugOfEpisode, startPlan, takeStart, titleFrom } from '../src/startModel.js';

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
    rememberStart('project-aaaa1111', {mode: 'idea', text: 'A countdown.', ratio: '16:9', style: ''});
    assert.ok(storage.data['zf.start:project-aaaa1111'], 'it waits in this tab for the next page load');
    assert.equal(takeStart('ep_project-bbbb2222_01'), null, 'another production finds nothing');
    assert.deepEqual(takeStart('ep_project-aaaa1111_01'), {mode: 'idea', text: 'A countdown.', ratio: '16:9', style: ''});
    assert.equal(takeStart('ep_project-aaaa1111_01'), null, 'and only once');
    assert.deepEqual(storage.data, {}, 'nothing is left behind');
  });
});

test('after a page load the hand-off comes from storage alone', () => {
  const saved = {'zf.start:project-cccc3333': JSON.stringify({mode: 'script', text: 'INT. ROOM', ratio: '21:9', style: '88125'})};
  withStorage(fakeStorage(saved), () => assert.deepEqual(takeStart('ep_project-cccc3333_01'), {mode: 'script', text: 'INT. ROOM', ratio: '21:9', style: '88125'}));
});

test('without storage the hand-off survives inside one page load, and broken or unusable saves are ignored', () => {
  withStorage(undefined, () => {
    rememberStart('project-dddd4444', {mode: 'novel', text: 'Chapter one.', ratio: '16:9', style: ''});
    assert.equal(takeStart('ep_project-dddd4444_01').text, 'Chapter one.');
    assert.equal(takeStart('ep_project-dddd4444_01'), null);
  });
  const throwing = {getItem() {throw new Error('blocked');}, setItem() {throw new Error('blocked');}, removeItem() {throw new Error('blocked');}};
  withStorage(throwing, () => {
    rememberStart('project-eeee5555', {mode: 'idea', text: 'Rain.', ratio: '16:9', style: ''});
    assert.equal(takeStart('ep_project-eeee5555_01').text, 'Rain.', 'a blocked storage falls back to memory');
  });
  for (const junk of ['not json', JSON.stringify({mode: 'video', text: 'x'}), JSON.stringify({mode: 'idea', text: '  '}), 'null', JSON.stringify(['idea'])]) {
    withStorage(fakeStorage({'zf.start:project-ffff6666': junk}), () => assert.equal(takeStart('ep_project-ffff6666_01'), null, junk));
  }
});
