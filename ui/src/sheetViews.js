import { t as uiText } from './i18n/index.js';
import { evaluate, mediaOf, tableEditPayload } from './sheetModel.js';
import { STATUSES, LEGACY_STATUSES, statusLabel, normalizeStatus } from './format.js';

const MODES = ['grid', 'gallery', 'kanban'];
const COMMON_STATUSES = STATUSES;

function viewColumns(parsed) {
  const types = parsed.table.attrs.column_types || [];
  const columns = parsed.headers.map((label, index) => ({label, index}));
  return {
    statusColumns: columns.filter(({index}) => types[index] === 'status' || parsed.rows.some(row => row.cells[index]?.kind === 'status')),
    coverColumns: columns.filter(({index}) => types[index] === 'image' || parsed.rows.some(row => mediaOf(row.cells[index]?.value, types[index])?.kind === 'image')),
  };
}

export function statusOptions(parsed, column, row) {
  const existing = parsed.rows.map(r => String(r.cells[column]?.value ?? '')).filter(Boolean);
  const configured = parsed.table.attrs.column_options?.[parsed.table.attrs.column_ids?.[column]]?.options;
  const options = [...new Set([...(configured?.length ? configured : COMMON_STATUSES), ...existing])];
  return row?.cells[column]?.kind === 'status' ? options.filter(value => STATUSES.includes(value) || value in LEGACY_STATUSES) : options;
}

export function sheetViewModel(parsed, visibleRows, preferences = {}) {
  const {statusColumns, coverColumns} = viewColumns(parsed);
  const groupColumn = statusColumns.some(c => c.index === preferences.groupColumn) ? preferences.groupColumn : statusColumns[0]?.index ?? -1;
  const coverColumn = preferences.coverColumn === -1 ? -1 : coverColumns.some(c => c.index === preferences.coverColumn) ? preferences.coverColumn : coverColumns[0]?.index ?? -1;
  const indexById = new Map(parsed.rows.map((row, index) => [row.rid, index]));
  const cards = visibleRows.filter(row => indexById.has(row.rid)).map(row => {
    const index = indexById.get(row.rid);
    const media = coverColumn < 0 ? null : mediaOf(row.cells[coverColumn]?.value, 'image');
    return {
      row, index, title: String(row.cells[0]?.value || uiText("sheetViews.row", {v0: (index + 1)})),
      cover: media?.kind === 'image' ? {...media, column: coverColumn, value: row.cells[coverColumn].value} : null,
      summary: row.cells.flatMap((cell, c) => c === 0 || c === coverColumn || statusColumns.some(s => s.index === c) || mediaOf(cell.value, parsed.table.attrs.column_types?.[c]) || !String(cell.value ?? '').trim() ? [] : [{
        label: parsed.headers[c], value: evaluate(cell.value, parsed.rows, new Set(), parsed.table.attrs.worksheet_name ? parsed.table.attrs.source_header_row || 1 : 0),
      }]).slice(0, 3),
    };
  });
  const groups = new Map();
  if (groupColumn >= 0) {
    for (const value of statusOptions(parsed, groupColumn)) groups.set(value, {value, label: statusLabel(value), cards: []});
    for (const card of cards) {
      const value = String(card.row.cells[groupColumn]?.value ?? '');
      if (!groups.has(value)) groups.set(value, {value, label: statusLabel(value) || uiText("sheetViews.notConfigured"), cards: []});
      groups.get(value).cards.push(card);
    }
  }
  return {statusColumns, coverColumns, groupColumn, coverColumn, cards, groups: [...groups.values()]};
}

export function statusMovePayload(parsed, rowId, column, value) {
  const rowIndex = parsed.rows.findIndex(row => row.rid === rowId);
  if (rowIndex < 0) throw new Error(uiText("sheetViews.thisRowNoLongerExistsRefreshThePage"));
  if (!viewColumns(parsed).statusColumns.some(c => c.index === column)) throw new Error(uiText("sheetViews.selectAStatusColumnFirst"));
  const row = parsed.rows[rowIndex];
  const options = statusOptions(parsed, column, row);
  if (!(value === '' && row.cells[column]?.kind !== 'status') && !options.includes(value) && !(value in LEGACY_STATUSES && options.includes(normalizeStatus(value)))) throw new Error(uiText("sheetViews.chooseAValidStatusOption"));
  return tableEditPayload(parsed, rowIndex, column, [[value]]);
}

function signature(parsed) {
  return JSON.stringify([parsed.headers, parsed.table.attrs.column_types || [], viewColumns(parsed).statusColumns.map(c => c.index)]);
}

export function viewPreferences(parsed, preferences) {
  return {...preferences, signature: signature(parsed)};
}

export function restoreViewPreferences(raw, parsed) {
  try {
    const data = JSON.parse(raw);
    const mode = MODES.includes(data?.mode) ? data.mode : 'grid';
    if (!data || data.signature !== signature(parsed)) return {mode};
    const {statusColumns, coverColumns} = viewColumns(parsed);
    return {mode,
      ...(data.coverColumn === -1 || coverColumns.some(c => c.index === data.coverColumn) ? {coverColumn: data.coverColumn} : {}),
      ...(statusColumns.some(c => c.index === data.groupColumn) ? {groupColumn: data.groupColumn} : {}),
    };
  } catch { return {mode: 'grid'}; }
}
