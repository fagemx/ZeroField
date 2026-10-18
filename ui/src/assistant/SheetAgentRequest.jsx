import { agentLabel } from '../format.js';
import { useLocale } from '../i18n/react.jsx';
import { t as uiText } from '../i18n/index.js';
import { useState } from 'react';
import { SheetDialog } from '../SheetDialog.jsx';

export function SheetAgentRequest({ request, instruction, onInstruction, agents, onSubmit, onUpdateScope, onClose }) {
  const locale = useLocale();
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
      if (strategy === 'race' && (raceAgents.length < 2 || raceAgents.length > 3 || selectedRace.length !== raceAgents.length)) throw new Error(uiText("sheetAgentRequest.chooseAgentsWithTableEditingPermission"));
      if (strategy === 'race' && mediaRace && request.scope.row_ids.length !== 1) throw new Error(uiText("sheetAgentRequest.selectOneRowAndAnOutputColumnToCompare"));
      if (strategy !== 'chat' && strategy !== 'race' && !chosen) throw new Error(uiText("sheetAgentRequest.chooseAnAvailableAgentOrWorker"));
      if (strategy !== 'chat' && mediaAgent && request.scope.row_ids.length > 1 && strategy !== 'fanout_rows') throw new Error(uiText("sheetAgentRequest.useABackgroundTaskPerRowToGenerateSeparate"));
      const cellOutput = mediaAgent || (strategy === 'race' && mediaRace);
      const target = { tab_key: request.scope.target_tab, table_id: request.scope.table_id, kind: 'table',
        ...(cellOutput ? { col_index: Number(outputColumn), row_id: request.scope.row_ids[0] } : {}) };
      const options = strategy === 'chat' ? null : { strategy, agentKey, raceAgents, target, writeMode: strategy === 'race' || cellOutput ? 'proposal' : writeMode, requestId: request.requestId };
      const ok = await onSubmit(options);
      if (ok !== false) onClose();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  return <SheetDialog title={uiText("sheetAgentRequest.assignToAnAgent")} onClose={onClose}>
    <div className="request-scope"><b>{request.title} / {request.table.name}</b><small>{uiText("sheetAgentRequest.pinnedRowsColumnsRevision", {v0: (request.scope.row_ids.length), v1: (request.scope.column_indices.length), v2: (request.scope.base_revision)})}</small></div>
    <p className="sheet-subtle">{uiText("sheetAgentRequest.thisScopeStaysPinnedUntilSubmissionReviewChangesBefore")}</p>
    <fieldset disabled={busy} className="agent-request-fields">
      <label className="modal-field"><span>{uiText("sheetAgentRequest.whatShouldTheAgentDo")}</span><textarea data-autofocus aria-label={uiText("sheetAgentRequest.agentTaskBrief")} rows={4} value={instruction} onChange={e => onInstruction(e.target.value)} placeholder={uiText("sheetAgentRequest.forExampleReviewTheseShotsAndProposeMissingProduction")} /></label>
      <label className="modal-field"><span>{uiText("sheetAgentRequest.executionMode")}</span><select aria-label={uiText("sheetAgentRequest.agentExecutionMode")} value={strategy} onChange={e => setStrategy(e.target.value)}>
        <option value="chat">{uiText("sheetAgentRequest.discussInChat")}</option><option value="single">{uiText("sheetAgentRequest.createABackgroundTask")}</option><option value="fanout_rows">{uiText("sheetAgentRequest.backgroundTaskPerRow")}</option><option value="race">{uiText("sheetAgentRequest.generateCandidates")}</option>
      </select></label>
      {strategy !== 'chat' && strategy !== 'race' && <label className="modal-field"><span>{uiText("sheetAgentRequest.assignedAgent")}</span><select aria-label={uiText("sheetAgentRequest.assignedAgent")} value={agentKey} onChange={e => {
        setAgentKey(e.target.value); const agent = activeAgents.find(a => a.agent_key === e.target.value);
        setWriteMode(agent?.can_propose_table ? 'proposal' : 'analysis_only');
      }}>{!activeAgents.some(agent => agent.agent_key === agentKey) && <option value={agentKey}>{uiText("sheetAgentRequest.thisAgentIsUnavailable")}</option>}
        {activeAgents.map(agent => <option key={agent.agent_key} value={agent.agent_key}>{agent.icon} {agentLabel(agent)}</option>)}
      </select></label>}
      {strategy === 'race' && <fieldset><legend>{uiText("sheetAgentRequest.candidateAgents")}</legend>{eligible.map(agent => <label className="agent-race-choice" key={agent.agent_key}>
        <input type="checkbox" checked={raceAgents.includes(agent.agent_key)} onChange={e => setRaceAgents(current => e.target.checked ? [...current, agent.agent_key] : current.filter(key => key !== agent.agent_key))} />{agent.icon} {agentLabel(agent)}
      </label>)}</fieldset>}
      {strategy !== 'chat' && (mediaAgent || mediaRace) && <label className="modal-field"><span>{uiText("sheetAgentRequest.outputColumn")}</span><select aria-label={uiText("sheetAgentRequest.outputColumn")} value={outputColumn} onChange={e => setOutputColumn(Number(e.target.value))}>
        {request.scope.column_indices.map(index => <option key={index} value={index}>{request.table.headers[index]}</option>)}
      </select></label>}
      {strategy !== 'chat' && strategy !== 'race' && !mediaAgent && <label className="modal-field"><span>{uiText("sheetAgentRequest.delivery")}</span><select aria-label={uiText("sheetAgentRequest.delivery")} value={writeMode} onChange={e => setWriteMode(e.target.value)}>
        <option value="proposal">{uiText("sheetAgentRequest.proposeChangesForReview")}</option><option value="analysis_only">{uiText("sheetAgentRequest.analyzeAndKeepFindings")}</option>
      </select></label>}
    </fieldset>
    {error && <p role="alert" className="error">{error}</p>}
    <div className="sheet-dialog-actions"><button disabled={busy} onClick={onUpdateScope}>{uiText("sheetAgentRequest.updateScopeFromSelectedVisibleRows")}</button>
      <button className="primary" disabled={busy || !instruction.trim()} onClick={submit}>{busy ? uiText("sheetAgentRequest.submitting") : strategy === 'chat' ? uiText("sheetAgentRequest.openInChat") : strategy === 'race' ? uiText("sheetAgentRequest.generateCandidates2") : uiText("sheetAgentRequest.startBackgroundTask")}</button></div>
  </SheetDialog>;
}
