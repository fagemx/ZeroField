import { useState } from 'react';
import { useLocale } from './i18n/react.jsx';
import { t } from './i18n/index.js';
import { assetVariants } from './studioModel.js';
import { codeTokens, codeType, shotBindings } from './bindingModel.js';
import { Icon } from './Icon.jsx';

// SPEC_18 R2, R3: what a shot uses, shown as the people, places and props its sentence names, and that sentence with each @code drawn
// as a small tag. Every change is a new text for the prompt cell; the parent writes it through the sheet's own cell commit.
// A look that has its own name on the sheet is shown by that name; one that only names a look of the asset says which ("Kael · night").
const label = row => row.look && !row.lookNamed ? row.name + ' · ' + row.look.toLowerCase() : row.name;

function Thumb({row, size}) {
  return <span className={'binding-thumb' + (row.imageUrl ? '' : ' is-blank')} style={size ? {width:size, height:size} : undefined}>{row.imageUrl ? <img src={row.imageUrl} alt="" loading="lazy"/> : null}</span>;
}

// One code in the sentence: a button that opens its card, a plain tag when nothing can open it, or a warning when the cast sheet
// has never heard of it. A code never disappears from the text, so a typo stays visible instead of silently meaning nothing.
function CodeTag({row, onOpen}) {
  if (row.unknown) return <span className="binding-tag is-unknown" role="note"><Icon name="warning" size={12}/>{t('stage.unknownCode', {code:'@' + row.code})}</span>;
  const inner = <><Thumb row={row}/><span>{label(row)}</span></>;
  return onOpen
    ? <button type="button" className={'binding-tag' + (row.missing ? ' is-missing' : '')} title={t('stage.openAsset', {name:row.name})} onClick={() => onOpen(row.code)}>{inner}</button>
    : <span className={'binding-tag' + (row.missing ? ' is-missing' : '')}>{inner}</span>;
}

// The prompt as text with tags (read-only). lookup: buildAssetLookup()-shaped map; onOpen(code) opens the card.
export function BindingText({text, lookup, onOpen}) {
  useLocale();
  const source = String(text ?? '');
  const rows = new Map(shotBindings(source, lookup).map(row => [row.code, row]));
  const parts = [];
  let cursor = 0;
  for (const token of codeTokens(source)) {
    if (token.start > cursor) parts.push(source.slice(cursor, token.start));
    parts.push(<CodeTag key={token.start} row={rows.get(token.code)} onOpen={onOpen}/>);
    cursor = token.end;
  }
  if (cursor < source.length) parts.push(source.slice(cursor));
  return <span className="binding-text">{parts}</span>;
}

// Base codes of the cast sheet that this shot does not name yet, grouped the way the wall groups them.
const GROUPS = ['CHARACTER', 'SCENE', 'PROP'];
function candidates(lookup, named) {
  const taken = new Set(named.map(row => row.base));
  const list = Object.values(lookup).filter(item => !item.id.includes(':') && !taken.has(item.id) && GROUPS.includes(codeType(item.id)));
  return GROUPS.map(type => ({type, items:list.filter(item => codeType(item.id) === type)})).filter(group => group.items.length);
}

function AddAsset({lookup, named, onAdd, disabled}) {
  const [open, setOpen] = useState(false);
  const groups = candidates(lookup, named);
  return <div className="binding-add">
    <button type="button" className="quiet" aria-expanded={open} disabled={disabled} onClick={() => setOpen(value => !value)}><Icon name="plus" size={13}/>{t('stage.castAdd')}</button>
    {open && <div className="binding-add-list" role="group" aria-label={t('stage.castAddHint')}>
      {groups.length ? groups.map(group => <section key={group.type}><h4>{t('world.group_' + group.type)}</h4>
        <ul>{group.items.map(item => {
          const picture = item.media?.kind === 'image' ? item.media.url : null;
          return <li key={item.id}><button type="button" onClick={() => {setOpen(false); onAdd(item.id);}}>
            <Thumb row={{imageUrl:picture}}/><span>{item.name || item.id}<small>@{item.id}</small></span></button></li>;
        })}</ul></section>) : <p>{t('stage.castAddNone')}</p>}
    </div>}
  </div>;
}

// The cast block of the shot detail. rows: shotBindings() of the prompt column; elsewhere: codesElsewhere() for the other cells.
// With writable false the rows only show: no look menu, no remove, no add.
export function ShotBindings({rows, lookup, elsewhere = {}, writable, disabled, onLook, onRemove, onAdd, onOpen}) {
  useLocale();
  const named = new Set(rows.map(row => row.code));
  const only = Object.keys(elsewhere).filter(code => !named.has(code));  // named by another cell only: this block cannot take it out
  const more = shotBindings(only.map(code => '@' + code).join(' '), lookup);
  return <section className="shot-cast" aria-label={t('stage.cast')}>
    <header><h3>{t('stage.cast')}<span className="num">{rows.length + more.length}</span></h3>
      {writable && <AddAsset lookup={lookup} named={rows} onAdd={onAdd} disabled={disabled}/>}</header>
    {rows.length + more.length === 0 && <p className="space-sub">{t('stage.castEmpty')}</p>}
    <ul>
      {rows.map(row => {
        const found = assetVariants(row.code, lookup), looks = found.includes(row.code) ? found : [row.code, ...found], other = elsewhere[row.code];
        const lookName = code => code.includes(':') ? lookup[code]?.name || code.split(':')[1].toLowerCase() : t('world.lookDefault');
        return <li key={row.code} className={row.missing ? 'is-missing' : ''}>
          <Thumb row={row} size={32}/>
          <span className="cast-name"><b>{row.unknown ? row.code : row.name}</b><small>@{row.code}
            {row.unknown && <> · <em>{t('stage.castUnknown')}</em></>}
            {!row.unknown && row.missing && <> · <em>{t('stage.castNoImage')}</em></>}</small>
            {other && <small className="cast-also">{t('stage.castAlsoIn', {columns:other.join(', ')})}</small>}</span>
          {!row.unknown && found.length > 1 && (writable
            ? <select className="cast-look" aria-label={t('stage.castLook', {name:row.name})} value={row.code} disabled={disabled} onChange={event => onLook(row.code, event.target.value)}>
              {looks.map(code => <option key={code} value={code}>{lookName(code)}</option>)}</select>
            : <span className="cast-look-static">{lookName(row.code)}</span>)}
          {!row.unknown && row.missing && onOpen && <button type="button" className="cast-fix" onClick={() => onOpen(row.code)}>{t('stage.castAddRef')}</button>}
          {writable && <button type="button" className="icon-btn cast-remove" aria-label={t('stage.castRemove', {code:'@' + row.code})} disabled={disabled} onClick={() => onRemove(row.code)}><Icon name="close" size={13}/></button>}
        </li>;
      })}
      {more.map(row => <li key={row.code} className="is-elsewhere">
        <Thumb row={row} size={32}/>
        <span className="cast-name"><b>{row.unknown ? row.code : row.name}</b><small>@{row.code}</small>
          <small className="cast-also">{t('stage.castOnlyIn', {columns:elsewhere[row.code].join(', ')})}</small></span>
        {!row.unknown && row.missing && onOpen && <button type="button" className="cast-fix" onClick={() => onOpen(row.code)}>{t('stage.castAddRef')}</button>}
      </li>)}
    </ul>
  </section>;
}
