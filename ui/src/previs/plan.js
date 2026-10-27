// Previs plans as plain data: camera keys, lens and actor action for one shot. No three.js here, so it is testable in node.
// A story shot's plan is stored in the project (SPEC_20 R26); project_docs/story_previs.py validates it against the enums
// here. plan.code and plan.cast[i].code name who plays the actor and each other cast member (@CAST-01, from the cast sheet).
// Coordinates are station-local: the actor stands at the console station facing +z (toward the glass); his reaching
// arm is on -x, which a camera behind him sees on screen right (the same screen layout as the Blender blockouts).
import { bezierAt } from '../controls/controlsModel.js';

export const FPS = 24, WIDTH = 1280, HEIGHT = 704;
export const DURATIONS = [4, 6, 8, 10];  // seconds; LTX-2.5 takes 8n+1 frames, including a 241-frame rehearsal
export const FRAMES = 97;  // the 4-second default
export const framesOf = plan => (DURATIONS.includes(plan?.seconds) ? plan.seconds : 4) * FPS + 1;
// Camera keys and the actor's timing are written on a 0..96 beat clock, so a longer shot plays the same blocking slower.
const beat = (plan, f) => f * 96 / (framesOf(plan) - 1);
export const LENSES = [24, 35, 50, 85];
export const MOVES = ['pushin', 'pullout', 'orbit', 'crane', 'track', 'static'];
export const ACTIONS = ['turnreach', 'stand', 'walkin'];
export const MOODS = ['grey', 'night'];
export const FACINGS = ['console', 'room'];  // the actor faces the console and glass, or turns to the room (the camera side)
export const SETS = ['observatory', 'parallax', 'empty'];
// The 2.5D parallax set (80.lv, Guillaume Scoffié): flat cards at depth around the actor's mark (+z behind him, -z in
// front). plan.layers [{id, role?, z?, x?, y?, scale?, billboard? (true | false | 'full'), src?, color?, opacity?}] take
// these as defaults by role; plan.beacon false switches the observatory's sun off (other sets have none).
export const PARALLAX_DEFAULTS = [
  { id: 'far', role: 'far', z: 4.8, y: 1.8, scale: 1.0, billboard: true, opacity: 1.0 },
  { id: 'mid', role: 'mid', z: 2.2, y: 1.5, scale: 0.85, billboard: true, opacity: 1.0 },
  { id: 'near', role: 'near', z: -0.7, y: 1.1, scale: 0.55, billboard: true, opacity: 0.9 },
];
// A plan's cards, far to near.
export function parallaxLayers(plan) {
  if (plan.layers?.length) {
    const role = l => PARALLAX_DEFAULTS.find(d => d.role === (l.role || l.id)) || PARALLAX_DEFAULTS[1];
    return plan.layers.map(l => ({ ...role(l), ...l })).sort((a, b) => b.z - a.z);
  }
  return plan.set === 'parallax' ? PARALLAX_DEFAULTS.map(l => ({ ...l })) : [];
}
// Yaw that turns a card's front (-z) to the camera about the vertical only, so a card never tips over.
export const billboardYaw = (cameraPos, layerPos) => Math.atan2(cameraPos[0] - layerPos[0], cameraPos[2] - layerPos[2]) + Math.PI;
// The observatory dome: centre on the floor, glass radius, wall height, and the open floor inside the console ring.
export const DOME = { x: 0, z: -4.1, radius: 6, base: 1.15, floor: 4.4 };

// Camera keys: [beat, position [x, y, z], aim [x, y, z]], beats 0..96 over the shot.
const PRESETS = {
  pushin: [[0, [1.4, 1.45, -5.8], [-0.2, 2.75, 0.4]], [48, [0.55, 1.8, -2.6], [-0.1, 1.5, 0.5]], [96, [-0.75, 1.95, -0.85], [-0.05, 1.32, 0.55]]],
  orbit: [[0, [2.3, 1.7, -1.6], [0, 1.4, 0.15]], [48, [0.1, 1.7, -2.6], [0, 1.4, 0.15]], [96, [-2.1, 1.7, -1.4], [0, 1.4, 0.15]]],
  crane: [[0, [0.8, 0.6, -2.1], [0, 1.6, 0.2]], [96, [0.45, 3.6, -1.6], [-0.05, 1.0, 0.4]]],
  track: [[0, [2.4, 1.6, -2.2], [0.6, 1.4, 0.4]], [96, [-2.2, 1.6, -2.2], [-0.6, 1.4, 0.4]]],
  static: [[0, [-0.9, 1.8, -1.6], [0, 1.35, 0.45]], [96, [-0.9, 1.8, -1.6], [0, 1.35, 0.45]]],
};
PRESETS.pullout = PRESETS.pushin.slice().reverse().map(([, pos, aim], i, all) => [all.length === 1 ? 0 : (i * 96) / (all.length - 1), pos, aim]);

const ease = t => t * t * (3 - 2 * t);

export function defaultPlan() {
  return { set: 'observatory', move: 'pushin', lens: 35, action: 'turnreach', facing: 'console', mood: 'grey', seconds: 4, keys: null };
}

// A shot's first plan comes from what the slate already says: Camera Motion, the lens in Optical Rig, the action text.
export function planFromSlate({ motion = '', rig = '', action = '' } = {}) {
  const plan = defaultPlan(), m = motion.toLowerCase(), mm = Number(rig.match(/(\d+)\s*mm/i)?.[1]);
  plan.move = /pull|dolly out|reveal/.test(m) ? 'pullout' : /push|dolly in|zoom in/.test(m) ? 'pushin' : /orbit|arc/.test(m) ? 'orbit'
    : /crane|jib|boom/.test(m) ? 'crane' : /track|truck|follow/.test(m) ? 'track' : /static|tripod|locked/.test(m) ? 'static' : plan.move;
  if (mm) plan.lens = LENSES.reduce((a, b) => (Math.abs(b - mm) < Math.abs(a - mm) ? b : a));
  plan.action = /\b(walks?|enters?|approach)/i.test(action) ? 'walkin' : /\b(turns?|reach|dial|press)/i.test(action) ? 'turnreach' : 'stand';
  return plan;
}

// Presets are framed for 35 mm. Another lens dollies along each key's line of sight to hold the shot size (what a DP does
// when swapping lenses), stopping on the open floor of the dome. Framed keys are the user's own and stay as they are.
export function cameraKeys(plan) {
  if (plan.keys && plan.keys.length >= 2) return plan.keys;
  const k = (plan.lens || 35) / 35;
  return (PRESETS[plan.move] || PRESETS.pushin).map(([f, pos, aim]) => [f, insideDome(aim, pos.map((v, i) => (v - aim[i]) * k)), aim]);
}
// The point along aim + offset nearest to the full offset that stays on the dome's open floor, under the glass (ops.js too).
export function insideDome(aim, offset) {
  for (let t = 1; t > 0; t -= 0.02) {
    const p = aim.map((v, i) => v + offset[i] * t), d = Math.hypot(p[0] - DOME.x, p[2] - DOME.z);
    if (p[1] >= 0.3 && d <= DOME.floor && p[1] <= DOME.base + Math.sqrt(Math.max(0, DOME.radius ** 2 - d * d)) - 0.3) return p;
  }
  return aim;
}

// Camera at frame f: eased piecewise interpolation between keys.
// A smooth path through every key (Hermite with Catmull-Rom tangents on the key beats), eased in and out over the
// whole shot: multi-key moves flow through their middle keys instead of stopping at each one. Two keys stay a plain ease.
// plan.easing [x1, y1, x2, y2] (a cubic-bezier, as the control kit's curve editor writes it) replaces the in-and-out ease for the
// move between the first and last key; a y beyond 0..1 overshoots the end key and settles back.
export function sampleCamera(plan, frame) {
  const keys = cameraKeys(plan), first = keys[0][0], end = keys[keys.length - 1][0], b = beat(plan, frame);
  if (b <= first) return { position: keys[0][1], aim: keys[0][2] };
  if (b >= end) return { position: keys[keys.length - 1][1], aim: keys[keys.length - 1][2] };  // land exactly on the end key
  const progress = (b - first) / (end - first), u = first + (Array.isArray(plan.easing) ? bezierAt(plan.easing, progress) : ease(progress)) * (end - first);
  let i = 0;
  while (i < keys.length - 2 && u > keys[i + 1][0]) i++;
  const k0 = keys[Math.max(0, i - 1)], k1 = keys[i], k2 = keys[i + 1], k3 = keys[Math.min(keys.length - 1, i + 2)];
  const span = Math.max(1e-6, k2[0] - k1[0]), t = (u - k1[0]) / span;
  const h = [2 * t ** 3 - 3 * t ** 2 + 1, t ** 3 - 2 * t ** 2 + t, -2 * t ** 3 + 3 * t ** 2, t ** 3 - t ** 2];
  const curve = j => k1[j].map((p1, d) => {
    const m1 = (k2[j][d] - k0[j][d]) * span / Math.max(1e-6, k2[0] - k0[0]), m2 = (k3[j][d] - k1[j][d]) * span / Math.max(1e-6, k3[0] - k1[0]);
    return h[0] * p1 + h[1] * m1 + h[2] * k2[j][d] + h[3] * m2;
  });
  return { position: curve(1), aim: curve(2) };
}

// Vertical field of view for a lens on a 36 mm wide sensor at the shot aspect (same convention as Blender).
export function verticalFov(lens, aspect = WIDTH / HEIGHT) {
  return 2 * Math.atan((36 / aspect) / 2 / lens) * 180 / Math.PI;
}

// Mannequin looks (SPEC_10 P3), built by figure.js. tone: the person's
// colour (board look) and coat shade (render look), so they read as the same person in every shot.
export const FIGURE_OPTIONS = { build: ['man', 'woman', 'child', 'elder'], outfit: ['jacket', 'longcoat', 'dress', 'robe'], hair: ['short', 'long', 'bun'] };
export const BUILD = { man: 1, woman: 0.94, child: 0.64, elder: 1 };  // each build's size against the adult man

// Body poses for the jointed mannequin (SPEC_10 P2): joint rotations in radians [x, y, z] on top of standing, plus how
// far the pelvis drops. +x pitches the spine and neck forward; -x swings an arm or a thigh forward; +x bends a knee back,
// -x bends an elbow forward; -z takes the left arm (on -x) out to the side, +z the right; on arms y turns the raised arm
// in (+ for the left, - for the right) after the forward pitch.
export const POSES = {
  stand: {},
  lean: { spine: [0.34, 0, 0], neck: [-0.18, 0, 0], shoulderL: [-0.3, 0, 0], shoulderR: [-0.3, 0, 0] },  // arms keep hanging
  recoil: { spine: [-0.2, 0, 0], neck: [-0.22, 0, 0], shoulderL: [-0.55, 0, -0.2], shoulderR: [-0.55, 0, 0.2], elbowL: [-1.2, 0, 0], elbowR: [-1.2, 0, 0] },
  slump: { spine: [0.3, 0, 0], neck: [0.45, 0, 0], shoulderL: [-0.18, 0, 0.06], shoulderR: [-0.18, 0, -0.06] },
  lookup: { spine: [-0.1, 0, 0], neck: [-0.6, 0, 0] },
  lookdown: { neck: [0.55, 0, 0] },
  face: { neck: [0.3, 0, 0], shoulderL: [-1.15, 0.45, 0], shoulderR: [-1.15, -0.45, 0], elbowL: [-2.3, 0, 0], elbowR: [-2.3, 0, 0] },
  crossed: { shoulderL: [-0.25, 0, 0.12], shoulderR: [-0.25, 0, -0.12], elbowL: [-1.75, 1.2, 0], elbowR: [-1.55, -1.2, 0] },
  open: { spine: [-0.08, 0, 0], neck: [-0.15, 0, 0], shoulderL: [-0.45, 0, -0.85], shoulderR: [-0.45, 0, 0.85], elbowL: [-0.35, 0, 0], elbowR: [-0.35, 0, 0] },
  kneel: { drop: 0.4, kneeL: [1.57, 0, 0], ankleL: [-1.57, 0, 0], hipR: [-1.4, 0, 0], kneeR: [1.4, 0, 0], spine: [0.1, 0, 0], shoulderL: [-0.1, 0, 0], shoulderR: [-0.1, 0, 0] },  // on his left knee
  push: { spine: [0.15, 0, 0], shoulderL: [-1.4, 0, 0.16], shoulderR: [-1.4, 0, -0.16], elbowL: [-0.2, 0, 0], elbowR: [-0.2, 0, 0] },  // both arms straight out at chest height
  // walkTo's gait: the pelvis down 5 cm on bent knees, ankles still under the hips and feet level, so a planted foot
  // stays in reach while the body passes over it.
  walk: { drop: 0.05, hipL: [-0.342, 0, 0], hipR: [-0.342, 0, 0], kneeL: [0.702, 0, 0], kneeR: [0.702, 0, 0], ankleL: [-0.36, 0, 0], ankleR: [-0.36, 0, 0] },
};
// Facial expressions for the pose skeleton's face points (skeleton.js), not the mannequin's head: jaw opens the mouth,
// wide stretches it, smile lifts (+) or drops (-) the corners, brow raises (+) or lowers (-) the brows, inner lifts the
// inner brows (grief), eyes opens (+) or squeezes (-) them.
export const EXPRESSIONS = {
  neutral: {},
  tense: { wide: -0.2, brow: -0.3 },
  rage: { jaw: 0.35, wide: 0.3, brow: -0.8, eyes: 0.3 },
  scream: { jaw: 1, wide: 0.45, brow: -0.7, eyes: 0.25 },
  cry: { jaw: 0.3, smile: -0.7, inner: 1, eyes: -0.6 },
  fear: { jaw: 0.6, brow: 1, inner: 0.4, eyes: 1 },
  shock: { jaw: 0.5, brow: 0.8, eyes: 0.8 },
};
export function blendFace(from, to, t) {
  const a = EXPRESSIONS[from] || {}, b = EXPRESSIONS[to] || a, out = {};
  for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) out[k] = (a[k] || 0) + ((b[k] || 0) - (a[k] || 0)) * t;
  return out;
}
const JOINTS = ['spine', 'neck', 'shoulderL', 'shoulderR', 'elbowL', 'elbowR', 'hipL', 'hipR', 'kneeL', 'kneeR', 'ankleL', 'ankleR'];
// A pose between two named poses: joint by joint, so a slump into a kneel bends every joint at once. A bent leg shortens
// with the square of its angle, so the pelvis drop blends as a square too and the feet stay on the floor on the way.
export function blendPose(from, to, t) {
  const a = POSES[from] || {}, b = POSES[to] || a, out = { drop: (Math.sqrt(a.drop || 0) + (Math.sqrt(b.drop || 0) - Math.sqrt(a.drop || 0)) * t) ** 2 };
  for (const j of JOINTS) if (a[j] || b[j]) out[j] = [0, 1, 2].map(i => (a[j]?.[i] || 0) + ((b[j]?.[i] || 0) - (a[j]?.[i] || 0)) * t);
  return out;
}

// Performance keys (SPEC_10): [{at 0..1, yaw?, reach?, back?, side?, body?, face?, headYaw?, armSwing?, sway?, bounce?}].
// headYaw is a local gaze turn in radians, distributed over neck/head by the rig. Gait channels add to the body pose.
// Each channel eases from the key
// that last set it to the next key that sets it; yaw is absolute (the plan's facing is not added); back (-z) and side (+x)
// move the actor off the mark. The shot grammar writes these when the director re-times what the actor does; a plan
// without them plays its canned action.
export function sampleActs(acts, u) {
  const out = {}, at = (keys, x) => { let i = 0; while (i < keys.length - 1 && x >= keys[i + 1].at) i++; return i; };
  for (const ch of ['yaw', 'reach', 'back', 'side', 'body', 'face', 'armSwing', 'sway', 'bounce', 'headYaw']) {
    const keys = acts.filter(k => k[ch] != null).sort((p, q) => p.at - q.at);
    if (!keys.length) continue;
    if (ch === 'body' && keys[0].at > 0) keys.unshift({ at: 0, body: 'stand' });  // he starts standing and arrives in the pose by its key
    if (ch === 'face' && keys[0].at > 0) keys.unshift({ at: 0, face: 'neutral' });
    const i = at(keys, u), a = keys[i], b = keys[i + 1], t = !b || u <= a.at ? 0 : ease(Math.min(1, (u - a.at) / Math.max(1e-6, b.at - a.at)));
    out[ch] = ch === 'body' ? blendPose(a.body, b?.body, t) : ch === 'face' ? blendFace(a.face, b?.face, t) : a[ch] + ((b?.[ch] ?? a[ch]) - a[ch]) * t;
  }
  const pose = out.body || {};
  if (out.armSwing != null) {
    for (const [s, sign] of [['L', 1], ['R', -1]]) {
      pose['shoulder' + s] = [...(pose['shoulder' + s] || [0, 0, 0])]; pose['shoulder' + s][0] += sign * out.armSwing;
      pose['elbow' + s] = [...(pose['elbow' + s] || [0, 0, 0])]; pose['elbow' + s][0] -= Math.abs(out.armSwing) * 0.35;
    }
  }
  if (out.sway != null) { pose.spine = [...(pose.spine || [0, 0, 0])]; pose.spine[2] += out.sway; }
  if (out.bounce != null) pose.drop = Math.max(0, (pose.drop || 0) + out.bounce);
  return { yaw: out.yaw || 0, reach: out.reach || 0, back: out.back || 0, side: out.side || 0, headYaw: out.headYaw || 0, pose, face: out.face || {} };
}

// Actor at frame f: body yaw (radians, 0 = facing the console), shoulder pitch (0 = arm down), distance back from the
// station and the body pose. Facing the room turns the actor around (the motion pass keeps who faces the camera only
// when the previs shows it); walking in while facing the room walks from the console toward the cameras.
export function sampleActor(plan, frame) {
  if (plan.acts?.length) return sampleActs(plan.acts, frame / (framesOf(plan) - 1));
  const f = beat(plan, frame), k = (a, b, t) => a + (b - a) * ease(Math.min(1, Math.max(0, t))), room = plan.facing === 'room', turn = room ? Math.PI : 0;
  if (plan.action === 'stand') return { yaw: turn, reach: 0, back: 0, pose: {} };
  if (plan.action === 'walkin') return sampleActs(motionPlan(plan).acts, frame / (framesOf(plan) - 1));
  return { yaw: k(-1.75, 0, f / 39) + turn, reach: k(0, 1.16, (f - 22) / 22), back: 0, pose: {} };  // turnreach: from the glass to the dial
}

// Direct motion space (MSFlow, LY Corp, CC0): a motion is 22 joints as stage XYZ per frame, in SMPL order (every parent
// before its children). L and R follow figure.js (L is on -x, the reaching arm), so a pin on wristL is the hand at the dial.
// plan.pins [{at 0..1, joint, pos [x, y, z], radius? (time sigma, default 0.22)}]: any joint at any moment, without training.
export const MSFLOW_JOINTS = ['pelvis', 'hipL', 'hipR', 'spine1', 'kneeL', 'kneeR', 'spine2', 'ankleL', 'ankleR',
  'spine3', 'footL', 'footR', 'neck', 'collarL', 'collarR', 'head', 'shoulderL', 'shoulderR', 'elbowL', 'elbowR', 'wristL', 'wristR'];
const PARENT = [-1, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 9, 12, 13, 14, 16, 17, 18, 19];
const SUBTREE = MSFLOW_JOINTS.map((_, j) => MSFLOW_JOINTS.filter((_, k) => { for (let a = k; a >= 0; a = PARENT[a]) if (a === j) return true; return false; }));
const LIMB = { wristL: ['shoulderL', 'elbowL'], wristR: ['shoulderR', 'elbowR'], ankleL: ['hipL', 'kneeL'], ankleR: ['hipR', 'kneeR'] };
const add = (a, b) => a.map((v, i) => v + b[i]), sub = (a, b) => a.map((v, i) => v - b[i]), mul = (a, k) => a.map(v => v * k);
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2], len = a => Math.sqrt(dot(a, a));
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const unit = a => mul(a, 1 / (len(a) || 1));
const turnAbout = (v, axis, angle) => {  // Rodrigues: v turned by angle about the unit axis
  const c = Math.cos(angle), s = Math.sin(angle);
  return add(add(mul(v, c), mul(cross(axis, v), s)), mul(axis, dot(axis, v) * (1 - c)));
};
function solveLinear(A, b) {  // Gauss-Jordan with partial pivoting; pins are few
  const n = b.length, M = A.map((row, i) => [...row, b[i]]);
  for (let c = 0; c < n; c++) {
    let p = c; for (let i = c + 1; i < n; i++) if (Math.abs(M[i][c]) > Math.abs(M[p][c])) p = i;
    [M[c], M[p]] = [M[p], M[c]];
    for (let i = 0; i < n; i++) if (i !== c) { const k = M[i][c] / M[c][c]; for (let j = c; j <= n; j++) M[i][j] -= k * M[c][j]; }
  }
  return M.map((row, i) => row[n] / row[i]);
}

// Two-bone analytical IK (law of cosines): the middle joint for a root, a target and two bone lengths, bending in the
// plane the current middle joint sets. A target out of reach straightens the limb toward it (end is where it lands).
export function solveLimbIK(rootPos, midPos, endTarget, len1, len2) {
  const to = sub(endTarget, rootPos), D = len(to), d = Math.min(len1 + len2, Math.max(Math.abs(len1 - len2) + 1e-9, D));
  const dir = D > 1e-9 ? mul(to, 1 / D) : [0, -1, 0], a = (len1 * len1 - len2 * len2 + d * d) / (2 * d), h = Math.sqrt(Math.max(0, len1 * len1 - a * a));
  const m = sub(midPos, rootPos);
  let pole = sub(m, mul(dir, dot(m, dir)));
  if (len(pole) < 1e-9) pole = cross(dir, Math.abs(dir[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0]);  // a straight limb bends in any plane
  return { mid: add(rootPos, add(mul(dir, a), mul(unit(pole), h))), end: add(rootPos, mul(dir, d)) };
}

// Pins on a motion in direct motion space (MSFlow's inference-time projection, as a closed-form solve): every pin lands
// exactly on its frame, the change fades out in time with a Gaussian, and a pin moves its joint's whole subtree (a pinned
// pelvis carries the body). A hand or head pinned beyond its bones first leans the upper body toward it about spine1,
// then moves the body for what is left; a foot moves the body. Elbows and knees are re-solved with two-bone IK so the
// limbs keep their length. baseFrames: [{joint: [x, y, z]}] per frame (the mannequin's FK, or MSFlow's output).
const REACH = { wristL: 'shoulderL', wristR: 'shoulderR', head: 'neck', ankleL: 'hipL', ankleR: 'hipR' };
export function solvePinnedXYZ(baseFrames, pins = []) {
  const F = baseFrames.length, frames = baseFrames.map(fr => Object.fromEntries(Object.entries(fr).map(([k, v]) => [k, [...v]])));
  const valid = (pins || []).filter(p => MSFLOW_JOINTS.includes(p.joint) && Number.isFinite(p.at) && p.pos?.length === 3 && p.pos.every(Number.isFinite));
  if (!F || !valid.length) return frames;
  const frameOf = p => Math.round(Math.min(1, Math.max(0, p.at)) * (F - 1)), sigma = p => p.radius ?? 0.22;
  const kernel = (f, c, s) => Math.exp(-(((f - c) / Math.max(1, F - 1)) ** 2) / (2 * s * s));
  const shift = (j, f, d) => { for (const k of SUBTREE[j]) if (frames[f][k]) frames[f][k] = add(frames[f][k], d); };
  const pinJoint = j => {  // Gaussian interpolation through every pin of joint j: exact on each pinned frame
    const own = new Map(valid.filter(p => p.joint === MSFLOW_JOINTS[j]).map(p => [frameOf(p), p]));  // one pin per frame, the last wins
    if (!own.size || !frames[0][MSFLOW_JOINTS[j]]) return;
    const ps = [...own].map(([f, p]) => ({ f, s: sigma(p), d: sub(p.pos, frames[f][MSFLOW_JOINTS[j]]) }));
    const K = ps.map(a => ps.map(b => kernel(a.f, b.f, b.s))), w = [0, 1, 2].map(i => solveLinear(K, ps.map(p => p.d[i])));
    for (let f = 0; f < F; f++) shift(j, f, [0, 1, 2].map(i => ps.reduce((sum, p, q) => sum + w[i][q] * kernel(f, p.f, p.s), 0)));
  };
  pinJoint(0);  // the pelvis first, so a reach never moves a pinned pelvis
  const pelvisPinned = valid.some(p => p.joint === 'pelvis');
  // A few rounds: one pin's lean (a head thrown back) can take another's hand out of reach again.
  for (let round = 0; round < 3; round++) for (const p of valid) {
    const root = REACH[p.joint], fp = frameOf(p), now = frames[fp];
    if (!root || !now[root] || !now[p.joint]) continue;
    const bones = LIMB[p.joint] ? len(sub(now[LIMB[p.joint][1]], now[root])) + len(sub(now[p.joint], now[LIMB[p.joint][1]])) : len(sub(now[p.joint], now.neck));
    const reach = bones * 0.98, s = sigma(p);
    if (!root.startsWith('hip') && now.spine1) {  // lean: turn the upper body about spine1 until the root is in reach
      const P = now.spine1, S = sub(now[root], P), T = sub(p.pos, P), r = len(S), D = len(T), axis = cross(S, T);
      if (r > 1e-9 && D > 1e-9 && len(axis) > 1e-9 && len(sub(T, S)) > reach) {
        const phi = Math.acos(Math.min(1, Math.max(-1, dot(S, T) / (r * D)))), c = (r * r + D * D - reach * reach) / (2 * r * D);
        const lean = Math.min(1, phi, c >= 1 ? phi : c <= -1 ? 0 : Math.max(0, phi - Math.acos(c))), u = unit(axis);
        for (let f = 0; f < F; f++) {
          const angle = lean * kernel(f, fp, s), pivot = frames[f].spine1;
          for (const k of SUBTREE[3]) if (frames[f][k]) frames[f][k] = add(pivot, turnAbout(sub(frames[f][k], pivot), u, angle));
        }
      }
    }
    const gap = sub(p.pos, frames[fp][root]), excess = len(gap) - reach;
    if (excess > 1e-9 && !pelvisPinned) for (let f = 0; f < F; f++) shift(0, f, mul(unit(gap), excess * kernel(f, fp, s)));
  }
  for (let j = 1; j < MSFLOW_JOINTS.length; j++) pinJoint(j);
  // Between pins a hand or foot can be carried past its reach: there it stops where the straightened limb ends (the foot
  // follows its ankle); on its own pinned frames it stays exact.
  const pinned = new Set(valid.map(p => p.joint));
  for (const [end, [root, mid]] of Object.entries(LIMB)) {
    if (pinned.has(mid)) continue;
    const exact = new Set(valid.filter(p => p.joint === end).map(frameOf));
    frames.forEach((fr, f) => {
      const b = baseFrames[f];
      if (!fr[root] || !fr[mid] || !fr[end]) return;
      const ik = solveLimbIK(fr[root], fr[mid], fr[end], len(sub(b[mid], b[root])), len(sub(b[end], b[mid])));
      fr[mid] = ik.mid;
      if (!exact.has(f)) shift(MSFLOW_JOINTS.indexOf(end), f, sub(ik.end, fr[end]));
    });
  }
  return frames;
}

// Motion skills, physical fixes and motion QA (SPEC_12) on direct-motion-space frames. Stage metres: the actor's mark is
// the origin and the console is at +z. Anchors are what a hand reaches for (the dial is the one the observatory builds).
export const SCENE_ANCHORS = {
  dial: { pos: [-0.25, 1.03, 0.56], normal: [0, 0.7, -0.7] },  // the console's brass dial, left
  recorder: { pos: [0.25, 1.03, 0.56], normal: [0, 0.7, -0.7] },  // the analog recorder, right
  console_edge: { pos: [0.0, 0.96, 0.52], normal: [0, 0.5, -0.86] },  // both hands on the console's front edge
  window_glass: { pos: [0.0, 1.45, 3.80], normal: [0, 0, -1] },  // out through the glass
};
// Axis-aligned boxes a hand or elbow must stay out of (the observatory only: the other sets have no console).
export const SCENE_BOXES = {
  console: { id: 'console', min: [-0.90, 0.0, 0.58], max: [0.90, 0.98, 1.12] },
  plinth: { id: 'plinth', min: [-1.45, 0.0, 0.25], max: [1.45, 0.14, 1.35] },
};
// The mannequin's soles (figure.js, an adult standing): ankle and toe points above the floor, the knee ball's radius for
// a kneel, and the ankles' distance from the midline. A smaller build scales them all.
export const ANKLE_FLOOR_Y = 0.074, FOOT_FLOOR_Y = 0.011, KNEE_FLOOR_Y = 0.052;
const STANCE_W = 0.144, sizeOf = plan => BUILD[plan.figure?.build] || 1;
const SIDES = ['L', 'R'], TIGHT = 0.35;  // a pin's time sigma in frames when every frame of a contact is pinned
const SETTLE = 4, WALK_SPEED = 1.2, STRIDE = 0.42, LIFT = 0.06;  // frames into and out of the gait; m/s; m per step; m
const FLOOR_TOL = 0.005, STANCE_UP = 0.015, STANCE_SPEED = 0.025, SLIDE_TOL = 0.015, STEP_AT = 0.08, STEP_FRAMES = 6;
const REACH_TOL = 0.015, BOX_TOL = 0.01, HANDS_APART = 0.06, POP_SPEED = 0.28;
const WEIGHT = { GROUND: 2, SLIDE: 2, REACH: 2, PENETRATION: 3, SELF_CONTACT: 1, POP: 1 };
const flat = (a, b) => Math.hypot(a[0] - b[0], a[2] - b[2]), dist = (a, b) => len(sub(a, b));
const near = (from, to) => from + Math.atan2(Math.sin(to - from), Math.cos(to - from));  // to, turned the short way from from
const solids = plan => ((plan.set || 'observatory') === 'observatory' ? Object.values(SCENE_BOXES) : []);
const boneLen = (frames, a, b) => Math.min(...frames.map(fr => (fr[a] && fr[b] ? dist(fr[a], fr[b]) : Infinity)));  // pins only ever stretch a bone
const r3 = v => Math.round(v * 1000) / 1000;

// A copy of v with every open value {range: [lo, hi]} replaced by pick(range, i), i counting them in document order.
const isRange = v => v && typeof v === 'object' && Array.isArray(v.range) && v.range.length === 2 && v.range.every(Number.isFinite);
function withRanges(v, pick) {
  let i = 0;
  const walk = x => (isRange(x) ? pick(x.range, i++) : Array.isArray(x) ? x.map(walk)
    : x && typeof x === 'object' ? Object.fromEntries(Object.entries(x).map(([k, y]) => [k, walk(y)])) : x);
  return walk(v);
}

// plan.use: [{skill, f0?, frames?, args?}] in order, each starting where the last one ended (f0 overrides; frames are the
// shot's). Returns performance keys (acts), direct-motion-space pins and checks: {contacts, planted} with frame ranges.
//   standIdle {at?: [x, z], heading?, until?, plant?}  stand on a spot; plant locks both feet for the hold
//   walkTo    {from?: [x, z], to: [x, z], steps?, vary?}   eases in, alternates the feet, settles with them together
//   reachGrip {anchor: name | [x, y, z], side? 'L' | 'R', reach?, hold?, release?}   frames to the grip, on it, off it
//   turnLook  {anchor: name | [x, y, z]} or {heading}   turns the body to it
//   kneelDown {duration?, face?}                  down onto the left knee, with an expression
export function compileMotionSkills(plan) {
  const p = withRanges(plan, ([lo, hi]) => (lo + hi) / 2), F = framesOf(p), k = sizeOf(p), mark = p.mark || [0, 0];
  const acts = [], pins = [], checks = { contacts: [], planted: [] }, at = f => Math.min(1, Math.max(0, f / (F - 1)));
  const key = (f, o) => acts.push({ at: at(f), ...o });
  const spot = pos => ({ side: pos[0] - mark[0], back: mark[1] - pos[1] });
  const pin = (f, joint, pos, skill, frames = TIGHT) => pins.push({ at: at(f), joint, pos, radius: frames / (F - 1), skill });
  const target = a => (typeof a === 'string' ? SCENE_ANCHORS[a]?.pos : a);
  const ankle = (pos, heading, s, lift = 0) => {  // where a planted ankle sits beside the pelvis at [x, z], body turned to heading
    const w = (s === 'L' ? -STANCE_W : STANCE_W) * k;
    return [pos[0] + w * Math.cos(heading), ANKLE_FLOOR_Y * k + lift, pos[1] - w * Math.sin(heading)];
  };
  let cur = { f: 0, pos: [...mark], heading: p.facing === 'room' ? Math.PI : 0, body: 'stand', face: 'neutral' };
  for (const step of p.use || []) {
    const a = step.args || {}, f0 = step.f0 ?? cur.f;
    if (step.skill === 'standIdle') {
      const until = a.until ?? f0 + (step.frames ?? 24), pos = a.at ?? cur.pos, heading = a.heading ?? cur.heading;
      for (const f of [f0, until]) key(f, { ...spot(pos), yaw: heading, body: 'stand' });
      if (a.plant) for (const s of SIDES) {
        const pos3 = ankle(pos, heading, s), from = Math.max(0, Math.ceil(f0)), to = Math.min(F - 1, Math.floor(until));
        for (let f = from; f <= to; f++) pin(f, 'ankle' + s, pos3, 'standIdle');
        checks.planted.push({ joint: 'ankle' + s, pos: pos3, from, to });
      }
      cur = { ...cur, f: until, pos, heading, body: 'stand' };
    } else if (step.skill === 'walkTo' && a.to) {
      const from = a.from ?? cur.pos, to = a.to, D = Math.hypot(to[0] - from[0], to[1] - from[1]), vary = a.vary ?? 0;
      const n = step.frames ?? Math.round(D / WALK_SPEED * FPS) + 2 * SETTLE, t1 = f0 + SETTLE, t2 = f0 + n - SETTLE;
      const heading = D > 1e-6 ? near(cur.heading, Math.atan2(to[0] - from[0], to[1] - from[1])) : cur.heading;
      const steps = Math.max(2, a.steps ?? Math.ceil(D / STRIDE)), T = (t2 - t1) / steps;
      // The pelvis: still while the knees bend, eased from one spot to the other (it turns during the first step), still
      // while they straighten. along(f) is where sampleActs puts it.
      key(f0, { ...spot(from), body: cur.body, armSwing: 0, sway: 0, bounce: 0 }); key(t1, { ...spot(from), yaw: cur.heading, body: 'walk' });
      key(t1 + T, { yaw: heading }); key(t2, { ...spot(to), body: 'walk', armSwing: 0, sway: 0, bounce: 0 }); key(f0 + n, { body: 'stand' });
      const along = f => { const u = ease(Math.min(1, Math.max(0, (f - t1) / (t2 - t1)))); return [from[0] + (to[0] - from[0]) * u, from[1] + (to[1] - from[1]) * u]; };
      // Step i swings the left foot, then the right, ... to land under the pelvis halfway through the step after it, so
      // the planted foot leads, then trails; the last two steps close the feet together on the end spot.
      const planted = { L: ankle(from, cur.heading, 'L'), R: ankle(from, cur.heading, 'R') }, swings = [];
      for (let i = 0; i < steps; i++) {
        const s = i % 2 ? 'R' : 'L', g = t1 + (i + 1) * T, lead = vary * 0.03 * k * Math.cos(2.4 * i);
        const mid = g - T / 2, strength = Math.sin(Math.PI * (mid - t1) / (t2 - t1)) ** 0.4, sign = i % 2 ? -1 : 1;
        key(mid, { armSwing: sign * 0.26 * strength, sway: sign * 0.022 * strength, bounce: -0.012 * strength });
        const land = i >= steps - 2 ? to : along(g + T / 2), toward = [Math.sin(heading) * lead, Math.cos(heading) * lead];
        const next = ankle(i >= steps - 2 ? land : [land[0] + toward[0], land[1] + toward[1]], heading, s);
        swings.push({ s, f: g - T, g, from: planted[s], to: next, lift: LIFT * k * (1 + vary * 0.5 * Math.sin(2.4 * i)) });
        planted[s] = next;
      }
      // Every frame of the gait pins both ankles: planted ones exactly where they landed (checks.planted), swinging
      // ones along an eased, lifted arc.
      for (const s of SIDES) {
        const own = swings.filter(w => w.s === s);
        let spot = own[0].from, since = Math.ceil(t1);
        for (let f = Math.ceil(t1); f <= t2; f++) {
          const w = own.find(o => f > o.f && f < o.g);
          if (w) {
            if (since !== null) { checks.planted.push({ joint: 'ankle' + s, pos: spot, from: since, to: f - 1 }); since = null; }
            const phase = (f - w.f) / (w.g - w.f), u = ease(phase);  // the foot clears the floor before it travels
            pin(f, 'ankle' + s, add(add(w.from, mul(sub(w.to, w.from), u)), [0, w.lift * Math.sin(Math.PI * phase), 0]), 'walkTo');
            continue;
          }
          if (since === null) { spot = own.filter(o => f >= o.g).pop().to; since = f; }
          pin(f, 'ankle' + s, spot, 'walkTo');
        }
        if (since !== null) checks.planted.push({ joint: 'ankle' + s, pos: spot, from: since, to: Math.floor(t2) });
      }
      cur = { ...cur, f: f0 + n, pos: to, heading, body: 'stand' };
    } else if (step.skill === 'reachGrip' && target(a.anchor)) {
      const pos = target(a.anchor), wrist = 'wrist' + (a.side === 'R' ? 'R' : 'L'), reach = a.reach ?? 12, hold = a.hold ?? 24, release = a.release ?? 12;
      const on = f0 + reach, off = on + hold;
      // Every frame of the hold is pinned, so the hand stays on the anchor. The first and last pins spread over the reach
      // in and the release (sigma a third of each) and come first: the solver leans the body for them, then each frame
      // of the hold only adds what it still lacks, so no frame leans twice.
      pin(on, wrist, pos, 'reachGrip', Math.max(TIGHT, reach / 3)); pin(off, wrist, pos, 'reachGrip', Math.max(TIGHT, release / 3));
      for (let f = on + 1; f < off; f++) pin(f, wrist, pos, 'reachGrip');
      checks.contacts.push({ joint: wrist, anchor: typeof a.anchor === 'string' ? a.anchor : null, pos, from: on, to: off });
      cur = { ...cur, f: off + release };
    } else if (step.skill === 'turnLook') {
      const pos = target(a.anchor ?? a.at), n = step.frames ?? 16;
      const heading = near(cur.heading, pos ? Math.atan2(pos[0] - cur.pos[0], pos[2] - cur.pos[1]) : a.heading ?? cur.heading);
      key(f0, { yaw: cur.heading }); key(f0 + n, { yaw: heading });
      cur = { ...cur, f: f0 + n, heading };
    } else if (step.skill === 'kneelDown') {
      const n = step.frames ?? a.duration ?? 24, face = a.face ? [{ face: cur.face }, { face: a.face }] : [{}, {}];
      key(f0, { body: cur.body, ...face[0] }); key(f0 + n, { body: 'kneel', ...face[1] });
      cur = { ...cur, f: f0 + n, body: 'kneel', face: a.face || cur.face };
    }
  }
  return { acts, pins, checks };
}

// The Walk in action as the one skill it plays as: in from the console side to the mark, or out from it when facing the room.
export function walkinUse(plan) {
  const mark = plan.mark || [0, 0], room = plan.facing === 'room';
  const from = room ? [...mark] : [mark[0], mark[1] - 2.2], to = room ? [mark[0], mark[1] - 2.2] : [...mark];
  return [{ skill: 'walkTo', frames: Math.round((framesOf(plan) - 1) * 0.72), args: { from, to } }];
}

// Where each step of plan.use starts and ends, as compileMotionSkills places them, so a timeline can draw and edit them.
// resizable names what a drag on a beat's right edge sets: the step's frames, a standIdle's until, or a reachGrip's hold;
// null for a step that does nothing (a walkTo with no goal, a grip on an unknown anchor).
export function motionBeats(plan) {
  const p = withRanges(plan, ([lo, hi]) => (lo + hi) / 2), mark = p.mark || [0, 0];
  let cur = { f: 0, pos: [...mark] };
  return (p.use || []).map((step, index) => {
    const a = step.args || {}, start = step.f0 ?? cur.f;
    let end = start, resizable = null;
    if (step.skill === 'standIdle') { end = a.until ?? start + (step.frames ?? 24); resizable = a.until != null ? 'until' : 'frames'; cur = { f: end, pos: a.at ?? cur.pos }; }
    else if (step.skill === 'walkTo' && a.to) {
      const from = a.from ?? cur.pos, D = Math.hypot(a.to[0] - from[0], a.to[1] - from[1]);
      end = start + (step.frames ?? Math.round(D / WALK_SPEED * FPS) + 2 * SETTLE); resizable = 'frames'; cur = { f: end, pos: a.to };
    } else if (step.skill === 'reachGrip' && (typeof a.anchor === 'string' ? SCENE_ANCHORS[a.anchor]?.pos : a.anchor)) {
      end = start + (a.reach ?? 12) + (a.hold ?? 24) + (a.release ?? 12); resizable = 'hold'; cur = { ...cur, f: end };
    } else if (step.skill === 'turnLook') { end = start + (step.frames ?? 16); resizable = 'frames'; cur = { ...cur, f: end }; }
    else if (step.skill === 'kneelDown') { end = start + (step.frames ?? a.duration ?? 24); resizable = 'frames'; cur = { ...cur, f: end }; }
    return { index, skill: step.skill, start, end, frames: end - start, resizable };
  });
}

// A plan as the stage plays it: open ranges at their midpoints (searchMotionPlan picks better values) and plan.use
// compiled into the plan's own acts and pins (and dropped, so a played plan plays the same again).
export function motionPlan(plan) {
  const p = withRanges(plan, ([lo, hi]) => (lo + hi) / 2);
  // The visible Walk in action uses the same gait as authored skills. Explicit acting/skills retain priority.
  if (!p.use?.length && !p.acts?.length && p.action === 'walkin') p.use = walkinUse(p);
  if (!p.use?.length) return p;
  const { acts, pins } = compileMotionSkills(p), { use, ...rest } = p;
  return { ...rest, acts: [...(p.acts || []), ...acts], pins: [...(p.pins || []), ...pins] };
}

// Frames where an ankle is planted: on the floor and barely moving.
function stance(frames, A, k) {
  return frames.map((fr, f) => {
    const other = frames[f ? f - 1 : Math.min(1, frames.length - 1)][A];
    return fr[A][1] <= ANKLE_FLOOR_Y * k + STANCE_UP && flat(fr[A], other) < STANCE_SPEED;
  });
}
// How deep p is inside a box and its nearest way out (up, toward the room, back or to a side; never down), or null.
function inside(p, box) {
  if (![0, 1, 2].every(i => p[i] > box.min[i] && p[i] < box.max[i])) return null;
  let best = null;
  for (const [i, out] of [[1, 1], [2, -1], [2, 1], [0, -1], [0, 1]]) {
    const depth = out > 0 ? box.max[i] - p[i] : p[i] - box.min[i];
    if (!best || depth < best.depth) best = { depth, i, out };
  }
  return best;
}

// Physical fixes on solved frames (solvePinnedXYZ's output), in order: feet out of the floor, planted feet locked, hands
// and elbows out of the console, and (opt in) velocity spikes smoothed. fix: {ground, slide, penetration} default on,
// {retime: true} opt in, false for none. Returns new frames and how many frames each fix changed.
export function applyMotionFixes(frames, fix = {}, plan = {}) {
  const out = frames.map(fr => Object.fromEntries(Object.entries(fr).map(([j, v]) => [j, [...v]])));
  const fixed = { ground: 0, slide: 0, penetration: 0, retime: 0 }, F = out.length, k = sizeOf(plan);
  if (fix === false || !F) return { frames: out, fixed };
  const on = name => fix === true || fix?.[name] !== false, has = (fr, js) => js.every(j => fr[j]);
  const legs = SIDES.map(s => ({ s, H: 'hip' + s, K: 'knee' + s, A: 'ankle' + s, T: 'foot' + s })).filter(g => out.every(fr => has(fr, [g.H, g.K, g.A, g.T])));
  for (const g of legs) Object.assign(g, { l1: boneLen(out, g.H, g.K), l2: boneLen(out, g.K, g.A) });
  // After an ankle moves: the knee follows by two-bone IK, and an ankle out of reach stops where the leg ends (its toe with it).
  const settle = (fr, g) => { const ik = solveLimbIK(fr[g.H], fr[g.K], fr[g.A], g.l1, g.l2); fr[g.T] = add(fr[g.T], sub(ik.end, fr[g.A])); fr[g.K] = ik.mid; fr[g.A] = ik.end; };
  if (on('ground')) out.forEach(fr => {
    let moved = false;
    for (const g of legs) {
      const dy = Math.max(ANKLE_FLOOR_Y * k - fr[g.A][1], FOOT_FLOOR_Y * k - fr[g.T][1]);
      if (dy > 1e-6) { fr[g.A][1] += dy; fr[g.T][1] += dy; settle(fr, g); moved = true; }
    }
    const knee = Math.max(0, ...SIDES.map(s => (fr['knee' + s] ? KNEE_FLOOR_Y * k - fr['knee' + s][1] : 0)));
    if (knee > 1e-6) { for (const j in fr) fr[j][1] += knee; moved = true; }  // a knee in the floor lifts the body onto it
    fixed.ground += moved;
  });
  if (on('slide')) {
    const changed = new Set();
    for (const g of legs) {
      const planted = stance(out, g.A, k), hold = (fr, spot) => {
        fr[g.A] = [spot.A[0], fr[g.A][1], spot.A[2]]; fr[g.T] = [spot.T[0], fr[g.T][1], spot.T[2]]; settle(fr, g);
      };
      for (let f = 0; f < F; f++) {
        if (!planted[f]) continue;
        let e = f; while (e + 1 < F && planted[e + 1]) e++;
        // Lock the foot where it landed. When the body has carried it STEP_AT away (a turn on the spot), it is a step:
        // the foot lifts and lands where the body put it over STEP_FRAMES, then locks there.
        let spot = { A: [...out[f][g.A]], T: [...out[f][g.T]] };
        for (let i = f + 1; i <= e; i++) {
          const fr = out[i];
          if (Math.max(flat(fr[g.A], spot.A), flat(fr[g.T], spot.T)) < STEP_AT) { if (flat(fr[g.A], spot.A) > 1e-9 || flat(fr[g.T], spot.T) > 1e-9) changed.add(i); hold(fr, spot); continue; }
          const j = Math.min(e, i + STEP_FRAMES), land = { A: [...out[j][g.A]], T: [...out[j][g.T]] };
          for (let m = i; m < j; m++) {
            const u = (m - i + 1) / (j - i + 1), s = ease(u), lift = 0.04 * k * Math.sin(Math.PI * u), fr2 = out[m];
            hold(fr2, { A: add(spot.A, mul(sub(land.A, spot.A), s)), T: add(spot.T, mul(sub(land.T, spot.T), s)) });
            fr2[g.A][1] += lift; fr2[g.T][1] += lift; settle(fr2, g); changed.add(m);
          }
          spot = land; i = j;
        }
        f = e;
      }
    }
    fixed.slide = changed.size;
  }
  const boxes = solids(plan);
  if (on('penetration') && boxes.length) out.forEach(fr => {
    let moved = false;
    for (const s of SIDES) {
      const S = 'shoulder' + s, E = 'elbow' + s, W = 'wrist' + s;
      if (!has(fr, [S, E, W])) continue;
      const l1 = boneLen(frames, S, E), l2 = boneLen(frames, E, W);
      for (let round = 0; round < 2; round++) for (const box of boxes) for (const j of [W, E]) {
        const hit = inside(fr[j], box);
        if (!hit || hit.depth <= FLOOR_TOL) continue;
        const exit = [...fr[j]]; exit[hit.i] = hit.out > 0 ? box.max[hit.i] + FLOOR_TOL : box.min[hit.i] - FLOOR_TOL;
        const ik = j === W ? solveLimbIK(fr[S], fr[E], exit, l1, l2) : solveLimbIK(fr[S], exit, fr[W], l1, l2);
        fr[E] = ik.mid; fr[W] = ik.end; moved = true;
      }
    }
    fixed.penetration += moved;
  });
  if (fix?.retime === true) for (let f = 1; f < F; f++) {
    if (!Object.keys(out[f]).some(j => out[f - 1][j] && dist(out[f][j], out[f - 1][j]) > POP_SPEED)) continue;
    const a = Math.max(0, f - 3), b = Math.min(F - 1, f + 2), span = b - a;
    if (span < 2) continue;
    for (const j of Object.keys(out[f])) {  // a cubic between the window's ends that leaves them with the motion's own velocity
      const P0 = out[a][j], P1 = out[b][j], m0 = mul(sub(P0, out[Math.max(0, a - 1)][j]), span), m1 = mul(sub(out[Math.min(F - 1, b + 1)][j], P1), span);
      for (let g = a + 1; g < b; g++) {
        const t = (g - a) / span, h = [2 * t ** 3 - 3 * t ** 2 + 1, t ** 3 - 2 * t ** 2 + t, -2 * t ** 3 + 3 * t ** 2, t ** 3 - t ** 2];
        out[g][j] = P0.map((v, i) => h[0] * v + h[1] * m0[i] + h[2] * P1[i] + h[3] * m1[i]);
      }
    }
    fixed.retime += span - 1; f = b;
  }
  return { frames: out, fixed };
}

// Motion QA in one pass over [F][22 joints]: what is physically off, when, how badly, why and what to do about it.
// {ok, cost (0 = clean), groups: [{kind, subject, count, first, last, worst, worstFrame, limit, cause, hint}]}, one group
// per kind and joint; worst and the limit in metres (per frame for POP).
export function auditMotion(frames, plan = {}) {
  const p = motionPlan(plan), F = frames.length, k = sizeOf(p), found = new Map();
  const pins = (p.pins || []).filter(q => MSFLOW_JOINTS.includes(q.joint) && Number.isFinite(q.at) && q.pos?.length === 3 && q.pos.every(Number.isFinite));
  const frameOf = q => Math.round(Math.min(1, Math.max(0, q.at)) * (F - 1));
  const flag = (kind, subject, f, worst, limit, info = {}) => {
    const id = kind + ':' + subject, g = found.get(id) || { kind, subject, count: 0, first: f, last: f, worst: -Infinity, worstFrame: f, limit, excess: 0 };
    g.count++; g.first = Math.min(g.first, f); g.last = Math.max(g.last, f); g.excess += worst - limit;
    if (worst > g.worst) Object.assign(g, { worst, worstFrame: f, info });
    found.set(id, g);
  };
  if (!F) return { ok: true, cost: 0, groups: [] };
  for (let f = 0; f < F; f++) {
    const fr = frames[f];
    for (const [j, floor] of [['ankleL', ANKLE_FLOOR_Y], ['ankleR', ANKLE_FLOOR_Y], ['footL', FOOT_FLOOR_Y], ['footR', FOOT_FLOOR_Y], ['kneeL', KNEE_FLOOR_Y], ['kneeR', KNEE_FLOOR_Y]]) {
      if (fr[j] && floor * k - fr[j][1] > FLOOR_TOL) flag('GROUND', j, f, floor * k - fr[j][1], FLOOR_TOL);
    }
    for (const box of solids(p)) for (const j of ['wristL', 'wristR', 'elbowL', 'elbowR']) {
      const hit = fr[j] && inside(fr[j], box);
      if (hit && hit.depth > BOX_TOL) flag('PENETRATION', j, f, hit.depth, BOX_TOL, { box: box.id, dy: box.max[1] - fr[j][1], dz: fr[j][2] - box.min[2] });
    }
    if (fr.wristL && fr.wristR) {  // hands through each other (not a two-handed grip), or into the head or chest
      const gripped = ['wristL', 'wristR'].every(j => pins.some(q => q.joint === j && frameOf(q) === f)), apart = dist(fr.wristL, fr.wristR);
      if (!gripped && apart < HANDS_APART) flag('SELF_CONTACT', 'wrists', f, HANDS_APART - apart, 0);
      if (fr.head && fr.neck && fr.spine2) for (const j of ['wristL', 'wristR']) {
        const skull = add(fr.head, mul(unit(sub(fr.head, fr.neck)), 0.12 * k)), axis = sub(fr.neck, fr.spine2), w = fr[j];
        const t = Math.min(1, Math.max(0, dot(sub(w, fr.spine2), axis) / (dot(axis, axis) || 1)));
        const depth = Math.max(0.09 * k - dist(w, skull), 0.09 * k - dist(w, add(fr.spine2, mul(axis, t))));
        if (depth > BOX_TOL) flag('SELF_CONTACT', j, f, depth, BOX_TOL);
      }
    }
    if (f) {
      let jump = 0, joint = null;
      for (const j in fr) if (frames[f - 1][j]) { const d = dist(fr[j], frames[f - 1][j]); if (d > jump) { jump = d; joint = j; } }
      if (jump > POP_SPEED) flag('POP', joint, f, jump, POP_SPEED);
    }
  }
  for (const s of SIDES) {  // a planted foot that drifts (its heel: turning on it is a pivot, not a slide)
    const A = 'ankle' + s;
    if (!frames.every(fr => fr[A])) continue;
    const planted = stance(frames, A, k);
    for (let f = 0; f < F; f++) {
      if (!planted[f]) continue;
      let e = f;
      for (; e + 1 < F && planted[e + 1]; e++) {
        const drift = flat(frames[e + 1][A], frames[f][A]);
        if (drift > SLIDE_TOL) flag('SLIDE', 'foot' + s, e + 1, drift, SLIDE_TOL);
      }
      f = e;
    }
  }
  for (const q of pins) {  // a hand or foot that cannot be where it is pinned
    const end = q.joint, fp = frameOf(q), fr = frames[fp], root = REACH[end], mid = LIMB[end]?.[1] ?? null;
    if (!/^(wrist|ankle|foot)/.test(end) || !fr[end]) continue;
    let miss = dist(fr[end], q.pos);
    if (mid && fr[root]) miss = Math.max(miss, dist(q.pos, fr[root]) - boneLen(frames, root, mid) - boneLen(frames, mid, end));
    if (miss > REACH_TOL) flag('REACH', end, fp, miss, REACH_TOL, { pin: q, toward: fr[root] ? unit([q.pos[0] - fr[root][0], 0, q.pos[2] - fr[root][2]]) : [0, 0, 0] });
  }
  // Why: the nearest pin on that side of the body, else the body pose keyed nearest in time, else the canned action.
  const causeAt = (f, joint) => {
    const side = /[LR]$/.test(joint) ? joint.slice(-1) : null;
    const pin = pins.filter(q => !side || q.joint.endsWith(side) || q.joint === 'pelvis').map(q => [q, frameOf(q)])
      .filter(([q, fq]) => Math.abs(fq - f) <= Math.max(2, 3 * (q.radius ?? 0.22) * (F - 1))).sort(([, a], [, b]) => Math.abs(a - f) - Math.abs(b - f))[0];
    if (pin) return `${pin[0].skill ? pin[0].skill + ' ' : ''}pin ${pin[0].joint} at f${pin[1]}`;
    const body = (p.acts || []).filter(a => a.body).sort((a, b) => Math.abs(a.at * (F - 1) - f) - Math.abs(b.at * (F - 1) - f))[0];
    if (body && body.body !== 'stand') return `pose ${body.body} at f${Math.round(body.at * (F - 1))}`;
    return p.acts?.length ? `performance keys at f${f}` : `action ${p.action || 'turnreach'} at f${f}`;
  };
  const groups = [...found.values()].map(({ excess, info, ...g }) => {
    const f = g.worstFrame, w = r3(g.worst);
    const [cause, hint] = {
      GROUND: () => [causeAt(f, g.subject), `Enable fix.ground or lift pelvis +${w}m at f${f}`],
      SLIDE: () => [causeAt(g.first, g.subject), `Enable fix.slide to lock planted foot at f${g.first}`],
      REACH: () => [`${info.pin.skill ? info.pin.skill + ' ' : ''}pin ${g.subject} at f${f}`, `Move actor mark [${r3(info.toward[0] * w)}, ${r3(info.toward[2] * w)}] m toward target or add spine lean at f${f}`],
      PENETRATION: () => [`${causeAt(f, g.subject)} into ${info.box}`, `Enable fix.penetration or move hand [0, +${r3(info.dy)}, -${r3(info.dz)}] m out of ${info.box} at f${f}`],
      SELF_CONTACT: () => [causeAt(f, g.subject), g.subject === 'wrists' ? `Keep the hands ${HANDS_APART}m apart, or pin both for a grip, at f${f}` : `Move ${g.subject} clear of the head and chest at f${f}`],
      POP: () => [causeAt(f, g.subject), `Enable fix.retime or spread the move over more frames at f${f}`],
    }[g.kind]();
    return { ...g, worst: w, limit: g.limit, cause, hint, weighted: WEIGHT[g.kind] * excess };
  }).sort((a, b) => b.weighted - a.weighted);
  const cost = r3(groups.reduce((sum, g) => sum + g.weighted, 0));
  return { ok: groups.length === 0, cost, groups: groups.map(({ weighted, ...g }) => g) };
}

// Open values {range: [lo, hi]} anywhere in a plan (a mark, a pin, a skill's args): the midpoint first, then a Halton
// spread over the box and, for the second half of the budget, a shrinking search around the best so far, until
// evaluate(plan) -> cost or {cost} reaches 0. Returns {plan (resolved), qa, evals, cost}.
export function searchMotionPlan(plan, evaluate, budget = 24) {
  const ranges = []; withRanges(plan, r => { ranges.push(r); return 0; });
  const halton = (i, b) => { let x = 0, f = 1; for (; i > 0; i = Math.floor(i / b)) { f /= b; x += f * (i % b); } return x; };
  const BASES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29];
  let best = null, evals = 0;
  const run = xs => {
    const resolved = withRanges(plan, (r, i) => xs[i]), result = evaluate(resolved), qa = typeof result === 'number' ? { cost: result } : result;
    evals++;
    if (!best || qa.cost < best.cost) best = { plan: resolved, qa, cost: qa.cost, xs };
  };
  run(ranges.map(([lo, hi]) => (lo + hi) / 2));
  for (let i = 1, local = 0; ranges.length && evals < budget && best.cost > 0; i++) {
    const u = ranges.map((_, d) => halton(i, BASES[d % BASES.length]));
    if (evals < budget / 2) run(ranges.map(([lo, hi], d) => lo + (hi - lo) * u[d]));
    else {
      const radius = 0.5 * 0.7 ** local++;
      run(ranges.map(([lo, hi], d) => Math.min(hi, Math.max(lo, best.xs[d] + (u[d] - 0.5) * 2 * radius * (hi - lo)))));
    }
  }
  return { plan: best.plan, qa: best.qa, evals, cost: best.cost };
}

// The shot's camera move in words, for the prompt beat sheet and the Camera Motion column.
export function describePlan(plan) {
  const lens = `${plan.lens}mm, ${(framesOf(plan) - 1) / FPS} s`;
  return {
    pushin: `Slow dolly push-in to an over-the-shoulder close shot, ${lens}`,
    pullout: `Slow dolly pull-out from an over-the-shoulder close shot to a wide view, ${lens}`,
    orbit: `Orbit around him from his left to his right, ${lens}`,
    crane: `Crane up from low to a high angle, ${lens}`,
    track: `Lateral tracking shot along the console, ${lens}`,
    static: `Locked-off over-the-shoulder shot, ${lens}`,
  }[plan.keys ? 'custom' : plan.move] || `Custom camera path, ${lens}`;
}
