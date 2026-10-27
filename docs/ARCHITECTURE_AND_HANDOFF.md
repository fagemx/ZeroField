# OpenBench 架構設計與代理交接技術手冊 (`ARCHITECTURE_AND_HANDOFF.md`)

本文件詳細記錄 **OpenBench** 的系統架構、資料庫 Schema、API 路由、前端元件分工，以及「頭手分離代理 (Head-Limb Agent)」與「多型態畫布 (Multi-Surface Canvas)」的設計細節，供後續任何 AI 代理或開發者直接接手。


## 2026-10-18 M8 接手入口

四角色、每角色模型、背景編排、問題 Gate、2～3 候選比較與 ACP 已接入既有工作台。請先讀 [本輪驗證](AGENT_ORCHESTRATION_ACCEPTANCE.md) 與 [規格裁定](AGENT_ORCHESTRATION_SPEC.md#7-本輪實作裁定優先於前文示意介面)；本文件後方歷史待辦不代表目前缺漏。

`agent_registry/agent_policy/agent_runtime` 管角色與共用執行；`orchestrator/orchestration_store` 管 Run/Task/Dispatch/Gate 與交易；`orchestration_service` 管私有成員 API；`orchestration_flow` 與 `orchestration_limb` 分別接既有 Flow／遠端 Worker。`acp_bridge` 只在可信 Worker 執行指定 adapter，Head 不執行使用者程式。

UI 從「交給代理」、文件選字工具列或明確 @agent 留言進入；助理的「代理工作」集中看進行中、待裁決與成果。普通提案使用既有核對面板，競案單一 Gate 並排比較後原子選用。關閉板只輪詢輕量 counts，分頁游標及本地草稿不被背景刷新重設。

資料庫順序到 161；執行入口 `worker.poll_once` 公平分配 chat／dispatch，共用 pool，不在模型執行期間持有 DB 交易。每槽重派有新 admission；取消即封住工具與輸出。部署 ACP、明確模型憑證及中止界線見 [WORKERS.md](WORKERS.md#acp-stdio-橋接)。

---

## 1. 為什麼做 OpenBench？（背景脈絡）

OpenBench 源自實際運作良好的「專案工作台」介面：
- **左側**：分頁導覽列（支援多分頁、釘選、標籤、新增分頁）。
- **中間**：協作畫布（原本是 ProseMirror 文件，支援多人即時區塊鎖定、四色螢光筆畫重點、針對文字範圍或整個區塊發起討論標註、版本歷史比較）。
- **右側**：專案 AI 代理（可讀取畫布內容、掃描待辦事項、提出 `ProposalCard` 修改提案讓使用者一鍵套用到畫布上）。

在抽離為獨立開源專案 **OpenBench** 時，我們確立了三個核心進化方向：

1. **中間畫布多型態化 (`doc` / `sheet` / `flow` / `board`)**
   - 除了原本好用的文件 (`doc`)，行銷團隊之後可以把自己的「每日成效日報」放進來變成 `sheet`（類 Excel 表格畫布），或是把自動化任務串成 `flow`（代理工作流節點畫布）。
   - 最關鍵的設計原則：**不同型態的畫布不各自造輪子，而是共用同一套標註 (`annotation`)、區塊鎖 (`block_lock`)、變更提案 (`ProposalCard`) 與歷史紀錄 (`revision`)**。
2. **右側代理「頭與手腳分離」＋ 可換供應商**
   - 借鏡 `C:\ai_project\openab`（將協調中樞 Head 與執行器手腳 Limb 分離，有任務的代理不一定住在同一個進程或同一台機器）與 `C:\ai_project\orca`（多代理任務追蹤，但不做程式碼 IDE，而是聚焦任務與畫布協作）。
   - 中間畫布上的工作都可以請右側代理完成，也可以改由外部 Worker 來源執行。代理的模型供應商可以更換，但依五條供應商原則（SPEC_20 §0.3）：(1) 預設與展示路徑全部用本機開放權重（Ollama＋`qwen3.8:27b`）；(2) 託管開放權重（例如 OpenRouter 上的同一個模型）是選配，不在展示路徑；(3) 閉源模型（OpenAI、Anthropic、Gemini）只在混合模式明確開啟時可用；(4) 不使用 chatgpt.com 訂閱端點，所有模型呼叫都走治理；(5) 非本機呼叫一律要價格上限，並記錄實際用到的模型。預設環境只放行本機，接其他端點要管理者在 Agent Console 放行該主機並設定價格上限。
3. **多專案管理與專案生命週期狀態 (`Project Hub`)**
   - 從單一專案擴充為多專案架構，支援專案狀態（`planning` 規劃中、`active` 進行中、`recurring` 例行日報、`blocked` 卡關中、`archived` 已封存）。

---

## 2. 資料庫結構 (`db/`)

Schema 定義於 `db/149_project_docs_schema.sql` 與 `db/154_project_assistant.sql`，全部位於獨立的 `projectops` schema 下（無任何外部 schema 依賴）：

### `projectops.member`（獨立成員表）
```sql
CREATE TABLE IF NOT EXISTS projectops.member (
    member_id    UUID PRIMARY KEY,
    email        TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    role_title   TEXT NOT NULL DEFAULT '',
    is_admin     BOOLEAN NOT NULL DEFAULT FALSE,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `projectops.project`（多專案與狀態）
```sql
CREATE TABLE IF NOT EXISTS projectops.project (
    slug        TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('planning', 'active', 'recurring', 'blocked', 'archived')),
    summary     TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `projectops.tab`（多型態畫布分頁）
```sql
CREATE TABLE IF NOT EXISTS projectops.tab (
    project_slug      TEXT NOT NULL REFERENCES projectops.project(slug) ON DELETE CASCADE,
    tab_key           TEXT NOT NULL,
    title             TEXT NOT NULL,
    parent_key        TEXT,
    sort_order        INTEGER NOT NULL DEFAULT 100,
    surface_type      TEXT NOT NULL DEFAULT 'doc'
                      CHECK (surface_type IN ('doc', 'sheet', 'flow', 'board')),
    doc_json          JSONB NOT NULL,
    -- 以及 pinned, tags, revision_no, updated_by, updated_at 等欄位
    PRIMARY KEY (project_slug, tab_key)
);
```

### 其他核心資料表
- `projectops.field_state`：儲存畫布內互動欄位（如 `status` 狀態膠囊、`fill` 可填格、`check` 勾選項）的最新值。
- `projectops.revision`：每次修改的完整快照、Diff 摘要與修改來源（人類成員或 `ai_assistant`）。
- `projectops.annotation` & `projectops.annotation_reply`：文字範圍重點標註（含四色螢光筆 `color` 與前後文錨點 `anchor_json`）與區塊討論串。
- `projectops.block_lock`：多人協作時的段落/表格列編輯鎖（TTL 自動過期機制）。
- `projectops.assistant_thread`、`projectops.assistant_message`、`projectops.assistant_proposal`：右側代理的對話序列、Worker Lease 鎖定佇列、以及對畫布的結構化變更提案。

---

## 3. 後端架構與 API 路由 (`project_docs/` & `project_assistant/`)

### 3.1 `project_docs/`（畫布與專案核心）
- `http.py`：HTTP 路由入口 `handle_projects(handler, parsed, method)`。
  - 連線管理：`http.set_connection_factory(fn)` 或透過環境變數 `OPENBENCH_DB_URI` / `DATABASE_URL` 建立 PostgreSQL 連線。
  - **新增/更新的多專案路由**：
    - `GET /projects/api/projects`：列出所有專案（含 `slug`, `title`, `status`, `summary`, `updated_at`）。
    - `POST /projects/api/projects`：建立新專案（傳入 `{slug, title, status, summary}`），並自動建立預設首頁分頁 `overview`。
    - `POST /projects/api/<slug>/meta`：更新專案的 `title`、`status`、`summary`。
    - `POST /projects/api/<slug>/tabs`：建立新分頁，支援傳入 `surface_type` (`doc` | `sheet` | `flow` | `board`)。
- `service.py`：業務邏輯層，負責組裝專案 Bootstrap payload、預設畫布內容、匯出 `.docx` 與稽核紀錄。
- `blocks.py`：純函式區塊操作引擎 (`apply_ops`)，支援 `put`、`del`、`put_row`、`del_row`、`order`，並檢查 `locks` 與 `base` 版本衝突。
- `anchoring.py`：文字範圍錨點演算法（透過 `quote` + 32 字元 `prefix`/`suffix` 在內文被編輯後自動找回重點標註位置）。

### 3.2 `project_assistant/`（頭手分離代理與多供應商）
- `mcp_server.py` & `tool_specs.py`：
  - 定義代理可用來操作中間畫布的標準工具（讀取分頁、讀取表格、新增/修改段落或表格列提案 `propose_edit`、更新狀態膠囊等）。
  - 支援直接被本機 Worker 呼叫，或透過標準 MCP over stdio (`python -m project_assistant.mcp_server`) 掛載給外部代理（如 Claude Desktop、Codex CLI、OpenAB Limb）。
- `providers.py`：
  - 定義 `ProviderConfig(kind, base_url, api_key, model)` 與 `provider_from_env()`。
  - 實作 `run_openai_compat_turn()`：支援所有相容 OpenAI `/v1/chat/completions` function calling 的供應商（OpenAI、Gemini、OpenRouter、Ollama、vLLM）。
- `worker.py`：
  - 透過 PostgreSQL `FOR UPDATE SKIP LOCKED` 佇列租約機制（Lease）領取待處理的 `assistant_message`。
  - 這讓「工作台 Web 伺服器 (Head)」與「代理執行器 (Limb)」天然解耦：你可以跑內建背景執行緒，也可以關閉內建執行緒，改由另一台機器上的 Worker 進程連同一個 DB 或透過 HTTP/MCP 領取任務。
- `todo.py`：
  - 自動掃描專案內所有分頁的表格，只要某一列含有狀態膠囊（例如 `未開始`、`進行中`、`等待回覆`、`卡住`），就會自動彙整為右側代理面板的待辦追蹤清單。

---

## 4. 前端架構 (`ui/src/`)

前端採用 React 18 + ProseMirror (TipTap) + Vite，建置輸出至 `static/projects/`：

- `App.jsx`：
  - 當網址在 `/projects/` 根路徑時，渲染 `ProjectHub` 多專案總覽頁。
  - 當進入 `/projects/<slug>/` 時，渲染三欄式工作台（左 `TabRail`、中 `DocSurface` + `SurfaceHeader`、右 `AssistantDock`），並在頂部導覽列整合專案狀態徽章與 `IdentityBadge` 身分切換器。
- `Surfaces.jsx`（本次新增的核心元件）：
  - `ProjectHub`：支援依專案狀態（全部 / 規劃中 / 進行中 / 例行日報 / 卡關中 / 已封存）篩選專案卡片、直接切換專案狀態、以及點擊「＋ 新增專案」建立新專案並自動初始化預設分頁。
  - `SurfaceHeader`：當分頁的 `surface_type` 為 `sheet`（日報試算表）或 `flow`（代理工作流）時，在畫布上方顯示專屬工具橫幅與操作提示，並提供根據 `surface_type` 產生的預設結構化畫布模板 (`defaultSurfaceTemplate`)。
  - `IdentityBadge`：在開發/展示模式下，可一鍵切換不同成員身分（如 Alex / Mia / Sam）以測試多人區塊鎖定與標註歸屬。
- `TabRail.jsx`：
  - 左側分頁樹。點擊「＋ 新增分頁」時，提供畫布型態選擇器（📄 文件畫布 `doc`、📊 日報試算表 `sheet`、⚡ 代理工作流 `flow`），並在分頁列表顯示對應圖示。
- `DocSurface.jsx` & `Annotations.jsx`：
  - 中間畫布編輯器、選取文字彈出四色螢光筆與標註選單、右側錨點卡片對位。
- `assistant/AssistantViews.jsx` & `assistant/useAssistant.js`：
  - 右側代理對話串、待辦事項清單、以及 `ProposalCard`（顯示代理對畫布提出的修改預覽，支援「套用修改」或「略過」）。

---

## 5. 如何執行、測試與繼續開發

### 5.1 跑後端單元測試
```powershell
cd C:\ai_project\openbench
python -m unittest discover -s tests -p "test_*.py" -v
```

### 5.2 建置前端與跑前端測試
```powershell
cd C:\ai_project\openbench\ui
npm install
npm run build
npm test
```
> 備註：`npm run build` 會將編譯後的 `app.js` 與 `app.css` 輸出至 `C:\ai_project\openbench\static\projects\`，由 `server.py` 直接提供服務。

### 5.3 啟動獨立開發伺服器
```powershell
cd C:\ai_project\openbench
# 方式 A：使用內建臨時 PostgreSQL (需環境裝有 testing.postgresql 或本地 PG)
python server.py --embedded-db --port 3013

# 方式 B：指定外部 PostgreSQL URI
$env:OPENBENCH_DB_URI = "postgresql://postgres:postgres@127.0.0.1:5432/openbench"
python server.py --port 3013
```

---

## 6. 後續擴充指南（Roadmap for Next Agents）

1. **在 `worker.py` 串接 `providers.py` 與前端供應商切換 UI**
   - 檔案位置：`project_assistant/worker.py` 與 `ui/src/assistant/AssistantViews.jsx`。
   - 做法：在 `worker.py` 呼叫模型前檢查 `providers.provider_from_env().kind`（或從前端傳入的 provider 設定），若為 `openai_compat` 則呼叫 `providers.run_openai_compat_turn(...)`。
   - 在右側面板頂部新增一個小齒輪或下拉選單，讓使用者可以在 UI 上即時切換 `OpenAI / Gemini / Claude / Ollama (Local) / Remote Limb`。
2. **深化 `sheet` 畫布（Excel 日報模式）**
   - 目前 `sheet` 分頁使用結構化表格並套用專屬雙欄寬度與表頭樣式，已支援代理透過 `put_row` 新增/更新每日數據列。
   - 後續可在 `Surfaces.jsx` 為 `sheet` 模式加入「匯入 CSV / Excel 成表格列」與「欄位總計 / 平均自動計算列」。
3. **深化 `flow` 畫布（代理節點工作流模式）**
   - 目前 `flow` 分頁以結構化節點清單與轉移表定義工作流。
   - 後續可在 `Surfaces.jsx` 加入 SVG 節點連線圖預覽，以及「▶ 執行此工作流」按鈕，點擊後自動向右側代理發送執行指令，將結果寫入指定的目標分頁（例如從資料源抓取數據後寫入 `daily-sheet` 分頁）。
