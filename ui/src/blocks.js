// 一塊一塊存（前端這半）：算出哪幾塊改了 → ops；伺服器的新版本回來時，沒在改的塊換新、正在改的保留。
// 伺服器那半在 project_docs/blocks.py。clean：每一塊上次同步後在編輯器裡的樣子（stable 字串）。

export function stable(value) {
  if (Array.isArray(value)) return "[" + value.map(stable).join(",") + "]";
  if (value && typeof value === "object") {
    return "{" + Object.keys(value).sort().filter((key) => value[key] !== undefined)
      .map((key) => JSON.stringify(key) + ":" + stable(value[key])).join(",") + "}";
  }
  return JSON.stringify(value === undefined ? null : value);
}

export const bidOf = (node) => (node && node.attrs && node.attrs.bid) || null;

export function isHeaderRow(row) {
  const cells = (row && row.content) || [];
  return cells.length > 0 && cells.every((cell) => cell.type === "tableHeader");
}

function textOf(node) {
  if (!node || typeof node !== "object") return "";
  if (node.type === "text") return node.text || "";
  return (node.content || []).map(textOf).join("");
}

const BLANK_TYPES = new Set(["paragraph", "heading", "bulletList", "orderedList", "taskList", "blockquote"]);

// 還沒打字的新塊（編輯器自己補的空段落、按了＋還沒打字）：先不送
export function isBlankNew(node) {
  return BLANK_TYPES.has(node.type) && !textOf(node).trim();
}

function headSignature(table) {
  const rows = table.content || [];
  const first = rows[0] || {};
  return stable({ attrs: table.attrs || {}, header: isHeaderRow(first) ? first : null, width: (first.content || []).length });
}

// 表頭、欄數、表格屬性都沒變：逐列存（別人同時改別列不會互相蓋掉）；不然回 null，整張表一起存
function tableRowOps(bid, base, cleanTable, table) {
  if (headSignature(cleanTable) !== headSignature(table)) return null;
  const cleanRows = new Map((cleanTable.content || []).map((r) => [bidOf(r), stable(r)]));
  const baseRows = new Map((base.content || []).map((r) => [bidOf(r), r]));
  const ops = [];
  const seen = new Set();
  let prev = null;
  for (const row of table.content || []) {
    const rid = bidOf(row);
    if (!rid) return null;
    seen.add(rid);
    if (!isHeaderRow(row)) {
      const known = cleanRows.get(rid);
      if (known === undefined) ops.push({ op: "put_row", table: bid, rid, after: prev, node: row, base: null });
      else if (stable(row) !== known) ops.push({ op: "put_row", table: bid, rid, after: prev, node: row, base: baseRows.get(rid) || null });
    }
    prev = rid;
  }
  const order = (table.content || []).map(bidOf).filter((rid) => cleanRows.has(rid));
  const cleanOrder = (cleanTable.content || []).map(bidOf).filter((rid) => seen.has(rid));
  if (stable(order) !== stable(cleanOrder)) return null;
  for (const [rid] of cleanRows) {
    if (!seen.has(rid) && baseRows.has(rid)) ops.push({ op: "del_row", table: bid, rid, base: baseRows.get(rid) });
  }
  return ops;
}

export function computeOps({ server, clean, current }) {
  const ops = [];
  const serverBlocks = new Map((server.content || []).map((node) => [bidOf(node), node]));
  const blocks = current.content || [];
  const seen = new Set();
  let prev = null;
  for (const node of blocks) {
    const bid = bidOf(node);
    if (!bid) continue;
    seen.add(bid);
    const known = clean.get(bid);
    const base = serverBlocks.get(bid) || null;
    if (known === undefined) {
      if (isBlankNew(node)) continue;
      ops.push({ op: "put", bid, after: prev, node, base: null });
    } else if (stable(node) !== known) {
      const rows = node.type === "table" && base && base.type === "table" ? tableRowOps(bid, base, JSON.parse(known), node) : null;
      if (rows) ops.push(...rows);
      else ops.push({ op: "put", bid, after: prev, node, base });
    }
    prev = bid;
  }
  for (const [bid, base] of serverBlocks) {
    if (bid && !seen.has(bid) && clean.has(bid)) ops.push({ op: "del", bid, base });
  }
  // 段落順序換了（誰搬的都算，10/15 起大家一起編輯）
  const serverOrder = (server.content || []).map(bidOf).filter((bid) => seen.has(bid));
  const currentOrder = blocks.map(bidOf).filter((bid) => serverBlocks.has(bid));
  if (stable(serverOrder) !== stable(currentOrder)) ops.push({ op: "order", bids: blocks.map(bidOf).filter(Boolean) });
  return ops;
}

// 伺服器的新內文 ＋ 自己正在改的塊 → 要換上的整份內文（kept：保留下來的自己的塊；deleted：自己刪了還沒存的）。
// force：這幾塊一律用伺服器的（存檔被擋下的那幾塊）。keepBid：游標所在的空白新塊（剛按＋還沒打字）也留著。
export function mergeServer({ server, clean, current, force = new Set(), keepBid = null }) {
  const dirty = new Map();
  const pending = [];
  const prevOf = new Map();
  let prev = null;
  for (const node of current.content || []) {
    const bid = bidOf(node);
    if (bid) prevOf.set(bid, prev);
    const known = bid ? clean.get(bid) : undefined;
    if (known === undefined) {
      const throwaway = node.type === "paragraph" && isBlankNew(node) && bid !== keepBid;
      if (!throwaway) pending.push({ after: prev, node });
    } else if (stable(node) !== known && !force.has(bid)) {
      dirty.set(bid, node);
    }
    if (bid) prev = bid;
  }
  const serverBids = new Set((server.content || []).map(bidOf));
  for (const [bid, node] of dirty) {
    if (!serverBids.has(bid)) {
      // 自己正在改、別人已經刪掉的塊：當成新塊重新送
      dirty.delete(bid);
      pending.push({ after: prevOf.get(bid) || null, node });
    }
  }
  // 自己刪掉、還沒存的塊：伺服器那邊還在，但不要放回來（存的時候會送出 del）
  const currentBids = new Set((current.content || []).map(bidOf).filter(Boolean));
  const deleted = new Set();
  for (const node of server.content || []) {
    const bid = bidOf(node);
    if (bid && clean.has(bid) && !currentBids.has(bid) && !force.has(bid)) deleted.add(bid);
  }
  const merged = [];
  const placed = new Set();
  const follow = (bid) => {
    for (const item of pending) {
      if (item.after === bid && !placed.has(item)) {
        placed.add(item);
        merged.push(item.node);
        follow(bidOf(item.node));
      }
    }
  };
  follow(null);
  for (const node of server.content || []) {
    const bid = bidOf(node);
    if (!deleted.has(bid)) merged.push(dirty.has(bid) ? dirty.get(bid) : node);
    follow(bid);
  }
  for (const item of pending) {
    if (placed.has(item)) continue;
    placed.add(item);
    const last = merged[merged.length - 1];
    const beforeTrailing = last && last.type === "paragraph" && isBlankNew(last) ? merged.length - 1 : merged.length;
    merged.splice(beforeTrailing, 0, item.node);
  }
  const kept = new Set([...dirty.keys(), ...pending.map((item) => bidOf(item.node)).filter(Boolean)]);
  return { doc: { type: "doc", content: merged }, kept, deleted };
}
