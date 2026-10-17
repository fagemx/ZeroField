// 從文件 JSON 取文字、列名稱、可填欄。跟伺服器 project_docs/doc_schema.py 的規則一致。
export function nodeText(node) {
  if (!node || typeof node !== "object") return "";
  if (node.type === "text") return node.text || "";
  if (node.type === "status") return (node.attrs && node.attrs.label) || "";
  if (node.type === "hardBreak") return " ";
  return (node.content || []).map(nodeText).join("");
}

export function rowLabel(row) {
  const cells = (row && row.content) || [];
  const first = cells.length ? nodeText(cells[0]).trim() : "";
  if (/^\d+$/.test(first) && cells.length > 1) return first + ". " + nodeText(cells[1]).trim();
  return first;
}

export function contains(node, types) {
  if (!node || typeof node !== "object") return false;
  if (types.includes(node.type)) return true;
  return (node.content || []).some((child) => contains(child, types));
}

export function isHeaderRow(row) {
  const cells = (row && row.content) || [];
  return cells.length > 0 && cells.every((cell) => cell.type === "tableHeader");
}

// 表格裡哪幾欄有「大家可填」的格子
export function fillColumns(table) {
  const columns = new Set();
  for (const row of (table && table.content) || []) {
    (row.content || []).forEach((cell, index) => {
      if (contains(cell, ["fill"])) columns.add(index);
    });
  }
  return columns;
}

export function anchorsOf(doc) {
  const anchors = {};
  const walk = (node) => {
    if (!node || typeof node !== "object") return;
    const bid = node.attrs && node.attrs.bid;
    if (node.type === "heading" && bid) anchors[bid] = nodeText(node).trim();
    if (node.type === "tableRow" && bid) anchors[bid] = rowLabel(node);
    (node.content || []).forEach(walk);
  };
  walk(doc);
  return anchors;
}
