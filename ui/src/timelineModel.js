// SPEC_15 Timeline: the episode as one row of clips in slate order. These are the editing rules, kept apart from the DOM so they
// can be tested. A clip is a take (or the 3D previs standing in for it, or only a planned length) plus a trim: where in the file
// it starts and stops. The film is a plain concatenation, so there are no gaps: shortening a clip always moves what follows
// (ripple), or, with ripple off, gives the time to the neighbour across the cut (roll) so the film keeps its length.
export const FPS = 24;
export const FRAME = 1 / FPS;
export const DEFAULT_SECONDS = 4;  // the previs plan's own default when a shot has no plan

const finite = value => typeof value === 'number' && Number.isFinite(value);
const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
export const toFrames = seconds => Math.round(seconds * FPS + 1e-9);
export const snapSeconds = seconds => toFrames(seconds) / FPS;
const floorSeconds = seconds => Math.floor(seconds * FPS + 1e-9) / FPS;
const keep = seconds => Math.round(seconds * 1e6) / 1e6;  // what is stored: six decimals, still a whole number of frames

// "00:08.0": minutes, seconds and tenths, the ruler and playhead label.
export function clock(seconds) {
  const tenths = Math.max(0, Math.round((finite(seconds) ? seconds : 0) * 10));
  return `${String(Math.floor(tenths / 600)).padStart(2, '0')}:${String(Math.floor(tenths / 10) % 60).padStart(2, '0')}.${tenths % 10}`;
}
// "−10 f" or "+0.5 s": a change in frames when it is under two seconds, else seconds.
export function signed(seconds) {
  const frames = toFrames(seconds);
  if (frames === 0) return '0 f';
  const sign = frames < 0 ? '−' : '+';
  return Math.abs(seconds) < 2 ? `${sign}${Math.abs(frames)} f` : `${sign}${Math.abs(seconds).toFixed(1)} s`;
}

export const planSeconds = shot => finite(shot?.previsPlan?.seconds) && shot.previsPlan.seconds > 0 ? shot.previsPlan.seconds : DEFAULT_SECONDS;

// Where a shot's picture comes from: its take, else the grey 3D previs standing in for it, else only a planned length.
export const clipKind = shot => shot.selectedVideoUrl ? 'take' : shot.previsVideoUrl ? 'previs' : 'plan';

// shots: the cinema slate in cut order. measured: {url: seconds} read from the files. trims: {rowId: {in, out|null}} drafts that
// override the saved shot.trim (a drag in progress). Only a take whose length is known can be trimmed; the film export never
// trims previs fill-in, so a clip that is not a take always plays whole.
export function buildClips(shots, {measured = {}, trims = {}} = {}) {
  let start = 0;
  return shots.map((shot, index) => {
    const kind = clipKind(shot), url = shot.selectedVideoUrl || shot.previsVideoUrl || null;
    const saved = Object.hasOwn(trims, shot.rowId) ? trims[shot.rowId] : shot.trim;
    const sourceKnown = url !== null && finite(measured[url]) && measured[url] > 0;
    const reach = Math.max(planSeconds(shot), finite(saved?.out) ? saved.out : 0);
    const source = Math.max(FRAME, floorSeconds(sourceKnown ? measured[url] : reach));
    const take = kind === 'take';
    const inPoint = take ? clamp(snapSeconds(finite(saved?.in) ? saved.in : 0), 0, source - FRAME) : 0;
    const outPoint = take ? clamp(snapSeconds(finite(saved?.out) ? saved.out : source), inPoint + FRAME, source) : source;
    const length = outPoint - inPoint;
    const clip = {id: shot.rowId, rowId: shot.rowId, shotId: shot.shotId, index, label: String(shot.shotIndex), title: String(shot.description || ''), sceneId: shot.sceneId || null, kind, url,
      still: shot.selectedImageUrl || null, source, sourceKnown, trimmable: take && sourceKnown, in: inPoint, out: outPoint, length, start, end: start + length,
      trimmed: take && (inPoint > 1e-6 || outPoint < source - 1e-6), dialogue: Array.isArray(shot.dialogue) ? shot.dialogue : []};
    start += length;
    return clip;
  });
}

export const totalSeconds = clips => clips.length ? clips[clips.length - 1].end : 0;

// The clip under a time on the timeline: the last one starting at or before it. After the end it is the last clip.
export function clipAt(clips, time) {
  if (!clips.length) return null;
  for (let at = clips.length - 1; at >= 0; at -= 1) if (time >= clips[at].start - 1e-9) return clips[at];
  return clips[0];
}
// Time in the clip's file for a time on the timeline.
export const fileTime = (clip, time) => clamp(clip.in + (time - clip.start), clip.in, clip.out);

// The saved shape of a trim: out is null when it runs to the end of the take, so a later longer take is not cut short.
function trimOf(clip, inPoint, outPoint) {
  return {in: keep(inPoint), out: outPoint >= clip.source - 1e-6 ? null : keep(outPoint)};
}

// Drag one edge of a clip. delta is the edge's move on the timeline in seconds (positive is later): an out edge dragged later
// makes the clip longer, an in edge dragged later makes it shorter. Ripple on: nothing else changes, later clips shift.
// Ripple off: the neighbour across the cut takes the same move on its facing edge (a roll), so the cut moves and the film does
// not. Without a trimmable neighbour a roll has nothing to give or take and behaves as a ripple. Returns the move actually
// allowed (clamped to the files and to one frame minimum) and the new trims, or null if this clip cannot be trimmed.
export function dragEdge(clips, index, edge, delta, {ripple = true} = {}) {
  const clip = clips[index];
  if (!clip?.trimmable || !finite(delta) || (edge !== 'in' && edge !== 'out')) return null;
  const peer = ripple ? null : (edge === 'out' ? clips[index + 1] : clips[index - 1]);
  const rolled = peer?.trimmable ? peer : null;
  let low, high;
  if (edge === 'out') {low = clip.in + FRAME - clip.out; high = clip.source - clip.out;}
  else {low = -clip.in; high = clip.out - FRAME - clip.in;}
  if (rolled) {
    if (edge === 'out') {low = Math.max(low, -rolled.in); high = Math.min(high, rolled.out - FRAME - rolled.in);}
    else {low = Math.max(low, rolled.in + FRAME - rolled.out); high = Math.min(high, rolled.source - rolled.out);}
  }
  const applied = snapSeconds(clamp(delta, low - 1e-9, high + 1e-9));
  const trims = {};
  if (edge === 'out') {
    trims[clip.rowId] = trimOf(clip, clip.in, clip.out + applied);
    if (rolled) trims[rolled.rowId] = trimOf(rolled, rolled.in + applied, rolled.out);
  } else {
    trims[clip.rowId] = trimOf(clip, clip.in + applied, clip.out);
    if (rolled) trims[rolled.rowId] = trimOf(rolled, rolled.in, rolled.out + applied);
  }
  return {delta: applied, rolled: rolled ? rolled.rowId : null, trims};
}
// Slide both edges together: the clip keeps its length and shows a different stretch of the take, so nothing else moves.
export function slip(clips, index, delta) {
  const clip = clips[index];
  if (!clip?.trimmable || !finite(delta)) return null;
  const applied = snapSeconds(clamp(delta, -clip.in - 1e-9, clip.source - clip.out + 1e-9));
  return {delta: applied, rolled: null, trims: {[clip.rowId]: trimOf(clip, clip.in + applied, clip.out + applied)}};
}
// The same, to an absolute point in the clip's file (the timecode fields and the range slider).
export const setPoint = (clips, index, edge, target, options) => finite(target) && clips[index]
  ? dragEdge(clips, index, edge, target - clips[index][edge], options) : null;
// The same, to a length in seconds, moving the out edge.
export const setLength = (clips, index, seconds, options) => finite(seconds) && clips[index]
  ? dragEdge(clips, index, 'out', clips[index].in + seconds - clips[index].out, options) : null;
// Trims that actually differ from what the clips already have; nothing to save for a no-op.
export const changedTrims = (clips, trims) => Object.fromEntries(Object.entries(trims).filter(([rowId, trim]) => {
  const clip = clips.find(item => item.rowId === rowId);
  return clip && (Math.abs(clip.in - trim.in) > 1e-6 || Math.abs(clip.out - (trim.out ?? clip.source)) > 1e-6);
}));
// Cleared: back to the whole take.
export const wholeTake = () => ({in: 0, out: null});

// The nearest target within a tolerance, for snapping a drag to the playhead and to other cuts.
export function nearest(targets, value, tolerance) {
  let best = null;
  for (const target of targets) if (Math.abs(target - value) <= tolerance && (best === null || Math.abs(target - value) < Math.abs(best - value))) best = target;
  return best;
}
export const cutPoints = clips => clips.length ? [0, ...clips.map(clip => clip.end)] : [];

// Rhythm: each clip's length against the episode's average. A clip that runs well over it gets a hint of how far to take it down.
export function rhythm(clips) {
  const total = totalSeconds(clips), mean = clips.length ? total / clips.length : 0;
  const longest = Math.max(0, ...clips.map(clip => clip.length));
  return {total, mean, longest, items: clips.map(clip => {
    const over = clip.length - mean;
    const long = clips.length > 2 && clip.length >= mean * 1.2 && over >= 0.5;
    return {id: clip.id, length: clip.length, ratio: longest ? clip.length / longest : 0, long, trimBy: long ? -snapSeconds(over) : 0};
  })};
}

// The "say" layer: a typed instruction for the selected clip, understood without a model. Returns {edge, delta} (an edge moved
// by that many seconds on the timeline) or {edge: 'out', length} (an absolute length), or null if it is not understood.
const ZH_DIGITS = {零: 0, 〇: 0, 一: 1, 二: 2, 兩: 2, 两: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9};
function zhNumber(text) {
  if (text === '半') return 0.5;
  const [tens, ones] = text.includes('十') ? text.split('十') : [null, text];
  const digit = part => part === '' ? 0 : part.length === 1 && part in ZH_DIGITS ? ZH_DIGITS[part] : NaN;
  const value = text.includes('十') ? (tens === '' ? 1 : digit(tens)) * 10 + digit(ones) : digit(ones);
  return Number.isFinite(value) ? value : NaN;
}
export function parseTrimCommand(text) {
  const source = String(text || '').trim().replace(/[−–—]/g, '-');
  const amount = /([+-]?)\s*(\d+(?:\.\d+)?|[零〇一二兩两三四五六七八九十半]+)\s*(格|幀|帧|frames?|fr|f|秒|seconds?|secs?|s)(?![a-z])/i.exec(source);
  if (!amount) return null;
  const number = /^\d/.test(amount[2]) ? Number(amount[2]) : zhNumber(amount[2]);
  if (!Number.isFinite(number) || number <= 0) return null;
  const seconds = snapSeconds(/^(?:格|幀|帧|f)/i.test(amount[3]) ? number / FPS : number);
  if (seconds <= 0) return null;
  const rest = source.slice(0, amount.index) + ' ' + source.slice(amount.index + amount[0].length);
  const edge = /入點|入点|開頭|开头|頭|头|\bin\b|start|head/i.test(rest) ? 'in' : 'out';
  const shorten = /縮短|缩短|變短|变短|短|剪掉|shorten|trim|cut|reduce/i.test(rest), extend = /加長|加长|延長|延长|拉長|拉长|變長|变长|extend|lengthen|longer|add/i.test(rest);
  const earlier = /早|提前|前移|往前|earlier|before|back|sooner|minus/i.test(rest), later = /晚|延後|延后|往後|往后|later|after|forward|plus/i.test(rest);
  if (!shorten && !extend && !earlier && !later && !amount[1]) return /長度|长度|\blength\b|duration/i.test(rest) ? {edge: 'out', length: seconds} : null;
  let sign;
  if (shorten !== extend) sign = (shorten ? -1 : 1) * (edge === 'in' ? -1 : 1);  // shortening moves an out edge earlier but an in edge later
  else if (amount[1]) sign = amount[1] === '-' ? -1 : 1;
  else sign = earlier !== later ? (earlier ? -1 : 1) : 0;
  return sign ? {edge, delta: sign * seconds} : null;
}
