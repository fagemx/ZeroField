import React, {useEffect, useState} from 'react';
import {useTranslation} from '../i18n/react.jsx';
import {expiryLabel, frozenRequest, previewUsable, resourceOptions, serverFlush} from './writingToolsModel.js';
import {ToolsNotice, useToolsAction, useToolsResourceCatalog} from './writingToolsState.js';

export function WritingSearch({writable, workspace, resourceRef = {kind:'working'}, transport, flush, reload, onNavigateSource, onError, onChanged}) {
  const {t} = useTranslation();
  const task = useToolsAction(onError);
  const catalog = useToolsResourceCatalog(workspace);
  const options = resourceOptions(catalog.workspace,resourceRef);
  const [query,setQuery] = useState('');
  const [scope,setScope] = useState([{sourceRef:resourceRef}]);
  const [otherEpisode,setOtherEpisode] = useState('');
  const [bibleId,setBibleId] = useState('');
  const [caseSensitive,setCaseSensitive] = useState(false);
  const [wholeWord,setWholeWord] = useState(false);
  const [results,setResults] = useState(null);
  const [criteria,setCriteria] = useState(null);
  const [selected,setSelected] = useState([]);
  const [replacement,setReplacement] = useState('');
  const [preview,setPreview] = useState(null);
  const [actions,setActions] = useState([]);
  const [done,setDone] = useState(false);
  const [,tick] = useState(0);
  useEffect(() => {const timer = setInterval(() => tick(value => value+1),15000);return () => clearInterval(timer);},[]);
  useEffect(() => {if (['stale','locked','conflict','auth'].includes(task.error)) setPreview(value => value ? {...value,stale:true} : null);},[task.error]);
  function invalidate() {setResults(null);setCriteria(null);setSelected([]);setPreview(null);setDone(false);task.clear();}
  function changeScope(item, checked) {
    const key = JSON.stringify(item);
    setScope(value => checked ? [...value.filter(entry => JSON.stringify(entry)!==key),item] : value.filter(entry => JSON.stringify(entry)!==key));invalidate();
  }
  function search(cursor) {
    const body = cursor ? {...criteria,cursor} : {query,scope,caseSensitive,wholeWord};
    const request = frozenRequest(transport,'search','POST',body);
    task.run(async signal => {
      if (writable && resourceRef.kind !== 'version' && body.scope.some(item => !item.episodeId && JSON.stringify(item.sourceRef) === JSON.stringify(resourceRef))) await serverFlush(flush);
      return request(signal);
    }, result => {
      setCriteria({query,scope:structuredClone(scope),caseSensitive,wholeWord});
      setResults(previous => ({...result,items:cursor ? [...previous.items,...result.items] : result.items}));
      if (!cursor) {setSelected([]);setPreview(null);}setDone(false);
    });
  }
  function replacePreview() {
    const request = frozenRequest(transport,'previews','POST',{kind:'replace',...criteria,replacement,matchIds:selected});
    task.run(async signal => {await serverFlush(flush);return request(signal);}, result => {
      setPreview(result);setActions([]);setDone(false);
    });
  }
  function apply() {
    if (!previewUsable(preview) || !actions.length) return;
    const request = frozenRequest(transport,`previews/${encodeURIComponent(preview.previewId)}/apply`,'POST',{
      expectedPreviewVersion:preview.version,selection:{actions:actions.map(actionId => ({actionId}))}});
    task.run(async signal => {await serverFlush(flush);return request(signal);}, async (result,signal) => {
      if (typeof result?.replaced !== 'number') throw Object.assign(new Error('Invalid replace acknowledgement'),{status:502});
      setPreview(null);setResults(null);setSelected([]);setDone(true);await reload?.();
      if (!signal.aborted) await onChanged?.(result);
    });
  }
  function toggle(id, checked, setter) {setter(value => checked ? [...value.filter(item => item !== id),id] : value.filter(item => item !== id));}
  const eligible = results?.items.filter(item => item.editable && !item.protected) || [];
  const changes = preview?.proposedChanges?.actions || [];
  const allowed = new Set((preview?.allowedActions || []).map(action => action.actionId));
  return <div>
    <p className="writing-help">{t('writing.tools.scopeHelp')}</p>
    <ToolsNotice task={task} t={t}/>
    <label>{t('writing.tools.query')}<input data-writing-query disabled={task.busy} value={query} onChange={event => {setQuery(event.target.value);invalidate();}}/></label>
    <fieldset disabled={task.busy}><legend>{t('writing.tools.scope')}</legend>
      {options.map(option => {const item = {sourceRef:option.ref};return <label className="writing-check" key={JSON.stringify(item)}><input type="checkbox"
        checked={scope.some(entry => JSON.stringify(entry)===JSON.stringify(item))} onChange={event => changeScope(item,event.target.checked)}/>{t(`writing.tools.${option.key}`,{name:option.name})}</label>;})}
      {['versions','branches'].map(kind => catalog.workspace[kind].nextCursor && <button type="button" key={kind} onClick={() => task.run(signal => catalog.loadMore(kind,transport,signal))}>{t(kind==='versions'?'writing.tools.moreVersions':'writing.tools.moreBranches')}</button>)}
      <label>{t('writing.tools.otherEpisode')}<input value={otherEpisode} onChange={event => setOtherEpisode(event.target.value)}/></label>
      <button type="button" disabled={!otherEpisode.trim() || scope.length >= 20} onClick={() => {changeScope({episodeId:otherEpisode.trim(),sourceRef:{kind:'working'}},true);setOtherEpisode('');}}>{t('writing.tools.addEpisode')}</button>
      <label>{t('writing.tools.sharedBible')}<input value={bibleId} onChange={event => setBibleId(event.target.value)}/></label>
      <button type="button" disabled={!bibleId.trim() || scope.length >= 20} onClick={() => {changeScope({kind:'bible',id:bibleId.trim()},true);setBibleId('');}}>{t('writing.tools.addToScope')}</button>
      {scope.filter(item => item.episodeId || item.kind === 'bible').map(item => <label className="writing-check" key={JSON.stringify(item)}><input type="checkbox" checked onChange={() => changeScope(item,false)}/>{item.episodeId || item.id}</label>)}
    </fieldset>
    <label className="writing-check"><input type="checkbox" disabled={task.busy} checked={caseSensitive} onChange={event => {setCaseSensitive(event.target.checked);invalidate();}}/>{t('writing.tools.caseSensitive')}</label>
    <label className="writing-check"><input type="checkbox" disabled={task.busy} checked={wholeWord} onChange={event => {setWholeWord(event.target.checked);invalidate();}}/>{t('writing.tools.wholeWord')}</label>
    <button type="button" disabled={task.busy || !query || Array.from(query).length > 200 || !scope.length || scope.length > 20} onClick={() => search()}>{t('writing.tools.searchAction')}</button>
    {results && <section><h4>{t('writing.tools.searchResults',{count:results.total})}</h4>
      <div className="writing-actions"><button type="button" disabled={!writable || task.busy} onClick={() => {setSelected(eligible.map(item => item.matchId));setPreview(null);task.clear();}}>{t('writing.tools.selectAll')}</button>
        <button type="button" disabled={task.busy} onClick={() => {setSelected([]);setPreview(null);task.clear();}}>{t('writing.tools.clearSelection')}</button></div>
      {results.items.map(match => <article className="writing-change" key={match.matchId}>
        <label className="writing-check"><input type="checkbox" aria-label={t('writing.tools.selectMatch',{text:match.before})} disabled={!writable || !match.editable || match.protected || task.busy}
          checked={selected.includes(match.matchId)} onChange={event => {toggle(match.matchId,event.target.checked,setSelected);setPreview(null);task.clear();}}/>
          {match.contextBefore}<mark>{match.before}</mark>{match.contextAfter}</label>
        <span className="writing-resource">{match.resourceRef?.sourceRef?.kind === 'source' || match.resourceRef?.sourceRef?.kind === 'branch' ? t('writing.tools.private') : t('writing.tools.shared')}
          {' · '}{match.resourceRef?.episodeId || ''}{' · '}{match.resourceRef?.sourceRef?.id || match.resourceRef?.sourceRef?.mode || match.resourceRef?.id || t('writing.tools.working')}{' · '}{match.version}</span>
        <span className="writing-help">{t('writing.tools.matchLocation',{block:match.blockKey,start:match.start,end:match.end})}</span>
        {(!match.editable || match.protected) && <p>{t('writing.tools.lockedMatch')}</p>}
        {match.sceneKey && <button type="button" onClick={() => onNavigateSource?.({sceneKey:match.sceneKey,beatKey:match.beatKey})}>{t('writing.tools.goToScene')}</button>}
      </article>)}
      {results.nextCursor && <button type="button" disabled={task.busy} onClick={() => search(results.nextCursor)}>{t('writing.tools.more')}</button>}
      <p className="writing-help">{t('writing.tools.replaceHelp')}</p>
      <label>{t('writing.tools.replacement')}<input disabled={task.busy} value={replacement} onChange={event => {setReplacement(event.target.value);setPreview(null);task.clear();}}/></label>
      <button type="button" disabled={!writable || task.busy || !selected.length} onClick={replacePreview}>{t('writing.tools.replacePreview')}</button>
    </section>}
    {preview && <section><p>{t('writing.tools.previewExpiry',{time:expiryLabel(preview.expiresAt)})}</p>
      {!previewUsable(preview) && <p role="alert">{t('writing.tools.stale')}</p>}
      {changes.map(change => <article key={change.actionId} className="writing-change">
        <label className="writing-check"><input type="checkbox" aria-label={t('writing.tools.selectChange',{id:change.actionId})}
          disabled={!allowed.has(change.actionId) || task.busy || !previewUsable(preview)} checked={actions.includes(change.actionId)} onChange={event => {toggle(change.actionId,event.target.checked,setActions);task.clear();}}/>{change.blockKey}</label>
        <span>{t('writing.tools.before')}</span><pre className="writing-before">{change.before}</pre>
        <span>{t('writing.tools.after')}</span><pre className="writing-after">{change.after}</pre>
      </article>)}
      {preview.warnings?.map((warning,index) => <p key={index}>{typeof warning === 'string' ? warning : warning.message || warning.code}</p>)}
      <button type="button" className="writing-primary" disabled={!writable || task.busy || !actions.length || !previewUsable(preview)} onClick={apply}>{t('writing.tools.apply')}</button>
    </section>}
    {done && <p role="status">{t('writing.tools.replaceDone')}</p>}
  </div>;
}
