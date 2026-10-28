import { useLocale } from '../i18n/react.jsx';
import { t } from '../i18n/index.js';
import { droppedList, referenceRows } from '../assetPanels.js';
import { Icon } from '../Icon.jsx';

// SPEC_21 §4: the part of "See the full prompt" that says which pictures the model is given, in the order it is given them (the prompt
// calls them image 1, image 2, ...), and what each one is for: a face for the identity only, a front for the clothes only, a place for its
// space and materials, a prop for its shape. The blocks the prompt budget left out are listed under it in muted text. Nothing shows when the
// server sent no plan (a preview from before SPEC_21); an empty plan says the picture is made from text alone.
export function ReferencePlan({plan, dropped}) {
  useLocale();
  const rows = referenceRows(plan), blocks = droppedList(dropped);
  if (!Array.isArray(plan) && !blocks.length) return null;
  return <div className="composer-plan" role="group" aria-label={t('composer.planTitle')}>
    {Array.isArray(plan) && <>
      <b className="composer-plan-title">{t('composer.planTitle')}</b>
      {rows.length ? <ol className="composer-plan-list">{rows.map(row => <li key={row.index}>
        <span className="composer-plan-thumb">{row.url ? <img src={row.url} alt="" loading="lazy"/> : <Icon name="image" size={14}/>}<i>{row.index}</i></span>
        <span className="composer-plan-text"><b>{row.code ? '@' + row.code : t('composer.planImage', {index: row.index})}</b>
          <small>{t('composer.planRole_' + row.role)}</small></span>
      </li>)}</ol> : <p className="studio-note">{t('composer.planNone')}</p>}
    </>}
    {blocks.length > 0 && <p className="composer-plan-dropped">{t('composer.planDropped', {blocks: blocks.join(' · ')})}</p>}
  </div>;
}
