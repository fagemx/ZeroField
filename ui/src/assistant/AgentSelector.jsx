export function AgentSelector({ agents = [], value, onChange, disabled }) {
  const selectable = agents.filter(a => a.enabled && a.role_kind !== 'observer' && a.runtime_kind === 'builtin_llm');
  return <label className="agent-selector"><span>Assign to</span><select aria-label={"Chat agent"} value={value} disabled={disabled}
    onChange={event => onChange(event.target.value)}>
    {!selectable.some(a => a.agent_key === value) && <option value={value} disabled>This agent is unavailable.</option>}
    {selectable.map(agent => <option key={agent.agent_key} value={agent.agent_key}>{agent.icon} {agent.display_name}</option>)}
  </select></label>;
}
