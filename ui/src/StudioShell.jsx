import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { useLocale } from './i18n/react.jsx';
import { currentLocale, setLocale, t } from './i18n/index.js';
import { episodeId, storyList, storyRequest, waitStoryTask } from './storyModel.js';
import { SHOT_FILTERS } from './studioModel.js';
import { Icon } from './Icon.jsx';
import './studio-shell.css';

// SPEC_15: a studio production has creative spaces instead of six numbered stations, now three ways of thinking:
// Story & World (structure), Shot Stage (space) and Timeline (time). There are no standing tabs: the current space is the
// one breadcrumb button that opens a menu (or Ctrl 1/2/3, Ctrl K, and every "go there" action). Other pages stay one Ctrl K away.
export const STORY_VIEW = 'story-world';
export const STAGE_TAB = 'cinema-studio';
export const TIMELINE_VIEW = 'timeline';
const STORY_TABS = [STORY_VIEW, 'director-brief', 'soul-cast'];
const STAGE_TABS = [STAGE_TAB, 'openjutsu-lab'];
export const VIRTUAL_TABS = [STORY_VIEW, TIMELINE_VIEW];  // spaces drawn by the shell itself, not by a project tab
export const spaceOf = key => STORY_TABS.includes(key) ? 'story' : STAGE_TABS.includes(key) ? 'stage' : key === TIMELINE_VIEW ? 'timeline' : null;
export const SPACES = [
  {key:'story', tab:STORY_VIEW, icon:'doc', label:'shell.storyWorld'},
  {key:'stage', tab:STAGE_TAB, icon:'clapper', label:'shell.shotStage'},
  {key:'timeline', tab:TIMELINE_VIEW, icon:'timeline', label:'shell.timeline'},
];
export const tabOfSpace = key => SPACES.find(space => space.key === key)?.tab || STAGE_TAB;
// What each space needs from you, shown only when the space menu is open: switching is on request, not a standing set of tabs.
export const spaceNote = (key, counts = {}) => key === 'story'
  ? [counts.scriptDirty && t('shell.storyUpdated'), counts.missing && t('shell.missingImages', {count:counts.missing})].filter(Boolean).join(' · ')
  : key === 'stage' ? [t('shell.shotCount', {count:counts.shots || 0}), counts.review && t('shell.toReview', {count:counts.review})].filter(Boolean).join(' · ')
    : t('shell.filmSummary', {filmed:counts.filmed || 0, total:counts.shots || 0});
// SPEC_18 R6: the same needs as things you can press. `target` is where the press goes: the shell carries it into the space ({view, facet}
// for Story & World, {filter} for the Shot Stage) and the space takes it once. The Timeline only reports how far the film is.
export const spaceShortcuts = (key, counts = {}) => key === 'story'
  ? [counts.scriptDirty && {id:'script', label:t('shell.storyUpdated'), target:{view:'script'}},
    counts.missing && {id:'missing', label:t('shell.missingImages', {count:counts.missing}), target:{view:'world', facet:'missing'}}].filter(Boolean)
  : key === 'stage' ? [counts.review && {id:'review', label:t('shell.toReview', {count:counts.review}), target:{filter:'review'}},
    counts.missingShots && {id:'missing', label:t('shell.shotsMissingRefs', {count:counts.missingShots}), target:{filter:'missing'}}].filter(Boolean)
    : [{id:'filmed', label:t('shell.filmSummary', {filmed:counts.filmed || 0, total:counts.shots || 0}), target:null}];

// One episode's state for the top bar, both spaces and the film: refreshed when a page saves (version) or on demand.
export function useEpisode(slug, epId, version, enabled = true) {
  const [state, setState] = useState({episodes:[], ep:null, shots:[], error:''});
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    if (!enabled) return undefined;
    let alive = true, error = '';
    // Each part loads on its own: a missing episode list must not keep the episode itself from loading.
    const settle = request => request.catch(failure => {error = error || failure.message; return null;});
    Promise.all([settle(storyList('/projects/pj_' + slug + '/episodes')), settle(storyRequest('/episodes/' + epId)), settle(storyList('/episodes/' + epId + '/shots'))])
      .then(([episodes, ep, shots]) => {if (alive) setState(current => ({episodes:episodes || current.episodes, ep, shots:shots || [], error}));});
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
    missingShots:cut.filter(shot => SHOT_FILTERS.missing({info:shot})).length,
    filmed:cut.filter(shot => shot.selectedVideoUrl).length,
    scriptDirty:Boolean(ep?.scriptDirty),
  };
}

// The breadcrumb is also the focus line: project / episode / space (a menu) / scene / shot. The focus travels between spaces.
// crumbs: {scene, shot} labels of the shell's current focus. panels: which panel toggles this space has (left, bottom, right).
export function StudioTopBar({project, episodes, epId, onEpisode, space, pageTitle, crumbs = {}, counts, onSpace, onCommand, assistant, film, identity, settings, panels = ['left', 'right'], layout = {}, onLayout}) {
  useLocale();
  const slash = <span className="studio-slash" aria-hidden="true">/</span>;
  // A page opened from a space (the cast sheet, the brief, a lab page) has no tabs to leave by: Back returns to that space (the Shot Stage when it has none).
  const home = SPACES.find(item => item.key === space) || SPACES[1];
  return <header className="top studio-top">
    <div className="studio-crumb">
      <a href="/projects/" className="brand-mark" aria-label={t('app.backToProductions')} title={t('app.backToProductions')}>ZF</a>
      <span className="doc-name studio-title">{project.title}</span>
      {episodes.length > 0 && <>{slash}
        <select className="studio-episode" aria-label={t('story.episode')} value={epId} onChange={event => onEpisode(event.target.value)}>
          {episodes.map(item => <option key={item.episodeId} value={item.episodeId}>{item.title}</option>)}</select></>}
      {slash}<SpaceMenu space={space} counts={counts} onSpace={onSpace}/>
      {pageTitle && <>{slash}<button type="button" className="studio-back" title={t('shell.backTo', {space:t(home.label)})} aria-label={t('shell.backTo', {space:t(home.label)})}
        onClick={() => onSpace?.(home.key)}><Icon name="arrowLeft" size={14}/><span>{t('shell.back')}</span></button>
        <span className="studio-focus" title={pageTitle}>{pageTitle}</span></>}
      {crumbs.scene && <>{slash}<span className="studio-focus" title={crumbs.scene}>{crumbs.scene}</span></>}
      {crumbs.shot && <>{slash}<b className="studio-focus is-now" title={crumbs.shot}><i className="studio-dot" aria-hidden="true"/>{crumbs.shot}</b></>}
    </div>
    <div className="studio-actions">
      <LocaleToggle />
      <button type="button" className="studio-command" onClick={onCommand} aria-label={t('shell.command')} aria-keyshortcuts="Control+K">
        <Icon name="code" /><span className="label">{t('shell.command')}</span><kbd>Ctrl K</kbd></button>
      {assistant}
      {panels.length > 0 && <div className="studio-layout" role="group" aria-label={t('shell.panels')}>
        {panels.map(key => <button key={key} type="button" aria-pressed={layout[key] !== false} aria-label={t('shell.panel_' + key)} title={t('shell.panel_' + key)}
          onClick={() => onLayout?.(key)}><Icon name={'panel' + key[0].toUpperCase() + key.slice(1)} size={15}/></button>)}
      </div>}
      <button type="button" className={'studio-film' + (film.open ? ' on' : '')} aria-pressed={film.open} onClick={film.onToggle}>
        <Icon name="play" />{t('shell.film')}<span className="num">{counts.filmed}/{counts.shots}</span></button>
      {settings}
      {identity}
    </div>
  </header>;
}

// The one place the three spaces are offered, and only on request: a quiet breadcrumb button that opens a menu. Under each space sit
// what it needs from you, each its own menu item (a shortcut is never a button inside the space's button): the arrow keys reach them,
// Escape closes the menu and returns focus to the space button.
export function SpaceMenu({space, counts = {}, defaultOpen = false, onSpace}) {
  useLocale();
  const [open, setOpen] = useState(defaultOpen);
  const root = useRef(null);
  const current = SPACES.find(item => item.key === space);
  useEffect(() => {
    if (!open) return undefined;
    const away = event => {if (!root.current?.contains(event.target)) setOpen(false);};
    const keys = event => {
      if (event.key === 'Escape') {setOpen(false); root.current?.querySelector('.studio-space-btn')?.focus();}
      else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        const items = [...root.current.querySelectorAll('[role="menuitemradio"],[role="menuitem"]')], at = items.indexOf(document.activeElement);
        event.preventDefault(); items[(at + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus();
      }
    };
    document.addEventListener('mousedown', away); document.addEventListener('keydown', keys);
    root.current?.querySelector('[aria-checked="true"]')?.focus();
    return () => {document.removeEventListener('mousedown', away); document.removeEventListener('keydown', keys);};
  }, [open]);
  return <div className="studio-spacemenu" ref={root}>
    <button type="button" className="studio-space-btn" aria-haspopup="menu" aria-expanded={open} aria-keyshortcuts="Control+1 Control+2 Control+3" onClick={() => setOpen(value => !value)}>
      <Icon name={current?.icon || 'layers'}/><span>{current ? t(current.label) : t('shell.spaces')}</span><Icon name="chevronDown" size={13}/></button>
    {open && <div className="studio-menu" role="menu" aria-label={t('shell.spaces')}>
      {SPACES.map((item, index) => <Fragment key={item.key}>
        <button type="button" role="menuitemradio" aria-checked={item.key === space} onClick={() => {setOpen(false); onSpace?.(item.key);}}>
          <Icon name={item.icon}/><span className="studio-menu-name">{t(item.label)}</span><kbd>Ctrl {index + 1}</kbd></button>
        {spaceShortcuts(item.key, counts).map(shortcut => <button key={shortcut.id} type="button" role="menuitem" className="studio-menu-shortcut"
          onClick={() => {setOpen(false); onSpace?.(item.key, shortcut.target || undefined);}}>
          <span>{shortcut.label}</span>{shortcut.target && <Icon name="arrowRight" size={13}/>}</button>)}
      </Fragment>)}
      <p className="studio-menu-foot">{t('shell.spaceMenuHint')}</p>
    </div>}
  </div>;
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
export function FilmOverlay({epId, shots, writable, onClose, onTimeline}) {
  useLocale();
  const cut = useMemo(() => orderedShots(shots).map(shot => ({...shot, play:shot.selectedVideoUrl || shot.previsVideoUrl || null, fill:!shot.selectedVideoUrl && Boolean(shot.previsVideoUrl)})), [shots]);
  const [at, setAt] = useState(0), [exporting, setExporting] = useState(false), [film, setFilm] = useState(null), [error, setError] = useState('');
  const [fill, setFill] = useState(true);
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
        <span className="spacer"/>{onTimeline && <button type="button" className="quiet" onClick={() => {onClose(); onTimeline();}}><Icon name="timeline" />{t('shell.openInTimeline')}</button>}
        <button type="button" className="icon-btn" aria-label={t('sheetDialog.closePanel')} onClick={onClose}><Icon name="close" /></button></header>
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
