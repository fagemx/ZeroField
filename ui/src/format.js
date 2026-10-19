import { t as uiText } from './i18n/index.js';
import { t, currentLocale } from './i18n/index.js';

export const STATUSES = ["Queued", "In Progress", "Rendering Image", "Rendering Video", "Pending Review", "Retake", "Blocked", "Approved"];
export const LEGACY_STATUSES = {"未開始":"Queued", "進行中":"In Progress", "生圖中":"Rendering Image", "生影片中":"Rendering Video", "等待審核":"Pending Review", "重抽":"Retake", "等待回覆":"Pending Review", "卡住":"Blocked", "已完成":"Approved"};
export const STATUS_CLASS = {"Queued":"notstarted", "In Progress":"inprogress", "Rendering Image":"inprogress", "Rendering Video":"inprogress", "Pending Review":"waiting", "Retake":"stuck", "Blocked":"stuck", "Approved":"done"};
export const ROLE_LABEL = {get admin() { return uiText("format.showrunner"); }, get director() { return uiText("format.director"); }, get marketing_lead() { return uiText("format.cinematographer"); }, get marketer() { return uiText("format.crew"); }, get art_lead() { return uiText("format.cinematographer"); }, get writer() { return uiText("format.screenwriter"); }, get engineer() { return uiText("format.vFXTD"); }, get member() { return uiText("format.crew"); }, get viewer() { return uiText("format.clientViewer"); }};
export const ACTION_LABEL = {get "寫進那一題的討論"() { return uiText("format.addToDiscussion"); }, get "改狀態"() { return uiText("format.changeStatus"); }, get "填交接追蹤"() { return uiText("format.updateDelivery"); }, get "留言問負責人"() { return uiText("format.askOwner"); }, get "在段落加標註"() { return uiText("format.annotatePassage"); }, get "私下轉給負責人"() { return uiText("format.forwardPrivatelyToOwner"); }, get table_edit() { return uiText("format.editTable"); }};
export function normalizeStatus(value) { return Object.hasOwn(LEGACY_STATUSES, value) ? LEGACY_STATUSES[value] : value; }
export function roleLabel(role, fallback = '') { return Object.hasOwn(ROLE_LABEL, role) ? ROLE_LABEL[role] : fallback; }
export function agentLabel(agent) {
  const defaults = {coordinator: ['Showrunner', 'format.showrunner'], doc_writer: ['Screenwriter', 'format.screenwriter'], sheet_ops: ['Cinematographer', 'format.cinematographer'], qa_critic: ['Continuity Supervisor', 'format.continuitySupervisor']};
  const entry = defaults[agent?.agent_key];
  return entry && agent.display_name === entry[0] ? t(entry[1]) : agent?.display_name || '';
}
const STATUS_KEYS = {"Queued":"queued", "In Progress":"inProgress", "Rendering Image":"renderingImage", "Rendering Video":"renderingVideo", "Pending Review":"pendingReview", "Retake":"retake", "Blocked":"blocked", "Approved":"approved"};
const CONSOLE_STATUSES = new Set(['queued','running','awaiting_gate','succeeded','failed','canceled','expired','active','resolved','open']);
export function statusLabel(value) { const normalized = normalizeStatus(value); return Object.hasOwn(STATUS_KEYS, normalized) ? t('status.' + STATUS_KEYS[normalized]) : CONSOLE_STATUSES.has(normalized) ? t('consoleStatus.' + normalized) : value; }

const PALETTE = [
  ["#e9e2d4", "#5b4a2c"], ["#dbeafe", "#1e40af"], ["#fce7f3", "#9d174d"], ["#dcfce7", "#166534"],
  ["#ede9fe", "#5b21b6"], ["#ffedd5", "#9a3412"], ["#e0f2fe", "#075985"], ["#fef9c3", "#854d0e"],
];

const DATE_OPTIONS = {
  timeZone: "Asia/Taipei", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
};

export function shortTime(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const parts = new Intl.DateTimeFormat(currentLocale(), DATE_OPTIONS).formatToParts(date);
  const p = Object.fromEntries(parts.map(part => [part.type, part.value]));
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
  const value = normalizeStatus(label);
  return Object.hasOwn(STATUS_CLASS, value) ? STATUS_CLASS[value] : "notstarted";
}

// 對話裡欄位變更那一行
export function activityLine(item) {
  const who = item.actor ? item.actor.name : "";
  const f = item.field || {};
  if (item.kind === "status") return t('format.activityStatus', {who, field: f.label === "狀態" ? t('format.status') : f.label || t('format.status'), old: statusLabel(f.old), new: statusLabel(f.new)});
  if (item.kind === "fill") return f.new ? t('format.activityFilled', {who, field: f.label, value: f.new}) : t('format.activityCleared', {who, field: f.label});
  if (item.kind === "check") return t(f.new === "true" ? 'format.activityChecked' : 'format.activityUnchecked', {who, field: f.label});
  return "";
}
