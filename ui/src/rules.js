// 標註的規則：誰該處理、誰能解決、清單怎麼分組、內文上用什麼樣子。跟伺服器 service.py 的權限一致。

export const LABELS = {
  q: { name: "Question", cls: "lb-q", open: true, hint: "Ask a question. It stays open until someone resolves it." },
  fix: { name: "Revise", cls: "lb-fix", open: true, hint: "Request a correction or rewrite. It stays open until resolved." },
  ok: { name: "Approved", cls: "lb-ok", open: false, hint: "Approve this passage. Changes to its text will require approval again." },
};
export const COLORS = { y: ["Yellow", "#ffd400"], g: ["Green", "#46c864"], b: ["Blue", "#5096ff"], p: ["Pink", "#ff64a0"] };

export const comments = (a) => (a.messages || []).filter((m) => m.kind === "comment");

export function mentionsOf(a) {
  const out = new Set();
  for (const m of comments(a)) for (const id of m.mentions || []) out.add(id);
  return out;
}

export function lastAuthor(a) {
  const list = comments(a);
  return list.length ? list[list.length - 1].actor.actor_id : a.created_by;
}

export const isMarkOnly = (a) => a.kind === "text" && !a.label && comments(a).length === 0;
export const isRecordOnly = (a) => a.kind === "text" && a.label === "ok" && !a.reconfirm && comments(a).length === 0;

export function isOpen(a) {
  if (a.resolved_at) return false;
  if (a.reconfirm) return true;
  if (a.label === "q" || a.label === "fix") return true;
  return comments(a).length > 0;
}

// 待我處理：@ 我還沒回、我確認過的字被改了、標了問題／要修改又沒 @ 人（交給管理者）
export function todoFor(a, me, isAdmin) {
  if (!isOpen(a)) return false;
  if (a.reconfirm) return a.label_by === me;
  const mentions = mentionsOf(a);
  if (mentions.size) return mentions.has(me) && lastAuthor(a) !== me;
  if (a.label === "q" || a.label === "fix") return Boolean(isAdmin) && lastAuthor(a) !== me;
  return false;
}

export function waitingOn(a, members) {
  return (members || []).filter((m) => todoFor(a, m.actor_id, m.role === "admin")).map((m) => m.name);
}

export const canResolve = (a, me, isAdmin) => Boolean(isAdmin) || a.created_by === me || mentionsOf(a).has(me);
export const canDelete = (a, me, isAdmin) => Boolean(isAdmin) || a.created_by === me;

export function latestAt(a) {
  let latest = a.created_at || "";
  for (const m of a.messages || []) if ((m.at || "") > latest) latest = m.at;
  return latest;
}

// 右上清單：待我處理；全部分成未解決／原文已修改／已解決。只算有標籤或有對話的（螢光筆、劃線不算）
export function panelGroups(list, me, isAdmin, mineOnly) {
  const shown = list
    .filter((a) => a.label || comments(a).length || a.kind === "row" && (a.messages || []).length)
    .filter((a) => !mineOnly || a.created_by === me)
    .sort((x, y) => (latestAt(y) > latestAt(x) ? 1 : -1));
  return {
    todo: shown.filter((a) => todoFor(a, me, isAdmin)),
    open: shown.filter((a) => isOpen(a) && !a.orphaned_at),
    orphan: shown.filter((a) => a.orphaned_at && !a.resolved_at),
    done: shown.filter((a) => a.resolved_at),
  };
}

export function chipFor(a) {
  if (a.reconfirm) return { cls: "re", text: "Approval required again" };
  if (a.label) return { cls: LABELS[a.label].cls, text: LABELS[a.label].name };
  if (a.kind === "row") return { cls: "row", text: "Whole Row" };
  return { cls: "nt", text: "Add Note" };
}

// 內文上這一則畫成什麼樣子
export function markClass(a, focused) {
  let cls = "pd-ann";
  if (a.draft) cls += " pd-draft";
  else if (a.resolved_at) cls += " pd-resolved";
  else if (a.reconfirm) cls += " pd-re";
  else if (a.label) cls += " pd-" + a.label;
  else if (a.style === "ul") cls += " pd-ul" + (comments(a).length ? " pd-has" : "");
  else if (a.style === "hl") cls += " pd-hl-" + (a.color || "y") + (comments(a).length ? " pd-has" : "");
  else cls += " pd-note";
  if (focused) cls += " pd-focus";
  return cls;
}
