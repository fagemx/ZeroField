export function AgentSelector({ agents = [], value, onChange, disabled }) {
  const selectable = agents.filter(a => a.enabled && a.role_kind !== 'observer' && a.runtime_kind === 'builtin_llm');
  return <label className="agent-selector"><span>交給</span><select aria-label="對話代理" value={value} disabled={disabled}
    onChange={event => onChange(event.target.value)}>
    {!selectable.some(a => a.agent_key === value) && <option value={value} disabled>此代理目前不可用</option>}
    {selectable.map(agent => <option key={agent.agent_key} value={agent.agent_key}>{agent.icon} {agent.display_name}</option>)}
  </select></label>;
}
