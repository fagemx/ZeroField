// Previs plans as plain data: camera keys, lens and actor action for one shot. No three.js here, so it is testable in node.
// Coordinates are station-local: the actor stands at the console station facing +z (toward the glass); his reaching
// arm is on -x, which a camera behind him sees on screen right (the same screen layout as the Blender blockouts).

export const FRAMES = 97, FPS = 24, WIDTH = 1280, HEIGHT = 704;
export const LENSES = [24, 35, 50, 85];
export const MOVES = ['pushin', 'pullout', 'orbit', 'crane', 'track', 'static'];
export const ACTIONS = ['turnreach', 'stand', 'walkin'];
export const MOODS = ['grey', 'night'];

// Camera keys: [frame, position [x, y, z], aim [x, y, z]], frames 0..96.
const PRESETS = {
  pushin: [[0, [1.4, 1.45, -5.8], [-0.2, 2.75, 0.4]], [48, [0.55, 1.8, -2.6], [-0.1, 1.5, 0.5]], [96, [-0.75, 1.95, -0.85], [-0.05, 1.32, 0.55]]],
  orbit: [[0, [2.3, 1.7, -1.6], [0, 1.4, 0.15]], [48, [0.1, 1.7, -2.6], [0, 1.4, 0.15]], [96, [-2.1, 1.7, -1.4], [0, 1.4, 0.15]]],
  crane: [[0, [0.8, 0.6, -2.1], [0, 1.6, 0.2]], [96, [0.45, 3.6, -1.6], [-0.05, 1.0, 0.4]]],
  track: [[0, [2.4, 1.6, -2.2], [0.6, 1.4, 0.4]], [96, [-2.2, 1.6, -2.2], [-0.6, 1.4, 0.4]]],
  static: [[0, [-0.9, 1.8, -1.6], [0, 1.35, 0.45]], [96, [-0.9, 1.8, -1.6], [0, 1.35, 0.45]]],
};
PRESETS.pullout = PRESETS.pushin.slice().reverse().map(([, pos, aim], i, all) => [all.length === 1 ? 0 : (i * 96) / (all.length - 1), pos, aim]);

const ease = t => t * t * (3 - 2 * t);
const lerp3 = (a, b, t) => a.map((v, k) => v + (b[k] - v) * t);

export function defaultPlan() {
  return { set: 'observatory', move: 'pushin', lens: 35, action: 'turnreach', mood: 'grey', keys: null };
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

export function cameraKeys(plan) {
  return plan.keys && plan.keys.length >= 2 ? plan.keys : PRESETS[plan.move] || PRESETS.pushin;
}

// Camera at frame f: eased piecewise interpolation between keys.
export function sampleCamera(plan, f) {
  const keys = cameraKeys(plan), last = keys[keys.length - 1];
  if (f <= keys[0][0]) return { position: keys[0][1], aim: keys[0][2] };
  if (f >= last[0]) return { position: last[1], aim: last[2] };  // land exactly on the end key
  for (let i = 0; i < keys.length - 1; i++) {
    const [f0, p0, a0] = keys[i], [f1, p1, a1] = keys[i + 1];
    if (f <= f1) { const t = ease((f - f0) / Math.max(1, f1 - f0)); return { position: lerp3(p0, p1, t), aim: lerp3(a0, a1, t) }; }
  }
  return { position: last[1], aim: last[2] };
}

// Vertical field of view for a lens on a 36 mm wide sensor at the shot aspect (same convention as Blender).
export function verticalFov(lens, aspect = WIDTH / HEIGHT) {
  return 2 * Math.atan((36 / aspect) / 2 / lens) * 180 / Math.PI;
}

// Actor at frame f: body yaw (radians, 0 = facing the console), shoulder pitch (0 = arm down) and distance back from the station.
export function sampleActor(plan, f) {
  const k = (a, b, t) => a + (b - a) * ease(Math.min(1, Math.max(0, t)));
  if (plan.action === 'stand') return { yaw: 0, reach: 0, back: 0 };
  if (plan.action === 'walkin') return { yaw: 0, reach: k(0, 1.16, (f - 60) / 22), back: k(2.2, 0, f / 60) };
  return { yaw: k(-1.75, 0, f / 39), reach: k(0, 1.16, (f - 22) / 22), back: 0 };  // turnreach: from the glass to the dial
}

// The shot's camera move in words, for the prompt beat sheet and the Camera Motion column.
export function describePlan(plan) {
  const lens = `${plan.lens}mm`;
  return {
    pushin: `Slow dolly push-in to an over-the-shoulder close shot, ${lens}`,
    pullout: `Slow dolly pull-out from an over-the-shoulder close shot to a wide view, ${lens}`,
    orbit: `Orbit around him from his left to his right, ${lens}`,
    crane: `Crane up from low to a high angle, ${lens}`,
    track: `Lateral tracking shot along the console, ${lens}`,
    static: `Locked-off over-the-shoulder shot, ${lens}`,
  }[plan.keys ? 'custom' : plan.move] || `Custom camera path, ${lens}`;
}
