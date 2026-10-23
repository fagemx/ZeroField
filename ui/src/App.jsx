import { LanguageSwitch } from './i18n/react.jsx';
import { useLocale } from './i18n/react.jsx';
import { t as uiText } from './i18n/index.js';
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "./api.js";
import { AgentConsoleApp } from './agentConsole/AgentConsoleApp.jsx';
import { consoleHash, consoleRoute } from './agentConsole/model.js';
import { AnnotationPanel, LinkIcon, NoteIcon, PenIcon, VIEW_LABEL, ViewMenu, todoCount } from "./Annotations.jsx";
import { anchorsOf } from "./docText.js";
import { DocSurface } from "./DocSurface.jsx";
import { HistoryPanel } from "./History.jsx";
import { parseLocation, tabHash } from "./route.js";
import { isOpen } from "./rules.js";
import { TabRail } from "./TabRail.jsx";
import { IdentityBadge, PROJECT_STATUS, ProjectHub, SurfaceHeader } from "./Surfaces.jsx";
import { STAGE_TAB, STORY_VIEW, CommandPalette, FilmOverlay, StudioTopBar, episodeCounts, spaceOf, useEpisode } from "./StudioShell.jsx";
import { StoryWorld } from "./StoryWorld.jsx";
import { AssetVaultModal, OpenApiModal, ToolboxModal } from "./StoryWorkbenchModals.jsx";
import { FlowSurface, SheetSurface } from "./CanvasViews.jsx";
import { WorkspaceSettings } from "./WorkspaceSettings.jsx";
import { AssistantSide, AssistantWorkspace } from "./assistant/AssistantViews.jsx";
import { appliedLabel, assistRows, waitingCount } from "./assistant/text.js";
import { useAssistant } from "./assistant/useAssistant.js";
import { assignmentRequest } from './assistant/orchestrationModel.js';
import "./assistant/assistant.css";
import "./workbench.css";
import { Icon } from "./Icon.jsx";

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
  const locale = useLocale();
  const [state, setState] = useState({ loading: true });
  const load = useCallback(() => {
    api.get("/projects/api/projects").then((data) => setState({ data })).catch((error) => setState({ error: error.message }));
  }, []);
  useEffect(() => { load(); }, [load]);
  if (state.loading) return <div className="center-note">{uiText("app.loading")}</div>;
  if (state.error) return <div className="center-note">{state.error}</div>;
  return <ProjectHub data={state.data} onReload={load} />;
}

export function App() {
  const locale = useLocale();
  const initial = useMemo(() => parseLocation(window.location.pathname, window.location.hash), []);
  if (!initial.slug) return <ProjectList />;
  return <ProjectPage slug={initial.slug} />;
}

function ProjectPage({ slug }) {
  const locale = useLocale();
  const [data, setData] = useState(null);
  const [fatal, setFatal] = useState(null);
  const expectedActor = useRef(null), [identityLost, setIdentityLost] = useState(false);
  const rememberedHash = () => {try {return sessionStorage.getItem('zf.production:'+slug) || '';} catch {return '';}};
  const [consoleView, setConsoleView] = useState(() => consoleRoute(window.location.hash));
  const [tabKey, setTabKey] = useState(() => parseLocation(window.location.pathname, consoleRoute(window.location.hash) ? rememberedHash() : window.location.hash).tab);
  const productionHash = useRef(consoleRoute(window.location.hash) ? rememberedHash() : window.location.hash);
  const productionReturnFocus = useRef(null);
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
  const [storyEpisode, setStoryEpisode] = useState(`ep_${slug}_01`);
  const [writingStatus, setWritingStatus] = useState(null), [writingFocus, setWritingFocus] = useState(null);
  const [paMode, setPaMode] = useState('off');
  const [paDraft, setPaDraft] = useState('');
  const [palette, setPalette] = useState(false), [filmOpen, setFilmOpen] = useState(false), [studioRail, setStudioRail] = useState(false), [studioModal, setStudioModal] = useState(null);
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
      if (expectedActor.current && payload.me.actor_id !== expectedActor.current) {
        // Do not upload, flush under the new cookie, or hand old private React state to a new actor.
        setIdentityLost(true); return null;
      }
      expectedActor.current = payload.me.actor_id;
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
    const studio = keys.includes(STAGE_TAB);
    if (studio && tabKey === STORY_VIEW) return;
    if (!tabKey || !keys.includes(tabKey)) {
      const first = studio ? STAGE_TAB : keys[0];
      if (first) {
        setTabKey(first);
        if (!consoleRoute(window.location.hash)) window.history.replaceState(null, "", tabHash(first));
      }
    }
  }, [data, tabKey]);

  useEffect(() => {
    if (!tabKey || !data || tabKey === STORY_VIEW) return;
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
      const consoleNext = consoleRoute(window.location.hash);
      if (consoleNext) {
        if (!consoleView && surfaceControl.current && !(await surfaceControl.current.flush())) {window.history.replaceState(null, '', productionHash.current || tabHash(tabKey));return;}
        if (!consoleView && data?.me?.actor_id) try {sessionStorage.setItem('zf.production:'+slug,productionHash.current || tabHash(tabKey));sessionStorage.setItem('zf.productionContext:'+slug+':'+data.me.actor_id,JSON.stringify({episodeId:storyEpisode,focus:surfaceControl.current?.consoleContext?.(),chatDraft:paDraft,dockMode:paMode}));} catch { /* Keep mounted context. */ }
        setConsoleView(consoleNext);
        return;
      }
      setConsoleView(null);
      requestAnimationFrame(() => (productionReturnFocus.current?.isConnected ? productionReturnFocus.current : document.querySelector('.workbench-app .top button'))?.focus());
      productionHash.current = window.location.hash;
      try {sessionStorage.setItem('zf.production:'+slug, window.location.hash);} catch { /* Keep mounted context. */ }
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
  }, [tabKey, consoleView, slug, data?.me?.actor_id, storyEpisode, paDraft, paMode]);

  useEffect(() => {
    if (!consoleView) return;
    document.querySelectorAll('.workbench-app video, .workbench-app audio').forEach(media => media.pause());
  }, [Boolean(consoleView)]);

  // 每 20 秒抓一次：別人的標註、狀態、鎖、內文（視窗在前景才抓）
  useEffect(() => {
    const timer = setInterval(async () => {
      if (document.visibilityState !== "visible" || consoleRoute(window.location.hash)) return;
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
    productionHash.current = tabHash(key);
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
    if (a.orphaned_at) { showToast(uiText("app.sourceTextNotFoundUseReattachToSelectA")); return; }
    setPanel(false);
    if (a.tab_key !== tabKey) {
      if (surfaceControl.current && !(await surfaceControl.current.flush())) return;
      window.history.pushState(null, "", tabHash(a.tab_key));
      setTabKey(a.tab_key);
    }
    if(a.kind==='row'&&a.anchor?.rid&&data?.tabs.find(item=>item.key===a.tab_key)?.surface_type==='sheet'){
      setSheetFocus({tabKey:a.tab_key,tableId:a.anchor.table_id,rowId:a.anchor.rid,colIndex:0,openRow:true,nonce:Date.now()});
      return;
    }
    focusAnnotation(a.id, { scroll: true, flash: true });
  }, [tabKey, focusAnnotation, showToast, data?.tabs]);

  const reattach = useCallback(async (a) => {
    setPanel(false);
    setAttachId(a.id);
    if (a.tab_key !== tabKey) await navigate(a.tab_key);
    showToast(uiText("app.selectTextThenChooseAttachHereInTheToolbar"));
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
      showToast(thread ? uiText("app.annotationLinkCopied") : uiText("app.pageLinkCopied"));
    } catch {
      window.prompt(uiText("app.copyThisLink"), url);
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
      out[a.id] = cache[a.tab_key][a.anchor.rid] || uiText("app.thisRow");
    }
    return out;
  }, [data, docs]);

  const narrow = () => window.matchMedia("(max-width: 860px)").matches;
  const [paView, setPaView] = useState("chat");   // chat｜manage（管理者才有）
  const [paFocus, setPaFocus] = useState(null);
  const [sheetFocus, setSheetFocus] = useState(null);
  useEffect(() => {
    if (!data?.me?.actor_id || !consoleRoute(window.location.hash)) return;
    try {const saved=JSON.parse(sessionStorage.getItem('zf.productionContext:'+slug+':'+data.me.actor_id));if(saved){setPaDraft(saved.chatDraft || '');if(['off','side','full'].includes(saved.dockMode))setPaMode(saved.dockMode);if(saved.episodeId)setStoryEpisode(saved.episodeId);if(saved.focus)setSheetFocus({...saved.focus,nonce:Date.now()});}} catch { /* Ignore unavailable or obsolete local context. */ }
  }, [slug,data?.me?.actor_id]);
  const paInput = useRef(null);
  const paEnabled = Boolean(data && data.assistant && data.assistant.enabled);
  const onApplied = useCallback((proposal, notes) => {
    loadProject();
    const key = proposal && proposal.target && proposal.target.tab_key;
    if (key) loadTab(key, true);
    if (proposal && proposal.status === "applied") {
      showToast(appliedLabel(proposal) + "：" + ((proposal.target && proposal.target.display) || ""));
    }
    else if (proposal && proposal.status === "failed") showToast(uiText("app.couldNotApply") + (proposal.error || ""), "error");
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
    if (surfaceControl.current && !(await surfaceControl.current.flush())) throw new Error(uiText("app.saveTheSourceAndResolveEditingConflictsFirst"));
    const request = assignmentRequest({ objective: text, scope, target: options.target, strategy: options.strategy,
      agentKey: options.agentKey, raceAgents: options.raceAgents, mode: options.writeMode || 'proposal', requestId: options.requestId });
    await assistant.startRun(request);
    setPaView('agents'); openAssistant(); showToast(uiText("app.taskQueuedResultsWillBeAvailableForReview"));
    return true;
  }, [assistant.startRun, askAssistant, openAssistant, showToast]);
  const onAgentRouted = useCallback(async request => {
    assistant.setSelectedAgent(request.agent_key); setPaView('chat'); openAssistant();
    await assistant.reload(); showToast(uiText("app.commentSentToTheAgentTheReplyWillAppear"));
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
      showToast(change.change === "removed" ? uiText("app.thisContentWasDeletedUseToRestoreIt", {v0: (change.button)}) : uiText("app.thisContentIsNoLongerOnThePage"));
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
      if (tries > 20) { pendingFlash.current = null; showToast(uiText("app.thisContentIsNoLongerOnThePage")); return; }
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
  const flushIdentity = useCallback(async () => {
    try {
      if (!surfaceControl.current || await surfaceControl.current.flush({reason:'identity'})) return true;
    } catch (error) { onError(error.message); return false; }
    onError(uiText('writing.integration.identityBlocked'));
    return false;
  }, [onError]);
  // Leaving the production (including sign-out links) honors the same save boundary.
  useEffect(() => {
    const leave = async event => {
      const link = event.target.closest?.('a[href]');
      if (!link || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || link.download || link.target === '_blank') return;
      const url = new URL(link.href, location.href);
      if (url.origin === location.origin && url.pathname === location.pathname) return;
      if (identityLost && url.pathname === '/login') return;
      event.preventDefault();
      const safe = /logout|signout/i.test(url.pathname) ? await flushIdentity() : await flushSurface();
      if (safe) location.assign(url.href);
    };
    document.addEventListener('click', leave);
    return () => document.removeEventListener('click', leave);
  }, [flushIdentity, flushSurface, identityLost]);
  const isStudio = Boolean(data?.tabs.some((t) => t.key === STAGE_TAB));
  const episode = useEpisode(slug, storyEpisode, (data?.tabs || []).map((t) => t.updated_at).join("|"), isStudio);
  useEffect(() => {if (writingStatus?.docHash) episode.reload();}, [writingStatus?.docHash]); // live alignment after manuscript ACK, not cached shot_meta
  // Ctrl K opens the command palette; G opens or closes the Assistant when focus is not in a field.
  useEffect(() => {
    if (!isStudio || consoleView) return undefined;
    const keys = (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); setPalette((open) => !open); return; }
      if (event.key.toLowerCase() !== "g" || event.ctrlKey || event.metaKey || event.altKey || event.defaultPrevented) return;
      if (event.target.closest?.("input,textarea,select,[contenteditable=true],.modal-scrim") || !paEnabled) return;
      event.preventDefault();
      setPaMode((current) => (current === "off" ? (narrow() ? "full" : "side") : "off"));
    };
    window.addEventListener("keydown", keys);
    return () => window.removeEventListener("keydown", keys);
  }, [isStudio, consoleView, paEnabled]);
  const openConsole = async () => {
    if (!(await flushSurface())) return;
    productionReturnFocus.current = document.activeElement;
    productionHash.current = consoleRoute(window.location.hash) ? productionHash.current : window.location.hash;
    try {sessionStorage.setItem('zf.production:'+slug, productionHash.current || tabHash(tabKey));sessionStorage.setItem('zf.productionContext:'+slug+':'+data.me.actor_id,JSON.stringify({episodeId:storyEpisode,focus:surfaceControl.current?.consoleContext?.(),chatDraft:paDraft,dockMode:paMode}));} catch { /* Mounted production stays intact. */ }
    window.location.hash = consoleHash();
  };
  const returnProduction = () => {window.location.hash = productionHash.current || tabHash(tabKey);};

  if (fatal) {
    return (
      <div className="center-note">
        <p>{fatal.status === 404 ? uiText("app.productionNotFound") : fatal.message}</p>
        <button type="button" className="ghost" onClick={() => window.location.reload()}>{uiText("app.refresh")}</button>
      </div>
    );
  }
  if (!data) return <div className="center-note">{uiText("app.loading")}</div>;

  const me = data.me;
  const signOut = async () => {
    if (!await flushIdentity()) return;
    try {
      // Existing token endpoint: same-origin + projects CSRF header, 303 clears the HttpOnly session.
      const response = await fetch('/logout', {method:'POST', credentials:'same-origin',
        headers:{'X-Requested-With':'projects','Content-Type':'application/x-www-form-urlencoded'}, body:''});
      if (!response.ok) {const payload = await response.json().catch(() => null); throw new Error(payload?.error || response.statusText);}
      window.location.assign('/login');
    } catch (error) {onError(error.message);}
  };
  const tabs = data.tabs;
  const tab = tabKey ? docs[tabKey] : null;
  const todo = todoCount(data.annotations, me);
  const openCount = (key) => data.annotations.filter((a) => a.tab_key === key && isOpen(a) && !a.orphaned_at).length;
  const storyView = isStudio && tabKey === STORY_VIEW;
  const space = isStudio ? spaceOf(tabKey) : null;
  const counts = episodeCounts(episode.ep, episode.shots);
  const reloadAll = async () => { episode.reload(); await loadProject(); if (tabKey && tabKey !== STORY_VIEW) await loadTab(tabKey, true); };
  const assistantButton = paEnabled && (
    <button type="button" className={"icon-btn pa-btn" + (paMode !== "off" ? " on" : "")} title={uiText("app.studioAssistant")} aria-keyshortcuts={isStudio ? "G" : undefined}
      onClick={() => { if (paMode === 'off') { if (assistant.orchestrationCounts?.needs_you || assistant.orchestrationCounts?.working) setPaView('agents'); openAssistant(); } else setPaMode('off'); }}>
      <Icon name="sparkle" /><span className="label">{uiText("app.studioAssistant")}</span>
      {paMode === 'off' && assistant.orchestrationCounts?.needs_you > 0 && <span className="count">? {assistant.orchestrationCounts.needs_you}</span>}
      {paMode === 'off' && assistant.orchestrationCounts?.working > 0 && <span className="count">⟳ {assistant.orchestrationCounts.working}</span>}
    </button>
  );
  // Every page and engineering tool, one Ctrl K away instead of standing in the top bar and page rail.
  const commands = isStudio ? [
    { id: "space-story", group: uiText("shell.groupSpaces"), label: uiText("shell.storyWorld"), icon: "doc", run: () => navigate(STORY_VIEW) },
    { id: "space-stage", group: uiText("shell.groupSpaces"), label: uiText("shell.shotStage"), icon: "clapper", run: () => navigate(STAGE_TAB) },
    { id: "film", group: uiText("shell.groupSpaces"), label: uiText("shell.filmTitle"), icon: "play", run: () => setFilmOpen(true) },
    ...tabs.map((item) => ({ id: "page-" + item.key, group: uiText("shell.groupPages"), label: item.title, hint: openCount(item.key) ? uiText("shell.openNotes", { count: openCount(item.key) }) : "",
      icon: item.surface_type === "sheet" ? "table" : item.surface_type === "flow" ? "flow" : "doc", run: () => navigate(item.key) })),
    { id: "assets", group: uiText("shell.groupTools"), label: uiText("story.assetVault"), icon: "layers", run: () => setStudioModal("assets") },
    { id: "annotations", group: uiText("shell.groupTools"), label: uiText("app.annotations"), hint: todo ? String(todo) : "", icon: "comment", run: () => { setPanel(true); setHistoryOpen(false); if (paMode === "side") setPaMode("off"); } },
    ...(tab && !storyView ? [{ id: "history", group: uiText("shell.groupTools"), label: uiText("shell.pageHistory"), icon: "history", run: () => { setHistoryOpen(true); setPanel(false); if (paMode === "side") setPaMode("off"); } }] : []),
    { id: "toolbox", group: uiText("shell.groupTools"), label: uiText("story.toolbox"), icon: "toolbox", run: () => setStudioModal("toolbox") },
    { id: "api", group: uiText("shell.groupTools"), label: uiText("story.openApi"), icon: "code", run: () => setStudioModal("api") },
    { id: "console", group: uiText("shell.groupTools"), label: uiText("console.entry"), icon: "terminal", run: openConsole },
    { id: "link", group: uiText("shell.groupTools"), label: uiText("app.copyLink"), icon: "link", run: copyLink },
    { id: "rail", group: uiText("shell.groupTools"), label: uiText(studioRail ? "shell.hidePages" : "shell.showPages"), icon: "menu", run: () => setStudioRail((open) => !open) },
  ] : [];
  return (
    <>
    {identityLost && <section className="center-note" role="alert"><p>{uiText('writing.integration.identityChanged')}</p><a href="/login">{uiText('writing.integration.signIn')}</a></section>}
    {consoleView && !identityLost && <AgentConsoleApp key={slug+':'+me.actor_id} slug={slug} me={me} project={data.project} route={consoleView} episodeId={storyEpisode} onReturn={returnProduction}/>}
    <div data-console-hidden={Boolean(consoleView || identityLost)} inert={consoleView || identityLost ? true : undefined} aria-hidden={consoleView || identityLost ? true : undefined} className={"app workbench-app surface-" + (storyView ? "story" : tab?.surface_type || "doc") + (isStudio ? " studio-shell" : "") + ((isStudio ? !studioRail : railHidden) ? " rail-off" : "") + (railOpen ? " rail-open" : "") + (me.can_edit ? " can-edit" : "")
      + (paMode === "side" ? " pa-on" : "") + (paMode === "full" ? " ws-on" : "")}>
      {isStudio ? <StudioTopBar project={data.project} episodes={episode.episodes} epId={storyEpisode}
        onEpisode={async (next) => { if (await flushSurface()) setStoryEpisode(next); }}
        space={space} pageTitle={!storyView && tab && tabKey !== STAGE_TAB ? tab.title : ""} counts={counts} writingStatus={storyView ? writingStatus : null}
        onSpace={(next) => navigate(next === "story" ? STORY_VIEW : STAGE_TAB)} onCommand={() => setPalette(true)}
        assistant={<>{todo > 0 && <button type="button" id="annBtn" className={"icon-btn" + (panel ? " on" : "")} title={uiText("app.annotationsNeedsYouAndAll")}
          onClick={() => { setPanel(!panel); setHistoryOpen(false); if (!panel && paMode === "side") setPaMode("off"); }}><NoteIcon /><span className="count">{todo}</span></button>}
          {tab?.surface_type === "doc" && !storyView && <button type="button" id="viewBtn" className={"icon-btn" + (viewMenu ? " on" : "")} title={uiText("app.chooseWhichHighlightsAndUnderlinesToShow")}
            onClick={(event) => setViewMenu(viewMenu ? null : event.currentTarget.getBoundingClientRect())}><PenIcon /></button>}
          {assistantButton}</>}
        film={{ open: filmOpen, onToggle: () => setFilmOpen((open) => !open) }}
        settings={<WorkspaceSettings me={me} project={data.project} onReload={loadProject} onError={onError} />}
        identity={<IdentityBadge me={me} members={data.members} beforeIdentity={flushIdentity} onSignOut={signOut} />} /> :
      <header className="top">
        <button type="button" className="icon-btn" onClick={() => (window.innerWidth <= 860 ? setRailOpen(!railOpen) : setRailHidden(!railHidden))}
          aria-label={uiText("app.togglePages")}><Icon name="menu" /> <span className="label">{uiText("app.pages")}</span></button>
        <a href="/projects/" className="icon-btn" title={uiText("app.backToProductions")} style={{ textDecoration: "none" }}><Icon name="arrowLeft" /> <span className="label">{uiText("app.allProductions")}</span></a>
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
        <button type="button" id="viewBtn" className={"icon-btn" + (viewMenu ? " on" : "")} title={uiText("app.chooseWhichHighlightsAndUnderlinesToShow")}
          onClick={(event) => setViewMenu(viewMenu ? null : event.currentTarget.getBoundingClientRect())}>
          <PenIcon /><span className="label">{VIEW_LABEL[view] || VIEW_LABEL.all}</span> ▾
        </button>
        <button type="button" id="annBtn" className={"icon-btn" + (panel ? " on" : "")} title={uiText("app.annotationsNeedsYouAndAll")}
          onClick={() => { setPanel(!panel); setHistoryOpen(false); if (!panel && paMode === "side") setPaMode("off"); }}>
          <NoteIcon /><span className="label">{uiText("app.annotations")}</span>{todo > 0 && <span className="count">{todo}</span>}
        </button>
        {assistantButton}
        <button type="button" className="icon-btn" onClick={copyLink} title={uiText("app.copyALinkToThisPageOrAnnotation")} aria-label={uiText("app.copyLink")}>
          <LinkIcon /><span className="label">{uiText("app.copyLink")}</span>
        </button>
        <button type="button" className="icon-btn" onClick={openConsole} aria-label={uiText('console.entry')}><Icon name="terminal" /><span className="label">{uiText('console.entry')}</span></button>
        <LanguageSwitch /><WorkspaceSettings me={me} project={data.project} onReload={loadProject} onError={onError} />
        <IdentityBadge me={me} members={data.members} beforeIdentity={flushIdentity} onSignOut={signOut} />
      </header>}
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
          {storyView && <StoryWorld slug={slug} epId={storyEpisode} me={me} ep={episode.ep} shots={episode.shots} loadError={episode.error} writable={me.can_write !== false}
            controlRef={surfaceControl} onStatus={setWritingStatus} focusSource={writingFocus}
            onChanged={reloadAll} onStage={async ({shotIds = []} = {}) => { if (await navigate(STAGE_TAB) && shotIds.length) { const shot = episode.shots.find(item => item.shotId === shotIds[0]); if (shot) setSheetFocus({tabKey:STAGE_TAB,rowId:shot.rowId,openRow:true,nonce:Date.now()}); } }} onAssets={() => navigate("soul-cast")} onVault={() => setStudioModal("assets")} />}
          {!tab && !storyView && <div className="center-note">{uiText("app.loading")}</div>}
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
              storyEpisode={storyEpisode}
              writingAlignment={episode.alignment}
              onOpenWorld={isStudio ? async ref => { if (await navigate(STORY_VIEW) && ref?.sceneKey) setWritingFocus({...ref,nonce:Date.now()}); } : undefined}
              onFilm={isStudio ? () => setFilmOpen(true) : undefined}
              onField={setField}
              onReloadTab={async () => { await loadTab(tab.key, true); await loadProject(); }}
              onAskAgent={paEnabled ? assignBackground : null}
              agents={assistant.state?.agents || []}
              onAgentRouted={onAgentRouted}
              assistantOpen={paMode !== "off" || panel || historyOpen}
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
              onError={onError} onToast={showToast} onConsole={openConsole} />
          )}
        </main>
      </div>
      {paEnabled && paMode === "side" && (
        <AssistantSide assistant={assistant} me={me} tabs={tabs} slug={slug} focus={paFocus} draft={paDraft}
          onDraft={setPaDraft} inputRef={paInput} view={paView} onView={setPaView} onExpand={() => setPaMode("full")}
          onClose={() => setPaMode("off")} onConsole={openConsole} onOpenTab={openFromAssistant} onStarter={starter} onError={onError} onToast={showToast} />
      )}
      {railOpen && <div className="rail-scrim" onClick={() => setRailOpen(false)} />}
      {palette && <CommandPalette commands={commands} onClose={() => setPalette(false)} />}
      {filmOpen && <FilmOverlay epId={storyEpisode} shots={episode.shots} writable={me.can_write !== false} onClose={() => setFilmOpen(false)} />}
      {studioModal === "assets" && <AssetVaultModal epId={storyEpisode} writable={me.can_write !== false} onClose={() => setStudioModal(null)} onChanged={reloadAll} onNavigate={() => { setStudioModal(null); navigate("soul-cast"); }} />}
      {studioModal === "toolbox" && <ToolboxModal writable={me.can_write !== false} onClose={() => setStudioModal(null)} />}
      {studioModal === "api" && <OpenApiModal slug={slug} epId={storyEpisode} onClose={() => setStudioModal(null)} />}
      {toast && <div className={"toast " + toast.kind} role="status">{toast.message}</div>}
    </div>
    </>
  );
}
