// SPEC_20 R7, R19, R20: asking the crew for a shot's beat sheet or camera, the job's state line, its cancel from the crew
// board, and the rule-fallback mark on the proposal it leaves on the shot.
import test, {before, after} from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {build} from 'esbuild';
import {mkdtemp, writeFile, rm} from 'node:fs/promises';
import {join, dirname, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {CREW_KINDS, crewActive, crewCancelPath, crewJobLine, crewJobPath, crewJobsPath, latestCrewJobs, newlyProposed} from '../src/crewJobModel.js';
import {cancellationRequest} from '../src/assistant/orchestrationModel.js';
import {rowProposals} from '../src/proposalModel.js';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
let temporary, components;
before(async () => {
  temporary = await mkdtemp(join(root, 'tests/.crew-render-'));
  const result = await build({stdin: {contents: "export {CrewAsk} from './src/CrewAsk.jsx'; export {ShotProposals} from './src/ShotProposals.jsx'; export {setLocale} from './src/i18n/index.js';",
    resolveDir: root, sourcefile: 'crew-render.jsx', loader: 'jsx'}, bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', packages: 'external', loader: {'.css': 'empty'}});
  const output = join(temporary, 'components.mjs');
  await writeFile(output, result.outputFiles[0].text);
  components = await import(pathToFileURL(output));
});
after(async () => {if (temporary) await rm(temporary, {recursive: true, force: true});});
const render = (name, props) => renderToStaticMarkup(React.createElement(components[name], props));

const job = (kind, status, extra = {}) => ({jobId: `cj_${kind}_${status}`, kind, status, ...extra});

test('the ask goes to the shot route of its kind and cancels through the crew board route', () => {
  assert.deepEqual(CREW_KINDS, ['beats', 'camera']);
  assert.equal(crewJobPath('sh_demo_b1', 'beats'), '/shots/sh_demo_b1/beat-proposals');
  assert.equal(crewJobPath('sh_demo_b1', 'camera'), '/shots/sh_demo_b1/camera-proposals');
  assert.equal(crewJobsPath('sh_demo_b1'), '/shots/sh_demo_b1/crew-jobs');
  assert.equal(crewCancelPath('demo', {jobId: 'cj_1'}), '/projects/api/demo/orchestration/crew-jobs/cj_1/cancel');
  const board = cancellationRequest('/projects/api/demo/orchestration', 'demo', {kind: 'crew_job', job_id: 'cj_1', agent_key: 'sheet_ops'});
  assert.deepEqual(board, {path: '/projects/api/demo/orchestration/crew-jobs/cj_1/cancel', body: {}});
});

test('the newest job of each kind is the current one, and its state line says what happened', () => {
  const listed = [job('camera', 'running'), job('beats', 'succeeded', {source: 'rule_fallback', result: {proposalIds: [7]}}), job('beats', 'failed')];
  const latest = latestCrewJobs(listed);
  assert.deepEqual(Object.keys(latest).sort(), ['beats', 'camera']);
  assert.equal(latest.beats.status, 'succeeded', 'the list is newest first');
  assert.ok(crewActive(latest.camera) && !crewActive(latest.beats));
  assert.deepEqual(crewJobLine(latest.beats), {key: 'crewFallback'});
  assert.deepEqual(crewJobLine(job('beats', 'succeeded', {source: 'model', result: {proposalIds: [3]}})), {key: 'crewProposed'});
  assert.deepEqual(crewJobLine(job('camera', 'succeeded', {source: 'model', result: {unchanged: true, proposalIds: []}})), {key: 'crewUnchanged'});
  assert.deepEqual(crewJobLine(job('beats', 'failed', {failure: 'local', error: 'down'})), {key: 'crewFailed', failure: 'local', error: 'down'});
  assert.deepEqual(crewJobLine(job('beats', 'queued')), {key: 'crewQueued'});
  assert.equal(crewJobLine(undefined), null);
  const seen = new Set(['cj_beats_succeeded']);
  assert.deepEqual(newlyProposed(latest, seen), [], 'a proposal already seen does not reload twice');
  assert.equal(newlyProposed({beats: job('beats', 'succeeded', {result: {proposalIds: [9]}})}, new Set()).length, 1);
});

test('a writer sees two asks in the shot detail; a viewer sees none', async () => {
  await components.setLocale('en');
  const html = render('CrewAsk', {slug: 'demo', shotId: 'sh_demo_b1', writable: true, disabled: false, onProposed() {}});
  assert.match(html, /<section class="crew-ask" aria-label="Ask the crew">/);
  assert.match(html, /<button type="button">Write the beat sheet<\/button>/);
  assert.match(html, /<button type="button">Choose the camera<\/button>/);
  assert.match(html, /nothing changes until you apply it/);
  assert.equal(render('CrewAsk', {slug: 'demo', shotId: 'sh_demo_b1', writable: false}), '');
  await components.setLocale('zh-TW');
  assert.match(render('CrewAsk', {slug: 'demo', shotId: 'sh_demo_b1', writable: true}), />寫分拍<\/button>.*>選鏡頭與運鏡<\/button>/s);
  await components.setLocale('en');
});

test('a rule-fallback proposal says so on the shot', () => {
  const proposal = {id: 5, action: 'table_edit', status: 'pending', target: {tab_key: 'cinema-studio', crew: {source: 'rule_fallback', kind: 'beats'}},
    review: {groups: [{index: 0, row_id: 'b1', changes: [{column: 'Action & Audio Prompt', before: 'Kael reaches.', after: 'One continuous 4-second shot.'}]}], partial_allowed: false, version: 'v5'}};
  const html = render('ShotProposals', {items: rowProposals([proposal], 'b1', 'cinema-studio'), writable: true, onApply() {}, onDismiss() {}});
  assert.match(html, /<small class="shot-proposal-note">Rule fallback, not model-written/);
  const model = {...proposal, id: 6, target: {...proposal.target, crew: {source: 'model'}}};
  assert.doesNotMatch(render('ShotProposals', {items: rowProposals([model], 'b1', 'cinema-studio'), writable: true, onApply() {}, onDismiss() {}}), /shot-proposal-note/);
});
