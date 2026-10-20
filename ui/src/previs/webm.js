// Minimal WebM (Matroska) writer for one video track of encoded VP8/VP9 chunks. Frame-exact: every chunk keeps its own
// timestamp and the track declares its frame duration, so a 97-frame previs reads back as 97 frames at 24 fps.

const enc = new TextEncoder();

function size(n) {  // EBML variable-length size, 8 bytes (marker 0x01) is always valid
  const out = new Uint8Array(8); out[0] = 0x01;
  for (let i = 7; i >= 1; i--) { out[i] = n & 0xff; n = Math.floor(n / 256); }
  return out;
}
function uint(n, bytes = 0) {
  const out = []; do { out.unshift(n & 0xff); n = Math.floor(n / 256); } while (n > 0);
  while (out.length < bytes) out.unshift(0);
  return new Uint8Array(out);
}
function float64(x) { const b = new DataView(new ArrayBuffer(8)); b.setFloat64(0, x); return new Uint8Array(b.buffer); }
function concat(parts) {
  const total = parts.reduce((s, p) => s + p.length, 0), out = new Uint8Array(total); let at = 0;
  for (const p of parts) { out.set(p, at); at += p.length; }
  return out;
}
function el(id, payload) {  // id: array of bytes; payload: Uint8Array or array of child elements
  const body = payload instanceof Uint8Array ? payload : concat(payload);
  return concat([new Uint8Array(id), size(body.length), body]);
}

// chunks: [{ data: Uint8Array, timestamp: microseconds, key: boolean }]
export function muxWebM(chunks, { width, height, fps, codec = 'vp9' }) {
  const frameNs = Math.round(1e9 / fps);
  const header = el([0x1a, 0x45, 0xdf, 0xa3], [
    el([0x42, 0x86], uint(1)), el([0x42, 0xf7], uint(1)), el([0x42, 0xf2], uint(4)), el([0x42, 0xf3], uint(8)),
    el([0x42, 0x82], enc.encode('webm')), el([0x42, 0x87], uint(4)), el([0x42, 0x85], uint(2))]);
  const info = el([0x15, 0x49, 0xa9, 0x66], [
    el([0x2a, 0xd7, 0xb1], uint(1000000)),  // timecodes in milliseconds
    el([0x4d, 0x80], enc.encode('ZeroField previs')), el([0x57, 0x41], enc.encode('ZeroField previs')),
    el([0x44, 0x89], float64(chunks.length * 1000 / fps))]);
  const tracks = el([0x16, 0x54, 0xae, 0x6b], [el([0xae], [
    el([0xd7], uint(1)), el([0x73, 0xc5], uint(1)), el([0x83], uint(1)),
    el([0x86], enc.encode(codec === 'vp8' ? 'V_VP8' : 'V_VP9')),
    el([0x23, 0xe3, 0x83], uint(frameNs)),  // DefaultDuration: the reader's frame rate
    el([0xe0], [el([0xb0], uint(width)), el([0xba], uint(height))])])]);
  const blocks = chunks.map(c => {  // one cluster at t=0 (a previs is a few seconds, well inside int16 ms)
    const rel = Math.round(c.timestamp / 1000), head = new Uint8Array([0x81, (rel >> 8) & 0xff, rel & 0xff, c.key ? 0x80 : 0x00]);
    return el([0xa3], concat([head, c.data]));
  });
  const cluster = el([0x1f, 0x43, 0xb6, 0x75], [el([0xe7], uint(0)), ...blocks]);
  return concat([header, el([0x18, 0x53, 0x80, 0x67], [info, tracks, cluster])]);
}

// Encode frames drawn by draw(f) on canvas into a WebM blob with exact timestamps (WebCodecs).
export async function encodeCanvas(canvas, frames, fps, draw, onProgress) {
  const configs = [{ codec: 'vp09.00.31.08', name: 'vp9' }, { codec: 'vp8', name: 'vp8' }];
  let chosen = null;
  for (const c of configs) {
    const config = { codec: c.codec, width: canvas.width, height: canvas.height, bitrate: 8_000_000, framerate: fps };
    if ((await VideoEncoder.isConfigSupported(config)).supported) { chosen = { ...c, config }; break; }
  }
  if (!chosen) throw new Error('This browser cannot encode video (WebCodecs VP8/VP9).');
  const chunks = []; let failure = null;
  const encoder = new VideoEncoder({
    output: chunk => { const data = new Uint8Array(chunk.byteLength); chunk.copyTo(data); chunks.push({ data, timestamp: chunk.timestamp, key: chunk.type === 'key' }); },
    error: e => { failure = e; },
  });
  encoder.configure(chosen.config);
  for (let f = 0; f < frames; f++) {
    draw(f);
    const frame = new VideoFrame(canvas, { timestamp: Math.round(f * 1e6 / fps), duration: Math.round(1e6 / fps) });
    encoder.encode(frame, { keyFrame: f % fps === 0 }); frame.close();
    onProgress?.(f + 1);
    if (encoder.encodeQueueSize > 8) await new Promise(r => setTimeout(r, 0));
  }
  await encoder.flush(); encoder.close();
  if (failure) throw failure;
  chunks.sort((a, b) => a.timestamp - b.timestamp);
  return new Blob([muxWebM(chunks, { width: canvas.width, height: canvas.height, fps, codec: chosen.name })], { type: 'video/webm' });
}
