import { agentLabel } from '../format.js';
import { useLocale } from '../i18n/react.jsx';
import { t as uiText, currentLocale } from '../i18n/index.js';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api.js';
import { TableProposalReview } from './TableProposalReview.jsx';
import { ProposalRaceView } from './ProposalRaceView.jsx';
import { groupBoardItems } from './orchestrationModel.js';
import './orchestration.css';

const statusLabel = { get queued() { return uiText("agentBoard.queued"); }, get running() { return uiText("agentBoard.running"); }, get completed() { return uiText("agentBoard.completed"); }, get succeeded() { return uiText("agentBoard.completed"); }, get failed() { return uiText("agentBoard.failed"); }, get canceled() { return uiText("agentBoard.canceled"); }, get online() { return uiText("agentBoard.available"); }, get busy() { return uiText("agentBoard.busy"); }, get offline() { return uiText("agentBoard.offline"); }, get needs_setup() { return uiText("agentBoard.needsSetup"); } };

// Readiness fix hints (SPEC_20 §4.2) → crewReadiness messages; anything newer falls back to a generic line.
const FIX_TEXT = { restart_without_no_worker: 'restartWithoutNoWorker', start_ollama: 'startOllama', start_model_server: 'startModelServer', check_endpoint: 'checkEndpoint', ollama_pull: 'ollamaPull', load_model: 'loadModel', set_api_key: 'setApiKey', configure_provider: 'configureProvider', allow_host: 'allowHost', enable_environment: 'enableEnvironment', keep_local: 'keepLocal', set_model_pricing: 'setModelPricing', reconcile_reservations: 'reconcileReservations', enable_agent: 'enableAgent', use_builtin_provider: 'useBuiltinProvider', reconfigure_provider: 'reconfigureProvider' };

// One plain line per distinct problem and fix; the agents it stops are named once beneath it.
export function readinessLines(readiness, agents = []) {
  if (!readiness || readiness.ready) return [];
  const names = new Map(agents.map(agent => [agent.agent_key, agentLabel(agent)])), lines = new Map();
  for (const blocker of readiness.blockers || []) {
    const id = [blocker.code, blocker.fix, blocker.model, blocker.host, blocker.port, blocker.count].join('|');
    if (!lines.has(id)) lines.set(id, { id, agents: [],
      text: uiText(`crewReadiness.${Object.hasOwn(FIX_TEXT, blocker.fix) ? FIX_TEXT[blocker.fix] : 'unknown'}`, { model: blocker.model, host: blocker.host, port: blocker.port, count: blocker.count, minutes: blocker.minutes, code: blocker.code }),
      command: blocker.fix === 'ollama_pull' && blocker.model ? `ollama pull ${blocker.model}` : '' });
    const line = lines.get(id), name = blocker.agentKey && (names.get(blocker.agentKey) || blocker.agentKey);
    if (name && !line.agents.includes(name)) line.agents.push(name);
  }
  return [...lines.values()];
}

export function CrewReadinessBanner({ readiness, agents, error = '', checking = false, onCheck }) {
  const lines = readinessLines(readiness, agents);
  if (!lines.length && !error) return null;
  return <section className="crew-readiness" aria-label={uiText("crewReadiness.label")}>
    <header>{lines.length > 0 && <strong>{uiText("crewReadiness.title")}</strong>}
      <button type="button" disabled={checking} onClick={onCheck}>{uiText(checking ? "crewReadiness.checking" : "crewReadiness.checkAgain")}</button></header>
    {error && <p className="error" role="alert">{uiText("crewReadiness.checkFailed", {v0: error})}</p>}
    {lines.length > 0 && <ul>{lines.map(line => <li key={line.id}>{line.text}{line.command && <> <code>{line.command}</code></>}
      {line.agents.length > 0 && <small>{uiText("crewReadiness.affects", {v0: new Intl.ListFormat(currentLocale(), {type: 'conjunction'}).format(line.agents)})}</small>}</li>)}</ul>}
  </section>;
}

function useCrewReadiness(slug) {
  const [state, setState] = useState({ readiness: null, error: '', checking: false }), current = useRef(slug);
  current.current = slug;
  const load = useCallback(async (refresh = false) => {
    if (refresh) setState(value => ({ ...value, checking: true }));
    try {
      const readiness = await api.get(`/projects/api/${slug}/agents/readiness${refresh ? '?refresh=1' : ''}`);
      if (current.current === slug) setState({ readiness, error: '', checking: false });
    } catch (error) {
      if (current.current === slug) setState(value => ({ ...value, error: error.message, checking: false }));
    }
  }, [slug]);
  useEffect(() => {
    if (!slug) return undefined;
    setState({ readiness: null, error: '', checking: false });
    load();
    const timer = setInterval(() => load(), 30000);
    return () => clearInterval(timer);
  }, [slug, load]);
  return { ...state, check: () => load(true) };
}

function CommentProposalReview({ proposal, assistant }) {
  const locale = useLocale();
  const [text, setText] = useState(proposal.content || ''), [busy, setBusy] = useState(false);
  const decide = async accept => {
    setBusy(true);
    try { await (accept ? assistant.apply(proposal, text) : assistant.dismiss(proposal)); await assistant.reloadBoard(true); }
    finally { setBusy(false); }
  };
  return <div className="board-comment-review"><p>{proposal.action} · {proposal.target?.display}</p>
    {proposal.target?.quote && <blockquote>{proposal.target.quote}</blockquote>}
    <textarea aria-label={uiText("agentBoard.reviewComment")} rows={4} value={text} onChange={event => setText(event.target.value)} />
    {assistant.proposalErrors?.[proposal.id] && <p className="error" role="alert">{assistant.proposalErrors[proposal.id]}</p>}
    <div className="board-actions"><button type="button" disabled={busy} onClick={() => decide(true)}>{uiText("agentBoard.approveSuggestion")}</button>
      <button type="button" disabled={busy} onClick={() => decide(false)}>{uiText("agentBoard.dismiss")}</button></div></div>;
}

export function OrchestrationCounters({ counts, onOpen }) {
  const locale = useLocale();
  return <div className="orchestration-counters"><button type="button" className={counts?.needs_you ? 'needs-you' : ''} onClick={onOpen}>{uiText("agentBoard.needsYou")}<b>{counts?.needs_you || 0}</b></button><button type="button" onClick={onOpen}>{uiText("agentBoard.working")}<b>{counts?.working || 0}</b></button></div>;
}

export function AgentBoard({ assistant, me, onOpenTarget }) {
  const locale = useLocale();
  const title = useRef(null), [busy, setBusy] = useState(null), [errors, setErrors] = useState({}), [reviewing, setReviewing] = useState(null);
  useEffect(() => { assistant.setBoardOpen(true); title.current?.focus({ preventScroll: true }); return () => assistant.setBoardOpen(false); }, [assistant.setBoardOpen]);
  const board = assistant.board, crew = useCrewReadiness(assistant.slug);
  const groups = groupBoardItems(['needs_you', 'working', 'done', 'idle'].flatMap(key => board[key] || []));
  const checkCrew = async () => {
    await crew.check();
    try { await assistant.reloadBoard(true); } catch { /* the board poll reports its own errors */ }
  };
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
  return <section className="agent-board" aria-label={uiText("agentBoard.agentBoard")}>
    <header className="board-heading"><h3 ref={title} tabIndex={-1}>{uiText("agentBoard.agentTasks")}</h3><button type="button" disabled={busy !== null} onClick={() => work('refresh', () => assistant.reloadBoard(true))}>{uiText("agentBoard.refresh")}</button></header>
    {assistant.boardError && <p className="error" role="alert">{assistant.boardError}</p>}
    {assistant.paged && <p className="board-note">{uiText("agentBoard.viewingOlderTasksRefreshToReturnToTheLatest")}</p>}
    <section className="board-group needs-group"><h4>{uiText("agentBoard.needsYou2")}<span>{board.counts?.needs_you || 0}</span></h4>
      {!groups.needs_you.length && <p className="board-empty">{uiText("agentBoard.noTasksNeedYourReviewOrDecision")}</p>}
      {groups.needs_you.map(item => <article className="board-item" key={item.id}>
        <strong>{item.title || item.question || uiText("agentBoard.changesToReview")}</strong>
        {item.kind === 'race_select' ? <><p>{uiText("agentBoard.candidatesReadyToReview", {v0: (item.proposals.length)})}</p><button type="button" onClick={() => assistant.updateBoardUi({ selected: item })}>{uiText("agentBoard.compareCandidates")}</button></> :
          item.kind === 'question' || item.kind === 'escalation' ? <><p>{item.question}</p>
            {item.context && <details><summary>{uiText("agentBoard.reviewPipelineScope")}</summary>{item.context.nodes.map(node => <p key={node.node_id}>{uiText("agentBoard.items", {v0: (node.title), v1: (node.row_count), v2: (node.target_title), v3: (node.write_mode === 'direct' ? uiText("agentBoard.directWrite") : uiText("agentBoard.proposalReview"))})}</p>)}
              {item.context.sources.map(source => <small key={source.tab_key}>{uiText("agentBoard.revision", {v0: (source.title), v1: (source.revision)})}<br /></small>)}</details>}
            <div className="board-options">{item.options.map(option => <button type="button" aria-pressed={board.ui.drafts[item.gate_id] === option.id} key={option.id}
              disabled={busy !== null || !me.can_write} onClick={() => answer(item, option)}>{option.label}</button>)}</div></> :
          <><button type="button" aria-expanded={reviewing === item.id} onClick={() => setReviewing(reviewing === item.id ? null : item.id)}>{uiText("agentBoard.reviewChanges")}</button>
            {reviewing === item.id && item.proposals.map(proposal => proposal.action !== 'table_edit' ? <CommentProposalReview key={proposal.id} proposal={proposal} assistant={assistant} /> : <TableProposalReview key={proposal.id} proposal={{ ...proposal, error: assistant.proposalErrors?.[proposal.id] || proposal.error }}
              onApply={async (p, content, options) => { const result = await assistant.apply(p, content, options); await assistant.reloadBoard(true); return result; }}
              onDismiss={async p => { const result = await assistant.dismiss(p); await assistant.reloadBoard(true); return result; }} />)}</>}
        {item.run_id && <button type="button" disabled={busy !== null || !me.can_write}
          onClick={() => work(item.id, () => assistant.cancelWork(item))}>{uiText("agentBoard.cancelThisBatch")}</button>}
        {errors[item.id] && <p className="error" role="alert">{errors[item.id]}</p>}
      </article>)}
    </section>
    <section className="board-group"><h4>{uiText("agentBoard.running2")}<span>{board.counts?.working || 0}</span></h4>
      {!groups.working.length && <p className="board-empty">{uiText("agentBoard.noBackgroundTasksAreRunning")}</p>}
      {groups.working.map(item => <article className="board-item" key={item.id}><strong>{item.title}</strong><p>{statusLabel[item.status]}{item.agent_key ? ` · ${item.agent_key}` : ''}</p>
        {item.tools_trace?.length > 0 && <small>{item.tools_trace.at(-1).label} {item.tools_trace.at(-1).detail}</small>}
        <div className="board-actions">{item.target?.tab_key && <button type="button" onClick={() => onOpenTarget(item.target)}>{uiText("agentBoard.viewSource")}</button>}
          {(item.kind !== 'flow' || item.can_cancel) && <button type="button" disabled={busy !== null || !me.can_write} onClick={() => work(item.id, () => assistant.cancelWork(item))}>{uiText("agentBoard.cancel")}</button>}</div>
        {errors[item.id] && <p className="error" role="alert">{errors[item.id]}</p>}</article>)}
    </section>
    <section className="board-group"><h4>{uiText("agentBoard.resultsHistory")}<span>{board.counts?.done || 0}</span></h4>
      {!groups.done.length && <p className="board-empty">{uiText("agentBoard.completedTasksAppearHere")}</p>}
      {groups.done.map(item => <article className="board-item" key={item.id}><strong>{item.title}</strong><p className={item.status === 'failed' ? 'error' : ''}>{statusLabel[item.status]}</p>
        {item.summary && <p>{item.summary}</p>}{item.error && <p className="error">{item.error}</p>}
        <div className="board-actions">{item.target?.tab_key && <button type="button" onClick={() => onOpenTarget(item.target)}>{uiText("agentBoard.viewResults")}</button>}
          {item.kind === 'task' && !item.flow_bound && ['failed', 'canceled'].includes(item.status) && <button type="button" disabled={busy !== null || !me.can_write} onClick={() => work(item.id, () => assistant.retryWork(item))}>{uiText("agentBoard.retry")}</button>}</div>
        {errors[item.id] && <p className="error" role="alert">{errors[item.id]}</p>}</article>)}
    </section>
    <section className="board-group"><h4>{uiText("agentBoard.agentsWorkers")}</h4>
      <CrewReadinessBanner readiness={crew.readiness} agents={groups.idle} error={crew.error} checking={crew.checking} onCheck={checkCrew} />
      {groups.idle.map(agent => <div className="board-agent" key={agent.id}>
      <strong>{agent.icon} {agentLabel(agent)}</strong><small className={agent.status === 'needs_setup' ? 'needs-setup' : undefined}>{statusLabel[agent.status] || agent.status} · {agent.active_dispatches || 0}/{agent.max_concurrency || 1}</small>
    </div>)}</section>
    {board.cursor && <button type="button" className="board-more" disabled={busy !== null} onClick={() => work('more', assistant.moreBoard)}>{uiText("agentBoard.loadMoreTasks")}</button>}
    {board.ui.selected && <ProposalRaceView gate={board.ui.selected} returnFocusRef={title} onClose={() => assistant.updateBoardUi({ selected: null })}
      onSelect={body => assistant.resolveGate(board.ui.selected.gate_id, body)} />}
  </section>;
}
