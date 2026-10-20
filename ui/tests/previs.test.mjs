import test from 'node:test';
import assert from 'node:assert/strict';
import {FRAMES, defaultPlan, cameraKeys, sampleCamera, sampleActor, verticalFov, describePlan, planFromSlate, DOME, framesOf} from '../src/previs/plan.js';
import {benchGroup, stageShots} from '../src/studioModel.js';
import {muxWebM, planFromWebM} from '../src/previs/webm.js';

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
  const room = {...plan, facing: 'room'};  // turned to the camera side: same gesture, half a turn
  for (const f of [0, 40, 96]) assert.ok(Math.abs(sampleActor(room, f).yaw - sampleActor(plan, f).yaw - Math.PI) < 1e-9);
  const walk = {...plan, action: 'walkin'};
  assert.deepEqual([sampleActor(walk, 0).back, sampleActor(walk, 96).back], [2.2, 0]);
  assert.deepEqual([sampleActor({...walk, facing: 'room'}, 0).back, sampleActor({...walk, facing: 'room'}, 96).back], [0, 2.2]);
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

test('a shot starts from its slate: Camera Motion, the Optical Rig lens and the action', () => {
  const s01 = planFromSlate({motion: 'Slow Dolly Push-In', rig: 'ARRI Alexa 65 / 35mm Anamorphic', action: 'Establish the empty observatory as Kael enters.'});
  assert.deepEqual([s01.move, s01.lens, s01.action], ['pushin', 35, 'walkin']);
  const s02 = planFromSlate({motion: 'Static Tripod', rig: 'RED V-Raptor / 85mm Prime', action: 'Kael notices the analog recorder.'});
  assert.deepEqual([s02.move, s02.lens, s02.action], ['static', 85, 'stand']);
  const s05 = planFromSlate({motion: 'Tracking Shot', rig: '40mm', action: 'He turns the brass dial.'});
  assert.deepEqual([s05.move, s05.lens, s05.action], ['track', 35, 'turnreach']);
  assert.equal(planFromSlate({motion: 'Pull-out reveal'}).move, 'pullout');
  assert.deepEqual(planFromSlate(), {...defaultPlan(), action: 'stand'});
});

test('the rendered previs carries its plan, and other files read as no plan', () => {
  const chunks = [{data: new Uint8Array([1, 2]), timestamp: 0, key: true}];
  const plan = {...defaultPlan(), move: 'orbit', lens: 85, keys: [[0, [1, 2, 3], [0, 1, 0]], [96, [3, 2, 1], [0, 1, 0]]]};
  assert.deepEqual(planFromWebM(muxWebM(chunks, {width: 1280, height: 704, fps: 24, plan})), plan);
  assert.equal(planFromWebM(muxWebM(chunks, {width: 1280, height: 704, fps: 24})), null);
  assert.equal(planFromWebM(new Uint8Array([0x7b, 0xa9, 0x01, 0, 0, 0, 0, 0, 0, 3, 0x61, 0x62, 0x63, 0])), null);
});

test('stage shots: rows of a slate with a Previs column, with keyframe, previs and slate text', () => {
  const v = id => `[video](/projects/api/demo/assets/pa_${id.repeat(32)})`, i = id => `![Image](/projects/api/demo/assets/pa_${id.repeat(32)})`;
  const parsed = {headers: ['Shot', 'Optical Rig (Camera & Lens)', 'Camera Motion', 'Action & Audio Prompt', 'Keyframe', 'Cinema Shot', 'Previs'],
    table: {attrs: {column_types: ['text', 'text', 'text', 'text', 'image', 'video', 'video']}},
    rows: [{rid: 'a', cells: ['S01', '35mm', 'Push-In', 'Kael enters', i('a'), v('b'), v('c')].map(value => ({value}))},
           {rid: 'b', cells: ['S02', '85mm', 'Static', 'He waits', '', '', ''].map(value => ({value}))}]};
  const [one, two] = stageShots(parsed);
  assert.deepEqual([one.rid, one.r, one.shot, one.previsCol], ['a', 0, 'S01', 6]);
  assert.match(one.previs, /pa_c{32}$/); assert.match(one.keyframe, /pa_a{32}$/);
  assert.deepEqual(one.slate, {motion: 'Push-In', rig: '35mm', action: 'Kael enters'});
  assert.deepEqual([two.previs, two.keyframe, two.r], [null, null, 1]);
  assert.deepEqual(stageShots(parsed, [parsed.rows[1]]).map(s => s.r), [1]);  // a filtered view keeps table row indexes
  assert.deepEqual(stageShots({...parsed, headers: parsed.headers.slice(0, 6).concat('Notes')}), []);
});

test('a longer lens dollies the preset back along its line of sight and never leaves the dome', () => {
  const at = (move, lens) => cameraKeys({...defaultPlan(), move, lens});
  const [[, pos35, aim35]] = at('static', 35), [[, pos85, aim85]] = at('static', 85);
  assert.deepEqual(aim85, aim35);
  assert.ok(Math.abs(dist(pos85, aim85) / dist(pos35, aim35) - 85 / 35) < 1e-9, 'static 85mm holds the 35mm shot size');
  for (const move of ['pushin', 'pullout', 'orbit', 'crane', 'track', 'static']) for (const lens of [24, 35, 50, 85]) {
    for (const [, p] of at(move, lens)) {
      const d = Math.hypot(p[0] - DOME.x, p[2] - DOME.z);
      assert.ok(p[1] >= 0.3 && d <= DOME.floor + 1e-9, `${move} ${lens}mm key ${p} stays on the open floor`);
    }
  }
  assert.ok(dist(at('pushin', 85)[0][1], at('pushin', 85)[0][2]) > dist(at('pushin', 35)[0][1], at('pushin', 35)[0][2]));
  const framed = {...defaultPlan(), lens: 85, keys: [[0, [1, 2, 3], [0, 1, 0]], [96, [3, 2, 1], [0, 1, 0]]]};
  assert.deepEqual(cameraKeys(framed), framed.keys);  // the user's framed keys are never moved
});

test('a longer shot plays the same blocking on more frames (LTX 8n+1: 4, 6 or 8 seconds)', () => {
  assert.deepEqual([framesOf(defaultPlan()), framesOf({seconds: 6}), framesOf({seconds: 8}), framesOf({seconds: 5}), framesOf({})], [97, 145, 193, 97, 97]);
  const four = defaultPlan(), six = {...four, seconds: 6};
  assert.deepEqual(sampleCamera(six, 144).position, cameraKeys(six).at(-1)[1]);  // the end key lands on the last frame
  assert.deepEqual(sampleCamera(six, 72), sampleCamera(four, 48));                // halfway is halfway
  assert.deepEqual(sampleActor(six, 66), sampleActor(four, 44));                   // the reach lands at the same point of the shot
  assert.match(describePlan(six), /35mm, 6 s/);
});
