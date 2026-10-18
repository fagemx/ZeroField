import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "./api.js";
import { AnnotationPanel, LinkIcon, NoteIcon, PenIcon, VIEW_LABEL, ViewMenu, todoCount } from "./Annotations.jsx";
import { anchorsOf } from "./docText.js";
import { DocSurface } from "./DocSurface.jsx";
import { HistoryPanel } from "./History.jsx";
import { parseLocation, tabHash } from "./route.js";
import { isOpen } from "./rules.js";
import { TabRail } from "./TabRail.jsx";
import { IdentityBadge, PROJECT_STATUS, ProjectHub, SurfaceHeader } from "./Surfaces.jsx";
import { FlowSurface, SheetSurface } from "./CanvasViews.jsx";
import { WorkspaceSettings } from "./WorkspaceSettings.jsx";
import { AssistantSide, AssistantWorkspace } from "./assistant/AssistantViews.jsx";
import { appliedLabel, assistRows, waitingCount } from "./assistant/text.js";
import { useAssistant } from "./assistant/useAssistant.js";
import { assignmentRequest } from './assistant/orchestrationModel.js';
import "./assistant/assistant.css";
import "./workbench.css";

const POLL_MS = 20000;

function useToast() {
  const [toast, setToast] = useState(null);
  const timer = useRef(null);
  const show = useCallback((message, kind = "info") => {
    clearTimeout(timer.current);
    setToast({ message, kind });
    timer.current = setTimeout(() => setToast(null), kind === "error" ? 6000 : Math.max(3000, String(message).length * 90));
  }, []);
  return [toast, show];
}

// 只影響自己畫面的設定（標記檢視、顯示已解決）：存在瀏覽器裡，讀不到就用預設
function usePref(key, fallback) {
  const [value, setValue] = useState(() => {
    try {
      const raw = window.localStorage.getItem(key);
      return raw === null ? fallback : JSON.parse(raw);
    } catch {
      return fallback;
    }
  });
  const set = useCallback((next) => {
    setValue(next);
    try { window.localStorage.setItem(key, JSON.stringify(next)); } catch { /* 私密視窗等情況存不了，沒關係 */ }
  }, [key]);
  return [value, set];
}

function ProjectList() {
  const [state, setState] = useState({ loading: true });
  const load = useCallback(() => {
    api.get("/projects/api/projects").then((data) => setState({ data })).catch((error) => setState({ error: error.message }));
  }, []);
  useEffect(() => { load(); }, [load]);
  if (state.loading) return <div className="center-note">Loading…</div>;
  if (state.error) return <div className="center-note">{state.error}</div>;
  return <ProjectHub data={state.data} onReload={load} />;
}

export function App() {
  const initial = useMemo(() => parseLocation(window.location.pathname, window.location.hash), []);
  if (!initial.slug) return <ProjectList />;
  return <ProjectPage slug={initial.slug} />;
}

function ProjectPage({ slug }) {
  const [data, setData] = useState(null);
  const [fatal, setFatal] = useState(null);
  const [tabKey, setTabKey] = useState(() => parseLocation(window.location.pathname, window.location.hash).tab);
  const [docs, setDocs] = useState({});
  const [focusId, setFocusId] = useState(null);
  const [focusRequest, setFocusRequest] = useState(null);
  const [flashId, setFlashId] = useState(null);
  const [panel, setPanel] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false); // 修改紀錄
  const pendingFlash = useRef(null); // 修改紀錄點到別頁的一處：換頁後再亮
  const [section, setSection] = useState(null);
  const [viewMenu, setViewMenu] = useState(null);
  const [view, setView] = usePref("projects.view", "all");
  const [showResolved, setShowResolved] = usePref("projects.showResolved", false);
  const [attachId, setAttachId] = useState(null);
  const [railOpen, setRailOpen] = useState(false);
  const [railHidden, setRailHidden] = useState(false);
  const [toast, showToast] = useToast();
  const surfaceControl = useRef(null);
  const [versionsFor, setVersionsFor] = useState(null); // 左邊「⋯ → 找回以前的內容…」：換到那一頁後打開版本紀錄
  const [docModeTabs, setDocModeTabs] = useState({});
  const versionsShown = useCallback(() => setVersionsFor(null), []);
  const annSeq = useRef(0);
  const pendingFocus = useRef((() => {
    const thread = parseLocation(window.location.pathname, window.location.hash).thread;
    return thread && /^a\d+$/.test(thread) ? thread.slice(1) : null;
  })());
  const flashTimer = useRef(null);

  const onError = useCallback((message) => showToast(message, "error"), [showToast]);

  const loadProject = useCallback(async () => {
    const seq = annSeq.current;
    try {
      const payload = await api.get(`/projects/api/${slug}`);
      setData((current) => {
        // 送出請求後自己又改了標註：這次的清單比較舊，留著自己的
        if (current && seq !== annSeq.current) return { ...payload, annotations: current.annotations };
        return payload;
      });
      document.title = payload.project.title;
      return payload;
    } catch (error) {
      setData((current) => {
        if (!current) setFatal(error);
        else onError(error.message);
        return current;
      });
      return null;
    }
  }, [slug, onError]);

  useEffect(() => { loadProject(); }, [loadProject]);

  const loadTab = useCallback(async (key, force = false) => {
    if (!key) return null;
    try {
      const payload = await api.get(`/projects/api/${slug}/tabs/${key}`);
      setDocs((current) => {
        const cached = current[key];
        // 自己剛存完的比較新，不要被晚到的回應蓋掉
        if (!force && cached) return current;
        if (cached && cached.updated_at && payload.tab.updated_at && payload.tab.updated_at < cached.updated_at) return current;
        return { ...current, [key]: payload.tab };
      });
      return payload.tab;
    } catch (error) {
      onError(error.message);
      return null;
    }
  }, [slug, onError]);

  // 決定目前分頁：網址上的、不然第一個
  useEffect(() => {
    if (!data) return;
    const keys = data.tabs.map((t) => t.key);
    if (!tabKey || !keys.includes(tabKey)) {
      const first = keys[0];
      if (first) {
        setTabKey(first);
        window.history.replaceState(null, "", tabHash(first));
      }
    }
  }, [data, tabKey]);

  useEffect(() => {
    if (!tabKey || !data) return;
    const meta = data.tabs.find((t) => t.key === tabKey);
    const cached = docs[tabKey];
    if (!cached) loadTab(tabKey, true);
    else if (meta && meta.updated_at && meta.updated_at > (cached.updated_at || "")) loadTab(tabKey, true);
  }, [tabKey, data && data.tabs]); // eslint-disable-line react-hooks/exhaustive-deps

  // 其他分頁背景先讀好：切換比較快，清單上的「整列」也叫得出名字
  useEffect(() => {
    if (!data) return undefined;
    let alive = true;
    (async () => {
      for (const t of data.tabs) {
        if (!alive) return;
        if (!docs[t.key]) await loadTab(t.key);
      }
    })();
    return () => { alive = false; };
  }, [data && data.tabs.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const focusAnnotation = useCallback((id, opts = {}) => {
    setFocusId(id === null || id === undefined ? null : id);
    if (id !== null && id !== undefined && (opts.scroll || opts.flash)) setFocusRequest({ id, at: Date.now() });
    if (opts.flash && id !== null && id !== undefined) {
      clearTimeout(flashTimer.current);
      setFlashId(id);
      flashTimer.current = setTimeout(() => setFlashId(null), 1300);
    }
  }, []);

  // 網址帶著標註（#分頁~a123）：打開那一則
  useEffect(() => {
    const id = pendingFocus.current;
    if (!id || !data || !tabKey || !docs[tabKey]) return;
    const target = data.annotations.find((a) => String(a.id) === id);
    pendingFocus.current = null;
    if (!target) return;
    if (target.tab_key !== tabKey) {
      pendingFocus.current = id;
      setTabKey(target.tab_key);
      return;
    }
    focusAnnotation(target.id, { scroll: true, flash: true });
  }, [data, tabKey, docs, focusAnnotation]);

  useEffect(() => {
    const onHash = async () => {
      const next = parseLocation(window.location.pathname, window.location.hash);
      if (next.thread && /^a\d+$/.test(next.thread)) pendingFocus.current = next.thread.slice(1);
      if (next.tab && next.tab !== tabKey) {
        if (surfaceControl.current && !(await surfaceControl.current.flush())) { window.history.replaceState(null, "", tabHash(tabKey)); return; }
        setFocusId(null);
        setTabKey(next.tab);
        window.scrollTo(0, 0);
      }
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [tabKey]);

  // 每 20 秒抓一次：別人的標註、狀態、鎖、內文（視窗在前景才抓）
  useEffect(() => {
    const timer = setInterval(async () => {
      if (document.visibilityState !== "visible") return;
      const payload = await loadProject();
      if (!payload || !tabKey) return;
      const meta = payload.tabs.find((t) => t.key === tabKey);
      const cached = docs[tabKey];
      if (meta && cached && meta.updated_at && meta.updated_at > (cached.updated_at || "")) loadTab(tabKey, true);
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [tabKey, docs, loadProject, loadTab]);

  const navigate = useCallback(async (key) => {
    setRailOpen(false);
    if (key === tabKey) return true;
    if (surfaceControl.current && !(await surfaceControl.current.flush())) return false;
    window.history.pushState(null, "", tabHash(key));
    setFocusId(null);
    setTabKey(key);
    window.scrollTo(0, 0);
    return true;
  }, [tabKey]);

  const refreshLater = useRef(null);
  const setField = useCallback(async (fid, value) => {
    const key = tabKey;
    const me = data.me;
    const before = data.values[key] && data.values[key][fid];
    setData((current) => ({
      ...current,
      values: { ...current.values, [key]: { ...(current.values[key] || {}), [fid]: { ...(before || {}), value, by: me.actor_id, by_name: me.name, at: new Date().toISOString() } } },
    }));
    try {
      const result = await api.post(`/projects/api/${slug}/fields`, { tab_key: key, field_id: fid, value });
      setData((current) => ({
        ...current,
        values: { ...current.values, [key]: { ...(current.values[key] || {}), [fid]: result.value } },
      }));
      // 狀態紀錄掛在那一列的對話上：重新讀一次標註
      clearTimeout(refreshLater.current);
      refreshLater.current = setTimeout(() => loadProject(), 300);
      return true;
    } catch (error) {
      setData((current) => {
        const values = { ...(current.values[key] || {}) };
        if (before) values[fid] = before; else delete values[fid];
        return { ...current, values: { ...current.values, [key]: values } };
      });
      onError(error.message);
      return false;
    }
  }, [slug, tabKey, data, onError, loadProject]);

  const onAnnotation = useCallback((update) => {
    annSeq.current += 1;
    setData((current) => {
      if (!current) return current;
      if (update && update.deleted !== undefined) {
        return { ...current, annotations: current.annotations.filter((a) => String(a.id) !== String(update.deleted)) };
      }
      const exists = current.annotations.some((a) => a.id === update.id);
      return {
        ...current,
        annotations: exists ? current.annotations.map((a) => (a.id === update.id ? update : a)) : [...current.annotations, update],
      };
    });
  }, []);

  const onAnnotations = useCallback((list) => {
    annSeq.current += 1;
    setData((current) => (current ? { ...current, annotations: list } : current));
  }, []);

  const onSaved = useCallback((result) => {
    setDocs((current) => {
      const tab = current[tabKey];
      if (!tab) return current;
      return { ...current, [tabKey]: { ...tab, doc: result.doc, revision: result.revision, updated_at: result.saved_at,
        updated_by_name: data ? data.me.name : tab.updated_by_name, title: result.title || tab.title } };
    });
    setData((current) => ({ ...current, tabs: current.tabs.map((t) => (t.key === tabKey
      ? { ...t, revision: result.revision, updated_at: result.saved_at, title: result.title || t.title } : t)) }));
  }, [tabKey, data]);

  const pick = useCallback(async (a) => {
    if (a.orphaned_at) { showToast("Source text not found. Use Reattach to select a new location."); return; }
    setPanel(false);
    if (a.tab_key !== tabKey) {
      if (surfaceControl.current && !(await surfaceControl.current.flush())) return;
      window.history.pushState(null, "", tabHash(a.tab_key));
      setTabKey(a.tab_key);
    }
    focusAnnotation(a.id, { scroll: true, flash: true });
  }, [tabKey, focusAnnotation, showToast]);

  const reattach = useCallback(async (a) => {
    setPanel(false);
    setAttachId(a.id);
    if (a.tab_key !== tabKey) await navigate(a.tab_key);
    showToast("Select text, then choose Attach Here in the toolbar.");
  }, [tabKey, navigate, showToast]);

  const resolveFromPanel = useCallback(async (a) => {
    try {
      const result = await api.post(`/projects/api/${slug}/annotations/${a.id}/resolve`, { resolved: true });
      onAnnotation(result.annotation);
    } catch (error) {
      onError(error.message);
    }
  }, [slug, onAnnotation, onError]);

  const copyLink = async () => {
    const thread = focusId && /^\d+$/.test(String(focusId)) ? `a${focusId}` : null;
    const url = `${window.location.origin}/projects/${slug}/${tabHash(tabKey, thread)}`;
    try {
      await navigator.clipboard.writeText(url);
      showToast(thread ? "Annotation link copied" : "Page link copied");
    } catch {
      window.prompt("Copy this link:", url);
    }
  };

  const rowLabels = useMemo(() => {
    const out = {};
    if (!data) return out;
    const cache = {};
    for (const a of data.annotations) {
      if (a.kind !== "row") continue;
      const tab = docs[a.tab_key];
      if (!tab) continue;
      if (!cache[a.tab_key]) cache[a.tab_key] = anchorsOf(tab.doc);
      out[a.id] = cache[a.tab_key][a.anchor.rid] || "this row";
    }
    return out;
  }, [data, docs]);

  const narrow = () => window.matchMedia("(max-width: 860px)").matches;
  const [paMode, setPaMode] = useState("off");    // off｜side｜full；需要協助時再展開，先留空間閱讀內容
  const [paView, setPaView] = useState("chat");   // chat｜manage（管理者才有）
  const [paFocus, setPaFocus] = useState(null);
  const [paDraft, setPaDraft] = useState("");
  const [sheetFocus, setSheetFocus] = useState(null);
  const paInput = useRef(null);
  const paEnabled = Boolean(data && data.assistant && data.assistant.enabled);
  const onApplied = useCallback((proposal, notes) => {
    loadProject();
    const key = proposal && proposal.target && proposal.target.tab_key;
    if (key) loadTab(key, true);
    if (proposal && proposal.status === "applied") {
      showToast(appliedLabel(proposal) + "：" + ((proposal.target && proposal.target.display) || ""));
    }
    else if (proposal && proposal.status === "failed") showToast("Could not apply:" + (proposal.error || ""), "error");
    if (notes && notes.length) showToast(notes.join(" "));
  }, [loadProject, loadTab, showToast]);
  const assistant = useAssistant(slug, paEnabled, paMode !== "off", onError, onApplied, data?.project?.privacy_mode);
  const paRows = useMemo(() => (paEnabled ? assistRows(assistant.state && assistant.state.todo) : null),
    [paEnabled, assistant.state]);
  const openAssistant = useCallback(() => {
    setPanel(false);
    setHistoryOpen(false);
    setPaMode(narrow() ? "full" : "side");
  }, []);
  const onSurfacePanel = useCallback((open) => {
    if (open) { setPaMode("off"); setPanel(false); setHistoryOpen(false); }
  }, []);
  const askAssistant = useCallback((text, focus, scope = null) => {
    assistant.setScope(scope);
    setPaDraft(text);
    setPaFocus(focus || null);
    setPaView("chat");
    setPanel(false);
    setHistoryOpen(false);
    setPaMode((current) => (current === "off" ? (narrow() ? "full" : "side") : current));
    setTimeout(() => paInput.current && paInput.current.focus(), 60);
  }, [assistant.setScope]);
  const assignBackground = useCallback(async (text, scope, options = null) => {
    if (!options?.strategy) { askAssistant(text, null, scope); return true; }
    if (surfaceControl.current && !(await surfaceControl.current.flush())) throw new Error("Save the source and resolve editing conflicts first.");
    const request = assignmentRequest({ objective: text, scope, target: options.target, strategy: options.strategy,
      agentKey: options.agentKey, raceAgents: options.raceAgents, mode: options.writeMode || 'proposal', requestId: options.requestId });
    await assistant.startRun(request);
    setPaView('agents'); openAssistant(); showToast("Task queued. Results will be available for review.");
    return true;
  }, [assistant.startRun, askAssistant, openAssistant, showToast]);
  const onAgentRouted = useCallback(async request => {
    assistant.setSelectedAgent(request.agent_key); setPaView('chat'); openAssistant();
    await assistant.reload(); showToast("Comment sent to the agent. The reply will appear in Studio Assistant.");
  }, [assistant.setSelectedAgent, assistant.reload, openAssistant, showToast]);
  // 點專案頁那一列的「✦ 一起回答」：打開助理、直接開始（上一句還在答時，先放進輸入框）
  const onAssistRow = useCallback(async (rid) => {
    const item = ((assistant.state && assistant.state.todo) || []).find((i) => i.rid === rid);
    const row = paRows && paRows.get(rid);
    if (!item || !row) return;
    const focus = item.kind === "question" ? { kind: "question", number: item.number }
      : { kind: "handoff", rid: item.rid, text: item.text };
    if (assistant.busy || assistant.sending) {
      askAssistant(row.prompt, focus);
      return;
    }
    askAssistant("", focus);
    const sent = await assistant.send(row.prompt);
    if (!sent) setPaDraft(row.prompt);
  }, [assistant, paRows, askAssistant]);
  const openFromAssistant = useCallback(async (key) => {
    const target = typeof key === 'string' ? { tab_key: key } : key;
    if (!target?.tab_key) return;
    if (paMode === "full") setPaMode(narrow() ? "off" : "side");
    if (await navigate(target.tab_key)) {
      if (target.row_id) {
        let tableId = target.table_id;
        if (!tableId) {
          const loaded = await api.get(`/projects/api/${slug}/tabs/${target.tab_key}`);
          tableId = loaded.tab.doc.content.find(node => node.type === 'table' && node.content.some(row => row.attrs?.bid === target.row_id))?.attrs.bid;
        }
        setSheetFocus({ tabKey: target.tab_key, tableId, rowId: target.row_id, colIndex: target.col_index ?? 0, nonce: Date.now() });
      }
      if (target.block_id && !surfaceControl.current?.flashUnit?.(target.block_id)) pendingFlash.current = target.block_id;
    }
  }, [paMode, navigate, slug]);
  const starter = useCallback((text) => askAssistant(text, null), [askAssistant]);

  // ---------- 修改紀錄 ----------
  const closeHistory = useCallback(() => setHistoryOpen(false), []);
  const flashChange = useCallback((id) => {
    const control = surfaceControl.current;
    return Boolean(control && control.flashUnit && control.flashUnit(id));
  }, []);
  const pickChange = useCallback(async (group, change) => {
    const id = change.anchor_id || change.rid || change.bid;
    if (!id) return;
    if (narrow()) setHistoryOpen(false); // 手機上清單蓋住內文：先收起來才看得到亮的那一段
    if (group.tab_key !== tabKey) {
      pendingFlash.current = id;
      await navigate(group.tab_key);
      return;
    }
    if (!flashChange(id)) {
      showToast(change.change === "removed" ? `This content was deleted. Use “${change.button}” to restore it.` : "This content is no longer on the page.");
    }
  }, [tabKey, navigate, flashChange, showToast]);
  useEffect(() => {
    const id = pendingFlash.current;
    if (!id || !docs[tabKey]) return undefined;
    let tries = 0;
    let timer = null;
    const attempt = () => {
      if (pendingFlash.current !== id) return;
      if (flashChange(id)) { pendingFlash.current = null; return; }
      tries += 1;
      if (tries > 20) { pendingFlash.current = null; showToast("This content is no longer on the page."); return; }
      timer = setTimeout(attempt, 150);
    };
    timer = setTimeout(attempt, 100);
    return () => clearTimeout(timer);
  }, [tabKey, docs, flashChange, showToast]);
  const onReverted = useCallback((key, result, isField) => {
    if (!isField) loadTab(key, true);
    loadProject();
  }, [loadTab, loadProject]);
  const flushSurface = useCallback(async () => (surfaceControl.current ? surfaceControl.current.flush() : true), []);

  if (fatal) {
    return (
      <div className="center-note">
        <p>{fatal.status === 404 ? "Production not found." : fatal.message}</p>
        <button type="button" className="ghost" onClick={() => window.location.reload()}>Refresh</button>
      </div>
    );
  }
  if (!data) return <div className="center-note">Loading…</div>;

  const me = data.me;
  const tabs = data.tabs;
  const tab = tabKey ? docs[tabKey] : null;
  const todo = todoCount(data.annotations, me);
  const openCount = (key) => data.annotations.filter((a) => a.tab_key === key && isOpen(a) && !a.orphaned_at).length;
  return (
    <div className={"app workbench-app surface-" + (tab?.surface_type || "doc") + (railHidden ? " rail-off" : "") + (railOpen ? " rail-open" : "") + (me.can_edit ? " can-edit" : "")
      + (paMode === "side" ? " pa-on" : "") + (paMode === "full" ? " ws-on" : "")}>
      <header className="top">
        <button type="button" className="icon-btn" onClick={() => (window.innerWidth <= 860 ? setRailOpen(!railOpen) : setRailHidden(!railHidden))}
          aria-label={"Toggle pages"}>☰ <span className="label">Pages</span></button>
        <a href="/projects/" className="icon-btn" title={"Back to productions"} style={{ textDecoration: "none" }}>← <span className="label">All Productions</span></a>
        <span className="doc-name">{data.project.title}</span>
        {data.project.status && PROJECT_STATUS[data.project.status] && (
          <span style={{
            fontSize: 12, fontWeight: 600, padding: "2px 8px", borderRadius: 999,
            color: PROJECT_STATUS[data.project.status].color,
            background: PROJECT_STATUS[data.project.status].bg,
          }}>
            {PROJECT_STATUS[data.project.status].label}
          </span>
        )}
        <span className="spacer" />
        <button type="button" id="viewBtn" className={"icon-btn" + (viewMenu ? " on" : "")} title={"Choose which highlights and underlines to show"}
          onClick={(event) => setViewMenu(viewMenu ? null : event.currentTarget.getBoundingClientRect())}>
          <PenIcon /><span className="label">{VIEW_LABEL[view] || VIEW_LABEL.all}</span> ▾
        </button>
        <button type="button" id="annBtn" className={"icon-btn" + (panel ? " on" : "")} title={"Annotations: Needs You and All"}
          onClick={() => { setPanel(!panel); setHistoryOpen(false); if (!panel && paMode === "side") setPaMode("off"); }}>
          <NoteIcon /><span className="label">Annotations</span>{todo > 0 && <span className="count">{todo}</span>}
        </button>
        {paEnabled && (
          <button type="button" className={"icon-btn pa-btn" + (paMode !== "off" ? " on" : "")} title={"Studio Assistant"}
            onClick={() => { if (paMode === 'off') { if (assistant.orchestrationCounts?.needs_you || assistant.orchestrationCounts?.working) setPaView('agents'); openAssistant(); } else setPaMode('off'); }}>
            <span className="spark">✦</span><span className="label">Studio Assistant</span>
            {paMode === 'off' && assistant.orchestrationCounts?.needs_you > 0 && <span className="count">? {assistant.orchestrationCounts.needs_you}</span>}
            {paMode === 'off' && assistant.orchestrationCounts?.working > 0 && <span className="count">⟳ {assistant.orchestrationCounts.working}</span>}
          </button>
        )}
        <button type="button" className="icon-btn" onClick={copyLink} title={"Copy a link to this page or annotation"} aria-label={"Copy Link"}>
          <LinkIcon /><span className="label">Copy Link</span>
        </button>
        <WorkspaceSettings me={me} project={data.project} onReload={loadProject} onError={onError} />
        <IdentityBadge me={me} members={data.members} />
      </header>
      <ViewMenu open={Boolean(viewMenu)} rect={viewMenu} view={view} showResolved={showResolved}
        onView={setView} onResolved={setShowResolved} onClose={() => setViewMenu(null)} />
      <AnnotationPanel open={panel} annotations={data.annotations} me={me} members={data.members} tabs={tabs}
        rowLabels={rowLabels} section={section} onSection={setSection} onPick={pick} onReattach={reattach}
        onResolve={resolveFromPanel} onClose={() => setPanel(false)} />
      <HistoryPanel open={historyOpen} slug={slug} tabKey={tabKey} tabTitle={tab ? tab.title : ""}
        version={tab ? tab.updated_at : ""} onPick={pickChange} onReverted={onReverted} flush={flushSurface}
        onClose={closeHistory} onError={onError} onToast={showToast} />
      <div className="layout">
        <TabRail slug={slug} tabs={tabs} me={me} tabKey={tabKey} openCount={openCount} onNavigate={navigate}
          onTabsChanged={(next) => setData((current) => ({ ...current, tabs: next }))}
          flush={async () => (surfaceControl.current ? surfaceControl.current.flush() : true)}
          onRenamed={(key) => { if (key === tabKey) loadTab(key, true); }}
          onVersions={async (key) => { if (await flushSurface() && await navigate(key)) setVersionsFor(key); }}
          onError={onError} onToast={showToast} />
        <main className="main">
          <div className="doc-host">
          {!tab && <div className="center-note">Loading…</div>}
          {tab && tab.surface_type === "sheet" && !versionsFor && !(docModeTabs && docModeTabs[tab.key]) && (
            <SheetSurface
              key={tab.key}
              controlRef={surfaceControl}
              me={me}
              tabs={tabs}
              slug={slug}
              tab={tab}
              values={data.values[tabKey]}
              annotations={data.annotations} locks={data.locks || []}
              focusRow={sheetFocus}
              onField={setField}
              onReloadTab={async () => { await loadTab(tab.key, true); await loadProject(); }}
              onAskAgent={paEnabled ? assignBackground : null}
              agents={assistant.state?.agents || []}
              onAgentRouted={onAgentRouted}
              assistantOpen={paMode !== "off" || panel || historyOpen}
              onPanelChange={onSurfacePanel}
              onSwitchDocMode={async () => { if (await flushSurface()) setDocModeTabs((prev) => ({ ...(prev || {}), [tab.key]: true })); }}
              onToast={showToast}
              onError={onError}
            />
          )}
          {tab && tab.surface_type === "flow" && !versionsFor && !(docModeTabs && docModeTabs[tab.key]) && (
            <FlowSurface
              key={tab.key}
              controlRef={surfaceControl}
              me={me}
              slug={slug}
              tab={tab}
              tabs={tabs}
              assistantOpen={paMode !== "off" || panel || historyOpen}
              onInspectorChange={onSurfacePanel}
              onOpenProposals={() => { assistant.reload(); openAssistant(); }}
              onOpenSource={async (target) => {
                if (await flushSurface() && await navigate(target.tabKey)) {
                  setSheetFocus({ ...target, nonce: Date.now() });
                  setPaMode("off");
                }
              }}
              values={data.values[tabKey]}
              onField={setField}
              onReloadTab={async () => { await loadTab(tab.key, true); await loadProject(); }}
              onAskAgent={paEnabled ? (prompt) => askAssistant(prompt, null) : null}
              onSwitchDocMode={async () => { if (await flushSurface()) setDocModeTabs((prev) => ({ ...(prev || {}), [tab.key]: true })); }}
              onToast={showToast}
              onError={onError}
            />
          )}
          {tab && (tab.surface_type === "doc" || !tab.surface_type || versionsFor || (docModeTabs && docModeTabs[tab.key])) && (
            <>
              <SurfaceHeader
                tab={tab}
                onAskAgent={paEnabled ? (prompt) => askAssistant(prompt, null) : null}
                onSwitchCanvasMode={async () => { if (await flushSurface()) setDocModeTabs((prev) => ({ ...(prev || {}), [tab.key]: false })); }}
              />
              <DocSurface key={tab.key} slug={slug} tab={tab} tabs={tabs} me={me} members={data.members}
                values={data.values[tabKey]} annotations={data.annotations} locks={data.locks || []}
                focusId={focusId} focusRequest={focusRequest} flashId={flashId} view={view} showResolved={showResolved}
                attachId={attachId} onField={setField} onFocus={focusAnnotation} onAnnotation={onAnnotation}
                onAnnotations={onAnnotations} onNavigate={navigate} onSaved={onSaved}
                versionsFor={versionsFor} onVersionsShown={versionsShown} onOpenPanel={(where) => { setSection(where); setPanel(true); }}
                onOpenHistory={() => { setHistoryOpen(!historyOpen); setPanel(false); if (paMode === "side") setPaMode("off"); }}
                onAttachDone={() => setAttachId(null)} onError={onError} onToast={showToast} controlRef={surfaceControl}
                assistRows={paRows} onAssistRow={onAssistRow} agents={assistant.state?.agents || []} onAgentRouted={onAgentRouted} />
            </>
          )}
          </div>
          {paEnabled && paMode === "full" && (
            <AssistantWorkspace assistant={assistant} me={me} tabs={tabs} slug={slug} focus={paFocus} onFocus={setPaFocus}
              draft={paDraft} onDraft={setPaDraft} inputRef={paInput} view={paView} onView={setPaView}
              onCollapse={() => setPaMode(narrow() ? "off" : "side")} onOpenTab={openFromAssistant} onStarter={starter}
              onError={onError} onToast={showToast} />
          )}
        </main>
      </div>
      {paEnabled && paMode === "side" && (
        <AssistantSide assistant={assistant} me={me} tabs={tabs} slug={slug} focus={paFocus} draft={paDraft}
          onDraft={setPaDraft} inputRef={paInput} view={paView} onView={setPaView} onExpand={() => setPaMode("full")}
          onClose={() => setPaMode("off")} onOpenTab={openFromAssistant} onStarter={starter} onError={onError} onToast={showToast} />
      )}
      {railOpen && <div className="rail-scrim" onClick={() => setRailOpen(false)} />}
      {toast && <div className={"toast " + toast.kind} role="status">{toast.message}</div>}
    </div>
  );
}
