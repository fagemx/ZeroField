import test from 'node:test';
import assert from 'node:assert/strict';
import { buildStoryFromWorkspace, primaryStoryAction } from '../src/storyHostModel.js';

test('the one primary button follows what the workspace shows', () => {
  const base = {writable:true, hasScript:true, hasShots:false};
  assert.deepEqual(primaryStoryAction(base), {action:'build', labelKey:'story.confirmAndBuild', disabled:false, hintKey:null});
  assert.equal(primaryStoryAction({...base, hasShots:true}).labelKey, 'world.updateStoryboard', 'with shots it updates');
  assert.equal(primaryStoryAction({...base, hasScript:false}).disabled, true, 'nothing written, nothing to build');
  assert.equal(primaryStoryAction({...base, busy:true}).disabled, true);
  assert.equal(primaryStoryAction({...base, loading:true}).disabled, true);
  assert.equal(primaryStoryAction({...base, writable:false}).disabled, true, 'a reader cannot build');
  assert.deepEqual(primaryStoryAction({...base, manuscript:'source', canAdapt:true}), {action:'adapt', labelKey:'writing.authoring.previewAdaptation', disabled:false, hintKey:null});
  assert.equal(primaryStoryAction({...base, manuscript:'source', canAdapt:false}).disabled, true, 'a source that cannot be adapted yet (conflict, recovery) waits');
  for (const [manuscript, hint] of [['version', 'world.primaryHint_version'], ['branch', 'world.primaryHint_branch']]) {
    const read = primaryStoryAction({...base, manuscript});
    assert.deepEqual([read.action, read.disabled, read.hintKey], ['none', true, hint], manuscript + ' says what to do first');
  }
  assert.equal(primaryStoryAction().disabled, true, 'no information, no action');
});

test('confirming the build makes the server hold the text first, then runs the three requests, and never sends the script itself', async () => {
  const sent = [], waited = [];
  const request = async (path, method, body) => {sent.push([method, path, body]); return {taskId:'t' + sent.length, result:{step:sent.length}};};
  const wait = async task => {waited.push(task.taskId); return task.result;};
  let flushes = 0, done;
  const result = await buildStoryFromWorkspace({epId:'ep_demo_01', breakdownMode:'scene', settings:{aspectRatio:'9:16', stylePresetId:'88124'}, request, wait,
    flush:async () => {flushes++; assert.equal(sent.length, 0, 'the server has the text before anything is sent'); return true;}, onDone:async value => {done = value;}});
  assert.equal(flushes, 1);
  assert.deepEqual(sent, [
    ['PUT', '/episodes/ep_demo_01/settings', {aspectRatio:'9:16', stylePresetId:'88124', breakdownMode:'scene'}],
    ['POST', '/episodes/ep_demo_01/asset-extractions', undefined],
    ['POST', '/episodes/ep_demo_01/storyboards', {breakdownMode:'scene'}],
  ]);
  assert.ok(!sent.some(([, path]) => path.endsWith('/script')), 'the workspace owns the script: there is no PUT script');
  assert.deepEqual(waited, ['t2', 't3'], 'both tasks are followed to their end, extraction first');
  assert.deepEqual(result, {step:3});
  assert.deepEqual(done, {step:3}, 'onDone gets the storyboard task result');
});

test('a build stops before sending anything when the server could not take the text', async () => {
  const sent = [];
  await assert.rejects(buildStoryFromWorkspace({epId:'ep_demo_01', settings:{}, request:async (...args) => {sent.push(args);}, wait:async () => null, flush:async () => false}), /Save to the server/);
  assert.deepEqual(sent, []);
  const direct = [];
  await buildStoryFromWorkspace({epId:'ep_demo_01', settings:{}, request:async (path, method) => {direct.push(method + ' ' + path); return {taskId:'x'};}, wait:async () => 'done'});
  assert.equal(direct.length, 3, 'without a workspace to ask (a page with no manuscript open) the requests simply go');
});
