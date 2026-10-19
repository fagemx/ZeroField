import { useLocale } from './i18n/react.jsx';
import { t as uiText } from './i18n/index.js';
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Image from "@tiptap/extension-image";
import { TaskList } from "@tiptap/extension-list";
import { TableKit } from "@tiptap/extension-table";
import { Mark } from "@tiptap/pm/model";
import { TextSelection } from "@tiptap/pm/state";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { selectionAnchor } from "./anchoring.js";
import { api } from "./api.js";
import { bidOf, computeOps, isBlankNew, mergeServer, stable } from "./blocks.js";
import { Dialog } from "./Dialog.jsx";
import { Menu, useOutside } from "./Menu.jsx";
import { rowLabel } from "./docText.js";
import {
  AnnotationLayer, AssistChips, BlockIds, FillColumns, FillNode, PermissionGuard, ProjectTaskItem, REMOTE, SYSTEM, StatusNode,
  TRUSTED, annotationKey, assistKey, newId, nowIso, permissionKey,
} from "./editorExtensions.js";
import { Margin, Sheet, hasCard } from "./Annotations.jsx";
import { shortTime } from "./format.js";
import { FieldsContext } from "./nodeViews.jsx";
import { blockEditable, canAddRow, isHeaderRowNode, unitEditable, unitsInRange } from "./permissions.js";
import { internalTab } from "./route.js";
import { COLORS, LABELS, comments, markClass } from "./rules.js";
import { Avatar } from "./Talk.jsx";
import { Icon } from "./Icon.jsx";

const SAVE_DELAY = 1500;
const RETRY_DELAY = 5000;
const LOCK_RENEW = 30000;
const NEW_VERSION_AFTER = 10 * 60 * 1000; // 停了 10 分鐘以上再改，算新的一次編輯（新版本）
const IMAGE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"];
const LINK_OK = /^(https?:\/\/|mailto:|#[a-z0-9][a-z0-9-]*$)/i;
const NARROW = "(max-width: 860px)";

function blockItems(pickImage) {
  return [
    { key: "text", label: uiText("docSurface.bodyText"), icon: "¶", words: uiText("docSurface.textParagraphBody"), run: (e) => e.chain().focus().setParagraph().run() },
    { key: "h1", label: uiText("docSurface.heading"), icon: "H1", words: uiText("docSurface.headingH1Title"), run: (e) => e.chain().focus().setNode("heading", { level: 1 }).run() },
    { key: "h2", label: uiText("docSurface.heading2"), icon: "H2", words: uiText("docSurface.headingH2"), run: (e) => e.chain().focus().setNode("heading", { level: 2 }).run() },
    { key: "h3", label: uiText("docSurface.heading3"), icon: "H3", words: uiText("docSurface.headingH3Subtitle"), run: (e) => e.chain().focus().setNode("heading", { level: 3 }).run() },
    { key: "bullet", label: uiText("docSurface.bulletList"), icon: "•", words: uiText("docSurface.bulletList2"), run: (e) => e.chain().focus().toggleBulletList().run() },
    { key: "numbered", label: uiText("docSurface.numberedList"), icon: "1.", words: uiText("docSurface.numberedOrderedList"), run: (e) => e.chain().focus().toggleOrderedList().run() },
    { key: "check", label: uiText("docSurface.checklist"), icon: "☑", words: uiText("docSurface.checkTodoTask"), run: (e) => e.chain().focus().toggleTaskList().run() },
    { key: "quote", label: uiText("docSurface.quote"), icon: "❝", words: uiText("docSurface.quoteCitation"), run: (e) => e.chain().focus().toggleBlockquote().run() },
    { key: "divider", label: uiText("docSurface.divider"), icon: "—", words: uiText("docSurface.dividerHr"), run: (e) => e.chain().focus().setHorizontalRule().run() },
    { key: "table", label: uiText("docSurface.table"), icon: "▦", words: uiText("docSurface.table2"), run: (e) => e.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run() },
    { key: "image", label: uiText("docSurface.image"), icon: <Icon name="image" />, words: uiText("docSurface.imagePhoto"), run: () => pickImage() },
    { key: "status", label: uiText("docSurface.status"), icon: "●", words: uiText("docSurface.statusProgress"),
      run: (e) => e.chain().focus().insertContent([{ type: "status", attrs: { label: "Queued" } }, { type: "text", text: " " }]).run() },
    { key: "fill", label: uiText("docSurface.sharedField"), icon: "✎", words: uiText("docSurface.fillEditableField"), run: (e) => e.chain().focus().insertContent({ type: "fill", attrs: { label: "" } }).run() },
  ];
}

// 「＋」新增的區塊
const NEW_BLOCKS = () => [["p", "¶", uiText("docSurface.paragraph")], ["h2", "H", uiText("docSurface.subheading")], ["ul", "•", uiText("docSurface.bulletList")], ["task", "☑", uiText("docSurface.checklist")], ["quote", "❝", uiText("docSurface.quote")], ["table", "▦", uiText("docSurface.table")]];

// 標註欄要文件區夠寬才放得下寬版（300px 卡片）。原本只看視窗寬度（1600 以下收成窄邊），
// 但右邊的專案助理側邊欄也會吃掉寬度（還可以拖拉調寬）：改看文件區實際的寬度。
// 1296 ＝ 原本的 1600 − 左邊分頁 240 − 內距 64，沒開側邊欄時跟以前一樣。
const WIDE_MARGIN_MIN = 1296;

function marginMode(available) {
  if (window.matchMedia(NARROW).matches) return "sheet";
  const width = available || window.innerWidth - 304;
  return width < WIDE_MARGIN_MIN ? "slim" : "wide";
}

function rowHasField(row) {
  let found = false;
  row.descendants((child) => {
    if (child.type.name === "status" || child.type.name === "fill") found = true;
    return !found;
  });
  return found;
}

function clip(text, n) {
  const value = String(text || "").trim();
  return value.length > n ? value.slice(0, n) + "…" : value;
}

// 兩個節點只差在屬性（誰新增的、新增時間、欄位 id）：結構、字、格式都一樣
function sameShape(a, b) {
  if (a.type !== b.type || a.childCount !== b.childCount) return false;
  if (a.isText) return a.text === b.text && Mark.sameSet(a.marks, b.marks);
  if (!Mark.sameSet(a.marks, b.marks)) return false;
  for (let i = 0; i < a.childCount; i += 1) if (!sameShape(a.child(i), b.child(i))) return false;
  return true;
}

// 只改屬性（游標、復原紀錄都留著）；結構不同才整塊換
function patchBlock(tr, pos, have, want) {
  if (have.eq(want)) return;
  if (!sameShape(have, want)) {
    tr.replaceWith(pos, pos + have.nodeSize, want);
    return;
  }
  const walk = (a, b, at) => {
    if (!a.isText && !a.sameMarkup(b)) tr.setNodeMarkup(at, undefined, b.attrs, b.marks);
    let offset = at + 1;
    for (let i = 0; i < a.childCount; i += 1) {
      walk(a.child(i), b.child(i), offset);
      offset += a.child(i).nodeSize;
    }
  };
  walk(have, want, pos);
}

// 把伺服器合併後的內文換進編輯器：只換有變的塊，其他塊的復原紀錄（Ctrl+Z）保留。
function patchDoc(editor, json) {
  const { state } = editor;
  const next = (json.content || []).map((node) => state.schema.nodeFromJSON(node));
  const nextBids = new Set(next.map((node) => node.attrs.bid));
  const $from = state.selection.$from;
  const caret = $from.depth > 0 ? { bid: $from.node(1).attrs.bid, offset: state.selection.from - $from.before(1) } : null;
  let tr = state.tr;
  const children = [];
  state.doc.forEach((node, offset) => children.push({ node, offset }));
  for (let i = children.length - 1; i >= 0; i -= 1) {
    const { node, offset } = children[i];
    if (!nextBids.has(node.attrs.bid)) tr.delete(offset, offset + node.nodeSize);
  }
  let pos = 0;
  let ordered = true;
  for (const want of next) {
    const have = pos < tr.doc.content.size ? tr.doc.nodeAt(pos) : null;
    if (have && have.attrs.bid === want.attrs.bid) {
      patchBlock(tr, pos, have, want);
      pos += want.nodeSize;
      continue;
    }
    let later = false;
    tr.doc.forEach((node, offset) => { if (offset > pos && node.attrs.bid === want.attrs.bid) later = true; });
    if (later) { ordered = false; break; }
    tr.insert(pos, want);
    pos += want.nodeSize;
  }
  if (!ordered || tr.doc.childCount !== next.length) {
    tr = state.tr.replaceWith(0, state.doc.content.size, next);
  }
  if (!tr.docChanged) return false;
  // 游標所在那一塊被整塊換掉時，游標會被擠到塊的外面：照原本在那一塊裡的位置放回去
  if (caret && editor.isFocused) {
    let start = null;
    let size = 0;
    tr.doc.forEach((node, offset) => { if (node.attrs.bid === caret.bid) { start = offset; size = node.nodeSize; } });
    const at = tr.selection.from;
    if (start !== null && (at <= start || at >= start + size)) {
      const target = Math.min(start + caret.offset, start + size - 1);
      tr.setSelection(TextSelection.near(tr.doc.resolve(Math.max(start + 1, target))));
    }
  }
  tr.setMeta(SYSTEM, true).setMeta(REMOTE, true).setMeta("addToHistory", false);
  editor.view.dispatch(tr);
  return true;
}

function cursorBid(editor) {
  const $from = editor.state.selection.$from;
  return $from.depth > 0 ? $from.node(1).attrs.bid : null;
}

// 一個畫面：大家都在這裡看、標註；能改的地方點一下就能打字，停止打字 1.5 秒一塊一塊存。
export function DocSurface({ slug, tab, tabs, me, members, values, annotations, locks, focusId, focusRequest, flashId, view,
  showResolved, attachId, onField, onFocus, onAnnotation, onAnnotations, onNavigate, onSaved, versionsFor, onVersionsShown,
  onOpenPanel, onOpenHistory, onAttachDone, onError, onToast, controlRef, assistRows, onAssistRow, agents = [], onAgentRouted }) {
  const locale = useLocale();
  const admin = me.role === "admin";
  const editorRef = useRef(null);
  const surfaceRef = useRef(null);
  const wrapRef = useRef(null);
  const toolbarRef = useRef(null);
  const fileInput = useRef(null);
  const session = useRef({ id: "s-" + newId(""), lastSave: 0 });
  const sync = useRef({ server: tab.doc, clean: new Map(), base: new Map(), revision: tab.revision, savedAt: tab.updated_at });
  const dirty = useRef(false);
  const timer = useRef(null);
  const inflight = useRef(null);
  const pending = useRef(null); // 輸入法組字中收到的伺服器內容：組完字再換
  const held = useRef(new Set()); // 我拿著的編輯鎖
  const blockedAt = useRef(0);
  const slashRef = useRef(null);
  const latest = useRef({});
  const ctxRef = useRef({ me: me.actor_id, admin, locks: new Map(), names: new Map(), adminIds: new Set(), onBlocked: () => {} });
  const ownerRef = useRef(admin ? null : me.actor_id);
  const assistRef = useRef({ chips: null, onAssist: () => {} });
  assistRef.current = { chips: assistRows || null, onAssist: (rid) => onAssistRow && onAssistRow(rid) };
  const [saveState, setSaveState] = useState({ kind: "saved", at: tab.updated_at });
  const [menu, setMenu] = useState(null);
  const [dialog, setDialog] = useState(null);
  const [wide, setWide] = useState(document.body.classList.contains("wide"));
  const [slash, setSlash] = useState(null);
  const [tableBar, setTableBar] = useState(null);
  const [linkPop, setLinkPop] = useState(null);
  const [history, setHistory] = useState({ undo: false, redo: false });
  const [editing, setEditing] = useState(null); // 游標在可以改的地方：{ what }
  const [mode, setMode] = useState(() => marginMode());
  const [layout, setLayout] = useState({ items: [], rows: [], adds: [], bars: [], height: 0 });
  const [drafts, setDrafts] = useState([]);
  const [adding, setAdding] = useState(() => new Set());
  const [busy, setBusy] = useState(false);
  const [sel, setSel] = useState(null);
  const [labelMenu, setLabelMenu] = useState(false);
  const [markPop, setMarkPop] = useState(null);
  const [gutter, setGutter] = useState(null);
  const [insMenu, setInsMenu] = useState(null);
  const [ready, setReady] = useState(false);
  const seltbRef = useRef(null);

  const memberNames = useMemo(() => new Map(members.map((m) => [m.actor_id, m.name])), [members]);
  const tabAnns = useMemo(() => [...annotations.filter((a) => a.tab_key === tab.key), ...drafts], [annotations, drafts, tab.key]);
  const byId = useCallback((id) => tabAnns.find((a) => String(a.id) === String(id)), [tabAnns]);
  latest.current = { onSaved, onToast, onError, onNavigate, onFocus, onAnnotation, onAnnotations, tabAnns, focusId, adding };

  // ---------- 權限的環境：我是誰、別人拿著哪些鎖 ----------
  useEffect(() => {
    const lockMap = new Map(locks.filter((l) => l.tab_key === tab.key && l.actor_id !== me.actor_id).map((l) => [l.unit_id, l.name]));
    ctxRef.current = {
      me: me.actor_id, admin, canWrite: me.can_write !== false, locks: lockMap, names: memberNames,
      adminIds: new Set(members.filter((m) => m.role === "admin").map((m) => m.actor_id)),
      onBlocked: (unit) => {
        if (Date.now() - blockedAt.current < 2500) return;
        blockedAt.current = Date.now();
        const id = unit.node.attrs.bid;
        const who = lockMap.get(id) || (unit.table && lockMap.get(unit.table.attrs.bid));
        latest.current.onToast(uiText("docSurface.isEditingThisPassageWaitUntilTheyFinish", {v0: (who || uiText("docSurface.anotherCrewMember"))}));
      },
    };
    ownerRef.current = admin ? null : me.actor_id;
    const editor = editorRef.current;
    if (editor && !editor.isDestroyed) editor.view.dispatch(editor.state.tr.setMeta(permissionKey, true));
  }, [locks, members, memberNames, me.actor_id, admin, tab.key, ready, locale]);

  // 左邊分頁「⋯ → 找回以前的內容…」：換到這一頁後打開版本紀錄
  useEffect(() => {
    if (!versionsFor || versionsFor !== tab.key) return;
    setDialog({ kind: "versions" });
    if (onVersionsShown) onVersionsShown();
  }, [versionsFor, tab.key, onVersionsShown, locale]);

  // 專案助理的「✦ 一起回答」跟著待辦變（裝飾，不改文件）
  useEffect(() => {
    const editor = editorRef.current;
    if (editor && !editor.isDestroyed) editor.view.dispatch(editor.state.tr.setMeta(assistKey, true));
  }, [assistRows, ready, locale]);

  const pickImage = useCallback(() => { if (fileInput.current) fileInput.current.click(); }, []);
  const items = useMemo(() => blockItems(pickImage), [pickImage, locale]);

  // ---------- 跟伺服器同步 ----------
  const resetSync = (serverDoc, revision, savedAt) => {
    const editor = editorRef.current;
    const clean = new Map();
    const base = new Map((serverDoc.content || []).map((node) => [bidOf(node), node]));
    for (const node of editor.getJSON().content || []) if (bidOf(node)) clean.set(bidOf(node), stable(node));
    sync.current = { server: serverDoc, clean, base, revision, savedAt };
    dirty.current = false;
  };

  // 伺服器的新內文進來：沒在改的塊換新、正在改的保留（opts.clean／sent：剛存完時用送出的那份當基準）
  const applyServer = (serverDoc, revision, savedAt, opts = {}) => {
    const editor = editorRef.current;
    if (!editor || editor.isDestroyed) return;
    if (editor.view.composing) { pending.current = { serverDoc, revision, savedAt, opts }; return; }
    const s = sync.current;
    const clean = opts.clean || s.clean;
    const sent = opts.sent || new Set();
    const { doc: merged, kept, deleted } = mergeServer({
      server: serverDoc, clean, current: editor.getJSON(), force: opts.force || new Set(), keepBid: cursorBid(editor),
    });
    patchDoc(editor, merged);
    const serverMap = new Map((serverDoc.content || []).map((node) => [bidOf(node), node]));
    const nextClean = new Map();
    const nextBase = new Map();
    for (const node of editor.getJSON().content || []) {
      const bid = bidOf(node);
      if (!bid) continue;
      if (kept.has(bid)) {
        if (clean.has(bid)) nextClean.set(bid, clean.get(bid));
        const base = sent.has(bid) ? serverMap.get(bid) : s.base.get(bid);
        if (base) nextBase.set(bid, base);
      } else if (serverMap.has(bid)) {
        nextClean.set(bid, stable(node));
        nextBase.set(bid, serverMap.get(bid));
      }
    }
    for (const bid of deleted) {
      nextClean.set(bid, clean.get(bid));
      nextBase.set(bid, s.base.get(bid) || serverMap.get(bid));
    }
    sync.current = { server: serverDoc, clean: nextClean, base: nextBase, revision, savedAt };
    dirty.current = kept.size > 0 || deleted.size > 0;
  };

  const lock = useCallback(async (unit, release = false) => {
    try {
      return await api.post(`/projects/api/${slug}/locks`, { tab_key: tab.key, unit, release });
    } catch {
      return null; // 鎖拿不到不擋人；存的時候伺服器會再檢查一次
    }
  }, [slug, tab.key]);

  const releaseIdle = useCallback(() => {
    const editor = editorRef.current;
    const here = editor && !editor.isDestroyed && editor.isFocused
      ? new Set(unitsInRange(editor.state.doc, editor.state.selection.from, editor.state.selection.from).map((u) => u.node.attrs.bid))
      : new Set();
    for (const unit of [...held.current]) {
      if (here.has(unit)) continue;
      held.current.delete(unit);
      lock(unit, true);
    }
  }, [lock]);

  const save = useCallback(async () => {
    const editor = editorRef.current;
    if (!editor || editor.isDestroyed) return true;
    if (inflight.current) await inflight.current;
    if (!dirty.current) return true;
    const s = sync.current;
    const current = editor.getJSON();
    const baseDoc = { type: "doc", content: (s.server.content || []).map((node) => s.base.get(bidOf(node)) || node) };
    const ops = computeOps({ server: baseDoc, clean: s.clean, current });
    if (!ops.length) {
      dirty.current = false;
      setSaveState((state) => ({ kind: "saved", at: state.at }));
      return true;
    }
    if (session.current.lastSave && Date.now() - session.current.lastSave > NEW_VERSION_AFTER) {
      session.current.id = "s-" + newId("");
    }
    dirty.current = false;
    setSaveState({ kind: "saving" });
    const sentClean = new Map(s.clean);
    const sentBids = new Set();
    const tables = new Map((current.content || []).filter((n) => n.type === "table").map((n) => [bidOf(n), n]));
    for (const op of ops) {
      if (op.op === "put") { sentClean.set(op.bid, stable(op.node)); sentBids.add(op.bid); }
      if ((op.op === "put_row" || op.op === "del_row") && tables.has(op.table)) {
        sentClean.set(op.table, stable(tables.get(op.table)));
        sentBids.add(op.table);
      }
    }
    const run = (async () => {
      try {
        const result = await api.post(`/projects/api/${slug}/tabs/${tab.key}/ops`, { session_id: session.current.id, ops });
        session.current.lastSave = Date.now();
        const force = new Set();
        for (const conflict of result.conflicts || []) {
          const table = (current.content || []).find((n) => n.type === "table" && (n.content || []).some((r) => bidOf(r) === conflict.unit));
          const unit = table ? bidOf(table) : conflict.unit;
          force.add(unit);
          sentBids.delete(unit);
        }
        applyServer(result.doc, result.revision, result.saved_at, { clean: sentClean, sent: sentBids, force });
        if (result.conflicts && result.conflicts.length) {
          const first = result.conflicts[0];
          const name = first.owner_name || uiText("docSurface.anotherCrewMember");
          latest.current.onToast(first.reason === "locked" ? uiText("docSurface.isEditingThisPassageYourChangesWereNotSaved", {v0: (name)})
            : first.reason === "changed" ? uiText("docSurface.thisPassageChangedElsewhereTheLatestContentIsShown")
              : uiText("docSurface.aPassageCouldNotBeEditedWithYourPermissions"));
        }
        setSaveState({ kind: "saved", at: result.saved_at });
        latest.current.onSaved({ revision: result.revision, saved_at: result.saved_at, doc: result.doc });
        if (result.annotations) latest.current.onAnnotations(result.annotations);
        releaseIdle();
        if (dirty.current) { clearTimeout(timer.current); timer.current = setTimeout(() => { save(); }, SAVE_DELAY); }
        return true;
      } catch (error) {
        dirty.current = true;
        setSaveState({ kind: "error", message: error.message });
        clearTimeout(timer.current);
        timer.current = setTimeout(() => { save(); }, RETRY_DELAY);
        return false;
      }
    })();
    inflight.current = run;
    const ok = await run;
    inflight.current = null;
    return ok;
  }, [slug, tab.key, admin, releaseIdle]); // eslint-disable-line react-hooks/exhaustive-deps

  const flush = useCallback(async () => {
    clearTimeout(timer.current);
    if (dirty.current || inflight.current) return save();
    return true;
  }, [save]);

  // 第一次改到某一塊：拿那一塊的編輯鎖；拿不到就換回伺服器的內容
  const claim = (transaction) => {
    const units = new Set();
    transaction.steps.forEach((step, index) => {
      const doc = transaction.docs[index];
      step.getMap().forEach((from, to) => {
        for (const unit of unitsInRange(doc, from, to)) units.add(unit.node.attrs.bid);
      });
    });
    for (const unit of units) {
      if (!unit || held.current.has(unit) || !sync.current.base.has(unit) && !rowKnown(unit)) continue;
      held.current.add(unit);
      lock(unit).then((result) => {
        if (!result || result.held !== false) return;
        held.current.delete(unit);
        const editor = editorRef.current;
        if (!editor || editor.isDestroyed) return;
        const table = editor.getJSON().content.find((n) => n.type === "table" && (n.content || []).some((r) => bidOf(r) === unit));
        applyServer(sync.current.server, sync.current.revision, sync.current.savedAt, { force: new Set([table ? bidOf(table) : unit]) });
        ctxRef.current.locks.set(unit, result.by_name);
        editor.view.dispatch(editor.state.tr.setMeta(permissionKey, true));
        latest.current.onToast(uiText("docSurface.isEditingThisPassageWaitUntilTheyFinish", {v0: (result.by_name)}));
      });
    }
  };

  const rowKnown = (rid) => (sync.current.server.content || []).some((n) => n.type === "table" && (n.content || []).some((r) => bidOf(r) === rid));

  // ---------- 斜線選單（在文件裡打 /） ----------
  const filterItems = useCallback((query) => {
    const q = query.toLowerCase();
    return items.filter((item) => !q || item.label.toLowerCase().includes(q) || item.words.includes(q));
  }, [items]);

  const closeSlash = () => { slashRef.current = null; setSlash(null); };

  const canEditAt = (editor, pos) => {
    const units = unitsInRange(editor.state.doc, pos, pos);
    return units.length > 0 && units.every((unit) => unitEditable(unit, ctxRef.current));
  };

  const updateSlash = (editor) => {
    const { selection } = editor.state;
    if (!selection.empty || !selection.$from.parent.isTextblock || !canEditAt(editor, selection.from)) { closeSlash(); return; }
    const $from = selection.$from;
    const before = $from.parent.textBetween(Math.max(0, $from.parentOffset - 24), $from.parentOffset, undefined, "￼");
    const match = /(?:^|\s)\/([^\s/]{0,20})$/.exec(before);
    if (!match) { closeSlash(); return; }
    const list = filterItems(match[1]);
    const coords = editor.view.coordsAtPos(selection.from);
    const previous = slashRef.current;
    const next = {
      query: match[1], from: selection.from - match[1].length - 1, to: selection.from,
      top: coords.bottom + 6, left: coords.left, list,
      index: previous && previous.query === match[1] ? previous.index : 0,
    };
    slashRef.current = next;
    setSlash(next);
  };

  const runSlash = (item) => {
    const state = slashRef.current;
    const editor = editorRef.current;
    if (!state || !editor) return;
    editor.chain().focus().deleteRange({ from: state.from, to: state.to }).run();
    closeSlash();
    item.run(editor);
  };

  const updateLinkPop = (editor) => {
    const { selection } = editor.state;
    if (!editor.isFocused || !selection.empty || !editor.isActive("link") || !canEditAt(editor, selection.from)) {
      setLinkPop(null);
      return;
    }
    const href = editor.getAttributes("link").href || "";
    const coords = editor.view.coordsAtPos(selection.from);
    setLinkPop({ href, top: coords.bottom + 8, left: Math.max(8, Math.min(coords.left - 20, window.innerWidth - 340)) });
  };

  const updateTableBar = (editor) => {
    if (!editor || !editor.isFocused || !editor.isActive("table") || !surfaceRef.current) { setTableBar(null); return; }
    const $from = editor.state.selection.$from;
    let table = null;
    for (let depth = $from.depth; depth > 0; depth -= 1) if ($from.node(depth).type.name === "table") table = $from.node(depth);
    if (!table || !blockEditable(table, ctxRef.current)) { setTableBar(null); return; }
    const at = editor.view.domAtPos(editor.state.selection.from);
    const element = at.node.nodeType === 3 ? at.node.parentElement : at.node;
    const wrapper = element && element.closest ? element.closest(".tableWrapper") : null;
    if (!wrapper) { setTableBar(null); return; }
    const rect = wrapper.getBoundingClientRect();
    const base = surfaceRef.current.getBoundingClientRect();
    setTableBar({ top: rect.top - base.top - 40, left: Math.max(0, rect.left - base.left) });
  };

  const updateEditing = (editor) => {
    if (!editor.isFocused) return;
    const { from } = editor.state.selection;
    const units = unitsInRange(editor.state.doc, from, from);
    const unit = units[0];
    if (!unit || !unitEditable(unit, ctxRef.current)) {
      setEditing((state) => (state && !dirty.current && !inflight.current ? null : state));
      return;
    }
    const what = unit.kind === "row" ? uiText("docSurface.tableRow", {v0: (clip(rowLabel(unit.node.toJSON()), 12) || uiText("docSurface.newRow"))})
      : ({ heading: uiText("docSurface.title"), paragraph: uiText("docSurface.thisPassage"), bulletList: uiText("docSurface.thisList"), orderedList: uiText("docSurface.thisList"), taskList: uiText("docSurface.thisChecklist"),
        blockquote: uiText("docSurface.thisQuote"), table: uiText("docSurface.thisTable") })[unit.node.type.name] || uiText("docSurface.thisBlock");
    setEditing({ what });
  };

  // 沒打字就離開的新區塊（按了＋、按了 Enter）：拿掉，跟重新整理後看到的一樣
  const dropBlankNew = (editor) => {
    const here = cursorBid(editor);
    const known = sync.current.clean;
    const ranges = [];
    editor.state.doc.forEach((node, offset) => {
      const bid = node.attrs.bid;
      if (!bid || known.has(bid) || bid === here || offset + node.nodeSize === editor.state.doc.content.size) return;
      if (isBlankNew(node.toJSON())) ranges.push([offset, offset + node.nodeSize]);
    });
    if (!ranges.length) return;
    const tr = editor.state.tr;
    for (let i = ranges.length - 1; i >= 0; i -= 1) tr.delete(ranges[i][0], ranges[i][1]);
    editor.view.dispatch(tr.setMeta(SYSTEM, true).setMeta("addToHistory", false));
  };

  const openLink = (href) => {
    const target = internalTab(href);
    if (target) latest.current.onNavigate(target);
    else if (href) window.open(href, "_blank", "noopener,noreferrer");
  };

  // 點到哪一則標註（重疊時選最短的）
  const annotationAt = (state, pos) => {
    const plugin = annotationKey.getState(state);
    if (!plugin) return null;
    let best = null;
    for (const [id, range] of plugin.ranges) {
      if (pos < range.from || pos > range.to) continue;
      if (!best || range.to - range.from < best.size) best = { id, size: range.to - range.from };
    }
    return best ? latest.current.tabAnns.find((a) => String(a.id) === String(best.id)) : null;
  };

  const scheduleLayout = useRef(() => {});

  const editor = useEditor({
    editable: me.can_write !== false,
    extensions: [
      StarterKit.configure({
        heading: { levels: [1, 2, 3] },
        codeBlock: false,
        link: {
          openOnClick: false,
          autolink: true,
          defaultProtocol: "https",
          isAllowedUri: (url) => LINK_OK.test(url),
          HTMLAttributes: { rel: "noopener noreferrer", target: null },
        },
      }),
      TableKit.configure({ table: { resizable: false } }),
      TaskList,
      ProjectTaskItem,
      Image.configure({ inline: false, allowBase64: false }),
      StatusNode,
      FillNode,
      BlockIds.configure({ getOwner: () => ownerRef.current }),
      FillColumns,
      PermissionGuard.configure({ getCtx: () => ctxRef.current }),
      AnnotationLayer,
      AssistChips.configure({ getCtx: () => assistRef.current }),
    ],
    content: tab.doc,
    editorProps: {
      attributes: { class: "doc doc-surface-editor", "aria-label": uiText("docSurface.bodyText") },
      handleKeyDown: (_view, event) => {
        const state = slashRef.current;
        if (!state || !state.list.length) return false;
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          const step = event.key === "ArrowDown" ? 1 : -1;
          const next = { ...state, index: (state.index + step + state.list.length) % state.list.length };
          slashRef.current = next;
          setSlash(next);
          return true;
        }
        if (event.key === "Enter" || event.key === "Tab") { runSlash(state.list[state.index]); return true; }
        if (event.key === "Escape") { closeSlash(); return true; }
        return false;
      },
      handleClick: (view, pos, event) => {
        const instance = editorRef.current;
        const editable = instance ? canEditAt(instance, pos) : false;
        const anchor = event.target && event.target.closest ? event.target.closest("a[href]") : null;
        if (anchor && (!editable || event.ctrlKey || event.metaKey)) {
          event.preventDefault();
          openLink(anchor.getAttribute("href"));
          return true;
        }
        const domSel = window.getSelection();
        if (domSel && !domSel.isCollapsed) return false; // 選字中，交給標註工具列
        // 本來能改、只是別人正在改：點下去就說一聲（不然打字沒反應會以為壞了）
        const ctx = ctxRef.current;
        if (ctx.locks.size) {
          const free = { ...ctx, locks: new Map() };
          const units = unitsInRange(view.state.doc, pos, pos);
          const busyUnit = units.find((unit) => !unitEditable(unit, ctx) && unitEditable(unit, free));
          if (busyUnit) {
            const who = ctx.locks.get(busyUnit.node.attrs.bid) || (busyUnit.table && ctx.locks.get(busyUnit.table.attrs.bid));
            if (who) latest.current.onToast(uiText("docSurface.isEditingThisPassageWaitUntilTheyFinish", {v0: (who)}));
          }
        }
        const a = annotationAt(view.state, pos);
        const { focusId: current, adding: addingNow } = latest.current;
        if (a && hasCard(a, addingNow)) {
          latest.current.onFocus(a.id);
          return false;
        }
        if (a && !editable) {
          const rect = event.target.getBoundingClientRect ? event.target.getBoundingClientRect() : null;
          if (rect) setMarkPop({ a, top: rect.bottom + 6, left: Math.max(8, Math.min(rect.left, window.innerWidth - 340)) });
          return false;
        }
        if (current) latest.current.onFocus(null);
        return false;
      },
      handlePaste: (_view, event) => {
        const files = [...(event.clipboardData ? event.clipboardData.files : [])].filter((f) => IMAGE_TYPES.includes(f.type));
        if (!files.length) return false;
        files.forEach((file) => uploadImage(file));
        return true;
      },
      handleDrop: (_view, event) => {
        const files = [...(event.dataTransfer ? event.dataTransfer.files : [])].filter((f) => IMAGE_TYPES.includes(f.type));
        if (!files.length) return false;
        event.preventDefault();
        files.forEach((file) => uploadImage(file));
        return true;
      },
      handleDOMEvents: {
        compositionend: () => {
          setTimeout(() => {
            const waiting = pending.current;
            if (!waiting) return;
            pending.current = null;
            applyServer(waiting.serverDoc, waiting.revision, waiting.savedAt, waiting.opts);
          }, 30);
          return false;
        },
      },
    },
    onCreate: ({ editor: instance }) => {
      editorRef.current = instance;
      resetSync(tab.doc, tab.revision, tab.updated_at);
      setReady(true);
      requestAnimationFrame(() => scheduleLayout.current());
    },
    onTransaction: ({ editor: instance, transaction }) => {
      if (transaction.docChanged && !transaction.getMeta(SYSTEM) && !transaction.getMeta(REMOTE) && !transaction.getMeta(TRUSTED)) {
        claim(transaction);
      }
      requestAnimationFrame(() => scheduleLayout.current());
    },
    onUpdate: ({ editor: instance, transaction }) => {
      requestAnimationFrame(() => updateTableBar(instance));
      updateSlash(instance);
      setHistory({ undo: instance.can().undo(), redo: instance.can().redo() });
      if (transaction && (transaction.getMeta(SYSTEM) || transaction.getMeta(REMOTE))) return;
      dirty.current = true;
      setSaveState((state) => ({ kind: "dirty", at: state.at }));
      clearTimeout(timer.current);
      timer.current = setTimeout(() => { save(); }, SAVE_DELAY);
    },
    onSelectionUpdate: ({ editor: instance }) => {
      updateSlash(instance);
      updateTableBar(instance);
      updateLinkPop(instance);
      updateEditing(instance);
      dropBlankNew(instance);
    },
    onFocus: ({ editor: instance }) => { updateTableBar(instance); updateEditing(instance); },
    onBlur: () => {
      setTimeout(() => {
        const instance = editorRef.current;
        if (!instance || instance.isDestroyed || instance.isFocused) return;
        closeSlash(); setTableBar(null); setLinkPop(null);
        if (toolbarRef.current && toolbarRef.current.contains(document.activeElement)) return;
        setEditing(null);
        dropBlankNew(instance);
        flush().then(() => releaseIdle());
      }, 150);
    },
  }, [tab.key]);

  // 別人（或另一個視窗）存了新版本：沒在改的塊換新
  useEffect(() => {
    const instance = editorRef.current;
    if (!instance || instance.isDestroyed || !ready) return;
    // 只收比手上新的（輪詢的回應可能比剛存完的還舊）
    if (!tab.updated_at || (sync.current.savedAt && tab.updated_at <= sync.current.savedAt)) return;
    if (inflight.current) return;
    applyServer(tab.doc, tab.revision, tab.updated_at);
  }, [tab.doc, tab.updated_at, ready]); // eslint-disable-line react-hooks/exhaustive-deps

  // 修改紀錄點一處：捲到那一段（或表格那一列）亮一下。找不到（已經刪掉了）回 false。
  // 亮的是蓋在上面的一層（編輯器會把自己 DOM 上多出來的 class 洗掉）
  const flashUnit = useCallback((id) => {
    const host = surfaceRef.current;
    const dom = host && id ? host.querySelector(`.ProseMirror [data-bid="${CSS.escape(id)}"]`) : null;
    if (!dom) return false;
    dom.scrollIntoView({ block: "center", behavior: "smooth" });
    const outer = host.getBoundingClientRect();
    const box = dom.getBoundingClientRect();
    for (const old of host.querySelectorAll(":scope > .flash-change")) old.remove();
    const mark = document.createElement("div");
    mark.className = "flash-change";
    Object.assign(mark.style, { top: `${box.top - outer.top - 3}px`, left: `${box.left - outer.left - 8}px`,
      width: `${box.width + 16}px`, height: `${box.height + 6}px` });
    host.appendChild(mark);
    setTimeout(() => mark.remove(), 2600);
    return true;
  }, []);

  useEffect(() => {
    if (!controlRef) return undefined;
    controlRef.current = { flush, flashUnit, isDirty: () => dirty.current || Boolean(inflight.current) };
    return () => { controlRef.current = null; };
  }, [controlRef, flush, flashUnit]);

  // 改的期間每 30 秒續約編輯鎖；離開這一頁放掉
  useEffect(() => {
    const renew = setInterval(() => { for (const unit of held.current) lock(unit); }, LOCK_RENEW);
    const heldNow = held.current;
    return () => {
      clearInterval(renew);
      for (const unit of heldNow) lock(unit, true);
      heldNow.clear();
    };
  }, [lock]);

  // ---------- 內文上的標註 ----------
  const markVisible = useCallback((a) => {
    if (a.kind !== "text" || a.orphaned_at) return false;
    if (a.resolved_at && !showResolved && String(focusId) !== String(a.id)) return false;
    if (!hasCard(a, adding)) {
      if (view === "none") return false;
      if (view === "mine" && a.created_by !== me.actor_id) return false;
    }
    return true;
  }, [showResolved, focusId, adding, view, me.actor_id]);

  useEffect(() => {
    const instance = editorRef.current;
    if (!instance || instance.isDestroyed || !ready) return;
    const list = tabAnns.filter(markVisible).map((a) => ({
      id: a.id,
      anchor: a.anchor,
      cls: markClass(a, String(focusId) === String(a.id)) + (String(flashId) === String(a.id) ? " pd-flash" : ""),
      title: hasCard(a, adding) ? undefined
        : `${a.created_by_name} ’s${a.style === "ul" ? uiText("docSurface.underline") : uiText("docSurface.highlight")} · ${shortTime(a.created_at)}`,
    }));
    instance.view.dispatch(instance.state.tr.setMeta(annotationKey, { items: list }).setMeta("addToHistory", false));
  }, [tabAnns, markVisible, focusId, flashId, adding, ready, locale]);

  // ---------- 右邊欄、列旁的 💬、＋ 新增一列：照內文的位置擺 ----------
  const cardAnns = useMemo(() => tabAnns.filter((a) => {
    if (!hasCard(a, adding) || a.orphaned_at) return false;
    if (a.resolved_at && !showResolved && String(focusId) !== String(a.id)) return false;
    return true;
  }), [tabAnns, adding, showResolved, focusId]);
  const layoutInputs = useRef({});
  layoutInputs.current = { cardAnns, tabAnns, mode };

  scheduleLayout.current = () => {
    const instance = editorRef.current;
    const surface = surfaceRef.current;
    if (!instance || instance.isDestroyed || !surface) return;
    const { cardAnns: cards, tabAnns: all, mode: currentMode } = layoutInputs.current;
    const pm = instance.view;
    const base = surface.getBoundingClientRect();
    const narrow = currentMode === "sheet";
    const plugin = annotationKey.getState(pm.state);
    const ranges = plugin ? plugin.ranges : new Map();
    const rows = new Map();
    const next = { items: [], rows: [], adds: [], bars: [], height: surface.offsetHeight };
    pm.state.doc.forEach((node, offset) => {
      if (node.type.name !== "table") return;
      const wrap = pm.nodeDOM(offset);
      const wrapRect = wrap && wrap.getBoundingClientRect ? wrap.getBoundingClientRect() : null;
      let rowPos = offset + 1;
      node.forEach((row) => {
       rows.set(row.attrs.bid, { pos: rowPos, node: row });
        if (!isHeaderRowNode(row) && rowHasField(row)) {
          const dom = pm.nodeDOM(rowPos);
          if (dom && dom.getBoundingClientRect && wrapRect) {
            const rect = dom.getBoundingClientRect();
            const talk = all.find((a) => a.kind === "row" && a.anchor.rid === row.attrs.bid && !a.draft);
            const count = talk ? comments(talk).length : 0;
            const has = Boolean(talk && (talk.messages || []).length);
            const first = dom.firstElementChild ? dom.firstElementChild.getBoundingClientRect() : rect;
            next.rows.push({
              rid: row.attrs.bid, count, has,
              top: Math.round(narrow ? rect.bottom - base.top - 32 : rect.top - base.top + 9),
              left: narrow ? Math.round(Math.max(first.left, wrapRect.left) - base.left + 10) : null,
            });
            if (has) next.bars.push({ rid: row.attrs.bid, top: Math.round(rect.top - base.top), left: Math.round(Math.max(rect.left, wrapRect.left) - base.left), height: Math.round(rect.height) });
          }
        }
        rowPos += row.nodeSize;
      });
      if (!narrow && wrapRect && canAddRow(node, ctxRef.current)) {
        next.adds.push({ table: node.attrs.bid, top: Math.round(wrapRect.bottom - base.top + 4), left: Math.round(wrapRect.left - base.left) });
      }
    });
    for (const a of cards) {
      if (a.kind === "row") {
        const info = rows.get(a.anchor.rid);
        const dom = info ? pm.nodeDOM(info.pos) : null;
        if (!dom || !dom.getBoundingClientRect) continue;
        next.items.push({ a, want: Math.round(dom.getBoundingClientRect().top - base.top), rowLabel: clip(rowLabel(info.node.toJSON()), 24) });
      } else {
        const range = ranges.get(a.id);
        if (!range) continue;
        try {
          next.items.push({ a, want: Math.round(pm.coordsAtPos(range.from).top - base.top), rowLabel: null });
        } catch { /* 還沒畫出來 */ }
      }
    }
    next.items.sort((x, y) => x.want - y.want);
    setLayout((prev) => {
      const key = (l) => JSON.stringify([l.items.map((i) => [i.a.id, i.want, i.a]), l.rows, l.adds, l.bars, l.height]);
      return key(prev) === key(next) ? prev : next;
    });
  };

  useLayoutEffect(() => { scheduleLayout.current(); }, [cardAnns, tabAnns, mode, ready, focusId]);

  useEffect(() => {
    const fit = () => setMode(marginMode(wrapRef.current && wrapRef.current.clientWidth));
    const onResize = () => { fit(); requestAnimationFrame(() => scheduleLayout.current()); };
    window.addEventListener("resize", onResize);
    const observer = new ResizeObserver(() => scheduleLayout.current());
    if (surfaceRef.current) observer.observe(surfaceRef.current);
    // 助理側邊欄打開、收起、拖拉調寬時，視窗沒變但文件區變了
    const wrapObserver = new ResizeObserver(() => fit());
    if (wrapRef.current) wrapObserver.observe(wrapRef.current);
    const late = setTimeout(() => scheduleLayout.current(), 400);
    return () => {
      window.removeEventListener("resize", onResize);
      observer.disconnect();
      wrapObserver.disconnect();
      clearTimeout(late);
    };
  }, []);

  useEffect(() => { document.body.classList.toggle("mslim", mode === "slim"); }, [mode]);
  useEffect(() => () => document.body.classList.remove("mslim"), []);

  // 從清單點過來：捲到那一則、閃一下
  useEffect(() => {
    if (!focusRequest || !ready) return undefined;
    const instance = editorRef.current;
    const timerId = setTimeout(() => {
      const a = latest.current.tabAnns.find((x) => String(x.id) === String(focusRequest.id));
      if (!a || !instance || instance.isDestroyed) return;
      let top = null;
      if (a.kind === "row") {
        instance.state.doc.descendants((node, pos) => {
          if (top === null && node.type.name === "tableRow" && node.attrs.bid === a.anchor.rid) {
            const dom = instance.view.nodeDOM(pos);
            if (dom && dom.getBoundingClientRect) top = dom.getBoundingClientRect().top;
          }
        });
      } else {
        const plugin = annotationKey.getState(instance.state);
        const range = plugin && plugin.ranges.get(a.id);
        if (range) top = instance.view.coordsAtPos(range.from).top;
      }
      if (top !== null) window.scrollBy({ top: top - window.innerHeight / 2.6, behavior: "smooth" });
    }, 60);
    return () => clearTimeout(timerId);
  }, [focusRequest, ready]);

  // ---------- 選字工具列 ----------
  const myMarksIn = (state, from, to) => {
    const plugin = annotationKey.getState(state);
    if (!plugin) return [];
    return latest.current.tabAnns.filter((a) => {
      if (a.kind !== "text" || a.draft || a.created_by !== me.actor_id || a.label || comments(a).length || !a.style) return false;
      const range = plugin.ranges.get(a.id);
      return range && range.from < to && range.to > from;
    });
  };

  const readSelection = useCallback(() => {
    const instance = editorRef.current;
    if (!instance || instance.isDestroyed) return;
    const domSel = window.getSelection();
    if (!domSel || !domSel.rangeCount || domSel.isCollapsed) { setSel(null); setLabelMenu(false); return; }
    const range = domSel.getRangeAt(0);
    const root = instance.view.dom;
    if (!root.contains(range.startContainer) || !root.contains(range.endContainer)) { setSel(null); setLabelMenu(false); return; }
    let from;
    let to;
    try {
      from = instance.view.posAtDOM(range.startContainer, range.startOffset);
      to = instance.view.posAtDOM(range.endContainer, range.endOffset);
    } catch {
      setSel(null);
      return;
    }
    if (to < from) [from, to] = [to, from];
    const picked = selectionAnchor(instance.state.doc, from, to);
    if (!picked) { setSel(null); return; }
    if (picked.tooLong) { latest.current.onToast(uiText("docSurface.selectUpToCharactersForAnAnnotation")); setSel(null); return; }
    const units = unitsInRange(instance.state.doc, from, to);
    const editable = !attachId && units.length > 0 && units.every((unit) => unitEditable(unit, ctxRef.current));
    const rect = range.getBoundingClientRect();
    setSel({ anchor: picked.anchor, from, to, editable, mine: myMarksIn(instance.state, from, to), rect });
    setMarkPop(null);
  }, [attachId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const up = (event) => {
      if (event.target.closest && event.target.closest(".seltb, .labelmenu, .toolbar, .menu, .card, .sheet, .pop")) return;
      setTimeout(readSelection, 0);
    };
    const key = (event) => { if (event.shiftKey || event.key === "Shift") setTimeout(readSelection, 0); };
    let selTimer = null;
    const change = () => {
      const narrow = window.matchMedia(NARROW).matches;
      const domSel = window.getSelection();
      if (domSel && domSel.isCollapsed) { setSel(null); setLabelMenu(false); return; }
      if (!narrow) return;
      clearTimeout(selTimer);
      selTimer = setTimeout(readSelection, 300);
    };
    document.addEventListener("mouseup", up);
    document.addEventListener("keyup", key);
    document.addEventListener("selectionchange", change);
    return () => {
      document.removeEventListener("mouseup", up);
      document.removeEventListener("keyup", key);
      document.removeEventListener("selectionchange", change);
      clearTimeout(selTimer);
    };
  }, [readSelection]);

  // 標完就把選取收起來。只清瀏覽器的選取不夠：編輯器下一次更新會把它自己的選取放回去，
  // 字一直反白，再拖一次會變成「拖著那段字走」而不是重新選字。
  const finishSel = () => {
    const instance = editorRef.current;
    if (instance && !instance.isDestroyed && !instance.state.selection.empty) {
      const { state } = instance;
      instance.view.dispatch(state.tr.setSelection(TextSelection.near(state.doc.resolve(state.selection.to))).setMeta("addToHistory", false));
    }
    const domSel = window.getSelection();
    if (domSel) domSel.removeAllRanges();
    setSel(null);
    setLabelMenu(false);
  };

  // 選字工具列置中在選到的字上方（量實際寬度）
  useLayoutEffect(() => {
    const bar = seltbRef.current;
    if (!bar || !sel || mode === "sheet") return;
    const width = bar.offsetWidth;
    const left = Math.max(8, Math.min(sel.rect.left + sel.rect.width / 2 - width / 2, window.innerWidth - width - 8));
    bar.style.left = `${Math.round(left)}px`;
  }, [sel, mode, attachId]);

  const firstTip = useRef(false);
  const tipOnce = () => {
    if (firstTip.current) return;
    firstTip.current = true;
    onToast(uiText("docSurface.highlightsAndUnderlinesAreVisibleToEveryoneWithoutSending"));
  };

  const createAnnotation = async (body) => {
    if (!(await flush())) throw new Error(uiText("docSurface.saveTheSourceAndResolveEditingConflictsFirst"));
    const result = await api.post(`/projects/api/${slug}/annotations`, { tab_key: tab.key, ...body, source_revision: sync.current.revision });
    onAnnotation(result.annotation);
    if (result.annotation.agent_request) onAgentRouted?.(result.annotation.agent_request);
    return result.annotation;
  };

  const run = async (work) => {
    setBusy(true);
    try {
      return await work();
    } catch (error) {
      onError(error.message);
      return null;
    } finally {
      setBusy(false);
    }
  };

  const onHighlight = (color) => run(async () => {
    const current = sel;
    finishSel();
    if (!current) return;
    const hls = current.mine.filter((a) => a.style === "hl");
    if (hls.some((a) => a.color === color)) {
      for (const a of hls.filter((x) => x.color === color)) {
        await api.post(`/projects/api/${slug}/annotations/${a.id}/delete`, {});
        onAnnotation({ deleted: a.id });
      }
      onToast(uiText("docSurface.highlightRemoved"));
    } else if (hls.length) {
      for (const a of hls) {
        const result = await api.post(`/projects/api/${slug}/annotations/${a.id}/style`, { style: "hl", color });
        onAnnotation(result.annotation);
      }
      onToast(uiText("docSurface.changedToColor", {v0: (COLORS[color][0])}));
    } else {
      await createAnnotation({ anchor: current.anchor, style: "hl", color });
      tipOnce();
    }
  });

  const onUnderline = () => run(async () => {
    const current = sel;
    finishSel();
    if (!current) return;
    const uls = current.mine.filter((a) => a.style === "ul");
    if (uls.length) {
      for (const a of uls) {
        await api.post(`/projects/api/${slug}/annotations/${a.id}/delete`, {});
        onAnnotation({ deleted: a.id });
      }
      onToast(uiText("docSurface.underlineRemoved"));
    } else {
      await createAnnotation({ anchor: current.anchor, style: "ul" });
      tipOnce();
    }
  });

  const onRemoveMine = () => run(async () => {
    const current = sel;
    finishSel();
    if (!current) return;
    for (const a of current.mine) {
      await api.post(`/projects/api/${slug}/annotations/${a.id}/delete`, {});
      onAnnotation({ deleted: a.id });
    }
    onToast(uiText("docSurface.removedHighlightsUnderlines", {v0: (current.mine.length)}));
  });

  const onLabel = (label) => run(async () => {
    const current = sel;
    finishSel();
    if (!current) return;
    const created = await createAnnotation({ anchor: current.anchor, label });
    if (label === "ok") {
      onToast(uiText("docSurface.recordedApprovedThisPassage", {v0: (me.name)}));
    } else {
      setAdding((set) => new Set(set).add(created.id));
      onFocus(created.id);
    }
  });

  const onNote = (agentKey = null) => {
    const current = sel;
    finishSel();
    if (!current) return;
    const draft = {
      id: "d-" + newId(""), kind: "text", tab_key: tab.key, anchor: current.anchor, draft: true, style: null, color: null,
      label: null, created_by: me.actor_id, created_by_name: me.name, created_at: nowIso(), messages: [],
      initialText: typeof agentKey === 'string' ? `@${agentKey} ` : '',
    };
    setDrafts((list) => [...list, draft]);
    onFocus(draft.id);
  };

  const onAttach = () => run(async () => {
    const current = sel;
    finishSel();
    if (!current || !attachId) return;
    await flush();
    const result = await api.post(`/projects/api/${slug}/annotations/${attachId}/reattach`, { anchor: current.anchor });
    onAnnotation(result.annotation);
    onAttachDone();
    onToast(uiText("docSurface.reattached"));
    onFocus(result.annotation.id, { flash: true });
  });

  const applyFormat = (kind) => {
    const instance = editorRef.current;
    if (!instance || !sel || !sel.editable) return;
    const chain = instance.chain().focus().setTextSelection({ from: sel.from, to: sel.to });
    if (kind === "bold") chain.toggleBold().run();
    if (kind === "italic") chain.toggleItalic().run();
    if (kind === "strike") chain.toggleStrike().run();
    if (kind === "link") { chain.run(); setDialog({ kind: "link" }); }
    setTimeout(readSelection, 0);
  };

  // 丟掉沒送出的草稿：焦點一離開就丟（跟樣稿一樣）
  useEffect(() => {
    setDrafts((list) => {
      const kept = list.filter((d) => String(d.id) === String(focusId));
      return kept.length === list.length ? list : kept;
    });
    setAdding((set) => {
      if (!set.size) return set;
      const keep = [...set].filter((id) => String(id) === String(focusId));
      return keep.length === set.size ? set : new Set(keep);
    });
  }, [focusId]);

  // ---------- 卡片上的動作 ----------
  const act = async (a, action, extra = {}) => {
    if (action === "send") {
      const sent = await run(async () => {
        let result;
        if (a.draft && a.kind === "row") result = await createAnnotation({ row: a.anchor.rid, body: extra.body });
        else if (a.draft) result = await createAnnotation({ anchor: a.anchor, body: extra.body });
        else {
          if (!(await flush())) throw new Error(uiText("docSurface.saveTheSourceAndResolveEditingConflictsFirst"));
          const data = await api.post(`/projects/api/${slug}/annotations/${a.id}/comments`, { body: extra.body, source_revision: sync.current.revision });
          onAnnotation(data.annotation);
          if (data.annotation.agent_request) onAgentRouted?.(data.annotation.agent_request);
          result = data.annotation;
        }
        return result;
      });
      if (!sent) return false;
      if (a.draft) { setDrafts((list) => list.filter((d) => d.id !== a.id)); onFocus(sent.id); }
      const mentioned = [...new Set((extra.body.match(/@\{([0-9a-f-]{36})\}/g) || []).map((token) => token.slice(2, -1)))]
        .filter((id) => id !== me.actor_id).map((id) => memberNames.get(id)).filter(Boolean);
      onToast(mentioned.length ? uiText("docSurface.sentWillSeeThisInNeedsYou", {v0: (mentioned.join("、"))}) : uiText("docSurface.sent"));
      return true;
    }
    if (action === "cancel") { setDrafts((list) => list.filter((d) => d.id !== a.id)); onFocus(null); return true; }
    if (action === "add-note") { setAdding((set) => new Set(set).add(a.id)); onFocus(a.id); return true; }
    const result = await run(async () => {
      if (action === "resolve" || action === "reopen") {
        const data = await api.post(`/projects/api/${slug}/annotations/${a.id}/resolve`, { resolved: action === "resolve" });
        onAnnotation(data.annotation);
        if (action === "resolve") { onFocus(null); onToast(uiText("docSurface.resolvedReopenItFromAnnotationsAll")); }
        return true;
      }
      if (action === "reconfirm") {
        const data = await api.post(`/projects/api/${slug}/annotations/${a.id}/reconfirm`, {});
        onAnnotation(data.annotation);
        onToast(uiText("docSurface.recordedApprovedThisPassageAgain", {v0: (me.name)}));
        return true;
      }
      if (action === "remove") {
        const others = comments(a).some((m) => m.actor.actor_id !== me.actor_id);
        if (others && !window.confirm(uiText("docSurface.deleteThisAnnotationAndItsCrewReplies"))) return false;
        await api.post(`/projects/api/${slug}/annotations/${a.id}/delete`, {});
        onAnnotation({ deleted: a.id });
        onFocus(null);
        onToast(a.label === "ok" && !comments(a).length ? uiText("docSurface.approvalRemoved") : uiText("docSurface.deleted"));
        return true;
      }
      if (action === "del-comment") {
        if (!window.confirm(uiText("docSurface.deleteThisComment"))) return false;
        await api.post(`/projects/api/${slug}/comments/${extra.comment}/delete`, {});
        onAnnotation({ ...a, messages: (a.messages || []).filter((m) => String(m.id) !== String(extra.comment)) });
        return true;
      }
      return false;
    });
    return Boolean(result);
  };

  const onCardClick = (event) => {
    const card = event.target.closest(".card");
    if (!card) return;
    const a = byId(card.dataset.ann);
    if (!a) return;
    const actEl = event.target.closest("[data-act]");
    if (!actEl) { if (String(focusId) !== String(a.id)) onFocus(a.id); return; }
    act(a, actEl.dataset.act, { comment: actEl.dataset.comment });
  };

  const openRowTalk = (rid) => {
    const existing = tabAnns.find((a) => a.kind === "row" && a.anchor.rid === rid);
    if (existing) { onFocus(existing.id); return; }
    const draft = {
      id: "d-row-" + rid, kind: "row", tab_key: tab.key, anchor: { rid }, draft: true, label: null, style: null,
      created_by: me.actor_id, created_by_name: me.name, created_at: nowIso(), messages: [],
    };
    setDrafts((list) => [...list.filter((d) => d.id !== draft.id), draft]);
    onFocus(draft.id);
  };

  // ---------- ＋ 新增區塊、＋ 新增一列 ----------
  const gutterHide = useRef(null);
  const onSurfaceMove = (event) => {
    const instance = editorRef.current;
    if (!instance || instance.isDestroyed || mode === "sheet" || insMenu) return;
    if (event.target.closest && event.target.closest(".gutter, .addrow, .rowbtn, .table-bar")) return;
    const pm = instance.view;
    const base = surfaceRef.current.getBoundingClientRect();
    let found = null;
    let index = 0;
    for (const child of pm.dom.children) {
      const rect = child.getBoundingClientRect();
      if (rect.height && event.clientY >= rect.top - 8 && event.clientY <= rect.bottom + 8) {
        try {
          const pos = pm.posAtDOM(child, 0);
          index = pm.state.doc.resolve(Math.min(pos, pm.state.doc.content.size)).index(0);
        } catch { break; }
        const heading = /^H[1-3]$/.test(child.tagName);
        found = { top: Math.round(rect.top - base.top + (heading ? 4 : 0)), index };
        break;
      }
    }
    if (found) {
      clearTimeout(gutterHide.current);
      setGutter((g) => (g && g.top === found.top && g.index === found.index ? g : found));
    }
  };
  const onSurfaceLeave = () => {
    clearTimeout(gutterHide.current);
    gutterHide.current = setTimeout(() => setGutter((g) => (insMenu ? g : null)), 600);
  };

  const ownerAttrs = () => (admin ? { bid: newId("b"), owner: null, created: null } : { bid: newId("b"), owner: me.actor_id, created: nowIso() });

  const insertBlock = (index, type) => {
    const instance = editorRef.current;
    if (!instance) return;
    setInsMenu(null);
    const { schema, doc } = instance.state;
    const n = schema.nodes;
    const para = (text) => n.paragraph.create(null, text ? schema.text(text) : null);
    const attrs = ownerAttrs();
    let node;
    if (type === "p") node = n.paragraph.create(attrs);
    else if (type === "h2") node = n.heading.create({ ...attrs, level: 2 });
    else if (type === "ul") node = n.bulletList.create(attrs, n.listItem.create(null, para()));
    else if (type === "task") node = n.taskList.create(attrs, n.taskItem.create({ checked: false }, para()));
    else if (type === "quote") node = n.blockquote.create(attrs, para());
    else {
      const head = n.tableRow.create(ownerAttrs(), [1, 2, 3].map((i) => n.tableHeader.create(null, para(uiText("docSurface.column", {v0: (i)})))));
      const body = n.tableRow.create(ownerAttrs(), [1, 2, 3].map(() => n.tableCell.create(null, para())));
      node = n.table.create(attrs, [head, body]);
    }
    let pos = 0;
    for (let i = 0; i <= Math.min(index, doc.childCount - 1); i += 1) pos += doc.child(i).nodeSize;
    const tr = instance.state.tr.insert(pos, node);
    const inside = type === "table" ? pos + 1 + node.child(0).nodeSize + 3
      : pos + ({ p: 1, h2: 1, quote: 2 }[type] || 3);
    tr.setSelection(TextSelection.near(tr.doc.resolve(Math.min(inside, tr.doc.content.size))));
    instance.view.dispatch(tr.setMeta(TRUSTED, true));
    instance.view.focus();
  };

  const addRow = (tableBid) => {
    const instance = editorRef.current;
    if (!instance) return;
    const { state } = instance;
    let tablePos = -1;
    let table = null;
    state.doc.forEach((node, offset) => { if (node.attrs.bid === tableBid) { tablePos = offset; table = node; } });
    if (!table) return;
    const n = state.schema.nodes;
    const header = table.firstChild && isHeaderRowNode(table.firstChild) ? table.firstChild : null;
    const sample = table.lastChild && !isHeaderRowNode(table.lastChild) ? table.lastChild : null;
    const width = table.firstChild ? table.firstChild.childCount : 1;
    const cells = [];
    for (let i = 0; i < width; i += 1) {
      const like = sample && i < sample.childCount ? sample.child(i) : null;
      let inner = null;
      if (like) like.descendants((child) => { if (!inner && (child.type.name === "status" || child.type.name === "fill")) inner = child; });
      const title = header && i < header.childCount ? header.child(i).textContent : "";
      let content = null;
      if ((inner && inner.type.name === "status") || /狀態/.test(title)) content = n.status.create({ label: "Queued" });
      else if (inner && inner.type.name === "fill") content = n.fill.create({ label: inner.attrs.label || "" });
      cells.push(n.tableCell.create(null, n.paragraph.create(null, content)));
    }
    const row = n.tableRow.create(ownerAttrs(), cells);
    const at = tablePos + table.nodeSize - 1;
    const tr = state.tr.insert(at, row);
    tr.setSelection(TextSelection.near(tr.doc.resolve(at + 3)));
    instance.view.dispatch(tr.setMeta(TRUSTED, true));
    instance.view.focus();
  };

  // ---------- 其他 ----------
  useEffect(() => {
    const beforeUnload = (event) => {
      if (dirty.current || inflight.current) { event.preventDefault(); event.returnValue = ""; }
    };
    const hidden = () => { if (document.visibilityState === "hidden") flush(); };
    window.addEventListener("beforeunload", beforeUnload);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      window.removeEventListener("beforeunload", beforeUnload);
      document.removeEventListener("visibilitychange", hidden);
    };
  }, [flush]);

  useEffect(() => () => clearTimeout(timer.current), []);
  useEffect(() => { document.body.classList.toggle("wide", wide); requestAnimationFrame(() => scheduleLayout.current()); }, [wide]);
  const closeMenu = useCallback(() => setMenu(null), []);
  useOutside(toolbarRef, closeMenu, Boolean(menu));

  useEffect(() => {
    if (!markPop && !insMenu) return undefined;
    const close = (event) => {
      if (event.target.closest && event.target.closest(".markpop, .ins-menu, .gutter")) return;
      setMarkPop(null);
      setInsMenu(null);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [markPop, insMenu]);

  async function uploadImage(file) {
    if (!IMAGE_TYPES.includes(file.type)) { latest.current.onError(uiText("docSurface.chooseAPNGJPEGGIFOrWebPImage")); return; }
    if (file.size > 8 * 1024 * 1024) { latest.current.onError(uiText("docSurface.imagesMustBeMBOrSmaller")); return; }
    try {
      latest.current.onToast(uiText("docSurface.uploadingImage"));
      const result = await api.upload(`/projects/api/${slug}/assets`, file);
      const caption = file.name.replace(/\.[^.]+$/, "");
      editorRef.current.chain().focus().insertContent({ type: "image", attrs: { src: result.src, alt: caption, title: caption } }).run();
      latest.current.onToast(uiText("docSurface.imageAdded"));
    } catch (error) {
      latest.current.onError(error.message);
    }
  }

  const restore = async (revision) => {
    setDialog(null);
    if (!(await flush())) return;
    try {
      const result = await api.post(`/projects/api/${slug}/tabs/${tab.key}/revisions/${revision}/restore`, {});
      patchDoc(editorRef.current, result.doc);
      resetSync(result.doc, result.revision, result.saved_at);
      session.current = { id: "s-" + newId(""), lastSave: 0 };
      setSaveState({ kind: "saved", at: result.saved_at });
      onSaved({ revision: result.revision, saved_at: result.saved_at, doc: result.doc, title: result.title });
      if (result.annotations) onAnnotations(result.annotations);
      onToast(uiText("docSurface.restoredRevisionThePreviousContentRemainsAvailableInVersion", {v0: (revision)}));
    } catch (error) {
      onError(error.message);
    }
  };

  const tableAtCursor = () => {
    if (!editor) return null;
    const $from = editor.state.selection.$from;
    for (let depth = $from.depth; depth > 0; depth -= 1) if ($from.node(depth).type.name === "table") return $from.node(depth);
    return null;
  };
  const cursorTable = editor ? tableAtCursor() : null;
  const ownTable = Boolean(cursorTable && blockEditable(cursorTable, ctxRef.current));

  const menus = editor ? {
    table: ownTable ? [
      { key: "ins", label: uiText("docSurface.insertTableWithAHeaderRow"), run: () => editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run() },
      "sep",
      { key: "rb", label: uiText("docSurface.insertRowAbove"), disabled: !editor.can().addRowBefore(), run: () => editor.chain().focus().addRowBefore().run() },
      { key: "ra", label: uiText("docSurface.insertRowBelow"), disabled: !editor.can().addRowAfter(), run: () => editor.chain().focus().addRowAfter().run() },
      { key: "cb", label: uiText("docSurface.insertColumnLeft"), disabled: !editor.can().addColumnBefore(), run: () => editor.chain().focus().addColumnBefore().run() },
      { key: "ca", label: uiText("docSurface.insertColumnRight"), disabled: !editor.can().addColumnAfter(), run: () => editor.chain().focus().addColumnAfter().run() },
      "sep",
      { key: "dr", label: uiText("docSurface.deleteRow"), disabled: !editor.can().deleteRow(), run: () => editor.chain().focus().deleteRow().run() },
      { key: "dc", label: uiText("docSurface.deleteColumn"), disabled: !editor.can().deleteColumn(), run: () => editor.chain().focus().deleteColumn().run() },
      { key: "dt", label: uiText("docSurface.deleteTable"), danger: true, disabled: !editor.can().deleteTable(), run: () => editor.chain().focus().deleteTable().run() },
    ] : [
      { key: "ins", label: uiText("docSurface.insertTableWithAHeaderRow"), run: () => editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run() },
      ...(cursorTable && canAddRow(cursorTable, ctxRef.current)
        ? [{ key: "add", label: uiText("docSurface.appendARowToThisTable"), run: () => addRow(cursorTable.attrs.bid) }] : []),
    ],
    plus: items.map((item) => ({ ...item, run: () => item.run(editor) })),
  } : {};

  const toolButton = (name, label, extra = {}) => {
    const open = Boolean(menu && menu.name === name);
    return (
      <span className="tb-wrap">
        <button type="button" className={"tb" + (open ? " on" : "")} aria-haspopup="menu" aria-expanded={open} title={extra.title}
          onMouseDown={(event) => { event.preventDefault(); setMenu(open ? null : { name, rect: event.currentTarget.getBoundingClientRect() }); }}>
          {label}
        </button>
        {open && menus[name] && <Menu items={menus[name]} onClose={closeMenu} rect={menu.rect} hint={extra.hint} />}
      </span>
    );
  };

  const stateText = {
    saved: uiText("docSurface.saved"),
    dirty: uiText("docSurface.editing"),
    saving: uiText("docSurface.saving"),
    error: uiText("docSurface.notSavedRetryingInSeconds"),
  }[saveState.kind];
  const stateTip = saveState.kind === "error" ? saveState.message
    : uiText("docSurface.clickOutsideToSaveAutomatically", {v0: (editing ? uiText("docSurface.editing2", {v0: (editing.what)}) : ""), v1: (saveState.at ? `; last saved ${shortTime(saveState.at)}` : "")});

  const fields = useMemo(() => ({ values: values || {}, onField }), [values, onField]);
  const cardProps = { me, members, agents, busy, adding, onAct: act };
  const focusedItem = layout.items.find((it) => String(it.a.id) === String(focusId))
    || (focusId ? (() => { const a = byId(focusId); return a ? { a, want: 0, rowLabel: null } : null; })() : null);
  const orphanCount = annotations.filter((a) => a.tab_key === tab.key && a.orphaned_at && !a.resolved_at).length;
  const showToolbar = Boolean(editing) || saveState.kind === "error";

  return (
    <div className="surface-wrap" ref={wrapRef}>
      <div className="edit-slot">
      <div className={"toolbar" + (showToolbar ? " on" : "")} ref={toolbarRef} role="toolbar" aria-label={uiText("docSurface.editingTools")}
        onMouseDown={(event) => { if (event.target === event.currentTarget) event.preventDefault(); }}>
        <button type="button" className="tb" title={uiText("docSurface.undoCtrlZ")} aria-label={uiText("docSurface.undo")} disabled={!history.undo}
          onMouseDown={(event) => { event.preventDefault(); editor && editor.chain().focus().undo().run(); }}>↶</button>
        <button type="button" className="tb" title={uiText("docSurface.redoCtrlY")} aria-label={uiText("docSurface.redo")} disabled={!history.redo}
          onMouseDown={(event) => { event.preventDefault(); editor && editor.chain().focus().redo().run(); }}>↷</button>
        <button type="button" className={"tb" + (wide ? " on" : "")} title={uiText("docSurface.pageWidth")} aria-label={uiText("docSurface.pageWidth")}
          onMouseDown={(event) => { event.preventDefault(); setWide(!wide); }}>↔</button>
        <span className="vsep" />
        {toolButton("table", "▦ ▾", { title: uiText("docSurface.table") })}
        <button type="button" className="tb" title={uiText("docSurface.insertImage")} aria-label={uiText("docSurface.insertImage")} onMouseDown={(event) => { event.preventDefault(); pickImage(); }}><Icon name="image" /></button>
        <button type="button" className="tb" title={uiText("docSurface.checklist")} aria-label={uiText("docSurface.checklist")}
          onMouseDown={(event) => { event.preventDefault(); editor && editor.chain().focus().toggleTaskList().run(); }}>☑</button>
        {toolButton("plus", "＋ ▾", { title: uiText("docSurface.insert"), hint: uiText("docSurface.typeInTheDocumentToOpenThisMenu") })}
        <span className="spacer" />
        <span className={"save-state " + saveState.kind} role="status" title={stateTip}>{stateText}</span>
        <button type="button" className="tb" title={uiText("docSurface.doneEditingClickOutsideToSave")}
          onMouseDown={(event) => { event.preventDefault(); if (editor) editor.commands.blur(); setEditing(null); flush().then(() => releaseIdle()); }}>{uiText("docSurface.complete")}</button>
        <input ref={fileInput} type="file" accept={IMAGE_TYPES.join(",")} hidden
          onChange={(event) => { const file = event.target.files[0]; event.target.value = ""; if (file) uploadImage(file); }} />
      </div>
      {!showToolbar && (
        <div className="meta-line">{uiText("docSurface.lastUpdated", {v0: (shortTime(tab.updated_at)), v1: (tab.updated_by_name ? `・${tab.updated_by_name}` : "")})}{onOpenHistory && <button type="button" className="hist-link" onClick={onOpenHistory}>{uiText("docSurface.changeHistory")}</button>}
        </div>
      )}
      </div>

      <div className="page">
        <div className="surface" ref={surfaceRef} onMouseMove={onSurfaceMove} onMouseLeave={onSurfaceLeave}
          onMouseEnter={() => clearTimeout(gutterHide.current)}
          onMouseDown={(event) => {
            // 點在內文下面的空白：游標放到最後
            if (!editorRef.current) return;
            const pm = surfaceRef.current.querySelector(".ProseMirror");
            if (!pm || pm.contains(event.target) || event.target.closest(".rowbtn, .addrow, .gutter, .table-bar")) return;
            if (event.clientY < pm.getBoundingClientRect().bottom - 4) return;
            event.preventDefault();
            editorRef.current.chain().focus("end").run();
          }}>
          {gutter && mode !== "sheet" && (
            <button type="button" className="gutter on" style={{ top: gutter.top }} title={uiText("docSurface.addContentBelowThisBlock")}
              onMouseEnter={() => clearTimeout(gutterHide.current)}
              onMouseDown={(event) => event.preventDefault()}
              onClick={(event) => {
                const rect = event.currentTarget.getBoundingClientRect();
                const block = editor && editor.state.doc.childCount > gutter.index ? editor.state.doc.child(gutter.index) : null;
                setInsMenu({ index: gutter.index, top: Math.min(rect.top, window.innerHeight - 330), left: rect.right + 6,
                  label: clip(block ? block.textContent : "", 14) });
              }}><span>＋</span></button>
          )}
          <FieldsContext.Provider value={fields}>
            <EditorContent editor={editor} />
          </FieldsContext.Provider>
          {tableBar && editor && (
            <div className="table-bar" role="toolbar" aria-label={uiText("docSurface.table")} style={{ top: tableBar.top, left: tableBar.left }}>
              {[
                [uiText("docSurface.rowAbove"), () => editor.chain().focus().addRowBefore().run()],
                [uiText("docSurface.rowBelow"), () => editor.chain().focus().addRowAfter().run()],
                [uiText("docSurface.columnLeft"), () => editor.chain().focus().addColumnBefore().run()],
                [uiText("docSurface.columnRight"), () => editor.chain().focus().addColumnAfter().run()],
                "sep",
                [uiText("docSurface.deleteRow"), () => editor.chain().focus().deleteRow().run()],
                [uiText("docSurface.deleteColumn"), () => editor.chain().focus().deleteColumn().run()],
                "sep",
                [uiText("docSurface.deleteTable"), () => editor.chain().focus().deleteTable().run(), "danger"],
              ].map((item, index) => (item === "sep" ? <span key={index} className="vsep" /> : (
                <button type="button" key={item[0]} className={item[2] || undefined}
                  onMouseDown={(event) => { event.preventDefault(); item[1](); }}>{item[0]}</button>
              )))}
            </div>
          )}
          <div className="overlay">
            {layout.bars.map((bar) => (
              <span key={"bar" + bar.rid} className="thread-bar" style={{ top: bar.top, left: bar.left, height: bar.height }} />
            ))}
            {layout.rows.map((row) => (
              <button type="button" key={"row" + row.rid} className={"rowbtn" + (row.has ? " has" : "")}
                style={row.left === null ? { top: row.top } : { top: row.top, left: row.left, right: "auto" }}
                title={uiText("docSurface.rowDiscussionAndStatusHistory")} aria-label={uiText("docSurface.rowDiscussionAndStatusHistory")} onClick={() => openRowTalk(row.rid)}>
                <Icon name="comment" />{row.count ? ` ${row.count}` : ""}
              </button>
            ))}
            {layout.adds.map((add) => (
              <button type="button" key={"add" + add.table} className="addrow" style={{ top: add.top, left: add.left }}
                onMouseDown={(event) => event.preventDefault()} onClick={() => addRow(add.table)}>{uiText("docSurface.addRow")}</button>
            ))}
          </div>
        </div>
        {mode !== "sheet" && (
          <Margin mode={mode} items={layout.items} focusId={focusId} orphans={orphanCount} minHeight={layout.height}
            cardProps={cardProps} onBubble={(id) => onFocus(String(focusId) === String(id) ? null : id)}
            onCardClick={onCardClick} onOrphans={() => onOpenPanel("orphan")} />
        )}
      </div>

      {mode === "sheet" && focusedItem && (
        <Sheet item={focusedItem} tabTitle={current.title} cardProps={cardProps} onCardClick={onCardClick} onClose={() => onFocus(null)} />
      )}

      {sel && (
        <div className="seltb on" role="toolbar" aria-label={uiText("docSurface.annotationTools")} ref={seltbRef}
          style={mode === "sheet" ? undefined : {
            left: Math.max(8, sel.rect.left),
            top: Math.min(window.innerHeight - 56, Math.max(58, sel.rect.top - 48)),
          }}
          onMouseDown={(event) => event.preventDefault()}>
          {attachId ? (
            <>
              <button type="button" onClick={onAttach}>{uiText("docSurface.attachHere")}</button>
              <button type="button" onClick={() => { finishSel(); onAttachDone(); }}>{uiText("docSurface.cancel")}</button>
            </>
          ) : (
            <>
              {sel.editable && (
                <span className="fmt">
                  <button type="button" title={uiText("docSurface.bold")} onClick={() => applyFormat("bold")}>B</button>
                  <button type="button" title={uiText("docSurface.italic")} onClick={() => applyFormat("italic")}><i>I</i></button>
                  <button type="button" title={uiText("docSurface.strikethrough")} onClick={() => applyFormat("strike")}><s>S</s></button>
                  <button type="button" title={uiText("docSurface.link")} onClick={() => applyFormat("link")}><Icon name="link" /></button>
                </span>
              )}
              <span className="grp"><span>{uiText("docSurface.highlight")}</span>
                {Object.entries(COLORS).map(([key, [name, color]]) => (
                  <button type="button" key={key} className={"dot" + (sel.mine.some((a) => a.style === "hl" && a.color === key) ? " on" : "")}
                    title={uiText("docSurface.highlightChooseAgainToRemove", {v0: (name)})} disabled={busy} onClick={() => onHighlight(key)}>
                    <i style={{ background: color }} />
                  </button>
                ))}
              </span>
              <button type="button" className={sel.mine.some((a) => a.style === "ul") ? "on" : undefined}
                title={uiText("docSurface.underlineThisTextChooseAgainToRemove")} disabled={busy} onClick={onUnderline}><span className="u">{uiText("docSurface.underline")}</span></button>
              {sel.mine.length > 0 && <button type="button" className="rm" title={uiText("docSurface.removeYourHighlightsAndUnderlinesFromThisPassage")} disabled={busy} onClick={onRemoveMine}>{uiText("docSurface.remove")}</button>}
              <button type="button" title={uiText("docSurface.markAsQuestionReviseOrApproved")} onClick={() => setLabelMenu(!labelMenu)}>{uiText("docSurface.annotate")}</button>
              <button type="button" title={uiText("docSurface.addANoteAndMentionCrewMembers")} onClick={() => onNote()}>{uiText("docSurface.addNote")}</button>
              {me.can_write && agents.some(agent => agent.agent_key === 'doc_writer' && agent.enabled) &&
                <button type="button" title={uiText("docSurface.createAnAgentTaskForTheSelectedPassageProcessing")} onClick={() => onNote('doc_writer')}>{uiText("docSurface.assignToAgent")}</button>}
            </>
          )}
        </div>
      )}
      {sel && labelMenu && (
        <div className="labelmenu on" onMouseDown={(event) => event.preventDefault()}
          style={mode === "sheet" ? undefined : { left: Math.max(8, Math.min(sel.rect.left, window.innerWidth - 300)), top: Math.min(window.innerHeight - 200, Math.max(58, sel.rect.top - 48) + 44) }}>
          {Object.entries(LABELS).map(([key, label]) => (
            <button type="button" key={key} disabled={busy} onClick={() => onLabel(key)}>
              <span className={"chip " + label.cls}>{label.name}</span><span><small>{label.hint}</small></span>
            </button>
          ))}
        </div>
      )}
      {markPop && (
        <div className="markpop on" style={{ top: markPop.top, left: markPop.left }}>
          <Avatar id={markPop.a.created_by} name={markPop.a.created_by_name} size={18} />
          <span><b>{markPop.a.created_by_name}</b>{uiText("docSurface.s", {v0: (markPop.a.style === "ul" ? uiText("docSurface.underline") : uiText("docSurface.highlight")), v1: (shortTime(markPop.a.created_at))})}</span>
          <button type="button" className="linkish" onClick={() => { const a = markPop.a; setMarkPop(null); setAdding((set) => new Set(set).add(a.id)); onFocus(a.id); }}>{uiText("docSurface.addNote2")}</button>
          {(admin || markPop.a.created_by === me.actor_id) && (
            <button type="button" className="linkish danger" onClick={() => { const a = markPop.a; setMarkPop(null); act(a, "remove"); }}>{uiText("docSurface.remove2")}</button>
          )}
        </div>
      )}
      {insMenu && (
        <div className="menu on ins-menu" style={{ top: insMenu.top, left: insMenu.left }} onMouseDown={(event) => event.preventDefault()}>
          {NEW_BLOCKS().map(([key, icon, label]) => (
            <button type="button" key={key} onClick={() => insertBlock(insMenu.index, key)}><span className="mi">{icon}</span>{label}</button>
          ))}
          <div className="note">{uiText("docSurface.addBelow", {v0: (insMenu.label || uiText("docSurface.thisBlock")), v1: (admin ? "" : `, attributed to ${me.name} `)})}</div>
        </div>
      )}

      {slash && slash.list.length > 0 && (
        <div className="menu slash-menu" role="listbox" style={{ position: "fixed", top: Math.min(slash.top, window.innerHeight - 320), left: Math.max(8, Math.min(slash.left, window.innerWidth - 270)) }}>
          {slash.list.map((item, index) => (
            <button type="button" key={item.key} role="option" aria-selected={index === slash.index}
              className={index === slash.index ? "sel" : undefined}
              onMouseDown={(event) => { event.preventDefault(); runSlash(item); }}>
              <span className="mi">{item.icon}</span>{item.label}
            </button>
          ))}
        </div>
      )}

      {linkPop && editor && (
        <div className="link-pop" style={{ top: linkPop.top, left: linkPop.left }} role="dialog" aria-label={uiText("docSurface.link")}>
          <button type="button" className="go" onMouseDown={(event) => { event.preventDefault(); setLinkPop(null); openLink(linkPop.href); }}>
            {internalTab(linkPop.href)
              ? uiText("docSurface.goTo", {v0: ((tabs.find((t) => t.key === internalTab(linkPop.href)) || {}).title || linkPop.href)})
              : <>{uiText("docSurface.open")}<span className="url">{linkPop.href}</span> ↗</>}
          </button>
          <span className="vsep" />
          <button type="button" onMouseDown={(event) => { event.preventDefault(); setDialog({ kind: "link" }); }}>{uiText("docSurface.edit")}</button>
          <button type="button" onMouseDown={(event) => {
            event.preventDefault();
            editor.chain().focus().extendMarkRange("link").unsetLink().run();
            setLinkPop(null);
          }}>{uiText("docSurface.removeLink")}</button>
        </div>
      )}

      {dialog && dialog.kind === "versions" && (
        <VersionsDialog slug={slug} tabKey={tab.key} flush={flush} onClose={() => setDialog(null)} onError={onError}
          onPick={(revision) => setDialog({ kind: "restore", revision })} />
      )}
      {dialog && dialog.kind === "restore" && (
        <Dialog title={uiText("docSurface.restoreRevision", {v0: (dialog.revision)})} confirmLabel={uiText("docSurface.restore")}
          message={uiText("docSurface.restoreExplanation")} onCancel={() => setDialog(null)}
          onConfirm={() => restore(dialog.revision)} />
      )}
      {dialog && dialog.kind === "link" && editor && (
        <Dialog title={uiText("docSurface.link")} input={{ value: editor.getAttributes("link").href || "", placeholder: uiText('common.dialogHttpsOrSelectAPageBelow') }}
          inputLabel={uiText("common.inputURL")} confirmLabel={uiText("docSurface.apply")}
          select={{ label: uiText('common.dialogOrLinkToAPage'), value: "", options: [{ value: "", label: uiText('common.dialogNone') }, ...tabs.map((t) => ({ value: "#" + t.key, label: t.title }))] }}
          onCancel={() => setDialog(null)}
          onConfirm={({ text, choice }) => {
            setDialog(null);
            const href = choice || text;
            if (!href) { editor.chain().focus().extendMarkRange("link").unsetLink().run(); return; }
            if (!LINK_OK.test(href)) { onError("Enter an https:// link or select a page."); return; }
            const chain = editor.chain().focus().extendMarkRange("link");
            if (editor.state.selection.empty) {
              const label = choice ? (tabs.find((t) => "#" + t.key === choice) || {}).title : href;
              chain.insertContent({ type: "text", text: label, marks: [{ type: "link", attrs: { href } }] }).run();
            } else {
              chain.setLink({ href }).run();
            }
          }} />
      )}
    </div>
  );
}

// 找回以前的內容：重新整理或關掉頁面之後，復原（Ctrl+Z）的紀錄就沒了，要從這裡找。
function VersionsDialog({ slug, tabKey, flush, onClose, onPick, onError }) {
  const locale = useLocale();
  const [revisions, setRevisions] = useState(null);
  useEffect(() => {
    let alive = true;
    (async () => {
      await flush();
      try {
        const data = await api.get(`/projects/api/${slug}/tabs/${tabKey}/revisions`);
        if (alive) setRevisions(data.revisions);
      } catch (error) {
        onError(error.message);
        onClose();
      }
    })();
    return () => { alive = false; };
  }, [slug, tabKey, flush, onClose, onError]);
  return (
    <Dialog title={uiText("docSurface.versionHistory")} confirmLabel={uiText("docSurface.close")} onCancel={onClose} onConfirm={onClose}
      message={uiText("docSurface.undoExplanation")}>
      {!revisions && <p className="modal-msg">{uiText("docSurface.loading")}</p>}
      {revisions && revisions.map((rev, index) => (
        <div key={rev.revision} className="deleted-row">
          <span>{shortTime(rev.saved_at)}・{rev.saved_by_name || "—"}{rev.restored ? uiText("docSurface.restored") : ""}
            <small>{uiText("docSurface.revisionItems", {v0: (rev.revision), v1: (index === 0 ? uiText("docSurface.currentContent") : "")})}</small></span>
          {index > 0 && <button type="button" className="ghost" onClick={() => onPick(rev.revision)}>{uiText("docSurface.restoreThisRevision")}</button>}
        </div>
      ))}
    </Dialog>
  );
}
