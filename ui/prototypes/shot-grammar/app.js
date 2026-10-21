// Shot Grammar prototype UI, one screen per job: Storyboard (every shot's start/end frame), Shot (frame one shot inside
// its idiom's room), Overhead (where every camera stands, with the lens view beside it), Idiom library, Export (3D Stage
// plans). Plain DOM; product integration would move this into PrevisStage.
import * as THREE from 'three';
import { buildStage, prepareRenderer, shotGuides } from '../../src/previs/scene.js';
import { HEIGHT, WIDTH, framesOf } from '../../src/previs/plan.js';
import * as G from './grammar.js';

const $ = id => document.getElementById(id);
const $$ = sel => [...document.querySelectorAll(sel)];
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = v => (Math.round(v * 10) / 10).toFixed(1);
const BEATS = G.SCENE.beats;
const ROUTES = ['scene', 'shot', 'overhead', 'library', 'export'];

/* ---------- state, history ---------- */
const STORE = 'zf.shotGrammar.v1';
const DEF = { preset: 'standard', seed: 7, mood: 'grey', beats: {}, pins: {}, over: {} };
const clone = o => JSON.parse(JSON.stringify(o));
function load() { try { return { ...clone(DEF), ...(JSON.parse(localStorage.getItem(STORE) || 'null') || {}) }; } catch { return clone(DEF); } }
let S = load();
const HIST = { list: [JSON.stringify(S)], at: 0 };
function commit() {
  const now = JSON.stringify(S);
  if (now !== HIST.list[HIST.at]) { HIST.list = HIST.list.slice(0, HIST.at + 1).concat(now).slice(-60); HIST.at = HIST.list.length - 1; }
  try { localStorage.setItem(STORE, now); } catch { /* private window: this session only */ }
  refresh();
}
function travel(step) {
  const at = HIST.at + step; if (at < 0 || at >= HIST.list.length) return;
  HIST.at = at; S = JSON.parse(HIST.list[at]); try { localStorage.setItem(STORE, HIST.list[at]); } catch { /* ignore */ }
  if (S.mood !== stageMood) buildSet();
  refresh();
}
const UI = { route: 'scene', sel: BEATS[0].id, t: 0, playing: null, limit: '' };

/* ---------- stage: one live renderer that moves between viewports, one for stills ---------- */
const live = document.createElement('canvas'); live.className = 'live'; live.setAttribute('aria-label', '3D stage');
const renderer = prepareRenderer(new THREE.WebGLRenderer({ canvas: live, antialias: true }));
renderer.setSize(WIDTH, HEIGHT, false);
const stills = prepareRenderer(new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true }));
stills.setSize(640, 352, false);
const top = new THREE.PerspectiveCamera(42, WIDTH / HEIGHT, 0.1, 100);
top.position.set(0, 12.5, -2.2); top.up.set(0, 0, 1); top.lookAt(0, 0, -2.2);
const lensCam = new THREE.PerspectiveCamera(35, WIDTH / HEIGHT, 0.05, 200);
let stage = null, stageMood = null, solids = [], guides = null;
const ray = new THREE.Raycaster(), va = new THREE.Vector3(), vb = new THREE.Vector3();
function buildSet() {
  stage?.dispose();
  stage = buildStage({ set: 'observatory', mood: S.mood, lens: 35 }); stageMood = S.mood;
  solids = []; stage.scene.traverse(o => { if (o.isMesh && !o.userData.actor && !o.userData.roof && o.material.isMeshLambertMaterial) solids.push(o); });
  guides = null; STILL.clear();
}
// Something solid between the subject and the camera (consoles, glass posts): the obstruction test the grammar uses.
function blocked(pos, F) {
  va.set(...F); vb.set(...pos).sub(va); const d = vb.length(); if (d < 0.06) return false;
  ray.set(va, vb.normalize()); ray.near = 0.03; ray.far = d;
  return ray.intersectObjects(solids, false).length > 0;
}
function aimLens(cam, r, p) {
  const c = G.solve(r.pick.s, r.plan, p);
  cam.fov = c.fov; cam.position.set(...c.pos); cam.up.set(0, 1, 0); cam.lookAt(...c.aim); cam.updateProjectionMatrix();
}
// A still of row r at shot time p, cached by everything that changes the picture.
const STILL = new Map();
function still(r, p, s = r.pick.s, idiomName = r.pick.idiom.name) {
  const key = JSON.stringify([r.beat.id, r.beat.seconds, idiomName, S.over[r.beat.id]?.[idiomName] || null, p, S.mood, s.az, s.size, s.end]);
  if (STILL.has(key)) return STILL.get(key);
  stage.pose(p * (framesOf(r.plan) - 1), r.plan); stage.roof(true); guides && (guides.group.visible = false);
  aimLens(lensCam, { ...r, pick: { ...r.pick, s } }, p);
  stills.render(stage.scene, lensCam);
  const url = stills.domElement.toDataURL('image/jpeg', 0.82);
  STILL.set(key, url); return url;
}

/* ---------- plan ---------- */
let ROWS = [], T0 = [], TOTAL = 0;
function plan(withGuides = true) {  // guides (overhead camera paths) are rebuilt on commit, not on every drag step
  ROWS = G.choose(G.SCENE, S, blocked);
  T0 = []; TOTAL = 0; for (const r of ROWS) { T0.push(TOTAL); TOTAL += r.beat.seconds; }
  if (!withGuides && guides) return;
  if (guides) { stage.scene.remove(guides.group); guides.dispose(); }
  guides = shotGuides(ROWS.map(r => ({ id: r.beat.id, plan: G.toPlan(r, S.mood), selected: r.beat.id === UI.sel })));
  stage.scene.add(guides.group);
}
const rowIndex = id => ROWS.findIndex(r => r.beat.id === id);
const rowOf = id => ROWS[rowIndex(id)];
function at(t) {
  let i = ROWS.length - 1; while (i > 0 && t < T0[i]) i--;
  const r = ROWS[i]; return { r, i, p: Math.min(1, Math.max(0, (t - T0[i]) / r.beat.seconds)) };
}
const over = (id, name) => ((S.over[id] ||= {})[name] ||= {});
const flagged = () => new Set(G.checks(ROWS).filter(c => c.kind === 'warn').map(c => c.id));
const frameTimes = s => (s.moving ? [0.02, 0.98] : [0.5]);

/* ---------- live drawing (Shot and Overhead) ---------- */
function draw() {
  if (UI.route !== 'shot' && UI.route !== 'overhead') return;
  const { r, p } = at(UI.t), f = p * (framesOf(r.plan) - 1);
  stage.pose(f, r.plan);
  if (UI.route === 'shot') {
    aimLens(stage.camera, r, p); stage.roof(true); guides.group.visible = false;
    renderer.render(stage.scene, stage.camera);
  } else {
    stage.roof(false); guides.group.visible = true; guides.update(p, 1.3);
    renderer.render(stage.scene, top);
    aimLens(lensCam, r, p); stage.roof(true); guides.group.visible = false;
    stills.render(stage.scene, lensCam);
    $('lensMini').getContext('2d').drawImage(stills.domElement, 0, 0, 640, 352);
  }
  const view = $(UI.route === 'shot' ? 'v-shot' : 'v-overhead');
  const set = (k, v) => view.querySelectorAll(`[data-ov="${k}"]`).forEach(el => { el.textContent = v; });
  set('shot', `${r.beat.id} · ${r.beat.title} · ${r.pick.idiom.name}`);
  set('words', G.words(r.pick.s)); set('limit', UI.limit);
  set('time', `${fmt(UI.t)} / ${fmt(TOTAL)} s · ${r.beat.id} frame ${Math.round(f)}`);
  view.querySelectorAll('.playhead').forEach(ph => { ph.style.left = `${(UI.t / TOTAL) * 100}%`; });
  $('vpShot').dataset.grab = String(UI.route === 'shot' && !UI.playing);
}

/* ---------- header, timelines ---------- */
function seg(id, items, cur, attr) {
  $(id).innerHTML = items.map(([v, l]) => `<button type="button" data-${attr}="${v}" aria-pressed="${v === cur}">${esc(l)}</button>`).join('');
}
function renderHeader() {
  $('sceneTitle').textContent = G.SCENE.title;
  seg('presets', Object.entries(G.PRESETS).map(([k, p]) => [k, p.label]), S.preset, 'preset');
  seg('moods', [['grey', 'Grey'], ['night', 'Night']], S.mood, 'mood');
  $('undo').disabled = HIST.at === 0; $('redo').disabled = HIST.at >= HIST.list.length - 1;
  $$('nav a').forEach(a => a.setAttribute('aria-current', a.dataset.route === UI.route ? 'page' : 'false'));
}
function timeline(id) {
  const flags = flagged(), pts = ROWS.map((r, i) => `${((T0[i] + r.beat.seconds / 2) / TOTAL) * 1000},${74 - r.beat.tension * 58}`).join(' ');
  $(id).innerHTML = ROWS.map(r => `
    <div class="tl-beat" data-sel="${r.beat.id === UI.sel}" style="width:${(r.beat.seconds / TOTAL) * 100}%">
      <b>${r.beat.id} <span class="flag">${flags.has(r.beat.id) ? '!' : ''}</span></b>
      <span>${esc(r.pick.idiom.name)}</span><span>${r.beat.seconds} s · tension ${fmt(r.beat.tension)}</span>
    </div>`).join('') +
    `<svg class="tl-svg" viewBox="0 0 1000 78" preserveAspectRatio="none" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="#f59e0b" stroke-opacity=".55" stroke-width="2" vector-effect="non-scaling-stroke"/></svg><div class="playhead"></div>`;
}

/* ---------- Storyboard ---------- */
function renderScene() {
  const flags = flagged();
  $('board').innerHTML = ROWS.map(r => {
    const s = r.pick.s, times = frameTimes(s);
    return `<button class="sb" data-open="${r.beat.id}" data-sel="${r.beat.id === UI.sel}">
      <div class="frames ${times.length === 1 ? 'one' : ''}">${times.map((p, k) => `<figure><img alt="${r.beat.id} ${times.length > 1 ? (k ? 'end' : 'start') : ''} frame" src="${still(r, p)}"><figcaption>${times.length > 1 ? (k ? 'End · ' + (s.end || s.size) : 'Start · ' + s.size) : s.size}</figcaption></figure>`).join('')}</div>
      <div class="meta"><span><b>${r.beat.id}</b> ${esc(r.beat.title)} ${flags.has(r.beat.id) ? '<span class="flag">· check</span>' : ''}</span>
        <span>${esc(r.pick.idiom.name)}${r.pinned ? ' <em class="chip pin">pinned</em>' : ''}${r.pick.idiom.drama ? ' <em class="chip drama">showpiece</em>' : ''}</span>
        <span class="words">${esc(G.words(s))} · ${r.beat.seconds} s</span></div>
    </button>`;
  }).join('');
  timeline('tlScene');
  $('checks').innerHTML = G.checks(ROWS).map(c => `<li data-kind="${c.kind}" ${c.id ? `data-open="${c.id}"` : ''}>${esc(c.text)}</li>`).join('');
}

/* ---------- Shot inspector ---------- */
function curve(s) {
  let d = ''; for (let i = 0; i <= 60; i++) { const p = i / 60; d += `${i ? 'L' : 'M'}${(p * 300).toFixed(1)} ${(52 - 44 * G.progress(s, p)).toFixed(1)}`; }
  const a = s.start * 300, b = G.moveStop(s) * 300;
  return `<svg class="curve" viewBox="0 0 300 56" preserveAspectRatio="none" aria-label="Move timing"><rect x="${a}" y="2" width="${Math.max(1, b - a)}" height="52" fill="#06b6d4" opacity=".12"/><path d="${d}" fill="none" stroke="#f59e0b" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>`;
}
const side = a => { const n = ((a + 540) % 360) - 180;  // -180..180, + = the subject's left
  return Math.abs(n) > 177 ? 'from behind' : Math.abs(n) < 3 ? 'from the front' : `${Math.round(Math.abs(n))}° ${n > 0 ? 'left' : 'right'} of front`; };
// A push ends tighter than it starts, a pull wider.
function endsFor(list, s) {
  const si = G.SIZES.indexOf(s.size);
  return list.filter(z => { const zi = G.SIZES.indexOf(z); return si < 0 || zi < 0 || (s.move === 'pull' ? zi < si : s.move === 'push' ? zi > si : true); });
}
function renderShot() {
  timeline('tlShot');
  const r = rowOf(UI.sel), b = r.beat, s = r.pick.s, idiom = r.pick.idiom;
  const room = G.roomOf(b, idiom, s, blocked), az = s.az ?? room.az0, ends = room.ends && endsFor(room.ends, s);
  const sizeStep = (list, cur, key) => `<div class="row"><span class="label">${key === 'end' ? 'End size' : 'Start size'}</span>
      <button data-size="${key}" data-dir="-1" ${list.indexOf(cur) <= 0 ? 'disabled' : ''}>Wider</button>
      <b>${cur} <span class="hint">${G.SIZE_LABEL[cur]}</span></b>
      <button data-size="${key}" data-dir="1" ${list.indexOf(cur) < 0 || list.indexOf(cur) >= list.length - 1 ? 'disabled' : ''}>Tighter</button></div>`;
  $('inspector').innerHTML = `
    <div class="card">
      <span class="label">${b.id} · ${esc(G.EVENTS[b.event])}</span>
      <h4>${esc(b.title)}</h4>
      <div class="row"><span class="label">Tension</span><input type="range" id="tension" min="0" max="1" step="0.05" value="${b.tension}"><b>${fmt(b.tension)}</b></div>
      <div class="row"><span class="label">Length</span><div class="seg">${[4, 6, 8].map(n => `<button data-sec="${n}" aria-pressed="${n === b.seconds}">${n} s</button>`).join('')}</div></div>
    </div>
    <div class="card">
      <h3>Idiom</h3>
      <div class="idioms">${r.cands.map(c => `
        <button class="idiom" data-idiom="${esc(c.idiom.name)}" data-pick="${c === r.pick}" data-usable="${c.usable}">
          <span class="t"><b>${esc(c.idiom.name)}</b>${c.idiom.drama ? '<em class="chip drama">showpiece</em>' : ''}${c === r.pick && r.pinned ? '<em class="chip pin">pinned</em>' : ''}<span>${c.usable ? `energy ${fmt(c.s.energy)}` : 'blocked by the set'}</span></span>
          <span class="w">${esc(G.words(c.s))}</span>
        </button>`).join('')}</div>
      ${r.pinned ? '<button id="unpin">Let the style choose again</button>' : '<p class="hint">Chosen for the beat\'s tension. Click another idiom to pin it.</p>'}
    </div>
    <div class="card">
      <h3>Framing</h3>
      ${sizeStep(room.sizes, s.size, 'size')}
      ${ends ? sizeStep(ends, s.end, 'end') : ''}
      <div class="row"><span class="label">Height</span><div class="seg">${room.heights.map(h => `<button data-height="${h}" aria-pressed="${h === s.angle}">${G.HEIGHT_LABEL[h]}</button>`).join('')}</div></div>
      <div class="row"><span class="label">Side</span><span>${side(az)}</span><span class="hint">room ${side(room.az[0])} to ${side(room.az[1])}</span></div>
      <div class="row"><span class="label">Lens</span><div class="seg">${[24, 35, 50, 85].map(l => `<button data-lens="${l}" aria-pressed="${l === s.lens}">${l}mm</button>`).join('')}</div></div>
      <button id="resetFrame" ${Object.keys(S.over[b.id]?.[idiom.name] || {}).length ? '' : 'disabled'}>Reset to the idiom</button>
    </div>
    ${s.moving ? `<div class="card">
      <h3>Move timing</h3>
      ${curve(s)}
      <div class="row"><span class="label">Starts at</span><input type="range" id="start" min="0" max="0.7" step="0.05" value="${s.start}"><b>${fmt(s.start * s.dur)} s</b></div>
      <div class="row"><span class="label">Speed</span><div class="seg">${G.SPEEDS.map(v => `<button data-speed="${v}" aria-pressed="${v === s.speed}">${v}</button>`).join('')}</div>${s.autoFaster ? '<span class="hint">sped up to fit</span>' : ''}</div>
      <div class="row"><span class="label">Ending</span><div class="seg">${Object.keys(G.ENDINGS).map(v => `<button data-ending="${v}" aria-pressed="${v === s.ending}">${v}</button>`).join('')}</div></div>
      <p class="hint">Moving from ${fmt(s.start * s.dur)} to ${fmt(G.moveStop(s) * s.dur)} s; ${esc(G.ENDINGS[s.ending])}.</p>
    </div>` : ''}`;
}

/* ---------- Overhead ---------- */
function renderOverhead() {
  timeline('tlTop');
  $('shotlist').innerHTML = ROWS.map(r => `<button data-pick-beat="${r.beat.id}" data-sel="${r.beat.id === UI.sel}"><b>${r.beat.id} · ${esc(r.pick.idiom.name)}</b><span>${esc(G.words(r.pick.s))}</span></button>`).join('');
}

/* ---------- Idiom library ---------- */
function renderLibrary() {
  $('library').innerHTML = Object.entries(G.IDIOMS).map(([event, list]) => {
    const r = ROWS.find(x => x.beat.event === event);
    return `<div class="lib-event"><h3>${esc(G.EVENTS[event])} <span class="hint">${r ? `shown on ${r.beat.id} · ${esc(r.beat.title)}` : 'not used in this scene'}</span></h3>
      <div class="lib-grid">${list.map(idiom => {
        const c = r?.cands.find(x => x.idiom === idiom), s = c?.s, times = s ? frameTimes(s) : [];
        return `<div class="lib-card" data-used="${r?.pick.idiom === idiom}">
          ${r && c?.usable ? `<div class="frames ${times.length === 1 ? 'one' : ''}">${times.map(p => `<figure><img alt="" src="${still(r, p, s, idiom.name)}"></figure>`).join('')}</div>` : ''}
          <div class="meta"><b>${esc(idiom.name)} ${idiom.drama ? '<em class="chip drama">showpiece</em>' : ''}</b>
            <span class="words">${esc(G.words(s || G.effShot({ seconds: 4 }, idiom)))}</span>
            ${r ? (c.usable ? `<button data-use="${esc(idiom.name)}" data-for="${r.beat.id}" ${r.pick.idiom === idiom ? 'disabled' : ''}>${r.pick.idiom === idiom ? `Used on ${r.beat.id}` : `Use on ${r.beat.id}`}</button>` : '<span class="hint">Blocked by the set on this beat</span>') : ''}</div>
        </div>`;
      }).join('')}</div></div>`;
  }).join('');
}

/* ---------- Export ---------- */
function renderExport() {
  $('export').innerHTML = ROWS.map(r => {
    const s = r.pick.s, json = JSON.stringify(G.toPlan(r, S.mood));
    return `<div class="exp-card"><img alt="${r.beat.id}" src="${still(r, frameTimes(s).slice(-1)[0])}">
      <div style="display:grid;gap:8px;min-width:0"><b>${r.beat.id} · ${esc(r.beat.title)} · ${esc(r.pick.idiom.name)}</b>
        <div class="words">${esc(G.words(s))}</div>
        <div class="row"><button data-copy="motion" data-for="${r.beat.id}">Copy Camera Motion</button><button data-copy="plan" data-for="${r.beat.id}">Copy 3D Stage plan</button><span class="hint">${r.beat.seconds} s = ${framesOf(r.plan)} frames · 17 camera keys</span></div>
        <pre>${esc(json)}</pre></div></div>`;
  }).join('');
}

/* ---------- routing ---------- */
function route() {
  const want = location.hash.slice(1);
  UI.route = ROUTES.includes(want) ? want : 'scene';
  for (const k of ROUTES) $(`v-${k}`).hidden = k !== UI.route;
  if (UI.route === 'shot') $('vpShot').prepend(live);
  if (UI.route === 'overhead') $('vpTop').prepend(live);
  if (UI.playing && UI.route !== 'shot' && UI.route !== 'overhead') stop();
  refresh();
}
function refresh() {
  plan(); renderHeader();
  ({ scene: renderScene, shot: renderShot, overhead: renderOverhead, library: renderLibrary, export: renderExport })[UI.route]();
  draw();
}
window.addEventListener('hashchange', route);

/* ---------- edits ---------- */
function select(id) {
  UI.sel = id; UI.limit = '';
  const i = rowIndex(id); UI.t = T0[i] + Math.min(ROWS[i].beat.seconds * 0.5, ROWS[i].beat.seconds - 0.01);
  refresh();
}
function setOver(id, patch) {  // a framing change pins the idiom it was made on
  const r = rowOf(id); Object.assign(over(id, r.pick.idiom.name), patch); S.pins[id] = r.pick.idiom.name;
}
const shotWith = (r, patch) => G.effShot(r.beat, r.pick.idiom, { ...(S.over[r.beat.id]?.[r.pick.idiom.name] || {}), ...patch });
function tryOver(patch, why) {
  const r = rowOf(UI.sel);
  if (!G.clear(shotWith(r, patch), r.plan, blocked)) { UI.limit = why; return draw(); }
  UI.limit = ''; setOver(UI.sel, patch); commit();
}
document.addEventListener('click', e => {
  const el = e.target.closest('button, [data-open]'); if (!el) return;
  const d = el.dataset, r = rowOf(UI.sel);
  if (d.preset) { S.preset = d.preset; return commit(); }
  if (d.mood) { S.mood = d.mood; buildSet(); return commit(); }
  if (d.open) { select(d.open); location.hash = 'shot'; return; }
  if (d.pickBeat) return select(d.pickBeat);
  if (el.id === 'reroll') { S.seed = (S.seed || 7) + 1; return commit(); }
  if (el.id === 'undo') return travel(-1);
  if (el.id === 'redo') return travel(1);
  if (d.step) { const n = ROWS[rowIndex(UI.sel) + Number(d.step)]; if (n) select(n.beat.id); return; }
  if (d.play) return togglePlay(d.play);
  if (d.sec) { (S.beats[UI.sel] ||= {}).seconds = Number(d.sec); return commit(); }
  if (d.idiom) { S.pins[UI.sel] = d.idiom; UI.limit = ''; return commit(); }
  if (d.use) { S.pins[d.for] = d.use; return commit(); }
  if (el.id === 'unpin') { delete S.pins[UI.sel]; return commit(); }
  if (el.id === 'resetFrame') { delete S.over[UI.sel]?.[r.pick.idiom.name]; UI.limit = ''; return commit(); }
  if (d.size) {
    const s = r.pick.s, room = G.roomOf(r.beat, r.pick.idiom, s, blocked), key = d.size;
    const list = key === 'end' ? endsFor(room.ends || [], s) : room.sizes, j = list.indexOf(s[key]) + Number(d.dir);
    if (list[j]) tryOver({ [key]: list[j] }, `${list[j]} would put the camera in the set`);
    return;
  }
  if (d.height) return tryOver({ angle: d.height }, `${G.HEIGHT_LABEL[d.height]} would put the camera in the set`);
  if (d.lens) return tryOver({ lens: Number(d.lens) }, `At ${d.lens}mm this framing needs more room than the dome has`);
  if (d.speed) { setOver(UI.sel, { speed: d.speed, mlen: undefined }); return commit(); }
  if (d.ending) { setOver(UI.sel, { ending: d.ending }); return commit(); }
  if (d.copy) { const x = rowOf(d.for); return copy(d.copy === 'plan' ? JSON.stringify(G.toPlan(x, S.mood)) : G.words(x.pick.s), el); }
  if (el.id === 'copyAll') return copy(JSON.stringify(Object.fromEntries(ROWS.map(x => [x.beat.id, { idiom: x.pick.idiom.name, cameraMotion: G.words(x.pick.s), plan: G.toPlan(x, S.mood) }])), null, 1), el);
});
document.addEventListener('input', e => {
  if (e.target.id === 'tension') { (S.beats[UI.sel] ||= {}).tension = Number(e.target.value); delete S.pins[UI.sel]; scheduleCommit(); }
  if (e.target.id === 'start') { setOver(UI.sel, { start: Number(e.target.value) }); scheduleCommit(); }
});
let commitT = 0;
function scheduleCommit() { plan(false); draw(); clearTimeout(commitT); commitT = setTimeout(commit, 350); }
async function copy(text, el) {
  const label = el.textContent;
  try { await navigator.clipboard.writeText(text); } catch { const ta = $('copybuf'); ta.value = text; ta.select(); document.execCommand('copy'); }
  el.textContent = 'Copied'; setTimeout(() => { el.textContent = label; }, 1200);
}

/* ---------- Shot: drag the camera round the subject, inside the idiom's room ---------- */
let drag = null;
live.addEventListener('pointerdown', e => {
  if (UI.route !== 'shot' || UI.playing) return;
  const r = rowOf(UI.sel);
  if (at(UI.t).r !== r) UI.t = T0[rowIndex(UI.sel)] + r.beat.seconds * 0.5;
  const room = G.roomOf(r.beat, r.pick.idiom, r.pick.s, blocked);
  drag = { x: e.clientX, y: e.clientY, az: r.pick.s.az ?? room.az0, angle: r.pick.s.angle, room, w: live.clientWidth };
  live.setPointerCapture(e.pointerId);
});
live.addEventListener('pointermove', e => {
  if (!drag) return;
  const r = rowOf(UI.sel), { room } = drag, want = drag.az + (e.clientX - drag.x) / drag.w * 120;  // the camera goes the way you drag; full width = 120°
  let az = Math.round(Math.min(room.az[1], Math.max(room.az[0], want)) / 5) * 5, why = '';
  if (want > room.az[1] + 3 || want < room.az[0] - 3) why = 'This idiom keeps the camera inside its side range';
  const idx = room.heights.map(h => G.HEIGHTS.indexOf(h)), hi = G.HEIGHTS.indexOf(drag.angle) + Math.round(-(e.clientY - drag.y) / 70);
  const angle = G.HEIGHTS[Math.min(Math.max(...idx), Math.max(Math.min(...idx), hi))];
  const ok = patch => G.clear(shotWith(r, patch), r.plan, blocked);
  while (az !== drag.az && !ok({ az, angle })) { az += az > drag.az ? -5 : 5; why = 'Further round, the set blocks the camera'; }
  setOver(UI.sel, { az, angle: ok({ az, angle }) ? angle : drag.angle });
  UI.limit = why; plan(false); draw();
});
const endDrag = () => { if (!drag) return; drag = null; commit(); };
live.addEventListener('pointerup', endDrag);
live.addEventListener('pointercancel', endDrag);

/* ---------- playback, scrubbing, keys ---------- */
function stop() { if (UI.playing) cancelAnimationFrame(UI.playing.raf); UI.playing = null; setPlayLabels(); }
function togglePlay(range) {
  if (UI.playing) { stop(); return draw(); }
  const i = rowIndex(UI.sel), from = range === 'shot' ? T0[i] : (UI.t >= TOTAL - 0.05 ? 0 : UI.t), to = range === 'shot' ? T0[i] + ROWS[i].beat.seconds : TOTAL;
  UI.t = from; UI.playing = { range, to, last: performance.now() };
  const tick = now => {
    const P = UI.playing; if (!P) return;
    UI.t = Math.min(P.to, UI.t + (now - P.last) / 1000); P.last = now;
    const cur = at(UI.t).r.beat.id;
    if (cur !== UI.sel && P.range === 'scene') { UI.sel = cur; (UI.route === 'shot' ? renderShot : renderOverhead)(); }
    draw();
    if (UI.t >= P.to - 1e-3) { stop(); return draw(); }
    P.raf = requestAnimationFrame(tick);
  };
  setPlayLabels(); UI.playing.raf = requestAnimationFrame(tick);
}
function setPlayLabels() {
  $$('[data-play]').forEach(b => { b.textContent = UI.playing?.range === b.dataset.play ? 'Pause' : b.dataset.play === 'scene' ? 'Play scene' : 'Play shot'; });
}
document.addEventListener('pointerdown', e => {
  const tl = e.target.closest('.timeline'); if (!tl) return;
  const box = tl.getBoundingClientRect(), t = Math.min(TOTAL - 0.01, Math.max(0, (e.clientX - box.left) / box.width * TOTAL)), id = at(t).r.beat.id;
  if (UI.route === 'scene') { select(id); location.hash = 'shot'; return; }
  UI.t = t;
  if (id !== UI.sel) { UI.sel = id; UI.limit = ''; refresh(); } else draw();
});
document.addEventListener('keydown', e => {
  if (e.target.closest('input, textarea')) return;
  if (e.key === ' ' && (UI.route === 'shot' || UI.route === 'overhead')) { e.preventDefault(); togglePlay('scene'); }
  if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') { const n = ROWS[rowIndex(UI.sel) + (e.key === 'ArrowRight' ? 1 : -1)]; if (n) select(n.beat.id); }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); travel(e.shiftKey ? 1 : -1); }
});

buildSet();
plan();
select(UI.sel);
route();
window.__shotGrammar = { get rows() { return ROWS; }, get state() { return S; }, get ui() { return UI; } };  // console handle for checking the prototype
