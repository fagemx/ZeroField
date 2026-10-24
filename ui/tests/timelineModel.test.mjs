import test from 'node:test';
import assert from 'node:assert/strict';
import {FPS, FRAME, buildClips, totalSeconds, clipAt, fileTime, dragEdge, slip, setPoint, setLength, changedTrims, nearest, cutPoints, rhythm, parseTrimCommand, clock, signed, planSeconds, wholeTake} from '../src/timelineModel.js';

const shot = (index, extra = {}) => ({rowId: 'b' + index, shotId: 'sh_demo_b' + index, shotIndex: index, sceneId: 'sc_demo_01_S01', selectedVideoUrl: `/take/${index}.mp4`, selectedImageUrl: `/still/${index}.png`, ...extra});
const near = (actual, expected, message) => assert.ok(Math.abs(actual - expected) < 1e-6, `${message || ''} ${actual} ≠ ${expected}`);
const measured = {'/take/1.mp4': 4, '/take/2.mp4': 4, '/take/3.mp4': 6};
const cut = (extra = {}, options = {}) => buildClips([shot(1), shot(2), shot(3, extra)], {measured, ...options});

test('clips follow slate order and add up: a take counts for its file, previs and plans for their planned seconds', () => {
  const clips = buildClips([shot(1), shot(2, {selectedVideoUrl: null, previsVideoUrl: '/previs/2.mp4', previsPlan: {seconds: 6}}), shot(3, {selectedVideoUrl: null, selectedImageUrl: null}), shot(4)], {measured: {'/take/1.mp4': 4, '/take/4.mp4': 5}});
  assert.deepEqual(clips.map(clip => [clip.label, clip.kind, clip.length, clip.start]), [['1', 'take', 4, 0], ['2', 'previs', 6, 4], ['3', 'plan', 4, 10], ['4', 'take', 5, 14]]);
  assert.equal(totalSeconds(clips), 19);
  assert.deepEqual(clips.map(clip => clip.trimmable), [true, false, false, true], 'only a take of known length can be trimmed');
  assert.equal(totalSeconds([]), 0);
  assert.equal(planSeconds({previsPlan: {seconds: 8}}), 8);assert.equal(planSeconds({previsPlan: {seconds: -2}}), 4);assert.equal(planSeconds({}), 4);
});

test('a take whose file is not measured yet is planned length and cannot be trimmed; it becomes exact once measured', () => {
  const [before] = buildClips([shot(1)], {measured: {}}), [after] = buildClips([shot(1)], {measured: {'/take/1.mp4': 5.04}});
  assert.equal(before.length, 4);assert.equal(before.trimmable, false);assert.equal(before.sourceKnown, false);
  near(after.length, 5.0, 'floored to a whole frame');assert.equal(after.trimmable, true);
  assert.equal(dragEdge([before], 0, 'out', -1), null);
});

test('a saved trim cuts a take and only a take; a draft overrides the saved one', () => {
  const saved = buildClips([shot(1, {trim: {in: 0.5, out: 3.5}}), shot(2, {selectedVideoUrl: null, previsVideoUrl: '/previs/2.mp4', trim: {in: 1, out: 2}})], {measured});
  assert.deepEqual([saved[0].in, saved[0].out, saved[0].length, saved[0].trimmed], [0.5, 3.5, 3, true]);
  assert.deepEqual([saved[1].in, saved[1].out, saved[1].length, saved[1].trimmed], [0, 4, 4, false], 'previs fill is never trimmed');
  const draft = buildClips([shot(1, {trim: {in: 0.5, out: 3.5}})], {measured, trims: {b1: {in: 0, out: 2}}});
  assert.equal(draft[0].length, 2);
  const whole = buildClips([shot(1, {trim: {in: 0.5, out: 3.5}})], {measured, trims: {b1: wholeTake()}});
  assert.deepEqual([whole[0].in, whole[0].out, whole[0].trimmed], [0, 4, false]);
  const wild = buildClips([shot(1, {trim: {in: -3, out: 99}})], {measured});
  assert.deepEqual([wild[0].in, wild[0].out], [0, 4], 'a trim outside the file is held inside it');
  const crossed = buildClips([shot(1, {trim: {in: 3, out: 1}})], {measured});
  assert.ok(crossed[0].length >= FRAME - 1e-9, 'a clip is never shorter than a frame');
});

test('clipAt finds the clip under a time and fileTime maps it into the take', () => {
  const clips = cut({trim: {in: 1, out: 5}});
  assert.equal(clipAt(clips, 0).label, '1');assert.equal(clipAt(clips, 3.99).label, '1');assert.equal(clipAt(clips, 4).label, '2');
  assert.equal(clipAt(clips, 9).label, '3');assert.equal(clipAt(clips, 500).label, '3', 'past the end is the last clip');assert.equal(clipAt([], 1), null);
  near(fileTime(clips[2], 9), 2, 'one second into a clip that starts at 1.0 in its file, 8 s on the timeline');
  assert.equal(fileTime(clips[2], 500), 5, 'held at the out point');
  assert.deepEqual(cutPoints(clips), [0, 4, 8, 12]);
});

test('ripple: shortening an out edge keeps the neighbours as they are and the film gets shorter', () => {
  const clips = cut(), move = dragEdge(clips, 0, 'out', -10 / FPS, {ripple: true});
  near(move.delta, -10 / FPS);assert.equal(move.rolled, null);
  assert.deepEqual(Object.keys(move.trims), ['b1']);near(move.trims.b1.out, 4 - 10 / FPS);assert.equal(move.trims.b1.in, 0);
  const after = buildClips([shot(1), shot(2), shot(3)], {measured, trims: move.trims});
  near(totalSeconds(after), 14 - 10 / FPS, 'the film is 10 frames shorter');near(after[1].start, 4 - 10 / FPS, 'the next clip moved up');
  assert.equal(after[1].length, 4);
});

test('an in edge dragged later makes the clip shorter and an out edge dragged later makes it longer; both stay inside the file', () => {
  const clips = cut({trim: {in: 1, out: 4}});
  assert.equal(clips[2].length, 3);
  near(dragEdge(clips, 2, 'in', 0.5).trims.b3.in, 1.5);
  near(dragEdge(clips, 2, 'in', -9).delta, -1, 'cannot reach before the start of the take');
  near(dragEdge(clips, 2, 'out', 9).delta, 2, 'cannot run past the end of the take (6 s)');
  assert.equal(dragEdge(clips, 2, 'out', 9).trims.b3.out, null, 'out at the end of the take is stored as null');
  near(dragEdge(clips, 2, 'out', -9).delta, -(3 - FRAME), 'at least one frame stays');
  near(dragEdge(clips, 2, 'in', 9).delta, 3 - FRAME);
  assert.equal(dragEdge(clips, 2, 'middle', 1), null);assert.equal(dragEdge(clips, 2, 'out', NaN), null);assert.equal(dragEdge(clips, 7, 'out', 1), null);
  near(dragEdge(clips, 2, 'out', 0.51 / FPS).delta, 1 / FPS, 'a move snaps to whole frames');
});

test('roll (ripple off): the cut moves, the neighbour gives or takes the same time, and the film keeps its length', () => {
  const clips = cut(), move = dragEdge(clips, 0, 'out', 12 / FPS, {ripple: false});
  near(move.delta, 0, 'clip 1 is the whole take, so it cannot run longer');
  const early = dragEdge(clips, 0, 'out', -12 / FPS, {ripple: false});
  assert.equal(early.rolled, 'b2');near(early.delta, 0, 'the next clip starts at its first frame, so there is nothing before it to give');
  // The next clip can start earlier in its file only when it was already trimmed at the head.
  const roomy = cut({trim: {in: 2, out: 6}});
  const second = dragEdge(roomy, 1, 'out', 0, {ripple: false});
  assert.equal(second.rolled, 'b3');
  const grow = buildClips([shot(1, {trim: {in: 0, out: 3}}), shot(2, {trim: {in: 1, out: 4}})], {measured});
  const rolled = dragEdge(grow, 0, 'out', 1, {ripple: false});
  near(rolled.delta, 1);assert.equal(rolled.trims.b1.out, null, 'the first clip runs to the end of its take again');near(rolled.trims.b2.in, 2, 'the next clip lost its first second');
  const after = buildClips([shot(1, {trim: {in: 0, out: 3}}), shot(2, {trim: {in: 1, out: 4}})], {measured, trims: rolled.trims});
  near(totalSeconds(after), totalSeconds(grow), 'a roll never changes the length of the film');
  near(after[1].start, 4);
  // The in edge rolls the clip before it.
  const back = dragEdge(grow, 1, 'in', -1, {ripple: false});
  near(back.delta, -1);near(back.trims.b2.in, 0);near(back.trims.b1.out, 2);
  const limited = dragEdge(grow, 1, 'in', 2, {ripple: false});
  near(limited.delta, 1, 'the clip before has one second of take left');
});

test('a roll without a trimmable neighbour behaves as a ripple', () => {
  const clips = buildClips([shot(1), shot(2, {selectedVideoUrl: null, previsVideoUrl: '/previs/2.mp4'})], {measured});
  const move = dragEdge(clips, 0, 'out', -1, {ripple: false});
  assert.equal(move.rolled, null);assert.deepEqual(Object.keys(move.trims), ['b1']);
  const first = dragEdge(buildClips([shot(1), shot(2)], {measured}), 0, 'in', 1, {ripple: false});
  assert.equal(first.rolled, null, 'nothing comes before the first clip');
});

test('setPoint and setLength move an edge to an exact place', () => {
  const clips = cut();
  near(setPoint(clips, 0, 'out', 3.5).trims.b1.out, 3.5);near(setPoint(clips, 0, 'in', 1).trims.b1.in, 1);
  near(setLength(clips, 2, 3.5).trims.b3.out, 3.5);
  near(setLength(clips, 2, 99).trims.b3.in, 0);assert.equal(setLength(clips, 2, 99).trims.b3.out, null);
  assert.equal(setPoint(clips, 0, 'out', Infinity), null);assert.equal(setLength(clips, 9, 3), null);
});

test('slip slides both edges together, keeping the length and moving nothing else', () => {
  const clips = cut({trim: {in: 1, out: 4}});
  const move = slip(clips, 2, 1);
  near(move.delta, 1);near(move.trims.b3.in, 2);near(move.trims.b3.out, 5);assert.deepEqual(Object.keys(move.trims), ['b3']);
  const after = buildClips([shot(1), shot(2), shot(3, {trim: {in: 1, out: 4}})], {measured, trims: move.trims});
  assert.equal(totalSeconds(after), totalSeconds(clips), 'the length is unchanged');
  near(slip(clips, 2, 9).delta, 2, 'cannot slide past the end of the take');assert.equal(slip(clips, 2, 9).trims.b3.out, null);
  near(slip(clips, 2, -9).delta, -1, 'cannot slide before the start');
  assert.equal(slip(clips, 9, 1), null);assert.equal(slip(clips, 2, NaN), null);
});

test('only trims that differ from what is already there are worth saving', () => {
  const clips = cut({trim: {in: 1, out: 5}});
  assert.deepEqual(changedTrims(clips, {b3: {in: 1, out: 5}, b1: {in: 0, out: null}}), {});
  assert.deepEqual(Object.keys(changedTrims(clips, {b3: {in: 1, out: 4}, b1: {in: 0, out: null}})), ['b3']);
  assert.deepEqual(changedTrims(clips, {zz: {in: 0, out: 1}}), {}, 'an unknown clip is ignored');
});

test('snapping picks the nearest target inside the tolerance', () => {
  assert.equal(nearest([0, 4, 8], 3.9, 0.2), 4);assert.equal(nearest([0, 4, 8], 6, 0.2), null);assert.equal(nearest([3.9, 4.1], 4.02, 0.2), 4.1);assert.equal(nearest([], 1, 1), null);
});

test('rhythm flags a clip that runs well over the average and says how far to take it down', () => {
  const clips = buildClips([shot(1), shot(2), shot(3), shot(4, {trim: null})], {measured: {'/take/1.mp4': 4, '/take/2.mp4': 4, '/take/3.mp4': 4, '/take/4.mp4': 8}});
  const beat = rhythm(clips);
  near(beat.mean, 5);near(beat.total, 20);assert.equal(beat.longest, 8);
  assert.deepEqual(beat.items.map(item => item.long), [false, false, false, true]);
  near(beat.items[3].trimBy, -3);near(beat.items[0].ratio, 0.5);
  assert.deepEqual(rhythm(buildClips([shot(1), shot(2)], {measured})).items.map(item => item.long), [false, false], 'two clips are never a rhythm');
  assert.deepEqual(rhythm([]), {total: 0, mean: 0, longest: 0, items: []});
});

test('the say layer understands short instructions in English and Chinese', () => {
  const second = 1;
  const expect = (text, wanted) => assert.deepEqual(parseTrimCommand(text), wanted, text);
  expect('out -3f', {edge: 'out', delta: -3 / FPS});
  expect('out earlier 3 frames', {edge: 'out', delta: -3 / FPS});
  expect('in +12f', {edge: 'in', delta: 0.5});
  expect('trim end 0.5s', {edge: 'out', delta: -0.5});
  expect('trim in 2f', {edge: 'in', delta: 2 / FPS});
  expect('extend 1 second', {edge: 'out', delta: second});
  expect('start later by 1s', {edge: 'in', delta: second});
  expect('length 3.5s', {edge: 'out', length: 3.5});
  expect('出點早三格', {edge: 'out', delta: -3 / FPS});
  expect('出點早3格', {edge: 'out', delta: -3 / FPS});
  expect('入點晚兩格', {edge: 'in', delta: 2 / FPS});
  expect('縮短半秒', {edge: 'out', delta: -0.5});
  expect('加長一秒', {edge: 'out', delta: second});
  expect('長度3.5秒', {edge: 'out', length: 3.5});
  expect('出點延後十二幀', {edge: 'out', delta: 0.5});
  expect('出點提前二十四格', {edge: 'out', delta: -second});
  for (const nothing of ['', 'make it better', 'out earlier', '3', 'out 3 apples', '0f earlier']) assert.equal(parseTrimCommand(nothing), null, nothing);
  assert.equal(parseTrimCommand(undefined), null);
});

test('times read as clock text and a change reads in frames or seconds', () => {
  assert.equal(clock(0), '00:00.0');assert.equal(clock(8), '00:08.0');assert.equal(clock(75.26), '01:15.3');assert.equal(clock(-1), '00:00.0');assert.equal(clock(NaN), '00:00.0');
  assert.equal(signed(-10 / FPS), '−10 f');assert.equal(signed(0.5), '+12 f');assert.equal(signed(3), '+3.0 s');assert.equal(signed(0), '0 f');
});
