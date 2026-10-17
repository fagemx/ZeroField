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
      setError("待核對項目已更新，請重新選取要接受的修改。");
    }
  }, [review?.version]);
  const decide = async (dismiss = false) => {
    setBusy(true); setError("");
    try {
      const result = dismiss ? await onDismiss(proposal) : await onApply(proposal, proposal.content,
        review?.partial_allowed ? { groups: picked, review_version: review.version } : {});
      if (result) onClose();
      else setError("這次尚未寫回。請檢查錯誤訊息；原提案與選取仍保留，可返回資料確認後再試。");
    } finally { setBusy(false); }
  };
  return createPortal(<dialog ref={dialog} className="proposal-review" aria-labelledby="proposal-review-title"
    onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }}>
    <header><div><span className="review-eyebrow">核對代理修改</span><h2 id="proposal-review-title">{proposal.target?.display || "表格修改"}</h2></div>
      <button type="button" disabled={busy} onClick={onClose} aria-label="返回工作區">✕</button></header>
    <div className="review-context"><span>{groups.length} 組修改{review?.source_revision ? ` · 來源版本 ${review.source_revision}` : ""}</span>
      <span>{review?.partial_allowed ? "可逐列接受；未勾選的修改會保留" : "這組修改需一起寫回"}</span></div>
    <div className="review-scroll">
      {review?.partial_allowed && <label className="review-all"><input type="checkbox" disabled={busy} checked={picked.length === groups.length}
        onChange={(e) => setPicked(e.target.checked ? groups.map((g) => g.index) : [])} />全選修改</label>}
      {groups.map((group) => <section className="review-group" key={group.index}>
        <h3>{review.partial_allowed && <input type="checkbox" disabled={busy} aria-label={`接受 ${group.label}`} checked={picked.includes(group.index)}
          onChange={(e) => setPicked((old) => e.target.checked ? [...old, group.index] : old.filter((i) => i !== group.index))} />}{group.label}</h3>
        <table><thead><tr><th>欄位</th><th>原內容</th><th>建議修改</th></tr></thead>
          <tbody>{group.changes.map((change, index) => <tr key={index}><th>{change.column}</th><td>{change.before || <span className="review-empty">空白</span>}</td><td className="review-after">{change.after || <span className="review-empty">清空</span>}</td></tr>)}</tbody></table>
      </section>)}
      {!groups.length && <pre>{proposal.content}</pre>}
    </div>
    {(error || proposal.error) && <p className="review-error" role="alert">{proposal.error || error}</p>}
    <footer><button type="button" disabled={busy} onClick={() => decide(true)}>不採用此提案</button><span />
      <button type="button" disabled={busy} onClick={onClose}>返回</button>
      <button type="button" className="primary" disabled={busy || (review?.partial_allowed && !picked.length)} onClick={() => decide()}>
        {busy ? "處理中…" : review?.partial_allowed ? `確認寫回 ${picked.length} 組修改` : "確認整組寫回"}</button></footer>
  </dialog>, document.body);
}

export function TableProposalReview({ proposal, onApply, onDismiss }) {
  const [open, setOpen] = useState(false);
  const review = proposal.review || proposal.target?.review;
  return <div className="pcard"><div className="h">有一份表格修改待核對</div><div className="where"><b>{proposal.target?.display}</b>
    {review?.groups && <span> · {review.groups.length} 組修改</span>}</div>
    <button type="button" className="btn primary" onClick={() => setOpen(true)}>核對修改</button>
    {proposal.error && <p role="alert">{proposal.error}</p>}
    {open && <ReviewDialog proposal={proposal} onApply={onApply} onDismiss={onDismiss} onClose={() => setOpen(false)} />}
  </div>;
}
