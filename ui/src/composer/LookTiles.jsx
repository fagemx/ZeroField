import { useState } from 'react';
import { useLocale } from '../i18n/react.jsx';
import { t } from '../i18n/index.js';
import { CAMERA_GROUPS, arrangeOptions, carouselMove, carouselStart, eraScale, optionLabel, scopeBadge, swatchGradient, textureHue } from './lookModel.js';
import { Icon } from '../Icon.jsx';

// SPEC_19 3.3: the look buttons under the composer's top half and the example tiles of its walls.
//   A look button: a small picture, the category, "This shot" / "Episode", and the current value (cut short; the full value on hover).
//   A tile: a 16:9 example. It shows its poster and plays its clip only while the pointer rests on it (one tile at a time, so one video,
//   1.2 I); an option without example media is an abstract texture told apart by colour, never a picture of something it is not, and
//   Auto is its own texture. A palette shows its own colours (a swatch strip). The chosen tile has the amber outline; a move chosen
//   more than once shows each of its places in the order.

// The texture of an option with no example media (and of Auto). bare: no word on it (a button's small picture).
export function LookTexture({id, auto = false, label = '', bare = false}) {
  return <span className={'look-texture' + (auto ? ' is-auto' : '')} style={auto ? undefined : {'--look-hue': textureHue(id)}} aria-hidden="true">
    {auto && !bare && <b>{label || 'Auto'}</b>}</span>;
}
// A palette's colours, the main one widest.
export function Swatch({hex, strip = false}) {
  const background = swatchGradient(hex);
  return background ? <span className={'look-swatch' + (strip ? ' is-strip' : '')} style={{background}} aria-hidden="true"/> : null;
}

function TileMedia({item, auto, label, active}) {
  const poster = item?.preview?.poster || null, clip = item?.preview?.clip || null, hex = Array.isArray(item?.hex) && item.hex.length ? item.hex : null;
  if (auto) return <LookTexture id={item?.id} auto label={label}/>;
  if (!poster && !clip) return hex ? <Swatch hex={hex}/> : <LookTexture id={item?.id}/>;
  return <>
    {poster ? <img src={poster} alt="" loading="lazy"/> : hex ? <Swatch hex={hex}/> : <LookTexture id={item.id}/>}
    {active && clip && <video src={clip} autoPlay muted loop playsInline preload="auto" aria-hidden="true"/>}
    {hex && poster && <Swatch hex={hex} strip/>}
  </>;
}

// One example. numbers: the places this option holds in the shot's order (moves), shown in the corner; flag: a word in the other
// corner (the option a crew proposal suggests).
export function LookTile({item, selected = false, numbers = [], disabled = false, small = false, flag = '', onClick}) {
  useLocale();
  const [hover, setHover] = useState(false);
  const auto = !item?.promptText, label = auto ? t('look.auto') : optionLabel(item, t);
  return <button type="button" className={'look-tile' + (selected ? ' is-selected' : '') + (small ? ' is-small' : '')} aria-pressed={selected} disabled={disabled}
    title={item?.promptText || t('look.autoHint')} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)} onFocus={() => setHover(true)} onBlur={() => setHover(false)}
    onClick={() => onClick?.(item)}>
    <span className="look-frame"><TileMedia item={item} auto={auto} label={t('look.auto')} active={hover}/>
      {numbers.length > 0 && <span className="look-order" aria-label={t('look.order', {numbers:numbers.join(', ')})}>{numbers.join('·')}</span>}
      {flag && <span className="look-flag">{flag}</span>}</span>
    <span className="look-name">{label}</span>
  </button>;
}

// Body, lens and aperture: three columns, one choice each, each column scrolling on its own (3.3).
export function CameraColumns({groups, choice, disabled = false, onChoose}) {
  useLocale();
  return <div className="look-columns">
    {CAMERA_GROUPS.map(group => <section key={group} className="look-column" aria-label={t('look.group_' + group)}>
      <h4>{t('look.group_' + group)}</h4>
      <div className="look-column-list">{(groups[group] || []).map(item => <LookTile key={item.id} item={item} small selected={choice?.[group] === item.id} disabled={disabled}
        onClick={() => onChoose(group, item.id)}/>)}</div>
    </section>)}
  </div>;
}

// The moves: a card grid; a press adds the move at the prompt's caret, or takes a chosen one out.
export function MoveGrid({moves, numbers = {}, disabled = false, onToggle}) {
  useLocale();
  return <div className="look-grid">{moves.map(item => <LookTile key={item.id} item={item} selected={Boolean(numbers[item.id])} numbers={numbers[item.id] || []} disabled={disabled}
    onClick={() => onToggle(item)}/>)}</div>;
}

// The look buttons (lookModel LOOK_BUTTONS): references, film setup, camera, palette, lighting.
//   buttons: [{id, label, scope: 'shot' | 'episode' | 'auto' | null, value, full, thumb (an image url), swatch (hex), texture ({id, auto}),
//   icon, dot (a missing picture), proposed (a crew proposal waits for it), badge}]. A shot that sets nothing follows the episode, so
//   scope 'auto' reads "Episode".
export function LookButtons({buttons, open = null, onOpen}) {
  useLocale();
  return <div className="look-buttons" role="toolbar" aria-label={t('look.buttons')}>
    {buttons.map(button => <button key={button.id} type="button" className={'look-button' + (open === button.id ? ' is-open' : '')} aria-expanded={open === button.id}
      title={[button.label, button.full || button.value, button.proposed && t('look.proposalWaiting')].filter(Boolean).join(' · ')} onClick={() => onOpen(open === button.id ? null : button.id)}>
      <span className="look-button-thumb">{button.thumb ? <img src={button.thumb} alt="" loading="lazy"/> : button.swatch?.length ? <Swatch hex={button.swatch}/>
        : button.texture ? <LookTexture id={button.texture.id} auto={button.texture.auto} bare/> : <Icon name={button.icon || 'image'} size={14}/>}
        {button.dot && <i className="look-dot" aria-hidden="true"/>}{button.proposed && <i className="look-dot is-proposal" aria-hidden="true"/>}</span>
      <span className="look-button-text"><span className="look-button-head"><b>{button.label}</b>{button.scope && <em className={'look-scope is-' + scopeBadge(button.scope)}>{t('look.' + scopeBadge(button.scope))}</em>}
        {button.badge && <em className="look-scope">{button.badge}</em>}</span>
        <small>{button.value || t('look.auto')}</small></span>
    </button>)}
  </div>;
}

// ---- The selectors of film setup, palette and lighting (3.3: by data type). value: the id chosen (the shot's own or the episode's);
// proposed: the id a crew proposal suggests (its tile says so); a press chooses at once (onChoose(id)).

// Genre and tempo: a left/right carousel of large examples, opening on the chosen one, one card per step.
export function LookCarousel({items, value, proposed = undefined, size = 3, disabled = false, label = '', onChoose}) {
  useLocale();
  const chosen = item => item.id === value || (!value && !item.promptText);
  const index = Math.max(0, items.findIndex(chosen));
  const [start, setStart] = useState(() => carouselStart(items.length, size, index));
  const first = Math.min(start, Math.max(0, items.length - size)), shown = items.slice(first, first + size);
  return <div className="look-carousel" role="group" aria-label={label}>
    <button type="button" className="look-step" aria-label={t('look.previous')} disabled={first <= 0} onClick={() => setStart(carouselMove(items.length, size, first, -1))}><Icon name="arrowLeft" size={16}/></button>
    <div className="look-carousel-track" style={{'--look-size': size}}>
      {shown.map(item => <LookTile key={item.id} item={item} selected={chosen(item)} disabled={disabled} flag={proposed === item.id ? t('look.proposed') : ''} onClick={() => onChoose(item.id)}/>)}
    </div>
    <button type="button" className="look-step" aria-label={t('look.next')} disabled={first + size >= items.length} onClick={() => setStart(carouselMove(items.length, size, first, 1))}><Icon name="arrowRight" size={16}/></button>
    {items.length > size && <small className="look-carousel-at">{t('look.carouselAt', {from: first + 1, to: Math.min(items.length, first + size), count: items.length})}</small>}
  </div>;
}

// Image era: a scale from the oldest look to the newest, in catalog order; Auto is its own cell beside it.
export function EraScale({items, value, proposed = undefined, disabled = false, label = '', onChoose}) {
  useLocale();
  const {auto, steps} = eraScale(items);
  return <div className="look-scale" role="group" aria-label={label}>
    {auto && <div className="look-scale-auto"><LookTile item={auto} selected={!value || value === auto.id} disabled={disabled} flag={proposed === auto.id ? t('look.proposed') : ''} onClick={() => onChoose(auto.id)}/></div>}
    <div className="look-scale-track">
      <ol className="look-scale-steps" style={{'--look-steps': Math.max(1, steps.length)}}>{steps.map(item => <li key={item.id} className={item.id === value ? 'is-on' : undefined}>
        <LookTile item={item} selected={item.id === value} disabled={disabled} flag={proposed === item.id ? t('look.proposed') : ''} onClick={() => onChoose(item.id)}/>
        <span className="look-scale-tick" aria-hidden="true"/></li>)}</ol>
      <div className="look-scale-ends" aria-hidden="true"><span>{t('look.eraOlder')}</span><span>{t('look.eraNewer')}</span></div>
    </div>
  </div>;
}

// Palette and lighting: a card grid with search and sort (palettes also sort dark to light by their main colour).
export function LookGrid({kind, items, value, proposed = undefined, disabled = false, label = '', onChoose}) {
  useLocale();
  const [query, setQuery] = useState(''), [sort, setSort] = useState('catalog');
  const sorts = kind === 'palette' ? ['catalog', 'name', 'tone'] : ['catalog', 'name'];
  const shown = arrangeOptions(items, {query, sort, label: item => optionLabel(item, t)});
  const matched = shown.filter(item => item.promptText).length;
  return <div className="look-grid-wrap">
    <div className="look-grid-tools">
      <input type="search" className="look-search" aria-label={t('look.searchLabel', {what: label})} placeholder={t('look.search')} value={query} onChange={event => setQuery(event.target.value)}/>
      <select aria-label={t('look.sort')} value={sort} onChange={event => setSort(event.target.value)}>{sorts.map(key => <option key={key} value={key}>{t('look.sort_' + key)}</option>)}</select>
    </div>
    <div className="look-grid">{shown.map(item => <LookTile key={item.id} item={item} selected={item.id === value || (!value && !item.promptText)} disabled={disabled}
      flag={proposed === item.id ? t('look.proposed') : ''} onClick={() => onChoose(item.id)}/>)}</div>
    {query.trim() && !matched && <p className="sheet-subtle" role="status">{t('look.noMatch', {query: query.trim()})}</p>}
  </div>;
}
