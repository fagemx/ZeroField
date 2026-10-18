import { t as uiText } from '../i18n/index.js';
// 專案助理畫面用的純函式：不碰 React、不碰網路。回答一律當純文字處理，只認 **粗體**、`程式碼`、▢ 三種標記。

export function splitSources(text) {
  const value = String(text || "");
  const lines = value.split("\n");
  const index = lines.map((line) => line.trim()).findIndex((line) => /^(?:Sources|出處)[:：]/i.test(line));
  if (index < 0) return { main: value, sources: [] };
  const raw = lines.slice(index).join(" ").replace(/^\s*(?:Sources|出處)[:：]\s*/i, "").split(/[、；;]/).map((s) => s.trim()).filter(Boolean);
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
  if (reply.status === "queued") return reply.attempts > 0 ? uiText("text.retrying") : uiText("text.queued");
  if (reply.status === "running" && reply.body) return uiText("text.writing");
  const looked = lookedAt(reply.tools);
  return looked.length ? uiText("text.reading") + looked.slice(-3).join(", ") : uiText("text.thinking");
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
  const match = String(text || "").match(/(?:question\s+(\d{1,2})\b|第\s*(\d{1,2})\s*題)/i);
  return match ? Number(match[1] || match[2]) : null;
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
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  return seconds % 60 ? `${minutes} m ${seconds % 60} s` : uiText("text.minutes", {v0: (minutes)});
}

export const DEFAULT_HINT = "The assistant can read numbers and formulas. Keep credentials out of production content.";

export function attachmentHint(files, privacyMode = "full_access") {
  const kinds = new Set((files || []).map((f) => f.kind));
  if (privacyMode === "mask_numbers") return uiText("text.numericMaskingIsEnabledSensitiveValuesAreMaskedAnd");
  if (kinds.has("image")) return uiText("text.imagesNumbersAndFormulasAreSharedAccordingToProduction");
  if (kinds.size) return uiText("text.attachmentTextNumbersAndFormulasAreAvailableForAnalysis");
  return uiText("text.theAssistantCanReadNumbersAndFormulasKeepCredentials");
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
  const done = (list) => list.filter((i) => ["Approved", "已完成"].includes(i.status)).length;
  return { questionsDone: done(questions), questions: questions.length, handoffDone: done(handoff), handoff: handoff.length };
}

export function draftPrompt(item) {
  if (item.kind === "question") return uiText("text.letSWorkOnQuestion", {v0: (item.number)});
  if (item.kind === "handoff") return uiText("text.letSWorkOnTheDeliverable", {v0: (item.text)});
  return "";
}

// 專案頁那一列文字後面的「✦ …」：題目放在問題那一格（第 2 格），交接追蹤放在項目那一格（第 1 格）。
export function assistRows(todo) {
  const rows = new Map();
  for (const item of todo || []) {
    if (!item.rid) continue;
    if (item.kind === "question") rows.set(item.rid, { label: uiText("text.workTogether"), cell: 1, prompt: draftPrompt(item) });
    if (item.kind === "handoff") rows.set(item.rid, { label: uiText("text.planThisDelivery"), cell: 0, prompt: draftPrompt(item) });
  }
  return rows;
}

export function taskLine(state, focus) {
  const pending = ((state && state.proposals) || []).filter((p) => p.status === "pending");
  if (pending.length) return pending.length > 1 ? uiText("text.thereAreResponsesAwaitingApproval", {v0: (pending.length)}) : uiText("text.responseReadyForApproval");
  const current = currentFocus(state && state.thread, focus);
  if (current && current.kind === "question") return uiText("text.workingOnQuestion", {v0: (current.number)});
  if (current && current.kind === "handoff") return uiText("text.workingOn", {v0: (current.text)});
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
  return proposal && proposal.action === "私下轉給負責人" ? uiText("text.forwardedPrivatelyToOwner") : uiText("text.appliedToProduction");
}

// 卡片上的說法：私下轉給負責人只有負責人看得到、不會放上專案頁，整張卡都不能出現「放上去」
export function proposalCopy(proposal) {
  if (proposal?.action === "table_edit") {
    return {
      ask: uiText("text.applyTheseTableChanges"), confirm: uiText("text.applyChanges"), field: uiText("text.changeDetails"),
      note: uiText("text.theTableUpdatesAfterApprovalChangedSourceDataWill"),
      dismissed: uiText("text.notApplied"), failed: uiText("text.couldNotApply"),
      compactLead: uiText("text.proposalReady"), compactTail: uiText("text.reviewTheProposalInTheWorkbenchThenApplyIt"),
    };
  }
  if (proposal && proposal.action === "私下轉給負責人") {
    return {
      ask: uiText("text.sendAPrivateQuestionToTheOwner"), confirm: uiText("text.sendToOwner"), field: uiText("text.questionForTheOwner"),
      note: uiText("text.onlyTheOwnerCanSeeThisEditTheText"),
      dismissed: uiText("text.doNotForward"), failed: uiText("text.notForwarded"),
      compactLead: uiText("text.privateQuestionReady"), compactTail: uiText("text.approveInTheWorkbenchToSendPrivatelyToThe"),
    };
  }
  return {
    ask: uiText("text.applyThisToTheProductionPage"), confirm: uiText("text.applyToPage"), field: uiText("text.contentToApply"), note: uiText("text.editTheTextBeforeApproving"),
    dismissed: uiText("text.notNow"), failed: uiText("text.notApplied"),
    compactLead: uiText("text.responseReady"), compactTail: uiText("text.approveInTheWorkbenchToApplyItToThe"),
  };
}

// 側邊欄的分頁（10/15 跟「標註」清單同一套）：對話、紀錄（以前的對話）、管理（只有管理者）。
// 私下問題等負責人回覆的數字掛在「管理」上，不另外佔一條。
export function paneTabs(manager, forwardsOpen) {
  const tabs = [{ key: "chat", label: uiText("text.chat") }, { key: "history", label: uiText("text.history") }];
  if (manager) tabs.push({ key: "manage", label: uiText("text.manage"), count: forwardsOpen > 0 ? forwardsOpen : 0 });
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
