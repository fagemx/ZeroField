export const STATUSES = ["Queued", "In Progress", "Rendering Image", "Rendering Video", "Pending Review", "Retake", "Blocked", "Approved"];
export const LEGACY_STATUSES = {"未開始":"Queued", "進行中":"In Progress", "生圖中":"Rendering Image", "生影片中":"Rendering Video", "等待審核":"Pending Review", "重抽":"Retake", "等待回覆":"Pending Review", "卡住":"Blocked", "已完成":"Approved"};
export const STATUS_CLASS = {"Queued":"notstarted", "In Progress":"inprogress", "Rendering Image":"inprogress", "Rendering Video":"inprogress", "Pending Review":"waiting", "Retake":"stuck", "Blocked":"stuck", "Approved":"done"};
export const ROLE_LABEL = {admin:"Showrunner", director:"Director", marketing_lead:"Cinematographer", marketer:"Crew", art_lead:"Cinematographer", writer:"Screenwriter", engineer:"VFX TD", member:"Crew", viewer:"Client / Viewer"};
export const ACTION_LABEL = {"寫進那一題的討論":"Add to Discussion", "改狀態":"Change Status", "填交接追蹤":"Update Delivery", "留言問負責人":"Ask Owner", "在段落加標註":"Annotate Passage", "私下轉給負責人":"Forward Privately to Owner", table_edit:"Edit Table"};
export function statusLabel(value) { return LEGACY_STATUSES[value] || value; }

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
  return STATUS_CLASS[statusLabel(label)] || "notstarted";
}

// 對話裡欄位變更那一行
export function activityLine(item) {
  const who = item.actor ? item.actor.name : "";
  const f = item.field || {};
  if (item.kind === "status") return `${who} changed ${f.label === "狀態" ? "Status" : f.label || "Status"} from ${statusLabel(f.old)} to ${statusLabel(f.new)}`;
  if (item.kind === "fill") return f.new ? `${who} filled ${f.label}: ${f.new}` : `${who} cleared ${f.label}`;
  if (item.kind === "check") return f.new === "true" ? `${who} checked ${f.label}` : `${who} unchecked ${f.label}`;
  return "";
}
