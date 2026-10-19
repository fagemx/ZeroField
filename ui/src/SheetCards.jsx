import { useLocale } from './i18n/react.jsx';
import { t as uiText } from './i18n/index.js';
import { MediaCell } from './MediaCell.jsx';
import { statusOptions } from './sheetViews.js';
import { statusClass, statusLabel } from './format.js';

export function SheetCards({model, mode, selected, onSelect, onOpen, onPreview, onStatus, writable, busy, parsed, onUpload, onRunStep, onVariant, onRebuildScene, scenes=[], shotInfo={}}) {
  const locale = useLocale();
  const card = (item) => {
    const {row, index, title, cover, summary} = item;
    const column = model.groupColumn;
    const value = String(row.cells[column]?.value ?? '');
    const options = column < 0 ? [] : statusOptions(parsed, column, row);
    return <article role="listitem" key={row.rid} className={`sheet-card${selected.has(row.rid) ? ' is-selected' : ''}`}>
      {item.mediaChain?.length > 1 ? <div className="sheet-card-chain">{item.assets?.length>0&&<div className="sheet-chain-part"><div className="sheet-chain-stage sheet-chain-assets">{item.assets.map(asset=><div key={asset.id}>{asset.value?<MediaCell compact value={asset.value} type={asset.type} label={'@'+asset.id} onLightbox={media=>onPreview({...media,label:'@'+asset.id})}/>:<div className="sheet-chain-empty">@{asset.id}</div>}<small>@{asset.id}</small></div>)}</div><span className="sheet-chain-arrow" aria-hidden="true">→</span></div>}{item.mediaChain.map((stage, at) => <div className="sheet-chain-part" key={stage.column}>
        {at > 0 && <span className="sheet-chain-arrow" aria-hidden="true">→</span>}<div className="sheet-chain-stage">
          {stage.media ? <MediaCell compact value={stage.value} type={stage.type} label={title + ' · ' + stage.label} onLightbox={media => onPreview({...media, r:index, c:stage.column})} /> : <div className="sheet-chain-empty">{uiText('studio.emptyStage')}</div>}
          <small>{stage.label}</small>{writable && <div className="sheet-stage-actions"><button disabled={busy} onClick={() => onUpload?.(index,stage.column)}>{uiText('sheetWorkspace.upload')}</button><button disabled={busy} onClick={() => onRunStep?.(row.rid,stage)}>{uiText('studio.runStage')}</button></div>}
        </div></div>)}</div> : model.coverColumn >= 0 && (cover ? <div className="sheet-card-cover"><MediaCell compact value={cover.value} type={cover.kind || parsed.table.attrs.column_types?.[cover.column]} label={uiText("sheetCards.message", {v0: (title), v1: (parsed.headers[cover.column])})} onLightbox={media => onPreview({...media, r: index, c: cover.column})} /></div>
        : <div className="sheet-card-cover empty-cover"><span>{uiText('studio.emptyStage')}</span></div>)}
      <div className="sheet-card-body"><div className="sheet-card-heading">
        <input type="checkbox" aria-label={uiText("sheetCards.select", {v0: (title)})} checked={selected.has(row.rid)} onChange={event => onSelect(row.rid, event.target.checked)} />
        <button className="sheet-card-title" onClick={() => onOpen(row.rid)} title={uiText("sheetCards.viewRowDetailsDiscussionAndHistory")}>{title}</button>
        <span className="sheet-card-index">{index + 1}</span>
      </div>
        {shotInfo[row.rid]?.complexity && <span className="story-tier-badge">{uiText('allocation.complexity_'+shotInfo[row.rid].complexity.complexity_tier)}{shotInfo[row.rid].allocation && <> · {uiText('allocation.tier_'+shotInfo[row.rid].allocation.tier)} · {shotInfo[row.rid].allocation.assigned_card_id}</>}</span>}
        <div className="card-asset-chips">{item.assets?.map(asset => <span key={asset.id} className="card-asset-chip">{item.mediaChain?.length<=1&&asset.value && <MediaCell compact value={asset.value} type={asset.type} label={'@' + asset.id} onLightbox={media => onPreview({...media, label:'@' + asset.id})} />}{asset.variants?.length>1 ? <button disabled={!writable||busy} title={uiText('story.cycleVariant')} onClick={() => onVariant?.(row,asset.id,asset.variants[(asset.variants.indexOf(asset.id)+1)%asset.variants.length])}>@{asset.id} ↻</button> : <small>@{asset.id}</small>}</span>)}</div>
        <dl className="sheet-card-summary">{summary.map((field, i) => <div key={i}><dt>{field.label}</dt><dd title={String(field.value)}>{field.value}</dd></div>)}</dl>
        <div className="sheet-card-actions">{column >= 0 && <select aria-label={uiText("sheetCards.message", {v0: (parsed.headers[column]), v1: (title)})} value={value} disabled={!writable || busy} onChange={event => onStatus(row.rid, column, event.target.value)}>
          <option value="" disabled={row.cells[column]?.kind === 'status'}>{uiText("sheetCards.notConfigured")}</option>
          {value && !options.includes(value) && <option value={value} disabled>{statusLabel(value)}</option>}
          {options.map(option => <option key={option} value={option}>{statusLabel(option)}</option>)}
        </select>}<button className="quiet" aria-label={uiText("sheetCards.viewDetails", {v0: (title)})} onClick={() => onOpen(row.rid)}>{uiText("sheetCards.details")}</button></div>
      </div>
    </article>;
  };
  if (mode === 'gallery' && model.sceneGroups?.length) return <div className="story-scene-groups">{model.sceneGroups.map(group => {
    const scene = scenes.find(s => 'SC'+String(s.sceneIndex).padStart(2,'0') === group.key || s.sceneId === group.key);
    return <details open key={group.key} className="story-scene"><summary>{scene?.title || group.key || uiText('story.ungrouped')} · {uiText('story.shotCount',{count:group.cards.length})}</summary>
      {scene && writable && <button disabled={busy} onClick={() => onRebuildScene?.(scene.sceneId)}>{uiText('story.rebuildScene')}</button>}
      <div className="sheet-gallery" role="list" aria-label={scene?.title || group.key}>{group.cards.map(card)}</div></details>;
  })}</div>;
  if (mode === 'gallery') return <div className="sheet-gallery" role="list" aria-label={uiText("sheetCards.galleryItems")}>{model.cards.map(card)}</div>;
  return <div className="sheet-board" aria-label={uiText("sheetCards.statusBoard")}>{model.groups.map(group => <section className="sheet-board-column" key={group.value} aria-label={uiText("sheetCards.items", {v0: (group.label), v1: (group.cards.length)})}>
    <header><span className={`sheet-board-dot${statusClass(group.value) === 'done' ? ' done' : ''}`} /><h2>{group.label}</h2><span>{group.cards.length}</span></header>
    <div role="list" aria-label={uiText("sheetCards.sData", {v0: (group.label)})}>{group.cards.map(card)}</div>
    {!group.cards.length && <p className="sheet-board-empty">{uiText("sheetCards.noData")}</p>}
  </section>)}</div>;
}
