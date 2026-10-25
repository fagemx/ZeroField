import { useEffect, useState } from 'react';
import { useLocale } from '../i18n/react.jsx';
import { t } from '../i18n/index.js';
import { storyRequest } from '../storyModel.js';
import { appFor, estimateOf, fallbackOptions, humanSeconds, reasonKey, requestBody, slotControls, startingApp } from './generationModel.js';

// SPEC_18 R8: what a picture will use and cost, on the same row as the button that makes it. The workflow, ratio and resolution you see are
// exactly what is sent. The time is what this production's earlier runs took, with how many runs that rests on, or "unknown"; a Router card
// shows a quote labelled as no price lock, or the error. One row, like the prompt bar it sits under: choices on the left, the cost and the
// button at the right end (the row wraps only when the pane is too narrow). The button is outlined: the screen's one primary action is elsewhere.
const timeText = seconds => { const {unit, value} = humanSeconds(seconds); return t(unit === 's' ? 'generation.seconds' : 'generation.minutes', {value}); };

function Cost({app, quote, onQuote}) {
  if (app?.quotable) {
    return <span className="gen-cost" role="status">
      {quote?.status === 'ready' ? <><b>${quote.data.amount_usd} USD</b><small>{t('generation.notLocked')}</small></>
        : quote?.status === 'error' ? <span className="gen-error">{t('generation.quoteFailed', {message:quote.message})}</span>
          : <button type="button" className="world-tool" disabled={quote?.status === 'loading'} onClick={onQuote}>{t(quote?.status === 'loading' ? 'generation.quoting' : 'generation.quote')}</button>}
    </span>;
  }
  const estimate = estimateOf(app);
  return <span className="gen-cost" role="status">{estimate ? <span>{t('generation.estimate', {time:timeText(estimate.seconds), samples:estimate.samples})}</span> : <span className="gen-unknown">{t('generation.estimateUnknown')}</span>}</span>;
}

// kind: 'asset' (the card in front of you). generating: its picture is in the making. label: the button's words. ratio: the episode's.
// preloaded: the options as the server gave them, for the first paint (the page and the tests); the bar still reads them fresh on mount.
export function GenerationBar({kind = 'asset', id, ratio = '', styleName = '', label, generating = false, canCancel = false, disabled = false, preloaded = null, onGenerate, onCancel}) {
  useLocale();
  const [loaded, setLoaded] = useState(preloaded || {status: 'loading', options: null}), [chosen, setChosen] = useState({appCode: null, values: {}}), [quote, setQuote] = useState(null);
  useEffect(() => {
    let alive = true;
    setLoaded({status: 'loading', options: null}); setQuote(null);
    storyRequest(`/${kind}s/${id}/generation-options`).then(options => {if (alive) setLoaded({status: 'ready', options});}).catch(() => {if (alive) setLoaded({status: 'failed', options: fallbackOptions()});});
    return () => {alive = false;};
  }, [kind, id]);
  const options = loaded.options || fallbackOptions();
  const app = startingApp(options, chosen.appCode);
  const controls = slotControls(app, chosen.values, ratio);
  const style = options.style?.name || styleName;
  const body = () => requestBody(app, controls);
  const ask = async () => {
    setQuote({status: 'loading'});
    try {setQuote({status: 'ready', data: await storyRequest(`/${kind}s/${id}/router-quotes`, 'POST', {...body(), kind: kind === 'asset' ? 'image' : 'video'})});}
    catch (err) {setQuote({status: 'error', message: err.message});}
  };
  const change = patch => {setChosen(current => ({...current, ...patch})); setQuote(null);};
  return <section className="gen-bar" aria-label={t('generation.title')}>
    {loaded.status === 'failed' && <p className="gen-error" role="status">{t('generation.optionsFailed')}</p>}
    <div className="gen-row">
      {loaded.status === 'ready' && options.apps.length > 0 && <>
        <select className="gen-workflow" aria-label={t('generation.workflow')} title={t('generation.workflow')} value={app?.appCode || ''} disabled={generating || disabled} onChange={event => change({appCode: event.target.value, values: {}})}>
          {!app && <option value="">—</option>}
          {options.apps.map(item => <option key={item.appCode} value={item.appCode} disabled={!item.configured}>{item.name}{item.configured ? '' : ' — ' + t('generation.' + reasonKey(item.reason))}</option>)}</select>
        {controls.map(control => <select key={control.key} aria-label={t('generation.control_' + control.kind, {name:control.key})} title={t('generation.control_' + control.kind, {name:control.key})}
          value={control.value} disabled={generating || disabled} onChange={event => change({values: {...chosen.values, [control.key]: event.target.value}})}>
          {control.options.map(option => <option key={option}>{option}</option>)}</select>)}
      </>}
      {style && <span className="gen-style" title={t('generation.style', {name:style})}>{style}</span>}
      <span className="gen-end">
        {app && loaded.status === 'ready' && <Cost app={app} quote={quote} onQuote={ask}/>}
        <button type="button" className="world-act gen-go" disabled={disabled || generating || !app} onClick={() => onGenerate(body())}>{label}</button>
        {generating && canCancel && <button type="button" className="world-tool" onClick={onCancel}>{t('world.cancelGeneration')}</button>}
      </span>
    </div>
    {loaded.status === 'ready' && !app && <p className="gen-error" role="status">{options.apps.length ? t('generation.noneReady') : t('generation.noApps')}</p>}
  </section>;
}
