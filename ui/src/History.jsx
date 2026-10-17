import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { api } from "./api.js";
import { Dialog } from "./Dialog.jsx";
import { shortTime } from "./format.js";
import { Avatar } from "./Talk.jsx";

// 修改紀錄（10/15 起大家一起編輯：大家都能改字，所以大家都要看得到誰改了什麼、改錯了能改回）。
// 一筆＝同一個人連續改的一次；每一處都可以單獨改回，改回本身也記成一筆。
export const HISTORY_RULE = "名單上的人都看得到誰改了什麼，也都能改回。同一個人連續改的算一筆（停 10 分鐘以上算新的一筆）。"
  + "改回只換回那一處，別人改的其他地方不動；改回本身也會記成一筆，可以再改回來。";
const SHOWN = 3; // 一筆先列幾處，其他的收在「還有 N 處」

export function headline(group) {
  const n = group.changes.length;
  if (group.kind === "create") return "新增這一頁";
  if (group.kind === "revert") return `改回 ${n} 處`;
  if (group.kind === "restore") return `把這一頁換回以前的版本，改了 ${n} 處`;
  if (group.kind === "rewrite") return `整份改寫，改了 ${n} 處`;
  return n ? `改了 ${n} 處` : null; // 沒有差別：另外寫「改了又改回」
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
      onError("還有沒存好的修改，存好再改回");
      return;
    }
    const body = change.field_id
      ? { field_id: change.field_id, value: change.value, after_activity: change.after_activity }
      : { from_rev: group.from_rev, to_rev: group.to_rev, bid: change.bid, ...(change.rid ? { rid: change.rid } : {}) };
    setBusy(group.id + "|" + change.key);
    try {
      const result = await api.post(`/projects/api/${slug}/tabs/${group.tab_key}/revert`, force ? { ...body, force: true } : body);
      setConfirm(null);
      onToast(result.already ? "這一處已經是改之前的樣子了" : "已改回。這次改回也記在修改紀錄裡，要的話可以再改回來。");
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
          {head || <span className="noop">改了又改回，沒有差別</span>}
          <span className="t">{shortTime(group.at)}</span>
        </div>
        {scope === "all" && group.tab_title && <div className="grp-tab">{group.tab_title}</div>}
        {list.map((change) => {
          const key = group.id + "|" + change.key;
          return (
            <div className="ch" key={change.key} role="button" tabIndex={0} title="到頁面上看這一處"
              onClick={() => onPick(group, change)} onKeyDown={(event) => { if (event.key === "Enter") onPick(group, change); }}>
              <div className="what">
                {change.label}
                {change.button && (
                  <span className="acts">
                    <button type="button" className="ghost xs" disabled={busy === key}
                      onClick={(event) => { event.stopPropagation(); revert(group, change); }}>
                      {busy === key ? "改回中…" : change.button}
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
            還有 {all.length - SHOWN} 處 ▾
          </button>
        )}
      </div>
    );
  };

  const current = data && data.scope === scope && (scope === "all" || data.key === tabKey) ? data : null;
  let body;
  if (!current) body = <div className="empty">讀取中…</div>;
  else if (!current.groups.length) body = <div className="empty">還沒有修改紀錄</div>;
  else {
    body = current.groups.map(item);
    if (current.more) body.push(<div className="empty" key="more">只列出最近 {current.groups.length} 筆</div>);
  }

  let dialog = null;
  if (confirm) {
    const { group, change, info } = confirm;
    const unit = change.field_id ? "這一格" : change.rid ? "這一列" : "這一段";
    const people = (info.later || []).map((p) => p.name).join("、") || "別人";
    const last = (info.later || []).slice(-1)[0];
    dialog = createPortal(
      <Dialog title={`${change.button}？`} confirmLabel="改回"
        message={`${unit}在${group.name}改過之後，${people}又改過${last ? `（${shortTime(last.at)}）` : ""}。改回會連${people}的修改一起換掉。`}
        onConfirm={() => revert(group, change, true)} onCancel={() => setConfirm(null)}>
        <div className="hist-preview">
          <div className="hd">改回後會變成</div>
          {info.preview || "（空白）"}
        </div>
      </Dialog>,
      document.body,
    );
  }

  return (
    <div className="pop on hist" ref={ref} role="dialog" aria-label="修改紀錄">
      <div className="pop-hd">
        <b>修改紀錄</b>
        {scope === "tab" && tabTitle && <span className="pop-sub">{tabTitle}</span>}
      </div>
      <div className="pop-tabs">
        <button type="button" className={scope === "tab" ? "on" : undefined} onClick={() => setScope("tab")}>這一頁</button>
        <button type="button" className={scope === "all" ? "on" : undefined} onClick={() => setScope("all")}>全部分頁</button>
        <span className="info" tabIndex={0} data-tip={HISTORY_RULE} aria-label={HISTORY_RULE}>ⓘ</span>
      </div>
      <div className="pop-list">{body}</div>
      {dialog}
    </div>
  );
}
