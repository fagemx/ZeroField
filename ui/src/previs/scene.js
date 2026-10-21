// three.js previs stage: a grey blockout the motion pass can follow. Built from primitives only (no assets),
// so what LTX-2.5 reads is structure, camera and light, never a look.
import * as THREE from 'three';
import { DEFAULT_FIGURE, DOME, WIDTH, HEIGHT, cameraKeys, framesOf, sampleActor, sampleActs, sampleCamera, verticalFov } from './plan.js';
import { SET, boardActor } from './board.js';

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

// A mannequin with adult proportions (tapered torso, round shoulders, capsule limbs, neck, a head about 1/7.6 of the
// height): the Layout-To-Render IC-LoRA renders blockout shapes literally. A box torso came out as a brass box and a
// 1/6.4 head as a child.
// Jointed (SPEC_10 P2): pelvis, spine, neck, shoulders, elbows, hips, knees and ankles, so poses (lean, slump, kneel, hands
// to the face...) bend it. Standing, every part sits where the single-piece mannequin's did; the limbs are split at the
// elbow and knee into two capsules of the same radius.
// Looks (SPEC_10 P3): build, outfit and hair change the silhouette, since the Layout Render reads who someone is from
// the shapes: a woman is narrower in the shoulders and wider in the hips, a child is 0.64 of the height with a larger
// head, an elder stoops; a long coat, a dress or a robe hangs from the waist; long hair falls to the shoulders.
// m: the person's materials, { coat, skin, hair }.
function actor(mats, figure = {}, m = mats) {
  const coat = m.coat;
  const look = { ...DEFAULT_FIGURE, ...figure }, woman = look.build === 'woman', child = look.build === 'child';
  const root = new THREE.Group(), joint = (parent, x, y, z) => { const g = new THREE.Group(); g.position.set(x, y, z); parent.add(g); return g; };
  const part = (parent, geo, mat, x, y, z) => { const m = new THREE.Mesh(geo, mat); m.position.set(x, y, z); parent.add(m); return m; };
  const limb = (r, total) => new THREE.CapsuleGeometry(r, total - 2 * r, 6, 16);  // a capsule `total` long, caps included
  const body = joint(root, 0, 0, 0); body.scale.setScalar(child ? 0.64 : woman ? 0.94 : 1);
  const pelvis = joint(body, 0, 0.98, 0), spine = joint(pelvis, 0, 0, 0), neck = joint(spine, 0, 0.6, 0), head = joint(neck, 0, 0.21, 0);
  const chest = woman ? 0.2 : 0.23;
  part(pelvis, new THREE.SphereGeometry(woman ? 0.2 : 0.18, 24, 12), coat, 0, 0, 0).scale.set(1, 0.6, woman ? 0.75 : 0.7);  // hips
  part(spine, new THREE.CylinderGeometry(chest, 0.17, 0.58, 24), coat, 0, 0.29, 0).scale.set(1, 1, 0.6);  // chest to waist
  part(spine, new THREE.SphereGeometry(chest, 24, 12), coat, 0, 0.58, 0).scale.set(1, 0.33, 0.6);  // shoulder line
  part(neck, new THREE.CylinderGeometry(0.055, 0.06, 0.14, 12), m.skin, 0, 0.06, 0);
  head.scale.setScalar(child ? 1.3 : 1);
  part(head, new THREE.SphereGeometry(0.11, 24, 16), m.skin, 0, 0, 0).scale.set(0.92, 1.15, 1);
  part(head, new THREE.BoxGeometry(0.05, 0.06, 0.08), m.skin, 0, 0, 0.11);  // nose: shows facing
  // Facing cues the motion pass can read: hair over the back of the head (a bare sphere from behind reads as a face)
  // and shoes pointing forward.
  part(head, new THREE.SphereGeometry(0.117, 24, 16, Math.PI, Math.PI, 0, Math.PI * 0.8), m.hair, 0, 0, 0).scale.set(0.92, 1.15, 1);
  part(head, new THREE.SphereGeometry(0.117, 24, 6, 0, Math.PI, 0, Math.PI * 0.22), m.hair, 0, 0, 0).scale.set(0.92, 1.15, 1);
  if (look.hair === 'long') part(head, limb(0.1, 0.42), m.hair, 0, -0.14, -0.06).scale.set(1.15, 1, 0.55);
  if (look.hair === 'bun') part(head, new THREE.SphereGeometry(0.06, 16, 12), m.hair, 0, 0.06, -0.13);
  const hem = { longcoat: [0.21, 0.3, 0.6], dress: [0.18, 0.36, 0.78], robe: [0.2, 0.36, 0.95] }[look.outfit];
  if (hem) part(pelvis, new THREE.CylinderGeometry(hem[0], hem[1], hem[2], 24), coat, 0, 0.06 - hem[2] / 2, 0).scale.set(1, 1, 0.8);
  const joints = { pelvis, spine, neck };
  for (const [side, x] of [['L', -1], ['R', 1]]) {  // left = the reaching arm, on -x
    const narrow = woman ? 0.03 : 0;
    const shoulder = x < 0 ? joint(spine, -0.28 + narrow, 0.55, 0) : joint(spine, 0.245 - narrow, 0.57, 0), elbow = joint(shoulder, 0, -0.33, 0);  // the hanging arm's top was at 0.245
    part(shoulder, limb(0.05, 0.35), coat, 0, -0.165, 0);
    part(elbow, limb(0.05, 0.35), coat, 0, -0.165, 0);
    part(elbow, new THREE.SphereGeometry(x < 0 ? 0.06 : 0.055, 12, 8), m.skin, 0, -0.35, 0);
    const hip = joint(pelvis, 0.11 * x, -0.06, 0), knee = joint(hip, 0, -0.45, 0), ankle = joint(knee, 0.01 * x, -0.43, 0);
    part(hip, limb(0.075, 0.5), coat, 0, -0.22, 0);
    part(knee, limb(0.075, 0.5), coat, 0, -0.22, 0);
    part(ankle, new THREE.BoxGeometry(0.11, 0.08, 0.28), m.hair, 0, 0, 0.07);
    shoulder.rotation.order = elbow.rotation.order = 'YXZ';  // pitch the arm forward first, then turn it in across the body
    Object.assign(joints, { ['shoulder' + side]: shoulder, ['elbow' + side]: elbow, ['hip' + side]: hip, ['knee' + side]: knee, ['ankle' + side]: ankle });
  }
  // The hanging arm sits a little out from the body; an elder stoops.
  const rest = { shoulderR: [0, 0, 0.08], ...(look.build === 'elder' ? { spine: [0.16, 0, 0], neck: [0.1, 0, 0] } : {}) };
  root.traverse(o => { o.userData.actor = true; });
  const out = { root, shoulder: joints.shoulderL, joints, rest };
  applyPose(out, { reach: 0, pose: {} });
  return out;
}
// Pose the jointed mannequin: the body pose on top of its rest, then the reach channel takes the left arm toward the console.
function applyPose(figure, a) {
  const p = a.pose || {};
  for (const [name, g] of Object.entries(figure.joints)) { const r = p[name] || [0, 0, 0], rest = figure.rest[name] || [0, 0, 0]; g.rotation.set(r[0] + rest[0], r[1] + rest[1], r[2] + rest[2]); }
  figure.joints.pelvis.position.y = (figure.pelvisY ?? 0.98) - (p.drop || 0);
  const w = Math.min(1, a.reach / 0.6);  // a reach blends the left arm from its pose to straight out at the dial
  if (w > 0) {
    const s = figure.joints.shoulderL.rotation, e = figure.joints.elbowL.rotation;
    s.set(s.x + (-a.reach - s.x) * w, s.y * (1 - w), s.z * (1 - w)); e.set(e.x * (1 - w), e.y * (1 - w), e.z * (1 - w));
  }
}
// Coats per cast member, so two people never read as one shape: grey and night tones.
const COATS = { grey: [0x55585f, 0x6b5a4c, 0x4c5866, 0x5d5268], night: [0x383a40, 0x45392f, 0x2f3944, 0x3d3446] };

// Build a stage for a plan's set and light. Returns { scene, camera, frame(f, plan), pose(f, plan), shoot(f, plan), roof(show), matte(on), dispose };
// pose/shoot take the current plan, so only a set or light change needs a new stage. opts.board: the board look for
// blocking (board.js), never for a previs that LTX renders.
// The renderer must have shadowMap enabled (see prepareRenderer).
export function prepareRenderer(renderer) {
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  return renderer;
}

export function buildStage(plan, opts = {}) {
  const night = plan.mood === 'night', board = !!opts.board;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(board ? (night ? SET.night : SET.background) : night ? 0x0d1219 : 0xaab4c4);  // grey mood matches the Blender blockout LTX was tested on
  const mats = { glass: lambert(board ? SET.glass : 0x8c949e), floor: lambert(board ? SET.floor : night ? 0x24262b : 0x4d4f54), brass: lambert(board ? SET.brass : 0x9e8550),
                 skin: lambert(0xccad94), hair: lambert(0x3a322c), coat: lambert(night ? 0x383a40 : 0x55585f), beam: new THREE.MeshBasicMaterial({ color: 0xfff2cc }) };
  if (board) {  // high-key and even, like the shot-idiom generator's stage: every shape reads
    scene.add(new THREE.HemisphereLight(0xffffff, 0x8a918d, 0.95));
    const sun = new THREE.DirectionalLight(0xffffff, 0.55); sun.position.set(-2, 4, 3); scene.add(sun);
  } else if (night) {
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
  // Shadows everywhere. No outline/crease lines: drawn edges read as a toon render and the motion pass turns cartoon.
  scene.traverse(o => { if (o.isMesh && o.material !== mats.beam) o.castShadow = o.receiveShadow = true; });
  // The cast: the shot's subject (the plan's own actor) plus anyone in plan.cast, rebuilt only when who is in it changes.
  let figures = [], castKey = null, matteOn = false;
  const coats = COATS[night ? 'night' : 'grey'].map(lambert);
  function cast(p) {
    const looks = [p.figure || {}, ...(p.cast || []).map(c => c.figure || {})], key = JSON.stringify(looks);
    if (key === castKey) return figures;
    for (const f of figures) { scene.remove(f.root); f.root.traverse(o => { if (o.isMesh) o.geometry.dispose(); }); }
    for (const f of figures) Object.values(f.mats || {}).forEach(x => x.dispose());
    figures = looks.map((look, i) => {
      const tone = look.tone ?? i;  // a person keeps their colour in every shot, whoever is the subject
      return board ? boardActor(look, tone) : actor(mats, look, { coat: coats[tone % coats.length], skin: mats.skin, hair: mats.hair });
    });
    castKey = key;
    for (const f of figures) { scene.add(f.root); f.root.traverse(o => { if (o.isMesh) o.castShadow = o.receiveShadow = !o.userData.outline; }); }
    if (matteOn) matte(true);
    return figures;
  }
  const place = (fig, a, mark = [0, 0], turn = 0) => {
    fig.root.position.set(mark[0], 0, mark[1] - a.back); fig.root.rotation.y = a.yaw + turn * Math.PI / 180; applyPose(fig, a);
  };
  const camera = new THREE.PerspectiveCamera(verticalFov(plan.lens), WIDTH / HEIGHT, 0.05, 200);
  const aim = new THREE.Vector3();
  function pose(f, p = plan) {  // the cast and the beacon at frame f; mark [x, z] and turn (degrees) place each actor
    const [main, ...others] = cast(p), u = f / (framesOf(p) - 1);
    place(main, sampleActor(p, f), p.mark, p.turn);
    (p.cast || []).forEach((c, i) => place(others[i], sampleActs(c.acts || [], u), c.mark, c.turn));
    const b = f * 96 / (framesOf(p) - 1);  // the beacon lights on the beat clock, so a 6 or 8 s shot keeps it after the dial turn
    beacon.scale.setScalar(b < 67 ? 0.001 : b < 71 ? (b - 67) / 4 : 1);
  }
  function shoot(f, p = plan) {  // planned camera at frame f
    const c = sampleCamera(p, f);
    camera.position.set(...c.position); camera.lookAt(aim.set(...c.aim));
    camera.fov = verticalFov(p.lens); camera.updateProjectionMatrix();
  }
  const frame = (f, p = plan) => { pose(f, p); shoot(f, p); };
  const roof = show => set.traverse(o => { if (o.userData.roof) o.visible = show; });  // the overhead plan looks through the dome
  // Actor matte for the Layout Render's attention mask: the same plan and camera, the actor white on black.
  const flat = { on: new THREE.MeshBasicMaterial({ color: 0xffffff }), off: new THREE.MeshBasicMaterial({ color: 0x000000 }) }, background = scene.background;
  function matte(on) {
    matteOn = on;
    scene.background = on ? new THREE.Color(0x000000) : background;
    scene.traverse(o => {
      if (!o.isMesh) return;
      o.userData.material ??= o.material;
      o.material = !on ? o.userData.material : o.userData.actor ? flat.on : flat.off;
    });
  }
  function dispose() {
    scene.traverse(o => { o.geometry?.dispose(); });
    Object.values(mats).concat(Object.values(flat), coats, ...figures.map(f => Object.values(f.mats || {}))).forEach(m => m.dispose());
  }
  return { scene, camera, frame, pose, shoot, roof, matte, dispose };
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
