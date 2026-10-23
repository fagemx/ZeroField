import { useEffect, useLayoutEffect, useMemo, useState } from 'react';
import { api, ApiError } from './api.js';
import { useLocale } from './i18n/react.jsx';
import { t } from './i18n/index.js';
import { AuthoringWorkspace } from './writing/AuthoringWorkspace.jsx';
import { WritingToolsPanel } from './writing/WritingToolsPanel.jsx';
import { storyRequest } from './storyModel.js';
import { createActorBoundRequest } from './writing/writingTransport.js';

// The episode tab remains the only editable mainline. No ep.scriptContent draft mirror.
const renderTools = props => <WritingToolsPanel {...props}/>;
export function StoryWorld({slug, epId, me, ep, shots = [], loadError, writable, controlRef, onChanged, onStage, onAssets, onVault, onStatus, focusSource, onIdentityLost}) {
  useLocale();
  // Cookies can change in another tab. Never upload this mounted actor's private draft as a new actor.
  const request = useMemo(() => createActorBoundRequest(me.actor_id, async (path, method, body, options) => {
    const current = await api.get(`/projects/api/${slug}`);
    if (current.me.actor_id !== me.actor_id) throw new ApiError(401, t('writing.integration.identityChanged'));
    // The preflight is just an early warning; the server binding closes its TOCTOU window.
    if (options.signal.aborted) throw new DOMException('Writing session disposed', 'AbortError');
    return storyRequest(path, method, body, options);
  }, onIdentityLost), [slug, me.actor_id, onIdentityLost]);
  useLayoutEffect(() => () => request.dispose(), [request]);
  const [styles, setStyles] = useState([]), [settingsError, setSettingsError] = useState('');
  useEffect(() => {let active = true; request('/catalog/styles').then(data => {if (active) setStyles(data.items || []);}).catch(error => {if (active) setSettingsError(error.message);}); return () => {active = false;};}, [request]);
  const setting = async patch => {
    try {
      if (controlRef.current && !await controlRef.current.flush({requireServer:true})) return;
      await request(`/episodes/${epId}/settings`, 'PUT', patch);
      await onChanged?.(); setSettingsError('');
    } catch (error) {setSettingsError(error.message);}
  };
  return <div className="story-world">
    <nav className="writing-world-links" aria-label={t('world.world')}>
      <button type="button" onClick={onAssets}>{t('world.assetWall')}</button>
      <button type="button" onClick={onVault}>{t('story.assetVault')}</button>
    </nav>
    <details className="writing-world-settings"><summary>{t('world.format')}</summary>
      <label>{t('story.aspectRatio')}<select aria-label={t('story.aspectRatio')} disabled={!writable} value={ep?.settings?.aspectRatio || '16:9'} onChange={e => setting({aspectRatio:e.target.value})}>{['16:9','9:16','1:1','21:9'].map(ratio => <option key={ratio}>{ratio}</option>)}</select></label>
      <label>{t('story.style')}<select aria-label={t('story.style')} disabled={!writable} value={ep?.settings?.stylePresetId || '88123'} onChange={e => setting({stylePresetId:e.target.value})}>{styles.map(style => <option key={style.stylePresetId} value={style.stylePresetId}>{style.name}</option>)}</select></label>
      <label>{t('story.breakdownMode')}<select aria-label={t('story.breakdownMode')} disabled={!writable} value={ep?.settings?.breakdownMode || 'auto'} onChange={e => setting({breakdownMode:e.target.value})}>{['auto','scene','cinematic'].map(mode => <option key={mode} value={mode}>{t('story.breakdownMode_' + mode)}</option>)}</select></label>
    </details>
    {(loadError || settingsError) && <p role="alert">{loadError || settingsError}</p>}
    <AuthoringWorkspace slug={slug} epId={epId} me={me} ep={ep} shots={shots} writable={writable}
      request={request} controlRef={controlRef} onChanged={onChanged} onStage={onStage}
      onStatus={onStatus} focusSource={focusSource} renderTools={renderTools}/>
  </div>;
}
