// 誰能改哪一塊（跟伺服器 project_docs/blocks.py 一致；伺服器會再檢查一次）。
// 2026-10-15 起大家一起編輯：名單上的人都能改任何一塊、任何一列；擋的只剩別人正拿著編輯鎖。
// 誰改了什麼記在系統紀錄。單位：第一層區塊；表格細到列。ctx：{ me: actor_id, admin: bool, locks: Map(單位 id → 拿鎖的人的名字) }

export function isHeaderRowNode(row) {
  if (!row || row.childCount === 0) return false;
  let all = true;
  row.forEach((cell) => { if (cell.type.name !== "tableHeader") all = false; });
  return all;
}

export function blockEditable(node, ctx) {
  return ctx.canWrite !== false && !ctx.locks.has(node.attrs.bid);
}

export function rowEditable(row, table, ctx) {
  return ctx.canWrite !== false && !ctx.locks.has(row.attrs.bid) && !ctx.locks.has(table.attrs.bid);
}

export function canAddRow(table, ctx) {
  return ctx.canWrite !== false && !ctx.locks.has(table.attrs.bid);
}

// 左邊分頁的「⋯」：管理者每一頁都能改名、移動、刪除；名單上的人只有自己新增的那幾頁
export function canManageTab(tab, me) {
  return me.can_write !== false && Boolean(me.can_edit || (tab.created_by && tab.created_by === me.actor_id));
}

// 範圍碰到哪些單位（插在兩塊中間的位置不算碰到任何一塊）
export function unitsInRange(doc, from, to) {
  const out = [];
  const hits = (start, end) => (from === to ? from > start && from < end : from < end && to > start);
  doc.forEach((node, offset) => {
    const start = offset;
    const end = offset + node.nodeSize;
    if (!hits(start, end)) return;
    if (node.type.name !== "table") {
      out.push({ kind: "block", node, pos: start });
      return;
    }
    let rowStart = start + 1;
    let any = false;
    node.forEach((row) => {
      const rowEnd = rowStart + row.nodeSize;
      if (hits(rowStart, rowEnd)) {
        out.push({ kind: "row", node: row, table: node, pos: rowStart, tablePos: start });
        any = true;
      }
      rowStart = rowEnd;
    });
    if (!any) out.push({ kind: "table", node, pos: start });
  });
  return out;
}

export function unitEditable(unit, ctx) {
  if (unit.kind === "row") return rowEditable(unit.node, unit.table, ctx);
  return blockEditable(unit.node, ctx);
}
