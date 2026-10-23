import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { defaultPlan, framesOf, motionPlan, sampleActor, compileMotionSkills } from '../src/previs/plan.js';
import { buildStage } from '../src/previs/scene.js';
import { createMotionDemoPlan, MOTION_DEMO_SCENE } from '../src/previs/demoPlan.js';

const distance = (a, b) => Math.hypot(...a.map((v, i) => v - b[i]));

test('the ordinary Walk in action alternates lifted feet while its root travels, then stands still', () => {
  const plan = { ...defaultPlan(), set: 'empty', action: 'walkin' }, compiled = motionPlan(plan);
  const stage = buildStage(plan), motion = stage.motion(plan), end = framesOf(plan) - 1;
  try {
    assert.ok(compiled.pins?.some(p => p.joint === 'ankleL') && compiled.pins?.some(p => p.joint === 'ankleR'), 'Walk in must use the shared contact-aware gait');
    const heights = side => motion.solved.map(fr => fr['ankle' + side][1]);
    assert.ok(Math.max(...heights('L')) > 0.10 && Math.max(...heights('R')) > 0.10, 'both feet must swing clear of the floor');
    assert.ok(Math.abs(motion.solved[end].pelvis[2] - motion.solved[0].pelvis[2] - 2.2) < 0.02, 'the root travels the requested distance');
    assert.ok(distance(motion.solved[end].pelvis, motion.solved[end - 10].pelvis) < 1e-5, 'the actor comes to rest');
    const arms = Array.from({ length: end + 1 }, (_, f) => sampleActor(compiled, f).pose.shoulderL?.[0] || 0);
    assert.ok(Math.max(...arms) - Math.min(...arms) > 0.2, 'arm swing accompanies the steps');
  } finally { stage.dispose(); }
});

test('a planted stand keeps both contact points for the requested hold', () => {
  const plan = { ...defaultPlan(), action: 'stand', use: [{ skill: 'standIdle', frames: 24, args: { at: [0, -0.25], plant: true } }] };
  const { pins, checks } = compileMotionSkills(plan);
  assert.equal(pins.filter(p => p.joint === 'ankleL').length, 25);
  assert.equal(pins.filter(p => p.joint === 'ankleR').length, 25);
  assert.equal(checks.planted.length, 2);
});

test('the ten-second demonstration has a settled look and sustained hand contact on the final rig', () => {
  const plan = createMotionDemoPlan(), compiled = motionPlan(plan), stage = buildStage(plan), end = framesOf(plan) - 1;
  try {
    assert.equal(end, 240);
    const motion = stage.motion(plan), root = motion.solved;
    assert.ok(distance(root[96].pelvis, root[120].pelvis) < 0.005, 'walking ends before the pause');
    assert.equal(sampleActor(compiled, 120).headYaw, 0, 'the head turn waits for the settled pause');
    assert.ok(sampleActor(compiled, 156).headYaw > 0.8, 'the actor looks toward the listener');
    const points = {};
    stage.pose(0, plan); stage.scene.traverse(o => { if (o.userData.kp && !points[o.userData.kp]) points[o.userData.kp] = o; });
    const actual = joint => points[joint].getWorldPosition(new THREE.Vector3()).toArray();
    const planted = compileMotionSkills(plan).checks.planted.filter(c => c.from < 96);
    let maxStepSlip = 0;
    for (const contact of planted) for (let f = contact.from; f <= contact.to; f++) {
      stage.pose(f, plan); stage.scene.updateMatrixWorld(true);
      const foot = actual(contact.joint);
      maxStepSlip = Math.max(maxStepSlip, Math.hypot(foot[0] - contact.pos[0], foot[2] - contact.pos[2]));
    }
    assert.ok(planted.length >= 6 && maxStepSlip < 0.015, `the supporting foot slides ${maxStepSlip} m while walking`);
    let maxHandError = 0, maxFootDrift = 0, feet;
    for (let f = 96; f <= end; f++) {
      stage.pose(f, plan); stage.scene.updateMatrixWorld(true);
      feet ||= ['ankleL', 'ankleR'].map(actual);
      for (const [i, joint] of ['ankleL', 'ankleR'].entries()) maxFootDrift = Math.max(maxFootDrift, distance(actual(joint), feet[i]));
      if (f >= 204) maxHandError = Math.max(maxHandError, distance(actual('wristR'), MOTION_DEMO_SCENE.contact));
    }
    assert.ok(maxFootDrift < 0.015, `planted stance drifts ${maxFootDrift} m`);
    assert.ok(maxHandError < 0.015, `rendered hand misses the object by ${maxHandError} m`);
  } finally { stage.dispose(); }
});
