import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { useLocale } from '../i18n/react.jsx';
import { t as uiText } from '../i18n/index.js';
import { ACTIONS, DURATIONS, FACINGS, FPS, HEIGHT, LENSES, MOODS, MOVES, SETS, WIDTH, cameraKeys, defaultPlan, describePlan, framesOf, planFromSlate, sampleCamera, verticalFov } from './plan.js';
import { buildStage, prepareRenderer, shotGuides } from './scene.js';
import { encodeCanvas, fetchPlan } from './webm.js';
import { drawSkeleton, poseKeypoints } from './skeleton.js';

// split: the overhead plan and the shot lens side by side on one renderer (80.lv's layout view over the camera view).
export const VIEWS = ['split', 'lens', 'overhead', 'free'];
const SPLIT = WIDTH / 2 - 1;  // each half of the split view, with a 2 px seam
const draftKey = (slug, rid) => `zf.previs:${slug}:${rid}`;
function loadDraft(slug, rid) { try { return JSON.parse(localStorage.getItem(draftKey(slug, rid)) || 'null'); } catch { return null; } }
function saveDraft(slug, rid, plan) {  // unrendered edits stay in this browser; a render stores its plan in the project
  try { if (plan) localStorage.setItem(draftKey(slug, rid), JSON.stringify(plan)); else localStorage.removeItem(draftKey(slug, rid)); } catch { /* optional */ }
}
const pick = (label, value, options, onChange, text) => <fieldset className="previs-field"><legend>{label}</legend>
  {options.map(o => <button type="button" key={o} aria-pressed={value === o} onClick={() => onChange(o)}>{text(o)}</button>)}</fieldset>;

// The 3D stage of a slate: every shot in one set. Look through a shot's lens, see all shot cameras on an overhead
// plan, frame custom paths in a free camera, play a shot or the whole scene, and render a shot's grey previs
// (97 frames, 24 fps) into its Previs cell, its actor matte into Actor Matte and its pose skeleton into Pose Skeleton
// (the Layout Render frees the actor and takes the acting from the skeleton). The render carries its plan, so the
// project keeps it.
export default function PrevisStage({ slug, shots, focus, writable, busy, onRender, onMotion, onLayout }) {
  useLocale();
  const [rid, setRid] = useState(() => (shots.some(s => s.rid === focus?.rid) ? focus.rid : shots[0]?.rid));
  const [drafts, setDrafts] = useState(() => Object.fromEntries(shots.map(s => [s.rid, loadDraft(slug, s.rid)]).filter(([, p]) => p)));
  const [stored, setStored] = useState({}), [rendered, setRendered] = useState({});  // url -> plan in that file; rid -> plan rendered here
  const [view, setView] = useState('lens'), [frame, setFrame] = useState(0), [playing, setPlaying] = useState(false);
  const [rendering, setRendering] = useState(false), [error, setError] = useState('');
  const host = useRef(null), live = useRef(null), progress = useRef(null), now = useRef({});

  const planOf = s => ({ ...defaultPlan(), ...(drafts[s.rid] || stored[s.previs] || rendered[s.rid] || planFromSlate(s.slate)) });
  const shot = shots.find(s => s.rid === rid) || shots[0];
  const plan = shot ? planOf(shot) : defaultPlan(), frames = framesOf(plan);
  const statusOf = s => (drafts[s.rid] ? 'edited' : s.previs ? 'rendered' : 'none');
  const edit = patch => { const next = { ...plan, ...patch }; saveDraft(slug, shot.rid, next); setDrafts(d => ({ ...d, [shot.rid]: next })); };
  const discard = () => { saveDraft(slug, shot.rid, null); setDrafts(({ [shot.rid]: _, ...rest }) => rest); };

  useEffect(() => { if (focus && shots.some(s => s.rid === focus.rid)) setRid(focus.rid); }, [focus]);
  const previsUrls = shots.map(s => s.previs).filter(Boolean).join('|');
  useEffect(() => {  // plans stored in the rendered previs files
    const urls = previsUrls.split('|').filter(u => u && !(u in stored));
    if (!urls.length) return;
    let alive = true;
    Promise.all(urls.map(u => fetchPlan(u).catch(() => null))).then(plans => {
      if (alive) setStored(old => ({ ...old, ...Object.fromEntries(urls.map((u, i) => [u, plans[i]])) }));
    });
    return () => { alive = false; };
  }, [previsUrls]);

  useEffect(() => {  // one renderer; overhead pan/zoom drive an orthographic plan camera
    if (!host.current) return undefined;
    const renderer = prepareRenderer(new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true }));
    renderer.setPixelRatio(1); renderer.setSize(WIDTH, HEIGHT, false);
    host.current.appendChild(renderer.domElement);
    const controls = new OrbitControls(new THREE.PerspectiveCamera(), renderer.domElement);
    const half = 5, top = new THREE.OrthographicCamera(-half * WIDTH / HEIGHT, half * WIDTH / HEIGHT, half, -half, 0.1, 80);
    top.up.set(0, 0, 1); top.position.set(0, 40, -2.4); top.lookAt(0, 0, -2.4);  // console at the top of the plan
    const aspect = a => { if (top.right !== half * a) { top.left = -half * a; top.right = half * a; top.updateProjectionMatrix(); } };
    const canvas = renderer.domElement, split = () => now.current.view === 'split';
    const onPlan = e => now.current.view === 'overhead' || (split() && e.offsetX < canvas.clientWidth / 2);  // the split's left half is the plan
    const pan = e => {
      if (!onPlan(e) || !(e.buttons & 1)) return;
      const k = (top.right - top.left) / top.zoom / (canvas.clientWidth * (split() ? SPLIT / WIDTH : 1));
      top.position.x += e.movementX * k; top.position.z += e.movementY * k; top.updateMatrixWorld(); now.current.draw();
    };
    const zoom = e => {
      if (!onPlan(e)) return;
      e.preventDefault(); top.zoom = Math.min(6, Math.max(0.4, top.zoom * (e.deltaY < 0 ? 1.12 : 1 / 1.12))); top.updateProjectionMatrix(); now.current.draw();
    };
    canvas.addEventListener('pointermove', pan); canvas.addEventListener('wheel', zoom, { passive: false });
    live.current = { renderer, controls, top, aspect, stage: null, guides: null };
    return () => {
      canvas.removeEventListener('pointermove', pan); canvas.removeEventListener('wheel', zoom);
      controls.dispose(); live.current.guides?.dispose(); live.current.stage?.dispose(); renderer.dispose(); canvas.remove(); live.current = null;
    };
  }, []);
  useEffect(() => {  // a new stage only when the set, its cards or the light change
    const ctx = live.current; if (!ctx) return;
    ctx.guides?.group.removeFromParent(); ctx.stage?.dispose();
    ctx.stage = buildStage(plan, { onLoad: () => { if (!now.current.rendering) now.current.draw(); } });
    ctx.controls.object = ctx.stage.camera;
    if (ctx.guides) ctx.stage.scene.add(ctx.guides.group);
  }, [plan.set, plan.mood, plan.set === 'parallax' ? JSON.stringify(plan.layers || null) : '']);
  const guideKey = JSON.stringify(shots.map(s => [s.shot, planOf(s), s.rid === shot?.rid]));
  useEffect(() => {  // every shot camera that shares this set
    const ctx = live.current; if (!ctx?.stage) return;
    if (ctx.guides) { ctx.guides.group.removeFromParent(); ctx.guides.dispose(); }
    ctx.guides = shotGuides(shots.filter(s => planOf(s).set === plan.set).map(s => ({ id: s.shot, plan: planOf(s), selected: s.rid === shot.rid })));
    ctx.stage.scene.add(ctx.guides.group);
  }, [guideKey]);

  const draw = () => {
    const ctx = live.current; if (!ctx?.stage) return;
    const { renderer, stage, guides } = ctx, split = view === 'split', top = view === 'overhead' || split;
    stage.pose(frame, plan); guides?.update(frame / (frames - 1), top ? 1.4 / ctx.top.zoom : 1);
    if (view === 'lens' || split) stage.shoot(frame, plan);
    else if (view === 'free') { stage.camera.fov = verticalFov(plan.lens); stage.camera.updateProjectionMatrix(); }
    const paint = (camera, plan, guided, x = 0, y = 0, w = WIDTH, h = HEIGHT) => {
      renderer.setViewport(x, y, w, h); renderer.setScissor(x, y, w, h);
      stage.roof(!plan); if (guides) guides.group.visible = guided;
      renderer.render(stage.scene, camera);
    };
    if (split) {  // one WebGL context, two viewports: the plan on the left, the lens letterboxed on the right
      const h = SPLIT * HEIGHT / WIDTH;
      renderer.setScissorTest(true); renderer.setScissor(0, 0, WIDTH, HEIGHT); renderer.setClearColor(0x000000); renderer.clear();  // black seam and letterbox
      ctx.aspect(SPLIT / HEIGHT); paint(ctx.top, true, true, 0, 0, SPLIT, HEIGHT);
      paint(stage.camera, false, false, WIDTH - SPLIT, (HEIGHT - h) / 2, SPLIT, h);
      renderer.setScissorTest(false); renderer.setViewport(0, 0, WIDTH, HEIGHT);
    } else {
      ctx.aspect(WIDTH / HEIGHT); paint(top ? ctx.top : stage.camera, top, view !== 'lens');
    }
  };
  now.current = { frame, frames, rid: shot?.rid, shots, view, draw, rendering };
  useEffect(() => { if (frame > frames - 1) setFrame(frames - 1); }, [frames]);  // a shorter shot: stay on its last frame
  useEffect(() => { if (!rendering) draw(); });  // previs scale: redraw after every change
  useEffect(() => {  // the free camera starts from the nearer key of this shot; orbiting redraws
    const ctx = live.current; if (!ctx?.stage) return;
    ctx.controls.enabled = view === 'free';
    if (view !== 'free') return;
    const keys = cameraKeys(plan), key = frame >= frames / 2 ? keys[keys.length - 1] : keys[0];
    ctx.stage.camera.position.set(...key[1]); ctx.controls.target.set(...key[2]); ctx.controls.update();
    const redraw = () => now.current.draw();
    ctx.controls.addEventListener('change', redraw); redraw();
    return () => ctx.controls.removeEventListener('change', redraw);
  }, [view, shot?.rid, plan.set, plan.mood]);
  useEffect(() => {  // 'shot' loops one shot; 'scene' cuts through the following shots in slate order
    if (!playing) return;
    const id = setInterval(() => {
      const { frame: f, frames: n, rid: at, shots: list } = now.current;
      if (f + 1 < n) { setFrame(f + 1); return; }
      const next = list[list.findIndex(s => s.rid === at) + 1];
      if (playing === 'shot') setFrame(0);
      else if (next) { setRid(next.rid); setFrame(0); }
      else setPlaying(false);
    }, 1000 / FPS);
    return () => clearInterval(id);
  }, [playing]);

  const step = d => { const i = shots.findIndex(s => s.rid === shot.rid), next = shots[i + d]; if (next) setRid(next.rid); };
  const onKey = e => {
    if (e.target.closest('input, select, textarea')) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); step(e.key === 'ArrowDown' ? 1 : -1); }
    else if (e.key === ' ' && !e.target.closest('button')) { e.preventDefault(); setPlaying(p => (p ? false : 'shot')); }
  };
  const fitOverhead = v => {  // frame every camera of this set and the actor's mark on the plan
    const top = live.current?.top; if (!top) return;
    live.current.aspect(v === 'split' ? SPLIT / HEIGHT : WIDTH / HEIGHT);
    const pts = shots.filter(s => planOf(s).set === plan.set).flatMap(s => [0, .25, .5, .75, 1].map(u => sampleCamera(planOf(s), u * (framesOf(planOf(s)) - 1)).position)).concat([[0, 0, 0.6]]);
    const xs = pts.map(q => q[0]), zs = pts.map(q => q[2]), [x0, x1, z0, z1] = [Math.min(...xs), Math.max(...xs), Math.min(...zs), Math.max(...zs)];
    top.position.x = (x0 + x1) / 2; top.position.z = (z0 + z1) / 2;
    top.zoom = Math.min(top.right / ((x1 - x0) / 2 + 1.5), top.top / ((z1 - z0) / 2 + 1.5));
    top.updateProjectionMatrix(); top.updateMatrixWorld();
  };
  const pickView = v => { if (v === 'overhead' || v === 'split') fitOverhead(v); setView(v); if (v !== 'lens' && playing === 'scene') setPlaying(false); };
  const playScene = () => { setView('lens'); if (playing !== 'scene') setFrame(0); setPlaying(p => (p === 'scene' ? false : 'scene')); };
  const capture = which => {  // the framed free camera becomes this shot's start or end key
    const ctx = live.current;
    const key = [which === 'start' ? 0 : 96,  // keys live on the 0..96 beat clock
      ctx.stage.camera.position.toArray().map(v => +v.toFixed(3)), ctx.controls.target.toArray().map(v => +v.toFixed(3))];
    const keys = cameraKeys(plan);
    edit({ keys: which === 'start' ? [key, keys[keys.length - 1]] : [keys[0], key] });
  };
  const render = async () => {
    const ctx = live.current, target = shot, p = plan;
    setPlaying(false); setRendering(true); setError('');
    try {
      // Always the full canvas through the shot camera, whatever the viewport showed (the split view uses two).
      ctx.renderer.setScissorTest(false); ctx.renderer.setViewport(0, 0, WIDTH, HEIGHT);
      ctx.stage.roof(true); if (ctx.guides) ctx.guides.group.visible = false;
      // WebCodecs + a WebM writer: exact timestamps, so the clip is 97 frames at 24 fps; the plan rides in the file.
      // A slate with an Actor Matte column also gets the same plan with the actor white on black (Layout Render mask),
      // one with a Pose Skeleton column the cast's joints as an OpenPose drawing (the acting, without the mannequin).
      const n = framesOf(p), passes = 1 + (target.matteCol >= 0) + (target.skeletonCol >= 0);
      let pass = 0;
      const encode = (canvas, draw, plan = null) => {
        const at = pass++ * n;
        return encodeCanvas(canvas, n, FPS, draw, done => { if (progress.current) progress.current.textContent = `${at + done}/${passes * n}`; }, plan);
      };
      const shoot = f => { ctx.stage.frame(f, p); ctx.renderer.render(ctx.stage.scene, ctx.stage.camera); };
      const blob = await encode(ctx.renderer.domElement, shoot, p);
      let matte = null, skeleton = null;
      if (target.matteCol >= 0) { ctx.stage.matte(true); try { matte = await encode(ctx.renderer.domElement, shoot); } finally { ctx.stage.matte(false); } }
      if (target.skeletonCol >= 0) {
        const canvas = Object.assign(document.createElement('canvas'), { width: WIDTH, height: HEIGHT }), pen = canvas.getContext('2d');
        skeleton = await encode(canvas, f => { ctx.stage.frame(f, p); drawSkeleton(pen, poseKeypoints(ctx.stage.scene, ctx.stage.camera)); });
      }
      if (await onRender(target, blob, matte, skeleton)) {
        saveDraft(slug, target.rid, null);
        setDrafts(({ [target.rid]: _, ...rest }) => rest); setRendered(r => ({ ...r, [target.rid]: p }));
      }
    } catch (e) { setError(e.message || String(e)); }
    setRendering(false); setView('lens');
  };

  const t = (key, params) => uiText('previs.' + key, params);
  if (!shot) return <div className="sheet-empty"><p>{t('empty')}</p></div>;
  const layoutable = shot.matteCol >= 0 && shot.skeletonCol >= 0;  // the Layout Render binds both
  return <div className="previs-stage" tabIndex={-1} onKeyDown={onKey}>
    <nav className="previs-shots" aria-label={t('shots')}>
      <h2>{t('shots')}</h2>
      {shots.map(s => {
        const p = planOf(s), state = statusOf(s);
        return <button type="button" key={s.rid} aria-current={s.rid === shot.rid} onClick={() => setRid(s.rid)}>
          {s.keyframe ? <img src={s.keyframe} alt="" loading="lazy" /> : <span className="previs-thumb" />}
          <span><b>{s.shot}</b><small>{t('move_' + (p.keys ? 'custom' : p.move))} · {p.lens}mm</small>
            <small className={'previs-state ' + state}>{t('state_' + state)}</small></span>
        </button>;
      })}
      <p className="previs-note">{t('keys')}</p>
    </nav>
    <section className="previs-view">
      <div className="previs-viewport">
        <div ref={host} className={'previs-canvas view-' + view} aria-label={t('viewport')} />
        <div className="previs-hud"><b>{shot.shot}</b> · {plan.lens}mm · {(frame / FPS).toFixed(2)}s</div>
        <div className="previs-views" role="group" aria-label={t('viewMode')}>{VIEWS.map(v =>
          <button type="button" key={v} aria-pressed={view === v} disabled={rendering}
            onClick={() => pickView(v)}>{t('view_' + v)}</button>)}</div>
        {view !== 'lens' && <p className="previs-hint">{t('hint_' + view)}</p>}
      </div>
      <div className="previs-timeline">
        <button type="button" onClick={() => setPlaying(p => (p === 'shot' ? false : 'shot'))} disabled={rendering}>{playing === 'shot' ? t('pause') : t('playShot')}</button>
        <button type="button" onClick={playScene} disabled={rendering}>{playing === 'scene' ? t('pause') : t('playScene')}</button>
        <input type="range" min="0" max={frames - 1} value={Math.min(frame, frames - 1)} aria-label={t('frame')} onChange={e => { setPlaying(false); setFrame(+e.target.value); }} />
        <span>{Math.min(frame, frames - 1)}/{frames - 1}</span>
      </div>
      <p className="previs-summary">{describePlan(plan)}</p>
    </section>
    <aside className="previs-controls" aria-label={t('inspector')}>
      <details className="previs-howto" open><summary>{t('howto')}</summary><ol>{[1, 2, 3, 4, 5].map(n => <li key={n}>{t('step' + n)}</li>)}</ol></details>
      <fieldset className="previs-fields" disabled={!writable || rendering}>
        {/* Switching to the parallax set hangs the shot's @SET image as its far card. */}
        {pick(t('set'), plan.set, SETS, v => edit({ set: v, ...(v === 'parallax' && shot.setAsset && !plan.layers ? { layers: [{ id: 'far', src: shot.setAsset.url }] } : {}) }), v => t('set_' + v))}
        {plan.set === 'observatory' && pick(t('beacon'), plan.beacon !== false, [true, false], v => edit({ beacon: v }), v => t(v ? 'beacon_on' : 'beacon_off'))}
        {plan.set === 'parallax' && <p className="previs-note">{plan.layers?.some(l => l.src) ? t('layersFromSet', { id: shot.setAsset?.id || 'SET' }) : t('layersPlaceholder')}</p>}
        {pick(t('action'), plan.action, ACTIONS, v => edit({ action: v }), v => t('action_' + v))}
        {pick(t('facing'), plan.facing, FACINGS, v => edit({ facing: v }), v => t('facing_' + v))}
        {pick(t('move'), plan.keys ? 'custom' : plan.move, MOVES, v => edit({ move: v, keys: null }), v => t('move_' + v))}
        {pick(t('lens'), plan.lens, LENSES, v => edit({ lens: v }), v => `${v}mm`)}
        {pick(t('duration'), plan.seconds, DURATIONS, v => edit({ seconds: v }), v => `${v} s`)}
        {pick(t('light'), plan.mood, MOODS, v => edit({ mood: v }), v => t('mood_' + v))}
        <fieldset className="previs-field"><legend>{t('framing')}</legend>
          <button type="button" disabled={view !== 'free'} onClick={() => capture('start')}>{t('setStart')}</button>
          <button type="button" disabled={view !== 'free'} onClick={() => capture('end')}>{t('setEnd')}</button>
          <button type="button" disabled={!plan.keys} onClick={() => edit({ keys: null })}>{t('resetPath')}</button>
          <button type="button" disabled={!drafts[shot.rid]} onClick={discard}>{t('discard')}</button>
        </fieldset>
      </fieldset>
      {error && <p className="sheet-save-error" role="alert">{error}</p>}
      {writable && <button type="button" className="primary previs-render" disabled={busy || rendering} onClick={render}>
        {rendering ? <>{t('rendering')} <span ref={progress} /></> : t('render')}</button>}
      {writable && onMotion && <button type="button" className="previs-motion" disabled={busy || rendering || !shot.previs || !!drafts[shot.rid]} onClick={() => onMotion(shot)}>{t('motion')}</button>}
      {writable && onLayout && layoutable && <button type="button" className="previs-motion" title={t('layoutHint')}
        disabled={busy || rendering || !shot.matte || !shot.skeleton || !!drafts[shot.rid]} onClick={() => onLayout(shot)}>{t('layout')}</button>}
      {writable && onMotion && (!shot.previs || drafts[shot.rid]) && <p className="previs-note">{t('renderFirst')}</p>}
      {writable && onLayout && layoutable && shot.previs && (!shot.matte || !shot.skeleton) && !drafts[shot.rid] && <p className="previs-note">{t('renderMatte')}</p>}
      <p className="previs-note">{t('note')}</p>
    </aside>
  </div>;
}
