import { useState } from 'react';
import { SheetDialog } from '../SheetDialog.jsx';

export function SheetAgentRequest({ request, instruction, onInstruction, agents, onSubmit, onUpdateScope, onClose }) {
  const [strategy, setStrategy] = useState('chat'), [agentKey, setAgentKey] = useState('sheet_ops');
  const [raceAgents, setRaceAgents] = useState(() => agents.filter(a => a.enabled && a.can_propose_table).slice(0, 2).map(a => a.agent_key));
  const [writeMode, setWriteMode] = useState('proposal'), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [outputColumn, setOutputColumn] = useState(request.preferredOutputColumn ?? request.scope.column_indices.find(index => ['image', 'video', 'audio'].includes(request.table.table?.attrs.column_types?.[index])) ?? request.scope.column_indices[0]);
  const activeAgents = agents.filter(agent => agent.enabled && agent.role_kind !== 'observer');
  const chosen = activeAgents.find(agent => agent.agent_key === agentKey);
  const mediaAgent = chosen && !chosen.capabilities.includes('llm') && chosen.capabilities.some(capability => ['image_gen', 'video_gen', 'media_assemble'].includes(capability));
  const eligible = activeAgents.filter(agent => agent.can_propose_table);
  const selectedRace = eligible.filter(agent => raceAgents.includes(agent.agent_key));
  const mediaRace = selectedRace.some(agent => !agent.capabilities.includes('llm'));
  const submit = async () => {
    setBusy(true); setError('');
    try {
      if (strategy === 'race' && (raceAgents.length < 2 || raceAgents.length > 3 || selectedRace.length !== raceAgents.length)) throw new Error("Choose 2–3 agents with table editing permission.");
      if (strategy === 'race' && mediaRace && request.scope.row_ids.length !== 1) throw new Error("Select one row and an output column to compare media candidates.");
      if (strategy !== 'chat' && strategy !== 'race' && !chosen) throw new Error("Choose an available agent or worker.");
      if (strategy !== 'chat' && mediaAgent && request.scope.row_ids.length > 1 && strategy !== 'fanout_rows') throw new Error("Use a background task per row to generate separate media outputs.");
      const cellOutput = mediaAgent || (strategy === 'race' && mediaRace);
      const target = { tab_key: request.scope.target_tab, table_id: request.scope.table_id, kind: 'table',
        ...(cellOutput ? { col_index: Number(outputColumn), row_id: request.scope.row_ids[0] } : {}) };
      const options = strategy === 'chat' ? null : { strategy, agentKey, raceAgents, target, writeMode: strategy === 'race' || cellOutput ? 'proposal' : writeMode, requestId: request.requestId };
      const ok = await onSubmit(options);
      if (ok !== false) onClose();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  return <SheetDialog title={"Assign to an Agent"} onClose={onClose}>
    <div className="request-scope"><b>{request.title} / {request.table.name}</b><small>Pinned {request.scope.row_ids.length} rows ×  {request.scope.column_indices.length} columns · revision {request.scope.base_revision}</small></div>
    <p className="sheet-subtle">This scope stays pinned until submission. Review changes before applying them.</p>
    <fieldset disabled={busy} className="agent-request-fields">
      <label className="modal-field"><span>What should the agent do?</span><textarea data-autofocus aria-label={"Agent Task Brief"} rows={4} value={instruction} onChange={e => onInstruction(e.target.value)} placeholder={"For example: review these shots and propose missing production notes"} /></label>
      <label className="modal-field"><span>Execution Mode</span><select aria-label={"Agent Execution Mode"} value={strategy} onChange={e => setStrategy(e.target.value)}>
        <option value="chat">Discuss in Chat</option><option value="single">Create a Background Task</option><option value="fanout_rows">Background Task per Row</option><option value="race">Generate 2–3 Candidates</option>
      </select></label>
      {strategy !== 'chat' && strategy !== 'race' && <label className="modal-field"><span>Assigned Agent</span><select aria-label={"Assigned Agent"} value={agentKey} onChange={e => {
        setAgentKey(e.target.value); const agent = activeAgents.find(a => a.agent_key === e.target.value);
        setWriteMode(agent?.can_propose_table ? 'proposal' : 'analysis_only');
      }}>{!activeAgents.some(agent => agent.agent_key === agentKey) && <option value={agentKey}>This agent is unavailable.</option>}
        {activeAgents.map(agent => <option key={agent.agent_key} value={agent.agent_key}>{agent.icon} {agent.display_name}</option>)}
      </select></label>}
      {strategy === 'race' && <fieldset><legend>Candidate Agents (2–3)</legend>{eligible.map(agent => <label className="agent-race-choice" key={agent.agent_key}>
        <input type="checkbox" checked={raceAgents.includes(agent.agent_key)} onChange={e => setRaceAgents(current => e.target.checked ? [...current, agent.agent_key] : current.filter(key => key !== agent.agent_key))} />{agent.icon} {agent.display_name}
      </label>)}</fieldset>}
      {strategy !== 'chat' && (mediaAgent || mediaRace) && <label className="modal-field"><span>Output Column</span><select aria-label={"Output Column"} value={outputColumn} onChange={e => setOutputColumn(Number(e.target.value))}>
        {request.scope.column_indices.map(index => <option key={index} value={index}>{request.table.headers[index]}</option>)}
      </select></label>}
      {strategy !== 'chat' && strategy !== 'race' && !mediaAgent && <label className="modal-field"><span>Delivery</span><select aria-label={"Delivery"} value={writeMode} onChange={e => setWriteMode(e.target.value)}>
        <option value="proposal">Propose Changes for Review</option><option value="analysis_only">Analyze and Keep Findings</option>
      </select></label>}
    </fieldset>
    {error && <p role="alert" className="error">{error}</p>}
    <div className="sheet-dialog-actions"><button disabled={busy} onClick={onUpdateScope}>Update Scope from Selected / Visible Rows</button>
      <button className="primary" disabled={busy || !instruction.trim()} onClick={submit}>{busy ? "Submitting…" : strategy === 'chat' ? "Open in Chat →" : strategy === 'race' ? "Generate Candidates" : "Start Background Task"}</button></div>
  </SheetDialog>;
}
