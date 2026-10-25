import { useEffect, useRef, useState } from 'react';
import { useLocale } from './i18n/react.jsx';
import { t } from './i18n/index.js';
import { statusLabel } from './format.js';
import { isWide } from './worldModel.js';
import { storyList } from './storyModel.js';
import { isActiveRun } from './generation/generationModel.js';
import { GenerationBar } from './generation/GenerationBar.jsx';
import { AppearanceForm } from './AppearanceForm.jsx';
import { describing, generateKey, newLookText, orderedImages, subjectOf } from './editorModel.js';
import { Icon } from './Icon.jsx';
import { RunState, Spinner, Status } from './WorldWall.jsx';

// SPEC_18 R12, as revised twice: the card in front of you is worked on in the large pane, laid out like the studio it was studied from.
// The picture on top with every picture of this look beside it; the looks under it, each with its own pictures and a + for another;
// then the description, the most important thing about a character, as one big box with the generation choices on a single row under
// it. Everything the editor acts on (the description, the pictures, the generate button, the upload) belongs to the look you picked, or
// to the card itself when none is picked. What is left (voice, status, notes, where it appears) folds away under it.
// Keyed by asset in the parent, so editing state never leaks from one card to the next.
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

// The looks of a card, as a strip of pictures with a + at the end for another one; the picked look can be renamed or deleted. A look is made
// from the card's own description (the same person in other clothes) and deleting says first which shots use it, and what happens to them.
const LOOK_KINDS = ['OUTFIT', 'POSE', 'LOOK'];
function LookStrip({item, looks, look, onLook, writable, busy, runs, onCreate, onRename, onDelete}) {
  const [mode, setMode] = useState(null), [name, setName] = useState(''), [kind, setKind] = useState('OUTFIT'), [text, setText] = useState('');
  const shown = looks.find(variant => variant.assetId === look) || null;
  const used = shown ? item.uses.filter(shot => (shot.assets || []).some(code => String(code).toUpperCase() === shown.assetCode.toUpperCase())) : [];
  const close = () => {setMode(null); setName(''); setText(''); setKind('OUTFIT');};
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
    {mode === 'new' && <form className="world-edit" onSubmit={async event => {event.preventDefault(); if (await onCreate(item.assetId, {name:name.trim(), kind, prompt:text.trim()})) close();}}>
      <label className="modal-field">{t('world.lookName')}<input value={name} required maxLength={120} autoFocus disabled={busy} onChange={event => setName(event.target.value)}/></label>
      <label className="modal-field">{t('world.lookKindLabel')}<select value={kind} disabled={busy} onChange={event => setKind(event.target.value)}>{LOOK_KINDS.map(key => <option key={key} value={key}>{t('world.lookKind_' + key)}</option>)}</select></label>
      <label className="modal-field">{t('world.lookPrompt')}<textarea rows={5} value={text} maxLength={4000} disabled={busy} onChange={event => setText(event.target.value)}/></label>
      <div className="world-actions"><button type="submit" className="world-act" disabled={busy || !name.trim()}>{t('world.lookCreate')}</button><button type="button" className="world-tool" onClick={close}>{t('common.cancel')}</button></div>
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

export function AssetEditor({item, detail, scenes = [], writable, busy, runs = {}, ratio = '', styleName = '', preloadedImages = null, onSave, onUpload, onGenerate, onCancel, onSelectImage, onClose,
  onLookCreate, onLookRename, onLookDelete, onOpenShot, onOpenScene, onTable, onVault}) {
  useLocale();
  const looks = detail?.variants || [];
  const [look, setLook] = useState(null), [drafts, setDrafts] = useState({}), [attrs, setAttrs] = useState(false), [zoom, setZoom] = useState(false), [preview, setPreview] = useState(null);
  const [naming, setNaming] = useState(false), [nameDraft, setNameDraft] = useState('');
  const file = useRef(null);
  const subject = subjectOf(item, looks, look), shown = subject === item ? null : subject;
  const run = runs[subject.assetId] || null, generating = isActiveRun(run);
  const {text, dirty} = describing(subject, drafts);
  const image = preview?.url || subject.selectedImageUrl, previewing = Boolean(preview && !preview.selected);
  const used = item.sceneIds.map(id => scenes.find(scene => scene.sceneId === id)).filter(Boolean);
  const wide = isWide(item.type);
  const setText = value => setDrafts(current => ({...current, [subject.assetId]: value}));
  const revert = () => setDrafts(current => {const {[subject.assetId]: dropped, ...rest} = current; return rest;});
  const pickLook = id => {setLook(id); setPreview(null); setAttrs(false);};
  // Saving the description is the same write as ever (PATCH /assets/{id}); the box then shows what the server kept.
  const saveText = async () => {const done = await onSave(subject.assetId, {prompt:text.trim()}); if (done) revert(); return done;};
  const generate = async body => {if (dirty && !(await saveText())) return; onGenerate(subject.assetId, body);};
  const useImage = async () => {if (await onSelectImage(subject.assetId, preview.imageId)) setPreview(null);};
  const saveName = async () => {
    const next = nameDraft.trim();
    if (!next) return;
    if (await (shown ? onLookRename(item.assetId, shown.variantId, next) : onSave(item.assetId, {name:next}))) setNaming(false);
  };
  const label = t(generateKey({generating, failed:run?.status === 'FAILED', dirty, hasImage:Boolean(subject.selectedImageUrl)}));
  const kinds = item.type;
  const summary = [t('world.voice_' + kinds) + ': ' + (item.voice || t('world.unset')), item.status ? statusLabel(item.status) : '', t('shell.shotCount', {count:item.uses.length})].filter(Boolean).join(' · ');
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
          onChange={event => {const chosen = event.target.files?.[0]; event.target.value = ''; if (chosen) onUpload(subject.assetId, chosen);}}/></>}
      {onClose && <button type="button" className="icon-btn world-close" aria-label={t('world.closeEditor')} title={t('world.closeEditor')} onClick={onClose}><Icon name="close"/></button>}
    </header>
    <div className="world-editor-box"><div className="world-editor-body">
      <div className="world-stage">
        <figure className={'world-hero' + (wide ? ' is-wide' : '') + (generating ? ' is-busy' : '')}>
          {image ? <button type="button" className="world-zoom" aria-label={t('world.enlarge')} onClick={() => setZoom(true)}><img src={image} alt={item.name}/></button>
            : <span className="world-art-empty"><Icon name="image" size={22}/>{shown ? t('world.lookNoImage') : t('world.needsImage')}</span>}
          {previewing && <figcaption>{t('world.previewing')}</figcaption>}
          {previewing && writable && <button type="button" className="world-act world-usepic" disabled={busy} onClick={useImage}>{t('world.useImage')}</button>}
          {run && <RunState run={run}/>}
        </figure>
        <Pictures key={subject.assetId} id={subject.assetId} selectedUrl={subject.selectedImageUrl} shownUrl={preview?.url || ''} revision={run?.status || ''} preloaded={preloadedImages} onPick={setPreview}/>
      </div>
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
        {writable && <GenerationBar key={subject.assetId} id={subject.assetId} ratio={ratio} styleName={styleName} label={label} generating={generating} canCancel={Boolean(run?.taskId)} disabled={busy}
          onGenerate={generate} onCancel={() => onCancel(subject.assetId)}/>}
      </section>
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
    {zoom && image && <Lightbox src={image} alt={item.name} onClose={() => setZoom(false)}/>}
  </section>;
}
