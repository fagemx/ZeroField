import test from 'node:test';
import assert from 'node:assert/strict';
import {WritingOutlineRecovery,outlineReviewFields} from '../src/writing/writingOutlineRecovery.js';
import {draftSceneMembership,replaceSceneBlocks,sceneBlocks,sceneSliceBoundary,sceneSliceBlocks,replaceSceneSlice} from '../src/writing/writingModel.js';
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
 const form=await create({journal,transport:async(_tail,_method,body)=>{calls.push(structuredClone(body));if(calls.length===1)await new Promise(resolve=>release=resolve);if(calls.length===1)throw Object.assign(new Error('ACK lost'),{status:500});const ack=structure(body.baseVersion+1);for(const patch of body.scenePatches)Object.assign(ack.scenes.find(scene=>scene.sceneKey===patch.sceneKey),patch);return {...ack,clientMutationId:body.clientMutationId};}});
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
test('N1 outside-anchor projection includes insert-before/after and never moves an unselected block',()=>{
 const node=(bid,text=bid)=>({type:'paragraph',attrs:{bid},content:[{type:'text',text,marks:[{type:'italic'}]}]});
 const base={type:'doc',content:['a','ha','hb','b','hc','c'].map(id=>node(id))},scene={headingBid:'hb',blockBids:['b']};
 const boundary=sceneSliceBoundary(base,scene),draft={...base,content:[...base.content.slice(0,3),node('new-before'),base.content[3],node('new-after'),...base.content.slice(4)]};
 assert.deepEqual(sceneSliceBlocks(draft,boundary).content.map(n=>n.attrs.bid),['hb','new-before','b','new-after']);
 const partial=sceneSliceBlocks(draft,boundary);partial.content[2]=node('b','edited');const replaced=replaceSceneSlice(draft,boundary,partial);
 assert.deepEqual(replaced.content.map(n=>n.attrs.bid),draft.content.map(n=>n.attrs.bid));assert.deepEqual(replaced.content.at(-1),base.content.at(-1));
 const inverted={...draft,content:[base.content[4],...draft.content.filter(n=>n.attrs.bid!=='hc')]};assert.equal(sceneSliceBlocks(inverted,boundary),null);assert.throws(()=>replaceSceneSlice(inverted,boundary,partial),/unresolved/);
});
test('N3 proof rejects touched metadata, plot-cell and stable identity divergence, not own body changes',()=>{
 const base={...structure(1),docHash:'doc1'};base.scenes[0].headingBid='heading';base.scenes[0].mapping='exact';
 const current=structuredClone(base);current.version=2;current.docHash='doc2';current.scenes[0].blockBids=['new-body'];
 const draft={scenePatches:[{sceneKey:'s',summary:'mine',plot:{lane:'my plot'}}],lanePatches:[]};
 assert.equal(outlineReviewFields(base,current,draft).every(field=>field.unchanged),true);
 current.scenes[0].plot.other='Remote additional plot cell';assert.equal(outlineReviewFields(base,current,draft).find(field=>field.field==='plot').unchanged,false);
 current.scenes[0].headingBid='different';assert.equal(outlineReviewFields(base,current,draft).some(field=>field.mergeable),false);
});
test('N3 ACK cannot rebase a queued field over concurrent metadata; conflict survives same-version recovery',async()=>{
 const journal=memory();let release;const sent=[];
 const form=await create({journal,transport:async(_tail,_method,body)=>{sent.push(body);await new Promise(resolve=>release=resolve);const ack=structure(2);ack.scenes[0].summary='sent summary';ack.scenes[0].storyTime='Remote changed time';return {...ack,clientMutationId:body.clientMutationId};}});
 form.change({sceneKey:'s',summary:'sent summary'});const saving=form.save();while(!release)await new Promise(resolve=>setTimeout(resolve,0));
 form.change({sceneKey:'s',storyTime:'My queued time'});release();await saving;
 assert.equal(form.state,'conflict');assert.equal(form.draft.scenePatches[0].storyTime,'My queued time');assert.equal(await form.flush({reason:'save'}),false);assert.equal(sent.length,1);form.dispose();
 const reopened=await create({journal,tabId:'reopened'});const remote=structure(2);remote.scenes[0].summary='sent summary';remote.scenes[0].storyTime='Remote changed time';
 await reopened.restore(reopened.recoveries[0],remote);assert.equal(reopened.state,'conflict');assert.equal(reopened.base.version,2);
 const review=reopened.reviewCurrent(remote),choices=Object.fromEntries(review.fields.map(field=>[field.path,'local']));
 assert.equal(await reopened.resolveReviewed(review,choices,{...remote,version:3}),false);
 assert.equal(await reopened.resolveReviewed(review,choices,remote),true);assert.equal(reopened.base.version,2);assert.equal(reopened.conflict,null);assert.equal(reopened.draft.scenePatches[0].storyTime,'My queued time');reopened.dispose();
});
test('N3 same metadata values alone do not authorize an unproven version swap or a frozen retry rewrite',async()=>{
 const remote={...structure(2),docHash:'other-doc'},journal=memory();let calls=0;
 const form=await create({journal,flushDocument:async()=>({safe:true,structure:remote,ownDocumentAdvance:false}),transport:async()=>{calls++;}});
 form.change({sceneKey:'s',summary:'mine'});assert.equal(await form.save(),false);assert.equal(form.base.version,1);assert.equal(form.state,'conflict');assert.equal(calls,0);
 const review=form.reviewCurrent(remote);form.change({sceneKey:'s',storyTime:'new input invalidates review'});assert.equal(await form.resolveReviewed(review,Object.fromEntries(review.fields.map(f=>[f.path,'local'])),remote),false);form.dispose();
});
test('lane-local bilingual additions have matching semantic keys and interpolation variables',async()=>{
 const en=JSON.parse(await readFile(new URL('../src/writing/locales/review2-authoring.en.json',import.meta.url)));
 const zh=JSON.parse(await readFile(new URL('../src/writing/locales/review2-authoring.zh-TW.json',import.meta.url)));
 assert.deepEqual(Object.keys(en).sort(),Object.keys(zh).sort());for(const key of Object.keys(en)){assert.ok(en[key]&&zh[key]);assert.deepEqual([...en[key].matchAll(/{{\w+}}/g)].map(m=>m[0]),[...zh[key].matchAll(/{{\w+}}/g)].map(m=>m[0]));}
});
