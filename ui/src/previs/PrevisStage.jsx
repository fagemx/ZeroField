import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { useLocale } from '../i18n/react.jsx';
import { t as uiText } from '../i18n/index.js';
import { ACTIONS, DURATIONS, FACINGS, FPS, HEIGHT, LENSES, MOODS, MOVES, SETS, WIDTH, cameraKeys, defaultPlan, describePlan, framesOf, sampleCamera, verticalFov } from './plan.js';
import { resolveShotPlan } from './storyPlan.js';
import { buildStage, prepareRenderer, shotGuides } from './scene.js';
import { encodeCanvas, fetchPlan } from './webm.js';
import { drawSkeleton, poseKeypoints } from './skeleton.js';
import { createMotionDemoPlan } from './demoPlan.js';
import { applyOptions, ghostsFor } from '../proposalModel.js';
import { moveCameraKey, moveDummy } from './blocking.js';
import { PlanHandles } from './PlanHandles.jsx';
import { BeatTrack } from './BeatTrack.jsx';
import { CameraMove } from './CameraMove.jsx';
import { Slider } from '../controls/Controls.jsx';

// split: the overhead plan and the shot lens side by side on one renderer (80.lv's layout view over the camera view).
export const VIEWS = ['split', 'lens', 'overhead', 'free'];
const SPLIT = WIDTH / 2 - 1;  // each half of the split view, with a 2 px seam
const PIP = { w: 320, h: 176, margin: 16 };  // the shot lens in the free and overhead views' lower right corner (canvas px)
const AUTO_FIX = { ground: true, slide: true, penetration: true };
const save = (blob, name) => {  // a local file to the browser's downloads
  const url = URL.createObjectURL(blob), link = Object.assign(document.createElement('a'), { href: url, download: name });
  link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
};
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
export default function PrevisStage({ slug, tabKey, proposals, onApplyProposal, onDismissProposal, shots, focus, writable, busy, onRender, onMotion, onLayout, onShot }) {
  useLocale();
  const [rid, setRid] = useState(() => (shots.some(s => s.rid === focus?.rid) ? focus.rid : shots[0]?.rid));
  const [drafts, setDrafts] = useState(() => Object.fromEntries(shots.map(s => [s.rid, loadDraft(slug, s.rid)]).filter(([, p]) => p)));
  const [stored, setStored] = useState({}), [rendered, setRendered] = useState({});  // url -> plan in that file; rid -> plan rendered here
  const [view, setView] = useState('lens'), [frame, setFrame] = useState(0), [playing, setPlaying] = useState(false);
  const [rendering, setRendering] = useState(false), [error, setError] = useState('');
  const [showDemo, setShowDemo] = useState(false), [demoPlan] = useState(createMotionDemoPlan);
  // pip: the lens corner window in the free and overhead views; returnView: the view Look through came from (Esc goes back).
  const [pip, setPip] = useState(true), [returnView, setReturnView] = useState(null), [qa, setQa] = useState(null);
  const host = useRef(null), live = useRef(null), progress = useRef(null), now = useRef({}), framed = useRef(null), bumping = useRef(0);
  const [, setMoved] = useState(0);  // changes when the overhead plan pans or zooms, so its drag handles are placed again
  useEffect(() => () => cancelAnimationFrame(bumping.current), []);

  const planOf = s => resolveShotPlan(s, { draft: drafts[s.rid], stored: stored[s.previs], rendered: rendered[s.rid] });
  const shot = shots.find(s => s.rid === rid) || shots[0];
  const plan = showDemo ? demoPlan : shot ? planOf(shot) : defaultPlan(), frames = framesOf(plan);
  // A crew member's proposed camera for this shot: dashed on the plan, and one click puts the lens through it (a comparison, not a change).
  const ghost = showDemo || !shot || !proposals?.length ? null : ghostsFor(proposals, shots.filter(s => s.rid === shot.rid), tabKey, planOf)[0] || null;
  const [lookGhost, setLookGhost] = useState(false);
  useEffect(() => { if (!ghost) setLookGhost(false); }, [ghost?.id]);  // eslint-disable-line react-hooks/exhaustive-deps
  const statusOf = s => (drafts[s.rid] ? 'edited' : s.previs ? 'rendered' : 'none');
  const edit = patch => { const next = { ...plan, ...patch }; saveDraft(slug, shot.rid, next); setDrafts(d => ({ ...d, [shot.rid]: next })); };
  const discard = () => { saveDraft(slug, shot.rid, null); setDrafts(({ [shot.rid]: _, ...rest }) => rest); };

  useEffect(() => { if (focus && shots.some(s => s.rid === focus.rid)) setRid(focus.rid); }, [focus]);
  useEffect(() => { if (shot) onShot?.(shot.rid); }, [shot?.rid]);  // the sheet's current shot follows the stage
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
      top.position.x += e.movementX * k; top.position.z += e.movementY * k; top.updateMatrixWorld(); now.current.draw(); now.current.bump();
    };
    const zoom = e => {
      if (!onPlan(e)) return;
      e.preventDefault(); top.zoom = Math.min(6, Math.max(0.4, top.zoom * (e.deltaY < 0 ? 1.12 : 1 / 1.12))); top.updateProjectionMatrix(); now.current.draw(); now.current.bump();
    };
    canvas.addEventListener('pointermove', pan); canvas.addEventListener('wheel', zoom, { passive: false });
    const lens = new THREE.PerspectiveCamera(verticalFov(35), WIDTH / HEIGHT, 0.05, 200);  // the PiP's shot camera; the free camera stays the user's
    live.current = { renderer, controls, top, aspect, lens, stage: null, guides: null };
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
  }, [plan.set, plan.mood, plan.presentation, JSON.stringify(plan.props || null), plan.set === 'parallax' ? JSON.stringify(plan.layers || null) : '']);
  // Motion QA of this shot's acting (scene.js motion: skills, pins, fixes), redone only when the motion changes.
  const motionKey = JSON.stringify([shot?.rid, plan.set, plan.mood, plan.use, plan.pins, plan.acts, plan.action, plan.facing, plan.seconds, plan.mark, plan.turn, plan.figure, plan.fix]);
  useEffect(() => { const ctx = live.current; if (ctx?.stage) setQa(ctx.stage.motion(plan).qa); }, [motionKey]);
  const guideKey = JSON.stringify(showDemo ? [['Motion demo', plan, true]] : [...shots.map(s => [s.shot, planOf(s), s.rid === shot?.rid]), ...(ghost ? [[ghost.label, ghost.plan, 'ghost']] : [])]);
  useEffect(() => {  // every shot camera that shares this set, and the proposed camera as a dashed ghost
    const ctx = live.current; if (!ctx?.stage) return;
    if (ctx.guides) { ctx.guides.group.removeFromParent(); ctx.guides.dispose(); }
    ctx.guides = shotGuides(showDemo ? [{ id: uiText('previs.demoTitle'), plan, selected: true }]
      : [...shots.filter(s => planOf(s).set === plan.set).map(s => ({ id: s.shot, plan: planOf(s), selected: s.rid === shot.rid })),
        ...(ghost ? [{ id: ghost.label + ' ✦', plan: ghost.plan, selected: false, ghost: true }] : [])]);
    ctx.stage.scene.add(ctx.guides.group);
  }, [guideKey]);

  const draw = () => {
    const ctx = live.current; if (!ctx?.stage) return;
    const { renderer, stage, guides } = ctx, split = view === 'split', top = view === 'overhead' || split;
    const lensPlan = lookGhost && ghost ? ghost.plan : plan;  // the camera the lens looks through
    stage.pose(frame, plan); guides?.update(frame / (frames - 1), top ? 1.4 / ctx.top.zoom : 1);
    if (view === 'lens' || split) stage.shoot(frame, lensPlan);
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
      if (pip && view !== 'lens') {  // the shot lens over the corner, clean like the render: roof on, no guides
        const c = sampleCamera(lensPlan, frame);
        ctx.lens.fov = verticalFov(lensPlan.lens); ctx.lens.updateProjectionMatrix(); ctx.lens.position.set(...c.position); ctx.lens.lookAt(...c.aim);
        renderer.setScissorTest(true); paint(ctx.lens, false, false, WIDTH - PIP.w - PIP.margin, PIP.margin, PIP.w, PIP.h);
        renderer.setScissorTest(false); renderer.setViewport(0, 0, WIDTH, HEIGHT);
      }
    }
  };
  now.current = { frame, frames, rid: shot?.rid, shots, view, draw, rendering, bump };
  // The overhead plan's handles sit on the plan, so they follow its pan and zoom (one redraw per animation frame at most).
  function bump() { if (!bumping.current) bumping.current = requestAnimationFrame(() => { bumping.current = 0; setMoved(n => n + 1); }); }
  const plane = () => {  // the plan's own box on the canvas: all of it, or the left half in the split view
    const ctx = live.current; if (!ctx) return null;
    const canvas = ctx.renderer.domElement, rect = canvas.getBoundingClientRect();
    ctx.top.updateMatrixWorld();
    return { top: ctx.top, rect, w: rect.width * (view === 'split' ? SPLIT / WIDTH : 1), h: rect.height };
  };
  const project = (x, z) => {
    const p = plane(); if (!p || !p.w) return null;
    const v = new THREE.Vector3(x, 0, z).project(p.top);
    return Math.abs(v.x) > 1.02 || Math.abs(v.y) > 1.02 ? null : { x: (v.x + 1) / 2 * p.w, y: (1 - v.y) / 2 * p.h };
  };
  const unproject = (clientX, clientY) => {
    const p = plane(); if (!p || !p.w) return null;
    const v = new THREE.Vector3(((clientX - p.rect.left) / p.w) * 2 - 1, 1 - ((clientY - p.rect.top) / p.h) * 2, 0).unproject(p.top);
    return [v.x, v.z];
  };
  useEffect(() => { if (frame > frames - 1) setFrame(frames - 1); }, [frames]);  // a shorter shot: stay on its last frame
  useEffect(() => { if (!rendering) draw(); });  // previs scale: redraw after every change
  useEffect(() => {  // the free camera starts from the nearer key of this shot; orbiting redraws
    const ctx = live.current; if (!ctx?.stage) return;
    ctx.controls.enabled = view === 'free';
    if (view !== 'free') return;
    const keys = cameraKeys(plan), key = frame >= frames / 2 ? keys[keys.length - 1] : keys[0], back = framed.current;
    framed.current = null;  // back from Look through: the framing it left
    ctx.stage.camera.position.set(...(back?.position || key[1])); ctx.controls.target.set(...(back?.target || key[2])); ctx.controls.update();
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

  const step = d => { if (rendering || showDemo) return; const i = shots.findIndex(s => s.rid === shot.rid), next = shots[i + d]; if (next) setRid(next.rid); };
  const onKey = e => {
    if (rendering) return;
    if (e.target.closest('input, select, textarea')) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); step(e.key === 'ArrowDown' ? 1 : -1); }
    else if (e.key === ' ' && !e.target.closest('button')) { e.preventDefault(); setPlaying(p => (p ? false : 'shot')); }
    else if (e.key === 'Escape' && view === 'lens' && returnView) { e.preventDefault(); exitLook(); }
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
  const pickView = v => { if (v === 'overhead' || v === 'split') fitOverhead(v); setView(v); setReturnView(null); if (v !== 'lens' && playing === 'scene') setPlaying(false); };
  const lookThrough = () => {  // full-frame lens; Esc (or Exit) returns to this view as it was framed
    const ctx = live.current;
    if (view === 'free' && ctx?.stage) framed.current = { position: ctx.stage.camera.position.toArray(), target: ctx.controls.target.toArray() };
    setReturnView(view); setView('lens');
  };
  const exitLook = () => { setView(returnView); setReturnView(null); };
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
      const n = framesOf(p), passes = showDemo ? 1 : 1 + (target.matteCol >= 0) + (target.skeletonCol >= 0);
      let pass = 0;
      const encode = (canvas, draw, plan = null) => {
        const at = pass++ * n;
        return encodeCanvas(canvas, n, FPS, draw, done => { if (progress.current) progress.current.textContent = `${at + done}/${passes * n}`; }, plan);
      };
      const shoot = f => { ctx.stage.frame(f, p); ctx.renderer.render(ctx.stage.scene, ctx.stage.camera); };
      const blob = await encode(ctx.renderer.domElement, shoot, p);
      if (showDemo) { save(blob, 'zerofield-motion-demo.webm'); return; }
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
    finally { setRendering(false); setView('lens'); }
  };
  // Keyframe Pack for first/last-frame workflows: the shot's frame 0 and last frame as clean 1280×704 PNGs (full canvas,
  // roof on, no guides or PiP, like the render) and a JSON with the camera at both ends and the plan.
  const exportPack = async () => {
    const ctx = live.current, p = plan, n = framesOf(p), cam = ctx.stage.camera, kept = [cam.position.clone(), cam.quaternion.clone(), cam.fov];
    setPlaying(false); setRendering(true); setError('');
    try {
      ctx.renderer.setScissorTest(false); ctx.renderer.setViewport(0, 0, WIDTH, HEIGHT);
      ctx.stage.roof(true); if (ctx.guides) ctx.guides.group.visible = false;
      const still = f => { ctx.stage.frame(f, p); ctx.renderer.render(ctx.stage.scene, cam); return new Promise(done => ctx.renderer.domElement.toBlob(done, 'image/png')); };
      const first = await still(0), last = await still(n - 1), end = f => ({ frame: f, ...sampleCamera(p, f) });
      const name = showDemo ? 'motion-demo' : shot.shot;
      const about = { shot: name, width: WIDTH, height: HEIGHT, fps: FPS, frames: n, lens: p.lens, camera: describePlan(p), first: end(0), last: end(n - 1), plan: p };
        save(first, `${showDemo ? 'motion-demo' : shot.shot}_first.png`); save(last, `${showDemo ? 'motion-demo' : shot.shot}_last.png`);
      save(new Blob([JSON.stringify(about, null, 2)], { type: 'application/json' }), `${name}_keyframes.json`);
    } catch (e) { setError(e.message || String(e)); }
    finally { cam.position.copy(kept[0]); cam.quaternion.copy(kept[1]); cam.fov = kept[2]; cam.updateProjectionMatrix(); setRendering(false); }
  };

  const t = (key, params) => uiText('previs.' + key, params);
  const decide = async work => { setError(''); try { if (!(await work())) setError(uiText('shotProposal.failed')); } catch (e) { setError(e.message || String(e)); } };
  if (!shot) return <div className="sheet-empty"><p>{t('empty')}</p></div>;
  const layoutable = shot.matteCol >= 0 && shot.skeletonCol >= 0;  // the Layout Render binds both
  return <div className="previs-stage" tabIndex={-1} onKeyDown={onKey}>
    <nav className="previs-shots" aria-label={t('shots')}>
      <h2>{t('shots')}</h2>
      {shots.map(s => {
        const p = planOf(s), state = statusOf(s);
        return <button type="button" key={s.rid} disabled={rendering} aria-current={!showDemo && s.rid === shot.rid} onClick={() => { setShowDemo(false); setPlaying(false); setFrame(0); setRid(s.rid); }}>
          {s.keyframe ? <img src={s.keyframe} alt="" loading="lazy" /> : <span className="previs-thumb" />}
          <span><b>{s.shot}</b><small>{t('move_' + (p.keys ? 'custom' : p.move))} · {p.lens}mm</small>
            <small className={'previs-state ' + state}>{t('state_' + state)}</small></span>
        </button>;
      })}
      <p className="previs-note">{t('keys')}</p>
      <button type="button" aria-pressed={showDemo} disabled={rendering} onClick={() => { setShowDemo(!showDemo); setPlaying(false); setFrame(0); setView('lens'); }}>
        <span><b>{showDemo ? t('demoBack') : t('demoTitle')}</b><small>{t('demoBeats')}</small></span>
      </button>
    </nav>
    <section className="previs-view">
      <div className="previs-viewport">
        <div ref={host} className={'previs-canvas view-' + view} aria-label={t('viewport')} />
        <div className="previs-hud"><b>{showDemo ? t('demoTitle') : shot.shot}</b> · {(lookGhost && ghost ? ghost.plan : plan).lens}mm · {(frame / FPS).toFixed(2)}s{lookGhost && ghost && <> · {t('ghostHud')}</>}</div>
        <div className="previs-views" role="group" aria-label={t('viewMode')}>{VIEWS.map(v =>
          <button type="button" key={v} aria-pressed={view === v} disabled={rendering}
            onClick={() => pickView(v)}>{t('view_' + v)}</button>)}
          {(view === 'free' || view === 'overhead') && <>
            <button type="button" aria-pressed={pip} title={t('pipHint')} onClick={() => setPip(on => !on)}>{t('pip')}</button>
            <button type="button" onClick={lookThrough} disabled={rendering}>{t('lookThrough')}</button></>}
          {view === 'lens' && returnView && <button type="button" onClick={exitLook}>{t('exitLookThrough')}</button>}
        </div>
        {pip && (view === 'free' || view === 'overhead') && <div className="previs-pip" aria-hidden="true"><span>{t('view_lens')}</span></div>}
        {(view === 'overhead' || view === 'split') && !showDemo && !rendering && <div className="plan-layer" role="group" aria-label={t('dragHint')}>
          <PlanHandles plan={plan} project={project} unproject={unproject} writable={writable}
            onDummy={(id, point, options) => edit(moveDummy(plan, id, point, options))} onKey={(index, point, options) => edit(moveCameraKey(plan, index, point, options))} /></div>}
        {view === 'lens' && returnView ? <p className="previs-hint">{t('hint_return', { view: t('view_' + returnView) })}</p>
          : view !== 'lens' && <p className={'previs-hint' + (pip && view !== 'split' ? ' beside-pip' : '')}>{t('hint_' + view)}</p>}
      </div>
      <div className="previs-timeline">
        <button type="button" onClick={() => setPlaying(p => (p === 'shot' ? false : 'shot'))} disabled={rendering}>{playing === 'shot' ? t('pause') : t('playShot')}</button>
        {!showDemo && <button type="button" onClick={playScene} disabled={rendering}>{playing === 'scene' ? t('pause') : t('playScene')}</button>}
        <span className="previs-scrub ctl-palette"><Slider value={Math.min(frame, frames - 1)} min={0} max={frames - 1} step={1} ariaLabel={t('frame')}
          valueText={f => `${f} · ${(f / FPS).toFixed(2)} s`} onChange={f => { setPlaying(false); setFrame(f); }} /></span>
        <span>{Math.min(frame, frames - 1)}/{frames - 1}</span>
      </div>
      {!showDemo && <BeatTrack plan={plan} frames={frames} frame={Math.min(frame, frames - 1)} writable={writable && !rendering}
        onEdit={edit} onSeek={f => { setPlaying(false); setFrame(f); }} />}
      <p className="previs-summary">{showDemo ? t('demoBeats') : describePlan(plan)}</p>
    </section>
    <aside className="previs-controls" aria-label={t('inspector')}>
      {showDemo ? <section className="previs-howto"><h3>{t('demoTitle')}</h3><p>{t('demoDescription')}</p><ol>{[1, 2, 3, 4].map(n => <li key={n}>{t('demoStep' + n)}</li>)}</ol></section>
        : <details className="previs-howto"><summary>{t('howto')}</summary><ol>{[1, 2, 3, 4, 5].map(n => <li key={n}>{t('step' + n)}</li>)}</ol></details>}
      {!showDemo && <fieldset className="previs-fields" disabled={!writable || rendering}>
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
        {/* Only the framing actions that can act now (CozyClay R2/R3): set start/end in the free view, otherwise one
            button that opens it; the preset and discard only once there is a path or an edit to undo. */}
        <fieldset className="previs-field"><legend>{t('framing')}</legend>
          {view === 'free' ? <>
            <button type="button" onClick={() => capture('start')}>{t('setStart')}</button>
            <button type="button" onClick={() => capture('end')}>{t('setEnd')}</button>
          </> : <button type="button" onClick={() => pickView('free')}>{t('frameCustom')}</button>}
          {plan.keys && <button type="button" onClick={() => edit({ keys: null })}>{t('resetPath')}</button>}
          {drafts[shot.rid] && <button type="button" onClick={discard}>{t('discard')}</button>}
        </fieldset>
      </fieldset>}
      {!showDemo && <CameraMove plan={plan} frames={frames} frame={Math.min(frame, frames - 1)} writable={writable && !rendering} onEdit={edit} />}
      {ghost && <section className="previs-proposal" aria-label={uiText('shotProposal.title')}>
        <h3>{uiText('shotProposal.title')}</h3>
        <p className="previs-note">{t('ghostLegend', { shot: ghost.label })}</p>
        <div className="previs-proposal-actions">
          <button type="button" aria-pressed={lookGhost} disabled={rendering} onClick={() => setLookGhost(on => !on)}>{t(lookGhost ? 'ghostBack' : 'ghostLook')}</button>
          {writable && onApplyProposal && <button type="button" className="apply" disabled={rendering || busy}
            onClick={() => decide(() => onApplyProposal(ghost.entry.proposal, ghost.entry.proposal.content, applyOptions(ghost.entry)))}>
            {uiText(ghost.entry.partial ? 'shotProposal.apply' : 'shotProposal.applyAll', { count: ghost.entry.size })}</button>}
          {writable && onDismissProposal && <button type="button" disabled={rendering || busy} onClick={() => decide(() => onDismissProposal(ghost.entry.proposal))}>{uiText('shotProposal.reject')}</button>}
        </div>
      </section>}
      {qa && <section className={'previs-qa' + (qa.ok ? ' clean' : '')} aria-label={t('qaTitle')} aria-live="polite">
        {qa.ok ? <p className="previs-qa-pill">{t('qaClean')}</p> : <>
          <p className="previs-qa-pill">{t('qaIssues', { count: qa.groups.length })}</p>
          <ul>{qa.groups.map(g => <li key={g.kind + g.subject}>
            <b>{t('qaIssue', { kind: g.kind, subject: g.subject, worst: g.worst, frame: g.worstFrame })}</b><small>{g.hint}</small></li>)}</ul>
        </>}
        {plan.fix ? <p className="previs-note">{t('autoFixOn')}{writable && !showDemo && <> <button type="button" className="previs-link" disabled={rendering} onClick={() => edit({ fix: undefined })}>{t('autoFixOff')}</button></>}</p>
          : !qa.ok && writable && !showDemo && <button type="button" className="previs-motion" disabled={rendering} onClick={() => edit({ fix: AUTO_FIX })}>{t('autoFix')}</button>}
      </section>}
      {error && <p className="sheet-save-error" role="alert">{error}</p>}
      {(writable || showDemo) && <button type="button" className="primary previs-render" disabled={busy || rendering} onClick={render}>
        {rendering ? <>{t('rendering')} <span ref={progress} /></> : showDemo ? t('demoDownload') : t('render')}</button>}
      {!showDemo && writable && onMotion && <button type="button" className="previs-motion" disabled={busy || rendering || !shot.previs || !!drafts[shot.rid]} onClick={() => onMotion(shot)}>{t('motion')}</button>}
      {!showDemo && writable && onLayout && layoutable && <button type="button" className="previs-motion" title={t('layoutHint')}
        disabled={busy || rendering || !shot.matte || !shot.skeleton || !!drafts[shot.rid]} onClick={() => onLayout(shot)}>{t('layout')}</button>}
      <button type="button" className="previs-motion" title={t('keyframePackHint')} disabled={rendering} onClick={exportPack}>{t('keyframePack')}</button>
      {!showDemo && writable && onMotion && (!shot.previs || drafts[shot.rid]) && <p className="previs-note">{t('renderFirst')}</p>}
      {!showDemo && writable && onLayout && layoutable && shot.previs && (!shot.matte || !shot.skeleton) && !drafts[shot.rid] && <p className="previs-note">{t('renderMatte')}</p>}
      <p className="previs-note">{showDemo ? t('demoLocal') : t('note')}</p>
    </aside>
  </div>;
}
