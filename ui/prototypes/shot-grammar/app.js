// Shot Grammar prototype UI (SPEC_09). Five screens share one state, one history and one way of changing things:
// drag with a live preview, apply on release, Esc cancels, every change says what it did, Ctrl+Z undoes it.
// Plain DOM; product integration would move this into PrevisStage.
import * as THREE from 'three';
import { buildStage, prepareRenderer, shotGuides } from '../../src/previs/scene.js';
import { FPS, HEIGHT, WIDTH, framesOf } from '../../src/previs/plan.js';
import * as G from './grammar.js';
import { bindTimeline, movePlayhead, renderTimeline } from './timeline.js';
import { bindCurve, renderCurve } from './curve.js';
import { bindOverlay, drawOverlay, mountOverlay } from './overhead.js';

const $ = id => document.getElementById(id);
const $$ = sel => [...document.querySelectorAll(sel)];
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = v => (Math.round(v * 10) / 10).toFixed(1);
const ROUTES = ['scene', 'shot', 'overhead', 'templates', 'export'];
const COST = { render: 'Re-renders the previs', repick: 'Re-picks idioms', text: 'Text only' };
const cost = k => `<span class="cost ${k}" title="${COST[k]}">${COST[k].toLowerCase()}</span>`;

/* ---------- state and history: every entry carries the sentence that described it (R4, R5) ---------- */
const STORE = 'zf.shotGrammar.v2';
const DEF = { preset: 'standard', rules: {}, seed: 7, mood: 'grey', beats: {}, pins: {}, over: {}, custom: {}, sceneTemplates: [] };
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
  if (S.mood !== stageMood) buildSet();
  refresh(); say(`${step < 0 ? 'Undone' : 'Redone'}${msg ? ': ' + msg.replace(/^Applied: /, '').replace(/\. Ctrl\+Z.*$/, '') : ''}.`);
}
const UI = { route: 'scene', sel: G.SCENE.beats[0].id, t: 0, frame: 'start', playing: null, speed: 1, loop: false, limit: '', scale: null };

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
let stage = null, stageMood = null, solids = [], figure = null, guides = null;
const ray = new THREE.Raycaster(), va = new THREE.Vector3(), vb = new THREE.Vector3();
function buildSet() {
  stage?.dispose();
  stage = buildStage({ set: 'observatory', mood: S.mood, lens: 35 }); stageMood = S.mood;
  figure = stage.scene.children.find(o => o.isGroup && o.userData.actor);
  solids = []; stage.scene.traverse(o => { if (o.isMesh && !o.userData.actor && !o.userData.roof && o.material.isMeshLambertMaterial) solids.push(o); });
  guides = null; STILL.clear(); ROOM.clear();
}
// The previs mannequin at frame f, moved to the beat's mark and turned (the product plan has no mark yet: SPEC_09 §8).
function pose(plan, f) {
  stage.pose(f, plan);
  figure.position.x += plan.mark[0]; figure.position.z += plan.mark[1]; figure.rotation.y += plan.turn * D2R;
}
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
  aim(lensCam, s, r.plan, p); stills.render(stage.scene, lensCam);
  const url = stills.domElement.toDataURL('image/jpeg', 0.82);
  if (STILL.size > 400) STILL.clear();
  STILL.set(key, url); return url;
}

/* ---------- the plan ---------- */
let ROWS = [], T0 = [], TOTAL = 0;
function plan(withGuides = true) {
  ROWS = G.choose(G.SCENE, S, blocked);
  T0 = []; TOTAL = 0; for (const r of ROWS) { T0.push(TOTAL); TOTAL += r.beat.seconds; }
  if (!withGuides && guides) return;
  if (guides) { stage.scene.remove(guides.group); guides.dispose(); }
  guides = shotGuides(ROWS.map(r => ({ id: r.beat.id, plan: G.toPlan(r, S.mood), selected: r.beat.id === UI.sel })));
  stage.scene.add(guides.group);
}
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
    renderer.render(stage.scene, stage.camera);
  } else {
    stage.roof(false); guides.group.visible = true; guides.update(p, 1.3);
    renderer.render(stage.scene, top);
    aim(lensCam, r.pick.s, r.plan, p); stage.roof(true); guides.group.visible = false;
    stills.render(stage.scene, lensCam);
    $('lensMini').getContext('2d').drawImage(stills.domElement, 0, 0, 640, 352);
    drawOverlay(ctx);
  }
  const view = $(UI.route === 'shot' ? 'v-shot' : 'v-overhead');
  const set = (k, v) => view.querySelectorAll(`[data-ov="${k}"]`).forEach(el => { el.textContent = v; });
  set('shot', `${r.beat.id} · ${r.beat.title} · ${r.pick.idiom.name}`);
  set('frame', UI.playing ? '' : hasEnd(r.pick.s) && r.beat.id === UI.sel ? (UI.frame === 'end' ? 'End frame' : 'Start frame') : '');
  set('words', G.words(r.pick.s)); set('limit', UI.limit);
  set('time', `${fmt(UI.t)} / ${fmt(TOTAL)} s · ${r.beat.id} frame ${Math.round(f)}`);
  movePlayhead(document, ctx);
  $('vpShot').dataset.grab = String(UI.route === 'shot' && !UI.playing);
}

/* ---------- header ---------- */
function seg(id, items, cur, attr) { $(id).innerHTML = items.map(([v, l]) => `<button type="button" data-${attr}="${v}" aria-pressed="${v === cur}">${esc(l)}</button>`).join(''); }
function renderHeader() {
  $('sceneTitle').textContent = G.SCENE.title;
  seg('presets', Object.entries(G.PRESETS).map(([k, p]) => [k, p.label + (k === S.preset && Object.keys(S.rules).length ? ' *' : '')]), S.preset, 'preset');
  $$('#presets button').forEach(b => { b.title = G.PRESETS[b.dataset.preset].desc; });
  seg('moods', [['grey', 'Grey'], ['night', 'Night']], S.mood, 'mood');
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
        <span class="words">${esc(G.words(s))} · ${r.beat.seconds} s</span></div></button>`; }).join('');
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
    <span class="seg" role="group" aria-label="Height">${room.heights.map(h => `<button data-height="${h}" aria-pressed="${h === s.angle}">${G.HEIGHT_LABEL[h]}</button>`).join('')}</span>
    <span>Side ${side(az)} <span class="hint">· room ${side(room.az[0])} to ${side(room.az[1])}</span></span>
    <span class="seg" role="group" aria-label="Lens">${[24, 35, 50, 85].map(l => `<button data-lens="${l}" aria-pressed="${l === s.lens}">${l}</button>`).join('')}</span>
    <button id="resetFrame" ${Object.keys(S.over[r.beat.id]?.[r.pick.idiom.name] || {}).length ? '' : 'disabled'} title="Back to the idiom's framing and timing">Reset to the idiom</button>
    ${cost('render')}<span class="hint">Drag the picture: left/right goes round him, up/down changes the height.</span>`;
}
function renderMinis() {
  const r = sel(), s = r.pick.s, times = frameTimes(s);
  $('minis').innerHTML = times.map((p, k) => { const which = times.length > 1 ? (k ? 'end' : 'start') : 'start';
    return `<figure data-on="${times.length > 1 && UI.frame === which}"><button data-target="${which}" style="padding:0;border:0;background:none" title="Show the ${which} frame"><img alt="${which} frame" src="${still(r, p)}"></button>${times.length > 1 ? (k ? 'End' : 'Start') : 'Frame'} · ${k ? s.end || s.size : s.size}</figure>`; }).join('');
}
function renderInspector() {
  const r = sel(), b = r.beat, s = r.pick.s, b0 = G.SCENE.beats.find(x => x.id === b.id), mine = (S.custom[b.event] || []).length;
  const tags = c => [c === r.pick && !r.pinned ? '<span class="tag auto">auto</span>' : '', c === r.pick && r.pinned ? '<span class="tag pin">pinned</span>' : '',
    c.idiom.drama ? '<span class="tag show">showpiece</span>' : '', c.s.breaks ? '<span class="tag brk">anchor break</span>' : '', c.idiom.mine ? '<span class="tag mine">mine</span>' : ''].join('');
  const moved = (b.mark && (b.mark[0] || b.mark[1])) || b.turn;
  $('inspector').innerHTML = `
    <div class="card">
      <span class="label">${b.id} · ${esc(G.EVENTS[b.event])}</span><h4>${esc(b.title)}</h4>
      <div class="row"><span class="label">Tension</span><b>${b.tension.toFixed(2)}</b><span class="hint">drag its point on the timeline${Math.abs(b0.tension - b.tension) > 0.01 ? ` · script ${b0.tension.toFixed(2)}` : ''}</span>${cost('repick')}</div>
      <div class="row"><span class="label">Length</span><span class="seg">${G.DURATIONS.map(n => `<button data-sec="${n}" aria-pressed="${n === b.seconds}">${n} s</button>`).join('')}</span><span class="hint">or drag its edge</span>${cost('render')}</div>
      <div class="row"><span class="label">Blocking</span><span>${esc(b.action)}, facing ${esc(b.facing)}${moved ? ` · mark (${(b.mark || [0, 0]).map(v => v.toFixed(2)).join(', ')}) m, turned ${b.turn || 0}°` : ''}</span>${moved ? '<button id="resetMark">Back to the station</button>' : '<span class="hint">drag him in Overhead</span>'}</div>
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
    <div class="card"><h3>Save as an idiom</h3>
      <form class="row" id="saveIdiom"><input type="text" id="idiomName" maxlength="40" placeholder="Name, e.g. Slow push past his shoulder" aria-label="Idiom name" style="flex:1"><button type="submit">Save</button></form>
      <p class="hint">Keeps this shot's framing and timing as a ${esc(G.EVENTS[b.event])} idiom you can use on any beat${mine ? ` (you have ${mine})` : ''}.</p></div>`;
  if (s.moving) renderCurve($('curveHost'), s, T0[rowIndex(b.id)]);
}
function renderShot() { renderTimelines(); renderFraming(); renderMinis(); renderInspector(); }

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
  $('export').innerHTML = ROWS.map(r => { const s = r.pick.s, p = G.toPlan(r, S.mood), moved = 'mark' in p;
    return `<div class="exp-card"><img alt="${r.beat.id}" src="${still(r, frameTimes(s).slice(-1)[0])}">
      <div style="display:grid;gap:8px;min-width:0"><b>${r.beat.id} · ${esc(r.beat.title)} · ${esc(r.pick.idiom.name)}</b>
        <div class="writes">${esc(G.words(s))}</div>
        <div class="row"><button data-copy="motion" data-for="${r.beat.id}">Copy Camera Motion</button><button data-copy="plan" data-for="${r.beat.id}">Copy 3D Stage plan</button><span class="hint">${r.beat.seconds} s = ${framesOf(r.plan)} frames · 17 camera keys</span></div>
        ${moved ? '<p class="hint" style="color:var(--warn)">He is off his station here: the 3D Stage plan needs a mark field before Render previs can place him (SPEC_09 §8).</p>' : ''}
        <pre>${esc(JSON.stringify(p))}</pre></div></div>`; }).join('');
}

/* ---------- routing and refresh ---------- */
function liveRender() {
  renderTimelines();
  if (UI.route === 'shot') {
    renderFraming(); const s = sel().pick.s; $('writes') && ($('writes').textContent = G.words(s));
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
  if (UI.sel !== id) UI.frame = 'start';
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
    return TX.once(`${id} ${G.HEIGHT_LABEL[r.pick.s.angle].toLowerCase()} → ${G.HEIGHT_LABEL[d.height].toLowerCase()}`, St => patch(St, id, { angle: d.height }), id);
  }
  if (d.lens) {
    if (!clearWith(id, { lens: Number(d.lens) })) return say(`<span class="lim">At ${d.lens}mm this framing needs more room than the dome has</span>`);
    return TX.once(`${id} lens ${r.pick.s.lens} → ${d.lens}mm (same shot size, camera ${Number(d.lens) > r.pick.s.lens ? 'farther' : 'closer'})`, St => patch(St, id, { lens: Number(d.lens) }), id);
  }
  if (d.ending) return TX.once(`${id} ending: ${G.ENDING_LABEL[d.ending].toLowerCase()}`, St => patch(St, id, { ending: d.ending }), id);
  if (d.applyScene) {
    const t = G.sceneTemplatesFor(S).find(x => x.name === d.applyScene);
    return TX.once(`scene template “${t.name}”`, St => { for (const b of G.SCENE.beats) { const name = t.picks[b.event]; if (!name || !G.idiomsFor(St, b.event).some(i => i.name === name)) continue;
      St.pins[b.id] = name; if (t.over?.[b.event]) ((St.over[b.id] ||= {})[name] = clone(t.over[b.event])); } });
  }
  if (d.delScene) return TX.once(`deleted scene template “${d.delScene}”`, St => { St.sceneTemplates = St.sceneTemplates.filter(x => x.name !== d.delScene); });
  if (d.delIdiom) return TX.once(`deleted idiom “${d.delIdiom}”`, St => { St.custom[d.event] = (St.custom[d.event] || []).filter(x => x.name !== d.delIdiom);
    for (const k of Object.keys(St.pins)) if (St.pins[k] === d.delIdiom) delete St.pins[k]; });
  if (d.copy) { const x = rowOf(d.for); return copy(d.copy === 'plan' ? JSON.stringify(G.toPlan(x, S.mood)) : G.words(x.pick.s), el); }
  if (el.id === 'copyAll') return copy(JSON.stringify(Object.fromEntries(ROWS.map(x => [x.beat.id, { idiom: x.pick.idiom.name, cameraMotion: G.words(x.pick.s), plan: G.toPlan(x, S.mood) }])), null, 1), el);
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
    TX.once(`saved the scene as template “${name}”`, St => { St.sceneTemplates.push({ name, desc: `Saved from ${G.SCENE.title}`, picks, over: ov }); });
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
  const k = e.target.dataset?.rule; if (!k || !TX.cur) return;
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
  drag = { x: e.clientX, y: e.clientY, az: r.pick.s.az ?? room.az0, angle: r.pick.s.angle, room, w: live.clientWidth, main: '', why: '' };
  TX.begin('frame'); live.setPointerCapture(e.pointerId);
});
live.addEventListener('pointermove', e => {
  if (!drag) return;
  const id = UI.sel, { room } = drag, want = drag.az + (e.clientX - drag.x) / drag.w * 120;  // the camera goes the way you drag; full width = 120°
  let az = Math.round(Math.min(room.az[1], Math.max(room.az[0], want)) / 5) * 5, why = '';
  if (want > room.az[1] + 3 || want < room.az[0] - 3) why = `side stops at ${side(want > room.az[1] ? room.az[1] : room.az[0])}: ${room.blockedAz.length ? 'further round, the set blocks the camera' : 'this idiom keeps the camera inside ±30°'}`;
  const idx = room.heights.map(h => G.HEIGHTS.indexOf(h)), hi = G.HEIGHTS.indexOf(drag.angle) + Math.round(-(e.clientY - drag.y) / 70);
  let angle = G.HEIGHTS[Math.min(Math.max(...idx), Math.max(Math.min(...idx), hi))];
  if (hi > Math.max(...idx) || hi < Math.min(...idx)) why = why || `height stops at ${G.HEIGHT_LABEL[angle].toLowerCase()}: this idiom allows ${room.heights.map(h => G.HEIGHT_LABEL[h].toLowerCase()).join(', ')}`;
  if (!clearWith(id, { az, angle })) angle = drag.angle;
  while (az !== drag.az && !clearWith(id, { az, angle })) { az += az > drag.az ? -5 : 5; why = 'further round, the set blocks the camera'; }
  drag.main = az === drag.az && angle === drag.angle ? '' : `${id} camera ${side(az)}${angle !== drag.angle ? `, ${G.HEIGHT_LABEL[angle].toLowerCase()}` : ''}`; drag.why = why;
  TX.live(St => patch(St, id, { az, angle }), `${side(az)} · ${G.HEIGHT_LABEL[angle]}`, why, e);
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
  ui: UI, tx: TX, patch, topCamera: top,
  rows: () => ROWS, t0: () => T0, total: () => TOTAL, state: () => S, row: sel, rowIndex,
  scale: () => UI.scale || TOTAL, freezeScale: v => { UI.scale = v; },
  room: roomOf, clear: clearWith, sideText: side,
  select, seek(t, scrub) { if (UI.playing) stop(); UI.t = t; if (scrub) UI.frame = null; const id = at(t).r.beat.id; if (id !== UI.sel) { UI.sel = id; refresh(); } else draw(); },
};
bindTimeline(ctx); bindCurve(ctx); bindOverlay(ctx);

buildSet();
plan();
seekFrame();
route();
window.__shotGrammar = { get rows() { return ROWS; }, get state() { return S; }, get ui() { return UI; }, get history() { return HIST; } };  // console handle for checking the prototype
