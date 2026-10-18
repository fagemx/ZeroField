import test from "node:test";
import assert from "node:assert/strict";
import { nextCell, sheetRequest, historyForRow } from "../src/sheetInteraction.js";

test("keyboard navigation follows visible rows and stops at table boundaries", () => {
  assert.deepEqual(nextCell({r: 0, c: 1}, "ArrowDown", [0, 3, 8], 4), {r: 3, c: 1});
  assert.deepEqual(nextCell({r: 3, c: 1}, "ArrowUp", [0, 3, 8], 4), {r: 0, c: 1});
  assert.deepEqual(nextCell({r: 8, c: 3}, "ArrowRight", [0, 3, 8], 4), {r: 8, c: 3});
  assert.equal(nextCell({r: 0, c: 0}, "ArrowDown", [], 4), null);
});

test("row history retains table-wide changes when schema and cells were edited together", () => {
  const groups = [{id: 1, changes: [{bid: "table", label: "表格內容與設定"}, {rid: "other"}]},
    {id: 2, changes: [{rid: "row", label: "修改本列"}, {anchor_id: "row", label: "修改狀態"}]},
    {id: 3, changes: [{bid: "another-table"}]}];
  const result = historyForRow(groups, "row", "table");
  assert.deepEqual(result.map((g) => g.id), [1, 2]);
  assert.equal(result[0].changes[0].tableWide, true);
  assert.equal(result[0].changes.length, 1);
  assert.equal(result[1].changes.length, 2);
  assert.equal(result[1].changes[0].tableWide, false);
  assert.equal(groups[0].changes[0].tableWide, undefined);
});

test("agent draft names selected records in table order without internal tool syntax", () => {
  const table = {name: "名單", rows: [{rid: "r_a", cells: [{value: "甲"}]}, {rid: "r_b", cells: [{value: "乙"}]}]};
  const draft = sheetRequest("合作專案", table, ["r_b", "r_a"], "補上缺少的說明");
  assert.ok(draft.includes("Row 1 “甲”, Row 2 “乙”"));
  assert.ok(draft.includes("補上缺少的說明"));
  assert.ok(!/row_id|propose_table_edit|r_a/.test(draft));
  assert.throws(() => sheetRequest("合作專案", table, ["deleted"], "修改"), /no longer exist/);
  assert.ok(sheetRequest("合作專案", table, null, "檢查").includes("the entire table"));
  assert.throws(() => sheetRequest("合作專案", table, null, "字".repeat(4000)), /too long/);
});
