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
  const result=await build({stdin:{contents:"export {CompositionPanel,CompositionReport,AssetVaultModal,AssetGenerationState,ShotProduction,StoryBatchBar,TakeGrades} from './src/StoryWorkbenchModals.jsx'; export {StudioTopBar,CommandPalette,SpaceMenu,spaceNote,spaceShortcuts,SPACES,spaceOf,tabOfSpace,FilmOverlay,episodeCounts,filmTrial} from './src/StudioShell.jsx'; export {ShotFilmView} from './src/ShotFilmPanel.jsx'; export {StoryWorld} from './src/StoryWorld.jsx'; export {BreakdownDialog} from './src/BreakdownDialog.jsx'; export {SheetCards} from './src/SheetCards.jsx'; export {setLocale} from './src/i18n/index.js';",resolveDir:root,sourcefile:'story-render.jsx',loader:'jsx'},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
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
  assert.match(html,/<button type="button" class="space-foot world-format-btn"[^>]*aria-label="Format and style: 16:9"/,'the foot of the left rail opens the same dialog');
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
