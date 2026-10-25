import { useEffect, useRef } from 'react';
import { EditorContent, useEditor } from '@tiptap/react';
import { Extension, Node } from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import Image from '@tiptap/extension-image';
import { TaskList, TaskItem } from '@tiptap/extension-list';
import { TableKit } from '@tiptap/extension-table';
import { TextSelection } from '@tiptap/pm/state';
import { BlockIds, ensureIds, PermissionGuard, SYSTEM, REMOTE } from '../editorExtensions.js';
import { stable, mergeAcknowledged } from './writingModel.js';

// Preserve validated document attributes that the legacy generic editor does not expose.
const TableMetadata=Extension.create({name:'writingTableMetadata',addGlobalAttributes(){return [{types:['table'],attributes:Object.fromEntries(['column_ids','column_options','source_header_row','source_start_column','source_data_start_row','mapping_revision'].map(name=>[name,{default:null}]))}];}});
const Status=Node.create({name:'status',group:'inline',inline:true,atom:true,addAttributes(){return {label:{default:'Queued'},fid:{default:null}};},parseHTML(){return [{tag:'span[data-writing-status]'}];},renderHTML({node}){return ['span',{'data-writing-status':'true'},node.attrs.label];}});
const Fill=Node.create({name:'fill',group:'inline',inline:true,atom:true,addAttributes(){return {label:{default:''},fid:{default:null}};},parseHTML(){return [{tag:'span[data-writing-fill]'}];},renderHTML({node}){return ['span',{'data-writing-fill':'true'},node.attrs.label];}});
export function canonicalEditorDoc(node,depth=0) {
  const result={type:node.type};
  if(node.text!==undefined)result.text=node.text;
  if(node.attrs){
    const attrs=Object.fromEntries(Object.entries(node.attrs).filter(([key,value])=>value!==null || ['owner','created'].includes(key) && depth===1 || key==='colwidth'));
    // Link defaults such as target/rel and list type are not persisted fields.
    if(node.type==='orderedList')delete attrs.type;
    if(Object.keys(attrs).length)result.attrs=attrs;
  }
  if(node.marks?.length)result.marks=node.marks.map(mark=>mark.type==='link'?{type:'link',attrs:{href:mark.attrs.href}}:{type:mark.type});
  if(node.content)result.content=node.content.map(child=>canonicalEditorDoc(child,depth+1));
  else if(node.type==='doc')result.content=[];
  return result;
}
export function writingExtensions({getOwner=()=>null,getCtx}={}) {
  return [StarterKit.configure({codeBlock:false,heading:{levels:[1,2,3]},link:{openOnClick:false,protocols:['http','https','mailto']}}),Image,TaskList,TaskItem,TableKit,BlockIds.configure({getOwner}),TableMetadata,Status,Fill,...(getCtx?[PermissionGuard.configure({getCtx})]:[])];
}
export function patchWritingEditor(editor,json) {
  const {state}=editor;
  const next=(json.content || []).map(node=>state.schema.nodeFromJSON(node));
  let tr=state.tr;
  // Patch only changed blocks when order/identity is stable, keeping cursor/history elsewhere.
  const have=[];state.doc.forEach((node,pos)=>have.push({node,pos}));
  if(have.length===next.length && have.every(({node},i)=>node.attrs.bid===next[i].attrs.bid)){
    for(let i=have.length-1;i>=0;i--)if(!have[i].node.eq(next[i]))tr.replaceWith(have[i].pos,have[i].pos+have[i].node.nodeSize,next[i]);
  }else tr.replaceWith(0,state.doc.content.size,next);
  if(!tr.docChanged)return;
  tr.setMeta(SYSTEM,true).setMeta(REMOTE,true).setMeta('addToHistory',false);editor.view.dispatch(tr);
}
export function WritingEditor({doc,sliceKey,writable,me,onChange,onComposition,onReady,label,focusBid,locks=[],privateResource=false}) {
  const latest=useRef({});latest.current={onChange,onComposition,onReady};
  const composing=useRef(false),compositionBase=useRef(null),deferred=useRef(null),editorRef=useRef(null),localEchoes=useRef([]);
  const changed=next=>{localEchoes.current.push(stable(next));if(localEchoes.current.length>200)localEchoes.current.shift();latest.current.onChange?.(next);};
  const ctx=useRef({});ctx.current={me:me?.actor_id,admin:privateResource || me?.role==='admin',locks:new Map(locks.map(lock=>[lock.bid,lock.name || lock.actor_id])),names:new Map(),adminIds:new Set(),onBlocked:()=>{}};
  const editor=useEditor({
    extensions:writingExtensions({getOwner:()=>me?.role==='admin'?null:me?.actor_id,getCtx:()=>ctx.current}),
    content:doc,editable:writable,immediatelyRender:false,shouldRerenderOnTransaction:false,
    editorProps:{attributes:{'aria-label':label,role:'textbox','aria-multiline':'true'},handleDOMEvents:{
      compositionstart:()=>{composing.current=true;compositionBase.current=canonicalEditorDoc(editorRef.current.getJSON());latest.current.onComposition?.(true);return false;},
      compositionend:()=>{
        // Let ProseMirror finish its composition transaction before scheduling a save/remote patch.
        setTimeout(()=>{if(!editorRef.current || editorRef.current.isDestroyed)return;composing.current=false;const live=canonicalEditorDoc(editorRef.current.getJSON());const merged=deferred.current?mergeAcknowledged(deferred.current,compositionBase.current,live):live;deferred.current=null;if(stable(merged)!==stable(live))patchWritingEditor(editorRef.current,merged);changed(merged);latest.current.onComposition?.(false);},0);return false;
      },
    }},
    onCreate:({editor})=>{const tr=ensureIds(editor.state);if(tr)editor.view.dispatch(tr);latest.current.onReady?.(editor);},
    onUpdate:({editor,transaction})=>{if(!transaction.getMeta(REMOTE))changed(canonicalEditorDoc(editor.getJSON()));},
  },[]);
  editorRef.current=editor;
  useEffect(()=>{if(editor)editor.setEditable(writable,false);},[editor,writable]);
  // A local transaction can rerender EditorContent before React receives its parent echo.
  // Only a genuinely different prop document is a remote/projection update.
  const docVersion=stable(doc);
  useEffect(()=>{localEchoes.current=[];deferred.current=null;},[sliceKey]);
  useEffect(()=>{
    if(!editor)return;
    const echo=localEchoes.current.lastIndexOf(docVersion);
    if(echo>=0){localEchoes.current.splice(0,echo+1);return;}
    if(stable(canonicalEditorDoc(editor.getJSON()))===docVersion)return;
    if(composing.current){deferred.current=doc;return;}patchWritingEditor(editor,doc);
  },[editor,docVersion,sliceKey]);
  useEffect(()=>{
    if(!editor || !focusBid || composing.current)return;
    let at=null;editor.state.doc.descendants((node,pos)=>{if(node.attrs.bid===focusBid){at=pos+1;return false;}});
    if(at!==null){editor.view.dispatch(editor.state.tr.setSelection(TextSelection.near(editor.state.doc.resolve(at))).scrollIntoView());editor.view.focus();}
  },[editor,focusBid]);
  return <EditorContent editor={editor} className="writing-editor" />;
}
