import { t as uiText } from './i18n/index.js';
export function nextCell(active, key, visibleRows, columns) {
  if (!visibleRows.length || !columns || !["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(key)) return null;
  let row = Math.max(0, visibleRows.indexOf(active.r));
  let col = active.c;
  if (key === "ArrowUp") row--;
  if (key === "ArrowDown") row++;
  if (key === "ArrowLeft") col--;
  if (key === "ArrowRight") col++;
  return {r: visibleRows[Math.max(0, Math.min(visibleRows.length - 1, row))], c: Math.max(0, Math.min(columns - 1, col))};
}

export function historyForRow(groups, rowId, tableId) {
  return groups.map((group) => ({...group, changes: (group.changes || [])
    .filter((change) => change.rid === rowId || change.anchor_id === rowId || (change.bid === tableId && !change.rid && !change.anchor_id))
    .map((change) => ({...change, tableWide: change.bid === tableId && !change.rid && !change.anchor_id}))
  })).filter((group) => group.changes.length);
}

export function sheetRequest(title, table, ids, instruction) {
  const picked = ids == null ? null : new Set(ids);
  const rows = table.rows.map((row, i) => ({...row, index: i + 1})).filter((row) => picked?.has(row.rid));
  if (picked && (!picked.size || rows.length !== picked.size)) throw new Error(uiText("sheetInteraction.theSelectedRowNoLongerExistsSelectAnotherRow"));
  const scope = picked ? uiText("sheetInteraction.selectedRows", {v0: (rows.length), v1: (rows.map((row) => uiText("sheetInteraction.row", {v0: (row.index), v1: (String(row.cells[0]?.value || uiText("sheetInteraction.untitled")).slice(0, 60))})).join(", "))}) : uiText("sheetInteraction.theEntireTable");
  const draft = uiText("sheetInteraction.readInAndProcessCheckTheLatestContentAnd", {v0: (table.name), v1: (title), v2: (scope), v3: (instruction.trim())});
  if (draft.length > 4000) throw new Error(uiText("sheetInteraction.theBriefAndSelectedRowsAreTooLongShorten"));
  return draft;
}

// Selections use source row/column indices, but their rectangle follows the view.
// A filtered or sorted view must never be converted to a source offset paste.
export function selectionRange(anchor, focus, visibleRows, visibleColumns) {
  const a = visibleRows.indexOf(anchor.r), b = visibleRows.indexOf(focus.r);
  const x = visibleColumns.indexOf(anchor.c), y = visibleColumns.indexOf(focus.c);
  if ([a,b,x,y].some(i => i < 0)) return {rows:[],columns:[]};
  return {rows:visibleRows.slice(Math.min(a,b),Math.max(a,b)+1),columns:visibleColumns.slice(Math.min(x,y),Math.max(x,y)+1)};
}

export function rangeTSV(parsed, range) {
  const quote = value => /[\t\n\r"]/.test(String(value)) ? `"${String(value).replaceAll('"','""')}"` : String(value);
  return range.rows.map(r => range.columns.map(c => quote(parsed.rows[r]?.cells[c]?.value ?? '')).join('\t')).join('\n');
}

export function visiblePastePayload(parsed, visibleIds, active, grid, visibleColumns = parsed.headers.map((_,i)=>i)) {
  const rowAt = visibleIds.indexOf(parsed.rows[active.r]?.rid), colAt = visibleColumns.indexOf(active.c);
  if (rowAt < 0 || rowAt + grid.length > visibleIds.length) throw new Error(uiText("sheetInteraction.thePasteExceedsVisibleRowsAddRowsOrClear"));
  if (colAt < 0 || grid.some(row => row.length + colAt > visibleColumns.length)) throw new Error(uiText("sheetInteraction.thePasteExceedsVisibleColumnsShowOrAddColumns"));
  const row_edits = grid.map((values,i) => {
    const old = parsed.rows.find(row=>row.rid===visibleIds[rowAt+i]);
    if (!old) throw new Error(uiText("sheetInteraction.theSelectedRowNoLongerExistsSelectAnotherRow"));
    const cells = {}, expected_cells = {};
    values.forEach((value,j) => {
      const c = visibleColumns[colAt+j], type = parsed.table.attrs.column_types?.[c];
      if (type === 'number' && value.trim() && (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(value.trim()) || !Number.isFinite(Number(value)))) throw new Error(uiText("sheetInteraction.requiresANumberWithoutThousandsSeparatorsUseAFormula", {v0: (parsed.headers[c])}));
      const options = parsed.table.attrs.column_options?.[parsed.table.attrs.column_ids?.[c]]?.options;
      if (type === 'status' && options?.length && value && !options.includes(value)) throw new Error(uiText("sheetInteraction.doesNotIncludeTheStatusConfigureThisOptionFirst", {v0: (parsed.headers[c]), v1: (value)}));
      cells[c] = value; expected_cells[c] = old.cells[c]?.value ?? '';
    });
    const column_ids = Object.fromEntries(Object.keys(cells).filter(c=>parsed.table.attrs.column_ids?.[c]).map(c=>[c,parsed.table.attrs.column_ids[c]]));
    return {row_id:old.rid,cells,expected_cells,...(Object.keys(column_ids).length ? {column_ids} : {})};
  });
  return {table_id:parsed.tableId,column_ids:[...(parsed.table.attrs.column_ids || [])],row_edits,new_rows:[]};
}

export function inverseOperation(operation) {
  if (operation.new_rows?.length) throw new Error(uiText("sheetInteraction.restoreAddedRowsThroughVersionHistoryCellUndoDoes"));
  return {...operation,row_edits:operation.row_edits.map(row=>({...row,cells:{...row.expected_cells},expected_cells:{...row.cells}}))};
}

// This is only offered after the user has reviewed a conflict. Automatic retry
// always reuses the original expected values instead of overwriting new work.
export function rebaseOperation(parsed, operation) {
  if(parsed.tableId!==operation.table_id)throw new Error(uiText("sheetInteraction.theSourceTableNoLongerExists"));
  const ids=parsed.table.attrs.column_ids||[];
  const row_edits=operation.row_edits.map(edit=>{
    const row=parsed.rows.find(r=>r.rid===edit.row_id);
    if(!row)throw new Error(uiText("sheetInteraction.theSelectedRowNoLongerExistsYourDraftIs"));
    const cells={},expected_cells={},column_ids={};
    for(const [oldIndex,value] of Object.entries(edit.cells)){
      const id=edit.column_ids?.[oldIndex],c=id?ids.indexOf(id):Number(oldIndex);
      if(c<0||c>=parsed.headers.length)throw new Error(uiText("sheetInteraction.theSelectedColumnNoLongerExistsYourDraftIs"));
      cells[c]=value;expected_cells[c]=row.cells[c]?.value??'';if(id)column_ids[c]=id;
    }
    return{row_id:row.rid,cells,expected_cells,...(Object.keys(column_ids).length?{column_ids}:{})};
  });
  return{...operation,column_ids:[...ids],row_edits,base_revision:undefined};
}

export function freezeSheetScope(tab, parsed, ids = null, columns = parsed.headers.map((_,i)=>i)) {
  const rows = ids == null ? parsed.rows.map(row=>row.rid) : [...ids];
  if (!rows.length || rows.some(id=>!parsed.rows.some(row=>row.rid===id))) throw new Error(uiText("sheetInteraction.theSelectedRowsNoLongerExistOrContainNo"));
  return {target_tab:tab.key,table_id:parsed.tableId,table_name:parsed.name,base_revision:tab.revision,
    row_ids:rows,column_ids:columns.map(c=>parsed.table.attrs.column_ids?.[c]).filter(Boolean),column_indices:[...columns]};
}
