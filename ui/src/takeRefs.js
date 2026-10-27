import { normalizeStatus } from './format.js';

// SPEC_19 R15 (package D): a shot quoting another shot's take in its prompt. `@SC01-S02.end` is that shot's cut out point (the last
// frame of its take when it is not trimmed), `@SC01-S02.start` its in point. The server freezes each tag when a generation is sent
// (project_docs/story_take_refs.py); this module only reads the prompt the way the server will, so the editor can draw the tag, show
// which take and second it stands for, and send the use the person chose (takeRefUses). Pure functions: no DOM, no requests.
//
// The rule is the server's, with ASCII meaning (JavaScript's default \w and \b are ASCII, as the server's re.ASCII): a tag starts at
// an @ that does not follow a word character, @, :, # or -, names a shot code of letters and digits joined by hyphens, and ends in
// .start or .end at a word boundary. "接續@SC01-S02.end的動作" is a tag; "x@S02.end", "@S02.ending" are not. A code that starts like an
// asset code (CAST-, SET-, LOC-, PROP-, CHAR-, SCENE-, STYLE-, any case) is never a shot, so @CAST-01.end, @CAST-01:night and @SET-01
// stay asset codes.

export const TAKE_REF = /(?<![\w@:#-])@([A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)\.(start|end)\b/g;
const ASSET_CODE = /^(?:CAST|SET|LOC|PROP|CHAR|SCENE|STYLE)-/i;
export const TAKE_REF_USES = ['first_frame', 'reference'];
export const MAX_TAKE_REFS = 6;

// The takeRefUses key of a tag: "SC01-S02.end" (the code upper-cased, as the server keys it).
export const refKey = (code, edge) => `${String(code ?? '').trim().toUpperCase()}.${edge}`;
const same = (a, b) => String(a ?? '').trim().toLowerCase() === String(b ?? '').trim().toLowerCase();

// Every take reference in the text, in reading order: {start, end, code, edge, key, text}.
export function takeRefTokens(text) {
  const source = String(text ?? ''), found = [];
  for (const match of source.matchAll(TAKE_REF)) {
    if (ASSET_CODE.test(match[1])) continue;
    found.push({start: match.index, end: match.index + match[0].length, code: match[1], edge: match[2], key: refKey(match[1], match[2]), text: match[0]});
  }
  return found;
}

// The shot of this episode a code names: matched against shotIndex without regard to case. {shot} when exactly one does, else
// {shot: null, state: 'unknown' | 'ambiguous'}.
export function shotForCode(code, shots = []) {
  const hits = (Array.isArray(shots) ? shots : []).filter(shot => same(shot?.shotIndex, code));
  return hits.length === 1 ? {shot: hits[0], state: null} : {shot: null, state: hits.length ? 'ambiguous' : 'unknown'};
}

const adopted = shot => normalizeStatus(shot?.reviewStatus) === 'Approved' && Boolean(shot?.selectedVideoUrl);
const finite = value => typeof value === 'number' && Number.isFinite(value);

// The second of a quoted take a tag stands for, as far as the page knows: .start is the trim's in point (0 untrimmed); .end its out
// point, or null for an untrimmed take (its last frame: the server measures the file when it cuts the frame).
export function edgeSeconds(edge, trim) {
  if (edge === 'start') return finite(trim?.in) && trim.in > 0 ? trim.in : 0;
  return finite(trim?.out) ? trim.out : null;
}

// One entry per distinct tag of the prompt, in the order each first appears:
//   {key, code, edge, positions [{start, end}], shot (the quoted shot view or null), state, takeUrl, at, adopted}
//   state: 'unknown' (no shot of the episode has that code), 'ambiguous' (several have), 'self' (the shot quotes itself),
//   'no_take' (the quoted shot has no take to quote yet), 'not_adopted' (it has a take but none adopted: the newest is used), 'ok'.
// shots: the episode's shot views. currentShotId: the shot whose prompt this is.
export function resolveTakeRefs(text, shots = [], currentShotId = null) {
  const refs = new Map();
  for (const token of takeRefTokens(text)) {
    const known = refs.get(token.key);
    if (known) { known.positions.push({start: token.start, end: token.end}); continue; }
    const {shot, state} = shotForCode(token.code, shots);
    const entry = {key: token.key, code: token.code, edge: token.edge, positions: [{start: token.start, end: token.end}], shot,
      state: state || (shot.shotId === currentShotId ? 'self' : !shot.selectedVideoUrl ? 'no_take' : adopted(shot) ? 'ok' : 'not_adopted'),
      takeUrl: shot?.selectedVideoUrl || null, at: shot?.selectedVideoUrl ? edgeSeconds(token.edge, shot.trim) : null, adopted: adopted(shot)};
    refs.set(token.key, entry);
  }
  return [...refs.values()];
}

// The screenplay beat a shot was cut from, as the server reads it (story_take_refs._segment): [beat keys, segment index, segment
// count] when the shot is one exact segment of one beat, else null.
function segmentOf(shot) {
  const origin = shot?.storyOrigin || {}, recipes = origin.recipes || [];
  if (origin.mapping !== 'exact' || recipes.length !== 1 || !('segmentIndex' in recipes[0]) || !recipes[0].beatKeys?.length) return null;
  return [recipes[0].beatKeys.join('\u0000'), recipes[0].segmentIndex, recipes[0].segmentCount];
}

// SPEC_19 §7 decision 7, the same rule the server applies when no use is sent: the out point of a shot quoted by the shot that
// continues its action (the next segment of the same screenplay beat, or a split of the quoted shot) is the first frame; anything
// else is a reference. null when the page lacks either shot view: the server decides (and it says reference without evidence).
export function defaultUse(edge, shot, quoted) {
  if (!shot || !quoted) return null;
  if (edge !== 'end') return 'reference';
  const lineage = shot.storyLineage || {};
  if (lineage.operation === 'split' && (lineage.fromShotIds || []).includes(quoted.shotId)) return 'first_frame';
  const before = segmentOf(quoted), after = segmentOf(shot);
  if (before && after && before[0] === after[0] && before[2] === after[2] && after[1] === before[1] + 1) return 'first_frame';
  return 'reference';
}

// What a tag is used as: the person's choice (uses, keyed like takeRefUses), else the default. {use, chosen, decided}: decided is
// false when the page could not judge the default (shown as a reference; the server decides).
export function refUse(ref, uses = {}, shot = null) {
  const picked = uses?.[ref.key];
  if (TAKE_REF_USES.includes(picked)) return {use: picked, chosen: true, decided: true};
  const fallback = defaultUse(ref.edge, shot, ref.shot);
  return {use: fallback || 'reference', chosen: false, decided: fallback !== null};
}

// The takeRefUses a generation request sends: only uses the person chose, only for tags the prompt still holds, at most one first
// frame (the server refuses two; the later choices fall back to reference), at most MAX_TAKE_REFS. undefined when there is none.
export function takeRefUses(text, uses = {}) {
  const present = new Set(takeRefTokens(text).map(token => token.key)), body = {};
  let first = false;
  for (const [key, use] of Object.entries(uses || {})) {
    if (!present.has(key) || !TAKE_REF_USES.includes(use) || Object.keys(body).length >= MAX_TAKE_REFS) continue;
    if (use === 'first_frame' && first) { body[key] = 'reference'; continue; }
    first = first || use === 'first_frame';
    body[key] = use;
  }
  return Object.keys(body).length ? body : undefined;
}

// Choosing a use for one tag: only one tag can be the first frame, so choosing it turns any other first-frame choice into a reference.
export function chooseUse(uses = {}, key, use) {
  const next = {...uses};
  if (use === 'first_frame') for (const [other, value] of Object.entries(next)) if (other !== key && value === 'first_frame') next[other] = 'reference';
  next[key] = use;
  return next;
}

// SPEC_19 3.7 "Continue from the previous shot": the shot just before this one in slate order, in the same scene, when it has an
// adopted take. {shot, key, code, edge: 'end', use} (use: defaultUse, null when undecidable) or null.
//   shots: the episode's shot views in slate order (the caller orders them, as the film does).
export function previousShot(shots = [], current = null) {
  const list = Array.isArray(shots) ? shots : [], at = list.findIndex(shot => shot.shotId === current?.shotId);
  const prev = at > 0 ? list[at - 1] : null;
  if (!prev || !current?.sceneId || prev.sceneId !== current.sceneId || !adopted(prev)) return null;
  return {shot: prev, key: refKey(prev.shotIndex, 'end'), code: String(prev.shotIndex), edge: 'end', use: defaultUse('end', current, prev)};
}

// The tag text for a shot's edge: "@SC01-S02.end".
export const takeRefTag = (code, edge = 'end') => `@${String(code).trim()}.${edge}`;

// The tag goes at the very start of the prompt (3.7: "inserted at the start"), one space before the text; a prompt that already
// quotes that edge is left as it is. Returns {text, caret (just after the tag), changed}.
export function prependTakeRef(text, code, edge = 'end') {
  const source = String(text ?? ''), tag = takeRefTag(code, edge), key = refKey(code, edge);
  const found = takeRefTokens(source).find(token => token.key === key);
  if (found) return {text: source, caret: found.end, changed: false};
  const joined = tag + (source === '' || /^\s/.test(source) ? '' : ' ') + source;
  return {text: source === '' ? tag + ' ' : joined, caret: tag.length + 1, changed: true};
}

// The tag goes where the caret is, with the spacing that keeps it a tag: a space before it after a word character, @, :, # or -,
// and a space after it before a word character. Returns {text, caret}.
export function insertTakeRef(text, caret, code, edge = 'end') {
  const source = String(text ?? ''), at = Math.max(0, Math.min(Number.isInteger(caret) ? caret : source.length, source.length));
  const before = source.slice(0, at), after = source.slice(at), tag = takeRefTag(code, edge);
  const lead = /[\w@:#-]$/.test(before) ? ' ' : '', tail = after === '' || /^\w/.test(after) ? ' ' : '';
  return {text: before + lead + tag + tail + after, caret: (before + lead + tag + tail).length};
}

// The thumbnail of a tag: the frame it quotes when the page can show it, else the quoted shot's own thumbnail.
//   frozen: the current shot view's takeRefs (frames the server already cut). Returns {kind: 'image', url} | {kind: 'video', url, at}
//   (a paused frame of the take at that second) | null.
export function refThumb(ref, frozen = []) {
  const shot = ref?.shot;
  if (!shot) return null;
  const cut = (Array.isArray(frozen) ? frozen : []).find(item => item?.frameUrl && item.shotId === shot.shotId && item.edge === ref.edge
    && !item.stale && item.takeUrl === shot.selectedVideoUrl);
  if (cut) return {kind: 'image', url: cut.frameUrl};
  if (shot.selectedVideoUrl && finite(ref.at)) return {kind: 'video', url: shot.selectedVideoUrl, at: ref.at};
  if (shot.selectedImageUrl) return {kind: 'image', url: shot.selectedImageUrl};
  return null;
}
