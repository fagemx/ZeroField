import { useLocale } from './i18n/react.jsx';
import { t as uiText } from './i18n/index.js';
import { useEffect, useRef } from 'react';

// A local, non-modal review keeps the sheet and Studio Assistant available.
export function SheetReview({onClose,onStep,children}) {
  useLocale();
  const panel=useRef(null);
  useEffect(()=>{
    const previous=document.activeElement;
    panel.current?.scrollIntoView({block:'start'});
    panel.current?.querySelector('button')?.focus();
    return()=>{if(previous?.isConnected)previous.focus();};
  },[]);
  return <div ref={panel} className="sheet-review" role="dialog" aria-modal="false" aria-label={uiText('studio.shotReview')} onKeyDown={event=>{
    if(event.key==='Escape'){event.stopPropagation();onClose();}
    if(event.target.closest('input,textarea,select,[contenteditable=true]'))return;
    if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();event.stopPropagation();onStep?.(event.key==='ArrowLeft'?-1:1);}
  }}>{children}</div>;
}
