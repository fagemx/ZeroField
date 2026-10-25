import test from 'node:test';
import assert from 'node:assert/strict';
import {BREAKDOWN_MODES, closestMode, estimatesByMode, targetSeconds} from '../src/breakdownModel.js';

const modes = {auto:{plannedSeconds:47}, scene:{plannedSeconds:35}, cinematic:{plannedSeconds:63}};

test('the way of splitting whose planned length lands nearest the target is the one to mark', () => {
  assert.equal(closestMode(modes, 45), 'auto');
  assert.equal(closestMode(modes, 30), 'scene');
  assert.equal(closestMode(modes, 90), 'cinematic');
  assert.equal(closestMode(modes, 41), 'auto', 'a tie goes to the first');
  assert.equal(closestMode(modes, null), null, 'no target, nothing to mark');
  assert.equal(closestMode(null, 45), null, 'no estimate yet');
  assert.equal(closestMode({auto:{plannedSeconds:NaN}, scene:null, cinematic:{plannedSeconds:63}}, 45), 'cinematic', 'a mode without a number is not a candidate');
  assert.deepEqual(BREAKDOWN_MODES, ['auto', 'scene', 'cinematic'], 'the three the dialog lists');
});

test('the target field gives the server a whole number of seconds in its range, or nothing', () => {
  assert.equal(targetSeconds('45'), 45);
  assert.equal(targetSeconds(' 90.9 '), 90);
  assert.equal(targetSeconds(10), 10);
  assert.equal(targetSeconds(1800), 1800);
  for (const bad of ['', 'abc', '9', '1801', '-5', null, undefined, '0']) assert.equal(targetSeconds(bad), null, String(bad));
});

test('the server\'s list of modes is read by mode', () => {
  assert.deepEqual(estimatesByMode({modes:[{breakdownMode:'auto', shotCount:9}, {breakdownMode:'scene', shotCount:4}]}), {auto:{breakdownMode:'auto', shotCount:9}, scene:{breakdownMode:'scene', shotCount:4}});
  assert.deepEqual(estimatesByMode(null), {});
  assert.deepEqual(estimatesByMode({}), {});
});
