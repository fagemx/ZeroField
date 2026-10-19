import { useEffect, useRef, useState } from 'react';
import { t } from '../i18n/index.js';
import { Icon } from '../Icon.jsx';
import { AGENT_FIELDS, TEMPLATES, pick, pretty } from './model.js';
import { Loading, useConsole, useDraft, useLoad } from './shared.jsx';

// Agent-assisted Quickstart: describe the agent or pick a template; the builder drafts the configuration
// in conversation. Nothing is saved until the showrunner presses Save version; the full editor stays one click away.
export function ConsoleQuickstart() {
  const {resource,agentDrafts}=useConsole();
  const draft=resource && agentDrafts[resource];
  return draft ? <Builder key={resource} draft={draft}/> : <QuickstartHome/>;
}

function QuickstartHome() {
  const state=useLoad('/quickstart');
  const {canEdit,action,request,navigate,setAgentDraft,draftKey}=useConsole();
  const [requirements,setRequirements]=useDraft('requirements','');
  const [preview,setPreview]=useState(null);
  const start=(draft,messages)=>{
    try{sessionStorage.setItem(draftKey+':builder:'+draft.agent_key,JSON.stringify(messages));}catch{/* The builder starts empty. */}
    setAgentDraft(draft);navigate('quickstart',draft.agent_key);
  };
  const describe=event=>{event.preventDefault();if(!requirements.trim())return;action(async()=>{
    const ask=[{role:'user',content:requirements.trim()}];
    const result=await request('/quickstart/converse',{method:'POST',body:{template_key:'blank',messages:ask}});
    setRequirements('');start(result.draft,[...ask,builderReply(result,ask[0].content)]);
  });};
  const blank=()=>action(async()=>{const result=await request('/quickstart/draft',{method:'POST',body:{template_key:'blank'}});start(result.draft,[{role:'assistant',content:t('console.builder.fromBlank')}]);});
  const open=item=>action(async()=>{const result=await request('/quickstart/draft',{method:'POST',body:{template_key:item.template_key}});setPreview({item,draft:result.draft});});
  return <section className="qs-home">
    <h2>{t('console.buildQuestion')}</h2>
    <p>{t('console.builder.subtitle')}</p>
    <form className="qs-prompt" onSubmit={describe}>
      <textarea aria-label={t('console.requirements')} placeholder={t('console.builder.placeholder')} rows={2} maxLength={4000} value={requirements} disabled={!canEdit}
        onChange={e=>setRequirements(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();e.currentTarget.form.requestSubmit();}}}/>
      <button type="submit" className="qs-send" aria-label={t('console.draftAgent')} title={t('console.draftAgent')} disabled={!canEdit || !requirements.trim()}><Icon name="arrowUp"/></button>
    </form>
    <Loading state={state}/>
    <div className="ac-templates">{(state.data?.templates || []).filter(item=>TEMPLATES.includes(item.template_key)).map(item=><button className="ac-template" disabled={!canEdit} key={item.template_key} onClick={()=>open(item)}>
      <h3>{t('console.templates.'+item.template_key+'.title')}</h3><p>{t('console.templates.'+item.template_key+'.description')}</p>
      <span className="ac-badge">{t('console.badges.'+item.badge)}</span>
    </button>)}</div>
    <p className="qs-blank"><button className="qs-link" disabled={!canEdit} onClick={blank}>{t('console.blank')}</button></p>
    {preview && <TemplatePreview preview={preview} onClose={()=>setPreview(null)} onUse={()=>{const title=t('console.templates.'+preview.item.template_key+'.title');setPreview(null);start(preview.draft,[{role:'assistant',content:t('console.builder.fromTemplate',{title})}]);}}/>}
  </section>;
}

function TemplatePreview({preview:{item,draft},onClose,onUse}) {
  const dialog=useRef(null);
  useEffect(()=>{dialog.current?.querySelector('button')?.focus();},[]);
  const title=t('console.templates.'+item.template_key+'.title');
  return <div className="qs-scrim" onClick={event=>{if(event.target===event.currentTarget)onClose();}}>
    <div ref={dialog} className="qs-dialog" role="dialog" aria-modal="true" aria-label={title} onKeyDown={e=>{if(e.key==='Escape')onClose();}}>
      <header><div><h2>{title}</h2><p>{t('console.templates.'+item.template_key+'.description')}</p></div><button className="qs-icon" aria-label={t('console.close')} onClick={onClose}><Icon name="close"/></button></header>
      <dl className="qs-facts"><div><dt>{t('console.builder.mode')}</dt><dd><span className="ac-badge">{t('console.badges.'+item.badge)}</span></dd></div>
        <div><dt>{t('console.builder.skills')}</dt><dd>{item.skill_keys.join(' · ') || '—'}</dd></div>
        <div><dt>{t('console.builder.tools')}</dt><dd>{item.allowed_tools.join(' · ')}</dd></div></dl>
      <section className="qs-config"><h3>{t('console.builder.configuration')}</h3><pre>{pretty(pick(draft,['display_name','system_prompt','skill_keys','allowed_tools','tool_policies','outcome_grader']))}</pre></section>
      <footer><button onClick={onClose}>{t('console.builder.cancel')}</button><button className="qs-primary" onClick={onUse}>{t('console.builder.useTemplate')}</button></footer>
    </div>
  </div>;
}

function builderReply(result,request) {
  if(result.mode!=='model')return {role:'assistant',content:t('console.builder.noModel'),kind:'notice'};
  const changed=result.changed?.length ? '\n'+t('console.builder.changed',{fields:result.changed.map(k=>t('console.builder.field.'+k,{defaultValue:k})).join(', ')}) : '';
  return {role:'assistant',content:(result.reply || t('console.builder.drafted',{request}))+changed};
}

function Builder({draft}) {
  const {action,request,navigate,setAgentDraft,catalog,canEdit,refresh,busy}=useConsole();
  const [messages,setMessages]=useDraft('builder:'+draft.agent_key,[]);
  const [reply,setReply]=useState('');
  const thread=useRef(null);
  const saved=(catalog.agents || []).find(a=>a.agent_key===draft.agent_key);
  useEffect(()=>{thread.current?.scrollTo({top:thread.current.scrollHeight});},[messages.length]);
  const send=event=>{event.preventDefault();const text=reply.trim();if(!text)return;action(async()=>{
    const ask=[...messages.filter(m=>m.kind!=='notice').map(({role,content})=>({role,content})),{role:'user',content:text}].slice(-24);
    setMessages([...messages,{role:'user',content:text}]);setReply('');
    const result=await request('/quickstart/converse',{method:'POST',body:{messages:ask,draft:pick(draft,AGENT_FIELDS)}});
    setAgentDraft({...result.draft,version:saved?.version || 0});setMessages(current=>[...current,builderReply(result,text)]);
  });};
  const save=()=>action(async()=>{
    const result=await request('/agents',{method:'POST',body:pick({...draft,version:saved?.version || 0},AGENT_FIELDS)});
    setAgentDraft(result.agent);setMessages(current=>[...current,{role:'assistant',content:t('console.builder.savedNote',{version:result.agent.version})}]);refresh();
  });
  const EDIT=['display_name','description','system_prompt','skill_keys','allowed_tools','tool_policies','outcome_grader','effort'];
  const stable=value=>JSON.stringify(value,(k,v)=>v && typeof v==='object' && !Array.isArray(v) ? Object.fromEntries(Object.entries(v).sort()) : v);
  const dirty=!saved || stable(pick(draft,EDIT))!==stable(pick(saved,EDIT));
  const steps=[['create',Boolean(saved)],['environment',false],['session',false],['integrate',false]];
  const asks=new Set(Object.entries(draft.tool_policies || {}).filter(([,p])=>p==='always_ask').map(([n])=>n));
  return <div className="qs-builder">
    <section className="qs-thread-wrap">
      <button className="qs-link qs-back" onClick={()=>navigate('quickstart')}><Icon name="arrowLeft"/>{t('console.builder.back')}</button>
      <div className="qs-thread" ref={thread} aria-live="polite">
        {messages.map((m,i)=><div key={i} className={'qs-msg '+m.role+(m.kind ? ' '+m.kind:'')}>{m.content}</div>)}
        <div className="qs-created"><span>{t('console.builder.created')}</span><b>{draft.display_name}</b><span className={'qs-pill'+(saved ? ' ok':'')}>{saved ? t('console.builder.savedVersion',{version:saved.version}) : t('console.builder.unsaved')}</span>
          <button className="qs-link" onClick={()=>navigate('agents',draft.agent_key)}>{t('console.builder.openEditor')}<Icon name="arrowRight"/></button></div>
        {busy && <div className="qs-msg assistant pending">{t('console.builder.drafting')}</div>}
      </div>
      <form className="qs-prompt qs-composer" onSubmit={send}>
        <textarea aria-label={t('console.builder.reply')} placeholder={t('console.builder.replyPlaceholder')} rows={1} maxLength={4000} value={reply} disabled={!canEdit}
          onChange={e=>setReply(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();e.currentTarget.form.requestSubmit();}}}/>
        <button type="submit" className="qs-send" aria-label={t('console.builder.send')} disabled={!canEdit || !reply.trim() || busy}><Icon name="arrowUp"/></button>
      </form>
    </section>
    <aside className="qs-rail">
      <section><h3>{t('console.builder.progress')}</h3><ol className="qs-steps">{steps.map(([key,done],i)=><li key={key} className={done ? 'done' : steps.findIndex(([,d])=>!d)===i ? 'current' : ''}>{t('console.builder.step.'+key)}</li>)}</ol></section>
      <section><h3>{t('console.builder.agent')}</h3><button className="qs-agent" onClick={()=>navigate('agents',draft.agent_key)}><Icon name="bot"/><span>{draft.display_name}</span><small>{saved ? 'v'+saved.version : t('console.builder.unsaved')}</small><Icon name="arrowRight"/></button></section>
      <section><h3>{t('console.builder.abilities')}</h3><ul className="qs-tools">{(draft.allowed_tools || []).map(n=><li key={n}><code>{n}</code>{asks.has(n) && <span>{t('console.builder.asksFirst')}</span>}</li>)}</ul>
        <p className="qs-meta">{t('console.builder.skills')}: {(draft.skill_keys || []).join(' · ') || '—'}<br/>{t('console.builder.grader')}: {t(draft.outcome_grader?.enabled ? 'console.builder.on' : 'console.builder.off')}</p></section>
      {!saved || dirty ? <button className="qs-primary" disabled={!canEdit || busy} onClick={save}>{t('console.save')}</button>
        : <button className="qs-primary" onClick={()=>navigate('environments')}>{t('console.builder.next.environment')}<Icon name="arrowRight"/></button>}
      {saved && <div className="qs-next"><button onClick={()=>navigate('playground',draft.agent_key)}>{t('console.builder.next.session')}</button><button onClick={()=>navigate('deployments','new')}>{t('console.builder.next.integrate')}</button></div>}
    </aside>
  </div>;
}
