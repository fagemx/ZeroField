import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { useLocale } from '../i18n/react.jsx';
import { t as uiText } from '../i18n/index.js';
import { Dialog } from '../Dialog.jsx';
import { ACTIONS, FPS, FRAMES, HEIGHT, LENSES, MOODS, MOVES, WIDTH, cameraKeys, describePlan, verticalFov as verticalFovFor } from './plan.js';
import { buildStage, prepareRenderer } from './scene.js';
import { encodeCanvas } from './webm.js';

const pick = (label, value, options, onChange, text) => <fieldset className="previs-field"><legend>{label}</legend>
  {options.map(o => <button type="button" key={o} aria-pressed={value === o} onClick={() => onChange(o)}>{text(o)}</button>)}</fieldset>;

// Block a shot in 3D (set, actor action, camera move, lens, light), scrub it, then render the grey previs video
// the motion pass follows. The render is a real 97-frame, 24 fps clip at the shot resolution.
export default function PrevisEditor({ shot, plan: initial, busy, onRender, onClose }) {
  useLocale();
  const [plan, setPlan] = useState(initial);
  const [frame, setFrame] = useState(0), [playing, setPlaying] = useState(false);
  const [free, setFree] = useState(false), [rendering, setRendering] = useState(false), [error, setError] = useState('');
  const host = useRef(null), live = useRef(null), progress = useRef(null);
  const set = patch => setPlan(old => ({ ...old, ...patch }));

  useEffect(() => {  // one renderer per dialog; the stage is rebuilt when the set or light changes
    const renderer = prepareRenderer(new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true }));
    renderer.setPixelRatio(1); renderer.setSize(WIDTH, HEIGHT, false);
    host.current.appendChild(renderer.domElement);
    const controls = new OrbitControls(new THREE.PerspectiveCamera(), renderer.domElement);
    live.current = { renderer, controls, stage: null };
    return () => { controls.dispose(); live.current.stage?.dispose(); renderer.dispose(); renderer.domElement.remove(); live.current = null; };
  }, []);
  useEffect(() => {
    const ctx = live.current; if (!ctx) return;
    ctx.stage?.dispose(); ctx.stage = buildStage(plan);
    ctx.controls.object = ctx.stage.camera;
  }, [plan.set, plan.mood]);
  useEffect(() => {  // draw the current frame; in free framing the camera belongs to the user
    const ctx = live.current; if (!ctx?.stage) return;
    ctx.stage.pose(frame);
    if (!free) ctx.stage.shoot(frame);
    else { ctx.stage.camera.fov = verticalFovFor(plan.lens); ctx.stage.camera.updateProjectionMatrix(); }
    ctx.renderer.render(ctx.stage.scene, ctx.stage.camera);
  }, [plan, frame, free]);
  useEffect(() => {  // entering free framing starts from the nearer camera key; orbiting redraws
    const ctx = live.current; if (!ctx?.stage) return;
    ctx.controls.enabled = free;
    if (!free) return;
    const keys = cameraKeys(plan), key = frame >= FRAMES / 2 ? keys[keys.length - 1] : keys[0];
    ctx.stage.camera.position.set(...key[1]); ctx.controls.target.set(...key[2]); ctx.controls.update();
    const redraw = () => ctx.renderer.render(ctx.stage.scene, ctx.stage.camera);
    ctx.controls.addEventListener('change', redraw); redraw();
    return () => ctx.controls.removeEventListener('change', redraw);
  }, [free, plan.set, plan.mood]);
  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => setFrame(f => (f + 1) % FRAMES), 1000 / FPS);
    return () => clearInterval(id);
  }, [playing]);

  const capture = which => {  // store the framed camera as the start or end key of a custom path
    const ctx = live.current, cam = ctx.stage.camera, aim = ctx.controls.target;
    const key = [which === 'start' ? 0 : FRAMES - 1, cam.position.toArray().map(v => +v.toFixed(3)), aim.toArray().map(v => +v.toFixed(3))];
    const keys = cameraKeys(plan);
    set({ keys: which === 'start' ? [key, keys[keys.length - 1]] : [keys[0], key] });
  };

  const render = async () => {
    const ctx = live.current; setPlaying(false); setFree(false); setRendering(true); setError('');
    try {
      // WebCodecs + a WebM writer: every frame gets its exact timestamp, so the clip is 97 frames at 24 fps.
      const blob = await encodeCanvas(ctx.renderer.domElement, FRAMES, FPS, f => {
        ctx.stage.frame(f); ctx.renderer.render(ctx.stage.scene, ctx.stage.camera);
      }, n => { if (progress.current) progress.current.textContent = `${n}/${FRAMES}`; });
      setFrame(FRAMES - 1);
      await onRender(blob, plan);
    } catch (e) { setError(e.message || String(e)); }
    setRendering(false);
  };

  const t = key => uiText('previs.' + key);
  return <Dialog title={uiText('previs.title', { v0: shot })} className="previs-dialog" hideConfirm cancelLabel={uiText('previs.close')} onCancel={onClose}>
    <div className="previs-layout">
      <div className="previs-view">
        <div ref={host} className="previs-canvas" aria-label={t('viewport')} />
        <div className="previs-timeline">
          <button type="button" onClick={() => setPlaying(p => !p)} disabled={rendering}>{playing ? t('pause') : t('play')}</button>
          <input type="range" min="0" max={FRAMES - 1} value={frame} aria-label={t('frame')} onChange={e => { setPlaying(false); setFrame(+e.target.value); }} />
          <span>{(frame / FPS).toFixed(2)}s</span>
        </div>
        <p className="previs-summary">{describePlan(plan)}</p>
      </div>
      <div className="previs-controls">
        {pick(t('set'), plan.set, ['observatory', 'empty'], v => set({ set: v }), v => t('set_' + v))}
        {pick(t('action'), plan.action, ACTIONS, v => set({ action: v }), v => t('action_' + v))}
        {pick(t('move'), plan.keys ? 'custom' : plan.move, MOVES, v => set({ move: v, keys: null }), v => t('move_' + v))}
        {pick(t('lens'), plan.lens, LENSES, v => set({ lens: v }), v => `${v}mm`)}
        {pick(t('light'), plan.mood, MOODS, v => set({ mood: v }), v => t('mood_' + v))}
        <fieldset className="previs-field"><legend>{t('framing')}</legend>
          <button type="button" aria-pressed={free} onClick={() => setFree(f => !f)} disabled={rendering}>{t('frameCamera')}</button>
          <button type="button" disabled={!free} onClick={() => capture('start')}>{t('setStart')}</button>
          <button type="button" disabled={!free} onClick={() => capture('end')}>{t('setEnd')}</button>
          <button type="button" disabled={!plan.keys} onClick={() => set({ keys: null })}>{t('resetPath')}</button>
        </fieldset>
        {error && <p className="sheet-save-error" role="alert">{error}</p>}
        <button type="button" className="primary previs-render" disabled={busy || rendering} onClick={render}>{rendering ? <>{t('rendering')} <span ref={progress} /></> : t('render')}</button>
        <p className="previs-note">{t('note')}</p>
      </div>
    </div>
  </Dialog>;
}
