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
    api.get(`${media.url}/meta`).then((data) => { if (alive) setKind(data.content_type.split("/")[0]); }).catch(() => { if (alive) setError("媒體讀取失敗"); });
    return () => { alive = false; };
  }, [media?.url, media?.kind]);
  if (!media) return null;
  const metadata = (event) => {
    const el = event.currentTarget;
    const duration = Number.isFinite(el.duration) ? `${el.duration.toFixed(1)} 秒` : "串流";
    setInfo(kind === "video" ? `${duration} · ${el.videoWidth} × ${el.videoHeight}` : duration);
  };
  if (compact) return <button type="button" className="media-compact" aria-label={`預覽${label || "媒體"}`} title={error || info || "點擊預覽"} onClick={() => onLightbox?.({ ...media, kind, label, value })}>
    {kind === "image" ? <img src={media.url} alt={label} loading="lazy" onError={() => setError("圖片讀取失敗")} />
      : kind === "video" ? <><span className="media-file-icon">▤</span><span>影片附件</span></>
        : kind === "audio" ? <><audio preload="metadata" src={media.url} onLoadedMetadata={metadata} onError={() => setError("音訊無法播放")} /><span className="media-audio">♫</span></> : <span>讀取中</span>}
    {(info || error) && <small>{error || info}</small>}
  </button>;
  return <div className="media-cell">
    {kind === "image" ? <button className="media-thumb" onClick={() => onLightbox({ ...media, kind })}><img src={media.url} alt={label} loading="lazy" onError={() => setError("圖片讀取失敗")} /></button>
      : kind === "video" ? <div className="media-file-card"><span className="media-file-icon">▤</span><strong>{label || "影片附件"}</strong><a href={media.url} download>下載附件 ↗</a></div>
        : kind === "audio" ? <audio controls preload="metadata" src={media.url} onLoadedMetadata={metadata} onError={() => setError("音訊無法播放")} /> : <small>讀取媒體…</small>}
    {info && <small>{info}</small>}{error && <small role="status">{error}</small>}
    {onReplace && <button onClick={onReplace}>上傳替換</button>}
    {kind === "image" && onRegenerate && <button onClick={onRegenerate}>✦ 重抽此格圖片</button>}
  </div>;
}
