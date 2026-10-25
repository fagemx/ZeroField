import { useState } from 'react';
import { useLocale } from './i18n/react.jsx';
import { t } from './i18n/index.js';
import { Dialog } from './Dialog.jsx';
import { Icon } from './Icon.jsx';
import { BREAKDOWN_MODES, RATIOS, TARGET_CHOICES, closestMode, targetSeconds } from './breakdownModel.js';

// SPEC_18 R7: what a storyboard build asks (how to split, ratio, style), in one dialog that opens when you press the screen's one
// action. Confirm runs the same build as before; cancel changes nothing. R13 adds, when the parent supplies them, a target length
// and the shots each way of splitting would give. The estimate never changes a shot's seconds: it only says which way lands nearest.
function Estimate({item}) {
  if (!item) return null;
  return <span className="breakdown-estimate">
    <b>{t('world.estimateTotal', {shots:item.shotCount, seconds:item.plannedSeconds})}</b>
    <small>{t('world.estimateNew', {count:item.newShots})}</small></span>;
}

export function BreakdownDialog({value, styles = [], rebuild, shots = 0, estimate, target = null, confirmDisabled = false, onTarget, onImport, onConfirm, onCancel}) {
  useLocale();
  const [mode, setMode] = useState(value.breakdownMode), [ratio, setRatio] = useState(value.ratio), [style, setStyle] = useState(value.style);
  const [custom, setCustom] = useState(target && !TARGET_CHOICES.includes(target) ? String(target) : '');
  const modes = estimate?.status === 'ready' ? estimate.modes : null;
  const nearest = closestMode(modes, target);
  const pickTarget = seconds => {setCustom(seconds && !TARGET_CHOICES.includes(seconds) ? String(seconds) : ''); onTarget?.(seconds);};
  return <Dialog title={t(rebuild ? 'world.dialogUpdate' : 'world.dialogBuild')} confirmLabel={t(rebuild ? 'world.updateStoryboard' : 'story.confirmAndBuild')} className="breakdown-dialog"
    confirmDisabled={confirmDisabled} onCancel={onCancel} onConfirm={() => onConfirm({breakdownMode:mode, ratio, style})}>
    <div className="breakdown-body">
    {shots > 0 && <p className="breakdown-keep">{t('world.dialogKeep', {count:shots})}</p>}
    <fieldset className="breakdown-modes"><legend>{t('story.breakdownMode')}</legend>
      {BREAKDOWN_MODES.map(key => <label key={key} className={mode === key ? 'is-on' : undefined}>
        <input type="radio" name="breakdown" value={key} checked={mode === key} onChange={() => setMode(key)}/>
        <span className="breakdown-mode-text"><b>{t('story.breakdownMode_' + key)}{nearest === key && <em className="breakdown-nearest">{t('world.estimateNearest', {seconds:target})}</em>}</b>
          <small>{t('world.breakdownHint_' + key)}</small></span>
        {modes && <Estimate item={modes[key]}/>}
      </label>)}
      {estimate?.status === 'loading' && <p className="space-sub" role="status">{t('world.estimateLoading')}</p>}
      {estimate?.status === 'error' && <p className="space-sub" role="status">{t('world.estimateFailed')}</p>}
      {modes && <p className="space-sub">{t('world.estimateNote')}</p>}
    </fieldset>
    {onTarget && <fieldset className="breakdown-target"><legend>{t('world.targetTitle')}</legend>
      <div className="studio-segmented small" role="group" aria-label={t('world.targetTitle')}>
        <button type="button" aria-pressed={target === null && !custom} onClick={() => pickTarget(null)}>{t('world.targetNone')}</button>
        {TARGET_CHOICES.map(seconds => <button key={seconds} type="button" aria-pressed={target === seconds} onClick={() => pickTarget(seconds)}>{t('world.targetSeconds', {seconds})}</button>)}
      </div>
      <label className="breakdown-custom">{t('world.targetCustom')}<input type="number" min={10} max={1800} step={1} inputMode="numeric" value={custom} placeholder="—"
        onKeyDown={event => {if (event.key === 'Enter') event.preventDefault();}}  // Enter in this field must not start the build
        onChange={event => {setCustom(event.target.value); onTarget(targetSeconds(event.target.value));}}/><span>{t('world.targetUnit')}</span></label>
      <small className="space-sub">{t('world.targetHint')}</small>
    </fieldset>}
    <div className="breakdown-format">
      <label className="modal-field">{t('story.aspectRatio')}<select value={ratio} onChange={event => setRatio(event.target.value)}>{RATIOS.map(item => <option key={item}>{item}</option>)}</select></label>
      <fieldset className="breakdown-styles"><legend>{t('story.style')}</legend>
        <div>{styles.map(item => <label key={item.stylePresetId} className={style === item.stylePresetId ? 'is-on' : undefined}>
          <input type="radio" name="style" value={item.stylePresetId} checked={style === item.stylePresetId} onChange={() => setStyle(item.stylePresetId)}/>
          {item.sampleImage ? <img src={item.sampleImage} alt="" loading="lazy"/> : <span className="breakdown-nosample" aria-hidden="true"/>}
          <span>{item.name}</span></label>)}</div>
      </fieldset>
    </div>
    {onImport && <div className="breakdown-import"><span><b>{t('world.importAsk')}</b><small>{t('world.importHint')}</small></span>
      <button type="button" className="world-tool" onClick={onImport}><Icon name="arrowUp" size={14}/>{t('world.importTable')}</button></div>}
    </div>
  </Dialog>;
}
