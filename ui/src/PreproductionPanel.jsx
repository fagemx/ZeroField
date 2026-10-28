import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocale } from './i18n/react.jsx';
import { t } from './i18n/index.js';
import { api } from './api.js';
import { usePolling } from './polling.js';
import { storyRequest } from './storyModel.js';
import { readinessLines } from './assistant/AgentBoard.jsx';
import { cardDismissed, dismissCard, flowActive, flowCancelPath, flowLine, lockSummary, pollDelay, preproductionPath,
  showPreproductionCard, stageRows } from './preproductionModel.js';

const when = at => {try {return new Date(at).toLocaleString(undefined, {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'});} catch {return at || '';}};
const lineText = line => {
  if (!line) return '';
  const params = {...line.params};
  if (line.stage) params.stage = t('preproduction.stage_' + line.stage);
  if (line.lock) params.lock = t('preproduction.lock_' + line.lock);
  return t('preproduction.' + line.key, params);
};

// SPEC_20 R24, R25: the crew's pre-production of one episode. Story & World shows the whole flow: the four stages in order,
// the lock between each (who set it and when, or what the next one will cover, with the button only for the director or
// the showrunner), what the crew is doing now, why it stopped, and cancel. The Shot Stage shows it compactly: after the
// storyboard is built, the "Let the crew pre-produce" card, then one line of where the flow stands. initial is for a
// first paint with data already in hand (tests, a server render); otherwise the panel reads it.
export function PreproductionPanel({slug, epId, writable, compact = false, shots = 0, initial = null}) {
  useLocale();
  const [state, setState] = useState(initial), [busy, setBusy] = useState(''), [error, setError] = useState(null);
  const [dismissed, setDismissed] = useState(() => cardDismissed(epId));
  const current = useRef(epId);
  current.current = epId;
  const load = useCallback(async () => {
    const data = await storyRequest(preproductionPath(epId));
    if (current.current === epId) setState(data);
  }, [epId]);
  useEffect(() => {
    if (!epId) return;
    setError(null); setDismissed(cardDismissed(epId));
    load().catch(failure => setError({text: t('preproduction.loadFailed', {v0: failure.message}), lines: []}));
  }, [epId, load]);
  // A failed load only slows the next try (see polling.js); the loop ends when the flow is no longer active.
  usePolling(load, state ? pollDelay(state.flow) : null);
  if (!epId || !state) return null;
  const flow = state.flow, active = flowActive(flow);
  const act = async (name, action) => {
    setBusy(name); setError(null);
    try { const data = await action(); if (data?.flow !== undefined && current.current === epId) setState(data); else await load(); }
    catch (failure) {
      const lines = failure.details?.flow?.stop?.changed?.map((text, index) => ({id: index, text})) || [];
      setError({text: failure.message, lines});
      await load().catch(() => {});
    } finally { setBusy(''); }
  };
  const start = scriptFinal => act('start', () => storyRequest(preproductionPath(epId), 'POST', scriptFinal ? {scriptFinal: true} : {}));
  const lock = next => act('lock', () => storyRequest(preproductionPath(epId, 'locks'), 'POST', {lock: next.lock, hash: next.hash}));
  const resume = () => act('resume', () => storyRequest(preproductionPath(epId, 'resumptions'), 'POST', {}));
  const cancel = () => act('cancel', async () => {await api.post(flowCancelPath(slug, flow), {}); return null;});
  const card = showPreproductionCard({state, shots, writable, dismissed});
  const errorBox = error && <div className="shot-proposal-error" role="alert"><p>{error.text}</p>
    {error.lines.length > 0 && <ul>{error.lines.map(item => <li key={item.id}>{item.text}</li>)}</ul>}</div>;

  if (compact) {
    if (card) return <section className="crew-flow crew-flow-card" aria-label={t('preproduction.cardTitle')}>
      <header><b>{t('preproduction.cardTitle')}</b><small>{t('preproduction.cardHint')}</small></header>
      <div className="crew-flow-actions">
        <button type="button" className="apply" disabled={Boolean(busy)} onClick={() => start(false)}>{t('preproduction.start')}</button>
        <button type="button" className="quiet" onClick={() => {dismissCard(epId); setDismissed(true);}}>{t('preproduction.notNow')}</button>
      </div>{errorBox}</section>;
    if (!active) return null;
    return <section className="crew-flow crew-flow-compact" aria-label={t('preproduction.title')}>
      <p className={'crew-flow-line ' + flow.status} role="status"><b>{t('preproduction.title')}</b> {lineText(flowLine(flow))}</p>
      {flow.status === 'waiting' && <small>{t('preproduction.compactLocks')}</small>}
    </section>;
  }

  const rows = stageRows(state);
  const line = flowLine(flow);
  return <section className="crew-flow" aria-label={t('preproduction.title')}>
    <header><b>{t('preproduction.title')}</b><small>{t('preproduction.hint')}</small></header>
    {flow && <p className={'crew-flow-line ' + flow.status} role="status">{lineText(line)}</p>}
    {flow?.status === 'blocked' && flow.blocked?.code === 'not_ready' && <ul className="crew-flow-reasons">
      {readinessLines({ready: false, blockers: flow.blocked.blockers || []}).map(item => <li key={item.id}>{item.text}{item.command && <> <code>{item.command}</code></>}</li>)}</ul>}
    {flow?.status === 'stopped' && <>
      {flow.stop?.changed?.length > 0 && <ul className="crew-flow-reasons">{flow.stop.changed.map((text, index) => <li key={index}>{text}</li>)}</ul>}
      {flow.stop?.staleProposals?.length > 0 && <small className="crew-flow-note">{t('preproduction.staleProposals', {count: flow.stop.staleProposals.length})}</small>}</>}
    {rows.length > 0 && <ol className="crew-flow-stages">{rows.map(row => <li key={row.key} className={'crew-flow-stage ' + row.status + (row.current ? ' current' : '')}>
      {row.gate && <LockRow row={row} canLock={state.canLock} writable={writable} busy={busy} onLock={lock}/>}
      <div className="crew-flow-stage-head"><b>{t('preproduction.stage_' + row.key)}</b>
        <span className={'crew-flow-chip ' + row.status}>{t('preproduction.status_' + row.status)}</span></div>
      <small>{t('preproduction.stageDo_' + row.key)}{row.counts?.total > 0 && <> · {t('preproduction.counts', {finished: row.counts.total - row.counts.queued - row.counts.running, total: row.counts.total})}</>}
        {row.counts?.proposals > 0 && <> · {t('preproduction.proposals', {count: row.counts.proposals})}</>}
        {row.counts?.fallback > 0 && <> · {t('preproduction.fallbacks', {count: row.counts.fallback})}</>}</small>
      {row.active.length > 0 && <ul className="crew-flow-jobs">{row.active.map(job => <li key={job.jobId}>
        {t('preproduction.job_' + job.kind)} · {job.targetLabel} <small>{t('preproduction.jobStatus_' + job.status)}</small></li>)}</ul>}
      {row.status !== 'pending' && row.skipped?.length > 0 && <details className="crew-flow-skipped"><summary>{t('preproduction.skippedCount', {count: row.skipped.length})}</summary>
        <ul>{row.skipped.map((item, index) => <li key={index}>{t('preproduction.job_' + item.kind)}: {item.reason}</li>)}</ul></details>}
    </li>)}</ol>}
    <div className="crew-flow-actions">
      {flow?.status === 'blocked' && writable && <button type="button" disabled={Boolean(busy)} onClick={resume}>{t('preproduction.tryAgain')}</button>}
      {active && flow.canCancel && writable && <button type="button" className="quiet" disabled={Boolean(busy)} onClick={cancel}>{t('preproduction.cancel')}</button>}
      {!active && state.canStart && writable && <>
        <button type="button" className="apply" disabled={Boolean(busy)} onClick={() => start(false)}>{t(flow ? 'preproduction.startAgain' : 'preproduction.start')}</button>
        <button type="button" disabled={Boolean(busy)} onClick={() => start(true)}>{t('preproduction.startFinal')}</button></>}
    </div>
    {errorBox}
  </section>;
}

function LockRow({row, canLock, writable, busy, onLock}) {
  if (row.held) return <p className="crew-flow-lock held">{t('preproduction.lock_' + row.gate)} · {t('preproduction.lockedBy', {name: row.held.byName || '—', time: when(row.held.at)})}</p>;
  if (!row.asking) return <p className="crew-flow-lock">{t('preproduction.lock_' + row.gate)}</p>;
  const summary = lockSummary(row.next);
  return <div className="crew-flow-lock asking">
    <p><b>{t('preproduction.lock_' + row.gate)}</b>{summary && <> · {t('preproduction.' + summary.key, summary.params)}</>}</p>
    {summary?.items?.length > 0 && <small>{summary.items.join(' · ')}</small>}
    {row.next?.pendingProposals > 0 && <small className="crew-flow-note">{t('preproduction.lockPending', {count: row.next.pendingProposals})}</small>}
    {row.next?.problem ? <small className="crew-flow-note">{row.next.problem}</small>
      : canLock && writable ? <button type="button" className="apply" disabled={Boolean(busy)} onClick={() => onLock(row.next)}>{t('preproduction.lockAction_' + row.gate)}</button>
        : <small>{t('preproduction.lockWaitsDirector')}</small>}
  </div>;
}
