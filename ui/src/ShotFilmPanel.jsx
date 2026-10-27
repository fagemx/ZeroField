import { useEffect, useRef, useState } from 'react';
import { useLocale } from './i18n/react.jsx';
import { t } from './i18n/index.js';
import { api } from './api.js';
import { shotId as storyShotId, storyList, storyRequest, takeGrade } from './storyModel.js';
import { rowProposals } from './proposalModel.js';
import { adoptionBody, filmNeighbors, filmSegments, filmSummary, mergeTakes, newTakeCountOf, nextNewTake, shotStateOf, takeOnlyProposal } from './takeModel.js';
import { normalizeStatus } from './format.js';
import { ClipVideo, filmPlayback, filmTrial, useFilmTrial } from './StudioShell.jsx';
import { ShotProposals } from './ShotProposals.jsx';
import { Icon } from './Icon.jsx';
import { shotMonitor, useShotMonitor } from './composer/shotMonitor.js';
import { episodeId as defaultEpisodeId } from './storyModel.js';
import { filmSeams, seamPlaylist, staleTakeRefs } from './takeModel.js';
import { TakeRefsLine, focusShotPrompt } from './film/TakeRefsLine.jsx';
import { PlayModeToggle, SeamDetail, SeamDot, queueCutChecks, useEpisodeCuts } from './film/Seams.jsx';

// SPEC_19 R3: the current shot's right column, "this shot in the cut". What it shows (3.2): the derived state and a "…" menu, the
// previous / this / next shot with "Play around", the episode's progress bar, the Take list (✓ adopts: POST /shots/{id}/adoptions),
// the trim, the crew proposals, the notes, and the cast folded away at the bottom. There is no approve button: adopting is the ✓.
//
// Takes are the shot's candidates (GET /shots/{id}/videos) merged with its pending media proposals; a take with a proposal behind it is
// adopted through the proposal (1.2 K). First frames are listed when the column is switched to them, and their ✓ only picks the frame
// (1.2 J). Writes go through onWrite, which holds the sheet's guards (no open cell draft, one write at a time) and reloads the row
// afterwards; nothing here edits a cell itself (1.2 B). A reader sees no ✓ and no ↻ (A15).
//
// The Shot Stage has one player (composer/shotMonitor.js): a take row, the current thumbnail or "Play around" queue there, and the shot
// composer's top half plays it; while no composer is on the page this panel draws the player itself. One <video> at a time, each clip
// as trimmed (1.2 I). A take tried in the cut (R19) stands in for the adopted one in "Play around" and in the film window until
// Esc, another shot, or its adoption; it is screen state only.

const SHOWN = 6;  // takes listed before "All n takes": each row holds a paused first frame
const ASSET = /^\/projects\/api\/([a-z0-9-]+)\/assets\/(pa_[0-9a-f]{32})$/;
const tenth = value => (Math.round(Number(value) * 10) / 10).toFixed(1);
const EMPTY = {videos:[], images:null, grades:[], error:'', loading:true};

// The shot's video candidates and continuity grades, reloaded when the sheet changes (version); first frames only once asked for.
function useShotMedia(id, version, output) {
  const [state, setState] = useState({id:null, ...EMPTY});
  useEffect(() => {
    if (!id) return undefined;
    let alive = true;
    setState(old => old.id === id ? {...old, loading:true} : {id, ...EMPTY});
    Promise.all([storyList(`/shots/${id}/videos`), storyRequest(`/shots/${id}/grades?limit=100`).then(data => data.items || [], () => [])])
      .then(([videos, grades]) => {if (alive) setState(old => ({...old, id, videos, grades, error:'', loading:false}));},
        error => {if (alive) setState(old => ({...old, id, error:error.message, loading:false}));});
    return () => {alive = false;};
  }, [id, version]);
  useEffect(() => {
    if (!id || output !== 'frame') return undefined;
    let alive = true;
    storyList(`/shots/${id}/images`).then(images => {if (alive) setState(old => old.id === id ? {...old, images} : old);},
      error => {if (alive) setState(old => old.id === id ? {...old, error:error.message} : old);});
    return () => {alive = false;};
  }, [id, version, output]);
  return state.id === id ? state : {id, ...EMPTY};
}

// How closely each take follows the shot's previs camera, where the server has measured it (only shown when there is a score).
function useFidelity(previsUrl, urls) {
  const [scores, setScores] = useState({});
  const key = urls.join('|');
  useEffect(() => {
    const [, slug, previsId] = ASSET.exec(previsUrl || '') || [];
    if (!previsId) return undefined;
    let alive = true;
    for (const url of urls) {
      const takeId = ASSET.exec(url)?.[2];
      if (!takeId || takeId === previsId) continue;
      api.get(`/projects/api/${slug}/camera-fidelity/${previsId}/${takeId}`).then(result => {
        if (alive && result?.status === 'done' && Number.isFinite(result.score)) setScores(old => ({...old, [url]:result.score}));
      }, () => {});
    }
    return () => {alive = false;};
  }, [previsUrl, key]);  // eslint-disable-line react-hooks/exhaustive-deps
  return scores;
}

// First frames in the same order as takes (newest first), each with its imageId.
const framesOf = images => mergeTakes(images || [], [], {}).map(frame => ({...frame, imageId:frame.candidate?.imageId ?? null}));

export function ShotFilmPanel({slug, tabKey, rid, shot = null, shots = [], label, sceneTitle, status, proposals = [], version, inFlight = null,
  writable, disabled, canStatus = true, hasFrame = false, controlRef, onWrite, onStatus, onRetake, onPick, onTimeline,
  onApplyProposal, onDismissProposal, onShowStage, menu = {}, top = null, failure = null, notes = null, cast = null, history = null}) {
  useLocale();
  const id = shot?.shotId || storyShotId(slug, rid);
  const [output, setOutput] = useState('video'), [showAll, setShowAll] = useState(false);
  const {playing, measured, hosts} = useShotMonitor();
  const trial = useFilmTrial();
  const media = useShotMedia(id, version, output);
  const entries = rowProposals(proposals, rid, tabKey);
  const takes = mergeTakes(media.videos, entries, {status, adoption:shot?.adoption ?? null});
  const running = Boolean(inFlight?.has(rid));
  const current = {...(shot || {shotId:id, rowId:rid, shotIndex:label, tabKey}), reviewStatus:status, takes, inFlight:running};
  const film = shots.some(item => item.shotId === id)
    ? shots.map(item => item.shotId === id ? current : {...item, inFlight:Boolean(inFlight?.has(item.rowId))}) : [current];
  const tried = trial?.shotId === id ? trial : null;
  const fidelity = useFidelity(shot?.previsVideoUrl, takes.slice(0, showAll ? takes.length : SHOWN).map(take => take.url));

  // Another shot, another cut: what was playing and the take being tried end with it; leaving the stage ends the trial too.
  useEffect(() => {shotMonitor.stop(); setShowAll(false); filmTrial.set(null);}, [id]);
  useEffect(() => () => {filmTrial.set(null); shotMonitor.stop();}, []);

  const item = playing ? playing.queue[playing.at] || null : null;
  const playingTake = item && item.shotId === id ? takes.find(take => take.url === item.url) || null : null;
  // Each play is a new run, so playing the same take again starts it over.
  const play = (queue, around = false) => shotMonitor.play(queue, around);
  const playTake = take => play([{shotId:id, shotIndex:current.shotIndex, index:0, url:take.url, in:0, out:null, source:'take', number:take.number}]);
  const neighbours = filmNeighbors(film, id, {measured});
  const around = (withTrial = tried) => {
    const ids = new Set([neighbours.prev, neighbours.current, neighbours.next].filter(Boolean).map(entry => entry.shotId));
    return filmPlayback(film, {fill:'latest', trial:withTrial}).filter(entry => ids.has(entry.shotId));
  };
  const playAround = (withTrial = tried) => play(around(withTrial), true);
  const stop = () => shotMonitor.stop();
  const next = () => shotMonitor.next();

  const adopt = async take => {
    const body = adoptionBody(take);
    if (!writable || !body) return false;
    const ok = await onWrite?.(() => storyRequest(`/shots/${id}/adoptions`, 'POST', body), {proposals:'proposalId' in body});
    if (ok && tried) filmTrial.set(null);
    return Boolean(ok);
  };
  const chooseFrame = frame => writable && frame.imageId && onWrite?.(() => storyRequest(`/shots/${id}/adoptions`, 'POST', {imageId:frame.imageId}));
  const unadopt = () => onWrite?.(() => storyRequest(`/shots/${id}/adoption`, 'DELETE'));
  const tryTake = take => {
    if (tried?.url === take.url) {filmTrial.set(null); stop(); return;}
    const value = {shotId:id, url:take.url, number:take.number};
    filmTrial.set(value); playAround(value);
  };
  // A (3.5): the take being tried, else the take playing in the monitor, else the newest; then the next shot with a new take.
  const adoptKey = async () => {
    const target = (tried && takes.find(take => take.url === tried.url)) || playingTake || takes[0];
    if (!writable || disabled || !target) return;
    const after = nextNewTake(film, id);
    if (!target.adopted && !(await adopt(target))) return;
    if (after) onPick?.(after.rowId);
  };
  const escape = () => {
    if (!tried && !playing) return false;
    filmTrial.set(null); stop(); return true;
  };
  useEffect(() => {
    if (!controlRef) return undefined;
    const control = {adopt:adoptKey, escape};
    controlRef.current = control;
    return () => {if (controlRef.current === control) controlRef.current = null;};
  });

  // SPEC_19 package D. R17: the seams between the film's shots and their checks (GET /episodes/{id}/cuts, read again on another shot or
  // a new revision). R18: "Cuts only" plays a second either side of every seam through the same player; a seam dot plays its own
  // seam. The seam shown is the one playing, else the one last pressed. R16: shots whose adopted take quotes a changed upstream.
  const epId = shot?.episodeId || defaultEpisodeId(slug);
  const [aroundMode, setAroundMode] = useState('whole'), [seamKey, setSeamKey] = useState(null), [seamCheck, setSeamCheck] = useState({busy:false, error:''});
  const cuts = useEpisodeCuts(epId, `${version}|${id}`);
  const seams = filmSeams(film, cuts.items);
  const seamQueue = only => seamPlaylist(filmPlayback(film, {fill:'latest', trial:tried}), {measured, only});
  const seamShown = seams.find(seam => seam.key === (item?.seam?.key || seamKey)) || null;
  useEffect(() => {setSeamKey(null); setSeamCheck({busy:false, error:''});}, [id]);
  const pickSeam = seam => {setSeamKey(seam.key); setSeamCheck({busy:false, error:''}); play(seamQueue(seam.key));};
  const checkSeam = async seam => {
    if (!writable) return;
    setSeamCheck({busy:true, error:''});
    try {await queueCutChecks(epId, [[seam.fromShotId, seam.toShotId]]); setSeamCheck({busy:false, error:''}); cuts.reload();}
    catch (error) {setSeamCheck({busy:false, error:error.message});}
  };
  const staleShots = new Set(film.filter(entry => staleTakeRefs(entry).length > 0).map(entry => entry.shotId));
  const aroundQueue = () => (aroundMode === 'seams' ? seamQueue() : around());
  const refsLine = <TakeRefsLine refs={shot?.takeRefs || []} shots={film} proposals={proposals} writable={writable} onReshoot={() => focusShotPrompt(rid)}/>;

  const blocked = normalizeStatus(status) === 'Blocked', approved = normalizeStatus(status) === 'Approved';
  const menuItems = [
    writable && canStatus && {id:'block', label:t(blocked ? 'shotMenu.unblock' : 'shotMenu.block'), write:true, run:() => onStatus?.(blocked ? 'Queued' : 'Blocked')},
    writable && approved && {id:'unadopt', label:t('shotMenu.unadopt'), write:true, run:unadopt},
    menu.table && {id:'table', label:t('shotMenu.openTable'), run:menu.table},
    menu.compare && {id:'compare', label:t('sheetWorkspace.compareVersions'), run:menu.compare},
    writable && menu.upload && {id:'upload', label:t('sheetWorkspace.replaceUpload'), write:true, run:menu.upload},
    writable && menu.reshoot && {id:'reshoot', label:t('studio.reshoot'), write:true, run:menu.reshoot},
    writable && menu.pipeline && {id:'pipeline', label:t('studio.openPipeline'), run:menu.pipeline},
    writable && menu.agent && {id:'agent', label:t('sheetWorkspace.requestAgentRevisions'), run:menu.agent},
  ].filter(Boolean).map(entry => ({...entry, disabled:Boolean(entry.write && disabled)}));

  const source = shot?.selectedVideoUrl ? measured[shot.selectedVideoUrl] : null;
  return <ShotFilmView label={label} sceneTitle={sceneTitle} state={shotStateOf(current)} newCount={newTakeCountOf(current)} writable={writable} disabled={disabled}
    canStatus={canStatus} menuItems={menuItems} top={<>{refsLine}{top}</>} film={film} neighbours={neighbours} segments={filmSegments(film, {measured})} summary={filmSummary(film, {measured})}
    seams={seams} staleShots={staleShots} seam={seamShown} seamBusy={seamCheck.busy} seamError={seamCheck.error} onSeam={pickSeam} onCheckSeam={checkSeam} aroundMode={aroundMode} onAroundMode={setAroundMode}
    currentId={id} trial={tried} playing={playing} item={item} canAround={aroundQueue().length > 0} onAround={() => (playing?.around ? stop() : play(aroundQueue(), true))}
    onPlayCurrent={() => play(around().filter(entry => entry.shotId === id))} onPick={rowId => onPick?.(rowId)} onStop={stop} onDone={next} onMeasured={(url, seconds) => shotMonitor.measure(url, seconds)} monitorHosted={hosts > 0}
    output={output} hasFrame={hasFrame} onOutput={setOutput} takes={takes} frames={output === 'frame' && media.images ? framesOf(media.images) : null} loading={media.loading} error={media.error}
    grades={media.grades} fidelity={fidelity} showAll={showAll} onShowAll={setShowAll} playingUrl={playingTake?.url || null}
    onPlay={playTake} onAdopt={adopt} onTry={tryTake} onChooseFrame={chooseFrame} onRetake={onRetake} onDismiss={take => take.entry && onDismissProposal?.(take.entry.proposal)}
    trim={{url:shot?.selectedVideoUrl || null, trim:shot?.trim || null, source}} onTimeline={onTimeline}
    crew={entries.filter(entry => !takeOnlyProposal(entry))} onApplyProposal={onApplyProposal} onDismissProposal={onDismissProposal} onShowStage={onShowStage}
    failure={failure} notes={notes} cast={cast} history={history}/>;
}

// What the panel draws, from plain data: no requests, no timers (the monitor's <video> is the only thing that plays).
export function ShotFilmView({label, sceneTitle, state = 'empty', newCount = 0, writable, disabled, canStatus = true, menuItems = [], top = null,
  neighbours = {index:-1, total:0}, segments = [], summary = {shots:0, adopted:0, withTake:0, seconds:0}, currentId, trial = null, playing = null, item = null,
  canAround = false, onAround, onPlayCurrent, onPick, onStop, onDone, onMeasured, monitorHosted = false, output = 'video', hasFrame = false, onOutput, takes = [], frames = null,
  loading = false, error = '', grades = [], fidelity = {}, showAll = false, onShowAll, playingUrl = null, onPlay, onAdopt, onTry, onChooseFrame, onRetake, onDismiss,
  trim = null, onTimeline, crew = [], onApplyProposal, onDismissProposal, onShowStage, failure = null, notes = null, cast = null, history = null,
  seams = null, staleShots = null, seam = null, seamBusy = false, seamError = '', onSeam, onCheckSeam, aroundMode = 'whole', onAroundMode}) {
  useLocale();
  trial = trial && trial.shotId === currentId ? trial : null;  // a take tried on another shot is not marked here
  // SPEC_19 package D: the seam after each segment (filmSeams(), keyed by the shot before it) and the shots with a stale reference.
  const seamAfter = new Map((seams || []).map(entry => [entry.fromShotId, entry]));
  const list = output === 'frame' ? frames || [] : takes;
  const shown = showAll ? list : list.slice(0, SHOWN);
  return <aside className="shot-detail shot-film" aria-label={t('film.panel')}>
    <header className="shot-film-head">
      <b className="num">{label}</b>{sceneTitle && <span className="shot-film-scene" title={sceneTitle}>{sceneTitle}</span>}
      <span className="spacer"/>
      <span className={'shot-state is-' + state}><i className={'shot-dot state-' + state} aria-hidden="true"/>{t('take.state_' + state)}{state === 'new_take' && newCount > 0 && <span className="num">{newCount}</span>}</span>
      <ShotMenu items={menuItems}/>
    </header>
    {top}
    {item && !monitorHosted && <FilmMonitor item={item} clip={`${playing?.run ?? 0}:${playing?.at ?? 0}`} trial={trial} currentId={currentId} onDone={onDone} onStop={onStop} onMeasured={onMeasured}/>}
    <section className="film-cut" aria-label={t('film.inTheCut')}>
      <header><h3>{t('film.inTheCut')}</h3>{neighbours.index >= 0 && <span className="studio-note">{t('film.position', {index:neighbours.index + 1, total:neighbours.total})}</span>}
        <span className="spacer"/>
        {onAroundMode && <PlayModeToggle mode={aroundMode} onMode={onAroundMode}/>}
        <button type="button" className="film-around" aria-pressed={Boolean(playing?.around)} disabled={!canAround && !playing?.around} onClick={onAround}>
          <Icon name={playing?.around ? 'pause' : 'play'} size={13}/>{t(playing?.around ? 'film.stop' : aroundMode === 'seams' ? 'seam.playCuts' : 'film.playAround')}</button></header>
      <ol className="film-neighbours">{['prev', 'current', 'next'].map(key => {
        const entry = neighbours[key];
        if (!entry) return <li key={key} className="is-none"><span className="film-thumb is-blank"/><small>{t('film.noNeighbour')}</small></li>;
        const isCurrent = key === 'current', tried = isCurrent && trial;
        return <li key={key} className={(isCurrent ? 'is-current' : '') + (tried ? ' is-trial' : '')}>
          <button type="button" onClick={() => (isCurrent ? onPlayCurrent?.() : onPick?.(entry.rowId))} aria-label={t('film.segment', {shot:entry.shotIndex, state:t('take.state_' + entry.state), seconds:tenth(entry.seconds)})}>
            <span className={'film-thumb is-' + entry.thumb.kind}>{entry.thumb.posterUrl ? <img src={entry.thumb.posterUrl} alt="" loading="lazy"/> : <Icon name={entry.thumb.kind === 'previs' ? 'cube' : 'image'} size={14}/>}
              {tried && <em className="film-tag is-trial">{t('film.tag_trial')}</em>}</span>
            <span className="film-caption"><b>{entry.shotIndex}</b><small><i className={'shot-dot state-' + entry.state} aria-hidden="true"/>{t('take.state_' + entry.state)} · {t('film.seconds', {seconds:tenth(entry.seconds)})}</small></span>
          </button></li>;
      })}</ol>
    </section>
    <section className="film-progress" aria-label={t('film.progress')}>
      <ol>{segments.map(segment => {
        const isCurrent = segment.shotId === currentId, tried = isCurrent && trial, stale = Boolean(staleShots?.has(segment.shotId)), after = seamAfter.get(segment.shotId);
        return <li key={segment.shotId} style={{flexGrow:Math.max(segment.share, 0.0001)}}>
          <button type="button" className={'film-seg state-' + segment.state + (isCurrent ? ' is-current' : '') + (tried ? ' is-trial' : '')} aria-current={isCurrent ? 'true' : undefined}
            aria-label={t('film.segment', {shot:segment.shotIndex, state:t('take.state_' + segment.state), seconds:tenth(segment.seconds)}) + (tried ? ' · ' + t('film.tag_trial') : '') + (stale ? ' · ' + t('refs.staleMark') : '')}
            title={t('film.segment', {shot:segment.shotIndex, state:t('take.state_' + segment.state), seconds:tenth(segment.seconds)})} onClick={() => !isCurrent && onPick?.(segment.rowId)}>
            {tried && <em>{t('film.tag_trial')}</em>}</button>
          {stale && <i className="film-seg-stale" title={t('refs.staleMark')} aria-hidden="true"/>}
          {after && <SeamDot seam={after} active={seam?.key === after.key} onPick={onSeam}/>}</li>;
      })}</ol>
      <p className="studio-note">{t('film.summary', {adopted:summary.adopted, total:summary.shots, seconds:tenth(summary.seconds)})}</p>
      {seam && <SeamDetail seam={seam} writable={writable} busy={seamBusy} error={seamError} onCheck={onCheckSeam}/>}
    </section>
    <section className="take-list" aria-label={t('take.list')}>
      <header><h3>{t('take.list')}</h3>
        {hasFrame && <div className="studio-segmented" role="group" aria-label={t('take.output')}>{['video', 'frame'].map(kind =>
          <button key={kind} type="button" aria-pressed={output === kind} onClick={() => onOutput?.(kind)}>{t(kind === 'video' ? 'take.outputVideo' : 'take.outputFrame')}</button>)}</div>}
        <span className="spacer"/>
        {writable && canStatus && <button type="button" className="take-retake" disabled={disabled} onClick={onRetake} title={t('take.retake')}><Icon name="refresh" size={13}/>{t('take.retakeKey')}</button>}
      </header>
      {error && <p className="sheet-save-error" role="alert">{t('take.failed', {message:error})}</p>}
      {!list.length && <p className="sheet-subtle">{loading || (output === 'frame' && frames === null) ? t('take.loading') : t(output === 'frame' ? 'take.noFrames' : 'take.none')}</p>}
      <ol>{shown.map(take => output === 'frame'
        ? <FrameRow key={take.url} frame={take} writable={writable} disabled={disabled} onChoose={onChooseFrame}/>
        : <TakeRow key={take.url} take={take} grade={takeGrade(grades, take.url)} fidelity={fidelity[take.url]} writable={writable} disabled={disabled}
          playing={playingUrl === take.url} tried={trial?.url === take.url} onPlay={onPlay} onAdopt={onAdopt} onTry={onTry} onDismiss={onDismiss}/>)}</ol>
      {list.length > SHOWN && <button type="button" className="quiet take-more" onClick={() => onShowAll?.(!showAll)}>{showAll ? t('take.showFewer') : t('take.showAll', {count:list.length})}</button>}
    </section>
    {trim && <TrimLine {...trim} onTimeline={onTimeline}/>}
    {failure}
    <ShotProposals items={crew} writable={writable && !disabled} onApply={onApplyProposal} onDismiss={onDismissProposal} onShow={onShowStage}/>
    {notes && <FilmNotes messages={notes.messages || []}>{notes.node}</FilmNotes>}
    {history}
    {cast && <details className="shot-cast-fold"><summary>{t('shotMenu.cast', {count:cast.count ?? 0})}</summary>{cast.node}</details>}
  </aside>;
}

function TakeRow({take, grade, fidelity, writable, disabled, playing, tried, onPlay, onAdopt, onTry, onDismiss}) {
  const body = adoptionBody(take), number = take.number;
  const facts = [grade?.status === 'graded' && t('take.grade', {score:grade.score}), Number.isFinite(fidelity) && t('take.fidelity', {percent:Math.round(fidelity * 100)})].filter(Boolean);
  return <li className={'take-row' + (take.adopted ? ' is-adopted' : '') + (playing ? ' is-playing' : '') + (tried ? ' is-trial' : '')}>
    <button type="button" className="take-play" aria-label={t('take.play', {number})} onClick={() => onPlay?.(take)}>
      <span className="take-thumb"><video src={take.url + '#t=0.1'} preload="metadata" muted playsInline aria-hidden="true"/></span>
      <span className="take-text"><span><b>{t('take.number', {number})}</b>{take.adopted && <em className="take-badge is-adopted">{t('take.inCut')}</em>}
        {take.isNew && !take.adopted && <em className="take-badge is-new">{t('take.new')}</em>}{tried && <em className="take-badge is-trial">{t('film.tag_trial')}</em>}</span>
        <small>{take.source === 'proposal' ? [t('take.pipeline'), ...facts].join(' · ') : facts.join(' · ')}</small></span>
    </button>
    {!take.adopted && <button type="button" className="take-try" aria-pressed={tried} aria-label={t(tried ? 'take.trying' : 'take.try', {number})} title={t(tried ? 'take.trying' : 'take.try', {number})}
      onClick={() => onTry?.(take)}><Icon name="timeline" size={14}/></button>}
    {writable && (take.adopted ? <span className="take-check is-on" role="img" aria-label={t('take.adopted')}><Icon name="check" size={14}/></span>
      : body ? <button type="button" className="take-check" aria-label={t('take.adoptTake', {number})} title={t('take.adoptKey')} disabled={disabled} onClick={() => onAdopt?.(take)}><Icon name="check" size={14}/></button>
        : <span className="take-check is-off" title={t('take.multiRow', {count:take.entry?.size ?? 0})}><Icon name="check" size={14}/></span>)}
    {writable && take.source === 'proposal' && body && <button type="button" className="take-dismiss" aria-label={t('take.dismiss', {number})} title={t('take.dismiss', {number})} disabled={disabled}
      onClick={() => onDismiss?.(take)}><Icon name="close" size={12}/></button>}
  </li>;
}

function FrameRow({frame, writable, disabled, onChoose}) {
  const number = frame.number;
  return <li className={'take-row' + (frame.selected ? ' is-adopted' : '')}>
    <span className="take-play is-still"><span className="take-thumb"><img src={frame.url} alt="" loading="lazy"/></span>
      <span className="take-text"><span><b>{t('take.frameNumber', {number})}</b>{frame.selected && <em className="take-badge is-adopted">{t('take.inUse')}</em>}</span></span></span>
    {writable && (frame.selected ? <span className="take-check is-on" role="img" aria-label={t('take.inUse')}><Icon name="check" size={14}/></span>
      : <button type="button" className="take-check" aria-label={t('take.adoptFrame', {number})} title={t('take.adoptFrame', {number})} disabled={disabled || !frame.imageId} onClick={() => onChoose?.(frame)}><Icon name="check" size={14}/></button>)}
  </li>;
}

// The trim the cut uses for the take in the cell (story_trim): "Cut uses 0.4–3.8 s", or the whole take; the Timeline edits it.
function TrimLine({url, trim, source, onTimeline}) {
  const from = Number.isFinite(trim?.in) && trim.in > 0 ? trim.in : 0, to = Number.isFinite(trim?.out) && trim.out > from ? trim.out : null;
  const text = !url ? t('film.noTake')
    : to !== null ? t(Number.isFinite(source) ? 'film.trimOf' : 'film.trim', {from:tenth(from), to:tenth(to), length:tenth(to - from), source:tenth(source || 0)})
      : from > 0 ? t('film.trimFrom', {from:tenth(from)})
        : Number.isFinite(source) ? t('film.wholeSeconds', {seconds:tenth(source)}) : t('film.whole');
  return <p className="film-trim"><Icon name="cut" size={13}/><span>{text}</span><span className="spacer"/>
    {onTimeline && <button type="button" className="quiet" title={t('film.openTimeline')} onClick={onTimeline}>{t('film.timeline')}<Icon name="arrowRight" size={12}/></button>}</p>;
}

// The row's notes: the latest two, and every note with the comment box folded under them.
function FilmNotes({messages, children}) {
  return <section className="film-notes" aria-label={t('film.notes')}>
    {messages.slice(-2).map((message, index) => <p key={message.id || index}><strong>{message.name || message.actor_name}</strong> {message.body || message.new_value}</p>)}
    <details><summary>{t('film.allNotes', {count:messages.length})}</summary>{children}</details>
  </section>;
}

// The player: one clip at a time, the source marked in the corner (a filled gap, a take being tried). The composer draws the same one.
export function FilmMonitor({item, clip, trial, currentId, onDone, onStop, onMeasured}) {
  const tag = item.source === 'trial' || (trial && item.shotId === currentId && item.url === trial.url) ? 'trial' : ['latest', 'previs'].includes(item.source) ? item.source : null;
  const caption = item.source === 'take' && item.number ? `${item.shotIndex} · ${t('take.number', {number:item.number})}` : String(item.shotIndex ?? '');
  return <figure className="film-monitor">
    <ClipVideo key={`${clip}:${item.shotId}:${item.url}`} item={item} onDone={onDone} onMeasured={onMeasured} aria-label={caption}
      onClick={event => {const video = event.currentTarget; if (video.paused) video.play().catch(() => {}); else video.pause();}}/>
    {tag && <em className={'film-tag is-' + tag}>{t('film.tag_' + tag)}</em>}
    <figcaption><span>{caption}</span><button type="button" className="film-monitor-stop" aria-label={t('film.stop')} title={t('film.stopHint')} onClick={onStop}><Icon name="close" size={12}/></button></figcaption>
  </figure>;
}

// The "…" menu: the shot's less frequent actions, folded until asked for. Escape closes it without reaching the stage's keys.
function ShotMenu({items}) {
  const [open, setOpen] = useState(false);
  const root = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const away = event => {if (!root.current?.contains(event.target)) setOpen(false);};
    document.addEventListener('mousedown', away);
    return () => document.removeEventListener('mousedown', away);
  }, [open]);
  if (!items.length) return null;
  return <details ref={root} className="shot-menu" open={open} onToggle={event => setOpen(event.currentTarget.open)}
    onKeyDown={event => {if (event.key === 'Escape' && open) {event.stopPropagation(); setOpen(false); root.current?.querySelector('summary')?.focus();}}}>
    <summary aria-label={t('shotMenu.more')} title={t('shotMenu.more')}>⋯</summary>
    <div className="shot-menu-list" role="menu">{items.map(entry => <button key={entry.id} type="button" role="menuitem" disabled={entry.disabled}
      onClick={() => {setOpen(false); entry.run();}}>{entry.label}</button>)}</div>
  </details>;
}
