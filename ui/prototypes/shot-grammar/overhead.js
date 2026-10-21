// Overhead editing (SPEC_09 §4): the selected shot drawn over the plan view — camera path, start and end cameras, the
// side range its idiom allows (red where the set blocks it), the subject, and the actor with a facing handle. Drag the
// start camera round the subject (side) or in and out (start size), the end camera (end size, or where an orbit ends),
// the actor (his mark) or the arrow (which way he faces). Hold Shift for fine framing: 1° steps and any distance.
import * as THREE from 'three';
import { framesOf } from '../../src/previs/plan.js';
import * as G from './grammar.js';

const v3 = new THREE.Vector3();
const fine = k => Math.round(Math.min(G.FINE.hk[1], Math.max(G.FINE.hk[0], k)) * 100) / 100;
let canvas = null, hits = [], DRAG = null;
function size() {
  const r = canvas.getBoundingClientRect(), k = devicePixelRatio || 1;
  if (canvas.width !== Math.round(r.width * k) || canvas.height !== Math.round(r.height * k)) { canvas.width = Math.round(r.width * k); canvas.height = Math.round(r.height * k); }
  return { w: r.width, h: r.height, k, r };
}
const project = (cam, p, w, h) => { v3.set(...p).project(cam); return [(v3.x + 1) / 2 * w, (1 - v3.y) / 2 * h]; };
function ground(cam, px, py, w, h, y) {
  const a = new THREE.Vector3((px / w) * 2 - 1, -(py / h) * 2 + 1, 0.5).unproject(cam), d = a.sub(cam.position);
  const t = (y - cam.position.y) / d.y; return [cam.position.x + d.x * t, cam.position.z + d.z * t];
}
export function mountOverlay(host) {
  if (!canvas) { canvas = document.createElement('canvas'); canvas.className = 'overlay'; canvas.setAttribute('aria-label', 'Overhead handles'); }
  host.appendChild(canvas);
}

export function drawOverlay(ctx) {
  if (!canvas?.isConnected) return;
  const { w, h, k } = size(), g = canvas.getContext('2d'), cam = ctx.topCamera, r = ctx.row(), s = r.pick.s, plan = r.plan;
  g.setTransform(k, 0, 0, k, 0, 0); g.clearRect(0, 0, w, h); hits = [];
  const P = p => project(cam, p, w, h), room = ctx.room(r);
  // Side range at the start distance: cyan where the camera may stand, red where the set blocks it.
  for (let a = room.azAll[0]; a < room.azAll[1]; a += 5) {
    const p0 = P(G.solve({ ...s, az: a, move: 'static' }, plan, 0).pos), p1 = P(G.solve({ ...s, az: a + 5, move: 'static' }, plan, 0).pos);
    g.strokeStyle = room.blockedAz.includes(a) || room.blockedAz.includes(a + 5) ? 'rgba(242,105,92,.85)' : 'rgba(6,182,212,.7)';
    g.lineWidth = 4; g.beginPath(); g.moveTo(...p0); g.lineTo(...p1); g.stroke();
  }
  // The camera path through the shot.
  g.strokeStyle = '#f59e0b'; g.lineWidth = 2; g.beginPath();
  for (let i = 0; i <= 30; i++) { const q = P(G.solve(s, plan, i / 30).pos); i ? g.lineTo(...q) : g.moveTo(...q); }
  g.stroke();
  const c0 = G.solve(s, plan, 0), c1 = G.solve(s, plan, 1), F = P(c0.F);
  const camGlyph = (c, filled, label) => {
    const p = P(c.pos), a = P(c.aim), dx = a[0] - p[0], dy = a[1] - p[1], l = Math.hypot(dx, dy) || 1;
    g.strokeStyle = '#f59e0b'; g.lineWidth = 1.5; g.beginPath(); g.moveTo(...p); g.lineTo(p[0] + dx / l * 26, p[1] + dy / l * 26); g.stroke();
    g.beginPath(); g.arc(p[0], p[1], 8, 0, 2 * Math.PI); g.fillStyle = filled ? '#f59e0b' : '#0d0f12'; g.fill(); g.stroke();
    g.fillStyle = '#e6e8ec'; g.font = '12px system-ui'; g.fillText(label, p[0] + 11, p[1] - 9);
    return p;
  };
  const moved = s.moving && Math.hypot(c1.pos[0] - c0.pos[0], c1.pos[2] - c0.pos[2]) > 0.05;
  if (moved) hits.push({ what: 'end', at: camGlyph(c1, false, 'end'), r: 12 });
  hits.push({ what: 'start', at: camGlyph(c0, true, moved ? 'start' : 'camera'), r: 12 });
  g.fillStyle = '#06b6d4'; g.beginPath(); g.arc(F[0], F[1], 4, 0, 2 * Math.PI); g.fill();
  // The actor at the moment the shot is framed on, with his facing handle.
  const A = G.actorAt(plan, G.refTime(s) * (framesOf(plan) - 1)), body = P([A.root[0], 0, A.root[2]]);
  const edge = P([A.root[0] + 0.28, 0, A.root[2]]), rad = Math.max(8, Math.hypot(edge[0] - body[0], edge[1] - body[1]));
  const hand = P([A.root[0] + A.fwd[0] * 0.8, 0, A.root[2] + A.fwd[2] * 0.8]);
  g.strokeStyle = '#e6e8ec'; g.lineWidth = 2; g.beginPath(); g.arc(body[0], body[1], rad, 0, 2 * Math.PI); g.stroke();
  g.beginPath(); g.moveTo(...body); g.lineTo(...hand); g.stroke();
  g.fillStyle = '#e6e8ec'; g.beginPath(); g.arc(hand[0], hand[1], 6, 0, 2 * Math.PI); g.fill();
  g.font = '12px system-ui'; g.fillText(r.beat.partner ? r.beat.name : 'mark', body[0] + rad + 4, body[1] + 4);
  hits.push({ what: 'facing', at: hand, r: 11 }, { what: 'actor', at: body, r: rad + 4 });
  const B = G.partnerAt(plan);
  if (B) {  // the other person, and the 180° line through them both; the camera's side is shaded
    const pb = P([B.root[0], 0, B.root[2]]), ax = [B.root[0] - A.root[0], B.root[2] - A.root[2]], l = Math.hypot(...ax) || 1, u = ax.map(v => v / l);
    const far = k => P([A.root[0] + u[0] * k, 0, A.root[2] + u[1] * k]), side = plan.side || 1, n = [-u[1] * side, u[0] * side];
    const shade = [far(-8), far(8), P([A.root[0] + u[0] * 8 + n[0] * 8, 0, A.root[2] + u[1] * 8 + n[1] * 8]), P([A.root[0] - u[0] * 8 + n[0] * 8, 0, A.root[2] - u[1] * 8 + n[1] * 8])];
    g.fillStyle = 'rgba(6,182,212,.07)'; g.beginPath(); shade.forEach((q, i) => (i ? g.lineTo(...q) : g.moveTo(...q))); g.fill();
    g.setLineDash([6, 5]); g.strokeStyle = 'rgba(230,232,236,.55)'; g.lineWidth = 1.5; g.beginPath(); g.moveTo(...far(-8)); g.lineTo(...far(8)); g.stroke(); g.setLineDash([]);
    g.strokeStyle = '#c4b5fd'; g.lineWidth = 2; g.beginPath(); g.arc(pb[0], pb[1], rad, 0, 2 * Math.PI); g.stroke();
    g.fillStyle = '#c4b5fd'; g.fillText(r.beat.partner.name, pb[0] + rad + 4, pb[1] + 4);
    g.fillStyle = 'rgba(230,232,236,.7)'; const lab = far(-1.2); g.fillText('180° line', lab[0] + 6, lab[1] - 6);
    hits.push({ what: 'partner', at: pb, r: rad + 4 });
  }
}

export function bindOverlay(ctx) {
  document.addEventListener('pointerdown', e => {
    if (e.target !== canvas || e.button !== 0) return;
    const { w, h, r: box } = size(), x = e.clientX - box.left, y = e.clientY - box.top;
    const hit = hits.find(o => Math.hypot(o.at[0] - x, o.at[1] - y) <= o.r); if (!hit) return;
    const row = ctx.row(), id = row.beat.id, s0 = row.pick.s, plan0 = row.plan, cam = ctx.topCamera;
    const room = ctx.room(row), az0 = s0.az ?? room.az0, A0 = G.actorAt(plan0, G.refTime(s0) * (framesOf(plan0) - 1));
    const beat0 = ctx.state().beats?.[id] || {}, mark0 = row.beat.mark || [0, 0], turn0 = beat0.turn || 0, back = mark0[1] - A0.root[2];
    const sc = ctx.scene(), shared = !!sc.blocking, who = hit.what === 'partner' ? row.beat.with : row.beat.who, from = hit.what === 'partner' ? row.beat.partner.mark : mark0;
    const setMark = (S, m) => { if (shared) ((S.blocking ||= {})[sc.id] ||= {})[who] = m; else (S.beats[id] ||= {}).mark = m; };
    const ends = room.ends ? room.ends.filter(z => { const si = G.SIZES.indexOf(s0.size), zi = G.SIZES.indexOf(z); return s0.move === 'pull' ? zi < si : s0.move === 'push' ? zi > si : true; }) : null;
    const camY = G.solve(s0, plan0, hit.what === 'end' ? 1 : 0).pos[1];
    DRAG = { what: hit.what, move(ev) {
      const px = ev.clientX - box.left, py = ev.clientY - box.top;
      if (this.what === 'start' || this.what === 'end') {
        const at = ground(cam, px, py, w, h, camY), inv = G.fromGround(s0, plan0, at);
        let want = inv.az; while (want - az0 > 180) want -= 360; while (az0 - want > 180) want += 360;
        let patch, why = '', main;
        if (this.what === 'start' || s0.move === 'orbit') {
          const key = this.what === 'end' ? 'az2' : 'az', from = this.what === 'end' ? (s0.az2 ?? az0 + 70) : az0;
          const lo = this.what === 'end' ? room.azAll[0] - 60 : room.az[0], hi = this.what === 'end' ? room.azAll[1] + 60 : room.az[1];
          const step = ev.shiftKey ? 1 : 5;  // Shift: fine framing, 1° and any distance (grammar.js FINE)
          let a = Math.round(Math.min(hi, Math.max(lo, want)) / step) * step;
          if (want < lo - 3 || want > hi + 3) why = this.what === 'end' ? 'an orbit ends within 60° of the idiom\'s side range' : 'this idiom keeps the camera inside its side range';
          patch = { [key]: a };
          if (this.what === 'start' && s0.move === 'orbit' && s0.az2 != null) patch.az2 = s0.az2 + (a - az0);
          if (this.what === 'start') { patch.size = G.nearestSize(inv.H, room.sizes); patch.hk = ev.shiftKey ? fine(inv.H / G.FRAME_H[patch.size]) : undefined; }
          while (a !== from && !ctx.clear(id, patch)) { a += a > from ? -step : step; patch[key] = a; if (patch.az2 != null && key === 'az') patch.az2 = s0.az2 + (a - az0); why = 'further round, the set blocks the camera'; }
          if (!ctx.clear(id, patch)) { patch = { [key]: from }; why = 'the set blocks the camera here'; }
          main = `${id} ${this.what === 'end' ? 'orbit ends' : 'camera'} ${ctx.sideText(patch[key])}${patch.size ? ` · ${patch.size}${patch.hk ? ` ×${patch.hk.toFixed(2)}` : ''}` : ''}${ev.shiftKey ? ' (fine)' : ''}`;
        } else {
          const end = ends?.length ? G.nearestSize(inv.H, ends) : s0.end;
          patch = { end, hk2: ev.shiftKey ? fine(inv.H / G.FRAME_H[end]) : undefined }; if (!ctx.clear(id, patch)) { patch = {}; why = `${end} would put the camera in the set`; }
          main = `${id} ends on ${patch.end || s0.end}${patch.hk2 ? ` ×${patch.hk2.toFixed(2)} (fine)` : ''}`;
        }
        this.main = main; this.why = why;
        ctx.tx.live(S => ctx.patch(S, id, patch), main.replace(`${id} `, ''), why, ev);
      } else {
        const at = ground(cam, px, py, w, h, 0);
        if (this.what === 'actor' || this.what === 'partner') {
          const off = this.what === 'actor' ? back : 0;
          const want = [Math.round(at[0] / 0.05) * 0.05, Math.round((at[1] + off) / 0.05) * 0.05], ok = G.markOk([want[0], want[1] - off]);
          const mark = ok ? want.map(v => +v.toFixed(2)) : from, name = ctx.scene().cast[who]?.name || 'He';
          this.why = ok ? '' : `${name} has to stay on the dome floor, clear of the console`;
          this.main = `${shared ? '' : id + ' '}${name}'s mark (${mark[0].toFixed(2)}, ${mark[1].toFixed(2)}) m from the station${shared ? ' for every shot of the scene' : ''}`;
          ctx.tx.live(S => setMark(S, mark), `${name} ${mark[0].toFixed(2)}, ${mark[1].toFixed(2)}`, this.why, ev);
        } else {
          const yaw = Math.atan2(at[0] - A0.root[0], at[1] - A0.root[2]) * 180 / Math.PI, baseYaw = A0.yaw * 180 / Math.PI - turn0;
          let turn = Math.round((yaw - baseYaw) / 15) * 15; turn = ((turn + 540) % 360) - 180;
          this.main = `${id} turned ${turn > 0 ? '+' : ''}${turn}° from his blocking`; this.why = '';
          ctx.tx.live(S => { (S.beats[id] ||= {}).turn = turn; }, `facing ${turn > 0 ? '+' : ''}${turn}°`, '', ev);
        }
      }
    } };
    ctx.tx.begin('overhead'); e.preventDefault();
  });
  window.addEventListener('pointermove', e => { if (DRAG) DRAG.move(e); });
  const end = ok => { if (!DRAG) return; const d = DRAG; DRAG = null; ctx.tx.end(ok && !!d.main, d.main, d.why); };
  window.addEventListener('pointerup', () => end(true));
  window.addEventListener('blur', () => end(false));
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && DRAG) { e.preventDefault(); end(false); } });
  document.addEventListener('pointermove', e => {  // a pointer cursor over anything draggable
    if (DRAG || e.target !== canvas) return;
    const { r: box } = size(), x = e.clientX - box.left, y = e.clientY - box.top;
    canvas.style.cursor = hits.some(o => Math.hypot(o.at[0] - x, o.at[1] - y) <= o.r) ? 'grab' : 'default';
  });
}
