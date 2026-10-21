import test from 'node:test';
import assert from 'node:assert/strict';
import { FRAME_H, IDIOMS, SCENE, actorAt, actorPlan, choose, effShot, fromGround, halfway, idiomFromShot, inDome, nearestSize, pickChanges, solve, tierFor, toPlan, whyNot } from '../prototypes/shot-grammar/grammar.js';
import { framesOf, sampleCamera } from '../src/previs/plan.js';
import * as G from '../prototypes/shot-grammar/grammar.js';

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

test('drama idioms wait for tension, and the scene breaks its calm camera at most once', () => {
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
    const c = solve(r.pick.s, r.plan, p), z = sampleCamera(plan, p * n);  // keys were solved with the performance keys
    assert.ok(dist(c.pos, z.position) < 0.03, `p=${p} off by ${dist(c.pos, z.position)}`);
  }
  assert.ok(JSON.stringify(plan).length < 4096);  // the WebM title keeps the plan only in its first 8 KB
  assert.ok(!('mark' in plan));  // the 3D Stage plan has no mark field until integration
});

test('the camera must stay inside the dome, and a blocked shot says when and why', () => {
  assert.ok(inDome([0, 1.6, -2]));
  assert.ok(!inDome([0, 1.6, 1.5]) && !inDome([0, 0.1, -2]));
  assert.ok(Object.values(IDIOMS).flat().every(i => i.shot.size in FRAME_H && (!i.shot.end || i.shot.end in FRAME_H)));
  const wide = effShot(beat, { lens: 35, shot: { subj: 'actor', focus: 'face', size: 'CU', end: 'EWS', az: 150, move: 'pull', speed: 'slow' } });
  const why = whyNot(wide, actorPlan(beat));
  assert.equal(why.kind, 'dome');
  assert.match(why.text, /at \d\.\d s the camera would leave the dome/);
  assert.equal(whyNot(wide, actorPlan(beat), () => true).kind, 'set');  // something solid in the way is reported first in time
});

test('a dragged movement window reads as a speed, and the halfway point follows the curve', () => {
  const shot = { subj: 'actor', focus: 'face', size: 'MS', end: 'CU', az: 150, move: 'push' };
  assert.equal(effShot(beat, { shot }, { mlen: 0.5 }).speed, 'fast');
  assert.equal(effShot(beat, { shot }, { mlen: 1.2 }).speed, 'mid');
  assert.equal(effShot(beat, { shot }, { mlen: 4 }).speed, 'slow');
  assert.equal(tierFor({ move: 'orbit' }, 1.2), 'mid');
  const s = effShot(beat, { shot }, { start: 0.2, mlen: 3, mid: 0.3 });
  const h = halfway(s);  // half the move is done 30% into its 3 s window that starts at 1.2 s of 6 s
  assert.ok(Math.abs(h * 6 - (1.2 + 0.3 * 3)) < 0.05, `halfway at ${h * 6} s`);
});

test('the overhead drag inverts the solver: ground point back to side and shot size', () => {
  const s = effShot(beat, { shot: { subj: 'actor', focus: 'face', size: 'MCU', az: 120, move: 'static' } }), plan = actorPlan(beat);
  const c = solve(s, plan, 0), back = fromGround(s, plan, [c.pos[0], c.pos[2]]);
  assert.ok(Math.abs(back.az - 120) < 0.5, `az ${back.az}`);
  assert.equal(nearestSize(back.H, ['MS', 'MCU', 'CU']), 'MCU');
});

test('the actor mark moves the subject, a saved idiom keeps the framing, and pick changes are listed', () => {
  const moved = { ...beat, mark: [0.6, -0.8], turn: 30 }, f = framesOf(actorPlan(moved)) - 1;
  const a = actorAt(actorPlan(beat), f), b = actorAt(actorPlan(moved), f);
  assert.ok(Math.abs(b.root[0] - a.root[0] - 0.6) < 1e-9 && Math.abs(b.root[2] - a.root[2] + 0.8) < 1e-9);
  const s = effShot(beat, IDIOMS.turn[1], { az: 160, size: 'MCU', start: 0.2 });
  const saved = idiomFromShot('Mine', s);
  assert.deepEqual([saved.shot.az, saved.shot.size, saved.shot.start, saved.lens], [160, 'MCU', 0.2, 35]);
  const before = choose(SCENE, { preset: 'standard', seed: 7 }), after = choose(SCENE, { preset: 'standard', seed: 7, pins: { S02: 'Locked three-quarter' } });
  assert.deepEqual(pickChanges(before, after).find(c => c.id === 'S02').to, 'Locked three-quarter');
});

test('fine framing stays relative to the subject: a nudge moves the camera with him and reads in the words', () => {
  const b = G.SCENE.beats[1], idiom = G.IDIOMS.turn.find(i => i.name === 'Locked three-quarter');
  const plan = G.actorPlan(b), base = G.effShot(b, idiom), fine = G.effShot(b, idiom, { hk: 1.1, elev: 8, az: 143 });
  const d = s => { const c = G.solve(s, plan, 0.5); return Math.hypot(...c.pos.map((v, i) => v - c.aim[i])); };
  assert.ok(Math.abs(d(fine) / d(base) - 1.1) < 1e-9, 'x1.10 is 10% farther at the same lens');
  assert.ok(G.solve(fine, plan, 0.5).pos[1] > G.solve(base, plan, 0.5).pos[1], '8° above eye level sits higher');
  assert.match(G.words(fine), /MCU \(10% wider\), camera 8° above eye level/);
  const moved = G.actorPlan({ ...b, mark: [0.6, -0.4] }), shift = (s, p) => G.solve(s, p, 0.5).pos;
  assert.ok(Math.abs(shift(fine, moved)[0] - shift(fine, plan)[0] - 0.6) < 1e-9, 'he steps 0.6 m right, the fine-framed camera follows');
  assert.equal(G.nearestHeight(8), 'eye'); assert.equal(G.nearestHeight(20), 'high');
});

test('an over-the-shoulder frames the subject on a third with the partner\'s near shoulder in the frame', () => {
  const scene = G.RELIEF, b = G.beatOf(scene.beats.find(x => x.id === 'R02'), {}, scene), idiom = G.IDIOMS.turn.find(i => i.name === 'Over the shoulder');
  const s = G.effShot(b, idiom), plan = G.actorPlan(b), c = G.solve(s, plan, 0.5), fov = c.fov * Math.PI / 180, hfov = 2 * Math.atan(Math.tan(fov / 2) * 1280 / 704);
  const view = c.aim.map((v, i) => v - c.pos[i]), across = (p) => {  // horizontal angle of point p from the frame's centre line
    const v = p.map((x, i) => x - c.pos[i]); return Math.atan2(view[0] * v[2] - view[2] * v[0], view[0] * v[0] + view[2] * v[2]);
  };
  const B = b.partner.mark, shoulders = [-0.2, 0.2].map(o => { const ax = [B[0] - b.mark[0], B[1] - b.mark[1]], l = Math.hypot(...ax); return [B[0] - ax[1] / l * o, 1.45, B[1] + ax[0] / l * o]; });
  assert.ok(shoulders.some(p => Math.abs(across(p)) < hfov / 2), 'a shoulder of the partner is inside the frame');
  const face = Math.abs(across(c.F)) / (hfov / 2);
  assert.ok(face > 0.2 && face < 0.55, `the subject sits off centre, near a third (${face.toFixed(2)} of the half width)`);
  assert.ok(G.sideOf(plan, c.pos) === plan.side, 'and the camera keeps the scene\'s side of the line');
});

test('every shot of the two-hander keeps the camera on one side of the line, orbits included, on either side', () => {
  for (const side of [1, -1]) {
    const rows = G.choose(G.RELIEF, { scene: 'relief', side: { relief: side } }, () => false);
    for (const r of rows) for (const p of [0, 0.5, 1]) assert.equal(G.sideOf(r.plan, G.solve(r.pick.s, r.plan, p).pos), side, `${r.beat.id} ${r.pick.idiom.name} at ${p}`);
    assert.ok(!G.checks(rows).some(c => /180° line/.test(c.text)));
  }
});
