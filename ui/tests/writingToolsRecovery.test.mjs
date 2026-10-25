import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createServer} from 'node:http';
import {spawn} from 'node:child_process';
import {build} from '../node_modules/esbuild/lib/main.js';
import {BibleFormRecovery} from '../src/writing/writingToolsRecovery.js';

const memory=()=>{const rows=new Map();return {rows,list:async scope=>[...rows.values()].filter(row=>row.scope===scope),put:async(key,value)=>rows.set(key,structuredClone({...value,key})),remove:async(key,seq)=>{if(rows.get(key)?.localSequence<=seq)rows.delete(key);}};};
test('form checkpoint/control uses scoped shared journal keys, exact-sequence identity decisions, and preserves newer checkpoints',async()=>{
 const journal=memory(),base={bibleId:'b1',version:1,entryKind:'note',notes:'Shared'};
 const form=new BibleFormRecovery({slug:'p',actorId:'a',epId:'e',tabId:'tab-a',journal});form.open(base,{entryKind:'note',notes:'Shared'});await form.discover();
 form.change({entryKind:'note',notes:'Private'});assert.equal(await form.flush(),true);assert.equal(form.recoveryState().state,'local_only');
 assert.equal(await form.flush({reason:'identity'}),false);assert.equal(await form.preserveIdentity(),true);assert.equal(await form.flush({reason:'identity'}),true);
 form.change({entryKind:'note',notes:'Newer private'});assert.equal(await form.flush({reason:'identity'}),false);await form.flush();
 const other=new BibleFormRecovery({slug:'p',actorId:'b',epId:'e',tabId:'tab-b',journal});other.open(null,{});await other.discover();assert.equal(other.recoveries.length,0);
 const reopened=new BibleFormRecovery({slug:'p',actorId:'a',epId:'e',tabId:'tab-c',journal});reopened.open(base,{notes:'Shared'});await reopened.discover();assert.equal(reopened.recoveries.length,1);
 await reopened.restore(reopened.recoveries[0],{...base,version:2,notes:'Remote'});assert.equal(reopened.state,'conflict');assert.equal(await reopened.flush(),false);assert.equal(reopened.base.version,1);
 assert.equal(reopened.merged(),true);assert.equal(reopened.base.version,2);assert.equal(reopened.draft.notes,'Newer private');
 await reopened.checkpoint();form.dispose();other.dispose();reopened.dispose();
});

test('latest dirty sequence, failed discard and stale cleanup never claim false recovery or clear a newer tab draft',async()=>{
 const journal=memory(),base={bibleId:'b1',version:1};
 const first=new BibleFormRecovery({slug:'p',actorId:'a',epId:'e',tabId:'first',journal});first.open(base,{notes:'shared'});await first.discover();first.change({notes:'old private'});await first.checkpoint();
 const second=new BibleFormRecovery({slug:'p',actorId:'a',epId:'e',tabId:'second',journal});second.open(base,{notes:'shared'});await second.discover();const old=second.recoveries[0];
 second.change({notes:'new not checkpointed'});assert.equal(second.recoveryState().recoverable,false);await second.discard(base,{notes:'shared'});
 first.change({notes:'newest first-tab private'});await first.checkpoint();
 await second.restore(old,base);assert.equal(journal.rows.get(old.key).draft.notes,'newest first-tab private');
 const remove=journal.remove;journal.remove=async()=>{throw new Error('Deletion denied');};
 await assert.rejects(second.discard(base,{notes:'shared'}),/Deletion denied/);assert.equal(second.dirty,true);assert.equal(second.recoveryState().recoverable,false);assert.equal(await second.flush({reason:'identity'}),false);
 journal.remove=remove;await second.discard(base,{notes:'shared'});assert.equal(second.dirty,false);assert.equal(journal.rows.get(old.key).draft.notes,'newest first-tab private');
 first.markError('auth');first.markError('conflict');assert.equal(first.state,'auth_lost');assert.equal(await first.flush(),false);
 first.dispose();second.dispose();
});

test('explicit pending-recovery preservation is actor scoped and rechecked against newer edits before identity change',async()=>{
 const journal=memory(),base={bibleId:'b1',version:1};
 const source=new BibleFormRecovery({slug:'p',actorId:'a',epId:'e',tabId:'source',journal});source.open(base,{notes:'shared'});await source.discover();source.change({notes:'first private'});await source.checkpoint();
 const owner=new BibleFormRecovery({slug:'p',actorId:'a',epId:'e',tabId:'owner',journal});owner.open(base,{notes:'shared'});await owner.discover();assert.equal(await owner.flush({reason:'identity'}),false);
 assert.equal(await owner.preserveRecovery(owner.recoveries[0]),true);assert.equal(await owner.flush({reason:'identity'}),true);assert.equal(owner.isDirty(),true);
 source.change({notes:'newer private'});await source.checkpoint();assert.equal(await owner.flush({reason:'identity'}),false);assert.equal(owner.recoveries[0].draft.notes,'newer private');
 assert.equal(await owner.preserveRecovery(owner.recoveries[0]),true);assert.equal(await owner.flush({reason:'identity'}),true);
 source.dispose();owner.dispose();
});

const fixture=String.raw`
import React from 'react';import {createRoot} from 'react-dom/client';
import {AuthoringWorkspace} from './src/writing/AuthoringWorkspace.jsx';
import {WritingToolsPanel} from './src/writing/WritingToolsPanel.jsx';
import {i18n} from './src/i18n/index.js';
import tools from './src/writing/locales/tools.en.json';import authoring from './src/writing/locales/authoring.en.json';
i18n.addResourceBundle('en','translation',{writing:{tools,authoring}},true,true);
window.actor='actor-a';window.episode='ep-1';window.control={current:null};window.statuses=[];window.calls=[];
const original=IDBDatabase.prototype.transaction;
IDBDatabase.prototype.transaction=function(stores,mode,...rest){if(window.failLocal&&mode==='readwrite')throw new DOMException('Synthetic quota denial','QuotaExceededError');return original.call(this,stores,mode,...rest);};
async function request(path,method='GET',body,options={}){
 const route=path.replace(/^\/episodes\/([^/]+)\/writing\//,'/wire/$1/');window.calls.push({actor:window.actor,path,method,body});
 const response=await fetch(route,{method,body:body===undefined?undefined:JSON.stringify(body),headers:{'Content-Type':'application/json'},signal:options.signal});
 const data=await response.json();if(!response.ok)throw Object.assign(new Error(data.message||'Fixture error'),{status:response.status,code:data.code,data});return data;
}
const root=createRoot(document.getElementById('root'));
window.renderWorkspace=()=>root.render(React.createElement(AuthoringWorkspace,{slug:'production',epId:window.episode,me:{actor_id:window.actor,name:'Author',role:'admin'},writable:true,ep:{settings:{}},request,controlRef:window.control,onStatus:status=>window.statuses.push(status),renderTools:props=>React.createElement(WritingToolsPanel,props)}));
window.tryEpisode=async episode=>{if(!await window.control.current.flush())return false;window.episode=episode;window.renderWorkspace();return true;};
window.tryIdentity=async actor=>{if(!await window.control.current.flush({reason:'identity'}))return false;window.actor=actor;window.renderWorkspace();return true;};
window.renderWorkspace();
`;
const driver=String.raw`
import os
from playwright.sync_api import sync_playwright,expect
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True)
 context=browser.new_context(accept_downloads=True,viewport={'width':1280,'height':900})
 page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
 page.goto(os.environ['RECOVERY_URL'])
 def open_bible():
  page.locator('.writing-toolbar').get_by_role('button',name='World, search & files',exact=True).click()
  page.locator('.writing-tools-nav').get_by_role('button',name='World & notes',exact=True).click()
  return page.get_by_role('region',name='World & notes')
 def wait_ready():page.wait_for_function("control.current && statuses.at(-1)?.tools?.some(item=>item.key==='bible:form'&&item.state!=='recovery')")
 wait_ready();bible=open_bible()
 bible.get_by_role('combobox',name='Subject',exact=True).select_option('note-1')
 notes=bible.get_by_role('textbox',name='Notes',exact=True)
 expect(notes).to_have_value('Shared original')
 notes.fill('Private before reload 😀 <script>not executable</script>')
 expect(bible.get_by_role('status').filter(has_text='Private draft saved on this device')).to_be_visible()
 assert page.evaluate('statuses.at(-1).dirty') is True
 assert page.evaluate('statuses.at(-1).documentState')=='saved',page.evaluate("({status:statuses.at(-1),calls,doc:document.querySelector('.tiptap').pmViewDesc.node.toJSON()})")
 assert page.evaluate("statuses.at(-1).tools.find(item=>item.key==='bible:form').recoverable") is True
 assert page.evaluate("calls.filter(c=>c.method!=='GET').length")==0
 assert page.evaluate('control.current.flush({requireServer:true})') is True
 assert page.evaluate('control.current.isDirty()') is True
 assert page.evaluate('control.current.flush()') is True
 # Space/episode navigation checkpoints privately without sending shared mutations.
 assert page.evaluate("tryEpisode('ep-2')") is True
 wait_ready();bible=open_bible()
 expect(bible.get_by_role('region',name='Private form recovery')).to_have_count(0)
 assert page.evaluate("tryEpisode('ep-1')") is True
 page.wait_for_function("statuses.at(-1)?.tools?.some(item=>item.state==='recovery')")
 bible=open_bible()
 expect(bible.get_by_role('region',name='Private form recovery')).to_contain_text('Private before reload')
 assert page.evaluate('control.current.flush()') is False
 bible.get_by_role('button',name='Restore private draft for review').click()
 expect(bible.get_by_role('textbox',name='Notes',exact=True)).to_have_value('Private before reload 😀 <script>not executable</script>')
 expect(bible.get_by_role('status').filter(has_text='Private draft saved on this device')).to_be_visible()
 assert page.evaluate('control.current.flush()') is True
 page.reload()
 page.wait_for_function("statuses.at(-1)?.tools?.some(item=>item.state==='recovery')")
 bible=open_bible()
 bible.get_by_role('button',name='Restore private draft for review').click()
 expect(bible.get_by_role('textbox',name='Notes',exact=True)).to_have_value('Private before reload 😀 <script>not executable</script>')
 assert page.evaluate("calls.filter(c=>c.method!=='GET').length")==0
 # Failed local transaction never claims recoverability, blocks real workspace navigation, offers download.
 page.evaluate('failLocal=true')
 bible.get_by_role('textbox',name='Notes',exact=True).fill('Private after quota failure')
 expect(bible.get_by_role('alert').filter(has_text='Local draft checkpoint failed')).to_be_visible()
 assert page.evaluate("control.current.recoveryState().tools.find(item=>item.key==='bible:form').recoverable") is False
 assert page.evaluate("tryEpisode('ep-2')") is False
 assert page.evaluate("tryIdentity('actor-b')") is False
 assert page.evaluate("window.dispatchEvent(new Event('beforeunload',{cancelable:true}))") is False
 with page.expect_download() as info:bible.get_by_role('button',name='Download private draft',exact=True).click()
 assert 'Private after quota failure' in open(info.value.path(),encoding='utf-8').read()
 assert page.evaluate("tryIdentity('actor-b')") is False, 'Download request alone is not identity-preservation consent'
 bible.get_by_role('button',name='Discard private form changes',exact=True).click()
 expect(bible.get_by_role('textbox',name='Notes',exact=True)).to_have_value('Private after quota failure')
 expect(bible.get_by_role('alert').filter(has_text='Local draft checkpoint failed')).to_be_visible()
 assert page.evaluate("tryIdentity('actor-b')") is False, 'Failed local discard must not clear the draft or authorize identity change'
 page.evaluate('failLocal=false')
 bible.get_by_role('button',name='Retry local checkpoint',exact=True).click()
 expect(bible.get_by_role('status').filter(has_text='Private draft saved on this device')).to_be_visible()
 # Deliberate same-sequence preservation gates identity; new edits invalidate a previous decision.
 bible.get_by_role('button',name='Keep this exact draft privately on this device for my account').click()
 bible.get_by_role('textbox',name='Notes',exact=True).fill('Private newest sequence')
 assert page.evaluate("tryIdentity('actor-b')") is False
 bible.get_by_role('button',name='Keep this exact draft privately on this device for my account').click()
 expect(bible.get_by_role('status').filter(has_text='Private draft saved on this device')).to_be_visible()
 assert page.evaluate("tryIdentity('actor-b')") is True
 wait_ready();bible=open_bible()
 expect(bible.get_by_role('region',name='Private form recovery')).to_have_count(0)
 assert 'Private newest sequence' not in bible.inner_text()
 assert page.evaluate("calls.filter(c=>c.method!=='GET').length")==0
 assert page.evaluate("tryIdentity('actor-a')") is True
 page.wait_for_function("statuses.at(-1)?.tools?.some(item=>item.state==='recovery')")
 bible=open_bible();bible.get_by_role('button',name='Restore private draft for review').click()
 expect(bible.get_by_role('textbox',name='Notes',exact=True)).to_have_value('Private newest sequence')
 # Current server version changes: original CAS is retained, no forced/automatic rebase.
 page.request.post(os.environ['RECOVERY_URL']+'fixture/change')
 bible.get_by_role('button',name='Save changes',exact=True).click()
 expect(bible.get_by_role('alert').filter(has_text='shared record changed or rejected')).to_be_visible()
 expect(bible.get_by_role('button',name='Save changes',exact=True)).to_be_disabled()
 expect(bible.get_by_role('textbox',name='Notes',exact=True)).to_have_value('Private newest sequence')
 assert page.evaluate("control.current.flush()") is False
 bible.get_by_role('button',name='Read current shared record').click()
 expect(bible.get_by_text('Current shared fields',exact=False)).to_be_visible()
 assert 'Remote changed' in bible.get_by_role('region',name='Review private/shared conflict').inner_text()
 assert page.evaluate("calls.filter(c=>c.method==='PATCH').length")==1
 bible.get_by_role('textbox',name='Notes',exact=True).fill('Reviewed merge: Remote changed + my private note')
 bible.get_by_role('button',name='I reviewed and merged these fields; use this shared version as the next CAS base').click()
 bible.get_by_role('button',name='Save changes',exact=True).click()
 expect(bible.get_by_role('status').filter(has_text='Saved on the server')).to_be_visible()
 assert page.evaluate("calls.filter(c=>c.method==='PATCH').map(c=>c.body.baseVersion)")==[1,2]
 assert page.evaluate('control.current.isDirty()') is False
 # Restore itself also checks the freshly fetched version, before any attempted write.
 bible.get_by_role('textbox',name='Notes',exact=True).fill('Private awaiting divergent restore')
 expect(bible.get_by_role('status').filter(has_text='Private draft saved on this device')).to_be_visible()
 assert page.evaluate('control.current.flush()') is True
 page.reload();page.wait_for_function("statuses.at(-1)?.tools?.some(item=>item.state==='recovery')")
 page.request.post(os.environ['RECOVERY_URL']+'fixture/change')
 bible=open_bible();bible.get_by_role('button',name='Restore private draft for review').click()
 expect(bible.get_by_role('textbox',name='Notes',exact=True)).to_have_value('Private awaiting divergent restore')
 expect(bible.get_by_role('button',name='Save changes',exact=True)).to_be_disabled()
 expect(bible.get_by_role('region',name='Review private/shared conflict')).to_contain_text('Remote changed')
 assert page.evaluate("calls.filter(c=>c.method==='PATCH').length")==0
 bible.get_by_role('button',name='Discard private form changes',exact=True).click()
 page.wait_for_function('control.current.isDirty()===false')
 expect(bible.get_by_role('textbox',name='Notes',exact=True)).to_have_value('Remote changed')
 # New standalone world/note fields also recover; recovery never automatically POSTs them.
 bible.get_by_role('button',name='New entry',exact=True).click()
 bible.get_by_role('combobox',name='Entry type',exact=True).last.select_option('world')
 bible.get_by_label('Title',exact=True).fill('Private signal law')
 bible.get_by_role('textbox',name='World rules',exact=True).fill('Only copper reflects the signal.')
 expect(bible.get_by_role('status').filter(has_text='Private draft saved on this device')).to_be_visible()
 assert page.evaluate('control.current.flush()') is True
 page.reload()
 page.wait_for_function("statuses.at(-1)?.tools?.some(item=>item.state==='recovery')")
 bible=open_bible();expect(bible.get_by_role('region',name='Private form recovery')).to_contain_text('Private signal law')
 bible.get_by_role('button',name='Restore private draft for review').click()
 expect(bible.get_by_label('Title',exact=True)).to_have_value('Private signal law')
 expect(bible.get_by_role('textbox',name='World rules',exact=True)).to_have_value('Only copper reflects the signal.')
 assert page.evaluate("calls.filter(c=>c.method==='POST').length")==0
 bible.get_by_role('button',name='Create shared entry',exact=True).click()
 expect(bible.get_by_role('status').filter(has_text='Saved on the server')).to_be_visible()
 assert page.evaluate("calls.filter(c=>c.method==='POST').at(-1).body.entryKind")=='world'
 # Explicit discard is distinct from acknowledgement and clears only this private sequence.
 bible.get_by_role('textbox',name='Notes',exact=True).fill('Discard this unsent note')
 expect(bible.get_by_role('status').filter(has_text='Private draft saved on this device')).to_be_visible()
 bible.get_by_role('button',name='Discard private form changes',exact=True).click()
 expect(bible.get_by_role('textbox',name='Notes',exact=True)).not_to_have_value('Discard this unsent note')
 page.wait_for_function('control.current.isDirty()===false')
 assert page.evaluate("control.current.flush({reason:'identity'})") is True
 # A stored unopened recovery can also be explicitly discarded without a shared mutation.
 bible.get_by_role('textbox',name='Notes',exact=True).fill('Discard pending recovery after reload')
 expect(bible.get_by_role('status').filter(has_text='Private draft saved on this device')).to_be_visible()
 assert page.evaluate('control.current.flush()') is True
 page.reload();page.wait_for_function("statuses.at(-1)?.tools?.some(item=>item.state==='recovery')")
 bible=open_bible();assert page.evaluate("control.current.flush({reason:'identity'})") is False
 bible.get_by_role('button',name='Keep this exact recovery privately for my account during identity change').click()
 assert page.evaluate("control.current.flush({reason:'identity'})") is True
 assert page.evaluate('control.current.isDirty()') is True
 page.reload();page.wait_for_function("statuses.at(-1)?.tools?.some(item=>item.state==='recovery')")
 bible=open_bible();assert page.evaluate("control.current.flush({reason:'identity'})") is False
 bible.get_by_role('button',name='Discard this recovery checkpoint',exact=True).click()
 expect(bible.get_by_role('region',name='Private form recovery')).to_have_count(0)
 page.wait_for_function('control.current.isDirty()===false')
 assert page.evaluate("calls.filter(c=>c.method!=='GET').length")==0
 assert errors==[],errors
 context.close();browser.close()
print('PASS: actual AuthoringWorkspace slot/control + real IndexedDB; private draft reload/episode/identity, quota failure, explicit preservation, stale CAS review and new world draft')
`;

test('real mounted workspace recovers private Bible forms and guards navigation/identity/CAS',{timeout:120000},async()=>{
 const directory=await mkdtemp(join(tmpdir(),'writing-tools-recovery-'));
 const shared=new Map(),requests=[];let server;
 const record=ep=>{if(!shared.has(ep))shared.set(ep,{bibleId:'note-1',entryKind:'note',title:'Research',version:1,notes:'Shared original',events:[],aliases:[]});return shared.get(ep);};
 try{
  await build({stdin:{contents:fixture,resolveDir:new URL('..',import.meta.url).pathname.replace(/^\/([A-Za-z]:)/,'$1'),loader:'jsx'},bundle:true,format:'esm',jsx:'automatic',outfile:join(directory,'bundle.js'),loader:{'.js':'jsx'},define:{'process.env.NODE_ENV':'"production"'},logLevel:'silent'});
  server=createServer(async(req,res)=>{
   try{
    const url=new URL(req.url,'http://localhost');res.setHeader('Content-Type','application/json');
    if(url.pathname==='/bundle.js'||url.pathname==='/bundle.css'){res.setHeader('Content-Type',url.pathname.endsWith('.css')?'text/css':'text/javascript');res.end(await readFile(join(directory,url.pathname.slice(1))));return;}
    if(url.pathname==='/fixture/change'){const current=record('ep-1');current.version++;current.notes='Remote changed';res.end('{}');return;}
    const match=url.pathname.match(/^\/wire\/([^/]+)\/(.*)$/);
    if(match){
     const [,ep,tail]=match;let raw='';for await(const chunk of req)raw+=chunk;const body=raw?JSON.parse(raw):undefined;requests.push({ep,tail,method:req.method,body});
     let data;
     if(tail==='workspace')data={doc:{type:'doc',content:[{type:'paragraph',attrs:{bid:'body1',owner:null,created:null},content:[{type:'text',text:'A shared screenplay.'}]}]},docHash:'hash-1',revision:1,structure:{initialized:true,stale:false,version:1,scenes:[],lanes:[]},sources:{items:[]},branches:{items:[]},versions:{items:[]},baseline:{versionId:null,legacy:true,retained:false},capabilities:{writable:true}};
     else if(tail==='bible'&&req.method==='GET')data={items:[record(ep)],nextCursor:null};
     else if(tail==='bible/note-1'&&req.method==='GET')data=record(ep);
     else if(tail==='bible/note-1'&&req.method==='PATCH'){
      if(body.baseVersion!==record(ep).version){res.statusCode=409;res.end(JSON.stringify({code:'DRAMA_WRITING_CONFLICT',message:'Shared version changed'}));return;}
      Object.assign(record(ep),body.patch);record(ep).version++;data={bibleId:'note-1',version:record(ep).version,clientMutationId:body.clientMutationId};
     }else if(tail==='bible'&&req.method==='POST'){shared.set(ep,{...body,bibleId:'note-1',version:1});data=record(ep);}
     else{res.statusCode=404;data={code:'DRAMA_NOT_FOUND',message:'Unexpected fixture route '+tail};}
     res.end(JSON.stringify(data));return;
    }
    res.setHeader('Content-Type','text/html');res.end('<!doctype html><html><head><link rel="stylesheet" href="/bundle.css"></head><body><div id="root"></div><script type="module" src="/bundle.js"></script></body></html>');
   }catch(error){res.statusCode=500;res.end(JSON.stringify({message:error.message}));}
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const output=await new Promise((resolve,reject)=>{const child=spawn(process.env.PYTHON||'python',['-X','utf8','-c',driver],{env:{...process.env,RECOVERY_URL:`http://127.0.0.1:${server.address().port}/`}});let stdout='',stderr='';child.stdout.on('data',chunk=>stdout+=chunk);child.stderr.on('data',chunk=>stderr+=chunk);child.on('error',reject);child.on('exit',code=>resolve({code,stdout,stderr}));});
  assert.equal(output.code,0,output.stdout+'\n'+output.stderr);assert.match(output.stdout,/PASS: actual AuthoringWorkspace/);console.log(output.stdout.trim());
  assert.deepEqual(requests.filter(req=>req.method==='PATCH').map(req=>req.body.baseVersion),[1,2]);
 }finally{if(server)await new Promise(resolve=>server.close(resolve));await rm(directory,{recursive:true,force:true});}
});
