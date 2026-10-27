import { isPending, rowProposals } from './proposalModel.js';

// SPEC_20 R7, R19-R23: asking the crew for a planning job on a target (a shot, an asset, a scene or an episode). The job
// runs on the server's crew worker and ends in proposals reviewed where they land (a shot's or an asset card's proposals),
// or in writing-preview candidates the director picks from in the script view; never in a write. These are the rules
// for the ask: where to send it, which job of a kind is the current one, and what its state line says.
export const CREW_KINDS = ['beats', 'camera'];  // the Cinematographer's asks
export const SHOT_CREW_KINDS = ['beats', 'camera', 'appearances'];
export const ASSET_CREW_KINDS = ['description', 'look'];
export const EPISODE_CREW_KINDS = ['adaptation', 'breakdown'];
export const ART_KINDS = ['description', 'look', 'appearances'];
export const ALL_CREW_KINDS = [...SHOT_CREW_KINDS, ...ASSET_CREW_KINDS, ...EPISODE_CREW_KINDS];
export const CREW_NOT_READY = 'DRAMA_CREW_NOT_READY';

const TAIL = {beats: 'beat', camera: 'camera', appearances: 'appearance', description: 'description', look: 'look',
  adaptation: 'adaptation', breakdown: 'breakdown'};
const ENTITY = {sh_: 'shots', as_: 'assets', sc_: 'scenes', ep_: 'episodes'};

// A target id's route base: its prefix says what it is (sh_, as_, sc_, ep_).
export const crewTargetBase = targetId => `/${ENTITY[String(targetId).slice(0, 3)] || 'shots'}/${targetId}`;
export const crewJobPath = (targetId, kind) => `${crewTargetBase(targetId)}/${TAIL[kind] || kind}-proposals`;
export const crewJobsPath = targetId => `${crewTargetBase(targetId)}/crew-jobs`;
export const crewCancelPath = (slug, job) => `/projects/api/${slug}/orchestration/crew-jobs/${job.jobId}/cancel`;
export const crewActive = job => ['queued', 'running'].includes(job?.status);

// The newest job of each kind from GET .../crew-jobs (the server lists them newest first).
export function latestCrewJobs(items = [], kinds = ALL_CREW_KINDS) {
  const latest = {};
  for (const job of Array.isArray(items) ? items : []) if (job && kinds.includes(job.kind) && !latest[job.kind]) latest[job.kind] = job;
  return latest;
}

// The state line of a job: an i18n key under shotProposal, plus what a failed job reports (its failure class or message).
export function crewJobLine(job) {
  if (!job) return null;
  const named = {queued: 'crewQueued', running: 'crewRunning', canceled: 'crewCanceled'}[job.status];
  if (named) return {key: named};
  if (job.status === 'failed') return {key: 'crewFailed', failure: job.failure || '', error: job.error || ''};
  if (Array.isArray(job.result?.candidates)) return {key: job.source === 'rule_fallback' ? 'crewCandidatesFallback' : 'crewCandidates'};
  if (job.result?.unchanged) return {key: 'crewUnchanged'};
  return {key: job.source === 'rule_fallback' ? 'crewFallback' : 'crewProposed'};
}

// Who is working, for the running line: the Cinematographer, Art (on the Screenwriter's profile) or the Screenwriter.
export const crewRunningKey = job => job?.role === 'sheet_ops' ? 'crewRunning' : ART_KINDS.includes(job?.kind) ? 'crewRunningArt' : 'crewRunningWriter';

// The Screenwriter's candidates of a finished job: the crew's (when the model answered) and the rule version. A candidate
// without a preview is the rule breakdown as the script stands: nothing to adopt, Build storyboard does it.
export const crewCandidates = job => job?.status === 'succeeded' && Array.isArray(job.result?.candidates) ? job.result.candidates : [];

// Jobs that finished with a proposal since we last looked: the target's proposals need reloading.
export const newlyProposed = (jobs, seen) => Object.values(jobs).filter(job => job?.status === 'succeeded' && job.result?.proposalIds?.length && !seen.has(job.jobId));

// An asset card's pending proposals (R21): edits of its own Soul Cast row, and new looks proposed for it (a look adds a row,
// so its review group is the new row; the crew target names the card it belongs to). Entries as rowProposals() gives them.
export function assetProposals(proposals, asset) {
  if (!asset?.rowId) return [];
  const looks = (Array.isArray(proposals) ? proposals : [])
    .filter(proposal => isPending(proposal) && proposal.action === 'table_edit' && proposal.target?.crew?.kind === 'look'
      && proposal.target.crew.assetRowId === asset.rowId)
    .flatMap(proposal => {
      const review = proposal.review || proposal.target?.review, groups = review?.groups || [];
      return groups.map(group => ({proposal, group, review, partial: Boolean(review.partial_allowed), size: groups.length}));
    });
  return [...rowProposals(proposals, asset.rowId, asset.tabKey || 'soul-cast'), ...looks];
}
