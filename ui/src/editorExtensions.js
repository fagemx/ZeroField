import { Extension, Node, mergeAttributes } from "@tiptap/core";
import { TaskItem } from "@tiptap/extension-list";
import { Fragment, Slice } from "@tiptap/pm/model";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

import { anchorRange, textIndex } from "./anchoring.js";
import { shortTime, statusClass } from "./format.js";
import { fillNodeView, statusNodeView, taskItemNodeView } from "./nodeViews.jsx";
import { blockEditable, rowEditable, unitEditable, unitsInRange } from "./permissions.js";

export const SYSTEM = "pdSystem"; // 系統自己改的（補 id、換上伺服器內容）：不擋、不算使用者的修改
export const REMOTE = "pdRemote"; // 換上伺服器的新版本：標註要重新對位
export const TRUSTED = "pdTrusted"; // 我們自己的介面動作（＋ 新增一列、＋ 新增區塊）：呼叫前已經檢查過權限
export const BLOCK_TYPES = ["paragraph", "heading", "bulletList", "orderedList", "taskList", "table", "blockquote", "image", "horizontalRule"];
const ID_RE = /^[A-Za-z0-9_-]{4,40}$/;
const FID_TYPES = new Set(["taskItem", "status", "fill"]);

export function newId(prefix) {
  const bytes = crypto.getRandomValues(new Uint8Array(6));
  const text = btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return prefix + text;
}

export function nowIso() {
  return new Date().toISOString().replace(/\.\d+Z$/, "Z");
}

// 錨點與欄位 id：第一層區塊、標題、表格列要 bid；勾選項、狀態、可填格要 fid。缺了或重複（複製貼上、拆段落）就補新的。
// mine：非管理者自己打出來的新區塊／新列（還沒有 owner 的）當場記成他的，存檔前就能接著改（伺服器存的時候也會這樣填）。
export function ensureIds(state, mine = null) {
  const seen = new Set();
  let tr = null;
  state.doc.descendants((node, pos, parent) => {
    const name = node.type.name;
    let attr = null;
    if (FID_TYPES.has(name)) attr = "fid";
    else if (name === "tableRow" || name === "heading" || (parent === state.doc && BLOCK_TYPES.includes(name))) attr = "bid";
    if (!attr) return;
    const value = node.attrs[attr];
    if (typeof value === "string" && ID_RE.test(value) && !seen.has(value)) {
      seen.add(value);
      return;
    }
    let fresh = newId(attr === "bid" ? "b" : "f");
    while (seen.has(fresh)) fresh = newId(attr === "bid" ? "b" : "f");
    seen.add(fresh);
    tr = tr || state.tr;
    const attrs = { ...node.attrs, [attr]: fresh };
    if (mine && attr === "bid" && "owner" in node.attrs && !node.attrs.owner) Object.assign(attrs, { owner: mine, created: nowIso() });
    tr.setNodeMarkup(pos, undefined, attrs);
  });
  if (tr) tr.setMeta("addToHistory", false).setMeta(SYSTEM, true);
  return tr;
}

const dataAttribute = (name, keepOnSplit) => ({
  default: null,
  keepOnSplit,
  parseHTML: (element) => element.getAttribute(`data-${name}`),
  renderHTML: (attrs) => (attrs[name] ? { [`data-${name}`]: attrs[name] } : {}),
});

export const BlockIds = Extension.create({
  name: "projectIds",
  addOptions() {
    return { getOwner: () => null }; // 非管理者回傳自己的 actor_id；管理者回 null（新增的算本文）
  },
  addGlobalAttributes() {
    return [
      { types: [...BLOCK_TYPES, "tableRow"],
        attributes: { bid: dataAttribute("bid", false), owner: dataAttribute("owner", true), created: dataAttribute("created", true) } },
      { types: ["taskItem"], attributes: { fid: dataAttribute("fid", false) } },
      { types: ["table"], attributes: {
        sheet_name: { default: null }, worksheet_name: { default: null }, column_types: { default: null },
      } },
    ];
  },
  addProseMirrorPlugins() {
    return [new Plugin({
      key: new PluginKey("projectIds"),
      appendTransaction: (transactions, _old, state) => {
        if (!transactions.some((tr) => tr.docChanged)) return null;
        const byUser = transactions.some((tr) => tr.docChanged && !tr.getMeta(SYSTEM) && !tr.getMeta(REMOTE));
        return ensureIds(state, byUser ? this.options.getOwner() : null);
      },
    })];
  },
});

// ---------- 權限守門：不能改的塊沒游標、不跳鍵盤（contenteditable=false）；改到了也擋下來 ----------

export const permissionKey = new PluginKey("pdPermission");

function textEndInside(node, pos) {
  if (node.isTextblock) return pos + node.nodeSize - 1;
  let found = null;
  node.descendants((child, offset) => {
    if (found !== null) return false;
    if (child.isTextblock) {
      found = pos + 1 + offset + child.nodeSize - 1;
      return false;
    }
    return true;
  });
  return found;
}

function lockChip(at, name) {
  return Decoration.widget(at, () => {
    const chip = document.createElement("span");
    chip.className = "pd-lockchip";
    chip.contentEditable = "false";
    chip.textContent = `${name} 正在編輯`;
    return chip;
  }, { side: 1, ignoreSelection: true, key: `lock-${name}-${at}` });
}

function ownerNote(node, ctx) {
  const owner = node.attrs.owner;
  if (!owner || ctx.adminIds.has(owner)) return null;
  const name = ctx.names.get(owner) || "已不在名單的人";
  return `— ${name} 新增${node.attrs.created ? " · " + shortTime(node.attrs.created) : ""}`;
}

function permissionDecorations(doc, ctx) {
  const decorations = [];
  doc.forEach((node, pos) => {
    if (node.type.name === "table") {
      const tableMine = ctx.admin || (node.attrs.owner && node.attrs.owner === ctx.me);
      let rowPos = pos + 1;
      let anyEditable = false;
      node.forEach((row) => {
        const editable = rowEditable(row, node, ctx);
        if (editable) anyEditable = true;
        else decorations.push(Decoration.node(rowPos, rowPos + row.nodeSize, { contenteditable: "false", class: "pd-ro" }));
        const note = ownerNote(row, ctx);
        if (note && row.firstChild) {
          decorations.push(Decoration.node(rowPos + 1, rowPos + 1 + row.firstChild.nodeSize, { "data-owner-note": note }));
        }
        const locker = ctx.locks.get(row.attrs.bid);
        const end = locker && textEndInside(row, rowPos);
        if (end !== null && end !== undefined && locker) decorations.push(lockChip(end, locker));
        rowPos += row.nodeSize;
      });
      const attrs = {};
      if (!anyEditable && !tableMine) Object.assign(attrs, { contenteditable: "false", class: "pd-ro" });
      const note = ownerNote(node, ctx);
      if (note) attrs["data-owner-note"] = note;
      if (Object.keys(attrs).length) decorations.push(Decoration.node(pos, pos + node.nodeSize, attrs));
      return;
    }
    const attrs = {};
    if (!blockEditable(node, ctx)) Object.assign(attrs, { contenteditable: "false", class: "pd-ro" });
    const note = ownerNote(node, ctx);
    if (note) attrs["data-owner-note"] = note;
    if (Object.keys(attrs).length) decorations.push(Decoration.node(pos, pos + node.nodeSize, attrs));
    const locker = ctx.locks.get(node.attrs.bid);
    const end = locker ? textEndInside(node, pos) : null;
    if (locker && end !== null) decorations.push(lockChip(end, locker));
  });
  return DecorationSet.create(doc, decorations);
}

function allowed(tr, ctx) {
  if (!tr.docChanged || tr.getMeta(SYSTEM) || tr.getMeta(REMOTE) || tr.getMeta(TRUSTED)) return true;
  if (ctx.admin && ctx.locks.size === 0) return true;
  for (let i = 0; i < tr.steps.length; i += 1) {
    const doc = tr.docs[i];
    const step = tr.steps[i];
    const ranges = [];
    step.getMap().forEach((from, to) => ranges.push([from, to]));
    if (typeof step.from === "number") ranges.push([step.from, typeof step.to === "number" ? step.to : step.from]);
    if (typeof step.pos === "number") ranges.push([step.pos, step.pos + 1]);
    for (const [from, to] of ranges) {
      for (const unit of unitsInRange(doc, from, to)) {
        if (!unitEditable(unit, ctx)) {
          ctx.onBlocked(unit);
          return false;
        }
      }
    }
  }
  return true;
}

// 貼上的內容：新的塊算是貼的人新增的（不沿用來源的 bid／owner）
function ownPasted(slice, ctx) {
  const owner = ctx.admin ? null : ctx.me;
  const created = ctx.admin ? null : nowIso();
  const fix = (fragment) => {
    const nodes = [];
    fragment.forEach((node) => {
      if (node.isText) {
        nodes.push(node);
        return;
      }
      const attrs = "owner" in node.attrs ? { ...node.attrs, bid: null, owner, created } : node.attrs;
      nodes.push(node.type.create(attrs, fix(node.content), node.marks));
    });
    return Fragment.fromArray(nodes);
  };
  return new Slice(fix(slice.content), slice.openStart, slice.openEnd);
}

export const PermissionGuard = Extension.create({
  name: "pdPermission",
  addOptions() {
    return { getCtx: () => ({ me: null, admin: true, locks: new Map(), names: new Map(), adminIds: new Set(), onBlocked: () => {} }) };
  },
  addProseMirrorPlugins() {
    const getCtx = this.options.getCtx;
    return [new Plugin({
      key: permissionKey,
      state: {
        init: (_config, state) => permissionDecorations(state.doc, getCtx()),
        apply: (tr, old, _oldState, newState) => (tr.docChanged || tr.getMeta(permissionKey) ? permissionDecorations(newState.doc, getCtx()) : old),
      },
      props: {
        decorations(state) { return this.getState(state); },
        transformPasted(slice) { return ownPasted(slice, getCtx()); },
      },
      filterTransaction: (tr) => allowed(tr, getCtx()),
    })];
  },
});

// ---------- 標註層：每一則畫成 inline decoration；打字時跟著移、整份換掉時重新對位 ----------

export const annotationKey = new PluginKey("pdAnnotations");

function buildAnnotations(doc, items) {
  const index = textIndex(doc);
  const decorations = [];
  const ranges = new Map();
  for (const item of items) {
    const range = item.range || anchorRange(index, item.anchor);
    if (!range) continue;
    ranges.set(item.id, { from: range.from, to: range.to });
    const attrs = { class: item.cls, "data-ann": String(item.id) };
    if (item.title) attrs.title = item.title;
    decorations.push(Decoration.inline(range.from, range.to, attrs, { inclusiveStart: false, inclusiveEnd: false, id: item.id }));
  }
  return { deco: DecorationSet.create(doc, decorations), ranges, items };
}

export const AnnotationLayer = Extension.create({
  name: "pdAnnotations",
  addProseMirrorPlugins() {
    return [new Plugin({
      key: annotationKey,
      state: {
        init: () => ({ deco: DecorationSet.empty, ranges: new Map(), items: [] }),
        apply(tr, value, _oldState, newState) {
          const meta = tr.getMeta(annotationKey);
          if (meta) return buildAnnotations(newState.doc, meta.items);
          if (!tr.docChanged) return value;
          if (tr.getMeta(REMOTE)) return buildAnnotations(newState.doc, value.items);
          const ranges = new Map();
          for (const [id, range] of value.ranges) {
            const from = tr.mapping.map(range.from, 1);
            const to = tr.mapping.map(range.to, -1);
            if (to > from) ranges.set(id, { from, to });
          }
          return { deco: value.deco.map(tr.mapping, tr.doc), ranges, items: value.items };
        },
      },
      props: { decorations(state) { return this.getState(state).deco; } },
    })];
  },
});

// ---------- 表格裡「大家可填」的欄：表頭加標記（不是內文） ----------

function fillColumnDecorations(doc) {
  const decorations = [];
  doc.descendants((node, pos) => {
    if (node.type.name !== "table") return true;
    const columns = new Set();
    node.forEach((row) => {
      let index = 0;
      row.forEach((cell) => {
        let has = false;
        cell.descendants((child) => { if (child.type.name === "fill") has = true; });
        if (has) columns.add(index);
        index += 1;
      });
    });
    let rowPos = pos + 1;
    node.forEach((row) => {
      let header = row.childCount > 0;
      row.forEach((cell) => { if (cell.type.name !== "tableHeader") header = false; });
      let field = false;
      row.descendants((child) => { if (child.type.name === "status" || child.type.name === "fill") field = true; });
      if (field && !header) decorations.push(Decoration.node(rowPos, rowPos + row.nodeSize, { class: "tracked-row" }));
      rowPos += row.nodeSize;
    });
    if (columns.size && node.firstChild) {
      let cellPos = pos + 2;
      let index = 0;
      node.firstChild.forEach((cell) => {
        if (cell.type.name === "tableHeader" && columns.has(index)) {
          decorations.push(Decoration.node(cellPos, cellPos + cell.nodeSize, { class: "fill-col" }));
        }
        cellPos += cell.nodeSize;
        index += 1;
      });
    }
    return false;
  });
  return DecorationSet.create(doc, decorations);
}

export const FillColumns = Extension.create({
  name: "fillColumns",
  addProseMirrorPlugins() {
    return [new Plugin({
      key: new PluginKey("fillColumns"),
      state: {
        init: (_config, state) => fillColumnDecorations(state.doc),
        apply: (tr, old) => (tr.docChanged ? fillColumnDecorations(tr.doc) : old),
      },
      props: { decorations(state) { return this.getState(state); } },
    })];
  },
});

// 狀態膠囊：值在 field_value；文件裡只記預設值。誰都能在膠囊上點選改值。
export const StatusNode = Node.create({
  name: "status",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,
  addAttributes() {
    return {
      fid: dataAttribute("fid", false),
      label: {
        default: "未開始",
        parseHTML: (element) => element.getAttribute("data-label") || "未開始",
        renderHTML: (attrs) => ({ "data-label": attrs.label }),
      },
    };
  },
  parseHTML() {
    return [{ tag: "span[data-status]" }];
  },
  renderHTML({ HTMLAttributes, node }) {
    return ["span", mergeAttributes(HTMLAttributes, { "data-status": "", class: "badge " + statusClass(node.attrs.label) }), node.attrs.label];
  },
  renderText({ node }) {
    return node.attrs.label;
  },
  addNodeView() {
    return statusNodeView;
  },
});

// 大家可填的格子：內容在 field_value；誰都能點它填。
export const FillNode = Node.create({
  name: "fill",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,
  addAttributes() {
    return {
      fid: dataAttribute("fid", false),
      label: {
        default: "",
        parseHTML: (element) => element.getAttribute("data-label") || "",
        renderHTML: (attrs) => ({ "data-label": attrs.label || "" }),
      },
    };
  },
  parseHTML() {
    return [{ tag: "span[data-fill]" }];
  },
  renderHTML({ HTMLAttributes }) {
    return ["span", mergeAttributes(HTMLAttributes, { "data-fill": "", class: "fill-chip" }), "大家可填"];
  },
  renderText() {
    return "";
  },
  addNodeView() {
    return fillNodeView;
  },
});

// 勾選項：勾或不勾存在 field_value（誰都能勾，有紀錄）；文件裡的 checked 只是預設值。
export const ProjectTaskItem = TaskItem.extend({
  addNodeView() {
    return taskItemNodeView;
  },
}).configure({ nested: true });

// ---------- 專案助理：在那一列的文字後面放「✦ 一起回答」（裝飾，不寫進文件；滑鼠移到那一列才出現） ----------

export const assistKey = new PluginKey("pdAssist");

function assistChip(at, rid, label, ctx) {
  return Decoration.widget(at, () => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "pa-chip";
    chip.contentEditable = "false";
    chip.textContent = "✦ " + label;
    chip.title = "跟專案助理一起做這一項";
    chip.addEventListener("mousedown", (event) => event.preventDefault());
    chip.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      ctx().onAssist(rid);
    });
    return chip;
  }, { side: 1, ignoreSelection: true, stopEvent: () => true, key: `assist-${rid}-${label}` });
}

function assistDecorations(doc, getCtx) {
  const chips = getCtx().chips;
  if (!chips || !chips.size) return DecorationSet.empty;
  const decorations = [];
  doc.descendants((node, pos) => {
    if (node.type.name !== "tableRow") return true;
    const chip = chips.get(node.attrs.bid);
    if (chip) {
      let index = 0;
      node.forEach((cell, offset) => {
        if (index === chip.cell) {
          const end = textEndInside(cell, pos + 1 + offset);
          if (end !== null) decorations.push(assistChip(end, node.attrs.bid, chip.label, getCtx));
        }
        index += 1;
      });
    }
    return false;
  });
  return DecorationSet.create(doc, decorations);
}

export const AssistChips = Extension.create({
  name: "pdAssist",
  addOptions() {
    return { getCtx: () => ({ chips: null, onAssist: () => {} }) };
  },
  addProseMirrorPlugins() {
    const getCtx = this.options.getCtx;
    return [new Plugin({
      key: assistKey,
      state: {
        init: (_config, state) => assistDecorations(state.doc, getCtx),
        apply: (tr, old, _oldState, newState) => (tr.docChanged || tr.getMeta(assistKey) ? assistDecorations(newState.doc, getCtx) : old),
      },
      props: { decorations(state) { return this.getState(state); } },
    })];
  },
});
