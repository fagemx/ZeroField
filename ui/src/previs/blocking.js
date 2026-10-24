// The "drag" layer of the 3D Stage (SPEC_15): put the dummies and camera keys where you want them on the overhead plan, retime
// camera keys and acting beats on a track. Pure functions on plans, so the rules (snap, stay on the stage, never overlap a
// neighbouring beat) are tested in node; PrevisStage only turns pointer movement into the numbers these take.
import { DOME, cameraKeys, framesOf, motionBeats, walkinUse } from './plan.js';

export const SNAP = 0.1;       // metres: a dragged mark or key lands on this grid
export const MIN_BEAT = 4;     // frames: a beat stays at least this long
export const CLOCK = 96;       // camera keys are written on a 0..96 beat clock, whatever the shot's length
const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
const r3 = value => Math.round(value * 1000) / 1000;
export const snapMetres = value => r3(Math.round(value / SNAP) * SNAP);

// Keep a stage point inside the dome's glass; a drag that goes past it stops at the wall.
export function onStage([x, z], margin = 0.3) {
  const dx = x - DOME.x, dz = z - DOME.z, distance = Math.hypot(dx, dz), limit = DOME.radius - margin;
  return distance <= limit ? [x, z] : [DOME.x + dx * limit / distance, DOME.z + dz * limit / distance];
}
export const placeOnStage = (point, {snap = true} = {}) => onStage(point.map(value => snap ? snapMetres(value) : r3(value))).map(r3);

// ---------- Dummies: the actor and the rest of the cast, each standing on a mark [x, z] ----------
export const dummiesOf = plan => [{id: 'actor', mark: plan.mark || [0, 0]}, ...(plan.cast || []).map((member, index) => ({id: 'cast:' + index, mark: member.mark || [0, 0]}))];
// The actor's skills name places on the stage (where a walk starts and ends, where he stands), so dragging the actor carries them
// along: the choreography keeps its shape and still ends on the mark. Anchors in the scene (a grip on the console) stay where they are.
const SPOTS = ['from', 'to', 'at'];
const isSpot = value => Array.isArray(value) && value.length === 2 && value.every(Number.isFinite);
function carry(use, [dx, dz]) {
  return use.map(step => {
    const args = step.args, moved = args && SPOTS.filter(name => isSpot(args[name]));
    return moved?.length ? {...step, args: {...args, ...Object.fromEntries(moved.map(name => [name, [r3(args[name][0] + dx), r3(args[name][1] + dz)]]))}} : step;
  });
}
export function moveDummy(plan, id, to, options) {
  const mark = placeOnStage(to, options);
  if (id === 'actor') {
    const from = plan.mark || [0, 0], next = {...plan, mark};
    return plan.use?.length ? {...next, use: carry(plan.use, [mark[0] - from[0], mark[1] - from[1]])} : next;
  }
  const index = id.startsWith('cast:') ? Number(id.slice(5)) : -1;
  return plan.cast?.[index] ? {...plan, cast: plan.cast.map((member, at) => at === index ? {...member, mark} : member)} : plan;
}

// ---------- Camera keys: a path the director frames by dragging its keys ----------
export const keyHandles = plan => cameraKeys(plan).map(([beat, position, aim], index) => ({index, beat, position, aim}));
const framed = plan => cameraKeys(plan).map(([beat, position, aim]) => [beat, [...position], [...aim]]);
// Drag a key across the plan: x and z follow the pointer, the height and the aim stay. A preset move becomes a framed path.
export function moveCameraKey(plan, index, to, options) {
  const keys = framed(plan);
  if (!keys[index]) return plan;
  const [x, z] = placeOnStage(to, options);
  keys[index][1][0] = x; keys[index][1][2] = z;
  return {...plan, keys};
}
// Retime one key on the beat clock, between its neighbours (the first and last key set when the move starts and stops).
export function retimeCameraKey(plan, index, beat) {
  const keys = framed(plan);
  if (!keys[index] || !Number.isFinite(beat)) return plan;
  keys[index][0] = r3(clamp(beat, index === 0 ? 0 : keys[index - 1][0] + 1, index === keys.length - 1 ? CLOCK : keys[index + 1][0] - 1));
  return {...plan, keys};
}
export const beatToFrame = (plan, beat) => beat * (framesOf(plan) - 1) / CLOCK;
export const frameToBeat = (plan, frame) => frame * CLOCK / (framesOf(plan) - 1);
// When the camera starts and stops moving, in frames: the first and last key.
export function cameraRange(plan) {
  const keys = cameraKeys(plan);
  return {start: beatToFrame(plan, keys[0][0]), end: beatToFrame(plan, keys[keys.length - 1][0])};
}
// Move the start and stop of the camera move; the keys between keep their place within it.
export function setCameraRange(plan, {start, end}) {
  const keys = framed(plan), from = keys[0][0], to = keys[keys.length - 1][0];
  const b0 = clamp(frameToBeat(plan, start), 0, CLOCK - 1), b1 = clamp(frameToBeat(plan, end), b0 + 1, CLOCK);
  if (![b0, b1].every(Number.isFinite) || to - from <= 0) return plan;
  return {...plan, keys: keys.map(([beat, position, aim]) => [r3(b0 + (beat - from) * (b1 - b0) / (to - from)), position, aim])};
}

// ---------- Acting beats: the skills in plan.use laid out on the shot's frames ----------
// Walk in plays as one walkTo skill, so it has a beat too; editing it writes that skill out as the plan's own use.
const useOf = plan => plan.use?.length ? plan.use : !plan.acts?.length && plan.action === 'walkin' ? walkinUse(plan) : null;
export function actingBeats(plan) {
  const use = useOf(plan);
  return use ? motionBeats({...plan, use}).filter(beat => beat.frames > 0).map(beat => ({...beat, derived: !plan.use?.length})) : [];
}
// Edits pin every step's start first, so changing one beat never moves another (the skills still read the same).
function pinned(plan) {
  const use = useOf(plan), beats = motionBeats({...plan, use});
  return {use: use.map((step, at) => ({...step, f0: beats[at].start})), beats};
}
const neighbours = (beats, index) => ({
  prev: beats.slice(0, index).reverse().find(beat => beat.frames > 0), next: beats.slice(index + 1).find(beat => beat.frames > 0)});
// Drag a beat's right edge: how long it runs. Stops at the next beat, the end of the shot and a minimum length.
export function resizeBeat(plan, index, end) {
  if (!useOf(plan) || !Number.isFinite(end)) return plan;
  const {use, beats} = pinned(plan), beat = beats[index], step = use[index];
  if (!beat?.resizable) return plan;
  const last = framesOf(plan) - 1, a = step.args || {}, grip = (a.reach ?? 12) + (a.release ?? 12), {next} = neighbours(beats, index);
  const limit = Math.min(last, next ? next.start : last), floor = Math.min(beat.start + (beat.resizable === 'hold' ? grip : MIN_BEAT), limit);
  const to = clamp(Math.round(end), floor, limit);
  const edited = beat.resizable === 'frames' ? {...step, frames: to - beat.start}
    : beat.resizable === 'until' ? {...step, args: {...a, until: to}} : {...step, args: {...a, hold: to - beat.start - grip}};
  return {...plan, use: use.map((item, at) => at === index ? edited : item)};
}
// Drag a whole beat: where it starts, between the beat before it and the one after, its length kept.
export function moveBeat(plan, index, start) {
  if (!useOf(plan) || !Number.isFinite(start)) return plan;
  const {use, beats} = pinned(plan), beat = beats[index], step = use[index];
  if (!beat || beat.frames <= 0) return plan;
  const last = framesOf(plan) - 1, {prev, next} = neighbours(beats, index), low = prev ? prev.end : 0, high = (next ? next.start : last) - beat.frames;
  if (high < low) return plan;
  const at = clamp(Math.round(start), low, high), shift = at - beat.start, a = step.args;
  const edited = {...step, f0: at, ...(a?.until != null ? {args: {...a, until: a.until + shift}} : {})};
  return {...plan, use: use.map((item, i) => i === index ? edited : item)};
}
