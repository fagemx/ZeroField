// three.js previs stage: a grey blockout the motion pass can follow. Built from primitives only (no assets),
// so what LTX-2.5 reads is structure, camera and light, never a look.
import * as THREE from 'three';
import { DOME, WIDTH, HEIGHT, cameraKeys, framesOf, sampleActor, sampleCamera, verticalFov } from './plan.js';

const ROOM = new THREE.Vector3(DOME.x, 0, DOME.z);  // dome centre; the station (actor's mark) is the origin, the console is at +z

function lambert(color) { return new THREE.MeshLambertMaterial({ color }); }

function observatory(group, mats) {
  const add = (geo, mat, x, y, z, ry = 0) => { const m = new THREE.Mesh(geo, mat); m.position.set(x, y, z); m.rotation.y = ry; group.add(m); return m; };
  add(new THREE.CylinderGeometry(6.6, 6.6, 0.1, 96), mats.floor, ROOM.x, -0.05, ROOM.z);
  const R = DOME.radius, Z0 = DOME.base;
  for (let i = 0; i < 36; i++) {
    const a = 2 * Math.PI * i / 36;
    add(new THREE.BoxGeometry(0.1, Z0, 0.1), mats.glass, ROOM.x + R * Math.cos(a), Z0 / 2, ROOM.z + R * Math.sin(a), -a);
  }
  for (let i = 0; i < 16; i++) {  // meridian ribs meeting at the top of the dome
    add(new THREE.TorusGeometry(R, 0.07, 8, 96, Math.PI), mats.glass, ROOM.x, Z0, ROOM.z, 2 * Math.PI * i / 16).userData.roof = true;
  }
  for (const el of [0, 18, 36, 54, 70]) {
    const t = el * Math.PI / 180;
    const ring = add(new THREE.TorusGeometry(R * Math.cos(t), 0.05, 8, 128), mats.glass, ROOM.x, Z0 + R * Math.sin(t), ROOM.z);
    ring.rotation.x = Math.PI / 2; ring.userData.roof = el > 0;
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
  // Facing cues the motion pass can read: hair over the back of the head (a bare sphere from behind reads as a face)
  // and shoes pointing forward.
  part(new THREE.SphereGeometry(0.137, 24, 16, Math.PI, Math.PI, 0, Math.PI * 0.8), mats.hair, 0, 1.78, 0).scale.set(0.92, 1.15, 1);
  part(new THREE.SphereGeometry(0.137, 24, 6, 0, Math.PI, 0, Math.PI * 0.22), mats.hair, 0, 1.78, 0).scale.set(0.92, 1.15, 1);
  for (const x of [-0.12, 0.12]) part(new THREE.BoxGeometry(0.11, 0.08, 0.28), mats.hair, x, 0.04, 0.07);
  part(new THREE.CylinderGeometry(0.05, 0.05, 0.64, 12), mats.coat, 0.3, 1.25, 0);
  const shoulder = new THREE.Group(); shoulder.position.set(-0.3, 1.55, 0); root.add(shoulder);  // reaching arm on -x
  const arm = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 0.66, 12), mats.coat); arm.position.set(0, -0.33, 0); shoulder.add(arm);
  const hand = new THREE.Mesh(new THREE.SphereGeometry(0.06, 12, 8), mats.skin); hand.position.set(0, -0.68, 0); shoulder.add(hand);
  return { root, shoulder };
}

// Build a stage for a plan's set and light. Returns { scene, camera, frame(f, plan), pose(f, plan), shoot(f, plan), roof(show), dispose };
// pose/shoot take the current plan, so only a set or light change needs a new stage.
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
                 skin: lambert(0xccad94), hair: lambert(0x3a322c), coat: lambert(night ? 0x383a40 : 0x55585f), beam: new THREE.MeshBasicMaterial({ color: 0xfff2cc }) };
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
  function pose(f, p = plan) {  // actor and beacon at frame f
    const a = sampleActor(p, f);
    figure.root.position.set(0, 0, -a.back);
    figure.root.rotation.y = a.yaw;
    figure.shoulder.rotation.x = -a.reach;
    beacon.scale.setScalar(f < 67 ? 0.001 : f < 71 ? (f - 67) / 4 : 1);
  }
  function shoot(f, p = plan) {  // planned camera at frame f
    const c = sampleCamera(p, f);
    camera.position.set(...c.position); camera.lookAt(aim.set(...c.aim));
    camera.fov = verticalFov(p.lens); camera.updateProjectionMatrix();
  }
  const frame = (f, p = plan) => { pose(f, p); shoot(f, p); };
  const roof = show => set.traverse(o => { if (o.userData.roof) o.visible = show; });  // the overhead plan looks through the dome
  function dispose() {
    scene.traverse(o => { o.geometry?.dispose(); });
    Object.values(mats).forEach(m => m.dispose());
  }
  return { scene, camera, frame, pose, shoot, roof, dispose };
}

// Director's guides for the overhead and free views (never rendered into a previs): each shot's camera path,
// a camera glyph at the current frame and its shot label. Shots on the same camera path share one glyph and label.
// entries: [{ id, plan, selected }].
export function shotGuides(entries) {
  const paths = new Map();
  for (const e of entries) {
    const key = JSON.stringify(cameraKeys(e.plan)), at = paths.get(key);
    if (at) { at.id += ' · ' + e.id; at.selected ||= e.selected; } else paths.set(key, { ...e });
  }
  const group = new THREE.Group(), parts = [];
  const glyphGeo = new THREE.BufferGeometry().setFromPoints([[0, 0, 0], [-0.22, -0.13, 0.4], [0, 0, 0], [0.22, -0.13, 0.4], [0, 0, 0], [0.22, 0.13, 0.4],
    [0, 0, 0], [-0.22, 0.13, 0.4], [-0.22, -0.13, 0.4], [0.22, -0.13, 0.4], [0.22, -0.13, 0.4], [0.22, 0.13, 0.4], [0.22, 0.13, 0.4], [-0.22, 0.13, 0.4],
    [-0.22, 0.13, 0.4], [-0.22, -0.13, 0.4], [-0.08, 0.16, 0.4], [0, 0.26, 0.4], [0, 0.26, 0.4], [0.08, 0.16, 0.4]].map(v => new THREE.Vector3(...v)));
  for (const { id, plan, selected } of paths.values()) {
    const color = selected ? 0xf2b33d : 0x06b6d4, opacity = selected ? 1 : 0.55;
    const line = new THREE.LineBasicMaterial({ color, transparent: true, opacity, depthTest: false });
    const points = Array.from({ length: 49 }, (_, i) => new THREE.Vector3(...sampleCamera(plan, i * (framesOf(plan) - 1) / 48).position));
    const path = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), line);
    const glyph = new THREE.LineSegments(glyphGeo, line);
    const canvas = document.createElement('canvas'), g = canvas.getContext('2d'), font = '600 30px system-ui, sans-serif';
    g.font = font; canvas.width = Math.ceil(g.measureText(id).width) + 24; canvas.height = 48;
    g.font = font; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillStyle = selected ? '#f2b33d' : '#67e8f9'; g.fillText(id, canvas.width / 2, 25);
    const label = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas), depthTest: false, transparent: true }));
    const base = 0.3 * canvas.width / 48;
    for (const o of [path, glyph, label]) { o.renderOrder = selected ? 3 : 2; group.add(o); }
    parts.push({ plan, glyph, label, path, base });
  }
  const target = new THREE.Vector3();
  // progress 0..1 through the shot (shots can differ in length); size scales glyphs and labels for the overhead plan.
  function update(progress, size = 1) {
    for (const { plan, glyph, label, base } of parts) {
      const c = sampleCamera(plan, progress * (framesOf(plan) - 1));
      glyph.position.set(...c.position); glyph.lookAt(target.set(...c.aim)); glyph.scale.setScalar(size);
      label.position.set(c.position[0], c.position[1] + 0.4 * size, c.position[2] - 0.45 * size);
      label.scale.set(base * size, 0.3 * size, 1);
    }
  }
  function dispose() {
    glyphGeo.dispose();
    for (const { path, label } of parts) { path.geometry.dispose(); path.material.dispose(); label.material.map.dispose(); label.material.dispose(); }
  }
  return { group, update, dispose };
}
