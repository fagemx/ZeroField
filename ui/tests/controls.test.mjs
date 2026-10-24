import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { build } from 'esbuild';
import { mkdtemp, writeFile, rm, readFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import {
  BEZIER_PRESETS, DEFAULT_FPS, bezierAt, bezierPath, clamp, formatBezier, formatTimecode, formatValue, fractionToValue, framesToParts, framesToSeconds,
  matchBezierPreset, moveBezierHandle, moveRangeHandle, normalizeBezier, parseBezier, parseTimecode, parseValueInput, rangeLength, roundToStep,
  sampleBezier, scrubValue, secondsToFrames, slideRange, snapValue, stepTimecode, valueToFraction,
} from '../src/controls/controlsModel.js';

const near = (actual, expected, epsilon = 1e-9, message) => assert.ok(Math.abs(actual - expected) <= epsilon, message || `${actual} is not within ${epsilon} of ${expected}`);
const LINEAR = [0, 0, 1, 1], EASE = [0.42, 0, 0.58, 1];

// ---------- Scalars ----------
test('clamp keeps values inside the bounds and survives missing, reversed and invalid input', () => {
  assert.equal(clamp(5, 0, 10), 5);
  assert.equal(clamp(-5, 0, 10), 0);
  assert.equal(clamp(15, 0, 10), 10);
  assert.equal(clamp(5, 10, 0), 5, 'a reversed pair is swapped, not trusted');
  assert.equal(clamp(50, 10, 0), 10);
  assert.equal(clamp(-3), -3, 'no bounds at all');
  assert.equal(clamp(7, undefined, 5), 5);
  assert.equal(clamp(-7, 0, undefined), 0);
  assert.equal(clamp(NaN, 2, 9), 2, 'NaN falls to the lower bound');
  assert.equal(clamp(NaN), 0);
  assert.equal(clamp('4', 0, 10), 0, 'only numbers count');
  assert.equal(clamp(Infinity, 0, 10), 10);
  assert.equal(clamp(-Infinity, 0, 10), 0);
  assert.ok(Object.is(clamp(-0.4 * 0, -1, 1), 0), 'negative zero is normalised');
});

test('roundToStep snaps to the grid that starts at origin and never leaks float noise', () => {
  assert.equal(roundToStep(7, 5), 5);
  assert.equal(roundToStep(8, 5), 10);
  assert.equal(roundToStep(0.1 + 0.2, 0.1), 0.3);
  assert.equal(roundToStep(1.23456, 0.001), 1.235);
  assert.equal(roundToStep(0.27, 0.1, 0.05), 0.25, 'the grid is 0.05, 0.15, 0.25 ...');
  assert.equal(roundToStep(0.65, 0.1, 0.15), 0.65);
  assert.equal(roundToStep(-7, 5), -5);
  assert.equal(roundToStep(2.5, 1), 3, 'halves round up');
  assert.equal(roundToStep(-2.5, 1), -2);
  assert.ok(Object.is(roundToStep(-0.4, 1), 0), 'no negative zero');
  assert.equal(roundToStep(5.2, 0), 5.2, 'a zero step does nothing');
  assert.equal(roundToStep(5.2, -1), 5.2);
  assert.equal(roundToStep(5.2, undefined), 5.2);
  assert.ok(Number.isNaN(roundToStep(NaN, 1)));
  assert.equal(roundToStep(0.0000123, 1e-7), 0.0000123, 'exponent-form steps keep their decimals');
});

test('valueToFraction and fractionToValue convert both ways on the step grid', () => {
  assert.equal(valueToFraction(5, 0, 10), 0.5);
  assert.equal(valueToFraction(15, 0, 10), 1);
  assert.equal(valueToFraction(-5, 0, 10), 0);
  assert.equal(valueToFraction(1, 2, 2), 0, 'a flat range has no position');
  assert.equal(valueToFraction(NaN, 0, 10), 0);
  assert.equal(valueToFraction(0, -2, 2), 0.5);
  assert.equal(fractionToValue(0.5, 0, 10, 1), 5);
  assert.equal(fractionToValue(0.26, 0, 1, 0.25), 0.25);
  assert.equal(fractionToValue(0, 2, 8, 1), 2);
  assert.equal(fractionToValue(-1, 2, 8, 1), 2);
  assert.equal(fractionToValue(9, 2, 8, 1), 8);
  assert.equal(fractionToValue(1, 0, 1, 0.3), 1, 'the far end is exact even when max is off the grid');
  assert.equal(fractionToValue(0.99, 0, 1, 0.3), 0.9);
  assert.equal(fractionToValue(0.5, 0.15, 1.15, 0.1), 0.65, 'the grid starts at min');
  assert.equal(fractionToValue(0.333, 0, 1), 0.333, 'no step means no rounding');
  for (const f of [0, 0.1, 0.25, 0.5, 0.75, 1]) near(valueToFraction(fractionToValue(f, -4, 4, 0.5), -4, 4), f, 0.0625 / 2 + 1e-9);
});

test('snapValue pulls to the nearest point inside the threshold', () => {
  assert.deepEqual(snapValue(0.52, [0, 0.5, 1], 0.05), { value: 0.5, snapped: 0.5 });
  assert.deepEqual(snapValue(0.56, [0, 0.5, 1], 0.05), { value: 0.56, snapped: null });
  assert.deepEqual(snapValue(0.9, [0.5, 1, 0.95], 0.2), { value: 0.95, snapped: 0.95 }, 'nearest wins, not first');
  assert.deepEqual(snapValue(3, [1, 5], 2), { value: 1, snapped: 1 }, 'the threshold is inclusive and a tie goes to the first point');
  assert.deepEqual(snapValue(3, [], 2), { value: 3, snapped: null });
  assert.deepEqual(snapValue(3, undefined, 2), { value: 3, snapped: null });
  assert.deepEqual(snapValue(3, [3], 0), { value: 3, snapped: null }, 'no threshold, no snapping');
  assert.deepEqual(snapValue(3, [3], -1), { value: 3, snapped: null });
  assert.deepEqual(snapValue(3, [NaN, 'x', 4], 2), { value: 4, snapped: 4 }, 'junk points are skipped');
  assert.equal(snapValue(NaN, [1], 5).snapped, null);
  assert.equal(snapValue(0, [0], 1).snapped, 0, 'a point equal to the value still reports as snapped');
});

test('scrubValue turns pointer travel into a clamped, step-rounded value, 10x slower in fine mode', () => {
  const base = { start: 0.5, pxPerUnit: 100, step: 0.01, min: 0, max: 1 };
  assert.deepEqual(scrubValue({ ...base, dx: 30 }), { value: 0.8, snapped: null });
  assert.deepEqual(scrubValue({ ...base, dx: -30 }), { value: 0.2, snapped: null });
  assert.equal(scrubValue({ ...base, dx: 30, fine: true }).value, 0.53, 'Shift: 10x slower');
  assert.equal(scrubValue({ ...base, dx: 300, fine: true }).value, 0.8);
  assert.equal(scrubValue({ ...base, dx: 50 }).value, 1);
  assert.equal(scrubValue({ ...base, dx: 5000 }).value, 1, 'clamped to max');
  assert.equal(scrubValue({ ...base, dx: -5000 }).value, 0, 'clamped to min');
  assert.equal(scrubValue({ ...base, dx: 12.3 }).value, 0.62, 'rounded to the step');
  assert.equal(scrubValue({ start: 1, dx: 7, pxPerUnit: 10, step: 0.5, min: 0.25, max: 5 }).value, 1.75, 'the step grid starts at min');
  assert.equal(scrubValue({ start: 0, dx: 13, pxPerUnit: 1, step: 5 }).value, 15, 'no min: the grid starts at 0');
  assert.equal(scrubValue({ start: 10, dx: 3 }).value, 13, 'one pixel per unit when pxPerUnit is missing');
  for (const pxPerUnit of [0, -4, NaN, Infinity * 0]) assert.equal(scrubValue({ start: 10, dx: 3, pxPerUnit }).value, 13, `pxPerUnit ${pxPerUnit} falls back to 1`);
  assert.deepEqual(scrubValue(), { value: 0, snapped: null });
  assert.equal(scrubValue({ start: 2, dx: NaN, step: 1 }).value, 2);
});

test('scrubValue snaps to points inside the threshold and reports which', () => {
  const base = { start: 0.9, dx: 8, pxPerUnit: 100, step: 0.01, snapPoints: [1], snapThreshold: 0.05 };
  assert.deepEqual(scrubValue(base), { value: 1, snapped: 1 }, '0.98 is within 0.05 of 1');
  assert.deepEqual(scrubValue({ ...base, dx: 2 }), { value: 0.92, snapped: null });
  assert.deepEqual(scrubValue({ ...base, snapPoints: [0.985], snapThreshold: 0.01 }), { value: 0.985, snapped: 0.985 }, 'a snap point beats the step grid');
  assert.deepEqual(scrubValue({ ...base, max: 0.99 }), { value: 0.99, snapped: null }, 'a snap point past max is clamped and no longer counts as a snap');
  assert.deepEqual(scrubValue({ ...base, snapPoints: undefined }), { value: 0.98, snapped: null });
  assert.deepEqual(scrubValue({ ...base, snapThreshold: undefined }), { value: 0.98, snapped: null }, 'points without a threshold never snap');
});

// ---------- Text ----------
test('formatValue writes fixed or trimmed decimals, units and sign labels', () => {
  assert.equal(formatValue(0.6), '0.60');
  assert.equal(formatValue(35.4, { decimals: 0 }), '35');
  assert.equal(formatValue(1.5, { decimals: 3 }), '1.500');
  assert.equal(formatValue(1.5, { decimals: 'auto' }), '1.5');
  assert.equal(formatValue(100, { decimals: 'auto' }), '100', 'only decimals are trimmed, never the integer part');
  assert.equal(formatValue(0.1 + 0.2, { decimals: 'auto' }), '0.3');
  assert.equal(formatValue(2.123456789, { decimals: 'auto' }), '2.123457');
  assert.equal(formatValue(0, { decimals: 'auto' }), '0');
  assert.equal(formatValue(1.2, { unit: 's' }), '1.20 s', 'a word unit is set off by a space');
  assert.equal(formatValue(35, { decimals: 0, unit: 'mm' }), '35 mm');
  assert.equal(formatValue(0.6, { unit: '×' }), '0.60×', 'a symbol unit sticks to the number');
  assert.equal(formatValue(50, { decimals: 0, unit: '%' }), '50%');
  assert.equal(formatValue(-0.5), '-0.50');
  assert.equal(formatValue(-0.001), '0.00', 'a value that rounds to zero loses its sign');
  assert.equal(formatValue(-0), '0.00');
  const signLabels = { negative: 'Early ', positive: 'Late ' };
  assert.equal(formatValue(-1.2, { signLabels }), 'Early 1.20');
  assert.equal(formatValue(0.4, { signLabels }), 'Late 0.40');
  assert.equal(formatValue(0, { signLabels }), '0.00');
  assert.equal(formatValue(-0.001, { signLabels }), '0.00');
  assert.equal(formatValue(-1.2, { signLabels, unit: 's' }), 'Early 1.20 s');
  assert.equal(formatValue(0.4, { signLabels: { negative: 'Early ' } }), '0.40');
  for (const bad of [NaN, Infinity, -Infinity, undefined, null, '5']) assert.equal(formatValue(bad), '', String(bad));
});

test('parseValueInput reads plain numbers and small arithmetic', () => {
  for (const [text, expected] of [['0.6', 0.6], [' 12 ', 12], ['.5', 0.5], ['5.', 5], ['1+2*3', 7], ['(1+2)*3', 9], ['10/4', 2.5], ['-3+5', 2], ['2*-3', -6], ['--2', 2],
    ['+5', 5], ['0.1+0.2', 0.3], ['−0.5', -0.5], ['2×3', 6], ['6÷4', 1.5], ['((2))', 2], ['8 / 2 / 2', 2], ['2 * (3 + 4) - 1', 13]]) {
    assert.equal(parseValueInput(text), expected, text);
  }
  assert.equal(parseValueInput(5), 5);
  assert.equal(parseValueInput(Infinity), null);
});

test('parseValueInput is relative only on request, clamps, and understands units and sign labels', () => {
  const rel = { relative: true, current: 0.5 };
  assert.equal(parseValueInput('+0.2', rel), 0.7);
  assert.equal(parseValueInput('-0.1', rel), 0.4);
  assert.equal(parseValueInput('+1*2', rel), 2.5);
  assert.equal(parseValueInput('0.3', rel), 0.3, 'no sign means absolute');
  assert.equal(parseValueInput('+0.2', { relative: true }), 0.2, 'without a current value the sign is just a sign');
  assert.equal(parseValueInput('+0.2', { current: 0.5 }), 0.2, 'relative must be asked for');
  assert.equal(parseValueInput('-0.1', { current: 0.5 }), -0.1);
  assert.equal(parseValueInput('9', { min: 0.1, max: 4 }), 4);
  assert.equal(parseValueInput('-5', { min: 0, max: 4 }), 0);
  assert.equal(parseValueInput('+9', { ...rel, max: 4 }), 4, 'relative results are clamped too');
  assert.equal(parseValueInput('35mm', { unit: 'mm' }), 35);
  assert.equal(parseValueInput('1.5 S', { unit: 's' }), 1.5, 'units are case-insensitive and may be spaced');
  assert.equal(parseValueInput('0.6×', { unit: '×' }), 0.6);
  assert.equal(parseValueInput('35', { unit: 'mm' }), 35);
  assert.equal(parseValueInput('2mm+1', { unit: 'mm' }), null, 'a unit in the middle is not a unit');
  const signLabels = { negative: 'Early ', positive: 'Late ' };
  assert.equal(parseValueInput('Early 1.2', { signLabels }), -1.2);
  assert.equal(parseValueInput('late 0.4', { signLabels }), 0.4);
  assert.equal(parseValueInput('-0.3', { signLabels }), -0.3, 'plain signed numbers still work');
  for (const v of [-2, -1.25, 0, 0.5, 3]) assert.equal(parseValueInput(formatValue(v, { signLabels, unit: 's' }), { signLabels, unit: 's' }), v, `round trip ${v}`);
});

test('parseValueInput rejects malformed text and never evaluates code', () => {
  for (const text of ['', '   ', 'abc', '1+', '+', '*2', '(1', '1)', '()', '1 2', '1..2', '1.2.3', '2**3', '1e3', '1,5', 'NaN', 'Infinity', '1/0', '0/0', 'alert(1)', '1+*2', '((1)', '1 +', '$5']) {
    assert.equal(parseValueInput(text), null, JSON.stringify(text));
  }
  for (const odd of [null, undefined, {}, [], true]) assert.equal(parseValueInput(odd), null);
  assert.equal(parseValueInput('1'.repeat(121)), null, 'absurdly long input is refused');
  assert.equal(parseValueInput('('.repeat(15) + '1' + ')'.repeat(15)), 1);
  assert.equal(parseValueInput('('.repeat(30) + '1' + ')'.repeat(30)), null, 'nesting is bounded');
  assert.equal(parseValueInput('-'.repeat(40) + '1'), null, 'so are stacked signs');
  globalThis.__ctlPwned = 0;
  assert.equal(parseValueInput('(globalThis.__ctlPwned = 1)'), null);
  assert.equal(parseValueInput('constructor'), null);
  assert.equal(parseValueInput('this.constructor.constructor("globalThis.__ctlPwned = 1")()'), null);
  assert.equal(globalThis.__ctlPwned, 0, 'nothing was evaluated');
  delete globalThis.__ctlPwned;
});

// ---------- Timecode ----------
test('seconds and frames convert with rounding at 24, 25, 30 and 29.97 fps', () => {
  assert.equal(DEFAULT_FPS, 24);
  assert.equal(secondsToFrames(8.5, 24), 204);
  assert.equal(secondsToFrames(8.5), 204, '24 fps by default');
  assert.equal(secondsToFrames(0.02, 24), 0);
  assert.equal(secondsToFrames(0.03, 24), 1);
  assert.equal(secondsToFrames(-0.5, 24), -12);
  assert.equal(secondsToFrames(1, 25), 25);
  assert.equal(secondsToFrames(1, 30), 30);
  assert.equal(secondsToFrames(1, 29.97), 30);
  assert.equal(secondsToFrames(1, 0), 24, 'a broken rate falls back to 24');
  assert.equal(secondsToFrames(1, NaN), 24);
  assert.equal(secondsToFrames(1, -5), 24);
  assert.equal(secondsToFrames(NaN, 24), 0);
  assert.ok(Object.is(secondsToFrames(-0.001, 24), 0), 'no negative zero');
  assert.equal(framesToSeconds(204, 24), 8.5);
  assert.equal(framesToSeconds(25, 25), 1);
  assert.equal(framesToSeconds(-12, 24), -0.5);
  assert.equal(framesToSeconds(0), 0);
  assert.equal(framesToSeconds(NaN), 0);
  near(framesToSeconds(30, 29.97), 1.001001, 1e-6);
});

test('framesToParts and formatTimecode split magnitude and sign, whole frames per second', () => {
  assert.deepEqual(framesToParts(0), { sign: 1, h: 0, m: 0, s: 0, f: 0 });
  assert.deepEqual(framesToParts(204), { sign: 1, h: 0, m: 0, s: 8, f: 12 });
  assert.deepEqual(framesToParts(-12), { sign: -1, h: 0, m: 0, s: 0, f: 12 });
  assert.deepEqual(framesToParts(24 * 3600 * 2 + 24 * 60 * 3 + 24 * 4 + 5, 24), { sign: 1, h: 2, m: 3, s: 4, f: 5 });
  assert.deepEqual(framesToParts(25 * 61 + 3, 25), { sign: 1, h: 0, m: 1, s: 1, f: 3 });
  assert.deepEqual(framesToParts(30 * 59 + 29, 30), { sign: 1, h: 0, m: 0, s: 59, f: 29 });
  assert.deepEqual(framesToParts(30 * 60, 29.97), { sign: 1, h: 0, m: 1, s: 0, f: 0 }, '29.97 counts 30 frames per timecode second');
  assert.deepEqual(framesToParts(12.6), { sign: 1, h: 0, m: 0, s: 0, f: 13 });
  assert.deepEqual(framesToParts(NaN), { sign: 1, h: 0, m: 0, s: 0, f: 0 });
  assert.equal(formatTimecode(204), '00:00:08:12');
  assert.equal(formatTimecode(0), '00:00:00:00');
  assert.equal(formatTimecode(-204), '00:00:08:12', 'unsigned shows the magnitude');
  assert.equal(formatTimecode(-204, 24, { signed: true }), '-00:00:08:12');
  assert.equal(formatTimecode(0, 24, { signed: true }), '00:00:00:00');
  assert.equal(formatTimecode(25 * 3, 25), '00:00:03:00');
  assert.equal(formatTimecode(24 * 3600 * 100), '100:00:00:00', 'hours may pass two digits');
});

test('parseTimecode accepts timecode, seconds, frames and relative edits, and refuses the rest', () => {
  const cases = [['00:00:08:12', 204], ['8:12', 204], ['1:08:12', 1644], ['0:0:8:12', 204], ['00;00;08;12', 204], ['8.5', 204], ['8.5s', 204], ['.5s', 12], ['8', 192], ['8s', 192],
    ['8 sec', 192], ['8 seconds', 192], ['12f', 12], ['12 f', 12], ['12 frames', 12], ['0f', 0], ['  00:00:08:12  ', 204]];
  for (const [text, frames] of cases) assert.equal(parseTimecode(text, 24), frames, text);
  assert.equal(parseTimecode('8:12', 25), 212);
  assert.equal(parseTimecode('8:12', 30), 252);
  assert.equal(parseTimecode('8.4', 25), 210);
  assert.equal(parseTimecode('8:24', 25), 224);
  assert.equal(parseTimecode('1:00', 29.97), 30, 'a 29.97 timecode second has 30 frames');
  assert.equal(parseTimecode('8:12'), 204, '24 fps by default');
  // Signed text is relative to `current`, or simply signed without it.
  assert.equal(parseTimecode('+12f', 24, { current: 100 }), 112);
  assert.equal(parseTimecode('-0.5s', 24, { current: 100 }), 88);
  assert.equal(parseTimecode('−0.5s', 24, { current: 100 }), 88);
  assert.equal(parseTimecode('+1:12', 24, { current: 10 }), 46);
  assert.equal(parseTimecode('-1:12', 24, { current: 100 }), 64);
  assert.equal(parseTimecode('+ 12f', 24, { current: 100 }), 112);
  assert.equal(parseTimecode('+12f'), 12);
  assert.equal(parseTimecode('-12f'), -12);
  assert.equal(parseTimecode('12f', 24, { current: 100 }), 12, 'unsigned text is absolute even with a current value');
  assert.equal(parseTimecode('-00:00:08:12'), -204);
  assert.ok(Object.is(parseTimecode('-0f'), 0));
  for (const text of ['', '  ', 'abc', '12x', '1:2:3:4:5', ':12', '8:', '8::12', '8:30', '1:60:00', '1:00:60:00', '00:60:00:00', '1.5:12', 'f', '-', '+', '12ff', '1e3', '8,5', '8.5.5s', '12f3']) {
    assert.equal(parseTimecode(text, 24), null, JSON.stringify(text));
  }
  assert.equal(parseTimecode('8:25', 25), null, 'a frame count at or past the rate is malformed');
  assert.equal(parseTimecode('8:24', 24), null);
  for (const odd of [null, undefined, 12, {}]) assert.equal(parseTimecode(odd, 24), null);
  assert.equal(parseTimecode('9'.repeat(30) + 's'), null, 'unsafe integers are refused');
});

test('formatTimecode and parseTimecode round-trip every frame count at every rate', () => {
  for (const fps of [24, 25, 30, 29.97, 23.976]) {
    for (const frames of [0, 1, 11, 23, 24, 25, 29, 30, 100, 1234, 86399, 86400, 123456]) {
      assert.equal(parseTimecode(formatTimecode(frames, fps), fps), frames, `${frames} @ ${fps}`);
      const negative = frames === 0 ? 0 : -frames;
      assert.equal(parseTimecode(formatTimecode(negative, fps, { signed: true }), fps), negative, `${negative} @ ${fps}`);
    }
  }
});

test('stepTimecode steps one segment, carries into the next, and honours shift, min and max', () => {
  assert.equal(stepTimecode(23, 24, 'f', 1), 24, 'frame 23 carries into the next second');
  assert.equal(formatTimecode(stepTimecode(23, 24, 'f', 1), 24), '00:00:01:00');
  assert.equal(stepTimecode(0, 24, 's', 1), 24);
  assert.equal(stepTimecode(0, 24, 's', 1, { shift: true }), 240, 'shift on seconds is 10 s');
  assert.equal(stepTimecode(100, 24, 'f', 1, { shift: true }), 110, 'shift on frames is 10 f');
  assert.equal(stepTimecode(5, 24, 'f', -1, { shift: true }), -5);
  assert.equal(stepTimecode(5, 24, 'f', -1, { shift: true, min: 0 }), 0, 'never below min');
  assert.equal(stepTimecode(0, 24, 's', -1, { shift: true, min: 0 }), 0);
  assert.equal(stepTimecode(24, 24, 's', 1, { max: 30 }), 30, 'never above max');
  assert.equal(stepTimecode(0, 24, 'm', 1), 1440);
  assert.equal(stepTimecode(0, 24, 'h', 1), 86400);
  assert.equal(stepTimecode(0, 25, 's', 1), 25);
  assert.equal(stepTimecode(0, 30, 's', 1), 30);
  assert.equal(stepTimecode(0, 29.97, 's', 1), 30);
  assert.equal(stepTimecode(50, 24, 's', 0), 50, 'no direction, no change');
  assert.equal(stepTimecode(10.4, 24, 'f', 1), 11, 'fractional input is rounded to whole frames');
  assert.equal(stepTimecode(0, 24, 'x', 1), 1, 'an unknown segment steps a frame');
  assert.equal(stepTimecode(NaN, 24, 'f', 1), 1);
});

// ---------- Range handles ----------
test('moveRangeHandle keeps the minimum gap, the bounds and the step grid', () => {
  const range = { start: 2, end: 8, min: 0, max: 10 };
  assert.deepEqual(moveRangeHandle(range, 'start', 5), { start: 5, end: 8, snapped: null });
  assert.deepEqual(moveRangeHandle(range, 'start', 9), { start: 7, end: 8, snapped: null }, 'start stops one gap before end');
  assert.deepEqual(moveRangeHandle(range, 'start', 9, { minGap: 2 }), { start: 6, end: 8, snapped: null });
  assert.deepEqual(moveRangeHandle(range, 'start', -3), { start: 0, end: 8, snapped: null });
  assert.deepEqual(moveRangeHandle(range, 'end', 1), { start: 2, end: 3, snapped: null }, 'end stops one gap after start');
  assert.deepEqual(moveRangeHandle(range, 'end', 99), { start: 2, end: 10, snapped: null });
  assert.deepEqual(moveRangeHandle(range, 'end', 2.4), { start: 2, end: 3, snapped: null });
  assert.deepEqual(moveRangeHandle(range, 'end', 5.4, { minGap: 0 }), { start: 2, end: 5, snapped: null });
  assert.deepEqual(moveRangeHandle(range, 'start', 2.74, { step: 0.5 }), { start: 2.5, end: 8, snapped: null });
  assert.deepEqual(moveRangeHandle({ ...range, min: 0.25 }, 'start', 1.3, { step: 0.5 }), { start: 1.25, end: 8, snapped: null }, 'the grid starts at min');
  assert.deepEqual(moveRangeHandle(range, 'start', 0.30000000000000004, { step: 0.1 }), { start: 0.3, end: 8, snapped: null });
  assert.deepEqual(moveRangeHandle(range, 'sideways', 4), { start: 4, end: 8, snapped: null }, 'an unknown handle moves the start');
  assert.deepEqual(moveRangeHandle(range, 'start', NaN), { start: 2, end: 8, snapped: null });
  assert.deepEqual(range, { start: 2, end: 8, min: 0, max: 10 }, 'the input range is not mutated');
  assert.deepEqual(moveRangeHandle({ start: 0, end: 2, min: 0, max: 2 }, 'start', 1, { minGap: 5 }), { start: 0, end: 2, snapped: null }, 'a gap wider than the span shrinks to the span');
});

test('moveRangeHandle snaps to points and only reports a snap that survived the clamps', () => {
  const range = { start: 2, end: 8, min: 0, max: 10 };
  assert.deepEqual(moveRangeHandle(range, 'end', 7.8, { snapPoints: [8], snapThreshold: 0.5 }), { start: 2, end: 8, snapped: 8 });
  assert.deepEqual(moveRangeHandle(range, 'start', 3.2, { snapPoints: [3.25], snapThreshold: 0.1 }), { start: 3.25, end: 8, snapped: 3.25 }, 'a snap point beats the grid');
  assert.deepEqual(moveRangeHandle(range, 'start', 4.2, { snapPoints: [3.25], snapThreshold: 0.1 }), { start: 4, end: 8, snapped: null });
  assert.deepEqual(moveRangeHandle(range, 'start', 7.9, { snapPoints: [8], snapThreshold: 0.5 }), { start: 7, end: 8, snapped: null }, 'the gap clamp moved it off the point');
});

test('slideRange moves the whole range, keeps its length and stops at the bounds', () => {
  const range = { start: 2, end: 5, min: 0, max: 10 };
  assert.deepEqual(slideRange(range, 1), { start: 3, end: 6 });
  assert.deepEqual(slideRange(range, -1), { start: 1, end: 4 });
  assert.deepEqual(slideRange(range, 20), { start: 7, end: 10 });
  assert.deepEqual(slideRange(range, -20), { start: 0, end: 3 });
  assert.deepEqual(slideRange(range, 0.4, { step: 1 }), { start: 2, end: 5 });
  assert.deepEqual(slideRange(range, 0.6, { step: 1 }), { start: 3, end: 6 });
  assert.deepEqual(slideRange({ start: 0.5, end: 2.25, min: 0, max: 10 }, 0.6, { step: 0.5 }), { start: 1, end: 2.75 }, 'only the start is rounded; the length is kept');
  assert.deepEqual(slideRange(range, NaN), { start: 2, end: 5 });
  assert.deepEqual(slideRange({ start: 0, end: 10, min: 0, max: 10 }, 3), { start: 0, end: 10 }, 'a range as long as the span fills it');
  assert.deepEqual(slideRange({ start: -1, end: 12, min: 0, max: 10 }, 3), { start: 0, end: 10 });
  assert.deepEqual(slideRange({ start: 0.1, end: 0.3, min: 0, max: 1 }, 0.2), { start: 0.3, end: 0.5 }, 'no float noise');
  for (const delta of [-7, -0.3, 0, 2.2, 9]) {
    const slid = slideRange(range, delta);
    near(rangeLength(slid), 3);
    assert.ok(slid.start >= 0 && slid.end <= 10);
  }
});

test('rangeLength is end minus start without float noise', () => {
  assert.equal(rangeLength({ start: 2, end: 5 }), 3);
  assert.equal(rangeLength({ start: 0.1, end: 0.3 }), 0.2);
  assert.equal(rangeLength({ start: 5, end: 2 }), -3);
  assert.equal(rangeLength({ start: 1, end: 1 }), 0);
});

// ---------- Bezier easing ----------
// Independent reference: plain bisection on x(t), no Newton, so it cannot share a bug with bezierAt.
function reference(values, x) {
  const [x1, y1, x2, y2] = values, at = (a, b, t) => 3 * (1 - t) ** 2 * t * a + 3 * (1 - t) * t ** 2 * b + t ** 3;
  let lo = 0, hi = 1;
  for (let i = 0; i < 200; i += 1) { const mid = (lo + hi) / 2; if (at(x1, x2, mid) < x) lo = mid; else hi = mid; }
  return at(y1, y2, (lo + hi) / 2);
}
let seed = 20261025;
const random = () => { seed = (seed * 1664525 + 1013904223) % 4294967296; return seed / 4294967296; };

test('the six easing presets are the documented curves', () => {
  assert.deepEqual(BEZIER_PRESETS, [
    { id: 'linear', values: [0, 0, 1, 1] }, { id: 'easeIn', values: [0.42, 0, 1, 1] }, { id: 'easeOut', values: [0, 0, 0.58, 1] },
    { id: 'easeInOut', values: [0.42, 0, 0.58, 1] }, { id: 'strongEaseOut', values: [0.16, 1, 0.3, 1] }, { id: 'backOut', values: [0.34, 1.56, 0.64, 1] },
  ]);
});

test('normalizeBezier clamps x to 0..1 and y to 0..1, or -1..2 with overshoot', () => {
  assert.deepEqual(normalizeBezier([2, -1, -1, 3]), [1, 0, 0, 1]);
  assert.deepEqual(normalizeBezier([2, -1, -1, 3], { overshoot: true }), [1, -1, 0, 2]);
  assert.deepEqual(normalizeBezier([0.5, 5, 0.5, -5], { overshoot: true }), [0.5, 2, 0.5, -1]);
  assert.deepEqual(normalizeBezier([0.5, 1.56, 0.5, 0.2], { overshoot: true }), [0.5, 1.56, 0.5, 0.2], 'values already in range pass through');
  assert.deepEqual(normalizeBezier([NaN, undefined, 'x', null]), LINEAR, 'unusable entries fall back to linear');
  assert.deepEqual(normalizeBezier([0.3]), [0.3, 0, 1, 1]);
  assert.deepEqual(normalizeBezier(), LINEAR);
  assert.deepEqual(normalizeBezier(null), LINEAR);
  const input = [0.2, 0.4, 0.6, 0.8], output = normalizeBezier(input);
  assert.notEqual(output, input, 'a new array comes back');
  assert.deepEqual(input, [0.2, 0.4, 0.6, 0.8]);
});

test('bezierAt solves the curve: linear is the identity, the ends are fixed, presets match an independent solver', () => {
  for (let i = 0; i <= 100; i += 1) near(bezierAt(LINEAR, i / 100), i / 100, 1e-6, `linear at ${i / 100}`);
  for (const { id, values } of BEZIER_PRESETS) {
    assert.equal(bezierAt(values, 0), 0, `${id} starts at 0`);
    assert.equal(bezierAt(values, 1), 1, `${id} ends at 1`);
    assert.equal(bezierAt(values, -0.5), 0);
    assert.equal(bezierAt(values, 1.5), 1);
    assert.equal(bezierAt(values, NaN), 0);
    for (let i = 1; i < 100; i += 1) near(bezierAt(values, i / 100), reference(values, i / 100), 1e-7, `${id} at ${i / 100}`);
  }
  near(bezierAt(EASE, 0.5), 0.5, 1e-6);
  for (let i = 0; i <= 20; i += 1) near(bezierAt(EASE, i / 20) + bezierAt(EASE, 1 - i / 20), 1, 1e-6, 'ease-in-out is point-symmetric');
  near(bezierAt(EASE, 0.25), 0.1291, 1e-3);
  assert.ok(bezierAt([0.42, 0, 1, 1], 0.5) < 0.5, 'ease-in lags the diagonal');
  assert.ok(bezierAt([0, 0, 0.58, 1], 0.5) > 0.5, 'ease-out leads it');
  assert.ok(bezierAt([0.16, 1, 0.3, 1], 0.1) > 0.4, 'strong ease-out is mostly done early');
  for (const values of [[0, 0, 0, 1], [1, 0, 1, 1], [0, 1, 1, 0], [1, 1, 0, 0], [0, 0, 0, 0], [1, 1, 1, 1], [0.5, -1, 0.5, 2], [0.01, 1, 0.99, 0]]) {
    for (let i = 1; i < 50; i += 1) near(bezierAt(values, i / 50), reference(values, i / 50), 1e-5, `${values} at ${i / 50}`);
  }
  near(bezierAt(undefined, 0.3), 0.3, 1e-6, 'a missing curve is linear');
});

test('samples never run backwards for y inside 0..1, and overshoot presets really overshoot', () => {
  for (const preset of BEZIER_PRESETS.filter(p => p.values[1] <= 1 && p.values[3] <= 1)) {
    const samples = sampleBezier(preset.values, 50);
    samples.forEach((value, i) => i && assert.ok(value >= samples[i - 1] - 1e-9, `${preset.id} step ${i}`));
  }
  for (let n = 0; n < 60; n += 1) {
    const values = [random(), random(), random(), random()], samples = sampleBezier(values, 40);
    samples.forEach((value, i) => i && assert.ok(value >= samples[i - 1] - 1e-9, `${values} step ${i}`));
    near(bezierAt(values, 0.37), reference(values, 0.37), 1e-6, `${values}`);
  }
  const back = sampleBezier(BEZIER_PRESETS.find(p => p.id === 'backOut').values, 20);
  assert.ok(Math.max(...back) > 1.05, 'back-out passes 1 before settling');
  assert.equal(back[0], 0);
  assert.equal(back[20], 1);
  const dip = sampleBezier([0.3, -0.8, 0.7, 1], 20);
  assert.ok(Math.min(...dip) < -0.05, 'a negative y1 anticipates by dipping below 0');
});

test('sampleBezier returns count + 1 progress values at even times', () => {
  const samples = sampleBezier(EASE);
  assert.equal(samples.length, 11, 'ten steps by default');
  assert.equal(samples[0], 0);
  assert.equal(samples[10], 1);
  samples.forEach((value, i) => near(value, bezierAt(EASE, i / 10)));
  assert.equal(sampleBezier(EASE, 4).length, 5);
  assert.deepEqual(sampleBezier(LINEAR, 4).map(v => Number(v.toFixed(6))), [0, 0.25, 0.5, 0.75, 1]);
  for (const count of [0, -3, NaN]) assert.deepEqual(sampleBezier(EASE, count), [0, 1], `count ${count} still gives both ends`);
  assert.equal(sampleBezier(EASE, 2.7).length, 3, 'fractional counts round down');
});

test('bezierPath draws M..C in a padded box with y pointing up', () => {
  assert.equal(bezierPath(EASE, { width: 56, height: 28, padding: 6 }), 'M6 22 C24.48 22 31.52 6 50 6');
  assert.equal(bezierPath(LINEAR, { width: 100, height: 100 }), 'M0 100 C0 100 100 0 100 0');
  assert.equal(bezierPath(EASE, { width: 300, height: 300, padding: 0 }), 'M0 300 C126 300 174 0 300 0');
  assert.equal(bezierPath(LINEAR, { width: 40, height: 28, padding: 4 }), 'M4 24 C4 24 36 4 36 4');
  assert.equal(bezierPath([0.34, 1.56, 0.64, 1], { width: 40, height: 28, padding: 4 }), 'M4 24 C14.88 -7.2 24.48 4 36 4', 'overshoot control points leave the box');
  assert.equal(bezierPath(LINEAR, { width: 200, height: 200, yMin: -0.5, yMax: 1.5 }), 'M0 150 C0 150 200 50 200 50', 'a wider y range moves 0 and 1 inside the box');
  assert.equal(bezierPath(undefined, { width: 10, height: 10 }), bezierPath(LINEAR, { width: 10, height: 10 }));
  assert.equal(bezierPath(EASE), bezierPath(EASE, { width: 100, height: 100, padding: 0, yMin: 0, yMax: 1 }), 'a 100 x 100 box by default');
  assert.doesNotMatch(bezierPath([NaN, Infinity, undefined, 'x'], { width: 50, height: 50 }), /NaN|Infinity|undefined/);
});

test('matchBezierPreset finds the preset whose four numbers are all within epsilon', () => {
  for (const { id, values } of BEZIER_PRESETS) assert.equal(matchBezierPreset(values), id);
  assert.equal(matchBezierPreset([0.424, 0.004, 0.576, 0.996]), 'easeInOut');
  assert.equal(matchBezierPreset([0.426, 0, 0.58, 1]), null, 'one number past epsilon is a custom curve');
  assert.equal(matchBezierPreset([0.426, 0, 0.58, 1], 0.01), 'easeInOut', 'epsilon is adjustable');
  assert.equal(matchBezierPreset([0.5, 0.5, 0.5, 0.5]), null);
  assert.equal(matchBezierPreset(undefined), 'linear', 'a missing curve is linear');
  assert.equal(matchBezierPreset([0.1, 0.2, 0.3, 0.4], 0.005, [{ id: 'mine', values: [0.1, 0.2, 0.3, 0.4] }]), 'mine', 'a custom preset list can be searched');
  assert.equal(matchBezierPreset(EASE, 0.005, [{ id: 'mine', values: [0.1, 0.2, 0.3, 0.4] }]), null);
});

test('formatBezier and parseBezier write and read cubic-bezier() text', () => {
  assert.equal(formatBezier(EASE), 'cubic-bezier(0.42, 0, 0.58, 1)');
  assert.equal(formatBezier(LINEAR), 'cubic-bezier(0, 0, 1, 1)');
  assert.equal(formatBezier([0.12345, 0.6789, 0.5, 1.5]), 'cubic-bezier(0.123, 0.679, 0.5, 1.5)', 'trimmed to three decimals');
  assert.equal(formatBezier([-0.0001, 0, 1, 1]), 'cubic-bezier(0, 0, 1, 1)', 'no "-0"');
  for (const { values } of BEZIER_PRESETS) assert.deepEqual(parseBezier(formatBezier(values)), values);
  for (const text of ['cubic-bezier(.42,0,.58,1)', '  CUBIC-BEZIER( 0.42 , 0 , 0.58 , 1 ) ; ', 'cubic-bezier(0.42, 0, 0.58, 1);', '0.42, 0, 0.58, 1', '0.42 0 0.58 1', ' 0.42,0,0.58,1 ']) {
    assert.deepEqual(parseBezier(text), EASE, text);
  }
  assert.deepEqual(parseBezier('cubic-bezier(0.3, -0.5, 0.7, 1.5)'), [0.3, -0.5, 0.7, 1.5], 'y may leave 0..1');
  assert.deepEqual(parseBezier('cubic-bezier(+0.5, +1, 0, 0)'), [0.5, 1, 0, 0]);
  for (const text of ['', 'cubic-bezier()', 'cubic-bezier(1,2,3)', 'cubic-bezier(1,2,3,4,5)', 'cubic-bezier(a,b,c,d)', 'ease-in-out', '(0.4, 0, 0.6, 1)', 'cubic-bezier(0.1,0.2,0.3,0.4',
    'cubic-bezier(1.5, 0, 0.5, 1)', 'cubic-bezier(0.5, 0, -0.1, 1)', '0.1, 0.2, 0.3', 'cubic-bezier(0.1, 0.2, 0.3, 0.4) extra', 'cubic-bezier(1e-1, 0, 0.5, 1)']) {
    assert.equal(parseBezier(text), null, JSON.stringify(text));
  }
  for (const odd of [null, undefined, 5, []]) assert.equal(parseBezier(odd), null);
});

test('moveBezierHandle moves one control point inside the allowed range', () => {
  assert.deepEqual(moveBezierHandle(LINEAR, 1, 0.3, 0.6), [0.3, 0.6, 1, 1]);
  assert.deepEqual(moveBezierHandle(LINEAR, 2, 0.7, 0.2), [0, 0, 0.7, 0.2]);
  assert.deepEqual(moveBezierHandle(EASE, 1, 0.1, 0.9), [0.1, 0.9, 0.58, 1], 'the other point is untouched');
  assert.deepEqual(moveBezierHandle(LINEAR, 1, -1, 0.5), [0, 0.5, 1, 1], 'x is held to 0..1');
  assert.deepEqual(moveBezierHandle(LINEAR, 1, 2, 0.5), [1, 0.5, 1, 1]);
  assert.deepEqual(moveBezierHandle(LINEAR, 1, 0.5, 1.5), [0.5, 1, 1, 1], 'y is held to 0..1 without overshoot');
  assert.deepEqual(moveBezierHandle(LINEAR, 1, 0.5, -0.5), [0.5, 0, 1, 1]);
  assert.deepEqual(moveBezierHandle(LINEAR, 2, 0.5, 1.5, { overshoot: true }), [0, 0, 0.5, 1.5]);
  assert.deepEqual(moveBezierHandle(LINEAR, 2, 0.5, 3, { overshoot: true }), [0, 0, 0.5, 2]);
  assert.deepEqual(moveBezierHandle(LINEAR, 1, 0.5, -3, { overshoot: true }), [0.5, -1, 1, 1]);
  assert.deepEqual(moveBezierHandle(LINEAR, 1, 0.333, 0.51, { snap: 0.05 }), [0.35, 0.5, 1, 1], 'snap rounds both coordinates');
  assert.deepEqual(moveBezierHandle(LINEAR, 2, 0.333, 1.52, { snap: 0.05, overshoot: true }), [0, 0, 0.35, 1.5]);
  assert.deepEqual(moveBezierHandle(LINEAR, 1, 0.123456, 0.987654), [0.1235, 0.9877, 1, 1], 'kept to four decimals');
  assert.deepEqual(moveBezierHandle(EASE, 1, NaN, undefined), EASE, 'unusable coordinates keep the old ones');
  assert.deepEqual(moveBezierHandle(LINEAR, 7, 0.4, 0.4), [0.4, 0.4, 1, 1], 'any other "which" means point 1');
  for (const snap of [0, -0.05, NaN]) assert.deepEqual(moveBezierHandle(LINEAR, 1, 0.333, 0.51, { snap }), [0.333, 0.51, 1, 1], `snap ${snap} is ignored`);
  const input = [0.1, 0.2, 0.3, 0.4];
  assert.notEqual(moveBezierHandle(input, 1, 0.5, 0.5), input);
  assert.deepEqual(input, [0.1, 0.2, 0.3, 0.4], 'the input is not mutated');
  assert.equal(moveBezierHandle(LINEAR, 1, 0.35, 0.5, { snap: 0.05 })[0], 0.35, 'snapped values carry no float noise');
});

// ---------- Components (server render) ----------
let components, temporary;
const uiRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
before(async () => {
  temporary = await mkdtemp(join(uiRoot, 'tests/.controls-render-'));
  const result = await build({ stdin: { contents: "export {NumberField, ScrubLabel, Slider, RangeSlider, TimecodeField, KeyframeButton, ResetButton, ParamRow, CurveEditor, CurveThumb} from './src/controls/Controls.jsx';",
    resolveDir: uiRoot, sourcefile: 'controls-render.jsx', loader: 'jsx' }, bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', packages: 'external',
    external: ['react', 'react/*', 'react-dom', 'react-dom/*'], loader: { '.css': 'empty' } });
  const output = join(temporary, 'components.mjs');
  await writeFile(output, result.outputFiles[0].text);
  components = await import(pathToFileURL(output));
});
after(async () => { if (temporary) { assert.ok(temporary.startsWith(join(uiRoot, 'tests', '.controls-render-'))); await rm(temporary, { recursive: true, force: true }); } });
const render = (Component, props) => renderToStaticMarkup(React.createElement(Component, props));
const tagsOf = (html, cls) => [...html.matchAll(/<[a-z][^>]*>/g)].map(match => match[0]).filter(tag => new RegExp(`class="(?:[^"]* )?${cls}(?: [^"]*)?"`).test(tag));
const tagOf = (html, cls) => tagsOf(html, cls)[0];
const count = (html, pattern) => (html.match(pattern) || []).length;

test('NumberField renders a spinbutton with value, range, unit and state classes', () => {
  const html = render(components.NumberField, { value: 0.6, unit: '×', min: 0.1, max: 4, ariaLabel: 'Speed' });
  const input = tagOf(html, 'ctl-nf-input');
  assert.match(input, /role="spinbutton"/);
  assert.match(input, /aria-label="Speed"/);
  assert.match(input, /aria-valuenow="0.6"/);
  assert.match(input, /aria-valuemin="0.1"/);
  assert.match(input, /aria-valuemax="4"/);
  assert.match(input, /aria-valuetext="0.60×"/);
  assert.match(input, /value="0.60"/);
  assert.match(html, /<i class="ctl-nf-unit" aria-hidden="true">×<\/i>/);
  assert.doesNotMatch(html, /is-modified|is-invalid|is-disabled|aria-invalid|role="alert"/);
  assert.match(tagOf(html, 'ctl-nf'), /class="ctl-kit ctl-nf"/);
});

test('NumberField marks modified, invalid and disabled, and shows its error text only when invalid', () => {
  assert.match(tagOf(render(components.NumberField, { value: 1, modified: true }), 'ctl-nf'), /is-modified/);
  const bad = render(components.NumberField, { value: 9, invalid: true, errorText: 'Out of range', ariaLabel: 'Speed' });
  assert.match(tagOf(bad, 'ctl-nf'), /is-invalid/);
  assert.match(tagOf(bad, 'ctl-nf-input'), /aria-invalid="true"/);
  assert.match(bad, /<span id="([^"]+)" class="ctl-nf-err" role="alert">Out of range<\/span>/);
  assert.equal(bad.match(/aria-describedby="([^"]+)"/)[1], bad.match(/<span id="([^"]+)" class="ctl-nf-err"/)[1], 'the input points at its message');
  assert.doesNotMatch(render(components.NumberField, { value: 9, invalid: true }), /ctl-nf-err/, 'no text, no message element');
  assert.doesNotMatch(render(components.NumberField, { value: 1, errorText: 'Out of range' }), /Out of range/);
  const off = render(components.NumberField, { value: 1, disabled: true });
  assert.match(tagOf(off, 'ctl-nf'), /is-disabled/);
  assert.match(tagOf(off, 'ctl-nf-input'), /disabled=""/);
});

test('NumberField shows sign labels, a linked label, the dragging state and forwards class and style', () => {
  const signed = render(components.NumberField, { value: -1.2, unit: 's', signLabels: { negative: 'Early ', positive: 'Late ' }, min: -2, max: 2 });
  assert.match(tagOf(signed, 'ctl-nf-input'), /value="Early 1.20"/);
  assert.match(tagOf(signed, 'ctl-nf-input'), /aria-valuetext="Early 1.20 s"/);
  assert.match(tagOf(signed, 'ctl-nf-input'), /aria-valuenow="-1.2"/);
  const labelled = render(components.NumberField, { value: 0.42, label: 'x1', className: 'mine', style: { width: 120 } });
  const id = tagOf(labelled, 'ctl-nf-input').match(/id="([^"]+)"/)[1];
  assert.match(labelled, new RegExp(`<label class="ctl-nf-label" for="${id}">x1</label>`));
  assert.match(tagOf(labelled, 'ctl-nfw'), /class="ctl-kit ctl-nfw mine"/);
  assert.match(tagOf(labelled, 'ctl-nfw'), /style="width:120px"/);
  const dragging = render(components.NumberField, { value: 0.64, dragging: true });
  assert.match(tagOf(dragging, 'ctl-nf'), /is-drag/);
  assert.equal(count(dragging, /class="ctl-nf-arrow"/g), 2);
  const plain = render(components.NumberField, { value: 1, className: 'mine', style: { margin: 3 } });
  assert.match(tagOf(plain, 'ctl-nf'), /class="ctl-kit ctl-nf mine"/);
  assert.match(tagOf(plain, 'ctl-nf'), /style="margin:3px"/);
  const empty = render(components.NumberField, { value: undefined });
  assert.match(tagOf(empty, 'ctl-nf-input'), /value=""/);
  assert.doesNotMatch(tagOf(empty, 'ctl-nf-input'), /aria-valuenow/);
});

test('ScrubLabel renders its text with the scrub class and honours disabled', () => {
  const label = (props, text) => renderToStaticMarkup(React.createElement(components.ScrubLabel, { value: 0.6, ...props }, text));
  assert.equal(label({ className: 'mine' }, 'Speed'), '<span class="ctl-kit ctl-scrub mine">Speed</span>');
  assert.equal(label({ disabled: true }, 'Speed'), '<span class="ctl-kit ctl-scrub is-disabled">Speed</span>');
  assert.match(label({ style: { width: 40 } }, 'Speed'), /style="width:40px"/);
});

test('Slider renders role=slider with value attributes, fill, default notch, ticks and state', () => {
  const html = render(components.Slider, { value: 0.6, min: 0, max: 1, defaultValue: 0.47, ticks: [0.25, 0.5], ariaLabel: 'Speed' });
  const thumb = tagOf(html, 'ctl-sl-k');
  assert.match(thumb, /role="slider"/);
  assert.match(thumb, /tabindex="0"/);
  assert.match(thumb, /aria-label="Speed"/);
  assert.match(thumb, /aria-valuemin="0"/);
  assert.match(thumb, /aria-valuemax="1"/);
  assert.match(thumb, /aria-valuenow="0.6"/);
  assert.match(thumb, /aria-valuetext="0.6"/);
  assert.match(thumb, /style="left:60%"/);
  assert.match(tagOf(html, 'ctl-sl-f'), /style="left:0%;width:60%"/);
  assert.match(tagOf(html, 'ctl-sl-d'), /style="left:47%"/);
  assert.deepEqual(tagsOf(html, 'ctl-sl-tk').map(tag => tag.match(/left:([\d.]+%)/)[1]), ['25%', '50%']);
  assert.match(tagOf(html, 'ctl-sl'), /class="ctl-kit ctl-sl is-modified"/, 'a value off its default is modified');
  assert.doesNotMatch(render(components.Slider, { value: 0.47, defaultValue: 0.47 }), /is-modified/);
  assert.doesNotMatch(html, /ctl-bub/, 'the value bubble exists only while dragging');
});

test('Slider text: aria-valuetext from a string or a function, bipolar fill from the centre, disabled state', () => {
  assert.match(tagOf(render(components.Slider, { value: 1.2, min: -2, max: 2, valueText: 'Late 1.2 s' }), 'ctl-sl-k'), /aria-valuetext="Late 1.2 s"/);
  assert.match(tagOf(render(components.Slider, { value: 1.2, min: -2, max: 2, valueText: v => `${v} seconds` }), 'ctl-sl-k'), /aria-valuetext="1.2 seconds"/);
  const late = render(components.Slider, { value: 1, min: -2, max: 2, bipolar: true });
  assert.match(tagOf(late, 'ctl-sl-f'), /style="left:50%;width:25%"/);
  assert.match(tagOf(late, 'ctl-sl-d'), /style="left:50%"/, 'the centre notch marks zero');
  assert.match(tagOf(render(components.Slider, { value: -1, min: -2, max: 2, bipolar: true }), 'ctl-sl-f'), /style="left:25%;width:25%"/);
  const off = render(components.Slider, { value: 0.5, disabled: true, ariaLabel: 'Speed' });
  assert.match(tagOf(off, 'ctl-sl-k'), /aria-disabled="true"/);
  assert.match(tagOf(off, 'ctl-sl-k'), /tabindex="-1"/);
  assert.match(tagOf(off, 'ctl-sl'), /is-disabled/);
  assert.match(tagOf(render(components.Slider, { value: 5, min: 10, max: 10 }), 'ctl-sl-k'), /style="left:0%"/, 'a flat range does not blow up');
  assert.match(tagOf(render(components.Slider, { value: undefined }), 'ctl-sl-k'), /^<span role="slider" tabindex="0" class="ctl-sl-k" style="left:0%" aria-orientation="horizontal" aria-valuemin="0" aria-valuemax="1">$/);
});

test('RangeSlider renders two labelled slider handles, a middle, and the trim hatch on request', () => {
  const html = render(components.RangeSlider, { start: 1, end: 5, min: 0, max: 6, step: 0.1, ariaLabelStart: 'In point', ariaLabelEnd: 'Out point', trimmedHatch: true, formatValue: v => `${v.toFixed(1)}s` });
  const handles = tagsOf(html, 'ctl-rg-h');
  assert.equal(handles.length, 2);
  assert.ok(handles.every(tag => /role="slider"/.test(tag) && /tabindex="0"/.test(tag)));
  const [start, end] = handles;
  assert.match(start, /data-handle="start"/);
  assert.match(start, /aria-label="In point"/);
  assert.match(start, /aria-valuenow="1"/);
  assert.match(start, /aria-valuemin="0"/);
  assert.match(start, /aria-valuemax="4"/, 'start cannot pass one gap before end');
  assert.match(start, /aria-valuetext="1.0s"/);
  assert.match(start, /style="left:16.667%"/);
  assert.match(end, /data-handle="end"/);
  assert.match(end, /aria-label="Out point"/);
  assert.match(end, /aria-valuemin="2"/, 'end cannot pass one gap after start');
  assert.match(end, /aria-valuemax="6"/);
  assert.match(end, /aria-valuetext="5.0s"/);
  assert.match(tagOf(html, 'ctl-rg-r'), /data-handle="slide"/);
  assert.match(tagOf(html, 'ctl-rg-r'), /style="left:16.667%;width:66.667%"/);
  assert.equal(tagsOf(html, 'ctl-rg-hatch').length, 2);
  assert.equal(count(render(components.RangeSlider, { start: 1, end: 5, min: 0, max: 6 }), /ctl-rg-hatch/g), 0, 'no hatch unless asked for');
  assert.match(tagOf(render(components.RangeSlider, { start: 1, end: 5, min: 0, max: 6, minGap: 2 }), 'ctl-rg-h'), /aria-valuemax="3"/);
  const off = render(components.RangeSlider, { start: 0, end: 1, disabled: true });
  assert.match(tagOf(off, 'ctl-rg'), /is-disabled/);
  assert.ok(tagsOf(off, 'ctl-rg-h').every(tag => /aria-disabled="true"/.test(tag) && /tabindex="-1"/.test(tag)));
});

test('TimecodeField renders four labelled spinbuttons that follow the frame rate', () => {
  const html = render(components.TimecodeField, { frames: 204, fps: 24, ariaLabel: 'Out point' });
  assert.match(tagOf(html, 'ctl-tcf'), /role="group"/);
  assert.match(tagOf(html, 'ctl-tcf'), /aria-label="Out point"/);
  const segments = tagsOf(html, 'ctl-sg');
  assert.equal(segments.length, 4);
  assert.ok(segments.every(tag => /role="spinbutton"/.test(tag) && /tabindex="0"/.test(tag)));
  assert.deepEqual(segments.map(tag => tag.match(/aria-valuenow="(\d+)"/)[1]), ['0', '0', '8', '12']);
  assert.deepEqual(segments.map(tag => tag.match(/aria-valuemax="(\d+)"/)[1]), ['99', '59', '59', '23']);
  assert.deepEqual(segments.map(tag => tag.match(/aria-label="([^"]+)"/)[1]), ['Out point hh', 'Out point mm', 'Out point ss', 'Out point ff']);
  assert.match(html, />00<\/span><i class="ctl-tcf-sep" aria-hidden="true">:<\/i><span[^>]*>00<\/span><i[^>]*>:<\/i><span[^>]*>08<\/span><i[^>]*>:<\/i><span[^>]*>12<\/span>/);
  assert.equal(tagsOf(render(components.TimecodeField, { frames: 0, fps: 25 }), 'ctl-sg')[3].match(/aria-valuemax="(\d+)"/)[1], '24');
  assert.equal(tagsOf(render(components.TimecodeField, { frames: 0, fps: 30 }), 'ctl-sg')[3].match(/aria-valuemax="(\d+)"/)[1], '29');
  assert.equal(tagsOf(render(components.TimecodeField, { frames: 0 }), 'ctl-sg')[3].match(/aria-valuemax="(\d+)"/)[1], '23', '24 fps by default');
  assert.equal(render(components.TimecodeField, { frames: 25 * 61 + 3, fps: 25 }).match(/<span[^>]*>(\d\d)<\/span>/g).map(s => s.replace(/<[^>]+>/g, '')).join(':'), '00:01:01:03');
  const named = render(components.TimecodeField, { frames: 0, segmentLabels: { h: 'Hours', m: 'Minutes', s: 'Seconds', f: 'Frames' } });
  assert.deepEqual(tagsOf(named, 'ctl-sg').map(tag => tag.match(/aria-label="([^"]+)"/)[1]), ['Hours', 'Minutes', 'Seconds', 'Frames']);
});

test('TimecodeField shows a negative sign and its modified, invalid and disabled states', () => {
  const negative = render(components.TimecodeField, { frames: -12, fps: 24 });
  assert.match(negative, /<i class="ctl-tcf-sign" aria-hidden="true">-<\/i>/);
  assert.match(tagsOf(negative, 'ctl-sg')[0], /aria-valuetext="-00"/, 'the sign is spoken with the first segment');
  assert.doesNotMatch(render(components.TimecodeField, { frames: 12 }), /ctl-tcf-sign/);
  assert.match(tagOf(render(components.TimecodeField, { frames: 0, modified: true }), 'ctl-tcf'), /is-modified/);
  const bad = render(components.TimecodeField, { frames: 0, invalid: true });
  assert.match(tagOf(bad, 'ctl-tcf'), /is-invalid/);
  assert.match(tagOf(bad, 'ctl-tcf'), /aria-invalid="true"/);
  const off = render(components.TimecodeField, { frames: 0, disabled: true });
  assert.match(tagOf(off, 'ctl-tcf'), /is-disabled/);
  assert.ok(tagsOf(off, 'ctl-sg').every(tag => /tabindex="-1"/.test(tag) && /aria-disabled="true"/.test(tag)));
});

test('KeyframeButton is a toggle: aria-pressed is true only when a key sits at the playhead', () => {
  const state = name => tagOf(render(components.KeyframeButton, { state: name, ariaLabel: 'Keyframe: Speed' }), 'ctl-kf');
  assert.match(state('here'), /aria-pressed="true"/);
  assert.match(state('here'), /is-here/);
  assert.match(state('none'), /aria-pressed="false"/);
  assert.match(state('none'), /is-none/);
  assert.match(state('elsewhere'), /aria-pressed="false"/);
  assert.match(state('elsewhere'), /is-elsewhere/);
  assert.match(state('none'), /aria-label="Keyframe: Speed"/);
  assert.match(state('none'), /type="button"/);
  assert.match(state('bogus'), /is-none/, 'an unknown state reads as none');
  assert.match(tagOf(render(components.KeyframeButton, {}), 'ctl-kf'), /is-none/, 'none by default');
  assert.match(tagOf(render(components.KeyframeButton, { state: 'here', disabled: true }), 'ctl-kf'), /disabled=""/);
});

test('ResetButton names itself, lights up only when active and is inert otherwise', () => {
  const on = tagOf(render(components.ResetButton, { active: true }), 'ctl-rs');
  assert.match(on, /aria-label="Reset"/);
  assert.match(on, /is-active/);
  assert.doesNotMatch(on, /disabled/);
  const off = tagOf(render(components.ResetButton, { active: false, ariaLabel: 'Reset speed' }), 'ctl-rs');
  assert.match(off, /aria-label="Reset speed"/);
  assert.match(off, /disabled=""/);
  assert.doesNotMatch(off, /is-active/);
  assert.match(tagOf(render(components.ResetButton, { active: true, disabled: true }), 'ctl-rs'), /disabled=""/);
  assert.match(render(components.ResetButton, {}), /<svg[^>]*aria-hidden="true"/, 'the icon is decoration');
  assert.doesNotMatch(tagOf(render(components.ResetButton, {}), 'ctl-rs'), /disabled/, 'active by default');
});

test('ParamRow lays the parts out compact (two lines) or as one five-column row', () => {
  const part = name => React.createElement('b', { 'data-part': name });
  const parts = { label: 'Speed', field: part('field'), slider: part('slider'), extra: part('extra'), keyframe: part('keyframe'), reset: part('reset') };
  const order = html => ['Speed', 'data-part="field"', 'data-part="slider"', 'data-part="extra"', 'data-part="keyframe"', 'data-part="reset"'].map(marker => html.indexOf(marker));
  const compact = render(components.ParamRow, parts);
  assert.match(tagOf(compact, 'ctl-pc'), /data-layout="compact"/);
  const [label, field, slider, extra, keyframe, reset] = order(compact);
  assert.ok(label < field && field < keyframe && keyframe < reset, 'first line: label, field, keyframe, reset');
  assert.ok(reset < slider && slider < extra, 'second line: slider then extra');
  assert.ok(compact.indexOf('class="ctl-pr-main"') > compact.indexOf('data-part="reset"'));
  const row = render(components.ParamRow, { ...parts, compact: false });
  assert.match(tagOf(row, 'ctl-pr'), /data-layout="row"/);
  const [rLabel, rField, rSlider, rExtra, rKey, rReset] = order(row);
  assert.ok(rLabel < rField && rField < rSlider && rSlider < rExtra && rExtra < rKey && rKey < rReset, 'one line: label | field | slider+extra | keyframe | reset');
  assert.doesNotMatch(row, /ctl-pch/);
});

test('ParamRow marks modified rows with the dot and keeps its slot when unmodified', () => {
  const modified = render(components.ParamRow, { label: 'Speed', modified: true });
  assert.match(tagOf(modified, 'ctl-pc'), /is-modified/);
  assert.match(tagOf(modified, 'ctl-pl'), /is-modified/);
  assert.match(modified, /<i class="ctl-dot" aria-hidden="true"><\/i>Speed/);
  const plain = render(components.ParamRow, { label: 'Speed' });
  assert.doesNotMatch(plain, /is-modified/);
  assert.match(plain, /<i class="ctl-dot" aria-hidden="true"><\/i>Speed/, 'the dot slot stays so labels align');
  assert.doesNotMatch(plain, /ctl-pr-main/, 'no slider, no second line');
  assert.match(tagOf(render(components.ParamRow, { label: 'Ease', compact: false, extra: React.createElement('b') }), 'ctl-pr'), /is-fieldless/);
  assert.doesNotMatch(tagOf(render(components.ParamRow, { label: 'x', compact: false, field: React.createElement('b') }), 'ctl-pr'), /is-fieldless/);
  assert.match(tagOf(render(components.ParamRow, { label: 'x', className: 'mine', style: { margin: 1 } }), 'ctl-pc'), /class="ctl-kit ctl-pc mine" style="margin:1px"/);
});

test('CurveThumb draws the easing path over a dashed linear reference', () => {
  const html = render(components.CurveThumb, { values: EASE });
  assert.equal(tagOf(html, 'ctl-ct-line').match(/ d="([^"]+)"/)[1], bezierPath(EASE, { width: 56, height: 28, padding: 6 }));
  assert.match(tagOf(html, 'ctl-ct-ref'), / d="M6 22 L50 6"/);
  assert.match(html, /<svg[^>]*width="56" height="28" viewBox="0 0 56 28" aria-hidden="true"/);
  const custom = render(components.CurveThumb, { values: [0.34, 1.56, 0.64, 1], width: 40, height: 28, padding: 4, reference: false, active: true, dashed: true });
  assert.equal(tagOf(custom, 'ctl-ct-line').match(/ d="([^"]+)"/)[1], bezierPath([0.34, 1.56, 0.64, 1], { width: 40, height: 28, padding: 4 }));
  assert.doesNotMatch(custom, /ctl-ct-ref/);
  assert.match(tagOf(custom, 'ctl-ct'), /is-active/);
  assert.match(tagOf(custom, 'ctl-ct'), /is-dashed/);
});

test('CurveEditor renders four number fields, one button per preset and the curve path', () => {
  const html = render(components.CurveEditor, { values: EASE, presetLabels: { easeInOut: 'Ease in-out', linear: 'Linear' } });
  const inputs = tagsOf(html, 'ctl-nf-input');
  assert.equal(inputs.length, 4);
  assert.deepEqual(inputs.map(tag => tag.match(/aria-label="([^"]+)"/)[1]), ['x1', 'y1', 'x2', 'y2']);
  assert.deepEqual(inputs.map(tag => tag.match(/value="([^"]+)"/)[1]), ['0.42', '0.00', '0.58', '1.00']);
  assert.deepEqual(inputs.map(tag => tag.match(/aria-valuemax="([^"]+)"/)[1]), ['1', '1', '1', '1']);
  assert.equal(tagsOf(html, 'ctl-pst').filter(tag => tag.startsWith('<button')).length, BEZIER_PRESETS.length);
  assert.equal(count(html, /<button type="button" class="ctl-btn ctl-pst/g), 6);
  assert.match(html, /<span>Ease in-out<\/span>/);
  assert.match(html, /<span>Linear<\/span>/);
  assert.match(html, /<span>strongEaseOut<\/span>/, 'a preset without a label shows its id');
  assert.equal(tagOf(html, 'ctl-ce-curve').match(/ d="([^"]+)"/)[1], bezierPath(EASE, { width: 300, height: 300, padding: 0 }));
  assert.match(html, /<code class="ctl-ce-code">cubic-bezier\(0.42, 0, 0.58, 1\)<\/code>/);
  assert.match(tagOf(html, 'ctl-ce-svg'), /width="380" height="392" viewBox="0 0 380 392"/);
  assert.deepEqual(tagsOf(html, 'ctl-nf').map(tag => /is-modified/.test(tag)), [true, false, true, false], 'fields that differ from linear carry the dot');
  assert.doesNotMatch(html, /ctl-ce-unit/, 'no overshoot, no unit-square outline');
});

test('CurveEditor highlights the matching preset and shows a dashed custom row otherwise', () => {
  const html = render(components.CurveEditor, { values: EASE });
  const pressed = tagsOf(html, 'ctl-pst').filter(tag => /aria-pressed="true"/.test(tag));
  assert.equal(pressed.length, 1);
  assert.match(pressed[0], /is-on/);
  assert.doesNotMatch(html, /is-custom/);
  const custom = render(components.CurveEditor, { values: [0.3, 0.1, 0.7, 0.9], presetLabels: { custom: 'Custom' } });
  assert.equal(count(custom, /aria-pressed="true"/g), 0);
  assert.match(tagOf(custom, 'is-custom'), /^<div class="ctl-pst is-on is-custom" aria-current="true">$/);
  assert.match(custom, /<svg[^>]*class="ctl-kit ctl-ct is-active is-dashed"/);
  assert.match(custom, /<span>Custom<\/span>/);
  assert.equal(count(custom, /<button type="button" class="ctl-btn ctl-pst/g), 6, 'the custom row is not a button');
  assert.match(render(components.CurveEditor, { values: [0.3, 0.1, 0.7, 0.9] }), /<span>custom<\/span>/, 'the id stands in for a missing label');
  const mine = [{ id: 'snap', values: [0.9, 0, 1, 1] }, { id: 'glide', values: [0, 0.8, 0.2, 1] }];
  const small = render(components.CurveEditor, { values: [0, 0.8, 0.2, 1], presets: mine, presetLabels: { snap: 'Snap', glide: 'Glide' } });
  assert.equal(count(small, /<button type="button" class="ctl-btn ctl-pst/g), 2, 'presets come from props');
  assert.match(tagsOf(small, 'ctl-pst').find(tag => /aria-pressed="true"/.test(tag)), /is-on/);
  assert.match(small, /<span>Glide<\/span>/);
});

test('CurveEditor draws two slider handles, labels only what it is given, and scales with size', () => {
  const html = render(components.CurveEditor, { values: EASE });
  const handles = tagsOf(html, 'ctl-ce-h');
  assert.equal(handles.length, 2);
  assert.ok(handles.every(tag => /role="slider"/.test(tag) && /tabindex="0"/.test(tag)));
  assert.match(handles[0], /aria-label="P1"/);
  assert.match(handles[0], /aria-valuetext="x 0.42, y 0"/);
  assert.match(handles[1], /aria-valuetext="x 0.58, y 1"/);
  assert.doesNotMatch(html, />Time<|>Progress<|ctl-ce-cap|ctl-ce-apply|is-note/, 'no labels given, no text drawn');
  const labelled = render(components.CurveEditor, { values: EASE, labels: { time: 'Time', progress: 'Progress', locked: 'Ends fixed', overshoot: 'Can overshoot', preview: 'Motion preview', apply: 'Apply' } });
  for (const text of ['Time', 'Progress', 'Ends fixed', 'Motion preview']) assert.match(labelled, new RegExp(`>${text}<`), text);
  assert.match(labelled, /<button type="button" class="ctl-btn ctl-ce-apply">Apply<\/button>/);
  assert.doesNotMatch(labelled, /Can overshoot/, 'the overshoot note appears only when the plot is open');
  const small = render(components.CurveEditor, { values: EASE, size: 200 });
  assert.match(tagOf(small, 'ctl-ce-svg'), /width="280" height="292"/);
  assert.equal(tagOf(small, 'ctl-ce-curve').match(/ d="([^"]+)"/)[1], bezierPath(EASE, { width: 200, height: 200, padding: 0 }));
  assert.match(render(components.CurveEditor, { values: [0.5] }), /<code class="ctl-ce-code">cubic-bezier\(0.5, 0, 1, 1\)<\/code>/, 'missing numbers fall back to linear');
});

test('CurveEditor draws the motion-preview dots and the time marker', () => {
  const html = render(components.CurveEditor, { values: EASE, progressAtTime: 0.6 });
  const dots = html.match(/<div class="ctl-dots"[^>]*>(.*?)<\/div>/)[1].match(/<i style="left:([\d.]+)%"><\/i>/g);
  assert.equal(dots.length, 11, 'ten steps, eleven dots');
  assert.match(dots[0], /left:0%/);
  assert.match(dots[10], /left:100%/);
  const lefts = dots.map(dot => Number(dot.match(/left:([\d.]+)%/)[1]));
  assert.ok(lefts[1] < 10 && lefts[5] === 50 && lefts[9] > 90, 'dense at the ends, sparse in the middle');
  assert.doesNotMatch(render(components.CurveEditor, { values: EASE, previewDots: false }), /ctl-dots/);
  assert.match(tagOf(html, 'ctl-ce-mark'), /cx="224"/, 'time 0.6 sits at 44 + 0.6 x 300');
  assert.match(tagOf(html, 'ctl-ce-mark'), new RegExp(`cy="${Number((28 + (1 - bezierAt(EASE, 0.6)) * 300).toFixed(2))}"`));
  assert.match(html, />0\.60<\/text>/);
  assert.match(html, />0\.67<\/text>/, 'progress at 0.6 is 0.67');
  assert.doesNotMatch(render(components.CurveEditor, { values: EASE }), /ctl-ce-mark|ctl-ce-time/);
});

test('CurveEditor opens the overshoot range for the prop or for a curve that already leaves 0..1', () => {
  const back = [0.34, 1.56, 0.64, 1];
  const html = render(components.CurveEditor, { values: back, labels: { overshoot: 'Can overshoot' } });
  assert.equal(tagOf(html, 'ctl-ce-curve').match(/ d="([^"]+)"/)[1], bezierPath(back, { width: 300, height: 300, padding: 0, yMin: -0.5, yMax: 1.75 }));
  assert.notEqual(tagOf(html, 'ctl-ce-curve').match(/ d="([^"]+)"/)[1], bezierPath(back, { width: 300, height: 300, padding: 0 }));
  assert.match(html, /ctl-ce-unit/);
  assert.match(html, />Can overshoot</);
  const fields = tagsOf(html, 'ctl-nf-input');
  assert.deepEqual(fields.map(tag => [tag.match(/aria-valuemin="([^"]+)"/)[1], tag.match(/aria-valuemax="([^"]+)"/)[1]]), [['0', '1'], ['-1', '2'], ['0', '1'], ['-1', '2']], 'y fields may leave 0..1');
  assert.match(html, /aria-valuetext="x 0.34, y 1.56"/);
  const forced = render(components.CurveEditor, { values: EASE, overshoot: true });
  assert.equal(tagOf(forced, 'ctl-ce-curve').match(/ d="([^"]+)"/)[1], bezierPath(EASE, { width: 300, height: 300, padding: 0, yMin: -0.5, yMax: 1.5 }));
  assert.match(forced, /ctl-ce-unit/);
});

test('the kit stays self-contained: no i18n, a DOM-free model, and every CSS rule scoped under .ctl-', async () => {
  const [jsx, model, css] = await Promise.all(['Controls.jsx', 'controlsModel.js', 'controls.css'].map(name => readFile(join(uiRoot, 'src/controls', name), 'utf8')));
  assert.doesNotMatch(jsx, /from\s+['"][^'"]*i18n[^'"]*['"]|react-i18next|\buseLocale\b|\bt\(\s*['"`]/, 'strings come in through props');
  assert.doesNotMatch(model, /\b(?:document|window|navigator|localStorage)\b|from\s+['"]react|\beval\s*\(|new Function/, 'the model is pure');
  assert.match(jsx, /import '\.\/controls\.css'/, 'the components bring their own stylesheet');
  const rules = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const selectors = [...rules.matchAll(/([^{}]+)\{/g)].map(match => match[1].trim()).filter(selector => !selector.startsWith('@'));
  assert.ok(selectors.length > 80, 'the stylesheet was parsed');
  for (const group of selectors) for (const selector of group.split(',')) assert.match(selector.trim(), /^\.ctl-/, `unscoped selector: ${selector.trim()}`);
  assert.doesNotMatch(rules, /var\(--(?:sunken|bg|panel|raised|hover|line|line2|text|muted|faint|accent|accent-soft|on-accent)\)/, 'palette tokens always carry their midnight fallback');
  for (const [token, fallback] of [['panel', '#171D26'], ['raised', '#1F2630'], ['sunken', '#0E1217'], ['accent', '#F2B33D'], ['text', '#E6EAF0']]) assert.match(rules, new RegExp(`var\\(--${token}, ${fallback}\\)`));
});
