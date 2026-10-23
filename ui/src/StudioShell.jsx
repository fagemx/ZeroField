import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocale } from './i18n/react.jsx';
import { currentLocale, setLocale, t } from './i18n/index.js';
import { episodeId, storyList, storyRequest, waitStoryTask } from './storyModel.js';
import { SHOT_FILTERS } from './studioModel.js';
import { Icon } from './Icon.jsx';
import './studio-shell.css';
import { semanticEnumKey } from './writing/writingModel.js';

// SPEC_15: a studio production has two creative spaces instead of six numbered stations.
// Story & World holds the script and the world it names; Shot Stage holds every shot. Other pages stay one Ctrl K away.
export const STORY_VIEW = 'story-world';
export const STAGE_TAB = 'cinema-studio';
const STORY_TABS = [STORY_VIEW, 'director-brief', 'soul-cast'];
const STAGE_TABS = [STAGE_TAB, 'openjutsu-lab'];
export const spaceOf = key => STORY_TABS.includes(key) ? 'story' : STAGE_TABS.includes(key) ? 'stage' : null;

// One episode's state for the top bar, both spaces and the film: refreshed when a page saves (version) or on demand.
export function useEpisode(slug, epId, version, enabled = true) {
  const [state, setState] = useState({episodes:[], ep:null, shots:[], alignment:null, error:''});
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    if (!enabled) return undefined;
    let alive = true, error = '';
    // Each part loads on its own: a missing episode list must not keep the episode itself from loading.
    const settle = request => request.catch(failure => {error = error || failure.message; return null;});
    Promise.all([settle(storyList('/projects/pj_' + slug + '/episodes')), settle(storyRequest('/episodes/' + epId)), settle(storyList('/episodes/' + epId + '/shots')), settle(storyRequest('/episodes/' + epId + '/writing/alignment'))])
      .then(([episodes, ep, shots, alignment]) => {if (alive) setState(current => ({episodes:episodes || current.episodes, ep, shots:shots || [], alignment, error}));});
    return () => {alive = false;};
  }, [slug, epId, version, nonce, enabled]);
  return {...state, reload:() => setNonce(n => n + 1)};
}

// Cinema slate order, the same order the exported film uses.
const shotOrder = shot => String(shot.shotIndex).split(/(\d+)/).map(part => /^\d+$/.test(part) ? part.padStart(6, '0') : part.toLowerCase()).join('');
export const orderedShots = shots => shots.filter(shot => shot.tabKey === STAGE_TAB).sort((a, b) => shotOrder(a).localeCompare(shotOrder(b)));
export function episodeCounts(ep, shots) {
  const cut = orderedShots(shots);
  return {
    shots:cut.length,
    review:cut.filter(shot => SHOT_FILTERS.review({status:shot.reviewStatus})).length,
    missing:ep?.missingAssetCodes?.length || 0,
    filmed:cut.filter(shot => shot.selectedVideoUrl).length,
    scriptDirty:Boolean(ep?.scriptDirty),
  };
}

export function StudioTopBar({project, episodes, epId, onEpisode, space, pageTitle, counts, onSpace, onCommand, assistant, film, identity, settings, writingStatus}) {
  useLocale();
  const storyNote = [counts.scriptDirty && t('shell.storyUpdated'), counts.missing && t('shell.missingImages', {count:counts.missing})].filter(Boolean).join(' · ');
  const stageNote = [t('shell.shotCount', {count:counts.shots}), counts.review && t('shell.toReview', {count:counts.review})].filter(Boolean).join(' · ');
  return <header className="top studio-top">
    <div className="studio-crumb">
      <a href="/projects/" className="brand-mark" aria-label={t('app.backToProductions')} title={t('app.backToProductions')}>ZF</a>
      <span className="doc-name studio-title">{project.title}</span>
      {episodes.length > 0 && <><span className="studio-slash" aria-hidden="true">/</span>
        <select className="studio-episode" aria-label={t('story.episode')} value={epId} onChange={event => onEpisode(event.target.value)}>
          {episodes.map(item => <option key={item.episodeId} value={item.episodeId}>{item.title}</option>)}</select></>}
    </div>
    <nav className="studio-spaces" aria-label={t('shell.spaces')}>
      <button type="button" aria-current={space === 'story' ? 'page' : undefined} onClick={() => onSpace('story')}>
        {t('shell.storyWorld')}{writingStatus && <span className="studio-note" role="status">{t('writing.authoring.' + semanticEnumKey('state', writingStatus.state))}</span>}{storyNote && <span className={'studio-note' + (counts.scriptDirty || counts.missing ? ' warn' : '')}>{storyNote}</span>}</button>
      <button type="button" aria-current={space === 'stage' ? 'page' : undefined} onClick={() => onSpace('stage')}>
        {t('shell.shotStage')}<span className="studio-note">{stageNote}</span></button>
      {pageTitle && <span className="studio-page" title={pageTitle}>{pageTitle}</span>}
    </nav>
    <div className="studio-actions">
      <LocaleToggle />
      <button type="button" className="studio-command" onClick={onCommand} aria-label={t('shell.command')} aria-keyshortcuts="Control+K">
        <Icon name="code" /><span className="label">{t('shell.command')}</span><kbd>Ctrl K</kbd></button>
      {assistant}
      <button type="button" className={'studio-film' + (film.open ? ' on' : '')} aria-pressed={film.open} onClick={film.onToggle}>
        <Icon name="play" />{t('shell.film')}<span className="num">{counts.filmed}/{counts.shots}</span></button>
      {settings}
      {identity}
    </div>
  </header>;
}

// Compact EN / 中 switch; the full LanguageSwitch stays on the production list.
function LocaleToggle() {
  useLocale();
  const now = currentLocale();
  return <div className="language-switch studio-locale" role="group" aria-label={t('common.language')}>
    {[['en', 'EN'], ['zh-TW', '中']].map(([locale, label]) => <button key={locale} type="button" lang={locale} aria-pressed={now === locale}
      aria-label={locale === 'en' ? 'English' : '繁體中文'} title={locale === 'en' ? 'English' : '繁體中文'} onMouseDown={event => event.preventDefault()} onClick={() => setLocale(locale)}>{label}</button>)}
  </div>;
}

// Ctrl K: every page and engineering tool, one filtered list. Arrow keys move, Enter runs, Escape closes.
export function CommandPalette({commands, onClose}) {
  useLocale();
  const [query, setQuery] = useState(''), [at, setAt] = useState(0);
  const input = useRef(null);
  const shown = useMemo(() => {
    const q = query.trim().toLocaleLowerCase();
    return commands.filter(item => !q || `${item.label} ${item.group} ${item.hint || ''}`.toLocaleLowerCase().includes(q));
  }, [commands, query]);
  useEffect(() => {const previous = document.activeElement; input.current?.focus(); return () => {if (previous?.isConnected) previous.focus();};}, []);
  useEffect(() => setAt(0), [query]);
  const run = item => {if (!item) return; onClose(); item.run();};
  return <div className="modal-scrim studio-palette-scrim" onMouseDown={event => {if (event.target === event.currentTarget) onClose();}}>
    <section className="studio-palette" role="dialog" aria-modal="true" aria-label={t('shell.command')}>
      <input ref={input} value={query} placeholder={t('shell.commandHint')} aria-label={t('shell.command')} role="combobox" aria-expanded="true" aria-controls="studio-commands"
        aria-activedescendant={shown[at] ? 'cmd-' + shown[at].id : undefined}
        onChange={event => setQuery(event.target.value)}
        onKeyDown={event => {
          if (event.key === 'Escape') {event.stopPropagation(); onClose();}
          else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {event.preventDefault(); setAt(i => (i + (event.key === 'ArrowDown' ? 1 : -1) + shown.length) % Math.max(shown.length, 1));}
          else if (event.key === 'Enter') {event.preventDefault(); run(shown[at]);}
        }}/>
      <ul id="studio-commands" role="listbox" aria-label={t('shell.command')}>
        {shown.map((item, index) => <li key={item.id} id={'cmd-' + item.id} role="option" aria-selected={index === at}
          onMouseEnter={() => setAt(index)} onMouseDown={event => {event.preventDefault(); run(item);}}>
          <Icon name={item.icon || 'arrowRight'} /><span>{item.label}</span>{item.hint && <small>{item.hint}</small>}<em>{item.group}</em></li>)}
        {!shown.length && <li className="studio-palette-empty">{t('shell.noCommand')}</li>}
      </ul>
    </section>
  </div>;
}

// The film overlay: the whole episode in slate order. Shots without a take fall back to their previs, then a slate card.
export function FilmOverlay({epId, shots, writable, onClose}) {
  useLocale();
  const cut = useMemo(() => orderedShots(shots).map(shot => ({...shot, play:shot.selectedVideoUrl || shot.previsVideoUrl || null, fill:!shot.selectedVideoUrl && Boolean(shot.previsVideoUrl)})), [shots]);
  const [at, setAt] = useState(0), [exporting, setExporting] = useState(false), [film, setFilm] = useState(null), [error, setError] = useState('');
  const [fill, setFill] = useState(true);
  const [alignment, setAlignment] = useState(null), [alignmentError, setAlignmentError] = useState('');
  useEffect(() => {
    let active = true; setAlignment(null); setAlignmentError('');
    storyRequest(`/episodes/${epId}/writing/alignment`).then(data => {if (active) setAlignment(data);}).catch(error => {if (active) setAlignmentError(error.message);});
    return () => {active = false;};
  }, [epId, shots]);
  const differing = alignment?.items.filter(item => item.storyAlignment?.state !== 'in_sync' || item.storyAlignment?.mediaOutdated) || [];
  const video = useRef(null), box = useRef(null), alive = useRef(true);
  const current = cut[at];
  useEffect(() => {alive.current = true; box.current?.focus(); return () => {alive.current = false;};}, []);
  // A shot with nothing to play holds its slate card for two seconds, then the cut moves on.
  useEffect(() => {
    if (!current || current.play) return undefined;
    const timer = setTimeout(() => setAt(i => (i + 1 < cut.length ? i + 1 : i)), 2000);
    return () => clearTimeout(timer);
  }, [current, cut.length]);
  const exportFilm = async () => {
    setExporting(true); setError('');
    try {
      const task = await storyRequest(`/episodes/${epId}/films`, 'POST', fill ? {fillPrevis:true} : {});
      const result = await waitStoryTask(task);
      if (alive.current) setFilm(result.videoUrl);
    } catch (err) {if (alive.current) setError(err.message);}
    finally {if (alive.current) setExporting(false);}
  };
  return <div className="modal-scrim studio-film-scrim" onMouseDown={event => {if (event.target === event.currentTarget) onClose();}}>
    <section ref={box} tabIndex={-1} className="studio-film-overlay" role="dialog" aria-modal="true" aria-label={t('shell.filmTitle')}
      onKeyDown={event => {if (event.key === 'Escape') {event.stopPropagation(); onClose();}}}>
      <header><h2>{t('shell.filmTitle')}</h2><span className="studio-note">{t('shell.filmSummary', {filmed:cut.filter(s => s.selectedVideoUrl).length, total:cut.length})}</span>
        <span className="spacer"/><button type="button" className="icon-btn" aria-label={t('sheetDialog.closePanel')} onClick={onClose}><Icon name="close" /></button></header>
      {alignmentError && <p role="alert">{t('writing.integration.alignmentUnavailable')} {alignmentError}</p>}
      {!!differing.length && <p role="status">{t('writing.integration.filmWarning', {shots:differing.map(item => item.shotIndex).join(', ')})}</p>}
      <div className="studio-film-screen">
        {film ? <video src={film} controls autoPlay playsInline preload="metadata" aria-label={t('story.episodeFilm')}/>
          : current?.play ? <video ref={video} key={current.shotId} src={current.play} controls autoPlay playsInline preload="metadata"
            onEnded={() => setAt(i => (i + 1 < cut.length ? i + 1 : i))} aria-label={current.shotIndex}/>
          : <div className="studio-film-slate">{current ? <><b>{current.shotIndex}</b><span>{t('shell.notShot')}</span></> : t('shell.noShots')}</div>}
        {!film && current?.fill && <span className="studio-film-tag">{t('shell.previsFill')}</span>}
      </div>
      <ol className="studio-film-strip" aria-label={t('shell.filmStrip')}>
        {cut.map((shot, index) => <li key={shot.shotId}><button type="button" aria-current={index === at && !film ? 'true' : undefined}
          className={shot.selectedVideoUrl ? 'shot' : shot.fill ? 'shot fill' : 'shot empty'} onClick={() => {setFilm(null); setAt(index);}}>
          {shot.selectedImageUrl ? <img src={shot.selectedImageUrl} alt="" loading="lazy"/> : <span className="studio-film-blank"/>}
          <span>{shot.shotIndex}</span></button></li>)}
      </ol>
      <footer>
        {cut.some(shot => shot.fill) ? <label className="studio-note studio-fill"><input type="checkbox" checked={fill} onChange={event => setFill(event.target.checked)}/>{t('shell.exportFill')}</label>
          : <span className="studio-note">{t('shell.exportHelp')}</span>}
        {error && <span role="alert" className="canvas-error">{error}</span>}
        {film && <a className="icon-btn" href={film} download><Icon name="download" />{t('shell.downloadFilm')}</a>}
        <span className="spacer"/>
        <button type="button" className="primary" disabled={!writable || exporting || !cut.some(s => s.selectedVideoUrl || (fill && s.fill))} onClick={exportFilm}>
          {exporting ? t('story.working') : t('shell.exportFilm')}</button>
      </footer>
    </section>
  </div>;
}

export { episodeId };
