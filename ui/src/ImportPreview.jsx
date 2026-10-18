import { useEffect, useRef, useState } from 'react';
import { api } from './api.js';
import { SheetDialog } from './SheetDialog.jsx';
import { importPath, importPreviewPath } from './importModel.js';
import { columnName } from './sheetModel.js';
import './import-preview.css';

export function ImportPreview({slug,files,target=null,onClose,onImported,flush,onError}) {
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
        if(file.size>8*1024*1024)throw new Error("This file exceeds 8 MB. Split it into smaller files before importing.");
        if(!/\.(xlsx|docx|md|csv)$/i.test(file.name))throw new Error("Choose an XLSX, DOCX, Markdown, or CSV file.");
        if(frozenTarget&&queue.length!==1)throw new Error("Select one file at a time to update an existing page.");
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
      if(flush&&!(await flush())){setError("Save this page’s pending changes before importing.");submitted.current=false;return;}
      const result=await api.upload(importPath(slug,frozenTarget,{format:preview.format,worksheet:sheet?.name,headerRow:Number(headerRow),deliveryMode,confirmReplace:replaceConfirmed}),file,file.name);
      // Callback errors must not invite replaying an import that already succeeded.
      try{await onImported?.(result,file,frozenTarget);}catch(e){onError?.(`File imported, but the view could not refresh:${e.message}`);}
      advance();
    }catch(e){setError(e.message);submitted.current=false;onError?.(e.message);}finally{setSaving(false);}
  };
  return <SheetDialog title={frozenTarget?"Review Page Update":"Import Preview"} wide onClose={close}><div className="import-preview">
    <div className="import-file-heading"><div><strong>{file?.name||"No File Selected"}</strong><small>{file?`${(file.size/1024).toFixed(1)} KB`:''}{queue.length>1?` · attempt ${index+1}／${queue.length}  files at a time`:''}</small></div><span>{frozenTarget?`Update “${frozenTarget.title}” · revision ${frozenTarget.revision}`:"Create New Page"}</span></div>
    {loading&&<p role="status">Loading file preview…</p>}
    {error&&<div className="import-error" role="alert"><p>{error}</p>{!preview&&<button disabled={loading} onClick={()=>setAttempt(old=>old+1)}>Reload Preview</button>}</div>}
    {preview&&<>
      {!!preview.worksheets?.length&&<><div className="import-preview-controls">{preview.worksheets.length>1&&<label>Preview Worksheet<select aria-label={"Preview Worksheet"} disabled={saving} value={sheetIndex} onChange={e=>updateOptions(()=>{const next=Number(e.target.value);setSheetIndex(next);setWorksheet(preview.worksheets[next]?.name||" ".trim());setHeaderRow(1);})}>{preview.worksheets.map((s,i)=><option key={i} value={i}>{s.name||`Table ${i+1}`}</option>)}</select></label>}{tableFile&&<label>Header Row<input type="number" aria-label={"Header Row Number"} min={1} max={Math.max(1,sheet?.row_count||1)} value={headerRow} disabled={saving} onChange={e=>updateOptions(()=>setHeaderRow(e.target.value))}/></label>}<small>{sheet?.row_count||0} rows ×  {sheet?.column_count||0} columns · first 20 rows shown</small></div>
        <div className="import-preview-grid"><table><thead><tr><th>#</th>{Array.from({length:sheet?.column_count||0},(_,c)=><th key={c}>{columnName(c)}</th>)}</tr></thead><tbody>{(sheet?.rows||[]).map((cells,r)=><tr key={r} className={tableFile?(r+1===Number(headerRow)?'import-header-row':r+1<Number(headerRow)?'import-prefix-row':''):''}><th><button disabled={!tableFile||saving} title={tableFile?"Use as Header":undefined} onClick={()=>updateOptions(()=>setHeaderRow(r+1))}>{r+1}{r+1===Number(headerRow)&&tableFile?"Header":''}</button></th>{Array.from({length:sheet?.column_count||0},(_,c)=><td key={c}>{String(cells[c]??'')}</td>)}</tr>)}</tbody></table></div>
        {Number(headerRow)>20&&<p className="import-note">The selected header is outside the 20-row preview. Check the source file.</p>}
        {preview.format==='xlsx'&&<p className="import-note">All worksheets will be imported. This header setting applies to “{sheet?.name}”; other worksheets use row 1. Rows before the header are excluded from the editable table.</p>}
      </>}
      {!preview.worksheets?.length&&<p className="import-document-note">The file can be read. Confirm to create an editable document and retain the original file.</p>}
      {preview.format==='xlsx'&&<fieldset className="import-delivery"><legend>Delivery Format</legend><label><input type="radio" name="delivery" value="original_patch" checked={deliveryMode==='original_patch'} disabled={saving} onChange={()=>updateOptions(()=>setDeliveryMode('original_patch'))}/><span><b>Preserve Source Workbook Format</b><small>Edit existing content. Changing headers, rows, or columns requires a delivery format decision.</small></span></label><label><input type="radio" name="delivery" value="new_workbook" checked={deliveryMode==='new_workbook'} disabled={saving} onChange={()=>updateOptions(()=>setDeliveryMode('new_workbook'))}/><span><b>Save as a New Workbook</b><small>Restructure the data in a new workbook. Original formatting, merged cells, and special objects may not be retained.</small></span></label></fieldset>}
      {(preview.warnings||[]).map((warning,i)=><p className="import-note" key={i}>{warning}</p>)}
      {frozenTarget&&preview.replacement&&<section className="import-replacement"><h3>File Replacement Changes</h3><p>Add {preview.replacement.summary.added} · removed {preview.replacement.summary.removed} · changed {preview.replacement.summary.changed} · unchanged {preview.replacement.summary.unchanged}</p><div className="import-preview-grid"><table><thead><tr><th>Location</th><th>Current Content</th><th>After Import</th></tr></thead><tbody>{preview.replacement.changes.map((change,i)=><tr key={i}><th>{change.label||change.row_id||change.kind}{change.column?` · ${change.column}`:""}</th><td>{change.before??"—"}</td><td>{change.after??"—"}{change.value_truncated?"(content truncated)":""}</td></tr>)}</tbody></table></div>{preview.replacement.truncated&&<p className="import-note">Showing the first 50 of {preview.replacement.change_count}  changes.</p>}{preview.replacement.ambiguities?.map((item,i)=><p className="import-error" key={i}>{item.message||"Duplicate rows cannot be matched reliably. Existing annotations remain available for reattachment."}</p>)}<label className="import-replace-check"><input type="checkbox" checked={replaceConfirmed} disabled={loading||previewKey!==currentKey||saving} onChange={e=>setReplaceConfirmed(e.target.checked)}/>Replace Current Content with This File</label></section>}{frozenTarget&&<p className="import-note">Confirm to create a revision and reattach annotations. If the page changes, the update stops and retains the file for retry.</p>}
    </>}
    <div className="sheet-dialog-actions"><button disabled={saving} onClick={close}>{index?"Finish Import":"Cancel"}</button>{queue.length>1&&<button disabled={saving} onClick={advance}>Skip File</button>}<span className="spacer"/><button className="primary" disabled={loading||saving||!!error||!preview||previewKey!==currentKey||!validHeader||(!!frozenTarget&&(!preview.replacement||!replaceConfirmed))} onClick={confirm}>{saving?"Importing…":frozenTarget?"Update This Page":queue.length>1&&index<queue.length-1?"Import and Continue":"Import File"}</button></div>
  </div></SheetDialog>;
}
