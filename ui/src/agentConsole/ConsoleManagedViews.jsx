import { useEffect, useState } from 'react';
import { t } from '../i18n/index.js';
import { statusLabel } from '../format.js';
import { AGENT_FIELDS, RESOURCE_FIELDS, STUDIO_TOOLS, agentInput, mergeSession, parseObject, pick, pretty, quoteCurrent } from './model.js';
import { Check, Empty, Field, History, JsonField, JsonView, Loading, SelectField, TextField, useConsole, useDraft, useLoad } from './shared.jsx';
import { ProposalRaceView } from '../assistant/ProposalRaceView.jsx';
import { allocationDispatchBody, allocationPath } from '../storyModel.js';
import { MediaCell } from '../MediaCell.jsx';
import { ModelSetup } from './ConsoleOpsViews.jsx';
import { ModelMatrix } from './ConsoleModelMatrix.jsx';

export function ConsoleAgents() {
  const {catalog,resource,navigate,agentDrafts}=useConsole();
  const agents=catalog.agents || [];
  const selected=agents.find(a=>a.agent_key===resource) || agentDrafts[resource];
  return <div className="ac-split"><aside className="ac-list">{agents.map(a=><button key={a.agent_key} aria-current={resource===a.agent_key ? 'true':undefined} onClick={()=>navigate('agents',a.agent_key)}>{a.display_name || a.agent_key}{a.read_only && <small>{t('console.readOnly')}</small>}</button>)}<button onClick={()=>navigate('quickstart')}>{t('console.newAgent')}</button></aside>
    <section>{selected ? <AgentEditor key={selected.agent_key} profile={selected}/> : <Empty/>}</section></div>;
}
function AgentEditor({profile}) {
  const {canEdit,canExecute,request,action,refresh,catalog,navigate}=useConsole();
  const readOnly=profile.read_only || profile.agent_key.startsWith('studio:');
  const [text,setText]=useDraft('agent:'+profile.agent_key,pretty(agentInput(profile)));
  const [raw,setRaw]=useState(false),[saved,setSaved]=useState(false);
  let config;try{config=parseObject(text);}catch{/* Raw draft may be incomplete. */}
  const set=(key,value)=>{setSaved(false);setText(pretty({...config,[key]:value}));};
  const save=()=>action(async()=>{
    const result=await request('/agents',{method:'POST',body:pick(parseObject(text),AGENT_FIELDS)});
    setText(pretty(agentInput(result.agent)));setSaved(true);refresh();
  });
  const disabled=!canEdit || readOnly;
  const tools=[...new Set([...STUDIO_TOOLS,...(config?.allowed_tools || [])])];
  return <><h2>{profile.display_name || profile.agent_key} <small>v{config?.version ?? profile.version}</small></h2>
    {readOnly ? <><p className="ac-notice">{t('console.systemMedia')}</p><JsonView value={profile} open/></> : <>
    <p>{t('console.draftNotice')}</p><div className="ac-actions"><button aria-pressed={raw} onClick={()=>setRaw(!raw)} disabled={!raw && !config}>{t(raw ? 'console.formView':'console.rawView')}</button><button disabled={disabled || !config} onClick={save}>{t('console.save')}</button><button disabled={!canExecute || !config || config.version===0 || !saved && text!==pretty(agentInput(profile))} onClick={()=>navigate('playground',config.agent_key)}>{t('console.launchSaved')}</button>{saved && <span role="status">{t('console.saved')}</span>}</div>
    {raw || !config ? <JsonField label="rawAgent" rows={24} value={text} onChange={value=>{setSaved(false);setText(value);}} disabled={disabled}/> : <fieldset disabled={disabled}>
      <div className="ac-grid"><TextField label="name" value={config.display_name} onChange={v=>set('display_name',v)}/><TextField label="agentKey" value={config.agent_key} disabled/>
      <TextField label="description" value={config.description} onChange={v=>set('description',v)}/><TextField label="concurrency" type="number" min={1} max={32} value={config.max_concurrency} onChange={v=>set('max_concurrency',Number(v))}/>
      <SelectField label="effort" value={config.effort} options={['low','medium','high']} onChange={v=>set('effort',v)}/><SelectField label="environment" value={config.default_environment_key} options={(catalog.environments || []).map(e=>({value:e.env_key,label:e.display_name || e.env_key}))} onChange={v=>set('default_environment_key',v)}/></div>
      <Check label="enabled" checked={config.enabled} onChange={v=>set('enabled',v)}/>
      <h3>{t('console.provider')}</h3><p>{t('console.inheritProvider')}</p>
      <div className="ac-grid">{['kind','base_url','model','api_key_env'].map(key=><TextField key={key} label={'provider_'+key} value={config.provider_config?.[key]} onChange={v=>{const next={...config.provider_config};if(v)next[key]=v;else delete next[key];set('provider_config',next);}}/>)}</div>
      <p>{t('console.referenceOnly')}</p><TextField label="systemPrompt" multiline rows={8} value={config.system_prompt} onChange={v=>set('system_prompt',v)}/>
      <h3>{t('console.pages.skills')}</h3><div className="ac-grid">{(catalog.skills || []).map(s=><label className="ac-check" key={s.skill_key}><input type="checkbox" checked={config.skill_keys?.includes(s.skill_key) || false} onChange={e=>set('skill_keys',e.target.checked ? [...(config.skill_keys || []),s.skill_key] : config.skill_keys.filter(k=>k!==s.skill_key))}/>{s.display_name || s.skill_key} · v{s.version}</label>)}</div>
      <h3>{t('console.toolPolicies')}</h3><p>{t('console.policyNotice')}</p><div className="ac-grid">{tools.map(tool=><div key={tool} className="ac-tool"><label><input type="checkbox" checked={config.allowed_tools?.includes(tool) || false} onChange={e=>set('allowed_tools',e.target.checked ? [...(config.allowed_tools || []),tool] : config.allowed_tools.filter(k=>k!==tool))}/><code>{tool}</code></label><select aria-label={tool+' '+t('console.policy')} value={config.tool_policies?.[tool] || 'auto'} onChange={e=>set('tool_policies',{...config.tool_policies,[tool]:e.target.value})}>{['auto','always_ask','disabled'].map(p=><option key={p} value={p}>{t('console.values.'+p)}</option>)}</select></div>)}</div>
      <h3>{t('console.multiagent')}</h3>{['allow_subagents','allow_workflows'].map(key=><Check key={key} label={key} checked={config.multiagent_config?.[key]} onChange={v=>set('multiagent_config',{...config.multiagent_config,[key]:v})}/>)}
      <TextField label="advisor" value={config.multiagent_config?.advisor_agent_key} onChange={v=>set('multiagent_config',{...config.multiagent_config,advisor_agent_key:v || null})}/>
      <h3>{t('console.grader')}</h3><Check label="enabled" checked={config.outcome_grader?.enabled} onChange={v=>set('outcome_grader',{...config.outcome_grader,enabled:v})}/><TextField label="criteria" multiline rows={3} value={config.outcome_grader?.criteria} onChange={v=>set('outcome_grader',{...config.outcome_grader,criteria:v})}/><TextField label="graderAgent" value={config.outcome_grader?.grader_agent_key} onChange={v=>set('outcome_grader',{...config.outcome_grader,grader_agent_key:v})}/><TextField label="revisions" type="number" min={0} max={3} value={config.outcome_grader?.max_revisions} onChange={v=>set('outcome_grader',{...config.outcome_grader,max_revisions:Number(v)})}/>
      <h3>{t('console.memoryMounts')}</h3>{(catalog.memory_store || []).filter(s=>!s.archived).map(store=>{const mount=config.memory_mounts?.find(m=>m.store_key===store.store_key);return <Field key={store.store_key} label="mount"><span>{store.display_name || store.store_key} · v{store.version}</span><select aria-label={store.store_key} value={mount?.access || ''} onChange={e=>set('memory_mounts',[...(config.memory_mounts || []).filter(m=>m.store_key!==store.store_key),...(e.target.value ? [{store_key:store.store_key,access:e.target.value}] : [])])}>{['','read_only','read_write'].map(v=><option key={v} value={v}>{t('console.values.'+(v || 'unmounted'))}</option>)}</select></Field>;})}
    </fieldset>}
    {profile.version>0 && <><History path={'/agents/'+encodeURIComponent(profile.agent_key)+'/history'}/><JsonView label="currentSaved" value={agentInput(profile)}/><button disabled={disabled} onClick={()=>{if(window.confirm(t('console.replaceDraftConfirm'))){setText(pretty(agentInput(profile)));setSaved(true);}}}>{t('console.loadCurrent')}</button></>}<JsonView label="effectiveConfiguration" value={{provider:profile.effective_provider_config,inherited:profile.provider_inherited,state:profile.provider_state}}/>
    </>}
  </>;
}

const DEFAULT_RESOURCE = {
 skills:{skill_key:'',version:0,display_name:'',category:'custom',summary:'',instructions_md:'',recommended_tools:[],enabled:true},
 environments:{env_key:'',version:0,display_name:'',env_kind:'local_sandbox',config:{},network_access:'restricted',allowed_hosts:[],packages:[],enabled:false},
 providers:{vault_key:'',version:0,display_name:'',provider_config:{},allowed_agent_keys:[],enabled:false},
 'memory-stores':{store_key:'',version:0,display_name:'',scope_kind:'project',scope_id:'',description:'',archived:false},
 'memory-entries':{store_key:'',entry_key:'',version:0,title:'',content_md:'',tags:[],archived:false},
 deployments:{deployment_key:'',version:0,display_name:'',agent_key:'coordinator',env_key:'env_local_4090',initial_prompt:'',playbook:'',target_scope:{},schedule_kind:'manual',timezone:'UTC',budget_cap_usd:1,enabled:false},
};
export function ResourceEditor({endpoint,items,resourceKey,selectedKey,onSelect,canWrite,extra,query='',newItem}) {
  const selected=items?.find(item=>item[resourceKey]===selectedKey);
  // A named resource is editable only once loaded; earlier edits would land in the ':new' draft and be lost.
  return <div className="ac-split"><aside className="ac-list">{(items || []).map(item=><button key={item[resourceKey]} aria-current={selectedKey===item[resourceKey] ? 'true':undefined} onClick={()=>onSelect(item[resourceKey])}>{item.display_name || item.title || item[resourceKey]}<small>v{item.version} · {item[resourceKey]}</small></button>)}<button onClick={()=>onSelect('new')}>{t('console.newResource')}</button></aside><section>{(selected || !selectedKey || selectedKey==='new') && <ResourceForm key={endpoint+':'+(selectedKey || 'new')} endpoint={endpoint} item={selected || newItem || DEFAULT_RESOURCE[endpoint]} resourceKey={resourceKey} canWrite={canWrite} query={query} onSelect={onSelect}/>}{selected && extra?.(selected)}</section></div>;
}
function ResourceForm({endpoint,item,resourceKey,canWrite,query,onSelect}) {
  const {action,request,refresh}=useConsole();
  const draftId=endpoint+':'+(endpoint==='memory-entries' ? item.store_key+':' : '')+(item[resourceKey] || 'new');
  const [text,setText]=useDraft(draftId,pretty(pick(item,RESOURCE_FIELDS[endpoint])));
  const [objectTexts,setObjectTexts]=useDraft(draftId+':structured',{});
  const [raw,setRaw]=useState(false);
  let config;try{config=parseObject(text);}catch{/* Retain invalid JSON until corrected. */}
  const set=(key,value)=>setText(pretty({...config,[key]:value}));
  const merged=()=>{const result=parseObject(text);for(const [key,value] of Object.entries(objectTexts))result[key]=JSON.parse(value);return result;};
  let parseValid=Boolean(config),valid=false;try{const body=merged();valid=[resourceKey,...['display_name','title'].filter(key=>Object.hasOwn(body,key))].every(key=>typeof body[key]==='string' && body[key].trim());}catch{parseValid=false;}
  const save=()=>action(async()=>{const result=await request('/'+endpoint+query,{method:'POST',body:pick(merged(),RESOURCE_FIELDS[endpoint])});const saved=result.item || result.deployment || result.entry;setObjectTexts({});
    // A created resource leaves the shared ':new' draft blank and opens under its own key.
    if(item.version>0)setText(pretty(pick(saved,RESOURCE_FIELDS[endpoint])));else{setText(pretty(pick(item,RESOURCE_FIELDS[endpoint])));onSelect(saved[resourceKey]);}refresh();});
  return <><div className="ac-actions"><button disabled={!parseValid} onClick={()=>{if(!raw){setText(pretty(merged()));setObjectTexts({});}setRaw(!raw);}}>{t(raw ? 'console.formView':'console.rawView')}</button><button disabled={!canWrite || !valid} onClick={save}>{t('console.save')}</button>{item.version>0 && !['deployments','memory-entries'].includes(endpoint) && <History path={'/'+endpoint+'/'+encodeURIComponent(item[resourceKey])+'/history'+query}/>} </div>
    {raw || !config ? <JsonField label="configuration" value={text} onChange={setText} rows={20} disabled={!canWrite}/> : <fieldset disabled={!canWrite}>{RESOURCE_FIELDS[endpoint].filter(k=>Object.hasOwn(config,k)).map(key=>{
      const value=config[key];
      if(key==='version') return <p key={key}>{t('console.version')} {value}</p>;
      if(typeof value==='boolean')return <Check key={key} label={'fields.'+key} checked={value} onChange={v=>set(key,v)}/>;
      if(typeof value==='object' && value!==null)return <JsonField key={key} label={'fields.'+key} value={objectTexts[key] ?? pretty(value)} onChange={v=>setObjectTexts({...objectTexts,[key]:v})} rows={5}/>;
      if(key==='schedule_kind')return <SelectField key={key} label={'fields.'+key} value={value} options={['manual','cron']} onChange={v=>setText(pretty({...config,schedule_kind:v,...(v==='cron' ? {cron_expr:config.cron_expr || '0 2 * * *'} : {})}))}/>;
      return <TextField key={key} label={'fields.'+key} value={value} multiline={['instructions_md','content_md','initial_prompt','playbook','description','summary'].includes(key)} rows={key==='instructions_md'||key==='content_md' ? 8:3} disabled={key===resourceKey && item.version>0} onChange={v=>set(key,typeof value==='number' ? Number(v):v)}/>;
    })}</fieldset>}{!valid && <p role="status">{t('console.requiredConfiguration')}</p>}{item.version>0 && <><JsonView label="currentSaved" value={pick(item,RESOURCE_FIELDS[endpoint])}/><button disabled={!canWrite} onClick={()=>{if(window.confirm(t('console.replaceDraftConfirm'))){setText(pretty(pick(item,RESOURCE_FIELDS[endpoint])));setObjectTexts({});}}}>{t('console.loadCurrent')}</button></>}
  </>;
}

export function ConsoleDeployments() {
  const state=useLoad('/deployments');const {resource,navigate,canEdit,canExecute,action,request}=useConsole();
  return <><p>{t('console.cronNotice')}</p><Loading state={state}/><ResourceEditor endpoint="deployments" items={state.data?.deployments} resourceKey="deployment_key" selectedKey={resource} onSelect={key=>navigate('deployments',key)} canWrite={canEdit} extra={item=><><button disabled={!canEdit || !canExecute || !item.enabled} onClick={()=>action(async()=>{const result=await request('/deployments/'+item.deployment_key+'/trigger',{method:'POST',body:{version:item.version,client_request_id:crypto.randomUUID()}});navigate('sessions',result.session_id || result.trigger?.run_id);})}>{t('console.trigger')}</button><JsonView label="latestTrigger" value={item.latest_trigger}/></>}/></>;
}
export function ConsoleEnvironments() {
  const state=useLoad('/environments');const {resource,navigate,canEdit}=useConsole();
  return <><p className="ac-notice">{t('console.environmentNotice')}</p><Loading state={state}/>{state.data && <><JsonView label="bridges" value={{mcp:state.data.mcp,sdk:state.data.sdk,cli:state.data.cli}}/><ResourceEditor endpoint="environments" items={state.data.environments} resourceKey="env_key" selectedKey={resource} onSelect={key=>navigate('environments',key)} canWrite={canEdit}/></>}</>;
}
export function ConsoleProviders() {
  const state=useLoad('/api-keys');const providers=useLoad('/providers');const {canEdit,resource,navigate,action,request,refresh,catalog}=useConsole();
  const [agent,setAgent]=useDraft('probeAgent','coordinator');const [kind,setKind]=useState('llm');const [health,setHealth]=useState(null);
  return <><ModelSetup/><ModelMatrix/><p className="ac-notice">{t('console.referenceOnly')} {t('console.connectionNotice')}</p><Loading state={state}/><Loading state={providers}/>
    {state.data && <><JsonView label="allowlist" value={state.data.allowlisted_references} open/><SelectField label="defaultProvider" value={state.data.default?.vault_key || ''} disabled={!canEdit} options={[{value:'',label:t('console.noProjectDefault')},...(state.data.references || []).filter(r=>r.enabled).map(r=>({value:r.vault_key,label:r.display_name || r.vault_key}))]} onChange={v=>action(async()=>{await request('/api-keys/default',{method:'POST',body:{version:state.data.default.version,vault_key:v || null}});refresh();})}/></>}
    <ResourceEditor endpoint="providers" items={providers.data?.items} resourceKey="vault_key" selectedKey={resource} onSelect={key=>navigate('api_keys',key)} canWrite={canEdit}/>
    <h3>{t('console.health')}</h3><SelectField label="agent" value={agent} onChange={setAgent} options={(catalog.agents || []).filter(a=>!a.read_only).map(a=>({value:a.agent_key,label:a.display_name}))}/><SelectField label="probeKind" value={kind} onChange={setKind} options={['llm','router','mcp']}/><button disabled={!canEdit} onClick={()=>action(async()=>setHealth(await request('/connections/health',{method:'POST',body:{agent_key:agent,kind,...(kind==='router'?{model:'ltx/ltx-2-5-pro'}:{})}})))}>{t('console.probe')}</button>{health && <JsonView label="health" value={health} open/>}
  </>;
}
export function ConsoleMemory() {
  const {resource,navigate,canEdit,canExecute,episodeId,me}=useConsole();
  const query='?episode_id='+encodeURIComponent(episodeId);const state=useLoad('/memory-stores'+query);
  const selected=state.data?.items?.find(item=>item.store_key===resource);
  return <><p>{t('console.memoryNotice')}</p><Loading state={state}/><ResourceEditor endpoint="memory-stores" query={query} items={state.data?.items} resourceKey="store_key" selectedKey={resource} onSelect={key=>navigate('memory_store',key)} canWrite={canEdit || canExecute && (!selected || selected.scope_kind==='user')} newItem={{...DEFAULT_RESOURCE['memory-stores'],...(!canEdit ? {scope_kind:'user',scope_id:me.actor_id}:{})}}/>{selected && <MemoryEntries key={selected.store_key} store={selected} query={query}/>}</>;
}
function MemoryEntries({store,query}) {
  const state=useLoad('/memory-stores/'+store.store_key+'/entries'+query);const {canEdit,canExecute,action,request,refresh,episodeId}=useConsole();
  const [selected,setSelected]=useDraft('memory-selection:'+store.store_key,'new'),[evidence,setEvidence]=useDraft('consolidate:'+store.store_key,'');
  const items=state.data?.entries || [];const current=items.find(e=>e.entry_key===selected);
  return <><h3>{t('console.entries')}</h3><Loading state={state}/><ResourceEditor endpoint="memory-entries" items={items} newItem={{...DEFAULT_RESOURCE['memory-entries'],store_key:store.store_key}} resourceKey="entry_key" selectedKey={selected} onSelect={setSelected} canWrite={canEdit || store.scope_kind==='user' && canExecute} query={query} extra={entry=>entry.id && <History path={'/memory-entries/'+entry.id+'/history'+query}/>}/>
    <TextField label="reviewedShots" value={evidence} onChange={setEvidence}/><button disabled={!current || !(canEdit || store.scope_kind==='user' && canExecute) || store.archived} onClick={()=>action(async()=>{await request('/memory-stores/consolidate',{method:'POST',body:{store_key:store.store_key,entry_key:current.entry_key,version:current.version,episode_id:episodeId,shot_ids:evidence.split(',').map(s=>s.trim()).filter(Boolean)}});refresh();})}>{t('console.consolidate')}</button>
  </>;
}

export function ConsoleSessions() {
  const state=useLoad('/sessions');const {resource,navigate}=useConsole();const [liveRun,setLiveRun]=useState(null);
  return <div className="ac-split"><aside className="ac-list"><Loading state={state}/>{state.data?.sessions?.length===0 && <Empty/>}{(state.data?.sessions || []).map(item=>{const run=liveRun?.id===item.id ? liveRun:item;return <button key={run.id} onClick={()=>navigate('sessions',run.id)} aria-current={run.id===resource ? 'true':undefined}>{run.objective}<small>{statusLabel(run.status)} · {run.id}</small></button>;})}</aside><section>{resource ? <SessionDetail key={resource} id={resource} onRun={setLiveRun}/> : <Empty/>}</section></div>;
}
function SessionDetail({id,onRun}) {
  const {request,externalRequest,canExecute,action,refresh,slug}=useConsole();const [detail,setDetail]=useState(null),[error,setError]=useState(false),[tick,setTick]=useState(0);
  useEffect(()=>{
    const controller=new AbortController();let cursor='';let previous=null;
    (async()=>{try{while(!controller.signal.aborted){const next=await request('/sessions/'+id+'/events?wait='+(cursor ? 12:0)+(cursor ? '&cursor='+encodeURIComponent(cursor):''),{signal:controller.signal});if(controller.signal.aborted)return;previous=mergeSession(previous,next);setDetail(previous);if(next.changed)onRun(next.run);cursor=next.cursor;if(!next.has_more && ['succeeded','failed','canceled','expired'].includes(next.run?.status))break;if(!next.has_more)await new Promise(resolve=>setTimeout(resolve,200));}}catch(err){if(!controller.signal.aborted)setError(true);}})();
    return ()=>controller.abort();
  },[id,request,tick,onRun]);
  const operate=(path,body)=>action(async()=>{await request('/sessions/'+id+'/'+path,{method:'POST',body:{...body,client_request_id:crypto.randomUUID()}});setTick(n=>n+1);refresh();});
  return <>{error && <p role="alert">{t('console.streamFailed')}</p>}{!detail ? <p role="status">{t('console.loading')}</p> : <>
    <h2>{detail.run.objective}</h2><p>{statusLabel(detail.run.status)} · {id}</p><div className="ac-actions">{['interrupt','cancel'].map(operation=><button key={operation} disabled={!canExecute || ['succeeded','failed','canceled','expired'].includes(detail.run.status)} onClick={()=>operate(operation,{reason:t('console.userCanceled')})}>{t('console.'+operation)}</button>)}</div><p>{t('console.cancelNotice')}</p>
    {(detail.configuration_blockers || []).length>0 && <p role="alert">{t('console.configurationBlocked')}</p>}
    {(detail.gates || []).filter(g=>g.status==='open').map(gate=><Gate key={gate.id} gate={gate} detail={detail} onResolve={(resolution)=>operate('resume',{gate_id:gate.id,resolution})} disabled={!canExecute}/>)}
    {detail.tasks?.some(task=>task.input_snapshot?.console?.consumed_context?.scorecard) && <JsonView label="graderScorecards" value={detail.tasks.map(task=>task.input_snapshot?.console?.consumed_context?.scorecard).filter(Boolean)} open/>}
    <JsonView label="consumedContext" value={detail.tasks?.map(task=>({task_id:task.id,...task.input_snapshot?.console}))} open/>
    <JsonView label="trace" value={{messages:detail.messages,dispatches:detail.dispatches,conversation:detail.conversation}} open/><JsonView label="usage" value={detail.private_usage}/>
    <RouterQuote sessionId={id}/>
  </>}</>;
}
function Gate({gate,detail,onResolve,disabled}) {
  const {externalRequest,slug}=useConsole();
  const [choice,setChoice]=useState(''),[boardGate,setBoardGate]=useState(null),[raceOpen,setRaceOpen]=useState(false),[invalid,setInvalid]=useState(false);
  const options=gate.options || [];
  const kind=gate.gate_kind;
  useEffect(()=>{
    if(!['race_select','proposal_review'].includes(kind))return;
    const controller=new AbortController();
    (async()=>{let cursor='';do{const board=await externalRequest('/projects/api/'+slug+'/orchestration/board?limit=50'+(cursor ? '&cursor='+encodeURIComponent(cursor):''),{signal:controller.signal});const match=board.needs_you?.find(item=>item.gate_id===gate.id);if(match){if(!controller.signal.aborted)setBoardGate(match);return;}cursor=board.cursor;}while(cursor && !controller.signal.aborted);})().catch(()=>{});
    return()=>controller.abort();
  },[gate.id,kind,externalRequest,slug]);
  const proposals=boardGate?.proposals || [];
  return <section className="ac-gate"><h3>{t('console.needsYou')}</h3><p>{gate.question}</p><JsonView label="gateEvidence" value={gate} open/>
    {kind==='race_select' ? <><button disabled={disabled || !boardGate || !proposals.length} onClick={()=>setRaceOpen(true)}>{t('console.compareCandidates')}</button>{raceOpen && <ProposalRaceView gate={boardGate} onSelect={body=>onResolve(body.resolution)} onClose={()=>setRaceOpen(false)}/>}</> : kind==='proposal_review' ? <>{proposals.map(proposal=><section key={proposal.id}><JsonView label="proposal" value={proposal} open/>{['apply','dismiss'].map(decision=><button disabled={disabled} key={decision} onClick={()=>onResolve({proposal_id:proposal.id,decision})}>{t('console.'+decision)}</button>)}</section>)}</> : <>
    {options.length>0 ? <SelectField label="decision" value={choice} onChange={setChoice} disabled={disabled} options={[{value:'',label:t('console.selectDecision')},...options.map((option,index)=>({value:String(option.id ?? index),label:option.label || option.text || String(option)}))]}/> : <JsonField label="resolution" value={choice} onChange={setChoice} disabled={disabled} rows={3}/>}
    <p>{t('console.gateNotice')}</p><button disabled={disabled || !choice} onClick={()=>{try{const resolution=options.length ? choice:JSON.parse(choice);setInvalid(false);onResolve(resolution);}catch{setInvalid(true);}}}>{t('console.confirmResume')}</button>{invalid && <p role="alert">{t('console.invalidJson')}</p>}
    </>}
  </section>;
}
function NativeResults({receipt}) {
  const {externalRequest}=useConsole();const [tasks,setTasks]=useState({});
  useEffect(()=>{
    const controller=new AbortController();
    const ids=receipt.taskIds || (receipt.taskId ? [receipt.taskId]:[]);
    for(const id of ids)(async()=>{try{while(!controller.signal.aborted){const response=await externalRequest('/aivideo/open/v1/tasks/'+encodeURIComponent(id),{signal:controller.signal});if(controller.signal.aborted)return;const task=response.data;setTasks(current=>({...current,[id]:task}));if(!['QUEUED','RUNNING'].includes(task.status))return;await new Promise(resolve=>setTimeout(resolve,800));}}catch(error){if(!controller.signal.aborted)setTasks(current=>({...current,[id]:{taskId:id,status:'UNAVAILABLE'}}));}})();
    return()=>controller.abort();
  },[externalRequest,pretty(receipt)]);
  return <section className="ac-native-results"><h3>{t('console.nativeResults')}</h3>{Object.values(tasks).map(task=><article key={task.taskId}><p>{task.taskId} · {statusLabel(task.status.toLowerCase())}</p>{['FAILED','UNAVAILABLE','CANCELED'].includes(task.status) && <p role="status">{t('console.requestFailed')}</p>}<JsonView label="dispatchResult" value={{taskId:task.taskId,status:task.status,result:task.result}}/>{(task.result?.videoUrl || task.result?.imageUrl) && <MediaCell value={task.result.videoUrl || task.result.imageUrl} type={task.result.videoUrl ? 'video':'image'} label={t('console.nativeResults')}/>}</article>)}</section>;
}
function RouterQuote({sessionId}) {
  const {request,externalRequest,action,canExecute,slug,episodeId,overview,refresh}=useConsole();
  const [input,setInput]=useDraft('quote:'+sessionId,pretty({shot_id:'',appCode:'router-ltx-2-5-pro',modelParams:{'input.duration':2}}));
  const [quote,setQuote]=useState(null),[now,setNow]=useState(Date.now()),[plan,setPlan]=useState(null),[reviewed,setReviewed]=useState(false),[result,setResult]=useState(null),[attempted,setAttempted]=useState(false);
  useEffect(()=>{const timer=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(timer);},[]);
  let allocationForm=false;try{const form=parseObject(input);allocationForm=Boolean(form.shot_id && form.appCode && Object.keys(form).every(key=>['shot_id','appCode'].includes(key)));}catch{/* Invalid form cannot preflight. */}
  const preview=()=>action(async()=>{
    if(!allocationForm)return;
    setQuote(null);setPlan(null);setReviewed(false);
    const form=parseObject(input);const policy=(await externalRequest('/aivideo/open/v1/projects/pj_'+slug+'/production-policy')).data;
    const options={productionPolicy:policy.productionPolicy,budgetMode:policy.productionPolicy==='open_weights_only' ? 'lab_economical':'hybrid_balanced'};
    const response=await externalRequest('/aivideo/open/v1'+allocationPath(slug,episodeId),{method:'POST',body:{...options,shotIds:[form.shot_id],appCode:form.appCode}});
    setPlan({allocation:response.data,options});
  });
  const getQuote=()=>action(async()=>{
    setQuote(null);setReviewed(false);
    const body=plan ? {allocation_id:plan.allocation.allocationId}:parseObject(input);
    const next=await request('/sessions/'+sessionId+'/router-quotes',{method:'POST',body});
    setQuote(next);setAttempted(false);
  });
  const dispatch=()=>action(async()=>{
    if(!quoteCurrent(quote) || !reviewed || attempted || overview?.budget?.comfy_router_budget_mode!=='estimate_soft')return;
    setAttempted(true);
    try{
      let path,body;
      if(plan){path='/episodes/'+episodeId+'/shot-video-generations';body=allocationDispatchBody(plan.allocation,plan.options.budgetMode,plan.options.productionPolicy);}
      else{const form=parseObject(input);if(form.allocation_id)throw new SyntaxError('Preview required');path='/shots/'+encodeURIComponent(form.shot_id)+'/'+(form.kind==='image' ? 'image':'video')+'-generations';body=pick(form,['appCode','modelParams','promptOverride','referenceSourceVideoId']);}
      const response=await externalRequest('/aivideo/open/v1'+path,{method:'POST',body});setResult(response.data);refresh();
    }finally{setQuote(null);setReviewed(false);setPlan(null);}
  });
  return <section className="ac-quote"><h3>{t('console.routerQuote')}</h3><p className="ac-warning">{t('console.softWarning')}</p><p>{t('console.quoteHelp')}</p><p>{t('console.allocationDefaults')}</p><JsonField label="quoteInput" value={input} onChange={v=>{setInput(v);setQuote(null);setPlan(null);setReviewed(false);}} rows={7}/><div className="ac-actions"><button disabled={!canExecute || !allocationForm} onClick={preview}>{t('console.previewAllocation')}</button><button disabled={!canExecute || plan && !plan.allocation.ready} onClick={getQuote}>{t('console.obtainQuote')}</button></div>
    {plan && <JsonView label="allocationIdentity" value={plan.allocation} open/>}{quote && <><p role="status">{t(quoteCurrent(quote,now) ? 'console.quoteFresh':'console.quoteExpired')}</p><JsonView label="quoteIdentity" value={quote} open/><Check label="reviewDispatch" checked={reviewed} onChange={setReviewed}/></>}
    <button disabled={!canExecute || !reviewed || !quoteCurrent(quote,now) || attempted || overview?.budget?.comfy_router_budget_mode!=='estimate_soft'} onClick={dispatch}>{t('console.dispatchExact')}</button>{attempted && <p role="status">{t('console.noPaidReplay')}</p>}{result && <><JsonView label="dispatchResult" value={result} open/><NativeResults key={pretty(result)} receipt={result}/></>}<p>{t('console.quoteDispatch')}</p></section>;
}
