import { useLocale } from '../i18n/react.jsx';
import { t as uiText } from '../i18n/index.js';
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import "./review.css";
import { reviewColumnLabel, reviewGroupLabel, reviewMedia } from "./reviewLabels.js";

function ReviewValue({ value, empty }) {
  const media = reviewMedia(value);
  if (!media) return value || empty;
  return media.kind === "image" ? <img className="review-thumb" src={media.url} alt={media.label} /> : <span>{media.label}</span>;
}

function ReviewDialog({ proposal, onApply, onDismiss, onClose }) {
  const locale = useLocale();
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
      setError(uiText("tableProposalReview.theProposalChangedSelectTheChangesToAcceptAgain"));
    }
  }, [review?.version]);
  const decide = async (dismiss = false) => {
    setBusy(true); setError("");
    try {
      const result = dismiss ? await onDismiss(proposal) : await onApply(proposal, proposal.content,
        review?.partial_allowed ? { groups: picked, review_version: review.version } : {});
      if (result) onClose();
      else setError(uiText("tableProposalReview.changesWereNotAppliedReviewTheErrorAndSource"));
    } finally { setBusy(false); }
  };
  return createPortal(<dialog ref={dialog} className="proposal-review" aria-labelledby="proposal-review-title"
    onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }}>
    <header><div><span className="review-eyebrow">{uiText("tableProposalReview.reviewAgentChanges")}</span><h2 id="proposal-review-title">{proposal.target?.display || uiText("tableProposalReview.tableChanges")}</h2></div>
      <button type="button" disabled={busy} onClick={onClose} aria-label={uiText("tableProposalReview.backToWorkspace")}>✕</button></header>
    <div className="review-context"><span>{uiText("tableProposalReview.changeGroups", {v0: (groups.length), v1: (review?.source_revision ? ` · source revision ${review.source_revision}` : "")})}</span>
      <span>{review?.partial_allowed ? uiText("tableProposalReview.acceptIndividualRowsUnselectedChangesRemainPending") : uiText("tableProposalReview.theseChangesMustBeAppliedTogether")}</span></div>
    <div className="review-scroll">
      {review?.partial_allowed && <label className="review-all"><input type="checkbox" disabled={busy} checked={picked.length === groups.length}
        onChange={(e) => setPicked(e.target.checked ? groups.map((g) => g.index) : [])} />{uiText("tableProposalReview.selectAllChanges")}</label>}
      {groups.map((group) => <section className="review-group" key={group.index}>
        <h3>{review.partial_allowed && <input type="checkbox" disabled={busy} aria-label={uiText("tableProposalReview.accept", {v0: (reviewGroupLabel(group))})} checked={picked.includes(group.index)}
          onChange={(e) => setPicked((old) => e.target.checked ? [...old, group.index] : old.filter((i) => i !== group.index))} />}{reviewGroupLabel(group)}</h3>
        <table><thead><tr><th>{uiText("tableProposalReview.column")}</th><th>{uiText("tableProposalReview.original")}</th><th>{uiText("tableProposalReview.suggestedChange")}</th></tr></thead>
          <tbody>{group.changes.map((change, index) => <tr key={index}><th>{reviewColumnLabel(change)}</th><td><ReviewValue value={change.before} empty={<span className="review-empty">{uiText("tableProposalReview.empty")}</span>} /></td><td className="review-after"><ReviewValue value={change.after} empty={<span className="review-empty">{uiText("tableProposalReview.clear")}</span>} /></td></tr>)}</tbody></table>
      </section>)}
      {!groups.length && <pre>{proposal.content}</pre>}
    </div>
    {(error || proposal.error) && <p className="review-error" role="alert">{proposal.error || error}</p>}
    <footer><button type="button" disabled={busy} onClick={() => decide(true)}>{uiText("tableProposalReview.dismissProposal")}</button><span />
      <button type="button" disabled={busy} onClick={onClose}>{uiText("tableProposalReview.back")}</button>
      <button type="button" className="primary" disabled={busy || (review?.partial_allowed && !picked.length)} onClick={() => decide()}>
        {busy ? uiText("tableProposalReview.processing") : review?.partial_allowed ? uiText("tableProposalReview.applyChangesChangeGroups", {v0: (picked.length)}) : uiText("tableProposalReview.applyAllChangesTogether")}</button></footer>
  </dialog>, document.body);
}

export function TableProposalReview({ proposal, onApply, onDismiss }) {
  const locale = useLocale();
  const [open, setOpen] = useState(false);
  const review = proposal.review || proposal.target?.review;
  return <div className="pcard"><div className="h">{uiText("tableProposalReview.aTableProposalIsReadyForReview")}</div><div className="where"><b>{proposal.target?.display}</b>
    {review?.groups && <span>{uiText("tableProposalReview.changeGroups2", {v0: (review.groups.length)})}</span>}</div>
    <button type="button" className="btn primary" onClick={() => setOpen(true)}>{uiText("tableProposalReview.reviewChanges")}</button>
    {proposal.error && <p role="alert">{proposal.error}</p>}
    {open && <ReviewDialog proposal={proposal} onApply={onApply} onDismiss={onDismiss} onClose={() => setOpen(false)} />}
  </div>;
}
