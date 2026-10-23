import { useState } from 'react';
import { useTranslation } from '../i18n/react.jsx';
import { documentText, sceneBlocks } from './writingModel.js';
const key='writing.authoring.';
export function WritingOutline({structure,doc,writable,selected,onSelect,onMetadata,onStructure,onShots,onUndo}) {
  const {t}=useTranslation();const [outline,setOutline]=useState(false),[laneName,setLaneName]=useState(''),[splitPoints,setSplitPoints]=useState({});
  const scenes=structure?.scenes || [],lanes=structure?.lanes || [];
  return <section className="writing-outline" aria-label={t(key+'outline')}>
    <header><h2>{t(key+'outline')}</h2><button type="button" aria-pressed={outline} onClick={()=>setOutline(!outline)}>{t(key+'plotView')}</button></header>
    {onUndo&&<button type="button" disabled={!writable} onClick={onUndo}>{t(key+'undoStructure')}</button>}
    <button type="button" aria-pressed={!selected} onClick={()=>onSelect(null)}>{t(key+'fullDocument')}</button>
    <ol>{scenes.map((scene,index)=><li key={scene.sceneKey}>
      <button type="button" aria-pressed={selected===scene.sceneKey} onClick={()=>onSelect(scene.sceneKey)}>{scene.title || scene.heading || t(key+'sceneNumber',{number:index+1})}</button>
      {outline&&<div className="writing-scene-metadata">
        <label>{t(key+'summary')}<textarea defaultValue={scene.summary || ''} key={`${scene.sceneKey}:summary:${structure.version}`} disabled={!writable} onBlur={e=>{if(e.target.value!==(scene.summary || ''))onMetadata({sceneKey:scene.sceneKey,summary:e.target.value});}}/></label>
        {!scene.summary&&<p><small>{t(key+'excerpt')}</small> {documentText(sceneBlocks(doc,scene)).slice(0,200)}</p>}
        {['storyTime','act','foreshadowing','payoff'].map(field=><label key={field}>{t(key+field)}<input defaultValue={scene[field] || ''} disabled={!writable} key={`${scene.sceneKey}:${field}:${structure.version}`} onBlur={e=>{if(e.target.value!==(scene[field] || ''))onMetadata({sceneKey:scene.sceneKey,[field]:e.target.value});}}/></label>)}
        {lanes.map(lane=><label key={lane.laneId}>{lane.name}<input defaultValue={scene.plot?.[lane.laneId] || ''} disabled={!writable} onBlur={e=>onMetadata({sceneKey:scene.sceneKey,plot:{...(scene.plot || {}),[lane.laneId]:e.target.value}})}/></label>)}
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
      {lanes.map(lane=><div key={lane.laneId}><label>{t(key+'plotLane')}<input key={structure.version} defaultValue={lane.name} maxLength={200} onBlur={event=>{if(event.target.value!==lane.name)onMetadata(null,{laneId:lane.laneId,name:event.target.value});}}/></label><button type="button" onClick={()=>onStructure({type:'remove_lane',laneId:lane.laneId})}>{t(key+'removeLane',{name:lane.name})}</button></div>)}
    </form>}
  </section>;
}
