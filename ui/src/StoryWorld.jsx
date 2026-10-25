import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocale } from './i18n/react.jsx';
import { t } from './i18n/index.js';
import { storyList, storyRequest, storyUpload, waitStoryTask, IMAGE_TYPES, MAX_IMAGE_BYTES } from './storyModel.js';
import { sourceDraft, editStoryScreenplay, needsStoryAdaptation, adaptStoryDraft, buildStoryFromDraft, storyComposition, choiceContrast,
  missingAssetSheets, assetGroupActive, rememberAssetGroup, restoredAssetGroup } from './storyImport.js';
import { CompositionPanel, CompositionReport, AssetGenerationState } from './StoryWorkbenchModals.jsx';
import { ScriptOutline } from './ScriptOutline.jsx';
import { WorldWall, WorldFacets, WorldList, AssetInspector, WorldSummary } from './WorldWall.jsx';
import { activeItem, rememberWorld, restoredWorld, worldCounts, worldFacets, worldGroups, worldItems } from './worldModel.js';
import { Icon } from './Icon.jsx';

const MODES = ['idea', 'novel', 'script'];
const focusedSceneOf = (shots, rid) => (rid && shots.find(shot => shot.rowId === rid)?.sceneId) || null;

// SPEC_15 Story & World: two views of one space. The script view holds the scenes, the source the agent grows into a script (SPEC_14
// lenses and collision cards on the page, not behind Ctrl K) and the script's outline; the Cast & sets view holds the people, places and
// props that script names, as a wall with an inspector. One amber action: update the storyboard.
export function StoryWorld({epId, ep, shots = [], loadError = '', writable, focus = {}, onFocus, onChanged, onStage, onOpenShot, onAssets, onVault}) {
  useLocale();
  const [drafts, setDrafts] = useState(() => ({script:sourceDraft(), idea:sourceDraft(), novel:sourceDraft()}));
  const [sourceMode, setSourceMode] = useState('script'), [targetScenes, setTargetScenes] = useState(3), [breakdownMode, setBreakdownMode] = useState('auto');
  const [ratio, setRatio] = useState('16:9'), [style, setStyle] = useState('88123'), [styles, setStyles] = useState([]);
  const [comp, setComp] = useState({medium:'', genre:'general', collisions:null, unchecked:[], focus:'overall', extra:''});
  const [assets, setAssets] = useState([]), [assetsReady, setAssetsReady] = useState(false), [kind, setKind] = useState('all'), [detail, setDetail] = useState(null);
  const [remembered] = useState(() => restoredWorld(epId));
  const [view, setView] = useState(remembered.view), [pick, setPick] = useState(remembered.pick), [facet, setFacet] = useState('all');
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [loading, setLoading] = useState(true), [group, setGroup] = useState(null), [task, setTask] = useState(null);
  const script = useRef(null), mounted = useRef(true), loadedFor = useRef(null), picked = useRef(false), openedFor = useRef(null);
  const draft = drafts[sourceMode], isSource = sourceMode !== 'script';
  const disabled = busy || loading || !writable;
  const composition = storyComposition(comp);
  const needsAdaptation = needsStoryAdaptation(sourceMode, draft, targetScenes, isSource ? composition : null);
  const updateDraft = update => setDrafts(current => ({...current, [sourceMode]:{...current[sourceMode], ...update}}));
  useEffect(() => {mounted.current = true; return () => {mounted.current = false;};}, []);
  useEffect(() => rememberWorld(epId, {view, pick}), [epId, view, pick]);
  // The screenplay, settings and styles load once per episode; later saves refresh the episode without wiping drafts.
  useEffect(() => {
    if (!ep || loadedFor.current === epId) return;
    loadedFor.current = epId; setLoading(true); setError('');
    setDrafts({script:sourceDraft(ep.scriptContent || ''), idea:sourceDraft(), novel:sourceDraft()});
    if (!picked.current) setSourceMode(ep.scriptContent?.trim() ? 'script' : 'idea');  // a choice made while loading stands
    setRatio(ep.settings?.aspectRatio || '16:9'); setStyle(ep.settings?.stylePresetId || '88123');
    setBreakdownMode(['auto','scene','cinematic'].includes(ep.settings?.breakdownMode) ? ep.settings.breakdownMode : 'auto');
    setGroup(restoredAssetGroup(epId));
    storyList('/catalog/styles').then(items => {if (mounted.current) setStyles(items);}).catch(err => {if (mounted.current) setError(err.message);})
      .finally(() => {if (mounted.current) setLoading(false);});
  }, [ep, epId]);
  const loadAssets = () => storyList(`/episodes/${epId}/assets`).then(items => {if (mounted.current) {setAssets(items); setAssetsReady(true);}});
  useEffect(() => {loadAssets().catch(err => setError(err.message));}, [epId, ep]);  // eslint-disable-line react-hooks/exhaustive-deps
  // The shell's focus lands here: "Add references" on the Shot Stage arrives with an asset code and opens that card on the wall once; with
  // no focus yet, the first scene is the focus so every space's breadcrumb has a place to start.
  useEffect(() => {
    const code = focus.assetCode?.split(':')[0];
    if (!code || openedFor.current === focus.assetCode) return;
    const asset = assets.find(item => item.assetCode.split(':')[0] === code);
    if (!asset) return;
    openedFor.current = focus.assetCode; setView('world'); setFacet('all'); setPick(asset.assetId);
    requestAnimationFrame(() => document.getElementById('world-card-' + asset.assetId)?.scrollIntoView({block:'nearest'}));
  }, [focus.assetCode, assets]);
  useEffect(() => {
    if (!focus.sceneId && !focus.shotRid && ep?.scenes?.[0]) onFocus?.({sceneId:ep.scenes[0].sceneId});
  }, [ep?.scenes, focus.sceneId, focus.shotRid]);  // eslint-disable-line react-hooks/exhaustive-deps
  const items = useMemo(() => worldItems(assets, shots), [assets, shots]);
  const facetNow = facet === 'missing' && !items.some(item => item.needsImage) ? 'all' : facet;  // nothing left to fix: back to everything
  const groups = worldGroups(items, facetNow);
  const active = view === 'world' ? activeItem(groups, pick) : null, activeId = active?.assetId || '';
  useEffect(() => {
    let alive = true; setDetail(null);
    if (activeId) storyRequest('/assets/' + activeId).then(item => {if (alive) setDetail(item);}).catch(err => {if (alive) setError(err.message);});
    return () => {alive = false;};
  }, [activeId]);
  // Missing reference sheets generate as one task group; polling survives a reload through sessionStorage.
  useEffect(() => {
    if (!group?.taskGroupId || !assetGroupActive(group)) return undefined;
    let alive = true, timer;
    const poll = async () => {
      try {
        const next = await storyRequest('/task-groups/' + group.taskGroupId);
        if (!alive) return;
        rememberAssetGroup(epId, next); setGroup(current => ({...current, ...next}));
        if (assetGroupActive(next)) timer = setTimeout(poll, 1500); else {await loadAssets(); onChanged?.();}
      } catch (err) {if (alive) setError(err.message);}
    };
    timer = setTimeout(poll, 800);
    return () => {alive = false; clearTimeout(timer);};
  }, [group?.taskGroupId]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Resolves true when the action went through, so a form can close itself only then.
  const run = async action => {
    if (busy) return false;
    setBusy(true); setError('');
    try {await action(); return true;} catch (err) {if (mounted.current) setError(err.message); return false;} finally {if (mounted.current) setBusy(false);}
  };
  const changeComposition = patch => {
    if (patch.medium === 'manju') setRatio('9:16');  // micro-drama is vertical by convention
    setComp(current => ({...current, ...patch}));
  };
  const collide = () => run(async () => {
    const result = await storyRequest(`/episodes/${epId}/story-collisions`, 'POST', {sourceText:draft.sourceText, mediumLens:comp.medium, genreLens:comp.genre});
    setComp(current => ({...current, collisions:result, unchecked:[]}));
  });
  const settings = {aspectRatio:ratio, stylePresetId:style};
  const adapt = () => run(async () => {
    await storyRequest(`/episodes/${epId}/settings`, 'PUT', {...settings, breakdownMode});
    updateDraft(await adaptStoryDraft({epId, sourceMode, draft, targetScenes, breakdownMode, composition, request:storyRequest}));
    onChanged?.();
  });
  // Extraction and storyboard tasks show their id and can be canceled, as the old script bar allowed.
  const follow = async pending => {setTask(pending); try {return await waitStoryTask(pending, {onProgress:setTask});} finally {if (mounted.current) setTask(null);}};
  const build = () => run(async () => {
    await buildStoryFromDraft({epId, sourceMode, draft, targetScenes, breakdownMode, composition:isSource ? composition : null, settings,
      request:storyRequest, wait:follow, onPrepared:updateDraft, onDone:async () => {await onChanged?.(); onStage?.();}});
  });
  const generateMissing = () => run(async () => {
    const pending = await storyRequest(`/episodes/${epId}/asset-image-generations`, 'POST', {appCode:'flux-soul-cast'});
    rememberAssetGroup(epId, pending); setGroup(pending);
  });
  // After any change to one asset: the list, its detail and the shell's episode (readiness of the shots that use it) catch up.
  const refreshAsset = async assetId => {await loadAssets(); setDetail(await storyRequest('/assets/' + assetId)); onChanged?.();};
  const generateOne = assetId => run(async () => {
    await waitStoryTask(await storyRequest(`/assets/${assetId}/image-generations`, 'POST', {appCode:'flux-soul-cast'}));
    await refreshAsset(assetId);
  });
  const saveAsset = (assetId, fields) => run(async () => {await storyRequest('/assets/' + assetId, 'PATCH', fields); await refreshAsset(assetId);});
  // An uploaded picture becomes a candidate of the asset and the selected reference in one go.
  const uploadAsset = (assetId, file) => run(async () => {
    if (!IMAGE_TYPES.includes(file.type)) throw new Error(t('world.imageType'));
    if (file.size > MAX_IMAGE_BYTES) throw new Error(t('world.imageSize'));
    const stored = await storyUpload(file, 'IMAGE');
    const candidate = await storyRequest(`/assets/${assetId}/images`, 'POST', {fileId:stored.fileId});
    await storyRequest(`/assets/${assetId}/selected-image`, 'PUT', {imageId:candidate.imageId});
    await refreshAsset(assetId);
  });
  const createAsset = (type, name, prompt) => run(async () => {
    const created = await storyRequest(`/episodes/${epId}/assets`, 'POST', {type, name, prompt});
    await loadAssets(); setFacet('all'); setPick(created.assetId); onChanged?.();
  });
  const openAsset = asset => {openedFor.current = asset.assetCode; setFacet('all'); setPick(asset.assetId); setView('world'); onFocus?.({assetCode:asset.assetCode});};
  // A scene in the list selects its heading in the screenplay.
  const jump = scene => {
    onFocus?.({sceneId:scene.sceneId, shotRid:null});  // a scene is the focus now; the Shot Stage picks the shot that needs you
    if (sourceMode !== 'script') setSourceMode('script');
    requestAnimationFrame(() => {
      const box = script.current, at = box ? box.value.indexOf(scene.title) : -1;
      if (!box) return;
      box.focus();
      if (at >= 0) {box.setSelectionRange(at, at + scene.title.length); box.scrollTop = Math.max(0, box.value.slice(0, at).split('\n').length - 2) * 22;}
    });
  };
  const openScene = scene => {setView('script'); jump(scene);};
  // A beat's line number selects that line in the screenplay.
  const jumpLine = line => requestAnimationFrame(() => {
    const box = script.current;
    if (!box || !line) return;
    const lines = box.value.split('\n'), start = lines.slice(0, line - 1).join('\n').length + (line > 1 ? 1 : 0);
    box.focus(); box.setSelectionRange(start, start + (lines[line - 1]?.length || 0)); box.scrollTop = Math.max(0, line - 3) * 22;
  });
  const scenes = ep?.scenes || [];
  const shotsByScene = useMemo(() => shots.reduce((map, shot) => map.set(shot.sceneId, (map.get(shot.sceneId) || 0) + 1), new Map()), [shots]);
  const missing = missingAssetSheets(ep);
  const recent = comp.collisions?.recentTraces || [];
  const contrast = comp.collisions ? choiceContrast(recent, comp.focus) : null;
  const struck = comp.collisions ? comp.unchecked.length : 0, kept = comp.collisions ? comp.collisions.candidates.length - struck : 0;
  const styleName = styles.find(item => item.stylePresetId === style)?.name;
  const canGenerate = writable && !busy && !assetGroupActive(group) && !ep?.scriptDirty;
  const generateHint = ep?.scriptDirty ? t('world.confirmFirst') : undefined;
  const notices = <>
    {loading && (!ep && loadError ? <p role="alert" className="canvas-error">{loadError}</p> : <p role="status">{t('story.importLoading')}</p>)}
    {busy && <p role="status">{t('story.working')}{task && <> · {task.taskId} <button type="button" className="quiet" onClick={() => storyRequest('/tasks/' + task.taskId + '/cancellations', 'POST').catch(err => setError(err.message))}>{t('story.cancelTask')}</button></>}</p>}
    {error && <p role="alert" className="canvas-error">{error}</p>}
  </>;

  return <div className="studio-space story-world">
    <nav className="space-list" aria-label={t(view === 'world' ? 'world.facets' : 'world.scenes')}>
      <div className="space-list-head">{view === 'world'
        ? <><b>{t('world.worldTitle')}</b><span className="num">{items.length}</span></>
        : <><b>{t('world.scenes')}</b><span className="num">{scenes.length}</span></>}</div>
      <div className="studio-segmented" role="group" aria-label={t('world.listView')}>
        <button type="button" aria-pressed={view === 'script'} onClick={() => setView('script')}>{t('world.byScene')}</button>
        <button type="button" aria-pressed={view === 'world'} onClick={() => setView('world')}>{t('world.assetWall')}</button>
      </div>
      {view === 'world' ? <WorldFacets facets={worldFacets(items)} facet={facetNow} onFacet={setFacet}/>
        : <ol className="space-items">{scenes.map(scene => <li key={scene.sceneId}><button type="button" aria-current={(focus.sceneId || focusedSceneOf(shots, focus.shotRid)) === scene.sceneId ? 'true' : undefined} onClick={() => jump(scene)}>
          <b className="num">{String(scene.sceneIndex).padStart(2, '0')}</b><span>{scene.title}</span>
          <small>{t('shell.shotCount', {count:shotsByScene.get(scene.sceneId) || 0})}</small></button></li>)}
          {!scenes.length && <li className="space-empty">{t('world.noScenes')}</li>}
        </ol>}
      <p className="space-foot">{[ratio, styleName].filter(Boolean).join(' · ')}</p>
    </nav>

    <main className="space-main">
      {view === 'world' ? <>
        <WorldWall groups={groups} counts={worldCounts(items)} total={items.length} activeId={activeId} ready={assetsReady} writable={writable} disabled={busy}
          missingCount={missing.length} canGenerate={canGenerate} generateHint={generateHint} generation={<AssetGenerationState group={group}/>}
          onPick={setPick} onCreate={createAsset} onGenerateMissing={generateMissing} onTable={onAssets}/>
        {notices}
      </> : <>
      <header className="space-head">
        <h1>{t('world.story')}</h1>
        <span className="space-sub">{t('story.sourceMode')}</span>
        <span className="spacer"/>
        <div className="studio-segmented" role="group" aria-label={t('story.sourceMode')}>
          {MODES.map(mode => <button key={mode} type="button" aria-pressed={sourceMode === mode} disabled={busy} onClick={() => {picked.current = true; setSourceMode(mode); setError('');}}>{t('story.sourceMode_' + mode)}</button>)}
        </div>
      </header>
      {isSource ? <>
        <section className="space-block" aria-labelledby="world-source">
          <h2 id="world-source"><span className="num">1</span>{t('world.ideaAndLens')}</h2>
          <label className="modal-field">{t('story.sourceText')}<textarea rows={4} value={draft.sourceText} maxLength={500000} disabled={disabled} placeholder={t('world.sourceHint')} onChange={e => updateDraft({sourceText:e.target.value})}/></label>
          <CompositionPanel value={comp} disabled={disabled} onChange={changeComposition} onCollide={draft.sourceText.trim() ? collide : null}/>
          <label className="modal-field space-inline">{t('story.targetScenes')}<input type="number" min={1} max={12} step={1} value={targetScenes} disabled={disabled} onChange={e => setTargetScenes(Math.max(1, Math.min(12, Math.trunc(Number(e.target.value)) || 1)))}/></label>
          {contrast?.contrastDetected && <p className="story-contrast" role="status">{t('world.contrastAhead', {from:t('story.focus_' + contrast.dominantFocus), to:t('story.focus_' + comp.focus)})}</p>}
          {!!comp.collisions?.candidates?.[0]?.propSlice?.length && <p className="story-slices">{t('world.propSlices')}<span>{comp.collisions.candidates[0].propSlice.join(' → ')}</span></p>}
        </section>
        <section className="space-block" aria-labelledby="world-beats">
          <h2 id="world-beats"><span className="num">2</span>{t('world.beats')}<span className="spacer"/>
            <button type="button" disabled={disabled || !draft.sourceText.trim() || !needsAdaptation} onClick={adapt}>{t('story.adaptScript')}</button></h2>
          <CompositionReport report={draft.report}/>
          <label className="modal-field">{t('story.script')}<textarea rows={12} value={draft.script} maxLength={500000} disabled={disabled} onChange={e => updateDraft(editStoryScreenplay(sourceMode, draft, e.target.value, targetScenes, composition))}/></label>
          <p className="space-sub">{t(needsAdaptation && draft.adaptationKey ? 'story.sourceChangedHelp' : 'story.screenplayEditHelp')}</p>
        </section>
      </> : <>
        {comp.medium && <button type="button" className="story-summary" onClick={() => setSourceMode(drafts.novel.sourceText.trim() ? 'novel' : 'idea')}>
          {[t('story.mediumLens_' + comp.medium), t('story.genreLens_' + comp.genre), comp.collisions && t('world.keptStruck', {kept, struck})].filter(Boolean).join(' · ')}
          <span>{t('world.adjust')}</span></button>}
        {ep?.scriptDirty && <p className="story-dirty" role="status">{t('story.scriptDirty')}</p>}
        <label className="modal-field space-script">{t('story.script')}<textarea ref={script} rows={22} value={draft.script} maxLength={500000} disabled={disabled} onChange={e => updateDraft(editStoryScreenplay(sourceMode, draft, e.target.value, targetScenes))}/></label>
        {shots.length > 0 && ep && <ScriptOutline epId={epId} script={draft.script} saved={ep.scriptContent || ''} version={(ep.confirmedHash || '') + ':' + shots.length}
          focusRid={focus.shotRid} onFocus={onFocus} onOpen={onOpenShot} onLine={jumpLine}/>}
      </>}
      <label className="space-upload"><Icon name="arrowUp"/>{t('story.uploadScript')}<input type="file" accept=".txt,.md,text/plain,text/markdown" disabled={disabled} onChange={async e => {
        const file = e.target.files?.[0]; e.target.value = ''; if (!file) return;
        if (!/\.(txt|md)$/i.test(file.name)) {setError(t('story.scriptFileType')); return;}
        if (file.size > 2000000) {setError(t('story.scriptTooLarge')); return;}
        const text = await file.text();
        if (text.length > 500000) {setError(t('story.scriptTextTooLong')); return;}
        updateDraft(isSource ? {sourceText:text} : {script:text}); setError('');
      }}/></label>
      {notices}
      </>}
    </main>

    <aside className="space-detail" aria-label={t('world.world')}>
      <div className="space-detail-body">
      {view === 'world' ? (active
        ? <AssetInspector key={active.assetId} item={active} detail={detail?.assetId === active.assetId ? detail : null} scenes={scenes} writable={writable} busy={busy}
            onSave={saveAsset} onUpload={uploadAsset} onGenerate={generateOne} onOpenShot={onOpenShot} onOpenScene={openScene} onTable={onAssets} onVault={onVault}/>
        : <WorldSummary withImages={items.filter(item => !item.needsImage).length} total={items.length}/>)
      : <>
        <WorldList items={items} kind={kind} onKind={setKind} focusCode={focus.assetCode} onOpen={openAsset}/>
        {missing.length > 0 && <button type="button" disabled={!writable || busy || assetGroupActive(group) || ep?.scriptDirty} onClick={generateMissing}
          title={ep?.scriptDirty ? t('world.confirmFirst') : undefined}>{t('story.generateMissingAssets')} ({missing.length})</button>}
        <AssetGenerationState group={group}/>
        <fieldset className="world-breakdown"><legend>{t('story.breakdownMode')}</legend>
          {['auto','scene','cinematic'].map(mode => <label key={mode}><input type="radio" name="breakdown" value={mode} checked={breakdownMode === mode} disabled={disabled} onChange={() => setBreakdownMode(mode)}/>{t('story.breakdownMode_' + mode)}</label>)}
        </fieldset>
        <details className="world-format"><summary>{t('world.format')}</summary>
          <label className="modal-field">{t('story.aspectRatio')}<select value={ratio} disabled={disabled} onChange={e => setRatio(e.target.value)}>{['16:9','9:16','1:1','21:9'].map(r => <option key={r}>{r}</option>)}</select></label>
          <label className="modal-field">{t('story.style')}<select value={style} disabled={disabled} onChange={e => setStyle(e.target.value)}>{styles.map(s => <option key={s.stylePresetId} value={s.stylePresetId}>{s.name}</option>)}</select></label>
        </details></>}
      </div>
      <button type="button" className="primary studio-primary" disabled={disabled || !(draft.script.trim() || (isSource && draft.sourceText.trim()))} onClick={build}>
        {shots.length ? t('world.updateStoryboard') : t('story.confirmAndBuild')}</button>
    </aside>
  </div>;
}
