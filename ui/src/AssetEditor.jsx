import { useEffect, useRef, useState } from 'react';
import { useLocale } from './i18n/react.jsx';
import { t } from './i18n/index.js';
import { statusLabel } from './format.js';
import { isWide } from './worldModel.js';
import { isActiveRun } from './generation/generationModel.js';
import { GenerationBar } from './generation/GenerationBar.jsx';
import { AppearanceForm } from './AppearanceForm.jsx';
import { Icon } from './Icon.jsx';
import { RunState, Status } from './WorldWall.jsx';

// SPEC_18 R12, as revised: the card in front of you is worked on in the large pane, not squeezed into a side column. The picture is the
// biggest thing on it; beside it (under it, in a narrower pane) sit how to make it again and what it is. × closes the pane and the wall
// has the whole view back. Keyed by asset in the parent, so editing state never leaks from one card to the next.
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

// A look is made, renamed and deleted here, beside its picture. Deleting says first which shots use it, and what happens to them.
const LOOK_KINDS = ['OUTFIT', 'POSE', 'LOOK'];
function LookTools({item, shown, busy, onCreate, onRename, onDelete}) {
  const [mode, setMode] = useState(null), [name, setName] = useState(''), [kind, setKind] = useState('OUTFIT'), [text, setText] = useState('');
  const used = shown ? item.uses.filter(shot => (shot.assets || []).some(code => String(code).toUpperCase() === shown.assetCode.toUpperCase())) : [];
  const close = () => {setMode(null); setName(''); setText(''); setKind('OUTFIT');};
  return <div className="world-look-tools">
    <div className="world-actions">
      <button type="button" className="world-tool" aria-expanded={mode === 'new'} disabled={busy} onClick={() => {close(); setMode(mode === 'new' ? null : 'new');}}><Icon name="plus" size={13}/>{t('world.lookNew')}</button>
      {shown && <button type="button" className="world-tool" disabled={busy} onClick={() => {setMode(mode === 'rename' ? null : 'rename'); setName(shown.name);}}><Icon name="pencil" size={13}/>{t('world.lookRename')}</button>}
      {shown && <button type="button" className="world-tool" disabled={busy} onClick={() => setMode(mode === 'delete' ? null : 'delete')}><Icon name="trash" size={13}/>{t('world.lookDelete')}</button>}
    </div>
    {mode === 'new' && <form className="world-edit" onSubmit={async event => {event.preventDefault(); if (await onCreate(item.assetId, {name:name.trim(), kind, prompt:text.trim()})) close();}}>
      <label className="modal-field">{t('world.lookName')}<input value={name} required maxLength={120} autoFocus disabled={busy} onChange={event => setName(event.target.value)}/></label>
      <label className="modal-field">{t('world.lookKindLabel')}<select value={kind} disabled={busy} onChange={event => setKind(event.target.value)}>{LOOK_KINDS.map(key => <option key={key} value={key}>{t('world.lookKind_' + key)}</option>)}</select></label>
      <label className="modal-field">{t('world.lookPrompt')}<textarea rows={3} value={text} maxLength={4000} disabled={busy} onChange={event => setText(event.target.value)}/></label>
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

// The card in front of you, in full. Left (above, in a narrower pane): the picture, its looks and what makes it again. Right (below): what the
// card is: the appearance as text or as tags, voice, notes and status, the shots that use it, and the ways out to the sheet and the vault.
export function AssetEditor({item, detail, scenes = [], writable, busy, run = null, ratio = '', styleName = '', onSave, onUpload, onGenerate, onCancel, onClose, onLookCreate, onLookRename, onLookDelete, onOpenShot, onOpenScene, onTable, onVault}) {
  useLocale();
  const generating = isActiveRun(run);
  const [editing, setEditing] = useState(false), [name, setName] = useState(item.name), [prompt, setPrompt] = useState(item.prompt), [tab, setTab] = useState('text');
  const [look, setLook] = useState(null), [zoom, setZoom] = useState(false);
  const file = useRef(null);
  const looks = detail?.variants || [], shown = looks.find(variant => variant.assetId === look) || null;
  const image = shown ? shown.selectedImageUrl : item.selectedImageUrl;
  const used = item.sceneIds.map(id => scenes.find(scene => scene.sceneId === id)).filter(Boolean);
  const wide = isWide(item.type);
  const save = fields => onSave(item.assetId, fields);
  const label = generating ? t('world.generating') : run?.status === 'FAILED' ? t('world.retry') : item.selectedImageUrl ? t('world.regenerate') : t('world.generateHere');
  return <section className="world-inspector world-editor" aria-label={item.name || item.assetCode}>
    <header className="world-title"><div><h2>{item.name || item.assetCode}</h2><small>@{item.assetCode}</small></div>
      <span className="world-type">{t('world.type_' + item.type)}</span><Status value={item.status}/>
      <span className="spacer"/>
      {writable && <>
        <button type="button" className="world-act" disabled={busy} onClick={() => file.current?.click()}><Icon name="arrowUp" size={14}/>{t('world.upload')}</button>
        <input ref={file} hidden type="file" accept="image/png,image/jpeg,image/webp,image/gif" aria-label={t('world.upload')}
          onChange={event => {const chosen = event.target.files?.[0]; event.target.value = ''; if (chosen) onUpload(item.assetId, chosen);}}/></>}
      {onClose && <button type="button" className="icon-btn world-close" aria-label={t('world.closeEditor')} title={t('world.closeEditor')} onClick={onClose}><Icon name="close"/></button>}
    </header>
    <div className="world-editor-box"><div className="world-editor-body">
      <div className="world-stage">
        <figure className={'world-hero' + (wide ? ' is-wide' : '') + (generating ? ' is-busy' : '')}>
          {image ? <button type="button" className="world-zoom" aria-label={t('world.enlarge')} onClick={() => setZoom(true)}><img src={image} alt={item.name}/></button>
            : <span className="world-art-empty"><Icon name="image" size={22}/>{shown ? t('world.lookNoImage') : t('world.needsImage')}</span>}
          {shown && <figcaption>{t('world.lookCaption', {name:shown.name, kind:shown.kind ? t('world.lookKind_' + shown.kind) : t('world.looks')})}</figcaption>}
          {run && <RunState run={run}/>}
        </figure>
        {looks.length > 0 && <div className="world-looks" role="group" aria-label={t('world.looks')}>
          {[{assetId:null, name:t('world.lookDefault'), selectedImageUrl:item.selectedImageUrl}, ...looks].map(variant =>
            <button key={variant.assetId || 'base'} type="button" aria-pressed={look === variant.assetId} title={variant.name} onClick={() => setLook(variant.assetId)}>
              {variant.selectedImageUrl ? <img src={variant.selectedImageUrl} alt=""/> : <span className="world-blank"/>}<span>{variant.name}</span></button>)}
        </div>}
        {writable && onLookCreate && <LookTools key={shown?.assetId || 'base'} item={item} shown={shown} busy={busy} onCreate={onLookCreate}
          onRename={(assetId, variantId, next) => onLookRename(assetId, variantId, next)} onDelete={async (assetId, variantId) => {const done = await onLookDelete(assetId, variantId); if (done) setLook(null); return done;}}/>}
        {writable && <GenerationBar id={item.assetId} ratio={ratio} styleName={styleName} label={label} generating={generating} canCancel={Boolean(run?.taskId)} disabled={busy}
          onGenerate={body => onGenerate(item.assetId, body)} onCancel={() => onCancel(item.assetId)}/>}
      </div>
      <div className="world-info">
        {writable && <div className="studio-segmented small" role="group" aria-label={t('world.appearance')}>
          <button type="button" aria-pressed={tab === 'text'} onClick={() => setTab('text')}>{t('world.tabText')}</button>
          <button type="button" aria-pressed={tab === 'attributes'} onClick={() => {setTab('attributes'); setEditing(false);}}>{t('world.tabAttributes')}</button></div>}
        {writable && tab === 'attributes' ? <AppearanceForm key={item.prompt} current={item.prompt} disabled={busy} onApply={async text => {if (await save({prompt:text})) setTab('text');}}/>
          : editing ? <form className="world-edit" onSubmit={async event => {event.preventDefault(); if (await save({name:name.trim(), prompt:prompt.trim()})) setEditing(false);}}>
            <label className="modal-field">{t('world.newName')}<input value={name} required maxLength={120} disabled={busy} onChange={event => setName(event.target.value)}/></label>
            <label className="modal-field">{t('world.appearance')}<textarea rows={10} value={prompt} maxLength={4000} disabled={busy} onChange={event => setPrompt(event.target.value)}/></label>
            <div className="world-actions"><button type="submit" className="world-act" disabled={busy || !name.trim()}>{t('common.save')}</button>
              <button type="button" className="world-tool" onClick={() => {setEditing(false); setName(item.name); setPrompt(item.prompt);}}>{t('common.cancel')}</button></div>
          </form> : <dl className="world-fields">
            <div className="is-appearance"><dt>{t('world.appearance')}</dt><dd className={item.prompt ? '' : 'is-unset'}>{item.prompt || t('world.unset')}</dd></div>
            <InlineField key={'voice' + item.voice} label={t('world.voice_' + item.type)} value={item.voice} writable={writable} busy={busy} onSave={value => save({voice:value})}/>
            <StatusField value={item.status} writable={writable} busy={busy} onSave={value => save({status:value})}/>
            <InlineField key={'notes' + item.notes} label={t('world.notes')} value={item.notes} kind="textarea" writable={writable} busy={busy} onSave={value => save({notes:value})}/>
            {writable && <button type="button" className="world-tool world-edit-btn" onClick={() => {setName(item.name); setPrompt(item.prompt); setEditing(true);}}><Icon name="pencil" size={13}/>{t('world.edit')}</button>}
          </dl>}
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
      </div>
    </div></div>
    {zoom && image && <Lightbox src={image} alt={item.name} onClose={() => setZoom(false)}/>}
  </section>;
}
