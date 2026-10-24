// Pure math behind the control kit: number fields, sliders, timecodes, range handles and easing curves.
// No DOM and no React here, so the node tests import this file directly and Controls.jsx only wires events to it.

const finite = n => typeof n === 'number' && Number.isFinite(n);
const noNegZero = n => (Object.is(n, -0) ? 0 : n);
// 0.1 + 0.2 style float noise is rounded away at 10 decimals, far below any step a control uses.
const tidy = n => noNegZero(Number(n.toFixed(10)));
const decimalsOf = n => {
  const text = String(Math.abs(n)), exponent = /e-(\d+)$/.exec(text);
  return exponent ? Number(exponent[1]) + (/\.(\d+)e/.exec(text)?.[1].length || 0) : text.split('.')[1]?.length || 0;
};

// NaN becomes the lower bound (0 when there is none); a reversed min/max pair is swapped instead of trusted.
export function clamp(value, min = -Infinity, max = Infinity) {
  let lo = finite(min) ? min : -Infinity, hi = finite(max) ? max : Infinity;
  if (lo > hi) [lo, hi] = [hi, lo];
  if (typeof value !== 'number' || Number.isNaN(value)) return lo === -Infinity ? 0 : lo;
  return noNegZero(Math.min(Math.max(value, lo), hi));
}

// Nearest multiple of step counted from origin (min 0.15, step 0.1 gives 0.15, 0.25, ...). Halves round up.
// A missing or non-positive step returns the value unchanged.
export function roundToStep(value, step, origin = 0) {
  if (!finite(value) || !finite(step) || step <= 0) return value;
  const base = finite(origin) ? origin : 0, places = Math.min(10, Math.max(decimalsOf(step), decimalsOf(base)));
  return noNegZero(Number((base + Math.round((value - base) / step) * step).toFixed(places)));
}

// 0..1 position of value inside [min, max]; a flat or invalid range gives 0.
export function valueToFraction(value, min, max) {
  if (!finite(value) || !finite(min) || !finite(max) || max === min) return 0;
  return clamp((value - min) / (max - min), 0, 1);
}

// Inverse of valueToFraction, on the step grid that starts at min. The two ends are exact even when max is off-grid.
export function fractionToValue(fraction, min, max, step) {
  const f = clamp(fraction, 0, 1);
  if (f <= 0) return min;
  if (f >= 1) return max;
  return clamp(roundToStep(min + f * (max - min), step, min), Math.min(min, max), Math.max(min, max));
}

// Pull value to the nearest point within threshold (first point wins a tie): {value, snapped} where snapped is that point or null.
export function snapValue(value, points, threshold) {
  if (!finite(value) || !Array.isArray(points) || !(threshold > 0)) return { value, snapped: null };
  let best = null, gap = Infinity;
  for (const point of points) {
    const distance = finite(point) ? Math.abs(point - value) : Infinity;
    if (distance <= threshold && distance < gap) { best = point; gap = distance; }
  }
  return best === null ? { value, snapped: null } : { value: best, snapped: best };
}

// Label drag: dx pixels of pointer travel from `start`, pxPerUnit pixels per 1.0 of value, fine (Shift) is 10x slower.
// A snap point inside the threshold wins over the step grid; the result always stays inside [min, max].
export function scrubValue({ start, dx, pxPerUnit = 1, step, min, max, fine = false, snapPoints, snapThreshold } = {}) {
  const speed = (fine ? 0.1 : 1) / (finite(pxPerUnit) && pxPerUnit > 0 ? pxPerUnit : 1);
  const raw = (finite(start) ? start : 0) + (finite(dx) ? dx : 0) * speed;
  const hit = snapValue(raw, snapPoints, snapThreshold);
  const value = clamp(hit.snapped === null ? roundToStep(clamp(raw, min, max), step, finite(min) ? min : 0) : hit.value, min, max);
  return { value, snapped: hit.snapped !== null && value === hit.snapped ? hit.snapped : null };
}

const trimZeros = text => (text.includes('.') ? text.replace(/0+$/, '').replace(/\.$/, '') : text);

// Display text. decimals is a count or 'auto' (up to 6, trailing zeros trimmed). signLabels {negative, positive} replaces
// the minus sign for bipolar values ('Early 1.2', 'Late 0.4'); zero never gets a label. A unit that starts with a letter
// is set off by a space ('1.2 s'), a symbol sticks to the number ('0.60×'). Non-finite values give ''.
export function formatValue(value, { decimals = 2, unit = '', signLabels } = {}) {
  if (!finite(value)) return '';
  const body = decimals === 'auto' ? trimZeros(Math.abs(value).toFixed(6)) : Math.abs(value).toFixed(clamp(Math.round(decimals), 0, 20));
  const zero = Number(body) === 0;
  let text = body;
  if (value < 0 && !zero) text = (signLabels ? signLabels.negative ?? '-' : '-') + body;
  else if (value > 0 && !zero && signLabels) text = (signLabels.positive ?? '') + body;
  return text + (unit ? (/^[A-Za-z]/.test(unit) ? ' ' : '') + unit : '');
}

const NUMBER = /^(?:\d+\.?\d*|\.\d+)/;
// Tiny arithmetic parser (numbers, + - * /, parentheses, unary signs). Never eval: anything else throws and becomes null.
function evaluate(source) {
  const s = source.replace(/[−–]/g, '-').replace(/×/g, '*').replace(/÷/g, '/');
  let i = 0, depth = 0;
  const fail = () => { throw new SyntaxError('bad expression'); };
  const peek = () => { while (s[i] === ' ') i += 1; return s[i]; };
  const enter = () => { depth += 1; if (depth > 20) fail(); };
  const primary = () => {
    if (peek() === '(') {
      i += 1; enter();
      const inner = expr();
      if (peek() !== ')') fail();
      i += 1; depth -= 1;
      return inner;
    }
    const match = NUMBER.exec(s.slice(i));
    if (!match) fail();
    i += match[0].length;
    return Number(match[0]);
  };
  const unary = () => {
    const c = peek();
    if (c !== '+' && c !== '-') return primary();
    i += 1; enter();
    const inner = unary();
    depth -= 1;
    return c === '-' ? -inner : inner;
  };
  const term = () => {
    let left = unary();
    for (let c = peek(); c === '*' || c === '/'; c = peek()) { i += 1; const right = unary(); left = c === '*' ? left * right : left / right; }
    return left;
  };
  const expr = () => {
    let left = term();
    for (let c = peek(); c === '+' || c === '-'; c = peek()) { i += 1; const right = term(); left = c === '+' ? left + right : left - right; }
    return left;
  };
  try {
    const result = expr();
    return peek() === undefined && finite(result) ? result : null;
  } catch {
    return null;
  }
}

// Typed text to a number, or null when it is not one. Plain numbers and arithmetic ("0.5*2", "(1+2)/4") work; with
// relative:true a leading sign means "from current" ("+0.2" is current + 0.2). `unit` is stripped from the end ("35mm"),
// `signLabels` is read back the way formatValue writes it ("Early 1.2" is -1.2). The result is clamped into [min, max].
export function parseValueInput(text, { min, max, current, relative = false, unit = '', signLabels } = {}) {
  if (typeof text === 'number') return finite(text) ? clamp(text, min, max) : null;
  if (typeof text !== 'string') return null;
  let s = text.trim(), sign = 1, labelled = false;
  if (!s || s.length > 120) return null;
  if (signLabels) {
    for (const [key, direction] of [['negative', -1], ['positive', 1]]) {
      const label = String(signLabels[key] ?? '').trim().toLowerCase();
      if (label && s.toLowerCase().startsWith(label)) { s = s.slice(label.length).trim(); sign = direction; labelled = true; break; }
    }
  }
  const suffix = String(unit || '').trim().toLowerCase();
  if (suffix && s.toLowerCase().endsWith(suffix)) s = s.slice(0, s.length - suffix.length).trim();
  const result = evaluate(s);
  if (result === null) return null;
  const fromCurrent = relative && !labelled && finite(current) && /^[+\-−]/.test(s);
  const value = labelled ? sign * result : fromCurrent ? current + result : result;
  return finite(value) ? clamp(tidy(value), min, max) : null;
}

// ---------- Timecode ----------
// Frames are integers. Timecode digits count whole frames per second, so 23.976 and 29.97 read as 24 and 30 (no drop frame);
// seconds <-> frames conversion uses the true rate.
export const DEFAULT_FPS = 24;
const rateOf = fps => (finite(fps) && fps > 0 ? fps : DEFAULT_FPS);
const baseOf = fps => Math.max(1, Math.round(rateOf(fps)));

export const secondsToFrames = (seconds, fps = DEFAULT_FPS) => (finite(seconds) ? noNegZero(Math.round(seconds * rateOf(fps))) : 0);
export const framesToSeconds = (frames, fps = DEFAULT_FPS) => (finite(frames) ? frames / rateOf(fps) : 0);

// Magnitude split into h/m/s/f plus the sign (+1 for zero).
export function framesToParts(frames, fps = DEFAULT_FPS) {
  const total = finite(frames) ? Math.round(frames) : 0, n = Math.abs(total), base = baseOf(fps);
  return { sign: total < 0 ? -1 : 1, h: Math.floor(n / (base * 3600)), m: Math.floor(n / (base * 60)) % 60, s: Math.floor(n / base) % 60, f: n % base };
}

// "00:00:08:12"; negative frames get a leading "-" only with {signed: true}, otherwise the magnitude is shown.
export function formatTimecode(frames, fps = DEFAULT_FPS, { signed = false } = {}) {
  const p = framesToParts(frames, fps), two = n => String(n).padStart(2, '0');
  return `${signed && p.sign < 0 ? '-' : ''}${two(p.h)}:${two(p.m)}:${two(p.s)}:${two(p.f)}`;
}

// Typed or pasted timecode to frames, or null. Accepts "00:00:08:12", "1:08:12" and "8:12" (right-aligned h:m:s:f; a frame
// count past the rate or minutes/seconds past 59 is malformed), "8.5" and "8.5s" (seconds, so a bare "12" is 12 seconds),
// "12f" (frames). A leading sign ("+12f", "-0.5s", "+1:12") is relative to `current` when it is given, else it is just negative/positive.
export function parseTimecode(text, fps = DEFAULT_FPS, { current } = {}) {
  if (typeof text !== 'string') return null;
  let s = text.trim().replace(/[−–]/g, '-'), sign = 1, signed = false, m;
  if (s[0] === '+' || s[0] === '-') { signed = true; sign = s[0] === '-' ? -1 : 1; s = s.slice(1).trim(); }
  const base = baseOf(fps);
  let frames = null;
  if ((m = /^(\d+(?:\.\d+)?|\.\d+)\s*f(?:rames?)?$/i.exec(s))) frames = Math.round(Number(m[1]));
  else if ((m = /^(\d+(?:\.\d+)?|\.\d+)\s*(?:s(?:ec(?:onds?)?)?)?$/i.exec(s))) frames = Math.round(Number(m[1]) * rateOf(fps));
  else if (/^\d+(?:[:;]\d+){1,3}$/.test(s)) {
    const parts = s.split(/[:;]/).map(Number), weights = [1, base, 60 * base, 3600 * base];
    if (!parts.every((v, k) => k === 0 || v < (k === parts.length - 1 ? base : 60))) return null;
    frames = parts.reduce((sum, v, k) => sum + v * weights[parts.length - 1 - k], 0);
  }
  if (frames === null || !Number.isSafeInteger(frames)) return null;
  return noNegZero(signed && finite(current) ? Math.round(current) + sign * frames : sign * frames);
}

// One arrow-key step on a segment ('h'|'m'|'s'|'f'): a frame, second, minute or hour, times 10 with shift.
// Carries into the next segment like real timecode. Stays inside [min, max] when they are given.
export function stepTimecode(frames, fps, segment, direction, { shift = false, min, max } = {}) {
  const base = baseOf(fps), unit = { f: 1, s: base, m: 60 * base, h: 3600 * base }[segment] ?? 1;
  const sign = Math.sign(direction) || 0, current = finite(frames) ? Math.round(frames) : 0;
  return clamp(current + sign * unit * (shift ? 10 : 1), min, max);
}

// ---------- Range handles ----------
// Move one end of {start, end} inside [min, max]: values land on the step grid from min, or on a snap point inside the
// threshold, and the ends never come closer than minGap (shrunk when the whole span is smaller). snapped reports the point used.
export function moveRangeHandle({ start, end, min, max }, handle, value, { minGap = 1, step = 1, snapPoints, snapThreshold } = {}) {
  if (!finite(value)) return { start, end, snapped: null };
  const gap = Math.max(0, Math.min(minGap, max - min)), hit = snapValue(value, snapPoints, snapThreshold);
  const target = hit.snapped === null ? roundToStep(value, step, min) : hit.value;
  let s = start, e = end;
  if (handle === 'end') e = clamp(target, Math.min(s + gap, max), max);
  else s = clamp(target, min, Math.max(e - gap, min));
  return { start: tidy(s), end: tidy(e), snapped: hit.snapped !== null && (handle === 'end' ? e : s) === hit.snapped ? hit.snapped : null };
}

// Shift the whole range by delta keeping its length and staying inside [min, max]. A range as long as the span fills it.
export function slideRange({ start, end, min, max }, delta, { step } = {}) {
  const length = end - start;
  if (length >= max - min) return { start: min, end: max };
  const room = max - length;
  let s = clamp(start + (finite(delta) ? delta : 0), min, room);
  if (finite(step) && step > 0) s = clamp(roundToStep(s, step, min), min, room);
  return { start: tidy(s), end: tidy(s + length) };
}

export const rangeLength = ({ start, end }) => tidy(end - start);

// ---------- Bezier easing ----------
// cubic-bezier(x1, y1, x2, y2) with the ends fixed at (0, 0) and (1, 1): values = [x1, y1, x2, y2].
export const BEZIER_PRESETS = [
  { id: 'linear', values: [0, 0, 1, 1] },
  { id: 'easeIn', values: [0.42, 0, 1, 1] },
  { id: 'easeOut', values: [0, 0, 0.58, 1] },
  { id: 'easeInOut', values: [0.42, 0, 0.58, 1] },
  { id: 'strongEaseOut', values: [0.16, 1, 0.3, 1] },
  { id: 'backOut', values: [0.34, 1.56, 0.64, 1] },
];
const LINEAR = [0, 0, 1, 1];
const asBezier = values => LINEAR.map((fallback, i) => (finite(values?.[i]) ? values[i] : fallback));
const tidy4 = n => noNegZero(Number(n.toFixed(4)));

// Four finite numbers with x in 0..1 and y in 0..1 (-1..2 with overshoot, the bounce range). Missing entries fall back to linear.
export function normalizeBezier(values, { overshoot = false } = {}) {
  const v = asBezier(values), lo = overshoot ? -1 : 0, hi = overshoot ? 2 : 1;
  return [clamp(v[0], 0, 1), clamp(v[1], lo, hi), clamp(v[2], 0, 1), clamp(v[3], lo, hi)];
}

const cubic = (a, b, t) => { const u = 1 - t; return 3 * u * u * t * a + 3 * u * t * t * b + t * t * t; };
const slope = (a, b, t) => { const u = 1 - t; return 3 * u * u * a + 6 * u * t * (b - a) + 3 * t * t * (1 - b); };

// Progress (y) at time x: solves x(t) = x with Newton and falls back to bisection when the slope is flat.
export function bezierAt(values, x) {
  const [x1, y1, x2, y2] = asBezier(values);
  if (!finite(x) || x <= 0) return 0;
  if (x >= 1) return 1;
  let t = x;
  for (let k = 0; k < 8; k += 1) {
    const error = cubic(x1, x2, t) - x;
    if (Math.abs(error) < 1e-9) return cubic(y1, y2, t);
    const d = slope(x1, x2, t);
    if (Math.abs(d) < 1e-6) break;
    t -= error / d;
    if (t < 0 || t > 1) break;
  }
  let lo = 0, hi = 1;
  t = x;
  for (let k = 0; k < 60; k += 1) {
    const error = cubic(x1, x2, t) - x;
    if (Math.abs(error) < 1e-9) break;
    if (error < 0) lo = t; else hi = t;
    t = (lo + hi) / 2;
  }
  return cubic(y1, y2, t);
}

// count + 1 progress values at time i / count (count defaults to 10 and is at least 1).
export function sampleBezier(values, count = 10) {
  const n = Math.max(1, Math.floor(count) || 1);
  return Array.from({ length: n + 1 }, (_, i) => bezierAt(values, i / n));
}

const coord = n => String(Number(n.toFixed(2)));
// SVG path "M.. C.." for the curve in a width x height box inset by padding, y pointing up. yMin/yMax (default 0..1)
// widen the vertical range for overshoot plots without changing the box.
export function bezierPath(values, { width = 100, height = 100, padding = 0, yMin = 0, yMax = 1 } = {}) {
  const [x1, y1, x2, y2] = asBezier(values), w = width - 2 * padding, h = height - 2 * padding, span = yMax - yMin || 1;
  const X = x => coord(padding + x * w), Y = y => coord(padding + ((yMax - y) / span) * h);
  return `M${X(0)} ${Y(0)} C${X(x1)} ${Y(y1)} ${X(x2)} ${Y(y2)} ${X(1)} ${Y(1)}`;
}

// Id of the preset whose four numbers are all within epsilon of values, else null. `presets` defaults to BEZIER_PRESETS.
export function matchBezierPreset(values, epsilon = 0.005, presets = BEZIER_PRESETS) {
  const v = asBezier(values);
  return presets.find(preset => preset.values.every((n, i) => Math.abs(n - v[i]) <= epsilon))?.id ?? null;
}

// "cubic-bezier(0.42, 0, 0.58, 1)", numbers trimmed to 3 decimals.
export const formatBezier = values => `cubic-bezier(${asBezier(values).map(v => String(Number(v.toFixed(3)))).join(', ')})`;

// "cubic-bezier(a, b, c, d)" or a bare "a, b, c, d" back to four numbers, or null. Like CSS, x1 and x2 must be within 0..1.
export function parseBezier(text) {
  if (typeof text !== 'string') return null;
  const wrapped = /^\s*cubic-bezier\s*\(([^()]*)\)\s*;?\s*$/i.exec(text), inner = wrapped ? wrapped[1] : /[()]/.test(text) ? null : text;
  if (inner === null) return null;
  const parts = inner.trim().split(/\s*,\s*|\s+/);
  if (parts.length !== 4 || !parts.every(part => /^[+-]?(?:\d+\.?\d*|\.\d+)$/.test(part))) return null;
  const values = parts.map(Number);
  return values[0] >= 0 && values[0] <= 1 && values[2] >= 0 && values[2] <= 1 ? values.map(noNegZero) : null;
}

// Move control point 1 or 2 to (x, y): x stays in 0..1, y in 0..1 (-1..2 with overshoot). snap rounds both to that
// increment first (0.05). Values are kept to 4 decimals; the other point is untouched. Returns a new array.
export function moveBezierHandle(values, which, x, y, { snap, overshoot = false } = {}) {
  const next = asBezier(values), at = which === 2 ? 2 : 0, lo = overshoot ? -1 : 0, hi = overshoot ? 2 : 1;
  const fit = n => (finite(snap) && snap > 0 ? roundToStep(n, snap) : n);
  next[at] = tidy4(clamp(fit(finite(x) ? x : next[at]), 0, 1));
  next[at + 1] = tidy4(clamp(fit(finite(y) ? y : next[at + 1]), lo, hi));
  return next;
}
