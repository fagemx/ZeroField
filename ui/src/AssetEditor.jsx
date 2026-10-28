import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocale } from './i18n/react.jsx';
import { t } from './i18n/index.js';
import { statusLabel } from './format.js';
import { isWide, rememberPanelGenerations, restoredPanelGenerations } from './worldModel.js';
import { storyList, storyRequest } from './storyModel.js';
import { MAX_TAKES, isActiveRun, restoredRuns, settleRun } from './generation/generationModel.js';
import { GenerationBar } from './generation/GenerationBar.jsx';
import { AppearanceForm } from './AppearanceForm.jsx';
import { describing, generateKey, newLookText, orderedImages, subjectOf } from './editorModel.js';
import { ALL, LOOK_KINDS, STRESS, STRESS_DEFAULT, STRESS_MAX, STRESS_MIN, STRESS_WITH_MAX, activeTasks, batchRun, chosenPanel, createdTasks, finishedScopes, hasPicture, isMadePanel,
  knownPanels, lockFields, lookBody, lookReady, metaPatch, panelCandidates, panelGenerationBody, panelRunEntries, panelRunRefused, panelRunState, panelRunsStarted,
  panelStrip, startPanelRuns, startingPanel, stressBody, stressCompany, stressMarked, stressOrder, stressTally } from './assetPanels.js';
import { Icon } from './Icon.jsx';
import { RunState, Spinner, Status } from './WorldWall.jsx';

// SPEC_18 R12, as revised twice: the card in front of you is worked on in the large pane, laid out like the studio it was studied from.
// The picture on top with every picture of this look beside it; the looks under it, each with its own pictures and a + for another;
// then the description, the most important thing about a character, as one big box with the generation choices on a single row under
// it. Everything the editor acts on (the description, the pictures, the generate button, the upload) belongs to the look you picked, or
// to the card itself when none is picked. What is left (voice, status, notes, where it appears) folds away under it.
// SPEC_21 §4: an asset is its text and its pictures, and each picture does one job. A strip under the picture lists the asset's panels
// (Face | Front (no head) | Back | Sheet for a character, Plate | Reverse | Angle for a set, Product for a prop) with "All pictures" before
// them and the stress test after them; the picture and the column beside it show the panel you picked and its candidates, and the row under
// the description makes more of it. The locks (acting profile; location map and light logic; shape lock; a look's change) sit under the
// description, each saved when you leave it. Panel pictures and stress tests run in the background like the card's own picture.
// Keyed by asset in the parent, so editing state never leaks from one card to the next.
// assets (optional): the wall's cards, so the stress test can offer them by name; without it, the codes of the shots this card is in.
// onRefresh (optional): called after a panel choice that may change the card's main picture, so the wall can read the card again.
const pad = index => String(index).padStart(2, '0');

function Lightbox({src, alt, onClose}) {
  useEffect(() => {
    const keys = event => {if (event.key === 'Escape') {event.stopPropagation(); onClose();}};
    window.addEventListener('keydown', keys, true);
    return () => window.removeEventListener('keydown', keys, true);
  }, [onClose]);
  return <div className="modal-scrim world-lightbox" onMouseDown={event => {if (event.target === event.currentTarget) onClose();}}>
    <img src={src} alt={alt}/>
    <button type="button" className="icon-btn" aria-label={t('world.closeImage')} onClick={onClose}><Icon name="close"/></button>
  </div>;
}

// One short field of the card edited where it stands. Text saves with Enter or Save, Escape puts it back; a status is a menu that saves
// when you pick (only values the sheet already knows). Readers see the value and no control.
const STATUS_CHOICES = ['Queued', 'In Progress', 'Pending Review', 'Blocked', 'Approved'];
function InlineField({label, value, kind = 'text', writable, busy, onSave}) {
  const [editing, setEditing] = useState(false), [draft, setDraft] = useState(value || '');
  const shape = kind === 'textarea' ? 'is-long' : 'is-short';  // a long field takes the whole row, short ones share it
  const close = () => {setEditing(false); setDraft(value || '');};
  const save = async () => {if (draft.trim() === String(value || '').trim() || await onSave(draft.trim())) setEditing(false);};
  if (!editing) return <div className={shape}><dt>{label}</dt><dd className={value ? '' : 'is-unset'}>{value || t('world.unset')}</dd>
    {writable && <button type="button" className="icon-btn world-field-edit" aria-label={t('world.editField', {field:label})} onClick={() => {setDraft(value || ''); setEditing(true);}}><Icon name="pencil" size={13}/></button>}</div>;
  return <div className={shape + ' world-inline-edit'}><dt>{label}</dt><dd>
    {kind === 'textarea'
      ? <textarea rows={3} value={draft} maxLength={4000} autoFocus disabled={busy} aria-label={label} onChange={event => setDraft(event.target.value)} onKeyDown={event => {if (event.key === 'Escape') {event.stopPropagation(); close();}}}/>
      : <input value={draft} maxLength={400} autoFocus disabled={busy} aria-label={label} onChange={event => setDraft(event.target.value)}
        onKeyDown={event => {if (event.key === 'Enter') {event.preventDefault(); save();} else if (event.key === 'Escape') {event.stopPropagation(); close();}}}/>}
    <span className="world-actions"><button type="button" className="world-act" disabled={busy} onClick={save}>{t('common.save')}</button><button type="button" className="world-tool" onClick={close}>{t('common.cancel')}</button></span>
  </dd></div>;
}

function StatusField({value, writable, busy, onSave}) {
  if (!writable) return null;
  const choices = value && !STATUS_CHOICES.includes(value) ? [value, ...STATUS_CHOICES] : STATUS_CHOICES;
  return <div className="is-short"><dt>{t('world.status')}</dt><dd><select aria-label={t('world.status')} value={value || ''} disabled={busy} onChange={event => onSave(event.target.value)}>
    {!value && <option value="">{t('world.unset')}</option>}{choices.map(choice => <option key={choice} value={choice}>{statusLabel(choice)}</option>)}</select></dd></div>;
}

// Every picture of one look (or of the card itself), the main one first. Picking one shows it in the picture above; making it the main one
// is a separate, deliberate step, because the main picture is what the shots use. Read again whenever the main picture or a run changes.
function Pictures({id, selectedUrl, shownUrl, revision, preloaded = null, onPick}) {
  useLocale();
  const [images, setImages] = useState(preloaded);
  useEffect(() => {
    if (preloaded) return undefined;
    let alive = true;
    storyList(`/assets/${id}/images`).then(items => {if (alive) setImages(items);}).catch(() => {if (alive) setImages([]);});
    return () => {alive = false;};
  }, [id, selectedUrl, revision, preloaded]);
  const list = orderedImages(images || []);
  return <aside className="world-pictures" aria-label={t('world.imagesTitle')}>
    <h3>{t('world.imagesTitle')}<span className="num">{list.length}</span></h3>
    <ul>{list.map(image => <li key={image.imageId}><button type="button" aria-pressed={(shownUrl || selectedUrl) === image.url} title={image.selected ? t('world.mainImage') : undefined} onClick={() => onPick(image)}>
      <img src={image.url} alt="" loading="lazy"/>{image.selected && <span className="world-main-mark"><Icon name="check" size={11}/></span>}</button></li>)}</ul>
    {images && !list.length && <p className="space-sub">{t('world.noImages')}</p>}
  </aside>;
}

// SPEC_21: the candidates of one panel (GET /assets/{id}/images?panel=), the chosen one first and marked. Picking one previews it above;
// "Use as Face" makes it the face. Read again when the chosen one changes or a batch of this panel finishes.
function PanelPictures({id, panel, chosen, shownUrl, revision, preloaded = null, onPick}) {
  useLocale();
  const [images, setImages] = useState(preloaded);
  useEffect(() => {
    if (preloaded) return undefined;
    let alive = true;
    storyList(`/assets/${id}/images?panel=${encodeURIComponent(panel)}`).then(items => {if (alive) setImages(items);}).catch(() => {if (alive) setImages([]);});
    return () => {alive = false;};
  }, [id, panel, chosen?.imageId, revision, preloaded]);
  const list = panelCandidates(images || [], panel, chosen), name = t('world.panel_' + panel);
  return <aside className="world-pictures" aria-label={t('world.panelCandidates', {panel:name})}>
    <h3>{name}<span className="num">{list.length}</span></h3>
    <ul>{list.map(image => <li key={image.imageId}><button type="button" aria-pressed={(shownUrl || chosen?.url) === image.url} title={image.chosen ? t('world.panelChosen', {panel:name}) : undefined} onClick={() => onPick(image)}>
      <img src={image.url} alt="" loading="lazy"/>{image.chosen && <span className="world-main-mark"><Icon name="check" size={11}/></span>}</button></li>)}</ul>
    {images && !list.length && <p className="space-sub">{t('world.panelNoCandidates')}</p>}
  </aside>;
}

// Why a panel cannot be made yet, in words.
function blockText(block, baseName) {
  if (!block) return '';
  if (block.reason === 'made') return t('world.panelSheetNote');
  if (block.reason === 'base') return t('world.panelNeedsBase', {name:baseName, panel:t('world.panel_' + block.panel)});
  const names = (block.missing || []).map(panel => t('world.panel_' + panel));
  return names.length > 1 ? t('world.panelNeeds2', {first:names[0], second:names[1]}) : names.length ? t('world.panelNeeds1', {first:names[0]}) : '';
}
const runWords = state => state?.status === 'active' ? t('world.generating') : state?.status === 'failed' ? t('world.generationFailed') : state?.status === 'canceled' ? t('world.canceled') : '';

function PanelThumb({url, state}) {
  return <span className="world-panel-thumb">{url ? <img src={url} alt="" loading="lazy"/> : <span className="world-blank"/>}
    {state?.status === 'active' && <span className="world-look-busy" aria-hidden="true"><Spinner/></span>}
    {state?.status === 'failed' && <span className="world-panel-flag" aria-hidden="true"><Icon name="warning" size={12}/></span>}</span>;
}

// The strip under the picture: all pictures, each panel with what is chosen for it, and the stress test with its tally. A blocked panel can
// still be opened, to read why and to see its candidates; only making it waits.
function PanelRail({strip, mode, mainUrl, runs, subjectId, baseName, stress, onMode}) {
  const tally = stressTally(stress || []), last = (stress || []).find(item => item?.url)?.url || null, stressState = panelRunState(runs, subjectId, STRESS);
  const label = (name, extra) => [name, ...extra].filter(Boolean).join(' · ');
  return <nav className="world-panels" aria-label={t('world.panels')}>
    <button type="button" className="world-panel is-all" aria-pressed={mode === ALL} onClick={() => onMode(ALL)}><PanelThumb url={mainUrl}/><span>{t('world.panel_all')}</span></button>
    {strip.list.map(entry => {
      const state = panelRunState(runs, subjectId, entry.panel), name = t('world.panel_' + entry.panel), why = entry.made ? '' : blockText(entry.block, baseName);
      return <button key={entry.panel} type="button" className={'world-panel' + (why ? ' is-blocked' : '')} aria-pressed={mode === entry.panel} title={why || undefined}
        aria-label={label(name, [runWords(state), why])} onClick={() => onMode(entry.panel)}><PanelThumb url={entry.chosen?.url} state={state}/><span>{name}</span></button>;
    })}
    {strip.sheetPending && <span className="world-panel is-pending" role="note" title={t('world.panelSheetPending')} aria-label={label(t('world.panel_sheet'), [t('world.panelSheetPending')])}>
      <PanelThumb/><span>{t('world.panel_sheet')}</span></span>}
    <button type="button" className="world-panel is-stress" aria-pressed={mode === STRESS} aria-label={label(t('world.panel_stress'), [tally.total ? t('world.stressTally', tally) : '', runWords(stressState)])}
      onClick={() => onMode(STRESS)}><PanelThumb url={last} state={stressState}/><span>{t('world.panel_stress')}</span>{tally.total > 0 && <small>{tally.recognizable}/{tally.total}</small>}</button>
  </nav>;
}

// The row under the description while a panel is in front of you: what this panel is for (or why it cannot be made yet), how many pictures
// to make (1-4), and the button. A changed description is saved first, because the panel is drawn from it.
export function PanelBar({panel, hint, why, state, dirty, disabled, onGenerate, onCancel}) {
  const [count, setCount] = useState(1);
  const name = t('world.panel_' + panel), active = state?.status === 'active';
  const words = active ? t('world.generating') : state?.status === 'failed' ? t('world.retry') : dirty ? t('world.panelSaveAndGenerate', {panel:name}) : t('world.panelGenerate', {panel:name});
  return <div className="world-panel-bar" role="group" aria-label={t('world.panelGenerate', {panel:name})}><div className="gen-row">
    <p className={why ? 'world-panel-why' : 'world-panel-hint'}>{why || hint}</p>
    <span className="gen-end">
      {state?.status === 'failed' && <span className="gen-error" role="alert">{t('world.panelFailed', {count:state.failed})}{state.error ? ': ' + state.error : ''}</span>}
      {state?.status === 'canceled' && <span className="gen-unknown" role="status">{t('world.canceled')}</span>}
      <select className="gen-count" aria-label={t('world.panelCount')} title={t('world.panelCount')} value={count} disabled={disabled || active || Boolean(why)} onChange={event => setCount(Number(event.target.value))}>
        {Array.from({length:MAX_TAKES}, (_, index) => index + 1).map(value => <option key={value} value={value}>{t('composer.countOption', {count:value})}</option>)}</select>
      <button type="button" className="world-act gen-go" disabled={disabled || active || Boolean(why)} onClick={() => onGenerate(count)}>{words}</button>
      {active && state.taskIds.length > 0 && <button type="button" className="world-tool" onClick={onCancel}>{t('world.cancelGeneration')}</button>}
    </span>
  </div></div>;
}

// The stress test's settings, under the description while the stress test is in front of you: how many pictures (4-10), who shares the frame
// (up to five) and which set it stands in. It needs a picture of the asset to start from.
export function StressBar({type, company, ready, state, disabled, onRun, onCancel}) {
  const [count, setCount] = useState(STRESS_DEFAULT), [codes, setCodes] = useState([]), [setCode, setSetCode] = useState('');
  const active = state?.status === 'active';
  const toggle = code => setCodes(current => current.includes(code) ? current.filter(item => item !== code) : [...current, code]);
  const counts = Array.from({length:STRESS_MAX - STRESS_MIN + 1}, (_, index) => STRESS_MIN + index);
  return <div className="world-panel-bar world-stress-bar" role="group" aria-label={t('world.stressRun')}><div className="gen-row">
    {company.cast.length > 0 ? <div className="world-stress-with" role="group" aria-label={t('world.stressWith')}><span>{t('world.stressWith')}</span>
      {company.cast.slice(0, 8).map(entry => {
        const full = !codes.includes(entry.code) && codes.length >= STRESS_WITH_MAX;
        return <button key={entry.code} type="button" className="attr-chip" aria-pressed={codes.includes(entry.code)} title={full ? t('world.stressWithMax', {count:STRESS_WITH_MAX}) : '@' + entry.code}
          disabled={disabled || active || full} onClick={() => toggle(entry.code)}>{entry.name}</button>;
      })}</div>
      : <p className="world-panel-hint">{t('world.stressNoCompany')}</p>}
    {type !== 'SCENE' && company.sets.length > 0 && <select aria-label={t('world.stressSet')} title={t('world.stressSet')} value={setCode} disabled={disabled || active} onChange={event => setSetCode(event.target.value)}>
      <option value="">{t('world.stressSetNone')}</option>{company.sets.map(entry => <option key={entry.code} value={entry.code}>{entry.name === entry.code ? '@' + entry.code : entry.name}</option>)}</select>}
    <span className="gen-end">
      {!ready && <span className="world-panel-why">{t('world.stressNeedsPicture')}</span>}
      {state?.status === 'failed' && <span className="gen-error" role="alert">{t('world.panelFailed', {count:state.failed})}{state.error ? ': ' + state.error : ''}</span>}
      {state?.status === 'canceled' && <span className="gen-unknown" role="status">{t('world.canceled')}</span>}
      <select className="gen-count" aria-label={t('world.stressCount')} title={t('world.stressCount')} value={count} disabled={disabled || active || !ready} onChange={event => setCount(Number(event.target.value))}>
        {counts.map(value => <option key={value} value={value}>{t('composer.countOption', {count:value})}</option>)}</select>
      <button type="button" className="world-act gen-go" disabled={disabled || active || !ready} onClick={() => onRun(stressBody({count, withAssets:codes, setCode}))}>
        {active ? t('world.generating') : state?.status === 'failed' ? t('world.retry') : t('world.stressRun')}</button>
      {active && state.taskIds.length > 0 && <button type="button" className="world-tool" onClick={onCancel}>{t('world.cancelGeneration')}</button>}
    </span>
  </div></div>;
}

// The stress test's results, in the picture's place: each picture with who was in it, marked recognizable or not; "7 / 10 recognizable" on top.
export function StressGrid({results, state, writable, disabled, onMark, onZoom}) {
  const tally = stressTally(results), list = stressOrder(results);
  return <section className="world-stress" aria-label={t('world.stressTitle')}>
    <header><h3>{t('world.stressTitle')}</h3>{tally.total > 0 && <b className="world-stress-tally">{t('world.stressTally', tally)}</b>}
      {state?.status === 'active' && <span className="world-run is-active" role="status"><Spinner/>{t('world.generating')}</span>}</header>
    {results === null ? <p className="space-sub" role="status">{t('story.importLoading')}</p>
      : list.length ? <ul className="world-stress-grid">{list.map((entry, index) => {
        const mark = entry.recognizable === true ? 'is-yes' : entry.recognizable === false ? 'is-no' : '';
        const company = Array.isArray(entry.with) && entry.with.length ? t('world.stressWithCodes', {codes:entry.with.map(code => '@' + code).join(' ')}) : '';
        return <li key={entry.imageId || index} className={mark || undefined}>
          <button type="button" className="world-stress-img" aria-label={t('world.stressOpen', {index:index + 1})} onClick={() => onZoom(entry.url)}><img src={entry.url} alt="" loading="lazy"/></button>
          <span className="world-stress-meta"><small>#{index + 1}{company ? ' · ' + company : ''}</small>
            {writable ? <span className="world-stress-marks">
              <button type="button" className="icon-btn" aria-pressed={entry.recognizable === true} aria-label={t('world.stressMarkYes', {index:index + 1})} title={t('world.stressYes')} disabled={disabled} onClick={() => onMark(entry.imageId, true)}><Icon name="check" size={13}/></button>
              <button type="button" className="icon-btn" aria-pressed={entry.recognizable === false} aria-label={t('world.stressMarkNo', {index:index + 1})} title={t('world.stressNo')} disabled={disabled} onClick={() => onMark(entry.imageId, false)}><Icon name="close" size={13}/></button></span>
              : <em>{t(entry.recognizable === true ? 'world.stressYes' : entry.recognizable === false ? 'world.stressNo' : 'world.stressUnmarked')}</em>}
          </span></li>;
      })}</ul> : <p className="space-sub">{t('world.stressEmpty')}</p>}
  </section>;
}

// One lock: a multi-line field saved when you leave it (PATCH /assets/{id}/meta), saying whether it saved. A look's lock left blank uses the
// base's, and says so. Readers read it.
function LockField({field, value, inherited, baseName, writable, onSave}) {
  const [draft, setDraft] = useState(value || ''), [state, setState] = useState(null);
  useEffect(() => setDraft(value || ''), [value]);
  const label = t('world.lock_' + field), id = 'world-lock-' + field;
  const hint = t('world.lockHint_' + field);
  const placeholder = inherited ? t('world.lockInherited', {name:baseName}) + '\n' + inherited : hint;
  const save = async () => {
    if (draft === (value || '')) return;
    setState('saving');
    try {await onSave(field, draft); setState('saved');} catch (err) {setState({error:err.message});}
  };
  const note = state === 'saving' ? t('world.lockSaving') : state === 'saved' ? t('world.lockSaved') : state?.error ? t('world.lockFailed', {message:state.error}) : '';
  if (!writable) return <div className="world-lock is-read"><span className="world-lock-head"><b>{label}</b></span>
    <p className={value || inherited ? '' : 'is-unset'}>{value || (inherited ? t('world.lockInherited', {name:baseName}) + ': ' + inherited : t('world.unset'))}</p></div>;
  return <div className="world-lock"><span className="world-lock-head"><label htmlFor={id}><b>{label}</b></label>
    {note && <small className={state?.error ? 'is-failed' : undefined} role={state?.error ? 'alert' : 'status'}>{note}</small>}</span>
    <textarea id={id} className="world-lock-text" rows={3} value={draft} maxLength={4000} placeholder={placeholder} title={hint}
      onChange={event => {setDraft(event.target.value); if (state) setState(null);}} onBlur={save}/></div>;
}

// The looks of a card, as a strip of pictures with a + at the end for another one; the picked look can be renamed or deleted. A look is made
// from the card's own description (the same person in other clothes) and deleting says first which shots use it, and what happens to them.
// SPEC_21: a look can also be a state (wet, injured, the prop in another state), made with the change from the base.
function LookStrip({item, looks, look, onLook, writable, busy, runs, onCreate, onRename, onDelete}) {
  const [mode, setMode] = useState(null), [name, setName] = useState(''), [kind, setKind] = useState('OUTFIT'), [text, setText] = useState(''), [change, setChange] = useState('');
  const shown = looks.find(variant => variant.assetId === look) || null;
  const used = shown ? item.uses.filter(shot => (shot.assets || []).some(code => String(code).toUpperCase() === shown.assetCode.toUpperCase())) : [];
  const close = () => {setMode(null); setName(''); setText(''); setKind('OUTFIT'); setChange('');};
  const choices = [{assetId:null, name:t('world.lookDefault'), selectedImageUrl:item.selectedImageUrl}, ...looks];
  return <div className="world-look-wrap">
    <div className="world-looks" role="group" aria-label={t('world.looks')}>
      {choices.map(variant => <button key={variant.assetId || 'base'} type="button" aria-pressed={look === variant.assetId} title={variant.name} onClick={() => onLook(variant.assetId)}>
        <span className="world-look-thumb">{variant.selectedImageUrl ? <img src={variant.selectedImageUrl} alt=""/> : <span className="world-blank"/>}
          {isActiveRun(runs[variant.assetId || item.assetId]) && <span className="world-look-busy" aria-hidden="true"><Spinner/></span>}</span>
        <span>{variant.name}</span></button>)}
      {writable && onCreate && <button type="button" className="world-look-add" aria-expanded={mode === 'new'} disabled={busy} onClick={() => {const opening = mode !== 'new'; close(); if (opening) {setMode('new'); setText(newLookText(item));}}}>
        <span className="world-look-thumb"><Icon name="plus" size={20}/></span><span>{t('world.lookNew')}</span></button>}
      {writable && shown && <span className="world-look-tools">
        <button type="button" className="icon-btn" aria-label={t('world.lookRename')} title={t('world.lookRename')} aria-expanded={mode === 'rename'} disabled={busy} onClick={() => {setMode(mode === 'rename' ? null : 'rename'); setName(shown.name);}}><Icon name="pencil" size={14}/></button>
        <button type="button" className="icon-btn" aria-label={t('world.lookDelete')} title={t('world.lookDelete')} aria-expanded={mode === 'delete'} disabled={busy} onClick={() => setMode(mode === 'delete' ? null : 'delete')}><Icon name="trash" size={14}/></button></span>}
    </div>
    {mode === 'new' && <form className="world-edit" onSubmit={async event => {event.preventDefault(); if (!lookReady({name, kind, change})) return; if (await onCreate(item.assetId, lookBody({name, kind, prompt:text, change}))) close();}}>
      <label className="modal-field">{t('world.lookName')}<input value={name} required maxLength={120} autoFocus disabled={busy} onChange={event => setName(event.target.value)}/></label>
      <label className="modal-field">{t('world.lookKindLabel')}<select value={kind} disabled={busy} onChange={event => setKind(event.target.value)}>{LOOK_KINDS.map(key => <option key={key} value={key}>{t('world.lookKind_' + key)}</option>)}</select></label>
      {kind === 'STATE' && <label className="modal-field">{t('world.lock_change')}<textarea rows={2} value={change} required maxLength={4000} disabled={busy} placeholder={t('world.lockHint_change')} onChange={event => setChange(event.target.value)}/>
        <small className="space-sub">{t('world.lookStateNote', {code:item.assetCode})}</small></label>}
      <label className="modal-field">{t('world.lookPrompt')}<textarea rows={5} value={text} maxLength={4000} disabled={busy} onChange={event => setText(event.target.value)}/></label>
      <div className="world-actions"><button type="submit" className="world-act" disabled={busy || !lookReady({name, kind, change})}>{t('world.lookCreate')}</button><button type="button" className="world-tool" onClick={close}>{t('common.cancel')}</button></div>
    </form>}
    {mode === 'rename' && shown && <form className="world-edit" onSubmit={async event => {event.preventDefault(); if (await onRename(item.assetId, shown.variantId, name.trim())) close();}}>
      <label className="modal-field">{t('world.lookName')}<input value={name} required maxLength={120} autoFocus disabled={busy} onChange={event => setName(event.target.value)}/></label>
      <div className="world-actions"><button type="submit" className="world-act" disabled={busy || !name.trim() || name.trim() === shown.name}>{t('common.save')}</button><button type="button" className="world-tool" onClick={close}>{t('common.cancel')}</button></div>
    </form>}
    {mode === 'delete' && shown && <div className="world-look-delete" role="alertdialog" aria-label={t('world.lookDeleteAsk', {name:shown.name})}>
      <b>{t('world.lookDeleteAsk', {name:shown.name})}</b>
      <p>{used.length ? t('world.lookDeleteUsed', {count:used.length, shots:used.map(shot => shot.shotIndex).join(', ')}) : t('world.lookDeleteUnused')}</p>
      {used.length > 0 && <p className="space-sub">{t('world.lookDeleteNote')}</p>}
      <div className="world-actions"><button type="button" className="world-tool" onClick={close}>{t('common.cancel')}</button>
        <button type="button" className="world-act is-danger" disabled={busy} onClick={async () => {if (await onDelete(item.assetId, shown.variantId)) close();}}>{t('world.lookDeleteConfirm')}</button></div>
    </div>}
  </div>;
}

// SPEC_21: panel pictures and stress tests run in the background like the card's own picture (SPEC_18 R1, the same run rules): several at
// once, each batch can be canceled or retried, and a reload picks them up from sessionStorage instead of sending them again. They are polled
// together once a second while the editor is open; a finished task has its panel's candidates (or the stress results) read again.
function usePanelRuns(ownerId, onError) {
  const [runs, setRuns] = useState(() => restoredRuns(restoredPanelGenerations(ownerId))), [finished, setFinished] = useState({});
  const mounted = useRef(true), inflight = useRef(new Set());
  useEffect(() => {mounted.current = true; return () => {mounted.current = false;};}, []);
  const watching = JSON.stringify(activeTasks(runs));
  useEffect(() => rememberPanelGenerations(ownerId, JSON.parse(watching)), [ownerId, watching]);
  const bump = scopes => {if (scopes.length) setFinished(current => scopes.reduce((next, scope) => ({...next, [scope]:(next[scope] || 0) + 1}), current));};
  useEffect(() => {
    const tasks = JSON.parse(watching);
    if (!Object.keys(tasks).length) return undefined;
    let alive = true, timer;
    const tick = async () => {
      const answers = [];
      await Promise.all(Object.entries(tasks).map(async ([key, taskId]) => {
        try {
          const answer = await storyRequest('/tasks/' + taskId);
          if (alive) answers.push([key, answer]);
        } catch (err) {
          if (alive && err.status === 404) answers.push([key, {taskId, status:'FAILED', error:{message:err.message}}]);  // the server no longer knows it
        }
      }));
      if (!alive) return;
      if (answers.length) setRuns(current => answers.reduce((next, [key, answer]) => settleRun(next, key, answer), current));
      bump(finishedScopes(answers));
      timer = setTimeout(tick, 1000);
    };
    timer = setTimeout(tick, 600);
    return () => {alive = false; clearTimeout(timer);};
  }, [watching]);
  // One batch per panel: the click is accepted at once and the panel says "generating" before the server has answered.
  const start = (assetId, panel, path, body) => {
    const scope = assetId + '#' + panel;
    if (inflight.current.has(scope) || panelRunState(runs, assetId, panel)?.status === 'active') return;
    inflight.current.add(scope);
    setRuns(current => startPanelRuns(current, assetId, panel));
    storyRequest(path, 'POST', body)
      .then(created => {
        if (!mounted.current) return;
        setRuns(current => panelRunsStarted(current, assetId, panel, created));
        if (createdTasks(created).some(task => task.status === 'SUCCEEDED')) bump([scope]);
      })
      .catch(err => {if (mounted.current) setRuns(current => panelRunRefused(current, assetId, panel, err.message));})
      .finally(() => inflight.current.delete(scope));
  };
  const cancel = (assetId, panel) => {
    for (const [key, run] of panelRunEntries(runs, assetId, panel)) {
      if (!isActiveRun(run) || !run.taskId) continue;
      storyRequest(`/tasks/${run.taskId}/cancellations`, 'POST')
        .then(() => {if (mounted.current) setRuns(now => settleRun(now, key, {taskId:run.taskId, status:'CANCELED'}));})
        .catch(err => {if (mounted.current) onError(err.message);});
    }
  };
  return {runs, finished, start, cancel};
}

// The stress results of one subject (GET /assets/{id}/stress-tests), read again when a stress batch of it finishes; only once the server
// has said it knows panels (SPEC_21), since an older one has no stress tests to read.
function useStress(id, revision, preloaded, enabled) {
  const [results, setResults] = useState(preloaded);
  useEffect(() => {
    if (preloaded || !enabled) return undefined;
    let alive = true;
    storyList(`/assets/${id}/stress-tests`).then(items => {if (alive) setResults(items);}).catch(() => {if (alive) setResults([]);});
    return () => {alive = false;};
  }, [id, revision, preloaded, enabled]);
  return [results, setResults];
}

export function AssetEditor({item, detail, scenes = [], assets = null, writable, busy, runs = {}, ratio = '', styleName = '', preloadedImages = null, preloadedPanels = null, preloadedStress = null,
  onSave, onUpload, onGenerate, onCancel, onSelectImage, onClose, onRefresh, onLookCreate, onLookRename, onLookDelete, onOpenShot, onOpenScene, onTable, onVault}) {
  useLocale();
  const looks = detail?.variants || [];
  const [look, setLook] = useState(null), [drafts, setDrafts] = useState({}), [attrs, setAttrs] = useState(false), [zoom, setZoom] = useState(null), [preview, setPreview] = useState(null);
  const [naming, setNaming] = useState(false), [nameDraft, setNameDraft] = useState('');
  const [records, setRecords] = useState({}), [modes, setModes] = useState({}), [working, setWorking] = useState(false), [error, setError] = useState('');
  const file = useRef(null), mounted = useRef(true);
  useEffect(() => {mounted.current = true; return () => {mounted.current = false;};}, []);
  const panelRuns = usePanelRuns(item.assetId, setError);
  const subject = subjectOf(item, looks, look), shown = subject === item ? null : subject;
  const run = runs[subject.assetId] || null, generating = isActiveRun(run);
  const {text, dirty} = describing(subject, drafts);
  // SPEC_21: GET /assets/{id} carries the panels and the locks. The page reads the card's own (detail); a look's is read here, and so is any
  // record a panel choice or a lock changed, until the page reads the card again.
  const readRecord = useCallback(id => storyRequest('/assets/' + id).then(found => {if (mounted.current && found) setRecords(current => ({...current, [id]:found})); return found;}), []);
  useEffect(() => {setRecords(current => {if (!current[item.assetId]) return current; const next = {...current}; delete next[item.assetId]; return next;});}, [detail, item.assetId]);
  useEffect(() => {if (shown && !records[shown.assetId]) readRecord(shown.assetId).catch(() => {});}, [shown?.assetId]);  // eslint-disable-line react-hooks/exhaustive-deps
  const baseRecord = records[item.assetId] || detail || null;
  const record = shown ? records[shown.assetId] || (knownPanels(shown) ? shown : null) : baseRecord;
  const base = shown ? {...item, ...(baseRecord || {})} : null;
  const panels = knownPanels(record), meta = record && record.meta && typeof record.meta === 'object' ? record.meta : null;
  const mainUrl = records[subject.assetId]?.selectedImageUrl ?? subject.selectedImageUrl;
  const baseName = item.name || item.assetCode;
  const auto = startingPanel({type:item.type, panels, mainUrl, base});
  const mode = panels ? modes[subject.assetId] ?? auto : ALL;
  // Once the panels are known the view holds still: choosing a face does not move you on to the front by itself.
  useEffect(() => {if (panels && modes[subject.assetId] === undefined) setModes(current => ({...current, [subject.assetId]:auto}));}, [Boolean(panels), subject.assetId]);  // eslint-disable-line react-hooks/exhaustive-deps
  const panelMode = mode !== ALL && mode !== STRESS;
  const strip = panelStrip({type:item.type, panels, base});
  const entry = panelMode ? strip.list.find(candidate => candidate.panel === mode) || null : null;
  const chosen = panelMode ? chosenPanel(panels, mode) : null;
  const batch = mode === ALL ? null : panelRunState(panelRuns.runs, subject.assetId, mode);
  const heroRun = mode === ALL ? run : batchRun(batch), heroBusy = mode === ALL ? generating : batch?.status === 'active';
  const image = mode === ALL ? preview?.url || mainUrl : panelMode ? preview?.url || chosen?.url : null;
  const previewing = mode === ALL ? Boolean(preview && !preview.selected) : Boolean(preview && !preview.chosen);
  const why = entry && !entry.made ? blockText(entry.block, baseName) : '';
  const revision = scope => panelRuns.finished[subject.assetId + '#' + scope] || 0;
  const [stress, setStress] = useStress(subject.assetId, revision(STRESS), preloadedStress, Boolean(panels));
  const used = item.sceneIds.map(id => scenes.find(scene => scene.sceneId === id)).filter(Boolean);
  const wide = isWide(item.type) || mode === 'sheet';
  const locked = busy || working;
  const setText = value => setDrafts(current => ({...current, [subject.assetId]: value}));
  const revert = () => setDrafts(current => {const {[subject.assetId]: dropped, ...rest} = current; return rest;});
  const pickLook = id => {setLook(id); setPreview(null); setAttrs(false);};
  const pickMode = next => {setModes(current => ({...current, [subject.assetId]:next})); setPreview(null);};
  // Saving the description is the same write as ever (PATCH /assets/{id}); the box then shows what the server kept.
  const saveText = async () => {const done = await onSave(subject.assetId, {prompt:text.trim()}); if (done) revert(); return done;};
  const generate = async body => {if (dirty && !(await saveText())) return; onGenerate(subject.assetId, body);};
  const useImage = async () => {if (await onSelectImage(subject.assetId, preview.imageId)) setPreview(null);};
  // A local write (a panel choice, a lock, a stress mark): the error says itself under the picture, and the rest of the editor stays usable.
  const act = async action => {
    setWorking(true); setError('');
    try {await action(); return true;} catch (err) {if (mounted.current) setError(err.message); return false;} finally {if (mounted.current) setWorking(false);}
  };
  // PUT /assets/{id}/panels/{panel}: the candidate becomes the panel. The server makes the sheet once face, front and back are chosen and
  // writes the main picture (the sheet, a set's plate, a prop's product); it answers with {meta, panels, selectedImageUrl}, which the editor
  // shows at once, and the wall reads the card again through onRefresh.
  const usePanel = () => act(async () => {
    const saved = await storyRequest(`/assets/${subject.assetId}/panels/${mode}`, 'PUT', {imageId:preview.imageId});
    if (knownPanels(saved)) {if (mounted.current) setRecords(current => ({...current, [subject.assetId]:{...(current[subject.assetId] || record || subject), ...saved}}));}
    else await readRecord(subject.assetId);
    if (mounted.current) setPreview(null);
    onRefresh?.(subject.assetId);
  });
  const generatePanel = async count => {
    if (dirty && !(await saveText())) return;
    setError('');
    panelRuns.start(subject.assetId, mode, `/assets/${subject.assetId}/image-generations`, panelGenerationBody(mode, count));
  };
  const runStress = body => {setError(''); panelRuns.start(subject.assetId, STRESS, `/assets/${subject.assetId}/stress-tests`, body);};
  const markStress = (imageId, recognizable) => act(async () => {
    await storyRequest(`/assets/${subject.assetId}/stress-tests/${imageId}`, 'PUT', {recognizable});
    if (mounted.current) setStress(current => stressMarked(current, imageId, recognizable));
  });
  // PATCH /assets/{id}/meta answers with the locks as saved; the field shows those.
  const saveMeta = async (field, value) => {
    const body = metaPatch(field, value);
    if (!body) return;
    const saved = await storyRequest(`/assets/${subject.assetId}/meta`, 'PATCH', body);
    if (!mounted.current) return;
    const next = {...(meta || {}), ...(saved && typeof saved === 'object' && !Array.isArray(saved) ? saved : body)};
    setRecords(current => ({...current, [subject.assetId]:{...(current[subject.assetId] || record || subject), meta:next}}));
  };
  const saveName = async () => {
    const next = nameDraft.trim();
    if (!next) return;
    if (await (shown ? onLookRename(item.assetId, shown.variantId, next) : onSave(item.assetId, {name:next}))) setNaming(false);
  };
  const label = t(generateKey({generating, failed:run?.status === 'FAILED', dirty, hasImage:Boolean(subject.selectedImageUrl)}));
  const kinds = item.type;
  const summary = [t('world.voice_' + kinds) + ': ' + (item.voice || t('world.unset')), item.status ? statusLabel(item.status) : '', t('shell.shotCount', {count:item.uses.length})].filter(Boolean).join(' · ');
  const hint = panelMode ? (shown ? t('world.panelHintLook', {name:baseName, panel:t('world.panel_' + mode)}) : t('world.panelHint_' + mode)) : '';
  const fields = meta ? lockFields(item.type, Boolean(shown)) : [];
  const baseMeta = shown && baseRecord?.meta && typeof baseRecord.meta === 'object' ? baseRecord.meta : {};
  const solo = mode === 'sheet' || mode === STRESS;
  return <section className="world-inspector world-editor" aria-label={item.name || item.assetCode}>
    <header className="world-title">
      {naming
        ? <form className="world-name-edit" onSubmit={event => {event.preventDefault(); saveName();}}>
          <input value={nameDraft} maxLength={120} autoFocus disabled={busy} aria-label={t('world.newName')} onChange={event => setNameDraft(event.target.value)} onKeyDown={event => {if (event.key === 'Escape') {event.stopPropagation(); setNaming(false);}}}/>
          <button type="submit" className="world-act" disabled={busy || !nameDraft.trim()}>{t('common.save')}</button><button type="button" className="world-tool" onClick={() => setNaming(false)}>{t('common.cancel')}</button></form>
        : <div><h2>{item.name || item.assetCode}{shown && <span className="world-name-look">{shown.name}</span>}</h2><small>@{subject.assetCode}</small></div>}
      {writable && !naming && <button type="button" className="icon-btn world-field-edit" aria-label={t('world.editField', {field:t('world.newName')})} onClick={() => {setNameDraft(shown ? shown.name : item.name); setNaming(true);}}><Icon name="pencil" size={13}/></button>}
      <span className="world-type">{t('world.type_' + item.type)}</span><Status value={item.status}/>
      <span className="spacer"/>
      {writable && <>
        <button type="button" className="world-act" disabled={busy} onClick={() => file.current?.click()}><Icon name="arrowUp" size={14}/>{t('world.upload')}</button>
        <input ref={file} hidden type="file" accept="image/png,image/jpeg,image/webp,image/gif" aria-label={t('world.upload')}
          onChange={event => {const chosenFile = event.target.files?.[0]; event.target.value = ''; if (chosenFile) onUpload(subject.assetId, chosenFile);}}/></>}
      {onClose && <button type="button" className="icon-btn world-close" aria-label={t('world.closeEditor')} title={t('world.closeEditor')} onClick={onClose}><Icon name="close"/></button>}
    </header>
    <div className="world-editor-box"><div className="world-editor-body">
      <div className={'world-stage' + (panels && solo ? ' is-solo' : '') + (mode === STRESS ? ' is-stress' : '')}>
        {mode === STRESS
          ? <StressGrid results={stress} state={batch} writable={writable} disabled={locked} onMark={markStress} onZoom={setZoom}/>
          : <figure className={'world-hero' + (wide ? ' is-wide' : '') + (heroBusy ? ' is-busy' : '')}>
            {image ? <button type="button" className="world-zoom" aria-label={t('world.enlarge')} onClick={() => setZoom(image)}><img src={image} alt={item.name}/></button>
              : <span className="world-art-empty"><Icon name="image" size={22}/>{panelMode ? why || t('world.panelEmpty', {panel:t('world.panel_' + mode)}) : shown ? t('world.lookNoImage') : t('world.needsImage')}</span>}
            {previewing && <figcaption>{mode === ALL ? t('world.previewing') : t('world.panelPreviewing', {panel:t('world.panel_' + mode)})}</figcaption>}
            {previewing && writable && mode === ALL && <button type="button" className="world-act world-usepic" disabled={busy} onClick={useImage}>{t('world.useImage')}</button>}
            {previewing && writable && panelMode && !isMadePanel(mode) && <button type="button" className="world-act world-usepic" disabled={locked} onClick={usePanel}>{t('world.panelUse', {panel:t('world.panel_' + mode)})}</button>}
            {heroRun && <RunState run={heroRun}/>}
          </figure>}
        {mode === ALL && <Pictures key={subject.assetId} id={subject.assetId} selectedUrl={subject.selectedImageUrl} shownUrl={preview?.url || ''} revision={run?.status || ''} preloaded={preloadedImages} onPick={setPreview}/>}
        {panelMode && !solo && <PanelPictures key={subject.assetId + mode} id={subject.assetId} panel={mode} chosen={chosen} shownUrl={preview?.url || ''} revision={revision(mode)}
          preloaded={preloadedPanels?.[mode] || null} onPick={setPreview}/>}
      </div>
      {panels && <PanelRail strip={strip} mode={mode} mainUrl={mainUrl} runs={panelRuns.runs} subjectId={subject.assetId} baseName={baseName} stress={stress} onMode={pickMode}/>}
      {error && <p className="gen-error" role="alert">{error}</p>}
      <LookStrip item={item} looks={looks} look={look} onLook={pickLook} writable={writable} busy={busy} runs={runs} onCreate={onLookCreate} onRename={onLookRename}
        onDelete={async (assetId, variantId) => {const done = await onLookDelete(assetId, variantId); if (done) pickLook(null); return done;}}/>
      <section className="world-describe" aria-label={t('world.description_' + item.type)}>
        <header>
          <h3>{t('world.description_' + item.type)}{shown && <small>{shown.name}</small>}</h3>
          {dirty && writable && <span className="world-unsaved">{t('world.unsaved')}</span>}
          <span className="spacer"/>
          {writable && <button type="button" className="world-tool" aria-expanded={attrs} onClick={() => setAttrs(value => !value)}><Icon name="plus" size={13}/>{t('world.tabAttributes')}</button>}
        </header>
        {attrs && writable && <div className="world-attrs-pop"><AppearanceForm key={subject.assetId} current={text} disabled={busy} onApply={applied => {setText(applied); setAttrs(false);}}/></div>}
        {writable
          ? <textarea className="world-describe-text" value={text} maxLength={4000} aria-label={t('world.description_' + item.type)} placeholder={t('world.describe_' + item.type)} onChange={event => setText(event.target.value)}/>
          : <div className={'world-describe-text is-read' + (text ? '' : ' is-unset')}>{text || t('world.unset')}</div>}
        {dirty && writable && <div className="world-describe-actions"><button type="button" className="world-act" disabled={busy} onClick={saveText}>{t('common.save')}</button>
          <button type="button" className="world-tool" onClick={revert}>{t('world.revert')}</button></div>}
        {writable && mode === ALL && <GenerationBar key={subject.assetId} id={subject.assetId} ratio={ratio} styleName={styleName} label={label} generating={generating} canCancel={Boolean(run?.taskId)} disabled={busy}
          onGenerate={generate} onCancel={() => onCancel(subject.assetId)}/>}
        {writable && panelMode && !isMadePanel(mode) && <PanelBar key={subject.assetId + mode} panel={mode} hint={hint} why={why} state={batch} dirty={dirty} disabled={locked}
          onGenerate={generatePanel} onCancel={() => panelRuns.cancel(subject.assetId, mode)}/>}
        {panelMode && isMadePanel(mode) && <p className="world-panel-hint world-panel-note">{t('world.panelSheetNote')}</p>}
        {writable && mode === STRESS && <StressBar key={subject.assetId} type={item.type} company={stressCompany(item, assets)} ready={hasPicture(panels, mainUrl)} state={batch} disabled={locked}
          onRun={runStress} onCancel={() => panelRuns.cancel(subject.assetId, STRESS)}/>}
      </section>
      {fields.length > 0 && <div className="world-locks" role="group" aria-label={t('world.locksTitle')}>
        <p className="world-locks-head"><b>{t('world.locksTitle')}</b><small>{t('world.locksHint')}</small></p>
        <div className="world-lock-fields">{fields.map(field => <LockField key={subject.assetId + field} field={field} value={meta[field] || ''} inherited={shown && field !== 'change' ? baseMeta[field] || '' : ''}
          baseName={baseName} writable={writable} onSave={saveMeta}/>)}</div>
      </div>}
      <details className="world-more">
        <summary><span>{t('world.moreTitle')}</span><small>{summary}</small></summary>
        <dl className="world-fields">
          <InlineField key={'voice' + item.voice} label={t('world.voice_' + kinds)} value={item.voice} writable={writable} busy={busy} onSave={value => onSave(item.assetId, {voice:value})}/>
          <StatusField value={item.status} writable={writable} busy={busy} onSave={value => onSave(item.assetId, {status:value})}/>
          <InlineField key={'notes' + item.notes} label={t('world.notes')} value={item.notes} kind="textarea" writable={writable} busy={busy} onSave={value => onSave(item.assetId, {notes:value})}/>
        </dl>
        <section className="world-used" aria-label={t('world.uses')}>
          <h3>{t('world.uses')}</h3>
          {item.uses.length ? <>
            <p className="space-sub">{item.sceneIds.length ? t('story.assetUses', {shots:item.uses.length, scenes:item.sceneIds.length}) : t('world.usesShots', {shots:item.uses.length})}</p>
            <ul className="world-shots">{item.uses.map(shot => <li key={shot.shotId}><button type="button" title={t('world.openShot', {shot:shot.shotIndex})} onClick={() => onOpenShot(shot.rowId, shot.sceneId)}>
              {shot.selectedImageUrl ? <img src={shot.selectedImageUrl} alt="" loading="lazy"/> : <span className="world-blank"/>}<span>{shot.shotIndex}</span></button></li>)}</ul>
            {used.length > 0 && <p className="world-scenes">{used.map(scene => <button key={scene.sceneId} type="button" className="world-tool" onClick={() => onOpenScene(scene)}>
              {t('shell.sceneCrumb', {index:pad(scene.sceneIndex), title:scene.title})}</button>)}</p>}
          </> : <p className="space-sub">{t('world.usesNone')}</p>}
        </section>
        <div className="world-actions">
          <button type="button" className="world-tool" onClick={onVault}>{t('world.variants')}</button>
          <button type="button" className="world-tool" onClick={onTable}>{t('world.editInSheet')}</button>
        </div>
      </details>
    </div></div>
    {zoom && <Lightbox src={zoom} alt={item.name} onClose={() => setZoom(null)}/>}
  </section>;
}
