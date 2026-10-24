import { useRef, useState } from 'react';
import { useLocale } from '../i18n/react.jsx';
import { t as uiText } from '../i18n/index.js';
import { TimecodeField } from '../controls/Controls.jsx';
import { FPS } from './plan.js';
import { actingBeats, beatToFrame, frameToBeat, keyHandles, moveBeat, resizeBeat, retimeCameraKey } from './blocking.js';

// The 3D Stage's bottom track: the camera's keys (diamonds) and the actor's beats (blocks) on the shot's own frames, so what
// happens when is one picture. Drag a block to move it, its right edge to change how long it runs, a diamond to retime a key;
// arrow keys do the same one frame at a time (Shift ten). Beats never push each other: each stops at its neighbour.
// Walk in and shots with motion skills have beats; the built-in turn-and-reach has fixed timing, so it says so.
const t = (key, params) => uiText('previs.' + key, params);

export function BeatTrack({plan, frames, frame, writable, onEdit, onSeek}) {
  useLocale();
  const lanes = useRef(null), drag = useRef(null), [pick, setPick] = useState(null);
  const last = Math.max(1, frames - 1), at = f => (f / last * 100) + '%';
  const beats = actingBeats(plan), keys = keyHandles(plan);
  const begin = (event, target, apply) => {
    if (event.button !== 0) return;
    event.stopPropagation(); setPick(target);
    if (!writable) return;
    event.preventDefault();
    try { event.currentTarget.setPointerCapture?.(event.pointerId); } catch { /* a synthetic pointer has nothing to capture */ }
    drag.current = {id: event.pointerId, x: event.clientX, base: plan, perPixel: last / (lanes.current.getBoundingClientRect().width || 1), apply};
  };
  const move = event => {
    const d = drag.current;
    if (d && d.id === event.pointerId) onEdit(d.apply(d.base, (event.clientX - d.x) * d.perPixel));
  };
  const drop = event => {if (drag.current?.id === event.pointerId) drag.current = null;};
  const step = (event, edit) => {
    const direction = event.key === 'ArrowLeft' ? -1 : event.key === 'ArrowRight' ? 1 : 0;
    if (!direction || !writable) return;
    event.preventDefault(); event.stopPropagation(); edit(direction * (event.shiftKey ? 10 : 1));
  };
  const seek = event => {
    const box = lanes.current.getBoundingClientRect();
    onSeek(Math.round(Math.min(1, Math.max(0, (event.clientX - box.left) / (box.width || 1))) * last));
  };
  const chosen = pick?.row === 'beat' ? beats.find(beat => beat.index === pick.index) : null, key = pick?.row === 'key' ? keys[pick.index] : null;
  const skill = name => t('skill_' + name);

  return <section className="previs-beats" aria-label={t('beatsTitle')}>
    <header><b>{t('beatsTitle')}</b><span>{t('beatsHint')}</span></header>
    <div className="pb-grid">
      <div className="pb-labels" aria-hidden="true"><span>{t('rowCamera')}</span><span>{t('rowActing')}</span></div>
      <div className="pb-lanes" ref={lanes} onPointerDown={seek}>
        <div className="pb-lane pb-keys">
          {keys.map(item => {
            const frameAt = beatToFrame(plan, item.beat);
            return <span key={item.index} role="slider" tabIndex={0} className={'pb-key' + (pick?.row === 'key' && pick.index === item.index ? ' is-picked' : '')} style={{left: at(frameAt)}}
              aria-label={t('keyAria', {index: item.index + 1})} aria-valuemin={0} aria-valuemax={last} aria-valuenow={Math.round(frameAt)} aria-valuetext={`${(frameAt / FPS).toFixed(2)} s`}
              onPointerDown={event => begin(event, {row: 'key', index: item.index}, (base, delta) => retimeCameraKey(base, item.index, item.beat + frameToBeat(base, delta)))}
              onPointerMove={move} onPointerUp={drop} onPointerCancel={drop} onFocus={() => setPick({row: 'key', index: item.index})}
              onKeyDown={event => step(event, direction => onEdit(retimeCameraKey(plan, item.index, item.beat + frameToBeat(plan, direction))))}><i aria-hidden="true">K{item.index + 1}</i></span>;
          })}
        </div>
        <div className="pb-lane pb-acts">
          {beats.length === 0 ? <p className="pb-note">{t('beatsBuiltin', {action: t('action_' + plan.action)})}</p>
            : beats.map(beat => <div key={beat.index} role="slider" tabIndex={0} className={'pb-beat' + (beat.derived ? ' is-derived' : '') + (pick?.row === 'beat' && pick.index === beat.index ? ' is-picked' : '')}
              style={{left: at(beat.start), width: `calc(${beat.frames / last * 100}% - 2px)`}} aria-label={skill(beat.skill)} aria-valuemin={0} aria-valuemax={last} aria-valuenow={beat.start}
              aria-valuetext={`${(beat.start / FPS).toFixed(2)} – ${(beat.end / FPS).toFixed(2)} s`}
              onPointerDown={event => begin(event, {row: 'beat', index: beat.index}, (base, delta) => moveBeat(base, beat.index, beat.start + delta))}
              onPointerMove={move} onPointerUp={drop} onPointerCancel={drop} onFocus={() => setPick({row: 'beat', index: beat.index})}
              onKeyDown={event => step(event, direction => onEdit(moveBeat(plan, beat.index, beat.start + direction)))}>
              <span>{skill(beat.skill)}</span>
              {beat.resizable && <i className="pb-edge" role="slider" tabIndex={0} aria-label={t('beatEdgeAria', {skill: skill(beat.skill)})} aria-valuemin={beat.start} aria-valuemax={last} aria-valuenow={beat.end}
                onPointerDown={event => begin(event, {row: 'beat', index: beat.index}, (base, delta) => resizeBeat(base, beat.index, beat.end + delta))}
                onPointerMove={move} onPointerUp={drop} onPointerCancel={drop}
                onKeyDown={event => step(event, direction => onEdit(resizeBeat(plan, beat.index, beat.end + direction)))}/>}
            </div>)}
        </div>
        <i className="pb-head" style={{left: at(frame)}} aria-hidden="true"/>
      </div>
    </div>
    {(chosen || key) && <footer className="pb-times">
      {chosen && <>
        <label><span>{t('beatStarts')}</span><TimecodeField frames={chosen.start} fps={FPS} min={0} max={last} disabled={!writable} ariaLabel={t('beatStarts')}
          onChange={value => onEdit(moveBeat(plan, chosen.index, value))}/></label>
        <label><span>{t('beatEnds')}</span><TimecodeField frames={chosen.end} fps={FPS} min={0} max={last} disabled={!writable || !chosen.resizable} ariaLabel={t('beatEnds')}
          onChange={value => onEdit(resizeBeat(plan, chosen.index, value))}/></label></>}
      {key && <label><span>{t('keyAt', {index: key.index + 1})}</span><TimecodeField frames={Math.round(beatToFrame(plan, key.beat))} fps={FPS} min={0} max={last} disabled={!writable}
        ariaLabel={t('keyAt', {index: key.index + 1})} onChange={value => onEdit(retimeCameraKey(plan, key.index, frameToBeat(plan, value)))}/></label>}
    </footer>}
  </section>;
}
