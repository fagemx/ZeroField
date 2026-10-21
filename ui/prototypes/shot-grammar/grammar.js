// Shot grammar (prototype): shots written in film terms (shot size, height, side, move, speed, ending) and solved into a
// camera on the ZeroField previs stage, relative to the subject. Ported from the shot-idiom generator prototype; plain
// data and math, no DOM, so node can test it. Obstruction by set geometry is injected by the caller (`blocked`).
import { DOME, LENSES, framesOf, sampleActor, verticalFov } from '../../src/previs/plan.js';

/* ---------- vocabulary ---------- */
// Shot size = the height of frame visible at the subject, in metres. The ladder runs wide to tight; INSERT is off-ladder.
export const SIZES = ['EWS', 'WS', 'MWS', 'MS', 'MCU', 'CU', 'ECU', 'EYES'];
export const FRAME_H = { EWS: 7, WS: 2.6, MWS: 1.35, MS: 0.8, MCU: 0.5, CU: 0.3, ECU: 0.16, EYES: 0.11, INSERT: 0.38 };
export const SIZE_LABEL = { EWS: 'Extreme wide', WS: 'Wide', MWS: 'Medium wide', MS: 'Medium', MCU: 'Medium close-up', CU: 'Close-up', ECU: 'Extreme close-up', EYES: 'Eyes', INSERT: 'Insert' };
export const HEIGHTS = ['low', 'eye', 'high'];
const ELEV = { low: -12, eye: 0, high: 30 };
export const HEIGHT_LABEL = { low: 'Low angle', eye: 'Eye level', high: 'High angle' };
export const MOVE_LABEL = { static: 'Locked-off', push: 'Push in', pull: 'Pull out', orbit: 'Orbit', track: 'Track', crane: 'Crane', pan: 'Pan', tilt: 'Tilt' };
export const SPEEDS = ['slow', 'mid', 'fast'];
export const ENDINGS = { ease: 'eases to a stop', stop: 'stops abruptly', snap: 'snaps into motion', flow: 'keeps moving into the cut' };
export const EVENTS = { establish: 'Establish', turn: 'Character turn', action: 'Hands & props', reveal: 'Reveal', pressure: 'Pressure', end: 'Button' };

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

export const PRESETS = {
  calm: { label: 'Calm', shift: -0.1, gate: 0.92, quota: 1 },
  standard: { label: 'Standard', shift: 0, gate: 0.8, quota: 1 },
  heightened: { label: 'Heightened', shift: 0.12, gate: 0.6, quota: 2 },
};

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
export const actorPlan = b => ({ set: 'observatory', move: 'static', lens: 35, action: b.action, facing: b.facing, mood: 'grey', seconds: b.seconds, keys: null });

// Idiom shot + the director's overrides; speed steps up when the move cannot finish in the time it has.
export function effShot(beat, idiom, over = {}) {
  const s = { lens: idiom.lens || 35, angle: 'eye', ending: 'ease', speed: 'mid', start: 0, ...idiom.shot, ...over };
  s.dur = beat.seconds; s.moving = s.move !== 'static';
  if (!s.moving) s.start = 0;
  s.moveDur = s.mlen != null ? Math.min(s.mlen, s.dur * (1 - s.start)) : s.dur * (1 - s.start);
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
export function energyOf(s) {
  const mag = s.end ? Math.min(1, Math.abs(Math.log(FRAME_H[s.size] / FRAME_H[s.end])) / Math.log(8)) : (s.moving ? 0.35 : 0);
  const spd = s.moving ? { slow: 0, mid: 0.18, fast: 0.38 }[s.speed] : 0;
  return Math.min(1, 0.05 + (s.moving ? 0.12 : 0) + 0.3 * mag + spd + (s.ending === 'stop' && s.moving ? 0.12 : 0) + (s.angle === 'low' ? 0.08 : 0));
}
// The scene's camera anchor is a calm observer; a fast move or a whip breaks it, and the film gets a quota of those.
export const breaksAnchor = s => s.moving && s.speed === 'fast';

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

/* ---------- subject points on the previs mannequin (station-local, see plan.js) ---------- */
const DIAL = [-0.25, 1.03, 0.56];
export function actorAt(plan, f) {
  const a = sampleActor(plan, f), root = [0, 0, -a.back], at = v => add(root, rotY(v, a.yaw));
  const r = a.reach;
  return {
    yaw: a.yaw, fwd: rotY([0, 0, 1], a.yaw),
    head: at([0, 1.79, 0]), eyes: at([0, 1.8, 0.09]), chest: at([0, 1.32, 0]),
    hands: at([-0.28, 1.53 - 0.68 * Math.cos(r), 0.68 * Math.sin(r)]),
  };
}
function subject(s, plan, f) {
  if (s.subj === 'prop') return { F: DIAL.slice(), fwd: [0, 0, -1] };
  const A = actorAt(plan, f);
  if (s.subj === 'wide') return { F: [0, 1.25, -0.4], fwd: [0, 0, -1] };
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
  return { pos, aim: target, fov, F };
}

/* ---------- where the camera may stand ---------- */
// Inside the dome, above the floor, under the glass (same rule as plan.js insideDome).
export function inDome(p) {
  const d = Math.hypot(p[0] - DOME.x, p[2] - DOME.z);
  return p[1] >= 0.3 && d <= DOME.floor && p[1] <= DOME.base + Math.sqrt(Math.max(0, DOME.radius ** 2 - d * d)) - 0.3;
}
const PROBE = [0, 0.25, 0.5, 0.75, 1];
// A shot is clear when the camera stays in the dome, nothing solid stands between it and the subject, and the actor never
// walks into the lens (within 0.6 m while he is away from the mark the shot was framed on), at five sample times.
export function clear(s, plan, blocked = () => false) {
  const frames = framesOf(plan) - 1, flat = (a, b) => Math.hypot(a[0] - b[0], a[2] - b[2]);
  const mark = actorAt(plan, refTime(s) * frames).head;
  return PROBE.every(p => {
    const c = solve(s, plan, p), h = actorAt(plan, p * frames).head;
    const inTheLens = flat(h, mark) > 0.4 && flat(c.pos, h) < 0.6;
    return inDome(c.pos) && !inTheLens && !blocked(c.pos, c.F);
  });
}
// The framing room an idiom leaves the director: side ±30°, one size step either way, the neighbouring heights;
// each option is kept only if the shot stays clear with it.
export function roomOf(beat, idiom, s, blocked) {
  const plan = actorPlan(beat), base = idiom.shot, az0 = base.az ?? 0;
  const li = SIZES.indexOf(base.size), ei = SIZES.indexOf(base.end), hi = HEIGHTS.indexOf(base.angle || 'eye');
  const ok = patch => clear({ ...s, ...patch }, plan, blocked);
  const run = []; for (let a = az0 - 30; a <= az0 + 30; a += 5) run.push(a);
  const cur = s.az ?? az0, i0 = run.indexOf(Math.round(cur / 5) * 5);
  let lo = i0, up = i0;
  if (i0 >= 0) { while (lo > 0 && ok({ az: run[lo - 1] })) lo--; while (up < run.length - 1 && ok({ az: run[up + 1] })) up++; }
  return {
    az0, az: i0 < 0 ? [az0 - 30, az0 + 30] : [run[lo], run[up]],
    sizes: (li < 0 ? [base.size] : SIZES.slice(Math.max(0, li - 1), li + 2)).filter(z => z === s.size || ok({ size: z })),
    ends: base.end ? (ei < 0 ? [base.end] : SIZES.slice(Math.max(0, ei - 1), ei + 2)).filter(z => z === s.end || ok({ end: z })) : null,
    heights: HEIGHTS.slice(Math.max(0, hi - 1), hi + 2).filter(h => h === s.angle || ok({ angle: h })),
  };
}

/* ---------- choosing an idiom per beat ---------- */
const sig = s => s.move + (s.speed === 'fast' ? '!' : '');
export function choose(scene, state, blocked) {
  const P = PRESETS[state.preset] || PRESETS.standard, used = new Map();
  let prev = null;
  const rows = scene.beats.map((b0, bi) => {
    const b = { ...b0, ...(state.beats?.[b0.id] || {}) }, plan = actorPlan(b);
    const target = clamp(0.08 + 0.8 * b.tension + P.shift, 0, 1);
    const cands = IDIOMS[b.event].map((idiom, ii) => {
      const s = effShot(b, idiom, state.over?.[b.id]?.[idiom.name]), usable = clear(s, plan, blocked);
      let cost = Math.abs(s.energy - target) * 2;
      if (idiom.drama) cost += b.tension >= P.gate ? -0.6 : 2.2;
      if (prev && prev !== 'static' && sig(s) === prev) cost += 0.8;
      cost += 0.3 * (used.get(sig(s)) || 0) * (s.moving ? 1 : 0.5);
      if (!usable) cost += 5;
      return { idiom, s, usable, cost: cost + rnd(state.seed || 7, bi, ii) * 0.2 };
    }).sort((a, z) => a.cost - z.cost);
    const pinned = cands.find(c => c.idiom.name === state.pins?.[b.id]);
    const pick = pinned || cands[0];
    used.set(sig(pick.s), (used.get(sig(pick.s)) || 0) + 1); prev = sig(pick.s);
    return { beat: b, plan, cands, pick, pinned: !!pinned };
  });
  // Anchor quota: too many anchor-breaking shots → the calmest unpinned beats fall back to their best calm idiom.
  for (let g = 0; g < 8; g++) {
    const br = rows.filter(r => r.pick.s.breaks); if (br.length <= P.quota) break;
    const r = br.filter(x => !x.pinned).sort((a, z) => a.beat.tension - z.beat.tension).find(x => x.cands.some(c => !c.s.breaks && c.usable));
    if (!r) break;
    r.pick = r.cands.find(c => !c.s.breaks && c.usable); r.quotaSwap = true;
  }
  return rows;
}

/* ---------- checks ---------- */
export function checks(rows) {
  const out = [];
  rows.forEach((r, i) => {
    const s = r.pick.s, id = r.beat.id;
    if (!r.pick.usable) out.push({ kind: 'warn', id, text: `${id}: the camera passes through the set or loses the subject; reframe or pick another idiom` });
    if (s.autoFaster) out.push({ kind: 'info', id, text: `${id}: ${MOVE_LABEL[s.move]} could not finish slowly in ${s.dur} s, so it runs ${s.speed}` });
    if (r.quotaSwap) out.push({ kind: 'info', id, text: `${id}: the film already breaks its calm camera once, so it uses "${r.pick.idiom.name}"` });
    const next = rows[i + 1];
    if (next) { const j = jumpCut(r, next); if (j) out.push({ kind: 'warn', id: next.beat.id, text: `${id} → ${next.beat.id}: same subject, similar size and only ${j}° apart; the cut will jump. Change the size or move the camera 45° or more` }); }
  });
  const breaking = rows.filter(r => r.pick.s.breaks);
  if (breaking.length) out.push({ kind: 'info', text: `Anchor breaks: ${breaking.map(r => r.beat.id).join(', ')} (fast moves; everything else stays a calm observer)` });
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
export function words(s) {
  const size = s.end && s.end !== s.size ? `${s.size} → ${s.end}` : s.size;
  const height = s.angle !== 'eye' ? `, ${HEIGHT_LABEL[s.angle].toLowerCase()}` : '';
  const pace = s.speed === 'slow' ? 'slow ' : s.speed === 'fast' ? 'fast ' : '';
  const move = !s.moving ? 'locked-off' : `${pace}${{ push: 'push-in', pull: 'pull-out', orbit: 'orbit', track: `track ${s.dir || 'right'}`, crane: `crane ${s.dir || 'up'}`, pan: `pan ${s.dir || 'right'}`, tilt: `tilt ${s.dir || 'up'}` }[s.move]}`;
  const lead = s.moving && s.start > 0 ? `holds, then from ${(s.start * s.dur).toFixed(1)} s ` : '';
  const end = s.moving && s.ending !== 'ease' ? `, ${ENDINGS[s.ending]}` : '';
  return `${size}${height} · ${lead}${move}${end}, ${s.lens}mm`;
}
// plan.js sampleCamera eases the whole shot once (smoothstep) before following the keys; keys are written at the
// inverse so the 3D Stage replays this timing. 17 keys keep the Catmull-Rom path on the solved curve.
const unsmooth = y => 0.5 - Math.sin(Math.asin(clamp(1 - 2 * y, -1, 1)) / 3);
export function toPlan(r, mood = 'grey') {
  const s = r.pick.s, plan = { ...actorPlan(r.beat), mood, lens: LENSES.reduce((a, b) => (Math.abs(b - s.lens) < Math.abs(a - s.lens) ? b : a)) };
  const round = v => v.map(x => Math.round(x * 1000) / 1000);
  plan.keys = Array.from({ length: 17 }, (_, i) => { const u = i * 6, c = solve(s, plan, unsmooth(u / 96)); return [u, round(c.pos), round(c.aim)]; });
  return plan;
}
