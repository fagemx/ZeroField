import test from 'node:test';
import assert from 'node:assert/strict';
import { isPaletteKey, passesToShell, spaceKey } from '../src/shellShortcuts.js';

const key = (name, init = {}) => ({ key: name, ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, ...init });

test('Ctrl or Cmd K is the command palette, whatever the case of the letter', () => {
  assert.equal(isPaletteKey(key('k', { ctrlKey: true })), true);
  assert.equal(isPaletteKey(key('K', { metaKey: true })), true);
  assert.equal(isPaletteKey(key('k')), false);
  assert.equal(isPaletteKey({ ctrlKey: true }), false, 'a key event without a key (an autofill) is not a shortcut');
});

test('Ctrl, Cmd or Alt with 1, 2 or 3 picks the space at that position; Shift or other digits do not', () => {
  assert.equal(spaceKey(key('1', { altKey: true })), 0);
  assert.equal(spaceKey(key('2', { ctrlKey: true })), 1);
  assert.equal(spaceKey(key('3', { metaKey: true })), 2);
  assert.equal(spaceKey(key('2', { altKey: true, shiftKey: true })), -1);
  assert.equal(spaceKey(key('4', { altKey: true })), -1);
  assert.equal(spaceKey(key('2')), -1);
});

test('a hosted editor lets the shell shortcuts through and keeps everything else, Ctrl+Alt+digit headings included', () => {
  assert.equal(passesToShell(key('k', { ctrlKey: true })), true);
  assert.equal(passesToShell(key('2', { altKey: true })), true);
  assert.equal(passesToShell(key('3', { ctrlKey: true })), true);
  assert.equal(passesToShell(key('1', { ctrlKey: true, altKey: true })), false, 'Ctrl+Alt+1 is the editor\'s heading key');
  assert.equal(passesToShell(key('g')), false, 'typing is never a shell shortcut');
  assert.equal(passesToShell(key('s', { ctrlKey: true })), false, 'save belongs to the workspace');
});
