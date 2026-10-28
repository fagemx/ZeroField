import { ApiError } from './api.js';
import { t } from './i18n/index.js';

export const STORY_BASE = '/aivideo/open/v1';
export const episodeId = (slug, index = 1) => `ep_${slug}_${String(index).padStart(2, '0')}`;
export const shotId = (slug, rid) => `sh_${slug}_${rid}`;

export async function storyRequest(path, method = 'GET', body, options = {}) {
  const headers = new Headers(options.headers || {});
  // Fixed by the mounted authoring session, not inferred from ambient cookies.
  if (options.expectedActorId != null) headers.set('X-Writing-Expected-Actor', options.expectedActorId);
  headers.set('Accept', options.responseType === 'json' || !options.responseType ? 'application/json' : '*/*');
  if (method !== 'GET') headers.set('X-Requested-With', 'projects');
  if (!options.raw && method !== 'GET') headers.set('Content-Type', 'application/json');
  if (method === 'POST') headers.set('Idempotency-Key', options.idempotencyKey || headers.get('Idempotency-Key') || crypto.randomUUID());
  let response;
  try {
    response = await fetch(STORY_BASE + path, {method, credentials:'same-origin', headers, signal:options.signal,
      ...(method === 'GET' ? {} : {body:options.raw ? body : JSON.stringify(body ?? {})})});
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new ApiError(0, t('api.connectionLostOrSessionExpiredRefreshThePage'));
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const error = new ApiError(response.status, payload?.message || payload?.error || response.statusText, payload);
    error.code = payload?.code; error.details = payload?.details;
    throw error;
  }
  if (options.responseType === 'blob') return response.blob();
  if (options.responseType === 'text') return response.text();
  const payload = await response.json();
  return payload.data;
}

// A file the story API can attach to an asset or shot: the raw bytes, with its purpose and name in headers (images up to 8 MB).
export const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/gif'];
export const MAX_IMAGE_BYTES = 8 * 1024 * 1024;
export async function storyUpload(file, purpose = 'IMAGE') {
  const response = await fetch(STORY_BASE + '/files', {method:'POST', credentials:'same-origin', body:file,
    headers:{'Content-Type':file.type || 'application/octet-stream', 'X-File-Purpose':purpose, 'X-File-Name':encodeURIComponent(file.name),
      'X-Requested-With':'projects', 'Idempotency-Key':crypto.randomUUID()}});
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.message || payload.error || response.statusText);
  return payload.data;
}

export async function storyList(path) {
  const items = [];
  let cursor;
  do {
    const data = await storyRequest(path + (path.includes('?') ? '&' : '?') + 'limit=100' + (cursor ? '&cursor=' + encodeURIComponent(cursor) : ''));
    items.push(...data.items); cursor = data.nextCursor;
  } while (cursor);
  return items;
}

export async function waitStoryTask(task, {signal, onProgress, request = storyRequest} = {}) {
  while (['QUEUED','RUNNING'].includes(task.status)) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    await new Promise((resolve, reject) => {
      const abort = () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); };
      const timer = setTimeout(() => {signal?.removeEventListener('abort', abort); resolve();}, 800);
      signal?.addEventListener('abort', abort, {once:true});
    });
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    task = await request('/tasks/' + task.taskId, 'GET', undefined, {signal});
    onProgress?.(task);
  }
  if (task.status !== 'SUCCEEDED') throw new Error(task.error?.message || task.status);
  return task.result;
}

export function selectedTake(candidates, id, kind = 'video') {
  return candidates.map(item => ({...item, selected:item[kind + 'Id'] === id}));
}

// Continuity grades arrive newest first; a take shows its latest grade.
export const GRADE_ACTIVE = ['queued', 'waiting_gpu', 'grading'];
export const gradesActive = grades => grades.some(g => GRADE_ACTIVE.includes(g.status));
export const takeGrade = (grades, url) => grades.find(g => g.assetUrl === url) || null;

export function replaceAssetVariant(value, oldId, nextId) {
  const pattern = new RegExp('(@?\\b)' + oldId.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(':','[:#]') + '(?![:#a-z0-9_-])', 'gi');
  return String(value).replace(pattern, (_, prefix) => prefix + nextId);
}

export function sceneKey(parsed, row) {
  const column = parsed.headers.findIndex(label => /^scene(?:\s*id)?$/i.test(label.trim()));
  if (column >= 0 && row.cells[column]?.value) return String(row.cells[column].value);
  return String(row.cells[0]?.value || '').match(/^(SC\d+)(?:[-_ ]|$)/i)?.[1].toUpperCase() || '';
}

export const allocationPath = (slug, ep) => `/projects/pj_${slug}/episodes/${ep}/shots:plan-allocation`;
export const escalationPath = (slug, ep, shot) => `/projects/pj_${slug}/episodes/${ep}/shots/${shot}:escalate`;
export function allocationDispatchBody(allocation, budgetMode, productionPolicy) {
  if (!allocation?.ready || !allocation.allocationId || !allocation.allocations?.length) throw new Error(t('allocation.preflightRequired'));
  return {allocationId:allocation.allocationId,shotIds:allocation.allocations.map(item=>item.shotId),budgetMode,productionPolicy};
}

export function approvedCompositionSource(takes) {
  const video = takes.videos.find(take => take.selected);
  if (video) return {referenceSourceVideoId:video.videoId};
  const image = takes.images.find(take => take.selected);
  return image ? {referenceSourceImageId:image.imageId} : null;
}

const BLOCKER_KEYS = {
  provider_not_configured:'blockerProvider',local_comfy_offline:'blockerLocalOffline',
  local_comfy_availability_unknown:'blockerLocalUnknown',card_unavailable:'blockerCard',selected_card_unavailable:'blockerCard',
  chain_requires_hybrid_paid_permission:'blockerHybrid',strategy_requires_hybrid_paid_permission:'blockerHybrid',
  required_media_missing:'blockerRequiredMedia',media_not_owned:'blockerOwnership',media_missing:'blockerMissingMedia',
  media_size_invalid:'blockerMediaSize',media_type_mismatch:'blockerMediaType',
  missing_preparation_source:'blockerPreparationSource',invalid_preparation_binding:'blockerPreparation',
  invalid_dependencies:'blockerPreparation',invalid_preparation_output:'blockerPreparation',
  invalid_generation_output:'blockerCardInputs',invalid_card_inputs:'blockerCardInputs',
  models_not_installed:'blockerModelsMissing',
};
export function allocationBlockerLabel(blocker) {
  const [code, , ...field] = String(blocker).split(':');
  if (code === 'models_not_installed') return t('allocation.blockerModelsMissing',{files:field.join(':')});
  const key = Object.hasOwn(BLOCKER_KEYS,code) ? BLOCKER_KEYS[code] : 'blockerUnknown';
  const message = t('allocation.'+key);
  return field.length && key !== 'blockerUnknown' ? t('allocation.blockerField',{message,field:field.join(':')}) : message;
}
