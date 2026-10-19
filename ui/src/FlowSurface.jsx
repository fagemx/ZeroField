import { useLocale } from './i18n/react.jsx';
import { t as uiText } from './i18n/index.js';
import { useEffect, useMemo, useRef, useState } from "react";
import { Background, Controls, Handle, Position, ReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "./flow-workspace.css";
import { api } from "./api.js";
import { newId, tablesOf } from "./sheetModel.js";
import { CAPABILITIES, NODE_KINDS, SCOPE_LABELS, STEP_KINDS, TASK_LABELS, applyCanvasPositions, connectNodes, createStep, flowToCanvas, pushDefinition, readSelection, redrawStart, redoDefinition, seedDefinition, summarizeTasks, tidyLayout, undoDefinition } from "./flowModel.js";
import { Icon } from "./Icon.jsx";
import { FlowInspector, FlowPreflight, FlowResults, Status } from "./FlowPanels.jsx";

import { MediaCell } from './MediaCell.jsx';

// Dify/Make-style step: the kind of work is read from its icon and tone; the + appends the next step.
function StepPicker({ onPick }) {
  return <div className="flow-picker nodrag nowheel" role="menu" aria-label={uiText("flowSurface.chooseATask")}>{Object.entries(STEP_KINDS).map(([kind, preset]) => {
    const look = NODE_KINDS[preset.capability] || NODE_KINDS.llm;
    return <button type="button" role="menuitem" key={kind} onClick={(event) => { event.stopPropagation(); onPick(kind); }}>
      <span className={`flow-kind tone-${look.tone}`}><Icon name={look.icon} /></span><span><strong>{uiText("stepTitles." + kind)}</strong><small>{uiText("stepDescriptions." + kind)}</small></span></button>;
  })}</div>;
}
function WorkStep({ data, selected, isConnectable }) {
  useLocale();
  const look = NODE_KINDS[data.capability] || NODE_KINDS.llm;
  const kindLabel = CAPABILITIES[data.capability] || "";
  return <article className={`flow-step-card tone-${look.tone} ${selected ? "is-selected" : ""}`}>
    <Handle type="target" position={Position.Left} isConnectable={isConnectable} aria-label={uiText("flowSurface.inputConnections", {v0: (data.title)})} />
    <header><span className={`flow-kind tone-${look.tone}`}><Icon name={look.icon} /></span><div><strong>{data.title}</strong>
      <small className="flow-executor-badge">{kindLabel}{data.executorLabel && data.executorLabel !== kindLabel ? ` · ${data.executorLabel}` : ""}</small></div>
      {data.total > 0 && <span className={`flow-bubble ${data.status || ""}`} title={TASK_LABELS[data.status]}>{data.completed}/{data.total}</span>}</header>
    {data.latestMediaUrl && <div className="flow-node-media nodrag nowheel"><MediaCell compact value={data.latestMediaUrl} label={data.title} /></div>}
    <p className="flow-step-route"><span>{data.source}</span><Icon name="arrowRight" /><span>{data.target}</span></p>
    <footer><small>{SCOPE_LABELS[data.scope]}</small><Status status={data.status} /></footer>
    <Handle type="source" position={Position.Right} isConnectable={isConnectable} aria-label={uiText("flowSurface.outputConnections", {v0: (data.title)})} />
    {data.onAddAfter && <button type="button" className="flow-add-next nodrag" aria-label={uiText("flowSurface.addNextStep", {v0: (data.title)})} title={uiText("flowSurface.addNextStep", {v0: (data.title)})}
      onClick={(event) => { event.stopPropagation(); data.onAddAfter(); }}><Icon name="plus" /></button>}
    {data.picker && <StepPicker onPick={data.onPick} />}
  </article>;
}
function StartStep({ data, selected }) {
  useLocale();
  return <article className={`flow-start-card ${selected ? "is-selected" : ""}`}>
    <header><span className="flow-kind tone-start"><Icon name="play" /></span><div><strong>{uiText("flowSurface.start")}</strong><small>{data.summary}</small></div></header>
    <Handle type="source" position={Position.Right} isConnectable={false} />
  </article>;
}
const nodeTypes = { workStep: WorkStep, start: StartStep };
const START = "__start";
const initialFitOptions = { padding: 0.1, maxZoom: 1 };
const emptyHistory = { past: [], present: null, future: [] };
const docResponse = (data) => ({ ...(data.tab || data), values: data.values || data.tab?.values || {} });

export function FlowSurface({ slug, tab, tabs = [], me, values, onSwitchDocMode, onToast, onError, controlRef, onInspectorChange, onOpenProposals, onOpenSource, assistantOpen }) {
  const locale = useLocale();
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
  const [agents, setAgents] = useState([]);
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
  const [pickerFor, setPickerFor] = useState(null);
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
  const scopeSummary = batch && selection ? uiText("flowSurface.rows", {v0: (tabs.find((item) => item.key === selection.target_tab)?.title || selection.target_tab), v1: (selection.row_ids.length)})
    : startNode ? uiText("flowSurface.fromStep", {v0: (definition?.nodes.find((node) => node.id === startNode)?.title || startNode)}) : uiText("flowSurface.fullPipeline");
  const canvas = useMemo(() => {
    if (!definition) return { nodes: [], edges: [] };
    const result = flowToCanvas(definition, selectedIds, tabs, tasks, agents, workers);
    const nodes = result.nodes.map((node) => ({ ...node, ...(pickerFor === node.id ? { zIndex: 1000 } : {}), data: { ...node.data, picker: pickerFor === node.id, onPick: (kind) => add(kind, node.id),
      ...(writable && !busy ? { onAddAfter: () => { setPickerFor((current) => current === node.id ? null : node.id); setAdding(false); } } : {}) } }));
    const edges = result.edges.map((edge) => ({ ...edge, selected: selectedEdgeIds.includes(edge.id) }));
    // The Start node is not stored: it shows what this run covers and feeds every step that waits on nothing.
    if (definition.nodes.length) {
      const roots = definition.nodes.filter((node) => !definition.edges.some((edge) => edge.target === node.id));
      const x = Math.min(...definition.nodes.map((node) => node.x ?? 0)) - 300, y = Math.min(...roots.map((node) => node.y ?? 0));
      nodes.unshift({ id: START, type: "start", position: { x, y }, draggable: false, deletable: false, selected: selectedIds.includes(START), data: { summary: scopeSummary } });
      for (const node of roots) edges.push({ id: `${START}--${node.id}`, source: START, target: node.id, className: "flow-start-edge", selectable: false, deletable: false });
    }
    return { nodes, edges };
  }, [definition, selectedIds, selectedEdgeIds, tabs, detail, agents, workers, locale, pickerFor, writable, busy, scopeSummary]);
  const canControl = writable && detail && (detail.run.created_by === me?.actor_id || me?.is_admin || me?.role === "admin");
  const report = (problem) => { const message = problem.message || String(problem); setError(message); onError?.(message); };
  const work = async (fn) => { setBusy(true); setError(""); try { return await fn(); } catch (problem) { report(problem); } finally { setBusy(false); } };
  const change = (next) => { setHistory((old) => { const present = typeof next === "function" ? next(old.present) : next; return editStart.current ? { ...old, present } : pushDefinition(old, present); }); setPreview(null); setError(""); };
  const finishEdit = () => { const before = editStart.current; editStart.current = null; if (before) setHistory((old) => JSON.stringify(before) === JSON.stringify(old.present) ? old : { ...old, past: [...old.past.slice(-49), before], future: [] }); };
  const update = (patch) => change((current) => ({ ...current, nodes: current.nodes.map((node) => node.id === selectedId ? { ...node, ...patch } : node) }));
  const select = (id) => { setSelectedIds(id ? [id] : []); setPreview(null); setAdding(false); setPickerFor(null); };
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
        const [workerData, runData, agentData] = await Promise.all([api.get(`/projects/api/limbs?project_slug=${encodeURIComponent(slug)}`), api.get(`${base}/runs`), api.get(`/projects/api/${slug}/agents`)]);
        if (alive) setAgents(agentData.agents || []);
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
    if (!definition) throw new Error(uiText("flowSurface.pipelineHasNotLoaded"));
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
    if (!single && batch && !selection) throw new Error(uiText("flowSurface.selectRowsInTheTableOrTurnOffSelected"));
    if (!single && batch && selection?.capability && !input.start_node_id) throw new Error(uiText("flowSurface.noStepMatchesThisCellSelectAStartingStep"));
    input.definition_revision = saved.revision;
    const data = await api.post(`${base}/preflight`, input);
    if (single && sourceDoc && data.source_revisions[sourceKey] !== sourceDoc.revision) throw new Error(uiText("flowSurface.theSourceChangedAfterTheSampleLoadedRefreshAnd"));
    setPreview(data); setPreviewInput(input); setAdding(false);
  });
  const execute = () => work(async () => {
    if (!preview?.ready || dirty) throw new Error(uiText("flowSurface.reviewTheRunScopeAgain"));
    const data = await api.post(`${base}/runs`, { ...previewInput, source_revisions: preview.source_revisions });
    setDetail(data); setRunId(data.run.id); setRuns((old) => [data.run, ...old.filter((run) => run.id !== data.run.id)]);
    setPreview(null); setResultsOpen(true); onToast?.(uiText("flowSurface.queuedForExecutionNotCompleteYet"));
  });
  const control = (action) => work(async () => { const data = await api.post(`${base}/runs/${runId}/${action}`, {}); setDetail(data); onToast?.(action === "cancel" ? uiText("flowSurface.remainingTasksCanceled") : uiText("flowSurface.retryingIncompleteTasksWithTheOriginalSettings")); });
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
  // A step added from a node's + lands to its right, waits for it and keeps the same rows.
  const add = (kind, after = null) => {
    const source = after && definition.nodes.find((node) => node.id === after);
    const node = { ...createStep(kind, newId(), definition.nodes.length), ...(source ? { x: (source.x ?? 0) + 340, y: source.y ?? 0, scope: source.scope,
      ...(source.row_source ? { row_source: source.row_source } : {}), input_tabs: source.input_tabs || [] } : {}) };
    while (definition.nodes.some((other) => Math.abs((other.x ?? 0) - node.x) < 280 && Math.abs((other.y ?? 0) - node.y) < 150)) node.y += 190;
    let next = { ...definition, nodes: [...definition.nodes, node] };
    try { if (source) next = connectNodes(next, source.id, node.id); } catch (problem) { report(problem); return; }
    change(next); select(node.id);
  };
  const tidy = () => { change(tidyLayout(definition)); setTimeout(() => instance.current?.fitView({ ...initialFitOptions, duration: 250 }), 60); };

  return <section className="canvas flow-workspace" aria-label={uiText("flowSurface.pipelineEditor")} onKeyDown={keyboard}>
    <header className="flow-topbar"><div className="flow-heading"><strong>{tab.title}</strong><small role="status">{busy ? uiText("flowSurface.processing") : dirty ? uiText("flowSurface.notSaved") : uiText("flowSurface.savedV", {v0: (revision)})}</small></div><div className="flow-top-actions">
      <button title={uiText("flowSurface.undoCtrlZ")} disabled={!writable || busy || !history.past.length} onClick={() => { setHistory(undoDefinition); setPreview(null); }}>{uiText("flowSurface.undo")}</button><button title={uiText("flowSurface.redoCtrlShiftZ")} disabled={!writable || busy || !history.future.length} onClick={() => { setHistory(redoDefinition); setPreview(null); }}>{uiText("flowSurface.redo")}</button><button disabled={busy} onClick={() => work(async () => { if (dirty) await save(); onSwitchDocMode(); })}>{uiText("flowSurface.document")}</button>
      {writable && <><button disabled={busy || !definition || definition.nodes.length >= 100} onClick={() => { setAdding(!adding); setSelectedIds([]); setPreview(null); }}>{uiText("flowSurface.addStep")}</button><button disabled={busy || !dirty} onClick={() => work(save)}>{uiText("flowSurface.save")}</button><button className="primary" disabled={busy || !definition?.nodes.length} onClick={() => check(false)}>{uiText("flowSurface.reviewRun")}</button></>}
    </div></header>
    {error && <div className="flow-feedback" role="alert"><span>{error}</span><button aria-label={uiText("flowSurface.dismissError")} onClick={() => setError("")}>×</button></div>}
    <div className={`flow-main ${selected || adding || preview || selectedId === START ? "with-panel" : ""}`}><div className="flow-stage">
      <div className="flow-canvas-tools"><label><input placeholder={uiText("flowSurface.searchSteps")} aria-label={uiText("flowSurface.searchSteps2")} value={search} onChange={(event) => setSearch(event.target.value)} /></label>{search && <div className="flow-search-results">{definition?.nodes.filter((node) => node.title.toLocaleLowerCase().includes(search.toLocaleLowerCase())).map((node) => <button key={node.id} onClick={() => { focusNode(node.id); setSearch(""); }}>{node.title}</button>)}</div>}<span>{uiText("flowSurface.steps", {v0: (definition?.nodes.length || 0)})}</span>{writable && definition?.nodes.length > 1 && <button disabled={busy} onClick={tidy}><Icon name="tidy" />{uiText("flowSurface.tidy")}</button>}<button disabled={!runId} onClick={() => setResultsOpen(!resultsOpen)}>{resultsOpen ? uiText("flowSurface.collapseResults") : uiText("flowSurface.resultsHistory")}{detail && ` · ${TASK_LABELS[detail.run.status]}`}</button></div>
      {!definition ? <p className="flow-empty-message" role="status">{uiText("flowSurface.loadingPipeline")}</p> : <ReactFlow colorMode="dark" nodes={canvas.nodes} edges={canvas.edges} nodeTypes={nodeTypes} onInit={(flow) => { instance.current = flow; }}
        onNodesChange={nodeChanges} onEdgesChange={(changes) => { const selections = changes.filter((item) => item.type === "select"); if (selections.length) setSelectedEdgeIds((ids) => selections.reduce((current, item) => item.selected ? [...current.filter((id) => id !== item.id), item.id] : current.filter((id) => id !== item.id), ids)); if (!writable || busy) return; const ids = changes.filter((item) => item.type === "remove").map((item) => item.id); if (ids.length) change((current) => ({ ...current, edges: current.edges.filter((edge) => !ids.includes(`${edge.source}--${edge.target}`)) })); }}
        onNodeClick={(_, node) => { setAdding(false); setPreview(null); setPickerFor(null); setSelectedIds((ids) => ids.includes(node.id) ? ids : [node.id]); }} onPaneClick={() => select(null)}
        onNodeDragStart={() => { dragStart.current = definition; }} onNodeDragStop={() => { const before = dragStart.current; dragStart.current = null; if (before) setHistory((old) => JSON.stringify(before) === JSON.stringify(old.present) ? old : { ...old, past: [...old.past.slice(-49), before], future: [] }); }}
        onConnect={({ source, target }) => connect(source, target)} nodesDraggable={writable && !busy} nodesConnectable={writable && !busy} edgesReconnectable={false} deleteKeyCode={writable && !busy ? ["Backspace", "Delete"] : null}
        fitView fitViewOptions={initialFitOptions} minZoom={0.25} maxZoom={1.8} selectionOnDrag panOnDrag={[1, 2]} panOnScroll zoomOnScroll={false} zoomOnPinch selectionKeyCode="Shift" multiSelectionKeyCode="Shift"
        ariaLabelConfig={{ "controls.ariaLabel": uiText("flowSurface.controlPanel"), "controls.zoomIn.ariaLabel": uiText("flowSurface.zoomIn"), "controls.zoomOut.ariaLabel": uiText("flowSurface.zoomOut"), "controls.fitView.ariaLabel": uiText("flowSurface.fitView"), "node.a11yDescription.default": uiText("flowSurface.nodeKeyboard"), "edge.a11yDescription.default": uiText("flowSurface.edgeKeyboard") }}>
        <Background gap={24} size={1} color="#2a2a2a" /><Controls showInteractive={false} />{!definition.nodes.length && <div className="flow-empty-message"><strong>{uiText("flowSurface.startWithAProductionTask")}</strong><p>{uiText("flowSurface.addAStepSelectItsSourceAndTestOne")}</p>{writable && <button className="primary" onClick={() => setAdding(true)}>{uiText("flowSurface.addTheFirstStep")}</button>}</div>}
      </ReactFlow>}
      <p className="flow-navigation-help">{uiText("flowSurface.dragToSelectMiddleRightDragToPanShift")}</p>
    </div>
      {adding && <aside className="flow-sidepanel" aria-label={uiText("flowSurface.addPipelineStep")}><div className="flow-panel-title"><strong>{uiText("flowSurface.chooseATask")}</strong><button aria-label={uiText("flowSurface.closeAddStep")} onClick={() => setAdding(false)}>×</button></div><div className="flow-kind-list">{Object.entries(STEP_KINDS).map(([kind, preset]) => <button key={kind} onClick={() => add(kind)}><strong>{uiText("stepTitles." + kind)}</strong><small>{uiText("stepDescriptions." + kind)}</small></button>)}</div></aside>}
      {selectedId === START && !preview && !adding && <aside className="flow-sidepanel" aria-label={uiText("flowSurface.runScopeTitle")}><div className="flow-panel-title"><strong>{uiText("flowSurface.runScopeTitle")}</strong><button aria-label={uiText("flowSurface.closeAddStep")} onClick={() => select(null)}>×</button></div>
        <div className="flow-step-form"><label className="flow-check"><input type="checkbox" checked={batch} onChange={(event) => setBatch(event.target.checked)} />{uiText("flowSurface.useSelectedTableRows")}</label>{selection && <p className="flow-muted">{uiText("flowSurface.rows", {v0: (tabs.find((item) => item.key === selection.target_tab)?.title || selection.target_tab), v1: (selection.row_ids.length)})}</p>}
          <label>{uiText("flowSurface.startingStep")}<select value={startNode || (batch && definition ? redrawStart(definition, selection) : "")} onChange={(event) => setStartNode(event.target.value)}><option value="">{uiText("flowSurface.runAll")}</option>{definition?.nodes.map((node) => <option value={node.id} key={node.id}>{uiText("flowSurface.andAllDownstreamSteps", {v0: (node.title)})}</option>)}</select></label>
          <p className="flow-muted">{uiText("flowSurface.continuingStartsANewRunWithoutReusingEarlierUpstream")}</p></div>
        {writable && <div className="flow-test-action"><button className="primary" disabled={busy || !definition?.nodes.length} onClick={() => check(false)}>{uiText("flowSurface.reviewRun")}</button></div>}</aside>}
      {preview && <FlowPreflight preview={preview} busy={busy} writable={writable} onClose={() => setPreview(null)} onFocus={focusNode} onExecute={execute} />}
      {selected && !preview && !adding && <FlowInspector {...{ selected, selectedId, definition, tabs, tab, workers, agents, writable, busy, sourceDoc, sourceTables, sourceTable, targetTables, targetTable, sourceKey, targetKey, samples, sampleRow, update, change, connect }}
        onEditStart={() => { editStart.current = definition; }} onEditEnd={finishEdit}
        tasks={tasks.filter((task) => task.node_id === selectedId)} onClose={() => select(null)} onSample={(id) => { setSampleRow(id); setPreview(null); }} onRemove={() => removeNodes([selectedId])} onTest={() => check(true)} onResults={() => setResultsOpen(true)}
        onRefresh={() => work(async () => { setSourceDoc(docResponse(await api.get(`/projects/api/${slug}/tabs/${sourceKey}`))); setPreview(null); })} />}
    </div>
    {resultsOpen && <FlowResults {...{ detail, tasks, runs, runId, canControl, busy, revision, tabs, me, onOpenProposals, onOpenSource }} progress={summarizeTasks(tasks)} onRun={setRunId} onClose={() => setResultsOpen(false)} onFocus={focusNode} onControl={control} />}
  </section>;
}
