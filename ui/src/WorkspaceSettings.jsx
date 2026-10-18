import { roleLabel } from './format.js';
import { useLocale } from './i18n/react.jsx';
import { t as uiText } from './i18n/index.js';
import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import { AgentSettings } from './assistant/AgentSettings.jsx';

export function WorkspaceSettings({ me, project, onReload, onError }) {
  const locale = useLocale();
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
  return <><button className="icon-btn" onClick={() => setOpen(true)}>{uiText("workspaceSettings.crewSettings")}</button>{open && <div className="modal-scrim"><div ref={dialog} className="modal workspace-settings" role="dialog" aria-modal="true" aria-label={uiText("workspaceSettings.crewProductionSettings")}><h2>{uiText("workspaceSettings.crewSettings2")}</h2><p>{uiText("workspaceSettings.crewRolesApplyAcrossThisStudioSProductions")}</p>
    {project && <label className="modal-field">{uiText("workspaceSettings.agentDataAccess")}<select value={project.privacy_mode || "full_access"} disabled={busy} onChange={(e) => work(async () => { await api.post(`/projects/api/${project.slug}/meta`, { privacy_mode: e.target.value }); await onReload(); })}><option value="full_access">{uiText("workspaceSettings.fullAccessNumbersFormulasAndProductionParameters")}</option><option value="mask_numbers">{uiText("workspaceSettings.numericMaskingMaskSensitiveNumbersAndExcludeImages")}</option></select></label>}
    {error && <p role="alert" className="error">{error}</p>}
    {project && <AgentSettings slug={project.slug} onSaved={onReload} />}
    <div className="member-list">{data?.members.map((m) => <button key={m.actor_id} className="member-row" onClick={() => setForm(m)}><b>{m.name}</b><span>{roleLabel(m.role, data.roles[m.role])} · {m.status === "active" ? uiText("workspaceSettings.enabled") : uiText("workspaceSettings.disable")}</span></button>)}</div>
    <form onSubmit={(e) => { e.preventDefault(); work(async () => { const result = await api.post("/projects/api/members", form); setData(result); setForm(blank); await onReload(); }); }}><h3>{form.actor_id ? uiText("workspaceSettings.editCrewMember") : uiText("workspaceSettings.addCrewMember")}</h3><label>{uiText("workspaceSettings.name")}<input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label><label>{uiText("workspaceSettings.email")}<input required type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label><label>{uiText("workspaceSettings.role")}<select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>{Object.entries(data?.roles || {}).map(([key, value]) => <option key={key} value={key}>{roleLabel(key, value)}</option>)}</select></label><label>{uiText("workspaceSettings.status")}<select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}><option value="active">{uiText("workspaceSettings.enabled")}</option><option value="inactive">{uiText("workspaceSettings.disable")}</option></select></label>{form.actor_id && <small>{uiText("workspaceSettings.accountID", {v0: (form.actor_id)})}</small>}<div className="canvas-toolbar"><button disabled={busy} type="submit">{uiText("workspaceSettings.saveCrewMember")}</button><button type="button" onClick={() => setForm(blank)}>{uiText("workspaceSettings.addAnother")}</button></div></form><button onClick={() => setOpen(false)}>{uiText("workspaceSettings.close")}</button>
  </div></div>}</>;
}
