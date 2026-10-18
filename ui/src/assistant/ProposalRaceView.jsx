import { useRef, useState } from 'react';
import { Dialog } from '../Dialog.jsx';
import { proposalChanges, raceSelectionPayload } from './orchestrationModel.js';
import './orchestration.css';
import { mediaOf } from '../sheetModel.js';

const labels = { queued: "Queued", running: "Running", awaiting_gate: "Ready for Review", failed: "Failed", timeout: "Timed Out", canceled: "Canceled" };

function DiffValue({ value }) {
  const media = mediaOf(value);
  if (media?.kind === 'image') return <img className="race-image" src={media.url} alt={"Candidate Image"} />;
  if (media) return <p><a href={media.url} download>{media.kind === 'video' ? "Download Video Attachment" : "Download Audio Attachment"}</a></p>;
  return <p>{value || "(empty)"}</p>;
}

export function ProposalRaceView({ gate, onSelect, onClose, returnFocusRef }) {
  const [busy, setBusy] = useState(null), [error, setError] = useState('');
  const requestId = useRef(crypto.randomUUID());
  const select = async proposal => {
    setBusy(proposal.id); setError('');
    try { await onSelect(raceSelectionPayload(gate, proposal.id, requestId.current)); onClose(); }
    catch (e) { setError(e.message); }
    finally { setBusy(null); }
  };
  const candidates = gate.candidates?.length ? gate.candidates : gate.proposals.map(proposal => ({ agent_key: proposal.agent_key, status: 'awaiting_gate' }));
  return <Dialog title={"Compare Candidates"} className="race-dialog" cancelLabel={"Back to Agent Board"} hideConfirm onConfirm={() => {}} onCancel={onClose} returnFocusRef={returnFocusRef}>
    <p className="race-intro">{gate.title}. Only the selected candidate will be applied; other candidates will be dismissed.</p>
    {gate.stale && <p className="error" role="status">These candidates have already been handled. Return to the board for the latest result.</p>}
    {error && <p className="error" role="alert">{error}</p>}
    <div className="race-columns">{candidates.map(candidate => {
      const proposal = gate.proposals.find(item => item.agent_key === candidate.agent_key);
      return <article className="race-candidate" key={candidate.agent_key}>
        <header><h4>{candidate.icon || '✦'} {candidate.display_name || candidate.agent_key}</h4><small>{candidate.model || "Model not reported"} · {labels[candidate.status] || candidate.status}</small></header>
        {proposal ? <><div className="race-differences">{proposalChanges(proposal).map((group, index) => <section key={index}>
          <strong>{group.label}</strong>{group.changes.map((change, at) => <div className="race-change" key={at}>
            <small>{change.column}</small><div><span>Before</span><DiffValue value={change.before} /></div><div className="race-after"><span>After</span><DiffValue value={change.after} /></div>
          </div>)}
        </section>)}</div><button type="button" className="primary" disabled={busy !== null || gate.stale} onClick={() => select(proposal)}>
          {busy === proposal.id ? "Applying…" : "✓ Select This Version"}</button></> : <p className="race-pending">{candidate.error || (['failed', 'timeout', 'canceled'].includes(candidate.status) ? "This candidate did not complete. You can select another completed version." : "Candidates will appear here when ready.")}</p>}
      </article>;
    })}</div>
  </Dialog>;
}
