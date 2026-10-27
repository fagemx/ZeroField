// SPEC_20 R24, R25: the crew's pre-production flow for one episode, as the panel shows it. The server runs the stages
// (Screenwriter, Art, Cinematographer, Continuity) as ordinary crew jobs and holds the director's three locks between
// them; these are the panel's rules: where each action goes, what each state says, what a lock will cover, how often
// to look again, and when the "Let the crew pre-produce" card shows (after the storyboard is built).
export const PREPRODUCTION_STAGES = ['screenwriter', 'art', 'cinematographer', 'continuity'];
export const PREPRODUCTION_LOCKS = ['script', 'list', 'storyboard'];
export const STAGE_GATE = {art: 'script', cinematographer: 'list', continuity: 'storyboard'};
export const ACTIVE_FLOW = ['running', 'waiting', 'blocked'];

export const preproductionPath = (epId, tail = '') => `/episodes/${epId}/preproduction${tail ? '/' + tail : ''}`;
export const flowCancelPath = (slug, flow) => `/projects/api/${slug}/orchestration/crew-flows/${flow.flowId}/cancel`;
export const flowActive = flow => ACTIVE_FLOW.includes(flow?.status);

const finished = counts => (counts?.succeeded || 0) + (counts?.failed || 0) + (counts?.canceled || 0);

// The flow's one-line state: an i18n key under preproduction and its parameters (stage and lock names are keys too).
export function flowLine(flow) {
  if (!flow) return null;
  if (flow.status === 'running') {
    const stage = flow.stages.find(item => item.status === 'running') || {};
    return {key: 'line_running', stage: stage.key, params: {finished: finished(stage.counts), total: stage.counts?.total || 0}};
  }
  if (flow.status === 'waiting') return {key: 'line_waiting', lock: flow.waitingFor, params: {}};
  if (flow.status === 'blocked') return {key: 'line_blocked', params: {reason: flow.blocked?.message || ''}, blocked: flow.blocked};
  if (flow.status === 'stopped') return {key: 'line_stopped', params: {reason: flow.stop?.message || ''}, stop: flow.stop};
  return {key: 'line_' + flow.status, params: {}};
}

// What a lock will cover, from GET preproduction's next.summary: the key and its numbers.
export function lockSummary(next) {
  if (!next?.summary) return null;
  const s = next.summary;
  const params = {script: {scenes: s.scenes, chars: s.chars}, list: {assets: s.assets, looks: s.looks, shots: s.shots},
    storyboard: {shots: s.shots, withPlan: s.withPlan}}[next.lock];
  return params ? {key: 'lockWhat_' + next.lock, params, items: Array.isArray(s.items) ? s.items : []} : null;
}

// One row per stage with the lock that opens it: set (who, when), the one to set now, or one still ahead.
export function stageRows(state) {
  const flow = state?.flow;
  if (!flow) return [];
  return flow.stages.map(stage => {
    const gate = STAGE_GATE[stage.key] || null;
    const held = gate ? flow.locks?.[gate] || null : null;
    const asking = Boolean(gate) && flow.status === 'waiting' && flow.waitingFor === gate;
    return {...stage, gate, held, asking, next: asking ? state.next : null,
      current: flow.current === stage.key && flowActive(flow),
      active: (stage.jobs || []).filter(job => ['queued', 'running'].includes(job.status)).slice(0, 5)};
  });
}

// Look again soon while the crew works; slower while it waits for you (a lock can still be invalidated); not at all after.
export function pollDelay(flow) {
  if (flow?.status === 'running') return 2000;
  return flowActive(flow) ? 6000 : null;
}

// R25: the card that invites the crew in once the storyboard exists. It shows to someone who can write, when the episode
// has shots, no flow is running and it has not been set aside for this episode.
export function showPreproductionCard({state, shots = 0, writable = false, dismissed = false}) {
  return Boolean(writable && state && state.canStart && shots > 0 && !flowActive(state.flow) && !dismissed);
}

const DISMISSED = epId => 'zf.preproductionCard:' + epId;
export function cardDismissed(epId, storage = globalThis.localStorage) {
  try { return storage?.getItem(DISMISSED(epId)) === '1'; } catch { return false; }
}
export function dismissCard(epId, storage = globalThis.localStorage) {
  try { storage?.setItem(DISMISSED(epId), '1'); } catch { /* a private window keeps the card */ }
}
