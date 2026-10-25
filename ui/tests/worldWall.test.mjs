import test, {before, after} from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {build} from 'esbuild';
import {mkdtemp, writeFile, rm} from 'node:fs/promises';
import {join, dirname, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {activeItem, worldCounts, worldFacets, worldGroups, worldItems} from '../src/worldModel.js';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
let temporary, components;
before(async () => {
  temporary = await mkdtemp(join(root, 'tests/.world-render-'));
  const result = await build({stdin: {contents: "export {WorldWall, WorldFacets, WorldList, AssetInspector, WorldSummary} from './src/WorldWall.jsx'; export {StoryWorld} from './src/StoryWorld.jsx'; export {StudioTopBar} from './src/StudioShell.jsx'; export {setLocale} from './src/i18n/index.js';",
    resolveDir: root, sourcefile: 'world-render.jsx', loader: 'jsx'}, bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', packages: 'external', loader: {'.css': 'empty'}});
  const output = join(temporary, 'components.mjs');
  await writeFile(output, result.outputFiles[0].text);
  components = await import(pathToFileURL(output));
});
after(async () => {if (temporary) await rm(temporary, {recursive: true, force: true});});
const render = (name, props) => renderToStaticMarkup(React.createElement(components[name], props));

const asset = (code, type, image, extra = {}) => ({assetId:'as_' + code, assetCode:code, name:extra.name || code, prompt:'A look for ' + code, type, isDefault:true, selectedImageUrl:image,
  voice:'', status:'Queued', notes:'', ...extra});
const assets = [
  asset('CAST-01', 'CHARACTER', '/kael.png', {name:'Kael', status:'Approved', voice:'Calm, measured delivery', notes:'Keep the coat'}),
  asset('CAST-02', 'CHARACTER', null, {name:'Mara'}),
  asset('SET-01', 'SCENE', '/dome.png', {name:'Observatory', status:'Approved', voice:'Wind and a soft radio pulse'}),
];
const shots = [
  {shotId:'sh_1', rowId:'b1', shotIndex:'S02', sceneId:'sc1', assets:['CAST-01', 'SET-01'], selectedImageUrl:'/s2.png'},
  {shotId:'sh_2', rowId:'b2', shotIndex:'S01', sceneId:'sc1', assets:['CAST-01:NIGHT'], selectedImageUrl:null},
];
const scenes = [{sceneId:'sc1', sceneIndex:1, title:'ARRIVAL'}];
const items = worldItems(assets, shots);
const wall = (extra = {}) => ({groups:worldGroups(items), counts:worldCounts(items), total:items.length, activeId:'as_CAST-01', ready:true, writable:true, disabled:false,
  missingCount:0, canGenerate:true, onPick() {}, onCreate() {}, onGenerateMissing() {}, onTable() {}, ...extra});
const inspector = (item, extra = {}) => ({item, detail:null, scenes, writable:true, busy:false, onSave() {}, onUpload() {}, onGenerate() {}, onOpenShot() {}, onOpenScene() {}, onTable() {}, onVault() {}, ...extra});
const card = (html, id) => html.match(new RegExp(`<li id="world-card-${id}">[\\s\\S]*?</li>`))[0];

test('the wall groups cast, sets and props, each card showing its image, status, use, name, code and look', () => {
  const html = render('WorldWall', wall());
  assert.match(html, /<h1>Cast &amp; sets<\/h1><span class="space-sub">2 cast · 1 sets · 0 props<\/span>/);
  for (const [type, name, count] of [['CHARACTER', 'Cast', 2], ['SCENE', 'Sets', 1], ['PROP', 'Props', 0]]) {
    assert.match(html, new RegExp(`<h2 id="world-group-${type}">${name}<span class="num">${count}</span>`));
  }
  const kael = card(html, 'as_CAST-01');
  assert.match(kael, /class="world-card" aria-pressed="true"/);
  assert.match(kael, /<img src="\/kael\.png" alt="" loading="lazy"\/>/);
  assert.match(kael, /<span class="world-status done"><i aria-hidden="true"><\/i>Approved<\/span>/);
  assert.match(kael, /<span class="world-uses">2 shots<\/span>/, 'S01 uses the NIGHT look and S02 the base, both count');
  assert.match(kael, /<b>Kael<\/b><small>@CAST-01<\/small><span class="world-desc">A look for CAST-01<\/span>/);
  const mara = card(html, 'as_CAST-02');
  assert.match(mara, /aria-pressed="false"/);
  assert.match(mara, /world-art-empty[^>]*>.*Needs an image/, 'a missing reference says so on the card');
  assert.doesNotMatch(mara, /world-uses/, 'no shot uses her yet');
  assert.match(card(html, 'as_SET-01'), /world-art is-wide/, 'sets are landscape');
  assert.match(html, /<ul class="world-cards is-wide">/);
  assert.match(html, /<h2 id="world-group-PROP">Props<span class="num">0<\/span><\/h2><ul class="world-cards is-wide"><li><button type="button" class="world-add">/, 'an empty type for a writer is just its add card');
  assert.match(html.match(/<li><button type="button" class="world-add">[\s\S]*?<\/li>/)[0], /<span>New character<\/span>/, 'the Cast group ends with its own add card');
  assert.equal((html.match(/class="world-add"/g) || []).length, 3, 'one add card per type, at the end of its cards');
});

test('only a writer can add, and a missing reference offers one batch generation', () => {
  const writer = render('WorldWall', wall({missingCount:2}));
  for (const label of ['New character', 'New set', 'New prop']) assert.ok(writer.includes(label), label);
  assert.match(writer, /<div class="world-banner" role="status"><span>2 character or scene references in this episode need an image\.<\/span><button type="button" class="world-act">Generate Missing Asset Sheets \(2\)<\/button><\/div>/);
  assert.match(render('WorldWall', wall({missingCount:2, canGenerate:false, generateHint:'Update the storyboard first'})), /class="world-act" disabled="" title="Update the storyboard first"/);
  const viewer = render('WorldWall', wall({writable:false, missingCount:2}));
  for (const label of ['New character', 'Generate Missing Asset Sheets']) assert.ok(!viewer.includes(label), label + ' is for writers');
  assert.match(viewer, /Open sheet/, 'anyone can open the sheet');
  assert.doesNotMatch(viewer, /world-add/);
  assert.match(viewer, /<p class="world-none">Nothing here yet\.<\/p>/, 'a viewer sees an empty type said plainly, with nothing to add');
  assert.doesNotMatch(render('WorldWall', wall()), /world-banner/);
});

test('an empty or loading wall says what is going on instead of showing nothing', () => {
  const empty = render('WorldWall', wall({groups:worldGroups([]), counts:worldCounts([]), total:0, activeId:''}));
  assert.match(empty, /<p class="world-empty" role="status">No cast, sets or props yet\./);
  assert.match(empty, /New character/);
  assert.match(render('WorldWall', wall({ready:false})), /<p role="status">Loading…?<\/p>|role="status">[^<]*[Ll]oading/);
  assert.match(render('WorldSummary', {withImages:0, total:0}), /<h2>Cast &amp; sets<\/h2>.*No cast, sets or props yet\./);
  assert.match(render('WorldSummary', {withImages:2, total:3}), /Pick a card to see everything about it\..*2 of 3 have a reference image\./);
});

test('the left rail filters by type with counts, and offers "needs an image" only while something does', () => {
  const html = render('WorldFacets', {facets:worldFacets(items), facet:'all', onFacet() {}});
  assert.match(html, /<button type="button" aria-current="true"><span>Everything<\/span><b class="num">3<\/b><\/button>/);
  for (const [label, count] of [['Cast', 2], ['Sets', 1], ['Props', 0], ['Needs an image', 1]]) assert.match(html, new RegExp(`<span>${label}</span><b class="num">${count}</b>`));
  const done = render('WorldFacets', {facets:worldFacets(worldItems(assets.filter(a => a.selectedImageUrl), shots)), facet:'all', onFacet() {}});
  assert.doesNotMatch(done, /Needs an image/);
});

test('the inspector shows the image, looks, what the script says, where the card appears and what you can do', () => {
  const kael = items[0];
  const detail = {assetId:'as_CAST-01', variants:[{assetId:'as_CAST-01:NIGHT', assetCode:'CAST-01:NIGHT', name:'Night jacket', kind:'OUTFIT', selectedImageUrl:'/night.png'}]};
  const html = render('AssetInspector', inspector(kael, {detail}));
  assert.match(html, /<figure class="world-hero"><button type="button" class="world-zoom" aria-label="Enlarge the image"><img src="\/kael\.png" alt="Kael"\/>/);
  assert.match(html, /<div class="world-looks" role="group" aria-label="Looks"><button type="button" aria-pressed="true" title="Default">.*?<span>Default<\/span><\/button><button type="button" aria-pressed="false" title="Night jacket"><img src="\/night\.png" alt=""\/><span>Night jacket<\/span>/);
  assert.match(html, /<h2>Kael<\/h2><small>@CAST-01<\/small>/);
  assert.match(html, /<span class="world-type">Character<\/span><span class="world-status done">/);
  assert.match(html, /<dt>Appearance<\/dt><dd class="">A look for CAST-01<\/dd>/);
  assert.match(html, /<dt>Voice<\/dt><dd class="">Calm, measured delivery<\/dd>/);
  assert.match(html, /<dt>Notes<\/dt><dd class="">Keep the coat<\/dd>/);
  assert.match(html, /Used in 2 shots across 1 scenes\./);
  assert.match(html, /title="Open shot S01"[^>]*>(<span class="world-blank"><\/span>)<span>S01<\/span>/, 'a shot without a keyframe shows a blank, in slate order');
  assert.ok(html.indexOf('>S01<') < html.indexOf('>S02<'));
  assert.match(html, /<button type="button" class="world-tool">Scene 01 · ARRIVAL<\/button>/);
  for (const label of ['Regenerate', 'Upload image', 'Edit', 'Variants…', 'Edit voice and notes in the sheet']) assert.ok(html.includes('>' + label + '<') || html.includes(label + '</button>'), label);
  assert.match(html, /<input hidden="" type="file" accept="image\/png,image\/jpeg,image\/webp,image\/gif" aria-label="Upload image"\/>/);
});

test('a card without an image, a set and a viewer each show what fits them', () => {
  const mara = render('AssetInspector', inspector(items[1]));
  assert.match(mara, /world-art-empty[^>]*>.*Needs an image/);
  assert.match(mara, />Generate here<\/button>/);
  assert.match(mara, /<dd class="is-unset">Not set<\/dd>/);
  assert.match(mara, /No shot uses it yet\./);
  const loose = worldItems([assets[0]], [{...shots[0], sceneId:undefined}])[0];
  assert.match(render('AssetInspector', inspector(loose)), /Used in 1 shots\./, 'shots that belong to no scene say only how many shots');
  assert.doesNotMatch(render('AssetInspector', inspector(loose)), /across 0 scenes/);
  const set = render('AssetInspector', inspector(items[2]));
  assert.match(set, /<figure class="world-hero is-wide">/);
  assert.match(set, /<dt>Ambience<\/dt><dd class="">Wind and a soft radio pulse<\/dd>/, 'a set has ambience, not a voice');
  assert.match(set, /<span class="world-type">Set<\/span>/);
  const viewer = render('AssetInspector', inspector(items[0], {writable:false}));
  for (const label of ['Regenerate', 'Upload image', '>Edit<']) assert.ok(!viewer.includes(label), label + ' is for writers');
  assert.match(viewer, /Variants…/, 'a viewer can still look around');
  assert.match(viewer, /Edit voice and notes in the sheet/);
});

test('the quick list beside the script shows the same assets and opens the wall on one', () => {
  const html = render('WorldList', {items, kind:'all', onKind() {}, focusCode:'CAST-01:NIGHT', onOpen() {}});
  assert.match(html, /<b>World<\/b>/);
  assert.match(html, /<li id="world-asset-as_CAST-01" class="is-focus"><button type="button" class="world-asset" title="See Kael in Cast &amp; sets">/, 'the focused asset, even by one of its looks, is marked');
  assert.match(html, /<li id="world-asset-as_CAST-02" class="is-missing ">/);
  assert.match(html, /<span class="world-status done"><i aria-hidden="true"><\/i>Approved<\/span><small>2 shots<\/small>/);
  assert.match(html, /<em>Needs an image<\/em>/);
  const cast = render('WorldList', {items, kind:'cast', onKind() {}, onOpen() {}});
  assert.ok(cast.includes('Kael') && !cast.includes('Observatory'), 'the Cast filter keeps only characters');
  assert.match(render('WorldList', {items:[], kind:'all', onKind() {}, onOpen() {}}), /No cast, sets or props yet\./);
});

test('Story & World opens on the script, with Cast & sets one click away in the left rail', () => {
  const html = render('StoryWorld', {epId:'ep_demo_01', writable:true});
  assert.match(html, /<button type="button" aria-pressed="true">By scene<\/button><button type="button" aria-pressed="false">Cast &amp; sets<\/button>/);
  assert.doesNotMatch(html, /Open sheet|world-facets/, 'the wall is a view of this space, not a page elsewhere');
});

test('a page opened from a space has a Back button to it, and the space views have none', () => {
  const props = {project:{title:'The Last Signal'}, episodes:[{episodeId:'ep_demo_01', title:'Episode 1'}], epId:'ep_demo_01', space:'story', counts:{shots:8, review:2, missing:1, filmed:6},
    onEpisode() {}, onSpace() {}, onCommand() {}, film:{open:false, onToggle() {}}};
  const sheet = render('StudioTopBar', {...props, pageTitle:'Soul Cast'});
  assert.match(sheet, /<button type="button" class="studio-back" title="Back to Story &amp; World" aria-label="Back to Story &amp; World">.*?<span>Back<\/span><\/button><span class="studio-focus" title="Soul Cast">Soul Cast<\/span>/);
  assert.doesNotMatch(render('StudioTopBar', props), /studio-back/);
  assert.match(render('StudioTopBar', {...props, space:null, pageTitle:'Pipeline'}), /aria-label="Back to Shot Stage"/, 'a page in no space goes back to the Shot Stage');
});

test('Cast & sets reads in Traditional Chinese', async () => {
  await components.setLocale('zh-TW');
  try {
    const html = render('WorldWall', wall({missingCount:1}));
    for (const text of ['角色與場景', '2 個角色 · 1 個場景 · 0 個道具', '新增角色', '新增道具', '開啟表格', '已核准', '還沒有圖']) assert.ok(html.includes(text), text);
    assert.ok(render('WorldWall', wall({writable:false})).includes('這一類還沒有設定。'));
    const detail = render('AssetInspector', inspector(items[0]));
    for (const text of ['外觀設定', '聲音', '備註', '出現在', '重新生成', '上傳圖片', '到表格編輯聲音與備註', '開啟鏡頭 S01']) assert.ok(detail.includes(text), text);
    assert.ok(render('AssetInspector', inspector(items[2])).includes('環境音'));
    assert.match(render('StudioTopBar', {project:{title:'x'}, episodes:[], epId:'e', space:'story', counts:{}, onSpace() {}, onCommand() {}, film:{open:false, onToggle() {}}, pageTitle:'Soul Cast'}), /aria-label="回到故事與世界".*<span>返回<\/span>/);
  } finally {await components.setLocale('en');}
});
