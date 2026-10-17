import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { Schema } from "@tiptap/pm/model";

import { anchorAt, docTextJSON, posToText, resolveAnchor, selectionAnchor, textIndex, textToPos } from "../src/anchoring.js";
import { computeOps, isBlankNew, mergeServer, stable } from "../src/blocks.js";
import { canAddRow, canManageTab, unitEditable, unitsInRange } from "../src/permissions.js";
import { isOpen, panelGroups, todoFor, waitingOn } from "../src/rules.js";

const CASES = JSON.parse(readFileSync(new URL("../../tests/fixtures/project_docs_anchor_cases.json", import.meta.url), "utf8"));
const ADMIN = "c6df6021-49c5-4ea6-a1db-c0aca6795165";
const MEMBER = "59370850-d500-565c-a979-2e4262c155d4";
const REVIEWER = "f1aff351-2051-5e7b-b18d-14d52693c371";

const owned = { bid: { default: null }, owner: { default: null }, created: { default: null } };
const schema = new Schema({
  nodes: {
    doc: { content: "block+" },
    paragraph: { group: "block", content: "inline*", attrs: owned },
    heading: { group: "block", content: "inline*", attrs: { ...owned, level: { default: 1 } } },
    table: { group: "block", content: "tableRow+", attrs: owned },
    tableRow: { content: "(tableCell | tableHeader)+", attrs: owned },
    tableCell: { content: "paragraph+" },
    tableHeader: { content: "paragraph+" },
    status: { group: "inline", inline: true, atom: true, attrs: { fid: { default: null }, label: { default: "未開始" } } },
    hardBreak: { group: "inline", inline: true },
    text: { group: "inline" },
  },
});
const p = (bid, text, owner = null) => schema.nodes.paragraph.create({ bid, owner }, text ? schema.text(text) : null);
const cellP = (text) => schema.nodes.paragraph.create(null, text ? schema.text(text) : null);
const row = (bid, owner, ...cells) => schema.nodes.tableRow.create({ bid, owner }, cells);
const td = (text) => schema.nodes.tableCell.create(null, cellP(text));
const th = (text) => schema.nodes.tableHeader.create(null, cellP(text));
const status = () => schema.nodes.tableCell.create(null, schema.nodes.paragraph.create(null, schema.nodes.status.create()));

test("text matches the server and the shared cases", () => {
  assert.equal(docTextJSON(CASES.doc), CASES.text);
  for (const item of CASES.cases) {
    const got = resolveAnchor(item.text, item.anchor);
    assert.deepEqual(got ? [got.start, got.end, got.exact] : null, item.expect, item.name);
  }
});

test("text index maps both ways and selections become anchors", () => {
  const doc = schema.nodes.doc.create(null, [p("b1", "abc"), p("b2", "de")]);
  const index = textIndex(doc);
  assert.equal(index.text, "abc\nde");
  assert.equal(textToPos(index.segs, 4), 6);
  assert.equal(textToPos(index.segs, 3, true), 4);
  assert.equal(posToText(index.segs, 7), 5);
  const picked = selectionAnchor(doc, 2, 8);
  assert.deepEqual(picked.anchor, anchorAt("abc\nde", 1, "bc\nde"));
  assert.equal(selectionAnchor(doc, 1, 1), null);
});

test("ops only include changed blocks, rows go row by row", () => {
  const server = { type: "doc", content: [
    { type: "paragraph", attrs: { bid: "b1", owner: null, created: null }, content: [{ type: "text", text: "本文" }] },
    { type: "table", attrs: { bid: "t1", owner: null, created: null }, content: [
      { type: "tableRow", attrs: { bid: "r0", owner: null, created: null }, content: [{ type: "tableHeader", content: [{ type: "paragraph" }] }] },
      { type: "tableRow", attrs: { bid: "r1", owner: null, created: null }, content: [{ type: "tableCell", content: [{ type: "paragraph" }] }] }] },
    { type: "paragraph", attrs: { bid: "b9", owner: null, created: null } },
  ] };
  const clean = new Map(server.content.map((n) => [n.attrs.bid, stable(n)]));
  const current = JSON.parse(JSON.stringify(server));
  current.content[1].content.push({ type: "tableRow", attrs: { bid: "r2", owner: MEMBER, created: null },
    content: [{ type: "tableCell", content: [{ type: "paragraph", content: [{ type: "text", text: "新列" }] }] }] });
  current.content.splice(1, 0, { type: "paragraph", attrs: { bid: "n1", owner: MEMBER, created: null }, content: [{ type: "text", text: "補充" }] });
  current.content.splice(2, 0, { type: "paragraph", attrs: { bid: "n2", owner: MEMBER, created: null } });
  const ops = computeOps({ server, clean, current });
  assert.deepEqual(ops.map((op) => [op.op, op.bid || op.rid, op.after]), [["put", "n1", "b1"], ["put_row", "r2", "r1"]]);
  assert.equal(ops[1].base, null);
  assert.ok(isBlankNew(current.content[2]));
  const removed = JSON.parse(JSON.stringify(server));
  removed.content.splice(0, 1);
  assert.deepEqual(computeOps({ server, clean, current: removed }).map((op) => op.op), ["del"]);
  // 10/15 起大家一起編輯：誰搬了段落的順序都會存
  const moved = JSON.parse(JSON.stringify(server));
  moved.content.reverse();
  assert.deepEqual(computeOps({ server, clean, current: moved }).map((op) => op.op), ["order"]);
});

test("merge keeps what I am editing and takes the rest from the server", () => {
  const server = { type: "doc", content: [
    { type: "paragraph", attrs: { bid: "b1" }, content: [{ type: "text", text: "別人改過" }] },
    { type: "paragraph", attrs: { bid: "b2" }, content: [{ type: "text", text: "伺服器" }] },
    { type: "paragraph", attrs: { bid: "b3" }, content: [{ type: "text", text: "別人新增" }] },
  ] };
  const before = [
    { type: "paragraph", attrs: { bid: "b1" }, content: [{ type: "text", text: "原文" }] },
    { type: "paragraph", attrs: { bid: "b2" }, content: [{ type: "text", text: "原文二" }] },
  ];
  const clean = new Map(before.map((n) => [n.attrs.bid, stable(n)]));
  const current = { type: "doc", content: [before[0],
    { type: "paragraph", attrs: { bid: "b2" }, content: [{ type: "text", text: "我正在改" }] },
    { type: "paragraph", attrs: { bid: "n1" }, content: [{ type: "text", text: "我新增的" }] }] };
  const { doc, kept } = mergeServer({ server, clean, current });
  assert.deepEqual(doc.content.map((n) => n.content[0].text), ["別人改過", "我正在改", "我新增的", "別人新增"]);
  assert.deepEqual([...kept].sort(), ["b2", "n1"]);
  const forced = mergeServer({ server, clean, current, force: new Set(["b2"]) });
  assert.equal(forced.doc.content[1].content[0].text, "伺服器");
  // 自己刪掉、還沒存的 b1：伺服器還有，也不放回來
  const removed = { type: "doc", content: current.content.slice(1) };
  const merged = mergeServer({ server, clean, current: removed });
  assert.deepEqual(merged.doc.content.map((n) => n.attrs.bid), ["b2", "n1", "b3"]);
  assert.deepEqual([...merged.deleted], ["b1"]);
});

test("everyone edits every block and row unless someone else holds the lock", () => {
  const table = schema.nodes.table.create({ bid: "t1" }, [row("r0", null, th("項目"), th("狀態")),
    row("r1", null, td("Meta 權杖"), status()), row("r2", MEMBER, td("我的列"), status())]);
  const doc = schema.nodes.doc.create(null, [p("b1", "本文"), p("b2", "我的", MEMBER), table]);
  const me = { me: MEMBER, admin: false, locks: new Map() };
  const units = (from, to) => unitsInRange(doc, from, to).map((u) => [u.kind, u.node.attrs.bid, unitEditable(u, me)]);
  assert.deepEqual(units(2, 2), [["block", "b1", true]]);
  assert.deepEqual(units(7, 8), [["block", "b2", true]]);
  const tablePos = doc.child(0).nodeSize + doc.child(1).nodeSize;
  const r2 = tablePos + 1 + table.child(0).nodeSize + table.child(1).nodeSize;
  assert.deepEqual(units(r2 + 4, r2 + 4), [["row", "r2", true]]);
  assert.deepEqual(units(tablePos + 4, tablePos + 4), [["row", "r0", true]]);
  assert.ok(canAddRow(table, me));
  const locked = { ...me, locks: new Map([["b2", "Sam"]]) };
  assert.equal(unitEditable(unitsInRange(doc, 7, 8)[0], locked), false);
  assert.equal(unitEditable(unitsInRange(doc, 2, 2)[0], { me: ADMIN, admin: true, locks: new Map() }), true);
  const tableLocked = { ...me, locks: new Map([["t1", "Sam"]]) };
  assert.equal(unitEditable(unitsInRange(doc, r2 + 4, r2 + 4)[0], tableLocked), false);
});

test("todo rules", () => {
  const msg = (who, body, mentions = []) => ({ kind: "comment", actor: { actor_id: who }, body, mentions, at: "2026-10-13T08:00:00Z" });
  const asked = { kind: "text", label: "q", created_by: REVIEWER, messages: [msg(REVIEWER, "?", [MEMBER])] };
  assert.ok(todoFor(asked, MEMBER, false));
  assert.ok(!todoFor(asked, ADMIN, true));
  const answered = { ...asked, messages: [...asked.messages, msg(MEMBER, "答")] };
  assert.ok(!todoFor(answered, MEMBER, false));
  const unaddressed = { kind: "text", label: "fix", created_by: REVIEWER, messages: [] };
  assert.ok(todoFor(unaddressed, ADMIN, true));
  assert.ok(!todoFor(unaddressed, MEMBER, false));
  const reconfirm = { kind: "text", label: "ok", label_by: MEMBER, created_by: MEMBER, reconfirm: { from: "a", to: "b" }, messages: [] };
  assert.ok(todoFor(reconfirm, MEMBER, false));
  const mark = { kind: "text", style: "hl", created_by: ADMIN, messages: [] };
  assert.ok(!isOpen(mark));
  assert.deepEqual(waitingOn(asked, [{ actor_id: MEMBER, name: "Mia", role: "marketer" }]), ["Mia"]);
  const groups = panelGroups([asked, unaddressed, mark, { ...asked, resolved_at: "x" }, { ...asked, orphaned_at: "y" }], MEMBER, false, false);
  // 原文改了、但 @ 的人還沒回：仍然算他的待辦（跟樣稿一樣）
  assert.deepEqual([groups.todo.length, groups.open.length, groups.orphan.length, groups.done.length], [2, 2, 1, 1]);
});

test("page menu: managers manage every page, members only the pages they added", () => {
  const admin = { actor_id: ADMIN, can_edit: true };
  const member = { actor_id: MEMBER, can_edit: false };
  const theirs = { key: "t-1", created_by: MEMBER };
  const kais = { key: "overview", created_by: ADMIN };
  assert.equal(canManageTab(kais, admin), true);
  assert.equal(canManageTab(theirs, admin), true);
  assert.equal(canManageTab(theirs, member), true);
  assert.equal(canManageTab(kais, member), false);
  assert.equal(canManageTab({ key: "old", created_by: null }, member), false);
});
