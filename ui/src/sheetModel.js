export const newId = () => "b" + crypto.randomUUID().replaceAll("-", "").slice(0, 12);
export const clone = (value) => JSON.parse(JSON.stringify(value));
export const textCell = (text, type = "tableCell") => ({ type, content: [{ type: "paragraph", content: String(text ?? "") ? [{ type: "text", text: String(text) }] : [] }] });

export function readCell(node, values = {}) {
  let value = "", kind = "text", fid = null;
  const walk = (n) => {
    if (n.type === "text") value += n.text || "";
    if (n.type === "hardBreak") value += "\n";
    if (n.type === "image") { value = `![${n.attrs?.alt || "Image"}](${n.attrs?.src})`; kind = "image"; }
    if (n.type === "status" || n.type === "fill") {
      kind = n.type; fid = n.attrs?.fid;
      value = values[fid]?.value ?? (kind === "status" ? n.attrs?.label || "Queued" : "");
    }
    for (const c of n.content || []) walk(c);
  };
  walk(node);
  return { value, kind, fid, rawNode: node };
}

export function tablesOf(doc, values = {}) {
  return (doc?.content || []).filter((n) => n.type === "table").map((table, index) => {
    const first = table.content?.[0];
    const hasHeader = first?.content?.every((c) => c.type === "tableHeader");
    return { table, tableId: table.attrs.bid, name: table.attrs.sheet_name || table.attrs.worksheet_name || `Table ${index + 1}`,
      headers: hasHeader ? first.content.map((c) => readCell(c, values).value) : first?.content?.map((_, i) => columnName(i)) || [],
      header: hasHeader ? first : null,
     rows: (table.content || []).slice(hasHeader ? 1 : 0).map((row) => ({ rid: row.attrs.bid, rawRow: row, cells: row.content.map((c) => readCell(c, values)) })) };
  });
}

export function columnName(index) {
  let result = "";
  for (let n = index + 1; n > 0; n = Math.floor((n - 1) / 26)) result = String.fromCharCode(65 + (n - 1) % 26) + result;
  return result;
}

// TSV from Excel supports quoted tabs, newlines and escaped quotes.
export function parseTSV(text) {
  const rows = [[]]; let value = "", quoted = false;
  text = text.replace(/\r\n/g, "\n");
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '"' && (quoted || !value)) {
      if (quoted && text[i + 1] === '"') { value += '"'; i++; } else quoted = !quoted;
    } else if (!quoted && (c === "\t" || c === "\n")) {
     rows.at(-1).push(value); value = "";
      if (c === "\n") rows.push([]);
    } else value += c;
  }
  if (quoted) throw new Error("Pasted text has an unclosed quote.");
 rows.at(-1).push(value);
  if (rows.length > 1 && rows.at(-1).length === 1 && rows.at(-1)[0] === "") rows.pop();
  if (rows.length > 200 || rows.some((r) => r.length > 100)) throw new Error("Paste up to 200 rows and 100 columns at a time.");
  return rows;
}

// Send field-backed cells and ordinary cells together so the server can validate
// the entire paste before applying either kind of change.
export function tableEditPayload(parsed, startRow, startCol, grid) {
  if (startRow < 0 || startRow > parsed.rows.length || startCol < 0 || grid.some((r) => startCol + r.length > parsed.headers.length)) throw new Error("The paste exceeds the column count. Add columns first.");
  const row_edits = [], new_rows = [];
  grid.forEach((cells, offset) => {
    const old = parsed.rows[startRow + offset];
    if (old) row_edits.push({ row_id: old.rid, cells: Object.fromEntries(cells.map((value, i) => [String(startCol + i), value])) });
    else {
      const row = parsed.headers.map(() => "");
      cells.forEach((value, i) => { row[startCol + i] = value; }); new_rows.push(row);
    }
  });
  return { table_id: parsed.tableId, row_edits, new_rows };
}

export function tableCSV(parsed) {
  const escape = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
  const formula = (value) => {
    if (!String(value).startsWith("=") || parsed.table?.attrs?.worksheet_name) return value;
    const refs = /(?<![\w.])(?:(?:'(?:[^']|'')+'|(?:\[[^\]]+\])?[A-Z_][\w.]*)!)?\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?(?![\w.])/gi;
    return String(value).split(/("(?:[^"]|"")*")/g).map((part, i) => i % 2 ? part : part.replace(refs, (token, offset) => {
      if (token.includes("!") || /^\s*\(/.test(part.slice(offset + token.length))) return token;
      return token.replace(/(\$?[A-Z]{1,3}\$?)(\d+)/gi, (_, col, row) => col + (Number(row) + 1));
    })).join("");
  };
  return "\uFEFF" + [parsed.headers, ...parsed.rows.map((row) => row.cells.map((c) => formula(c.value)))].map((row) => row.map(escape).join(",")).join("\r\n");
}

export function mediaOf(value, type) {
  const text = String(value || "");
  const match = text.match(/(?:!\[[^\]]*\]|\[(image|video|audio)\])\(([^)]+)\)/);
  const url = match ? match[2] : text;
  if (!/^(https?:\/\/|\/projects\/api\/)/i.test(url)) return null;
  let kind = match?.[1] || (text.startsWith("![") ? "image" : type);
  if (!["image", "video", "audio"].includes(kind)) {
    kind = /\.(mp4|webm)(\?|$)/i.test(url) ? "video" : /\.(mp3|wav|ogg|flac|m4a)(\?|$)/i.test(url) ? "audio" : /\.(png|jpe?g|gif|webp)(\?|$)/i.test(url) ? "image" : null;
  }
  if (!kind && /^\/projects\/api\/[a-z0-9-]+\/assets\/pa_[a-f0-9]{32}$/.test(url)) kind = "asset";
  return kind ? { kind, url } : null;
}

export function evaluate(value, rows, seen = new Set(), offset = 0) {
  if (!String(value).startsWith("=")) return value;
  try {
    let expr = String(value).slice(1).toUpperCase();
    const cell = (letters, row) => {
      let c = 0; for (const x of letters) c = c * 26 + x.charCodeAt(0) - 64;
      const key = `${letters}${row}`;
      if (seen.has(key)) throw new Error("Circular reference");
      const raw = rows[Number(row) - 1 - offset]?.cells[c - 1]?.value ?? "0";
      const result = evaluate(raw, rows, new Set([...seen, key]), offset);
      const n = Number(String(result).replaceAll(",", ""));
      if (!Number.isFinite(n)) throw new Error("Cannot calculate");
      return n;
    };
    expr = expr.replace(/(SUM|AVG|AVERAGE)\(([A-Z]+)(\d+):([A-Z]+)(\d+)\)/g, (_, fn, c1, r1, c2, r2) => {
      if (c1 !== c2 || Math.abs(+r2 - +r1) > 10000) throw new Error("Unsupported range");
      let sum = 0; for (let r = Math.min(+r1, +r2); r <= Math.max(+r1, +r2); r++) sum += cell(c1, r);
      return String(fn === "SUM" ? sum : sum / (Math.abs(+r2 - +r1) + 1));
    });
    expr = expr.replace(/\$?([A-Z]+)\$?(\d+)/g, (_, c, r) => String(cell(c, r)));
    const tokens = expr.match(/\d*\.\d+|\d+\.?\d*|[()+\-*/]/g) || [];
    if (tokens.join("") !== expr.replace(/\s/g, "")) return value;
    let i = 0;
    const atom = () => {
      if (tokens[i] === "+") { i++; return atom(); }
      if (tokens[i] === "-") { i++; return -atom(); }
      if (tokens[i] === "(") { i++; const n = sum(); if (tokens[i++] !== ")") throw new Error(); return n; }
      const token = tokens[i++]; if (!/^\d*\.?\d+$/.test(token || "")) throw new Error(); return Number(token);
    };
    const product = () => { let n = atom(); while (["*", "/"].includes(tokens[i])) { const op = tokens[i++], r = atom(); n = op === "*" ? n * r : n / r; } return n; };
    const sum = () => { let n = product(); while (["+", "-"].includes(tokens[i])) { const op = tokens[i++], r = product(); n = op === "+" ? n + r : n - r; } return n; };
    const n = sum(); if (i !== tokens.length || !Number.isFinite(n)) throw new Error();
    return String(Math.round(n * 1e6) / 1e6);
  } catch { return "#ERROR"; }
}
