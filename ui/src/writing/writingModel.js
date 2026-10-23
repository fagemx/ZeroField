import { bidOf, computeOps, stable, mergeServer } from '../blocks.js';
import { impactSelection } from './writingImpactAdapter.js';
export { stable };
export const emptyDoc = () => ({type:'doc',content:[]});
export const clone = value => structuredClone(value);
export const cleanMap = doc => new Map((doc.content || []).map(node => [bidOf(node),stable(node)]));
export function documentText(node) {
  if (node?.type === 'text') return node.text || '';
  if (node?.type === 'hardBreak') return '\n';
  const content = node?.content || [];
  return content.map(documentText).join(node?.type === 'doc' ? '\n' : '');
}
export function textCounts(doc) {
  const text = documentText(doc);
  const cjk = text.match(/[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]/gu) || [];
  const latin = text.replace(/[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]/gu,' ').match(/[\p{L}\p{N}]+(?:['’-][\p{L}\p{N}]+)*/gu) || [];
  return {words:cjk.length + latin.length,characters:Array.from(text).length};
}
export function documentOps(base, current) {
  const ops = computeOps({server:base,clean:cleanMap(base),current});
  // Unlike the legacy editor, an intentionally empty new paragraph is savable.
  const existing = new Set((base.content || []).map(bidOf));
  let after = null;
  for (const node of current.content || []) {
    const bid = bidOf(node);
    if (bid && !existing.has(bid) && !ops.some(op => op.bid === bid)) ops.push({op:'put',bid,after,node,base:null});
    if (bid) after = bid;
  }
  return ops;
}
export function mergeAcknowledged(server, sent, current) {
  if (stable(sent) === stable(current)) return server;
  const result = mergeServer({server,clean:cleanMap(sent),current});
  // Preserve a local reorder made after submission; remote-only blocks stay present.
  const sentOrder = (sent.content || []).map(bidOf);
  const localOrder = (current.content || []).map(bidOf);
  if (stable(sentOrder) !== stable(localOrder)) {
    const byId = new Map(result.doc.content.map(node=>[bidOf(node),node]));
    result.doc.content = [...localOrder.filter(id=>byId.has(id)).map(id=>byId.get(id)),...result.doc.content.filter(node=>!localOrder.includes(bidOf(node)))];
  }
  return result.doc;
}
export const semanticEnumKey=(category,value)=>category+String(value).split('_').map(part=>part[0]?.toUpperCase()+part.slice(1)).join('');
export const refKey = ref => ref.kind === 'source' ? `source:${ref.mode}` : `${ref.kind}:${ref.id || 'main'}`;
export function sceneBlocks(doc, scene) {
  if (!scene) return doc;
  const bids = new Set([scene.headingBid,...(scene.blockBids || []),...(scene.beats || []).flatMap(beat=>beat.blockBids || [])]);
  return {...doc,content:(doc.content || []).filter(node=>bids.has(bidOf(node)))};
}
// A selected scene is an editing slice, not a fresh projection through server blockBids.
// Keep every local block (including empty inserts and split headings) until a fresh load.
export function draftSceneMembership(scene,partial) {
  return {...scene,headingBid:null,blockBids:(partial.content || []).map(bidOf),beats:[]};
}
export function replaceSceneBlocks(doc, scene, partial) {
  const selected = sceneBlocks(doc,scene).content;
  const bids = new Set(selected.map(bidOf));
  const at = doc.content.findIndex(node=>bids.has(bidOf(node)));
  if (at < 0) throw new Error('Scene mapping is unresolved');
  const content = doc.content.filter(node=>!bids.has(bidOf(node)));
  content.splice(at,0,...partial.content);
  return {...doc,content};
}
export function sourceStructureForDoc(structure,doc) {
  const bids=new Set((doc.content || []).map(bidOf));
  const walk=items=>(items || []).map(item=>({...item,blockBids:(item.blockBids || []).filter(bid=>bids.has(bid)),...(item.sections?{sections:walk(item.sections)}:{})}));
  return {...structure,...(structure.chapters?{chapters:walk(structure.chapters)}:{}),...(structure.sections?{sections:walk(structure.sections)}:{})};
}
export function baselineState(workspace) {
  const baseline = workspace?.baseline;
  if (baseline?.versionId || baseline?.productionScriptVersionId) return {kind:'snapshot',name:baseline.name || baseline.versionId || baseline.productionScriptVersionId,dirty:!!(baseline.scriptDirty ?? workspace.scriptDirty)};
  if (baseline?.confirmedHash || workspace?.confirmedHash) return {kind:'legacy',dirty:!!(baseline?.scriptDirty ?? workspace.scriptDirty)};
  return {kind:'none',dirty:!!workspace?.scriptDirty};
}
export function promotionProjection(preview) {
  const proposal=preview.proposedChanges || {};
  if(!proposal.sourceDoc)return proposal.doc;
  if(proposal.whole!==false)return proposal.sourceDoc;
  const keys=new Set((preview.allowedActions || []).filter(action=>['adopt_scene','add_scene'].includes(action.kind)).map(action=>action.sceneKey));
  const bids=new Set((proposal.sourceStructure?.scenes || []).filter(scene=>keys.has(scene.sceneKey)).flatMap(scene=>[scene.headingBid,...(scene.blockBids || [])]));
  return {...proposal.sourceDoc,content:(proposal.sourceDoc.content || []).filter(node=>bids.has(bidOf(node)))};
}
export function defaultImpactSelection(preview) {
  // Nothing destructive or manually overridden is preselected. Explicit review is safer.
  return {actions:[]};
}
export function allowedSelection(preview, selected) {
  if(preview.kind==='impact')return impactSelection(preview,selected);
  const actions = preview.allowedActions || [];
  return {actions:selected.map(item=>{
    const allowed = actions.find(action=>action.actionId===item.actionId && action.kind===item.kind);
    if (!allowed) throw new Error('Action is not in the frozen preview');
    const result = {actionId:item.actionId,kind:item.kind};
    if (item.fields) {
      if (item.fields.some(field=>!(allowed.fields || []).includes(field))) throw new Error('Field is not allowed');
      result.fields = item.fields;
    }
    return result;
  })};
}
