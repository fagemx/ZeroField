import { codeTokens } from '../bindingModel.js';
import { takeRefTokens } from '../takeRefs.js';

// SPEC_19 3.3 / 4.3: the look catalog the shot composer offers, and the prompt's # move tags. Pure functions: no DOM, no requests.
//
// The catalog comes from GET /catalog/looks?kind=camera|move|genre|era|tempo|palette|light (project_docs/look_catalog.json): each option is
//   {id, kind, group? ('body' | 'lens' | 'aperture' for camera), labelKey, promptText, preview: {poster, clip} | null, hex?}
// and each group starts with its Auto option (empty promptText). A camera choice is written into the shot's Optical Rig column as the
// options' descriptions; a move is a #id tag inside the prompt, where it stands (its position says when the move happens, 1.2 G).

export const CAMERA_GROUPS = ['body', 'lens', 'aperture'];
// The look buttons of the composer, in order: references and camera (package B), film setup, palette and lighting (package C, which
// read lookScope below).
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

// ---- Package C (R11, R12): film setup, palette and lighting. GET /catalog/looks?kind=genre|era|tempo|palette|light answers the
// options of one kind, Auto first (empty promptText); a palette also has hex (its main colour first). Ids are what the episode
// settings (look) and a shot's override (PUT /shots/{id}/look) store.
export const SHOT_LOOK_KINDS = ['genre', 'era', 'tempo', 'palette', 'light'];
// The kinds each look button opens, in the order its wall lists them. Film setup groups genre, image era and tempo (one Film: line).
export const BUTTON_KINDS = {filmSetup: ['genre', 'era', 'tempo'], camera: ['camera'], palette: ['palette'], lighting: ['light']};
export const buttonOfKind = kind => Object.keys(BUTTON_KINDS).find(button => BUTTON_KINDS[button].includes(kind)) || null;
// The selector each kind is chosen with (3.3, the options draft): genre and tempo are left/right carousels, era a scale from old to
// new (Auto its own cell beside it), palette and light card grids with search and sort.
export const KIND_SELECTOR = {genre: 'carousel', era: 'scale', tempo: 'carousel', palette: 'grid', light: 'grid'};

// An option's label key when only its id is known (a proposal's value before the catalog arrives): lookCatalog.<kind>.<camelCaseId>,
// the convention the catalog's labelKeys follow (rain-mystery -> lookCatalog.genre.rainMystery).
export const labelKeyOf = (kind, id) => `lookCatalog.${kind}.${String(id ?? '').replace(/-([a-z0-9])/g, (_, char) => char.toUpperCase())}`;
// Whether an id is its kind's Auto: the catalog says so (no promptText); without the catalog, Auto ids are auto or auto-<group>.
export function isAutoId(id, items = []) {
  if (id === undefined || id === null || id === '') return true;
  const item = listOf(items).find(option => option?.id === id);
  return item ? !item.promptText : /^auto(-|$)/.test(String(id));
}
// The label of one id of one kind: its catalog option's, else its label key's, else the id.
export function idLabel(kind, id, items, translate) {
  if (isAutoId(id, items)) return translate('look.auto');
  const item = listOf(items).find(option => option?.id === id);
  return optionLabel(item || {id, labelKey: labelKeyOf(kind, id)}, translate);
}

// The look buttons say "Episode" when the shot follows the episode, set or Auto, and "This shot" when it overrides it.
export const scopeBadge = scope => (scope === 'shot' ? 'shot' : 'episode');
// A button over several kinds (film setup) is "This shot" as soon as one of them is overridden.
export function buttonScope(kinds, episodeLook, shotLook) {
  const scopes = kinds.map(kind => ({kind, ...lookScope(kind, episodeLook, shotLook)}));
  return {scope: scopes.some(item => item.scope === 'shot') ? 'shot' : 'episode', kinds: scopes};
}
// The kinds a shot overrides (the wall marks their category with a dot; Reset all and "Back to the episode" take them away).
export const overriddenKinds = (kinds, shotLook) => kinds.filter(kind => lookScope(kind, null, shotLook).scope === 'shot');
// The kinds an episode draft sets to something other than Auto (the dots of the episode look page).
export const setKinds = (kinds, look, catalog = {}) => kinds.filter(kind => !isAutoId(look?.[kind], catalog[kind]));

// PUT /shots/{id}/look bodies: one kind set, one or more kinds back to the episode (null), with the revision the shot was read at.
const withRevision = (body, revision) => (Number.isInteger(revision) ? {...body, baseRevision: revision} : body);
export const shotLookBody = (kind, id, revision) => withRevision({[kind]: id}, revision);
export const resetLookBody = (kinds, shotLook, revision) => withRevision(Object.fromEntries(overriddenKinds(kinds, shotLook).map(kind => [kind, null])), revision);

// ---- The camera of a shot: its Optical Rig cell. The episode's camera ({body, lens, aperture}) is the default only while the cell is
// empty; then the camera button says "Episode". Any text in the cell is the shot's own.
export function cameraScope(rigText, episodeCamera, items = []) {
  const own = String(rigText ?? '').trim() !== '';
  const groups = cameraGroups(items);
  const shared = CAMERA_GROUPS.some(group => !isAutoId(episodeCamera?.[group], groups[group]));
  if (own || !shared) return {scope: 'shot', choice: cameraChoice(rigText, items)};
  const choice = Object.fromEntries(CAMERA_GROUPS.map(group => [group, isAutoId(episodeCamera?.[group], groups[group]) ? autoOf(groups[group])?.id ?? null : episodeCamera[group]]));
  return {scope: 'episode', choice: {...choice, custom: false}};
}

// ---- An episode look draft (the Episode look page) and the PUT /episodes/{id}/settings body. Auto is left out, so all Auto is
// look: {} (which clears the stored look).
export function episodeDraft(settings = {}) {
  const look = settings?.look || {};
  return {aspectRatio: settings?.aspectRatio || '16:9', stylePresetId: String(settings?.stylePresetId || '88123'),
    look: {...Object.fromEntries(SHOT_LOOK_KINDS.map(kind => [kind, look[kind] ?? null])),
      camera: Object.fromEntries(CAMERA_GROUPS.map(group => [group, look.camera?.[group] ?? null]))}};
}
export function episodeLookBody(draft, settings = {}) {
  const look = {};
  for (const kind of SHOT_LOOK_KINDS) if (!isAutoId(draft.look?.[kind])) look[kind] = draft.look[kind];
  const camera = Object.fromEntries(CAMERA_GROUPS.filter(group => !isAutoId(draft.look?.camera?.[group])).map(group => [group, draft.look.camera[group]]));
  if (Object.keys(camera).length) look.camera = camera;
  return {aspectRatio: draft.aspectRatio, stylePresetId: draft.stylePresetId, ...(settings?.breakdownMode ? {breakdownMode: settings.breakdownMode} : {}), look};
}
export const sameDraft = (a, b) => JSON.stringify(episodeLookBody(a)) === JSON.stringify(episodeLookBody(b));
// How many shots keep their own value of a kind (they do not follow the episode): the page says so beside the choice.
export const overrideCount = (shots, kinds) => listOf(shots).filter(shot => overriddenKinds(kinds, shot?.look).length > 0).length;

// ---- A palette's swatch strip: its colours left to right, the main colour (the first) twice as wide. Only #rgb / #rrggbb count.
const HEX = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i;
export const swatchColors = hex => listOf(hex).filter(color => HEX.test(String(color)));
export function swatchGradient(hex) {
  const colors = swatchColors(hex);
  if (!colors.length) return null;
  const total = colors.length + 1, round = value => Math.round(value * 100) / 100;
  let at = 0;
  const stops = colors.map((color, index) => {
    const from = at; at += (index === 0 ? 2 : 1) / total * 100;
    return `${color} ${round(from)}% ${round(at)}%`;
  });
  return `linear-gradient(90deg, ${stops.join(', ')})`;
}
// How light a colour reads (relative luminance, 0 black to 1 white): the palette grid can sort dark to light by its main colour.
export function luminance(color) {
  if (!HEX.test(String(color))) return 1;
  let hex = String(color).slice(1);
  if (hex.length === 3) hex = [...hex].map(char => char + char).join('');
  const [r, g, b] = [0, 2, 4].map(at => parseInt(hex.slice(at, at + 2), 16) / 255).map(c => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

// The card grids' search and sort. Auto stays first whatever is typed; sort is 'catalog' (the catalog's order), 'name' (by label in
// the interface language) or 'tone' (palettes, dark to light by the main colour).
export function arrangeOptions(items, {query = '', sort = 'catalog', label = item => item?.id || ''} = {}) {
  const list = listOf(items), auto = list.filter(isAuto), rest = list.filter(item => !isAuto(item));
  const needle = String(query).trim().toLocaleLowerCase();
  const found = needle ? rest.filter(item => [label(item), item.id, item.promptText].some(text => String(text || '').toLocaleLowerCase().includes(needle))) : rest;
  const sorted = sort === 'name' ? [...found].sort((a, b) => label(a).localeCompare(label(b)))
    : sort === 'tone' ? [...found].sort((a, b) => luminance(swatchColors(a.hex)[0]) - luminance(swatchColors(b.hex)[0])) : found;
  return [...auto, ...sorted];
}

// A carousel shows size cards of count; start is the first. It opens with the chosen card in view, and steps one card at a time.
const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
export const carouselStart = (count, size, index) => clamp(index - Math.floor((size - 1) / 2), 0, Math.max(0, count - size));
export const carouselMove = (count, size, start, delta) => clamp(start + delta, 0, Math.max(0, count - size));
// The era scale: Auto on its own, the rest in catalog order (oldest look first).
export function eraScale(items) {
  const list = listOf(items);
  return {auto: list.find(isAuto) || null, steps: list.filter(item => !isAuto(item))};
}
