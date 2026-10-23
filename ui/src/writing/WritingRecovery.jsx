import { useState } from 'react';
import { useTranslation } from '../i18n/react.jsx';
import { documentText } from './writingModel.js';
import { i18n } from '../i18n/index.js';
import en from './locales/review1-auth.en.json';
import zhTW from './locales/review1-auth.zh-TW.json';
i18n.addResourceBundle('en','translation',en,true,true);
i18n.addResourceBundle('zh-TW','translation',zhTW,true,true);
const p='writing.authoring.';
export function WritingRecovery({snapshot,persistence,onError}) {
  const {t}=useTranslation(),[busy,setBusy]=useState(false);
  const act=async fn=>{setBusy(true);try{await fn();}catch(error){onError(error);}finally{setBusy(false);}};
  return <div className="writing-recovery" role="alert">
    <h2>{t(p+'recoveryFound')}</h2><p>{t(p+'recoveryExplanation')}</p>
    {snapshot.recoveries.map(entry=><section key={entry.key}>
      {persistence.recoveryDivergence(entry).metadata&&<p>{t('writing.reviewIdentity.metadataChanged')}</p>}
      <p>{entry.updatedAt}</p><div className="writing-compare-columns"><div><h3>{t(p+'serverCopy')}</h3><pre>{documentText(persistence.base.doc)}</pre></div><div><h3>{t(p+'deviceCopy')}</h3><pre>{documentText(entry.doc)}</pre></div></div>
      {persistence.resourceRef.kind!=='working'&&<details><summary>{t('writing.reviewIdentity.metadataCopies')}</summary><div className="writing-compare-columns"><pre>{JSON.stringify({structure:persistence.base.structure,composition:persistence.base.composition},null,2)}</pre><pre>{JSON.stringify({structure:entry.structure,composition:entry.composition},null,2)}</pre></div></details>}
      <button type="button" disabled={busy} onClick={()=>act(()=>persistence.restore(entry))}>{t(p+'restoreDevice')}</button>
      <button type="button" disabled={busy} onClick={()=>act(()=>persistence.discardRecovery(entry))}>{t(p+'discardDevice')}</button>
    </section>)}
  </div>;
}
