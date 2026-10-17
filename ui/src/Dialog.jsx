import { useEffect, useRef, useState } from "react";

// 簡單的對話框：一行輸入（可選）、一個下拉（可選）、確定／取消。
export function Dialog({ title, message, input, inputLabel, select, confirmLabel = "確定", danger, onConfirm, onCancel, children }) {
  const [text, setText] = useState(input && input.value ? input.value : "");
  const [choice, setChoice] = useState(select && select.value ? select.value : "");
  const field = useRef(null);
  useEffect(() => {
    if (field.current) { field.current.focus(); field.current.select(); }
    const esc = (event) => { if (event.key === "Escape") onCancel(); };
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [onCancel]);
  const submit = (event) => {
    event.preventDefault();
    if (input && input.required && !text.trim()) return;
    onConfirm({ text: text.trim(), choice });
  };
  return (
    <div className="modal-scrim" onMouseDown={(event) => { if (event.target === event.currentTarget) onCancel(); }}>
      <form className="modal" onSubmit={submit} role="dialog" aria-label={title}>
        <h3>{title}</h3>
        {message && <p className="modal-msg">{message}</p>}
        {input && (
          <label className="modal-field">
            <span>{inputLabel}</span>
            <input ref={field} value={text} maxLength={input.maxLength || 200} placeholder={input.placeholder || ""}
              onChange={(event) => setText(event.target.value)} />
          </label>
        )}
        {select && (
          <label className="modal-field">
            <span>{select.label}</span>
            <select value={choice} onChange={(event) => setChoice(event.target.value)}>
              {select.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
        )}
        {children}
        <div className="modal-actions">
          <button type="button" className="ghost" onClick={onCancel}>取消</button>
          <button type="submit" className={danger ? "primary danger" : "primary"}>{confirmLabel}</button>
        </div>
      </form>
    </div>
  );
}
