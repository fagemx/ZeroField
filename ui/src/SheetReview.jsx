import { useEffect, useRef } from 'react';

// Wide review keeps the data grid mounted underneath, preserving its scroll.
export function SheetReview({onClose,children}) {
  const panel=useRef(null);
  useEffect(()=>{
    const previous=document.activeElement;
    panel.current?.querySelector('button')?.focus();
    return()=>{if(previous?.isConnected)previous.focus();};
  },[]);
  return <div ref={panel} className="sheet-review" role="dialog" aria-modal="true" aria-label="圖片與素材審核" onKeyDown={e=>{
    if(e.key==='Escape'){e.stopPropagation();onClose();}
    if(e.key!=='Tab')return;
    const controls=[...panel.current.querySelectorAll('button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),a[href]')].filter(el=>el.getClientRects().length);
    const first=controls[0],last=controls.at(-1);
    if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}
    if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}
  }}>{children}</div>;
}
