import { useState } from 'react';
import { useTranslation } from '../i18n/react.jsx';
import { documentText } from './writingModel.js';
const p='writing.authoring.';
export function WritingRecovery({snapshot,persistence,onError}) {
  const {t}=useTranslation(),[busy,setBusy]=useState(false);
  const act=async fn=>{setBusy(true);try{await fn();}catch(error){onError(error);}finally{setBusy(false);}};
  return <div className="writing-recovery" role="alert">
    <h2>{t(p+'recoveryFound')}</h2><p>{t(p+'recoveryExplanation')}</p>
    {snapshot.recoveries.map(entry=><section key={entry.key}>
      <p>{entry.updatedAt}</p><div className="writing-compare-columns"><div><h3>{t(p+'serverCopy')}</h3><pre>{documentText(persistence.base.doc)}</pre></div><div><h3>{t(p+'deviceCopy')}</h3><pre>{documentText(entry.doc)}</pre></div></div>
      <button type="button" disabled={busy} onClick={()=>act(()=>persistence.restore(entry))}>{t(p+'restoreDevice')}</button>
      <button type="button" disabled={busy} onClick={()=>act(()=>persistence.discardRecovery(entry))}>{t(p+'discardDevice')}</button>
    </section>)}
  </div>;
}
