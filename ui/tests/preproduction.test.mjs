// SPEC_20 R24, R25: the crew's pre-production panel (stages, the director's locks, the current work, the stop reason,
// cancel), the "Let the crew pre-produce" card after the storyboard is built, and the Continuity Supervisor's ask.
import test, {before, after} from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {build} from 'esbuild';
import {mkdtemp, writeFile, rm} from 'node:fs/promises';
import {join, dirname, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {ACTIVE_FLOW, PREPRODUCTION_LOCKS, PREPRODUCTION_STAGES, STAGE_GATE, cardDismissed, dismissCard, flowActive, flowCancelPath,
  flowLine, lockSummary, pollDelay, preproductionPath, showPreproductionCard, stageRows} from '../src/preproductionModel.js';
import {ALL_CREW_KINDS, CONTINUITY_KINDS, GENERATION_DESK_CREW, crewFindings, crewJobLine, crewJobPath, crewRunningKey} from '../src/crewJobModel.js';
import {cancellationRequest} from '../src/assistant/orchestrationModel.js';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
let temporary, components;
before(async () => {
  temporary = await mkdtemp(join(root, 'tests/.preproduction-render-'));
  const result = await build({stdin: {contents: "export {PreproductionPanel} from './src/PreproductionPanel.jsx'; export {CrewAsk} from './src/CrewAsk.jsx'; export {setLocale} from './src/i18n/index.js';",
    resolveDir: root, sourcefile: 'preproduction-render.jsx', loader: 'jsx'}, bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', packages: 'external', loader: {'.css': 'empty'}});
  const output = join(temporary, 'components.mjs');
  await writeFile(output, result.outputFiles[0].text);
  components = await import(pathToFileURL(output));
});
after(async () => {if (temporary) await rm(temporary, {recursive: true, force: true});});
const render = props => renderToStaticMarkup(React.createElement(components.PreproductionPanel, {slug: 'demo', epId: 'ep_demo_01', ...props}));

const counts = (extra = {}) => ({queued: 0, running: 0, succeeded: 0, failed: 0, canceled: 0, total: 0, fallback: 0, proposals: 0, skipped: 0, ...extra});
const stage = (key, status, extra = {}) => ({key, status, gate: STAGE_GATE[key] || null, counts: counts(), jobs: [], skipped: [], ...extra});
const flow = (status, extra = {}) => ({flowId: 'cf_1', episodeId: 'ep_demo_01', status, waitingFor: null, blocked: null, stop: null, canCancel: true,
  current: 'screenwriter', locks: {script: null, list: null, storyboard: null},
  stages: [stage('screenwriter', 'running', {counts: counts({total: 2, running: 1, succeeded: 1}),
    jobs: [{jobId: 'cj_1', kind: 'breakdown', status: 'running', targetLabel: 'Episode 1'}]}),
  stage('art', 'pending'), stage('cinematographer', 'pending'), stage('continuity', 'pending')], ...extra});
const waiting = (extra = {}) => ({episodeId: 'ep_demo_01', canStart: false, canLock: true,
  flow: flow('waiting', {waitingFor: 'script', current: 'art', stages: [stage('screenwriter', 'done', {counts: counts({total: 1, succeeded: 1, proposals: 0})}),
    stage('art', 'pending'), stage('cinematographer', 'pending'), stage('continuity', 'pending')]}),
  next: {lock: 'script', hash: 'sha256:abc', stage: 'art', problem: null, pendingProposals: 2,
    summary: {scenes: 2, chars: 340, items: ['Scene 01: Observatory', 'Scene 02: Departure']}}, ...extra});

test('the flow is four stages behind three locks, and its actions go to the episode and the crew board', () => {
  assert.deepEqual(PREPRODUCTION_STAGES, ['screenwriter', 'art', 'cinematographer', 'continuity']);
  assert.deepEqual(PREPRODUCTION_LOCKS, ['script', 'list', 'storyboard']);
  assert.deepEqual(STAGE_GATE, {art: 'script', cinematographer: 'list', continuity: 'storyboard'});
  assert.deepEqual(ACTIVE_FLOW, ['running', 'waiting', 'blocked']);
  assert.equal(preproductionPath('ep_demo_01'), '/episodes/ep_demo_01/preproduction');
  assert.equal(preproductionPath('ep_demo_01', 'locks'), '/episodes/ep_demo_01/preproduction/locks');
  assert.equal(flowCancelPath('demo', {flowId: 'cf_1'}), '/projects/api/demo/orchestration/crew-flows/cf_1/cancel');
  assert.deepEqual(cancellationRequest('/projects/api/demo/orchestration', 'demo', {kind: 'crew_flow', flow_id: 'cf_1'}),
    {path: '/projects/api/demo/orchestration/crew-flows/cf_1/cancel', body: {}});
  assert.ok(flowActive({status: 'blocked'}) && !flowActive({status: 'stopped'}) && !flowActive(null));
});

test('each state says where the flow stands, and the panel looks again only while it can change', () => {
  assert.deepEqual(flowLine(flow('running')), {key: 'line_running', stage: 'screenwriter', params: {finished: 1, total: 2}});
  assert.deepEqual(flowLine(waiting().flow), {key: 'line_waiting', lock: 'script', params: {}});
  assert.equal(flowLine(flow('blocked', {blocked: {code: 'paused', message: 'Automatic crew work is paused.'}})).params.reason, 'Automatic crew work is paused.');
  assert.equal(flowLine(flow('stopped', {stop: {message: 'The script changed.'}})).key, 'line_stopped');
  assert.deepEqual(flowLine(flow('completed')), {key: 'line_completed', params: {}});
  assert.equal(flowLine(null), null);
  assert.deepEqual([pollDelay(flow('running')), pollDelay(flow('waiting')), pollDelay(flow('completed')), pollDelay(null)], [2000, 6000, null, null]);
  assert.deepEqual(lockSummary(waiting().next), {key: 'lockWhat_script', params: {scenes: 2, chars: 340}, items: ['Scene 01: Observatory', 'Scene 02: Departure']});
  assert.deepEqual(lockSummary({lock: 'list', summary: {assets: 4, looks: 1, shots: 5}}).params, {assets: 4, looks: 1, shots: 5});
  const rows = stageRows(waiting());
  assert.deepEqual(rows.map(row => [row.key, row.gate, row.asking]), [['screenwriter', null, false], ['art', 'script', true], ['cinematographer', 'list', false], ['continuity', 'storyboard', false]]);
  assert.equal(rows[1].next.hash, 'sha256:abc', 'the lock carries the hash of exactly what the director saw');
});

test('R25: the card shows after the storyboard is built, never before, and not while a flow runs', () => {
  const none = {canStart: true, flow: null};
  assert.equal(showPreproductionCard({state: none, shots: 5, writable: true}), true);
  assert.equal(showPreproductionCard({state: none, shots: 0, writable: true}), false, 'no storyboard yet');
  assert.equal(showPreproductionCard({state: none, shots: 5, writable: false}), false, 'a viewer');
  assert.equal(showPreproductionCard({state: none, shots: 5, writable: true, dismissed: true}), false, 'set aside for this episode');
  assert.equal(showPreproductionCard({state: {canStart: false, flow: flow('running')}, shots: 5, writable: true}), false);
  assert.equal(showPreproductionCard({state: {canStart: true, flow: flow('completed')}, shots: 5, writable: true}), true, 'a finished flow can run again');
  const store = new Map(), storage = {getItem: key => store.get(key) ?? null, setItem: (key, value) => store.set(key, value)};
  assert.equal(cardDismissed('ep_demo_01', storage), false);
  dismissCard('ep_demo_01', storage);
  assert.equal(cardDismissed('ep_demo_01', storage), true);
  assert.equal(cardDismissed('ep_demo_02', storage), false);
  assert.equal(cardDismissed('ep_demo_01', {getItem() {throw new Error('blocked');}}), false, 'blocked storage keeps the card');
});

test('the Shot Stage shows the card once the storyboard exists, then one line of where the flow stands', async () => {
  await components.setLocale('en');
  const card = render({compact: true, writable: true, shots: 5, initial: {canStart: true, canLock: true, flow: null, next: null}});
  assert.match(card, /<section class="crew-flow crew-flow-card" aria-label="Let the crew pre-produce">/);
  assert.match(card, /<button type="button" class="apply">Let the crew pre-produce<\/button>/);
  assert.match(card, /<button type="button" class="quiet">Not now<\/button>/);
  assert.match(card, /Nothing is generated\./);
  assert.equal(render({compact: true, writable: true, shots: 0, initial: {canStart: true, flow: null}}), '', 'no card before the storyboard is built');
  const line = render({compact: true, writable: true, shots: 5, initial: {canStart: false, canLock: true, flow: flow('running'), next: null}});
  assert.match(line, /role="status"><b>Crew pre-production<\/b> Screenwriter is working: 1 of 2 jobs finished\.<\/p>/);
  assert.doesNotMatch(line, /<button/, 'locks are set in Story &amp; World');
  await components.setLocale('zh-TW');
  assert.match(render({compact: true, writable: true, shots: 5, initial: {canStart: true, flow: null}}), />讓劇組前製<\/button>/);
  await components.setLocale('en');
});

test('the director sees what the lock covers and locks it; anyone else sees who it waits for', async () => {
  await components.setLocale('en');
  const html = render({writable: true, initial: waiting()});
  assert.match(html, /Review the proposals, then set the Script lock\./);
  assert.match(html, /<b>Script lock<\/b> · 2 scenes, 340 characters/);
  assert.match(html, /Scene 01: Observatory · Scene 02: Departure/);
  assert.match(html, /2 proposals from this stage still wait/);
  assert.match(html, /<button type="button" class="apply">Lock the script<\/button>/);
  assert.match(html, /<button type="button" class="quiet">Cancel pre-production<\/button>/);
  assert.doesNotMatch(html, /Lock the cast and sets list/, 'a later lock is not offered yet');
  const crew = render({writable: true, initial: waiting({canLock: false})});
  assert.doesNotMatch(crew, />Lock the script</);
  assert.match(crew, /Waiting for the director or the showrunner to lock\./);
  const refused = render({writable: true, initial: waiting({next: {...waiting().next, problem: 'Confirm the script and build the storyboard first.'}})});
  assert.doesNotMatch(refused, />Lock the script</, 'no dead button: the reason instead');
  assert.match(refused, /Confirm the script and build the storyboard first\./);
});

test('the current job, the stop reason with what changed, a blocked stage and a fresh start', async () => {
  await components.setLocale('en');
  const running = render({writable: true, initial: {canStart: false, canLock: true, flow: flow('running'), next: null}});
  assert.match(running, /Shot breakdown · Episode 1 <small>working<\/small>/);
  assert.match(running, /1 of 2 jobs finished/);
  const locked = {script: {by: 'u1', byName: 'Maya Chen', role: 'director', at: '2026-10-27T09:00:00Z', hash: 'sha256:1', summary: {}}, list: null, storyboard: null};
  const stopped = render({writable: true, initial: {canStart: true, canLock: true, next: null, flow: flow('stopped', {canCancel: false, locks: locked,
    stop: {lock: 'script', message: 'The script changed after the script lock, so the flow stopped.', changed: ['The text of scene "Scene 02: Departure" changed.'], staleProposals: [4, 5]},
    stages: [stage('screenwriter', 'done'), stage('art', 'stopped'), stage('cinematographer', 'pending'), stage('continuity', 'pending')]})}});
  assert.match(stopped, /Stopped: The script changed after the script lock, so the flow stopped\./);
  assert.match(stopped, /<li>The text of scene &quot;Scene 02: Departure&quot; changed\.<\/li>/);
  assert.match(stopped, /2 proposals from the later stages are now stale\./);
  assert.match(stopped, /Script lock · locked by Maya Chen/);
  assert.match(stopped, />Start pre-production again<\/button>/);
  assert.doesNotMatch(stopped, /Cancel pre-production/);
  const blocked = render({writable: true, initial: {canStart: false, canLock: true, next: null, flow: flow('blocked', {current: 'art',
    blocked: {stage: 'art', code: 'paused', message: 'Automatic crew work is paused for this production. Resume it, then try again.', blockers: []}})}});
  assert.match(blocked, /Blocked: Automatic crew work is paused/);
  assert.match(blocked, />Try again<\/button>/);
  const fresh = render({writable: true, initial: {canStart: true, canLock: true, flow: null, next: null}});
  assert.match(fresh, />Let the crew pre-produce<\/button>.*>The script is final: start at the script lock<\/button>/s);
  assert.doesNotMatch(render({writable: false, initial: {canStart: false, canLock: false, flow: null, next: null}}), /<button/, 'a viewer reads only');
});

test('the Continuity Supervisor is asked on an episode or a scene, and its findings are listed with their fix', async () => {
  assert.deepEqual(CONTINUITY_KINDS, ['continuity']);
  assert.ok(ALL_CREW_KINDS.includes('continuity'));
  assert.equal(crewJobPath('sc_demo_01_S01', 'continuity'), '/scenes/sc_demo_01_S01/continuity-proposals');
  assert.equal(crewJobPath('ep_demo_01', 'continuity'), '/episodes/ep_demo_01/continuity-proposals');
  assert.equal(crewRunningKey({role: 'qa_critic', kind: 'continuity'}), 'crewRunningContinuity');
  const findings = [{kind: 'wardrobe', shots: ['SC01-S01', 'SC01-S02'], subject: '@CAST-01', severity: 'major', certainty: 'likely', detail: 'The jacket opens.', proposalId: 7}];
  const done = {jobId: 'cj_c', kind: 'continuity', status: 'succeeded', source: 'model', result: {findings, proposalIds: [7]}};
  assert.deepEqual(crewJobLine(done), {key: 'crewFindings', params: {count: 1}});
  assert.deepEqual(crewJobLine({...done, source: 'rule_fallback'}), {key: 'crewFindingsFallback', params: {count: 1}});
  assert.deepEqual(crewJobLine({...done, result: {findings: [], proposalIds: []}}), {key: 'crewFindingsNone', params: {count: 0}});
  assert.deepEqual(crewFindings(done), findings);
  assert.deepEqual(crewFindings({...done, status: 'running'}), []);
  assert.deepEqual(GENERATION_DESK_CREW, {prompt: ['beats'], camera: ['camera'], cast: ['appearances']}, 'the SPEC_19 desk hook');
  await components.setLocale('en');
  const html = renderToStaticMarkup(React.createElement(components.CrewAsk, {slug: 'demo', targetId: 'ep_demo_01', kinds: CONTINUITY_KINDS,
    title: 'shotProposal.askContinuityTitle', hint: 'shotProposal.askContinuityHint', writable: true}));
  assert.match(html, /aria-label="Ask the Continuity Supervisor"/);
  assert.match(html, /<button type="button">Check continuity<\/button>/);
  assert.match(html, /Grades are information, not gates\./);
});
