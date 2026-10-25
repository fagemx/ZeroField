import test from 'node:test';
import assert from 'node:assert/strict';
import { WritingPersistence } from '../src/writing/writingPersistence.js';
import { storyRequest } from '../src/storyModel.js';
import { createActorBoundRequest } from '../src/writing/writingTransport.js';
const doc=text=>({type:'doc',content:[{type:'paragraph',attrs:{bid:'base'},content:[{type:'text',text}]}]});
const initial={doc:doc('same text'),docHash:'H',version:1,structure:{chapters:[]},composition:{mediumLens:'cinema'}};
function journal(){const rows=new Map();return {rows,async list(){return [...rows.values()];},async put(key,value){rows.set(key,structuredClone({...value,key}));},async remove(key){rows.delete(key);}};}
function queue(extra={}){return new WritingPersistence({resourceRef:{kind:'source',mode:'novel'},initial,journal:journal(),scope:'actor-A',tabId:'one',delay:60000,maxDelay:60000,transport:async()=>{throw new Error('unexpected upload');},...extra});}

test('expected actor option is serialized even for reads, without replacing bearer/CSRF headers',async()=>{
 const original=globalThis.fetch;const calls=[];
 globalThis.fetch=async(url,options)=>{calls.push(options);return new Response(JSON.stringify({data:{}}));};
 try{await storyRequest('/episodes/e/writing/sources/novel','PUT',{}, {expectedActorId:'actor-A',headers:{Authorization:'Bearer explicit'}});await storyRequest('/episodes/e/writing/workspace','GET',undefined,{expectedActorId:'actor-A'});
 for(const call of calls)assert.equal(call.headers.get('X-Writing-Expected-Actor'),'actor-A');
 assert.equal(calls[0].headers.get('Authorization'),'Bearer explicit');assert.equal(calls[0].headers.get('X-Requested-With'),'projects');
 }finally{globalThis.fetch=original;}
});

test('disposed late ACK cannot erase private recovery or advance its base',async()=>{
 const local=journal();let release,started;const ready=new Promise(resolve=>started=resolve);
 const p=queue({journal:local,transport:async(_tail,_method,body)=>{started();await new Promise(resolve=>release=resolve);return {...initial,version:2,doc:body.doc,docHash:'ACK',clientMutationId:body.clientMutationId};}});
 p.change(doc('A private unsynced novel'));const saving=p.save();await ready;p.dispose();release();await saving;await p.journalWork;
 assert.equal(p.base.version,1);assert.equal(p.isDirty(),true);assert.equal(local.rows.size,1);assert.match(JSON.stringify([...local.rows.values()]),/A private unsynced novel/);
});

for(const kind of ['source','branch'])test(`${kind} metadata-only recovery must not silently borrow the current server CAS version`,async()=>{
 const local=journal(),ref=kind==='source'?{kind,mode:'novel'}:{kind,id:'branch'};
 const old=queue({journal:local,resourceRef:ref});old.changeMetadata({structure:{chapters:[{title:'device chapter'}]},composition:{mediumLens:'animation'}});await old.checkpoint();old.dispose();
 const current=queue({journal:local,resourceRef:ref,tabId:'two',initial:{...initial,version:2,structure:{chapters:[{title:'server chapter'}]},composition:{mediumLens:'manga'}}});
 try{const [entry]=await current.discover();await current.restore(entry);
 assert.equal(current.state,'conflict');assert.equal(current.base.version,1);assert.equal(current.conflict.metadataOnly,true);assert.equal(await current.save(),false);assert.equal(current.makePending().body.baseVersion,1);
 const checkpoint=local.rows.get(current.key);assert.equal(checkpoint.baseVersion,entry.baseVersion);assert.equal(checkpoint.baseStructureFingerprint,entry.baseStructureFingerprint);assert.equal(checkpoint.baseCompositionFingerprint,entry.baseCompositionFingerprint);
 }finally{current.dispose();}
});

test('session disposal aborts pending work, refuses reconnect and drops a late private read',async()=>{
 let release,options,calls=0;const bound=createActorBoundRequest('A',async(_path,_method,_body,sent)=>{calls++;options=sent;await new Promise(resolve=>release=resolve);return {privateText:'B must not receive this'};});
 const reading=bound('/episodes/e/writing/sources/novel');bound.dispose();assert.equal(options.signal.aborted,true);release();await assert.rejects(reading,{name:'AbortError'});await assert.rejects(bound('/episodes/e/writing/sources/novel'),{name:'AbortError'});assert.equal(calls,1);assert.equal(options.expectedActorId,'A');
});
test('identity mismatch stops the entire mounted request session before another replay',async()=>{
 let calls=0,lost=0;const bound=createActorBoundRequest('A',async()=>{calls++;throw Object.assign(new Error('identity mismatch'),{status:401,code:'DRAMA_WRITING_IDENTITY_MISMATCH'});},()=>lost++);
 await assert.rejects(bound('/episodes/e/writing/previews','POST',{}),{status:401});await assert.rejects(bound('/episodes/e/writing/previews','POST',{}),{name:'AbortError'});assert.equal(calls,1);assert.equal(lost,1);
});
test('metadata fingerprint changes require a choice even when a version is incorrectly unchanged',async()=>{
 const local=journal(),old=queue({journal:local});old.change(doc('device text'));await old.checkpoint();old.dispose();
 const current=queue({journal:local,tabId:'two',initial:{...initial,composition:{mediumLens:'storybook'}}});
 try{const [entry]=await current.discover();await current.restore(entry);assert.equal(current.state,'conflict');assert.equal(current.conflict.metadata,true);}finally{current.dispose();}
});
for(const kind of ['source','branch'])for(const keepMetadata of [false,true])test(`${kind} recovery only rebases after explicit choice (keepMetadata=${keepMetadata})`,async()=>{
 const resourceRef=kind==='source'?{kind,mode:'novel'}:{kind,id:'branch'};
 const local=journal(),old=queue({journal:local,resourceRef});old.changeMetadata({composition:{mediumLens:'manju'}});await old.checkpoint();old.dispose();
 const server={...initial,version:2,composition:{mediumLens:'storybook'}},current=queue({journal:local,resourceRef,tabId:'two',initial:server});
 try{const [entry]=await current.discover();await current.restore(entry);await current.resolveWithCurrentBase(current.doc,server,{keepMetadata});assert.equal(current.base.version,2);assert.equal((current.pending || current.makePending()).body.composition.mediumLens,keepMetadata?'manju':'storybook');assert.equal(current.conflict,null);}finally{current.dispose();}
});
test('unchanged hash with a coalesced mainline revision remains restorable',async()=>{
 const local=journal(),old=queue({journal:local,resourceRef:{kind:'working'}});old.change(doc('device text'));await old.checkpoint();old.dispose();
 const current=queue({journal:local,resourceRef:{kind:'working'},tabId:'two',initial:{...initial,version:2}});
 try{const [entry]=await current.discover();await current.restore(entry);assert.equal(current.state,'dirty');assert.equal(current.conflict,undefined);}finally{current.dispose();}
});
test('pre-repair journals without metadata fingerprints still conflict on private version divergence',async()=>{
 const local=journal(),old=queue({journal:local});old.change(doc('legacy device edit'));await old.checkpoint();old.dispose();
 const entry=local.rows.get(old.key);for(const key of ['baseStructure','baseComposition','baseStructureFingerprint','baseCompositionFingerprint'])delete entry[key];
 const current=queue({journal:local,tabId:'two',initial:{...initial,version:2}});
 try{const [entry]=await current.discover();await current.restore(entry);assert.equal(current.state,'conflict');assert.equal(current.base.version,1);assert.equal(current.makePending().body.baseVersion,1);}finally{current.dispose();}
});
test('working recovery continues to compare content hashes, not coalesced revision numbers',async()=>{
 const local=journal(),ref={kind:'working'},old=queue({journal:local,resourceRef:ref});old.change(doc('device edit'));await old.checkpoint();old.dispose();
 const current=queue({journal:local,resourceRef:ref,tabId:'two',initial:{...initial,doc:doc('remote edit'),docHash:'remote-H',version:1}});
 try{const [entry]=await current.discover();await current.restore(entry);assert.equal(current.state,'conflict');}finally{current.dispose();}
});
