import { useState } from 'react';
import { useTranslation } from '../i18n/react.jsx';
import { documentText,clone } from './writingModel.js';
import { mutationId } from './writingTransport.js';
const p='writing.authoring.';
export function WritingSourceTools({doc,structure={},composition={},writable,onMetadata,onDocument,request,epId,onError,targetScenes=3,onTargetScenes}) {
  const {t}=useTranslation();const [collisions,setCollisions]=useState(null),[busy,setBusy]=useState(false),[title,setTitle]=useState(''),[bids,setBids]=useState([]);
  const chapters=structure.chapters || [],trace=composition.choiceTrace || {focus:'overall',keptLabels:[],uncheckedLabels:[],extraCondition:''};
  const updateComposition=patch=>onMetadata({composition:{...composition,...patch}});
  const updateTrace=patch=>updateComposition({choiceTrace:{...trace,...patch}});
  const collide=async()=>{setBusy(true);try{const result=await request(`/episodes/${encodeURIComponent(epId)}/story-collisions`,'POST',{sourceText:documentText(doc),mediumLens:composition.mediumLens,genreLens:composition.genreLens || 'general'},{idempotencyKey:mutationId()});setCollisions(result);updateTrace({keptLabels:result.candidates.map(card=>card.label),uncheckedLabels:[]});}catch(error){onError(error);}finally{setBusy(false);}};
  const updateChapters=next=>onMetadata({structure:{...structure,chapters:next}});
  const unassign=items=>items.map(item=>({...item,blockBids:(item.blockBids || []).filter(id=>!bids.includes(id)),...(item.sections?{sections:unassign(item.sections)}:{})}));
  const orderedBids=(doc.content || []).map(node=>node.attrs?.bid).filter(id=>bids.includes(id));
  const add=()=>{if(!title.trim() || !bids.length)return;updateChapters([...unassign(chapters),{chapterKey:'wch_'+mutationId().replaceAll('-',''),title:title.trim(),blockBids:orderedBids,sections:[]}]);setTitle('');setBids([]);};
  const move=(index,delta)=>{
    const next=clone(chapters);[next[index],next[index+delta]]=[next[index+delta],next[index]];
    const byId=new Map((doc.content || []).map(node=>[node.attrs?.bid,node]));const ordered=[...new Set(next.flatMap(chapter=>[...(chapter.blockBids || []),...(chapter.sections || []).flatMap(section=>section.blockBids || [])]))];
    const selected=new Set(ordered);onDocument({...doc,content:[...ordered.filter(id=>byId.has(id)).map(id=>byId.get(id)),...(doc.content || []).filter(node=>!selected.has(node.attrs?.bid))]});updateChapters(next);
  };
  return <section className="writing-source-tools">
    {onTargetScenes&&<label className="writing-target-scenes">{t('story.targetScenes')}<input type="number" min={1} max={12} step={1} value={targetScenes} disabled={!writable} aria-label={t('story.targetScenes')}
      onChange={event=>onTargetScenes(Math.max(1,Math.min(12,Math.trunc(Number(event.target.value))||1)))}/></label>}
    <details><summary>{t(p+'sourceDevelopment')}</summary><p>{t(p+'sourceDevelopmentHelp')}</p>
      <label>{t('story.mediumLens')}<select aria-label={t('story.mediumLens')} value={composition.mediumLens || ''} disabled={!writable} onChange={event=>event.target.value?updateComposition({mediumLens:event.target.value,genreLens:composition.genreLens || 'general'}):onMetadata({composition:{}})}><option value="">{t('story.mediumLens_off')}</option>{['manju','cinema','storybook'].map(value=><option key={value} value={value}>{t('story.mediumLens_'+value)}</option>)}</select></label>
      {!!composition.mediumLens&&<><label>{t('story.genreLens')}<select aria-label={t('story.genreLens')} disabled={!writable} value={composition.genreLens || 'general'} onChange={event=>updateComposition({genreLens:event.target.value})}>{['general','melodrama','xianxia','comedy','suspense'].map(value=><option key={value} value={value}>{t('story.genreLens_'+value)}</option>)}</select></label>
        <button type="button" disabled={!writable||busy||!documentText(doc).trim()} onClick={collide}>{t('story.collideConditions')}</button>
        {(collisions?.candidates || [...new Set([...(trace.keptLabels || []),...(trace.uncheckedLabels || [])])].map(label=>({id:label,label}))).map(card=><label key={card.id}><input type="checkbox" disabled={!writable} checked={trace.keptLabels?.includes(card.label) || false} onChange={event=>updateTrace({keptLabels:event.target.checked?[...(trace.keptLabels || []),card.label]:(trace.keptLabels || []).filter(label=>label!==card.label),uncheckedLabels:event.target.checked?(trace.uncheckedLabels || []).filter(label=>label!==card.label):[...(trace.uncheckedLabels || []),card.label]})}/>{card.label}{card.conditionA&&<small>{card.conditionA} × {card.conditionB}</small>}</label>)}
        <label>{t('story.choiceFocus')}<select disabled={!writable} value={trace.focus || 'overall'} onChange={event=>updateTrace({focus:event.target.value})}>{['overall','collision','restraint','reversal','negative_space'].map(value=><option key={value} value={value}>{t('story.focus_'+value)}</option>)}</select></label>
        <label>{t('story.extraCondition')}<input disabled={!writable} maxLength={500} value={trace.extraCondition || ''} onChange={event=>updateTrace({extraCondition:event.target.value})}/></label>
        {collisions?.candidates?.[0]?.propSlice&&<p>{collisions.candidates[0].propSlice.join(' → ')}</p>}
      </>}
    </details>
    <details><summary>{t(p+'chapters')}</summary><p>{t(p+'chapterHelp')}</p>
      <ol>{chapters.map((chapter,index)=><li key={chapter.chapterKey || chapter.key}>
        <input aria-label={t(p+'chapterTitle')} disabled={!writable} value={chapter.title || ''} onChange={event=>updateChapters(chapters.map((item,i)=>i===index?{...item,title:event.target.value}:item))}/>
        <button type="button" disabled={!writable||index===0} onClick={()=>move(index,-1)}>{t(p+'moveUp')}</button><button type="button" disabled={!writable||index===chapters.length-1} onClick={()=>move(index,1)}>{t(p+'moveDown')}</button>
        <button type="button" disabled={!writable||index===chapters.length-1} onClick={()=>{const next=clone(chapters);next[index]={...chapter,blockBids:[...(chapter.blockBids || []),...(chapters[index+1].blockBids || [])],sections:[...(chapter.sections || []),...(chapters[index+1].sections || [])]};next.splice(index+1,1);updateChapters(next);}}>{t(p+'mergeNext')}</button>
        <button type="button" disabled={!writable} onClick={()=>updateChapters(chapters.filter((_,i)=>i!==index))}>{t(p+'removeBoundary')}</button>
        <ul>{(chapter.sections || []).map(section=><li key={section.sectionKey || section.key}>{section.title}</li>)}</ul>
        <button type="button" disabled={!writable||!title.trim()||!bids.length} onClick={()=>{updateChapters(unassign(chapters).map((item,i)=>i===index?{...item,sections:[...(item.sections || []),{sectionKey:'wsec_'+mutationId().replaceAll('-',''),title:title.trim(),blockBids:orderedBids}]}:item));setTitle('');setBids([]);}}>{t(p+'addSection')}</button>
      </li>)}</ol>
      <label>{t(p+'chapterTitle')}<input disabled={!writable} value={title} maxLength={200} onChange={event=>setTitle(event.target.value)}/></label>
      <fieldset disabled={!writable}><legend>{t(p+'chapterBlocks')}</legend>{(doc.content || []).map(node=><label key={node.attrs?.bid}><input type="checkbox" checked={bids.includes(node.attrs?.bid)} onChange={event=>setBids(items=>event.target.checked?[...items,node.attrs?.bid]:items.filter(id=>id!==node.attrs?.bid))}/>{documentText(node).slice(0,100) || t(p+'emptyParagraph')}</label>)}</fieldset>
      <button type="button" disabled={!writable||!title.trim()||!bids.length} onClick={add}>{t(p+'addChapter')}</button>
    </details>
  </section>;
}
