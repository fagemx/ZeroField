// SPEC_21 §4: the asset-first editor. An asset is its text and its pictures, and each picture does one job: a character's face gives the
// identity, the front (shot from the shoulders down, no head) the clothes, the back the rest; a set's plate gives the space, its reverse and
// angle are edited from the plate; a prop's product shot gives its shape. The locks are the text constants pasted into every prompt that uses
// the asset. This file only decides: which panels a type has, why one cannot be made yet, what a stress test tallies, and the requests the
// editor sends (SPEC_21 §2.2). It reads nothing and writes nothing.
import { activeTasks, clampCount, isActiveRun, runRefused, runStarted, settleRun } from './generation/generationModel.js';
import { baseCode } from './worldModel.js';

export const PANELS = Object.freeze({CHARACTER: ['face', 'front', 'back', 'sheet'], SCENE: ['plate', 'reverse', 'angle'], PROP: ['product']});
// The sheet is put together by the server once face, front and back are chosen (§2.4); nobody generates it.
export const MADE_PANELS = Object.freeze(['sheet']);
// What has to be chosen before a panel can be made (§2.3: front is drawn from the face, back from face and front; reverse and angle are
// edits of the plate).
export const NEEDS = Object.freeze({front: ['face'], back: ['face', 'front'], reverse: ['plate'], angle: ['plate']});
export const LOCKS = Object.freeze({CHARACTER: ['acting'], SCENE: ['geo', 'light'], PROP: ['lock']});
export const META_FIELDS = Object.freeze(['acting', 'geo', 'light', 'lock', 'change']);
export const META_MAX = 4000;
export const STRESS_MIN = 4, STRESS_MAX = 10, STRESS_DEFAULT = 8, STRESS_WITH_MAX = 5;  // the server takes at most five co-stars
// The editor's own views beside the panels: every picture of the asset (SPEC_18's column, uploads included) and the stress test.
export const ALL = 'all', STRESS = 'stress';

export const panelsOf = type => PANELS[type] || [];
export const isMadePanel = panel => MADE_PANELS.includes(panel);
export const typeOfCode = code => /^CAST/i.test(code) ? 'CHARACTER' : /^PROP/i.test(code) ? 'PROP' : 'SCENE';  // as the server reads a code
export const isVariant = subject => subject?.isDefault === false || String(subject?.assetCode || '').includes(':');

// The panels the server knows for an asset: {face: {url, imageId} | null, ...}, or null while that is not known (the record is still loading,
// or the server is older than SPEC_21). Only a panel with a picture counts as chosen.
export const knownPanels = record => record && record.panels && typeof record.panels === 'object' && !Array.isArray(record.panels) ? record.panels : null;
export const chosenPanel = (panels, panel) => panels?.[panel]?.url ? panels[panel] : null;
export const hasPicture = (panels, mainUrl) => Boolean(mainUrl) || Object.values(panels || {}).some(value => value?.url);

// Why a panel cannot be made now, or null when it can.
//   {reason: 'made'}                     the sheet: the server puts it together
//   {reason: 'needs', missing: [panel]}  the panels to choose first, in the order they are made
//   {reason: 'base', panel}              a look is edited from its base's same panel (or its main picture), and the base has neither
export function panelBlock({type, panel, panels = null, base = null}) {
  if (isMadePanel(panel)) return {reason: 'made'};
  if (!panelsOf(type).includes(panel)) return {reason: 'needs', missing: []};
  if (base) return chosenPanel(knownPanels(base), panel) || base.selectedImageUrl ? null : {reason: 'base', panel};
  const missing = (NEEDS[panel] || []).filter(need => !chosenPanel(panels, need));
  return missing.length ? {reason: 'needs', missing} : null;
}

// The rail beside the picture: each panel of the type with what is chosen for it and why it is blocked. The sheet is listed only once the
// server has made it; until then `sheetPending` says it is still to come.
export function panelStrip({type, panels = null, base = null}) {
  const list = panelsOf(type).filter(panel => !isMadePanel(panel) || chosenPanel(panels, panel)).map(panel => ({
    panel, chosen: chosenPanel(panels, panel), made: isMadePanel(panel), block: panelBlock({type, panel, panels, base})}));
  return {list, sheetPending: panelsOf(type).includes('sheet') && !chosenPanel(panels, 'sheet')};
}

// Where the editor opens: the next panel to make, or the asset's own pictures when it has a main picture from before SPEC_21 and no panel
// yet (or when the panels are not known). When every panel is chosen it shows the sheet (characters) or the first panel.
export function startingPanel({type, panels = null, mainUrl = '', base = null}) {
  if (!panels || !panelsOf(type).length) return ALL;
  const any = panelsOf(type).some(panel => chosenPanel(panels, panel));
  if (!any && mainUrl) return ALL;
  const next = panelsOf(type).find(panel => !isMadePanel(panel) && !chosenPanel(panels, panel) && !panelBlock({type, panel, panels, base}));
  if (next) return next;
  return chosenPanel(panels, 'sheet') ? 'sheet' : panelsOf(type)[0];
}

// A panel's candidates (GET /assets/{id}/images?panel=): the chosen one first, then the newest first (the server lists oldest first).
// A candidate made for another panel never shows here, even if the server sent it.
export function panelCandidates(images = [], panel, chosen = null) {
  const own = (Array.isArray(images) ? images : []).filter(image => image?.url && (!image.panel || image.panel === panel))
    .map(image => ({...image, chosen: Boolean(chosen?.imageId) && image.imageId === chosen.imageId}));
  return [...own.filter(image => image.chosen), ...own.filter(image => !image.chosen).reverse()];
}

// ---- Requests (SPEC_21 §2.2) ----
export const panelGenerationBody = (panel, count) => ({panel, count: clampCount(count)});
export const clampStress = value => Math.max(STRESS_MIN, Math.min(STRESS_MAX, Math.round(Number(value)) || STRESS_DEFAULT));
export function stressBody({count = STRESS_DEFAULT, withAssets = [], setCode = ''} = {}) {
  const codes = [...new Set((withAssets || []).map(code => String(code).trim().toUpperCase()).filter(Boolean))].slice(0, STRESS_WITH_MAX);
  return {count: clampStress(count), ...(codes.length ? {withAssets: codes} : {}), ...(setCode ? {setCode: String(setCode).toUpperCase()} : {})};
}
// One lock field, as PATCH /assets/{id}/meta takes it; null for a field the server does not know.
export function metaPatch(field, value) {
  if (!META_FIELDS.includes(field)) return null;
  return {[field]: String(value ?? '').slice(0, META_MAX)};
}
// The lock fields of a subject, in the order they are shown: a look's change first (what differs), then the locks of its type.
export const lockFields = (type, variant = false) => [...(variant ? ['change'] : []), ...(LOCKS[type] || [])];

// A new look (POST /assets/{id}/variants). A state (wet, injured, the prop in another state) needs its change; the server opens its
// description with "Same identity as @base …".
export const LOOK_KINDS = Object.freeze(['OUTFIT', 'POSE', 'LOOK', 'STATE']);
export const lookReady = ({name = '', kind = 'OUTFIT', change = ''}) => Boolean(String(name).trim()) && (kind !== 'STATE' || Boolean(String(change).trim()));
export function lookBody({name = '', kind = 'OUTFIT', prompt = '', change = ''}) {
  return {name: String(name).trim(), kind: LOOK_KINDS.includes(kind) ? kind : 'OUTFIT', prompt: String(prompt).trim(),
    ...(kind === 'STATE' ? {change: String(change).trim()} : {})};
}

// ---- The stress test ----
// "7 / 10 recognizable": how many of the pictures were marked recognizable, out of all of them.
export function stressTally(results = []) {
  const list = Array.isArray(results) ? results : [];
  const recognizable = list.filter(item => item?.recognizable === true).length, unrecognizable = list.filter(item => item?.recognizable === false).length;
  return {recognizable, unrecognizable, unmarked: list.length - recognizable - unrecognizable, total: list.length};
}
// The results in the order they were asked for (variation 0, 1, ...), newest batch first when one variation was run twice.
export const stressOrder = (results = []) => (Array.isArray(results) ? results : []).map((item, index) => ({item, index}))
  .sort((a, b) => (Number(a.item?.variation) || 0) - (Number(b.item?.variation) || 0) || b.index - a.index).map(entry => entry.item);
export const stressMarked = (results, imageId, recognizable) => (results || []).map(item => item.imageId === imageId ? {...item, recognizable} : item);
// The list as the server sends it: an array, or a page of items ({items, nextCursor, total, recognizable} for the stress tests).
export const listOf = data => Array.isArray(data) ? data : Array.isArray(data?.items) ? data.items : [];

// Who can share the frame and which set to stand in: from the wall's assets when the page passes them, otherwise from the codes of the
// shots that already use this asset (the company it keeps). Looks of the asset itself never count.
export function stressCompany(item, assets = null) {
  const own = baseCode(item?.assetCode);
  const usedWith = new Map();
  for (const shot of item?.uses || []) for (const code of shot.assets || []) {
    const key = String(code).toUpperCase();
    if (baseCode(key) !== own) usedWith.set(key, (usedWith.get(key) || 0) + 1);
  }
  const listed = Array.isArray(assets)
    ? assets.filter(asset => asset?.assetCode && baseCode(asset.assetCode) !== own && asset.isDefault !== false)
      .map(asset => ({code: asset.assetCode.toUpperCase(), name: asset.name || asset.assetCode, imageUrl: asset.selectedImageUrl || null, type: asset.type || typeOfCode(asset.assetCode)}))
    : [...usedWith.keys()].map(code => ({code, name: code, imageUrl: null, type: typeOfCode(code)}));
  const shared = entry => usedWith.get(entry.code) || usedWith.get(baseCode(entry.code)) || 0;
  const sorted = listed.map((entry, index) => ({entry, index})).sort((a, b) => shared(b.entry) - shared(a.entry) || a.index - b.index).map(({entry}) => entry);
  return {cast: sorted.filter(entry => entry.type !== 'SCENE'), sets: sorted.filter(entry => entry.type === 'SCENE')};
}

// ---- Panel generations in the background (the SPEC_18 R1 pattern, per panel) ----
// A panel batch is up to four tasks (count 1-4); each is a run of generationModel keyed `${assetId}#${panel}#${n}`, so the same start, settle,
// cancel and reload rules hold. One batch per panel at a time; a new batch replaces what the last one left (a failure, a cancel).
export const runKey = (assetId, panel, index = 0) => `${assetId}#${panel}#${index}`;
const prefix = (assetId, panel) => `${assetId}#${panel}#`;
export const panelRunEntries = (runs, assetId, panel) => Object.entries(runs || {}).filter(([key]) => key.startsWith(prefix(assetId, panel)));

export function startPanelRuns(runs, assetId, panel) {
  if (panelRunEntries(runs, assetId, panel).some(([, run]) => isActiveRun(run))) return runs;
  const next = Object.fromEntries(Object.entries(runs || {}).filter(([key]) => !key.startsWith(prefix(assetId, panel))));
  return {...next, [runKey(assetId, panel)]: {taskId: '', status: 'QUEUED'}};
}
// The answer of POST image-generations / stress-tests: {tasks, count}, or one task (a request without count).
export const createdTasks = created => Array.isArray(created?.tasks) ? created.tasks.filter(task => task?.taskId) : created?.taskId ? [created] : [];
export function panelRunsStarted(runs, assetId, panel, created) {
  let next = Object.fromEntries(Object.entries(runs || {}).filter(([key]) => !key.startsWith(prefix(assetId, panel))));
  createdTasks(created).forEach((task, index) => {next = settleRun(runStarted(next, runKey(assetId, panel, index), task), runKey(assetId, panel, index), task);});
  return next;
}
export const panelRunRefused = (runs, assetId, panel, message) => runRefused(runs, runKey(assetId, panel), message);

// What a panel says about its batch: null when nothing is in flight or left to say; else
//   {status: 'active' | 'failed' | 'canceled', active, failed, canceled, taskIds (in flight, to cancel), error}
export function panelRunState(runs, assetId, panel) {
  const list = panelRunEntries(runs, assetId, panel).map(([, run]) => run);
  if (!list.length) return null;
  const active = list.filter(isActiveRun), failed = list.filter(run => run.status === 'FAILED'), canceled = list.filter(run => run.status === 'CANCELED');
  const status = active.length ? 'active' : failed.length ? 'failed' : canceled.length ? 'canceled' : null;
  if (!status) return null;
  return {status, active: active.length, failed: failed.length, canceled: canceled.length, taskIds: active.map(run => run.taskId).filter(Boolean),
    error: failed.find(run => run.error)?.error || ''};
}
// The run-shaped view of a batch, for the picture's RunState badge.
export const batchRun = state => !state ? null : state.status === 'active' ? {status: 'RUNNING'} : state.status === 'failed' ? {status: 'FAILED', error: state.error} : {status: 'CANCELED'};
// The subjects and panels whose candidates should be read again: a task of theirs finished. -> ['assetId#panel']
export const finishedScopes = answers => [...new Set(answers.filter(([, answer]) => answer?.status === 'SUCCEEDED').map(([key]) => key.split('#').slice(0, 2).join('#')))];
export { activeTasks };

// ---- The prompt preview (POST /shots/{id}/prompt-previews): the reference plan and what the budget left out ----
export const REFERENCE_ROLES = Object.freeze(['character_face', 'character_body', 'location', 'prop']);
export const referenceRows = plan => (Array.isArray(plan) ? plan : []).filter(entry => entry && (entry.url || entry.assetCode))
  .map((entry, index) => ({index: index + 1, code: String(entry.assetCode || ''), role: REFERENCE_ROLES.includes(entry.role) ? entry.role : 'other',
    panel: entry.panel || null, url: entry.url || null}));
export const droppedList = blocks => (Array.isArray(blocks) ? blocks : []).map(block => String(block ?? '').trim()).filter(Boolean);
