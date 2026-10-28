import { useEffect, useRef, useState } from 'react';
import { useLocale } from '../i18n/react.jsx';
import { t } from '../i18n/index.js';
import { storyList, storyRequest } from '../storyModel.js';
import { FALLBACK_SHOT_APP, FRAME_APP, clampCount, estimateOf, fallbackOptions, frameOptions, frameOptionsUsable, generateLabel, humanSeconds, nodeControls, reasonKey, requestBody,
  secondChoices, shotRequestBody, slotControls, startingApp, startingSeconds, MAX_TAKES } from './generationModel.js';

// SPEC_18 R8: what a picture will use and cost, on the same row as the button that makes it. The workflow, ratio and resolution you see are
// exactly what is sent. The time is what this production's earlier runs took, with how many runs that rests on, or "unknown"; a Router card
// shows a quote labelled as no price lock, or the error. One row, like the prompt bar it sits under: choices on the left, the cost and the
// button at the right end (the row wraps only when the pane is too narrow). The button is outlined: the screen's one primary action is elsewhere.
//
// SPEC_19 R9, kind="shot": the shot composer's parameter row. `lead` (the composer's @ / # buttons and its output switch) opens the row;
// then the workflow, the seconds, resolution and sound, how many takes (1-4), the time, and the Shot Stage's one primary button
// ("Generate 2 · about 80 s", or "Save & generate" while the prompt has unsaved changes). A narrow row (under 760 px, or a window under
// 960 px) folds resolution and sound into "More"; the shot's ratio follows the episode and always sits there. A first frame uses the
// shot's image options (?kind=image, else the catalog's image cards), a video the shot's own generation options.
const timeText = seconds => { const {unit, value} = humanSeconds(seconds); return t(unit === 's' ? 'generation.seconds' : 'generation.minutes', {value}); };

// The catalog's cards per capability, read once per page: their inputs give the shot row its seconds and sound.
const CATALOG = new Map();
const catalogApps = capability => {
  if (!CATALOG.has(capability)) CATALOG.set(capability, storyList('/catalog/apps?capability=' + capability).catch(error => {CATALOG.delete(capability); throw error;}));
  return CATALOG.get(capability);
};

function Cost({app, quote, onQuote, shot = false}) {
  if (app?.quotable) {
    return <span className="gen-cost" role="status">
      {quote?.status === 'ready' ? <><b>${quote.data.amount_usd} USD</b><small>{t('generation.notLocked')}</small></>
        : quote?.status === 'error' ? <span className="gen-error">{t('generation.quoteFailed', {message:quote.message})}</span>
          : <button type="button" className="world-tool" disabled={quote?.status === 'loading'} onClick={onQuote}>{t(quote?.status === 'loading' ? 'generation.quoting' : 'generation.quote')}</button>}
    </span>;
  }
  const estimate = estimateOf(app);
  // On the shot row the time is on the button; the note says what it rests on.
  if (shot) return <span className="gen-cost" role="status">{estimate ? <small>{t('composer.samples', {samples:estimate.samples})}</small> : <span className="gen-unknown">{t('generation.estimateUnknown')}</span>}</span>;
  return <span className="gen-cost" role="status">{estimate ? <span>{t('generation.estimate', {time:timeText(estimate.seconds), samples:estimate.samples})}</span> : <span className="gen-unknown">{t('generation.estimateUnknown')}</span>}</span>;
}

// Folds controls into "More" when the row is narrow (the shot row only; without a ResizeObserver, as on the server, it stays wide).
function useNarrow(root, enabled) {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    if (!enabled || !root.current || typeof ResizeObserver === 'undefined') return undefined;
    const check = () => setNarrow(Boolean(root.current) && (root.current.clientWidth < 760 || window.innerWidth < 960));
    const observer = new ResizeObserver(check);
    observer.observe(root.current); check();
    return () => observer.disconnect();
  }, [enabled]);  // eslint-disable-line react-hooks/exhaustive-deps
  return narrow;
}

// kind: 'asset' (the card in front of you) or 'shot' (the shot composer). generating: its picture is in the making. label: the button's
// words (the shot row words its own). ratio: the episode's. preloaded: the options as the server gave them ({status, options, catalog?}),
// for the first paint (the page and the tests); the bar still reads them fresh on mount.
// Shot only: output 'video' | 'frame'; seconds: the shot's planned length; dirty: the prompt has unsaved changes; lead: what opens the
// row; bodyRef: a ref that always holds the request the button would send ({appCode, modelParams?, count}), for the prompt preview.
export function GenerationBar({kind = 'asset', id, ratio = '', styleName = '', label, generating = false, canCancel = false, disabled = false, preloaded = null, onGenerate, onCancel,
  output = 'video', seconds: planned = null, dirty = false, lead = null, bodyRef = null}) {
  useLocale();
  const shot = kind === 'shot', root = useRef(null);
  const [loaded, setLoaded] = useState(preloaded || {status: 'loading', options: null}), [chosen, setChosen] = useState({appCode: null, values: {}}), [quote, setQuote] = useState(null);
  const [count, setCount] = useState(1);
  const narrow = useNarrow(root, shot);
  useEffect(() => {
    let alive = true;
    setLoaded({status: 'loading', options: null}); setQuote(null);
    const frame = shot && output === 'frame', capability = frame ? 'IMAGE' : 'VIDEO';
    // SPEC_21: a first frame's cards come from the shot's image options, whose default is the server's (the reference card); a server
    // without them leaves the catalog's image cards, which never default to an edit card.
    const options = frame ? storyRequest(`/shots/${id}/generation-options?kind=image`)
      .then(value => frameOptionsUsable(value) ? value : Promise.reject(new Error('no image options')))
      .catch(() => catalogApps('IMAGE').then(items => frameOptions(items)))
      : storyRequest(`/${kind}s/${id}/generation-options`);
    Promise.all([options, shot ? catalogApps(capability).catch(() => []) : null])
      .then(([value, catalog]) => {if (alive) setLoaded({status: 'ready', options: value, catalog: catalog || []});})
      .catch(() => {if (alive) setLoaded({status: 'failed', options: fallbackOptions(shot ? (frame ? FRAME_APP : FALLBACK_SHOT_APP) : undefined), catalog: []});});
    return () => {alive = false;};
  }, [kind, id, shot && output]);  // eslint-disable-line react-hooks/exhaustive-deps
  // Another output is another list of workflows: the shot row starts over on it (the takes count stays).
  useEffect(() => {if (shot) setChosen({appCode: null, values: {}});}, [shot && output]);  // eslint-disable-line react-hooks/exhaustive-deps
  const options = loaded.options || fallbackOptions(shot ? (output === 'frame' ? FRAME_APP : FALLBACK_SHOT_APP) : undefined);
  const app = startingApp(options, chosen.appCode);
  const controls = slotControls(app, chosen.values, ratio);
  const inputs = shot ? nodeControls((loaded.catalog || []).find(item => item.appCode === app?.appCode)) : {};
  const choices = secondChoices(inputs.duration, planned), seconds = chosen.seconds ?? startingSeconds(choices, planned), audio = chosen.audio ?? true;
  // A Router card makes one take per request (the server refuses count > 1 for it): its count stays at one, and the row says why.
  const takes = shot && app?.quotable ? 1 : count;
  const style = shot ? '' : options.style?.name || styleName;
  const body = () => shot ? shotRequestBody(app, controls, {inputs, seconds, audio}) : requestBody(app, controls);
  if (bodyRef) bodyRef.current = app ? {...body(), ...(shot ? {count: takes} : {})} : null;
  const ask = async () => {
    setQuote({status: 'loading'});
    try {setQuote({status: 'ready', data: await storyRequest(`/${kind}s/${id}/router-quotes`, 'POST', {...body(), kind: kind === 'asset' || output === 'frame' ? 'image' : 'video'})});}
    catch (err) {setQuote({status: 'error', message: err.message});}
  };
  const change = patch => {setChosen(current => ({...current, ...patch})); setQuote(null);};
  const ready = loaded.status === 'ready' || (loaded.status === 'failed' && shot);
  const select = control => <select key={control.key} aria-label={t('generation.control_' + control.kind, {name:control.key})} title={t('generation.control_' + control.kind, {name:control.key})}
    value={control.value} disabled={generating || disabled} onChange={event => change({values: {...chosen.values, [control.key]: event.target.value}})}>
    {control.options.map(option => <option key={option}>{option}</option>)}</select>;
  const sound = shot && inputs.audio && <button type="button" key="sound" className="gen-toggle" aria-pressed={audio} disabled={generating || disabled} title={t('composer.sound')}
    onClick={() => change({audio: !audio})}>{t(audio ? 'composer.soundOn' : 'composer.soundOff')}</button>;
  // The shot row: the ratio always in More; resolution and sound there too when narrow.
  const folded = shot ? [...controls.filter(control => control.kind === 'ratio' || narrow), ...(narrow && sound ? [sound] : [])] : [];
  const inline = controls.filter(control => !shot || (control.kind !== 'ratio' && !narrow));
  const words = shot ? generateLabel({output, count: takes, estimate: app?.quotable ? null : estimateOf(app), dirty}) : null;
  return <section ref={root} className={'gen-bar' + (shot ? ' is-shot' : '')} aria-label={t('generation.title')}>
    {loaded.status === 'failed' && <p className="gen-error" role="status">{t('generation.optionsFailed')}</p>}
    <div className="gen-row">
      {lead}
      {ready && options.apps.length > 0 && <>
        <select className="gen-workflow" aria-label={t('generation.workflow')} title={shot && app?.name ? app.name : t('generation.workflow')} value={app?.appCode || ''} disabled={generating || disabled} onChange={event => change({appCode: event.target.value, values: {}, seconds: undefined})}>
          {!app && <option value="">—</option>}
          {options.apps.map(item => <option key={item.appCode} value={item.appCode} disabled={!item.configured}>{item.name}{item.configured ? '' : ' — ' + t('generation.' + reasonKey(item.reason))}</option>)}</select>
        {shot && (choices.length ? <select className="gen-seconds" aria-label={t('composer.seconds')} title={t('composer.seconds')} value={seconds ?? ''} disabled={generating || disabled}
          onChange={event => change({seconds: Number(event.target.value)})}>{choices.map(value => <option key={value} value={value}>{t('generation.seconds', {value})}</option>)}</select>
          : Number.isFinite(planned) && output !== 'frame' && <span className="gen-static" title={t('composer.secondsPlanned')}>{t('generation.seconds', {value:Math.round(planned * 10) / 10})}</span>)}
        {inline.map(select)}
        {!narrow && sound}
        {folded.length > 0 && <details className="gen-more"><summary title={t('composer.moreHint')}>{t('composer.more')}</summary>
          <div className="gen-more-list">{folded.map(item => item?.key && item.options ? <label key={item.key}><span>{t('generation.control_' + item.kind, {name:item.key})}</span>{select(item)}</label> : item)}</div></details>}
      </>}
      {style && <span className="gen-style" title={t('generation.style', {name:style})}>{style}</span>}
      <span className="gen-end">
        {shot && (app?.quotable ? <span className="gen-static gen-count" title={t('composer.countRouter')}>{t('composer.countOption', {count:1})}</span>
          : <select className="gen-count" aria-label={t('composer.count')} title={t('composer.count')} value={count} disabled={generating || disabled} onChange={event => setCount(clampCount(event.target.value))}>
            {Array.from({length: MAX_TAKES}, (_, index) => index + 1).map(value => <option key={value} value={value}>{t('composer.countOption', {count:value})}</option>)}</select>)}
        {app && ready && <Cost app={app} quote={quote} onQuote={ask} shot={shot}/>}
        <button type="button" className={shot ? 'primary composer-go' : 'world-act gen-go'} disabled={disabled || generating || !app}
          onClick={() => onGenerate(shot ? {...body(), count: takes} : body())}>{shot ? t(words.key, {...words.params, time:words.params.seconds ? timeText(words.params.seconds) : ''}) : label}</button>
        {generating && canCancel && <button type="button" className="world-tool" onClick={onCancel}>{t('world.cancelGeneration')}</button>}
      </span>
    </div>
    {loaded.status === 'ready' && !app && <p className="gen-error" role="status">{options.apps.length ? t('generation.noneReady') : t('generation.noApps')}</p>}
  </section>;
}
