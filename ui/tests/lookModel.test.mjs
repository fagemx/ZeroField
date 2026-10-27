import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {cameraGroups, cameraChoice, cameraText, withCamera, changedGroups, moveTokens, moveOrder, moveNumbers, insertMove, removeMove, removeMoves,
  promptTokens, typingAt, replaceTyping, lookScope, withoutOverride, backToEpisodeBody, optionLabel, textureHue, LOOK_BUTTONS,
  BUTTON_KINDS, KIND_SELECTOR, SHOT_LOOK_KINDS, buttonOfKind, buttonScope, scopeBadge, overriddenKinds, setKinds, shotLookBody, resetLookBody, cameraScope,
  labelKeyOf, isAutoId, idLabel, episodeDraft, episodeLookBody, sameDraft, overrideCount, swatchColors, swatchGradient, luminance, arrangeOptions,
  carouselStart, carouselMove, eraScale} from '../src/composer/lookModel.js';
import {LOOK_OPTIONS} from './lookOptionsFixture.mjs';

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

// ---------- Package C: film setup, palette and lighting (R11, R12) ----------
const looks = LOOK_OPTIONS;

test('C1: a shot follows the episode until it overrides a kind; an episode change reaches only the shots that follow it', () => {
  const before = {genre: 'rain-mystery', palette: 'midnight-slate'}, after = {genre: 'quiet-drama', palette: 'lamp-amber'};
  const follows = {}, overrides = {palette: 'dry-ochre'};
  assert.deepEqual(lookScope('palette', after, follows), {value: 'lamp-amber', scope: 'episode'}, 'a shot without an override shows the new episode value');
  assert.deepEqual(lookScope('palette', after, overrides), {value: 'dry-ochre', scope: 'shot'}, 'an overridden shot keeps its own');
  assert.deepEqual(lookScope('genre', before, overrides), {value: 'rain-mystery', scope: 'episode'}, 'an override of one kind leaves the others with the episode');
  const film = buttonScope(BUTTON_KINDS.filmSetup, after, {tempo: 'slow-drift'});
  assert.equal(film.scope, 'shot', 'film setup says This shot as soon as one of its kinds is overridden');
  assert.deepEqual(film.kinds.map(item => [item.kind, item.value, item.scope]), [['genre', 'quiet-drama', 'episode'], ['era', null, 'auto'], ['tempo', 'slow-drift', 'shot']]);
  assert.equal(buttonScope(BUTTON_KINDS.filmSetup, after, {}).scope, 'episode');
  assert.equal(buttonScope(BUTTON_KINDS.palette, null, null).scope, 'episode', 'nothing set anywhere: the shot follows the episode (Auto)');
  assert.deepEqual(['shot', 'episode', 'auto', null].map(scopeBadge), ['shot', 'episode', 'episode', 'episode']);
  assert.deepEqual(overriddenKinds(BUTTON_KINDS.filmSetup, {genre: 'auto', palette: 'lamp-amber', era: null}), ['genre'], 'an override to Auto is still an override');
  assert.deepEqual(setKinds(BUTTON_KINDS.filmSetup, {genre: 'auto', era: 'tape-era', tempo: null}, looks), ['era'], 'the episode page dots what is not Auto');
  assert.equal(overrideCount([{look: {palette: 'dry-ochre'}}, {look: {}}, {}, {look: {light: 'low-sun'}}], ['palette']), 1);
});

test('back to the episode, Reset all and a choice are PUT /shots/{id}/look bodies with the revision the shot was read at', () => {
  assert.deepEqual(shotLookBody('palette', 'lamp-amber', 3), {palette: 'lamp-amber', baseRevision: 3});
  assert.deepEqual(shotLookBody('genre', 'auto', null), {genre: 'auto'}, 'no revision read yet: none sent');
  assert.deepEqual(resetLookBody(['palette'], {palette: 'dry-ochre', light: 'low-sun'}, 4), {palette: null, baseRevision: 4}, '"Back to the episode" for one kind');
  assert.deepEqual(resetLookBody(BUTTON_KINDS.filmSetup, {genre: 'quiet-drama', tempo: 'still-hold', palette: 'dry-ochre'}, 7), {genre: null, tempo: null, baseRevision: 7},
    'Reset all takes back every override of the wall, and only those');
  assert.deepEqual(resetLookBody(['palette'], {}, 2), {baseRevision: 2}, 'nothing overridden: nothing to take back');
  assert.deepEqual(backToEpisodeBody('light'), {light: null});
});

const HEX5 = ['#C98A3D', '#8A4B2A', '#3B2A24', '#E8C48A', '#1E1A1A'];
test('a palette is a swatch strip from its hex, the main colour first and widest', () => {
  assert.equal(swatchGradient(['#2E3A4A', '#5B6F86']), 'linear-gradient(90deg, #2E3A4A 0% 66.67%, #5B6F86 66.67% 100%)');
  assert.equal(swatchGradient(HEX5), 'linear-gradient(90deg, #C98A3D 0% 33.33%, #8A4B2A 33.33% 50%, #3B2A24 50% 66.67%, #E8C48A 66.67% 83.33%, #1E1A1A 83.33% 100%)');
  assert.deepEqual(swatchColors(['#123', 'red', '#12345', '#A1B2C3', null, 'url(x)']), ['#123', '#A1B2C3'], 'only #rgb and #rrggbb are colours');
  assert.equal(swatchGradient([]), null); assert.equal(swatchGradient(undefined), null); assert.equal(swatchGradient(['nope']), null);
  assert.ok(luminance('#000000') < luminance('#2E3A4A') && luminance('#2E3A4A') < luminance('#FFFFFF'));
  assert.equal(luminance('#fff'), luminance('#FFFFFF'));
});

test('the camera button says Episode only while the Optical Rig cell is empty and the episode has a camera', () => {
  const episode = {body: 'film-35mm', lens: 'anamorphic'};
  assert.deepEqual(cameraScope('', episode, catalog), {scope: 'episode', choice: {body: 'film-35mm', lens: 'anamorphic', aperture: 'auto-aperture', custom: false}});
  assert.equal(cameraScope('  ', episode, catalog).scope, 'episode', 'blank text is an empty cell');
  const own = cameraText({body: 'film-16mm', lens: 'auto-lens', aperture: 'f4'}, catalog);
  assert.deepEqual(cameraScope(own, episode, catalog), {scope: 'shot', choice: {body: 'film-16mm', lens: 'auto-lens', aperture: 'f4', custom: false}}, 'text in the cell is the shot\'s own');
  assert.equal(cameraScope('', null, catalog).scope, 'shot', 'no episode camera: as before');
  assert.equal(cameraScope('', {body: 'auto-body', lens: 'auto-lens', aperture: 'auto-aperture'}, catalog).scope, 'shot', 'an all-Auto episode camera is no camera');
  assert.equal(cameraScope('', {body: 'film-35mm'}, []).scope, 'episode', 'before the catalog arrives an id other than auto-* still counts');
});

test('labels, Auto and selectors by data type', () => {
  assert.equal(labelKeyOf('genre', 'rain-mystery'), 'lookCatalog.genre.rainMystery');
  assert.equal(labelKeyOf('genre', 'instrument-room-sf'), 'lookCatalog.genre.instrumentRoomSf');
  assert.equal(labelKeyOf('tempo', 'hold-then-burst'), 'lookCatalog.tempo.holdThenBurst');
  assert.equal(labelKeyOf('palette', 'auto'), 'lookCatalog.palette.auto');
  for (const [kind, list] of Object.entries(looks)) for (const item of list) assert.equal(labelKeyOf(kind, item.id), item.labelKey, item.id);
  for (const id of [null, undefined, '', 'auto', 'auto-body']) assert.ok(isAutoId(id), String(id));
  assert.ok(!isAutoId('auto-pilot', [{id: 'auto-pilot', promptText: 'x'}]), 'the catalog decides when it knows the option');
  const translate = key => ({'look.auto': 'Auto', 'lookCatalog.palette.lampAmber': 'Lamp amber'})[key] || key;
  assert.equal(idLabel('palette', 'lamp-amber', [], translate), 'Lamp amber', 'a proposal value before the catalog: its label key');
  assert.equal(idLabel('palette', 'auto', looks.palette, translate), 'Auto');
  assert.equal(idLabel('palette', 'neon-new', [], translate), 'neon-new', 'an id the interface does not know yet');
  assert.deepEqual(SHOT_LOOK_KINDS, ['genre', 'era', 'tempo', 'palette', 'light']);
  assert.deepEqual(BUTTON_KINDS.filmSetup, ['genre', 'era', 'tempo']);
  assert.deepEqual(SHOT_LOOK_KINDS.map(buttonOfKind), ['filmSetup', 'filmSetup', 'filmSetup', 'palette', 'lighting']);
  assert.deepEqual(KIND_SELECTOR, {genre: 'carousel', era: 'scale', tempo: 'carousel', palette: 'grid', light: 'grid'});
});

test('the episode page keeps a draft and sends {aspectRatio, stylePresetId, look} without Auto', () => {
  const stored = {aspectRatio: '21:9', stylePresetId: '88124', breakdownMode: 'scene', look: {genre: 'rain-mystery', camera: {body: 'film-35mm'}, palette: 'midnight-slate'}};
  const draft = episodeDraft(stored);
  assert.deepEqual(draft, {aspectRatio: '21:9', stylePresetId: '88124', look: {genre: 'rain-mystery', era: null, tempo: null, palette: 'midnight-slate', light: null,
    camera: {body: 'film-35mm', lens: null, aperture: null}}});
  assert.deepEqual(episodeLookBody({...draft, look: {...draft.look, light: 'low-sun', era: 'auto', camera: {body: 'film-35mm', lens: 'auto-lens', aperture: 'f4'}}}, stored),
    {aspectRatio: '21:9', stylePresetId: '88124', breakdownMode: 'scene', look: {genre: 'rain-mystery', palette: 'midnight-slate', light: 'low-sun', camera: {body: 'film-35mm', aperture: 'f4'}}});
  assert.deepEqual(episodeLookBody(episodeDraft({})), {aspectRatio: '16:9', stylePresetId: '88123', look: {}}, 'all Auto clears the stored look');
  assert.ok(sameDraft(draft, episodeDraft(stored)));
  assert.ok(sameDraft({...draft, look: {...draft.look, era: 'auto'}}, draft), 'choosing Auto where nothing was set changes nothing');
  assert.ok(!sameDraft({...draft, aspectRatio: '16:9'}, draft));
});

test('the card grids search and sort with Auto first; the carousel opens on the choice; the era scale keeps Auto apart', () => {
  const label = item => item.id;
  assert.deepEqual(arrangeOptions(looks.palette, {query: 'AMBER', label}).map(item => item.id), ['auto', 'lamp-amber']);
  assert.deepEqual(arrangeOptions(looks.palette, {query: 'nothing like it', label}).map(item => item.id), ['auto']);
  assert.deepEqual(arrangeOptions(looks.light, {sort: 'name', label}).map(item => item.id).slice(0, 3), ['auto', 'backlight-rim', 'hard-top']);
  const tone = arrangeOptions(looks.palette, {sort: 'tone', label}).map(item => item.id);
  assert.equal(tone[0], 'auto'); assert.equal(tone[1], 'wet-glass-neon', 'the darkest main colour first'); assert.equal(tone.at(-1), 'sea-bleached');
  assert.deepEqual(arrangeOptions(looks.genre, {label}).map(item => item.id), looks.genre.map(item => item.id), 'catalog order');
  assert.equal(carouselStart(9, 3, 0), 0); assert.equal(carouselStart(9, 3, 4), 3); assert.equal(carouselStart(9, 3, 8), 6); assert.equal(carouselStart(2, 3, 1), 0);
  assert.equal(carouselMove(9, 3, 0, -1), 0); assert.equal(carouselMove(9, 3, 5, 1), 6); assert.equal(carouselMove(9, 3, 6, 1), 6);
  const scale = eraScale(looks.era);
  assert.equal(scale.auto.id, 'auto');
  assert.deepEqual(scale.steps.map(item => item.id), ['early-lens', 'saturated-print', 'grain-film', 'tape-era', 'clean-digital'], 'oldest to newest, in table order');
});
