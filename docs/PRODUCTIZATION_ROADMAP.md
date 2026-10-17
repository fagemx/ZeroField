# OpenBench 產品化完整開發藍圖與代理施工規格書 (`PRODUCTIZATION_ROADMAP.md`)

> **最新交付：本輪可用性重整已實作並完成代理操作走查。** 使用者於 2026-10-16 授權「照你研究的規劃內容開工做完」。設計依據為 [`PRODUCT_UX_REPLAN.md`](./PRODUCT_UX_REPLAN.md)，交付及操作證據見 [`UX_IMPLEMENTATION.md`](./UX_IMPLEMENTATION.md)。以下 M0～M7 是工程交付歷史；本輪測試與合成資料走查也不能代表使用者長期試用已完成。

## 可用性重整進度（與 M0～M7 分開）

| 階段 | 內容 | 狀態 |
| --- | --- | --- |
| R | 克隆七個參考庫、原始碼／官方資料比較、本機操作走查、既有平台開發方法研究 | 研究及三方交叉檢查已統整；18 張走查截圖與證據限制見新規劃 |
| D | 表格、代理核對、素材審核、工作流四組連貫操作設計 | 已落地互動介面並依代理操作走查修訂；使用者試用回饋另列 |
| S | grid／workbook 取捨、React Flow 適配、共用操作／資料契約 | 採現有資料表＋明示原檔相容邊界；React Flow adapter、固定身分與原子修改已驗證。完整工作簿引擎仍是未採用候選 |
| I | 按修訂後設計實作共用基礎操作 | 連續編輯、提案核對、素材審核、節點設定及交接已實作；最終證據與具體限制見實作紀錄 |
| E | 三類日常工作試用、視覺與操作 QA、反覆修正 | 代理已做合成資料瀏覽器操作與修正；真實使用者反覆日常試用未執行 |

原始規格續列如下。

> **2026-10-16 使用者校正：先做順通用工作台。** 文件、表格、工作流是可自由組裝的共同能力；行銷／美術／影劇只提供範本。近期優先改善新建、匯入、閱讀編輯與代理提案確認。使用者明確要求「先不用影片播放」：現行介面採影片附件／下載，以下播放器規格保留作歷史紀錄，不是本輪交付要求。介面進度及驗證見 [`WORKSPACE_UX.md`](./WORKSPACE_UX.md)。

> **2026-10-16 實作進度：M0～M7 工程交付項目全部完成。** 已補齊一次拆鏡／動態逐列／匯總合成、可執行模型與 FFmpeg Worker、媒體單格重抽及版本預覽。逐項完成清單見 [`ROADMAP_COMPLETION.md`](./ROADMAP_COMPLETION.md)，85 項 Python／41 項前端與實際媒體產線驗證見 [`ACCEPTANCE.md`](./ACCEPTANCE.md)。下文保留原始規格；Docker 容器與遠端 CI 未執行的界線亦列於驗收文件。安裝見 [`DEPLOYMENT.md`](./DEPLOYMENT.md)，手腳設定見 [`WORKERS.md`](./WORKERS.md)。

> **給後續接手開發的 AI 代理（Codex / Claude / Antigravity）**：
> 本文件是 **OpenBench** 的核心產品設計與工程規格書。
> 請務必先理解以下兩大設計支柱，再依序執行 **M0 ～ M7** 里程碑。

---

## 🌟 核心產品哲學：兩大設計支柱

### 支柱一：打破「寫死按鈕的專用工作台」，用「文件＋表格＋節點指令」自由排出任何產線

傳統開發「AI 影劇片場工作台」、「美術外包管理系統」或「行銷數據後台」時，往往把流程寫死成固定的 UI 表單與按鈕（例如：點按鈕 A 生劇本 → 點按鈕 B 拆鏡 → 點按鈕 C 生圖）。
這種做法的致命傷是：**一旦專案流程要調整（例如先定場景再改分鏡）、要一次量產 60 個鏡頭、或要多人邊審邊改，寫死的 UI 馬上卡死，失去自由度與管理彈性。**

**OpenBench 的核心洞察**：
> **「本質上，所有領域的產線都只是『結構化文件 (`doc`) ＋ 量產追蹤表 (`sheet`) ＋ 給代理的指令流 (`flow`)』！」**

只要把這三種畫布與「頭手分離的多模態代理（Head & Limbs）」打通，使用者就能針對不同專案，自己排出**可工作、可批次量產、可管理進度、可多人標註協作**的新形態工作台：

| 專案類型 | 📄 `DocSurface`（文件畫布） | 📊 `SheetSurface`（試算表／量產表畫布） | ⚡ `FlowSurface`（節點工作流畫布） | 🔌 掛載的代理手腳（Agent Limbs） |
| :--- | :--- | :--- | :--- | :--- |
| **📈 行銷數據專案** | 企劃總覽、口徑定義、週報總結 | **每日成效日報表**<br>（儲存格：金額、公式 `=D1/C1`、ROAS、狀態） | 抓資料 → 算異常 → 寫週報提案 | LLM 分析手腳、Python 報表手腳 |
| **🎬 AI 影劇量產專案**<br>*(從劇本到整部電影)* | 世界觀設定、分集劇本（導演與編劇直接畫螢光筆改台詞） | **1. 角色／場景資產表**（定妝圖＋固定 Seed/Prompt）<br>**2. 分鏡量產表 (Storyboard)**（鏡號｜台詞｜運鏡 Prompt｜**🖼️首幀圖格**｜**🎬影片格**｜**🎵配音格**｜審核狀態） | 劇本拆鏡 → 批次生首幀圖 → 審核通過列轉影片 → FFmpeg 串接成片 | LLM 編劇手腳、**ComfyUI/Flux/即夢 生圖手腳**、**Seedance/Kling/Veo 生影片手腳**、**FFmpeg/TTS 合成手腳** |
| **🎨 美術資產專案** | 美術風格指南、外包規範書 | **資產交付與審核表**<br>（資產代號｜規格｜**🖼️草圖格**｜**🖼️完稿格**｜主美標註狀態） | 讀取規範 → 批次跑草圖 → 主美標註回饋 → 局部重繪 | 生圖手腳、圖生圖 Inpaint 手腳 |

---

### 支柱二：不硬分區！「分頁即檔案、匯入匯出即版本交接、代理跨分頁免打開直改」

在真實辦公與創作場景中，不要在左側介面上生硬地把「指揮台視圖」與「本地檔案區」拆成兩個世界。
1. **單一乾淨的分頁樹 (`Unified Tab Rail`)**：
   - 所有分頁（總覽、劇本、分鏡表、日報表、工作流、或從電腦拖進來的 `.xlsx`/`.docx`/`.md`/`.csv`）全部平等住在左側分頁欄。
2. **底層保留原檔母體 (`source_blob`) 無損交接**：
   - 畫面上統一用好讀、可畫螢光筆標註的畫布呈現；但若分頁是由本地 `.xlsx` 或 `.docx` 拖入建立，底層保留原檔母體。
   - 匯出交接時，使用 `openpyxl` / `python-docx` **只將畫布上修改過的儲存格／段落 Patch 回原檔**，不洗掉原 Excel 的複雜公式、多工作表或排版。
   - 當外部改完檔案再拖回該分頁時，自動比對 Diff 建立新版本 (`revision`)，並執行 `reanchor_tab()` 讓原有的螢光筆重點與討論串自動對位。
3. **「打開改」與「不用打開改（Headless Batch Edit）」並存**：
   - 使用者可以在「專案總覽」看著進度表，**不用點開分鏡表或日報表**，直接叫右側代理：「*幫我把 EP01 分鏡表裡狀態是『未開始』的 20 鏡全部補齊運鏡 Prompt，或者把三份日報算好更新到總覽*」——代理跨分頁提出 `ProposalCard`，按一下「確認」即同步寫入！

---

## 里程碑總覽 (Milestones M0 ～ M7)

| 優先級 | 代號 | 模組名稱 | 核心目標 |
| :---: | :---: | :--- | :--- |
| **🔥 P0** | **M0** | **分頁與本地檔案無縫交接 (`file_handoff.py`)** | 支援把 `.xlsx`/`.docx`/`.md`/`.csv` 直接拖進分頁欄變成畫布、保留原檔母體無損 Patch 匯出、外部修改拖回自動 Diff，以及代理跨分頁免打開修改。 |
| **🔥 P0** | **M1** | **資料遮罩策略開關 (`privacy_mode`)** | 讓每個專案可自由選擇「允許代理讀寫真實數字（預設 `full_access`）」或「嚴格數值遮罩模式（`mask_numbers`）」。 |
| **🔥 P0** | **M2** | **多用途產線範本與多媒體表格格 (`Media Cells & Templates`)** | 新增專案產線範本（行銷／AI 影劇／美術／自訂）；讓 `SheetSurface` 儲存格原生支援**圖片 🖼️、影片 🎬、音訊 🎵 預覽與單列批次量產觸發**。 |
| **P1** | **M3** | **頭手分離：多模態供應商與遠端手腳協定 (`Head-Limb Protocol`)** | 支援註冊與切換 LLM 手腳、生圖手腳（Image Limb）、生影片手腳（Video Limb）與剪輯合成手腳（Media Limb），提供遠端 Worker 領取任務 API。 |
| **P1** | **M4** | **`SheetSurface` 深度產品化（Excel 貼上＋多工作表＋批次量產）** | 支援 `Ctrl+V` 整片貼上、動態增刪欄位、多勾選列批次交給代理量產（如一次選 20 鏡重抽首幀圖）。 |
| **P1** | **M5** | **`FlowSurface` 真實 DAG 產線執行引擎 (`flow_runner.py`)** | 持久化節點座標與自由連線，後端依拓撲順序自動執行跨分頁產線（例如：讀劇本 Doc → 拆列寫入分鏡 Sheet → 批次生圖 → 合成影片）。 |
| **P2** | **M6** | **成員管理 UI 與輕量認證系統 (`Auth & RBAC`)** | 在 UI 新增「👥 成員與角色管理」彈窗（導演／主美／行銷／工程）與 Token / Reverse-Proxy 登入。 |
| **P2** | **M7** | **開源打包與一鍵部署 (`Packaging & Docker`)** | 補齊 `pyproject.toml`、`Dockerfile`、`docker-compose.yml` 與 GitHub Actions CI。 |

---

## 各里程碑詳細施工規格

### M0：分頁與本地檔案無縫交接 (`project_docs/file_handoff.py`)

1. **Schema 擴充 (`db/149_project_docs_schema.sql`)**：
   ```sql
   ALTER TABLE projectops.tab
     ADD COLUMN IF NOT EXISTS source_filename TEXT,
     ADD COLUMN IF NOT EXISTS source_mime     TEXT,
     ADD COLUMN IF NOT EXISTS source_blob     BYTEA,
     ADD COLUMN IF NOT EXISTS linked_path     TEXT;
   ```
2. **匯入與外部交接比對 (`POST /projects/api/<slug>/tabs/import`)**：
   - 拖入 `.xlsx`/`.csv` 自動轉為 `surface_type='sheet'` 分頁；拖入 `.docx`/`.md` 自動轉為 `surface_type='doc'` 分頁，並保存 `source_blob`。
   - 若拖入既有分頁，自動計算與目前畫布的 `doc_changes` 差異，建立新版本並呼叫 `reanchor_tab()` 重對位所有標註。
3. **無損 Patch 匯出 (`GET /projects/api/<slug>/tabs/<key>/export?format=xlsx|docx|csv|md`)**：
   - 若分頁有 `source_blob`，用 `openpyxl` / `python-docx` 只將變動的儲存格或段落 Patch 進原檔母體後輸出；若無則直接生成乾淨檔案。
4. **代理跨分頁免打開修改工具 (`propose_table_edit`)**：
   - 在 `project_assistant/tool_specs.py` 與 `tools.py` 新增 `propose_table_edit(tab_key, row_edits, new_rows)`，讓使用者在總覽頁就能指揮代理修改任一分頁的表格內容（例如一次幫分鏡表新增 15 個鏡頭列，或幫日報表填寫數據）。

---

### M1：資料遮罩策略開關 (`privacy_mode`)

1. **Schema (`db/149_project_docs_schema.sql`)**：
   - `projectops.project` 新增 `privacy_mode TEXT NOT NULL DEFAULT 'full_access' CHECK (privacy_mode IN ('full_access', 'mask_numbers'))`。
2. **行為分流 (`project_assistant/tools.py`, `service.py`)**：
   - `full_access`（預設）：不呼叫 `mask_text`，允許代理完整讀寫數字、公式、鏡號參數與 Seed。
   - `mask_numbers`：啟用 `masking.py` 將大於 100 的敏感金額遮成 `▢`。

---

### M2：多用途產線範本與多媒體表格格 (`Media Cells & Project Archetypes`)

這是支援 **AI 影劇（劇本→分鏡→成片）** 與 **美術資產量產** 的關鍵模組：

1. **專案產線範本 (`project_docs/templates.py` & `service.py`)**：
   - 在 `POST /projects/api/projects` 支援 `template` 參數（前端「＋ 新增專案」彈窗可直接選擇）：
     - `marketing`（📈 行銷數據與日報產線）：自動建立 `專案總覽 (doc)`、`每日成效日報 (sheet)`、`自動化異常診斷 (flow)`。
     - `ai_drama`（🎬 AI 影劇：從劇本到成片產線）：自動建立：
       1. `📄 第一集劇本與世界觀 (doc)`：含場次、對白、導演標註範例。
       2. `📊 角色與場景資產設定表 (sheet)`：含角色名、外觀固定 Prompt、定妝參考圖格、配音音色、狀態。
       3. `📊 EP01 分鏡量產表 (sheet)`：含 `鏡號 (Shot)`、`景別／運鏡`、`畫面與台詞`、`生圖／生影片 Prompt`、`🖼️ 首幀畫面預覽`、`🎬 動態影片預覽`、`狀態`、`導演備註`。
       4. `⚡ 劇本→分鏡→生圖→成片產線 (flow)`：定義 4 個串接節點（劇本拆鏡代理 → 角色一致性生圖手腳 → 圖生影片手腳 → FFmpeg 配音合成手腳）。
     - `art_studio`（🎨 美術資產量產與審核台）：自動建立 `美術規範書 (doc)`、`資產交付審核表 (sheet)`、`跑圖審核流 (flow)`。
     - `blank`（🧩 空白自由組裝）。
2. **`SheetSurface` 多媒體儲存格渲染與互動 (`ui/src/CanvasViews.jsx`)**：
   - 當表格欄位或儲存格內容包含圖片／影片／音訊資產（例如 `/projects/api/<slug>/assets/pa_...`、`![說明](url)`、或媒體標籤）時：
     - **🖼️ 圖片格**：在儲存格內直接渲染高質感縮圖卡片，點擊可放大檢視（Lightbox）、上傳替換圖片、或點「`✦ 重抽此格圖片`」。
     - **🎬 影片格**：在儲存格內渲染迷你影片預覽（Hover 播放或點擊展開播放器、顯示秒數與解析度）。
     - **🎵 音訊格**：渲染迷你播放按鈕與音軌長度。
3. **批次勾選與量產列操作 (`Batch Row Actions`)**：
   - 在 `SheetSurface` 每列左側提供勾選框（Checkbox）：
     - 導演或美術可以一次勾選 Shot 05 ～ Shot 15，點頂部 **「✦ 批次交給代理執行 (11 列)」**：
     - 例如：「*把勾選這 11 鏡的狀態改為『生圖中』，並呼叫生圖手腳依第 D 欄 Prompt 產出首幀圖填入第 E 欄*」。

---

### M3：頭手分離 — 多模態供應商與遠端手腳協定 (`Head-Limb Protocol`)

參考 `openab` 的頭手分離精神，將代理手腳分為四種能力型態（Capabilities）：
1. **`llm`（文字與推理手腳）**：OpenAI GPT-5.4、Google Gemini 2.5 Pro、Anthropic Claude Sonnet、Local Ollama / vLLM。
2. **`image_gen`（生圖與修圖手腳）**：ComfyUI Server、Flux API、即夢 (Jimeng / Dreamina)、Midjourney Bridge。
3. **`video_gen`（生影片手腳）**：Seedance、Kling (可靈)、Veo、Runway。
4. **`media_assemble`（音訊與成片合成手腳）**：FFmpeg 剪輯合成器、ElevenLabs / CosyVoice TTS 配音手腳。

#### 施工步驟
- 在 `db/154_project_assistant.sql` 新增 `projectops.agent_limb` 表。
- 在 `project_docs/http.py` 實作：
  - `GET  /projects/api/limbs`：列出所有已註冊的 LLM 與多模態手腳。
  - `POST /projects/api/limbs/register`：遠端 GPU 機器上的 ComfyUI / Seedance / FFmpeg Worker 註冊自己。
  - `POST /projects/api/limbs/claim`：遠端手腳領取待處理的生圖／生影片／推理任務。
  - `POST /projects/api/limbs/upload-cell-asset`：遠端生圖／生影片手腳跑完後，直接把產出的圖片或 `.mp4` 上傳至 `projectops.asset` 並寫入對應分鏡表的 `(row_id, col_index)`（或產生 `ProposalCard` 供導演審核）！

---

### M4：`SheetSurface` 深度產品化

1. **支援從 Excel / 外部表格 `Ctrl+V` 整片貼上（TSV 解析）**：一次展開多列多欄並送出批次 `put_row` ops。
2. **動態欄位管理**：在試算表表頭支援「＋ 新增欄」、「設定欄位型態（文字／數值／公式／圖片格／影片格／狀態膠囊）」。
3. **單列版本對比**：在分鏡表或日報表的任一列，可點開查看該列過去改過幾次 Prompt、抽過哪幾版圖片。

---

### M5：`FlowSurface` 真實 DAG 產線執行引擎 (`project_assistant/flow_runner.py`)

1. **自由拉線與座標持久化**：支援一對多（例如：劇本拆完分鏡後，同時觸發「生首幀圖手腳」與「TTS 配音手腳」平行執行）與多對一匯流（圖＋音都完成後，觸發「成片合成手腳」）。
2. **單列觸發 vs. 整表批次觸發**：
   - 產線可以針對「整張分鏡表所有『未開始』的列」批次跑，也可以只針對「導演剛剛標記為『重抽』的第 12 鏡」單列重跑！
3. **執行狀態即時回饋**：在 `FlowSurface` 節點卡片與 `SheetSurface` 對應列上即時顯示進度條與產出結果。

---

### M6 & M7：成員權限管理 (`Auth & RBAC`) 與開源打包 (`Docker & CI`)

- **M6**：頂部新增「👥 成員管理」彈窗（支援設定導演、編劇、主美、行銷、工程等角色標籤），支援 `dev | token | header` 登入模式。
- **M7**：補齊 `pyproject.toml`、`Dockerfile`、`docker-compose.yml` 與 `.github/workflows/ci.yml`。
