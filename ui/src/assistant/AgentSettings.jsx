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
  return <section className="agent-settings"><h3>專家代理</h3>
    {error && <p className="error" role="alert">{error}</p>}
    <div className="agent-roster-edit">{agents.map(agent => <button type="button" key={agent.agent_key} onClick={() => choose(agent)}>
      {agent.icon} {agent.display_name}{agent.enabled ? '' : '（停用）'}</button>)}<button type="button" onClick={() => choose(null)}>＋ 自訂代理</button></div>
    {active && <form onSubmit={save}>
      <label>代理代號<input required pattern="[a-z][a-z0-9_-]{0,63}" value={draft.agent_key} readOnly={editing} onChange={e => field('agent_key', e.target.value)} /></label>
      <label>顯示名稱<input required maxLength={120} value={draft.display_name} onChange={e => field('display_name', e.target.value)} /></label>
      <label>圖示<input maxLength={20} value={draft.icon} onChange={e => field('icon', e.target.value)} /></label>
      <label>角色<select value={draft.role_kind} onChange={e => field('role_kind', e.target.value)}><option value="primary">主控</option><option value="worker">專家</option><option value="observer">唯讀觀察</option></select></label>
      <label>角色指令<textarea rows={5} maxLength={30000} value={draft.system_prompt} onChange={e => field('system_prompt', e.target.value)} /></label>
      <label>知識包<textarea rows={3} maxLength={50000} value={draft.knowledge_pack} onChange={e => field('knowledge_pack', e.target.value)} /></label>
      <fieldset><legend>允許工具</legend><div className="agent-tool-options">{toolNames.map(name => <label key={name}>
        <input type="checkbox" checked={draft.allowed_tools.includes(name)} onChange={e => field('allowed_tools', e.target.checked ? [...draft.allowed_tools, name] : draft.allowed_tools.filter(n => n !== name))} />{name}</label>)}</div></fieldset>
      <label>模型設定<textarea rows={4} spellCheck={false} value={provider} onChange={e => setProvider(e.target.value)} /></label>
      <small>空物件沿用全域模型。可填 kind、base_url、model、effort、api_key_env；憑證只填部署者允許的環境變數名稱。</small>
      <label>同時執行上限<input type="number" min={1} max={32} value={draft.max_concurrency} onChange={e => field('max_concurrency', Number(e.target.value))} /></label>
      <label><input type="checkbox" checked={draft.enabled} onChange={e => field('enabled', e.target.checked)} />啟用</label>
      <button type="submit" disabled={busy}>{busy ? '儲存中…' : '儲存代理設定'}</button>
    </form>}
  </section>;
}
