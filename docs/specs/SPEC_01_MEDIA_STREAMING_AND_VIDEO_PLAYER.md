# SPEC 01 — Media Streaming & Inline Video Player Foundation

**Parent Index**: [`docs/ZEROFIELD_SPEC.md`](../ZEROFIELD_SPEC.md)  
**Order of Execution**: **Step 1 (Foundation)** — Run before `SPEC_02` (Frontend Workspace) and `SPEC_04` (Showcase Seed). Can run in parallel with `SPEC_03` (Backend Worker).  
**Owned Files**:
- `project_docs/repository.py`
- `project_docs/http.py`
- `ui/src/MediaCell.jsx`
- `ui/src/assistant/ProposalRaceView.jsx`
- `tests/test_zerofield_baseline.py` (or `tests/test_media_streaming.py`)
- `ui/tests/` (new media cell & race view tests)

---

## 1. Objective & Scope

Currently, `ZeroField` inherits `OpenBench`'s legacy rule where video assets (`video/mp4`, `video/webm`) are rendered as static download links (`"Video attachment" / "Download attachment"`), and `/projects/api/{slug}/assets/{asset_id}/meta` loads the entire 64 MB `bytea` blob from PostgreSQL into Python memory just to compute `len(data)`.

 Note what is **already implemented** in the current baseline (`ce80b94`) so you do not rewrite it:
- `project_docs/media.py:validate()` and `project_docs/service.py:upload_asset()` **already validate and accept `video/mp4`, `video/webm`, and `audio/*` up to 64 MB**.
- `server.py:send_skillops_bytes()` **already implements HTTP `Range: bytes=start-end` (`206 Partial Content`, `416`, `Accept-Ranges: bytes`, `Content-Range`)** for `video/*` and `audio/*`.

This spec delivers:
1. **Zero-Blob `/meta` SQL lookup** in `repository.py` and `http.py`.
2. **`If-None-Match` (`304 Not Modified`) short-circuit** on `/projects/api/{slug}/assets/{asset_id}`.
3. **Session-level `META_CACHE` + inline `<video>` player** (with Hover-to-Play in compact grids/cards and full controls in review views) in `ui/src/MediaCell.jsx`.
4. **Side-by-side inline `<video>` playback** in `ui/src/assistant/ProposalRaceView.jsx` for M8 multi-agent / multi-take candidate comparisons.

---

## 2. Exact Implementation Requirements

### 2.1 Backend: `project_docs/repository.py` — Add `get_asset_meta()`
In `project_docs/repository.py`, right below `get_asset()` (around line 740):
- `projectops.asset` already stores `byte_size INTEGER NOT NULL` on insert (see `put_asset()`).
- Add:
  ```python
  def get_asset_meta(connection, slug: str, asset_id: str) -> tuple[str, int] | None:
      with connection.cursor() as cursor:
          cursor.execute(
              "SELECT content_type, byte_size FROM projectops.asset WHERE project_slug = %s AND asset_id = %s",
              (slug, asset_id),
          )
          row = cursor.fetchone()
      return (row[0], int(row[1])) if row else None
  ```

### 2.2 Backend: `project_docs/http.py` — Zero-Blob `asset_meta` & `304` on `asset`
In `project_docs/http.py` inside `_api()` (around lines 495–508):
1. **`name == "asset_meta"`**:
   - Replace `found = repo.get_asset(conn, args[0], args[1])` with `found = repo.get_asset_meta(conn, args[0], args[1])`.
   - Return `{"content_type": found[0], "bytes": found[1]}` on 200, or `{"error": "Media not found."}` on 404.
2. **`name == "asset"`**:
   - Check `inm = handler.headers.get("If-None-Match") or ""`.
   - Target ETag is `etag = f'"{args[1]}"'`.
   - If `etag in inm` or `args[1] in inm`:
     - Call `meta = repo.get_asset_meta(conn, args[0], args[1])` and `conn.rollback()`.
     - If not `meta`, return 404 `{"error": "Media not found."}`.
     - Otherwise send `304 Not Modified` with headers `ETag: etag` and `Cache-Control: private, max-age=31536000, immutable` and empty body (0 bytes read from `data` column).
   - If `If-None-Match` does not match, keep the existing `repo.get_asset(conn, args[0], args[1])` + `handler.send_skillops_bytes(200, found[0], found[1], cache_control="private, max-age=31536000, immutable", etag=etag)` flow (which automatically handles `Range` -> `206 Partial Content` in `server.py`), and update the 404 message from `"Image not found."` to `"Media not found."`.

### 2.3 Frontend: `ui/src/MediaCell.jsx` — `META_CACHE`, Inline `<video>`, Hover-to-Play & Video Re-shoot
In `ui/src/MediaCell.jsx`:
1. **Module-level `/meta` Cache**:
   - At module top level, define:
     ```js
     const META_CACHE = new Map();
     export function clearMediaMetaCache() { META_CACHE.clear(); }
     ```
   - When `media?.kind === "asset"`, check `META_CACHE.get(media.url)` first:
     - If cached as a resolved string (e.g., `"video"`, `"image"`, `"audio"`), call `setKind(cached)` synchronously without making a network request.
     - If cached as an in-flight Promise, attach `.then(...)` to reuse the same request.
     - Otherwise store the Promise in `META_CACHE`, and upon resolution store the resolved kind string (`data.content_type.split("/")[0]`). On failure, delete from `META_CACHE` so retries can succeed.
2. **Inline `<video>` in `compact` Mode (`compact === true`)**:
   - Why hover-to-play matters: A table or storyboard gallery may have 20–40 video cells on screen. Chromium limits active hardware video decoders per tab.
   - When `kind === "video"` in `compact` mode, render inside the `<button type="button" className="media-compact" ...>`:
     ```jsx
     <video
       className="media-video-thumb"
       src={media.url}
       muted
       loop
       playsInline
       preload="metadata"
       onLoadedMetadata={metadata}
       onMouseEnter={(e) => { e.currentTarget.play?.().catch(() => {}); }}
       onMouseLeave={(e) => { e.currentTarget.pause?.(); }}
       onError={() => setError("Could not play video")}
     />
     ```
   - Clicking the `<button className="media-compact">` continues to invoke `onLightbox?.({ ...media, kind, label, value })`.
3. **Inline `<video>` in Full Mode (`compact === false`)**:
   - When `kind === "video"` in full mode (used inside `SheetReview`, detail drawers, and lightboxes), replace `<div className="media-file-card">...</div>` with:
     ```jsx
     <video
       className="media-video-player"
       src={media.url}
       controls
       muted
       loop
       playsInline
       preload="metadata"
       onLoadedMetadata={metadata}
       onError={() => setError("Could not play video")}
     />
     ```
   - Also keep a subtle download link or let native `<video controls>` handle playback while allowing `onClick={() => onLightbox?.({ ...media, kind })}` when `onLightbox` is provided.
4. **Enable `onRegenerate` for Video Cells**:
   - Change `{kind === "image" && onRegenerate && ...}` so that **both `kind === "image"` and `kind === "video"`** render the `onRegenerate` button when `onRegenerate` is passed.

### 2.4 Frontend: `ui/src/assistant/ProposalRaceView.jsx` — Inline Video for Multi-Take Candidates
In `ui/src/assistant/ProposalRaceView.jsx`:
- Update `DiffValue({ value })`:
  - Import `MediaCell` from `../MediaCell.jsx`.
  - When `media?.kind === "image"`, keep `<img className="race-image" src={media.url} alt={uiText("proposalRaceView.candidateImage")} />`.
  - When `media?.kind === "video"`, render:
    ```jsx
    <video className="race-video" src={media.url} controls muted loop playsInline preload="metadata" />
    ```
  - When `media?.kind === "asset"`, render `<MediaCell value={value} />` so asset URLs (`/projects/api/{slug}/assets/pa_...`) resolve their MIME type via `META_CACHE` and render as inline `<img>` or `<video>` inside the race comparison dialog!

---

## 3. Verification & Acceptance Criteria

Run and verify:
```powershell
python -m unittest discover -s tests -v
npm test --prefix ui
npm run build --prefix ui
```
1. **Backend Tests**:
   - Verify `repo.get_asset_meta()` returns `(content_type, byte_size)` without reading `data`.
   - Verify `GET /projects/api/{slug}/assets/{asset_id}/meta` returns `200` with `{"content_type": "video/mp4", "bytes": ...}`.
   - Verify `GET /projects/api/{slug}/assets/{asset_id}` with matching `If-None-Match: "pa_..."` returns `304 Not Modified` with empty body.
2. **Frontend Tests & Build**:
   - Verify `MediaCell` renders `<video>` when `kind === "video"` (both compact and full modes), caches `/meta` across multiple mounts of the same `pa_...` asset URL, and exposes `onRegenerate` for both images and videos.
   - Verify `ProposalRaceView` renders `<video>` for candidate video takes.
   - Run `npm run build --prefix ui` and confirm `static/projects/` updates cleanly.
