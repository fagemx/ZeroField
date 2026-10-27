// SPEC_20 R7, R19, R20: asking the crew (the Cinematographer) for a shot's beat sheet or camera. The job runs on the
// server's crew worker and ends in a proposal reviewed on the shot (ShotProposals), never in a write. These are the rules
// for the ask: where to send it, which job of a kind is the current one, and what its state line says.
export const CREW_KINDS = ['beats', 'camera'];
export const CREW_NOT_READY = 'DRAMA_CREW_NOT_READY';

export const crewJobPath = (shotId, kind) => `/shots/${shotId}/${kind === 'camera' ? 'camera' : 'beat'}-proposals`;
export const crewJobsPath = shotId => `/shots/${shotId}/crew-jobs`;
export const crewCancelPath = (slug, job) => `/projects/api/${slug}/orchestration/crew-jobs/${job.jobId}/cancel`;
export const crewActive = job => ['queued', 'running'].includes(job?.status);

// The newest job of each kind from GET .../crew-jobs (the server lists them newest first).
export function latestCrewJobs(items = []) {
  const latest = {};
  for (const job of Array.isArray(items) ? items : []) if (job && CREW_KINDS.includes(job.kind) && !latest[job.kind]) latest[job.kind] = job;
  return latest;
}

// The state line of a job: an i18n key under shotProposal, plus what a failed job reports (its failure class or message).
export function crewJobLine(job) {
  if (!job) return null;
  const named = {queued: 'crewQueued', running: 'crewRunning', canceled: 'crewCanceled'}[job.status];
  if (named) return {key: named};
  if (job.status === 'failed') return {key: 'crewFailed', failure: job.failure || '', error: job.error || ''};
  if (job.result?.unchanged) return {key: 'crewUnchanged'};
  return {key: job.source === 'rule_fallback' ? 'crewFallback' : 'crewProposed'};
}

// Jobs that finished with a proposal since we last looked: the shot's proposals need reloading.
export const newlyProposed = (jobs, seen) => Object.values(jobs).filter(job => job?.status === 'succeeded' && job.result?.proposalIds?.length && !seen.has(job.jobId));
