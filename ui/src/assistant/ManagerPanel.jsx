import { useCallback, useEffect, useState } from "react";

import { api } from "../api.js";
import { shortTime } from "../format.js";
import { clip } from "./text.js";

const REPORT_STATE = {
  published: "已更新", leak: "有疑似數字，這次沒有發布（舊的照用）", no_source: "找不到這個資料夾",
  empty: "資料夾裡沒有報表", error: "讀取失敗",
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

  if (!data) return <div className="kai-body">載入中…</div>;
  const open = data.forwards.filter((f) => f.status === "open");
  const answered = data.forwards.filter((f) => f.status === "answered").slice(-5).reverse();
  const stats = data.stats;
  const report = data.report.status;
  const enabled = data.members.filter((m) => m.enabled);
  const nameOf = (id) => (data.members.find((m) => m.actor_id === id) || {}).name || "（已離開名單）";
  return (
    <div className="kai-body">
      <h4>交代給專案助理</h4>
      {data.notes.filter((n) => n.status === "open").map((n) => (
        <div className="item" key={n.id}>{n.body}
          <small>{n.target_id ? `給 ${nameOf(n.target_id)}` : "給所有人"} · {shortTime(n.created_at)} 交代 · 對方下次打開助理時，助理會先帶他做
            <button type="button" className="link" onClick={() => post(`/notes/${n.id}/done`, {}, "已標成完成")}>完成</button></small>
        </div>
      ))}
      <textarea value={note} rows={2} placeholder="例如：下週一前確認 Google 的安裝轉換動作" onChange={(event) => setNote(event.target.value)} />
      <div className="row-end">
        <select value={target} onChange={(event) => setTarget(event.target.value)} aria-label="交代給誰">
          <option value="">給所有開放的人</option>
          {enabled.map((m) => <option key={m.actor_id} value={m.actor_id}>給 {m.name}（{m.role_label}）</option>)}
        </select>
        <button type="button" className="btn primary" disabled={!note.trim()} style={{ marginLeft: 8 }}
          onClick={async () => {
            const body = target ? { body: note.trim(), target_id: target } : { body: note.trim() };
            if (await post("/notes", body, "已交代。對方下次打開助理時會先看到")) setNote("");
          }}>交代</button>
      </div>

      <h4>私下轉給你的問題</h4>
      {!open.length && <div className="item muted">目前沒有。</div>}
      {open.map((f) => (
        <div className="item" key={f.id}><b>{f.owner_name || "行銷"}</b>：{f.question}<small>{shortTime(f.created_at)}</small>
          <textarea rows={2} value={answers[f.id] || ""} placeholder="回覆會出現在對方的助理對話裡"
            onChange={(event) => setAnswers({ ...answers, [f.id]: event.target.value })} />
          <div className="row-end">
            <button type="button" className="btn primary" disabled={!(answers[f.id] || "").trim()}
              onClick={() => post(`/forwards/${f.id}/answer`, { answer: answers[f.id].trim() }, "已回覆")}>回覆</button>
          </div>
        </div>
      ))}
      {answered.map((f) => <div className="item muted" key={f.id}>{clip(f.question, 40)}<small>已回覆 · {shortTime(f.answered_at)}</small></div>)}

      <h4>經助理放上專案頁的</h4>
      {!data.applied.length && <div className="item muted">還沒有。</div>}
      {data.applied.slice().reverse().map((p) => (
        <div className="item" key={p.id}><b>{p.target && p.target.display}</b>：{clip(p.content, 90)}
          <small>{p.owner_name}確認 · 經專案助理 · {shortTime(p.decided_at)}</small></div>
      ))}

      <h4>最近 7 天</h4>
      <div className="stats">
        <div className="stat"><b>{stats.questions}</b><span>問了幾次</span></div>
        <div className="stat"><b>{stats.proposals_applied}</b><span>放上專案頁</span></div>
        <div className="stat"><b>{stats.forwarded}</b><span>轉給你的</span></div>
        <div className="stat"><b>{stats.failed}</b><span>沒答完</span></div>
      </div>

      <h4>誰可以用</h4>
      {data.members.map((m) => (
        <label className="item member" key={m.actor_id}>
          <input type="checkbox" checked={m.enabled}
            onChange={(event) => post("/members", { actor_id: m.actor_id, enabled: event.target.checked },
              event.target.checked ? `已開放給 ${m.name}` : `已關掉 ${m.name}`)} />
          {m.name}<small>{m.role_label}</small>
        </label>
      ))}

      <h4>報表資料夾</h4>
      <div className="item">
        {report ? <>索引：{REPORT_STATE[report.state] || report.state}{report.files ? `（${report.files} 本）` : ""}<small>{shortTime(report.checked_at)}</small></>
          : "還沒有索引。"}
        <input value={source} placeholder="例如 ./data/reports 或共用報表資料夾路徑" onChange={(event) => setSource(event.target.value)} />
        <div className="row-end">
          <button type="button" className="btn" disabled={!source.trim()}
            onClick={() => post("/settings", { report_source: source.trim() }, "已設定；10 分鐘內會建好索引")}>設定</button>
        </div>
      </div>
      <div className="privacy">你看不到對方和助理的對話內容，只看得到他確認放上來的東西、轉給你的問題和使用次數。</div>
    </div>
  );
}
