import test from 'node:test';
import assert from 'node:assert/strict';
import { BEAT_STORY, checkPerformance, levels, levelLines, parseWriter, perfOf, samplePerf, segments, templateSheet, writeScene, writeVersions, writtenSheet } from '../prototypes/shot-grammar/perf.js';
import { sampleActor } from '../src/previs/plan.js';

test('the default performance keys replay the 3D Stage turn-and-reach exactly', () => {
  const plan = { action: 'turnreach', facing: 'console', seconds: 4 }, acts = BEAT_STORY.S04.acts.map(k => ({ ...k, hands: k.hands === 'record' ? 'dial' : k.hands }));
  for (const f of [0, 10, 22, 30, 39, 44, 60, 96]) {
    const a = sampleActor(plan, f), b = samplePerf(acts, f / 96);
    assert.ok(Math.abs(a.yaw - b.yaw) < 1e-9 && Math.abs(a.reach - b.reach) < 1e-9 && Math.abs(a.back - b.back) < 1e-9, `frame ${f}`);
  }
});

test('the beat sheet is cut at the keys that carry text and ends with the line and the sound', () => {
  const segs = segments(BEAT_STORY.S03.acts, 6);
  assert.deepEqual(segs.map(s => [s.t0.toFixed(1), s.t1.toFixed(1)]), [['0.0', '1.4'], ['1.4', '2.8'], ['2.8', '4.5'], ['4.5', '6.0']]);
  const L = levels({}, perfOf(null, 'reveal')), sheet = templateSheet(segs, L, BEAT_STORY.S03);
  assert.match(sheet, /^0\.0–1\.4s: He stands turned/);
  assert.match(sheet, /Performance: natural; upper body\./);
  assert.match(sheet, /Sound: the click of the dial/);
  const six = writtenSheet(segments(BEAT_STORY.S06.acts, 4), ['a', 'b'], BEAT_STORY.S06);
  assert.match(six, /Kael says: "This is Kael\. I hear you\."/);
});

test('playing bigger than the previs relaxes "follow the pose" to "blocking only" unless the director chose', () => {
  const decl = perfOf(null, 'turn');  // subtle, up to open, face only
  assert.equal(levels({}, decl).fit, 'pose');
  const big = levels({ scale: 'heightened' }, decl);
  assert.deepEqual([big.beyond, big.fit, big.fitAuto], [true, 'blocking', true]);
  assert.equal(levels({ scale: 'heightened', fit: 'pose' }, decl).fit, 'pose');
  assert.equal(levels({ body: 'full' }, decl).beyond, true);
});

test('checks catch camera words, the wrong size, the wrong body range and a missing colour', () => {
  const segs = segments(BEAT_STORY.S03.acts, 6), story = BEAT_STORY.S03;
  const L = (p = {}) => levels(p, perfOf(null, 'reveal'));
  const clean = ['He stands at the glass, listening, as if the storm might answer.', 'He turns from the glass toward the console, breath held.',
    'His hand finds the brass dial and turns it; far beyond the glass a beacon blinks on.', 'He freezes, eyes locked on the light, as if afraid to blink.'];
  assert.ok(checkPerformance(clean, { segs, L: L(), story }).ok);
  const r1 = checkPerformance([clean[0] + ' The camera pushes in.', ...clean.slice(1)], { segs, L: L(), story });
  assert.match(r1.byShot[0].join(), /camera word/);
  const acting = ['He tilts his head at the glass, listening.', 'He pulls back his hand and turns from the glass toward the console.', clean[2], 'He cranes his neck, eyes on the light.'];
  assert.ok(!checkPerformance(acting, { segs, L: L(), story }).byShot[0] && !checkPerformance(acting, { segs, L: L(), story }).byShot[1], 'acting verbs are not camera words');
  assert.match(checkPerformance([clean[0], clean[1], clean[2], 'He freezes in a low angle close-up.'], { segs, L: L(), story }).byShot[3].join(), /camera word/);
  assert.match(checkPerformance(clean, { segs, L: L({ scale: 'heightened' }), story }).byShot[-1].join(), /nothing big/);
  const faint = [clean[0], clean[1], clean[2], 'He barely reacts to the light.'];
  assert.match(checkPerformance(faint, { segs, L: L({ scale: 'open' }), story }).byShot[-1].join(), /written small: barely/);
  const walks = [clean[0], clean[1], clean[2], 'He walks to the glass.'];
  assert.match(checkPerformance(walks, { segs, L: L({ body: 'face' }), story }).byShot[-1].join(), /face only but it has: walks/);
  assert.ok(!checkPerformance(clean, { segs, L: L({ body: 'face' }), story }).byShot[-1], 'the blocked turn itself is allowed');
  assert.match(checkPerformance(clean, { segs, L: L({ color: 'tears' }), story }).byShot[-1].join(), /colour is tears/);
  const back = ['seen from behind', 'seen in profile', 'seen from behind', 'seen from behind'];
  assert.match(checkPerformance([clean[0], clean[1], clean[2], 'He turns round to face us, eyes wide.'], { segs, L: L(), story, facing: back }).byShot[3].join(), /seen from behind/);
  assert.match(checkPerformance(clean, { segs, L: L(), story, facing: back }).byShot[3].join(), /describes his eyes/, 'no face from behind');
  const still = [clean[0], clean[1], clean[2], 'He freezes, head tilted toward the light, shoulders locked.'];
  assert.ok(!checkPerformance(still, { segs, L: L(), story, facing: back }).byShot[3], 'freezing with his back to us is fine');
  const noDial = [clean[0], clean[1], 'He reaches out; far beyond the glass a beacon blinks on.', clean[3]];
  assert.match(checkPerformance(noDial, { segs, L: L(), story }).byShot[-1].join(), /missing "dial"/);
});

test('a thinking model\'s answer is read after its reasoning', () => {
  assert.deepEqual(parseWriter('<think>{"draft": 1} hmm</think>\n{"shots": [{"id": "S03", "segments": ["a"]}]}'), { shots: [{ id: 'S03', segments: ['a'] }] });
  assert.equal(parseWriter('no json here'), null);
});

test('a beat that fails the checks is rewritten once with its issues; one that fails twice stays on the template', async () => {
  const beat = id => { const segs = segments(BEAT_STORY[id].acts, 6), L = levels({}, perfOf(null, 'reveal'));
    return { id, title: id, seconds: 6, camera: 'Push in', visible: 'his face', levelLines: levelLines(L), segs, story: BEAT_STORY[id], L }; };
  const good = ['He stands at the glass, listening.', 'He turns from the glass toward the console.', 'His hand finds the dial and turns it; far beyond the glass a beacon blinks on.', 'He freezes, eyes on the light.'];
  const prompts = [];
  const ask = async p => { prompts.push(p);
    return prompts.length === 1 ? JSON.stringify({ shots: [{ id: 'S01', segments: entry }, { id: 'S03', segments: good.map((x, i) => i ? x : x + ' The camera pushes in.') }, { id: 'S05', segments: ['a'] }] })
      : `<think>fixing</think>${JSON.stringify({ shots: [{ id: 'S03', segments: good }] })}`; };
  const entry = ['He comes in out of the rain toward the console.', 'He stops at his station.', 'He lays a hand on the console.'];
  const out = await writeScene({ title: 'T', premise: 'P' }, [beat('S01'), beat('S03'), beat('S05')], ask);
  assert.equal(prompts.length, 2);
  assert.match(prompts[1], /Your last attempt failed these checks, fix them: segment 1: camera word/);
  assert.ok(!prompts[1].includes('Shot S01') && prompts[1].includes('Shot S05'), 'only the failures are asked again');
  assert.deepEqual(out.S01, { texts: entry, issues: [] });
  assert.deepEqual(out.S03, { texts: good, issues: [] });
  assert.equal(out.S05.texts, null);
  const v = await writeVersions({ title: 'T', premise: 'P' }, beat('S03'), async () => JSON.stringify({ versions: [{ label: 'Held breath', segments: good }, { label: 'Short', segments: ['x'] }] }));
  assert.deepEqual(v.map(x => [x.label, x.issues.length]), [['Held breath', 0]]);
});
