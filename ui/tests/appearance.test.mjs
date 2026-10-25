import test, {before, after} from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {build} from 'esbuild';
import {mkdtemp, writeFile, rm} from 'node:fs/promises';
import {join, dirname, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {CHOICES, GROUPS, composeAppearance, emptySelection, hasSelection, mergeAppearance, needsChoice} from '../src/appearanceModel.js';
import {quickActions} from '../src/assistant/quickActions.js';
import {setLocale} from '../src/i18n/index.js';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
let temporary, components;
before(async () => {
  temporary = await mkdtemp(join(root, 'tests/.appearance-render-'));
  const result = await build({stdin: {contents: "export {AppearanceForm} from './src/AppearanceForm.jsx'; export {setLocale} from './src/i18n/index.js';", resolveDir: root, sourcefile: 'appearance-render.jsx', loader: 'jsx'},
    bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', packages: 'external', loader: {'.css': 'empty'}});
  const output = join(temporary, 'components.mjs');
  await writeFile(output, result.outputFiles[0].text);
  components = await import(pathToFileURL(output));
});
after(async () => {if (temporary) await rm(temporary, {recursive: true, force: true});});
const render = props => renderToStaticMarkup(React.createElement(components.AppearanceForm, {current:'', disabled:false, onApply() {}, ...props}));

const kael = {gender:'male', age:'middle', region:'nordic', skin:'tan', face:'square', hairStyle:'short', hairColor:'dark_brown', height:'tall', build:'lean',
  top:'a dark jacket', bottom:'work trousers', shoes:'worn boots', accessory:'a scarf'};

test('the same picks always compose the same description, in the same order: who, skin, face, hair, body, clothes', () => {
  const text = composeAppearance(kael);
  assert.equal(text, 'middle-aged man of Nordic descent, tan skin, square face, short dark brown hair, tall, lean build, wearing a dark jacket, work trousers, worn boots, a scarf.');
  assert.equal(composeAppearance(kael), text);
  assert.equal(composeAppearance({...kael}), text);
  assert.equal(composeAppearance(Object.fromEntries(Object.entries(kael).reverse())), text, 'the order of the picks does not change the order of the words');
});

test('partial picks compose what was picked and nothing else; nothing picked composes nothing', () => {
  assert.equal(composeAppearance({}), '');
  assert.equal(composeAppearance(emptySelection()), '');
  assert.equal(composeAppearance({gender:'female'}), 'woman.');
  assert.equal(composeAppearance({age:'elder'}), 'elderly person.');
  assert.equal(composeAppearance({age:'child', gender:'male'}), 'boy.');
  assert.equal(composeAppearance({age:'child', gender:'female', region:'east_asian'}), 'girl of East Asian descent.');
  assert.equal(composeAppearance({age:'child'}), 'child.');
  assert.equal(composeAppearance({region:'african'}), 'person of African descent.');
  assert.equal(composeAppearance({hairStyle:'bald', hairColor:'black'}), 'bald.', 'no hair colour for a shaved head');
  assert.equal(composeAppearance({hairStyle:'ponytail', hairColor:'red'}), 'red hair in a ponytail.');
  assert.equal(composeAppearance({hairColor:'gray'}), 'gray hair.');
  assert.equal(composeAppearance({hairStyle:'long'}), 'long hair.');
  assert.equal(composeAppearance({height:'average', build:'sturdy'}), 'average height, sturdy build.');
  assert.equal(composeAppearance({top:'  a red coat  ', shoes:''}), 'wearing a red coat.', 'clothes are the user\'s own words, trimmed');
  assert.equal(composeAppearance({unknown:'x', skin:'fair'}), 'fair skin.', 'unknown keys are ignored');
});

test('every option the form offers has words in the description, and every group is accounted for', () => {
  for (const [field, options] of Object.entries(CHOICES)) {
    for (const option of options) assert.notEqual(composeAppearance({[field]: option}), '', `${field}=${option}`);
  }
  assert.deepEqual(GROUPS.map(group => group.key), ['basic', 'face', 'body', 'outfit']);
  assert.deepEqual(GROUPS.flatMap(group => group.fields).sort(), Object.keys(emptySelection()).sort(), 'every pick belongs to exactly one group');
  assert.equal(hasSelection({}), false);
  assert.equal(hasSelection({top:'  '}), false);
  assert.equal(hasSelection({skin:'tan'}), true);
});

test('existing appearance text is never overwritten unasked: with text there the choice is the writer\'s, with none it just applies', () => {
  const composed = composeAppearance({gender:'male', age:'middle'});
  assert.equal(needsChoice('', composed), false);
  assert.equal(needsChoice('   ', composed), false, 'blank is empty');
  assert.equal(needsChoice('A tired keeper.', composed), true);
  assert.equal(needsChoice(composed, composed), false, 'the same text is nothing to ask about');
  assert.equal(needsChoice('A tired keeper.', ''), false, 'nothing picked, nothing to apply');
  assert.equal(mergeAppearance('A tired keeper.', composed, 'replace'), composed);
  assert.equal(mergeAppearance('A tired keeper.', composed, 'append'), 'A tired keeper. middle-aged man.');
  assert.equal(mergeAppearance('A tired keeper', composed, 'append'), 'A tired keeper. middle-aged man.', 'a sentence without its stop gets one');
  assert.equal(mergeAppearance('', composed, 'append'), composed);
  assert.equal(mergeAppearance('他很累。', composed, 'append'), '他很累。 middle-aged man.');
});

test('the form groups the picks, shows the words as they build up, and nothing is pressed or applied until you choose', () => {
  const html = render({});
  for (const text of ['Basics', 'Face and hair', 'Body', 'Outfit', 'Gender expression', 'Age', 'Region or culture', 'Skin tone', 'Face shape', 'Hair style', 'Hair colour', 'Height', 'Build', 'Top', 'Bottom', 'Shoes', 'Accessories']) assert.ok(html.includes(text), text);
  assert.match(html, /Nothing changes until you apply\./);
  assert.equal((html.match(/aria-pressed="false"/g) || []).length, Object.values(CHOICES).flat().length, 'one toggle per option, none pressed');
  assert.doesNotMatch(html, /aria-pressed="true"/);
  assert.match(html, /<button type="button" class="attr-swatch" aria-pressed="false" aria-label="Tan" title="Tan" style="background:#A06A44"><\/button>/);
  assert.match(html, /<button type="button" class="world-act" disabled="">Apply to appearance<\/button>/, 'nothing picked: nothing to apply');
  assert.doesNotMatch(html, /attr-preview|attr-ask/);
  assert.match(render({disabled:true}), /class="attr-chip" aria-pressed="false" disabled=""/);
});

test('the quick actions follow where you are and what you hold, and say so in the request', async () => {
  await setLocale('en');
  const scene = {index:'02', title:'Signal'}, asset = {code:'CAST-01', name:'Kael'}, shot = {index:'S03'};
  const script = quickActions({space:'story', view:'script', scene});
  assert.deepEqual(script.map(item => item.id), ['polish', 'structure', 'dialogue']);
  assert.equal(script[0].label, 'Polish scene 02');
  assert.match(script[0].text, /scene 02 “Signal”/);
  assert.equal(script[2].label, 'Make scene 02\'s dialogue more spoken');
  assert.deepEqual(quickActions({space:'story', view:'script'}).map(item => item.id), ['structure', 'dialogue'], 'no scene in focus: only what needs none');
  assert.equal(quickActions({space:'story', view:'script'})[1].label, 'Make the dialogue more spoken');
  const wall = quickActions({space:'story', view:'world', asset});
  assert.deepEqual(wall.map(item => item.id), ['attributes', 'looks']);
  assert.equal(wall[0].label, 'Fill in Kael\'s appearance');
  assert.match(wall[0].text, /Kael \(@CAST-01\)/);
  assert.deepEqual(quickActions({space:'story', view:'world'}), [], 'no card in front of you: nothing to hold');
  assert.equal(quickActions({space:'story', view:'world', asset:{code:'PROP-01'}})[1].label, 'Suggest two looks for PROP-01', 'no name yet: the code');
  const stage = quickActions({space:'stage', shot});
  assert.deepEqual(stage.map(item => item.label), ['Make S03\'s camera more specific', 'Check S03 against its neighbours']);
  assert.match(stage[0].text, /shot S03/);
  assert.deepEqual(quickActions({space:'stage'}), [], 'no shot, no shot actions: the general suggestions stay');
  assert.deepEqual(quickActions({space:'timeline', shot}), []);
  assert.deepEqual(quickActions(), []);
  await setLocale('zh-TW');
  try {
    assert.equal(quickActions({space:'story', view:'script', scene})[0].label, '潤飾第 02 場');
    assert.equal(quickActions({space:'stage', shot})[1].label, '檢查 S03 與前後鏡的連戲');
    assert.match(quickActions({space:'story', view:'world', asset})[0].text, /補齊 Kael（@CAST-01）的外觀/);
  } finally {await setLocale('en');}
});

test('the attribute form reads in Traditional Chinese', async () => {
  await components.setLocale('zh-TW');
  try {
    const html = render({});
    for (const text of ['基礎', '臉與髮', '體型', '服裝', '性別表達', '年齡段', '地區／文化背景', '膚色', '套用到外觀', '選好之後按「套用到外觀」才會改文字。', '中年', '北歐']) assert.ok(html.includes(text), text);
  } finally {await components.setLocale('en');}
});
