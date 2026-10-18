import { MediaCell } from './MediaCell.jsx';
import { statusOptions } from './sheetViews.js';
import { statusClass, statusLabel } from './format.js';

export function SheetCards({model, mode, selected, onSelect, onOpen, onPreview, onStatus, writable, busy, parsed}) {
  const card = (item) => {
    const {row, index, title, cover, summary} = item;
    const column = model.groupColumn;
    const value = String(row.cells[column]?.value ?? '');
    const options = column < 0 ? [] : statusOptions(parsed, column, row);
    return <article role="listitem" key={row.rid} className={`sheet-card${selected.has(row.rid) ? ' is-selected' : ''}`}>
      {model.coverColumn >= 0 && (cover ? <div className="sheet-card-cover"><MediaCell compact value={cover.value} type="image" label={`${title} · ${parsed.headers[cover.column]}`} onLightbox={media => onPreview({...media, r: index, c: cover.column})} /></div>
        : <div className="sheet-card-cover empty-cover"><span>No Image</span></div>)}
      <div className="sheet-card-body"><div className="sheet-card-heading">
        <input type="checkbox" aria-label={`Select ${title}`} checked={selected.has(row.rid)} onChange={event => onSelect(row.rid, event.target.checked)} />
        <button className="sheet-card-title" onClick={() => onOpen(row.rid)} title={"View row details, discussion, and history"}>{title}</button>
        <span className="sheet-card-index">{index + 1}</span>
      </div>
        <dl className="sheet-card-summary">{summary.map((field, i) => <div key={i}><dt>{field.label}</dt><dd title={String(field.value)}>{field.value}</dd></div>)}</dl>
        <div className="sheet-card-actions">{column >= 0 && <select aria-label={`${parsed.headers[column]} · ${title}`} value={value} disabled={!writable || busy} onChange={event => onStatus(row.rid, column, event.target.value)}>
          <option value="" disabled={row.cells[column]?.kind === 'status'}>Not Configured</option>
          {value && !options.includes(value) && <option value={value} disabled>{statusLabel(value)}</option>}
          {options.map(option => <option key={option} value={option}>{statusLabel(option)}</option>)}
        </select>}<button className="quiet" aria-label={`View ${title} Details`} onClick={() => onOpen(row.rid)}>Details ↗</button></div>
      </div>
    </article>;
  };
  if (mode === 'gallery') return <div className="sheet-gallery" role="list" aria-label={"Gallery Items"}>{model.cards.map(card)}</div>;
  return <div className="sheet-board" aria-label={"Status Board"}>{model.groups.map(group => <section className="sheet-board-column" key={group.value} aria-label={`${group.label} · ${group.cards.length}  items`}>
    <header><span className={`sheet-board-dot${statusClass(group.value) === 'done' ? ' done' : ''}`} /><h2>{group.label}</h2><span>{group.cards.length}</span></header>
    <div role="list" aria-label={`${group.label} ’s data`}>{group.cards.map(card)}</div>
    {!group.cards.length && <p className="sheet-board-empty">No Data</p>}
  </section>)}</div>;
}
