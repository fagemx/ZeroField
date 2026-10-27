import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useLocale } from '../i18n/react.jsx';
import { t } from '../i18n/index.js';
import { codeType } from '../bindingModel.js';
import { promptTokens, replaceTyping, typingAt, optionLabel } from './lookModel.js';
import { Icon } from '../Icon.jsx';

// SPEC_19 R9: the shot's prompt, the biggest box on the screen. It edits the Action & Audio Prompt column in place: no Edit button;
// Enter is a new line, Ctrl+Enter saves. @ opens the cast, sets and props, # the camera moves; both are drawn as tags inside the text,
// and so is a take reference (@SC01-S02.end, R15) with the frame it quotes. A code the cast sheet does not know is a warning tag
// (SPEC_18 R3); a reference to a shot with nothing adopted is a warning too. The text is the truth: a tag is the characters it stands
// for, so what is saved is exactly what was typed (and an unknown #word or code is never dropped).
//
// The box is a contenteditable whose HTML is drawn from the text on every change (tags are atomic, contenteditable=false spans that
// carry their characters in data-token). After each change the caret is put back at the same place in the text. The box keeps its own
// undo (Ctrl+Z / Ctrl+Shift+Z), since redrawing it drops the browser's.

const escapeHtml = value => String(value).replace(/[&<>"]/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'})[char]);

// The text as the box's HTML. decorate(token) -> {cls, title, label, thumb: {kind, url, at} | null}.
export function promptHtml(text, tokens, decorate) {
  const source = String(text ?? '');
  let html = '', cursor = 0;
  for (const token of tokens) {
    html += escapeHtml(source.slice(cursor, token.start));
    const look = decorate(token);
    const thumb = look.thumb?.kind === 'image' ? `<img class="pc-thumb" src="${escapeHtml(look.thumb.url)}" alt="">`
      : look.thumb?.kind === 'video' ? `<video class="pc-thumb" src="${escapeHtml(look.thumb.url)}#t=${Math.max(Number(look.thumb.at) || 0, 0.1)}" preload="metadata" muted playsinline aria-hidden="true"></video>`
        : look.icon ? `<span class="pc-icon" aria-hidden="true">${escapeHtml(look.icon)}</span>` : '';
    html += `<span class="pc-tag ${look.cls}" contenteditable="false" data-token="${escapeHtml(token.text)}" data-kind="${token.kind}"${token.key ? ` data-key="${escapeHtml(token.key)}"` : ''}`
      + ` title="${escapeHtml(look.title || token.text)}">${thumb}<span class="pc-label">${escapeHtml(look.label)}</span></span>`;
    cursor = token.end;
  }
  html += escapeHtml(source.slice(cursor));
  if (source.endsWith('\n')) html += '<br data-tail="1">';  // the empty last line needs something to stand on
  return html;
}

// The text the box holds now: text nodes as they are, a tag as its characters, a <br> as a new line (the drawn tail <br> is not one).
function serialize(node) {
  let out = '';
  const walk = parent => {
    for (const child of parent.childNodes) {
      if (child.nodeType === 3) out += child.nodeValue;
      else if (child.nodeType === 1) {
        if (child.dataset?.token != null) out += child.dataset.token;
        else if (child.tagName === 'BR') { if (!child.dataset?.tail) out += '\n'; }
        else if (/^(DIV|P)$/.test(child.tagName)) { if (out && !out.endsWith('\n')) out += '\n'; walk(child); }
        else walk(child);
      }
    }
  };
  walk(node);
  return out;
}
const textOf = root => (root.childNodes.length === 1 && root.firstChild.tagName === 'BR' ? '' : serialize(root));

// Where the selection starts and ends, as offsets into the text (null when it is not in the box).
function selectionOffsets(root) {
  const selection = root.ownerDocument.getSelection();
  if (!selection?.rangeCount) return null;
  const range = selection.getRangeAt(0);
  if (!root.contains(range.startContainer) || !root.contains(range.endContainer)) return null;
  const upTo = (container, offset) => {
    const part = root.ownerDocument.createRange();
    part.selectNodeContents(root); part.setEnd(container, offset);
    const box = root.ownerDocument.createElement('div');
    box.append(part.cloneContents());
    return serialize(box).length;
  };
  return {start: upTo(range.startContainer, range.startOffset), end: upTo(range.endContainer, range.endOffset)};
}
// Puts the caret at an offset of the text (after a tag when the offset falls inside one).
function placeCaret(root, offset) {
  const doc = root.ownerDocument, range = doc.createRange();
  let left = Math.max(0, offset), placed = false;
  for (const node of root.childNodes) {
    const length = node.nodeType === 3 ? node.nodeValue.length : node.dataset?.token != null ? node.dataset.token.length : node.tagName === 'BR' && !node.dataset?.tail ? 1 : 0;
    if (left <= length && (node.nodeType === 3 || length > 0)) {
      if (node.nodeType === 3) range.setStart(node, left);
      else if (left === 0) range.setStartBefore(node);
      else range.setStartAfter(node);
      placed = true;
      break;
    }
    left -= length;
  }
  if (!placed) { range.selectNodeContents(root); range.collapse(false); } else range.collapse(true);
  const selection = doc.getSelection();
  selection.removeAllRanges(); selection.addRange(range);
}

// The @ / # menu's entries for what is being typed.
//   assets: buildAssetLookup()-shaped map; moves: catalog move options; shots: other shots that can be quoted ({shotIndex, ...}).
export function menuEntries(typing, {assets = {}, moves = [], shots = []} = {}) {
  if (!typing) return [];
  const query = typing.query.toLowerCase();
  if (typing.trigger === '#') {
    return moves.filter(item => !query || item.id.includes(query) || optionLabel(item, t).toLowerCase().includes(query)).slice(0, 12)
      .map(item => ({id: item.id, token: '#' + item.id, label: optionLabel(item, t), hint: '#' + item.id, kind: 'move'}));
  }
  const cast = Object.values(assets).filter(item => ['CHARACTER', 'SCENE', 'PROP'].includes(codeType(item.id)))
    .filter(item => !query || item.id.toLowerCase().includes(query) || (item.name || '').toLowerCase().includes(query))
    .map(item => ({id: item.id, token: '@' + item.id, label: item.name || item.id, hint: '@' + item.id, kind: 'asset', group: codeType(item.id),
      image: item.media?.kind === 'image' ? item.media.url : null}));
  const quoted = query ? shots.filter(shot => String(shot.shotIndex).toLowerCase().startsWith(query.split('.')[0])).flatMap(shot => ['end', 'start']
    .map(edge => ({id: shot.shotId + edge, token: `@${shot.shotIndex}.${edge}`, label: t('composer.quoteEntry_' + edge, {shot: shot.shotIndex}), hint: `@${shot.shotIndex}.${edge}`, kind: 'take',
      image: shot.selectedImageUrl || null}))) : [];
  return [...cast, ...quoted].slice(0, 14);
}

// The editor. value: the text shown (the draft, else the cell); onChange(text) every change; onSave() on Ctrl+Enter.
//   decorate(token): how a tag looks. menus: {assets, moves, shots} for @ and #. onTag(token, element): a tag was clicked.
//   api: a ref the composer uses to insert at the caret ({insert(fn), focus(), caret()}).
export function PromptEditor({rid, value, onChange, onSave, editable = true, moves = [], decorate, menus = {}, onTag, api, placeholder, label}) {
  useLocale();
  const root = useRef(null), caret = useRef(null), last = useRef(null), composing = useRef(false);
  const history = useRef({past: [], future: [], at: 0});
  const [menu, setMenu] = useState(null);
  const tokens = useMemo(() => promptTokens(value, {moves}), [value, moves]);
  const html = useMemo(() => promptHtml(value, tokens, decorate), [value, tokens, decorate]);
  useEffect(() => {history.current = {past: [], future: [], at: 0}; last.current = null; setMenu(null);}, [rid]);
  // The HTML was redrawn: the caret goes back where the text says it was.
  useLayoutEffect(() => {
    const box = root.current;
    if (box && caret.current !== null && box.ownerDocument.activeElement === box) placeCaret(box, caret.current);
  }, [html]);
  const lastCaret = () => last.current ?? String(value).length;
  const remember = () => {const box = root.current; const at = box && selectionOffsets(box); if (at) last.current = at.end;};
  const commit = (next, at, {coalesce = false} = {}) => {
    const stack = history.current, now = Date.now();
    if (!(coalesce && now - stack.at < 700 && stack.past.length)) stack.past.push({value: String(value), caret: lastCaret()});
    if (stack.past.length > 100) stack.past.shift();
    stack.future = []; stack.at = now;
    caret.current = at; last.current = at;
    onChange(next);
  };
  const travel = direction => {
    const stack = history.current, from = direction === 'undo' ? stack.past : stack.future, to = direction === 'undo' ? stack.future : stack.past;
    const step = from.pop();
    if (!step) return;
    to.push({value: String(value), caret: lastCaret()});
    caret.current = step.caret; last.current = step.caret; stack.at = 0;
    onChange(step.value);
  };
  const updateMenu = (text, at) => {
    const typing = typingAt(text, at), entries = menuEntries(typing, menus);
    setMenu(typing && entries.length ? {typing, entries, index: 0, at} : null);
  };
  const read = () => {
    const box = root.current;
    if (!box || composing.current) return;
    const next = textOf(box), at = selectionOffsets(box)?.end ?? next.length;
    if (next === value) { last.current = at; return; }
    commit(next, at, {coalesce: true});
    updateMenu(next, at);
  };
  const replaceSelection = text => {
    const box = root.current, at = (box && selectionOffsets(box)) || {start: lastCaret(), end: lastCaret()}, source = String(value);
    const next = source.slice(0, at.start) + text + source.slice(at.end);
    commit(next, at.start + text.length);
    return at.start + text.length;
  };
  const choose = entry => {
    if (!menu) return;
    const {text, caret: at} = replaceTyping(value, menu.typing, menu.at, entry.token);
    setMenu(null);
    commit(text, at);
    root.current?.focus();
  };
  if (api) api.current = {
    caret: lastCaret,
    focus: () => root.current?.focus(),
    // fn(text, caret) -> {text, caret}: an insertion made from outside the box (a move from the wall, a quoted take, @ or # buttons).
    insert(fn, {openMenu = false} = {}) {
      const result = fn(String(value), lastCaret());
      if (!result || result.text === value) return;
      commit(result.text, result.caret);
      root.current?.focus();
      if (openMenu) updateMenu(result.text, result.caret);
    },
  };
  const keys = event => {
    if (composing.current || event.nativeEvent.isComposing || event.keyCode === 229) return;
    const mod = event.ctrlKey || event.metaKey, key = event.key;
    if (menu) {
      if (key === 'ArrowDown' || key === 'ArrowUp') {event.preventDefault(); setMenu(old => ({...old, index: (old.index + (key === 'ArrowDown' ? 1 : -1) + old.entries.length) % old.entries.length})); return;}
      if ((key === 'Enter' && !mod) || key === 'Tab') {event.preventDefault(); choose(menu.entries[menu.index]); return;}
      if (key === 'Escape') {event.preventDefault(); event.stopPropagation(); setMenu(null); return;}
    }
    if (key === 'Enter' && mod) {event.preventDefault(); onSave?.(); return;}
    if (key === 'Enter') {event.preventDefault(); replaceSelection('\n'); setMenu(null); return;}
    if (mod && key.toLowerCase() === 'z') {event.preventDefault(); travel(event.shiftKey ? 'redo' : 'undo'); return;}
    if (mod && key.toLowerCase() === 'y') {event.preventDefault(); travel('redo');}
  };
  const position = menu && (() => {
    const box = root.current, selection = box?.ownerDocument.getSelection();
    if (!box || !selection?.rangeCount) return {left: 12, top: 28};
    const rect = selection.getRangeAt(0).getBoundingClientRect(), frame = box.parentElement.getBoundingClientRect();
    return rect.width || rect.height ? {left: Math.max(4, rect.left - frame.left), top: rect.bottom - frame.top + 4} : {left: 12, top: 28};
  })();
  return <div className="pc-field">
    <div ref={root} className="pc-editor" role="textbox" aria-multiline="true" aria-label={label} data-shot-prompt={rid} data-empty={value === '' ? 'true' : undefined}
      data-placeholder={placeholder} contentEditable={editable ? 'true' : 'false'} suppressContentEditableWarning spellCheck={false} tabIndex={0}
      dangerouslySetInnerHTML={{__html: html}}
      onInput={read} onKeyDown={keys} onKeyUp={event => {if (!['Shift', 'Control', 'Meta', 'Alt'].includes(event.key)) remember();}}
      onMouseUp={remember} onBlur={() => {remember(); setMenu(null);}}
      onCompositionStart={() => {composing.current = true;}} onCompositionEnd={() => {composing.current = false; read();}}
      onPaste={event => {if (!editable) return; event.preventDefault(); replaceSelection(event.clipboardData.getData('text/plain').replace(/\r\n?/g, '\n'));}}
      onDrop={event => event.preventDefault()}
      onClick={event => {const tag = event.target.closest?.('[data-token]'); if (tag) onTag?.({kind: tag.dataset.kind, token: tag.dataset.token, key: tag.dataset.key || null}, tag);}}/>
    {menu && <ul className="pc-menu" role="listbox" aria-label={t(menu.typing.trigger === '#' ? 'composer.menuMoves' : 'composer.menuCast')} style={position}>
      {menu.entries.map((entry, index) => <li key={entry.id} role="option" aria-selected={index === menu.index}
        onMouseDown={event => {event.preventDefault(); choose(entry);}} onMouseEnter={() => setMenu(old => ({...old, index}))}>
        <span className="pc-menu-thumb">{entry.image ? <img src={entry.image} alt="" loading="lazy"/> : <Icon name={entry.kind === 'move' ? 'expand' : entry.kind === 'take' ? 'clapper' : 'image'} size={13}/>}</span>
        <span>{entry.label}</span><small>{entry.hint}</small></li>)}
    </ul>}
  </div>;
}
