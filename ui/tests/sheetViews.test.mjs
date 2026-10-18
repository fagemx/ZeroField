import test from 'node:test';
import assert from 'node:assert/strict';
import { sheetViewModel, restoreViewPreferences, viewPreferences, statusMovePayload, statusOptions } from '../src/sheetViews.js';

const cell = (value, kind = 'text') => ({value, kind});
const parsed = {
  tableId: 't1', headers: ['名稱', '草圖', '進度', '工時', '合計', '覆核'],
  table: {attrs: {column_types: ['text', 'image', 'status', 'number', 'formula', 'text']}},
  rows: [
    {rid: 'r1', cells: [cell('甲'), cell('![草圖](https://example.org/a.png)'), cell('進行中'), cell('2'), cell('=D1+D2'), cell('等待審核', 'status')]},
    {rid: 'r2', cells: [cell('乙'), cell(''), cell(''), cell('3'), cell(''), cell('已完成', 'status')]},
    {rid: 'r3', cells: [cell('丙'), cell('[video](https://example.org/c.mp4)'), cell('外部覆核'), cell('4'), cell(''), cell('未開始', 'status')]},
  ],
};

test('filtered cards retain original row identity and formulas use the complete table', () => {
  const before = JSON.stringify(parsed);
  const model = sheetViewModel(parsed, [parsed.rows[2], parsed.rows[0]], {});
  assert.deepEqual(model.cards.map(c => [c.row.rid, c.index]), [['r3', 2], ['r1', 0]]);
  assert.ok(model.cards[1].summary.some(s => s.label === '合計' && s.value === '5'));
  assert.equal(JSON.stringify(parsed), before);
});

test('kanban preserves unknown and blank statuses and supports field-backed status columns', () => {
  const model = sheetViewModel(parsed, parsed.rows, {});
  assert.deepEqual(model.statusColumns.map(c => c.index), [2, 5]);
  assert.deepEqual(model.groups.find(g => g.value === '').cards.map(c => c.row.rid), ['r2']);
  assert.deepEqual(model.groups.find(g => g.value === '外部覆核').cards.map(c => c.row.rid), ['r3']);
  assert.equal(model.groups.reduce((n, g) => n + g.cards.length, 0), 3);
  const alternate = sheetViewModel(parsed, parsed.rows, {groupColumn: 5});
  assert.deepEqual(alternate.groups.find(g => g.value === '已完成').cards.map(c => c.row.rid), ['r2']);
});

test('gallery never renders a video as an image and can omit covers', () => {
  const model = sheetViewModel(parsed, parsed.rows, {});
  assert.equal(model.cards[0].cover.url, 'https://example.org/a.png');
  assert.equal(model.cards[1].cover, null);
  assert.equal(model.cards[2].cover, null);
  assert.equal(sheetViewModel(parsed, parsed.rows, {coverColumn: -1}).cards[0].cover, null);
  const plain = {...parsed, headers: ['工作'], table: {attrs: {}}, rows: [{rid: 'x', cells: [cell('查資料')]}]};
  const textOnly = sheetViewModel(plain, plain.rows, {});
  assert.equal(textOnly.groupColumn, -1);
  assert.equal(textOnly.coverColumn, -1);
  assert.equal(textOnly.cards[0].title, '查資料');
});

test('configured status options replace generic defaults while retaining existing values', () => {
  const custom = {...parsed, table:{attrs:{...parsed.table.attrs,column_ids:['name','image','state'],column_options:{state:{options:['待安排','已交付']}}}}};
  assert.deepEqual(statusOptions(custom,2),['待安排','已交付','進行中','外部覆核']);
});

test('card formulas use selected imported header row instead of assuming row one', () => {
  const imported={...parsed,table:{attrs:{...parsed.table.attrs,worksheet_name:'資料',source_header_row:3}},rows:[{rid:'r1',cells:[cell('甲'),cell(''),cell('進行中'),cell('8'),cell('=D4*2'),cell('')]}]};
  assert.equal(sheetViewModel(imported,imported.rows).cards[0].summary.find(s=>s.label==='合計').value,'16');
});

test('status changes address one original row and one status column only', () => {
  assert.deepEqual(statusMovePayload(parsed, 'r3', 2, '已完成'), {
    table_id: 't1', row_edits: [{row_id: 'r3', cells: {'2': '已完成'}}], new_rows: [],
  });
  assert.throws(() => statusMovePayload(parsed, 'deleted', 2, '已完成'), /no longer exist/);
  assert.throws(() => statusMovePayload(parsed, 'r1', 0, '已完成'), /status column/);
  assert.throws(() => statusMovePayload(parsed, 'r1', 2, '任意未知值'), /status option/);
  assert.throws(() => statusMovePayload(parsed, 'r1', 5, ''), /status option/);
});

test('view preferences survive reload but stale column bindings and malformed storage are discarded', () => {
  const saved = JSON.stringify(viewPreferences(parsed, {mode: 'kanban', coverColumn: -1, groupColumn: 5}));
  assert.deepEqual(restoreViewPreferences(saved, parsed), {mode: 'kanban', coverColumn: -1, groupColumn: 5});
  const changed = {...parsed, headers: ['進度', '草圖', '名稱', '工時', '合計', '覆核']};
  assert.deepEqual(restoreViewPreferences(saved, changed), {mode: 'kanban'});
  assert.deepEqual(restoreViewPreferences('{broken', parsed), {mode: 'grid'});
  assert.deepEqual(restoreViewPreferences('null', parsed), {mode: 'grid'});
  assert.deepEqual(restoreViewPreferences('{"mode":"unknown"}', parsed), {mode: 'grid'});
});
