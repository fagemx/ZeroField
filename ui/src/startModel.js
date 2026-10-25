import { RATIOS } from './breakdownModel.js';

// SPEC_18 R16: a production that starts from a story. The hub makes the production and hands what was typed to Story & World, which opens
// with it already in the draft; nothing reaches the server until the build runs, exactly as when it is typed there. The hand-off lives in
// this tab's sessionStorage (the hub and the production are two page loads) and is read once.
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

const usable = value => Boolean(value) && typeof value === 'object' && START_MODES.includes(value.mode) && typeof value.text === 'string' && value.text.trim() !== '';

export function rememberStart(slug, start) {
  memory.set(slug, start);
  try { globalThis.sessionStorage?.setItem(key(slug), JSON.stringify(start)); } catch { /* No storage: a hand-off inside one page load still works. */ }
}

// The text a production was started with, once: asking again, or for another production, finds nothing.
export function takeStart(epId) {
  const slug = slugOfEpisode(epId);
  if (!slug) return null;
  let found = memory.get(slug) || null;
  memory.delete(slug);
  try {
    const storage = globalThis.sessionStorage;
    const saved = storage?.getItem(key(slug));
    if (saved) found = JSON.parse(saved);
    storage?.removeItem(key(slug));
  } catch { /* Unreadable or no storage: whatever memory held stands. */ }
  return usable(found) ? found : null;
}
