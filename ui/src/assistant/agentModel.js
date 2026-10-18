import { t as uiText } from '../i18n/index.js';
export function openReplies(thread = []) {
  return new Map(thread.filter(m => m.role === 'assistant' && ['queued', 'running'].includes(m.status))
    .map(m => [m.agent_key || 'coordinator', m]));
}

export function resolveAgentTarget(text, explicitKey, agents = []) {
  const plain = String(text).replace(/```[\s\S]*?```|`[^`]*`|^\s*>[^\n]*/gm, '');
  const tokens = [...plain.matchAll(/(?<![\p{L}\p{N}_@])@([a-zA-Z][a-zA-Z0-9_-]*|[\u3400-\u9fff]+)/gu)].map(m => m[1]);
  const keys = new Set();
  for (const token of tokens) {
    const found = agents.filter(a => a.agent_key === token || a.display_name === token);
    if (found.length !== 1) throw new Error(uiText("agentModel.noUniqueAgentFoundFor", {v0: (token)}));
    keys.add(found[0].agent_key);
  }
  if (keys.size > 1 || (keys.size && explicitKey && !keys.has(explicitKey))) throw new Error(uiText("agentModel.chooseOneAgentPerConversationUseBatchDelegationFor"));
  const key = explicitKey || [...keys][0] || 'coordinator';
  const agent = agents.find(a => a.agent_key === key);
  if (!agent || !agent.enabled || agent.role_kind === 'observer' || agent.runtime_kind !== 'builtin_llm') throw new Error(uiText("agentModel.thisAgentCannotReceiveChatMessagesRightNow"));
  return key;
}

export function agentSuggestions(text, agents = []) {
  const match = String(text).match(/(?:^|\s)@([\p{L}\p{N}_-]*)$/u);
  if (!match) return [];
  return agents.filter(a => a.enabled && a.role_kind !== 'observer' && a.runtime_kind === 'builtin_llm' &&
    (a.agent_key.includes(match[1]) || a.display_name.includes(match[1])));
}

export function messagePersona(message) {
  const profile = message.agent_snapshot || {};
  return `${profile.icon || '✦'} ${profile.display_name || message.agent_key || uiText("agentModel.studioAssistant")}${message.model ? ` · ${message.model}` : ''}`;
}
