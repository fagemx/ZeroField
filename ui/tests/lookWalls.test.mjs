import test, {before, after} from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {build} from 'esbuild';
import {mkdtemp, writeFile, rm, readFile} from 'node:fs/promises';
import {join, dirname, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {LOOK_OPTIONS, ALL_LOOK_OPTIONS} from './lookOptionsFixture.mjs';
import en from '../src/i18n/locales/en.json' with {type: 'json'};
import zh from '../src/i18n/locales/zh-TW.json' with {type: 'json'};

// SPEC_19 package C (R11, R12): film setup, palette and lighting on the shot composer, the Episode look page, and the crew's look
// proposals (SPEC_20 R18). The camera catalog is the packaged one; the five look kinds come from the options draft (lookOptionsFixture).
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
let temporary, components;
before(async () => {
  temporary = await mkdtemp(join(root, 'tests/.look-walls-render-'));
  const result = await build({stdin: {contents: "export {ShotComposer} from './src/composer/ShotComposer.jsx'; export {LookWall, LookProposal, CameraWall, CameraRigWall} from './src/composer/ExampleWall.jsx'; export {EpisodeLook} from './src/EpisodeLook.jsx'; export {StoryWorld} from './src/StoryWorld.jsx'; export {setLocale} from './src/i18n/index.js';",
    resolveDir: root, sourcefile: 'look-walls-render.jsx', loader: 'jsx'}, bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', packages: 'external', loader: {'.css': 'empty'}});
  const output = join(temporary, 'components.mjs');
  await writeFile(output, result.outputFiles[0].text);
  components = await import(pathToFileURL(output));
});
after(async () => {if (temporary) await rm(temporary, {recursive: true, force: true});});
const render = (name, props) => renderToStaticMarkup(React.createElement(components[name], props));
const noop = () => {};

const camera = JSON.parse(await readFile(new URL('../../project_docs/look_catalog.json', import.meta.url), 'utf8')).items;
const lookCatalog = {camera: camera.filter(item => item.kind === 'camera'), moves: camera.filter(item => item.kind === 'move')};
const ltx = {appCode: 'ltx25-cinema', name: 'LTX-2.5 Cinema', tier: 'open_weights', configured: true, reason: null, outputs: ['VIDEO'], estimate: null, quotable: false};
const bar = {status: 'ready', options: {apps: [ltx], defaultAppCode: 'ltx25-cinema'}, catalog: []};
const episode = {aspectRatio: '21:9', stylePresetId: '88124', look: {genre: 'rain-mystery', era: 'grain-film', palette: 'midnight-slate', light: 'window-side',
  camera: {body: 'film-35mm', lens: 'anamorphic'}}};
const shotOf = (look = {}, extra = {}) => ({shotId: 'sh_demo_b2', rowId: 'b2', shotIndex: 'S02', tabKey: 'cinema-studio', reviewStatus: 'Queued', selectedVideoUrl: null,
  trim: {in: 0, out: null}, adoption: null, look, lookRevision: 4, ...extra});
function composer({look = {light: 'hard-top'}, settings = episode, rig = '', proposals = null, ...extra} = {}) {
  const shot = shotOf(look);
  return {slug: 'demo', tabKey: 'cinema-studio', rid: 'b2', shot, shots: [shot], label: 'S02', status: 'Queued', text: 'Kael waits by the dial.', promptColumn: true,
    rig: {text: rig, column: true, onWrite: noop}, ladder: [{key: 'frame', stage: {column: 2}, media: null}, {key: 'video', stage: {column: 3}, media: null}], writable: true,
    epId: 'ep_demo_01', onLook: noop, onApplyProposal: noop, onDismissProposal: noop, onDraft: noop, onSave: noop, onGenerate: noop,
    preloaded: {catalog: lookCatalog, looks: LOOK_OPTIONS, episode: settings, bar, ...(proposals ? {lookProposals: proposals} : {})}, ...extra};
}
// One look button by its label: [scope tag, value, title].
function button(html, label) {
  const found = html.match(new RegExp(`<button type="button" class="look-button"[^>]*title="([^"]*)"[^>]*>([\\s\\S]*?)</button>`, 'g')) || [];
  const one = found.find(item => item.includes(`<b>${label}</b>`));
  assert.ok(one, label + ' button');
  return {html: one, scope: one.match(/<em class="look-scope is-(\w+)">/)?.[1] || null, value: one.match(/<small>([^<]*)<\/small>/)?.[1], title: one.match(/title="([^"]*)"/)[1]};
}
const proposal = (value, extra = {}) => ({id: 9, action: 'shot_meta', status: 'pending', shotId: 'sh_demo_b2', field: 'look', baseRevision: 4, currentRevision: 4, value,
  summary: 'Warmer for the lamp scene.', author: {kind: 'member', name: 'Maya Lin'}, canDecide: true, ...extra});

const at = (dictionary, key) => key.split('.').reduce((node, part) => node?.[part], dictionary);
test('every look label the interface reads exists in both languages', () => {
  const keys = [...ALL_LOOK_OPTIONS.map(item => item.labelKey),
    ...['genre', 'era', 'tempo', 'palette', 'light'].map(kind => 'look.kind_' + kind), ...['filmSetup', 'camera', 'palette', 'lighting', 'references'].map(name => 'look.' + name),
    ...['backToEpisode', 'followsEpisode', 'ownValue', 'episodeCamera', 'previous', 'next', 'carouselAt', 'eraOlder', 'eraNewer', 'search', 'searchLabel', 'sort', 'sort_catalog',
      'sort_name', 'sort_tone', 'noMatch', 'proposed', 'proposalWaiting', 'proposalTitle', 'proposalBy', 'proposalCrew', 'proposalToEpisode', 'proposalApply', 'proposalApplying',
      'proposalDismiss', 'proposalStale', 'proposalReadOnly', 'proposalMore'].map(key => 'look.' + key),
    ...['title', 'open', 'hint', 'format', 'ratio', 'style', 'noStyles', 'looks', 'pick', 'apply', 'applying', 'applied', 'unsaved', 'loading', 'failed', 'overrides',
      'cameraHint', 'cameraOverrides'].map(key => 'episodeLook.' + key), 'composer.preview_film', 'composer.preview_color', 'composer.preview_light',
    ...['lookNotObject', 'unknownLookSetting', 'unknownLookOption', 'shotLookRevisionConflict', 'shotProposalLookChanged', 'shotProposalLookInvalid'].map(key => 'errors.' + key)];
  for (const key of keys) {
    assert.equal(typeof at(en, key), 'string', 'en: ' + key);
    assert.equal(typeof at(zh, key), 'string', 'zh-TW: ' + key);
  }
  assert.equal(ALL_LOOK_OPTIONS.length, 41, '36 options and 5 Auto');
  assert.equal(at(en, 'look.kind_era'), 'Image era'); assert.equal(at(zh, 'look.kind_era'), '影像年代');
  assert.equal(at(zh, 'lookCatalog.era.tapeEra'), '錄影帶年代'); assert.equal(at(en, 'lookCatalog.palette.dryOchre'), 'Dry ochre');
  assert.equal(at(zh, 'lookCatalog.genre.closeWarmth'), '近身暖意'); assert.equal(at(en, 'lookCatalog.tempo.holdThenBurst'), 'Hold, then burst');
});

test('C1: the five look buttons follow the episode look, say Episode or This shot, and show a palette as its colours', () => {
  const html = render('ShotComposer', composer());
  assert.deepEqual([...html.matchAll(/class="look-button"[^>]*>[\s\S]*?<b>([^<]+)<\/b>/g)].map(match => match[1]), ['References', 'Film setup', 'Camera', 'Color palette', 'Lighting']);
  const film = button(html, 'Film setup');
  assert.deepEqual([film.scope, film.value], ['episode', 'Rain-soaked mystery · Grain-film era']);
  assert.match(film.title, /Genre: Rain-soaked mystery · Image era: Grain-film era/, 'the full value on hover');
  const palette = button(html, 'Color palette');
  assert.deepEqual([palette.scope, palette.value], ['episode', 'Midnight slate']);
  assert.match(palette.html, /<span class="look-swatch" style="background:linear-gradient\(90deg, #2E3A4A 0% 28\.57%, #5B6F86 28\.57% 42\.86%/, 'a swatch strip, the main colour widest');
  const light = button(html, 'Lighting');
  assert.deepEqual([light.scope, light.value], ['shot', 'Hard overhead light'], 'the shot overrides its lighting');
  assert.match(light.html, /<span class="look-texture" style="--look-hue:\d+" aria-hidden="true"><\/span>/, 'no example media yet: a texture');
  const cam = button(html, 'Camera');
  assert.deepEqual([cam.scope, cam.value], ['episode', '35mm film · Anamorphic'], 'an empty Optical Rig cell: the episode camera');
  assert.equal(button(render('ShotComposer', composer({rig: camera.find(item => item.id === 'film-16mm').promptText})), 'Camera').scope, 'shot', 'text in the cell is the shot\'s own');
  assert.equal(button(render('ShotComposer', composer({settings: {aspectRatio: '16:9'}})), 'Camera').scope, 'shot', 'no episode camera: as before');

  // The episode look changes: the shot that follows it shows the new value, the override stays.
  const next = render('ShotComposer', composer({settings: {...episode, look: {...episode.look, palette: 'lamp-amber', light: 'low-sun'}}}));
  assert.deepEqual([button(next, 'Color palette').scope, button(next, 'Color palette').value], ['episode', 'Lamp amber']);
  assert.deepEqual([button(next, 'Lighting').scope, button(next, 'Lighting').value], ['shot', 'Hard overhead light']);
  const bare = render('ShotComposer', composer({look: {}, settings: {}}));
  assert.deepEqual([button(bare, 'Lighting').scope, button(bare, 'Lighting').value], ['episode', 'Auto'], 'nothing set anywhere: Auto, following the episode');
  assert.match(button(bare, 'Film setup').html, /<span class="look-texture is-auto" aria-hidden="true"><\/span>/, 'Auto is its own texture, no word in a small picture');
  assert.equal((html.match(/class="primary composer-go"/g) || []).length, 1, 'still one primary button');
});

test('a pending look proposal dots the button it touches', () => {
  const html = render('ShotComposer', composer({proposals: [proposal({palette: 'lamp-amber'})]}));
  assert.match(button(html, 'Color palette').html, /<i class="look-dot is-proposal" aria-hidden="true"><\/i>/);
  assert.match(button(html, 'Color palette').title, /A crew proposal is waiting/);
  for (const label of ['Film setup', 'Lighting', 'Camera', 'References']) assert.doesNotMatch(button(html, label).html, /is-proposal/, label);
  assert.match(button(render('ShotComposer', composer({proposals: [proposal({tempo: 'still-hold'})]})), 'Film setup').html, /is-proposal/, 'tempo belongs to film setup');
});

const wall = (button, extra = {}) => ({button, options: {status: 'ready', error: '', kinds: LOOK_OPTIONS}, category: 'genre', onCategory: noop,
  value: kind => ({genre: 'bright-caper', era: 'grain-film', tempo: null, palette: 'midnight-slate', light: 'hard-top'})[kind] ?? null,
  scope: kind => ({genre: {scope: 'shot', value: 'bright-caper'}, light: {scope: 'shot', value: 'hard-top'}})[kind] || {scope: 'episode', value: null},
  episode: kind => episode.look[kind] ?? null, changed: ['genre'], onChoose: noop, onBack: noop, onReset: noop, onClose: noop, ...extra});

test('the film setup wall: genre, image era and tempo on the left, a carousel and a scale, a dot and Back to episode for an override', () => {
  const html = render('LookWall', wall('filmSetup'));
  assert.match(html, /<section class="example-wall" tabindex="-1" aria-label="Film setup">/);
  assert.match(html, /<button type="button" class="quiet">Reset all<\/button>/, 'Reset all at the top right');
  assert.match(html, /aria-label="Close \(Esc\)"/);
  assert.deepEqual([...html.matchAll(/<nav class="example-wall-nav"[\s\S]*?<\/nav>/g)][0][0].match(/<span>[^<]+<\/span>/g), ['<span>Genre</span>', '<span>Image era</span>', '<span>Tempo</span>']);
  assert.match(html, /<button type="button" aria-current="true"><span>Genre<\/span><i class="look-dot" aria-label="Changed"><\/i><\/button>/, 'the overridden kind has a dot');
  assert.match(html, /Set for this shot · the episode has Rain-soaked mystery/);
  assert.match(html, /<button type="button" class="quiet">Back to episode<\/button>/);
  assert.match(html, /<div class="look-carousel" role="group" aria-label="Genre">/);
  assert.match(html, /aria-label="Previous"/); assert.match(html, /aria-label="Next" disabled=""/, 'the carousel opens on the choice, at the end of the row');
  assert.match(html, /7–9 of 9/);
  assert.equal((html.match(/class="look-tile[^"]*"/g) || []).length, 3, 'three large examples at a time');
  assert.match(html, /class="look-tile is-selected" aria-pressed="true"[^>]*>[\s\S]*?<span class="look-name">Bright caper<\/span>/);
  assert.doesNotMatch(html, /<video/, 'no example plays until the pointer rests on it');
  assert.doesNotMatch(html, /class="primary/, 'a wall has no OK button: a choice applies at once');

  const era = render('LookWall', wall('filmSetup', {category: 'era', changed: []}));
  assert.match(era, /<div class="look-scale" role="group" aria-label="Image era"><div class="look-scale-auto"><button type="button" class="look-tile"[^>]*>[\s\S]*?<b>Auto<\/b>/, 'Auto is its own cell, an abstract texture');
  assert.deepEqual([...era.matchAll(/<li[^>]*><button[\s\S]*?<span class="look-name">([^<]+)<\/span>/g)].map(match => match[1]),
    ['Early-lens era', 'Saturated-print era', 'Grain-film era', 'Tape era', 'Clean digital era'], 'oldest to newest');
  assert.match(era, /<li class="is-on">/); assert.match(era, /<span>Older<\/span><span>Newer<\/span>/);
  assert.match(era, /Follows the episode/); assert.doesNotMatch(era, /Back to episode/);
  assert.match(render('LookWall', wall('filmSetup', {category: 'tempo'})), /<div class="look-carousel" role="group" aria-label="Tempo">/);

  const reader = render('LookWall', wall('filmSetup', {disabled: true}));
  assert.doesNotMatch(reader, /Back to episode|Reset all/, 'a reader cannot write');
  assert.ok((reader.match(/class="look-tile[^"]*" aria-pressed="(true|false)" disabled=""/g) || []).length === 3);
});

test('palette and lighting are card grids with search and sort; a palette shows its own colours', () => {
  const html = render('LookWall', wall('palette', {changed: []}));
  assert.match(html, /<div class="example-wall-body is-single">/, 'one kind: no category column');
  assert.match(html, /<input type="search" class="look-search" aria-label="Search Color palette" placeholder="Search" value=""\/>/);
  assert.match(html, /<select aria-label="Sort"><option value="catalog" selected="">Suggested order<\/option><option value="name">Name<\/option><option value="tone">Dark to light<\/option><\/select>/);
  assert.equal((html.match(/class="look-tile[^"]*"/g) || []).length, 13, 'Auto and twelve palettes');
  assert.match(html, /<span class="look-frame"><span class="look-texture is-auto" aria-hidden="true"><b>Auto<\/b><\/span><\/span><span class="look-name">Auto<\/span>/);
  assert.match(html, /class="look-tile is-selected"[^>]*><span class="look-frame"><span class="look-swatch" style="background:linear-gradient\(90deg, #2E3A4A/);
  assert.match(html, /Follows the episode/);
  const light = render('LookWall', wall('lighting', {changed: ['light']}));
  assert.match(light, /<option value="name">Name<\/option><\/select>/); assert.doesNotMatch(light, /Dark to light/, 'only palettes sort by tone');
  assert.match(light, /Set for this shot · the episode has Side-window soft light/);
  assert.match(light, /Back to episode/);
  assert.equal((light.match(/class="look-tile[^"]*"/g) || []).length, 8);
});

test('a crew proposal shows in the wall it touches with Apply and Dismiss for the person it was made for, read-only for a viewer', () => {
  const review = {id: 9, proposal: proposal({palette: 'lamp-amber', genre: null}), values: {genre: null, palette: 'lamp-amber'}, kinds: ['genre', 'palette'], buttons: ['filmSetup', 'palette'],
    author: 'Maya Lin', summary: 'Warmer for the lamp scene.', baseRevision: 3, currentRevision: 4, stale: true, canDecide: true, readOnly: false, more: 1, error: ''};
  const html = render('LookWall', wall('palette', {review, onApply: noop, onDismiss: noop}));
  assert.match(html, /<section class="look-proposal" aria-label="Crew proposal"><header><i class="look-dot is-proposal" aria-hidden="true"><\/i><b>Maya Lin proposes<\/b><\/header>/);
  assert.match(html, /<li><span>Genre<\/span><b>Back to the episode<\/b><\/li><li><span>Color palette<\/span><b>Lamp amber<\/b><\/li>/);
  assert.match(html, /Warmer for the lamp scene\./);
  assert.match(html, /revision 3, now 4/);
  assert.match(html, /<button type="button" class="look-act">Apply<\/button><button type="button" class="quiet">Dismiss<\/button>/);
  assert.match(html, /1 more after this one/);
  assert.match(html, /<span class="look-flag">Proposed<\/span><\/span><span class="look-name">Lamp amber<\/span>/, 'the proposed example says so');
  assert.match(render('LookWall', wall('filmSetup', {review})), /<span>Genre<\/span>[\s\S]*?<i class="look-dot is-proposal" aria-label="A crew proposal is waiting">/, 'its category is dotted');
  assert.doesNotMatch(render('LookWall', wall('lighting', {review})), /look-proposal/, 'a wall it does not touch does not show it');
  const reader = render('LookWall', wall('palette', {review: {...review, canDecide: false, readOnly: true}}));
  assert.doesNotMatch(reader, />Apply<|>Dismiss</); assert.match(reader, /Only a member who can edit can apply it\./);
  assert.match(render('LookWall', wall('palette', {review, decision: 'apply'})), /<button type="button" class="look-act" disabled="">Applying…<\/button>/);
});

test('the camera wall says when an empty Optical Rig follows the episode camera, and text in it can go back to the episode', () => {
  const groups = {body: lookCatalog.camera.filter(item => item.group === 'body'), lens: lookCatalog.camera.filter(item => item.group === 'lens'), aperture: lookCatalog.camera.filter(item => item.group === 'aperture')};
  const base = {catalog: {status: 'ready', items: lookCatalog.camera, groups}, choice: {body: 'film-35mm', lens: 'anamorphic', aperture: 'auto-aperture'}, custom: false, moves: lookCatalog.moves,
    numbers: {}, order: [], category: 'rig', onCategory: noop, onChoose: noop, onMove: noop, onClose: noop, onReset: noop};
  const follows = render('CameraWall', {...base, episodeNote: 'The Optical Rig cell is empty, so this shot uses the episode\'s camera: 35mm film · Anamorphic. A choice here writes this shot\'s own.'});
  assert.match(follows, /<span class="studio-note" role="note">The Optical Rig cell is empty, so this shot uses the episode&#x27;s camera: 35mm film · Anamorphic\./);
  assert.doesNotMatch(follows, /Back to episode/);
  assert.match(render('CameraWall', {...base, onBack: noop}), /<button type="button" class="quiet">Back to episode<\/button>/);
  assert.doesNotMatch(render('CameraWall', {...base, onBack: noop, disabled: true}), /Back to episode/);
  assert.doesNotMatch(render('CameraWall', base), /look-wall-scope/, 'package B as it was without an episode camera');
});

const styles = [{stylePresetId: '88123', name: 'Sci-Fi Noir Anamorphic', sampleImage: '/projects/assets/style-samples/sci-fi-noir.svg'}, {stylePresetId: '88124', name: 'Cel-Shaded Anime Drama', sampleImage: '/projects/assets/style-samples/cel-shaded-anime.svg'}];
const page = (extra = {}) => ({epId: 'ep_demo_01', styles, shots: [shotOf({genre: 'bright-caper'}), shotOf({}, {opticalRig: '16mm'}), shotOf({})], writable: true, onClose: noop, onApplied: noop,
  preloaded: {settings: episode, catalog: lookCatalog, looks: LOOK_OPTIONS}, ...extra});

test('R12: the Episode look page holds the ratio, the style samples and the episode\'s four look walls, with one primary Apply to episode', () => {
  const html = render('EpisodeLook', page());
  assert.match(html, /<section class="episode-look" tabindex="-1" aria-label="Episode look"><header class="episode-look-head"><h2>Episode look<\/h2>/);
  assert.match(html, /<button type="button" class="icon-btn" aria-label="Close \(Esc\)"/, 'never a dead end');
  assert.deepEqual([...html.matchAll(/<button type="button" aria-pressed="(true|false)">(\d+:\d+)<\/button>/g)].map(match => match[2] + (match[1] === 'true' ? '*' : '')), ['16:9', '9:16', '1:1', '21:9*']);
  assert.match(html, /<button type="button" class="look-tile is-selected" aria-pressed="true"><span class="look-frame"><img src="\/projects\/assets\/style-samples\/cel-shaded-anime\.svg" alt="" loading="lazy"\/><\/span><span class="look-name">Cel-Shaded Anime Drama<\/span><\/button>/,
    'the style is chosen from its sample');
  assert.deepEqual([...html.matchAll(/class="look-button[^"]*"[^>]*>[\s\S]*?<b>([^<]+)<\/b>/g)].map(match => match[1]), ['Film setup', 'Camera', 'Color palette', 'Lighting']);
  assert.doesNotMatch(html, /class="look-scope/, 'the episode page is the episode: no Episode / This shot tags');
  assert.match(html, /<button type="button" class="look-button is-open" aria-expanded="true"/, 'film setup is open to begin with');
  assert.match(html, /1 shots set their own/, 'how many shots keep their own genre');
  assert.doesNotMatch(html, /Back to episode/);
  const primaries = html.match(/class="primary[^"]*"/g) || [];
  assert.deepEqual(primaries, ['class="primary episode-look-apply"'], 'one primary button');
  assert.match(html, /<button type="button" class="primary episode-look-apply" disabled="">Apply to episode<\/button>/, 'nothing changed yet');
  assert.match(html, /<span>Genre<\/span><i class="look-dot" aria-label="Changed"><\/i>/, 'what the episode sets is dotted');
  assert.doesNotMatch(render('EpisodeLook', page({writable: false})), /episode-look-apply/);
  const cam = render('EpisodeLook', page({preloaded: {...page().preloaded, wall: 'camera'}}));
  assert.match(cam, /<section class="look-column" aria-label="Body">/);
  assert.match(cam, /class="look-tile is-selected is-small"[^>]*>[\s\S]*?<span class="look-name">35mm film<\/span>/);
  assert.match(cam, /an empty cell uses this camera\. 1 shots have their own\./);
  assert.doesNotMatch(cam, /Camera moves/, 'a move is a tag in a shot\'s prompt, not an episode setting');
  assert.match(render('EpisodeLook', page({preloaded: {...page().preloaded, wall: null}})), /Pick a look button to see its examples\./);
});

test('the Episode look page and the new walls read in Traditional Chinese', async () => {
  await components.setLocale('zh-TW');
  try {
    const html = render('EpisodeLook', page());
    for (const text of ['本集質感', '套用到本集', '比例', '畫風', '片型', '類型', '影像年代', '節奏', '雨夜謎案', '1 鏡自己設定']) assert.ok(html.includes(text), text);
    const shot = render('ShotComposer', composer());
    for (const text of ['片型', '色調', '燈光', '本集', '本鏡', '午夜石板', '頂光硬影']) assert.ok(shot.includes(text), text);
    assert.match(render('LookWall', wall('filmSetup')), /回到本集/);
  } finally {await components.setLocale('en');}
});

test('Story & World: the format tile opens the Episode look page over the middle and right columns; the dialog no longer asks the style', async () => {
  const html = render('StoryWorld', {slug: 'demo', me: {actor_id: 'actor'}, epId: 'ep_demo_02', writable: true});
  assert.match(html, /<button type="button" class="space-foot world-format-btn" title="Episode look" aria-expanded="false" aria-label="Episode look: 16:9">/);
  assert.doesNotMatch(html, /class="episode-look"/, 'closed until the tile is pressed');
  const source = await readFile(join(root, 'src/StoryWorld.jsx'), 'utf8');
  assert.match(source, /onClick=\{\(\) => setLookOpen\(open => !open\)\}/);
  assert.match(source, /\{lookOpen && <EpisodeLook epId=\{epId\} ep=\{ep\} styles=\{styles\} shots=\{shots\} writable=\{writable\} onClose=\{closeLook\} onApplied=\{appliedLook\}\/>\}/);
  assert.match(source, /className=\{'studio-space story-world' \+ \(lookOpen \? ' is-look' : active \? ' is-editing' : ''\)\}/, 'the page takes the middle and right columns; they stay mounted underneath');
  assert.match(source, /\{!lookOpen && <button type="button" className="primary studio-primary"/, 'while the page is open its Apply is the one primary button');
  assert.match(source, /<BreakdownDialog value=\{\{breakdownMode, ratio, style\}\} styles=\{\[\]\}/, 'the storyboard dialog passes the episode style on unchanged');
  assert.match(source, /formatTile\.current\?\.focus\(\)/, 'closing returns to the tile that opened it');
  const css = await readFile(join(root, 'src/composer/composer.css'), 'utf8');
  assert.match(css, /\.story-world\.is-look > \.space-main, \.story-world\.is-look > \.space-detail \{ display: none; \}/);
});

test('look writes go through the sheet: readers cannot write, an open prompt draft stays open, the answered shot replaces its entry', async () => {
  const sheet = await readFile(join(root, 'src/SheetWorkspace.jsx'), 'utf8');
  const write = sheet.match(/const lookWrite=([^\n]*\n[^\n]*)/)?.[1] || '';
  assert.match(write, /^fn=>\{if\(!writable\)return Promise\.resolve\(false\);/, 'a reader writes nothing');
  assert.match(write, /if\(editing&&editing\.source!=='composer'\)\{guardDraft\(\);return Promise\.resolve\(false\);\}/, 'only a draft outside the composer stops it, as for the Optical Rig');
  assert.match(write, /return run\(async\(\)=>/, 'one write at a time, errors shown like the other writes');
  assert.match(write, /setShotInfo\(old=>\(\{\.\.\.old,\[view\.rowId\]:\{\.\.\.old\[view\.rowId\],\.\.\.view\}\}\)\)/);
  assert.match(write, /if\(e\?\.status===409\)setTakesNonce\(n=>n\+1\)/, 'a stale revision reads the shots again');
  assert.match(sheet, /epId=\{epId\} onLook=\{lookWrite\} onApplyProposal=\{onApplyProposal\} onDismissProposal=\{onDismissProposal\}\/>;/);
  const composerSource = await readFile(join(root, 'src/composer/ShotComposer.jsx'), 'utf8');
  assert.match(composerSource, /const putLook = body => \{if \(writable\) lookWrite\(\(\) => storyRequest\(`\/shots\/\$\{id\}\/look`, 'PUT', body\)\);\};/);
  assert.match(composerSource, /onApplyProposal\(review\.proposal, undefined, \{\}\)/, 'applied like a 3D plan proposal');
  assert.match(composerSource, /return storyRequest\(`\/shots\/\$\{id\}`\);/, 'an applied proposal reads the shot again');
});
