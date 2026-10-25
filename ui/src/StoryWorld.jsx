import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocale } from './i18n/react.jsx';
import { t } from './i18n/index.js';
import { storyList, storyRequest, storyUpload, waitStoryTask, IMAGE_TYPES, MAX_IMAGE_BYTES } from './storyModel.js';
import { sourceDraft, editStoryScreenplay, needsStoryAdaptation, adaptStoryDraft, buildStoryFromDraft, storyComposition, choiceContrast,
  missingAssetSheets, assetGroupActive, rememberAssetGroup, restoredAssetGroup } from './storyImport.js';
import { CompositionPanel, CompositionReport, AssetGenerationState } from './StoryWorkbenchModals.jsx';
import { ScriptOutline } from './ScriptOutline.jsx';
import { WorldWall, WorldFacets, WorldList, WorldSummary } from './WorldWall.jsx';
import { AssetEditor } from './AssetEditor.jsx';
import { UNSCENED, activeItem, rememberGenerations, rememberWorld, restoredGenerations, restoredWorld, sceneFilter, worldCounts, worldFacets, worldGroups, worldItems } from './worldModel.js';
import { FALLBACK_APP, activeTasks, isActiveRun, restoredRuns, runRefused, runStarted, settleRun, startRun } from './generation/generationModel.js';
import { BreakdownDialog } from './BreakdownDialog.jsx';
import { BREAKDOWN_MODES, estimatesByMode } from './breakdownModel.js';
import { assetLookupFrom, codeBase, normalizeCode } from './bindingModel.js';
import { Icon } from './Icon.jsx';

const MODES = ['idea', 'novel', 'script'];
const focusedSceneOf = (shots, rid) => (rid && shots.find(shot => shot.rowId === rid)?.sceneId) || null;

// SPEC_15 Story & World: two views of one space. The script view holds the scenes, the source the agent grows into a script (SPEC_14
// lenses and collision cards on the page, not behind Ctrl K) and the script's outline; the Cast & sets view holds the people, places and
// props that script names, as a wall. Nothing opens by itself: the card you pick opens in a large editor pane (SPEC_18 R12) and x gives the
// wall the whole view back. One primary action: update the storyboard (R7: it asks its few questions in a dialog first). Pictures generate
// in the background (R1), several at once, while you carry on.
// intent: where the shell's space menu sent you ({view, facet}), taken once; onImportTable opens the sheet import for the shot table.
export function StoryWorld({epId, ep, shots = [], loadError = '', writable, focus = {}, intent = null, onFocus, onChanged, onStage, onOpenShot, onAssets, onVault, onIntentDone, onImportTable}) {
  useLocale();
  const [drafts, setDrafts] = useState(() => ({script:sourceDraft(), idea:sourceDraft(), novel:sourceDraft()}));
  const [sourceMode, setSourceMode] = useState('script'), [targetScenes, setTargetScenes] = useState(3), [breakdownMode, setBreakdownMode] = useState('auto');
  const [ratio, setRatio] = useState('16:9'), [style, setStyle] = useState('88123'), [styles, setStyles] = useState([]);
  const [comp, setComp] = useState({medium:'', genre:'general', collisions:null, unchecked:[], focus:'overall', extra:''});
  const [assets, setAssets] = useState([]), [assetsReady, setAssetsReady] = useState(false), [kind, setKind] = useState('all'), [detail, setDetail] = useState(null);
  const [remembered] = useState(() => restoredWorld(epId));
  const [view, setView] = useState(remembered.view), [pick, setPick] = useState(remembered.pick), [facet, setFacet] = useState('all'), [sceneSel, setSceneSel] = useState(remembered.scene);
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [loading, setLoading] = useState(true), [group, setGroup] = useState(null), [task, setTask] = useState(null);
  const [runs, setRuns] = useState(() => restoredRuns(restoredGenerations(epId))), [building, setBuilding] = useState(false), [target, setTarget] = useState(null), [estimate, setEstimate] = useState(null);
  const script = useRef(null), mounted = useRef(true), loadedFor = useRef(null), picked = useRef(false), openedFor = useRef(null), sentTo = useRef(epId);
  const inflight = useRef(new Set()), activeRef = useRef(''), intentSeen = useRef(null), changedRef = useRef(onChanged);
  changedRef.current = onChanged;
  const draft = drafts[sourceMode], isSource = sourceMode !== 'script';
  const disabled = busy || loading || !writable;
  const composition = storyComposition(comp);
  const needsAdaptation = needsStoryAdaptation(sourceMode, draft, targetScenes, isSource ? composition : null);
  const updateDraft = update => setDrafts(current => ({...current, [sourceMode]:{...current[sourceMode], ...update}}));
  useEffect(() => {mounted.current = true; return () => {mounted.current = false;};}, []);
  useEffect(() => rememberWorld(epId, {view, pick, scene:sceneSel}), [epId, view, pick, sceneSel]);
  // Another episode starts from what this tab remembers of it: its own pictures in flight, its own scene filter.
  useEffect(() => {
    if (sentTo.current === epId) return;
    sentTo.current = epId; inflight.current = new Set();
    setRuns(restoredRuns(restoredGenerations(epId))); setSceneSel(restoredWorld(epId).scene);
  }, [epId]);
  // What is in flight survives a reload (assetId -> taskId); finished or failed runs need nothing kept.
  const watching = JSON.stringify(activeTasks(runs));
  useEffect(() => rememberGenerations(epId, JSON.parse(watching)), [epId, watching]);
  // The shell's space menu can send you straight to a view and a filter ("2 missing images"); it is taken once.
  useEffect(() => {
    if (!intent || intent.space !== 'story' || intentSeen.current === intent.nonce) return;
    intentSeen.current = intent.nonce;
    if (intent.view) setView(intent.view);
    if (intent.facet) setFacet(intent.facet);
    if (intent.view === 'world') setSceneSel(null);  // "everything that is missing", not just this scene's
    onIntentDone?.();
  }, [intent]);  // eslint-disable-line react-hooks/exhaustive-deps
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
  // The crew's suggestions (SPEC_18 R11) follow what you hold: which view is open, and the card in front of you.
  useEffect(() => {onFocus?.({view});}, [view]);  // eslint-disable-line react-hooks/exhaustive-deps
  const items = useMemo(() => worldItems(assets, shots), [assets, shots]);
  // SPEC_18 R5: the wall can be narrowed to one scene's assets; the type and needs-image filters work inside that.
  const sceneNow = sceneSel === UNSCENED || (sceneSel && (ep?.scenes || []).some(scene => scene.sceneId === sceneSel)) ? sceneSel : null;
  const scoped = useMemo(() => sceneFilter(items, sceneNow), [items, sceneNow]);
  const facetNow = facet === 'missing' && !scoped.some(item => item.needsImage) ? 'all' : facet;  // nothing left to fix: back to everything
  const groups = worldGroups(scoped, facetNow);
  const active = view === 'world' ? activeItem(groups, pick) : null, activeId = active?.assetId || '';
  activeRef.current = activeId;
  useEffect(() => {
    if (view !== 'world' || !active) return;
    openedFor.current = active.assetCode;  // already here: the shell's "land on this card" must not take it as news
    onFocus?.({assetCode:active.assetCode, assetName:active.name || active.assetCode});
  }, [view, activeId]);  // eslint-disable-line react-hooks/exhaustive-deps
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

  // SPEC_18 R13: while the build dialog is open, the server counts the shots each way of splitting would give for the script as it is on
  // screen (saved or not). It only counts: nothing is written. A failed count never blocks the build; the dialog just says it could not.
  useEffect(() => {
    if (!building || !draft.script.trim()) {setEstimate(null); return undefined;}
    let alive = true;
    setEstimate({status:'loading'});
    const timer = setTimeout(() => {
      storyRequest(`/episodes/${epId}/storyboard-estimates`, 'POST', {breakdownModes:BREAKDOWN_MODES, scriptContent:draft.script})
        .then(result => {if (alive) setEstimate({status:'ready', modes:estimatesByMode(result)});})
        .catch(() => {if (alive) setEstimate({status:'error'});});
    }, 150);
    return () => {alive = false; clearTimeout(timer);};
  }, [building, epId, draft.script]);  // eslint-disable-line react-hooks/exhaustive-deps

  // After a card's picture finishes, only that card (and the editor, if it is open on it) is read again; the shell's episode
  // follows so the shots that use it stop saying "missing". Nothing else on the page reloads or loses its place.
  const refreshCards = async ids => {
    const fresh = (await Promise.all(ids.map(id => storyRequest('/assets/' + id).catch(() => null)))).filter(Boolean);
    if (!mounted.current || !fresh.length) return;
    setAssets(list => list.map(item => fresh.find(next => next.assetId === item.assetId) || item));
    const shown = fresh.find(next => next.assetId === activeRef.current);
    if (shown) setDetail(shown);
    changedRef.current?.();  // the poll below outlives the render that started it, so it reaches the shell through a ref
  };
  // Running pictures are polled together, once a second, until each is done. A reload brings them back from sessionStorage and the first
  // poll says what became of them: a finished one is refreshed, never sent again.
  useEffect(() => {
    const tasks = JSON.parse(watching);
    if (!Object.keys(tasks).length) return undefined;
    let alive = true, timer;
    const tick = async () => {
      const answers = [];
      await Promise.all(Object.entries(tasks).map(async ([assetId, taskId]) => {
        try {
          const answer = await storyRequest('/tasks/' + taskId);
          if (alive) answers.push([assetId, answer]);
        } catch (err) {
          if (alive && err.status === 404) answers.push([assetId, {taskId, status:'FAILED', error:{message:err.message}}]);  // the server no longer knows it
        }
      }));
      if (!alive) return;
      if (answers.length) setRuns(current => answers.reduce((next, [assetId, answer]) => settleRun(next, assetId, answer), current));
      const done = answers.filter(([, answer]) => answer.status === 'SUCCEEDED').map(([assetId]) => assetId);
      if (done.length) await refreshCards(done);
      if (alive) timer = setTimeout(tick, 1000);
    };
    timer = setTimeout(tick, 600);
    return () => {alive = false; clearTimeout(timer);};
  }, [watching]);  // eslint-disable-line react-hooks/exhaustive-deps

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
  // The build asks its few questions in a dialog (SPEC_18 R7); confirming runs exactly the requests the old button ran, in the same order,
  // with the dialog's choices. Cancelling the dialog sends nothing.
  const build = (choice = {}) => run(async () => {
    await buildStoryFromDraft({epId, sourceMode, draft, targetScenes, breakdownMode:choice.breakdownMode ?? breakdownMode, composition:isSource ? composition : null,
      settings:{aspectRatio:choice.ratio ?? ratio, stylePresetId:choice.style ?? style},
      request:storyRequest, wait:follow, onPrepared:updateDraft, onDone:async () => {await onChanged?.(); onStage?.();}});
  });
  const confirmBuild = choice => {setBuilding(false); setBreakdownMode(choice.breakdownMode); setRatio(choice.ratio); setStyle(choice.style); return build(choice);};
  const importTable = () => {setBuilding(false); onImportTable?.();};
  const generateMissing = () => run(async () => {
    const pending = await storyRequest(`/episodes/${epId}/asset-image-generations`, 'POST', {appCode:'flux-soul-cast'});
    rememberAssetGroup(epId, pending); setGroup(pending);
  });
  // After any change to one asset: the list, its detail and the shell's episode (readiness of the shots that use it) catch up.
  const refreshAsset = async assetId => {await loadAssets(); setDetail(await storyRequest('/assets/' + assetId)); onChanged?.();};
  // One picture, in the background (SPEC_18 R1): the click is accepted at once, the card says "generating", and nothing else waits.
  // One task per card: a card in flight cannot be sent again, any other card can.
  // body is what the generation bar shows ({appCode, modelParams}); a retry from a card sends the default workflow, as before.
  const generate = (assetId, body = {appCode:FALLBACK_APP}) => {
    if (!writable || inflight.current.has(assetId) || isActiveRun(runs[assetId])) return;
    inflight.current.add(assetId); setError('');
    setRuns(current => startRun(current, assetId));
    storyRequest(`/assets/${assetId}/image-generations`, 'POST', body)
      .then(created => {
        if (!mounted.current) return;
        setRuns(current => settleRun(runStarted(current, assetId, created), assetId, created));
        if (created.status === 'SUCCEEDED') refreshCards([assetId]);
      })
      .catch(err => {if (mounted.current) setRuns(current => runRefused(current, assetId, err.message));})
      .finally(() => inflight.current.delete(assetId));
  };
  const cancelGeneration = assetId => {
    const current = runs[assetId];
    if (!current?.taskId) return;
    storyRequest(`/tasks/${current.taskId}/cancellations`, 'POST')
      .then(() => {if (mounted.current) setRuns(now => settleRun(now, assetId, {taskId:current.taskId, status:'CANCELED'}));})
      .catch(err => {if (mounted.current) setError(err.message);});
  };
  const saveAsset = (assetId, fields) => run(async () => {await storyRequest('/assets/' + assetId, 'PATCH', fields); await refreshAsset(assetId);});
  // SPEC_18 R12: looks are made, renamed and deleted beside the picture, through the variants API that was already there.
  const createLook = (assetId, fields) => run(async () => {await storyRequest(`/assets/${assetId}/variants`, 'POST', fields); await refreshAsset(assetId);});
  const renameLook = (assetId, variantId, name) => run(async () => {await storyRequest(`/assets/${assetId}/variants/${variantId}`, 'PATCH', {name}); await refreshAsset(assetId);});
  const deleteLook = (assetId, variantId) => run(async () => {await storyRequest(`/assets/${assetId}/variants/${variantId}`, 'DELETE'); await refreshAsset(assetId);});
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
  // x on the editor: the wall has the whole view back, and the crew no longer thinks you are holding a card.
  const closeEditor = () => {openedFor.current = null; setPick(''); onFocus?.({assetCode:null, assetName:null});};
  // An @code tag in the script outline opens its card; the code may name a look, then the asset it belongs to is the card.
  const assetLookup = useMemo(() => assetLookupFrom(assets), [assets]);
  const openCode = code => {
    const asset = assets.find(item => normalizeCode(item.assetCode) === code) || assets.find(item => codeBase(item.assetCode) === codeBase(code));
    if (asset) openAsset(asset);
  };
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
  const styleName = styles.find(item => item.stylePresetId === style)?.name, styleSample = styles.find(item => item.stylePresetId === style)?.sampleImage;
  const canGenerate = writable && !busy && !assetGroupActive(group) && !ep?.scriptDirty;
  const generateHint = ep?.scriptDirty ? t('world.confirmFirst') : undefined;
  const canBuild = !disabled && Boolean(draft.script.trim() || (isSource && draft.sourceText.trim()));
  // The scene filter's choices: everything, the scene picked, the scene in focus (the breadcrumb's) and what no shot places in a scene.
  const focusScene = scenes.find(scene => scene.sceneId === (focus.sceneId || focusedSceneOf(shots, focus.shotRid))) || null;
  const sceneChoices = [{key:null}];
  if (scenes.length) {
    for (const scene of [scenes.find(item => item.sceneId === sceneNow), focusScene]) {
      if (scene && !sceneChoices.some(choice => choice.key === scene.sceneId)) sceneChoices.push({key:scene.sceneId, label:t('shell.sceneCrumb', {index:String(scene.sceneIndex).padStart(2, '0'), title:scene.title})});
    }
    if (sceneNow === UNSCENED || items.some(item => !item.sceneIds.length)) sceneChoices.push({key:UNSCENED});
  }
  const notices = <>
    {loading && (!ep && loadError ? <p role="alert" className="canvas-error">{loadError}</p> : <p role="status">{t('story.importLoading')}</p>)}
    {busy && <p role="status">{t('story.working')}{task && <> · {task.taskId} <button type="button" className="quiet" onClick={() => storyRequest('/tasks/' + task.taskId + '/cancellations', 'POST').catch(err => setError(err.message))}>{t('story.cancelTask')}</button></>}</p>}
    {error && <p role="alert" className="canvas-error">{error}</p>}
  </>;

  return <div className={'studio-space story-world' + (active ? ' is-editing' : '')}>
    <nav className="space-list" aria-label={t(view === 'world' ? 'world.facets' : 'world.scenes')}>
      <div className="space-list-head">{view === 'world'
        ? <><b>{t('world.worldTitle')}</b><span className="num">{scoped.length}</span></>
        : <><b>{t('world.scenes')}</b><span className="num">{scenes.length}</span></>}</div>
      <div className="studio-segmented" role="group" aria-label={t('world.listView')}>
        <button type="button" aria-pressed={view === 'script'} onClick={() => setView('script')}>{t('world.byScene')}</button>
        <button type="button" aria-pressed={view === 'world'} onClick={() => setView('world')}>{t('world.assetWall')}</button>
      </div>
      {view === 'world' ? <WorldFacets facets={worldFacets(scoped)} facet={facetNow} onFacet={setFacet}/>
        : <ol className="space-items">{scenes.map(scene => <li key={scene.sceneId}><button type="button" aria-current={(focus.sceneId || focusedSceneOf(shots, focus.shotRid)) === scene.sceneId ? 'true' : undefined} onClick={() => jump(scene)}>
          <b className="num">{String(scene.sceneIndex).padStart(2, '0')}</b><span>{scene.title}</span>
          <small>{t('shell.shotCount', {count:shotsByScene.get(scene.sceneId) || 0})}</small></button></li>)}
          {!scenes.length && <li className="space-empty">{t('world.noScenes')}</li>}
        </ol>}
      {writable
        ? <button type="button" className="space-foot world-format-btn" title={t('world.format')} aria-label={t('world.format') + ': ' + [ratio, styleName].filter(Boolean).join(' · ')} onClick={() => setBuilding(true)}>
          {styleSample && <img className="world-format-thumb" src={styleSample} alt="" loading="lazy"/>}
          <span>{[ratio, styleName].filter(Boolean).join(' · ')}</span><Icon name="arrowRight" size={13}/></button>
        : <p className="space-foot">{[ratio, styleName].filter(Boolean).join(' · ')}</p>}
    </nav>

    <main className="space-main">
      {view === 'world' ? <>
        <WorldWall groups={groups} counts={worldCounts(scoped)} total={scoped.length} filtered={sceneNow !== null} activeId={activeId} ready={assetsReady} writable={writable} disabled={busy}
          missingCount={missing.length} canGenerate={canGenerate} generateHint={generateHint} generation={<AssetGenerationState group={group}/>}
          runs={runs} sceneChoices={sceneChoices} scene={sceneNow} onScene={setSceneSel} onCancel={cancelGeneration} onRetry={generate}
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
          focusRid={focus.shotRid} lookup={assetLookup} onFocus={onFocus} onOpen={onOpenShot} onLine={jumpLine} onOpenAsset={openCode}/>}
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
        ? <AssetEditor key={active.assetId} item={active} detail={detail?.assetId === active.assetId ? detail : null} scenes={scenes} writable={writable} busy={busy} run={runs[active.assetId] || null} ratio={ratio} styleName={styleName}
            onSave={saveAsset} onClose={closeEditor} onUpload={uploadAsset} onGenerate={generate} onCancel={cancelGeneration} onLookCreate={createLook} onLookRename={renameLook} onLookDelete={deleteLook} onOpenShot={onOpenShot} onOpenScene={openScene} onTable={onAssets} onVault={onVault}/>
        : <WorldSummary withImages={items.filter(item => !item.needsImage).length} total={items.length}/>)
      : <>
        <WorldList items={items} kind={kind} onKind={setKind} focusCode={focus.assetCode} onOpen={openAsset}/>
        {missing.length > 0 && <button type="button" disabled={!writable || busy || assetGroupActive(group) || ep?.scriptDirty} onClick={generateMissing}
          title={ep?.scriptDirty ? t('world.confirmFirst') : undefined}>{t('story.generateMissingAssets')} ({missing.length})</button>}
        <AssetGenerationState group={group}/></>}
      </div>
      <button type="button" className="primary studio-primary" disabled={!canBuild} onClick={() => setBuilding(true)}>
        {shots.length ? t('world.updateStoryboard') : t('story.confirmAndBuild')}</button>
    </aside>
    {building && <BreakdownDialog value={{breakdownMode, ratio, style}} styles={styles} rebuild={shots.length > 0} shots={shots.length} confirmDisabled={!canBuild}
      estimate={estimate} target={target} onTarget={setTarget}
      onImport={onImportTable ? importTable : undefined} onConfirm={confirmBuild} onCancel={() => setBuilding(false)}/>}
  </div>;
}
