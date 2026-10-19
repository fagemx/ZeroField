import { roleLabel } from './format.js';
import { LanguageSwitch } from './i18n/react.jsx';
import { useLocale } from './i18n/react.jsx';
import { t as uiText } from './i18n/index.js';
import { useState } from "react";

import { api } from "./api.js";
import { shortTime } from "./format.js";
import { Avatar } from "./Talk.jsx";
import { WorkspaceSettings } from "./WorkspaceSettings.jsx";
import { SheetDialog } from "./SheetDialog.jsx";

export { StoryWorkbench as StudioModeBar } from './StoryWorkbenchModals.jsx';

export const PROJECT_STATUS = {
  planning: { get label() { return uiText("surfaces.planning"); }, color: "#5b5bd6", bg: "#eef0ff" },
  active: { get label() { return uiText("surfaces.inProgress"); }, color: "#0d7a5f", bg: "#e6f6f1" },
  recurring: { get label() { return uiText("surfaces.ongoing"); }, color: "#0369a1", bg: "#e0f2fe" },
  blocked: { get label() { return uiText("surfaces.blocked"); }, color: "#b45309", bg: "#fef3c7" },
  archived: { get label() { return uiText("surfaces.archived"); }, color: "#64748b", bg: "#f1f5f9" },
};

export function IdentityBadge({ me, members }) {
  const locale = useLocale();
  const list = members || [];
  if (list.length <= 1 || me.auth_mode !== "dev") {
    return (
      <span className="me" title={uiText("surfaces.asSignedIn", {v0: (me.name), v1: (roleLabel(me.role, me.role_label))})}>
        <Avatar id={me.actor_id} name={me.name} size={26} />
        <span className="name">{me.name}</span>
        <small>{roleLabel(me.role, me.role_label)}</small>
      </span>
    );
  }
  return (
    <span className="me" title={uiText("surfaces.switchCrewIdentityDevelopmentDemoMode")}>
      <Avatar id={me.actor_id} name={me.name} size={26} />
      <select
        aria-label={uiText("surfaces.switchIdentity")}
        value={me.actor_id}
        onChange={(e) => {
          const next = encodeURIComponent(window.location.pathname + window.location.hash);
          window.location.href = `/__who?actor=${encodeURIComponent(e.target.value)}&next=${next}`;
        }}
        style={{ border: "none", background: "transparent", font: "inherit", fontWeight: 600, cursor: "pointer" }}
      >
        {list.map((m) => (
          <option key={m.actor_id} value={m.actor_id}>
            {m.name}({roleLabel(m.role, m.role_label)})
          </option>
        ))}
      </select>
    </span>
  );
}

export function ProjectHub({ data, onReload }) {
  const locale = useLocale();
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
    {key: "zerofield_studio", icon: "▧", title: "ZeroField Studio", detail: uiText("surfaces.directorBriefCastLookbookCinemaSlateV2VPlanningAnd")},
    {key: "blank", icon: "▤", title: uiText("surfaces.blankProduction"), detail: uiText("surfaces.startWithABriefAndAddProductionPagesAs")},
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
    <header className="top"><span className="doc-name"><span className="brand-mark">ZF</span> ZeroField Studio</span><span className="spacer" /><LanguageSwitch />{me && <WorkspaceSettings me={me} onReload={onReload} />}{me && <IdentityBadge me={me} members={data.members} />}</header>
    <main className="hub-page">
      <header className="hub-heading"><div><span className="canvas-eyebrow">{uiText("surfaces.yOURSTUDIO")}</span><h1>{uiText("surfaces.fromScriptToSlate")}</h1><p>{uiText("surfaces.planYourFilmDirectTheCrewAndReviewEvery")}</p></div>{writable && <button className="primary hub-create" onClick={() => { setTitle(""); setSummary(""); setSlug(""); setTemplate("zerofield_studio"); setError(""); setCreating(true); }}>{uiText("surfaces.newProduction")}</button>}</header>
      <div className="hub-guide"><span><b>01</b>{uiText("surfaces.addABriefOrSlate")}</span><span><b>02</b>{uiText("surfaces.describeTheTask")}</span><span><b>03</b>{uiText("surfaces.reviewAndApplyChanges")}</span></div>
      <div className="hub-filter"><h2>{uiText("surfaces.allProductions")}<small>{projects.length}</small></h2><input aria-label={uiText("surfaces.searchProductions")} placeholder={uiText("surfaces.searchProductions2")} value={query} onChange={(e) => setQuery(e.target.value)} /><select aria-label={uiText("surfaces.filterProductionsByStatus")} value={filter} onChange={(e) => setFilter(e.target.value)}><option value="all">{uiText("surfaces.allStatuses")}</option>{Object.entries(PROJECT_STATUS).map(([key, cfg]) => <option key={key} value={key}>{cfg.label}</option>)}</select></div>
      {error && !creating && <p className="canvas-error" role="alert">{error}</p>}
      {!shown.length && <div className="hub-empty"><h3>{projects.length ? uiText("surfaces.noMatchingProductions") : uiText("surfaces.startYourNextProduction")}</h3><p>{projects.length ? uiText("surfaces.tryADifferentTitleOrStatus") : uiText("surfaces.createAProductionImportABriefOrBuildYour")}</p></div>}
      <div className="hub-projects">{shown.map((p) => {
        const st = PROJECT_STATUS[p.status || "active"] || PROJECT_STATUS.active;
        return <article className="hub-card" key={p.slug}><div className="hub-card-top"><span className="hub-project-icon">▤</span><select disabled={!writable} aria-label={uiText("surfaces.status", {v0: (p.title)})} value={p.status || "active"} style={{color: st.color, background: st.bg}} onChange={async (e) => { try { await api.post(`/projects/api/${p.slug}/meta`, {status: e.target.value}); onReload(); } catch (err) { setError(err.message); } }}>{Object.entries(PROJECT_STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select></div><a className="hub-project-title" href={`/projects/${p.slug}/`}>{p.title}</a><p>{p.summary || uiText("surfaces.planDiscussAndDirectYourProduction")}</p><footer><span>{p.tab_count != null ? uiText("surfaces.pageCount", {count: p.tab_count}) : uiText("surfaces.openProduction")}</span><span>{uiText("surfaces.updated", {v0: (shortTime(p.updated_at))})}</span></footer></article>;
      })}</div>
    </main>
    {creating && <SheetDialog title={uiText("surfaces.newProduction2")} wide onClose={closeCreate}><form onSubmit={create}>
      <label className="modal-field"><span>{uiText("surfaces.productionTitle")}</span><input data-autofocus required maxLength={200} value={title} placeholder={uiText("surfaces.forExampleTheLastSignal")} onChange={(e) => setTitle(e.target.value)} /></label>
      <label className="modal-field"><span>{uiText("surfaces.productionGoal")}<small>{uiText("surfaces.optional")}</small></span><input maxLength={400} value={summary} placeholder={uiText("surfaces.describeTheFilmOrProductionGoalInOneSentence")} onChange={(e) => setSummary(e.target.value)} /></label>
      <fieldset className="template-options"><legend>{uiText("surfaces.startingPoint")}</legend>{templates.map((item) => <label className={template === item.key ? "chosen" : ""} key={item.key}><input type="radio" name="template" value={item.key} checked={template === item.key} onChange={() => setTemplate(item.key)} /><span className="template-icon">{item.icon}</span><span><b>{item.title}</b><small>{item.detail}</small></span></label>)}</fieldset>
      <p className="sheet-subtle">{uiText("surfaces.templatesAreEditableStartingPointsCustomizeThePagesColumns")}</p>
      <details className="project-advanced"><summary>{uiText("surfaces.uRLSettings")}</summary><label className="modal-field"><span>{uiText("surfaces.uRLSlugLeaveEmptyToGenerate")}</span><input value={slug} pattern="[a-z0-9][a-z0-9-]{0,40}" maxLength={41} placeholder={uiText("surfaces.forExampleTheLastSignal2")} onChange={(e) => setSlug(e.target.value.toLowerCase())} /></label></details>
      {error && <p className="canvas-error" role="alert">{error}</p>}<div className="sheet-dialog-actions"><span className="spacer" /><button type="button" disabled={busy} onClick={closeCreate}>{uiText("surfaces.cancel")}</button><button className="primary" type="submit" disabled={busy || !title.trim()}>{busy ? uiText("surfaces.creating") : uiText("surfaces.createProduction")}</button></div>
    </form></SheetDialog>}
  </div>;
}
export function SurfaceHeader({ tab, onAskAgent, onSwitchCanvasMode }) {
  const locale = useLocale();
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
        <b>{isSheet ? uiText("surfaces.tableDocumentAnnotations") : uiText("surfaces.pipelineDocumentAnnotations")}</b>
        <span style={{ marginLeft: 8, color: "#4b5563" }}>{uiText("surfaces.highlightAndAnnotateThisDocumentOrReturnToIts")}</span>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        {onSwitchCanvasMode && (
          <button type="button" className="icon-btn pa-btn on" onClick={onSwitchCanvasMode}>
            {isSheet ? uiText("surfaces.backToTable") : uiText("surfaces.backToPipeline")}
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
          >{uiText("surfaces.askAnAgentAboutThisCanvas")}</button>
        )}
      </div>
    </div>
  );
}
