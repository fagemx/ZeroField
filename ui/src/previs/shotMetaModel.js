import { defaultPlan } from './plan.js';
import { dummiesOf } from './blocking.js';
import { codesOnSet, samePlan } from './storyPlan.js';
import { agentLabel } from '../format.js';

// SPEC_20 R18 (decision 5): a crew proposal that changes a shot's stored 3D plan (action shot_meta, field previsPlan). It is
// reviewed where it lands, on the 3D Stage: the proposed plan as a ghost over the current one, approved or rejected through the
// assistant's own proposal decisions. These are the rules for reading a shot's proposals and for what the stage shows of one.
export const SHOT_META = 'shot_meta';
export const PREVIS_FIELD = 'previsPlan';

// GET /projects/api/{slug}/assistant/shots/{shotId}/proposals: my pending proposals for the shot, each with its proposed value.
export const shotProposalsPath = (slug, shotId) => `/projects/api/${slug}/assistant/shots/${encodeURIComponent(shotId)}/proposals`;
// get is api.get (a test passes a fake). Only well-formed pending 3D plan proposals are kept: a plan, or (SPEC_20 R27) the
// operations a server without a headless browser could not solve, which this stage solves itself.
const isPlan = value => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const opsOnly = p => !isPlan(p?.value) && Array.isArray(p?.ops) && p.ops.length > 0;
export async function loadShotProposals(get, slug, shotId) {
  const data = await get(shotProposalsPath(slug, shotId));
  return (Array.isArray(data?.proposals) ? data.proposals : []).filter(p => p?.action === SHOT_META && p.status === 'pending'
    && p.field === PREVIS_FIELD && (isPlan(p.value) || opsOnly(p)));
}
// POST: the stage's solve of an operations-only proposal, attached before it is approved (previs_ops.attach_solution).
export const solutionPath = (slug, id) => `/projects/api/${slug}/assistant/proposals/${id}/solution`;

// The operations as lines the inspector shows: [{key (stage.* text), params}], in the order they were sent.
export function opLines(ops, moveKeys = { static: 1, orbit: 3 }) {
  const metres = value => `${value > 0 ? '+' : ''}${Math.round(value * 100) / 100}`;
  return (Array.isArray(ops) ? ops : []).map(op => {
    if (op?.op === 'place') {
      const [x, z] = Array.isArray(op.offset) ? op.offset : [0, 0];
      return { key: 'metaOpPlace', params: { cast: op.cast, where: op.relativeTo + (x || z ? ` ${metres(x)}, ${metres(z)} m` : ''), facing: op.facing } };
    }
    if (op?.op === 'camera') {
      const last = moveKeys[op.move] ?? 2, keys = op.move === 'static' ? '' : ` ${op.from || 'K1'}→${op.to || 'K' + last}`;
      return { key: 'metaOpCamera', params: { size: String(op.size || '').replace('_', ' '), angle: op.angle, lens: op.lens, move: op.move, keys } };
    }
    return { key: 'metaOpRetime', params: { beat: op?.beat, percent: Math.round((op?.at ?? 0) * 100) } };
  });
}

// The assistant's list carries my proposals without their values; the ids pending for this shot tell the stage when to read
// the shot's list again (a new proposal came in, or one was decided from a card).
export function shotMetaKey(proposals, shotId) {
  if (!shotId) return '';
  return (Array.isArray(proposals) ? proposals : [])
    .filter(p => p?.action === SHOT_META && p.status === 'pending' && p.target?.shotId === shotId)
    .map(p => p.id).sort((a, b) => a - b).join(',');
}

const SCALARS = [['set', 'set'], ['move', 'move'], ['lens', 'lens'], ['seconds', 'duration'], ['action', 'action'], ['facing', 'facing'], ['mood', 'light']];
const same = (a, b, keys) => keys.every(key => samePlan(a?.[key] ?? null, b?.[key] ?? null));
// Everyone on set by who they are: the plan's own actor, then the cast by code (or place, for someone without one).
const people = plan => new Map([['actor', plan || {}], ...(plan?.cast || []).map((member, index) => [member.code || '#' + index, member])]);
// Whether anyone on set in both plans differs in these keys (someone joining or leaving is said on its own).
function moved(current, proposed, keys) {
  const before = people(current), after = people(proposed);
  return [...before].some(([who, person]) => after.has(who) && !same(person, after.get(who), keys));
}

// What the proposal changes in the plan on stage, in the stage's own terms: {kind: 'field', key, label, from, to} for the
// pickers (label is the previs.* key of the picker's name), then the camera path, who joins or leaves, the marks, the acting
// and anything else (figures, props, cards).
export function planChanges(current, proposed) {
  const changes = [];
  for (const [key, label] of SCALARS) {
    if (!samePlan(current?.[key] ?? null, proposed?.[key] ?? null)) changes.push({ kind: 'field', key, label, from: current?.[key], to: proposed?.[key] });
  }
  if (!same(current, proposed, ['keys', 'easing'])) changes.push({ kind: 'camera' });
  const before = codesOnSet(current || {}), after = codesOnSet(proposed || {});
  const added = after.filter(code => !before.includes(code)), removed = before.filter(code => !after.includes(code));
  if (added.length) changes.push({ kind: 'castAdded', codes: added });
  if (removed.length) changes.push({ kind: 'castRemoved', codes: removed });
  if (moved(current, proposed, ['mark', 'turn'])) changes.push({ kind: 'blocking' });
  if (moved(current, proposed, ['acts']) || !same(current, proposed, ['use', 'pins', 'fix'])) changes.push({ kind: 'acting' });
  if (moved(current, proposed, ['figure']) || !same(current, proposed, ['props', 'layers', 'beacon', 'presentation'])) changes.push({ kind: 'other' });
  return changes;
}

// Where the proposal puts each person on set (numeric marks only; an open range has no one spot): rings on the overhead plan.
export function ghostMarks(proposed) {
  if (!proposed) return [];
  return dummiesOf(proposed).map((d, index) => ({ id: d.id, mark: d.mark, code: (index === 0 ? proposed.code : proposed.cast?.[index - 1]?.code) || '' }))
    .filter(d => Array.isArray(d.mark) && d.mark.length === 2 && d.mark.every(Number.isFinite));
}

// The author as people read it: the crew member's (localized) title for an agent, the person's name for a member.
export function authorLabel(author) {
  if (!author) return '';
  return author.kind === 'agent' ? agentLabel({ agent_key: author.key, display_name: author.name }) || author.key || '' : author.name || '';
}

// The review the stage shows for a shot: its first pending proposal (others wait their turn), or null.
//   plan: the plan on stage now; revision: the stored revision the stage holds; writable: this person may edit;
//   draft: the shot has unsaved edits in this browser (approving would leave them behind, so it waits); error: a refusal to show;
//   solve(proposal) -> plan: this stage's own solve (ops.js) of an operations-only proposal (SPEC_20 R27); it throws when it cannot.
export function shotMetaReview(list, { plan = null, revision = 0, writable = false, draft = false, error = '', solve = null } = {}) {
  const pending = Array.isArray(list) ? list.filter(p => p?.status === 'pending' && (isPlan(p.value) || opsOnly(p))) : [];
  const first = pending[0];
  if (!first) return null;
  let solved = isPlan(first.value) ? first.value : null, solveError = '';
  if (!solved) {
    try { solved = solve ? solve(first) : null; } catch (e) { solveError = e?.message || String(e); }  // null: not ready yet
  }
  const proposed = solved ? { ...defaultPlan(), ...solved } : null;
  const current = Math.max(Number.isInteger(first.currentRevision) ? first.currentRevision : 0, Number.isInteger(revision) ? revision : 0);
  const canDecide = Boolean(writable && first.canDecide);
  const changes = proposed ? planChanges(plan, proposed) : [];
  return {
    id: first.id, proposal: first, plan: proposed, label: first.shot?.label || '', author: authorLabel(first.author),
    summary: String(first.summary || ''), baseRevision: first.baseRevision, currentRevision: current,
    stale: Number.isInteger(first.baseRevision) && first.baseRevision !== current,
    changes, same: Boolean(proposed) && changes.length === 0, marks: proposed ? ghostMarks(proposed) : [],
    // SPEC_20 R27, R28: the operations, the server's contact sheet, how it was solved and an optional model note.
    ops: opLines(first.ops), preview: first.preview?.url ? first.preview : null, warnings: first.solve?.warnings || [],
    opsOnly: opsOnly(first), solveError, vision: first.vision || null,
    canDecide, readOnly: !canDecide, blockedByDraft: canDecide && Boolean(draft), blockedBySolve: canDecide && !proposed,
    more: pending.length - 1, error: error || '',
  };
}
