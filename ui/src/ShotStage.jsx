import { useEffect, useRef, useState } from 'react';
import { useLocale } from './i18n/react.jsx';
import { t } from './i18n/index.js';
import { mediaOf } from './sheetModel.js';
import { mediaStages, SHOT_FILTERS } from './studioModel.js';
import { shotStateOf } from './takeModel.js';
import { CameraFidelity } from './ShotBench.jsx';
import { Icon } from './Icon.jsx';

// SPEC_18 R4: the shot's three rungs, cheapest first: previs -> first frame -> video. Each shows what exists (a picture, or a paused first
// frame; nothing here ever plays on its own) and opens the view where that rung is worked on. A shot with no previs yet is told so, with a
// quiet way to plan one; it never blocks shooting. SPEC_19 took it out of the shot's right column (the column is now the shot in the
// cut). Given onOutput, it is the shot composer's output switch (R9): the first frame and the video rungs become the two things the
// composer can make, each ticked when the shot already has one; the previs rung stays in the 3D Stage.
const RUNG_ICON = {previs: 'cube', frame: 'image', video: 'play'};
function RungThumb({step}) {
  const media = step.media;
  if (media?.kind === 'image') return <img src={media.url} alt="" loading="lazy"/>;
  if (media?.kind === 'video') return <video src={media.url + '#t=0.1'} preload="metadata" muted playsInline tabIndex={-1} aria-hidden="true"/>;
  return <Icon name={RUNG_ICON[step.key]} size={16}/>;
}
export function MediaLadder({steps, onOpen, onPlan, output = 'video', onOutput = null}) {
  useLocale();
  if (!steps.length) return null;
  if (onOutput) return <OutputSwitch steps={steps} output={output} onOutput={onOutput}/>;
  const planned = steps.some(step => step.key === 'previs' && !step.media);
  return <div className="shot-ladder">
    <ol aria-label={t('stage.ladder')}>
      {steps.map((step, index) => <li key={step.key} className={step.media ? 'is-made' : 'is-todo'}>
        <button type="button" title={t('stage.ladderOpen_' + step.key)} onClick={() => onOpen(step)}>
          <span className="ladder-thumb"><RungThumb step={step}/></span>
          <span className="ladder-cap">{step.media ? <Icon name="check" size={11}/> : null}{t('stage.ladder_' + step.key)}{!step.media && <small>{t('stage.ladderEmpty')}</small>}</span>
        </button>
        {index < steps.length - 1 && <Icon name="arrowRight" size={13} className="ico ladder-arrow"/>}
      </li>)}
    </ol>
    {planned && <p className="ladder-note">{t('stage.noPrevis')}<button type="button" className="quiet" onClick={onPlan}>{t('stage.planPrevis')}</button></p>}
  </div>;
}

// The output switch: what the composer makes next. A rung the sheet has no column for is not offered.
function OutputSwitch({steps, output, onOutput}) {
  const rungs = ['frame', 'video'].map(key => steps.find(step => step.key === key)).filter(Boolean);
  if (!rungs.length) return null;
  return <div className="studio-segmented shot-output" role="group" aria-label={t('composer.output')}>
    {rungs.map(step => <button key={step.key} type="button" aria-pressed={output === step.key} title={step.media ? t('composer.outputMade', {output:t('stage.ladder_' + step.key)}) : t('stage.ladder_' + step.key)}
      onClick={() => onOutput(step.key)}><Icon name={RUNG_ICON[step.key]} size={13}/>{t('stage.ladder_' + step.key)}{step.media && <Icon name="check" size={11} className="ico shot-output-made"/>}</button>)}
  </div>;
}

import { semanticEnumKey } from './writing/writingModel.js';

// Only the live writing/alignment projection is freshness authority (never cached shot_meta).
export function ShotSourceBadge({alignment, shotId, onSource}) {
  useLocale();
  const item = alignment?.items.find(item => item.shotId === shotId);
  if (!item) return <p role="status">{t('writing.integration.alignmentUnavailable')}</p>;
  return <section className="shot-source" aria-label={t('writing.integration.storySource')}>
    <b>{t('writing.authoring.' + semanticEnumKey('alignment', item.storyAlignment.state))}</b>
    {item.storyAlignment.mediaOutdated && <p>{t('writing.integration.oldMedia')}</p>}
    {item.sourceRef && <button type="button" onClick={() => onSource?.(item.sourceRef)}>{t('writing.authoring.backToSource')}</button>}
  </section>;
}

// SPEC_19 R7: the Shot Stage's views live in one "View" menu instead of a row of standing buttons. views: [{key, label, icon}]; the
// current one names the button. settings: the view's own settings (the overview's cover and grouping), at the foot of the menu.
// Arrow keys move through the views, Escape closes the menu and returns to its button.
export function StageViewMenu({views, mode, disabled = false, onPick, settings = null, defaultOpen = false}) {
  useLocale();
  const [open, setOpen] = useState(defaultOpen);
  const root = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const away = event => {if (!root.current?.contains(event.target)) setOpen(false);};
    document.addEventListener('mousedown', away);
    root.current?.querySelector('[aria-checked="true"]')?.focus();
    return () => document.removeEventListener('mousedown', away);
  }, [open]);
  const current = views.find(view => view.key === mode) || views[0];
  const keys = event => {
    if (!open) return;
    if (event.key === 'Escape') {event.preventDefault(); event.stopPropagation(); setOpen(false); root.current?.querySelector('.stage-view-btn')?.focus();}
    else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      const items = [...root.current.querySelectorAll('[role="menuitemradio"]')], at = items.indexOf(document.activeElement);
      event.preventDefault(); event.stopPropagation(); items[(at + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus();
    }
  };
  return <div className="stage-view-menu" ref={root} onKeyDown={keys}>
    <button type="button" className="stage-view-btn" aria-haspopup="menu" aria-expanded={open} disabled={disabled} title={t('composer.viewHint')} onClick={() => setOpen(value => !value)}>
      <span className="stage-view-label">{t('composer.view')}</span>{current && <Icon name={current.icon} size={14}/>}<b>{current?.label}</b><Icon name="chevronDown" size={13}/></button>
    {open && <div className="studio-menu stage-view-list" role="menu" aria-label={t('composer.views')}>
      {views.map(view => <button key={view.key} type="button" role="menuitemradio" aria-checked={view.key === mode} onClick={() => {setOpen(false); onPick(view.key);}}>
        <Icon name={view.icon}/><span className="studio-menu-name">{view.label}</span></button>)}
      {settings && <div className="stage-view-settings" role="group" aria-label={t('composer.viewSettings')}><p className="studio-menu-foot">{t('composer.viewSettings')}</p>{settings}</div>}
    </div>}
  </div>;
}

// SPEC_15 Shot Stage: the storyboard, the 3D stage and review are views of one shot list, not three stations.
const cover = (parsed, row) => mediaStages(parsed, row).filter(stage => stage.media).find(stage => stage.type === 'image') || null;

// Each shot shows what it is doing in the film (SPEC_19 4.1: generating, new take, adopted, ...), derived from the table status, the
// shot view and the rows with a running task (inFlight, a Set of row ids); the table's own status words stay in the table.
export function ShotList({parsed, rows, statusColumn, shotInfo, scenes, currentRid, filter, onFilter, onPick, inFlight = null}) {
  useLocale();
  const status = row => statusColumn < 0 ? '' : row.cells[statusColumn]?.value || '';
  const entry = row => ({status:status(row), info:shotInfo[row.rid], inFlight:Boolean(inFlight?.has(row.rid))});
  const stateOf = row => shotStateOf({...(shotInfo[row.rid] || {}), reviewStatus:status(row)}, {inFlight:Boolean(inFlight?.has(row.rid))});
  const shown = rows.filter(row => SHOT_FILTERS[filter](entry(row)));
  const titles = Object.fromEntries(scenes.map(scene => [scene.sceneId, scene.title]));
  const groups = [];
  for (const row of shown) {
    const key = shotInfo[row.rid]?.sceneId || '';
    if (groups.at(-1)?.key !== key) groups.push({key, rows:[]});
    groups.at(-1).rows.push(row);
  }
  return <nav className="shot-list" aria-label={t('stage.shotList')}>
    <div className="space-list-head"><b>{t('stage.shots')}</b><span className="num">{rows.length}</span></div>
    <div className="shot-filters" role="group" aria-label={t('stage.filter')}>
      {Object.keys(SHOT_FILTERS).map(key => {
        const count = rows.filter(row => SHOT_FILTERS[key](entry(row))).length;
        return (key === 'all' || count > 0) && <button key={key} type="button" aria-pressed={filter === key} onClick={() => onFilter(key)}>{t('stage.filter_' + key)} <span className="num">{count}</span></button>;
      })}
    </div>
    {groups.map(group => <section key={group.key || 'none'}>
      {group.key && <h3>{titles[group.key] || group.key}</h3>}
      <ol>{group.rows.map(row => {
        const image = cover(parsed, row), state = stateOf(row);
        return <li key={row.rid}><button type="button" aria-current={row.rid === currentRid ? 'true' : undefined} onClick={() => onPick(row.rid)}>
          <span className="shot-list-thumb">{image ? <img src={image.media.url} alt="" loading="lazy"/> : <span className="shot-list-blank"/>}</span>
          <span className="shot-list-text"><b>{String(row.cells[0]?.value || '—')}</b><small>{t('take.state_' + state)}</small></span>
          <span className={'shot-dot state-' + state} aria-hidden="true"/>
        </button></li>;
      })}</ol>
    </section>)}
    {!shown.length && <p className="space-empty">{t('stage.noShots')}</p>}
    <p className="space-foot">{t('stage.shortcuts')}</p>
  </nav>;
}

// The previs and the take of one shot, played together on one clock, with the camera-fidelity score between them.
export function ShotCompare({parsed, row}) {
  useLocale();
  const at = re => parsed.headers.findIndex(header => re.test(header)), types = parsed.table.attrs.column_types || [];
  const video = column => column < 0 ? null : mediaOf(row.cells[column]?.value, types[column])?.url || null;
  const previs = video(at(/previs|blockout/i)), take = video(at(/cinema shot|remaster|output/i));
  const left = useRef(null), right = useRef(null);
  const [time, setTime] = useState(0), [length, setLength] = useState(0), [playing, setPlaying] = useState(false);
  useEffect(() => {setTime(0); setPlaying(false);}, [row.rid]);
  const both = fn => [left.current, right.current].filter(Boolean).forEach(fn);
  const toggle = () => {
    if (playing) {both(v => v.pause()); setPlaying(false); return;}
    both(v => {v.currentTime = Math.min(time, v.duration || time); v.play().catch(() => {});}); setPlaying(true);
  };
  const seek = value => {setTime(value); both(v => {v.currentTime = Math.min(value, v.duration || value);});};
  if (!previs && !take) return <div className="sheet-empty"><p>{t('stage.compareEmpty')}</p></div>;
  return <section className="shot-compare" aria-label={t('stage.view_compare')}>
    <div className="shot-compare-pair">
      {[[previs, left, t('stage.previs')], [take, right, t('stage.take')]].map(([url, ref, label]) => <figure key={label}>
        {url ? <video ref={ref} src={url} muted playsInline preload="metadata" onLoadedMetadata={event => {const seconds = event.currentTarget.duration || 0; setLength(value => Math.max(value, seconds));}}
          onTimeUpdate={ref === left || !previs ? event => setTime(event.currentTarget.currentTime) : undefined} onEnded={() => setPlaying(false)}/>
          : <div className="shot-compare-missing">{t('stage.notYet')}</div>}
        <figcaption>{label}</figcaption></figure>)}
    </div>
    <div className="shot-compare-clock">
      <button type="button" className="shot-play" aria-label={playing ? t('stage.pause') : t('stage.playBoth')} onClick={toggle}>{playing ? '❚❚' : '▶'}</button>
      <input type="range" min={0} max={length || 0} step={0.04} value={Math.min(time, length || 0)} aria-label={t('stage.scrub')} onChange={event => seek(Number(event.target.value))}/>
      <span className="num">{time.toFixed(1)} / {length.toFixed(1)}s</span>
    </div>
    {previs && take && <CameraFidelity previs={previs} take={take}/>}
  </section>;
}
