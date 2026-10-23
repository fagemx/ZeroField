import { useState } from 'react';
import { useTranslation } from '../i18n/react.jsx';
import { allowedSelection, documentText, semanticEnumKey } from './writingModel.js';
const prefix='writing.authoring.';
export function WritingPreview({preview,shots=[],writable,onApply,onClose,onShots,onSource}) {
  const {t}=useTranslation();const [selected,setSelected]=useState([]),[busy,setBusy]=useState(false),[error,setError]=useState(null);
  const expires=typeof preview.expiresAt==='number'?preview.expiresAt*1000:Date.parse(preview.expiresAt);
  const expired=expires<=Date.now(),blocked=expired || preview.stale || preview.status!=='pending';
  const changes=Array.isArray(preview.proposedChanges)?preview.proposedChanges:preview.proposedChanges?.shots || preview.proposedChanges?.changes || [];
  const actions=preview.allowedActions || [];
  const toggle=(action,checked)=>setSelected(items=>checked?[...items,{actionId:action.actionId,kind:action.kind,...(action.kind==='update_text'?{fields:action.fields || []}:{})}]:items.filter(item=>item.actionId!==action.actionId));
  const apply=async()=>{setBusy(true);setError(null);try{await onApply(allowedSelection(preview,selected));}catch(error){setError(error);}finally{setBusy(false);}};
  return <section className="writing-preview" role="region" aria-label={t(prefix+'reviewPreview')}>
    <header><h2>{t(prefix+(preview.kind==='impact'?'impactReview':'reviewPreview'))}</h2><button type="button" onClick={onClose}>{t(prefix+'close')}</button></header>
    <p>{t(prefix+'previewSafety')}</p>
    {(preview.warnings || []).map((warning,i)=><p key={i} role="note">{typeof warning==='string'?warning:warning.message || warning.code}</p>)}
    {preview.candidateBranchId&&<p>{t(prefix+'candidatePreserved',{id:preview.candidateBranchId})}</p>}
    {blocked&&<p role="alert">{t(prefix+'stalePreview')}</p>}
    {preview.proposedChanges?.doc&&<div><h3>{t(prefix+'proposedManuscript')}</h3><pre>{documentText(preview.proposedChanges.sourceDoc || preview.proposedChanges.doc)}</pre></div>}
    {preview.proposedChanges?.operation&&<p>{t(prefix+'structureOperation',{operation:t(prefix+semanticEnumKey('action',preview.proposedChanges.operation.type))})}</p>}
    {changes.map((change,index)=><article className="writing-change" key={change.actionId || change.shotId || index}>
      <h3>{change.label || change.shotId || change.sceneKey || t(prefix+'changeNumber',{number:index+1})}</h3>
      {change.state&&<p>{t(prefix+semanticEnumKey('alignment',change.state),{defaultValue:change.state})}</p>}
      {(change.reasons || []).map(reason=><p key={reason}>{t(prefix+'reason',{reason})}</p>)}
      {change.manualOverride&&<p role="note">{t(prefix+'manualOverride')}</p>}
      <div className="writing-compare-columns">
        {['oldSource','newSource','currentText','suggestedText'].filter(field=>change[field]!==undefined).map(field=><div key={field}><h4>{t(prefix+field)}</h4><pre>{typeof change[field]==='object'?(change[field].type?documentText(change[field]):JSON.stringify(change[field],null,2)):change[field]}</pre></div>)}
      </div>
      {(change.media || shots.find(shot=>shot.shotId===change.shotId)?.selectedVideoUrl)&&<p>{t(prefix+'mediaPreserved')}</p>}
      {shots.find(shot=>shot.shotId===change.shotId)?.selectedVideoUrl&&<video controls preload="metadata" src={shots.find(shot=>shot.shotId===change.shotId).selectedVideoUrl} aria-label={t(prefix+'existingTake')}/>}
      {change.shotId&&<button type="button" onClick={()=>onShots?.({shotIds:[change.shotId]})}>{t(prefix+'openShot')}</button>}
      {change.sceneKey&&<button type="button" onClick={()=>onSource?.({sceneKey:change.sceneKey,beatKey:change.beatKey})}>{t(prefix+'backToSource')}</button>}
    </article>)}
    <fieldset disabled={!writable || busy || blocked}><legend>{t(prefix+'selectActions')}</legend>
      {actions.map(action=><div key={action.actionId} className="writing-preview-action">
        <label><input type="checkbox" checked={selected.some(item=>item.actionId===action.actionId)} onChange={event=>toggle(action,event.target.checked)}/>{t(prefix+semanticEnumKey('action',action.kind),{defaultValue:action.kind})} {[action.shotId,action.sceneKey,action.beatKey,action.label].filter(Boolean).join(' · ')}</label>
        {action.kind==='update_text'&&selected.some(item=>item.actionId===action.actionId)&&<div>{(action.fields || []).map(field=><label key={field}><input type="checkbox" checked={selected.find(item=>item.actionId===action.actionId)?.fields?.includes(field) || false} onChange={event=>setSelected(items=>items.map(item=>item.actionId!==action.actionId?item:{...item,fields:event.target.checked?[...item.fields,field]:item.fields.filter(value=>value!==field)}))}/>{t(prefix+field)}</label>)}</div>}
      </div>)}
      <button type="button" className="writing-primary" disabled={!selected.length || selected.some(item=>item.kind==='update_text'&&!item.fields?.length)} onClick={apply}>{t(prefix+'applySelected')}</button>
    </fieldset>
    {error&&<p role="alert">{error.message}</p>}
  </section>;
}
