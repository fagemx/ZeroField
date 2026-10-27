import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { ANGLES, MOVE_KEYS, OPS_VERSION, OpsError, SIZES, STAGE_TARGETS, solveOps, solveRequest, targetPoint, validateOps } from '../src/previs/ops.js';
import { LENSES, MOVES, SCENE_ANCHORS, SETS, defaultPlan, describePlan, sampleCamera } from '../src/previs/plan.js';
import { actingBeats } from '../src/previs/blocking.js';

const golden = JSON.parse(fs.readFileSync(new URL('../../tests/fixtures/previs_ops_golden.json', import.meta.url), 'utf8'));
const base = (extra = {}) => ({ ...defaultPlan(), ...extra });
const place = (cast, relativeTo, offset, facing) => ({ op: 'place', cast, relativeTo, offset, facing });
const near = (actual, expected, message = '') => assert.ok(Math.abs(actual - expected) < 1e-3, `${message} ${actual} ≠ ${expected}`);

test('every golden case solves to the checked-in plan, and the same request always gives the same plan', () => {
  assert.equal(golden.version, OPS_VERSION, 'regenerate the golden file: node scripts/previs_ops_golden.mjs --write');
  assert.ok(golden.cases.length >= 8);
  for (const { id, input, expect } of golden.cases) {
    const before = JSON.stringify(input), first = solveRequest(input), again = solveRequest(JSON.parse(JSON.stringify(input)));
    assert.deepEqual(first, expect, id);
    assert.deepEqual(again, first, id + ' is deterministic');
    assert.equal(JSON.stringify(input), before, id + ' leaves its input alone');
  }
});

test('every invalid golden request is refused at the path the golden file (and the Python validator) names', () => {
  for (const { id, input, path, message } of golden.invalid) {
    assert.throws(() => solveRequest(input), error => error instanceof OpsError && error.path === path && error.message === message, id);
  }
});

test('the vocabulary is the stage’s own: lenses, moves and sets come from plan.js', () => {
  assert.deepEqual(Object.keys(MOVE_KEYS).sort(), [...MOVES].sort());
  assert.deepEqual(Object.keys(STAGE_TARGETS).sort(), [...SETS].sort());
  for (const name of Object.keys(SCENE_ANCHORS)) assert.ok(STAGE_TARGETS.observatory.includes(name), name);
  assert.deepEqual(SIZES, ['wide', 'full', 'medium', 'close', 'extreme_close']);
  assert.deepEqual(ANGLES, ['low', 'eye', 'high', 'overhead']);
  const camera = lens => ({ op: 'camera', size: 'close', angle: 'eye', lens, move: 'static' });
  for (const lens of LENSES) validateOps(base(), [camera(lens)]);
  assert.throws(() => validateOps(base(), [camera('35')]), /lens/);
});

test('targets sit where the stage builds them, and "window" is the glass', () => {
  assert.deepEqual(targetPoint(base(), 'console'), [0, 0.58]);
  assert.deepEqual(targetPoint(base(), 'dial'), [-0.25, 0.56]);
  assert.deepEqual(targetPoint(base(), 'window'), [0, 3.8]);
  assert.deepEqual(targetPoint(base(), 'mark'), [0, 0]);
  assert.equal(targetPoint(base({ set: 'empty' }), 'console'), null);
  assert.deepEqual(targetPoint(base({ set: 'parallax' }), 'near'), [0, -0.7]);
  assert.deepEqual(targetPoint(base({ set: 'parallax', layers: [{ id: 'mid', x: 1.5, z: 3 }] }), 'mid'), [1.5, 3]);
  assert.equal(targetPoint(base({ set: 'parallax' }), 'console'), null);
});

test('the first new code takes the unnamed actor, later ones join the cast, someone on set moves', () => {
  const { plan } = solveOps(base(), [place('@CAST-02', 'console', [0.2, -0.5], 'room'), place('@CAST-01', '@CAST-02', [1, 0], '@CAST-02')]);
  assert.equal(plan.code, '@CAST-02');
  assert.deepEqual(plan.mark, [0.2, 0.08]);
  assert.deepEqual(plan.cast, [{ code: '@CAST-01', mark: [1.2, 0.08], turn: -90 }]);
  const named = base({ code: '@CAST-01', cast: [{ code: '@CAST-02', mark: [1, -1] }] });
  const moved = solveOps(named, [place('@CAST-02', 'mark', [-1, -1], 'room')]).plan;
  assert.equal(moved.code, '@CAST-01');
  assert.deepEqual(moved.cast, [{ code: '@CAST-02', mark: [-1, -1], turn: 180 }]);
  assert.deepEqual(moved.mark, undefined, 'nobody else moves');
});

test('facing: a canned actor faces the console or the room side and turns the rest; a cast member turns', () => {
  const window = solveOps(base(), [place('@CAST-01', 'mark', [1, 0], 'window')]).plan;
  assert.equal(window.facing, 'console'); near(window.turn, -14.7, 'toward the glass, a little left');
  const room = solveOps(base(), [place('@CAST-01', 'mark', [0, 0], 'room')]).plan;
  assert.deepEqual([room.facing, room.turn], ['room', 0]);
  const skills = base({ code: '@CAST-01', use: [{ skill: 'standIdle', frames: 24 }] });
  const turned = solveOps(skills, [place('@CAST-01', 'mark', [0, 0], 'room')]).plan;
  assert.deepEqual([turned.facing, turned.turn], ['console', 180], 'skills keep their facing; the actor turns');
});

test('the camera frames everyone on set from the side the actor faces, at the size and angle asked', () => {
  const ops = [place('@CAST-01', 'mark', [0, 0], 'camera'), { op: 'camera', size: 'close', angle: 'eye', lens: 50, move: 'pushin', from: 'K1', to: 'K2' }];
  const { plan } = solveOps(base({ easing: [0.1, 0, 0.9, 1] }), ops);
  assert.deepEqual([plan.lens, plan.move, plan.easing], [50, 'pushin', undefined]);
  assert.equal(plan.keys.length, 2);
  const [[b0, p0, a0], [b1, p1]] = plan.keys;
  assert.deepEqual([b0, b1], [0, 96]);
  assert.deepEqual(a0, [0, 1.66, 0], 'aimed at the face');
  assert.ok(p0[2] < p1[2] && p1[2] < 0, 'pushes in from the room side');
  near(p1[2], -1.566, 'a 0.62 m frame on a 50 mm lens');
  near(p0[2], -1.566 * 1.9);
  assert.equal(plan.facing, 'room', 'faces the lens');
  const low = solveOps(base(), [ops[0], { ...ops[1], angle: 'low' }]).plan.keys[1][1], high = solveOps(base(), [ops[0], { ...ops[1], angle: 'high' }]).plan.keys[1][1];
  assert.ok(low[1] < 1.66 && high[1] > 1.66, 'low looks up, high looks down');
  const wide = solveOps(base(), [ops[0], { ...ops[1], size: 'wide' }]).plan.keys[1][1];
  assert.ok(wide[2] < p1[2], 'a wider size stands further back');
  assert.match(describePlan(plan), /50mm/);
});

test('from and to pick the span of the move; a static camera holds one key over the shot', () => {
  const orbit = k => solveOps(base(), [{ op: 'camera', size: 'medium', angle: 'eye', lens: 35, move: 'orbit', ...k }]).plan.keys;
  const all = orbit({}), half = orbit({ from: 'K2', to: 'K3' });
  assert.equal(all.length, 3);
  assert.deepEqual(all.map(k => k[0]), [0, 48, 96]);
  assert.deepEqual(half.map(k => k[1]), [all[1][1], all[2][1]]);
  assert.deepEqual(half.map(k => k[0]), [0, 96], 're-timed over the whole shot');
  const still = solveOps(base(), [{ op: 'camera', size: 'medium', angle: 'eye', lens: 35, move: 'static', from: 'K1' }]).plan;
  assert.deepEqual(still.keys[0][1], still.keys[1][1]);
  assert.deepEqual(sampleCamera(still, 0), sampleCamera(still, 96));
});

test('a retime moves an acting beat between its neighbours; a plan without acting beats cannot be retimed', () => {
  const walk = base({ code: '@CAST-01', seconds: 8, use: [{ skill: 'standIdle', frames: 24 }, { skill: 'turnLook', args: { heading: 1 } }] });
  const { plan, warnings } = solveOps(walk, [{ op: 'retime', beat: 2, at: 0.5 }]);
  assert.equal(actingBeats(plan)[1].start, 96);
  assert.deepEqual(warnings, []);
  assert.equal(actingBeats(base({ action: 'walkin' })).length, 1, 'the Walk in action is one beat');
  assert.throws(() => solveOps(base(), [{ op: 'retime', beat: 1, at: 0.5 }]), error => error.path === 'ops[0].beat');
});

test('solveRequest resolves the base like the stage: the stored plan, else the seed over the slate', () => {
  const ops = [{ op: 'camera', size: 'medium', angle: 'eye', lens: 85, move: 'static' }];
  const seeded = solveRequest({ shot: { slate: { motion: 'Orbit', rig: '24mm', action: 'He walks in.' }, previsPlan: { set: 'parallax', seconds: 6 } }, ops });
  assert.deepEqual([seeded.plan.set, seeded.plan.seconds, seeded.plan.action, seeded.base.actingBeats], ['parallax', 6, 'walkin', 1]);
  const stored = solveRequest({ stored: base({ set: 'empty', mood: 'night' }), shot: { previsPlan: { set: 'parallax' } }, ops });
  assert.deepEqual([stored.plan.set, stored.plan.mood], ['empty', 'night']);
  assert.throws(() => solveRequest({ shot: {}, ops, castCodes: [] }) && solveRequest({ shot: {}, ops: [place('@CAST-01', 'mark', [0, 0], 'room')], castCodes: [] }), /not on the cast sheet/);
});
