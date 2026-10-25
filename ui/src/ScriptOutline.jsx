import { useEffect, useState } from 'react';
import { useLocale } from './i18n/react.jsx';
import { t } from './i18n/index.js';
import { storyRequest } from './storyModel.js';
import { BindingText } from './ShotBindings.jsx';

// SPEC_15 Story & World: which shot each beat of the script became, and what an edit would leave out of step. The server replays
// the rule that builds shots from beats (scene s, beat i is the i-th shot of that scene) and reports it without writing anything,
// so this is a reading of the production as it stands, never a second copy of it. Nothing here changes the script or a shot.
const first = text => String(text || '').split('\n').find(line => line.trim()) || '';
const clip = (text, size = 96) => text.length > size ? text.slice(0, size - 1).trimEnd() + '…' : text;

// What the outline looks like for an alignment (the saved script's, or the draft's) and the shots the draft would touch.
// lookup (optional): with it, an @code in a beat is drawn as a small tag with its picture, and onOpenAsset opens its card (SPEC_18 R3).
export function OutlineView({view, affected = [], focusRid, checking, lookup, onFocus, onOpen, onLine, onOpenAsset}) {
  useLocale();
  if (!view) return <p className="space-sub" role="status">{t('outline.loading')}</p>;
  if (!view.scenes?.length) return <p className="outline-note" role="status">{t('outline.noScenes')}</p>;
  const hit = new Set(affected), label = new Map(view.scenes.flatMap(scene => scene.beats.filter(beat => beat.shotId).map(beat => [beat.shotId, beat.shotIndex])));
  return <>
    {checking ? <p className="outline-note" role="status">{t('outline.checking')}</p>
      : affected.length > 0 ? <p className="outline-note is-impact" role="status">{t('outline.impact', {count: affected.length, shots: affected.map(id => label.get(id) || id).join(', ')})}</p>
        : null}
    <ol className="outline-scenes">{view.scenes.map(scene => <li key={scene.sceneId}>
      <h3><b className="num">{String(scene.sceneIndex).padStart(2, '0')}</b>{scene.title}</h3>
      <ul>{scene.beats.map(beat => {
        const now = beat.rowId && beat.rowId === focusRid, touched = beat.shotId && hit.has(beat.shotId);
        return <li key={beat.index} className={'is-' + beat.state + (touched ? ' is-affected' : '')}>
          <button type="button" className="outline-line" disabled={!beat.line} onClick={() => onLine?.(beat.line)} title={beat.line ? t('outline.findLine', {line: beat.line}) : t('outline.noLine')}>{beat.line ? 'L' + beat.line : '—'}</button>
          <span className="outline-text">{lookup ? <BindingText text={clip(first(beat.text))} lookup={lookup} onOpen={onOpenAsset}/> : clip(first(beat.text))}</span>
          {beat.rowId ? <button type="button" className="outline-chip" aria-current={now ? 'true' : undefined} title={t('outline.focusShot', {shot: beat.shotIndex})}
            onClick={() => (now ? onOpen?.(beat.rowId, scene.sceneId) : onFocus?.({shotRid: beat.rowId, sceneId: scene.sceneId}))}>{beat.shotIndex}</button>
            : <em className="outline-none">{t('outline.noShot')}</em>}
          {beat.state === 'changed' && !touched && <small>{t('outline.changed')}</small>}
          {touched && <small>{t('outline.affected')}</small>}
        </li>;
      })}</ul>
    </li>)}</ol>
    {view.orphans?.length > 0 && <p className="space-sub">{t('outline.orphans', {shots: view.orphans.map(item => item.shotIndex).join(', ')})}</p>}
  </>;
}

// Reads the alignment of the saved script, and, while the draft differs from it, what saving the draft would touch.
export function ScriptOutline({epId, script, saved = '', version, focusRid, lookup, onFocus, onOpen, onLine, onOpenAsset}) {
  useLocale();
  const [alignment, setAlignment] = useState(null), [impact, setImpact] = useState(null), [error, setError] = useState('');
  const edited = script !== saved;
  useEffect(() => {
    let live = true;
    setError('');
    storyRequest(`/episodes/${epId}/script-alignment`).then(data => {if (live) setAlignment(data);}).catch(failure => {if (live) setError(failure.message);});
    return () => {live = false;};
  }, [epId, version]);
  useEffect(() => {
    setImpact(null);
    if (!edited || !script.trim()) return undefined;
    let live = true;
    const timer = setTimeout(() => {
      storyRequest(`/episodes/${epId}/script-impact`, 'POST', {scriptContent: script}).then(data => {if (live) setImpact(data);}).catch(failure => {if (live) setError(failure.message);});
    }, 600);
    return () => {live = false; clearTimeout(timer);};
  }, [epId, script, edited, version]);
  return <section className="space-block outline" aria-labelledby="world-outline">
    <h2 id="world-outline">{t('outline.title')}</h2>
    <p className="space-sub">{t('outline.hint')}</p>
    {error && <p role="alert" className="canvas-error">{error}</p>}
    <OutlineView view={edited && impact ? impact : alignment} affected={edited ? impact?.affectedShotIds : []} checking={edited && !impact && !error} focusRid={focusRid} lookup={lookup} onFocus={onFocus} onOpen={onOpen} onLine={onLine} onOpenAsset={onOpenAsset}/>
  </section>;
}
