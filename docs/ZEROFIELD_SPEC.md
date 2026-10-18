# ZeroField Studio — Product & Implementation Specification (`ZEROFIELD_SPEC.md`)

**Repository**: `C:\ai_project\ZeroField`  
**Target Competition**: ComfyUI [Open Source Higgsfield Challenge](https://comfy.org/open-source-higgsfield) (Deadline: **2026-10-30 09:00 PT** / **2026-10-31 00:00 Taipei**)  
**Current Repo Checkpoint**: Commit `ce80b94` (*English ZeroField contest baseline* + *OpenBench M8-A–D multi-agent orchestration*).

---

## 0. Modular Spec Index & Agent Dispatch Map (`docs/specs/`)

To allow clean, parallel, conflict-free execution by one or more coding agents, the implementation is split into **5 modular specifications** with strict file ownership boundaries:

| Spec Document | Scope & Focus | Owned Files | Execution Order |
| :--- | :--- | :--- | :--- |
| **[`docs/specs/SPEC_01_MEDIA_STREAMING_AND_VIDEO_PLAYER.md`](./specs/SPEC_01_MEDIA_STREAMING_AND_VIDEO_PLAYER.md)** | Zero-Blob `/meta`, `304 Not Modified`, `META_CACHE`, inline `<video>` in `MediaCell.jsx` & `ProposalRaceView.jsx` | `project_docs/repository.py`, `project_docs/http.py`, `ui/src/MediaCell.jsx`, `ui/src/assistant/ProposalRaceView.jsx` | **Step 1 (Foundation)** |
| **[`docs/specs/SPEC_02_MACRO_MESO_MICRO_WORKSPACE.md`](./specs/SPEC_02_MACRO_MESO_MICRO_WORKSPACE.md)** | **Macro ↔ Meso ↔ Micro** in-place switching, `Studio Assistant` coexistence, `runInPlace` execution, Meso visual chain cards, Micro side-by-side review & `FlowSurface` pipeline manager | `ui/src/App.jsx`, `ui/src/SheetWorkspace.jsx`, `ui/src/sheetViews.js`, `ui/src/SheetCards.jsx`, `ui/src/FlowSurface.jsx`, `ui/src/FlowPanels.jsx`, `ui/src/flowModel.js` | **Step 2A (Frontend UX)** *(After `SPEC_01`; parallel with `SPEC_03`)* |
| **[`docs/specs/SPEC_03_ASSET_BINDING_AND_COMFY_PLATFORM.md`](./specs/SPEC_03_ASSET_BINDING_AND_COMFY_PLATFORM.md)** | **Flexible Reference Pack Prep** (`extract_frame` for 1st frame, `motion_structure` for continuous action structure video, `@Asset` auto-binding, `anchor_keyframe`) + **Universal External ComfyUI JSON Slot Binder** (`bind_external_workflow` + `ComfyPlatformClient`) | `project_assistant/limb_worker.py`, `workflows/*.json`, `tests/test_studio_worker.py` | **Step 2B (Backend Worker)** *(Zero file overlap with `SPEC_01` & `SPEC_02` — can run in parallel!)* |
| **[`docs/specs/SPEC_04_SHOWCASE_SEED_AND_LAUNCHER.md`](./specs/SPEC_04_SHOWCASE_SEED_AND_LAUNCHER.md)** | Pre-loaded showcase assets (`samples/`), `seed_showcase_media`, and one-command launcher `run_studio.py` | `run_studio.py`, `samples/*`, `README.md`, `tests/test_run_studio.py` | **Step 3 (Integration)** *(After `SPEC_01`–`SPEC_03`)* |
| **[`docs/specs/SPEC_05_DUAL_ENGINE_ALIGNMENT_AND_LINEWORLDS.md`](./specs/SPEC_05_DUAL_ENGINE_ALIGNMENT_AND_LINEWORLDS.md)** | **Self-Hosted RunningHub Card Engine** (`workflows/cards/*.json`, `nodeInfoList`, `slot_plan`, `disabled_loras`, `"None"` unlinking, 8-frame `frame_sheet`, `.bounded.mp4` duration trim, `@source` 2-pass optimize) + **Dual-Engine Alignment** (`MiniMax H3 Ref2VA + H3-Context-IR` & `LTX-2.5 IC-LoRA + Ingredients Sheet`, `32px` & `8n+1`/`17n+5`) + **`line-worlds` Procedural Motion Structure** (`layout_silhouette`, `sparse_tracks`, `time_strata`) | `project_assistant/limb_worker.py`, `workflows/cards/*.json`, `workflows/minimax_h3_ref2va.json`, `workflows/ltx25_*.json`, `tests/test_studio_worker.py` | **Step 4 (RunningHub Card Engine & `line-worlds` Upgrade)** *(After `SPEC_03`)* |

---

## 1. Core Philosophy & Product Architecture

### 1.1 Multi-Tool Agent Collaboration (Human Directs, Agents Execute)
Real visual creators do not limit themselves to a single tool or a single model. ZeroField is designed around `OpenBench`'s core premise:
- **Agents and heterogeneous workers do the heavy lifting**: M8 specialist agents (`Showrunner`, `Screenwriter`, `Cinematographer`, `Continuity Supervisor`), external CLI agents (`ACP stdio`), Comfy Developer Platform workflows (`Comfy Router` / `Comfy SDK` / local ComfyUI), and vendor-neutral media bridges (`bridge()`) work in parallel.
- **Humans manage, review, annotate, and decide**: Instead of manually clicking 500 times in a single-shot prompt box and sorting through 600 loose files like on Higgsfield, the human director moves fluidly across **Macro (巨觀)**, **Meso (中觀)**, and **Micro (微觀)** views to steer the production.

### 1.2 Role of `FlowSurface` vs. Daily Editing Views
Code audit of `ui/src/FlowSurface.jsx`, `ui/src/flowModel.js`, and `project_docs/templates.py` revealed why forcing users to jump to `FlowSurface` for everyday shot editing breaks the user experience:
1. **`FlowSurface` (`Comfy Pipeline` tab) is the Pipeline Management Surface (管線架構管理台)**:
   - Its nodes operate across **different tables and different `row_id` spaces** (`director-brief` ➔ `soul-cast` ➔ `cinema-studio` ➔ `openjutsu-lab`).
   - Therefore, `FlowSurface` should be used to **configure pipeline stages, bind workers/agents, and inspect pipeline-level runs**—NOT as a mandatory detour every time a user wants to generate or re-shoot a single shot!
2. **Everyday Creative Editing (`Macro ↔ Meso ↔ Micro`) Happens In-Place Within Each Production Sheet (`Soul Cast`, `Cinema Studio`, `OpenJutsu Lab`)**:
   - Users switch between **Macro (`Table` / `Board`)**, **Meso (`Gallery / Storyboard Visual Chain`)**, and **Micro (`Unified Shot Review & Inspector`)** **within the same tab in 0 seconds, without losing context and without closing the right-hand `Studio Assistant`!**

```text
┌───────────────────────────────────────────────────────────────────────────────────┐
│                   IN-PLACE 3-TIER EDITING & REVIEW WORKSPACE                      │
│              (Inside Cinema Studio / OpenJutsu Lab / Soul Cast)                   │
├───────────────────────────────────────────────────────────────────────────────────┤
│                                                                                   │
│  1. MACRO (巨觀 — 全片場記與批量交辦: Table View & Status Board View)              │
│     • Manage all 20–50 shots, @Asset bindings, Optical Rigs, statuses & notes     │
│     • Batch-select rows ➔ "Assign to Agent" OR "Run Selected Shots" IN-PLACE      │
│       (calls /flow/preflight + /flow/runs in background; NO forced tab jump!)     │
│                                        │                                          │
│                                        ▼ 0-second view switch (same tab)          │
│  2. MESO (中觀 — 帶畫面的視覺分鏡鏈路牆: Storyboard / Visual Chain Gallery View)   │
│     • Each shot card renders its complete visual chain side-by-side:              │
│       - Cinema Studio: [@CAST/@SET Thumbnails] ──► [Keyframe] ──► [Shot <video>]  │
│       - OpenJutsu Lab: [Source <video>] + [@CAST Thumbnail] ──► [Remastered <video>]│
│     • Hover-to-play video previews, quick status change, and 1-click re-shoot     │
│                                        │                                          │
│                                        ▼ Click any shot card / row / annotation   │
│  3. MICRO (微觀 — 單鏡對照審片與指揮台: Unified Shot Review & Detail Inspector)    │
│     • Coexists with right-hand Studio Assistant & Annotations (NEVER auto-closes!)│
│     • ← Prev Shot / Next Shot → stepping (keyboard ArrowLeft / ArrowRight)        │
│     • Side-by-side visual chain for the active shot:                              │
│       [@Asset References] + [Keyframe / Source Video] ◄──► [Output Video Player]  │
│     • Direct in-place [Upload], [✦ Generate / Re-shoot], Preset Chips,            │
│       Version History diff, and Row Annotation (@Agent auto-routing)              │
│                                                                                   │
└────────────────────────────────────────┬──────────────────────────────────────────┘
                                         │ Optional: "Manage Pipeline"
                                         ▼
┌───────────────────────────────────────────────────────────────────────────────────┐
│  PIPELINE MANAGEMENT (`Comfy Pipeline` / `FlowSurface.jsx`)                       │
│  • Configure multi-tool DAG stages (Crew Agents / ACP CLI / Comfy SDK / Bridges)  │
│  • Nodes show Executor Badge + latest output thumbnail/video preview              │
└───────────────────────────────────────────────────────────────────────────────────┘
```

### 1.3 Official Competition Rules & Prize Strategy
Per the verified [official rules](https://comfy.org/open-source-higgsfield) and [`docs/HIGGSFIELD_FEATURE_INVENTORY_2026-10-18.md`](./HIGGSFIELD_FEATURE_INVENTORY_2026-10-18.md):
1. **Mandatory Platform Requirement**: Entries **must build on the Comfy Developer Platform (`Comfy Router` and/or `Comfy SDK`)**, while retaining support for local ComfyUI and external bridges.
2. **Prize Stacking Reality**: Each submission can win **1 Main Category Prize** (`Best Overall $10,000`, `Most Innovative RTX 5090`, `Most Viral RTX 5090`, or `Open Weights Only RTX 5090`) **+ 1 Model Provider Bonus Prize** (`LTX $2,000 Cash`, `FLUX 3 Credits`, or `MiniMax H3 Credits`).
3. **Default Open-Weights Workflows**:
   - Shipped `workflows/*.json` use **100% Open Weights** (`LTX-2.5` core video model + `FLUX` asset/keyframe model + `SAM2 / Depth` controls), qualifying for **Best Overall**, **Open Weights Only**, and the **LTX $2,000 Bonus**.

### 1.4 Explicit Non-Goals (Do Not Build in This Phase)
- **NO Canvas Mask Painting (`Inpaint Brush`) or Video Frame Extraction (`Extend`)**: Deferred so engineering focus stays 100% on **Macro ↔ Meso ↔ Micro** switching, inline video playback, `@Asset` auto-binding, and Comfy SDK/Router workflows.
- **NO Timeline Video Editor (NLE)**: Audio passthrough is handled directly inside the Comfy workflow (`LoadVideo.audio -> VideoCombine.audio`).

---

## 2. Current Codebase Baseline (Already Completed in `ce80b94`)

Do not duplicate or break these completed foundations:
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

### Task 1: Inline Video Playback & Zero-Blob `/meta` Foundation

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
  - Add a module-level cache `const META_CACHE = new Map();` (and export `clearMediaMetaCache()` for unit tests) so each `${media.url}/meta` is fetched at most once per session.
  - When `kind === "video"`:
    - **In `compact` mode (table cells, Meso storyboard cards, and flow node previews)**:
      - Render `<video className="media-video-thumb" src={media.url} muted loop playsInline preload="metadata" onLoadedMetadata={metadata} onMouseEnter={e => e.currentTarget.play?.().catch(() => {})} onMouseLeave={e => { e.currentTarget.pause?.(); }} onError={() => setError("Could not play video")} />`.
      - Clicking the compact button triggers `onLightbox?.({ ...media, kind, label, value })`.
    - **In full mode (Micro review / lightbox / candidate race comparison)**:
      - Render `<video className="media-video-player" src={media.url} controls muted loop playsInline preload="metadata" onLoadedMetadata={metadata} onError={() => setError("Could not play video")} />`.
    - **Regenerate / Re-shoot button**:
      - Enable `onRegenerate` when `(kind === "image" || kind === "video") && onRegenerate`.

---

### Task 2: Re-Architecting **Macro ↔ Meso ↔ Micro** Switching & Pipeline Management

This task fixes the 4 structural UX discontinuities identified in code audit so creators can move seamlessly between **Macro (Table/Board)**, **Meso (Visual Chain Gallery)**, **Micro (Unified Shot Review)**, and **`Studio Assistant`**, while keeping `FlowSurface` as a clean pipeline manager.

#### 2.1 Fix Discontinuity #1: Coexistence of Micro Shot View & Right-Hand `Studio Assistant`
- **Problem**: `ui/src/SheetWorkspace.jsx` line 42 has:
  ```js
  useEffect(()=>{if(assistantOpen){setPanel(null);setPreview(null);setRequest(null);}},[assistantOpen]);
  ```
  This forcefully closes the user's open shot review (`preview`) or row detail (`panel`) whenever they open `Studio Assistant` or `Annotations`!
- **Fix in `ui/src/SheetWorkspace.jsx`**:
  - **Do NOT close `preview` or `panel === 'row'` when `assistantOpen` becomes true!** Only close transient popovers if needed, so a director can keep a shot (`S02`) open in Micro Review on the left/center while chatting with an agent or reviewing candidate proposals in `Studio Assistant` on the right.

#### 2.2 Fix Discontinuity #2: In-Place Pipeline Execution (No Forced 6-Step Tab Jump to `FlowSurface`)
- **Problem**: Currently, clicking `Run Pipeline` on selected rows or `Review regeneration pipeline` in `SheetReview` writes to `sessionStorage` and sets `window.location.hash = workflow`, kicking the user out of `Cinema Studio` / `OpenJutsu Lab` into `Comfy Pipeline` just to run a shot!
- **Fix in `ui/src/SheetWorkspace.jsx`**:
  - Add an **in-place execution helper `runInPlace(rowIds, options = {})`** in `SheetSurface`:
    1. Fetches the flow definition from `/projects/api/${slug}/tabs/${flowKey}/flow`.
    2. Finds the matching step node (`redrawStart(definition, { target_tab: tab.key, row_ids: rowIds, ...options })` or the first node whose `row_source.tab_key === tab.key` or `target.tab_key === tab.key`).
    3. Calls `POST /projects/api/${slug}/tabs/${flowKey}/flow/preflight` and, if `preflight.ready` is true, immediately calls `POST /projects/api/${slug}/tabs/${flowKey}/flow/runs` **in the background** and shows a toast (`"Queued for execution — progress will update automatically"`), keeping the user right on their current `Cinema Studio` / `OpenJutsu Lab` page!
    4. If `preflight.ready` is false (e.g., no compatible worker is connected yet), display a clear actionable error with an optional `"Open Pipeline Settings"` link (`toFlow`) so the user only visits `FlowSurface` when pipeline configuration is actually needed.

#### 2.3 Fix Discontinuity #3: Upgrade **Meso (中觀)** — Visual Shot Chain Cards in `Gallery` & `Board` (`sheetViews.js` & `SheetCards.jsx`)
- **Problem**: Currently, `ui/src/sheetViews.js` only extracts a single `image` column as `cover` (ignoring `video` columns completely, and hiding the shot's input-to-output progression).
- **Fix in `ui/src/sheetViews.js` & `ui/src/SheetCards.jsx`**:
  1. **Support both `image` and `video` columns in `coverColumns`**:
     - In `viewColumns(parsed)`:
       ```js
       coverColumns: columns.filter(({index}) => ['image', 'video'].includes(types[index]) || parsed.rows.some(row => ['image', 'video'].includes(mediaOf(row.cells[index]?.value, types[index])?.kind))),
       ```
     - In `sheetViewModel(parsed, visibleRows, preferences)`:
       - Resolve `cover` using the column's actual media kind (`['image', 'video'].includes(media?.kind)`).
       - Also attach **`mediaChain`** to each card item: an array of all media columns in that row (`{ column: c, label: parsed.headers[c], type: types[c], value: cell.value, media: mediaOf(cell.value, types[c]) }`) plus any **resolved `@Asset` reference thumbnails** from the `soul-cast` tab (when passed or available).
  2. **Render the Visual Shot Chain in `SheetCards.jsx` (Meso View)**:
     - When a card has multiple media stages (e.g., `Cinema Studio` has `Keyframe` + `Cinema Shot`, or `OpenJutsu Lab` has `Source Driving Video` + `Remastered Video`), render a **horizontal Visual Chain strip** at the top of the card (`[Keyframe / Source Video] ──► [Cinema Shot / Remastered Video]`, plus `@Asset` badges) using `<MediaCell compact type={stage.type} ... />`!
     - If a stage is empty and `writable`, allow clicking it to upload or trigger in-place generation.

#### 2.4 Fix Discontinuity #4: Unify **Micro (微觀)** — Single-Shot Side-by-Side Review, Preset Chips & Row Annotation Jump
- **Row Annotation Jump (`ui/src/App.jsx` & `ui/src/SheetWorkspace.jsx`)**:
  - In `ui/src/App.jsx:pick(a)` (line 302): when `a.kind === "row"` and `a.anchor?.rid` targets a `sheet` tab, call `setSheetFocus({ tabKey: a.tab_key, rowId: a.anchor.rid, colIndex: 0, openRow: true, nonce: Date.now() })` after navigating to `a.tab_key`.
  - In `ui/src/SheetWorkspace.jsx`: when `focusRow?.openRow` is true, open the Micro view for that row automatically.
- **Unified Micro Shot View (`SheetReview` in `ui/src/SheetWorkspace.jsx`)**:
  - **Keyboard Shot Stepping (`←` / `→`)**: When `preview` (`SheetReview`) is open and focus is not inside an `<input>`, `<textarea>`, or `<select>`, pressing `ArrowLeft` / `ArrowRight` calls `stepPreview(-1)` / `stepPreview(1)` to step smoothly through shots `S01 ➔ S02 ➔ S03`.
  - **Side-by-Side Shot Media Chain in `SheetReview`**:
    - Instead of showing only a single isolated cell in `SheetReview`, display **all media stages of `previewRow` side-by-side** (e.g., `Keyframe` alongside `Cinema Shot`, or `Source Driving Video` alongside `Remastered Video`, plus any `@CAST-01` / `@SET-01` reference thumbnails resolved from `soul-cast`), with individual `[Replace / Upload]` and in-place `[✦ Generate / Re-shoot]` buttons on each stage!
  - **Inline Row Fields & Quick Preset Chips**:
    - Allow editing the shot's key text fields (`Optical Rig`, `Camera Motion`, `Jutsu Mode`, `Action & Audio Prompt`) directly inside the Micro view or table edit strip (`.sheet-edit-strip`) with one-click preset chips:
      - **`Optical Rig`**: `ARRI Alexa 65 / 35mm Anamorphic f/1.4`, `RED V-Raptor / 85mm Prime f/1.8`, `35mm Film / Vintage Anamorphic`, `16mm Bolex Vintage Film`, `DV Camcorder / Clean Sharp`
      - **`Camera Motion`**: `Slow Dolly Push-In`, `Tracking Shot`, `Static Tripod`, `Handheld Urgency`, `Crane Rise High-Angle`, `Drone Orbit 180°`, `Rack Focus`, `Whip Pan`, `POV`
      - **`Jutsu Mode`**: `Motion Transfer`, `Object Swap`
      - **`@Asset` Chips**: Dynamically list `@CAST-01`, `@SET-01`, etc. from the `soul-cast` tab for 1-click insertion.
- **Multi-Take Video Playback in `ProposalRaceView.jsx`**:
  - In `ui/src/assistant/ProposalRaceView.jsx`: update `DiffValue` so `media?.kind === 'video'` renders `<video className="race-video" src={media.url} controls muted loop playsInline preload="metadata" />` and `media?.kind === 'asset'` renders `<MediaCell value={value} />`.

#### 2.5 Clean Up `FlowSurface` (`Comfy Pipeline`) as Pipeline Manager
- **File**: `ui/src/FlowSurface.jsx`, `ui/src/FlowPanels.jsx`, `ui/src/flowModel.js`
  - Show an **Executor Badge** on each `WorkStep` node card (`🤖 Agent`, `⌨️ ACP CLI`, `🎨 Comfy`, `🔌 Bridge`) and render `<MediaCell compact value={latestAssetUrl} />` when a run task for that node has produced an `output.asset_url`.
  - In `FlowPanels.jsx` (`TaskResult`): render `<MediaCell compact value={task.output.asset_url} />` alongside the download link.

---

### Task 3: Flexible Reference Pack Prep (`First Frame` + `Motion Structure` + `@Asset`) & Universal External JSON Slot Binder

See full details in **[`docs/specs/SPEC_03_ASSET_BINDING_AND_COMFY_PLATFORM.md`](./specs/SPEC_03_ASSET_BINDING_AND_COMFY_PLATFORM.md)**.

#### 3.1 Built-In Reference Media Prep Modes (`project_assistant/limb_worker.py:ffmpeg()`)
- Before calling an external ComfyUI JSON, the platform prepares and manages the required conditioning/reference assets directly in the sheet:
  1. **`mode: "extract_frame"` (`First Frame` Extraction)**: Extracts frame 0 (or `timestamp_sec`) from `Source Driving Video` as a lossless PNG image asset (`first_frame.png`) so the pose/composition of frame 1 can be combined with `@CAST-01` to produce an inspectable `Anchor / Swapped Keyframe`.
  2. **`mode: "motion_structure"` (`Continuous Motion Structure Video` Prep)**: Converts `Source Driving Video` into a continuous motion/structure conditioning MP4 (`structure_type: "edge_lineart" | "luma_depth" | "frame_diff"`, with `-movflags +faststart`) for frame-by-frame motion control.
  3. **`layout: "side_by_side"`**: Combines `Source Driving Video` and `Remastered Video` into a split-screen comparison MP4.

#### 3.2 Standardized Reference Pack Assembler (`resolve_studio_context(task) -> dict`)
- Assembles a complete **`Reference Pack`** for any shot or remix row:
  - `source_video`, `first_frame`, `motion_structure_video`, `anchor_keyframe`, `primary_image_url`
  - `asset_images` & `asset_map` (auto-resolved from `@CAST-01`, `@SET-01`, `@PROP-01` in the `soul-cast` tab)
  - `compiled_prompt` (ordered `Optical Rig` + `Camera Motion` + `Jutsu Mode` + `@Asset` prompts + `Action Prompt`) & `seed`

#### 3.3 Universal External ComfyUI JSON Slot Binder (`bind_external_workflow` + `ComfyPlatformClient`)
- Treats any ComfyUI workflow JSON as an **external workflow file** managed by the project—never hardcoding internal node structures.
- Maps any key or dot-path from the Reference Pack (`anchor_keyframe`, `first_frame`, `motion_structure_video`, `source_video`, `asset_images.0`, `compiled_prompt`, `seed`) into arbitrary `(node_id, input_name)` slots via `input_bindings` (plus full backward compatibility with `image_node`, `reference_image_node`, `video_node`, `param_bindings`), automatically uploading bound image/video assets via `ComfyPlatformClient`.

---

### Task 4: Pre-Loaded Showcase Assets (`samples/`) & `run_studio.py` Launcher

1. **Preserve `tests/test_zerofield_baseline.py` Compatibility**:
   - Keep `templates.tab_specs("zerofield_studio", ...)` returning empty media cells with `Queued` status on raw calls and keep the 5-node structure in `templates.flow_specs("zerofield_studio")` so `tests/test_zerofield_baseline.py` passes 100%.
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
   - `sheetViews.js` includes `video` columns in `coverColumns` and builds `mediaChain` for Meso storyboard cards.
   - `SheetWorkspace` preserves `preview` / `panel` when `assistantOpen` is true (Macro/Micro + Assistant coexistence).
   - `MediaCell.jsx` caches `/meta` and renders `<video>` for `kind === "video"`.
   - `ProposalRaceView.jsx` renders `<video>` for candidate video takes.
