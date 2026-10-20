import test from 'node:test';
import assert from 'node:assert/strict';
import {FRAMES, defaultPlan, cameraKeys, sampleCamera, sampleActor, verticalFov, describePlan} from '../src/previs/plan.js';
import {benchGroup} from '../src/studioModel.js';

const dist = (a, b) => Math.hypot(...a.map((v, k) => v - b[k]));

test('previs camera paths start and end on their keys and a push-in closes on the station', () => {
  const plan = defaultPlan(), keys = cameraKeys(plan);
  assert.deepEqual(sampleCamera(plan, 0).position, keys[0][1]);
  assert.deepEqual(sampleCamera(plan, FRAMES - 1).position, keys[keys.length - 1][1]);
  const station = [0, 1.4, 0];
  const d = [0, 24, 48, 72, 96].map(f => dist(sampleCamera(plan, f).position, station));
  assert.ok(d.every((v, i) => i === 0 || v <= d[i - 1] + 1e-9), d.join());
  const pull = {...plan, move: 'pullout'};
  assert.deepEqual(sampleCamera(pull, 0).position, sampleCamera(plan, FRAMES - 1).position);
  assert.deepEqual(sampleCamera(pull, FRAMES - 1).position, sampleCamera(plan, 0).position);
});

test('framed start/end keys override the preset and lenses map to a 36 mm sensor', () => {
  const plan = {...defaultPlan(), keys: [[0, [1, 2, 3], [0, 1, 0]], [96, [4, 5, 6], [0, 1, 0]]]};
  assert.deepEqual(sampleCamera(plan, 0).position, [1, 2, 3]);
  assert.deepEqual(sampleCamera(plan, 96).position, [4, 5, 6]);
  assert.match(describePlan(plan), /Custom camera path/);
  assert.ok(Math.abs(verticalFov(35) - 31.6) < 0.2, verticalFov(35));
  assert.ok(verticalFov(85) < verticalFov(35) && verticalFov(35) < verticalFov(24));
});

test('turn-and-reach turns to the console first, then reaches and holds; previs is a bench input', () => {
  const plan = defaultPlan();
  assert.ok(sampleActor(plan, 0).yaw > 1.5 && sampleActor(plan, 0).reach === 0);
  assert.equal(sampleActor(plan, 40).yaw, 0);
  assert.ok(Math.abs(sampleActor(plan, 44).reach - 1.16) < 1e-9 && sampleActor(plan, 96).reach === sampleActor(plan, 44).reach);
  assert.equal(benchGroup('Previs'), 'input');
});
