import { useState } from 'react';
import { useLocale } from '../i18n/react.jsx';
import { t } from '../i18n/index.js';
import { CAMERA_GROUPS, optionLabel, textureHue } from './lookModel.js';
import { Icon } from '../Icon.jsx';

// SPEC_19 3.3: the look buttons under the composer's top half and the example tiles of its walls.
//   A look button: a small picture, the category, "This shot" / "Episode", and the current value (cut short; the full value on hover).
//   A tile: a 16:9 example. It shows its poster and plays its clip only while the pointer rests on it (one tile at a time, so one video,
//   1.2 I); an option without example media is an abstract texture told apart by colour, never a picture of something it is not, and
//   Auto is its own texture. The chosen tile has the amber outline; a move chosen more than once shows each of its places in the order.

// The texture of an option with no example media (and of Auto).
export function LookTexture({id, auto = false, label = ''}) {
  return <span className={'look-texture' + (auto ? ' is-auto' : '')} style={auto ? undefined : {'--look-hue': textureHue(id)}} aria-hidden="true">
    {auto && <b>{label || 'Auto'}</b>}</span>;
}

function TileMedia({item, auto, label, active}) {
  const poster = item?.preview?.poster || null, clip = item?.preview?.clip || null;
  if (auto || (!poster && !clip)) return <LookTexture id={item?.id} auto={auto} label={label}/>;
  return <>
    {poster ? <img src={poster} alt="" loading="lazy"/> : <LookTexture id={item.id}/>}
    {active && clip && <video src={clip} autoPlay muted loop playsInline preload="auto" aria-hidden="true"/>}
  </>;
}

// One example. numbers: the places this option holds in the shot's order (moves), shown in the corner.
export function LookTile({item, selected = false, numbers = [], disabled = false, small = false, onClick}) {
  useLocale();
  const [hover, setHover] = useState(false);
  const auto = !item?.promptText, label = auto ? t('look.auto') : optionLabel(item, t);
  return <button type="button" className={'look-tile' + (selected ? ' is-selected' : '') + (small ? ' is-small' : '')} aria-pressed={selected} disabled={disabled}
    title={item?.promptText || t('look.autoHint')} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)} onFocus={() => setHover(true)} onBlur={() => setHover(false)}
    onClick={() => onClick?.(item)}>
    <span className="look-frame"><TileMedia item={item} auto={auto} label={t('look.auto')} active={hover}/>
      {numbers.length > 0 && <span className="look-order" aria-label={t('look.order', {numbers:numbers.join(', ')})}>{numbers.join('·')}</span>}</span>
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

// The look buttons: references and camera in package B; package C turns on film setup, palette and lighting (lookModel LOOK_BUTTONS).
//   buttons: [{id, label, scope: 'shot' | 'episode' | null, value, full, thumb, dot, badge}]
export function LookButtons({buttons, open = null, onOpen}) {
  useLocale();
  return <div className="look-buttons" role="toolbar" aria-label={t('look.buttons')}>
    {buttons.map(button => <button key={button.id} type="button" className={'look-button' + (open === button.id ? ' is-open' : '')} aria-expanded={open === button.id}
      title={[button.label, button.full || button.value].filter(Boolean).join(' · ')} onClick={() => onOpen(open === button.id ? null : button.id)}>
      <span className="look-button-thumb">{button.thumb ? <img src={button.thumb} alt="" loading="lazy"/> : <Icon name={button.icon || 'image'} size={14}/>}
        {button.dot && <i className="look-dot" aria-hidden="true"/>}</span>
      <span className="look-button-text"><span className="look-button-head"><b>{button.label}</b>{button.scope && <em className={'look-scope is-' + button.scope}>{t('look.' + button.scope)}</em>}
        {button.badge && <em className="look-scope">{button.badge}</em>}</span>
        <small>{button.value || t('look.auto')}</small></span>
    </button>)}
  </div>;
}
