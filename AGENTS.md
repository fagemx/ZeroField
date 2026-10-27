# ZeroField Studio — Agent Instructions & Guardrails (`AGENTS.md`)

> **2026-10-20 Phase 2 local render bring-up:** Real 4090 renders run through Pipeline → local ComfyUI 0.42.1 → proposal → review with the official open-weights graphs (FLUX 3 Klein keyframes/Soul Cast, LTX-2.5 22B distilled shots with generated audio); interim FLUX.1 dev / LTXV 0.9.7 graphs remain in `workflows/interim/`. S01–S06, Soul Cast references and a 24 s six-shot Director Cut are real renders; local qwen3.8 vision graded the product's 8-frame sheets (S01 72, S02 89, S06 84 pass; S03 58, S04 48, S05 64 retake). Fixed: re-shoot/retry seed advance, still-image prompt phrasing and camera-brand lettering, seed/reference framing leaking into shot prompts, S03 asset tags, official `SaveVideo` API form, story canvas fit. Open SPEC_08 decision: single-step proposals pin the whole source page. See [`docs/PHASE2_PROGRESS.md`](./docs/PHASE2_PROGRESS.md).

> **2026-10-19 SPEC_08 independent review complete (OK with notes):** After explicit user takeover, security and journey reviews of `c3900b4` ran; six journey defects and one card-loader hardening were fixed, and project/episode memory writes are now admin-only by user decision; final product `5cd83d72f4ee5652626fb5ede27d3a70fefd9172` (backend506/frontend119/build/browser4/installed-wheel151 rerun, zero failures/skips). See [review record](./docs/SPEC08_REVIEW.md). Overall acceptance remains the user's decision. The pause/handoff text below is historical.

> **SPEC_08 current handoff:** The lean Console is implemented on product `c3900b440e75c015ef9d6c686667ef8887daaea2`. Integration RAN backend506/frontend119 (zero failures/skips), production build and installed-wheel151-resource identity (12 migrations/17 cards/7 native schemas). Browser4 at the unchanged product is READ evidence, not rerun. Owned PG16 is stopped. Read [current usage](./docs/SPEC08_CONSOLE.md) and [integration verification](./docs/spec08-verification.json) first; independent reviews are **pending**, not passed. Exactly four groups/twelve page IDs: `workspace=[dashboard,api_keys]`, `build=[playground,skills]`, `managed_agents=[quickstart,agents,sessions,deployments,environments,memory_store]`, `analytics=[usage_cost,spend_rate_limits]`. No new Files/Batches/IAM/webhook/OTel/retention or separate cache/log/CLI/integration pages/services. Preserve inherited data/helpers and SPEC_06/07 history. Official Router pricing is native **POST `/estimate`**, not `/price`; quotes are never price locks. Hard is the default; versioned current-admin `estimate_soft` consent permits estimate risk, not a billing guarantee. Project Judge admission remains strict10, including atomic batches/replay/uncertainty. Application controls are not an OS sandbox or hardware-cost guarantee. No paid/credentialed provider calls, CLI launches, model downloads, pushes or deployment are authorized by these receipts.

> **2026-10-19 SPEC_07 corrective verification:** The six accepted review defects at `dda463b271169f3ccee0f9539983e78917aab7ce` have bounded fixes and regression evidence in product candidate `956536dafff7832bcd1c765f459515d9ee536fe0`: live v2 authority/effective-default grants, input-ready allocation/contact-sheet propagation, and same-row review/approved-image handoff. Final integration RAN backend **389**, frontend **111**, build and newly installed-wheel checks; zero test skips. Three same-candidate browser interactions are READ evidence from the UI owner, not rerun by integration. Independent review of `4b77295904990561c59ac877a3cfd91a807b5b08` concluded **OK with notes**, resolving all six original findings with no new blocker identified; see the [durable review](./docs/SPEC07_REVIEW.md). Historical passing totals did not cover the original defects. See the current [receipt](./docs/spec07-verification.json). Live-provider quality, billing and remote cancellation remain unverified.

> **2026-10-19 SPEC_07 integration:** Studio extraction, graphless routing, allocation-backed Story dispatch, explicit project policy, structural preparation and M8-reviewed media races/chains are implemented. See [`docs/SPEC07_STUDIO_ROUTING.md`](./docs/SPEC07_STUDIO_ROUTING.md) and [`docs/spec07-verification.json`](./docs/spec07-verification.json) for current contracts/evidence. Open weights remain the default (media generation and, since SPEC_20, the agent and grader models too); hybrid requires an explicit authorized choice. Synthetic provider/local inference tests do not establish real model quality. The approved SPEC_07 requirements below remain intact; historical “next” wording is not a request to redo completed components.

> **2026-10-19 SPEC_06 implementation:** The RH STORY facade, five-entry workbench, script baseline lock, variants, scene grouping, candidate history, split/merge, card overrides, batches and FFmpeg film export are implemented. See [`docs/STORY_WORKBENCH.md`](./docs/STORY_WORKBENCH.md) and [`docs/story-workbench-verification.json`](./docs/story-workbench-verification.json). Backend 306 / frontend 108 tests and the UI build pass. Migration `162_story_workbench.sql` persists API metadata and uploads; collaborative tabs remain authoritative. GPU/provider inference and external webhook networking were not exercised. The older “SPEC_06 next” descriptions below are historical scope, not a request to implement it again.

> **2026-10-18 bilingual interface update (user-approved batches 1–2):** English is the first-run default and fallback; users may explicitly select Traditional Chinese. All new product UI must use semantic keys in `ui/src/i18n/locales/en.json` and `zh-TW.json`. Keep wire values, M8 / ACP keys, user content and custom names independent of display language. Use `normalizeStatus()` for logic and `statusLabel()` for display. Translated templates, project / AI language settings and video development remain later work. See [`docs/bilingual-baseline.json`](./docs/bilingual-baseline.json).

> **2026-10-18 English contest baseline:** The M8-A–D / ACP / E1 engine is retained. English UI, crew labels, a five-page `zerofield_studio` planning template, and legacy status compatibility are implemented. Backend 241 / frontend 78 tests, UI build, wheel resources, and isolated desktop UI checks passed; see [`docs/english-baseline.json`](./docs/english-baseline.json). Video-specific development, generation workflows, real sample renders, and `run_studio.py` are the next phase. Use README’s Available now section for current capability claims.

> **給接手的 AI 代理（Codex / Claude / Antigravity）**：
> 本專案 **`ZeroField`**（位於 `C:\ai_project\ZeroField`）是專為參加 ComfyUI **「Open Source Higgsfield Challenge」**（截止日：2026-10-30 09:00 PT）獨立出來的參賽專用 Repo。
>
> **動工前請務必依序閱讀以下 5 份核心文件**：
> 1. **[`docs/HANDOFF_4090_PC.md`](./docs/HANDOFF_4090_PC.md)**（**電腦交接首頁**：`SPEC_01`～`SPEC_07` 歷史基底與 **`SPEC_08`** 整合交接，內容止於 `SPEC_08`；更新的規格見下一項）
> 2. **[`docs/specs/`](./docs/specs/)**（**規格目錄，編號越大越新，最新範圍優先**；每份規格開頭的「狀態」列寫明是否已實作。目前最新的是 **[`SPEC_20`](./docs/specs/SPEC_20_PLANNING_AGENT_LAYER_AND_PROVIDER_PRINCIPLES.md)**（規劃代理層與**模型供應商五條原則**）與 **[`SPEC_19`](./docs/specs/SPEC_19_SHOT_COMPOSER_ADOPTION_AND_FILM_PANEL.md)**（鏡頭生成台、採用即成片、引用與接點）。**[`SPEC_08`](./docs/specs/SPEC_08_CLAUDE_CONSOLE_AGENT_PLATFORM.md)** 是 Agent Console 的基底規格，不再是最新範圍：獨立全螢幕 `Agent Console`，四組十二頁、12 範本／空白／自然語言草稿、7 個 Studio／advisor 工具、版本化 Skills／Memory、獨立 Outcome Grader、M8 Sessions、手動／Cron Deployments、Providers／Environments 與合併 Usage／Limits；不新增企業管理頁）
> 3. **[`docs/SPEC07_STUDIO_ROUTING.md`](./docs/SPEC07_STUDIO_ROUTING.md)** 與 **[`docs/STORY_WORKBENCH.md`](./docs/STORY_WORKBENCH.md)**（已完成基底：`SPEC_07` 免開 ComfyUI 閉源路由與 `allocationId` 授權契約、`SPEC_06` RH STORY 漫劇工作台）
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

### ③ Comfy Developer Platform（Comfy Router / SDK）與 Open Weights 核心工作流
- **「必須建構於 Comfy Developer Platform（Comfy Router 和／或 Comfy SDK）之上」是否為比賽規定：待確認**（SPEC_20 R6）。官方頁（comfy.org/open-source-higgsfield，2026-10-27 逐句核對）沒有這條，只寫可以在任何地方執行 ComfyUI，Developer Platform 只出現在導覽列；`docs/HIGGSFIELD_FEATURE_INVENTORY_2026-10-18.md` 寫過這句，但現行官方頁沒有。確認出處前**不要把它寫成比賽規定**，只當成建議。
  - 啟動器預設是本機 ComfyUI：`run_studio.py --platform local`（`run_studio.py:486`；環境變數 `COMFY_PLATFORM` 可改預設值），未指定 `--comfy-url`／`COMFY_BASE_URL` 時工作流直接送到 `127.0.0.1:8188`（`card_engine.comfy_base_url`）。
  - 要走 Developer Platform 才帶 `--platform comfy_sdk`（2026-10-21 自架 GPU 實測通過）：未設 `COMFY_API_KEY` 時接官方 `comfy-api-proxy`（`127.0.0.1:8189`，把本機 ComfyUI 轉成 SDK 的 v2 API），設了金鑰則接 Comfy Cloud。若 R6 確認是規定，展示啟動改用 `--platform comfy_sdk`。
  - Open Weights Only 組的官方規則是不得使用夥伴節點（Partner Nodes）或閉源 API、只能用開放權重模型；本機 ComfyUI 跑開放權重同樣符合，不需要 comfy-api-proxy。Comfy Router 是託管模型（含閉源）的轉接，本專案只在混合模式使用。
  - 已知不相容：`comfy-api-proxy` 0.1.6 要求 `metadata` 是字串，`comfy-sdk` 0.5.0 送的是字典；worker 設定不要帶 `metadata`。
- `workflows/` 內的預設工作流採用 100% 開放權重模型（**`LTX-2.5`** 作為核心影片模型以符合 LTX \$2,000 加碼獎資格 ＋ **`FLUX`** 作為角色／場景資產與首幀模型），同時符合 **Best Overall** 與 **Open Weights Only** 參賽條件。**Open Weights Only 也看代理與評分模型，它們同樣須為開放權重**（預設為本機 Ollama＋`qwen3.8:27b`；SPEC_20 供應商原則 1）。
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
