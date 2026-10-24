import { cameraKeys, planFromSlate } from './previs/plan.js';

// SPEC_15: an agent's table proposal is reviewed where it lands, on the shot it changes, not in the assistant side panel. These
// are the rules for finding a shot's pending proposals and for what a camera proposal would make of the shot (its ghost camera).
// A table_edit proposal's review has one group per edited row (group.row_id is the row's rid), each with its column changes.
export const isPending = proposal => proposal?.status === 'pending';

// One entry per group that edits this row, from the pending table proposals for this tab. partial: the groups of this
// proposal can be applied one at a time; size: how many rows the whole proposal edits.
export function rowProposals(proposals, rid, tabKey) {
  return (Array.isArray(proposals) ? proposals : [])
    .filter(proposal => isPending(proposal) && proposal.action === 'table_edit' && (!tabKey || !proposal.target?.tab_key || proposal.target.tab_key === tabKey))
    .flatMap(proposal => {
      const review = proposal.review || proposal.target?.review, groups = review?.groups || [];
      return groups.filter(group => group.row_id === rid).map(group => ({proposal, group, review, partial: Boolean(review.partial_allowed), size: groups.length}));
    });
}

// What to send to apply one entry: just its row when the proposal allows it, else the whole proposal.
export const applyOptions = ({group, review, partial}) => partial ? {groups: [group.index], review_version: review.version} : {};

const changeIn = (group, pattern) => group.changes?.find(change => pattern.test(change.column));
// The shot's slate text as the proposal would leave it.
export function proposedSlate(slate = {}, group) {
  const motion = changeIn(group, /camera.*motion/i), rig = changeIn(group, /optical|rig|lens/i), action = changeIn(group, /action|prompt/i);
  return {motion: motion ? motion.after : slate.motion, rig: rig ? rig.after : slate.rig, action: action ? action.after : slate.action, camera: Boolean(motion || rig)};
}
// The shot's plan with the proposed camera in place of its own (a custom framed path gives way to the proposed move), or null
// when the proposal does not touch the camera or would leave it where it is.
export function ghostPlan(plan, slate, group) {
  const next = proposedSlate(slate, group);
  if (!next.camera) return null;
  const {move, lens} = planFromSlate(next), ghost = {...plan, move, lens, keys: null};
  return JSON.stringify(cameraKeys(ghost)) === JSON.stringify(cameraKeys(plan)) ? null : ghost;
}
// Ghost cameras for the stage: every pending camera proposal on a shot, labelled with the shot it belongs to.
export function ghostsFor(proposals, shots, tabKey, planOf) {
  return shots.flatMap(shot => rowProposals(proposals, shot.rid, tabKey).flatMap(entry => {
    const plan = ghostPlan(planOf(shot), shot.slate, entry.group);
    return plan ? [{rid: shot.rid, id: entry.proposal.id, label: shot.shot, plan, entry}] : [];
  }));
}
