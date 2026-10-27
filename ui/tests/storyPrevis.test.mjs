import test from 'node:test';
import assert from 'node:assert/strict';
import { stageShots } from '../src/studioModel.js';
import { resolveShotPlan } from '../src/previs/storyPlan.js';

test('Story shot metadata reaches the stage and supplies its parallax set, lens and acting', () => {
  const image = '/projects/api/story/assets/pa_' + 'a'.repeat(32);
  const row = { rid: 'b_shot', cells: ['SC01-S02', 'ARRI Alexa / 35mm', 'Static Tripod', '@CAST-01 looks at @SET-01', '', ''].map(value => ({ value })) };
  const parsed = { headers: ['Shot', 'Optical Rig', 'Camera Motion', 'Action Prompt', 'Keyframe', 'Previs'], rows: [row], table: { attrs: { column_types: ['text', 'text', 'text', 'text', 'image', 'video'] } } };
  const generated = { set: 'parallax', lens: 85, move: 'pushin', action: 'turnreach', facing: 'room', seconds: 4 };
  const [shot] = stageShots(parsed, parsed.rows, { 'SET-01': { id: 'SET-01', media: { kind: 'image', url: image } } }, { b_shot: { previsPlan: generated } });
  const plan = resolveShotPlan(shot);
  for (const [key, value] of Object.entries(generated)) assert.equal(plan[key], value);
  assert.deepEqual(plan.layers, [{ id: 'far', src: image }]);
  assert.equal(resolveShotPlan(stageShots(parsed)[0]).move, 'static', 'older rows retain slate inference');
  row.cells[3].value = '@CAST-01 looks at @LOC-01';
  const [location] = stageShots(parsed, parsed.rows, { 'LOC-01': { id: 'LOC-01', media: { kind: 'image', url: image } } }, { b_shot: { previsPlan: generated } });
  assert.deepEqual(resolveShotPlan(location).layers, [{ id: 'far', src: image }], 'legacy location assets supply the same parallax background');
});

test('a story shot reaches the stage with its id and the revision of the plan stored in the project', () => {
  const row = { rid: 'b_shot', cells: ['SC01-S01', '35mm', 'Static', 'Kael waits', '', ''].map(value => ({ value })) };
  const parsed = { headers: ['Shot', 'Optical Rig', 'Camera Motion', 'Action Prompt', 'Keyframe', 'Previs'], rows: [row], table: { attrs: { column_types: ['text', 'text', 'text', 'text', 'image', 'video'] } } };
  const [story] = stageShots(parsed, parsed.rows, null, { b_shot: { shotId: 'sh_demo_b_shot', previsPlanRevision: 3, previsPlanStored: true, previsPlan: { lens: 50 } } });
  assert.deepEqual([story.shotId, story.previsRevision, story.previsStored], ['sh_demo_b_shot', 3, true]);
  const [cleared] = stageShots(parsed, parsed.rows, null, { b_shot: { shotId: 'sh_demo_b_shot', previsPlanRevision: 4, previsPlanStored: false } });
  assert.deepEqual([cleared.previsRevision, cleared.previsStored], [4, false], 'a cleared plan keeps its revision');
  const [sheetOnly] = stageShots(parsed);
  assert.deepEqual([sheetOnly.shotId, sheetOnly.previsRevision, sheetOnly.previsStored], [null, null, false], 'a row outside the story sheets stores nothing');
});

test('a plan resolves draft, then stored, then the WebM backup, then this render, then the seed', () => {
  const shot = { slate: { motion: 'Static tripod', rig: '85mm', action: 'waits' }, previsPlan: { lens: 24, move: 'orbit' } };
  const draft = { move: 'track' }, stored = { move: 'crane' }, embedded = { move: 'pullout' }, rendered = { move: 'pushin', lens: 50 };
  assert.equal(resolveShotPlan(shot, { draft, stored, embedded, rendered }).move, 'track', 'unsaved edits in this browser win');
  assert.equal(resolveShotPlan(shot, { stored, embedded, rendered }).move, 'crane', 'then the plan stored in the project');
  assert.equal(resolveShotPlan(shot, { embedded, rendered }).move, 'pullout', 'then the plan a rendered previs carries');
  assert.deepEqual([resolveShotPlan(shot, { rendered }).move, resolveShotPlan(shot, { rendered }).lens], ['pushin', 50], 'then the render made here');
  assert.deepEqual([resolveShotPlan(shot).move, resolveShotPlan(shot).lens], ['orbit', 24], 'and last the storyboard seed on the slate');
  assert.deepEqual(resolveShotPlan(shot, { stored: { lens: 85 } }), { ...resolveShotPlan(null, { stored: {} }), lens: 85 }, 'a stored plan fills in the defaults');
  assert.equal(resolveShotPlan(shot, { stored: null, embedded: null, rendered: null }).move, 'orbit', 'nothing stored anywhere: the seed');
});

test('Director edits and recorded plans keep priority over a regenerated storyboard', () => {
  const shot = { previsPlan: { set: 'parallax', lens: 85, move: 'orbit' }, setAsset: { url: '/set.png' } };
  const draft = { set: 'empty', lens: 50, move: 'track', keys: [[0, [1, 2, 3], [0, 0, 0]]] };
  const stored = { set: 'parallax', lens: 24, layers: [] };
  const rendered = { lens: 35, move: 'crane' };
  assert.equal(resolveShotPlan(shot, { draft, stored, rendered }).move, 'track');
  assert.deepEqual(resolveShotPlan(shot, { draft }).keys, draft.keys);
  assert.deepEqual(resolveShotPlan(shot, { stored, rendered }).layers, [], 'explicitly cleared layers remain cleared');
  assert.equal(resolveShotPlan(shot, { rendered }).move, 'crane');
});

test('Invalid generated plan fields fall back to supported slate values', () => {
  const plan = resolveShotPlan({ slate: { rig: '85mm', motion: 'Slow Dolly In', action: 'walks' }, previsPlan: { lens: -8, move: 'unknown', seconds: 300, action: null, facing: 'other', set: 'missing' } });
  assert.equal(plan.lens, 85); assert.equal(plan.move, 'pushin'); assert.equal(plan.action, 'walkin');
  assert.equal(plan.seconds, 4); assert.equal(plan.set, 'observatory');
});
