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
import {ASSET_CREW_KINDS, CREW_KINDS, EPISODE_CREW_KINDS, SHOT_CREW_KINDS, assetProposals, crewActive, crewCancelPath, crewCandidates,
  crewJobLine, crewJobPath, crewJobsPath, crewRunningKey, latestCrewJobs, newlyProposed} from '../src/crewJobModel.js';
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

test('SPEC_20 R21-R23: every target kind asks on its own route, and the running line names who works', () => {
  assert.deepEqual(SHOT_CREW_KINDS, ['beats', 'camera', 'appearances']);
  assert.equal(crewJobPath('sh_demo_b1', 'appearances'), '/shots/sh_demo_b1/appearance-proposals');
  assert.equal(crewJobPath('as_demo_b2', 'description'), '/assets/as_demo_b2/description-proposals');
  assert.equal(crewJobPath('as_demo_b2', 'look'), '/assets/as_demo_b2/look-proposals');
  assert.equal(crewJobPath('sc_demo_01_S01', 'appearances'), '/scenes/sc_demo_01_S01/appearance-proposals');
  assert.equal(crewJobPath('ep_demo_01', 'adaptation'), '/episodes/ep_demo_01/adaptation-proposals');
  assert.equal(crewJobPath('ep_demo_01', 'breakdown'), '/episodes/ep_demo_01/breakdown-proposals');
  assert.equal(crewJobsPath('as_demo_b2'), '/assets/as_demo_b2/crew-jobs');
  assert.equal(crewJobsPath('ep_demo_01'), '/episodes/ep_demo_01/crew-jobs');
  assert.deepEqual(Object.keys(latestCrewJobs([job('look', 'running'), job('beats', 'failed')], ASSET_CREW_KINDS)), ['look'], 'only the kinds asked here');
  assert.equal(crewRunningKey({role: 'sheet_ops', kind: 'beats'}), 'crewRunning');
  assert.equal(crewRunningKey({role: 'doc_writer', kind: 'look'}), 'crewRunningArt');
  assert.equal(crewRunningKey({role: 'doc_writer', kind: 'breakdown'}), 'crewRunningWriter');
});

test('SPEC_20 R23: candidates are listed for the director to pick, and a rule-only result says so', () => {
  const model = {source: 'model', previewId: 'wpre_1', branchId: 'wbr_1', impact: {shotCount: 6, newShots: 1}};
  const rule = {source: 'rule', previewId: null, branchId: null, impact: {shotCount: 5, newShots: 0}};
  const done = job('breakdown', 'succeeded', {source: 'model', result: {candidates: [model, rule], proposalIds: []}});
  assert.deepEqual(crewJobLine(done), {key: 'crewCandidates'});
  assert.deepEqual(crewCandidates(done), [model, rule]);
  assert.deepEqual(crewJobLine(job('adaptation', 'succeeded', {source: 'rule_fallback', result: {candidates: [rule]}})), {key: 'crewCandidatesFallback'});
  assert.deepEqual(crewCandidates(job('adaptation', 'running')), []);
  assert.deepEqual(newlyProposed({breakdown: done}, new Set()), [], 'candidates need no proposal reload');
});

test('SPEC_20 R21: an asset card shows its own proposals and the looks proposed for it', () => {
  const review = rid => ({groups: [{index: 0, row_id: rid, changes: [{column: 'Locked Appearance Prompt / Seed', before: 'a', after: 'b'}]}], partial_allowed: false, version: 'v'});
  const own = {id: 1, action: 'table_edit', status: 'pending', target: {tab_key: 'soul-cast', crew: {kind: 'description', assetRowId: 'b1'}}, review: review('b1')};
  const look = {id: 2, action: 'table_edit', status: 'pending', target: {tab_key: 'soul-cast', crew: {kind: 'look', assetRowId: 'b1'}}, review: review('bnew')};
  const other = {id: 3, action: 'table_edit', status: 'pending', target: {tab_key: 'soul-cast', crew: {kind: 'look', assetRowId: 'b9'}}, review: review('bnew9')};
  const done = {...look, id: 4, status: 'applied'};
  assert.deepEqual(assetProposals([own, look, other, done], {rowId: 'b1', tabKey: 'soul-cast'}).map(entry => entry.proposal.id), [1, 2]);
  assert.deepEqual(assetProposals([own], {}), []);
});

test('a writer sees Art on an asset card and the Screenwriter on the episode', async () => {
  await components.setLocale('en');
  const card = render('CrewAsk', {slug: 'demo', targetId: 'as_demo_b1', kinds: ASSET_CREW_KINDS, noteKinds: ['look'], title: 'shotProposal.askArt',
    hint: 'shotProposal.askArtHint', writable: true});
  assert.match(card, /aria-label="Ask Art"/);
  assert.match(card, /<button type="button">Ask Art to fill the description<\/button>/);
  assert.match(card, /<button type="button">Propose a new look<\/button>/);
  assert.match(card, /placeholder="What the look is, for example: soaked rain coat for the night scene"/);
  const episode = render('CrewAsk', {slug: 'demo', targetId: 'ep_demo_01', kinds: EPISODE_CREW_KINDS, title: 'shotProposal.askWriter', hint: 'shotProposal.askWriterHint', writable: true});
  assert.match(episode, />Adapt my idea or novel<\/button>.*>Propose a shot breakdown<\/button>/s);
  assert.doesNotMatch(episode, /crew-ask-note/, 'no note field where no ask takes one');
  assert.match(render('CrewAsk', {slug: 'demo', shotId: 'sh_demo_b1', writable: true}), />Who is in this shot<\/button>/);
  await components.setLocale('zh-TW');
  assert.match(render('CrewAsk', {slug: 'demo', targetId: 'as_demo_b1', kinds: ASSET_CREW_KINDS, title: 'shotProposal.askArt', writable: true}), />請美術補描述<\/button>/);
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
