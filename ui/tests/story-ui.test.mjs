import test, {before, after} from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {build} from 'esbuild';
import {mkdtemp,writeFile,rm} from 'node:fs/promises';
import {join,dirname,resolve} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {t,setLocale} from '../src/i18n/index.js';
import {sourceDraft,editStoryScreenplay,hasSceneHeadings,needsStoryAdaptation,adaptStoryDraft,buildStoryFromDraft,storyComposition,choiceContrast,missingAssetSheets,assetGroupActive,rememberAssetGroup,restoredAssetGroup} from '../src/storyImport.js';

const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
let temporary, components;
before(async()=>{
  temporary=await mkdtemp(join(root,'tests/.story-render-'));
  const result=await build({stdin:{contents:"export {CompositionPanel,CompositionReport,AssetVaultModal,AssetGenerationState,ShotProduction,StoryBatchBar,TakeGrades} from './src/StoryWorkbenchModals.jsx'; export {StudioTopBar,CommandPalette} from './src/StudioShell.jsx'; export {StoryWorld} from './src/StoryWorld.jsx'; export {SheetCards} from './src/SheetCards.jsx'; export {setLocale} from './src/i18n/index.js';",resolveDir:root,sourcefile:'story-render.jsx',loader:'jsx'},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
  const output=join(temporary,'components.mjs');await writeFile(output,result.outputFiles[0].text);components=await import(pathToFileURL(output));
});
after(async()=>{if(temporary)await rm(temporary,{recursive:true,force:true});});
const render=(name,props)=>renderToStaticMarkup(React.createElement(components[name],props));

test('the studio top bar holds two unnumbered spaces with their status, Ctrl K and one film entry',()=>{
  const html=render('StudioTopBar',{project:{title:'The Last Signal'},episodes:[{episodeId:'ep_demo_01',title:'Episode 1'}],epId:'ep_demo_01',space:'stage',counts:{shots:8,review:2,missing:1,filmed:6,scriptDirty:true},onEpisode(){},onSpace(){},onCommand(){},film:{open:false,onToggle(){}}});
  assert.match(html,/<button type="button">Story &amp; World<span class="studio-note warn">Script changed · 1 missing images<\/span><\/button>/);
  assert.match(html,/<button type="button" aria-current="page">Shot Stage<span class="studio-note">8 shots · 2 to review<\/span><\/button>/);
  assert.match(html,/Ctrl K/);assert.match(html,/Film<span class="num">6\/8<\/span>/);
  assert.doesNotMatch(html,/[①②③④⑤⑥]|Start Creating|My Projects|Studio Engine/,'no numbered stations and no second set of entries');
  assert.equal((html.match(/>Film</g)||[]).length,1,'one film entry');
});

test('Toolbox, Open API and Agent Console are commands in the Ctrl K palette',()=>{
  const html=render('CommandPalette',{commands:[['Story & World','Space'],['Soul Cast','Page'],['Toolbox','Tool'],['Open API','Tool'],['Agent Console','Tool']].map(([label,group],i)=>({id:'c'+i,label,group,run(){}})),onClose(){}});
  assert.match(html,/role="dialog"/);assert.match(html,/role="combobox"/);
  assert.match(html,/Toolbox[\s\S]*?Open API[\s\S]*?Agent Console/);
  assert.match(html,/<li id="cmd-c0" role="option" aria-selected="true">/,'the first command is ready for Enter');
});

test('Micro has real candidate, split, restoration and node-input surfaces',()=>{
  const html=render('ShotProduction',{slug:'demo',rid:'brow',writable:true});
  for(const text of ['Candidate Takes','Split Shot','2nd-Pass 4K Restore','nodeInfoList','Re-shoot with These Inputs']) assert.ok(html.includes(text));
  assert.match(html,/<details>/);
  for(const text of ['Continuity grades','Auto-grade new takes','No grades yet']) assert.ok(html.includes(text));
});

test('continuity grades show score, notes, the GPU hand-off and a one-click retake in both languages',async()=>{
  const grades=[{gradeId:'g1',assetId:'pa_1',assetUrl:'/projects/api/demo/assets/pa_1',status:'graded',score:58,passed:false,
    feedback:'Hand leaves the dial late.',issues:['Second figure at 2.5s'],retakePrompt:'Kael keeps his hand on the dial.',sheetUrl:'/projects/api/demo/assets/pa_2',model:'qwen3.8',seconds:31.2,gpu:{comfyFreed:true}},
    {gradeId:'g2',assetId:'pa_3',assetUrl:'/projects/api/demo/assets/pa_3',status:'waiting_gpu',auto:true}];
  const grading={grades,auto:true,busy:false,error:''};
  let html=render('TakeGrades',{grading,writable:true});
  for(const text of ['58/100','Retake','Hand leaves the dial late.','Second figure at 2.5s','Retake with this prompt','Kael keeps his hand on the dial.','8-frame contact sheet','GPU handed off from ComfyUI','Waiting for the GPU','Auto']) assert.ok(html.includes(text),text);
  assert.match(html,/checked=""/);
  await components.setLocale('zh-TW');  // the bundle carries its own i18n instance
  html=render('TakeGrades',{grading,writable:false});
  for(const text of ['連戲評分','重拍','用這個提示詞重拍','等待 GPU','8 格聯絡表']) assert.ok(html.includes(text),text);
  assert.match(html,/disabled=""/);
  await components.setLocale('en');
});

test('scene headers are collapsible, counted and retain the rebuild action',()=>{
  const row={rid:'brow',cells:[{value:'SC01-S01'}]};
  const card={row,index:0,title:'SC01-S01',summary:[],assets:[],mediaChain:[]};
  const html=render('SheetCards',{model:{sceneGroups:[{key:'SC01',cards:[card]}],groupColumn:-1,coverColumn:-1},mode:'gallery',selected:new Set(),parsed:{headers:['Shot'],rows:[row],table:{attrs:{}}},writable:true,scenes:[{sceneIndex:1,sceneId:'sc_demo_01_S01',title:'Observatory Arrival'}]});
  assert.match(html,/<details open=""/);assert.match(html,/Observatory Arrival/);assert.match(html,/1 Shots/);assert.match(html,/Rebuild Scene Shots/);
});

test('new count and usage labels interpolate in both interface languages',async()=>{
  for(const locale of ['en','zh-TW']){
    await setLocale(locale);
    assert.ok(t('story.generateSelected',{count:3}).includes('3'));
    assert.doesNotMatch(t('story.assetUses',{shots:7,scenes:2}),/[{}]/);
  }
  await setLocale('en');
});

test('Story & World keeps every Start Creating field on the page, defaults to Screenplay and has one amber action',()=>{
  const html=render('StoryWorld',{epId:'ep_demo_02',writable:true});
  for(const name of ['Scenes','Story','Script','Aspect Ratio','Style Preset','Idea / Logline','Novel / Story Chapter','Screenplay','Storyboard Density','World','Confirm Script &amp; Build Storyboard']) assert.ok(html.includes(name),name);
  assert.match(html,/aria-pressed="true"[^>]*>Screenplay/);
  assert.match(html,/accept="\.txt,\.md,text\/plain,text\/markdown"/);
  for(const mode of ['auto','scene','cinematic']) assert.ok(html.includes(`value="${mode}"`));
  assert.equal((html.match(/class="primary/g)||[]).length,1,'one primary action');
  assert.match(render('StoryWorld',{epId:'ep_demo_02',writable:true,shots:[{shotId:'s1',sceneId:'sc1'}]}),/Update Storyboard &amp; Open Shot Stage/);
});

test('adapting preserves the original source and screenplay edits while a changed source requires a fresh adaptation',async()=>{
  const original={...sourceDraft(),sourceText:'An astronomer finds a countdown.'};
  let sent;
  const prepared=await adaptStoryDraft({epId:'ep_demo_02',sourceMode:'idea',draft:original,targetScenes:3,breakdownMode:'cinematic',request:async(...args)=>{
    sent=args;return {script:{content:'## Scene 01: Observatory\n@CAST-01 enters.'}};
  }});
  assert.deepEqual(sent,['/episodes/ep_demo_02/script-adaptations','POST',{sourceText:original.sourceText,sourceMode:'idea',targetScenes:3,breakdownMode:'cinematic'}]);
  assert.equal(original.script,'');assert.equal(original.adaptationKey,null);
  assert.equal(prepared.sourceText,original.sourceText);
  assert.equal(needsStoryAdaptation('idea',prepared,3),false);
  const edited={...prepared,script:prepared.script+'\n\nShe reaches for the dial.'};
  assert.equal(needsStoryAdaptation('idea',edited,3),false);
  assert.equal(needsStoryAdaptation('idea',{...edited,sourceText:'A new story.'},3),true);
  assert.equal(needsStoryAdaptation('idea',edited,4),true);
  const handwritten=editStoryScreenplay('idea',original,'## Scene 01: My handwritten scene\nThe beacon flashes.');
  assert.equal(needsStoryAdaptation('idea',handwritten,3),false);
  assert.equal(handwritten.sourceText,original.sourceText);
  const chineseEdit=editStoryScreenplay('novel',original,'## 場景一：觀測站\n小明走進房間。');
  assert.equal(needsStoryAdaptation('novel',chineseEdit,3),false);
  const requests=[];
  await buildStoryFromDraft({epId:'ep_demo_02',sourceMode:'novel',draft:chineseEdit,request:async(path,method,body)=>{requests.push({path,body});return {status:'SUCCEEDED'};},wait:async()=>({})});
  assert.equal(requests.some(call=>call.path.endsWith('script-adaptations')),false);
  assert.equal(requests.find(call=>call.path.endsWith('/script')).body.scriptContent,chineseEdit.script);
  assert.equal(needsStoryAdaptation('script',sourceDraft('An unstructured screenplay.'),3),false);
});

const cards=[{id:'col_1',label:'Duel × 60-second delivery',conditionA:'Kael is mid-duel',conditionB:'the phone shows 60 seconds',focus:'collision'},
  {id:'col_2',label:'Parcel signature × drawn blade',conditionA:'Kael must sign first',conditionB:'the pen will not write',focus:'restraint'}];

test('a composition carries lenses and the choice trace; no lens is the classic request',()=>{
  assert.equal(storyComposition({medium:'',genre:'comedy',collisions:{candidates:cards}}),null);
  assert.deepEqual(storyComposition({medium:'cinema',genre:'suspense',collisions:null}),{mediumLens:'cinema',genreLens:'suspense'});
  assert.deepEqual(storyComposition({medium:'manju',genre:'comedy',collisions:{candidates:cards},unchecked:[cards[1].label],focus:'reversal',extra:'  No real names.  '}),
    {mediumLens:'manju',genreLens:'comedy',choiceTrace:{focus:'reversal',keptLabels:[cards[0].label],uncheckedLabels:[cards[1].label],extraCondition:'No real names.'}});
});

test('a composed adaptation sends lenses and the trace, returns the no-label report, and a changed choice needs a fresh adaptation',async()=>{
  const draft={...sourceDraft(),sourceText:'A courier is secretly an immortal.'};
  const composition=storyComposition({medium:'manju',genre:'comedy',collisions:{candidates:cards},unchecked:[cards[1].label]});
  let sent;
  const prepared=await adaptStoryDraft({epId:'ep_demo_02',sourceMode:'idea',draft,composition,request:async(...args)=>{sent=args;
    return {script:{content:'## Scene 01: Duel\n@CAST-01 draws.'},voiceAudit:{ok:true,violations:[],concreteScore:80},choiceTrace:{traceId:'ctr_1',contrastDetected:true,contrastCue:'Prior beats held to restraint; this turn switches directly to reversal action without explanation.'}};}});
  assert.deepEqual(sent[2],{sourceText:draft.sourceText,sourceMode:'idea',targetScenes:3,breakdownMode:'auto',...composition});
  assert.equal(prepared.report.voiceAudit.ok,true);assert.equal(prepared.report.choiceTrace.traceId,'ctr_1');
  assert.equal(needsStoryAdaptation('idea',prepared,3,composition),false);
  assert.equal(needsStoryAdaptation('idea',prepared,3,{...composition,genreLens:'suspense'}),true);
  assert.equal(needsStoryAdaptation('idea',prepared,3),true);
  const html=render('CompositionReport',{report:prepared.report});
  assert.match(html,/No-Label Check: Clean · concrete score 80\/100/);assert.match(html,/Behavior contrast: Prior beats held to restraint/);
  assert.equal(render('CompositionReport',{report:null}),'');
});

test('the composition panel stays folded to one lens choice until a lens is picked, then strikes unchecked cards',async()=>{
  const value={medium:'',genre:'general',collisions:null,unchecked:[],focus:'overall',extra:''};
  let html=render('CompositionPanel',{value,onChange:()=>{}});
  assert.match(html,/<button type="button" aria-pressed="true">Classic adaptation \(no lens\)<\/button>/);
  assert.doesNotMatch(html,/Collision Genre|Collide Conditions/);
  html=render('CompositionPanel',{value:{...value,medium:'manju',genre:'comedy',collisions:{candidates:cards},unchecked:[cards[1].label]},onChange:()=>{},onCollide:()=>{}});
  for(const text of ['AI Manju / Micro-Drama','Absurd Comedy','Collide Conditions (L1→L2)','Kael is mid-duel × the phone shows 60 seconds','Head-on collision','Extra Condition']) assert.ok(html.includes(text),text);
  assert.match(html,/<li><label><input type="checkbox" checked=""\/><span><strong>Duel × 60-second delivery/);
  assert.match(html,/<li class="is-struck"><label><input type="checkbox"\/><span><strong>Parcel signature × drawn blade/);
  assert.doesNotMatch(render('CompositionPanel',{value:{...value,medium:'cinema'},onChange:()=>{}}),/<button type="button">Collide/);  // no source, no collision
  await components.setLocale('zh-TW');
  html=render('CompositionPanel',{value:{...value,medium:'storybook',collisions:{candidates:cards}},onChange:()=>{}});
  for(const text of ['表現形式透鏡','繪本／視覺故事書','條件碰撞類型','補一句限制條件','正面相撞']) assert.ok(html.includes(text),text);
  await components.setLocale('en');
  assert.doesNotMatch(render('StoryWorld',{epId:'ep_demo_02',writable:true}),/Medium Lens/,'Screenplay mode shows no composition controls');
});

test('one-click novel creation adapts, saves, extracts and builds the selected episode before onDone',async()=>{
  const calls=[],waited=[],events=[];
  const source={...sourceDraft(),sourceText:'Aria crosses the station.\n\n"Who is there?"'};
  let prepared;
  const result=await buildStoryFromDraft({epId:'ep_demo_03',sourceMode:'novel',draft:source,targetScenes:2,breakdownMode:'cinematic',settings:{aspectRatio:'9:16',stylePresetId:'88123'},
    request:async(path,method,body)=>{calls.push([path,method,body]);if(path.endsWith('script-adaptations'))return {script:{content:'## Scene 01: Station\nAria enters.\n\n## Scene 02: Corridor\nAria calls out.'}};return {taskId:path.endsWith('storyboards')?'board':'assets',status:'SUCCEEDED'};},
    wait:async task=>{waited.push(task.taskId);return {built:task.taskId};},onPrepared:draft=>{prepared=draft;events.push('prepared');},onDone:()=>events.push('done')});
  assert.deepEqual(calls.map(call=>call[0].split('/').at(-1)),['settings','script-adaptations','script','asset-extractions','storyboards']);
  assert.ok(calls.every(call=>call[0].startsWith('/episodes/ep_demo_03/')));
  assert.equal(calls[0][2].breakdownMode,'cinematic');assert.deepEqual(calls.at(-1)[2],{breakdownMode:'cinematic'});
  assert.equal(calls[2][2].scriptContent,prepared.script);assert.equal(prepared.sourceText,source.sourceText);
  assert.deepEqual(waited,['assets','board']);assert.deepEqual(events,['prepared','done']);assert.deepEqual(result,{built:'board'});
});

test('retry after extraction failure keeps the prepared screenplay and never adapts the same source twice',async()=>{
  let current={...sourceDraft(),sourceText:'A beacon begins to count down.'},adaptations=0,fail=true,done=0;
  const request=async(path,method,body)=>{
    if(path.endsWith('script-adaptations')){adaptations++;return {script:{content:'## Scene 01: Beacon\nA light flashes.'}};}
    if(path.endsWith('asset-extractions')&&fail)throw new Error('Extraction unavailable');
    if(path.endsWith('/script')&&!fail)assert.ok(body.scriptContent.includes('An edited ending.'));
    return {status:'SUCCEEDED',result:{}};
  };
  const run=()=>buildStoryFromDraft({epId:'ep_demo_01',sourceMode:'idea',draft:current,request,wait:async task=>task.result,onPrepared:draft=>{current=draft;},onDone:()=>{done++;}});
  await assert.rejects(run(),/Extraction unavailable/);assert.equal(done,0);assert.equal(adaptations,1);
  current={...current,script:current.script+'\n\nAn edited ending.'};fail=false;
  await run();assert.equal(adaptations,1);assert.equal(done,1);
});

test('structured input skips adaptation and a malformed adaptation cannot trigger extraction or completion',async()=>{
  for(const content of ['Scene 01: Night\nSomeone walks.','## Scene 02: Dawn\nSomeone enters.','INT. OBSERVATORY - NIGHT\nA light flashes.','## 場景一：觀測站\n小明走進房間。','场景2：车站\n小明走进房间。']) assert.equal(hasSceneHeadings(content),true);
  const calls=[];
  await buildStoryFromDraft({epId:'ep_demo_01',sourceMode:'novel',draft:{...sourceDraft(),sourceText:'INT. OBSERVATORY - NIGHT\nA light flashes.'},request:async path=>{calls.push(path);return {status:'SUCCEEDED'};},wait:async()=>({})});
  assert.equal(calls.some(path=>path.endsWith('script-adaptations')),false);
  calls.length=0;
  await assert.rejects(buildStoryFromDraft({epId:'ep_demo_01',sourceMode:'idea',draft:{...sourceDraft(),sourceText:'A light flashes.'},request:async path=>{calls.push(path);return {};},wait:async()=>{},onDone:()=>assert.fail('must not finish')}),/no screenplay/);
  assert.deepEqual(calls.map(path=>path.split('/').at(-1)),['settings','script-adaptations']);
});

test('asset readiness uses exact episode references and group progress restores without launching another batch',()=>{
  assert.deepEqual(missingAssetSheets({missingAssetCodes:['CAST-01','CAST-01:NIGHT','@SET-02','LOC-03','PROP-03','CAST-01']}),['CAST-01','CAST-01:NIGHT','SET-02','LOC-03']);
  assert.deepEqual(missingAssetSheets(null),[]);
  const values=new Map(),storage={getItem:key=>values.get(key),setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)};
  const group={taskGroupId:'tg_abc123',taskIds:['task_1','task_2'],assetCodes:['CAST-01:NIGHT','SET-02']};
  assert.equal(assetGroupActive(group),true);
  rememberAssetGroup('ep_demo_02',group,storage);
  assert.deepEqual(restoredAssetGroup('ep_demo_02',storage),group);assert.equal(restoredAssetGroup('ep_demo_01',storage),null);
  const finished={...group,counts:{queued:'0',running:'0',succeeded:'1',failed:'1'}};
  assert.equal(assetGroupActive(finished),false);rememberAssetGroup('ep_demo_02',finished,storage);
  assert.equal(restoredAssetGroup('ep_demo_02',storage),null);
});

test('asset generation displays queued count, outcomes and actionable failures in both languages',async()=>{
  const group={taskGroupId:'tg_abc123',taskIds:['task_1','task_2'],assetCodes:['CAST-01','SET-02']};
  assert.match(render('AssetGenerationState',{group}),/2 asset tasks · 2 queued/);
  const finished={...group,counts:{total:'2',queued:'0',running:'0',succeeded:'1',failed:'1'},tasks:[{taskId:'task_1',status:'SUCCEEDED'},{taskId:'task_2',status:'FAILED',error:{message:'Worker unavailable'}}]};
  let html=render('AssetGenerationState',{group:finished,error:'Connection lost'});
  for(const text of ['1 completed','1 failed or canceled','Worker unavailable','Completed images are kept','Refresh Task Status'])assert.ok(html.includes(text),text);
  await components.setLocale('zh-TW');
  html=render('AssetGenerationState',{group:finished});assert.ok(html.includes('已完成的圖片會保留'));
  await components.setLocale('en');
  assert.match(render('AssetVaultModal',{epId:'ep_demo_01',writable:false}),/<button disabled="">Generate Missing Asset Sheets/);
});

test('the P4 contrast preview matches the server rule: two of the last five held one line and this focus opposes it',()=>{
  const traces=focus=>focus.map(f=>({focus:f}));
  assert.deepEqual(choiceContrast(traces(['restraint','restraint']),'reversal'),{contrastDetected:true,dominantFocus:'restraint'});
  assert.equal(choiceContrast(traces(['restraint']),'reversal').contrastDetected,false);
  assert.equal(choiceContrast(traces(['restraint','restraint']),'collision').contrastDetected,false);
  assert.equal(choiceContrast(traces(['collision','collision','x','x','x','x']),'negative_space').contrastDetected,false,'only the last five count');
});
