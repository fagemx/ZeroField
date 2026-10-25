import { useEffect, useState } from 'react';
import { useLocale } from './i18n/react.jsx';
import { t } from './i18n/index.js';
import { storyList } from './storyModel.js';
import { RATIOS } from './breakdownModel.js';
import { MAX_START_FILE, MAX_START_TEXT, START_FILE, START_MODES, startPlan, titleFrom } from './startModel.js';
import { Icon } from './Icon.jsx';
import './start.css';

// SPEC_18 R16: one big box to start a production from. Pick what you are bringing (an idea, a novel chapter, a screenplay), write or
// paste it (or load a .txt or .md file), choose the ratio and a style, and the production opens on Story & World with it in the draft.
// Creating the production is the hub's job: onCreate({title, start}) gets what to name it and what to hand over.
export function StartFromStory({preloaded = null, busy = false, error = '', onCancel, onCreate}) {
  useLocale();
  const [mode, setMode] = useState('idea'), [text, setText] = useState(''), [title, setTitle] = useState(''), [ratio, setRatio] = useState(RATIOS[0]), [style, setStyle] = useState('');
  const [styles, setStyles] = useState(preloaded || []), [problem, setProblem] = useState('');
  // Styles come with sample pictures; without them (a failed read) the production simply starts in its default style.
  useEffect(() => {
    if (preloaded) return undefined;
    let alive = true;
    storyList('/catalog/styles').then(items => {if (alive) setStyles(items);}).catch(() => {});
    return () => {alive = false;};
  }, [preloaded]);
  const chosen = style || styles[0]?.stylePresetId || '';
  const plan = startPlan({mode, text, ratio, style: chosen});
  const name = title.trim() || titleFrom(text, t('start.untitled'));
  const load = async file => {
    if (!file) return;
    if (!START_FILE.test(file.name)) {setProblem(t('start.fileType')); return;}
    if (file.size > MAX_START_FILE) {setProblem(t('start.fileTooLarge')); return;}
    const content = await file.text();
    if (content.length > MAX_START_TEXT) {setProblem(t('start.textTooLong')); return;}
    setText(content); setProblem('');
  };
  return <form className="start-story" onSubmit={event => {event.preventDefault(); if (plan.ok && !busy) onCreate({title: name, start: plan.start});}}>
    <div className="start-modes" role="group" aria-label={t('start.mode')}>
      {START_MODES.map(key => <button key={key} type="button" aria-pressed={mode === key} disabled={busy} onClick={() => setMode(key)}>{t('story.sourceMode_' + key)}</button>)}
    </div>
    <textarea data-autofocus className="start-text" rows={9} value={text} maxLength={MAX_START_TEXT} disabled={busy} aria-label={t('story.sourceMode_' + mode)}
      placeholder={t('start.placeholder_' + mode)} onChange={event => {setText(event.target.value); setProblem('');}}/>
    <div className="start-under">
      <label className="start-upload"><Icon name="arrowUp" size={14}/>{t('start.upload')}
        <input type="file" accept=".txt,.md,text/plain,text/markdown" disabled={busy} onChange={event => {const file = event.target.files?.[0]; event.target.value = ''; load(file);}}/></label>
      {!plan.ok && plan.reason === 'empty' ? <span className="start-hint">{t('start.needText')}</span> : null}
      {problem && <span className="start-problem" role="alert">{problem}</span>}
    </div>
    <fieldset className="start-ratios"><legend>{t('start.ratio')}</legend>
      <div>{RATIOS.map(value => <button key={value} type="button" aria-pressed={ratio === value} disabled={busy} onClick={() => setRatio(value)}>{value}</button>)}</div>
    </fieldset>
    {styles.length > 0 && <fieldset className="start-styles"><legend>{t('start.style')}</legend>
      <div>{styles.map(item => <label key={item.stylePresetId} className={chosen === item.stylePresetId ? 'is-on' : undefined}>
        <input type="radio" name="start-style" value={item.stylePresetId} checked={chosen === item.stylePresetId} disabled={busy} onChange={() => setStyle(item.stylePresetId)}/>
        {item.sampleImage ? <img src={item.sampleImage} alt="" loading="lazy"/> : <span className="start-nosample" aria-hidden="true"/>}
        <span>{item.name}</span></label>)}</div>
    </fieldset>}
    <label className="modal-field start-title"><span>{t('start.titleLabel')}<small>{t('surfaces.optional')}</small></span>
      <input maxLength={200} value={title} disabled={busy} placeholder={titleFrom(text, t('start.untitled'))} onChange={event => setTitle(event.target.value)}/></label>
    {error && <p className="canvas-error" role="alert">{error}</p>}
    <div className="sheet-dialog-actions"><span className="spacer"/>
      <button type="button" disabled={busy} onClick={onCancel}>{t('surfaces.cancel')}</button>
      <button type="submit" className="primary" disabled={!plan.ok || busy}>{t(busy ? 'start.creating' : 'start.create')}</button></div>
  </form>;
}
