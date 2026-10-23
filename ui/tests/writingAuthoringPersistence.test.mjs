import test from 'node:test';
import assert from 'node:assert/strict';
import { WritingPersistence } from '../src/writing/writingPersistence.js';
import { journalScope,journalKey } from '../src/writing/writingJournal.js';
import { documentOps,mergeAcknowledged,textCounts,sceneBlocks,replaceSceneBlocks,allowedSelection,baselineState,stable } from '../src/writing/writingModel.js';
import { createTextStoryboardAction } from '../src/writing/writingTasks.js';
import { createWritingTransport,writingAction } from '../src/writing/writingTransport.js';
const paragraph=(id,text)=>({type:'paragraph',attrs:{bid:id,owner:null,created:null},...(text?{content:[{type:'text',text}]}:{})});
const doc=(...nodes)=>({type:'doc',content:nodes});
const initial={doc:doc(paragraph('base','before')),docHash:'hash0',version:1};
const scope=journalScope({origin:'http://localhost',slug:'film',actorId:'actor1',epId:'episode1',resourceKind:'working',resourceId:'main'});
function memoryJournal(){const entries=new Map();return {entries,async list(scope){return [...entries.values()].filter(entry=>entry.scope===scope);},async put(key,value){entries.set(key,structuredClone({...value,key}));},async remove(key,sequence=Infinity){if(entries.get(key)?.localSequence<=sequence)entries.delete(key);}};}
function queue(options={}){return new WritingPersistence({resourceRef:{kind:'working'},initial,scope,tabId:'tab1',journal:memoryJournal(),transport:async(_tail,_method,body)=>({clientMutationId:body.clientMutationId,docHash:'hash1',doc:doc(body.ops[0].node),savedAt:'2026-10-23T00:00:00Z'}),...options});}
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};

test('transport injects exact four argument route/options and retry retains action identity',async()=>{
 const calls=[];const transport=createWritingTransport('ep 1',async(...args)=>{calls.push(args);return 1;});const signal=new AbortController().signal;
 const action=writingAction(transport,'previews',{kind:'impact'},{signal});await action();await action();assert.equal(calls[0][0],'/episodes/ep%201/writing/previews');assert.equal(calls[0][3].signal,signal);assert.equal(calls[0][3].idempotencyKey,calls[1][3].idempotencyKey);assert.throws(()=>transport('../escape'));
});
test('block saves preserve marks/identities and allow deleting final text and empty document',()=>{
 const rich=doc({...paragraph('base','after'),content:[{type:'text',text:'after',marks:[{type:'bold'}]}]});const ops=documentOps(initial.doc,rich);assert.equal(ops[0].bid,'base');assert.deepEqual(ops[0].base,initial.doc.content[0]);assert.deepEqual(ops[0].node.content[0].marks,[{type:'bold'}]);assert.equal(documentOps(initial.doc,doc())[0].op,'del');assert.equal(documentOps(doc(),doc(paragraph('blank','')))[0].op,'put');
});
test('server ACK of older sequence never clears new text or newer journal; next save uses acknowledged base',async()=>{
 const wait=deferred(),calls=[],journal=memoryJournal();let first=true;
 const persistence=queue({journal,transport:async(_tail,_method,body)=>{calls.push(body);if(first){first=false;await wait.promise;}return {clientMutationId:body.clientMutationId,docHash:'hash'+calls.length,doc:doc(body.ops[0].node)};}});
 persistence.change(doc(paragraph('base','first')));const saving=persistence.save();await new Promise(resolve=>setTimeout(resolve,0));persistence.change(doc(paragraph('base','latest')));await persistence.journalWork;wait.resolve();await saving;
 assert.equal(persistence.doc.content[0].content[0].text,'latest');assert.equal(persistence.isDirty(),true);assert.equal(journal.entries.get(persistence.key).doc.content[0].content[0].text,'latest');assert.equal(await persistence.flush({requireServer:true}),true);assert.equal(calls[1].ops[0].base.content[0].text,'first');assert.equal(persistence.state,'saved');assert.equal(journal.entries.size,0);persistence.dispose();
});
test('network ACK loss reuses identical mutation body/key, then saves subsequent edits separately',async()=>{
 const calls=[];let fail=true;const persistence=queue({transport:async(...args)=>{calls.push(structuredClone(args));if(fail){fail=false;throw new Error('Disconnected after write');}return {clientMutationId:args[2].clientMutationId,docHash:'h',doc:doc(args[2].ops[0].node)};}});
 persistence.change(doc(paragraph('base','first')));assert.equal(await persistence.save(),false);assert.equal(persistence.state,'local_only');persistence.change(doc(paragraph('base','second')));await persistence.flush({requireServer:true});assert.deepEqual(calls[0],calls[1]);assert.notEqual(calls[1][2].clientMutationId,calls[2][2].clientMutationId);assert.equal(persistence.doc.content[0].content[0].text,'second');persistence.dispose();
});
test('navigation can be locally safe while actions require a server ACK',async()=>{
 const persistence=queue({transport:async()=>{throw new Error('offline');}});persistence.change(doc(paragraph('base','offline')));assert.equal(await persistence.flush(),true);assert.equal(await persistence.flush({requireServer:true}),false);assert.equal(persistence.state,'local_only');persistence.dispose();
});
test('IDB denial plus network failure is not safe or saved',async()=>{
 const persistence=queue({journal:{async put(){throw new Error('quota');},async list(){throw new Error('denied');}},transport:async()=>{throw new Error('offline');}});persistence.change(doc());assert.equal(await persistence.flush(),false);assert.equal(persistence.state,'save_failed');assert.equal(persistence.recoveryState().recoverable,false);persistence.dispose();
});
test('401 and 403 stop upload/reconnect retries even when durably recoverable',async()=>{
 for(const status of [401,403]){let count=0;const persistence=queue({transport:async()=>{count++;throw Object.assign(new Error('Revoked'),{status});}});persistence.change(doc());assert.equal(await persistence.flush(),false);assert.equal(persistence.state,'auth_lost');await persistence.save();assert.equal(count,1);assert.equal(persistence.recoveryState().recoverable,true);persistence.dispose();}
});
test('HTTP 200 conflicts retain both copies and cannot falsely flush successfully',async()=>{
 const persistence=queue({transport:async(_tail,_method,body)=>({clientMutationId:body.clientMutationId,docHash:'h',doc:initial.doc,conflicts:[{bid:'base'}]})});persistence.change(doc(paragraph('base','mine')));assert.equal(await persistence.flush(),false);assert.equal(persistence.state,'conflict');assert.equal(persistence.doc.content[0].content[0].text,'mine');assert.deepEqual(persistence.conflict.server,initial.doc);persistence.dispose();
});
test('IME buffers all network work until compositionend, debounce and max interval are bounded',async()=>{
 const jobs=new Map();let index=0,calls=0;const clock={setTimeout(fn,ms){const id=++index;jobs.set(id,{fn,ms});return id;},clearTimeout(id){jobs.delete(id);}};
 const persistence=queue({clock,transport:async(_tail,_method,body)=>{calls++;return {clientMutationId:body.clientMutationId,docHash:'h',doc:doc(body.ops[0].node)};}});
 persistence.setComposing(true);persistence.change(doc(paragraph('base','中')));assert.equal(jobs.size,0);assert.equal(await persistence.flush({requireServer:true}),false);assert.equal(calls,0);persistence.setComposing(false);assert.deepEqual([...jobs.values()].map(job=>job.ms).sort((a,b)=>a-b),[800,5000]);persistence.change(doc(paragraph('base','中文')));assert.equal(jobs.size,2);await persistence.flush();assert.equal(calls,1);persistence.dispose();
});
test('recovery is explicitly compared and actor/episode/tab isolated; divergent base becomes conflict',async()=>{
 const journal=memoryJournal(),old=queue({journal,tabId:'old'});old.change(doc(paragraph('base','recovered')));await old.checkpoint();old.dispose();
 const current=queue({journal,tabId:'new',initial:{...initial,docHash:'remote',doc:doc(paragraph('base','remote'))}});const entries=await current.discover();assert.equal(entries.length,1);assert.equal(current.state,'recovery');assert.equal(await current.flush(),false);await current.restore(entries[0]);assert.equal(current.state,'conflict');assert.equal(journal.entries.has(old.key),false);assert.equal(journal.entries.has(current.key),true);
 const other=queue({journal,scope:journalScope({origin:'http://localhost',slug:'film',actorId:'actor2',epId:'episode1',resourceKind:'working',resourceId:'main'})});assert.equal((await other.discover()).length,0);assert.notEqual(journalKey(scope,'a'),journalKey(scope,'b'));current.dispose();other.dispose();
});
test('refresh does not drop pending local edits; late disposed ACK cannot notify the next editor',async()=>{
 const wait=deferred(),states=[];const persistence=queue({notify:state=>states.push(state),transport:async(_tail,_method,body)=>{await wait.promise;return {clientMutationId:body.clientMutationId,docHash:'ack',doc:doc(body.ops[0].node)};}});persistence.change(doc(paragraph('base','mine')));assert.equal(persistence.refresh({...initial,docHash:'new',doc:doc(paragraph('base','other'))}),false);const saving=persistence.save();await new Promise(resolve=>setTimeout(resolve,0));persistence.dispose();const before=states.length;wait.resolve();await saving;assert.equal(states.length,before);
});
test('private source saves empty documents with real version CAS, not script ops',async()=>{
 const calls=[];const persistence=queue({resourceRef:{kind:'source',mode:'novel'},transport:async(...args)=>{calls.push(args);return {clientMutationId:args[2].clientMutationId,docHash:'empty',version:2};}});persistence.change(doc());await persistence.flush({requireServer:true});assert.equal(calls[0][0],'sources/novel');assert.equal(calls[0][1],'PUT');assert.equal(calls[0][2].baseVersion,1);assert.deepEqual(calls[0][2].doc,doc());persistence.dispose();
});
test('scene and full views share a block model; unselected rich blocks survive scene editing',()=>{
 const source=doc(paragraph('one','first'),paragraph('two','second'));const scene={headingBid:'one',beats:[{blockBids:['one']}]};assert.deepEqual(sceneBlocks(source,scene),doc(source.content[0]));assert.deepEqual(replaceSceneBlocks(source,scene,doc(paragraph('one','edited'))).content[1],source.content[1]);assert.equal(textCounts(doc(paragraph('one','中文 Hello, world! 😀'))).words,4);
});
test('bounded ops batches save all blocks without losing unsent content',async()=>{
 let server={type:'doc',content:Array.from({length:420},(_,i)=>paragraph('block'+i,'old'))};let calls=0;
 const persistence=queue({initial:{doc:server,docHash:'start',version:1},transport:async(_tail,_method,body)=>{calls++;assert.ok(body.ops.length<=200);for(const op of body.ops){if(op.op==='put')server.content[server.content.findIndex(node=>node.attrs.bid===op.bid)]=op.node;}return {clientMutationId:body.clientMutationId,doc:structuredClone(server),docHash:'batch'+calls,conflicts:[]};}});
 persistence.change({type:'doc',content:server.content.map(node=>paragraph(node.attrs.bid,'new'))});assert.equal(await persistence.flush({requireServer:true}),true);assert.equal(calls,3);assert.equal(persistence.doc.content.length,420);assert.ok(persistence.doc.content.every(node=>node.content[0].text==='new'));persistence.dispose();
});
test('metadata-only source changes are durably recoverable and use CAS composition fields',async()=>{
 const journal=memoryJournal();const old=queue({journal,resourceRef:{kind:'source',mode:'novel'},initial:{...initial,structure:{chapters:[]},composition:{}},transport:async()=>{throw new Error('offline');}});old.changeMetadata({composition:{mediumLens:'cinema',genreLens:'suspense'}});await old.save();old.dispose();const next=queue({journal,tabId:'other',resourceRef:{kind:'source',mode:'novel'},initial:{...initial,structure:{chapters:[]},composition:{}}});assert.equal((await next.discover()).length,1);assert.equal(next.recoveryState().recoverable,true);next.dispose();
});
test('text-only confirm/build keeps per-step replay keys and never sends a whole-script overwrite or media generation',async()=>{
 const calls=[];let ambiguous=true;const request=async(path,method,body,options)=>{calls.push({path,method,body,options});if(path.endsWith('asset-extractions')&&ambiguous){ambiguous=false;throw new Error('lost ACK');}return {taskId:'text',status:'SUCCEEDED',result:{ok:true}};};const action=createTextStoryboardAction(request,'ep1');await assert.rejects(action);assert.deepEqual(await action(),{ok:true});assert.equal(calls[0].options.idempotencyKey,calls[1].options.idempotencyKey);assert.notEqual(calls[1].options.idempotencyKey,calls[2].options.idempotencyKey);assert.equal(calls.some(call=>call.path.includes('generations') || call.path.endsWith('/script')),false);
});
test('impact actions/fields can only be frozen subset and legacy baseline is honest',()=>{
 const preview={allowedActions:[{actionId:'a',kind:'update_text',fields:['dialogue']}]};assert.deepEqual(allowedSelection(preview,[{actionId:'a',kind:'update_text',fields:['dialogue']}]).actions[0].fields,['dialogue']);assert.throws(()=>allowedSelection(preview,[{actionId:'a',kind:'update_text',fields:['camera']}]));assert.throws(()=>allowedSelection(preview,[{actionId:'b',kind:'add_shot'}]));assert.equal(baselineState({confirmedHash:'old',scriptDirty:true}).kind,'legacy');assert.equal(baselineState({}).kind,'none');
});
