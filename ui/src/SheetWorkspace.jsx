import { useLocale } from './i18n/react.jsx';
import { t as uiText } from './i18n/index.js';
import { Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react';
import { api } from './api.js';
import { columnName, evaluate, mediaOf, parseTSV, tableEditPayload, tableCSV, tablesOf } from './sheetModel.js';
import { MediaCell } from './MediaCell.jsx';
import { SheetDialog } from './SheetDialog.jsx';
import { SheetCards } from './SheetCards.jsx';
import { buildAssetLookup, assetReferences, resolveAssetReference, mediaStages, mediaLadder, stageShots, presetsFor, presetLabel, applyPreset, studioRunInput, queueStudioRun, SHOT_FILTERS } from './studioModel.js';
import { actionColumn } from './bindingModel.js';
import { BindingText } from './ShotBindings.jsx';
import { SheetReview } from './SheetReview.jsx';
import { StoryBatchBar, ShotProduction } from './StoryWorkbenchModals.jsx';
import { episodeId, replaceAssetVariant, shotId as storyShotId, storyList, storyRequest, waitStoryTask } from './storyModel.js';
import { freezeSheetScope, historyForRow, inverseOperation, rangeTSV, rebaseOperation, selectionRange, sheetRequest, visiblePastePayload } from './sheetInteraction.js';
import { restoreViewPreferences, sheetViewModel, statusOptions, viewMode, viewPreferences } from './sheetViews.js';
import { shortTime, statusClass, statusLabel } from './format.js';
import { ShotList, ShotCompare, ShotSourceBadge, StageViewMenu } from './ShotStage.jsx';
import { ShotFilmPanel } from './ShotFilmPanel.jsx';
import { AdoptLatestButton } from './film/AdoptLatest.jsx';
import { TIMELINE_VIEW, inSlateOrder } from './StudioShell.jsx';
import { ShotComposer } from './composer/ShotComposer.jsx';
import { CrewAsk } from './CrewAsk.jsx';
import { PreproductionPanel } from './PreproductionPanel.jsx';
import './sheet-workspace.css';
import { SheetAgentRequest } from './assistant/SheetAgentRequest.jsx';
import { ShotBench, ShotStrip } from './ShotBench.jsx';
import { StoryCanvas } from './StoryCanvas.jsx';
// three.js only loads when a shot is blocked in 3D.
const PrevisStage = lazy(() => import('./previs/PrevisStage.jsx'));

const TYPES = {get text() { return uiText("sheetWorkspace.text"); },get number() { return uiText("sheetWorkspace.number"); },get formula() { return uiText("sheetWorkspace.formula"); },get image() { return uiText("sheetWorkspace.image"); },get video() { return uiText("sheetWorkspace.videoAttachment"); },get audio() { return uiText("sheetWorkspace.audio"); },get status() { return uiText("sheetWorkspace.status"); }};

export function SheetSurface({slug,tab,tabs=[],me,values,annotations=[],locks=[],controlRef,onReloadTab,onAskAgent,onSwitchDocMode,onToast,onError,onPanelChange,assistantOpen,focusRow,agents=[],onAgentRouted, storyEpisode, onOpenWorld, onFilm, shotFocus, onShotFocus, proposals=[], onApplyProposal, onDismissProposal, onReloadProposals, intent=null, onIntentDone, writingAlignment, onOpenSource}) {
  const locale = useLocale();
  const tables = useMemo(()=>tablesOf(tab.doc,values),[tab.doc,values]);
  const [tableId,setTableId]=useState(null);
  const parsed=tables.find(t=>t.tableId===tableId)||tables[0];
  const [active,setActive]=useState({r:0,c:0}),[anchor,setAnchor]=useState({r:0,c:0});
  const [selected,setSelected]=useState(new Set()),[query,setQuery]=useState(''),[statusFilter,setStatusFilter]=useState('');
  const [sort,setSort]=useState(null),[hidden,setHidden]=useState([]),[widths,setWidths]=useState({});
  const [localPreference,setLocalPreference]=useState(null);
  const [editing,setEditing]=useState(null),[text,setText]=useState(''),[busy,setBusy]=useState(false),[saveState,setSaveState]=useState("saved");
  const [failure,setFailure]=useState(null),[undo,setUndo]=useState([]),[redo,setRedo]=useState([]),[pendingPaste,setPendingPaste]=useState(null);
  const [panel,setPanel]=useState(null),[rowOpen,setRowOpen]=useState(null),[previewState,setPreview]=useState(null),[history,setHistory]=useState(null);
  const [comment,setComment]=useState(''),[request,setRequest]=useState(null),[instruction,setInstruction]=useState('');
  const [columnDraft,setColumnDraft]=useState(null),[schemaPlan,setSchemaPlan]=useState(null),[newWorkbook,setNewWorkbook]=useState(false),[workflow,setWorkflow]=useState('');
  const [taskError,setTaskError]=useState(''),[shotFilter,setShotFilter]=useState('all');
  const [assetDocuments,setAssetDocuments]=useState([]),[storyScenes,setStoryScenes]=useState([]),[episodeRows,setEpisodeRows]=useState(null),[shotInfo,setShotInfo]=useState({});
  // SPEC_19 4.1: rows with a pipeline task still queued or running (from the task poll below) are generating; the shot panel's
  // A and Esc go through filmControl.
  const [running,setRunning]=useState('');
  // SPEC_19 R9: story tasks the shot composer sent from this page, per row (they count as generating until they end), and a counter
  // that moves when one ends, so the takes and the episode's shots are read again even when the cell did not change (an adopted shot).
  const [storyRuns,setStoryRuns]=useState({}),[takesNonce,setTakesNonce]=useState(0);
  const inFlight=useMemo(()=>new Set([...(running?running.split('|'):[]),...Object.keys(storyRuns)]),[running,storyRuns]);
  const filmControl=useRef(null),composerControl=useRef(null),storyWaits=useRef(new Set());
  useEffect(()=>()=>{storyWaits.current.forEach(controller=>controller.abort());storyWaits.current.clear();},[]);
  const productionSheet=['cinema-studio','openjutsu-lab'].includes(tab.key);
  const epId=storyEpisode||episodeId(slug);
  useEffect(()=>{if(productionSheet){setEpisodeRows(new Set());setSelected(new Set());setPanel(null);setPreview(null);}},[epId,productionSheet]);
  useEffect(()=>{
    let alive=true;
    if(productionSheet)Promise.all([storyList(`/episodes/${epId}/scenes`),storyList(`/episodes/${epId}/shots`)]).then(([scenes,shots])=>{
      if(alive){setStoryScenes(scenes);setShotInfo(Object.fromEntries(shots.map(shot=>[shot.rowId,shot])));setEpisodeRows(new Set(shots.filter(shot=>shot.tabKey===tab.key).map(shot=>shot.rowId)));}
    }).catch(()=>{if(alive){setStoryScenes([]);setEpisodeRows(new Set());}});
    return()=>{alive=false;};
  },[epId,productionSheet,tab.updated_at,takesNonce]);
  const assetLookup=useMemo(()=>buildAssetLookup([{...tab,values},...assetDocuments]),[tab.doc,values,assetDocuments]);
  const grid=useRef(null),editor=useRef(null),dragging=useRef(false),composing=useRef(false),busyRef=useRef(false),upload=useRef(null),uploadTarget=useRef(null);
  const reload=useRef(onReloadTab),outputs=useRef(null);
  const handledFocus=useRef(null),reviewFocus=useRef(null);
  reload.current=onReloadTab;
  const writable=me?.can_write!==false;
  const dirty=!!editing && text!==editing.value;
  const preferenceKey=`openbench-sheet-view:${slug}:${tab.key}:${parsed?.tableId||''}`;
  const storedPreference=useMemo(()=>{try{return localStorage.getItem(preferenceKey);}catch{return null;}},[preferenceKey]);
  useEffect(()=>{
    setSelected(new Set());setActive({r:0,c:0});setAnchor({r:0,c:0});setQuery('');setStatusFilter('');setSort(null);setHidden([]);setWidths({});setUndo([]);setRedo([]);setPanel(null);setPreview(null);setFailure(null);setSaveState("saved");
  },[parsed?.tableId]);
  useEffect(()=>{setHidden([]);setSort(null);setWidths({});setColumnDraft(null);},[JSON.stringify(parsed?.table.attrs.column_ids||[])]);
  useEffect(()=>{const ids=new Set(parsed?.rows.map(row=>row.rid)||[]);setSelected(old=>new Set([...old].filter(id=>ids.has(id))));},[JSON.stringify(parsed?.rows.map(row=>row.rid)||[])]);
  useEffect(()=>{onPanelChange?.(!!panel||!!previewState||!!request);},[panel,previewState,request,onPanelChange]);
  useEffect(()=>{if(assistantOpen){setRequest(null);setPanel(current=>current==='columns'?null:current);}},[assistantOpen]);
  useEffect(()=>{
    if(!focusRow||focusRow.tabKey!==tab.key||dirty||busy)return;
    const token=JSON.stringify(focusRow);if(handledFocus.current===token)return;
    const target=focusRow.tableId?tables.find(t=>t.tableId===focusRow.tableId):tables.find(t=>t.rows.some(row=>row.rid===focusRow.rowId))||tables[0];
    if(!target){handledFocus.current=token;onError?.(uiText("sheetWorkspace.thePipelineSSourceWorksheetNoLongerExistsNo"));return;}
    if(parsed?.tableId!==target.tableId){setTableId(target.tableId);return;}
    const r=target.rows.findIndex(row=>row.rid===focusRow.rowId),c=Number(focusRow.colIndex??0);
    if(r<0||!Number.isInteger(c)||c<0||c>=target.headers.length){handledFocus.current=token;onError?.(uiText("sheetWorkspace.aSourceRowOrColumnNoLongerExistsReview"));return;}
    handledFocus.current=token;setQuery('');setStatusFilter('');setHidden(old=>old.filter(index=>index!==c));setPanel(null);setPreview(null);
    const prior=restoreViewPreferences(localPreference?.key===preferenceKey?localPreference.raw:storedPreference,target);
    // openStage: a shot whose crew proposal is reviewed on the 3D Stage (SPEC_20 R18); a sheet without a previs column opens its row instead.
    const toStage=focusRow.openStage&&target.headers.some(h=>/previs|blockout/i.test(h));
    setLocalPreference({key:preferenceKey,raw:JSON.stringify(viewPreferences(target,{...prior,mode:toStage?'stage':productionSheet&&focusRow.openRow?'review':'grid'}))});setActive({r,c});setAnchor({r,c});
    if(toStage){setRowOpen(focusRow.rowId);setStageFocus({rid:focusRow.rowId});}
    else if(focusRow.openRow){setRowOpen(focusRow.rowId);setPanel('row');setComment('');setHistory(null);if(productionSheet){const stage=mediaStages(target,target.rows[r])[0];if(stage){setPanel(null);setPreview({...stage.media,r,c:stage.column,label:stage.label,value:stage.value});}}}
    requestAnimationFrame(()=>{const cell=grid.current?.querySelector(`[data-cell="${r}:${c}"]`);cell?.focus();cell?.scrollIntoView({block:'nearest',inline:'nearest'});});
  },[focusRow,tab.key,tables,parsed?.tableId,dirty,busy,preferenceKey,storedPreference,localPreference,onError]);
  useEffect(()=>{
    const stop=()=>{dragging.current=false;};window.addEventListener('mouseup',stop);
    return()=>window.removeEventListener('mouseup',stop);
  },[]);
  useEffect(()=>{
    if(!controlRef)return;
    const control={consoleContext:()=>{const rid=previewState ? parsed?.rows[previewState.r]?.rid : panel==='row'||productionSheet ? rowOpen:null;return rid ? {tabKey:tab.key,tableId:parsed.tableId,rowId:rid,colIndex:previewState?.c ?? 0,openRow:true}:null;},flush:async()=>{
      if(dirty||busy||pendingPaste){onError?.(busy?uiText("sheetWorkspace.waitForSavingToFinishBeforeSwitchingPages"):uiText("sheetWorkspace.saveOrCancelTheCurrentDraftFirst"));return false;}return true;
    }};controlRef.current=control;
    return()=>{if(controlRef.current===control)controlRef.current=null;};
  },[controlRef,dirty,busy,pendingPaste,onError,previewState,panel,rowOpen,parsed,tab.key]);
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
          setRunning([...new Set((data.tasks||[]).filter(t=>['queued','running','blocked'].includes(t.status)&&t.row_id).map(t=>t.row_id))].sort().join('|'));
          if(outputs.current!==null&&outputs.current!==next)await reload.current?.();outputs.current=next;setTaskError('');}
      }catch(e){if(alive)setTaskError(e.message);}if(alive)timer=setTimeout(poll,5000);
    };poll();return()=>{alive=false;clearTimeout(timer);};
  },[slug,tab.key]);

  useEffect(()=>{
    let alive=true;
    const others=tabs.filter(item=>item.surface_type==='sheet'&&item.key!==tab.key);
    Promise.all(others.map(async item=>{const data=await api.get('/projects/api/'+slug+'/tabs/'+item.key);return {...item,...(data.tab||data),values:data.values||data.tab?.values||{}};}))
      .then(documents=>{if(alive)setAssetDocuments(documents);}).catch(()=>{if(alive)setAssetDocuments([]);});
    return()=>{alive=false;};
  },[slug,tab.key,JSON.stringify(tabs.filter(item=>item.surface_type==='sheet').map(item=>[item.key,item.revision]))]);
  // Crew proposals are reviewed on their shot, so a production sheet reads the assistant's list when it opens.
  useEffect(()=>{if(productionSheet)onReloadProposals?.();},[productionSheet,tab.key]);  // eslint-disable-line react-hooks/exhaustive-deps
  // The shell's space menu can arrive here with a shot filter ("2 to review"); it is taken once and cleared.
  useEffect(()=>{if(intent?.space==='stage'&&productionSheet&&intent.filter&&SHOT_FILTERS[intent.filter]){setShotFilter(intent.filter);onIntentDone?.();}},[intent,productionSheet]);  // eslint-disable-line react-hooks/exhaustive-deps

  if(!parsed)return <div className="canvas sheet-empty"><h2>{tab.title}</h2><p>{uiText("sheetWorkspace.addATableToStartPlanningYourProduction")}</p><button onClick={onSwitchDocMode}>{uiText("sheetWorkspace.editThisPage")}</button></div>;
  const attrs=parsed.table.attrs,types=attrs.column_types||[],columnIds=attrs.column_ids||[];
  const preferences=restoreViewPreferences(localPreference?.key===preferenceKey?localPreference.raw:storedPreference,parsed,productionSheet?'composer':'grid');
  const visibleColumns=parsed.headers.map((_,i)=>i).filter(c=>!hidden.includes(c));
  const isStatus=c=>types[c]==='status'||parsed.rows.some(row=>row.cells[c]?.kind==='status');
  // Untouched text columns flex to the canvas (88px floor); media, status, numbers and resized columns keep their width.
  const flexColumn=c=>!widths[c]&&!attrs.column_widths?.[columnIds[c]]&&!['number','formula','image','video','audio'].includes(types[c])&&!isStatus(c);
  const columnWidth=c=>widths[c]||attrs.column_widths?.[columnIds[c]]||(['number','formula'].includes(types[c])?110:isStatus(c)?144:['image','video'].includes(types[c])?140:/(日期|date)/i.test(parsed.headers[c])?120:/(備註|說明|prompt|內容|notes|description|content)/i.test(parsed.headers[c])?210:140);
  const statusValues=[...new Set(parsed.rows.flatMap(row=>row.cells.flatMap((cell,c)=>isStatus(c)&&cell.value?[cell.value]:[])))];
  const visibleRows=parsed.rows.filter(row=>(!productionSheet||!episodeRows||episodeRows.has(row.rid))&&(!statusFilter||row.cells.some((cell,c)=>isStatus(c)&&cell.value===statusFilter))&&(!query||row.cells.some(cell=>String(cell.value).toLocaleLowerCase().includes(query.toLocaleLowerCase()))));
  if(sort)visibleRows.sort((a,b)=>String(a.cells[sort.c]?.value??'').localeCompare(String(b.cells[sort.c]?.value??''),'zh-Hant',{numeric:true})*(sort.direction==='desc'?-1:1));
  const rowIndices=visibleRows.map(row=>parsed.rows.indexOf(row)),visibleIds=visibleRows.map(row=>row.rid);
  const range=selectionRange(anchor,active,rowIndices,visibleColumns);
  // SPEC_19 R7: on a production sheet a chosen shot opens on its composer; with no shot chosen yet the stage is the overview grid.
  const selectedRow=productionSheet?visibleRows.find(item=>item.rid===rowOpen)||null:null;
  const view=sheetViewModel(parsed,visibleRows,preferences,assetLookup),hasStage=parsed.headers.some(h=>/previs|blockout/i.test(h)),mode=viewMode(preferences.mode,{productionSheet,selected:Boolean(selectedRow),hasStage});
  const flows=tabs.filter(t=>t.surface_type==='flow');
  // SPEC_15 Shot Stage: on a production sheet the shot list and the current shot's detail stand beside every view
  // except the table, canvas and 3D stage (which carries its own list), and Review shows the current shot.
  const statusCol=view.statusColumns[0]?.index??-1,shotStatus=item=>statusCol<0?'':item.cells[statusCol]?.value||'';
  const actionCol=productionSheet?actionColumn(parsed.headers):-1;  // the prompt column: its @codes are the shot's cast (SPEC_18 R2, R3)
  const listedRows=productionSheet?visibleRows.filter(item=>SHOT_FILTERS[shotFilter]({status:shotStatus(item),info:shotInfo[item.rid],inFlight:inFlight.has(item.rid)})):visibleRows;
  const currentRow=productionSheet?(visibleRows.find(item=>item.rid===rowOpen)||listedRows[0]||visibleRows[0]||null):null;
  const studioRails=productionSheet&&!['grid','canvas','stage'].includes(mode);
  const reviewStage=item=>{const stages=mediaStages(parsed,item),stage=stages.find(s=>s.media&&s.type==='video')||stages.find(s=>s.media)||stages[0];return stage?{...stage.media,r:parsed.rows.indexOf(item),c:stage.column,label:stage.label,value:stage.value}:null;};
  const preview=previewState||(productionSheet&&mode==='review'&&currentRow?reviewStage(currentRow):null);
  const row=parsed.rows.find(r=>r.rid===rowOpen),previewRow=preview?.r==null?null:parsed.rows[preview.r];
  const contextRow=previewRow||row;
  const reviewSource=contextRow?{revision:tab.revision,status:contextRow.cells[view.statusColumns[0]?.index]?.value,
    mediaVersion:JSON.stringify(mediaStages(parsed,contextRow).map(stage=>[stage.column,stage.value]))}:undefined;
  const rowMediaCols=previewRow?mediaStages(parsed,previewRow):[];
  const previewAssets=previewRow?assetReferences(previewRow).map(id=>resolveAssetReference(id,assetLookup)):[];
  const previewCapability=(types[preview?.c]==='video'||preview?.kind==='video')?'video_gen':'image_gen';
  const previewTargetValid=!!previewRow&&Number.isInteger(preview?.c)&&preview.c>=0&&preview.c<parsed.headers.length;
  const messages=annotations.filter(a=>a.tab_key===tab.key&&a.anchor?.rid===contextRow?.rid).flatMap(a=>a.messages||[]);
  const imported=!!attrs.worksheet_name;
  const activeCell=parsed.rows[active.r]?.cells[active.c];
  const safeFocus={r:rowIndices.includes(active.r)?active.r:rowIndices[0],c:visibleColumns.includes(active.c)?active.c:visibleColumns[0]};
  const setView=change=>{const raw=JSON.stringify(viewPreferences(parsed,{...preferences,...change}));setLocalPreference({key:preferenceKey,raw});try{localStorage.setItem(preferenceKey,raw);}catch{/* optional view preference */}};
  const guardDraft=()=>{if(dirty||busy||pendingPaste){onError?.(busy?uiText("sheetWorkspace.waitForSavingToFinish"):uiText("sheetWorkspace.saveOrCancelTheDraftBeforeSwitchingExportingOr"));return false;}return true;};
  const switchDocument=()=>{if(guardDraft())onSwitchDocMode?.();};
  const downloadWorkbook=mode=>{if(guardDraft())run(()=>api.download(`/projects/api/${slug}/tabs/${tab.key}/export?format=xlsx${mode==='new_workbook'?'&mode=new_workbook':''}`,`${tab.title}${mode==='new_workbook'?uiText("sheetWorkspace.organized"):''}.xlsx`));};
  const closeSchema=()=>{if(busy)return;setSchemaPlan(null);setFailure(null);setSaveState("saved");};
  const closePaste=()=>{if(busy)return;setPendingPaste(null);setFailure(null);setSaveState("saved");};
  const focus=cell=>{setActive(cell);setAnchor(cell);requestAnimationFrame(()=>grid.current?.querySelector(`[data-cell="${cell.r}:${cell.c}"]`)?.focus());};
  const focusAfterEdit=cell=>{if(preview)reviewFocus.current?.focus();else focus(cell);};
  const closePanel=()=>{if(!guardDraft())return;setPanel(null);setPreview(null);setHistory(null);focus(active);};
  const fail=(error,retry=null)=>{setFailure({message:error.message,details:error.data,retry});setSaveState("unsaved");onError?.(error.message);};
  const run=async fn=>{
    if(busyRef.current)return false;busyRef.current=true;setBusy(true);
    try{await fn();return true;}catch(e){fail(e);return false;}finally{busyRef.current=false;setBusy(false);}
  };
  const refresh=async()=>{try{await onReloadTab();}catch(e){setFailure({message:uiText("sheetWorkspace.savedButTheViewHasNotRefreshed", {v0: (e.message)}),retry:onReloadTab});}};
  const submit=async(payload,{record=true}={})=>{
    if(busyRef.current)return false;busyRef.current=true;setBusy(true);setSaveState("saving");setFailure(null);
    try{
      const result=await api.post(`/projects/api/${slug}/tabs/${tab.key}/table-edit`,{...payload,base_revision:payload.base_revision??tab.revision});
      if(result.conflicts?.length){const error=new Error(uiText("sheetWorkspace.theContentChangedOrIsLockedYourDraftIs"));error.data=result;throw error;}
      if(record&&!payload.new_rows?.length){setUndo(old=>[...old.slice(-49),payload]);setRedo([]);}
      if(payload.new_rows?.length){setUndo([]);setRedo([]);}
      setSaveState("saved");await refresh();return true;
    }catch(e){fail(e,()=>submit(payload,{record}));setFailure(old=>({...old,draft:payload.row_edits?.map(row=>Object.values(row.cells).join(' / ')).join('；')}));if(e.status===409)await refresh();return false;}finally{busyRef.current=false;setBusy(false);}
  };
  const payloadCell=(r,c,value,base=parsed)=>visiblePastePayload(base,[base.rows[r].rid],{r,c},[[value]]);
  const commit=async(r,c,value)=>{try{return await submit(payloadCell(r,c,value));}catch(e){fail(e);return false;}};
  const beginEdit=(r,c,initial)=>{
    if(!writable||busy||dirty)return;const cell=parsed.rows[r]?.cells[c];if(!cell)return;
    setFailure(null);setActive({r,c});setAnchor({r,c});setText(initial??String(cell.value));setEditing({r,c,rid:parsed.rows[r].rid,value:cell.value,table:parsed,revision:tab.revision,selectAll:initial==null});setSaveState("editing");
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
        setEditing(null);setSaveState("saved");focusAfterEdit(key?nextPosition(current,key,back):current);
      }
    }catch(e){fail(e);}
  };
  const cancelEdit=()=>{if(busy)return;setEditing(null);setFailure(null);setSaveState("saved");focusAfterEdit(active);};
  const rebaseEdit=async()=>{
    try{const original=payloadCell(editing.r,editing.c,text,editing.table),updated=rebaseOperation(parsed,original);
      if(await submit(updated)){setEditing(null);focusAfterEdit({r:parsed.rows.findIndex(row=>row.rid===editing.rid),c:Number(Object.keys(updated.row_edits[0].cells)[0])});}
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
    if(['ArrowUp','ArrowDown','ArrowLeft','ArrowRight',uiText("sheetWorkspace.tab")].includes(e.key)){
      e.preventDefault();const next=nextPosition({r,c},e.key,e.shiftKey&&e.key==='Tab');setActive(next);if(!e.shiftKey||e.key==='Tab')setAnchor(next);requestAnimationFrame(()=>grid.current?.querySelector(`[data-cell="${next.r}:${next.c}"]`)?.focus());return;
    }
    if(e.key==='Escape'){setAnchor(active);return;}
    if(e.key==='Process'||e.keyCode===229){beginEdit(r,c,'');return;}
    if(e.key.length===1&&!e.ctrlKey&&!e.metaKey&&!e.altKey){e.preventDefault();beginEdit(r,c,e.key);}
  };
  const openRow=rid=>{if(dirty){fail(new Error(uiText("sheetWorkspace.saveOrCancelTheCurrentCellEditFirst")));return;}setRowOpen(rid);setPanel('row');setHistory(null);setComment('');if(productionSheet){const r=parsed.rows.findIndex(row=>row.rid===rid),stage=r>=0?mediaStages(parsed,parsed.rows[r])[0]:null;if(stage)showPreview({...stage.media,r,c:stage.column,label:stage.label,value:stage.value});}};
  const showHistory=async rid=>run(async()=>{const data=await api.get(`/projects/api/${slug}/history?tab=${encodeURIComponent(tab.key)}`);setHistory(historyForRow(data.groups||data.history||[],rid,parsed.tableId));});
  const showPreview=item=>{if(!guardDraft())return;setPreview(item);setRowOpen(parsed.rows[item.r]?.rid||null);setHistory(null);setPanel(null);setComment('');if(productionSheet&&mode!=='review')setView({mode:'review'});};
  const stepPreview=(direction,targetRid=null)=>{
    if(!previewTargetValid||!guardDraft())return;
    const at=visibleRows.findIndex(r=>r.rid===previewRow?.rid),target=targetRid?visibleRows.find(r=>r.rid===targetRid):visibleRows[at+direction];if(!target||target.rid===previewRow?.rid)return;
    const r=parsed.rows.indexOf(target),c=preview.c,media=mediaOf(target.cells[c]?.value,types[c]);
    setPreview({...(media||{}),r,c,label:parsed.headers[c],value:target.cells[c]?.value});setRowOpen(target.rid);setComment('');setHistory(null);onShotFocus?.(target.rid);
  };
  const ask=(ids=null,initial='',crew=false)=>{
    if(!guardDraft())return;
    try{const chosen=ids||(selected.size?[...selected]:range.rows.length?range.rows.map(r=>parsed.rows[r].rid):visibleIds);
      const columns=ids||selected.size?parsed.headers.map((_,i)=>i):range.columns.length?range.columns:visibleColumns;
      const scope=freezeSheetScope(tab,parsed,chosen,columns);setRequest({scope,table:parsed,title:tab.title,requestId:crypto.randomUUID(),crew});setInstruction(initial);setPanel(null);setPreview(null);
    }catch(e){fail(e);}
  };
  const toFlow=(ids,options={})=>{if(!guardDraft())return;try{if(!flows.length)throw new Error(uiText('studio.noPipeline'));sessionStorage.setItem(`openbench-selection:${slug}`,JSON.stringify({...freezeSheetScope(tab,parsed,ids),...options}));window.location.hash=workflow||flows[0].key;}catch(e){fail(e);}};
  const runInPlace=async(ids,options={})=>{
    if(!writable||!guardDraft()||busyRef.current)return;
    busyRef.current=true;setBusy(true);setFailure(null);
    try{
      const flowKey=workflow||flows[0]?.key;if(!flowKey)throw new Error(uiText('studio.noPipeline'));
      const base='/projects/api/'+slug+'/tabs/'+flowKey+'/flow';
      const saved=await api.get(base);
      const input=studioRunInput(saved,{tabKey:tab.key,tableId:parsed.tableId,columnIds,rowIds:ids,row:ids.length===1?parsed.rows.find(r=>r.rid===ids[0])?.cells.map(c=>c.value):undefined,...options});
      await queueStudioRun(api,base,input,{tabKey:tab.key,revision:tab.revision});
      setSaveState('saved');onToast?.(uiText(options.singleStep?'studio.queuedReview':'studio.queued'));
    }catch(error){fail(error,()=>toFlow(ids,options));}finally{busyRef.current=false;setBusy(false);}
  };
  const cycleVariant=async(row,oldId,nextId)=>{
    if(!writable||!guardDraft())return;
    let payload=null;
    row.cells.forEach((cell,c)=>{
      const next=replaceAssetVariant(cell.value,oldId,nextId);
      if(next===String(cell.value))return;
      const part=payloadCell(parsed.rows.indexOf(row),c,next);
      if(!payload)payload=part;
      else{Object.assign(payload.row_edits[0].cells,part.row_edits[0].cells);Object.assign(payload.row_edits[0].expected_cells,part.row_edits[0].expected_cells);}
    });
    if(payload)await submit(payload);
  };
  const rebuildScene=id=>{if(guardDraft())run(async()=>{await waitStoryTask(await storyRequest(`/scenes/${id}/shot-rebuilds`,'POST'));await refresh();});};
  const runStage=(rid,stage)=>runInPlace([rid],{singleStep:true,capability:stage.type==='video'?'video_gen':'image_gen',col_index:stage.column});
  const presetChips=(c,value,choose)=><div className="studio-presets">{presetsFor(parsed.headers[c],Object.keys(assetLookup)).map(preset=><button type="button" className="preset-chip" key={preset} disabled={busy||!writable||(dirty&&editing?.c!==c)} onClick={()=>choose(applyPreset(String(value||''),preset))}>{presetLabel(preset)}</button>)}</div>;

  const schema=async body=>run(async()=>{
    setSaveState("saving");const result=await api.post(`/projects/api/${slug}/tabs/${tab.key}/table-schema`,{table_id:parsed.tableId,expected_column_ids:columnIds,base_revision:tab.revision,...body});
    if(result.conflicts?.length){const error=new Error(uiText("sheetWorkspace.theColumnChangedYourSettingsDraftIsPreservedRefresh"));error.data=result;throw error;}
    setUndo([]);setRedo([]);setSchemaPlan(null);setColumnDraft(null);setSaveState("saved");await refresh();
  });
  const saveColumn=()=>{if(!columnDraft)return;const options=columnDraft.options.split(/\r?\n|、/).map(s=>s.trim()).filter(Boolean);if(columnDraft.type==='status'&&!options.length){fail(new Error(uiText("sheetWorkspace.addAtLeastOneStatusOption")));return;}setSchemaPlan({operation:'configure',column_id:columnIds[columnDraft.c],name:columnDraft.name,column_type:columnDraft.type,...(columnDraft.type==='status'?{options}:{})});setNewWorkbook(false);};
  const openColumn=c=>{if(!guardDraft())return;setColumnDraft({c,name:parsed.headers[c],type:types[c]||'text',options:statusOptions(parsed,c).join('\n')});setPanel("columns");setPreview(null);};
  // One path for every media write into a cell: store the asset, then commit the cell against the revision the user saw.
  // extra: more [file, column] pairs on the same row, committed in the same edit (the 3D stage's previs, actor matte and pose skeleton).
  const uploadToCell=async(file,target,extra=[])=>{try{setBusy(true);const stored=[];for(const [item,c] of [[file,target.c],...extra]){const result=await api.upload(`/projects/api/${slug}/assets`,item,item.name),kind=result.content_type.split('/')[0];stored.push({c,kind,url:result.src,value:kind==='image'?`![Image](${result.src})`:`[${kind}](${result.src})`});}setBusy(false);const payload=visiblePastePayload(target.table,[target.table.rows[target.r].rid],target,[stored.map(s=>s.value)],stored.map(s=>s.c));if(await submit({...payload,base_revision:target.revision})){const {kind,url,value}=stored[0];setPreview(current=>current?.r===target.r&&current?.c===target.c?{...current,url,kind,value}:current);setEditing(null);onToast?.(uiText('studio.mediaUpdated'));return true;}}catch(error){setBusy(false);fail(error);}return false;};
  // The 3D stage of the slate: "Block in 3D" on a shot opens it on that shot; a render writes the shot's Previs cell
  // (and Actor Matte). Run motion pass queues that one step; Run layout render queues Layout Key -> Layout Render.
  const [stageFocus,setStageFocus]=useState(null);
  const openStage=rid=>{if(!guardDraft())return;setPanel(null);setPreview(null);setHistory(null);setStageFocus({rid});setView({mode:'stage'});};
  const motionStage=shot=>runInPlace([shot.rid],{singleStep:true,capability:'video_gen',match:node=>node.id==='motion'||/previs motion/i.test(node.title||'')});
  const layoutStage=shot=>runInPlace([shot.rid],{capability:'image_gen',match:node=>node.id==='layoutkey'||/layout key/i.test(node.title||'')});
  const renderStage=(shot,blob,matte,skeleton)=>{const file=(data,stem)=>new File([data],`${stem}_${shot.shot||'shot'}.webm`,{type:'video/webm'});
    const extra=[[matte,'matte',shot.matteCol],[skeleton,'skeleton',shot.skeletonCol]].filter(([data,,c])=>data&&c>=0).map(([data,stem,c])=>[file(data,stem),c]);
    return uploadToCell(file(blob,'previs'),{r:shot.r,c:shot.previsCol,table:parsed,revision:tab.revision},extra);};
  const pickUpload=(r,c)=>{if(!writable||!guardDraft())return;uploadTarget.current={r,c,table:parsed,revision:tab.revision};upload.current?.click();};
  const exportCSV=()=>{if(!guardDraft())return;const url=URL.createObjectURL(new Blob([tableCSV(parsed)],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=`${tab.title}-${parsed.name}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
  const notesFor=rid=>rid?annotations.filter(a=>a.tab_key===tab.key&&a.anchor?.rid===rid).flatMap(a=>a.messages||[]):[];
  const postComment=rid=>rid&&run(async()=>{const result=await api.post(`/projects/api/${slug}/annotations`,{tab_key:tab.key,row:rid,body:comment,source_revision:tab.revision});setComment('');await refresh();if(result.annotation?.agent_request)onAgentRouted?.(result.annotation.agent_request);});
  // The row's comments and a box for a new one; the shot panel shows the shot's own row (its current shot), every other view the row it opened.
  const discussionFor=(rid,list=notesFor(rid))=><div className="sheet-discussion"><h3>{uiText("sheetWorkspace.discussion")}</h3>{list.length?list.map((m,i)=><p key={m.id||i}><strong>{m.name||m.actor_name}</strong> {m.body||m.new_value}</p>):<p className="sheet-subtle">{uiText("sheetWorkspace.noCommentsYet")}</p>}{writable&&rid&&<><textarea aria-label={uiText("sheetWorkspace.rowComment")} placeholder={uiText("sheetWorkspace.addProductionNotesForThisRow")} rows={3} value={comment} onChange={e=>setComment(e.target.value)}/><button disabled={busy||!comment.trim()} onClick={()=>postComment(rid)}>{uiText("sheetWorkspace.postComment")}</button></>}</div>;
  const discussion=discussionFor(contextRow?.rid,messages);
  const historyContent=history&&<div className="sheet-history"><h3>{uiText("sheetWorkspace.versionHistory")}</h3>{!history.length&&<p>{uiText("sheetWorkspace.noChangesRecordedForThisRow")}</p>}{history.map(g=><section key={g.id}><b>{g.name} · {shortTime(g.at)}</b>{g.changes.map((change,i)=>{
    const hasMedia=!!(change.media_before?.length||change.media_after?.length);
    const segments=(change.segments||[]).map(([kind,s],j)=>kind==='-'?<del key={j}>{s}</del>:kind==='+'?<ins key={j}>{s}</ins>:<span key={j}>{s}</span>);
    return <div className="history-row-change" key={i}>{change.tableWide&&<small>{uiText("sheetWorkspace.tableWideChanges")}</small>}<p>{change.label||change.title||uiText("sheetWorkspace.contentChanges")}</p>{!hasMedia&&segments}<div className="history-media">{[[uiText("sheetWorkspace.before"),change.media_before],[uiText("sheetWorkspace.after"),change.media_after]].map(([label,urls])=>urls?.length?<div key={label}><strong>{label}</strong>{urls.map(url=><MediaCell key={url} value={url} label={label} onLightbox={item=>showPreview({...item,r:preview?.r??(contextRow?parsed.rows.indexOf(contextRow):undefined),c:preview?.c})}/>)}</div>:null)}</div>{hasMedia&&<details className="history-field-diff"><summary>{uiText("sheetWorkspace.fullColumnChanges")}</summary>{segments}</details>}</div>;
  })}</section>)}</div>;

  // Shot Stage: one current shot across views. The list, up/down, A and R act on it; leaving Review drops its open stage.
  const pickShot=rid=>{if(!guardDraft())return;if(previewState&&visibleRows.some(item=>item.rid===rid))stepPreview(0,rid);else setRowOpen(rid);setStageFocus({rid});onShotFocus?.(rid);};
  const pickView=key=>{if(!guardDraft())return;if(key!=='review')setPreview(null);if(key==='stage'&&currentRow)setStageFocus({rid:currentRow.rid});if(key==='composer'&&!selectedRow&&currentRow)setRowOpen(currentRow.rid);setView({mode:key});};
  // A shot chosen from the overview (a card or the shot list) opens on its composer (R7); elsewhere choosing a shot keeps the view.
  const openShot=rid=>{if(!guardDraft())return;pickShot(rid);if(productionSheet&&mode==='gallery')setView({mode:'composer'});};
  const backToOverview=()=>{if(!guardDraft())return;setPreview(null);setView({mode:'gallery'});};
  // The shell's focus and this view's current shot are one thing: arrive on the shot you were on in another space, or report the one shown first.
  useEffect(()=>{
    if(!productionSheet||!onShotFocus||!visibleRows.length)return;
    if(shotFocus&&visibleRows.some(item=>item.rid===shotFocus)){if(currentRow?.rid!==shotFocus)pickShot(shotFocus);}
    else if(currentRow&&shotFocus!==currentRow.rid)onShotFocus(currentRow.rid);
  },[shotFocus,productionSheet,visibleRows.length,currentRow?.rid]);  // eslint-disable-line react-hooks/exhaustive-deps
  const setShotStatus=(item,value)=>statusCol>=0&&commit(parsed.rows.indexOf(item),statusCol,value);
  // R (SPEC_19 3.5): the shot goes to Retake and the focus to its prompt input, when one is on the page (the shot composer's, marked
  // data-shot-prompt with the row id); with none on the page only the status is written.
  const focusPrompt=item=>{if(productionSheet&&mode!=='composer'){setRowOpen(item.rid);setView({mode:'composer'});}
    requestAnimationFrame(()=>requestAnimationFrame(()=>document.querySelector(`[data-shot-prompt="${CSS.escape(item.rid)}"]`)?.focus()));};
  const retakeShot=async item=>{if(!writable||statusCol<0||!guardDraft())return;if(await setShotStatus(item,'Retake'))focusPrompt(item);};
  // "Reshoot with the new take" (SPEC_19 3.7) only opens the composer on the prompt; the reference resolves to the new adoption on send.
  const reshootShot=item=>{if(guardDraft())focusPrompt(item);};
  // SPEC_19 R9: the composer edits the prompt cell through the sheet's own draft (editing, marked source 'composer'), so every guard of a
  // cell draft holds (no shot switch, no adoption, no A/R over unsaved text) and saving is the same guarded cell edit. Typing back to
  // the saved text ends the draft.
  const draftComposer=(item,c,next)=>{
    if(!writable||c<0)return;
    const mine=editing?.source==='composer'&&editing.rid===item.rid&&editing.c===c;
    if(editing&&!mine&&dirty){fail(new Error(uiText("sheetWorkspace.saveOrCancelTheCurrentDraftFirst")));return;}
    const original=String(item.cells[c]?.value??'');
    if(next===original){if(editing){setEditing(null);setSaveState("saved");}return;}
    if(!mine){setFailure(null);setEditing({r:parsed.rows.indexOf(item),c,rid:item.rid,value:original,table:parsed,revision:tab.revision,source:'composer'});setSaveState("editing");}
    setText(next);
  };
  const saveComposer=async()=>{
    if(editing?.source!=='composer')return true;
    if(!dirty){setEditing(null);setSaveState("saved");return true;}
    const current=editing;let payload;
    try{payload={...payloadCell(current.r,current.c,text,current.table),base_revision:current.revision};}catch(e){fail(e);return false;}
    const ok=await submit(payload);if(ok){setEditing(null);setSaveState("saved");}return ok;
  };
  const revertComposer=()=>{if(busy||editing?.source!=='composer')return;setEditing(null);setFailure(null);setSaveState("saved");};
  // Generate from the composer: an unsaved prompt is saved first ("Save & generate"), so the takes are made from the text on screen; each
  // task the server creates (count 1-4) is followed until it ends, then the takes are read again.
  const followStory=(rid,tasks)=>{
    if(!tasks.length)return;
    setStoryRuns(old=>({...old,[rid]:(old[rid]||0)+tasks.length}));
    for(const task of tasks){
      const controller=new AbortController();storyWaits.current.add(controller);
      waitStoryTask(task,{signal:controller.signal}).catch(error=>{if(error?.name!=='AbortError')onError?.(uiText('composer.taskFailed',{message:error.message}));})
        .finally(()=>{storyWaits.current.delete(controller);if(controller.signal.aborted)return;
          setStoryRuns(old=>{const left=(old[rid]||1)-1,next={...old};if(left>0)next[rid]=left;else delete next[rid];return next;});setTakesNonce(n=>n+1);reload.current?.();});
    }
  };
  const generateShot=async(item,{output,body})=>{
    if(!writable)return false;
    if(editing&&editing.source!=='composer'){guardDraft();return false;}
    if(!(await saveComposer()))return false;
    let tasks=[];
    const ok=await run(async()=>{const result=await storyRequest(`/shots/${shotInfo[item.rid]?.shotId||storyShotId(slug,item.rid)}/${output==='frame'?'image':'video'}-generations`,'POST',body);
      tasks=Array.isArray(result?.tasks)?result.tasks:result?.taskId?[result]:[];});
    if(!ok)return false;
    followStory(item.rid,tasks);onToast?.(uiText('composer.queued',{count:tasks.length||body.count||1}));return true;
  };
  // A story write from the shot panel (adopt, un-adopt, first frame): never over an open cell draft, one write at a time, and the row is
  // reloaded afterwards instead of patched here (SPEC_19 1.2 B); an applied pipeline proposal also reloads the proposal list.
  const storyWrite=(fn,{proposals:reloadProposals=false}={})=>{if(!writable||!guardDraft())return Promise.resolve(false);
    return run(async()=>{try{await fn();}finally{await refresh();if(reloadProposals)await onReloadProposals?.();}});};
  const openInTable=(rid,c)=>{if(!guardDraft())return;const r=parsed.rows.findIndex(item=>item.rid===rid);setPreview(null);setView({mode:'grid'});if(r>=0)focus({r,c});};
  const stageKeys=e=>{
    if(!studioRails||!currentRow||editing||e.defaultPrevented||e.ctrlKey||e.metaKey||e.altKey||e.target.closest('input,textarea,select,video,[contenteditable=true]'))return;
    const key=e.key.toLowerCase();
    if(key==='escape'){if(composerControl.current?.escape()||filmControl.current?.escape())e.preventDefault();return;}
    if(key==='arrowdown'||key==='arrowup'){const next=listedRows[listedRows.findIndex(item=>item.rid===currentRow.rid)+(key==='arrowdown'?1:-1)];if(next){e.preventDefault();pickShot(next.rid);}return;}
    // A adopts (the take being tried, else the one playing, else the newest) and moves on; R sends the shot to Retake. Readers: neither.
    if((key==='a'||key==='r')&&writable&&!busy&&!dirty){
      if(key==='a'&&filmControl.current){e.preventDefault();filmControl.current.adopt();}
      else if(key==='r'&&statusCol>=0){e.preventDefault();retakeShot(currentRow);}
    }
  };
  // One shot's status, actions, prompt editors and discussion: the review aside and the Shot Stage detail.
  const shotControls=(r,target,col)=>{const valid=Number.isInteger(col)&&col>=0&&col<parsed.headers.length,capability=types[col]==='video'?'video_gen':'image_gen';
    return <>{view.statusColumns.map(({index,label})=><label className="modal-field" key={index}><span>{label}</span><select value={target.cells[index]?.value||''} disabled={!writable||busy||dirty} onChange={e=>commit(r,index,e.target.value)}><option value="">{uiText("sheetWorkspace.notConfigured")}</option>{statusOptions(parsed,index,target).map(s=><option key={s} value={s}>{statusLabel(s)}</option>)}</select></label>)}<div className="sheet-panel-actions"><button disabled={busy} onClick={()=>showHistory(target.rid)}>{uiText("sheetWorkspace.compareVersions")}</button>{writable&&valid&&<><button disabled={busy} onClick={()=>pickUpload(r,col)}>{uiText("sheetWorkspace.replaceUpload")}</button>{flows.length>0&&<button disabled={busy} onClick={()=>runInPlace([target.rid],{singleStep:true,capability:capability,col_index:col})}>{uiText("studio.reshoot")}</button>}{flows.length>0&&<button className="quiet" disabled={busy} onClick={()=>toFlow([target.rid],{capability:capability,col_index:col})}>{uiText("studio.openPipeline")}</button>}<button disabled={!onAskAgent} onClick={()=>ask([target.rid],`Use this row’s brief and references to propose image revisions for “${parsed.headers[col]}”.`)}>{uiText("sheetWorkspace.requestAgentRevisions")}</button></>}</div>{target.cells.map((cell,c)=>!['image','video','audio','status'].includes(types[c])&&/prompt|optical|rig|lens|camera|motion|movement|jutsu|mode|cast|reference|asset/i.test(parsed.headers[c])?<section className="review-presets" key={c}><strong>{parsed.headers[c]}</strong>
      {editing?.rid===target.rid&&editing.c===c?<><textarea ref={editor} aria-label={parsed.headers[c]} rows={4} value={text} disabled={busy} onChange={event=>setText(event.target.value)} onCompositionStart={()=>{composing.current=true;}} onCompositionEnd={()=>{composing.current=false;}} onKeyDown={event=>{event.stopPropagation();if(composing.current||event.nativeEvent.isComposing||event.keyCode===229)return;if(event.key==='Escape'){event.preventDefault();cancelEdit();}else if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();finishEdit();}}}/><small>{uiText('studio.editHint')}</small>{presetChips(c,text,setText)}<div className="sheet-panel-actions"><button disabled={busy} onClick={()=>finishEdit()}>{uiText('sheetWorkspace.save')}</button><button disabled={busy} onClick={cancelEdit}>{uiText('sheetWorkspace.cancel')}</button>{failure&&<button disabled={busy} onClick={rebaseEdit}>{uiText('sheetWorkspace.retryWithMyContent')}</button>}</div></>:<><small>{c===actionCol&&cell.value?<BindingText text={cell.value} lookup={assetLookup} onOpen={onOpenWorld}/>:cell.value||uiText('sheetWorkspace.notFilledIn')}</small>{writable&&<button disabled={busy||dirty} onClick={()=>beginEdit(r,c)}>{uiText('sheetWorkspace.edit')}</button>}</>}
    </section>:null)}{discussion}</>;};
  const review=preview&&<SheetReview onClose={productionSheet?backToOverview:closePanel} onStep={stepPreview}><header><button ref={reviewFocus} onClick={productionSheet?backToOverview:closePanel}>{productionSheet?uiText("stage.view_gallery"):uiText("sheetWorkspace.backToTable")}</button><h2>{previewRow?.cells[0]?.value||preview.label||uiText("sheetWorkspace.assetReview")}</h2><span className="spacer"/><button aria-label={uiText("sheetWorkspace.previousAsset")} disabled={!previewTargetValid||visibleRows.findIndex(r=>r.rid===previewRow?.rid)<=0} onClick={()=>stepPreview(-1)}>{uiText("sheetWorkspace.previous")}</button><button aria-label={uiText("sheetWorkspace.nextAsset")} disabled={!previewTargetValid||visibleRows.findIndex(r=>r.rid===previewRow?.rid)>=visibleRows.length-1||!previewRow} onClick={()=>stepPreview(1)}>{uiText("sheetWorkspace.next")}</button></header><div className="sheet-review-body"><div className="sheet-review-image">{rowMediaCols.length>1?<ShotBench stages={rowMediaCols} assets={previewAssets} activeColumn={preview.c} writable={writable} busy={busy} onSelect={stage=>setPreview({...stage.media,r:preview.r,c:stage.column,label:stage.label,value:stage.value})} onUpload={stage=>pickUpload(preview.r,stage.column)} onPrevis={()=>openStage(previewRow.rid)} onRun={stage=>runStage(previewRow.rid,stage)} onBundle={stage=>run(()=>api.download(`${stage.media.url}/bundle`,`${previewRow.cells[0]?.value||'take'}-take-bundle.zip`))}/>:preview.url?<MediaCell value={previewRow?.cells[preview.c]?.value||preview.value||preview.url} type={types[preview.c]||preview.kind} label={preview.label}/>:<p>{uiText('studio.emptyStage')}</p>}{productionSheet&&previewRow&&<ShotProduction key={previewRow.rid} slug={slug} actorId={me?.actor_id} rid={previewRow.rid} source={reviewSource} writable={writable} disabled={busy||dirty} beforeRun={guardDraft} onChanged={refresh}/>}{historyContent}</div>{!productionSheet&&<aside><h3>{preview.label}</h3>{failure&&<p className="sheet-save-error" role="alert">{failure.message}</p>}{previewRow&&shotControls(preview.r,previewRow,preview.c)}</aside>}</div>{!productionSheet&&visibleRows.length>1&&<ShotStrip rows={visibleRows} parsed={parsed} currentRid={previewRow?.rid} onJump={rid=>stepPreview(0,rid)}/>}</SheetReview>;
  // SPEC_19 R3: the current shot's right column is the shot in the cut (ShotFilmPanel): no approve button, the ✓ on a take adopts it.
  // Status and the less frequent actions live in its "…" menu; the prompt, camera and cast are edited in the shot composer (R8, R9).
  const shotDetail=studioRails&&currentRow&&(()=>{
    const r=parsed.rows.indexOf(currentRow),info=shotInfo[currentRow.rid],status=shotStatus(currentRow),missing=info?.readiness?.missingAssets||[];
    const shotCol=parsed.headers.findIndex(h=>/cinema shot|remaster|output/i.test(h)),col=previewRow?.rid===currentRow.rid?preview.c:Math.max(shotCol,0);
    const valid=Number.isInteger(col)&&col>=0&&col<parsed.headers.length,capability=types[col]==='video'?'video_gen':'image_gen';
    const film=inSlateOrder(Object.values(shotInfo).filter(item=>item.tabKey===tab.key));
    return <ShotFilmPanel slug={slug} tabKey={tab.key} rid={currentRow.rid} shot={info||null} shots={film} label={String(currentRow.cells[0]?.value||'—')}
      sceneTitle={storyScenes.find(scene=>scene.sceneId===info?.sceneId)?.title} status={status} proposals={proposals} version={`${tab.revision}:${takesNonce}`} inFlight={inFlight}
      writable={writable} disabled={busy||dirty} canStatus={statusCol>=0} hasFrame={parsed.headers.some(h=>/keyframe|reference.*image|anchor/i.test(h))} controlRef={filmControl}
      onWrite={storyWrite} onStatus={value=>setShotStatus(currentRow,value)} onRetake={()=>retakeShot(currentRow)} onReshoot={()=>reshootShot(currentRow)} onPick={pickShot}
      onTimeline={()=>{if(guardDraft())window.location.hash=TIMELINE_VIEW;}}
      onApplyProposal={onApplyProposal} onDismissProposal={onDismissProposal} onShowStage={hasStage?()=>pickView('stage'):undefined}
      menu={{table:()=>openInTable(currentRow.rid,actionCol>=0?actionCol:0),compare:()=>showHistory(currentRow.rid),upload:valid?()=>pickUpload(r,col):undefined,
        reshoot:flows.length>0&&valid?()=>runInPlace([currentRow.rid],{singleStep:true,capability,col_index:col}):undefined,
        pipeline:flows.length>0&&valid?()=>toFlow([currentRow.rid],{capability,col_index:col}):undefined,
        agent:onAskAgent&&valid?()=>ask([currentRow.rid],`Use this row’s brief and references to propose image revisions for “${parsed.headers[col]}”.`):undefined}}
      top={<><ShotSourceBadge alignment={writingAlignment} shotId={info?.shotId} onSource={onOpenSource}/>
        {missing.length>0&&<p className="shot-missing">{uiText('stage.missing',{codes:missing.map(code=>'@'+code).join(', ')})}{onOpenWorld&&<button type="button" className="quiet" onClick={()=>onOpenWorld(missing[0])}>{uiText('stage.addReferences')}</button>}</p>}</>}
      failure={failure&&<p className="sheet-save-error" role="alert">{failure.message}</p>}
      notes={{messages:notesFor(currentRow.rid),node:discussionFor(currentRow.rid)}}
      history={mode!=='review'&&historyContent}
      crewTools={<>{tab.key==='cinema-studio'&&<PreproductionPanel compact slug={slug} epId={epId} writable={writable} shots={parsed.rows.length}/>}{/* SPEC_20 R25: the card after the storyboard is built */}
        <CrewAsk slug={slug} shotId={info?.shotId||storyShotId(slug,currentRow.rid)} writable={writable} disabled={busy||dirty} onProposed={onReloadProposals}/></>}/>;
  })();

  // The overview's cover and grouping columns: the foot of the View menu on a production sheet, their own row elsewhere.
  const cardSettings=<>{view.coverColumns.length>0&&<label>{uiText("sheetWorkspace.cover")}<select aria-label={uiText("sheetWorkspace.cardCoverColumn")} value={view.coverColumn} onChange={e=>setView({coverColumn:Number(e.target.value)})}><option value={-1}>{uiText("sheetWorkspace.none")}</option>{view.coverColumns.map(c=><option key={c.index} value={c.index}>{c.label}</option>)}</select></label>}{view.statusColumns.length>0&&<label>{uiText("sheetWorkspace.group")}<select aria-label={uiText("sheetWorkspace.boardGroupingColumn")} value={view.groupColumn} onChange={e=>setView({groupColumn:Number(e.target.value)})}>{view.statusColumns.map(c=><option key={c.index} value={c.index}>{c.label}</option>)}</select></label>}<small>{uiText("sheetWorkspace.viewSettingsApplyToThisBrowserOnly")}</small></>;
  // SPEC_19 R7: the Shot Stage's views, the composer first (it is the default once a shot is chosen).
  const stageViews=[{key:'composer',label:uiText('composer.view_composer'),icon:'sparkle'},{key:'gallery',label:uiText('stage.view_gallery'),icon:'board'},
    ...(hasStage?[{key:'stage',label:uiText('previs.stage'),icon:'cube'}]:[]),{key:'review',label:uiText('stage.view_review'),icon:'play'},
    ...(hasStage?[{key:'compare',label:uiText('stage.view_compare'),icon:'layers'}]:[]),{key:'grid',label:uiText("sheetWorkspace.table"),icon:'table'},
    {key:'canvas',label:uiText('sheetWorkspace.canvas'),icon:'flow'},{key:'kanban',label:uiText("sheetWorkspace.board"),icon:'board'}];
  // SPEC_19 R8, R9: the chosen shot's composer. The prompt is the Action & Audio Prompt cell (its draft while one is open), the camera
  // the Optical Rig cell (written at once, undone with the sheet's undo); generating goes through generateShot.
  const composer=productionSheet&&mode==='composer'&&currentRow&&(()=>{
    const r=parsed.rows.indexOf(currentRow),info=shotInfo[currentRow.rid],scene=storyScenes.find(item=>item.sceneId===info?.sceneId);
    const rigCol=parsed.headers.findIndex(h=>/optical|rig/i.test(h)),motionCol=parsed.headers.findIndex(h=>/camera.*motion/i.test(h));
    const mine=editing?.source==='composer'&&editing.rid===currentRow.rid,cell=actionCol>=0?String(currentRow.cells[actionCol]?.value??''):'';
    return <ShotComposer slug={slug} tabKey={tab.key} rid={currentRow.rid} shot={info||null} shots={inSlateOrder(Object.values(shotInfo).filter(item=>item.tabKey===tab.key))}
      label={String(currentRow.cells[0]?.value||'—')} scene={scene?{index:scene.sceneIndex,title:scene.title}:null} status={shotStatus(currentRow)}
      text={mine?text:cell} dirty={mine&&dirty} promptColumn={actionCol>=0} onDraft={next=>draftComposer(currentRow,actionCol,next)} onSave={saveComposer} onRevert={revertComposer}
      rig={{text:rigCol>=0?String(currentRow.cells[rigCol]?.value??''):'',column:rigCol>=0,onWrite:next=>{if(rigCol>=0)commit(r,rigCol,next);}}}
      motionText={motionCol>=0?String(currentRow.cells[motionCol]?.value??''):''} undo={{can:undo.length>0&&!editing&&!busy,run:()=>travelHistory('undo')}}
      ladder={mediaLadder(parsed,currentRow)} lookup={assetLookup} headers={parsed.headers} cells={currentRow.cells} actionCol={actionCol}
      proposals={proposals} version={`${tab.revision}:${takesNonce}`} inFlight={inFlight.has(currentRow.rid)} generating={storyRuns[currentRow.rid]||0}
      writable={writable} disabled={busy} canStatus={statusCol>=0} controlRef={composerControl}
      onWrite={storyWrite} onRetake={()=>retakeShot(currentRow)} onShowStage={hasStage?()=>pickView('stage'):undefined} onOpenWorld={onOpenWorld}
      onGenerate={payload=>generateShot(currentRow,payload)}/>;
  })();

  return <section className="canvas sheet-canvas sheet-v2 sheet-workspace" onPaste={paste} onCopy={copy} onKeyDown={productionSheet?stageKeys:undefined}>
    <header className="sheet-workspace-heading"><h1>{tab.title}</h1><span className="sheet-count">{uiText("sheetWorkspace.rows", {v0: (parsed.rows.length)})}</span><div className="sheet-save-state" role="status">{busy?uiText("sheetWorkspace.saving"):dirty?uiText("sheetWorkspace.notSubmitted"):uiText("sheetWorkspace." + saveState)}</div><button aria-label={uiText("sheetWorkspace.undoCellEdit")} title={uiText("sheetWorkspace.undoCtrlZ")} disabled={!undo.length||busy||!!editing} onClick={()=>travelHistory('undo')}>↶</button><button aria-label={uiText("sheetWorkspace.redoCellEdit")} title={uiText("sheetWorkspace.redoCtrlShiftZ")} disabled={!redo.length||busy||!!editing} onClick={()=>travelHistory('redo')}>↷</button><details className="sheet-more"><summary aria-label={uiText("sheetWorkspace.moreTableActions")}>⋯</summary><div className="sheet-dropdown"><button disabled={busy||dirty} onClick={switchDocument}>{uiText("sheetWorkspace.documentAnnotations")}</button><button disabled={busy||dirty} onClick={()=>downloadWorkbook("original_patch")}>{uiText("sheetWorkspace.exportExcelPreserveSourceFormat")}</button><button disabled={busy||dirty} onClick={()=>downloadWorkbook("new_workbook")}>{uiText("sheetWorkspace.saveAsNewWorkbook")}</button><button disabled={busy||dirty} onClick={exportCSV}>{uiText("sheetWorkspace.exportWorksheetCSV")}</button><button disabled={busy} onClick={()=>run(()=>api.download(`/projects/api/${slug}/takes/export`,`${slug}-approved-takes.zip`))}>{uiText("sheetWorkspace.exportApprovedTakes")}</button></div></details></header>
    {tables.length>1&&<div className="sheet-tabs" role="tablist">{tables.map(t=><button role="tab" key={t.tableId} aria-selected={t.tableId===parsed.tableId} disabled={busy||dirty||!!pendingPaste} onClick={()=>{setEditing(null);setTableId(t.tableId);}}>{t.name}</button>)}</div>}
    <div className="sheet-workspace-toolbar">{productionSheet?<StageViewMenu views={stageViews} mode={mode} disabled={dirty} onPick={pickView} settings={['gallery','kanban'].includes(mode)?cardSettings:null}/>
      :<div className="sheet-view-switch" role="group" aria-label={uiText("sheetWorkspace.tableView")}>{[['grid',uiText("sheetWorkspace.table")],...(hasStage?[['stage',uiText('previs.stage')]]:[]),['gallery',uiText("sheetWorkspace.gallery")],['kanban',uiText("sheetWorkspace.board"),true]].map(([key,label,quiet])=><button key={key} className={quiet?'quiet-view':undefined} aria-pressed={mode===key} disabled={dirty} onClick={()=>pickView(key)}>{label}</button>)}</div>}
      <input className="sheet-search" aria-label={uiText("sheetWorkspace.searchTable")} placeholder={uiText("sheetWorkspace.search")} value={query} disabled={dirty} onChange={e=>{setQuery(e.target.value);setSelected(new Set());setAnchor({r:-1,c:-1});}}/>
      {!!statusValues.length&&<select aria-label={uiText("sheetWorkspace.filterByStatus")} value={statusFilter} disabled={dirty} onChange={e=>{setStatusFilter(e.target.value);setSelected(new Set());setAnchor({r:-1,c:-1});}}><option value="">{uiText("sheetWorkspace.allStatuses")}</option>{statusValues.map(s=><option key={s} value={s}>{statusLabel(s)}</option>)}</select>}
      {(query||statusFilter)&&<button className="quiet" onClick={()=>{setQuery('');setStatusFilter('');}}>{uiText("sheetWorkspace.clearFiltersRows", {v0: (visibleRows.length)})}</button>}
      {sort&&<button className="quiet" onClick={()=>setSort(null)}>{uiText("sheetWorkspace.clearSorting")}</button>}
      <span className="spacer"/><button disabled={busy||dirty} onClick={()=>{setColumnDraft(null);setPanel(panel==='columns'?null:'columns');}}>{uiText("sheetWorkspace.column", {v0: (hidden.length?` · hidden ${hidden.length}`:'')})}</button>
      {writable&&<><button disabled={busy||dirty} onClick={()=>{if(productionSheet&&epId!==episodeId(slug)){if(!storyScenes[0]){onError?.(uiText('story.confirmScript'));return;}run(async()=>{await storyRequest(`/scenes/${storyScenes[0].sceneId}/shots`,'POST');await refresh();});return;}const payload=tableEditPayload(parsed,parsed.rows.length,0,[parsed.headers.map(()=>'')]);if(imported){setSchemaPlan({addRow:payload});setNewWorkbook(false);}else submit(payload);}}>{uiText("sheetWorkspace.row")}</button>{onAskAgent&&<button className={productionSheet?undefined:"primary"} disabled={!visibleRows.length||dirty} onClick={()=>productionSheet?ask(selected.size?[...selected]:visibleIds,uiText('studio.crewFillBrief'),true):ask()}>{productionSheet?uiText('studio.crewFill'):uiText("sheetWorkspace.assignToAgent")}</button>}</>}
    </div>
    {!productionSheet&&['gallery','kanban'].includes(mode)&&<div className="sheet-card-settings">{cardSettings}</div>}
    {productionSheet&&<StoryBatchBar slug={slug} epId={epId} rowIds={[...selected]} writable={writable} disabled={busy||dirty||!!pendingPaste} beforeRun={guardDraft} onChanged={refresh}/>}
    {selected.size>0&&<div className="batch-bar"><b>{uiText("sheetWorkspace.selectedRows", {v0: (selected.size)})}</b>{productionSheet&&mode==='gallery'&&<AdoptLatestButton slug={slug} tabKey={tab.key} rowIds={[...selected]} shotInfo={shotInfo} proposals={proposals} writable={writable} disabled={busy||dirty} onWrite={storyWrite}/>}<button disabled={!onAskAgent||!writable} onClick={()=>ask([...selected])}>{uiText("sheetWorkspace.assignToAgent")}</button>{flows.length>0&&<><select aria-label={uiText("sheetWorkspace.selectAPipeline")} value={workflow||flows[0].key} onChange={e=>setWorkflow(e.target.value)}>{flows.map(t=><option key={t.key} value={t.key}>{t.title}</option>)}</select><button disabled={!writable||busy||dirty||selected.size>200} onClick={()=>runInPlace([...selected])}>{uiText("sheetWorkspace.runPipeline")}</button><button className="quiet" disabled={busy||dirty} onClick={()=>toFlow([...selected])}>{uiText("studio.configurePipeline")}</button></>}<button className="quiet" onClick={()=>setSelected(new Set())}>{uiText("sheetWorkspace.deselect")}</button></div>}
    {failure&&<div className="sheet-save-error" role="alert"><strong>{failure.message}</strong>{failure.draft&&!editing&&<span>{uiText("sheetWorkspace.preservedDraft", {v0: (failure.draft.slice(0,250))})}</span>}{editing&&<span>{uiText("sheetWorkspace.myContentCurrentContent", {v0: (text.slice(0,180)), v1: (String(parsed.rows.find(r=>r.rid===editing.rid)?.cells[editing.c]?.value??'').slice(0,180))})}</span>}{failure.details?.conflicts&&<details><summary>{uiText("sheetWorkspace.reviewConflict")}</summary><pre>{JSON.stringify(failure.details.conflicts,null,2)}</pre></details>}<div>{editing?<><button disabled={busy} onClick={()=>finishEdit()}>{uiText("sheetWorkspace.retrySave")}</button><button disabled={busy} onClick={rebaseEdit}>{uiText("sheetWorkspace.retryWithMyContent")}</button><button disabled={busy} onClick={cancelEdit}>{uiText("sheetWorkspace.discardThisEdit")}</button></>:failure.retry&&<button disabled={busy} onClick={failure.retry}>{uiText("sheetWorkspace.retry")}</button>}<button disabled={busy} onClick={()=>run(refresh)}>{uiText("sheetWorkspace.reloadCurrentContent")}</button><button onClick={()=>setFailure(null)}>{uiText("sheetWorkspace.collapse")}</button></div></div>}
    {taskError&&<p className="sheet-task-warning" role="status">{uiText("sheetWorkspace.taskStatusCouldNotRefresh", {v0: (taskError)})}</p>}
    {editing&&editing.source!=='composer'&&<div className="sheet-edit-strip"><b>{columnName(editing.c)}{editing.r+1} · {parsed.headers[editing.c]}</b><span>{uiText("sheetWorkspace.enterNextRowTabNextColumnShiftEnterNew")}</span><button disabled={busy} onClick={()=>finishEdit()}>{uiText("sheetWorkspace.save")}</button><button disabled={busy} onClick={cancelEdit}>{uiText("sheetWorkspace.cancel")}</button>{presetChips(editing.c,text,setText)}</div>}
    <div className={`sheet-workspace-body${panel?' has-panel':''}${studioRails?' studio-rails':''}`}>
      {studioRails&&<ShotList parsed={parsed} rows={visibleRows} statusColumn={statusCol} shotInfo={shotInfo} scenes={storyScenes} currentRid={currentRow?.rid} filter={shotFilter} onFilter={setShotFilter} onPick={openShot} inFlight={inFlight}/>}
      <div className="sheet-main-view">
        {mode==='grid'?<div className="sheet-scroll" ref={grid}><table className="production-sheet" role="grid" aria-label={parsed.name} aria-rowcount={visibleRows.length+1} style={{width:`max(100%, ${visibleColumns.reduce((n,c)=>n+(flexColumn(c)?88:columnWidth(c)),112)}px)`}}><colgroup><col style={{width:32}}/><col style={{width:36}}/>{visibleColumns.map(c=><col key={c} style={flexColumn(c)?undefined:{width:columnWidth(c)}}/>)}<col style={{width:44}}/></colgroup><thead><tr><th className="select-col"><input type="checkbox" aria-label={uiText("sheetWorkspace.selectAllVisibleRows")} checked={visibleRows.length>0&&visibleRows.every(r=>selected.has(r.rid))} onChange={e=>setSelected(e.target.checked?new Set(visibleIds):new Set())}/></th><th className="row-number">#</th>{visibleColumns.map(c=><th key={columnIds[c]||c}><button className="sheet-column-trigger" disabled={busy||dirty} aria-label={uiText("sheetWorkspace.configureColumn", {v0: (parsed.headers[c])})} onClick={()=>openColumn(c)}><span className="column-letter">{columnName(c)}</span><span>{parsed.headers[c]}</span>{sort?.c===c?<span>{sort.direction==='asc'?'↑':'↓'}</span>:<span className="column-chevron">⌄</span>}</button></th>)}<th className="row-actions">{uiText("sheetWorkspace.details")}</th></tr></thead><tbody>{visibleRows.map(item=>{
          const r=parsed.rows.indexOf(item);
          return <tr key={item.rid} className={selected.has(item.rid)?'selected-row':''}><td className="select-col"><input type="checkbox" aria-label={uiText("sheetWorkspace.selectRowRows", {v0: (r+1)})} checked={selected.has(item.rid)} onChange={e=>setSelected(old=>{const next=new Set(old);if(e.target.checked)next.add(item.rid);else next.delete(item.rid);return next;})}/></td><td className="row-number">{r+1}</td>{visibleColumns.map(c=>{
            const cell=item.cells[c]||{value:''},media=mediaOf(cell.value,types[c]),isEditing=editing?.rid===item.rid&&editing.c===c,inRange=range.rows.includes(r)&&range.columns.includes(c);
            return <td key={columnIds[c]||c} role="gridcell" aria-selected={inRange} aria-label={uiText("sheetWorkspace.message", {v0: (columnName(c)), v1: (r+1), v2: (parsed.headers[c])})} data-cell={`${r}:${c}`} tabIndex={r===safeFocus.r&&c===safeFocus.c?0:-1} className={`${inRange?'range-cell ':''}${active.r===r&&active.c===c?'active-cell ':''}${isEditing?'editing-cell':''}`}
              onFocus={e=>{if(e.target!==e.currentTarget)return;setActive({r,c});if(!range.rows.length)setAnchor({r,c});}} onMouseDown={e=>{if(e.button!==0||editing||e.target.closest('button,select,input,textarea'))return;dragging.current=true;if(!e.shiftKey)setAnchor({r,c});setActive({r,c});e.currentTarget.focus();}}
              onMouseEnter={e=>{if(dragging.current&&e.buttons===1&&!editing)setActive({r,c});}}
              onDoubleClick={()=>{if(!media)beginEdit(r,c);}} onKeyDown={e=>keyCell(e,r,c)}>
              {isEditing?<textarea ref={editor} className="sheet-inline-editor" aria-label={uiText("sheetWorkspace.cellContentOrFormula")} value={text} disabled={busy} onChange={e=>setText(e.target.value)} onCompositionStart={()=>{composing.current=true;}} onCompositionEnd={()=>{composing.current=false;}} onKeyDown={e=>{
                e.stopPropagation();if(composing.current||e.nativeEvent.isComposing||e.keyCode===229)return;
                if(e.key==='Escape'){e.preventDefault();cancelEdit();}else if(e.key==='Tab'||(e.key==='Enter'&&!e.shiftKey)){e.preventDefault();finishEdit(e.key,e.shiftKey);}
              }}/>:media?<MediaCell compact value={cell.value} type={types[c]} label={parsed.headers[c]} onLightbox={item=>showPreview({...item,r,c})}/>:['image','video','audio'].includes(types[c])&&writable?<button className="cell-upload-btn" disabled={busy||dirty} onClick={()=>pickUpload(r,c)}>{uiText('studio.uploadSource')}</button>:isStatus(c)?<select aria-label={uiText("sheetWorkspace.row2", {v0: (r+1), v1: (parsed.headers[c])})} className={`cell-status ${statusClass(cell.value)==='done'?'done':''}`} value={cell.value||''} disabled={!writable||busy||dirty} onChange={e=>commit(r,c,e.target.value)}><option value="" disabled={cell.kind==='status'}>{uiText("sheetWorkspace.notConfigured")}</option>{statusOptions(parsed,c,item).map(value=><option key={value} value={value}>{statusLabel(value)}</option>)}</select>:<span className={`cell-text ${String(cell.value).startsWith('=')?'formula-result':''}`} title={cell.value}>{evaluate(cell.value,parsed.rows,new Set(),imported?(attrs.source_header_row||1):0)||<span className="empty-cell">—</span>}</span>}
            </td>;
          })}<td className="row-actions"><button aria-label={uiText("sheetWorkspace.rowDetails", {v0: (r+1)})} onClick={()=>openRow(item.rid)}>↗</button>{locks.some(lock=>lock.tab_key===tab.key&&[item.rid,parsed.tableId].includes(lock.unit_id))&&<small title={uiText("sheetWorkspace.anotherCrewMemberIsEditingThisRow")}>{uiText("sheetWorkspace.locked")}</small>}</td></tr>;
        })}</tbody></table>{!visibleRows.length&&<div className="sheet-empty"><p>{query||statusFilter?uiText("sheetWorkspace.noMatchingRows"):uiText("sheetWorkspace.startWithTheFirstRow")}</p><small>{query||statusFilter?uiText("sheetWorkspace.clearFiltersOrTryAnotherSearch"):uiText("sheetWorkspace.chooseRowToAddDataThenPasteFromExcel")}</small></div>}</div>
          :mode==='kanban'&&view.groupColumn<0?<div className="sheet-empty"><h2>{uiText("sheetWorkspace.configureAStatusColumn")}</h2><p>{uiText("sheetWorkspace.setAColumnSTypeToStatusToGroup")}</p><button onClick={()=>setPanel('columns')}>{uiText("sheetWorkspace.configureColumn2")}</button></div>
          :!visibleRows.length?<div className="sheet-empty"><p>{uiText("sheetWorkspace.noMatchingRows")}</p></div>:mode==='composer'&&composer?composer:mode==='review'?review:mode==='compare'?<ShotCompare parsed={parsed} row={currentRow}/>:mode==='canvas'?<StoryCanvas storageKey={'zf.canvas:'+slug+':'+tab.key} model={view} parsed={parsed} scenes={storyScenes} title={tab.title} writable={writable} busy={busy||dirty} onOpen={openRow} onPreview={showPreview} onCommit={(rid,c,value)=>commit(parsed.rows.findIndex(r=>r.rid===rid),c,value)} onUpload={pickUpload} onRunStep={runStage}/>:mode==='stage'?<Suspense fallback={null}><PrevisStage slug={slug} tabKey={tab.key} proposals={proposals} onApplyProposal={onApplyProposal} onDismissProposal={onDismissProposal} shots={stageShots(parsed,visibleRows,assetLookup,shotInfo)} focus={stageFocus} writable={writable} busy={busy||dirty} onRender={renderStage} onMotion={motionStage} onLayout={layoutStage} onShot={productionSheet?(rid=>{setRowOpen(rid);onShotFocus?.(rid);}):undefined}/></Suspense>:<SheetCards model={view} mode={mode} parsed={parsed} selected={selected} onSelect={(rid,checked)=>setSelected(old=>{const next=new Set(old);if(checked)next.add(rid);else next.delete(rid);return next;})} onOpen={studioRails?openShot:openRow} onPreview={showPreview} onStatus={(rid,c,value)=>commit(parsed.rows.findIndex(r=>r.rid===rid),c,value)} writable={writable} busy={busy||dirty} onUpload={pickUpload} onRunStep={runStage} onVariant={cycleVariant} scenes={storyScenes} shotInfo={shotInfo} onRebuildScene={rebuildScene} compact={studioRails} current={studioRails?currentRow?.rid:null}/>}
      </div>
      {panel?<aside className="sheet-side-panel" aria-label={panel==='columns'?uiText("sheetWorkspace.columnSettings"):uiText("sheetWorkspace.rowDetails2")}><header><h2>{panel==='columns'?uiText("sheetWorkspace.columnSettings"):row?.cells[0]?.value||uiText("sheetWorkspace.rowDetails2")}</h2><button aria-label={uiText("sheetWorkspace.closeSidebar")} onClick={closePanel}>×</button></header>
        {panel==='columns'?<><p className="sheet-subtle">{uiText("sheetWorkspace.sortingVisibilityAndWidthAffectThisViewOnly")}</p><div className="sheet-columns-nav">{parsed.headers.map((name,c)=><button key={c} className={columnDraft?.c===c?'active':''} onClick={()=>openColumn(c)}>{name}{hidden.includes(c)?uiText("sheetWorkspace.hidden"):''}</button>)}</div>{columnDraft&&<div className="sheet-column-form"><label>{uiText("sheetWorkspace.columnName")}<input aria-label={uiText("sheetWorkspace.columnName")} value={columnDraft.name} disabled={!writable} onChange={e=>setColumnDraft({...columnDraft,name:e.target.value})}/></label><label>{uiText("sheetWorkspace.contentType")}<select aria-label={uiText("sheetWorkspace.columnType")} value={columnDraft.type} disabled={!writable} onChange={e=>setColumnDraft({...columnDraft,type:e.target.value})}>{Object.entries(TYPES).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>{columnDraft.type==='status'&&<label>{uiText("sheetWorkspace.statusOptionsOnePerLine")}<textarea aria-label={uiText("sheetWorkspace.statusOptions")} rows={5} value={columnDraft.options} disabled={!writable} onChange={e=>setColumnDraft({...columnDraft,options:e.target.value})}/></label>}<button className="primary" disabled={!writable||busy||!columnDraft.name.trim()} onClick={saveColumn}>{uiText("sheetWorkspace.applyColumnSettings")}</button><hr/><div className="sheet-panel-actions"><button onClick={()=>setSort({c:columnDraft.c,direction:'asc'})}>{uiText("sheetWorkspace.sortAscending")}</button><button onClick={()=>setSort({c:columnDraft.c,direction:'desc'})}>{uiText("sheetWorkspace.sortDescending")}</button></div><label>{uiText("sheetWorkspace.width")}<input type="number" aria-label={uiText("sheetWorkspace.columnWidth")} min={80} max={600} value={columnWidth(columnDraft.c)} onChange={e=>setWidths({...widths,[columnDraft.c]:Math.max(80,Math.min(600,Number(e.target.value)||180))})}/></label><button disabled={!hidden.includes(columnDraft.c)&&visibleColumns.length<=1} onClick={()=>setHidden(old=>old.includes(columnDraft.c)?old.filter(c=>c!==columnDraft.c):[...old,columnDraft.c])}>{hidden.includes(columnDraft.c)?uiText("sheetWorkspace.showColumn"):uiText("sheetWorkspace.hideColumn")}</button><hr/><button className="danger" disabled={!writable||busy||parsed.headers.length<=1} onClick={()=>{setSchemaPlan({operation:'delete',column_id:columnIds[columnDraft.c],label:parsed.headers[columnDraft.c]});setNewWorkbook(false);}}>{uiText("sheetWorkspace.deleteColumn")}</button></div>}
          {writable&&<form className="sheet-new-column" onSubmit={e=>{e.preventDefault();const name=new FormData(e.currentTarget).get('column_name').trim();if(name){setSchemaPlan({operation:'add',name,column_type:'text'});setNewWorkbook(false);}}}><label>{uiText("sheetWorkspace.addColumn")}<input name="column_name" required aria-label={uiText("sheetWorkspace.newColumnName")} placeholder={uiText("sheetWorkspace.columnName")}/></label><button disabled={busy||parsed.headers.length>=100}>{uiText("sheetWorkspace.addColumn2")}</button></form>}</>
          :row&&<><div className="sheet-panel-actions"><button disabled={!writable||!onAskAgent} onClick={()=>ask([row.rid])}>{uiText("sheetWorkspace.assignToAgent")}</button><button disabled={busy} onClick={()=>showHistory(row.rid)}>{uiText("sheetWorkspace.versionHistory")}</button></div><dl className="row-detail-fields">{row.cells.map((cell,c)=><div key={c}><dt>{parsed.headers[c]}</dt><dd>{mediaOf(cell.value,types[c])?<MediaCell compact value={cell.value} type={types[c]} label={parsed.headers[c]} onLightbox={item=>showPreview({...item,r:parsed.rows.indexOf(row),c})}/>:<span>{(isStatus(c)?statusLabel(cell.value):cell.value)||uiText("sheetWorkspace.notFilledIn")}</span>}{writable&&<div className="sheet-field-actions"><button onClick={()=>{setPanel(null);setView({mode:'grid'});beginEdit(parsed.rows.indexOf(row),c);}}>{uiText("sheetWorkspace.edit")}</button>{presetsFor(parsed.headers[c],Object.keys(assetLookup)).length>0&&presetChips(c,cell.value,value=>commit(parsed.rows.indexOf(row),c,value))}{['image','video','audio'].includes(types[c])&&<button disabled={busy} onClick={()=>pickUpload(parsed.rows.indexOf(row),c)}>{uiText("sheetWorkspace.upload")}</button>}</div>}</dd></div>)}</dl>{productionSheet&&<ShotProduction key={row.rid} slug={slug} actorId={me?.actor_id} rid={row.rid} source={reviewSource} writable={writable} disabled={busy||dirty} beforeRun={guardDraft} onChanged={refresh}/>}{discussion}{historyContent}</>}
      </aside>:shotDetail}
    </div>
    <footer className="sheet-footer"><span>{mode==='grid'?(range.rows.length?uiText("sheetWorkspace.selectRowsColumns", {v0: (range.rows.length), v1: (range.columns.length)}):uiText("sheetWorkspace.clickACellDragOrUseShiftArrowKeys")):uiText("sheetWorkspace.tableGalleryAndBoardShareTheSameData")}{mode==='grid'&&activeCell&&<span> · {columnName(active.c)}{active.r+1}{String(activeCell.value).startsWith('=')?`　${activeCell.value}`:''}</span>}</span><span>{mode==='grid'?uiText("sheetWorkspace.typeOrPressF2ToEditCopiedFormulasRetain"):uiText("sheetWorkspace.visibleRows", {v0: (visibleRows.length)})}</span></footer>
    {pendingPaste&&<SheetDialog title={uiText("sheetWorkspace.reviewPasteScope")} wide onClose={closePaste}><>{failure&&<p className="sheet-save-error" role="alert">{uiText("sheetWorkspace.pasteDraftPreserved", {v0: (failure.message)})}</p>}</><p>{uiText("sheetWorkspace.thisUpdatesTheVisibleRowsColumnsFilteredOutRows", {v0: (pendingPaste.rows), v1: (pendingPaste.columns)})}</p><div className="sheet-paste-preview"><table><tbody>{pendingPaste.cells.slice(0,8).map((cells,i)=><tr key={i}><th>{uiText("sheetWorkspace.row3", {v0: (parsed.rows.findIndex(r=>r.rid===pendingPaste.payload.row_edits[i].row_id)+1)})}</th>{cells.map((value,c)=><td key={c}>{value||uiText("sheetWorkspace.empty")}</td>)}</tr>)}</tbody></table></div>{pendingPaste.rows>8&&<p>{uiText("sheetWorkspace.plusRowsTheWholePasteCanBeUndoneTogether", {v0: (pendingPaste.rows-8)})}</p>}<p className="sheet-subtle">{uiText("sheetWorkspace.textAndNumbersRetainTheirInputValuesFormulaReferences")}</p><div className="sheet-dialog-actions"><button disabled={busy} onClick={closePaste}>{uiText("sheetWorkspace.cancel")}</button>{failure&&<button disabled={busy} onClick={()=>{try{setPendingPaste({...pendingPaste,payload:rebaseOperation(parsed,pendingPaste.payload)});setFailure(null);}catch(e){fail(e);}}}>{uiText("sheetWorkspace.reviewAgainstLatestValues")}</button>}<button className="primary" disabled={busy} onClick={async()=>{if(await submit(pendingPaste.payload))setPendingPaste(null);}}>{uiText("sheetWorkspace.applyPaste")}</button></div></SheetDialog>}
    {request&&<SheetAgentRequest request={request} instruction={instruction} onInstruction={setInstruction} agents={agents}
      onClose={()=>setRequest(null)} onUpdateScope={()=>{try{const ids=selected.size?[...selected]:visibleIds;setRequest({...request,scope:freezeSheetScope(tab,parsed,ids),table:parsed,title:tab.title});}catch(e){fail(e);}}}
      onSubmit={async options=>onAskAgent?.(sheetRequest(request.title,request.table,request.scope.row_ids,instruction),request.scope,options)} />}
    {schemaPlan&&<SheetDialog title={schemaPlan.operation==='delete'?uiText("sheetWorkspace.reviewColumnDeletion"):uiText("sheetWorkspace.reviewColumnDeliveryFormat")} onClose={closeSchema}><>{failure&&<p className="sheet-save-error" role="alert">{failure.message}</p>}</><p>{uiText("sheetWorkspace.formulaAndPipelineDependenciesAreCheckedBeforeApplyingChanges", {v0: (schemaPlan.operation==='delete'?uiText("sheetWorkspace.deleteAndItsCellContents", {v0: (schemaPlan.label)}):uiText("sheetWorkspace.confirmToApplyTheseStructuralOrColumnSettings"))})}</p>{imported&&<><p>{uiText("sheetWorkspace.thisTableCameFromExcelAfterChangingItsStructure")}</p><label className="sheet-check"><input type="checkbox" checked={newWorkbook} onChange={e=>setNewWorkbook(e.target.checked)}/>{uiText("sheetWorkspace.iWillDeliverTheseChangesAsANewWorkbook")}</label></>}<p className="sheet-subtle">{uiText("sheetWorkspace.structuralChangesClearCellUndoHistoryExistingRevisionsRemain")}</p><div className="sheet-dialog-actions"><button disabled={busy} onClick={closeSchema}>{uiText("sheetWorkspace.cancel")}</button><button className="primary" disabled={busy||(imported&&!newWorkbook)} onClick={async()=>{const delivery=imported?{delivery_mode:'new_workbook'}:{};if(schemaPlan.addRow){if(await submit({...schemaPlan.addRow,...delivery}))setSchemaPlan(null);}else await schema({...schemaPlan,...delivery});}}>{uiText("sheetWorkspace.applyChanges")}</button></div></SheetDialog>}
    {!productionSheet&&review}
    <input ref={upload} hidden type="file" accept="image/png,image/jpeg,image/gif,image/webp,video/mp4,video/webm,audio/*" onChange={e=>{const file=e.target.files?.[0],target=uploadTarget.current;e.target.value='';if(file&&target)uploadToCell(file,target);}}/>
  </section>;
}
