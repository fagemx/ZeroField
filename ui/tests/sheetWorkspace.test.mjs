import test from 'node:test';
import assert from 'node:assert/strict';
import * as sheet from '../src/sheetInteraction.js';

const table = {tableId:'t',name:'工作表',headers:['名稱','狀態','數值'],table:{attrs:{column_ids:['c_name','c_status','c_value'],column_types:['text','status','number']}},rows:[
  {rid:'a',cells:[{value:'同名'},{value:'未開始'},{value:'10'}]},
  {rid:'b',cells:[{value:'隱藏'},{value:'已完成'},{value:'20'}]},
  {rid:'c',cells:[{value:'同名'},{value:'未開始'},{value:'30'}]},
]};
test('filtered sorted paste writes only visible row identities with original-value guards',()=>{
  assert.equal(typeof sheet.visiblePastePayload,'function');
  const result=sheet.visiblePastePayload(table,['c','a'],{r:2,c:1},[['進行中','31'],['進行中','11']]);
  assert.deepEqual(result.row_edits,[{row_id:'c',cells:{1:'進行中',2:'31'},expected_cells:{1:'未開始',2:'30'},column_ids:{1:'c_status',2:'c_value'}},{row_id:'a',cells:{1:'進行中',2:'11'},expected_cells:{1:'未開始',2:'10'},column_ids:{1:'c_status',2:'c_value'}}]);
  assert.deepEqual(result.column_ids,['c_name','c_status','c_value']);
  assert.deepEqual(result.new_rows,[]);
  assert.throws(()=>sheet.visiblePastePayload(table,['c','a'],{r:0,c:1},[['x'],['y']]),/visible/);
});
test('range copies a rectangle in visible order including quoted multiline cells',()=>{
  assert.equal(typeof sheet.selectionRange,'function');
  assert.deepEqual(sheet.selectionRange({r:2,c:2},{r:0,c:0},[2,0],[0,2]),{rows:[2,0],columns:[0,2]});
  assert.equal(sheet.rangeTSV(table,{rows:[2,0],columns:[0,2]}),'同名\t30\n同名\t10');
});
test('one undo inverses all cells using new values as CAS and keeps stable columns',()=>{
  assert.equal(typeof sheet.inverseOperation,'function');
  const action={table_id:'t',column_ids:['c_name','c_status','c_value'],row_edits:[{row_id:'c',cells:{1:'進行中',2:'31'},expected_cells:{1:'未開始',2:'30'}}],new_rows:[]};
  assert.deepEqual(sheet.inverseOperation(action),{...action,row_edits:[{row_id:'c',cells:{1:'未開始',2:'30'},expected_cells:{1:'進行中',2:'31'}}]});
  assert.deepEqual(sheet.inverseOperation(sheet.inverseOperation(action)),action);
});
test('agent scope freezes selected identities and source revision despite later view changes',()=>{
  assert.equal(typeof sheet.freezeSheetScope,'function');
  const ids=['c','a'];
  const scope=sheet.freezeSheetScope({key:'tab',revision:7},table,ids,[2]);
  ids.pop();
  assert.deepEqual(scope.row_ids,['c','a']);
  assert.deepEqual(scope.column_ids,['c_value']);
  assert.equal(scope.base_revision,7);
  assert.throws(()=>sheet.freezeSheetScope({key:'tab'},table,['gone']),/no longer exist/);
});
test('typed paste rejects invalid numbers and preserves exact text for valid values',()=>{
  assert.equal(typeof sheet.visiblePastePayload,'function');
  assert.throws(()=>sheet.visiblePastePayload(table,['a'],{r:0,c:2},[['abc']]),/number/);
  for (const value of ['1,000', '=SUM(A1:A2)', '0x10']) assert.throws(()=>sheet.visiblePastePayload(table,['a'],{r:0,c:2},[[value]]),/number/);
  assert.equal(sheet.visiblePastePayload(table,['a'],{r:0,c:2},[['01.50']]).row_edits[0].cells[2],'01.50');
});

test('explicit draft rebase keeps frozen rows and maps moved columns by identity',()=>{
  assert.equal(typeof sheet.rebaseOperation,'function');
  const pending={table_id:'t',row_edits:[{row_id:'c',cells:{0:'我的內容'},expected_cells:{0:'同名'},column_ids:{0:'c_name'}}],new_rows:[]};
  const moved={...table,table:{attrs:{...table.table.attrs,column_ids:['c_status','c_name','c_value']}},rows:[...table.rows.slice(0,2),{rid:'c',cells:[{value:'未開始'},{value:'同事內容'},{value:'30'}]}]};
  const rebased=sheet.rebaseOperation(moved,pending);
  assert.deepEqual(rebased.row_edits,[{row_id:'c',cells:{1:'我的內容'},expected_cells:{1:'同事內容'},column_ids:{1:'c_name'}}]);
  assert.equal(pending.row_edits[0].expected_cells[0],'同名');
  assert.throws(()=>sheet.rebaseOperation({...table,rows:[]},pending),/no longer exist/);
});
