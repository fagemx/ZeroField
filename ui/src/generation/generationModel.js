// Background generation (SPEC_18 R1): one picture task per card, running while you do other things.
// A run is {taskId, status, error?}. QUEUED / RUNNING are in flight; FAILED keeps its reason for a retry; CANCELED is said as canceled,
// not as a failure. A finished task leaves no run behind: its card refreshes and that is all.
export const isActiveRun = run => Boolean(run) && ['QUEUED', 'RUNNING'].includes(run.status);

// assetId -> taskId of everything still in flight (what survives a reload). A run whose task is not created yet has no id to keep.
export const activeTasks = runs => Object.fromEntries(Object.entries(runs).filter(([, run]) => isActiveRun(run) && run.taskId).map(([assetId, run]) => [assetId, run.taskId]));

// What a reload restored: the tasks are in flight as far as we know; the first poll says what became of them.
export const restoredRuns = tasks => Object.fromEntries(Object.entries(tasks).map(([assetId, taskId]) => [assetId, {taskId, status: 'RUNNING'}]));

// The click is accepted at once: the card shows "generating" before the task id exists.
export const startRun = (runs, assetId) => isActiveRun(runs[assetId]) ? runs : {...runs, [assetId]: {taskId: '', status: 'QUEUED'}};
export const runStarted = (runs, assetId, task) => ({...runs, [assetId]: {taskId: task.taskId, status: task.status || 'QUEUED'}});
export const runRefused = (runs, assetId, message) => ({...runs, [assetId]: {taskId: '', status: 'FAILED', error: message}});
export const runDismissed = (runs, assetId) => { const next = {...runs}; delete next[assetId]; return next; };

// A polled task folds into the runs. A succeeded task removes its run (the caller refreshes that one card); any other
// terminal state keeps the run so the card can say why. A stale answer for a run that moved on (another task id) is ignored.
export function settleRun(runs, assetId, task) {
  const run = runs[assetId];
  if (!run || (run.taskId && run.taskId !== task.taskId)) return runs;
  if (task.status === 'SUCCEEDED') return runDismissed(runs, assetId);
  if (task.status === 'FAILED') return {...runs, [assetId]: {taskId: task.taskId, status: 'FAILED', error: task.error?.message || 'FAILED'}};
  if (task.status === 'CANCELED') return {...runs, [assetId]: {taskId: task.taskId, status: 'CANCELED'}};
  return run.status === task.status ? runs : {...runs, [assetId]: {...run, status: task.status}};
}

// ---- SPEC_18 R8: the generation bar. The server lists what a card can use (GET /assets/{id}/generation-options); this file only reads
// that list, decides what the bar may say, and shapes the request so what is sent is what is shown.
export const FALLBACK_APP = 'flux-soul-cast';
// When the list cannot be read the bar offers the one workflow the page always used, so generating is never blocked by it (SPEC_18 4.3).
// A shot's video falls back to the studio's video card the same way (SPEC_19 R9).
export const FALLBACK_SHOT_APP = 'ltx25-cinema';
export const fallbackOptions = (appCode = FALLBACK_APP) => ({apps: [{appCode, name: appCode, tier: null, configured: true, reason: null, outputs: [], slots: {}, estimate: null, quotable: false}],
  defaultAppCode: appCode, style: null, degraded: true});
export const appFor = (options, appCode) => options?.apps?.find(app => app.appCode === appCode) || null;
// The workflow the bar starts on: the one asked for if it can run, else the server's default if it can, else the first that can.
export const startingApp = (options, wanted) => [appFor(options, wanted), appFor(options, options?.defaultAppCode), ...(options?.apps || [])].find(app => app?.configured) || null;

// The time the bar may promise: only what the server measured, and how many runs it rests on. Anything else is "unknown", never 0.
export function estimateOf(app) {
  const estimate = app?.estimate;
  return estimate && Number.isFinite(estimate.seconds) && estimate.seconds >= 1 && Number.isFinite(estimate.samples) && estimate.samples >= 1
    ? {seconds: Math.round(estimate.seconds), samples: Math.round(estimate.samples)} : null;
}
// 40 -> {unit:'s', value:40}; 95 -> {unit:'min', value:2}: the bar rounds, it does not pretend to know the second.
export const humanSeconds = seconds => seconds < 100 ? {unit: 's', value: Math.round(seconds)} : {unit: 'min', value: Math.round(seconds / 60)};

// The controls a card's slots give the bar. The server names two (aspectRatio, resolution) and, in slotParams, the card input each one
// sets (the modelParams key, nodeId.fieldName) and the values that input allows. A control exists only when there is an input to set; its
// menu is the values the card allows, else (for the ratio) the usual ratios. `values` are the choices made now (slot name -> value).
const RATIOS = ['16:9', '9:16', '1:1', '21:9'];
const isRatio = name => /aspect|ratio/i.test(name);
export function slotControls(app, values = {}, episodeRatio = '') {
  return Object.entries(app?.slots || {}).flatMap(([name, spec]) => {
    const param = app.slotParams?.[name];
    if (!param?.key) return [];
    const listed = param.options?.length ? param.options : Array.isArray(spec) && spec.length ? spec : null;
    const options = (listed || (isRatio(name) ? RATIOS : null))?.map(String);
    if (!options) return [];
    const wanted = values[name] ?? (isRatio(name) && options.includes(episodeRatio) ? episodeRatio : options[0]);
    return [{key: name, param: param.key, kind: isRatio(name) ? 'ratio' : 'resolution', options, value: options.includes(wanted) ? wanted : options[0]}];
  });
}
// What is sent is what is shown: the workflow on screen and, for each control on screen, its value under the card's own input key.
export function requestBody(app, controls = []) {
  const modelParams = Object.fromEntries(controls.map(control => [control.param, control.value]));
  return {appCode: app.appCode, ...(Object.keys(modelParams).length ? {modelParams} : {})};
}
// The reason a card is greyed out, as a message key (unknown codes get the plain one).
const REASON_KEYS = {blocked_by_policy: 'reason_blocked_by_policy', blocked_by_privacy: 'reason_blocked_by_privacy', not_configured: 'reason_not_configured'};
export const reasonKey = reason => REASON_KEYS[reason] || 'reason_unavailable';

// ---- SPEC_19 R9: the shot composer's parameter row (GenerationBar kind="shot"). A shot makes a video from its video cards
// (GET /shots/{id}/generation-options) or a first frame from the image cards (GET /catalog/apps?capability=IMAGE: the options of a shot
// list its video cards only). The catalog item of a card also lists its inputs, which give the row two controls the options do not:
// the seconds (a "duration" slot) and the sound (a generate_audio list). What is sent is still what is shown.
export const MAX_TAKES = 4;
export const clampCount = value => Math.max(1, Math.min(MAX_TAKES, Math.round(Number(value)) || 1));
export const SECOND_CHOICES = [4, 6, 8];  // the lengths the 3D Stage plans a shot in

const tierOf = item => item?.driver === 'comfy_router' ? 'router' : item?.driver === 'comfy_local' && item?.tier === 'open_weights' ? 'open_weights' : 'closed';
// A catalog item as a generation-options app. Availability is the card's provider configuration only: the policy and privacy checks
// of generation-options are not applied to image cards here (the server still refuses what the policy blocks when it is sent).
export function frameOptions(items, defaultAppCode = FALLBACK_APP) {
  const seen = new Set(), apps = [];
  for (const item of Array.isArray(items) ? items : []) {
    if (!item?.appCode || seen.has(item.card_id || item.appCode)) continue;
    seen.add(item.card_id || item.appCode);
    const configured = item.configuration?.configured !== false;
    apps.push({appCode: item.appCode, name: item.name || item.appCode, tier: tierOf(item), configured, reason: configured ? null : 'not_configured',
      outputs: ['IMAGE'], estimate: null, quotable: item.driver === 'comfy_router'});
  }
  const preferred = apps.find(app => app.appCode === defaultAppCode && app.configured) || apps.find(app => app.configured);
  return {apps, defaultAppCode: preferred?.appCode || null, style: null};
}

// The seconds and sound inputs of a card, from its catalog item's nodes: {duration: {key, options} | null, audio: {key} | null}.
//   duration: the card's visible "duration" slot (its options when it is a list); audio: a visible generate_audio list of true / false.
export function nodeControls(item) {
  const nodes = (item?.nodes || []).filter(node => !node.hidden), key = node => `${node.nodeId}.${node.fieldName}`;
  const duration = nodes.find(node => node.slot === 'duration');
  const audio = nodes.find(node => /generate_audio/i.test(node.fieldName) && (node.options || []).map(String).includes('true'));
  const listed = duration?.fieldType === 'LIST' && duration.options?.length ? duration.options.map(Number).filter(Number.isFinite) : null;
  return {duration: duration ? {key: key(duration), options: listed} : null, audio: audio ? {key: key(audio)} : null};
}
// The seconds the row offers for a card with a duration input: its own list, else 4, 6 and 8 with the shot's planned length.
export function secondChoices(control, planned) {
  if (!control) return [];
  if (control.options?.length) return control.options;
  const list = new Set(SECOND_CHOICES);
  if (Number.isFinite(planned) && planned > 0) list.add(Math.round(planned));
  return [...list].sort((a, b) => a - b);
}
// The value shown first: the shot's planned length when the card offers it, else the nearest offered one.
export function startingSeconds(choices, planned) {
  if (!choices.length) return null;
  if (!Number.isFinite(planned)) return choices[0];
  return choices.reduce((best, value) => Math.abs(value - planned) < Math.abs(best - planned) ? value : best, choices[0]);
}
// The shot row's request: the asset row's body, plus the seconds and the sound inputs when the card has them.
export function shotRequestBody(app, controls = [], {inputs = {}, seconds = null, audio = null} = {}) {
  const body = requestBody(app, controls), modelParams = {...(body.modelParams || {})};
  if (inputs.duration && Number.isFinite(seconds)) modelParams[inputs.duration.key] = seconds;
  if (inputs.audio && typeof audio === 'boolean') modelParams[inputs.audio.key] = audio ? 'true' : 'false';
  return {appCode: body.appCode, ...(Object.keys(modelParams).length ? {modelParams} : {})};
}
// The main button's words: "Save & generate" while the prompt has unsaved changes; else "Generate n", with the time when this
// production has measured the card (n takes take about n times as long: they run one after another). -> {key, params}
export function generateLabel({output = 'video', count = 1, estimate = null, dirty = false}) {
  if (dirty) return {key: 'composer.saveAndGenerate', params: {count}};
  const kind = output === 'frame' ? 'frame' : 'video';
  return estimate ? {key: 'composer.generateTime_' + kind, params: {count, seconds: estimate.seconds * count}} : {key: 'composer.generate_' + kind, params: {count}};
}
