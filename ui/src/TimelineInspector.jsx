import { useEffect, useState } from 'react';
import { useLocale } from './i18n/react.jsx';
import { t } from './i18n/index.js';
import { RangeSlider, TimecodeField } from './controls/Controls.jsx';
import { FPS, clock, parseTrimCommand, signed, toFrames } from './timelineModel.js';

// Right panel of the Timeline space: the clip in hand. Each job has three ways in, the same everywhere in the studio: say it in a
// line, adjust it with the control kit, or drag it on the timeline. All three end in the same trim, so they never disagree.
const Layer = ({name, children}) => <div className="tl-layer"><span className="tl-lay">{t('timeline.layer_' + name)}</span><div className="tl-layer-body">{children}</div></div>;

export function TimelineInspector({clip, saved, ripple, onRipple, writable, saving, onPoint, onSlide, onLength, onMove, onReset, takes = [], onTake, hint = null}) {
  useLocale();
  const [say, setSay] = useState(''), [note, setNote] = useState('');
  useEffect(() => {setSay(''); setNote('');}, [clip?.id]);
  if (!clip) return <aside className="tl-panel tl-inspector ctl-palette ctl-kit" aria-label={t('timeline.length')}>
    <header><h2>{t('timeline.clip', {shot: '–'})}</h2></header><p className="tl-empty">{t('timeline.noClip')}</p></aside>;

  const free = writable && clip.trimmable;
  const why = !clip.trimmable ? t(clip.kind === 'take' ? 'timeline.notTrimmable_loading' : 'timeline.notTrimmable_' + clip.kind) : !writable ? t('timeline.readOnly') : '';
  const sourceFrames = Math.round(clip.source * FPS), inFrames = toFrames(clip.in), outFrames = toFrames(clip.out);
  const change = clip.length - (saved ? saved.length : clip.length);
  // The line you type: "out -3f", "in +0.5s", "length 3.5s", or the same in Chinese. Nothing is guessed beyond that.
  const submit = event => {
    event.preventDefault();
    if (!free || !say.trim()) return;
    const command = parseTrimCommand(say);
    if (!command) {setNote(t('timeline.sayNotUnderstood')); return;}
    const result = command.length !== undefined ? onLength(command.length) : onMove(command.edge, command.delta);
    if (!result || (command.length === undefined && Math.abs(result.delta) < 1e-9)) {setNote(t('timeline.sayNoRoom')); return;}
    setNote(''); setSay('');
  };
  const range = (next, meta, commit) => {
    const flip = Boolean(meta.alt);
    if (meta.handle === 'start') onPoint('in', next.start / FPS, commit, flip);
    else if (meta.handle === 'end') onPoint('out', next.end / FPS, commit, flip);
    else onSlide(next.start / FPS, commit);
  };
  const at = (edge, commit) => frames => onPoint(edge, frames / FPS, commit, false);

  return <aside className="tl-panel tl-inspector ctl-palette ctl-kit" aria-label={t('timeline.length')}>
    <header><h2>{t('timeline.clip', {shot: clip.label})}</h2><span>{t('timeline.clipMeta', {seconds: clip.length.toFixed(1), frames: toFrames(clip.length)})}</span></header>
    <div className="tl-inspector-body">
      <section className="tl-sec">
        <div className="tl-sec-head"><h3>{t('timeline.length')}</h3>
          <button type="button" role="switch" aria-checked={ripple} className="tl-switch" onClick={onRipple} title={t('timeline.rippleHelp')}><span>{t('timeline.ripple')}</span><i aria-hidden="true"/></button></div>
        {why && <p className="tl-why" role="note">{why}</p>}
        {hint && free && <div className="tl-hint-card" role="note"><span>{t('timeline.long', {shot: clip.label, change: signed(hint.trimBy)})}</span>
          <button type="button" onClick={() => onMove('out', hint.trimBy)}>{t('timeline.takeItDown', {change: signed(hint.trimBy)})}</button></div>}
        <Layer name="say">
          <form onSubmit={submit}>
            <input type="text" className="tl-say" value={say} disabled={!free} placeholder={t('timeline.sayPlaceholder')} aria-label={t('timeline.sayLabel')}
              aria-invalid={note ? true : undefined} onChange={event => {setSay(event.target.value); setNote('');}}/>
            {note && <p className="tl-say-note" role="alert">{note}</p>}
          </form>
        </Layer>
        <Layer name="adjust">
          <div className="tl-readout"><span>{t('timeline.takeRange', {seconds: clip.source.toFixed(1)})}</span>
            <span>{t('timeline.lengthReadout', {seconds: clip.length.toFixed(1), frames: toFrames(clip.length)})}{Math.abs(change) > 1e-6 && <em> ({signed(change)})</em>}</span></div>
          <RangeSlider start={inFrames} end={outFrames} min={0} max={Math.max(1, sourceFrames)} step={1} minGap={1} trimmedHatch disabled={!free}
            ariaLabelStart={t('timeline.rangeIn', {shot: clip.label})} ariaLabelEnd={t('timeline.rangeOut', {shot: clip.label})}
            formatValue={frames => clock(frames / FPS)}
            onChange={(next, meta) => range(next, meta, false)} onCommit={(next, meta) => range(next, meta, true)}/>
          <div className="tl-points">
            <label><span className={inFrames > 0 ? 'is-modified' : ''}>{t('timeline.inPoint')}</span>
              <TimecodeField frames={inFrames} fps={FPS} min={0} max={Math.max(0, outFrames - 1)} disabled={!free} modified={inFrames > 0}
                ariaLabel={t('timeline.rangeIn', {shot: clip.label})} onChange={at('in', false)} onCommit={at('in', true)}/></label>
            <label><span className={outFrames < sourceFrames ? 'is-modified' : ''}>{t('timeline.outPoint')}</span>
              <TimecodeField frames={outFrames} fps={FPS} min={Math.min(sourceFrames, inFrames + 1)} max={sourceFrames} disabled={!free} modified={outFrames < sourceFrames}
                ariaLabel={t('timeline.rangeOut', {shot: clip.label})} onChange={at('out', false)} onCommit={at('out', true)}/></label>
          </div>
          {clip.trimmed && <button type="button" className="tl-reset" disabled={!free} onClick={onReset}>{t('timeline.resetTrim')}</button>}
        </Layer>
        <Layer name="drag"><p className="tl-hint-text">{t('timeline.dragHint')}</p></Layer>
        {saving && <p className="tl-saving" role="status">{t('timeline.saving')}</p>}
      </section>

      <section className="tl-sec">
        <div className="tl-sec-head"><h3>{t('timeline.dialogue')}</h3></div>
        {clip.dialogue.length === 0 ? <p className="tl-hint-text">{t('timeline.dialogueEmpty')}</p>
          : <ul className="tl-lines">{clip.dialogue.map((line, index) => <li key={index}>
            {line.speaker && <b>{line.speaker}</b>}<span>{line.line}</span>
            {Number(line.estimatedSeconds) > 0 && <small>{t('timeline.lineSeconds', {seconds: Number(line.estimatedSeconds).toFixed(1)})}</small>}</li>)}</ul>}
      </section>

      {takes.length > 0 && <section className="tl-sec" id="tl-takes">
        <div className="tl-sec-head"><h3>{t('timeline.takes')}</h3></div>
        <ul className="tl-takes-list">{takes.map((take, index) => <li key={take.videoId}>
          <video src={take.url + '#t=0.1'} muted playsInline preload="metadata" aria-label={t('timeline.takePreview', {index: index + 1})}/>
          <span>{t('timeline.takeNumber', {index: index + 1})}</span>
          <button type="button" disabled={!writable} onClick={() => onTake(take)}>{t('timeline.useTake')}</button></li>)}</ul>
      </section>}
    </div>
  </aside>;
}
