import test, {before, after} from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {build} from 'esbuild';
import {mkdtemp, writeFile, rm} from 'node:fs/promises';
import {join, dirname, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {appFor, estimateOf, fallbackOptions, humanSeconds, reasonKey, requestBody, slotControls, startingApp} from '../src/generation/generationModel.js';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
let temporary, components;
before(async () => {
  temporary = await mkdtemp(join(root, 'tests/.gen-render-'));
  const result = await build({stdin: {contents: "export {GenerationBar} from './src/generation/GenerationBar.jsx'; export {setLocale} from './src/i18n/index.js';",
    resolveDir: root, sourcefile: 'gen-render.jsx', loader: 'jsx'}, bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', packages: 'external', loader: {'.css': 'empty'}});
  const output = join(temporary, 'components.mjs');
  await writeFile(output, result.outputFiles[0].text);
  components = await import(pathToFileURL(output));
});
after(async () => {if (temporary) await rm(temporary, {recursive: true, force: true});});
const render = props => renderToStaticMarkup(React.createElement(components.GenerationBar, {id:'as_CAST-01', label:'Regenerate', onGenerate() {}, onCancel() {}, ...props}));

const flux = {appCode:'FLUX3_SOUL_CAST', name:'FLUX 3 Klein', tier:'open_weights', configured:true, reason:null, outputs:['REFERENCE'], slots:{aspectRatio:true, resolution:['1k', '2k']},
  slotParams:{aspectRatio:{key:'5.aspect_ratio', options:null}, resolution:{key:'5.resolution', options:['1k', '2k']}}, estimate:{seconds:41, samples:5}, quotable:false};
const router = {appCode:'NANO_ROUTER', name:'Nano Router', tier:'router', configured:true, reason:null, outputs:['REFERENCE'], slots:{}, estimate:null, quotable:true};
const cloud = {appCode:'CLOUD_IMG', name:'Cloud Image', tier:'closed', configured:false, reason:'blocked_by_policy', outputs:['REFERENCE'], slots:{}, estimate:null, quotable:false};
const options = (...apps) => ({apps, defaultAppCode:apps[0].appCode, style:{stylePresetId:'88123', name:'Sci-Fi Noir Anamorphic'}});
const ready = (...apps) => ({preloaded:{status:'ready', options:options(...apps)}});

test('the workflow starts on the one asked for, else the default, else the first that can run, and never on one that cannot', () => {
  const list = options(flux, router, cloud);
  assert.equal(startingApp(list, 'NANO_ROUTER').appCode, 'NANO_ROUTER');
  assert.equal(startingApp(list, 'CLOUD_IMG').appCode, 'FLUX3_SOUL_CAST', 'asked for one that cannot run: the default');
  assert.equal(startingApp(list, null).appCode, 'FLUX3_SOUL_CAST');
  assert.equal(startingApp({apps:[cloud, router], defaultAppCode:'CLOUD_IMG'}, null).appCode, 'NANO_ROUTER', 'the default cannot run: the first that can');
  assert.equal(startingApp({apps:[cloud], defaultAppCode:'CLOUD_IMG'}, null), null, 'nothing can run');
  assert.equal(startingApp(null, null), null);
  assert.equal(appFor(list, 'X'), null);
  assert.equal(fallbackOptions().apps[0].appCode, 'flux-soul-cast', 'when the list cannot be read, the workflow the page always used');
});

test('the time the bar may promise is only what the server measured, with its sample count; anything else is unknown, never 0', () => {
  assert.deepEqual(estimateOf(flux), {seconds:41, samples:5});
  assert.deepEqual(estimateOf({estimate:{seconds:40.6, samples:3}}), {seconds:41, samples:3});
  for (const bad of [null, undefined, {estimate:null}, {estimate:{seconds:0, samples:5}}, {estimate:{seconds:0.2, samples:5}}, {estimate:{seconds:30, samples:0}}, {estimate:{seconds:NaN, samples:5}}, {estimate:{seconds:'41', samples:5}}, {estimate:{}}]) {
    assert.equal(estimateOf(bad), null, JSON.stringify(bad));
  }
  assert.deepEqual(humanSeconds(41), {unit:'s', value:41});
  assert.deepEqual(humanSeconds(99), {unit:'s', value:99});
  assert.deepEqual(humanSeconds(100), {unit:'min', value:2}, 'a minute and a half is said in minutes, rounded');
  assert.deepEqual(humanSeconds(600), {unit:'min', value:10});
});

test('a card\'s slots become the controls shown, and what is sent is exactly what the controls show', () => {
  const controls = slotControls(flux, {}, '9:16');
  assert.deepEqual(controls.map(control => [control.key, control.kind, control.value]), [['aspectRatio', 'ratio', '9:16'], ['resolution', 'resolution', '1k']]);
  assert.deepEqual(controls[0].options, ['16:9', '9:16', '1:1', '21:9'], 'a free ratio input offers the usual ratios');
  assert.deepEqual(requestBody(flux, controls), {appCode:'FLUX3_SOUL_CAST', modelParams:{'5.aspect_ratio':'9:16', '5.resolution':'1k'}}, 'sent under the card\'s own input keys, with the values on screen');
  const picked = slotControls(flux, {resolution:'2k', aspectRatio:'1:1'}, '9:16');
  assert.deepEqual(requestBody(flux, picked).modelParams, {'5.aspect_ratio':'1:1', '5.resolution':'2k'}, 'a choice beats the episode default');
  assert.equal(slotControls(flux, {}, '4:3')[0].value, '16:9', 'an episode ratio the card cannot do is not offered');
  assert.deepEqual(slotControls(flux, {resolution:'8k'}, '')[1].value, '1k', 'a value the card does not list falls back to one it does');
  const listed = {...flux, slotParams:{...flux.slotParams, aspectRatio:{key:'5.aspect_ratio', options:['1:1', '16:9']}}};
  assert.deepEqual(slotControls(listed, {}, '9:16')[0].options, ['1:1', '16:9'], 'a ratio input that lists its values is limited to them');
  assert.equal(slotControls(listed, {}, '9:16')[0].value, '1:1');
  assert.deepEqual(requestBody(router, slotControls(router)), {appCode:'NANO_ROUTER'}, 'a card with no slots sends none');
  assert.deepEqual(slotControls({slots:{aspectRatio:true}}), [], 'a slot with no card input to set has no control');
  assert.deepEqual(slotControls({slots:{seed:true}, slotParams:{seed:{key:'9.seed', options:null}}}), [], 'free inputs other than the ratio are the card\'s business');
  assert.deepEqual(slotControls(null), []);
});

test('a card that cannot run says why, in a message key the page translates', () => {
  assert.equal(reasonKey('blocked_by_policy'), 'reason_blocked_by_policy');
  assert.equal(reasonKey('blocked_by_privacy'), 'reason_blocked_by_privacy');
  assert.equal(reasonKey('not_configured'), 'reason_not_configured');
  assert.equal(reasonKey('something_new'), 'reason_unavailable');
  assert.equal(reasonKey(null), 'reason_unavailable');
});

test('the bar shows the workflow, the controls, the style and the measured time, and the button is outlined', () => {
  const html = render({...ready(flux, router, cloud), ratio:'9:16', styleName:'Fallback'});
  assert.match(html, /<section class="gen-bar" aria-label="Generate">/);
  assert.match(html, /<label>Workflow<select>?[^>]*value="FLUX3_SOUL_CAST"|<label>Workflow<select/);
  assert.match(html, /<option value="FLUX3_SOUL_CAST" selected="">FLUX 3 Klein<\/option>/);
  assert.match(html, /<option value="CLOUD_IMG" disabled="">Cloud Image — blocked by this production&#x27;s policy<\/option>/, 'a card that cannot run stays listed, greyed out, with its reason');
  assert.match(html, /<label>Aspect ratio<select><option>16:9<\/option><option selected="">9:16<\/option><option>1:1<\/option>/, 'the episode\'s ratio is the one shown');
  assert.match(html, /<label>Resolution<select><option selected="">1k<\/option><option>2k<\/option>/);
  assert.match(html, /<p class="gen-style">Style: Sci-Fi Noir Anamorphic \(follows the episode\)<\/p>/, 'the server\'s style name wins over the page\'s');
  assert.match(html, /<div class="gen-cost" role="status"><span>About 41 s \(5 runs\)<\/span><\/div>/);
  assert.match(html, /<button type="button" class="world-act">Regenerate<\/button>/);
  assert.doesNotMatch(html, /class="primary/, 'the screen\'s one primary action is elsewhere');
});

test('no measured time says so, a Router card offers a quote labelled as no price lock, and neither shows 0', () => {
  const unknown = render(ready({...flux, estimate:null}));
  assert.match(unknown, /<span class="gen-unknown">Time unknown<\/span>/);
  assert.doesNotMatch(unknown, /About|0 s/);
  const few = render(ready({...flux, estimate:{seconds:0, samples:9}}));
  assert.match(few, /Time unknown/, 'a zero is no measurement');
  const quote = render({...ready(router), preloaded:{status:'ready', options:options(router)}});
  assert.match(quote, /<button type="button" class="world-tool">Get a quote<\/button>/);
  assert.doesNotMatch(quote, /About|Time unknown/, 'a Router card is priced by its quote, not by its history');
});

test('options that could not be read leave the default workflow, say so, and never stop the button', () => {
  const failed = render({preloaded:{status:'failed', options:fallbackOptions()}});
  assert.match(failed, /<p class="gen-error" role="status">Couldn&#x27;t load the options\. The default workflow is used\.<\/p>/);
  assert.match(failed, /<button type="button" class="world-act">Regenerate<\/button>/);
  const loading = render({});
  assert.doesNotMatch(loading, /gen-fields|gen-error/);
  assert.match(loading, /<button type="button" class="world-act">Regenerate<\/button>/, 'while the list loads the button is the one the page always had');
});

test('with nothing able to run the button is off and the list says why; a card in flight cannot be sent again but can be canceled', () => {
  const none = render(ready(cloud));
  assert.match(none, /<p class="gen-error" role="status">No workflow is ready to use\. The reasons are in the list\.<\/p>/);
  assert.match(none, /<button type="button" class="world-act" disabled="">Regenerate<\/button>/);
  const running = render({...ready(flux), generating:true, canCancel:true, label:'Generating'});
  assert.match(running, /<button type="button" class="world-act" disabled="">Generating<\/button>/);
  assert.match(running, /<button type="button" class="world-tool">Cancel generation<\/button>/);
  assert.match(running, /<select[^>]*disabled=""/, 'the workflow cannot change under a picture being made');
  assert.doesNotMatch(render({...ready(flux), generating:true, canCancel:false}), /Cancel generation/, 'no task yet, nothing to cancel');
  assert.match(render({...ready(flux), disabled:true}), /<button type="button" class="world-act" disabled="">Regenerate<\/button>/);
});

test('the bar reads in Traditional Chinese', async () => {
  await components.setLocale('zh-TW');
  try {
    const html = render({...ready(flux, cloud), label:'重新生成'});
    for (const text of ['工作流程', '比例', '解析度', '畫風：Sci-Fi Noir Anamorphic（跟隨本集）', '約 41 秒（5 次）', '被本製作的政策擋下']) assert.ok(html.includes(text), text);
    assert.ok(render(ready({...flux, estimate:null})).includes('時間未知'));
    assert.ok(render({...ready(router)}).includes('取得報價'));
  } finally {await components.setLocale('en');}
});
