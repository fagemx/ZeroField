// Shot grammar (prototype): shots written in film terms (shot size, height, side, move, speed, ending) and solved into a
// camera on the ZeroField previs stage, relative to the subject. Ported from the shot-idiom generator prototype; plain
// data and math, no DOM, so node can test it. Obstruction by set geometry is injected by the caller (`blocked`).
// Interaction rules: docs/specs/SPEC_09_SHOT_GRAMMAR_INTERACTION.md.
import { DOME, LENSES, framesOf, sampleActor, verticalFov } from '../../src/previs/plan.js';
import { BEAT_STORY, samplePerf } from './perf.js';

/* ---------- vocabulary ---------- */
// Shot size = the height of frame visible at the subject, in metres. The ladder runs wide to tight; INSERT is off-ladder.
export const SIZES = ['EWS', 'WS', 'MWS', 'MS', 'MCU', 'CU', 'ECU', 'EYES'];
export const FRAME_H = { EWS: 7, WS: 2.6, MWS: 1.35, MS: 0.8, MCU: 0.5, CU: 0.3, ECU: 0.16, EYES: 0.11, INSERT: 0.38 };
export const SIZE_LABEL = { EWS: 'Extreme wide', WS: 'Wide', MWS: 'Medium wide', MS: 'Medium', MCU: 'Medium close-up', CU: 'Close-up', ECU: 'Extreme close-up', EYES: 'Eyes', INSERT: 'Insert' };
export const HEIGHTS = ['low', 'eye', 'high'];
const ELEV = { low: -12, eye: 0, high: 30 };
export const HEIGHT_LABEL = { low: 'Low angle', eye: 'Eye level', high: 'High angle' };
export const MOVE_LABEL = { static: 'Locked-off', push: 'Push in', pull: 'Pull out', orbit: 'Orbit', track: 'Track', crane: 'Crane', pan: 'Pan', tilt: 'Tilt' };
// Move classes colour the timeline: the camera body travels, the camera only turns, or it holds.
export const MOVE_CLASS = { static: 'hold', push: 'travel', pull: 'travel', orbit: 'travel', track: 'travel', crane: 'travel', pan: 'turn', tilt: 'turn' };
export const SPEEDS = ['slow', 'mid', 'fast'];
export const ENDINGS = { ease: 'eases to a stop', stop: 'stops abruptly', snap: 'snaps into motion', flow: 'keeps moving into the cut' };
export const ENDING_LABEL = { ease: 'Ease out', stop: 'Hard stop', snap: 'Snap in', flow: 'Keep moving' };
export const EVENTS = { establish: 'Establish', turn: 'Character turn', action: 'Hands & props', reveal: 'Reveal', pressure: 'Pressure', end: 'Button' };
export const DURATIONS = [4, 6, 8];  // seconds a slate row can render (LTX-2.5 8n+1 frames)

/* ---------- idiom library ----------
   One idiom = one continuous shot (a ZeroField row renders one previs and one LTX clip).
   subj: actor | prop | wide.  focus: face | eyes | body | hands | prop | wide.
   az: side in degrees around the subject, 0 = in front of the face (the room side for props), 180 = behind, + = subject's left.
   drama: a showpiece the chooser keeps for high tension. */
export const IDIOMS = {
  establish: [
    { name: 'Wide hold', lens: 24, shot: { subj: 'wide', focus: 'wide', size: 'WS', angle: 'high', az: 15, move: 'static' } },
    { name: 'Crane down into the room', shot: { subj: 'actor', focus: 'body', size: 'WS', end: 'MWS', angle: 'high', az: 165, move: 'crane', dir: 'down', speed: 'slow' } },
    { name: 'Slow orbit', shot: { subj: 'actor', focus: 'body', size: 'MWS', angle: 'eye', az: 205, az2: 140, move: 'orbit', speed: 'slow' } },
    { name: 'Reveal pull-out', drama: true, lens: 24, shot: { subj: 'actor', focus: 'face', size: 'MCU', end: 'WS', angle: 'eye', az: 155, move: 'pull', speed: 'slow' } },
  ],
  turn: [
    { name: 'Locked three-quarter', shot: { subj: 'actor', focus: 'face', size: 'MCU', angle: 'eye', az: 140, move: 'static' } },
    { name: 'Slow push to close-up', shot: { subj: 'actor', focus: 'face', size: 'MS', end: 'CU', angle: 'eye', az: 150, move: 'push', speed: 'slow' } },
    { name: 'Arc to profile', shot: { subj: 'actor', focus: 'face', size: 'MCU', angle: 'eye', az: 165, az2: 100, move: 'orbit', speed: 'slow' } },
    { name: 'Snap push to the eyes', drama: true, shot: { subj: 'actor', focus: 'eyes', size: 'MCU', end: 'ECU', angle: 'eye', az: 130, move: 'push', start: 0.35, speed: 'fast', ending: 'stop' } },
  ],
  action: [
    { name: 'Insert on the hands', lens: 50, shot: { subj: 'actor', focus: 'hands', size: 'INSERT', angle: 'high', az: 150, move: 'static' } },
    { name: 'Over-the-shoulder push to the dial', shot: { subj: 'prop', focus: 'prop', size: 'MS', end: 'MCU', angle: 'high', az: 12, move: 'push', speed: 'slow' } },
    { name: 'Track along the console', shot: { subj: 'actor', focus: 'body', size: 'MWS', angle: 'eye', az: 120, move: 'track', dir: 'left', speed: 'mid' } },
    { name: 'Low-angle reach', shot: { subj: 'actor', focus: 'hands', size: 'MS', angle: 'low', az: 110, move: 'static' } },
  ],
  reveal: [
    { name: 'Low-angle push', shot: { subj: 'actor', focus: 'body', size: 'MWS', end: 'MS', angle: 'low', az: 140, move: 'push', speed: 'slow' } },
    { name: 'Tilt up to the sky', shot: { subj: 'actor', focus: 'body', size: 'MWS', angle: 'eye', az: 170, move: 'tilt', dir: 'up', speed: 'slow' } },
    { name: 'Pull back to the glass', drama: true, lens: 24, shot: { subj: 'actor', focus: 'face', size: 'CU', end: 'WS', angle: 'eye', az: 150, move: 'pull', speed: 'mid' } },
    { name: 'Whip to the light', drama: true, shot: { subj: 'actor', focus: 'body', size: 'MS', angle: 'eye', az: 160, move: 'pan', dir: 'right', start: 0.4, speed: 'fast', ending: 'stop' } },
  ],
  pressure: [
    { name: 'Low-angle hold', shot: { subj: 'actor', focus: 'face', size: 'MCU', angle: 'low', az: 135, move: 'static' } },
    { name: 'Profile hold', lens: 50, shot: { subj: 'actor', focus: 'face', size: 'MCU', angle: 'eye', az: 95, move: 'static' } },
    { name: 'Creeping push', shot: { subj: 'actor', focus: 'face', size: 'MWS', end: 'MCU', angle: 'eye', az: 165, move: 'push', speed: 'slow', ending: 'flow' } },
    { name: 'Crash push', drama: true, shot: { subj: 'actor', focus: 'face', size: 'MS', end: 'CU', angle: 'eye', az: 145, move: 'push', start: 0.4, speed: 'fast', ending: 'stop' } },
  ],
  end: [
    { name: 'Hold on him', shot: { subj: 'actor', focus: 'face', size: 'MS', angle: 'eye', az: 20, move: 'static' } },
    { name: 'Drift out', shot: { subj: 'actor', focus: 'face', size: 'MCU', end: 'MWS', angle: 'eye', az: 25, move: 'pull', speed: 'slow' } },
    { name: 'Crane up and away', lens: 24, shot: { subj: 'actor', focus: 'body', size: 'MWS', end: 'WS', angle: 'eye', az: 30, move: 'crane', dir: 'up', speed: 'slow' } },
  ],
};
// The idioms a beat can use: the library plus the director's own (saved from a framed shot).
export const idiomsFor = (state, event) => [...IDIOMS[event], ...(state?.custom?.[event] || []).map(i => ({ ...i, mine: true }))];
// Parameters a framed shot carries into a saved idiom.
const SHOT_KEYS = ['subj', 'focus', 'size', 'end', 'angle', 'az', 'az2', 'move', 'dir', 'speed', 'ending', 'start', 'mlen', 'mid'];
export function idiomFromShot(name, s) {
  const shot = {}; for (const k of SHOT_KEYS) if (s[k] != null && !(k === 'start' && !s[k])) shot[k] = s[k];
  return { name, lens: s.lens, shot };
}

/* ---------- the scene: The Last Signal, one beat per slate row ---------- */
// action / facing drive the existing previs mannequin (plan.js sampleActor); seconds is 4, 6 or 8 (LTX 8n+1 frames).
export const SCENE = {
  title: 'The Last Signal · Observatory',
  beats: [
    { id: 'S01', title: 'Kael enters the dome', event: 'establish', tension: 0.2, seconds: 6, action: 'walkin', facing: 'console' },
    { id: 'S02', title: 'At the console', event: 'turn', tension: 0.35, seconds: 4, action: 'stand', facing: 'console' },
    { id: 'S03', title: 'A light answers outside', event: 'reveal', tension: 0.85, seconds: 6, action: 'turnreach', facing: 'console' },
    { id: 'S04', title: 'His hand on the record key', event: 'action', tension: 0.5, seconds: 4, action: 'turnreach', facing: 'console' },
    { id: 'S05', title: 'The beacon pulses', event: 'pressure', tension: 0.7, seconds: 6, action: 'stand', facing: 'console' },
    { id: 'S06', title: 'He decides to speak', event: 'end', tension: 0.3, seconds: 4, action: 'stand', facing: 'room' },
  ],
};

/* ---------- templates: styles and scene templates ---------- */
// A style is how the whole scene picks: tension shift, the showpiece gate, how many anchor breaks, how much variety.
export const PRESETS = {
  calm: { label: 'Calm', desc: 'Calm observer: showpieces only at the very peak, one anchor break at most.', shift: -0.1, gate: 0.92, quota: 1, variety: 1 },
  standard: { label: 'Standard', desc: 'Camera energy follows each beat\'s tension; one anchor break for the turning point.', shift: 0, gate: 0.8, quota: 1, variety: 1 },
  heightened: { label: 'Heightened', desc: 'Tense beats move faster and earn showpieces sooner; two anchor breaks allowed.', shift: 0.12, gate: 0.6, quota: 2, variety: 1.3 },
};
export const RULES = {  // the parameters behind a style, with the ranges the Rules panel offers
  shift: { label: 'Energy shift', min: -0.3, max: 0.3, step: 0.02, hint: 'Pushes every beat\'s target camera energy down or up.' },
  gate: { label: 'Showpiece gate', min: 0.4, max: 1, step: 0.02, hint: 'Tension a beat needs before showpiece idioms are preferred.' },
  quota: { label: 'Anchor breaks', min: 0, max: 6, step: 1, hint: 'How many fast, attention-grabbing moves the scene may use.' },
  variety: { label: 'Variety', min: 0, max: 2, step: 0.1, hint: 'Penalty for repeating the previous shot\'s move.' },
};
export const rulesOf = state => ({ ...(PRESETS[state?.preset] || PRESETS.standard), ...(state?.rules || {}) });
// A scene template picks an idiom per event (and may carry framing). Built-ins plus templates saved from a scene.
export const SCENE_TEMPLATES = [
  { name: 'Observer', desc: 'Locked-off and patient: the camera watches, he acts.', picks: { establish: 'Wide hold', turn: 'Locked three-quarter', action: 'Insert on the hands', reveal: 'Low-angle push', pressure: 'Profile hold', end: 'Hold on him' } },
  { name: 'Classic coverage', desc: 'Wide to close across the scene, one reveal at the turn.', picks: { establish: 'Crane down into the room', turn: 'Slow push to close-up', action: 'Over-the-shoulder push to the dial', reveal: 'Pull back to the glass', pressure: 'Creeping push', end: 'Drift out' } },
  { name: 'Kinetic', desc: 'A camera that keeps travelling: orbits, tracks and a whip at the reveal.', picks: { establish: 'Slow orbit', turn: 'Arc to profile', action: 'Track along the console', reveal: 'Whip to the light', pressure: 'Crash push', end: 'Crane up and away' } },
];
export const sceneTemplatesFor = state => [...SCENE_TEMPLATES, ...(state?.sceneTemplates || []).map(t => ({ ...t, mine: true }))];

/* ---------- small math ---------- */
const D2R = Math.PI / 180, clamp = (x, a, b) => Math.min(b, Math.max(a, x));
const smooth = x => { x = clamp(x, 0, 1); return x * x * (3 - 2 * x); };
const add = (a, b) => a.map((v, i) => v + b[i]), scale = (a, k) => a.map(v => v * k), sub = (a, b) => a.map((v, i) => v - b[i]);
const norm = a => { const l = Math.hypot(...a) || 1; return a.map(v => v / l); };
const rotY = (v, a) => [v[0] * Math.cos(a) + v[2] * Math.sin(a), v[1], -v[0] * Math.sin(a) + v[2] * Math.cos(a)];
const leftOfCam = dir => norm([-dir[2], 0, dir[0]]);
const lerpLog = (a, b, t) => Math.exp(Math.log(a) + (Math.log(b) - Math.log(a)) * t);
// Seeded tie-break so the chooser is stable between reloads.
function rnd(...xs) { let h = 0x811c9dc5; for (const x of xs) { h = Math.imul(h ^ (x >>> 0), 0x01000193); h ^= h >>> 15; } h = Math.imul(h ^ (h >>> 15), h | 1); return ((h ^ (h >>> 14)) >>> 0) / 4294967296; }

/* ---------- the shot as played ---------- */
// mark: the actor's spot as an offset from the console station [x, z]; turn: extra facing in degrees.
// acts: the performance keys (SPEC_10) that drive the mannequin; the beat's own unless the director re-timed them.
export const actorPlan = b => ({ set: 'observatory', move: 'static', lens: 35, action: b.action, facing: b.facing, mood: 'grey', seconds: b.seconds, keys: null, mark: b.mark || [0, 0], turn: b.turn || 0, acts: b.acts || BEAT_STORY[b.id]?.acts || null });

// Idiom shot + the director's overrides. A dragged movement window sets the speed tier (a short window is a fast move);
// otherwise the speed steps up when the move cannot finish in the time it has.
export function effShot(beat, idiom, over = {}) {
  const s = { lens: idiom.lens || 35, angle: 'eye', ending: 'ease', speed: 'mid', start: 0, ...idiom.shot, ...over };
  s.dur = beat.seconds; s.moving = s.move !== 'static';
  if (!s.moving) { s.start = 0; s.mlen = null; s.mid = null; }
  s.moveDur = s.mlen != null ? Math.min(s.mlen, s.dur * (1 - s.start)) : s.dur * (1 - s.start);
  if (s.moving && s.mlen != null) s.speed = tierFor(s, s.moveDur);
  s.min = minDur(s);
  while (s.moving && s.mlen == null && over.speed == null && s.moveDur + 1e-6 < s.min && SPEEDS.indexOf(s.speed) < 2) {
    s.speed = SPEEDS[SPEEDS.indexOf(s.speed) + 1]; s.autoFaster = true; s.min = minDur(s);
  }
  s.energy = energyOf(s); s.breaks = breaksAnchor(s);
  return s;
}
export function minDur(s) {
  if (s.move === 'static') return 0.45;
  if (s.move === 'orbit') return { slow: 1.5, mid: 1.1, fast: 0.8 }[s.speed];
  return { slow: 1.3, mid: 0.9, fast: 0.6 }[s.speed];
}
// The speed a movement window of L seconds reads as: shorter than a mid move needs is fast, short of a slow move is mid.
export function tierFor(s, L) { const m = sp => minDur({ ...s, speed: sp }); return L < m('mid') ? 'fast' : L < Math.max(m('slow'), 1.6) ? 'mid' : 'slow'; }
export function energyOf(s) {
  const mag = s.end ? Math.min(1, Math.abs(Math.log(FRAME_H[s.size] / FRAME_H[s.end])) / Math.log(8)) : (s.moving ? 0.35 : 0);
  const spd = s.moving ? { slow: 0, mid: 0.18, fast: 0.38 }[s.speed] : 0;
  return Math.min(1, 0.05 + (s.moving ? 0.12 : 0) + 0.3 * mag + spd + (s.ending === 'stop' && s.moving ? 0.12 : 0) + (s.angle === 'low' ? 0.08 : 0));
}
// The scene's camera anchor is a calm observer; a fast move or a whip breaks it, and the scene gets a quota of those.
export const breaksAnchor = s => s.moving && s.speed === 'fast';
export const targetEnergy = (tension, rules) => clamp(0.08 + 0.8 * tension + (rules?.shift || 0), 0, 1);

// Movement window: slow fills the shot; mid and fast take fixed seconds, so a longer shot holds after the move.
const SPEED_WIN = { slow: 1, mid: 0.7, fast: 0.35 }, SPEED_SEC = { mid: 1.5, fast: 0.6 };
export function moveWin(s) {
  const rest = s.dur * (1 - s.start);
  if (s.mlen != null && rest > 0) return clamp(s.mlen / rest, 0.02, 1);
  if (!SPEED_SEC[s.speed] || !(rest > 0)) return SPEED_WIN[s.speed] || 0.7;
  return Math.min(1, SPEED_SEC[s.speed] / rest);
}
function ease(ending, x) {
  x = clamp(x, 0, 1);
  if (ending === 'snap') return 1 - Math.pow(1 - x, 3);
  if (ending === 'stop') return x < 0.86 ? 0.93 * Math.pow(x / 0.86, 2) : 0.93 + 0.07 * (1 - Math.pow(1 - (x - 0.86) / 0.14, 2));
  if (ending === 'flow') return x;
  return smooth(x);
}
// 0..1 progress of the move at shot time p (0..1). mid = where the move is half done (speed distribution).
export function progress(s, p) {
  if (!s.moving || p < s.start) return 0;
  let x = clamp((p - s.start) / (1 - s.start) / moveWin(s), 0, 1);
  if (s.mid != null && Math.abs(s.mid - 0.5) > 0.005 && x > 0 && x < 1) x = Math.pow(x, Math.log(0.5) / Math.log(s.mid));
  return ease(s.ending, x);
}
export const moveStop = s => Math.min(1, s.start + (s.mlen != null ? s.mlen / s.dur : (1 - s.start) * moveWin(s)));
// Shot time (0..1) at which the move is half done.
export function halfway(s) { for (let i = 0; i <= 400; i++) { const p = i / 400; if (progress(s, p) >= 0.5) return p; } return 1; }

/* ---------- subject points on the previs mannequin (station-local, see plan.js) ---------- */
const DIAL = [-0.25, 1.03, 0.56];
export function actorAt(plan, f) {
  const a = plan.acts ? samplePerf(plan.acts, f / (framesOf(plan) - 1)) : sampleActor(plan, f), yaw = a.yaw + (plan.turn || 0) * D2R, m = plan.mark || [0, 0];
  const root = [m[0], 0, m[1] - a.back], at = v => add(root, rotY(v, yaw)), r = a.reach;
  return {
    yaw, root, fwd: rotY([0, 0, 1], yaw),
    head: at([0, 1.79, 0]), eyes: at([0, 1.8, 0.09]), chest: at([0, 1.32, 0]),
    hands: at([-0.28, 1.53 - 0.68 * Math.cos(r), 0.68 * Math.sin(r)]),
  };
}
// Where the actor may stand: on the dome floor, clear of the console ring.
export const markOk = ([x, z]) => Math.hypot(x - DOME.x, z - DOME.z) <= 4.2;
function subject(s, plan, f) {
  if (s.subj === 'prop') return { F: DIAL.slice(), fwd: [0, 0, -1] };
  if (s.subj === 'wide') return { F: [0, 1.25, -0.4], fwd: [0, 0, -1] };
  const A = actorAt(plan, f);
  const F = { eyes: A.eyes, hands: A.hands, body: A.chest }[s.focus] || A.head;
  return { F, fwd: A.fwd, top: A.head[1] + 0.13 };
}
// The subject is sampled once per shot (the camera does not chase small head moves): where the move lands, or for a
// locked-off shot where the action lands (the hand on the dial, the actor on his mark).
export const refTime = s => (s.moving ? moveStop(s) : 1);

/* ---------- the solver ---------- */
// Returns the camera at shot time p: position, aim, vertical fov (fixed per shot: one lens, like a real prime).
export function solve(s, plan, p) {
  const frames = framesOf(plan) - 1, { F, fwd, top } = subject(s, plan, refTime(s) * frames);
  const q = progress(s, p), fov = verticalFov(s.lens);
  const h0 = FRAME_H[s.size], h1 = s.end ? FRAME_H[s.end] : h0;
  const H = lerpLog(h0, h1, ['push', 'pull', 'crane', 'orbit', 'track'].includes(s.move) ? q : 0);
  const d = (H / 2) / Math.tan(fov / 2 * D2R);
  const sign = ['left', 'down'].includes(s.dir) ? -1 : 1;
  let az = s.az || 0, lateral = 0, lift = 0, look = [0, 0, 0];
  if (s.move === 'orbit') { const a0 = s.az ?? 0, a1 = s.az2 ?? a0 + 70 * sign; az = a0 + (a1 - a0) * q; }
  if (s.move === 'track') lateral = sign * (-0.75 + 0.75 * q);
  if (s.move === 'crane') lift = sign * 0.9 * q;
  if (s.move === 'pan') look = scale(leftOfCam(rotY(fwd, az * D2R)), -sign * 0.9 * q * d * 0.5);
  if (s.move === 'tilt') look = [0, sign * 0.6 * q, 0];
  const aim = F.slice();
  // Headroom: the top of the head sits a tenth of the frame below the top edge, at every size (a wide never centres below the knees).
  if (top != null && ['face', 'body'].includes(s.focus)) aim[1] = Math.max(0.9, top - 0.4 * H);
  const elev = ELEV[s.angle] ?? 0, dir = rotY(fwd, az * D2R);
  let pos = add(aim, scale(dir, d * Math.cos(elev * D2R)));
  pos[1] += d * Math.sin(elev * D2R) + lift;
  if (lateral) pos = add(pos, scale(leftOfCam(dir), lateral));
  const target = lateral ? add(aim, scale(leftOfCam(dir), lateral)) : add(add(aim, look), [0, lift * 0.35, 0]);
  return { pos, aim: target, fov, F, az, H };
}
// The inverse for the overhead view: a camera dragged to ground point [x, z] reads as a side and a frame height.
export function fromGround(s, plan, [x, z]) {
  const { F, fwd } = subject(s, plan, refTime(s) * (framesOf(plan) - 1));
  const v = [x - F[0], z - F[2]], flat = Math.hypot(...v) || 1e-6;
  const az = Math.atan2(fwd[2] * v[0] - fwd[0] * v[1], fwd[0] * v[0] + fwd[2] * v[1]) / D2R;
  const d = flat / Math.cos((ELEV[s.angle] ?? 0) * D2R), H = 2 * d * Math.tan(verticalFov(s.lens) / 2 * D2R);
  return { az, H };
}
// The ladder size whose frame height is closest (in log terms) to H, from a list.
export const nearestSize = (H, list) => list.reduce((a, b) => (Math.abs(Math.log(FRAME_H[b] / H)) < Math.abs(Math.log(FRAME_H[a] / H)) ? b : a));

/* ---------- where the camera may stand ---------- */
// Inside the dome, above the floor, under the glass (same rule as plan.js insideDome).
export function inDome(p) {
  const d = Math.hypot(p[0] - DOME.x, p[2] - DOME.z);
  return p[1] >= 0.3 && d <= DOME.floor && p[1] <= DOME.base + Math.sqrt(Math.max(0, DOME.radius ** 2 - d * d)) - 0.3;
}
const PROBE = [0, 0.25, 0.5, 0.75, 1];
// Why a shot cannot be shot, as the first failure in time: the camera leaves the dome, something solid stands between
// it and the subject, or the actor walks into the lens (within 0.6 m while away from the mark the shot framed).
// Returns null when the shot is clear.
export function whyNot(s, plan, blocked = () => false) {
  const frames = framesOf(plan) - 1, flat = (a, b) => Math.hypot(a[0] - b[0], a[2] - b[2]);
  const mark = actorAt(plan, refTime(s) * frames).head;
  for (const p of PROBE) {
    const c = solve(s, plan, p), h = actorAt(plan, p * frames).head, at = (p * s.dur).toFixed(1);
    if (!inDome(c.pos)) return { at, kind: 'dome', text: `at ${at} s the camera would leave the dome` };
    if (blocked(c.pos, c.F)) return { at, kind: 'set', text: `at ${at} s the set blocks the view of the subject` };
    if (flat(h, mark) > 0.4 && flat(c.pos, h) < 0.6) return { at, kind: 'actor', text: `at ${at} s he walks into the lens` };
  }
  return null;
}
export const clear = (s, plan, blocked) => !whyNot(s, plan, blocked);
// The framing room an idiom leaves the director: side ±30°, one size step either way, the neighbouring heights;
// each option is kept only if the shot stays clear with it. blockedAz lists the side angles the set takes away.
export function roomOf(beat, idiom, s, blocked) {
  const plan = actorPlan(beat), base = idiom.shot, az0 = base.az ?? 0;
  const li = SIZES.indexOf(base.size), ei = SIZES.indexOf(base.end), hi = HEIGHTS.indexOf(base.angle || 'eye');
  const ok = patch => clear({ ...s, ...patch }, plan, blocked);
  const run = []; for (let a = az0 - 30; a <= az0 + 30; a += 5) run.push(a);
  const okAz = run.map(a => ok({ az: a }));
  const cur = Math.round((s.az ?? az0) / 5) * 5, i0 = run.indexOf(cur);
  let lo = i0, up = i0;
  if (i0 >= 0) { while (lo > 0 && okAz[lo - 1]) lo--; while (up < run.length - 1 && okAz[up + 1]) up++; }
  return {
    az0, az: i0 < 0 ? [az0 - 30, az0 + 30] : [run[lo], run[up]], azAll: [az0 - 30, az0 + 30],
    blockedAz: run.filter((a, i) => !okAz[i]),
    sizes: (li < 0 ? [base.size] : SIZES.slice(Math.max(0, li - 1), li + 2)).filter(z => z === s.size || ok({ size: z })),
    ends: base.end ? (ei < 0 ? [base.end] : SIZES.slice(Math.max(0, ei - 1), ei + 2)).filter(z => z === s.end || ok({ end: z })) : null,
    heights: HEIGHTS.slice(Math.max(0, hi - 1), hi + 2).filter(h => h === s.angle || ok({ angle: h })),
  };
}

/* ---------- choosing an idiom per beat ---------- */
const sig = s => s.move + (s.speed === 'fast' ? '!' : '');
export const beatOf = (b0, state) => ({ ...b0, ...(state?.beats?.[b0.id] || {}), ...(state?.perf?.[b0.id]?.acts ? { acts: state.perf[b0.id].acts } : {}) });
export function choose(scene, state, blocked) {
  const P = rulesOf(state), used = new Map();
  let prev = null;
  const rows = scene.beats.map((b0, bi) => {
    const b = beatOf(b0, state), plan = actorPlan(b), target = targetEnergy(b.tension, P);
    const cands = idiomsFor(state, b.event).map((idiom, ii) => {
      const s = effShot(b, idiom, state.over?.[b.id]?.[idiom.name]), why = whyNot(s, plan, blocked);
      let cost = Math.abs(s.energy - target) * 2;
      if (idiom.drama) cost += b.tension >= P.gate ? -0.6 : 2.2;
      if (prev && prev !== 'static' && sig(s) === prev) cost += 0.8 * P.variety;
      cost += 0.3 * P.variety * (used.get(sig(s)) || 0) * (s.moving ? 1 : 0.5);
      if (why) cost += 5;
      return { idiom, s, usable: !why, why, cost: cost + rnd(state.seed || 7, bi, ii) * 0.2 };
    }).sort((a, z) => a.cost - z.cost);
    const pinned = cands.find(c => c.idiom.name === state.pins?.[b.id]);
    const pick = pinned || cands[0];
    used.set(sig(pick.s), (used.get(sig(pick.s)) || 0) + 1); prev = sig(pick.s);
    return { beat: b, plan, target, cands, pick, pinned: !!pinned };
  });
  // Anchor quota: too many anchor-breaking shots → the calmest unpinned beats fall back to their best calm idiom.
  for (let g = 0; g < 8; g++) {
    const br = rows.filter(r => r.pick.s.breaks); if (br.length <= P.quota) break;
    const r = br.filter(x => !x.pinned).sort((a, z) => a.beat.tension - z.beat.tension).find(x => x.cands.some(c => !c.s.breaks && c.usable));
    if (!r) break;
    r.pick = r.cands.find(c => !c.s.breaks && c.usable); r.quotaSwap = true;
  }
  rows.rules = P;
  return rows;
}
// What a change did to the plan beyond the thing touched: beats whose idiom changed.
export function pickChanges(before, after) {
  return after.filter((r, i) => before[i] && before[i].pick.idiom.name !== r.pick.idiom.name)
    .map(r => ({ id: r.beat.id, from: before.find(x => x.beat.id === r.beat.id).pick.idiom.name, to: r.pick.idiom.name, quota: !!r.quotaSwap }));
}

/* ---------- checks ---------- */
export function checks(rows) {
  const out = [], P = rows.rules;
  rows.forEach((r, i) => {
    const s = r.pick.s, id = r.beat.id;
    if (!r.pick.usable) out.push({ kind: 'warn', id, text: `${id}: ${r.pick.why.text}; reframe or pick another idiom` });
    if (s.autoFaster) out.push({ kind: 'info', id, text: `${id}: ${MOVE_LABEL[s.move]} could not finish slowly in ${s.dur} s, so it runs ${s.speed}` });
    if (r.quotaSwap) out.push({ kind: 'info', id, text: `${id}: the scene already used its anchor breaks, so it uses "${r.pick.idiom.name}"` });
    const next = rows[i + 1];
    if (next) { const j = jumpCut(r, next); if (j) out.push({ kind: 'warn', id: next.beat.id, text: `${id} → ${next.beat.id}: same subject, similar size and only ${j}° apart; the cut will jump. Change the size or move the camera 45° or more` }); }
  });
  const breaking = rows.filter(r => r.pick.s.breaks);
  if (breaking.length) out.push({ kind: 'info', text: `Anchor breaks: ${breaking.map(r => r.beat.id).join(', ')}${P ? ` (${breaking.length} of ${P.quota})` : ''}; everything else stays a calm observer` });
  return out.length ? out : [{ kind: 'ok', text: 'No continuity problems' }];
}
export function jumpCut(a, z) {
  const sa = a.pick.s, sz = z.pick.s;
  if (sa.subj !== 'actor' || sz.subj !== 'actor') return null;
  const ha = FRAME_H[sa.end || sa.size], hz = FRAME_H[sz.size];
  if (Math.max(ha, hz) / Math.min(ha, hz) >= 1.4) return null;
  const A = solve(sa, a.plan, 1), Z = solve(sz, z.plan, 0);
  const va = norm(sub(A.pos, A.F)), vz = norm(sub(Z.pos, Z.F));
  const deg = Math.round(Math.acos(clamp(va[0] * vz[0] + va[1] * vz[1] + va[2] * vz[2], -1, 1)) / D2R);
  return deg < 45 ? deg : null;
}

/* ---------- words and the ZeroField plan ---------- */
const sideWords = az => { const n = Math.round(((az + 540) % 360) - 180); return Math.abs(n) > 165 ? 'from behind' : Math.abs(n) < 15 ? 'frontal' : Math.abs(n) > 115 ? `over his ${n > 0 ? 'left' : 'right'} shoulder` : `${n > 0 ? 'left' : 'right'} profile`; };
export function words(s) {
  const size = s.end && s.end !== s.size ? `${s.size} → ${s.end}` : s.size;
  const height = s.angle !== 'eye' ? `, ${HEIGHT_LABEL[s.angle].toLowerCase()}` : '';
  const side = s.subj === 'actor' ? `, ${sideWords(s.az || 0)}` : '';
  const pace = s.speed === 'slow' ? 'slow ' : s.speed === 'fast' ? 'fast ' : '';
  const move = !s.moving ? 'locked-off' : `${pace}${{ push: 'push-in', pull: 'pull-out', orbit: 'orbit', track: `track ${s.dir || 'right'}`, crane: `crane ${s.dir || 'up'}`, pan: `pan ${s.dir || 'right'}`, tilt: `tilt ${s.dir || 'up'}` }[s.move]}`;
  const lead = s.moving && s.start > 0 ? `holds, then from ${(s.start * s.dur).toFixed(1)} s ` : '';
  const stop = moveStop(s), done = s.moving && stop < 0.97 ? `, settled by ${(stop * s.dur).toFixed(1)} s` : '';
  const end = s.moving && s.ending !== 'ease' ? `, ${ENDINGS[s.ending]}` : '';
  return `${size}${height}${side} · ${lead}${move}${done}${end}, ${s.lens}mm`;
}
// plan.js sampleCamera eases the whole shot once (smoothstep) before following the keys; keys are written at the
// inverse so the 3D Stage replays this timing. 17 keys keep the Catmull-Rom path on the solved curve.
const unsmooth = y => 0.5 - Math.sin(Math.asin(clamp(1 - 2 * y, -1, 1)) / 3);
export function toPlan(r, mood = 'grey') {
  const s = r.pick.s, plan = { ...actorPlan(r.beat), mood, lens: LENSES.reduce((a, b) => (Math.abs(b - s.lens) < Math.abs(a - s.lens) ? b : a)) };
  const round = v => v.map(x => Math.round(x * 1000) / 1000);
  plan.keys = Array.from({ length: 17 }, (_, i) => { const u = i * 6, c = solve(s, plan, unsmooth(u / 96)); return [u, round(c.pos), round(c.aim)]; });
  if (!plan.mark[0] && !plan.mark[1] && !plan.turn) { delete plan.mark; delete plan.turn; }  // the 3D Stage plan has no mark field yet (SPEC_09 §8)
  delete plan.acts;  // the 3D Stage animates its three canned actions; re-timed performance keys need a plan field (SPEC_10 §4)
  return plan;
}
