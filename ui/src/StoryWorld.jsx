import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useLocale } from './i18n/react.jsx';
import { t } from './i18n/index.js';
import { api, ApiError } from './api.js';
import { storyList, storyRequest, storyUpload, waitStoryTask, IMAGE_TYPES, MAX_IMAGE_BYTES } from './storyModel.js';
import { missingAssetSheets, assetGroupActive, rememberAssetGroup, restoredAssetGroup } from './storyImport.js';
import { AssetGenerationState } from './StoryWorkbenchModals.jsx';
import { WorldWall, WorldFacets, WorldList, WorldSummary } from './WorldWall.jsx';
import { AssetEditor } from './AssetEditor.jsx';
import { UNSCENED, activeItem, rememberGenerations, rememberWorld, restoredGenerations, restoredWorld, sceneFilter, worldCounts, worldFacets, worldGroups, worldItems } from './worldModel.js';
import { FALLBACK_APP, activeTasks, isActiveRun, restoredRuns, runRefused, runStarted, settleRun, startRun } from './generation/generationModel.js';
import { BreakdownDialog } from './BreakdownDialog.jsx';
import { BREAKDOWN_MODES, estimatesByMode } from './breakdownModel.js';
import { buildStoryFromWorkspace, primaryStoryAction, startHandOff } from './storyHostModel.js';
import { takeStart } from './startModel.js';
import { AuthoringWorkspace } from './writing/AuthoringWorkspace.jsx';
import { WritingToolsPanel } from './writing/WritingToolsPanel.jsx';
import { createActorBoundRequest } from './writing/writingTransport.js';
import { Icon } from './Icon.jsx';

const focusedSceneOf = (shots, rid) => (rid && shots.find(shot => shot.rowId === rid)?.sceneId) || null;
const renderTools = props => <WritingToolsPanel {...props}/>;

// SPEC_15 Story & World: two views of one space. The script view is the writing workspace (SPEC_16, hosted here by SPEC_16A): the stable
// outline of the screenplay in the left rail, the manuscript in the middle, and its panels (versions, story impact, preview, world and
// search and files) in the right column; the Cast & sets view holds the people, places and props that script names, as a wall. Nothing
// opens by itself: the card you pick opens in a large editor pane (SPEC_18 R12) and x gives the wall the whole view back. One primary
// action, which follows what you are looking at: update the storyboard (R7: it asks its few questions in a dialog first), or preview an
// adaptation. Pictures generate in the background (R1), several at once, while you carry on.
// intent: where the shell's space menu sent you ({view, facet}), taken once; onImportTable opens the sheet import for the shot table.
// controlRef/onStatus/focusSource/onIdentityLost are the writing workspace's contract with the shell (save boundary, status chip, jump from
// a shot back to its source, sign-in lost); me is whoever is signed in, fixed for the life of the workspace.
export function StoryWorld({slug = '', epId, me, ep, shots = [], loadError = '', writable, focus = {}, intent = null, controlRef, focusSource = null, onFocus, onStatus, onIdentityLost,
  onChanged, onStage, onOpenShot, onAssets, onVault, onIntentDone, onImportTable}) {
  useLocale();
  const [breakdownMode, setBreakdownMode] = useState('auto');
  const [ratio, setRatio] = useState('16:9'), [style, setStyle] = useState('88123'), [styles, setStyles] = useState([]);
  const [assets, setAssets] = useState([]), [assetsReady, setAssetsReady] = useState(false), [kind, setKind] = useState('all'), [detail, setDetail] = useState(null);
  const [remembered] = useState(() => restoredWorld(epId));
  const [view, setView] = useState(remembered.view), [pick, setPick] = useState(remembered.pick), [facet, setFacet] = useState('all'), [sceneSel, setSceneSel] = useState(remembered.scene);
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [loading, setLoading] = useState(true), [group, setGroup] = useState(null), [task, setTask] = useState(null);
  const [runs, setRuns] = useState(() => restoredRuns(restoredGenerations(epId))), [building, setBuilding] = useState(false), [target, setTarget] = useState(null), [estimate, setEstimate] = useState(null);
  // The writing workspace: what it reports (which manuscript, its text, whether a panel is open), a jump asked from this page's rail, and the two
  // columns of the shell it renders into.
  const [ready, setReady] = useState(false), [seed, setSeed] = useState(null);
  const [scriptStatus, setScriptStatus] = useState(null), [railFocus, setRailFocus] = useState(null), [leftSlot, setLeftSlot] = useState(null), [rightSlot, setRightSlot] = useState(null);
  const localControl = useRef(null), control = controlRef || localControl;
  const mounted = useRef(true), loadedFor = useRef(null), openedFor = useRef(null), sentTo = useRef(epId);
  const inflight = useRef(new Set()), activeRef = useRef(''), intentSeen = useRef(null), changedRef = useRef(onChanged), focusRef = useRef(focus);
  changedRef.current = onChanged; focusRef.current = focus;
  const disabled = busy || loading || !writable;
  const slots = useMemo(() => ({left:leftSlot, right:rightSlot}), [leftSlot, rightSlot]);
  // Cookies can change in another tab: every request of the writing session carries who this workspace was opened for.
  const actorId = me?.actor_id || '';
  const request = useMemo(() => actorId ? createActorBoundRequest(actorId, async (path, method, body, options) => {
    const current = await api.get(`/projects/api/${slug}`);
    if (current.me.actor_id !== actorId) throw new ApiError(401, t('writing.integration.identityChanged'));
    // The preflight is only an early warning; the server binding closes its race.
    if (options.signal.aborted) throw new DOMException('Writing session disposed', 'AbortError');
    return storyRequest(path, method, body, options);
  }, onIdentityLost) : storyRequest, [slug, actorId, onIdentityLost]);
  useLayoutEffect(() => () => request.dispose?.(), [request]);
  const reportStatus = useCallback(status => {setScriptStatus(status); onStatus?.(status);}, [onStatus]);
  const pickedScene = useCallback(scene => {
    if (scene?.sceneId && scene.sceneId !== focusRef.current.sceneId) onFocus?.({sceneId:scene.sceneId, shotRid:null});  // the scene in the editor is the focus
  }, [onFocus]);
  useEffect(() => {mounted.current = true; return () => {mounted.current = false;};}, []);
  useEffect(() => rememberWorld(epId, {view, pick, scene:sceneSel}), [epId, view, pick, sceneSel]);
  // Leaving the script view unmounts the workspace; the shell's status chip must not keep what it last said.
  useEffect(() => {if (view !== 'script') {setScriptStatus(null); onStatus?.(null);}}, [view]);  // eslint-disable-line react-hooks/exhaustive-deps
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
  // The settings and styles load once per episode.
  useEffect(() => {
    if (!ep || loadedFor.current === epId) return;
    loadedFor.current = epId; setLoading(true); setError('');
    // A production started from a story (SPEC_18 R16) opens with the ratio and style chosen in the hub.
    const start = takeStart(epId);
    setRatio(start?.ratio || ep.settings?.aspectRatio || '16:9'); setStyle(start?.style || ep.settings?.stylePresetId || '88123');
    setBreakdownMode(['auto','scene','cinematic'].includes(ep.settings?.breakdownMode) ? ep.settings.breakdownMode : 'auto');
    // Its text goes to the workspace: a screenplay is saved into the working script first (the workspace then opens on it); an idea or a novel
    // opens as a private source with the text in it (SPEC_16A 3.5).
    const plan = startHandOff(start);
    if (plan.kind === 'working') {
      storyRequest(`/episodes/${epId}/script`, 'PUT', {scriptContent:plan.text}).then(() => onChanged?.()).catch(err => {if (mounted.current) setError(err.message);})
        .finally(() => {if (mounted.current) setReady(true);});
    } else {setSeed(plan.kind === 'source' ? plan : null); setReady(true);}
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
    if (!activeId || !window.matchMedia?.('(max-width: 1100px)').matches) return;
    requestAnimationFrame(() => document.querySelector('.world-editor')?.scrollIntoView({block:'start'}));
  }, [activeId]);
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

  // SPEC_18 R13: while the build dialog is open, the server counts the shots each way of splitting would give for the script it holds. The
  // dialog only opens once the workspace has saved to the server, so that is the script on screen. It only counts: nothing is written. A
  // failed count never blocks the build; the dialog just says it could not.
  useEffect(() => {
    if (!building) {setEstimate(null); return undefined;}
    let alive = true;
    setEstimate({status:'loading'});
    const timer = setTimeout(() => {
      storyRequest(`/episodes/${epId}/storyboard-estimates`, 'POST', {breakdownModes:BREAKDOWN_MODES})
        .then(result => {if (alive) setEstimate({status:'ready', modes:estimatesByMode(result)});})
        .catch(() => {if (alive) setEstimate({status:'error'});});
    }, 150);
    return () => {alive = false; clearTimeout(timer);};
  }, [building, epId]);

  // After a card's picture finishes, only that card (and the editor, if it is open on it) is read again; the shell's episode
  // follows so the shots that use it stop saying "missing". Nothing else on the page reloads or loses its place.
  const refreshCards = async ids => {
    const fresh = (await Promise.all(ids.map(id => storyRequest('/assets/' + id).catch(() => null)))).filter(Boolean);
    if (!mounted.current || !fresh.length) return;
    setAssets(list => list.map(item => fresh.find(next => next.assetId === item.assetId) || item));
    const shown = fresh.find(next => next.assetId === activeRef.current);
    if (shown) setDetail(shown);
    else if (fresh.some(next => next.isDefault === false) && activeRef.current) {  // a look finished: its card lists it, and counts its missing pictures
      await loadAssets(); const card = await storyRequest('/assets/' + activeRef.current).catch(() => null);
      if (mounted.current && card) setDetail(card);
    }
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
  // Extraction and storyboard tasks show their id and can be canceled, as the old script bar allowed.
  const follow = async pending => {setTask(pending); try {return await waitStoryTask(pending, {onProgress:setTask});} finally {if (mounted.current) setTask(null);}};
  // The build asks its few questions in a dialog (SPEC_18 R7), but only once the server holds what you wrote: the workspace saves first, and
  // if it cannot (a conflict, a lost sign-in) it says so itself and the dialog stays shut. Cancelling the dialog sends nothing.
  const holdsScript = async () => control.current ? control.current.flush({requireServer:true}) : true;
  const openBuild = async () => {if (await holdsScript()) setBuilding(true);};
  // Confirming runs the requests the old button ran, in the same order, with the dialog's choices, minus the script itself: the workspace owns it.
  const build = (choice = {}) => run(async () => {
    await buildStoryFromWorkspace({epId, breakdownMode:choice.breakdownMode ?? breakdownMode,
      settings:{aspectRatio:choice.ratio ?? ratio, stylePresetId:choice.style ?? style},
      request:storyRequest, wait:follow, flush:holdsScript, onDone:async () => {await onChanged?.(); onStage?.();}});
  });
  const confirmBuild = choice => {setBuilding(false); setBreakdownMode(choice.breakdownMode); setRatio(choice.ratio); setStyle(choice.style); return build(choice);};
  const importTable = () => {setBuilding(false); onImportTable?.();};
  const generateMissing = () => run(async () => {
    const pending = await storyRequest(`/episodes/${epId}/asset-image-generations`, 'POST', {appCode:'flux-soul-cast'});
    rememberAssetGroup(epId, pending); setGroup(pending);
  });
  // After any change to one asset: the list, its detail and the shell's episode (readiness of the shots that use it) catch up.
  // Whatever was just written (the card, one of its looks, a picture), the card that is open is read again with its looks.
  const refreshAsset = async () => {await loadAssets(); setDetail(await storyRequest('/assets/' + activeRef.current)); onChanged?.();};
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
  // Making another picture of a card or a look its main one.
  const selectImage = (assetId, imageId) => run(async () => {await storyRequest(`/assets/${assetId}/selected-image`, 'PUT', {imageId}); await refreshAsset();});
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
  // Leaving the writing workspace for the wall is leaving a space for a moment: what you wrote is saved first, or you stay and the workspace says why.
  const switchView = async next => {
    if (next === view) return;
    if (view === 'script' && !(await holdsScript())) return;
    setView(next);
  };
  // A scene is the focus now; the Shot Stage picks the shot that needs you. The workspace scrolls its manuscript to the scene.
  const focusScene = scene => {
    onFocus?.({sceneId:scene.sceneId, shotRid:null});
    setRailFocus({sceneId:scene.sceneId, nonce:Date.now()});
  };
  const openScene = async scene => {if (view !== 'script') await switchView('script'); focusScene(scene);};
  const jumpTo = railFocus && railFocus.nonce > (focusSource?.nonce || 0) ? railFocus : focusSource;
  const scenes = ep?.scenes || [];
  const shotsByScene = useMemo(() => shots.reduce((map, shot) => map.set(shot.sceneId, (map.get(shot.sceneId) || 0) + 1), new Map()), [shots]);
  const missing = missingAssetSheets(ep);
  const styleName = styles.find(item => item.stylePresetId === style)?.name, styleSample = styles.find(item => item.stylePresetId === style)?.sampleImage;
  const canGenerate = writable && !busy && !assetGroupActive(group) && !ep?.scriptDirty;
  const generateHint = ep?.scriptDirty ? t('world.confirmFirst') : undefined;
  // What the one primary button does depends on what the workspace is showing (a working script, a private source, a saved version).
  const manuscript = view === 'script' ? scriptStatus?.manuscript || 'working' : 'working';
  const hasScript = Boolean((view === 'script' && scriptStatus?.characters > 0) || ep?.scriptContent?.trim());
  const primary = primaryStoryAction({manuscript, writable, hasScript, hasShots:shots.length > 0, busy, loading, canAdapt:Boolean(scriptStatus?.canAdapt)});
  const canBuild = primary.action === 'build' && !primary.disabled;
  const onPrimary = () => {if (primary.action === 'adapt') control.current?.previewAdaptation?.(); else if (primary.action === 'build') openBuild();};
  const showOutline = view === 'script' && scriptStatus?.manuscript === 'working', panelOpen = Boolean(scriptStatus?.panelOpen);
  // The scene filter's choices: everything, the scene picked, the scene in focus (the breadcrumb's) and what no shot places in a scene.
  const focusScene_ = scenes.find(scene => scene.sceneId === (focus.sceneId || focusedSceneOf(shots, focus.shotRid))) || null;
  const sceneChoices = [{key:null}];
  if (scenes.length) {
    for (const scene of [scenes.find(item => item.sceneId === sceneNow), focusScene_]) {
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
        <button type="button" aria-pressed={view === 'script'} onClick={() => switchView('script')}>{t('world.byScene')}</button>
        <button type="button" aria-pressed={view === 'world'} onClick={() => switchView('world')}>{t('world.assetWall')}</button>
      </div>
      {view === 'world' ? <WorldFacets facets={worldFacets(scoped)} facet={facetNow} onFacet={setFacet}/>
        : <>
          {/* The workspace puts its stable outline here while it shows the working script; otherwise the scenes the shots came from. */}
          <div className="story-outline-slot" ref={setLeftSlot} hidden={!showOutline}/>
          {!showOutline && <ol className="space-items">{scenes.map(scene => <li key={scene.sceneId}><button type="button" aria-current={(focus.sceneId || focusedSceneOf(shots, focus.shotRid)) === scene.sceneId ? 'true' : undefined} onClick={() => focusScene(scene)}>
            <b className="num">{String(scene.sceneIndex).padStart(2, '0')}</b><span>{scene.title}</span>
            <small>{t('shell.shotCount', {count:shotsByScene.get(scene.sceneId) || 0})}</small></button></li>)}
            {!scenes.length && <li className="space-empty">{t('world.noScenes')}</li>}
          </ol>}
        </>}
      {writable
        ? <button type="button" className="space-foot world-format-btn" title={t('world.format')} aria-label={t('world.format') + ': ' + [ratio, styleName].filter(Boolean).join(' · ')} onClick={openBuild}>
          {styleSample && <img className="world-format-thumb" src={styleSample} alt="" loading="lazy"/>}
          <span>{[ratio, styleName].filter(Boolean).join(' · ')}</span><Icon name="arrowRight" size={13}/></button>
        : <p className="space-foot">{[ratio, styleName].filter(Boolean).join(' · ')}</p>}
    </nav>

    <main className={'space-main' + (view === 'script' ? ' is-writing' : '')}>
      {view === 'world' ? <>
        <WorldWall groups={groups} counts={worldCounts(scoped)} total={scoped.length} filtered={sceneNow !== null} activeId={activeId} ready={assetsReady} writable={writable} disabled={busy}
          missingCount={missing.length} canGenerate={canGenerate} generateHint={generateHint} generation={<AssetGenerationState group={group}/>}
          runs={runs} sceneChoices={sceneChoices} scene={sceneNow} onScene={setSceneSel} onCancel={cancelGeneration} onRetry={generate}
          onPick={setPick} onCreate={createAsset} onGenerateMissing={generateMissing} onTable={onAssets}/>
        {notices}
      </> : <>
        {ready && <AuthoringWorkspace slug={slug} epId={epId} me={me} ep={ep} shots={shots} writable={writable} request={request} controlRef={control}
          onChanged={onChanged} onStage={onStage} onStatus={reportStatus} onScene={pickedScene} focusSource={jumpTo} renderTools={renderTools} slots={slots}
          seed={seed} onSeeded={() => setSeed(null)}/>}
        {notices}
      </>}
    </main>

    <aside className="space-detail" aria-label={t('world.world')}>
      <div className="space-detail-body">
      {view === 'world' ? (active
        ? <AssetEditor key={active.assetId} item={active} detail={detail?.assetId === active.assetId ? detail : null} scenes={scenes} writable={writable} busy={busy} runs={runs} ratio={ratio} styleName={styleName}
            onSave={saveAsset} onSelectImage={selectImage} onClose={closeEditor} onUpload={uploadAsset} onGenerate={generate} onCancel={cancelGeneration} onLookCreate={createLook} onLookRename={renameLook} onLookDelete={deleteLook} onOpenShot={onOpenShot} onOpenScene={openScene} onTable={onAssets} onVault={onVault}/>
        : <WorldSummary withImages={items.filter(item => !item.needsImage).length} total={items.length}/>)
      : <>
        {/* The workspace's panels (versions, story impact, preview, world and search and files) take this column while one is open. */}
        <div className="story-panel-slot" ref={setRightSlot} hidden={!panelOpen}/>
        {!panelOpen && <>
          <WorldList items={items} kind={kind} onKind={setKind} focusCode={focus.assetCode} onOpen={openAsset}/>
          {missing.length > 0 && <button type="button" disabled={!writable || busy || assetGroupActive(group) || ep?.scriptDirty} onClick={generateMissing}
            title={ep?.scriptDirty ? t('world.confirmFirst') : undefined}>{t('story.generateMissingAssets')} ({missing.length})</button>}
          <AssetGenerationState group={group}/></>}</>}
      </div>
      <button type="button" className="primary studio-primary" disabled={primary.disabled} title={primary.hintKey ? t(primary.hintKey) : undefined} onClick={onPrimary}>
        {t(primary.labelKey)}</button>
    </aside>
    {building && <BreakdownDialog value={{breakdownMode, ratio, style}} styles={styles} rebuild={shots.length > 0} shots={shots.length} confirmDisabled={!canBuild}
      estimate={estimate} target={target} onTarget={setTarget}
      onImport={onImportTable ? importTable : undefined} onConfirm={confirmBuild} onCancel={() => setBuilding(false)}/>}
  </div>;
}
