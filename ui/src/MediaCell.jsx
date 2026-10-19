import { useLocale } from './i18n/react.jsx';
import { t as uiText } from './i18n/index.js';
import { useEffect, useState } from 'react';
import { api } from './api.js';
import { mediaOf } from './sheetModel.js';
import { getMediaMeta } from './mediaMeta.js';
import { Icon } from './Icon.jsx';

export function MediaCell({ value, type, label, onLightbox, onRegenerate, onReplace, compact = false }) {
  useLocale();
  const media = mediaOf(value, type);
  const [resolved, setResolved] = useState(null);
  const [info, setInfo] = useState('');
  const [error, setError] = useState('');
  const kind = media?.kind === 'asset' ? (resolved?.url === media.url ? resolved.kind : 'asset') : media?.kind;
  useEffect(() => {
    setInfo(''); setError('');
    if (media?.kind !== 'asset') return;
    let alive = true;
    getMediaMeta(media.url, api.get).then(data => {
      if (alive) setResolved({url: media.url, kind: data.content_type.split('/')[0]});
    }).catch(() => { if (alive) setError(uiText('mediaCell.couldNotLoadMedia')); });
    return () => { alive = false; };
  }, [media?.url, media?.kind]);
  if (!media) return null;
  const metadata = event => {
    const el = event.currentTarget;
    const duration = Number.isFinite(el.duration) ? el.duration.toFixed(1) + ' s' : uiText('mediaCell.stream');
    setInfo(kind === 'video' ? duration + ' · ' + el.videoWidth + ' × ' + el.videoHeight : duration);
  };
  const preview = () => onLightbox?.({ ...media, kind, label, value });
  const video = <video className="media-video-player" src={media.url} controls={!compact} muted loop playsInline preload="metadata"
    onLoadedMetadata={metadata} onError={() => setError(uiText('studio.couldNotPlayVideo'))} />;
  if (compact) return <button type="button" className="media-compact" aria-label={uiText('mediaCell.preview', {v0: label || uiText('mediaCell.media')})} title={error || info || uiText('mediaCell.clickToPreview')} onMouseEnter={event => { event.currentTarget.querySelector('video')?.play()?.catch(() => {}); }} onMouseLeave={event => event.currentTarget.querySelector('video')?.pause()} onClick={event => { event.currentTarget.querySelector('video')?.pause(); preview(); }}>
    {kind === 'image' ? <img src={media.url} alt={label || ''} loading="lazy" onError={() => setError(uiText('studio.couldNotLoadImage'))} />
      : kind === 'video' ? video : kind === 'audio' ? <><audio preload="metadata" src={media.url} onLoadedMetadata={metadata} onError={() => setError(uiText('studio.couldNotPlayAudio'))} /><span className="media-audio"><Icon name="music" size={20} /></span></> : <span>{uiText('mediaCell.loading')}</span>}
    {(info || error) && <small>{error || info}</small>}
  </button>;
  return <div className="media-cell">
    {kind === 'image' ? <button className="media-thumb" onClick={preview}><img src={media.url} alt={label || ''} loading="lazy" onError={() => setError(uiText('studio.couldNotLoadImage'))} /></button>
      : kind === 'video' ? <>{video}<a href={media.url} download>{uiText('mediaCell.downloadAttachment')}</a></>
        : kind === 'audio' ? <audio controls preload="metadata" src={media.url} onLoadedMetadata={metadata} onError={() => setError(uiText('studio.couldNotPlayAudio'))} /> : <small>{uiText('mediaCell.loadingMedia')}</small>}
    {info && <small>{info}</small>}{error && <small role="status">{error}</small>}
    {onReplace && <button onClick={onReplace}>{uiText('mediaCell.replaceUpload')}</button>}
    {['image', 'video'].includes(kind) && onRegenerate && <button onClick={onRegenerate}>{uiText('studio.reshoot')}</button>}
  </div>;
}
