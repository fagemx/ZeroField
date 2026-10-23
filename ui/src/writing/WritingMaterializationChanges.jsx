import { useTranslation } from '../i18n/react.jsx';
import { documentText } from './writingModel.js';
const p='writing.authoring.';
// Informational projection only: apply still sends frozen action IDs, never this text.
export function WritingMaterializationChanges({proposal,actions,selected}) {
  const {t}=useTranslation();
  const chosen=actions.filter(action=>selected.some(item=>item.actionId===action.actionId));
  const whole=chosen.some(action=>action.kind==='adopt_whole');
  const nodes=proposal.sourceDoc?.content || proposal.doc?.content || [];
  return <section className="writing-materialization" aria-label={t(p+'materializationTitle')}>
    <h3>{t(p+'materializationTitle')}</h3><p role="note">{t(p+'materializationHelp')}</p>
    {(proposal.materializationChanges || []).map(change=><article key={change.sceneKey}>
      <h4>{change.sceneKey}</h4><p>{t(p+(whole||chosen.some(action=>action.sceneKey===change.sceneKey)?'conversionSelected':'conversionNotSelected'))}</p>
      <div className="writing-compare-columns"><div><h4>{t(p+'authoredSourceTitle')}</h4><pre>{change.source?.title}</pre></div><div><h4>{t(p+'canonicalHeading')}</h4><pre>{change.headingText}</pre></div></div>
      <p>{t(p+'sourceDocumentHash',{hash:change.source?.docHash || '—'})}</p>
      <p>{t(p+'sourceBlockLineage')} <code>{[change.source?.headingBid,...(change.source?.blockBids || [])].filter(Boolean).join(' · ')}</code></p>
      <p>{t(p+'materializedHeadingId',{id:change.headingBid})}</p>
      {(change.quotedBlockBids || []).map(bid=>{const node=nodes.find(node=>node.attrs?.bid===bid);return <div key={bid}><strong>{t(p+'quotedSourceBlock',{id:bid})}</strong><pre>{node?documentText(node):t(p+'conversionTextUnavailable')}</pre></div>;})}
    </article>)}
  </section>;
}
