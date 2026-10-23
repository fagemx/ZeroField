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
