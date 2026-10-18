import { useEffect, useState } from "react";
import { api } from "./api.js";
import { mediaOf } from "./sheetModel.js";

export function MediaCell({ value, type, label, onLightbox, onRegenerate, onReplace, compact = false }) {
  const media = mediaOf(value, type);
  const [kind, setKind] = useState(media?.kind);
  const [info, setInfo] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    setKind(media?.kind); setInfo(""); setError("");
    if (media?.kind !== "asset") return;
    let alive = true;
    api.get(`${media.url}/meta`).then((data) => { if (alive) setKind(data.content_type.split("/")[0]); }).catch(() => { if (alive) setError("Could not load media"); });
    return () => { alive = false; };
  }, [media?.url, media?.kind]);
  if (!media) return null;
  const metadata = (event) => {
    const el = event.currentTarget;
    const duration = Number.isFinite(el.duration) ? `${el.duration.toFixed(1)} s` : "Stream";
    setInfo(kind === "video" ? `${duration} · ${el.videoWidth} × ${el.videoHeight}` : duration);
  };
  if (compact) return <button type="button" className="media-compact" aria-label={`Preview${label || "Media"}`} title={error || info || "Click to preview"} onClick={() => onLightbox?.({ ...media, kind, label, value })}>
    {kind === "image" ? <img src={media.url} alt={label} loading="lazy" onError={() => setError("Could not load image")} />
      : kind === "video" ? <><span className="media-file-icon">▤</span><span>Video Attachment</span></>
        : kind === "audio" ? <><audio preload="metadata" src={media.url} onLoadedMetadata={metadata} onError={() => setError("Could not play audio")} /><span className="media-audio">♫</span></> : <span>Loading</span>}
    {(info || error) && <small>{error || info}</small>}
  </button>;
  return <div className="media-cell">
    {kind === "image" ? <button className="media-thumb" onClick={() => onLightbox({ ...media, kind })}><img src={media.url} alt={label} loading="lazy" onError={() => setError("Could not load image")} /></button>
      : kind === "video" ? <div className="media-file-card"><span className="media-file-icon">▤</span><strong>{label || "Video Attachment"}</strong><a href={media.url} download>Download Attachment ↗</a></div>
        : kind === "audio" ? <audio controls preload="metadata" src={media.url} onLoadedMetadata={metadata} onError={() => setError("Could not play audio")} /> : <small>Loading media…</small>}
    {info && <small>{info}</small>}{error && <small role="status">{error}</small>}
    {onReplace && <button onClick={onReplace}>Replace Upload</button>}
    {kind === "image" && onRegenerate && <button onClick={onRegenerate}>✦ Regenerate Image</button>}
  </div>;
}
