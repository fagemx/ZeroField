import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import { AgentSettings } from './assistant/AgentSettings.jsx';

export function WorkspaceSettings({ me, project, onReload, onError }) {
  const dialog = useRef(null);
  const [open, setOpen] = useState(false), [data, setData] = useState(null), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const blank = { name: "", email: "", role: "member", status: "active" };
  const [form, setForm] = useState(blank);
  const work = async (fn) => { setBusy(true); setError(""); try { await fn(); } catch (e) { setError(e.message); } finally { setBusy(false); } };
  useEffect(() => { if (open) api.get("/projects/api/members").then(setData).catch((e) => setError(e.message)); }, [open]);
  useEffect(() => {
    if (!open) return undefined;
    const previous = document.activeElement;
    dialog.current?.querySelector('button')?.focus();
    const keydown = event => {
      if (event.key === 'Escape') setOpen(false);
      if (event.key === 'Tab') {
        const controls = [...(dialog.current?.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled)') || [])];
        const first = controls[0], last = controls.at(-1);
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    };
    document.addEventListener('keydown', keydown);
    return () => { document.removeEventListener('keydown', keydown); previous?.focus(); };
  }, [open]);
  if (!me?.can_edit) return null;
  return <><button className="icon-btn" onClick={() => setOpen(true)}>👥 成員與設定</button>{open && <div className="modal-scrim"><div ref={dialog} className="modal workspace-settings" role="dialog" aria-modal="true" aria-label="成員與專案設定"><h2>成員與設定</h2><p>成員角色適用於此工作台的所有專案。</p>
    {project && <label className="modal-field">代理資料存取<select value={project.privacy_mode || "full_access"} disabled={busy} onChange={(e) => work(async () => { await api.post(`/projects/api/${project.slug}/meta`, { privacy_mode: e.target.value }); await onReload(); })}><option value="full_access">完整存取：允許數字、公式與製作參數</option><option value="mask_numbers">數值遮罩：遮蔽敏感數字，不傳送圖片</option></select></label>}
    {error && <p role="alert" className="error">{error}</p>}
    {project && <AgentSettings slug={project.slug} onSaved={onReload} />}
    <div className="member-list">{data?.members.map((m) => <button key={m.actor_id} className="member-row" onClick={() => setForm(m)}><b>{m.name}</b><span>{data.roles[m.role]} · {m.status === "active" ? "啟用" : "停用"}</span></button>)}</div>
    <form onSubmit={(e) => { e.preventDefault(); work(async () => { const result = await api.post("/projects/api/members", form); setData(result); setForm(blank); await onReload(); }); }}><h3>{form.actor_id ? "編輯成員" : "新增成員"}</h3><label>姓名<input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label><label>電子郵件<input required type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label><label>角色<select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>{Object.entries(data?.roles || {}).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label><label>狀態<select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}><option value="active">啟用</option><option value="inactive">停用</option></select></label>{form.actor_id && <small>帳號 ID：{form.actor_id}</small>}<div className="canvas-toolbar"><button disabled={busy} type="submit">儲存成員</button><button type="button" onClick={() => setForm(blank)}>新增另一位</button></div></form><button onClick={() => setOpen(false)}>關閉</button>
  </div></div>}</>;
}
