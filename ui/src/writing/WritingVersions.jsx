import { useRef, useState } from 'react';
import { useTranslation } from '../i18n/react.jsx';
import { writingAction, mutationId } from './writingTransport.js';
import { documentText, semanticEnumKey } from './writingModel.js';
const p='writing.authoring.';
export function WritingVersions({workspace,resourceRef,resource,writable,transport,flush,reload,onSelect,onPreview,onError}) {
  const retry=useRef(null);const [retryPending,setRetryPending]=useState(false);
  const {t}=useTranslation();const [name,setName]=useState(''),[share,setShare]=useState(false),[busy,setBusy]=useState(false),[comparison,setComparison]=useState(null),[selectedScenes,setSelectedScenes]=useState([]),[compareRef,setCompareRef]=useState(null),[rightHash,setRightHash]=useState(null),[leftChoice,setLeftChoice]=useState('working'),[extraVersions,setExtraVersions]=useState([]),[extraBranches,setExtraBranches]=useState([]),[versionCursor,setVersionCursor]=useState(undefined),[branchCursor,setBranchCursor]=useState(undefined);
  const versions=[...(workspace.versions?.items || workspace.versions || []),...extraVersions],branches=[...(workspace.branches?.items || workspace.branches || []),...extraBranches];
  const loadMore=kind=>run(async()=>{const cursor=kind==='version'?(versionCursor===undefined?workspace.versions?.nextCursor:versionCursor):(branchCursor===undefined?workspace.branches?.nextCursor:branchCursor);const data=await transport(`${kind==='version'?'versions':'branches'}?cursor=${encodeURIComponent(cursor)}&limit=100`);if(kind==='version'){setExtraVersions(items=>[...items,...data.items]);setVersionCursor(data.nextCursor);}else{setExtraBranches(items=>[...items,...data.items]);setBranchCursor(data.nextCursor);}});
  const run=async fn=>{setBusy(true);try{await fn();}catch(error){onError?.(error);}finally{setBusy(false);}};
  const mutate=async(tail,method,body)=>{const action=method==='POST'?writingAction(transport,tail,body):()=>transport(tail,method,body);retry.current=async()=>{const result=await action();await reload();if(tail==='branches')await onSelect({kind:'branch',id:result.branchId});if(tail==='previews')onPreview(result);setName('');return result;};try{const result=await action();retry.current=null;setRetryPending(false);return result;}catch(error){if(!error.status||error.status>=500)setRetryPending(true);else retry.current=null;throw error;}};
  const serverFlush=async()=>{if(!await flush({requireServer:true}))throw new Error(t(p+'serverSaveRequired'));};
  const snapshot=()=>run(async()=>{await serverFlush();await mutate('versions','POST',{name:name.trim(),sourceRef:resourceRef,expectedSourceHash:resource().docHash,share:true});setName('');await reload();});
  const branch=()=>run(async()=>{await serverFlush();const created=await mutate('branches','POST',{name:name.trim(),sourceRef:resourceRef,expectedSourceHash:resource().docHash});setName('');await reload();await onSelect({kind:'branch',id:created.branchId});});
  const compare=ref=>run(async()=>{await serverFlush();const [kind,id]=leftChoice.split(':');const leftRef=kind==='working'?{kind:'working'}:{kind,id};const leftPath=kind==='working'?'workspace':`${kind==='branch'?'branches':'versions'}/${encodeURIComponent(id)}`;const [left,right]=await Promise.all([transport(leftPath),transport(`${ref.kind==='branch'?'branches':'versions'}/${encodeURIComponent(ref.id)}`)]);const hash=right.docHash || right.snapshot?.docHash;const result=await writingAction(transport,'compare',{leftRef,rightRef:ref,expectedHashes:{left:left.docHash || left.snapshot?.docHash,right:hash}})();setCompareRef(ref);setRightHash(hash);setComparison(result);setSelectedScenes([]);});
  const promote=whole=>run(async()=>{
    await serverFlush();const latest=await transport('workspace');
    const preview=await mutate('previews','POST',{kind:'promotion',sourceRef:compareRef,expectedSourceHash:rightHash,targetDocHash:latest.docHash,...(whole?{whole:true}:{sceneKeys:selectedScenes})});onPreview(preview);
  });
  const catalog=(item,kind,patch)=>run(async()=>{
    const id=kind==='version'?item.versionId:item.branchId;
    const body={...(kind==='version'?{baseCatalogVersion:item.catalogVersion}:{baseVersion:item.version}),clientMutationId:mutationId(),...patch};
    await mutate(`${kind==='version'?'versions':'branches'}/${encodeURIComponent(id)}`,'PATCH',body);await reload();
  });
  return <section className="writing-versions" aria-label={t(p+'versions')}>
    <h2>{t(p+'versions')}</h2><p>{t(p+'versionExplanation')}</p>
    {retryPending&&<button type="button" disabled={busy} onClick={()=>run(async()=>{await retry.current();retry.current=null;setRetryPending(false);})}>{t(p+'retryAction')}</button>}
    {writable&&<fieldset disabled={retryPending}><div><label>{t(p+'versionName')}<input value={name} maxLength={200} onChange={event=>setName(event.target.value)}/></label>
      <label><input type="checkbox" checked={share} onChange={event=>setShare(event.target.checked)}/>{t(p+'shareSnapshot')}</label>
      <button type="button" disabled={busy || !name.trim() || !share || resourceRef.kind==='source'} onClick={snapshot}>{t(p+'saveVersion')}</button>
      <button type="button" disabled={busy || !name.trim()} onClick={branch}>{t(p+'createBranch')}</button>
    </div></fieldset>}
    <label>{t(p+'comparisonReference')}<select aria-label={t(p+'comparisonReference')} value={leftChoice} onChange={event=>setLeftChoice(event.target.value)}><option value="working">{t(p+'workingScript')}</option>{versions.map(item=><option key={item.versionId} value={'version:'+item.versionId}>{item.name}</option>)}{branches.map(item=><option key={item.branchId} value={'branch:'+item.branchId}>{item.name}</option>)}</select></label>
    <ul>{[...versions.map(item=>({...item,kind:'version'})),...branches.map(item=>({...item,kind:'branch'}))].map(item=>{
      const id=item.versionId || item.branchId,pinned=item.pinned || workspace.baseline?.versionId===id;return <li key={id}>
        <button type="button" disabled={busy} onClick={()=>onSelect({kind:item.kind,id})}>{item.name} · {item.createdBy} · {item.createdAt}</button>
        <small>{t(p+(item.kind==='branch'?'privateBranch':'sharedSnapshot'))} {item.locked&&t(p+'locked')}</small>
        <button type="button" disabled={busy} onClick={()=>compare({kind:item.kind,id})}>{t(p+'compare')}</button>
        {writable&&!retryPending&&<>
          <button type="button" disabled={busy || pinned} onClick={()=>catalog(item,item.kind,{locked:!item.locked})}>{t(p+(item.locked?'unlock':'lock'))}</button>
          <button type="button" disabled={busy || pinned || item.locked || !name.trim()} onClick={()=>catalog(item,item.kind,{name:name.trim()})}>{t(p+'rename')}</button>
          <button type="button" disabled={busy || pinned || item.locked} onClick={()=>catalog(item,item.kind,{archived:!item.archived})}>{t(p+(item.archived?'restoreCatalog':'archive'))}</button>
        </>}
      </li>;
    })}</ul>
    {(versionCursor===undefined?workspace.versions?.nextCursor:versionCursor)&&<button type="button" disabled={busy} onClick={()=>loadMore('version')}>{t(p+'moreVersions')}</button>}
    {(branchCursor===undefined?workspace.branches?.nextCursor:branchCursor)&&<button type="button" disabled={busy} onClick={()=>loadMore('branch')}>{t(p+'moreBranches')}</button>}
    {comparison&&<section aria-label={t(p+'comparison')}>
      <h3>{t(p+'comparison')}</h3>
      {(comparison.scenes || comparison.changes || []).map((scene,index)=><article key={scene.sceneKey || index}>
        <label><input type="checkbox" disabled={!scene.sceneKey} checked={selectedScenes.includes(scene.sceneKey)} onChange={event=>setSelectedScenes(keys=>event.target.checked?[...keys,scene.sceneKey]:keys.filter(key=>key!==scene.sceneKey))}/>{scene.title || scene.sceneKey} · {t(p+semanticEnumKey('diff',scene.state || scene.kind || 'modified'),{defaultValue:scene.state || scene.kind})}</label>
        {scene.mapping==='unresolved'&&<p>{t(p+'diffUnresolved')}</p>}
        <div className="writing-compare-columns"><pre>{scene.left?.title}</pre><pre>{scene.right?.title}</pre></div>
      </article>)}
      {(comparison.blocks || []).map(block=><div className="writing-compare-columns" key={block.bid}><pre>{documentText(block.left)}</pre><pre>{documentText(block.right)}</pre></div>)}
      {writable&&<><button type="button" disabled={busy || !selectedScenes.length} onClick={()=>promote(false)}>{t(p+'previewSelectedScenes')}</button><button type="button" disabled={busy} onClick={()=>promote(true)}>{t(p+'previewWhole')}</button></>}
    </section>}
  </section>;
}
