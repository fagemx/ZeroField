// The studio's keyboard shortcuts, defined once: the shell (App) acts on them, and an editor hosted inside a space lets them through.
// Ctrl/Cmd+K opens the command palette.
export const isPaletteKey = event => (event.ctrlKey || event.metaKey) && String(event.key || '').toLowerCase() === 'k';
// Ctrl/Cmd/Alt + 1·2·3 pick a space (a browser may keep Ctrl+digit for its own tabs, so Alt+digit works too); -1 when it is not one.
export const spaceKey = event => (/^[1-3]$/.test(event.key || '') && (event.ctrlKey || event.metaKey || event.altKey) && !event.shiftKey ? Number(event.key) - 1 : -1);
// What a hosted editor must not swallow. Ctrl+Alt+1·2·3 stay the editor's own heading keys, so those are not the shell's here.
export const passesToShell = event => (isPaletteKey(event) || spaceKey(event) >= 0) && !((event.ctrlKey || event.metaKey) && event.altKey);
