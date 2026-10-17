import { tablesOf } from "./sheetModel.js";

export const CAPABILITIES = { llm: "文字與推理", image_gen: "圖片生成", video_gen: "影片生成", media_assemble: "音訊與合成" };
export const TASK_LABELS = { blocked: "等待上游", queued: "排隊中", running: "執行中", awaiting_approval: "等待提案審核", succeeded: "已完成", failed: "失敗", canceled: "已取消" };
export const SCOPE_LABELS = { once: "執行一次", rows: "逐列處理", aggregate: "全部完成後匯總", legacy: "依批次選取" };

export const STEP_KINDS = {
  read: { title: "讀取與擷取", description: "從文件或表格擷取需要的內容", capability: "llm", prompt: "從指定來源擷取需要的內容，保留來源依據。" },
  transform: { title: "整理內容", description: "分類、改寫、摘要或計算說明", capability: "llm", prompt: "整理指定來源，回傳清楚且可核對的結果。" },
  generate: { title: "生成圖片", description: "依資料與指令產出圖片", capability: "image_gen", prompt: "依指定來源與指令生成圖片。" },
  review: { title: "提出核對建議", description: "整理建議，指定寫回位置後由人核對", capability: "llm", prompt: "檢查指定內容並提出具體修正建議，說明修改理由。" },
  write: { title: "寫入文件或表格", description: "依目標欄位整理結果，核對後寫回", capability: "llm", prompt: "將指定來源整理成符合目標文件或表格欄位的結果。" },
};

export function createStep(kind, id, index = 0) {
  const preset = STEP_KINDS[kind] || STEP_KINDS.transform;
  return { id, kind, title: preset.title, capability: preset.capability, prompt: preset.prompt,
    scope: "once", input_tabs: [], target: {}, write_mode: "proposal", x: 60 + index % 3 * 310, y: 70 + Math.floor(index / 3) * 180 };
}

export function pushDefinition(history, next) {
  if (JSON.stringify(history.present) === JSON.stringify(next)) return history;
  return { past: [...history.past.slice(-49), history.present], present: next, future: [] };
}
export function undoDefinition(history) {
  if (!history.past.length) return history;
  return { past: history.past.slice(0, -1), present: history.past.at(-1), future: [history.present, ...history.future] };
}
export function redoDefinition(history) {
  if (!history.future.length) return history;
  return { past: [...history.past, history.present], present: history.future[0], future: history.future.slice(1) };
}

export function flowToCanvas(definition, selectedIds = [], tabs = [], tasks = []) {
  const name = (key) => tabs.find((t) => t.key === key)?.title || key;
  return {
    nodes: definition.nodes.map((node) => ({ id: node.id, type: "workStep", position: { x: node.x ?? 0, y: node.y ?? 0 },
      selected: selectedIds.includes(node.id), data: { title: node.title, scope: node.scope || "legacy",
        source: name(node.row_source?.tab_key || node.input_tabs?.[0]) || "尚未選來源",
        target: name(node.target?.tab_key) || "保留結果", status: summarizeTasks(tasks.filter((t) => t.node_id === node.id)).status },
      ariaLabel: `${node.title}；${name(node.row_source?.tab_key || node.input_tabs?.[0]) || "尚未選來源"} → ${name(node.target?.tab_key) || "保留結果"}` })),
    edges: definition.edges.map((edge) => ({ id: `${edge.source}--${edge.target}`, source: edge.source, target: edge.target,
      label: "完成後執行", ariaLabel: "前一步完成並通過核對後執行；輸出以來源步驟識別提供", markerEnd: { type: "arrowclosed" } })),
  };
}

export function applyCanvasPositions(definition, changes) {
  const positions = new Map(changes.filter((c) => c.type === "position" && c.position).map((c) => [c.id, c.position]));
  if (!positions.size) return definition;
  return { ...definition, nodes: definition.nodes.map((node) => positions.has(node.id) ? { ...node, x: positions.get(node.id).x, y: positions.get(node.id).y } : node) };
}

export function seedDefinition(doc, values) {
  const rows = tablesOf(doc, values)[0]?.rows || [];
  const nodes = rows.map((row, i) => {
    const cells = row.cells.map((c) => String(c.value));
    const provider = cells[1] || "";
    const capability = /image|生圖|ComfyUI|Flux|即夢/i.test(provider) ? "image_gen"
      : /video|影片|Seedance|Kling|Veo/i.test(provider) ? "video_gen"
        : /media|合成|FFmpeg|TTS/i.test(provider) ? "media_assemble" : "llm";
    return { id: row.rid, title: cells[0] || `節點 ${i + 1}`, capability,
      prompt: [cells[2], cells[4]].filter(Boolean).join("\n"), x: 40 + i * 400, y: 70,
      input_tabs: [], target: {}, write_mode: "proposal" };
  });
  return { nodes, edges: nodes.slice(1).map((n, i) => ({ source: nodes[i].id, target: n.id })) };
}

export function connectNodes(definition, source, target) {
  if (source === target) throw new Error("節點不能連回自己");
  if (!definition.nodes.some((n) => n.id === source) || !definition.nodes.some((n) => n.id === target)) throw new Error("找不到連線節點");
  if (definition.edges.some((e) => e.source === source && e.target === target)) return definition;
  const edges = [...definition.edges, { source, target }];
  const visited = new Set();
  const visit = (id, path = new Set()) => {
    if (path.has(id)) throw new Error("這條連線會形成循環");
    if (visited.has(id)) return;
    for (const edge of edges.filter((e) => e.source === id)) visit(edge.target, new Set([...path, id]));
    visited.add(id);
  };
  visit(target);
  return { ...definition, edges };
}

export function readSelection(storage, slug) {
  try {
    const selection = JSON.parse(storage.getItem(`openbench-selection:${slug}`));
    if (typeof selection?.target_tab !== "string" || !Array.isArray(selection.row_ids)) return null;
    const ids = [...new Set(selection.row_ids.filter((id) => typeof id === "string" && id))];
    return ids.length ? { target_tab: selection.target_tab, row_ids: ids.slice(0, 200),
      ...(selection.capability ? { capability: selection.capability } : {}),
      ...(Number.isInteger(selection.col_index) ? { col_index: selection.col_index } : {}) } : null;
  } catch { return null; }
}

export function redrawStart(definition, selection) {
  if (!selection?.capability) return "";
  return definition.nodes.find((n) => n.capability === selection.capability && n.target?.tab_key === selection.target_tab && n.target?.col_index === selection.col_index)?.id || "";
}

export function connectedWorker(worker, now = Date.now()) {
  return !!worker.enabled && !!worker.last_seen_at && now - Date.parse(worker.last_seen_at) < 300000;
}

export function summarizeTasks(tasks) {
  const states = tasks.map((t) => t.status);
  const status = ["failed", "running", "awaiting_approval", "queued", "blocked", "canceled"].find((s) => states.includes(s)) || (states.length ? "succeeded" : null);
  return { status, completed: states.filter((s) => s === "succeeded").length, total: states.length };
}

export function taskSourceContext(task, run, tabs = []) {
  if (!task.row_id) return null;
  const node = run?.definition?.nodes.find((item) => item.id === task.node_id);
  const source = run?.execution?.row_source || node?.row_source || {};
  const matches = (task.input?.rows || []).filter((row) => row.row_id === task.row_id && (!source.tab_key || row.tab_key === source.tab_key) && (!source.table_id || row.table_id === source.table_id));
  const row = task.source_context || (matches.length === 1 ? matches[0] : null);
  const tabKey = row?.tab_key || source.tab_key;
  if (!tabKey) return null;
  const inputTab = task.input?.tabs?.find((item) => item.tab_key === tabKey);
  const cellText = (cell) => String(cell?.value ?? cell ?? "").trim();
  return { tabKey, tableId: row?.table_id || source.table_id, rowId: task.row_id, colIndex: 0,
    title: row?.title || inputTab?.title || tabs.find((item) => item.key === tabKey)?.title || tabKey,
    revision: row?.revision ?? inputTab?.revision,
    label: (row?.cells || []).slice(0, 2).map(cellText).filter(Boolean).join(" · ") || "來源資料列" };
}
