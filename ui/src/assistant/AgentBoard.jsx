import { useEffect, useRef, useState } from 'react';
import { TableProposalReview } from './TableProposalReview.jsx';
import { ProposalRaceView } from './ProposalRaceView.jsx';
import { groupBoardItems } from './orchestrationModel.js';
import './orchestration.css';

const statusLabel = { queued: '排隊中', running: '執行中', completed: '已完成', succeeded: '已完成', failed: '失敗', canceled: '已取消', online: '可使用', busy: '忙碌', offline: '未連接' };

function CommentProposalReview({ proposal, assistant }) {
  const [text, setText] = useState(proposal.content || ''), [busy, setBusy] = useState(false);
  const decide = async accept => {
    setBusy(true);
    try { await (accept ? assistant.apply(proposal, text) : assistant.dismiss(proposal)); await assistant.reloadBoard(true); }
    finally { setBusy(false); }
  };
  return <div className="board-comment-review"><p>{proposal.action} · {proposal.target?.display}</p>
    {proposal.target?.quote && <blockquote>{proposal.target.quote}</blockquote>}
    <textarea aria-label="核對留言內容" rows={4} value={text} onChange={event => setText(event.target.value)} />
    {assistant.proposalErrors?.[proposal.id] && <p className="error" role="alert">{assistant.proposalErrors[proposal.id]}</p>}
    <div className="board-actions"><button type="button" disabled={busy} onClick={() => decide(true)}>確認此建議</button>
      <button type="button" disabled={busy} onClick={() => decide(false)}>先略過</button></div></div>;
}

export function OrchestrationCounters({ counts, onOpen }) {
  return <div className="orchestration-counters"><button type="button" className={counts?.needs_you ? 'needs-you' : ''} onClick={onOpen}>
    ? 待你裁決 <b>{counts?.needs_you || 0}</b></button><button type="button" onClick={onOpen}>⟳ 執行中 <b>{counts?.working || 0}</b></button></div>;
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
  return <section className="agent-board" aria-label="代理編排看板">
    <header className="board-heading"><h3 ref={title} tabIndex={-1}>代理工作</h3><button type="button" disabled={busy !== null} onClick={() => work('refresh', () => assistant.reloadBoard(true))}>更新</button></header>
    {assistant.boardError && <p className="error" role="alert">{assistant.boardError}</p>}
    {assistant.paged && <p className="board-note">正在查看較早的工作。按「更新」回到最新狀態。</p>}
    <section className="board-group needs-group"><h4>待你裁決 <span>{board.counts?.needs_you || 0}</span></h4>
      {!groups.needs_you.length && <p className="board-empty">目前沒有待核對或待決定的工作。</p>}
      {groups.needs_you.map(item => <article className="board-item" key={item.id}>
        <strong>{item.title || item.question || '待核對修改'}</strong>
        {item.kind === 'race_select' ? <><p>{item.proposals.length} 個候選可核對</p><button type="button" onClick={() => assistant.updateBoardUi({ selected: item })}>比較候選版本</button></> :
          item.kind === 'question' || item.kind === 'escalation' ? <><p>{item.question}</p>
            {item.context && <details><summary>核對流程範圍</summary>{item.context.nodes.map(node => <p key={node.node_id}>{node.title} · {node.row_count} 筆 · {node.target_title} · {node.write_mode === 'direct' ? '直接寫入' : '提案核對'}</p>)}
              {item.context.sources.map(source => <small key={source.tab_key}>{source.title} · 版本 {source.revision}<br /></small>)}</details>}
            <div className="board-options">{item.options.map(option => <button type="button" aria-pressed={board.ui.drafts[item.gate_id] === option.id} key={option.id}
              disabled={busy !== null || !me.can_write} onClick={() => answer(item, option)}>{option.label}</button>)}</div></> :
          <><button type="button" aria-expanded={reviewing === item.id} onClick={() => setReviewing(reviewing === item.id ? null : item.id)}>核對修改</button>
            {reviewing === item.id && item.proposals.map(proposal => proposal.action !== 'table_edit' ? <CommentProposalReview key={proposal.id} proposal={proposal} assistant={assistant} /> : <TableProposalReview key={proposal.id} proposal={{ ...proposal, error: assistant.proposalErrors?.[proposal.id] || proposal.error }}
              onApply={async (p, content, options) => { const result = await assistant.apply(p, content, options); await assistant.reloadBoard(true); return result; }}
              onDismiss={async p => { const result = await assistant.dismiss(p); await assistant.reloadBoard(true); return result; }} />)}</>}
        {item.run_id && <button type="button" disabled={busy !== null || !me.can_write}
          onClick={() => work(item.id, () => assistant.cancelWork(item))}>取消這批工作</button>}
        {errors[item.id] && <p className="error" role="alert">{errors[item.id]}</p>}
      </article>)}
    </section>
    <section className="board-group"><h4>執行中 <span>{board.counts?.working || 0}</span></h4>
      {!groups.working.length && <p className="board-empty">沒有正在執行的背景工作。</p>}
      {groups.working.map(item => <article className="board-item" key={item.id}><strong>{item.title}</strong><p>{statusLabel[item.status]}{item.agent_key ? ` · ${item.agent_key}` : ''}</p>
        {item.tools_trace?.length > 0 && <small>{item.tools_trace.at(-1).label} {item.tools_trace.at(-1).detail}</small>}
        <div className="board-actions">{item.target?.tab_key && <button type="button" onClick={() => onOpenTarget(item.target)}>查看來源</button>}
          {(item.kind !== 'flow' || item.can_cancel) && <button type="button" disabled={busy !== null || !me.can_write} onClick={() => work(item.id, () => assistant.cancelWork(item))}>取消</button>}</div>
        {errors[item.id] && <p className="error" role="alert">{errors[item.id]}</p>}</article>)}
    </section>
    <section className="board-group"><h4>結果與紀錄 <span>{board.counts?.done || 0}</span></h4>
      {!groups.done.length && <p className="board-empty">結束的工作會保留在這裡。</p>}
      {groups.done.map(item => <article className="board-item" key={item.id}><strong>{item.title}</strong><p className={item.status === 'failed' ? 'error' : ''}>{statusLabel[item.status]}</p>
        {item.summary && <p>{item.summary}</p>}{item.error && <p className="error">{item.error}</p>}
        <div className="board-actions">{item.target?.tab_key && <button type="button" onClick={() => onOpenTarget(item.target)}>查看結果</button>}
          {item.kind === 'task' && !item.flow_bound && ['failed', 'canceled'].includes(item.status) && <button type="button" disabled={busy !== null || !me.can_write} onClick={() => work(item.id, () => assistant.retryWork(item))}>重試</button>}</div>
        {errors[item.id] && <p className="error" role="alert">{errors[item.id]}</p>}</article>)}
    </section>
    <section className="board-group"><h4>代理與手腳池</h4>{groups.idle.map(agent => <div className="board-agent" key={agent.id}>
      <strong>{agent.icon} {agent.display_name}</strong><small>{statusLabel[agent.status] || agent.status} · {agent.active_dispatches || 0}/{agent.max_concurrency || 1}</small>
    </div>)}</section>
    {board.cursor && <button type="button" className="board-more" disabled={busy !== null} onClick={() => work('more', assistant.moreBoard)}>載入更多工作</button>}
    {board.ui.selected && <ProposalRaceView gate={board.ui.selected} returnFocusRef={title} onClose={() => assistant.updateBoardUi({ selected: null })}
      onSelect={body => assistant.resolveGate(board.ui.selected.gate_id, body)} />}
  </section>;
}
