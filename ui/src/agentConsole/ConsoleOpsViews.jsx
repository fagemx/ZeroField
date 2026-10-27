import { useCallback, useEffect, useRef, useState } from 'react';
import { currentLocale, t } from '../i18n/index.js';
import { Icon } from '../Icon.jsx';
import { consoleError } from './model.js';
import { useConsole } from './shared.jsx';
import { CONTEXT_COMMAND, HEALTH_STEPS, PULL_COMMAND, QUEUE_GROUPS, TONE, gpuShare, gib, offPreset, pauseLine, providerLine,
  queueLine, queueTotals, remainingSteps, stepText, validCost, vram } from './opsModel.js';

// SPEC_20 R36/R38-R40 inside the existing pages: Dashboard carries the automation switch, the GPU panel and
// the project-wide queue; Providers & API Keys carries the guided model setup and health check.

export function Pill({tone='muted',children}) {return <span className={'ac-pill '+tone}>{children}</span>;}
const when=value=>{const date=value ? new Date(value):null;return date && !Number.isNaN(date.getTime()) ? date.toLocaleString(currentLocale(),{dateStyle:'medium',timeStyle:'short'}):'';};

/** Loads one operations endpoint now, on refresh and every `every` ms; requests abort on unmount. */
export function useOps(path,every) {
  const {request,revision}=useConsole();
  const [state,setState]=useState({});const [tick,setTick]=useState(0);
  useEffect(()=>{
    const controller=new AbortController();
    const load=()=>request(path,{signal:controller.signal}).then(data=>{if(!controller.signal.aborted)setState({data});}).catch(error=>{if(!controller.signal.aborted && error.name!=='AbortError')setState(current=>({...current,error}));});
    load();const timer=every ? setInterval(load,every):null;
    return()=>{controller.abort();if(timer)clearInterval(timer);};
  },[path,request,revision,tick,every]);
  return [state,()=>setTick(n=>n+1)];
}

// ---------- R40 automation switch ----------
export function PausedBanner() {
  const {overview,canEdit,action,request,refresh,navigate}=useConsole();
  const automation=overview?.automation;
  if(!automation?.paused)return null;
  return <section className="ac-paused" role="status"><Icon name="pause"/><div><strong>{t('console.ops.automation.bannerTitle')}</strong><p>{pauseLine(automation)}</p><p>{t('console.ops.automation.scope')}</p></div>
    {canEdit ? <button onClick={()=>action(async()=>{await request('/automation',{method:'POST',body:{paused:false}});refresh();})}>{t('console.ops.automation.resume')}</button>
      : <button onClick={()=>navigate('dashboard')}>{t('console.ops.automation.details')}</button>}</section>;
}
export function AutomationSwitch() {
  const {overview,canEdit,action,request,refresh}=useConsole();
  const automation=overview?.automation || {paused:false};const [reason,setReason]=useState('');
  const set=paused=>action(async()=>{await request('/automation',{method:'POST',body:paused ? {paused,reason:reason.trim()}:{paused}});setReason('');refresh();});
  return <section className={'ac-card ac-automation'+(automation.paused ? ' paused':'')} aria-labelledby="ac-automation-title">
    <header><h2 id="ac-automation-title">{t('console.ops.automation.title')}</h2><Pill tone={automation.paused ? 'warn':'ok'}>{t(automation.paused ? 'console.ops.automation.paused':'console.ops.automation.running')}</Pill></header>
    <p>{t('console.ops.automation.explain')}</p>
    <ul className="ac-scope">{['grading','preproduction','deployments'].map(item=><li key={item}>{t('console.ops.automation.item.'+item)}</li>)}</ul>
    {automation.paused && <p className="ac-strong">{pauseLine(automation)}</p>}
    {!canEdit ? <p><small>{t('console.ops.automation.adminOnly')}</small></p> : automation.paused
      ? <div className="ac-actions"><button onClick={()=>set(false)}>{t('console.ops.automation.resume')}</button></div>
      : <div className="ac-pause-form"><label className="ac-field"><span>{t('console.ops.automation.reason')}</span><input maxLength={300} value={reason} placeholder={t('console.ops.automation.reasonPlaceholder')} onChange={e=>setReason(e.target.value)}/></label><button className="ac-danger" onClick={()=>set(true)}>{t('console.ops.automation.pause')}</button></div>}
    <p><small>{t('console.ops.automation.manual')}</small></p>
  </section>;
}

// ---------- R38 GPU panel ----------
export function GpuPanel() {
  const [state,reload]=useOps('/gpu',15000);const panel=state.data;
  return <section className="ac-card ac-gpu" aria-labelledby="ac-gpu-title">
    <header><h2 id="ac-gpu-title">{t('console.ops.gpu.title')}</h2><button className="ac-icon-button" aria-label={t('console.refresh')} title={t('console.refresh')} onClick={reload}><Icon name="refresh"/></button></header>
    {!panel ? <p role="status">{state.error ? t('console.loadFailed'):t('console.loading')}</p> : <>
      {panel.gpuOwner?.owner && <p className="ac-strong">{t('console.ops.gpu.owner',{holder:panel.gpuOwner.owner.holder || '?',purpose:panel.gpuOwner.owner.purpose || '',since:when(panel.gpuOwner.owner.since)})}</p>}
      <ComfyStatus comfy={panel.comfy}/>
      <h3>{t('console.ops.gpu.models')}</h3>
      {panel.modelServers.length===0 ? <p>{t('console.ops.gpu.noLocalModelServer')}</p> : panel.modelServers.map(server=><ModelServer key={server.host+':'+server.port} server={server}/>)}
      <p><small>{t('console.ops.gpu.checked',{at:when(panel.checkedAt)})} {t('console.ops.gpu.readOnly')}</small></p>
    </>}
  </section>;
}
function ComfyStatus({comfy}) {
  if(comfy.state!=='ok')return <><h3>ComfyUI</h3><p className="ac-strong">{t('console.ops.gpu.comfy.'+comfy.state,{host:comfy.host,port:comfy.port})}</p></>;
  return <><h3>ComfyUI {comfy.version && <small className="ac-inline">{comfy.version}</small>}</h3>
    {comfy.devices.map((device,index)=>{const memory=vram(device);return <div className="ac-device" key={index}><span>{device.name}</span>
      {memory ? <><div className="ac-meter" role="meter" aria-label={t('console.ops.gpu.vramUsed')} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(memory.share*100)}><i style={{width:Math.round(memory.share*100)+'%'}}/></div>
        <p className="ac-figures"><strong>{t('console.ops.gpu.free',{free:memory.free})}</strong> <span>{t('console.ops.gpu.ofTotal',{total:memory.total})}</span></p></> : <p>{t('console.ops.gpu.noVram')}</p>}</div>;})}
    <p>{comfy.queue ? t('console.ops.gpu.queue',{running:comfy.queue.running,pending:comfy.queue.pending}) : t('console.ops.gpu.queueUnknown')}</p></>;
}
function ModelServer({server}) {
  if(server.state!=='ok')return <p className="ac-strong">{t('console.ops.gpu.server.'+server.state,{host:server.host,port:server.port})}</p>;
  if(!server.models.length)return <p>{t('console.ops.gpu.noneLoaded',{port:server.port})}</p>;
  return <ul className="ac-rows">{server.models.map(model=><li key={model.name}><span className="ac-row-main"><code>{model.name}</code>{model.parameterSize && <small className="ac-inline">{model.parameterSize}{model.quantization ? ' · '+model.quantization:''}</small>}</span>
    <span className="ac-row-meta">{t('console.ops.gpu.modelVram',{vram:gib(model.vramBytes)})}{gpuShare(model)!==null && ' · '+t('console.ops.gpu.onGpu',{share:gpuShare(model)})}{model.contextLength ? ' · '+t('console.ops.gpu.context',{length:model.contextLength}):''}</span>
    {model.contextLength && model.contextLength<=4096 && <small className="ac-warn-text">{t('console.ops.gpu.smallContext')}</small>}</li>)}</ul>;
}

// ---------- R39 queue and failures (the R12 failure class reads as its plain-language line) ----------
export function QueuePanel() {
  const [days,setDays]=useState(7);const [state,reload]=useOps('/queue?days='+days,15000);const view=state.data;
  const totals=queueTotals(view);
  return <section className="ac-card ac-queue" aria-labelledby="ac-queue-title">
    <header><h2 id="ac-queue-title">{t('console.ops.queue.title')}</h2>
      <label className="ac-inline-field"><span>{t('console.ops.queue.window')}</span><select value={days} onChange={e=>setDays(Number(e.target.value))}>{[1,7,30].map(n=><option key={n} value={n}>{t('console.ops.queue.window'+n)}</option>)}</select></label>
      <button className="ac-icon-button" aria-label={t('console.refresh')} title={t('console.refresh')} onClick={reload}><Icon name="refresh"/></button></header>
    {!view ? <p role="status">{state.error ? t('console.loadFailed'):t('console.loading')}</p> : <>
      <dl className="ac-budget ac-queue-kpis"><div><dt>{t('console.ops.queue.active')}</dt><dd>{totals.active}</dd></div><div><dt>{t('console.ops.queue.failed',{days:view.days})}</dt><dd>{totals.failed}</dd></div><div><dt>{t('console.ops.queue.uncertain')}</dt><dd>{view.counts.uncertain}</dd></div></dl>
      {QUEUE_GROUPS.map(group=><QueueGroup key={group} group={group} data={view[group]} counts={view.counts[group]}/>)}
      <Uncertain view={view} onDone={reload}/>
      <p><small>{t('console.ops.queue.privacy')}</small></p>
    </>}
  </section>;
}
function QueueGroup({group,data,counts}) {
  const {catalog}=useConsole();
  const names=Object.fromEntries((catalog.agents || []).map(agent=>[agent.agent_key,agent.display_name || agent.agent_key]));
  const items=[...data.active.map(item=>[item,'active']),...data.failed.map(item=>[item,'failed'])];
  return <section className="ac-queue-group"><h3>{t('console.ops.queue.group.'+group)} <small className="ac-inline">{t('console.ops.queue.groupCounts',{active:counts.active,failed:counts.failed})}</small></h3>
    {items.length===0 ? <p className="ac-quiet">{t('console.ops.queue.nothing')}</p> : <ul className="ac-rows">{items.map(([item,kind])=>{const line=queueLine(group,item);return <li key={item.id}>
      <span className="ac-row-main"><Pill tone={kind==='failed' ? 'bad':'muted'}>{line.state}</Pill><strong>{names[line.who] || line.who}</strong>{line.mine===true && <small className="ac-inline">{t('console.ops.queue.yours')}</small>}{line.mine===false && <small className="ac-inline">{t('console.ops.queue.someoneElse')}</small>}</span>
      <span className="ac-row-meta">{when(line.at)}</span>
      {line.reason && <p className="ac-reason">{line.reason}</p>}{line.detail && <p className="ac-reason"><small>{line.detail}</small></p>}</li>;})}</ul>}
  </section>;
}
function Uncertain({view,onDone}) {
  const {request,action,catalog}=useConsole();const [costs,setCosts]=useState({});
  const name=key=>(catalog.agents || []).find(agent=>agent.agent_key===key)?.display_name || key;
  const count=view.counts.uncertain;
  if(!count)return null;
  if(!view.canReconcile)return <section className="ac-queue-group"><h3>{t('console.ops.queue.uncertainTitle')}</h3><p>{t('console.ops.queue.uncertainMember',{n:count})}</p></section>;
  const reconcile=key=>action(async()=>{await request('/reservations/'+encodeURIComponent(key)+'/reconcile',{method:'POST',body:{observedCostUsd:costs[key].trim()}});setCosts(current=>({...current,[key]:''}));onDone();});
  return <section className="ac-queue-group"><h3>{t('console.ops.queue.uncertainTitle')}</h3><p>{t('console.ops.queue.uncertainHelp')}</p>
    <ul className="ac-rows">{view.uncertain.map(item=><li key={item.requestKey} className="ac-uncertain">
      <span className="ac-row-main"><strong>{name(item.agentKey)}</strong><code>{item.model}</code><small className="ac-inline">{item.provider}</small></span>
      <span className="ac-row-meta">{t('console.ops.queue.ceiling',{amount:item.ceilingUsd ?? '—'})} · {when(item.startedAt)}{item.holdsSlot ? ' · '+t('console.ops.queue.holdsSlot'):''}</span>
      <div className="ac-reconcile"><label><span>{t('console.ops.queue.observedCost')}</span><input inputMode="decimal" placeholder="0.0000" value={costs[item.requestKey] ?? ''} onChange={e=>setCosts(current=>({...current,[item.requestKey]:e.target.value}))}/></label>
        <button disabled={!validCost(costs[item.requestKey])} onClick={()=>reconcile(item.requestKey)}>{t('console.ops.queue.reconcile')}</button></div></li>)}</ul></section>;
}

// ---------- R36 model setup and health check ----------
export function ModelSetup() {
  const {canEdit}=useConsole();
  if(!canEdit)return <section className="ac-card ac-setup"><h2>{t('console.ops.setup.title')}</h2><p>{t('console.ops.setup.adminOnly')}</p></section>;
  return <ModelSetupAdmin/>;
}
function ModelSetupAdmin() {
  const {request,action,refresh}=useConsole();
  const [state,reload]=useOps('/model-setup',0);const setup=state.data;
  const [agent,setAgent]=useState('coordinator');
  const apply=item=>action(async()=>{await request('/model-setup',{method:'POST',body:{agent_key:item.agentKey,version:item.version}});reload();refresh();});
  if(!setup)return <section className="ac-card ac-setup"><h2>{t('console.ops.setup.title')}</h2><p role="status">{state.error ? consoleError(state.error):t('console.loading')}</p></section>;
  const off=offPreset(setup);
  return <section className="ac-card ac-setup" aria-labelledby="ac-setup-title">
    <header><h2 id="ac-setup-title">{t('console.ops.setup.title')}</h2>{off.length===0 ? <Pill tone="ok">{t('console.ops.setup.allOnPreset')}</Pill> : <Pill tone="warn">{t('console.ops.setup.someOffPreset',{n:off.length})}</Pill>}</header>
    <p>{t('console.ops.setup.intro')}</p>
    <ol className="ac-setup-steps">
      <li><h3>{t('console.ops.setup.step1')}</h3>
        <div className="ac-preset"><Icon name="cube"/><div><strong>{setup.preset.label}</strong><p>{t('console.ops.setup.presetBody',{address:setup.preset.base_url})}</p></div></div>
        <ul className="ac-rows">{setup.agents.map(item=><li key={item.agentKey}><span className="ac-row-main"><strong>{item.displayName}</strong><small className="ac-inline">{item.agentKey}</small>
          <Pill tone={item.matchesPreset ? 'ok':item.state==='ok' ? 'muted':'bad'}>{t(item.matchesPreset ? 'console.ops.setup.onPreset':item.state==='ok' ? 'console.ops.setup.custom':'console.ops.setup.broken')}</Pill></span>
          <span className="ac-row-meta">{providerLine(item.provider)}{!item.enabled && ' · '+t('console.ops.setup.disabled')}</span>
          {!item.matchesPreset && <button onClick={()=>apply(item)}>{t('console.ops.setup.usePreset')}</button>}</li>)}</ul>
        {setup.projectDefault && <p><small>{t('console.ops.setup.projectDefault',{key:setup.projectDefault})}</small></p>}</li>
      <li><h3>{t('console.ops.setup.step2')}</h3><p>{t('console.ops.setup.installBody')}</p>
        <Command text={PULL_COMMAND(setup.preset.model)}/><p>{t('console.ops.setup.contextBody',{target:setup.preset.contextTarget})}</p><Command text={CONTEXT_COMMAND}/></li>
      <li><h3>{t('console.ops.setup.step3')}</h3><HealthCheck agents={setup.agents} agent={agent} setAgent={setAgent}/></li>
    </ol>
  </section>;
}
function Command({text}) {
  const [copied,setCopied]=useState(false);
  return <div className="ac-command"><code>{text}</code><button className="ac-icon-button" aria-label={t('console.ops.setup.copy')} title={t('console.ops.setup.copy')} onClick={()=>{navigator.clipboard?.writeText(text).then(()=>{setCopied(true);setTimeout(()=>setCopied(false),1500);}).catch(()=>{});}}><Icon name={copied ? 'check':'doc'}/></button></div>;
}
function HealthCheck({agents,agent,setAgent}) {
  const {request}=useConsole();
  const [results,setResults]=useState({}),[running,setRunning]=useState(false),[error,setError]=useState('');
  const controller=useRef(null);
  useEffect(()=>()=>controller.current?.abort(),[]);
  const run=useCallback(async()=>{
    controller.current?.abort();const own=new AbortController();controller.current=own;
    setRunning(true);setError('');setResults(Object.fromEntries(HEALTH_STEPS.map(step=>[step,{step,status:'pending'}])));
    let queue=[...HEALTH_STEPS];
    try{
      while(queue.length){
        const step=queue.shift();
        setResults(current=>({...current,[step]:{step,status:'running'}}));
        const result=await request('/model-check',{method:'POST',body:{agent_key:agent,step},signal:own.signal});
        if(own.signal.aborted)return;
        const next=remainingSteps(result);
        setResults(current=>({...current,[step]:result,...Object.fromEntries(queue.filter(s=>!next.includes(s)).map(s=>[s,{step:s,status:'skipped'}]))}));
        queue=queue.filter(s=>next.includes(s));
      }
    }catch(err){if(!own.signal.aborted && err.name!=='AbortError'){setError(consoleError(err));setResults(current=>Object.fromEntries(Object.entries(current).map(([k,v])=>[k,v.status==='running' || v.status==='pending' ? {step:k,status:'skipped'}:v])));}}
    finally{if(controller.current===own){setRunning(false);}}
  },[agent,request]);
  const started=Object.keys(results).length>0;
  return <>
    <p>{t('console.ops.check.intro')}</p>
    <div className="ac-check-run"><label className="ac-inline-field"><span>{t('console.agent')}</span><select value={agent} disabled={running} onChange={e=>{setAgent(e.target.value);setResults({});}}>{agents.map(item=><option key={item.agentKey} value={item.agentKey}>{item.displayName}</option>)}</select></label>
      <button className="qs-primary" disabled={running} onClick={run}>{t(running ? 'console.ops.check.running':started ? 'console.ops.check.again':'console.ops.check.run')}</button></div>
    {error && <p className="ac-error" role="alert">{error}</p>}
    <ol className="ac-health">{HEALTH_STEPS.map(step=><HealthStep key={step} step={step} result={results[step]}/>)}</ol>
    <p><small>{t('console.ops.check.governed')}</small></p>
  </>;
}
function HealthStep({step,result}) {
  const status=result?.status || 'pending';const done=!['pending','running','skipped'].includes(status);
  const text=done ? stepText(result):null;
  return <li className={'ac-health-step '+(TONE[status] || 'muted')} aria-busy={status==='running'}>
    <div className="ac-health-head"><strong>{t('console.ops.check.step.'+step)}</strong><Pill tone={TONE[status]}>{t('console.ops.check.status.'+status)}</Pill>{done && result.seconds!=null && <small className="ac-inline">{t('console.ops.check.seconds',{seconds:result.seconds})}</small>}</div>
    {!done && <p className="ac-quiet">{t('console.ops.check.about.'+step)}</p>}
    {text && <p>{text.summary}</p>}
    {text?.fix && <p className="ac-fix">{text.fix}</p>}
    {text?.command && <Command text={text.command}/>}
    {done && result.detail?.reply && <p><small>{t('console.ops.check.reply',{reply:result.detail.reply})}</small></p>}
    {done && result.message && <p><small>{result.message}</small></p>}
  </li>;
}
