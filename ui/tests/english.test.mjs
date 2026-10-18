import test from 'node:test';
import assert from 'node:assert/strict';
import * as format from '../src/format.js';
import { readCell } from '../src/sheetModel.js';
import { progressCounts, questionNumber, splitSources } from '../src/assistant/text.js';

test('legacy status values stay intact while their labels and colors match the English studio', () => {
  const cell = readCell({type:'status',attrs:{fid:'f_test',label:'已完成'}});
  assert.equal(cell.value,'已完成');
  assert.equal(format.statusLabel(cell.value),'Approved');
  assert.equal(format.statusClass(cell.value),'done');
  assert.equal(format.statusClass('Approved'),'done');
  assert.equal(format.statusLabel('Custom delivery'),'Custom delivery');
});

test('assistant progress and source links accept both English and legacy conversations', () => {
  assert.deepEqual(progressCounts([{kind:'question',status:'Approved'},{kind:'handoff',status:'已完成'}]),
    {questionsDone:1,questions:1,handoffDone:1,handoff:1});
  assert.equal(questionNumber('Let us answer question 2'),2);
  assert.equal(questionNumber('第 2 題'),2);
  assert.deepEqual(splitSources('Reviewed.\nSources: Director Brief; Soul Cast').sources,['Director Brief','Soul Cast']);
});
