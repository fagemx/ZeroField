import test, {before, after} from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {build} from 'esbuild';
import {mkdtemp, writeFile, rm} from 'node:fs/promises';
import {join, dirname, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {shotBindings} from '../src/bindingModel.js';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
let temporary, components;
before(async () => {
  temporary = await mkdtemp(join(root, 'tests/.shot-render-'));
  const result = await build({stdin: {contents: "export {ShotBindings, BindingText} from './src/ShotBindings.jsx'; export {MediaLadder} from './src/ShotStage.jsx'; export {OutlineView} from './src/ScriptOutline.jsx'; export {setLocale} from './src/i18n/index.js';",
    resolveDir: root, sourcefile: 'shot-render.jsx', loader: 'jsx'}, bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', packages: 'external', loader: {'.css': 'empty'}});
  const output = join(temporary, 'components.mjs');
  await writeFile(output, result.outputFiles[0].text);
  components = await import(pathToFileURL(output));
});
after(async () => {if (temporary) await rm(temporary, {recursive: true, force: true});});
const render = (name, props) => renderToStaticMarkup(React.createElement(components[name], props));

const lookup = {
  'CAST-01': {id:'CAST-01', name:'Kael', media:{kind:'image', url:'/kael.png'}},
  'CAST-01:NIGHT': {id:'CAST-01:NIGHT', name:'Night jacket', media:{kind:'image', url:'/night.png'}},
  'SET-01': {id:'SET-01', name:'Observatory', media:{kind:'image', url:'/dome.png'}},
  'PROP-01': {id:'PROP-01', name:'Reel recorder'},  // listed, no picture yet
  'CAST-02': {id:'CAST-02', name:'Mara', media:{kind:'image', url:'/mara.png'}},
};
const sentence = '@CAST-01 turns @PROP-01 toward the open dome of @SET-01.';
const castProps = (extra = {}) => ({rows:shotBindings(sentence, lookup), lookup, elsewhere:{}, writable:true, disabled:false, onLook() {}, onRemove() {}, onAdd() {}, onOpen() {}, ...extra});
const row = (html, name) => html.match(new RegExp(`<li[^>]*>(?:(?!</li>)[\\s\\S])*<b>${name}</b>[\\s\\S]*?</li>`))?.[0] || '';

test('the cast lists each code in order with its picture, name, a look menu, and a way to remove it', () => {
  const html = render('ShotBindings', castProps());
  assert.match(html, /<section class="shot-cast" aria-label="On set">/);
  assert.match(html, /<h3>On set<span class="num">3<\/span><\/h3>/);
  assert.ok(html.indexOf('<b>Kael</b>') < html.indexOf('<b>Reel recorder</b>') && html.indexOf('<b>Reel recorder</b>') < html.indexOf('<b>Observatory</b>'), 'in the order the sentence names them');
  const kael = row(html, 'Kael');
  assert.match(kael, /<img src="\/kael\.png" alt="" loading="lazy"\/>/);
  assert.match(kael, /<small>@CAST-01<\/small>/);
  assert.match(kael, /<select class="cast-look" aria-label="Look of Kael">/);
  assert.match(kael, /<option value="CAST-01" selected="">Default<\/option><option value="CAST-01:NIGHT">Night jacket<\/option>/, 'the look menu offers the default and the sheet\'s looks, the one in the text selected');
  assert.match(kael, /<button type="button" class="icon-btn cast-remove" aria-label="Remove @CAST-01 from this shot">/);
  assert.doesNotMatch(row(html, 'Observatory'), /<select/, 'a place with no looks has no look menu');
  assert.match(html, /<button type="button" class="quiet" aria-expanded="false"[^>]*>.*?Add<\/button>/);
});

test('a look in the sentence shows as selected, and a look the sheet does not list is still an option', () => {
  const night = render('ShotBindings', castProps({rows:shotBindings('@cast-01:night waits', lookup)}));
  assert.match(night, /<option value="CAST-01">Default<\/option><option value="CAST-01:NIGHT" selected="">Night jacket<\/option>/);
  const odd = render('ShotBindings', castProps({rows:shotBindings('@CAST-01:DAY waits', lookup)}));
  assert.match(odd, /<option value="CAST-01:DAY" selected="">day<\/option>/, 'the text says DAY, so the menu must not pretend otherwise');
});

test('a code without a picture says so and offers to add one; an unlisted code is flagged and has nothing to open', () => {
  const html = render('ShotBindings', castProps());
  const recorder = row(html, 'Reel recorder');
  assert.match(recorder, /binding-thumb is-blank/);
  assert.match(recorder, /<em>no reference image<\/em>/);
  assert.match(recorder, /<button type="button" class="cast-fix">Add reference<\/button>/);
  assert.doesNotMatch(row(html, 'Kael'), /cast-fix/);
  const ghost = render('ShotBindings', castProps({rows:shotBindings('@CAST-09 waits', lookup)}));
  assert.match(ghost, /<b>CAST-09<\/b>/);
  assert.match(ghost, /<em>not on the cast sheet<\/em>/);
  assert.doesNotMatch(ghost, /cast-fix|<select/, 'there is no asset to fix or to give a look');
  assert.doesNotMatch(render('ShotBindings', castProps({onOpen:undefined})), /cast-fix/, 'with nowhere to go, no button that goes there');
});

test('a code that also sits in another cell says where, and one named only there is listed but cannot be removed here', () => {
  const html = render('ShotBindings', castProps({elsewhere:{'PROP-01':['Director Take Notes'], 'CAST-02':['Director Take Notes', 'Previs']}}));
  assert.match(row(html, 'Reel recorder'), /<small class="cast-also">Also in: Director Take Notes<\/small>/);
  const mara = row(html, 'Mara');
  assert.match(mara, /class="is-elsewhere"/);
  assert.match(mara, /Only in: Director Take Notes, Previs/);
  assert.doesNotMatch(mara, /cast-remove|<select/);
  assert.match(html, /<span class="num">4<\/span>/, 'the count includes it: the shot still uses her');
});

test('a reader sees the cast without any control; a busy sheet disables them; an empty shot says so', () => {
  const reader = render('ShotBindings', castProps({writable:false}));
  for (const control of ['<select', 'cast-remove', 'binding-add', 'aria-expanded']) assert.ok(!reader.includes(control), control + ' is for writers');
  assert.match(reader, /<span class="cast-look-static">Default<\/span>/);
  const busy = render('ShotBindings', castProps({disabled:true}));
  assert.match(busy, /<select class="cast-look" aria-label="Look of Kael" disabled="">/);
  assert.match(busy, /class="icon-btn cast-remove"[^>]*disabled=""/);
  assert.match(busy, /<button type="button" class="quiet" aria-expanded="false" disabled="">/);
  assert.match(render('ShotBindings', castProps({rows:[]})), /No cast, sets or props named in this shot yet\./);
});

test('the prompt reads as text with tags: a picture and a name for each code, a warning for an unknown one', () => {
  const html = render('BindingText', {text:'@cast-01:night shows @PROP-01 to @CAST-09.', lookup, onOpen() {}});
  assert.match(html, /^<span class="binding-text"><button type="button" class="binding-tag" title="Open Night jacket in Cast &amp; sets"><span class="binding-thumb"><img src="\/night\.png" alt="" loading="lazy"\/><\/span><span>Night jacket<\/span><\/button> shows /);
  assert.match(html, /<button type="button" class="binding-tag is-missing" title="Open Reel recorder in Cast &amp; sets"><span class="binding-thumb is-blank"><\/span><span>Reel recorder<\/span><\/button>/);
  assert.match(html, /<span class="binding-tag is-unknown" role="note">.*?Can&#x27;t find @CAST-09<\/span>\.<\/span>$/, 'the text around the tags is exactly the original, and the warning replaces nothing');
  const plain = render('BindingText', {text:'@CAST-01 waits', lookup});
  assert.match(plain, /<span class="binding-tag"><span class="binding-thumb">/, 'with nowhere to open it, a tag is not a button');
  assert.doesNotMatch(plain, /<button/);
  assert.match(render('BindingText', {text:'@CAST-01:DAY waits', lookup}), /<span>Kael · day<\/span>/, 'a look the sheet does not name says which look it is');
  assert.equal(render('BindingText', {text:'', lookup}), '<span class="binding-text"></span>');
  assert.equal(render('BindingText', {text:'No codes here, only words.', lookup}), '<span class="binding-text">No codes here, only words.</span>');
});

const media = (kind, url) => ({kind, url});
const steps = [
  {key:'previs', stage:{column:4, label:'Previs'}, media:media('video', 'https://example.org/previs.mp4')},
  {key:'frame', stage:{column:2, label:'Keyframe'}, media:media('image', 'https://example.org/key.png')},
  {key:'video', stage:{column:3, label:'Cinema Shot'}, media:null},
];

test('the ladder shows previs, first frame and video with what exists; nothing plays by itself', () => {
  const html = render('MediaLadder', {steps, onOpen() {}, onPlan() {}});
  assert.match(html, /<ol aria-label="From previs to take">/);
  assert.equal((html.match(/<li class="is-(made|todo)">/g) || []).join(''), '<li class="is-made"><li class="is-made"><li class="is-todo">');
  assert.match(html, /<video src="https:\/\/example\.org\/previs\.mp4#t=0\.1" preload="metadata" muted="" playsInline="" tabindex="-1" aria-hidden="true"><\/video>|<video src="https:\/\/example\.org\/previs\.mp4#t=0\.1" preload="metadata" muted=""/);
  assert.doesNotMatch(html, /autoplay|controls|autoPlay/i, 'a video rung is a paused first frame');
  assert.match(html, /<img src="https:\/\/example\.org\/key\.png" alt="" loading="lazy"\/>/);
  assert.match(html, /title="Open the 3D stage"/);
  assert.equal((html.match(/title="Open in Review"/g) || []).length, 2);
  for (const text of ['Previs', 'First frame', 'Take']) assert.ok(html.includes(text), text);
  assert.match(html, /Take<small>not yet<\/small>/, 'an empty rung says it is not made yet');
  assert.doesNotMatch(html, /No previs yet/, 'the previs exists');
});

test('a shot with no previs yet is told so, with a quiet way to plan one; a sheet without the column has no rung and no note', () => {
  const html = render('MediaLadder', {steps:[{...steps[0], media:null}, steps[1]], onOpen() {}, onPlan() {}});
  assert.match(html, /<p class="ladder-note">No previs yet\.<button type="button" class="quiet">Plan previs<\/button><\/p>/);
  const plain = render('MediaLadder', {steps:steps.slice(1), onOpen() {}, onPlan() {}});
  assert.doesNotMatch(plain, /Previs|ladder-note/);
  assert.equal(render('MediaLadder', {steps:[], onOpen() {}}), '', 'nothing to climb, nothing drawn');
});

test('the script outline draws an @code in a beat as a tag only when it is given the asset sheet', () => {
  const view = {scenes:[{sceneId:'sc1', sceneIndex:1, title:'ARRIVAL', beats:[{index:0, text:'@CAST-01 turns the recorder.', line:3, rowId:'b1', shotId:'sh1', shotIndex:'S01', state:'built'}]}], orphans:[]};
  const plain = render('OutlineView', {view});
  assert.match(plain, /<span class="outline-text">@CAST-01 turns the recorder\.<\/span>/, 'as before without a lookup');
  const tagged = render('OutlineView', {view, lookup, onOpenAsset() {}});
  assert.match(tagged, /<span class="outline-text"><span class="binding-text"><button type="button" class="binding-tag"[^>]*><span class="binding-thumb"><img src="\/kael\.png"/);
  assert.match(tagged, /<span>Kael<\/span><\/button> turns the recorder\.<\/span><\/span>/);
});

test('the shot detail reads in Traditional Chinese', async () => {
  await components.setLocale('zh-TW');
  try {
    const cast = render('ShotBindings', castProps({elsewhere:{'PROP-01':['備註']}}));
    for (const text of ['出場', '加入', '缺參考圖', '補參考圖', '也出現在：備註', 'Kael 的造型']) assert.ok(cast.includes(text), text);
    assert.ok(render('BindingText', {text:'@CAST-09', lookup}).includes('找不到 @CAST-09'));
    const ladder = render('MediaLadder', {steps:[{...steps[0], media:null}, steps[1], steps[2]], onOpen() {}, onPlan() {}});
    for (const text of ['由預演到影片', '預演', '首幀', '影片', '尚無', '還沒有預演。', '先排預演']) assert.ok(ladder.includes(text), text);
  } finally {await components.setLocale('en');}
});
