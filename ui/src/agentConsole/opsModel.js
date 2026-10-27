// Agent Console operations (SPEC_20 R36, R38-R40): pure view logic for the model setup and health
// check, the GPU panel, the project-wide queue and the automation switch. Wire values stay as the
// server sends them; everything a person reads goes through console.ops.* messages.
import { currentLocale, t } from '../i18n/index.js';

export const HEALTH_STEPS = ['model', 'chat', 'tools', 'json', 'vision', 'context'];
// A failure here means later steps would only repeat it; they are shown as skipped instead of run.
const BLOCKING = { model: ['unreachable', 'not_model_server', 'model_missing', 'auth', 'governance', 'kind_removed', 'unsupported_kind', 'auth_missing'],
  chat: ['unreachable', 'model_missing', 'governance', 'kind_removed', 'unsupported_kind', 'auth_missing', 'auth', 'timeout', 'quota'] };
const SERVER_DOWN = ['unreachable', 'governance', 'kind_removed', 'unsupported_kind', 'auth_missing'];

/** Steps still to run after `result`; [] when a blocking failure makes the rest pointless. */
export function remainingSteps(result, steps = HEALTH_STEPS) {
  const after = steps.slice(steps.indexOf(result.step) + 1);
  if (result.status !== 'fail' || !BLOCKING[result.step]?.includes(result.code)) return after;
  // The context length only needs the server, so it still runs when the model server answered.
  return SERVER_DOWN.includes(result.code) ? [] : after.filter(step => step === 'context');
}

export const TONE = { pass: 'ok', warn: 'warn', fail: 'bad', skip: 'muted', skipped: 'muted', running: 'muted', pending: 'muted' };

const FIXES = ['start_ollama', 'start_model_server', 'check_endpoint', 'ollama_pull', 'load_model', 'set_api_key', 'allow_host',
  'review_agent', 'reconfigure_provider', 'use_builtin_provider', 'configure_provider', 'tool_model', 'json_model', 'vision_model',
  'retry_when_idle', 'wait_or_raise_quota', 'ollama_context_length', 'server_context'];
const CODES = ['model_present', 'list_unavailable', 'unreachable', 'not_model_server', 'model_missing', 'auth', 'governance', 'kind_removed',
  'unsupported_kind', 'auth_missing', 'replied', 'empty_reply', 'tool_called', 'no_tool_call', 'tool_arguments', 'json_valid', 'json_invalid',
  'image_described', 'vision_wrong', 'rejected', 'timeout', 'quota', 'model_error', 'context_ok', 'context_4096', 'context_small',
  'context_server_default', 'context_remote', 'context_unknown_server'];

/** Plain-language lines for one step result: what happened, and what to do about it. */
export function stepText(result) {
  const detail = result?.detail || {};
  const params = { model: detail.model || '', host: detail.host || '', port: detail.port ?? '', length: detail.contextLength ?? '',
    target: detail.target ?? 16384, max: detail.modelMax ?? '' };
  const code = CODES.includes(result?.code) ? result.code : 'unknown';
  return {
    summary: t('console.ops.check.code.' + code, { ...params, code: result?.code || '' }),
    fix: result?.fix ? t('console.ops.check.fix.' + (FIXES.includes(result.fix) ? result.fix : 'unknown'), params) : '',
    command: result?.fix === 'ollama_pull' ? 'ollama pull ' + (detail.model || '') : result?.fix === 'ollama_context_length' ? CONTEXT_COMMAND : '',
  };
}
export const CONTEXT_COMMAND = '$env:OLLAMA_CONTEXT_LENGTH=16384; ollama serve';
export const PULL_COMMAND = model => 'ollama pull ' + model;

/** Crew agents that do not resolve to the recommended local preset. */
export const offPreset = setup => (setup?.agents || []).filter(agent => !agent.matchesPreset);

export function providerLine(provider) {
  if (!provider) return t('console.ops.setup.noProvider');
  return provider.local ? t('console.ops.setup.localProvider', { model: provider.model, address: provider.baseUrl })
    : t('console.ops.setup.hostedProvider', { model: provider.model, host: provider.host });
}

// ---------- GPU panel ----------
const GIB = 1024 ** 3;
export const gib = bytes => (Number.isFinite(bytes) && bytes !== null ? (bytes / GIB).toFixed(1) : '—');
/** Free/total VRAM and the used share for the meter; null when ComfyUI did not report it. */
export function vram(device) {
  if (!device || !Number.isFinite(device.vramTotal) || !device.vramTotal || !Number.isFinite(device.vramFree)) return null;
  const used = Math.max(0, device.vramTotal - device.vramFree);
  return { free: gib(device.vramFree), total: gib(device.vramTotal), used: gib(used), share: Math.min(1, used / device.vramTotal) };
}
export const gpuShare = model => (Number.isFinite(model?.gpuShare) ? Math.round(model.gpuShare * 100) : null);

// ---------- queue and failures ----------
const ERROR_KINDS = ['abandoned', 'not_member', 'quota', 'lockdown', 'admission', 'crash', 'auth', 'timeout', 'unavailable', 'bad_response',
  'kind_removed', 'configuration', 'local', 'provider', 'empty', 'output', 'error'];
export const QUEUE_GROUPS = ['turns', 'dispatches', 'tasks', 'grades'];

/** Why a chat turn failed, in plain words; the stored kind is kept for anything newer. */
export function turnReason(item) {
  const kind = item?.errorKind;
  return ERROR_KINDS.includes(kind) ? t('console.ops.queue.kind.' + kind) : t('console.ops.queue.kind.other', { kind: kind || '?' });
}
/** One line per queued/running/failed item: who does it, what state, and the reason when it failed. */
export function queueLine(group, item) {
  const who = group === 'tasks' ? t('console.ops.queue.pipelineStep', { node: item.nodeId, tab: item.tabKey })
    : group === 'grades' ? t(item.auto ? 'console.ops.queue.autoGrade' : 'console.ops.queue.manualGrade', { shot: item.shotId })
      : item.agentKey;
  const reason = group === 'turns' ? (item.status === 'failed' ? turnReason(item) : '') : item.error || '';
  return { who, state: t('console.ops.queue.state.' + item.status, { defaultValue: item.status }), reason,
    detail: group === 'turns' ? item.detail || '' : '', mine: item.mine, at: item.finishedAt || item.updatedAt || item.createdAt || item.requestedAt };
}
export const queueTotals = view => QUEUE_GROUPS.reduce((sum, group) => ({ active: sum.active + (view?.counts?.[group]?.active || 0),
  failed: sum.failed + (view?.counts?.[group]?.failed || 0) }), { active: 0, failed: 0 });

/** A reconcile amount the server accepts: a nonnegative decimal string with at most four places. */
export const validCost = text => /^\d{1,6}(?:\.\d{1,4})?$/.test(String(text ?? '').trim());

// ---------- automation switch ----------
export function pauseLine(automation) {
  if (!automation?.paused) return '';
  const when = automation.at ? new Date(automation.at) : null;
  const at = when && !Number.isNaN(when.getTime()) ? when.toLocaleString(currentLocale(), { dateStyle: 'medium', timeStyle: 'short' }) : '';
  return t(automation.reason ? 'console.ops.automation.pausedByReason' : 'console.ops.automation.pausedBy',
    { name: automation.byName || t('console.ops.automation.someone'), at, reason: automation.reason || '' });
}
