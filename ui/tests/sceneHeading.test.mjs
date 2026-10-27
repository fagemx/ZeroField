import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {isSceneHeading, hasSceneHeadingLine} from '../src/writing/sceneHeading.js';
import {hasSceneHeadings, needsStoryAdaptation, sourceDraft} from '../src/storyImport.js';

// The same table project_docs/scene_headings.py is tested against (tests/test_scene_headings.py).
const CASES = JSON.parse(readFileSync(new URL('../../tests/fixtures/scene_heading_cases.json', import.meta.url), 'utf8'));

test('the browser copy of the scene-heading rule gives the shared fixture answers', () => {
  for (const line of CASES.headings) assert.equal(isSceneHeading(line), true, line);
  for (const line of CASES.prose) assert.equal(isSceneHeading(line), false, line);
  assert.equal(isSceneHeading(null), false);
});

test('story import counts numbered and INT./EXT. headings on any line, never mid-line words', () => {
  const numbered = 'SPILLWAY\r\n\r\n1. INT. CONTROL ROOM - NIGHT\r\nNora waits.\r\n2. EXT. CREST - NIGHT';
  assert.equal(hasSceneHeadingLine(numbered), true);
  assert.equal(hasSceneHeadings(numbered), true);
  assert.equal(hasSceneHeadings('Nora walks into INT. territory and heads EXT. toward the road.'), false);
  assert.equal(hasSceneHeadings('Est. 1902, the dam still holds.'), false);
  assert.equal(hasSceneHeadings(''), false);
  // A pasted numbered screenplay is used as written, not sent to adaptation.
  assert.equal(needsStoryAdaptation('novel', sourceDraft(numbered)), false);
});
