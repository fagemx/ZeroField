import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from './api.js';
import { columnName, evaluate, mediaOf, parseTSV, tableEditPayload, tableCSV, tablesOf } from './sheetModel.js';
import { MediaCell } from './MediaCell.jsx';
import { SheetDialog } from './SheetDialog.jsx';
import { SheetCards } from './SheetCards.jsx';
import { SheetReview } from './SheetReview.jsx';
import { freezeSheetScope, historyForRow, inverseOperation, rangeTSV, rebaseOperation, selectionRange, sheetRequest, visiblePastePayload } from './sheetInteraction.js';
import { restoreViewPreferences, sheetViewModel, statusOptions, viewPreferences } from './sheetViews.js';
import { shortTime } from './format.js';
import './sheet-workspace.css';

const TYPES = {text:'文字',number:'數值',formula:'公式',image:'圖片',video:'影片附件',audio:'音訊',status:'狀態'};

export function SheetSurface({slug,tab,tabs=[],me,values,annotations=[],locks=[],controlRef,onReloadTab,onAskAgent,onSwitchDocMode,onToast,onError,onPanelChange,assistantOpen,focusRow}) {
  const tables = useMemo(()=>tablesOf(tab.doc,values),[tab.doc,values]);
  const [tableId,setTableId]=useState(null);
  const parsed=tables.find(t=>t.tableId===tableId)||tables[0];
  const [active,setActive]=useState({r:0,c:0}),[anchor,setAnchor]=useState({r:0,c:0});
  const [selected,setSelected]=useState(new Set()),[query,setQuery]=useState(''),[statusFilter,setStatusFilter]=useState('');
  const [sort,setSort]=useState(null),[hidden,setHidden]=useState([]),[widths,setWidths]=useState({});
  const [localPreference,setLocalPreference]=useState(null);
  const [editing,setEditing]=useState(null),[text,setText]=useState(''),[busy,setBusy]=useState(false),[saveState,setSaveState]=useState('已儲存');
  const [failure,setFailure]=useState(null),[undo,setUndo]=useState([]),[redo,setRedo]=useState([]),[pendingPaste,setPendingPaste]=useState(null);
  const [panel,setPanel]=useState(null),[rowOpen,setRowOpen]=useState(null),[preview,setPreview]=useState(null),[history,setHistory]=useState(null);
  const [comment,setComment]=useState(''),[request,setRequest]=useState(null),[instruction,setInstruction]=useState('');
  const [columnDraft,setColumnDraft]=useState(null),[schemaPlan,setSchemaPlan]=useState(null),[newWorkbook,setNewWorkbook]=useState(false),[workflow,setWorkflow]=useState('');
  const [taskError,setTaskError]=useState('');
  const grid=useRef(null),editor=useRef(null),dragging=useRef(false),composing=useRef(false),busyRef=useRef(false),upload=useRef(null),uploadTarget=useRef(null);
  const reload=useRef(onReloadTab),outputs=useRef(null);
  const handledFocus=useRef(null);
  reload.current=onReloadTab;
  const writable=me?.can_write!==false;
  const dirty=!!editing && text!==editing.value;
  const preferenceKey=`openbench-sheet-view:${slug}:${tab.key}:${parsed?.tableId||''}`;
  const storedPreference=useMemo(()=>{try{return localStorage.getItem(preferenceKey);}catch{return null;}},[preferenceKey]);
  useEffect(()=>{
    setSelected(new Set());setActive({r:0,c:0});setAnchor({r:0,c:0});setQuery('');setStatusFilter('');setSort(null);setHidden([]);setWidths({});setUndo([]);setRedo([]);setPanel(null);setPreview(null);setFailure(null);setSaveState('已儲存');
  },[parsed?.tableId]);
  useEffect(()=>{setHidden([]);setSort(null);setWidths({});setColumnDraft(null);},[JSON.stringify(parsed?.table.attrs.column_ids||[])]);
  useEffect(()=>{onPanelChange?.(!!panel||!!preview||!!request);},[panel,preview,request,onPanelChange]);
  useEffect(()=>{if(assistantOpen){setPanel(null);setPreview(null);setRequest(null);}},[assistantOpen]);
  useEffect(()=>{
    if(!focusRow||focusRow.tabKey!==tab.key||dirty||busy)return;
    const token=JSON.stringify(focusRow);if(handledFocus.current===token)return;
    const target=tables.find(t=>t.tableId===focusRow.tableId);
    if(!target){handledFocus.current=token;onError?.('工作流來源工作表已不存在；沒有改選其他工作表');return;}
    if(parsed?.tableId!==target.tableId){setTableId(target.tableId);return;}
    const r=target.rows.findIndex(row=>row.rid===focusRow.rowId),c=Number(focusRow.colIndex??0);
    if(r<0||!Number.isInteger(c)||c<0||c>=target.headers.length){handledFocus.current=token;onError?.('工作流來源列或欄位已不存在；請在執行結果核對來源');return;}
    handledFocus.current=token;setQuery('');setStatusFilter('');setHidden(old=>old.filter(index=>index!==c));setPanel(null);setPreview(null);
    const prior=restoreViewPreferences(localPreference?.key===preferenceKey?localPreference.raw:storedPreference,target);
    setLocalPreference({key:preferenceKey,raw:JSON.stringify(viewPreferences(target,{...prior,mode:'grid'}))});setActive({r,c});setAnchor({r,c});
    requestAnimationFrame(()=>{const cell=grid.current?.querySelector(`[data-cell="${r}:${c}"]`);cell?.focus();cell?.scrollIntoView({block:'nearest',inline:'nearest'});});
  },[focusRow,tab.key,tables,parsed?.tableId,dirty,busy,preferenceKey,storedPreference,localPreference,onError]);
  useEffect(()=>{
    const stop=()=>{dragging.current=false;};window.addEventListener('mouseup',stop);
    return()=>window.removeEventListener('mouseup',stop);
  },[]);
  useEffect(()=>{
    if(!controlRef)return;
    const control={flush:async()=>{
      if(dirty||busy||pendingPaste){onError?.(busy?'請等儲存完成後再切換分頁':'草稿尚未提交，請先儲存或取消這次編輯');return false;}return true;
    }};controlRef.current=control;
    return()=>{if(controlRef.current===control)controlRef.current=null;};
  },[controlRef,dirty,busy,pendingPaste,onError]);
  useEffect(()=>{
    if(!dirty&&!pendingPaste)return;
    const protect=e=>{e.preventDefault();e.returnValue='';};window.addEventListener('beforeunload',protect);
    return()=>window.removeEventListener('beforeunload',protect);
  },[dirty,pendingPaste]);
  useEffect(()=>{
    if(!editing)return;
    editor.current?.focus();if(editing.selectAll)editor.current?.select();
  },[editing]);
  useEffect(()=>{
    let alive=true,timer;
    const poll=async()=>{
      try {const data=await api.get(`/projects/api/${slug}/tasks?target_tab=${encodeURIComponent(tab.key)}`);
        if(alive){const next=(data.tasks||[]).filter(t=>t.status==='succeeded').map(t=>`${t.id}:${t.updated_at}`).sort().join('|');
          if(outputs.current!==null&&outputs.current!==next)await reload.current?.();outputs.current=next;setTaskError('');}
      }catch(e){if(alive)setTaskError(e.message);}if(alive)timer=setTimeout(poll,5000);
    };poll();return()=>{alive=false;clearTimeout(timer);};
  },[slug,tab.key]);

  if(!parsed)return <div className="canvas sheet-empty"><h2>{tab.title}</h2><p>加入一張表格，開始整理資料。</p><button onClick={onSwitchDocMode}>編輯這個分頁</button></div>;
  const attrs=parsed.table.attrs,types=attrs.column_types||[],columnIds=attrs.column_ids||[];
  const preferences=restoreViewPreferences(localPreference?.key===preferenceKey?localPreference.raw:storedPreference,parsed);
  const visibleColumns=parsed.headers.map((_,i)=>i).filter(c=>!hidden.includes(c));
  const isStatus=c=>types[c]==='status'||parsed.rows.some(row=>row.cells[c]?.kind==='status');
  const columnWidth=c=>widths[c]||attrs.column_widths?.[columnIds[c]]||(['number','formula'].includes(types[c])?110:isStatus(c)?120:/(日期|date)/i.test(parsed.headers[c])?120:/(備註|說明|prompt|內容)/i.test(parsed.headers[c])?210:160);
  const statusValues=[...new Set(parsed.rows.flatMap(row=>row.cells.flatMap((cell,c)=>isStatus(c)&&cell.value?[cell.value]:[])))];
  const visibleRows=parsed.rows.filter(row=>(!statusFilter||row.cells.some((cell,c)=>isStatus(c)&&cell.value===statusFilter))&&(!query||row.cells.some(cell=>String(cell.value).toLocaleLowerCase().includes(query.toLocaleLowerCase()))));
  if(sort)visibleRows.sort((a,b)=>String(a.cells[sort.c]?.value??'').localeCompare(String(b.cells[sort.c]?.value??''),'zh-Hant',{numeric:true})*(sort.direction==='desc'?-1:1));
  const rowIndices=visibleRows.map(row=>parsed.rows.indexOf(row)),visibleIds=visibleRows.map(row=>row.rid);
  const range=selectionRange(anchor,active,rowIndices,visibleColumns);
  const view=sheetViewModel(parsed,visibleRows,preferences),mode=preferences.mode;
  const flows=tabs.filter(t=>t.surface_type==='flow');
  const row=parsed.rows.find(r=>r.rid===rowOpen),previewRow=preview?.r==null?null:parsed.rows[preview.r];
  const contextRow=previewRow||row;
  const previewTargetValid=!!previewRow&&Number.isInteger(preview?.c)&&preview.c>=0&&preview.c<parsed.headers.length;
  const messages=annotations.filter(a=>a.tab_key===tab.key&&a.anchor?.rid===contextRow?.rid).flatMap(a=>a.messages||[]);
  const imported=!!attrs.worksheet_name;
  const activeCell=parsed.rows[active.r]?.cells[active.c];
  const safeFocus={r:rowIndices.includes(active.r)?active.r:rowIndices[0],c:visibleColumns.includes(active.c)?active.c:visibleColumns[0]};
  const setView=change=>{const raw=JSON.stringify(viewPreferences(parsed,{...preferences,...change}));setLocalPreference({key:preferenceKey,raw});try{localStorage.setItem(preferenceKey,raw);}catch{/* optional view preference */}};
  const guardDraft=()=>{if(dirty||busy||pendingPaste){onError?.(busy?'請等儲存完成':'請先儲存或取消目前草稿，再切換、匯出或修改欄位');return false;}return true;};
  const switchDocument=()=>{if(guardDraft())onSwitchDocMode?.();};
  const downloadWorkbook=mode=>{if(guardDraft())run(()=>api.download(`/projects/api/${slug}/tabs/${tab.key}/export?format=xlsx${mode==='new_workbook'?'&mode=new_workbook':''}`,`${tab.title}${mode==='new_workbook'?'-整理版':''}.xlsx`));};
  const closeSchema=()=>{if(busy)return;setSchemaPlan(null);setFailure(null);setSaveState('已儲存');};
  const closePaste=()=>{if(busy)return;setPendingPaste(null);setFailure(null);setSaveState('已儲存');};
  const focus=cell=>{setActive(cell);setAnchor(cell);requestAnimationFrame(()=>grid.current?.querySelector(`[data-cell="${cell.r}:${cell.c}"]`)?.focus());};
  const closePanel=()=>{setPanel(null);setPreview(null);setHistory(null);focus(active);};
  const fail=(error,retry=null)=>{setFailure({message:error.message,details:error.data,retry});setSaveState('未儲存');onError?.(error.message);};
  const run=async fn=>{
    if(busyRef.current)return false;busyRef.current=true;setBusy(true);
    try{await fn();return true;}catch(e){fail(e);return false;}finally{busyRef.current=false;setBusy(false);}
  };
  const refresh=async()=>{try{await onReloadTab();}catch(e){setFailure({message:`已寫入，但畫面尚未更新：${e.message}`,retry:onReloadTab});}};
  const submit=async(payload,{record=true}={})=>{
    if(busyRef.current)return false;busyRef.current=true;setBusy(true);setSaveState('儲存中…');setFailure(null);
    try{
      const result=await api.post(`/projects/api/${slug}/tabs/${tab.key}/table-edit`,{...payload,base_revision:payload.base_revision??tab.revision});
      if(result.conflicts?.length){const error=new Error('內容已變更或鎖定；草稿已保留，請核對目前內容後再處理');error.data=result;throw error;}
      if(record&&!payload.new_rows?.length){setUndo(old=>[...old.slice(-49),payload]);setRedo([]);}
      if(payload.new_rows?.length){setUndo([]);setRedo([]);}
      setSaveState('已儲存');await refresh();return true;
    }catch(e){fail(e,()=>submit(payload,{record}));setFailure(old=>({...old,draft:payload.row_edits?.map(row=>Object.values(row.cells).join(' / ')).join('；')}));if(e.status===409)await refresh();return false;}finally{busyRef.current=false;setBusy(false);}
  };
  const payloadCell=(r,c,value,base=parsed)=>visiblePastePayload(base,[base.rows[r].rid],{r,c},[[value]]);
  const commit=async(r,c,value)=>{try{return await submit(payloadCell(r,c,value));}catch(e){fail(e);return false;}};
  const beginEdit=(r,c,initial)=>{
    if(!writable||busy||dirty)return;const cell=parsed.rows[r]?.cells[c];if(!cell)return;
    setFailure(null);setActive({r,c});setAnchor({r,c});setText(initial??String(cell.value));setEditing({r,c,rid:parsed.rows[r].rid,value:cell.value,table:parsed,revision:tab.revision,selectAll:initial==null});setSaveState('編輯中');
  };
  const nextPosition=(current,key,back=false)=>{
    let ri=Math.max(0,rowIndices.indexOf(current.r)),ci=Math.max(0,visibleColumns.indexOf(current.c));
    if(key==='Tab'){ci+=back?-1:1;if(ci>=visibleColumns.length){ci=0;ri++;}if(ci<0){ci=visibleColumns.length-1;ri--;}}
    else if(key==='Enter'||key==='ArrowDown')ri+=back?-1:1;
    else if(key==='ArrowUp')ri--;else if(key==='ArrowLeft')ci--;else if(key==='ArrowRight')ci++;
    return{r:rowIndices[Math.max(0,Math.min(rowIndices.length-1,ri))],c:visibleColumns[Math.max(0,Math.min(visibleColumns.length-1,ci))]};
  };
  const finishEdit=async(key=null,back=false)=>{
    if(!editing||composing.current||busy)return;
    try{
      const current=editing;
      if(!dirty||await submit({...payloadCell(current.r,current.c,text,current.table),base_revision:current.revision})){
        setEditing(null);setSaveState('已儲存');focus(key?nextPosition(current,key,back):current);
      }
    }catch(e){fail(e);}
  };
  const cancelEdit=()=>{if(busy)return;setEditing(null);setFailure(null);setSaveState('已儲存');focus(active);};
  const rebaseEdit=async()=>{
    try{const original=payloadCell(editing.r,editing.c,text,editing.table),updated=rebaseOperation(parsed,original);
      if(await submit(updated)){setEditing(null);focus({r:parsed.rows.findIndex(row=>row.rid===editing.rid),c:Number(Object.keys(updated.row_edits[0].cells)[0])});}
    }catch(e){fail(e);}
  };
  const travelHistory=async direction=>{
    const stack=direction==='undo'?undo:redo,action=stack.at(-1);if(!action||editing)return;
    const payload=direction==='undo'?inverseOperation(action):action;
    if(await submit(payload,{record:false})){
      if(direction==='undo'){setUndo(old=>old.slice(0,-1));setRedo(old=>[...old,action]);}else{setRedo(old=>old.slice(0,-1));setUndo(old=>[...old,action]);}
    }else setFailure(old=>old?{...old,retry:()=>travelHistory(direction)}:old);
  };
  const paste=e=>{
    if(!writable||busy||editing||!e.target.closest('td[data-cell]'))return;e.preventDefault();
    try{const cells=parseTSV(e.clipboardData.getData('text/plain')),payload=visiblePastePayload(parsed,visibleIds,active,cells,visibleColumns);
      if(cells.length>1||cells[0].length>1||query||statusFilter||sort||hidden.length)setPendingPaste({payload,cells,rows:cells.length,columns:Math.max(...cells.map(r=>r.length))});else submit(payload);
    }catch(error){fail(error);}
  };
  const copy=e=>{if(editing||!e.target.closest('td[data-cell]'))return;e.preventDefault();e.clipboardData.setData('text/plain',rangeTSV(parsed,range));};
  const keyCell=(e,r,c)=>{
    if(e.target!==e.currentTarget||editing)return;
    if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='a'){e.preventDefault();setAnchor({r:rowIndices[0],c:visibleColumns[0]});setActive({r:rowIndices.at(-1),c:visibleColumns.at(-1)});return;}
    if((e.ctrlKey||e.metaKey)&&['z','y'].includes(e.key.toLowerCase())){e.preventDefault();travelHistory(e.shiftKey||e.key.toLowerCase()==='y'?'redo':'undo');return;}
    if(e.key==='F2'||e.key==='Enter'){e.preventDefault();beginEdit(r,c);return;}
    if(['ArrowUp','ArrowDown','ArrowLeft','ArrowRight','Tab'].includes(e.key)){
      e.preventDefault();const next=nextPosition({r,c},e.key,e.shiftKey&&e.key==='Tab');setActive(next);if(!e.shiftKey||e.key==='Tab')setAnchor(next);requestAnimationFrame(()=>grid.current?.querySelector(`[data-cell="${next.r}:${next.c}"]`)?.focus());return;
    }
    if(e.key==='Escape'){setAnchor(active);return;}
    if(e.key==='Process'||e.keyCode===229){beginEdit(r,c,'');return;}
    if(e.key.length===1&&!e.ctrlKey&&!e.metaKey&&!e.altKey){e.preventDefault();beginEdit(r,c,e.key);}
  };
  const openRow=rid=>{if(dirty){fail(new Error('請先儲存或取消目前的格內編輯'));return;}setRowOpen(rid);setPanel('row');setHistory(null);setComment('');};
  const showHistory=async rid=>run(async()=>{const data=await api.get(`/projects/api/${slug}/history?tab=${encodeURIComponent(tab.key)}`);setHistory(historyForRow(data.groups||data.history||[],rid,parsed.tableId));});
  const showPreview=item=>{setPreview(item);setRowOpen(parsed.rows[item.r]?.rid||null);setHistory(null);setPanel(null);setComment('');};
  const stepPreview=direction=>{
    if(!previewTargetValid)return;
    const at=visibleRows.findIndex(r=>r.rid===previewRow?.rid),target=visibleRows[at+direction];if(!target)return;
    const r=parsed.rows.indexOf(target),c=preview.c,media=mediaOf(target.cells[c]?.value,types[c]);
    setPreview({...(media||{}),r,c,label:parsed.headers[c],value:target.cells[c]?.value});setRowOpen(target.rid);setComment('');setHistory(null);
  };
  const ask=(ids=null,initial='')=>{
    try{const chosen=ids||(selected.size?[...selected]:range.rows.length?range.rows.map(r=>parsed.rows[r].rid):visibleIds);
      const columns=ids||selected.size?parsed.headers.map((_,i)=>i):range.columns.length?range.columns:visibleColumns;
      const scope=freezeSheetScope(tab,parsed,chosen,columns);setRequest({scope,table:parsed,title:tab.title});setInstruction(initial);setPanel(null);setPreview(null);
    }catch(e){fail(e);}
  };
  const toFlow=(ids,options={})=>{if(!guardDraft())return;try{sessionStorage.setItem(`openbench-selection:${slug}`,JSON.stringify({...freezeSheetScope(tab,parsed,ids),...options}));window.location.hash=workflow||flows[0].key;}catch(e){fail(e);}};
  const schema=async body=>run(async()=>{
    setSaveState('儲存中…');const result=await api.post(`/projects/api/${slug}/tabs/${tab.key}/table-schema`,{table_id:parsed.tableId,expected_column_ids:columnIds,base_revision:tab.revision,...body});
    if(result.conflicts?.length){const error=new Error('欄位已被修改，設定草稿保留，請重新整理後核對');error.data=result;throw error;}
    setUndo([]);setRedo([]);setSchemaPlan(null);setColumnDraft(null);setSaveState('已儲存');await refresh();
  });
  const saveColumn=()=>{if(!columnDraft)return;const options=columnDraft.options.split(/\r?\n|、/).map(s=>s.trim()).filter(Boolean);if(columnDraft.type==='status'&&!options.length){fail(new Error('請至少設定一個狀態選項'));return;}setSchemaPlan({operation:'configure',column_id:columnIds[columnDraft.c],name:columnDraft.name,column_type:columnDraft.type,...(columnDraft.type==='status'?{options}:{})});setNewWorkbook(false);};
  const openColumn=c=>{if(!guardDraft())return;setColumnDraft({c,name:parsed.headers[c],type:types[c]||'text',options:statusOptions(parsed,c).join('\n')});setPanel('columns');setPreview(null);};
  const pickUpload=(r,c)=>{uploadTarget.current={r,c,table:parsed,revision:tab.revision};upload.current?.click();};
  const exportCSV=()=>{if(!guardDraft())return;const url=URL.createObjectURL(new Blob([tableCSV(parsed)],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=`${tab.title}-${parsed.name}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
  const postComment=()=>run(async()=>{await api.post(`/projects/api/${slug}/annotations`,{tab_key:tab.key,row:contextRow.rid,body:comment});setComment('');await refresh();});
  const discussion=<div className="sheet-discussion"><h3>討論</h3>{messages.length?messages.map((m,i)=><p key={m.id||i}><strong>{m.name||m.actor_name}</strong> {m.body||m.new_value}</p>):<p className="sheet-subtle">尚無留言</p>}{writable&&<><textarea aria-label="列留言" placeholder="記錄這一筆需要調整的地方" rows={3} value={comment} onChange={e=>setComment(e.target.value)}/><button disabled={busy||!comment.trim()} onClick={postComment}>送出留言</button></>}</div>;
  const historyContent=history&&<div className="sheet-history"><h3>版本紀錄</h3>{!history.length&&<p>這一列尚無修改紀錄。</p>}{history.map(g=><section key={g.id}><b>{g.name} · {shortTime(g.at)}</b>{g.changes.map((change,i)=>{
    const hasMedia=!!(change.media_before?.length||change.media_after?.length);
    const segments=(change.segments||[]).map(([kind,s],j)=>kind==='-'?<del key={j}>{s}</del>:kind==='+'?<ins key={j}>{s}</ins>:<span key={j}>{s}</span>);
    return <div className="history-row-change" key={i}>{change.tableWide&&<small>整張表格的修改</small>}<p>{change.label||change.title||'內容變更'}</p>{!hasMedia&&segments}<div className="history-media">{[['修改前',change.media_before],['修改後',change.media_after]].map(([label,urls])=>urls?.length?<div key={label}><strong>{label}</strong>{urls.map(url=><MediaCell key={url} value={url} label={label} onLightbox={item=>showPreview({...item,r:preview?.r??(contextRow?parsed.rows.indexOf(contextRow):undefined),c:preview?.c})}/>)}</div>:null)}</div>{hasMedia&&<details className="history-field-diff"><summary>完整欄位變更</summary>{segments}</details>}</div>;
  })}</section>)}</div>;

  return <section className="canvas sheet-canvas sheet-v2 sheet-workspace" onPaste={paste} onCopy={copy}>
    <header className="sheet-workspace-heading"><h1>{tab.title}</h1><span className="sheet-count">{parsed.rows.length} 列</span><div className="sheet-save-state" role="status">{busy?'儲存中…':dirty?'尚未提交':saveState}</div><button aria-label="撤銷上一次儲存格操作" title="撤銷 Ctrl+Z" disabled={!undo.length||busy||!!editing} onClick={()=>travelHistory('undo')}>↶</button><button aria-label="重做儲存格操作" title="重做 Ctrl+Shift+Z" disabled={!redo.length||busy||!!editing} onClick={()=>travelHistory('redo')}>↷</button><details className="sheet-more"><summary aria-label="表格更多操作">⋯</summary><div className="sheet-dropdown"><button disabled={busy||dirty} onClick={switchDocument}>文件與標註</button><button disabled={busy||dirty} onClick={()=>downloadWorkbook("original_patch")}>匯出 Excel（保留來源格式）</button><button disabled={busy||dirty} onClick={()=>downloadWorkbook("new_workbook")}>另存新工作簿（目前資料）</button><button disabled={busy||dirty} onClick={exportCSV}>匯出此工作表 CSV</button></div></details></header>
    {tables.length>1&&<div className="sheet-tabs" role="tablist">{tables.map(t=><button role="tab" key={t.tableId} aria-selected={t.tableId===parsed.tableId} disabled={busy||dirty||!!pendingPaste} onClick={()=>{setEditing(null);setTableId(t.tableId);}}>{t.name}</button>)}</div>}
    <div className="sheet-workspace-toolbar"><div className="sheet-view-switch" role="group" aria-label="表格檢視方式">{[['grid','表格'],['gallery','圖庫'],['kanban','看板']].map(([key,label])=><button key={key} aria-pressed={mode===key} disabled={dirty} onClick={()=>setView({mode:key})}>{label}</button>)}</div>
      <input className="sheet-search" aria-label="搜尋表格" placeholder="搜尋…" value={query} disabled={dirty} onChange={e=>{setQuery(e.target.value);setSelected(new Set());setAnchor({r:-1,c:-1});}}/>
      {!!statusValues.length&&<select aria-label="篩選列狀態" value={statusFilter} disabled={dirty} onChange={e=>{setStatusFilter(e.target.value);setSelected(new Set());setAnchor({r:-1,c:-1});}}><option value="">全部狀態</option>{statusValues.map(s=><option key={s}>{s}</option>)}</select>}
      {(query||statusFilter)&&<button className="quiet" onClick={()=>{setQuery('');setStatusFilter('');}}>清除篩選 · {visibleRows.length} 列</button>}
      {sort&&<button className="quiet" onClick={()=>setSort(null)}>清除排序 ×</button>}
      <span className="spacer"/><button disabled={busy||dirty} onClick={()=>{setColumnDraft(null);setPanel(panel==='columns'?null:'columns');}}>欄位{hidden.length?` · 隱藏 ${hidden.length}`:''}</button>
      {writable&&<><button disabled={busy||dirty} onClick={()=>{const payload=tableEditPayload(parsed,parsed.rows.length,0,[parsed.headers.map(()=>'')]);if(imported){setSchemaPlan({addRow:payload});setNewWorkbook(false);}else submit(payload);}}>＋ 列</button>{onAskAgent&&<button className="primary" disabled={!visibleRows.length||dirty} onClick={()=>ask()}>交給代理</button>}</>}
    </div>
    {mode!=='grid'&&<div className="sheet-card-settings">{view.coverColumns.length>0&&<label>封面 <select aria-label="卡片封面欄位" value={view.coverColumn} onChange={e=>setView({coverColumn:Number(e.target.value)})}><option value={-1}>不顯示</option>{view.coverColumns.map(c=><option key={c.index} value={c.index}>{c.label}</option>)}</select></label>}{view.statusColumns.length>0&&<label>分組 <select aria-label="看板分組欄位" value={view.groupColumn} onChange={e=>setView({groupColumn:Number(e.target.value)})}>{view.statusColumns.map(c=><option key={c.index} value={c.index}>{c.label}</option>)}</select></label>}<small>檢視設定只影響此瀏覽器</small></div>}
    {selected.size>0&&<div className="batch-bar"><b>已勾選 {selected.size} 列</b><button disabled={!onAskAgent||!writable} onClick={()=>ask([...selected])}>請代理處理</button>{flows.length>0&&<><select aria-label="選擇執行工作流" value={workflow||flows[0].key} onChange={e=>setWorkflow(e.target.value)}>{flows.map(t=><option key={t.key} value={t.key}>{t.title}</option>)}</select><button disabled={!writable||selected.size>200} onClick={()=>toFlow([...selected])}>交給工作流</button></>}<button className="quiet" onClick={()=>setSelected(new Set())}>取消勾選</button></div>}
    {failure&&<div className="sheet-save-error" role="alert"><strong>{failure.message}</strong>{failure.draft&&!editing&&<span>保留的修改：{failure.draft.slice(0,250)}</span>}{editing&&<span>我的內容：{text.slice(0,180)} · 目前內容：{String(parsed.rows.find(r=>r.rid===editing.rid)?.cells[editing.c]?.value??'').slice(0,180)}</span>}{failure.details?.conflicts&&<details><summary>查看衝突</summary><pre>{JSON.stringify(failure.details.conflicts,null,2)}</pre></details>}<div>{editing?<><button disabled={busy} onClick={()=>finishEdit()}>重試儲存</button><button disabled={busy} onClick={rebaseEdit}>採用我的內容再次儲存</button><button disabled={busy} onClick={cancelEdit}>放棄這次編輯</button></>:failure.retry&&<button disabled={busy} onClick={failure.retry}>重試</button>}<button disabled={busy} onClick={()=>run(refresh)}>重新讀取目前內容</button><button onClick={()=>setFailure(null)}>收起</button></div></div>}
    {taskError&&<p className="sheet-task-warning" role="status">任務狀態暫時無法更新：{taskError}</p>}
    {editing&&<div className="sheet-edit-strip"><b>{columnName(editing.c)}{editing.r+1} · {parsed.headers[editing.c]}</b><span>Enter 往下 · Tab 往右 · Shift+Enter 換行 · Esc 取消</span><button disabled={busy} onClick={()=>finishEdit()}>儲存</button><button disabled={busy} onClick={cancelEdit}>取消</button></div>}
    <div className={`sheet-workspace-body${panel?' has-panel':''}`}>
      <div className="sheet-main-view">
        {mode==='grid'?<div className="sheet-scroll" ref={grid}><table className="production-sheet" role="grid" aria-label={parsed.name} aria-rowcount={visibleRows.length+1} style={{width:visibleColumns.reduce((n,c)=>n+columnWidth(c),112)}}><colgroup><col style={{width:32}}/><col style={{width:36}}/>{visibleColumns.map(c=><col key={c} style={{width:columnWidth(c)}}/>)}<col style={{width:44}}/></colgroup><thead><tr><th className="select-col"><input type="checkbox" aria-label="選取全部可見列" checked={visibleRows.length>0&&visibleRows.every(r=>selected.has(r.rid))} onChange={e=>setSelected(e.target.checked?new Set(visibleIds):new Set())}/></th><th className="row-number">#</th>{visibleColumns.map(c=><th key={columnIds[c]||c}><button className="sheet-column-trigger" disabled={busy||dirty} aria-label={`設定欄位 ${parsed.headers[c]}`} onClick={()=>openColumn(c)}><span className="column-letter">{columnName(c)}</span><span>{parsed.headers[c]}</span>{sort?.c===c?<span>{sort.direction==='asc'?'↑':'↓'}</span>:<span className="column-chevron">⌄</span>}</button></th>)}<th className="row-actions">詳情</th></tr></thead><tbody>{visibleRows.map(item=>{
          const r=parsed.rows.indexOf(item);
          return <tr key={item.rid} className={selected.has(item.rid)?'selected-row':''}><td className="select-col"><input type="checkbox" aria-label={`選取第 ${r+1} 列`} checked={selected.has(item.rid)} onChange={e=>setSelected(old=>{const next=new Set(old);if(e.target.checked)next.add(item.rid);else next.delete(item.rid);return next;})}/></td><td className="row-number">{r+1}</td>{visibleColumns.map(c=>{
            const cell=item.cells[c]||{value:''},media=mediaOf(cell.value,types[c]),isEditing=editing?.rid===item.rid&&editing.c===c,inRange=range.rows.includes(r)&&range.columns.includes(c);
            return <td key={columnIds[c]||c} role="gridcell" aria-selected={inRange} aria-label={`${columnName(c)}${r+1} ${parsed.headers[c]}`} data-cell={`${r}:${c}`} tabIndex={r===safeFocus.r&&c===safeFocus.c?0:-1} className={`${inRange?'range-cell ':''}${active.r===r&&active.c===c?'active-cell ':''}${isEditing?'editing-cell':''}`}
              onFocus={e=>{if(e.target!==e.currentTarget)return;setActive({r,c});if(!range.rows.length)setAnchor({r,c});}} onMouseDown={e=>{if(e.button!==0||editing||e.target.closest('button,select,input,textarea'))return;dragging.current=true;if(!e.shiftKey)setAnchor({r,c});setActive({r,c});e.currentTarget.focus();}}
              onMouseEnter={e=>{if(dragging.current&&e.buttons===1&&!editing)setActive({r,c});}}
              onDoubleClick={()=>{if(!media)beginEdit(r,c);}} onKeyDown={e=>keyCell(e,r,c)}>
              {isEditing?<textarea ref={editor} className="sheet-inline-editor" aria-label="儲存格內容或公式" value={text} disabled={busy} onChange={e=>setText(e.target.value)} onCompositionStart={()=>{composing.current=true;}} onCompositionEnd={()=>{composing.current=false;}} onKeyDown={e=>{
                e.stopPropagation();if(composing.current||e.nativeEvent.isComposing||e.keyCode===229)return;
                if(e.key==='Escape'){e.preventDefault();cancelEdit();}else if(e.key==='Tab'||(e.key==='Enter'&&!e.shiftKey)){e.preventDefault();finishEdit(e.key,e.shiftKey);}
              }}/>:media?<MediaCell compact value={cell.value} type={types[c]} label={parsed.headers[c]} onLightbox={item=>showPreview({...item,r,c})}/>:isStatus(c)?<select aria-label={`第 ${r+1} 列 ${parsed.headers[c]}`} className={`cell-status ${cell.value==='已完成'?'done':''}`} value={cell.value||''} disabled={!writable||busy||dirty} onChange={e=>commit(r,c,e.target.value)}><option value="" disabled={cell.kind==='status'}>未設定</option>{statusOptions(parsed,c,item).map(value=><option key={value}>{value}</option>)}</select>:<span className={`cell-text ${String(cell.value).startsWith('=')?'formula-result':''}`} title={cell.value}>{evaluate(cell.value,parsed.rows,new Set(),imported?(attrs.source_header_row||1):0)||<span className="empty-cell">—</span>}</span>}
            </td>;
          })}<td className="row-actions"><button aria-label={`第 ${r+1} 列詳細內容`} onClick={()=>openRow(item.rid)}>↗</button>{locks.some(lock=>lock.tab_key===tab.key&&[item.rid,parsed.tableId].includes(lock.unit_id))&&<small title="這一列有人正在編輯">鎖定</small>}</td></tr>;
        })}</tbody></table>{!visibleRows.length&&<div className="sheet-empty"><p>{query||statusFilter?'沒有符合條件的資料':'從第一筆資料開始'}</p><small>{query||statusFilter?'清除篩選，或換一個關鍵字。':'按「＋ 列」建立資料，接著可貼上 Excel 內容。'}</small></div>}</div>
          :mode==='kanban'&&view.groupColumn<0?<div className="sheet-empty"><h2>先設定狀態欄</h2><p>將欄位類型改成狀態，就能依進度分組。</p><button onClick={()=>setPanel('columns')}>設定欄位</button></div>
          :!visibleRows.length?<div className="sheet-empty"><p>沒有符合條件的資料</p></div>:<SheetCards model={view} mode={mode} parsed={parsed} selected={selected} onSelect={(rid,checked)=>setSelected(old=>{const next=new Set(old);if(checked)next.add(rid);else next.delete(rid);return next;})} onOpen={openRow} onPreview={showPreview} onStatus={(rid,c,value)=>commit(parsed.rows.findIndex(r=>r.rid===rid),c,value)} writable={writable} busy={busy}/>}
      </div>
      {panel&&<aside className="sheet-side-panel" aria-label={panel==='columns'?'欄位設定':'列詳細內容'}><header><h2>{panel==='columns'?'欄位設定':row?.cells[0]?.value||'列詳細內容'}</h2><button aria-label="關閉側欄" onClick={closePanel}>×</button></header>
        {panel==='columns'?<><p className="sheet-subtle">排序、隱藏與寬度只改目前檢視。</p><div className="sheet-columns-nav">{parsed.headers.map((name,c)=><button key={c} className={columnDraft?.c===c?'active':''} onClick={()=>openColumn(c)}>{name}{hidden.includes(c)?' · 已隱藏':''}</button>)}</div>{columnDraft&&<div className="sheet-column-form"><label>欄位名稱<input aria-label="欄位名稱" value={columnDraft.name} disabled={!writable} onChange={e=>setColumnDraft({...columnDraft,name:e.target.value})}/></label><label>內容類型<select aria-label="欄位類型" value={columnDraft.type} disabled={!writable} onChange={e=>setColumnDraft({...columnDraft,type:e.target.value})}>{Object.entries(TYPES).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>{columnDraft.type==='status'&&<label>狀態選項（每行一項）<textarea aria-label="狀態選項" rows={5} value={columnDraft.options} disabled={!writable} onChange={e=>setColumnDraft({...columnDraft,options:e.target.value})}/></label>}<button className="primary" disabled={!writable||busy||!columnDraft.name.trim()} onClick={saveColumn}>套用欄位設定</button><hr/><div className="sheet-panel-actions"><button onClick={()=>setSort({c:columnDraft.c,direction:'asc'})}>由小到大 ↑</button><button onClick={()=>setSort({c:columnDraft.c,direction:'desc'})}>由大到小 ↓</button></div><label>欄寬 <input type="number" aria-label="欄位寬度" min={80} max={600} value={columnWidth(columnDraft.c)} onChange={e=>setWidths({...widths,[columnDraft.c]:Math.max(80,Math.min(600,Number(e.target.value)||180))})}/></label><button disabled={!hidden.includes(columnDraft.c)&&visibleColumns.length<=1} onClick={()=>setHidden(old=>old.includes(columnDraft.c)?old.filter(c=>c!==columnDraft.c):[...old,columnDraft.c])}>{hidden.includes(columnDraft.c)?'顯示此欄':'隱藏此欄'}</button><hr/><button className="danger" disabled={!writable||busy||parsed.headers.length<=1} onClick={()=>{setSchemaPlan({operation:'delete',column_id:columnIds[columnDraft.c],label:parsed.headers[columnDraft.c]});setNewWorkbook(false);}}>刪除此欄…</button></div>}
          {writable&&<form className="sheet-new-column" onSubmit={e=>{e.preventDefault();const name=new FormData(e.currentTarget).get('column_name').trim();if(name){setSchemaPlan({operation:'add',name,column_type:'text'});setNewWorkbook(false);}}}><label>新增欄位<input name="column_name" required aria-label="新增欄位名稱" placeholder="欄位名稱"/></label><button disabled={busy||parsed.headers.length>=100}>新增欄…</button></form>}</>
          :row&&<><div className="sheet-panel-actions"><button disabled={!writable||!onAskAgent} onClick={()=>ask([row.rid])}>交給代理</button><button disabled={busy} onClick={()=>showHistory(row.rid)}>版本紀錄</button></div><dl className="row-detail-fields">{row.cells.map((cell,c)=><div key={c}><dt>{parsed.headers[c]}</dt><dd>{mediaOf(cell.value,types[c])?<MediaCell compact value={cell.value} type={types[c]} label={parsed.headers[c]} onLightbox={item=>showPreview({...item,r:parsed.rows.indexOf(row),c})}/>:<span>{cell.value||'尚未填寫'}</span>}{writable&&<div className="sheet-field-actions"><button onClick={()=>{setPanel(null);setView({mode:'grid'});beginEdit(parsed.rows.indexOf(row),c);}}>編輯</button>{['image','video','audio'].includes(types[c])&&<button disabled={busy} onClick={()=>pickUpload(parsed.rows.indexOf(row),c)}>上傳</button>}</div>}</dd></div>)}</dl>{discussion}{historyContent}</>}
      </aside>}
    </div>
    <footer className="sheet-footer"><span>{mode==='grid'?(range.rows.length?`選取 ${range.rows.length} 列 × ${range.columns.length} 欄`:'單擊選格 · 拖曳或 Shift + 方向鍵選取'):'表格、圖庫與看板共用資料'}{mode==='grid'&&activeCell&&<span> · {columnName(active.c)}{active.r+1}{String(activeCell.value).startsWith('=')?`　${activeCell.value}`:''}</span>}</span><span>{mode==='grid'?'直接輸入或 F2 編輯 · 複製公式保留原文字':`${visibleRows.length} 筆資料`}</span></footer>
    {pendingPaste&&<SheetDialog title="核對貼上範圍" wide onClose={closePaste}><>{failure&&<p className="sheet-save-error" role="alert">{failure.message} · 貼上草稿仍保留</p>}</><p>將修改目前可見的 {pendingPaste.rows} 列 × {pendingPaste.columns} 欄，被篩選隱藏的列不會改動。</p><div className="sheet-paste-preview"><table><tbody>{pendingPaste.cells.slice(0,8).map((cells,i)=><tr key={i}><th>第 {parsed.rows.findIndex(r=>r.rid===pendingPaste.payload.row_edits[i].row_id)+1} 列</th>{cells.map((value,c)=><td key={c}>{value||'（空白）'}</td>)}</tr>)}</tbody></table></div>{pendingPaste.rows>8&&<p>另有 {pendingPaste.rows-8} 列；整次操作可一次撤銷。</p>}<p className="sheet-subtle">文字與數值保持原輸入；公式以原文字寫入，不自動位移參照。</p><div className="sheet-dialog-actions"><button disabled={busy} onClick={closePaste}>取消</button>{failure&&<button disabled={busy} onClick={()=>{try{setPendingPaste({...pendingPaste,payload:rebaseOperation(parsed,pendingPaste.payload)});setFailure(null);}catch(e){fail(e);}}}>以最新原值重新核對</button>}<button className="primary" disabled={busy} onClick={async()=>{if(await submit(pendingPaste.payload))setPendingPaste(null);}}>確認貼上</button></div></SheetDialog>}
    {request&&<SheetDialog title="交給代理協助" onClose={()=>setRequest(null)}><div className="request-scope"><b>{request.title} / {request.table.name}</b><small>已固定 {request.scope.row_ids.length} 列 × {request.scope.column_indices.length} 欄 · 版本 {request.scope.base_revision}</small></div><p className="sheet-subtle">切換選取不會改變這次範圍。代理會先提出修改，由你核對後寫回。</p><label className="modal-field"><span>想完成什麼？</span><textarea data-autofocus aria-label="代理工作需求" rows={5} value={instruction} onChange={e=>setInstruction(e.target.value)} placeholder="例如：核對這幾筆資料，補上缺少的說明"/></label><div className="sheet-dialog-actions"><button onClick={()=>{try{const ids=selected.size?[...selected]:visibleIds;setRequest({...request,scope:freezeSheetScope(tab,parsed,ids),table:parsed,title:tab.title});}catch(e){fail(e);}}}>以目前勾選／可見列更新範圍</button><button className="primary" disabled={!instruction.trim()} onClick={()=>{try{onAskAgent?.(sheetRequest(request.title,request.table,request.scope.row_ids,instruction),request.scope);setRequest(null);}catch(e){fail(e);}}}>放入對話 →</button></div></SheetDialog>}
    {schemaPlan&&<SheetDialog title={schemaPlan.operation==='delete'?'核對刪除欄位':'核對欄位與交付方式'} onClose={closeSchema}><>{failure&&<p className="sheet-save-error" role="alert">{failure.message}</p>}</><p>{schemaPlan.operation==='delete'?`將刪除「${schemaPlan.label}」及此欄內容。`:'確認後套用這次資料結構或欄位設定。'}伺服器會檢查公式及工作流依賴；有未解決依賴時拒絕修改。</p>{imported&&<><p>這張表來自 Excel。改變結構或表頭後，請使用「另存新工作簿」交付目前資料；新檔不保證原檔格式與合併格。</p><label className="sheet-check"><input type="checkbox" checked={newWorkbook} onChange={e=>setNewWorkbook(e.target.checked)}/>我會另存新工作簿交付這次整理</label></>}<p className="sheet-subtle">欄位結構變更會清空儲存格撤銷記錄，既有版本仍保留。</p><div className="sheet-dialog-actions"><button disabled={busy} onClick={closeSchema}>取消</button><button className="primary" disabled={busy||(imported&&!newWorkbook)} onClick={async()=>{const delivery=imported?{delivery_mode:'new_workbook'}:{};if(schemaPlan.addRow){if(await submit({...schemaPlan.addRow,...delivery}))setSchemaPlan(null);}else await schema({...schemaPlan,...delivery});}}>確認修改</button></div></SheetDialog>}
    {preview&&<SheetReview onClose={closePanel}><header><button onClick={closePanel}>← 返回表格</button><h2>{previewRow?.cells[0]?.value||preview.label||'素材審核'}</h2><span className="spacer"/><button aria-label="上一筆素材" disabled={!previewTargetValid||visibleRows.findIndex(r=>r.rid===previewRow?.rid)<=0} onClick={()=>stepPreview(-1)}>↑ 上一筆</button><button aria-label="下一筆素材" disabled={!previewTargetValid||visibleRows.findIndex(r=>r.rid===previewRow?.rid)>=visibleRows.length-1||!previewRow} onClick={()=>stepPreview(1)}>下一筆 ↓</button></header><div className="sheet-review-body"><div className="sheet-review-image">{preview.kind==='image'?<img src={preview.url} alt={preview.label||'目前圖片'}/>:preview.url?<MediaCell value={preview.value||preview.url} type={preview.kind} label={preview.label} onLightbox={setPreview}/>:<p>這一筆尚無圖片</p>}{historyContent}</div><aside><h3>{preview.label}</h3>{previewRow&&<>{view.statusColumns.map(({index,label})=><label className="modal-field" key={index}><span>{label}</span><select value={previewRow.cells[index]?.value||''} disabled={!writable||busy} onChange={e=>commit(preview.r,index,e.target.value)}><option value="">未設定</option>{statusOptions(parsed,index,previewRow).map(s=><option key={s}>{s}</option>)}</select></label>)}<div className="sheet-panel-actions"><button disabled={busy} onClick={()=>showHistory(previewRow.rid)}>比較版本</button>{writable&&previewTargetValid&&<><button disabled={busy} onClick={()=>pickUpload(preview.r,preview.c)}>上傳替換</button>{flows.length>0&&<button disabled={busy} onClick={()=>toFlow([previewRow.rid],{capability:"image_gen",col_index:preview.c})}>檢查重抽工作流</button>}<button disabled={!onAskAgent} onClick={()=>ask([previewRow.rid],`請依本列需求與參考資料，整理「${parsed.headers[preview.c]}」的圖片修改提案。`)}>請代理修改</button></>}</div>{discussion}</>}</aside></div></SheetReview>}
    <input ref={upload} hidden type="file" accept="image/png,image/jpeg,image/gif,image/webp,video/mp4,video/webm,audio/*" onChange={async e=>{const file=e.target.files?.[0],target=uploadTarget.current;e.target.value='';if(!file||!target)return;try{setBusy(true);const result=await api.upload(`/projects/api/${slug}/assets`,file,file.name);setBusy(false);const kind=result.content_type.split('/')[0],value=kind==='image'?`![圖片](${result.src})`:`[${kind}](${result.src})`;if(await submit({...payloadCell(target.r,target.c,value,target.table),base_revision:target.revision})){setPreview(null);setEditing(null);onToast?.('媒體已更新，先前版本保留在紀錄中');}}catch(error){setBusy(false);fail(error);}}}/>
  </section>;
}
