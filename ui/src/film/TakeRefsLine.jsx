import { useEffect, useState } from 'react';
import { useLocale } from '../i18n/react.jsx';
import { t } from '../i18n/index.js';
import { storyList } from '../storyModel.js';
import { rowProposals } from '../proposalModel.js';
import { mergeTakes, takeRefChange } from '../takeModel.js';
import { Icon } from '../Icon.jsx';

// SPEC_19 R16 (3.7, D4, D5): the "References" line at the top of the shot column. It lists what the adopted take quoted when it was
// sent (the shot view's takeRefs, frozen at that moment): the shot, which of its takes, the second, and whether the frame was the
// first frame or a reference. When the quoted shot has since adopted another take or moved that cut point, the reference is stale:
// the line says what it is now and offers "Re-shoot with the new one", which only puts the cursor in this shot's prompt (the
// composer's [data-shot-prompt="<rowId>"]). Nothing is sent: the tag resolves to the new adoption when the shot is generated.
//
// The take numbers are the quoted shot's own Take list numbers (its candidates and its pending pipeline takes, 1 = oldest), read
// once per quoted shot; until they arrive the line names the shot and the second only.

const tenth = value => (Math.round(Number(value) * 10) / 10).toFixed(1);

// Focus the shot's prompt in the composer, if one is on the page. Returns whether it found one.
export function focusShotPrompt(rowId) {
  const selector = `[data-shot-prompt="${typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(String(rowId)) : String(rowId)}"]`;
  const input = typeof document === 'undefined' ? null : document.querySelector(selector);
  if (!input) return false;
  input.scrollIntoView?.({block: 'nearest'});
  input.focus();
  return true;
}

export function TakeRefsLine({refs = [], shots = [], proposals = [], writable = false, onReshoot}) {
  useLocale();
  const list = Array.isArray(refs) ? refs : [];
  const key = list.map(ref => `${ref.shotId}:${ref.takeUrl}:${ref.nowTakeUrl}`).join('|');
  const [numbers, setNumbers] = useState({});  // {shotId: {takeUrl: number}}
  useEffect(() => {
    const ids = [...new Set(list.map(ref => ref.shotId).filter(Boolean))];
    if (!ids.length) return undefined;
    let alive = true;
    for (const id of ids) {
      const shot = shots.find(item => item.shotId === id);
      storyList(`/shots/${id}/videos`).then(videos => {
        const takes = mergeTakes(videos, shot ? rowProposals(proposals, shot.rowId, shot.tabKey) : [], {});
        if (alive) setNumbers(old => ({...old, [id]: Object.fromEntries(takes.map(take => [take.url, take.number]))}));
      }, () => {});
    }
    return () => {alive = false;};
  }, [key]);  // eslint-disable-line react-hooks/exhaustive-deps
  const items = list.map(ref => ({...ref, number: numbers[ref.shotId]?.[ref.takeUrl] ?? null, nowNumber: numbers[ref.shotId]?.[ref.nowTakeUrl] ?? null,
    change: takeRefChange(ref, shots.find(item => item.shotId === ref.shotId) || null)}));
  return <TakeRefsView items={items} writable={writable} onReshoot={onReshoot}/>;
}

// What a stale reference says changed.
function changeText(item) {
  const change = item.change;
  if (!change) return '';
  if (change.kind === 'gone') return t('refs.gone', {shot: item.shotIndex});
  if (change.kind === 'take') return item.nowNumber ? t('refs.changedTo', {number: item.nowNumber}) : t('refs.changed');
  if (Number.isFinite(change.seconds)) return t(item.edge === 'start' ? 'refs.inMoved' : 'refs.outMoved', {seconds: tenth(change.seconds)});
  return t('refs.cutMoved');
}

// Plain view: items are takeRefs entries with number / nowNumber (or null) and change (takeRefChange()). Nothing when there are none.
export function TakeRefsView({items = [], writable = false, onReshoot}) {
  useLocale();
  if (!items.length) return null;
  const stale = items.some(item => item.stale);
  return <section className={'take-refs' + (stale ? ' is-stale' : '')} aria-label={t('refs.title')}>
    <h3>{t('refs.title')}</h3>
    <ul>{items.map((item, index) => <li key={`${item.shotId}:${item.edge}:${index}`} className={item.stale ? 'is-stale' : undefined}>
      {item.frameUrl ? <img className="take-ref-frame" src={item.frameUrl} alt="" loading="lazy"/> : <span className="take-ref-frame is-blank" aria-hidden="true"/>}
      <span className="take-ref-text">
        <span><b className="num">{item.shotIndex}</b>{item.number && <span>{t('take.number', {number: item.number})}</span>}
          {Number.isFinite(item.at) && <span className="num">{t('refs.at', {edge: t('refs.edge_' + (item.edge === 'start' ? 'start' : 'end')), seconds: tenth(item.at)})}</span>}
          <em className="take-ref-use">{t(item.use === 'first_frame' ? 'refs.use_first_frame' : 'refs.use_reference')}</em></span>
        {item.adopted === false && <small>{t('refs.notAdopted')}</small>}
        {item.stale && <small className="take-ref-change"><Icon name="warning" size={12}/>{changeText(item)}</small>}
      </span>
    </li>)}</ul>
    {stale && writable && <button type="button" className="take-refs-reshoot" title={t('refs.reshootHint')} onClick={() => onReshoot?.()}><Icon name="refresh" size={13}/>{t('refs.reshoot')}</button>}
  </section>;
}
