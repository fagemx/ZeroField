import { agentLabel } from '../format.js';
import { useLocale } from '../i18n/react.jsx';
import { t as uiText } from '../i18n/index.js';
export function AgentSelector({ agents = [], value, onChange, disabled }) {
  const locale = useLocale();
  const selectable = agents.filter(a => a.enabled && a.role_kind !== 'observer' && a.runtime_kind === 'builtin_llm');
  return <label className="agent-selector"><span>{uiText("agentSelector.assignTo")}</span><select aria-label={uiText("agentSelector.chatAgent")} value={value} disabled={disabled}
    onChange={event => onChange(event.target.value)}>
    {!selectable.some(a => a.agent_key === value) && <option value={value} disabled>{uiText("agentSelector.thisAgentIsUnavailable")}</option>}
    {selectable.map(agent => <option key={agent.agent_key} value={agent.agent_key}>{agent.icon} {agentLabel(agent)}</option>)}
  </select></label>;
}
