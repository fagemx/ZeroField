// 專案助理畫面用的純函式：不碰 React、不碰網路。回答一律當純文字處理，只認 **粗體**、`程式碼`、▢ 三種標記。

export function splitSources(text) {
  const value = String(text || "");
  const lines = value.split("\n");
  const index = lines.map((line) => line.trim()).findIndex((line) => /^出處[:：]/.test(line));
  if (index < 0) return { main: value, sources: [] };
  const raw = lines.slice(index).join(" ").replace(/^\s*出處[:：]\s*/, "").split(/[、；;]/).map((s) => s.trim()).filter(Boolean);
  const merged = [];
  for (const item of raw) {
    if (/^[A-Z]{1,3}\d+$/.test(item) && merged.length) merged[merged.length - 1] += "、" + item;
    else merged.push(item);
  }
  return { main: lines.slice(0, index).join("\n").trimEnd(), sources: merged };
}

export function sourceTarget(item, tabs) {
  const match = String(item).match(/^([^〈《(（]+)[〈《(（]?([^〉》)）]*)/);
  const page = match ? match[1].trim() : String(item);
  const heading = match ? (match[2] || "").trim() : "";
  const hit = (tabs || []).find((t) => t.title === page) || (tabs || []).find((t) => page.includes(t.title));
  return hit ? { key: hit.key, heading } : null;
}

export function isReportSource(item) {
  return /報表|ROAS|每日|自操|週執行|廣告成效|roas|daily|weekly/i.test(String(item));
}

export function inlineParts(line) {
  const parts = [];
  const pattern = /\*\*(.+?)\*\*|`([^`]+)`|(▢|〔已遮掉的[^〕]+〕)/g;
  const text = String(line || "");
  let last = 0;
  let match;
  while ((match = pattern.exec(text))) {
    if (match.index > last) parts.push({ kind: "text", text: text.slice(last, match.index) });
    if (match[1] !== undefined) parts.push({ kind: "strong", text: match[1] });
    else if (match[2] !== undefined) parts.push({ kind: "code", text: match[2] });
    else parts.push({ kind: "mask", text: match[3] });
    last = pattern.lastIndex;
  }
  if (last < text.length) parts.push({ kind: "text", text: text.slice(last) });
  return parts;
}

export function blocks(text) {
  const out = [];
  let list = null;
  for (const raw of String(text || "").split("\n")) {
    const line = raw.replace(/\s+$/, "");
    const bullet = line.match(/^\s*[-*] (.*)$/);
    const number = line.match(/^\s*\d+[.)] (.*)$/);
    if (bullet || number) {
      const kind = bullet ? "ul" : "ol";
      if (!list || list.kind !== kind) {
        list = { kind, items: [] };
        out.push(list);
      }
      list.items.push((bullet || number)[1]);
      continue;
    }
    list = null;
    if (line.trim()) out.push({ kind: "p", text: line });
  }
  return out;
}

export function lookedAt(tools) {
  const seen = [];
  for (const tool of tools || []) {
    const label = tool.detail ? `${tool.label} ${tool.detail}` : tool.label;
    if (label && !seen.includes(label)) seen.push(label);
  }
  return seen;
}

export function workingLine(reply) {
  if (!reply) return "";
  if (reply.status === "queued") return reply.attempts > 0 ? "重新試一次…" : "排隊中…";
  if (reply.status === "running" && reply.body) return "正在寫…";
  const looked = lookedAt(reply.tools);
  return looked.length ? "正在看：" + looked.slice(-3).join("、") : "正在想…";
}

// 還在寫的回答：助理邊寫，資料庫那一則就邊存（worker 的 write_partial），畫面先把寫好的部分秀出來。
export function liveText(reply) {
  if (!reply || reply.role !== "assistant" || reply.status !== "running") return "";
  return String(reply.body || "");
}

export function openReply(thread) {
  return [...(thread || [])].reverse()
    .find((m) => m.role === "assistant" && (m.status === "queued" || m.status === "running")) || null;
}

export function questionNumber(text) {
  const match = String(text || "").match(/第\s*(\d{1,2})\s*題/);
  return match ? Number(match[1]) : null;
}

function lastUser(thread) {
  return [...(thread || [])].reverse().find((m) => m.role === "user") || null;
}

export function currentFocus(thread, focus) {
  if (focus && focus.kind === "none") {
    // 取消選取之後，在她送出下一句之前都不自動選（不然上一句提到第幾題又會亮起來）
    const last = lastUser(thread);
    if (!last || last.id <= (focus.after || 0)) return null;
    focus = null;
  }
  if (focus) return focus;
  const last = lastUser(thread);
  const number = last ? questionNumber(last.body) : null;
  return number ? { kind: "question", number } : null;
}

export function isPicked(focus, item) {
  if (!focus || !item) return false;
  if (focus.kind === "question") return item.kind === "question" && item.number === focus.number;
  if (focus.kind === "handoff") return item.kind === "handoff" && item.rid === focus.rid;
  return false;
}

// 待辦：點一題就選起來、輸入框帶入那句；再點同一題就取消，自動帶入、還沒改過的那句也一起拿掉
export function pickTodo(focusNow, item, draft, thread) {
  if (isPicked(focusNow, item)) {
    const last = lastUser(thread);
    return { focus: { kind: "none", after: last ? last.id : 0 }, draft: draft === draftPrompt(item) ? "" : draft };
  }
  const focus = item.kind === "question" ? { kind: "question", number: item.number }
    : { kind: "handoff", rid: item.rid, text: item.text };
  return { focus, draft: draftPrompt(item) };
}

// 這一句花了多久：從她送出到回答寫完（含排隊）；對不上就用 worker 自己記的秒數
export function elapsedSeconds(reply, thread) {
  if (!reply || reply.role !== "assistant" || reply.status !== "done") return null;
  const asked = (thread || []).find((m) => m.id === reply.reply_to);
  const start = asked ? Date.parse(asked.created_at) : NaN;
  const end = reply.finished_at ? Date.parse(reply.finished_at) : NaN;
  if (Number.isFinite(start) && Number.isFinite(end) && end >= start) return Math.max(1, Math.round((end - start) / 1000));
  return reply.seconds != null ? Math.max(1, Math.round(Number(reply.seconds))) : null;
}

export function formatSeconds(seconds) {
  if (seconds == null) return "";
  if (seconds < 60) return `${seconds} 秒`;
  const minutes = Math.floor(seconds / 60);
  return seconds % 60 ? `${minutes} 分 ${seconds % 60} 秒` : `${minutes} 分鐘`;
}

export const DEFAULT_HINT = "此專案允許助理讀取數字與公式。請勿輸入權杖或金鑰。";

export function attachmentHint(files, privacyMode = "full_access") {
  const kinds = new Set((files || []).map((f) => f.kind));
  if (privacyMode === "mask_numbers") return "此專案已開啟數值遮罩；敏感數值會先遮掉，圖片不會傳給助理。";
  if (kinds.has("image")) return "圖片會交給助理；附件數字與公式依此專案設定完整提供。請勿上傳金鑰。";
  if (kinds.size) return "附件中的數字、文字與公式會提供給助理，供分析與編輯提案使用。";
  return DEFAULT_HINT;
}

export const ACCEPT_FILES = "image/png,image/jpeg,image/gif,image/webp,.xlsx,.xlsm,.docx,.pdf,.txt,.csv,.tsv,.md,.json,.log";

export function guessKind(file) {
  const name = String((file && file.name) || "").toLowerCase();
  if (String((file && file.type) || "").startsWith("image/") || /\.(png|jpe?g|gif|webp)$/.test(name)) return "image";
  if (/\.(xlsx|xlsm)$/.test(name)) return "sheet";
  if (/\.(docx|pdf)$/.test(name)) return "doc";
  return "text";
}

export function fileIcon(kind) {
  return kind === "sheet" ? "📊" : kind === "image" ? "🖼" : "📄";
}

// 側邊欄可以拖拉調寬：至少 320、最多 720，也要留至少 360 給專案頁
export const PA_WIDTH = { min: 320, max: 720, fallback: 400 };

export function clampWidth(px, viewport) {
  const value = Number(px);
  if (!Number.isFinite(value)) return PA_WIDTH.fallback;
  const max = Math.max(PA_WIDTH.min, Math.min(PA_WIDTH.max, (viewport || 1280) - 360));
  return Math.round(Math.min(max, Math.max(PA_WIDTH.min, value)));
}

// 開了新對話以後，之前那段還沒確認的答案：放在目前這段最上面
export function orphanPending(proposals, thread) {
  const ids = new Set((thread || []).map((m) => m.id));
  return (proposals || []).filter((p) => p.status === "pending" && !ids.has(p.message_id));
}

export function todoGroups(todo) {
  const items = todo || [];
  return {
    notes: items.filter((i) => i.kind === "note"),
    questions: items.filter((i) => i.kind === "question").sort((a, b) => a.number - b.number),
    handoff: items.filter((i) => i.kind === "handoff"),
    mentions: items.filter((i) => i.kind === "mention"),
  };
}

export function progressCounts(todo) {
  const { questions, handoff } = todoGroups(todo);
  const done = (list) => list.filter((i) => i.status === "已完成").length;
  return { questionsDone: done(questions), questions: questions.length, handoffDone: done(handoff), handoff: handoff.length };
}

export function draftPrompt(item) {
  if (item.kind === "question") return `我們來回答第 ${item.number} 題`;
  if (item.kind === "handoff") return `我們來做交接追蹤的「${item.text}」`;
  return "";
}

// 專案頁那一列文字後面的「✦ …」：題目放在問題那一格（第 2 格），交接追蹤放在項目那一格（第 1 格）。
export function assistRows(todo) {
  const rows = new Map();
  for (const item of todo || []) {
    if (!item.rid) continue;
    if (item.kind === "question") rows.set(item.rid, { label: "一起回答", cell: 1, prompt: draftPrompt(item) });
    if (item.kind === "handoff") rows.set(item.rid, { label: "這一項怎麼交", cell: 0, prompt: draftPrompt(item) });
  }
  return rows;
}

export function taskLine(state, focus) {
  const pending = ((state && state.proposals) || []).filter((p) => p.status === "pending");
  if (pending.length) return pending.length > 1 ? `有 ${pending.length} 個答案等你確認` : "答案整理好了，等你確認";
  const current = currentFocus(state && state.thread, focus);
  if (current && current.kind === "question") return `正在處理：第 ${current.number} 題`;
  if (current && current.kind === "handoff") return `正在處理：${current.text}`;
  return "";
}

export function clip(text, n) {
  const value = String(text || "");
  return value.length > n ? value.slice(0, n) + "…" : value;
}

// 助理在這則回答用過 offer_document（而且成功）才有下載連結；畫面上沒有其他下載入口。
export function documentUrl(slug, message) {
  if (!message || message.role !== "assistant" || message.status !== "done") return null;
  const offered = (message.tools || []).some((t) => t && t.tool === "offer_document" && t.ok);
  return offered ? `/projects/api/${slug}/assistant/messages/${message.id}/document` : null;
}

// 確認後的說法：私下轉給負責人不會出現在專案頁，不能說「已放上專案頁」。
export function appliedLabel(proposal) {
  return proposal && proposal.action === "私下轉給負責人" ? "已私下轉給負責人" : "已放上專案頁";
}

// 卡片上的說法：私下轉給負責人只有負責人看得到、不會放上專案頁，整張卡都不能出現「放上去」
export function proposalCopy(proposal) {
  if (proposal?.action === "table_edit") {
    return {
      ask: "確認這些表格修改？", confirm: "確認寫回", field: "修改內容",
      note: "確認後才會更新表格；若資料已變更，會請你重新核對。",
      dismissed: "未套用", failed: "未能寫回",
      compactLead: "修改提案已整理好：", compactTail: "請到工作台核對內容，再確認寫回。",
    };
  }
  if (proposal && proposal.action === "私下轉給負責人") {
    return {
      ask: "要私下問負責人嗎？", confirm: "確認轉給負責人", field: "要問負責人的話",
      note: "只有負責人看得到，不會放上專案頁；可以先改字再確認",
      dismissed: "先不轉", failed: "沒轉出去",
      compactLead: "要私下問負責人的話整理好了：", compactTail: "在工作台確認後才會送給負責人，不會放上專案頁。",
    };
  }
  return {
    ask: "要放到專案頁嗎？", confirm: "確認放上去", field: "要放上去的內容", note: "可以先改字再確認",
    dismissed: "先不放", failed: "沒放上去",
    compactLead: "答案整理好了：", compactTail: "在工作台確認後就會放上專案頁。",
  };
}

// 側邊欄的分頁（10/15 跟「標註」清單同一套）：對話、紀錄（以前的對話）、管理（只有管理者）。
// 私下問題等負責人回覆的數字掛在「管理」上，不另外佔一條。
export function paneTabs(manager, forwardsOpen) {
  const tabs = [{ key: "chat", label: "對話" }, { key: "history", label: "紀錄" }];
  if (manager) tabs.push({ key: "manage", label: "管理", count: forwardsOpen > 0 ? forwardsOpen : 0 });
  return tabs;
}

export function paneTab(view, history) {
  if (view === "manage") return "manage";
  return history ? "history" : "chat";
}

// 頂列「✦ 專案助理」旁的數字：有事在等這個人（負責人交代的、等他確認的答案；負責人另外加上等他回覆的私下問題）
export function waitingCount(state) {
  if (!state) return 0;
  const notes = (state.todo || []).filter((item) => item.kind === "note").length;
  const pending = (state.proposals || []).filter((p) => p.status === "pending").length;
  return notes + pending + (state.forwards_open || 0);
}
