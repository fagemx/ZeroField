// Shot Grammar prototype UI (SPEC_09). Five screens share one state, one history and one way of changing things:
// drag with a live preview, apply on release, Esc cancels, every change says what it did, Ctrl+Z undoes it.
// Plain DOM; product integration would move this into PrevisStage.
import * as THREE from 'three';
import { buildStage, prepareRenderer, shotGuides } from '../../src/previs/scene.js';
import { setPx } from '../../src/previs/board.js';
import { FPS, HEIGHT, WIDTH, framesOf } from '../../src/previs/plan.js';
import * as G from './grammar.js';
import * as P from './perf.js';
import { bindTimeline, movePlayhead, renderTimeline } from './timeline.js';
import { bindCurve, renderCurve } from './curve.js';
import { bindOverlay, drawOverlay, mountOverlay } from './overhead.js';
import { bindTrack, moveTrackHead, renderTrack } from './perftrack.js';

const $ = id => document.getElementById(id);
const $$ = sel => [...document.querySelectorAll(sel)];
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = v => (Math.round(v * 10) / 10).toFixed(1);
const ROUTES = ['scene', 'shot', 'overhead', 'templates', 'export'];
const COST = { render: 'Re-renders the previs', repick: 'Re-picks idioms', text: 'Text only' };
const cost = k => `<span class="cost ${k}" title="${COST[k]}">${COST[k].toLowerCase()}</span>`;

/* ---------- state and history: every entry carries the sentence that described it (R4, R5) ---------- */
const STORE = 'zf.shotGrammar.v2';
const DEF = { preset: 'standard', rules: {}, seed: 7, mood: 'grey', beats: {}, pins: {}, over: {}, custom: {}, sceneTemplates: [], perf: {}, sheet: {} };
const clone = o => JSON.parse(JSON.stringify(o));
function load() { try { return { ...clone(DEF), ...(JSON.parse(localStorage.getItem(STORE) || 'null') || {}) }; } catch { return clone(DEF); } }
let S = load();
const HIST = { list: [{ json: JSON.stringify(S), msg: '' }], at: 0 };
function save(json) { try { localStorage.setItem(STORE, json); } catch { /* private window: this session only */ } }
function commit(msg) {
  const json = JSON.stringify(S);
  if (json !== HIST.list[HIST.at].json) { HIST.list = HIST.list.slice(0, HIST.at + 1).concat({ json, msg }).slice(-80); HIST.at = HIST.list.length - 1; save(json); }
  refresh(); if (msg) say(msg);
}
function travel(step) {
  const at = HIST.at + step; if (at < 0 || at >= HIST.list.length) return;
  const msg = (step < 0 ? HIST.list[HIST.at] : HIST.list[at]).msg;
  HIST.at = at; S = JSON.parse(HIST.list[at].json); save(HIST.list[at].json);
  if (S.mood !== stageMood || S.look !== stageLook) buildSet();
  refresh(); say(`${step < 0 ? 'Undone' : 'Redone'}${msg ? ': ' + msg.replace(/^Applied: /, '').replace(/\. Ctrl\+Z.*$/, '') : ''}.`);
}
const UI = { route: 'scene', sel: G.sceneOf(S).beats[0].id, t: 0, frame: 'start', playing: null, speed: 1, loop: false, limit: '', scale: null,
  key: null, writing: null, pending: null };  // key: the selected performance key; pending: model versions waiting to be applied

/* ---------- one change at a time: live preview, apply on release, Esc cancels (R3, R5) ---------- */
const TX = {
  cur: null,
  begin(kind) { this.cur = { kind, base: clone(S), rows: ROWS }; },
  live(mutate, tip, why, ev) {
    if (!this.cur) return;
    S = clone(this.cur.base); mutate(S); plan(false); UI.limit = why || '';
    liveRender(); const text = typeof tip === 'function' ? tip() : tip; if (text || why) showTip(text, why, ev);
  },
  end(ok, main, why, self) {
    const c = this.cur; this.cur = null; hideTip(); UI.limit = '';
    if (!c) return;
    if (!ok || JSON.stringify(S) === JSON.stringify(c.base)) { S = c.base; refresh(); if (why && ok) say(`<span class="lim">${esc(why)}</span>`); return; }
    plan(); const fx = G.pickChanges(c.rows, ROWS).filter(x => x.id !== self).sort((a, b) => main.startsWith(b.id) - main.startsWith(a.id));  // the touched beat first
    commit(`Applied: ${esc(main)}${fx.length ? '; ' + fx.map(x => `${x.id} now uses “${esc(x.to)}”${x.quota ? ' (the scene ran out of anchor breaks)' : ''}`).join('; ') : ''}${why ? `; <span class="lim">${esc(why)}</span>` : ''}. Ctrl+Z undoes it.`);
  },
  once(main, mutate, self) { this.begin('once'); this.live(mutate); this.end(true, main, '', self); },
};
// Set framing overrides on the idiom a beat uses; a framed shot keeps its idiom (R8: what you set stays).
function patch(St, id, p) {
  const name = rowOf(id).pick.idiom.name; St.pins[id] = name;
  const o = ((St.over[id] ||= {})[name] ||= {});
  for (const [k, v] of Object.entries(p)) if (v === undefined) delete o[k]; else o[k] = v;
}

/* ---------- feedback ---------- */
let sayT = 0;
function say(html) {
  $('sayText').innerHTML = html; $('say').hidden = false;
  clearTimeout(sayT); sayT = setTimeout(() => { if (!$('say').matches(':hover')) $('say').hidden = true; }, 12000);
}
function showTip(text, why, ev) {
  const t = $('tip'); t.innerHTML = `${esc(text || '')}${why ? `${text ? ' · ' : ''}<span class="lim">${esc(why)}</span>` : ''}`; t.hidden = false;
  if (ev) { t.style.left = `${Math.min(innerWidth - t.offsetWidth - 8, ev.clientX + 14)}px`; t.style.top = `${Math.max(8, ev.clientY - 34)}px`; }
}
const hideTip = () => { $('tip').hidden = true; };

/* ---------- stage: one live renderer that moves between viewports, one for stills ---------- */
const D2R = Math.PI / 180;
const live = document.createElement('canvas'); live.className = 'live'; live.setAttribute('aria-label', '3D stage');
const renderer = prepareRenderer(new THREE.WebGLRenderer({ canvas: live, antialias: true }));
renderer.setSize(WIDTH, HEIGHT, false);
const stills = prepareRenderer(new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true }));
stills.setSize(640, 352, false);
const top = new THREE.PerspectiveCamera(42, WIDTH / HEIGHT, 0.1, 100);
top.position.set(0, 12.5, -2.2); top.up.set(0, 0, 1); top.lookAt(0, 0, -2.2);
const lensCam = new THREE.PerspectiveCamera(35, WIDTH / HEIGHT, 0.05, 200);
let stage = null, stageMood = null, stageLook = null, solids = [], guides = null;
const ray = new THREE.Raycaster(), va = new THREE.Vector3(), vb = new THREE.Vector3();
function buildSet() {
  stage?.dispose();
  stage = buildStage({ set: 'observatory', mood: S.mood, lens: 35 }, { board: S.look !== 'render' }); stageMood = S.mood; stageLook = S.look;
  solids = []; stage.scene.traverse(o => { if (o.isMesh && !o.userData.actor && !o.userData.roof && o.material.isMeshLambertMaterial) solids.push(o); });
  guides = null; STILL.clear(); ROOM.clear();
}
// The cast at frame f: the plan carries marks, looks, the other people and the performance keys (SPEC_09 §8, SPEC_10),
// so this is exactly what Render previs plays.
function pose(plan, f) { stage.pose(f, plan); }
function blocked(pos, F) {  // something solid between the subject and the camera (consoles, glass posts)
  va.set(...F); vb.set(...pos).sub(va); const d = vb.length(); if (d < 0.06) return false;
  ray.set(va, vb.normalize()); ray.near = 0.03; ray.far = d;
  return ray.intersectObjects(solids, false).length > 0;
}
function aim(cam, s, plan, p) {
  const c = G.solve(s, plan, p);
  cam.fov = c.fov; cam.position.set(...c.pos); cam.up.set(0, 1, 0); cam.lookAt(...c.aim); cam.updateProjectionMatrix();
}
const STILL = new Map();
function still(r, p, s = r.pick.s) {
  const key = JSON.stringify([r.plan, s, p, S.mood]);
  if (STILL.has(key)) return STILL.get(key);
  pose(r.plan, p * (framesOf(r.plan) - 1)); stage.roof(true); if (guides) guides.group.visible = false;
  aim(lensCam, s, r.plan, p); setPx(lensCam, 352); stills.render(stage.scene, lensCam);
  const url = stills.domElement.toDataURL('image/jpeg', 0.82);
  if (STILL.size > 400) STILL.clear();
  STILL.set(key, url); return url;
}

/* ---------- the plan ---------- */
let ROWS = [], T0 = [], TOTAL = 0;
function plan(withGuides = true) {
  ROWS = G.choose(scene(), S, blocked);
  T0 = []; TOTAL = 0; for (const r of ROWS) { T0.push(TOTAL); TOTAL += r.beat.seconds; }
  if (!withGuides && guides) return;
  if (guides) { stage.scene.remove(guides.group); guides.dispose(); }
  guides = shotGuides(ROWS.map(r => ({ id: r.beat.id, plan: G.toPlan(r, S.mood), selected: r.beat.id === UI.sel })));
  stage.scene.add(guides.group);
}
const scene = () => G.sceneOf(S);
const rowIndex = id => ROWS.findIndex(r => r.beat.id === id);
const rowOf = id => ROWS[rowIndex(id)];
const sel = () => rowOf(UI.sel);
function at(t) {
  let i = ROWS.length - 1; while (i > 0 && t < T0[i]) i--;
  const r = ROWS[i]; return { r, i, p: Math.min(1, Math.max(0, (t - T0[i]) / r.beat.seconds)) };
}
const ROOM = new Map();  // the framing room is ~100 probes; overhead redraws it every frame while playing
function roomOf(r) {
  const key = JSON.stringify([r.plan, r.pick.idiom.name, r.pick.s]);
  if (!ROOM.has(key)) { if (ROOM.size > 200) ROOM.clear(); ROOM.set(key, G.roomOf(r.beat, r.pick.idiom, r.pick.s, blocked)); }
  return ROOM.get(key);
}
const clearWith = (id, p) => { const r = rowOf(id); return G.clear(G.effShot(r.beat, r.pick.idiom, { ...(S.over[id]?.[r.pick.idiom.name] || {}), ...p }), r.plan, blocked); };
const side = a => { const n = Math.round(((a + 540) % 360) - 180);
  return Math.abs(n) > 177 ? 'from behind' : Math.abs(n) < 3 ? 'from the front' : `${Math.abs(n)}° ${n > 0 ? 'left' : 'right'} of front`; };
const hasEnd = s => s.moving && ((s.end && s.end !== s.size) || s.move === 'orbit');
const frameP = (s, which) => (!s.moving ? 0.5 : which === 'end' ? 1 : 0.02);
const ends = s => { const room = roomOf(sel()); if (!room.ends) return null; const si = G.SIZES.indexOf(s.size);
  return room.ends.filter(z => { const zi = G.SIZES.indexOf(z); return si < 0 || zi < 0 || (s.move === 'pull' ? zi < si : s.move === 'push' ? zi > si : true); }); };

/* ---------- live drawing (Shot and Overhead) ---------- */
function draw() {
  if (UI.route !== 'shot' && UI.route !== 'overhead') return;
  const { r, p } = at(UI.t), f = p * (framesOf(r.plan) - 1);
  pose(r.plan, f);
  if (UI.route === 'shot') {
    aim(stage.camera, r.pick.s, r.plan, p); stage.roof(true); guides.group.visible = false;
    setPx(stage.camera, HEIGHT); renderer.render(stage.scene, stage.camera);
  } else {
    stage.roof(false); guides.group.visible = true; guides.update(p, 1.3);
    setPx(top, HEIGHT); renderer.render(stage.scene, top);
    aim(lensCam, r.pick.s, r.plan, p); stage.roof(true); guides.group.visible = false;
    setPx(lensCam, 352); stills.render(stage.scene, lensCam);
    $('lensMini').getContext('2d').drawImage(stills.domElement, 0, 0, 640, 352);
    drawOverlay(ctx);
  }
  const view = $(UI.route === 'shot' ? 'v-shot' : 'v-overhead');
  const set = (k, v) => view.querySelectorAll(`[data-ov="${k}"]`).forEach(el => { el.textContent = v; });
  set('shot', `${r.beat.id} · ${r.beat.title} · ${r.pick.idiom.name}`);
  set('frame', UI.playing ? '' : hasEnd(r.pick.s) && r.beat.id === UI.sel ? (UI.frame === 'end' ? 'End frame' : 'Start frame') : '');
  set('words', G.words(r.pick.s)); set('limit', UI.limit);
  set('time', `${fmt(UI.t)} / ${fmt(TOTAL)} s · ${r.beat.id} frame ${Math.round(f)}`);
  movePlayhead(document, ctx); moveTrackHead(ctx);
  $('vpShot').dataset.grab = String(UI.route === 'shot' && !UI.playing);
}

/* ---------- header ---------- */
function seg(id, items, cur, attr) { $(id).innerHTML = items.map(([v, l]) => `<button type="button" data-${attr}="${v}" aria-pressed="${v === cur}">${esc(l)}</button>`).join(''); }
function renderHeader() {
  $('sceneTitle').textContent = scene().title;
  seg('scenes', Object.values(G.SCENES).map(c => [c.id, Object.values(c.cast).map(x => x.name).join(' & ')]), scene().id, 'scenepick');
  const two = !!scene().blocking, side = S.side?.[scene().id] || 1, [a, b] = Object.values(scene().cast).map(x => x.name);
  $('lineSide').hidden = !two;
  if (two) seg('lineSides', [[1, `${b}'s right`], [-1, `${b}'s left`]], side, 'lineside');
  $$('#lineSides button').forEach(x => { x.title = `Every shot keeps the camera on this side of the line from ${a} to ${b}`; });
  seg('presets', Object.entries(G.PRESETS).map(([k, p]) => [k, p.label + (k === S.preset && Object.keys(S.rules).length ? ' *' : '')]), S.preset, 'preset');
  $$('#presets button').forEach(b => { b.title = G.PRESETS[b.dataset.preset].desc; });
  seg('moods', [['grey', 'Grey'], ['night', 'Night']], S.mood, 'mood');
  seg('looks', [['board', 'Board'], ['render', 'Render']], S.look === 'render' ? 'render' : 'board', 'look');
  $$('#looks button').forEach(b => { b.title = b.dataset.look === 'board' ? 'Each person in their own colour with outlines, on a bright set: for blocking' : 'Exactly what Render previs sends to LTX: the grey look the Layout Render was validated on'; });
  $('undo').disabled = HIST.at === 0; $('redo').disabled = HIST.at >= HIST.list.length - 1;
  $('undo').title = HIST.at ? `Undo: ${HIST.list[HIST.at].msg.replace(/<[^>]+>/g, '').replace(/^Applied: /, '')}` : 'Nothing to undo';
  $$('nav a').forEach(a => a.setAttribute('aria-current', a.dataset.route === UI.route ? 'page' : 'false'));
  $$('[data-speed-pb]').forEach(b => b.setAttribute('aria-pressed', String(Number(b.dataset.speedPb) === UI.speed)));
  $('loop').checked = UI.loop;
}
const renderTimelines = () => $$(`#v-${UI.route} [data-timeline]`).forEach(el => renderTimeline(el, ctx));

/* ---------- Storyboard ---------- */
const frameTimes = s => (s.moving ? [0.02, 1] : [0.5]);
function renderScene() {
  renderTimelines();
  const flags = new Set(G.checks(ROWS).filter(c => c.kind === 'warn').map(c => c.id));
  $('board').innerHTML = ROWS.map(r => { const s = r.pick.s, times = frameTimes(s);
    return `<button class="sb" data-open="${r.beat.id}" data-sel="${r.beat.id === UI.sel}" title="Frame ${r.beat.id}">
      <div class="frames ${times.length === 1 ? 'one' : ''}">${times.map((p, k) => `<figure><img alt="${r.beat.id} ${times.length > 1 ? (k ? 'end' : 'start') : ''} frame" src="${still(r, p)}"><figcaption>${times.length > 1 ? (k ? 'End · ' + (s.end || s.size) : 'Start · ' + s.size) : s.size}</figcaption></figure>`).join('')}</div>
      <div class="meta"><span><b>${r.beat.id}</b> ${esc(r.beat.title)} ${flags.has(r.beat.id) ? '<span class="flag">· check</span>' : ''}</span>
        <span>${esc(r.pick.idiom.name)} ${r.pinned ? '<span class="tag pin">pinned</span>' : '<span class="tag auto">auto</span>'} ${r.pick.idiom.drama ? '<span class="tag show">showpiece</span>' : ''} ${r.pick.idiom.mine ? '<span class="tag mine">mine</span>' : ''}</span>
        <span class="words">${esc(G.words(s))} · ${r.beat.seconds} s</span>
        <span class="hint">Performance ${(x => `<span class="tag ${x.source}">${SOURCE[x.source]}</span>${x.stale ? ' <span class="tag stale">out of date</span>' : ''}`)(perfRow(r))}</span></div></button>`; }).join('');
  $('writeAll').disabled = !!UI.writing; $('writeAll').textContent = UI.writing === 'scene' ? `Writing with ${MODEL.name}…` : 'Write the performances';
  $('checks').innerHTML = G.checks(ROWS).map(c => `<li data-kind="${c.kind}" ${c.id ? `data-open="${c.id}"` : ''}>${esc(c.text)}</li>`).join('');
}

/* ---------- Shot ---------- */
function renderFraming() {
  const r = sel(), s = r.pick.s, room = roomOf(r), az = s.az ?? room.az0, end = UI.frame === 'end' && hasEnd(s);
  const list = end ? (ends(s) || [s.end]) : room.sizes, cur = end ? s.end : s.size, i = list.indexOf(cur);
  const sizeCtl = s.move === 'orbit' && end ? `<span>Orbit ends ${side(s.az2 ?? az + 70)} <span class="hint">drag the end camera in Overhead</span></span>`
    : `<span class="row"><button data-size="${end ? 'end' : 'size'}" data-dir="-1" ${i <= 0 ? 'disabled' : ''}>Wider</button><b class="size" title="${G.SIZE_LABEL[cur]}">${cur}</b><button data-size="${end ? 'end' : 'size'}" data-dir="1" ${i < 0 || i >= list.length - 1 ? 'disabled' : ''}>Tighter</button></span>`;
  $('framing').innerHTML = `<b>Framing · ${r.beat.id}</b>
    ${hasEnd(s) ? `<span class="seg" role="group" aria-label="Frame to adjust"><button data-target="start" aria-pressed="${!end}">Start</button><button data-target="end" aria-pressed="${end}">End</button></span>` : ''}
    ${sizeCtl}
    <span class="row" title="Fine distance around ${cur}: 5% a click, up to halfway to the next size"><button data-fine="${end ? 'hk2' : 'hk'}" data-k="1.05" aria-label="A little wider">−</button><span class="hint">×${((end ? s.hk2 : s.hk) || 1).toFixed(2)}</span><button data-fine="${end ? 'hk2' : 'hk'}" data-k="0.952" aria-label="A little tighter">+</button></span>
    <span class="seg" role="group" aria-label="Height">${room.heights.map(h => `<button data-height="${h}" aria-pressed="${h === s.angle && s.elev == null}">${G.HEIGHT_LABEL[h]}</button>`).join('')}</span>${s.elev != null ? `<span class="hint">${Math.round(s.elev)}°</span>` : ''}
    <span>Side ${side(az)} <span class="hint">· room ${side(room.az[0])} to ${side(room.az[1])}</span></span>
    <span class="seg" role="group" aria-label="Lens">${[24, 35, 50, 85].map(l => `<button data-lens="${l}" aria-pressed="${l === s.lens}">${l}</button>`).join('')}</span>
    <button id="resetFrame" ${Object.keys(S.over[r.beat.id]?.[r.pick.idiom.name] || {}).length ? '' : 'disabled'} title="Back to the idiom's framing and timing">Reset to the idiom</button>
    ${cost('render')}<span class="hint">Drag the picture: left/right goes round him, up/down changes the height. Hold Shift to fine-tune (1°, any height); − / + nudge the distance.</span>`;
}
function renderMinis() {
  const r = sel(), s = r.pick.s, times = frameTimes(s);
  $('minis').innerHTML = times.map((p, k) => { const which = times.length > 1 ? (k ? 'end' : 'start') : 'start';
    return `<figure data-on="${times.length > 1 && UI.frame === which}"><button data-target="${which}" style="padding:0;border:0;background:none" title="Show the ${which} frame"><img alt="${which} frame" src="${still(r, p)}"></button>${times.length > 1 ? (k ? 'End' : 'Start') : 'Frame'} · ${k ? s.end || s.size : s.size}</figure>`; }).join('');
}
function renderInspector() {
  const r = sel(), b = r.beat, s = r.pick.s, b0 = scene().beats.find(x => x.id === b.id), mine = (S.custom[b.event] || []).length;
  const tags = c => [c === r.pick && !r.pinned ? '<span class="tag auto">auto</span>' : '', c === r.pick && r.pinned ? '<span class="tag pin">pinned</span>' : '',
    c.idiom.drama ? '<span class="tag show">showpiece</span>' : '', c.s.breaks ? '<span class="tag brk">anchor break</span>' : '', c.idiom.mine ? '<span class="tag mine">mine</span>' : ''].join('');
  const moved = (b.mark && (b.mark[0] || b.mark[1])) || b.turn;
  $('inspector').innerHTML = `
    <div class="card">
      <span class="label">${b.id} · ${esc(G.EVENTS[b.event])}</span><h4>${esc(b.title)}</h4>
      <div class="row"><span class="label">Tension</span><b>${b.tension.toFixed(2)}</b><span class="hint">drag its point on the timeline${Math.abs(b0.tension - b.tension) > 0.01 ? ` · script ${b0.tension.toFixed(2)}` : ''}</span>${cost('repick')}</div>
      <div class="row"><span class="label">Length</span><span class="seg">${G.DURATIONS.map(n => `<button data-sec="${n}" aria-pressed="${n === b.seconds}">${n} s</button>`).join('')}</span><span class="hint">or drag its edge</span>${cost('render')}</div>
      ${b.partner ? `<div class="row"><span class="label">Blocking</span><span>${esc(b.name)} at (${b.mark.map(v => v.toFixed(2)).join(', ')}) facing ${esc(b.partner.name)} at (${b.partner.mark.map(v => v.toFixed(2)).join(', ')})${b.turn ? `, turned ${b.turn}°` : ''}</span><span class="hint">drag either of them in Overhead: they move for the whole scene</span></div>`
      : `<div class="row"><span class="label">Blocking</span><span>${esc(b.action)}, facing ${esc(b.facing)}${moved ? ` · mark (${(b.mark || [0, 0]).map(v => v.toFixed(2)).join(', ')}) m, turned ${b.turn || 0}°` : ''}</span>${moved ? '<button id="resetMark">Back to the station</button>' : '<span class="hint">drag him in Overhead</span>'}</div>`}
    </div>
    <div class="card">
      <h3>Idiom ${cost('render')}</h3>
      <div class="chips">${r.cands.map(c => `<button class="chip" data-idiom="${esc(c.idiom.name)}" data-pick="${c === r.pick}" data-usable="${c.usable}" title="${esc(G.words(c.s))}">
        <span class="n">${esc(c.idiom.name)}</span><span class="tags">${tags(c)}</span>
        <span class="w">${esc(G.words(c.s))}</span>${c.usable ? '' : `<span class="why">${esc(c.why.text)}</span>`}</button>`).join('')}</div>
      ${r.pinned ? `<button id="unpin">Let the style choose again</button>` : `<p class="hint">Picked for tension ${b.tension.toFixed(2)} (target camera energy ${r.target.toFixed(2)}). Click another to pin it.</p>`}
    </div>
    ${s.moving ? `<div class="card"><h3>Move timing ${cost('render')}</h3><div id="curveHost"></div>
      <div class="row"><span class="label">Ending</span><span class="seg">${Object.keys(G.ENDINGS).map(v => `<button data-ending="${v}" aria-pressed="${v === s.ending}">${G.ENDING_LABEL[v]}</button>`).join('')}</span></div>
      <p class="hint">Drag the band to slide the move, its edges to start or stop it, the dot to move where it is half done. A short window is a fast move. Double-click to reset.</p></div>` : ''}
    <div class="card"><h3>Writes to Camera Motion ${cost('text')}</h3><div class="writes" id="writes">${esc(G.words(s))}</div></div>
    <div class="card" id="perfCard"></div>
    <div class="card"><h3>Save as an idiom</h3>
      <form class="row" id="saveIdiom"><input type="text" id="idiomName" maxlength="40" placeholder="Name, e.g. Slow push past his shoulder" aria-label="Idiom name" style="flex:1"><button type="submit">Save</button></form>
      <p class="hint">Keeps this shot's framing and timing as a ${esc(G.EVENTS[b.event])} idiom you can use on any beat${mine ? ` (you have ${mine})` : ''}.</p></div>`;
  if (s.moving) renderCurve($('curveHost'), s, T0[rowIndex(b.id)]);
  renderPerf();
}
function renderShot() { renderTimelines(); renderFraming(); renderMinis(); renderInspector(); renderTrack($('perfTrack'), ctx); }

/* ---------- Performance (SPEC_10): levels, the beat sheet and the local model that writes it ---------- */
const MODEL = { url: 'http://127.0.0.1:11434', name: 'qwen3.8:27b-16k' };
const WRITES = 'zf.shotGrammar.writes';  // what the model wrote, by beat and signature: levels written once come back free
const cache = {
  get(k) { try { return JSON.parse(localStorage.getItem(WRITES) || '{}')[k] || null; } catch { return null; } },
  put(k, v) { try { const all = JSON.parse(localStorage.getItem(WRITES) || '{}'); all[k] = v; localStorage.setItem(WRITES, JSON.stringify(all)); } catch { /* private window */ } },
};
const SOURCE = { template: 'from the idiom template', agent: 'written by the model', edited: 'edited by you' };
// Everything the performance of a row depends on. texts: one per segment (the template keys' own sentences when nobody wrote it).
function perfRow(r, St = S) {
  const b = r.beat, decl = P.perfOf(r.pick.idiom, b.event), L = P.levels(St.perf[b.id], decl), story = P.BEAT_STORY[b.id];
  const segs = P.segments(b.acts || story.acts, b.seconds), camera = G.words(r.pick.s), sig = P.sigOf(L, segs, camera);
  const sh = St.sheet[b.id], fits = !!sh && sh.texts.length === segs.length;
  return { b, decl, L, story, segs, camera, sig, source: fits ? sh.source : 'template', stale: !!sh && (!fits || sh.sig !== sig), lost: !!sh && !fits,
    texts: fits ? sh.texts : segs.map(g => g.text), sheet: fits ? P.writtenSheet(segs, sh.texts, story) : P.templateSheet(segs, L, story) };
}
const brief = x => ({ id: x.b.id, title: x.b.title, seconds: x.b.seconds, camera: x.camera, levelLines: P.levelLines(x.L), segs: x.segs, story: x.story, L: x.L,
  visible: `${x.b.name}: ${P.visibleOf(rowOf(x.b.id).pick.s)}${x.b.partner ? `; ${x.b.partner.name} is in the shot with ${x.b.name}` : ''}`, facing: facingOf(x) });
// Which way the subject faces the camera in each segment, from the previs (the 4090 scale test: without it the model
// turned a man seen from behind round to face the lens).
function facingOf(x) {
  const r = rowOf(x.b.id), n = framesOf(r.plan) - 1;
  return x.segs.map(g => { const u = (g.t0 + g.t1) / 2 / x.b.seconds, A = G.actorAt(r.plan, u * n), c = G.solve(r.pick.s, r.plan, u).pos;
    const v = [c[0] - A.root[0], c[2] - A.root[2]], cos = (A.fwd[0] * v[0] + A.fwd[2] * v[1]) / (Math.hypot(...v) || 1);
    return cos < -0.5 ? 'seen from behind' : cos > 0.5 ? 'seen from the front' : 'seen in profile'; });  // no camera words: the writer copies them
}
let abort = null;
async function ask(prompt) {
  const res = await fetch(MODEL.url + '/api/chat', { method: 'POST', signal: abort.signal, headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: MODEL.name, stream: false, think: false, format: 'json', keep_alive: '2m', options: { temperature: 0.8 },
      messages: [{ role: 'system', content: P.RULES }, { role: 'user', content: prompt }] }) });
  if (!res.ok) throw new Error(`${res.status} ${(await res.text()).slice(0, 140)}`);
  return (await res.json()).message?.content || '';
}
// keep_alive 0 hands the 4090 back to LTX as soon as the writing is done (the grader does the same).
const release = () => fetch(MODEL.url + '/api/generate', { method: 'POST', body: JSON.stringify({ model: MODEL.name, keep_alive: 0 }) }).catch(() => {});
async function run(what, job) {
  if (UI.writing) return;
  UI.writing = what; abort = new AbortController(); refreshPerf();
  try { await job(); } catch (e) {
    say(`<span class="lim">${abort.signal.aborted ? 'Stopped' : `The local model (${MODEL.name}) did not answer: ${esc(e.message)}`}; the performance text stays as it was.</span>`);
  } finally { UI.writing = null; abort = null; release(); refreshPerf(); }
}
const refreshPerf = () => { if (UI.route === 'shot') renderPerf(); if (UI.route === 'scene') renderScene(); };
function writeAll() {
  return run('scene', async () => {
    const xs = ROWS.map(r => perfRow(r)), todo = xs.filter(x => x.source !== 'edited'), kept = xs.length - todo.length;
    const t0 = performance.now(), out = await P.writeScene(scene(), todo.map(brief), ask);
    const ok = todo.filter(x => out[x.b.id].texts && !out[x.b.id].issues.length), bad = todo.filter(x => !ok.includes(x));
    for (const x of ok) cache.put(`${x.b.id}|${x.sig}`, out[x.b.id].texts);
    TX.once(`the model wrote the performances in ${Math.round((performance.now() - t0) / 1000)} s: ${ok.map(x => x.b.id).join(', ') || 'none'} passed the checks`
      + (bad.length ? `; ${bad.map(x => `${x.b.id} stays on the template (${out[x.b.id].issues[0] || 'no answer'})`).join('; ')}` : '')
      + (kept ? `; ${kept} beat${kept > 1 ? 's' : ''} you edited kept` : ''),
    St => { for (const x of ok) St.sheet[x.b.id] = { source: 'agent', texts: out[x.b.id].texts, sig: x.sig }; });
  });
}
function writeBeat(id, n) {
  return run(id, async () => {
    const x = perfRow(rowOf(id));
    const opts = n ? await P.writeVersions(scene(), brief(x), ask, n)
      : (o => (o?.texts ? [{ label: 'Rewritten', ...o }] : []))((await P.writeScene(scene(), [brief(x)], ask))[id]);
    if (!opts.length) return say(`<span class="lim">${id}: the model's answer did not have ${x.segs.length} segments; nothing changed.</span>`);
    UI.pending = { id, sig: x.sig, opts, at: Math.max(0, opts.findIndex(o => !o.issues.length)) };
  });
}
// A level change; when the model already wrote for the new levels, that text comes back from the cache.
function setLevel(id, key, value, main) {
  let back = false, stale = false, fit = null;
  const fit0 = perfRow(rowOf(id)).L.fit;
  TX.begin('perf');
  TX.live(St => {
    const p = (St.perf[id] ||= {});
    if (value == null || value === '' || (Array.isArray(value) && !value.length)) delete p[key]; else p[key] = value;
    const x = perfRow(rowOf(id), St), sh = St.sheet[id]; fit = key !== 'fit' && x.L.fit !== fit0 ? x.L : null;
    if (sh?.source === 'agent' && sh.sig !== x.sig) { const c = cache.get(`${id}|${x.sig}`); if (c?.length === x.segs.length) { St.sheet[id] = { source: 'agent', texts: c, sig: x.sig }; back = true; } else stale = true; }
  });
  TX.end(true, `${id} ${main}${fit ? `; fit ${fit.fitAuto ? 'relaxes' : 'goes back'} to ${P.FITS[fit.fit].label.toLowerCase()} (${P.FITS[fit.fit].lane}) because the performance is ${fit.fitAuto ? 'bigger than' : 'back within'} what the previs is blocked for` : ''}${back ? '; the text the model wrote for these levels came back' : stale ? '; the written performance is out of date (Rewrite)' : ''}`, '', id);
}
function renderPerf() {
  const host = $('perfCard'); if (!host) return;
  const r = sel(), id = r.beat.id, x = perfRow(r), { L, decl } = x, busy = UI.writing, pend = UI.pending?.id === id ? UI.pending : null;
  const up = (list, v, top) => list.indexOf(v) > list.indexOf(top);
  const lv = (key, list, labels, cur, beyond) => `<span class="seg" role="group" aria-label="${key}">${list.map(v => `<button data-lv="${key}" data-v="${v}" aria-pressed="${v === cur}"
    ${beyond(v) ? 'data-beyond="true" title="Bigger than this idiom\'s previs is blocked for"' : ''}>${esc(labels[v])}</button>`).join('')}</span>`;
  const issues = x.source === 'template' ? [] : P.issueList(P.checkPerformance(x.texts, { segs: x.segs, L, story: x.story, line: x.story.line?.text, facing: facingOf(x) }));
  const tag = `<span class="tag ${x.source}">${SOURCE[x.source]}</span>${x.stale ? '<span class="tag stale" title="Levels, framing or timing changed since it was written">out of date</span>' : ''}`;
  const cmp = pend ? pend.opts[pend.at] : null;
  host.innerHTML = `<h3>Performance ${cost('text')}</h3>
    <p class="hint">${esc(decl.way[0].toUpperCase() + decl.way.slice(1))}: the idiom plays it ${decl.scale}, ${{ face: 'face only', upper: 'upper body', full: 'full body' }[decl.body]}; the previs is blocked for up to ${decl.range[1]}.</p>
    <div class="row"><span class="label">Scale</span>${lv('scale', P.SCALES, P.SCALE_LABEL, L.scale, v => up(P.SCALES, v, decl.range[1]))}</div>
    <div class="row"><span class="label">Body</span>${lv('body', P.BODIES, P.BODY_LABEL, L.body, v => up(P.BODIES, v, decl.body))}</div>
    <div class="row"><span class="label">Colour</span><span class="seg" role="group" aria-label="colour"><button data-lv="color" data-v="" aria-pressed="${!L.color}">None</button>${Object.entries(P.COLORS).map(([k, c]) => `<button data-lv="color" data-v="${k}" aria-pressed="${k === L.color}">${c.label}</button>`).join('')}</span></div>
    <div class="row"><span class="label">Carried by</span><span class="seg" role="group" aria-label="focus">${Object.entries(P.FOCUS).map(([k, l]) => `<button data-focus="${k}" aria-pressed="${L.focus.includes(k)}">${l}</button>`).join('')}</span></div>
    <div class="row"><span class="label">Note</span><input type="text" id="perfNote" maxlength="80" value="${esc(L.note)}" placeholder="One line for the actor, e.g. he has waited three years for this" style="flex:1"></div>
    <div class="row"><span class="label">Fit</span><span class="seg" role="group" aria-label="fit"><button data-fit="" aria-pressed="${!S.perf[id]?.fit}" title="Follow the previs pose unless the performance is bigger than the previs is blocked for">Auto</button>${Object.entries(P.FITS).map(([k, f]) => `<button data-fit="${k}" aria-pressed="${k === S.perf[id]?.fit}">${f.label}</button>`).join('')}</span>${cost('render')}</div>
    <p class="hint">${S.perf[id]?.fit ? '' : `Auto: ${esc(P.FITS[L.fit].label.toLowerCase())} · `}${esc(P.FITS[L.fit].lane)}${L.fitAuto ? ` · <span style="color:var(--warn)">relaxed from “follow the pose” because ${L.scale !== decl.scale && up(P.SCALES, L.scale, decl.range[1]) ? `${L.scale} is bigger than the previs is blocked for` : 'the body range is bigger than the previs'}</span>` : ''}</p>
    <div class="row"><span class="label">Beat sheet</span>${tag}</div>
    ${x.lost ? `<p class="hint" style="color:var(--warn)">Your text had ${S.sheet[id].texts.length} segments; the keys now cut ${x.segs.length}, so the template shows. Rewrite it or go back to the template.</p>` : ''}
    <div class="segs">${x.segs.map((g, i) => `<label class="sg"><span class="t">${fmt(g.t0)}–${fmt(g.t1)} s</span><textarea data-seg="${i}" rows="2" aria-label="Segment ${i + 1}">${esc(x.texts[i])}</textarea></label>`).join('')}</div>
    ${issues.length ? `<ul class="issues">${issues.map(m => `<li>${esc(m)}</li>`).join('')}</ul>` : ''}
    ${pend ? `<div class="pend"><div class="row"><b>The model's ${pend.opts.length > 1 ? 'versions' : 'rewrite'}</b>${pend.opts.length > 1 ? `<span class="seg">${pend.opts.map((o, k) => `<button data-pv="${k}" aria-pressed="${k === pend.at}">${esc(o.label || `Version ${k + 1}`)}${o.issues.length ? ' ⚠' : ''}</button>`).join('')}</span>` : ''}</div>
      ${pend.sig !== x.sig ? '<p class="hint" style="color:var(--warn)">Written before your last change; it may not fit the levels now.</p>' : ''}
      <div class="cmp">${x.segs.map((g, i) => `<div><span class="t">${fmt(g.t0)}–${fmt(g.t1)} s</span><p class="now">${esc(x.texts[i])}</p><p class="new">${esc(cmp.texts[i] ?? '')}</p></div>`).join('')}</div>
      ${cmp.issues.length ? `<ul class="issues">${cmp.issues.map(m => `<li>${esc(m)}</li>`).join('')}</ul>` : ''}
      <div class="row"><button data-pvapply ${cmp.issues.length || cmp.texts.length !== x.segs.length ? 'disabled' : ''}>Apply</button><button data-pvdrop>Discard</button><span class="hint">grey: now · white: the model's</span></div></div>` : ''}
    <div class="row">${busy ? `<span class="hint">${busy === 'scene' ? 'Writing the scene' : `Writing ${busy}`} with ${MODEL.name}…</span><button data-pstop>Stop</button>`
      : `<button data-pwrite="1">Rewrite this beat</button><button data-pwrite="3">Write 3 versions</button>`}
      <button data-ptemplate ${x.source === 'template' && !x.lost ? 'disabled' : ''}>Back to the template</button></div>
    <span class="label">Writes to Action &amp; Audio Prompt</span><div class="writes pre">${esc(x.sheet)}</div>`;
}

/* ---------- Overhead ---------- */
function renderOverhead() {
  renderTimelines();
  $('shotlist').innerHTML = ROWS.map(r => `<button data-pick-beat="${r.beat.id}" data-sel="${r.beat.id === UI.sel}"><b>${r.beat.id} · ${esc(r.pick.idiom.name)}</b><span>${esc(G.words(r.pick.s))}</span></button>`).join('');
}

/* ---------- Templates: styles, scene templates, idioms ---------- */
function renderTemplates() {
  const P = G.rulesOf(S);
  const styles = Object.entries(G.PRESETS).map(([k, p]) => `<div class="tcard" data-on="${k === S.preset}"><div class="meta"><b>${esc(p.label)}</b><span class="hint">${esc(p.desc)}</span>
    <button data-preset="${k}" ${k === S.preset ? 'disabled' : ''}>${k === S.preset ? 'In use' : 'Use this style'}</button></div></div>`).join('');
  const rules = Object.entries(G.RULES).map(([k, d]) => `<label><span>${esc(d.label)}<br><span class="hint">${esc(d.hint)}</span></span>
    <input type="range" data-rule="${k}" min="${d.min}" max="${d.max}" step="${d.step}" value="${P[k]}"><output>${P[k]}</output></label>`).join('');
  const scenes = G.sceneTemplatesFor(S).map(t => `<div class="tcard"><div class="meta"><b>${esc(t.name)} ${t.mine ? '<span class="tag mine">mine</span>' : ''}</b><span class="hint">${esc(t.desc || '')}</span>
    <ul>${Object.entries(t.picks).map(([ev, n]) => `<li>${esc(G.EVENTS[ev])}: ${esc(n)}</li>`).join('')}</ul>
    <div class="row"><button data-apply-scene="${esc(t.name)}">Apply to the scene</button>${t.mine ? `<button data-del-scene="${esc(t.name)}">Delete</button>` : ''}</div></div></div>`).join('');
  const idioms = Object.keys(G.IDIOMS).map(event => {
    const r = ROWS.find(x => x.beat.event === event);
    return `<div class="tset"><h3>${esc(G.EVENTS[event])} <span class="hint">${r ? `shown on ${r.beat.id} · ${esc(r.beat.title)}` : 'not used in this scene'}</span></h3><div class="tgrid">${G.idiomsFor(S, event).map(idiom => {
      const c = r?.cands.find(x => x.idiom.name === idiom.name), s = c?.s, times = s ? frameTimes(s) : [];
      return `<div class="tcard" data-on="${r?.pick.idiom.name === idiom.name}">
        ${c?.usable ? `<div class="frames ${times.length === 1 ? 'one' : ''}">${times.map(p => `<figure><img alt="" src="${still(r, p, s)}"></figure>`).join('')}</div>` : ''}
        <div class="meta"><b>${esc(idiom.name)} ${idiom.drama ? '<span class="tag show">showpiece</span>' : ''} ${idiom.mine ? '<span class="tag mine">mine</span>' : ''}</b>
          <span class="words">${esc(G.words(s || G.effShot({ seconds: 4 }, idiom)))}</span>
          ${c && !c.usable ? `<span class="hint" style="color:var(--warn)">${esc(c.why.text)} on ${r.beat.id}</span>` : ''}
          <div class="row">${r && c?.usable ? `<button data-use="${esc(idiom.name)}" data-for="${r.beat.id}" ${r.pick.idiom.name === idiom.name ? 'disabled' : ''}>${r.pick.idiom.name === idiom.name ? `Used on ${r.beat.id}` : `Use on ${r.beat.id}`}</button>` : ''}
          ${idiom.mine ? `<button data-del-idiom="${esc(idiom.name)}" data-event="${event}">Delete</button>` : ''}</div></div></div>`; }).join('')}</div></div>`;
  }).join('');
  $('templates').innerHTML = `
    <div class="tset"><h3>Styles <span class="hint">how every unpinned beat picks ${cost('repick')}</span></h3><div class="tgrid">${styles}</div>
      <details ${Object.keys(S.rules).length ? 'open' : ''}><summary>Rules behind the style${Object.keys(S.rules).length ? ' (edited)' : ''}</summary><div class="card rules">${rules}
        <div class="row"><button id="resetRules" ${Object.keys(S.rules).length ? '' : 'disabled'}>Back to the style's rules</button></div></div></details></div>
    <div class="tset"><h3>Scene templates <span class="hint">one idiom per event, pinned on every beat ${cost('render')}</span></h3><div class="tgrid">${scenes}</div>
      <form class="row" id="saveScene"><input type="text" id="sceneName" maxlength="40" placeholder="Save this scene's shots as…" aria-label="Scene template name" style="flex:1;max-width:420px"><button type="submit">Save scene template</button></form></div>
    ${idioms}`;
}

/* ---------- Export ---------- */
function renderExport() {
  $('export').innerHTML = ROWS.map(r => { const s = r.pick.s, p = G.toPlan(r, S.mood), moved = 'mark' in p, x = perfRow(r);
    return `<div class="exp-card"><img alt="${r.beat.id}" src="${still(r, frameTimes(s).slice(-1)[0])}">
      <div style="display:grid;gap:8px;min-width:0"><b>${r.beat.id} · ${esc(r.beat.title)} · ${esc(r.pick.idiom.name)}</b>
        <span class="label">Camera Motion</span><div class="writes">${esc(G.words(s))}</div>
        <span class="label">Action &amp; Audio Prompt · <span class="tag ${x.source}">${SOURCE[x.source]}</span>${x.stale ? ' <span class="tag stale">out of date</span>' : ''}</span><div class="writes pre">${esc(x.sheet)}</div>
        <div class="row"><button data-copy="motion" data-for="${r.beat.id}">Copy Camera Motion</button><button data-copy="action" data-for="${r.beat.id}">Copy Action &amp; Audio Prompt</button><button data-copy="plan" data-for="${r.beat.id}">Copy 3D Stage plan</button><span class="hint">${r.beat.seconds} s = ${framesOf(r.plan)} frames · 17 camera keys</span></div>
        <pre>${esc(JSON.stringify(p))}</pre></div></div>`; }).join('');
}

/* ---------- routing and refresh ---------- */
function liveRender() {
  renderTimelines();
  if (UI.route === 'shot') {
    renderFraming(); renderTrack($('perfTrack'), ctx); renderPerf(); const s = sel().pick.s; $('writes') && ($('writes').textContent = G.words(s));
    if (s.moving && $('curveHost')) renderCurve($('curveHost'), s, T0[rowIndex(UI.sel)]);
    if (!UI.playing) seekFrame();
  }
  draw();
}
function refresh() {
  plan(); renderHeader();
  ({ scene: renderScene, shot: renderShot, overhead: renderOverhead, templates: renderTemplates, export: renderExport })[UI.route]();
  draw();
}
function route() {
  const want = location.hash.slice(1);
  UI.route = ROUTES.includes(want) ? want : 'scene';
  for (const k of ROUTES) $(`v-${k}`).hidden = k !== UI.route;
  if (UI.route === 'shot') $('vpShot').prepend(live);
  if (UI.route === 'overhead') { $('vpTop').prepend(live); mountOverlay($('vpTop')); }
  if (UI.playing && UI.route !== 'shot' && UI.route !== 'overhead') stop();
  refresh();
}
window.addEventListener('hashchange', route);
// The player rests on the frame being adjusted: the start or the end of the selected shot.
function seekFrame() { const i = rowIndex(UI.sel), r = ROWS[i]; UI.t = T0[i] + Math.min(r.beat.seconds - 1e-3, frameP(r.pick.s, UI.frame) * r.beat.seconds); }
function select(id, seek = true) {
  if (UI.sel !== id) { UI.frame = 'start'; UI.key = null; }
  UI.sel = id; UI.limit = '';
  if (seek) seekFrame();
  refresh();
}

/* ---------- clicks ---------- */
document.addEventListener('click', e => {
  const el = e.target.closest('button, [data-open]'); if (!el || (el.type === 'submit' && el.form)) return;  // form buttons go to the submit handler
  const d = el.dataset, r = sel(), id = UI.sel;
  if (el.id === 'sayClose') { $('say').hidden = true; return; }
  if (d.preset) { const before = S.preset; return TX.once(`style ${G.PRESETS[before].label} → ${G.PRESETS[d.preset].label}`, St => { St.preset = d.preset; St.rules = {}; }); }
  if (d.mood) { S.mood = d.mood; buildSet(); return commit(`Applied: light ${d.mood}. Ctrl+Z undoes it.`); }
  if (d.look) { if ((S.look || 'board') === d.look) return; S.look = d.look; buildSet();
    return commit(`Applied: ${d.look === 'board' ? 'board look: each person in their own colour on a bright set (for blocking)' : 'render look: the grey previs LTX gets'}. Ctrl+Z undoes it.`); }
  if (d.scenepick) { if (d.scenepick === scene().id) return; const to = G.SCENES[d.scenepick];
    UI.sel = to.beats[0].id; UI.key = null; UI.pending = null; UI.frame = 'start'; UI.t = 0;
    return TX.once(`scene: ${to.title}`, St => { St.scene = to.id; }); }
  if (d.lineside) { const sc = scene(), v = Number(d.lineside); if (v === (S.side?.[sc.id] || 1)) return;
    return TX.once(`the camera moves to the other side of the 180° line for every shot of ${sc.title}`, St => { (St.side ||= {})[sc.id] = v; }); }
  if (d.open) { select(d.open); location.hash = 'shot'; return; }
  if (d.pickBeat) return select(d.pickBeat);
  if (el.id === 'reroll') return TX.once('re-rolled the ties between equally good idioms', St => { St.seed = (St.seed || 7) + 1; });
  if (el.id === 'undo') return travel(-1);
  if (el.id === 'redo') return travel(1);
  if (d.play) return togglePlay(d.play);
  if (d.frame) return stepFrame(Number(d.frame));
  if (d.speedPb) { UI.speed = Number(d.speedPb); return renderHeader(); }
  if (d.target) { UI.frame = d.target; seekFrame(); return renderShot(), draw(); }
  if (d.sec) { const from = r.beat.seconds, to = Number(d.sec); if (from !== to) TX.once(`${id} ${from} → ${to} s (scene ${TOTAL} → ${TOTAL - from + to} s)`, St => { (St.beats[id] ||= {}).seconds = to; }); return; }
  if (d.idiom) { if (d.idiom !== r.pick.idiom.name) TX.once(`${id} uses “${d.idiom}” (pinned)`, St => { St.pins[id] = d.idiom; }, id); return; }
  if (d.use) { TX.once(`${d.for} uses “${d.use}” (pinned)`, St => { St.pins[d.for] = d.use; }, d.for); return; }
  if (el.id === 'unpin') return TX.once(`${id} unpinned; the style picks again`, St => { delete St.pins[id]; });
  if (el.id === 'resetFrame') return TX.once(`${id} framing and timing back to “${r.pick.idiom.name}”`, St => { delete St.over[id]?.[r.pick.idiom.name]; });
  if (el.id === 'resetMark') return TX.once(`${id} back on his station`, St => { if (St.beats[id]) { delete St.beats[id].mark; delete St.beats[id].turn; } });
  if (el.id === 'resetRules') return TX.once(`rules back to the ${G.PRESETS[S.preset].label} style`, St => { St.rules = {}; });
  if (d.size) {
    const s = r.pick.s, key = d.size, list = key === 'end' ? (ends(s) || []) : roomOf(r).sizes, j = list.indexOf(s[key]) + Number(d.dir);
    if (!list[j]) return;
    if (!clearWith(id, { [key]: list[j] })) return say(`<span class="lim">${list[j]} would put the camera in the set</span>`);
    return TX.once(`${id} ${key === 'end' ? 'end' : 'start'} ${s[key]} → ${list[j]}`, St => patch(St, id, { [key]: list[j] }), id);
  }
  if (d.height) {
    if (!clearWith(id, { angle: d.height })) return say(`<span class="lim">${G.HEIGHT_LABEL[d.height]} would put the camera in the set</span>`);
    return TX.once(`${id} ${G.HEIGHT_LABEL[r.pick.s.angle].toLowerCase()} → ${G.HEIGHT_LABEL[d.height].toLowerCase()}`, St => patch(St, id, { angle: d.height, elev: undefined }), id);
  }
  if (d.fine) {
    const s = r.pick.s, key = d.fine, k0 = s[key] || 1, k = Math.round(Math.min(G.FINE.hk[1], Math.max(G.FINE.hk[0], k0 * Number(d.k))) * 100) / 100;
    if (k === k0) return say(`<span class="lim">fine distance stops at ×${k0.toFixed(2)}: past that it is the next shot size (Wider / Tighter)</span>`);
    if (!clearWith(id, { [key]: k })) return say('<span class="lim">that would put the camera in the set</span>');
    return TX.once(`${id} ${key === 'hk2' ? 'end' : 'start'} ${key === 'hk2' ? s.end : s.size} ×${k0.toFixed(2)} → ×${k.toFixed(2)} (${k > k0 ? 'wider' : 'tighter'}, fine)`, St => patch(St, id, { [key]: Math.abs(k - 1) < 0.005 ? undefined : k }), id);
  }
  if (d.lens) {
    if (!clearWith(id, { lens: Number(d.lens) })) return say(`<span class="lim">At ${d.lens}mm this framing needs more room than the dome has</span>`);
    return TX.once(`${id} lens ${r.pick.s.lens} → ${d.lens}mm (same shot size, camera ${Number(d.lens) > r.pick.s.lens ? 'farther' : 'closer'})`, St => patch(St, id, { lens: Number(d.lens) }), id);
  }
  if (d.ending) return TX.once(`${id} ending: ${G.ENDING_LABEL[d.ending].toLowerCase()}`, St => patch(St, id, { ending: d.ending }), id);
  if (d.lv) {
    const L = perfRow(r).L, cur = L[d.lv] || '', names = { scale: P.SCALE_LABEL, body: P.BODY_LABEL, color: Object.fromEntries(Object.entries(P.COLORS).map(([k, c]) => [k, c.label])) }[d.lv];
    if (d.v === cur) return;
    return setLevel(id, d.lv, d.v, `${d.lv === 'color' ? 'colour' : d.lv} ${(names[cur] || 'none').toLowerCase()} → ${(names[d.v] || 'none').toLowerCase()}`);
  }
  if (d.focus) { const f = perfRow(r).L.focus, on = f.includes(d.focus); return setLevel(id, 'focus', on ? f.filter(k => k !== d.focus) : [...f, d.focus], `${on ? 'no longer' : 'now'} carried by ${P.FOCUS[d.focus].toLowerCase()}`); }
  if ('fit' in d) { const cur = S.perf[id]?.fit || ''; if (d.fit === cur) return;
    const L = P.levels({ ...S.perf[id], fit: d.fit || undefined }, perfRow(r).decl);
    return setLevel(id, 'fit', d.fit, `fit: ${d.fit ? P.FITS[d.fit].label.toLowerCase() : `auto (${P.FITS[L.fit].label.toLowerCase()})`} → ${P.FITS[L.fit].lane}`); }
  if (d.pwrite) return writeBeat(id, d.pwrite === '3' ? 3 : 0);
  if ('pwriteall' in d) return writeAll();
  if ('pstop' in d) return abort?.abort();
  if ('ptemplate' in d) return TX.once(`${id} performance back to the idiom template`, St => { delete St.sheet[id]; });
  if (d.pv) { UI.pending.at = Number(d.pv); return renderPerf(); }
  if ('pvdrop' in d) { UI.pending = null; return renderPerf(); }
  if ('pvapply' in d) {
    const p = UI.pending, o = p.opts[p.at], x = perfRow(r); UI.pending = null;
    cache.put(`${id}|${x.sig}`, o.texts);
    return TX.once(`${id} performance: the model's ${p.opts.length > 1 ? `“${o.label}”` : 'rewrite'} applied`, St => { St.sheet[id] = { source: 'agent', texts: o.texts, sig: x.sig }; });
  }
  if (d.applyScene) {
    const t = G.sceneTemplatesFor(S).find(x => x.name === d.applyScene);
    return TX.once(`scene template “${t.name}”`, St => { for (const b of scene().beats) { const name = t.picks[b.event]; if (!name || !G.idiomsFor(St, b.event).some(i => i.name === name)) continue;
      St.pins[b.id] = name; if (t.over?.[b.event]) ((St.over[b.id] ||= {})[name] = clone(t.over[b.event])); } });
  }
  if (d.delScene) return TX.once(`deleted scene template “${d.delScene}”`, St => { St.sceneTemplates = St.sceneTemplates.filter(x => x.name !== d.delScene); });
  if (d.delIdiom) return TX.once(`deleted idiom “${d.delIdiom}”`, St => { St.custom[d.event] = (St.custom[d.event] || []).filter(x => x.name !== d.delIdiom);
    for (const k of Object.keys(St.pins)) if (St.pins[k] === d.delIdiom) delete St.pins[k]; });
  if (d.copy) { const x = rowOf(d.for); return copy(d.copy === 'plan' ? JSON.stringify(G.toPlan(x, S.mood)) : d.copy === 'action' ? perfRow(x).sheet : G.words(x.pick.s), el); }
  if (el.id === 'copyAll') return copy(JSON.stringify(Object.fromEntries(ROWS.map(x => [x.beat.id, { idiom: x.pick.idiom.name, cameraMotion: G.words(x.pick.s), actionAudioPrompt: perfRow(x).sheet, plan: G.toPlan(x, S.mood) }])), null, 1), el);
});
const uniqueName = (name, taken) => { let n = name, k = 2; while (taken.includes(n)) n = `${name} (${k++})`; return n; };
document.addEventListener('submit', e => {
  e.preventDefault();
  if (e.target.id === 'saveIdiom') {
    const r = sel(), raw = $('idiomName').value.trim() || `${r.pick.idiom.name} · ${r.beat.id}`;
    const name = uniqueName(raw, G.idiomsFor(S, r.beat.event).map(i => i.name)), idiom = G.idiomFromShot(name, r.pick.s);
    TX.once(`saved “${name}” as a ${G.EVENTS[r.beat.event]} idiom; ${r.beat.id} uses it`, St => { (St.custom[r.beat.event] ||= []).push(idiom); St.pins[r.beat.id] = name; }, r.beat.id);
  }
  if (e.target.id === 'saveScene') {
    const raw = $('sceneName').value.trim() || 'My scene', name = uniqueName(raw, G.sceneTemplatesFor(S).map(t => t.name));
    const picks = {}, ov = {};
    for (const r of ROWS) if (!picks[r.beat.event]) { picks[r.beat.event] = r.pick.idiom.name; const o = S.over[r.beat.id]?.[r.pick.idiom.name]; if (o && Object.keys(o).length) ov[r.beat.event] = clone(o); }
    TX.once(`saved the scene as template “${name}”`, St => { St.sceneTemplates.push({ name, desc: `Saved from ${scene().title}`, picks, over: ov }); });
  }
});
// Rules sliders: live while dragging, one history step on release.
document.addEventListener('input', e => {
  const k = e.target.dataset?.rule; if (!k) return;
  if (!TX.cur) TX.begin('rule');
  const v = Number(e.target.value); e.target.nextElementSibling.textContent = v;
  TX.live(St => { St.rules = { ...St.rules, [k]: v }; });
});
document.addEventListener('change', e => {
  const t = e.target, id = UI.sel;
  if (t.id === 'perfNote') return setLevel(id, 'note', t.value.trim(), t.value.trim() ? `note: “${t.value.trim()}”` : 'note cleared');
  if (t.dataset?.seg != null) {  // a segment typed by hand: the beat's text is now the director's, the model never overwrites it
    const x = perfRow(sel()), i = Number(t.dataset.seg), texts = x.texts.slice(); texts[i] = t.value.trim();
    if (texts[i] === x.texts[i]) return;
    return TX.once(`${id} segment ${i + 1} (${fmt(x.segs[i].t0)}–${fmt(x.segs[i].t1)} s) edited by you`, St => { St.sheet[id] = { source: 'edited', texts, sig: x.sig }; });
  }
  const k = t.dataset?.rule; if (!k || !TX.cur) return;
  TX.end(true, `${G.RULES[k].label.toLowerCase()} ${G.rulesOf(TX.cur.base)[k]} → ${e.target.value}`);
});
$('loop').addEventListener('change', e => { UI.loop = e.target.checked; });
async function copy(text, el) {
  const label = el.textContent;
  try { await navigator.clipboard.writeText(text); } catch { const ta = $('copybuf'); ta.value = text; ta.select(); document.execCommand('copy'); }
  el.textContent = 'Copied'; setTimeout(() => { el.textContent = label; }, 1200);
}

/* ---------- Shot: drag the camera round the subject, inside the idiom's room ---------- */
let drag = null;
live.addEventListener('pointerdown', e => {
  if (UI.route !== 'shot' || UI.playing || e.button !== 0) return;
  const r = sel(), room = roomOf(r);
  if (at(UI.t).r !== r) seekFrame();
  drag = { x: e.clientX, y: e.clientY, az: r.pick.s.az ?? room.az0, angle: r.pick.s.angle, elev: G.elevOf(r.pick.s), room, w: live.clientWidth, main: '', why: '' };
  TX.begin('frame'); live.setPointerCapture(e.pointerId);
});
live.addEventListener('pointermove', e => {
  if (!drag) return;
  const id = UI.sel, { room } = drag, want = drag.az + (e.clientX - drag.x) / drag.w * 120;  // the camera goes the way you drag; full width = 120°
  const step = e.shiftKey ? 1 : 5;  // Shift: fine framing (1°, any height)
  let az = Math.round(Math.min(room.az[1], Math.max(room.az[0], want)) / step) * step, why = '';
  if (want > room.az[1] + 3 || want < room.az[0] - 3) why = `side stops at ${side(want > room.az[1] ? room.az[1] : room.az[0])}: ${room.blockedAz.length ? 'further round, the set blocks the camera' : 'this idiom keeps the camera inside ±30°'}`;
  const idx = room.heights.map(h => G.HEIGHTS.indexOf(h)), hi = G.HEIGHTS.indexOf(drag.angle) + Math.round(-(e.clientY - drag.y) / 70);
  let angle = G.HEIGHTS[Math.min(Math.max(...idx), Math.max(Math.min(...idx), hi))];
  if (hi > Math.max(...idx) || hi < Math.min(...idx)) why = why || `height stops at ${G.HEIGHT_LABEL[angle].toLowerCase()}: this idiom allows ${room.heights.map(h => G.HEIGHT_LABEL[h].toLowerCase()).join(', ')}`;
  let elev;  // fine: any height between the idiom's lowest and highest, 0.25° per pixel
  if (e.shiftKey) { const lo = G.ELEV[room.heights[0]], up = G.ELEV[room.heights[room.heights.length - 1]], want = drag.elev - (e.clientY - drag.y) * 0.25;
    elev = Math.round(Math.min(up, Math.max(lo, want))); angle = G.nearestHeight(elev);
    if (want > up + 1 || want < lo - 1) why = why || `height stops at ${elev}°: this idiom allows ${lo}° to ${up}°`; }
  const p0 = () => ({ az, angle, elev });
  if (!clearWith(id, p0())) { angle = drag.angle; elev = undefined; }
  while (az !== drag.az && !clearWith(id, p0())) { az += az > drag.az ? -step : step; why = 'further round, the set blocks the camera'; }
  const high = elev != null ? `${elev}° ${elev >= 0 ? 'above' : 'below'} eye level` : G.HEIGHT_LABEL[angle].toLowerCase();
  drag.main = az === drag.az && angle === drag.angle && elev == null ? '' : `${id} camera ${side(az)}, ${high}${e.shiftKey ? ' (fine)' : ''}`; drag.why = why;
  TX.live(St => patch(St, id, { az, angle, elev }), `${side(az)} · ${high}`, why, e);
});
const endDrag = ok => { if (!drag) return; const d = drag; drag = null; TX.end(ok && !!d.main, d.main, d.why, UI.sel); };
live.addEventListener('pointerup', () => endDrag(true));
live.addEventListener('pointercancel', () => endDrag(false));
document.addEventListener('keydown', e => { if (e.key === 'Escape' && drag) { e.preventDefault(); endDrag(false); } });

/* ---------- playback ---------- */
function stop() { if (UI.playing) cancelAnimationFrame(UI.playing.raf); UI.playing = null; setPlayLabels(); }
function togglePlay(range) {
  if (UI.playing) { stop(); return draw(); }
  const i = rowIndex(UI.sel), from = range === 'shot' ? T0[i] : (UI.t >= TOTAL - 0.05 ? 0 : UI.t), to = range === 'shot' ? T0[i] + ROWS[i].beat.seconds : TOTAL;
  UI.t = from; UI.playing = { range, from, to, last: performance.now() };
  const tick = now => {
    const P = UI.playing; if (!P) return;
    UI.t += (now - P.last) / 1000 * UI.speed; P.last = now;
    if (UI.t >= P.to - 1e-3) { if (UI.loop) UI.t = P.from; else { UI.t = P.to - 1e-3; stop(); return draw(); } }
    const cur = at(UI.t).r.beat.id;
    if (cur !== UI.sel && P.range === 'scene') { UI.sel = cur; (UI.route === 'shot' ? renderShot : renderOverhead)(); }
    draw(); P.raf = requestAnimationFrame(tick);
  };
  setPlayLabels(); UI.playing.raf = requestAnimationFrame(tick);
}
function setPlayLabels() { $$('[data-play]').forEach(b => { b.textContent = UI.playing?.range === b.dataset.play ? 'Pause' : b.dataset.play === 'scene' ? 'Play scene' : 'Play shot'; }); }
function stepFrame(n) {
  if (UI.playing) stop();
  UI.t = Math.min(TOTAL - 1e-3, Math.max(0, UI.t + n / FPS)); UI.frame = null;
  const id = at(UI.t).r.beat.id; if (id !== UI.sel) { UI.sel = id; refresh(); } else draw();
}
document.addEventListener('keydown', e => {
  if (e.target.closest?.('input, textarea, select')) return;
  const playing = UI.route === 'shot' || UI.route === 'overhead';
  if (e.key === ' ' && playing) { e.preventDefault(); togglePlay('scene'); }
  if ((e.key === 'ArrowRight' || e.key === 'ArrowLeft') && playing && !e.target.closest('[role="slider"]')) { e.preventDefault(); stepFrame(e.key === 'ArrowRight' ? 1 : -1); }
  if (e.key === ']' || e.key === '[') { const n = ROWS[rowIndex(UI.sel) + (e.key === ']' ? 1 : -1)]; if (n) select(n.beat.id); }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); travel(e.shiftKey ? 1 : -1); }
});
$('say').addEventListener('mouseleave', () => { clearTimeout(sayT); sayT = setTimeout(() => { $('say').hidden = true; }, 4000); });

/* ---------- the context the components work through ---------- */
const ctx = {
  ui: UI, tx: TX, patch, topCamera: top, scene,
  rows: () => ROWS, t0: () => T0, total: () => TOTAL, state: () => S, row: sel, rowIndex,
  scale: () => UI.scale || TOTAL, freezeScale: v => { UI.scale = v; },
  room: roomOf, clear: clearWith, sideText: side,
  draw: () => draw(), say, select, seek(t, scrub) { if (UI.playing) stop(); UI.t = t; if (scrub) UI.frame = null; const id = at(t).r.beat.id; if (id !== UI.sel) { UI.sel = id; refresh(); } else draw(); },
};
bindTimeline(ctx); bindCurve(ctx); bindOverlay(ctx); bindTrack(ctx);

buildSet();
plan();
seekFrame();
route();
window.__shotGrammar = { get rows() { return ROWS; }, get state() { return S; }, get ui() { return UI; }, get history() { return HIST; } };  // console handle for checking the prototype
