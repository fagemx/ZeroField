// 標註怎麼找回原文：記住選到的字＋前後文，內文改了再找回來。
// 跟伺服器 project_docs/anchoring.py、doc_schema.doc_text 同一套規則（tests/fixtures/project_docs_anchor_cases.json 對照）。
export const CONTEXT = 32;
export const MAX_QUOTE = 300;
const TEXTBLOCKS = new Set(["paragraph", "heading"]);

// 文件 JSON → 文字：區塊之間一個換行；hardBreak 是換行；狀態、可填格這類小元件不算字
export function docTextJSON(doc) {
  let text = "";
  let first = true;
  const walk = (node) => {
    if (!node || typeof node !== "object") return;
    if (TEXTBLOCKS.has(node.type)) {
      if (!first) text += "\n";
      first = false;
      for (const child of node.content || []) {
        if (child.type === "text") text += child.text || "";
        else if (child.type === "hardBreak") text += "\n";
      }
      return;
    }
    (node.content || []).forEach(walk);
  };
  walk(doc);
  return text;
}

// ProseMirror 文件 → 文字＋每段文字在文件裡的位置（t：文字位置、p：文件位置、n：長度）
export function textIndex(doc) {
  let text = "";
  let first = true;
  const segs = [];
  doc.descendants((node, pos) => {
    if (!node.isTextblock) return true;
    if (!TEXTBLOCKS.has(node.type.name)) return false;
    if (!first) text += "\n";
    first = false;
    node.forEach((child, offset) => {
      if (child.isText) {
        segs.push({ t: text.length, p: pos + 1 + offset, n: child.text.length });
        text += child.text;
      } else if (child.type.name === "hardBreak") {
        text += "\n";
      }
    });
    return false;
  });
  return { text, segs };
}

// 文字位置 → 文件位置。落在段落交界時：開頭往後找下一段、結尾往前找上一段
export function textToPos(segs, offset, isEnd = false) {
  if (isEnd) {
    for (const s of segs) if (offset > s.t && offset <= s.t + s.n) return s.p + (offset - s.t);
    for (let i = segs.length - 1; i >= 0; i -= 1) if (segs[i].t + segs[i].n <= offset) return segs[i].p + segs[i].n;
  } else {
    for (const s of segs) if (offset >= s.t && offset < s.t + s.n) return s.p + (offset - s.t);
    for (const s of segs) if (s.t >= offset) return s.p;
  }
  return null;
}

// 文件位置 → 文字位置（不在字裡就算前一段的結尾）
export function posToText(segs, pos) {
  let last = 0;
  for (const s of segs) {
    if (pos < s.p) return last;
    if (pos <= s.p + s.n) return s.t + (pos - s.p);
    last = s.t + s.n;
  }
  return last;
}

export function anchorAt(text, start, quote) {
  const end = start + quote.length;
  return { quote, start, prefix: text.slice(Math.max(0, start - CONTEXT), start), suffix: text.slice(end, end + CONTEXT) };
}

function score(text, index, anchor) {
  const prefix = anchor.prefix || "";
  const suffix = anchor.suffix || "";
  let total = 0;
  for (let k = 1; k <= prefix.length && index - k >= 0; k += 1) {
    if (text[index - k] !== prefix[prefix.length - k]) break;
    total += 1;
  }
  const end = index + anchor.quote.length;
  for (let k = 0; k < suffix.length && end + k < text.length; k += 1) {
    if (text[end + k] !== suffix[k]) break;
    total += 1;
  }
  return total;
}

export function resolveAnchor(text, anchor) {
  const quote = (anchor && anchor.quote) || "";
  if (!quote) return null;
  const old = anchor.start || 0;
  let best = -1;
  let bestScore = -1;
  let bestDistance = Infinity;
  for (let i = text.indexOf(quote); i !== -1; i = text.indexOf(quote, i + 1)) {
    const s = score(text, i, anchor);
    const d = Math.abs(i - old);
    if (s > bestScore || (s === bestScore && d < bestDistance)) {
      best = i;
      bestScore = s;
      bestDistance = d;
    }
  }
  if (best >= 0) return { start: best, end: best + quote.length, exact: true };
  const prefix = (anchor.prefix || "").slice(-10);
  const suffix = (anchor.suffix || "").slice(0, 10);
  if (prefix.length >= 4 && suffix.length >= 4) {
    for (let i = text.indexOf(prefix); i !== -1; i = text.indexOf(prefix, i + 1)) {
      const begin = i + prefix.length;
      const end = text.indexOf(suffix, begin);
      if (end > begin && end <= begin + quote.length * 2 + 12) return { start: begin, end, exact: false };
    }
  }
  return null;
}

// 選取 → 錨點（去掉頭尾空白）；太長回 {tooLong: true}；沒選到字回 null
export function selectionAnchor(doc, from, to) {
  const index = textIndex(doc);
  let start = posToText(index.segs, from);
  const end = posToText(index.segs, to);
  if (end <= start) return null;
  let quote = index.text.slice(start, end);
  start += quote.length - quote.replace(/^\s+/, "").length;
  quote = quote.trim();
  if (!quote) return null;
  if (quote.length > MAX_QUOTE) return { tooLong: true };
  return { anchor: anchorAt(index.text, start, quote) };
}

// 錨點 → 文件位置
export function anchorRange(index, anchor) {
  const found = resolveAnchor(index.text, anchor);
  if (!found) return null;
  const from = textToPos(index.segs, found.start);
  const to = textToPos(index.segs, found.end, true);
  if (from === null || to === null || to <= from) return null;
  return { from, to, exact: found.exact };
}
