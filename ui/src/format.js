export const STATUSES = ["未開始", "進行中", "生圖中", "生影片中", "等待審核", "重抽", "等待回覆", "卡住", "已完成"];
export const STATUS_CLASS = {
  未開始: "notstarted", 進行中: "inprogress", 等待回覆: "waiting", 卡住: "stuck", 已完成: "done",
};
export const ROLE_LABEL = { admin: "管理者", director: "總監", marketing_lead: "行銷主管", marketer: "行銷" };

const PALETTE = [
  ["#e9e2d4", "#5b4a2c"], ["#dbeafe", "#1e40af"], ["#fce7f3", "#9d174d"], ["#dcfce7", "#166534"],
  ["#ede9fe", "#5b21b6"], ["#ffedd5", "#9a3412"], ["#e0f2fe", "#075985"], ["#fef9c3", "#854d0e"],
];

const PARTS = new Intl.DateTimeFormat("en-US", {
  timeZone: "Asia/Taipei", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});

export function shortTime(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const p = Object.fromEntries(PARTS.formatToParts(date).map((part) => [part.type, part.value]));
  return `${p.month}/${p.day} ${p.hour}:${p.minute}`;
}

export function avatarColors(id) {
  let hash = 0;
  for (const ch of String(id || "")) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  const [bg, fg] = PALETTE[hash % PALETTE.length];
  return { bg, fg };
}

export function initial(name) {
  const text = String(name || "?").trim();
  return text ? Array.from(text)[0].toUpperCase() : "?";
}

export function statusClass(label) {
  return STATUS_CLASS[label] || "notstarted";
}

// 對話裡欄位變更那一行
export function activityLine(item) {
  const who = item.actor ? item.actor.name : "";
  const f = item.field || {};
  if (item.kind === "status") return `${who} 把「${f.label || "狀態"}」從「${f.old}」改成「${f.new}」`;
  if (item.kind === "fill") return f.new ? `${who} 填了「${f.label}」：${f.new}` : `${who} 清空了「${f.label}」`;
  if (item.kind === "check") return f.new === "true" ? `${who} 勾選了「${f.label}」` : `${who} 取消勾選「${f.label}」`;
  return "";
}
