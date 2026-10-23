import React, {useEffect, useRef, useState} from 'react';
import {useTranslation} from '../i18n/react.jsx';
import {actionId, cleanPrintHtml, downloadBlob, expiryLabel, expiryTime, frozenRequest, previewUsable, readResource, resourceOptions, serverFlush} from './writingToolsModel.js';
import {ToolsNotice, useToolsAction, useToolsResourceCatalog} from './writingToolsState.js';

export function WritingFiles({writable, workspace, resourceRef = {kind:'working'}, selectedSceneKeys = [], transport, flush, reload, onError, onChanged}) {
  const {t} = useTranslation();
  const task = useToolsAction(onError);
  const catalog = useToolsResourceCatalog(workspace);
  const options = resourceOptions(catalog.workspace,resourceRef);
  const [purpose,setPurpose] = useState('novel');
  const [file,setFile] = useState(null);
  const [upload,setUpload] = useState(null);
  const [sections,setSections] = useState([]);
  const [preview,setPreview] = useState(null);
  const [importState,setImportState] = useState('');
  const [importPending,setImportPending] = useState(false);
  const [applyingImport,setApplyingImport] = useState(false);
  const [sourceRef,setSourceRef] = useState(resourceRef);
  const [range,setRange] = useState('whole');
  const [format,setFormat] = useState('docx');
  const [summaries,setSummaries] = useState(false);
  const [bibleIds,setBibleIds] = useState('');
  const [handle,setHandle] = useState(null);
  const [exportState,setExportState] = useState('');
  const [printHtml,setPrintHtml] = useState('');
  const frame = useRef(null);
  const uploadSequence = useRef(0);
  const [,tick] = useState(0);
  useEffect(() => {const timer=setInterval(() => tick(value=>value+1),15000);return () => clearInterval(timer);},[]);
  useEffect(() => {if (['stale','locked','conflict','auth'].includes(task.error)) {
    setPreview(value=>value ? {...value,stale:true} : null);
    if (task.error==='auth') {setHandle(null);setPrintHtml('');}
  }},[task.error]);
  function uploadFile() {
    if (!file) return;
    const sequence = ++uploadSequence.current;
    const request = frozenRequest(transport,'imports','POST',file,{raw:true,headers:{'X-Filename':encodeURIComponent(file.name),'X-Writing-Purpose':purpose,'Content-Type':'application/octet-stream'}});
    setImportPending(true);
    task.run(async signal=>{try{return await request(signal);}catch(error){if(sequence!==uploadSequence.current)return null;throw error;}},result=>{
      if (sequence !== uploadSequence.current) return;
      if (!result?.uploadHash || typeof result?.proposedChanges?.text !== 'string') throw Object.assign(new Error('Invalid import acknowledgement'),{status:502});
      setUpload(result);setSections((result.sections || result.proposedChanges.sections).map(section=>({...section,included:section.included!==false})));
      setPreview(result);setImportState('');
    }).finally(()=>setImportPending(false));
  }
  function cancelImport() {
    uploadSequence.current++;
    setUpload(null);setPreview(null);setSections([]);setFile(null);setImportPending(false);setImportState('cancelledImport');
  }
  function revise() {
    const body={kind:'import',uploadPreviewId:upload.previewId,uploadHash:upload.uploadHash,sections:sections.map(({sectionId,title,start,end,included})=>({sectionId,title,start:Number(start),end:Number(end),included}))};
    const sequence=uploadSequence.current;
    task.run(frozenRequest(transport,'previews','POST',body),result=>{if(sequence===uploadSequence.current)setPreview(result);});
  }
  function confirmImport() {
    if (!previewUsable(preview)) return;
    const sequence=uploadSequence.current;
    setApplyingImport(true);
    task.run(frozenRequest(transport,`previews/${encodeURIComponent(preview.previewId)}/apply`,'POST',{
      expectedPreviewVersion:preview.version,selection:{actions:[{actionId:'import_document'}]}}),async (result,signal)=>{
      if(sequence!==uploadSequence.current)return;
      if(!result?.sourceRef||!result.docHash)throw Object.assign(new Error('Invalid import acknowledgement'),{status:502});
      setUpload(null);setPreview(null);setSections([]);setImportState('importDone');
      await reload?.();if(!signal.aborted)await onChanged?.(result);
    }).finally(()=>setApplyingImport(false));
  }
  function updateSection(index,key,value) {
    setSections(previous=>previous.map((section,at)=>at===index?{...section,[key]:value}:section));setPreview(null);task.clear();
  }
  function clearExport(){setHandle(null);setExportState('');setPrintHtml('');task.clear();}
  function prepareExport() {
    // Freeze user choices once per action, including retries after a lost ACK.
    const ref=structuredClone(sourceRef), keys=range==='selected'?[...selectedSceneKeys]:undefined;
    const include={summaries,bibleIds:bibleIds.split('\n').filter(Boolean)};
    let request;
    task.run(async signal=>{
      if(!request){
        if(JSON.stringify(ref)===JSON.stringify(resourceRef)&&ref.kind!=='version')await serverFlush(flush);
        const source=await readResource(transport,ref,signal);
        if(!source?.docHash)throw Object.assign(new Error('Missing source'),{status:422});
        request=frozenRequest(transport,'exports','POST',{sourceRef:ref,expectedHash:source.docHash,...(keys?{sceneKeys:keys}:{}),format,include});
      }
      return request(signal);
    },result=>{
      if(!result?.exportId||!Number.isFinite(expiryTime(result.expiresAt)))throw Object.assign(new Error('Invalid export acknowledgement'),{status:502});
      setHandle(result);setExportState('exportPrepared');setPrintHtml('');
    });
  }
  function content() {
    if(!handle||expiryTime(handle.expiresAt)<=Date.now())return;
    // Derive an authenticated relative route from an opaque ID; never navigate a public content URL.
    task.run(frozenRequest(transport,`exports/${encodeURIComponent(handle.exportId)}/content`,'GET',undefined,{responseType:handle.format==='print'?'text':'blob'}),result=>{
      if(handle.format==='print'){
        if(typeof result!=='string'||!result)throw Object.assign(new Error('Invalid print content'),{status:502});
        setPrintHtml(cleanPrintHtml(result));setExportState('printReady');}
      else {downloadBlob(result,handle.filename);setExportState('downloadStarted');}
    });
  }
  const fileValid=file&&/\.(txt|md|docx)$/i.test(file.name)&&file.size<=(/\.docx$/i.test(file.name)?8*1024*1024:2000000);
  const importAllowed=previewUsable(preview)&&preview.allowedActions?.some(action=>action.actionId==='import_document');
  return <div>
    <ToolsNotice task={task} t={t}/>
    <h3>{t('writing.tools.importPurpose')}</h3>
    <p className="writing-help">{t('writing.tools.importHelp')}</p>
    <label>{t('writing.tools.importPurpose')}<select disabled={task.busy||Boolean(upload)} value={purpose} onChange={event=>{setPurpose(event.target.value);task.clear();}}>{['idea','novel','script'].map(value=><option key={value} value={value}>{t(`writing.tools.${value}`)}</option>)}</select></label>
    <label>{t('writing.tools.importFile')}<input key={importState==='cancelledImport'?'cancelled':'file'} type="file" accept=".txt,.md,.docx" disabled={!writable||task.busy||Boolean(upload)} onChange={event=>{setFile(event.target.files[0]||null);setImportState('');task.clear();}}/></label>
    {file&&!fileValid&&<p role="alert">{t('writing.tools.invalid')}</p>}
    <button type="button" disabled={!writable||task.busy||!fileValid||Boolean(upload)} onClick={uploadFile}>{t('writing.tools.uploadPreview')}</button>
    {(upload||importPending)&&<button type="button" disabled={applyingImport} onClick={cancelImport}>{t('writing.tools.cancel')}</button>}
    {upload&&<section><p>{t('writing.tools.privatePreview')}</p>
      <h4>{t('writing.tools.warnings')}</h4>{upload.warnings?.map((warning,index)=><p key={index}>{typeof warning==='string'?warning:warning.message||warning.code}</p>)}
      <h4>{t('writing.tools.boundaries')}</h4><p className="writing-help">{t('writing.tools.boundaryHelp')}</p>
      <pre className="writing-change">{upload.proposedChanges.text}</pre>
      {sections.map((section,index)=><fieldset key={section.sectionId} disabled={task.busy}>
        <label>{t('writing.tools.sectionName')}<input value={section.title} onChange={event=>updateSection(index,'title',event.target.value)}/></label>
        <label>{t('writing.tools.sectionStart')}<input type="number" min="0" value={section.start} onChange={event=>updateSection(index,'start',event.target.value)}/></label>
        <label>{t('writing.tools.sectionEnd')}<input type="number" min="0" value={section.end} onChange={event=>updateSection(index,'end',event.target.value)}/></label>
        <label className="writing-check"><input type="checkbox" checked={section.included!==false} onChange={event=>updateSection(index,'included',event.target.checked)}/>{t('writing.tools.includeSection')}</label>
        <button type="button" onClick={()=>{setSections(value=>value.filter((_,at)=>at!==index));setPreview(null);task.clear();}}>{t('writing.tools.removeBoundary')}</button>
      </fieldset>)}
      <div className="writing-actions"><button type="button" disabled={task.busy||sections.length>=1000} onClick={()=>{setSections(value=>[...value,{sectionId:`sec_${actionId()}`,title:'',start:0,end:0,included:true}]);setPreview(null);task.clear();}}>{t('writing.tools.addBoundary')}</button>
      <button type="button" disabled={task.busy||!sections.length} onClick={revise}>{t('writing.tools.revisedPreview')}</button></div>
      {preview&&<><p>{t('writing.tools.previewExpiry',{time:expiryLabel(preview.expiresAt)})}</p>
        {!previewUsable(preview)&&<p role="alert">{t('writing.tools.stale')}</p>}
        {preview!==upload&&preview.warnings?.map((warning,index)=><p key={index}>{typeof warning==='string'?warning:warning.message||warning.code}</p>)}
        <button type="button" className="writing-primary" disabled={!writable||task.busy||!importAllowed} onClick={confirmImport}>{t('writing.tools.confirmImport')}</button></>}
    </section>}
    {importState&&<p role="status">{t(`writing.tools.${importState}`)}</p>}
    <hr/><h3>{t('writing.tools.createExport')}</h3>
    <p className="writing-help">{t('writing.tools.exportPrivacy')}</p>
    <fieldset disabled={task.busy}>
      <label>{t('writing.tools.resource')}<select value={JSON.stringify(sourceRef)} onChange={event=>{setSourceRef(JSON.parse(event.target.value));clearExport();}}>{options.map(option=><option key={JSON.stringify(option.ref)} value={JSON.stringify(option.ref)}>{t(`writing.tools.${option.key}`,{name:option.name})}</option>)}</select></label>
      {['versions','branches'].map(kind => catalog.workspace[kind].nextCursor && <button type="button" key={kind} onClick={() => task.run(signal => catalog.loadMore(kind,transport,signal))}>{t(kind==='versions'?'writing.tools.moreVersions':'writing.tools.moreBranches')}</button>)}
      <label>{t('writing.tools.sceneRange')}<select value={range} onChange={event=>{setRange(event.target.value);clearExport();}}><option value="whole">{t('writing.tools.wholeEpisode')}</option><option value="selected" disabled={!selectedSceneKeys.length}>{t('writing.tools.selectedScenes',{count:selectedSceneKeys.length})}</option></select></label>
      {range==='selected'&&<pre className="writing-resource">{selectedSceneKeys.join('\n')}</pre>}
      <label>{t('writing.tools.exportFormat')}<select value={format} onChange={event=>{setFormat(event.target.value);clearExport();}}>{['txt','md','docx','print'].map(value=><option key={value} value={value}>{value==='print'?t('writing.tools.print'):value.toUpperCase()}</option>)}</select></label>
      <label className="writing-check"><input type="checkbox" checked={summaries} onChange={event=>{setSummaries(event.target.checked);clearExport();}}/>{t('writing.tools.includeSummaries')}</label>
      <label>{t('writing.tools.includeBible')}<textarea value={bibleIds} onChange={event=>{setBibleIds(event.target.value);clearExport();}}/></label>
    </fieldset>
    <button type="button" disabled={task.busy||(range==='selected'&&!selectedSceneKeys.length)} onClick={prepareExport}>{t('writing.tools.createExport')}</button>
    {handle&&<section><p>{t('writing.tools.exportExpires',{time:expiryLabel(handle.expiresAt)})}</p><p>{handle.filename}</p>
      {handle.warnings?.map((warning,index)=><p key={index}>{typeof warning==='string'?warning:warning.message||warning.code}</p>)}
      <button type="button" disabled={task.busy||expiryTime(handle.expiresAt)<=Date.now()} onClick={content}>{t(handle.format==='print'?'writing.tools.openPrint':'writing.tools.download')}</button>
    </section>}
    {exportState&&<p role="status">{t(`writing.tools.${exportState}`)}</p>}
    {printHtml&&<section><iframe title={t('writing.tools.print')} sandbox="allow-same-origin allow-modals" ref={frame} srcDoc={printHtml}/>
      <div className="writing-actions"><button type="button" onClick={()=>{frame.current?.contentWindow?.focus();frame.current?.contentWindow?.print();setExportState('printRequested');}}>{t('writing.tools.printDialog')}</button>
      <button type="button" onClick={()=>setPrintHtml('')}>{t('writing.tools.closePrint')}</button></div>
    </section>}
  </div>;
}
