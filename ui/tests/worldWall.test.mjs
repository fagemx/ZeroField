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
  const result = await build({stdin: {contents: "export {WorldWall, WorldFacets, WorldList, WorldSummary} from './src/WorldWall.jsx'; export {AssetEditor} from './src/AssetEditor.jsx'; export {StoryWorld} from './src/StoryWorld.jsx'; export {StudioTopBar, episodeCounts} from './src/StudioShell.jsx'; export {setLocale} from './src/i18n/index.js';",
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
const editor = (item, extra = {}) => ({item, detail:null, scenes, writable:true, busy:false, runs:{}, onSave() {}, onUpload() {}, onGenerate() {}, onSelectImage() {}, onOpenShot() {}, onOpenScene() {}, onTable() {}, onVault() {}, ...extra});
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

const pictures = [{imageId:'im_1', url:'/kael-old.png', selected:false}, {imageId:'im_2', url:'/kael.png', selected:true}, {imageId:'im_3', url:'/kael-new.png', selected:false}];
const kaelLooks = {assetId:'as_CAST-01', variants:[
  {assetId:'as_CAST-01:NIGHT', assetCode:'CAST-01:NIGHT', variantId:'vr_1', name:'Night jacket', kind:'OUTFIT', prompt:'same courier in a rain cape', selectedImageUrl:'/night.png'},
  {assetId:'as_CAST-01:LISTEN', assetCode:'CAST-01:LISTEN', variantId:'vr_2', name:'Listening', kind:'POSE', prompt:'head tilted', selectedImageUrl:null}]};

test('the editor shows the picture and every picture of it, the looks with a + for another, the description, and what is left folded away', () => {
  const html = render('AssetEditor', editor(items[0], {detail:kaelLooks, preloadedImages:pictures, onLookCreate() {}}));
  assert.match(html, /<figure class="world-hero"><button type="button" class="world-zoom" aria-label="Enlarge the image"><img src="\/kael\.png" alt="Kael"\/>/);
  const column = html.match(/<aside class="world-pictures" aria-label="Pictures">[\s\S]*?<\/aside>/)[0];
  assert.match(column, /<h3>Pictures<span class="num">3<\/span><\/h3>/);
  assert.deepEqual([...column.matchAll(/<img src="([^"]+)"/g)].map(match => match[1]), ['/kael.png', '/kael-new.png', '/kael-old.png'], 'the main picture first, then the newest');
  assert.match(column, /<li><button type="button" aria-pressed="true" title="Main picture"><img src="\/kael\.png" alt="" loading="lazy"\/><span class="world-main-mark">/);
  assert.equal((column.match(/aria-pressed="true"/g) || []).length, 1, 'one picture is the one in front of you');
  const strip = html.match(/<div class="world-looks" role="group" aria-label="Looks">[\s\S]*?<\/div>/)[0];
  assert.deepEqual([...strip.matchAll(/<button type="button" aria-pressed="[a-z]+" title="([^"]+)"/g)].map(match => match[1]), ['Default', 'Night jacket', 'Listening']);
  assert.match(strip, /aria-pressed="true" title="Default"/, 'the card itself is the look in front of you');
  assert.match(strip, /<button type="button" class="world-look-add" aria-expanded="false"><span class="world-look-thumb">.*?<\/span><span>New look<\/span><\/button>/, 'a + at the end of the looks');
  assert.match(html, /<h2>Kael<\/h2><small>@CAST-01<\/small>/);
  assert.match(html, /<span class="world-type">Character<\/span><span class="world-status done">/);
  const describe = html.match(/<section class="world-describe"[\s\S]*?<\/section>/)[0];
  assert.match(describe, /<h3>Character description<\/h3>/);
  assert.match(describe, /<textarea[^>]*class="world-describe-text"[^>]*placeholder="Who is this\?[^"]*"[^>]*>A look for CAST-01<\/textarea>/);
  assert.match(describe, /<section class="gen-bar" aria-label="Generate"><div class="gen-row">/, 'the generation choices sit under the description, on one row');
  assert.match(describe, /<button type="button" class="world-act gen-go">Regenerate<\/button>/);
  const more = html.match(/<details class="world-more">[\s\S]*?<\/details>/)[0];
  assert.match(more, /<summary><span>More<\/span><small>Voice: Calm, measured delivery · Approved · 2 shots<\/small><\/summary>/);
  assert.match(more, /<dt>Voice<\/dt><dd class="">Calm, measured delivery<\/dd>/);
  assert.match(more, /<dt>Notes<\/dt><dd class="">Keep the coat<\/dd>/);
  assert.match(more, /Used in 2 shots across 1 scenes\./);
  assert.match(more, /title="Open shot S01"[^>]*>(<span class="world-blank"><\/span>)<span>S01<\/span>/, 'a shot without a keyframe shows a blank, in slate order');
  assert.ok(more.indexOf('>S01<') < more.indexOf('>S02<'));
  assert.match(more, /<button type="button" class="world-tool">Scene 01 · ARRIVAL<\/button>/);
  for (const label of ['Upload image', 'Variants…', 'Edit voice and notes in the sheet']) assert.ok(html.includes('>' + label + '<') || html.includes(label + '</button>'), label);
  assert.match(html, /<input hidden="" type="file" accept="image\/png,image\/jpeg,image\/webp,image\/gif" aria-label="Upload image"\/>/);
  assert.doesNotMatch(html.slice(0, html.indexOf('<details')), /<dt>/, 'nothing but the description is spread out; voice, notes and status are folded away');
});

test('the editor has a way to close it in its title row, and the lightbox is never inside the size container', () => {
  const html = render('AssetEditor', editor(items[0], {onClose() {}, preloadedImages:pictures}));
  assert.match(html, /<button type="button" class="icon-btn world-close" aria-label="Close editor" title="Close editor">/);
  const head = html.slice(html.indexOf('<header class="world-title">'), html.indexOf('</header>'));
  assert.match(head, /<h2>Kael<\/h2>.*Upload image.*world-close/, 'name, upload and close share the title row');
  assert.match(html, /<div class="world-editor-box"><div class="world-editor-body">/, 'the box is what the layout asks about its width');
  assert.doesNotMatch(html.slice(html.indexOf('<div class="world-editor-box">'), html.lastIndexOf('</div></div>')), /world-lightbox/, 'the lightbox is never inside the size container');
  assert.doesNotMatch(render('AssetEditor', editor(items[0])), /world-close/, 'without a handler there is no button that does nothing');
  assert.match(render('AssetEditor', editor(items[0], {writable:false, onClose() {}})), /aria-label="Close editor"/, 'a reader can close it too');
  assert.match(html, /<button type="button" class="icon-btn world-field-edit" aria-label="Edit Name">/, 'the name is renamed from a pencil beside it');
});

test('a card without a picture, a set and a viewer each show what fits them', () => {
  const mara = render('AssetEditor', editor(items[1], {preloadedImages:[]}));
  assert.match(mara, /world-art-empty[^>]*>.*Needs an image/);
  assert.match(mara, /<aside class="world-pictures"[\s\S]*No pictures yet\./);
  assert.match(mara, />Generate here<\/button>/);
  assert.match(mara, /<dd class="is-unset">Not set<\/dd>/);
  assert.match(mara, /No shot uses it yet\./);
  const loose = worldItems([assets[0]], [{...shots[0], sceneId:undefined}])[0];
  assert.match(render('AssetEditor', editor(loose)), /Used in 1 shots\./, 'shots that belong to no scene say only how many shots');
  assert.doesNotMatch(render('AssetEditor', editor(loose)), /across 0 scenes/);
  const set = render('AssetEditor', editor(items[2]));
  assert.match(set, /<figure class="world-hero is-wide">/);
  assert.match(set, /<h3>Set description<\/h3>/);
  assert.match(set, /placeholder="What is this place\?/);
  assert.match(set, /<dt>Ambience<\/dt><dd class="">Wind and a soft radio pulse<\/dd>/, 'a set has ambience, not a voice');
  assert.match(set, /<span class="world-type">Set<\/span>/);
  const viewer = render('AssetEditor', editor(items[0], {writable:false}));
  for (const gone of ['Regenerate', 'Upload image', '<textarea', 'gen-bar', 'world-look-add', 'aria-label="Status"', 'world-field-edit', 'Attributes']) assert.ok(!viewer.includes(gone), gone + ' is for writers');
  assert.match(viewer, /<div class="world-describe-text is-read">A look for CAST-01<\/div>/, 'a reader reads the description');
  assert.match(viewer, /Variants…/, 'a viewer can still look around');
  assert.match(viewer, /Edit voice and notes in the sheet/);
  assert.match(viewer, /<dt>Voice<\/dt><dd class="">Calm, measured delivery<\/dd>/, 'a reader still reads every field');
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

const runCard = (html, id) => html.match(new RegExp(`<li id="world-card-${id}"[^>]*>[\\s\\S]*?</li>`))[0];

test('a card says it is generating and can be canceled, a failed one says why and offers a retry, and the others stay as they were', () => {
  const html = render('WorldWall', wall({runs:{'as_CAST-01':{taskId:'t1', status:'RUNNING'}, 'as_CAST-02':{taskId:'', status:'QUEUED'}, 'as_SET-01':{taskId:'t3', status:'FAILED', error:'Worker unavailable'}}}));
  const kael = runCard(html, 'as_CAST-01');
  assert.match(kael, /^<li id="world-card-as_CAST-01" class="has-run has-btn">/);
  assert.match(kael, /<span class="world-art world-art is-busy"|<span class="world-art is-busy">/);
  assert.match(kael, /<span class="world-run is-active" role="status"><svg class="ico world-spin"[^>]*>.*?<\/svg>Generating<\/span>/);
  assert.match(kael, /<button type="button" class="world-run-btn" aria-label="Cancel generation: Kael">Cancel<\/button>/);
  const mara = runCard(html, 'as_CAST-02');
  assert.match(mara, /class="has-run"/);
  assert.match(mara, /Generating/);
  assert.doesNotMatch(mara, /world-run-btn/, 'the click is accepted at once, but there is no task to cancel until the server has made one');
  const dome = runCard(html, 'as_SET-01');
  assert.match(dome, /class="has-run has-btn"/);
  assert.match(dome, /<span class="world-run is-failed" role="alert">.*?Generation failed<small>Worker unavailable<\/small><\/span>/);
  assert.match(dome, /<button type="button" class="world-run-btn" aria-label="Retry: Observatory">Retry<\/button>/);
  assert.doesNotMatch(html.match(/<li id="world-card-as_CAST-02"[\s\S]*?<\/li>/)[0], /world-run-btn/);
});

test('a canceled card says canceled, not failed, and an idle wall has no run markup at all', () => {
  const canceled = render('WorldWall', wall({runs:{'as_CAST-01':{taskId:'t1', status:'CANCELED'}}}));
  const kael = runCard(canceled, 'as_CAST-01');
  assert.match(kael, /<span class="world-run is-canceled" role="status">Canceled<\/span>/);
  assert.doesNotMatch(kael, /world-run-btn|is-failed|has-btn/);
  assert.doesNotMatch(render('WorldWall', wall()), /world-run|has-run|is-busy|world-spin/);
  assert.match(card(render('WorldWall', wall()), 'as_CAST-01'), /class="world-card" aria-pressed="true"/, 'an idle card is exactly what it was');
});

test('the editor shows the run of the look in front of you, cannot send it again, and offers cancel and retry', () => {
  const kael = items[0];
  const running = (state, id = 'as_CAST-01') => ({runs:{[id]:state}});
  const busy = render('AssetEditor', editor(kael, {...running({taskId:'t1', status:'RUNNING'}), onCancel() {}}));
  assert.match(busy, /<figure class="world-hero is-busy">/);
  assert.match(busy, /<span class="world-run is-active" role="status">/);
  assert.match(busy, /<button type="button" class="world-act gen-go" disabled="">Generating<\/button>/);
  assert.match(busy, /<button type="button" class="world-tool">Cancel generation<\/button>/);
  assert.doesNotMatch(render('AssetEditor', editor(kael, running({taskId:'', status:'QUEUED'}))), /Cancel generation/, 'no task yet, nothing to cancel');
  const failed = render('AssetEditor', editor(kael, running({taskId:'t1', status:'FAILED', error:'Worker unavailable'})));
  assert.match(failed, /<button type="button" class="world-act gen-go">Retry<\/button>/);
  assert.match(failed, /Worker unavailable/);
  assert.doesNotMatch(failed, /is-busy|Cancel generation/);
  const idle = render('AssetEditor', editor(kael));
  assert.doesNotMatch(idle, /world-run|is-busy/);
  assert.match(idle, /<button type="button" class="world-act gen-go">Regenerate<\/button>/);
  assert.match(render('AssetEditor', editor(kael, {busy:true})), /<button type="button" class="world-act gen-go" disabled="">Regenerate<\/button>/, 'a save in flight still holds the button, as before');
  const reader = render('AssetEditor', editor(kael, {writable:false, ...running({taskId:'t1', status:'RUNNING'})}));
  assert.doesNotMatch(reader, /gen-go|Cancel generation/, 'a reader can see it is generating and can do nothing about it');
  assert.match(reader, /Generating/);
  assert.doesNotMatch(render('AssetEditor', editor(kael, running({taskId:'t9', status:'RUNNING'}, 'as_CAST-02'))), /is-busy|world-run/, 'another card being made does not touch this one');
  const lookBusy = render('AssetEditor', editor(kael, {detail:kaelLooks, ...running({taskId:'t2', status:'RUNNING'}, 'as_CAST-01:NIGHT')}));
  assert.match(lookBusy, /<span class="world-look-busy" aria-hidden="true">/, 'a look being made shows it on its own picture in the strip');
  assert.doesNotMatch(lookBusy, /<figure class="world-hero[^"]*is-busy/, 'not on the picture in front of you');
});

test('a writer edits the description in its box, adds attribute tags and looks, and edits voice, notes and status where they stand', () => {
  const kael = items[0];
  const writer = render('AssetEditor', editor(kael, {detail:kaelLooks, onLookCreate() {}, onLookRename() {}, onLookDelete() {}, ratio:'16:9', styleName:'Sci-Fi Noir'}));
  assert.match(writer, /<button type="button" class="world-tool" aria-expanded="false"><svg[^>]*>.*?<\/svg>Attributes<\/button>/, 'attribute tags are added from the description box');
  assert.doesNotMatch(writer, /world-attrs-pop/, 'closed until asked for');
  assert.doesNotMatch(writer, /world-describe-actions|Unsaved changes/, 'nothing is waiting to be saved');
  assert.match(writer, /<dt>Voice<\/dt><dd class="">Calm, measured delivery<\/dd><button type="button" class="icon-btn world-field-edit" aria-label="Edit Voice">/);
  assert.match(writer, /<dt>Notes<\/dt><dd class="">Keep the coat<\/dd><button type="button" class="icon-btn world-field-edit" aria-label="Edit Notes">/);
  assert.match(writer, /<dt>Status<\/dt><dd><select aria-label="Status"[^>]*>.*?<option value="Approved" selected="">Approved<\/option>/);
  assert.match(writer, /<section class="gen-bar" aria-label="Generate">/);
  assert.doesNotMatch(writer, /world-look-tools/, 'a look has its rename and delete once it is picked, not before');
  assert.doesNotMatch(render('AssetEditor', editor(kael)), /world-look-add/, 'looks are made only where the page can make them');
});

test('a card says how many of its looks still lack a picture, unless it is busy generating', () => {
  const withLooks = worldItems([{...assets[0], looks:{total:3, missingImages:2}}, {...assets[2], looks:{total:1, missingImages:0}}], shots);
  const html = render('WorldWall', wall({groups:worldGroups(withLooks), counts:worldCounts(withLooks), total:withLooks.length}));
  assert.match(card(html, 'as_CAST-01'), /<span class="world-lookbadge">2 looks without an image<\/span>/);
  assert.doesNotMatch(card(html, 'as_SET-01'), /lookbadge/, 'every look has its picture');
  assert.doesNotMatch(card(render('WorldWall', wall()), 'as_CAST-01'), /lookbadge/, 'no look data, no badge');
  const busy = render('WorldWall', wall({groups:worldGroups(withLooks), counts:worldCounts(withLooks), total:withLooks.length, runs:{'as_CAST-01':{taskId:'t1', status:'RUNNING'}}}));
  assert.doesNotMatch(runCard(busy, 'as_CAST-01'), /lookbadge/);
});

test('the scene filter row appears only when there is a choice, and says which scene the wall shows', () => {
  const choices = [{key:null}, {key:'sc1', label:'Scene 01 · ARRIVAL'}, {key:'__unscened'}];
  const html = render('WorldWall', wall({sceneChoices:choices, scene:'sc1'}));
  assert.match(html, /<div class="world-scene-filter" role="group" aria-label="Filter by scene"><span>Scene<\/span>/);
  assert.match(html, /<button type="button" aria-pressed="false">All<\/button><button type="button" aria-pressed="true">Scene 01 · ARRIVAL<\/button><button type="button" aria-pressed="false">Unscened<\/button>/);
  assert.match(render('WorldWall', wall({sceneChoices:choices, scene:null})), /aria-pressed="true">All<\/button>/);
  assert.doesNotMatch(render('WorldWall', wall({sceneChoices:[{key:null}]})), /world-scene-filter/, 'one choice is no choice');
  assert.doesNotMatch(render('WorldWall', wall()), /world-scene-filter/);
  assert.match(render('WorldWall', wall({groups:worldGroups([]), counts:worldCounts([]), total:0, filtered:true})), /<p class="world-empty" role="status">Nothing in this scene uses cast, sets or props yet\./);
  assert.match(render('WorldWall', wall({groups:worldGroups([]), counts:worldCounts([]), total:0})), /No cast, sets or props yet\./, 'with no filter the wall is truly empty');
});

test('the run states and the scene filter read in Traditional Chinese', async () => {
  await components.setLocale('zh-TW');
  try {
    const html = render('WorldWall', wall({runs:{'as_CAST-01':{taskId:'t1', status:'RUNNING'}, 'as_CAST-02':{taskId:'t2', status:'FAILED', error:'x'}, 'as_SET-01':{taskId:'t3', status:'CANCELED'}},
      sceneChoices:[{key:null}, {key:'sc1', label:'場 01 · ARRIVAL'}, {key:'__unscened'}], scene:null}));
    for (const text of ['生成中', '取消生成: Kael', '生成失敗', '重試: Mara', '已取消', '依場次篩選', '全部', '未分場']) assert.ok(html.includes(text), text);
  } finally {await components.setLocale('en');}
});

test('the menu counts the pictures the wall lacks, props included, and falls back to the episode when the wall is unknown', () => {
  const ep = {missingAssetCodes:['CAST-02', 'SET-01']};
  const wallAssets = [{selectedImageUrl:'/a.png'}, {selectedImageUrl:null}, {selectedImageUrl:''}, {selectedImageUrl:null}];
  assert.equal(components.episodeCounts(ep, [], wallAssets).missing, 3, 'what the wall shows under "needs an image"');
  assert.equal(components.episodeCounts(ep, [], []).missing, 0, 'a wall where every card has its picture lacks nothing');
  assert.equal(components.episodeCounts(ep, []).missing, 2, 'no asset list yet: the episode list stands');
  assert.equal(components.episodeCounts(null, [], null).missing, 0);
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
    const detail = render('AssetEditor', editor(items[0], {onLookCreate() {}}));
    for (const text of ['角色描述', '聲音', '備註', '出現在', '更多資料', '重新生成', '上傳圖片', '新增造型', '到表格編輯聲音與備註', '開啟鏡頭 S01']) assert.ok(detail.includes(text), text);
    assert.ok(render('AssetEditor', editor(items[0], {preloadedImages:pictures})).includes('圖片'), 'the pictures column');
    assert.ok(render('AssetEditor', editor(items[2])).includes('環境音'));
    assert.match(render('StudioTopBar', {project:{title:'x'}, episodes:[], epId:'e', space:'story', counts:{}, onSpace() {}, onCommand() {}, film:{open:false, onToggle() {}}, pageTitle:'Soul Cast'}), /aria-label="回到故事與世界".*<span>返回<\/span>/);
  } finally {await components.setLocale('en');}
});
