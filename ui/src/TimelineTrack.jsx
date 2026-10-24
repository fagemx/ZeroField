import { useEffect, useRef, useState } from 'react';
import { useLocale } from './i18n/react.jsx';
import { t } from './i18n/index.js';
import { Icon } from './Icon.jsx';
import { FRAME, clock, cutPoints, nearest, signed } from './timelineModel.js';

const ROWS = ['rhythm', 'video', 'takes', 'dialogue'];
const stamp = seconds => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds) % 60).padStart(2, '0')}`;
// A label every few seconds, whatever the zoom, so the ruler never crowds.
const labelEvery = pps => pps >= 90 ? 1 : pps >= 45 ? 2 : pps >= 18 ? 5 : pps >= 9 ? 10 : 30;

// The bottom panel of the Timeline space: ruler, rhythm bars, the cut itself (video 1), other takes, and the script's dialogue.
// Dragging a clip edge asks the owner (onEdge) to trim; nothing here knows the trim rules.
export function TimelineTrack({clips, beat, selectedId, playhead, playing, zoom, onZoom, ripple, onRipple, snapOn, onSnap, writable, takeCount = 0, onTakes,
  exporting, exportDisabled, onExport, onScrub, onSelect, onEdge}) {
  useLocale();
  const scroller = useRef(null), canvas = useRef(null), drag = useRef(null), scrub = useRef(false);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const box = scroller.current;
    if (!box) return undefined;
    setWidth(box.clientWidth);
    if (typeof ResizeObserver === 'undefined') return undefined;
    const watch = new ResizeObserver(() => setWidth(box.clientWidth));
    watch.observe(box);
    return () => watch.disconnect();
  }, []);
  const total = clips.length ? clips[clips.length - 1].end : 0;
  const fit = width > 0 && total > 0 ? Math.max(8, (width - 40) / total) : 30;
  const pps = Math.min(240, fit * zoom);
  const selected = clips.find(clip => clip.id === selectedId) || null;
  // Keep what you are working on in view: the playhead while it plays, the selected clip when it changes.
  useEffect(() => {
    const box = scroller.current;
    if (!box || !playing) return;
    const x = playhead * pps;
    if (x < box.scrollLeft || x > box.scrollLeft + box.clientWidth - 48) box.scrollLeft = Math.max(0, x - 48);
  }, [playhead, playing, pps]);
  useEffect(() => {
    const box = scroller.current;
    if (!box || !selected) return;
    const left = selected.start * pps, right = selected.end * pps;
    if (left < box.scrollLeft) box.scrollLeft = Math.max(0, left - 24);
    else if (right > box.scrollLeft + box.clientWidth) box.scrollLeft = Math.min(left - 24, right - box.clientWidth + 24);
  }, [selected?.id]);  // eslint-disable-line react-hooks/exhaustive-deps

  const timeAt = event => Math.max(0, Math.min(total, (event.clientX - canvas.current.getBoundingClientRect().left) / pps));
  const startScrub = event => {
    if (event.button !== 0 || event.target.closest('.tl-edge')) return;
    scrub.current = true;
    try { event.currentTarget.setPointerCapture?.(event.pointerId); } catch { /* a synthetic pointer has nothing to capture */ }
    onScrub(timeAt(event), false);
  };
  const moveScrub = event => {if (scrub.current) onScrub(timeAt(event), false);};
  const endScrub = event => {if (scrub.current) {scrub.current = false; onScrub(timeAt(event), true);}};

  // Grabbing a clip edge. The move is measured from where the drag began, so a long drag can come back to where it started.
  const startEdge = (event, clip, edge) => {
    if (!writable || event.button !== 0) return;
    event.preventDefault(); event.stopPropagation();
    try { event.currentTarget.setPointerCapture?.(event.pointerId); } catch { /* a synthetic pointer has nothing to capture */ }
    drag.current = {index: clip.index, edge, x: event.clientX, base: clips, delta: 0};
    onSelect(clip.id, edge);
  };
  const edgeDelta = (event, state) => {
    let delta = (event.clientX - state.x) / pps;
    const clip = state.base[state.index], flipped = ripple === event.altKey;  // Alt flips ripple for this drag
    // A cut (an out edge, or any edge that rolls) lands on the playhead and the other cuts when snapping is on.
    const edgeAt = state.edge === 'out' ? clip.end : flipped ? clip.start : null;
    if (snapOn && edgeAt !== null) {
      const targets = [playhead, ...cutPoints(state.base).filter(point => Math.abs(point - clip.start) > 1e-6 && Math.abs(point - clip.end) > 1e-6)];
      const hit = nearest(targets, edgeAt + delta, 8 / pps);
      if (hit !== null) delta = hit - edgeAt;
    }
    return {delta, flipped};
  };
  const moveEdge = event => {
    const state = drag.current;
    if (!state) return;
    const {delta, flipped} = edgeDelta(event, state);
    state.delta = delta;
    onEdge({index: state.index, edge: state.edge, delta, base: state.base, ripple: !flipped, commit: false});
  };
  const endEdge = event => {
    const state = drag.current;
    if (!state) return;
    drag.current = null;
    const {delta, flipped} = edgeDelta(event, state);
    onEdge({index: state.index, edge: state.edge, delta, base: state.base, ripple: !flipped, commit: true});
  };
  const nudge = (event, clip, edge) => {
    const step = event.key === 'ArrowLeft' ? -1 : event.key === 'ArrowRight' ? 1 : 0;
    if (!step || !writable) return;
    event.preventDefault();
    onEdge({index: clip.index, edge, delta: step * FRAME * (event.shiftKey ? 10 : 1), base: clips, ripple: ripple !== event.altKey, commit: true});
  };

  const marks = [];
  for (let at = 0, every = labelEvery(pps); at <= total + every; at += every) marks.push(at);
  const dialogue = clips.flatMap(clip => {
    let cursor = clip.start;
    return clip.dialogue.flatMap((line, at) => {
      const room = clip.end - cursor;
      if (room <= 1e-6) return [];
      const length = Math.min(Number(line.estimatedSeconds) > 0 ? Number(line.estimatedSeconds) : 1, room), block = {id: `${clip.id}-${at}`, clip, line, start: cursor, length};
      cursor += length;
      return [block];
    });
  });
  const x = seconds => seconds * pps;
  return <section className="tl-track" aria-label={t('timeline.trackTitle')}>
    <header className="tl-track-head">
      <h2>{t('timeline.trackTitle')}</h2>
      <span className="tl-tool is-on" aria-hidden="true"><Icon name="cursor" size={14}/>{t('timeline.select')}</span>
      <button type="button" className="tl-tool" aria-pressed={ripple} aria-keyshortcuts="R" onClick={onRipple} title={t('timeline.rippleHelp')}><Icon name="ripple" size={14}/>{t('timeline.ripple')}</button>
      <button type="button" className="tl-tool" aria-pressed={snapOn} onClick={onSnap} title={t('timeline.snapHelp')}><Icon name="magnet" size={14}/>{t('timeline.snap')}</button>
      <span className="spacer"/>
      <label className="tl-zoom"><span>{t('timeline.zoom')}</span>
        <input type="range" min="1" max="8" step="0.1" value={zoom} onChange={event => onZoom(Number(event.target.value))} aria-label={t('timeline.zoom')}/></label>
      <button type="button" className="primary tl-export" disabled={exportDisabled || exporting} onClick={onExport}><Icon name="download" size={14}/>{exporting ? t('story.working') : t('timeline.export')}</button>
    </header>
    <div className="tl-body">
      <div className="tl-labels" aria-hidden="true">
        <div className="tl-ruler-label"/>
        {ROWS.map(row => <div key={row} className={'tl-label tl-label-' + row}>{t('timeline.row_' + row)}</div>)}
      </div>
      <div className="tl-scroll" ref={scroller}>
        {clips.length === 0 ? <p className="tl-empty">{t('timeline.empty')}</p>
          : <div className="tl-canvas" ref={canvas} style={{width: Math.max(width, x(total) + 48)}}>
            <div className="tl-ruler" onPointerDown={startScrub} onPointerMove={moveScrub} onPointerUp={endScrub} onPointerCancel={endScrub}
              style={{backgroundImage: `repeating-linear-gradient(90deg, var(--line-2) 0 1px, transparent 1px ${pps}px)`}}>
              {marks.map(at => <span key={at} style={{left: x(at)}}>{stamp(at)}</span>)}</div>
            <div className="tl-row tl-rhythm" onPointerDown={startScrub} onPointerMove={moveScrub} onPointerUp={endScrub} onPointerCancel={endScrub}>
              {clips.map((clip, at) => {
                const item = beat.items[at];
                return <i key={clip.id} className={'tl-bar' + (clip.id === selectedId ? ' is-now' : '') + (clip.kind === 'take' ? '' : ' is-ghost') + (item.long ? ' is-long' : '')}
                  style={{left: x(clip.start) + 1, width: Math.max(2, x(clip.length) - 2), height: Math.max(4, 28 * item.ratio) + (item.long ? 0 : 0)}}/>;
              })}
              {clips.map((clip, at) => beat.items[at].long && <span key={clip.id} className="tl-hint" style={{left: x(clip.start) + 6}}>{t('timeline.long', {shot: clip.label, change: signed(beat.items[at].trimBy)})}</span>)}
            </div>
            <div className="tl-row tl-video" role="list" aria-label={t('timeline.row_video')}>
              {clips.map(clip => {
                const now = clip.id === selectedId, grab = writable && clip.trimmable;
                return <div key={clip.id} role="listitem" tabIndex={0} className={'tl-clip is-' + clip.kind + (now ? ' is-now' : '') + (clip.trimmed ? ' is-trimmed' : '')}
                  aria-current={now ? 'true' : undefined} aria-label={`${clip.label} ${clock(clip.length)}`} style={{left: x(clip.start) + 1, width: Math.max(6, x(clip.length) - 2)}}
                  onPointerDown={startScrub} onPointerMove={moveScrub} onPointerUp={endScrub} onPointerCancel={endScrub}
                  onKeyDown={event => {if ((event.key === 'Enter' || event.key === ' ') && event.target === event.currentTarget) {event.preventDefault(); onScrub(clip.start, true);}}}>
                  <span className="tl-film" style={clip.still && clip.kind !== 'plan' ? {backgroundImage: `url("${clip.still}")`} : undefined}/>
                  <span className="tl-clip-label"><i>{clip.label}</i><span>{clip.title}</span></span>
                  {clip.kind === 'previs' && <b className="tl-tag">{t('timeline.previsTag')}</b>}
                  {clip.kind === 'plan' && <b className="tl-tag">{t('timeline.planTag')}</b>}
                  {clip.trimmed && <b className="tl-tag is-trim">{signed(clip.length - clip.source)}</b>}
                  {grab && ['in', 'out'].map(edge => <span key={edge} className={'tl-edge tl-edge-' + edge} role="slider" tabIndex={now ? 0 : -1}
                    aria-label={t('timeline.edge_' + edge, {shot: clip.label})} aria-valuemin={0} aria-valuemax={clip.source} aria-valuenow={clip[edge]} aria-valuetext={clock(clip[edge])}
                    onPointerDown={event => startEdge(event, clip, edge)} onPointerMove={moveEdge} onPointerUp={endEdge} onPointerCancel={endEdge}
                    onKeyDown={event => nudge(event, clip, edge)}/>)}
                </div>;
              })}
            </div>
            <div className="tl-row tl-takes">
              {selected && takeCount > 0 && <button type="button" className="tl-ghost" style={{left: x(selected.start) + 1, width: Math.max(96, x(selected.length) - 2)}} onClick={onTakes}>
                <span>{t('timeline.otherTakes', {count: takeCount})}</span></button>}
            </div>
            <div className="tl-row tl-dialogue">
              {dialogue.map(block => <span key={block.id} className={'tl-line' + (block.clip.id === selectedId ? ' is-now' : '')} title={`${block.line.speaker ? block.line.speaker + ': ' : ''}${block.line.line}`}
                style={{left: x(block.start) + 1, width: Math.max(4, x(block.length) - 2)}}>{block.line.speaker && <i>{block.line.speaker}</i>}{block.line.line}</span>)}
            </div>
            <div className="tl-playhead" style={{left: x(playhead)}} aria-hidden="true"><span>{clock(playhead)}</span></div>
          </div>}
      </div>
    </div>
  </section>;
}
