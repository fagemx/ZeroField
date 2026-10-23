import React, {useEffect, useMemo, useState} from 'react';
import {useTranslation} from '../i18n/react.jsx';
import {actionId, downloadBlob, frozenRequest} from './writingToolsModel.js';
import {ToolsNotice, useToolsAction} from './writingToolsState.js';

import {BibleFormRecovery} from './writingToolsRecovery.js';

const TEXT_FIELDS = ['role', 'background', 'constraints', 'relationships', 'rules', 'research', 'notes'];
const blank = () => ({entryKind: 'note', title: '', assetId: '', aliases: [], events: [], ...Object.fromEntries(TEXT_FIELDS.map(key => [key, '']))});
function editable(entry) {
  return {...blank(), ...Object.fromEntries(['entryKind','title','assetId','aliases','events',...TEXT_FIELDS].filter(key => entry[key] !== undefined).map(key => [key, structuredClone(entry[key])]))};
}

function recoveryBase(entry) {return entry ? {bibleId:entry.bibleId,version:entry.version,...editable(entry)} : null;}

export function WritingBible({slug, me, epId, registerToolControl, writable, selectedSubjectId, workspace, transport, onNavigateSource, onNavigateShots, onError, onChanged}) {
  const {t} = useTranslation();
  const task = useToolsAction(onError);
  const [catalog, setCatalog] = useState({items: [], nextCursor: null});
  const [entry, setEntry] = useState(null);
  const [draft, setDraft] = useState(blank);
  const manager = useMemo(() => {
    const instance=new BibleFormRecovery({slug,actorId:me?.actor_id || me?.actorId || me?.id,epId});
    instance.open(null,blank());return instance;
  },[slug,me?.actor_id,me?.actorId,me?.id,epId]);
  const control=useMemo(()=>({flush:options=>manager.flush(options),isDirty:()=>manager.isDirty(),recoveryState:()=>manager.recoveryState()}),[manager]);
  const [recovery,setRecovery] = useState(() => manager.snapshot());
  const dirty=recovery.dirty;
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    manager.notify=setRecovery;setRecovery(manager.snapshot());
    manager.discover().catch(error=>manager.discoveryError(error));
    return () => {if(manager.dirty)manager.checkpoint();manager.dispose();};
  },[manager]);
  useEffect(() => registerToolControl?.('bible:form',control),[registerToolControl,control,recovery.state,recovery.dirty,recovery.recoverable,recovery.identityRequested,recovery.localError]);
  useEffect(() => {if(task.error)manager.markError(task.error);},[task.error,manager]);
  useEffect(() => {
    const warn=event=>{if(manager.isDirty()&&(!manager.recoveryState().recoverable||['recovery','conflict','auth_lost'].includes(manager.state))){event.preventDefault();event.returnValue='';}};
    window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);
  },[manager]);
  const [matrix, setMatrix] = useState(null);
  const [filter, setFilter] = useState('');
  const scenes = workspace?.structure?.scenes || [];
  const change = (key, value) => {const next={...manager.draft,[key]:value};manager.change(next);setDraft(next);setSaved(false);task.clear();};
  async function load(cursor, selected = selectedSubjectId, signal) {
    const query = new URLSearchParams({limit: '20', ...(cursor ? {cursor} : {}), ...(filter ? {filter} : {})});
    const result = await transport(`bible?${query}`, 'GET', undefined, {signal});
    signal?.throwIfAborted();
    setCatalog(previous => ({...result, items: cursor ? [...previous.items, ...result.items] : result.items}));
    if (!cursor && selected) {
      const match = result.items.find(item => item.assetId === selected || item.bibleId === selected);
      if (match) await choose(match.bibleId,signal);
    }
    try {await manager.discover();}catch(error){manager.discoveryError(error);}
  }
  async function choose(id,signal) {
    const result = await transport(`bible/${encodeURIComponent(id)}`, 'GET', undefined, {signal});
    signal?.throwIfAborted();
    if(manager.open(recoveryBase(result),editable(result))){setEntry(result);setDraft(editable(result));setSaved(false);}
  }
  useEffect(() => {if (!dirty) task.run(signal => load(undefined,selectedSubjectId,signal));}, [filter, selectedSubjectId]); // The parent keys the component by actor/project/episode.
  function appearances() {
    const subject = entry?.assetId || selectedSubjectId;
    const query = new URLSearchParams({episodeId: epId, ...(subject ? {subjectIds: subject} : {})});
    task.run(frozenRequest(transport, `appearances?${query}`), setMatrix);
  }
  function save() {
    const patch = {aliases: draft.aliases.filter(Boolean), ...Object.fromEntries(TEXT_FIELDS.map(key => [key, draft[key]])),
      events: draft.events.map(({orphaned, ...event}) => Object.fromEntries(Object.entries(event).filter(([key,value]) => !['endSceneKey','stateKey','stateValue'].includes(key) || value !== '')))};
    if (draft.entryKind !== 'asset_extension') patch.title = draft.title;
    if(manager.conflict||manager.state==='auth_lost'||manager.recoveries.length)return;
    const sequence=manager.sequence;
    const body = entry ? {baseVersion: manager.base.version, clientMutationId: actionId(), patch} :
      {...patch, entryKind: draft.entryKind, ...(draft.entryKind === 'asset_extension' ? {assetId: draft.assetId} : {})};
    const request = frozenRequest(transport, entry ? `bible/${encodeURIComponent(entry.bibleId)}` : 'bible', entry ? 'PATCH' : 'POST', body);
    task.run(async signal=>{await manager.checkpoint();return request(signal);}, async (result,signal) => {
      const full = await transport(`bible/${encodeURIComponent(result.bibleId || entry.bibleId)}`, 'GET', undefined, {signal});
      signal.throwIfAborted();
      await manager.acknowledge(recoveryBase(full),editable(full),sequence);
      signal.throwIfAborted();setEntry(full);setDraft(editable(full));setSaved(true);
      await load(undefined, null,signal); if (!signal.aborted) await onChanged?.(result);
    });
  }
  function downloadDraft(value) {
    downloadBlob(new Blob([JSON.stringify({kind:'private_bible_draft',fields:value},null,2)],{type:'application/json'}),'private-world-draft.json');
  }
  function restoreDraft(row) {
    task.run(async signal=>{
      const remote=row.base?.bibleId ? await transport(`bible/${encodeURIComponent(row.base.bibleId)}`,'GET',undefined,{signal}) : null;
      signal.throwIfAborted();await manager.restore(row,recoveryBase(remote));return remote;
    },remote=>{setEntry(remote);setDraft(structuredClone(manager.draft));setSaved(false);});
  }
  function reviewCurrent() {
    const id=manager.base?.bibleId;
    if(!id)return;
    task.run(frozenRequest(transport,`bible/${encodeURIComponent(id)}`),remote=>{manager.review(recoveryBase(remote));setEntry(remote);});
  }
  function discardDraft() {
    task.run(async()=>{
      const remote=manager.remote || recoveryBase(entry),next=remote ? editable(remote) : blank();
      if(!await manager.discard(remote,next))return null;
      return {remote:entry?.bibleId===remote?.bibleId&&entry?.version===remote?.version ? entry : remote,next};
    },result=>{if(result){setEntry(result.remote);setDraft(result.next);setSaved(false);}});
  }
  function eventChange(index, key, value) {
    change('events', draft.events.map((event, at) => at === index ? {...event, [key]: value} : event));
  }
  return <div>
    <p className="writing-help">{t('writing.tools.biblePrivacy')}</p>
    <ToolsNotice task={task} t={t}/>
    <label>{t('writing.tools.entryKind')}<select value={filter} disabled={dirty || task.busy} onChange={event => setFilter(event.target.value)}>
      <option value="">{t('writing.tools.bible')}</option>{['asset_extension','world','note'].map(kind => <option key={kind} value={kind}>{t(`writing.tools.${kind}`)}</option>)}
    </select></label>
    <div className="writing-actions">
      <button type="button" disabled={dirty || task.busy} onClick={() => task.run(signal => load(undefined,selectedSubjectId,signal))}>{t('writing.tools.refresh')}</button>
      <button type="button" disabled={!writable || dirty || task.busy} onClick={() => {const next={...blank(),...(selectedSubjectId ? {entryKind:'asset_extension',assetId:selectedSubjectId} : {})};manager.open(null,next);setEntry(null);setDraft(next);setSaved(false);}}>{t('writing.tools.newEntry')}</button>
    </div>
    <label>{t('writing.tools.subject')}<select value={entry?.bibleId || ''} disabled={dirty || task.busy} onChange={event => event.target.value && task.run(signal => choose(event.target.value,signal))}>
      <option value="">{t('writing.tools.newEntry')}</option>{catalog.items.map(item => <option value={item.bibleId} key={item.bibleId}>{item.asset?.name || item.title || item.assetId || item.bibleId}</option>)}
    </select></label>
    {catalog.nextCursor && <button type="button" disabled={task.busy || dirty} onClick={() => task.run(signal => load(catalog.nextCursor,selectedSubjectId,signal))}>{t('writing.tools.more')}</button>}
    <p className="writing-resource">{t(entry?'writing.tools.sharedRecord':'writing.tools.newPrivateForm')}</p>
    {entry?.asset && <div className="writing-change"><strong>{entry.asset.name}</strong> <code>@{entry.asset.assetCode}</code>
      {entry.asset.selectedImageUrl && <img src={entry.asset.selectedImageUrl} alt={entry.asset.name} width="80" loading="lazy"/>}
    </div>}
    <p className="writing-help">{t('writing.tools.assetIdentity')}</p>
    <fieldset disabled={!writable || task.busy}>
      {!entry && <label>{t('writing.tools.entryKind')}<select value={draft.entryKind} onChange={event => change('entryKind', event.target.value)}>{['asset_extension','world','note'].map(kind => <option key={kind} value={kind}>{t(`writing.tools.${kind}`)}</option>)}</select></label>}
      {draft.entryKind === 'asset_extension' ? !entry && <label>{t('writing.tools.assetId')}<input value={draft.assetId} onChange={event => change('assetId',event.target.value)}/></label> :
        <label>{t('writing.tools.titleField')}<input value={draft.title} onChange={event => change('title',event.target.value)}/></label>}
      <label>{t('writing.tools.aliases')}<textarea value={draft.aliases.join('\n')} onChange={event => change('aliases',event.target.value.split('\n'))}/></label>
      {TEXT_FIELDS.map(key => <label key={key}>{t(`writing.tools.${key}`)}<textarea value={draft[key]} onChange={event => change(key,event.target.value)}/></label>)}
      <h4>{t('writing.tools.events')}</h4>
      {draft.events.map((event, index) => <fieldset key={event.eventId} disabled={Boolean(event.orphaned)}>
        <legend>{t('writing.tools.eventId',{id:event.eventId})}</legend>
        {event.orphaned && <p>{t('writing.tools.orphaned')}</p>}
        <label>{t('writing.tools.eventEpisode')}<input value={event.episodeId} onChange={e => eventChange(index,'episodeId',e.target.value)}/></label>
        <label>{t('writing.tools.eventScene')}<input list="writing-event-scenes" value={event.sceneKey} onChange={e => eventChange(index,'sceneKey',e.target.value)}/></label>
        <label>{t('writing.tools.eventEndScene')}<input value={event.endSceneKey || ''} onChange={e => eventChange(index,'endSceneKey',e.target.value)}/></label>
        <label>{t('writing.tools.stateKey')}<input value={event.stateKey || ''} onChange={e => eventChange(index,'stateKey',e.target.value)}/></label>
        <label>{t('writing.tools.stateValue')}<input value={event.stateValue || ''} onChange={e => eventChange(index,'stateValue',e.target.value)}/></label>
        <label>{t('writing.tools.eventKind')}<input value={event.kind} onChange={e => eventChange(index,'kind',e.target.value)}/></label>
        <label>{t('writing.tools.eventNote')}<textarea value={event.note} onChange={e => eventChange(index,'note',e.target.value)}/></label>
        <label className="writing-check"><input type="checkbox" checked={Boolean(event.productionRelevant)} onChange={e => eventChange(index,'productionRelevant',e.target.checked)}/>{t('writing.tools.productionRelevant')}</label>
        <button type="button" onClick={() => change('events',draft.events.filter((_,at) => at !== index))}>{t('writing.tools.removeEvent')}</button>
      </fieldset>)}
      <datalist id="writing-event-scenes">{scenes.map(scene => <option value={scene.sceneKey} key={scene.sceneKey}>{scene.title || scene.sceneKey}</option>)}</datalist>
      <button type="button" disabled={!entry && draft.entryKind !== 'asset_extension'} onClick={() => change('events',[...draft.events,{eventId:`evt_${actionId()}`,subjectId:entry?.assetId || entry?.bibleId || draft.assetId,episodeId:epId,sceneKey:scenes[0]?.sceneKey || '',kind:'',note:'',productionRelevant:false}])}>{t('writing.tools.addEvent')}</button>
    </fieldset>
    {manager.dirty && <p role="status">{t(recovery.recoverable?'writing.tools.localDraft':'writing.tools.unsaved')}</p>}
    {saved && !manager.dirty && <p role="status">{t('writing.tools.saved')}</p>}
    {recovery.localError && <><p role="alert">{t('writing.tools.localCheckpointFailed')}</p>
      {!manager.dirty && <button type="button" disabled={task.busy} onClick={()=>task.run(()=>manager.discover())}>{t('writing.tools.checkpointDraft')}</button>}
    </>}
    {recovery.recoveries.length>0 && <section aria-label={t('writing.tools.recoveryTitle')}><h4>{t('writing.tools.recoveryTitle')}</h4><p>{t('writing.tools.recoveryHelp')}</p>
      {recovery.recoveries.map(row=><article className="writing-change" key={row.key}><strong>{row.draft.title || row.base?.bibleId || t(`writing.tools.${row.draft.entryKind}`)}</strong>
        <pre>{JSON.stringify(row.draft,null,2)}</pre>
        {recovery.preservedRecoveryKeys.includes(row.key)&&<p role="status">{t('writing.tools.preservationConfirmed')}</p>}
        <button type="button" disabled={task.busy||manager.dirty} onClick={()=>restoreDraft(row)}>{t('writing.tools.restoreDraft')}</button>
        <button type="button" disabled={task.busy} onClick={()=>downloadDraft(row.draft)}>{t('writing.tools.downloadPrivateDraft')}</button>
        <button type="button" disabled={task.busy} onClick={()=>task.run(()=>manager.preserveRecovery(row))}>{t('writing.tools.preserveRecovery')}</button>
        <button type="button" disabled={task.busy} onClick={()=>task.run(()=>manager.discardRecovery(row))}>{t('writing.tools.discardRecovery')}</button>
      </article>)}
    </section>}
    {recovery.conflict && <section aria-label={t('writing.tools.reviewConflict')}><p role="alert">{t('writing.tools.privateConflict')}</p>
      <button type="button" disabled={task.busy||recovery.state==='auth_lost'} onClick={reviewCurrent}>{t('writing.tools.reviewCurrent')}</button>
      {recovery.remote && <><h4>{t('writing.tools.currentSharedFields')}</h4><pre>{JSON.stringify(recovery.remote,null,2)}</pre>
        <button type="button" disabled={task.busy||recovery.state==='auth_lost'} onClick={()=>{if(manager.merged())task.clear();}}>{t('writing.tools.confirmReviewedMerge')}</button></>}
    </section>}
    {recovery.identityPreserved && <p role="status">{t('writing.tools.preservationConfirmed')}</p>}
    {recovery.identityRequested && manager.dirty && !recovery.identityPreserved && <p role="alert">{t('writing.tools.identityDraftDecision')}</p>}
    {manager.dirty && <div className="writing-actions">
      <button type="button" disabled={task.busy} onClick={()=>task.run(()=>manager.checkpoint())}>{t('writing.tools.checkpointDraft')}</button>
      <button type="button" disabled={task.busy} onClick={()=>downloadDraft(manager.draft)}>{t('writing.tools.downloadPrivateDraft')}</button>
      <button type="button" disabled={task.busy} onClick={()=>task.run(()=>manager.preserveIdentity())}>{t('writing.tools.preserveIdentity')}</button>
      <button type="button" disabled={task.busy} onClick={discardDraft}>{t('writing.tools.discardPrivateDraft')}</button>
    </div>}
    <button type="button" className="writing-primary" disabled={!writable || task.busy || !manager.dirty || recovery.conflict || recovery.state==='auth_lost' || recovery.recoveries.length>0} onClick={save}>{t(entry ? 'writing.tools.save' : 'writing.tools.createEntry')}</button>
    <h4>{t('writing.tools.appearances')}</h4>
    <p className="writing-help">{t('writing.tools.appearanceHelp')}</p>
    <button type="button" disabled={task.busy} onClick={appearances}>{t('writing.tools.refresh')}</button>
    {matrix && <div className="writing-matrix"><table><thead><tr><th>{t('writing.tools.subject')}</th>{scenes.map(scene => <th key={scene.sceneKey}>{scene.title || scene.sceneKey}</th>)}</tr></thead><tbody>
      {matrix.rows.map(row => <tr key={row.subjectId}><th>{row.asset?.name || row.subjectId}<p>{t('writing.tools.explicitReferences',{count:row.explicitSceneCount})}</p><p>{t('writing.tools.mentions',{count:row.mentionCount})}</p></th>
        {scenes.map(scene => {const cell = row.cells.find(item => item.sceneKey === scene.sceneKey); return <td key={scene.sceneKey}>{cell && <>
          <button type="button" onClick={() => onNavigateSource?.({sceneKey:cell.sceneKey})}>{t('writing.tools.explicitReferences',{count:cell.explicitReference ? 1 : 0})}</button>
          <button type="button" disabled={!cell.shotIds?.length} onClick={() => onNavigateShots?.({shotIds:cell.shotIds})}>{t('writing.tools.shotCount',{count:cell.shotCount})}</button>
          <p>{t('writing.tools.mentions',{count:cell.mentionCount})}</p>
        </>}</td>;})}</tr>)}
    </tbody></table></div>}
    {entry?.continuityWarnings?.length > 0 && <section><h4>{t('writing.tools.continuity')}</h4>{entry.continuityWarnings.map((warning,index) => <p key={index}>{typeof warning === 'string' ? warning : warning.kind === 'orphaned_event' ? t('writing.tools.orphanWarning',{id:warning.eventId}) : warning.kind === 'conflicting_explicit_states' ? t('writing.tools.stateConflictWarning',{ids:warning.eventIds.join(', ')}) : t('writing.tools.referenceWarning')}</p>)}</section>}
  </div>;
}
