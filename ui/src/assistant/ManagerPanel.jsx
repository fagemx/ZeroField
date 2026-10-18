import { useCallback, useEffect, useState } from "react";

import { api } from "../api.js";
import { shortTime } from "../format.js";
import { clip } from "./text.js";

const REPORT_STATE = {
  published: "Updated", leak: "Possible sensitive values found. The existing index was retained.", no_source: "Folder not found",
  empty: "No workbooks in this folder", error: "Could not load",
};

export function ManagerPanel({ slug, onError, onToast }) {
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

  if (!data) return <div className="kai-body">Loading…</div>;
  const open = data.forwards.filter((f) => f.status === "open");
  const answered = data.forwards.filter((f) => f.status === "answered").slice(-5).reverse();
  const stats = data.stats;
  const report = data.report.status;
  const enabled = data.members.filter((m) => m.enabled);
  const nameOf = (id) => (data.members.find((m) => m.actor_id === id) || {}).name || "(no longer on the crew)";
  return (
    <div className="kai-body">
      <h4>Assign to Studio Assistant</h4>
      {data.notes.filter((n) => n.status === "open").map((n) => (
        <div className="item" key={n.id}>{n.body}
          <small>{n.target_id ? `For ${nameOf(n.target_id)}` : "For Everyone"} · {shortTime(n.created_at)}  assignment · Shown when the recipient next opens the assistant
            <button type="button" className="link" onClick={() => post(`/notes/${n.id}/done`, {}, "Marked complete")}>Complete</button></small>
        </div>
      ))}
      <textarea value={note} rows={2} placeholder={"For example: review the shot list before Monday’s production meeting"} onChange={(event) => setNote(event.target.value)} />
      <div className="row-end">
        <select value={target} onChange={(event) => setTarget(event.target.value)} aria-label={"Assign To"}>
          <option value="">All Enabled Crew</option>
          {enabled.map((m) => <option key={m.actor_id} value={m.actor_id}>For {m.name}({m.role_label})</option>)}
        </select>
        <button type="button" className="btn primary" disabled={!note.trim()} style={{ marginLeft: 8 }}
          onClick={async () => {
            const body = target ? { body: note.trim(), target_id: target } : { body: note.trim() };
            if (await post("/notes", body, "Assigned. The recipient will see this when they next open the assistant.")) setNote("");
          }}>Assign</button>
      </div>

      <h4>Private Questions for You</h4>
      {!open.length && <div className="item muted">None at the moment.</div>}
      {open.map((f) => (
        <div className="item" key={f.id}><b>{f.owner_name || "Crew"}</b>：{f.question}<small>{shortTime(f.created_at)}</small>
          <textarea rows={2} value={answers[f.id] || ""} placeholder={"Your reply will appear in the recipient’s assistant conversation."}
            onChange={(event) => setAnswers({ ...answers, [f.id]: event.target.value })} />
          <div className="row-end">
            <button type="button" className="btn primary" disabled={!(answers[f.id] || "").trim()}
              onClick={() => post(`/forwards/${f.id}/answer`, { answer: answers[f.id].trim() }, "Replied")}>Reply</button>
          </div>
        </div>
      ))}
      {answered.map((f) => <div className="item muted" key={f.id}>{clip(f.question, 40)}<small>Replied ·  {shortTime(f.answered_at)}</small></div>)}

      <h4>Applied Assistant Proposals</h4>
      {!data.applied.length && <div className="item muted">None yet.</div>}
      {data.applied.slice().reverse().map((p) => (
        <div className="item" key={p.id}><b>{p.target && p.target.display}</b>：{clip(p.content, 90)}
          <small>{p.owner_name}Approved · Studio Assistant ·  {shortTime(p.decided_at)}</small></div>
      ))}

      <h4>Last 7 Days</h4>
      <div className="stats">
        <div className="stat"><b>{stats.questions}</b><span>Requests</span></div>
        <div className="stat"><b>{stats.proposals_applied}</b><span>Applied</span></div>
        <div className="stat"><b>{stats.forwarded}</b><span>Forwarded to You</span></div>
        <div className="stat"><b>{stats.failed}</b><span>Incomplete</span></div>
      </div>

      <h4>Agent Access</h4>
      {data.members.map((m) => (
        <label className="item member" key={m.actor_id}>
          <input type="checkbox" checked={m.enabled}
            onChange={(event) => post("/members", { actor_id: m.actor_id, enabled: event.target.checked },
              event.target.checked ? `Enabled for ${m.name}` : `Disabled for ${m.name}`)} />
          {m.name}<small>{m.role_label}</small>
        </label>
      ))}

      <h4>Workbook Folder</h4>
      <div className="item">
        {report ? <>Index:{REPORT_STATE[report.state] || report.state}{report.files ? `(${report.files}  workbooks)` : ""}<small>{shortTime(report.checked_at)}</small></>
          : "No index yet."}
        <input value={source} placeholder={"For example: ./data/reports or a shared workbook folder"} onChange={(event) => setSource(event.target.value)} />
        <div className="row-end">
          <button type="button" className="btn" disabled={!source.trim()}
            onClick={() => post("/settings", { report_source: source.trim() }, "Configured. The index will be ready within 10 minutes.")}>Configure</button>
        </div>
      </div>
      <div className="privacy">Private conversations remain private. You can see applied proposals, forwarded questions, and usage counts.</div>
    </div>
  );
}
