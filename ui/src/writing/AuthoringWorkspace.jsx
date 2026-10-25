import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from '../i18n/react.jsx';
import { storyRequest } from '../storyModel.js';
import { createWritingTransport, writingAction, mutationId } from './writingTransport.js';
import { createWritingJournal, journalScope } from './writingJournal.js';
import { WritingPersistence } from './writingPersistence.js';
import { WritingOutlineRecovery } from './writingOutlineRecovery.js';
import { baselineState, documentText, emptyDoc, refKey, sceneSliceBoundary, sceneSliceBlocks, replaceSceneSlice, textCounts, stable, sourceStructureForDoc, semanticEnumKey } from './writingModel.js';
import { WritingEditor } from './WritingEditor.jsx';
import { WritingOutline, WritingOutlineMerge } from './WritingOutline.jsx';
import { WritingVersions } from './WritingVersions.jsx';
import { WritingPreview } from './WritingPreview.jsx';
import { WritingRecovery } from './WritingRecovery.jsx';
import { WritingConflict } from './WritingConflict.jsx';
import { WritingSourceTools } from './WritingSourceTools.jsx';
import { createTextStoryboardAction } from './writingTasks.js';
import { impactRequest, impactSelection } from './writingImpactAdapter.js';
import { WritingImpactSetup } from './WritingImpactSetup.jsx';
import { WritingToolControls } from './writingToolControls.js';
import './authoring.css';
const p='writing.authoring.';
const blankResource=()=>({doc:emptyDoc(),version:0,docHash:null,structure:{chapters:[],sections:[]},composition:{}});
const workingResource=data=>({doc:data.doc,docHash:data.docHash,version:data.revision,structure:data.structure,composition:data.composition,productionInputs:data.productionInputs});

export function AuthoringWorkspace(props) {
  // Identity changes unmount every private state/cache/editor, including unresolved previews.
  return <WorkspaceSession key={JSON.stringify([props.slug,props.epId,props.me?.actor_id])} {...props}/>;
}
function WorkspaceSession({slug,epId,me,writable,ep,shots=[],request=storyRequest,controlRef,onChanged,onStage,onStatus,focusSource,renderTools}) {
  const {t}=useTranslation();
  const transport=useMemo(()=>createWritingTransport(epId,request),[epId,request]);
  const journal=useMemo(()=>createWritingJournal(),[]),tabId=useRef(mutationId());
  const [workspace,setWorkspace]=useState(null),[resourceRef,setResourceRef]=useState({kind:'working'}),[resource,setResource]=useState(null),[snapshot,setSnapshot]=useState(null),[error,setError]=useState(null),[panel,setPanel]=useState(null),[preview,setPreview]=useState(null),[selectedScene,setSelectedScene]=useState(null),[focusBid,setFocusBid]=useState(null),[focus,setFocus]=useState(false),[outlineOpen,setOutlineOpen]=useState(true),[fontSize,setFontSize]=useState(18),[lineHeight,setLineHeight]=useState(1.8),[pageWidth,setPageWidth]=useState(720),[duplicate,setDuplicate]=useState(false),[busy,setBusy]=useState(false),[switching,setSwitching]=useState(false);
  const taskAbort=useRef(new AbortController());
  const persistence=useRef(null),latest=useRef({}),mounted=useRef(true),loadSequence=useRef(0),editor=useRef(null),actionRetry=useRef(null),structureUndo=useRef(null);
  const activeSlice=useRef(null),[sliceGeneration,setSliceGeneration]=useState(0),ownDocumentAcks=useRef(new Set());
  const [toolRevision,setToolRevision]=useState(0),[outlineSnapshot,setOutlineSnapshot]=useState(null);
  const outlineRecovery=useMemo(()=>new WritingOutlineRecovery({slug,actorId:me.actor_id,epId,transport,journal,tabId:tabId.current,
    flushDocument:async options=>{
      const instance=persistence.current;if(instance&&!await instance.flush(options))return false;
      if(!mounted.current||instance!==persistence.current)return false;
      const current=await transport('workspace');if(!mounted.current||instance!==persistence.current)return false;
      const ownDocumentAdvance=latest.current.resourceRef.kind==='working'&&current.docHash===instance?.base.docHash&&ownDocumentAcks.current.has(current.docHash);
      if(current.docHash===instance?.base.docHash)setWorkspace(current);
      return {safe:true,structure:current.structure,ownDocumentAdvance};
    },
    notify:state=>{if(mounted.current){setOutlineSnapshot(state);setToolRevision(value=>value+1);}},
  }),[slug,me.actor_id,epId,transport,journal]);
  const toolControls=useMemo(()=>new WritingToolControls(()=>{if(mounted.current)setToolRevision(value=>value+1);}),[]);
  const registerToolControl=useCallback((key,control)=>toolControls.register(key,control),[toolControls]);
  latest.current={workspace,resourceRef,resource,snapshot,writable,onChanged,onStatus,selectedScene,panel,translate:t};
  const report=useCallback(error=>{if(mounted.current)setError(error);},[]);
  const fetchResource=useCallback(async(ref,data)=>{
    if(ref.kind==='working')return workingResource(data);
    if(ref.kind==='source')return await transport(`sources/${ref.mode}`) || blankResource();
    const result=await transport(`${ref.kind==='branch'?'branches':'versions'}/${encodeURIComponent(ref.id)}`);
    return ref.kind==='version'?{...result.snapshot,name:result.name,locked:true,versionId:result.versionId}:result;
  },[transport]);
  const reload=useCallback(async()=>{
    const data=await transport('workspace');if(!mounted.current)return;
    setWorkspace(data);outlineRecovery.refresh(data.structure);
    const current=latest.current.resourceRef;
    const next=await fetchResource(current,data);if(!mounted.current)return;
    if(persistence.current?.refresh(next)){activeSlice.current=null;setResource(next);setSnapshot(persistence.current.snapshot());}
    else if(!persistence.current){setResource(next);}
    return data;
  },[transport,fetchResource,outlineRecovery]);
  useEffect(()=>{
    if(outlineSnapshot?.state==='saved'&&workspace&&outlineSnapshot.base?.version>workspace.structure.version)reload().then(()=>latest.current.onChanged?.()).catch(report);
  },[outlineSnapshot,workspace,reload,report]);
  const load=useCallback(async(ref)=>{
    const sequence=++loadSequence.current;
    let data=await transport('workspace');
    if(writable && (!data.structure.initialized || data.structure.stale)){await writingAction(transport,'initialize',{expectedDocHash:data.docHash})();data=await transport('workspace');}
    const next=await fetchResource(ref,data);
    if(!mounted.current || sequence!==loadSequence.current)return;
    if(!next?.doc)throw new Error(latest.current.translate(p+'invalidWorkspace'));
    persistence.current?.dispose();activeSlice.current=null;outlineRecovery.refresh(data.structure);if(!outlineRecovery.discovered)await outlineRecovery.discover();
    if(!mounted.current || sequence!==loadSequence.current)return;
    setWorkspace(data);setResourceRef(ref);setResource(next);setSelectedScene(ref.kind==='working'&&documentText(next.doc).length>100000?data.structure.scenes?.[0]?.sceneKey || null:null);setPreview(null);structureUndo.current=null;
    if(ref.kind==='version'){persistence.current=null;setSnapshot({state:'readonly',dirty:false,recoverable:false,doc:next.doc,docHash:next.docHash});return data;}
    const instance=new WritingPersistence({resourceRef:ref,initial:next,transport,journal,
      scope:journalScope({slug,actorId:me.actor_id,epId,resourceKind:ref.kind,resourceId:ref.id || ref.mode || 'main'}),tabId:tabId.current,
      notify:state=>{if(mounted.current&&persistence.current===instance){if(ref.kind==='working'&&instance.base.clientMutationId){ownDocumentAcks.current.add(instance.base.docHash);if(ownDocumentAcks.current.size>32)ownDocumentAcks.current.delete(ownDocumentAcks.current.values().next().value);}setSnapshot(state);if(ref.kind==='working'&&state.state==='saved'&&state.docHash!==latest.current.workspace?.docHash){transport('workspace').then(data=>{if(mounted.current&&persistence.current===instance&&data.docHash===instance.base.docHash){setWorkspace(data);outlineRecovery.refresh(data.structure);}}).catch(report);}}}});
    persistence.current=instance;setSnapshot(instance.snapshot());await instance.discover();return data;
  },[transport,fetchResource,journal,slug,me.actor_id,epId,writable,report,outlineRecovery]);
  useEffect(()=>{mounted.current=true;taskAbort.current=new AbortController();load({kind:'working'}).catch(report);return()=>{mounted.current=false;loadSequence.current++;persistence.current?.dispose();taskAbort.current.abort();};},[load,report]);
  useEffect(()=>()=>outlineRecovery.dispose(),[outlineRecovery]);
  useEffect(()=>registerToolControl('outline:metadata',outlineRecovery),[registerToolControl,outlineRecovery]);
  // Tool callers get this manuscript-only boundary: previews must not submit unrelated forms.
  const flushDocument=useCallback(async(options={})=>persistence.current?await persistence.current.flush(options.reason==='identity'?{...options,requireServer:true}:options):!!latest.current.resource,[]);
  const flush=useCallback(async(options={})=>{
    const documentSafe=await flushDocument(options);
    if(options.requireServer&&options.reason!=='identity')return documentSafe;
    const toolsSafe=await toolControls.flush(options);return documentSafe&&toolsSafe;
  },[flushDocument,toolControls]);
  const selectResource=async ref=>{setSwitching(true);try{if(await flush()){setError(null);return await load(ref);}}catch(error){report(error);}finally{setSwitching(false);}};
  const navigateShots=useCallback(async value=>{if(await flush()&&mounted.current)await onStage?.(value);},[flush,onStage]);
  const navigateSource=useCallback(async ref=>{
    let data=latest.current.workspace;
    if(!await flush())return false;
    if(latest.current.resourceRef.kind!=='working'){try{setSwitching(true);data=await load({kind:'working'});}catch(error){report(error);return;}finally{setSwitching(false);}}
    const scene=(data?.structure?.scenes || []).find(scene=>scene.sceneKey===ref.sceneKey);
    if(!scene){report(new Error(latest.current.translate(p+'sourceNotInWorking')));return false;}activeSlice.current=null;setSliceGeneration(value=>value+1);setSelectedScene(scene.sceneKey);setFocusBid((scene.beats || []).find(beat=>beat.beatKey===ref.beatKey)?.blockBids?.[0] || scene.headingBid);
  },[flush,load,report]);
  const workspaceReady=!!workspace;
  useEffect(()=>{if(focusSource&&workspaceReady)navigateSource(focusSource);},[focusSource,workspaceReady,navigateSource]);
  useEffect(()=>{
    if(!controlRef)return;
    const summary=()=>toolControls.summary(persistence.current?.snapshot() || {state:'readonly',dirty:false,recoverable:false});
    const instance={flush,isDirty:()=>summary().dirty,recoveryState:()=>summary(),consoleContext:()=>({episodeId:epId,sourceRef:latest.current.resourceRef,sceneKeys:latest.current.selectedScene?[latest.current.selectedScene]:[],docHash:persistence.current?.base.docHash || latest.current.resource?.docHash}),focusSource:navigateSource};
    controlRef.current=instance;return()=>{if(controlRef.current===instance)controlRef.current=null;};
  },[controlRef,epId,flush,navigateSource,toolControls]);
  useEffect(()=>{if(snapshot)onStatus?.({...toolControls.summary(snapshot),docHash:snapshot.docHash});},[snapshot,onStatus,toolControls,toolRevision]);
  useEffect(()=>{
    const unload=event=>{const state=toolControls.summary(persistence.current?.snapshot());if(state.dirty&&!state.recoverable){event.preventDefault();event.returnValue='';}};
    const reconnect=()=>{if(persistence.current?.state==='local_only')persistence.current.save();if(outlineRecovery.state==='local_only')outlineRecovery.save();};
    window.addEventListener('beforeunload',unload);window.addEventListener('online',reconnect);
    return()=>{window.removeEventListener('beforeunload',unload);window.removeEventListener('online',reconnect);};
  },[toolControls,outlineRecovery]);
  useEffect(()=>{
    if(!globalThis.BroadcastChannel)return;
    const channel=new BroadcastChannel('zerofield-writing-'+JSON.stringify([slug,me.actor_id,epId,refKey(resourceRef)]));
    channel.onmessage=event=>{if(event.data.tabId!==tabId.current){setDuplicate(true);if(event.data.kind==='hello')channel.postMessage({kind:'present',tabId:tabId.current});}};
    channel.postMessage({kind:'hello',tabId:tabId.current});return()=>channel.close();
  },[slug,me.actor_id,epId,resourceRef]);
  const requireServer=async()=>{if(!await flushDocument({requireServer:true}))throw new Error(t(p+'serverSaveRequired'));};
  const run=async fn=>{if(busy)return;setBusy(true);setError(null);try{await fn();}catch(error){report(error);}finally{if(mounted.current)setBusy(false);}};
  const post=async(tail,body)=>{
    const retry=writingAction(transport,tail,body);actionRetry.current=async()=>{const result=await retry();if(tail==='previews'){setPreview(result);setPanel('preview');}else if(tail.endsWith('/apply')){setPreview(null);setPanel(null);}return result;};
    const result=await retry();actionRetry.current=null;return result;
  };
  const structure=workspace?.structure || resource?.structure || {scenes:[],lanes:[]};
  const previewStructure=operation=>run(async()=>{await requireServer();await requireOutline();const current=await transport('workspace');const result=await post('previews',{kind:'structure',targetDocHash:current.docHash,structureVersion:current.structure.version,operation});setPreview(result);setPanel('preview');});
  const metadata=(scenePatch,lanePatch)=>outlineRecovery.change(scenePatch,lanePatch);
  const requireOutline=async()=>{if(!await outlineRecovery.flush({requireServer:true}))throw new Error(t(p+'serverSaveRequired'));};
  const apply=async selection=>{
    await requireServer();
    let active=preview;
    if(preview.kind==='impact'){
      active=await transport(`previews/${encodeURIComponent(preview.previewId)}`);setPreview(active);
      if(active.status!=='pending'||active.expiresAt*1000<=Date.now())throw new Error(t(p+'stalePreview'));
      selection=impactSelection(active,selection.actions);
    }
    const result=await post(`previews/${encodeURIComponent(active.previewId)}/apply`,{expectedPreviewVersion:active.version,selection});
    structureUndo.current=preview.kind==='structure'&&result.beforeVersionId ? {snapshotId:result.beforeVersionId,docHash:result.docHash,structureHash:result.structure?.structureHash} : null;setPreview(null);setPanel(null);if(['promotion','adaptation'].includes(preview.kind))await load({kind:'working'});else await reload();if(mounted.current)onChanged?.(result);
  };
  const previewImpact=async options=>{
    await requireServer();
    const target=options.targetRef.kind==='working'?await transport('workspace'):await transport(`versions/${encodeURIComponent(options.targetRef.id)}`);
    const body=impactRequest({...options,expectedSourceHash:target.docHash || target.snapshot?.docHash});
    const result=await post('previews',body);setPreview(result);setPanel('preview');
  };
  const adaptation=()=>run(async()=>{await requireServer();const current=persistence.current.base;const result=await post('previews',{kind:'adaptation',sourceRef:resourceRef,expectedSourceHash:current.docHash,targetDocHash:workspace.docHash,targetScenes:4,breakdownMode:'auto',...(current.composition || {})});setPreview(result);setPanel('preview');await reload();});
  const buildText=()=>run(async()=>{await requireServer();const action=createTextStoryboardAction(request,epId,{breakdownMode:ep?.settings?.breakdownMode || 'auto',signal:taskAbort.current.signal});actionRetry.current=async()=>{const result=await action();if(!mounted.current)return result;await onChanged?.(result);await reload();if(mounted.current)onStage?.({shotIds:[]});return result;};await actionRetry.current();actionRetry.current=null;});
  const download=()=>{
    const url=URL.createObjectURL(new Blob([documentText(persistence.current?.doc || resource.doc)],{type:'text/plain;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='writing-recovery.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),0);
  };
  const openPanel=name=>setPanel(current=>current===name?null:name);
  const keyboard=event=>{
    const searchShortcut=(event.ctrlKey||event.metaKey)&&event.shiftKey&&event.key.toLowerCase()==='f';
    // The injected tools panel owns search mode and listens at window; let that one shortcut through.
    if(!searchShortcut)event.stopPropagation();
    if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'){event.preventDefault();flush({reason:'save'});}
    if(searchShortcut){event.preventDefault();setFocus(false);setPanel('tools');}
    if(event.key==='Escape'&&focus){event.preventDefault();setFocus(false);editor.current?.commands.focus();}
  };
  const counts=useMemo(()=>snapshot?.doc?textCounts(snapshot.doc):{words:0,characters:0},[snapshot?.doc]);
  if(!workspace||!resource||!snapshot)return <section className="authoring-workspace" aria-busy="true"><p role={error?'alert':'status'}>{error?.message || t(p+'loading')}</p></section>;
  const doc=snapshot.doc,serverScene=resourceRef.kind==='working'&&selectedScene?structure.scenes?.find(scene=>scene.sceneKey===selectedScene):null;
  const sliceKey=refKey(resourceRef)+':'+sliceGeneration;
  const pendingSlice=activeSlice.current?.key===sliceKey&&activeSlice.current.instance===persistence.current&&(snapshot.dirty||persistence.current?.composing);
  if(!serverScene&&!pendingSlice)activeSlice.current=null;
  else if(serverScene&&(!activeSlice.current||activeSlice.current.key!==sliceKey||activeSlice.current.instance!==persistence.current||
    (!snapshot.dirty&&!persistence.current?.composing&&workspace.docHash===snapshot.docHash&&activeSlice.current.hash!==workspace.docHash))){
    activeSlice.current={key:sliceKey,instance:persistence.current,hash:workspace.docHash,boundary:sceneSliceBoundary(workspace.doc,serverScene)};
  }
  const slice=activeSlice.current,partial=slice?sceneSliceBlocks(doc,slice.boundary):null;
  const shown=partial || doc,baseline=baselineState(workspace);
  const editable=!!writable&&(!slice||!!partial)&&!switching&&resourceRef.kind!=='version'&&!resource.locked&&!snapshot.recoveries?.length&&!['conflict','auth_lost'].includes(snapshot.state);
  const aggregate=toolControls.summary(snapshot),toolSummary=toolControls.summary();
  const toolProps={slug,epId,me,writable,workspace,resourceRef,selectedSceneKeys:selectedScene?[selectedScene]:[],selectedSubjectId:null,transport,flush:flushDocument,registerToolControl,reload,onNavigateSource:navigateSource,onNavigateShots:navigateShots,onError:report,onChanged};
  return <section className={`authoring-workspace${focus?' writing-focus':''}`} onKeyDown={keyboard} style={{'--writing-font':fontSize+'px','--writing-line-height':lineHeight,'--writing-width':pageWidth+'px'}}>
    <header className="writing-toolbar">
      <label>{t(p+'manuscript')}<select aria-label={t(p+'manuscript')} value={refKey(resourceRef)} onChange={event=>{const [kind,value]=event.target.value.split(':');selectResource(kind==='working'?{kind}:kind==='source'?{kind,mode:value}:{kind,id:value});}}>
        <option value="working:main">{t(p+'workingScript')}</option><option value="source:idea">{t(p+'privateIdea')}</option><option value="source:novel">{t(p+'privateNovel')}</option>
        {['branch','version'].includes(resourceRef.kind)&&![...(workspace.branches?.items || []),...(workspace.versions?.items || [])].some(item=>(item.branchId || item.versionId)===resourceRef.id)&&<option value={refKey(resourceRef)}>{resource.name || resourceRef.id}</option>}
        {(workspace.branches?.items || workspace.branches || []).map(branch=><option key={branch.branchId} value={'branch:'+branch.branchId}>{branch.name}</option>)}
        {(workspace.versions?.items || workspace.versions || []).map(version=><option key={version.versionId} value={'version:'+version.versionId}>{version.name}</option>)}
      </select></label>
      <button type="button" aria-pressed={outlineOpen} onClick={()=>setOutlineOpen(!outlineOpen)}>{t(p+'outline')}</button>
      <button type="button" aria-pressed={panel==='versions'} onClick={()=>openPanel('versions')}>{t(p+'versions')}</button>
      {renderTools&&<button type="button" aria-pressed={panel==='tools'} onClick={()=>openPanel('tools')}>{t(p+'tools')}</button>}
      <button type="button" aria-pressed={focus} onClick={()=>setFocus(!focus)}>{t(p+'focus')}</button>
      <details><summary>{t(p+'typography')}</summary><label>{t(p+'fontSize')}<input type="range" min="14" max="24" value={fontSize} onChange={e=>setFontSize(+e.target.value)}/></label><label>{t(p+'lineHeight')}<input type="range" min="1.4" max="2.2" step="0.1" value={lineHeight} onChange={e=>setLineHeight(+e.target.value)}/></label><label>{t(p+'pageWidth')}<input type="range" min="560" max="960" step="20" value={pageWidth} onChange={e=>setPageWidth(+e.target.value)}/></label></details>
    </header>
    {error&&<div role="alert">{error.message}{actionRetry.current&&![401,403,409].includes(error.status)&&<button type="button" onClick={()=>run(async()=>{await actionRetry.current();actionRetry.current=null;await reload();})}>{t(p+'retryAction')}</button>}</div>}
    {duplicate&&<p role="status">{t(p+'duplicateTab')}</p>}
    <div className="writing-layout">
      {outlineOpen&&resourceRef.kind==='working'&&<aside className="writing-left"><WritingOutline structure={structure} metadataDraft={outlineSnapshot?.draft} onComposition={value=>outlineRecovery.setComposing(value)} doc={doc} writable={editable&&!busy&&!outlineSnapshot?.recoveries?.length&&outlineSnapshot?.state!=='auth_lost'} selected={selectedScene} onSelect={async key=>{if(await flush()){activeSlice.current=null;setSliceGeneration(value=>value+1);setSelectedScene(key);setFocusBid(structure.scenes.find(scene=>scene.sceneKey===key)?.headingBid);}}} onMetadata={metadata} onStructure={previewStructure} onShots={navigateShots} onUndo={structureUndo.current?()=>run(async()=>{await requireServer();const current=await transport('workspace'),undo=structureUndo.current;if(current.docHash!==undo.docHash || undo.structureHash&&current.structure.structureHash!==undo.structureHash)throw new Error(t(p+'undoStale'));const result=await post('previews',{kind:'structure',targetDocHash:current.docHash,structureVersion:current.structure.version,operation:{type:'restore',snapshotId:undo.snapshotId}});setPreview(result);setPanel('preview');}):null}/></aside>}
      <main className="writing-manuscript">
        {slice&&!partial&&<p role="alert">{t(p+'sceneBoundaryChanged')}</p>}
        {(outlineSnapshot?.dirty||outlineSnapshot?.localError)&&<section className="writing-outline-recovery" aria-label={t(p+'outlineDraft')}>
          <h3>{t(p+'outlineDraft')}</h3><p role="status">{t(p+semanticEnumKey('state',outlineSnapshot.state))}</p>
          {outlineSnapshot.localError&&<p role="alert">{t(p+'localRecoveryFailed')}<button type="button" onClick={()=>run(()=>outlineRecovery.dirty()?outlineRecovery.checkpoint():outlineRecovery.discover())}>{t(p+'retryAction')}</button></p>}
          {outlineSnapshot.error&&<p role="alert">{outlineSnapshot.error.message}</p>}
          {outlineSnapshot.conflict&&<><p role="alert">{t(p+'outlineConflictReviewNotice',{version:outlineSnapshot.baseVersion})}</p>
            <button type="button" onClick={()=>run(async()=>{const current=await transport('workspace');outlineRecovery.reviewCurrent(current.structure);})}>{t(p+'reviewOutline')}</button>
            {outlineSnapshot.review&&<WritingOutlineMerge key={outlineSnapshot.review.sequence+':'+outlineSnapshot.review.structure.version} review={outlineSnapshot.review} onApply={choices=>run(async()=>{const current=await transport('workspace');if(await outlineRecovery.resolveReviewed(outlineSnapshot.review,choices,current.structure))await outlineRecovery.save({explicit:true});else{outlineRecovery.reviewCurrent(current.structure);throw new Error(t(p+'outlineReviewStale'));}})}/>}</>}
          {outlineSnapshot.recoveries.map(row=><div key={row.key}><pre>{JSON.stringify(row.draft,null,2)}</pre>
            <button type="button" onClick={()=>run(async()=>{const current=await transport('workspace');await outlineRecovery.restore(row,current.structure);})}>{t(p+'restoreOutline')}</button>
            <button type="button" onClick={()=>run(()=>outlineRecovery.discardRecovery(row))}>{t(p+'discardOutlineRecovery')}</button>
            <button type="button" onClick={()=>run(()=>outlineRecovery.preserveRecovery(row))}>{t(p+'keepOutlineRecovery')}</button>
          </div>)}
          {outlineRecovery.dirty()&&<><button type="button" disabled={!!outlineSnapshot.conflict||outlineSnapshot.state==='auth_lost'||outlineSnapshot.state==='saving'} onClick={()=>run(()=>outlineRecovery.save({explicit:true}))}>{t(p+'saveOutline')}</button>
            <button type="button" onClick={()=>run(async()=>{const current=await transport('workspace');await outlineRecovery.discard(current.structure);await reload();})}>{t(p+'discardOutline')}</button>
            <button type="button" onClick={()=>run(()=>outlineRecovery.preserveIdentity())}>{t(p+'keepOutline')}</button>
            <button type="button" onClick={()=>{const url=URL.createObjectURL(new Blob([JSON.stringify({baseVersion:outlineSnapshot.baseVersion,...outlineSnapshot.draft},null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='outline-recovery.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),0);}}>{t(p+'downloadOutline')}</button></>}
        </section>}
        <p className="writing-scope">{t(p+(resourceRef.kind==='working'?'sharedWorking':resourceRef.kind==='version'?'sharedSnapshot':'privateScope'))}</p>
        {snapshot.recoveries?.length>0&&<WritingRecovery snapshot={snapshot} persistence={persistence.current} onError={report}/>}
        {snapshot.state==='conflict'&&<WritingConflict persistence={persistence.current} fetchServer={async()=>fetchResource(resourceRef,await transport('workspace'))} onError={report} onDownload={download}/>}
        {snapshot.state==='auth_lost'&&<p role="alert">{t(p+'authLost')}</p>}
        {snapshot.error&&snapshot.state!=='auth_lost'&&<p role="alert">{snapshot.error.message}</p>}
        {snapshot.localError&&<p role="alert">{t(p+'localRecoveryFailed')}</p>}
        {resourceRef.kind==='source'&&<WritingSourceTools key={resourceRef.mode} doc={doc} structure={snapshot.structure} composition={snapshot.composition} writable={editable} onDocument={next=>persistence.current.change(next)} onMetadata={patch=>persistence.current.changeMetadata(patch)} request={request} epId={epId} onError={report}/>}
        <WritingEditor key={refKey(resourceRef)} sliceKey={sliceKey} doc={shown} writable={editable} me={me} privateResource={['source','branch'].includes(resourceRef.kind)} locks={resourceRef.kind==='working'?(workspace.locks || []):[]} label={t(p+'editorLabel')} focusBid={focusBid} onReady={value=>{editor.current=value;}} onComposition={value=>persistence.current?.setComposing(value)} onChange={next=>{if(editable){if(slice){if(activeSlice.current!==slice)return;persistence.current?.change(replaceSceneSlice(persistence.current.doc,slice.boundary,next));}else persistence.current?.change(next);if(resourceRef.kind==='source')persistence.current?.changeMetadata({structure:sourceStructureForDoc(persistence.current.draftStructure,next)});}}}/>
        {['local_only','save_failed','auth_lost'].includes(snapshot.state)&&<div><button type="button" onClick={download}>{t(p+'downloadDraft')}</button>{snapshot.state!=='auth_lost'&&<button type="button" onClick={()=>persistence.current.save()}>{t(p+'retrySave')}</button>}</div>}
      </main>
      <aside className="writing-right" hidden={!panel}>
        {panel&&<button type="button" onClick={()=>setPanel(null)}>{t(p+'closePanel')}</button>}
        {panel==='versions'&&<WritingVersions workspace={workspace} resourceRef={resourceRef} resource={()=>persistence.current?.base || resource} writable={writable} transport={transport} flush={flushDocument} reload={reload} onSelect={selectResource} onPreview={result=>{setPreview(result);setPanel('preview');}} onError={report}/>}
        {panel==='impact'&&<WritingImpactSetup key={refKey(resourceRef)} targetRef={resourceRef.kind==='version'?{kind:'version',id:resourceRef.id}:{kind:'working'}} structure={resourceRef.kind==='version'?resource.structure:structure} shots={shots} confirmBaseline={!!workspace.baseline?.scriptDirty || !workspace.baseline?.versionId} writable={writable} onPreview={previewImpact}/>}
        {panel==='preview'&&preview&&<WritingPreview key={preview.previewId} preview={preview} shots={shots} writable={writable} onApply={apply} onClose={()=>setPanel(null)} onShots={navigateShots} onSource={navigateSource} onRevise={preview.kind==='impact'?()=>setPanel('impact'):undefined} onRefresh={preview.kind==='impact'?async()=>{const fresh=await transport(`previews/${encodeURIComponent(preview.previewId)}`);setPreview(fresh);}:undefined}/>}
        {/* Keep tool/editor instances alive through panel toggles. */}
        {renderTools&&<div hidden={panel!=='tools'}>{renderTools(toolProps)}</div>}
      </aside>
    </div>
    <footer className="writing-status"><span role="status" aria-live="polite">{t(p+semanticEnumKey('state',snapshot.state))}{snapshot.savedAt&&snapshot.state==='saved'?' · '+new Date(snapshot.savedAt).toLocaleTimeString():''}</span>
      {aggregate.tools.some(item=>item.dirty||item.recoverable)&&<span data-writing-tool-status="true">{t(p+'toolDraftStatus',{state:t(p+semanticEnumKey('state',toolSummary.state))})}</span>}
      <span title={t(p+'wordCountRule')}>{t(p+'counts',counts)}</span><span>{t(p+semanticEnumKey('baseline',baseline.kind),{name:baseline.name})}{baseline.dirty?' · '+t(p+'scriptChanged'):''}</span>
      {writable&&resourceRef.kind==='source'?<button type="button" className={panel?undefined:'writing-primary'} disabled={busy || !editable} onClick={adaptation}>{t(p+'previewAdaptation')}</button>:['working','version'].includes(resourceRef.kind)&&<button type="button" className={panel?undefined:'writing-primary'} disabled={busy||!writable} onClick={shots.length||resourceRef.kind==='version'?()=>setPanel('impact'):buildText}>{t(p+(shots.length||resourceRef.kind==='version'?'reviewImpact':'confirmAndBuild'))}</button>}
      <button type="button" onClick={()=>navigateShots({shotIds:[]})}>{t(p+'goToStage')}</button>
    </footer>
  </section>;
}
