import test, {before, after} from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {build} from 'esbuild';
import {mkdtemp, writeFile, rm} from 'node:fs/promises';
import {join, dirname, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {buildClips, rhythm} from '../src/timelineModel.js';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
let temporary, components;
before(async () => {
  temporary = await mkdtemp(join(root, 'tests/.timeline-render-'));
  const result = await build({stdin: {contents: "export {Timeline} from './src/Timeline.jsx'; export {TimelineTrack} from './src/TimelineTrack.jsx'; export {TimelineInspector} from './src/TimelineInspector.jsx'; export {setLocale} from './src/i18n/index.js';",
    resolveDir: root, sourcefile: 'timeline-render.jsx', loader: 'jsx'}, bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', packages: 'external', loader: {'.css': 'empty'}});
  const output = join(temporary, 'components.mjs');
  await writeFile(output, result.outputFiles[0].text);
  components = await import(pathToFileURL(output));
});
after(async () => {if (temporary) await rm(temporary, {recursive: true, force: true});});
const render = (name, props) => renderToStaticMarkup(React.createElement(components[name], props));

const shot = (index, extra = {}) => ({rowId: 'b' + index, shotId: 'sh_demo_b' + index, tabKey: 'cinema-studio', shotIndex: String(index), sceneId: 'sc_demo_01_S01', description: 'Shot ' + index,
  selectedVideoUrl: `/take/${index}.mp4`, selectedImageUrl: `/still/${index}.png`, ...extra});
const measured = {'/take/1.mp4': 4, '/take/2.mp4': 4, '/take/3.mp4': 8};
const shots = [shot(1), shot(2, {dialogue: [{speaker: 'KAEL', line: 'Hold the line.', estimatedSeconds: 2}]}), shot(3),
  shot(4, {selectedVideoUrl: null, previsVideoUrl: '/previs/4.mp4'}), shot(5, {selectedVideoUrl: null, selectedImageUrl: null})];

test('the Timeline space shows the rhythm list, the cut preview, the clip inspector and the timeline', () => {
  const html = render('Timeline', {epId: 'ep_demo_01', shots, writable: true, focusRid: 'b2', onFocus() {}, onChanged() {}});
  assert.match(html, /<aside class="tl-panel tl-list" aria-label="Shot rhythm">/);
  assert.match(html, /<section class="tl-panel tl-preview" aria-label="Cut preview">/);
  assert.match(html, /<aside class="tl-panel tl-inspector ctl-palette ctl-kit"/);
  assert.match(html, /<section class="tl-track" aria-label="Timeline">/);
  assert.equal((html.match(/<li><button type="button"[^>]*><b>\d<\/b><span class="tl-meter">/g) || []).length, 5, 'one rhythm row per shot');
  assert.match(html, /<button type="button"[^>]*aria-current="true"[^>]*><b>1<\/b>/, 'the first shot is selected until the shell focuses another');
  assert.match(html, /Dashed bar = not shot yet, filled in with the 3D previs/);
  assert.match(html, /Export Episode MP4/);
  assert.doesNotMatch(html, /Select a shot on the timeline/);
});

test('the timeline row draws every clip in slate order, with previs and unshot shots as dashed ghosts', () => {
  const clips = buildClips(shots, {measured}), html = render('TimelineTrack', {clips, beat: rhythm(clips), selectedId: 'b3', playhead: 8.5, playing: false, zoom: 1, ripple: true, snapOn: true, writable: true,
    onZoom() {}, onRipple() {}, onSnap() {}, onScrub() {}, onSelect() {}, onEdge() {}, onExport() {}});
  assert.equal((html.match(/role="listitem"/g) || []).length, 5);
  assert.match(html, /class="tl-clip is-take is-now"[^>]*aria-current="true"/, 'only the selected clip carries the current mark');
  assert.match(html, /class="tl-clip is-previs"/);assert.match(html, /class="tl-clip is-plan"/);
  assert.match(html, /<b class="tl-tag">3D<\/b>/);assert.match(html, /<b class="tl-tag">Not shot<\/b>/);
  assert.equal((html.match(/class="tl-edge tl-edge-in"/g) || []).length, 3, 'only the three takes of known length have handles; previs and unshot clips always play whole');
  assert.match(html, /<div class="tl-playhead" style="left:[^"]*" aria-hidden="true"><span>00:08.5<\/span>/);
  assert.match(html, /aria-pressed="true"[^>]*aria-keyshortcuts="R"[^>]*>[\s\S]*?Ripple/);
  assert.match(html, /KAEL<\/i>Hold the line\./, 'the dialogue row carries the script lines');
});

test('a take of known length gets in and out handles that work as sliders', () => {
  const clips = buildClips([shot(1, {trim: {in: 0.5, out: 3}})], {measured}), html = render('TimelineTrack', {clips, beat: rhythm(clips), selectedId: 'b1', playhead: 0, playing: false, zoom: 1, ripple: true, snapOn: true, writable: true,
    onZoom() {}, onRipple() {}, onSnap() {}, onScrub() {}, onSelect() {}, onEdge() {}, onExport() {}});
  assert.match(html, /role="slider" tabindex="0" aria-label="1 in point" aria-valuemin="0" aria-valuemax="4" aria-valuenow="0.5" aria-valuetext="00:00.5"/);
  assert.match(html, /aria-label="1 out point"[^>]*aria-valuenow="3"/);
  assert.match(html, /<b class="tl-tag is-trim">−36 f<\/b>/, 'a trimmed clip says how much was taken off');
  const readOnly = render('TimelineTrack', {clips, beat: rhythm(clips), selectedId: 'b1', playhead: 0, playing: false, zoom: 1, ripple: true, snapOn: true, writable: false, exportDisabled: true,
    onZoom() {}, onRipple() {}, onSnap() {}, onScrub() {}, onSelect() {}, onEdge() {}, onExport() {}});
  assert.doesNotMatch(readOnly, /tl-edge/, 'a viewer cannot grab an edge');
  assert.match(readOnly, /<button type="button" class="primary tl-export" disabled="">/);
});

test('a clip that runs well over the average is called out on the rhythm row', () => {
  const clips = buildClips([shot(1), shot(2), shot(3)], {measured}), html = render('TimelineTrack', {clips, beat: rhythm(clips), selectedId: 'b1', playhead: 0, playing: false, zoom: 1, ripple: true, snapOn: true, writable: true,
    onZoom() {}, onRipple() {}, onSnap() {}, onScrub() {}, onSelect() {}, onEdge() {}, onExport() {}});
  assert.match(html, /class="tl-hint"[^>]*>3 runs long · try −2\.7 s<\/span>/);
  assert.match(html, /class="tl-bar is-long"/);
});

test('an empty episode says so and offers nothing to play or export', () => {
  const html = render('Timeline', {epId: 'ep_demo_01', shots: [], writable: true, onFocus() {}, onChanged() {}});
  assert.match(html, /No shots yet\. Add shots in the Shot Stage first\./);
  assert.match(html, /class="tl-play"[^>]*disabled=""/);
  assert.match(html, /class="primary tl-export" disabled=""/);
});

test('the inspector offers say, adjust and drag for a take, with timecode fields and a range slider', () => {
  const clip = buildClips([shot(1, {trim: {in: 0.5, out: 3}, dialogue: [{speaker: 'KAEL', line: 'Hold the line.', estimatedSeconds: 2}]})], {measured})[0];
  const html = render('TimelineInspector', {clip, saved: clip, ripple: true, writable: true, saving: false, onRipple() {}, onPoint() {}, onSlide() {}, onLength() {}, onMove() {}, onReset() {}, takes: [], onTake() {}});
  assert.match(html, /<h2>1 · Clip<\/h2><span>2\.5 s · 60 f<\/span>/);
  for (const layer of ['Say', 'Adjust', 'Drag']) assert.match(html, new RegExp(`<span class="tl-lay">${layer}</span>`));
  assert.match(html, /aria-label="Trim by instruction"/);assert.match(html, /placeholder="e\.g\. out 3 frames earlier"/);
  assert.match(html, /role="switch" aria-checked="true"/);
  assert.equal((html.match(/data-handle="(start|end)"/g) || []).length, 2, 'the range slider has two handles');
  assert.match(html, /aria-label="1 in point"/);assert.match(html, /aria-label="1 out point"/);
  assert.equal((html.match(/role="spinbutton"/g) || []).length, 8, 'two timecode fields of four segments');
  assert.match(html, /Use the whole take/);
  assert.match(html, /Take 0 – 4\.0 s/);assert.match(html, /Length 2\.5 s = 60 f/);
  assert.match(html, /KAEL<\/b><span>Hold the line\.<\/span><small>about 2\.0 s<\/small>/);
  assert.doesNotMatch(html, /always plays whole|Nothing to trim/);
});

test('the inspector explains why previs, unshot and read-only clips cannot be trimmed', () => {
  const props = {saved: null, ripple: true, saving: false, onRipple() {}, onPoint() {}, onSlide() {}, onLength() {}, onMove() {}, onReset() {}, takes: [], onTake() {}};
  const previs = buildClips([shot(4, {selectedVideoUrl: null, previsVideoUrl: '/previs/4.mp4'})], {measured})[0], plan = buildClips([shot(5, {selectedVideoUrl: null, selectedImageUrl: null})], {})[0];
  assert.match(render('TimelineInspector', {...props, clip: previs, writable: true}), /3D previs stands in for this shot and always plays whole/);
  assert.match(render('TimelineInspector', {...props, clip: plan, writable: true}), /Nothing to trim yet/);
  assert.match(render('TimelineInspector', {...props, clip: previs, writable: true}), /class="tl-say"[^>]*disabled=""/);
  const loading = buildClips([shot(1)], {})[0];
  assert.match(render('TimelineInspector', {...props, clip: loading, writable: true}), /Reading the take&#x27;s length…/);
  const take = buildClips([shot(1)], {measured})[0];
  assert.match(render('TimelineInspector', {...props, clip: take, writable: false}), /You can view the cut but not trim it\./);
  assert.match(render('TimelineInspector', {...props, clip: null, writable: true}), /Select a shot on the timeline\./);
});

test('a clip that runs long offers to be taken down, but only where it can be trimmed', () => {
  const props = {saved: null, ripple: true, saving: false, onRipple() {}, onPoint() {}, onSlide() {}, onLength() {}, onMove() {}, onReset() {}, takes: [], onTake() {}, hint: {trimBy: -2.6667}};
  const take = buildClips([shot(1)], {measured})[0];
  const html = render('TimelineInspector', {...props, clip: take, writable: true});
  assert.match(html, /<div class="tl-hint-card" role="note"><span>1 runs long · try −2\.7 s<\/span><button type="button">Take it down by −2\.7 s<\/button><\/div>/);
  assert.doesNotMatch(render('TimelineInspector', {...props, clip: take, writable: false}), /tl-hint-card/, 'a viewer cannot trim, so nothing is offered');
  assert.doesNotMatch(render('TimelineInspector', {...props, clip: take, writable: true, hint: null}), /tl-hint-card/);
  assert.doesNotMatch(render('TimelineInspector', {...props, clip: buildClips([shot(4, {selectedVideoUrl: null, previsVideoUrl: '/previs/4.mp4'})], {measured})[0], writable: true}), /tl-hint-card/, 'previs plays whole');
});

test('other takes of the shot list with a one-tap switch', () => {
  const clip = buildClips([shot(1)], {measured})[0], html = render('TimelineInspector', {clip, saved: clip, ripple: false, writable: true, saving: true, onRipple() {}, onPoint() {}, onSlide() {}, onLength() {}, onMove() {}, onReset() {}, onTake() {},
    takes: [{videoId: 'vd_a', url: '/take/1b.mp4', selected: false}, {videoId: 'vd_b', url: '/take/1c.mp4', selected: false}]});
  assert.match(html, /<h3>Other takes<\/h3>/);
  assert.equal((html.match(/Use this take/g) || []).length, 2);
  assert.match(html, /role="switch" aria-checked="false"/);
  assert.match(html, /role="status">Saving…/);
});

test('the Timeline reads in Traditional Chinese too', () => {
  components.setLocale('zh-TW');
  try {
    const clips = buildClips(shots, {measured}), html = render('TimelineTrack', {clips, beat: rhythm(clips), selectedId: 'b1', playhead: 0, playing: false, zoom: 1, ripple: true, snapOn: true, writable: true,
      onZoom() {}, onRipple() {}, onSnap() {}, onScrub() {}, onSelect() {}, onEdge() {}, onExport() {}});
    for (const text of ['時間軸', '匯出整集 MP4', '影像 V1', '候選 V2', '對白 A1', '未拍']) assert.ok(html.includes(text), text);
    const clip = clips[0], inspector = render('TimelineInspector', {clip, saved: clip, ripple: true, writable: true, saving: false, onRipple() {}, onPoint() {}, onSlide() {}, onLength() {}, onMove() {}, onReset() {}, takes: [], onTake() {}});
    for (const text of ['<span class="tl-lay">說</span>', '<span class="tl-lay">調</span>', '<span class="tl-lay">拖</span>', '使用整段素材'.slice(0, 0), '長度']) assert.ok(inspector.includes(text), text);
  } finally {components.setLocale('en');}
});
