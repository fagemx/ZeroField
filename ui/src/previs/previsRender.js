// SPEC_20 R28: a contact sheet of a plan, drawn by the same stage the 3D Stage renders (scene.js, figure.js) through the
// shot camera. The previs-solver page runs it in a headless browser for a crew proposal's preview; nothing here touches
// the network except the plan's own card images, which the page's host serves.
import * as THREE from 'three';
import { FPS, HEIGHT, WIDTH, framesOf, parallaxLayers } from './plan.js';
import { buildStage, prepareRenderer } from './scene.js';

export const SHEET = { columns: 3, rows: 2, scale: 0.5, header: 44, caption: 26, gap: 6 };
// The frames a sheet shows: start, four between, the last.
export const sheetFrames = plan => { const last = framesOf(plan) - 1; return [0, 0.2, 0.4, 0.6, 0.8, 1].map(t => Math.round(t * last)); };

// Waits for the cards' images (at most waitMs), renders each frame at half size and lays them out with a header line.
// Returns {dataUrl (PNG), width, height, frames: [{frame, seconds}]}.
export async function contactSheet(plan, { title = '', frames = sheetFrames(plan), waitMs = 4000 } = {}) {
  const images = parallaxLayers(plan).filter(layer => layer.src).length;
  let loaded = 0, done;
  const ready = new Promise(resolve => { done = resolve; });
  if (!images) done();
  const stage = buildStage(plan, { onLoad: () => { if (++loaded >= images) done(); } });
  await Promise.race([ready, new Promise(resolve => setTimeout(resolve, waitMs))]);
  const w = Math.round(WIDTH * SHEET.scale), h = Math.round(HEIGHT * SHEET.scale), { columns, gap, header, caption } = SHEET;
  const rows = Math.ceil(frames.length / columns);
  const renderer = prepareRenderer(new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true }));
  renderer.setPixelRatio(1); renderer.setSize(w, h, false);
  const sheet = document.createElement('canvas');
  sheet.width = columns * w + (columns + 1) * gap; sheet.height = header + rows * (h + caption) + (rows + 1) * gap;
  const pen = sheet.getContext('2d');
  pen.fillStyle = '#11151b'; pen.fillRect(0, 0, sheet.width, sheet.height);
  pen.fillStyle = '#e6eaf0'; pen.font = '600 20px system-ui, sans-serif'; pen.textBaseline = 'middle';
  pen.fillText(title, gap * 2, header / 2 + gap / 2);
  try {
    stage.roof(true);
    frames.forEach((f, i) => {
      const x = gap + (i % columns) * (w + gap), y = header + gap + Math.floor(i / columns) * (h + caption + gap);
      stage.frame(f, plan); renderer.render(stage.scene, stage.camera);
      pen.drawImage(renderer.domElement, x, y, w, h);
      pen.fillStyle = '#9aa4b2'; pen.font = '500 15px system-ui, sans-serif';
      pen.fillText(`${(f / FPS).toFixed(2)} s · f${f}`, x + 4, y + h + caption / 2);
    });
    return { dataUrl: sheet.toDataURL('image/png'), width: sheet.width, height: sheet.height, frames: frames.map(f => ({ frame: f, seconds: Math.round(f / FPS * 1000) / 1000 })) };
  } finally {
    stage.dispose(); renderer.dispose(); renderer.forceContextLoss?.();
  }
}
