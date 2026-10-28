import { RATIOS } from './breakdownModel.js';

// SPEC_18 R16: the hub hands the original text to Story & World through this tab's sessionStorage.
// peekStart keeps it recoverable until the actor-bound writing save AND resource load succeed;
// only the host then acknowledges that exact hand-off. takeStart remains a destructive legacy adapter.
export const START_MODES = ['idea', 'novel', 'script'];
export const MAX_START_TEXT = 500000;   // what the Story page accepts for one draft
export const MAX_START_FILE = 2000000;  // bytes, as for "Upload script"
export const START_FILE = /\.(txt|md)$/i;
const key = slug => 'zf.start:' + slug;
const memory = new Map();

export const slugOfEpisode = epId => /^ep_([a-z0-9-]{1,41})_\d+$/.exec(String(epId || ''))?.[1] || '';

// A title for a production nobody named: the first line of what was written, without its markup, cut at 40 characters.
export function titleFrom(text, fallback = '') {
  const line = String(text || '').split(/\r?\n/).map(part => part.replace(/^[#>*_\-\s]+/, '').replace(/[#*_\s]+$/, '')).find(Boolean) || '';
  return Array.from(line).slice(0, 40).join('').trim() || fallback;
}

// What to hand over, or why nothing can be: 'mode', 'empty' or 'long'.
export function startPlan({mode, text, ratio = RATIOS[0], style = ''}) {
  const body = String(text || '').trim();
  if (!START_MODES.includes(mode)) return {ok: false, reason: 'mode'};
  if (!body) return {ok: false, reason: 'empty'};
  if (body.length > MAX_START_TEXT) return {ok: false, reason: 'long'};
  return {ok: true, start: {mode, text: body, ratio: RATIOS.includes(ratio) ? ratio : RATIOS[0], style: String(style || '')}};
}

// The production a story start creates (SPEC_20 R44-1, R44-2): the studio template's pages, columns and pipeline,
// without its sample brief, cast, sets, shots or clips, so the story becomes the working screenplay.
export function storyProductionRequest(title, slug = `project-${globalThis.crypto.randomUUID().slice(0, 8)}`) {
  return {slug, title, template: 'zerofield_studio', status: 'planning', summary: '', samples: false};
}

const usable = value => Boolean(value) && typeof value === 'object' && START_MODES.includes(value.mode) && typeof value.text === 'string' && value.text.trim() !== '';

export function rememberStart(slug, start) {
  if (usable(start) && !start.handoffId) start.handoffId = globalThis.crypto?.randomUUID?.() || `start-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  memory.set(slug, structuredClone(start));
  try {
    const storage = globalThis.sessionStorage;
    if (!storage) return false;
    storage.setItem(key(slug), JSON.stringify(start));
    return true;
  } catch { return false; /* Memory fallback works, but callers can refuse non-durable checkpoints. */ }
}

// Non-destructive, including old pending starts: migrate their stable retry identity before returning.
export function peekStart(epId) {
  const slug = slugOfEpisode(epId);
  if (!slug) return null;
  let found = memory.get(slug) || null;
  try {
    const saved = globalThis.sessionStorage?.getItem(key(slug));
    if (saved) found = JSON.parse(saved);
  } catch { /* Unreadable or no storage: whatever memory held stands. */ }
  if (!usable(found)) return null;
  if (!found.handoffId) {
    const cached = memory.get(slug);
    if (cached?.handoffId && samePayload(cached, found)) found.handoffId = cached.handoffId;
    rememberStart(slug, found);
  }
  return structuredClone(found);
}

const samePayload = (left, right) => usable(left) && usable(right) && ['mode','text','ratio','style'].every(field => left[field] === right[field]);
const sameStart = (left, right) => samePayload(left, right) && left.handoffId === right.handoffId;

// Compare-and-delete: an old save/load completion must never consume a newer hand-off.
// Checkpoint updates of the SAME start do not invalidate its eventual acknowledgement.
export function acknowledgeStart(epId, start) {
  const slug = slugOfEpisode(epId);
  if (!slug || !start?.handoffId || !sameStart(peekStart(epId), start)) return false;
  try {
    const storage = globalThis.sessionStorage;
    const saved = storage?.getItem(key(slug));
    if (saved) {
      let current;
      try { current = JSON.parse(saved); } catch { return false; }
      if (!sameStart(current, start)) return false;
      try { storage.removeItem(key(slug)); } catch { return false; }
    }
  } catch { /* Blocked storage: only the memory copy can be acknowledged. */ }
  if (sameStart(memory.get(slug), start)) memory.delete(slug);
  return true;
}

// Legacy read-once callers retain their old behaviour; reliable callers use peek + acknowledge.
export function takeStart(epId) {
  const start = peekStart(epId);
  if (start) acknowledgeStart(epId, start);
  return start;
}
