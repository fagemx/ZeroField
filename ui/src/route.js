// 網址：/projects/<專案>/#<分頁>~<對話錨點>
const SLUG = /^\/projects\/([a-z0-9][a-z0-9-]{0,40})\/?$/;
const KEY = /^[a-z0-9][a-z0-9-]{0,40}$/;
const ANCHOR = /^[A-Za-z0-9_-]{1,40}$/;

export function parseLocation(pathname, hash) {
  const match = SLUG.exec(pathname || "");
  const raw = String(hash || "").replace(/^#/, "");
  const [tab, thread] = raw.split("~");
  return {
    slug: match ? match[1] : null,
    tab: KEY.test(tab || "") ? tab : null,
    thread: ANCHOR.test(thread || "") ? thread : null,
  };
}

export function tabHash(tab, thread) {
  return "#" + tab + (thread ? "~" + thread : "");
}

export function internalTab(href) {
  const raw = String(href || "");
  return raw.startsWith("#") && KEY.test(raw.slice(1)) ? raw.slice(1) : null;
}
