import test from 'node:test';
import assert from 'node:assert/strict';
import {mediaLadder} from '../src/studioModel.js';

const cell = value => ({value});
const sheet = (headers, types) => ({headers, table:{attrs:{column_types:types}}});
const url = path => 'https://example.org' + path;  // sheet media must be an absolute or /projects/api/ URL
const image = path => `![Image](${url(path)})`, video = path => `[video](${url(path)})`;

test('the ladder runs previs -> first frame -> video, each with its media, and only for columns the sheet has', () => {
  const parsed = sheet(['Shot', 'Action & Audio Prompt', 'Keyframe', 'Cinema Shot', 'Previs'], ['text', 'text', 'image', 'video', 'video']);
  const row = {cells:[cell('S03'), cell('@CAST-01 waits'), cell(image('/key.png')), cell(video('/take.mp4')), cell(video('/previs.mp4'))]};
  const steps = mediaLadder(parsed, row);
  assert.deepEqual(steps.map(step => [step.key, step.stage.label, step.media?.url]), [['previs', 'Previs', url('/previs.mp4')], ['frame', 'Keyframe', url('/key.png')], ['video', 'Cinema Shot', url('/take.mp4')]]);
  assert.deepEqual(steps.map(step => step.stage.column), [4, 2, 3], 'each step knows its column, so a click can open that very stage');
});

test('a sheet with a Previs column but no previs for this shot still has the step, empty; one without the column has none', () => {
  const parsed = sheet(['Shot', 'Keyframe', 'Cinema Shot', 'Previs'], ['text', 'image', 'video', 'video']);
  const steps = mediaLadder(parsed, {cells:[cell('S01'), cell(image('/k.png')), cell(''), cell('')]});
  assert.deepEqual(steps.map(step => [step.key, Boolean(step.media)]), [['previs', false], ['frame', true], ['video', false]]);
  assert.equal(steps[0].stage.column, 3);
  const plain = sheet(['Shot', 'Keyframe', 'Cinema Shot'], ['text', 'image', 'video']);
  assert.deepEqual(mediaLadder(plain, {cells:[cell('S01'), cell(''), cell('')]}).map(step => step.key), ['frame', 'video'], 'no Previs column, no previs step');
  assert.deepEqual(mediaLadder(sheet(['Shot', 'Notes'], ['text', 'text']), {cells:[cell('S01'), cell('x')]}), [], 'nothing to climb');
});

test('a source video is not a previs; the first frame is a First Frame or Keyframe image; the take is Cinema Shot, Remaster or Output', () => {
  const parsed = sheet(['Source Driving Video', 'Custom Image', 'First Frame', 'Anchor Keyframe', 'Motion Structure', 'Remastered Video'], ['video', 'image', 'image', 'image', 'video', 'video']);
  const row = {cells:[cell(video('/source.mp4')), cell(image('/custom.png')), cell(''), cell(image('/anchor.png')), cell(video('/motion.mp4')), cell(video('/remaster.mp4'))]};
  const steps = mediaLadder(parsed, row);
  assert.deepEqual(steps.map(step => step.key), ['frame', 'video'], 'the source video and the motion pass are not rungs');
  assert.equal(steps[0].stage.label, 'Anchor Keyframe', 'the first frame that has a picture is the rung; an empty First Frame does not hide it');
  assert.equal(steps[1].stage.label, 'Remastered Video');
  const none = mediaLadder(parsed, {cells:parsed.headers.map(() => cell(''))});
  assert.deepEqual(none.map(step => [step.key, step.stage.label, step.media]), [['frame', 'First Frame', null], ['video', 'Remastered Video', null]]);
});
