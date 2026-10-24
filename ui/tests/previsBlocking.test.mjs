import test from 'node:test';
import assert from 'node:assert/strict';
import {DOME, cameraKeys, compileMotionSkills, defaultPlan, framesOf, motionBeats, motionPlan, sampleCamera} from '../src/previs/plan.js';
import {CLOCK, MIN_BEAT, actingBeats, beatToFrame, cameraRange, dummiesOf, frameToBeat, keyHandles, moveBeat, moveCameraKey, moveDummy, onStage, placeOnStage, resizeBeat, retimeCameraKey, setCameraRange, snapMetres} from '../src/previs/blocking.js';

const near = (actual, expected, message = '') => assert.ok(Math.abs(actual - expected) < 1e-6, `${message} ${actual} ≠ ${expected}`);
const skills = (extra = {}) => ({...defaultPlan(), set: 'observatory', use: [
  {skill: 'walkTo', args: {from: [0, -2.2], to: [0, 0]}},
  {skill: 'standIdle', frames: 12},
  {skill: 'turnLook', args: {heading: 0}},
  {skill: 'reachGrip', args: {anchor: [0, 1, 0.4], reach: 10, hold: 20, release: 8}}], seconds: 8, ...extra});

test('a dragged mark snaps to 10 cm and cannot leave the dome', () => {
  assert.equal(snapMetres(0.24), 0.2);assert.equal(snapMetres(0.26), 0.3);assert.equal(snapMetres(-1.04), -1);assert.equal(snapMetres(1.2345), 1.2);
  assert.deepEqual(placeOnStage([0.26, -2.44]), [0.3, -2.4]);
  assert.deepEqual(placeOnStage([0.26, -2.44], {snap: false}), [0.26, -2.44]);
  const [x, z] = placeOnStage([40, DOME.z]);
  near(Math.hypot(x - DOME.x, z - DOME.z), DOME.radius - 0.3, 'held at the glass');near(z, DOME.z);
  assert.deepEqual(onStage([0, 0]), [0, 0]);
});

test('the actor and each cast member are dummies on their own marks', () => {
  const plan = {...defaultPlan(), mark: [0.5, -1], cast: [{mark: [2, 0], turn: 90, acts: []}, {turn: 0}]};
  assert.deepEqual(dummiesOf(plan), [{id: 'actor', mark: [0.5, -1]}, {id: 'cast:0', mark: [2, 0]}, {id: 'cast:1', mark: [0, 0]}]);
  assert.deepEqual(dummiesOf(defaultPlan()), [{id: 'actor', mark: [0, 0]}]);
  assert.deepEqual(moveDummy(plan, 'actor', [1.04, -1.96]).mark, [1, -2]);
  const moved = moveDummy(plan, 'cast:1', [-1.5, -2]);
  assert.deepEqual(moved.cast[1], {turn: 0, mark: [-1.5, -2]});assert.deepEqual(moved.cast[0], plan.cast[0]);assert.deepEqual(plan.cast[1], {turn: 0}, 'the original plan is not touched');
  assert.equal(moveDummy(plan, 'cast:7', [0, 0]), plan);assert.equal(moveDummy(plan, 'nobody', [0, 0]), plan);
});

test('dragging the actor carries his choreography with him; scene anchors and other dummies stay put', () => {
  const plan = {...defaultPlan(), mark: [0, 0], cast: [{mark: [2, 0]}], use: [
    {skill: 'walkTo', args: {from: [0, -2.2], to: [0, 0]}}, {skill: 'standIdle', args: {at: [0, 0], until: 40}},
    {skill: 'reachGrip', args: {anchor: [0, 1, 0.4]}}, {skill: 'turnLook', args: {heading: 1}}, {skill: 'walkTo', args: {to: {range: [0, 1]}}}]};
  const moved = moveDummy(plan, 'actor', [-1.5, -1]);
  assert.deepEqual(moved.mark, [-1.5, -1]);
  assert.deepEqual(moved.use[0].args, {from: [-1.5, -3.2], to: [-1.5, -1]}, 'the walk keeps its shape and still ends on the mark');
  assert.deepEqual(moved.use[1].args, {at: [-1.5, -1], until: 40}, 'a stand moves, its end frame does not');
  assert.deepEqual(moved.use[2], plan.use[2], 'the console is where it was');
  assert.deepEqual(moved.use[3], plan.use[3]);assert.deepEqual(moved.use[4], plan.use[4], 'an open range is not a point to shift');
  assert.deepEqual(moved.cast, plan.cast);assert.deepEqual(plan.use[0].args, {from: [0, -2.2], to: [0, 0]}, 'the original plan is not touched');
  const again = moveDummy(moved, 'actor', [0, 0]);
  assert.deepEqual(again.use[0].args, {from: [0, -2.2], to: [0, 0]}, 'dragging back puts the walk back');
  const cast = moveDummy(plan, 'cast:0', [3, 1]);
  assert.deepEqual(cast.use, plan.use, 'moving a cast member does not touch the actor\'s skills');
  const derived = moveDummy({...defaultPlan(), action: 'walkin'}, 'actor', [1, 1]);
  assert.equal(derived.use, undefined);assert.deepEqual(actingBeats(derived)[0].end, 69, 'Walk in follows the mark by itself');
});

test('dragging a camera key moves it across the plan and keeps its height and aim; a preset move becomes a framed path', () => {
  const plan = {...defaultPlan(), move: 'pushin', lens: 35}, original = cameraKeys(plan);
  assert.equal(plan.keys, null);
  const next = moveCameraKey(plan, 1, [0.04, -3.06]);
  assert.ok(next.keys, 'framed now');assert.equal(next.keys.length, original.length);
  assert.deepEqual([next.keys[1][1][0], next.keys[1][1][2]], [0, -3.1]);
  assert.equal(next.keys[1][1][1], original[1][1][1], 'the height stays');assert.deepEqual(next.keys[1][2], original[1][2], 'the aim stays');
  assert.deepEqual(next.keys[0], original[0], 'the other keys stay');assert.equal(plan.keys, null);
  assert.equal(moveCameraKey(plan, 9, [0, 0]), plan);
  assert.deepEqual(keyHandles(next).map(handle => [handle.index, handle.beat]), [[0, 0], [1, 48], [2, 96]]);
  const out = moveCameraKey(next, 1, [50, 50]);
  assert.ok(Math.hypot(out.keys[1][1][0] - DOME.x, out.keys[1][1][2] - DOME.z) <= DOME.radius, 'a key stays inside the glass');
});

test('a camera key retimes between its neighbours and the move range moves its ends', () => {
  const plan = {...defaultPlan(), move: 'pushin'};
  assert.equal(retimeCameraKey(plan, 1, 70).keys[1][0], 70);
  assert.equal(retimeCameraKey(plan, 1, 200).keys[1][0], 95, 'one beat before the last key');
  assert.equal(retimeCameraKey(plan, 1, -5).keys[1][0], 1, 'one beat after the first key');
  assert.equal(retimeCameraKey(plan, 0, -5).keys[0][0], 0);assert.equal(retimeCameraKey(plan, 2, 500).keys[2][0], CLOCK);
  assert.equal(retimeCameraKey(plan, 1, NaN), plan);assert.equal(retimeCameraKey(plan, 8, 3), plan);
  assert.deepEqual(cameraRange(plan), {start: 0, end: 96});
  near(beatToFrame({...plan, seconds: 8}, 48), 96);near(frameToBeat({...plan, seconds: 8}, 96), 48);
  const eight = {...plan, seconds: 8}, range = setCameraRange(eight, {start: 48, end: 144});
  assert.deepEqual(cameraRange(range), {start: 48, end: 144});
  assert.deepEqual(range.keys.map(key => key[0]), [24, 48, 72], 'the middle key keeps its place within the move');
  const collapsed = setCameraRange(eight, {start: 100, end: 100}), spans = collapsed.keys.map(key => key[0]);
  assert.ok(spans[spans.length - 1] - spans[0] >= 1 - 1e-9, 'a move is at least one beat long');
});

test('an easing curve reshapes the camera move and leaves its ends where they are', () => {
  const plan = {...defaultPlan(), move: 'track'}, linear = {...plan, easing: [0, 0, 1, 1]}, out = {...plan, easing: [0.16, 1, 0.3, 1]}, last = framesOf(plan) - 1;
  assert.deepEqual(sampleCamera(linear, 0), sampleCamera(plan, 0));assert.deepEqual(sampleCamera(linear, last), sampleCamera(plan, last));
  const at = frame => sampleCamera(plan, frame).position[0], lin = frame => sampleCamera(linear, frame).position[0], fast = frame => sampleCamera(out, frame).position[0];
  const [start, end] = [at(0), at(last)], progress = x => (x - start) / (end - start);
  assert.ok(progress(fast(24)) > progress(lin(24)), 'an ease-out covers more ground early than a linear move');
  assert.ok(Math.abs(progress(lin(24)) - progress(at(24))) > 0.05, 'and a linear move differs from the default in-and-out ease');
  assert.deepEqual(sampleCamera({...plan, easing: 'nope'}, 30), sampleCamera(plan, 30), 'anything but four numbers is ignored');
});

test('beats lay the motion skills out on the shot as the compiler places them', () => {
  const plan = skills(), beats = motionBeats(plan);
  assert.deepEqual(beats.map(beat => [beat.skill, beat.start, beat.end, beat.resizable]), [['walkTo', 0, 52, 'frames'], ['standIdle', 52, 64, 'frames'], ['turnLook', 64, 80, 'frames'], ['reachGrip', 80, 118, 'hold']]);
  const {acts} = compileMotionSkills(plan), times = new Set(acts.map(key => Math.round(key.at * (framesOf(plan) - 1))));
  for (const frame of [0, 52, 64, 80]) assert.ok(times.has(frame), `the compiler writes a key at frame ${frame}, where a beat starts or ends`);
  assert.equal(Math.max(...times), 80, 'a grip adds pins, not acting keys, so the last key is where the turn ends');
  assert.deepEqual(motionBeats({...plan, use: [{skill: 'walkTo'}, {skill: 'reachGrip', args: {anchor: 'nowhere'}}, {skill: 'standIdle', args: {until: 30}}]}).map(beat => [beat.frames, beat.resizable]), [[0, null], [0, null], [30, 'until']], 'steps that do nothing have no length');
  assert.deepEqual(motionBeats({...plan, use: [{skill: 'kneelDown', args: {duration: 18}}, {skill: 'kneelDown', f0: 40, frames: 10}]}).map(beat => [beat.start, beat.end]), [[0, 18], [40, 50]]);
  assert.deepEqual(motionBeats(defaultPlan()), []);
});

test('Walk in has a beat of its own, and editing it writes the skill out as the plan\'s use', () => {
  const plan = {...defaultPlan(), action: 'walkin', seconds: 4}, beats = actingBeats(plan);
  assert.deepEqual(beats.map(beat => [beat.skill, beat.start, beat.end, beat.derived]), [['walkTo', 0, 69, true]]);
  const next = resizeBeat(plan, 0, 40);
  assert.equal(next.use.length, 1);assert.equal(next.use[0].frames, 40);assert.equal(next.use[0].f0, 0);
  assert.deepEqual(actingBeats(next).map(beat => [beat.end, beat.derived]), [[40, false]]);
  const before = motionPlan(plan).acts.map(key => key.at), same = motionPlan({...plan, use: resizeBeat(plan, 0, 69).use}).acts.map(key => key.at);
  assert.deepEqual(same, before, 'writing it out as it already is plays the same');
  assert.deepEqual(actingBeats({...defaultPlan(), action: 'turnreach'}), [], 'a built-in action has no beats to drag');
  assert.deepEqual(actingBeats({...plan, acts: [{at: 0, yaw: 0}]}), [], 'explicit acting keys keep priority over the derived walk');
  assert.equal(resizeBeat({...defaultPlan(), action: 'stand'}, 0, 40).use, undefined);
});

test('dragging a beat edge changes only that beat, stops at the next beat and the end of the shot, and keeps a minimum', () => {
  const plan = skills(), end = framesOf(plan) - 1;
  const longer = resizeBeat(plan, 1, 62);
  assert.deepEqual(motionBeats(longer).map(beat => [beat.start, beat.end]), [[0, 52], [52, 62], [64, 80], [80, 118]], 'the neighbours stay put');
  assert.deepEqual(longer.use.map(step => step.f0), [0, 52, 64, 80], 'starts are pinned so nothing slides');
  assert.equal(motionBeats(resizeBeat(plan, 1, 90))[1].end, 64, 'it cannot run into the next beat');
  assert.equal(motionBeats(resizeBeat(plan, 1, 52))[1].end, 52 + MIN_BEAT, 'a beat keeps a minimum length');
  assert.equal(motionBeats(resizeBeat(plan, 3, 500))[3].end, end, 'nor past the end of the shot');
  const hold = resizeBeat(plan, 3, 130);
  assert.equal(hold.use[3].args.hold, 130 - 80 - 10 - 8, 'a grip stretches its hold, keeping its reach and release');
  assert.equal(motionBeats(hold)[3].end, 130);
  assert.equal(motionBeats(resizeBeat(plan, 3, 85))[3].end, 80 + 10 + 8, 'but never shorter than reach plus release');
  const idle = resizeBeat({...plan, use: [{skill: 'standIdle', args: {until: 30}}, {skill: 'standIdle', f0: 40, frames: 10}]}, 0, 35);
  assert.equal(idle.use[0].args.until, 35);
  assert.equal(resizeBeat(plan, 9, 10), plan);assert.equal(resizeBeat(plan, 1, NaN), plan);
  const nothing = {...plan, use: [{skill: 'walkTo'}]};
  assert.equal(resizeBeat(nothing, 0, 30), nothing, 'a step that does nothing cannot be resized');
  assert.deepEqual(plan.use.map(step => step.f0), [undefined, undefined, undefined, undefined], 'the original plan is not touched');
});

test('dragging a whole beat keeps its length and stays between its neighbours', () => {
  const plan = skills({use: [{skill: 'standIdle', frames: 10}, {skill: 'standIdle', f0: 30, frames: 20}, {skill: 'standIdle', f0: 80, args: {until: 100}}]}), moved = moveBeat(plan, 1, 45);
  assert.deepEqual(motionBeats(moved).map(beat => [beat.start, beat.end]), [[0, 10], [45, 65], [80, 100]]);
  assert.deepEqual(motionBeats(moveBeat(plan, 1, 0))[1], {...motionBeats(moveBeat(plan, 1, 0))[1], start: 10, end: 30}, 'it stops at the end of the beat before');
  assert.equal(motionBeats(moveBeat(plan, 1, 90))[1].end, 80, 'and at the start of the one after');
  const shifted = moveBeat(plan, 2, 85);
  assert.equal(shifted.use[2].f0, 85);assert.equal(shifted.use[2].args.until, 105, 'an until moves with its start');
  assert.equal(motionBeats(moveBeat(plan, 2, 500))[2].end, framesOf(plan) - 1, 'the last beat stops at the end of the shot');
  assert.equal(moveBeat(plan, 5, 3), plan);assert.equal(moveBeat(plan, 0, NaN), plan);
  const tight = skills({use: [{skill: 'standIdle', f0: 0, frames: 10}, {skill: 'standIdle', f0: 10, frames: 10}, {skill: 'standIdle', f0: 20, frames: 10}]});
  assert.deepEqual(motionBeats(moveBeat(tight, 1, 15)).map(beat => beat.start), [0, 10, 20], 'a beat with no room does not move');
});
