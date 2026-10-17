import test from "node:test";
import assert from "node:assert/strict";
import { parseTSV, evaluate, columnName, mediaOf, tableEditPayload, tableCSV, tablesOf, textCell } from "../src/sheetModel.js";
test("Excel TSV preserves quoted newlines and tabs", () => {
  assert.deepEqual(parseTSV('a\t"b\nc"\r\n"d\tq"\t"say ""hi"""\r\n'), [["a", "b\nc"], ["d\tq", 'say "hi"']]);
  assert.throws(() => parseTSV('"unclosed'));
});
test("formula recursion, averages and cycle protection", () => {
  const rows = [{ cells: [{ value: "10" }, { value: "=A1*2" }] }, { cells: [{ value: "30" }, { value: "=B1+A2" }] }];
  assert.equal(evaluate("=B2/5", rows), "10");
  assert.equal(evaluate("=AVERAGE(A1:A2)", rows), "20");
  assert.equal(evaluate("=A1", [{ cells: [{ value: "=A1" }] }]), "#ERROR");
  assert.equal(evaluate("=1/0", rows), "#ERROR");
  assert.equal(columnName(26), "AA");
});
test("asset previews reject active URLs and recognize typed assets", () => {
  assert.equal(mediaOf("javascript:alert(1)", "image"), null);
  assert.deepEqual(mediaOf("[video](/projects/api/demo/assets/pa_abc)"), { kind: "video", url: "/projects/api/demo/assets/pa_abc" });
});

test("pasting across plain and field cells retains row identity and pads appended rows", () => {
  const doc = { content: [{ type: "table", attrs: { bid: "table-a" }, content: [
    { type: "tableRow", attrs: { bid: "header" }, content: [textCell("Prompt", "tableHeader"), textCell("Status", "tableHeader")] },
    { type: "tableRow", attrs: { bid: "shot-a" }, content: [textCell("Original"), { type: "tableCell", content: [{ type: "paragraph", content: [{ type: "status", attrs: { fid: "status-a", label: "未開始" } }] }] }] },
  ] }] };
  const parsed = tablesOf(doc, { "status-a": { value: "已完成" } })[0];
  const before = JSON.stringify(doc);
  assert.equal(parsed.rows[0].cells[1].value, "已完成");
  assert.deepEqual(tableEditPayload(parsed, 0, 0, [["New prompt", "進行中"], ["Appended"]]), {
    table_id: "table-a", row_edits: [{ row_id: "shot-a", cells: { 0: "New prompt", 1: "進行中" } }], new_rows: [["Appended", ""]],
  });
  assert.equal(JSON.stringify(doc), before, "paste preparation never mutates source fields or rows");
  assert.throws(() => tableEditPayload(parsed, 0, 1, [["a", "b"]]), /超出欄數/);
});

test("selected-sheet CSV exports current field values and escapes delimiters", () => {
  assert.equal(tableCSV({ headers: ["Name", "Note"], rows: [{ cells: [{ value: "A,B" }, { value: 'say "hello"\nnext' }] }] }), '\uFEFF"Name","Note"\r\n"A,B","say ""hello""\nnext"');
});

test("imported Excel formula references include its header row", () => {
  const rows = [{ cells: [{ value: "10" }] }, { cells: [{ value: "25" }] }];
  assert.equal(evaluate("=SUM(A2:A3)", rows, new Set(), 1), "35");
});


test("native CSV shifts references for its header while imported Excel retains them", () => {
  const native = { headers: ["Value", "Formula"], table: { attrs: {} }, rows: [{ cells: [{ value: "1200" }, { value: "=A1*2" }] }] };
  assert.ok(tableCSV(native).includes("=A2*2"));
  native.rows[0].cells[1].value = '=LOG10(A1)+SUM(Sheet2!A1:B3)+SUM(\'Data 2\'!A1:B3)';
  assert.ok(tableCSV(native).includes('=LOG10(A2)+SUM(Sheet2!A1:B3)+SUM(\'Data 2\'!A1:B3)'));
  native.rows[0].cells[1].value = "=A1*2";
  native.table.attrs.worksheet_name = "Imported";
  assert.ok(tableCSV(native).includes("=A1*2"));
  assert.equal(mediaOf("/projects/api/demo/assets/pa_" + "a".repeat(32)).kind, "asset");
});
