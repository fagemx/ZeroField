import test from 'node:test';
import assert from 'node:assert/strict';
import {assetReferences, assetVariants, buildAssetLookup, resolveAssetReference} from '../src/studioModel.js';
import {replaceAssetVariant, sceneKey, selectedTake, episodeId, shotId} from '../src/storyModel.js';
import {sheetViewModel} from '../src/sheetViews.js';
import {tablesOf} from '../src/sheetModel.js';

const cell = value => ({type:'tableCell',content:[{type:'paragraph',content:value ? [{type:'text',text:value}] : []}]});
const table = (headers, rows, types=[]) => ({type:'table',attrs:{bid:'btable',column_types:types},content:[
  {type:'tableRow',attrs:{bid:'bhead'},content:headers.map(h => ({...cell(h),type:'tableHeader'}))},
  ...rows.map((r,i) => ({type:'tableRow',attrs:{bid:'brow'+i},content:r.map(cell)}))]});

test('wardrobe tags recognize colon/hash, resolve exact images and inherit base thumbnails', () => {
  const row = {cells:[{value:'@CAST-01:night @CAST-01#night @SET-01 @CAST-010'}]};
  assert.deepEqual(assetReferences(row), ['CAST-01:NIGHT','SET-01','CAST-010']);
  const doc = {type:'doc',content:[table(['Asset ID','Name','Appearance','Reference Image'],[
    ['CAST-01','Actor','Base','![Image](/projects/api/demo/assets/pa_'+'a'.repeat(32)+')'],
    ['CAST-01:night','Night','Jacket',''],
  ],['text','text','text','image'])]};
  const lookup = buildAssetLookup([{key:'soul-cast',doc}]);
  assert.equal(lookup['CAST-01:NIGHT'].value,lookup['CAST-01'].value);
  assert.equal(resolveAssetReference('CAST-01:DAMAGED', lookup).value,lookup['CAST-01'].value);
  assert.deepEqual(assetVariants('CAST-01:NIGHT',lookup),['CAST-01','CAST-01:NIGHT']);
});

test('variant switching changes only complete asset tokens', () => {
  assert.equal(replaceAssetVariant('@CAST-01 @CAST-010 @CAST-01:damaged','CAST-01','CAST-01:night'), '@CAST-01:night @CAST-010 @CAST-01:damaged');
  assert.equal(replaceAssetVariant('@CAST-01:night @CAST-01:NIGHT','CAST-01:NIGHT','CAST-01'), '@CAST-01 @CAST-01');
  assert.equal(replaceAssetVariant('@CAST-01#night','CAST-01:NIGHT','CAST-01'), '@CAST-01');
});

test('Meso groups scenes without losing original row indices and supports explicit Scene columns', () => {
  const parsed = tablesOf({type:'doc',content:[table(['Shot','Prompt','Status'],[
    ['SC01-S01','@CAST-01','Queued'],['SC02-S01','Exit','Approved'],['SC01-S02','Arrival','Queued'],
  ],['text','text','status'])]})[0];
  const model = sheetViewModel(parsed, parsed.rows);
  assert.deepEqual(model.sceneGroups.map(g => [g.key,g.cards.length]),[['SC01',2],['SC02',1]]);
  assert.deepEqual(model.sceneGroups[0].cards.map(c => c.index),[0,2]);
  assert.equal(sceneKey({headers:['Shot','Scene']},{cells:[{value:'S01'},{value:'Observatory'}]}),'Observatory');
});

test('Micro take selection is immutable and leaves exactly one active candidate', () => {
  const takes = [{videoId:'vd_a',selected:true},{videoId:'vd_b',selected:false}];
  assert.deepEqual(selectedTake(takes,'vd_b').map(t => t.selected),[false,true]);
  assert.equal(takes[0].selected,true);
  assert.equal(episodeId('demo',2),'ep_demo_02');
  assert.equal(shotId('demo','brow1'),'sh_demo_brow1');
});

test('allocation preflight wire paths and dispatch use the reviewed immutable assignment IDs', async () => {
  const {allocationPath, escalationPath, allocationDispatchBody} = await import('../src/storyModel.js');
  assert.equal(allocationPath('demo','ep_demo_02'),'/projects/pj_demo/episodes/ep_demo_02/shots:plan-allocation');
  assert.equal(escalationPath('demo','ep_demo_02','sh_demo_b1'),'/projects/pj_demo/episodes/ep_demo_02/shots/sh_demo_b1:escalate');
  assert.throws(()=>allocationDispatchBody({ready:false},'deadline_rush','hybrid_studio'));
  const plan={ready:true,allocationId:'al_one',allocations:[{shotId:'sh_demo_b1',assignedCardId:'custom-card'}]};
  assert.deepEqual(allocationDispatchBody(plan,'deadline_rush','hybrid_studio'),{allocationId:'al_one',shotIds:['sh_demo_b1'],budgetMode:'deadline_rush',productionPolicy:'hybrid_studio'});
  assert.equal(plan.allocations[0].assignedCardId,'custom-card');
});
