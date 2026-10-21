// The performance track (SPEC_10 §3.1): the selected beat's performance keys on its own time axis. One set of keys drives
// both the previs mannequin and the beat sheet, so dragging "his hand finds the dial" later makes him reach later in the
// previs and starts that segment of the Action & Audio Prompt later. Click a key to edit what it sets, double-click the
// track to add one, arrows nudge a focused key by 0.1 s, Delete removes it.
import { BEAT_STORY, HANDS_LABEL, LOOK_LABEL, POSE_LABEL } from './perf.js';

const GAP = 0.25;  // seconds between keys: closer than this and a segment is too short to play
const fmt = v => (Math.round(v * 10) / 10).toFixed(1);
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const actsOf = r => r.beat.acts || BEAT_STORY[r.beat.id].acts;
const short = k => (k.text ? `“${k.text.length > 34 ? k.text.slice(0, 32) + '…' : k.text}”` : [k.look && `looks at ${LOOK_LABEL[k.look]}`, k.hands && `hands ${HANDS_LABEL[k.hands]}`, k.body && POSE_LABEL[k.body], k.walk != null && `${k.walk} m from his mark`].filter(Boolean).join(', ') || 'an empty key');
function setActs(St, id, fn) {
  const acts = JSON.parse(JSON.stringify(St.perf[id]?.acts || BEAT_STORY[id].acts));
  fn(acts); acts.sort((a, b) => a.at - b.at); (St.perf[id] ||= {}).acts = acts;
  return acts;
}
// What a key change does to text someone wrote: re-timed it goes out of date; with more or fewer segments it no longer
// fits, and the template shows until it is rewritten.
const stale = (ctx, id, cut) => { const src = ctx.state().sheet[id]?.source; if (!src) return '';
  return cut ? `; the beat sheet ${src === 'edited' ? 'you edited' : 'the model wrote'} no longer fits the segments, so the template shows (Rewrite, or undo)`
    : src === 'agent' ? '; the written performance is out of date (Rewrite)' : ''; };
const segNo = (acts, i) => acts.slice(0, i + 1).filter(k => k.text != null).length;

let DRAG = null;
export function renderTrack(el, ctx) {
  if (!el) return;
  const r = ctx.row(), id = r.beat.id, secs = r.beat.seconds, acts = actsOf(r), key = ctx.ui.key?.id === id ? ctx.ui.key.i : null;
  const texts = acts.map((k, i) => [k, i]).filter(([k]) => k.text != null);
  const bands = texts.map(([k], j) => { const end = texts[j + 1]?.[0].at ?? 1; return `<div class="pt-band" style="left:${k.at * 100}%;width:${(end - k.at) * 100}%"><span>${j + 1}</span></div>`; }).join('');
  const ticks = Array.from({ length: secs + 1 }, (_, s) => `<i style="left:${s / secs * 100}%"><span>${s}s</span></i>`).join('');
  const k = key != null ? acts[key] : null, walks = acts.some(a => a.walk != null);
  const opt = (map, cur, keep) => (keep ? '<option value="">keeps the last</option>' : '') + Object.entries(map).map(([v, l]) => `<option value="${v}" ${v === cur ? 'selected' : ''}>${esc(l)}</option>`).join('');
  el.innerHTML = `<div class="row"><span class="label">Performance keys · ${id}</span><span class="hint">drag a key to re-time it, click to edit, double-click the track to add one</span>
      <span class="cost render" title="Re-renders the previs">re-renders the previs</span>
      ${ctx.state().perf[id]?.acts ? '<button data-preset-keys>Back to the beat\'s keys</button>' : ''}</div>
    <div class="pt" data-pt title="Double-click to add a key here">
      <div class="pt-ruler">${ticks}</div>${bands}
      ${acts.map((a, i) => `<div class="pt-k ${a.text != null ? 'txt' : ''} ${i === key ? 'sel' : ''} ${DRAG?.i === i ? 'active' : ''}" data-pk="${i}" role="slider" tabindex="0"
        aria-label="${esc(short(a))}" aria-valuenow="${fmt(a.at * secs)}" title="${fmt(a.at * secs)} s · ${esc(short(a))}" style="left:${a.at * 100}%">${a.text != null ? segNo(acts, i) : ''}</div>`).join('')}
      <div class="pt-play"></div>
    </div>
    ${k ? `<div class="kedit"><b>${key ? `Key ${key}` : 'Start'} · ${fmt(k.at * secs)} s</b>
      <label>Looks at <select data-kf="look">${opt(LOOK_LABEL, k.look, key > 0)}</select></label>
      <label>Hands <select data-kf="hands">${opt(HANDS_LABEL, k.hands, key > 0)}</select></label>
      <label>Body <select data-kf="body">${opt(POSE_LABEL, k.body || (key ? undefined : 'stand'), key > 0)}</select></label>
      ${walks ? `<label>From his mark <input type="number" data-kf="walk" min="0" max="4" step="0.1" value="${k.walk ?? ''}" placeholder="keeps" style="width:64px"> m</label>` : ''}
      <input type="text" data-kf="text" maxlength="160" value="${esc(k.text || '')}" placeholder="No text: this key only moves him" aria-label="What he does from this key" style="flex:1;min-width:220px">
      <button data-kdel ${key ? '' : 'disabled title="The start sets where he begins"'}>Delete key</button></div>` : ''}`;
  moveTrackHead(ctx);
}
export function moveTrackHead(ctx) {
  const head = document.querySelector('#perfTrack .pt-play'); if (!head) return;
  const r = ctx.row(), i = ctx.rowIndex(r.beat.id), p = (ctx.ui.t - ctx.t0()[i]) / r.beat.seconds;
  head.hidden = p < 0 || p > 1; head.style.left = `${Math.min(1, Math.max(0, p)) * 100}%`;
}

export function bindTrack(ctx) {
  const host = () => document.getElementById('perfTrack');
  const showAt = (id, at) => { const r = ctx.row(); ctx.ui.t = ctx.t0()[ctx.rowIndex(id)] + Math.min(r.beat.seconds - 1e-3, at * r.beat.seconds); ctx.draw(); };
  // Move key i of the selected beat to `want` (0..1), kept GAP seconds from its neighbours. Returns [at, why].
  const place = (acts, i, want, secs) => {
    const q = v => Math.round(v * secs * 20) / (secs * 20), lo = acts[i - 1].at + GAP / secs, hi = (acts[i + 1]?.at ?? 1) - GAP / secs;
    const at = q(Math.min(hi, Math.max(lo, want)));
    const why = want < lo - 1e-3 ? `keys stay ${GAP} s apart (the one before is at ${fmt(acts[i - 1].at * secs)} s)`
      : want > hi + 1e-3 ? (acts[i + 1] ? `keys stay ${GAP} s apart (the next is at ${fmt(acts[i + 1].at * secs)} s)` : `a key needs ${GAP} s before the end of the shot`) : '';
    return [at, why];
  };
  const moved = (id, acts, i, at, secs) => `${id} ${short(acts[i])} ${fmt(acts[i].at * secs)} → ${fmt(at * secs)} s${acts[i].text != null ? ` (segment ${segNo(acts, i)} now starts at ${fmt(at * secs)} s)` : ''}; the mannequin moves with it${stale(ctx, id)}`;

  document.addEventListener('pointerdown', e => {
    const k = e.target.closest('[data-pk]'); if (!k || e.button !== 0) return;
    const r = ctx.row(), id = r.beat.id, secs = r.beat.seconds, acts = actsOf(r), i = Number(k.dataset.pk), box = k.closest('[data-pt]').getBoundingClientRect();
    ctx.ui.key = { id, i }; e.preventDefault(); k.focus();
    if (!i) { renderTrack(host(), ctx); return showAt(id, 0); }  // the start key only selects: it sets where he begins
    ctx.tx.begin('key');
    DRAG = { i, x0: e.clientX, at: acts[i].at, why: '', moved: false, move(ev) {
      if (Math.abs(ev.clientX - this.x0) > 2) this.moved = true;
      if (!this.moved) return;
      [this.at, this.why] = place(acts, i, acts[i].at + (ev.clientX - this.x0) / box.width, secs);
      ctx.tx.live(St => setActs(St, id, a => { a[i].at = this.at; }), `${short(acts[i])} at ${fmt(this.at * secs)} s`, this.why, ev);
      showAt(id, this.at);
    }, end(ok) {
      ctx.tx.end(ok && this.moved && this.at !== acts[i].at, moved(id, acts, i, this.at, secs), this.why);
      if (!this.moved) { renderTrack(host(), ctx); showAt(id, acts[i].at); }
    } };
  });
  window.addEventListener('pointermove', e => { DRAG?.move(e); });
  const end = ok => { if (!DRAG) return; const d = DRAG; DRAG = null; d.end(ok); };
  window.addEventListener('pointerup', () => end(true));
  window.addEventListener('blur', () => end(false));
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && DRAG) { e.preventDefault(); return end(false); }
    const k = e.target.closest?.('[data-pk]'); if (!k) return;
    const r = ctx.row(), id = r.beat.id, secs = r.beat.seconds, acts = actsOf(r), i = Number(k.dataset.pk);
    if ((e.key === 'ArrowLeft' || e.key === 'ArrowRight') && i) {
      e.preventDefault(); e.stopPropagation();
      const [at, why] = place(acts, i, acts[i].at + (e.key === 'ArrowRight' ? 0.1 : -0.1) / secs, secs);
      if (at === acts[i].at) return ctx.say(`<span class="lim">${esc(why)}</span>`);
      ctx.ui.key = { id, i }; ctx.tx.once(moved(id, acts, i, at, secs), St => setActs(St, id, a => { a[i].at = at; }), id);
      document.querySelector(`#perfTrack [data-pk="${i}"]`)?.focus();
    }
    if ((e.key === 'Delete' || e.key === 'Backspace') && i) { e.preventDefault(); remove(id, acts, i, secs); }
  }, true);
  const remove = (id, acts, i, secs) => { ctx.ui.key = null; ctx.tx.once(`${id} removed the key at ${fmt(acts[i].at * secs)} s (${short(acts[i])})${stale(ctx, id, acts[i].text != null)}`, St => setActs(St, id, a => { a.splice(i, 1); }), id); };

  document.addEventListener('dblclick', e => {
    const t = e.target.closest('[data-pt]'); if (!t || e.target.closest('[data-pk]')) return;
    const r = ctx.row(), id = r.beat.id, secs = r.beat.seconds, acts = actsOf(r), box = t.getBoundingClientRect();
    const at = Math.round((e.clientX - box.left) / box.width * secs * 20) / (secs * 20), near = acts.find(a => Math.abs(a.at - at) * secs < GAP);
    if (near || at * secs > secs - GAP) return ctx.say(`<span class="lim">Keys stay ${GAP} s apart${near ? ` (there is one at ${fmt(near.at * secs)} s)` : ' and clear of the end of the shot'}</span>`);
    let added = 0;
    ctx.tx.once(`${id} added a key at ${fmt(at * secs)} s: pick what he does there`, St => { added = setActs(St, id, a => { a.push({ at }); }).findIndex(a => a.at === at && a.look == null && a.hands == null && a.text == null); }, id);
    ctx.ui.key = { id, i: added }; renderTrack(host(), ctx); showAt(id, at);
  });
  document.addEventListener('click', e => {
    const r = ctx.row(), id = r.beat.id, secs = r.beat.seconds, acts = actsOf(r);
    if (e.target.closest('[data-kdel]')) return remove(id, acts, ctx.ui.key.i, secs);
    if (e.target.closest('[data-preset-keys]')) { ctx.ui.key = null; ctx.tx.once(`${id} performance keys back to the beat's own${stale(ctx, id)}`, St => { delete St.perf[id].acts; }, id); }
  });
  document.addEventListener('change', e => {
    const f = e.target.closest?.('[data-kf]'); if (!f || ctx.ui.key == null) return;
    const r = ctx.row(), id = r.beat.id, secs = r.beat.seconds, acts = actsOf(r), i = ctx.ui.key.i, field = f.dataset.kf;
    const raw = field === 'text' ? f.value.trim() : f.value, v = field === 'walk' && raw !== '' ? Math.min(4, Math.max(0, Number(raw))) : raw;
    const what = field === 'text' ? (v ? `starts segment ${segNo([...acts.slice(0, i), { text: v }], i)}: “${v}”` : 'no longer starts a segment; it only moves him')
      : field === 'walk' ? (v === '' ? 'keeps his distance from the mark' : `${v} m from his mark`)
      : v === '' ? `${field} keeps the last key's` : field === 'look' ? `looks at ${LOOK_LABEL[v]}` : field === 'body' ? POSE_LABEL[v] : `hands ${HANDS_LABEL[v]}`;
    ctx.tx.once(`${id} key at ${fmt(acts[i].at * secs)} s ${what}${field === 'text' ? '' : '; the mannequin follows'}${stale(ctx, id, field === 'text' && !v !== (acts[i].text == null))}`,
      St => setActs(St, id, a => { if (v === '') delete a[i][field]; else a[i][field] = v; }), id);
  });
}
