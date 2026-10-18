import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { api } from "./api.js";
import { Dialog } from "./Dialog.jsx";
import { shortTime } from "./format.js";
import { Avatar } from "./Talk.jsx";

// 修改紀錄（10/15 起大家一起編輯：大家都能改字，所以大家都要看得到誰改了什麼、改錯了能改回）。
// 一筆＝同一個人連續改的一次；每一處都可以單獨改回，改回本身也記成一筆。
export const HISTORY_RULE = "The crew can see and restore changes. Consecutive edits by one person form a revision; editing after a 10-minute pause starts another."
  + "Restoring affects only the selected content. Other edits remain, and the restoration is recorded as a new revision.";
const SHOWN = 3; // 一筆先列幾處，其他的收在「還有 N 處」

export function headline(group) {
  const n = group.changes.length;
  if (group.kind === "create") return "Created Page";
  if (group.kind === "revert") return `Restore ${n}  changes`;
  if (group.kind === "restore") return `Restored this page to an earlier revision, changing ${n}  changes`;
  if (group.kind === "rewrite") return `Rewrote the page, changing ${n}  changes`;
  return n ? `Changed ${n}  changes` : null; // 沒有差別：另外寫「改了又改回」
}

function Segments({ segments }) {
  const changed = segments.some(([kind]) => kind !== "=");
  return (
    <div className="txt">
      {segments.map(([kind, text], index) => {
        if (kind === "-") return <del key={index}>{text}</del>;
        if (kind === "+") return <ins key={index}>{text}</ins>;
        return <span key={index} className={changed ? "ctx" : undefined}>{text}</span>;
      })}
    </div>
  );
}

export function HistoryPanel({ open, slug, tabKey, tabTitle, version, onPick, onReverted, flush, onClose, onError, onToast }) {
  const ref = useRef(null);
  const [scope, setScope] = useState("tab");
  const [data, setData] = useState(null);
  const [expanded, setExpanded] = useState(() => new Set());
  const [busy, setBusy] = useState(null);
  const [confirm, setConfirm] = useState(null);

  const load = useCallback(async () => {
    const key = scope === "tab" ? tabKey : null;
    try {
      const payload = await api.get(`/projects/api/${slug}/history` + (key ? `?tab=${encodeURIComponent(key)}` : ""));
      setData({ scope, key, ...payload });
    } catch (error) {
      onError(error.message);
    }
  }, [slug, scope, tabKey, onError]);

  useEffect(() => { if (open) load(); }, [open, load, version]);

  useEffect(() => {
    if (!open) return undefined;
    const close = (event) => {
      if (ref.current && !ref.current.contains(event.target) && !event.target.closest(".hist-link, .modal-scrim")) onClose();
    };
    const esc = (event) => { if (event.key === "Escape" && !document.querySelector(".modal-scrim")) onClose(); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open, onClose]);

  const revert = async (group, change, force = false) => {
    if (flush && (await flush()) === false) {
      onError("Save pending edits before restoring a revision.");
      return;
    }
    const body = change.field_id
      ? { field_id: change.field_id, value: change.value, after_activity: change.after_activity }
      : { from_rev: group.from_rev, to_rev: group.to_rev, bid: change.bid, ...(change.rid ? { rid: change.rid } : {}) };
    setBusy(group.id + "|" + change.key);
    try {
      const result = await api.post(`/projects/api/${slug}/tabs/${group.tab_key}/revert`, force ? { ...body, force: true } : body);
      setConfirm(null);
      onToast(result.already ? "This content already matches its earlier version." : "Restored. This restoration is also recorded in Change History.");
      onReverted(group.tab_key, result, Boolean(change.field_id));
      load();
    } catch (error) {
      if (error.status === 409 && error.data && error.data.code === "changed_later") {
        setConfirm({ group, change, info: error.data });
      } else {
        setConfirm(null);
        onError(error.message);
      }
    } finally {
      setBusy(null);
    }
  };

  if (!open) return null;

  const item = (group) => {
    const all = group.changes;
    const isOpen = expanded.has(group.id);
    const list = isOpen ? all : all.slice(0, SHOWN);
    const head = headline(group);
    return (
      <div className="grp" key={group.id}>
        <div className="grp-hd">
          <Avatar id={group.actor_id || ""} name={group.name} size={18} />
          <b>{group.name}</b>
          {head || <span className="noop">No difference after restoring</span>}
          <span className="t">{shortTime(group.at)}</span>
        </div>
        {scope === "all" && group.tab_title && <div className="grp-tab">{group.tab_title}</div>}
        {list.map((change) => {
          const key = group.id + "|" + change.key;
          return (
            <div className="ch" key={change.key} role="button" tabIndex={0} title={"Locate on Page"}
              onClick={() => onPick(group, change)} onKeyDown={(event) => { if (event.key === "Enter") onPick(group, change); }}>
              <div className="what">
                {change.label}
                {change.button && (
                  <span className="acts">
                    <button type="button" className="ghost xs" disabled={busy === key}
                      onClick={(event) => { event.stopPropagation(); revert(group, change); }}>
                      {busy === key ? "Restoring…" : change.button}
                    </button>
                  </span>
                )}
              </div>
              {change.segments.length > 0 && <Segments segments={change.segments} />}
            </div>
          );
        })}
        {all.length > SHOWN && !isOpen && (
          <button type="button" className="more-ch" onClick={() => setExpanded(new Set(expanded).add(group.id))}>
            Also {all.length - SHOWN}  changes ▾
          </button>
        )}
      </div>
    );
  };

  const current = data && data.scope === scope && (scope === "all" || data.key === tabKey) ? data : null;
  let body;
  if (!current) body = <div className="empty">Loading…</div>;
  else if (!current.groups.length) body = <div className="empty">No changes recorded yet.</div>;
  else {
    body = current.groups.map(item);
    if (current.more) body.push(<div className="empty" key="more">Showing the latest {current.groups.length}  items</div>);
  }

  let dialog = null;
  if (confirm) {
    const { group, change, info } = confirm;
    const unit = change.field_id ? "this cell" : change.rid ? "this row" : "this passage";
    const people = (info.later || []).map((p) => p.name).join("、") || "Another crew member";
    const last = (info.later || []).slice(-1)[0];
    dialog = createPortal(
      <Dialog title={`${change.button}？`} confirmLabel={"Restore"}
        message={`${unit}after${group.name} changed it,${people} changed it again${last ? `(${shortTime(last.at)})` : ""}. Restoring will also replace${people}’s changes.`}
        onConfirm={() => revert(group, change, true)} onCancel={() => setConfirm(null)}>
        <div className="hist-preview">
          <div className="hd">After restoring</div>
          {info.preview || "(empty)"}
        </div>
      </Dialog>,
      document.body,
    );
  }

  return (
    <div className="pop on hist" ref={ref} role="dialog" aria-label={"Change History"}>
      <div className="pop-hd">
        <b>Change History</b>
        {scope === "tab" && tabTitle && <span className="pop-sub">{tabTitle}</span>}
      </div>
      <div className="pop-tabs">
        <button type="button" className={scope === "tab" ? "on" : undefined} onClick={() => setScope("tab")}>This Page</button>
        <button type="button" className={scope === "all" ? "on" : undefined} onClick={() => setScope("all")}>All Pages</button>
        <span className="info" tabIndex={0} data-tip={HISTORY_RULE} aria-label={HISTORY_RULE}>ⓘ</span>
      </div>
      <div className="pop-list">{body}</div>
      {dialog}
    </div>
  );
}
