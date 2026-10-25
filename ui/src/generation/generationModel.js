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
export const fallbackOptions = () => ({apps: [{appCode: FALLBACK_APP, name: FALLBACK_APP, tier: null, configured: true, reason: null, outputs: [], slots: {}, estimate: null, quotable: false}],
  defaultAppCode: FALLBACK_APP, style: null, degraded: true});
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
