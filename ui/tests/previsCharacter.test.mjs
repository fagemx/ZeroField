import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { buildFigure } from '../src/previs/figure.js';

const materials = () => Object.fromEntries(['coat', 'skin', 'hair'].map(k => [k, new THREE.MeshLambertMaterial()]));
const garment = (f, name) => { let found; f.root.traverse(o => { if (o.userData.garment === name) found = o; }); return found; };
const update = f => { f.root.updateMatrixWorld(true); f.root.traverse(o => { if (o.isSkinnedMesh) o.skeleton.update(); }); };
const vertex = (mesh, i) => mesh.applyBoneTransform(i, new THREE.Vector3().fromBufferAttribute(mesh.geometry.attributes.position, i));
function components(g) {
  const parent = Array.from({ length: g.attributes.position.count }, (_, i) => i), root = i => { while (parent[i] !== i) { parent[i] = parent[parent[i]]; i = parent[i]; } return i; };
  const ix = g.index.array;
  for (let i = 0; i < ix.length; i += 3) { const a = root(ix[i]); parent[root(ix[i + 1])] = a; parent[root(ix[i + 2])] = a; }
  return new Set(parent.map((_, i) => root(i))).size;
}

test('clothing is connected across shoulders, elbows and knees, with finite normalized skin influences', () => {
  const f = buildFigure({}, 0, materials());
  for (const name of ['shirt', 'pants']) {
    const mesh = garment(f, name), g = mesh.geometry;
    assert.equal(components(g), 1, `${name} has no detached sleeve or trouser parts`);
    const w = g.attributes.skinWeight, ids = g.attributes.skinIndex;
    for (let i = 0; i < w.count; i++) {
      const weights = [w.getX(i), w.getY(i), w.getZ(i), w.getW(i)];
      assert.ok(weights.every(x => Number.isFinite(x) && x >= 0));
      assert.ok(Math.abs(weights.reduce((a, b) => a + b) - 1) < 1e-6);
      for (const id of [ids.getX(i), ids.getY(i), ids.getZ(i), ids.getW(i)]) assert.ok(id < mesh.skeleton.bones.length);
    }
  }
});

test('an elbow gesture deforms its sleeve while the chest stays put, in render and board looks', () => {
  for (const render of [materials(), null]) {
    const f = buildFigure({}, 0, render), mesh = garment(f, 'shirt'), p = mesh.geometry.attributes.position;
    update(f);
    let sleeve = 0, chest = 0, sleeveCount = 0, chestCount = 0;
    const before = Array.from({ length: p.count }, (_, i) => vertex(mesh, i));
    f.joints.elbowR.rotation.x -= 1.1; update(f);
    for (let i = 0; i < p.count; i++) {
      const now = vertex(mesh, i); assert.ok(now.toArray().every(Number.isFinite));
      if (p.getX(i) > 0.24 && p.getY(i) < 1.1) { sleeve += now.distanceTo(before[i]); sleeveCount++; }
      if (Math.abs(p.getX(i)) < 0.06 && p.getY(i) > 1.25) { chest += now.distanceTo(before[i]); chestCount++; }
    }
    assert.ok(sleeveCount && sleeve / sleeveCount > 0.10, 'a bent elbow carries the continuous lower sleeve');
    assert.ok(chestCount && chest / chestCount < 1e-5, 'an elbow cannot pull the torso along');
  }
});

test('the new surface retains the semantic rig, finger landmarks and adult floor/height envelope', () => {
  const f = buildFigure({}, 0, materials()), tags = {};
  update(f); f.root.traverse(o => { if (o.userData.kp) tags[o.userData.kp] = o; });
  for (const name of ['pelvis', 'spine', 'chest', 'neck', 'head', ...['L', 'R'].flatMap(s => ['shoulder', 'elbow', 'wrist', 'hip', 'knee', 'ankle'].map(j => j + s))]) assert.ok(tags[name], name);
  for (const side of ['L', 'R']) for (let finger = 0; finger < 5; finger++) for (let joint = 0; joint < 3; joint++) assert.ok(tags[`f${finger}_${joint}${side}`]);
  const box = new THREE.Box3().setFromObject(f.root, true);
  assert.ok(box.max.y > 1.88 && box.max.y < 1.98, `adult height ${box.max.y}`);
  assert.ok(box.min.y > -0.025 && box.min.y < 0.025, `sole height ${box.min.y}`);
  assert.ok(Math.abs(tags.shoulderR.position.x - 0.2) < 1e-9 && tags.kneeR.position.y === -0.42, 'IK bone lengths stay unchanged');
});

test('each actor owns its surface buffers and figure-owned materials without taking stage materials', () => {
  const supplied = materials(), a = buildFigure({}, 0, supplied), b = buildFigure({}, 1, supplied);
  assert.notEqual(garment(a, 'shirt').geometry, garment(b, 'shirt').geometry);
  assert.notEqual(garment(a, 'shirt').geometry.attributes.position.array, garment(b, 'shirt').geometry.attributes.position.array);
  assert.ok(Object.values(supplied).every(m => !a.mats.includes(m)), 'the stage retains ownership of supplied materials');
  garment(a, 'shirt').geometry.dispose();
  assert.ok(garment(b, 'shirt').geometry.attributes.position.count > 0, 'disposing one shot leaves other actor geometry intact');
});
