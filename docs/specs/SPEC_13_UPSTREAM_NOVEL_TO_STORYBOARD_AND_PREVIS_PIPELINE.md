# SPEC 13 — 前段短劇流水線補完：一句話／小說改編、智慧資產提取、多鏡位分鏡拆解與 3D Previs 自動走位（借鏡 ViMax / 火寶短劇 / Jellyfish / Toonflow）

> **狀態**：Ready for Execution（可與 `SPEC_12` 獨立或依序執行，檔案零衝突：`SPEC_12` 改 `ui/src/previs/*`，本規格改 `project_docs/story_openapi.py` 與 `ui/src/StoryWorkbenchModals.jsx`）
> **核心原則**：**不新增獨立工作台**，直接強化現有頂部 **`Start Creating（開始創作）`** 與 **`Asset Vault（資產庫）`** 的前段流水線，把「一句話點子／長篇小說／粗略劇本」一路打通到我們獨有的「Soul Cast 資產表 + Cinema 分鏡表 + 3D Previs 舞台走位」！

---

## 0. 現況診斷：為什麼我們「前面流程」是斷的？

對照目前 GitHub 最火的 6 個 AI 短劇開源專案（**火寶短劇 `huobao-drama`**、**`Toonflow`**、**`Pixelle-Video`**、**`Jellyfish`**、**`waoowaoo`**、港大 **`ViMax`**），它們之所以能做到「小說/一句話進去 → 分鏡與成片出來」，是因為它們在前段都有 **4 個標準轉換步驟**：
1. **`script_rewriter`（ViMax `Idea2Video` / `Novel2Video`）**：把「一句話靈感」擴寫成多場戲，或把「長篇小說章節」壓縮改編成結構化短劇劇本（含場次標題、環境描述、人物動作、對白）。
2. **`extractor`（Jellyfish / 火寶資產提取器）**：從劇本自動抽取並去重 **角色（`@CAST` 含外貌/服裝變體）**、**場景（`@SET` 含光影與遠中近景深描述）**、**關鍵道具（`@PROP`）**，生成可直接餵給生圖模型的定妝照 Prompt。
3. **`storyboard_breaker`（多鏡位分鏡拆解器）**：把一場戲拆成 **3～6 顆連續電影分鏡**（遠景建立鏡頭 → 中景走位 → 過肩對白 → 特寫情緒反應），每顆鏡頭配好景別、運鏡、出場資產與台詞。
4. **`shot_readiness`（Jellyfish 分鏡就緒檢查與資產一鍵補齊）**：檢查每顆鏡頭引用的 `@CAST` / `@SET` 是否已有參考圖，一鍵批次生成缺圖資產。

反觀我們目前的 `project_docs/story_openapi.py`（第 167～462 行）：
- `scene_sections()`：只認得寫死的 `Scene 01` 或 `INT./EXT.`，如果使用者貼進一段小說或一句話點子，全部會被塞進同一個 `Scene 01`。
- `extract()`：只跑一行簡單正則，且把場景描述寫死成無意義的 `"Reference for @SET-01"`，完全沒抽角色外貌、服裝變體或場景細節。
- `build_shots()`：**一場戲永遠只生 1 顆鏡頭（`SC01-S01`）**，而且把攝影機寫死成 `"ARRI Alexa 65 / 35mm Anamorphic f/1.4"` + `"Static Tripod"`，也沒有自動幫我們的王牌武器 **`3D Previs Stage`** 配好焦段、運鏡與假人動作！

---

## 1. 最高防呆鐵律（確保 `tests/test_story_openapi.py` 與 `story-ui.test.mjs` 100% 通過）

執行代理修改 `project_docs/story_openapi.py` 與 `ui/src/StoryWorkbenchModals.jsx` 時，**必須嚴格遵守以下相容性守衛**：

1. **`test_story_openapi.py` 單句場景相容性**：
   - 既有測試 `prepare()` 與 `test_multi_episode_shots_variants_patch_and_scene_rebuild` 會傳入只有單句內容的場景（例如 `"Scene 01: Second\n@CAST-02 runs."`），並斷言 `len(second) == 1` 以及 `self.assertIn('ARRI Alexa', shots[0]['opticalRig'])`、`detail['counts']['succeeded'] == '2'`。
   - **防呆規則**：
     - 當一個 `Scene` 內部只有 **1 個動作句／段落**（且未指定 `breakdownMode="cinematic_multi"`）時，`build_shots()` **必須維持產出 1 顆鏡頭（`SCxx-S01`）**，且第一顆鏡頭的 `opticalRig` 字串必須包含 `"ARRI Alexa"`（例如 `"ARRI Alexa 65 / 35mm Anamorphic f/1.4"`）！
     - 當一個 `Scene` 包含 **多個分鏡段落／多句動作對白標記**（如以空行分段、`- [Shot]` 標記、或多輪角色對白 + `breakdownMode="cinematic"`）時，`build_shots()` 才會將該場戲拆解為 `SCxx-S01`, `SCxx-S02`, `SCxx-S03`... 多顆連續鏡頭！
2. **`Start Creating` 按鈕 DOM 契約（`ui/tests/story-ui.test.mjs`）**：
   - `StoryWorkbench` 頂部的 `<button disabled={!writable || action.busy} onClick={() => open('import')}>...Start Creating</button>` 以及 `ImportModal` 的標題與現有欄位不可刪除。

---

## 2. 負責檔案與架構（Worker Bundles）

| Bundle | 模組名稱 | 負責檔案 | 說明 |
| :--- | :--- | :--- | :--- |
| **Bundle A** | **後端短劇改編、深度資產提取與多鏡位 Previs 分鏡引擎** | `project_docs/story_openapi.py`, `project_docs/runtime_http.py`, `tests/test_story_openapi.py` | 實作 `Idea2Script / Novel2Script` 改編、深度 `@CAST/@SET/@PROP` 外貌描述提取、多鏡位拆解 + 自動配給 `Optical Rig` / `Camera Motion` / `previsPlan` 與 Shot Readiness 檢查 |
| **Bundle B** | **前端 `Start Creating` 三模式入口（一句話／小說／劇本）與資產一鍵就緒** | `ui/src/StoryWorkbenchModals.jsx`, `ui/src/i18n/locales/en.json`, `ui/src/i18n/locales/zh-TW.json`, `ui/tests/story-ui.test.mjs` | 在現有 `Start Creating` 彈窗加入「一句話靈感 / 小說改編 / 標準劇本」模式、分鏡密度選擇，以及 `Asset Vault` 一鍵補齊缺圖資產 |

---

## 3. Bundle A 詳細規格：後端前段流水線升級（`project_docs/story_openapi.py`）

### 3.1 新增「一句話／長篇小說 ➔ 結構化短劇劇本」改編器（對應 ViMax `Idea2Video / Novel2Video` & 火寶 `script_rewriter`）

1. **新增純函數 `adapt_source_to_script(raw_text, mode="auto", target_scenes=3, style_name="Sci-Fi Noir Anamorphic")`**：
   - **自動識別輸入類型（`mode="auto"`）**：
     - **`"idea"`（一句話靈感／短綱，字數 `< 240` 且無 `Scene` 標題）**：自動擴寫為 `target_scenes` 場結構化短劇劇本（起承轉合：建立衝突 ➔ 危機推進 ➔ 高潮反轉），自動分配 `@CAST-01`, `@CAST-02`, `@SET-01`, `@PROP-01` 與分鏡節拍段落。
     - **`"novel"`（長篇小說／散文段落，無 `Scene` 標題但有多段敘事與引號對白 `"..."` / `「...」`）**：
       - 自動按場景轉換詞（時間／地點切換或每 2～4 個敘事段）切分為 `## Scene 01: <地點與氛圍>`、`## Scene 02: ...`；
       - 自動識別小說中的人物名稱與引號對白，轉寫為標準劇本格式（`Character: Name (appearance traits)`、動作描寫段落、以及 `NAME: "Dialogue line"`），確保每個分鏡節拍以空行分隔。
     - **`"script"`（已有 `Scene` / `INT.` / `EXT.` 標題的劇本）**：保持原有結構並標準化標題。
2. **新增／擴充 API 端點 `POST /aivideo/open/v1/episodes/{episodeId}/script-adaptations`**：
   - 請求 Body：`{ "sourceText": "...", "sourceMode": "auto" | "idea" | "novel" | "script", "targetScenes": 3, "breakdownMode": "auto" | "scene" | "cinematic" }`
   - 支援雙引擎：
     - 若環境已設定 LLM Provider（`OPENBENCH_MODEL` + `OPENBENCH_API_BASE`），可呼叫 LLM 產生結構化劇本；
     - **內建確定性離線引擎（Zero-LLM Deterministic Adapter）**：即使未設定外部 LLM API Key，也能透過內建規則與敘事節拍模板，100% 離線將「一句話點子」或「小說段落」改寫為帶 `## Scene XX`、`@CAST-XX`、`@SET-XX`、`@PROP-XX` 與多節拍分段的標準短劇劇本，並寫入該集 `set_script()`！

### 3.2 升級 `extract(conn, me, ep)`：深度提取角色外貌、服裝變體、場景 2.5D 描述與道具（對應火寶 `extractor` & Jellyfish 資產一致性）

修改 `project_docs/story_openapi.py` 的 `extract(conn, me, ep)`，保留原有 `@CAST-xx` / `Character:` 識別邏輯，並大幅強化自動生成的資產 Prompt 與分類：

1. **角色（`@CAST-xx`）外貌與定妝 Prompt 提取**：
   - 從劇本中的 `Character: Name (traits)`、`@CAST-01 (traits)` 或人物出場首句描寫中提取外貌特徵；
   - 自動組裝適合 `flux-soul-cast` 的一致性定妝描述（例如：`"{name}, {extracted_traits}, cinematic character portrait, consistent facial structure, neutral studio rim lighting"`，若無額外描述則保留 `name.strip()` 以相容舊測試）。
   - 若劇本中出現 `@CAST-01:night` 或 `@CAST-01#injured` 等變體標記，自動在 `soul-cast` 建立對應的變體列（`kind = "OUTFIT"`）。
2. **場景（`@SET-xx`）環境與 2.5D 景深描述提取**：
   - 不再只寫死 `"Reference for @SET-01"`！
   - 自動從各場次的標題（`## Scene 01: Rooftop Rain at Midnight`）與首句環境描寫提取場景名稱與視覺 Prompt（例如：`"Reference for @SET-01 — Rooftop Rain at Midnight, wide cinematic environment plate, clear foreground/midground/background depth layers, no characters"`），讓生成的 `@SET` 圖天然適合 `SPEC_11` 的 **2.5D Parallax 舞台**！
3. **關鍵道具（`@PROP-xx`）自動提取**：
   - 識別劇本中的 `@PROP-xx` 或 `Prop: Name` 標記並寫入 `soul-cast`。

### 3.3 升級 `build_shots(conn, me, ep, only_scene=None, breakdown_mode=None)`：多鏡位拆解 + 自動配給鏡頭語法與 3D Previs 計畫（對應火寶 `storyboard_breaker` + ZeroField 3D Stage）

這是連接「前段文字劇本」與我們「後段 3D Previs + LTX-2.5」最核心的橋樑！

1. **智慧分鏡節拍切分 `scene_shot_beats(scene_content, breakdown_mode="auto")`**：
   - **相容守衛**：若 `scene_content` 只有單一段落／單句（如舊測試的 `"@CAST-01 walks past @PROP-01."`），且 `breakdown_mode` 非 `"cinematic"`，回傳長度為 `1` 的列表 `[scene_content.strip()]`（確保舊測試 `len(shots) == 1` 100% 通過！）。
   - 當 `scene_content` 含有多個以空行分隔的節拍段落（`\n\n+`）、或明確的 `Shot 1:` / `- ` 列表、或 `breakdown_mode == "cinematic"` 時，將該場戲拆分為多個分鏡節拍 `SC{sceneIndex:02d}-S{shotIndex:02d}`（例如 `SC01-S01`, `SC01-S02`, `SC01-S03`）。
2. **自動推導電影攝影機語法與 3D Previs 計畫 `infer_shot_grammar(beat_text, beat_index, total_beats)`**：
   - 根據節拍文字關鍵字與在場次中的位置（首鏡建立、中段互動、尾鏡高潮），自動配給：
     - **首鏡（`beat_index == 0` 且無特定特寫關鍵字）**：
       - `opticalRig`: `"ARRI Alexa 65 / 35mm Anamorphic f/1.4"`（**注意：首鏡維持包含 `ARRI Alexa` 以 100% 通過 `test_story_openapi.py` 第 161 行斷言！**）
       - `cameraMotion`: 依關鍵字自動選配（若含 `walk / enter / approach / 走` 則配 `"Slow Dolly In"`；若含 `run / chase / 跑` 則配 `"Handheld Tracking"`；否則預設 `"Static Tripod"`）。
     - **後續分鏡（`beat_index >= 1`）**：
       - 自動根據動作與情緒關鍵字交替分配專業鏡位：
         - 對白／互動：`opticalRig = "Panavision Millennium DXL2 / 50mm Prime"`, `cameraMotion = "Slow Dolly In"`
         - 環繞／對峙：`opticalRig = "RED V-Raptor XL / 35mm T1.5"`, `cameraMotion = "Orbit 45°"`
         - 情緒特寫／驚訝／崩潰（含 `close-up / eyes / tears / shock / dial / hand / 特寫`）：`opticalRig = "Sony Venice 2 / 85mm Macro"`, `cameraMotion = "Crane Up"` 或 `"Slow Dolly In"`
     - **自動提取對白與配音時間軸（`dialogue`）**：
       - 若該節拍含有角色台詞（如 `CAST-01: "We are out of time."` 或 `「沒時間了。」`），自動抽取出 `{ speaker, line, estimatedSeconds }` 存入該鏡的 `shot_meta`（`meta_sh_...`），供字幕與 TTS 使用。
     - **自動產生 3D Previs 初始計畫（`previsPlan`）並存入 `shot_meta`**：
       - 自動映射為 `PrevisStage` 的標準 `plan`：`{ set: "parallax", lens: 24|35|50|85, move: "pushin"|"orbit"|"track"|"crane"|"static", action: "walkin"|"turnreach"|"stand", facing: "console"|"room", seconds: 4 }`，讓導演切去 `3D Stage` 時，每顆鏡頭的攝影機焦段、運鏡軌跡與演員動作已經根據劇本自動排好！

### 3.4 新增分鏡就緒度檢查（Shot Readiness Check，借鏡 Jellyfish）

- 在 `shot_view(conn, slug, row)` 回傳物件中新增欄位 `readiness`（不影響既有欄位）：
  ```python
  "readiness": {
      "ready": bool,              # 所有引用的 @CAST / @SET 是否都已有參考圖或該鏡已有首幀/預演片
      "missingAssets": list[str], # 尚未生成參考圖的 @CAST-xx / @SET-xx 代碼清單
      "hasPrevis": bool,          # 是否已渲染 3D Previs / Pose Skeleton
      "hasDialogue": bool,        # 是否包含台詞
  }
  ```
- 新增端點 `POST /aivideo/open/v1/episodes/{episodeId}/asset-image-generations`：
  - 一鍵為該集所有尚無 `selectedImageUrl` 的 `@CAST` 與 `@SET` 資產派發圖片生成任務（預設使用 `flux-soul-cast` 或呼叫端傳入的 `appCode`），回傳 `taskGroupId` 與 `taskIds`，徹底解決以前抽完資產還要手動一格一格點生圖的痛點！

---

## 4. Bundle B 詳細規格：前端 `Start Creating` 升級與一鍵資產生成（`ui/src/StoryWorkbenchModals.jsx`）

### 4.1 升級 `ImportModal`（`Start Creating` 彈窗）

在完全保留現有 `Start Creating` 欄位與測試相容的前提下，將 `ImportModal` 升級為支援 **3 種創作起點**（模仿火寶短劇 / ViMax / Toonflow 的無門檻入口）：

1. **創作起點切換（Source Mode Selector）**：
   - **`Idea / Logline（一句話靈感）`**：輸入一句話（例如：*"A lone astronomer discovers the sun beacon is a countdown timer and tries to smash the brass dial."*），點 **`Adapt to Multi-Scene Script（AI 擴寫為多場短劇劇本）`** 即呼叫 `POST /episodes/{epId}/script-adaptations` 將下方劇本框自動填入包含 3 場戲、`@CAST`、`@SET` 與多節拍分鏡的完整劇本。
   - **`Novel / Story Chapter（長篇小說／故事改編）`**：貼入整章小說或上傳 `.txt / .md`，點 **`Adapt to Multi-Scene Script`** 自動拆場、提角色外貌、轉對白並切分鏡節拍。
   - **`Screenplay（標準分場劇本，預設）`**：直接編輯或貼上劇本。
2. **一鍵流水線按鈕（`Confirm Script & Build Storyboard`）**：
   - 若目前劇本框內沒有 `Scene` 標題且選在 `Idea` 或 `Novel` 模式，點擊主按鈕時自動先執行 `script-adaptations` 轉成結構化多節拍劇本，接著自動跑完 `asset-extractions` ➔ `storyboards`，一步到位產出角色資產與多鏡位分鏡表！

### 4.2 升級 `AssetVaultModal`：一鍵生成全部缺圖資產（Batch Generate Missing Assets）

- 在 `AssetVaultModal` 頂部新增 **`Generate Missing Asset Sheets`（一鍵生成缺圖角色/場景定妝照）** 按鈕：
  - 當該集有尚未生成圖片的 `@CAST` / `@SET` 時，點擊即可呼叫 `POST /episodes/{epId}/asset-image-generations` 批次生圖，讓所有分鏡快速達到 Jellyfish 的 `Shot Ready` 狀態。

---

## 5. 驗收標準與執行指令（Acceptance Criteria）

執行代理完成後，必須依序跑過以下驗證並確保 **0 failures / 0 skips**：

1. **後端 Story OpenAPI 單元與整合測試**：
   ```bash
   pytest tests/test_story_openapi.py
   ```
   - 既有 11 個測試項目 **100% 原樣通過**（特別確認單句 `Scene 01` 仍產出 1 顆鏡頭且首鏡含 `ARRI Alexa`）。
   - 新增測試驗證：
     - `adapt_source_to_script`：輸入一句話靈感（`mode="idea"`）或無 `Scene` 標題的小說段落（`mode="novel"`），能離線自動拆出多場 `## Scene 01..03`、提取角色與對白並分段；
     - 多節拍場景（含 3 個空行分隔段落或 `breakdownMode="cinematic"`）呼叫 `build_shots` 後，自動拆出 `SC01-S01`, `SC01-S02`, `SC01-S03` 多顆鏡頭，且自動配給不同焦段/運鏡、`dialogue` 與 `previsPlan`；
     - `shot_view` 正確回傳 `readiness.missingAssets`，且 `POST /episodes/{id}/asset-image-generations` 能批次為缺圖資產建立生圖任務。
2. **前端 UI 與雙語字典測試 + 正式編譯**：
   ```bash
   node --test ui/tests/story-ui.test.mjs ui/tests/studio-ui.test.mjs ui/tests/i18n.test.mjs
   npm run build --prefix ui
   ```
