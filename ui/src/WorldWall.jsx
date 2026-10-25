import { useEffect, useRef, useState } from 'react';
import { useLocale } from './i18n/react.jsx';
import { t } from './i18n/index.js';
import { statusClass, statusLabel } from './format.js';
import { KIND_FILTERS, isWide } from './worldModel.js';
import { Icon } from './Icon.jsx';
import './world.css';

// SPEC_15 Story & World, "Cast & sets": the wall of what the script names (people, places, props), each card its reference image,
// name, look, status and the shots that use it. The left rail filters it, the right column inspects the card in front of you.
const pad = index => String(index).padStart(2, '0');
const Status = ({value}) => value ? <span className={'world-status ' + statusClass(value)}><i aria-hidden="true"/>{statusLabel(value)}</span> : null;

function Art({item}) {
  return <span className={'world-art' + (isWide(item.type) ? ' is-wide' : '')}>
    {item.selectedImageUrl ? <img src={item.selectedImageUrl} alt="" loading="lazy"/>
      : <span className="world-art-empty"><Icon name="image" size={20}/>{t('world.needsImage')}</span>}
    <Status value={item.status}/>
    {item.uses.length > 0 && <span className="world-uses">{t('shell.shotCount', {count:item.uses.length})}</span>}
  </span>;
}

function Card({item, active, onPick}) {
  return <li id={'world-card-' + item.assetId}>
    <button type="button" className="world-card" aria-pressed={active} onClick={() => onPick(item.assetId)}>
      <Art item={item}/>
      <span className="world-card-text"><b>{item.name || item.assetCode}</b><small>@{item.assetCode}</small>
        {item.prompt && <span className="world-desc">{item.prompt}</span>}</span>
    </button>
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

function Group({group, activeId, writable, disabled, onPick, onCreate}) {
  const [adding, setAdding] = useState(false);
  return <section className="world-group" aria-labelledby={'world-group-' + group.type}>
    <h2 id={'world-group-' + group.type}>{t('world.group_' + group.type)}<span className="num">{group.items.length}</span></h2>
    {adding && <NewForm type={group.type} disabled={disabled} onCreate={onCreate} onClose={() => setAdding(false)}/>}
    {group.items.length || writable ? <ul className={'world-cards' + (isWide(group.type) ? ' is-wide' : '')}>
      {group.items.map(item => <Card key={item.assetId} item={item} active={item.assetId === activeId} onPick={onPick}/>)}
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

export function WorldWall({groups, counts, total, activeId, ready, writable, disabled, missingCount, canGenerate, generateHint, generation, onPick, onCreate, onGenerateMissing, onTable}) {
  useLocale();
  return <>
    <header className="space-head"><h1>{t('world.worldTitle')}</h1><span className="space-sub">{t('world.summary', counts)}</span><span className="spacer"/>
      <button type="button" className="world-tool" onClick={onTable}><Icon name="table" size={14}/>{t('world.openSheet')}</button></header>
    {missingCount > 0 && <div className="world-banner" role="status"><span>{t('story.missingAssetCount', {count:missingCount})}</span>
      {writable && <button type="button" className="world-act" disabled={!canGenerate} title={generateHint} onClick={onGenerateMissing}>{t('story.generateMissingAssets')} ({missingCount})</button>}</div>}
    {generation}
    {!ready ? <p role="status">{t('story.importLoading')}</p> : <div className="world-wall">
      {total === 0 && <p className="world-empty" role="status">{t('world.emptyWall')}</p>}
      {groups.map(group => <Group key={group.type} group={group} activeId={activeId} writable={writable} disabled={disabled} onPick={onPick} onCreate={onCreate}/>)}
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

function Lightbox({src, alt, onClose}) {
  useEffect(() => {
    const keys = event => {if (event.key === 'Escape') {event.stopPropagation(); onClose();}};
    window.addEventListener('keydown', keys, true);
    return () => window.removeEventListener('keydown', keys, true);
  }, [onClose]);
  return <div className="modal-scrim world-lightbox" onMouseDown={event => {if (event.target === event.currentTarget) onClose();}}>
    <img src={src} alt={alt}/>
    <button type="button" className="icon-btn" aria-label={t('world.closeImage')} onClick={onClose}><Icon name="close"/></button>
  </div>;
}

// The card in front of you, in full: its image and looks, what the script says about it, where it appears, and what you can do to it.
// Keyed by asset in the parent, so editing state never leaks from one card to the next.
export function AssetInspector({item, detail, scenes = [], writable, busy, onSave, onUpload, onGenerate, onOpenShot, onOpenScene, onTable, onVault}) {
  useLocale();
  const [editing, setEditing] = useState(false), [name, setName] = useState(item.name), [prompt, setPrompt] = useState(item.prompt);
  const [look, setLook] = useState(null), [zoom, setZoom] = useState(false);
  const file = useRef(null);
  const looks = detail?.variants || [], shown = looks.find(variant => variant.assetId === look) || null;
  const image = shown ? shown.selectedImageUrl : item.selectedImageUrl;
  const used = item.sceneIds.map(id => scenes.find(scene => scene.sceneId === id)).filter(Boolean);
  const wide = isWide(item.type);
  const fields = [['appearance', t('world.appearance'), item.prompt], ['voice', t('world.voice_' + item.type), item.voice], ['notes', t('world.notes'), item.notes]];
  return <section className="world-inspector" aria-label={item.name || item.assetCode}>
    <figure className={'world-hero' + (wide ? ' is-wide' : '')}>
      {image ? <button type="button" className="world-zoom" aria-label={t('world.enlarge')} onClick={() => setZoom(true)}><img src={image} alt={item.name}/></button>
        : <span className="world-art-empty"><Icon name="image" size={22}/>{shown ? t('world.lookNoImage') : t('world.needsImage')}</span>}
      {shown && <figcaption>{t('world.lookCaption', {name:shown.name, kind:shown.kind ? t('world.lookKind_' + shown.kind) : t('world.looks')})}</figcaption>}
    </figure>
    {looks.length > 0 && <div className="world-looks" role="group" aria-label={t('world.looks')}>
      {[{assetId:null, name:t('world.lookDefault'), selectedImageUrl:item.selectedImageUrl}, ...looks].map(variant =>
        <button key={variant.assetId || 'base'} type="button" aria-pressed={look === variant.assetId} title={variant.name} onClick={() => setLook(variant.assetId)}>
          {variant.selectedImageUrl ? <img src={variant.selectedImageUrl} alt=""/> : <span className="world-blank"/>}<span>{variant.name}</span></button>)}
    </div>}
    {writable && <div className="world-actions">
      <button type="button" className="world-act" disabled={busy} onClick={() => onGenerate(item.assetId)}>{item.selectedImageUrl ? t('world.regenerate') : t('world.generateHere')}</button>
      <button type="button" className="world-act" disabled={busy} onClick={() => file.current?.click()}><Icon name="arrowUp" size={14}/>{t('world.upload')}</button>
      <input ref={file} hidden type="file" accept="image/png,image/jpeg,image/webp,image/gif" aria-label={t('world.upload')}
        onChange={event => {const chosen = event.target.files?.[0]; event.target.value = ''; if (chosen) onUpload(item.assetId, chosen);}}/>
    </div>}
    <header className="world-title"><div><h2>{item.name || item.assetCode}</h2><small>@{item.assetCode}</small></div>
      <span className="world-type">{t('world.type_' + item.type)}</span><Status value={item.status}/></header>
    {editing ? <form className="world-edit" onSubmit={async event => {event.preventDefault(); if (await onSave(item.assetId, {name:name.trim(), prompt:prompt.trim()})) setEditing(false);}}>
      <label className="modal-field">{t('world.newName')}<input value={name} required maxLength={120} disabled={busy} onChange={event => setName(event.target.value)}/></label>
      <label className="modal-field">{t('world.appearance')}<textarea rows={7} value={prompt} maxLength={4000} disabled={busy} onChange={event => setPrompt(event.target.value)}/></label>
      <div className="world-actions"><button type="submit" className="world-act" disabled={busy || !name.trim()}>{t('common.save')}</button>
        <button type="button" className="world-tool" onClick={() => {setEditing(false); setName(item.name); setPrompt(item.prompt);}}>{t('common.cancel')}</button></div>
    </form> : <dl className="world-fields">
      {fields.map(([key, label, value]) => <div key={key} className={key === 'appearance' ? '' : 'is-short'}><dt>{label}</dt><dd className={value ? '' : 'is-unset'}>{value || t('world.unset')}</dd></div>)}
      {writable && <button type="button" className="world-tool world-edit-btn" onClick={() => {setName(item.name); setPrompt(item.prompt); setEditing(true);}}><Icon name="pencil" size={13}/>{t('world.edit')}</button>}
    </dl>}
    <section className="world-used" aria-label={t('world.uses')}>
      <h3>{t('world.uses')}</h3>
      {item.uses.length ? <>
        <p className="space-sub">{item.sceneIds.length ? t('story.assetUses', {shots:item.uses.length, scenes:item.sceneIds.length}) : t('world.usesShots', {shots:item.uses.length})}</p>
        <ul className="world-shots">{item.uses.map(shot => <li key={shot.shotId}><button type="button" title={t('world.openShot', {shot:shot.shotIndex})} onClick={() => onOpenShot(shot.rowId, shot.sceneId)}>
          {shot.selectedImageUrl ? <img src={shot.selectedImageUrl} alt="" loading="lazy"/> : <span className="world-blank"/>}<span>{shot.shotIndex}</span></button></li>)}</ul>
        {used.length > 0 && <p className="world-scenes">{used.map(scene => <button key={scene.sceneId} type="button" className="world-tool" onClick={() => onOpenScene(scene)}>
          {t('shell.sceneCrumb', {index:pad(scene.sceneIndex), title:scene.title})}</button>)}</p>}
      </> : <p className="space-sub">{t('world.usesNone')}</p>}
    </section>
    <div className="world-actions">
      <button type="button" className="world-tool" onClick={onVault}>{t('world.variants')}</button>
      <button type="button" className="world-tool" onClick={onTable}>{t('world.editInSheet')}</button>
    </div>
    {zoom && image && <Lightbox src={image} alt={item.name} onClose={() => setZoom(false)}/>}
  </section>;
}

// With nothing on the wall there is nothing to inspect; say how the wall fills.
export function WorldSummary({withImages, total}) {
  useLocale();
  return <section className="world-inspector world-summary">
    <h2>{t('world.worldTitle')}</h2>
    <p className="space-sub">{total ? t('world.pickCard') : t('world.emptyWall')}</p>
    {total > 0 && <p className="space-sub">{t('world.readyCount', {ready:withImages, total})}</p>}
  </section>;
}
