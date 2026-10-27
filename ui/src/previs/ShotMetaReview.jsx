import { useLocale } from '../i18n/react.jsx';
import { t as uiText } from '../i18n/index.js';

// SPEC_20 R18: a crew member's proposed 3D plan for the shot on stage, reviewed in the inspector. review comes from
// shotMetaReview(); busy is '' or the decision on its way ('approve' | 'reject'). The proposed camera is the dashed path in the
// viewport and its marks are the rings on the overhead plan; Preview puts the whole proposed plan on stage until Back.
const previs = (key, params) => uiText('previs.' + key, params);
function fieldValue(key, value) {
  if (value === undefined || value === null) return '—';
  if (key === 'lens') return `${value}mm`;
  if (key === 'seconds') return `${value} s`;
  const prefix = { set: 'set_', move: 'move_', action: 'action_', facing: 'facing_', mood: 'mood_' }[key];
  return prefix ? previs(prefix + value, { defaultValue: String(value) }) : String(value);
}
export function changeText(change) {
  if (change.kind === 'field') return uiText('stage.metaChange', { what: previs(change.label), from: fieldValue(change.key, change.from), to: fieldValue(change.key, change.to) });
  if (change.kind === 'castAdded') return uiText('stage.metaChangeCastAdded', { codes: change.codes.join(', ') });
  if (change.kind === 'castRemoved') return uiText('stage.metaChangeCastRemoved', { codes: change.codes.join(', ') });
  return uiText({ camera: 'stage.metaChangeCamera', blocking: 'stage.metaChangeBlocking', acting: 'stage.metaChangeActing' }[change.kind] || 'stage.metaChangeOther');
}

export function ShotMetaReview({ review, previewing = false, busy = '', disabled = false, onPreview, onApprove, onReject }) {
  useLocale();
  if (!review) return null;
  const deciding = Boolean(busy) || disabled;
  return <section className="previs-proposal previs-meta-proposal" aria-label={uiText('stage.metaTitle')} aria-busy={busy ? true : undefined}>
    <h3>{uiText('stage.metaTitle')}</h3>
    <p className="previs-note">{uiText('stage.metaBy', { author: review.author || uiText('stage.metaCrew'), shot: review.label })}{' '}
      {uiText('stage.metaBase', { base: review.baseRevision })}</p>
    {review.summary && <p className="previs-meta-summary">{review.summary}</p>}
    {review.same ? <p className="previs-note">{uiText('stage.metaNoChanges')}</p>
      : <ul className="previs-meta-changes">{review.changes.map((change, index) => <li key={index}>{changeText(change)}</li>)}</ul>}
    <p className="previs-note">{uiText('stage.metaLegend')}</p>
    {review.stale && !review.error && <p className="previs-meta-stale">{uiText('stage.metaStale', { current: review.currentRevision })}</p>}
    {review.error && <p className="shot-proposal-error" role="alert">{review.error}</p>}
    <div className="previs-proposal-actions">
      <button type="button" aria-pressed={previewing} disabled={disabled} onClick={onPreview}>{uiText(previewing ? 'stage.metaBack' : 'stage.metaPreview')}</button>
      {review.canDecide && <button type="button" className="apply" disabled={deciding || review.blockedByDraft} onClick={onApprove}>
        {uiText(busy === 'approve' ? 'stage.metaApproving' : 'stage.metaApprove')}</button>}
      {review.canDecide && <button type="button" disabled={deciding} onClick={onReject}>{uiText('stage.metaReject')}</button>}
    </div>
    {review.blockedByDraft && <p className="previs-note">{uiText('stage.metaDraftFirst')}</p>}
    {review.readOnly && <p className="previs-note">{uiText('stage.metaReadOnly')}</p>}
    {review.more > 0 && <p className="previs-note">{uiText('stage.metaMore', { count: review.more })}</p>}
  </section>;
}

// The proposal's marks on the overhead plan: a dashed ring where it puts each person, labelled with their cast code.
// project(x, z) is the stage's plan projection (null when the point is off the plan).
export function GhostMarks({ marks = [], project }) {
  useLocale();
  return <div className="plan-ghosts" aria-hidden="true">
    {marks.map(m => {
      const spot = project(m.mark[0], m.mark[1]);
      return spot ? <span key={m.id} className="plan-ghost-mark" style={{ left: spot.x, top: spot.y }} title={uiText('stage.metaMark', { who: m.code || '—' })}>
        {m.code && <b>{m.code.replace(/^@/, '')}</b>}</span> : null;
    })}
  </div>;
}
