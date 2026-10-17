// 留言本文裡的 @ 存成 @{actor_id}；顯示時換成名字。名字以名單為準，不以打出來的字為準。
const TOKEN = /@\{([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\}/g;

export function splitMentions(body) {
  const parts = [];
  let last = 0;
  const text = String(body || "");
  for (const match of text.matchAll(TOKEN)) {
    if (match.index > last) parts.push({ type: "text", text: text.slice(last, match.index) });
    parts.push({ type: "mention", id: match[1] });
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push({ type: "text", text: text.slice(last) });
  return parts;
}

// parts：[{text}] 或 [{mention: actor_id}]，由留言框的內容轉來
export function serializeParts(parts) {
  let body = "";
  const mentions = [];
  for (const part of parts) {
    if (part.mention) {
      body += "@{" + part.mention + "}";
      if (!mentions.includes(part.mention)) mentions.push(part.mention);
    } else {
      body += part.text || "";
    }
  }
  body = body.replace(/ /g, " ").replace(/[ \t]+\n/g, "\n").trim();
  return { body, mentions };
}

// 名稱前綴符合的成員排在前面。
export function filterMembers(members, query) {
  const q = String(query || "").trim().toLowerCase();
  if (!q) return members.slice();
  const starts = (m) => m.name.toLowerCase().startsWith(q) || String(m.email || "").toLowerCase().startsWith(q);
  const first = members.filter(starts);
  const rest = members.filter((m) => !starts(m) && m.name.toLowerCase().includes(q));
  return [...first, ...rest];
}

// 留言框目前游標前面有沒有正在打的 @xxx
export function mentionQuery(textBeforeCaret) {
  const match = /(^|[\s(（])@([^\s@]{0,20})$/.exec(String(textBeforeCaret || ""));
  return match ? match[2] : null;
}
