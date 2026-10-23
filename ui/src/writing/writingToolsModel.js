// Tools never own source documents or calculate replacement offsets. All writes use frozen handles.
export function actionId() {
  return globalThis.crypto?.randomUUID?.() || `writing-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function toolsErrorKey(error) {
  const code = error?.code || error?.data?.code;
  if (error?.status === 401 || error?.status === 403) return 'auth';
  if (code === 'DRAMA_WRITING_PREVIEW_STALE') return 'stale';
  if (code === 'DRAMA_WRITING_LOCKED' || code === 'DRAMA_OPERATION_NOT_ALLOWED') return 'locked';
  if (code === 'DRAMA_WRITING_CONFLICT' || error?.status === 409) return 'conflict';
  if (error?.status === 413) return 'limit';
  if (error?.status === 422) return 'invalid';
  if (code === 'WRITING_FLUSH_REQUIRED') return 'flushRequired';
  return 'failed';
}

export function retryable(error) {
  // Never replay automatically. Only an explicit retry of the exact frozen request is offered.
  return !error?.status || error.status >= 500;
}

export function frozenRequest(transport, tail, method = 'GET', body, options = {}) {
  const fixedBody = body === undefined ? undefined : structuredClone(body);
  const fixedOptions = {...options, ...(method === 'POST' ? {idempotencyKey: actionId()} : {})};
  return signal => {
    signal?.throwIfAborted();
    return transport(tail, method, fixedBody, signal ? {...fixedOptions, signal} : fixedOptions);
  };
}

export async function serverFlush(flush) {
  if (typeof flush !== 'function' || await flush({requireServer: true}) !== true) {
    const error = new Error('Server save required');
    error.code = 'WRITING_FLUSH_REQUIRED';
    throw error;
  }
}

export function previewUsable(preview, now = Date.now()) {
  return Boolean(preview?.previewId && preview.status === 'pending' && !preview.stale &&
    Number.isFinite(expiryTime(preview.expiresAt)) && expiryTime(preview.expiresAt) > now);
}

export function expiryTime(value) {
  return typeof value === 'number' ? value * 1000 : Date.parse(value);
}

export function expiryLabel(value) {
  const time = expiryTime(value);
  return Number.isFinite(time) ? new Date(time).toLocaleString() : '—';
}

export function resourceOptions(workspace, currentRef = {kind: 'working'}) {
  const options = [{ref: {kind: 'working'}, key: 'working'},
    ...((workspace?.sources?.items || []).map(source => ({ref: {kind: 'source', mode: source.mode}, key: source.mode === 'idea' ? 'sourceIdea' : 'sourceNovel'}))),
    ...((workspace?.branches?.items || []).map(branch => ({ref: {kind: 'branch', id: branch.branchId}, key: 'branch', name: branch.name}))),
    ...((workspace?.versions?.items || []).map(version => ({ref: {kind: 'version', id: version.versionId}, key: 'version', name: version.name})))];
  if (!options.some(option => JSON.stringify(option.ref) === JSON.stringify(currentRef))) options.unshift({ref: currentRef, key: 'currentResource'});
  return options;
}

export async function readResource(transport, sourceRef, signal) {
  signal?.throwIfAborted();
  if (sourceRef.kind === 'working') return transport('workspace', 'GET', undefined, {signal});
  if (sourceRef.kind === 'source') return transport(`sources/${encodeURIComponent(sourceRef.mode)}`, 'GET', undefined, {signal});
  if (sourceRef.kind === 'branch') return transport(`branches/${encodeURIComponent(sourceRef.id)}`, 'GET', undefined, {signal});
  if (sourceRef.kind === 'version') {
    const version = await transport(`versions/${encodeURIComponent(sourceRef.id)}`, 'GET', undefined, {signal});
    return version.snapshot;
  }
  throw Object.assign(new Error('Invalid resource'), {status: 422});
}

export function safeFilename(name, fallback = 'manuscript.txt') {
  const clean = String(name || '').split(/[\\/]/).pop().replace(/[\u0000-\u001f\u007f]/g, '').trim();
  return clean && clean !== '.' && clean !== '..' ? clean : fallback;
}

export function downloadBlob(blob, filename, documentObject = document, urlObject = URL) {
  const url = urlObject.createObjectURL(blob);
  const anchor = documentObject.createElement('a');
  anchor.href = url;
  anchor.download = safeFilename(filename);
  anchor.rel = 'noopener';
  documentObject.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // Keep the URL alive long enough for the browser to start the download; always release it.
  setTimeout(() => urlObject.revokeObjectURL(url), 1000);
}

// Defense in depth: authenticated server print HTML is escaped server-side; this view also
// drops all active elements, URL attributes and user styles. No dangerouslySetInnerHTML in React.
export function cleanPrintHtml(html, Parser = DOMParser) {
  const parsed = new Parser().parseFromString(html, 'text/html');
  const allowed = new Set(['MAIN','SECTION','ARTICLE','DIV','P','H1','H2','H3','H4','PRE','STRONG','EM','UL','OL','LI','HR','BR','SPAN','TABLE','THEAD','TBODY','TR','TH','TD']);
  const blocked = new Set(['SCRIPT','STYLE','IFRAME','OBJECT','EMBED','IMG','LINK','META','BASE','FORM','INPUT','BUTTON','SVG','MATH']);
  const escape = text => text.replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  function serialize(node) {
    if (node.nodeType === 3) return escape(node.textContent || '');
    if (node.nodeType !== 1 || blocked.has(node.tagName)) return '';
    const content = Array.from(node.childNodes, serialize).join('');
    if (!allowed.has(node.tagName)) return content;
    const tag = node.tagName.toLowerCase();
    return `<${tag}>${content}</${tag}>`;
  }
  const content = Array.from(parsed.body.childNodes, serialize).join('');
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><style>body{font:12pt/1.6 system-ui,sans-serif;color:#111;background:#fff;margin:18mm}pre{white-space:pre-wrap;font:inherit}section,article{break-before:auto}h1,h2,h3{break-after:avoid}table{border-collapse:collapse}td,th{border:1px solid #777;padding:4pt}@media print{h2{break-before:page}}</style></head><body>${content}</body></html>`;
}
