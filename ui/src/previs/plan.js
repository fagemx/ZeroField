// Previs plans as plain data: camera keys, lens and actor action for one shot. No three.js here, so it is testable in node.
// Coordinates are station-local: the actor stands at the console station facing +z (toward the glass); his reaching
// arm is on -x, which a camera behind him sees on screen right (the same screen layout as the Blender blockouts).

export const FPS = 24, WIDTH = 1280, HEIGHT = 704;
export const DURATIONS = [4, 6, 8];  // seconds; LTX-2.5 takes 8n+1 frames: 97, 145 or 193
export const FRAMES = 97;  // the 4-second default
export const framesOf = plan => (DURATIONS.includes(plan?.seconds) ? plan.seconds : 4) * FPS + 1;
// Camera keys and the actor's timing are written on a 0..96 beat clock, so a longer shot plays the same blocking slower.
const beat = (plan, f) => f * 96 / (framesOf(plan) - 1);
export const LENSES = [24, 35, 50, 85];
export const MOVES = ['pushin', 'pullout', 'orbit', 'crane', 'track', 'static'];
export const ACTIONS = ['turnreach', 'stand', 'walkin'];
export const MOODS = ['grey', 'night'];
export const FACINGS = ['console', 'room'];  // the actor faces the console and glass, or turns to the room (the camera side)
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
function insideDome(aim, offset) {
  for (let t = 1; t > 0; t -= 0.02) {
    const p = aim.map((v, i) => v + offset[i] * t), d = Math.hypot(p[0] - DOME.x, p[2] - DOME.z);
    if (p[1] >= 0.3 && d <= DOME.floor && p[1] <= DOME.base + Math.sqrt(Math.max(0, DOME.radius ** 2 - d * d)) - 0.3) return p;
  }
  return aim;
}

// Camera at frame f: eased piecewise interpolation between keys.
// A smooth path through every key (Hermite with Catmull-Rom tangents on the key beats), eased in and out over the
// whole shot: multi-key moves flow through their middle keys instead of stopping at each one. Two keys stay a plain ease.
export function sampleCamera(plan, frame) {
  const keys = cameraKeys(plan), first = keys[0][0], end = keys[keys.length - 1][0], b = beat(plan, frame);
  if (b <= first) return { position: keys[0][1], aim: keys[0][2] };
  if (b >= end) return { position: keys[keys.length - 1][1], aim: keys[keys.length - 1][2] };  // land exactly on the end key
  const u = first + ease((b - first) / (end - first)) * (end - first);
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

// Mannequin looks (SPEC_10 P3). The default is the mannequin the Layout Render was validated on. tone: the person's
// colour (board look) and coat shade (render look), so they read as the same person in every shot.
export const DEFAULT_FIGURE = { build: 'man', outfit: 'jacket', hair: 'short' };
export const FIGURE_OPTIONS = { build: ['man', 'woman', 'child', 'elder'], outfit: ['jacket', 'longcoat', 'dress', 'robe'], hair: ['short', 'long', 'bun'] };

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
};
const JOINTS = ['spine', 'neck', 'shoulderL', 'shoulderR', 'elbowL', 'elbowR', 'hipL', 'hipR', 'kneeL', 'kneeR', 'ankleL', 'ankleR'];
// A pose between two named poses: joint by joint, so a slump into a kneel bends every joint at once.
export function blendPose(from, to, t) {
  const a = POSES[from] || {}, b = POSES[to] || a, out = { drop: (a.drop || 0) + ((b.drop || 0) - (a.drop || 0)) * t };
  for (const j of JOINTS) if (a[j] || b[j]) out[j] = [0, 1, 2].map(i => (a[j]?.[i] || 0) + ((b[j]?.[i] || 0) - (a[j]?.[i] || 0)) * t);
  return out;
}

// Performance keys (SPEC_10): [{at 0..1 of the shot, yaw?, reach?, back?, body?}]. Each channel eases from the key that
// last set it to the next key that sets it; yaw is absolute (the plan's facing is not added). The shot grammar writes
// these when the director re-times what the actor does; a plan without them plays its canned action.
export function sampleActs(acts, u) {
  const out = {}, at = (keys, x) => { let i = 0; while (i < keys.length - 1 && x >= keys[i + 1].at) i++; return i; };
  for (const ch of ['yaw', 'reach', 'back', 'body']) {
    const keys = acts.filter(k => k[ch] != null).sort((p, q) => p.at - q.at);
    if (!keys.length) continue;
    if (ch === 'body' && keys[0].at > 0) keys.unshift({ at: 0, body: 'stand' });  // he starts standing and arrives in the pose by its key
    const i = at(keys, u), a = keys[i], b = keys[i + 1], t = !b || u <= a.at ? 0 : ease(Math.min(1, (u - a.at) / Math.max(1e-6, b.at - a.at)));
    out[ch] = ch === 'body' ? blendPose(a.body, b?.body, t) : a[ch] + ((b?.[ch] ?? a[ch]) - a[ch]) * t;
  }
  return { yaw: out.yaw || 0, reach: out.reach || 0, back: out.back || 0, pose: out.body || {} };
}

// Actor at frame f: body yaw (radians, 0 = facing the console), shoulder pitch (0 = arm down), distance back from the
// station and the body pose. Facing the room turns the actor around (the motion pass keeps who faces the camera only
// when the previs shows it); walking in while facing the room walks from the console toward the cameras.
export function sampleActor(plan, frame) {
  if (plan.acts?.length) return sampleActs(plan.acts, frame / (framesOf(plan) - 1));
  const f = beat(plan, frame), k = (a, b, t) => a + (b - a) * ease(Math.min(1, Math.max(0, t))), room = plan.facing === 'room', turn = room ? Math.PI : 0;
  if (plan.action === 'stand') return { yaw: turn, reach: 0, back: 0, pose: {} };
  if (plan.action === 'walkin') return { yaw: turn, reach: k(0, 1.16, (f - 60) / 22), back: room ? k(0, 2.2, f / 60) : k(2.2, 0, f / 60), pose: {} };
  return { yaw: k(-1.75, 0, f / 39) + turn, reach: k(0, 1.16, (f - 22) / 22), back: 0, pose: {} };  // turnreach: from the glass to the dial
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
