import test from 'node:test';
import assert from 'node:assert/strict';
import {rowProposals, applyOptions, proposedSlate, ghostPlan, ghostsFor, isPending} from '../src/proposalModel.js';
import {defaultPlan, planFromSlate, cameraKeys} from '../src/previs/plan.js';

const group = (index, rid, changes) => ({index, row_id: rid, row_number: index + 1, label: 'Row ' + (index + 1), changes});
const camera = (before, after) => ({column: 'Camera Motion', before, after});
const proposal = (id, groups, extra = {}) => ({id, action: 'table_edit', status: 'pending', target: {tab_key: 'cinema-studio', display: 'Cinema Studio'},
  review: {groups, partial_allowed: true, version: 'v' + id}, ...extra});
const slate = {motion: 'Static Tripod', rig: 'ARRI Alexa 65 / 35mm Prime', action: 'Kael waits'};

test('a shot finds its own pending table proposals, one entry per edited row', () => {
  const list = [proposal(1, [group(0, 'b1', [camera('Static Tripod', 'Slow Dolly In')]), group(1, 'b2', [camera('Static Tripod', 'Crane Up')])]),
    proposal(2, [group(0, 'b1', [{column: 'Prompt', before: 'a', after: 'b'}])], {status: 'applied'}),
    proposal(3, [group(0, 'b1', [camera('x', 'y')])], {action: 'comment'}),
    proposal(4, [group(0, 'b1', [camera('x', 'y')])], {target: {tab_key: 'openjutsu-lab'}}),
    proposal(5, [group(0, 'b9', [camera('x', 'y')])])];
  const mine = rowProposals(list, 'b1', 'cinema-studio');
  assert.deepEqual(mine.map(entry => [entry.proposal.id, entry.group.index, entry.partial, entry.size]), [[1, 0, true, 2]]);
  assert.deepEqual(rowProposals(list, 'b2', 'cinema-studio').map(entry => entry.proposal.id), [1]);
  assert.deepEqual(rowProposals(list, 'b1', 'openjutsu-lab').map(entry => entry.proposal.id), [4], 'another tab is its own place');
  assert.deepEqual(rowProposals(list, 'nope', 'cinema-studio'), []);
  assert.deepEqual(rowProposals(undefined, 'b1'), []);
  assert.deepEqual(rowProposals([{...proposal(6, [group(0, 'b1', [])]), review: undefined, target: {tab_key: 'cinema-studio', review: {groups: [group(0, 'b1', [])]}}}], 'b1').length, 1, 'the review may sit on the target');
  assert.equal(isPending({status: 'pending'}), true);assert.equal(isPending({status: 'dismissed'}), false);assert.equal(isPending(null), false);
});

test('applying one row sends only its group when the proposal allows it, and the whole proposal otherwise', () => {
  const [entry] = rowProposals([proposal(1, [group(3, 'b1', []), group(4, 'b2', [])])], 'b1');
  assert.deepEqual(applyOptions(entry), {groups: [3], review_version: 'v1'});
  const [whole] = rowProposals([proposal(2, [group(0, 'b1', [])], {review: {groups: [group(0, 'b1', [])], partial_allowed: false, version: 'v2'}})], 'b1');
  assert.deepEqual(applyOptions(whole), {});
});

test('a proposal reads as the slate it would leave', () => {
  const next = proposedSlate(slate, group(0, 'b1', [camera('Static Tripod', 'Slow Dolly In'), {column: 'Optical Rig', before: 'x', after: 'Sony Venice 2 / 85mm Macro'}]));
  assert.deepEqual(next, {motion: 'Slow Dolly In', rig: 'Sony Venice 2 / 85mm Macro', action: 'Kael waits', camera: true});
  assert.equal(proposedSlate(slate, group(0, 'b1', [{column: 'Prompt', before: 'a', after: 'b'}])).camera, false);
  assert.equal(proposedSlate(undefined, group(0, 'b1', [])).motion, undefined);
});

test('a camera proposal becomes a ghost plan with the proposed move and lens; others make none', () => {
  const plan = planFromSlate(slate);
  assert.equal(plan.move, 'static');
  const ghost = ghostPlan(plan, slate, group(0, 'b1', [camera('Static Tripod', 'Slow Dolly In')]));
  assert.equal(ghost.move, 'pushin');assert.equal(ghost.keys, null);assert.equal(ghost.lens, plan.lens, 'the lens stays unless the rig changes');
  assert.notDeepEqual(cameraKeys(ghost), cameraKeys(plan));
  const wide = ghostPlan(plan, slate, group(0, 'b1', [{column: 'Optical Rig', before: slate.rig, after: 'Sony Venice 2 / 85mm Macro'}]));
  assert.equal(wide.lens, 85);assert.equal(wide.move, 'static', 'only the lens changed');
  assert.equal(ghostPlan(plan, slate, group(0, 'b1', [{column: 'Prompt', before: 'a', after: 'b'}])), null, 'no camera in it');
  assert.equal(ghostPlan(plan, slate, group(0, 'b1', [camera('Static Tripod', 'Locked tripod')])), null, 'the same camera as now');
  const framed = {...defaultPlan(), keys: [[0, [0, 1, -2], [0, 1, 0]], [96, [1, 1, -2], [0, 1, 0]]]};
  assert.equal(ghostPlan(framed, slate, group(0, 'b1', [camera('x', 'Crane Up')])).keys, null, 'a hand-framed path gives way to the proposed move');
});

test('every pending camera proposal on the slate is one ghost, labelled with its shot', () => {
  const shots = [{rid: 'b1', shot: 'S01', slate}, {rid: 'b2', shot: 'S02', slate}, {rid: 'b3', shot: 'S03', slate}];
  const list = [proposal(1, [group(0, 'b1', [camera('Static Tripod', 'Slow Dolly In')]), group(1, 'b3', [{column: 'Prompt', before: 'a', after: 'b'}])]), proposal(2, [group(0, 'b2', [camera('Static Tripod', 'Crane Up')])])];
  const ghosts = ghostsFor(list, shots, 'cinema-studio', shot => planFromSlate(shot.slate));
  assert.deepEqual(ghosts.map(ghost => [ghost.rid, ghost.id, ghost.label, ghost.plan.move]), [['b1', 1, 'S01', 'pushin'], ['b2', 2, 'S02', 'crane']]);
  assert.deepEqual(ghostsFor([], shots, 'cinema-studio', shot => planFromSlate(shot.slate)), []);
});
