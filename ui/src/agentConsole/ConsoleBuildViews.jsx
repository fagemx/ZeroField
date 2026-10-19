import { useState } from 'react';
import { t } from '../i18n/index.js';
import { parseObject } from './model.js';
import { ResourceEditor } from './ConsoleManagedViews.jsx';
import { Check, JsonField, JsonView, Loading, SelectField, TextField, useConsole, useDraft, useLoad } from './shared.jsx';

export function ConsoleSkills() {
  const state=useLoad('/skills');const {resource,navigate,canEdit}=useConsole();
  return <><p>{t('console.skillsNotice')}</p><Loading state={state}/><ResourceEditor endpoint="skills" items={state.data?.items} resourceKey="skill_key" selectedKey={resource} onSelect={key=>navigate('skills',key)} canWrite={canEdit}/></>;
}
export function ConsolePlayground() {
  const {catalog,resource,canExecute,canEdit,request,action,navigate,episodeId}=useConsole();
  const [config,setConfig]=useDraft('playground:'+resource,{agent_key:resource || 'coordinator',objective:'',episode_id:episodeId,media:[],raw:'',useRaw:false});
  const [result,setResult]=useState(null);
  const update=(key,value)=>setConfig({...config,[key]:value});
  const run=mode=>action(async()=>{
    const body={mode,objective:config.objective,episode_id:config.episode_id,media:config.media};
    if(config.useRaw){body.draft=parseObject(config.raw);if(mode==='live')body.save_and_run=true;}else body.agent_key=config.agent_key;
    if(mode==='live')body.client_request_id=crypto.randomUUID();
    const next=await request('/playground',{method:'POST',body});setResult(next);
    if(next.session_id)navigate('sessions',next.session_id);
  });
  return <><p>{t('console.playgroundNotice')}</p><SelectField label="agent" value={config.agent_key} onChange={v=>update('agent_key',v)} options={(catalog.agents || []).filter(a=>a.enabled && !a.read_only && a.runtime_kind==='builtin_llm').map(a=>({value:a.agent_key,label:a.display_name}))}/>
    {canEdit && <Check label="useRaw" checked={config.useRaw} onChange={v=>update('useRaw',v)}/>}{config.useRaw && <JsonField label="rawAgent" value={config.raw} onChange={v=>update('raw',v)} rows={15}/>}
    <TextField label="objective" value={config.objective} onChange={v=>update('objective',v)} multiline maxLength={4000} rows={5}/><TextField label="episode" value={config.episode_id} onChange={v=>update('episode_id',v)}/><TextField label="mediaIds" value={config.media.join(', ')} onChange={v=>update('media',v.split(',').map(s=>s.trim()).filter(Boolean))}/>
    <div className="ac-actions"><button disabled={!canExecute || !config.objective.trim()} onClick={()=>run('dry_run')}>{t('console.dryRun')}</button><button disabled={!canExecute || !config.objective.trim()} onClick={()=>run('live')}>{t(config.useRaw ? 'console.saveAndRun':'console.runLive')}</button></div>
    {result && <JsonView label="compiledInput" value={result} open/>}
  </>;
}
