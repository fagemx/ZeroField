// A sheet row opened from outside the stage is also the shell's shot focus, and the Timeline's "use this take" adopts it (SPEC_19 R1).
// Source-level, like the other shell checks: App.jsx and Timeline.jsx are too wired up to mount without the whole project.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const uiRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const app = await readFile(join(uiRoot, 'src/App.jsx'), 'utf8');
const timeline = await readFile(join(uiRoot, 'src/Timeline.jsx'), 'utf8');

// The text from the first `start` match up to the next `end` match after it, so a call site is read in its own block.
const between = (source, start, end) => {
  const from = source.search(start);
  assert.ok(from >= 0, `found ${start}`);
  const rest = source.slice(from);
  const to = rest.slice(1).search(end);
  assert.ok(to >= 0, `found ${end} after ${start}`);
  return rest.slice(0, to + 1);
};

test('focusStageRow sets the shell shot focus for a stage row only', () => {
  const helper = app.match(/const focusStageRow = useCallback\((.*?), \[setFocus\]\);/s)?.[1];
  assert.ok(helper, 'a helper next to setFocus');
  const calls = [];
  const spaceOf = key => ({ 'cinema-studio': 'stage', 'openjutsu-lab': 'stage', 'soul-cast': 'story' })[key] || null;
  const focusStageRow = new Function('spaceOf', 'setFocus', `return ${helper};`)(spaceOf, patch => calls.push(patch));
  focusStageRow('cinema-studio', 'b2');
  focusStageRow('openjutsu-lab', 'b3');
  focusStageRow('soul-cast', 'b4');
  focusStageRow('director-brief', 'b5');
  focusStageRow('cinema-studio', undefined);
  assert.deepEqual(calls, [{ shotRid: 'b2' }, { shotRid: 'b3' }], 'story pages and a missing row id leave the focus alone');
  assert.match(helper, /spaceOf\(tab\) === 'stage'/, 'the same stage test as the restored context');
});

test('opening an annotation on a stage row also sets the shell shot focus', () => {
  const pick = between(app, /const pick = useCallback\(/, /\n  const reattach = /);
  assert.match(pick, /setSheetFocus\(\{tabKey:a\.tab_key,tableId:a\.anchor\.table_id,rowId:a\.anchor\.rid[^}]*\}\);\s*focusStageRow\(a\.tab_key, a\.anchor\.rid\);/);
  assert.match(pick, /\}, \[[^\]]*focusStageRow[^\]]*\]\);\s*$/, 'a dependency of the callback');
});

test('restoring the production context after a Console refresh sets the shell shot focus', () => {
  const restore = between(app, /A Console refresh keeps the production context/, /const paInput = /);
  assert.match(restore, /setSheetFocus\(\{\.\.\.saved\.focus,nonce:Date\.now\(\)\}\);focusStageRow\(saved\.focus\.tabKey,saved\.focus\.rowId\);/);
});

test('opening a proposal target sets the shell shot focus after the sheet focus', () => {
  const open = between(app, /const openFromAssistant = useCallback\(/, /const starter = /);
  assert.match(open, /setSheetFocus\(\{ tabKey: target\.tab_key, tableId, rowId: target\.row_id[\s\S]*?\}\);\s*focusStageRow\(target\.tab_key, target\.row_id\);/);
  assert.match(open, /\}, \[[^\]]*focusStageRow[^\]]*\]\);\s*$/, 'a dependency of the callback');
});

test('a flow source link sets the shell shot focus after the sheet focus', () => {
  const link = between(app, /onOpenSource=\{async \(target\) =>/, /values=\{data\.values\[tabKey\]\}/);
  assert.match(link, /setSheetFocus\(\{ \.\.\.target, nonce: Date\.now\(\) \}\);\s*focusStageRow\(target\.tabKey, target\.rowId\);/);
});

test('every row-opening setSheetFocus in the shell is paired with the shell shot focus', () => {
  const opens = [...app.matchAll(/\bsetSheetFocus\(\{/g)].map(match => match.index);
  assert.equal(opens.length, 4, 'a fifth place that opens a sheet row needs the same pairing and a test above');
  for (const at of opens) {
    const next = app.indexOf('focusStageRow(', at);
    assert.ok(next > at && next - at < 400, `focusStageRow follows the setSheetFocus at offset ${at}`);
    assert.ok(!app.slice(at + 1, next).includes('setSheetFocus('), 'and comes before the next one');
  }
});

test('the Timeline uses a take by adopting it, not with selected-video', () => {
  const use = timeline.match(/const useTake = async take => \{[\s\S]*?\n  \};/)?.[0] || '';
  assert.match(use, /storyRequest\(`\/shots\/\$\{selected\.shotId\}\/adoptions`, 'POST', \{videoId: take\.videoId\}\)/);
  assert.match(use, /onChanged\?\.\(\)/, 'the shots reload after the swap');
  assert.match(use, /catch \(failure\) \{setError\(failure\.message\);\}/, 'a refusal is shown');
  assert.doesNotMatch(timeline, /selected-video|'PUT', \{videoId/, 'no PUT selected-video left in the timeline');
});
