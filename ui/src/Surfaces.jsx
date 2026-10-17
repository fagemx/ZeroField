import { useState } from "react";

import { api } from "./api.js";
import { shortTime } from "./format.js";
import { Avatar } from "./Talk.jsx";
import { WorkspaceSettings } from "./WorkspaceSettings.jsx";
import { SheetDialog } from "./SheetDialog.jsx";

export const PROJECT_STATUS = {
  planning: { label: "規劃／對齊中", color: "#5b5bd6", bg: "#eef0ff" },
  active: { label: "進行中", color: "#0d7a5f", bg: "#e6f6f1" },
  recurring: { label: "日常營運", color: "#0369a1", bg: "#e0f2fe" },
  blocked: { label: "卡關待決議", color: "#b45309", bg: "#fef3c7" },
  archived: { label: "已封存", color: "#64748b", bg: "#f1f5f9" },
};

export function IdentityBadge({ me, members }) {
  const list = members || [];
  if (list.length <= 1 || me.auth_mode !== "dev") {
    return (
      <span className="me" title={`以 ${me.name}（${me.role_label}）登入`}>
        <Avatar id={me.actor_id} name={me.name} size={26} />
        <span className="name">{me.name}</span>
        <small>{me.role_label}</small>
      </span>
    );
  }
  return (
    <span className="me" title="切換目前操作身分（Dev / 展示模式）">
      <Avatar id={me.actor_id} name={me.name} size={26} />
      <select
        aria-label="切換身分"
        value={me.actor_id}
        onChange={(e) => {
          const next = encodeURIComponent(window.location.pathname + window.location.hash);
          window.location.href = `/__who?actor=${encodeURIComponent(e.target.value)}&next=${next}`;
        }}
        style={{ border: "none", background: "transparent", font: "inherit", fontWeight: 600, cursor: "pointer" }}
      >
        {list.map((m) => (
          <option key={m.actor_id} value={m.actor_id}>
            {m.name}（{m.role_label}）
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
  const [template, setTemplate] = useState("blank");
  const [summary, setSummary] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const projects = data.projects || [];
  const me = data.me;
  const writable = me?.can_write !== false;
  const shown = projects.filter((p) => (filter === "all" || (p.status || "active") === filter) && `${p.title} ${p.summary || ""}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  const templates = [
    {key: "blank", icon: "▤", title: "空白專案", detail: "從一份總覽開始，依需要加入文件與表格。"},
    {key: "marketing", icon: "↗", title: "行銷與數據", detail: "專案總覽、成效日報與分析流程。"},
    {key: "art_studio", icon: "◈", title: "美術與資產", detail: "風格規範、資產交付與審核流程。"},
    {key: "ai_drama", icon: "▧", title: "影劇製作", detail: "劇本、角色設定、分鏡與製作流程。"},
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
    <header className="top"><span className="doc-name"><span className="brand-mark">o</span> OpenBench</span><span className="spacer" />{me && <WorkspaceSettings me={me} onReload={onReload} />}{me && <IdentityBadge me={me} members={data.members} />}</header>
    <main className="hub-page">
      <header className="hub-heading"><div><span className="canvas-eyebrow">你的工作空間</span><h1>讓資料與工作，放在一起。</h1><p>整理文件與表格，和團隊討論，再交給代理協助。</p></div>{writable && <button className="primary hub-create" onClick={() => { setTitle(""); setSummary(""); setSlug(""); setTemplate("blank"); setError(""); setCreating(true); }}>＋ 新增專案</button>}</header>
      <div className="hub-guide"><span><b>01</b> 放入文件或表格</span><span><b>02</b> 描述要完成的工作</span><span><b>03</b> 確認提案，更新內容</span></div>
      <div className="hub-filter"><h2>所有專案 <small>{projects.length}</small></h2><input aria-label="搜尋專案" placeholder="搜尋專案…" value={query} onChange={(e) => setQuery(e.target.value)} /><select aria-label="專案狀態篩選" value={filter} onChange={(e) => setFilter(e.target.value)}><option value="all">全部狀態</option>{Object.entries(PROJECT_STATUS).map(([key, cfg]) => <option key={key} value={key}>{cfg.label}</option>)}</select></div>
      {error && !creating && <p className="canvas-error" role="alert">{error}</p>}
      {!shown.length && <div className="hub-empty"><h3>{projects.length ? "沒有符合條件的專案" : "從你正在做的工作開始"}</h3><p>{projects.length ? "試試其他名稱或狀態。" : "建立專案後，可以匯入現有檔案，也可以自己新增分頁。"}</p></div>}
      <div className="hub-projects">{shown.map((p) => {
        const st = PROJECT_STATUS[p.status || "active"] || PROJECT_STATUS.active;
        return <article className="hub-card" key={p.slug}><div className="hub-card-top"><span className="hub-project-icon">▤</span><select disabled={!writable} aria-label={`${p.title} 狀態`} value={p.status || "active"} style={{color: st.color, background: st.bg}} onChange={async (e) => { try { await api.post(`/projects/api/${p.slug}/meta`, {status: e.target.value}); onReload(); } catch (err) { setError(err.message); } }}>{Object.entries(PROJECT_STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select></div><a className="hub-project-title" href={`/projects/${p.slug}/`}>{p.title}</a><p>{p.summary || "一起整理資料、討論與處理工作。"}</p><footer><span>{p.tab_count != null ? `${p.tab_count} 個分頁` : "開啟專案"}</span><span>{shortTime(p.updated_at)} 更新</span></footer></article>;
      })}</div>
    </main>
    {creating && <SheetDialog title="建立新專案" wide onClose={closeCreate}><form onSubmit={create}>
      <label className="modal-field"><span>專案名稱</span><input data-autofocus required maxLength={200} value={title} placeholder="例如：十月工作計畫、網站改版" onChange={(e) => setTitle(e.target.value)} /></label>
      <label className="modal-field"><span>想完成什麼？ <small>選填</small></span><input maxLength={400} value={summary} placeholder="用一句話記下這個專案的目標" onChange={(e) => setSummary(e.target.value)} /></label>
      <fieldset className="template-options"><legend>從哪裡開始</legend>{templates.map((item) => <label className={template === item.key ? "chosen" : ""} key={item.key}><input type="radio" name="template" value={item.key} checked={template === item.key} onChange={() => setTemplate(item.key)} /><span className="template-icon">{item.icon}</span><span><b>{item.title}</b><small>{item.detail}</small></span></label>)}</fieldset>
      <p className="sheet-subtle">範本只提供起點，分頁、欄位和工作流程都可以調整。</p>
      <details className="project-advanced"><summary>網址設定</summary><label className="modal-field"><span>網址代號（留空自動產生）</span><input value={slug} pattern="[a-z0-9][a-z0-9-]{0,40}" maxLength={41} placeholder="例如：team-plan" onChange={(e) => setSlug(e.target.value.toLowerCase())} /></label></details>
      {error && <p className="canvas-error" role="alert">{error}</p>}<div className="sheet-dialog-actions"><span className="spacer" /><button type="button" disabled={busy} onClick={closeCreate}>取消</button><button className="primary" type="submit" disabled={busy || !title.trim()}>{busy ? "建立中…" : "建立專案"}</button></div>
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
        <b>{isSheet ? "表格 · 文件與標註" : "工作流 · 文件與標註"}</b>
        <span style={{ marginLeft: 8, color: "#4b5563" }}>
          你可以在這裡使用螢光筆畫重點與文字標註，或隨時切回專屬畫布。
        </span>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        {onSwitchCanvasMode && (
          <button type="button" className="icon-btn pa-btn on" onClick={onSwitchCanvasMode}>
            {isSheet ? "返回表格" : "返回工作流"}
          </button>
        )}
        {onAskAgent && (
          <button
            type="button"
            className="icon-btn"
            onClick={() => onAskAgent(
              isSheet
                ? `請幫我檢查「${tab.title}」這張表格的欄位與目前待填項目`
                : `請幫我規劃「${tab.title}」這個節點工作流的代理串接步驟`
            )}
          >
            ✦ 請代理協助此畫布
          </button>
        )}
      </div>
    </div>
  );
}
