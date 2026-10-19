import { t } from '../i18n/index.js';
import { TEMPLATES } from './model.js';
import { Loading, TextField, useConsole, useDraft, useLoad } from './shared.jsx';

export function ConsoleQuickstart() {
  const state=useLoad('/quickstart');
  const {canEdit,action,request,navigate,setAgentDraft}=useConsole();
  const [requirements,setRequirements]=useDraft('requirements','');
  const draft=(template_key,text=requirements)=>action(async()=>{
    const result=await request('/quickstart/draft',{method:'POST',body:{template_key,requirements:text}});
    setAgentDraft(result.draft);navigate('agents',result.draft.agent_key);
  });
  return <section><h2>{t('console.buildQuestion')}</h2><p>{t('console.draftNotice')}</p>
    <TextField label="requirements" multiline rows={3} maxLength={4000} value={requirements} onChange={setRequirements}/>
    <div className="ac-actions"><button disabled={!canEdit || !requirements.trim()} onClick={()=>draft('blank')}>{t('console.draftAgent')}</button><button disabled={!canEdit} onClick={()=>draft('blank','')}>{t('console.blank')}</button></div>
    <Loading state={state}/><div className="ac-templates">{(state.data?.templates || []).filter(item=>TEMPLATES.includes(item.template_key)).map(item=><button className="ac-template" disabled={!canEdit} key={item.template_key} onClick={()=>draft(item.template_key)}>
      <span className="ac-badge">{t('console.badges.'+item.badge)}</span><h3>{t('console.templates.'+item.template_key+'.title')}</h3><p>{t('console.templates.'+item.template_key+'.description')}</p><small>{item.skill_keys.join(' · ')}<br/>{item.allowed_tools.join(' · ')}</small>
    </button>)}</div>
  </section>;
}
