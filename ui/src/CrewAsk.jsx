import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocale } from './i18n/react.jsx';
import { t } from './i18n/index.js';
import { api } from './api.js';
import { storyRequest } from './storyModel.js';
import { providerFailureText } from './assistant/providerFailures.js';
import { readinessLines } from './assistant/AgentBoard.jsx';
import { CREW_KINDS, CREW_NOT_READY, crewActive, crewCancelPath, crewJobLine, crewJobPath, crewJobsPath, latestCrewJobs, newlyProposed } from './crewJobModel.js';

const LABEL = {beats: 'shotProposal.askBeats', camera: 'shotProposal.askCamera'};
const lineText = line => t('shotProposal.' + line.key, line.key === 'crewFailed' ? {v0: providerFailureText(line.failure) || line.error} : {});

// SPEC_20 R7, R19, R20: ask the Cinematographer for this shot's beat sheet or camera. The answer arrives as a proposal in
// the shot's proposals above; the job also shows on the crew board, where it can be canceled too.
export function CrewAsk({slug, shotId, writable, disabled, onProposed}) {
  useLocale();
  const [jobs, setJobs] = useState({}), [busy, setBusy] = useState(''), [error, setError] = useState(null);
  const seen = useRef(new Set()), current = useRef(shotId);
  current.current = shotId;
  const load = useCallback(async (initial = false) => {
    const data = await storyRequest(crewJobsPath(shotId));
    if (current.current !== shotId) return;
    const latest = latestCrewJobs(data.items);
    if (initial) for (const job of data.items || []) seen.current.add(job.jobId);
    setJobs(latest);
  }, [shotId]);
  useEffect(() => {
    setJobs({}); setError(null);
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
  if (!writable) return null;
  const ask = async kind => {
    setBusy(kind); setError(null);
    try {
      const job = await storyRequest(crewJobPath(shotId, kind), 'POST', {});
      setJobs(old => ({...old, [kind]: job}));
    } catch (failure) {
      setError(failure.code === CREW_NOT_READY ? {text: t('shotProposal.crewNotReady'), lines: readinessLines({ready: false, blockers: failure.details?.blockers || []})}
        : {text: failure.message, lines: []});
    } finally { setBusy(''); }
  };
  const cancel = async job => {
    try { await api.post(crewCancelPath(slug, job), {}); await load(); } catch (failure) { setError({text: failure.message, lines: []}); }
  };
  return <section className="crew-ask" aria-label={t('shotProposal.askCrew')}>
    <header><b>{t('shotProposal.askCrew')}</b><small>{t('shotProposal.askCrewHint')}</small></header>
    {CREW_KINDS.map(kind => {
      const job = jobs[kind], line = crewJobLine(job), active = crewActive(job);
      return <div key={kind} className="crew-ask-row">
        <button type="button" disabled={disabled || Boolean(busy) || active} onClick={() => ask(kind)}>{t(LABEL[kind])}</button>
        {line && <small className={'crew-ask-state ' + job.status} role="status">{lineText(line)}</small>}
        {active && <button type="button" className="quiet" onClick={() => cancel(job)}>{t('shotProposal.crewCancel')}</button>}
      </div>;
    })}
    {error && <div className="shot-proposal-error" role="alert"><p>{error.text}</p>
      {error.lines.length > 0 && <ul>{error.lines.map(item => <li key={item.id}>{item.text}{item.command && <> <code>{item.command}</code></>}</li>)}</ul>}</div>}
  </section>;
}
