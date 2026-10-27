import { useEffect, useState } from 'react';
import { useLocale } from '../i18n/react.jsx';
import { t } from '../i18n/index.js';
import { storyRequest } from '../storyModel.js';

// SPEC_19 R17 and R18 (3.7, D6, D8): the seams of the film. A seam is the join between two neighbouring shots; its dot sits in the
// gap of the progress bar (and of the film window's strip): green holds, yellow has problems, grey not checked or not checkable yet,
// a hollow dot is waiting in the grader's queue and a red ring is a check that could not run. A seam shows its check (score, the
// problems, the two frames side by side). The data is GET /episodes/{id}/cuts; POST /episodes/{id}/cut-checks queues checks, and a
// reader never sees that action. A check is information only: it never blocks adopting or exporting (fixed decision 13).
// Playing a seam goes through the player that is already on the page (seamPlaylist() items); nothing here owns a <video>.

const POLL_MS = 4000;  // while a check is queued, how often the cuts are read again

// GET /episodes/{id}/cuts, read again when `version` changes (the caller passes what changes on a new shot or an adoption) and
// every few seconds while a check is queued. {items, error, reload}.
export function useEpisodeCuts(epId, version) {
  const [state, setState] = useState({epId: null, items: [], error: ''});
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    if (!epId) return undefined;
    let alive = true;
    storyRequest(`/episodes/${epId}/cuts`).then(data => {if (alive) setState({epId, items: Array.isArray(data?.items) ? data.items : [], error: ''});},
      error => {if (alive) setState(old => ({epId, items: old.epId === epId ? old.items : [], error: error.message}));});
    return () => {alive = false;};
  }, [epId, version, nonce]);
  const items = state.epId === epId ? state.items : [];
  const queued = items.some(cut => cut?.check?.state === 'queued');
  useEffect(() => {
    if (!queued) return undefined;
    const timer = setTimeout(() => setNonce(n => n + 1), POLL_MS);
    return () => clearTimeout(timer);
  }, [queued, state]);
  return {items, error: state.epId === epId ? state.error : '', reload: () => setNonce(n => n + 1)};
}

// POST /episodes/{id}/cut-checks: pairs [[fromShotId, toShotId]] or nothing (every checkable cut not checked yet).
export const queueCutChecks = (epId, pairs = null) => storyRequest(`/episodes/${epId}/cut-checks`, 'POST', pairs ? {pairs} : {});

// What a seam's state reads as: grey splits into "not checked" and "can't check yet" (a side has no adopted take of this production).
export const seamLabelState = seam => seam?.state === 'none' && seam?.cut && !seam.checkable ? 'blocked' : seam?.state || 'none';
const seamTitle = seam => t('seam.title', {from: seam.fromShotIndex, to: seam.toShotIndex});

// One seam in a gap: a dot to press. It plays the seam and shows its check.
export function SeamDot({seam, active = false, onPick}) {
  useLocale();
  const state = seamLabelState(seam);
  const label = t('seam.dot', {from: seam.fromShotIndex, to: seam.toShotIndex, state: t('seam.state_' + state)});
  return <button type="button" className={'seam-dot is-' + seam.state + (active ? ' is-active' : '')} aria-pressed={active} aria-label={label} title={label}
    onClick={event => {event.stopPropagation(); onPick?.(seam);}}/>;
}

// "Whole / Cuts only": what "Play around" and the film window play.
export function PlayModeToggle({mode = 'whole', onMode}) {
  useLocale();
  return <div className="studio-segmented small film-mode" role="group" aria-label={t('seam.mode')}>
    {['whole', 'seams'].map(value => <button key={value} type="button" aria-pressed={mode === value} onClick={() => onMode?.(value)}>{t('seam.mode_' + value)}</button>)}
  </div>;
}

// The check of one seam: its state and score, the problems found, the feedback and the two frames that were compared.
//   onCheck: queue this one seam (writers only; shown when it can be checked and is not already waiting).
export function SeamDetail({seam, writable = false, busy = false, error = '', onCheck}) {
  useLocale();
  if (!seam) return null;
  const state = seamLabelState(seam), check = seam.check || {}, done = seam.state === 'pass' || seam.state === 'issue';
  const shotLabel = shotId => (shotId === seam.fromShotId ? seam.fromShotIndex : shotId === seam.toShotId ? seam.toShotIndex : shotId);
  const issues = Array.isArray(check.issues) ? check.issues.filter(Boolean) : [];
  return <section className={'seam-detail is-' + seam.state} aria-label={seamTitle(seam)}>
    <header><i className={'seam-mark is-' + seam.state} aria-hidden="true"/><b>{seamTitle(seam)}</b>
      <span className="seam-state">{t('seam.state_' + state)}</span>{done && Number.isFinite(check.score) && <span className="num seam-score">{t('seam.score', {score: check.score})}</span>}
      <span className="spacer"/>
      {writable && onCheck && seam.checkable && seam.state !== 'queued' && <button type="button" className="seam-check" disabled={busy} onClick={() => onCheck(seam)}>
        {t(seam.state === 'none' ? 'seam.checkOne' : 'seam.checkAgain')}</button>}
    </header>
    {done && (issues.length ? <ul className="seam-issues">{issues.map((issue, index) => <li key={index}>{issue}</li>)}</ul> : <p className="seam-note">{t('seam.noIssues')}</p>)}
    {done && check.feedback && <p className="seam-note">{check.feedback}</p>}
    {done && check.frameSheetUrl && <img className="seam-frames" src={check.frameSheetUrl} alt={t('seam.frames', {from: seam.fromShotIndex, to: seam.toShotIndex})} loading="lazy"/>}
    {seam.state === 'failed' && <p className="seam-note">{t('seam.failed', {message: check.error || ''})}</p>}
    {seam.state === 'queued' && <p className="seam-note">{t('seam.waiting')}</p>}
    {seam.state === 'none' && (seam.blockedBy.length
      ? seam.blockedBy.map(block => <p key={block.shotId + block.reason} className="seam-note">{t(['not_adopted', 'external_take'].includes(block.reason) ? 'seam.blocked_' + block.reason : 'seam.blocked', {shot: shotLabel(block.shotId)})}</p>)
      : <p className="seam-note">{t('seam.noCheck')}</p>)}
    {error && <p className="sheet-save-error" role="alert">{error}</p>}
  </section>;
}

// The film window's "Check cuts" (outlined, never the primary action): queues every checkable cut not checked yet, then says how many.
// Readers do not get it (the caller leaves it out).
export function CheckCutsButton({epId, seams = [], onQueued}) {
  useLocale();
  const [busy, setBusy] = useState(false), [note, setNote] = useState(''), [error, setError] = useState('');
  const checked = seams.filter(seam => seam.state === 'pass' || seam.state === 'issue').length;
  const issues = seams.filter(seam => seam.state === 'issue').length;
  const run = async () => {
    setBusy(true); setError(''); setNote('');
    try {
      const result = await queueCutChecks(epId);
      const skipped = Array.isArray(result?.skipped) ? result.skipped.length : 0;
      setNote([result?.queued ? t('seam.queued', {count: result.queued}) : t('seam.nothing'), skipped && t('seam.skipped', {count: skipped})].filter(Boolean).join(' · '));
      onQueued?.(result);
    } catch (failure) {setError(failure.message);}
    finally {setBusy(false);}
  };
  return <span className="seam-check-all">
    <button type="button" className="seam-check" disabled={busy || !seams.length} onClick={run}>{busy ? t('seam.queuing') : t('seam.checkAll')}</button>
    <span className="studio-note" role="status">{note || (seams.length ? t('seam.summary', {checked, total: seams.length, issues}) : '')}</span>
    {error && <span className="canvas-error" role="alert">{error}</span>}
  </span>;
}
