import { useLocale } from './i18n/react.jsx';
import { t as uiText } from './i18n/index.js';
import { useEffect, useRef } from "react";

export function SheetDialog({ title, onClose, children, wide = false }) {
  const locale = useLocale();
  const box = useRef(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement;
    (box.current.querySelector("[data-autofocus]") || box.current).focus();
    return () => { if (previous?.isConnected) previous.focus(); };
  }, []);
  return <div className="modal-scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) close.current(); }}>
    <section ref={box} tabIndex={-1} className={`modal sheet-dialog${wide ? " wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}
      onKeyDown={(e) => {
        if (e.key === "Escape") { e.stopPropagation(); close.current(); }
        if (e.key === "Tab") {
          const items = [...box.current.querySelectorAll('button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), a[href]')].filter((el) => el.getClientRects().length);
          if (!items.length) { e.preventDefault(); return; }
          const first = items[0], last = items.at(-1);
          if (e.shiftKey && (document.activeElement === first || document.activeElement === box.current)) { e.preventDefault(); last.focus(); }
          else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        }
      }}>
      <header className="sheet-dialog-header"><h2>{title}</h2><button type="button" aria-label={uiText("sheetDialog.closePanel")} onClick={onClose}>✕</button></header>
      {children}
    </section>
  </div>;
}
