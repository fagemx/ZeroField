import test from 'node:test';
import assert from 'node:assert/strict';
import { META_CACHE, getMediaMeta } from '../src/mediaMeta.js';
import { benchLinks, buildAssetLookup, assetReferences, mediaStages, presetsFor, presetLabel, applyPreset, studioRunInput, queueStudioRun } from '../src/studioModel.js';
import { sheetViewModel } from '../src/sheetViews.js';
import { flowToCanvas } from '../src/flowModel.js';
import { setLocale } from '../src/i18n/index.js';

const cell=value=>({value});
const parsed={tableId:'shots',headers:['Shot','References','Keyframe','Cinema Shot'],table:{attrs:{column_ids:['id','refs','image','video'],column_types:['text','text','image','video']}},rows:[{rid:'r1',cells:[cell('SH-01'),cell('@CAST-01 @set-02 @CAST-01'),cell(''),cell('[video](https://example.org/take.mp4)')]}]};
const flow={revision:7,definition:{nodes:[
  {id:'script',scope:'once',capability:'llm',target:{tab_key:'brief'}},
  {id:'frame',scope:'rows',capability:'image_gen',row_source:{tab_key:'cinema',table_id:'shots'},target:{tab_key:'cinema',table_id:'shots',col_index:2}},
  {id:'movie',scope:'rows',capability:'video_gen',row_source:{tab_key:'cinema',table_id:'shots'},target:{tab_key:'cinema',table_id:'shots',col_index:3}},
],edges:[{source:'script',target:'frame'},{source:'frame',target:'movie'}]}};
const scope={tabKey:'cinema',tableId:'shots',columnIds:['id','refs','image','video'],rowIds:['r1'],singleStep:true,capability:'video_gen',col_index:3};

test('metadata requests are shared while pending and failed lookups can be retried',async()=>{
  META_CACHE.clear();let count=0,release;
  const fetchMeta=()=>{count++;return new Promise(resolve=>{release=resolve;});};
  const one=getMediaMeta('/asset',fetchMeta),two=getMediaMeta('/asset',fetchMeta);
  assert.equal(one,two);await Promise.resolve();assert.equal(count,1);release({content_type:'video/mp4'});
  assert.deepEqual(await one,{content_type:'video/mp4'});assert.equal(await getMediaMeta('/asset',fetchMeta),await one);assert.equal(count,1);
  await assert.rejects(getMediaMeta('/bad',()=>Promise.reject(new Error('offline'))),/offline/);
  assert.deepEqual(await getMediaMeta('/bad',()=>Promise.resolve({content_type:'image/png'})),{content_type:'image/png'});
});

test('video gallery keeps empty stages, distinct asset IDs and resolved cross-page references',()=>{
  const lookup={'CAST-01':{value:'![cast](https://example.org/cast.png)',type:'image',tabKey:'soul-cast'}};
  const model=sheetViewModel(parsed,parsed.rows,{coverColumn:3},lookup),card=model.cards[0];
  assert.deepEqual(model.coverColumns.map(item=>item.index),[2,3]);assert.equal(card.cover.kind,'video');
  assert.deepEqual(card.mediaChain.map(stage=>[stage.column,stage.type,!!stage.media]),[[2,'image',false],[3,'video',true]]);
  assert.deepEqual(card.assetRefs,['CAST-01','SET-02']);assert.equal(card.assets[0].tabKey,'soul-cast');assert.equal(card.assets[1].id,'SET-02');
  assert.deepEqual(assetReferences(parsed.rows[0]),['CAST-01','SET-02']);
});

test('asset lookup reads named IDs and media from a source document',()=>{
  const text=value=>({type:'text',text:value});const row=(id,values)=>({type:'tableRow',attrs:{bid:id},content:values.map(value=>({type:'tableCell',content:[{type:'paragraph',content:[text(value)]}]}))});
  const doc={type:'doc',content:[{type:'table',attrs:{bid:'cast',column_types:['text','image']},content:[row('header',['Asset','Reference']),row('cast1',['CAST-01','![cast](https://example.org/cast.png)'])]}]};
  const lookup=buildAssetLookup([{key:'soul-cast',doc}]);assert.equal(lookup['CAST-01'].value,'![cast](https://example.org/cast.png)');assert.equal(lookup['CAST-01'].rowId,'cast1');
});

test('single-cell execution uses exactly one saved node and never broadens missing or ambiguous matches',()=>{
  const input=studioRunInput(flow,scope);
  assert.deepEqual(input,{execution_mode:'single_step',node_id:'movie',input_mode:'current_sources',sample_row_id:'r1',definition_revision:7});
  for(const forbidden of ['row_ids','target_tab','start_node_id'])assert.ok(!(forbidden in input));
  assert.throws(()=>studioRunInput(flow,{...scope,col_index:1}),/No unambiguous/);
  assert.throws(()=>studioRunInput({...flow,definition:{...flow.definition,nodes:[...flow.definition.nodes,{...flow.definition.nodes[2],id:'duplicate'}]}},scope),/No unambiguous/);
  const foreign=structuredClone(flow);foreign.definition.nodes[2].row_source.tab_key='other';assert.throws(()=>studioRunInput(foreign,scope),/No unambiguous/);
  const legacy=structuredClone(flow);delete legacy.definition.nodes[2].scope;assert.throws(()=>studioRunInput(legacy,scope),/No unambiguous/);
  // Two steps write the same column: a node predicate names one (the 3D stage runs the previs motion pass this way).
  const twin={...flow,definition:{...flow.definition,nodes:[...flow.definition.nodes,{...flow.definition.nodes[2],id:'motion',title:'Previs Motion Pass'}]}};
  assert.equal(studioRunInput(twin,{...scope,match:node=>node.id==='motion'}).node_id,'motion');
  assert.equal(studioRunInput(twin,{...scope,match:node=>node.id!=='motion'}).node_id,'movie');
  // OpenJutsu: a swap step filtered on Jutsu Mode takes Object Swap rows; other rows keep the unfiltered restyle step.
  const swap={...flow,definition:{...flow.definition,nodes:[...flow.definition.nodes,{...flow.definition.nodes[2],id:'swap',row_source:{tab_key:'cinema',table_id:'shots',status_col:1,status:['Object Swap']}}]}};
  assert.equal(studioRunInput(swap,{...scope,row:['VFX-02','Object Swap']}).node_id,'swap');
  assert.equal(studioRunInput(swap,{...scope,row:['VFX-01','Motion Transfer']}).node_id,'movie');
  assert.throws(()=>studioRunInput(swap,scope),/No unambiguous/);
  const onlySwap={...swap,definition:{...swap.definition,nodes:swap.definition.nodes.filter(node=>node.id!=='movie')}};
  assert.throws(()=>studioRunInput(onlySwap,{...scope,row:['VFX-01','Motion Transfer']}),/No unambiguous/);
});

test('batch execution starts with the matching sheet rather than unrelated upstream work',()=>{
  assert.deepEqual(studioRunInput(flow,{...scope,singleStep:false,capability:undefined,col_index:undefined,rowIds:['r1','r2']}),{target_tab:'cinema',row_ids:['r1','r2'],definition_revision:7,start_node_id:'frame'});
  // The 3D stage's layout render: a named first step of a lane whose key column other steps also write; the run continues downstream.
  const lane={...flow,definition:{...flow.definition,nodes:[...flow.definition.nodes,{...flow.definition.nodes[1],id:'layoutkey',title:'Layout Key'},{...flow.definition.nodes[2],id:'layout',title:'Layout Render'}]}};
  assert.equal(studioRunInput(lane,{...scope,singleStep:false,capability:'image_gen',col_index:undefined,match:node=>node.id==='layoutkey'}).start_node_id,'layoutkey');
  assert.throws(()=>studioRunInput(lane,{...scope,singleStep:false,capability:'image_gen',col_index:undefined}),/No unambiguous/);
});

test('queue preserves reviewed revisions and never runs a failed or stale preflight',async()=>{
  const input=studioRunInput(flow,scope),calls=[];
  const api={post:async(path,body)=>{calls.push([path,body]);return path.endsWith('/preflight')?{ready:true,source_revisions:{cinema:3}}:{run:{id:'run1'}};}};
  await queueStudioRun(api,'/flow',input,{tabKey:'cinema',revision:3});assert.equal(calls.length,2);assert.deepEqual(calls[1][1],{...input,source_revisions:{cinema:3}});
  calls.length=0;await assert.rejects(queueStudioRun(api,'/flow',input,{tabKey:'cinema',revision:4}),/source changed/);assert.equal(calls.length,1);
  let ran=false;await assert.rejects(queueStudioRun({post:async path=>{if(path.endsWith('/runs'))ran=true;return {ready:false,errors:[{message:'Worker offline'}]};}},'/flow',input),/Worker offline/);assert.equal(ran,false);
});

test('preset selection preserves wire values and appends asset references only once',()=>{
  assert.equal(presetsFor('Camera Motion')[0],'Slow Dolly Push-In');assert.equal(presetsFor('Optical Rig').length,5);assert.deepEqual(presetsFor('Jutsu Mode'),['Motion Transfer','Object Swap']);
  assert.deepEqual(presetsFor('Action Prompt',['CAST-01']),['@CAST-01']);assert.equal(applyPreset('Walk @CAST-01','@CAST-01'),'Walk @CAST-01');assert.equal(applyPreset('Walk','@CAST-01'),'Walk @CAST-01');
});

test('pipeline nodes show executor and latest successful output only',()=>{
  const definition={nodes:[{id:'a',title:'Render',agent_key:'director',capability:'video_gen'},{id:'b',title:'Assemble',limb_id:'worker'}],edges:[]};
  const tasks=[{node_id:'a',status:'succeeded',updated_at:'2026-10-17',output:{asset_url:'/old'}},{node_id:'a',status:'succeeded',updated_at:'2026-10-18',output:{asset_url:'/new'}},{node_id:'a',status:'failed',updated_at:'2026-10-19',output:{asset_url:'/failed'}}];
  const canvas=flowToCanvas(definition,[],[],tasks,[{agent_key:'director',display_name:'Director'}],[{id:'worker',name:'Comfy Worker'}]);
  assert.equal(canvas.nodes[0].data.executorLabel,'Director');assert.equal(canvas.nodes[0].data.latestMediaUrl,'/new');assert.equal(canvas.nodes[1].data.executorLabel,'Comfy Worker');assert.equal(canvas.nodes[1].data.latestMediaUrl,undefined);
});

test('localized preset labels do not alter parameter values',async()=>{await setLocale('zh-TW');assert.equal(presetLabel('Slow Dolly Push-In'),'緩慢推軌靠近');assert.equal(presetsFor('Camera Motion')[0],'Slow Dolly Push-In');await setLocale('en');});

test('reference preparation selects exact-column media workers for image and motion stages',()=>{
  const prepared=structuredClone(flow);
  prepared.definition.nodes.push({id:'first',scope:'rows',capability:'media_assemble',row_source:{tab_key:'cinema',table_id:'shots'},target:{tab_key:'cinema',table_id:'shots',col_index:8}});
  prepared.definition.nodes.push({id:'motion',scope:'rows',capability:'media_assemble',row_source:{tab_key:'cinema',table_id:'shots'},target:{tab_key:'cinema',table_id:'shots',col_index:9}});
  assert.equal(studioRunInput(prepared,{...scope,capability:'image_gen',col_index:8}).node_id,'first');
  assert.equal(studioRunInput(prepared,{...scope,capability:'video_gen',col_index:9}).node_id,'motion');
  assert.throws(()=>studioRunInput(prepared,{...scope,capability:'image_gen',col_index:10}),/No unambiguous/);
  const duplicate=structuredClone(prepared);duplicate.definition.nodes.push({...duplicate.definition.nodes.at(-2),id:'other-first',capability:'image_gen'});
  assert.throws(()=>studioRunInput(duplicate,{...scope,capability:'image_gen',col_index:8}),/No unambiguous/);
});

test('appended reference stages display before outputs while preserving action columns and unknown slots',()=>{
  const expanded={headers:['Source Driving Video','Custom Image','Remastered Video','Split-Screen MP4','First Frame','Motion Structure','Anchor Keyframe','Other Image'],table:{attrs:{column_types:['video','image','video','video','image','video','image','image']}},rows:[]};
  const stages=mediaStages(expanded,{cells:expanded.headers.map(()=>({value:''}))});
  assert.deepEqual(stages.map(stage=>stage.label),['Source Driving Video','Custom Image','First Frame','Motion Structure','Anchor Keyframe','Remastered Video','Split-Screen MP4','Other Image']);
  assert.deepEqual(stages.map(stage=>stage.column),[0,1,4,5,6,2,3,7]);
  assert.equal(stages.find(stage=>stage.label==='First Frame').type,'image');
});

test('canvas bench links fan footage out to every pass and merge passes into the remaster', () => {
  const stage = label => ({ label });
  const vfx = benchLinks(['Source Driving Video', 'First Frame', 'Motion Structure', 'Anchor Keyframe', 'Remastered Video', 'Split-Screen MP4'].map(stage));
  assert.deepEqual(vfx.order, ['input', 'control', 'output']);
  assert.deepEqual(vfx.links.map(([a, b]) => a.label + '>' + b.label), ['Source Driving Video>First Frame', 'Source Driving Video>Motion Structure', 'Source Driving Video>Anchor Keyframe',
    'First Frame>Remastered Video', 'Motion Structure>Remastered Video', 'Anchor Keyframe>Remastered Video', 'Remastered Video>Split-Screen MP4']);
  assert.deepEqual(benchLinks(['Keyframe', 'Cinema Shot'].map(stage)).links.map(([a, b]) => a.label + '>' + b.label), ['Keyframe>Cinema Shot']);
});
