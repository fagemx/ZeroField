# SPEC 06 — Self-Hosted RH STORY AI Drama Workbench (`/aivideo/open/v1`) & Macro ↔ Meso ↔ Micro Integration

**Parent Index**: [`docs/ZEROFIELD_SPEC.md`](../ZEROFIELD_SPEC.md)  
**Prerequisite Baselines**:
- [`docs/specs/SPEC_02_MACRO_MESO_MICRO_WORKSPACE.md`](./SPEC_02_MACRO_MESO_MICRO_WORKSPACE.md) (Macro ↔ Meso ↔ Micro UI switching)
- [`docs/specs/SPEC_05_DUAL_ENGINE_ALIGNMENT_AND_LINEWORLDS.md`](./SPEC_05_DUAL_ENGINE_ALIGNMENT_AND_LINEWORLDS.md) (Self-Hosted RunningHub `/openapi/v2` Card Engine & `nodeInfoList` Injector)  
**Reference Specification Audited**:
- [`docs/references/runninghub-open-api-2026-10-18/`](../references/runninghub-open-api-2026-10-18/README.md) (`openapi.json`, `API_REFERENCE.md`, `endpoints.json`, `guides/*.txt`, `web-pages/*.txt` — 15 functional groups, 75 paths, 98 operations from `https://story.runninghub.ai/aivideo/open/v1`)
- [`docs/references/open-source-lock.json`](../references/open-source-lock.json) (`baserow`, `teable`, `activepieces`, `affine`, `windmill`, `xyflow`, `univer`)  
**Order of Execution**: **Step 5 (After `SPEC_05` — Unifies Lower-Layer `/openapi/v2` ComfyUI Card Engine with Upper-Layer `/aivideo/open/v1` Drama Workbench & Macro/Meso/Micro UI)**  
**Owned Files**:
- **Backend**:
  - `project_docs/story_openapi.py` *(new module — implements `/aivideo/open/v1/*` RH STORY OpenAPI v1 server & bidirectional mapping to ZeroField projects/tabs)*
  - `project_docs/runtime_http.py` *(mount `/aivideo/open/v1/` dispatcher alongside `/openapi/v2/`)*
  - `project_assistant/limb_worker.py` *(connect `appCode` catalog, `ASSET_EXTRACT`, `STORYBOARD_GENERATE`, `SHOT_IMAGE_GENERATE`, `SHOT_VIDEO_GENERATE`, and `FILM_EXPORT` tasks to local ComfyUI cards + FFmpeg)*
- **Frontend**:
  - `ui/src/Surfaces.jsx` & `ui/src/App.jsx` *(5-module RH STORY Top Bar: `Start Creating`, `Toolbox`, `My Projects`, `Asset Vault`, `Open API`)*
  - `ui/src/StoryWorkbenchModals.jsx` *(new component — Quick Script Import/Confirm modal, Toolbox Card Manager/Importer, Asset Variant Drawer, Open API Playground)*
  - `ui/src/SheetWorkspace.jsx`, `ui/src/SheetCards.jsx`, `ui/src/SheetReview.jsx`, `ui/src/studioModel.js`, `ui/src/sheetViews.js` *(Macro Script Baseline Lock & Film Export bar; Meso Scene Grouping & `@CAST-01:variant` chips; Micro Candidate Take History, Split/Merge Shot, & `nodeInfoList` Override Inspector)*
  - `ui/src/i18n/locales/en.json` & `ui/src/i18n/locales/zh-TW.json` *(bilingual semantic keys; English default, Traditional Chinese selectable)*
- **Tests**:
  - `tests/test_story_openapi.py` *(new backend test suite verifying RH STORY `/aivideo/open/v1/*` contract, envelope, idempotency, stage locks, and bidirectional sheet sync)*
  - `ui/tests/storyWorkbench.test.mjs` *(frontend unit tests for `@CAST-01:variant` resolution, Scene grouping in Meso view, and Micro take switching)*

---

## 1. Executive Summary & Architectural Vision

### 1.1 Two-Layer RunningHub Architecture Inside ZeroField Studio
RunningHub’s ecosystem consists of two distinct layers:
1. **Lower Layer — Compute Card Engine (`/openapi/v2/*`, implemented in `SPEC_05`)**:
   - Executes individual ComfyUI workflows bound to a `webappId` / `card_id` (`2109942725885075458` `h3-short-video-v3`, `2103540145878601730` `h3-reference`, `2105000000000000001` `ltx25-openjutsu`, etc.) via a flat `nodeInfoList` (`nodeId`, `fieldName`, `fieldValue`).
2. **Upper Layer — RH STORY AI Comic/Drama Workbench (`/aivideo/open/v1/*`, specified in `SPEC_06`)**:
   - Manages the **8-stage episodic drama lifecycle**:
     `PROJECT ➔ EPISODE ➔ SCRIPT ➔ ASSETS ➔ SCENES ➔ STORYBOARD ➔ SHOTS ➔ FILM_EXPORT`
   - Dispatches shot/asset image and video generation to the lower layer using `appCode` (mapped 1-to-1 to our Studio Cards in `workflows/cards/*.json`).

### 1.2 How RH STORY Maps to ZeroField’s **Macro ↔ Meso ↔ Micro** Triad
Instead of forcing directors to jump across disconnected web pages, ZeroField unifies RH STORY’s 8-stage pipeline and 5 top-level navigation modules directly into our **Macro (巨觀) ↔ Meso (中觀) ↔ Micro (微觀)** workspace backed by ZeroField’s live collaborative sheets:

```text
┌───────────────────────────────────────────────────────────────────────────────────────────────┐
│ TOP NAVIGATION BAR (Aligned with RH STORY 5 Pillars + Bilingual EN / zh-TW):                  │
│ [✦ Start Creating]  [🎬 My Projects (Macro/Meso/Micro)]  [❖ Asset Vault]  [🧰 Toolbox]  [⚡ Open API] │
└───────────────────────────────────────────────┬───────────────────────────────────────────────┘
                                                │
        ┌───────────────────────────────────────┼───────────────────────────────────────┐
        ▼                                       ▼                                       ▼
┌───────────────────────────────┐ ┌───────────────────────────────────┐ ┌───────────────────────────────┐
│ 🔭 MACRO (巨觀 — 全劇統籌)     │ │ 🎞️ MESO (中觀 — 場次與視覺鏈路牆)  │ │ 🔬 MICRO (微觀 — 單鏡審片調校) │
│ • 1-Click Script Import &     │ │ • Scene-Grouped Storyboard Gallery│ │ • Side-by-Side Stage Review   │
│   Episode Split (`director-   │ │   (`Scene 01: Rain Street`, etc.) │ │   (`←`/`→` keyboard stepping, │
│   brief` ➔ `/project-imports`)│ │ • Visual Evolution Chain Strip:   │ │   coexists with Assistant)    │
│ • "Confirm Script & Extract"  │ │   `[@CAST-01:night + @SET-01]`    │ │ • Multi-Take History Strip    │
│   Baseline Lock (`/asset-     │ │   `──► [Keyframe / 8-Frame Sheet]`│ │   (`/shots/{id}/videos` +     │
│   extractions` + `/storyboards`│ │   `──► [Cinema / Remastered MP4]` │ │   1-click `Select Take`)      │
│ • Batch Shot Generation       │ │ • 1-Click Wardrobe/Variant Pill   │ │ • 2-Pass Chaining (`@source`  │
│   (`/shot-video-generations`  │ │   Switcher (`@CAST-01:default` ➔  │ │   `referenceSourceVideoId`)   │
│   + `task-groups` progress)   │ │   `@CAST-01:night`)               │ │ • Shot Split / Merge (`/splits`│
│ • 1-Click Episode Film Export │ │ • Single-Scene Shot Rebuild       │ │ • Advanced `nodeInfoList`     │
│   (`/episodes/{id}/films` MP4)│ │   (`/scenes/{id}/shot-rebuilds`)  │ │   (`nodeId` / `fieldName`)    │
└───────────────────────────────┘ └───────────────────────────────────┘ └───────────────────────────────┘
```

---

## 2. Bidirectional Data Model Mapping (ZeroField 5 Tabs ↔ RH STORY Entities)

All RH STORY `/aivideo/open/v1/*` API calls **read and write directly to ZeroField’s existing project & tab tables** so changes made via API immediately appear in the UI, and edits in the UI (`Table`, `Gallery`, `Board`, `SheetReview`) are immediately reflected in `/aivideo/open/v1/*` responses!

| RH STORY Entity | ID Prefix | ZeroField Storage Backing | Exact Column / Field Mapping |
| :--- | :---: | :--- | :--- |
| **`Project`** | `pj_<slug>` | `projectops.project` (`slug`, `title`, `summary`) | `projectId = f"pj_{slug}"`, `title`, `description = summary` |
| **`Episode`** | `ep_<slug>_01` | Project episode metadata + `director-brief` (`doc` tab) | Default Episode 1 (`episodeIndex = 1`) maps to `director-brief` markdown content (`PUT /episodes/{episodeId}/script` updates `director-brief` and records a document revision for `GET /episodes/{episodeId}/script/versions`). Additional episodes (`ep_<slug>_02`, ...) map to `director-brief-ep02` or section blocks. |
| **`Asset` & `Variant`** | `as_<ASSET_ID>`<br>`vr_<ASSET_ID>_<key>` | `soul-cast` (`sheet` tab: `# Soul Cast & Asset Lookbook`) | • Row `Asset ID`: `CAST-01` (`type="CHARACTER"`), `SET-01` / `LOC-01` (`type="SCENE"`), `PROP-01` (`type="PROP"`), `STYLE-01` (`custom style`).<br>• **Wardrobe / State Variants**: Stored either as sub-rows with `Asset ID` = `CAST-01:night` (`kind="OUTFIT"`, `variantId="vr_CAST-01_night"`) or JSON/markdown gallery links in `Notes` / `Reference Image`. Default row `CAST-01` is `isDefault=True`. |
| **`Scene`** | `sc_<slug>_S01` | `## Scene` sections in `director-brief` + `Scene` grouping prefix on shots (`S01`, `S02` or `SC01-S01`) | Each scene has `sceneId`, `sceneIndex`, `title`, `content`, and owns the ordered list of `Shot` rows belonging to that scene. |
| **`Shot`** | `sh_<slug>_<rid>` | Rows in `cinema-studio` (and/or `openjutsu-lab`) `sheet` tabs | • `shotId = f"sh_{slug}_{row.rid}"`<br>• `Shot` (col 0) ➔ `shotIndex` & optional `sceneId` prefix (e.g. `SC01-S01` or `S01`)<br>• `Optical Rig` (col 1) + `Camera Motion` (col 2) + `Action & Audio Prompt` (col 3) ➔ `description`, `dialogue`, `durationSeconds`, and bound `@Asset` list (`@CAST-01`, `@CAST-01:night`, `@SET-01`)<br>• `Keyframe` (col 4) ➔ `selectedImageUrl`<br>• `Cinema Shot` / `Remastered Video` (col 5) ➔ `selectedVideoUrl`<br>• `Status` (col 6) ➔ mapped via `normalizeStatus()` (`Approved`/`Pending Review` ➔ `READY`, `Rendering Video`/`In Progress` ➔ `RUNNING`, `Queued` ➔ `PENDING`) |
| **`Shot Candidate History`** | `im_<asset_id>`<br>`vd_<asset_id>` | Row revision history (`projectops.change_group`) + task outputs for `(tab_key, row_id, col_index)` | Every generated or uploaded image/video on a shot row is preserved in candidate history (`GET /shots/{shotId}/images` & `/videos`). Calling `PUT /shots/{shotId}/selected-image` or `selected-video` updates the active cell value in `cinema-studio` / `openjutsu-lab`! |
| **`Film`** | `fl_<task_id>` | `comfy-pipeline` / `Edit` delivery output + `projectops.asset` | `POST /episodes/{episodeId}/films` concatenates all shots’ `selectedVideoUrl` in `shotIndex` order using FFmpeg (`-movflags +faststart`), stores the MP4 in `projectops.asset`, and returns `{ fileId, videoUrl }`. |

---

## 3. Part 1 (Backend): Self-Hosted `/aivideo/open/v1/*` RH STORY OpenAPI Engine (`project_docs/story_openapi.py`)

### 3.1 Wire Conventions & Response Envelope (100% RH STORY Spec Compliant)
Per `docs/references/runninghub-open-api-2026-10-18/guides/02-conventions.txt` and `03-error-codes.txt`:

1. **Base Path**: `/aivideo/open/v1` (mounted in `project_docs/runtime_http.py` whenever `parsed.path.startswith("/aivideo/open/v1")`).
2. **Success Envelope (`HTTP 200`)**:
   ```json
   {
     "code": 0,
     "msg": "success",
     "errorMessages": null,
     "data": { ... }
   }
   ```
3. **Error Envelope (Non-200 HTTP Status Matches Error Category)**:
   ```json
   {
     "code": "DRAMA_STAGE_PRECONDITION",
     "message": "Episodes require confirmed script and extracted scenes before generating storyboards.",
     "requestId": "req_8f9a1b2c3d4e"
   }
   ```
   - Supported standard error codes & HTTP statuses:
     - `400`: `DRAMA_REQUEST_FAILED`
     - `401`: `DRAMA_AUTH_MISSING`, `DRAMA_AUTH_INVALID` (when `Authorization` header is missing or lacks `Bearer ` prefix in strict mode; in local dev mode, accept any non-empty `Bearer <token>`)
     - `404`: `DRAMA_NOT_FOUND`
     - `409`: `DRAMA_IDEMPOTENCY_CONFLICT`, `DRAMA_OPERATION_NOT_ALLOWED`, `DRAMA_STAGE_PRECONDITION`
     - `422`: `DRAMA_VALIDATION_FAILED`, `DRAMA_SCRIPT_INVALID`, `DRAMA_STAGE_INPUT_EMPTY`, `DRAMA_STYLE_NOT_FOUND`
4. **`Idempotency-Key` Header Deduplication**:
   - On `POST` endpoints, if `Idempotency-Key` is provided:
     - If `len(key) > 128`, return `422 DRAMA_VALIDATION_FAILED`.
     - Cache `(bearer_token, endpoint, idempotency_key) -> (body_sha256, response_payload)` in memory/DB for 24h.
     - Same key + same body ➔ return cached response immediately.
     - Same key + different body ➔ return `409 DRAMA_IDEMPOTENCY_CONFLICT`.
5. **Cursor Pagination (`cursor` + `limit`) & 64-Bit Integer Strings**:
   - All list endpoints accept `limit` (`1..100`, default `20`; outside range ➔ `422 DRAMA_VALIDATION_FAILED`) and `cursor`, returning `{ "items": [...], "nextCursor": "..." | null }`.
   - All 64-bit numeric fields (`size`, `skuId`, `taskCount`, `inputTokens`, `outputTokens`, `counts.*`) MUST be serialized as **numeric strings** (e.g. `"10234"`, `"0"`).

---

### 3.2 Required `/aivideo/open/v1` Endpoints & Behavior

#### Group A: Catalog & Capabilities (`目录`)
1. **`GET /aivideo/open/v1/capabilities`**:
   - Returns:
     ```json
     {
       "version": "v1",
       "site": "AI",
       "baseUrl": "http://127.0.0.1:8000/aivideo/open/v1",
       "stages": ["PROJECT", "EPISODE", "SCRIPT", "ASSETS", "SCENES", "STORYBOARD", "SHOTS", "FILM_EXPORT"],
       "rateLimit": { "replenishRatePerSecond": 50, "burstCapacity": 100 },
       "features": {
         "files": true,
         "projectImport": true,
         "scriptTools": true,
         "editing": true,
         "assetEditing": true,
         "batchGeneration": true,
         "taskRetry": true,
         "webhookDeliveries": true,
         "usage": true,
         "sandbox": false
       }
     }
     ```
2. **`GET /aivideo/open/v1/catalog/apps`**:
   - Query params: `capability` (`IMAGE` | `VIDEO`, required; invalid ➔ `422 DRAMA_VALIDATION_FAILED`), optional `usageScope` (`CHARACTER`, `SCENE_PROP`, `SCENE_PROP_EDIT`, `FREE_CREATION_T2I`, `FREE_CREATION_I2I`).
   - Dynamically maps our registered Studio Cards in `workflows/cards/*.json` PLUS standard RH STORY aliases (`NANO_PRO_G2_I2I_OFFICIAL`, `SEEDANCE_2_FAST_MULTIMODAL_VIDEO`) to local cards:
     | `appCode` | Mapped Local `card_id` | `webappId` | `capability` | `imageMode` |
     | :--- | :--- | :--- | :---: | :---: |
     | `H3_SHORT_VIDEO_V3` | `h3-short-video-v3` | `2109942725885075458` | `VIDEO` | `I2I` |
     | `H3_REF2VA_PASS1` / `SEEDANCE_2_FAST_MULTIMODAL_VIDEO` | `h3-reference` | `2103540145878601730` | `VIDEO` | `I2I` |
     | `H3_OPTIMIZE_4K` | `h3-optimize` | `2103540145878601731` | `VIDEO` | `I2I` |
     | `LTX25_OPENJUTSU_V2V` | `ltx25-openjutsu` | `2105000000000000001` | `VIDEO` | `I2I` |
     | `LTX25_CINEMA_SHOT` | `ltx25-cinema` | `2105000000000000002` | `VIDEO` | `I2I` |
     | `FLUX3_SOUL_CAST` / `NANO_PRO_G2_I2I_OFFICIAL` | `flux-soul-cast` | `2105000000000000003` | `IMAGE` | `I2I` |
     | `LOCAL_SDXL_SMOKE` | `local-smoke` | `2105000000000000004` | `IMAGE` | `T2I` |
   - Also accepts any `card_id` or `webappId` directly as `appCode` in generation endpoints!
3. **`GET /aivideo/open/v1/catalog/styles`**, **`/catalog/director-styles`**, **`/catalog/aspect-ratios`**:
   - Return built-in cinematic style presets (`88123`: `Sci-Fi Noir Anamorphic`, `88124`: `Cel-Shaded Anime Drama`, `88125`: `Dark Fantasy Concept`, `88126`: `High-Contrast Neo-Noir`), director styles (`ARRI Alexa 65 / 35mm Anamorphic`, `RED V-Raptor / 85mm Prime`, `16mm Bolex`), and aspect ratios (`16:9`, `9:16`, `1:1`, `21:9`).

#### Group B: Files, 1-Click Project Import & Projects/Episodes (`文件` / `一键导入` / `项目` / `剧集与剧本`)
1. **`POST /aivideo/open/v1/files`**, **`GET /files/{fileId}`**, **`DELETE /files/{fileId}`**, **`GET /files/{fileId}/url`**:
   - Supports uploading scripts (`.txt` / `.md`, `purpose="SCRIPT"`), images (`purpose="IMAGE"`), or audio/video; returns `fileId` (`up_<hex>`), `size` (as string), and `url`.
2. **`POST /aivideo/open/v1/project-imports`** & **`POST /aivideo/open/v1/project-generations`**:
   - Accepts `{ scriptContent | scriptFileId, title, aspectRatio, stylePresetId }`.
   - Validates exclusive `scriptContent` XOR `scriptFileId` (both or neither ➔ `400 DRAMA_REQUEST_FAILED`; empty script ➔ `422 DRAMA_SCRIPT_INVALID`).
   - Creates a ZeroField project (`zerofield_studio` template), splits multi-episode scripts into episodes, writes formatted script to `director-brief`, and returns async task envelope `{ taskId: "tk_...", type: "PROJECT_IMPORT", status: "QUEUED", ... }` which resolves to `{ projectId: "pj_<slug>", episodeId: "ep_<slug>_01", episodeCount: N, episodes: [...] }`.
3. **`POST /aivideo/open/v1/projects`**, **`GET /projects`**, **`GET /projects/{projectId}`**, **`PATCH /projects/{projectId}`**, **`DELETE /projects/{projectId}`**, **`GET /projects/{projectId}/episodes`**.
4. **`POST /aivideo/open/v1/projects/{projectId}/episodes`**, **`GET /episodes/{episodeId}`**, **`PATCH /episodes/{episodeId}`**, **`PUT /episodes/{episodeId}/script`**, **`GET /episodes/{episodeId}/script/versions`**, **`POST /episodes/{episodeId}/script-refinements`**, **`GET/PUT /episodes/{episodeId}/settings`**:
   - **Script Baseline Dirty Flag (`scriptDirty`)**:
     - Whenever `PUT /episodes/{episodeId}/script`, `POST /episodes/{episodeId}/script-refinements`, or manual scene edits modify the script after assets/scenes were confirmed, mark `episode.scriptDirty = True`.
     - If `POST /episodes/{episodeId}/storyboards` is called while `scriptDirty == True` or before scenes exist, return `409 DRAMA_STAGE_PRECONDITION` instructing the caller to run `POST /episodes/{episodeId}/asset-extractions` first (matching RH STORY’s exact state-machine rule!).

#### Group C: Asset Extraction, Variants & Scene/Shot Binding (`资产`)
1. **`POST /aivideo/open/v1/episodes/{episodeId}/asset-extractions`**:
   - Precondition: Episode must have non-empty script (`director-brief`), otherwise return `422 DRAMA_STAGE_INPUT_EMPTY`.
   - Parses the script (via configured LLM or deterministic structured parser fallback when offline) to:
     1. Split the script into ordered **Scenes (`sc_...`)**.
     2. Extract **Characters (`CAST-01`, ...)**, **Scenes/Locations (`SET-01`, ...)**, and **Props (`PROP-01`, ...)** and upsert them into the `soul-cast` sheet tab!
     3. Clear `episode.scriptDirty = False` (locking the confirmed script baseline).
   - Returns task envelope `type: "ASSET_EXTRACT"`.
2. **`GET /aivideo/open/v1/episodes/{episodeId}/assets`**, **`POST /episodes/{episodeId}/assets`**, **`GET /assets/{assetId}`**, **`PATCH /assets/{assetId}`**, **`DELETE /assets/{assetId}`**:
   - Reads/writes rows in `soul-cast`.
3. **`GET /aivideo/open/v1/assets/{assetId}/variants`**, **`POST /assets/{assetId}/variants`**, **`PATCH /assets/{assetId}/variants/{variantId}`**, **`DELETE /assets/{assetId}/variants/{variantId}`**:
   - Manages wardrobe/state variants (e.g., `kind: "OUTFIT"`, `name: "Night Ops Jacket"`, `isDefault: false`).
   - Stored in `soul-cast` as variant rows (`CAST-01:night`) or structured metadata so `@CAST-01:night` can be referenced directly in any shot row!
4. **`POST /aivideo/open/v1/assets/{assetId}/image-generations`**, **`POST /assets/{assetId}/images`**, **`GET /assets/{assetId}/images`**, **`PUT /assets/{assetId}/selected-image`**:
   - Generates or uploads the reference image for an asset in `soul-cast` using `flux-soul-cast` / `local-smoke` via our local ComfyUI Card Engine and updates the `Reference Image` column.
5. **`PUT /aivideo/open/v1/shots/{shotId}/assets`** & **`PUT /assets/{assetId}/scenes`**:
   - Updates the `@CAST-XX` / `@SET-XX` / `@PROP-XX` tags bound to the target shot row in `cinema-studio` / `openjutsu-lab`.

#### Group D: Scenes, Storyboard Generation & Shot Production (`分场与分镜` / `镜头产出` / `成片与文件`)
1. **`GET /aivideo/open/v1/episodes/{episodeId}/scenes`**, **`POST /episodes/{episodeId}/scenes`**, **`PATCH /scenes/{sceneId}`**, **`PUT /episodes/{episodeId}/scene-order`**, **`POST /scene-merges`**, **`POST /scenes/{sceneId}/shot-rebuilds`**.
2. **`POST /aivideo/open/v1/episodes/{episodeId}/storyboards`**:
   - Precondition: Scenes must exist and `scriptDirty` must be `False` (otherwise `409 DRAMA_STAGE_PRECONDITION`).
   - Populates `cinema-studio` shot rows (`S01`, `S02`, ...) with `Optical Rig`, `Camera Motion`, `Action & Audio Prompt` (including `@CAST-01`, `@SET-01` bindings), and `Status = Queued`.
   - Returns task envelope `type: "STORYBOARD_GENERATE"` with `result: { "shotsCount": N }`.
3. **`GET /aivideo/open/v1/episodes/{episodeId}/shots`**, **`GET /shots/{shotId}`**, **`PATCH /shots/{shotId}`**, **`POST /scenes/{sceneId}/shots`**, **`DELETE /shots/{shotId}`**:
   - Reads/writes rows in `cinema-studio` / `openjutsu-lab`.
4. **`POST /aivideo/open/v1/shots/{shotId}/splits`** & **`POST /aivideo/open/v1/shot-merges`**:
   - `splits`: Splits one shot row (e.g. `S02`) into two consecutive shot rows (`S02A`, `S02B`) preserving `@Asset` bindings and optical rig.
   - `shot-merges`: Merges two or more shot rows into a single combined shot row.
5. **`POST /aivideo/open/v1/shots/{shotId}/image-generations`** & **`POST /shots/{shotId}/video-generations`**:
   - Resolves `appCode` to the corresponding Studio Card (`workflows/cards/*.json`).
   - Calls `resolve_studio_context()` + `build_node_info()` + `inject_node_info_into_workflow()` (from `SPEC_05`).
   - Supports `modelParams` (mapped to `nodeInfoList` overrides or semantic slots), `promptOverride`, and `referenceSourceVideoId` (mapped to `@source` for 2-pass restoration or continuation!).
   - Updates the shot’s `Keyframe` (`selectedImageUrl`) or `Cinema Shot` / `Remastered Video` (`selectedVideoUrl`) cell in the sheet and appends the output to the shot’s candidate history (`GET /shots/{shotId}/images` & `/videos`).
6. **`PUT /aivideo/open/v1/shots/{shotId}/selected-image`** & **`PUT /shots/{shotId}/selected-video`**:
   - Switches the active cell in `cinema-studio` / `openjutsu-lab` to the chosen candidate `imageId` / `videoId`.
7. **`POST /aivideo/open/v1/episodes/{episodeId}/shot-image-generations`** & **`POST /episodes/{episodeId}/shot-video-generations`** & **`GET /task-groups/{groupId}`**:
   - Queues batch generation across all or selected shots in the episode and returns a `taskGroup` with stringified counts (`total`, `succeeded`, `failed`, `running`, `queued`).
8. **`POST /aivideo/open/v1/episodes/{episodeId}/films`** & **`GET /episodes/{episodeId}/films`**:
   - Precondition: At least one shot in the episode has a generated/selected video (`selectedVideoUrl`), otherwise return `409 DRAMA_STAGE_PRECONDITION`.
   - Uses FFmpeg concat demuxer / filter (`limb_worker.py`) to stitch all selected shot videos in order into a single `.mp4` with `-movflags +faststart`, saves it to `projectops.asset`, and returns `{ taskId, type: "FILM_EXPORT", status: "QUEUED" }` ➔ `{ fileId, videoUrl }`.

#### Group E: Tasks, Quota & Webhooks (`任务` / `平台` / `计费` / `Webhook 管理`)
1. **`GET /aivideo/open/v1/tasks/{taskNo}`**, **`GET /tasks`**, **`POST /tasks/{taskNo}/cancellations`**, **`POST /tasks/{taskNo}/retries`**.
2. **`GET /aivideo/open/v1/usage`**, **`GET /balance`**, **`GET /quota`**, **`GET /bills`**, **`GET /bills/{billNo}`** (returns local self-hosted unlimited/dev quota with stringified 64-bit counters).
3. **`POST /aivideo/open/v1/webhooks`**, **`GET /webhooks`**, **`DELETE /webhooks/{webhookId}`**, **`POST /webhooks/{webhookId}/test-deliveries`**, **`GET /webhooks/{webhookId}/deliveries`**.

---

## 4. Part 2 (Frontend): Integrating RH STORY’s 5 Pillars into Macro ↔ Meso ↔ Micro

### 4.1 Top Workbench Bar — The 5 RH STORY Pillars (`ui/src/Surfaces.jsx` & `ui/src/App.jsx`)
In the project header (`SurfaceHeader` in `ui/src/Surfaces.jsx`), add a clean, non-disruptive **Studio Mode Bar** with the 5 RH STORY pillars (using bilingual i18n keys in `en.json` and `zh-TW.json`):

1. **`✦ Start Creating` (`開始創作`)**:
   - Opens the **1-Click Script Import & Auto-Breakdown Drawer (`StoryImportModal`)**.
   - Users can paste a script or upload a `.txt`/`.md` file, pick an Aspect Ratio (`16:9` / `9:16`) and Style Preset, and click **"Confirm Script, Extract Assets & Build Storyboard"**.
   - Calls `/aivideo/open/v1/episodes/{epId}/script` ➔ `/asset-extractions` ➔ `/storyboards` and populates `director-brief`, `soul-cast`, and `cinema-studio` in one flow.
2. **`🎬 My Projects / Production Desk` (`我的項目`)**:
   - The active **Macro (`Table`/`Board`) ↔ Meso (`Gallery`) ↔ Micro (`SheetReview`)** multi-tab workspace.
3. **`❖ Asset Vault` (`資產庫`)**:
   - Quick-switches to `soul-cast` or opens the **Asset & Wardrobe Variant Drawer**, allowing the director to manage `@CAST-01` default appearance plus wardrobe variants (`@CAST-01:night`, `@CAST-01:damaged`), bind style presets, and preview which scenes/shots each asset appears in.
4. **`🧰 Toolbox` (`工具箱`)**:
   - Opens the **Self-Hosted AI-App Card Manager (`ToolboxModal`)**.
   - Displays all registered Studio Cards (`GET /openapi/v2/cards` & `GET /aivideo/open/v1/catalog/apps`), showing each card’s **`webappId`**, **`card_id` (`appCode`)**, **frame rule (`17n+5` / `8n+1`)**, and exposed **`nodeInfoList` (`nodeId`, `fieldName`, `fieldType`, `slot`)**.
   - Includes **"Import ComfyUI `.json` + RunningHub `curl`"** so users can paste any downloaded `.json` workflow and `curl` snippet to register a new local AI-App card on the spot!
5. **`⚡ Open API` (`開放 API`)**:
   - Opens the **Self-Hosted Open API Inspector (`OpenApiModal`)** showing live copy-pasteable `curl` and Python snippets for both:
     - **Layer 1 (Workflow Card API)**: `POST /openapi/v2/run/ai-app/{webappId}` (with live `nodeInfoList` JSON for the selected card).
     - **Layer 2 (RH STORY Drama API)**: `POST /aivideo/open/v1/shots/{shotId}/video-generations`, `/asset-extractions`, `/storyboards`, `/films`.

---

### 4.2 Upgrading **Macro (巨觀)** in `ui/src/SheetWorkspace.jsx`
1. **Script Baseline Banner & 1-Click Confirm (`director-brief` & `cinema-studio`)**:
   - When `director-brief` has been edited since the last extraction, show a non-intrusive bar:
     `Script modified since last breakdown · [Confirm Script & Sync Assets/Shots]`
2. **Batch AI-App Selector & Episode Film Export Bar**:
   - In the Macro toolbar / batch bar of `cinema-studio` and `openjutsu-lab`:
     - Allow picking the target **`appCode` / Studio Card** (e.g. `MiniMax H3 Short Video v3 (2109942725885075458)`, `MiniMax H3 Ref2VA (2103540145878601730)`, `LTX-2.5 OpenJutsu (2105000000000000001)`) when batch-running selected rows.
     - Add **`🎬 Export Episode Film` (`導出整集成片`)** button that triggers `POST /aivideo/open/v1/episodes/{episodeId}/films` and opens an inline `<video controls>` preview of the stitched episode MP4 when finished.

---

### 4.3 Upgrading **Meso (中觀)** in `ui/src/sheetViews.js`, `ui/src/studioModel.js` & `ui/src/SheetCards.jsx`
1. **Wardrobe / Variant Asset Resolution (`@CAST-01:night`)**:
   - Update `assetReferences(row)` and `buildAssetLookup(documents)` in `ui/src/studioModel.js` to recognize both base asset IDs (`@CAST-01`, `@SET-01`, `@PROP-01`) and variant tags (`@CAST-01:night`, `@CAST-01#night`):
     ```js
     /@?\b(?:CAST|SET|LOC|PROP|STYLE)-\d+(?:[:#][a-z0-9_-]+)?\b/gi
     ```
   - If `@CAST-01:night` is referenced, `assetLookup["CAST-01:NIGHT"]` resolves the specific wardrobe variant’s thumbnail (falling back to `assetLookup["CAST-01"]` if the variant has no separate image yet).
2. **Scene-Grouped Storyboard Gallery (`Group by Scene` in Meso `Gallery` View)**:
   - In `ui/src/sheetViews.js` and `ui/src/SheetCards.jsx`, when viewing `Gallery` (`mode === 'gallery'`), detect scene prefixes on shots (e.g. `SC01-S01` or `Scene` column or `director-brief` scene mapping) and allow collapsible **Scene Headers** (`Scene 01 · Observatory Arrival (3 Shots)`) with a **`↻ Rebuild Scene Shots`** action.
3. **Interactive Variant Switcher Chip on Meso Cards**:
   - On each Meso shot card’s `.card-asset-chips`, clicking an `@CAST-01` chip when variants exist (`CAST-01:night`, etc.) lets the director cycle or pick the wardrobe variant for that shot in 1 click.

---

### 4.4 Upgrading **Micro (微觀)** in `ui/src/SheetWorkspace.jsx` & `ui/src/SheetReview.jsx`
Inside the `SheetReview` side-by-side shot inspector (which stays open alongside `Studio Assistant`):
1. **Candidate Take Strip & 1-Click Take Selection (`/shots/{shotId}/images` & `/videos`)**:
   - Below the active stage player in `SheetReview`, render all historical candidate takes for that shot cell (from row history / `/aivideo/open/v1/shots/{shotId}/videos`) so the director can compare takes and click **`✓ Use This Take`** (`PUT /shots/{shotId}/selected-video`) without digging through raw diff logs.
2. **Shot Split & 2-Pass Restoration (`@source`) Actions**:
   - Add **`✂ Split Shot`** (`POST /shots/{shotId}/splits` — splits the current row into two sequential shots) and **`✧ 2nd-Pass 4K Restore (H3 Optimize)`** (triggers `h3-optimize` `2103540145878601731` with `@source` bound to the current shot’s video).
3. **Card & `nodeInfoList` (`nodeId`) Inspector Accordion**:
   - Add a collapsible **`⚙ AI-App Card & Node Inputs (nodeInfoList)`** section in `SheetReview` showing the active card’s `webappId` (e.g. `2109942725885075458`) and its exposed `nodeId` / `fieldName` inputs (e.g. `Node 1 · image (<Picture 1>)`, `Node 61 · image (<Picture 2>)`, `Node 3 · video (<Video 1>)`, `Node 57 · text (H3-Context-IR)`), allowing direct per-shot override before clicking **Re-shoot**.

---

## 5. Verification & Test Suite Requirements

### 5.1 Backend Unit & HTTP Integration Tests (`tests/test_story_openapi.py`)
Create `tests/test_story_openapi.py` covering:
1. **Suite 1 — Catalog & Capabilities (`/aivideo/open/v1/capabilities` & `/catalog/apps`)**:
   - Verifies `{ code: 0, msg: "success", errorMessages: null, data: ... }` envelope.
   - Verifies `/catalog/apps?capability=VIDEO` and `capability=IMAGE` return all local Studio Cards (`h3-short-video-v3` `2109942725885075458`, `h3-reference` `2103540145878601730`, `ltx25-openjutsu`, `flux-soul-cast`, etc.) with stringified `skuId`.
   - Verifies invalid `capability=AUDIO` returns `HTTP 422` with `code: "DRAMA_VALIDATION_FAILED"`.
2. **Suite 2 — `Idempotency-Key` & Error Code Contract**:
   - Verifies repeating a `POST /aivideo/open/v1/projects` request with the same `Idempotency-Key` and body returns the identical project without creating a duplicate.
   - Verifies repeating the same `Idempotency-Key` with a different body returns `HTTP 409` with `code: "DRAMA_IDEMPOTENCY_CONFLICT"`.
3. **Suite 3 — 8-Stage Lifecycle & Script Baseline Lock (`PROJECT ➔ SCRIPT ➔ ASSETS ➔ STORYBOARD ➔ SHOTS ➔ FILM_EXPORT`)**:
   - Creates a project and episode via `/aivideo/open/v1/project-imports` (or `/projects` + `/episodes/{id}/script`).
   - Verifies calling `/episodes/{id}/storyboards` before `/asset-extractions` returns `HTTP 409 DRAMA_STAGE_PRECONDITION`.
   - Runs `POST /episodes/{id}/asset-extractions` and verifies `soul-cast` sheet rows (`CAST-01`, `SET-01`, etc.) and scenes are populated.
   - Creates an outfit variant via `POST /assets/{assetId}/variants` (`CAST-01:night`) and verifies `GET /assets/{assetId}` lists the variant.
   - Runs `POST /episodes/{id}/storyboards` and verifies `cinema-studio` shot rows (`S01`, `S02`, ...) are populated.
   - Modifies the script via `PUT /episodes/{id}/script` and verifies `/storyboards` again enforces `409 DRAMA_STAGE_PRECONDITION` until `/asset-extractions` re-confirms the baseline.
4. **Suite 4 — Shot Generation, Candidate Take Switching, Shot Split & Film Export**:
   - Triggers `POST /shots/{shotId}/video-generations` with `appCode: "h3-short-video-v3"` (or `"2109942725885075458"`).
   - Verifies `GET /shots/{shotId}/videos` lists the generated take and `PUT /shots/{shotId}/selected-video` updates the `cinema-studio` sheet cell.
   - Verifies `POST /shots/{shotId}/splits` splits the shot row into two rows in `cinema-studio`.
   - Verifies `POST /episodes/{id}/films` concatenates the episode’s shot videos via FFmpeg into a playable `+faststart` MP4 and returns `{ fileId, videoUrl }`.

### 5.2 Frontend Tests & Build Verification
1. Run `npm test --prefix ui` (including `ui/tests/storyWorkbench.test.mjs`).
2. Run `npm run build --prefix ui` (Guardrail #4: always rebuild `static/projects/` after editing `ui/src/`).
3. Run full backend test suite:
   ```powershell
   python -m unittest discover -s tests -p "test_*.py"
   ```
   Ensure 0 failures across `test_story_openapi.py`, `test_studio_worker.py`, `test_media_streaming.py`, `test_run_studio.py`, and `test_zerofield_baseline.py`.
