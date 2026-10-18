import { useEffect, useRef, useState } from 'react';
import { TableProposalReview } from './TableProposalReview.jsx';
import { ProposalRaceView } from './ProposalRaceView.jsx';
import { groupBoardItems } from './orchestrationModel.js';
import './orchestration.css';

const statusLabel = { queued: "Queued", running: "Running", completed: "Completed", succeeded: "Completed", failed: "Failed", canceled: "Canceled", online: "Available", busy: "Busy", offline: "Offline" };

function CommentProposalReview({ proposal, assistant }) {
  const [text, setText] = useState(proposal.content || ''), [busy, setBusy] = useState(false);
  const decide = async accept => {
    setBusy(true);
    try { await (accept ? assistant.apply(proposal, text) : assistant.dismiss(proposal)); await assistant.reloadBoard(true); }
    finally { setBusy(false); }
  };
  return <div className="board-comment-review"><p>{proposal.action} · {proposal.target?.display}</p>
    {proposal.target?.quote && <blockquote>{proposal.target.quote}</blockquote>}
    <textarea aria-label={"Review comment"} rows={4} value={text} onChange={event => setText(event.target.value)} />
    {assistant.proposalErrors?.[proposal.id] && <p className="error" role="alert">{assistant.proposalErrors[proposal.id]}</p>}
    <div className="board-actions"><button type="button" disabled={busy} onClick={() => decide(true)}>Approve suggestion</button>
      <button type="button" disabled={busy} onClick={() => decide(false)}>Dismiss</button></div></div>;
}

export function OrchestrationCounters({ counts, onOpen }) {
  return <div className="orchestration-counters"><button type="button" className={counts?.needs_you ? 'needs-you' : ''} onClick={onOpen}>
    ? Needs You <b>{counts?.needs_you || 0}</b></button><button type="button" onClick={onOpen}>⟳ Working <b>{counts?.working || 0}</b></button></div>;
}

export function AgentBoard({ assistant, me, onOpenTarget }) {
  const title = useRef(null), [busy, setBusy] = useState(null), [errors, setErrors] = useState({}), [reviewing, setReviewing] = useState(null);
  useEffect(() => { assistant.setBoardOpen(true); title.current?.focus({ preventScroll: true }); return () => assistant.setBoardOpen(false); }, [assistant.setBoardOpen]);
  const board = assistant.board;
  const groups = groupBoardItems(['needs_you', 'working', 'done', 'idle'].flatMap(key => board[key] || []));
  const work = async (id, action) => {
    setBusy(id); setErrors(current => ({ ...current, [id]: '' }));
    try { await action(); }
    catch (error) { setErrors(current => ({ ...current, [id]: error.message })); }
    finally { setBusy(null); }
  };
  const answer = (item, option) => work(item.id, async () => {
    assistant.updateBoardUi({ drafts: { ...board.ui.drafts, [item.gate_id]: option.id } });
    await assistant.resolveGate(item.gate_id, { client_request_id: crypto.randomUUID(), resolution: option.id });
  });
  return <section className="agent-board" aria-label={"Agent Board"}>
    <header className="board-heading"><h3 ref={title} tabIndex={-1}>Agent Tasks</h3><button type="button" disabled={busy !== null} onClick={() => work('refresh', () => assistant.reloadBoard(true))}>Refresh</button></header>
    {assistant.boardError && <p className="error" role="alert">{assistant.boardError}</p>}
    {assistant.paged && <p className="board-note">Viewing older tasks. Refresh to return to the latest activity.</p>}
    <section className="board-group needs-group"><h4>Needs You <span>{board.counts?.needs_you || 0}</span></h4>
      {!groups.needs_you.length && <p className="board-empty">No tasks need your review or decision.</p>}
      {groups.needs_you.map(item => <article className="board-item" key={item.id}>
        <strong>{item.title || item.question || "Changes to review"}</strong>
        {item.kind === 'race_select' ? <><p>{item.proposals.length}  candidates ready to review</p><button type="button" onClick={() => assistant.updateBoardUi({ selected: item })}>Compare Candidates</button></> :
          item.kind === 'question' || item.kind === 'escalation' ? <><p>{item.question}</p>
            {item.context && <details><summary>Review pipeline scope</summary>{item.context.nodes.map(node => <p key={node.node_id}>{node.title} · {node.row_count}  items ·  {node.target_title} · {node.write_mode === 'direct' ? "Direct write" : "Proposal review"}</p>)}
              {item.context.sources.map(source => <small key={source.tab_key}>{source.title} · revision {source.revision}<br /></small>)}</details>}
            <div className="board-options">{item.options.map(option => <button type="button" aria-pressed={board.ui.drafts[item.gate_id] === option.id} key={option.id}
              disabled={busy !== null || !me.can_write} onClick={() => answer(item, option)}>{option.label}</button>)}</div></> :
          <><button type="button" aria-expanded={reviewing === item.id} onClick={() => setReviewing(reviewing === item.id ? null : item.id)}>Review Changes</button>
            {reviewing === item.id && item.proposals.map(proposal => proposal.action !== 'table_edit' ? <CommentProposalReview key={proposal.id} proposal={proposal} assistant={assistant} /> : <TableProposalReview key={proposal.id} proposal={{ ...proposal, error: assistant.proposalErrors?.[proposal.id] || proposal.error }}
              onApply={async (p, content, options) => { const result = await assistant.apply(p, content, options); await assistant.reloadBoard(true); return result; }}
              onDismiss={async p => { const result = await assistant.dismiss(p); await assistant.reloadBoard(true); return result; }} />)}</>}
        {item.run_id && <button type="button" disabled={busy !== null || !me.can_write}
          onClick={() => work(item.id, () => assistant.cancelWork(item))}>Cancel This Batch</button>}
        {errors[item.id] && <p className="error" role="alert">{errors[item.id]}</p>}
      </article>)}
    </section>
    <section className="board-group"><h4>Running <span>{board.counts?.working || 0}</span></h4>
      {!groups.working.length && <p className="board-empty">No background tasks are running.</p>}
      {groups.working.map(item => <article className="board-item" key={item.id}><strong>{item.title}</strong><p>{statusLabel[item.status]}{item.agent_key ? ` · ${item.agent_key}` : ''}</p>
        {item.tools_trace?.length > 0 && <small>{item.tools_trace.at(-1).label} {item.tools_trace.at(-1).detail}</small>}
        <div className="board-actions">{item.target?.tab_key && <button type="button" onClick={() => onOpenTarget(item.target)}>View Source</button>}
          {(item.kind !== 'flow' || item.can_cancel) && <button type="button" disabled={busy !== null || !me.can_write} onClick={() => work(item.id, () => assistant.cancelWork(item))}>Cancel</button>}</div>
        {errors[item.id] && <p className="error" role="alert">{errors[item.id]}</p>}</article>)}
    </section>
    <section className="board-group"><h4>Results &amp; History <span>{board.counts?.done || 0}</span></h4>
      {!groups.done.length && <p className="board-empty">Completed tasks appear here.</p>}
      {groups.done.map(item => <article className="board-item" key={item.id}><strong>{item.title}</strong><p className={item.status === 'failed' ? 'error' : ''}>{statusLabel[item.status]}</p>
        {item.summary && <p>{item.summary}</p>}{item.error && <p className="error">{item.error}</p>}
        <div className="board-actions">{item.target?.tab_key && <button type="button" onClick={() => onOpenTarget(item.target)}>View Results</button>}
          {item.kind === 'task' && !item.flow_bound && ['failed', 'canceled'].includes(item.status) && <button type="button" disabled={busy !== null || !me.can_write} onClick={() => work(item.id, () => assistant.retryWork(item))}>Retry</button>}</div>
        {errors[item.id] && <p className="error" role="alert">{errors[item.id]}</p>}</article>)}
    </section>
    <section className="board-group"><h4>Agents &amp; Workers</h4>{groups.idle.map(agent => <div className="board-agent" key={agent.id}>
      <strong>{agent.icon} {agent.display_name}</strong><small>{statusLabel[agent.status] || agent.status} · {agent.active_dispatches || 0}/{agent.max_concurrency || 1}</small>
    </div>)}</section>
    {board.cursor && <button type="button" className="board-more" disabled={busy !== null} onClick={() => work('more', assistant.moreBoard)}>Load More Tasks</button>}
    {board.ui.selected && <ProposalRaceView gate={board.ui.selected} returnFocusRef={title} onClose={() => assistant.updateBoardUi({ selected: null })}
      onSelect={body => assistant.resolveGate(board.ui.selected.gate_id, body)} />}
  </section>;
}
