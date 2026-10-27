import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {cameraGroups, cameraChoice, cameraText, withCamera, changedGroups, moveTokens, moveOrder, moveNumbers, insertMove, removeMove, removeMoves,
  promptTokens, typingAt, replaceTyping, lookScope, withoutOverride, backToEpisodeBody, optionLabel, textureHue, LOOK_BUTTONS} from '../src/composer/lookModel.js';

// The packaged catalog the server serves at GET /catalog/looks (project_docs/look_catalog.json).
const catalog = JSON.parse(await readFile(new URL('../../project_docs/look_catalog.json', import.meta.url), 'utf8')).items;
const moves = catalog.filter(item => item.kind === 'move');
const ids = text => moveTokens(text, moves).map(token => token.id);

test('# move tags follow the server rule: whitespace or the start before, no id character after, a catalog id', () => {
  assert.deepEqual(ids('#push-in Kael turns. #pan'), ['push-in', 'pan']);
  assert.deepEqual(ids('Kael turns\n#crane-up\t#auto'), ['crane-up', 'auto']);
  assert.deepEqual(ids('他轉身 #push-in他走'), ['push-in'], 'CJK text may follow a tag');
  assert.deepEqual(ids('#pan。'), ['pan'], 'punctuation may follow a tag');
  assert.deepEqual(ids('@CAST-01#night turns'), [], 'the wardrobe form @CAST-01#night is never a move');
  assert.deepEqual(ids('@CAST-01#pan'), [], 'not even when the look has a move name');
  for (const text of ['。#pan', ']#pan', 'a#pan', '#push-inX', '#push-in_', '#push-in-', '#Pan', '#xyz', '#p', '##pan'])
    assert.deepEqual(ids(text), [], text + ' is not a move tag');
  assert.deepEqual(ids('　#pan'), ['pan'], 'an ideographic space is whitespace on both sides');
  assert.deepEqual(ids(' #pan'), ['pan']);
  assert.deepEqual(ids('﻿#pan'), [], 'U+FEFF is not whitespace to the server, even though JavaScript calls it \\s');
  assert.deepEqual(ids('\u001f#pan'), ['pan'], 'U+001F is whitespace to the server');
  assert.deepEqual(moveTokens('a #pan b', ['pan']), [{start: 2, end: 6, id: 'pan'}], 'the move ids alone are enough');
});

test('moves keep their order, and each card knows its numbers', () => {
  const text = '#push-in Kael turns. #pan then #push-in';
  assert.deepEqual(moveOrder(text, moves), ['push-in', 'pan', 'push-in']);
  assert.deepEqual(moveNumbers(text, moves), {'push-in': [1, 3], pan: [2]});
});

test('a move goes in at the caret and stays a tag', () => {
  assert.deepEqual(insertMove('Kael turns.', 4, 'pan'), {text: 'Kael #pan turns.', caret: 9});
  assert.deepEqual(insertMove('Kael turns.', 11, 'pan'), {text: 'Kael turns. #pan ', caret: 17});
  assert.deepEqual(insertMove('', 0, 'pan'), {text: '#pan ', caret: 5});
  assert.deepEqual(insertMove('他轉身他走', 3, 'push-in'), {text: '他轉身 #push-in他走', caret: 12}, 'a space before, CJK after needs none');
  assert.deepEqual(insertMove('a\nb', 2, 'pan'), {text: 'a\n#pan b', caret: 7});
  assert.deepEqual(insertMove('abc', undefined, 'pan'), {text: 'abc #pan ', caret: 9}, 'no caret: the end');
  for (const [text, caret] of [['ab', 1], ['ab', 2], ['他轉身', 1], ['@CAST-01', 8]]) assert.deepEqual(ids(insertMove(text, caret, 'pan').text), ['pan'], text);
  assert.deepEqual(ids(insertMove('#pan', 4, 'push-in').text), ['pan', 'push-in'], 'B4: a second move after the first');
  assert.deepEqual(moveNumbers(insertMove('#pan x', 0, 'push-in').text, moves), {'push-in': [1], pan: [2]}, 'B4: inserted before, numbered first');
});

test('removing a move takes its tags and one side of their spacing', () => {
  assert.equal(removeMove('Kael turns. #pan He walks.', 'pan', moves), 'Kael turns. He walks.');
  assert.equal(removeMove('#pan Kael turns.', 'pan', moves), 'Kael turns.');
  assert.equal(removeMove('Kael turns #pan。', 'pan', moves), 'Kael turns。');
  assert.equal(removeMove('a #pan b #pan', 'pan', moves), 'a b');
  assert.equal(removeMove('@CAST-01#pan stays', 'pan', moves), '@CAST-01#pan stays', 'a wardrobe code is not a move');
  assert.equal(removeMoves('#push-in a #pan b #xyz', moves), 'a b #xyz', 'an unknown #word stays as written');
});

test('the camera choice reads back from the Optical Rig text, writes the catalog descriptions and can be reset', () => {
  const groups = cameraGroups(catalog);
  assert.deepEqual(Object.keys(groups), ['body', 'lens', 'aperture']);
  assert.ok(Object.values(groups).every(list => list[0].promptText === ''), 'each group starts with Auto');
  const choice = {body: 'film-35mm', lens: 'anamorphic', aperture: 'auto-aperture'};
  const text = cameraText(choice, catalog);
  assert.equal(text, groups.body.find(item => item.id === 'film-35mm').promptText + ' ' + groups.lens.find(item => item.id === 'anamorphic').promptText);
  assert.deepEqual(cameraChoice(text, catalog), {...choice, custom: false});
  assert.deepEqual(cameraChoice('', catalog), {body: 'auto-body', lens: 'auto-lens', aperture: 'auto-aperture', custom: false});
  assert.deepEqual(cameraChoice('ARRI Alexa 65 / 35mm Anamorphic f/1.4', catalog), {body: 'auto-body', lens: 'auto-lens', aperture: 'auto-aperture', custom: true}, 'an older preset is custom text');
  assert.equal(cameraText(withCamera(choice, 'lens', 'auto-lens'), catalog), groups.body.find(item => item.id === 'film-35mm').promptText);
  assert.equal(cameraText({body: 'auto-body', lens: 'auto-lens', aperture: 'auto-aperture'}, catalog), '', 'all Auto is the empty rig');
  assert.deepEqual(changedGroups(choice, catalog), ['body', 'lens']);
});

test('the editor draws @assets, #moves and take references as tags without overlap, and knows what is being typed', () => {
  const text = '@CAST-01:night turns @PROP-01 #push-in toward CAST-02 @SC01-S02.end @CAST-01#night #xyz';
  assert.deepEqual(promptTokens(text, {moves}).map(token => [token.kind, token.text]),
    [['asset', '@CAST-01:night'], ['asset', '@PROP-01'], ['move', '#push-in'], ['take', '@SC01-S02.end'], ['asset', '@CAST-01#night']]);
  assert.deepEqual(typingAt('Kael meets @ca', 14), {trigger: '@', start: 11, query: 'ca'});
  assert.deepEqual(typingAt('他把@', 3), {trigger: '@', start: 2, query: ''});
  assert.equal(typingAt('mail@x', 6), null, 'an @ after a word character is not a mention');
  assert.deepEqual(typingAt('turns #pu', 9), {trigger: '#', start: 6, query: 'pu'});
  assert.equal(typingAt('@CAST-01#ni', 11).trigger, '@', 'a wardrobe look is part of the code');
  assert.equal(typingAt('a。#pu', 5), null, 'no move menu where no move tag can stand');
  const typing = typingAt('Kael meets @ca now', 14);
  assert.deepEqual(replaceTyping('Kael meets @ca now', typing, 14, '@CAST-02'), {text: 'Kael meets @CAST-02 now', caret: 19});
  assert.deepEqual(replaceTyping('#pu', typingAt('#pu', 3), 3, '#push-in'), {text: '#push-in ', caret: 9});
});

test('package C reads an episode look and a shot override, and goes back to the episode', () => {
  assert.deepEqual(lookScope('palette', {palette: 'dusk-fable'}, null), {value: 'dusk-fable', scope: 'episode'});
  assert.deepEqual(lookScope('palette', {palette: 'dusk-fable'}, {palette: 'dry-ochre'}), {value: 'dry-ochre', scope: 'shot'});
  assert.deepEqual(lookScope('light', {palette: 'dusk-fable'}, {light: null}), {value: null, scope: 'auto'});
  assert.deepEqual(withoutOverride({palette: 'dry-ochre', light: 'window'}, 'palette'), {light: 'window'});
  assert.deepEqual(backToEpisodeBody('palette'), {palette: null});
  assert.deepEqual(LOOK_BUTTONS, ['references', 'filmSetup', 'camera', 'palette', 'lighting']);
});

test('an option is labelled by its key, else its id; an option with no media gets a stable texture hue', () => {
  const translate = key => ({'lookCatalog.move.pan': 'Pan'})[key] || key;
  assert.equal(optionLabel({id: 'pan', labelKey: 'lookCatalog.move.pan'}, translate), 'Pan');
  assert.equal(optionLabel({id: 'new-move', labelKey: 'lookCatalog.move.newMove'}, translate), 'new-move');
  assert.equal(textureHue('pan'), textureHue('pan'));
  assert.ok(textureHue('pan') >= 0 && textureHue('pan') < 360);
});
