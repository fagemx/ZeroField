import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocale } from './i18n/react.jsx';
import { t } from './i18n/index.js';
import { storyList, storyRequest, waitStoryTask } from './storyModel.js';
import { orderedShots } from './StudioShell.jsx';
import { Icon } from './Icon.jsx';
import { FRAME, buildClips, changedTrims, clipAt, clock, dragEdge, fileTime, rhythm, setLength, setPoint, signed, slip, totalSeconds, wholeTake } from './timelineModel.js';
import { TimelineTrack } from './TimelineTrack.jsx';
import { TimelineInspector } from './TimelineInspector.jsx';
import './timeline.css';

// SPEC_15 Timeline, the third way to think about the episode: time. Left, the shots' rhythm (bar length is seconds); middle, the
// cut under the playhead as two frames side by side; right, the clip in hand; below, the timeline itself. The film is the cut
// in this order with each take trimmed as shown, so trims are saved on the shot and the export reads them back.
const isField = target => Boolean(target?.closest?.('input,textarea,select,button,[contenteditable=true],[role="slider"],.modal-scrim'));

// A setting only this browser needs to remember (ripple, snapping): unreadable storage just means the default.
function useSetting(key, fallback) {
  const [value, setValue] = useState(() => {
    try {const raw = window.localStorage.getItem('zf.timeline.' + key); return raw === null ? fallback : JSON.parse(raw);} catch {return fallback;}
  });
  const set = useCallback(next => {setValue(next); try {window.localStorage.setItem('zf.timeline.' + key, JSON.stringify(next));} catch { /* private window */ }}, [key]);
  return [value, set];
}

// Seconds of every file in the cut, read once from its metadata, three at a time. A take is trimmed against its real length;
// until its file answers, a clip keeps its planned length and cannot be trimmed.
function useDurations(urls) {
  const [seconds, setSeconds] = useState({});
  const seen = useRef(new Set()), queue = useRef([]), running = useRef(0), mounted = useRef(true), pump = useRef(null);
  pump.current = () => {
    while (mounted.current && running.current < 3 && queue.current.length) {
      const url = queue.current.shift(), video = document.createElement('video');
      running.current += 1;
      const done = value => {
        running.current -= 1; video.onloadedmetadata = video.onerror = null; video.removeAttribute('src'); video.load();
        if (mounted.current && Number.isFinite(value) && value > 0) setSeconds(current => ({...current, [url]: value}));
        pump.current();
      };
      video.preload = 'metadata'; video.onloadedmetadata = () => done(video.duration); video.onerror = () => done(0); video.src = url;
    }
  };
  useEffect(() => {mounted.current = true; return () => {mounted.current = false;};}, []);
  const key = urls.join('|');
  useEffect(() => {
    for (const url of urls) if (!seen.current.has(url)) {seen.current.add(url); queue.current.push(url);}
    pump.current();
  }, [key]);  // eslint-disable-line react-hooks/exhaustive-deps
  return seconds;
}

// One side of the cut: the last frame kept of the shot before, or the first frame kept of the shot after.
function Frame({clip, at, label}) {
  const video = useRef(null);
  useEffect(() => {
    const element = video.current;
    if (!element || !clip?.url) return undefined;
    const seek = () => {try {element.currentTime = at;} catch { /* metadata is not ready yet */ }};
    if (element.readyState >= 1) seek(); else element.addEventListener('loadedmetadata', seek, {once: true});
    return () => element.removeEventListener('loadedmetadata', seek);
  }, [clip?.url, at]);
  return <div className={'tl-frame' + (clip ? '' : ' is-empty')}>
    {!clip ? <span className="tl-slate">{t('timeline.noNeighbour')}</span>
      : clip.url ? <video ref={video} src={clip.url} muted playsInline preload="auto" aria-label={label}/>
        : clip.still ? <img src={clip.still} alt=""/> : <span className="tl-slate"><b>{clip.label}</b>{t('timeline.noPicture')}</span>}
    {clip && <span className="tl-frame-tag">{label}</span>}
  </div>;
}
const Moved = ({from, to}) => Math.abs(to - from) < 1e-6 ? <>{clock(to)}</> : <>{clock(from)} → <b>{clock(to)}</b> {signed(to - from)}</>;

export function Timeline({epId, shots = [], writable, focusRid, onFocus, onChanged}) {
  useLocale();
  const cut = useMemo(() => orderedShots(shots), [shots]);
  const urls = useMemo(() => cut.map(shot => shot.selectedVideoUrl || shot.previsVideoUrl).filter(Boolean), [cut]);
  const measured = useDurations(urls);
  const [draft, setDraft] = useState({});
  const saved = useMemo(() => buildClips(cut, {measured}), [cut, measured]);
  const clips = useMemo(() => Object.keys(draft).length ? buildClips(cut, {measured, trims: draft}) : saved, [cut, measured, draft, saved]);
  const beat = useMemo(() => rhythm(clips), [clips]);
  const [selectedId, setSelectedId] = useState(null), [side, setSide] = useState('out');
  const [playhead, setPlayheadState] = useState(0), [playing, setPlaying] = useState(false);
  const [ripple, setRipple] = useSetting('ripple', true), [snapOn, setSnapOn] = useSetting('snap', true), [zoom, setZoom] = useState(1);
  const [error, setError] = useState(''), [saving, setSaving] = useState(false), [exporting, setExporting] = useState(false), [film, setFilm] = useState('');
  const [takes, setTakes] = useState({shot: '', items: []});
  const clipsRef = useRef(clips), playheadRef = useRef(0), player = useRef(null), dragging = useRef(false), alive = useRef(true), pending = useRef({}), act = useRef({});
  clipsRef.current = clips;
  const setPlayhead = useCallback(time => {playheadRef.current = time; setPlayheadState(time);}, []);
  const selected = clips.find(clip => clip.id === selectedId) || clips[0] || null;
  const total = totalSeconds(clips);

  useEffect(() => {alive.current = true; return () => {alive.current = false;};}, []);
  useEffect(() => {setSelectedId(null); setPlayhead(0); setPlaying(false); setDraft({}); pending.current = {}; setFilm(''); setError('');}, [epId, setPlayhead]);
  // New shots from the server replace what was only shown while the trims were being saved.
  useEffect(() => {
    if (dragging.current) return;
    pending.current = {}; setDraft({});
  }, [shots]);
  // The shell's focus decides the clip, and the playhead goes to it unless it is already inside.
  const hasClips = clips.length > 0;
  useEffect(() => {
    const clip = clipsRef.current.find(item => item.rowId === focusRid);
    if (!clip) return;
    setSelectedId(clip.id);
    const at = playheadRef.current;
    if (at < clip.start - 1e-6 || at > clip.end + 1e-6) setPlayhead(clip.start);
  }, [focusRid, hasClips, setPlayhead]);

  const focusClip = clip => {if (clip && clip.rowId !== focusRid) onFocus?.(clip.rowId);};
  const scrub = (time, final) => {
    setPlaying(false); setPlayhead(Math.max(0, Math.min(total, time)));
    const clip = clipAt(clipsRef.current, time);
    if (!clip) return;
    setSelectedId(clip.id); setSide('out');
    if (final) focusClip(clip);
  };
  const select = (id, edge = 'out') => {setSelectedId(id); setSide(edge); focusClip(clips.find(clip => clip.id === id));};

  // Saving. A drag only draws a draft; the server hears about it when the drag ends. Both clips of a roll are saved together.
  const rowOf = useMemo(() => Object.fromEntries(saved.map(clip => [clip.rowId, clip.shotId])), [saved]);
  const save = async trims => {
    const changes = changedTrims(saved, trims), ids = Object.keys(changes);
    dragging.current = false;
    if (!ids.length) {pending.current = {}; setDraft({}); return;}
    setSaving(true); setError('');
    try {
      await Promise.all(ids.map(rowId => storyRequest(`/shots/${rowOf[rowId]}/trim`, 'PUT', changes[rowId])));
      Object.assign(pending.current, changes);
      onChanged?.();
    } catch (failure) {
      if (alive.current) {setError(failure.message); pending.current = {}; setDraft({});}
    } finally {if (alive.current) setSaving(false);}
  };
  const edit = (result, commit) => {
    if (!result) return null;
    dragging.current = !commit;
    setDraft({...pending.current, ...result.trims});
    if (commit) save({...pending.current, ...result.trims});
    return result;
  };
  // flip: Alt held on a control inverts ripple for this one change.
  const fromTrack = ({index, edge, delta, base, ripple: rippling, commit}) => edit(dragEdge(base, index, edge, delta, {ripple: rippling}), commit);
  const trimTo = (edge, target, commit = true, flip = false) => selected ? edit(setPoint(clips, selected.index, edge, target, {ripple: ripple !== flip}), commit) : null;
  const slideTo = (target, commit = true) => selected ? edit(slip(clips, selected.index, target - selected.in), commit) : null;
  const lengthTo = seconds => selected ? edit(setLength(clips, selected.index, seconds, {ripple}), true) : null;
  const moveBy = (edge, delta) => selected ? edit(dragEdge(clips, selected.index, edge, delta, {ripple}), true) : null;
  const resetTrim = () => selected ? edit({delta: 0, trims: {[selected.rowId]: wholeTake()}}, true) : null;

  // Other takes of the selected shot: the same list the Shot Stage offers, one tap to use.
  useEffect(() => {
    if (!selected?.shotId || selected.kind === 'plan') {setTakes({shot: '', items: []}); return undefined;}
    let live = true;
    storyList(`/shots/${selected.shotId}/videos`).then(items => {if (live) setTakes({shot: selected.shotId, items});}).catch(() => {if (live) setTakes({shot: '', items: []});});
    return () => {live = false;};
  }, [selected?.shotId, selected?.kind, selected?.url]);  // eslint-disable-line react-hooks/exhaustive-deps
  const otherTakes = takes.shot === selected?.shotId ? takes.items.filter(take => !take.selected) : [];
  const useTake = async take => {
    setError('');
    try {await storyRequest(`/shots/${selected.shotId}/selected-video`, 'PUT', {videoId: take.videoId}); onChanged?.();} catch (failure) {setError(failure.message);}
  };

  // Playing the cut: one video follows the playhead through each clip's trimmed range; a clip with no picture holds on a clock.
  useEffect(() => {
    const video = player.current;
    if (!playing) {video?.pause(); return undefined;}
    let frame = 0, last = performance.now(), active = null, entered = last;
    const stop = at => {setPlaying(false); setPlayhead(at);};
    const tick = now => {
      const list = clipsRef.current;
      let time = playheadRef.current;
      const clip = clipAt(list, time);
      if (!clip) {stop(0); return;}
      if (active !== clip.id) {
        active = clip.id; entered = now; setSelectedId(clip.id); setSide('out');
        if (video && clip.url) {
          const start = () => {video.currentTime = fileTime(clip, playheadRef.current); video.play().catch(() => {});};
          if (video.dataset.url === clip.url) start(); else {video.dataset.url = clip.url; video.onloadedmetadata = start; video.src = clip.url;}
        }
      } else if (clip.url && video && !video.error && !(video.paused && !video.ended && now - entered > 2500)) {
        // The video keeps the time. A file that ends exactly where the cut does has stopped by now; one that is still loading holds the
        // playhead, but not for ever: a take that will not play lets the clock carry the cut on.
        if (video.ended) time = clip.end;
        else if (video.readyState >= 2 && !video.paused) time = clip.start + (video.currentTime - clip.in);
      } else time += (now - last) / 1000;
      last = now;
      if (time >= clip.end - 1e-3) {
        const next = list[clip.index + 1];
        if (!next) {stop(clip.end); return;}
        time = next.start;
      }
      setPlayhead(time);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, setPlayhead]);
  const toggle = () => {
    if (playing) {setPlaying(false); return;}
    if (!clips.length) return;
    if (playheadRef.current >= total - 1e-3) setPlayhead(0);
    setPlaying(true);
  };
  const hop = step => {
    if (clips.length < 2) return;
    const here = selected ? (side === 'in' ? selected.index - 1 : selected.index) : 0;
    const target = clips[Math.min(clips.length - 2, Math.max(0, here + step))];
    setPlaying(false); setSelectedId(target.id); setSide('out'); setPlayhead(Math.max(target.start, target.end - FRAME)); focusClip(target);
  };
  act.current = {toggle, ripple: () => setRipple(!ripple), step: (frames, final = true) => scrub(playheadRef.current + frames * FRAME, final)};
  useEffect(() => {
    const keys = event => {
      if (event.ctrlKey || event.metaKey || event.altKey || event.defaultPrevented || isField(event.target)) return;
      if (event.key === ' ') {event.preventDefault(); act.current.toggle();}
      else if (event.key.toLowerCase() === 'r') {event.preventDefault(); act.current.ripple();}
      else if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {event.preventDefault(); act.current.step((event.key === 'ArrowLeft' ? -1 : 1) * (event.shiftKey ? 24 : 1));}
    };
    window.addEventListener('keydown', keys);
    return () => window.removeEventListener('keydown', keys);
  }, []);

  const exportFilm = async () => {
    setExporting(true); setError('');
    try {
      const fill = clips.some(clip => clip.kind === 'previs');
      const result = await waitStoryTask(await storyRequest(`/episodes/${epId}/films`, 'POST', fill ? {fillPrevis: true} : {}));
      if (alive.current) setFilm(result.videoUrl);
    } catch (failure) {if (alive.current) setError(failure.message);}
    finally {if (alive.current) setExporting(false);}
  };
  const unfilmed = clips.filter(clip => clip.kind === 'plan').length;

  const cutAt = selected ? (side === 'in' ? selected.index - 1 : selected.index) : -1;
  const before = clips[cutAt] || null, after = clips[cutAt + 1] || null;
  const savedBefore = before && saved[before.index], savedAfter = after && saved[after.index];
  const change = total - totalSeconds(saved);
  const mark = (value) => value.toFixed(1);

  return <div className="studio-timeline">
    <aside className="tl-panel tl-list" aria-label={t('timeline.rhythm')}>
      <header><h2>{t('timeline.rhythm')}</h2><span>{t('timeline.rhythmHint')}</span></header>
      {clips.length === 0 ? <p className="tl-empty">{t('timeline.empty')}</p> : <ol>
        {clips.map((clip, at) => <li key={clip.id}><button type="button" aria-current={clip.id === selected?.id ? 'true' : undefined} onClick={() => {select(clip.id); setPlaying(false); setPlayhead(clip.start);}}>
          <b>{clip.label}</b><span className="tl-meter"><i className={clip.kind === 'take' ? '' : 'is-ghost'} style={{width: Math.max(4, beat.items[at].ratio * 100) + '%'}}/></span><em>{mark(clip.length)}</em></button></li>)}
      </ol>}
      <footer>{t('timeline.ghostLegend')}<br/>{t('timeline.totalAverage', {total: mark(beat.total), mean: mark(beat.mean)})}</footer>
    </aside>

    <section className="tl-panel tl-preview" aria-label={t('timeline.junction')}>
      <header><h2>{t('timeline.junction')}{before && after && <span> {before.label} → {after.label}</span>}</h2>
        <span className="tl-follow"><Icon name="check" size={13}/>{t('timeline.followPlayhead')}</span></header>
      <div className="tl-stage">
        <video ref={player} className={'tl-player' + (playing ? ' is-on' : '')} playsInline preload="auto" aria-label={t('timeline.player')}/>
        {!playing && <>
          <div className="tl-pair">
            <figure><Frame clip={before} at={before ? Math.max(before.in, before.out - FRAME) : 0} label={before ? t('timeline.outOf', {shot: before.label}) : ''}/>
              {before && <figcaption><Moved from={savedBefore.out} to={before.out}/></figcaption>}</figure>
            <figure><Frame clip={after} at={after ? after.in : 0} label={after ? t('timeline.inOf', {shot: after.label}) : ''}/>
              {after && <figcaption><Moved from={savedAfter.in} to={after.in}/> · {t(ripple ? 'timeline.rippleOn' : 'timeline.rollOn')}</figcaption>}</figure>
          </div>
          <p className="tl-film-line">{Math.abs(change) > 1e-6
            ? <>{t('timeline.filmChanged', {from: mark(totalSeconds(saved)), to: mark(total)})}{selected && ripple && selected.index < clips.length - 1 ? ' · ' + t('timeline.shotsShift', {count: clips.length - 1 - selected.index, change: signed(change)}) : ''}</>
            : t('timeline.filmTotal', {total: mark(total)})}</p>
        </>}
      </div>
      <footer>
        <button type="button" className="tl-play" aria-label={t(playing ? 'timeline.pause' : 'timeline.play')} aria-keyshortcuts="Space" onClick={toggle} disabled={!clips.length}><Icon name={playing ? 'pause' : 'play'} size={14}/></button>
        <span className="tl-clock">{clock(playhead)} / {clock(total)}</span>
        <span className="spacer"/>
        <button type="button" className="tl-hop" onClick={() => hop(-1)} disabled={clips.length < 2}><Icon name="skipPrev" size={14}/>{t('timeline.prevCut')}</button>
        <button type="button" className="tl-hop" onClick={() => hop(1)} disabled={clips.length < 2}>{t('timeline.nextCut')}<Icon name="skipNext" size={14}/></button>
      </footer>
      {(error || film || unfilmed > 0) && <p className={'tl-status' + (error ? ' is-error' : '')} role={error ? 'alert' : 'status'}>
        {error || (film ? <a href={film} download>{t('shell.downloadFilm')}</a> : t('timeline.unfilmed', {count: unfilmed}))}</p>}
    </section>

    <TimelineInspector clip={selected} saved={selected ? saved[selected.index] : null} ripple={ripple} onRipple={() => setRipple(!ripple)} writable={writable} saving={saving}
      onPoint={trimTo} onSlide={slideTo} onLength={lengthTo} onMove={moveBy} onReset={resetTrim} takes={otherTakes} onTake={useTake}
      hint={selected && beat.items[selected.index]?.long ? beat.items[selected.index] : null}/>

    <TimelineTrack clips={clips} beat={beat} selectedId={selected?.id} playhead={playhead} playing={playing} zoom={zoom} onZoom={setZoom}
      ripple={ripple} onRipple={() => setRipple(!ripple)} snapOn={snapOn} onSnap={() => setSnapOn(!snapOn)} writable={writable} takeCount={otherTakes.length}
      exporting={exporting} exportDisabled={!writable || !clips.some(clip => clip.kind !== 'plan')} onExport={exportFilm}
      onScrub={scrub} onSelect={select} onEdge={fromTrack}/>
  </div>;
}
