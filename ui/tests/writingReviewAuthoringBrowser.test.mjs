import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createServer} from 'node:http';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const uiRoot=fileURLToPath(new URL('..',import.meta.url));
const fixture=String.raw`
import React from 'react';import{createRoot}from'react-dom/client';
import{AuthoringWorkspace}from'./src/writing/AuthoringWorkspace.jsx';import{i18n}from'./src/i18n/index.js';
import authoring from './src/writing/locales/authoring.en.json';import reviewAuthoring from './src/writing/locales/review1-authoring.en.json';
import review2Authoring from './src/writing/locales/review2-authoring.en.json';
i18n.addResourceBundle('en','translation',{writing:{authoring:{...authoring,...reviewAuthoring,...review2Authoring}}},true,true);
window.calls=[];window.control={};window.statuses=[];window.failMetadata=false;window.delaySave=false;window.failLocal=false;
const original=IDBDatabase.prototype.transaction;IDBDatabase.prototype.transaction=function(stores,mode,...rest){if(window.failLocal&&mode==='readwrite')throw new Error('Synthetic quota failure');return original.call(this,stores,mode,...rest);};
const block=(bid,text,type='paragraph')=>({type,attrs:{bid,owner:null,created:null,...(type==='heading'?{level:2}:{})},content:[{type:'text',text,...(bid==='bodyB'?{marks:[{type:'bold'}]}:{})}]});
window.serverDoc={type:'doc',content:[block('headA','Scene 01: Before','heading'),block('bodyA','Surrounding before.'),block('headB','Scene 02: Selected','heading'),block('bodyB','Selected action.'),block('headC','Scene 03: After','heading'),block('bodyC','Surrounding after.')]};
window.version=Number(sessionStorage.getItem('fixtureVersion'))||1;window.sceneMetadata={};window.lanes=[{laneId:'lane1',name:'Signal',order:1}];window.actor='actor-a';window.episode='ep1';
window.structure=()=>({initialized:true,version:window.version,docHash:'hash'+window.version,scenes:['A','B','C'].map((key,i)=>{const at=serverDoc.content.findIndex(n=>n.attrs.bid==='head'+key),end=i===2?serverDoc.content.length:serverDoc.content.findIndex(n=>n.attrs.bid==='head'+['A','B','C'][i+1]),nodes=serverDoc.content.slice(at+1,end);return {sceneKey:'scene'+key,headingBid:'head'+key,title:'Scene 0'+(i+1)+': '+({A:'Before',B:'Selected',C:'After'})[key],mapping:'exact',blockBids:nodes.map(n=>n.attrs.bid),beats:nodes.map(n=>({beatKey:'beat'+n.attrs.bid,blockBids:[n.attrs.bid]})),assetCodes:['@CAST-01'],shotIds:['shot'+key],...(window.sceneMetadata[key]||{})};}),lanes:window.lanes});
const request=async(path,method='GET',body)=>{
 window.calls.push({path,method,body:structuredClone(body)});const tail=path.split('/writing/')[1];
 if(tail==='workspace')return {doc:structuredClone(serverDoc),docHash:'hash'+window.version,revision:window.version,structure:window.structure(),versions:{items:[]},branches:{items:[]},locks:[],baseline:{}};
 if(tail==='structure/metadata'){
  if(window.delayMetadata)await new Promise(resolve=>window.releaseMetadata=resolve);
  if(window.failMetadata)throw Object.assign(new Error('Synthetic metadata offline'),{status:500});
  if(body.baseVersion!==window.version)throw Object.assign(new Error('Structure changed'),{status:409});
  for(const patch of body.scenePatches){const key=patch.sceneKey.slice(-1);window.sceneMetadata[key]={...(window.sceneMetadata[key]||{}),...patch};}
  for(const patch of body.lanePatches){const lane=window.lanes.find(l=>l.laneId===patch.laneId);if(lane)Object.assign(lane,patch);else window.lanes.push(patch);}
  window.version++;return {...window.structure(),clientMutationId:body.clientMutationId,savedAt:new Date().toISOString()};
 }
 if(tail==='script/ops'){
  if(window.failScript)throw Object.assign(new Error('Synthetic script offline'),{status:500});
  if(window.delaySave)await new Promise(resolve=>window.releaseSave=resolve);
  for(const op of body.ops){const at=serverDoc.content.findIndex(n=>n.attrs.bid===op.bid);if(op.op==='put'){if(at>=0)serverDoc.content[at]=op.node;else serverDoc.content.splice(op.after?serverDoc.content.findIndex(n=>n.attrs.bid===op.after)+1:0,0,op.node);}else if(op.op==='del'){if(at>=0)serverDoc.content.splice(at,1);}else if(op.op==='order'){const byId=new Map(serverDoc.content.map(n=>[n.attrs.bid,n]));serverDoc.content=op.bids.map(id=>byId.get(id)).filter(Boolean);}}
  window.version++;return {clientMutationId:body.clientMutationId,doc:structuredClone(serverDoc),docHash:'hash'+window.version,revision:window.version,version:window.version,conflicts:[]};
 }
 if(tail?.startsWith('sources/'))return null;
 throw new Error('Unexpected route '+tail);
};
const root=createRoot(document.getElementById('root'));window.mount=()=>root.render(<AuthoringWorkspace slug="fixture" epId={window.episode} me={{actor_id:window.actor,role:'admin'}} writable request={request} controlRef={window.control} onStatus={s=>window.statuses.push(s)} onStage={s=>window.stage=s} renderTools={props=><button onClick={()=>props.reload()}>Refresh fixture workspace</button>}/>);
window.tryEpisode=async ep=>{if(!await control.current.flush())return false;window.episode=ep;window.mount();return true;};window.mount();
`;
async function browser(driver){
 const bundle=await build({stdin:{contents:fixture,resolveDir:uiRoot,loader:'jsx'},bundle:true,write:false,format:'iife',jsx:'automatic',loader:{'.css':'empty'},define:{'process.env.NODE_ENV':'"production"'}});
 const server=createServer((req,res)=>{if(req.url==='/app.js'){res.setHeader('Content-Type','text/javascript');res.end(bundle.outputFiles[0].text);}else{res.setHeader('Content-Type','text/html');res.end('<!doctype html><div id="root"></div><script src="/app.js"></script>');}});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const python=`from playwright.sync_api import sync_playwright,expect\nwith sync_playwright() as p:\n browser=p.chromium.launch(headless=True)\n context=browser.new_context(accept_downloads=True)\n page=context.new_page()\n errors=[]\n page.on('pageerror',lambda error:errors.append(str(error)))\n page.goto('http://127.0.0.1:${server.address().port}')\n expect(page.get_by_role('textbox',name='Manuscript editor')).to_contain_text('Selected action.')\n${driver}\n assert errors==[],errors\n context.close()\n browser.close()\nprint('PASS: mounted authoring regression')`;
 try{const output=await new Promise((resolve,reject)=>{const child=spawn('python',['-X','utf8','-c',python]);let stdout='',stderr='';child.stdout.on('data',c=>stdout+=c);child.stderr.on('data',c=>stderr+=c);child.on('error',reject);child.on('close',code=>resolve({code,stdout,stderr}));});assert.equal(output.code,0,output.stdout+'\n'+output.stderr);console.log(output.stdout.trim());}
 finally{await new Promise(resolve=>server.close(resolve));}
}
test('J1 mounted scene Enter, paste, delete, heading split and delayed ACK preserve local blocks and identities',{timeout:90000},()=>browser(String.raw`
 page.get_by_role('button',name='Scene 02: Selected',exact=True).click()
 editor=page.get_by_role('textbox',name='Manuscript editor')
 expect(editor).not_to_contain_text('Surrounding before.')
 page.wait_for_timeout(100)
 editor.evaluate("el=>{const e=el.editor;let at;e.state.doc.forEach((n,p)=>{if(n.type.name==='paragraph')at=p+n.nodeSize-1});e.commands.setTextSelection(at);e.view.focus();}")
 page.keyboard.press('Enter')
 expect(editor.locator('p')).to_have_count(2)
 page.keyboard.type('New paragraph.');page.keyboard.type(' Again.')
 expect(editor.locator('p').last).to_have_text('New paragraph. Again.')
 expect(editor.locator('h2')).to_have_text('Scene 02: Selected')
 assert page.evaluate("calls.filter(c=>c.path.endsWith('script/ops')).length")==0
 editor.evaluate(r"el=>{const data=new DataTransfer();data.setData('text/plain','Pasted one.\n\nPasted two.');el.dispatchEvent(new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true}));}")
 expect(editor).to_contain_text('Pasted two.')
 editor.evaluate("el=>{el.editor.commands.setTextSelection(3);el.editor.view.focus();}");page.keyboard.press('Enter')
 expect(editor.locator('h2')).to_have_count(2)
 page.keyboard.type('Split heading.')
 editor.evaluate("el=>{const e=el.editor;let range;e.state.doc.forEach((n,p)=>{if(n.type.name==='paragraph')range={from:p+1,to:p+n.nodeSize-1}});e.commands.setTextSelection(range);e.view.focus();}");page.keyboard.press('Backspace');page.keyboard.press('Backspace')
 expect(editor).not_to_contain_text('Pasted two.')
 ids=editor.evaluate("el=>[...el.children].map(n=>n.getAttribute('data-bid'))")
 assert len(ids)==len(set(ids)),ids
 page.evaluate('delaySave=true')
 page.keyboard.press('Control+s');page.wait_for_function('!!window.releaseSave')
 editor.evaluate("el=>{const e=el.editor;let at;e.state.doc.forEach((n,p)=>{if(at===undefined&&n.type.name==='paragraph')at=p+n.nodeSize-1});e.commands.setTextSelection(at);e.view.focus();}");page.keyboard.press('Enter');page.keyboard.type('Typed during ACK.')
 editor.dispatch_event('compositionstart');page.keyboard.insert_text('中文');page.wait_for_timeout(850)
 expect(editor).to_contain_text('Typed during ACK.中文')
 page.evaluate('delaySave=false;releaseSave()');page.wait_for_timeout(100)
 expect(editor).to_contain_text('Typed during ACK.中文')
 editor.dispatch_event('compositionend');page.wait_for_timeout(50)
 # Multiple transactions in one JS turn must use the latest draft membership, not a render closure.
 editor.evaluate("el=>{const e=el.editor;e.commands.splitBlock();e.commands.insertContent('Synchronous first');e.commands.splitBlock();e.commands.insertContent('Synchronous second');}")
 expect(editor).to_contain_text('Synchronous second')
 assert page.evaluate('control.current.flush({requireServer:true})') is True
 expect(editor).to_contain_text('Typed during ACK.中文')
 full=page.evaluate('serverDoc.content');bids=[n['attrs']['bid'] for n in full]
 assert len(bids)==len(set(bids)),bids
 assert bids[:2]==['headA','bodyA'] and bids[-2:]==['headC','bodyC'],bids
 assert next(n for n in full if n['attrs']['bid']=='bodyB')['content'][0]['marks']==[{'type':'bold'}]
 page.get_by_role('button',name='Full manuscript',exact=True).click()
 expect(editor).to_contain_text('Surrounding before.')
 expect(editor).to_contain_text('Typed during ACK.中文')
`));
test('J3 mounted outline Ctrl+S failure is dirty/recoverable and restores after navigation',{timeout:90000},()=>browser(String.raw`
 page.get_by_role('button',name='Plot overview',exact=True).click()
 page.locator('.writing-scene-metadata textarea').nth(1).fill('Author summary before blur')
 assert page.evaluate('control.current.isDirty()') is True
 page.evaluate('failMetadata=true');page.keyboard.press('Control+s')
 page.wait_for_function("calls.some(c=>c.path.endsWith('structure/metadata'))")
 assert page.evaluate('control.current.isDirty()') is True
 assert page.evaluate('control.current.flush()') is True
 assert page.evaluate('control.current.recoveryState().state')=='local_only'
 assert page.evaluate("tryEpisode('ep2')") is True
 page.wait_for_function("statuses.at(-1)?.tools?.some(t=>t.key==='outline:metadata'&&t.state!=='recovery')")
 assert page.evaluate("tryEpisode('ep1')") is True
 page.get_by_role('button',name='Restore outline draft for review',exact=True).click()
 page.get_by_role('button',name='Plot overview',exact=True).click()
 expect(page.locator('.writing-scene-metadata textarea').nth(1)).to_have_value('Author summary before blur')
 assert page.evaluate("calls.filter(c=>c.path.endsWith('structure/metadata')).every(c=>c.body.baseVersion===1)") is True
 page.evaluate('failMetadata=false');page.keyboard.press('Control+s')
 page.wait_for_function('control.current.isDirty()===false')
 assert page.evaluate('sceneMetadata.B.summary')=='Author summary before blur'
`));
test('J3 controlled summary/time/plot/lane edits survive delayed ACK and use successive current CAS',{timeout:90000},()=>browser(String.raw`
 page.get_by_role('button',name='Plot overview',exact=True).click()
 row=page.locator('.writing-scene-metadata').nth(1)
 page.evaluate('delayMetadata=true')
 row.locator('textarea').fill('First summary')
 row.get_by_label('Story time',exact=True).fill('Three years earlier')
 row.get_by_label('Signal',exact=True).fill('Signal plot cell')
 page.keyboard.press('Control+s');page.wait_for_function('!!window.releaseMetadata')
 row.locator('textarea').fill('Newest summary during ACK')
 row.get_by_label('Story time',exact=True).fill('The following night')
 page.evaluate('delayMetadata=false;releaseMetadata()')
 page.wait_for_function('control.current.isDirty()===false')
 expect(row.locator('textarea')).to_have_value('Newest summary during ACK')
 expect(row.get_by_label('Story time',exact=True)).to_have_value('The following night')
 expect(row.get_by_label('Signal',exact=True)).to_have_value('Signal plot cell')
 assert page.evaluate("calls.filter(c=>c.path.endsWith('structure/metadata')).map(c=>c.body.baseVersion)")==[1,2]
 assert page.evaluate('sceneMetadata.B.plot.lane1')=='Signal plot cell'
 expect(row.get_by_role('button',name='1 linked shots',exact=True)).to_be_visible()
 # Projection remains consumable after the metadata ACK/reload.
 expect(row).to_contain_text('@CAST-01')
 page.locator('.writing-outline form').get_by_role('textbox').last.fill('Renamed thread')
 page.keyboard.press('Control+s');page.wait_for_function('control.current.isDirty()===false')
 assert page.evaluate('lanes[0].name')=='Renamed thread'
 expect(page.get_by_role('textbox',name='Manuscript editor')).to_contain_text('Selected action.')
 assert page.evaluate("calls.some(c=>/generations|allocations|script\/ops/.test(c.path))") is False
`));
test('J3 quota + network failure blocks leaving; metadata-only divergent recovery is never rebased/published',{timeout:90000},()=>browser(String.raw`
 page.get_by_role('button',name='Plot overview',exact=True).click()
 page.evaluate('failLocal=true;failMetadata=true')
 page.locator('.writing-scene-metadata textarea').nth(1).fill('Do not lose this metadata')
 page.keyboard.press('Control+s')
 page.wait_for_function("control.current.recoveryState().state==='save_failed'")
 assert page.evaluate('control.current.recoveryState().recoverable') is False
 assert page.evaluate("tryEpisode('ep2')") is False
 assert page.evaluate('control.current.flush({reason:"identity"})') is False
 assert page.evaluate("window.dispatchEvent(new Event('beforeunload',{cancelable:true}))") is False
 with page.expect_download() as info:page.get_by_role('button',name='Download outline draft',exact=True).click()
 assert 'Do not lose this metadata' in open(info.value.path(),encoding='utf-8').read()
 page.evaluate('failLocal=false')
 assert page.evaluate('control.current.flush()') is True
 assert page.evaluate('control.current.recoveryState().state')=='local_only'
 # A different browser tab changed structure metadata, not manuscript text.
 page.evaluate("sessionStorage.setItem('fixtureVersion',String(++version))")
 page.reload()
 page.get_by_role('button',name='Restore outline draft for review',exact=True).click()
 page.wait_for_function("control.current.recoveryState().state==='conflict'")
 expect(page.get_by_text('This draft keeps base version 1',exact=False)).to_be_visible()
 assert page.evaluate('control.current.flush({reason:"save"})') is False
 assert page.evaluate("calls.filter(c=>c.path.endsWith('structure/metadata')).length")==0
 page.get_by_role('button',name='Plot overview',exact=True).click()
 expect(page.locator('.writing-scene-metadata textarea').nth(1)).to_have_value('Do not lose this metadata')
 assert page.evaluate("tryEpisode('ep2')") is False
 page.get_by_role('button',name='Discard outline draft and read current structure',exact=True).click()
 page.wait_for_function('control.current.isDirty()===false')
 assert page.evaluate("calls.filter(c=>c.path.endsWith('structure/metadata')).length")==0
`));
test('N1 scene/full/scene after ACK includes saved insert-before and preserves document order',{timeout:90000},()=>browser(String.raw`
 editor=page.get_by_role('textbox',name='Manuscript editor')
 page.get_by_role('button',name='Scene 02: Selected',exact=True).click()
 expect(editor).not_to_contain_text('Surrounding before.')
 editor.evaluate("el=>{const e=el.editor;let at;e.state.doc.forEach((n,p)=>{if(n.attrs.bid==='bodyB')at=p+n.nodeSize-1});e.commands.setTextSelection(at);e.commands.insertContent(' Edited in B.');}")
 assert page.evaluate('control.current.flush({requireServer:true})') is True
 page.get_by_role('button',name='Full manuscript',exact=True).click()
 expect(editor).to_contain_text('Surrounding before.')
 editor.evaluate("el=>{const e=el.editor;let at;e.state.doc.forEach((n,p)=>{if(n.attrs.bid==='bodyB')at=p});e.commands.insertContentAt(at,{type:'paragraph',content:[{type:'text',text:'FIRST inserted action.'}]});}")
 assert page.evaluate('control.current.flush({requireServer:true})') is True
 before=page.evaluate('serverDoc.content.map(n=>n.attrs.bid)')
 page.get_by_role('button',name='Scene 02: Selected',exact=True).click()
 expect(editor).to_contain_text('FIRST inserted action.')
 editor.evaluate("el=>{const e=el.editor;let at;e.state.doc.forEach((n,p)=>{if(n.attrs.bid==='bodyB')at=p+n.nodeSize-1});e.commands.setTextSelection(at);e.commands.insertContent(' Re-entry edit.');}")
 assert page.evaluate('control.current.flush({requireServer:true})') is True
 assert page.evaluate('serverDoc.content.map(n=>n.attrs.bid)')==before
`));
test('N3 co-dirty manuscript and summary/time/plot Ctrl+S uses a proven own-document advance',{timeout:90000},()=>browser(String.raw`
 page.get_by_role('button',name='Plot overview',exact=True).click()
 editor=page.get_by_role('textbox',name='Manuscript editor')
 editor.evaluate("el=>{const e=el.editor;let at;e.state.doc.forEach((n,p)=>{if(n.attrs.bid==='bodyB')at=p+n.nodeSize-1});e.commands.setTextSelection(at);e.commands.insertContent(' Same author manuscript edit.');}")
 row=page.locator('.writing-scene-metadata').nth(1)
 row.locator('textarea').fill('Co-dirty summary')
 row.get_by_label('Story time',exact=True).fill('Tomorrow')
 row.get_by_label('Signal',exact=True).fill('Co-dirty plot')
 page.evaluate('delaySave=true');page.keyboard.press('Control+s')
 page.wait_for_function('!!window.releaseSave')
 row.locator('textarea').fill('Co-dirty summary updated during document ACK')
 assert page.evaluate("calls.some(c=>c.path.endsWith('structure/metadata'))") is False
 page.evaluate('delaySave=false;releaseSave()')
 page.wait_for_function("control.current.recoveryState().state==='saved' || control.current.recoveryState().state==='conflict'")
 assert page.evaluate('control.current.recoveryState().state')=='saved',page.evaluate('({status:control.current.recoveryState(),calls})')
 assert page.evaluate('sceneMetadata.B.summary')=='Co-dirty summary updated during document ACK'
 assert page.evaluate("calls.filter(c=>c.path.endsWith('structure/metadata')).map(c=>c.body.baseVersion)")==[2]
`));
test('N1 pending slice transitions, repeated before/after insertion and remote refresh preserve all identities/order',{timeout:90000},()=>browser(String.raw`
 editor=page.get_by_role('textbox',name='Manuscript editor')
 original=page.evaluate('structuredClone(serverDoc.content)')
 page.get_by_role('button',name='Scene 02: Selected',exact=True).click()
 expect(editor).not_to_contain_text('Surrounding before.')
 page.evaluate('failScript=true')
 editor.evaluate("el=>{const e=el.editor;e.commands.insertContentAt(e.state.doc.content.size,{type:'paragraph',content:[{type:'text',text:'Pending scene paragraph'}]});}")
 page.keyboard.press('Control+s');page.wait_for_function("control.current.recoveryState().state==='local_only'")
 page.get_by_role('button',name='Full manuscript',exact=True).click()
 expect(editor).to_contain_text('Pending scene paragraph')
 expect(editor).to_contain_text('Surrounding before.')
 editor.evaluate("el=>{const e=el.editor;let at;e.state.doc.forEach((n,p)=>{if(n.attrs.bid==='bodyB')at=p});e.commands.insertContentAt(at,{type:'paragraph',content:[{type:'text',text:'Before pending existing action'}]});}")
 page.get_by_role('button',name='Scene 02: Selected',exact=True).click()
 expect(editor).to_contain_text('Before pending existing action')
 expect(editor).to_contain_text('Pending scene paragraph')
 expect(editor).not_to_contain_text('Surrounding before.')
 page.evaluate('failScript=false;delaySave=true')
 page.keyboard.press('Control+s');page.wait_for_function('!!window.releaseSave')
 # Navigation waits for the outstanding ACK rather than retiring a dirty slice early.
 page.get_by_role('button',name='Full manuscript',exact=True).click()
 expect(editor).not_to_contain_text('Surrounding before.')
 expect(editor).to_contain_text('Pending scene paragraph')
 page.evaluate('delaySave=false;releaseSave()')
 expect(editor).to_contain_text('Surrounding before.')
 assert page.evaluate('control.current.flush({requireServer:true})') is True
 for cycle in range(3):
  editor.evaluate("(el,cycle)=>{const e=el.editor;let at;e.state.doc.forEach((n,p)=>{if(n.attrs.bid==='bodyB')at=p});e.commands.insertContentAt(at,{type:'paragraph',content:[{type:'text',text:'Before cycle '+cycle}]});let after;e.state.doc.forEach((n,p)=>{if(n.attrs.bid==='bodyB')after=p+n.nodeSize});e.commands.insertContentAt(after,{type:'paragraph',content:[{type:'text',text:'After cycle '+cycle}]});}",cycle)
  assert page.evaluate('control.current.flush({requireServer:true})') is True
  before=page.evaluate('serverDoc.content.map(n=>n.attrs.bid)')
  page.get_by_role('button',name='Scene 02: Selected',exact=True).click()
  expect(editor).to_contain_text('Before cycle '+str(cycle))
  expect(editor).to_contain_text('After cycle '+str(cycle))
  editor.evaluate("el=>{const e=el.editor;let at;e.state.doc.forEach((n,p)=>{if(n.attrs.bid==='bodyB')at=p+n.nodeSize-1});e.commands.setTextSelection(at);e.commands.insertContent(' Cycle edit.');}")
  assert page.evaluate('control.current.flush({requireServer:true})') is True
  assert page.evaluate('serverDoc.content.map(n=>n.attrs.bid)')==before
  page.get_by_role('button',name='Full manuscript',exact=True).click()
  expect(editor).to_contain_text('Surrounding before.')
 page.get_by_role('button',name='Scene 02: Selected',exact=True).click()
 page.evaluate("serverDoc.content.splice(serverDoc.content.findIndex(n=>n.attrs.bid==='bodyB'),0,{type:'paragraph',attrs:{bid:'remoteBefore',owner:null,created:null},content:[{type:'text',text:'Remote refreshed paragraph'}]});version++")
 page.get_by_role('button',name='World, search & files',exact=True).click()
 page.get_by_role('button',name='Refresh fixture workspace',exact=True).click()
 expect(editor).to_contain_text('Remote refreshed paragraph')
 before=page.evaluate('serverDoc.content.map(n=>n.attrs.bid)')
 editor.evaluate("el=>{const e=el.editor;let at;e.state.doc.forEach((n,p)=>{if(n.attrs.bid==='bodyB')at=p+n.nodeSize-1});e.commands.setTextSelection(at);e.commands.insertContent(' After remote refresh.');}")
 assert page.evaluate('control.current.flush({requireServer:true})') is True
 assert page.evaluate('serverDoc.content.map(n=>n.attrs.bid)')==before
 # A refresh while this slice is dirty must retain its pending edit; the next block ACK
 # merges a remote-only insertion instead of clearing the slice or absorbing a neighbor.
 page.evaluate('failScript=true')
 editor.evaluate("el=>{const e=el.editor;let at;e.state.doc.forEach((n,p)=>{if(n.attrs.bid==='bodyB')at=p+n.nodeSize-1});e.commands.setTextSelection(at);e.commands.insertContent(' Pending through remote refresh.');}")
 page.keyboard.press('Control+s');page.wait_for_function("control.current.recoveryState().state==='local_only'")
 page.evaluate("serverDoc.content.splice(serverDoc.content.findIndex(n=>n.attrs.bid==='bodyB'),0,{type:'paragraph',attrs:{bid:'remotePending',owner:null,created:null},content:[{type:'text',text:'Remote during pending refresh'}]});version++")
 page.get_by_role('button',name='Refresh fixture workspace',exact=True).click()
 expect(editor).to_contain_text('Pending through remote refresh.')
 page.evaluate('failScript=false')
 assert page.evaluate('control.current.flush({requireServer:true})') is True
 expect(editor).to_contain_text('Remote during pending refresh')
 expect(editor).to_contain_text('Pending through remote refresh.')
 final=page.evaluate('serverDoc.content')
 assert final[:2]==original[:2] and final[-2:]==original[-2:]
 ids=[n['attrs']['bid'] for n in final];assert len(ids)==len(set(ids))
 assert next(n for n in final if n['attrs']['bid']=='bodyB')['content'][0]['marks']==[{'type':'bold'}]
`));
test('N3 true concurrent metadata is preserved and resolved only by a fresh explicit field merge',{timeout:90000},()=>browser(String.raw`
 page.get_by_role('button',name='Plot overview',exact=True).click()
 editor=page.get_by_role('textbox',name='Manuscript editor')
 editor.evaluate("el=>{const e=el.editor;let at;e.state.doc.forEach((n,p)=>{if(n.attrs.bid==='bodyB')at=p+n.nodeSize-1});e.commands.setTextSelection(at);e.commands.insertContent(' Own document advance with a real metadata conflict.');}")
 row=page.locator('.writing-scene-metadata').nth(1)
 row.locator('textarea').fill('Private summary')
 row.get_by_label('Story time',exact=True).fill('Private time')
 row.get_by_label('Signal',exact=True).fill('Private plot')
 page.evaluate("sceneMetadata.B={summary:'Remote summary',storyTime:'Remote time',plot:{lane1:'Remote plot'},payoff:'Unrelated remote payoff'};version++")
 page.keyboard.press('Control+s');page.wait_for_function("control.current.recoveryState().state==='conflict'")
 assert page.evaluate('control.current.recoveryState().recoverable') is True
 assert page.evaluate("calls.filter(c=>c.path.endsWith('structure/metadata')).length")==0
 expect(row.locator('textarea')).to_have_value('Private summary')
 page.get_by_role('button',name='Read current outline for reviewed merge',exact=True).click()
 merge=page.get_by_role('form',name='Review outline metadata merge',exact=True)
 expect(merge).to_contain_text('Remote summary')
 expect(merge).to_contain_text('Private summary')
 # The form names scenes and lanes the way the author sees them, never by internal path or ID.
 expect(merge).to_contain_text('Scene 02: Selected')
 expect(merge).to_contain_text('Signal: Remote plot')
 expect(merge).not_to_contain_text('scenePatches')
 expect(merge).not_to_contain_text('sceneB')
 expect(merge.get_by_label('Value to keep Scene 02: Selected · Summary',exact=True)).to_have_value('server')
 merge.get_by_label('Value to keep Scene 02: Selected · Summary',exact=True).select_option('local')
 # A newer version after review invalidates the entire selection; no stale merge request is sent.
 page.evaluate("sceneMetadata.B.storyTime='Remote time after review';version++")
 merge.get_by_role('button',name='Save explicitly reviewed outline merge',exact=True).click()
 first=merge.get_by_role('alert').filter(has_text='Private draft values to be discarded')
 expect(first).to_contain_text('Private draft values to be discarded: 2')
 expect(first).to_contain_text('Signal: Private plot')
 with page.expect_download() as exported:
  first.get_by_role('button',name='Download discarded values',exact=True).click()
 exported_text=open(exported.value.path(),encoding='utf8').read()
 assert '"Signal"' in exported_text and 'Private plot' in exported_text and 'lane1' not in exported_text
 first.get_by_role('button',name='Discard these values and save',exact=True).click()
 expect(page.get_by_text('The outline or draft changed after review.',exact=False)).to_be_visible()
 assert page.evaluate("calls.filter(c=>c.path.endsWith('structure/metadata')).length")==0
 merge.get_by_label('Value to keep Scene 02: Selected · Summary',exact=True).select_option('local')
 merge.get_by_label('Value to keep Scene 02: Selected · Plot cells',exact=True).select_option('local')
 # Story time stays on the shared value, so the private value would be dropped: confirm first, offer a download, allow going back.
 merge.get_by_role('button',name='Save explicitly reviewed outline merge',exact=True).click()
 alert=merge.get_by_role('alert').filter(has_text='Private draft values to be discarded')
 expect(alert).to_contain_text('Private draft values to be discarded: 1')
 expect(alert).to_contain_text('Scene 02: Selected · Story time')
 expect(alert).to_contain_text('Private time')
 expect(alert).to_be_focused()
 assert page.evaluate("calls.filter(c=>c.path.endsWith('structure/metadata')).length")==0
 with page.expect_download() as download:
  alert.get_by_role('button',name='Download discarded values',exact=True).click()
 assert download.value.suggested_filename=='outline-discarded-values.json'
 saved=open(download.value.path(),encoding='utf8').read()
 assert 'Private time' in saved and 'Scene 02: Selected' in saved and 'scenePatches' not in saved
 alert.get_by_role('button',name='Go back and choose again',exact=True).click()
 expect(alert).to_have_count(0)
 expect(merge.get_by_role('button',name='Save explicitly reviewed outline merge',exact=True)).to_be_focused()
 assert page.evaluate("calls.filter(c=>c.path.endsWith('structure/metadata')).length")==0
 merge.get_by_role('button',name='Save explicitly reviewed outline merge',exact=True).click()
 merge.get_by_role('alert').filter(has_text='Private draft values to be discarded').get_by_role('button',name='Discard these values and save',exact=True).click()
 page.wait_for_function('control.current.isDirty()===false')
 assert page.evaluate('sceneMetadata.B.summary')=='Private summary'
 assert page.evaluate('sceneMetadata.B.storyTime')=='Remote time after review'
 assert page.evaluate('sceneMetadata.B.plot.lane1')=='Private plot'
 assert page.evaluate('sceneMetadata.B.payoff')=='Unrelated remote payoff'
 assert page.evaluate("calls.filter(c=>c.path.endsWith('structure/metadata')).map(c=>c.body.baseVersion)")==[4]
 assert page.evaluate("calls.some(c=>/generations|allocations/.test(c.path))") is False
`));
