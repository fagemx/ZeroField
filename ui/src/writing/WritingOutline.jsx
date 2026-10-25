import { useEffect, useRef, useState } from 'react';
import { useTranslation } from '../i18n/react.jsx';
import { documentText, sceneBlocks, stable } from './writingModel.js';
import { plotEntries } from './writingOutlineRecovery.js';
const key='writing.authoring.';
const sceneFields=['summary','storyTime','act','foreshadowing','payoff'];
// Private draft values that the chosen merge would drop: the author kept the shared value instead.
// A value the author never changed from their own base (edited and restored) is not a discard.
const droppedFields=(review,choices)=>review.fields.filter(field=>choices[field.path]==='server'&&field.local!==undefined&&stable(field.local)!==stable(field.server)&&stable(field.local)!==stable(field.base));
export function WritingOutlineMerge({review,onApply}) {
  const {t}=useTranslation();
  const [choices,setChoices]=useState(()=>Object.fromEntries(review.fields.map(field=>[field.path,field.unchanged?'local':'server'])));
  const [confirming,setConfirming]=useState(false);
  const warning=useRef(null),save=useRef(null),returning=useRef(false);
  // Focus the warning when it opens and give focus back to Save when the author goes back (the Back button unmounts).
  useEffect(()=>{if(confirming)warning.current?.focus();else if(returning.current){returning.current=false;save.current?.focus();}},[confirming]);
  const names=review.names||{scenes:{},lanes:{}};
  const laneName=id=>names.lanes[id]||t(key+'outlineMergeLaneUnnamed');
  const sceneName=id=>{
    const scene=names.scenes[id];if(!scene)return t(key+'outlineMergeSceneUnknown');
    const name=scene.title||t(key+'sceneNumber',{number:scene.number});
    // Two scenes may share a title; the number keeps them apart without showing internal IDs.
    return scene.title&&Object.entries(names.scenes).some(([other,item])=>other!==id&&item.title===scene.title)?t(key+'outlineMergeSceneDuplicate',{name,number:scene.number}):name;
  };
  const subject=field=>field.kind==='scenePatches'?sceneName(field.id):t(key+'outlineMergeLane',{name:laneName(field.id)});
  const fieldName=field=>field.kind==='scenePatches'
    ?(sceneFields.includes(field.field)?t(key+field.field):field.field==='plot'?t(key+'outlineMergePlot'):field.field)
    :(field.field==='name'?t(key+'outlineMergeLaneName'):field.field==='order'?t(key+'outlineMergeLaneOrder'):field.field);
  const label=field=>t(key+'outlineMergeFieldLabel',{subject:subject(field),field:fieldName(field)});
  const show=(field,value)=>{
    if(value===undefined||value==='')return t(key+'outlineUnset');
    if(field.field==='plot'&&value&&typeof value==='object')return plotEntries(value,laneName).map(entry=>t(key+'outlineMergePlotCell',entry)).join('\n')||t(key+'outlineUnset');
    return typeof value==='string'?value:JSON.stringify(value,null,2);
  };
  // The exported file carries the same names the author saw, never lane or scene IDs, and keeps same-named lanes apart.
  const plain=(field,value)=>field.field==='plot'&&value&&typeof value==='object'?plotEntries(value,laneName):value;
  const dropped=droppedFields(review,choices);
  const choose=(path,value)=>{setConfirming(false);setChoices(current=>({...current,[path]:value}));};
  const download=()=>{
    const blob=new Blob([JSON.stringify({kind:'outline-discarded-values',sharedVersionAtReview:review.structure.version,fields:dropped.map(field=>({subject:subject(field),field:fieldName(field),privateDraftValue:plain(field,field.local)}))},null,2)],{type:'application/json'});
    const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='outline-discarded-values.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),0);
  };
  return <form aria-label={t(key+'outlineMerge')} onSubmit={event=>{event.preventDefault();if(dropped.length)setConfirming(true);else onApply(choices);}}>
    <p>{t(key+'outlineMergeInstructions',{version:review.structure.version})}</p>
    {review.fields.map(field=><fieldset key={field.path}><legend>{label(field)}</legend>
      <div><strong>{t(key+'outlineMergeBase')}</strong><pre>{show(field,field.base)}</pre></div>
      <div><strong>{t(key+'outlineMergeServer')}</strong><pre>{show(field,field.server)}</pre></div>
      <div><strong>{t(key+'outlineMergeLocal')}</strong><pre>{show(field,field.local)}</pre></div>
      {!field.mergeable&&<p role="alert">{t(key+'outlineIdentityChanged')}</p>}
      <label>{t(key+'outlineMergeChoice')}<select aria-label={t(key+'outlineMergeChoice')+' '+label(field)} value={choices[field.path]} onChange={event=>choose(field.path,event.target.value)}>
        <option value="server">{t(key+'outlineUseServer')}</option><option value="local" disabled={!field.mergeable}>{t(key+'outlineUseLocal')}</option>
      </select></label>
    </fieldset>)}
    <button type="submit" ref={save} disabled={confirming}>{t(key+'saveReviewedOutline')}</button>
    {confirming&&<div role="alert" tabIndex={-1} ref={warning} className="writing-outline-discard">
      <h3>{t(key+'outlineDropTitle',{count:dropped.length})}</h3>
      <p>{t(key+'outlineDropExplain')}</p>
      <ul>{dropped.map(field=><li key={field.path}><strong>{label(field)}</strong><pre>{show(field,field.local)}</pre></li>)}</ul>
      <button type="button" onClick={download}>{t(key+'outlineDropDownload')}</button>
      <button type="button" onClick={()=>{returning.current=true;setConfirming(false);}}>{t(key+'outlineDropBack')}</button>
      <button type="button" onClick={()=>onApply(choices)}>{t(key+'outlineDropConfirm')}</button>
    </div>}
  </form>;
}
export function WritingOutline({structure,metadataDraft,doc,writable,selected,onSelect,onMetadata,onStructure,onShots,onUndo,onComposition}) {
  const {t}=useTranslation();const [outline,setOutline]=useState(false),[laneName,setLaneName]=useState(''),[splitPoints,setSplitPoints]=useState({});
  const scenes=(structure?.scenes || []).map(scene=>({...scene,...metadataDraft?.scenePatches?.find(patch=>patch.sceneKey===scene.sceneKey)}));
  const laneMap=new Map((structure?.lanes || []).map(lane=>[lane.laneId,lane]));
  for(const patch of metadataDraft?.lanePatches || [])laneMap.set(patch.laneId,{...laneMap.get(patch.laneId),...patch});
  const lanes=[...laneMap.values()];
  return <section className="writing-outline" aria-label={t(key+'outline')} onCompositionStart={()=>onComposition?.(true)} onCompositionEnd={()=>onComposition?.(false)}>
    <header><h2>{t(key+'outline')}</h2><button type="button" aria-pressed={outline} onClick={()=>setOutline(!outline)}>{t(key+'plotView')}</button></header>
    {onUndo&&<button type="button" disabled={!writable} onClick={onUndo}>{t(key+'undoStructure')}</button>}
    <button type="button" aria-pressed={!selected} onClick={()=>onSelect(null)}>{t(key+'fullDocument')}</button>
    <ol>{scenes.map((scene,index)=><li key={scene.sceneKey}>
      <button type="button" aria-pressed={selected===scene.sceneKey} onClick={()=>onSelect(scene.sceneKey)}>{scene.title || scene.heading || t(key+'sceneNumber',{number:index+1})}</button>
      {outline&&<div className="writing-scene-metadata">
        <label>{t(key+'summary')}<textarea value={scene.summary || ''} disabled={!writable} onChange={e=>onMetadata({sceneKey:scene.sceneKey,summary:e.target.value})}/></label>
        {!scene.summary&&<p><small>{t(key+'excerpt')}</small> {documentText(sceneBlocks(doc,scene)).slice(0,200)}</p>}
        {['storyTime','act','foreshadowing','payoff'].map(field=><label key={field}>{t(key+field)}<input value={scene[field] || ''} disabled={!writable} onChange={e=>onMetadata({sceneKey:scene.sceneKey,[field]:e.target.value})}/></label>)}
        {lanes.map(lane=><label key={lane.laneId}>{lane.name}<input value={scene.plot?.[lane.laneId] || ''} disabled={!writable} onChange={e=>onMetadata({sceneKey:scene.sceneKey,plot:{...(scene.plot || {}),[lane.laneId]:e.target.value}})}/></label>)}
        <p>{(scene.assetCodes || []).join(' · ')}</p>
        {(scene.shotIds || []).length>0&&<button type="button" onClick={()=>onShots?.({shotIds:scene.shotIds})}>{t(key+'linkedShots',{count:scene.shotIds.length})}</button>}
      </div>}
      {writable&&<div className="writing-structure-actions">
        <button type="button" disabled={index===0} aria-label={t(key+'moveSceneUp',{name:scene.title || index+1})} onClick={()=>onStructure({type:'move',sceneKey:scene.sceneKey,afterSceneKey:scenes[index-2]?.sceneKey || null})}>↑</button>
        <button type="button" disabled={index===scenes.length-1} aria-label={t(key+'moveSceneDown',{name:scene.title || index+1})} onClick={()=>onStructure({type:'move',sceneKey:scene.sceneKey,afterSceneKey:scenes[index+1].sceneKey})}>↓</button>
        {scene.beats?.length>1&&<label>{t(key+'splitAt')}<select aria-label={t(key+'splitSceneAt',{name:scene.title || index+1})} value={splitPoints[scene.sceneKey] || scene.beats[1].blockBids?.[0]} onChange={event=>setSplitPoints(points=>({...points,[scene.sceneKey]:event.target.value}))}>{scene.beats.slice(1).flatMap(beat=>(beat.blockBids || []).map(bid=><option key={bid} value={bid}>{documentText((doc.content || []).find(node=>node.attrs?.bid===bid)).slice(0,60) || bid}</option>))}</select></label>}
        <button type="button" disabled={!scene.beats?.length || scene.beats.length<2} onClick={()=>onStructure({type:'split',sceneKey:scene.sceneKey,atBid:splitPoints[scene.sceneKey] || scene.beats?.[1]?.blockBids?.[0]})}>{t(key+'split')}</button>
        <button type="button" disabled={index===scenes.length-1} onClick={()=>onStructure({type:'merge',sceneKeys:[scene.sceneKey,scenes[index+1].sceneKey],keepSceneKey:scene.sceneKey})}>{t(key+'mergeNext')}</button>
        <button type="button" onClick={()=>onStructure({type:'remove',sceneKey:scene.sceneKey})}>{t(key+'removeScene')}</button>
      </div>}
    </li>)}</ol>
    {writable&&<button type="button" onClick={()=>onStructure({type:'add',afterSceneKey:scenes.at(-1)?.sceneKey || null,title:'Scene '+String(scenes.length+1).padStart(2,'0')+': '+t(key+'newScene')})}>{t(key+'addScene')}</button>}
    {outline&&writable&&<form onSubmit={event=>{event.preventDefault();if(laneName.trim()){onMetadata(null,{laneId:'lane_'+crypto.randomUUID().replaceAll('-',''),name:laneName.trim(),order:lanes.length+1});setLaneName('');}}}>
      <label>{t(key+'plotLane')}<input value={laneName} onChange={event=>setLaneName(event.target.value)} maxLength={100}/></label><button disabled={!laneName.trim() || lanes.length>=8}>{t(key+'addLane')}</button>
      {lanes.map(lane=><div key={lane.laneId}><label>{t(key+'plotLane')}<input value={lane.name} maxLength={200} onChange={event=>onMetadata(null,{laneId:lane.laneId,name:event.target.value})}/></label><button type="button" onClick={()=>onStructure({type:'remove_lane',laneId:lane.laneId})}>{t(key+'removeLane',{name:lane.name})}</button></div>)}
    </form>}
  </section>;
}
