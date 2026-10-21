// The motion curve (SPEC_09 §4, ported from the shot-idiom generator's 運動區間): when in the shot the camera moves and
// how its speed is spread. Drag the band to slide the move, its edges to start or stop it earlier or later, the dot to
// move where it is half done. The window's length is the speed: a short window is a fast move. Double-click resets.
import * as G from './grammar.js';

const H = 92, TOP = 8, SPAN = 76, yOf = v => TOP + (1 - v) * SPAN;
const fmt = v => (Math.round(v * 10) / 10).toFixed(1);
export function curveLabel(s, t0 = 0) {
  const st = s.start, sp = G.moveStop(s), t = p => fmt(t0 + p * s.dur);
  return `${t(st)}–${t(sp)} s moving (${fmt((sp - st) * s.dur)} s → ${s.speed}) · half done at ${t(G.halfway(s))} s`;
}
export function renderCurve(el, s, t0) {
  const st = s.start, sp = G.moveStop(s), half = G.halfway(s), drag = DRAG?.h;
  let d = ''; for (let i = 0; i <= 90; i++) { const p = i / 90; d += `${i ? 'L' : 'M'}${(p * 300).toFixed(1)} ${yOf(G.progress(s, p)).toFixed(1)}`; }
  el.innerHTML = `<div class="mv" data-mv title="Double-click to reset the timing to the idiom">
      <svg viewBox="0 0 300 ${H}" preserveAspectRatio="none" aria-hidden="true">
        <rect x="${st * 300}" y="${TOP}" width="${Math.max(1, (sp - st) * 300)}" height="${SPAN}" fill="var(--cyan)" opacity=".13"/>
        <line x1="0" x2="300" y1="${yOf(0.5)}" y2="${yOf(0.5)}" stroke="#3a414c" stroke-dasharray="3 4" vector-effect="non-scaling-stroke"/>
        <path d="${d}" fill="none" stroke="var(--amber)" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>
      <div class="mv-band" data-mv-h="band" style="left:${st * 100}%;width:${(sp - st) * 100}%" title="Drag to slide the whole move"></div>
      <div class="mv-h ${drag === 'start' ? 'active' : ''}" data-mv-h="start" role="slider" tabindex="0" aria-label="Move starts" style="left:${st * 100}%"></div>
      <div class="mv-h ${drag === 'stop' ? 'active' : ''}" data-mv-h="stop" role="slider" tabindex="0" aria-label="Move ends" style="left:${sp * 100}%"></div>
      <div class="mv-k ${drag === 'mid' ? 'active' : ''}" data-mv-h="mid" role="slider" tabindex="0" aria-label="Half done at" style="left:${half * 100}%;top:${yOf(0.5)}px"></div>
    </div>
    <p class="hint" data-mv-label>${curveLabel(s, t0)}</p>`;
}

let DRAG = null;
export function bindCurve(ctx) {
  document.addEventListener('pointerdown', e => {
    const h = e.target.closest('[data-mv-h]'); if (!h || e.button !== 0) return;
    const r = ctx.row(), s = r.pick.s, box = h.closest('[data-mv]').getBoundingClientRect();
    const start0 = s.start, stop0 = G.moveStop(s), mid0 = s.mid ?? 0.5, minF = Math.min(1, G.minDur({ ...s, speed: 'fast' }) / s.dur), q = v => Math.round(v * 100) / 100;
    DRAG = { h: h.dataset.mvH, move(ev) {
      const df = (ev.clientX - e.clientX) / box.width; let start = start0, stop = stop0, mid = mid0, why = '';
      if (this.h === 'start') { const want = start0 + df, hi = Math.max(0, stop0 - minF); start = q(Math.max(0, Math.min(hi, want))); if (want > hi + 0.005) why = `the move needs at least ${(minF * s.dur).toFixed(1)} s`; if (want < -0.005) why = 'already at the start of the shot'; }
      if (this.h === 'stop') { const want = stop0 + df, lo = Math.min(1, start0 + minF); stop = q(Math.min(1, Math.max(lo, want))); if (want < lo - 0.005) why = `the move needs at least ${(minF * s.dur).toFixed(1)} s`; if (want > 1.005) why = 'already at the end of the shot'; }
      if (this.h === 'band') { const len = stop0 - start0, want = start0 + df; start = q(Math.max(0, Math.min(1 - len, want))); stop = start + len; if (want < -0.005) why = 'already at the start of the shot'; if (want > 1 - len + 0.005) why = 'already at the end of the shot'; }
      if (this.h === 'mid') { const want = mid0 + df / Math.max(0.05, stop0 - start0); mid = q(Math.max(0.2, Math.min(0.8, want))); if (want < 0.195 || want > 0.805) why = 'the halfway point stays within 20–80% of the move'; }
      const patch = { start, mlen: Math.round((stop - start) * s.dur * 100) / 100, mid };
      this.why = why; this.changed = start !== start0 || Math.abs(stop - stop0) > 0.005 || mid !== mid0;
      ctx.tx.live(S => ctx.patch(S, r.beat.id, patch), null, why, ev);
      this.main = this.changed ? `${r.beat.id} ${curveLabel(ctx.row().pick.s, ctx.t0()[ctx.rowIndex(r.beat.id)])}` : '';
    } };
    ctx.tx.begin('timing'); e.preventDefault();
  });
  window.addEventListener('pointermove', e => { if (DRAG) DRAG.move(e); });
  const end = ok => { if (!DRAG) return; const d = DRAG; DRAG = null; ctx.tx.end(ok && d.changed, d.main, d.why); };
  window.addEventListener('pointerup', () => end(true));
  window.addEventListener('blur', () => end(false));
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && DRAG) { e.preventDefault(); end(false); } });
  document.addEventListener('dblclick', e => {
    if (!e.target.closest('[data-mv]')) return;
    const r = ctx.row();
    ctx.tx.begin('timing'); ctx.tx.live(S => ctx.patch(S, r.beat.id, { start: undefined, mlen: undefined, mid: undefined }));
    ctx.tx.end(true, `${r.beat.id} move timing back to "${r.pick.idiom.name}"`);
  });
}
