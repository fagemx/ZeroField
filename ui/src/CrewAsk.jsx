import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocale } from './i18n/react.jsx';
import { t } from './i18n/index.js';
import { api } from './api.js';
import { storyRequest } from './storyModel.js';
import { providerFailureText } from './assistant/providerFailures.js';
import { readinessLines } from './assistant/AgentBoard.jsx';
import { CREW_NOT_READY, SHOT_CREW_KINDS, crewActive, crewCancelPath, crewCandidates, crewJobLine, crewJobPath, crewJobsPath,
  crewRunningKey, latestCrewJobs, newlyProposed } from './crewJobModel.js';

const LABEL = {beats: 'shotProposal.askBeats', camera: 'shotProposal.askCamera', appearances: 'shotProposal.askAppearances',
  description: 'shotProposal.askDescription', look: 'shotProposal.askLook', adaptation: 'shotProposal.askAdaptation',
  breakdown: 'shotProposal.askBreakdown'};
const lineText = (line, job) => line.key === 'crewRunning' ? t('shotProposal.' + crewRunningKey(job))
  : t('shotProposal.' + line.key, line.key === 'crewFailed' ? {v0: providerFailureText(line.failure) || line.error} : {});
const impactText = impact => impact ? t('shotProposal.candidateImpact', {count: impact.shotCount, added: impact.newShots}) : '';

// SPEC_20 R7, R19-R23: ask the crew for a planning job on one target. On a shot (shotId): the Cinematographer's beat sheet
// and camera, and who is in the shot; on an asset card (targetId as_…): Art's description and a new look; on an episode
// (targetId ep_…): the Screenwriter's adaptation and breakdown. Proposals arrive where the target's proposals are shown;
// the Screenwriter's candidates are listed here and open in the script view (onCandidate). Every job also shows on the
// crew board, where it can be canceled too. noteKinds get the note typed above the buttons (what the look is, say).
export function CrewAsk({slug, shotId, targetId, kinds = SHOT_CREW_KINDS, noteKinds = [], title = 'shotProposal.askCrew',
  hint = 'shotProposal.askCrewHint', writable, disabled, onProposed, onCandidate}) {
  useLocale();
  const target = targetId || shotId;
  const [jobs, setJobs] = useState({}), [busy, setBusy] = useState(''), [error, setError] = useState(null), [note, setNote] = useState('');
  const seen = useRef(new Set()), current = useRef(target);
  current.current = target;
  const load = useCallback(async (initial = false) => {
    const data = await storyRequest(crewJobsPath(target));
    if (current.current !== target) return;
    const latest = latestCrewJobs(data.items, kinds);
    if (initial) for (const job of data.items || []) seen.current.add(job.jobId);
    setJobs(latest);
  }, [target, kinds.join(',')]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    setJobs({}); setError(null); setNote('');
    load(true).catch(() => {});
  }, [load]);
  useEffect(() => {
    if (!Object.values(jobs).some(crewActive)) return undefined;
    const timer = setTimeout(() => load().catch(() => {}), 1500);
    return () => clearTimeout(timer);
  }, [jobs, load]);
  useEffect(() => {
    const fresh = newlyProposed(jobs, seen.current);
    for (const job of fresh) seen.current.add(job.jobId);
    if (fresh.length) onProposed?.();
  }, [jobs, onProposed]);
  if (!writable || !target) return null;
  const ask = async kind => {
    setBusy(kind); setError(null);
    try {
      const body = noteKinds.includes(kind) && note.trim() ? {note: note.trim()} : {};
      const job = await storyRequest(crewJobPath(target, kind), 'POST', body);
      setJobs(old => ({...old, [kind]: job}));
    } catch (failure) {
      setError(failure.code === CREW_NOT_READY ? {text: t('shotProposal.crewNotReady'), lines: readinessLines({ready: false, blockers: failure.details?.blockers || []})}
        : {text: failure.message, lines: []});
    } finally { setBusy(''); }
  };
  const cancel = async job => {
    try { await api.post(crewCancelPath(slug, job), {}); await load(); } catch (failure) { setError({text: failure.message, lines: []}); }
  };
  return <section className="crew-ask" aria-label={t(title)}>
    <header><b>{t(title)}</b><small>{t(hint)}</small></header>
    {noteKinds.some(kind => kinds.includes(kind)) && <label className="crew-ask-note"><span>{t('shotProposal.crewNote')}</span>
      <input type="text" value={note} maxLength={1000} placeholder={t('shotProposal.crewNotePlaceholder')} disabled={disabled}
        onChange={event => setNote(event.target.value)}/></label>}
    {kinds.map(kind => {
      const job = jobs[kind], line = crewJobLine(job), active = crewActive(job), candidates = crewCandidates(job);
      return <div key={kind} className="crew-ask-row">
        <button type="button" disabled={disabled || Boolean(busy) || active} onClick={() => ask(kind)}>{t(LABEL[kind] || kind)}</button>
        {line && <small className={'crew-ask-state ' + job.status} role="status">{lineText(line, job)}</small>}
        {active && <button type="button" className="quiet" onClick={() => cancel(job)}>{t('shotProposal.crewCancel')}</button>}
        {candidates.length > 0 && <ul className="crew-ask-candidates">{candidates.map((candidate, index) => <li key={index}>
          {candidate.previewId || candidate.branchId
            ? <button type="button" className="quiet" disabled={!onCandidate} onClick={() => onCandidate?.(candidate)}>
              {t(candidate.source === 'model' ? 'shotProposal.candidateCrew' : 'shotProposal.candidateRule')}</button>
            : <span>{t(candidate.source === 'model' ? 'shotProposal.candidateCrewAsIs' : 'shotProposal.candidateRuleAsIs')}</span>}
          {candidate.impact && <small>{impactText(candidate.impact)}</small>}
        </li>)}</ul>}
      </div>;
    })}
    {error && <div className="shot-proposal-error" role="alert"><p>{error.text}</p>
      {error.lines.length > 0 && <ul>{error.lines.map(item => <li key={item.id}>{item.text}{item.command && <> <code>{item.command}</code></>}</li>)}</ul>}</div>}
  </section>;
}
