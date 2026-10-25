import { useTranslation } from '../i18n/react.jsx';
import { semanticEnumKey } from './writingModel.js';
const p='writing.authoring.';
const text=value=>typeof value==='string'?value:JSON.stringify(value,null,2);
export function WritingImpactChanges({proposal,onShots,onSource,onRevise}) {
  const {t}=useTranslation();
  return <div className="writing-impact-changes">
    {!proposal.canApply&&<p role="alert">{t(p+'impactCompareOnly')}</p>}
    {proposal.confirmBaseline&&<p role="note">{t(p+'impactConfirmsOnApply')}</p>}
    {proposal.targetVersionId&&<p>{t(p+'impactTargetVersion',{id:proposal.targetVersionId})}</p>}
    {proposal.shots.map(change=>{
      const alignment=change.storyAlignment || {},source=change.sourceRef;
      return <article className="writing-change" key={change.shotId}>
        <h3>{change.shotIndex || change.shotId}</h3><p>{change.shotId}</p>
        <p>{t(p+semanticEnumKey('alignment',alignment.state || 'unbound'))}</p>
        {(alignment.reasons || []).map(reason=><p key={reason}>{t(p+'reason',{reason:t(p+semanticEnumKey('alignment',reason),{defaultValue:reason})})}</p>)}
        {!!alignment.manualFields?.length&&<p role="note">{t(p+'manualOverride')} {alignment.manualFields.map(field=>t(p+field,{defaultValue:field})).join(' · ')}</p>}
        <p>{change.storyOrigin?.versionId?t(p+'actualOrigin',{id:change.storyOrigin.versionId}):t(p+'unknownOrigin')}</p>
        {alignment.mediaOutdated&&<p role="note">{t(p+'mediaOutdated')}</p>}
        <div className="writing-compare-columns">{['oldSource','newSource'].map(field=><div key={field}><h4>{t(p+field)}</h4>{(change[field] || []).map((item,index)=><pre key={index}>{[item.sceneKey,item.beatKey,item.text].filter(Boolean).join('\n')}</pre>)}</div>)}</div>
        <div className="writing-compare-columns">{['current','suggested'].map(field=><div key={field}><h4>{t(p+(field==='current'?'currentText':'suggestedText'))}</h4>{['description','dialogue'].map(name=><div key={name}><strong>{t(p+name)}</strong><pre>{text(change[field]?.[name] ?? '')}</pre></div>)}</div>)}</div>
        {(change.media?.selectedVideoUrl || change.media?.selectedImageUrl)&&<p>{t(p+'mediaPreserved')}</p>}
        {change.media?.selectedImageUrl&&<img src={change.media.selectedImageUrl} alt={t(p+'existingImage')}/>}
        {change.media?.selectedVideoUrl&&<video controls preload="metadata" src={change.media.selectedVideoUrl} aria-label={t(p+'existingTake')}/>}
        <button type="button" onClick={()=>onShots?.({shotIds:[change.shotId]})}>{t(p+'openShot')}</button>
        {source?.sceneKey&&<button type="button" onClick={()=>onSource?.(source)}>{t(p+'backToSource')}</button>}
      </article>;
    })}
    {!!proposal.additions.length&&<section><h3>{t(p+'impactAdditions')}</h3><p>{t(p+'textShotsOnly')}</p>{proposal.additions.map((addition,index)=><pre key={index}>{text(addition)}</pre>)}</section>}
    {!!proposal.assetChanges.length&&<section><h3>{t(p+'impactAssets')}</h3><p>{t(p+'assetConfirmationHelp')}</p>{proposal.assetChanges.map((asset,index)=><pre key={index}>{text(asset)}</pre>)}</section>}
    {onRevise&&<button type="button" onClick={onRevise}>{t(p+'reviseImpactBindings')}</button>}
  </div>;
}
