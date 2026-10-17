import assert from "node:assert/strict";
import test from "node:test";

import {
  appliedLabel, assistRows, blocks, currentFocus, documentUrl, draftPrompt, inlineParts, lookedAt, openReply, progressCounts,
  sourceTarget,
  liveText, splitSources, taskLine, waitingCount, workingLine,
  attachmentHint, clampWidth, elapsedSeconds, formatSeconds, guessKind, isPicked, orphanPending, pickTodo, DEFAULT_HINT,
  paneTab, paneTabs, proposalCopy,
} from "../src/assistant/text.js";

const TABS = [{ key: "questions", title: "待確認問題" }, { key: "reports", title: "現行報表研究" }];

test("sources are split off and bare cell refs merge into the previous one", () => {
  const { main, sources } = splitSources("先確認 35%。\n出處：自操廣告 ROAS〈整體廣告_iOS〉J4、P4；待確認問題〈請行銷回答〉");
  assert.equal(main, "先確認 35%。");
  assert.deepEqual(sources, ["自操廣告 ROAS〈整體廣告_iOS〉J4、P4", "待確認問題〈請行銷回答〉"]);
  assert.deepEqual(splitSources("沒有出處").sources, []);
  assert.deepEqual(sourceTarget("待確認問題〈請行銷回答〉", TABS), { key: "questions", heading: "請行銷回答" });
  assert.equal(sourceTarget("自操廣告 ROAS〈整體廣告_iOS〉J4", TABS), null);
});

test("inline formatting is parsed, never injected", () => {
  assert.deepEqual(inlineParts("**先做第 1 題**，看 `J4`，金額 ▢ 元"), [
    { kind: "strong", text: "先做第 1 題" }, { kind: "text", text: "，看 " }, { kind: "code", text: "J4" },
    { kind: "text", text: "，金額 " }, { kind: "mask", text: "▢" }, { kind: "text", text: " 元" },
  ]);
  assert.deepEqual(inlineParts("<img src=x onerror=alert(1)>"), [{ kind: "text", text: "<img src=x onerror=alert(1)>" }]);
  assert.deepEqual(blocks("一\n- a\n- b\n1. c\n\n二"), [
    { kind: "p", text: "一" }, { kind: "ul", items: ["a", "b"] }, { kind: "ol", items: ["c"] }, { kind: "p", text: "二" },
  ]);
});

test("working line says what it is looking at", () => {
  const tools = [{ label: "待辦", detail: "" }, { label: "專案頁", detail: "questions" }, { label: "待辦", detail: "" }];
  assert.deepEqual(lookedAt(tools), ["待辦", "專案頁 questions"]);
  assert.equal(workingLine({ status: "running", tools }), "正在看：待辦、專案頁 questions");
  assert.equal(workingLine({ status: "running", tools: [] }), "正在想…");
  assert.equal(workingLine({ status: "queued", attempts: 0, tools: [] }), "排隊中…");
  assert.equal(workingLine({ status: "queued", attempts: 1, tools: [] }), "重新試一次…");
  assert.equal(workingLine({ status: "running", tools, body: "第 2 題要" }), "正在寫…");
  const thread = [{ role: "user", body: "我們來回答第 8 題" }, { role: "assistant", status: "running", tools: [] }];
  assert.equal(openReply(thread).status, "running");
  assert.equal(openReply([{ role: "assistant", status: "done" }]), null);
  assert.deepEqual(currentFocus(thread, null), { kind: "question", number: 8 });
  assert.deepEqual(currentFocus(thread, { kind: "handoff", rid: "r1", text: "x" }), { kind: "handoff", rid: "r1", text: "x" });
});

test("todo counts, row prompts and the task strip", () => {
  const todo = [
    { kind: "note", id: 1, text: "這週先回答第 1、2 題" },
    { kind: "question", rid: "q2", number: 2, text: "範圍？", status: "未開始" },
    { kind: "question", rid: "q1", number: 1, text: "花多久？", status: "已完成" },
    { kind: "handoff", rid: "h1", text: "AppsFlyer 事件名稱", status: "未開始" },
  ];
  assert.deepEqual(progressCounts(todo), { questionsDone: 1, questions: 2, handoffDone: 0, handoff: 1 });
  assert.equal(draftPrompt(todo[1]), "我們來回答第 2 題");
  assert.equal(draftPrompt(todo[3]), "我們來做交接追蹤的「AppsFlyer 事件名稱」");
  const rows = assistRows(todo);
  assert.deepEqual(rows.get("q1"), { label: "一起回答", cell: 1, prompt: "我們來回答第 1 題" });
  assert.equal(rows.get(todo[3].rid).label, "這一項怎麼交");
  assert.equal(rows.get(todo[3].rid).cell, 0);
  assert.equal(rows.has("1"), false);
  assert.equal(taskLine({ proposals: [{ status: "pending" }], thread: [] }, null), "答案整理好了，等你確認");
  assert.equal(taskLine({ proposals: [], thread: [{ role: "user", body: "第 2 題" }] }, null), "正在處理：第 2 題");
  assert.equal(taskLine({ proposals: [], thread: [] }, null), "");
});

test("download link only on a finished answer that offered the document", () => {
  const offered = { id: 42, role: "assistant", status: "done", tools: [{ tool: "offer_document", ok: true }] };
  assert.equal(documentUrl("ad-data", offered), "/projects/api/ad-data/assistant/messages/42/document");
  assert.equal(documentUrl("ad-data", { ...offered, status: "running" }), null);
  assert.equal(documentUrl("ad-data", { ...offered, role: "user" }), null);
  assert.equal(documentUrl("ad-data", { ...offered, tools: [{ tool: "offer_document", ok: false }] }), null);
  assert.equal(documentUrl("ad-data", { ...offered, tools: [{ tool: "read_page", ok: true }] }), null);
  assert.equal(documentUrl("ad-data", null), null);
});

test("a private forward is never described as put on the page", () => {
  assert.equal(appliedLabel({ action: "私下轉給負責人" }), "已私下轉給負責人");
  assert.equal(appliedLabel({ action: "寫進那一題的討論" }), "已放上專案頁");
});

test("the top-bar count is notes plus answers waiting for confirmation", () => {
  assert.equal(waitingCount(null), 0);
  assert.equal(waitingCount({ todo: [], proposals: [] }), 0);
  assert.equal(waitingCount({
    todo: [{ kind: "note", id: 1 }, { kind: "question", rid: "q1" }],
    proposals: [{ status: "pending" }, { status: "applied" }],
  }), 2);
});

test("live text: what the assistant has written so far, only while it is writing", () => {
  assert.equal(liveText({ role: "assistant", status: "running", body: "第 2 題要" }), "第 2 題要");
  assert.equal(liveText({ role: "assistant", status: "running", body: "" }), "");
  assert.equal(liveText({ role: "assistant", status: "queued", body: "" }), "");
  assert.equal(liveText({ role: "assistant", status: "done", body: "完整答案" }), "");
  assert.equal(liveText(null), "");
});

test("a picked todo item can be unpicked, and the auto-filled line goes with it", () => {
  const q2 = { kind: "question", number: 2, rid: "r2" };
  const thread = [{ id: 5, role: "user", body: "嗨" }, { id: 6, role: "assistant", body: "嗨" }];
  const picked = pickTodo(null, q2, "", thread);
  assert.deepEqual(picked, { focus: { kind: "question", number: 2 }, draft: "我們來回答第 2 題" });
  assert.equal(isPicked(picked.focus, q2), true);
  const unpicked = pickTodo(picked.focus, q2, "我們來回答第 2 題", thread);
  assert.deepEqual(unpicked, { focus: { kind: "none", after: 5 }, draft: "" });
  assert.equal(pickTodo(picked.focus, q2, "我們來回答第 2 題，先從產品開始", thread).draft, "我們來回答第 2 題，先從產品開始");
  // 取消之後，就算上一句提到第幾題也不自動選；她再送一句才照那一句判斷
  const asked = [{ id: 5, role: "user", body: "我們來回答第 2 題" }];
  assert.equal(currentFocus(asked, { kind: "none", after: 5 }), null);
  assert.deepEqual(currentFocus([...asked, { id: 9, role: "user", body: "第 3 題呢" }], { kind: "none", after: 5 }),
    { kind: "question", number: 3 });
});

test("how long an answer took: from her question to the finished answer", () => {
  const thread = [{ id: 1, role: "user", created_at: "2026-10-14T08:00:00+00:00" }];
  const reply = { id: 2, role: "assistant", status: "done", reply_to: 1, finished_at: "2026-10-14T08:00:07.400+00:00", seconds: 4.2 };
  assert.equal(elapsedSeconds(reply, thread), 7);
  assert.equal(elapsedSeconds({ ...reply, reply_to: 99 }, thread), 4);  // 找不到那一句就用 worker 記的秒數
  assert.equal(elapsedSeconds({ ...reply, status: "failed" }, thread), null);
  assert.deepEqual([formatSeconds(9), formatSeconds(65), formatSeconds(120), formatSeconds(null)], ["9 秒", "1 分 5 秒", "2 分鐘", ""]);
});

test("attachment hint, kinds, side panel width and answers left in older conversations", () => {
  assert.equal(attachmentHint([]), DEFAULT_HINT);
  assert.match(attachmentHint([{ kind: "sheet" }, { kind: "image" }]), /圖片會交給助理/);
  assert.match(attachmentHint([{ kind: "doc" }]), /數字、文字與公式/);
  assert.match(attachmentHint([{ kind: "image" }], "mask_numbers"), /圖片不會傳給助理/);
  assert.deepEqual(["a.PNG", "報表.xlsx", "說明.docx", "規格.pdf", "n.csv"].map((name) => guessKind({ name, type: "" })),
    ["image", "sheet", "doc", "doc", "text"]);
  assert.equal(guessKind({ name: "image.png", type: "image/png" }), "image");
  assert.deepEqual([clampWidth(100, 1440), clampWidth(560, 1440), clampWidth(2000, 1440), clampWidth(700, 900), clampWidth("x", 1440)],
    [320, 560, 720, 540, 400]);
  const thread = [{ id: 10 }, { id: 11 }];
  const proposals = [{ id: 1, status: "pending", message_id: 3 }, { id: 2, status: "pending", message_id: 11 },
    { id: 3, status: "applied", message_id: 3 }];
  assert.deepEqual(orphanPending(proposals, thread).map((p) => p.id), [1]);
});

test("a private question to the lead never reads like it goes on the page", () => {
  const forward = proposalCopy({ action: "私下轉給負責人" });
  assert.equal(forward.ask, "要私下問負責人嗎？");
  assert.equal(forward.confirm, "確認轉給負責人");
  assert.match(forward.note, /只有負責人看得到/);
  assert.match(forward.compactTail, /不會放上專案頁/);
  assert.doesNotMatch(JSON.stringify(forward), /放上去|放到專案頁/);
  const page = proposalCopy({ action: "寫進那一題的討論" });
  assert.deepEqual([page.ask, page.confirm, page.dismissed], ["要放到專案頁嗎？", "確認放上去", "先不放"]);
  const table = proposalCopy({action: "table_edit"});
  assert.equal(table.confirm, "確認寫回");
  assert.match(table.note, /資料已變更/);
  assert.doesNotMatch(JSON.stringify(table), /table_edit/);
});

test("the lead's count includes private questions waiting for a reply", () => {
  const state = { todo: [{ kind: "note" }], proposals: [{ status: "pending" }], forwards_open: 2 };
  assert.equal(waitingCount(state), 4);
  assert.equal(waitingCount({ todo: [], proposals: [] }), 0);
});

test("side panel tabs: 對話、紀錄, and 管理 only for managers, carrying the waiting count", () => {
  assert.deepEqual(paneTabs(false, 3).map((t) => t.key), ["chat", "history"]);
  const kai = paneTabs(true, 2);
  assert.deepEqual(kai.map((t) => t.label), ["對話", "紀錄", "管理"]);
  assert.equal(kai[2].count, 2);
  assert.equal(paneTabs(true, 0)[2].count, 0);
  assert.equal(paneTabs(true, undefined)[2].count, 0);
  assert.equal(paneTab("manage", true), "manage");
  assert.equal(paneTab("chat", true), "history");
  assert.equal(paneTab("chat", false), "chat");
});
