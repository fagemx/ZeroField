import { useState } from 'react';
import { t } from '../i18n/index.js';
import { Icon } from '../Icon.jsx';
import { readinessLines } from '../assistant/AgentBoard.jsx';
import { consoleError } from './model.js';
import { useConsole } from './shared.jsx';
import { Pill, useOps } from './ConsoleOpsViews.jsx';
import { INHERIT, TIER_TONE, abilities, applyProblem, changeBody, choiceNotes, endpointNote, groupChoices, hostedBody, isCurrent, readyView,
  whereLine } from './matrixModel.js';

// SPEC_20 R37 on Providers & API Keys: which model each crew role and custom agent uses, what it can do, whether the
// crew can use it, and the showrunner's switch for hosted open-weights models. The server probes local endpoints only.

export function ModelMatrix() {
  const {canEdit}=useConsole();
  if(!canEdit)return <section className="ac-card ac-matrix"><h2>{t('console.matrix.title')}</h2><p>{t('console.matrix.adminOnly')}</p></section>;
  return <ModelMatrixAdmin/>;
}

function ModelMatrixAdmin() {
  const [forced,setForced]=useState(false),[open,setOpen]=useState(null);
  const [state,reload]=useOps('/model-matrix'+(forced ? '?refresh=1':''),0);const data=state.data;
  const check=()=>{setForced(true);reload();};
  return <section className="ac-card ac-matrix" aria-labelledby="ac-matrix-title">
    <header><h2 id="ac-matrix-title">{t('console.matrix.title')}</h2>
      {data && <Pill>{t('console.matrix.policy.'+data.policy.production,{defaultValue:data.policy.production})}</Pill>}
      <button className="ac-icon-button" aria-label={t('console.matrix.refresh')} title={t('console.matrix.refresh')} onClick={check}><Icon name="refresh"/></button></header>
    <p>{t('console.matrix.intro')}</p>
    {!data ? <p role="status">{state.error ? t('console.matrix.loadFailed'):t('console.loading')}</p> : <MatrixBody data={data} open={open} onToggle={key=>setOpen(open===key ? null:key)}/>}
  </section>;
}

/** The switch and the table, from one /model-matrix answer; `open` is the agent key whose change panel is showing. */
export function MatrixBody({data,open,onToggle}) {
  return <>
    <HostedSwitch policy={data.policy}/>
    <div className="ac-table-wrap"><table className="ac-matrix-table">
      <colgroup>{['role','model','tier','can','ready','change'].map(col=><col key={col} className={'ac-col-'+col}/>)}</colgroup>
      <thead><tr>{['role','model','tier','can','ready','change'].map(col=><th key={col} scope="col">{t('console.matrix.col.'+col)}</th>)}</tr></thead>
      <tbody>{data.rows.map(row=><MatrixRow key={row.agentKey} row={row} data={data} open={open===row.agentKey} onToggle={()=>onToggle(row.agentKey)}/>)}</tbody>
    </table></div>
    {data.policy.closedHidden>0 && <p><small>{t('console.matrix.closedHidden',{n:data.policy.closedHidden})}</small></p>}
  </>;
}

// The showrunner's switch for provider_policy.hosted_open_enabled, with the plain reason it is off by default.
function HostedSwitch({policy}) {
  const {request,action,refresh}=useConsole();const [problem,setProblem]=useState('');
  const enabled=policy.hostedOpenEnabled===true;
  const set=value=>action(async()=>{
    setProblem('');
    try{await request('/provider-policy',{method:'POST',body:hostedBody(policy,value)});refresh();}
    catch(error){setProblem(t(error?.status===409 ? 'console.matrix.stale':'console.matrix.hosted.failed'));}
  });
  return <div className={'ac-hosted'+(enabled ? ' on':'')}>
    <div><h3>{t('console.matrix.hosted.title')}</h3><p>{t('console.matrix.hosted.body')}</p><p>{t('console.matrix.hosted.stillNeeds')}</p></div>
    <div className="ac-switch-row">
      <button type="button" role="switch" aria-checked={enabled} aria-label={t('console.matrix.hosted.label')} className="ac-switch" onClick={()=>set(!enabled)}><span className="ac-switch-knob"/></button>
      <div><strong>{t('console.matrix.hosted.label')}</strong><p>{t(policy.hybrid ? 'console.matrix.hosted.hybrid':enabled ? 'console.matrix.hosted.on':'console.matrix.hosted.off')}</p></div>
    </div>
    {problem && <p className="ac-error" role="alert">{problem}</p>}
  </div>;
}

function Abilities({model}) {
  const {chips,context,assumed}=abilities(model);
  return <><ul className="ac-chips">{chips.map(chip=><li key={chip.key} className={chip.on ? 'on':'off'} aria-label={t(chip.on ? 'console.matrix.cap.yes':'console.matrix.cap.no',{name:chip.name})}>{chip.name}</li>)}
    <li className="on">{t('console.matrix.cap.context',{size:context})}</li></ul>
    {assumed && <small className="ac-warn-text" title={t('console.matrix.assumedHint')}>{t('console.matrix.assumed')}</small>}</>;
}

function MatrixRow({row,data,open,onToggle}) {
  const current=row.current,ready=readyView(row);
  const lines=readinessLines({ready:false,blockers:row.readiness?.blockers || []},[]);
  const notes=current ? choiceNotes({...current,denials:row.denials}):[];
  return <>
    <tr className={row.enabled ? '':'ac-off'}>
      <th scope="row"><strong>{row.displayName}</strong><small>{row.agentKey}</small>
        {row.custom && <Pill>{t('console.matrix.custom')}</Pill>}{!row.enabled && <Pill>{t('console.matrix.off')}</Pill>}</th>
      <td>{current ? <><code className="ac-model">{current.model}</code>{current.label && <small>{current.label}</small>}<small>{whereLine(current)}</small>
        {row.inherits && <small>{t('console.matrix.usesDefault')}</small>}</>
        : <small className="ac-warn-text">{ready.setup || t('console.matrix.noModel')}</small>}</td>
      <td>{current && <><Pill tone={TIER_TONE[current.tier] || 'muted'}>{t('console.matrix.tier.'+current.tier,{defaultValue:current.tier})}</Pill>
        {notes.map(note=><small key={note.text} className="ac-warn-text">{note.text}</small>)}</>}</td>
      <td>{current && <Abilities model={current}/>}</td>
      <td><Pill tone={ready.tone}>{ready.label}</Pill>
        {ready.state==='untested' && <small>{t('console.matrix.ready.untestedHint')}</small>}
        {lines.slice(0,1).map(line=><p key={line.id} className="ac-reason">{line.text}{line.command && <> <code>{line.command}</code></>}</p>)}
        {lines.length>1 && <small>{t('console.matrix.moreProblems',{n:lines.length-1})}</small>}</td>
      <td><button type="button" aria-expanded={open} onClick={onToggle}>{t(open ? 'console.matrix.close':'console.matrix.change')}</button></td>
    </tr>
    {open && <tr className="ac-matrix-panel"><td colSpan={6}><ChangePanel key={row.agentKey+':'+row.version} row={row} data={data} onDone={onToggle}/></td></tr>}
  </>;
}

// Pick one model; denied ones say why and cannot be picked. The save goes through the ordinary agent save on the server.
function ChangePanel({row,data,onDone}) {
  const {request,action,refresh}=useConsole();
  const [pick,setPick]=useState(null),[problem,setProblem]=useState('');
  const groups=groupChoices(data.choices,data.endpoints);
  const chosen=pick===INHERIT ? INHERIT:data.choices.find(choice=>choice.key===pick) || null;
  const unchanged=pick===null || chosen===null || (chosen===INHERIT ? row.inherits : isCurrent(row,chosen));
  const apply=()=>action(async()=>{
    setProblem('');
    try{await request('/model-matrix',{method:'POST',body:changeBody(row,chosen)});onDone();refresh();}
    catch(error){setProblem(applyProblem(error,chosen===INHERIT ? null:chosen) || consoleError(error));}
  });
  const name='model-'+row.agentKey;
  return <div className="ac-change">
    <h3>{t('console.matrix.choose',{role:row.displayName})}</h3>
    <fieldset className="ac-choices" aria-label={t('console.matrix.choose',{role:row.displayName})}>
      <label className={'ac-choice'+(row.inherits ? ' current':'')}><input type="radio" name={name} checked={pick===INHERIT} disabled={row.inherits} onChange={()=>setPick(INHERIT)}/>
        <span className="ac-choice-body"><span className="ac-choice-main"><strong>{t('console.matrix.useDefault')}</strong>{row.inherits && <Pill>{t('console.matrix.current')}</Pill>}</span><small>{t('console.matrix.useDefaultBody')}</small></span></label>
      {groups.map(group=><div key={group.id} className="ac-choice-group">
        <h4>{group.kind==='listing' ? t('console.matrix.group.listing',{host:group.endpoint.host,port:group.endpoint.port}):t('console.matrix.group.catalog')}</h4>
        {group.endpoint && endpointNote(group.endpoint) && <p className="ac-warn-text">{endpointNote(group.endpoint)}</p>}
        {group.kind==='listing' && group.endpoint.state==='ok' && group.items.length===0 && <p className="ac-quiet">{t('console.matrix.noListing')}</p>}
        {group.items.map(choice=><ChoiceRow key={choice.key} row={row} choice={choice} name={name} checked={pick===choice.key} onPick={()=>setPick(choice.key)}/>)}
      </div>)}
    </fieldset>
    {problem && <p className="ac-error" role="alert">{problem}</p>}
    <div className="ac-actions"><button type="button" className="qs-primary" disabled={unchanged} onClick={apply}>{t('console.matrix.apply')}</button><button type="button" onClick={onDone}>{t('console.matrix.close')}</button></div>
  </div>;
}

function ChoiceRow({row,choice,name,checked,onPick}) {
  const current=isCurrent(row,choice),notes=choiceNotes(choice);
  return <label className={'ac-choice'+(current ? ' current':'')+(choice.allowed ? '':' denied')}>
    <input type="radio" name={name} checked={checked} disabled={!choice.allowed || current} onChange={onPick}/>
    <span className="ac-choice-body">
      <span className="ac-choice-main"><code>{choice.model}</code><Pill tone={TIER_TONE[choice.tier] || 'muted'}>{t('console.matrix.tier.'+choice.tier,{defaultValue:choice.tier})}</Pill>{current && <Pill>{t('console.matrix.current')}</Pill>}</span>
      {choice.label && <small>{choice.label}{choice.local ? '':' · '+whereLine(choice)}</small>}
      <Abilities model={choice}/>
      {notes.map(note=><small key={note.text} className="ac-warn-text">{note.text}</small>)}
    </span>
  </label>;
}
