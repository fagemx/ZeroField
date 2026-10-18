import test from "node:test";
import assert from "node:assert/strict";
import { connectNodes, connectedWorker, readSelection, seedDefinition, summarizeTasks } from "../src/flowModel.js";
import { textCell } from "../src/sheetModel.js";
import { applyCanvasPositions, createStep, flowToCanvas, pushDefinition, redoDefinition, taskSourceContext, undoDefinition } from "../src/flowModel.js";

test("result row context uses the claimed source snapshot and never offers a non-row jump", () => {
  const run = { definition: { nodes: [{ id: "step", row_source: { tab_key: "source", table_id: "table" } }] } };
  const task = { node_id: "step", row_id: "r2", source_context: { tab_key: "source", table_id: "table", title: "原始資料", revision: 3, cells: ["鏡頭二", "待核對"] } };
  assert.deepEqual(taskSourceContext(task, run), { tabKey: "source", tableId: "table", rowId: "r2", colIndex: 0, title: "原始資料", revision: 3, label: "鏡頭二 · 待核對" });
  assert.equal(taskSourceContext({ ...task, row_id: null }, run), null);
  assert.equal(taskSourceContext({ node_id: "step", row_id: "r2" }, run).label, "Source Rows");
  const input = { tabs: [{ tab_key: "source", title: "來源", revision: 2 }], rows: [{ row_id: "r2", tab_key: "reference", table_id: "table", cells: ["錯誤參考列"] }, { row_id: "r2", tab_key: "source", table_id: "table", cells: ["正確來源列"] }] };
  assert.equal(taskSourceContext({ node_id: "step", row_id: "r2", input }, run).label, "正確來源列");
});

test("React Flow adapter preserves execution attributes and original coordinates", () => {
  const definition = { viewport: { zoom: 0.5 }, nodes: [{ id: "a", x: -22, y: 75, title: "整理", capability: "llm", input_tabs: ["source"], target: { tab_key: "output", column_id: "column-a", col_index: 2 }, custom: { model: "fixture" } }], edges: [] };
  const snapshot = JSON.stringify(definition);
  const projected = flowToCanvas(definition, ["a"], [{ key: "source", title: "來源" }, { key: "output", title: "結果" }]);
  assert.deepEqual(projected.nodes[0].position, { x: -22, y: 75 });
  assert.equal(projected.nodes[0].data.source, "來源");
  assert.equal(projected.nodes[0].selected, true);
  const moved = applyCanvasPositions(definition, [{ type: "position", id: "a", position: { x: 200, y: 300 } }, { type: "dimensions", id: "a", dimensions: { width: 200, height: 100 } }]);
  assert.deepEqual(moved.nodes[0], { ...definition.nodes[0], x: 200, y: 300 });
  assert.deepEqual(moved.viewport, definition.viewport);
  assert.equal(JSON.stringify(definition), snapshot);
});

test('moving a profile-bound node preserves its agent routing', () => {
  const definition = {nodes:[{id:'profile',agent_key:'sheet_ops',capability:'llm',x:0,y:0}],edges:[]};
  const moved = applyCanvasPositions(definition,[{type:'position',id:'profile',position:{x:10,y:20}}]);
  assert.equal(moved.nodes[0].agent_key,'sheet_ops');
});

test("definition undo and redo restore complete connection and configuration changes", () => {
  const a = createStep("transform", "a"), b = createStep("generate", "b", 1);
  const original = { nodes: [a, b], edges: [], custom: "preserved" };
  const connected = connectNodes(original, "a", "b");
  let history = pushDefinition({ past: [], present: original, future: [] }, connected);
  history = undoDefinition(history);
  assert.deepEqual(history.present, original);
  assert.deepEqual(redoDefinition(history).present, connected);
  const edited = { ...original, nodes: [{ ...a, prompt: "new" }, b] };
  assert.equal(pushDefinition(history, edited).future.length, 0);
  assert.equal(createStep("review", "review").write_mode, "proposal");
});

const graph = { nodes: ["a", "b", "c", "d"].map((id) => ({ id })), edges: [] };
test("DAG editor permits branching and joins, rejects back edges and duplicates", () => {
  let dag = connectNodes(graph, "a", "b");
  dag = connectNodes(dag, "a", "c");
  dag = connectNodes(dag, "b", "d");
  dag = connectNodes(dag, "c", "d");
  assert.equal(dag.edges.length, 4);
  assert.equal(connectNodes(dag, "a", "b"), dag);
  assert.throws(() => connectNodes(dag, "d", "a"), /cycle/);
  assert.throws(() => connectNodes(dag, "a", "a"), /itself/);
  assert.throws(() => connectNodes(dag, "missing", "a"), /not found/);
  assert.equal(graph.edges.length, 0);
});

test("legacy table migration infers capabilities without fictional worker bindings", () => {
  const rows = [["Draft", "OpenAI", "Read script", "未開始", "Return prompts"], ["Frame", "ComfyUI", "Generate", "未開始", ""], ["Motion", "Seedance", "Animate", "未開始", ""], ["Edit", "FFmpeg TTS", "Assemble", "未開始", ""]];
  const doc = { content: [{ type: "table", attrs: { bid: "flow" }, content: [
    { type: "tableRow", attrs: { bid: "head" }, content: rows[0].map((_, i) => textCell(String(i), "tableHeader")) },
    ...rows.map((r, i) => ({ type: "tableRow", attrs: { bid: `n${i}` }, content: r.map((v) => textCell(v)) })),
  ] }] };
  const result = seedDefinition(doc, {});
  assert.deepEqual(result.nodes.map((n) => n.capability), ["llm", "image_gen", "video_gen", "media_assemble"]);
  assert.equal(result.nodes[0].prompt, "Read script\nReturn prompts");
  assert.ok(result.nodes.every((n) => n.write_mode === "proposal" && !n.limb_id));
  assert.deepEqual(result.edges[2], { source: "n2", target: "n3" });
});

test("batch selection validates persisted data and deduplicates rows", () => {
  const storage = (value) => ({ getItem: () => value });
  assert.equal(readSelection(storage("broken"), "demo"), null);
  assert.equal(readSelection(storage('{"target_tab":"shots","row_ids":[]}'), "demo"), null);
  assert.deepEqual(readSelection(storage('{"target_tab":"shots","row_ids":["a","a",null,"b"]}'), "demo"), { target_tab: "shots", row_ids: ["a", "b"] });
});

test("progress is based on successful persisted tasks and failures remain visible", () => {
  assert.deepEqual(summarizeTasks([{ status: "succeeded" }, { status: "awaiting_approval" }, { status: "blocked" }]), { status: "awaiting_approval", completed: 1, total: 3 });
  assert.equal(summarizeTasks([{ status: "succeeded" }, { status: "failed" }]).status, "failed");
  assert.equal(summarizeTasks([]).status, null);
  const now = Date.parse("2026-10-16T00:00:00Z");
  assert.equal(connectedWorker({ enabled: true, last_seen_at: "2026-10-15T23:59:00Z" }, now), true);
  assert.equal(connectedWorker({ enabled: true, last_seen_at: "2026-10-15T23:50:00Z" }, now), false);
  assert.equal(connectedWorker({ enabled: false, last_seen_at: "2026-10-15T23:59:00Z" }, now), false);
});


test("single image redraw preserves cell selection and chooses matching node", async () => {
  const { readSelection, redrawStart } = await import("../src/flowModel.js");
  const storage = { getItem: () => JSON.stringify({ target_tab: "shots", row_ids: ["r1"], capability: "image_gen", col_index: 4 }) };
  const selection = readSelection(storage, "demo");
  const definition = { nodes: [{ id: "wrong", capability: "image_gen", target: { tab_key: "shots", col_index: 2 } }, { id: "image", capability: "image_gen", target: { tab_key: "shots", col_index: 4 } }] };
  assert.equal(redrawStart(definition, selection), "image");
  assert.equal(redrawStart(definition, { ...selection, col_index: 9 }), "");
});
