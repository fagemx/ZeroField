// The previs character: an original continuous, skinned clay proxy on the existing semantic pose rig. Clothing bends
// across shoulders, elbows, hips and knees; a neutral face and shaped shoes make facing and planted steps readable.
// One body, two looks:
//   board   for blocking: a flat two-tone fill in the person's own colour, construction lines and a thick outline, on a
//           high-key set (the generator's look);
//   render  what Render previs sends to LTX: grey coat, skin on the head, neck and hands, hair and shoes, no outlines
//           (outlines turn the motion pass cartoon). The Layout Render renders blockout shapes literally: a box torso
//           came out as a brass box, a 1/6.4 head as a child, and with the actor following the previs at 60% the
//           capsule arms and ball hands of the first mannequin came out as tubes and a fist (SPEC_10 §7.6), so the
//           body silhouette is continuous and the hands have fingers.
// Joint names are shared with plan.js POSES, so poses and performance keys drive either look.
import * as THREE from 'three';
import { BUILD } from './plan.js';
import { garmentGeometries, profileGeometry } from './characterGeometry.js';

// Fill and outline colour per cast member, in cast order (the first is the shot's subject).
export const CAST_COLORS = [['#a9c8ea', '#2e5f9c'], ['#e2a08f', '#8e2f22'], ['#bda6dc', '#4b3274'], ['#a8d4b0', '#2f6b3c']];
export const SET = { background: 0xcfd6d3, floor: 0xe4e8e6, glass: 0x9aa49f, brass: 0xd8cfb8, night: 0xaeb8c4 };

/* ---------- shaders (rig.js): two-tone fill with constant-width construction lines, and an inverted-hull outline ---------- */
const FILL_VS = `
varying vec3 vN; varying vec3 vV; varying vec3 vP;
#include <common>
#include <skinning_pars_vertex>
void main(){
  #include <beginnormal_vertex>
  #include <skinbase_vertex>
  #include <skinnormal_vertex>
  #include <begin_vertex>
  #include <skinning_vertex>
  vP = position; vec4 mv = modelViewMatrix * vec4(transformed, 1.0); vV = mv.xyz;
  vN = normalize(normalMatrix * objectNormal); gl_Position = projectionMatrix * mv; }`;
const FILL_FS = `
uniform vec3 uColor; uniform vec3 uShade; uniform vec3 uLight; uniform vec3 uLineColor; uniform float uLines; uniform float uEyeY;
varying vec3 vN; varying vec3 vV; varying vec3 vP;
void main(){
  vec3 n = normalize(vN), c = dot(n, normalize(uLight)) > 0.02 ? uColor : uShade;
  if (uLines > 0.5) {
    float on = 1.0 - smoothstep(0.8, 1.8, abs(vP.x) / max(fwidth(vP.x), 1e-5));
    if (uLines > 1.5) on *= step(0.0, vP.z);
    float onY = (1.0 - smoothstep(0.8, 1.8, abs(vP.y - uEyeY) / max(fwidth(vP.y), 1e-5))) * step(-0.01, vP.z) * (1.0 - step(1.5, uLines));
    c = mix(c, uLineColor, max(on, onY) * 0.9);
  }
  gl_FragColor = vec4(c, 1.0);
}`;
const LINE_VS = `
uniform float uThick; uniform float uPx; uniform float uScale;
#include <common>
#include <skinning_pars_vertex>
void main(){
  #include <beginnormal_vertex>
  #include <skinbase_vertex>
  #include <skinnormal_vertex>
  #include <begin_vertex>
  #include <skinning_vertex>
  vec4 mv0 = modelViewMatrix * vec4(transformed, 1.0); float t = (uThick + uPx * max(-mv0.z, 0.01)) / uScale;
  gl_Position = projectionMatrix * viewMatrix * modelMatrix * vec4(transformed + normalize(objectNormal) * t, 1.0); }`;
const LINE_FS = `uniform vec3 uColor; void main(){ gl_FragColor = vec4(uColor, 1.0); }`;
const LIGHT = new THREE.Vector3(-0.45, 0.62, 0.64).normalize();
export const PX = { value: 0.002 };
// World size of 1.6 px at unit distance for a camera and a viewport height; call before each render.
export const setPx = (camera, height) => { PX.value = 2 * Math.tan(camera.fov / 2 * Math.PI / 180) / height * 1.6; };
const fillMat = (color, line, lines = 0) => new THREE.ShaderMaterial({ vertexShader: FILL_VS, fragmentShader: FILL_FS, extensions: { derivatives: true },
  uniforms: { uColor: { value: new THREE.Color(color) }, uShade: { value: new THREE.Color(color).multiplyScalar(0.82) }, uLight: { value: LIGHT },
    uLineColor: { value: new THREE.Color(line) }, uLines: { value: lines }, uEyeY: { value: 0.1 } } });
const lineMat = (line, thick, scale) => new THREE.ShaderMaterial({ vertexShader: LINE_VS, fragmentShader: LINE_FS, side: THREE.BackSide,
  uniforms: { uThick: { value: thick }, uPx: PX, uScale: { value: scale }, uColor: { value: new THREE.Color(line) } } });

/* ---------- geometry (rig.js) ---------- */
const _n = new THREE.Vector3();
function ellipsoid(rx, ry, rz, cx = 0, cy = 0, cz = 0, ws = 18, hs = 12) {
  const g = new THREE.SphereGeometry(1, ws, hs), p = g.attributes.position, n = g.attributes.normal;
  for (let i = 0; i < p.count; i++) {
    const x = p.getX(i), y = p.getY(i), z = p.getZ(i);
    _n.set(x / rx, y / ry, z / rz).normalize(); n.setXYZ(i, _n.x, _n.y, _n.z);
    p.setXYZ(i, x * rx + cx, y * ry + cy, z * rz + cz);
  }
  return g;
}
// A limb hangs from its joint (y = 0) to y = -len: thick at the joint (r0), thinner at the far end (r1), with a slight belly.
function limb(len, r0, r1, bulge = 0.12, up = false) {
  const pts = [];
  for (let i = 0; i <= 14; i++) {
    const s = (1 - Math.cos(Math.PI * i / 14)) / 2, base = r1 + (r0 - r1) * s + bulge * r0 * Math.sin(Math.PI * s);
    pts.push(new THREE.Vector2(Math.max(1e-4, base * Math.pow(Math.sin(Math.PI * s), 0.4)), -len + s * len));
  }
  const g = new THREE.LatheGeometry(pts, 12);
  if (up) g.rotateX(Math.PI);
  return g;
}
const UPPER = 0.29, FORE = 0.27;
const HEAD_PROFILE = [[0, 0.018, 0.027, 0.025], [0.018, 0.050, 0.057, 0.026], [0.05, 0.071, 0.075, 0.020], [0.10, 0.088, 0.093, 0.012],
  [0.15, 0.092, 0.098, 0.008], [0.195, 0.080, 0.086, 0.005], [0.225, 0.050, 0.054, 0.005], [0.234, 0.001, 0.001, 0.005]];
// One continuous cap follows the actual sculpted head profile. The former two spherical patches intersected the
// broader forehead, exposing small scalp islands; a smoothly varying hairline stays outside the head everywhere.
function hairCap() {
  const positions = [], indices = [], segments = 36, rows = 16;
  const section = y => {
    let i = 0; while (i < HEAD_PROFILE.length - 2 && y > HEAD_PROFILE[i + 1][0]) i++;
    const a = HEAD_PROFILE[i], b = HEAD_PROFILE[i + 1], t = Math.min(1, Math.max(0, (y - a[0]) / (b[0] - a[0])));
    return [1, 2, 3].map(k => a[k] + (b[k] - a[k]) * t);
  };
  for (let row = 0; row <= rows; row++) for (let i = 0; i <= segments; i++) {
    const phi = i / segments * Math.PI * 2, line = 0.103 + 0.052 * Math.sin(phi), y = 0.234 + (line - 0.234) * row / rows;
    const [rx, rz, cz] = section(y), grow = row === 0 ? 0 : 0.004;
    positions.push(row ? (rx + grow) * Math.cos(phi) : 0, y + 0.004, cz + (row ? (rz + grow) * Math.sin(phi) : 0));
    if (row && i) { const n = row * (segments + 1) + i; indices.push(n, n - 1, n - segments - 2, n, n - segments - 2, n - segments - 1); }
  }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3)); g.setIndex(indices); g.computeVertexNormals(); return g;
}
// The generator's relaxed stand (degrees) as this mannequin's rest: a slight curve in the back, arms a little out and bent.
// Its "l" side is +x, the render mannequin's right.
const REST = { spine: [3, 0, 0], chest: [-3, 0, 0], neck: [8, 0, 0], head: [-6, 0, 0], shoulderR: [3, 0, 9], shoulderL: [3, 0, -9], elbowR: [-14, 0, 0], elbowL: [-14, 0, 0],
  hipR: [0, 0, 3], hipL: [0, 0, -3], ankleR: [0, 0, -3], ankleL: [0, 0, 3] };

// A person. figure: { build, outfit, hair } (plan.js FIGURE_OPTIONS); tone: their colour in the board look.
// render: { coat, skin, hair } materials for the render look (owned by the stage); without it, the board look.
export function buildFigure(figure = {}, tone = 0, render = null) {
  const scale = 1.045 * (BUILD[figure.build] || 1);  // 1.045: an adult's head tops out at 1.92 m, as on the first mannequin
  let mats, fills;
  const owned = [];
  if (render) {
    const feature = new THREE.MeshLambertMaterial({ color: 0x454543 }), lip = new THREE.MeshLambertMaterial({ color: 0x9c8271 });
    owned.push(feature, lip);
    fills = { body: render.coat, chest: render.coat, pants: render.pants || render.coat, head: render.skin, nose: render.skin, neck: render.skin, hand: render.skin, finger: render.skin, foot: render.hair, hair: render.hair, feature, lip };
  } else {
    const [color, line] = CAST_COLORS[tone % CAST_COLORS.length];
    mats = { body: fillMat(color, line), chest: fillMat(color, line, 2), head: fillMat(color, line, 1), hair: fillMat(line, line),
      line: lineMat(line, 0.0062, scale), lineHand: lineMat(line, 0.0042, scale), lineFinger: lineMat(line, 0.0026, scale) };
    fills = { chest: mats.chest, head: mats.head, nose: mats.head, hair: mats.hair, feature: mats.hair, lip: mats.hair };
  }
  const root = new THREE.Group(), body = new THREE.Group(); body.scale.setScalar(scale); root.add(body);
  const joint = (parent, x, y, z, order = 'XZY') => { const g = new THREE.Bone(); g.position.set(x, y, z); g.rotation.order = order; parent.add(g); return g; };
  const part = (parent, geo, kind) => {
    const m = new THREE.Mesh(geo, fills[kind] || (render ? render.coat : mats.body)); parent.add(m);
    if (!render && kind !== 'feature' && kind !== 'lip') { const o = new THREE.Mesh(geo, kind === 'finger' ? mats.lineFinger : kind === 'hand' ? mats.lineHand : mats.line); o.userData.outline = true; parent.add(o); }
    return m;
  };
  const chain = (start, L, r) => {
    const js = [start]; let parent = start; start.userData.tip = L[L.length - 1];
    L.forEach((len, k) => {
      if (k) { const j = new THREE.Group(); j.position.set(0, -L[k - 1], 0); parent.add(j); js.push(j); parent = j; }
      part(parent, limb(len + r * 0.5, r * (1 - 0.08 * k), r * (0.86 - 0.08 * k), 0.04), 'finger');
    });
    return js;
  };
  const hand = (wrist, side) => {  // relaxed fingers (rig.js setHand 'relax')
    // userData.kp tags the hand's OpenPose keypoints (stage_render.py pose): wrist, then 4 per finger from the thumb.
    const s = side > 0 ? 'R' : 'L'; wrist.userData.kp = 'wrist' + s;
    // The cuff ends just above the wrist. A short tapered skin bridge overlaps both cuff and palm, so a hand never
    // floats below the sleeve when the elbow bends. It follows the wrist, without changing any hand landmarks.
    part(wrist, profileGeometry([[-0.035, 0.024, 0.019], [-0.005, 0.026, 0.021], [0.035, 0.030, 0.024]]), 'hand');
    const tag = (js, f) => { const tip = js[0].userData.tip; js.forEach((j, k) => { j.userData.kp = `f${f}_${k}${s}`; j.userData.tip = k === js.length - 1 ? tip : 0; }); };
    const base = new THREE.Group(); base.rotation.y = -Math.PI / 2 * side; wrist.add(base);
    part(base, ellipsoid(0.042, 0.05, 0.017, 0, -0.052, 0, 14, 10), 'hand');
    const tb = new THREE.Group(); tb.position.set(0.03 * side, -0.028, 0.012); tb.rotation.order = 'ZXY'; base.add(tb);
    const thumb = chain(tb, [0.036, 0.029, 0.023], 0.0115); tag(thumb, 0);
    thumb[0].rotation.set(-0.35 - 0.25 * 0.55, 0.15 * side, (0.62 - 0.25 * 0.5) * side); thumb[1].rotation.x = -0.25 * 0.7; thumb[2].rotation.x = -0.25 * 0.8;
    [[0.026, [0.041, 0.026, 0.02], 0.0095, 0.22, 0.17], [0.009, [0.045, 0.029, 0.021], 0.0098, 0.3, 0.05], [-0.009, [0.042, 0.027, 0.02], 0.0093, 0.36, -0.07], [-0.025, [0.034, 0.021, 0.018], 0.0084, 0.42, -0.19]]
      .forEach(([fx, L, r, c, spread], f) => {
        const g = new THREE.Group(); g.position.set(fx * side, -0.097, 0); g.rotation.order = 'ZXY'; base.add(g);
        const js = chain(g, L, r); tag(js, f + 1); js[0].rotation.set(-c * 1.3, 0, spread * 0.25 * side); js[1].rotation.x = -c * 1.6; js[2].rotation.x = -c * 1.15;
      });
  };
  const pelvis = joint(body, 0, 0.95, 0, 'YXZ');
  const spine = joint(pelvis, 0, 0.05, 0, 'YXZ');
  const chest = joint(spine, 0, 0.2, 0, 'YXZ');
  const neck = joint(chest, 0, 0.31, 0, 'YXZ'); part(neck, profileGeometry([[0, 0.056, 0.050], [0.025, 0.049, 0.046], [0.11, 0.047, 0.044], [0.14, 0.055, 0.05]]), 'neck');
  const collar = new THREE.TorusGeometry(0.055, 0.006, 8, 28); collar.rotateX(Math.PI / 2); collar.translate(0, 0.054, 0); part(neck, collar, 'body');
  const head = joint(neck, 0, 0.1, 0, 'YXZ');
  part(head, profileGeometry(HEAD_PROFILE), 'head');
  part(head, ellipsoid(0.012, 0.020, 0.018, 0, 0.099, 0.111, 14, 10), 'nose');
  for (const side of [-1, 1]) {
    part(head, ellipsoid(0.014, 0.025, 0.017, side * 0.09, 0.105, 0.008, 14, 10), 'head');
    part(head, ellipsoid(0.010, 0.005, 0.003, side * 0.035, 0.133, 0.100, 12, 8), 'feature');
    part(head, ellipsoid(0.015, 0.002, 0.003, side * 0.035, 0.150, 0.102, 12, 8), 'feature');
  }
  part(head, ellipsoid(0.018, 0.0018, 0.002, 0, 0.057, 0.098, 16, 8), 'lip');
  part(head, hairCap(), 'hair');
  if (figure.hair === 'bun') part(head, ellipsoid(0.05, 0.05, 0.05, 0, 0.2, -0.07), 'hair');
  if (figure.hair === 'long') part(head, ellipsoid(0.095, 0.15, 0.05, 0, 0.02, -0.075), 'hair');
  const hem = { longcoat: [0.17, 0.23, 0.5], dress: [0.16, 0.27, 0.68], robe: [0.17, 0.28, 0.86] }[figure.outfit];
  if (hem) part(pelvis, profileGeometry([[-hem[2], hem[1], hem[1] * 0.65], [-hem[2] * 0.7, hem[0] + (hem[1] - hem[0]) * 0.7, 0.14], [0.025, hem[0], 0.11]]), 'body');
  const J = { pelvis, spine, chest, neck, head };
  for (const side of [1, -1]) {
    const s = side > 0 ? 'R' : 'L';
    const sh = joint(chest, 0.2 * side, 0.27, 0, 'YXZ');
    const el = joint(sh, 0, -UPPER, 0, 'YXZ');
    hand(joint(el, 0, -FORE, 0), side);
    const hp = joint(pelvis, 0.095 * side, -0.06, 0);
    const kn = joint(hp, 0, -0.42, 0);
    const an = joint(kn, 0, -0.4, 0);
    part(an, profileGeometry([[-0.075, 0.006, 0.012, -0.034], [-0.065, 0.041, 0.036, -0.033], [-0.025, 0.047, 0.043, -0.027], [0.045, 0.049, 0.038, -0.032], [0.135, 0.045, 0.025, -0.045], [0.175, 0.029, 0.018, -0.052], [0.188, 0.001, 0.001, -0.052]], 24, 'z'), 'foot');
    Object.assign(J, { ['shoulder' + s]: sh, ['elbow' + s]: el, ['hip' + s]: hp, ['knee' + s]: kn, ['ankle' + s]: an });
  }
  for (const [name, g] of Object.entries(J)) g.userData.kp = name;
  const D = Math.PI / 180, rest = Object.fromEntries(Object.entries(REST).map(([k, v]) => [k, v.map(x => x * D)]));
  for (const [name, g] of Object.entries(J)) g.rotation.set(...(rest[name] || [0, 0, 0]));
  root.updateMatrixWorld(true);
  const bones = [], boneIndex = {}, points = {};
  root.traverse(o => { if (o.isBone && o.userData.kp) { boneIndex[o.userData.kp] = bones.length; bones.push(o); points[o.userData.kp] = body.worldToLocal(o.getWorldPosition(new THREE.Vector3())).toArray(); } });
  const skeleton = new THREE.Skeleton(bones), garments = garmentGeometries(points, boneIndex, figure);
  for (const [name, geo] of Object.entries(garments)) {
    const garment = new THREE.SkinnedMesh(geo, fills[name === 'shirt' ? 'body' : 'pants'] || mats.body); garment.name = name; garment.frustumCulled = false;
    body.add(garment); root.updateMatrixWorld(true); garment.bind(skeleton); garment.userData.garment = name;
    if (!render) { const outline = new THREE.SkinnedMesh(geo, mats.line); outline.frustumCulled = false; outline.userData.outline = true; body.add(outline); root.updateMatrixWorld(true); outline.bind(skeleton); }
  }
  root.traverse(o => { o.userData.actor = true; });
  return { root, joints: J, rest, pelvisY: 0.95, mats: [...(mats ? Object.values(mats) : []), ...owned] };  // supplied render materials remain stage-owned
}
