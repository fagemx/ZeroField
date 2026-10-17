import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { menuPosition } from "./menuPosition.js";

// 工具列和左邊分頁共用的下拉選單：按鈕下面打開（下面放不下就往上開），點外面關掉。
export function useOutside(ref, onOutside, active) {
  useEffect(() => {
    if (!active) return undefined;
    const handle = (event) => { if (ref.current && !ref.current.contains(event.target)) onOutside(); };
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [ref, onOutside, active]);
}

export function Menu({ items, onClose, rect, hint }) {
  const ref = useRef(null);
  const [height, setHeight] = useState(0);
  // 畫出來之前先量高度，放不下就換位置（useLayoutEffect：不會先閃一下在錯的位置）
  useLayoutEffect(() => { if (ref.current) setHeight(ref.current.offsetHeight); }, [items.length, hint]);
  const style = menuPosition(rect, 280, height, { width: window.innerWidth, height: window.innerHeight });
  return (
    <div className="menu tool-menu" role="menu" ref={ref} style={style}>
      {items.map((item, index) => (item === "sep"
        ? <div key={index} className="sep" />
        : (
          <button type="button" key={item.key || index} role="menuitem" disabled={item.disabled}
            className={item.danger ? "danger" : undefined}
            onMouseDown={(event) => { event.preventDefault(); onClose(); item.run(); }}>
            {item.icon && <span className="mi">{item.icon}</span>}
            {item.label}
            {item.note && <small>{item.note}</small>}
          </button>
        )))}
      {hint && <div className="note hint">{hint}</div>}
    </div>
  );
}
