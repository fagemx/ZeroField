// SPEC_21 §4 (package D), acceptance A11: the asset-first editor. Panels per type with their prerequisites, the locks under the
// description, the stress test and its tally, the State look, the background panel runs, and the reference plan in the prompt preview.
// The server side (§2.2) is built in parallel: the components are rendered from fake answers of that contract.
import test, {before, after} from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {build} from 'esbuild';
import {mkdtemp, writeFile, rm} from 'node:fs/promises';
import {join, dirname, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {ALL, LOCKS, LOOK_KINDS, STRESS, activeTasks, batchRun, chosenPanel, createdTasks, droppedList, finishedScopes, hasPicture, listOf, lockFields, lookBody, lookReady,
  metaPatch, panelBlock, panelCandidates, panelGenerationBody, panelRunRefused, panelRunState, panelRunsStarted, panelStrip, panelsOf, referenceRows, runKey, startPanelRuns,
  startingPanel, stressBody, stressCompany, stressMarked, stressOrder, stressTally} from '../src/assetPanels.js';
import {FRAME_APP, frameOptions, frameOptionsUsable, isEditCard, settleRun, startingApp} from '../src/generation/generationModel.js';
import {rememberGenerations, rememberPanelGenerations, restoredGenerations, restoredPanelGenerations, worldItems} from '../src/worldModel.js';
import en from '../src/i18n/locales/en.json' with {type:'json'};
import zh from '../src/i18n/locales/zh-TW.json' with {type:'json'};

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
let temporary, components;
before(async () => {
  temporary = await mkdtemp(join(root, 'tests/.spec21-render-'));
  const result = await build({stdin: {contents: "export {AssetEditor, PanelBar, StressBar, StressGrid} from './src/AssetEditor.jsx'; export {ReferencePlan} from './src/composer/ReferencePlan.jsx'; export {setLocale} from './src/i18n/index.js';",
    resolveDir: root, sourcefile: 'spec21-render.jsx', loader: 'jsx'}, bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', packages: 'external', loader: {'.css': 'empty'}});
  const output = join(temporary, 'components.mjs');
  await writeFile(output, result.outputFiles[0].text);
  components = await import(pathToFileURL(output));
});
after(async () => {if (temporary) await rm(temporary, {recursive: true, force: true});});
const render = (name, props) => renderToStaticMarkup(React.createElement(components[name], props));
const zhTW = async action => {await components.setLocale('zh-TW'); try {return await action();} finally {await components.setLocale('en');}};

const pic = (panel, n) => ({url: `/assets/${panel}-${n}.png`, imageId: `im_${panel}_${n}`});
const asset = (code, type, image, extra = {}) => ({assetId:'as_' + code, assetCode:code, name:extra.name || code, prompt:'A look for ' + code, type, isDefault:true, selectedImageUrl:image,
  voice:'', status:'Queued', notes:'', ...extra});
const shots = [
  {shotId:'sh_1', rowId:'b1', shotIndex:'S01', sceneId:'sc1', assets:['CAST-01', 'CAST-02', 'SET-01', 'PROP-01'], selectedImageUrl:null},
  {shotId:'sh_2', rowId:'b2', shotIndex:'S02', sceneId:'sc1', assets:['CAST-01:WET', 'CAST-02'], selectedImageUrl:null},
];
const [noa, ines, canyon, burner] = worldItems([
  asset('CAST-01', 'CHARACTER', null, {name:'Noa'}),
  asset('CAST-02', 'CHARACTER', '/ines.png', {name:'Ines'}),
  asset('SET-01', 'SCENE', null, {name:'Canyon rim'}),
  asset('PROP-01', 'PROP', null, {name:'Burner valve'}),
], shots);
const editor = (item, extra = {}) => ({item, detail:null, scenes:[], writable:true, busy:false, runs:{}, onSave() {}, onUpload() {}, onGenerate() {}, onSelectImage() {},
  onOpenShot() {}, onOpenScene() {}, onTable() {}, onVault() {}, preloadedImages:[], preloadedStress:[], ...extra});
const record = (item, panels, meta = {acting:'', geo:'', light:'', lock:'', change:''}) => ({...item, variants:[], panels, meta});
const rail = html => html.match(/<nav class="world-panels" aria-label="Reference panels">[\s\S]*?<\/nav>/)[0];

// ---------- the pure model ----------

test('each type has its panels, and a panel waits for the panels it is drawn from', () => {
  assert.deepEqual(panelsOf('CHARACTER'), ['face', 'front', 'back', 'sheet']);
  assert.deepEqual(panelsOf('SCENE'), ['plate', 'reverse', 'angle']);
  assert.deepEqual(panelsOf('PROP'), ['product']);
  assert.deepEqual(panelsOf('OTHER'), []);
  const none = {face:null, front:null, back:null, sheet:null};
  assert.equal(panelBlock({type:'CHARACTER', panel:'face', panels:none}), null, 'the face needs nothing');
  assert.deepEqual(panelBlock({type:'CHARACTER', panel:'front', panels:none}), {reason:'needs', missing:['face']});
  assert.deepEqual(panelBlock({type:'CHARACTER', panel:'back', panels:none}), {reason:'needs', missing:['face', 'front']}, 'in the order they are made');
  assert.deepEqual(panelBlock({type:'CHARACTER', panel:'back', panels:{...none, face:pic('face', 1)}}), {reason:'needs', missing:['front']});
  assert.equal(panelBlock({type:'CHARACTER', panel:'back', panels:{...none, face:pic('face', 1), front:pic('front', 1)}}), null);
  assert.deepEqual(panelBlock({type:'CHARACTER', panel:'sheet', panels:none}), {reason:'made'}, 'nobody generates the sheet');
  assert.deepEqual(panelBlock({type:'SCENE', panel:'reverse', panels:{plate:null}}), {reason:'needs', missing:['plate']});
  assert.deepEqual(panelBlock({type:'SCENE', panel:'angle', panels:{plate:{url:'', imageId:'x'}}}), {reason:'needs', missing:['plate']}, 'a panel without a picture is not chosen');
  assert.equal(panelBlock({type:'SCENE', panel:'angle', panels:{plate:pic('plate', 1)}}), null);
  assert.equal(panelBlock({type:'PROP', panel:'product', panels:{}}), null);
  // A look is edited from its base's same panel, else from the base's main picture.
  assert.equal(panelBlock({type:'CHARACTER', panel:'back', panels:{}, base:{panels:{back:pic('back', 1)}}}), null, 'the look\'s own face is not needed');
  assert.equal(panelBlock({type:'CHARACTER', panel:'front', panels:{}, base:{panels:{}, selectedImageUrl:'/noa.png'}}), null);
  assert.deepEqual(panelBlock({type:'CHARACTER', panel:'front', panels:{}, base:{panels:{face:pic('face', 1)}}}), {reason:'base', panel:'front'});
});

test('the rail lists the sheet only once the server made it, and the editor opens on the next panel to make', () => {
  const empty = panelStrip({type:'CHARACTER', panels:{face:null, front:null, back:null, sheet:null}});
  assert.deepEqual(empty.list.map(entry => entry.panel), ['face', 'front', 'back']);
  assert.equal(empty.sheetPending, true);
  assert.deepEqual(empty.list.map(entry => Boolean(entry.block)), [false, true, true]);
  const done = panelStrip({type:'CHARACTER', panels:{face:pic('face', 1), front:pic('front', 1), back:pic('back', 1), sheet:pic('sheet', 1)}});
  assert.deepEqual(done.list.map(entry => [entry.panel, entry.made, entry.chosen?.imageId]), [['face', false, 'im_face_1'], ['front', false, 'im_front_1'], ['back', false, 'im_back_1'], ['sheet', true, 'im_sheet_1']]);
  assert.equal(done.sheetPending, false);
  assert.equal(panelStrip({type:'SCENE', panels:{}}).sheetPending, false, 'only a character has a sheet');

  assert.equal(startingPanel({type:'CHARACTER', panels:null, mainUrl:''}), ALL, 'panels not known yet (or an older server): the pictures as before');
  assert.equal(startingPanel({type:'CHARACTER', panels:{}, mainUrl:'/old.png'}), ALL, 'a card with a picture from before SPEC_21 opens on its pictures');
  assert.equal(startingPanel({type:'CHARACTER', panels:{}, mainUrl:''}), 'face');
  assert.equal(startingPanel({type:'CHARACTER', panels:{face:pic('face', 1)}, mainUrl:''}), 'front');
  assert.equal(startingPanel({type:'CHARACTER', panels:{face:pic('face', 1), front:pic('front', 2)}, mainUrl:''}), 'back');
  assert.equal(startingPanel({type:'CHARACTER', panels:{face:pic('face', 1), front:pic('front', 2), back:pic('back', 3), sheet:pic('sheet', 4)}, mainUrl:'/s.png'}), 'sheet');
  assert.equal(startingPanel({type:'SCENE', panels:{}, mainUrl:''}), 'plate');
  assert.equal(startingPanel({type:'SCENE', panels:{plate:pic('plate', 1)}, mainUrl:'/p.png'}), 'reverse');
  assert.equal(startingPanel({type:'PROP', panels:{product:pic('product', 1)}, mainUrl:'/p.png'}), 'product', 'all made: the first panel');
  assert.equal(startingPanel({type:'CHARACTER', panels:{}, mainUrl:'', base:{panels:{}}}), 'face', 'a look whose base has nothing: the first panel, which says why');
});

test('a panel lists its own candidates, the chosen one first, then the newest', () => {
  const images = [{imageId:'a', url:'/a.png', panel:'face'}, {imageId:'b', url:'/b.png', panel:'face'}, {imageId:'c', url:'/c.png', panel:'face'},
    {imageId:'d', url:'/d.png', panel:'front'}, {imageId:'e', url:'/e.png', panel:null}, {imageId:'f', url:''}];
  const list = panelCandidates(images, 'face', {imageId:'b', url:'/b.png'});
  assert.deepEqual(list.map(image => image.imageId), ['b', 'e', 'c', 'a'], 'another panel never shows; a candidate from before panels may');
  assert.deepEqual(list.map(image => image.chosen), [true, false, false, false]);
  assert.deepEqual(panelCandidates(null, 'face'), []);
  assert.equal(chosenPanel({face:{url:'/x.png', imageId:'x'}}, 'face').imageId, 'x');
  assert.equal(chosenPanel({face:null}, 'face'), null);
  assert.equal(hasPicture({face:null}, ''), false);
  assert.equal(hasPicture({face:pic('face', 1)}, ''), true);
  assert.equal(hasPicture(null, '/main.png'), true);
});

test('the requests are the contract of SPEC_21 §2.2', () => {
  assert.deepEqual(panelGenerationBody('face', 3), {panel:'face', count:3});
  assert.deepEqual(panelGenerationBody('front', 9), {panel:'front', count:4}, 'count is 1-4');
  assert.deepEqual(panelGenerationBody('back', 0), {panel:'back', count:1});
  assert.deepEqual(stressBody({count:6, withAssets:['cast-02', 'CAST-02', ' prop-01 '], setCode:'set-01'}), {count:6, withAssets:['CAST-02', 'PROP-01'], setCode:'SET-01'});
  assert.deepEqual(stressBody({count:2}), {count:4}, 'at least 4');
  assert.deepEqual(stressBody({count:40, withAssets:[]}), {count:10}, 'at most 10; nothing empty is sent');
  assert.deepEqual(stressBody(), {count:8});
  assert.deepEqual(stressBody({withAssets:['CAST-02', 'CAST-03', 'CAST-04', 'CAST-05', 'PROP-01', 'PROP-02']}).withAssets, ['CAST-02', 'CAST-03', 'CAST-04', 'CAST-05', 'PROP-01'], 'the server takes five co-stars at most');
  assert.deepEqual(metaPatch('acting', 'Keeps one hand on the burner.'), {acting:'Keeps one hand on the burner.'});
  assert.equal(metaPatch('voice', 'x'), null, 'only the five lock fields');
  assert.equal(metaPatch('geo', 'x'.repeat(5000)).geo.length, 4000);
  assert.deepEqual(metaPatch('light', null), {light:''});
  assert.deepEqual(LOCKS, {CHARACTER:['acting'], SCENE:['geo', 'light'], PROP:['lock']});
  assert.deepEqual(lockFields('CHARACTER'), ['acting']);
  assert.deepEqual(lockFields('SCENE', true), ['change', 'geo', 'light'], 'a look says first what it changes');
  assert.deepEqual(lockFields('PROP', true), ['change', 'lock']);
  assert.ok(LOOK_KINDS.includes('STATE'));
  assert.equal(lookReady({name:'Soaked', kind:'STATE', change:''}), false, 'a state needs its change');
  assert.equal(lookReady({name:'Soaked', kind:'STATE', change:'hair and clothes soaked'}), true);
  assert.equal(lookReady({name:'Night', kind:'OUTFIT'}), true);
  assert.equal(lookReady({name:' ', kind:'OUTFIT'}), false);
  assert.deepEqual(lookBody({name:' Soaked ', kind:'STATE', prompt:' same pilot \n', change:' hair and clothes soaked '}), {name:'Soaked', kind:'STATE', prompt:'same pilot', change:'hair and clothes soaked'});
  assert.deepEqual(lookBody({name:'Night', kind:'OUTFIT', prompt:'rain cape', change:'ignored'}), {name:'Night', kind:'OUTFIT', prompt:'rain cape'}, 'the old body, exactly, for the other kinds');
  assert.deepEqual(listOf([1, 2]), [1, 2]);
  assert.deepEqual(listOf({items:[3], nextCursor:null}), [3]);
  assert.deepEqual(listOf(null), []);
});

test('the stress test tallies "n / total recognizable", keeps the asked order, and offers the company the asset keeps', () => {
  const results = [{imageId:'s2', variation:1, recognizable:false}, {imageId:'s1', variation:0, recognizable:true}, {imageId:'s3', variation:2, recognizable:null},
    {imageId:'s4', variation:1, recognizable:true}];
  assert.deepEqual(stressTally(results), {recognizable:2, unrecognizable:1, unmarked:1, total:4});
  assert.deepEqual(stressTally(null), {recognizable:0, unrecognizable:0, unmarked:0, total:0});
  assert.deepEqual(stressOrder(results).map(item => item.imageId), ['s1', 's4', 's2', 's3'], 'by variation, the newer of a repeated one first');
  assert.deepEqual(stressMarked(results, 's3', true).map(item => item.recognizable), [false, true, true, true]);
  const fromShots = stressCompany(noa);
  assert.deepEqual(fromShots.cast.map(entry => entry.code), ['CAST-02', 'PROP-01'], 'the codes of the shots it is in, most shared first; its own look never');
  assert.deepEqual(fromShots.sets.map(entry => entry.code), ['SET-01']);
  const wall = [noa, ines, canyon, burner, {...ines, assetId:'as_CAST-02:NIGHT', assetCode:'CAST-02:NIGHT', isDefault:false}, asset('CAST-03', 'CHARACTER', null, {name:'Ranger'})];
  const named = stressCompany(noa, wall);
  assert.deepEqual(named.cast.map(entry => [entry.code, entry.name]), [['CAST-02', 'Ines'], ['PROP-01', 'Burner valve'], ['CAST-03', 'Ranger']], 'by name, shared ones first, looks left out');
  assert.deepEqual(named.sets.map(entry => entry.name), ['Canyon rim']);
});

test('panel batches run like the card\'s own picture: accepted at once, settled per task, cancelable, retried, and kept for a reload', () => {
  let runs = startPanelRuns({}, 'as_CAST-01', 'face');
  assert.deepEqual(runs, {'as_CAST-01#face#0': {taskId:'', status:'QUEUED'}});
  assert.equal(panelRunState(runs, 'as_CAST-01', 'face').status, 'active');
  assert.deepEqual(activeTasks(runs), {}, 'no task id yet: nothing to keep or cancel');
  assert.equal(startPanelRuns(runs, 'as_CAST-01', 'face'), runs, 'one batch per panel at a time');
  runs = panelRunsStarted(runs, 'as_CAST-01', 'face', {tasks:[{taskId:'t1', status:'QUEUED'}, {taskId:'t2', status:'RUNNING'}, {taskId:'t3', status:'QUEUED'}], count:3});
  assert.deepEqual(activeTasks(runs), {'as_CAST-01#face#0':'t1', 'as_CAST-01#face#1':'t2', 'as_CAST-01#face#2':'t3'});
  assert.deepEqual(panelRunState(runs, 'as_CAST-01', 'face'), {status:'active', active:3, failed:0, canceled:0, taskIds:['t1', 't2', 't3'], error:''});
  assert.equal(panelRunState(runs, 'as_CAST-01', 'front'), null, 'another panel is idle');
  assert.equal(panelRunState(runs, 'as_CAST-01:WET', 'face'), null, 'and so is the same panel of a look');
  runs = settleRun(runs, runKey('as_CAST-01', 'face', 0), {taskId:'t1', status:'SUCCEEDED'});
  runs = settleRun(runs, runKey('as_CAST-01', 'face', 1), {taskId:'t2', status:'FAILED', error:{message:'Worker unavailable'}});
  assert.deepEqual(panelRunState(runs, 'as_CAST-01', 'face'), {status:'active', active:1, failed:1, canceled:0, taskIds:['t3'], error:'Worker unavailable'});
  runs = settleRun(runs, runKey('as_CAST-01', 'face', 2), {taskId:'t3', status:'CANCELED'});
  assert.deepEqual(panelRunState(runs, 'as_CAST-01', 'face'), {status:'failed', active:0, failed:1, canceled:1, taskIds:[], error:'Worker unavailable'});
  assert.deepEqual(batchRun(panelRunState(runs, 'as_CAST-01', 'face')), {status:'FAILED', error:'Worker unavailable'});
  const retried = startPanelRuns(runs, 'as_CAST-01', 'face');
  assert.deepEqual(retried, {'as_CAST-01#face#0': {taskId:'', status:'QUEUED'}}, 'a retry replaces what the last batch left');
  assert.deepEqual(panelRunRefused(retried, 'as_CAST-01', 'face', 'Choose the face first'), {'as_CAST-01#face#0': {taskId:'', status:'FAILED', error:'Choose the face first'}});
  assert.deepEqual(createdTasks({taskId:'t9', status:'QUEUED'}), [{taskId:'t9', status:'QUEUED'}], 'a request without count answers with one task');
  assert.deepEqual(panelRunsStarted({}, 'as_SET-01', 'stress', {tasks:[{taskId:'s1', status:'SUCCEEDED'}], count:1}), {}, 'already done: nothing to watch');
  assert.deepEqual(finishedScopes([['as_CAST-01#face#0', {status:'SUCCEEDED'}], ['as_CAST-01#face#1', {status:'SUCCEEDED'}], ['as_SET-01#stress#2', {status:'SUCCEEDED'}], ['as_SET-01#plate#0', {status:'RUNNING'}]]),
    ['as_CAST-01#face', 'as_SET-01#stress']);
  assert.equal(batchRun(null), null);
  assert.deepEqual(batchRun({status:'active'}), {status:'RUNNING'});
  assert.deepEqual(batchRun({status:'canceled'}), {status:'CANCELED'});
});

test('panel tasks are remembered per card apart from the card\'s own pictures', () => {
  const store = new Map();
  globalThis.sessionStorage = {getItem: key => store.get(key) ?? null, setItem: (key, value) => store.set(key, value), removeItem: key => store.delete(key)};
  try {
    rememberGenerations('ep_x', {as_1:'t1'});
    rememberPanelGenerations('as_1', {'as_1#face#0':'t2'});
    assert.equal(store.get('zf.panelgen:as_1'), '{"as_1#face#0":"t2"}');
    assert.deepEqual(restoredGenerations('ep_x'), {as_1:'t1'}, 'neither list overwrites the other');
    assert.deepEqual(restoredPanelGenerations('as_1'), {'as_1#face#0':'t2'});
    rememberPanelGenerations('as_1', {});
    assert.equal(store.has('zf.panelgen:as_1'), false);
    store.set('zf.panelgen:as_2', 'not json');
    assert.deepEqual(restoredPanelGenerations('as_2'), {});
    delete globalThis.sessionStorage;
    rememberPanelGenerations('as_3', {'as_3#plate#0':'t3'});
    assert.deepEqual(restoredPanelGenerations('as_3'), {'as_3#plate#0':'t3'}, 'without storage, in memory');
  } finally {delete globalThis.sessionStorage;}
});

test('the reference plan reads in the order the model gets it, with each picture\'s role', () => {
  const rows = referenceRows([{assetCode:'CAST-01', role:'character_face', panel:'face', url:'/f.png'}, {assetCode:'CAST-01', role:'character_body', panel:'front', url:'/b.png'},
    {assetCode:'SET-01', role:'location', panel:'plate', url:'/p.png'}, {assetCode:'PROP-01', role:'mystery', panel:null, url:'/x.png'}, null]);
  assert.deepEqual(rows.map(row => [row.index, row.code, row.role]), [[1, 'CAST-01', 'character_face'], [2, 'CAST-01', 'character_body'], [3, 'SET-01', 'location'], [4, 'PROP-01', 'other']]);
  assert.deepEqual(referenceRows(undefined), []);
  assert.deepEqual(droppedList(['PHYSICS', '', ' CHARACTER ACTING ', null]), ['PHYSICS', 'CHARACTER ACTING']);
  assert.deepEqual(droppedList('PHYSICS'), []);
});

// ---------- the editor ----------

test('a character opens on the panel strip: All pictures, Face, Front (no head) and Back with their reasons, the sheet still to come, and the stress test', () => {
  const panels = {face:pic('face', 2), front:null, back:null, sheet:null};
  const html = render('AssetEditor', editor(noa, {detail:record(noa, panels, {acting:'Grips the rail with both hands.', geo:'', light:'', lock:'', change:''}),
    preloadedPanels:{front:[{imageId:'im_front_1', url:'/front-1.png', panel:'front'}]}}));
  assert.match(html, /<div class="world-stage">/);
  assert.ok(html.indexOf('</figure>') < html.indexOf('<nav class="world-panels"') && html.indexOf('<nav class="world-panels"') < html.indexOf('world-look-wrap'), 'the strip sits under the picture, above the looks');
  const strip = rail(html);
  assert.match(strip, /<button type="button" class="world-panel is-all" aria-pressed="false"><span class="world-panel-thumb"><span class="world-blank"><\/span><\/span><span>All pictures<\/span><\/button>/);
  assert.match(strip, /aria-pressed="false" aria-label="Face"><span class="world-panel-thumb"><img src="\/assets\/face-2\.png"/, 'the chosen face is its tile');
  assert.match(strip, /class="world-panel" aria-pressed="true" aria-label="Front \(no head\)">/, 'the next panel to make is in front of you');
  assert.match(strip, /class="world-panel is-blocked" aria-pressed="false" title="Choose the Front \(no head\) picture first\." aria-label="Back · Choose the Front \(no head\) picture first\.">/);
  assert.match(strip, /<span class="world-panel is-pending" role="note" title="The sheet appears once Face, Front and Back are chosen\."/);
  assert.match(strip, /aria-label="Stress test"><span class="world-panel-thumb">/);
  // The picture is the panel in front of you; its candidates beside it; the row under the description makes more of it.
  assert.match(html, /<figure class="world-hero"><span class="world-art-empty">.*?No Front \(no head\) picture yet<\/span><\/figure>/);
  assert.match(html, /<aside class="world-pictures" aria-label="Front \(no head\) pictures"><h3>Front \(no head\)<span class="num">1<\/span><\/h3>/);
  const bar = html.match(/<div class="world-panel-bar" role="group" aria-label="Generate Front \(no head\)">[\s\S]*?<\/div><\/div>/)[0];
  assert.match(bar, /<p class="world-panel-hint">Clothes only: shoulders to feet with the head out of frame, drawn from the chosen Face\.<\/p>/);
  assert.match(bar, /<select class="gen-count" aria-label="How many pictures" title="How many pictures"><option value="1" selected="">×1<\/option><option value="2">×2<\/option><option value="3">×3<\/option><option value="4">×4<\/option><\/select>/);
  assert.match(bar, /<button type="button" class="world-act gen-go">Generate Front \(no head\)<\/button>/);
  assert.doesNotMatch(html, /class="gen-bar"/, 'the workflow row belongs to All pictures: a panel picks its own workflow');
  // The lock sits under the description, and saves itself.
  const locks = html.match(/<div class="world-locks" role="group" aria-label="Locks">[\s\S]*?<details/)[0];
  assert.match(locks, /<p class="world-locks-head"><b>Locks<\/b><small>Pasted word for word into every prompt that uses it\. Saved when you leave the field\.<\/small><\/p>/);
  assert.match(locks, /<label for="world-lock-acting"><b>Acting profile<\/b><\/label>/);
  assert.match(locks, /<textarea id="world-lock-acting" class="world-lock-text" rows="3" maxLength="4000" placeholder="How this person behaves on camera[^"]*"[^>]*>Grips the rail with both hands\.<\/textarea>/);
  assert.ok(html.indexOf('world-describe') < html.indexOf('world-locks') && html.indexOf('world-locks') < html.indexOf('world-more'), 'under the description, above what folds away');
});

test('a card with nothing yet starts on the face; a card from before panels starts on its pictures, exactly as before', () => {
  const blank = render('AssetEditor', editor(noa, {detail:record(noa, {face:null, front:null, back:null, sheet:null}), preloadedPanels:{face:[]}}));
  assert.match(rail(blank), /class="world-panel" aria-pressed="true" aria-label="Face">/);
  assert.match(rail(blank), /class="world-panel is-blocked" aria-pressed="false" title="Choose the Face and Front \(no head\) pictures first\."/);
  assert.match(blank, /<aside class="world-pictures" aria-label="Face pictures"><h3>Face<span class="num">0<\/span><\/h3><ul><\/ul><p class="space-sub">None yet\.<\/p><\/aside>/);
  assert.match(blank, />Generate Face<\/button>/);
  assert.match(blank, /Identity only: a three-quarter close-up on mid-grey, flat light\./);
  const legacy = render('AssetEditor', editor(ines, {detail:record(ines, {face:null, front:null, back:null, sheet:null}), preloadedImages:[{imageId:'im_1', url:'/ines.png', selected:true}]}));
  assert.match(rail(legacy), /<button type="button" class="world-panel is-all" aria-pressed="true"><span class="world-panel-thumb"><img src="\/ines\.png"/, 'All pictures, the main one as its tile');
  assert.match(legacy, /<figure class="world-hero"><button type="button" class="world-zoom" aria-label="Enlarge the image"><img src="\/ines\.png" alt="Ines"\/>/);
  assert.match(legacy, /<aside class="world-pictures" aria-label="Pictures">/);
  assert.match(legacy, /<section class="gen-bar" aria-label="Generate">/, 'the workflow row, as SPEC_18 left it');
  const unknown = render('AssetEditor', editor(ines, {preloadedImages:[]}));
  assert.doesNotMatch(unknown, /world-panels|is-solo|world-locks|world-panel-bar/, 'while the server has not said it knows panels, nothing new shows');
});

test('the sheet appears once made, read-only, in the picture\'s place; a set has Plate, Reverse and Angle with two locks; a prop has its Product and shape lock', () => {
  const panels = {face:pic('face', 1), front:pic('front', 1), back:pic('back', 1), sheet:pic('sheet', 1)};
  const sheet = render('AssetEditor', editor({...noa, selectedImageUrl:'/assets/sheet-1.png'}, {detail:record(noa, panels)}));
  assert.match(rail(sheet), /class="world-panel" aria-pressed="true" aria-label="Sheet"><span class="world-panel-thumb"><img src="\/assets\/sheet-1\.png"/);
  assert.doesNotMatch(rail(sheet), /is-pending|is-blocked/);
  assert.match(sheet, /<div class="world-stage is-solo">/, 'no candidates column: there is nothing to choose');
  assert.match(sheet, /<figure class="world-hero is-wide"><button type="button" class="world-zoom" aria-label="Enlarge the image"><img src="\/assets\/sheet-1\.png"/);
  assert.match(sheet, /<p class="world-panel-hint world-panel-note">The sheet is put together from the chosen Face, Front and Back\. Choose another of those to change it\.<\/p>/);
  assert.doesNotMatch(sheet, /Generate Sheet|world-panel-bar/, 'nobody generates the sheet');

  const set = render('AssetEditor', editor(canyon, {detail:record(canyon, {plate:pic('plate', 1), reverse:null, angle:null}, {acting:'', geo:'Launch field to the east.', light:'', lock:'', change:''})}));
  assert.deepEqual([...rail(set).matchAll(/aria-label="([^"]+)"><span class="world-panel-thumb">/g)].map(match => match[1]), ['Plate', 'Reverse', 'Angle', 'Stress test']);
  assert.match(rail(set), /class="world-panel" aria-pressed="true" aria-label="Reverse">/);
  assert.doesNotMatch(rail(set), /is-pending/, 'a set has no sheet');
  assert.match(set, />Generate Reverse<\/button>/);
  assert.match(set, /<label for="world-lock-geo"><b>Location map<\/b><\/label>/);
  assert.match(set, /<label for="world-lock-light"><b>Light logic<\/b><\/label>/);
  assert.match(set, />Launch field to the east\.<\/textarea>/);
  assert.doesNotMatch(set, /Acting profile|Shape lock/);

  const prop = render('AssetEditor', editor(burner, {detail:record(burner, {product:null})}));
  assert.deepEqual([...rail(prop).matchAll(/aria-label="([^"]+)"><span class="world-panel-thumb">/g)].map(match => match[1]), ['Product', 'Stress test']);
  assert.match(prop, />Generate Product<\/button>/);
  assert.match(prop, /<label for="world-lock-lock"><b>Shape lock<\/b><\/label>/);
  assert.match(prop, /placeholder="Its exact shape and material, and what it is not/);
});

test('a reader sees the panels, the candidates and the locks, and nothing to change them with', () => {
  const html = render('AssetEditor', editor(noa, {writable:false, detail:record(noa, {face:pic('face', 1), front:null, back:null, sheet:null}, {acting:'', geo:'', light:'', lock:'', change:''}),
    preloadedPanels:{front:[]}}));
  assert.match(html, /<nav class="world-panels"/);
  assert.match(html, /<aside class="world-pictures" aria-label="Front \(no head\) pictures">/);
  assert.match(html, /<div class="world-lock is-read"><span class="world-lock-head"><b>Acting profile<\/b><\/span><p class="is-unset">Not set<\/p><\/div>/);
  for (const gone of ['<textarea', 'world-panel-bar', 'Generate Front', 'Use as', 'gen-bar']) assert.ok(!html.includes(gone), gone + ' is for writers');
});

test('a panel in flight says so on its tile and its row, and survives a reload', () => {
  const store = new Map([['zf.panelgen:as_CAST-01', JSON.stringify({'as_CAST-01#face#0':'t1', 'as_CAST-01#face#1':'t2', 'as_CAST-01#stress#0':'t3'})]]);
  globalThis.sessionStorage = {getItem: key => store.get(key) ?? null, setItem: (key, value) => store.set(key, value), removeItem: key => store.delete(key)};
  try {
    const html = render('AssetEditor', editor(noa, {detail:record(noa, {face:null, front:null, back:null, sheet:null}), preloadedPanels:{face:[]}}));
    assert.match(rail(html), /aria-label="Face · Generating"><span class="world-panel-thumb"><span class="world-blank"><\/span><span class="world-look-busy" aria-hidden="true"><svg class="ico world-spin"/);
    assert.match(rail(html), /aria-label="Stress test · Generating">/);
    assert.match(html, /<figure class="world-hero is-busy">/);
    assert.match(html, /<span class="world-run is-active" role="status">.*?Generating<\/span>/);
    assert.match(html, /<button type="button" class="world-act gen-go" disabled="">Generating<\/button><button type="button" class="world-tool">Cancel generation<\/button>/);
  } finally {delete globalThis.sessionStorage;}
});

test('the panel row says why a panel waits and holds its button; a failed batch says why and offers a retry', () => {
  const blocked = render('PanelBar', {panel:'back', hint:'x', why:'Choose the Face and Front (no head) pictures first.', state:null, dirty:false, disabled:false, onGenerate() {}, onCancel() {}});
  assert.match(blocked, /<p class="world-panel-why">Choose the Face and Front \(no head\) pictures first\.<\/p>/);
  assert.match(blocked, /<button type="button" class="world-act gen-go" disabled="">Generate Back<\/button>/);
  const failed = render('PanelBar', {panel:'face', hint:'Identity only.', why:'', state:{status:'failed', active:0, failed:2, canceled:0, taskIds:[], error:'Worker unavailable'}, dirty:false, disabled:false, onGenerate() {}, onCancel() {}});
  assert.match(failed, /<span class="gen-error" role="alert">2 failed: Worker unavailable<\/span>/);
  assert.match(failed, /<button type="button" class="world-act gen-go">Retry<\/button>/);
  assert.doesNotMatch(failed, /Cancel generation/);
  const dirty = render('PanelBar', {panel:'plate', hint:'', why:'', state:null, dirty:true, disabled:false, onGenerate() {}, onCancel() {}});
  assert.match(dirty, />Save &amp; generate Plate<\/button>/, 'the panel is drawn from the description, so a changed one is saved first');
  assert.match(render('PanelBar', {panel:'face', hint:'', why:'', state:{status:'canceled', taskIds:[]}, disabled:false, onGenerate() {}, onCancel() {}}), /<span class="gen-unknown" role="status">Canceled<\/span>/);
});

test('the stress test lists its pictures marked recognizable or not under "n / total recognizable", and its settings pick count, company and set', () => {
  const results = [{imageId:'s1', url:'/s1.png', variation:0, with:['CAST-02'], recognizable:true}, {imageId:'s2', url:'/s2.png', variation:1, with:[], recognizable:false},
    {imageId:'s3', url:'/s3.png', variation:2, with:[], recognizable:null}];
  const grid = render('StressGrid', {results, state:null, writable:true, disabled:false, onMark() {}, onZoom() {}});
  assert.match(grid, /<section class="world-stress" aria-label="Stress test"><header><h3>Stress test<\/h3><b class="world-stress-tally">1 \/ 3 recognizable<\/b><\/header>/);
  const cards = [...grid.matchAll(/<li( class="[^"]+")?>[\s\S]*?<\/li>/g)].map(match => match[0]);
  assert.equal(cards.length, 3);
  assert.match(cards[0], /^<li class="is-yes">/);
  assert.match(cards[0], /<small>#1 · with @CAST-02<\/small>/);
  assert.match(cards[0], /<button type="button" class="icon-btn" aria-pressed="true" aria-label="Picture 1: recognizable" title="Recognizable">/);
  assert.match(cards[1], /^<li class="is-no">/);
  assert.match(cards[1], /aria-pressed="true" aria-label="Picture 2: not recognizable"/);
  assert.match(cards[2], /^<li>/);
  assert.match(cards[2], /aria-label="Enlarge picture 3"><img src="\/s3\.png"/);
  const reader = render('StressGrid', {results, state:null, writable:false, disabled:false, onMark() {}, onZoom() {}});
  assert.deepEqual([...reader.matchAll(/<em>([^<]+)<\/em>/g)].map(match => match[1]), ['Recognizable', 'Not recognizable', 'Not marked']);
  assert.doesNotMatch(reader, /aria-pressed/);
  assert.match(render('StressGrid', {results:[], state:null, writable:true}), /No stress test yet\. Run one to see it in other poses, light and company/);
  assert.match(render('StressGrid', {results:[], state:{status:'active', taskIds:['t1']}, writable:true}), /<span class="world-run is-active" role="status">.*?Generating<\/span>/);

  const bar = render('StressBar', {type:'CHARACTER', company:stressCompany(noa, [noa, ines, canyon, burner]), ready:true, state:null, disabled:false, onRun() {}, onCancel() {}});
  assert.match(bar, /<div class="world-stress-with" role="group" aria-label="In frame with"><span>In frame with<\/span><button type="button" class="attr-chip" aria-pressed="false" title="@CAST-02">Ines<\/button><button type="button" class="attr-chip" aria-pressed="false" title="@PROP-01">Burner valve<\/button><\/div>/);
  assert.match(bar, /<select aria-label="Set" title="Set"><option value="" selected="">No set<\/option><option value="SET-01">Canyon rim<\/option><\/select>/);
  assert.match(bar, /<select class="gen-count" aria-label="How many pictures" title="How many pictures">(<option value="\d+"( selected="")?>×\d+<\/option>){7}<\/select>/, 'four to ten');
  assert.match(bar, /<option value="8" selected="">×8<\/option>/);
  assert.match(bar, /<button type="button" class="world-act gen-go">Run stress test<\/button>/);
  const waiting = render('StressBar', {type:'SCENE', company:{cast:[], sets:[{code:'SET-02', name:'SET-02'}]}, ready:false, state:null, disabled:false, onRun() {}, onCancel() {}});
  assert.match(waiting, /<p class="world-panel-hint">No other cast or prop shares a shot with it yet\.<\/p>/);
  assert.doesNotMatch(waiting, /aria-label="Set"/, 'a set does not stand in another set');
  assert.match(waiting, /<span class="world-panel-why">Needs a picture to start from: choose a panel or a main picture first\.<\/span>/);
  assert.match(waiting, /<button type="button" class="world-act gen-go" disabled="">Run stress test<\/button>/);
});

test('the rail shows the stress tally on its tile', () => {
  const stress = [{imageId:'s1', url:'/s1.png', variation:0, recognizable:true}, {imageId:'s2', url:'/s2.png', variation:1, recognizable:false}];
  const html = render('AssetEditor', editor(noa, {detail:record(noa, {face:pic('face', 1), front:null, back:null, sheet:null}), preloadedStress:stress, preloadedPanels:{front:[]}}));
  assert.match(rail(html), /aria-label="Stress test · 1 \/ 2 recognizable"><span class="world-panel-thumb"><img src="\/s1\.png"[^>]*\/><\/span><span>Stress test<\/span><small>1\/2<\/small><\/button>/);
});

test('the prompt preview lists the reference plan with thumbnails and roles, and what the budget left out in muted text', () => {
  const plan = [{assetCode:'CAST-01', role:'character_face', panel:'face', url:'/f.png'}, {assetCode:'CAST-01', role:'character_body', panel:'front', url:'/b.png'},
    {assetCode:'SET-01', role:'location', panel:'plate', url:'/p.png'}, {assetCode:'PROP-01', role:'prop', panel:'product', url:null}];
  const html = render('ReferencePlan', {plan, dropped:['PHYSICS', 'CHARACTER ACTING']});
  assert.match(html, /^<div class="composer-plan" role="group" aria-label="Reference images, in the order the model gets them"><b class="composer-plan-title">Reference images, in the order the model gets them<\/b><ol class="composer-plan-list">/);
  const rows = [...html.matchAll(/<li>[\s\S]*?<\/li>/g)].map(match => match[0]);
  assert.equal(rows.length, 4);
  assert.match(rows[0], /<span class="composer-plan-thumb"><img src="\/f\.png" alt="" loading="lazy"\/><i>1<\/i><\/span><span class="composer-plan-text"><b>@CAST-01<\/b><small>Face: identity only<\/small><\/span>/);
  assert.match(rows[1], /<i>2<\/i>.*<small>Body: clothes only<\/small>/);
  assert.match(rows[2], /<b>@SET-01<\/b><small>Place: space and materials only<\/small>/);
  assert.match(rows[3], /<svg[^>]*>.*<\/svg><i>4<\/i>.*<small>Prop: shape and material only<\/small>/, 'no picture yet: an icon, still numbered');
  assert.match(html, /<p class="composer-plan-dropped">Left out to fit the budget: PHYSICS · CHARACTER ACTING<\/p><\/div>$/);
  assert.equal(render('ReferencePlan', {}), '', 'a preview from before SPEC_21 has no plan: nothing new shows');
  assert.match(render('ReferencePlan', {plan:[]}), /<p class="studio-note">No reference images are sent\.<\/p>/);
  assert.match(render('ReferencePlan', {dropped:['OPTICS']}), /^<div class="composer-plan"[^>]*><p class="composer-plan-dropped">Left out to fit the budget: OPTICS<\/p><\/div>$/);
});

test('the new words read in Traditional Chinese, and every new key has both languages with the same parameters', async () => {
  for (const [section, keys] of [['world', ['panels', 'panel_face', 'panel_front', 'panel_sheet', 'panel_plate', 'panel_product', 'panel_stress', 'panelNeeds1', 'panelNeeds2', 'panelNeedsBase',
    'lock_acting', 'lock_geo', 'lock_light', 'lock_lock', 'lock_change', 'stressTally', 'stressRun', 'lookKind_STATE', 'lookStateNote']], ['composer', ['planTitle', 'planRole_character_face', 'planDropped']]]) {
    for (const key of keys) {
      assert.equal(typeof en[section][key], 'string', `${section}.${key} en`);
      assert.equal(typeof zh[section][key], 'string', `${section}.${key} zh-TW`);
      const params = text => [...text.matchAll(/\{\{(\w+)\}\}/g)].map(match => match[1]).sort();
      assert.deepEqual(params(en[section][key]), params(zh[section][key]), `${section}.${key} parameters`);
    }
  }
  await zhTW(() => {
    const html = render('AssetEditor', editor(noa, {detail:record(noa, {face:pic('face', 1), front:null, back:null, sheet:null}), preloadedPanels:{front:[]}}));
    for (const text of ['全部圖片', '臉部', '正面（無頭）', '背面', '三視圖', '壓力測試', '先選定正面（無頭）。', '生成正面（無頭）', '鎖', '行為檔']) assert.ok(html.includes(text), text);
    const grid = render('StressGrid', {results:[{imageId:'s1', url:'/s1.png', variation:0, recognizable:true}], state:null, writable:true});
    assert.ok(grid.includes('1 / 1 認得出'));
    assert.ok(render('ReferencePlan', {plan:[{assetCode:'SET-01', role:'location', url:'/p.png'}], dropped:['PHYSICS']}).includes('場景：只取空間與材質'));
  });
});

// ---------- the first frame's card (integrator note: package A's cards sort flux-klein-edit first) ----------

test('a first frame defaults to the reference card, never to an edit card, whatever order the catalog lists them in', () => {
  const card = (cardId, appCode = cardId, extra = {}) => ({appCode, card_id:cardId, name:cardId, driver:'comfy_local', tier:'open_weights', configuration:{configured:true}, ...extra});
  const catalog = [card('flux-klein-edit'), card('flux-reference-key'), card('flux-soul-cast', 'FLUX3_SOUL_CAST'), card('flux-soul-cast', 'NANO_PRO_G2_I2I_OFFICIAL')];
  const options = frameOptions(catalog);
  assert.equal(options.defaultAppCode, 'flux-reference-key');
  assert.equal(FRAME_APP, 'flux-reference-key');
  assert.deepEqual(options.apps.map(app => app.appCode), ['flux-klein-edit', 'flux-reference-key', 'FLUX3_SOUL_CAST'], 'one entry per card, aliases folded');
  assert.equal(startingApp(options, null).appCode, 'flux-reference-key');
  assert.equal(frameOptions([card('flux-klein-edit'), card('flux-soul-cast', 'FLUX3_SOUL_CAST')]).defaultAppCode, 'FLUX3_SOUL_CAST', 'the soul-cast card by its card id, though its appCode is an alias');
  assert.equal(frameOptions([card('flux-klein-edit'), card('flux-reference-key', 'flux-reference-key', {configuration:{configured:false}}), card('sdxl-frame')]).defaultAppCode, 'sdxl-frame',
    'a card that cannot run is skipped, and so is an edit card');
  assert.equal(frameOptions([card('flux-klein-edit')]).defaultAppCode, 'flux-klein-edit', 'an edit card only when it is all there is');
  assert.equal(frameOptions(catalog, 'FLUX3_SOUL_CAST').defaultAppCode, 'FLUX3_SOUL_CAST', 'a default asked for is kept');
  assert.equal(frameOptions([]).defaultAppCode, null);
  assert.equal(isEditCard({cardId:'flux-klein-edit'}), true);
  assert.equal(isEditCard({appCode:'flux-reference-key'}), false);
  assert.equal(isEditCard({appCode:'CREDIT_EDITOR'}), false, 'a word that only contains "edit" is not an edit card');
});

test("the shot's image options are used for a first frame only when they are image cards", () => {
  const server = {apps:[{appCode:'flux-reference-key', configured:true, outputs:['IMAGE']}, {appCode:'FLUX3_SOUL_CAST', configured:true, outputs:['IMAGE']}], defaultAppCode:'flux-reference-key', style:null};
  assert.equal(frameOptionsUsable(server), true);
  assert.equal(startingApp(server, null).appCode, 'flux-reference-key', "the server's default");
  assert.equal(frameOptionsUsable({apps:[{appCode:'LTX25_CINEMA_SHOT', configured:true, outputs:['VIDEO']}], defaultAppCode:'LTX25_CINEMA_SHOT'}), false, 'an older server answers with video cards');
  assert.equal(frameOptionsUsable({apps:[], defaultAppCode:null}), false);
  assert.equal(frameOptionsUsable(null), false);
});
