import { useEffect, useState } from 'react';
import { t } from '../i18n/index.js';
import { Icon } from '../Icon.jsx';
import { useConsole } from './shared.jsx';
import { AUDIT_STEPS, EXPIRY_DAYS, KNOWN_TOOLS, STATUS_TONE, WRITE_MODES, auditLine, connectionSnippets, createBody, daysLabel, effectiveStatus,
  expiryLine, expiryPreview, externalError, formValid, heldIssued, holdIssued, lastUsedLine, newForm, presetTools, releaseIssued,
  serverUrl, setKey, setMode, setName, toggleTool, toolGroups, toolLabels, usageLine, validateForm } from './externalAgentsModel.js';

// SPEC_20 R41 inside the existing Environments & Bridges page: no page or group is added. Showrunners issue
// service-account tokens for zerofield-mcp, see what each agent may do and has done, and revoke a token.

function Pill({tone='muted',children}) {return <span className={'ac-pill '+tone}>{children}</span>;}

/** Accounts and the tool list now, on refresh and after every change; requests abort on unmount. */
function useAccounts(base) {
  const {externalRequest,revision}=useConsole();
  const [state,setState]=useState({});const [tick,setTick]=useState(0);
  useEffect(()=>{
    const controller=new AbortController();
    externalRequest(base,{signal:controller.signal}).then(data=>{if(!controller.signal.aborted)setState({data});}).catch(error=>{if(!controller.signal.aborted && error.name!=='AbortError')setState(current=>({...current,error}));});
    return()=>controller.abort();
  },[base,externalRequest,revision,tick]);
  return [state,()=>setTick(n=>n+1)];
}

export function ExternalAgents() {
  const {canEdit}=useConsole();
  if(!canEdit)return <section className="ac-card ac-external"><h2>{t('console.external.title')}</h2><p>{t('console.external.adminOnly')}</p></section>;
  return <ExternalAgentsAdmin/>;
}

function ExternalAgentsAdmin() {
  const {slug,action,externalRequest}=useConsole();
  const base='/projects/api/'+encodeURIComponent(slug)+'/service-accounts';
  const [state,reload]=useAccounts(base);
  const [creating,setCreating]=useState(false);
  const [issued,setIssued]=useState(()=>heldIssued(slug));
  const [message,setMessage]=useState('');
  const accounts=state.data?.items || [];const available=state.data?.availableTools || [];
  const connect={project:slug,...serverUrl(),http:state.data?.connect?.http || null};
  const done=()=>{releaseIssued(slug);setIssued(null);};
  const create=body=>action(async()=>{
    setMessage('');
    try{
      const result=await externalRequest(base,{method:'POST',body});
      holdIssued(slug,result);setIssued(result);setCreating(false);reload();
    }catch(error){if(error.name==='AbortError')throw error;setMessage(externalError(error));}
  });
  const revoke=account=>action(async()=>{
    setMessage('');
    try{await externalRequest(base+'/'+encodeURIComponent(account.accountKey)+'/revoke',{method:'POST',body:{}});reload();}
    catch(error){if(error.name==='AbortError')throw error;setMessage(externalError(error));}
  });
  return <section className="ac-card ac-external" aria-labelledby="ac-external-title">
    <header><h2 id="ac-external-title">{t('console.external.title')}</h2>
      {!creating && <button className="qs-primary" disabled={!state.data} onClick={()=>{setCreating(true);setMessage('');}}><Icon name="plus"/>{t('console.external.new')}</button>}</header>
    <p>{t('console.external.intro')}</p>
    {state.error && !state.data && <p className="ac-error" role="alert">{t('console.loadFailed')}</p>}
    {message && <p className="ac-error" role="alert">{message}</p>}
    {issued && <IssuedToken issued={issued} connect={connect} onDone={done}/>}
    {creating && <TokenForm accounts={accounts} available={available} onCancel={()=>setCreating(false)} onCreate={create}/>}
    {!state.data && !state.error && <p role="status">{t('console.loading')}</p>}
    {state.data && <>
      <h3>{t('console.external.accounts.title')}</h3>
      {accounts.length===0 ? <p className="ac-quiet">{t('console.external.accounts.empty')}</p>
        : <ul className="ac-accounts">{accounts.map(account=><AccountRow key={account.accountKey} base={base} account={account} available={available} onRevoke={revoke}/>)}</ul>}
      {!issued && <details className="ac-howto"><summary>{t('console.external.setup.title')}</summary><Setup connect={connect} token=""/></details>}
    </>}
  </section>;
}

// ---------- creating a token ----------

function TokenForm({accounts,available,onCancel,onCreate}) {
  const [form,setForm]=useState(()=>newForm(available));
  const errors=validateForm(form,accounts,available);
  const groups=toolGroups(available);
  const generation=form.mode==='generate';
  const submit=event=>{event.preventDefault();if(formValid(errors))onCreate(createBody(form,available));};
  return <form className="ac-token-form" onSubmit={submit} aria-labelledby="ac-token-form-title">
    <h3 id="ac-token-form-title">{t('console.external.form.title')}</h3>
    <div className="ac-form-grid">
      <label className="ac-field"><span>{t('console.external.form.name')}</span><input value={form.name} maxLength={120} placeholder={t('console.external.form.namePlaceholder')} autoFocus onChange={e=>setForm(setName(form,e.target.value))}/>
        {errors.name==='nameLong' && <small className="ac-warn-text">{t('console.external.error.nameLong')}</small>}</label>
      <label className="ac-field"><span>{t('console.external.form.key')}</span><input value={form.key} maxLength={48} spellCheck={false} onChange={e=>setForm(setKey(form,e.target.value))}/>
        <small className={errors.key && form.key ? 'ac-warn-text':''}>{errors.key && form.key ? t('console.external.error.'+errors.key) : t('console.external.form.keyHelp')}</small></label>
    </div>
    <fieldset className="ac-modes"><legend>{t('console.external.form.mode')}</legend>
      <div className="ac-mode-grid">{WRITE_MODES.map(mode=><label key={mode} className={'ac-mode'+(form.mode===mode ? ' on':'')}>
        <input type="radio" name="ac-write-mode" checked={form.mode===mode} onChange={()=>setForm(setMode(form,mode,available))}/>
        <span><strong>{t('console.external.mode.'+mode+'.title')}</strong><small>{t('console.external.mode.'+mode+'.body')}</small></span></label>)}</div>
      <p className="ac-nomoney"><Icon name="shield"/><span>{t('console.external.mode.noMoney')}</span></p>
    </fieldset>
    <fieldset className="ac-tool-pick"><legend>{t('console.external.form.tools')}</legend>
      <div className="ac-presets"><span>{t('console.external.preset.label')}</span>{['read','propose','all'].map(preset=><button type="button" key={preset} onClick={()=>setForm({...form,tools:presetTools(available,preset,form.mode)})}>{t('console.external.preset.'+preset)}</button>)}</div>
      {groups.map(group=><div className="ac-tool-group" key={group.kind}><h4>{t('console.external.kind.'+group.kind)}</h4>
        {group.tools.map(tool=>{const locked=tool.generation && !generation;return <label key={tool.name} className={'ac-tool-option'+(locked ? ' locked':'')}>
          <input type="checkbox" checked={form.tools.includes(tool.name)} disabled={locked} onChange={()=>setForm(toggleTool(form,tool.name))}/>
          <span><strong>{tool.label}</strong> <code>{tool.name}</code><small>{locked ? t('console.external.needsGenerate') : toolHelp(tool)}</small></span></label>;})}</div>)}
      {errors.tools && <p className="ac-warn-text" role="alert">{t('console.external.error.'+errors.tools)}</p>}
    </fieldset>
    <div className="ac-form-grid">
      <label className="ac-field"><span>{t('console.external.form.expires')}</span><select value={form.days} onChange={e=>setForm({...form,days:Number(e.target.value)})}>{EXPIRY_DAYS.map(days=><option key={days} value={days}>{daysLabel(days)}</option>)}</select>
        <small>{errors.days ? t('console.external.error.daysInvalid') : t('console.external.form.expiresOn',{date:expiryPreview(form.days)})}</small></label>
    </div>
    <div className="ac-actions"><button type="submit" disabled={!formValid(errors)}>{t('console.external.form.create')}</button><button type="button" onClick={onCancel}>{t('console.external.cancel')}</button></div>
  </form>;
}
const toolHelp=tool=>KNOWN_TOOLS.includes(tool.name) ? t('console.external.tool.'+tool.name) : t('console.external.kindHelp.'+(tool.generation ? 'generate' : tool.writes ? 'propose' : tool.category==='workflow' ? 'guide' : 'read'));

// ---------- the token, once, and how to connect ----------

function CopyButton({text,label}) {
  const [copied,setCopied]=useState(false);
  return <button type="button" className="ac-copy" aria-label={label} title={label} onClick={()=>{navigator.clipboard?.writeText(text).then(()=>{setCopied(true);setTimeout(()=>setCopied(false),1500);}).catch(()=>{});}}><Icon name={copied ? 'check':'doc'}/><span>{t(copied ? 'console.external.copied':'console.external.copy')}</span></button>;
}

function IssuedToken({issued,connect,onDone}) {
  return <section className="ac-issued" aria-labelledby="ac-issued-title">
    <h3 id="ac-issued-title"><Icon name="key"/>{t('console.external.issued.title',{name:issued.account.displayName})}</h3>
    <p className="ac-strong">{t('console.external.issued.once')}</p>
    <div className="ac-token"><code aria-label={t('console.external.issued.token')}>{issued.token}</code><CopyButton text={issued.token} label={t('console.external.issued.copyToken')}/></div>
    <Setup connect={connect} token={issued.token}/>
    <div className="ac-actions"><button type="button" onClick={onDone}>{t('console.external.issued.done')}</button></div>
  </section>;
}

function Setup({connect,token}) {
  const [format,setFormat]=useState('claude');
  const snippets=connectionSnippets({...(token ? {token}:{}),project:connect.project,url:connect.url,http:connect.http});
  const text=snippets[format];
  return <div className="ac-setup-block">
    <p>{t('console.external.setup.intro',{command:'zerofield-mcp'})}</p>
    <div className="ac-segment" role="group" aria-label={t('console.external.setup.format')}>{['claude','json'].map(key=><button type="button" key={key} aria-pressed={format===key} onClick={()=>setFormat(key)}>{t('console.external.setup.'+key)}</button>)}</div>
    <div className="ac-snippet"><pre tabIndex={0} aria-label={t('console.external.setup.'+format)}>{text}</pre><CopyButton text={text} label={t('console.external.setup.copy')}/></div>
    <dl className="ac-env">{snippets.env.map(([key,value])=><div key={key}><dt><code>{key}</code></dt><dd>{t('console.external.setup.env.'+key)}</dd></div>)}</dl>
    {!token && <p><small>{t('console.external.setup.placeholder')}</small></p>}
    {!connect.local && <p><small>{t('console.external.setup.notLocal',{host:connect.host})}</small></p>}
    {snippets.http && <div className="ac-http"><h4>{t('console.external.setup.http.title')}</h4><p>{t('console.external.setup.http.body')}</p>
      <div className="ac-snippet"><pre tabIndex={0}>{snippets.http.url+'\n'+snippets.http.header}</pre><CopyButton text={snippets.http.url+'\n'+snippets.http.header} label={t('console.external.setup.copy')}/></div></div>}
  </div>;
}

// ---------- the accounts ----------

function AccountRow({base,account,available,onRevoke}) {
  const [open,setOpen]=useState(false),[confirming,setConfirming]=useState(false);
  const status=effectiveStatus(account);
  const labels=toolLabels(account,available);
  return <li className={'ac-account '+status}>
    <div className="ac-account-head"><span className="ac-account-name"><strong>{account.displayName}</strong><code>{account.accountKey}</code></span>
      <Pill tone={STATUS_TONE[status]}>{t('console.external.status.'+status)}</Pill>
      <Pill>{t('console.external.mode.'+account.writeMode+'.title')}</Pill></div>
    <p className="ac-account-meta">{expiryLine(account)} · {lastUsedLine(account)}</p>
    <p className="ac-account-meta">{usageLine(account)}</p>
    <ul className="ac-chips" aria-label={t('console.external.form.tools')}>{labels.map(tool=><li key={tool.name} title={tool.name}>{tool.label}</li>)}</ul>
    <div className="ac-account-actions">
      <button type="button" aria-expanded={open} onClick={()=>setOpen(!open)}>{t(open ? 'console.external.audit.hide':'console.external.audit.show')}</button>
      {status==='active' && !confirming && <button type="button" className="ac-danger" onClick={()=>setConfirming(true)}>{t('console.external.revoke.ask')}</button>}
    </div>
    {confirming && <div className="ac-confirm" role="alertdialog" aria-label={t('console.external.revoke.title',{name:account.displayName})}>
      <p className="ac-strong">{t('console.external.revoke.body',{name:account.displayName})}</p>
      <div className="ac-actions"><button type="button" className="ac-danger" onClick={()=>{setConfirming(false);onRevoke(account);}}>{t('console.external.revoke.yes')}</button><button type="button" autoFocus onClick={()=>setConfirming(false)}>{t('console.external.revoke.no')}</button></div></div>}
    {open && <AuditLog base={base} account={account} available={available}/>}
  </li>;
}

function AuditLog({base,account,available}) {
  const {externalRequest,revision}=useConsole();
  const [limit,setLimit]=useState(AUDIT_STEPS[0]),[state,setState]=useState({loading:true}),[tick,setTick]=useState(0);
  useEffect(()=>{
    const controller=new AbortController();
    externalRequest(base+'/'+encodeURIComponent(account.accountKey)+'/audit?limit='+limit,{signal:controller.signal})
      .then(data=>{if(!controller.signal.aborted)setState({data});}).catch(error=>{if(!controller.signal.aborted && error.name!=='AbortError')setState({error});});
    return()=>controller.abort();
  },[base,account.accountKey,limit,externalRequest,revision,tick]);
  const items=state.data?.items || [];
  const next=AUDIT_STEPS.find(step=>step>limit);
  return <section className="ac-audit" aria-label={t('console.external.audit.title')}>
    <header><h4>{t('console.external.audit.title')}</h4><button type="button" className="ac-icon-button" aria-label={t('console.refresh')} title={t('console.refresh')} onClick={()=>setTick(n=>n+1)}><Icon name="refresh"/></button></header>
    {state.loading && <p role="status">{t('console.loading')}</p>}
    {state.error && <p className="ac-error" role="alert">{t('console.loadFailed')}</p>}
    {state.data && (items.length===0 ? <p className="ac-quiet">{t('console.external.audit.empty')}</p> : <ol className="ac-audit-rows">{items.map(entry=>{const line=auditLine(entry,account,available);return <li key={entry.id} className={'ac-audit-row '+line.kind}>
      <span className="ac-audit-when">{line.at}</span>
      <span className="ac-audit-what"><strong>{line.what}</strong>{line.tool && line.tool!==line.what && <code>{line.tool}</code>}</span>
      <span className="ac-audit-who">{line.who}{line.actingFor && <small>{line.actingFor}</small>}</span>
      <span className="ac-audit-result">{line.result && <Pill tone={line.result.tone}>{line.result.label}</Pill>}{line.detail && <small>{line.detail}</small>}</span></li>;})}</ol>)}
    <footer>{state.data && items.length>=limit && next && <button type="button" onClick={()=>setLimit(next)}>{t('console.external.audit.more')}</button>}<small>{t('console.external.audit.privacy')}</small></footer>
  </section>;
}
