import { useState } from "react";

import { api } from "./api.js";
import { shortTime } from "./format.js";
import { Avatar } from "./Talk.jsx";
import { WorkspaceSettings } from "./WorkspaceSettings.jsx";
import { SheetDialog } from "./SheetDialog.jsx";

export const PROJECT_STATUS = {
  planning: { label: "Planning", color: "#5b5bd6", bg: "#eef0ff" },
  active: { label: "In Progress", color: "#0d7a5f", bg: "#e6f6f1" },
  recurring: { label: "Ongoing", color: "#0369a1", bg: "#e0f2fe" },
  blocked: { label: "Blocked", color: "#b45309", bg: "#fef3c7" },
  archived: { label: "Archived", color: "#64748b", bg: "#f1f5f9" },
};

export function IdentityBadge({ me, members }) {
  const list = members || [];
  if (list.length <= 1 || me.auth_mode !== "dev") {
    return (
      <span className="me" title={`As ${me.name}(${me.role_label}) signed in`}>
        <Avatar id={me.actor_id} name={me.name} size={26} />
        <span className="name">{me.name}</span>
        <small>{me.role_label}</small>
      </span>
    );
  }
  return (
    <span className="me" title={"Switch Crew Identity (development / demo mode)"}>
      <Avatar id={me.actor_id} name={me.name} size={26} />
      <select
        aria-label={"Switch Identity"}
        value={me.actor_id}
        onChange={(e) => {
          const next = encodeURIComponent(window.location.pathname + window.location.hash);
          window.location.href = `/__who?actor=${encodeURIComponent(e.target.value)}&next=${next}`;
        }}
        style={{ border: "none", background: "transparent", font: "inherit", fontWeight: 600, cursor: "pointer" }}
      >
        {list.map((m) => (
          <option key={m.actor_id} value={m.actor_id}>
            {m.name}({m.role_label})
          </option>
        ))}
      </select>
    </span>
  );
}

export function ProjectHub({ data, onReload }) {
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const [slug, setSlug] = useState("");
  const [title, setTitle] = useState("");
  const [template, setTemplate] = useState("zerofield_studio");
  const [summary, setSummary] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const projects = data.projects || [];
  const me = data.me;
  const writable = me?.can_write !== false;
  const shown = projects.filter((p) => (filter === "all" || (p.status || "active") === filter) && `${p.title} ${p.summary || ""}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  const templates = [
    {key: "zerofield_studio", icon: "▧", title: "ZeroField Studio", detail: "Director brief, cast lookbook, cinema slate, V2V planning, and an editable pipeline."},
    {key: "blank", icon: "▤", title: "Blank Production", detail: "Start with a brief and add production pages as needed."},
  ];
  const closeCreate = () => { if (!busy) setCreating(false); };
  const create = async (event) => {
    event.preventDefault();
    if (!title.trim() || busy) return;
    setError(""); setBusy(true);
    try {
      const res = await api.post("/projects/api/projects", { slug: slug.trim().toLowerCase() || `project-${crypto.randomUUID().slice(0, 8)}`, title: title.trim(), template, status: "planning", summary: summary.trim() });
      if (res?.project) window.location.href = `/projects/${res.project.slug}/`;
      else { setCreating(false); onReload(); }
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  };
  return <div className="app hub-app">
    <header className="top"><span className="doc-name"><span className="brand-mark">ZF</span> ZeroField Studio</span><span className="spacer" />{me && <WorkspaceSettings me={me} onReload={onReload} />}{me && <IdentityBadge me={me} members={data.members} />}</header>
    <main className="hub-page">
      <header className="hub-heading"><div><span className="canvas-eyebrow">YOUR STUDIO</span><h1>From Script to Slate.</h1><p>Plan your film, direct the crew, and review every proposed change.</p></div>{writable && <button className="primary hub-create" onClick={() => { setTitle(""); setSummary(""); setSlug(""); setTemplate("zerofield_studio"); setError(""); setCreating(true); }}>＋ New Production</button>}</header>
      <div className="hub-guide"><span><b>01</b> Add a brief or slate</span><span><b>02</b> Describe the task</span><span><b>03</b> Review and apply changes</span></div>
      <div className="hub-filter"><h2>All Productions <small>{projects.length}</small></h2><input aria-label={"Search Productions"} placeholder={"Search productions…"} value={query} onChange={(e) => setQuery(e.target.value)} /><select aria-label={"Filter Productions by Status"} value={filter} onChange={(e) => setFilter(e.target.value)}><option value="all">All Statuses</option>{Object.entries(PROJECT_STATUS).map(([key, cfg]) => <option key={key} value={key}>{cfg.label}</option>)}</select></div>
      {error && !creating && <p className="canvas-error" role="alert">{error}</p>}
      {!shown.length && <div className="hub-empty"><h3>{projects.length ? "No Matching Productions" : "Start Your Next Production"}</h3><p>{projects.length ? "Try a different title or status." : "Create a production, import a brief, or build your slate from the studio template."}</p></div>}
      <div className="hub-projects">{shown.map((p) => {
        const st = PROJECT_STATUS[p.status || "active"] || PROJECT_STATUS.active;
        return <article className="hub-card" key={p.slug}><div className="hub-card-top"><span className="hub-project-icon">▤</span><select disabled={!writable} aria-label={`${p.title} Status`} value={p.status || "active"} style={{color: st.color, background: st.bg}} onChange={async (e) => { try { await api.post(`/projects/api/${p.slug}/meta`, {status: e.target.value}); onReload(); } catch (err) { setError(err.message); } }}>{Object.entries(PROJECT_STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select></div><a className="hub-project-title" href={`/projects/${p.slug}/`}>{p.title}</a><p>{p.summary || "Plan, discuss, and direct your production."}</p><footer><span>{p.tab_count != null ? `${p.tab_count}  pages` : "Open Production"}</span><span>Updated {shortTime(p.updated_at)}</span></footer></article>;
      })}</div>
    </main>
    {creating && <SheetDialog title={"New Production"} wide onClose={closeCreate}><form onSubmit={create}>
      <label className="modal-field"><span>Production Title</span><input data-autofocus required maxLength={200} value={title} placeholder={"For example: The Last Signal"} onChange={(e) => setTitle(e.target.value)} /></label>
      <label className="modal-field"><span>Production Goal <small>optional</small></span><input maxLength={400} value={summary} placeholder={"Describe the film or production goal in one sentence"} onChange={(e) => setSummary(e.target.value)} /></label>
      <fieldset className="template-options"><legend>Starting Point</legend>{templates.map((item) => <label className={template === item.key ? "chosen" : ""} key={item.key}><input type="radio" name="template" value={item.key} checked={template === item.key} onChange={() => setTemplate(item.key)} /><span className="template-icon">{item.icon}</span><span><b>{item.title}</b><small>{item.detail}</small></span></label>)}</fieldset>
      <p className="sheet-subtle">Templates are editable starting points. Customize the pages, columns, and pipeline.</p>
      <details className="project-advanced"><summary>URL Settings</summary><label className="modal-field"><span>URL Slug (leave empty to generate)</span><input value={slug} pattern="[a-z0-9][a-z0-9-]{0,40}" maxLength={41} placeholder={"For example: the-last-signal"} onChange={(e) => setSlug(e.target.value.toLowerCase())} /></label></details>
      {error && <p className="canvas-error" role="alert">{error}</p>}<div className="sheet-dialog-actions"><span className="spacer" /><button type="button" disabled={busy} onClick={closeCreate}>Cancel</button><button className="primary" type="submit" disabled={busy || !title.trim()}>{busy ? "Creating…" : "Create Production"}</button></div>
    </form></SheetDialog>}
  </div>;
}
export function SurfaceHeader({ tab, onAskAgent, onSwitchCanvasMode }) {
  const kind = (tab && tab.surface_type) || "doc";
  if (kind === "doc") return null;
  const isSheet = kind === "sheet";
  return (
    <div style={{
      maxWidth: 920, margin: "16px auto 0", padding: "12px 16px", borderRadius: 10,
      background: isSheet ? "#f0fdf4" : "#eef2ff",
      border: `1px solid ${isSheet ? "#bbf7d0" : "#c7d2fe"}`,
      display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap",
    }}>
      <div style={{ fontSize: 13, color: "#1f1e1c" }}>
        <b>{isSheet ? "Table · Document & Annotations" : "Pipeline · Document & Annotations"}</b>
        <span style={{ marginLeft: 8, color: "#4b5563" }}>
          Highlight and annotate this document, or return to its canvas at any time.
        </span>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        {onSwitchCanvasMode && (
          <button type="button" className="icon-btn pa-btn on" onClick={onSwitchCanvasMode}>
            {isSheet ? "Back to Table" : "Back to Pipeline"}
          </button>
        )}
        {onAskAgent && (
          <button
            type="button"
            className="icon-btn"
            onClick={() => onAskAgent(
              isSheet
                ? `Review the columns and missing information in “${tab.title}”.`
                : `Plan the agent connections for the pipeline “${tab.title}”.`
            )}
          >
            ✦ Ask an Agent About This Canvas
          </button>
        )}
      </div>
    </div>
  );
}
