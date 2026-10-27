# ZeroField Studio — 設計與開發規範 (`DESIGN_AND_DEV_GUIDELINES.md`)

> **2026-10-18 使用者核准更新：** 介面支援 English／繁體中文手動切換；首次開啟及缺漏翻譯時預設英文。下文的 English-First 以英文預設展示為準。新增介面文案須加入 `ui/src/i18n/locales/en.json` 與 `zh-TW.json`，使用語意鍵與完整句子參數。資料庫狀態、工具名稱、角色 ID 與 M8／ACP 協定固定；`normalizeStatus()` 處理狀態邏輯，`statusLabel()` 僅負責顯示。範本與使用者內容保留原文，影片功能仍為下一階段。

本規範適用於所有參與 **`C:\ai_project\ZeroField`** 開發的 AI 代理與工程師。  
目標是確保作品在 **ComfyUI Open Source Higgsfield Challenge**（國際評審團：ComfyOrg、NVIDIA、LTX、Black Forest Labs）獲得最高評分，同時避免破壞底層架構與既有測試。

---

## 1. 語言與國際化規範（English-First UI & Docs）

### 1.1 為什麼必須全英文化？
本賽事的評審與社群使用者皆為英語系開發者與創作者。評審打開 GitHub Repo 與本地 Web UI 的**前 30 秒不能看到滿屏中文辦公術語**（如「跨部門數據」、「行銷主管」、「影片附件」）。

### 1.2 必須英文化的範圍（User-Facing Surfaces）
1. **品牌與頂欄（[`ui/src/Surfaces.jsx`](file:///C:/ai_project/ZeroField/ui/src/Surfaces.jsx)）**：
   - 左上角品牌名改為 **`ZeroField Studio`**（標記為 `ZF` 或電影場記板圖示）。
   - 首頁標題與引導改為電影工作室語境（例如：*"Direct multi-shot cinema & batch V2V illusions on Open Weights."*）。
   - 建立專案對話框預設選中 **`ZeroField Studio (Cinema + OpenJutsu)`** 範本；隱藏或移至次要位置的「行銷與數據（Marketing）」、「空白辦公」範本。
2. **工作區、表格與畫布按鈕（`ui/src/*.jsx`）**：
   - **[`ui/src/MediaCell.jsx`](file:///C:/ai_project/ZeroField/ui/src/MediaCell.jsx)**：
     - `"影片附件"` / `"下載附件"` ➔ 直接改為內嵌 `<video>` 播放器，按鈕文案改為 `"Upload Source"` / `"✦ Re-shoot / Regenerate"`。
   - **[`ui/src/Fields.jsx`](file:///C:/ai_project/ZeroField/ui/src/Fields.jsx) & [`ui/src/format.js`](file:///C:/ai_project/ZeroField/ui/src/format.js)**：
     - 填寫格 placeholder `"點這裡填寫"` ➔ `"Click to add director notes..."`。
   - **[`ui/src/CanvasViews.jsx`](file:///C:/ai_project/ZeroField/ui/src/CanvasViews.jsx) & [`ui/src/FlowPanels.jsx`](file:///C:/ai_project/ZeroField/ui/src/FlowPanels.jsx)**：
     - 節點執行按鈕、狀態提示、多版本審核（[`ui/src/SheetReview.jsx`](file:///C:/ai_project/ZeroField/ui/src/SheetReview.jsx)）統一使用專業英文影視術語（`Run Pipeline`、`Run Selected Shots`、`Approve Take`、`Request Retake`）。
3. **角色名稱與權限標籤（[`project_docs/service.py`](file:///C:/ai_project/ZeroField/project_docs/service.py#L32-L33) & [`project_docs/repository.py`](file:///C:/ai_project/ZeroField/project_docs/repository.py)）**：
   - `ROLE_LABEL` 改為影視劇組職稱：`{"admin": "Showrunner", "director": "Director", "art_lead": "Cinematographer (DP)", "writer": "Screenwriter", "engineer": "VFX TD", "member": "Crew", "viewer": "Client / Viewer"}`。
   - Dev 模式預設測試成員改為英文劇組名單（如 `Alex Rivera (Director)`, `Maya Lin (Cinematographer)`）。

### 1.3 ⚠️ 狀態膠囊（Status Pills）英文化的「白名單防呆鐵律」
- **嚴禁只改前端或只改 `templates.py` 的狀態文字！**
- 後端 [`project_docs/doc_schema.py`](file:///C:/ai_project/ZeroField/project_docs/doc_schema.py#L17) 的 `STATUSES` 是文件儲存的嚴格白名單：
  ```python
  # project_docs/doc_schema.py
  # 必須同時保留舊中文狀態（讓既有 116 個後端單元測試 100% 通過）並加入英文影視狀態：
  STATUSES = (
      "Queued", "In Progress", "Rendering Image", "Rendering Video",
      "Pending Review", "Retake", "Blocked", "Approved",
      # Legacy statuses kept for backward-compatible unit tests:
      "未開始", "進行中", "生圖中", "生影片中", "等待審核", "重抽", "等待回覆", "卡住", "已完成",
  )
  ```
- 前端 [`ui/src/format.js`](file:///C:/ai_project/ZeroField/ui/src/format.js) 的 `STATUSES` 下拉選單則只顯示英文狀態（`Queued`, `In Progress`, `Rendering Image`, `Rendering Video`, `Pending Review`, `Retake`, `Blocked`, `Approved`），並在 `statusClass()` 同時映射中英文狀態的顏色樣式。

---

## 2. 視覺與 UX 設計規範（Cinematic Studio Aesthetic）

1. **影片必須「格內即播（Inline Video Playback）」**：
   - 在 [`ui/src/MediaCell.jsx`](file:///C:/ai_project/ZeroField/ui/src/MediaCell.jsx) 中，`kind === "video"` 時**絕對不可只顯示「▤ 影片附件」文字卡**。
   - 必須渲染 `<video src={media.url} controls muted loop playsInline preload="metadata" className="media-video-player" />`，且在 `compact` 模式下支援滑鼠懸停自動靜音預覽（Hover Play）或點擊放大檢視（Lightbox）。
   - `kind === "video"` 同樣必須顯示 `onRegenerate` 按鈕（`"✦ Re-shoot Take"`），不能只限於 `kind === "image"`。
2. **支援使用者從瀏覽器直接上傳 `.mp4` / `.webm` 原片（OpenJutsu 必備）**：
   - OpenJutsu（Genjutsu V2V）需要使用者在表格的 `Source Driving Video` 欄位上傳實拍影片。
   - 檢查 [`project_docs/http.py`](file:///C:/ai_project/ZeroField/project_docs/http.py) 與 [`project_docs/service.py`](file:///C:/ai_project/ZeroField/project_docs/service.py#L37-L43) 的媒體上傳路由：除了 `IMAGE_MAGIC` 外，必須允許互動端上傳 `video/mp4`（ftyp box magic bytes）與 `video/webm`（`\x1a\x45\xdf\xa3`），且單檔上限放寬至 **64 MB**（與 Worker 上傳上限一致）。
3. **Director's Optical & Motion Picker（光學與運鏡快速選單，拒絕純手打 Prompt）**：
   - 評審在測試 Cinema Studio 時，最期待看到像真實攝影機一樣的控制器（Camera Body、Lens Focal Length、Aperture、Camera Motion）。
   - 在表格編輯或側欄提供視覺化的膠囊選單（Pill Selector），選取後自動同步至該鏡的生成參數。
4. **深色影視調色盤（Dark Studio Theme / High-Contrast Slate）**：
   - 調校 [`ui/src/styles.css`](file:///C:/ai_project/ZeroField/ui/src/styles.css) 與 [`ui/src/workbench.css`](file:///C:/ai_project/ZeroField/ui/src/workbench.css)：頂欄、工作流畫布與媒體預覽區採用深色專業片場質感（如 `#0d0f12` 底色、琥珀金 `#f59e0b` 與霓虹青 `#06b6d4` 強調色），讓分鏡圖片與 `LTX-2.5` 影片畫面在視覺上最突出。

---

## 3. 競賽合規與模型規範（Contest Compliance & Open-Weights Purity）

1. **100% Open-Weights 鐵律（鎖定 RTX 5090 + LTX \$2,000 現金獎）**：
   - `workflows/` 目錄下的所有 ComfyUI API JSON **嚴禁包含任何閉源付費節點（No Partner Nodes / No Closed APIs）**。圖檔本身 100% 開放權重；`workflows/cards/` 裡的閉源與雲端卡片（`kling-v2-master`、`seedance-20-pro`、`rh-cloud-h3-burst`、`router-*.json`）和 `workflows/router/` 的 7 個 Comfy Router 模型定義不是圖檔，只在混合模式（`hybrid_studio` 製作政策）可用，預設的 `open_weights_only` 政策會擋住（`project_assistant/studio/model_router.py` 的 `effective_production_policy`）。
   - 影片生成與 V2V 改造一律以 **`LTX-2.5`** 為核心；首幀與角色資產一律以 **`FLUX 3 Image Klein (5.6B)`** 為核心。
   - **模型供應商五條原則**（SPEC_20 §0.3；規劃與對話代理、連戲評分、媒體生成都適用）：
     1. **預設與展示路徑全部用本機開放權重。** 規劃與評分用 Ollama（`openai_compat` 介面，預設 `http://127.0.0.1:11434/v1`）＋`qwen3.8:27b`；生成用 ComfyUI＋LTX-2.5／FLUX 3。
     2. **託管開放權重是選配。** 例如 OpenRouter 上的同一個模型，給沒有顯示卡的人；由管理者開啟，不在比賽展示路徑。
     3. **閉源模型只在混合模式明確開啟時可用。** 包括 OpenAI、Anthropic、Gemini 與 Comfy Router 的閉源卡；混合模式即 `hybrid_studio` 製作政策。
     4. **不使用 chatgpt.com 訂閱端點；所有模型呼叫都走治理。** 包括連戲評分與快速建立助手。
     5. **非本機呼叫一律要價格上限，並記錄實際用到的模型。**
   - 目前的落實：`openai_compat` 介面相容任何 OpenAI 相容端點，但預設環境只放行本機（`localhost`、`127.0.0.1`、`::1`）。要接託管端點或閉源模型，管理者必須先在 Agent Console 的 Environments & Bridges 放行該主機，並在 Spend & Rate Limits 設定該模型的價格上限，否則治理會拒絕。尚未完成（SPEC_20 R9、R11、R12）：託管開放權重的獨立開關與用量分級、連戲評分與快速建立助手走治理、帳本記錄回應裡的實際模型；在那之前，連戲評分與快速建立助手請只指向本機端點。
   - 拆鏡（劇本到分鏡）預設由規則與範本產生，不呼叫模型（`project_docs/story_adaptation.py`；建立分鏡回傳 `"engine": "deterministic"`）。劇組產生拆鏡提案屬 SPEC_20 的規劃包（C 包），尚未實作。
2. **SFW 與版權／肖像權合規（Official Rule: Legal, SFW, No Unauthorized IP/Likeness）**：
   - 預載於 `samples/` 與展示專案中的所有圖片、實拍原片（Driving Videos）、角色名稱與 Prompt：
     - **嚴禁使用真實名人／演員姓名或臉部照片**（例如不可寫 Keanu Reeves、Scarlett Johansson）。
     - **嚴禁使用受版權保護的電影／動漫原片截圖**（例如不可拿《駭客任務》或《火影忍者》片段當 OpenJutsu 原片）。
     - 統一使用原創科幻／黑色電影角色（如 `Detective Kael`、`Aria Vance`）以及 CC0／自製實拍素材。

---

## 4. 工程與建置鐵律（Build, Test & Windows Environment Rules）

1. **改完前端 `ui/src/` 必須重新編譯 `static/projects/`！**
   - Python 伺服器（`server.py`）直接提供 `static/projects/` 下的編譯後資產。
   - **每次修改 `ui/src/` 下的任何檔案後，必須執行**：
     ```powershell
     npm run build --prefix ui
     ```
     否則瀏覽器打開 `http://127.0.0.1:3020` 看到的永遠是舊畫面！
2. **保持既有測試相容性**：
   - 修改後端 `project_docs/` 或 `project_assistant/` 時，避免破壞既有 API 簽章與資料表欄位。
   - 驗證指令：
     - 後端測試：`python -m unittest discover -s tests -v`
     - 前端測試：`npm test --prefix ui`
3. **Windows 開發環境注意事項**：
   - 指令優先使用 **PowerShell**。
   - Python 執行檔路徑：`C:\Users\synvoke\AppData\Local\Programs\Python\Python312\python.exe`（或專案下的 `.venv\Scripts\python.exe`）。
   - 處理含多語系字元的 Python 腳本請加上 `python -X utf8`，存檔確保 UTF-8 編碼。
   - `git add` 請指定明確路徑，不要把臨時測試資料庫檔案或超大未壓縮暫存檔提交進 Git。

---

## 5. 影音播放效能、快取與記憶體管理鐵律（Playback Performance, Caching & Memory Management）

因為 `ZeroField` 是多鏡頭分鏡表（Cinema Studio）與多變體矩陣（OpenJutsu）的**影片編輯工作台**，一個分頁可能同時出現 20～60 個影片格。**若直接套用原本處理小圖的方式處理影片，會導致資料庫記憶體爆滿與瀏覽器硬體解碼器崩潰**。施工時必須落實以下 5 條效能規範：

### 5.1 修復 `/meta` 端點「全量讀取 64 MB `bytea`」的記憶體炸彈
- **現況問題**：[`project_docs/http.py`](file:///C:/ai_project/ZeroField/project_docs/http.py#L472-L476) 的 `asset_meta` 呼叫了 `repo.get_asset(conn, slug, asset_id)`，把整支 64 MB 的影片 `data` 從 PostgreSQL 撈進 Python RAM，只為了算 `len(found[1])`！當分鏡表有 20 個鏡頭時，一開頁面就會瞬間從資料庫拉出超過 1 GB 的 binary。
- **強制修正**：
  - `projectops.asset` 資料表**原本就有 `byte_size` 欄位**（見 [`project_docs/repository.py`](file:///C:/ai_project/ZeroField/project_docs/repository.py#L725-L731)）。
  - 在 `repository.py` 新增輕量查詢 `get_asset_meta(conn, slug, asset_id)`，只執行：
    ```sql
    SELECT content_type, byte_size FROM projectops.asset WHERE project_slug = %s AND asset_id = %s
    ```
  - 讓 `asset_meta` 實現 **0 Bytes Blob 讀取**。

### 5.2 支援 HTTP `Range`（`206 Partial Content`）與 `304 Not Modified` 短路快取
- **現況問題**：HTML5 `<video>` 標籤需要 `Accept-Ranges: bytes` 與 `206 Partial Content` 才能拖曳時間軸（Seek / Scrub）、快速讀取檔頭資訊（`preload="metadata"`）與無縫循環播放。
- **強制修正（[`project_docs/http.py`](file:///C:/ai_project/ZeroField/project_docs/http.py#L477-L486) & `server.py`）**：
  1. **ETag 短路檢查**：由於 `pa_<32hex>` 是 SHA-256 內容尋址（Content-Addressed，100% 不可變），在查詢資料庫前先檢查請求標頭 `If-None-Match` 是否包含 `"{asset_id}"`；若命中直接回傳 `304 Not Modified`，完全不碰資料庫與記憶體。
  2. **本地磁碟快取層（Local Disk Asset Cache）**：當從 PostgreSQL 讀取 `pa_<32hex>` 資產（特別是 `video/*`）時，可將其寫入本地暫存快取目錄（如 `.cache/assets/{asset_id}`），後續請求直接由本地檔案系統讀取區段（`file.seek(start)` + `file.read(length)`），避免重複將數十 MB 的 `bytea` 載入 Python Heap。
  3. **支援 `Range: bytes=start-end`**：解析 HTTP `Range` 標頭，回傳 `206 Partial Content`、`Accept-Ranges: bytes` 與 `Content-Range: bytes {start}-{end}/{total}`。

### 5.3 瀏覽器 `<video>` 硬體解碼器上限與 DOM 記憶體管理（[`ui/src/MediaCell.jsx`](file:///C:/ai_project/ZeroField/ui/src/MediaCell.jsx)）
- **現況風險**：Chromium 瀏覽器對單一分頁的硬體 `<video>` 解碼器（`WebMediaPlayer`）有嚴格上限（約 16～32 個）。若表格內 40 個影片格同時掛載並解碼播放，會造成瀏覽器卡死或黑畫面。
- **強制設計**：
  1. **前端模組級 `/meta` 快取（`META_CACHE`）**：在 `MediaCell.jsx` 頂層建立 `const META_CACHE = new Map();`，同一個 `media.url` 在整個瀏覽器工作階段只發送一次 `/meta` 請求，切換分頁或捲動表格時零重複請求。
  2. **按需解碼（Hover-to-Play / Active-Only Decoding）**：
     - 表格預設靜止狀態下，影片格使用 `preload="metadata"`（僅抓首幀與時長），**不自動全部同時播放**。
     - 僅當滑鼠懸停（`onMouseEnter`）或聚焦於該格時才呼叫 `videoRef.current.play()`；滑鼠移開（`onMouseLeave`）或組件卸載時立刻 `pause()`。
     - 僅在「Multi-Take 並排審核面板（`SheetReview.jsx`）」或「Lightbox 檢視器」中才同時同步播放 2～3 個候選 Take。
  3. **釋放 Blob URL**：任何上傳預覽若使用 `URL.createObjectURL(file)`，必須在卸載或上傳完成後呼叫 `URL.revokeObjectURL()`。

### 5.4 FFmpeg 輸出強制加上 `-movflags +faststart`
- 在 [`project_assistant/limb_worker.py`](file:///C:/ai_project/ZeroField/project_assistant/limb_worker.py#L317-L329) 中，不論是全片串接（`concat`）還是 OpenJutsu 的「左右並排對比影片（`side_by_side`）」，FFmpeg 最終輸出的 `.mp4` **一律必須加上 `-movflags +faststart`**，將 `moov` 索引移至檔案最前端，確保瀏覽器透過 HTTP Range 在 50ms 內就能開始播放。

