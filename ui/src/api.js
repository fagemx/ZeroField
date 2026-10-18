import { t as uiText } from './i18n/index.js';
// 所有寫入都帶 X-Requested-With: projects（伺服器靠它擋跨站請求）。
const WRITE_HEADERS = { "Content-Type": "application/json", "X-Requested-With": "projects" };

export class ApiError extends Error {
  constructor(status, message, data = null) {
    super(message);
    this.status = status;
    this.data = data; // 伺服器回的整份內容（例如改回時「之後又有人改過」的名單）
    Object.defineProperty(this, 'message', {configurable: true, get: () => errorMessage(data, message)});
  }
}

export function errorMessage(data, fallback) {
  return typeof data?.message_key === 'string' && data.message_key.startsWith('errors.')
    ? uiText(data.message_key, {...data.message_params, defaultValue: fallback}) : fallback;
}

async function handle(response) {
  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!response.ok) {
    throw new ApiError(response.status, (data && data.error) || uiText("api.serverResponse", {v0: (response.status)}), data);
  }
  if (data === null) throw new ApiError(0, uiText("api.connectionLostOrSessionExpiredRefreshThePage"));
  return data;
}

async function send(path, init) {
  let response;
  try {
    response = await fetch(path, { credentials: "same-origin", ...init });
  } catch {
    throw new ApiError(0, uiText("api.connectionLostOrSessionExpiredRefreshThePage"));
  }
  return handle(response);
}

export const api = {
  download: async (path, filename) => {
    const response = await fetch(path, { credentials: "same-origin" });
    if (!response.ok) return handle(response);
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url; link.download = filename; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
  get: (path) => send(path, { headers: { Accept: "application/json" } }),
  post: (path, body) => send(path, { method: "POST", headers: WRITE_HEADERS, body: JSON.stringify(body || {}) }),
  upload: (path, file, name) => send(path, {
    method: "POST",
    headers: {
      "Content-Type": file.type || "application/octet-stream", "X-Requested-With": "projects",
      ...(name ? { "X-File-Name": encodeURIComponent(name) } : {}),
    },
    body: file,
  }),
};
