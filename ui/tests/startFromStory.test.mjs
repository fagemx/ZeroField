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
  temporary = await mkdtemp(join(root, 'tests/.start-render-'));
  const result = await build({stdin: {contents: "export {StartFromStory} from './src/StartFromStory.jsx'; export {setLocale} from './src/i18n/index.js';",
    resolveDir: root, sourcefile: 'start-render.jsx', loader: 'jsx'}, bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', packages: 'external', loader: {'.css': 'empty'}});
  const output = join(temporary, 'components.mjs');
  await writeFile(output, result.outputFiles[0].text);
  components = await import(pathToFileURL(output));
});
after(async () => {if (temporary) await rm(temporary, {recursive: true, force: true});});
const render = props => renderToStaticMarkup(React.createElement(components.StartFromStory, {onCancel() {}, onCreate() {}, ...props}));
const styles = [{stylePresetId:'88123', name:'Sci-Fi Noir', sampleImage:'/projects/assets/style-samples/sci-fi-noir.svg'}, {stylePresetId:'88124', name:'Cel-Shaded Anime'}];

test('the story start offers an idea, a novel chapter or a screenplay in one big box, a ratio and a style, and one primary action', () => {
  const html = render({preloaded:styles});
  assert.match(html, /<div class="start-modes" role="group" aria-label="What you are starting from"><button type="button" aria-pressed="true">Idea \/ Logline<\/button><button type="button" aria-pressed="false">Novel \/ Story Chapter<\/button><button type="button" aria-pressed="false">Screenplay<\/button><\/div>/);
  assert.match(html, /<textarea[^>]*class="start-text"[^>]*placeholder="One or two sentences is enough[^"]*"[^>]*><\/textarea>/);
  assert.match(html, /<label class="start-upload">.*?Load a \.txt or \.md file<input type="file" accept="\.txt,\.md,text\/plain,text\/markdown"\/><\/label>/);
  for (const [ratio, pressed] of [['16:9', 'true'], ['9:16', 'false'], ['1:1', 'false'], ['21:9', 'false']]) assert.match(html, new RegExp(`<button type="button" aria-pressed="${pressed}">${ratio}</button>`), ratio);
  assert.match(html, /<label class="is-on"><input type="radio" name="start-style" checked="" value="88123"\/><img src="\/projects\/assets\/style-samples\/sci-fi-noir\.svg" alt="" loading="lazy"\/><span>Sci-Fi Noir<\/span><\/label>/, 'the first style is chosen and shows its sample');
  assert.match(html, /<label><input type="radio" name="start-style" value="88124"\/><span class="start-nosample" aria-hidden="true"><\/span><span>Cel-Shaded Anime<\/span><\/label>/, 'a style without a sample falls back to its name');
  assert.match(html, /placeholder="Untitled story"/, 'the title is optional and says what it would be');
  assert.match(html, /<span class="start-hint">Write or paste something to start from\.<\/span>/);
  assert.match(html, /<button type="submit" class="primary" disabled="">Create and start<\/button>/, 'nothing to start from yet');
  assert.equal((html.match(/class="primary/g) || []).length, 1, 'one primary action');
  assert.match(html, /<button type="button">Cancel<\/button>/);
});

test('without styles there is no style choice; a busy form holds every control and says it is creating; an error is an alert', () => {
  assert.doesNotMatch(render({preloaded:[]}), /start-styles|start-style/);
  const busy = render({preloaded:styles, busy:true});
  assert.match(busy, /<button type="submit" class="primary" disabled="">Creating…<\/button>/);
  assert.match(busy, /<button type="button" disabled="">Cancel<\/button>/);
  assert.match(busy, /<button type="button" aria-pressed="true" disabled="">Idea \/ Logline<\/button>/);
  assert.match(busy, /<input type="file"[^>]*disabled=""/);
  assert.match(busy, /<textarea[^>]*disabled=""/);
  assert.match(render({preloaded:styles, error:'Slug already exists'}), /<p class="canvas-error" role="alert">Slug already exists<\/p>/);
  assert.doesNotMatch(render({preloaded:styles}), /canvas-error/);
});

test('the story start reads in Traditional Chinese', async () => {
  await components.setLocale('zh-TW');
  try {
    const html = render({preloaded:styles});
    for (const text of ['你要從什麼開始', '一兩句就夠：誰、想要什麼、什麼擋在前面。', '載入 .txt 或 .md 檔', '畫幅比例', '畫風', '名稱', '未命名故事', '先寫點或貼上內容才能開始。', '建立並開始']) assert.ok(html.includes(text), text);
  } finally {await components.setLocale('en');}
});
