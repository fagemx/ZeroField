import test, {before, after} from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {build} from 'esbuild';
import {mkdtemp, writeFile, rm} from 'node:fs/promises';
import {join, dirname, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {rowProposals} from '../src/proposalModel.js';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
let temporary, components;
before(async () => {
  temporary = await mkdtemp(join(root, 'tests/.proposal-render-'));
  const result = await build({stdin: {contents: "export {ShotProposals} from './src/ShotProposals.jsx'; export {default as PrevisStage} from './src/previs/PrevisStage.jsx'; export {setLocale} from './src/i18n/index.js';",
    resolveDir: root, sourcefile: 'proposal-render.jsx', loader: 'jsx'}, bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', packages: 'external', loader: {'.css': 'empty'}});
  const output = join(temporary, 'components.mjs');
  await writeFile(output, result.outputFiles[0].text);
  components = await import(pathToFileURL(output));
});
after(async () => {if (temporary) await rm(temporary, {recursive: true, force: true});});
const render = (name, props) => renderToStaticMarkup(React.createElement(components[name], props));

const group = (index, rid, changes) => ({index, row_id: rid, row_number: index + 1, label: 'Row', changes});
const camera = {column: 'Camera Motion', before: 'Static Tripod', after: 'Slow Dolly In'};
const proposal = (id, groups, partial = true) => ({id, action: 'table_edit', status: 'pending', target: {tab_key: 'cinema-studio'}, review: {groups, partial_allowed: partial, version: 'v' + id}});

test('a shot shows its crew proposal with the old text struck through and the new text beside it', () => {
  const items = rowProposals([proposal(1, [group(0, 'b1', [camera, {column: 'Prompt', before: '', after: 'Hold the frame.'}])])], 'b1', 'cinema-studio');
  const html = render('ShotProposals', {items, writable: true, onApply() {}, onDismiss() {}, onShow() {}});
  assert.match(html, /<section class="shot-proposals" aria-label="Crew proposal">/);
  assert.match(html, /<dt>Camera Motion<\/dt><dd><del>Static Tripod<\/del><ins>Slow Dolly In<\/ins><\/dd>/);
  assert.match(html, /<del>\(empty\)<\/del><ins>Hold the frame\.<\/ins>/, 'an empty old value reads as empty');
  assert.match(html, /<button type="button" class="apply">Apply<\/button><button type="button">Reject<\/button><button type="button" class="quiet">Show this camera in the 3D Stage<\/button>/);
  assert.equal(render('ShotProposals', {items: [], writable: true}), '', 'nothing pending, nothing shown');
});

test('a proposal that only applies together says so and applies all of it', () => {
  const items = rowProposals([proposal(2, [group(0, 'b1', [{column: 'Prompt', before: 'a', after: 'b'}]), group(1, 'b2', [{column: 'Prompt', before: 'c', after: 'd'}])], false)], 'b1', 'cinema-studio');
  const html = render('ShotProposals', {items, writable: true, onApply() {}, onDismiss() {}});
  assert.match(html, /One proposal across 2 rows\. It only applies together\./);
  assert.match(html, />Apply all changes \(2\)<\/button>/);
  assert.doesNotMatch(html, /Show this camera/, 'no camera in it, and no way to show one without a stage');
  const part = rowProposals([proposal(3, [group(0, 'b1', [camera]), group(1, 'b2', [camera])])], 'b1', 'cinema-studio');
  assert.match(render('ShotProposals', {items: part, writable: true, onApply() {}, onDismiss() {}}), /Part of one proposal that edits 2 rows\. Rejecting drops all of them\./);
});

test('a viewer sees the proposal but cannot decide it, and an error stays on the card', () => {
  const items = rowProposals([{...proposal(4, [group(0, 'b1', [camera])]), error: 'The row changed since this was proposed.'}], 'b1', 'cinema-studio');
  const html = render('ShotProposals', {items, writable: false, onApply() {}, onDismiss() {}});
  assert.match(html, /<button type="button" class="apply" disabled="">Apply<\/button><button type="button" disabled="">Reject<\/button>/);
  assert.match(html, /role="alert">The row changed since this was proposed\./);
});

test('the 3D Stage offers the proposed camera next to the shot, only when there is one', () => {
  const shot = {rid: 'b1', r: 0, shot: 'S01', slate: {motion: 'Static Tripod', rig: '35mm', action: 'Kael waits'}, previs: null, keyframe: null, matteCol: -1, skeletonCol: -1, setAsset: null};
  const base = {slug: 'demo', tabKey: 'cinema-studio', shots: [shot], writable: true, busy: false, onRender: async () => true, onApplyProposal() {}, onDismissProposal() {}};
  const plain = render('PrevisStage', {...base, proposals: []});
  assert.doesNotMatch(plain, /previs-proposal|Look through the proposed camera/);
  const html = render('PrevisStage', {...base, proposals: [proposal(5, [group(0, 'b1', [camera])])]});
  assert.match(html, /<section class="previs-proposal" aria-label="Crew proposal"><h3>Crew proposal<\/h3><p class="previs-note">S01 has a proposed camera, dashed on the plan\.<\/p>/);
  assert.match(html, /aria-pressed="false">Look through the proposed camera<\/button><button type="button" class="apply">Apply<\/button><button type="button">Reject<\/button>/);
  const other = render('PrevisStage', {...base, proposals: [proposal(6, [group(0, 'b9', [camera])])]});
  assert.doesNotMatch(other, /previs-proposal/, 'a proposal for another shot is not this shot\'s');
  const same = render('PrevisStage', {...base, proposals: [proposal(7, [group(0, 'b1', [{column: 'Camera Motion', before: 'x', after: 'Static Tripod'}])])]});
  assert.doesNotMatch(same, /previs-proposal/, 'a camera proposal that changes nothing has no ghost');
  const viewer = render('PrevisStage', {...base, writable: false, proposals: [proposal(5, [group(0, 'b1', [camera])])]});
  assert.match(viewer, /Look through the proposed camera/);assert.doesNotMatch(viewer, /class="apply"/);
});

test('the proposal reads in Traditional Chinese', () => {
  components.setLocale('zh-TW');
  try {
    const items = rowProposals([proposal(8, [group(0, 'b1', [camera])])], 'b1', 'cinema-studio');
    const html = render('ShotProposals', {items, writable: true, onApply() {}, onDismiss() {}, onShow() {}});
    for (const text of ['劇組提案', '套用', '拒絕', '在 3D 片場看這個機位']) assert.ok(html.includes(text), text);
  } finally {components.setLocale('en');}
});
