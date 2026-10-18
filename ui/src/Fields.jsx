import { useLocale } from './i18n/react.jsx';
import { t as uiText } from './i18n/index.js';
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { STATUSES, shortTime, statusClass, statusLabel, normalizeStatus } from "./format.js";

// 狀態膠囊：點了選，選了就存。選單放在最上層（不會被表格的捲動區切掉），上次是誰改的寫在下面。
export function StatusPill({ value, info, onChange }) {
  const locale = useLocale();
  const [rect, setRect] = useState(null);
  const button = useRef(null);
  const menu = useRef(null);
  useEffect(() => {
    if (!rect) return undefined;
    const close = (event) => {
      if (menu.current && menu.current.contains(event.target)) return;
      if (button.current && button.current.contains(event.target)) return;
      setRect(null);
    };
    const esc = (event) => { if (event.key === "Escape") setRect(null); };
    const away = () => setRect(null);
    document.addEventListener("mousedown", close, true);
    document.addEventListener("keydown", esc);
    window.addEventListener("resize", away);
    window.addEventListener("scroll", away, true);
    return () => {
      document.removeEventListener("mousedown", close, true);
      document.removeEventListener("keydown", esc);
      window.removeEventListener("resize", away);
      window.removeEventListener("scroll", away, true);
    };
  }, [rect]);
  const toggle = () => setRect(rect ? null : button.current.getBoundingClientRect());
  const width = 252;
  return (
    <span className="pill-wrap" data-interactive="">
      <button type="button" ref={button} className={"badge " + statusClass(value)} aria-haspopup="menu"
        aria-expanded={Boolean(rect)} onClick={toggle} onMouseDown={(event) => event.preventDefault()}>
        {statusLabel(value)}
      </button>
      {rect && createPortal(
        <span ref={menu} className="menu pill-menu" role="menu" data-interactive=""
          style={{ position: "fixed", top: Math.min(rect.bottom + 6, window.innerHeight - 290),
            left: Math.max(8, Math.min(rect.left, window.innerWidth - width - 8)), width }}>
          {STATUSES.map((label) => (
            <button type="button" key={label} role="menuitem"
              onClick={() => { setRect(null); if (label !== value) onChange(label); }}>
              <span className={"badge " + statusClass(label)}>{statusLabel(label)}</span>
              {label === normalizeStatus(value) && <span className="tick">✓</span>}
            </button>
          ))}
          <span className="who">
            {info && info.by_name ? uiText("fields.lastChanged", {v0: (info.by_name), v1: (shortTime(info.at))}) : uiText("fields.noChangesYet")}
            <br />{uiText("fields.selectToSaveYourChangeIsRecordedInThis")}</span>
        </span>,
        document.body,
      )}
    </span>
  );
}

// 大家可填的格子：點了打字，離開格子或按 Enter 就存（Shift+Enter 換行）。
export function FillField({ value, info, onSave }) {
  const locale = useLocale();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value || "");
  const [saved, setSaved] = useState(false);
  const area = useRef(null);
  useEffect(() => { if (!editing) setDraft(value || ""); }, [value, editing]);
  useEffect(() => {
    if (editing && area.current) {
      area.current.focus();
      area.current.setSelectionRange(area.current.value.length, area.current.value.length);
    }
  }, [editing]);
  const finish = async () => {
    setEditing(false);
    const next = draft.trim();
    if (next === (value || "")) return;
    const ok = await onSave(next);
    if (ok) {
      setSaved(true);
      setTimeout(() => setSaved(false), 1600);
    }
  };
  if (editing) {
    return (
      <textarea ref={area} className="cell-input" rows={2} value={draft} maxLength={2000} data-interactive=""
        onChange={(event) => setDraft(event.target.value)} onBlur={finish}
        onKeyDown={(event) => {
          event.stopPropagation();
          if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.blur(); }
          if (event.key === "Escape") { setDraft(value || ""); setEditing(false); }
        }} />
    );
  }
  return (
    <span className="fill-field" role="button" tabIndex={0} title={uiText("fields.clickToAddNotesClickOutsideToSave")} data-interactive=""
      onMouseDown={(event) => event.preventDefault()}
      onClick={() => setEditing(true)}
      onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); setEditing(true); } }}>
      {value ? <span className="fill-value">{value}</span> : <span className="ph">{uiText("fields.clickToAddDirectorNotes")}</span>}
      {value && info && info.by_name && <span className="by">{info.by_name}・{shortTime(info.at)}</span>}
      {saved && <span className="saved-tip">{uiText("fields.saved")}</span>}
    </span>
  );
}
