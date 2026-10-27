import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocale } from '../i18n/react.jsx';
import { t } from '../i18n/index.js';
import { storyList, storyRequest } from '../storyModel.js';
import { rowProposals } from '../proposalModel.js';
import { adoptionBody, isAdopted, mergeTakes } from '../takeModel.js';
import { planSeconds } from '../timelineModel.js';
import { resolveAssetReference } from '../studioModel.js';
import { addBinding, codeBase, codesElsewhere, removeBinding, replaceLook, shotBindings } from '../bindingModel.js';
import { chooseUse, insertTakeRef, prependTakeRef, previousShot, refThumb, refUse, resolveTakeRefs, takeRefUses } from '../takeRefs.js';
import { useFilmTrial } from '../StudioShell.jsx';
import { FilmMonitor } from '../ShotFilmPanel.jsx';
import { MediaLadder } from '../ShotStage.jsx';
import { GenerationBar } from '../generation/GenerationBar.jsx';
import { cameraChoice, cameraGroups, cameraText, changedGroups, insertMove, moveNumbers, moveOrder, optionLabel, removeMove, removeMoves, withCamera, CAMERA_GROUPS } from './lookModel.js';
import { shotMonitor, playingItem, useShotMonitor } from './shotMonitor.js';
import { CameraWall, ReferenceWall } from './ExampleWall.jsx';
import { LookButtons } from './LookTiles.jsx';
import { PromptEditor } from './PromptComposer.jsx';
import { Icon } from '../Icon.jsx';
import './composer.css';

// SPEC_19 R8, R9 (3.3): the shot composer, the Shot Stage's middle when a shot is chosen. The top half is the shot's take and its play bar
// (Take 3 new | Take 2 ✓ | ...; ✓ adopts, ↻ sends to Retake), or, when a look button is pressed, its example wall. Under it the look
// buttons (references and camera; package C adds film setup, palette and lighting), then the prompt, the biggest box on the screen, with
// the parameter row and the screen's one primary button. The top half is the Shot Stage's one player (shotMonitor): the right column's
// take rows, "Play around" and a take tried in the cut all play here.

const CATALOG = {promise: null};
// The camera and move options (GET /catalog/looks?kind=camera|move, paged: storyList asks 100 at a time), read once per page; a failure
// is tried again on the next mount. preloaded ({camera, moves}): the options for the first paint (the tests).
const catalogState = ({camera, moves}) => ({status: 'ready', items: camera, moves, groups: cameraGroups(camera), error: ''});
function useLookCatalog(preloaded = null) {
  const [state, setState] = useState(() => preloaded ? catalogState(preloaded) : {status: 'loading', items: [], moves: [], groups: cameraGroups([]), error: ''});
  useEffect(() => {
    if (preloaded) return undefined;
    let alive = true;
    CATALOG.promise ||= Promise.all([storyList('/catalog/looks?kind=camera'), storyList('/catalog/looks?kind=move')])
      .then(([camera, moves]) => ({camera, moves}), error => {CATALOG.promise = null; throw error;});
    CATALOG.promise.then(value => {if (alive) setState(catalogState(value));},
      error => {if (alive) setState(old => ({...old, status: 'failed', error: error.message}));});
    return () => {alive = false;};
  }, []);
  return state;
}

// The shot's video takes, newest first: its candidates and its pending media proposals (the same list as the right column's).
function useTakes(id, version, entries, status, adoption) {
  const [state, setState] = useState({id: null, videos: []});
  useEffect(() => {
    if (!id) return undefined;
    let alive = true;
    storyList(`/shots/${id}/videos`).then(videos => {if (alive) setState({id, videos});}, () => {if (alive) setState({id, videos: []});});
    return () => {alive = false;};
  }, [id, version]);
  return mergeTakes(state.id === id ? state.videos : [], entries, {status, adoption});
}

const tenth = value => (Math.round(Number(value) * 10) / 10).toFixed(1);

// The top half when nothing is playing: the take in view (its first frame, paused), with a play button.
function TakeView({take, frameUrl, output, onPlay}) {
  const still = output === 'frame' ? frameUrl : null;
  return <div className="composer-view">
    {still ? <img src={still} alt=""/> : take ? (frameUrl ? <img src={frameUrl} alt=""/> : <video src={take.url + '#t=0.1'} preload="metadata" muted playsInline aria-hidden="true"/>)
      : <span className="composer-empty"><Icon name="clapper" size={22}/>{t(output === 'frame' ? 'take.noFrames' : 'take.none')}</span>}
    {take && output !== 'frame' && <button type="button" className="composer-play" aria-label={t('take.play', {number: take.number})} onClick={() => onPlay(take)}><Icon name="play" size={20}/></button>}
  </div>;
}

// The play bar: the takes newest first, the adopted one ticked; ✓ adopts the take in view, ↻ sends the shot to Retake.
function TakeBar({takes, viewUrl, playingUrl, writable, disabled, canStatus, onPick, onAdopt, onRetake}) {
  const shown = takes.slice(0, 5), view = takes.find(take => take.url === viewUrl) || null, body = view && adoptionBody(view);
  return <div className="composer-takes" role="group" aria-label={t('take.list')}>
    <ol>{shown.map(take => <li key={take.url}><button type="button" aria-pressed={take.url === viewUrl} className={take.url === playingUrl ? 'is-playing' : undefined}
      onClick={() => onPick(take)}>{t('take.number', {number: take.number})}{take.adopted ? <Icon name="check" size={12}/> : take.isNew ? <em>{t('take.new')}</em> : null}</button></li>)}
      {takes.length > shown.length && <li className="studio-note">+{takes.length - shown.length}</li>}</ol>
    <span className="spacer"/>
    {writable && view && (view.adopted ? <span className="take-check is-on" role="img" aria-label={t('take.adopted')}><Icon name="check" size={14}/></span>
      : body ? <button type="button" className="take-check" aria-label={t('take.adoptTake', {number: view.number})} title={t('take.adoptKey')} disabled={disabled} onClick={() => onAdopt(view)}><Icon name="check" size={14}/></button> : null)}
    {writable && canStatus && <button type="button" className="take-retake" disabled={disabled} onClick={onRetake} title={t('take.retake')}><Icon name="refresh" size={13}/>{t('take.retakeKey')}</button>}
  </div>;
}

// What "See the full prompt" shows (POST /shots/{id}/prompt-previews, the worker's own compiler on the saved prompt): the prompt read-only,
// the pictures it refers to ({kind: 'asset', code, name, imageUrl}, then {kind: 'take', shotIndex, edge, at, use, adopted, ...}) and the
// camera it used ({opticalRig, cameraMovement, moves}). An unsaved prompt is not what the server would compile: it says so and offers to
// save first.
function PromptPreview({state, onSaveAndPreview, disabled}) {
  if (state.status === 'unsaved') return <p className="studio-note warn composer-preview-note" role="note">{t('composer.previewUnsaved')}
    {onSaveAndPreview && <button type="button" className="quiet" disabled={disabled} onClick={onSaveAndPreview}>{t('composer.saveAndPreview')}</button>}</p>;
  if (state.status === 'loading') return <p className="sheet-subtle" role="status">{t('composer.previewLoading')}</p>;
  if (state.status === 'failed') return <p className="gen-error" role="alert">{t('composer.previewFailed', {message: state.error})}</p>;
  if (state.status !== 'ready') return null;
  const {compiledPrompt = null, references = [], look = null} = state.data || {};
  const camera = [['opticalRig', look?.opticalRig], ['cameraMovement', look?.cameraMovement],
    ['moves', Array.isArray(look?.moves) && look.moves.length ? look.moves.map(move => typeof move === 'string' ? '#' + move : move?.id ? '#' + move.id : String(move)).join(' ') : '']].filter(([, value]) => value);
  return <section className="composer-preview" aria-label={t('composer.previewTitle')}>
    {compiledPrompt === null ? <p className="studio-note">{t('composer.previewNoPrompt')}</p> : <pre>{compiledPrompt}</pre>}
    {Array.isArray(references) && references.length > 0 && <ul className="composer-preview-refs" aria-label={t('composer.previewRefs')}>{references.map((ref, index) => <li key={index}>
      {ref?.kind === 'take'
        ? <><Icon name="clapper" size={13}/><span>@{ref.shotIndex}.{ref.edge} · {t('look.as_' + (ref.use === 'first_frame' ? 'first_frame' : 'reference'))}
          {Number.isFinite(ref.at) ? ' · ' + t('generation.seconds', {value: tenth(ref.at)}) : ''}{ref.adopted === false ? ' · ' + t('composer.previewNotAdopted') : ''}</span></>
        : <>{ref?.imageUrl ? <img src={ref.imageUrl} alt="" loading="lazy"/> : <Icon name="image" size={13}/>}<span>{ref?.name || ref?.code}{ref?.code ? <small> @{ref.code}</small> : null}</span></>}
    </li>)}</ul>}
    {camera.length > 0 && <dl>{camera.map(([key, value]) => <div key={key}><dt>{t('composer.preview_' + key)}</dt><dd>{String(value)}</dd></div>)}</dl>}
  </section>;
}

// The use of a quoted take: first frame (the same action continues) or reference (the same place from another angle).
function RefPopover({entry, use, onUse, onClose}) {
  const message = entry.state === 'ok' ? t('composer.refOk', {shot: entry.code, seconds: entry.at === null ? t('composer.lastFrame') : t('generation.seconds', {value: tenth(entry.at)})})
    : t('composer.ref_' + entry.state, {shot: entry.code, tag: '@' + entry.key});
  return <div className="pc-popover" role="dialog" aria-label={'@' + entry.key} onKeyDown={event => {if (event.key === 'Escape') {event.stopPropagation(); onClose();}}}>
    <header><b>@{entry.code}.{entry.edge}</b><button type="button" className="icon-btn" aria-label={t('look.close')} onClick={onClose}><Icon name="close" size={12}/></button></header>
    <p className={entry.state === 'ok' ? 'studio-note' : 'studio-note warn'}>{message}</p>
    <div className="studio-segmented small" role="radiogroup" aria-label={t('composer.refUse')}>
      {['first_frame', 'reference'].map(value => <button key={value} type="button" role="radio" aria-checked={use.use === value} aria-pressed={use.use === value}
        title={t('composer.useHint_' + value)} onClick={() => onUse(value)}>{t('look.as_' + value)}</button>)}</div>
    {!use.chosen && <p className="studio-note">{t(use.decided ? 'composer.useDefault' : 'composer.useServer')}</p>}
  </div>;
}

export function ShotComposer({slug, tabKey, rid, shot = null, shots = [], label, scene = null, status = '', text = '', dirty = false, promptColumn = true,
  onDraft, onSave, onRevert, rig = {text: '', column: false}, motionText = '', undo = null, ladder = [], lookup = {}, headers = [], cells = [], actionCol = -1,
  proposals = [], version, inFlight = false, generating = 0, writable = false, disabled = false, canStatus = true, controlRef,
  onWrite, onRetake, onShowStage, onOpenWorld, onGenerate, preloaded = {}}) {
  useLocale();
  const id = shot?.shotId || `sh_${slug}_${rid}`;
  const catalog = useLookCatalog(preloaded.catalog || null);
  const entries = useMemo(() => rowProposals(proposals, rid, tabKey), [proposals, rid, tabKey]);
  const takes = useTakes(id, version, entries, status, shot?.adoption ?? null);
  const {playing} = useShotMonitor();
  const trial = useFilmTrial();
  const item = playingItem(playing);
  const [output, setOutput] = useState('video'), [wall, setWall] = useState(null), [view, setView] = useState(null);
  const [refCategory, setRefCategory] = useState('CHARACTER'), [cameraCategory, setCameraCategory] = useState('rig');
  const [uses, setUses] = useState({}), [refOpen, setRefOpen] = useState(null), [preview, setPreview] = useState({open: false, status: 'idle'});
  const editor = useRef(null), bodyRef = useRef(null);
  // This composer draws the stage's one player while it is on the page.
  useEffect(() => shotMonitor.host(), []);
  useEffect(() => {setView(null); setUses({}); setRefOpen(null); setPreview({open: false, status: 'idle'});}, [id]);
  useEffect(() => {
    if (!controlRef) return undefined;
    const control = {escape: () => {if (refOpen) {setRefOpen(null); return true;} if (wall) {setWall(null); return true;} return false;}};
    controlRef.current = control;
    return () => {if (controlRef.current === control) controlRef.current = null;};
  });

  const moves = catalog.moves;
  const choice = useMemo(() => cameraChoice(rig.text, catalog.items), [rig.text, catalog.items]);
  const numbers = useMemo(() => moveNumbers(text, moves), [text, moves]), order = useMemo(() => moveOrder(text, moves), [text, moves]);
  const film = useMemo(() => shots.some(item => item.shotId === id) ? shots : [...shots, ...(shot ? [shot] : [])], [shots, shot, id]);
  const current = film.find(item => item.shotId === id) || shot;
  const refs = useMemo(() => resolveTakeRefs(text, film, id), [text, film, id]);
  const previous = previousShot(film, current);
  const quotable = film.filter(item => item.shotId !== id && isAdopted(item));
  const rows = useMemo(() => shotBindings(text, lookup), [text, lookup]);
  const elsewhere = useMemo(() => actionCol >= 0 ? codesElsewhere(headers, cells, actionCol) : {}, [headers, cells, actionCol]);
  const more = useMemo(() => {const named = new Set(rows.map(row => row.code)); return shotBindings(Object.keys(elsewhere).filter(code => !named.has(code)).map(code => '@' + code).join(' '), lookup);}, [rows, elsewhere, lookup]);

  // Every change to the prompt goes through the editor, so it can be undone there and is saved with the prompt.
  const edit = fn => {if (editor.current) editor.current.insert(fn); else {const result = fn(text, text.length); if (result && result.text !== text) onDraft(result.text);}};
  const castEdit = op => edit(source => ({text: op(source), caret: op(source).length}));
  const openWall = next => {if (next) shotMonitor.stop(); setWall(next); setRefOpen(null);};

  // A tag's look in the prompt.
  const byMove = useMemo(() => Object.fromEntries(moves.map(item => [item.id, item])), [moves]);
  const byRef = useMemo(() => Object.fromEntries(refs.map(ref => [ref.key, ref])), [refs]);
  const decorate = useCallback(token => {
    if (token.kind === 'move') {const item = byMove[token.id]; return {cls: 'is-move', label: '#' + optionLabel(item, t), title: item?.promptText || token.text, icon: '↗'};}
    if (token.kind === 'take') {
      const ref = byRef[token.key], use = ref ? refUse(ref, uses, current) : null;
      if (!ref) return {cls: 'is-warn', label: token.text, title: token.text};
      const warn = ref.state !== 'ok';
      return {cls: 'is-take' + (warn ? ' is-warn' : ''), thumb: refThumb(ref, shot?.takeRefs), label: `${ref.code} · ${t('composer.edge_' + ref.edge)} · ${t('look.as_' + use.use)}`,
        title: ref.state === 'ok' ? t('composer.refOk', {shot: ref.code, seconds: ref.at === null ? t('composer.lastFrame') : t('generation.seconds', {value: tenth(ref.at)})}) : t('composer.ref_' + ref.state, {shot: ref.code, tag: token.text})};
    }
    const entry = resolveAssetReference(token.code, lookup), known = Boolean(lookup[token.code] || lookup[codeBase(token.code)]);
    if (!known) return {cls: 'is-warn', label: '@' + token.code, title: t('stage.unknownCode', {code: '@' + token.code}), icon: '!'};
    const image = entry.media?.kind === 'image' ? entry.media.url : null;
    return {cls: 'is-asset' + (image ? '' : ' is-missing'), label: entry.name || token.code, title: '@' + token.code, thumb: image ? {kind: 'image', url: image} : null};
  }, [byMove, byRef, uses, current, shot?.takeRefs, lookup]);

  // The camera: body, lens and aperture are written to the Optical Rig column at once (undoable); moves are #tags in the prompt.
  const chooseCamera = (group, value) => {if (!writable || !rig.column) return; const next = cameraText(withCamera(choice, group, value), catalog.items); if (next !== rig.text) rig.onWrite(next);};
  const toggleMove = item => numbers[item.id] ? edit(source => {const next = removeMove(source, item.id, moves); return {text: next, caret: next.length};})
    : edit((source, caret) => insertMove(source, caret, item.id));
  const resetCamera = () => {if (rig.column && rig.text) rig.onWrite(''); if (order.length) edit(source => {const next = removeMoves(source, moves); return {text: next, caret: next.length};});};

  // Takes: the one in view is the one playing, else the one picked on the bar, else the newest.
  const playingTake = item && item.shotId === id ? takes.find(take => take.url === item.url) || null : null;
  const inView = playingTake || takes.find(take => take.url === view) || takes[0] || null;
  const playTake = take => {setView(take.url); setWall(null); shotMonitor.play([{shotId: id, shotIndex: current?.shotIndex || label, index: 0, url: take.url, in: 0, out: null, source: 'take', number: take.number}]);};
  const adopt = take => {const body = adoptionBody(take); if (writable && body) onWrite?.(() => storyRequest(`/shots/${id}/adoptions`, 'POST', body), {proposals: 'proposalId' in body});};

  const generate = async body => {
    const sent = takeRefUses(text, uses);
    await onGenerate?.({output, body: {...body, ...(sent ? {takeRefUses: sent} : {})}});
  };
  // The server compiles the saved prompt; with unsaved changes the preview asks for a save first (a promptOverride would replace the
  // whole compiled prompt and leave the #moves unexpanded, so it is never used for this).
  const fetchPreview = async saved => {
    const body = bodyRef.current;
    if (!body) return;
    const sent = takeRefUses(saved, uses);
    setPreview({open: true, status: 'loading'});
    try {setPreview({open: true, status: 'ready', data: await storyRequest(`/shots/${id}/prompt-previews`, 'POST', {...body, kind: output === 'frame' ? 'image' : 'video', ...(sent ? {takeRefUses: sent} : {})})});}
    catch (error) {setPreview({open: true, status: 'failed', error: error.message});}
  };
  const loadPreview = () => {
    if (preview.open) {setPreview({open: false, status: 'idle'}); return;}
    if (dirty) {setPreview({open: true, status: 'unsaved'}); return;}
    fetchPreview(String(cells[actionCol]?.value ?? ''));
  };
  const saveAndPreview = async () => {const saved = text; if (await onSave?.()) fetchPreview(saved);};
  // A preview of the saved text goes stale once the prompt changes again.
  useEffect(() => {if (dirty) setPreview(old => old.open && old.status !== 'unsaved' ? {open: true, status: 'unsaved'} : old);}, [dirty]);

  const adopted = takes.find(take => take.adopted);
  const missing = rows.filter(row => row.missing && !row.unknown).length;
  const cameraNames = CAMERA_GROUPS.map(group => catalog.items.find(option => option.id === choice[group])).filter(option => option?.promptText).map(option => optionLabel(option, t));
  const moveNames = order.map(moveId => optionLabel(byMove[moveId], t));
  const cameraValue = [...(choice.custom ? [t('look.custom')] : cameraNames), ...moveNames].join(' · ');
  const buttons = [
    {id: 'references', label: t('look.references'), scope: 'shot', icon: 'users', thumb: rows.find(row => row.imageUrl)?.imageUrl || null, dot: missing > 0,
      value: rows.length ? t(missing ? 'look.refSummaryMissing' : 'look.refSummary', {count: rows.length, missing}) : ''},
    {id: 'camera', label: t('look.camera'), scope: 'shot', icon: 'clapper', value: cameraValue, full: choice.custom ? rig.text : cameraValue,
      badge: current?.previsVideoUrl ? t('look.fromPrevis') : null},
  ];
  const ref = refOpen ? byRef[refOpen] : null;
  const seconds = current ? planSeconds(current) : null;
  const stateLine = [scene?.index != null && t('composer.scene', {index: scene.index}), Number.isFinite(seconds) && t('generation.seconds', {value: tenth(seconds)}),
    adopted ? t('composer.inCut', {number: adopted.number}) : t('composer.notInCut')].filter(Boolean).join(' · ');

  return <section className="shot-composer" aria-label={t('composer.title')} onKeyDown={event => {if (event.key === 'Escape' && (refOpen || wall)) {event.preventDefault(); if (refOpen) setRefOpen(null); else setWall(null);}}}>
    <header className="composer-head"><b className="num">{label}</b>{scene?.title && <span className="composer-scene" title={scene.title}>{scene.title}</span>}
      <span className="studio-note">{stateLine}</span><span className="spacer"/>
      {(inFlight || generating > 0) && <span className="shot-state is-generating"><i className="shot-dot state-generating" aria-hidden="true"/>{t('take.state_generating')}{generating > 0 && <span className="num">{generating}</span>}</span>}
    </header>
    <div className="composer-top">
      {wall === 'camera' ? <CameraWall catalog={catalog} choice={choice} custom={choice.custom && Boolean(rig.text)} numbers={numbers} order={order} moves={moves} legacyMotion={motionText}
          rigColumn={rig.column} disabled={!writable || disabled} hasPrevis={Boolean(current?.previsVideoUrl)} category={cameraCategory} onCategory={setCameraCategory}
          changed={changedGroups(choice, catalog.items)} onChoose={chooseCamera} onMove={toggleMove} onClose={() => setWall(null)} onReset={resetCamera}
          onUndo={undo?.can ? undo.run : undefined} onStage={onShowStage}/>
        : wall === 'references' ? <ReferenceWall rows={rows} more={more} lookup={lookup} elsewhere={elsewhere} writable={writable && promptColumn} disabled={disabled} category={refCategory}
          onCategory={setRefCategory} onClose={() => setWall(null)} onFix={onOpenWorld}
          onLook={(code, next) => castEdit(source => replaceLook(source, code, next))} onRemove={code => castEdit(source => removeBinding(source, code))} onAdd={code => castEdit(source => addBinding(source, code))}
          shots={quotable} previous={previous} onQuote={(target, edge) => edit((source, caret) => insertTakeRef(source, caret, target.shotIndex, edge))}
          onContinue={(use, leave) => {edit(source => prependTakeRef(source, previous.code, 'end')); if (!leave) setUses(old => chooseUse(old, previous.key, use));}}/>
        : <>
          {item ? <FilmMonitor item={item} clip={`${playing.run}:${playing.at}`} trial={trial} currentId={id} onDone={shotMonitor.next} onStop={shotMonitor.stop} onMeasured={shotMonitor.measure}/>
            : <TakeView take={inView} frameUrl={current?.selectedImageUrl || null} output={output} onPlay={playTake}/>}
          <TakeBar takes={takes} viewUrl={inView?.url || null} playingUrl={playingTake?.url || null} writable={writable} disabled={disabled} canStatus={canStatus}
            onPick={playTake} onAdopt={adopt} onRetake={onRetake}/>
        </>}
    </div>
    <LookButtons buttons={buttons} open={wall} onOpen={openWall}/>
    <section className="prompt-box" aria-label={t('composer.prompt')}>
      <header><b>{t('composer.prompt')}</b><small className="studio-note">{t('composer.promptHint')}</small><span className="spacer"/>
        {dirty && <><span className="studio-note warn" role="status">{t('composer.unsaved')}</span>
          <button type="button" className="quiet" onClick={onRevert} disabled={disabled}>{t('composer.revert')}</button></>}
        <button type="button" className="quiet composer-preview-toggle" aria-expanded={preview.open} onClick={loadPreview}>{t('composer.previewToggle')}<Icon name={preview.open ? 'chevronDown' : 'arrowRight'} size={12}/></button>
      </header>
      {!promptColumn && <p className="gen-error" role="status">{t('composer.noPromptColumn')}</p>}
      <div className="pc-wrap">
        <PromptEditor rid={rid} value={text} onChange={onDraft} onSave={onSave} editable={writable && promptColumn && !disabled} moves={moves} decorate={decorate}
          menus={{assets: lookup, moves, shots: quotable}} api={editor} label={t('composer.prompt')} placeholder={t('composer.placeholder')}
          onTag={tag => {if (tag.kind === 'take' && tag.key) setRefOpen(old => old === tag.key ? null : tag.key); else if (tag.kind === 'move') openWall('camera'); else if (tag.kind === 'asset') openWall('references');}}/>
        {ref && <RefPopover entry={ref} use={refUse(ref, uses, current)} onUse={value => setUses(old => chooseUse(old, ref.key, value))} onClose={() => setRefOpen(null)}/>}
      </div>
      {preview.open && <PromptPreview state={preview} disabled={disabled} onSaveAndPreview={writable && promptColumn ? saveAndPreview : null}/>}
      {writable ? <GenerationBar kind="shot" id={id} output={output} preloaded={preloaded.bar || null} seconds={seconds} dirty={dirty} bodyRef={bodyRef} disabled={disabled || !promptColumn}
        lead={<>
          <span className="pc-triggers" role="group" aria-label={t('composer.insert')}>
            <button type="button" className="icon-btn" title={t('composer.insertCast')} aria-label={t('composer.insertCast')} disabled={!promptColumn || disabled}
              onClick={() => editor.current?.insert((source, caret) => {const before = source.slice(0, caret), lead = before && !/[\s(（[【「]$/.test(before) ? ' ' : ''; return {text: before + lead + '@' + source.slice(caret), caret: caret + lead.length + 1};}, {openMenu: true})}>@</button>
            <button type="button" className="icon-btn" title={t('composer.insertMove')} aria-label={t('composer.insertMove')} disabled={!promptColumn || disabled}
              onClick={() => editor.current?.insert((source, caret) => {const before = source.slice(0, caret), lead = before && !/\s$/.test(before) ? ' ' : ''; return {text: before + lead + '#' + source.slice(caret), caret: caret + lead.length + 1};}, {openMenu: true})}>#</button>
          </span>
          <MediaLadder steps={ladder} output={output} onOutput={setOutput}/>
        </>}
        onGenerate={generate}/> : <p className="studio-note">{t('composer.readOnly')}</p>}
    </section>
  </section>;
}
