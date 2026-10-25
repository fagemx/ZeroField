import test from 'node:test';
import assert from 'node:assert/strict';
import { startHandOff } from '../src/storyHostModel.js';
import { textToHtml } from '../src/writing/writingModel.js';

test('a start hands its text to the right place: a screenplay to the working script, an idea or a novel to the private source of that name', () => {
  assert.deepEqual(startHandOff({mode:'script', text:'INT. DOME\nKael enters.'}), {kind:'working', text:'INT. DOME\nKael enters.'});
  assert.deepEqual(startHandOff({mode:'idea', text:'A countdown in the static.'}), {kind:'source', mode:'idea', text:'A countdown in the static.'});
  assert.deepEqual(startHandOff({mode:'novel', text:'Chapter one.'}), {kind:'source', mode:'novel', text:'Chapter one.'});
  for (const nothing of [null, undefined, {}, {mode:'idea'}, {mode:'idea', text:''}, {mode:'script', text:'  \n '}, {mode:'idea', text:42}]) {
    assert.deepEqual(startHandOff(nothing), {kind:'none'}, JSON.stringify(nothing));
  }
});

test('plain text becomes paragraphs for the editor, and never becomes markup', () => {
  assert.equal(textToHtml('One.\n\nTwo lines\nin one paragraph.\n\n\n\nThree.'), '<p>One.</p><p>Two lines<br>in one paragraph.</p><p>Three.</p>');
  assert.equal(textToHtml('Windows\r\n\r\nline endings\r\nkeep their breaks'), '<p>Windows</p><p>line endings<br>keep their breaks</p>');
  assert.equal(textToHtml('<script>alert(1)</script> & "quoted" > <b>bold</b>'), '<p>&lt;script&gt;alert(1)&lt;/script&gt; &amp; "quoted" &gt; &lt;b&gt;bold&lt;/b&gt;</p>');
  assert.equal(textToHtml(''), '');
  assert.equal(textToHtml('  \n\n  \n'), '', 'only whitespace is no paragraph at all');
  assert.equal(textToHtml(undefined), '');
});
