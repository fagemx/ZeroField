// SPEC_20 R27 (decision 11): structured 3D operations and their deterministic solve into a plan (plan.js format).
// The crew never writes code for the 3D Stage. It sends operations in film language and this module turns them into
// the plan the stage plays: who stands where (blocking.js moveDummy, so a walk's spots travel with the actor), which way
// each person faces (plan.facing / plan.turn, cast[i].turn), the camera path (plan.keys, lens, move) and when an acting
// beat lands (blocking.js moveBeat). The same base plan and operations always give the same plan: nothing here reads a
// clock, a random number or the page. The server runs this file in a headless browser (project_assistant/
// headless_previs.py, the previs-solver page); without a browser the reviewer's 3D Stage runs it. Python validates the
// operations with the same rules first (project_assistant/previs_ops.py; tests check the two agree).
//
// Operations (SPEC_20 §4.6). Stage coordinates are station-local metres: +z toward the console and the glass, -z toward
// the room (the camera side), the actor's mark at [0, 0]. Headings: 0 faces +z.
//   place  {cast, relativeTo, offset: [x, z], facing}   cast: a @CAST code from the cast sheet. relativeTo: a set target
//          (STAGE_TARGETS of the plan's set, "window" for window_glass), "mark" (the stage origin) or a cast code already
//          on set or placed by an earlier op. offset: metres added to that point's floor position. facing: a set target,
//          "mark", a cast code on set, "camera" (toward the camera at mid-shot) or "room" (the camera side, -z).
//          A code already on set moves; a new code becomes the plan's own actor when the actor has no code, else joins plan.cast.
//   camera {size, angle, lens, move, from?, to?}       size SIZES, angle ANGLES, lens LENSES, move MOVES. The solver frames
//          everyone on set from the side the actor faces and writes the move's keys K1..Kn (MOVE_KEYS: static 1, orbit 3,
//          the others 2); from/to (default the first and last key) pick the span the shot uses, re-timed over the shot.
//   retime {beat, at}                                   beat: the 3D Stage's acting beat, counted from 1 (actingBeats:
//          the skills of plan.use, or the Walk in action's walk). at: where it now starts, a fraction 0..1 of the shot.
// Order of the solve: places in list order; facings ("camera" first turns to the camera side, which also sets which way a
// walk goes); the camera, framed on where everyone ends the shot; "camera" facings toward the lens at mid-shot; retimes.
import { BUILD, FPS, HEIGHT, LENSES, MOVES, PARALLAX_DEFAULTS, SCENE_ANCHORS, SCENE_BOXES, WIDTH, framesOf, insideDome,
  motionPlan, parallaxLayers, sampleActor, sampleActs, sampleCamera, verticalFov } from './plan.js';
import { actingBeats, moveBeat, moveDummy } from './blocking.js';
import { addCastMember, codesOnSet, resolveShotPlan } from './storyPlan.js';

export const OPS_VERSION = 1;  // bump when the same operations would solve to a different plan
export const OP_TYPES = ['place', 'camera', 'retime'];
export const SIZES = ['wide', 'full', 'medium', 'close', 'extreme_close'];
export const ANGLES = ['low', 'eye', 'high', 'overhead'];
export const FACE_LENS = ['camera', 'room'];
export const MAX_OPS = 32;
export const MAX_OFFSET = 8;  // metres either way
export const MOVE_KEYS = { static: 1, pushin: 2, pullout: 2, crane: 2, track: 2, orbit: 3 };
// What a place op may name on each set: the observatory's anchors (plan.js SCENE_ANCHORS) and boxes (SCENE_BOXES), the
// parallax set's three card depths (PARALLAX_DEFAULTS roles), nothing on the empty stage. "mark" and cast codes always.
export const STAGE_TARGETS = { observatory: ['console', 'plinth', 'dial', 'recorder', 'console_edge', 'window_glass'], parallax: ['far', 'mid', 'near'], empty: [] };
export const TARGET_ALIASES = { window: 'window_glass' };
export const OP_FIELDS = { place: [['op', 'cast', 'relativeTo', 'offset', 'facing'], []], camera: [['op', 'size', 'angle', 'lens', 'move'], ['from', 'to']], retime: [['op', 'beat', 'at'], []] };
const CAST_CODE = /^@CAST-\d{1,4}$/, CAMERA_KEY = /^K(\d{1,2})$/;
// Camera framing per size for an adult (figure.js BUILD scales it): the frame height at the subject in metres and the
// height the lens aims at (face for the close sizes, chest for a medium, the whole body for full and wide).
const FRAMING = { extreme_close: [0.34, 1.74], close: [0.62, 1.66], medium: [1.2, 1.42], full: [2.3, 0.98], wide: [4.6, 1.0] };
const ELEVATION = { low: -16, eye: 0, high: 24, overhead: 62 };  // degrees the camera sits above (or below) the aim line
const PUSH = 1.9;  // a push-in starts (a pull-out ends) this many times further out than the framing distance
const ORBIT = 50;  // degrees either side of the front an orbit swings

export class OpsError extends Error {
  constructor(path, message) { super(`${path} ${message}`); this.name = 'OpsError'; this.code = 'PREVIS_OPS_INVALID'; this.path = path; }
}

const r3 = v => Math.round(v * 1000) / 1000 || 0;  // millimetres; "|| 0" drops a negative zero
const deg = a => Math.round(a * 1800 / Math.PI) / 10 || 0;  // tenths of a degree
const wrap = a => Math.atan2(Math.sin(a), Math.cos(a));
const isObj = v => v && typeof v === 'object' && !Array.isArray(v);
const finite = v => typeof v === 'number' && Number.isFinite(v);
const clone = v => JSON.parse(JSON.stringify(v));
const midpoint = v => (finite(v) ? v : Array.isArray(v?.range) ? (v.range[0] + v.range[1]) / 2 : 0);
const spot = mark => (Array.isArray(mark) ? [midpoint(mark[0]), midpoint(mark[1])] : [0, 0]);
export const targetName = name => TARGET_ALIASES[name] || name;
const fmt = ([x, z]) => `[${r3(x)}, ${r3(z)}]`;

// Everyone on set: the plan's own actor, then the cast, with where they stand and their build.
const people = plan => [{ who: 'actor', code: plan.code || null, mark: spot(plan.mark), build: plan.figure?.build },
  ...(plan.cast || []).map((m, i) => ({ who: 'cast:' + i, code: m.code || null, mark: spot(m.mark), build: m.figure?.build }))];
const whoIs = (plan, code) => people(plan).find(p => p.code === code)?.who || null;
const markOf = (plan, who) => people(plan).find(p => p.who === who).mark;

// A set target's floor point [x, z]: an anchor's own spot, a box's front edge (the side toward the room), a card's depth.
export function targetPoint(plan, name) {
  const n = targetName(name), set = plan.set || 'observatory';
  if (n === 'mark') return [0, 0];
  if (!(STAGE_TARGETS[set] || []).includes(n)) return null;
  if (set === 'parallax') {
    const card = parallaxLayers({ ...plan, set: 'parallax' }).find(l => (l.role || l.id) === n) || PARALLAX_DEFAULTS.find(d => d.role === n);
    return [card.x ?? 0, card.z];
  }
  if (SCENE_ANCHORS[n]) return [SCENE_ANCHORS[n].pos[0], SCENE_ANCHORS[n].pos[2]];
  const box = SCENE_BOXES[n];
  return [(box.min[0] + box.max[0]) / 2, box.min[2]];
}
const pointOf = (plan, name) => (CAST_CODE.test(name) ? markOf(plan, whoIs(plan, name)) : targetPoint(plan, name));
// A mark inside one of the observatory's solid set pieces (the console, standing on the plinth is fine).
const insideSetPiece = (plan, [x, z]) => ((plan.set || 'observatory') === 'observatory' ? ['console'] : [])
  .find(id => { const b = SCENE_BOXES[id]; return x > b.min[0] && x < b.max[0] && z > b.min[2] && z < b.max[2]; }) || null;
const keyIndex = name => Number(CAMERA_KEY.exec(name)?.[1]) - 1;

// Throw OpsError unless ops are valid against the base plan (and castCodes, the production's cast sheet, when given).
export function validateOps(base, ops, { castCodes = null } = {}) {
  if (!Array.isArray(ops) || !ops.length || ops.length > MAX_OPS) throw new OpsError('ops', `must list 1 to ${MAX_OPS} operations.`);
  const set = base.set || 'observatory', targets = STAGE_TARGETS[set] || [], onSet = new Set(codesOnSet(base)), placed = new Set();
  const sheet = castCodes ? new Set(castCodes) : null, beats = actingBeats(base).length, retimed = new Set(), facings = [];
  let cameras = 0;
  ops.forEach((op, i) => {
    const path = `ops[${i}]`;
    if (!isObj(op) || !OP_TYPES.includes(op.op)) throw new OpsError(path, 'must be an operation: place, camera or retime.');
    const [required, optional] = OP_FIELDS[op.op], unknown = Object.keys(op).filter(k => !required.includes(k) && !optional.includes(k));
    if (unknown.length) throw new OpsError(path, `has unknown fields: ${unknown.sort().join(', ')}.`);
    const missing = required.filter(k => op[k] === undefined || op[k] === null);
    if (missing.length) throw new OpsError(path, `needs ${missing.join(', ')}.`);
    if (op.op === 'place') {
      if (typeof op.cast !== 'string' || !CAST_CODE.test(op.cast)) throw new OpsError(path + '.cast', 'must be a cast code such as @CAST-01.');
      if (sheet && !sheet.has(op.cast)) throw new OpsError(path + '.cast', `names ${op.cast}, which is not on the cast sheet.`);
      if (placed.has(op.cast)) throw new OpsError(path + '.cast', `places ${op.cast} a second time; place each person once.`);
      const anchor = typeof op.relativeTo === 'string' ? targetName(op.relativeTo) : null;
      if (!anchor || anchor === op.cast || !(targets.includes(anchor) || anchor === 'mark' || (CAST_CODE.test(anchor) && (onSet.has(anchor) || placed.has(anchor))))) {
        throw new OpsError(path + '.relativeTo', `must be a target of the ${set} set (${[...targets, 'mark'].join(', ')}) or someone already on set.`);
      }
      if (!Array.isArray(op.offset) || op.offset.length !== 2 || !op.offset.every(v => finite(v) && Math.abs(v) <= MAX_OFFSET)) {
        throw new OpsError(path + '.offset', `must be [x, z] in metres, each within ±${MAX_OFFSET}.`);
      }
      if (typeof op.facing !== 'string') throw new OpsError(path + '.facing', 'must be a target, a cast code, camera or room.');
      placed.add(op.cast); facings.push([path + '.facing', op.cast, targetName(op.facing)]);
    } else if (op.op === 'camera') {
      if (++cameras > 1) throw new OpsError(path, 'is a second camera operation; a shot has one camera.');
      if (!SIZES.includes(op.size)) throw new OpsError(path + '.size', `must be one of ${SIZES.join(', ')}.`);
      if (!ANGLES.includes(op.angle)) throw new OpsError(path + '.angle', `must be one of ${ANGLES.join(', ')}.`);
      if (!LENSES.includes(op.lens)) throw new OpsError(path + '.lens', `must be one of ${LENSES.join(', ')} (mm).`);
      if (!MOVES.includes(op.move)) throw new OpsError(path + '.move', `must be one of ${MOVES.join(', ')}.`);
      const count = MOVE_KEYS[op.move], from = op.from == null ? 0 : keyIndex(op.from), to = op.to == null ? (op.move === 'static' ? from : count - 1) : keyIndex(op.to);
      for (const [field, index] of [['from', from], ['to', to]]) {
        if (op[field] != null && !(typeof op[field] === 'string' && Number.isInteger(index) && index >= 0 && index < count)) {
          throw new OpsError(`${path}.${field}`, `must be a camera key of a ${op.move} move: ${Array.from({ length: count }, (_, k) => 'K' + (k + 1)).join(', ')}.`);
        }
      }
      if (op.move === 'static' ? to !== from : to <= from) {
        throw new OpsError(path + '.to', op.move === 'static' ? 'must be the key a static camera holds (the same as from).' : 'must be a later key than from.');
      }
    } else {
      if (!Number.isInteger(op.beat) || op.beat < 1 || op.beat > beats) {
        throw new OpsError(path + '.beat', beats ? `must be an acting beat from 1 to ${beats}.` : 'cannot be retimed: this plan has no acting beats.');
      }
      if (retimed.has(op.beat)) throw new OpsError(path + '.beat', `retimes beat ${op.beat} a second time.`);
      if (!finite(op.at) || op.at < 0 || op.at > 1) throw new OpsError(path + '.at', 'must be a fraction of the shot from 0 to 1.');
      retimed.add(op.beat);
    }
  });
  for (const [path, self, name] of facings) {
    const ok = name !== self && (targets.includes(name) || name === 'mark' || FACE_LENS.includes(name) || (CAST_CODE.test(name) && (onSet.has(name) || placed.has(name))));
    if (!ok) throw new OpsError(path, `must be a target of the ${set} set (${[...targets, 'mark'].join(', ')}), camera, room or someone else on set.`);
  }
  return ops;
}

// Where someone stands when the shot ends: the mark plus how far the acting carries them (a walk, skills, performance keys),
// as scene.js places them (mark + [side, -back]). A walk in facing the room ends 2.2 m nearer the camera than its mark.
function endSpot(plan, who) {
  const p = motionPlan(plan), [x, z] = markOf(p, who);
  const acted = who === 'actor' ? sampleActor(p, framesOf(p) - 1) : sampleActs(p.cast[Number(who.slice(5))].acts || [], 1);
  return [x + (acted.side || 0), z - (acted.back || 0)];
}

// The camera move framing everyone on set (where they end the shot) from the front side, before key selection:
// [[position, aim], ...].
function framedPath(plan, op, front) {
  const crowd = people(plan).map(p => ({ ...p, mark: endSpot(plan, p.who) })), k = crowd.reduce((sum, p) => sum + (BUILD[p.build] || 1), 0) / crowd.length;
  const c = [0, 1].map(i => crowd.reduce((sum, p) => sum + p.mark[i], 0) / crowd.length);
  let spread = 0;
  for (const a of crowd) for (const b of crowd) spread = Math.max(spread, Math.hypot(a.mark[0] - b.mark[0], a.mark[1] - b.mark[1]));
  const [frame, aimAt] = FRAMING[op.size], wide = op.size === 'wide', aimY = wide ? aimAt : aimAt * k, height = wide ? frame : frame * k;
  const v = verticalFov(op.lens) * Math.PI / 180, h = 2 * Math.atan(Math.tan(v / 2) * WIDTH / HEIGHT);
  const d = Math.max(height / 2 / Math.tan(v / 2), (spread + 0.7) / 2 / Math.tan(h / 2)), e = ELEVATION[op.angle] * Math.PI / 180;
  const right = [Math.cos(front), -Math.sin(front)], aim = (shift = 0) => [c[0] + right[0] * shift, aimY, c[1] + right[1] * shift];
  const at = (dist, { swing = 0, y = null, shift = 0 } = {}) => {
    const a = front + swing * Math.PI / 180, flat = dist * Math.cos(e);
    return [c[0] + Math.sin(a) * flat + right[0] * shift, y ?? Math.max(0.3, aimY + dist * Math.sin(e)), c[1] + Math.cos(a) * flat + right[1] * shift];
  };
  const lateral = Math.max(0.8, 0.45 * d), rise = at(d)[1];
  return {
    static: () => [[at(d), aim()]],
    pushin: () => [[at(d * PUSH), aim()], [at(d), aim()]],
    pullout: () => [[at(d), aim()], [at(d * PUSH), aim()]],
    orbit: () => [[at(d, { swing: -ORBIT }), aim()], [at(d), aim()], [at(d, { swing: ORBIT }), aim()]],
    track: () => [[at(d, { shift: -lateral }), aim(-0.4 * lateral)], [at(d, { shift: lateral }), aim(0.4 * lateral)]],
    crane: () => [[at(d), aim()], [at(d * 1.1, { y: rise + 1.5 }), aim()]],
  }[op.move]();
}

function withCamera(plan, op, front, warnings) {
  const path = framedPath(plan, op, front).map(([position, aim], index) => {
    const kept = insideDome(aim, position.map((value, i) => value - aim[i]));
    if (Math.hypot(...kept.map((value, i) => value - position[i])) > 0.001) warnings.push(`Camera key K${index + 1} was pulled in toward the subject to stay inside the stage.`);
    return [kept.map(r3), aim.map(r3)];
  });
  const from = op.from == null ? 0 : keyIndex(op.from), to = op.to == null ? (op.move === 'static' ? from : path.length - 1) : keyIndex(op.to);
  const span = op.move === 'static' ? [path[from], path[from]] : path.slice(from, to + 1);
  const keys = span.map(([position, aim], i) => [r3(i * 96 / (span.length - 1)), position, aim]);
  const { easing, ...rest } = plan;  // a new move plays with the default ease
  return { ...rest, lens: op.lens, move: op.move, keys };
}

const headingTo = (from, to) => Math.atan2(to[0] - from[0], to[1] - from[1]);
// The heading a person ends the shot on, from the plan alone: the actor's canned action ends on its facing plus turn.
const headingOf = (plan, who) => (who === 'actor' ? (plan.facing === 'room' ? Math.PI : 0) : 0) + midpoint((who === 'actor' ? plan : plan.cast[Number(who.slice(5))]).turn ?? 0) * Math.PI / 180;
// Turn someone to a heading. The actor with a canned action faces the console or the room (whichever side the heading is
// on) and turns the rest; an actor with skills or performance keys keeps his facing (they are written for it) and turns.
function turnTo(plan, who, heading) {
  if (who !== 'actor') {
    const index = Number(who.slice(5));
    return { ...plan, cast: plan.cast.map((m, at) => (at === index ? { ...m, turn: deg(wrap(heading)) } : m)) };
  }
  const canned = !plan.use?.length && !plan.acts?.length, room = canned ? Math.abs(wrap(heading)) > Math.PI / 2 + 1e-9 : plan.facing === 'room';
  return { ...plan, facing: room ? 'room' : 'console', turn: deg(wrap(heading - (room ? Math.PI : 0))) };
}

// Apply validated operations to a base plan. Returns {plan, warnings}; warnings say what the solver changed or noticed.
export function solveOps(base, ops, { castCodes = null } = {}) {
  validateOps(base, ops, { castCodes });
  let plan = clone(base);
  const warnings = [], places = ops.filter(op => op.op === 'place'), camera = ops.find(op => op.op === 'camera');
  for (const op of places) {
    const at = pointOf(plan, targetName(op.relativeTo)), want = [at[0] + op.offset[0], at[1] + op.offset[1]];
    let who = whoIs(plan, op.cast);
    if (!who) {
      if (!plan.code) { plan = { ...plan, code: op.cast }; who = 'actor'; }
      else { plan = addCastMember(plan, op.cast); who = 'cast:' + (plan.cast.length - 1); }
    }
    plan = moveDummy(plan, who, want, { snap: false });
    const got = markOf(plan, who), piece = insideSetPiece(plan, got);
    if (Math.hypot(got[0] - want[0], got[1] - want[1]) > 0.001) warnings.push(`${op.cast} was kept on the stage at ${fmt(got)} instead of ${fmt(want)}.`);
    if (piece) warnings.push(`${op.cast} stands inside the ${piece} at ${fmt(got)}.`);
  }
  // Facings from the marks; "camera" first turns to the camera side (-z), which also sets which way a walk goes.
  const toLens = [];
  for (const op of places) {
    const who = whoIs(plan, op.cast), name = targetName(op.facing);
    if (name === 'camera') toLens.push(who);
    plan = turnTo(plan, who, name === 'camera' || name === 'room' ? Math.PI : headingTo(markOf(plan, who), pointOf(plan, name)));
  }
  if (camera) plan = withCamera(plan, camera, headingOf(plan, 'actor'), warnings);
  // Then "camera" faces the lens at mid-shot from where each person ends the shot.
  const lens = sampleCamera(plan, (framesOf(plan) - 1) / 2).position;
  for (const who of toLens) plan = turnTo(plan, who, headingTo(endSpot(plan, who), [lens[0], lens[2]]));
  for (const op of ops.filter(item => item.op === 'retime')) {
    const last = framesOf(plan) - 1, start = Math.round(op.at * last), beat = actingBeats(plan)[op.beat - 1];
    plan = moveBeat(plan, beat.index, start);
    const now = actingBeats(plan)[op.beat - 1].start;
    if (Math.abs(now - start) > 1e-6) warnings.push(`Acting beat ${op.beat} starts at frame ${r3(now)} (${r3(now / FPS)} s), not ${start}: it stays between its neighbours and inside the shot.`);
  }
  return { plan, warnings };
}

// The solver page's request: the stored plan (or null) and the shot's seed, as the 3D Stage resolves a shot (storyPlan.js
// resolveShotPlan: stored plan, else the storyboard seed over what the slate text says), the operations and the cast codes.
//   {stored, shot: {slate: {motion, rig, action}, previsPlan, setAsset: {url} | null}, ops, castCodes}
export function solveRequest({ stored = null, shot = {}, ops, castCodes = null } = {}) {
  const base = resolveShotPlan(shot || {}, { stored: isObj(stored) ? stored : null });
  const { plan, warnings } = solveOps(base, ops, { castCodes: Array.isArray(castCodes) ? castCodes : null });
  return { version: OPS_VERSION, plan, warnings, base: { set: base.set, onSet: codesOnSet(base), actingBeats: actingBeats(base).length } };
}


