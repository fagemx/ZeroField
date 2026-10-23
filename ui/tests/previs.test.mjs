import test from 'node:test';
import assert from 'node:assert/strict';
import {FRAMES, defaultPlan, cameraKeys, sampleCamera, sampleActor, sampleActs, blendPose, POSES, verticalFov, describePlan, planFromSlate, DOME, framesOf} from '../src/previs/plan.js';
import * as THREE from 'three';
import {buildStage} from '../src/previs/scene.js';
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
  assert.deepEqual([one.matteCol, one.matte], [-1, null]);  // an older slate: the stage renders no matte
  const matted = {...parsed, headers: [...parsed.headers, 'Actor Matte'], rows: parsed.rows.map((row, k) => ({...row, cells: [...row.cells, {value: k ? '' : v('d')}]}))};
  const [withMatte, without] = stageShots(matted);
  assert.equal(withMatte.matteCol, 7); assert.match(withMatte.matte, /pa_d{32}$/); assert.equal(without.matte, null);
  assert.equal(benchGroup('Actor Matte'), 'control');  // a control pass on the bench, never the shot's input or output
  assert.deepEqual([withMatte.skeletonCol, withMatte.skeleton], [-1, null]);
  const posed = {...matted, headers: [...matted.headers, 'Pose Skeleton'], rows: matted.rows.map((row, k) => ({...row, cells: [...row.cells, {value: k ? '' : v('e')}]}))};
  const [withSkeleton] = stageShots(posed);
  assert.equal(withSkeleton.skeletonCol, 8); assert.match(withSkeleton.skeleton, /pa_e{32}$/);
  assert.equal(benchGroup('Pose Skeleton'), 'control');
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

test('multi-key paths flow through their middle keys; two keys stay a plain ease', () => {
  const plan = {...defaultPlan(), keys: [[0, [2, 1, -1], [0, 1.4, 0]], [48, [0, 2, -2.6], [0, 1.4, 0]], [96, [-2, 3, -1], [0, 1.3, 0]]]};
  const at = f => sampleCamera(plan, f).position;
  assert.ok(dist(at(47), at(49)) > 0.05, 'the camera is still moving as it passes the middle key');
  assert.ok(Math.abs(at(48)[0]) < 0.25, 'and it passes close to it');
  assert.deepEqual(at(96), [-2, 3, -1]);
  const two = {...defaultPlan(), keys: [[0, [0, 0, 0], [0, 1, 1]], [96, [4, 0, 0], [0, 1, 1]]]};
  assert.ok(Math.abs(sampleCamera(two, 48).position[0] - 2) < 1e-9 && sampleCamera(two, 24).position[0] < 1, 'eased in, halfway at the middle');
});

test('performance keys in a plan replace its canned action; each channel eases between the keys that set it', () => {
  const acts = [{at: 0, yaw: -1.75, reach: 0, body: 'stand'}, {at: 0.25, yaw: 0}, {at: 0.5, reach: 1.16, body: 'lean'}, {at: 0.9, body: 'kneel'}];
  const plan = {...defaultPlan(), seconds: 6, acts}, at = u => sampleActor(plan, u * 144);
  assert.equal(at(0).yaw, -1.75); assert.equal(at(0.25).yaw, 0); assert.equal(at(1).yaw, 0);
  assert.ok(Math.abs(at(0.25).reach - 0.58) < 1e-9, 'reach eases from the start key to the 0.5 key, ignoring the yaw-only key between');
  assert.ok(at(0.4).reach > 0 && at(0.4).reach < 1.16); assert.equal(at(0.6).reach, 1.16);
  assert.deepEqual(at(0.5).pose, blendPose('lean', 'kneel', 0));
  assert.ok(at(0.7).pose.drop > 0 && at(0.7).pose.drop < POSES.kneel.drop, 'halfway into the kneel the pelvis is part way down');
  assert.deepEqual(sampleActs(acts, 0.95).pose, blendPose('kneel', undefined, 0));
  const late = [{at: 0, yaw: 0}, {at: 0.5, body: 'slump'}];
  assert.ok(Object.values(sampleActs(late, 0).pose).flat().every(v => v === 0), 'standing at the start; the pose arrives by its key');
  assert.ok(sampleActs(late, 0.25).pose.spine[0] > 0 && sampleActs(late, 0.25).pose.spine[0] < POSES.slump.spine[0]);
  const room = {...plan, facing: 'room'};
  assert.equal(sampleActor(room, 144).yaw, 0, 'a keyed yaw is absolute: facing is not added');
  const bytes = muxWebM([{data: new Uint8Array(4), timestamp: 0, type: 'key'}], {width: 1280, height: 704, fps: 24, plan});
  assert.deepEqual(planFromWebM(bytes.subarray(0, 8192)).acts, acts, 'the keys ride in the WebM with the plan');
});

test('the mannequin stands in the first mannequin\'s envelope (1.93 m, ±0.34 m) and bends into its poses', () => {
  const stage = buildStage(defaultPlan()), plan = {...defaultPlan(), action: 'stand'};
  const actor = () => { stage.scene.updateMatrixWorld(true); const box = new THREE.Box3(); stage.scene.traverse(o => { if (o.isMesh && o.userData.actor) { if (o.isSkinnedMesh) o.computeBoundingBox(); box.union(new THREE.Box3().setFromObject(o)); } }); return box; };
  stage.pose(0, plan);
  const rest = actor();
  assert.ok(Math.abs(rest.max.y - 1.93) < 0.01 && Math.abs(rest.min.y) < 0.005 && Math.abs(rest.min.x + 0.34) < 0.01, 'an adult standing on the floor');
  const fingerSegments = new Map();
  stage.scene.traverse(o => { if (/^f[0-4]_[0-2][LR]$/.test(o.userData.kp || '')) fingerSegments.set(o.userData.kp, o); });
  assert.equal(fingerSegments.size, 30, 'both hands retain five articulated three-segment fingers');
  for (const [name, joint] of fingerSegments) {
    const mesh = joint.children.find(o => o.isMesh && o.userData.actor && !o.userData.outline);
    assert.ok(mesh, `${name} has visible finger geometry`);
    mesh.geometry.computeBoundingBox();
    const size = mesh.geometry.boundingBox.getSize(new THREE.Vector3());
    assert.ok(size.y > Math.max(size.x, size.z) * 1.1, `${name} is an elongated finger segment, not a ball`);
  }
  stage.pose(0, {...plan, acts: [{at: 0, body: 'kneel'}]});
  assert.ok(actor().max.y < rest.max.y - 0.3 && actor().min.y > -0.08, 'kneeling lowers him, no deeper than a shin into the floor');
  stage.pose(0, {...plan, acts: [{at: 0, body: 'lean'}]});
  assert.ok(actor().max.z > rest.max.z + 0.1, 'leaning brings the head forward');
  stage.pose(0, {...plan, acts: [{at: 0, body: 'face', reach: 1.16}]});
  assert.ok(actor().max.z > rest.max.z + 0.3, 'a reach still takes the left arm out to the console from any pose');
});

test('the pose skeleton is the mannequin\'s own joints: OpenPose order, his right on his right, no face from behind', async () => {
  const {poseKeypoints} = await import('../src/previs/skeleton.js');
  const plan = defaultPlan(), stage = buildStage(plan), f = framesOf(plan) - 1;  // S03 holds behind him, at the dial
  stage.frame(f, plan);
  const [person, ...rest] = poseKeypoints(stage.scene, stage.camera);
  assert.equal(rest.length, 0);
  assert.equal(person.body.length, 18); assert.equal(person.handR.length, 21); assert.equal(person.handL.length, 21);
  const [nose, neck, rShoulder, , rWrist, lShoulder, , lWrist] = person.body, [rEye, lEye, rEar, lEar] = person.body.slice(14);
  assert.deepEqual([nose[2], rEye[2], lEye[2]], [0, 0, 0]);  // seen from behind: no face points
  assert.ok(rEar[2] + lEar[2] >= 1);
  // From behind his right is on screen right: the reaching (right) hand is the one toward the frame's right.
  assert.ok(rShoulder[0] > lShoulder[0] && rWrist[0] > lWrist[0]);
  assert.ok(neck[0] > lShoulder[0] && neck[0] < rShoulder[0]);  // the shoulders' 3D midpoint, projected
  assert.ok(person.handR.every(([x, y]) => Math.hypot(x - rWrist[0], y - rWrist[1]) < 260));  // the hand hangs off its own wrist
  // Turned to face the camera, the face points come back and his right moves to screen left.
  stage.frame(f, {...plan, turn: 180});
  const [front] = poseKeypoints(stage.scene, stage.camera);
  assert.equal(front.body[0][2], 1);
  assert.ok(front.body[2][0] < front.body[5][0]);
});

test('face points: 68 landmarks in iBUG order, hidden from behind, moved by the performance keys\' expressions', async () => {
  const {poseKeypoints, faceLandmarks} = await import('../src/previs/skeleton.js');
  const {EXPRESSIONS} = await import('../src/previs/plan.js');
  const rest = faceLandmarks(), scream = faceLandmarks(EXPRESSIONS.scream), cry = faceLandmarks(EXPRESSIONS.cry);
  assert.equal(rest.length, 68);
  const gap = f => f[66].y - f[62].y, eyeH = f => f[37].y - f[41].y;  // inner lips apart; right eye lid to lid
  assert.ok(gap(scream) < gap(rest) - 0.025, 'a scream opens the mouth');
  assert.ok(scream[8].y < rest[8].y - 0.02, 'and drops the chin');
  assert.ok(eyeH(cry) < eyeH(rest) * 0.6 && cry[48].y < rest[48].y, 'crying squeezes the eyes and pulls the corners down');
  assert.ok(cry[21].y > rest[21].y && cry[17].y - rest[17].y < cry[21].y - rest[21].y, 'grief lifts the inner brows more than the outer');
  assert.ok(rest[36].x < rest[39].x && rest[39].x < rest[42].x && rest[42].x < rest[45].x, 'right eye outer to inner, then left eye inner to outer');
  // Keys blend the expression like a pose, from neutral before the first key.
  assert.ok(Object.values(sampleActs([{at: 0.5, face: 'scream'}], 0).face).every(v => v === 0));
  assert.equal(sampleActs([{at: 0.5, face: 'scream'}], 0.25).face.jaw.toFixed(2), '0.50');
  // Drawn only while the face is toward the camera.
  const plan = {...defaultPlan(), acts: [{at: 0, face: 'scream'}]}, stage = buildStage(plan), f = framesOf(plan) - 1;
  stage.frame(f, plan);
  assert.ok(poseKeypoints(stage.scene, stage.camera)[0].face.every(p => p[2] === 0), 'S03 from behind: no face points');
  stage.frame(f, {...plan, turn: 180});
  const face = poseKeypoints(stage.scene, stage.camera)[0].face;
  assert.equal(face.filter(p => p[2]).length, 68);
  assert.ok(face[8][1] > face[30][1] && face[30][1] > face[27][1], 'on screen the chin is below the nose tip, the nose tip below the bridge');
});

test('2.5D parallax cards: defaults by role, far to near, never in defaultPlan; billboards turn their front to the camera', async () => {
  const {PARALLAX_DEFAULTS, parallaxLayers, billboardYaw} = await import('../src/previs/plan.js');
  assert.deepEqual(Object.keys(defaultPlan()), ['set', 'move', 'lens', 'action', 'facing', 'mood', 'seconds', 'keys'], 'layers, beacon and pins stay optional');
  assert.deepEqual(parallaxLayers(defaultPlan()), []);
  const cards = parallaxLayers({...defaultPlan(), set: 'parallax'});
  assert.deepEqual(cards, PARALLAX_DEFAULTS); cards[0].z = 99; assert.equal(PARALLAX_DEFAULTS[0].z, 4.8, 'a copy');
  const custom = parallaxLayers({set: 'observatory', layers: [{id: 'near', src: '/x.png'}, {id: 'sky', role: 'far', z: 9}]});
  assert.deepEqual(custom.map(l => [l.id, l.z, l.src ?? null]), [['sky', 9, null], ['near', -0.7, '/x.png']]);
  // A card's front is -z: turned by yaw it is (-sin, -cos); it must point at the camera wherever an orbit or track takes it.
  for (const move of ['orbit', 'track', 'pushin']) for (const f of [0, 48, 96]) for (const card of [[0, 1.8, 4.8], [0.5, 1.1, -0.7]]) {
    const eye = sampleCamera({...defaultPlan(), move}, f).position, yaw = billboardYaw(eye, card);
    const to = [eye[0] - card[0], eye[2] - card[2]], n = Math.hypot(...to);
    assert.ok(Math.abs(-Math.sin(yaw) * to[0] / n - Math.cos(yaw) * to[1] / n - 1) < 1e-9, `${move} f${f}`);
  }
});

test('the parallax set builds its cards facing the shot camera, without the sun; the observatory sun can be switched off', () => {
  const plan = {...defaultPlan(), set: 'parallax', move: 'orbit'}, stage = buildStage(plan);
  const find = (s, test) => { const out = []; s.scene.traverse(o => { if (test(o)) out.push(o); }); return out; };
  const cards = find(stage, o => o.userData.parallaxLayer), [beacon] = find(stage, o => o.userData.beacon);
  assert.deepEqual(cards.map(c => c.userData.parallaxLayer.id), ['far', 'mid', 'near']);
  assert.ok(cards.every(c => !c.castShadow), 'flat cards cast no shadows');
  for (const f of [0, 48, 96]) {
    stage.frame(f, plan); stage.scene.updateMatrixWorld(true);
    assert.equal(beacon.visible, false);
    for (const card of cards.slice(0, 2)) {  // the far and mid cards: front (-z in world) toward the camera
      const front = card.getWorldDirection(new THREE.Vector3()).negate(), to = stage.camera.position.clone().sub(card.position).setY(0).normalize();
      assert.ok(front.dot(to) > 0.999, `${card.userData.parallaxLayer.id} f${f}`);
    }
  }
  const far = cards[0].geometry; far.computeBoundingBox();
  assert.ok(far.boundingBox.max.x - far.boundingBox.min.x > 10, 'the far card fills a 35 mm frame from the wide key');
  stage.matte(true); assert.ok(cards.every(c => !c.visible), 'the actor matte drops the cards'); stage.matte(false);
  const dome = buildStage(defaultPlan()), [sun] = find(dome, o => o.userData.beacon);
  dome.frame(96, defaultPlan()); assert.equal(sun.visible, true, 'on by default after the dial turn');
  dome.frame(96, {...defaultPlan(), beacon: false}); assert.equal(sun.visible, false);
});

test('a shot\'s @SET image becomes its stage setAsset (the parallax far card)', () => {
  const img = '/projects/api/demo/assets/pa_' + 'f'.repeat(32);
  const parsed = {headers: ['Shot', 'Action & Audio Prompt', 'Previs'], table: {attrs: {column_types: ['text', 'text', 'video']}},
    rows: [{rid: 'a', cells: ['S01', 'Kael at the glass @CAST-01 @SET-01', ''].map(value => ({value}))}, {rid: 'b', cells: ['S02', 'No set tag', ''].map(value => ({value}))}]};
  const [one, two] = stageShots(parsed, parsed.rows, {'SET-01': {id: 'SET-01', media: {kind: 'image', url: img}}});
  assert.deepEqual(one.setAsset, {id: 'SET-01', url: img}); assert.equal(two.setAsset, null);
  assert.equal(stageShots(parsed)[0].setAsset, null, 'no lookup, no image');
});

test('direct-motion-space pins land exactly on their frames, keep the limbs\' bone lengths, and the mannequin follows', async () => {
  const {MSFLOW_JOINTS, solvePinnedXYZ, solveLimbIK} = await import('../src/previs/plan.js');
  assert.equal(MSFLOW_JOINTS.length, 22);
  const plan = {...defaultPlan(), action: 'stand'}, stage = buildStage(plan), {base} = stage.motion(plan), F = base.length;
  assert.deepEqual(Object.keys(base[0]).sort(), [...MSFLOW_JOINTS].sort());
  const pins = [{at: 0, joint: 'pelvis', pos: [0, 0.98, -1.8]}, {at: 0.45, joint: 'wristL', pos: [-0.25, 1.03, 0.56]}, {at: 0.85, joint: 'head', pos: [0, 1.65, -0.15]},
    {at: 0.2, joint: 'ankleR', pos: [0.15, 0.12, -1.1]}, {at: 0.7, joint: 'ankleR', pos: [0.2, 0.15, 0.1]}];  // two steps of one foot
  const frozen = JSON.stringify(base), solved = solvePinnedXYZ(base, pins);
  assert.equal(JSON.stringify(base), frozen, 'the input motion is not changed');
  const dist = (a, b) => Math.hypot(...a.map((v, i) => v - b[i]));
  for (const p of pins) assert.ok(dist(solved[Math.round(p.at * (F - 1))][p.joint], p.pos) < 1e-6, `${p.joint} at ${p.at}`);
  for (const f of [0, 20, 43, 67, 82, 96]) for (const [a, b] of [['shoulderL', 'elbowL'], ['elbowL', 'wristL'], ['hipR', 'kneeR'], ['kneeR', 'ankleR']])
    assert.ok(Math.abs(dist(solved[f][a], solved[f][b]) - dist(base[f][a], base[f][b])) < 1e-6, `${a}-${b} keeps its length on frame ${f}`);
  assert.ok(dist(solved[43].shoulderL, base[43].shoulderL) > 0.05, 'the dial is out of the standing arm\'s reach: the upper body leans in');
  const local = solvePinnedXYZ(base, [{at: 0, joint: 'wristR', pos: [0.4, 1.2, 0.3], radius: 0.1}]);
  assert.ok(MSFLOW_JOINTS.every(j => dist(local[96][j], base[96][j]) < 1e-6), 'a pin fades out in time');
  // Two-bone IK: the law of cosines keeps both lengths; a target out of reach straightens the limb toward it.
  const ik = solveLimbIK([0, 0, 0], [0, -0.3, 0.1], [0, -0.4, 0.2], 0.3, 0.28), side = m => -0.4 * m[2] - 0.2 * m[1];  // which side of the root-target line
  assert.ok(Math.abs(dist([0, 0, 0], ik.mid) - 0.3) < 1e-9 && Math.abs(dist(ik.mid, [0, -0.4, 0.2]) - 0.28) < 1e-9);
  assert.ok(side(ik.mid) * side([0, -0.3, 0.1]) > 0, 'it bends the way the current middle joint does');
  assert.ok(Math.abs(dist([0, 0, 0], solveLimbIK([0, 0, 0], [0, -0.3, 0], [0, -2, 0], 0.3, 0.28).end) - 0.58) < 1e-9);
  // The mannequin: its hand is on the dial and its pelvis on the mark at the pinned frames.
  const pinned = {...plan, pins}, at = kp => { let o; stage.scene.traverse(x => { if (x.userData.kp === kp && !o) o = x; }); return o.getWorldPosition(new THREE.Vector3()).toArray(); };
  stage.pose(43, pinned); stage.scene.updateMatrixWorld(true); assert.ok(dist(at('wristL'), pins[1].pos) < 1e-3, 'hand on the dial');
  stage.pose(0, pinned); stage.scene.updateMatrixWorld(true); assert.ok(dist(at('pelvis'), pins[0].pos) < 1e-3, 'pelvis on its mark');
});

test('from behind the skeleton keeps a crown point, so looking up and slumping read differently; the body stays 18 points', async () => {
  const {poseKeypoints} = await import('../src/previs/skeleton.js');
  const crownAbove = body => {
    const plan = {...defaultPlan(), acts: [{at: 0, body}]}, stage = buildStage(plan);
    stage.frame(96, plan);
    const [person] = poseKeypoints(stage.scene, stage.camera);
    assert.equal(person.body.length, 18); assert.equal(person.body[0][2], 0, 'no nose from behind'); assert.equal(person.crown[2], 1, body);
    return person.body[1][1] - person.crown[1];  // pixels the crown sits above the neck
  };
  assert.ok(crownAbove('lookup') > crownAbove('slump') + 30, 'a head thrown back puts the crown higher over the neck than a slump');
});

// SPEC_12: physical fixes and motion QA on the stage's own frames (an adult standing at the mark, clean to start with).
const standing = () => buildStage(defaultPlan()).motion({...defaultPlan(), action: 'stand'}).base;
const copy = frames => frames.map(fr => Object.fromEntries(Object.entries(fr).map(([j, v]) => [j, [...v]])));
const group = (qa, kind, subject) => qa.groups.find(g => g.kind === kind && (!subject || g.subject === subject));

test('fix.ground lifts an ankle in the floor back onto its sole; the QA names the frame, the cause and the fix', async () => {
  const {applyMotionFixes, auditMotion, ANKLE_FLOOR_Y} = await import('../src/previs/plan.js');
  const base = standing(), shin = dist(base[0].kneeL, base[0].ankleL);
  assert.equal(auditMotion(base, {action: 'stand'}).ok, true, 'the standing mannequin is clean');
  const sunk = copy(base);
  for (let f = 40; f <= 50; f++) { const dy = sunk[f].ankleL[1] + 0.05; sunk[f].ankleL[1] -= dy; sunk[f].footL[1] -= dy; }  // ankle at y = -0.05
  const qa = auditMotion(sunk, {action: 'stand'}), ground = group(qa, 'GROUND', 'ankleL');
  assert.equal(qa.ok, false); assert.ok(qa.cost > 0);
  assert.deepEqual([ground.count, ground.first, ground.last, ground.limit], [11, 40, 50, 0.005]);
  assert.ok(ground.worst > 0.12 && ground.worstFrame >= 40 && ground.worstFrame <= 50);
  assert.match(ground.cause, /action stand at f\d+/); assert.match(ground.hint, /^Enable fix\.ground or lift pelvis \+0\.12\dm at f\d+$/);
  const {frames, fixed} = applyMotionFixes(sunk, {ground: true}, {action: 'stand'});
  assert.equal(fixed.ground, 11);
  assert.ok(frames.every(fr => fr.ankleL[1] >= ANKLE_FLOOR_Y - 1e-9), 'every ankle back on its sole');
  assert.ok(frames.every(fr => Math.abs(dist(fr.kneeL, fr.ankleL) - shin) < 1e-6), 'the knee follows by IK: the shin keeps its length');
  assert.equal(group(auditMotion(frames, {action: 'stand'}), 'GROUND'), undefined);
  assert.equal(sunk[45].ankleL[1].toFixed(2), '-0.05', 'the input is not changed');
  assert.deepEqual(applyMotionFixes(sunk, false).fixed, {ground: 0, slide: 0, penetration: 0, retime: 0});
});

test('fix.slide locks a planted foot that drifts, and Auto-Fix cleans the canned turn-and-reach pivoting feet', async () => {
  const {applyMotionFixes, auditMotion} = await import('../src/previs/plan.js');
  const drifting = copy(standing()), start = drifting[0].ankleR;
  for (let f = 30; f < drifting.length; f++) {  // 4 cm out to the side over 30 frames while standing on it
    const dx = 0.04 * Math.min(1, (f - 30) / 30);
    drifting[f].ankleR[0] += dx; drifting[f].footR[0] += dx;
  }
  const slide = group(auditMotion(drifting, {action: 'stand'}), 'SLIDE', 'footR');
  assert.ok(slide && Math.abs(slide.worst - 0.04) < 1e-3 && slide.limit === 0.015 && slide.worstFrame >= 60, JSON.stringify(slide));
  assert.match(slide.hint, /^Enable fix\.slide to lock planted foot at f\d+$/);
  const {frames, fixed} = applyMotionFixes(drifting, {slide: true}, {action: 'stand'});
  assert.ok(fixed.slide >= 60);
  assert.ok(frames.every(fr => Math.hypot(fr.ankleR[0] - start[0], fr.ankleR[2] - start[2]) < 1e-4), 'the ankle stays on its first spot');
  assert.equal(auditMotion(frames, {action: 'stand'}).ok, true);
  // The default shot turns him on the spot: both feet orbit the pelvis. Auto-Fix plants them and steps when it must.
  const stage = buildStage(defaultPlan()), raw = stage.motion(defaultPlan()).qa;
  assert.deepEqual(raw.groups.map(g => g.kind + ':' + g.subject).sort(), ['SLIDE:footL', 'SLIDE:footR']);
  assert.match(group(raw, 'SLIDE').cause, /^action turnreach at f\d+$/);
  const fixedShot = stage.motion({...defaultPlan(), fix: {ground: true, slide: true, penetration: true}});
  assert.equal(fixedShot.qa.ok, true, JSON.stringify(fixedShot.qa.groups)); assert.ok(fixedShot.fixed.slide > 0);
});

test('fix.penetration pushes a hand pinned into the console back out over its top; the arm keeps its length', async () => {
  const {applyMotionFixes, auditMotion, SCENE_BOXES} = await import('../src/previs/plan.js');
  const plan = {...defaultPlan(), action: 'stand', pins: [{at: 0.5, joint: 'wristL', pos: [-0.25, 0.9, 0.66], radius: 0.08}]};
  const {solved, base} = buildStage(plan).motion(plan), box = SCENE_BOXES.console;
  const inBox = p => p.every((v, i) => v > box.min[i] + 0.01 && v < box.max[i] - 0.01);
  assert.ok(inBox(solved[48].wristL), 'the pin puts the hand inside the console');
  const qa = auditMotion(solved, plan), hit = group(qa, 'PENETRATION', 'wristL');
  assert.ok(hit && hit.worstFrame >= 44 && hit.worstFrame <= 52 && hit.limit === 0.01, JSON.stringify(qa.groups));
  assert.match(hit.cause, /pin wristL at f48 into console/); assert.match(hit.hint, /^Enable fix\.penetration or move hand \[0, \+0\.\d+, -0\.\d+\] m out of console at f\d+$/);
  assert.equal(group(auditMotion(solved, {...plan, set: 'empty'}), 'PENETRATION'), undefined, 'no console on the empty stage');
  const {frames, fixed} = applyMotionFixes(solved, {penetration: true}, plan);
  assert.ok(fixed.penetration > 0);
  for (const fr of frames) for (const j of ['wristL', 'elbowL']) assert.ok(!fr[j].every((v, i) => v > box.min[i] + 0.005 && v < box.max[i] - 0.005), `${j} out of the console`);
  assert.ok(frames[48].wristL[1] >= box.max[1], 'out over the top, the nearest way out');
  const upper = dist(base[0].shoulderL, base[0].elbowL), fore = dist(base[0].elbowL, base[0].wristL);
  assert.ok(Math.abs(dist(frames[48].shoulderL, frames[48].elbowL) - upper) < 1e-6 && Math.abs(dist(frames[48].elbowL, frames[48].wristL) - fore) < 1e-6);
  assert.equal(group(auditMotion(frames, plan), 'PENETRATION'), undefined);
});

test('motion QA without fixes reports ground, slide, penetration and reach with the worst frame, cause and hint', async () => {
  const {auditMotion} = await import('../src/previs/plan.js');
  // A kneel keyed in at 0.75: the right foot ends in the floor and both feet are dragged into the pose.
  const kneel = {...defaultPlan(), acts: [{at: 0, body: 'stand'}, {at: 0.75, body: 'kneel'}]}, stage = buildStage(kneel);
  const qa = stage.motion(kneel).qa, ground = group(qa, 'GROUND', 'ankleR');
  assert.ok(ground && ground.worst > 0.03 && ground.last === 96); assert.equal(ground.cause, 'pose kneel at f72');
  assert.ok(group(qa, 'SLIDE', 'footR'));
  assert.equal(stage.motion({...kneel, fix: {}}).qa.ok, true, 'Auto-Fix clears both');
  // The pelvis pinned on its mark, the right hand pinned far past the console: the lean cannot reach it.
  const far = {...defaultPlan(), action: 'stand', pins: [{at: 0, joint: 'pelvis', pos: [0, 0.9927, 0], radius: 2}, {at: 0.5, joint: 'wristR', pos: [0.3, 1.2, 1.6]}]};
  const reach = group(auditMotion(stage.motion(far).solved, far), 'REACH', 'wristR');
  assert.ok(reach && reach.worstFrame === 48 && reach.worst > 0.2 && reach.limit === 0.015, JSON.stringify(reach));
  assert.equal(reach.cause, 'pin wristR at f48');
  assert.match(reach.hint, /^Move actor mark \[0\.\d+, 0\.\d+\] m toward target or add spine lean at f48$/);
  assert.ok(qa.cost > 0 && qa.groups.length === new Set(qa.groups.map(g => g.kind + g.subject)).size, 'one group per kind and joint');
});

test('skills compile to keys, pins and checks; the search resolves an open walk length to a clean reach for the dial', async () => {
  const {compileMotionSkills, searchMotionPlan, auditMotion, SCENE_ANCHORS} = await import('../src/previs/plan.js');
  const plan = {...defaultPlan(), action: 'stand', use: [
    {skill: 'walkTo', args: {from: [0, -1.6], to: [0, {range: [-1.4, 0.2]}]}},
    {skill: 'reachGrip', args: {anchor: 'dial'}}]};
  const {acts, pins, checks} = compileMotionSkills(plan);
  assert.deepEqual([...new Set(acts.filter(a => a.body).map(a => a.body))], ['stand', 'walk']);
  assert.deepEqual([...new Set(pins.map(p => p.joint))].sort(), ['ankleL', 'ankleR', 'wristL']);
  assert.ok(checks.planted.length >= 4 && checks.planted.every(c => c.to >= c.from));
  const [contact] = checks.contacts;
  assert.deepEqual([contact.joint, contact.anchor, contact.pos, contact.to - contact.from], ['wristL', 'dial', SCENE_ANCHORS.dial.pos, 24]);
  assert.ok(acts.every(a => a.at >= 0 && a.at <= 1) && pins.every(p => p.at >= 0 && p.at <= 1));
  const stage = buildStage(plan), evaluate = p => stage.motion(p).qa;
  assert.ok(evaluate(plan).cost > 0, 'the midpoint stops too far back: the body is dragged to the dial');
  const found = searchMotionPlan(plan, evaluate);
  assert.equal(found.cost, 0); assert.equal(found.qa.ok, true); assert.ok(found.evals >= 2 && found.evals <= 24);
  const z = found.plan.use[0].args.to[1];
  assert.ok(Number.isFinite(z) && z >= -1.4 && z <= 0.2, String(z));
  assert.doesNotMatch(JSON.stringify(found.plan), /range/);
  const {solved} = stage.motion(found.plan), F = solved.length, [grip] = compileMotionSkills(found.plan).checks.contacts;
  for (let f = grip.from; f <= grip.to; f++) assert.ok(dist(solved[f].wristL, SCENE_ANCHORS.dial.pos) < 1e-6, `hand on the dial at f${f}`);
  assert.ok(Math.abs(solved[F - 1].pelvis[2] - z) < 0.05 && Math.abs(solved[F - 1].pelvis[0]) < 0.05, 'the walk ends on the found spot');
  const strides = checks.planted.filter(c => c.joint === 'ankleL').map(c => c.pos[2]);
  assert.ok(strides.every((v, i) => i === 0 || v > strides[i - 1]), 'the left foot lands further on each step');
  assert.equal(auditMotion(solved, found.plan).ok, true);
  assert.equal(searchMotionPlan({...defaultPlan(), action: 'stand'}, () => 0).evals, 1, 'no open values: one evaluation');
});

test('fix.retime smooths a one-frame jump that the QA flags as a pop', async () => {
  const {applyMotionFixes, auditMotion} = await import('../src/previs/plan.js');
  const jump = copy(standing());
  for (let f = 50; f < jump.length; f++) for (const j in jump[f]) jump[f][j][0] += 0.5;  // the whole body teleports 0.5 m
  const pop = group(auditMotion(jump, {action: 'stand'}), 'POP');
  assert.ok(pop && pop.worstFrame === 50 && Math.abs(pop.worst - 0.5) < 1e-3);
  const {frames, fixed} = applyMotionFixes(jump, {ground: false, slide: false, penetration: false, retime: true});
  assert.equal(fixed.retime, 4);
  assert.equal(group(auditMotion(frames, {action: 'stand'}), 'POP'), undefined);
  assert.deepEqual([frames[47].pelvis, frames[52].pelvis], [jump[47].pelvis, jump[52].pelvis], 'the window\'s ends are kept');
});
