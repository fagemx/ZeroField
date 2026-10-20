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
  assert.ok(d[4] < d[0] - 3, `the camera must actually travel: ${d.join()}`);
  for (const move of ['pushin', 'orbit', 'crane', 'track']) {  // every moving preset changes position between its ends
    const m = {...plan, move};
    assert.ok(dist(sampleCamera(m, 0).position, sampleCamera(m, 96).position) > 1, move);
    assert.ok(cameraKeys(m).every(([f], i, ks) => f >= 0 && f <= 96 && (i === 0 || f > ks[i - 1][0])), move);
  }
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
  assert.ok(Math.abs(sampleActor(plan, 0).yaw) > 1.5 && sampleActor(plan, 0).reach === 0);
  assert.equal(sampleActor(plan, 40).yaw, 0);
  assert.ok(Math.abs(sampleActor(plan, 44).reach - 1.16) < 1e-9 && sampleActor(plan, 96).reach === sampleActor(plan, 44).reach);
  assert.equal(benchGroup('Previs'), 'input');
});

test('the WebM writer keeps every frame with its own timestamp and declares the frame rate', async () => {
  const {muxWebM} = await import('../src/previs/webm.js');
  const chunks = Array.from({length: 97}, (_, f) => ({data: new Uint8Array([0x10 + (f % 7), f]), timestamp: Math.round(f * 1e6 / 24), key: f % 24 === 0}));
  const out = muxWebM(chunks, {width: 1280, height: 704, fps: 24});
  const hex = Buffer.from(out).toString('hex');
  assert.equal(hex.slice(0, 8), '1a45dfa3');
  assert.ok(Buffer.from(out).includes(Buffer.from('V_VP9')));
  assert.ok(hex.includes('23e383' + '0100000000000004' + '027bc86b'), 'DefaultDuration 41666667 ns');
  const blocks = hex.match(/a301000000000000(06)81/g) || [];
  assert.equal(blocks.length, 97);
  const last = out.indexOf(0x81, out.length - 6);  // last block: track 1, relative time 4000 ms
  assert.deepEqual([...out.slice(last + 1, last + 3)], [0x0f, 0xa0]);
});
