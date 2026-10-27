import { useEffect, useState } from 'react';
import { useLocale } from '../i18n/react.jsx';
import { t } from '../i18n/index.js';
import { shotId as storyShotId, storyList, storyRequest } from '../storyModel.js';
import { rowProposals } from '../proposalModel.js';
import { adoptLatestPlan, mergeTakes } from '../takeModel.js';

// SPEC_19 §7 decision 6 (3.6): on the overview, once shots are picked, "Adopt latest takes" in the action bar (outlined: the overview
// has no primary button). Each picked shot's newest take is adopted with POST /shots/{id}/adoptions exactly as its ✓ in the shot column
// would: through the pending pipeline proposal behind it, else as a candidate (adoptionBody()). One shot at a time, so the sheet lock
// takes them in order; a shot with nothing to adopt is skipped and the bar says which and why.

// Adopt the newest take of each row. request / list are the story calls (injectable for tests). Never throws: a failure is a skip.
//   [{rid, shot (its label), adopted: true, number, proposal} | {rid, shot, skip: 'none'|'adopted'|'shared'|'unavailable'|'failed', message?}]
export async function adoptLatestTakes({slug, tabKey, rowIds = [], shotInfo = {}, proposals = [], request = storyRequest, list = storyList}) {
  const results = [];
  for (const rid of rowIds) {
    const info = shotInfo[rid] || null, id = info?.shotId || storyShotId(slug, rid), shot = info?.shotIndex || rid;
    try {
      const takes = mergeTakes(await list(`/shots/${id}/videos`), rowProposals(proposals, rid, tabKey), {status: info?.reviewStatus ?? '', adoption: info?.adoption ?? null});
      const plan = adoptLatestPlan(takes);
      if (plan.skip) {results.push({rid, shot, skip: plan.skip}); continue;}
      await request(`/shots/${id}/adoptions`, 'POST', plan.body);
      results.push({rid, shot, adopted: true, number: plan.take.number, proposal: 'proposalId' in plan.body});
    } catch (error) {
      results.push({rid, shot, skip: 'failed', message: error?.message || String(error)});
    }
  }
  return results;
}

// The bar's button. onWrite: the sheet's guarded story write (no open cell draft, one write at a time, reloads the rows and the
// proposals afterwards); it resolves false when the guard refused, and then nothing was sent. Readers do not get the button.
export function AdoptLatestButton({slug, tabKey, rowIds = [], shotInfo = {}, proposals = [], writable = false, disabled = false, onWrite}) {
  useLocale();
  const [busy, setBusy] = useState(false), [report, setReport] = useState(null);
  const key = rowIds.join('|');
  useEffect(() => setReport(null), [key]);
  if (!writable) return null;
  const run = async () => {
    setBusy(true); setReport(null);
    let results = null;
    try {
      await onWrite?.(async () => {results = await adoptLatestTakes({slug, tabKey, rowIds, shotInfo, proposals});}, {proposals: true});
    } finally {
      setBusy(false);
      if (results) setReport(results);
    }
  };
  return <span className="adopt-latest">
    <button type="button" className="adopt-latest-btn" title={t('adoptLatest.hint')} disabled={disabled || busy || !rowIds.length} onClick={run}>
      {busy ? t('adoptLatest.working') : t('adoptLatest.button')}</button>
    {report && <AdoptLatestReport results={report}/>}
  </span>;
}

// "Adopted 3 shots · skipped 2", then each skipped shot and why.
export function AdoptLatestReport({results = []}) {
  useLocale();
  const adopted = results.filter(result => result.adopted).length, skipped = results.filter(result => !result.adopted);
  return <span className="adopt-latest-report" role="status">
    <span>{t('adoptLatest.result', {adopted, skipped: skipped.length})}</span>
    {skipped.length > 0 && <ul>{skipped.map(result => <li key={result.rid}>{t('adoptLatest.reason_' + result.skip, {shot: result.shot, message: result.message || ''})}</li>)}</ul>}
  </span>;
}
