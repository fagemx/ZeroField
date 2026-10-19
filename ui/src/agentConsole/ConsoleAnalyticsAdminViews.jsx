import { useState } from 'react';
import { t } from '../i18n/index.js';
import { LIMIT_FIELDS, budgetRemaining, money, parseObject, pick, pretty } from './model.js';
import { Check, JsonField, JsonView, Loading, SelectField, TextField, useConsole, useDraft, useLoad } from './shared.jsx';

export function Budget({budget={}}) {
  return <dl className="ac-budget"><div><dt>{t('console.accounted')}</dt><dd>{money(budget.accounted_usd)}</dd></div><div><dt>{t('console.reserved')}</dt><dd>{money(budget.pending_usd)}</dd></div><div><dt>{t('console.uncertain')}</dt><dd>{money(budget.uncertain_usd)}</dd></div><div><dt>{t('console.remaining')}</dt><dd>{money(budgetRemaining(budget))}</dd></div><div><dt>{t('console.judge')}</dt><dd>{budget.judge_trial_used_runs ?? '—'} / {budget.judge_trial_effective_cap_runs ?? budget.judge_trial_cap_runs ?? 10} · {t('console.remaining')} {budget.judge_trial_remaining_runs ?? '—'} · {t(budget.judge_trial_mode ? 'console.protected':'console.notProtected')}</dd></div></dl>;
}
export function ConsoleUsage() {
  const [days,setDays]=useDraft('usageDays',30);const state=useLoad('/usage-cost?days='+days);
  return <><p className="ac-notice">{t('console.analyticsNotice')}</p><SelectField label="period" value={String(days)} onChange={v=>setDays(Number(v))} options={['7','30','90','366']}/><Loading state={state}/>{state.data && <><Budget budget={state.data.budget}/><JsonView label="aggregates" value={state.data.aggregates} open/><JsonView label="privateLogs" value={state.data.private_logs} open/></>}</>;
}
export function ConsoleLimits() {
  const state=useLoad('/spend-rate-limits');return <><Loading state={state}/>{state.data && <LimitsEditor data={state.data}/>}</>;
}
function LimitsEditor({data}) {
  const {canEdit,request,action,refresh}=useConsole();
  const [text,setText]=useDraft('limits',pretty(pick(data.settings,LIMIT_FIELDS)));
  const [consent,setConsent]=useState(false);
  let config;try{config=parseObject(text);}catch{/* Preserve raw edits. */}
  const set=(key,value)=>{setConsent(false);setText(pretty({...config,[key]:value}));};
  return <><Budget budget={data.budget}/><p>{t('console.limitsDraft',{mode:t('console.values.'+data.budget.comfy_router_budget_mode)})}</p><p>{t('console.judgeCounting')}</p><p className="ac-warning">{t('console.softWarning')}</p><fieldset disabled={!canEdit}>
    {config && <><div className="ac-grid">{['monthly','session','episode'].map(kind=><TextField key={kind} label={kind+'Cap'} type="number" min={0} step="0.01" value={config['spend_limit_'+kind+'_usd']} onChange={v=>set('spend_limit_'+kind+'_usd',Number(v))}/>)}</div>
    <Check label="judgePreset" checked={config.judge_trial_mode} onChange={v=>set('judge_trial_mode',v)}/><SelectField label="budgetMode" value={config.comfy_router_budget_mode} onChange={v=>set('comfy_router_budget_mode',v)} options={['hard','estimate_soft']}/><SelectField label="onSpendLimit" value={config.on_spend_limit} onChange={v=>set('on_spend_limit',v)} options={['pause','downgrade_open_weights']}/></>}
    <JsonField label="activeLimits" value={text} onChange={v=>{setText(v);setConsent(false);}} rows={17}/>
    {config?.comfy_router_budget_mode==='estimate_soft' && <Check label="softConsent" checked={consent} onChange={setConsent}/>}
    <button disabled={!config || config.comfy_router_budget_mode==='estimate_soft' && !consent} onClick={()=>action(async()=>{
      const body=pick(parseObject(text),LIMIT_FIELDS);if(body.comfy_router_budget_mode==='estimate_soft')body.estimate_soft_consent=consent;
      const result=await request('/spend-rate-limits',{method:'POST',body});setText(pretty(pick(result.settings,LIMIT_FIELDS)));setConsent(false);refresh();
    })}>{t('console.save')}</button>
    {config?.version!==data.settings.version && <button onClick={()=>{if(window.confirm(t('console.replaceDraftConfirm'))){setText(pretty(pick(data.settings,LIMIT_FIELDS)));setConsent(false);}}}>{t('console.loadCurrent')}</button>}
  </fieldset></>;
}
