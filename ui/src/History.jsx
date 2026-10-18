import { useLocale } from './i18n/react.jsx';
import { t as uiText } from './i18n/index.js';
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { api } from "./api.js";
import { Dialog } from "./Dialog.jsx";
import { shortTime } from "./format.js";
import { Avatar } from "./Talk.jsx";

// 修改紀錄（10/15 起大家一起編輯：大家都能改字，所以大家都要看得到誰改了什麼、改錯了能改回）。
// 一筆＝同一個人連續改的一次；每一處都可以單獨改回，改回本身也記成一筆。
export const HISTORY_RULE = () => uiText("history.theCrewCanSeeAndRestoreChangesConsecutiveEdits") + " " + uiText("history.restoringAffectsOnlyTheSelectedContentOtherEditsRemain");
const SHOWN = 3; // 一筆先列幾處，其他的收在「還有 N 處」

export function headline(group) {
  const n = group.changes.length;
  if (group.kind === "create") return uiText("history.createdPage");
  if (group.kind === "revert") return uiText("history.restoreChanges", {v0: (n)});
  if (group.kind === "restore") return uiText("history.restoredThisPageToAnEarlierRevisionChangingChanges", {v0: (n)});
  if (group.kind === "rewrite") return uiText("history.rewroteThePageChangingChanges", {v0: (n)});
  return n ? uiText("history.changedChanges", {v0: (n)}) : null; // 沒有差別：另外寫「改了又改回」
}

function Segments({ segments }) {
  const locale = useLocale();
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
  const locale = useLocale();
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
      onError(uiText("history.savePendingEditsBeforeRestoringARevision"));
      return;
    }
    const body = change.field_id
      ? { field_id: change.field_id, value: change.value, after_activity: change.after_activity }
      : { from_rev: group.from_rev, to_rev: group.to_rev, bid: change.bid, ...(change.rid ? { rid: change.rid } : {}) };
    setBusy(group.id + "|" + change.key);
    try {
      const result = await api.post(`/projects/api/${slug}/tabs/${group.tab_key}/revert`, force ? { ...body, force: true } : body);
      setConfirm(null);
      onToast(result.already ? uiText("history.thisContentAlreadyMatchesItsEarlierVersion") : uiText("history.restoredThisRestorationIsAlsoRecordedInChangeHistory"));
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
          {head || <span className="noop">{uiText("history.noDifferenceAfterRestoring")}</span>}
          <span className="t">{shortTime(group.at)}</span>
        </div>
        {scope === "all" && group.tab_title && <div className="grp-tab">{group.tab_title}</div>}
        {list.map((change) => {
          const key = group.id + "|" + change.key;
          return (
            <div className="ch" key={change.key} role="button" tabIndex={0} title={uiText("history.locateOnPage")}
              onClick={() => onPick(group, change)} onKeyDown={(event) => { if (event.key === "Enter") onPick(group, change); }}>
              <div className="what">
                {change.label}
                {change.button && (
                  <span className="acts">
                    <button type="button" className="ghost xs" disabled={busy === key}
                      onClick={(event) => { event.stopPropagation(); revert(group, change); }}>
                      {busy === key ? uiText("history.restoring") : change.button}
                    </button>
                  </span>
                )}
              </div>
              {change.segments.length > 0 && <Segments segments={change.segments} />}
            </div>
          );
        })}
        {all.length > SHOWN && !isOpen && (
          <button type="button" className="more-ch" onClick={() => setExpanded(new Set(expanded).add(group.id))}>{uiText("history.alsoChanges", {v0: (all.length - SHOWN)})}</button>
        )}
      </div>
    );
  };

  const current = data && data.scope === scope && (scope === "all" || data.key === tabKey) ? data : null;
  let body;
  if (!current) body = <div className="empty">{uiText("history.loading")}</div>;
  else if (!current.groups.length) body = <div className="empty">{uiText("history.noChangesRecordedYet")}</div>;
  else {
    body = current.groups.map(item);
    if (current.more) body.push(<div className="empty" key="more">{uiText("history.showingTheLatestItems", {v0: (current.groups.length)})}</div>);
  }

  let dialog = null;
  if (confirm) {
    const { group, change, info } = confirm;
    const unit = change.field_id ? uiText("history.thisCell") : change.rid ? uiText("history.thisRow") : uiText("history.thisPassage");
    const people = (info.later || []).map((p) => p.name).join("、") || uiText("history.anotherCrewMember");
    const last = (info.later || []).slice(-1)[0];
    dialog = createPortal(
      <Dialog title={uiText("history.message", {v0: (change.button)})} confirmLabel={uiText("history.restore")}
        message={uiText("history.restoreConflict", {v0: (unit), v1: (group.name), v2: (people), v3: (last ? `(${shortTime(last.at)})` : ""), v4: (people)})}
        onConfirm={() => revert(group, change, true)} onCancel={() => setConfirm(null)}>
        <div className="hist-preview">
          <div className="hd">{uiText("history.afterRestoring")}</div>
          {info.preview || uiText("history.empty")}
        </div>
      </Dialog>,
      document.body,
    );
  }

  return (
    <div className="pop on hist" ref={ref} role="dialog" aria-label={uiText("history.changeHistory")}>
      <div className="pop-hd">
        <b>{uiText("history.changeHistory")}</b>
        {scope === "tab" && tabTitle && <span className="pop-sub">{tabTitle}</span>}
      </div>
      <div className="pop-tabs">
        <button type="button" className={scope === "tab" ? "on" : undefined} onClick={() => setScope("tab")}>{uiText("history.thisPage")}</button>
        <button type="button" className={scope === "all" ? "on" : undefined} onClick={() => setScope("all")}>{uiText("history.allPages")}</button>
        <span className="info" tabIndex={0} data-tip={HISTORY_RULE()} aria-label={HISTORY_RULE()}>ⓘ</span>
      </div>
      <div className="pop-list">{body}</div>
      {dialog}
    </div>
  );
}
