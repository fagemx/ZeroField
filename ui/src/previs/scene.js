// three.js previs stage: a grey blockout the motion pass can follow. Built from primitives only (no assets),
// so what LTX-2.5 reads is structure, camera and light, never a look.
import * as THREE from 'three';
import { FRAMES, WIDTH, HEIGHT, sampleActor, sampleCamera, verticalFov } from './plan.js';

const ROOM = new THREE.Vector3(0, 0, -4.1);  // dome centre; the station (actor's mark) is the origin, the console is at +z

function lambert(color) { return new THREE.MeshLambertMaterial({ color }); }

function observatory(group, mats) {
  const add = (geo, mat, x, y, z, ry = 0) => { const m = new THREE.Mesh(geo, mat); m.position.set(x, y, z); m.rotation.y = ry; group.add(m); return m; };
  add(new THREE.CylinderGeometry(6.6, 6.6, 0.1, 96), mats.floor, ROOM.x, -0.05, ROOM.z);
  const R = 6, Z0 = 1.15;
  for (let i = 0; i < 36; i++) {
    const a = 2 * Math.PI * i / 36;
    add(new THREE.BoxGeometry(0.1, Z0, 0.1), mats.glass, ROOM.x + R * Math.cos(a), Z0 / 2, ROOM.z + R * Math.sin(a), -a);
  }
  for (let i = 0; i < 16; i++) {  // meridian ribs meeting at the top of the dome
    const rib = add(new THREE.TorusGeometry(R, 0.07, 8, 96, Math.PI), mats.glass, ROOM.x, Z0, ROOM.z, 2 * Math.PI * i / 16);
    rib.rotation.x = 0;
  }
  for (const el of [0, 18, 36, 54, 70]) {
    const t = el * Math.PI / 180;
    const ring = add(new THREE.TorusGeometry(R * Math.cos(t), 0.05, 8, 128), mats.glass, ROOM.x, Z0 + R * Math.sin(t), ROOM.z);
    ring.rotation.x = Math.PI / 2;
  }
  const seg = 40, w = 2 * Math.PI * 5.05 / seg * 0.98;
  for (let i = 0; i < seg; i++) {  // continuous console ring hugging the glass, sloped top toward the room
    const a = 2 * Math.PI * i / seg, ca = Math.cos(a), sa = Math.sin(a);
    add(new THREE.BoxGeometry(0.84, 0.84, w), mats.brass, ROOM.x + 5.05 * ca, 0.42, ROOM.z + 5.05 * sa, -a);
    const top = add(new THREE.BoxGeometry(0.64, 0.12, w), mats.brass, ROOM.x + 4.85 * ca, 0.92, ROOM.z + 4.85 * sa, -a);
    top.rotateZ(0.38);
  }
  const dial = add(new THREE.CylinderGeometry(0.17, 0.17, 0.14, 48), mats.brass, -0.25, 1.03, 0.56);
  dial.rotation.x = -0.38;
}

function emptyStage(group, mats) {
  const floor = new THREE.Mesh(new THREE.BoxGeometry(14, 0.1, 14), mats.floor); floor.position.set(0, -0.05, -3); group.add(floor);
  const wall = new THREE.Mesh(new THREE.BoxGeometry(14, 4, 0.2), mats.glass); wall.position.set(0, 2, 1.2); group.add(wall);
}

function actor(mats) {
  const root = new THREE.Group();
  const part = (geo, mat, x, y, z) => { const m = new THREE.Mesh(geo, mat); m.position.set(x, y, z); root.add(m); return m; };
  part(new THREE.CylinderGeometry(0.09, 0.09, 0.9, 16), mats.coat, -0.12, 0.45, 0);
  part(new THREE.CylinderGeometry(0.09, 0.09, 0.9, 16), mats.coat, 0.12, 0.45, 0);
  part(new THREE.BoxGeometry(0.48, 0.72, 0.28), mats.coat, 0, 1.25, 0);
  part(new THREE.SphereGeometry(0.13, 24, 16), mats.skin, 0, 1.78, 0).scale.set(0.92, 1.15, 1);
  part(new THREE.BoxGeometry(0.05, 0.06, 0.08), mats.skin, 0, 1.78, 0.13);  // nose: shows facing
  part(new THREE.CylinderGeometry(0.05, 0.05, 0.64, 12), mats.coat, 0.3, 1.25, 0);
  const shoulder = new THREE.Group(); shoulder.position.set(-0.3, 1.55, 0); root.add(shoulder);  // reaching arm on -x
  const arm = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 0.66, 12), mats.coat); arm.position.set(0, -0.33, 0); shoulder.add(arm);
  const hand = new THREE.Mesh(new THREE.SphereGeometry(0.06, 12, 8), mats.skin); hand.position.set(0, -0.68, 0); shoulder.add(hand);
  return { root, shoulder };
}

// Build a stage for a plan. Returns { scene, camera, frame(f), pose(f), shoot(f), dispose }.
// The renderer must have shadowMap enabled (see prepareRenderer).
export function prepareRenderer(renderer) {
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  return renderer;
}

export function buildStage(plan) {
  const night = plan.mood === 'night';
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(night ? 0x0d1219 : 0xaab4c4);  // grey mood matches the Blender blockout LTX was tested on
  const mats = { glass: lambert(0x8c949e), floor: lambert(night ? 0x24262b : 0x4d4f54), brass: lambert(0x9e8550),
                 skin: lambert(0xccad94), coat: lambert(night ? 0x383a40 : 0x55585f), beam: new THREE.MeshBasicMaterial({ color: 0xfff2cc }) };
  if (night) {
    scene.add(new THREE.HemisphereLight(0x2a3550, 0x0a0a0c, 0.35));
    const key = new THREE.PointLight(0xff9a4d, 9, 6, 1.6); key.position.set(0.3, 0.7, 0.4); scene.add(key);
    const rim = new THREE.DirectionalLight(0x8cb4ff, 1.1); rim.position.set(-3, 5, 8); scene.add(rim);
  } else {
    scene.add(new THREE.HemisphereLight(0xdde4ee, 0x303236, 0.9));
    // Studio key with soft shadows, like the Blender workbench blockout the motion pass was validated on.
    const key = new THREE.DirectionalLight(0xffffff, 1.0); key.position.set(-4, 9, -8); key.target.position.copy(ROOM); scene.add(key, key.target);
    key.castShadow = true; key.shadow.mapSize.set(2048, 2048); key.shadow.bias = -0.0005;
    Object.assign(key.shadow.camera, { left: -9, right: 9, top: 9, bottom: -9, near: 0.5, far: 40 });
  }
  const set = new THREE.Group(); scene.add(set);
  (plan.set === 'empty' ? emptyStage : observatory)(set, mats);
  const beacon = new THREE.Mesh(new THREE.SphereGeometry(0.8, 24, 16), mats.beam); beacon.position.set(-2, 3, 28); scene.add(beacon);
  const figure = actor(mats); scene.add(figure.root);
  // Shadows everywhere. No outline/crease lines: drawn edges read as a toon render and the motion pass turns cartoon.
  scene.traverse(o => { if (o.isMesh && o.material !== mats.beam) o.castShadow = o.receiveShadow = true; });
  const camera = new THREE.PerspectiveCamera(verticalFov(plan.lens), WIDTH / HEIGHT, 0.05, 200);
  const aim = new THREE.Vector3();
  function pose(f) {  // actor and beacon at frame f
    const a = sampleActor(plan, f);
    figure.root.position.set(0, 0, -a.back);
    figure.root.rotation.y = a.yaw;
    figure.shoulder.rotation.x = -a.reach;
    beacon.scale.setScalar(f < 67 ? 0.001 : f < 71 ? (f - 67) / 4 : 1);
  }
  function shoot(f) {  // planned camera at frame f
    const c = sampleCamera(plan, f);
    camera.position.set(...c.position); camera.lookAt(aim.set(...c.aim));
    camera.fov = verticalFov(plan.lens); camera.updateProjectionMatrix();
  }
  const frame = f => { pose(f); shoot(f); };
  function dispose() {
    scene.traverse(o => { o.geometry?.dispose(); });
    Object.values(mats).forEach(m => m.dispose());
  }
  return { scene, camera, frame, pose, shoot, dispose, frames: FRAMES };
}
