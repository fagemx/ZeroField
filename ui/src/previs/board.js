// The board look: how the director reads the stage while blocking. The mannequin, its shading and its outline are the
// shot-idiom generator's (docs/prototypes/shot-idiom-generator/rig.js in ad_growth_data, same author): an artist's
// drawing mannequin with an egg head, round ball joints, a full chest, tapering limbs and fingered hands, a flat
// two-tone fill in the person's own colour, construction lines and a thick outline, on a high-key set. It never goes
// into a previs: outlines turn the motion pass cartoon (scene.js), so Render previs keeps the grey render look.
// Joints carry the render mannequin's names (scene.js actor), so the same poses and performance keys drive both.
import * as THREE from 'three';

// Fill and outline colour per cast member, in cast order (the first is the shot's subject).
export const CAST_COLORS = [['#a9c8ea', '#2e5f9c'], ['#e2a08f', '#8e2f22'], ['#bda6dc', '#4b3274'], ['#a8d4b0', '#2f6b3c']];
export const SET = { background: 0xcfd6d3, floor: 0xe4e8e6, glass: 0x9aa49f, brass: 0xd8cfb8, night: 0xaeb8c4 };

/* ---------- shaders (rig.js): two-tone fill with constant-width construction lines, and an inverted-hull outline ---------- */
const FILL_VS = `
varying vec3 vN; varying vec3 vV; varying vec3 vP;
void main(){ vP = position; vec4 mv = modelViewMatrix * vec4(position, 1.0); vV = mv.xyz;
  vN = normalize(normalMatrix * normal); gl_Position = projectionMatrix * mv; }`;
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
void main(){ vec4 mv0 = modelViewMatrix * vec4(position, 1.0); float t = (uThick + uPx * max(-mv0.z, 0.01)) / uScale;
  gl_Position = projectionMatrix * viewMatrix * modelMatrix * vec4(position + normal * t, 1.0); }`;
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
// The generator's relaxed stand (degrees) as this mannequin's rest: a slight curve in the back, arms a little out and bent.
// Its "l" side is +x, the render mannequin's right.
const REST = { spine: [3, 0, 0], chest: [-3, 0, 0], neck: [8, 0, 0], head: [-6, 0, 0], shoulderR: [3, 0, 9], shoulderL: [3, 0, -9], elbowR: [-14, 0, 0], elbowL: [-14, 0, 0],
  hipR: [0, 0, 3], hipL: [0, 0, -3], ankleR: [0, 0, -3], ankleL: [0, 0, 3] };
const BUILD = { man: 1, woman: 0.94, child: 0.64, elder: 1 };

// A person in the board look. figure: { build, outfit, hair } (plan.js FIGURE_OPTIONS); i: their place in the cast.
export function boardActor(figure = {}, i = 0) {
  const [color, line] = CAST_COLORS[i % CAST_COLORS.length], scale = 1.045 * (BUILD[figure.build] || 1);  // 1.045: the head tops out where the render mannequin's does
  const mats = { body: fillMat(color, line), chest: fillMat(color, line, 2), head: fillMat(color, line, 1), hair: fillMat(line, line),
    line: lineMat(line, 0.0062, scale), lineHand: lineMat(line, 0.0042, scale), lineFinger: lineMat(line, 0.0026, scale) };
  const root = new THREE.Group(), body = new THREE.Group(); body.scale.setScalar(scale); root.add(body);
  const joint = (parent, x, y, z, order = 'XZY') => { const g = new THREE.Group(); g.position.set(x, y, z); g.rotation.order = order; parent.add(g); return g; };
  const part = (parent, geo, kind) => {
    const fill = { chest: mats.chest, head: mats.head, hair: mats.hair }[kind] || mats.body;
    const ln = kind === 'finger' ? mats.lineFinger : kind === 'hand' ? mats.lineHand : mats.line;
    const m = new THREE.Mesh(geo, fill), o = new THREE.Mesh(geo, ln); o.userData.outline = true; parent.add(m, o); return m;
  };
  const chain = (start, L, r) => {
    const js = [start]; let parent = start;
    L.forEach((len, k) => {
      if (k) { const j = new THREE.Group(); j.position.set(0, -L[k - 1], 0); parent.add(j); js.push(j); parent = j; }
      part(parent, limb(len + r * 0.5, r * (1 - 0.08 * k), r * (0.86 - 0.08 * k), 0.04), 'finger');
    });
    return js;
  };
  const hand = (wrist, side) => {  // relaxed fingers (rig.js setHand 'relax')
    const base = new THREE.Group(); base.rotation.y = -Math.PI / 2 * side; wrist.add(base);
    part(base, ellipsoid(0.042, 0.05, 0.017, 0, -0.052, 0, 14, 10), 'hand');
    const tb = new THREE.Group(); tb.position.set(0.03 * side, -0.028, 0.012); tb.rotation.order = 'ZXY'; base.add(tb);
    const thumb = chain(tb, [0.036, 0.029, 0.023], 0.0115);
    thumb[0].rotation.set(-0.35 - 0.25 * 0.55, 0.15 * side, (0.62 - 0.25 * 0.5) * side); thumb[1].rotation.x = -0.25 * 0.7; thumb[2].rotation.x = -0.25 * 0.8;
    [[0.026, [0.041, 0.026, 0.02], 0.0095, 0.22, 0.17], [0.009, [0.045, 0.029, 0.021], 0.0098, 0.3, 0.05], [-0.009, [0.042, 0.027, 0.02], 0.0093, 0.36, -0.07], [-0.025, [0.034, 0.021, 0.018], 0.0084, 0.42, -0.19]]
      .forEach(([fx, L, r, c, spread]) => {
        const g = new THREE.Group(); g.position.set(fx * side, -0.097, 0); g.rotation.order = 'ZXY'; base.add(g);
        const js = chain(g, L, r); js[0].rotation.set(-c * 1.3, 0, spread * 0.25 * side); js[1].rotation.x = -c * 1.6; js[2].rotation.x = -c * 1.15;
      });
  };
  const pelvis = joint(body, 0, 0.95, 0, 'YXZ'); part(pelvis, ellipsoid(0.16, 0.11, 0.105, 0, -0.02, 0), 'body');
  const spine = joint(pelvis, 0, 0.05, 0, 'YXZ'); part(spine, ellipsoid(0.125, 0.12, 0.09, 0, 0.09, 0.005), 'body');
  const chest = joint(spine, 0, 0.2, 0, 'YXZ'); part(chest, ellipsoid(0.175, 0.165, 0.105, 0, 0.15, 0.01), 'chest');
  const neck = joint(chest, 0, 0.31, 0, 'YXZ'); part(neck, limb(0.12, 0.043, 0.046, 0.05, true), 'body');
  const head = joint(neck, 0, 0.1, 0, 'YXZ'); part(head, ellipsoid(0.092, 0.118, 0.103, 0, 0.115, 0.01), 'head');
  part(head, ellipsoid(0.014, 0.022, 0.017, 0, 0.094, 0.113, 10, 8), 'head');  // nose
  if (figure.hair === 'bun') part(head, ellipsoid(0.05, 0.05, 0.05, 0, 0.2, -0.07), 'hair');
  if (figure.hair === 'long') part(head, ellipsoid(0.095, 0.15, 0.05, 0, 0.02, -0.075), 'hair');
  const hem = { longcoat: [0.17, 0.25, 0.5], dress: [0.16, 0.3, 0.68], robe: [0.17, 0.3, 0.86] }[figure.outfit];
  if (hem) part(pelvis, limb(hem[2], hem[0], hem[1], 0).translate(0, 0.02, 0), 'body');  // narrow at the waist, wide at the hem
  const J = { pelvis, spine, chest, neck, head };
  for (const side of [1, -1]) {
    const s = side > 0 ? 'R' : 'L';
    const sh = joint(chest, 0.2 * side, 0.27, 0, 'YXZ'); part(sh, ellipsoid(0.058, 0.058, 0.058), 'body'); part(sh, limb(UPPER, 0.05, 0.04, 0.15), 'body');
    const el = joint(sh, 0, -UPPER, 0, 'YXZ'); part(el, ellipsoid(0.038, 0.038, 0.038), 'body'); part(el, limb(FORE, 0.042, 0.03, 0.12), 'body');
    hand(joint(el, 0, -FORE, 0), side);
    const hp = joint(pelvis, 0.095 * side, -0.06, 0); part(hp, ellipsoid(0.075, 0.075, 0.075), 'body'); part(hp, limb(0.42, 0.075, 0.05, 0.12), 'body');
    const kn = joint(hp, 0, -0.42, 0); part(kn, ellipsoid(0.05, 0.05, 0.05), 'body'); part(kn, limb(0.4, 0.056, 0.036, 0.14), 'body');
    const an = joint(kn, 0, -0.4, 0); part(an, ellipsoid(0.046, 0.036, 0.115, 0, -0.035, 0.055), 'body');
    Object.assign(J, { ['shoulder' + s]: sh, ['elbow' + s]: el, ['hip' + s]: hp, ['knee' + s]: kn, ['ankle' + s]: an });
  }
  root.traverse(o => { o.userData.actor = true; });
  const D = Math.PI / 180, rest = Object.fromEntries(Object.entries(REST).map(([k, v]) => [k, v.map(x => x * D)]));
  return { root, joints: J, rest, pelvisY: 0.95, mats: Object.values(mats) };
}
