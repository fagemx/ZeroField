import test, {before, after} from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {build} from 'esbuild';
import {mkdtemp, writeFile, rm} from 'node:fs/promises';
import {join, dirname, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {defaultPlan} from '../src/previs/plan.js';
import {ghostMarks, loadShotProposals, opLines, planChanges, shotMetaKey, shotMetaReview, shotProposalsPath, solutionPath} from '../src/previs/shotMetaModel.js';
import {ACTION_LABEL} from '../src/format.js';
import {setLocale as setModelLocale} from '../src/i18n/index.js';

// SPEC_20 R18: a crew proposal of a shot's whole 3D plan (shot_meta) is reviewed on the 3D Stage: the proposed plan as a ghost over
// the current one, who proposed it and what it changes, Approve / Reject for the person it was made for, read-only for a viewer.
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
let temporary, components;
before(async () => {
  temporary = await mkdtemp(join(root, 'tests/.shot-meta-render-'));
  const result = await build({stdin: {contents: "export {ShotMetaReview, GhostMarks, changeText} from './src/previs/ShotMetaReview.jsx'; export {setLocale} from './src/i18n/index.js';",
    resolveDir: root, sourcefile: 'shot-meta-render.jsx', loader: 'jsx'}, bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', packages: 'external', loader: {'.css': 'empty'}});
  const output = join(temporary, 'components.mjs');
  await writeFile(output, result.outputFiles[0].text);
  components = await import(pathToFileURL(output));
});
after(async () => {if (temporary) await rm(temporary, {recursive: true, force: true});});
const render = (name, props) => renderToStaticMarkup(React.createElement(components[name], props));
const noop = () => {};

const current = {...defaultPlan(), lens: 35, move: 'pushin', code: '@CAST-01', mark: [0, 0]};
const proposed = {...current, lens: 85, move: 'orbit', seconds: 6, mark: [0.4, -0.6], cast: [{code: '@CAST-02', mark: [1.5, 0.3]}]};
const item = (id, value, extra = {}) => ({id, action: 'shot_meta', status: 'pending', shotId: 'sh_demo_b1', field: 'previsPlan', baseRevision: 2, currentRevision: 2,
  value, summary: 'Orbit on an 85 so the dial reads.', shot: {label: 'S03', tabKey: 'cinema-studio', rowId: 'b1'},
  author: {kind: 'agent', key: 'sheet_ops', name: 'Cinematographer'}, canDecide: true, ...extra});

test('the stage reads my pending 3D plan proposals for one shot and keeps only well-formed ones', async () => {
  const asked = [];
  const get = async path => {asked.push(path); return {proposals: [item(1, proposed), item(2, null), {...item(3, proposed), field: 'look'}, {...item(4, proposed), status: 'applied'}, item(5, [proposed]), item(6, current)]};};
  const list = await loadShotProposals(get, 'demo', 'sh_demo_b1');
  assert.deepEqual(asked, ['/projects/api/demo/assistant/shots/sh_demo_b1/proposals']);
  assert.deepEqual(list.map(p => p.id), [1, 6]);
  assert.equal(shotProposalsPath('demo', 'sh_a b'), '/projects/api/demo/assistant/shots/sh_a%20b/proposals');
  assert.deepEqual(await loadShotProposals(async () => ({}), 'demo', 'sh_x'), []);
  await assert.rejects(loadShotProposals(async () => {throw Object.assign(new Error('Assistant access is not enabled'), {status: 403});}, 'demo', 'sh_x'), /not enabled/);
});

test('the assistant list tells the stage when to read a shot\'s proposals again', () => {
  const proposals = [{id: 9, action: 'shot_meta', status: 'pending', target: {shotId: 'sh_a'}}, {id: 4, action: 'shot_meta', status: 'pending', target: {shotId: 'sh_a'}},
    {id: 5, action: 'shot_meta', status: 'applied', target: {shotId: 'sh_a'}}, {id: 6, action: 'table_edit', status: 'pending', target: {shotId: 'sh_a'}},
    {id: 7, action: 'shot_meta', status: 'pending', target: {shotId: 'sh_b'}}];
  assert.equal(shotMetaKey(proposals, 'sh_a'), '4,9');
  assert.equal(shotMetaKey(proposals, 'sh_b'), '7');
  assert.equal(shotMetaKey(proposals, null), '');
  assert.equal(shotMetaKey(undefined, 'sh_a'), '');
});

test('what a proposal changes reads in the stage\'s own terms', () => {
  assert.deepEqual(planChanges(current, {...current}), [], 'the same plan changes nothing');
  const changes = planChanges(current, proposed);
  assert.deepEqual(changes.filter(c => c.kind === 'field').map(c => [c.key, c.from, c.to]), [['move', 'pushin', 'orbit'], ['lens', 35, 85], ['seconds', 4, 6]]);
  assert.deepEqual(changes.filter(c => c.kind !== 'field').map(c => c.kind), ['castAdded', 'blocking']);
  assert.deepEqual(changes.find(c => c.kind === 'castAdded').codes, ['@CAST-02']);
  const framed = {...current, keys: [[0, [1, 1.6, -3], [0, 1.4, 0]], [96, [-1, 1.6, -3], [0, 1.4, 0]]]};
  assert.deepEqual(planChanges(current, framed).map(c => c.kind), ['camera']);
  assert.deepEqual(planChanges(proposed, current).map(c => c.kind).slice(-2), ['castRemoved', 'blocking']);
  assert.deepEqual(planChanges(current, {...current, acts: [{at: 0, body: 'kneel'}]}).map(c => c.kind), ['acting']);
  assert.deepEqual(planChanges(current, {...current, figure: {build: 'elder'}}).map(c => c.kind), ['other']);
  assert.deepEqual(planChanges(current, {...current, keys: null, easing: undefined}), [], 'no keys and an absent easing are the preset either way');
  assert.equal(components.changeText(changes[1]), 'Lens: 35mm → 85mm');
  assert.equal(components.changeText(changes[0]), 'Camera move: Push in → Orbit');
  assert.equal(components.changeText(changes.find(c => c.kind === 'castAdded')), 'Joins the shot: @CAST-02');
});

test('the ghost rings mark where the proposal puts each person, numeric marks only', () => {
  assert.deepEqual(ghostMarks(proposed), [{id: 'actor', mark: [0.4, -0.6], code: '@CAST-01'}, {id: 'cast:0', mark: [1.5, 0.3], code: '@CAST-02'}]);
  assert.deepEqual(ghostMarks({...proposed, mark: [{range: [0, 1]}, 0], cast: [{mark: [2, 0]}]}).map(m => [m.id, m.code]), [['cast:0', '']]);
  assert.deepEqual(ghostMarks(null), []);
  const project = (x, z) => (x > 1 ? null : {x: 100 + x * 10, y: 100 - z * 10});
  const html = render('GhostMarks', {marks: ghostMarks(proposed), project});
  assert.match(html, /<span class="plan-ghost-mark" style="left:104px;top:106px" title="Proposed mark: @CAST-01"><b>CAST-01<\/b><\/span>/);
  assert.equal((html.match(/plan-ghost-mark/g) || []).length, 1, 'a mark off the plan is not drawn');
});

test('the review is the shot\'s first pending proposal, decidable only by a writer it was made for', () => {
  assert.equal(shotMetaReview([], {plan: current}), null);
  assert.equal(shotMetaReview(undefined), null);
  const review = shotMetaReview([item(1, {lens: 85, move: 'orbit'}), item(2, proposed)], {plan: current, revision: 2, writable: true});
  assert.equal(review.id, 1);
  assert.deepEqual([review.plan.lens, review.plan.set, review.plan.seconds], [85, 'observatory', 4], 'a partial value fills in from the default plan');
  assert.deepEqual([review.label, review.author, review.summary, review.more], ['S03', 'Cinematographer', 'Orbit on an 85 so the dial reads.', 1]);
  assert.deepEqual([review.canDecide, review.readOnly, review.blockedByDraft, review.stale], [true, false, false, false]);
  assert.equal(shotMetaReview([item(1, proposed, {author: {kind: 'agent', key: 'sheet_ops', name: 'Cinematographer'}})], {plan: current}).readOnly, true, 'not writable here: view only');
  assert.equal(shotMetaReview([item(1, proposed, {canDecide: false})], {plan: current, writable: true}).readOnly, true, 'the server says this person cannot decide it');
  assert.equal(shotMetaReview([item(1, proposed)], {plan: current, writable: true, draft: true}).blockedByDraft, true, 'unsaved edits first');
  const behind = shotMetaReview([item(1, proposed, {currentRevision: 2})], {plan: current, revision: 3, writable: true});
  assert.deepEqual([behind.stale, behind.currentRevision], [true, 3], 'a revision stored here since the list was read counts');
  assert.equal(shotMetaReview([item(1, proposed)], {plan: current, error: 'Refused.'}).error, 'Refused.');
  assert.equal(shotMetaReview([item(1, proposed, {author: {kind: 'member', id: 'u1', name: 'Maya Lin'}})], {plan: current}).author, 'Maya Lin');
  assert.equal(ACTION_LABEL.shot_meta, '3D plan proposal');
});

test('the inspector shows who proposed what, with Approve and Reject for the person it was made for', () => {
  const review = shotMetaReview([item(1, proposed), item(2, proposed)], {plan: current, revision: 2, writable: true});
  const html = render('ShotMetaReview', {review, onPreview: noop, onApprove: noop, onReject: noop});
  assert.match(html, /<section class="previs-proposal previs-meta-proposal" aria-label="Proposed 3D plan"><h3>Proposed 3D plan<\/h3>/);
  assert.match(html, /Cinematographer proposes a new 3D plan for S03\. It starts from stored revision 2\./);
  assert.match(html, /<p class="previs-meta-summary">Orbit on an 85 so the dial reads\.<\/p>/);
  assert.match(html, /<li>Camera move: Push in → Orbit<\/li><li>Lens: 35mm → 85mm<\/li><li>Duration: 4 s → 6 s<\/li><li>Joins the shot: @CAST-02<\/li><li>Cast marks moved<\/li>/);
  assert.match(html, /<button type="button" aria-pressed="false">Preview the proposal<\/button><button type="button" class="apply">Approve<\/button><button type="button">Reject<\/button>/);
  assert.match(html, /More proposals waiting for this shot: 1/);
  assert.doesNotMatch(html, /View only|previs-meta-stale|role="alert"/);
  const previewing = render('ShotMetaReview', {review, previewing: true, busy: 'approve', onPreview: noop, onApprove: noop, onReject: noop});
  assert.match(previewing, /aria-busy="true"/);
  assert.match(previewing, /<button type="button" aria-pressed="true">Back to the current plan<\/button><button type="button" class="apply" disabled="">Approving…<\/button><button type="button" disabled="">Reject<\/button>/);
  assert.equal(render('ShotMetaReview', {review: null}), '');
});

test('a viewer sees the proposal read-only; a stale one and a refusal say so', () => {
  const viewer = render('ShotMetaReview', {review: shotMetaReview([item(1, proposed)], {plan: current, writable: false}), onPreview: noop});
  assert.match(viewer, /Preview the proposal<\/button><\/div>/, 'no Approve or Reject');
  assert.doesNotMatch(viewer, /class="apply"|>Reject</);
  assert.match(viewer, /View only: read-only crew members cannot approve proposals\./);
  const behind = shotMetaReview([item(1, proposed, {baseRevision: 0, currentRevision: 1})], {plan: current, writable: true});
  assert.match(render('ShotMetaReview', {review: behind, onPreview: noop}), /<p class="previs-meta-stale">The stored plan is now revision 1, so approving this proposal will fail\./);
  const refused = shotMetaReview([item(1, proposed, {baseRevision: 0, currentRevision: 1})], {plan: current, writable: true,
    error: 'The 3D plan of shot S03 changed after this proposal was made (revision 0, now 1). Nothing was applied; generate a new proposal.'});
  const html = render('ShotMetaReview', {review: refused, onPreview: noop, onApprove: noop, onReject: noop});
  assert.match(html, /<p class="shot-proposal-error" role="alert">The 3D plan of shot S03 changed after this proposal was made/);
  assert.doesNotMatch(html, /previs-meta-stale/, 'the refusal already names both revisions');
  assert.match(html, /class="apply">Approve<\/button>/, 'it stays on stage to be rejected');
  const draft = render('ShotMetaReview', {review: shotMetaReview([item(1, proposed)], {plan: current, writable: true, draft: true}), onPreview: noop});
  assert.match(draft, /class="apply" disabled="">Approve<\/button>/);
  assert.match(draft, /Save or discard your unsaved edits before approving\./);
  assert.match(render('ShotMetaReview', {review: shotMetaReview([item(1, current)], {plan: current, writable: true})}), /Same as the plan on stage\./);
});

test('the review reads in Traditional Chinese', async () => {
  await components.setLocale('zh-TW'); await setModelLocale('zh-TW');  // the bundled components and the model each hold an i18n instance
  try {
    const review = shotMetaReview([item(1, proposed, {baseRevision: 1, currentRevision: 2})], {plan: current, writable: true});
    const html = render('ShotMetaReview', {review, onPreview: noop, onApprove: noop, onReject: noop});
    for (const text of ['提議的 3D 計畫', '為 S03 提出新的 3D 計畫', '依據已存的第 1 版', '焦距：35mm → 85mm', '運鏡：推近 → 環繞', '加入這一鏡：@CAST-02',
      '已存的計畫現在是第 2 版', '預覽提案', '核准', '拒絕']) assert.ok(html.includes(text), text);
    assert.equal(ACTION_LABEL.shot_meta, '3D 計畫提案');
  } finally {await components.setLocale('en'); await setModelLocale('en');}
});

// SPEC_20 R27, R28: a proposal made of 3D operations carries the server's contact sheet and the operations; without a server solve
// (no headless browser) the stage solves them with the same ops.js and approving attaches that solve first.
const OPS = [{op: 'place', cast: '@CAST-01', relativeTo: 'console', offset: [0, -0.55], facing: 'camera'},
  {op: 'camera', size: 'close', angle: 'eye', lens: 50, move: 'pushin', from: 'K1', to: 'K2'}, {op: 'retime', beat: 2, at: 0.6}];
const sheet = {kind: 'contact_sheet', url: '/projects/api/demo/assets/pa_' + 'b'.repeat(32), width: 1944, height: 818, frames: [0, 19, 38, 58, 77, 96].map(frame => ({frame}))};

test('operations-only proposals are kept for the stage to solve, and the stage\'s solve is the ghost', async () => {
  const opsOnly = item(7, null, {ops: OPS, solve: {status: 'ops_only', reason: 'no_browser'}, preview: null});
  const list = await loadShotProposals(async () => ({proposals: [opsOnly, item(8, null, {ops: []}), item(9, null)]}), 'demo', 'sh_demo_b1');
  assert.deepEqual(list.map(p => p.id), [7], 'operations without a plan are kept; nothing at all is not');
  const asked = [];
  const review = shotMetaReview(list, {plan: current, revision: 2, writable: true, solve: proposal => {asked.push(proposal.id); return proposed;}});
  assert.deepEqual(asked, [7]);
  assert.deepEqual([review.opsOnly, review.plan.lens, review.blockedBySolve, review.preview, review.solveError], [true, 85, false, null, '']);
  assert.deepEqual(review.ops.map(line => line.key), ['metaOpPlace', 'metaOpCamera', 'metaOpRetime']);
  assert.deepEqual(review.ops[0].params, {cast: '@CAST-01', where: 'console 0, -0.55 m', facing: 'camera'});
  assert.equal(solutionPath('demo', 7), '/projects/api/demo/assistant/proposals/7/solution');
  const failed = shotMetaReview(list, {plan: current, writable: true, solve: () => {throw new Error('ops[2].beat must be an acting beat from 1 to 1.');}});
  assert.deepEqual([failed.plan, failed.blockedBySolve, failed.marks, failed.same], [null, true, [], false]);
  const html = render('ShotMetaReview', {review: failed, onPreview: noop, onApprove: noop, onReject: noop});
  assert.match(html, /role="alert">This stage could not solve the operations: ops\[2\]\.beat must be an acting beat from 1 to 1\.<\/p>/);
  assert.match(html, /<button type="button" aria-pressed="false" disabled="">Preview the proposal<\/button><button type="button" class="apply" disabled="">Approve<\/button>/);
  const waiting = shotMetaReview(list, {plan: current, writable: true, solve: () => null});
  assert.deepEqual([waiting.plan, waiting.solveError, waiting.blockedBySolve], [null, '', true], 'the stored plan is still loading');
  const solved = render('ShotMetaReview', {review, onPreview: noop, onApprove: noop, onReject: noop});
  assert.match(solved, /Operations only: the server rendered no preview\. This stage solved them; approving stores this solve\./);
  assert.match(solved, /class="apply">Approve<\/button>/);
});

test('a solved proposal shows its contact sheet, its operations, the solver\'s notes and a model note to check', () => {
  const solved = item(3, proposed, {ops: OPS, preview: sheet, solve: {status: 'solved', by: 'headless', warnings: ['Camera key K1 was pulled in toward the subject to stay inside the stage.']},
    vision: {status: 'checked', model: 'qwen3.8:27b', note: 'Face reads from 1.6 s.', issues: ['K1 starts behind his head']}});
  const review = shotMetaReview([solved], {plan: current, revision: 2, writable: true});
  assert.deepEqual([review.opsOnly, review.preview.url, review.warnings.length], [false, sheet.url, 1]);
  const html = render('ShotMetaReview', {review, onPreview: noop, onApprove: noop, onReject: noop});
  assert.match(html, new RegExp(`<figure class="previs-meta-sheet"><a href="${sheet.url}" target="_blank" rel="noreferrer"><img src="${sheet.url}" alt="Contact sheet of the proposed 3D plan" loading="lazy" width="1944" height="818"/></a>`));
  assert.match(html, /Rendered from the solved plan: 6 frames through the shot camera/);
  assert.match(html, /<details class="previs-meta-ops"><summary>Operations \(3\)<\/summary><ol><li>@CAST-01 at console 0, -0\.55 m, facing camera<\/li><li>Camera: close, eye angle, 50mm pushin K1→K2<\/li><li>Acting beat 2 starts at 60% of the shot<\/li><\/ol><\/details>/);
  assert.match(html, /<summary>Solver notes \(1\)<\/summary><ul><li>Camera key K1 was pulled in toward the subject to stay inside the stage\.<\/li><\/ul>/);
  assert.match(html, /Model note \(qwen3\.8:27b\), check it yourself: Face reads from 1\.6 s\. Issues it saw: K1 starts behind his head/);
  assert.doesNotMatch(html, /Operations only/);
  assert.deepEqual(opLines([{op: 'camera', size: 'extreme_close', angle: 'low', lens: 85, move: 'static'}, {op: 'camera', size: 'wide', angle: 'high', lens: 24, move: 'orbit'}])
    .map(line => line.params.keys + '|' + line.params.size), ['|extreme close', ' K1→K3|wide']);
});
