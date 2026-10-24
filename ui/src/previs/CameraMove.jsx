import { useLocale } from '../i18n/react.jsx';
import { t as uiText } from '../i18n/index.js';
import { CurveEditor, CurveThumb, ParamRow, RangeSlider, ResetButton, TimecodeField } from '../controls/Controls.jsx';
import { cameraKeys, FPS } from './plan.js';
import { cameraRange, frameToBeat, setCameraRange } from './blocking.js';

// "Adjust" for the camera move, with the control kit: when it starts and stops (a range slider and two timecodes, the same numbers as
// the first and last camera key on the beat track), and how it eases (a cubic-bezier curve the stage plays back exactly). Folded away
// until asked for: the buttons above are what most shots need.
const t = (key, params) => uiText('previs.' + key, params);
const SMOOTH = [0.42, 0, 0.58, 1];  // what a move does when it has no curve of its own: smooth in and out
const PRESET_IDS = ['linear', 'easeIn', 'easeOut', 'easeInOut', 'strongEaseOut', 'backOut'];

export function CameraMove({plan, frames, frame, writable, onEdit}) {
  useLocale();
  const last = frames - 1, range = cameraRange(plan), start = Math.round(range.start), end = Math.round(range.end);
  const moved = start !== 0 || end !== last, curve = Array.isArray(plan.easing) ? plan.easing : SMOOTH;
  const keys = cameraKeys(plan), first = keys[0][0], stop = keys[keys.length - 1][0];
  const progress = stop > first ? (frameToBeat(plan, frame) - first) / (stop - first) : 0;
  const set = next => onEdit(setCameraRange(plan, next));
  const seconds = value => `${(value / FPS).toFixed(2)} s`;
  return <details className="previs-move">
    <summary>{t('moveTitle')}</summary>
    <div className="previs-move-body ctl-palette ctl-kit">
      <ParamRow label={t('moveRange')} modified={moved} slider={<RangeSlider start={start} end={end} min={0} max={Math.max(1, last)} step={1} minGap={1} trimmedHatch disabled={!writable}
          ariaLabelStart={t('moveStarts')} ariaLabelEnd={t('moveStops')} formatValue={seconds} onChange={set}/>}
        reset={<ResetButton active={moved} disabled={!writable} ariaLabel={t('moveRangeReset')} onReset={() => set({start: 0, end: last})}/>}/>
      <div className="previs-move-times">
        <label><span>{t('moveStarts')}</span><TimecodeField frames={start} fps={FPS} min={0} max={Math.max(0, end - 1)} disabled={!writable} modified={start > 0}
          ariaLabel={t('moveStarts')} onChange={value => set({start: value, end})}/></label>
        <label><span>{t('moveStops')}</span><TimecodeField frames={end} fps={FPS} min={Math.min(last, start + 1)} max={last} disabled={!writable} modified={end < last}
          ariaLabel={t('moveStops')} onChange={value => set({start, end: value})}/></label>
      </div>
      <ParamRow label={t('moveEasing')} modified={Array.isArray(plan.easing)} extra={<CurveThumb values={curve} width={56} height={28} active={Array.isArray(plan.easing)}/>}
        reset={<ResetButton active={Array.isArray(plan.easing)} disabled={!writable} ariaLabel={t('moveEasingReset')} onReset={() => onEdit({easing: undefined})}/>}/>
      {writable && <CurveEditor values={curve} size={176} overshoot snap={0.01} ariaLabel={t('moveEasing')} progressAtTime={progress} onChange={values => onEdit({easing: values})}
        labels={{time: t('easingTime'), progress: t('easingProgress'), overshoot: t('easingOvershoot'), preview: t('easingPreview')}}
        presetLabels={{...Object.fromEntries(PRESET_IDS.map(id => [id, t('ease_' + id)])), custom: t('ease_custom')}}/>}
      <p className="previs-note">{t('moveNote')}</p>
    </div>
  </details>;
}
