import { useEffect, useRef, useState } from "react";

// 簡單的對話框：一行輸入（可選）、一個下拉（可選）、確定／取消。
export function Dialog({ title, message, input, inputLabel, select, confirmLabel = "確定", cancelLabel = "取消", danger, onConfirm, onCancel, children, hideConfirm = false, className = '', returnFocusRef }) {
  const [text, setText] = useState(input && input.value ? input.value : "");
  const [choice, setChoice] = useState(select && select.value ? select.value : "");
  const field = useRef(null);
  const modal = useRef(null);
  const cancelRef = useRef(onCancel);
  cancelRef.current = onCancel;
  useEffect(() => {
    const previous = document.activeElement;
    if (field.current) { field.current.focus(); field.current.select(); }
    else modal.current?.querySelector('button,input,select,textarea')?.focus();
    const esc = (event) => {
      if (event.key === "Escape") cancelRef.current();
      if (event.key === 'Tab') {
        const controls = [...(modal.current?.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled)') || [])];
        if (event.shiftKey && document.activeElement === controls[0]) { event.preventDefault(); controls.at(-1)?.focus(); }
        else if (!event.shiftKey && document.activeElement === controls.at(-1)) { event.preventDefault(); controls[0]?.focus(); }
      }
    };
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("keydown", esc); (previous?.isConnected ? previous : returnFocusRef?.current)?.focus(); };
  }, []);
  const submit = (event) => {
    event.preventDefault();
    if (input && input.required && !text.trim()) return;
    onConfirm({ text: text.trim(), choice });
  };
  return (
    <div className="modal-scrim" onMouseDown={(event) => { if (event.target === event.currentTarget) onCancel(); }}>
      <form ref={modal} className={`modal ${className}`} onSubmit={submit} role="dialog" aria-modal="true" aria-label={title}>
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
          <button type="button" className="ghost" onClick={onCancel}>{cancelLabel}</button>
          {!hideConfirm && <button type="submit" className={danger ? "primary danger" : "primary"}>{confirmLabel}</button>}
        </div>
      </form>
    </div>
  );
}
