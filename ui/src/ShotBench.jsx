import { useEffect, useState } from 'react';
import { api } from './api.js';
import { useLocale } from './i18n/react.jsx';
import { t as uiText } from './i18n/index.js';
import { MediaCell } from './MediaCell.jsx';
import { benchGroup, mediaStages } from './studioModel.js';

// Micro review as a left-to-right bench: inputs (source footage, @cast/@set) -> control passes
// (first frame, motion structure, keyframes) -> output (shot / remaster and the before-after split).
export function ShotBench({ stages, assets, activeColumn, writable, busy, onSelect, onUpload, onRun, onPrevis, onBundle }) {
  useLocale();
  const groups = { input: [], control: [], output: [] };
  for (const stage of stages) groups[benchGroup(stage.label)].push(stage);
  const previs = stages.find(stage => stage.media && /previs|blockout/i.test(stage.label));
  const card = (stage, big) => <section key={stage.column} className={'bench-stage' + (big ? ' is-output' : '') + (activeColumn === stage.column ? ' is-active' : '')}>
    <button className="review-stage-title" aria-pressed={activeColumn === stage.column} onClick={() => onSelect(stage)}>{stage.label}</button>
    {stage.media ? <MediaCell value={stage.value} type={stage.type} label={stage.label} /> : <p className="bench-empty">{uiText('studio.emptyStage')}</p>}
    {big && previs && stage.media && stage.type === 'video' && <CameraFidelity previs={previs.media.url} take={stage.media.url} />}
    {big && onBundle && /\/assets\/pa_[0-9a-f]{32}$/.test(stage.media?.url || '') && <button className="bench-bundle" disabled={busy} title={uiText('studio.takeBundleHint')} onClick={() => onBundle(stage)}>{uiText('studio.downloadTakeBundle')}</button>}
    {writable && <div className="sheet-stage-actions">{onPrevis && /previs|blockout/i.test(stage.label) && <button className="primary" disabled={busy} onClick={() => onPrevis(stage)}>{uiText('previs.open')}</button>}<button disabled={busy} onClick={() => onUpload(stage)}>{uiText('sheetWorkspace.upload')}</button>{!/previs|blockout/i.test(stage.label) && <button disabled={busy} onClick={() => onRun(stage)}>{uiText('studio.runStage')}</button>}</div>}
  </section>;
  const hasInput = groups.input.length > 0 || assets.length > 0;
  return <div className={'shot-bench' + (hasInput ? '' : ' no-input')} aria-label={uiText('studio.shotBench')}>
    {hasInput && <section className="bench-col bench-input"><h3>{uiText('studio.benchInput')}</h3>
      {groups.input.map(stage => card(stage))}
      {assets.length > 0 && <div className="bench-assets" aria-label={uiText('studio.boundAssets')}>{assets.map(asset => <figure key={asset.id}>
        {asset.value ? <MediaCell compact value={asset.value} type={asset.type} label={'@' + asset.id} /> : <span className="sheet-chain-empty">@{asset.id}</span>}
        <figcaption>@{asset.id}</figcaption></figure>)}</div>}
    </section>}
    {hasInput && groups.control.length > 0 && <span className="bench-arrow" aria-hidden="true" />}
    {groups.control.length > 0 && <section className="bench-col bench-control"><h3>{uiText('studio.benchControl')}</h3>{groups.control.map(stage => card(stage))}</section>}
    {groups.output.length > 0 && <span className="bench-arrow" aria-hidden="true" />}
    {groups.output.length > 0 && <section className="bench-col bench-output"><h3>{uiText('studio.benchOutput')}</h3>{groups.output.map(stage => card(stage, true))}</section>}
  </div>;
}

// Every visible shot as a thumbnail; the current one is marked. Arrow keys still step one shot.
export function ShotStrip({ rows, parsed, currentRid, onJump }) {
  useLocale();
  return <nav className="shot-strip" aria-label={uiText('studio.benchStrip')}>{rows.map(row => {
    const stages = mediaStages(parsed, row).filter(stage => stage.media);
    const cover = stages[stages.length - 1];
    return <button key={row.rid} aria-current={row.rid === currentRid ? 'true' : undefined} onClick={() => onJump(row.rid)}>
      <span className="shot-strip-thumb">{cover && (cover.type === 'video' ? <video src={cover.media.url} preload="metadata" muted playsInline /> : <img src={cover.media.url} alt="" loading="lazy" />)}</span>
      <span className="shot-strip-label">{String(row.cells[0]?.value || '—')}</span>
    </button>;
  })}</nav>;
}

const ASSET_URL = /^\/projects\/api\/([a-z0-9-]+)\/assets\/(pa_[0-9a-f]{32})$/;

// How closely a take follows its previs camera: the server scores each (previs, take) pair once, in the background.
export function CameraFidelity({ previs, take }) {
  useLocale();
  const [, slug, previsId] = ASSET_URL.exec(previs) || [], [, , takeId] = ASSET_URL.exec(take) || [];
  const path = slug && previsId && takeId && previsId !== takeId ? `/projects/api/${slug}/camera-fidelity/${previsId}/${takeId}` : null;
  const [result, setResult] = useState(null);
  useEffect(() => {
    if (!path) return undefined;
    let alive = true, timer;
    setResult(null);
    const load = tries => api.get(path).then(data => {
      if (!alive) return;
      setResult(data);
      if (data.status === 'pending' && tries > 0) timer = setTimeout(() => load(tries - 1), 2000);
    }, error => { if (alive) setResult({ status: 'failed', error: error.message }); });
    load(30);
    return () => { alive = false; clearTimeout(timer); };
  }, [path]);
  return path && result ? <FidelityReadout result={result} /> : null;
}

export function FidelityReadout({ result }) {
  useLocale();
  if (result.status !== 'done') return <p className="camera-fidelity is-muted" role="status" title={result.error}>{uiText(result.status === 'pending' ? 'studio.fidelityPending' : 'studio.fidelityFailed')}</p>;
  return <section className="camera-fidelity" aria-label={uiText('studio.fidelityTitle')}>
    <p><strong>{uiText('studio.fidelityTitle')}</strong><span className="camera-fidelity-score">{result.score.toFixed(2)}</span></p>
    <dl>{['tilt', 'pan', 'zoom'].map(axis => <div key={axis}><dt>{uiText('studio.fidelity_' + axis)}</dt>
      <dd>{typeof result[axis]?.travel === 'number' ? result[axis].travel.toFixed(2) + '×' : uiText('studio.fidelityHeld')}</dd></div>)}</dl>
    <small>{uiText('studio.fidelityHint')}</small>
  </section>;
}
