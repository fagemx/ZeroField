import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import "./review.css";

function ReviewDialog({ proposal, onApply, onDismiss, onClose }) {
  const dialog = useRef(null);
  const review = proposal.review || proposal.target?.review;
  const groups = review?.groups || [];
  const [picked, setPicked] = useState(groups.map((g) => g.index));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const seenVersion = useRef(review?.version);
  useEffect(() => {
    const previous = document.activeElement;
    dialog.current.showModal();
    return () => { if (previous?.isConnected) previous.focus(); };
  }, []);
  useEffect(() => {
    if (seenVersion.current !== review?.version) {
      seenVersion.current = review?.version;
      setPicked([]);
      setError("The proposal changed. Select the changes to accept again.");
    }
  }, [review?.version]);
  const decide = async (dismiss = false) => {
    setBusy(true); setError("");
    try {
      const result = dismiss ? await onDismiss(proposal) : await onApply(proposal, proposal.content,
        review?.partial_allowed ? { groups: picked, review_version: review.version } : {});
      if (result) onClose();
      else setError("Changes were not applied. Review the error and source data, then retry. Your proposal and selection are preserved.");
    } finally { setBusy(false); }
  };
  return createPortal(<dialog ref={dialog} className="proposal-review" aria-labelledby="proposal-review-title"
    onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }}>
    <header><div><span className="review-eyebrow">Review Agent Changes</span><h2 id="proposal-review-title">{proposal.target?.display || "Table Changes"}</h2></div>
      <button type="button" disabled={busy} onClick={onClose} aria-label={"Back to Workspace"}>✕</button></header>
    <div className="review-context"><span>{groups.length}  change groups{review?.source_revision ? ` · source revision ${review.source_revision}` : ""}</span>
      <span>{review?.partial_allowed ? "Accept individual rows. Unselected changes remain pending." : "These changes must be applied together."}</span></div>
    <div className="review-scroll">
      {review?.partial_allowed && <label className="review-all"><input type="checkbox" disabled={busy} checked={picked.length === groups.length}
        onChange={(e) => setPicked(e.target.checked ? groups.map((g) => g.index) : [])} />Select All Changes</label>}
      {groups.map((group) => <section className="review-group" key={group.index}>
        <h3>{review.partial_allowed && <input type="checkbox" disabled={busy} aria-label={`Accept ${group.label}`} checked={picked.includes(group.index)}
          onChange={(e) => setPicked((old) => e.target.checked ? [...old, group.index] : old.filter((i) => i !== group.index))} />}{group.label}</h3>
        <table><thead><tr><th>Column</th><th>Original</th><th>Suggested Change</th></tr></thead>
          <tbody>{group.changes.map((change, index) => <tr key={index}><th>{change.column}</th><td>{change.before || <span className="review-empty">Empty</span>}</td><td className="review-after">{change.after || <span className="review-empty">Clear</span>}</td></tr>)}</tbody></table>
      </section>)}
      {!groups.length && <pre>{proposal.content}</pre>}
    </div>
    {(error || proposal.error) && <p className="review-error" role="alert">{proposal.error || error}</p>}
    <footer><button type="button" disabled={busy} onClick={() => decide(true)}>Dismiss Proposal</button><span />
      <button type="button" disabled={busy} onClick={onClose}>Back</button>
      <button type="button" className="primary" disabled={busy || (review?.partial_allowed && !picked.length)} onClick={() => decide()}>
        {busy ? "Processing…" : review?.partial_allowed ? `Apply Changes ${picked.length}  change groups` : "Apply All Changes Together"}</button></footer>
  </dialog>, document.body);
}

export function TableProposalReview({ proposal, onApply, onDismiss }) {
  const [open, setOpen] = useState(false);
  const review = proposal.review || proposal.target?.review;
  return <div className="pcard"><div className="h">A table proposal is ready for review.</div><div className="where"><b>{proposal.target?.display}</b>
    {review?.groups && <span> · {review.groups.length}  change groups</span>}</div>
    <button type="button" className="btn primary" onClick={() => setOpen(true)}>Review Changes</button>
    {proposal.error && <p role="alert">{proposal.error}</p>}
    {open && <ReviewDialog proposal={proposal} onApply={onApply} onDismiss={onDismiss} onClose={() => setOpen(false)} />}
  </div>;
}
