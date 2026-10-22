// three.js previs stage: a grey blockout the motion pass can follow. Built from primitives only (no assets),
// so what LTX-2.5 reads is structure, camera and light, never a look.
import * as THREE from 'three';
import { DOME, MSFLOW_JOINTS, WIDTH, HEIGHT, billboardYaw, cameraKeys, framesOf, parallaxLayers, sampleActor, sampleActs, sampleCamera,
  solveLimbIK, solvePinnedXYZ, verticalFov } from './plan.js';
import { SET, buildFigure } from './figure.js';

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

// The 2.5D parallax set: a dark floor for the actor's shadow and the plan's cards (plan.js parallaxLayers). Each card is
// sized to the 35 mm frustum at its distance from the wide push-in key, so the far card fills that frame and any camera
// move slides the cards against each other. A card with src shows that image (the shot's @SET); without one a grey
// block per depth (far light, mid a darker band, near a dark frame the actor shows through), so depth still reads.
const EYE_Z = -5.8;
function parallaxStage(group, mats, plan, onLoad) {
  const floor = new THREE.Mesh(new THREE.BoxGeometry(16, 0.1, 16), mats.floor); floor.position.set(0, -0.05, -2); group.add(floor);
  const tan = Math.tan(verticalFov(35) * Math.PI / 360);
  const quad = (x0, y0, x1, y1) => [new THREE.Vector2(x0, y0), new THREE.Vector2(x1, y0), new THREE.Vector2(x1, y1), new THREE.Vector2(x0, y1)];
  for (const layer of parallaxLayers(plan)) {
    const h = 2 * Math.max(0.5, layer.z - EYE_Z) * tan * (layer.scale ?? 1), w = h * WIDTH / HEIGHT;
    const mat = new THREE.MeshBasicMaterial({ color: layer.color ?? { far: 0xa7aeb8, mid: 0x6c7179, near: 0x26282c }[layer.role] ?? 0x6c7179, transparent: true, opacity: layer.opacity ?? 1 });
    mats['layer:' + layer.id] = mat;
    let geo;
    if (layer.src || layer.role === 'far') geo = new THREE.PlaneGeometry(w, h);
    else if (layer.role === 'near') { const s = new THREE.Shape(quad(-w / 2, -h / 2, w / 2, h / 2)); s.holes.push(new THREE.Path(quad(-0.36 * w, -0.38 * h, 0.36 * w, 0.38 * h))); geo = new THREE.ShapeGeometry(s); }
    else geo = new THREE.PlaneGeometry(w, h * 0.45).translate(0, -h * 0.275, 0);
    geo.rotateY(Math.PI);  // the front faces -z, toward the cameras (billboardYaw)
    const card = new THREE.Mesh(geo, mat); card.position.set(layer.x ?? 0, layer.y, layer.z); card.userData.parallaxLayer = layer; group.add(card);
    if (layer.src && typeof document !== 'undefined') new THREE.TextureLoader().load(layer.src, tex => {
      tex.colorSpace = THREE.SRGBColorSpace; mat.map = tex; mat.color.set(0xffffff); mat.needsUpdate = true; onLoad?.();
    });
  }
}

// Where each direct-motion-space joint (plan.js MSFLOW_JOINTS) sits on the mannequin: a figure.js keypoint and an offset
// in its frame (body metres).
const RIG = { pelvis: ['pelvis'], hipL: ['hipL'], hipR: ['hipR'], spine1: ['spine'], kneeL: ['kneeL'], kneeR: ['kneeR'], spine2: ['chest'],
  ankleL: ['ankleL'], ankleR: ['ankleR'], spine3: ['chest', [0, 0.2, 0]], footL: ['ankleL', [0, -0.06, 0.12]], footR: ['ankleR', [0, -0.06, 0.12]],
  neck: ['neck'], collarL: ['chest', [-0.09, 0.26, 0]], collarR: ['chest', [0.09, 0.26, 0]], head: ['head'], shoulderL: ['shoulderL'], shoulderR: ['shoulderR'],
  elbowL: ['elbowL'], elbowR: ['elbowR'], wristL: ['wristL'], wristR: ['wristR'] };
const keypoints = fig => fig.kp ??= (() => { const m = {}; fig.root.traverse(o => { if (o.userData.kp && !(o.userData.kp in m)) m[o.userData.kp] = o; }); return m; })();
function rigXYZ(fig) {
  fig.root.updateMatrixWorld(true);
  const kp = keypoints(fig);
  return Object.fromEntries(MSFLOW_JOINTS.map(name => { const [j, off = [0, 0, 0]] = RIG[name]; return [name, kp[j].localToWorld(new THREE.Vector3(...off)).toArray()]; }));
}
// Put the posed mannequin on a solved motion frame: move it by the pelvis, turn the spine and neck along the solved
// bones, then two-bone IK from the mannequin's own shoulders and hips to the solved hands and feet.
export function retargetXYZToRig(fig, base, solved) {
  const kp = keypoints(fig), V = a => new THREE.Vector3(...a), at = name => kp[name].getWorldPosition(new THREE.Vector3());
  fig.root.position.add(V(solved.pelvis).sub(V(base.pelvis))); fig.root.updateMatrixWorld(true);
  const rotate = (joint, delta) => {  // a world rotation on joint; its children follow
    const parent = joint.parent.getWorldQuaternion(new THREE.Quaternion());
    joint.quaternion.premultiply(parent.clone().invert().multiply(delta).multiply(parent)); joint.updateMatrixWorld(true);
  };
  const turn = (joint, from, to) => { if (from.lengthSq() > 1e-12 && to.lengthSq() > 1e-12) rotate(joint, new THREE.Quaternion().setFromUnitVectors(from.normalize(), to.normalize())); };
  const basis = (up, side) => {  // up exact, side made square to it
    const y = up.normalize(), x = side.sub(y.clone().multiplyScalar(side.dot(y))).normalize();
    return new THREE.Matrix4().makeBasis(x, y, x.clone().cross(y));
  };
  turn(kp.spine, at('chest').sub(at('spine')), V(solved.spine2).sub(V(solved.spine1)));
  // The chest takes the solved neck direction and shoulder line together, so a lean carries the shoulders without twist.
  rotate(kp.chest, new THREE.Quaternion().setFromRotationMatrix(basis(V(solved.neck).sub(V(solved.spine2)), V(solved.shoulderR).sub(V(solved.shoulderL)))
    .multiply(basis(at('neck').sub(at('chest')), at('shoulderR').sub(at('shoulderL'))).transpose())));
  turn(kp.neck, at('head').sub(at('neck')), V(solved.head).sub(V(solved.neck)));
  for (const [root, mid, end] of [['shoulderL', 'elbowL', 'wristL'], ['shoulderR', 'elbowR', 'wristR'], ['hipL', 'kneeL', 'ankleL'], ['hipR', 'kneeR', 'ankleR']]) {
    if (at(end).distanceTo(V(solved[end])) < 1e-4) continue;
    const S = at(root), ik = solveLimbIK(S.toArray(), solved[mid], solved[end], at(mid).distanceTo(S), at(end).distanceTo(at(mid)));
    turn(kp[root], at(mid).sub(S), V(ik.mid).sub(S));
    turn(kp[mid], at(end).sub(at(mid)), V(ik.end).sub(at(mid)));
  }
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

// Build a stage for a plan's set and light. Returns { scene, camera, frame(f, plan), pose(f, plan), shoot(f, plan), roof(show), matte(on), motion(plan), dispose };
// pose/shoot take the current plan, so only a set, card or light change needs a new stage. opts.board: the board look for
// blocking (figure.js), never for a previs that LTX renders; opts.onLoad: called when a card's image arrives.
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
  if (plan.set === 'parallax') parallaxStage(set, mats, plan, opts.onLoad);
  else (plan.set === 'empty' ? emptyStage : observatory)(set, mats);
  // The observatory's sun, unless the plan switches it off (it sat in every close-up of the dome, SPEC_10 §7.9).
  const lit = p => (p.set || 'observatory') === 'observatory' && p.beacon !== false;
  const beacon = new THREE.Mesh(new THREE.SphereGeometry(0.8, 24, 16), mats.beam); beacon.position.set(-2, 3, 28); beacon.userData.beacon = true; beacon.visible = lit(plan); scene.add(beacon);
  // Shadows everywhere but the flat cards. No outline/crease lines: drawn edges read as a toon render and the motion pass turns cartoon.
  scene.traverse(o => { if (o.isMesh && o.material !== mats.beam && !o.userData.parallaxLayer) o.castShadow = o.receiveShadow = true; });
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
      return buildFigure(look, tone, board ? null : { coat: coats[tone % coats.length], skin: mats.skin, hair: mats.hair });
    });
    castKey = key;
    for (const f of figures) { scene.add(f.root); f.root.traverse(o => { if (o.isMesh) o.castShadow = o.receiveShadow = !o.userData.outline; }); }
    if (matteOn) matte(true);
    return figures;
  }
  const place = (fig, a, mark = [0, 0], turn = 0) => {
    fig.root.position.set(mark[0], 0, mark[1] - a.back); fig.root.rotation.y = a.yaw + turn * Math.PI / 180; applyPose(fig, a);
    fig.root.userData.face = a.face || {};  // the expression the skeleton's face points draw (skeleton.js)
  };
  const camera = new THREE.PerspectiveCamera(verticalFov(plan.lens), WIDTH / HEIGHT, 0.05, 200);
  const aim = new THREE.Vector3(), eye = new THREE.Vector3();
  // The subject's motion in direct motion space: the mannequin's FK per frame and the plan's pins solved on it, kept
  // until the acting or the pins change.
  let motionKey = null, solvedMotion = null;
  function motion(p = plan) {
    const main = cast(p)[0], key = JSON.stringify([p.pins, p.acts, p.action, p.facing, p.seconds, p.mark, p.turn, p.figure]);
    if (key !== motionKey) {
      const base = [];
      for (let f = 0; f < framesOf(p); f++) { place(main, sampleActor(p, f), p.mark, p.turn); base.push(rigXYZ(main)); }
      solvedMotion = { base, solved: solvePinnedXYZ(base, p.pins) }; motionKey = key;
    }
    return solvedMotion;
  }
  function pose(f, p = plan) {  // the cast, the beacon and the cards at frame f; mark [x, z] and turn (degrees) place each actor
    const pinned = p.pins?.length ? motion(p) : null;
    const [main, ...others] = cast(p), u = f / (framesOf(p) - 1);
    place(main, sampleActor(p, f), p.mark, p.turn);
    if (pinned) retargetXYZToRig(main, pinned.base[f], pinned.solved[f]);
    (p.cast || []).forEach((c, i) => place(others[i], sampleActs(c.acts || [], u), c.mark, c.turn));
    const b = f * 96 / (framesOf(p) - 1);  // the beacon lights on the beat clock, so a 6 or 8 s shot keeps it after the dial turn
    beacon.scale.setScalar(b < 67 ? 0.001 : b < 71 ? (b - 67) / 4 : 1); beacon.visible = lit(p);
    eye.set(...sampleCamera(p, f).position);
    for (const card of set.children) {  // cards face the shot camera, and a card the camera is passing fades out
      const layer = card.userData.parallaxLayer;
      if (!layer) continue;
      if (layer.billboard === 'full') { card.lookAt(eye); card.rotateY(Math.PI); }
      else if (layer.billboard !== false) card.rotation.y = billboardYaw(eye.toArray(), card.position.toArray());
      card.material.opacity = (layer.opacity ?? 1) * Math.min(1, Math.max(0, (card.position.distanceTo(eye) - 0.4) / 0.8));
    }
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
      if (o.userData.parallaxLayer) { o.visible = !on; return; }  // a transparent card would black out the actor behind it
      o.userData.material ??= o.material;
      o.material = !on ? o.userData.material : o.userData.actor ? flat.on : flat.off;
    });
  }
  function dispose() {
    scene.traverse(o => { o.geometry?.dispose(); });
    Object.values(mats).concat(Object.values(flat), coats, ...figures.map(f => Object.values(f.mats || {}))).forEach(m => { m.map?.dispose(); m.dispose(); });
  }
  return { scene, camera, frame, pose, shoot, roof, matte, motion, dispose };
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
