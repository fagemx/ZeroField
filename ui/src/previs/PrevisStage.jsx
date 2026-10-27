import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { useLocale } from '../i18n/react.jsx';
import { t as uiText } from '../i18n/index.js';
import { ACTIONS, DURATIONS, FACINGS, FPS, HEIGHT, LENSES, MOODS, MOVES, SETS, WIDTH, cameraKeys, defaultPlan, describePlan, framesOf, sampleCamera, verticalFov } from './plan.js';
import { addCastMember, codesOnSet, loadPlan, plansToLoad, readDraft, removeCastMember, resolveShotPlan, samePlan, savePlan, setCastCode, slateFromPlan, storable } from './storyPlan.js';
import { storyRequest } from '../storyModel.js';
import { buildStage, prepareRenderer, shotGuides } from './scene.js';
import { encodeCanvas, fetchPlan } from './webm.js';
import { drawSkeleton, poseKeypoints } from './skeleton.js';
import { createMotionDemoPlan } from './demoPlan.js';
import { applyOptions, ghostsFor } from '../proposalModel.js';
import { api } from '../api.js';
import { loadShotProposals, shotMetaKey, shotMetaReview } from './shotMetaModel.js';
import { GhostMarks, ShotMetaReview } from './ShotMetaReview.jsx';
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
function loadDraft(slug, rid) { try { return readDraft(JSON.parse(localStorage.getItem(draftKey(slug, rid)) || 'null')); } catch { return null; } }
function saveDraft(slug, rid, draft) {  // {plan, base}: edits not saved in the project yet stay in this browser (SPEC_20 R26)
  try { if (draft) localStorage.setItem(draftKey(slug, rid), JSON.stringify(draft)); else localStorage.removeItem(draftKey(slug, rid)); } catch { /* optional */ }
}
const pick = (label, value, options, onChange, text) => <fieldset className="previs-field"><legend>{label}</legend>
  {options.map(o => <button type="button" key={o} aria-pressed={value === o} onClick={() => onChange(o)}>{text(o)}</button>)}</fieldset>;

// The 3D stage of a slate: every shot in one set. Look through a shot's lens, see all shot cameras on an overhead
// plan, frame custom paths in a free camera, play a shot or the whole scene, and render a shot's grey previs
// (97 frames, 24 fps) into its Previs cell, its actor matte into Actor Matte and its pose skeleton into Pose Skeleton
// (the Layout Render frees the actor and takes the acting from the skeleton). A story shot's plan is saved in the project
// with a revision (SPEC_20 R26): Save plan stores it, a render stores it first, and edits not saved yet are a draft in
// this browser. The render still carries its plan in the WebM, the backup for shots outside the story sheets.
// A crew proposal of a new plan for a story shot (SPEC_20 R18, action shot_meta) is reviewed here too: its camera dashed and its
// marks ringed over the current plan, a preview of the whole proposed plan, and Approve / Reject through the assistant's decisions.
export default function PrevisStage({ slug, tabKey, proposals, onApplyProposal, onDismissProposal, shots, focus, writable, busy, onRender, onMotion, onLayout, onShot }) {
  useLocale();
  const [rid, setRid] = useState(() => (shots.some(s => s.rid === focus?.rid) ? focus.rid : shots[0]?.rid));
  const [drafts, setDrafts] = useState(() => Object.fromEntries(shots.map(s => [s.rid, loadDraft(slug, s.rid)]).filter(([, d]) => d)));
  const [embedded, setEmbedded] = useState({}), [rendered, setRendered] = useState({});  // url -> plan in that file; rid -> plan rendered here
  // saved: rid -> the plan the project stores ({plan, revision, ...}); castOptions: the production's cast codes (SPEC_20 R29);
  // conflict: a save someone else's revision refused ({rid, plan, currentRevision, stored}); synced: rid -> slate text written here.
  const [saved, setSaved] = useState({}), [castOptions, setCastOptions] = useState(null), [conflict, setConflict] = useState(null);
  const [saving, setSaving] = useState(false), [notice, setNotice] = useState(''), [synced, setSynced] = useState({});
  const [loadFailed, setLoadFailed] = useState({}), [retries, setRetries] = useState(0);
  // SPEC_20 R18: metaLists: shotId -> my pending 3D plan proposals for that shot; metaBusy: the decision on its way;
  // metaFailure: {id, shotId, message?} the last refusal (its text is the assistant's error for that proposal when it has one).
  const [metaLists, setMetaLists] = useState({}), [metaBusy, setMetaBusy] = useState(''), [metaFailure, setMetaFailure] = useState(null);
  const [previewMeta, setPreviewMeta] = useState(false), [metaReads, setMetaReads] = useState(0);
  const draftsNow = useRef(drafts), loading = useRef(new Set());
  draftsNow.current = drafts;
  const [view, setView] = useState('lens'), [frame, setFrame] = useState(0), [playing, setPlaying] = useState(false);
  const [rendering, setRendering] = useState(false), [error, setError] = useState('');
  const [showDemo, setShowDemo] = useState(false), [demoPlan] = useState(createMotionDemoPlan);
  // pip: the lens corner window in the free and overhead views; returnView: the view Look through came from (Esc goes back).
  const [pip, setPip] = useState(true), [returnView, setReturnView] = useState(null), [qa, setQa] = useState(null);
  const host = useRef(null), live = useRef(null), progress = useRef(null), now = useRef({}), framed = useRef(null), bumping = useRef(0);
  const [, setMoved] = useState(0);  // changes when the overhead plan pans or zooms, so its drag handles are placed again
  useEffect(() => () => cancelAnimationFrame(bumping.current), []);

  const planOf = s => resolveShotPlan(s, { draft: drafts[s.rid]?.plan, stored: saved[s.rid]?.plan, embedded: embedded[s.previs], rendered: rendered[s.rid] });
  const shot = shots.find(s => s.rid === rid) || shots[0];
  const ownPlan = showDemo ? demoPlan : shot ? planOf(shot) : defaultPlan();
  // SPEC_20 R18: a crew proposal of a whole new plan for a story shot. Its camera is dashed over the current plan and its marks
  // ring the overhead plan; Preview puts the proposed plan itself on stage (read-only) until Back.
  const metaShotId = !showDemo && shot && storable(shot) ? shot.shotId : null;
  const metaError = metaFailure && metaFailure.shotId === metaShotId
    ? (proposals || []).find(p => p.id === metaFailure.id)?.error || metaFailure.message || uiText('stage.metaFailed') : '';
  const metaReview = metaShotId ? shotMetaReview(metaLists[metaShotId], { plan: ownPlan, revision: saved[shot.rid]?.revision ?? shot.previsRevision ?? 0,
    writable: writable && Boolean(onApplyProposal && onDismissProposal), draft: Boolean(drafts[shot.rid]), error: metaError }) : null;
  const previewing = Boolean(previewMeta && metaReview);
  const plan = previewing ? metaReview.plan : ownPlan, frames = framesOf(plan);
  // A crew member's proposed camera for this shot: dashed on the plan, and one click puts the lens through it (a comparison, not a change).
  const ghost = showDemo || !shot || !proposals?.length ? null : ghostsFor(proposals, shots.filter(s => s.rid === shot.rid), tabKey, planOf)[0] || null;
  const [lookGhost, setLookGhost] = useState(false);
  useEffect(() => { if (!ghost) setLookGhost(false); }, [ghost?.id]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setPreviewMeta(false); }, [shot?.rid, metaReview?.id]);  // a preview belongs to one proposal on one shot
  // A story shot's stored plan is known (or it has none), so what the stage shows is what an edit starts from and a save replaces.
  const known = s => !storable(s) || (saved[s.rid] ? saved[s.rid].revision >= s.previsRevision : !s.previsStored);
  const revisionOf = s => saved[s.rid]?.revision ?? s.previsRevision ?? 0;
  // Saved in the project while its previs shows another plan, or none yet: render it before the motion pass.
  const unrendered = s => storable(s) && Boolean(saved[s.rid]?.plan) && (!s.previs || (Boolean(embedded[s.previs]) && !samePlan(saved[s.rid].plan, embedded[s.previs])));
  const statusOf = s => (drafts[s.rid] ? 'edited' : unrendered(s) ? 'saved' : s.previs ? 'rendered' : 'none');
  const keepDraft = (id, draft) => { saveDraft(slug, id, draft); setDrafts(({ [id]: _, ...rest }) => (draft ? { ...rest, [id]: draft } : rest)); };
  // An edit is a draft of the whole plan that remembers the stored revision it started from (its save names that revision).
  const change = next => { if (known(shot)) keepDraft(shot.rid, { plan: next, base: drafts[shot.rid]?.base ?? revisionOf(shot) }); };
  const edit = patch => change({ ...plan, ...patch });
  const discard = () => keepDraft(shot.rid, null);

  useEffect(() => { if (focus && shots.some(s => s.rid === focus.rid)) setRid(focus.rid); }, [focus]);
  useEffect(() => { if (shot) onShot?.(shot.rid); }, [shot?.rid]);  // the sheet's current shot follows the stage
  const previsUrls = shots.map(s => s.previs).filter(Boolean).join('|');
  useEffect(() => {  // plans carried in the rendered previs files
    const urls = previsUrls.split('|').filter(u => u && !(u in embedded));
    if (!urls.length) return;
    let alive = true;
    Promise.all(urls.map(u => fetchPlan(u).catch(() => null))).then(plans => {
      if (alive) setEmbedded(old => ({ ...old, ...Object.fromEntries(urls.map((u, i) => [u, plans[i]])) }));
    });
    return () => { alive = false; };
  }, [previsUrls]);
  // Plans stored in the project: every stored one, a newer revision than the one held, and the shot on stage (its cast codes).
  const keep = (id, state) => {
    setSaved(old => (old[id]?.revision > state.revision ? old : { ...old, [id]: state }));
    setCastOptions(state.castOptions);
  };
  const toLoad = plansToLoad(shots, saved, shot?.rid).filter(s => !loadFailed[s.rid]);
  useEffect(() => {
    for (const s of toLoad) {
      const key = s.rid + ':' + s.previsRevision;
      if (loading.current.has(key)) continue;
      loading.current.add(key);
      loadPlan(storyRequest, s.shotId).then(state => keep(s.rid, state))
        .catch(e => setLoadFailed(old => ({ ...old, [s.rid]: e.message || String(e) })))
        .finally(() => loading.current.delete(key));
    }
  }, [toLoad.map(s => s.rid + ':' + s.previsRevision).join('|'), retries]);
  useEffect(() => setNotice(''), [shot?.rid]);  // a note on what was just done belongs to the shot it was done on
  // SPEC_20 R18: my pending 3D plan proposals for the shot on stage, read again when the assistant's list of them changes, the
  // stored revision moves, or a decision was just made here. A crew member without the assistant (403) simply has none.
  const metaKey = shotMetaKey(proposals, metaShotId), storedRevision = shot ? saved[shot.rid]?.revision ?? null : null;
  useEffect(() => {
    if (!metaShotId || !slug) return undefined;
    let alive = true;
    loadShotProposals(api.get, slug, metaShotId).then(list => { if (alive) setMetaLists(old => ({ ...old, [metaShotId]: list })); })
      .catch(() => { if (alive) setMetaLists(old => (metaShotId in old ? old : { ...old, [metaShotId]: [] })); });
    return () => { alive = false; };
  }, [slug, metaShotId, metaKey, storedRevision, metaReads]);

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
  const guideKey = JSON.stringify(showDemo ? [['Motion demo', plan, true]] : [...shots.map(s => [s.shot, planOf(s), s.rid === shot?.rid]), ...(ghost ? [[ghost.label, ghost.plan, 'ghost']] : []),
    ...(metaReview ? [[metaReview.label, metaReview.plan, 'meta']] : []), plan.set]);
  useEffect(() => {  // every shot camera that shares this set, and the proposed cameras as dashed ghosts
    const ctx = live.current; if (!ctx?.stage) return;
    if (ctx.guides) { ctx.guides.group.removeFromParent(); ctx.guides.dispose(); }
    ctx.guides = shotGuides(showDemo ? [{ id: uiText('previs.demoTitle'), plan, selected: true }]
      : [...shots.filter(s => planOf(s).set === plan.set).map(s => ({ id: s.shot, plan: planOf(s), selected: s.rid === shot.rid })),
        ...(ghost ? [{ id: ghost.label + ' ✦', plan: ghost.plan, selected: false, ghost: true }] : []),
        ...(metaReview ? [{ id: (metaReview.label || shot.shot) + ' ✦', plan: metaReview.plan, selected: false, ghost: true }] : [])]);
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
  // SPEC_20 R26: store a story shot's plan over revision base. The draft it saved goes; edits made while it was on its way stay
  // a draft, now on top of the new revision. A refused revision becomes the conflict to settle; nothing is lost either way.
  const persist = async (target, p, base) => {
    setSaving(true); setError(''); setNotice('');
    try {
      const result = await savePlan(storyRequest, target.shotId, p, base);
      if (!result.ok) { setConflict({ rid: target.rid, plan: p, ...result.conflict }); return false; }
      setConflict(old => (old?.rid === target.rid ? null : old)); keep(target.rid, result.saved);
      const draft = draftsNow.current[target.rid];
      if (draft) keepDraft(target.rid, samePlan(draft.plan, p) ? null : { plan: draft.plan, base: result.saved.revision });
      return true;
    } catch (e) { setError(e.message || String(e)); return false; }
    finally { setSaving(false); }
  };
  const savable = s => storable(s) && known(s) && (Boolean(drafts[s.rid]) || !samePlan(planOf(s), saved[s.rid]?.plan));
  const savePlanNow = () => persist(shot, plan, drafts[shot.rid]?.base ?? revisionOf(shot));
  const reloadSaved = () => {  // the conflict's way back: the stored plan, without this browser's draft
    const { rid: id, stored } = conflict;
    setConflict(null); keepDraft(id, null); keep(id, stored);
  };
  const overwrite = () => {  // the conflict's other way: this plan, over the revision that is stored now
    const target = shots.find(s => s.rid === conflict.rid);
    if (target) persist(target, conflict.plan, conflict.currentRevision);
  };
  // SPEC_20 R29: the slate's Optical Rig and Camera Motion say what the plan does (a person's direct edit of those two cells).
  // What was written here stands in for the sheet's text until the sheet reloads with it (or with someone else's).
  const sheetSlate = s => ({ opticalRig: s.slate?.rig ?? '', cameraMotion: s.slate?.motion ?? '' });
  const slateOf = s => (synced[s.rid] && samePlan(synced[s.rid].from, sheetSlate(s)) ? synced[s.rid].fields : sheetSlate(s));
  const slateText = shot && !showDemo && storable(shot) ? slateFromPlan(plan, { rig: slateOf(shot).opticalRig }) : null;
  const slateDiffers = Boolean(slateText) && !samePlan(slateText, slateOf(shot));
  const syncSlate = async () => {
    const target = shot, fields = slateText;
    setSaving(true); setError(''); setNotice('');
    try {
      await storyRequest(`/shots/${target.shotId}`, 'PATCH', fields);
      setSynced(old => ({ ...old, [target.rid]: { fields, from: sheetSlate(target) } })); setNotice(uiText('stage.planSlateSynced'));
    } catch (e) { setError(e.message || String(e)); }
    finally { setSaving(false); }
  };
  const render = async () => {
    const ctx = live.current, target = shot, p = plan;
    setPlaying(false); setError('');
    // A story shot's plan is stored before its render (when it is not stored as it is), so a previs always shows a stored plan.
    if (!showDemo && storable(target) && (drafts[target.rid] || !samePlan(p, saved[target.rid]?.plan))
      && !(await persist(target, p, drafts[target.rid]?.base ?? revisionOf(target)))) return;
    setRendering(true);
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
        if (!storable(target)) keepDraft(target.rid, null);  // a story shot's draft went when its plan was stored
        setRendered(r => ({ ...r, [target.rid]: p }));
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
  // SPEC_20 R18: approve or reject the shot's proposed plan through the assistant's own proposal decisions. An approval stores it
  // as the next revision (the stage reads it back); a refusal (the stored plan moved since) keeps the proposal here with the reason.
  const decideMeta = async verb => {
    const review = metaReview, target = shot;
    if (!review || metaBusy) return;
    setMetaBusy(verb); setMetaFailure(null); setError(''); setNotice('');
    try {
      const result = await (verb === 'approve' ? onApplyProposal(review.proposal, undefined, {}) : onDismissProposal(review.proposal));
      const outcome = result?.proposal?.status;
      if (!result || (verb === 'approve' ? outcome !== 'applied' : outcome !== 'dismissed')) {
        setMetaFailure({ id: review.id, shotId: target.shotId, message: result?.proposal?.error || '' });
        // The stored plan may have moved on: read it, so the stage and the proposal's changes compare with what is stored now.
        if (verb === 'approve') loadPlan(storyRequest, target.shotId).then(state => keep(target.rid, state)).catch(() => {});
        return;
      }
      setPreviewMeta(false);
      if (verb === 'approve') {
        const state = await loadPlan(storyRequest, target.shotId);
        keep(target.rid, state);
        setNotice(uiText('stage.metaApplied', { revision: state.revision }));
      } else setNotice(uiText('stage.metaRejected'));
    } catch (e) { setMetaFailure({ id: review.id, shotId: target.shotId, message: e.message || String(e) }); }
    finally { setMetaBusy(''); setMetaReads(n => n + 1); }
  };
  if (!shot) return <div className="sheet-empty"><p>{t('empty')}</p></div>;
  const layoutable = shot.matteCol >= 0 && shot.skeletonCol >= 0;  // the Layout Render binds both
  // previewing: the proposed plan is on stage, to look at, not to edit, save or render.
  const editable = writable && !rendering && known(shot) && !previewing, stale = Boolean(drafts[shot.rid]) || unrendered(shot);  // stale: the previs is not this plan
  const stateLabel = state => (state === 'saved' ? uiText('stage.planStateSaved') : t('state_' + state));
  // SPEC_20 R29: everyone on set with the cast code they play, chosen from the cast sheet (each code once per shot).
  const onSet = [['actor', plan.code, uiText('stage.planActor')], ...(plan.cast || []).map((member, i) => [i, member.code, uiText('stage.planCastMember', { index: i + 1 })])];
  const taken = codesOnSet(plan), free = (castOptions || []).filter(option => !taken.includes(option.code));
  const storedNow = saved[shot.rid];
  return <div className="previs-stage" tabIndex={-1} onKeyDown={onKey}>
    <nav className="previs-shots" aria-label={t('shots')}>
      <h2>{t('shots')}</h2>
      {shots.map(s => {
        const p = planOf(s), state = statusOf(s);
        return <button type="button" key={s.rid} disabled={rendering} aria-current={!showDemo && s.rid === shot.rid} onClick={() => { setShowDemo(false); setPlaying(false); setFrame(0); setRid(s.rid); }}>
          {s.keyframe ? <img src={s.keyframe} alt="" loading="lazy" /> : <span className="previs-thumb" />}
          <span><b>{s.shot}</b><small>{t('move_' + (p.keys ? 'custom' : p.move))} · {p.lens}mm</small>
            <small className={'previs-state ' + state}>{stateLabel(state)}</small></span>
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
        <div className="previs-hud"><b>{showDemo ? t('demoTitle') : shot.shot}</b> · {(lookGhost && ghost ? ghost.plan : plan).lens}mm · {(frame / FPS).toFixed(2)}s{lookGhost && ghost && <> · {t('ghostHud')}</>}{previewing && <> · {uiText('stage.metaHud')}</>}</div>
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
          {metaReview && !previewing && <GhostMarks marks={metaReview.marks} project={project} />}
          <PlanHandles plan={plan} project={project} unproject={unproject} writable={writable && known(shot) && !previewing}
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
      {!showDemo && <BeatTrack plan={plan} frames={frames} frame={Math.min(frame, frames - 1)} writable={editable}
        onEdit={edit} onSeek={f => { setPlaying(false); setFrame(f); }} />}
      <p className="previs-summary">{showDemo ? t('demoBeats') : describePlan(plan)}</p>
    </section>
    <aside className="previs-controls" aria-label={t('inspector')}>
      {showDemo ? <section className="previs-howto"><h3>{t('demoTitle')}</h3><p>{t('demoDescription')}</p><ol>{[1, 2, 3, 4].map(n => <li key={n}>{t('demoStep' + n)}</li>)}</ol></section>
        : <details className="previs-howto"><summary>{t('howto')}</summary><ol>{[1, 2, 3, 4, 5].map(n => <li key={n}>{t('step' + n)}</li>)}</ol></details>}
      {!showDemo && <ShotMetaReview review={metaReview} previewing={previewing} busy={metaBusy} disabled={rendering || saving || busy}
        onPreview={() => { setLookGhost(false); setPreviewMeta(on => !on); }} onApprove={() => decideMeta('approve')} onReject={() => decideMeta('reject')} />}
      {!showDemo && <fieldset className="previs-fields" disabled={!editable}>
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
        {storable(shot) && castOptions && <fieldset className="previs-field previs-cast"><legend>{uiText('stage.planOnSet')}</legend>
          {onSet.map(([who, code, label]) => <label key={who}><span className="previs-note">{label}</span>{' '}
            <select value={code || ''} onChange={e => change(setCastCode(plan, who, e.target.value))}>
              <option value="">{uiText('stage.planCastNone')}</option>
              {code && !castOptions.some(option => option.code === code) && <option value={code}>{code} · {uiText('stage.castUnknown')}</option>}
              {castOptions.map(option => <option key={option.code} value={option.code} disabled={option.code !== code && taken.includes(option.code)}>{option.code} · {option.name}</option>)}
            </select>
            {who !== 'actor' && <button type="button" aria-label={uiText('stage.planCastRemove', { index: who + 1 })} onClick={() => change(removeCastMember(plan, who))}>×</button>}
          </label>)}
          {free.length > 0 && (plan.cast || []).length < 8 && <select value="" aria-label={uiText('stage.planCastAdd')} onChange={e => e.target.value && change(addCastMember(plan, e.target.value))}>
            <option value="">{uiText('stage.planCastAdd')}</option>
            {free.map(option => <option key={option.code} value={option.code}>{option.code} · {option.name}</option>)}
          </select>}
          {!castOptions.length && <p className="previs-note">{uiText('stage.planCastEmpty')}</p>}
        </fieldset>}
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
      {!showDemo && <CameraMove plan={plan} frames={frames} frame={Math.min(frame, frames - 1)} writable={editable} onEdit={edit} />}
      {ghost && <section className="previs-proposal" aria-label={uiText('shotProposal.title')}>
        <h3>{uiText('shotProposal.title')}</h3>
        <p className="previs-note">{t('ghostLegend', { shot: ghost.label })}</p>
        <div className="previs-proposal-actions">
          <button type="button" aria-pressed={lookGhost} disabled={rendering} onClick={() => { setPreviewMeta(false); setLookGhost(on => !on); }}>{t(lookGhost ? 'ghostBack' : 'ghostLook')}</button>
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
        {plan.fix ? <p className="previs-note">{t('autoFixOn')}{writable && !showDemo && <> <button type="button" className="previs-link" disabled={!editable} onClick={() => edit({ fix: undefined })}>{t('autoFixOff')}</button></>}</p>
          : !qa.ok && writable && !showDemo && <button type="button" className="previs-motion" disabled={!editable} onClick={() => edit({ fix: AUTO_FIX })}>{t('autoFix')}</button>}
      </section>}
      {/* SPEC_20 R26: someone stored another revision since this plan's edits began. Nothing is lost: reload the stored one, or save this one over it. */}
      {!showDemo && conflict?.rid === shot.rid && <section className="previs-proposal" role="alert" aria-label={uiText('stage.planConflictTitle')}>
        <h3>{uiText('stage.planConflictTitle')}</h3>
        <p className="previs-note">{uiText('stage.planConflict', { revision: conflict.currentRevision })}</p>
        <div className="previs-proposal-actions">
          <button type="button" className="apply" disabled={saving || rendering} onClick={reloadSaved}>{uiText('stage.planReload')}</button>
          {writable && <button type="button" disabled={saving || rendering} onClick={overwrite}>{uiText('stage.planOverwrite')}</button>}
        </div>
      </section>}
      {!showDemo && loadFailed[shot.rid] && <p className="sheet-save-error" role="alert">{uiText('stage.planLoadFailed', { message: loadFailed[shot.rid] })}{' '}
        <button type="button" className="previs-link" onClick={() => { setLoadFailed(({ [shot.rid]: _, ...rest }) => rest); setRetries(n => n + 1); }}>{uiText('stage.planRetry')}</button></p>}
      {error && <p className="sheet-save-error" role="alert">{error}</p>}
      {(writable || showDemo) && <button type="button" className="primary previs-render" disabled={busy || rendering || saving || previewing || (!showDemo && !known(shot))} onClick={render}>
        {rendering ? <>{t('rendering')} <span ref={progress} /></> : showDemo ? t('demoDownload') : t('render')}</button>}
      {!showDemo && writable && storable(shot) && <button type="button" className="previs-motion" title={uiText('stage.planSaveHint')}
        disabled={busy || rendering || saving || previewing || !savable(shot)} onClick={savePlanNow}>{saving ? uiText('stage.planSaving') : savable(shot) ? uiText('stage.planSave') : uiText('stage.planSaved')}</button>}
      {!showDemo && storable(shot) && <p className="previs-note">{!known(shot) ? uiText('stage.planLoading') : drafts[shot.rid] ? uiText('stage.planUnsaved')
        : storedNow?.plan ? uiText('stage.planStored', { revision: storedNow.revision }) : uiText('stage.planNotStored')}</p>}
      {!showDemo && writable && !previewing && slateDiffers && <button type="button" className="previs-motion" title={uiText('stage.planSyncSlateHint', { rig: slateText.opticalRig, motion: slateText.cameraMotion })}
        disabled={busy || rendering || saving} onClick={syncSlate}>{uiText('stage.planSyncSlate')}</button>}
      {notice && <p className="previs-note" role="status">{notice}</p>}
      {!showDemo && writable && onMotion && <button type="button" className="previs-motion" disabled={busy || rendering || previewing || !shot.previs || stale} onClick={() => onMotion(shot)}>{t('motion')}</button>}
      {!showDemo && writable && onLayout && layoutable && <button type="button" className="previs-motion" title={t('layoutHint')}
        disabled={busy || rendering || previewing || !shot.matte || !shot.skeleton || stale} onClick={() => onLayout(shot)}>{t('layout')}</button>}
      <button type="button" className="previs-motion" title={t('keyframePackHint')} disabled={rendering} onClick={exportPack}>{t('keyframePack')}</button>
      {!showDemo && writable && onMotion && (!shot.previs || stale) && <p className="previs-note">{t('renderFirst')}</p>}
      {!showDemo && writable && onLayout && layoutable && shot.previs && (!shot.matte || !shot.skeleton) && !stale && <p className="previs-note">{t('renderMatte')}</p>}
      <p className="previs-note">{showDemo ? t('demoLocal') : t('note')}</p>
    </aside>
  </div>;
}
