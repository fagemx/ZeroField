import { roleLabel } from '../format.js';
import { useLocale } from '../i18n/react.jsx';
import { t as uiText } from '../i18n/index.js';
import { useCallback, useEffect, useState } from "react";

import { api } from "../api.js";
import { shortTime } from "../format.js";
import { clip } from "./text.js";

const REPORT_STATE = {
  get published() { return uiText("managerPanel.updated"); }, get leak() { return uiText("managerPanel.possibleSensitiveValuesFoundTheExistingIndexWasRetained"); }, get no_source() { return uiText("managerPanel.folderNotFound"); },
  get empty() { return uiText("managerPanel.noWorkbooksInThisFolder"); }, get error() { return uiText("managerPanel.couldNotLoad"); },
};

export function ManagerPanel({ slug, onError, onToast }) {
  const locale = useLocale();
  const base = `/projects/api/${slug}/assistant`;
  const [data, setData] = useState(null);
  const [note, setNote] = useState("");
  const [target, setTarget] = useState("");
  const [answers, setAnswers] = useState({});
  const [source, setSource] = useState("");

  const load = useCallback(async () => {
    try {
      const result = await api.get(`${base}/manager`);
      setData(result);
      setSource(result.report.source || "");
    } catch (error) {
      onError(error.message);
    }
  }, [base, onError]);
  useEffect(() => { load(); }, [load]);

  const post = async (path, body, message) => {
    try {
      const result = await api.post(`${base}${path}`, body);
      if (result.stats) setData(result);
      else await load();
      if (message) onToast(message);
      return result;
    } catch (error) {
      onError(error.message);
      return null;
    }
  };

  if (!data) return <div className="kai-body">{uiText("managerPanel.loading")}</div>;
  const open = data.forwards.filter((f) => f.status === "open");
  const answered = data.forwards.filter((f) => f.status === "answered").slice(-5).reverse();
  const stats = data.stats;
  const report = data.report.status;
  const enabled = data.members.filter((m) => m.enabled);
  const nameOf = (id) => (data.members.find((m) => m.actor_id === id) || {}).name || uiText("managerPanel.noLongerOnTheCrew");
  return (
    <div className="kai-body">
      <h4>{uiText("managerPanel.assignToStudioAssistant")}</h4>
      {data.notes.filter((n) => n.status === "open").map((n) => (
        <div className="item" key={n.id}>{n.body}
          <small>{uiText("managerPanel.assignmentShownWhenTheRecipientNextOpensTheAssistant", {v0: (n.target_id ? uiText("managerPanel.for", {v0: (nameOf(n.target_id))}) : uiText("managerPanel.forEveryone")), v1: (shortTime(n.created_at))})}<button type="button" className="link" onClick={() => post(`/notes/${n.id}/done`, {}, "Marked complete")}>{uiText("managerPanel.complete")}</button></small>
        </div>
      ))}
      <textarea value={note} rows={2} placeholder={uiText("managerPanel.forExampleReviewTheShotListBeforeMondayS")} onChange={(event) => setNote(event.target.value)} />
      <div className="row-end">
        <select value={target} onChange={(event) => setTarget(event.target.value)} aria-label={uiText("managerPanel.assignTo")}>
          <option value="">{uiText("managerPanel.allEnabledCrew")}</option>
          {enabled.map((m) => <option key={m.actor_id} value={m.actor_id}>{uiText("managerPanel.for2", {v0: (m.name), v1: (roleLabel(m.role, m.role_label))})}</option>)}
        </select>
        <button type="button" className="btn primary" disabled={!note.trim()} style={{ marginLeft: 8 }}
          onClick={async () => {
            const body = target ? { body: note.trim(), target_id: target } : { body: note.trim() };
            if (await post("/notes", body, "Assigned. The recipient will see this when they next open the assistant.")) setNote("");
          }}>{uiText("managerPanel.assign")}</button>
      </div>

      <h4>{uiText("managerPanel.privateQuestionsForYou")}</h4>
      {!open.length && <div className="item muted">{uiText("managerPanel.noneAtTheMoment")}</div>}
      {open.map((f) => (
        <div className="item" key={f.id}><b>{f.owner_name || uiText("managerPanel.crew")}</b>：{f.question}<small>{shortTime(f.created_at)}</small>
          <textarea rows={2} value={answers[f.id] || ""} placeholder={uiText("managerPanel.yourReplyWillAppearInTheRecipientSAssistant")}
            onChange={(event) => setAnswers({ ...answers, [f.id]: event.target.value })} />
          <div className="row-end">
            <button type="button" className="btn primary" disabled={!(answers[f.id] || "").trim()}
              onClick={() => post(`/forwards/${f.id}/answer`, { answer: answers[f.id].trim() }, "Replied")}>{uiText("managerPanel.reply")}</button>
          </div>
        </div>
      ))}
      {answered.map((f) => <div className="item muted" key={f.id}>{clip(f.question, 40)}<small>{uiText("managerPanel.replied", {v0: (shortTime(f.answered_at))})}</small></div>)}

      <h4>{uiText("managerPanel.appliedAssistantProposals")}</h4>
      {!data.applied.length && <div className="item muted">{uiText("managerPanel.noneYet")}</div>}
      {data.applied.slice().reverse().map((p) => (
        <div className="item" key={p.id}><b>{p.target && p.target.display}</b>：{clip(p.content, 90)}
          <small>{uiText("managerPanel.approvedStudioAssistant", {v0: (p.owner_name), v1: (shortTime(p.decided_at))})}</small></div>
      ))}

      <h4>{uiText("managerPanel.lastDays")}</h4>
      <div className="stats">
        <div className="stat"><b>{stats.questions}</b><span>{uiText("managerPanel.requests")}</span></div>
        <div className="stat"><b>{stats.proposals_applied}</b><span>{uiText("managerPanel.applied")}</span></div>
        <div className="stat"><b>{stats.forwarded}</b><span>{uiText("managerPanel.forwardedToYou")}</span></div>
        <div className="stat"><b>{stats.failed}</b><span>{uiText("managerPanel.incomplete")}</span></div>
      </div>

      <h4>{uiText("managerPanel.agentAccess")}</h4>
      {data.members.map((m) => (
        <label className="item member" key={m.actor_id}>
          <input type="checkbox" checked={m.enabled}
            onChange={(event) => post("/members", { actor_id: m.actor_id, enabled: event.target.checked },
              event.target.checked ? `Enabled for ${m.name}` : `Disabled for ${m.name}`)} />
          {m.name}<small>{roleLabel(m.role, m.role_label)}</small>
        </label>
      ))}

      <h4>{uiText("managerPanel.workbookFolder")}</h4>
      <div className="item">
        {report ? <>{uiText("managerPanel.index", {v0: (REPORT_STATE[report.state] || report.state), v1: (report.files ? `(${report.files}  workbooks)` : "")})}<small>{shortTime(report.checked_at)}</small></>
          : uiText("managerPanel.noIndexYet")}
        <input value={source} placeholder={uiText("managerPanel.forExampleDataReportsOrASharedWorkbookFolder")} onChange={(event) => setSource(event.target.value)} />
        <div className="row-end">
          <button type="button" className="btn" disabled={!source.trim()}
            onClick={() => post("/settings", { report_source: source.trim() }, "Configured. The index will be ready within 10 minutes.")}>{uiText("managerPanel.configure")}</button>
        </div>
      </div>
      <div className="privacy">{uiText("managerPanel.privateConversationsRemainPrivateYouCanSeeAppliedProposals")}</div>
    </div>
  );
}
