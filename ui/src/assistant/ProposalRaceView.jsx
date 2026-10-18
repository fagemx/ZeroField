import { useLocale } from '../i18n/react.jsx';
import { t as uiText } from '../i18n/index.js';
import { useRef, useState } from 'react';
import { Dialog } from '../Dialog.jsx';
import { proposalChanges, raceSelectionPayload } from './orchestrationModel.js';
import './orchestration.css';
import { mediaOf } from '../sheetModel.js';

const labels = { get queued() { return uiText("proposalRaceView.queued"); }, get running() { return uiText("proposalRaceView.running"); }, get awaiting_gate() { return uiText("proposalRaceView.readyForReview"); }, get failed() { return uiText("proposalRaceView.failed"); }, get timeout() { return uiText("proposalRaceView.timedOut"); }, get canceled() { return uiText("proposalRaceView.canceled"); } };

function DiffValue({ value }) {
  const locale = useLocale();
  const media = mediaOf(value);
  if (media?.kind === 'image') return <img className="race-image" src={media.url} alt={uiText("proposalRaceView.candidateImage")} />;
  if (media) return <p><a href={media.url} download>{media.kind === 'video' ? uiText("proposalRaceView.downloadVideoAttachment") : uiText("proposalRaceView.downloadAudioAttachment")}</a></p>;
  return <p>{value || uiText("proposalRaceView.empty")}</p>;
}

export function ProposalRaceView({ gate, onSelect, onClose, returnFocusRef }) {
  const locale = useLocale();
  const [busy, setBusy] = useState(null), [error, setError] = useState('');
  const requestId = useRef(crypto.randomUUID());
  const select = async proposal => {
    setBusy(proposal.id); setError('');
    try { await onSelect(raceSelectionPayload(gate, proposal.id, requestId.current)); onClose(); }
    catch (e) { setError(e.message); }
    finally { setBusy(null); }
  };
  const candidates = gate.candidates?.length ? gate.candidates : gate.proposals.map(proposal => ({ agent_key: proposal.agent_key, status: 'awaiting_gate' }));
  return <Dialog title={uiText("proposalRaceView.compareCandidates")} className="race-dialog" cancelLabel={uiText("proposalRaceView.backToBoard")} hideConfirm onConfirm={() => {}} onCancel={onClose} returnFocusRef={returnFocusRef}>
    <p className="race-intro">{uiText("proposalRaceView.onlyTheSelectedCandidateWillBeAppliedOtherCandidates", {v0: (gate.title)})}</p>
    {gate.stale && <p className="error" role="status">{uiText("proposalRaceView.theseCandidatesHaveAlreadyBeenHandledReturnToThe")}</p>}
    {error && <p className="error" role="alert">{error}</p>}
    <div className="race-columns">{candidates.map(candidate => {
      const proposal = gate.proposals.find(item => item.agent_key === candidate.agent_key);
      return <article className="race-candidate" key={candidate.agent_key}>
        <header><h4>{candidate.icon || '✦'} {candidate.display_name || candidate.agent_key}</h4><small>{candidate.model || uiText("proposalRaceView.modelNotReported")} · {labels[candidate.status] || candidate.status}</small></header>
        {proposal ? <><div className="race-differences">{proposalChanges(proposal).map((group, index) => <section key={index}>
          <strong>{group.label}</strong>{group.changes.map((change, at) => <div className="race-change" key={at}>
            <small>{change.column}</small><div><span>{uiText("proposalRaceView.before")}</span><DiffValue value={change.before} /></div><div className="race-after"><span>{uiText("proposalRaceView.after")}</span><DiffValue value={change.after} /></div>
          </div>)}
        </section>)}</div><button type="button" className="primary" disabled={busy !== null || gate.stale} onClick={() => select(proposal)}>
          {busy === proposal.id ? uiText("proposalRaceView.applying") : uiText("proposalRaceView.selectThisVersion")}</button></> : <p className="race-pending">{candidate.error || (['failed', 'timeout', 'canceled'].includes(candidate.status) ? uiText("proposalRaceView.thisCandidateDidNotCompleteYouCanSelectAnother") : uiText("proposalRaceView.candidatesWillAppearHereWhenReady"))}</p>}
      </article>;
    })}</div>
  </Dialog>;
}
