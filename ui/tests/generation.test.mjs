import test from 'node:test';
import assert from 'node:assert/strict';
import {activeTasks, isActiveRun, restoredRuns, runDismissed, runRefused, runStarted, settleRun, startRun} from '../src/generation/generationModel.js';
import {rememberGenerations, restoredGenerations} from '../src/worldModel.js';

test('three cards can generate at once, each with its own run, and a second click on a running card changes nothing', () => {
  let runs = {};
  for (const id of ['as_1', 'as_2', 'as_3']) runs = startRun(runs, id);
  assert.deepEqual(Object.keys(runs), ['as_1', 'as_2', 'as_3']);
  assert.ok(Object.values(runs).every(isActiveRun), 'all three show generating before any task id exists');
  assert.deepEqual(activeTasks(runs), {}, 'a run without a task id has nothing to remember or poll yet');
  runs = runStarted(runs, 'as_1', {taskId:'t1', status:'QUEUED'});
  assert.equal(startRun(runs, 'as_1'), runs, 'one in-flight task per card: the same object comes back');
  runs = runStarted(runStarted(runs, 'as_2', {taskId:'t2', status:'RUNNING'}), 'as_3', {taskId:'t3'});
  assert.deepEqual(activeTasks(runs), {as_1:'t1', as_2:'t2', as_3:'t3'});
  assert.equal(runs.as_3.status, 'QUEUED', 'a task that does not say yet is queued');
});

test('a finished picture removes only its own run; a failure keeps its reason; cancel is canceled, not failed', () => {
  let runs = {as_1:{taskId:'t1', status:'RUNNING'}, as_2:{taskId:'t2', status:'RUNNING'}, as_3:{taskId:'t3', status:'QUEUED'}};
  runs = settleRun(runs, 'as_1', {taskId:'t1', status:'SUCCEEDED'});
  assert.deepEqual(Object.keys(runs), ['as_2', 'as_3'], 'the two others keep running');
  runs = settleRun(runs, 'as_2', {taskId:'t2', status:'FAILED', error:{message:'Worker unavailable'}});
  assert.deepEqual(runs.as_2, {taskId:'t2', status:'FAILED', error:'Worker unavailable'});
  assert.equal(isActiveRun(runs.as_2), false, 'a failed card can generate again');
  runs = settleRun(runs, 'as_3', {taskId:'t3', status:'CANCELED'});
  assert.deepEqual(runs.as_3, {taskId:'t3', status:'CANCELED'});
  assert.deepEqual(activeTasks(runs), {}, 'nothing in flight is left to remember');
  assert.equal(settleRun({as_1:{taskId:'t1', status:'RUNNING'}}, 'as_1', {taskId:'t1', status:'FAILED'}).as_1.error, 'FAILED', 'no message: say the state');
});

test('progress updates change the status; an answer for an older task or an unknown card is ignored', () => {
  const runs = {as_1:{taskId:'t1', status:'QUEUED'}};
  const running = settleRun(runs, 'as_1', {taskId:'t1', status:'RUNNING'});
  assert.equal(running.as_1.status, 'RUNNING');
  assert.equal(settleRun(running, 'as_1', {taskId:'t1', status:'RUNNING'}), running, 'nothing changed, the same object');
  assert.equal(settleRun(running, 'as_1', {taskId:'old', status:'SUCCEEDED'}), running, 'a task the card moved on from');
  assert.equal(settleRun(running, 'as_9', {taskId:'x', status:'SUCCEEDED'}), running);
  const retried = runStarted(runRefused(runs, 'as_1', 'No worker'), 'as_1', {taskId:'t2', status:'QUEUED'});
  assert.deepEqual(retried.as_1, {taskId:'t2', status:'QUEUED'}, 'retry replaces the failure');
  assert.deepEqual(runDismissed(retried, 'as_1'), {});
});

test('what a reload restores is in flight until the first poll says otherwise, so a finished picture is refreshed, never sent twice', () => {
  const runs = restoredRuns({as_1:'t1', as_2:'t2'});
  assert.deepEqual(runs, {as_1:{taskId:'t1', status:'RUNNING'}, as_2:{taskId:'t2', status:'RUNNING'}});
  assert.deepEqual(activeTasks(settleRun(runs, 'as_1', {taskId:'t1', status:'SUCCEEDED'})), {as_2:'t2'}, 'it finished while the page was away: gone, refreshed, no new request');
});

test('running tasks are remembered per episode in sessionStorage, and without storage in memory', () => {
  const store = new Map();
  globalThis.sessionStorage = {getItem: key => store.get(key) ?? null, setItem: (key, value) => store.set(key, value), removeItem: key => store.delete(key)};
  try {
    assert.deepEqual(restoredGenerations('ep_gen_a'), {});
    rememberGenerations('ep_gen_a', {as_1:'t1', as_2:'t2'});
    assert.equal(store.get('zf.gen:ep_gen_a'), '{"as_1":"t1","as_2":"t2"}');
    assert.deepEqual(restoredGenerations('ep_gen_a'), {as_1:'t1', as_2:'t2'});
    assert.deepEqual(restoredGenerations('ep_gen_b'), {}, 'another episode starts clean');
    rememberGenerations('ep_gen_a', {});
    assert.equal(store.has('zf.gen:ep_gen_a'), false, 'nothing in flight, nothing stored');
    store.set('zf.gen:ep_gen_c', 'not json');
    assert.deepEqual(restoredGenerations('ep_gen_c'), {}, 'unreadable storage is not an error');
    store.set('zf.gen:ep_gen_d', '{"as_1":"t1","as_2":7,"":"t3"}');
    assert.deepEqual(restoredGenerations('ep_gen_d'), {as_1:'t1'}, 'only well-formed entries come back');
    store.set('zf.gen:ep_gen_e', '[1,2]');
    assert.deepEqual(restoredGenerations('ep_gen_e'), {});
    delete globalThis.sessionStorage;
    rememberGenerations('ep_gen_f', {as_5:'t5'});
    assert.deepEqual(restoredGenerations('ep_gen_f'), {as_5:'t5'}, 'no storage: the page remembers for as long as it lives');
    globalThis.sessionStorage = {getItem() {throw new Error('blocked');}, setItem() {throw new Error('blocked');}, removeItem() {throw new Error('blocked');}};
    assert.doesNotThrow(() => rememberGenerations('ep_gen_g', {as_6:'t6'}));
    assert.deepEqual(restoredGenerations('ep_gen_g'), {as_6:'t6'}, 'blocked storage falls back to memory');
  } finally {delete globalThis.sessionStorage;}
});
