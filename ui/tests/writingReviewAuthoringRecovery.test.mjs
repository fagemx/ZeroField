import test from 'node:test';
import assert from 'node:assert/strict';
import {WritingOutlineRecovery} from '../src/writing/writingOutlineRecovery.js';
import {draftSceneMembership,replaceSceneBlocks,sceneBlocks} from '../src/writing/writingModel.js';
import {readFile} from 'node:fs/promises';
const memory=()=>{const rows=new Map();return {rows,list:async scope=>[...rows.values()].filter(row=>row.scope===scope),put:async(key,value)=>{rows.set(key,structuredClone({...value,key}));},remove:async(key,sequence)=>{if(rows.get(key)?.localSequence<=sequence)rows.delete(key);}};};
const structure=version=>({version,scenes:[{sceneKey:'s',summary:'original',storyTime:'day',plot:{lane:'original plot'}}],lanes:[{laneId:'lane',name:'Signal',order:1}]});
const create=async({journal=memory(),transport=async()=>{},tabId='one',actorId='actor',...options}={})=>{const form=new WritingOutlineRecovery({slug:'project',actorId,epId:'episode',journal,transport,tabId,delay:60000,maxDelay:60000,...options});form.refresh(structure(1));await form.discover();return form;};
test('J1 repeated scene replacements use draft membership and preserve surrounding identities/marks',()=>{
 const p=(bid,text)=>({type:'paragraph',attrs:{bid},content:[{type:'text',text,marks:[{type:'bold'}]}]});
 const doc={type:'doc',content:[p('before','Before'),p('selected','Action'),p('after','After')]};
 let scene={headingBid:null,blockBids:['selected']};
 let draft={type:'doc',content:[p('selected','Action'),p('new','')]};
 let full=replaceSceneBlocks(doc,scene,draft);scene=draftSceneMembership(scene,draft);
 draft={...draft,content:[p('selected','Action'),p('new','Typed'),p('paste','Pasted')]};
 full=replaceSceneBlocks(full,scene,draft);scene=draftSceneMembership(scene,draft);
 full=replaceSceneBlocks(full,scene,{...draft,content:[p('new','Newest')]});
 assert.deepEqual(full.content.map(n=>n.attrs.bid),['before','new','after']);assert.deepEqual(full.content[0],doc.content[0]);assert.deepEqual(full.content.at(-1),doc.content.at(-1));
 assert.equal(sceneBlocks(full,draftSceneMembership(scene,{content:[p('new','Newest')]})).content[0].content[0].text,'Newest');
});
test('outline queue freezes CAS and mutation body across lost ACK, while later edits await the next ACK',async()=>{
 const journal=memory(),calls=[];let release;
 const form=await create({journal,transport:async(_tail,_method,body)=>{calls.push(structuredClone(body));if(calls.length===1)await new Promise(resolve=>release=resolve);if(calls.length===1)throw Object.assign(new Error('ACK lost'),{status:500});return {...structure(body.baseVersion+1),clientMutationId:body.clientMutationId};}});
 try{
  form.change({sceneKey:'s',summary:'first'});const pending=form.save();while(!release)await new Promise(resolve=>setTimeout(resolve,0));
  form.change({sceneKey:'s',summary:'second',storyTime:'later',plot:{lane:'thread'}});release();assert.equal(await pending,false);
  assert.equal(form.state,'local_only');assert.equal(form.isDirty(),true);
  assert.equal(await form.flush({reason:'save',requireServer:true}),true);
  assert.deepEqual(calls[0],calls[1]);assert.equal(calls[2].baseVersion,2);assert.equal(calls[2].scenePatches[0].summary,'second');assert.notEqual(calls[2].clientMutationId,calls[1].clientMutationId);
  assert.equal(form.isDirty(),false);assert.equal(journal.rows.size,0);
 }finally{form.dispose();}
});
test('outline reload rejects metadata-only version divergence; restore does not rebase or publish',async()=>{
 const journal=memory(),calls=[];const first=await create({journal});
 first.change({sceneKey:'s',summary:'private local',plot:{lane:'draft thread'}});await first.checkpoint();first.dispose();
 const reopened=await create({journal,tabId:'second',transport:async(...args)=>calls.push(args)});
 try{
  assert.equal(reopened.state,'recovery');const row=reopened.recoveries[0];
  await reopened.restore(row,structure(2));assert.equal(reopened.base.version,1);assert.equal(reopened.state,'conflict');
  assert.equal(await reopened.flush({reason:'save',requireServer:true}),false);assert.equal(calls.length,0);assert.equal(reopened.draft.scenePatches[0].summary,'private local');
  assert.equal(await reopened.discard(structure(2)),true);assert.equal(reopened.base.version,2);assert.equal(reopened.isDirty(),false);
 }finally{reopened.dispose();}
});
test('same-version restore requires explicit save, and exact identity consent is invalidated by new input',async()=>{
 const journal=memory(),calls=[];const first=await create({journal});first.change({sceneKey:'s',summary:'review me'});await first.checkpoint();first.dispose();
 const reopened=await create({journal,tabId:'two',transport:async(_tail,_method,body)=>{calls.push(body);return {...structure(2),clientMutationId:body.clientMutationId};}});
 try{
  await reopened.restore(reopened.recoveries[0],structure(1));assert.equal(await reopened.flush(),true);assert.equal(await reopened.save(),false);assert.equal(calls.length,0);
  assert.equal(await reopened.flush({reason:'identity'}),false);await reopened.preserveIdentity();assert.equal(await reopened.flush({reason:'identity'}),true);
  reopened.change({sceneKey:'s',storyTime:'night'});assert.equal(await reopened.flush({reason:'identity'}),false);
  assert.equal(await reopened.flush({reason:'save',requireServer:true}),true);assert.equal(calls.length,1);assert.equal(calls[0].baseVersion,1);
 }finally{reopened.dispose();}
});
test('quota failure prevents navigation without ACK; auth stops retry; dirty drafts cannot silently refresh bases',async()=>{
 const journal=memory();journal.put=async()=>{throw new Error('quota');};let calls=0;
 const form=await create({journal,transport:async()=>{calls++;throw Object.assign(new Error('offline'),{status:500});}});
 try{
  form.change({sceneKey:'s',storyTime:'night'});assert.equal(await form.flush(),false);assert.equal(form.recoveryState().recoverable,false);assert.equal(form.state,'save_failed');assert.equal(form.refresh(structure(2)),false);assert.equal(form.base.version,1);
  form.transport=async()=>{calls++;throw Object.assign(new Error('denied'),{status:403});};assert.equal(await form.flush(),false);assert.equal(form.state,'auth_lost');const sent=calls;assert.equal(await form.save(),false);assert.equal(calls,sent);
 }finally{form.dispose();}
});
test('actor/episode journal isolation and conditional cleanup preserve a newer checkpoint from another tab',async()=>{
 const journal=memory(),one=await create({journal});one.change({sceneKey:'s',summary:'old'});await one.checkpoint();
 const other=await create({journal,actorId:'other',tabId:'other'});assert.equal(other.recoveries.length,0);
 const two=await create({journal,tabId:'two'});const old=two.recoveries[0];await two.preserveRecovery(old);assert.equal(await two.flush({reason:'identity'}),true);
 one.change({sceneKey:'s',summary:'newest'});await one.checkpoint();assert.equal(await two.flush({reason:'identity'}),false);
 await two.discardRecovery(old);assert.equal(journal.rows.get(old.key).draft.scenePatches[0].summary,'newest');
 one.dispose();two.dispose();other.dispose();
});
test('initial journal denial still permits controlled typing and a real server ACK; no device backup is invented',async()=>{
 const journal=memory();journal.list=async()=>{throw new Error('IndexedDB denied');};journal.put=async()=>{throw new Error('IndexedDB denied');};
 const form=await create({journal,transport:async(_tail,_method,body)=>({...structure(2),clientMutationId:body.clientMutationId})});
 try{form.change({sceneKey:'s',summary:'Still editable'});assert.equal(form.isDirty(),true);assert.equal(form.recoveryState().recoverable,false);assert.equal(await form.flush({reason:'save',requireServer:true}),true);assert.equal(form.state,'saved');assert.equal(form.isDirty(),false);}finally{form.dispose();}
});
test('lane-local bilingual additions have matching semantic keys and interpolation variables',async()=>{
 const en=JSON.parse(await readFile(new URL('../src/writing/locales/review1-authoring.en.json',import.meta.url)));
 const zh=JSON.parse(await readFile(new URL('../src/writing/locales/review1-authoring.zh-TW.json',import.meta.url)));
 assert.deepEqual(Object.keys(en).sort(),Object.keys(zh).sort());for(const key of Object.keys(en)){assert.ok(en[key]&&zh[key]);assert.deepEqual([...en[key].matchAll(/{{\w+}}/g)].map(m=>m[0]),[...zh[key].matchAll(/{{\w+}}/g)].map(m=>m[0]));}
});
