# ZeroField Studio — Agent Instructions & Guardrails (`AGENTS.md`)

> **2026-10-18 English contest baseline:** The M8-A–D / ACP / E1 engine is retained. English UI, crew labels, a five-page `zerofield_studio` planning template, and legacy status compatibility are implemented. Backend 241 / frontend 78 tests, UI build, wheel resources, and isolated desktop UI checks passed; see [`docs/english-baseline.json`](./docs/english-baseline.json). Video-specific development, generation workflows, real sample renders, and `run_studio.py` are the next phase. Use README’s Available now section for current capability claims.

> **給接手的 AI 代理（Codex / Claude / Antigravity）**：
> 本專案 **`ZeroField`**（位於 `C:\ai_project\ZeroField`）是專為參加 ComfyUI **「Open Source Higgsfield Challenge」**（截止日：2026-10-30 09:00 PT）獨立出來的參賽專用 Repo。
>
> **動工前請務必依序閱讀以下 3 份核心文件**：
> 1. **[`docs/DESIGN_AND_DEV_GUIDELINES.md`](./docs/DESIGN_AND_DEV_GUIDELINES.md)**（必讀！英文介面規範、`STATUSES` 白名單防呆、影片播放器、Open-Weights 與版權合規鐵律）
> 2. **[`docs/ZEROFIELD_SPEC.md`](./docs/ZEROFIELD_SPEC.md)**（參賽改造完整規格與 Task 1～4 交付清單）
> 3. **[`docs/AGENT_ORCHESTRATION_SPEC.md`](./docs/AGENT_ORCHESTRATION_SPEC.md)**（多代理拆鏡、Multi-Take 並排盲測與自動審片規格）

---

## 1. 最高優先級開發鐵律（Top Guardrails — 違反任一條將導致失格或畫面壞掉）

### ① 全英文使用者介面（English-First UI for International Judges）
- 評審為 ComfyOrg、NVIDIA、LTX、Black Forest Labs 國際團隊，**所有看得到的畫面、按鈕、預設展示專案、角色職稱（Showrunner / Director / Cinematographer）與範本一律使用專業英文影視術語**。
- **⚠️ 狀態膠囊（Status Pills）白名單防呆**：
  - 後端 [`project_docs/doc_schema.py`](./project_docs/doc_schema.py) 第 17 行的 `STATUSES` 是資料庫存檔的嚴格白名單！
  - 新增英文狀態（`"Queued"`, `"In Progress"`, `"Rendering Image"`, `"Rendering Video"`, `"Pending Review"`, `"Retake"`, `"Blocked"`, `"Approved"`）時，**必須同時更新 `project_docs/doc_schema.py` 的 `STATUSES` 與前端 `ui/src/format.js`**，且在後端 `doc_schema.py` 保留舊中文狀態字串以免既有單元測試失敗！

### ② 解除舊版「不顯示影片播放器」限制 — 全面開啟格內 `<video>` 播放與上傳
- 在 [`ui/src/MediaCell.jsx`](./ui/src/MediaCell.jsx) 中，`kind === "video"` 時**必須渲染內嵌 `<video controls muted loop playsInline preload="metadata">` 播放器**（不可只顯示「影片附件」文字卡），並開啟影片格的 `onRegenerate`（`"✦ Re-shoot Take"`）按鈕。
- 在 [`project_docs/service.py`](./project_docs/service.py) 與 [`project_docs/http.py`](./project_docs/http.py) 的互動媒體上傳路由中，除圖片外**必須允許使用者從瀏覽器直接上傳 `video/mp4` 與 `video/webm`（上限 64 MB）**，供 OpenJutsu V2V 欄位上傳實拍原片。

### ③ 100% Open Weights & 合規素材（鎖定 RTX 5090 + LTX \$2,000 + Best Overall \$10,000）
- `workflows/` 內的所有 ComfyUI API JSON **嚴禁使用任何閉源付費 Partner Nodes**，100% 採用開放權重模型：**`LTX-2.5`**（核心 I2V 運鏡與 V2V 動作轉移／換物）＋ **`FLUX 3 Image Klein (5.6B)`**（核心角色資產與首幀）。
- `samples/` 與預設專案素材必須 **100% SFW、無版權爭議、無真實名人姓名或肖像**。

### ④ 改完前端 `ui/src/` 必跑 `npm run build --prefix ui`
- `server.py` 讀取的是編譯後的 `static/projects/`。每次修改 `ui/src/` 後，**必須執行 `npm run build --prefix ui`**，否則瀏覽器畫面不會更新！

### ⑤ 影音播放效能、快取與記憶體管理（防爆 RAM 與解碼器崩潰）
- **`/meta` 零 Blob 查詢**：在 [`project_docs/repository.py`](./project_docs/repository.py) 新增 `get_asset_meta()` 只查 `SELECT content_type, byte_size FROM projectops.asset`，嚴禁在 `/meta` 路由呼叫 `get_asset()` 把 64 MB 影片撈進記憶體！
- **HTTP `Range` (`206 Partial Content`) + `ETag` (`304`) + 本地磁碟快取**：在 [`project_docs/http.py`](./project_docs/http.py) 的 `asset` 路由實作 `If-None-Match` 短路、`.cache/assets/` 磁碟快取與 `Range: bytes=start-end` 區段讀取，讓 `<video>` 能秒開與自由拖曳時間軸。
- **前端 `MediaCell.jsx` 記憶體防護**：建立模組級 `META_CACHE = new Map()` 避免重複打 `/meta`；表格內的 `<video>` 預設 `preload="metadata"` 靜止顯示首幀，**僅在滑鼠懸停（Hover）或點開審核時才播放（`play()`）**，移開即 `pause()`，避免超過瀏覽器硬體解碼器上限（~16–32 個）。
- **FFmpeg `+faststart`**：所有 `limb_worker.py` 產出的 MP4（含 `side_by_side` 對比片）一律加上 `-movflags +faststart`。

---

## 2. 優先施工任務（詳見 `docs/ZEROFIELD_SPEC.md`）

1. **Task 1 — 後端 `limb_worker.py` 與影片上傳升級**：
   - 在 `comfyui()` 支援 `video_node`（自動上傳分鏡表中的 `.mp4` 原片至 ComfyUI `/upload/image` 綁定 `LoadVideo` 節點）。
   - 支援 `param_bindings` 與光學預設編譯（將表格中的 `Optical Rig`、`Camera Motion` 注入 ComfyUI 節點）。
   - 在 `ffmpeg()` 新增 `layout: "side_by_side"`（`hstack` 左右並排對比影片合成，一鍵產出「原片 vs. LTX-2.5 改造片」Viral MP4）。
   - 放寬 `service.py` 互動上傳支援 `.mp4` / `.webm`（64 MB）。
2. **Task 2 — 旗艦英文範本 `zerofield_studio`（`project_docs/templates.py` & `doc_schema.py`）**：
   - 擴充 `doc_schema.py` 的 `STATUSES` 白名單。
   - 建立內建英文展示專案與範本，包含：`director-brief`、`soul-cast`、`cinema-studio`、`openjutsu-lab`、`comfy-pipeline`。
3. **Task 3 — 前端 `ui/src/` 英文影視級改造**：
   - 英文化 `Surfaces.jsx`、`MediaCell.jsx`、`Fields.jsx`、`format.js`、`SheetReview.jsx`、`FlowPanels.jsx`。
   - 開啟影片格內嵌 `<video>` 播放器與 Multi-Take 版本切換。
   - 新增 **Director's Optical & Motion Picker**（快速選擇 ARRI/RED 機身、Anamorphic 焦段、Dolly/Handheld/Orbit 運鏡）。
   - 執行 `npm run build --prefix ui` 並驗證畫面。
4. **Task 4 — 一鍵啟動器 `run_studio.py` 與預載 Open-Weights Workflows (`workflows/`)**：
   - 讓評審只需一行指令即可同時啟動 Server + Worker 並看到預載的展示專案。
