// Shot grammar (prototype): shots written in film terms (shot size, height, side, move, speed, ending) and solved into a
// camera on the ZeroField previs stage, relative to the subject. Ported from the shot-idiom generator prototype; plain
// data and math, no DOM, so node can test it. Obstruction by set geometry is injected by the caller (`blocked`).
// Interaction rules: docs/specs/SPEC_09_SHOT_GRAMMAR_INTERACTION.md.
import { DOME, LENSES, framesOf, sampleActor, verticalFov } from '../../src/previs/plan.js';
import { BEAT_STORY, toActs } from './perf.js';
// Height of each build relative to the default mannequin (scene.js actor scales the body the same way).
const BUILD_SCALE = { man: 1, woman: 0.94, child: 0.64, elder: 1 };

/* ---------- vocabulary ---------- */
// Shot size = the height of frame visible at the subject, in metres. The ladder runs wide to tight; INSERT is off-ladder.
export const SIZES = ['EWS', 'WS', 'MWS', 'MS', 'MCU', 'CU', 'ECU', 'EYES'];
export const FRAME_H = { EWS: 7, WS: 2.6, MWS: 1.35, MS: 0.8, MCU: 0.5, CU: 0.3, ECU: 0.16, EYES: 0.11, INSERT: 0.38 };
export const SIZE_LABEL = { EWS: 'Extreme wide', WS: 'Wide', MWS: 'Medium wide', MS: 'Medium', MCU: 'Medium close-up', CU: 'Close-up', ECU: 'Extreme close-up', EYES: 'Eyes', INSERT: 'Insert' };
export const HEIGHTS = ['low', 'eye', 'high'];
export const ELEV = { low: -12, eye: 0, high: 30 };
// Fine framing (held Shift): still film terms relative to the subject, so the camera keeps following the actor and every
// check (room, line, jump cut, words) keeps working. hk / hk2 scale the start / end frame height around the shot size
// (a step of the ladder is about x1.6, so x0.8-1.25 reaches halfway to the next size); elev is the camera height in
// degrees between the idiom's lowest and highest height; side is already an angle and takes 1° steps.
export const FINE = { hk: [0.8, 1.25] };
export const elevOf = s => s.elev ?? ELEV[s.angle] ?? 0;
// The height word for a fine elevation: the nearest of low, eye, high.
export const nearestHeight = e => HEIGHTS.reduce((a, b) => (Math.abs(ELEV[b] - e) < Math.abs(ELEV[a] - e) ? b : a));
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
    { name: 'Two-shot, wide', pair: true, lens: 24, shot: { subj: 'pair', focus: 'body', size: 'WS', angle: 'eye', az: 0, move: 'static' } },
  ],
  turn: [
    { name: 'Locked three-quarter', shot: { subj: 'actor', focus: 'face', size: 'MCU', angle: 'eye', az: 140, move: 'static' } },
    { name: 'Slow push to close-up', shot: { subj: 'actor', focus: 'face', size: 'MS', end: 'CU', angle: 'eye', az: 150, move: 'push', speed: 'slow' } },
    { name: 'Arc to profile', shot: { subj: 'actor', focus: 'face', size: 'MCU', angle: 'eye', az: 165, az2: 100, move: 'orbit', speed: 'slow' } },
    { name: 'Snap push to the eyes', drama: true, shot: { subj: 'actor', focus: 'eyes', size: 'MCU', end: 'ECU', angle: 'eye', az: 130, move: 'push', start: 0.35, speed: 'fast', ending: 'stop' } },
    { name: 'Over the shoulder', pair: true, lens: 85, shot: { subj: 'actor', focus: 'face', size: 'MCU', angle: 'eye', az: 16, ots: true, move: 'static' } },
  ],
  action: [
    { name: 'Insert on the hands', lens: 50, shot: { subj: 'actor', focus: 'hands', size: 'INSERT', angle: 'high', az: 150, move: 'static' } },
    { name: 'Over-the-shoulder push to the dial', shot: { subj: 'prop', focus: 'prop', size: 'MS', end: 'MCU', angle: 'high', az: 12, move: 'push', speed: 'slow' } },
    { name: 'Track along the console', shot: { subj: 'actor', focus: 'body', size: 'MWS', angle: 'eye', az: 120, move: 'track', dir: 'left', speed: 'mid' } },
    { name: 'Low-angle reach', shot: { subj: 'actor', focus: 'hands', size: 'MS', angle: 'low', az: 110, move: 'static' } },
    { name: 'Over the shoulder onto the hands', pair: true, lens: 50, shot: { subj: 'actor', focus: 'hands', size: 'MS', angle: 'high', az: 22, ots: true, move: 'static' } },
  ],
  reveal: [
    { name: 'Low-angle push', shot: { subj: 'actor', focus: 'body', size: 'MWS', end: 'MS', angle: 'low', az: 140, move: 'push', speed: 'slow' } },
    { name: 'Tilt up to the sky', shot: { subj: 'actor', focus: 'body', size: 'MWS', angle: 'eye', az: 170, move: 'tilt', dir: 'up', speed: 'slow' } },
    { name: 'Pull back to the glass', drama: true, lens: 24, shot: { subj: 'actor', focus: 'face', size: 'CU', end: 'WS', angle: 'eye', az: 150, move: 'pull', speed: 'mid' } },
    { name: 'Whip to the light', drama: true, shot: { subj: 'actor', focus: 'body', size: 'MS', angle: 'eye', az: 160, move: 'pan', dir: 'right', start: 0.4, speed: 'fast', ending: 'stop' } },
    { name: 'Two-shot push', pair: true, shot: { subj: 'pair', focus: 'body', size: 'MWS', end: 'MS', angle: 'low', az: 15, move: 'push', speed: 'slow' } },
  ],
  pressure: [
    { name: 'Low-angle hold', shot: { subj: 'actor', focus: 'face', size: 'MCU', angle: 'low', az: 135, move: 'static' } },
    { name: 'Profile hold', lens: 50, shot: { subj: 'actor', focus: 'face', size: 'MCU', angle: 'eye', az: 95, move: 'static' } },
    { name: 'Creeping push', shot: { subj: 'actor', focus: 'face', size: 'MWS', end: 'MCU', angle: 'eye', az: 165, move: 'push', speed: 'slow', ending: 'flow' } },
    { name: 'Crash push', drama: true, shot: { subj: 'actor', focus: 'face', size: 'MS', end: 'CU', angle: 'eye', az: 145, move: 'push', start: 0.4, speed: 'fast', ending: 'stop' } },
    { name: 'Push past the shoulder', pair: true, lens: 50, shot: { subj: 'actor', focus: 'face', size: 'MS', end: 'MCU', angle: 'eye', az: 20, ots: true, move: 'push', speed: 'slow' } },
  ],
  end: [
    { name: 'Hold on him', shot: { subj: 'actor', focus: 'face', size: 'MS', angle: 'eye', az: 20, move: 'static' } },
    { name: 'Drift out', shot: { subj: 'actor', focus: 'face', size: 'MCU', end: 'MWS', angle: 'eye', az: 25, move: 'pull', speed: 'slow' } },
    { name: 'Crane up and away', lens: 24, shot: { subj: 'actor', focus: 'body', size: 'MWS', end: 'WS', angle: 'eye', az: 30, move: 'crane', dir: 'up', speed: 'slow' } },
    { name: 'Two-shot pull-out', pair: true, lens: 24, shot: { subj: 'pair', focus: 'body', size: 'MWS', end: 'WS', angle: 'eye', az: 10, move: 'pull', speed: 'slow' } },
  ],
};
// The idioms a beat can use: the library plus the director's own (saved from a framed shot). Two-person idioms (pair:
// two-shots, over-the-shoulders) only for a beat with someone else in it.
export const idiomsFor = (state, event, beat) => [...IDIOMS[event], ...(state?.custom?.[event] || []).map(i => ({ ...i, mine: true }))]
  .filter(i => !beat || !i.pair || beat.partner);
// Parameters a framed shot carries into a saved idiom.
const SHOT_KEYS = ['subj', 'focus', 'size', 'end', 'angle', 'az', 'az2', 'ots', 'hk', 'hk2', 'elev', 'move', 'dir', 'speed', 'ending', 'start', 'mlen', 'mid'];
export function idiomFromShot(name, s) {
  const shot = {}; for (const k of SHOT_KEYS) if (s[k] != null && !(k === 'start' && !s[k])) shot[k] = s[k];
  return { name, lens: s.lens, shot };
}

/* ---------- the scenes: The Last Signal, one beat per slate row ---------- */
// action / facing drive the existing previs mannequin (plan.js sampleActor); seconds is 4, 6 or 8 (LTX 8n+1 frames).
// who: the beat's subject (the shot's own actor); with: someone else in the shot. A scene with blocking keeps each
// person on one mark through every shot (dragging someone moves them for the whole scene).
const KAEL = { name: 'Kael', figure: { build: 'man', outfit: 'jacket', hair: 'short', tone: 0 } };
export const SCENE = {
  id: 'solo', title: 'The Last Signal · Observatory', cast: { kael: KAEL },
  premise: 'Kael: a radio operator in his thirties, alone in a glass observatory during a storm, waiting for an answer to his signal.',
  beats: [
    { id: 'S01', title: 'Kael enters the dome', event: 'establish', tension: 0.2, seconds: 6, action: 'walkin', facing: 'console' },
    { id: 'S02', title: 'At the console', event: 'turn', tension: 0.35, seconds: 4, action: 'stand', facing: 'console' },
    { id: 'S03', title: 'A light answers outside', event: 'reveal', tension: 0.85, seconds: 6, action: 'turnreach', facing: 'console' },
    { id: 'S04', title: 'His hand on the record key', event: 'action', tension: 0.5, seconds: 4, action: 'turnreach', facing: 'console' },
    { id: 'S05', title: 'The beacon pulses', event: 'pressure', tension: 0.7, seconds: 6, action: 'stand', facing: 'console' },
    { id: 'S06', title: 'He decides to speak', event: 'end', tension: 0.3, seconds: 4, action: 'stand', facing: 'room' },
  ],
};
// A two-hander (SPEC_10 P3): Mira, the relief operator, arrives; Kael tells her the signal answered. They face each
// other across the floor; the 180° line runs between them.
export const RELIEF = {
  id: 'relief', title: 'The Last Signal · Relief', cast: { kael: KAEL, mira: { name: 'Mira', figure: { build: 'woman', outfit: 'longcoat', hair: 'bun', tone: 1 } } },
  premise: 'Kael: a radio operator in his thirties who has kept the observatory alone through the storm. Mira: the relief operator, a woman in her forties in a long coat, arriving for the night shift. He tells her the signal answered.',
  blocking: { kael: [0, -0.5], mira: [0.5, -2.1] },  // each person's mark for the whole scene: the coverage cuts between the same two places
  beats: [
    { id: 'R01', title: 'Mira arrives', event: 'establish', tension: 0.25, seconds: 6, who: 'kael', with: 'mira' },
    { id: 'R02', title: 'You heard it too?', event: 'turn', tension: 0.45, seconds: 4, who: 'mira', with: 'kael' },
    { id: 'R03', title: 'He plays her the recording', event: 'action', tension: 0.5, seconds: 4, who: 'kael', with: 'mira' },
    { id: 'R04', title: 'She does not believe it', event: 'pressure', tension: 0.7, seconds: 6, who: 'mira', with: 'kael' },
    { id: 'R05', title: 'The beacon answers', event: 'reveal', tension: 0.88, seconds: 6, who: 'kael', with: 'mira' },
    { id: 'R06', title: 'Then answer it', event: 'end', tension: 0.3, seconds: 4, who: 'mira', with: 'kael' },
  ],
};
export const SCENES = { solo: SCENE, relief: RELIEF };
export const sceneOf = state => SCENES[state?.scene] || SCENE;

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
// figure / cast: the subject's look and anyone else in the shot (scene.js builds and poses them all); side: which side
// of the line between the two the camera keeps (+1 left of subject → partner), for the solver only.
export function actorPlan(b) {
  const mark = b.mark || [0, 0], p = b.partner, story = BEAT_STORY[b.id];
  const plan = { set: 'observatory', move: 'static', lens: 35, action: b.action || 'stand', facing: b.facing || 'console', mood: 'grey', seconds: b.seconds, keys: null,
    figure: b.figure, mark, turn: b.turn || 0, acts: toActs(b.acts || story?.acts, mark, p?.mark) || undefined };
  if (p) plan.cast = [{ figure: p.figure, mark: p.mark, turn: p.turn || 0, acts: toActs(story?.pacts || [{ at: 0, look: 'partner' }], p.mark, mark) }];
  if (p) plan.side = b.side || 1;
  return plan;
}

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
  // Two in the shot: keep the camera on the scene's side of the line between them (an over-the-shoulder on Kael and its
  // reverse on Mira mirror each other), unless the director set the side by hand. Over the partner's shoulder when close to the axis.
  // The nearest side to the idiom's that stands clear of the line (the mirror first, then 5° steps either way); a subject
  // who turns away from the partner can leave both the idiom's side and its mirror on the line.
  if (beat.partner && (s.subj === 'actor' || s.subj === 'wide')) {
    const plan = actorPlan(beat);
    // Over the shoulder: just off the line, so the near shoulder (about 0.3 m out from the line at the partner) frames the
    // subject; a push past the shoulder runs 0.45 m out so the camera slides by the partner instead of through them.
    if (s.ots && over.az == null) { const [a, b] = [plan.mark, beat.partner.mark]; s.az = Math.sign(s.az || 1) * Math.round(Math.atan2(s.moving ? 0.45 : 0.3, Math.hypot(b[0] - a[0], b[1] - a[1])) / D2R); }
    const ok = az => { const c = solve({ ...s, az, az2: s.az2 != null ? s.az2 + az - (s.az || 0) : undefined }, plan, 0); return lineDist(plan, c.pos) * plan.side > 0.15; };
    if (over.az == null && !ok(s.az || 0)) {
      const a0 = s.az || 0, tries = [-a0, ...Array.from({ length: 24 }, (_, i) => (i % 2 ? -1 : 1) * 5 * (1 + (i >> 1))).flatMap(d => [a0 + d, -a0 + d])];
      const az = tries.find(ok);
      if (az != null) { if (s.az2 != null) s.az2 += az - a0; s.az = az; s.mirrored = true; }
    }
    if (s.subj === 'actor' && Math.abs(s.az || 0) <= 35) s.overName = beat.partner.name;
  }
  if (s.subj === 'pair' && beat.partner) s.pairNames = [beat.name, beat.partner.name];
  return s;
}
// Signed distance (metres) of a point from the line through the subject and the partner: + on one side, - on the other.
export function lineDist(plan, pos) {
  const a = plan.mark || [0, 0], b = plan.cast?.[0]?.mark; if (!b) return 0;
  return ((b[0] - a[0]) * (pos[2] - a[1]) - (b[1] - a[1]) * (pos[0] - a[0])) / (Math.hypot(b[0] - a[0], b[1] - a[1]) || 1);
}
export const sideOf = (plan, pos) => Math.sign(lineDist(plan, pos)) || 1;
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
  const a = sampleActor(plan, f), yaw = a.yaw + (plan.turn || 0) * D2R, m = plan.mark || [0, 0], k = BUILD_SCALE[plan.figure?.build] || 1;
  const root = [m[0], 0, m[1] - a.back], at = v => add(root, rotY(v.map(x => x * k), yaw)), r = a.reach;
  return {
    yaw, root, fwd: rotY([0, 0, 1], yaw),
    head: at([0, 1.79, 0]), eyes: at([0, 1.8, 0.09]), chest: at([0, 1.32, 0]),
    hands: at([-0.28, 1.53 - 0.68 * Math.cos(r), 0.68 * Math.sin(r)]),
  };
}
// The other person in the shot, where they stand (they do not walk in this prototype).
export function partnerAt(plan) {
  const c = plan.cast?.[0]; if (!c) return null;
  const k = BUILD_SCALE[c.figure?.build] || 1, root = [c.mark[0], 0, c.mark[1]];
  return { root, head: [root[0], 1.79 * k, root[2]], chest: [root[0], 1.32 * k, root[2]] };
}
// Where the actor may stand: on the dome floor, clear of the console ring.
export const markOk = ([x, z]) => Math.hypot(x - DOME.x, z - DOME.z) <= 4.2;
function subject(s, plan, f) {
  if (s.subj === 'prop') return { F: DIAL.slice(), fwd: [0, 0, -1] };
  if (s.subj === 'wide') return { F: [0, 1.25, -0.4], fwd: [0, 0, -1] };
  if (s.subj === 'pair') {  // both of them: framed on the middle, the camera faces the line from the scene's side
    const A = actorAt(plan, f), B = partnerAt(plan), ax = norm([B.root[0] - A.root[0], 0, B.root[2] - A.root[2]]), side = plan.side || 1;
    const mid = (p, q) => p.map((v, i) => (v + q[i]) / 2);
    return { F: s.focus === 'body' ? mid(A.chest, B.chest) : mid(A.head, B.head), fwd: [-ax[2] * side, 0, ax[0] * side], top: Math.max(A.head[1], B.head[1]) + 0.13 };
  }
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
  const h0 = FRAME_H[s.size] * (s.hk || 1), h1 = s.end ? FRAME_H[s.end] * (s.hk2 || 1) : h0;  // hk / hk2: fine framing around the size (FINE)
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
  const elev = elevOf(s), dir = rotY(fwd, az * D2R);
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
  const d = flat / Math.cos(elevOf(s) * D2R), H = 2 * d * Math.tan(verticalFov(s.lens) / 2 * D2R);
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
    const B = partnerAt(plan); if (B && flat(c.pos, B.root) < 0.35) return { at, kind: 'actor', text: `at ${at} s the camera would stand inside the other actor` };
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
// A beat as played: the director's overrides, re-timed performance keys, who is in it (from the scene's cast), where
// everyone stands (the scene's blocking, as the director moved it) and the side of the line the scene keeps.
export const markOf = (scene, state, who) => state?.blocking?.[scene.id]?.[who] || scene.blocking?.[who];
export function beatOf(b0, state, scene = SCENE) {
  const o = state?.beats?.[b0.id] || {}, b = { ...b0, ...o, ...(state?.perf?.[b0.id]?.acts ? { acts: state.perf[b0.id].acts } : {}) };
  const id = b.who || Object.keys(scene.cast)[0], who = scene.cast[id];
  b.who = id; b.name = who.name; b.figure = who.figure;
  if (scene.blocking) b.mark = markOf(scene, state, id);
  if (b.with) b.partner = { id: b.with, name: scene.cast[b.with].name, figure: scene.cast[b.with].figure, mark: markOf(scene, state, b.with) || [0, -1.5], turn: 0 };
  b.side = state?.side?.[scene.id] || 1;
  return b;
}
export function choose(scene, state, blocked) {
  const P = rulesOf(state), used = new Map();
  let prev = null;
  const rows = scene.beats.map((b0, bi) => {
    const b = beatOf(b0, state, scene), plan = actorPlan(b), target = targetEnergy(b.tension, P);
    const cands = idiomsFor(state, b.event, b).map((idiom, ii) => {
      const s = effShot(b, idiom, state.over?.[b.id]?.[idiom.name]), why = whyNot(s, plan, blocked);
      let cost = Math.abs(s.energy - target) * 2;
      if (idiom.drama) cost += b.tension >= P.gate ? -0.6 : 2.2;
      if (idiom.pair) cost -= 0.5;  // two people in the beat: coverage (two-shots, over-the-shoulders) comes first
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
export function pickChanges(before, after) {  // by beat id: a scene switch shares none, so it reports none
  const was = id => before.find(x => x.beat.id === id);
  return after.filter(r => was(r.beat.id) && was(r.beat.id).pick.idiom.name !== r.pick.idiom.name)
    .map(r => ({ id: r.beat.id, from: was(r.beat.id).pick.idiom.name, to: r.pick.idiom.name, quota: !!r.quotaSwap }));
}

/* ---------- checks ---------- */
export function checks(rows) {
  const out = [], P = rows.rules;
  rows.forEach((r, i) => {
    const s = r.pick.s, id = r.beat.id;
    if (!r.pick.usable) out.push({ kind: 'warn', id, text: `${id}: ${r.pick.why.text}; reframe or pick another idiom` });
    if (s.autoFaster) out.push({ kind: 'info', id, text: `${id}: ${MOVE_LABEL[s.move]} could not finish slowly in ${s.dur} s, so it runs ${s.speed}` });
    if (r.quotaSwap) out.push({ kind: 'info', id, text: `${id}: the scene already used its anchor breaks, so it uses "${r.pick.idiom.name}"` });
    if (r.beat.partner) {
      const crossed = [0, 1].some(p => sideOf(r.plan, solve(s, r.plan, p).pos) !== r.plan.side);
      if (crossed) out.push({ kind: 'warn', id, text: `${id}: the camera crosses the 180° line between ${r.beat.name} and ${r.beat.partner.name}; on the cut they swap sides of the frame. Keep it on the scene's side or flip the side for the whole scene` });
    }
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
  const ha = FRAME_H[sa.end || sa.size] * ((sa.end ? sa.hk2 : sa.hk) || 1), hz = FRAME_H[sz.size] * (sz.hk || 1);
  if (Math.max(ha, hz) / Math.min(ha, hz) >= 1.4) return null;
  const A = solve(sa, a.plan, 1), Z = solve(sz, z.plan, 0);
  const va = norm(sub(A.pos, A.F)), vz = norm(sub(Z.pos, Z.F));
  const deg = Math.round(Math.acos(clamp(va[0] * vz[0] + va[1] * vz[1] + va[2] * vz[2], -1, 1)) / D2R);
  return deg < 45 ? deg : null;
}

/* ---------- words and the ZeroField plan ---------- */
const sideWords = az => { const n = Math.round(((az + 540) % 360) - 180); return Math.abs(n) > 165 ? 'from behind' : Math.abs(n) < 15 ? 'frontal' : Math.abs(n) > 115 ? `over the ${n > 0 ? 'left' : 'right'} shoulder` : `${n > 0 ? 'left' : 'right'} profile`; };
const fineSize = (z, k) => (k && Math.abs(k - 1) > 0.02 ? `${z} (${Math.round(Math.abs(k - 1) * 100)}% ${k > 1 ? 'wider' : 'tighter'})` : z);
export function words(s) {
  const size = s.end && s.end !== s.size ? `${fineSize(s.size, s.hk)} → ${fineSize(s.end, s.hk2)}` : fineSize(s.size, s.hk);
  const height = s.elev != null ? (Math.abs(s.elev) < 1 ? '' : `, camera ${Math.abs(Math.round(s.elev))}° ${s.elev > 0 ? 'above' : 'below'} eye level`) : s.angle !== 'eye' ? `, ${HEIGHT_LABEL[s.angle].toLowerCase()}` : '';
  const side = s.subj === 'pair' ? `, two-shot of ${s.pairNames?.join(' and ') || 'both'}` : s.subj === 'actor' ? (s.overName ? `, over ${s.overName}'s shoulder` : `, ${sideWords(s.az || 0)}`) : '';
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
  if (!plan.mark[0] && !plan.mark[1] && !plan.turn) { delete plan.mark; delete plan.turn; }  // on the station: the plan stays as small as before
  delete plan.side;
  return plan;
}
