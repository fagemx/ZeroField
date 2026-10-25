import test from 'node:test';
import assert from 'node:assert/strict';
import { describing, generateKey, newLookText, orderedImages, subjectOf } from '../src/editorModel.js';

const kael = {assetId:'as_CAST-01', assetCode:'CAST-01', name:'Kael', prompt:'a courier in his thirties', selectedImageUrl:'/kael.png'};
const looks = [{assetId:'as_CAST-01:NIGHT', assetCode:'CAST-01:NIGHT', name:'Night jacket', prompt:'the same courier in a rain cape', selectedImageUrl:'/night.png'},
  {assetId:'as_CAST-01:LISTEN', assetCode:'CAST-01:LISTEN', name:'Listening', prompt:'', selectedImageUrl:null}];

test('the editor acts on the look that is picked, and on the card itself when none is or the picked one is gone', () => {
  assert.equal(subjectOf(kael, looks, 'as_CAST-01:NIGHT'), looks[0]);
  assert.equal(subjectOf(kael, looks, null), kael);
  assert.equal(subjectOf(kael, looks, 'as_CAST-01:GONE'), kael, 'a look that was deleted falls back to the card');
  assert.equal(subjectOf(kael, undefined, 'as_CAST-01:NIGHT'), kael);
});

test('the description box shows the draft of the subject in front of you, per subject, and knows when it differs from what is saved', () => {
  assert.deepEqual(describing(kael, {}), {text:'a courier in his thirties', saved:'a courier in his thirties', dirty:false});
  const drafts = {'as_CAST-01': 'a courier in his forties', 'as_CAST-01:NIGHT': 'the same courier in a rain cape'};
  assert.deepEqual(describing(kael, drafts), {text:'a courier in his forties', saved:'a courier in his thirties', dirty:true});
  assert.equal(describing(looks[0], drafts).dirty, false, 'a draft equal to what is saved is no change');
  assert.deepEqual(describing(looks[1], drafts), {text:'', saved:'', dirty:false}, 'another look is untouched by the first one\'s draft');
  assert.equal(describing(looks[1], {'as_CAST-01:LISTEN': ''}).dirty, false, 'an empty draft of an empty description is no change');
  assert.equal(describing(looks[0], {'as_CAST-01:NIGHT': ''}).dirty, true, 'clearing a description is a change');
  assert.deepEqual(describing({assetId:'x'}, {}), {text:'', saved:'', dirty:false}, 'a card with no description yet');
});

test('the generate button says what will happen: it saves a changed description first', () => {
  assert.equal(generateKey({generating:true, dirty:true}), 'world.generating', 'a picture in the making comes first');
  assert.equal(generateKey({failed:true, dirty:true}), 'world.retry');
  assert.equal(generateKey({dirty:true, hasImage:true}), 'world.saveAndGenerate');
  assert.equal(generateKey({hasImage:true}), 'world.regenerate');
  assert.equal(generateKey({}), 'world.generateHere');
});

test('a new look starts from the card\'s own description, and from nothing when it has none', () => {
  assert.equal(newLookText(kael), 'a courier in his thirties\n');
  assert.equal(newLookText({prompt:'  padded  '}), 'padded\n');
  for (const none of [{prompt:''}, {prompt:'   '}, {}, null, undefined]) assert.equal(newLookText(none), '', JSON.stringify(none));
});

test('the pictures of a subject list the main one first and the rest newest first', () => {
  const listed = [{imageId:'1', selected:false}, {imageId:'2', selected:true}, {imageId:'3', selected:false}, {imageId:'4', selected:false}];
  assert.deepEqual(orderedImages(listed).map(image => image.imageId), ['2', '4', '3', '1']);
  assert.deepEqual(orderedImages(listed.map(image => ({...image, selected:false}))).map(image => image.imageId), ['4', '3', '2', '1'], 'no main picture: newest first');
  assert.deepEqual(orderedImages([]), []);
  assert.deepEqual(orderedImages(), []);
  assert.equal(listed[0].imageId, '1', 'the list it was given is left alone');
});
