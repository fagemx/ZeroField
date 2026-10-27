import { useEffect, useRef, useState } from 'react';
import { useLocale } from './i18n/react.jsx';
import { t } from './i18n/index.js';
import { storyRequest } from './storyModel.js';
import { RATIOS } from './breakdownModel.js';
import { BUTTON_KINDS, CAMERA_GROUPS, episodeDraft, episodeLookBody, idLabel, isAutoId, optionLabel, overrideCount, sameDraft, setKinds, swatchColors } from './composer/lookModel.js';
import { episodeSettings, useEpisodeSettings, useLookCatalog, useLookOptions } from './composer/lookCatalog.js';
import { CameraRigWall, LookWall } from './composer/ExampleWall.jsx';
import { LookButtons, LookTexture } from './composer/LookTiles.jsx';
import { Icon } from './Icon.jsx';
import './composer/composer.css';

// SPEC_19 R12 (3.6): the Episode look page, opened from the "16:9 · Style" tile at the foot of Story & World's left rail. It takes the
// space's middle and right columns (a big pane, not the narrow aside); x or Esc closes it and the space is as you left it. It holds
// the episode's aspect ratio, its style sample (it replaces the style choice of the storyboard dialog) and the episode's film setup,
// camera, palette and lighting, chosen on the same walls as a shot's. Choices make a draft; the page's one primary button, "Apply to
// episode", sends it (PUT /episodes/{id}/settings {aspectRatio, stylePresetId, look}). Every shot then shows the new values with
// "Episode", except what a shot overrides, which keeps "This shot" (C1); the page says how many shots keep their own.
const PAGE_BUTTONS = ['filmSetup', 'camera', 'palette', 'lighting'];
const ownRig = shots => (Array.isArray(shots) ? shots : []).filter(shot => String(shot?.opticalRig || '').trim()).length;

export function EpisodeLook({epId, ep = null, styles = [], shots = [], writable = false, onClose, onApplied, preloaded = {}}) {
  useLocale();
  const stored = useEpisodeSettings(epId, preloaded.settings || null);
  const catalog = useLookCatalog(preloaded.catalog || null), looks = useLookOptions(preloaded.looks || null);
  const base = stored.settings || ep?.settings || {}, baseKey = JSON.stringify(base);
  const [draft, setDraft] = useState(() => episodeDraft(base)), [touched, setTouched] = useState(false);
  const [wall, setWall] = useState(preloaded.wall === undefined ? 'filmSetup' : preloaded.wall), [category, setCategory] = useState('genre');
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [applied, setApplied] = useState(false);
  const root = useRef(null);
  // The page reads the stored settings when it opens; until you change something, the draft follows what the server holds.
  useEffect(() => {if (epId && !preloaded.settings) episodeSettings.load(epId).catch(err => setError(err.message));}, [epId]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {if (!touched) setDraft(episodeDraft(base));}, [baseKey]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {root.current?.focus({preventScroll: true});}, []);
  const dirty = !sameDraft(draft, episodeDraft(base));
  const disabled = !writable || busy;
  const change = next => {setDraft(next); setTouched(true); setApplied(false); setError('');};
  const look = draft.look;

  const chooseLook = (kind, id) => change({...draft, look: {...look, [kind]: id}});
  const chooseCamera = (group, id) => change({...draft, look: {...look, camera: {...look.camera, [group]: id}}});
  const resetWall = button => change({...draft, look: button === 'camera' ? {...look, camera: Object.fromEntries(CAMERA_GROUPS.map(group => [group, null]))}
    : {...look, ...Object.fromEntries(BUTTON_KINDS[button].map(kind => [kind, null]))}});
  const apply = async () => {
    if (disabled || !dirty) return;
    setBusy(true); setError('');
    try {
      const body = episodeLookBody(draft, base);
      const saved = await storyRequest(`/episodes/${epId}/settings`, 'PUT', body);
      const settings = saved && typeof saved === 'object' ? saved : body;
      episodeSettings.put(epId, settings);
      setTouched(false); setDraft(episodeDraft(settings)); setApplied(true);
      onApplied?.(settings);
    } catch (err) {setError(err.message);} finally {setBusy(false);}
  };

  // The camera columns show each group's Auto when the draft leaves it unset.
  const cameraChoice = Object.fromEntries(CAMERA_GROUPS.map(group => [group, look.camera[group] ?? catalog.groups[group]?.find(item => !item.promptText)?.id ?? null]));
  const named = (kind, id) => idLabel(kind, id, looks.kinds[kind], t);
  const buttonOf = button => {
    if (button === 'camera') {
      const chosen = CAMERA_GROUPS.map(group => catalog.groups[group]?.find(item => item.id === look.camera[group])).filter(item => item?.promptText);
      return {id: button, label: t('look.camera'), icon: 'clapper', value: chosen.map(item => optionLabel(item, t)).join(' · ') || CAMERA_GROUPS.filter(group => !isAutoId(look.camera[group])).map(group => look.camera[group]).join(' · ')};
    }
    const kinds = BUTTON_KINDS[button], set = kinds.filter(kind => !isAutoId(look[kind], looks.kinds[kind]));
    const lead = set[0] ? looks.kinds[set[0]].find(item => item.id === look[set[0]]) || null : null;
    return {id: button, label: t('look.' + button), value: set.map(kind => named(kind, look[kind])).join(' · '),
      full: kinds.length > 1 ? set.map(kind => t('look.kind_' + kind) + ': ' + named(kind, look[kind])).join(' · ') : '',
      thumb: button === 'palette' ? null : lead?.preview?.poster || null, swatch: button === 'palette' ? swatchColors(lead?.hex) : null,
      texture: {id: set[0] ? look[set[0]] : button, auto: !set.length}};
  };
  const overrides = kind => {const count = overrideCount(shots, [kind]); return count ? t('episodeLook.overrides', {count}) : '';};
  const rigs = ownRig(shots);

  return <section ref={root} className="episode-look" tabIndex={-1} aria-label={t('episodeLook.title')}
    onKeyDown={event => {if (event.key === 'Escape' && !event.defaultPrevented) {event.preventDefault(); onClose?.();}}}>
    <header className="episode-look-head">
      <h2>{t('episodeLook.title')}</h2><span className="studio-note">{t('episodeLook.hint')}</span><span className="spacer"/>
      <button type="button" className="icon-btn" aria-label={t('look.close')} title={t('look.close')} onClick={onClose}><Icon name="close" size={14}/></button>
    </header>
    <div className="episode-look-body">
      {stored.status === 'loading' && !stored.settings && !ep?.settings && <p className="sheet-subtle" role="status">{t('episodeLook.loading')}</p>}
      {stored.status === 'failed' && <p className="gen-error" role="alert">{t('episodeLook.failed', {message: stored.error || ''})}</p>}
      <section className="episode-look-format" aria-label={t('episodeLook.format')}>
        <div className="episode-look-field"><h3>{t('episodeLook.ratio')}</h3>
          <div className="studio-segmented" role="group" aria-label={t('episodeLook.ratio')}>{RATIOS.map(ratio =>
            <button key={ratio} type="button" aria-pressed={draft.aspectRatio === ratio} disabled={disabled} onClick={() => change({...draft, aspectRatio: ratio})}>{ratio}</button>)}</div></div>
        <div className="episode-look-field is-wide"><h3>{t('episodeLook.style')}</h3>
          {styles.length ? <div className="episode-look-styles" role="group" aria-label={t('episodeLook.style')}>{styles.map(item => {
            const chosen = draft.stylePresetId === String(item.stylePresetId);
            return <button key={item.stylePresetId} type="button" className={'look-tile' + (chosen ? ' is-selected' : '')} aria-pressed={chosen} disabled={disabled}
              onClick={() => change({...draft, stylePresetId: String(item.stylePresetId)})}>
              <span className="look-frame">{item.sampleImage ? <img src={item.sampleImage} alt="" loading="lazy"/> : <LookTexture id={String(item.stylePresetId)}/>}</span>
              <span className="look-name">{item.name}</span></button>;
          })}</div> : <p className="sheet-subtle">{t('episodeLook.noStyles')}</p>}</div>
      </section>
      <section className="episode-look-looks" aria-label={t('episodeLook.looks')}>
        <h3>{t('episodeLook.looks')}</h3>
        <LookButtons buttons={PAGE_BUTTONS.map(buttonOf)} open={wall} onOpen={setWall}/>
        {wall === 'camera' ? <CameraRigWall catalog={catalog} choice={cameraChoice} disabled={disabled} onChoose={chooseCamera} onClose={() => setWall(null)}
            onReset={CAMERA_GROUPS.some(group => !isAutoId(look.camera[group], catalog.groups[group])) ? () => resetWall('camera') : null}
            note={[t('episodeLook.cameraHint'), rigs ? t('episodeLook.cameraOverrides', {count: rigs}) : ''].filter(Boolean).join(' ')}/>
          : wall ? <LookWall button={wall} options={looks} category={category} onCategory={setCategory} value={kind => look[kind] ?? null} note={overrides}
            changed={setKinds(BUTTON_KINDS[wall], look, looks.kinds)} disabled={disabled} onChoose={chooseLook}
            onReset={setKinds(BUTTON_KINDS[wall], look, looks.kinds).length ? () => resetWall(wall) : null} onClose={() => setWall(null)}/>
          : <p className="sheet-subtle">{t('episodeLook.pick')}</p>}
      </section>
    </div>
    <footer className="episode-look-foot">
      {error ? <p className="gen-error" role="alert">{error}</p>
        : dirty ? <span className="studio-note warn" role="status">{t('episodeLook.unsaved')}</span>
          : applied ? <span className="studio-note" role="status">{t('episodeLook.applied')}</span> : null}
      <span className="spacer"/>
      {writable && <button type="button" className="primary episode-look-apply" disabled={busy || !dirty} onClick={apply}>{t(busy ? 'episodeLook.applying' : 'episodeLook.apply')}</button>}
    </footer>
  </section>;
}
