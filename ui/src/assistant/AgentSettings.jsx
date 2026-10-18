import { useEffect, useState } from 'react';
import { api } from '../api.js';

const blank = () => ({ agent_key: '', display_name: '', icon: '🤖', role_kind: 'worker', system_prompt: '', knowledge_pack: '',
  enabled: true, max_concurrency: 2, allowed_tools: [], provider_config: {} });

export function AgentSettings({ slug, onSaved }) {
  const [agents, setAgents] = useState([]), [draft, setDraft] = useState(blank), [provider, setProvider] = useState('{}');
  const [error, setError] = useState(''), [busy, setBusy] = useState(false), [editing, setEditing] = useState(false), [active, setActive] = useState(false);
  const reload = async () => setAgents((await api.get(`/projects/api/${slug}/agents`)).agents.filter(a => !a.agent_key.startsWith('limb:')));
  useEffect(() => { let active = true; api.get(`/projects/api/${slug}/agents`).then(data => {
    if (active) setAgents(data.agents.filter(a => !a.agent_key.startsWith('limb:')));
  }).catch(e => active && setError(e.message)); return () => { active = false; }; }, [slug]);
  const choose = agent => {
    setDraft(agent ? { ...blank(), ...agent } : blank()); setProvider(JSON.stringify(agent?.provider_config || {}, null, 2));
    setEditing(Boolean(agent)); setError(''); setActive(true);
  };
  const field = (key, value) => setDraft(current => ({ ...current, [key]: value }));
  const toolNames = [...new Set(agents.flatMap(a => a.allowed_tools || []))].sort();
  const save = async event => {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const payload = Object.fromEntries(Object.keys(blank()).map(key => [key, draft[key]]));
      payload.provider_config = JSON.parse(provider);
      await api.post(`/projects/api/${slug}/agents`, payload); await reload(); onSaved?.();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  return <section className="agent-settings"><h3>Specialist Agents</h3>
    {error && <p className="error" role="alert">{error}</p>}
    <div className="agent-roster-edit">{agents.map(agent => <button type="button" key={agent.agent_key} onClick={() => choose(agent)}>
      {agent.icon} {agent.display_name}{agent.enabled ? '' : "(disabled)"}</button>)}<button type="button" onClick={() => choose(null)}>＋ Custom Agent</button></div>
    {active && <form onSubmit={save}>
      <label>Agent Key<input required pattern="[a-z][a-z0-9_-]{0,63}" value={draft.agent_key} readOnly={editing} onChange={e => field('agent_key', e.target.value)} /></label>
      <label>Display Name<input required maxLength={120} value={draft.display_name} onChange={e => field('display_name', e.target.value)} /></label>
      <label>Icon<input maxLength={20} value={draft.icon} onChange={e => field('icon', e.target.value)} /></label>
      <label>Role<select value={draft.role_kind} onChange={e => field('role_kind', e.target.value)}><option value="primary">Coordinator</option><option value="worker">Specialist</option><option value="observer">Read-only Observer</option></select></label>
      <label>Role Instructions<textarea rows={5} maxLength={30000} value={draft.system_prompt} onChange={e => field('system_prompt', e.target.value)} /></label>
      <label>Knowledge Pack<textarea rows={3} maxLength={50000} value={draft.knowledge_pack} onChange={e => field('knowledge_pack', e.target.value)} /></label>
      <fieldset><legend>Allowed Tools</legend><div className="agent-tool-options">{toolNames.map(name => <label key={name}>
        <input type="checkbox" checked={draft.allowed_tools.includes(name)} onChange={e => field('allowed_tools', e.target.checked ? [...draft.allowed_tools, name] : draft.allowed_tools.filter(n => n !== name))} />{name}</label>)}</div></fieldset>
      <label>Model Configuration<textarea rows={4} spellCheck={false} value={provider} onChange={e => setProvider(e.target.value)} /></label>
      <small>Use {} to inherit the default model. Supported keys: kind, base_url, model, effort, api_key_env. Reference credentials by an environment variable allowed by the deployment.</small>
      <label>Concurrency Limit<input type="number" min={1} max={32} value={draft.max_concurrency} onChange={e => field('max_concurrency', Number(e.target.value))} /></label>
      <label><input type="checkbox" checked={draft.enabled} onChange={e => field('enabled', e.target.checked)} />Enabled</label>
      <button type="submit" disabled={busy}>{busy ? "Saving…" : "Save Agent"}</button>
    </form>}
  </section>;
}
