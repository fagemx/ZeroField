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
import {mergeTakes,filmNeighbors,filmSegments,filmSummary} from '../src/takeModel.js';

const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
let temporary, components;
before(async()=>{
  temporary=await mkdtemp(join(root,'tests/.story-render-'));
  const result=await build({stdin:{contents:"export {CompositionPanel,CompositionReport,AssetVaultModal,AssetGenerationState,ShotProduction,StoryBatchBar,TakeGrades} from './src/StoryWorkbenchModals.jsx'; export {StudioTopBar,CommandPalette,SpaceMenu,spaceNote,spaceShortcuts,SPACES,spaceOf,tabOfSpace,FilmOverlay,episodeCounts,filmTrial} from './src/StudioShell.jsx'; export {ShotFilmView} from './src/ShotFilmPanel.jsx'; export {StoryWorld} from './src/StoryWorld.jsx'; export {BreakdownDialog} from './src/BreakdownDialog.jsx'; export {SheetCards} from './src/SheetCards.jsx'; export {setLocale} from './src/i18n/index.js'; export {ShotComposer} from './src/composer/ShotComposer.jsx'; export {CameraWall} from './src/composer/ExampleWall.jsx'; export {shotMonitor} from './src/composer/shotMonitor.js'; export {StageViewMenu} from './src/ShotStage.jsx'; export {viewMode} from './src/sheetViews.js';",resolveDir:root,sourcefile:'story-render.jsx',loader:'jsx'},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
  const output=join(temporary,'components.mjs');await writeFile(output,result.outputFiles[0].text);components=await import(pathToFileURL(output));
});
after(async()=>{if(temporary)await rm(temporary,{recursive:true,force:true});});
const render=(name,props)=>renderToStaticMarkup(React.createElement(components[name],props));

test('the studio top bar is a breadcrumb: one space button that opens a menu, no standing tabs, the focus, Ctrl K and one film entry',()=>{
  const html=render('StudioTopBar',{project:{title:'The Last Signal'},episodes:[{episodeId:'ep_demo_01',title:'Episode 1'}],epId:'ep_demo_01',space:'stage',crumbs:{scene:'Scene 02 · Signal',shot:'S03'},counts:{shots:8,review:2,missing:1,filmed:7,adopted:6,scriptDirty:true},onEpisode(){},onSpace(){},onCommand(){},film:{open:false,onToggle(){}}});
  assert.match(html,/<button type="button" class="studio-space-btn" aria-haspopup="menu" aria-expanded="false"[^>]*>[\s\S]*?<span>Shot Stage<\/span>/);
  assert.doesNotMatch(html,/role="menu"|studio-spaces|aria-current="page"|>Story &amp; World<|>Timeline</,'the other spaces are offered only when the menu is open');
  assert.match(html,/<span class="studio-focus" title="Scene 02 · Signal">Scene 02 · Signal<\/span>/);
  assert.match(html,/<b class="studio-focus is-now" title="S03"><i class="studio-dot" aria-hidden="true"><\/i>S03<\/b>/,'the shot in focus ends the breadcrumb');
  assert.match(html,/role="group" aria-label="Panels"/);assert.doesNotMatch(html,/aria-label="Bottom panel"/,'only a space with a bottom panel offers its toggle');
  assert.match(html,/Ctrl K/);assert.match(html,/Film<span class="num">6\/8<\/span>/,'SPEC_19 R6: the film number is the adopted shots, not the shots with a take');
  assert.doesNotMatch(html,/[①②③④⑤⑥]|Start Creating|My Projects|Studio Engine/,'no numbered stations and no second set of entries');
  assert.equal((html.match(/>Film</g)||[]).length,1,'one film entry');
});

test('three spaces map to their pages, and the space menu says what each one needs',()=>{
  assert.deepEqual(components.SPACES.map(space=>[space.key,space.tab]),[['story','story-world'],['stage','cinema-studio'],['timeline','timeline']]);
  assert.equal(components.spaceOf('timeline'),'timeline');assert.equal(components.spaceOf('soul-cast'),'story');assert.equal(components.spaceOf('openjutsu-lab'),'stage');assert.equal(components.spaceOf('other'),null);
  assert.equal(components.tabOfSpace('timeline'),'timeline');assert.equal(components.tabOfSpace('nope'),'cinema-studio');
  const counts={shots:8,review:2,missing:1,filmed:7,adopted:6,scriptDirty:true};
  assert.equal(components.spaceNote('story',counts),'Script changed · 1 missing images');
  assert.equal(components.spaceNote('stage',counts),'8 shots · 2 to review');
  assert.equal(components.spaceNote('timeline',counts),'6 of 8 shots adopted');
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

test('Story & World hosts the writing workspace and keeps one primary action and the format foot; the build questions wait in a dialog',()=>{
  const page=extra=>render('StoryWorld',{slug:'demo',me:{actor_id:'actor'},epId:'ep_demo_02',writable:true,...extra});
  const html=page();
  // The workspace mounts once the host has decided what a production started from a story hands it (SPEC_16A 3.5), so a first render has none.
  assert.doesNotMatch(html,/<textarea/,'no second, unpersisted copy of the script on the page');
  for(const name of ['Scenes','By scene','Cast &amp; sets','Confirm Script &amp; Build Storyboard']) assert.ok(html.includes(name),name);
  assert.match(html,/class="story-outline-slot"/,'the outline has its place in the left rail');
  assert.match(html,/class="story-panel-slot"/,'the panels have their place in the right column');
  for(const asked of ['Aspect Ratio','Style Preset','Storyboard Density','name="breakdown"','world-format"']) assert.ok(!html.includes(asked),asked+' is asked in the dialog, it no longer stands on the page');
  assert.equal((html.match(/class="primary/g)||[]).length,1,'one primary action');
  assert.doesNotMatch(html,/role="dialog"/,'the dialog is closed until the action is pressed');
  assert.match(html,/<button type="button" class="space-foot world-format-btn"[^>]*aria-expanded="false" aria-label="Episode look: 16:9"/,'SPEC_19 R12: the foot of the left rail opens the Episode look page');
  assert.match(page({shots:[{shotId:'s1',sceneId:'sc1'}]}),/Update Storyboard &amp; Open Shot Stage/);
  assert.doesNotMatch(page({writable:false}),/world-format-btn/,'a reader sees the format, not a way to change it');
});

const dialogProps=(extra={})=>({value:{breakdownMode:'auto',ratio:'16:9',style:'88123'},styles:[{stylePresetId:'88123',name:'Sci-Fi Noir',sampleImage:'/projects/assets/style-samples/sci-fi-noir.svg'},{stylePresetId:'88124',name:'Cel-Shaded'}],rebuild:true,shots:8,onConfirm(){},onCancel(){},onImport(){},...extra});
const estimateOf=(auto,scene,cinematic)=>({status:'ready',modes:Object.fromEntries(Object.entries({auto,scene,cinematic}).map(([key,[shotCount,newShots,plannedSeconds]])=>[key,{breakdownMode:key,shotCount,newShots,keptShots:shotCount-newShots,plannedSeconds}]))});

test('the build dialog asks how to split, the ratio and the style, has one primary action and a way to import a shot table',()=>{
  const html=render('BreakdownDialog',dialogProps());
  assert.match(html,/role="dialog" aria-modal="true" aria-label="Update storyboard"/);
  const radio=value=>html.match(new RegExp(`<input[^>]*value="${value}"[^>]*>`))?.[0]||'';
  for(const mode of ['auto','scene','cinematic']) assert.match(radio(mode),/type="radio"[^>]*name="breakdown"|name="breakdown"[^>]*type="radio"/,mode);
  assert.match(radio('auto'),/checked=""/);assert.doesNotMatch(radio('scene'),/checked=""/);
  for(const text of ['Storyboard Density','The script&#x27;s beats decide how many shots','The leanest cut, fewest shots','Aspect Ratio','Style Preset','Sci-Fi Noir','Cel-Shaded','Have your own shot table?','Import shot table','The 8 shots you have are kept']) assert.ok(html.includes(text),text);
  assert.equal((html.match(/class="primary/g)||[]).length,1,'one primary action in the dialog');
  assert.match(html,/<button type="submit" class="primary">Update Storyboard &amp; Open Shot Stage<\/button>/);
  assert.match(html,/<img src="\/projects\/assets\/style-samples\/sci-fi-noir\.svg" alt="" loading="lazy"\/>/,'a style with a sample shows it');
  assert.match(html,/<input[^>]*value="88124"[^>]*\/><span class="breakdown-nosample"/,'a style without a sample falls back to its name card');
  assert.doesNotMatch(html,/Target length|planned|new<\/small>/,'no estimate until the server has answered');
  assert.doesNotMatch(render('BreakdownDialog',dialogProps({onImport:undefined})),/Import shot table/);
  const build=render('BreakdownDialog',dialogProps({rebuild:false,shots:0}));
  assert.match(build,/aria-label="Build storyboard"/);assert.match(build,/>Confirm Script &amp; Build Storyboard<\/button>/);assert.doesNotMatch(build,/shots you have are kept/);
  assert.match(render('BreakdownDialog',dialogProps({confirmDisabled:true})),/<button type="submit" class="primary" disabled="">/);
});

test('the dialog shows what each way of splitting would give, marks the one nearest the target, and fails soft',()=>{
  const estimate=estimateOf([11,3,47],[8,0,35],[15,7,63]);
  const html=render('BreakdownDialog',dialogProps({estimate,target:45,onTarget(){}}));
  for(const text of ['11 shots · 47 s planned','8 shots · 35 s planned','15 shots · 63 s planned','3 new','0 new','7 new','Target length for this episode','Not set','45 s','90 s','Custom','Only marks the nearest way to split']) assert.ok(html.includes(text),text);
  assert.equal((html.match(/Nearest to 45 s/g)||[]).length,1,'one way is marked');
  assert.match(html,/Auto — follow story beats<em class="breakdown-nearest">Nearest to 45 s<\/em>/,'the mark sits on the way that lands nearest 45 s: 47 against 35 and 63');
  assert.match(html,/aria-pressed="true">45 s<\/button>/,'the chosen target is pressed');
  assert.match(html,/Planned seconds are the default plan for new shots plus the shots you have/);
  const none=render('BreakdownDialog',dialogProps({estimate,onTarget(){}}));
  assert.doesNotMatch(none,/Nearest to/,'no target, nothing marked');assert.match(none,/aria-pressed="true">Not set<\/button>/);
  assert.match(render('BreakdownDialog',dialogProps({estimate:{status:'error'}})),/Couldn&#x27;t estimate\. You can still build\./);
  assert.match(render('BreakdownDialog',dialogProps({estimate:{status:'error'}})),/<button type="submit" class="primary">/,'a failed estimate never blocks the build');
  assert.match(render('BreakdownDialog',dialogProps({estimate:{status:'loading'}})),/Counting shots…/);
});

test('the space menu lists what each space needs as items of their own, never a button inside a button',()=>{
  const counts={shots:8,review:2,missing:2,missingShots:1,filmed:7,adopted:6,scriptDirty:true};
  const html=render('SpaceMenu',{space:'stage',counts,defaultOpen:true,onSpace(){}});
  assert.match(html,/role="menu" aria-label="Creative spaces"/);
  assert.deepEqual([...html.matchAll(/<button type="button" role="(menuitemradio|menuitem)"/g)].map(match=>match[1]),
    ['menuitemradio','menuitem','menuitem','menuitemradio','menuitem','menuitem','menuitemradio','menuitem'],'each shortcut follows its space, as its own item');
  for(const text of ['Script changed','2 missing images','2 to review','1 shots missing references','6 of 8 shots adopted']) assert.ok(html.includes(text),text);
  assert.doesNotMatch(html,/<button[^>]*>(?:(?!<\/button>)[\s\S])*<button/,'no button inside another button');
  assert.doesNotMatch(html,/<small>/,'the notes are items now, not small print');
  const calm=render('SpaceMenu',{space:'story',counts:{shots:8,filmed:8,adopted:8},defaultOpen:true,onSpace(){}});
  assert.deepEqual([...calm.matchAll(/role="(menuitemradio|menuitem)"/g)].map(match=>match[1]),['menuitemradio','menuitemradio','menuitemradio','menuitem'],'nothing to fix: no shortcut, only the film so far');
  assert.doesNotMatch(render('SpaceMenu',{space:'stage',counts}),/role="menuitem"/,'closed: nothing');
  assert.deepEqual(components.spaceShortcuts('story',counts).map(item=>[item.id,item.target]),[['script',{view:'script'}],['missing',{view:'world',facet:'missing'}]]);
  assert.deepEqual(components.spaceShortcuts('stage',counts).map(item=>[item.id,item.target]),[['review',{filter:'review'}],['missing',{filter:'missing'}]]);
  assert.deepEqual(components.spaceShortcuts('stage',{shots:8}),[]);
  assert.equal(components.spaceShortcuts('timeline',counts)[0].target,null,'the film is a status, there is nowhere to filter to');
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
  assert.doesNotMatch(render('StoryWorld',{slug:'demo',me:{actor_id:'actor'},epId:'ep_demo_02',writable:true}),/Medium Lens/,'Screenplay mode shows no composition controls');
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

// SPEC_19 package A: the shot in the cut. S02 is adopted (Take 2, trimmed), two takes arrived since (a candidate and a pipeline take).
const filmAt=minute=>new Date(Date.UTC(2026,9,27,10,minute)).toISOString();
const filmShot=(n,extra={})=>({shotId:'sh_demo_b'+n,rowId:'b'+n,shotIndex:'S0'+n,tabKey:'cinema-studio',reviewStatus:'Queued',selectedVideoUrl:null,selectedImageUrl:null,previsVideoUrl:null,trim:{in:0,out:null},adoption:null,...extra});
function filmFixture({proposalSize=1,trial=null,writable=true}={}){
  const s1=filmShot(1,{reviewStatus:'Approved',selectedVideoUrl:'/t/1a.mp4',selectedImageUrl:'/s/1.png',adoption:{adopted:true,url:'/t/1a.mp4',at:filmAt(1),by:'u1'},takeSummary:{total:1,newSinceAdoption:0}});
  const s2=filmShot(2,{reviewStatus:'Approved',selectedVideoUrl:'/t/2b.mp4',selectedImageUrl:'/s/2.png',adoption:{adopted:true,url:'/t/2b.mp4',at:filmAt(5),by:'u1'},trim:{in:0.4,out:3.8}});
  const s3=filmShot(3,{previsVideoUrl:'/p/3.mp4',takeSummary:{total:0,newSinceAdoption:0}});
  const candidates=[{videoId:'vd_a',url:'/t/2a.mp4',createdAt:filmAt(2),selected:false},{videoId:'vd_b',url:'/t/2b.mp4',createdAt:filmAt(4),selected:true},{videoId:'vd_c',url:'/t/2c.mp4',createdAt:filmAt(8),selected:false}];
  const entry={proposal:{id:41,created_at:filmAt(9)},group:{index:0,row_id:'b2',changes:[{column:'Cinema Shot',before:'',after:'[Video](/t/2d.mp4)'}]},size:proposalSize,partial:false};
  const takes=mergeTakes(candidates,[entry],{status:'Approved',adoption:s2.adoption});
  const film=[s1,{...s2,takes},s3];
  return {label:'S02',sceneTitle:'Observatory',state:'new_take',newCount:2,writable,disabled:false,canStatus:true,
    menuItems:[{id:'block',label:'Mark as blocked',run(){}},{id:'table',label:'Open in table',run(){}}],
    neighbours:filmNeighbors(film,'sh_demo_b2'),segments:filmSegments(film),summary:filmSummary(film),currentId:'sh_demo_b2',trial,takes,hasFrame:true,
    trim:{url:'/t/2b.mp4',trim:{in:0.4,out:3.8},source:4},onTimeline(){},notes:{messages:[{id:1,name:'Maya',body:'Hold on the dial.'}],node:null},cast:{count:2,node:null}};
}

test('the shot in the cut: neighbours, progress, takes newest first with a ✓ each, and no approve button',()=>{
  const html=render('ShotFilmView',filmFixture());
  assert.match(html,/<aside class="shot-detail shot-film" aria-label="This shot in the cut">/);
  assert.doesNotMatch(html,/class="primary|Approve/,'R3: no approve button and no primary button in the column');
  assert.match(html,/<span class="shot-state is-new_take"><i class="shot-dot state-new_take" aria-hidden="true"><\/i>New take<span class="num">2<\/span><\/span>/);
  for(const text of ['In the cut','Shot 2 of 3','Play around','Adopted 2 of 3 · ','Cut uses 0.4–3.8 s · 3.4 of 4.0 s','Timeline','Retake (R)','Hold on the dial.','Notes · 1','On set · 2']) assert.ok(html.includes(text),text);
  assert.equal((html.match(/class="film-seg /g)||[]).length,3,'one progress segment per shot');
  assert.match(html,/class="film-seg state-adopted"[^>]*aria-label="S01 · Adopted/);assert.match(html,/class="film-seg state-new_take is-current" aria-current="true"/);assert.match(html,/class="film-seg state-empty"/);
  assert.deepEqual([...html.matchAll(/aria-label="Adopt Take (\d)"/g)].map(match=>match[1]),['4','3','1'],'newest first; the adopted take has no ✓ to press');
  assert.match(html,/Take 2<\/b><em class="take-badge is-adopted">In the cut<\/em>/);assert.match(html,/class="take-check is-on" role="img" aria-label="Adopted"/);
  assert.match(html,/Take 4<\/b><em class="take-badge is-new">New<\/em>[\s\S]*?From the pipeline/);
  assert.match(html,/aria-label="Reject Take 4"/,'a pipeline take can still be rejected');
  assert.match(html,/<details class="shot-menu"><summary aria-label="More shot actions"/,'the menu is folded');
  assert.match(html,/<details class="shot-cast-fold"><summary>On set · 2<\/summary>/,'the cast is folded at the bottom');
  assert.equal((html.match(/<video/g)||[]).length,4,'paused first frames of the four takes; nothing plays until asked');
  assert.match(html,/<video src="\/t\/2d\.mp4#t=0\.1" preload="metadata" muted=""/);
});

test('a reader sees the cut and can try a take, but has no ✓ and no ↻ (A15)',()=>{
  const html=render('ShotFilmView',filmFixture({writable:false}));
  assert.doesNotMatch(html,/Adopt Take|Retake \(R\)|take-check|Reject Take/);
  assert.match(html,/aria-label="Try Take 3 in the cut"/);
  assert.match(html,/In the cut<\/em>/,'the take in the cut is still marked');
});

test('a pipeline take shared with other rows is applied as a crew proposal, not adopted from the list',()=>{
  const html=render('ShotFilmView',filmFixture({proposalSize:2}));
  assert.doesNotMatch(html,/aria-label="Adopt Take 4"/);assert.doesNotMatch(html,/Reject Take 4/);
  assert.match(html,/class="take-check is-off" title="Part of a crew proposal across 2 rows/);
});

test('a take tried in the cut is marked on its row, on the progress bar and on the shot thumbnail',()=>{
  const html=render('ShotFilmView',filmFixture({trial:{shotId:'sh_demo_b2',url:'/t/2c.mp4',number:3}}));
  assert.match(html,/<li class="take-row is-trial">[\s\S]*?Take 3<\/b><em class="take-badge is-new">New<\/em><em class="take-badge is-trial">Trial<\/em>/);
  assert.match(html,/aria-pressed="true" aria-label="Trying Take 3 in the cut/);
  assert.match(html,/class="film-seg state-new_take is-current is-trial"[^>]*aria-label="S02 · New take · [\d.]+ s · Trial"[^>]*><em>Trial<\/em>/);
  assert.match(html,/<li class="is-current is-trial">[\s\S]*?<em class="film-tag is-trial">Trial<\/em>/);
  assert.doesNotMatch(render('ShotFilmView',filmFixture({trial:{shotId:'sh_other',url:'/t/9.mp4'}})),/Trial/,'a trial on another shot is not this one');
});

test('the shot column reads in Traditional Chinese, Approved shown as adopted',async()=>{
  await components.setLocale('zh-TW');
  try{
    const html=render('ShotFilmView',{...filmFixture(),state:'adopted',newCount:0});
    for(const text of ['這一鏡在成片裡','在成片裡','第 2／3 鏡','接著看','已採用','採用 Take 4','採用中','再拍 (R)','成片用 0.4–3.8 秒 · 3.4／4.0 秒','節奏台','管線產出','出場 · 2']) assert.ok(html.includes(text),text);
    assert.doesNotMatch(html,/已核准|核准/);
  }finally{await components.setLocale('en');}
});

test('the film window: adopted shots are the cut, gaps play the latest take by default and export as previs, adopted count in the top bar',()=>{
  const shots=[filmShot(1,{reviewStatus:'Approved',selectedVideoUrl:'/t/1a.mp4',selectedImageUrl:'/s/1.png'}),filmShot(2,{selectedVideoUrl:'/t/2a.mp4'}),filmShot(3,{previsVideoUrl:'/p/3.mp4'}),filmShot(4,{tabKey:'openjutsu-lab',reviewStatus:'Approved',selectedVideoUrl:'/t/lab.mp4'})];
  const html=render('FilmOverlay',{epId:'ep_demo_01',shots,writable:true,onClose(){}});
  for(const text of ['Adopted 1 of 3 shots','1 shots have a take but none adopted','Fill gaps with','Export gaps as']) assert.ok(html.includes(text),text);
  assert.match(html,/aria-pressed="true">Latest take<\/button>/,'playback fills with the newest take');
  assert.match(html,/<option value="previs" selected="">Previs<\/option>/,'the export fills with previs unless asked');
  assert.equal((html.match(/<video/g)||[]).length,1,'one player');assert.match(html,/<video src="\/t\/1a\.mp4"/);
  assert.match(html,/class="shot fill" title="Not adopted"/);assert.match(html,/class="shot fill" title="Previs"/);
  assert.match(html,/<button type="button" class="primary">Export Episode MP4<\/button>/);
  assert.deepEqual(components.episodeCounts(null,shots),{shots:3,review:1,missing:0,missingShots:0,filmed:2,adopted:1,scriptDirty:false});
});

test('a take tried in the cut stands in for its shot in the film window, marked Trial, and never reaches the export',()=>{
  const shots=[filmShot(1,{reviewStatus:'Approved',selectedVideoUrl:'/t/1a.mp4'}),filmShot(2)];
  components.filmTrial.set({shotId:'sh_demo_b1',url:'/t/1b.mp4',number:2});
  try{
    const html=render('FilmOverlay',{epId:'ep_demo_01',shots,writable:true,onClose(){}});
    assert.match(html,/<video src="\/t\/1b\.mp4"/);assert.match(html,/<span class="studio-film-tag is-trial">Trial<\/span>/);
    assert.match(html,/class="shot fill is-trial" title="Trial"/);
    assert.ok(html.includes('Adopted 1 of 2 shots'),'the trial changes no count');
  }finally{components.filmTrial.set(null);}
  assert.equal(components.filmTrial.get(),null);
});

// SPEC_19 package B: the shot composer. The catalog is the packaged one the server serves at GET /catalog/looks.
import {readFile as readCatalog} from 'node:fs/promises';
const looks=JSON.parse(await readCatalog(new URL('../../project_docs/look_catalog.json',import.meta.url),'utf8')).items;
const lookCatalog={camera:looks.filter(item=>item.kind==='camera'),moves:looks.filter(item=>item.kind==='move')};
const ltx={appCode:'ltx25-cinema',name:'LTX-2.5 Cinema',tier:'open_weights',configured:true,reason:null,outputs:['VIDEO'],estimate:{seconds:40,samples:5},quotable:false};
const barOptions={status:'ready',options:{apps:[ltx],defaultAppCode:'ltx25-cinema',style:null},catalog:[]};
function composerFixture(extra={}){
  const s1=filmShot(1,{sceneId:'sc1',reviewStatus:'Approved',selectedVideoUrl:'/t/1a.mp4',selectedImageUrl:'/s/1.png',trim:{in:0,out:3.8}});
  const s2=filmShot(2,{sceneId:'sc1',previsPlan:{seconds:4}});
  const s3=filmShot(3,{sceneId:'sc1',selectedVideoUrl:'/t/3a.mp4'});
  const lookup={'CAST-01':{id:'CAST-01',name:'Kael',media:{kind:'image',url:'/kael.png'}},'SET-01':{id:'SET-01',name:'Observatory',media:{kind:'image',url:'/obs.png'}}};
  return {slug:'demo',tabKey:'cinema-studio',rid:'b2',shot:s2,shots:[s1,s2,s3],label:'S02',scene:{index:1,title:'Observatory'},status:'Queued',
    text:'@S01.end @CAST-01 turns to @SET-01 #push-in\n@S03.start @CAST-09 #xyz',dirty:false,promptColumn:true,rig:{text:'',column:true,onWrite(){}},
    ladder:[{key:'frame',stage:{column:2},media:{kind:'image',url:'/s/2.png'}},{key:'video',stage:{column:3},media:null}],lookup,writable:true,disabled:false,
    preloaded:{catalog:lookCatalog,bar:barOptions},onDraft(){},onSave(){},onGenerate(){},...extra};
}

test('B1: a chosen shot opens on its composer, none chosen is the overview, and the views live in one View menu',()=>{
  assert.equal(components.viewMode('composer',{productionSheet:true,selected:true}),'composer');
  assert.equal(components.viewMode('composer',{productionSheet:true,selected:false}),'gallery','no shot chosen yet: the overview grid');
  assert.equal(components.viewMode('composer',{productionSheet:false,selected:true}),'grid','only a production sheet has a composer');
  assert.equal(components.viewMode('stage',{productionSheet:true,hasStage:false}),'gallery');
  assert.equal(components.viewMode('review',{productionSheet:true}),'review');
  const views=[['composer','Composer','sparkle'],['gallery','Overview','board'],['stage','3D Stage','cube'],['review','Review','play'],['compare','Compare','layers'],['grid','Table','table'],['canvas','Canvas','flow'],['kanban','Board','board']].map(([key,label,icon])=>({key,label,icon}));
  const closed=render('StageViewMenu',{views,mode:'composer',onPick(){}});
  assert.equal((closed.match(/<button/g)||[]).length,1,'one button stands in the toolbar for all eight views');
  assert.match(closed,/<button type="button" class="stage-view-btn" aria-haspopup="menu" aria-expanded="false"[^>]*><span class="stage-view-label">View<\/span>[\s\S]*<b>Composer<\/b>/);
  assert.doesNotMatch(closed,/role="menu"/);
  const open=render('StageViewMenu',{views,mode:'gallery',onPick(){},defaultOpen:true,settings:React.createElement('label',null,'Cover')});
  assert.deepEqual([...open.matchAll(/role="menuitemradio" aria-checked="(true|false)"><svg[\s\S]*?<span class="studio-menu-name">([^<]+)</g)].map(match=>match[2]+(match[1]==='true'?'*':'')),
    ['Composer','Overview*','3D Stage','Review','Compare','Table','Canvas','Board']);
  assert.match(open,/<div class="stage-view-settings" role="group" aria-label="View settings"><p class="studio-menu-foot">View settings<\/p><label>Cover<\/label><\/div>/,'cover and grouping are view settings');
});

test('the composer: the take on top, the look buttons, the prompt with its tags and one light primary button',()=>{
  const html=render('ShotComposer',composerFixture());
  assert.match(html,/<section class="shot-composer" aria-label="Shot composer">/);
  assert.match(html,/Scene 1 · 4\.0 s · Nothing adopted yet/);
  assert.match(html,/<div class="look-buttons" role="toolbar" aria-label="Look">/);
  assert.equal((html.match(/class="look-button"/g)||[]).length,5,'references, film setup, camera, palette and lighting');
  assert.match(html,/<b>References<\/b><em class="look-scope is-shot">This shot<\/em><\/span><small>3 in this shot<\/small>/,'two known codes and one the cast sheet does not know');
  assert.match(html,/data-shot-prompt="b2"/,'R puts the focus here');
  assert.match(html,/<span class="pc-tag is-asset" contenteditable="false" data-token="@CAST-01" data-kind="asset" title="@CAST-01"><img class="pc-thumb" src="\/kael\.png" alt=""><span class="pc-label">Kael<\/span><\/span>/);
  assert.match(html,/<span class="pc-tag is-move" contenteditable="false" data-token="#push-in" data-kind="move" title="The camera pushes in slowly[^"]*"><span class="pc-icon" aria-hidden="true">↗<\/span><span class="pc-label">#Push in<\/span><\/span>/);
  assert.match(html,/<span class="pc-tag is-warn" contenteditable="false" data-token="@CAST-09" data-kind="asset" title="Can't find @CAST-09">/,'an unknown code is a warning tag');
  assert.match(html,/turns to <span class="pc-tag is-asset"[^>]*data-token="@SET-01"/);
  assert.match(html,/ #xyz/,'an unknown #word stays plain text');
  assert.doesNotMatch(html,/data-token="#xyz"/);
  assert.match(html,/\n<span class="pc-tag is-take/,'a new line stays a new line');
  assert.equal((html.match(/class="primary composer-go"/g)||[]).length,1,'the one primary button');
  assert.match(html,/<button type="button" class="primary composer-go">Generate ×1 · ~40 s<\/button>/,'the time is on the button');
  assert.match(html,/<div class="studio-segmented shot-output" role="group" aria-label="Make"><button type="button" aria-pressed="false" title="First frame: this shot already has one">/,'the ladder is the output switch, ticked where made');
  assert.match(html,/<select class="gen-count" aria-label="Takes to make"[^>]*><option value="1" selected="">×1<\/option><option value="2">×2<\/option><option value="3">×3<\/option><option value="4">×4<\/option><\/select>/);
});

test('D1: a quoted take is a tag with the frame it quotes, a warning when the shot is not adopted, and its use',()=>{
  const html=render('ShotComposer',composerFixture());
  assert.match(html,/<span class="pc-tag is-take" contenteditable="false" data-token="@S01\.end" data-kind="take" data-key="S01\.end" title="Quotes S01 at 3\.8 s"><video class="pc-thumb" src="\/t\/1a\.mp4#t=3\.8" preload="metadata" muted playsinline aria-hidden="true"><\/video><span class="pc-label">S01 · out · Reference<\/span><\/span>/,
    'the adopted take at the trim out point, a paused frame');
  assert.match(html,/<span class="pc-tag is-take is-warn" contenteditable="false" data-token="@S03\.start" data-kind="take" data-key="S03\.start" title="S03 has nothing adopted yet: its latest take will be used\."><video class="pc-thumb" src="\/t\/3a\.mp4#t=0\.1"/);
  const beat=index=>({storyOrigin:{mapping:'exact',recipes:[{beatKeys:['b1'],segmentIndex:index,segmentCount:2}]}});
  const fixture=composerFixture();
  const continued=render('ShotComposer',{...fixture,shot:{...fixture.shot,...beat(1)},shots:[{...fixture.shots[0],...beat(0)},{...fixture.shot,...beat(1)},fixture.shots[2]]});
  assert.match(continued,/<span class="pc-label">S01 · out · First frame<\/span>/,'the next segment of the same beat continues from the out point');
});

test('B9: an unsaved prompt turns the primary button into Save & generate; a reader has no button',()=>{
  const html=render('ShotComposer',composerFixture({dirty:true}));
  assert.match(html,/<button type="button" class="primary composer-go">Save &amp; generate<\/button>/);
  assert.match(html,/<span class="studio-note warn" role="status">Not saved<\/span>/);
  const reader=render('ShotComposer',composerFixture({writable:false}));
  assert.doesNotMatch(reader,/composer-go|take-check|take-retake/);
  assert.match(reader,/data-shot-prompt="b2"[^>]*contentEditable="false"/i,'the prompt can be read, not changed');
});

test('one player on the stage: the composer plays what the right column queues, the column draws no player of its own',()=>{
  components.shotMonitor.play([{shotId:'sh_demo_b2',shotIndex:'S02',index:0,url:'/t/2c.mp4',in:0,out:null,source:'take',number:3}]);
  try{
    const html=render('ShotComposer',composerFixture());
    assert.equal((html.match(/autoplay=""/gi)||[]).length,1,'one video plays');
    assert.match(html,/<figure class="film-monitor"><video src="\/t\/2c\.mp4" autoplay=""/i);
    const playing={item:{shotId:'sh_demo_b2',url:'/t/2c.mp4',source:'take',number:3,shotIndex:'S02'},playing:{run:1,at:0}};
    assert.doesNotMatch(render('ShotFilmView',{...filmFixture(),...playing,monitorHosted:true}),/film-monitor|autoplay/i,'the composer hosts the player');
    assert.match(render('ShotFilmView',{...filmFixture(),...playing}),/<figure class="film-monitor">/,'without a composer the column draws it');
  }finally{components.shotMonitor.stop();}
});

test('B4: the camera wall numbers the moves in prompt order, outlines the chosen body and lens, and starts each group with Auto',()=>{
  const groups={body:lookCatalog.camera.filter(item=>item.group==='body'),lens:lookCatalog.camera.filter(item=>item.group==='lens'),aperture:lookCatalog.camera.filter(item=>item.group==='aperture')};
  const base={catalog:{status:'ready',items:lookCatalog.camera,groups},choice:{body:'film-35mm',lens:'anamorphic',aperture:'auto-aperture'},custom:false,moves:lookCatalog.moves,
    numbers:{'push-in':[1,3],pan:[2]},order:['push-in','pan','push-in'],onCategory(){},onChoose(){},onMove(){},onClose(){},onReset(){}};
  const moves=render('CameraWall',{...base,category:'moves'});
  assert.match(moves,/aria-pressed="true"[^>]*><span class="look-frame"><img src="\/projects\/assets\/look-samples\/move\/push-in\.webp"[^>]*\/><span class="look-order" aria-label="Order 1, 3">1·3<\/span><\/span><span class="look-name">Push in<\/span>/);
  assert.match(moves,/<span class="look-order" aria-label="Order 2">2<\/span><\/span><span class="look-name">Pan<\/span>/);
  assert.match(moves,/<section aria-label="This shot, in order"><h4>This shot, in order<\/h4><ol><li><span class="num">1<\/span>Push in<\/li><li><span class="num">2<\/span>Pan<\/li><li><span class="num">3<\/span>Push in<\/li><\/ol>/);
  assert.equal((moves.match(/<video/g)||[]).length,0,'no example plays until the pointer rests on it');
  assert.match(moves,/>Reset all<\/button>/);assert.match(moves,/aria-label="Close \(Esc\)"/);
  const rig=render('CameraWall',{...base,category:'rig',changed:['body','lens']});
  assert.match(rig,/<section class="look-column" aria-label="Body">/);
  assert.equal((rig.match(/class="look-tile is-selected is-small"/g)||[]).length,3,'one choice per column');
  assert.match(rig,/<span class="look-texture is-auto" aria-hidden="true"><b>Auto<\/b><\/span>/,'Auto is an abstract texture');
  assert.match(rig,/<button type="button" aria-current="true"><span>Body &amp; lens<\/span><i class="look-dot" aria-label="Changed"><\/i><\/button>/);
});

test('the composer reads in Traditional Chinese',async()=>{
  await components.setLocale('zh-TW');
  try{
    const html=render('ShotComposer',composerFixture({dirty:true}));
    for(const text of ['鏡頭生成台','第 1 場','還沒採用','參考','攝影機','本鏡','提示詞','看送出的完整提示詞','儲存並生成','未儲存','S01 · 出點 · 當參考','#慢推','S03 還沒採用，會用最新的 Take。','1 支']) assert.ok(html.includes(text),text);
  }finally{await components.setLocale('en');}
});
// ---------- SPEC_19 package D: references, upstream changed, seams, cuts only, adopting latest takes, package A follow-ups ----------
// The film/ components are bundled on their own (with their own i18n instance) the first time a test asks for them.
import {filmSeams} from '../src/takeModel.js';
import {readFile} from 'node:fs/promises';
let filmBundle=null;
const filmParts=()=>filmBundle||=build({stdin:{contents:"export {TakeRefsView,TakeRefsLine,focusShotPrompt} from './src/film/TakeRefsLine.jsx'; export {SeamDetail,SeamDot,PlayModeToggle,CheckCutsButton} from './src/film/Seams.jsx'; export {adoptLatestTakes,AdoptLatestButton,AdoptLatestReport} from './src/film/AdoptLatest.jsx'; export {setLocale} from './src/i18n/index.js';",resolveDir:root,sourcefile:'story-film.jsx',loader:'jsx'},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}})
  .then(async result=>{const output=join(temporary,'film.mjs');await writeFile(output,result.outputFiles[0].text);return import(pathToFileURL(output));});
const renderPart=(parts,name,props)=>renderToStaticMarkup(React.createElement(parts[name],props));
const quoted=(extra={})=>({shotId:'sh_demo_b1',shotIndex:'S01',edge:'end',takeUrl:'/t/1a.mp4',at:3.8,use:'first_frame',stale:false,nowTakeUrl:'/t/1a.mp4',frameUrl:'/f/1.png',adopted:true,number:2,nowNumber:2,change:null,...extra});
const seamCut=(from,to,check={},extra={})=>({index:0,fromShotId:'sh_demo_b'+from,toShotId:'sh_demo_b'+to,fromShotIndex:'S0'+from,toShotIndex:'S0'+to,checkable:true,blockedBy:[],
  check:{state:'none',checkId:null,score:null,passed:null,issues:[],feedback:null,frameSheetUrl:null,frames:null,error:null,auto:null,requestedAt:null,checkedAt:null,...check},...extra});

test('the References line names each quoted shot, its take, the second and the use, and nothing at all without references',async()=>{
  const parts=await filmParts();
  const html=renderPart(parts,'TakeRefsView',{items:[quoted(),quoted({shotId:'sh_demo_b4',shotIndex:'S04',edge:'start',at:0,use:'reference',adopted:false,number:null,frameUrl:null})],writable:true});
  assert.match(html,/<section class="take-refs" aria-label="References"><h3>References<\/h3>/);
  assert.match(html,/<img class="take-ref-frame" src="\/f\/1\.png"[^>]*><span class="take-ref-text"><span><b class="num">S01<\/b><span>Take 2<\/span><span class="num">out @3\.8 s<\/span><em class="take-ref-use">as first frame<\/em>/);
  assert.match(html,/<b class="num">S04<\/b><span class="num">in @0\.0 s<\/span><em class="take-ref-use">as reference<\/em><\/span><small>Its newest take then; nothing was adopted<\/small>/,'a quote of an unadopted take says so; an unknown take number is left out');
  assert.doesNotMatch(html,/Upstream|Re-shoot with the new one|is-stale/,'nothing changed upstream: no warning and no re-shoot');
  assert.equal(renderPart(parts,'TakeRefsView',{items:[],writable:true}),'');
  assert.equal(renderPart(parts,'TakeRefsLine',{refs:[],shots:[],writable:true}),'','no references: no line and no request');
});

test('upstream changed: the reference says what it is now, a writer gets "Re-shoot with the new one", and the progress bar marks the shot',async()=>{
  const parts=await filmParts();
  const items=[quoted({stale:true,nowTakeUrl:'/t/1c.mp4',nowNumber:3,change:{kind:'take',url:'/t/1c.mp4'}}),quoted({shotId:'sh_demo_b4',shotIndex:'S04',edge:'start',at:0,stale:true,change:{kind:'edge',seconds:0.4}}),
    quoted({shotId:'sh_demo_b5',shotIndex:'S05',stale:true,nowTakeUrl:null,change:{kind:'gone'}}),quoted({shotId:'sh_demo_b6',shotIndex:'S06',stale:true,nowNumber:null,nowTakeUrl:'/t/6x.mp4',change:{kind:'take',url:'/t/6x.mp4'}})];
  const html=renderPart(parts,'TakeRefsView',{items,writable:true});
  assert.match(html,/<section class="take-refs is-stale"/);
  for(const text of ['Upstream now uses Take 3','Upstream in point is now 0.4 s','S05 has no take now','Upstream changed its take']) assert.ok(html.includes(text),text);
  assert.equal((html.match(/<button/g)||[]).length,1,'one re-shoot for the line');
  assert.match(html,/<button type="button" class="take-refs-reshoot" title="Puts the cursor in this shot&#x27;s prompt\. Nothing is sent[^"]*">[\s\S]*?Re-shoot with the new one<\/button>/);
  assert.doesNotMatch(renderPart(parts,'TakeRefsView',{items,writable:false}),/<button/,'a reader sees the warning but cannot re-shoot');
  // The film panel: the shot whose take quotes a changed upstream carries a yellow corner on its segment.
  const view=render('ShotFilmView',{...filmFixture(),staleShots:new Set(['sh_demo_b3'])});
  assert.match(view,/class="film-seg state-empty"[^>]*aria-label="S03 · Not shot · [\d.]+ s · Upstream changed"[^>]*><\/button><i class="film-seg-stale" title="Upstream changed" aria-hidden="true"><\/i>/);
  assert.equal((view.match(/film-seg-stale/g)||[]).length,1,'only that shot');
  await parts.setLocale('zh-TW');
  try{
    const zh=renderPart(parts,'TakeRefsView',{items,writable:true});
    for(const text of ['引用','上游已換成 Take 3','上游入點已改為 0.4 秒','用新的重拍','當首幀','出點 @3.8 秒']) assert.ok(zh.includes(text),text);
  }finally{await parts.setLocale('en');}
});

test('"Re-shoot with the new one" only puts the cursor in this shot\'s prompt and sends nothing',async()=>{
  const parts=await filmParts();
  const seen=[],requests=[],saved={document:globalThis.document,fetch:globalThis.fetch};
  globalThis.fetch=(...args)=>{requests.push(args);return Promise.reject(new Error('no request expected'));};
  globalThis.document={querySelector:selector=>{seen.push(selector);return selector==='[data-shot-prompt="b3"]'?{focus(){seen.push('focus');},scrollIntoView(){seen.push('scroll');}}:null;}};
  try{
    assert.equal(parts.focusShotPrompt('b3'),true);
    assert.deepEqual(seen,['[data-shot-prompt="b3"]','scroll','focus']);
    assert.equal(parts.focusShotPrompt('b9'),false,'no composer prompt on the page: nothing happens');
    assert.deepEqual(requests,[],'no request of any kind');
  }finally{globalThis.document=saved.document;globalThis.fetch=saved.fetch;}
});

test('seam dots sit between the progress segments: green holds, yellow has problems, grey unchecked, queued and failed marked apart',()=>{
  const six=[1,2,3,4,5,6].map(n=>filmShot(n,{reviewStatus:'Approved',selectedVideoUrl:`/t/${n}.mp4`,adoption:{adopted:true,url:`/t/${n}.mp4`,at:filmAt(n),by:'u1'}}));
  const cuts=[seamCut(1,2,{state:'done',score:88,passed:true}),seamCut(2,3,{state:'done',score:41,passed:false,issues:['S02 ends with the reel in his left hand, S03 opens with it in his right'],feedback:'Prop hand flips.',frameSheetUrl:'/sheet/23.png'}),
    seamCut(3,4,{state:'queued'}),seamCut(4,5,{state:'failed',error:'The vision model timed out'}),seamCut(5,6,{},{checkable:false,blockedBy:[{shotId:'sh_demo_b6',reason:'not_adopted'}]})];
  const seams=filmSeams(six,cuts);
  const html=render('ShotFilmView',{...filmFixture(),segments:filmSegments(six),seams,seam:seams[1],onSeam(){},onCheckSeam(){}});
  assert.deepEqual([...html.matchAll(/class="seam-dot is-(\w+)[^"]*" aria-pressed="(\w+)" aria-label="([^"]+)"/g)].map(match=>[match[1],match[2],match[3]]),[
    ['pass','false','Cut S01 → S02 · Holds'],['issue','true','Cut S02 → S03 · Has problems'],['queued','false','Cut S03 → S04 · Checking…'],['failed','false','Cut S04 → S05 · Check failed'],['none','false','Cut S05 → S06 · Can&#x27;t check yet']],
    'one dot per gap, none after the last shot; the pressed one is the seam shown');
  assert.match(html,/<li style="flex-grow:[\d.]+"><button type="button" class="film-seg state-adopted"[^>]*><\/button><button type="button" class="seam-dot is-pass"/,'the dot sits in its segment\'s gap');
  // The seam shown: its score, its problems, the two frames, and (for a writer) checking it again.
  assert.match(html,/<section class="seam-detail is-issue" aria-label="Cut S02 → S03"><header><i class="seam-mark is-issue" aria-hidden="true"><\/i><b>Cut S02 → S03<\/b><span class="seam-state">Has problems<\/span><span class="num seam-score">Score 41<\/span>/);
  for(const text of ['S02 ends with the reel in his left hand, S03 opens with it in his right','Prop hand flips.','Check again']) assert.ok(html.includes(text),text);
  assert.match(html,/<img class="seam-frames" src="\/sheet\/23\.png" alt="The out frame of S02 beside the in frame of S03"/);
  assert.doesNotMatch(render('ShotFilmView',{...filmFixture(),writable:false,segments:filmSegments(six),seams,seam:seams[0]}),/Check this cut|Check again/,'a reader cannot queue a check');
  assert.match(render('ShotFilmView',{...filmFixture(),segments:filmSegments(six),seams,seam:seams[4],onCheckSeam(){}}),/S06 has no adopted take yet\./);
  assert.doesNotMatch(render('ShotFilmView',{...filmFixture(),segments:filmSegments(six),seams,seam:seams[4],onCheckSeam(){}}),/Check this cut/,'a seam that cannot be checked offers no check');
  const failed=render('ShotFilmView',{...filmFixture(),segments:filmSegments(six),seams,seam:seams[3],onCheckSeam(){}});
  assert.match(failed,/<p class="seam-note">The check could not run: The vision model timed out<\/p>/);assert.match(failed,/>Check again<\/button>/,'a failed check can be queued again');
  const queued=render('ShotFilmView',{...filmFixture(),segments:filmSegments(six),seams,seam:seams[2],onCheckSeam(){}});
  assert.match(queued,/Waiting for the Continuity Supervisor/);assert.doesNotMatch(queued,/Check again|Check this cut/,'a queued check is not queued twice');
  assert.doesNotMatch(render('ShotFilmView',filmFixture()),/seam-dot|seam-detail/,'without seams the bar is as before');
});

test('cuts only: "Play around" gets a Whole / Cuts only switch, and the film window has it too',async()=>{
  let html=render('ShotFilmView',{...filmFixture(),canAround:true,aroundMode:'whole',onAroundMode(){}});
  assert.match(html,/<div class="studio-segmented small film-mode" role="group" aria-label="What to play"><button type="button" aria-pressed="true">Whole<\/button><button type="button" aria-pressed="false">Cuts only<\/button><\/div><button type="button" class="film-around"[^>]*>[\s\S]*?Play around<\/button>/);
  html=render('ShotFilmView',{...filmFixture(),canAround:true,aroundMode:'seams',onAroundMode(){}});
  assert.match(html,/aria-pressed="true">Cuts only<\/button>[\s\S]*?Play the cuts<\/button>/);
  const shots=[filmShot(1,{reviewStatus:'Approved',selectedVideoUrl:'/t/1a.mp4'}),filmShot(2,{reviewStatus:'Approved',selectedVideoUrl:'/t/2a.mp4'}),filmShot(3,{previsVideoUrl:'/p/3.mp4'})];
  const film=render('FilmOverlay',{epId:'ep_demo_01',shots,writable:true,onClose(){}});
  assert.match(film,/<div class="studio-film-fill" role="group" aria-label="Fill gaps with"><div class="studio-segmented small film-mode" role="group" aria-label="What to play"><button type="button" aria-pressed="true">Whole<\/button>/);
  assert.equal((film.match(/<video/g)||[]).length,1,'one player whichever way it plays');
  assert.deepEqual([...film.matchAll(/class="seam-dot is-(\w+)[^"]*"[^>]*aria-label="([^"]+)"/g)].map(match=>match[2]),['Cut S01 → S02 · Not checked','Cut S02 → S03 · Not checked'],'the strip has a dot in each gap');
  await components.setLocale('zh-TW');
  try{
    const zh=render('ShotFilmView',{...filmFixture(),canAround:true,aroundMode:'seams',onAroundMode(){}});
    for(const text of ['整段','只看接點','巡接點']) assert.ok(zh.includes(text),text);
  }finally{await components.setLocale('en');}
});

test('the film window offers "Check cuts" as an outlined button to writers only, beside the export',()=>{
  const shots=[filmShot(1,{reviewStatus:'Approved',selectedVideoUrl:'/t/1a.mp4'}),filmShot(2,{reviewStatus:'Approved',selectedVideoUrl:'/t/2a.mp4'})];
  const html=render('FilmOverlay',{epId:'ep_demo_01',shots,writable:true,onClose(){}});
  assert.match(html,/<button type="button" class="seam-check">Check cuts<\/button><span class="studio-note" role="status">0 of 1 cuts checked · 0 with problems<\/span>/);
  assert.equal((html.match(/class="primary"/g)||[]).length,1,'export stays the one primary button');
  const reader=render('FilmOverlay',{epId:'ep_demo_01',shots,writable:false,onClose(){}});
  assert.doesNotMatch(reader,/Check cuts|seam-check/,'a reader does not see "Check cuts"');
  assert.match(reader,/class="seam-dot is-none"/,'but still sees the seams');
});

test('"Adopt latest takes" adopts each picked shot\'s newest take as its ✓ would, one at a time, and says what it skipped and why',async()=>{
  const parts=await filmParts();
  const videos={
    sh_demo_b1:[{videoId:'vd_1a',url:'/t/1a.mp4',createdAt:filmAt(1)},{videoId:'vd_1b',url:'/t/1b.mp4',createdAt:filmAt(3)}],
    sh_demo_b2:[{videoId:'vd_2a',url:'/t/2a.mp4',createdAt:filmAt(1)}],
    sh_demo_b3:[{videoId:'vd_3a',url:'/t/3a.mp4',createdAt:filmAt(2),selected:true}],
    sh_demo_b4:[],
    sh_demo_b5:[{videoId:'vd_5a',url:'/t/5a.mp4',createdAt:filmAt(2)}],
  };
  const proposal={id:77,action:'table_edit',status:'pending',created_at:filmAt(9),target:{tab_key:'cinema-studio'},review:{groups:[{index:0,row_id:'b2',row_number:2,label:'Row 2',changes:[{column:'Cinema Shot',before:'',after:'[Video](/t/2b.mp4)'}]}],partial_allowed:true,version:'v77'}};
  const shotInfo={b1:filmShot(1),b2:filmShot(2),b3:filmShot(3,{reviewStatus:'Approved',selectedVideoUrl:'/t/3a.mp4',adoption:{adopted:true,url:'/t/3a.mp4',at:filmAt(5),by:'u1'}}),b4:filmShot(4),b5:filmShot(5)};
  const sent=[];
  const results=await parts.adoptLatestTakes({slug:'demo',tabKey:'cinema-studio',rowIds:['b1','b2','b3','b4','b5'],shotInfo,proposals:[proposal],
    list:async path=>videos[path.split('/')[2]],request:async(path,method,body)=>{sent.push([path,method,body]);if(path.includes('b5'))throw new Error('Read-only crew members cannot modify a production.');return {};}});
  assert.deepEqual(sent,[['/shots/sh_demo_b1/adoptions','POST',{videoId:'vd_1b'}],['/shots/sh_demo_b2/adoptions','POST',{proposalId:77}],['/shots/sh_demo_b5/adoptions','POST',{videoId:'vd_5a'}]],
    'the newest candidate, the pending pipeline take through its proposal; in shot order');
  assert.deepEqual(results.map(result=>[result.shot,result.adopted?'adopted':result.skip]),[['S01','adopted'],['S02','adopted'],['S03','adopted'],['S04','none'],['S05','failed']]);
  const report=renderPart(parts,'AdoptLatestReport',{results});
  for(const text of ['Adopted 2 shots · skipped 3','S03: its newest take is already in the cut','S04: no take yet','S05: Read-only crew members cannot modify a production.']) assert.ok(report.includes(text),text);
  assert.equal(renderPart(parts,'AdoptLatestButton',{rowIds:['b1'],writable:false}),'','a reader gets no button');
  const button=renderPart(parts,'AdoptLatestButton',{rowIds:['b1','b2'],writable:true,onWrite(){}});
  assert.match(button,/<button type="button" class="adopt-latest-btn" title="Adopt the newest take of each picked shot, as its ✓ would">Adopt latest takes<\/button>/);
  assert.doesNotMatch(button,/primary/,'outlined, not a primary button');
  await parts.setLocale('zh-TW');
  try{
    assert.ok(renderPart(parts,'AdoptLatestButton',{rowIds:['b1'],writable:true}).includes('全部採用最新 Take'));
    assert.ok(renderPart(parts,'AdoptLatestReport',{results}).includes('已採用 2 鏡 · 跳過 3 鏡'));
  }finally{await parts.setLocale('en');}
  const source=await readFile(join(root,'src/SheetWorkspace.jsx'),'utf8');
  assert.match(source,/\{productionSheet&&mode==='gallery'&&<AdoptLatestButton /,'only on the overview, inside the bar that appears once shots are picked');
});

test('package A follow-ups: the overview cards read Adopted on the Shot Stage, Approved elsewhere; Review adopts through /adoptions',async()=>{
  const row={rid:'brow',cells:[{value:'SC01-S01'},{value:'Approved'}]};
  const parsed={headers:['Shot','Status'],rows:[row],table:{attrs:{column_types:[null,'status']}}};
  const card={row,index:0,title:'SC01-S01',summary:[],assets:[],mediaChain:[]};
  const props={model:{cards:[card],groupColumn:1,coverColumn:-1},mode:'gallery',selected:new Set(),parsed,writable:true};
  assert.match(render('SheetCards',{...props,compact:true}),/<option value="Approved"[^>]*>Adopted<\/option>/,'on the Shot Stage');
  assert.match(render('SheetCards',{...props,compact:false}),/<option value="Approved"[^>]*>Approved<\/option>/,'the table and other pages keep Approved');
  const source=await readFile(join(root,'src/StoryWorkbenchModals.jsx'),'utf8');
  assert.match(source,/storyRequest\(`\/shots\/\$\{id\}\/adoptions`, 'POST', kind === 'images' \? \{imageId:take\.imageId\} : \{videoId:take\.videoId\}\)/);
  assert.doesNotMatch(source,/selected-\$\{kind/,'Review no longer picks a take with selected-video');
});
