import { useLocale } from './i18n/react.jsx';
import { t as uiText } from './i18n/index.js';
import { MediaCell } from './MediaCell.jsx';
import { statusOptions } from './sheetViews.js';
import { statusClass, statusLabel } from './format.js';

export function SheetCards({model, mode, selected, onSelect, onOpen, onPreview, onStatus, writable, busy, parsed}) {
  const locale = useLocale();
  const card = (item) => {
    const {row, index, title, cover, summary} = item;
    const column = model.groupColumn;
    const value = String(row.cells[column]?.value ?? '');
    const options = column < 0 ? [] : statusOptions(parsed, column, row);
    return <article role="listitem" key={row.rid} className={`sheet-card${selected.has(row.rid) ? ' is-selected' : ''}`}>
      {model.coverColumn >= 0 && (cover ? <div className="sheet-card-cover"><MediaCell compact value={cover.value} type="image" label={uiText("sheetCards.message", {v0: (title), v1: (parsed.headers[cover.column])})} onLightbox={media => onPreview({...media, r: index, c: cover.column})} /></div>
        : <div className="sheet-card-cover empty-cover"><span>{uiText("sheetCards.noImage")}</span></div>)}
      <div className="sheet-card-body"><div className="sheet-card-heading">
        <input type="checkbox" aria-label={uiText("sheetCards.select", {v0: (title)})} checked={selected.has(row.rid)} onChange={event => onSelect(row.rid, event.target.checked)} />
        <button className="sheet-card-title" onClick={() => onOpen(row.rid)} title={uiText("sheetCards.viewRowDetailsDiscussionAndHistory")}>{title}</button>
        <span className="sheet-card-index">{index + 1}</span>
      </div>
        <dl className="sheet-card-summary">{summary.map((field, i) => <div key={i}><dt>{field.label}</dt><dd title={String(field.value)}>{field.value}</dd></div>)}</dl>
        <div className="sheet-card-actions">{column >= 0 && <select aria-label={uiText("sheetCards.message", {v0: (parsed.headers[column]), v1: (title)})} value={value} disabled={!writable || busy} onChange={event => onStatus(row.rid, column, event.target.value)}>
          <option value="" disabled={row.cells[column]?.kind === 'status'}>{uiText("sheetCards.notConfigured")}</option>
          {value && !options.includes(value) && <option value={value} disabled>{statusLabel(value)}</option>}
          {options.map(option => <option key={option} value={option}>{statusLabel(option)}</option>)}
        </select>}<button className="quiet" aria-label={uiText("sheetCards.viewDetails", {v0: (title)})} onClick={() => onOpen(row.rid)}>{uiText("sheetCards.details")}</button></div>
      </div>
    </article>;
  };
  if (mode === 'gallery') return <div className="sheet-gallery" role="list" aria-label={uiText("sheetCards.galleryItems")}>{model.cards.map(card)}</div>;
  return <div className="sheet-board" aria-label={uiText("sheetCards.statusBoard")}>{model.groups.map(group => <section className="sheet-board-column" key={group.value} aria-label={uiText("sheetCards.items", {v0: (group.label), v1: (group.cards.length)})}>
    <header><span className={`sheet-board-dot${statusClass(group.value) === 'done' ? ' done' : ''}`} /><h2>{group.label}</h2><span>{group.cards.length}</span></header>
    <div role="list" aria-label={uiText("sheetCards.sData", {v0: (group.label)})}>{group.cards.map(card)}</div>
    {!group.cards.length && <p className="sheet-board-empty">{uiText("sheetCards.noData")}</p>}
  </section>)}</div>;
}
