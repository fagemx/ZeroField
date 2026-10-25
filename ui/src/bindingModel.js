import { resolveAssetReference } from './studioModel.js';

// Shot bindings (SPEC_18 R2, R3): the @codes a shot's prompt names, read and edited where they stand.
// Where a code sits in the sentence is part of what the sentence says ("@CAST-01 turns @PROP-01 toward @SET-01"), so every edit
// below touches only the target code's own characters and the space it leaves behind. Nothing is re-ordered or re-written around it.
const CODE = /@?\b((?:CAST|SET|LOC|PROP|STYLE)-\d+(?:[:#][a-z0-9_-]+)?)\b/gi;

export const normalizeCode = code => String(code || '').replace(/^@/, '').replace('#', ':').toUpperCase();
export const codeBase = code => normalizeCode(code).split(':')[0];
export const codeLook = code => normalizeCode(code).split(':')[1] || '';
const TYPES = {CAST: 'CHARACTER', SET: 'SCENE', LOC: 'SCENE', PROP: 'PROP', STYLE: 'STYLE'};
export const codeType = code => TYPES[codeBase(code).split('-')[0]] || null;

// Every code in the text in reading order: its normalized form, where it sits, and whether it was written with its @.
export function codeTokens(text) {
  return [...String(text ?? '').matchAll(CODE)].map(match => ({code: normalizeCode(match[1]), start: match.index, end: match.index + match[0].length, at: match[0].startsWith('@')}));
}

// The column of a production sheet that carries the shot's prompt: "Action & Audio Prompt", else the first column that looks like one.
export function actionColumn(headers = []) {
  const exact = headers.findIndex(label => /action\s*&?\s*audio\s*prompt/i.test(label));
  return exact >= 0 ? exact : headers.findIndex(label => /action|prompt/i.test(label));
}

// One row per distinct code, in the order each first appears; a code named twice is one row that remembers both places.
// lookup: buildAssetLookup(). missing: the row has no picture to show; unknown: the asset sheet does not list it at all.
export function shotBindings(text, lookup = {}) {
  const rows = new Map();
  for (const token of codeTokens(text)) {
    const row = rows.get(token.code) || {code: token.code, base: codeBase(token.code), look: codeLook(token.code), positions: []};
    row.positions.push({start: token.start, end: token.end});
    rows.set(token.code, row);
  }
  return [...rows.values()].map(row => {
    const entry = resolveAssetReference(row.code, lookup), known = Boolean(lookup[row.code] || lookup[row.base]);
    const imageUrl = entry.media?.kind === 'image' ? entry.media.url : null;
    return {...row, name: (known && entry.name) || row.base, lookNamed: Boolean(row.look && lookup[row.code]?.name), imageUrl, missing: !imageUrl, unknown: !known};
  });
}

// Rebuilds the text with each code replaced by whatever `change(token)` returns (a string), or kept when it returns null.
function rewrite(text, change) {
  const source = String(text ?? '');
  let out = '', cursor = 0;
  for (const token of codeTokens(source)) {
    const next = change(token);
    if (next === null) continue;
    out += source.slice(cursor, token.start) + next;
    cursor = token.end;
  }
  return out + source.slice(cursor);
}

// Another look of the same asset: only that code changes (its @ stays or stays absent), everything else is the same characters.
export function replaceLook(text, code, nextCode) {
  const from = normalizeCode(code), to = normalizeCode(nextCode);
  return rewrite(text, token => token.code === from ? (token.at ? '@' : '') + to : null);
}

const AFTER_PUNCTUATION = /^[,.;:!?、，。；：！？)）\]】」』]/;
// The code and its own space go; the gap it leaves closes: no double spaces, no space before a mark, no space left at a line's start.
export function removeBinding(text, code) {
  const target = normalizeCode(code);
  const found = codeTokens(text).filter(token => token.code === target);
  let out = String(text ?? '');
  for (const token of found.reverse()) {
    let before = out.slice(0, token.start), after = out.slice(token.end);
    const trailing = /[ \t]+$/.test(before);
    if (trailing && (/^[ \t]/.test(after) || after === '' || /^\r?\n/.test(after) || AFTER_PUNCTUATION.test(after))) before = before.replace(/[ \t]+$/, '');
    if (before === '' || /\n$/.test(before)) after = after.replace(/^[ \t]+/, '');
    out = before + after;
  }
  return out;
}

// A code not yet named joins at the end of the sentence, one space after the last character. Naming it twice changes nothing.
export function addBinding(text, code) {
  const source = String(text ?? ''), next = normalizeCode(code);
  if (!next || codeTokens(source).some(token => token.code === next)) return source;
  return source === '' ? '@' + next : source + (/\s$/.test(source) ? '' : ' ') + '@' + next;
}

// The lookup the tags read, from the story API's asset list, for places where the sheet's own lookup is not at hand (the script outline).
// Same shape as buildAssetLookup(); a look with no picture of its own shows its base asset's, as it does there.
export function assetLookupFrom(assets = []) {
  const lookup = {};
  for (const asset of assets) {
    const code = normalizeCode(asset.assetCode);
    lookup[code] = {id: code, name: asset.name || '', ...(asset.selectedImageUrl ? {media: {kind: 'image', url: asset.selectedImageUrl}} : {})};
  }
  for (const [code, entry] of Object.entries(lookup)) {
    const base = lookup[code.split(':')[0]];
    if (code.includes(':') && !entry.media && base?.media) lookup[code] = {...entry, media: base.media};
  }
  return lookup;
}

// Codes that also appear in the row's other cells (notes, say). A binding edit only rewrites the prompt column, so those stay in the
// shot's assets; the cast block says so instead of pretending the code is gone. Returns {CODE: [column label, ...]}.
export function codesElsewhere(headers = [], cells = [], skip = -1) {
  const where = {};
  cells.forEach((cell, index) => {
    if (index === skip) return;
    for (const {code} of codeTokens(typeof cell === 'object' && cell ? cell.value : cell)) (where[code] ||= []).includes(headers[index]) || where[code].push(headers[index] || String(index + 1));
  });
  return where;
}
