import test, {before, after} from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {build} from 'esbuild';
import {mkdtemp, writeFile, rm} from 'node:fs/promises';
import {join, dirname, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {defaultPlan} from '../src/previs/plan.js';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
let temporary, components;
before(async () => {
  temporary = await mkdtemp(join(root, 'tests/.stage-render-'));
  const result = await build({stdin: {contents: "export {BeatTrack} from './src/previs/BeatTrack.jsx'; export {CameraMove} from './src/previs/CameraMove.jsx'; export {PlanHandles} from './src/previs/PlanHandles.jsx'; export {default as PrevisStage} from './src/previs/PrevisStage.jsx'; export {setLocale} from './src/i18n/index.js';",
    resolveDir: root, sourcefile: 'stage-render.jsx', loader: 'jsx'}, bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', packages: 'external', loader: {'.css': 'empty'}});
  const output = join(temporary, 'components.mjs');
  await writeFile(output, result.outputFiles[0].text);
  components = await import(pathToFileURL(output));
});
after(async () => {if (temporary) await rm(temporary, {recursive: true, force: true});});
const render = (name, props) => renderToStaticMarkup(React.createElement(components[name], props));
const noop = () => {};
const skills = {...defaultPlan(), seconds: 8, use: [{skill: 'walkTo', args: {from: [0, -2.2], to: [0, 0]}}, {skill: 'reachGrip', args: {anchor: [0, 1, 0.4]}}]};

test('the beat track draws the camera keys and each acting beat on the shot\'s frames', () => {
  const html = render('BeatTrack', {plan: skills, frames: 193, frame: 48, writable: true, onEdit: noop, onSeek: noop});
  assert.match(html, /<section class="previs-beats" aria-label="Beats">/);
  assert.equal((html.match(/class="pb-key/g) || []).length, 3, 'the push-in preset has three keys');
  assert.match(html, /aria-label="Camera key K1" aria-valuemin="0" aria-valuemax="192" aria-valuenow="0" aria-valuetext="0\.00 s"/);
  assert.match(html, /aria-label="Camera key K3"[^>]*aria-valuenow="192" aria-valuetext="8\.00 s"/);
  assert.match(html, /class="pb-beat"[^>]*aria-label="Walk to"[^>]*aria-valuenow="0" aria-valuetext="0\.00 – 2\.17 s"/);
  assert.match(html, /aria-label="Reach and hold"[^>]*aria-valuenow="52"/);
  assert.equal((html.match(/class="pb-edge"/g) || []).length, 2, 'both beats can be stretched');
  assert.match(html, /<i class="pb-head" style="left:25%"/, 'the playhead is a quarter of the way along');
  assert.doesNotMatch(html, /role="spinbutton"/, 'timecodes only appear once something is picked');
});

test('Walk in shows its derived beat dashed, and a built-in action says its timing is fixed', () => {
  const walk = render('BeatTrack', {plan: {...defaultPlan(), action: 'walkin'}, frames: 97, frame: 0, writable: true, onEdit: noop, onSeek: noop});
  assert.match(walk, /class="pb-beat is-derived"[^>]*aria-label="Walk to"/);
  const fixed = render('BeatTrack', {plan: {...defaultPlan(), action: 'turnreach'}, frames: 97, frame: 0, writable: true, onEdit: noop, onSeek: noop});
  assert.match(fixed, /<p class="pb-note">This shot uses the built-in action “Turn &amp; reach”, whose timing is fixed\./);
  assert.doesNotMatch(fixed, /class="pb-beat/);assert.match(fixed, /class="pb-key/, 'the camera keys can still be retimed');
});

test('the camera move section offers a range slider, two timecodes and an easing curve', () => {
  const html = render('CameraMove', {plan: {...defaultPlan(), easing: [0.16, 1, 0.3, 1]}, frames: 97, frame: 24, writable: true, onEdit: noop});
  assert.match(html, /<details class="previs-move"><summary>Camera move<\/summary>/, 'folded until asked for');
  assert.equal((html.match(/data-handle="(start|end)"/g) || []).length, 2);
  assert.match(html, /aria-label="Move starts"/);assert.match(html, /aria-label="Move stops"/);
  assert.equal((html.match(/role="spinbutton"/g) || []).length >= 8, true, 'two timecode fields of four segments, and the curve\'s number fields');
  assert.match(html, /Strong ease out/);assert.match(html, /cubic-bezier\(0\.16, 1, 0\.3, 1\)/);
  const viewer = render('CameraMove', {plan: defaultPlan(), frames: 97, frame: 0, writable: false, onEdit: noop});
  assert.doesNotMatch(viewer, /ctl-ce-plot/, 'a viewer sees the numbers but not the editor');
});

test('the plan handles are an amber square for the actor and light handles for the camera keys', () => {
  const project = (x, z) => ({x: 100 - x * 10, y: 100 - z * 10}), plan = {...defaultPlan(), mark: [0.5, -1], cast: [{mark: [2, 0]}]};
  const html = render('PlanHandles', {plan, project, unproject: () => [0, 0], writable: true, onDummy: noop, onKey: noop});
  assert.match(html, /class="plan-handle is-dummy is-now"[^>]*aria-label="Move the actor&#x27;s mark"/);
  assert.match(html, /class="plan-handle is-dummy"[^>]*aria-label="Move cast member 1&#x27;s mark"/);
  assert.equal((html.match(/class="plan-handle is-key"/g) || []).length, 3);assert.match(html, /<span aria-hidden="true">K1<\/span>/);
  assert.match(html, /style="left:95px;top:110px"/, 'handles sit where the plan puts the mark');
  assert.match(render('PlanHandles', {plan, project, unproject: () => [0, 0], writable: false, onDummy: noop, onKey: noop}), /class="plan-handle is-now" style="[^"]*" disabled=""|disabled=""[^>]*aria-label="Move the actor/, 'a viewer sees them but cannot grab');
  assert.doesNotMatch(render('PlanHandles', {plan, project: () => null, unproject: () => null, writable: true, onDummy: noop, onKey: noop}), /class="plan-handle /, 'handles off the plan are not drawn');
});

test('the 3D Stage carries the beat track and the camera move in every view, and the handles only on the overhead plan', () => {
  const shot = {rid: 'a', r: 0, shot: 'S01', slate: {motion: 'Static Tripod', rig: '35mm', action: 'Kael waits'}, previs: null, keyframe: null, matteCol: -1, skeletonCol: -1, setAsset: null};
  const html = render('PrevisStage', {slug: 'demo', shots: [shot], writable: true, busy: false, onRender: async () => true});
  assert.match(html, /<section class="previs-beats"/);assert.match(html, /<details class="previs-move">/);
  assert.doesNotMatch(html, /plan-handle|plan-layer/, 'the lens view has no plan to drag on');
});

test('the drag and beat labels read in Traditional Chinese', () => {
  components.setLocale('zh-TW');
  try {
    const html = render('BeatTrack', {plan: skills, frames: 193, frame: 0, writable: true, onEdit: noop, onSeek: noop});
    for (const text of ['節拍', '運鏡', '表演', '走到', '伸手握住']) assert.ok(html.includes(text), text);
    assert.ok(render('CameraMove', {plan: defaultPlan(), frames: 97, frame: 0, writable: true, onEdit: noop}).includes('緩入緩出'));
  } finally {components.setLocale('en');}
});
