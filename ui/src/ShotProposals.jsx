import { useState } from 'react';
import { useLocale } from './i18n/react.jsx';
import { t } from './i18n/index.js';
import { applyOptions } from './proposalModel.js';

// A crew member's proposal for this shot, reviewed on the shot: the old text struck through, the new text beside it, apply or
// reject right there. A camera change also shows in the 3D Stage as a dashed ghost camera. items come from rowProposals().
export function ShotProposals({items = [], writable, onApply, onDismiss, onShow}) {
  useLocale();
  const [busy, setBusy] = useState(''), [failed, setFailed] = useState({});
  if (!items.length) return null;
  const decide = async (key, work) => {
    setBusy(key); setFailed(old => ({...old, [key]: ''}));
    try {if (!(await work())) setFailed(old => ({...old, [key]: t('shotProposal.failed')}));} finally {setBusy('');}
  };
  return <section className="shot-proposals" aria-label={t('shotProposal.title')}>
    {items.map(entry => {
      const key = entry.proposal.id + ':' + entry.group.index, camera = entry.group.changes.some(change => /camera.*motion|optical|rig|lens/i.test(change.column));
      const message = failed[key] || entry.proposal.error;
      return <article key={key} className="shot-proposal" aria-busy={busy === key || undefined}>
        <header><b>{t('shotProposal.title')}</b>{entry.size > 1 && <small>{t(entry.partial ? 'shotProposal.partOf' : 'shotProposal.together', {count: entry.size})}</small>}</header>
        <dl>{entry.group.changes.map((change, index) => <div key={index}><dt>{change.column}</dt>
          <dd><del>{change.before || t('shotProposal.empty')}</del><ins>{change.after || t('shotProposal.cleared')}</ins></dd></div>)}</dl>
        {message && <p className="shot-proposal-error" role="alert">{message}</p>}
        <div className="shot-proposal-actions">
          <button type="button" className="apply" disabled={!writable || Boolean(busy)} onClick={() => decide(key, () => onApply(entry.proposal, entry.proposal.content, applyOptions(entry)))}>
            {busy === key ? t('shotProposal.applying') : t(entry.partial ? 'shotProposal.apply' : 'shotProposal.applyAll', {count: entry.size})}</button>
          <button type="button" disabled={!writable || Boolean(busy)} onClick={() => decide(key, () => onDismiss(entry.proposal))}>{t('shotProposal.reject')}</button>
          {camera && onShow && <button type="button" className="quiet" onClick={onShow}>{t('shotProposal.showInStage')}</button>}
        </div>
      </article>;
    })}
  </section>;
}
