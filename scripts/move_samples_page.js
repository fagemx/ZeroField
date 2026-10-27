// Browser side of scripts/make_move_samples.mjs (SPEC_19 §4.4, B10): renders one sample loop per camera-move option of
// project_docs/look_catalog.json with the 3D Stage's own code. The set is the Stage's grey observatory (scene.js), the
// subject its grey mannequin (figure.js), the camera paths the Stage's sampleCamera where a move is a two-key path, and
// the clip goes through the Stage's WebCodecs export (webm.js). The node script turns the WebM into the H.264 loop.
// No model, no network: everything here is three.js primitives.
import * as THREE from 'three';
import { defaultPlan, sampleCamera, verticalFov } from '../ui/src/previs/plan.js';
import { buildStage, prepareRenderer } from '../ui/src/previs/scene.js';
import { encodeCanvas } from '../ui/src/previs/webm.js';

export const FPS = 24, FRAMES = 48, W = 480, H = 270, SUPER = 2, ASPECT = W / H;
const ease = t => t * t * (3 - 2 * t);
const clamp01 = t => Math.min(1, Math.max(0, t));
const lerp = (a, b, t) => a.map((v, i) => v + (b[i] - v) * t);
const TAU = Math.PI * 2;

// One subject for every option: the Stage's default mannequin on its mark in the grey observatory, sun off.
const BASE = { ...defaultPlan(), set: 'observatory', mood: 'grey', beacon: false, seconds: 4, action: 'stand', facing: 'room',
  figure: { build: 'man', outfit: 'jacket', hair: 'short', tone: 0 } };

// A two-key Stage camera path, sampled at progress t (0..1) through plan.js sampleCamera (its own ease in and out).
const keyed = (from, to) => t => sampleCamera({ ...BASE, keys: [[0, ...from], [96, ...to]] }, t * 96);

// Timelines map an output frame (0..47) to the move's progress.
//   crossfade: the move plays over the first 40 frames, the last 8 dissolve back to frame 0, so the loop closes.
//   pingpong:  there and back, eased at both ends.
//   periodic:  t = i / 48 for paths that repeat by themselves (every wobble has a whole number of cycles in 2 s).
const MOTION = 40;
const timeline = {
  crossfade: i => clamp01(i / (MOTION - 1)),
  pingpong: i => ease(1 - Math.abs(1 - 2 * i / FRAMES)),
  periodic: i => i / FRAMES,
};

// Each option: plan (the stage's subject and action), loop, lens (mm), camera(t, ctx) -> {position, aim, roll?},
// actor(t) -> the plan frame the subject is on, poster (output frame), and optional blur / focus.
export const MOVES = {
  'push-in': { loop: 'crossfade', lens: 35, poster: 26,
    camera: keyed([[0.35, 1.5, -5.6], [0, 1.15, 0]], [[0.1, 1.6, -1.2], [0, 1.52, 0]]) },
  'pull-out': { loop: 'crossfade', lens: 35, poster: 26,
    camera: keyed([[0.1, 1.6, -1.2], [0, 1.52, 0]], [[0.35, 1.5, -5.6], [0, 1.15, 0]]) },
  'crane-up': { loop: 'crossfade', lens: 30, poster: 10,
    camera: keyed([[0.7, 0.55, -2.9], [0, 1.45, 0]], [[0.45, 4.2, -2.3], [0, 0.6, 0.1]]) },
  'crane-down': { loop: 'crossfade', lens: 30, poster: 12,
    camera: keyed([[0.45, 4.2, -2.3], [0, 0.6, 0.1]], [[0.7, 1.55, -2.9], [0, 1.4, 0]]) },
  'orbit-180': { loop: 'crossfade', lens: 30, poster: 14,
    camera: t => { const a = (-90 + 180 * ease(t)) * Math.PI / 180, r = 2.15;
      return { position: [r * Math.sin(a), 1.6, -r * Math.cos(a)], aim: [0, 1.3, 0] }; } },
  pan: { loop: 'pingpong', lens: 35, poster: 15,
    camera: t => { const a = (36 - 72 * t) * Math.PI / 180, eye = [0, 1.6, -3.4];
      return { position: eye, aim: [eye[0] + 4 * Math.sin(a), 1.35, eye[2] + 4 * Math.cos(a)] }; } },
  // The subject walks across the room and the camera keeps level with his pelvis, a little ahead of him.
  tracking: { loop: 'crossfade', lens: 28, poster: 20,
    plan: { seconds: 6, action: 'stand', facing: 'room', use: [{ skill: 'walkTo', f0: 0, frames: 120, args: { from: [2.2, -0.7], to: [-2.2, -0.7], steps: 10 } }] },
    actor: t => 38 + t * 46,
    camera: (t, ctx) => { const p = ctx.pelvis(); return { position: [p.x + 0.15, 1.45, p.z - 2.7], aim: [p.x - 0.35, 1.15, p.z] }; } },
  // A locked medium shot with a whole-number-of-cycles wobble on position, aim and roll, so it loops by itself.
  handheld: { loop: 'periodic', lens: 35, poster: 10,
    camera: t => {
      const w = (amp, cycles, phase) => amp * Math.sin(TAU * cycles * t + phase);
      const d = [w(0.03, 1, 0.4) + w(0.012, 3, 1.3) + w(0.005, 7, 2.1), w(0.02, 2, 0.9) + w(0.008, 5, 2.6), w(0.025, 1, 2.0) + w(0.01, 4, 0.2)];
      const a = [w(0.045, 2, 1.7) + w(0.018, 5, 0.6) + w(0.008, 9, 1.1), w(0.03, 3, 0.1) + w(0.012, 6, 2.2), 0];
      return { position: [0.35 + d[0], 1.6 + d[1], -2.0 + d[2]], aim: [a[0], 1.45 + a[1], a[2]], roll: w(0.02, 1, 0.5) + w(0.01, 3, 1.9) };
    } },
  // Hold on the subject, whip to the console across the room, hold, whip back. Whips are smeared with sub-frames.
  'whip-pan': { loop: 'periodic', lens: 35, poster: 16, blur: 32,
    camera: t => {
      const f = t * FRAMES, seg = (a, b) => ease(clamp01((f - a) / (b - a)));
      const u = f < 24 ? seg(13, 19) : 1 - seg(37, 43), a = (0 + 78 * u) * Math.PI / 180, eye = [0, 1.6, -2.4];
      return { position: eye, aim: [eye[0] + 4 * Math.sin(a), 1.4 - 0.25 * u, eye[2] + 4 * Math.cos(a)] };
    } },
  // Close on the subject's face at frame left, the far side of the dome behind him: focus pulls from him to the far
  // console and back. focus(t) is the focus distance in dioptres (1 / metres), so the pull is even through the depth.
  'rack-focus': { loop: 'pingpong', lens: 35, poster: 22, hold: 0.32,
    plan: { facing: 'console', mark: [0, -0.9] },
    camera: () => ({ position: [0.3, 1.6, 0.4], aim: [0.9, 1.6, -9] }),
    focus: t => 1 / 1.3 + (1 / 9 - 1 / 1.3) * t, planes: { subject: 1 / 1.3, set: 1 / 9 }, bokeh: 15 },
  // Through the subject's eyes: the camera rides his head as he turns from the glass to the dial and reaches for it.
  pov: { loop: 'crossfade', lens: 24, poster: 34, near: 0.16,
    plan: { action: 'turnreach', facing: 'console' },
    actor: t => t * 50,
    camera: (t, ctx) => {
      const head = ctx.joint('head'), yaw = ctx.yaw(), bob = 0.012 * Math.sin(TAU * 2 * t);
      const fwd = [Math.sin(yaw), 0, Math.cos(yaw)], pitch = -0.12 - 0.42 * ease(clamp01((t - 0.35) / 0.65));
      const eye = [head.x + fwd[0] * 0.13, head.y + 0.05 + bob, head.z + fwd[2] * 0.13];
      return { position: eye, aim: [eye[0] + fwd[0], eye[1] + Math.tan(pitch), eye[2] + fwd[2]], roll: 0.025 * Math.sin(TAU * t + 0.6) };
    } },
  // Locked off; only the subject moves (he turns from the glass to the dial and reaches for it).
  static: { loop: 'crossfade', lens: 35, poster: 30,
    plan: { action: 'turnreach', facing: 'console' },
    actor: t => t * 50,
    camera: () => ({ position: [-2.5, 1.5, -1.35], aim: [-0.1, 1.15, 0.25] }) },
};

function renderMove(id) {
  const spec = MOVES[id];
  if (!spec) throw new Error('unknown move ' + id);
  const plan = { ...BASE, ...(spec.plan || {}), lens: spec.lens };
  const stage = buildStage(plan);
  stage.roof(true);
  const renderer = prepareRenderer(new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true }));
  renderer.setPixelRatio(1); renderer.setSize(W * SUPER, H * SUPER, false);
  const camera = stage.camera;
  camera.aspect = ASPECT; camera.fov = verticalFov(spec.lens, ASPECT); camera.near = spec.near ?? 0.05; camera.updateProjectionMatrix();
  // Depth of field for the rack focus: two layers, the set without the subject (he still casts his shadow) and the
  // subject alone on clear, each blurred by how far it is from the focus plane, the subject drawn over the set.
  const layer = document.createElement('canvas'); layer.width = W * SUPER; layer.height = H * SUPER;
  const layerPen = layer.getContext('2d');
  function actorOnly(on) {
    stage.scene.traverse(o => {
      if (!o.isMesh) return;
      if (o.userData.actor) { o.material.colorWrite = !on ? true : on === 'subject'; o.material.depthWrite = !on ? true : on === 'subject'; }
      else o.visible = on !== 'subject';
    });
    stage.scene.background = on === 'subject' ? null : sky;
  }
  const sky = stage.scene.background;
  function focusPass(fd) {
    const blur = plane => Math.min(spec.bokeh, spec.bokeh * Math.abs(fd - spec.planes[plane]) / Math.abs(spec.planes.subject - spec.planes.set));
    layerPen.clearRect(0, 0, layer.width, layer.height);
    for (const part of ['set', 'subject']) {
      actorOnly(part); renderer.setClearColor(0x000000, 0); renderer.render(stage.scene, camera);
      layerPen.filter = `blur(${blur(part).toFixed(2)}px)`; layerPen.drawImage(renderer.domElement, 0, 0); layerPen.filter = 'none';
    }
    actorOnly(false);
    return layer;
  }
  // The mannequin is built on the first pose, so its joints are looked up then (the plan has one person).
  const find = test => { let hit = null; stage.scene.traverse(o => { if (!hit && test(o)) hit = o; }); return hit; };
  const ctx = {
    joint: name => { stage.scene.updateMatrixWorld(true); return find(o => o.userData.kp === name).getWorldPosition(new THREE.Vector3()); },
    pelvis: () => ctx.joint('pelvis'),
    yaw: () => find(o => o.userData.actor && o.parent === stage.scene).rotation.y,
  };
  const out = document.createElement('canvas'); out.width = W; out.height = H;
  const pen = out.getContext('2d'); pen.imageSmoothingEnabled = true; pen.imageSmoothingQuality = 'high';
  const progressAt = i => timeline[spec.loop](i);
  // One picture at progress t into the canvas pen draws on, with alpha (the motion-blur and dissolve average).
  function shot(t, alpha = 1, target = pen) {
    const tt = spec.hold ? clamp01((t - spec.hold / 2) / (1 - spec.hold)) : t;  // rack focus: rest on each plane
    stage.pose(Math.round(spec.actor ? spec.actor(tt) : 0), plan);
    const c = spec.camera(tt, ctx);
    camera.position.set(...c.position); camera.lookAt(new THREE.Vector3(...c.aim));
    if (c.roll) camera.rotateZ(c.roll);
    camera.updateMatrixWorld(true);
    const picture = spec.focus ? focusPass(spec.focus(ease(tt))) : (renderer.render(stage.scene, camera), renderer.domElement);
    target.globalAlpha = alpha; target.drawImage(picture, 0, 0, W, H); target.globalAlpha = 1;
  }
  const first = document.createElement('canvas'); first.width = W; first.height = H;
  const firstPen = first.getContext('2d');
  function draw(i) {
    pen.fillStyle = '#000'; pen.fillRect(0, 0, W, H);
    if (spec.loop === 'crossfade' && i >= MOTION) {  // dissolve from the last frame of the move back to the first
      shot(1); pen.globalAlpha = (i - MOTION + 1) / (FRAMES - MOTION + 1); pen.drawImage(first, 0, 0); pen.globalAlpha = 1;
      return;
    }
    const t = progressAt(i);
    if (spec.blur) {  // a 360-degree shutter: the average of sub-frames across this frame's interval
      const t1 = progressAt(i + 1) - t, n = Math.abs(spec.camera(t + t1, ctx).aim[0] - spec.camera(t, ctx).aim[0]) > 0.02 ? spec.blur : 1;
      for (let k = 0; k < n; k++) shot(t + t1 * k / n, 1 / (k + 1));
    } else shot(t);
    if (i === 0) { firstPen.clearRect(0, 0, W, H); firstPen.drawImage(out, 0, 0); }
  }
  return { out, draw, dispose: () => { stage.dispose(); renderer.dispose(); renderer.forceContextLoss?.(); } };
}

const toBase64 = blob => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(String(reader.result).split(',')[1]); reader.onerror = reject; reader.readAsDataURL(blob);
});

window.zfMoves = {
  ids: Object.keys(MOVES),
  // -> JSON {ok, id, webm (base64), poster (PNG data URL), frames: [PNG data URL] (debug only)}
  async render(id, { debug = false } = {}) {
    try {
      const job = renderMove(id), spec = MOVES[id], stills = {}, keep = new Set([spec.poster, ...(debug ? [0, 8, 16, 24, 32, 40, 47] : [])]);
      const blob = await encodeCanvas(job.out, FRAMES, FPS, i => { job.draw(i); if (keep.has(i)) stills[i] = job.out.toDataURL('image/png'); });
      job.dispose();
      return JSON.stringify({ ok: true, id, webm: await toBase64(blob), poster: stills[spec.poster],
        frames: debug ? [0, 8, 16, 24, 32, 40, 47].map(i => stills[i]) : [] });
    } catch (error) {
      return JSON.stringify({ ok: false, id, error: String(error?.stack || error) });
    }
  },
};
window.zfMovesReady = true;
