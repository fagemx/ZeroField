import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { buildStage } from '../src/previs/scene.js';
import { defaultPlan } from '../src/previs/plan.js';
import { createMotionDemoPlan } from '../src/previs/demoPlan.js';

const point = (stage, name, offset = [0, 0, 0]) => {
  let joint;
  stage.scene.traverse(o => { if (!joint && o.userData.kp === name) joint = o; });
  stage.scene.updateMatrixWorld(true);
  return joint.localToWorld(new THREE.Vector3(...offset)).toArray();
};
const distance = (a, b) => Math.hypot(...a.map((x, i) => x - b[i]));

test('retarget carries the solved toe direction onto the final rig, not only its ankle position', () => {
  const plan = { ...defaultPlan(), acts: [{ at: 0, body: 'stand' }, { at: 0.75, body: 'kneel' }], fix: {} };
  const stage = buildStage(plan), { solved } = stage.motion(plan);
  for (const f of [0, 24, 48, 72, 96]) {
    stage.pose(f, plan);
    for (const s of ['L', 'R']) assert.ok(distance(point(stage, 'ankle' + s, [0, -0.06, 0.12]), solved[f]['foot' + s]) < 0.002,
      `${s} foot agrees with the solved position on frame ${f}`);
  }
  stage.dispose();
});

test('rehearsal contact objects belong to the scene and remain opaque in the actor matte', () => {
  const plan = { ...defaultPlan(), presentation: 'rehearsal', set: 'empty', props: [{ id: 'touch-pad', shape: 'cylinder', radius: 0.1, height: 0.05, position: [0.3, 1.05, 0.2], contact: true }] };
  const stage = buildStage(plan), prop = stage.scene.getObjectByName('touch-pad');
  assert.deepEqual(prop.position.toArray(), plan.props[0].position);
  assert.equal(prop.userData.contactObject, true);
  stage.matte(true); assert.equal(prop.material.color.getHex(), 0);
  stage.matte(false); assert.notEqual(prop.material.color.getHex(), 0);
  stage.dispose();
});

test('the demonstration touches the visible pad with a fingertip throughout its hold', () => {
  const plan = createMotionDemoPlan(), stage = buildStage(plan), pad = plan.props.find(p => p.contact);
  const top = pad.position[1] + pad.height / 2;
  for (const f of [204, 216, 228, 240]) {
    stage.pose(f, plan); stage.scene.updateMatrixWorld(true);
    const fingertips = [];
    // Only the subject (first matching landmark per digit), and the final phalanx's visible tip.
    for (let digit = 1; digit <= 4; digit++) {
      let joint; stage.scene.traverse(o => { if (!joint && o.userData.kp === `f${digit}_2R`) joint = o; });
      fingertips.push(joint.localToWorld(new THREE.Vector3(0, -joint.userData.tip, 0)));
    }
    assert.ok(fingertips.some(p => Math.hypot(p.x - pad.position[0], p.z - pad.position[2]) < pad.radius && Math.abs(p.y - top) < 0.012), `visible finger on the pad at ${f}`);
  }
  stage.dispose();
});
