import { useEffect, useRef, useState } from 'react';
import { useLocale } from './i18n/react.jsx';
import { t } from './i18n/index.js';
import { mediaOf } from './sheetModel.js';
import { mediaStages, SHOT_FILTERS } from './studioModel.js';
import { statusClass, statusLabel } from './format.js';
import { CameraFidelity } from './ShotBench.jsx';

// SPEC_15 Shot Stage: the storyboard, the 3D stage and review are views of one shot list, not three stations.
const cover = (parsed, row) => mediaStages(parsed, row).filter(stage => stage.media).find(stage => stage.type === 'image') || null;

export function ShotList({parsed, rows, statusColumn, shotInfo, scenes, currentRid, filter, onFilter, onPick}) {
  useLocale();
  const status = row => statusColumn < 0 ? '' : row.cells[statusColumn]?.value || '';
  const entry = row => ({status:status(row), info:shotInfo[row.rid]});
  const shown = rows.filter(row => SHOT_FILTERS[filter](entry(row)));
  const titles = Object.fromEntries(scenes.map(scene => [scene.sceneId, scene.title]));
  const groups = [];
  for (const row of shown) {
    const key = shotInfo[row.rid]?.sceneId || '';
    if (groups.at(-1)?.key !== key) groups.push({key, rows:[]});
    groups.at(-1).rows.push(row);
  }
  return <nav className="shot-list" aria-label={t('stage.shotList')}>
    <div className="space-list-head"><b>{t('stage.shots')}</b><span className="num">{rows.length}</span></div>
    <div className="shot-filters" role="group" aria-label={t('stage.filter')}>
      {Object.keys(SHOT_FILTERS).map(key => {
        const count = rows.filter(row => SHOT_FILTERS[key](entry(row))).length;
        return (key === 'all' || count > 0) && <button key={key} type="button" aria-pressed={filter === key} onClick={() => onFilter(key)}>{t('stage.filter_' + key)} <span className="num">{count}</span></button>;
      })}
    </div>
    {groups.map(group => <section key={group.key || 'none'}>
      {group.key && <h3>{titles[group.key] || group.key}</h3>}
      <ol>{group.rows.map(row => {
        const image = cover(parsed, row), value = status(row);
        return <li key={row.rid}><button type="button" aria-current={row.rid === currentRid ? 'true' : undefined} onClick={() => onPick(row.rid)}>
          <span className="shot-list-thumb">{image ? <img src={image.media.url} alt="" loading="lazy"/> : <span className="shot-list-blank"/>}</span>
          <span className="shot-list-text"><b>{String(row.cells[0]?.value || '—')}</b><small>{value ? statusLabel(value) : '—'}</small></span>
          <span className={'shot-dot ' + statusClass(value)} aria-hidden="true"/>
        </button></li>;
      })}</ol>
    </section>)}
    {!shown.length && <p className="space-empty">{t('stage.noShots')}</p>}
    <p className="space-foot">{t('stage.shortcuts')}</p>
  </nav>;
}

// The previs and the take of one shot, played together on one clock, with the camera-fidelity score between them.
export function ShotCompare({parsed, row}) {
  useLocale();
  const at = re => parsed.headers.findIndex(header => re.test(header)), types = parsed.table.attrs.column_types || [];
  const video = column => column < 0 ? null : mediaOf(row.cells[column]?.value, types[column])?.url || null;
  const previs = video(at(/previs|blockout/i)), take = video(at(/cinema shot|remaster|output/i));
  const left = useRef(null), right = useRef(null);
  const [time, setTime] = useState(0), [length, setLength] = useState(0), [playing, setPlaying] = useState(false);
  useEffect(() => {setTime(0); setPlaying(false);}, [row.rid]);
  const both = fn => [left.current, right.current].filter(Boolean).forEach(fn);
  const toggle = () => {
    if (playing) {both(v => v.pause()); setPlaying(false); return;}
    both(v => {v.currentTime = Math.min(time, v.duration || time); v.play().catch(() => {});}); setPlaying(true);
  };
  const seek = value => {setTime(value); both(v => {v.currentTime = Math.min(value, v.duration || value);});};
  if (!previs && !take) return <div className="sheet-empty"><p>{t('stage.compareEmpty')}</p></div>;
  return <section className="shot-compare" aria-label={t('stage.view_compare')}>
    <div className="shot-compare-pair">
      {[[previs, left, t('stage.previs')], [take, right, t('stage.take')]].map(([url, ref, label]) => <figure key={label}>
        {url ? <video ref={ref} src={url} muted playsInline preload="metadata" onLoadedMetadata={event => {const seconds = event.currentTarget.duration || 0; setLength(value => Math.max(value, seconds));}}
          onTimeUpdate={ref === left || !previs ? event => setTime(event.currentTarget.currentTime) : undefined} onEnded={() => setPlaying(false)}/>
          : <div className="shot-compare-missing">{t('stage.notYet')}</div>}
        <figcaption>{label}</figcaption></figure>)}
    </div>
    <div className="shot-compare-clock">
      <button type="button" className="shot-play" aria-label={playing ? t('stage.pause') : t('stage.playBoth')} onClick={toggle}>{playing ? '❚❚' : '▶'}</button>
      <input type="range" min={0} max={length || 0} step={0.04} value={Math.min(time, length || 0)} aria-label={t('stage.scrub')} onChange={event => seek(Number(event.target.value))}/>
      <span className="num">{time.toFixed(1)} / {length.toFixed(1)}s</span>
    </div>
    {previs && take && <CameraFidelity previs={previs} take={take}/>}
  </section>;
}
