import { useState } from 'react';
import { useLocale } from './i18n/react.jsx';
import { t } from './i18n/index.js';
import { CHOICES, GROUPS, SWATCHES, TEXT_FIELDS, composeAppearance, emptySelection, hasSelection, mergeAppearance, needsChoice } from './appearanceModel.js';

// SPEC_18 R9: appearance as tags. Picking changes nothing until "Apply to appearance"; if the character already has appearance text,
// you are asked whether these replace it or follow it, and the text is never overwritten silently. Nothing here is stored but the text.
function Choice({field, value, disabled, onPick}) {
  const swatches = SWATCHES[field];
  return <div className="attr-field" role="group" aria-label={t('world.attr_' + field)}>
    <span className="attr-label">{t('world.attr_' + field)}</span>
    <div className={swatches ? 'attr-swatches' : 'attr-chips'}>{CHOICES[field].map(option => {
      const name = t(`world.attrOpt_${field}_${option}`), on = value === option;
      return swatches
        ? <button key={option} type="button" className="attr-swatch" aria-pressed={on} aria-label={name} title={name} disabled={disabled} style={{background: swatches[option]}} onClick={() => onPick(on ? '' : option)}/>
        : <button key={option} type="button" className="attr-chip" aria-pressed={on} disabled={disabled} onClick={() => onPick(on ? '' : option)}>{name}</button>;
    })}</div>
  </div>;
}

export function AppearanceForm({current, disabled, onApply}) {
  useLocale();
  const [pick, setPick] = useState(emptySelection), [asking, setAsking] = useState(null);
  const composed = composeAppearance(pick);
  const set = (key, value) => {setPick(now => ({...now, [key]: value})); setAsking(null);};
  const apply = mode => {setAsking(null); return onApply(mergeAppearance(current, composed, mode));};
  return <div className="attr-form">
    <p className="space-sub">{t('world.attrsHint')}</p>
    {GROUPS.map(group => <fieldset key={group.key} className="attr-group"><legend>{t('world.attrGroup_' + group.key)}</legend>
      {group.fields.map(field => TEXT_FIELDS.includes(field)
        ? <label key={field} className="attr-text">{t('world.attr_' + field)}<input value={pick[field]} maxLength={80} disabled={disabled} onChange={event => set(field, event.target.value)}/></label>
        : <Choice key={field} field={field} value={pick[field]} disabled={disabled} onPick={value => set(field, value)}/>)}
    </fieldset>)}
    {composed && <p className="attr-preview" aria-live="polite">{composed}</p>}
    {asking ? <div className="attr-ask" role="group" aria-label={t('world.attrsAsk')}>
      <p>{t('world.attrsAsk')}</p>
      <div className="world-actions"><button type="button" className="world-act" disabled={disabled} onClick={() => apply('replace')}>{t('world.attrsReplace')}</button>
        <button type="button" className="world-act" disabled={disabled} onClick={() => apply('append')}>{t('world.attrsAppend')}</button>
        <button type="button" className="world-tool" onClick={() => setAsking(null)}>{t('common.cancel')}</button></div>
    </div> : <div className="world-actions"><button type="button" className="world-act" disabled={disabled || !hasSelection(pick) || !composed}
      onClick={() => (needsChoice(current, composed) ? setAsking(composed) : apply('replace'))}>{t('world.attrsApply')}</button></div>}
  </div>;
}
