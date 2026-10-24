import test, {before, after} from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {build} from 'esbuild';
import {mkdtemp, writeFile, rm} from 'node:fs/promises';
import {join, dirname, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
let temporary, components;
before(async () => {
  temporary = await mkdtemp(join(root, 'tests/.outline-render-'));
  const result = await build({stdin: {contents: "export {OutlineView, ScriptOutline} from './src/ScriptOutline.jsx'; export {StoryWorld} from './src/StoryWorld.jsx'; export {setLocale} from './src/i18n/index.js';",
    resolveDir: root, sourcefile: 'outline-render.jsx', loader: 'jsx'}, bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', packages: 'external', loader: {'.css': 'empty'}});
  const output = join(temporary, 'components.mjs');
  await writeFile(output, result.outputFiles[0].text);
  components = await import(pathToFileURL(output));
});
after(async () => {if (temporary) await rm(temporary, {recursive: true, force: true});});
const render = (name, props) => renderToStaticMarkup(React.createElement(components[name], props));

const beat = (index, text, line, shot, state) => ({index, text, line, shotId: shot ? 'sh_demo_b' + shot : null, shotIndex: shot ? 'S0' + shot : null, rowId: shot ? 'b' + shot : null, state});
const view = {scriptDirty: false, orphans: [{shotId: 'sh_demo_b9', shotIndex: 'T1', rowId: 'b9', sceneId: 'sc_demo_01_S02'}], scenes: [
  {sceneId: 'sc_demo_01_S01', sceneIndex: 1, title: 'ARRIVAL', beats: [beat(0, 'Kael enters the observatory.\nRain on the glass.', 3, 1, 'linked'), beat(1, 'A radio signal pulses.', 5, 2, 'changed')]},
  {sceneId: 'sc_demo_01_S02', sceneIndex: 2, title: 'SIGNAL', beats: [beat(0, 'Kael reaches for the dial.', 9, null, 'no_shot'), beat(1, 'x'.repeat(200), null, 3, 'linked')]}]};

test('every beat shows its line, its text and the shot built from it', () => {
  const html = render('OutlineView', {view, affected: [], focusRid: 'b2', onFocus() {}, onOpen() {}, onLine() {}});
  assert.match(html, /<h3><b class="num">01<\/b>ARRIVAL<\/h3>/);assert.match(html, /<h3><b class="num">02<\/b>SIGNAL<\/h3>/);
  assert.match(html, /<button type="button" class="outline-line" title="Find line 3 in the script">L3<\/button><span class="outline-text">Kael enters the observatory\.<\/span>/, 'the beat shows its first line');
  assert.match(html, /<button type="button" class="outline-chip" title="Look at shot S01">S01<\/button>/);
  assert.match(html, /aria-current="true" title="Look at shot S02">S02<\/button>/, 'the shot in focus carries the current mark');
  assert.match(html, /<em class="outline-none">No shot yet<\/em>/);
  assert.match(html, /<button type="button" class="outline-line" disabled="" title="This beat is not in the script text as written">—<\/button>/);
  assert.match(html, /<li class="is-changed"><button[^>]*>L5<\/button><span class="outline-text">A radio signal pulses\.<\/span>.*?<small>its prompt differs from this beat<\/small>/);
  assert.match(html, new RegExp('<span class="outline-text">' + 'x'.repeat(95) + '…</span>'), 'a long beat is clipped');
  assert.match(html, /T1 were not built from this script and stay as they are\./);
  assert.doesNotMatch(html, /out of step with the script|Checking what this edit touches/);
});

test('an edit lists the shots it would leave out of step and hatches their beats', () => {
  const html = render('OutlineView', {view, affected: ['sh_demo_b1', 'sh_demo_b3'], focusRid: null, onFocus() {}, onOpen() {}, onLine() {}});
  assert.match(html, /<p class="outline-note is-impact" role="status">Saving this version leaves shots out of step with the script: S01, S03\.<\/p>/);
  assert.match(html, /<li class="is-linked is-affected">.*?<small>would fall out of step<\/small>/);
  assert.equal((html.match(/is-affected/g) || []).length, 2);
  assert.match(render('OutlineView', {view, affected: [], checking: true}), /<p class="outline-note" role="status">Checking what this edit touches…<\/p>/);
  assert.match(render('OutlineView', {view: null}), /Reading how the script became shots…/);
  assert.match(render('OutlineView', {view: {scenes: [], orphans: []}, affected: []}), /<p class="outline-note" role="status">No scene headings found in this text, so there is nothing to match to shots yet\.<\/p>/);
});

test('the outline sits under the script and reads in Traditional Chinese', () => {
  const html = render('ScriptOutline', {epId: 'ep_demo_01', script: 'INT. DOME', saved: 'INT. DOME', version: 'x:3', focusRid: null, onFocus() {}, onOpen() {}, onLine() {}});
  assert.match(html, /<section class="space-block outline" aria-labelledby="world-outline"><h2 id="world-outline">Script and shots<\/h2>/);
  components.setLocale('zh-TW');
  try {
    const zh = render('OutlineView', {view, affected: ['sh_demo_b1'], focusRid: null});
    for (const text of ['儲存這個版本後，這些鏡頭會和劇本對不上：S01。', '還沒有鏡頭', '鏡頭的提示詞和這一段不一樣了']) assert.ok(zh.includes(text), text);
  } finally {components.setLocale('en');}
});

test('Story & World shows the outline in the script view once the episode has shots', () => {
  const ep = {scriptContent: 'INT. DOME\nKael enters.', confirmedHash: 'h', scenes: [{sceneId: 'sc_1', sceneIndex: 1, title: 'DOME'}], settings: {}};
  const shots = [{rowId: 'b1', shotId: 'sh_demo_b1', sceneId: 'sc_1', shotIndex: 'S01', tabKey: 'cinema-studio'}];
  const props = {epId: 'ep_demo_01', ep, writable: true, focus: {}, onFocus() {}, onChanged() {}, onStage() {}, onOpenShot() {}, onAssets() {}, onVault() {}};
  assert.match(render('StoryWorld', {...props, shots}), /id="world-outline"/);
  assert.doesNotMatch(render('StoryWorld', {...props, shots: []}), /world-outline/, 'no shots, nothing to map the script to');
});
