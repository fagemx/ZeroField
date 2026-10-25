// Parent-frozen impact-interface v1. This adapter does not infer source mappings.
export const impactContractVersion = 1;
export function impactRequest(options) {
  const allowed=['targetRef','expectedSourceHash','confirmBaseline','shotIds','bindings','breakdownMode'];
  if(!options||Object.keys(options).some(key=>!allowed.includes(key)))throw new TypeError('Unknown impact request field');
  const {targetRef,expectedSourceHash,confirmBaseline,shotIds,bindings,breakdownMode}=options;
  if(!targetRef||!['working','version'].includes(targetRef.kind)||Object.keys(targetRef).some(key=>!['kind','id'].includes(key))||targetRef.kind==='version'&&!targetRef.id||targetRef.kind==='working'&&targetRef.id!==undefined)throw new TypeError('Impact target must be working or a version');
  if(typeof expectedSourceHash!=='string'||!expectedSourceHash||typeof confirmBaseline!=='boolean')throw new TypeError('Impact requires source hash and baseline choice');
  const result={kind:'impact',targetRef:{...targetRef},expectedSourceHash,confirmBaseline};
  if(shotIds!==undefined){if(!Array.isArray(shotIds)||!shotIds.length||new Set(shotIds).size!==shotIds.length||shotIds.some(id=>typeof id!=='string'||!id))throw new TypeError('Choose distinct shots');result.shotIds=[...shotIds];}
  if(bindings!==undefined){
    const seen=new Set();
    if(!Array.isArray(bindings))throw new TypeError('Bindings must be explicit choices');
    result.bindings=bindings.map(binding=>{
      if(!binding||Object.keys(binding).some(key=>!['shotId','sceneKeys','beatKeys'].includes(key))||typeof binding.shotId!=='string'||!binding.shotId||seen.has(binding.shotId))throw new TypeError('Invalid explicit shot binding');
      for(const key of ['sceneKeys','beatKeys'])if(!Array.isArray(binding[key])||new Set(binding[key]).size!==binding[key].length||binding[key].some(id=>typeof id!=='string'||!id))throw new TypeError('Invalid stable source keys');
      if(!binding.sceneKeys.length)throw new TypeError('Choose an explicit source scene');
      seen.add(binding.shotId);return {shotId:binding.shotId,sceneKeys:[...binding.sceneKeys],beatKeys:[...binding.beatKeys]};
    });
  }
  if(breakdownMode!==undefined)result.breakdownMode=breakdownMode;
  return result;
}
export function impactProposal(preview) {
  const value=preview?.proposedChanges;
  if(preview?.kind!=='impact'||!value||Array.isArray(value)||!['shots','additions','assetChanges'].every(key=>Array.isArray(value[key]))||!Array.isArray(preview.allowedActions)||preview.allowedActions.some(action=>typeof action.actionId!=='string'||!['update_text','keep_shot','leave_unresolved','bind_source','add_shot'].includes(action.kind))||typeof value.canApply!=='boolean'||typeof value.confirmBaseline!=='boolean')throw new TypeError('Unsupported frozen impact proposal');
  return value;
}
// Additive readonly freshness: aggregate stale is not authority for unrelated rows.
export function impactFreshness(preview) {
  const additive=typeof preview.sharedStale==='boolean'&&Array.isArray(preview.staleActionIds)&&preview.staleActionIds.every(id=>typeof id==='string');
  return {sharedStale:additive?preview.sharedStale:!!preview.stale,staleActionIds:additive?[...preview.staleActionIds]:[],legacy:!additive};
}
export function toggleImpactAction(preview,selected,actionId,checked) {
  const action=preview.allowedActions?.find(item=>item.actionId===actionId);
  if(!action)throw new TypeError('Unknown frozen impact action');
  const freshness=impactFreshness(preview);
  if(checked&&(freshness.sharedStale||freshness.staleActionIds.includes(actionId)))throw new TypeError('Repreview this stale action');
  const rest=selected.filter(item=>item.actionId!==actionId&&(!checked||!action.shotId||preview.allowedActions.find(allowed=>allowed.actionId===item.actionId)?.shotId!==action.shotId));
  return checked?[...rest,{actionId,...(action.kind==='update_text'?{fields:[...(action.fields || [])]}:{})}]:rest;
}
export function impactSelection(preview,selected) {
  if(!impactProposal(preview).canApply)throw new TypeError('This target is compare-only');
  if(!Array.isArray(selected)||!selected.length)throw new TypeError('Choose at least one frozen action');
  const freshness=impactFreshness(preview);
  if(freshness.sharedStale)throw new TypeError('Shared source changed; create a fresh preview');
  const seen=new Set(),shots=new Set();
  return {actions:selected.map(item=>{
    if(Object.keys(item).some(key=>!['actionId','kind','fields'].includes(key)))throw new TypeError('Only frozen action identity and fields can be selected');
    if(freshness.staleActionIds.includes(item.actionId))throw new TypeError('Selected row changed; create a fresh preview');
    const action=preview.allowedActions?.find(action=>action.actionId===item.actionId);
    if(!action||item.kind!==undefined&&item.kind!==action.kind||seen.has(item.actionId)||action.shotId&&shots.has(action.shotId))throw new TypeError('Select one frozen action per shot');
    seen.add(item.actionId);if(action.shotId)shots.add(action.shotId);
    const result={actionId:item.actionId};
    if(item.fields!==undefined){
      if(action.kind!=='update_text'||!Array.isArray(item.fields)||!item.fields.length||new Set(item.fields).size!==item.fields.length||item.fields.some(field=>!action.fields?.includes(field)))throw new TypeError('Select a nonempty unique frozen field subset');
      result.fields=[...item.fields];
    }
    return result;
  })};
}
