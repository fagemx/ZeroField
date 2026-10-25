import test from 'node:test';
import assert from 'node:assert/strict';
import {actionColumn, addBinding, codeTokens, codesElsewhere, normalizeCode, removeBinding, replaceLook, shotBindings} from '../src/bindingModel.js';

const lookup = {
  'CAST-01': {id:'CAST-01', name:'Kael', media:{kind:'image', url:'/kael.png'}},
  'CAST-01:NIGHT': {id:'CAST-01:NIGHT', name:'Night jacket', media:{kind:'image', url:'/night.png'}},
  'SET-01': {id:'SET-01', name:'Observatory', media:{kind:'image', url:'/dome.png'}},
  'PROP-01': {id:'PROP-01', name:'Reel recorder'},  // listed on the cast sheet, no picture yet
};
const sentence = '@CAST-01 turns @PROP-01 toward the open dome of @SET-01, then @PROP-01 hums.';

test('codes are found in reading order, in any case, with : or # for a look, and a bare code counts', () => {
  assert.deepEqual(codeTokens('Kael @cast-01:night and CAST-02#day, @PROP-9x. XCAST-03 @STYLE-01.').map(token => [token.code, token.at]),
    [['CAST-01:NIGHT', true], ['CAST-02:DAY', false], ['STYLE-01', true]], 'PROP-9x and XCAST-03 are not codes');
  assert.equal(normalizeCode('@cast-01#night'), 'CAST-01:NIGHT');
  assert.deepEqual(codeTokens(''), []);
  assert.deepEqual(codeTokens(null), []);
});

test('the cast of a shot lists each code once, in the order it first appears, remembering every place', () => {
  const rows = shotBindings(sentence, lookup);
  assert.deepEqual(rows.map(row => row.code), ['CAST-01', 'PROP-01', 'SET-01']);
  const recorder = rows[1];
  assert.equal(recorder.positions.length, 2, 'named twice, one row');
  assert.deepEqual(recorder.positions.map(({start, end}) => sentence.slice(start, end)), ['@PROP-01', '@PROP-01']);
  assert.deepEqual([rows[0].name, rows[0].imageUrl, rows[0].missing, rows[0].unknown], ['Kael', '/kael.png', false, false]);
  assert.deepEqual([recorder.name, recorder.imageUrl, recorder.missing, recorder.unknown], ['Reel recorder', null, true, false], 'listed but without a picture: add one');
  assert.deepEqual(shotBindings('', lookup), []);
});

test('a look resolves to its own picture, falls back to the base asset, and an unlisted code is flagged, not dropped', () => {
  const [night, day, ghost] = shotBindings('@cast-01:night then @CAST-01:DAY then @CAST-09', lookup);
  assert.deepEqual([night.code, night.base, night.look, night.imageUrl], ['CAST-01:NIGHT', 'CAST-01', 'NIGHT', '/night.png']);
  assert.deepEqual([day.look, day.imageUrl, day.unknown], ['DAY', '/kael.png', false], 'a look with no sheet row of its own shows the base picture');
  assert.deepEqual([ghost.unknown, ghost.missing, ghost.name], [true, true, 'CAST-09']);
});

test('changing a look rewrites that one code and leaves every other character as it was', () => {
  const before = 'She waits. @cast-01:night  looks up —  @PROP-01 hums.';
  const after = replaceLook(before, 'CAST-01:NIGHT', 'CAST-01');
  assert.equal(after, 'She waits. @CAST-01  looks up —  @PROP-01 hums.', 'double spaces and punctuation stay untouched');
  assert.equal(replaceLook(sentence, 'CAST-01', 'CAST-01:NIGHT'), sentence.replace('@CAST-01 ', '@CAST-01:NIGHT '));
  assert.equal(replaceLook(sentence, 'PROP-01', 'PROP-01:BROKEN').match(/PROP-01:BROKEN/g).length, 2, 'every mention of that look changes together');
  assert.equal(replaceLook('CAST-01 waits', 'CAST-01', 'CAST-01:NIGHT'), 'CAST-01:NIGHT waits', 'a code written without @ stays without @');
  assert.equal(replaceLook(sentence, 'CAST-07', 'CAST-07:X'), sentence, 'a code that is not there changes nothing');
  assert.equal(replaceLook('@CAST-01:NIGHT and @CAST-01', 'CAST-01', 'CAST-01:DAY'), '@CAST-01:NIGHT and @CAST-01:DAY', 'a look of the same asset is another code');
});

test('removing a code takes its own space with it: no double space, no space before a mark, none left at a line start', () => {
  assert.equal(removeBinding(sentence, 'SET-01'), '@CAST-01 turns @PROP-01 toward the open dome of, then @PROP-01 hums.');
  assert.equal(removeBinding('@CAST-01 turns @PROP-01 toward the dome', 'PROP-01'), '@CAST-01 turns toward the dome');
  assert.equal(removeBinding('@CAST-01 hands over @PROP-01.', 'PROP-01'), '@CAST-01 hands over.');
  assert.equal(removeBinding('@PROP-01 hums', 'PROP-01'), 'hums');
  assert.equal(removeBinding('Wide.\n@PROP-01 hums\n@SET-01 glows', 'PROP-01'), 'Wide.\nhums\n@SET-01 glows');
  assert.equal(removeBinding('Wide.\n@PROP-01', 'PROP-01'), 'Wide.\n');
  assert.equal(removeBinding(sentence, 'PROP-01'), '@CAST-01 turns toward the open dome of @SET-01, then hums.', 'both mentions go');
  assert.equal(removeBinding(sentence, 'PROP-09'), sentence);
  assert.equal(removeBinding('@CAST-01:NIGHT waits', 'CAST-01'), '@CAST-01:NIGHT waits', 'another look is another code');
  assert.equal(removeBinding(removeBinding(sentence, 'SET-01'), 'SET-01'), removeBinding(sentence, 'SET-01'), 'the same input always gives the same result');
});

test('adding a code joins the end of the sentence after one space, and naming it twice changes nothing', () => {
  assert.equal(addBinding('She waits.', 'CAST-02'), 'She waits. @CAST-02');
  assert.equal(addBinding('She waits. ', 'cast-02'), 'She waits. @CAST-02');
  assert.equal(addBinding('', 'SET-02'), '@SET-02');
  assert.equal(addBinding(sentence, 'PROP-01'), sentence);
  assert.equal(addBinding(sentence, 'CAST-01:NIGHT'), sentence + ' @CAST-01:NIGHT', 'another look of a named asset is another code');
  assert.equal(addBinding(sentence, ''), sentence);
});

test('the prompt column is "Action & Audio Prompt", else the first column that looks like a prompt', () => {
  assert.equal(actionColumn(['Shot', 'Optical Rig (Camera & Lens)', 'Camera Motion', 'Action & Audio Prompt', 'Keyframe']), 3);
  assert.equal(actionColumn(['Shot', 'Prompt', 'Notes']), 1);
  assert.equal(actionColumn(['Shot', 'Action', 'Audio Prompt']), 1);
  assert.equal(actionColumn(['Shot', 'Notes']), -1);
});

test('a code that also sits in other cells is reported with their column names, never silently ignored', () => {
  const headers = ['Shot', 'Action & Audio Prompt', 'Director Take Notes', 'Keyframe'];
  const cells = [{value:'S03'}, {value:'@CAST-01 holds @PROP-01'}, {value:'Keep @prop-01 in frame; @SET-01 stays dark'}, {value:'![Image](/a.png)'}];
  assert.deepEqual(codesElsewhere(headers, cells, 1), {'PROP-01': ['Director Take Notes'], 'SET-01': ['Director Take Notes']});
  assert.deepEqual(codesElsewhere(headers, ['S03', '@CAST-01', '', ''], 1), {});
  assert.deepEqual(codesElsewhere(headers, [{value:'@CAST-01 @CAST-01'}, {value:''}, {value:''}, {value:''}], 1), {'CAST-01': ['Shot']}, 'one column name per column');
});
