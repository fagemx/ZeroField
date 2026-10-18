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
      if (strategy === 'race' && (raceAgents.length < 2 || raceAgents.length > 3 || selectedRace.length !== raceAgents.length)) throw new Error('請選擇 2～3 位具有表格修改權限的代理');
      if (strategy === 'race' && mediaRace && request.scope.row_ids.length !== 1) throw new Error('媒體候選比較請先選一列，再選擇產出欄位');
      if (strategy !== 'chat' && strategy !== 'race' && !chosen) throw new Error('請選擇目前可用的代理或手腳');
      if (strategy !== 'chat' && mediaAgent && request.scope.row_ids.length > 1 && strategy !== 'fanout_rows') throw new Error('多列媒體請選擇逐列背景處理，讓每列有獨立產出');
      const cellOutput = mediaAgent || (strategy === 'race' && mediaRace);
      const target = { tab_key: request.scope.target_tab, table_id: request.scope.table_id, kind: 'table',
        ...(cellOutput ? { col_index: Number(outputColumn), row_id: request.scope.row_ids[0] } : {}) };
      const options = strategy === 'chat' ? null : { strategy, agentKey, raceAgents, target, writeMode: strategy === 'race' || cellOutput ? 'proposal' : writeMode, requestId: request.requestId };
      const ok = await onSubmit(options);
      if (ok !== false) onClose();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  return <SheetDialog title="交給代理協助" onClose={onClose}>
    <div className="request-scope"><b>{request.title} / {request.table.name}</b><small>已固定 {request.scope.row_ids.length} 列 × {request.scope.column_indices.length} 欄 · 版本 {request.scope.base_revision}</small></div>
    <p className="sheet-subtle">範圍會保留到送出。修改先提供核對，確認後才寫回。</p>
    <fieldset disabled={busy} className="agent-request-fields">
      <label className="modal-field"><span>想完成什麼？</span><textarea data-autofocus aria-label="代理工作需求" rows={4} value={instruction} onChange={e => onInstruction(e.target.value)} placeholder="例如：核對這幾筆資料，補上缺少的說明" /></label>
      <label className="modal-field"><span>處理方式</span><select aria-label="代理處理方式" value={strategy} onChange={e => setStrategy(e.target.value)}>
        <option value="chat">放入對話，繼續討論</option><option value="single">建立一項背景工作</option><option value="fanout_rows">每列各自背景處理</option><option value="race">產生 2～3 個候選版本</option>
      </select></label>
      {strategy !== 'chat' && strategy !== 'race' && <label className="modal-field"><span>負責代理</span><select aria-label="負責代理" value={agentKey} onChange={e => {
        setAgentKey(e.target.value); const agent = activeAgents.find(a => a.agent_key === e.target.value);
        setWriteMode(agent?.can_propose_table ? 'proposal' : 'analysis_only');
      }}>{!activeAgents.some(agent => agent.agent_key === agentKey) && <option value={agentKey}>此代理目前不可用</option>}
        {activeAgents.map(agent => <option key={agent.agent_key} value={agent.agent_key}>{agent.icon} {agent.display_name}</option>)}
      </select></label>}
      {strategy === 'race' && <fieldset><legend>候選代理（2～3 位）</legend>{eligible.map(agent => <label className="agent-race-choice" key={agent.agent_key}>
        <input type="checkbox" checked={raceAgents.includes(agent.agent_key)} onChange={e => setRaceAgents(current => e.target.checked ? [...current, agent.agent_key] : current.filter(key => key !== agent.agent_key))} />{agent.icon} {agent.display_name}
      </label>)}</fieldset>}
      {strategy !== 'chat' && (mediaAgent || mediaRace) && <label className="modal-field"><span>產出欄位</span><select aria-label="產出欄位" value={outputColumn} onChange={e => setOutputColumn(Number(e.target.value))}>
        {request.scope.column_indices.map(index => <option key={index} value={index}>{request.table.headers[index]}</option>)}
      </select></label>}
      {strategy !== 'chat' && strategy !== 'race' && !mediaAgent && <label className="modal-field"><span>交付內容</span><select aria-label="交付內容" value={writeMode} onChange={e => setWriteMode(e.target.value)}>
        <option value="proposal">提出可核對的修改</option><option value="analysis_only">只分析，保留結論</option>
      </select></label>}
    </fieldset>
    {error && <p role="alert" className="error">{error}</p>}
    <div className="sheet-dialog-actions"><button disabled={busy} onClick={onUpdateScope}>以目前勾選／可見列更新範圍</button>
      <button className="primary" disabled={busy || !instruction.trim()} onClick={submit}>{busy ? '送出中…' : strategy === 'chat' ? '放入對話 →' : strategy === 'race' ? '產生候選提案' : '開始背景工作'}</button></div>
  </SheetDialog>;
}
