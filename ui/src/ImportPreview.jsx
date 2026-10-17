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
        if(file.size>8*1024*1024)throw new Error('檔案超過 8 MB，請分成較小的檔案再匯入');
        if(!/\.(xlsx|docx|md|csv)$/i.test(file.name))throw new Error('請選擇 XLSX、DOCX、Markdown 或 CSV 檔案');
        if(frozenTarget&&queue.length!==1)throw new Error('更新既有分頁時，請一次選擇一個檔案');
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
      if(flush&&!(await flush())){setError('目前分頁尚有未儲存的內容，請先完成儲存再匯入');submitted.current=false;return;}
      const result=await api.upload(importPath(slug,frozenTarget,{format:preview.format,worksheet:sheet?.name,headerRow:Number(headerRow),deliveryMode,confirmReplace:replaceConfirmed}),file,file.name);
      // Callback errors must not invite replaying an import that already succeeded.
      try{await onImported?.(result,file,frozenTarget);}catch(e){onError?.(`檔案已匯入，畫面更新失敗：${e.message}`);}
      advance();
    }catch(e){setError(e.message);submitted.current=false;onError?.(e.message);}finally{setSaving(false);}
  };
  return <SheetDialog title={frozenTarget?'核對更新分頁':'匯入前預覽'} wide onClose={close}><div className="import-preview">
    <div className="import-file-heading"><div><strong>{file?.name||'沒有選取檔案'}</strong><small>{file?`${(file.size/1024).toFixed(1)} KB`:''}{queue.length>1?` · 第 ${index+1}／${queue.length} 個檔案`:''}</small></div><span>{frozenTarget?`更新「${frozenTarget.title}」 · 版本 ${frozenTarget.revision}`:'建立新分頁'}</span></div>
    {loading&&<p role="status">正在讀取檔案預覽…</p>}
    {error&&<div className="import-error" role="alert"><p>{error}</p>{!preview&&<button disabled={loading} onClick={()=>setAttempt(old=>old+1)}>重新讀取預覽</button>}</div>}
    {preview&&<>
      {!!preview.worksheets?.length&&<><div className="import-preview-controls">{preview.worksheets.length>1&&<label>預覽工作表<select aria-label="預覽工作表" disabled={saving} value={sheetIndex} onChange={e=>updateOptions(()=>{const next=Number(e.target.value);setSheetIndex(next);setWorksheet(preview.worksheets[next]?.name||" ".trim());setHeaderRow(1);})}>{preview.worksheets.map((s,i)=><option key={i} value={i}>{s.name||`表格 ${i+1}`}</option>)}</select></label>}{tableFile&&<label>表頭在第幾列<input type="number" aria-label="表頭列號" min={1} max={Math.max(1,sheet?.row_count||1)} value={headerRow} disabled={saving} onChange={e=>updateOptions(()=>setHeaderRow(e.target.value))}/></label>}<small>{sheet?.row_count||0} 列 × {sheet?.column_count||0} 欄 · 預覽前 20 列</small></div>
        <div className="import-preview-grid"><table><thead><tr><th>#</th>{Array.from({length:sheet?.column_count||0},(_,c)=><th key={c}>{columnName(c)}</th>)}</tr></thead><tbody>{(sheet?.rows||[]).map((cells,r)=><tr key={r} className={tableFile?(r+1===Number(headerRow)?'import-header-row':r+1<Number(headerRow)?'import-prefix-row':''):''}><th><button disabled={!tableFile||saving} title={tableFile?'設為表頭':undefined} onClick={()=>updateOptions(()=>setHeaderRow(r+1))}>{r+1}{r+1===Number(headerRow)&&tableFile?' 表頭':''}</button></th>{Array.from({length:sheet?.column_count||0},(_,c)=><td key={c}>{String(cells[c]??'')}</td>)}</tr>)}</tbody></table></div>
        {Number(headerRow)>20&&<p className="import-note">選定的表頭超出前 20 列預覽，請先確認來源檔案。</p>}
        {preview.format==='xlsx'&&<p className="import-note">所有工作表都會匯入；這次表頭設定套用「{sheet?.name}」，其他工作表使用第 1 列。表頭以前的資料不進入工作台表格。</p>}
      </>}
      {!preview.worksheets?.length&&<p className="import-document-note">檔案可讀取，確認後建立可編輯文件；來源原檔會一併保留。</p>}
      {preview.format==='xlsx'&&<fieldset className="import-delivery"><legend>預期怎麼交付</legend><label><input type="radio" name="delivery" value="original_patch" checked={deliveryMode==='original_patch'} disabled={saving} onChange={()=>updateOptions(()=>setDeliveryMode('original_patch'))}/><span><b>保留來源工作簿格式</b><small>編輯既有內容；改變表頭或列欄結構前，另外確認交付方式。</small></span></label><label><input type="radio" name="delivery" value="new_workbook" checked={deliveryMode==='new_workbook'} disabled={saving} onChange={()=>updateOptions(()=>setDeliveryMode('new_workbook'))}/><span><b>整理後另存新工作簿</b><small>可調整資料結構；新檔不保證原本的格式、合併格及特殊物件。</small></span></label></fieldset>}
      {(preview.warnings||[]).map((warning,i)=><p className="import-note" key={i}>{warning}</p>)}
      {frozenTarget&&preview.replacement&&<section className="import-replacement"><h3>整份檔案取代前後差異</h3><p>新增 {preview.replacement.summary.added} · 移除 {preview.replacement.summary.removed} · 修改 {preview.replacement.summary.changed} · 未變 {preview.replacement.summary.unchanged}</p><div className="import-preview-grid"><table><thead><tr><th>位置</th><th>目前內容</th><th>匯入後</th></tr></thead><tbody>{preview.replacement.changes.map((change,i)=><tr key={i}><th>{change.label||change.row_id||change.kind}{change.column?` · ${change.column}`:""}</th><td>{change.before??"—"}</td><td>{change.after??"—"}{change.value_truncated?"（內容截短）":""}</td></tr>)}</tbody></table></div>{preview.replacement.truncated&&<p className="import-note">預覽顯示前 50 項，共 {preview.replacement.change_count} 項差異。</p>}{preview.replacement.ambiguities?.map((item,i)=><p className="import-error" key={i}>{item.message||"重複列無法確定對位；舊標註保留為待重新對位。"}</p>)}<label className="import-replace-check"><input type="checkbox" checked={replaceConfirmed} disabled={loading||previewKey!==currentKey||saving} onChange={e=>setReplaceConfirmed(e.target.checked)}/>以這份檔案取代目前內容</label></section>}{frozenTarget&&<p className="import-note">確認後會建立新版本、重新對位標註；如果分頁已被修改，這次更新會停止並保留檔案供重試。</p>}
    </>}
    <div className="sheet-dialog-actions"><button disabled={saving} onClick={close}>{index?'結束匯入':'取消'}</button>{queue.length>1&&<button disabled={saving} onClick={advance}>略過這個檔案</button>}<span className="spacer"/><button className="primary" disabled={loading||saving||!!error||!preview||previewKey!==currentKey||!validHeader||(!!frozenTarget&&(!preview.replacement||!replaceConfirmed))} onClick={confirm}>{saving?'匯入中…':frozenTarget?'確認更新這個分頁':queue.length>1&&index<queue.length-1?'確認匯入，繼續下一個':'確認匯入'}</button></div>
  </div></SheetDialog>;
}
