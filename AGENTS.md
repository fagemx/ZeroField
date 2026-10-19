# ZeroField Studio — Agent Instructions & Guardrails (`AGENTS.md`)

> **2026-10-19 SPEC_06 implementation:** The RH STORY facade, five-entry workbench, script baseline lock, variants, scene grouping, candidate history, split/merge, card overrides, batches and FFmpeg film export are implemented. See [`docs/STORY_WORKBENCH.md`](./docs/STORY_WORKBENCH.md) and [`docs/story-workbench-verification.json`](./docs/story-workbench-verification.json). Backend 306 / frontend 108 tests and the UI build pass. Migration `162_story_workbench.sql` persists API metadata and uploads; collaborative tabs remain authoritative. GPU/provider inference and external webhook networking were not exercised. The older “SPEC_06 next” descriptions below are historical scope, not a request to implement it again.

> **2026-10-18 bilingual interface update (user-approved batches 1–2):** English is the first-run default and fallback; users may explicitly select Traditional Chinese. All new product UI must use semantic keys in `ui/src/i18n/locales/en.json` and `zh-TW.json`. Keep wire values, M8 / ACP keys, user content and custom names independent of display language. Use `normalizeStatus()` for logic and `statusLabel()` for display. Translated templates, project / AI language settings and video development remain later work. See [`docs/bilingual-baseline.json`](./docs/bilingual-baseline.json).

> **2026-10-18 English contest baseline:** The M8-A–D / ACP / E1 engine is retained. English UI, crew labels, a five-page `zerofield_studio` planning template, and legacy status compatibility are implemented. Backend 241 / frontend 78 tests, UI build, wheel resources, and isolated desktop UI checks passed; see [`docs/english-baseline.json`](./docs/english-baseline.json). Video-specific development, generation workflows, real sample renders, and `run_studio.py` are the next phase. Use README’s Available now section for current capability claims.

> **給接手的 AI 代理（Codex / Claude / Antigravity）**：
> 本專案 **`ZeroField`**（位於 `C:\ai_project\ZeroField`）是專為參加 ComfyUI **「Open Source Higgsfield Challenge」**（截止日：2026-10-30 09:00 PT）獨立出來的參賽專用 Repo。
>
> **動工前請務必依序閱讀以下 5 份核心文件**：
> 1. **[`docs/HANDOFF_4090_PC.md`](./docs/HANDOFF_4090_PC.md)**（**電腦交接首頁**：目前 `SPEC_01`～`SPEC_05` 完成狀態、下一步 **`SPEC_06`** 任務、以及跨 Repo 參考清單）
> 2. **[`docs/specs/SPEC_06_RH_STORY_WORKBENCH_AND_MACRO_MESO_MICRO.md`](./docs/specs/SPEC_06_RH_STORY_WORKBENCH_AND_MACRO_MESO_MICRO.md)**（**下一步主規格**：自建 RH STORY 漫劇工作台 `/aivideo/open/v1` 雙向 API 引擎、頂部五大入口、以及巨觀 ↔ 中觀 ↔ 微觀深度整合）
> 3. **[`docs/specs/SPEC_05_DUAL_ENGINE_ALIGNMENT_AND_LINEWORLDS.md`](./docs/specs/SPEC_05_DUAL_ENGINE_ALIGNMENT_AND_LINEWORLDS.md)**（已完成基底：自建 RunningHub `/openapi/v2` 卡片引擎、`MiniMax H3 Ref2VA + H3-Context-IR`、`LTX-2.5 IC-LoRA + Ingredients Sheet` 與 `line-worlds` 結構產生器）
> 4. **[`docs/DESIGN_AND_DEV_GUIDELINES.md`](./docs/DESIGN_AND_DEV_GUIDELINES.md)**（必讀！英文介面規範、`STATUSES` 白名單防呆、影片播放器、Open-Weights 與版權合規鐵律）
> 5. **[`docs/ZEROFIELD_SPEC.md`](./docs/ZEROFIELD_SPEC.md)** 與 **[`docs/AGENT_ORCHESTRATION_SPEC.md`](./docs/AGENT_ORCHESTRATION_SPEC.md)**（參賽總體規格與多代理編排規格）

---

## 1. 最高優先級開發鐵律（Top Guardrails — 違反任一條將導致失格或畫面壞掉）

### ① 全英文使用者介面（English-First UI for International Judges）
- 評審為 ComfyOrg、NVIDIA、LTX、Black Forest Labs 國際團隊，**所有看得到的畫面、按鈕、預設展示專案、角色職稱（Showrunner / Director / Cinematographer）與範本一律使用專業英文影視術語**。
- **⚠️ 狀態膠囊（Status Pills）白名單防呆**：
  - 後端 [`project_docs/doc_schema.py`](./project_docs/doc_schema.py) 第 17 行的 `STATUSES` 是資料庫存檔的嚴格白名單！
  - 新增英文狀態（`"Queued"`, `"In Progress"`, `"Rendering Image"`, `"Rendering Video"`, `"Pending Review"`, `"Retake"`, `"Blocked"`, `"Approved"`）時，**必須同時更新 `project_docs/doc_schema.py` 的 `STATUSES` 與前端 `ui/src/format.js`**，且在後端 `doc_schema.py` 保留舊中文狀態字串以免既有單元測試失敗！

### ② 解除舊版「不顯示影片播放器」限制 — 全面開啟格內 `<video>`、畫廊封面與競速盲測播放
- 在 [`ui/src/MediaCell.jsx`](./ui/src/MediaCell.jsx) 中，`kind === "video"` 時**必須渲染內嵌 `<video>` 播放器**（緊湊模式下支援 Hover-to-Play 預覽，完整模式下支援 `controls`），不可只顯示「Video attachment」文字卡，並開啟影片格的 `onRegenerate` 按鈕。
- 在 [`ui/src/sheetViews.js`](./ui/src/sheetViews.js) 與 [`ui/src/SheetCards.jsx`](./ui/src/SheetCards.jsx) 中，`coverColumns` 必須同時納入 `image` 與 `video` 欄位，讓 `Gallery` 與 `Board` 視圖能直接顯示分鏡與 OpenJutsu 影片卡片。
- 在 [`ui/src/assistant/ProposalRaceView.jsx`](./ui/src/assistant/ProposalRaceView.jsx) 中，當候選提案為影片時，必須渲染並排 `<video>` 播放器供盲測挑片。

### ③ Comfy Developer Platform 合規（Comfy Router / SDK）＋ Open Weights 核心工作流
- 比賽規定必須建構於 **Comfy Developer Platform（Comfy Router 和／或 Comfy SDK）** 之上，不可只依賴裸打本機 `127.0.0.1:8188/prompt`。
- `workflows/` 內的預設工作流採用 100% 開放權重模型（**`LTX-2.5`** 作為核心影片模型以符合 LTX \$2,000 加碼獎資格 ＋ **`FLUX`** 作為角色／場景資產與首幀模型），同時符合 **Best Overall** 與 **Open Weights Only** 參賽條件。
- `samples/` 與預設專案素材必須 **100% SFW、無版權爭議、無真實名人姓名或肖像**。

### ④ 改完前端 `ui/src/` 必跑 `npm run build --prefix ui`
- `server.py` 讀取的是編譯後的 `static/projects/`。每次修改 `ui/src/` 後，**必須執行 `npm run build --prefix ui`**，否則瀏覽器畫面不會更新！

### ⑤ 影音播放效能與零 Blob `/meta` 查詢（防爆 RAM 與解碼器崩潰）
- **`/meta` 零 Blob 查詢**：在 [`project_docs/repository.py`](./project_docs/repository.py) 新增 `get_asset_meta()` 只查 `SELECT content_type, byte_size FROM projectops.asset`，並在 [`project_docs/http.py`](./project_docs/http.py) 的 `asset_meta` 路由改呼 `get_asset_meta()`，嚴禁呼叫 `get_asset()` 把 64 MB 影片撈進記憶體！
- **`If-None-Match` (`304`) 短路 + `server.py` 既有 `Range` (`206`) 串流**：`server.py:send_skillops_bytes` 已實作 `206 Partial Content`；請在 `http.py` 的 `asset` 路由補上 `If-None-Match` 命中時直接回傳 `304 Not Modified`（不讀 `data` bytea）。
- **前端 `MediaCell.jsx` 記憶體防護**：建立模組級 `META_CACHE = new Map()` 避免重複打 `/meta`；表格內的 `<video>` 預設 `preload="metadata"` 靜止顯示首幀，**僅在滑鼠懸停（Hover）或點開審核時才播放（`play()`）**，移開即 `pause()`。
- **FFmpeg `+faststart`**：所有 `limb_worker.py` 產出的 MP4（含 `side_by_side` 對比片）一律加上 `-movflags +faststart`。

---

## 2. 模組化施工規格與派工清單（詳見 `docs/ZEROFIELD_SPEC.md` 與 `docs/specs/`）

> **注意**：`ce80b94` 已完成全英文 UI 基底、5 頁 `zerofield_studio` 範本、英文與舊中文 `STATUSES` 相容、M8 多代理編排、`media.py` 64 MB MP4/WebM 驗證與 `server.py` HTTP `Range` 串流。
> 為了讓單一或多個代理能清楚分工且互不踩檔，後續實作已拆分為 **4 份獨立子規格（`docs/specs/SPEC_01` ～ `SPEC_04`）**：

1. **[`docs/specs/SPEC_01_MEDIA_STREAMING_AND_VIDEO_PLAYER.md`](./docs/specs/SPEC_01_MEDIA_STREAMING_AND_VIDEO_PLAYER.md) — 格內 `<video>` 播放與零 Blob `/meta` 基礎建設（Step 1）**：
   - **負責檔案**：`project_docs/repository.py`, `project_docs/http.py`, `ui/src/MediaCell.jsx`, `ui/src/assistant/ProposalRaceView.jsx`。
   - `repository.py` 新增 `get_asset_meta()`，`http.py` 的 `asset_meta` 改用零 Blob 查詢並在 `asset` 支援 `304 Not Modified`。
   - `MediaCell.jsx` 加上 `META_CACHE`、格內 `<video>`（Hover-to-Play 預覽與完整控制模式）及影片 `onRegenerate`；`ProposalRaceView.jsx` 支援候選影片並排播放。

2. **[`docs/specs/SPEC_02_MACRO_MESO_MICRO_WORKSPACE.md`](./docs/specs/SPEC_02_MACRO_MESO_MICRO_WORKSPACE.md) — 同頁「巨觀 ↔ 中觀 ↔ 微觀」無縫切換與 `FlowSurface` 管線管理（Step 2A，純前端）**：
   - **負責檔案**：`ui/src/App.jsx`, `ui/src/SheetWorkspace.jsx`, `ui/src/sheetViews.js`, `ui/src/SheetCards.jsx`, `ui/src/FlowSurface.jsx`, `ui/src/FlowPanels.jsx`, `ui/src/flowModel.js`。
   - **解除強制關閉斷層**：修改 `SheetWorkspace.jsx` 第 42 行，打開右側 `Studio Assistant` 時**不可強制關閉**正在檢視的單鏡微觀畫面（`preview` / `panel === 'row'`）。
   - **原地背景執行（`runInPlace`）**：在 `SheetWorkspace.jsx` 直接呼叫 `/flow/preflight` + `/flow/runs` 在背景排隊執行，不再強迫跳轉去 `FlowSurface` 分頁。
   - **中觀（Meso）視覺鏈路卡片（`sheetViews.js` & `SheetCards.jsx`）**：`coverColumns` 納入 `video` 欄位，並在 `Gallery` 卡片上橫向呈現該鏡的完整視覺演進鏈路（`[@Asset] ──► [Keyframe / Source Video] ──► [Cinema Shot / Remastered Video]`）。
   - **微觀（Micro）單鏡並排審片（`SheetReview` & `App.jsx`）**：修正 `App.jsx:pick(a)` 列標註直達；`SheetReview` 支援 `←` / `→` 方向鍵切鏡、同鏡多階段媒體並排對照、原地單步上傳與重拍、以及 `Optical Rig` / `Camera Motion` / `Jutsu Mode` / `@Asset` 快速點選膠囊；`FlowSurface` 專責管理管線並顯示執行器標籤與產出縮圖。

3. **[`docs/specs/SPEC_03_ASSET_BINDING_AND_COMFY_PLATFORM.md`](./docs/specs/SPEC_03_ASSET_BINDING_AND_COMFY_PLATFORM.md) — 靈活參考素材準備（第一幀 ＋ 連續動作結構 ＋ `@Asset`）與外部 ComfyUI JSON 萬用孔位綁定（Step 2B，純後端 Worker，可與 `SPEC_02` 平行施工）**：
   - **負責檔案**：`project_assistant/limb_worker.py`, `workflows/*.json`, `tests/test_studio_worker.py`。
   - **參考素材準備器（`ffmpeg()` 擴充模式）**：新增 `mode: "extract_frame"`（從原片提取第一幀 PNG 供首幀換角定錨）、`mode: "motion_structure"`（從原片製作連續動作結構影片 MP4 供動作控制）與 `layout: "side_by_side"`（並排對比合成）。
   - **參考素材包組裝器（`resolve_studio_context(task)`）**：自動收齊該鏡的 `source_video`、`first_frame`、`motion_structure_video`、`anchor_keyframe`，並跨分頁從 `soul-cast` 解析 `@CAST-01`、`@SET-01`、`@PROP-01` 的多張參考圖（`asset_images` / `asset_map`）與有序編譯 Prompt。
   - **外部 JSON 萬用孔位綁定器（`bind_external_workflow` + `ComfyPlatformClient`）**：不寫死 ComfyUI JSON 內部節點，透過 `input_bindings` 將上述準備好的任意參考素材自動上傳並映射至外部 JSON 指定的 `(node_id, input_name)` 執行（支援 Comfy Router / SDK 與本機 ComfyUI）。

4. **[`docs/specs/SPEC_04_SHOWCASE_SEED_AND_LAUNCHER.md`](./docs/specs/SPEC_04_SHOWCASE_SEED_AND_LAUNCHER.md) — 一鍵啟動器 `run_studio.py` 與預載短劇素材 (`samples/`)（Step 3）**：
   - **負責檔案**：`run_studio.py`, `samples/*`, `README.md`, `tests/test_run_studio.py`。
   - 建立 `run_studio.py` 與 `seed_showcase_media()` 一鍵啟動並掛載 Worker 與範例短劇素材（保持 `templates.tab_specs()` 原始呼叫為空媒體格以 100% 通過 `tests/test_zerofield_baseline.py`）。

5. **[`docs/specs/SPEC_05_DUAL_ENGINE_ALIGNMENT_AND_LINEWORLDS.md`](./docs/specs/SPEC_05_DUAL_ENGINE_ALIGNMENT_AND_LINEWORLDS.md) — 自建 RunningHub 卡片引擎（`Card JSON` + `nodeInfoList`）、雙引擎對位準備器（`MiniMax H3 Ref2VA + H3-Context-IR` & `LTX-2.5 IC-LoRA + Ingredients Sheet`）、代理 8 格時間戳看片與 `line-worlds` 連續動作結構產生器（Step 4）**：
   - **負責檔案**：`project_assistant/limb_worker.py`, `workflows/cards/*.json`, `workflows/minimax_h3_ref2va.json`, `workflows/ltx25_*.json`, `workflows/README.md`, `tests/test_studio_worker.py`。
   - **自建 RunningHub 卡片契約與注入器（`workflows/cards/*.json` + `build_node_info` + `inject_node_info_into_workflow`）**：將 150 節點的 ComfyUI 圖封裝為 6～10 個語意插槽（支援 `locked_nodes` 內部鎖死、`disabled_loras` 設 `"none"` 自動將 `strength_model` 歸零、空媒體槽 `"None"` 自動拔除下游連線），同一份 `Card + nodeInfoList` 通吃本地 ComfyUI、Comfy SDK v2 與 RunningHub WebApp。
   - **智慧排位與代理 8 格看片前置器（`slot_plan` + `mode="frame_sheet"` + `compute_request_fingerprint`）**：自動依出場拍數將有圖的 `@Asset` 排入 `slot="ref"`（排除 `excluded_refs` 禁用素材，純文字道具留空送 `"None"`）；自動從原片抽 8 格帶時間戳總覽圖（`1600x600`）供代理撰寫角色/動作分工指令並以 SHA-256 指紋鎖定。
   - **雙引擎多資產與規格對齊器（`32px` 網格 + `8n+1` / `17n+5` 幀）**：內建本地版 **`H3-Context-IR` 6 段式結構化 Prompt 編譯器**（供 `MiniMax H3`）與 **`mode="ingredients_sheet"` 多資產橫向拼圖器**（供 `LTX-2.5 Ingredients IC-LoRA`）。
   - **多密度動作結構與 `line-worlds` 參數化渲染器**：支援原片 `ref05_edge` / `ref05_depth` 半解析度去皺褶結構片，以及 `line-worlds`（2-Link IK + `stride/turn/reach/flare/camera_zoom` 旋鈕）渲染 **`layout_silhouette`**（色塊剪影片）、**`sparse_tracks`**（彩色錨點軌跡片）與 **`time_strata`**（單張時間摺層殘影圖）。
   - **收片 `.bounded.mp4` 幀數精準裁切與二階段 `@source` 交棒（`h3-reference` ➔ `h3-optimize`）**：自動將 `17n+5` / `8n+1` 多算的尾幀用 FFmpeg CRF 16 切回 `min(請求秒數, 原片秒數)` + `+faststart`，並支援 `@source` 一鍵帶入二階段 4K 修復卡。

6. **[`docs/specs/SPEC_06_RH_STORY_WORKBENCH_AND_MACRO_MESO_MICRO.md`](./docs/specs/SPEC_06_RH_STORY_WORKBENCH_AND_MACRO_MESO_MICRO.md) — 自建 RH STORY 漫劇工作台（`/aivideo/open/v1/*`）與「巨觀 ↔ 中觀 ↔ 微觀」深度整合（Step 5，下一步執行目標）**：
   - **負責檔案**：`project_docs/story_openapi.py`, `project_docs/runtime_http.py`, `project_assistant/limb_worker.py`, `ui/src/Surfaces.jsx`, `ui/src/App.jsx`, `ui/src/StoryWorkbenchModals.jsx`, `ui/src/SheetWorkspace.jsx`, `ui/src/SheetCards.jsx`, `ui/src/SheetReview.jsx`, `ui/src/studioModel.js`, `ui/src/sheetViews.js`, `ui/src/i18n/locales/en.json`, `ui/src/i18n/locales/zh-TW.json`, `tests/test_story_openapi.py`, `ui/tests/storyWorkbench.test.mjs`。
   - **自建 `/aivideo/open/v1/*` 漫劇 OpenAPI 引擎（`project_docs/story_openapi.py`）**：對齊 `docs/references/runninghub-open-api-2026-10-18/` 規範（`{code: 0, msg: "success", data}` 信封、`Idempotency-Key` 24h 去重、64-bit 字串計數、`DRAMA_*` 錯誤碼與對應 HTTP 狀態碼），將 `PROJECT ➔ EPISODE ➔ SCRIPT ➔ ASSETS (含 Variants) ➔ SCENES ➔ STORYBOARD ➔ SHOTS ➔ FILM_EXPORT` 雙向映射至 ZeroField 的 5 張表並串聯底層 `/openapi/v2` ComfyUI 卡片。
   - **頂部五大入口（對齊 RH STORY 導航）**：`Start Creating（開始創作：一鍵劇本導入拆集/提資產/拆鏡）`、`My Projects（我的項目：巨中微觀主工作台）`、`Asset Vault（資產庫：支援 @CAST-01:variant 服裝變體管理）`、`Toolbox（工具箱：檢視與匯入 ComfyUI .json + RunningHub curl 卡片與 nodeId）`、`Open API（開放 API 測試台）`。
   - **巨觀 ↔ 中觀 ↔ 微觀全面升級**：
     - **巨觀（Macro）**：「確認劇本」基線鎖提示列、批次指定 `appCode` 生圖生片、以及「導出整集成片（`POST /episodes/{id}/films` FFmpeg 無縫拼接）」。
     - **中觀（Meso）**：按 `Scene`（場次）分組摺疊的分鏡畫廊、支援 `@CAST-01:night` 服裝變體解析與卡片上一鍵換裝膠囊。
     - **微觀（Micro）**：單鏡多候選歷史條與一鍵挑片（`PUT /shots/{id}/selected-video`）、單鏡拆分（`POST /shots/{id}/splits`）、二階段 4K 修復交棒（`@source`）、以及 `nodeInfoList`（`nodeId` / `fieldName`）進階微調抽屜。
