import test from 'node:test';
import assert from 'node:assert/strict';
import {takeRefTokens, refKey, shotForCode, resolveTakeRefs, edgeSeconds, defaultUse, refUse, takeRefUses, chooseUse, previousShot,
  prependTakeRef, insertTakeRef, refThumb, takeRefTag} from '../src/takeRefs.js';

// SPEC_19 R15 / D1, D11: @SC01-S02.end quotes another shot's take; the editor reads tags the way the server does.
const keys = text => takeRefTokens(text).map(token => token.key);

test('a take reference names a real shot code with .start or .end, and never an asset code', () => {
  assert.deepEqual(keys('Continue @SC01-S02.end, then @S03.start.'), ['SC01-S02.end', 'S03.start']);
  assert.deepEqual(keys('@sc01-s02.END'), [], 'the edge is lowercase, as the server writes it');
  assert.deepEqual(keys('@sc01-s02.end'), ['SC01-S02.end'], 'the code is upper-cased for the takeRefUses key');
  assert.deepEqual(keys('接續@SC01-S02.end的動作'), ['SC01-S02.end'], 'CJK text before and after is not a word character');
  for (const text of ['@CAST-01.end', '@CAST-01:night', '@CAST-01#night', '@SET-01', '@set-02.start', '@LOC-1.end', '@PROP-03.end', '@CHAR-01.end', '@scene-02.start', '@STYLE-01.start'])
    assert.deepEqual(keys(text), [], text + ' is an asset code');
  for (const text of ['x@S02.end', 'mail@SC01-S02.end', '#@S02.end', ':@S02.end', '-@S02.end', '@@S02.end', '@S02.ending', '@S02.end_', '@S02-.end', '@-S02.end', '@S02'])
    assert.deepEqual(keys(text), [], text + ' is not a tag');
  assert.deepEqual(keys('(@S02.end)'), ['S02.end']);
  assert.deepEqual(keys('@S02.end.'), ['S02.end'], 'a full stop after the edge ends the tag');
  const [token] = takeRefTokens('Then @SC01-S02.end turns');
  assert.deepEqual(token, {start: 5, end: 18, code: 'SC01-S02', edge: 'end', key: 'SC01-S02.end', text: '@SC01-S02.end'});
  assert.equal(refKey(' sc01-s02 ', 'start'), 'SC01-S02.start');
  assert.equal(takeRefTag('SC01-S02'), '@SC01-S02.end');
});

const shot = (index, extra = {}) => ({shotId: 'sh_demo_' + index, rowId: 'r' + index, shotIndex: index, sceneId: 'sc1', reviewStatus: 'Queued',
  selectedVideoUrl: null, selectedImageUrl: null, trim: {in: 0, out: null}, ...extra});

test('a tag resolves to one shot of the episode, case-insensitively, and says what it can quote', () => {
  const shots = [shot('SC01-S01', {reviewStatus: 'Approved', selectedVideoUrl: '/t/1.mp4', trim: {in: 0.4, out: 3.8}}), shot('SC01-S02', {selectedVideoUrl: '/t/2.mp4'}),
    shot('SC01-S03'), shot('SC01-S04'), shot('dup'), shot('DUP'), shot('SC01-S05', {reviewStatus: '已完成', selectedVideoUrl: '/t/5.mp4'})];
  assert.equal(shotForCode('sc01-s01', shots).shot.shotId, 'sh_demo_SC01-S01');
  assert.deepEqual(shotForCode('dup', shots), {shot: null, state: 'ambiguous'});
  assert.deepEqual(shotForCode('S99', shots), {shot: null, state: 'unknown'});
  const refs = resolveTakeRefs('@sc01-s01.end @SC01-S01.start @SC01-S02.end @SC01-S03.end @S99.end @dup.end @SC01-S04.start @SC01-S05.end @SC01-S01.end', shots, 'sh_demo_SC01-S04');
  assert.deepEqual(refs.map(ref => [ref.key, ref.state]), [['SC01-S01.end', 'ok'], ['SC01-S01.start', 'ok'], ['SC01-S02.end', 'not_adopted'], ['SC01-S03.end', 'no_take'],
    ['S99.end', 'unknown'], ['DUP.end', 'ambiguous'], ['SC01-S04.start', 'self'], ['SC01-S05.end', 'ok']]);
  assert.equal(refs[0].positions.length, 2, 'a tag written twice is one reference');
  assert.equal(refs[0].at, 3.8, '.end is the trim out point');
  assert.equal(refs[1].at, 0.4, '.start is the trim in point');
  assert.equal(refs[2].at, null, 'an untrimmed .end is the last frame, measured by the server');
  assert.equal(refs[2].takeUrl, '/t/2.mp4', 'a shot with nothing adopted is quoted by its newest take');
  assert.equal(refs[7].adopted, true, 'a legacy approved status counts as adopted');
  assert.equal(edgeSeconds('start', null), 0);
  assert.equal(edgeSeconds('end', {in: 1, out: 2.5}), 2.5);
});

test('the default use follows the server: the next segment of one beat, or a split, continues from the out point', () => {
  const beat = (index, count = 3) => ({storyOrigin: {mapping: 'exact', recipes: [{beatKeys: ['b1', 'b2'], segmentIndex: index, segmentCount: count}]}});
  const s2 = shot('S02', {...beat(0)}), s3 = shot('S03', {...beat(1)});
  assert.equal(defaultUse('end', s3, s2), 'first_frame');
  assert.equal(defaultUse('start', s3, s2), 'reference', 'an in point is always a reference');
  assert.equal(defaultUse('end', shot('S04', beat(2)), s2), 'reference', 'not adjacent');
  assert.equal(defaultUse('end', shot('S03', beat(1, 4)), s2), 'reference', 'another cut of the beat');
  assert.equal(defaultUse('end', shot('S03', {storyOrigin: {mapping: 'approx', recipes: beat(1).storyOrigin.recipes}}), s2), 'reference');
  assert.equal(defaultUse('end', shot('S03', {storyLineage: {operation: 'split', fromShotIds: ['sh_demo_S02']}}), s2), 'first_frame');
  assert.equal(defaultUse('end', shot('S03'), shot('S02')), 'reference', 'no evidence: a reference');
  assert.equal(defaultUse('end', null, s2), null, 'the page cannot judge: the server decides');
  const ref = resolveTakeRefs('@S02.end', [s2, s3], s3.shotId)[0];
  assert.deepEqual(refUse(ref, {}, s3), {use: 'first_frame', chosen: false, decided: true});
  assert.deepEqual(refUse(ref, {'S02.end': 'reference'}, s3), {use: 'reference', chosen: true, decided: true});
  assert.deepEqual(refUse(ref, {}, null), {use: 'reference', chosen: false, decided: false}, 'undecided is shown as a reference');
});

test('takeRefUses sends only chosen uses of tags still in the prompt, one first frame at most', () => {
  assert.equal(takeRefUses('@S02.end', {}), undefined);
  assert.deepEqual(takeRefUses('@S02.end and @S04.start', {'S02.end': 'first_frame', 'S04.start': 'reference', 'S09.end': 'reference'}), {'S02.end': 'first_frame', 'S04.start': 'reference'});
  assert.deepEqual(takeRefUses('@S02.end @S03.end', {'S02.end': 'first_frame', 'S03.end': 'first_frame'}), {'S02.end': 'first_frame', 'S03.end': 'reference'});
  assert.equal(takeRefUses('@S02.end', {'S02.end': 'poster'}), undefined, 'an unknown use is never sent');
  assert.deepEqual(chooseUse({'S02.end': 'first_frame', 'S04.start': 'reference'}, 'S03.end', 'first_frame'), {'S02.end': 'reference', 'S04.start': 'reference', 'S03.end': 'first_frame'});
  assert.deepEqual(chooseUse({'S02.end': 'first_frame'}, 'S02.end', 'reference'), {'S02.end': 'reference'});
});

test('continue from the previous shot: the adjacent shot of the same scene, only when it is adopted', () => {
  const beat = index => ({storyOrigin: {mapping: 'exact', recipes: [{beatKeys: ['b'], segmentIndex: index, segmentCount: 2}]}});
  const s1 = shot('S01', {reviewStatus: 'Approved', selectedVideoUrl: '/t/1.mp4', ...beat(0)}), s2 = shot('S02', beat(1)), s3 = shot('S03', {sceneId: 'sc2'});
  assert.deepEqual(previousShot([s1, s2, s3], s2), {shot: s1, key: 'S01.end', code: 'S01', edge: 'end', use: 'first_frame'});
  assert.equal(previousShot([s1, s2, s3], s1), null, 'the first shot has none');
  assert.equal(previousShot([s1, s2, s3], s3), null, 'another scene');
  assert.equal(previousShot([{...s1, reviewStatus: 'Queued'}, s2], s2), null, 'not adopted');
  assert.equal(previousShot([shot('S01', {reviewStatus: 'Approved', selectedVideoUrl: '/t/1.mp4'}), shot('S02')], shot('S02')).use, 'reference');
});

test('a tag is inserted at the start or at the caret, spaced so it stays a tag', () => {
  assert.deepEqual(prependTakeRef('Kael turns.', 'S02'), {text: '@S02.end Kael turns.', caret: 9, changed: true});
  assert.deepEqual(prependTakeRef('', 'S02'), {text: '@S02.end ', caret: 9, changed: true});
  assert.deepEqual(prependTakeRef('Kael turns @s02.end', 'S02'), {text: 'Kael turns @s02.end', caret: 19, changed: false}, 'already quoted: left alone');
  assert.deepEqual(insertTakeRef('Kael turns.', 4, 'S02', 'start'), {text: 'Kael @S02.start turns.', caret: 15});
  assert.deepEqual(insertTakeRef('接續的動作', 2, 'SC01-S02'), {text: '接續@SC01-S02.end的動作', caret: 15});
  assert.deepEqual(insertTakeRef('ab', 2, 'S02'), {text: 'ab @S02.end ', caret: 12});
  for (const result of [insertTakeRef('ab', 1, 'S02'), insertTakeRef('ab', 2, 'S02'), insertTakeRef('接續的', 2, 'S02')]) assert.equal(keys(result.text).length, 1);
});

test('the thumbnail of a tag: the frame already cut, else the take at that second, else the shot picture', () => {
  const quoted = shot('S02', {reviewStatus: 'Approved', selectedVideoUrl: '/t/2.mp4', selectedImageUrl: '/i/2.png', trim: {in: 0, out: 3.8}});
  const [end] = resolveTakeRefs('@S02.end', [quoted], 'sh_x');
  assert.deepEqual(refThumb(end, [{shotId: quoted.shotId, edge: 'end', takeUrl: '/t/2.mp4', frameUrl: '/f/2.png', stale: false}]), {kind: 'image', url: '/f/2.png'});
  assert.deepEqual(refThumb(end, [{shotId: quoted.shotId, edge: 'end', takeUrl: '/t/old.mp4', frameUrl: '/f/old.png', stale: true}]), {kind: 'video', url: '/t/2.mp4', at: 3.8}, 'a frame of another take is not this one');
  const [untrimmed] = resolveTakeRefs('@S02.end', [{...quoted, trim: {in: 0, out: null}}], 'sh_x');
  assert.deepEqual(refThumb(untrimmed), {kind: 'image', url: '/i/2.png'}, 'the last frame is unknown: the shot picture');
  assert.equal(refThumb(resolveTakeRefs('@S09.end', [quoted], 'sh_x')[0]), null);
});
