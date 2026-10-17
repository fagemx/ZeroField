import assert from "node:assert/strict";
import test from "node:test";

import { anchorsOf, fillColumns, isHeaderRow, rowLabel } from "../src/docText.js";
import { activityLine, avatarColors, shortTime } from "../src/format.js";
import { filterMembers, mentionQuery, serializeParts, splitMentions } from "../src/mentions.js";
import { menuPosition } from "../src/menuPosition.js";
import { internalTab, parseLocation, tabHash } from "../src/route.js";

const ADMIN = "c6df6021-49c5-4ea6-a1db-c0aca6795165";
const MEMBER = "59370850-d500-565c-a979-2e4262c155d4";

test("location parsing keeps only valid keys", () => {
  assert.deepEqual(parseLocation("/projects/ad-data/", "#handoff~brow01"), { slug: "ad-data", tab: "handoff", thread: "brow01" });
  assert.deepEqual(parseLocation("/projects/", ""), { slug: null, tab: null, thread: null });
  assert.equal(parseLocation("/projects/ad-data/", "#Bad Key").tab, null);
  assert.equal(tabHash("meta"), "#meta");
  assert.equal(tabHash("meta", "b1"), "#meta~b1");
  assert.equal(internalTab("#google"), "google");
  assert.equal(internalTab("https://x"), null);
});

test("mentions serialize to actor ids and back", () => {
  const { body, mentions } = serializeParts([{ text: "放好了 " }, { mention: ADMIN }, { text: " 請確認 " }, { mention: ADMIN }]);
  assert.equal(body, `放好了 @{${ADMIN}} 請確認 @{${ADMIN}}`);
  assert.deepEqual(mentions, [ADMIN]);
  assert.deepEqual(splitMentions(body).map((p) => p.type), ["text", "mention", "text", "mention"]);
  assert.equal(splitMentions("@{not-an-id}")[0].type, "text");
});

test("mention picker query and filter", () => {
  assert.equal(mentionQuery("請 @佳"), "佳");
  assert.equal(mentionQuery("email@x"), null);
  assert.equal(mentionQuery("@"), "");
  const members = [{ name: "Alex", email: "alex" }, { name: "Mia", email: "mia.chen" }, { name: "Sam", email: "sam.lee" }];
  assert.deepEqual(filterMembers(members, "mi").map((m) => m.name), ["Mia"]);
  assert.deepEqual(filterMembers(members, "mia").map((m) => m.name), ["Mia"]);
  assert.equal(filterMembers(members, "").length, 3);
  assert.deepEqual(filterMembers(members, "al").map((m) => m.name), ["Alex"]);
});

const cell = (type, ...content) => ({ type, content: [{ type: "paragraph", content }] });
const text = (value) => ({ type: "text", text: value });

test("row labels, header rows and fill columns", () => {
  const header = { type: "tableRow", content: [cell("tableHeader", text("#")), cell("tableHeader", text("問題"))] };
  const row = { type: "tableRow", attrs: { bid: "bq1" }, content: [cell("tableCell", text("1")), cell("tableCell", text("每天花多久？"))] };
  assert.equal(rowLabel(row), "1. 每天花多久？");
  assert.ok(isHeaderRow(header));
  assert.ok(!isHeaderRow(row));
  const table = { type: "table", content: [header, { type: "tableRow", content: [cell("tableCell", text("a")), cell("tableCell", { type: "fill", attrs: { fid: "f1" } })] }] };
  assert.deepEqual([...fillColumns(table)], [1]);
  const doc = { type: "doc", content: [{ type: "heading", attrs: { level: 2, bid: "bh" }, content: [text("段")] }, { type: "table", content: [header, row] }] };
  assert.deepEqual(anchorsOf(doc), { bh: "段", bq1: "1. 每天花多久？" });
});

test("time is shown in Taipei time", () => {
  assert.equal(shortTime("2026-10-14T02:12:00+00:00"), "10/14 10:12");
  assert.equal(shortTime(null), "");
});

test("activity lines name the person", () => {
  assert.equal(activityLine({ kind: "status", actor: { name: "Mia" }, field: { label: "狀態", old: "未開始", new: "等待回覆" } }),
    "Mia 把「狀態」從「未開始」改成「等待回覆」");
  assert.equal(activityLine({ kind: "fill", actor: { name: "Sam" }, field: { label: "負責人", new: "" } }), "Sam 清空了「負責人」");
  assert.equal(activityLine({ kind: "check", actor: { name: "Alex" }, field: { label: "寄出", new: "true" } }), "Alex 勾選了「寄出」");
});

test("avatar colors are stable per person", () => {
  assert.deepEqual(avatarColors(MEMBER), avatarColors(MEMBER));
});

test("menus open below the button, flip above when the bottom has no room, else stick to the bottom", () => {
  const view = { width: 1400, height: 800 };
  const button = { left: 230, top: 470, bottom: 494 };
  assert.deepEqual(menuPosition(button, 280, 200, view), { top: 500, left: 230 });
  // 10/15 負責人：最下面那一頁點「⋯」，選單超出頁面
  assert.deepEqual(menuPosition({ left: 230, top: 700, bottom: 724 }, 280, 330, view), { top: 364, left: 230 });
  assert.deepEqual(menuPosition({ left: 230, top: 200, bottom: 224 }, 280, 700, view), { top: 92, left: 230 });
  assert.equal(menuPosition({ left: 1300, top: 10, bottom: 34 }, 280, 100, view).left, 1112);
  assert.equal(menuPosition(null, 280, 100, view), undefined);
});
