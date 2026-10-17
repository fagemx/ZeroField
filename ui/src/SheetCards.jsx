import { MediaCell } from './MediaCell.jsx';
import { statusOptions } from './sheetViews.js';

export function SheetCards({model, mode, selected, onSelect, onOpen, onPreview, onStatus, writable, busy, parsed}) {
  const card = (item) => {
    const {row, index, title, cover, summary} = item;
    const column = model.groupColumn;
    const value = String(row.cells[column]?.value ?? '');
    const options = column < 0 ? [] : statusOptions(parsed, column, row);
    return <article role="listitem" key={row.rid} className={`sheet-card${selected.has(row.rid) ? ' is-selected' : ''}`}>
      {model.coverColumn >= 0 && (cover ? <div className="sheet-card-cover"><MediaCell compact value={cover.value} type="image" label={`${title} · ${parsed.headers[cover.column]}`} onLightbox={media => onPreview({...media, r: index, c: cover.column})} /></div>
        : <div className="sheet-card-cover empty-cover"><span>尚無圖片</span></div>)}
      <div className="sheet-card-body"><div className="sheet-card-heading">
        <input type="checkbox" aria-label={`選取 ${title}`} checked={selected.has(row.rid)} onChange={event => onSelect(row.rid, event.target.checked)} />
        <button className="sheet-card-title" onClick={() => onOpen(row.rid)} title="查看整列、討論與紀錄">{title}</button>
        <span className="sheet-card-index">{index + 1}</span>
      </div>
        <dl className="sheet-card-summary">{summary.map((field, i) => <div key={i}><dt>{field.label}</dt><dd title={String(field.value)}>{field.value}</dd></div>)}</dl>
        <div className="sheet-card-actions">{column >= 0 && <select aria-label={`${parsed.headers[column]} · ${title}`} value={value} disabled={!writable || busy} onChange={event => onStatus(row.rid, column, event.target.value)}>
          <option value="" disabled={row.cells[column]?.kind === 'status'}>未設定</option>
          {value && !options.includes(value) && <option value={value} disabled>{value}</option>}
          {options.map(option => <option key={option}>{option}</option>)}
        </select>}<button className="quiet" aria-label={`查看 ${title} 詳情`} onClick={() => onOpen(row.rid)}>詳情 ↗</button></div>
      </div>
    </article>;
  };
  if (mode === 'gallery') return <div className="sheet-gallery" role="list" aria-label="圖庫資料">{model.cards.map(card)}</div>;
  return <div className="sheet-board" aria-label="狀態看板">{model.groups.map(group => <section className="sheet-board-column" key={group.value} aria-label={`${group.label} · ${group.cards.length} 筆`}>
    <header><span className={`sheet-board-dot${group.value === '已完成' ? ' done' : ''}`} /><h2>{group.label}</h2><span>{group.cards.length}</span></header>
    <div role="list" aria-label={`${group.label} 的資料`}>{group.cards.map(card)}</div>
    {!group.cards.length && <p className="sheet-board-empty">尚無資料</p>}
  </section>)}</div>;
}
