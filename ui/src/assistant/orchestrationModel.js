import { t as uiText } from '../i18n/index.js';
export const EMPTY_COUNTS = { needs_you: 0, working: 0, done: 0, idle: 0 };

export function cancellationRequest(base, slug, item) {
  if (item.kind === 'flow') return { path: `/projects/api/${slug}/tabs/${item.target.tab_key}/flow/runs/${item.flow_run_id}/cancel`, body: {} };
  if (item.gate_id && item.run_id) return { path: `${base}/runs/${item.run_id}/cancel`, body: { reason: uiText("orchestrationModel.batchCanceledFromAgentBoard") } };
  return { path: `${base}/dispatches/${item.dispatch_id}/cancel`, body: { admission_no: item.admission_no, reason: uiText("orchestrationModel.canceledFromAgentBoard") } };
}
export const emptyBoard = () => ({ needs_you: [], working: [], done: [], idle: [], counts: { ...EMPTY_COUNTS }, cursor: null,
  ui: { selected: null, drafts: {}, selectedProposalId: null } });

export function groupBoardItems(items = []) {
  const groups = { needs_you: [], working: [], done: [], idle: [] };
  const gated = new Set(items.filter(item => item.gate_id).flatMap(item => item.proposal_ids || []));
  const seen = new Set();
  for (const item of items) {
    if (!item || seen.has(item.id)) continue;
    seen.add(item.id);
    if (item.kind === 'agent') groups.idle.push(item);
    else if (['question', 'proposal_review', 'race_select', 'escalation'].includes(item.kind)) {
      if (['resolved', 'dismissed'].includes(item.status)) continue;
      if (!item.gate_id && item.proposal_ids?.length && item.proposal_ids.every(id => gated.has(id))) continue;
      groups.needs_you.push(item);
    } else if (['queued', 'running'].includes(item.status)) groups.working.push(item);
    else if (['completed', 'succeeded', 'failed', 'canceled'].includes(item.status)) groups.done.push(item);
  }
  return groups;
}

export function reconcileBoard(previous, next, context = {}) {
  if (context.responseSlug && context.currentSlug !== context.responseSlug) return previous;
  const ui = previous?.ui || emptyBoard().ui;
  const selected = ui.selected ? (next.needs_you || []).find(item => item.gate_id === ui.selected.gate_id) || { ...ui.selected, stale: true } : null;
  const open = new Set((next.needs_you || []).map(item => item.gate_id));
  if (selected) open.add(selected.gate_id);
  return { ...next, ui: { ...ui, selected, drafts: Object.fromEntries(Object.entries(ui.drafts || {}).filter(([id]) => open.has(id))) } };
}

export function raceSelectionPayload(gate, proposalId, requestId) {
  if (!Number.isInteger(proposalId) || proposalId <= 0) throw new Error(uiText("orchestrationModel.selectACandidateThatIsReadyForReview"));
  return { client_request_id: requestId, resolution: { proposal_id: proposalId } };
}

export function assignmentRequest({ objective, strategy = 'single', agentKey, raceAgents, scope, target, requestId, mode = 'proposal' }) {
  if (!objective?.trim()) throw new Error(uiText("orchestrationModel.describeTheTask"));
  return { client_request_id: requestId, objective: objective.trim(), strategy, write_mode: mode,
    ...(agentKey && strategy !== 'race' ? { agent_key: agentKey } : {}),
    ...(strategy === 'race' ? { race_agents: [...raceAgents] } : {}),
    ...(scope ? { scope: structuredClone(scope) } : {}), ...(target && mode !== 'analysis_only' ? { target: structuredClone(target) } : {}) };
}

export function proposalChanges(proposal) {
  const review = proposal.target?.review || proposal.review;
  if (review?.groups?.length) return review.groups;
  return [{ label: proposal.action || uiText("orchestrationModel.proposedChanges"), changes: [{ column: proposal.target?.tab_title || uiText("orchestrationModel.content"),
    before: proposal.target?.quote || '', after: proposal.content || '' }] }];
}
