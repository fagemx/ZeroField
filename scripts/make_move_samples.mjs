#!/usr/bin/env node
// Sample loops for the camera-move options (SPEC_19 §4.4, acceptance B10), rendered by the 3D Stage itself.
//
//   node scripts/make_move_samples.mjs [--only push-in,pan] [--debug <dir>] [--browser <msedge.exe>]
//
// Bundles scripts/move_samples_page.js (the Stage's scene.js, plan.js and webm.js) with esbuild from ui/node_modules,
// serves it on 127.0.0.1, opens it in headless Edge over the DevTools protocol (WebGL on SwiftShader, so no GPU), and
// records each move through the Stage's WebCodecs export. FFmpeg then writes, per non-Auto move option of
// project_docs/look_catalog.json:
//   ui/public/assets/look-samples/move/<id>.mp4   2 s loop, 480x270, H.264, +faststart, <= 400 KB
//   ui/public/assets/look-samples/move/<id>.webp  poster, 480x270, <= 60 KB
// and records them in ui/public/assets/look-samples/manifest.json (its move items only) and in the move items' preview
// in look_catalog.json (a line edit, so the rest of the file keeps its layout). No image or video model is involved.
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const UI_MODULES = join(ROOT, 'ui', 'node_modules');
const OUT_DIR = join(ROOT, 'ui', 'public', 'assets', 'look-samples', 'move');
const MANIFEST = join(ROOT, 'ui', 'public', 'assets', 'look-samples', 'manifest.json');
const CATALOG = join(ROOT, 'project_docs', 'look_catalog.json');
const URL_BASE = '/projects/assets/look-samples/move/';
const WORKFLOW = 'scripts/make_move_samples.mjs';  // the manifest's workflow is a repo path, as for the stills
const RENDERER = '3D Stage grey-box render in headless Edge (scripts/move_samples_page.js)';
const CLIP_MAX = 400 * 1024, POSTER_MAX = 60 * 1024, WIDTH = 480, HEIGHT = 270, SECONDS = 2;
const BROWSERS = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Microsoft/Edge/Application/msedge.exe'];

const args = process.argv.slice(2), flag = name => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : null; };
const only = flag('--only')?.split(',').filter(Boolean) || null, debugDir = flag('--debug'), browser = flag('--browser') || BROWSERS.find(existsSync);
if (!browser) throw new Error('No Edge found; pass --browser <path to msedge.exe or chrome.exe>.');

function run(cmd, argv) {
  const r = spawnSync(cmd, argv, { encoding: 'utf8', maxBuffer: 64 << 20 });
  if (r.status !== 0) throw new Error(`${cmd} ${argv.join(' ')} failed:\n${r.stderr || r.error}`);
  return r.stdout;
}

// The move options, in catalog order, without Auto.
const catalogText = readFileSync(CATALOG, 'utf8');
const moves = JSON.parse(catalogText).items.filter(item => item.kind === 'move' && item.promptText);
const wanted = only ? moves.filter(m => only.includes(m.id)) : moves;
if (only && wanted.length !== only.length) throw new Error('Unknown move in --only: ' + only.filter(id => !moves.some(m => m.id === id)).join(', '));

// 1. Bundle the page against the UI's own three.js and Stage modules.
const esbuild = await import(pathToFileURL(join(UI_MODULES, 'esbuild', 'lib', 'main.js')).href);
const bundle = await esbuild.build({ entryPoints: [join(ROOT, 'scripts', 'move_samples_page.js')], bundle: true, format: 'esm', write: false,
  nodePaths: [UI_MODULES], target: 'chrome120', logLevel: 'warning', legalComments: 'none' });
const pageJs = bundle.outputFiles[0].text;
const html = '<!doctype html><meta charset="utf-8"><title>move samples</title><body style="margin:0;background:#000"><script type="module" src="/page.js"></script>';

// 2. Serve it on loopback only.
const server = createServer((req, res) => {
  if (req.url === '/') { res.writeHead(200, { 'content-type': 'text/html' }); res.end(html); return; }
  if (req.url === '/page.js') { res.writeHead(200, { 'content-type': 'text/javascript' }); res.end(pageJs); return; }
  res.writeHead(404); res.end();
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const pageUrl = `http://127.0.0.1:${server.address().port}/`;

// 3. Headless Edge with the flags project_assistant/headless_previs.py uses (SwiftShader WebGL, nothing else on the network).
const profile = mkdtempSync(join(tmpdir(), 'zf-move-samples-'));
const edge = spawn(browser, ['--headless=new', '--remote-debugging-port=0', '--user-data-dir=' + profile, '--no-first-run',
  '--no-default-browser-check', '--disable-extensions', '--disable-sync', '--disable-background-networking', '--disable-component-update',
  '--disable-default-apps', '--mute-audio', '--disable-features=Translate,MediaRouter,OptimizationHints', '--use-angle=swiftshader',
  '--enable-unsafe-swiftshader', '--window-size=1280,720', 'about:blank'], { stdio: 'ignore' });
let ws = null;
const cleanup = () => { try { ws?.close(); } catch {} ; try { edge.kill(); } catch {} ; server.close(); setTimeout(() => { try { rmSync(profile, { recursive: true, force: true }); } catch {} }, 500); };
process.on('exit', () => { try { edge.kill(); } catch {} });
edge.on('exit', code => { for (const call of pending.values()) call.reject(new Error(`Edge exited (${code})`)); pending.clear(); });

const sleep = ms => new Promise(r => setTimeout(r, ms));
async function devtoolsPort() {
  const file = join(profile, 'DevToolsActivePort');
  for (let i = 0; i < 200; i++) { if (existsSync(file)) { const port = readFileSync(file, 'utf8').split('\n')[0].trim(); if (port) return port; } await sleep(100); }
  throw new Error('Edge did not open its DevTools port.');
}
let nextId = 0; const pending = new Map();
function send(method, params = {}) {
  const id = ++nextId;
  return new Promise((resolveCall, reject) => {
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`${method}: no answer from Edge in 5 minutes`)); }, 300_000);
    pending.set(id, { resolve: v => { clearTimeout(timer); resolveCall(v); }, reject: e => { clearTimeout(timer); reject(e); } });
    ws.send(JSON.stringify({ id, method, params }));
  });
}
async function evaluate(expression, awaitPromise = false) {
  const r = await send('Runtime.evaluate', { expression, awaitPromise, returnByValue: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
  return r.result.value;
}

const results = [];
try {
  const port = await devtoolsPort();
  let target = null;
  for (let i = 0; i < 50 && !target; i++) {
    target = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(t => t.type === 'page');
    if (!target) await sleep(100);
  }
  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  ws.onmessage = event => {
    const msg = JSON.parse(event.data), call = pending.get(msg.id);
    if (!call) return;
    pending.delete(msg.id);
    if (msg.error) call.reject(new Error(msg.error.message)); else call.resolve(msg.result);
  };
  await send('Page.enable'); await send('Runtime.enable');
  await send('Page.navigate', { url: pageUrl });
  for (let i = 0; i < 300 && !(await evaluate('window.zfMovesReady === true').catch(() => false)); i++) await sleep(100);
  if (!(await evaluate('window.zfMovesReady === true'))) throw new Error('The sample page did not load.');
  const pageIds = await evaluate('window.zfMoves.ids');
  const missing = wanted.filter(m => !pageIds.includes(m.id));
  if (missing.length) throw new Error('No camera path for: ' + missing.map(m => m.id).join(', '));

  mkdirSync(OUT_DIR, { recursive: true });
  const work = mkdtempSync(join(tmpdir(), 'zf-move-work-'));
  if (debugDir) mkdirSync(debugDir, { recursive: true });
  for (const move of wanted) {
    const started = Date.now();
    const result = JSON.parse(await evaluate(`window.zfMoves.render(${JSON.stringify(move.id)}, {debug: ${!!debugDir}})`, true));
    if (!result.ok) throw new Error(`${move.id}: ${result.error}`);
    const webm = join(work, move.id + '.webm'), png = join(work, move.id + '.png');
    writeFileSync(webm, Buffer.from(result.webm, 'base64'));
    writeFileSync(png, Buffer.from(result.poster.split(',')[1], 'base64'));
    if (debugDir) {  // frames 0, 8, ... 40, 47 as one 4x2 sheet, to look at the move and the loop seam
      result.frames.forEach((frame, i) => writeFileSync(join(work, `${move.id}-${i}.png`), Buffer.from(frame.split(',')[1], 'base64')));
      run('ffmpeg', ['-y', '-v', 'error', '-i', join(work, `${move.id}-%d.png`), '-vf', 'tile=4x2', join(debugDir, `${move.id}-sheet.png`)]);
    }
    const clip = encodeClip(webm, join(OUT_DIR, move.id + '.mp4'));
    const poster = encodePoster(png, join(OUT_DIR, move.id + '.webp'));
    results.push({ move, clip, poster });
    console.log(`${move.id.padEnd(11)} clip ${(clip.bytes / 1024).toFixed(1)} KB (crf ${clip.crf}, ${clip.frames} frames)  poster ${(poster.bytes / 1024).toFixed(1)} KB (q ${poster.quality})  ${((Date.now() - started) / 1000).toFixed(1)} s`);
  }
  rmSync(work, { recursive: true, force: true });
} finally {
  cleanup();
}

// H.264 at the lowest CRF that fits, then checked with ffprobe.
function encodeClip(src, dst) {
  for (const crf of [16, 18, 20, 22, 24, 26, 28, 30, 32]) {
    run('ffmpeg', ['-y', '-v', 'error', '-i', src, '-an', '-r', '24', '-vf', `scale=${WIDTH}:${HEIGHT}:flags=lanczos,format=yuv420p`,
      '-c:v', 'libx264', '-preset', 'slow', '-profile:v', 'high', '-crf', String(crf), '-g', '48', '-movflags', '+faststart', dst]);
    const bytes = readFileSync(dst).length;
    if (bytes <= CLIP_MAX) {
      const probe = JSON.parse(run('ffprobe', ['-v', 'error', '-select_streams', 'v:0', '-count_frames', '-show_entries',
        'stream=codec_name,width,height,nb_read_frames,r_frame_rate:format=duration', '-of', 'json', dst]));
      const s = probe.streams[0], duration = Number(probe.format.duration);
      if (s.codec_name !== 'h264' || s.width !== WIDTH || s.height !== HEIGHT || Math.abs(duration - SECONDS) > 0.05)
        throw new Error(`${dst}: unexpected ${JSON.stringify(probe)}`);
      const head = readFileSync(dst).subarray(0, 64 << 10), moov = head.indexOf('moov'), mdat = head.indexOf('mdat');
      if (moov < 0 || (mdat >= 0 && moov > mdat)) throw new Error(`${dst}: moov is not ahead of mdat (+faststart)`);
      return { bytes, crf, frames: Number(s.nb_read_frames) };
    }
  }
  throw new Error(`${dst}: over ${CLIP_MAX} bytes even at CRF 32`);
}

function encodePoster(src, dst) {
  for (const quality of [90, 82, 75, 68, 60, 50, 40]) {
    run('ffmpeg', ['-y', '-v', 'error', '-i', src, '-vf', `scale=${WIDTH}:${HEIGHT}:flags=lanczos`, '-c:v', 'libwebp', '-quality', String(quality), '-compression_level', '6', dst]);
    const bytes = readFileSync(dst).length;
    if (bytes <= POSTER_MAX) return { bytes, quality };
  }
  throw new Error(`${dst}: over ${POSTER_MAX} bytes even at quality 40`);
}

// 4. Manifest: this script owns the move items; other kinds' items are kept as they are.
const generatedAt = new Date().toISOString();
const manifest = existsSync(MANIFEST) ? JSON.parse(readFileSync(MANIFEST, 'utf8')) : { version: 1, items: [] };
const done = new Map(results.map(r => [r.move.id, r]));
const item = move => ({ kind: 'move', id: move.id, poster: URL_BASE + move.id + '.webp', clip: URL_BASE + move.id + '.mp4', workflow: WORKFLOW, renderer: RENDERER,
  model: null, seed: null, prompt: move.promptText, variant: null, generatedAt, license: 'CC0-1.0', author: 'ZeroField project (generated)' });
const kept = (manifest.items || []).filter(i => !(i.kind === 'move' && done.has(i.id)));
const order = id => moves.findIndex(m => m.id === id);
const items = [...kept.filter(i => i.kind !== 'move'), ...[...kept.filter(i => i.kind === 'move'), ...results.map(r => item(r.move))].sort((a, b) => order(a.id) - order(b.id))];
writeFileSync(MANIFEST, JSON.stringify({ version: 1, items }, null, 2) + '\n');

// 5. Catalog: add or replace "preview" on each rendered move item, touching only that item's text.
let text = readFileSync(CATALOG, 'utf8');
const eol = text.includes('\r\n') ? '\r\n' : '\n';  // a Windows checkout has CRLF; keep whatever the file has
for (const { move } of results) {
  const preview = `"preview": {"poster": "${URL_BASE}${move.id}.webp", "clip": "${URL_BASE}${move.id}.mp4"}`;
  const own = new RegExp(`(\\{"kind": "move", "id": "${move.id}",[^{}]*?"promptText": "(?:[^"\\\\]|\\\\.)*")(?:,\\s*"preview": \\{[^{}]*\\})?`);
  if (!own.test(text)) throw new Error(`look_catalog.json: cannot find the move item ${move.id}`);
  text = text.replace(own, (_, head) => `${head},${eol}     ${preview}`);
}
JSON.parse(text);  // still valid
writeFileSync(CATALOG, text);
console.log(`${results.length} move samples written to ${OUT_DIR}`);
