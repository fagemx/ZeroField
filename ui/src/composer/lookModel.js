import { codeTokens } from '../bindingModel.js';
import { takeRefTokens } from '../takeRefs.js';

// SPEC_19 3.3 / 4.3: the look catalog the shot composer offers, and the prompt's # move tags. Pure functions: no DOM, no requests.
//
// The catalog comes from GET /catalog/looks?kind=camera|move (project_docs/look_catalog.json): each option is
//   {id, kind, group? ('body' | 'lens' | 'aperture' for camera), labelKey, promptText, preview: {poster, clip} | null, hex?}
// and each group starts with its Auto option (empty promptText). A camera choice is written into the shot's Optical Rig column as the
// options' descriptions; a move is a #id tag inside the prompt, where it stands (its position says when the move happens, 1.2 G).

export const CAMERA_GROUPS = ['body', 'lens', 'aperture'];
// The look buttons of the composer, in order. Package B draws references and camera; package C adds the other three by turning them on
// here and giving each its wall (they read lookScope below).
export const LOOK_BUTTONS = ['references', 'filmSetup', 'camera', 'palette', 'lighting'];
export const LOOK_KINDS = ['genre', 'era', 'tempo', 'camera', 'palette', 'light'];

const listOf = items => (Array.isArray(items) ? items : []);

// Camera options by group, each group in catalog order (Auto first).
export function cameraGroups(items) {
  const groups = Object.fromEntries(CAMERA_GROUPS.map(group => [group, []]));
  for (const item of listOf(items)) if (item?.kind === 'camera' && groups[item.group]) groups[item.group].push(item);
  return groups;
}
const isAuto = item => !item?.promptText;
const autoOf = list => list.find(isAuto) || null;

// Which body, lens and aperture an Optical Rig text holds: for each group, the option whose description the text contains (the
// longest, should one description contain another), else that group's Auto. custom: the text says something no option accounts for
// (a hand-written rig, or an older preset); choosing an option then replaces it.
export function cameraChoice(text, items) {
  const groups = cameraGroups(items), source = String(text ?? '').trim();
  let rest = source;
  const choice = {};
  for (const group of CAMERA_GROUPS) {
    const hit = groups[group].filter(item => !isAuto(item) && source.includes(item.promptText)).sort((a, b) => b.promptText.length - a.promptText.length)[0];
    choice[group] = (hit || autoOf(groups[group]))?.id ?? null;
    if (hit) rest = rest.replace(hit.promptText, ' ');
  }
  return {...choice, custom: rest.trim() !== ''};
}

// The Optical Rig text for a choice: the chosen descriptions in body, lens, aperture order, one space apart (the server's
// camera_text); Auto adds nothing, so all Auto is the empty text.
export function cameraText(choice, items) {
  const groups = cameraGroups(items);
  return CAMERA_GROUPS.map(group => groups[group].find(item => item.id === choice?.[group])?.promptText || '').filter(Boolean).join(' ');
}

// One group changed: the rest of the choice stays as it is.
export const withCamera = (choice, group, id) => ({...choice, [group]: id});

// The camera groups that differ from Auto: the wall marks their category with a dot.
export const changedGroups = (choice, items) => CAMERA_GROUPS.filter(group => {
  const auto = autoOf(cameraGroups(items)[group]);
  return choice?.[group] && choice[group] !== auto?.id;
});

// ---- # move tags (1.2 F), the rule of project_docs/story_look.py MOVE_TAG: whitespace or the start of the text before the #, a
// lowercase id of 2 to 41 characters, no ASCII id character (letter, digit, _ or -) right after it, and an id the catalog has.
// "Whitespace" is Python's (str.isspace), spelled out because JavaScript's \s differs from it (U+FEFF in, U+001C-U+001F and U+0085
// out). So @CAST-01#night is a wardrobe code, never a move; "。#pan" and "]#pan" are not tags; "#push-inX" is not; an unknown #word
// stays plain text.
const SPACE = '\\t\\n\\v\\f\\r\\x1c-\\x20\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000';
export const MOVE_TAG = new RegExp(`(?<![^${SPACE}])#([a-z][a-z0-9-]{1,40})(?![A-Za-z0-9_-])`, 'g');
const SPACE_CHAR = new RegExp(`[${SPACE}]`);
const idsOf = moves => new Set(listOf(moves instanceof Set ? [...moves] : moves).map(move => typeof move === 'string' ? move : move?.id).filter(Boolean));

// [{start, end, id}] for every catalog move tag in the text, in order. moves: the move ids, or the move options.
export function moveTokens(text, moves) {
  const known = idsOf(moves), found = [];
  for (const match of String(text ?? '').matchAll(MOVE_TAG)) if (known.has(match[1])) found.push({start: match.index, end: match.index + match[0].length, id: match[1]});
  return found;
}

// The moves of the shot in prompt order (a move written twice is listed twice).
export const moveOrder = (text, moves) => moveTokens(text, moves).map(token => token.id);
// Each move's place(s) in that order, 1-based: {id: [1, 3]}. The wall's cards show these numbers.
export function moveNumbers(text, moves) {
  const numbers = {};
  moveOrder(text, moves).forEach((id, index) => { (numbers[id] ||= []).push(index + 1); });
  return numbers;
}

// A move tag at the caret, spaced so it stays a tag: a space before it unless whitespace (or nothing) is there, and a space after it
// at the end of the text, before an ASCII id character, or before another # or @ tag. Returns {text, caret (just after the tag and its space)}.
export function insertMove(text, caret, id) {
  const source = String(text ?? ''), at = Math.max(0, Math.min(Number.isInteger(caret) ? caret : source.length, source.length));
  const before = source.slice(0, at), after = source.slice(at);
  const lead = before === '' || SPACE_CHAR.test(before.at(-1)) ? '' : ' ';
  const tail = after === '' || /^[A-Za-z0-9_#@-]/.test(after) ? ' ' : '';  // a tag right after needs its own space before it
  const head = before + lead + '#' + id + tail;
  return {text: head + after, caret: head.length};
}

const CLOSING = /^[,.;:!?)\]}…。，、；：！？）」』】]/;
// Every tag of one move goes, with one side of its spacing; the rest of the text stays as written.
export function removeMove(text, id, moves = [id]) {
  let out = String(text ?? '');
  for (const token of moveTokens(out, moves).filter(token => token.id === id).reverse()) {
    let before = out.slice(0, token.start), after = out.slice(token.end);
    if (/[ \t]$/.test(before) && (after === '' || /^\s/.test(after) || CLOSING.test(after))) before = before.slice(0, -1);
    else if ((before === '' || /\n$/.test(before)) && /^[ \t]/.test(after)) after = after.slice(1);
    out = before + after;
  }
  return out;
}

// Every move tag goes (the wall's Reset all).
export const removeMoves = (text, moves) => [...idsOf(moves)].reduce((out, id) => removeMove(out, id, moves), String(text ?? ''));

// ---- The prompt editor's tags, in reading order, never overlapping: @asset codes (written with their @), #moves the catalog has,
// and @shot.edge take references. {start, end, kind: 'asset' | 'move' | 'take', code | id | key, text}.
export function promptTokens(text, {moves = []} = {}) {
  const source = String(text ?? '');
  const found = [
    ...codeTokens(source).filter(token => token.at).map(token => ({start: token.start, end: token.end, kind: 'asset', code: token.code})),
    ...moveTokens(source, moves).map(token => ({...token, kind: 'move'})),
    ...takeRefTokens(source).map(token => ({start: token.start, end: token.end, kind: 'take', key: token.key, code: token.code, edge: token.edge})),
  ].sort((a, b) => a.start - b.start || b.end - a.end);
  const kept = [];
  for (const token of found) if (!kept.length || token.start >= kept.at(-1).end) kept.push({...token, text: source.slice(token.start, token.end)});
  return kept;
}

// What is being typed at the caret, for the @ / # menus: {trigger: '@' | '#', start (of the trigger), query} or null.
//   @ opens after anything but a word character (CJK text, punctuation, a space or the start); the query is the code typed so far.
//   # opens only where a move tag can stand (whitespace or the start before it); the query is lowercase id characters.
export function typingAt(text, caret) {
  const before = String(text ?? '').slice(0, Number.isInteger(caret) ? caret : undefined);
  const at = /(?:^|[^\w@])@([A-Za-z0-9:#._-]{0,32})$/.exec(before);
  if (at) return {trigger: '@', start: before.length - at[1].length - 1, query: at[1]};
  const hash = new RegExp(`(?:^|[${SPACE}])#([a-z0-9-]{0,40})$`).exec(before);
  if (hash) return {trigger: '#', start: before.length - hash[1].length - 1, query: hash[1]};
  return null;
}

// A menu choice replaces what was typed (from the trigger to the caret) with the token and one space. Returns {text, caret}.
export function replaceTyping(text, typing, caret, token) {
  const source = String(text ?? ''), after = source.slice(caret);
  const insert = token + (after === '' || !/^\s/.test(after) ? ' ' : '');
  return {text: source.slice(0, typing.start) + insert + after, caret: typing.start + insert.length};
}

// ---- Package C's episode look and shot overrides (4.3), defined here so the look buttons can read them: an episode keeps its look
// in its settings ({genre, era, tempo, camera, palette, light}: option ids), a shot keeps only what it overrides (meta look).
//   lookScope -> {value: option id | null, scope: 'shot' (overridden here) | 'episode' (follows the episode) | 'auto' (neither sets it)}
export function lookScope(kind, episodeLook = null, shotLook = null) {
  const own = shotLook?.[kind], shared = episodeLook?.[kind];
  if (own !== undefined && own !== null && own !== '') return {value: own, scope: 'shot'};
  if (shared !== undefined && shared !== null && shared !== '') return {value: shared, scope: 'episode'};
  return {value: null, scope: 'auto'};
}
// "Back to the episode": the shot drops its override of one kind. The PUT /shots/{id}/look body for that is {[kind]: null}.
export function withoutOverride(shotLook, kind) {
  const next = {...(shotLook || {})};
  delete next[kind];
  return next;
}
export const backToEpisodeBody = kind => ({[kind]: null});

// The label of an option in the interface language: its labelKey, else its id (a catalog newer than the interface).
export function optionLabel(item, translate) {
  if (!item) return '';
  const text = item.labelKey ? translate(item.labelKey) : '';
  return text && text !== item.labelKey ? text : item.id;
}

// A stable hue for an option without example media: its abstract texture placeholder is told apart by colour, never by a picture of
// something it is not.
export function textureHue(id) {
  let hash = 0;
  for (const char of String(id ?? '')) hash = (hash * 31 + char.codePointAt(0)) % 360;
  return hash;
}
