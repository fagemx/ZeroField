import test from 'node:test';
import assert from 'node:assert/strict';
import { impactRequest,impactProposal,impactSelection,toggleImpactAction,impactFreshness } from '../src/writing/writingImpactAdapter.js';
import { WritingToolControls } from '../src/writing/writingToolControls.js';
// Synthetic fixtures conform to parent-frozen impact-interface v1; NOT real backend evidence.
const preview=()=>({kind:'impact',previewId:'p',version:1,status:'pending',allowedActions:[{actionId:'u1',kind:'update_text',shotId:'shot1',fields:['description','dialogue'],defaultSelected:false},{actionId:'k1',kind:'keep_shot',shotId:'shot1'},{actionId:'b1',kind:'bind_source',shotId:'shot1'},{actionId:'l2',kind:'leave_unresolved',shotId:'shot2'},{actionId:'a1',kind:'add_shot',beatKeys:['beat-new']}],proposedChanges:{shots:[],additions:[],assetChanges:[],confirmBaseline:true,targetVersionId:null,canApply:true}});
test('synthetic W4 v1 request uses expectedSourceHash, fixed refs and explicitly selected bindings only',()=>{
 const options={targetRef:{kind:'working'},expectedSourceHash:'a'.repeat(64),confirmBaseline:true,shotIds:['shot1'],bindings:[{shotId:'shot1',sceneKeys:['scene1'],beatKeys:[]}],breakdownMode:'auto'};
 const result=impactRequest(options);assert.deepEqual(result,{kind:'impact',...options});options.bindings[0].sceneKeys.push('not-sent');assert.deepEqual(result.bindings[0].sceneKeys,['scene1']);assert.equal('expectedDocHash' in result,false);
 assert.throws(()=>impactRequest({...options,expectedDocHash:'guessed'}));assert.throws(()=>impactRequest({...options,targetRef:{kind:'branch',id:'private'}}));assert.throws(()=>impactRequest({...options,expectedSourceHash:undefined}));assert.throws(()=>impactRequest({...options,bindings:[{shotId:'shot1',sceneKeys:[],beatKeys:[]}]}));assert.deepEqual(impactRequest({targetRef:{kind:'version',id:'v'},expectedSourceHash:'hash',confirmBaseline:false}),{kind:'impact',targetRef:{kind:'version',id:'v'},expectedSourceHash:'hash',confirmBaseline:false});
});
test('synthetic W4 v1 response preserves shots/additions/assets object and compares noncurrent targets read-only',()=>{
 const frozen=preview();assert.equal(impactProposal(frozen),frozen.proposedChanges);assert.throws(()=>impactProposal({...frozen,proposedChanges:[]}));frozen.proposedChanges.canApply=false;assert.throws(()=>impactSelection(frozen,[{actionId:'k1'}]),/compare-only/);
});
test('synthetic frozen selection is actionId/optional field subset, one action per shot, no injected targets or text',()=>{
 const frozen=preview();assert.deepEqual(impactSelection(frozen,[{actionId:'u1',fields:['dialogue']},{actionId:'l2'},{actionId:'a1'}]),{actions:[{actionId:'u1',fields:['dialogue']},{actionId:'l2'},{actionId:'a1'}]});assert.deepEqual(impactSelection(frozen,[{actionId:'b1',kind:'bind_source'}]),{actions:[{actionId:'b1'}]});
 for(const selection of [[{actionId:'u1',fields:[]}],[{actionId:'u1',fields:['dialogue','dialogue']}],[{actionId:'u1',fields:['camera']}],[{actionId:'k1',fields:['dialogue']}],[{actionId:'u1'},{actionId:'k1'}],[{actionId:'k1'},{actionId:'k1'}],[{actionId:'u1',shotId:'shot2'}],[{actionId:'b1',sceneKeys:['invented']}],[{actionId:'u1',replacement:'injected'}]])assert.throws(()=>impactSelection(frozen,selection));
 assert.deepEqual(impactSelection(frozen,[{actionId:'u1'}]),{actions:[{actionId:'u1'}]});
});
test('synthetic manual update remains opt-in and UI toggles eliminate contradictory actions for one shot',()=>{
 const frozen=preview();let selected=[];assert.deepEqual(selected,[]);selected=toggleImpactAction(frozen,selected,'u1',true);assert.deepEqual(selected,[{actionId:'u1',fields:['description','dialogue']}]);selected=toggleImpactAction(frozen,selected,'k1',true);assert.deepEqual(selected,[{actionId:'k1'}]);selected=toggleImpactAction(frozen,selected,'l2',true);assert.equal(selected.length,2);selected=toggleImpactAction(frozen,selected,'k1',false);assert.deepEqual(selected,[{actionId:'l2'}]);
});
test('additive freshness rejects shared/selected stale rows, not unrelated fresh actions; legacy stale stays conservative',()=>{
 const frozen={...preview(),stale:true,sharedStale:false,staleActionIds:['l2']};assert.deepEqual(impactFreshness(frozen),{sharedStale:false,staleActionIds:['l2'],legacy:false});assert.deepEqual(impactSelection(frozen,[{actionId:'k1'}]),{actions:[{actionId:'k1'}]});assert.throws(()=>impactSelection(frozen,[{actionId:'l2'}]),/Selected row changed/);assert.throws(()=>toggleImpactAction(frozen,[],'l2',true));assert.deepEqual(toggleImpactAction(frozen,[{actionId:'l2'}],'l2',false),[]);
 assert.throws(()=>impactSelection({...frozen,sharedStale:true},[{actionId:'k1'}]),/Shared source/);const legacy={...preview(),stale:true};assert.equal(impactFreshness(legacy).legacy,true);assert.throws(()=>impactSelection(legacy,[{actionId:'k1'}]));assert.throws(()=>impactSelection({...legacy,sharedStale:false},[{actionId:'k1'}]));
});
const control=(state,flush=async()=>true)=>({flush,isDirty:()=>state.dirty,recoveryState:()=>({state:state.state,recoverable:state.recoverable})});
test('registered failed checkpoint blocks unsafe navigation even if a control incorrectly returns true',async()=>{
 const registry=new WritingToolControls(),state={dirty:true,state:'save_failed',recoverable:false};registry.register('note',control(state));assert.equal(await registry.flush(),false);assert.deepEqual(registry.summary({state:'saved',dirty:false,recoverable:false}),{state:'save_failed',dirty:true,recoverable:false,documentState:'saved',tools:[{key:'note',dirty:true,state:'save_failed',recoverable:false}]});
});
test('registered durable local checkpoint is navigable but never relabeled as server saved',async()=>{
 const registry=new WritingToolControls(),state={dirty:true,state:'local_only',recoverable:true};let options;registry.register('bible',control(state,async value=>{options=value;return true;}));assert.equal(await registry.flush(),true);assert.deepEqual(options,{reason:'navigation',requireServer:false});assert.equal(registry.summary({state:'saved',dirty:false,recoverable:false}).state,'local_only');assert.equal(registry.summary({state:'saved',dirty:false,recoverable:false}).documentState,'saved');assert.equal(registry.summary().dirty,true);assert.equal(registry.summary().recoverable,true);
});
test('requireServer does not flush unrelated tool forms; identity still requires explicit handling',async()=>{
 const registry=new WritingToolControls(),state={dirty:true,state:'local_only',recoverable:true};let calls=0,preserved=false;registry.register('private-note',control(state,async options=>{calls++;return options.reason!=='identity'||preserved;}));assert.equal(await registry.flush({requireServer:true}),true);assert.equal(calls,0);assert.equal(await registry.flush({reason:'identity'}),false);assert.equal(await registry.flush({reason:'identity',requireServer:true}),false);preserved=true;assert.equal(await registry.flush({reason:'identity'}),true);assert.equal(state.dirty,true);
});
test('old unregister cannot clear replacement; registry is scoped per identity and replacement during flush blocks',async()=>{
 const registry=new WritingToolControls(),state={dirty:false,state:'saved',recoverable:false},same=control(state);const old=registry.register('note',same),current=registry.register('note',same);old();assert.equal(registry.states().length,1);current();assert.equal(registry.states().length,0);registry.register('note',same);assert.equal(new WritingToolControls().states().length,0);
 let resolve;registry.register('note',control(state,()=>new Promise(done=>{resolve=done;})));const saving=registry.flush();registry.register('note',same);resolve(true);assert.equal(await saving,false);
});
