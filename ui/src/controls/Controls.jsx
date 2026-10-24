import { Fragment, useEffect, useId, useRef, useState } from 'react';
import {
  BEZIER_PRESETS, DEFAULT_FPS, bezierAt, bezierPath, clamp, formatBezier, formatValue as formatNumber, fractionToValue, framesToParts,
  matchBezierPreset, moveBezierHandle, moveRangeHandle, normalizeBezier, parseTimecode, parseValueInput, roundToStep, sampleBezier, scrubValue,
  slideRange, snapValue, stepTimecode, valueToFraction,
} from './controlsModel.js';
import './controls.css';

// Control kit: the shared "adjust" and "drag" parts of the studio inspector. Every visible and aria string arrives through props
// (no i18n in here); the math lives in controlsModel.js. Modifier keys are the same everywhere: Shift = fine (x0.1) while dragging
// and x10 on arrow keys, Ctrl/Cmd = snap, Alt = only this one (reported to the caller), Escape = cancel and restore.
const cx = (...parts) => parts.filter(Boolean).join(' ');
const finite = n => typeof n === 'number' && Number.isFinite(n);
const tidy = n => Number(n.toFixed(10));
const pct = fraction => `${Number((fraction * 100).toFixed(3))}%`;
const near = (a, b) => Math.abs(a - b) < 1e-9;
const two = n => String(n).padStart(2, '0');

// Pointer drag shared by every draggable part: captures the pointer on press, Escape cancels, and the handlers always see the
// latest props. onStart returns the drag's own mutable state (or false to refuse); onEnd(event, cancelled, state) closes it.
function useDrag({ onStart, onMove, onEnd }) {
  const latest = useRef(null), session = useRef(null), [active, setActive] = useState(false);
  latest.current = { onStart, onMove, onEnd };
  const stop = (event, cancelled) => {
    const current = session.current;
    if (!current) return;
    session.current = null;
    setActive(false);
    window.removeEventListener('keydown', current.onKey, true);
    try { current.element.releasePointerCapture?.(current.id); } catch { /* the capture is already gone */ }
    latest.current.onEnd?.(event, cancelled, current.data);
  };
  useEffect(() => () => { if (session.current) window.removeEventListener('keydown', session.current.onKey, true); }, []);
  const bind = {
    onPointerDown(event) {
      if (event.pointerType === 'mouse' && event.button !== 0) return;
      const data = latest.current.onStart?.(event);
      if (data === false) return;
      const element = event.currentTarget;
      try { element.setPointerCapture?.(event.pointerId); } catch { /* synthetic pointer: nothing to capture */ }
      const onKey = key => { if (key.key === 'Escape') { key.preventDefault(); key.stopPropagation(); stop(key, true); } };
      window.addEventListener('keydown', onKey, true);
      session.current = { element, id: event.pointerId, data, onKey };
      setActive(true);
    },
    onPointerMove(event) { if (session.current) latest.current.onMove?.(event, session.current.data); },
    onPointerUp(event) { stop(event, false); },
    onPointerCancel(event) { stop(event, true); },
  };
  return { active, bind };
}

// ---------- Number field ----------
// Typed text goes through parseValueInput (numbers, arithmetic, "+0.2" when relative). Enter and blur commit, Escape reverts,
// ArrowUp/Down step (Shift x10, Alt x0.1). Text that is not a value turns the field red and never reaches onChange.
// onChange(value) fires for every change, onCommit(value) when an edit is finished; `dragging` is the scrub-label drag state.
export function NumberField({ value, onChange, onCommit, min, max, step = 0.01, decimals = 2, unit, label, signLabels, modified, disabled, invalid, errorText, ariaLabel, relative, dragging, className, style }) {
  const id = useId(), errorId = `${id}-err`, input = useRef(null), armed = useRef(false);
  const [draft, setDraft] = useState(null), [typo, setTypo] = useState(false);
  const shown = formatNumber(value, { decimals, signLabels });
  const bad = Boolean(invalid) || typo;
  const parse = text => parseValueInput(text, { min, max, current: value, relative, unit, signLabels });
  const settle = () => { setDraft(null); setTypo(false); };
  const commit = text => {
    const parsed = parse(text);
    if (parsed === null) return false;
    settle();
    if (parsed !== value) { onChange?.(parsed); onCommit?.(parsed); }
    return true;
  };
  const nudge = (direction, event) => {
    const base = draft === null ? value : parse(draft) ?? value;
    const next = clamp(tidy((finite(base) ? base : 0) + direction * step * (event.shiftKey ? 10 : event.altKey ? 0.1 : 1)), min, max);
    setTypo(false);
    if (draft !== null) setDraft(formatNumber(next, { decimals, signLabels }));
    if (next !== value) { onChange?.(next); onCommit?.(next); }
  };
  const onKeyDown = event => {
    if (event.key === 'ArrowUp' || event.key === 'ArrowDown') { event.preventDefault(); nudge(event.key === 'ArrowUp' ? 1 : -1, event); }
    else if (event.key === 'Enter') { event.preventDefault(); if (draft !== null && !commit(draft)) setTypo(true); }
    else if (event.key === 'Escape' && (draft !== null || typo)) { event.preventDefault(); event.stopPropagation(); settle(); }
  };
  const field = (
    <span className={cx(!label && 'ctl-kit', 'ctl-nf', modified && 'is-modified', dragging && 'is-drag', bad && 'is-invalid', disabled && 'is-disabled', !label && className)} style={label ? undefined : style}>
      {dragging && <i className="ctl-nf-arrow" aria-hidden="true">{'◂'}</i>}
      <input ref={input} id={id} className="ctl-nf-input" type="text" inputMode="decimal" autoComplete="off" spellCheck={false} role="spinbutton"
        size={Math.max(3, (draft ?? shown).length)} value={draft ?? shown} disabled={disabled} aria-label={ariaLabel} aria-invalid={bad || undefined} aria-describedby={bad && errorText ? errorId : undefined}
        aria-valuenow={finite(value) ? value : undefined} aria-valuemin={finite(min) ? min : undefined} aria-valuemax={finite(max) ? max : undefined}
        aria-valuetext={shown ? formatNumber(value, { decimals, unit, signLabels }) : undefined}
        onPointerDown={() => { armed.current = document.activeElement !== input.current; }}
        onMouseUp={event => { if (armed.current) { armed.current = false; event.preventDefault(); } }}
        onFocus={event => event.currentTarget.select()}
        onChange={event => { const text = event.target.value; setDraft(text); setTypo(text.trim() !== '' && parse(text) === null); }}
        onKeyDown={onKeyDown}
        onBlur={() => { if (draft !== null && !commit(draft)) settle(); else setTypo(false); }} />
      {dragging && <i className="ctl-nf-arrow" aria-hidden="true">{'▸'}</i>}
      {unit && <i className="ctl-nf-unit" aria-hidden="true">{unit}</i>}
      {bad && errorText && <span id={errorId} className="ctl-nf-err" role="alert">{errorText}</span>}
    </span>
  );
  return label
    ? <span className={cx('ctl-kit ctl-nfw', className)} style={style}><label className="ctl-nf-label" htmlFor={id}>{label}</label>{field}</span>
    : field;
}

// ---------- Scrub label ----------
// A label you drag sideways to change a value (cursor ew-resize, Shift = fine, `fine` forces it, Ctrl/Cmd snaps to snapPoints,
// Escape restores the start value). It is not focusable: the keyboard path is the NumberField next to it. pxPerUnit defaults to
// "the whole min..max range in 240px" (1/step without a range). onDragChange(true|false) lets the field show its dragging state.
export function ScrubLabel({ children, value, onChange, onCommit, step = 0.01, min, max, pxPerUnit, fine = false, snapPoints, snapThreshold, disabled, onDragChange, className, style }) {
  const rate = pxPerUnit ?? (finite(min) && finite(max) && max > min ? 240 / (max - min) : 1 / step);
  const drag = useDrag({
    onStart: event => {
      if (disabled || !finite(value)) return false;
      onDragChange?.(true);
      return { x: event.clientX, from: value, start: value, last: value, fine: fine || event.shiftKey };
    },
    onMove: (event, d) => {
      const slow = fine || event.shiftKey;
      if (slow !== d.fine) { d.x = event.clientX; d.from = d.last; d.fine = slow; }   // re-anchor so toggling Shift never jumps the value
      const snap = event.ctrlKey || event.metaKey;
      const result = scrubValue({ start: d.from, dx: event.clientX - d.x, pxPerUnit: rate, step, min, max, fine: slow, snapPoints: snap ? snapPoints : undefined, snapThreshold });
      if (result.value !== d.last) { d.last = result.value; onChange?.(result.value); }
    },
    onEnd: (event, cancelled, d) => {
      onDragChange?.(false);
      if (cancelled) { if (d.last !== d.start) onChange?.(d.start); }
      else if (d.last !== d.start) onCommit?.(d.last);
    },
  });
  return <span className={cx('ctl-kit ctl-scrub', drag.active && 'is-drag', disabled && 'is-disabled', className)} style={style} {...(disabled ? {} : drag.bind)}>{children}</span>;
}

// ---------- Slider ----------
// role="slider" thumb on a 24px-tall hit area. A press on the track jumps there; on the thumb (or with Shift) it grabs without moving.
// The default-value notch pulls softly; Ctrl/Cmd snaps to snapPoints (else ticks) and the default; Shift is fine and never snaps.
// Keys: arrows step (Shift x10), PageUp/Down x10, Home/End min/max. `valueText` (string or fn) feeds aria-valuetext and the drag bubble.
export function Slider({ value, onChange, onCommit, min = 0, max = 1, step = 0.01, defaultValue, bipolar = false, ticks, snapPoints, ariaLabel, valueText, disabled, className, style }) {
  const root = useRef(null), thumb = useRef(null), [snapAt, setSnapAt] = useState(null);
  const span = max - min, hasDefault = finite(defaultValue);
  const text = v => (typeof valueText === 'function' ? valueText(v) : valueText ?? formatNumber(v, { decimals: 'auto' }));
  const targets = [...(snapPoints ?? ticks ?? []), ...(hasDefault ? [defaultValue] : [])];
  const resolve = (raw, event, fine) => {
    const perPx = span / (root.current?.getBoundingClientRect().width || 1), hard = event.ctrlKey || event.metaKey;
    const hit = fine ? { value: raw, snapped: null } : snapValue(raw, hard ? targets : hasDefault ? [defaultValue] : [], (hard ? 8 : 3) * perPx);
    return { value: hit.snapped === null ? fractionToValue(valueToFraction(raw, min, max), min, max, step) : hit.value, snapped: hit.snapped };
  };
  const apply = (d, result) => { setSnapAt(result.snapped); if (result.value !== d.last) { d.last = result.value; onChange?.(result.value); } };
  const drag = useDrag({
    onStart: event => {
      if (disabled || !(span > 0)) return false;
      const rect = root.current.getBoundingClientRect(), fine = event.shiftKey;
      const pointer = min + clamp((event.clientX - rect.left) / (rect.width || 1), 0, 1) * span;
      const onThumb = event.target === thumb.current || Math.abs(event.clientX - (rect.left + valueToFraction(value, min, max) * rect.width)) <= 8;
      const raw = onThumb || fine ? (finite(value) ? value : min) : pointer;
      thumb.current?.focus({ preventScroll: true });
      const d = { x: event.clientX, raw, now: raw, fine, start: value, last: value };
      if (!onThumb && !fine) apply(d, resolve(raw, event, false));
      return d;
    },
    onMove: (event, d) => {
      const fine = event.shiftKey, perPx = span / (root.current.getBoundingClientRect().width || 1);
      if (fine !== d.fine) { d.x = event.clientX; d.raw = d.now; d.fine = fine; }   // re-anchor so toggling Shift never jumps the thumb
      d.now = clamp(d.raw + (event.clientX - d.x) * perPx * (fine ? 0.1 : 1), min, max);
      apply(d, resolve(d.now, event, fine));
    },
    onEnd: (event, cancelled, d) => {
      setSnapAt(null);
      if (cancelled) { if (d.last !== d.start) onChange?.(d.start); }
      else if (d.last !== d.start) onCommit?.(d.last);
    },
  });
  const onKeyDown = event => {
    if (disabled) return;
    const key = event.key, big = step * 10, current = finite(value) ? value : min;
    let next;
    if (key === 'ArrowRight' || key === 'ArrowUp') next = current + (event.shiftKey ? big : step);
    else if (key === 'ArrowLeft' || key === 'ArrowDown') next = current - (event.shiftKey ? big : step);
    else if (key === 'PageUp') next = current + big;
    else if (key === 'PageDown') next = current - big;
    else if (key === 'Home') next = min;
    else if (key === 'End') next = max;
    else return;
    event.preventDefault();
    if (key !== 'Home' && key !== 'End') next = clamp(roundToStep(next, step, min), min, max);
    if (next !== value) { onChange?.(next); onCommit?.(next); }
  };
  const f = valueToFraction(value, min, max);
  const centre = bipolar ? valueToFraction(min < 0 && max > 0 ? 0 : (min + max) / 2, min, max) : 0;
  const modified = hasDefault && finite(value) && !near(value, defaultValue);
  const notch = (at, key) => <i key={key} className={cx('ctl-sl-d', snapAt !== null && near(snapAt, at) && 'is-snap')} style={{ left: pct(valueToFraction(at, min, max)) }} />;
  return (
    <div ref={root} className={cx('ctl-kit ctl-sl', drag.active && 'is-drag', snapAt !== null && 'is-snap', modified && 'is-modified', disabled && 'is-disabled', className)} style={style} {...drag.bind}>
      <i className="ctl-sl-t" />
      <i className="ctl-sl-f" style={{ left: pct(Math.min(centre, f)), width: pct(Math.abs(f - centre)) }} />
      {ticks?.map(tick => <i key={tick} className={cx('ctl-sl-tk', snapAt !== null && near(snapAt, tick) && 'is-snap')} style={{ left: pct(valueToFraction(tick, min, max)) }} />)}
      {bipolar && !(hasDefault && near(valueToFraction(defaultValue, min, max), centre)) && notch(min < 0 && max > 0 ? 0 : (min + max) / 2, 'centre')}
      {hasDefault && notch(defaultValue, 'default')}
      <span ref={thumb} role="slider" tabIndex={disabled ? -1 : 0} className="ctl-sl-k" style={{ left: pct(f) }} aria-label={ariaLabel} aria-orientation="horizontal"
        aria-valuemin={min} aria-valuemax={max} aria-valuenow={finite(value) ? value : undefined} aria-valuetext={finite(value) ? text(value) : undefined}
        aria-disabled={disabled || undefined} onKeyDown={onKeyDown} />
      {drag.active && finite(value) && <span className="ctl-bub" style={{ left: pct(f) }}>{text(value)}</span>}
    </div>
  );
}

// ---------- Range slider ----------
// Two handles (role="slider") and a draggable middle that slides the range keeping its length. onChange(range, {alt, handle}) and
// onCommit(range, {alt, handle}) get {start, end}; alt is Alt held, so a caller can skip rippling neighbours. Ctrl/Cmd snaps to
// snapPoints, Shift is fine. trimmedHatch hatches the media outside [start, end]. formatValue(v) writes the bubble and aria-valuetext.
export function RangeSlider({ start, end, min = 0, max = 1, step = 1, onChange, onCommit, minGap = 1, snapPoints, snapThreshold, ariaLabelStart, ariaLabelEnd, formatValue, trimmedHatch = false, disabled, className, style }) {
  const root = useRef(null), [mode, setMode] = useState(null), [snapAt, setSnapAt] = useState(null);
  const show = formatValue || (v => formatNumber(v, { decimals: 'auto' }));
  const span = max - min, fs = valueToFraction(start, min, max), fe = valueToFraction(end, min, max);
  const apply = (d, event) => {
    const fine = event.shiftKey;
    if (fine !== d.fine) { d.x = event.clientX; d.from = d.last; d.raw = d.now; d.fine = fine; }   // re-anchor so toggling Shift never jumps a handle
    const moved = (event.clientX - d.x) * d.perPx * (fine ? 0.1 : 1);
    let next, snapped = null;
    if (d.handle === 'slide') next = slideRange({ ...d.from, min, max }, moved, { step });
    else {
      d.now = d.raw + moved;
      const hard = event.ctrlKey || event.metaKey;
      const result = moveRangeHandle({ ...d.last, min, max }, d.handle, d.now, { minGap, step, snapPoints: hard ? snapPoints : undefined, snapThreshold: snapThreshold ?? 8 * d.perPx });
      next = { start: result.start, end: result.end };
      snapped = result.snapped;
    }
    setSnapAt(snapped);
    d.alt = event.altKey;
    if (next.start !== d.last.start || next.end !== d.last.end) { d.last = next; onChange?.(next, { alt: event.altKey, handle: d.handle }); }
  };
  const drag = useDrag({
    onStart: event => {
      if (disabled || !(span > 0)) return false;
      const rect = root.current.getBoundingClientRect(), perPx = span / (rect.width || 1);
      const pointer = min + clamp((event.clientX - rect.left) / (rect.width || 1), 0, 1) * span;
      let handle = event.target.closest?.('[data-handle]')?.dataset.handle;
      const jump = !handle;   // a press on the bare track pulls the nearer handle there
      if (jump) handle = Math.abs(pointer - start) <= Math.abs(pointer - end) ? 'start' : 'end';
      const raw = jump ? pointer : handle === 'end' ? end : start;
      const d = { handle, x: event.clientX, raw, now: raw, perPx, fine: event.shiftKey, alt: event.altKey, from: { start, end }, last: { start, end }, origin: { start, end } };
      setMode(handle);
      if (handle !== 'slide') root.current.querySelector(`[data-handle="${handle}"]`)?.focus({ preventScroll: true });
      if (jump) apply(d, event);
      return d;
    },
    onMove: (event, d) => apply(d, event),
    onEnd: (event, cancelled, d) => {
      setMode(null);
      setSnapAt(null);
      const changed = d.last.start !== d.origin.start || d.last.end !== d.origin.end;
      if (cancelled) { if (changed) onChange?.(d.origin, { alt: false, handle: d.handle }); }
      else if (changed) onCommit?.(d.last, { alt: Boolean(d.alt), handle: d.handle });
    },
  });
  const onKey = handle => event => {
    if (disabled) return;
    const key = event.key, big = step * 10, current = handle === 'end' ? end : start;
    let value;
    if (key === 'ArrowRight' || key === 'ArrowUp') value = current + (event.shiftKey ? big : step);
    else if (key === 'ArrowLeft' || key === 'ArrowDown') value = current - (event.shiftKey ? big : step);
    else if (key === 'PageUp') value = current + big;
    else if (key === 'PageDown') value = current - big;
    else if (key === 'Home') value = min;
    else if (key === 'End') value = max;
    else return;
    event.preventDefault();
    const moved = moveRangeHandle({ start, end, min, max }, handle, value, { minGap, step }), meta = { alt: event.altKey, handle };
    if (moved.start !== start || moved.end !== end) { onChange?.({ start: moved.start, end: moved.end }, meta); onCommit?.({ start: moved.start, end: moved.end }, meta); }
  };
  const handleProps = (handle, label, lo, hi, now) => ({
    role: 'slider', tabIndex: disabled ? -1 : 0, 'data-handle': handle, className: cx('ctl-rg-h', mode === handle && 'is-drag'), style: { left: pct(handle === 'end' ? fe : fs) },
    'aria-label': label, 'aria-orientation': 'horizontal', 'aria-valuemin': lo, 'aria-valuemax': hi, 'aria-valuenow': finite(now) ? now : undefined,
    'aria-valuetext': finite(now) ? show(now) : undefined, 'aria-disabled': disabled || undefined, onKeyDown: onKey(handle),
  });
  return (
    <div ref={root} className={cx('ctl-kit ctl-rg', mode && 'is-drag', snapAt !== null && 'is-snap', disabled && 'is-disabled', className)} style={style} {...drag.bind}>
      {trimmedHatch && <><i className="ctl-rg-hatch" style={{ left: 0, width: pct(fs) }} /><i className="ctl-rg-hatch" style={{ right: 0, width: pct(1 - fe) }} /></>}
      <i className="ctl-rg-r" data-handle="slide" style={{ left: pct(fs), width: pct(Math.max(0, fe - fs)) }} />
      {snapAt !== null && <i className="ctl-rg-snap" style={{ left: pct(valueToFraction(snapAt, min, max)) }} />}
      <span {...handleProps('start', ariaLabelStart, min, Math.max(min, end - minGap), start)} />
      <span {...handleProps('end', ariaLabelEnd, Math.min(max, start + minGap), max, end)} />
      {mode === 'slide' && <span className="ctl-bub" style={{ left: pct((fs + fe) / 2) }}>{show(start)} – {show(end)}</span>}
      {(mode === 'start' || mode === 'end') && <span className="ctl-bub" style={{ left: pct(mode === 'end' ? fe : fs) }}>{show(mode === 'end' ? end : start)}</span>}
    </div>
  );
}

// ---------- Timecode field ----------
// hh:mm:ss:ff, each segment a focusable role="spinbutton". ArrowUp/Down step the segment (Shift x10, carries like real timecode),
// ArrowLeft/Right and Tab move between segments, digits replace the segment (two digits, or one that cannot grow, move on),
// Enter commits, a pasted string goes through parseTimecode (signed text is relative to the current value when `relative`).
// Segment names for assistive tech come from segmentLabels {h, m, s, f}, else "<ariaLabel> hh|mm|ss|ff".
const SEGMENTS = ['h', 'm', 's', 'f'];
export function TimecodeField({ frames, fps = DEFAULT_FPS, onChange, onCommit, relative = false, min, max, ariaLabel, segmentLabels, modified, disabled, invalid, className, style }) {
  const parts = framesToParts(frames, fps), base = Math.max(1, Math.round(finite(fps) && fps > 0 ? fps : DEFAULT_FPS));
  const [at, setAt] = useState(-1), [typo, setTypo] = useState(false), typed = useRef(''), cells = useRef([]);
  const limit = key => (key === 'h' ? 99 : key === 'f' ? base - 1 : 59);
  const withSegment = (key, n) => {
    const next = { ...parts, [key]: clamp(n, 0, limit(key)) }, total = next.h * 3600 * base + next.m * 60 * base + next.s * base + next.f;
    return clamp(total === 0 ? 0 : parts.sign * total, min, max);
  };
  const focusCell = index => cells.current[clamp(index, 0, SEGMENTS.length - 1)]?.focus();
  const onKeyDown = (event, index) => {
    if (disabled) return;
    const key = SEGMENTS[index];
    if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
      event.preventDefault();
      typed.current = '';
      const next = stepTimecode(frames, fps, key, event.key === 'ArrowUp' ? 1 : -1, { shift: event.shiftKey, min, max });
      if (next !== frames) { onChange?.(next); onCommit?.(next); }
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault();
      focusCell(index + (event.key === 'ArrowRight' ? 1 : -1));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      typed.current = '';
      onCommit?.(frames);
    } else if (/^\d$/.test(event.key) && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      typed.current = (typed.current + event.key).slice(-2);
      const next = withSegment(key, Number(typed.current));
      if (next !== frames) onChange?.(next);
      if (typed.current.length === 2 || Number(typed.current) * 10 > limit(key)) { typed.current = ''; onCommit?.(next); focusCell(index + 1); }
    } else if (event.key === 'Backspace' || event.key === 'Delete') {
      event.preventDefault();
      typed.current = '';
      const next = withSegment(key, 0);
      if (next !== frames) onChange?.(next);
    }
  };
  const onPaste = event => {
    if (disabled) return;
    event.preventDefault();
    const parsed = parseTimecode(event.clipboardData?.getData('text') ?? '', fps, { current: relative ? frames : undefined });
    if (parsed === null) { setTypo(true); return; }
    const next = clamp(parsed, min, max);
    setTypo(false);
    onChange?.(next);
    onCommit?.(next);
  };
  const bad = Boolean(invalid) || typo;
  return (
    <span role="group" aria-label={ariaLabel} aria-invalid={bad || undefined} className={cx('ctl-kit ctl-tcf', modified && 'is-modified', bad && 'is-invalid', disabled && 'is-disabled', className)} style={style} onPaste={onPaste}>
      {parts.sign < 0 && <i className="ctl-tcf-sign" aria-hidden="true">-</i>}
      {SEGMENTS.map((key, index) => (
        <Fragment key={key}>
          {index > 0 && <i className="ctl-tcf-sep" aria-hidden="true">:</i>}
          <span ref={el => { cells.current[index] = el; }} role="spinbutton" tabIndex={disabled ? -1 : 0} className={cx('ctl-sg', at === index && 'is-on')}
            aria-label={segmentLabels?.[key] ?? ([ariaLabel, key + key].filter(Boolean).join(' '))} aria-valuemin={0} aria-valuemax={limit(key)} aria-valuenow={parts[key]}
            aria-valuetext={(index === 0 && parts.sign < 0 ? '-' : '') + two(parts[key])} aria-disabled={disabled || undefined}
            onFocus={() => { setAt(index); setTypo(false); typed.current = ''; }}
            onBlur={() => { setAt(-1); if (typed.current) { typed.current = ''; onCommit?.(frames); } }}
            onKeyDown={event => onKeyDown(event, index)}>{two(parts[key])}</span>
        </Fragment>
      ))}
    </span>
  );
}

// ---------- Keyframe diamond and reset ----------
// state: 'none' (hollow), 'here' (filled amber, a key sits at the playhead) or 'elsewhere' (hollow with a centre dot).
// aria-pressed means "there is a keyframe here": true only for 'here'.
export function KeyframeButton({ state = 'none', onToggle, ariaLabel, disabled, className, style }) {
  const kind = state === 'here' || state === 'elsewhere' ? state : 'none';
  return <button type="button" className={cx('ctl-kit ctl-btn ctl-kf', `is-${kind}`, className)} style={style} data-state={kind} aria-pressed={kind === 'here'}
    aria-label={ariaLabel} title={ariaLabel} disabled={disabled} onClick={event => onToggle?.(event)} />;
}

// Lights up (and works) only when the value differs from its default; dim and inert otherwise.
export function ResetButton({ active = true, onReset, ariaLabel = 'Reset', disabled, className, style }) {
  return (
    <button type="button" className={cx('ctl-kit ctl-btn ctl-rs', active && !disabled && 'is-active', className)} style={style} aria-label={ariaLabel} title={ariaLabel}
      disabled={disabled || !active} onClick={event => onReset?.(event)}>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
        <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" /><path d="M3 3v5h5" /></svg>
    </button>
  );
}

// ---------- Parameter row ----------
// Pure layout around already-built parts. compact (the 300px right column): label, field, keyframe and reset on the first
// line, the slider (and any extra control, e.g. a curve chip) on a second line. Not compact: one 5-column line, 96 | 88 | 1fr | 24 | 24.
// `modified` puts the white dot before the label (the dot's slot is kept when it is off so labels stay aligned).
export function ParamRow({ label, modified = false, field, slider, extra, keyframe, reset, compact = true, className, style }) {
  const name = <span className={cx('ctl-pl', modified && 'is-modified')}><i className="ctl-dot" aria-hidden="true" />{label}</span>;
  const main = slider || extra ? <div className="ctl-pr-main">{slider}{extra}</div> : null;
  if (compact) {
    return (
      <div className={cx('ctl-kit ctl-pc', modified && 'is-modified', className)} style={style} data-layout="compact">
        <div className="ctl-pch">{name}<span className="ctl-pc-field">{field}</span><span className="ctl-pc-kf">{keyframe}</span><span className="ctl-pc-rs">{reset}</span></div>
        {main}
      </div>
    );
  }
  return (
    <div className={cx('ctl-kit ctl-pr', modified && 'is-modified', !field && 'is-fieldless', className)} style={style} data-layout="row">
      {name}{field && <span className="ctl-pr-field">{field}</span>}{main}<span className="ctl-pr-kf">{keyframe}</span><span className="ctl-pr-rs">{reset}</span>
    </div>
  );
}

// Small inline curve (compact param rows, preset lists): the easing curve over a dashed linear reference.
export function CurveThumb({ values, width = 56, height = 28, padding, active, dashed, reference = true, className, style }) {
  const pad = padding ?? Math.max(2, Math.round(height * 0.2));
  return (
    <svg className={cx('ctl-kit ctl-ct', active && 'is-active', dashed && 'is-dashed', className)} style={style} width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true" focusable="false">
      {reference && <path className="ctl-ct-ref" d={`M${pad} ${height - pad} L${width - pad} ${pad}`} />}
      <path className="ctl-ct-line" d={bezierPath(values, { width, height, padding: pad })} />
    </svg>
  );
}

// ---------- Curve editor ----------
const EDIT_LEFT = 44, EDIT_TOP = 28, EDIT_RIGHT = 36, EDIT_BOTTOM = 64;   // room for the axis numbers and titles around the plot
const FIELD_NAMES = ['x1', 'y1', 'x2', 'y2'];
const LINEAR = [0, 0, 1, 1];
const fixed2 = n => n.toFixed(2);

// Vertical range of the plot. Without overshoot it is the unit square; with it the plot shows at least -0.5..1.5 and widens in
// quarters (never past -1..2) to hold both control points and the curve. The plot keeps its pixel height either way.
function plotRange(values, open) {
  if (!open) return { lo: 0, hi: 1 };
  const ys = [values[1], values[3], ...sampleBezier(values, 24)];
  return { lo: Math.max(-1, Math.min(-0.5, Math.floor((Math.min(...ys) - 0.1) * 4) / 4)), hi: Math.min(2, Math.max(1.5, Math.ceil((Math.max(...ys) + 0.1) * 4) / 4)) };
}

// Cubic-bezier easing editor, fully controlled by `values` ([x1, y1, x2, y2]). Two control points drag on the SVG (Shift fine,
// Ctrl/Cmd snaps to 0.05, Escape cancels; `snap` = true or an increment snaps always) and move with the arrow keys (0.01, Shift 0.1,
// Alt 0.001); the four number fields, the preset list (selected when the values match one, else a dashed "custom" row) and the
// motion-preview dots stay in sync. A curve that already leaves 0..1 opens the overshoot range by itself. labels {time, progress,
// locked, overshoot, preview, apply} and presetLabels {id: text, custom: text} carry every visible string; progressAtTime is the
// playhead's 0..1 position in the move, drawn as a marker with its progress. A labels.apply button calls onCommit(values).
export function CurveEditor({ values, onChange, onCommit, presets = BEZIER_PRESETS, presetLabels, overshoot = false, snap, size = 300, labels = {}, previewDots = true, progressAtTime, ariaLabel, className, style }) {
  const v = LINEAR.map((fallback, i) => (finite(values?.[i]) ? values[i] : fallback));
  const open = overshoot || v[1] < 0 || v[1] > 1 || v[3] < 0 || v[3] > 1;
  const [lock, setLock] = useState(null), [sel, setSel] = useState(null), svg = useRef(null);
  const range = lock?.range ?? plotRange(v, open), rise = range.hi - range.lo;
  const W = size + EDIT_LEFT + EDIT_RIGHT, H = size + EDIT_TOP + EDIT_BOTTOM;
  const X = x => Number((EDIT_LEFT + x * size).toFixed(2)), Y = y => Number((EDIT_TOP + ((range.hi - y) / rise) * size).toFixed(2));
  const grid = typeof snap === 'number' && snap > 0 ? snap : snap ? 0.05 : 0;
  const matched = matchBezierPreset(v, 0.005, presets);
  const emit = (next, final) => { onChange?.(next); if (final) onCommit?.(next); };
  const dragFor = which => ({
    onStart: event => {
      const box = svg.current.getBoundingClientRect(), at = which === 1 ? 0 : 2, locked = { range: plotRange(v, open), open };
      setLock(locked);   // the plot keeps its scale for the whole drag, so the handle never runs away from the pointer
      setSel(which);
      event.currentTarget.focus?.({ preventScroll: true });
      return { which, at, x: event.clientX, y: event.clientY, from: [v[at], v[at + 1]], origin: v, last: v, fine: event.shiftKey, sx: box.width / W || 1, sy: box.height / H || 1, ...locked };
    },
    onMove: (event, d) => {
      const fine = event.shiftKey;
      if (fine !== d.fine) { d.x = event.clientX; d.y = event.clientY; d.from = [d.last[d.at], d.last[d.at + 1]]; d.fine = fine; }
      const k = fine ? 0.1 : 1, x = d.from[0] + ((event.clientX - d.x) / (d.sx * size)) * k;
      const y = d.from[1] - ((event.clientY - d.y) / (d.sy * size)) * (d.range.hi - d.range.lo) * k;
      const next = moveBezierHandle(d.last, d.which, x, clamp(y, d.range.lo, d.range.hi), { snap: grid || (event.ctrlKey || event.metaKey ? 0.05 : undefined), overshoot: d.open });
      if (next.some((n, i) => n !== d.last[i])) { d.last = next; emit(next, false); }
    },
    onEnd: (event, cancelled, d) => {
      setLock(null);
      const changed = d.last.some((n, i) => n !== d.origin[i]);
      if (cancelled) { if (changed) emit(d.origin, false); }
      else if (changed) onCommit?.(d.last);
    },
  });
  const drags = [useDrag(dragFor(1)), useDrag(dragFor(2))];
  const onHandleKey = which => event => {
    const dir = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] }[event.key];
    if (!dir) return;
    event.preventDefault();
    const at = which === 1 ? 0 : 2, amount = event.shiftKey ? 0.1 : event.altKey ? 0.001 : 0.01;
    const next = moveBezierHandle(v, which, v[at] + dir[0] * amount, v[at + 1] + dir[1] * amount, { overshoot: open });
    if (next.some((n, i) => n !== v[i])) emit(next, true);
  };
  const withField = (index, n) => normalizeBezier(v.map((old, i) => (i === index ? n : old)), { overshoot: open });
  const t = finite(progressAtTime) ? clamp(progressAtTime, 0, 1) : null, progressNow = t === null ? null : bezierAt(v, t);
  const levels = [];
  for (let y = Math.ceil(range.lo * 4) / 4; y <= range.hi + 1e-9; y += 0.25) levels.push(Number(y.toFixed(2)));
  const dragging = drags[0].active ? 1 : drags[1].active ? 2 : 0;
  const steps = sampleBezier(v, 10), floor = Math.min(0, ...steps), ceil = Math.max(1, ...steps);
  const label = (text, props) => text ? <text className="ctl-ce-t" {...props}>{text}</text> : null;
  return (
    <div className={cx('ctl-kit ctl-ce', className)} style={style} role="group" aria-label={ariaLabel}>
      <div className="ctl-ce-presets">
        {presets.map(preset => {
          const on = matched === preset.id;
          return (
            <button key={preset.id} type="button" className={cx('ctl-btn ctl-pst', on && 'is-on')} aria-pressed={on} onClick={() => emit(preset.values.slice(), true)}>
              <CurveThumb values={preset.values} width={40} height={28} padding={4} reference={false} active={on} /><span>{presetLabels?.[preset.id] ?? preset.id}</span>
            </button>
          );
        })}
        {matched === null && <div className="ctl-pst is-on is-custom" aria-current="true"><CurveThumb values={v} width={40} height={28} padding={4} reference={false} dashed active /><span>{presetLabels?.custom ?? 'custom'}</span></div>}
      </div>
      <div className="ctl-ce-plot">
        <svg ref={svg} className="ctl-ce-svg" width={W} height={H} viewBox={`0 0 ${W} ${H}`} focusable="false">
          <rect className="ctl-ce-bg" x={EDIT_LEFT} y={EDIT_TOP} width={size} height={size} />
          {[0.25, 0.5, 0.75].map(g => <path key={`v${g}`} className="ctl-ce-grid" d={`M${X(g)} ${EDIT_TOP}V${EDIT_TOP + size}`} />)}
          {levels.filter(y => y > range.lo && y < range.hi).map(y => <path key={`h${y}`} className="ctl-ce-grid" d={`M${EDIT_LEFT} ${Y(y)}H${EDIT_LEFT + size}`} />)}
          {open && <rect className="ctl-ce-unit" x={X(0)} y={Y(1)} width={size} height={Y(0) - Y(1)} />}
          <path className="ctl-ce-ref" d={`M${X(0)} ${Y(0)}L${X(1)} ${Y(1)}`} />
          <path className="ctl-ce-tan" d={`M${X(0)} ${Y(0)}L${X(v[0])} ${Y(v[1])}M${X(1)} ${Y(1)}L${X(v[2])} ${Y(v[3])}`} />
          <g transform={`translate(${EDIT_LEFT} ${EDIT_TOP})`}><path className="ctl-ce-curve" d={bezierPath(v, { width: size, height: size, padding: 0, yMin: range.lo, yMax: range.hi })} /></g>
          {t !== null && <>
            <path className="ctl-ce-time" d={`M${X(t)} ${EDIT_TOP}V${EDIT_TOP + size}M${EDIT_LEFT} ${Y(progressNow)}H${EDIT_LEFT + size}`} />
            <circle className="ctl-ce-mark" cx={X(t)} cy={Y(progressNow)} r={4} />
            <text className="ctl-ce-t is-hot" x={X(t)} y={EDIT_TOP + size + 16} textAnchor="middle">{fixed2(t)}</text>
            <text className="ctl-ce-t is-hot" x={EDIT_LEFT - 8} y={Y(progressNow) + 4} textAnchor="end">{fixed2(progressNow)}</text>
          </>}
          <rect className="ctl-ce-end" x={X(0) - 4} y={Y(0) - 4} width={8} height={8} />
          <rect className="ctl-ce-end" x={X(1) - 4} y={Y(1) - 4} width={8} height={8} />
          {levels.filter(y => Number.isInteger(y * 2) && (t === null || Math.abs(Y(y) - Y(progressNow)) >= 15)).map(y => <text key={`y${y}`} className="ctl-ce-t" x={EDIT_LEFT - 8} y={Y(y) + 4} textAnchor="end">{String(y)}</text>)}
          {[0, 0.5, 1].filter(x => t === null || Math.abs(X(x) - X(t)) >= 20).map(x => <text key={`x${x}`} className="ctl-ce-t" x={X(x)} y={EDIT_TOP + size + 16} textAnchor="middle">{String(x)}</text>)}
          {label(labels.time, { x: X(0.5), y: H - 6, textAnchor: 'middle' })}
          {label(labels.progress, { transform: `translate(10 ${EDIT_TOP + size / 2}) rotate(-90)`, textAnchor: 'middle' })}
          {label(labels.locked, { className: 'ctl-ce-t is-note', x: EDIT_LEFT + size - 2, y: 19, textAnchor: 'end' })}
          {open && label(labels.overshoot, { className: 'ctl-ce-t is-note', x: EDIT_LEFT + 4, y: 19 })}
          {[1, 2].map(which => {
            const at = which === 1 ? 0 : 2, hx = X(v[at]), hy = Y(v[at + 1]), on = sel === which, drag = drags[which - 1];
            return (
              <g key={which} role="slider" tabIndex={0} className={cx('ctl-ce-h', on && 'is-sel', drag.active && 'is-drag')} aria-label={`P${which}`} aria-orientation="horizontal"
                aria-valuemin={0} aria-valuemax={1} aria-valuenow={v[at]} aria-valuetext={`x ${formatNumber(v[at], { decimals: 'auto' })}, y ${formatNumber(v[at + 1], { decimals: 'auto' })}`}
                onKeyDown={onHandleKey(which)} onFocus={() => setSel(which)} onBlur={() => setSel(null)} {...drag.bind}>
                <circle className="ctl-ce-hit" cx={hx} cy={hy} r={14} />
                {on && <circle className="ctl-ce-ring" cx={hx} cy={hy} r={12} />}
                <circle className="ctl-ce-dot" cx={hx} cy={hy} r={on ? 7 : 6} />
              </g>
            );
          })}
          {dragging > 0 && (() => {
            const at = dragging === 1 ? 0 : 2, bx = clamp(X(v[at]) + 14, EDIT_LEFT, W - 96), by = clamp(Y(v[at + 1]) + 6, EDIT_TOP, EDIT_TOP + size - 20);
            return <g className="ctl-ce-read" pointerEvents="none"><rect x={bx} y={by} width={88} height={20} rx={4} /><text x={bx + 8} y={by + 14}>{fixed2(v[at])} , {fixed2(v[at + 1])}</text></g>;
          })()}
        </svg>
      </div>
      <div className="ctl-ce-side">
        <div className="ctl-ce-fields">
          {FIELD_NAMES.map((name, i) => (
            <NumberField key={name} label={name} ariaLabel={name} value={v[i]} min={i % 2 ? (open ? -1 : 0) : 0} max={i % 2 ? (open ? 2 : 1) : 1} step={0.01} decimals={2}
              modified={v[i] !== LINEAR[i]} onChange={n => emit(withField(i, n), false)} onCommit={n => onCommit?.(withField(i, n))} />
          ))}
        </div>
        {previewDots && (
          <div>
            {labels.preview && <span className="ctl-ce-cap">{labels.preview}</span>}
            <div className="ctl-dots" aria-hidden="true">{steps.map((p, i) => <i key={i} style={{ left: pct((p - floor) / (ceil - floor)) }} />)}</div>
          </div>
        )}
        <code className="ctl-ce-code">{formatBezier(v)}</code>
        {labels.apply && <button type="button" className="ctl-btn ctl-ce-apply" onClick={() => onCommit?.(v)}>{labels.apply}</button>}
      </div>
    </div>
  );
}
