import { useLocale } from './i18n/react.jsx';
import { t as uiText } from './i18n/index.js';
import { useEffect, useRef, useState } from 'react';
import { api } from './api.js';
import { SheetDialog } from './SheetDialog.jsx';
import { importPath, importPreviewPath } from './importModel.js';
import { columnName } from './sheetModel.js';
import './import-preview.css';

export function ImportPreview({slug,files,target=null,onClose,onImported,flush,onError}) {
  const locale = useLocale();
  const [queue]=useState(()=>[...files]),[frozenTarget]=useState(()=>target?{...target}:null);
  const [index,setIndex]=useState(0),[preview,setPreview]=useState(null),[loading,setLoading]=useState(true),[saving,setSaving]=useState(false),[error,setError]=useState('');
  const [sheetIndex,setSheetIndex]=useState(0),[headerRow,setHeaderRow]=useState(1),[deliveryMode,setDeliveryMode]=useState('original_patch'),[attempt,setAttempt]=useState(0);
  const [worksheet,setWorksheet]=useState(''),[replaceConfirmed,setReplaceConfirmed]=useState(false),[previewKey,setPreviewKey]=useState('');
  const submitted=useRef(false),file=queue[index];
  const format=file?.name.split('.').at(-1)?.toLowerCase();
  const currentKey=JSON.stringify([index,headerRow,worksheet,deliveryMode,attempt]);
  const updateOptions=fn=>{setReplaceConfirmed(false);setLoading(true);setAttempt(old=>old+1);fn();};
  useEffect(()=>{setSheetIndex(0);setHeaderRow(1);setWorksheet('');setDeliveryMode('original_patch');setReplaceConfirmed(false);},[file]);
  useEffect(()=>{
    if(!file)return;let alive=true;
    setLoading(true);setError('');setReplaceConfirmed(false);submitted.current=false;
    const read=async()=>{
      try{
        if(file.size>8*1024*1024)throw new Error(uiText("importPreview.thisFileExceedsMBSplitItIntoSmallerFiles"));
        if(!/\.(xlsx|docx|md|csv)$/i.test(file.name))throw new Error(uiText("importPreview.chooseAnXLSXDOCXMarkdownOrCSVFile"));
        if(frozenTarget&&queue.length!==1)throw new Error(uiText("importPreview.selectOneFileAtATimeToUpdateAn"));
        const result=await api.upload(importPreviewPath(slug,frozenTarget,{format,worksheet,headerRow:Number(headerRow),deliveryMode}),file,file.name);
        if(alive){setPreview(result);setPreviewKey(currentKey);if(format==='xlsx'&&!worksheet&&result.worksheets?.[sheetIndex]?.name)setWorksheet(result.worksheets[sheetIndex].name);}
      }catch(e){if(alive)setError(e.message);}finally{if(alive)setLoading(false);}
    };read();return()=>{alive=false;};
  },[file,slug,attempt,frozenTarget,queue.length,headerRow,worksheet,deliveryMode,format,currentKey,sheetIndex]);
  const sheet=preview?.worksheets?.[sheetIndex];
  const tableFile=['xlsx','csv'].includes(preview?.format);
  const validHeader=!tableFile||(Number.isInteger(Number(headerRow))&&headerRow>=1&&headerRow<=Math.max(1,sheet?.row_count||1));
  const close=()=>{if(!saving)onClose();};
  const advance=()=>{if(index+1<queue.length)setIndex(old=>old+1);else onClose();};
  const confirm=async()=>{
    if(submitted.current||saving||loading||!preview||previewKey!==currentKey||!validHeader||(frozenTarget&&(!preview.replacement||!replaceConfirmed)))return;
    submitted.current=true;setSaving(true);setError('');
    try{
      if(flush&&!(await flush())){setError(uiText("importPreview.saveThisPageSPendingChangesBeforeImporting"));submitted.current=false;return;}
      const result=await api.upload(importPath(slug,frozenTarget,{format:preview.format,worksheet:sheet?.name,headerRow:Number(headerRow),deliveryMode,confirmReplace:replaceConfirmed}),file,file.name);
      // Callback errors must not invite replaying an import that already succeeded.
      try{await onImported?.(result,file,frozenTarget);}catch(e){onError?.(uiText("importPreview.fileImportedButTheViewCouldNotRefresh", {v0: (e.message)}));}
      advance();
    }catch(e){setError(e.message);submitted.current=false;onError?.(e.message);}finally{setSaving(false);}
  };
  return <SheetDialog title={frozenTarget?uiText("importPreview.reviewPageUpdate"):uiText("importPreview.importPreview")} wide onClose={close}><div className="import-preview">
    <div className="import-file-heading"><div><strong>{file?.name||uiText("importPreview.noFileSelected")}</strong><small>{file?uiText("importPreview.kB", {v0: ((file.size/1024).toFixed(1))}):''}{queue.length>1?uiText("importPreview.queuePosition", {v0: (index+1), v1: (queue.length)}):''}</small></div><span>{frozenTarget?uiText("importPreview.updateRevision", {v0: (frozenTarget.title), v1: (frozenTarget.revision)}):uiText("importPreview.createNewPage")}</span></div>
    {loading&&<p role="status">{uiText("importPreview.loadingFilePreview")}</p>}
    {error&&<div className="import-error" role="alert"><p>{error}</p>{!preview&&<button disabled={loading} onClick={()=>setAttempt(old=>old+1)}>{uiText("importPreview.reloadPreview")}</button>}</div>}
    {preview&&<>
      {!!preview.worksheets?.length&&<><div className="import-preview-controls">{preview.worksheets.length>1&&<label>{uiText("importPreview.previewWorksheet")}<select aria-label={uiText("importPreview.previewWorksheet")} disabled={saving} value={sheetIndex} onChange={e=>updateOptions(()=>{const next=Number(e.target.value);setSheetIndex(next);setWorksheet(preview.worksheets[next]?.name||" ".trim());setHeaderRow(1);})}>{preview.worksheets.map((s,i)=><option key={i} value={i}>{s.name||uiText("importPreview.table", {v0: (i+1)})}</option>)}</select></label>}{tableFile&&<label>{uiText("importPreview.headerRow")}<input type="number" aria-label={uiText("importPreview.headerRowNumber")} min={1} max={Math.max(1,sheet?.row_count||1)} value={headerRow} disabled={saving} onChange={e=>updateOptions(()=>setHeaderRow(e.target.value))}/></label>}<small>{uiText("importPreview.rowsColumnsFirstRowsShown", {v0: (sheet?.row_count||0), v1: (sheet?.column_count||0)})}</small></div>
        <div className="import-preview-grid"><table><thead><tr><th>#</th>{Array.from({length:sheet?.column_count||0},(_,c)=><th key={c}>{columnName(c)}</th>)}</tr></thead><tbody>{(sheet?.rows||[]).map((cells,r)=><tr key={r} className={tableFile?(r+1===Number(headerRow)?'import-header-row':r+1<Number(headerRow)?'import-prefix-row':''):''}><th><button disabled={!tableFile||saving} title={tableFile?uiText("importPreview.useAsHeader"):undefined} onClick={()=>updateOptions(()=>setHeaderRow(r+1))}>{r+1}{r+1===Number(headerRow)&&tableFile?uiText("importPreview.header"):''}</button></th>{Array.from({length:sheet?.column_count||0},(_,c)=><td key={c}>{String(cells[c]??'')}</td>)}</tr>)}</tbody></table></div>
        {Number(headerRow)>20&&<p className="import-note">{uiText("importPreview.theSelectedHeaderIsOutsideTheRowPreviewCheck")}</p>}
        {preview.format==='xlsx'&&<p className="import-note">{uiText("importPreview.allWorksheetsWillBeImportedThisHeaderSettingApplies", {v0: (sheet?.name)})}</p>}
      </>}
      {!preview.worksheets?.length&&<p className="import-document-note">{uiText("importPreview.theFileCanBeReadConfirmToCreateAn")}</p>}
      {preview.format==='xlsx'&&<fieldset className="import-delivery"><legend>{uiText("importPreview.deliveryFormat")}</legend><label><input type="radio" name="delivery" value="original_patch" checked={deliveryMode==='original_patch'} disabled={saving} onChange={()=>updateOptions(()=>setDeliveryMode('original_patch'))}/><span><b>{uiText("importPreview.preserveSourceWorkbookFormat")}</b><small>{uiText("importPreview.editExistingContentChangingHeadersRowsOrColumnsRequires")}</small></span></label><label><input type="radio" name="delivery" value="new_workbook" checked={deliveryMode==='new_workbook'} disabled={saving} onChange={()=>updateOptions(()=>setDeliveryMode('new_workbook'))}/><span><b>{uiText("importPreview.saveAsANewWorkbook")}</b><small>{uiText("importPreview.restructureTheDataInANewWorkbookOriginalFormatting")}</small></span></label></fieldset>}
      {(preview.warnings||[]).map((warning,i)=><p className="import-note" key={i}>{warning}</p>)}
      {frozenTarget&&preview.replacement&&<section className="import-replacement"><h3>{uiText("importPreview.fileReplacementChanges")}</h3><p>{uiText("importPreview.addRemovedChangedUnchanged", {v0: (preview.replacement.summary.added), v1: (preview.replacement.summary.removed), v2: (preview.replacement.summary.changed), v3: (preview.replacement.summary.unchanged)})}</p><div className="import-preview-grid"><table><thead><tr><th>{uiText("importPreview.location")}</th><th>{uiText("importPreview.currentContent")}</th><th>{uiText("importPreview.afterImport")}</th></tr></thead><tbody>{preview.replacement.changes.map((change,i)=><tr key={i}><th>{change.label||change.row_id||change.kind}{change.column?` · ${change.column}`:""}</th><td>{change.before??"—"}</td><td>{change.after??"—"}{change.value_truncated?uiText("importPreview.contentTruncated"):""}</td></tr>)}</tbody></table></div>{preview.replacement.truncated&&<p className="import-note">{uiText("importPreview.showingTheFirstOfChanges", {v0: (preview.replacement.change_count)})}</p>}{preview.replacement.ambiguities?.map((item,i)=><p className="import-error" key={i}>{item.message||uiText("importPreview.duplicateRowsCannotBeMatchedReliablyExistingAnnotationsRemain")}</p>)}<label className="import-replace-check"><input type="checkbox" checked={replaceConfirmed} disabled={loading||previewKey!==currentKey||saving} onChange={e=>setReplaceConfirmed(e.target.checked)}/>{uiText("importPreview.replaceCurrentContentWithThisFile")}</label></section>}{frozenTarget&&<p className="import-note">{uiText("importPreview.confirmToCreateARevisionAndReattachAnnotationsIf")}</p>}
    </>}
    <div className="sheet-dialog-actions"><button disabled={saving} onClick={close}>{index?uiText("importPreview.finishImport"):uiText("importPreview.cancel")}</button>{queue.length>1&&<button disabled={saving} onClick={advance}>{uiText("importPreview.skipFile")}</button>}<span className="spacer"/><button className="primary" disabled={loading||saving||!!error||!preview||previewKey!==currentKey||!validHeader||(!!frozenTarget&&(!preview.replacement||!replaceConfirmed))} onClick={confirm}>{saving?uiText("importPreview.importing"):frozenTarget?uiText("importPreview.updateThisPage"):queue.length>1&&index<queue.length-1?uiText("importPreview.importAndContinue"):uiText("importPreview.importFile")}</button></div>
  </div></SheetDialog>;
}
