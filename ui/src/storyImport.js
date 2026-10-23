import { t } from './i18n/index.js';

export const sourceDraft = (script = '') => ({sourceText:'', script, adaptationKey:null});

export function hasSceneHeadings(content) {
  return /^\s*(?:#{1,6}\s*)?(?:Scene\s*\d+\b|(?:場景|场景)\s*[一二三四五六七八九十\d]+|(?:INT|EXT|INT\.?\s*\/\s*EXT)\.)/im.test(content || '');
}

const adaptationKey = (sourceMode, draft, targetScenes) => JSON.stringify([sourceMode, draft.sourceText, targetScenes]);

export function editStoryScreenplay(sourceMode, draft, script, targetScenes = 3) {
  return {...draft, script, adaptationKey:sourceMode === 'script' ? draft.adaptationKey : adaptationKey(sourceMode, draft, targetScenes)};
}

export function needsStoryAdaptation(sourceMode, draft, targetScenes = 3) {
  if (sourceMode === 'script') return false;
  if (draft.sourceText.trim()) return draft.adaptationKey !== adaptationKey(sourceMode, draft, targetScenes) || !hasSceneHeadings(draft.script);
  return !!draft.script.trim() && !hasSceneHeadings(draft.script);
}

export async function adaptStoryDraft({epId, sourceMode, draft, targetScenes = 3, breakdownMode = 'auto', request}) {
  const sourceText = draft.sourceText.trim() ? draft.sourceText : draft.script;
  if (!sourceText.trim()) throw new Error(t('story.sourceRequired'));
  const result = await request(`/episodes/${epId}/script-adaptations`, 'POST', {sourceText, sourceMode, targetScenes, breakdownMode});
  const script = result?.script?.content;
  if (typeof script !== 'string' || !script.trim()) throw new Error(t('story.adaptationEmpty'));
  return {...draft, script, adaptationKey:adaptationKey(sourceMode, draft, targetScenes)};
}

// Save the prepared draft before downstream requests so a retry keeps screenplay edits
// and does not adapt the original source a second time.
export async function buildStoryFromDraft({epId, sourceMode, draft, targetScenes = 3, breakdownMode = 'auto', settings, request, wait, onPrepared, onDone}) {
  await request(`/episodes/${epId}/settings`, 'PUT', {...settings, breakdownMode});
  let prepared = draft;
  if (needsStoryAdaptation(sourceMode, draft, targetScenes)) {
    const source = draft.sourceText.trim() ? draft.sourceText : draft.script;
    prepared = hasSceneHeadings(source)
      ? {...draft, script:source, adaptationKey:adaptationKey(sourceMode, draft, targetScenes)}
      : await adaptStoryDraft({epId, sourceMode, draft, targetScenes, breakdownMode, request});
    onPrepared?.(prepared);
  }
  if (!prepared.script.trim()) throw new Error(t('story.sourceRequired'));
  await request(`/episodes/${epId}/script`, 'PUT', {scriptContent:prepared.script});
  await wait(await request(`/episodes/${epId}/asset-extractions`, 'POST'));
  const result = await wait(await request(`/episodes/${epId}/storyboards`, 'POST', {breakdownMode}));
  await onDone?.(result);
  return result;
}

export function missingAssetSheets(episode) {
  return [...new Set((episode?.missingAssetCodes || []).map(code => String(code).replace(/^@/, '').replace('#', ':').toUpperCase())
    .filter(code => /^(?:CAST|SET|LOC)-/.test(code)))];
}

export function assetGroupActive(group) {
  if (!group?.taskIds?.length) return false;
  if (!group.counts) return true;
  return Number(group.counts.queued || 0) + Number(group.counts.running || 0) > 0;
}

const pendingAssetGroups = new Map();
const groupStorageKey = epId => 'zerofield.asset-generation.' + epId;

export function rememberAssetGroup(epId, group, storage) {
  const active = assetGroupActive(group);
  if (active) pendingAssetGroups.set(epId, group);
  else pendingAssetGroups.delete(epId);
  try {
    const session = storage ?? globalThis.sessionStorage;
    if (active) session?.setItem(groupStorageKey(epId), JSON.stringify({taskGroupId:group.taskGroupId, taskIds:group.taskIds, assetCodes:group.assetCodes}));
    else session?.removeItem(groupStorageKey(epId));
  } catch { /* The in-memory copy still survives closing this dialog. */ }
}

export function restoredAssetGroup(epId, storage) {
  try {
    const group = JSON.parse((storage ?? globalThis.sessionStorage)?.getItem(groupStorageKey(epId)) || 'null');
    if (group && /^tg_[a-z0-9]+$/i.test(group.taskGroupId) && Array.isArray(group.taskIds) && group.taskIds.every(id => typeof id === 'string')) return group;
  } catch { /* Storage can be disabled or contain an older value. */ }
  return pendingAssetGroups.get(epId) || null;
}
