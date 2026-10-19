import { useCallback, useEffect, useRef, useState } from 'react';
import { t } from '../i18n/index.js';
import { LanguageSwitch, useLocale } from '../i18n/react.jsx';
import { roleLabel, statusLabel } from '../format.js';
import { GROUPS, consoleError, consoleHash, resourceSearch } from './model.js';
import { ConsoleContext, Empty, JsonView, Loading, consoleRequest, useConsole, useDraft, useLoad } from './shared.jsx';
import { ConsoleQuickstart } from './ConsoleQuickstart.jsx';
import { ConsolePlayground, ConsoleSkills } from './ConsoleBuildViews.jsx';
import { ConsoleAgents, ConsoleDeployments, ConsoleEnvironments, ConsoleMemory, ConsoleProviders, ConsoleSessions } from './ConsoleManagedViews.jsx';
import { Budget, ConsoleLimits, ConsoleUsage } from './ConsoleAnalyticsAdminViews.jsx';
import './agentConsole.css';
import { Icon } from '../Icon.jsx';

const PAGE_ICON={dashboard:'chart',api_keys:'key',playground:'play',skills:'doc',quickstart:'sparkle',agents:'bot',sessions:'comment',deployments:'rocket',environments:'layers',memory_store:'database',usage_cost:'chart',spend_rate_limits:'gauge'};

export function AgentConsoleApp({slug,me,project,route,episodeId,onReturn}) {
  useLocale();
  const lifetime=useRef(null);if(!lifetime.current)lifetime.current=new AbortController();
  const actionController=useRef(null);
  useEffect(()=>{actionController.current?.abort();setError('');},[route.page,route.resource]);
  useEffect(()=>()=>lifetime.current.abort(),[]);
  const base='/projects/api/'+encodeURIComponent(slug)+'/agent-console';
  // Loads carry their own signal; only signal-less action calls follow the pending action, so
  // navigating away during an action cannot abort the next page's load.
  const signals=options=>AbortSignal.any([lifetime.current.signal,...(options.signal ? [options.signal] : actionController.current ? [actionController.current.signal]:[])]);
  const request=useCallback((path,options={})=>consoleRequest(base,path,{...options,signal:signals(options)}),[base]);
  const externalRequest=useCallback((path,options={})=>consoleRequest('',path,{...options,signal:signals(options)}),[]);
  const [revision,setRevision]=useState(0),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [overview,setOverview]=useState(null),[catalog,setCatalog]=useState({});
  const [projects,setProjects]=useState([]);
  const draftKey='zf.console:'+slug+':'+me.actor_id;
  const [agentDrafts,setAgentDrafts]=useState(()=>{try{return JSON.parse(sessionStorage.getItem(draftKey+':newAgents')) || {};}catch{return {};}});
  const refresh=useCallback(()=>setRevision(n=>n+1),[]);
  const navigate=useCallback((page,resource='')=>{window.location.hash=consoleHash(page,resource);},[]);
  useEffect(()=>{
    const controller=new AbortController();
    const options={signal:controller.signal};
    const loadOverview=()=>request('/dashboard',options).then(data=>{if(!controller.signal.aborted)setOverview(data);}).catch(e=>{if(!controller.signal.aborted && e.name!=='AbortError')setError(consoleError(e));});
    loadOverview();const timer=setInterval(loadOverview,5000);
    const resources={agents:['/agents','agents'],skills:['/skills','items'],sessions:['/sessions','sessions'],deployments:['/deployments','deployments'],environments:['/environments','environments'],memory_store:['/memory-stores?episode_id='+encodeURIComponent(episodeId),'items']};
    for(const [key,[path,field]] of Object.entries(resources))request(path,options).then(result=>{if(!controller.signal.aborted)setCatalog(current=>({...current,[key]:result[field]}));}).catch(()=>{});
    return()=>{clearInterval(timer);controller.abort();};
  },[request,revision,episodeId]);
  useEffect(()=>{const controller=new AbortController();consoleRequest('/projects/api/projects','',{signal:controller.signal}).then(result=>setProjects(result.projects || [])).catch(()=>{});return()=>controller.abort();},[]);
  const working=useRef(false);
  const action=async fn=>{
    if(working.current)return;working.current=true;actionController.current=new AbortController();setBusy(true);setError('');
    try{await fn();}catch(err){if(!lifetime.current.signal.aborted && err.name!=='AbortError')setError(consoleError(err));}finally{working.current=false;actionController.current=null;if(!lifetime.current.signal.aborted)setBusy(false);}
  };
  const setAgentDraft=draft=>setAgentDrafts(current=>{
    const next={...current,[draft.agent_key]:draft};try{sessionStorage.setItem(draftKey+':newAgents',JSON.stringify(next));}catch{/* Mounted draft is retained. */}return next;
  });
  const value={slug,me,episodeId,request,externalRequest,revision,refresh,action,navigate,catalog,overview,resource:route.resource,draftKey,canEdit:overview?.can_edit===true,canExecute:overview?.can_execute===true,agentDrafts,setAgentDraft,busy};
  return <ConsoleContext.Provider value={value}><ConsoleShell page={route.page} busy={busy} error={error} projects={projects} project={project} onReturn={onReturn}/></ConsoleContext.Provider>;
}
function ConsoleShell({page,busy,error,projects,project,onReturn}) {
  const {navigate,overview,me,slug,catalog,resource,refresh}=useConsole();
  const [collapsed,setCollapsed]=useDraft('collapsed',false),[search,setSearch]=useState(null);
  const searchRef=useRef(null),searchButton=useRef(null),heading=useRef(null);
  useEffect(()=>{heading.current?.focus();},[page,resource]);
  useEffect(()=>{const listener=event=>{if((event.ctrlKey||event.metaKey) && event.key.toLowerCase()==='k'){event.preventDefault();setSearch(current=>current===null ? '':null);}};window.addEventListener('keydown',listener);return()=>window.removeEventListener('keydown',listener);},[]);
  useEffect(()=>{if(search!==null)searchRef.current?.focus();},[search===null]);
  const closeSearch=()=>{setSearch(null);searchButton.current?.focus();};
  const Views={dashboard:ConsoleDashboard,api_keys:ConsoleProviders,playground:ConsolePlayground,skills:ConsoleSkills,quickstart:ConsoleQuickstart,agents:ConsoleAgents,sessions:ConsoleSessions,deployments:ConsoleDeployments,environments:ConsoleEnvironments,memory_store:ConsoleMemory,usage_cost:ConsoleUsage,spend_rate_limits:ConsoleLimits};
  const View=Views[page];
  return <div className={'agent-console'+(collapsed ? ' ac-collapsed':'')}>
    <aside className="ac-nav"><div className="ac-brand"><strong>{collapsed ? 'ZF':t('console.brand')}</strong><button aria-label={t('console.toggleNav')} aria-expanded={!collapsed} onClick={()=>setCollapsed(!collapsed)}><Icon name="menu"/></button></div>
      <label className="ac-workspace"><span>{t('console.workspace')}</span><select aria-label={t('console.workspace')} value={slug} onChange={e=>{if(e.target.value!==slug)window.location.assign('/projects/'+encodeURIComponent(e.target.value)+'/'+consoleHash(page));}}><option value={slug}>{project.title}</option>{projects.filter(p=>p.slug!==slug).map(p=><option key={p.slug} value={p.slug}>{p.title}</option>)}</select></label>
      <button ref={searchButton} className="ac-search-button" onClick={()=>setSearch('')}>{t('console.search')} <kbd>Ctrl K</kbd></button>
      <nav aria-label={t('console.navigation')}>{Object.entries(GROUPS).map(([group,pages])=><section key={group}><h2>{t('console.groups.'+group)}</h2>{pages.map(key=><button title={t('console.pages.'+key)} key={key} aria-current={page===key ? 'page':undefined} disabled={busy} onClick={()=>navigate(key)}><Icon name={PAGE_ICON[key]}/><span className="ac-nav-label">{t('console.pages.'+key)}</span></button>)}</section>)}</nav>
      <footer><Budget budget={overview?.budget}/><p>{me.name} · {roleLabel(me.role)}</p></footer>
    </aside>
    <div className="ac-stage"><header className="ac-header"><button disabled={busy} onClick={onReturn}>{t('console.returnProduction')}</button><span className="ac-production">{project.title}</span><button onClick={refresh} disabled={busy}>{t('console.refresh')}</button><LanguageSwitch/></header>
      <main aria-busy={busy}><h1 tabIndex={-1} ref={heading}>{t('console.pages.'+page)}</h1>{error && <p className="ac-error" role="alert">{error}</p>}{!overview ? <p role="status">{t('console.loading')}</p> : <fieldset disabled={busy}><View key={page}/></fieldset>}</main>
    </div>
    {search!==null && <div className="ac-search-backdrop" onClick={closeSearch}><section className="ac-search-dialog" role="dialog" aria-modal="true" aria-label={t('console.search')} onClick={e=>e.stopPropagation()} onKeyDown={event=>{if(event.key==='Escape'){event.preventDefault();closeSearch();}if(event.key==='Tab'){const controls=event.currentTarget.querySelectorAll('input,button');const first=controls[0],last=controls[controls.length-1];if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}}if(event.key==='ArrowDown' && document.activeElement===searchRef.current){event.preventDefault();event.currentTarget.querySelector('.ac-search-results button')?.focus();}}}>
      <label>{t('console.search')}<input ref={searchRef} value={search} onChange={e=>setSearch(e.target.value)}/></label><button onClick={closeSearch}>{t('console.close')}</button><div className="ac-search-results">{resourceSearch(catalog,search).map(item=><button key={item.page+item.key} onClick={()=>{navigate(item.page,item.resource);closeSearch();}}>{item.label}<small>{t('console.pages.'+item.page)}</small></button>)}</div>
    </section></div>}
  </div>;
}
function ConsoleDashboard() {
  const {overview,navigate}=useConsole();
  return <><p>{t('console.dashboardNotice')}</p><div className="ac-kpis">{['needs_you','working','done','idle'].map(key=><button key={key} onClick={()=>navigate('sessions')}><strong>{overview.counts?.[key] ?? '—'}</strong>{t('console.counts.'+key)}</button>)}</div><Budget budget={overview.budget}/><JsonView label="workerState" value={overview.builtin_worker}/><JsonView label="environmentStates" value={overview.environments}/><h2>{t('console.recentSessions')}</h2>{overview.recent_sessions?.length ? overview.recent_sessions.map(run=><button className="ac-recent" key={run.id} onClick={()=>navigate('sessions',run.id)}>{run.objective} · {statusLabel(run.status)}</button>):<Empty/>}<JsonView label="usage30" value={overview.usage_30_days}/></>;
}
