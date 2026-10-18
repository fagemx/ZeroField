# ZeroField Studio — Product & Implementation Specification (`ZEROFIELD_SPEC.md`)

**Repository**: `C:\ai_project\ZeroField`  
**Target Competition**: ComfyUI [Open Source Higgsfield Challenge](https://comfy.org/open-source-higgsfield) (Deadline: **2026-10-30 09:00 PT** / **2026-10-31 00:00 Taipei**)  
**Current Repo Checkpoint**: Commit `9187954` (*English / Traditional Chinese interface* + *OpenBench M8-A–D / ACP / E1*). English remains the first-run default. Backend **245** and frontend **83** tests, the frontend build, and wheel resource verification passed; see [the bilingual baseline receipt](./bilingual-baseline.json). The video and production features below remain implementation targets.

**Interface localization**: Add every new product UI message to both `ui/src/i18n/locales/en.json` and `zh-TW.json`. Use fixed wire values and `normalizeStatus()` for logic, and translated labels only for display. Preserve existing project content and custom agent names when switching languages.

---

## 1. Core Philosophy & Product Strategy

### 1.1 Human Directs, Multi-Tool Agents Execute
Modern visual creators do not restrict themselves to a single tool or a single model. A real production combines **LLM planning agents, CLI coding/automation agents (`ACP stdio`), Comfy SDK / Comfy Router workflows (`FLUX`, `LTX-2.5`, control pipelines), and external media bridges (`bridge`)**.
- **Higgsfield's Bottleneck**: Even with 60+ tools, a creator making a short drama on Higgsfield must manually click 500+ times (`References 0/50`, `Film setup`, `Camera`, `Color palette`, `Lighting`) and dig through 600+ loose files in flat folders.
- **ZeroField's Solution**: Wrap complex multi-tool workflows behind a structured, collaborative studio workspace where **AI agents and workers do the heavy lifting, and the human producer/director manages, inspects, annotates, and approves**.

### 1.2 The Core UX Architecture: Seamless **Macro ↔ Meso ↔ Micro** Switching
The heart of ZeroField's user experience is frictionless navigation across three operational scales—always preserving the active shot/row and asset context:

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ 1. MACRO (巨觀 —的全片統籌與批量交辦)                                          │
│    • Director Brief + Asset Hub (Soul Cast) + Multi-Shot Slate               │
│    • Table / Gallery / Board views + M8 Agent Board (Needs You / Running)    │
│    • Batch-select rows ➔ Assign to Agents or Send to Pipeline                │
└───────────────┬──────────────────────────────────────────────┬───────────────┘
                │ Open Shot(s) in Pipeline                     │ Click Shot Media /
                │ (preserves active row_id & step)             │ Click Annotation
                ▼                                              ▼
┌───────────────────────────────────────┐      ┌───────────────────────────────┐
│ 2. MESO (中觀 — 帶畫面的簡化節點畫布)   │ ◄──► │ 3. MICRO (微觀 — 單鏡對照審片) │
│    • Simplified Visual FlowSurface    │Jump  │    • SheetReview & RaceView   │
│    • Top Shot Switcher (All / S01..)  │with  │    • Side-by-Side (Keyframe / │
│    • Nodes display live thumbnail /   │Row & │      Source Video vs. Output) │
│      inline <video> + Executor badge  │Node  │    • ← / → keyboard shot step │
│      (Agent / ACP CLI / Comfy / Bridge)│     │    • Row Annotation ➔ Agent   │
└───────────────────────────────────────┘      └───────────────────────────────┘
```

### 1.3 Official Competition Rules & Prize Strategy
Per the verified [official rules](https://comfy.org/open-source-higgsfield) and [`docs/HIGGSFIELD_FEATURE_INVENTORY_2026-10-18.md`](./HIGGSFIELD_FEATURE_INVENTORY_2026-10-18.md):
1. **Mandatory Platform Requirement**: Entries **must build on the Comfy Developer Platform (`Comfy Router` and/or `Comfy SDK`)**, while keeping compatibility with local ComfyUI and vendor-neutral bridges.
2. **Prize Stacking Reality**: Each submission can win **1 Main Category Prize** (`Best Overall $10,000`, `Most Innovative RTX 5090`, `Most Viral RTX 5090`, or `Open Weights Only RTX 5090`) **+ 1 Model Provider Bonus Prize** (`LTX $2,000 Cash`, `FLUX 3 Credits`, or `MiniMax H3 Credits`).
3. **Default Open-Weights Workflows + Multi-Tool Extensibility**:
   - Shipped `workflows/*.json` use **100% Open Weights** (`LTX-2.5` core video model + `FLUX` asset/keyframe model + `SAM2 / Depth` controls), qualifying for **Best Overall**, **Open Weights Only**, and the **LTX $2,000 Bonus**.
   - The orchestration engine remains open to any registered tool (`M8 Specialist Agents`, `ACP CLI Agents`, `Comfy Router / SDK`, `Media Bridge`).

### 1.4 Explicit Non-Goals (Do Not Build Now)
- **NO Canvas Mask Painting (`Inpaint Brush`) or Video Frame Extraction (`Extend`) in this phase**: Focus 100% on making **Macro ↔ Meso ↔ Micro** switching, media-bearing flow nodes, inline video playback, and `@Asset` auto-binding rock-solid first.
- **NO Timeline Video Editor (NLE)**: Audio passthrough is handled directly inside the Comfy workflow (`LoadVideo.audio -> VideoCombine.audio`).
- **NO 60 Standalone Mini-App Pages**: Keep all workflows unified inside the `Brief ➔ Asset Hub ➔ Slate / Matrix ➔ Visual Pipeline Canvas` workspace.

---

## 2. Current Codebase Baseline (Already Completed in `ce80b94`)

Do not duplicate or break the following completed foundations:
- **English Studio Baseline & M8 Multi-Agent Engine (`ce80b94`)**:
  - 241 backend tests (`python -m unittest discover -s tests -v`) and 78 frontend tests (`npm test --prefix ui`) pass.
  - `project_docs/doc_schema.py` includes English statuses (`Queued`, `In Progress`, `Rendering Image`, `Rendering Video`, `Pending Review`, `Retake`, `Blocked`, `Approved`) alongside legacy Chinese statuses.
  - `project_docs/templates.py` defines the 5-page `zerofield_studio` template (`director-brief`, `soul-cast`, `cinema-studio`, `openjutsu-lab`, `comfy-pipeline`).
- **Media Upload Validation & HTTP Range Streaming**:
  - `project_docs/media.py:validate()` and `project_docs/service.py:upload_asset()` **already support `video/mp4`, `video/webm`, and `audio/*` up to 64 MB** (`MAX_BYTES = 67108864`).
  - `server.py:send_skillops_bytes()` **already implements HTTP `Range: bytes=start-end` (`206 Partial Content`, `416`, `Accept-Ranges: bytes`, `Content-Range`)** for `video/*` and `audio/*`.

---

## 3. Implementation Tasks (For the Executing Agent)

Execute the following 4 tasks in order. Preserve all existing tests (`tests/test_zerofield_baseline.py`, etc.), and run `npm run build --prefix ui` after any frontend change.

---

### Task 1: Inline Video Playback, Zero-Blob `/meta` & Gallery/Board Video Covers

#### 1.1 Backend: Zero-Blob `/meta` & `304 Not Modified` Short-Circuit
- **File**: `project_docs/repository.py`
  - Below `get_asset()` (around line 740), add `get_asset_meta(connection, slug: str, asset_id: str) -> tuple[str, int] | None`:
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
- **File**: `project_docs/http.py`
  - In `_api()` where `name == "asset_meta"` (around line 495):
    - Replace `repo.get_asset(conn, args[0], args[1])` with `repo.get_asset_meta(conn, args[0], args[1])` and return `{"content_type": found[0], "bytes": found[1]}` (0-byte blob read).
  - In `_api()` where `name == "asset"` (around line 500):
    - If `handler.headers.get("If-None-Match")` matches or contains `f'"{args[1]}"'`, verify existence with `repo.get_asset_meta(conn, args[0], args[1])`, rollback, and return `304 Not Modified` with `ETag: f'"{args[1]}"'` without reading `data` from PostgreSQL.
    - Change the 404 error message from `"Image not found."` to `"Media not found."`.

#### 1.2 Frontend: Inline `<video>` in `MediaCell.jsx` with Hover-to-Play & `META_CACHE`
- **File**: `ui/src/MediaCell.jsx`
  - Add a module-level cache `const META_CACHE = new Map();` (export `clearMediaMetaCache()` for tests) so each `${media.url}/meta` is fetched at most once per session.
  - When `kind === "video"`:
    - **In `compact` mode (table cells, gallery cards, and flow node cards)**:
      - Render `<video className="media-video-thumb" src={media.url} muted loop playsInline preload="metadata" onLoadedMetadata={metadata} onMouseEnter={e => e.currentTarget.play?.().catch(() => {})} onMouseLeave={e => { e.currentTarget.pause?.(); }} onError={() => setError("Could not play video")} />`.
      - Clicking the compact wrapper triggers `onLightbox?.({ ...media, kind, label, value })`.
    - **In full mode (review drawer / lightbox / detail view)**:
      - Render `<video className="media-video-player" src={media.url} controls muted loop playsInline preload="metadata" onLoadedMetadata={metadata} onError={() => setError("Could not play video")} />`.
    - **Regenerate / Re-shoot button**:
      - Enable `onRegenerate` when `(kind === "image" || kind === "video") && onRegenerate`.

#### 1.3 Frontend: Enable Video Covers in `Gallery` & `Board` Views (`sheetViews.js` & `SheetCards.jsx`)
- **File**: `ui/src/sheetViews.js`
  - In `viewColumns(parsed)`: include both `'image'` and `'video'` columns in `coverColumns`:
    ```js
    coverColumns: columns.filter(({index}) => ['image', 'video'].includes(types[index]) || parsed.rows.some(row => ['image', 'video'].includes(mediaOf(row.cells[index]?.value, types[index])?.kind))),
    ```
  - In `sheetViewModel(parsed, visibleRows, preferences)`:
    - Resolve `const colType = parsed.table.attrs.column_types?.[coverColumn] || 'image'; const media = coverColumn < 0 ? null : mediaOf(row.cells[coverColumn]?.value, colType);`
    - Allow `['image', 'video'].includes(media?.kind)` in `cover`:
      `cover: ['image', 'video'].includes(media?.kind) ? {...media, column: coverColumn, value: row.cells[coverColumn].value} : null`
- **File**: `ui/src/SheetCards.jsx`
  - In `card()` (line 13): pass `type={cover.kind || "image"}` instead of hardcoded `type="image"` to `<MediaCell compact ... />`.

---

### Task 2: Seamless **Macro ↔ Meso ↔ Micro** Switching & Media-Bearing Flow Canvas

This task fixes the navigation discontinuities between the project overview/tables (**Macro**), the simplified visual pipeline canvas (**Meso**), and the single-shot review & candidate comparison drawers (**Micro**).

#### 2.1 Macro ➔ Micro / Macro: Fix Row Annotation Jump (`ui/src/App.jsx` & `ui/src/SheetWorkspace.jsx`)
- **Problem**: In `ui/src/App.jsx:pick(a)` (line 302), clicking a row annotation (`a.kind === "row"`, `a.anchor?.rid`) in the top `Annotations` panel only calls `focusAnnotation(a.id)` (which only works on `DocSurface`), doing nothing when the target tab is a `sheet`!
- **Fix**:
  - In `ui/src/App.jsx:pick(a)`: when the target tab has `surface_type === "sheet"` and `a.kind === "row"` with `a.anchor?.rid`, call `setSheetFocus({ tabKey: a.tab_key, rowId: a.anchor.rid, colIndex: 0, openRow: true, nonce: Date.now() })` after navigating to `a.tab_key`.
  - In `ui/src/SheetWorkspace.jsx` (`focusRow` effect around line 44): if `focusRow.openRow` is true, automatically call `setRowOpen(focusRow.rowId); setPanel('row');` so the row's details and annotation thread open immediately.

#### 2.2 Macro / Micro ➔ Meso: Direct Shot-to-Canvas Navigation (`SheetWorkspace.jsx`, `SheetCards.jsx`, `FlowSurface.jsx`)
- **In `ui/src/SheetWorkspace.jsx` & `ui/src/SheetCards.jsx`**:
  - Add a clean `"Open in Pipeline"` action on single rows (in the row detail side panel and in `SheetReview`) that calls `toFlow([row.rid], { sample_row_id: row.rid, capability: ..., col_index: ... })`.
  - In `SheetReview` (around line 270 of `SheetWorkspace.jsx`): fix the regeneration pipeline button so it passes `capability: (types[preview.c] === 'video' || preview.kind === 'video') ? 'video_gen' : 'image_gen'` and `sample_row_id: previewRow.rid` instead of hardcoding `capability: "image_gen"`.
  - In the grid cell renderer (around line 246 of `SheetWorkspace.jsx`): when a media cell (`['image', 'video', 'audio'].includes(types[c])`) is empty (`!media`) and `writable`, render an inline `+ Upload` button calling `pickUpload(r, c)`.
- **In `ui/src/FlowSurface.jsx`**:
  - When `FlowSurface` mounts with a `selection` from `sessionStorage` (`readSelection(window.sessionStorage, slug)`):
    - If `selection.sample_row_id` or `selection.row_ids?.length === 1`, automatically set `sampleRow` to `selection.sample_row_id || selection.row_ids[0]`.
    - If ` redrawStart(definition, selection)` resolves a matching step node ID, automatically select and focus that node (`setSelectedIds([matchedNodeId])`) so the user lands directly on the exact step and shot they clicked from Macro/Micro!

#### 2.3 Meso (中觀): Upgrade `FlowSurface.jsx` & `FlowPanels.jsx` into a Media-Bearing Simplified Studio Canvas
- **Top Active Shot / Sample Switcher (`ui/src/FlowSurface.jsx`)**:
  - In `.flow-canvas-tools` (the top bar of `FlowSurface`), add an **Active Shot / Row Switcher** dropdown (`All Rows (Batch)` vs. individual rows from the primary sheet such as `1 · S01`, `2 · S02`, `3 · S03`) bound to `sampleRow`.
  - Users should not have to dig into the right-hand inspector just to switch which shot (`S01` vs `S02`) they are previewing on the canvas.
- **Media-Bearing Node Cards (`WorkStep` in `ui/src/FlowSurface.jsx` & `flowToCanvas` in `ui/src/flowModel.js`)**:
  - Upgrade `flowToCanvas` and `WorkStep` so each node card on the canvas displays:
    1. **Executor / Tool Badge**: Clearly show whether the step is driven by a **Crew Agent** (`🤖 Cinematographer`), an **ACP CLI** (`⌨️ ACP`), a **Comfy Workflow** (`🎨 Comfy`), or a **Media Bridge** (`🔌 Bridge`).
    2. **Live Media Preview inside the Node Card**:
       - When a `sampleRow` is active (or when the latest task run has an `output.asset_url` or target cell media value for that row/step), render a compact `<MediaCell compact value={nodeMediaUrl} />` **directly inside the `WorkStep` node card on the canvas**!
       - Clicking the media preview inside the node opens a quick lightbox/preview or jumps to the shot (`onOpenSource`), enabling instant **Meso ➔ Micro** and **Meso ➔ Macro** transitions.
- **Inline Media in `FlowPanels.jsx` (`TaskResult`)**:
  - In `ui/src/FlowPanels.jsx` (`TaskResult`, around line 93): when `task.output?.asset_url` is present, render `<MediaCell compact value={task.output.asset_url} />` alongside the link so run results show playable video/image thumbnails directly in the flow panel.

#### 2.4 Micro (微觀): Side-by-Side Context in `SheetReview` & Video Playback in `ProposalRaceView`
- **File**: `ui/src/SheetWorkspace.jsx` (`SheetReview`, around line 269)
  - **Keyboard Shot Stepping (`←` / `→`)**: While `preview` (`SheetReview`) is open and focus is not inside an `<input>` or `<textarea>`, pressing `ArrowLeft` / `ArrowRight` calls `stepPreview(-1)` / `stepPreview(1)` so the director can rapidly review shots `S01 ➔ S02 ➔ S03` in sequence.
  - **Same-Row Companion Media Bar (Input vs. Output Comparison)**:
    - When reviewing a row in `SheetReview` that has multiple media columns (e.g., `Cinema Studio` has `Keyframe` + `Cinema Shot`, and `OpenJutsu Lab` has `Source Driving Video` + `Remastered Video` + `Split-Screen MP4`), display a **Row Media Switcher / Side-by-Side Compare strip** inside `SheetReview` so the director can view `Source Driving Video` and `Remastered Video` (or `Keyframe` and `Cinema Shot`) side-by-side without closing the review drawer!
- **File**: `ui/src/assistant/ProposalRaceView.jsx`
  - In `DiffValue({ value })`: when `media?.kind === 'video'`, render `<video className="race-video" src={media.url} controls muted loop playsInline preload="metadata" />` instead of a download link; when `media?.kind === 'asset'`, render `<MediaCell value={value} />` so M8 multi-agent / multi-take races play candidate videos side-by-side.

---

### Task 3: `@Asset` Auto-Binding, Cinema Studio 4.0 Compiler & Comfy Developer Platform

#### 3.1 `@Asset` Auto-Binding & Structured Prompt Compiler (`project_assistant/limb_worker.py`)
Eliminate the need for humans to manually select references for every shot:
- Add `resolve_studio_context(task: dict) -> dict` in `project_assistant/limb_worker.py`:
  - Reads the active row from `task.get("input", {}).get("structured_rows", [])`.
  - Scans the active row's cells for `@?([A-Z]+-\d+)` asset references (e.g., `@CAST-01`, `CAST-01`, `@SET-01`, `@LOC-01`, `@PROP-01`).
  - Matches those IDs against the `soul-cast` / `assets` table in `task["input"]["tabs"]`, extracting each matched asset's **Reference Image URL** (`/projects/api/.../assets/pa_...`), **Locked Appearance Prompt**, and **Seed** (`seed[:\s]+(\d+)`).
  - Compiles ordered **Optical Rig / Setup** + **Ordered Camera Motion** + **Resolved `@Asset` Appearance Prompts** + **Shot Action & Audio Prompt** into `compiled_prompt`, and returns:
    ```python
    {
        "compiled_prompt": "...",
        "seed": 48291,
        "primary_image_url": "...",       # shot Keyframe URL if present, else primary @CAST/@SET Reference Image URL
        "reference_image_urls": ["..."],  # all resolved @Asset reference image URLs in mention order
        "source_video_url": "...",        # Source Driving Video URL from openjutsu-lab row
        "jutsu_mode": "Motion Transfer",  # or "Object Swap"
    }
    ```

#### 3.2 Quick Preset Chips in Table Edit Strip (`ui/src/SheetWorkspace.jsx`)
- When editing a text cell (`editing`) in `cinema-studio` or `openjutsu-lab`, display clickable preset chips inside `.sheet-edit-strip` based on the column header so humans can adjust parameters with one click (while agents can batch-edit them across rows):
  - **`Optical Rig` column**: `ARRI Alexa 65 / 35mm Anamorphic f/1.4`, `RED V-Raptor / 85mm Prime f/1.8`, `35mm Film / Vintage Anamorphic`, `16mm Bolex Vintage Film`, `DV Camcorder / Clean Sharp`
  - **`Camera Motion` column**: `Slow Dolly Push-In`, `Tracking Shot`, `Static Tripod`, `Handheld Urgency`, `Crane Rise High-Angle`, `Drone Orbit 180°`, `Rack Focus`, `Whip Pan`, `POV`
  - **`Jutsu Mode` column**: `Motion Transfer`, `Object Swap`
  - **Prompt / Reference columns**: Quick `@Asset` chips (`@CAST-01`, `@SET-01`, etc.) dynamically read from the `soul-cast` tab.

#### 3.3 Comfy Developer Platform (`Comfy Router` / `Comfy SDK` + Local ComfyUI) & Workflows
- **File**: `project_assistant/limb_worker.py`
  - Upgrade `comfyui(task, config, head)` (and add `ComfyPlatformClient`) to support:
    1. **Comfy Developer Platform (`platform: "comfy_router" | "comfy_sdk" | "local"`)**: Supports `COMFY_ROUTER_URL` / `COMFY_API_KEY` or `config.get("router_url")` Bearer/API-key headers in addition to local ComfyUI servers.
    2. **`resolve_studio_context(task)` Integration**:
       - Injects `ctx["compiled_prompt"]` into `prompt_node` and `ctx["seed"]` into `seed_node`.
       - Uploads `ctx["primary_image_url"]` to `image_node` and any `ctx["reference_image_urls"]` to `reference_image_node`.
       - **`video_node` Support**: When `config.get("video_node")` is set, uploads `ctx["source_video_url"]` (`video/mp4` or `video/webm`) to `/upload/image` and binds the returned filename to `workflow[str(config["video_node"])]["inputs"][config.get("video_input", "video")]`.
       - **`param_bindings` Support**: Maps configured node/input pairs from `config.get("param_bindings")`.
  - In `ffmpeg()`: add `layout: "side_by_side"` (`hstack` with `-movflags +faststart`) when combining two row videos (`Source Driving Video` + `Remastered Video`), preserving existing concat behavior.
- **Files**: `workflows/`
  - Add 3 clean, open-weights ComfyUI API JSON files:
    1. `workflows/flux3_klein_soul_cast.json`
    2. `workflows/ltx25_cinema_shot.json`
    3. `workflows/ltx25_openjutsu_v2v.json`

---

### Task 4: Pre-Loaded Showcase Assets (`samples/`) & `run_studio.py` Launcher

1. **Preserve `tests/test_zerofield_baseline.py` Compatibility**:
   - Keep `templates.tab_specs("zerofield_studio", ...)` returning empty media cells with `Queued` status on raw calls so `test_studio_template_has_five_english_tabs_and_empty_media_cells` passes without modification.
2. **Create `run_studio.py` & Demo Seeder**:
   - `python run_studio.py --port 3020 --comfy-url http://127.0.0.1:8188` starts the server (with embedded DB when needed), auto-registers built-in workers (`image_gen`, `video_gen`, `media_assemble`), seeds sample media (`samples/`) into the default showcase project if present, and runs the limb worker polling loop in a background thread.

---

## 4. Verification & Acceptance Gates

The executing agent MUST run and pass all of the following before completion:

```powershell
python -m unittest discover -s tests -v
npm test --prefix ui
npm run build --prefix ui
python -m build --wheel
```

Required new unit tests:
1. **Backend (`tests/`)**:
   - `repo.get_asset_meta()` zero-blob query & `http.py` `304 Not Modified` ETag response.
   - `limb_worker.resolve_studio_context()` (`@CAST-01` / `@SET-01` cross-tab resolution + ordered camera/rig prompt compilation).
   - `limb_worker.comfyui()` `video_node`, `reference_image_node`, `param_bindings`, and Comfy Router / SDK headers.
   - `limb_worker.ffmpeg()` `layout="side_by_side"` output with `+faststart`.
2. **Frontend (`ui/tests/`)**:
   - `sheetViews.js` includes `video` columns in `coverColumns` for `Gallery` and `Board` views.
   - `flowModel.js` / `FlowSurface` attaches media previews and executor badges to step nodes.
   - `MediaCell.jsx` caches `/meta` and renders `<video>` for `kind === "video"`.
   - `ProposalRaceView.jsx` renders `<video>` for candidate video takes.
