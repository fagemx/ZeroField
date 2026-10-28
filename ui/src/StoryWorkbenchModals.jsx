import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocale } from './i18n/react.jsx';
import { t } from './i18n/index.js';
import { api } from './api.js';
import { usePolling } from './polling.js';
import { SheetDialog } from './SheetDialog.jsx';
import { MediaCell } from './MediaCell.jsx';
import { episodeId, shotId, selectedTake, storyList, storyRequest, waitStoryTask } from './storyModel.js';
import { normalizeStatus, statusLabel } from './format.js';
import { ProposalRaceView } from './assistant/ProposalRaceView.jsx';
import { allocationPath, escalationPath, allocationDispatchBody, approvedCompositionSource, allocationBlockerLabel, GRADE_ACTIVE, gradesActive, takeGrade } from './storyModel.js';
import { missingAssetSheets, assetGroupActive, rememberAssetGroup, restoredAssetGroup } from './storyImport.js';
import './story-workbench.css';

function useStoryAction(onChanged) {
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [task, setTask] = useState(null);
  const controller = useRef(null), working = useRef(false);
  useEffect(() => () => controller.current?.abort(), []);
  const run = async action => {
    if (working.current) return;
    working.current = true; setBusy(true); setError('');
    controller.current = new AbortController();
    try {
      const result = await action(async pending => {
        setTask(pending);
        return waitStoryTask(pending, {signal:controller.current.signal, onProgress:setTask});
      });
      if (!controller.current.signal.aborted) await onChanged?.();
      return result;
    } catch (err) { if (err.name !== 'AbortError') setError(err.message); }
    finally { if (!controller.current.signal.aborted) setBusy(false); working.current = false; }
  };
  return {busy, error, task, run};
}

function ActionState({action}) {
  return <>{action.error && <p role="alert" className="canvas-error">{action.error}</p>}{action.busy && <p role="status">{t('story.working')}{action.task && <> · {action.task.taskId}</>}</p>}</>;
}

// SPEC_14 P5 lenses and the P3 choice trace: keep or strike collision cards, pick a focus, add one condition.
// Off (no medium lens) keeps the classic adaptation and its request unchanged.
export function CompositionPanel({value, disabled, onChange, onCollide}) {
  useLocale();
  const {medium, genre, collisions, unchecked, focus, extra} = value;
  const reset = {collisions:null, unchecked:[]};
  // Lenses and focus are light pills on the page (SPEC_15), one pressed per group.
  const pills = (label, options, current, key, pick) => <div className="story-pills" role="group" aria-label={label}><span>{label}</span>
    {options.map(option => <button key={option} type="button" aria-pressed={current === option} disabled={disabled} onClick={() => pick(option)}>{t(key + (option || 'off'))}</button>)}</div>;
  return <fieldset className="story-composition"><legend>{t('story.composition')}</legend>
    {pills(t('story.mediumLens'), ['', 'manju', 'cinema', 'storybook'], medium, 'story.mediumLens_', m => onChange({medium:m, ...reset}))}
    {medium && <>
      {pills(t('story.genreLens'), ['general', 'melodrama', 'xianxia', 'comedy', 'suspense'], genre, 'story.genreLens_', g => onChange({genre:g, ...reset}))}
      <button type="button" disabled={disabled || !onCollide} onClick={onCollide}>{t('story.collideConditions')}</button>
      {collisions && <>
        <p>{t('story.collisionHelp')}</p>
        <ul className="story-collisions">{collisions.candidates.map(card => {
          const struck = unchecked.includes(card.label);
          return <li key={card.id} className={struck ? 'is-struck' : undefined}><label>
            <input type="checkbox" checked={!struck} disabled={disabled} onChange={() => onChange({unchecked:struck ? unchecked.filter(label => label !== card.label) : [...unchecked, card.label]})}/>
            <span><strong>{card.label}</strong> · {t('story.focus_' + card.focus)}<br/>{card.conditionA} × {card.conditionB}</span>
          </label></li>;
        })}</ul>
        {pills(t('story.choiceFocus'), ['overall', 'collision', 'restraint', 'reversal', 'negative_space'], focus, 'story.focus_', f => onChange({focus:f}))}
        <label className="modal-field">{t('story.extraCondition')}<input value={extra} maxLength={500} disabled={disabled} placeholder={t('story.extraConditionHint')} onChange={e => onChange({extra:e.target.value})}/></label>
      </>}
    </>}
  </fieldset>;
}

export function CompositionReport({report}) {
  useLocale();
  if (!report?.voiceAudit) return null;
  const {voiceAudit, choiceTrace} = report;
  return <p role="status" className="story-voice">
    {voiceAudit.ok ? t('story.voiceClean', {score:voiceAudit.concreteScore}) : t('story.voiceFlagged', {labels:voiceAudit.violations.join(', ')})}
    {choiceTrace?.contrastDetected && <><br/>{t('story.contrastDetected', {cue:choiceTrace.contrastCue})}</>}
  </p>;
}

export function AssetGenerationState({group, error, onRefresh}) {
  if (!group) return null;
  const counts = group.counts || {total:group.taskIds.length, queued:group.taskIds.length};
  const taskLabels = {QUEUED:'queued', RUNNING:'running', SUCCEEDED:'succeeded', FAILED:'failed', CANCELED:'canceled'};
  return <section aria-label={t('story.assetGenerationProgress')}>
    <p role="status">{t('story.assetGenerationCounts',{total:counts.total || 0, queued:counts.queued || 0, running:counts.running || 0, succeeded:counts.succeeded || 0, failed:Number(counts.failed || 0) + Number(counts.canceled || 0)})}</p>
    {!!group.assetCodes?.length && <p>{group.assetCodes.map(code => '@' + code).join(', ')}</p>}
    {!!group.tasks?.length && <details><summary>{t('story.assetGenerationTasks')}</summary><ul>{group.tasks.map(task => <li key={task.taskId}>{task.taskId} · {t('story.assetTask_' + (taskLabels[task.status] || 'unknown'))}{task.error?.message && <> · {task.error.message}</>}</li>)}</ul></details>}
    {Number(counts.failed || 0) + Number(counts.canceled || 0) > 0 && <p>{t('story.assetGenerationRetryHelp')}</p>}
    {error && <p role="alert">{t('story.assetGenerationRefreshFailed',{message:error})}</p>}
    {error && <button onClick={onRefresh}>{t('story.refreshAssetTasks')}</button>}
  </section>;
}

export function AssetVaultModal({epId, writable, onClose, onChanged, onNavigate}) {
  const [assets, setAssets] = useState([]), [selected, setSelected] = useState(''), [detail, setDetail] = useState(null);
  const [name, setName] = useState(''), [key, setKey] = useState(''), [prompt, setPrompt] = useState(''), [error, setError] = useState(''), [editing, setEditing] = useState(null);
  const [episode, setEpisode] = useState(null), [loading, setLoading] = useState(true), [group, setGroup] = useState(null), [groupError, setGroupError] = useState(''), [pollVersion, setPollVersion] = useState(0);
  const selectedRef = useRef(selected); selectedRef.current = selected;
  const action = useStoryAction(async () => {await loadVault(); await loadDetail(selected); await onChanged?.();});
  const loadVault = async () => {
    const [items, ep] = await Promise.all([storyList(`/episodes/${epId}/assets`), storyRequest('/episodes/' + epId)]);
    setAssets(items); setEpisode(ep);
    setSelected(current => items.some(item => item.assetId === current) ? current : items[0]?.assetId || '');
  };
  const loadDetail = async id => {if (id) setDetail(await storyRequest('/assets/' + id));};
  const missing = missingAssetSheets(episode), generating = assetGroupActive(group);
  useEffect(() => {
    let alive = true; setLoading(true); setEpisode(null); setGroup(restoredAssetGroup(epId)); setGroupError(''); setError('');
    Promise.all([storyList(`/episodes/${epId}/assets`), storyRequest('/episodes/' + epId)]).then(([items, ep]) => {
      if (alive) {setAssets(items); setEpisode(ep); setSelected(items[0]?.assetId || '');}
    }).catch(e => {if (alive) setError(e.message);}).finally(() => {if (alive) setLoading(false);});
    return () => {alive = false;};
  }, [epId]);
  useEffect(() => {
    if (!group?.taskGroupId) return;
    let alive = true, timer;
    setGroupError('');
    const poll = async () => {
      try {
        const next = await storyRequest('/task-groups/' + group.taskGroupId);
        if (!alive) return;
        rememberAssetGroup(epId, next);
        setGroup(current => ({...current, ...next}));
        if (assetGroupActive(next)) timer = setTimeout(poll, 1500);
        else {await loadVault(); if (alive) {await loadDetail(selectedRef.current); await onChanged?.();}}
      } catch (err) {if (alive) setGroupError(err.message);}
    };
    poll();
    return () => {alive = false; clearTimeout(timer);};
  }, [group?.taskGroupId, pollVersion]);
  useEffect(() => {
    let alive = true; setDetail(null); setEditing(null); setName(''); setKey(''); setPrompt('');
    if (selected) storyRequest('/assets/' + selected).then(item => {if (alive) setDetail(item);}).catch(e => {if (alive) setError(e.message);});
    return () => {alive = false;};
  }, [selected]);
  return <SheetDialog title={t('story.assetVault')} wide onClose={action.busy ? () => {} : onClose}>
    <button disabled={action.busy} onClick={onNavigate}>{t('story.openAssetSheet')}</button>
    <button disabled={!writable || action.busy || loading || generating || !missing.length} onClick={() => action.run(async () => {
      setError(''); setGroupError('');
      const pending = await storyRequest(`/episodes/${epId}/asset-image-generations`, 'POST', {appCode:'flux-soul-cast'});
      rememberAssetGroup(epId, pending); setGroup(pending);
    })}>{t('story.generateMissingAssets')}</button>
    <p>{t(loading ? 'story.assetReadinessLoading' : !episode ? 'story.assetReadinessUnavailable' : missing.length ? 'story.missingAssetCount' : 'story.noMissingAssets',{count:missing.length})}</p>
    <AssetGenerationState group={group} error={groupError} onRefresh={() => setPollVersion(value => value + 1)}/>
    <label className="modal-field">{t('story.asset')}<select value={selected} disabled={action.busy} onChange={e => setSelected(e.target.value)}>{assets.map(a => <option key={a.assetId} value={a.assetId}>@{a.assetCode} · {a.name}</option>)}</select></label>
    {detail && <><p>{detail.prompt}</p><div className="story-variants">{[detail, ...detail.variants].map(a => <figure key={a.assetId}>{a.selectedImageUrl && <MediaCell compact type="image" value={a.selectedImageUrl} label={a.name}/>}<figcaption>@{a.assetCode} · {a.name}</figcaption>{a.variantId && writable && <div><button disabled={action.busy} onClick={() => {setEditing(a.variantId); setName(a.name); setKey(a.assetCode.split(':')[1].toLowerCase()); setPrompt(a.prompt);}}>{t('story.editVariant')}</button><button disabled={action.busy} onClick={() => action.run(() => storyRequest(`/assets/${selected}/variants/${a.variantId}`, 'DELETE'))}>{t('story.deleteVariant')}</button></div>}</figure>)}</div>
      <p>{t('story.assetUses',{shots:detail.shotIds?.length || 0,scenes:detail.sceneIds?.length || 0})}</p>
      <form onSubmit={e => {e.preventDefault(); action.run(async () => {await storyRequest(`/assets/${selected}/variants${editing ? '/' + editing : ''}`, editing ? 'PATCH' : 'POST', {name, key, prompt, kind:'OUTFIT'}); setName(''); setKey(''); setPrompt(''); setEditing(null);});}}>
        <h3>{t(editing ? 'story.editVariant' : 'story.addVariant')}</h3><label className="modal-field">{t('story.variantName')}<input required value={name} disabled={!writable || action.busy} onChange={e => setName(e.target.value)}/></label>
        <label className="modal-field">{t('story.variantKey')}<input required pattern="(?:[a-z0-9_]|-)+" value={key} placeholder="night" disabled={!writable || action.busy || !!editing} onChange={e => setKey(e.target.value)}/></label>
        <label className="modal-field">{t('story.variantPrompt')}<textarea value={prompt} disabled={!writable || action.busy} onChange={e => setPrompt(e.target.value)}/></label>
        <button disabled={!writable || action.busy || !name.trim() || !key}>{t(editing ? 'story.saveVariant' : 'story.addVariant')}</button>{editing && <button type="button" onClick={() => {setEditing(null); setName(''); setKey(''); setPrompt('');}}>{t('common.cancel')}</button>}
      </form></>}
    {error && <p role="alert">{error}</p>}<ActionState action={action}/>
  </SheetDialog>;
}

export function ToolboxModal({writable, onClose}) {
  const [cards, setCards] = useState([]), [workflow, setWorkflow] = useState(''), [curl, setCurl] = useState(''), [name, setName] = useState(''), [error, setError] = useState('');
  const load = async () => {const data = await api.get('/openapi/v2/cards'); setCards(data.cards);};
  const action = useStoryAction(load);
  useEffect(() => {let alive = true; api.get('/openapi/v2/cards').then(data => {if (alive) setCards(data.cards);}).catch(e => {if (alive) setError(e.message);}); return () => {alive = false;};}, []);
  return <SheetDialog title={t('story.toolbox')} wide onClose={action.busy ? () => {} : onClose}>
    <p>{t('story.toolboxHelp')}</p>
    {cards.map(card => <details key={card.card_id}><summary>{card.label} · {card.card_id} · {card.engine_config.webappId} · {card.engine_config.frame_rule || card.engine_config.frame_formula || '—'}</summary>
      <div className="story-node-table"><table><thead><tr>{['nodeId','fieldName','fieldType','slot'].map(key => <th key={key}>{key}</th>)}</tr></thead><tbody>{card.nodes.filter(n => !n.hidden).map(n => <tr key={n.nodeId + '.' + n.fieldName}><td>{n.nodeId}</td><td>{n.fieldName}</td><td>{n.fieldType}</td><td>{n.slot || '—'}</td></tr>)}</tbody></table></div></details>)}
    <h3>{t('story.importCard')}</h3>
    <label className="modal-field">{t('story.cardName')}<input value={name} disabled={!writable || action.busy} onChange={e => setName(e.target.value)}/></label>
    <label className="modal-field">{t('story.workflowJson')}<input type="file" accept=".json,application/json" disabled={!writable || action.busy} onChange={async e => {try {const file = e.target.files?.[0]; if (file) {if (file.size > 2000000) throw new Error(t('story.scriptTooLarge')); setWorkflow(await file.text());}} catch (err) {setError(err.message);}}}/><textarea aria-label={t('story.workflowJson')} rows={6} value={workflow} disabled={!writable || action.busy} onChange={e => setWorkflow(e.target.value)}/></label>
    <label className="modal-field">{t('story.runninghubCurl')}<textarea rows={4} value={curl} disabled={!writable || action.busy} onChange={e => setCurl(e.target.value)}/></label>
    <button disabled={!writable || action.busy || !workflow.trim()} onClick={() => action.run(async () => {
      await api.post('/openapi/v2/cards/register', {workflow:JSON.parse(workflow), ...(name ? {label:name} : {}), ...(curl ? {curl} : {})}); setWorkflow(''); setCurl('');
    })}>{t('story.registerCard')}</button>
    {error && <p role="alert">{error}</p>}<ActionState action={action}/>
  </SheetDialog>;
}

export function OpenApiModal({slug, epId, onClose}) {
  const [cards, setCards] = useState([]), [selected, setSelected] = useState(''), [operation, setOperation] = useState('video-generations'), [target, setTarget] = useState('');
  const [result, setResult] = useState(''), [copied, setCopied] = useState(false), [error, setError] = useState('');
  useEffect(() => {let alive = true; api.get('/openapi/v2/cards').then(data => {if (alive) {setCards(data.cards); setSelected(data.cards[0]?.card_id || '');}}).catch(e => {if (alive) setError(e.message);}); return () => {alive = false;};}, []);
  const card = cards.find(c => c.card_id === selected);
  const nodes = card?.nodes.filter(n => !n.hidden).map(n => ({nodeId:n.nodeId, fieldName:n.fieldName, fieldValue:n.defaultValue ?? 'None'})) || [];
  const path = operation === 'video-generations' ? `/shots/${target || shotId(slug, 'ROW_ID')}/video-generations` : `/episodes/${epId}/${operation}`;
  const body = operation === 'video-generations' ? {appCode:card?.card_id || 'ltx25-cinema', modelParams:{}} : {};
  const host = window.location.origin;
  const shellQuote = value => "'" + value.replaceAll("'", "'\\''") + "'";
  const snippet = `curl -X POST ${shellQuote(host + '/openapi/v2/run/ai-app/' + (card?.engine_config.webappId || ''))} \\\n  -H 'Authorization: Bearer YOUR_TOKEN' -H 'Content-Type: application/json' \\\n  -d ${shellQuote(JSON.stringify({nodeInfoList:nodes}))}\n\ncurl -X POST ${shellQuote(host + '/aivideo/open/v1' + path)} \\\n  -H 'Authorization: Bearer YOUR_TOKEN' -H 'Content-Type: application/json' \\\n  -H 'Idempotency-Key: YOUR_UNIQUE_KEY' -d ${shellQuote(JSON.stringify(body))}`;
  const python = `import json, requests\nheaders = {"Authorization": "Bearer YOUR_TOKEN", "Idempotency-Key": "YOUR_UNIQUE_KEY"}\nrequests.post(${JSON.stringify(host + '/openapi/v2/run/ai-app/' + (card?.engine_config.webappId || ''))},\n  headers=headers, json=json.loads(${JSON.stringify(JSON.stringify({nodeInfoList:nodes}))}))\nrequests.post(${JSON.stringify(host + '/aivideo/open/v1' + path)},\n  headers=headers, json=json.loads(${JSON.stringify(JSON.stringify(body))}))`;
  return <SheetDialog title={t('story.openApi')} wide onClose={onClose}>
    <p>{t('story.apiHelp')}</p>
    <label className="modal-field">{t('story.appCode')}<select value={selected} onChange={e => setSelected(e.target.value)}>{cards.map(c => <option key={c.card_id} value={c.card_id}>{c.label}</option>)}</select></label>
    <label className="modal-field">{t('story.operation')}<select value={operation} onChange={e => setOperation(e.target.value)}>{['video-generations','asset-extractions','storyboards','films'].map(op => <option key={op}>{op}</option>)}</select></label>
    {operation === 'video-generations' && <label className="modal-field">{t('story.shotId')}<input value={target} onChange={e => setTarget(e.target.value)}/></label>}
    <pre className="story-code">{snippet}</pre><pre className="story-code">{python}</pre>
    <button onClick={async () => {try {await navigator.clipboard.writeText(snippet + '\n\n' + python); setCopied(true);} catch (e) {setError(e.message);}}}>{t(copied ? 'story.copied' : 'story.copyExamples')}</button>
    <button onClick={async () => {try {setResult(JSON.stringify(await storyRequest('/capabilities'), null, 2)); setError('');} catch (e) {setError(e.message);}}}>{t('story.testCapabilities')}</button>
    {result && <pre className="story-code">{result}</pre>}{error && <p role="alert">{error}</p>}
  </SheetDialog>;
}

export function StoryBatchBar({slug, epId = episodeId(slug), rowIds, writable, disabled, onChanged, beforeRun}) {
  useLocale();
  const [apps, setApps] = useState([]), [app, setApp] = useState('automatic');
  const [mode, setMode] = useState('lab_economical'), [policy, setPolicy] = useState('open_weights_only'), [ceiling, setCeiling] = useState('open_weights_only'), [allocation, setAllocation] = useState(null);
  const action = useStoryAction(onChanged);
  useEffect(() => {let alive=true; storyRequest(`/projects/pj_${slug}/production-policy`).then(data=>{if(alive){setPolicy(data.productionPolicy);setCeiling(data.deploymentPolicy);setMode(data.productionPolicy==='hybrid_studio'?'hybrid_balanced':'lab_economical');}}).catch(()=>{}); return()=>{alive=false;};}, [slug]);
  useEffect(() => {setAllocation(null);}, [epId, rowIds.join('|'), mode, policy, app]);
  useEffect(() => {let alive = true; Promise.all(['IMAGE','VIDEO'].map(capability => storyList('/catalog/apps?capability=' + capability))).then(lists => {if (alive) setApps(lists.flat());}).catch(() => {}); return () => {alive = false;};}, []);
  const selected = apps.find(a => a.appCode === app);
  return <div className={'story-batch' + (rowIds.length ? '' : ' is-idle')}>
    <details className="story-settings"><summary aria-label={t('allocation.settings')}><span className="story-policy-badge">{t(policy === 'open_weights_only' ? 'allocation.openBadge' : 'allocation.hybridBadge')}</span><span className="story-settings-summary">{t('allocation.mode_'+mode)} · {app==='automatic' ? t('allocation.automatic') : (selected?.name || app)}</span></summary>
      <div className="story-settings-body">
    <label>{t('allocation.policy')} <select aria-label={t('allocation.policy')} value={policy} disabled={!writable || disabled || action.busy} onChange={e=>{const next=e.target.value; action.run(async()=>{const saved=await storyRequest(`/projects/pj_${slug}/production-policy`,'PUT',{productionPolicy:next});setPolicy(saved.productionPolicy);setMode(saved.productionPolicy==='hybrid_studio'?'hybrid_balanced':'lab_economical');});}}><option value="open_weights_only">{t('allocation.openPolicy')}</option><option value="hybrid_studio" disabled={ceiling==='open_weights_only'}>{t('allocation.hybridPolicy')}</option></select></label>
    <label className="story-resource-pill">{t('allocation.resourceMode')} <select value={mode} disabled={disabled || action.busy} onChange={e=>setMode(e.target.value)}>{['lab_economical','hybrid_balanced','deadline_rush'].map(value=><option key={value} value={value}>{t('allocation.mode_'+value)}</option>)}</select></label>
    <label>{t('story.appCode')} <select aria-label={t('story.appCode')} value={app} disabled={action.busy || disabled} onChange={e => setApp(e.target.value)}><option value="automatic">{t('allocation.automatic')}</option>{apps.map(a => <option key={a.appCode} value={a.appCode}>{a.name} · {a.webappId}</option>)}</select></label>
      </div>
    </details>
    {rowIds.length ? <>
    <button disabled={!writable || disabled || action.busy || !rowIds.length || selected?.capability === 'IMAGE'} onClick={()=>action.run(async()=>{
      if(beforeRun?.()===false)return;
      setAllocation(await storyRequest(allocationPath(slug,epId),'POST',{budgetMode:mode,productionPolicy:policy,shotIds:rowIds.map(rid=>shotId(slug,rid)),...(app!=='automatic'?{appCode:app}:{})}));
    })}>{t('allocation.preflight')}</button>
    {allocation && <section className="story-allocation" aria-label={t('allocation.summary')}><p>{t('allocation.counts',{open:allocation.summary.openWeightsShotCount,closed:allocation.summary.closedHeroShotCount,cloud:allocation.summary.cloudBurstShotCount})}</p><p>{t('allocation.estimateCaution')}</p><ul>{allocation.allocations.map(item=><li key={item.shotId}>{item.shotId} · {t('allocation.complexity_'+item.complexityTier)} · {item.assignedCardId} · {t('allocation.tier_'+item.tier)}{!item.ready&&<strong> · {t('allocation.blocked')}: {item.configuration_blockers.map(allocationBlockerLabel).join('; ')}</strong>}</li>)}</ul></section>}
    <button disabled={!writable || disabled || action.busy || !rowIds.length || (selected?.capability !== 'IMAGE' && !allocation?.ready)} onClick={() => action.run(async wait => {
      if (beforeRun?.() === false) return;
      const group = await storyRequest(`/episodes/${epId}/shot-${selected?.capability === 'IMAGE' ? 'image' : 'video'}-generations`, 'POST',
        selected?.capability === 'IMAGE' ? {appCode:app, shotIds:rowIds.map(rid => shotId(slug, rid)),budgetMode:mode} : allocationDispatchBody(allocation,mode,policy));
      setAllocation(null);
      const results = await Promise.allSettled(group.taskIds.map(taskId => wait({taskId, status:'QUEUED'})));
      const failures = results.filter(result => result.status === 'rejected');
      if (failures.length) {await onChanged?.(); throw new Error(t('story.batchFailed',{count:failures.length}) + ' ' + failures[0].reason.message);}
    })}>{t('story.generateSelected', {count:rowIds.length})}</button>
    <button disabled={!writable || disabled || action.busy || rowIds.length<2} onClick={()=>action.run(()=>{
      if(beforeRun?.()===false)return;
      return storyRequest('/shot-merges','POST',{shotIds:rowIds.map(rid=>shotId(slug,rid))});
    })}>{t('story.mergeSelected')}</button>

    </> : <span className="story-batch-hint">{t('story.selectShotsHint')}</span>}
    <ActionState action={action}/>
  </div>;
}

export function ShotProduction({slug, actorId, rid, source, writable, disabled, onChanged, beforeRun}) {
  useLocale();
  const id = shotId(slug, rid);
  const draftKey=actorId ? `zf.shot:${slug}:${actorId}:${rid}` : null;
  const [draft]=useState(()=>{try{return draftKey ? JSON.parse(sessionStorage.getItem(draftKey)) || {}:{};}catch{return {};}});
  const [takes, setTakes] = useState({images:[], videos:[]}), [apps, setApps] = useState([]), [app, setApp] = useState(draft.app || 'LTX25_CINEMA_SHOT');
  const [values, setValues] = useState(draft.values || {}), [loaded, setLoaded] = useState(0), [error, setError] = useState(''), [shot, setShot] = useState(null), [mediaRun, setMediaRun] = useState(null);
  const action = useStoryAction(async () => {setLoaded(n => n + 1); await onChanged?.();});
  const mediaVersion = JSON.stringify([id,source?.mediaVersion]);
  const [takesVersion,setTakesVersion] = useState(null);
  const currentTakes = takesVersion === mediaVersion ? takes : {images:[],videos:[]};
  const reviewStatus = source?.status ?? shot?.reviewStatus;
  const compositionSource = approvedCompositionSource(currentTakes);
  // A video is in use once it is adopted (in the cell and the shot Approved); a still once it is the first frame.
  const inUse = (kind, take) => Boolean(take.selected) && (kind === 'images' || normalizeStatus(reviewStatus) === 'Approved');
  useEffect(() => {
    let alive = true;
    Promise.all([storyList('/shots/' + id + '/images'), storyList('/shots/' + id + '/videos'), storyRequest('/shots/' + id), ...['IMAGE','VIDEO'].map(capability => storyList('/catalog/apps?capability=' + capability))]).then(([images,videos,view,...lists]) => {
      if (alive) {setTakes({images,videos}); setTakesVersion(mediaVersion); setShot(view); setMediaRun(view.mediaRunId || null); setApps(lists.flat()); setError('');}
    }).catch(e => {if (alive) setError(e.message);});
    return () => {alive = false;};
  }, [id, loaded, source?.revision, source?.status, mediaVersion]);
  useEffect(() => {if(draftKey)try{sessionStorage.setItem(draftKey,JSON.stringify({app,values}));}catch{/* Mounted overrides remain available. */}}, [draftKey,app,values]);
  const selected = apps.find(a => a.appCode === app);
  const perform = fn => action.run(async wait => {if (beforeRun?.() === false) return; return fn(wait);});
  const grading = useTakeGrades(slug, id);
  // Retake with the grader's rewritten prompt: it becomes the shot's prompt and the shot re-renders, no approval step.
  const videoApp = selected?.capability === 'VIDEO' ? app : apps.find(a => a.capability === 'VIDEO')?.appCode;
  const retake = g => perform(async wait => {
    await storyRequest(`/shots/${id}`, 'PATCH', {description:g.retakePrompt});
    await wait(await storyRequest(`/shots/${id}/video-generations`, 'POST', {appCode:videoApp}));
  });
  return <section className="story-shot-tools">
    <h3>{t('story.candidateTakes')}</h3>
    {shot && <p>{normalizeStatus(reviewStatus) === 'Approved' ? t('take.adopted') : statusLabel(reviewStatus)} · {t('allocation.complexity_' + shot.complexity.complexity_tier)}</p>}
    {shot && ['Retake','Pending Review','Approved'].includes(normalizeStatus(reviewStatus)) && <div className="story-escalation" aria-label={t('allocation.escalation')}>
      {['closed_hero','open_structural_lock','ab_race','closed_to_open_4k'].map(strategy=><button key={strategy} disabled={!writable || disabled || action.busy} onClick={()=>perform(async()=>{const result=await storyRequest(escalationPath(slug,shot.episodeId || episodeId(slug),id),'POST',{strategy});setMediaRun(result.runId);})}>{t('allocation.strategy_'+strategy)}</button>)}
      <button disabled={!writable || disabled || action.busy || normalizeStatus(reviewStatus)!=='Approved' || !compositionSource} onClick={()=>perform(async()=>{const result=await storyRequest(escalationPath(slug,shot.episodeId || episodeId(slug),id),'POST',{chainMode:'open_previz_to_closed_hero',...compositionSource});setMediaRun(result.runId);})}>{t('allocation.approvedHero')}</button>
    </div>}
    {mediaRun && <MediaRunReview slug={slug} runId={mediaRun} writable={writable} onChanged={async()=>{setLoaded(n=>n+1);await onChanged?.();}}/>}
    {['images','videos'].map(kind => <div className="story-takes" key={kind}>{currentTakes[kind].map(take => <figure key={take.imageId || take.videoId}>
      <MediaCell compact type={kind === 'images' ? 'image' : 'video'} value={take.url} label={take.imageId || take.videoId}/>
      <figcaption><button disabled={!writable || disabled || action.busy || inUse(kind, take)} aria-pressed={inUse(kind, take)} onClick={() => perform(async () => {
        // SPEC_19 R1: using a take is adopting it (POST /shots/{id}/adoptions): a video joins the cut (status Approved, trim reset),
        // a still only becomes the first frame (1.2 J). The old PUT selected-video picked a take without putting it in the cut.
        await storyRequest(`/shots/${id}/adoptions`, 'POST', kind === 'images' ? {imageId:take.imageId} : {videoId:take.videoId});
        setTakes(old=>({...old,[kind]:selectedTake(old[kind],take.imageId||take.videoId,kind==='images'?'image':'video')}));
      })}>{kind === 'videos' ? t(inUse(kind, take) ? 'take.inCut' : 'take.adopt') : t(take.selected ? 'story.selectedTake' : 'story.useTake')}</button>
      {kind === 'videos' && <GradeButton grade={takeGrade(grading.grades, take.url)} disabled={!writable || grading.busy} onGrade={() => grading.grade({videoId:take.videoId})}/>}</figcaption>
    </figure>)}</div>)}
    <TakeGrades grading={grading} writable={writable} onRetake={videoApp && !disabled && !action.busy ? retake : null}/>
    <div className="sheet-panel-actions"><button disabled={!writable || disabled || action.busy} onClick={() => perform(() => storyRequest(`/shots/${id}/splits`, 'POST'))}>{t('story.splitShot')}</button>
      <button disabled={!writable || disabled || action.busy || !currentTakes.videos.some(v => v.selected)} onClick={() => perform(async wait => {
        await wait(await storyRequest(`/shots/${id}/video-generations`, 'POST', {appCode:'H3_OPTIMIZE_4K', referenceSourceVideoId:currentTakes.videos.find(v => v.selected).videoId}));
      })}>{t('story.restore4k')}</button></div>
    <details open={Object.keys(draft.values || {}).length ? true:undefined}><summary>{t('story.nodeInspector')}</summary>
      <label className="modal-field">{t('story.appCode')}<select value={app} disabled={action.busy} onChange={e => {setApp(e.target.value);setValues({});}}>{apps.map(a => <option key={a.appCode} value={a.appCode}>{a.name}</option>)}</select></label>
      <code>{selected?.webappId}</code>
      {selected?.nodes.filter(n => !n.hidden).map(node => {
        const key = node.nodeId + '.' + node.fieldName;
        return <label className="modal-field" key={key}><span>{key} · {node.label}</span><input aria-label={key} placeholder={String(node.defaultValue ?? '')} value={values[key] ?? ''} disabled={!writable || action.busy} onChange={e => setValues({...values,[key]:e.target.value})}/></label>;
      })}
      <button disabled={!writable || disabled || action.busy || !selected} onClick={() => perform(async wait => {
        await wait(await storyRequest(`/shots/${id}/${selected.capability === 'IMAGE' ? 'image' : 'video'}-generations`, 'POST', {appCode:app, modelParams:values}));
      })}>{t('story.reshootWithInputs')}</button>
    </details>
    {error && <p role="alert">{error}</p>}<ActionState action={action}/>
  </section>;
}

// Continuity grades of this row's takes; polls while a grade is queued, waiting for the GPU or running. A failed fetch shows its
// error but never stops the poll (backoff and wake-on-visible are in polling.js), so a grade stored meanwhile still appears.
function useTakeGrades(slug, id) {
  const [grades, setGrades] = useState([]), [auto, setAuto] = useState(false), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const shot = useRef(id);
  shot.current = id;
  const load = useCallback(async () => {
    try {
      const data = await storyRequest(`/shots/${id}/grades?limit=100`);
      if (shot.current === id) {setGrades(data.items); setAuto(data.autoGrade); setError('');}
    } catch (e) {
      if (shot.current === id) setError(e.message);
      throw e;
    }
  }, [id]);
  useEffect(() => {load().catch(() => {});}, [load]);
  usePolling(load, gradesActive(grades) ? 3000 : null);
  const call = async fn => {setBusy(true); try {await fn(); setError(''); load().catch(() => {});} catch (e) {setError(e.message);} finally {setBusy(false);}};
  return {grades, auto, error, busy,
    grade: body => call(() => storyRequest(`/shots/${id}/grades`, 'POST', body)),
    setAuto: value => call(async () => setAuto((await storyRequest(`/projects/pj_${slug}/grading`, 'PUT', {autoGrade:value})).autoGrade))};
}

function GradeButton({grade, disabled, onGrade}) {
  const running = grade && GRADE_ACTIVE.includes(grade.status);
  return <span className="take-grade-action">
    {grade?.status === 'graded' && <span className={'grade-pill ' + (grade.passed ? 'is-pass' : 'is-retake')}>{t('grade.score', {score:grade.score})}</span>}
    <button disabled={disabled || running} onClick={onGrade}>{running ? t('grade.status_' + grade.status) : t(grade ? 'grade.regrade' : 'grade.grade')}</button>
  </span>;
}

export function TakeGrades({grading, writable, onRetake}) {
  useLocale();
  return <section className="take-grades" aria-label={t('grade.title')}>
    <h3>{t('grade.title')}</h3>
    <label className="sheet-check" title={t('grade.autoHint')}><input type="checkbox" checked={grading.auto} disabled={!writable || grading.busy} onChange={e => grading.setAuto(e.target.checked)}/>{t('grade.autoGrade')}</label>
    {grading.error && <p role="alert">{grading.error}</p>}
    {!grading.grades.length && <p className="sheet-subtle">{t('grade.none')}</p>}
    {grading.grades.map(g => {
      const graded = g.status === 'graded';
      return <article key={g.gradeId} className={'take-grade ' + (graded ? (g.passed ? 'is-pass' : 'is-retake') : 'is-' + g.status)}>
        <div className="take-grade-media"><MediaCell compact type="video" value={g.assetUrl} label={g.assetId}/></div>
        <div className="take-grade-body">
          <p className="take-grade-head">{graded ? <><strong className={'grade-pill ' + (g.passed ? 'is-pass' : 'is-retake')}>{t('grade.score', {score:g.score})}</strong> <span>{t(g.passed ? 'grade.pass' : 'grade.retake')}</span></> : <strong role="status">{t('grade.status_' + g.status)}</strong>}
            {g.auto && <span className="grade-auto">{t('grade.auto')}</span>}</p>
          {g.feedback && <p>{g.feedback}</p>}
          {g.issues?.length > 0 && <ul aria-label={t('grade.issues')}>{g.issues.map((issue, i) => <li key={i}>{issue}</li>)}</ul>}
          {g.error && <p role="alert">{g.error}</p>}
          {graded && !g.passed && g.retakePrompt && <div className="take-grade-retake">
            <details><summary>{t('grade.retakePrompt')}</summary><p>{g.retakePrompt}</p></details>
            <button disabled={!writable || !onRetake} onClick={() => onRetake(g)}>{t('grade.retakeNow')}</button>
          </div>}
          {g.sheetUrl && <details><summary>{t('grade.sheet')}</summary><img src={g.sheetUrl} alt={t('grade.sheetAlt')} loading="lazy"/></details>}
          {graded && <small>{t(g.gpu?.comfyFreed ? 'grade.meta' : 'grade.metaNoComfy', {model:g.model, seconds:g.seconds})}</small>}
        </div>
      </article>;
    })}
  </section>;
}

function MediaRunReview({slug, runId, writable, onChanged}) {
  const [gate,setGate]=useState(null),[opened,setOpened]=useState(false),[error,setError]=useState(''),[runStatus,setRunStatus]=useState('active');
  useEffect(()=>{
    let alive=true;
    const load=()=>Promise.all([api.get(`/projects/api/${slug}/orchestration/board`),api.get(`/projects/api/${slug}/orchestration/runs/${runId}`)]).then(([data,detail])=>{if(alive){setGate(data.needs_you?.find(item=>item.run_id===runId && item.proposals?.length)||null);setRunStatus(detail.run.status);}}).catch(e=>{if(alive)setError(e.message);});
    load();const timer=setInterval(load,1500);return()=>{alive=false;clearInterval(timer);};
  },[slug,runId]);
  return <section className="story-media-review"><p role="status">{t('allocation.run_'+runStatus)}</p><p>{t('allocation.reviewRequired')}</p>
    {gate && <button disabled={!writable} onClick={()=>setOpened(true)}>{t('allocation.reviewCandidates')}</button>}
    <button disabled={!writable || ['failed','succeeded','canceled'].includes(runStatus)} onClick={async()=>{try{await api.post(`/projects/api/${slug}/orchestration/runs/${runId}/cancel`,{client_request_id:crypto.randomUUID()});setGate(null);await onChanged?.();}catch(e){setError(e.message);}}}>{t('story.cancelTask')}</button>
    {error&&<p role="alert">{error}</p>}
    {opened&&gate&&<ProposalRaceView gate={gate} onClose={()=>setOpened(false)} onSelect={async body=>{await api.post(`/projects/api/${slug}/orchestration/gates/${gate.gate_id}/resolve`,body);setGate(null);await onChanged?.();}}/>}
  </section>;
}
