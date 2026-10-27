import { useEffect, useRef } from 'react';
import { useLocale } from '../i18n/react.jsx';
import { t } from '../i18n/index.js';
import { assetVariants } from '../studioModel.js';
import { codeType } from '../bindingModel.js';
import { CameraColumns, MoveGrid } from './LookTiles.jsx';
import { optionLabel } from './lookModel.js';
import { Icon } from '../Icon.jsx';

// SPEC_19 3.3: the example wall. It covers the composer's top half, as wide as the composer; the look buttons and the prompt stay where
// they are, and pressing another look button swaps the wall's content without closing it first. A narrow column of categories on the
// left (a dot marks one that has been changed), the examples on the right; × or Esc closes it and the take comes back. A choice takes
// effect at once: there is no OK button. Ctrl+Z inside the wall undoes the last cell it wrote (the sheet's undo).
export function ExampleWall({title, categories, current, onCategory, onClose, onReset, onUndo, aside = null, children}) {
  useLocale();
  const root = useRef(null);
  useEffect(() => {root.current?.focus({preventScroll: true});}, []);
  const keys = event => {
    if (event.key === 'Escape') {event.preventDefault(); event.stopPropagation(); onClose(); return;}
    const typing = event.target.closest('input,textarea,select,[contenteditable=true]');
    if (!typing && onUndo && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z' && !event.shiftKey) {event.preventDefault(); event.stopPropagation(); onUndo();}
  };
  return <section ref={root} className="example-wall" tabIndex={-1} aria-label={title} onKeyDown={keys}>
    <header><h3>{title}</h3><span className="spacer"/>
      {onReset && <button type="button" className="quiet" onClick={onReset}>{t('look.resetAll')}</button>}
      <button type="button" className="icon-btn example-wall-close" aria-label={t('look.close')} title={t('look.close')} onClick={onClose}><Icon name="close" size={14}/></button></header>
    <div className="example-wall-body">
      <nav className="example-wall-nav" aria-label={title}>
        {categories.map(category => <button key={category.id} type="button" aria-current={current === category.id ? 'true' : undefined} onClick={() => onCategory(category.id)}>
          <span>{category.label}</span>{category.count ? <span className="num">{category.count}</span> : null}{category.dot && <i className="look-dot" aria-label={t('look.changed')}/>}</button>)}
        {aside}
      </nav>
      <div className="example-wall-main">{children}</div>
    </div>
  </section>;
}

// ---- Camera (R8): body, lens and aperture write the shot's Optical Rig column; a move goes into the prompt as a #tag at the caret.
export function CameraWall({catalog, choice, custom, numbers, order, moves, legacyMotion = '', rigColumn = true, disabled, hasPrevis = false, category, onCategory,
  onChoose, onMove, onClose, onReset, onUndo, onStage, changed = []}) {
  useLocale();
  const byId = Object.fromEntries((moves || []).map(item => [item.id, item]));
  const aside = <div className="example-wall-aside">
    {order.length > 0 && <section aria-label={t('look.moveOrder')}><h4>{t('look.moveOrder')}</h4>
      <ol>{order.map((id, index) => <li key={index}><span className="num">{index + 1}</span>{optionLabel(byId[id], t)}</li>)}</ol></section>}
    {onStage && <button type="button" className="quiet" onClick={onStage}><Icon name="cube" size={13}/>{t(hasPrevis ? 'look.stageFromPrevis' : 'look.stage')}</button>}
  </div>;
  return <ExampleWall title={t('look.camera')} current={category} onCategory={onCategory} onClose={onClose} onReset={disabled ? null : onReset} onUndo={onUndo} aside={aside}
    categories={[{id: 'rig', label: t('look.rig'), dot: changed.length > 0}, {id: 'moves', label: t('look.moves'), dot: order.length > 0, count: order.length}]}>
    {catalog.status === 'loading' && <p className="sheet-subtle" role="status">{t('look.loading')}</p>}
    {catalog.status === 'failed' && <p className="gen-error" role="alert">{t('look.failed', {message: catalog.error || ''})}</p>}
    {catalog.status === 'ready' && category === 'rig' && <>
      {!rigColumn && <p className="gen-error" role="status">{t('look.noRigColumn')}</p>}
      {custom && <p className="studio-note" role="note">{t('look.customRig')}</p>}
      <CameraColumns groups={catalog.groups} choice={choice} disabled={disabled || !rigColumn} onChoose={onChoose}/>
      <p className="studio-note">{t('look.rigHint')}</p>
    </>}
    {catalog.status === 'ready' && category === 'moves' && <>
      {!order.length && legacyMotion && <p className="studio-note" role="note">{t('look.legacyMotion', {text: legacyMotion})}</p>}
      <MoveGrid moves={moves} numbers={numbers} disabled={disabled} onToggle={onMove}/>
      <p className="studio-note">{t('look.moveHint')}</p>
    </>}
  </ExampleWall>;
}

// ---- References (R8, SPEC_18 R2): the people, places and props the prompt names, the picture of each being its example. A look can be
// changed, a code taken out, one added, a missing picture fixed; every change edits only that code in the prompt (bindingModel), the way
// SPEC_18 R2 writes it. "Other shots" (R15) quotes another shot's adopted take, and offers the shot just before as the first row.
const TYPES = ['CHARACTER', 'SCENE', 'PROP'];
const lookName = (code, lookup) => code.includes(':') ? lookup[code]?.name || code.split(':')[1].toLowerCase() : t('world.lookDefault');

function AssetTile({row, lookup, elsewhere, writable, disabled, onLook, onRemove, onFix}) {
  const found = assetVariants(row.code, lookup), looks = found.includes(row.code) ? found : [row.code, ...found];
  return <li className={'ref-tile' + (row.missing ? ' is-missing' : '') + (row.unknown ? ' is-unknown' : '')}>
    <span className="ref-picture">{row.imageUrl ? <img src={row.imageUrl} alt="" loading="lazy"/> : <Icon name={row.unknown ? 'warning' : 'image'} size={20}/>}</span>
    <span className="ref-text"><b>{row.unknown ? row.code : row.name}</b><small>@{row.code}{row.unknown ? ' · ' + t('stage.castUnknown') : row.missing ? ' · ' + t('stage.castNoImage') : ''}</small>
      {elsewhere?.[row.code] && <small className="cast-also">{t('stage.castAlsoIn', {columns: elsewhere[row.code].join(', ')})}</small>}</span>
    <span className="ref-actions">
      {!row.unknown && found.length > 1 && (writable
        ? <select aria-label={t('stage.castLook', {name: row.name})} value={row.code} disabled={disabled} onChange={event => onLook(row.code, event.target.value)}>
          {looks.map(code => <option key={code} value={code}>{lookName(code, lookup)}</option>)}</select>
        : <span className="cast-look-static">{lookName(row.code, lookup)}</span>)}
      {!row.unknown && row.missing && onFix && <button type="button" className="quiet" onClick={() => onFix(row.code)}>{t('stage.castAddRef')}</button>}
      {writable && <button type="button" className="icon-btn" aria-label={t('stage.castRemove', {code: '@' + row.code})} disabled={disabled} onClick={() => onRemove(row.code)}><Icon name="close" size={12}/></button>}
    </span>
  </li>;
}

function AddTiles({type, lookup, named, disabled, onAdd}) {
  const taken = new Set(named.map(row => row.base));
  const items = Object.values(lookup).filter(item => !item.id.includes(':') && !taken.has(item.id) && codeType(item.id) === type);
  if (!items.length) return null;
  return <section className="ref-add" aria-label={t('stage.castAddHint')}><h4>{t('stage.castAdd')}</h4>
    <ul>{items.map(item => <li key={item.id}><button type="button" disabled={disabled} onClick={() => onAdd(item.id)}>
      <span className="ref-picture is-small">{item.media?.kind === 'image' ? <img src={item.media.url} alt="" loading="lazy"/> : <Icon name="plus" size={14}/>}</span>
      <span>{item.name || item.id}<small>@{item.id}</small></span></button></li>)}</ul></section>;
}

function ShotFrame({shot}) {
  return <span className="ref-picture">{shot.selectedImageUrl ? <img src={shot.selectedImageUrl} alt="" loading="lazy"/>
    : shot.selectedVideoUrl ? <video src={shot.selectedVideoUrl + '#t=0.1'} preload="metadata" muted playsInline aria-hidden="true"/> : <Icon name="clapper" size={18}/>}</span>;
}

export function ReferenceWall({rows, more = [], lookup, elsewhere, writable, disabled, category, onCategory, onClose, onLook, onRemove, onAdd, onFix,
  shots = [], previous = null, onQuote, onContinue}) {
  useLocale();
  const of = type => rows.filter(row => codeType(row.code) === type || (row.unknown && type === 'CHARACTER' && !TYPES.includes(codeType(row.code))));
  const categories = [...TYPES.map(type => ({id: type, label: t('world.group_' + type), count: of(type).length, dot: of(type).some(row => row.missing)})),
    {id: 'shots', label: t('look.otherShots'), count: shots.length}];
  return <ExampleWall title={t('look.references')} current={category} onCategory={onCategory} onClose={onClose} categories={categories}>
    {category !== 'shots' && <>
      {of(category).length === 0 && <p className="sheet-subtle">{t('look.noneOfType')}</p>}
      <ul className="ref-grid">{of(category).map(row => <AssetTile key={row.code} row={row} lookup={lookup} elsewhere={elsewhere} writable={writable} disabled={disabled}
        onLook={onLook} onRemove={onRemove} onFix={onFix}/>)}
        {category === 'CHARACTER' && more.map(row => <li key={row.code} className="ref-tile is-elsewhere"><span className="ref-picture">{row.imageUrl ? <img src={row.imageUrl} alt="" loading="lazy"/> : <Icon name="image" size={20}/>}</span>
          <span className="ref-text"><b>{row.name}</b><small>@{row.code}</small><small className="cast-also">{t('stage.castOnlyIn', {columns: (elsewhere[row.code] || []).join(', ')})}</small></span></li>)}</ul>
      {writable && <AddTiles type={category} lookup={lookup} named={rows} disabled={disabled} onAdd={onAdd}/>}
    </>}
    {category === 'shots' && <>
      {previous && <section className="ref-continue" aria-label={t('look.continueTitle')}>
        <ShotFrame shot={previous.shot}/>
        <span className="ref-text"><b>{t('look.continueTitle')}</b><small>{t('look.continueFrom', {shot: previous.code})}</small></span>
        {writable && <span className="ref-actions">
          {(previous.use === 'first_frame' ? ['first_frame', 'reference'] : ['reference', 'first_frame']).map((use, index) =>
            <button key={use} type="button" className={index === 0 ? 'look-act' : 'quiet'} disabled={disabled} onClick={() => onContinue(use, index === 0 && previous.use === null)}>
              {t(index === 0 ? 'look.continueAs_' + use : 'look.as_' + use)}</button>)}</span>}
      </section>}
      {!shots.length && !previous && <p className="sheet-subtle">{t('look.noOtherShots')}</p>}
      <ul className="ref-grid">{shots.map(shot => <li key={shot.shotId} className="ref-tile">
        <ShotFrame shot={shot}/>
        <span className="ref-text"><b>{shot.shotIndex}</b><small>{t('take.state_adopted')}</small></span>
        {writable && <span className="ref-actions">{['end', 'start'].map(edge => <button key={edge} type="button" className="quiet" disabled={disabled}
          title={t('look.quoteHint_' + edge, {shot: shot.shotIndex})} onClick={() => onQuote(shot, edge)}>{t('look.quote_' + edge)}</button>)}</span>}
      </li>)}</ul>
      <p className="studio-note">{t('look.quoteHint')}</p>
    </>}
  </ExampleWall>;
}
