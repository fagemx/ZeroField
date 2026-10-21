// The scene timeline (SPEC_09 §4): beats (drag a right edge: the shot's length, snapping to 4/6/8 s), the shot row
// (move class, framing, anchor breaks), the tension curve (drag a point) over each shot's camera energy, and the
// playhead (press on the curve and drag to scrub). One component, mounted in Storyboard, Shot and Overhead.
import * as G from './grammar.js';

const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const CURVE_H = 84, PAD = 8, SPAN = CURVE_H - 2 * PAD;
const yOf = v => PAD + (1 - v) * SPAN;
const base = id => Object.values(G.SCENES).flatMap(sc => sc.beats).find(b => b.id === id);  // the script's own beat (ids are unique across scenes)

export function renderTimeline(el, ctx) {
  const rows = ctx.rows(), T0 = ctx.t0(), scale = ctx.scale(), sel = ctx.ui.sel, drag = DRAG?.what;
  const pct = s => (s / scale) * 100, flags = new Set(G.checks(rows).filter(c => c.kind === 'warn').map(c => c.id));
  const steps = rows.map((r, i) => { const x0 = pct(T0[i]) * 10, x1 = pct(T0[i] + r.beat.seconds) * 10, y = yOf(r.beat.tension); return `${i ? 'L' : 'M'}${x0} ${y} L${x1} ${y}`; }).join(' ');
  const bars = rows.map((r, i) => { const x0 = pct(T0[i]) * 10 + 3, w = pct(r.beat.seconds) * 10 - 6, e = r.pick.s.energy;
    return `<rect x="${x0}" y="${yOf(e)}" width="${Math.max(1, w)}" height="${e * SPAN}" fill="var(--${G.MOVE_CLASS[r.pick.s.move]})" opacity=".35"/>`; }).join('');
  const marks = rows.map((r, i) => { const b0 = base(r.beat.id); if (Math.abs(b0.tension - r.beat.tension) < 0.01) return '';
    const cx = pct(T0[i] + r.beat.seconds / 2) * 10; return `<line x1="${cx - 18}" x2="${cx + 18}" y1="${yOf(b0.tension)}" y2="${yOf(b0.tension)}" stroke="var(--tension)" stroke-dasharray="3 3" opacity=".7" vector-effect="non-scaling-stroke"/>`; }).join('');
  const wants = rows.map((r, i) => { const x0 = pct(T0[i]) * 10 + 3, x1 = pct(T0[i] + r.beat.seconds) * 10 - 3, y = yOf(G.targetEnergy(r.beat.tension, rows.rules));
    return `<line x1="${x0}" x2="${x1}" y1="${y}" y2="${y}" stroke="#e6e8ec" stroke-dasharray="5 4" opacity=".55" vector-effect="non-scaling-stroke"/>`; }).join('');
  const ticks = []; for (let s = 0; s <= scale; s++) ticks.push(`<i style="left:${pct(s)}%" class="${s % 2 ? '' : 'major'}">${s % 2 ? '' : `<span>${s}s</span>`}</i>`);
  el.innerHTML = `<div class="tl" data-tl>
    <div class="tl-ruler" data-ruler title="Press and drag to move the playhead">${ticks.join('')}</div>
    <div class="tl-lane beats">${rows.map((r, i) => `
      <div class="tl-beat" data-beat="${r.beat.id}" data-sel="${r.beat.id === sel}" style="left:${pct(T0[i])}%;width:${pct(r.beat.seconds)}%" title="${esc(r.beat.title)}">
        <b>${r.beat.id}</b> ${flags.has(r.beat.id) ? '<span class="flag">!</span>' : ''} <small>${r.beat.seconds} s · ${esc(G.EVENTS[r.beat.event])}</small><br>${esc(r.pick.idiom.name)}${r.pinned ? ' <small>· pinned</small>' : ''}</div>
      <div class="tl-edge ${drag === 'edge:' + r.beat.id ? 'active' : ''}" data-edge="${r.beat.id}" style="left:${pct(T0[i] + r.beat.seconds)}%" title="Drag to change ${r.beat.id}'s length (4, 6 or 8 s)"></div>`).join('')}
    </div>
    <div class="tl-lane shots">${rows.map((r, i) => { const s = r.pick.s;
      return `<div class="tl-shot" data-shot="${r.beat.id}" data-class="${G.MOVE_CLASS[s.move]}" data-sel="${r.beat.id === sel}" style="left:${pct(T0[i])}%;width:${pct(r.beat.seconds)}%">
        ${s.end && s.end !== s.size ? `${s.size}→${s.end}` : s.size} · ${esc(G.MOVE_LABEL[s.move].toLowerCase())}${s.moving ? ' ' + s.speed : ''}${s.breaks ? '<span class="brk">anchor</span>' : ''}${r.pick.usable ? '' : ' <span class="bad">· blocked</span>'}</div>`; }).join('')}
    </div>
    <div class="tl-curve" data-curve>
      <span class="tl-axis hi">intense</span><span class="tl-axis lo">calm</span>
      <svg viewBox="0 0 1000 ${CURVE_H}" preserveAspectRatio="none" aria-hidden="true">${bars}${wants}${marks}
        <path d="${steps}" fill="none" stroke="var(--tension)" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>
      ${rows.map((r, i) => `<div class="tl-knob ${drag === 'knob:' + r.beat.id ? 'active' : ''} ${r.pinned ? 'pinned' : ''}" data-knob="${r.beat.id}" role="slider" aria-label="${r.beat.id} tension" aria-valuemin="0" aria-valuemax="1" aria-valuenow="${r.beat.tension}" tabindex="0" style="left:${pct(T0[i] + r.beat.seconds / 2)}%;top:${yOf(r.beat.tension)}px"
        title="${r.beat.id} tension ${r.beat.tension.toFixed(2)}. ${r.pinned ? `Pinned to “${esc(r.pick.idiom.name)}”: tension will not change its camera until you unpin it.` : 'Drag up for a more intense beat (a camera that does more), down for a calmer one. The shot re-picks its idiom on release.'}"></div>`).join('')}
    </div>
    <div class="tl-play" data-play-head style="left:${pct(ctx.ui.t)}%"></div>
    <div class="tl-legend"><span><i style="background:var(--hold)"></i>Locked-off</span><span><i style="background:var(--travel)"></i>Camera travels</span><span><i style="background:var(--turn)"></i>Camera turns</span>
      <span><i style="background:var(--tension);height:3px"></i>Tension: how intense each beat is. Drag a point; unpinned shots re-pick their camera</span>
      <span><i style="background:var(--travel);opacity:.35"></i>Bar: how much the chosen camera does</span><span><i style="border-top:2px dashed #e6e8ec;height:0;opacity:.6"></i>What this tension asks the camera for</span>
      <span>anchor = a fast move that breaks the calm camera</span><span>Drag on the ruler to scrub · Space plays</span></div>
  </div>`;
}
export function movePlayhead(root, ctx) {
  root.querySelectorAll('[data-play-head]').forEach(p => { p.style.left = `${(ctx.ui.t / ctx.scale()) * 100}%`; });
}

/* ---------- interaction: one drag at a time, live preview, apply on release, Esc cancels (SPEC_09 R3) ---------- */
let DRAG = null;
export const dragging = () => !!DRAG;
export function bindTimeline(ctx) {
  document.addEventListener('pointerdown', e => {
    const tl = e.target.closest('[data-tl]'); if (!tl || e.button !== 0) return;
    const box = tl.getBoundingClientRect(), rows = ctx.rows(), T0 = ctx.t0();
    const edge = e.target.closest('[data-edge]'), knob = e.target.closest('[data-knob]');
    if (edge) {
      const id = edge.dataset.edge, i = rows.findIndex(r => r.beat.id === id), sec0 = rows[i].beat.seconds, total0 = ctx.total();
      ctx.freezeScale(total0);  // the scale holds while dragging, so the edge stays under the pointer (a longer scene runs off the right)
      const pxPerSec = box.width / total0;
      DRAG = { what: 'edge:' + id, move(ev) {
        const raw = sec0 + (ev.clientX - e.clientX) / pxPerSec, sec = G.DURATIONS.reduce((a, b) => (Math.abs(b - raw) < Math.abs(a - raw) ? b : a));
        const lim = raw < G.DURATIONS[0] - 0.8 || raw > G.DURATIONS.at(-1) + 0.8 ? 'LTX-2.5 renders 4, 6 or 8 s (97, 145 or 193 frames)' : '';
        this.main = sec === sec0 ? '' : `${id} ${sec0} → ${sec} s (scene ${total0} → ${total0 - sec0 + sec} s)`; this.why = lim;
        ctx.tx.live(S => { (S.beats[id] ||= {}).seconds = sec; }, `${id} ${sec} s · scene ${total0 - sec0 + sec} s`, lim, ev);
      } };
      ctx.tx.begin('length');
    } else if (knob) {
      const id = knob.dataset.knob, t0 = rows.find(r => r.beat.id === id).beat.tension, y0 = e.clientY, pinned = ctx.state().pins?.[id];
      DRAG = { what: 'knob:' + id, move(ev) {
        const raw = t0 - (ev.clientY - y0) / SPAN, t = Math.round(Math.min(1, Math.max(0, raw)) / 0.05) * 0.05;
        this.main = Math.abs(t - t0) < 1e-6 ? '' : `${id} tension ${t0.toFixed(2)} → ${t.toFixed(2)}`;
        this.why = raw > 1.02 || raw < -0.02 ? 'tension runs from 0 to 1' : '';
        ctx.tx.live(S => { (S.beats[id] ||= {}).tension = +t.toFixed(2); },
          () => { const also = G.pickChanges(rows, ctx.rows()).filter(c => c.id !== id).map(c => `${c.id} → “${c.to}”`);
            return `${id} tension ${t.toFixed(2)} → ${pinned ? `stays “${pinned}” (pinned)` : `“${ctx.rows().find(r => r.beat.id === id).pick.idiom.name}”`}${also.length ? ` · also ${also.join(', ')}` : ''}`; }, this.why, ev);
      } };
      ctx.select(id, false);
      ctx.tx.begin('tension');
    } else if (e.target.closest('[data-beat]')) {
      return ctx.select(e.target.closest('[data-beat]').dataset.beat);
    } else if (!e.target.closest('[data-ruler]')) {  // the shot row and the curve select the beat under the pointer
      const t = (e.clientX - box.left) / box.width * ctx.scale(); let i = rows.length - 1; while (i > 0 && t < T0[i]) i--;
      return ctx.select(rows[i].beat.id);
    } else {
      const scrub = ev => { const t = Math.min(ctx.total() - 0.01, Math.max(0, (ev.clientX - box.left) / box.width * ctx.scale())); ctx.seek(t, true); };
      DRAG = { what: 'scrub', scrub: true, move: scrub }; scrub(e);
      e.preventDefault(); return;
    }
    e.preventDefault();
  });
  window.addEventListener('pointermove', e => { if (DRAG) DRAG.move(e); });
  const end = ok => { if (!DRAG) return; const d = DRAG; DRAG = null; ctx.freezeScale(null); if (!d.scrub) ctx.tx.end(ok && !!d.main, d.main, d.why); };
  window.addEventListener('pointerup', () => end(true));
  window.addEventListener('blur', () => end(false));
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && DRAG) { e.preventDefault(); end(false); } });
  // Keyboard on a focused tension point: arrows step 0.05 (R1 with a keyboard path).
  document.addEventListener('keydown', e => {
    const knob = e.target.closest?.('[data-knob]'); if (!knob || !['ArrowUp', 'ArrowDown'].includes(e.key)) return;
    e.preventDefault(); e.stopPropagation();
    const id = knob.dataset.knob, t0 = ctx.rows().find(r => r.beat.id === id).beat.tension, t = Math.min(1, Math.max(0, +(t0 + (e.key === 'ArrowUp' ? 0.05 : -0.05)).toFixed(2)));
    if (t === t0) return;
    ctx.tx.begin('tension'); ctx.tx.live(S => { (S.beats[id] ||= {}).tension = t; }); ctx.tx.end(true, `${id} tension ${t0.toFixed(2)} → ${t.toFixed(2)}`);
    document.querySelector(`[data-knob="${id}"]`)?.focus();
  }, true);
}
