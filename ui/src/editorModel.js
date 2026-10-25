// SPEC_18 R12, revised again: the card in front of you is a character (or a set, or a prop) with one description, several looks and several
// pictures. What the editor shows and acts on is the look you picked, or the card itself when no look is picked.
export const subjectOf = (item, looks = [], lookId = null) => looks.find(look => look.assetId === lookId) || item;

// The description box: what is in it, and whether that differs from what is saved. A draft is kept per subject, so moving between looks
// loses nothing that was typed.
export function describing(subject, drafts = {}) {
  const saved = subject.prompt || '';
  const text = drafts[subject.assetId] ?? saved;
  return {text, saved, dirty: text !== saved};
}

// What the generate button says. A changed description is saved first, so what is in the box is what gets made.
export function generateKey({generating = false, failed = false, dirty = false, hasImage = false}) {
  if (generating) return 'world.generating';
  if (failed) return 'world.retry';
  if (dirty) return 'world.saveAndGenerate';
  return hasImage ? 'world.regenerate' : 'world.generateHere';
}

// A new look starts from the character's own description (the same person in other clothes); the person writes what changes.
export const newLookText = item => item?.prompt?.trim() ? item.prompt.trim() + '\n' : '';

// The pictures of one subject: the main one first, then the rest newest first (the server lists them oldest first).
export const orderedImages = (images = []) => [...images.filter(image => image.selected), ...images.filter(image => !image.selected).reverse()];
