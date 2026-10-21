import test from 'node:test';
import assert from 'node:assert/strict';
import { FRAME_H, IDIOMS, SCENE, actorPlan, choose, effShot, inDome, solve, toPlan } from '../prototypes/shot-grammar/grammar.js';
import { framesOf, sampleCamera } from '../src/previs/plan.js';

const beat = SCENE.beats[2];  // S03, 6 s
const dist = (a, b) => Math.hypot(...a.map((v, i) => v - b[i]));

test('shot size sets the camera distance: a push lands on its end framing', () => {
  const s = effShot(beat, { shot: { subj: 'actor', focus: 'eyes', size: 'MS', end: 'CU', az: 150, move: 'push', speed: 'slow' } });
  const plan = actorPlan(beat), tan = Math.tan(solve(s, plan, 0).fov / 2 * Math.PI / 180);
  const at = p => { const c = solve(s, plan, p); return dist(c.pos, c.aim); };
  assert.ok(Math.abs(at(0) - FRAME_H.MS / 2 / tan) < 1e-6);
  assert.ok(Math.abs(at(1) - FRAME_H.CU / 2 / tan) < 1e-6);
});

test('a longer lens holds the same shot size from farther away', () => {
  const shot = { subj: 'actor', focus: 'eyes', size: 'MCU', az: 140, move: 'static' }, plan = actorPlan(beat);
  const d = lens => { const c = solve(effShot(beat, { lens, shot }), plan, 0); return dist(c.pos, c.aim); };
  assert.ok(Math.abs(d(85) / d(35) - 85 / 35) < 0.02);
});

test('drama idioms wait for tension, and the film breaks its calm camera at most once', () => {
  const rows = choose(SCENE, { preset: 'standard', seed: 7 });
  rows.filter(r => r.pick.idiom.drama).forEach(r => assert.ok(r.beat.tension >= 0.8, r.beat.id));
  assert.ok(rows.filter(r => r.pick.s.breaks).length <= 1);
  assert.deepEqual(rows.map(r => r.beat.id), SCENE.beats.map(b => b.id));
});

test('exported keys replay the solved camera through the 3D Stage sampler', () => {
  const r = choose(SCENE, { preset: 'standard', seed: 7, pins: { S03: 'Low-angle push' } })[2];
  assert.equal(r.pick.idiom.name, 'Low-angle push');
  const plan = toPlan(r), n = framesOf(plan) - 1;
  for (const p of [0, 0.2, 0.5, 0.8, 1]) {
    const c = solve(r.pick.s, plan, p), z = sampleCamera(plan, p * n);
    assert.ok(dist(c.pos, z.position) < 0.03, `p=${p} off by ${dist(c.pos, z.position)}`);
  }
  assert.ok(JSON.stringify(plan).length < 4096);  // the WebM title keeps the plan only in its first 8 KB
});

test('the camera must stay inside the dome', () => {
  assert.ok(inDome([0, 1.6, -2]));
  assert.ok(!inDome([0, 1.6, 1.5]) && !inDome([0, 0.1, -2]));
  assert.ok(Object.values(IDIOMS).flat().every(i => i.shot.size in FRAME_H && (!i.shot.end || i.shot.end in FRAME_H)));
});
