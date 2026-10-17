import { useEffect, useMemo, useRef, useState } from "react";
import { Background, Controls, Handle, Position, ReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "./flow-workspace.css";
import { api } from "./api.js";
import { newId, tablesOf } from "./sheetModel.js";
import { SCOPE_LABELS, STEP_KINDS, TASK_LABELS, applyCanvasPositions, connectNodes, createStep, flowToCanvas, pushDefinition, readSelection, redrawStart, redoDefinition, seedDefinition, summarizeTasks, undoDefinition } from "./flowModel.js";
import { FlowInspector, FlowPreflight, FlowResults, Status } from "./FlowPanels.jsx";

function WorkStep({ data, selected, isConnectable }) {
  return <article className={`flow-step-card ${selected ? "is-selected" : ""}`}>
    <Handle type="target" position={Position.Left} isConnectable={isConnectable} aria-label={`${data.title} 輸入連線`} />
    <strong>{data.title}</strong><span className="flow-step-route">{data.source} → {data.target}</span>
    <div><small>{SCOPE_LABELS[data.scope]}</small><Status status={data.status} /></div>
    <Handle type="source" position={Position.Right} isConnectable={isConnectable} aria-label={`${data.title} 輸出連線`} />
  </article>;
}
const nodeTypes = { workStep: WorkStep };
const initialFitOptions = { padding: 0.25, maxZoom: 1 };
const emptyHistory = { past: [], present: null, future: [] };
const docResponse = (data) => ({ ...(data.tab || data), values: data.values || data.tab?.values || {} });

export function FlowSurface({ slug, tab, tabs = [], me, values, onSwitchDocMode, onToast, onError, controlRef, onInspectorChange, onOpenProposals, onOpenSource, assistantOpen }) {
  const base = `/projects/api/${slug}/tabs/${tab.key}/flow`;
  const [history, setHistory] = useState(emptyHistory);
  const definition = history.present;
  const [savedJSON, setSavedJSON] = useState("");
  const [revision, setRevision] = useState(0);
  const dirty = !!definition && JSON.stringify(definition) !== savedJSON;
  const [selectedIds, setSelectedIds] = useState([]);
  const [selectedEdgeIds, setSelectedEdgeIds] = useState([]);
  const selectedId = selectedIds.at(-1) || null;
  const selected = definition?.nodes.find((node) => node.id === selectedId);
  const [workers, setWorkers] = useState([]);
  const [runs, setRuns] = useState([]);
  const [runId, setRunId] = useState("");
  const [detail, setDetail] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(false);
  const [search, setSearch] = useState("");
  const [sourceDoc, setSourceDoc] = useState(null);
  const [targetDoc, setTargetDoc] = useState(null);
  const [sampleRow, setSampleRow] = useState("");
  const [preview, setPreview] = useState(null);
  const [previewInput, setPreviewInput] = useState(null);
  const [resultsOpen, setResultsOpen] = useState(false);
  const [selection] = useState(() => readSelection(window.sessionStorage, slug));
  const [batch, setBatch] = useState(() => !!readSelection(window.sessionStorage, slug));
  const [startNode, setStartNode] = useState("");
  const instance = useRef(null);
  const dragStart = useRef(null);
  const editStart = useRef(null);
  const writable = me?.can_write !== false;
  const sourceKey = selected?.row_source?.tab_key || selected?.input_tabs?.[0] || "";
  const targetKey = selected?.target?.tab_key || "";
  const sourceTables = useMemo(() => tablesOf(sourceDoc?.doc, sourceDoc?.values || {}), [sourceDoc]);
  const targetTables = useMemo(() => tablesOf(targetDoc?.doc, targetDoc?.values || {}), [targetDoc]);
  const sourceTable = sourceTables.find((table) => table.tableId === selected?.row_source?.table_id) || sourceTables[0];
  const targetTable = targetTables.find((table) => table.tableId === selected?.target?.table_id) || targetTables[0];
  const samples = useMemo(() => {
    let rows = (selected?.row_source?.table_id ? sourceTables.filter((table) => table.tableId === selected.row_source.table_id) : sourceTables).flatMap((table) => table.rows);
    const source = selected?.row_source;
    const statuses = Array.isArray(source?.status) ? source.status : source?.status ? [source.status] : [];
    if (statuses.length) rows = rows.filter((row) => (source.status_col == null ? row.cells : [row.cells[source.status_col]]).some((cell) => statuses.includes(String(cell?.value ?? ""))));
    return rows;
  }, [sourceTables, selected?.row_source]);
  const tasks = detail?.tasks || [];
  const canvas = useMemo(() => { if (!definition) return { nodes: [], edges: [] }; const result = flowToCanvas(definition, selectedIds, tabs, tasks); return { ...result, edges: result.edges.map((edge) => ({ ...edge, selected: selectedEdgeIds.includes(edge.id) })) }; }, [definition, selectedIds, selectedEdgeIds, tabs, detail]);
  const canControl = writable && detail && (detail.run.created_by === me?.actor_id || me?.is_admin || me?.role === "admin");
  const report = (problem) => { const message = problem.message || String(problem); setError(message); onError?.(message); };
  const work = async (fn) => { setBusy(true); setError(""); try { return await fn(); } catch (problem) { report(problem); } finally { setBusy(false); } };
  const change = (next) => { setHistory((old) => { const present = typeof next === "function" ? next(old.present) : next; return editStart.current ? { ...old, present } : pushDefinition(old, present); }); setPreview(null); setError(""); };
  const finishEdit = () => { const before = editStart.current; editStart.current = null; if (before) setHistory((old) => JSON.stringify(before) === JSON.stringify(old.present) ? old : { ...old, past: [...old.past.slice(-49), before], future: [] }); };
  const update = (patch) => change((current) => ({ ...current, nodes: current.nodes.map((node) => node.id === selectedId ? { ...node, ...patch } : node) }));
  const select = (id) => { setSelectedIds(id ? [id] : []); setPreview(null); setAdding(false); };
  const focusNode = (id) => { select(id); instance.current?.fitView({ nodes: [{ id }], maxZoom: 1.1, padding: 0.65, duration: 0 }); };

  useEffect(() => {
    let alive = true;
    setHistory(emptyHistory); setSavedJSON(""); setPreview(null); setDetail(null); setRunId(""); setSelectedIds([]);
    api.get(base).then((data) => {
      if (!alive) return;
      const seeded = data.revision === 0 && !data.definition.nodes.length ? seedDefinition(tab.doc, values) : data.definition;
      setHistory({ past: [], present: seeded, future: [] }); setRevision(data.revision); setSavedJSON(JSON.stringify(data.definition));
    }).catch((problem) => alive && report(problem));
    return () => { alive = false; };
  }, [base]);
  useEffect(() => { onInspectorChange?.(!!selected || adding || !!preview); return () => onInspectorChange?.(false); }, [!!selected, adding, !!preview]);
  useEffect(() => { finishEdit(); }, [selectedId, assistantOpen, adding, !!preview]);
  useEffect(() => { if (assistantOpen) { setSelectedIds([]); setAdding(false); setPreview(null); } }, [assistantOpen]);
  useEffect(() => {
    let alive = true, timer;
    const poll = async () => {
      try {
        const [workerData, runData] = await Promise.all([api.get(`/projects/api/limbs?project_slug=${encodeURIComponent(slug)}`), api.get(`${base}/runs`)]);
        if (alive) { setWorkers(workerData.limbs || workerData.workers || []); setRuns(runData.runs || []); setRunId((current) => current || runData.runs?.[0]?.id || ""); }
      } catch (problem) { if (alive) setError(problem.message); }
      if (alive) timer = setTimeout(poll, 5000);
    };
    poll(); return () => { alive = false; clearTimeout(timer); };
  }, [base, slug]);
  useEffect(() => {
    setDetail(null); if (!runId) return;
    let alive = true, timer;
    const poll = async () => {
      try { const data = await api.get(`${base}/runs/${runId}`); if (alive) setDetail(data); }
      catch (problem) { if (alive) setError(problem.message); }
      if (alive) timer = setTimeout(poll, 2500);
    };
    poll(); return () => { alive = false; clearTimeout(timer); };
  }, [base, runId]);
  useEffect(() => {
    setSourceDoc(null); setSampleRow(""); if (!sourceKey) return;
    let alive = true;
    api.get(`/projects/api/${slug}/tabs/${sourceKey}`).then((data) => { if (alive) setSourceDoc(docResponse(data)); }).catch((problem) => alive && setError(problem.message));
    return () => { alive = false; };
  }, [slug, sourceKey]);
  useEffect(() => {
    setTargetDoc(null); if (!targetKey) return;
    let alive = true;
    api.get(`/projects/api/${slug}/tabs/${targetKey}`).then((data) => { if (alive) setTargetDoc(docResponse(data)); }).catch((problem) => alive && setError(problem.message));
    return () => { alive = false; };
  }, [slug, targetKey]);
  useEffect(() => { setSampleRow((current) => samples.some((row) => row.rid === current) ? current : samples[0]?.rid || ""); }, [samples]);
  useEffect(() => {
    if (!dirty) return;
    const guard = (event) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", guard); return () => window.removeEventListener("beforeunload", guard);
  }, [dirty]);
  const save = async () => {
    finishEdit();
    if (!definition) throw new Error("工作流尚未載入");
    const data = await api.post(base, { definition, revision });
    setRevision(data.revision); setHistory((old) => ({ ...old, present: data.definition })); setSavedJSON(JSON.stringify(data.definition)); return data;
  };
  useEffect(() => {
    if (!controlRef) return;
    const control = { flush: async () => { if (!dirty) return true; try { await save(); return true; } catch (problem) { report(problem); return false; } }, hasUnsavedChanges: () => dirty };
    controlRef.current = control;
    return () => { if (controlRef.current === control) controlRef.current = null; };
  }, [controlRef, dirty, definition, revision]);
  const check = (single = false) => work(async () => {
    const saved = dirty || !revision ? await save() : { revision };
    const input = single ? { execution_mode: "single_step", node_id: selectedId, input_mode: "current_sources", ...(selected?.row_source ? { sample_row_id: sampleRow } : {}) }
      : { ...(batch && selection ? { target_tab: selection.target_tab, row_ids: selection.row_ids } : {}), ...((startNode || (batch && redrawStart(definition, selection))) ? { start_node_id: startNode || redrawStart(definition, selection) } : {}) };
    if (!single && batch && !selection) throw new Error("請先從表格選取列，或取消依選取列執行");
    if (!single && batch && selection?.capability && !input.start_node_id) throw new Error("找不到對應此儲存格的工作步驟，請選擇起點");
    input.definition_revision = saved.revision;
    const data = await api.post(`${base}/preflight`, input);
    if (single && sourceDoc && data.source_revisions[sourceKey] !== sourceDoc.revision) throw new Error("來源已在樣本載入後變更。請更新樣本，核對新內容後再試這一步。");
    setPreview(data); setPreviewInput(input); setAdding(false);
  });
  const execute = () => work(async () => {
    if (!preview?.ready || dirty) throw new Error("請先重新檢查執行範圍");
    const data = await api.post(`${base}/runs`, { ...previewInput, source_revisions: preview.source_revisions });
    setDetail(data); setRunId(data.run.id); setRuns((old) => [data.run, ...old.filter((run) => run.id !== data.run.id)]);
    setPreview(null); setResultsOpen(true); onToast?.("已排入執行佇列，尚未完成");
  });
  const control = (action) => work(async () => { const data = await api.post(`${base}/runs/${runId}/${action}`, {}); setDetail(data); onToast?.(action === "cancel" ? "已取消後續執行" : "以原執行設定重試未完成項目"); });
  const connect = (source, target) => { try { change(connectNodes(definition, source, target)); } catch (problem) { report(problem); } };
  const removeNodes = (ids) => { change((current) => ({ ...current, nodes: current.nodes.filter((node) => !ids.includes(node.id)), edges: current.edges.filter((edge) => !ids.includes(edge.source) && !ids.includes(edge.target)) })); setSelectedIds((current) => current.filter((id) => !ids.includes(id))); };
  const nodeChanges = (changes) => {
    const selections = changes.filter((change) => change.type === "select");
    if (selections.length) setSelectedIds((current) => selections.reduce((ids, change) => change.selected ? [...ids.filter((id) => id !== change.id), change.id] : ids.filter((id) => id !== change.id), current));
    if (!writable || busy) return;
    if (changes.some((change) => change.type === "position" && change.position)) {
      if (dragStart.current) setHistory((old) => ({ ...old, present: applyCanvasPositions(old.present, changes) })); else change((current) => applyCanvasPositions(current, changes));
      setPreview(null);
    }
    const removed = changes.filter((change) => change.type === "remove").map((change) => change.id);
    if (removed.length) removeNodes(removed);
  };
  const keyboard = (event) => {
    if (event.target.closest("input,textarea,select,[contenteditable=true]")) return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z" && writable && !busy) { event.preventDefault(); setHistory(event.shiftKey ? redoDefinition : undoDefinition); setPreview(null); }
    if (event.key === "Escape") { select(null); setPreview(null); setAdding(false); }
  };
  const add = (kind) => { const node = createStep(kind, newId(), definition.nodes.length); change({ ...definition, nodes: [...definition.nodes, node] }); select(node.id); };

  return <section className="canvas flow-workspace" aria-label="工作流編輯器" onKeyDown={keyboard}>
    <header className="flow-topbar"><div className="flow-heading"><strong>{tab.title}</strong><small role="status">{busy ? "處理中…" : dirty ? "尚未儲存" : `已儲存 · v${revision}`}</small></div><div className="flow-top-actions">
      <button title="撤銷 Ctrl+Z" disabled={!writable || busy || !history.past.length} onClick={() => { setHistory(undoDefinition); setPreview(null); }}>撤銷</button><button title="重做 Ctrl+Shift+Z" disabled={!writable || busy || !history.future.length} onClick={() => { setHistory(redoDefinition); setPreview(null); }}>重做</button><button disabled={busy} onClick={() => work(async () => { if (dirty) await save(); onSwitchDocMode(); })}>文件</button>
      {writable && <><button disabled={busy || !definition || definition.nodes.length >= 100} onClick={() => { setAdding(!adding); setSelectedIds([]); setPreview(null); }}>新增步驟</button><button disabled={busy || !dirty} onClick={() => work(save)}>儲存</button><button className="primary" disabled={busy || !definition?.nodes.length} onClick={() => check(false)}>檢查並執行</button></>}
    </div></header>
    {error && <div className="flow-feedback" role="alert"><span>{error}</span><button aria-label="關閉錯誤" onClick={() => setError("")}>×</button></div>}
    <div className={`flow-main ${selected || adding || preview ? "with-panel" : ""}`}><div className="flow-stage">
      <div className="flow-canvas-tools"><label><input placeholder="搜尋步驟…" aria-label="搜尋步驟" value={search} onChange={(event) => setSearch(event.target.value)} /></label>{search && <div className="flow-search-results">{definition?.nodes.filter((node) => node.title.toLocaleLowerCase().includes(search.toLocaleLowerCase())).map((node) => <button key={node.id} onClick={() => { focusNode(node.id); setSearch(""); }}>{node.title}</button>)}</div>}<span>{definition?.nodes.length || 0} 步驟</span><button disabled={!runId} onClick={() => setResultsOpen(!resultsOpen)}>{resultsOpen ? "收起結果" : "結果與紀錄"}{detail && ` · ${TASK_LABELS[detail.run.status]}`}</button></div>
      {!definition ? <p className="flow-empty-message" role="status">載入工作流…</p> : <ReactFlow nodes={canvas.nodes} edges={canvas.edges} nodeTypes={nodeTypes} onInit={(flow) => { instance.current = flow; }}
        onNodesChange={nodeChanges} onEdgesChange={(changes) => { const selections = changes.filter((item) => item.type === "select"); if (selections.length) setSelectedEdgeIds((ids) => selections.reduce((current, item) => item.selected ? [...current.filter((id) => id !== item.id), item.id] : current.filter((id) => id !== item.id), ids)); if (!writable || busy) return; const ids = changes.filter((item) => item.type === "remove").map((item) => item.id); if (ids.length) change((current) => ({ ...current, edges: current.edges.filter((edge) => !ids.includes(`${edge.source}--${edge.target}`)) })); }}
        onNodeClick={(_, node) => { setAdding(false); setPreview(null); setSelectedIds((ids) => ids.includes(node.id) ? ids : [node.id]); }} onPaneClick={() => select(null)}
        onNodeDragStart={() => { dragStart.current = definition; }} onNodeDragStop={() => { const before = dragStart.current; dragStart.current = null; if (before) setHistory((old) => JSON.stringify(before) === JSON.stringify(old.present) ? old : { ...old, past: [...old.past.slice(-49), before], future: [] }); }}
        onConnect={({ source, target }) => connect(source, target)} nodesDraggable={writable && !busy} nodesConnectable={writable && !busy} edgesReconnectable={false} deleteKeyCode={writable && !busy ? ["Backspace", "Delete"] : null}
        fitView fitViewOptions={initialFitOptions} minZoom={0.25} maxZoom={1.8} selectionOnDrag panOnDrag={[1, 2]} panOnScroll zoomOnScroll={false} zoomOnPinch selectionKeyCode="Shift" multiSelectionKeyCode="Shift"
        ariaLabelConfig={{ "controls.zoomIn.ariaLabel": "放大", "controls.zoomOut.ariaLabel": "縮小", "controls.fitView.ariaLabel": "符合視窗", "node.a11yDescription.default": "Enter 選取步驟。方向鍵移動，Delete 刪除。", "edge.a11yDescription.default": "Enter 選取連線，Delete 刪除。" }}>
        <Background gap={24} size={1} color="#dce1e8" /><Controls showInteractive={false} />{!definition.nodes.length && <div className="flow-empty-message"><strong>從一件工作開始</strong><p>新增步驟，選擇資料來源，再試一筆結果。</p>{writable && <button className="primary" onClick={() => setAdding(true)}>新增第一步</button>}</div>}
      </ReactFlow>}
      <p className="flow-navigation-help">拖曳空白處框選 · 中鍵／右鍵平移 · Shift 多選 · 左下方縮放與符合視窗</p>
    </div>
      {adding && <aside className="flow-sidepanel" aria-label="新增工作步驟"><div className="flow-panel-title"><strong>選擇要做的工作</strong><button aria-label="關閉新增步驟" onClick={() => setAdding(false)}>×</button></div><div className="flow-kind-list">{Object.entries(STEP_KINDS).map(([kind, preset]) => <button key={kind} onClick={() => add(kind)}><strong>{preset.title}</strong><small>{preset.description}</small></button>)}</div></aside>}
      {preview && <FlowPreflight preview={preview} busy={busy} writable={writable} onClose={() => setPreview(null)} onFocus={focusNode} onExecute={execute} />}
      {selected && !preview && !adding && <FlowInspector {...{ selected, selectedId, definition, tabs, tab, workers, writable, busy, sourceDoc, sourceTables, sourceTable, targetTables, targetTable, sourceKey, targetKey, samples, sampleRow, update, change, connect }}
        onEditStart={() => { editStart.current = definition; }} onEditEnd={finishEdit}
        tasks={tasks.filter((task) => task.node_id === selectedId)} onClose={() => select(null)} onSample={(id) => { setSampleRow(id); setPreview(null); }} onRemove={() => removeNodes([selectedId])} onTest={() => check(true)} onResults={() => setResultsOpen(true)}
        onRefresh={() => work(async () => { setSourceDoc(docResponse(await api.get(`/projects/api/${slug}/tabs/${sourceKey}`))); setPreview(null); })} />}
    </div>
    {!preview && <div className="flow-run-scope"><details><summary>執行範圍{batch && selection ? ` · ${selection.row_ids.length} 筆已選列` : " · 全流程"}</summary><div><label><input type="checkbox" checked={batch} onChange={(event) => setBatch(event.target.checked)} />使用表格選取的列</label>{selection && <span>{tabs.find((item) => item.key === selection.target_tab)?.title || selection.target_tab} · {selection.row_ids.length} 列</span>}<label>起點<select value={startNode || (batch && definition ? redrawStart(definition, selection) : "")} onChange={(event) => setStartNode(event.target.value)}><option value="">執行全部</option>{definition?.nodes.map((node) => <option value={node.id} key={node.id}>{node.title} 及所有下游</option>)}</select></label><small>從此繼續會新建執行，不重用舊上游結果。</small></div></details></div>}
    {resultsOpen && <FlowResults {...{ detail, tasks, runs, runId, canControl, busy, revision, tabs, me, onOpenProposals, onOpenSource }} progress={summarizeTasks(tasks)} onRun={setRunId} onClose={() => setResultsOpen(false)} onFocus={focusNode} onControl={control} />}
  </section>;
}
