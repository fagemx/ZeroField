import { useState } from 'react';
import { useLocale } from './i18n/react.jsx';
import { t } from './i18n/index.js';
import { statusClass, statusLabel } from './format.js';
import { KIND_FILTERS, UNSCENED, isWide } from './worldModel.js';
import { isActiveRun } from './generation/generationModel.js';
import { Icon } from './Icon.jsx';
import './world.css';

// SPEC_15 Story & World, "Cast & sets": the wall of what the script names (people, places, props), each card its reference image,
// name, look, status and the shots that use it. The left rail filters it; the card you pick opens in the large pane on the right (AssetEditor).
const pad = index => String(index).padStart(2, '0');
export const Status = ({value}) => value ? <span className={'world-status ' + statusClass(value)}><i aria-hidden="true"/>{statusLabel(value)}</span> : null;

// SPEC_18 R1: a picture is being made, failed, or was canceled. Said on the card and in the editor, in words, never only by colour.
const Spinner = () => <svg className="ico world-spin" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="9" opacity=".25"/><path d="M21 12a9 9 0 0 0-9-9"/></svg>;
export function RunState({run}) {
  useLocale();
  if (!run) return null;
  if (isActiveRun(run)) return <span className="world-run is-active" role="status"><Spinner/>{t('world.generating')}</span>;
  if (run.status === 'CANCELED') return <span className="world-run is-canceled" role="status">{t('world.canceled')}</span>;
  return <span className="world-run is-failed" role="alert"><Icon name="warning" size={13}/>{t('world.generationFailed')}{run.error && <small>{run.error}</small>}</span>;
}

function Art({item, run}) {
  return <span className={'world-art' + (isWide(item.type) ? ' is-wide' : '') + (isActiveRun(run) ? ' is-busy' : '')}>
    {item.selectedImageUrl ? <img src={item.selectedImageUrl} alt="" loading="lazy"/>
      : <span className="world-art-empty"><Icon name="image" size={20}/>{t('world.needsImage')}</span>}
    <Status value={item.status}/>
    {item.uses.length > 0 && <span className="world-uses">{t('shell.shotCount', {count:item.uses.length})}</span>}
    {item.looks?.missingImages > 0 && !isActiveRun(run) && <span className="world-lookbadge">{t('world.lookBadge', {count:item.looks.missingImages})}</span>}
    <RunState run={run}/>
  </span>;
}

// The cancel and retry buttons sit beside the card button (a button cannot hold a button), laid over the picture's corner.
function Card({item, active, run, onPick, onCancel, onRetry}) {
  const button = (isActiveRun(run) && run.taskId) || run?.status === 'FAILED';
  return <li id={'world-card-' + item.assetId} className={run ? 'has-run' + (button ? ' has-btn' : '') : undefined}>
    <button type="button" className="world-card" aria-pressed={active} onClick={() => onPick(item.assetId)}>
      <Art item={item} run={run}/>
      <span className="world-card-text"><b>{item.name || item.assetCode}</b><small>@{item.assetCode}</small>
        {item.prompt && <span className="world-desc">{item.prompt}</span>}</span>
    </button>
    {isActiveRun(run) && run.taskId && <button type="button" className="world-run-btn" aria-label={t('world.cancelGeneration') + ': ' + (item.name || item.assetCode)} onClick={() => onCancel(item.assetId)}>{t('common.cancel')}</button>}
    {run?.status === 'FAILED' && <button type="button" className="world-run-btn" aria-label={t('world.retry') + ': ' + (item.name || item.assetCode)} onClick={() => onRetry(item.assetId)}>{t('world.retry')}</button>}
  </li>;
}

function NewForm({type, disabled, onCreate, onClose}) {
  const [name, setName] = useState(''), [prompt, setPrompt] = useState('');
  return <form className="world-new" onSubmit={async event => {event.preventDefault(); if (await onCreate(type, name.trim(), prompt.trim())) onClose();}}>
    <label className="modal-field">{t('world.newName')}<input value={name} required maxLength={120} autoFocus disabled={disabled} onChange={event => setName(event.target.value)}/></label>
    <label className="modal-field">{t('world.appearance')}<textarea rows={3} value={prompt} maxLength={4000} disabled={disabled} onChange={event => setPrompt(event.target.value)}/></label>
    <div className="world-actions"><button type="submit" className="world-act" disabled={disabled || !name.trim()}>{t('world.create')}</button>
      <button type="button" className="world-tool" onClick={onClose}>{t('common.cancel')}</button></div>
  </form>;
}

function Group({group, activeId, writable, disabled, runs, onPick, onCreate, onCancel, onRetry}) {
  const [adding, setAdding] = useState(false);
  return <section className="world-group" aria-labelledby={'world-group-' + group.type}>
    <h2 id={'world-group-' + group.type}>{t('world.group_' + group.type)}<span className="num">{group.items.length}</span></h2>
    {adding && <NewForm type={group.type} disabled={disabled} onCreate={onCreate} onClose={() => setAdding(false)}/>}
    {group.items.length || writable ? <ul className={'world-cards' + (isWide(group.type) ? ' is-wide' : '')}>
      {group.items.map(item => <Card key={item.assetId} item={item} active={item.assetId === activeId} run={runs[item.assetId]} onPick={onPick} onCancel={onCancel} onRetry={onRetry}/>)}
      {writable && !adding && <li><button type="button" className="world-add" onClick={() => setAdding(true)}><Icon name="plus" size={18}/><span>{t('world.add_' + group.type)}</span></button></li>}</ul>
      : <p className="world-none">{t('world.groupEmpty')}</p>}
  </section>;
}

// The left rail while the wall is open: type filters with their counts ("needs an image" appears only while something does).
export function WorldFacets({facets, facet, onFacet}) {
  useLocale();
  return <ul className="world-facets">{facets.filter(item => item.key !== 'missing' || item.count > 0).map(item => <li key={item.key}>
    <button type="button" aria-current={facet === item.key ? 'true' : undefined} onClick={() => onFacet(item.key)}>
      <span>{t('world.facet_' + item.key)}</span><b className="num">{item.count}</b></button></li>)}</ul>;
}

// SPEC_18 R5: "Scene: All | the scene in focus | Unscened". Shown only when there is a choice to make. A scene you picked stays on the
// row even after the focus moves on, so the wall never silently changes which scene it is showing.
export function SceneFilter({choices, scene, onScene}) {
  useLocale();
  if (choices.length < 2) return null;
  const label = choice => choice.key === null ? t('world.sceneAll') : choice.key === UNSCENED ? t('world.sceneUnscened') : choice.label;
  return <div className="world-scene-filter" role="group" aria-label={t('world.sceneFilter')}>
    <span>{t('world.sceneLabel')}</span>
    <div className="studio-segmented small">{choices.map(choice => <button key={choice.key ?? 'all'} type="button" aria-pressed={scene === choice.key} onClick={() => onScene(choice.key)}>{label(choice)}</button>)}</div>
  </div>;
}

export function WorldWall({groups, counts, total, filtered = false, activeId, ready, writable, disabled, missingCount, canGenerate, generateHint, generation, runs = {}, sceneChoices = [], scene = null,
  onPick, onCreate, onGenerateMissing, onTable, onCancel, onRetry, onScene}) {
  useLocale();
  return <>
    <header className="space-head"><h1>{t('world.worldTitle')}</h1><span className="space-sub">{t('world.summary', counts)}</span><span className="spacer"/>
      <button type="button" className="world-tool" onClick={onTable}><Icon name="table" size={14}/>{t('world.openSheet')}</button></header>
    <SceneFilter choices={sceneChoices} scene={scene} onScene={onScene}/>
    {missingCount > 0 && <div className="world-banner" role="status"><span>{t('story.missingAssetCount', {count:missingCount})}</span>
      {writable && <button type="button" className="world-act" disabled={!canGenerate} title={generateHint} onClick={onGenerateMissing}>{t('story.generateMissingAssets')} ({missingCount})</button>}</div>}
    {generation}
    {!ready ? <p role="status">{t('story.importLoading')}</p> : <div className="world-wall">
      {total === 0 && <p className="world-empty" role="status">{t(filtered ? 'world.sceneEmpty' : 'world.emptyWall')}</p>}
      {groups.map(group => <Group key={group.type} group={group} activeId={activeId} writable={writable} disabled={disabled} runs={runs} onPick={onPick} onCreate={onCreate} onCancel={onCancel} onRetry={onRetry}/>)}
    </div>}
  </>;
}

// The right column while the script is open: a quick list of the same assets; a card opens the wall on it.
export function WorldList({items, kind, onKind, focusCode, onOpen}) {
  useLocale();
  const shown = items.filter(KIND_FILTERS[kind]);
  return <>
    <div className="space-detail-head"><b>{t('world.world')}</b>
      <div className="studio-segmented small" role="group" aria-label={t('world.assetKind')}>
        {Object.keys(KIND_FILTERS).map(key => <button key={key} type="button" aria-pressed={kind === key} onClick={() => onKind(key)}>{t('world.kind_' + key)}</button>)}
      </div></div>
    <ul className="world-assets">{shown.map(item => {
      const focused = focusCode && item.assetCode.split(':')[0] === focusCode.split(':')[0];
      return <li key={item.assetId} id={'world-asset-' + item.assetId} className={(item.needsImage ? 'is-missing ' : '') + (focused ? 'is-focus' : '')}>
        <button type="button" className="world-asset" title={t('world.openInWall', {name:item.name || item.assetCode})} onClick={() => onOpen(item)}>
          <span className="world-thumb">{item.selectedImageUrl ? <img src={item.selectedImageUrl} alt="" loading="lazy"/> : <span className="world-blank"/>}</span>
          <span className="world-asset-text"><b>{item.name || item.assetCode}</b><small>@{item.assetCode}</small>
            {item.prompt && <span className="world-desc">{item.prompt}</span>}
            <span className="world-asset-meta"><Status value={item.status}/>{item.needsImage && <em>{t('world.needsImage')}</em>}
              {item.uses.length > 0 && <small>{t('shell.shotCount', {count:item.uses.length})}</small>}</span></span>
        </button></li>;
    })}{!shown.length && <li className="space-empty">{t('world.noAssets')}</li>}</ul>
  </>;
}

// With no card open the right pane says how the wall fills; picking a card swaps it for the editor.
export function WorldSummary({withImages, total}) {
  useLocale();
  return <section className="world-inspector world-summary">
    <h2>{t('world.worldTitle')}</h2>
    <p className="space-sub">{total ? t('world.pickCard') : t('world.emptyWall')}</p>
    {total > 0 && <p className="space-sub">{t('world.readyCount', {ready:withImages, total})}</p>}
  </section>;
}
