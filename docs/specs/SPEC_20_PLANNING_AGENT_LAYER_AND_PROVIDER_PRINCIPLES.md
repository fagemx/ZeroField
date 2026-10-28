# SPEC_20 規劃代理層：劇組真的會規劃、對內對外分工、供應商原則

> **狀態：** 已實作，待驗收（2026-10-27）。使用者指示不受參賽截止時間限制、R1–R44 全部完整實作；各項實作已併入整合分支 `feat/spec20-integration`，R44 與部分項目尚未完成，逐項狀態與未完成處見 §11。完整分片測試已跑（收據 `docs/spec20-verification.json`：後端 1237、前端 592 項全過）。2026-10-27 在使用者的 4090 上做了實機驗收（收據的 `real_acceptance`）：A14、A15、A17 通過；R42 以本機模型跑了分拍與接點，分數偏低；R44 只用介面走到匯出成片，但靠介面上的變通繞過兩個阻擋斷點。2026-10-28 修好這兩個斷點（R44-3、R44-7）後重走一次（收據的 `real_acceptance.R44_rewalk`）：劇組與連戲評分改走 OpenRouter 上的託管開放權重 DeepSeek V4.1 Flash 1017，製作政策維持 `open_weights_only`，不用任何變通就走到匯出成片，兩個斷點關閉；同日修好 R44-1、R44-2、R44-4、R44-5、R44-6、R44-8 與預覽分配推薦未安裝卡片的問題，再重走前製（收據的 `real_acceptance.R44_rewalk2`），九項檢查全過；新記下的斷點見該收據。真實 MCP 主機檢查還沒做。
> **依據：** [`docs/research/2026-10-27-planning-agent-layer.md`](../research/2026-10-27-planning-agent-layer.md)（研究備忘，含查證狀態）。
> **相關：** SPEC_08（中控台）、SPEC_13／14／16（故事與拆鏡）、SPEC_18（R4 階梯、R8 生成列）、SPEC_19（生成台、採用即成片、引用與接點；另一個工作階段在 `feat/spec19-integration` 平行實作，見 §10）。
> **截止：** 參賽截止 2026-10-30 09:00 PT（台灣 10/31 00:00）。「P0／P1／P2」只代表先後與重要性，不再是截止前後的切分。

## 0. 目標與固定決策

### 0.1 問題
規格與重設計畫布在許多步驟假設「劇組在判斷」，產品執行時卻沒有對應的能力：
- 全新安裝沒有可用的模型：供應商預設指向 api.openai.com＋gpt-4.1 且沒有金鑰；README 用 `--no-worker` 啟動；劇組「在線」只看背景程式心跳。
- 故事到分鏡全是規則與範本（`story_adaptation.py` 第 1 行就寫明不呼叫模型）。
- 3D 計畫只存在瀏覽器暫存與預演影片檔裡，沒有任何代理工具能改。
- 真正用模型跑過的，只有單支 Take 的連戲評分。

開發時，這些判斷由編碼代理與腳本代做；使用者在自己的專案裡一用就斷。

### 0.2 目標
1. 使用者在自己的專案裡，劇組能在本機開放權重模型上真的規劃：從介面觸發、產出提案、就地審核。
2. 對外開放 MCP，讓自帶代理的使用者用同一套工具；安全放在工具層。
3. 五條供應商原則落到程式與文件。
4. 先修掉會讓劇組失效、或影響參賽資格的問題，並讓文件與程式一致。

### 0.3 固定決策

**供應商原則（使用者 2026-10-27 核定）**
1. **預設與展示路徑全部用本機開放權重。** 規劃與評分用 Ollama＋`qwen3.8:27b`；生成用 ComfyUI＋LTX-2.5／FLUX 3。
2. **託管開放權重是選配。** 用 OpenRouter 上的同一個模型，給沒有顯示卡的人；由管理者開啟，並標明不在比賽展示路徑。
3. **閉源模型只在混合模式明確開啟時可用。** 包括 OpenAI、Anthropic、Gemini 與 Comfy Router 的閉源卡；混合模式即既有的 `hybrid_studio` 製作政策。
4. **移除 chatgpt.com 訂閱端點；所有模型呼叫都走治理。** 包括連戲評分與快速建立助手。
5. **非本機呼叫一律要價格上限，並記錄實際用到的模型。** 用量分級要分得出「本機開放權重／託管開放權重／閉源」。

**架構**

6. **不換代理框架。** 保留自家工具迴圈，以及 PostgreSQL 的提案與決策閘門。
7. **對外用 MCP、對內用自家迴圈，兩邊共用同一套工具層。** ACP 只當選配工人。
8. **安全不依賴流程手冊。** 寫入一律產生提案或經閘門核准；工具層自己檢查範圍與參數。
9. **劇組產出一律是提案，人採用才寫入。** 不新增狀態值（`project_docs/doc_schema.py:17` 不動），也不自動寫 `Pending Review`（同 SPEC_19 固定決策 1、2）。
10. **不自動花錢**（同 SPEC_19 固定決策 8）：劇組可以提議生成，不能自行送出閉源或付費生成。
11. **3D 計畫由結構化操作加確定性求解產生**，不執行模型寫的程式。
12. **每個劇組工作都有四樣東西：** JSON 輸出格式、程式端驗證、最多重試一次、沒有模型時的規則退路。

## 1. 現況

### 1.1 程式盤點
| 範圍 | 位置 | 現況 | 本規格 |
|---|---|---|---|
| 供應商預設 | `project_assistant/providers.py:35-43` | `openai_compat` → `https://api.openai.com/v1`、`gpt-4.1`、沒有金鑰 | R2 |
| 免金鑰判斷 | `providers.py:77` | 用「網址字串含 127.0.0.1 或 localhost」判斷；`::1` 判斷不到，網址別處含 localhost 也會誤判 | R2 |
| 失敗後的預留 | `providers.py:177-179`；`execution_governance.py:113-118`、`:183-188` | 失敗的一輪留在 `uncertain`，計入並行上限，沒有程式會清掉 | R1 |
| `responses` 類型 | `execution_governance.py:239-242`；`model_client.py:19`、`:72-87`、`:145-148` | 固定連 `chatgpt.com/backend-api/codex/responses`，用開發者電腦上 `~/.codex/auth.json` 或 pi 給的權杖，並自訂標頭繞過 Cloudflare | R3 |
| 最後一輪 | `providers.py:104` | 第 16 輪送 `tool_choice: "none"`；Ollama 不支援 `tool_choice` | R4 |
| 連戲評分 | `take_grader.py:163-201`、`:265-276` | 真的呼叫視覺模型，但不走治理（沒帶 admission）；自動評分只掛在管線路徑（`flow_runner.py:1029-1030`） | R11、R23 |
| 快速建立助手 | `agent_console_service.py:128-136` | 直接呼叫模型，不走治理 | R11 |
| 劇組在線 | `orchestration_flow.py:11-19`；`agent_registry.py:264-290` | 只看背景程式 90 秒內有沒有心跳 | R2 |
| 管線工人 | `run_studio.py:524` | 只註冊給展示專案；使用者的專案沒有 | R14 |
| 拆鏡、描述、出場、鏡頭 | `project_docs/story_adaptation.py`、`story_openapi.py:599-655` | 規則與範本 | C 包 |
| 3D 計畫 | `ui/src/previs/PrevisStage.jsx:28-32`、`ui/src/previs/webm.js`、`story_openapi.py:643` | 瀏覽器暫存＋預演 WebM 標題；後端只有 6 個列舉欄位的種子 | D 包 |
| 代理工具 | `tool_specs.py`、`studio_tools.py` | 7 個 studio 工具；沒有讀場次、鏡頭 meta、3D 計畫的工具；新增一個工具要改約 6 個檔案 | B 包 |
| 提案 | `store.py:481`；`project_assistant/service.py:255`（`_write`）、`:339`（`apply_proposal`） | 以表格為中心；單步提案會鎖住整頁（`docs/PHASE2_PROGRESS.md:136-144`） | B 包 |
| 對外介面 | `mcp_stdio.py`（宣告 2025-06-18，每輪一個）；`limbs.py`、`orchestration_limb.py` | 只有內部管線與遠端工人協定 | E 包 |
| GPU | `take_grader.py:36`、`:234-262`；`studio/card_engine.py:1365-1368` | 程序內的鎖；代理的模型呼叫不參與 | R13 |
| 中控台 | `agent_console_service.py`、`ui/src/agentConsole/` | 12 頁多為原始 JSON；健康檢查只對 `/models` 發 GET | F 包 |

### 1.2 陷阱
- **A. 失敗會鎖死劇組。** 每一輪結束時 `finally` 都會呼叫 `admission.after({}, 'unknown')`（`providers.py:177-179`）。成功的那一輪早已結算，這行不會生效；但失敗的一輪（連不上、401、429、逾時）會被結算成 `uncertain`。`uncertain` 計入每個角色的並行上限（預設 2，`agent_registry.py:99`）與專案的模型並行上限（預設 4，`agent_console_store.py:43`），而 `finalize()` 遇到 `uncertain` 會直接返回（`execution_governance.py:169`）。結果是：本機 Ollama 沒開時，同一角色失敗兩次就永遠被鎖住。
- **B. `responses` 類型等於 chatgpt.com。** `model_destination()` 對 `responses` 回傳固定網址（`execution_governance.py:239-242`）。有四個測試檔用假端點驗證這條路，移除時要改寫測試，不能只刪程式（見 R3）。
- **C. Ollama 的 OpenAI 相容介面不支援 `tool_choice`，圖片也只收 base64。** 連戲評分已經用 base64 ✓（`take_grader.py:272`）。
- **D. Ollama 在顯示記憶體小於 24 GiB 時，預設情境只有 4k**（官方文件 docs.ollama.com/context-length），4090 很可能落在這一級，要在本機確認。OpenAI 相容介面設不了 `num_ctx`，只能用伺服器的 `OLLAMA_CONTEXT_LENGTH` 或 Modelfile。我們開發用的 `qwen3.8:27b-16k` 是本機 Modelfile 標籤，不是官方標籤。
- **E. 思考強度。** 研究報告指出 Qwen3.8 預設思考強度很高。`ProviderConfig.effort` 只接受 `low`／`medium`／`high`（`providers.py:31`）；快速建立助手目前用 `/no_think` 軟開關（`agent_console_service.py:134-135`）。
- **F. 單步提案會鎖住整頁。** 同一分頁有多個待審提案時，採用其中一個，其他的就會失敗。這是 SPEC_08 的契約，有測試釘住（`test_source_changed_while_executing_or_waiting_for_approval_cannot_write`）。劇組一次替多鏡提案一定會撞到，所以 C 包之前要先解決（R17）。
- **G. 治理只分「本機 vs 非本機」。** 非本機一律記成 `closed_flagship`（`execution_governance.py:282-283`），商用視覺一律拒絕（`:228-231`）。託管開放權重需要新的分級（R9）。
- **H. 評分不走治理。** 如果連戲監督的設定指向託管端點，影格會直接送出去，既不檢查網路政策，也沒有價格上限（`take_grader.py:269` 沒有帶 admission）。
- **I. 預演在瀏覽器裡算圖**（PrevisStage 算好 WebM 再上傳），伺服器沒有算圖器。代理要「算一張來看」，得先有無頭算圖（R28）。
- **J. 3D 計畫的 `cast` 只有站位，沒有角色代碼**；`SCENE_ANCHORS` 只適用天文台場景（`ui/src/previs/plan.js`）。
- **K. 公開 REST（`/aivideo/open/v1`）不適合當代理介面。** 它沒有範圍限制、直接寫入，開發模式還能用 `X-OpenBench-Actor` 標頭冒名（`project_docs/auth.py:67-68`）。
- **L. 代理看不到故事結構。** 只能用 `read_page` 翻表格文字，每頁約 5800 字。
- **M. 取消派工不會打斷進行中的模型呼叫**，對話也不能取消。
- **N. 測試環境。** 完整後端測試要用一次性的 PG（埠 55461），不是展示資料庫（55440），並設 `OPENBENCH_TEST_DB_URI`；前端改完必跑 `npm run build --prefix ui`。

### 1.3 文件與程式不一致（要修）
範圍：供應商、模型、代理與參賽合規相關的敘述。介面與播放效能章節不在這次核對範圍。

**指南與 AGENTS.md**

| # | 文件位置 | 文件寫的 | 程式與事實 | 修法 | 需求 |
|---|---|---|---|---|---|
| D1 | 指南 §3.1 第 70 行 | 「LLM 拆鏡預設支援本地開源權重模型（Ollama／vLLM），同時相容任何 OpenAI 相容端點」，舉例 qwen3／llama-3.3／deepseek | 拆鏡完全不呼叫模型（`story_adaptation.py:1`；建立分鏡回傳 `"engine": "deterministic"`，`story_openapi.py:1413`）；供應商預設 api.openai.com＋gpt-4.1（`providers.py:40-42`）；預設環境只放行本機（`agent_console_store.py:574`），接其他端點要管理者另開白名單環境並設價格上限 | 改寫成五條供應商原則；拆鏡寫明「預設由規則拆鏡，劇組產生拆鏡提案（C 包）」；範例模型改為 `qwen3.8:27b`，拿掉授權有限制的 llama | R2、R5 |
| D2 | 指南 §3.1 第 68 行 | 「`workflows/` 目錄下的所有 ComfyUI API JSON 嚴禁包含任何閉源付費節點」 | 工作流圖本身沒有夥伴節點 ✓（逐檔掃過）。但 `workflows/cards/` 有閉源卡：`kling-v2-master`、`seedance-20-pro`（vendor_api、closed_hero）、`rh-cloud-h3-burst`（runninghub_cloud）、`router-*.json`（Comfy Router）；`workflows/router/` 另有 7 個 Router 模型定義。這些由製作政策擋住（預設 `open_weights_only`，`studio/model_router.py` 的 `effective_production_policy`） | 補一句：「圖檔 100% 開放權重；閉源卡片與 Router 定義只在混合模式可用，預設政策擋住」 | R5 |
| D3 | AGENTS.md 第 45 行（`docs/ZEROFIELD_SPEC.md` 第 77 行同） | 「比賽規定必須建構於 Comfy Developer Platform（Comfy Router 和／或 Comfy SDK）之上，不可只依賴裸打本機 `127.0.0.1:8188/prompt`」 | 官方頁（2026-10-27 逐句核對）沒有這條，反而寫 "Create your favorite app and more with ComfyUI, running it wherever you like."；"Developer Platform" 只出現在導覽列。程式方面，啟動器預設 `--platform local`（`run_studio.py:486`），也就是直接打 `127.0.0.1:8188`（`card_engine.py:1111-1112`） | R6 已確認不是規定（「App requirements」第 1 條明列完全本機可行）：刪除「規定」寫法，寫明預設是本機 ComfyUI、Developer Platform 是選項之一 | R5、R6 |
| D4 | AGENTS.md 第 46 行 | 「`--platform comfy_sdk` 在未設 `COMFY_API_KEY` 時預設接 comfy-api-proxy」；「Open Weights Only 組只能走這條，Router 是閉源模型的轉接」 | 前半句正確，但只在明確帶 `--platform comfy_sdk` 時成立（`card_engine.py:1105-1113`），讀者容易誤以為是預設。後半句的依據就是 D3，官方頁沒有；Open Weights Only 只禁止夥伴節點與閉源 API，本機 ComfyUI 跑開放權重同樣符合 | 改寫成「預設 local；要走 Developer Platform 才帶 comfy_sdk」；「只能走這條」刪除 | R5、R6 |
| D5 | AGENTS.md 第 11 行 | "Open weights remain the default; hybrid requires an explicit authorized choice." | 媒體生成成立（`docs/SPEC07_STUDIO_ROUTING.md:7-9`）；但代理模型預設是 OpenAI（`providers.py:40-42`），還有 chatgpt.com 路徑 | R2、R3 做完後成立；文件註明範圍包含代理與評分模型 | R2、R3、R5 |
| D6 | AGENTS.md 第 48 行 | 「預設工作流採用 100% 開放權重……同時符合 Best Overall 與 Open Weights Only 參賽條件」 | 預設工作流 ✓；但 Open Weights Only 也要看代理與評分模型，目前的預設不符合 | 補一句「代理與評分模型也須為開放權重（SPEC_20 供應商原則 1）」 | R5 |
| D7 | AGENTS.md 第 22–27 行 | 給接手代理的閱讀清單把 SPEC_08 列為「主規格／最新範圍優先」 | 之後已有 SPEC_09～SPEC_19 與本規格 | 改成指向 `docs/specs/` 的最新規格與 SPEC_20 | R5 |

**其他文件的同類問題**

| # | 文件位置 | 文件寫的 | 程式與事實 | 修法 | 需求 |
|---|---|---|---|---|---|
| D8 | `docs/ZEROFIELD_SPEC.md` 第 27 行 | "Agents and heterogeneous workers do the heavy lifting" | 預設沒有可用模型；README 用 `--no-worker`；判斷步驟多為規則 | 改寫成現況；C 包落地後再更新 | R5 |
| D9 | `docs/ZEROFIELD_SPEC.md` 第 80 行 | 預設工作流含 "SAM2 / Depth controls" | `workflows/` 裡沒有 SAM2 或深度模型節點；深度是 FFmpeg 產生的 `luma_depth` 結構片 | 刪除 SAM2／Depth，或寫明是 FFmpeg 結構片 | R5 |
| D10 | `docs/SPEC08_CONSOLE.md` 第 36–39 行 | 快速建立助手 "local default `qwen3.8:27b-16k` via Ollama" | 預設其實是 api.openai.com（`providers.py:40-42`）；`27b-16k` 是本機 Modelfile 標籤 | R2 做完後改成 `qwen3.8:27b`，並說明情境長度設定 | R2、R5 |
| D11 | `docs/ARCHITECTURE_AND_HANDOFF.md` 第 32 行 | 代理「可以隨時更換模型供應商（OpenAI、Gemini、Claude、OpenRouter、Ollama）」 | 預設環境只放行本機；非本機要管理者設白名單、金鑰變數與價格上限；換成閉源還要混合模式（原則 3） | 改寫成五條原則 | R5 |
| D12 | `README.md` 第 56、77 行 | 快速開始用 `--no-worker`；只寫「設定本機開放權重端點」，沒有步驟 | — | 加「Models」一節：安裝 Ollama、`ollama pull qwen3.8:27b`、`OLLAMA_CONTEXT_LENGTH`、不帶 `--no-worker` 啟動；OpenRouter 為選配，不在展示路徑；閉源要混合模式 | R5 |
| D13 | `project_assistant/providers.py` 第 6–7、24 行（註解） | 列出 `responses`（ChatGPT Responses 串流端點） | R3 移除後過時 | 隨 R3 更新 | R3 |

## 2. 需求

### 2.1 P0：先做

| R | 名稱 | 內容 |
|---|---|---|
| R1 | 修鎖死 | 依 §4.1 結算失敗的一輪：本機端點的任何失敗、非本機但請求沒送出或被拒（連線被拒、DNS 失敗、HTTP 400／401／403／404／413／422／429），都結算為已終止，不留 `uncertain`。只有請求已送出、結果不明的情況（逾時、連線中斷、5xx、回應過大）才留 `uncertain`。`uncertain` 超過保留時間（新設定 `rate_limits.uncertain_hold_seconds`，預設 600 秒）就不再佔並行名額，但照樣計入花費，直到管理者對帳。新增對帳 API（§4.1）。 |
| R2 | 預設本機模型與劇組就緒 | `provider_from_env` 預設改為 `http://127.0.0.1:11434/v1`＋`qwen3.8:27b`。沒設任何 `OPENBENCH_*` 時整組套用本機預設，含 effort `medium`；自訂了端點或模型時不自動帶 effort，除非另設新增的 `OPENBENCH_REASONING_EFFORT`（避免把 `reasoning_effort` 送給不支援的模型）。免金鑰判斷改成和 `execution_governance.local_url()` 相同的規則（只看主機名，含 `::1`）。新增就緒 API（§4.2）。劇組名單的狀態改成「背景程式有心跳且沒有阻擋」才算 `online`，否則顯示新的 `needs_setup`。劇組看板加一條橫幅，逐條列出劇組不能做事的原因與修正方法。 |
| R3 | 移除 chatgpt.com | `model_client.py` 只保留 `ModelError`、`TurnResult`、`MAX_ROUNDS`、`LAST_ROUND_NOTE`，刪除 chatgpt.com 傳輸與權杖讀取（`URL`、`USER_AGENT`、`credentials`、`_default_bearer_token`、`_jwt_account_id`、`forget_credentials`、`request_body`、`stream_once`、`_stream_with_retry`、`run_turn` 及其輔助函式）。`responses`（含 `OPENBENCH_PROVIDER=direct` 別名）從允許的類型移除（`agent_registry.py:152`、`:174`；`agent_console_store.py:417`；`execution_governance.py:239-242`、`:662`；`providers.py:37-39`）。已存的 `responses` 設定在讀取時回報 `kind_removed`，不發出任何連線。`agent_runtime.py:166-171` 與 `outcome_grader.py:67-70` 的非 `openai_compat` 分支改成回傳設定錯誤。介面文案 `configureOPENBENCHAPIKEYOPENAIAPIKEYOrLocalCLI`（`en.json`、`zh-TW.json` 第 1680 行，中文版寫著 `~/.codex/auth.json`）一併改寫或移除。改寫依賴這條路的測試（§5）。 |
| R4 | Ollama 相容 | 不再送 `tool_choice`。第 16 輪不帶 `tools`，改附 `LAST_ROUND_NOTE`（「用已查到的內容回答」）。README 寫明以 `OLLAMA_CONTEXT_LENGTH=16384`（或更高）啟動 Ollama。劇組對話預設 `reasoning_effort=medium`，評分維持 `low`。 |
| R5 | 文件對齊 | 依 §1.3 修正 D1–D12。README 新增「Models」一節，照五條原則寫：本機預設、託管開放權重選配且不在展示路徑、閉源需混合模式。 |
| R6 | 確認平台規定（已確認，不改程式） | 2026-10-27 確認不是規定：官方頁「App requirements」第 1 條要求用 ComfyUI 建構，執行方式不限（完全本機、Comfy Cloud、Developer Platform、Comfy Router、Comfy SDK 或混用）。條文由前端元件從網站翻譯檔載入，只看頁面 HTML 找不到。展示啟動維持 `--platform local`；文件不再寫成規定。第 3 條要求在示範影片說明另外結合的工具與模型，示範影片要交代劇組用的本機語言模型。 |
| R7 | 分拍提示詞提案 | 與 R19 合併實作（§7 決定 10）。新增 `POST /aivideo/open/v1/shots/{id}/beat-proposals`：由攝影指導依 §4.4 的格式寫分拍，編譯成 Phase 2 的提示詞格式，產生「Action & Audio Prompt」欄的 `table_edit` 提案，在既有的 ShotProposals 審核；沒有模型時回 409，不做任何寫入。 |

### 2.2 P1／P2

**A. 供應商層與治理（P1）**

| R | 名稱 | 內容 |
|---|---|---|
| R8 | 供應商目錄與能力旗標 | 新增 `project_assistant/provider_catalog.json`（§4.3）：每個預設帶分級與能力（tools、tool_choice、json_schema、vision、image_url、情境長度）。送出的內容依能力決定：沒有 `tool_choice` 就不送；不收圖片網址就轉 base64；有 json_schema 就用 `response_format`。 |
| R9 | 三級用量分級與政策 | 分級為 `local_open`／`hosted_open`／`closed`，取代「本機 vs 非本機」。`open_weights_only`：允許 `local_open`；`hosted_open` 要管理者另開「託管開放權重」開關。`hybrid_studio`：全部允許。部署天花板 `OPENBENCH_PRODUCTION_POLICY` 也管代理模型。`hosted_open` 的看圖請求依目錄價格計費，不再一律拒絕。 |
| R10 | 情境預算 | 每輪送出前估算長度（位元組 ÷ 3 的保守估計，或目錄提供的 tokenizer 比例）；超過模型情境的 80% 就修剪較舊的歷史與工具輸出，並在結果裡註明已修剪。每個劇組工作有自己的 `reasoning_effort`。 |
| R11 | 評分與快速建立助手走治理 | `take_grader.vision()` 與快速建立助手都改用 `ProviderAdmission`。本機不計費、不擋；非本機依 R9。 |
| R12 | 失敗分類與實際模型 | 失敗分類為 local／quota／auth／provider／timeout／empty／output，在使用者看得到的地方寫成白話（借用判斷台的做法）。帳本記錄回應裡實際的 `model`。 |
| R13 | GPU 仲裁器 | 改用跨程序的仲裁（PostgreSQL advisory lock，以 GPU 主機為鍵），涵蓋本機 ComfyUI 算圖、連戲評分、本機模型呼叫三者。延續「ComfyUI /free → 等 VRAM → 呼叫 → keep_alive:0」，並改成按階段批次：一集的規劃全部做完再算圖，同一鏡的 Take 一次評完。 |
| R14 | 新專案的管線工人 | 使用者自己的專案也要有本機工人與預設管線（目前只註冊給展示專案，`run_studio.py:524`）。做法見待決 7。 |

**B. 工具層、情境與提案（P1）**

| R | 名稱 | 內容 |
|---|---|---|
| R15 | 宣告式工具登記 | 一張表宣告工具的名稱、說明、參數格式、預設政策、是否會寫入、會出現在哪些清單；`tool_specs`、`agent_policy` 的拒絕清單、中控台與 UI 的工具清單都從這張表產生。所有工具都驗證參數。 |
| R16 | 情境工具 | `read_episode`、`read_scene`、`read_shot`（含 meta、3D 計畫、前後鏡）、`read_cast`（含造型與參考圖網址）、`list_takes`（含評分）。輸出結構化 JSON 並包在結果信封裡（§4.5）。 |
| R17 | 提案只鎖目標格 | 單步提案改成只鎖目標列與目標格，其他待審提案自動對齊新版本。這會改動 SPEC_08 契約與它的測試（待決 4）。 |
| R18 | 非表格提案 | 3D 計畫與質感設定這類寫進鏡頭 meta 的提案（作法見待決 5），要能在 PrevisStage 的鬼影與生成台就地審核。 |

**C. 劇組規劃工作（P1）**

每個工作都遵守固定決策 12（格式、驗證、重試一次、規則退路），並在對應的地方就地審核。

| R | 判斷步驟 | 內容 |
|---|---|---|
| R19 | 分拍提示詞（J7） | R7 沒做的話在這裡做；另外在生成台的提示詞區（SPEC_19 R9）加「請劇組寫分拍」入口。 |
| R20 | 鏡頭與運鏡（J8） | 輸出對齊 `plan.js` 的 `LENSES`／`MOVES` 與 Optical Rig 文字，產生欄位提案，並在 3D 片場顯示鬼影攝影機。 |
| R21 | 描述與造型（J3、J4） | 描述寫進 soul-cast 的鎖定外觀欄，只寫外觀、不寫構圖詞（Phase 2 教訓）；造型產生新的變體列。在 StoryWorld 就地審核。 |
| R22 | 出場（J5） | 依場次角色解析代名詞；插入鏡只綁場景（Phase 2 教訓）。 |
| R23 | 拆鏡與改編（J1、J2、J6），自動評分接上故事 API | 透過寫作預覽的 `adaptation` 與 `impact` 產生候選版本，規則版本當退路。故事 API 產生的 Take 也要觸發自動評分（目前只有管線會，`flow_runner.py:1029-1030`）。 |
| R24 | 劇組前製流程 | 一個派工流程依序跑：編劇（劇本）→ 美術（角色、場景、道具）→ 攝影指導（鏡頭、3D）→ 連戲（檢查）。每段之間有人工「鎖」：劇本鎖 → 清單鎖 → 分鏡鎖。前一段沒鎖，下一段不開始。已實作：`project_assistant/crew_preproduction.py`（`story_record` 的 `crew_flow`，每集一個進行中的流程）。鎖只有導演或製片總監能設，記錄設定者、時間、內容快照與 `content_hash`，送出時要帶畫面上看到的雜湊；鎖定內容之後被改，流程停止並列出改了什麼、取消它的工作、標出過時提案（讀取流程時與工人執行前、提案前各查一次）。各段工作以 `automatic=True` 送出：總開關暫停時該段不開始、已排隊的不被領取，手動請劇組不受影響。流程不送任何生成（R13 批次：整集規劃完才算圖）。「每鏡有誰」放在美術段、清單鎖之前（與手冊一致，避免和分拍搶同一格）。連戲工作 `crew_continuity.py`（場記，場次或整集；每個問題附依據欄位與把握度，能改欄位的修正成為該鏡提案，規則退路只做計畫層檢查；評測轉接 `run_eval_job`）。 |
| R25 | 觸發點 | 建好分鏡後出現「讓劇組前製」卡片；生成台各組有「請劇組」按鈕；StoryWorld 的資產卡有「請美術補描述」。全部顯示在劇組看板，可以取消。已實作：建好分鏡後，鏡頭舞台的鏡頭詳情出現「讓劇組前製」卡片（`ui/src/PreproductionPanel.jsx`），故事與世界的劇本檢視有完整流程面板與「檢查連戲」；流程與工作都在劇組看板，可取消（`/orchestration/crew-flows/{flowId}/cancel`）。生成台的「請劇組」等 SPEC_19 併入後依 `crewJobModel.js` 的 `GENERATION_DESK_CREW` 接上。 |

**D. 3D（P1）**

| R | 名稱 | 內容 |
|---|---|---|
| R26 | 3D 計畫存後端 | 新增 `GET`／`PUT /aivideo/open/v1/shots/{id}/previs-plan`，存在 `meta_<shotId>.previsPlanFull`（`{plan, planRevision, updatedAt, updatedBy}`；`previsPlan` 是分鏡種子，重建分鏡會覆寫，所以另開欄位）。寫入要帶 `If-Match` 或 `baseRevision` 版本，版本不符回 409。瀏覽器暫存降級成未存檔的草稿；預演 WebM 裡的計畫只當備份。 |
| R27 | 結構化操作與求解 | 操作格式見 §4.6。求解共用前端既有的計畫程式（`plan.js`、`blocking.js`），不在 Python 重寫一份。已實作：`propose_previs_ops`（`project_assistant/previs_ops.py`、`ui/src/previs/ops.js`）。 |
| R28 | 無頭算圖與看圖驗證 | 伺服器端以無頭瀏覽器跑同一套預演程式，輸出接觸表或 WebM（待決 6）。提案附預覽圖；可選擇交給視覺模型檢查，並由人確認。已實作：無頭 Edge／Chromium 的接觸表（`headless_previs.py`、`previsRender.js`），WebM 未做。 |
| R29 | 3D 與文字同步、角色代碼 | 存 3D 計畫時，用 `describePlan` 一併提議更新 Optical Rig 與 Camera Motion 欄。`plan.cast` 改帶 `@CAST` 代碼。 |

**E. 對外介面（stdio 為 P1，其餘為 P2）**

| R | 名稱 | 內容 |
|---|---|---|
| R30 | stdio MCP 伺服器 | 新增 `zerofield-mcp` 指令，支援 MCP 2026-07-28（`server/discover`、每個請求在 `_meta` 帶版本），並相容 2025-11-25 以前的握手式版本。只提供 R16 的讀取工具、提案工具、受政策管制的生成，以及流程手冊（§4.7）。 |
| R31 | 服務帳號權杖 | 啟用既有的 `agent_service_account` 表。權杖限定專案、工具、寫入模式，有到期時間；稽核記錄外部代理的身分。 |
| R32 | 流程手冊 | repo 內新增 `skills/` 資料夾（SKILL.md 格式），內容包括：劇組前製、單鏡分拍、3D 走位、接點巡檢。另以 `get_workflow` 工具回傳。手冊沒觸發時，工具層照樣限制（固定決策 8）。 |
| R33 | Streamable HTTP（P2） | 只綁本機，用服務帳號權杖驗證。 |
| R34 | MCP Apps 卡片（P2） | 生成台、成片視窗、3D 片場三張卡片（待決 9）。已實作：3D 預覽接觸表（`project_assistant/mcp_apps.py`、`mcp_cards/previs_contact_sheet.html`，`read_shot` 與 `propose_previs_ops`）；生成台與成片接點兩張等 SPEC_19 併入後再做。 |
| R35 | ACP 工人選配（P2） | 沿用 `acp_bridge`，補齊判斷台的鎖權限：只開指定的 MCP、清除密鑰環境變數、啟動後確認模式、權限請求預設拒絕且一次性、意外工具呼叫就砍掉整棵程序、擋斜線指令、離線列出工具清單。 |

**F. 中控台（P1）**

| R | 名稱 | 內容 |
|---|---|---|
| R36 | 模型設定精靈與健康檢查 | 依序實際試對話、工具呼叫、JSON schema、看圖；確認模型存在；顯示情境長度。 |
| R37 | 角色 × 模型矩陣 | 從 `/models` 清單選模型，標示分級。 |
| R38 | 顯示卡面板 | 顯示剩餘 VRAM、ComfyUI 佇列、目前載入的模型。 |
| R39 | 工作佇列與失敗 | 全專案的對話、派工、工人失敗與 `uncertain` 預留；提供對帳入口（R1 的 API）。 |
| R40 | 自動工作總開關 | 自動評分、劇組前製、排程部署都能從一處暫停。 |
| R41 | 外部代理連線頁 | 發權杖、設範圍、看稽核（R31）。 |

**G. 驗收工具（P1）**

| R | 名稱 | 內容 |
|---|---|---|
| R42 | 劇組評測集 | 難例鏡頭（正面、高張力、情緒外露）的分拍、走位、接點各若干題，含標準答案與評分方式。換模型或改提示詞時重跑。 |
| R43 | 離線工具清單檢查 | 列出內部劇組與 MCP 實際看得到的所有工具，多出一個就失敗。 |
| R44 | 空白專案實走 | 空白專案、只用介面、只用本機模型走完一集；記錄斷點，收據放 `docs/spec20-verification.json`。 |

## 3. 介面

**P0：劇組看板橫幅（R2）**
- 位置：`ui/src/assistant/AgentBoard.jsx` 角色清單上方。
- 有阻擋時，每條原因一行，例如「本機模型連不上：請啟動 Ollama」、「找不到 qwen3.8:27b：執行 `ollama pull qwen3.8:27b`」、「背景程式沒開：請不帶 `--no-worker` 重新啟動」，各附一個「再檢查一次」按鈕。
- 全部就緒時橫幅消失；角色狀態顯示 `online`。
- 文案只用 `en.json`／`zh-TW.json` 的語意鍵（同 SPEC_19 固定決策 9）。

**P1：** 「讓劇組前製」卡片、生成台的「請劇組」入口、PrevisStage 的鬼影與操作預覽、中控台各頁。需要畫面時，另外畫進重設計畫布的第 11 組畫板。

## 4. 契約

### 4.1 失敗結算（R1）
| 情況 | 預留結算 | 佔並行名額 | 計入花費 |
|---|---|---|---|
| 本機端點（127.0.0.1、localhost、::1）的任何失敗 | 已終止（`finalized`） | 否 | 否 |
| 非本機，請求沒送出（連線被拒、DNS 失敗） | 已終止，觀測成本 0 | 否 | 0 |
| 非本機，HTTP 400／401／403／404／413／422／429 | 已終止，觀測成本 0 | 否 | 0 |
| 非本機，逾時、送出後連線中斷、5xx、回應過大 | `uncertain`（維持現狀） | 保留時間內佔用 | 依上限計，直到對帳 |
| 成功 | 依用量結算 | 否 | 依用量 |

- `ProviderAdmission.after(usage, outcome='succeeded', *, known_terminated=False, observed_cost=None)`，參數原樣傳給 `finalize()`（`execution_governance.py:158`、`:288`）。
- `reserve()` 計算並行數時，`uncertain` 只在 `COALESCE(started_at, created_at)` 落在保留時間內才算；花費上限的計算不變。
- **新增對帳：** `POST /projects/api/{slug}/agent-console/reservations/{requestKey}/reconcile`，body `{"observedCostUsd": "0.0123"}`，只限管理者。把 `uncertain` 改成 `finalized` 並寫一筆帳本調整；目標不是 `uncertain` 時回 409。

### 4.2 就緒 API（R2）
`GET /projects/api/{slug}/agents/readiness`（新增；任何成員可讀；結果快取 30 秒）
```json
{
  "ready": false,
  "checkedAt": "2026-10-28T09:00:00Z",
  "worker": {"running": false, "lastSeenAt": null},
  "providers": [
    {"model": "qwen3.8:27b", "destination": "local", "tier": "local_open",
     "reachable": true, "modelPresent": false, "agents": ["coordinator", "sheet_ops"]}
  ],
  "blockers": [
    {"code": "worker_not_running", "agentKey": null, "fix": "restart_without_no_worker"},
    {"code": "model_missing", "agentKey": "sheet_ops", "fix": "ollama_pull", "model": "qwen3.8:27b"}
  ]
}
```
- **阻擋代碼：** `worker_not_running`、`provider_unreachable`、`model_missing`、`auth_missing`、`network_policy`、`pricing_missing`、`reservations_stuck`、`agent_disabled`、`cli_blocked`、`kind_removed`。
- **用量分級被政策擋下（R9）** 沿用 `network_policy`，修正方法為 `enable_hosted_open`（`hosted_open` 但管理者沒開 `provider_policy.hosted_open_enabled`）或 `use_hybrid_policy`（`closed` 但有效製作政策不是 `hybrid_studio`）；阻擋另帶 `model`、`host`、`tier`。`providers[].tier` 依供應商目錄判定，有對上目錄時另帶 `catalogId`。
- **只會自動探測本機端點**（`GET {base}/models`，逾時 2 秒），並比對模型名稱。非本機端點回傳 `"reachable": null`，請管理者到中控台測試。
- **不回傳金鑰；非本機端點只回傳主機名。**

### 4.3 供應商目錄（R8，P1 草稿）
```json
{"id": "ollama-qwen3.8-27b", "label": "Qwen3.8 27B (local, Ollama)", "kind": "openai_compat",
 "base_url": "http://127.0.0.1:11434/v1", "model": "qwen3.8:27b", "tier": "local_open",
 "capabilities": {"tools": true, "tool_choice": false, "json_schema": true, "vision": true, "image_url": false},
 "context_tokens": 16384, "default_effort": "medium"}
```
另有 `openrouter-qwen3.8-27b` 與 `openrouter-deepseek-v4.1-flash-1017`（`hosted_open`，需要 `api_key_env` 與價格）。DeepSeek 那筆是使用者 2026-10-27 指定的開發用模型（開放權重 `deepseek-ai/DeepSeek-V4.1-Flash-1017`，可看圖、工具、JSON schema），讓開發與實走不必和 ComfyUI 搶 GPU；`context_tokens` 設 131072 是我們允許的預算，不是模型上限（1M）。產品預設仍是本機 Ollama。閉源預設只在 `hybrid_studio` 下列出。

### 4.4 分拍提示詞格式（R7／R19）
模型輸出：
```json
{"setup": "One continuous 4-second shot inside the observatory at dusk; rain on the glass. Kael, …",
 "beats": [{"from": 0.0, "to": 1.5, "camera": "wide from the left", "action": "Kael turns from the glass toward the console"},
           {"from": 1.5, "to": 2.5, "camera": "dolly in, arc right", "action": "he reaches for the brass dial with his right hand"}],
 "sound": "rain on glass, the click of the dial",
 "constraints": ["One person only", "No text"]}
```
- **驗證：** `beats` 從 0 開始、首尾相接、結束時間等於鏡頭秒數（`DURATIONS` 為 4／6／8／10）；原本的 `@` 標籤全部保留；不得出現攝影機品牌字樣。
- **編譯成文字：** 設定句 → 每拍一行 `0-1.5s: …` → `Sound: …` 與限制句。這是 `research/motion_lab/prompt_s03.txt` 的格式。

### 4.5 結果信封（R16）
每個讀取工具都回傳 `{"status", "data", "sources", "warnings", "limitations", "hash"}`，每次呼叫都寫一筆稽核。

### 4.6 3D 操作（R27、R28，已定案）
工具 `propose_previs_ops`（只產生提案）的參數：
```json
{"shotId": "sh_…", "baseRevision": 7, "ops": [
  {"op": "place", "cast": "@CAST-01", "relativeTo": "console", "offset": [-1.0, 0.0], "facing": "window"},
  {"op": "camera", "size": "medium", "angle": "low", "lens": 35, "move": "pushin", "from": "K1", "to": "K2"},
  {"op": "retime", "beat": 2, "at": 0.6}
]}
```
- **欄位封閉**：請求只有 `shotId`、`baseRevision`、`ops`（1–32 個）；每種操作只收下表欄位，多一個就拒絕。
- **單位與座標**：片場座標是站位為原點的公尺，+z 朝主控台與玻璃、-z 朝攝影機那一側，`offset` 是 `[x, z]` 公尺（各 ±8 以內）。朝向 0 是 +z。

| 操作 | 欄位 | 規則 |
|---|---|---|
| `place` | `cast`、`relativeTo`、`offset`、`facing` | `cast` 是角色表上的 `@CAST` 代碼，每人一次。`relativeTo` 是場景目標（天文台：console、plinth、dial、recorder、console_edge、window_glass，`window` 是 window_glass 的別名；視差場景：far、mid、near；空場景沒有）、`mark`（原點），或已在場（存檔計畫裡或前面的操作放過）的代碼。`facing` 另可用 `camera`（鏡頭中段的攝影機位置）與 `room`（-z）。新代碼若計畫的主角還沒有代碼就成為主角（`plan.code`），否則加入 `plan.cast`；已在場的人移動。 |
| `camera` | `size`、`angle`、`lens`、`move`，選填 `from`、`to` | `size`：wide、full、medium、close、extreme_close；`angle`：low、eye、high、overhead；`lens` 屬 `LENSES`、`move` 屬 `MOVES`。求解器從主角面向的那一側框住所有在場的人，寫出該運鏡的鍵 K1…Kn（static 1 個、orbit 3 個、其他 2 個）；`from`／`to`（預設第一與最後一個）選用其中一段，攤到整個鏡頭。最多一個。 |
| `retime` | `beat`、`at` | `beat` 是 3D 片場的表演段落（`plan.use` 的技能；Walk in 動作算一段），從 1 數；`at` 是該段新的開始點，鏡頭長度的 0–1。前後段落與鏡頭邊界會擋住它，求解器會註明實際落點。 |

- **求解**：前端 `ui/src/previs/ops.js`（共用 `plan.js`、`blocking.js`、`storyPlan.js`）依序處理放置、朝向、攝影機、朝向攝影機者、重排時間。同一份存檔計畫（或分鏡種子）加同一組操作，一定得到同一份計畫；`tests/fixtures/previs_ops_golden.json` 是 JS 的輸出，Python 與 JS 的驗證用同一份檔案對答案。伺服器以無頭 Edge／Chromium 跑同一支程式（`project_assistant/headless_previs.py`），不需要 Node；頁面只能讀這次建置的檔案與交給它的場景圖，其餘網址一律拒絕。
- **提案**：`shot_meta` 的 `previsPlan` 提案，目標另帶 `ops`、`opsHash`、`solve`（`solved`／`ops_only`、求解者、警告）與 `preview`（6 格接觸表，存為專案資產）。`baseRevision` 不符時回 409 `DRAMA_PREVIS_REVISION_CONFLICT`（準備時與寫入提案前各查一次）；操作不合法回 422，並指出欄位路徑。
- **沒有瀏覽器時**：提案只存操作（`value` 為 null）。審核的 3D 片場用同一支 `ops.js` 求解並顯示鬼影；按核准時先把這份結果附上（`POST /projects/api/{slug}/assistant/proposals/{id}/solution`，驗證角色表並檢查與操作一致），再套用。沒有求解結果的提案一律不能核准，不會寫入未求解的計畫。
- **看圖檢查（選用）**：專案設定 `previs_vision_check` 為 `on` 時，提案建立後把接觸表交給連戲監督的視覺模型，走治理與 GPU 仲裁，只在提案上加註（`vision`），由人確認。算圖本身用 SwiftShader（CPU），不佔 GPU。

### 4.7 MCP 工具與權杖範圍（R30／R31，P1 草稿）
- 讀取：R16 的情境工具。
- 提案：`propose_shot_prompt`、`propose_camera`、`propose_previs_ops`、`propose_asset_description`、`propose_cast`、`propose_look`。
- 生成：`request_generation`，帶冪等 `requestId` 與費用估計，走製作政策，不得繞過固定決策 10。
- 手冊：`get_workflow`。
- 權杖範圍：`{project, tools: [...], writeMode: "propose_only" | "generate", expiresAt}`。

## 5. 檔案

**P0**

| 檔案 | 需求 | 改什麼 |
|---|---|---|
| `project_assistant/providers.py` | R1、R2、R3、R4 | 失敗結算、預設值、免金鑰判斷、最後一輪、註解 |
| `project_assistant/execution_governance.py` | R1、R3 | `after()` 參數、`reserve()` 保留時間、`reconcile()`、移除 `responses` |
| `project_assistant/agent_console_store.py` | R1、R3 | `uncertain_hold_seconds` 預設值；`:417` 移除 `responses` |
| `project_assistant/model_client.py` | R3 | 只留共用型別 |
| `project_assistant/agent_runtime.py`、`outcome_grader.py` | R3 | 移除 `run_turn` 分支 |
| `project_assistant/agent_registry.py` | R2、R3 | 名單狀態 `needs_setup`；`:152`、`:174` 移除 `responses` |
| `project_assistant/crew_readiness.py`（新） | R2 | 就緒檢查 |
| `project_docs/http.py`、`project_docs/console_http.py` | R1、R2 | 就緒與對帳路由 |
| `ui/src/assistant/AgentBoard.jsx`、`ui/src/i18n/locales/en.json`、`zh-TW.json` | R2、R3 | 橫幅與文案；移除 `configureOPENBENCHAPIKEYOPENAIAPIKEYOrLocalCLI` |
| `tests/test_providers.py`、`tests/test_agent_console_governance.py` | R1、R2、R4 | 失敗結算、預設值、最後一輪 |
| `tests/test_agent_console.py`（約 536–560 行）、`tests/test_agent_console_governance.py`（約 158–180 行）、`tests/test_agent_runtime.py`（第 89、136 行）、`tests/test_studio_console_tools.py`（約 38–60 行） | R3 | 改寫依賴 `responses`／`model_client.run_turn` 的測試 |
| `tests/test_crew_readiness.py`（新）、`ui/tests/` 相關測試 | R2 | 就緒 API 與橫幅 |
| `docs/DESIGN_AND_DEV_GUIDELINES.md`、`AGENTS.md`、`docs/ZEROFIELD_SPEC.md`、`docs/SPEC08_CONSOLE.md`、`docs/ARCHITECTURE_AND_HANDOFF.md`、`README.md` | R5 | §1.3 D1–D12 |

**P1／P2**：檔案在各包開工前另列。原則是：新工具只改宣告表（R15）；3D 求解不在 Python 重寫（R27）。

## 6. 執行順序
多代理平行實作：每個代理在自己的工作樹做一個工作包，審查後立刻併進 `feat/spec20-integration`，依賴到齊的工作包馬上開工，不等整波。測試分三層：代理只跑自己新增的測試與直接改到的檔案的測試；併入時只跑該包新增的測試與有衝突的檔案的測試；完整測試只在全部完成後跑一次，並分片並行。複雜的工作包交給 Opus，單純的交給 Sonnet。

| 波 | 工作包（並行） | 依賴 |
|---|---|---|
| 1 | 供應商核心（R1、R3、R4、R2 的預設值）；劇組就緒（R2 的就緒 API、名單狀態、看板）；工具登記（R15、R43）；文件對齊（R5）；提案只鎖目標格（R17）；3D 計畫存後端（R26、R29） | 無 |
| 2 | 供應商進階（R8、R9、R10、R12）；評分治理與 GPU 仲裁（R11、R13）；情境工具（R16）；非表格提案（R18 的 3D 計畫部分）；中控台（R36、R37、R39；R38、R40）；新專案的管線工人（R14） | 第 1 波 |
| 3 | 劇組工作框架與分拍、鏡頭（R7／R19、R20）；3D 操作與無頭算圖（R27、R28）；對外 stdio MCP 與權杖（R30、R31）；流程手冊（R32）；ACP 工人加固（R35）；劇組評測集（R42） | 第 2 波 |
| 4 | 描述、造型、出場、拆鏡與改編（R21、R22、R23）；前製流程與觸發點（R24、R25）；Streamable HTTP 與 MCP Apps（R33、R34）；外部代理連線頁（R41） | 第 3 波 |
| 5 | 整合驗收、README 能力敘述更新、收據；GPU 實機驗收（A14、A15、A17、R42 實跑、R44），等使用者確認 GPU 空檔 | 第 4 波 |

R6 已確認（見 §7 第 1 條），不阻擋任何一波。

## 7. 待決與已決
使用者 2026-10-27 指示完整實作；以下技術決策由執行者先定，理由寫在各條，使用者可以推翻。

1. **平台規定（R6）：已確認不是規定（2026-10-27）。** 官方頁「App requirements」第 1 條把 Developer Platform 列為執行方式之一，完全本機同樣符合。`docs/HIGGSFIELD_FEATURE_INVENTORY_2026-10-18.md` 的「built using the Comfy Developer Platform」與現行條文不符。展示啟動維持 `--platform local`。
2. **託管開放權重是否符合 Open Weights Only：待使用者決定要不要問主辦。** 在得到答覆前，`hosted_open` 預設關閉，展示路徑只用本機（原則 1、2）。
3. **`uncertain` 保留時間：決定 600 秒。** 可在花費上限頁調整。
4. **提案只鎖目標格（R17）：決定實作。** 理由：劇組一次替多鏡提案是 C 包的前提，整頁鎖會讓同頁第二個提案必然失敗。單步提案改成只鎖目標列與目標格；其他待審提案若目標沒被動到就自動對齊新版本；同一格被改過仍然失敗並說明原因。`test_source_changed_while_executing_or_waiting_for_approval_cannot_write` 改成「改到別列可以套用、改到同一格會失敗」，另補測試。
5. **非表格提案（R18）：決定新增提案動作 `shot_meta`。** `assistant_proposal.action` 本來就是自由文字，不需要遷移。目標帶 `{shotId, field, baseRevision}`，以欄位版本號防衝突，不鎖整頁；`service._write` 新增分支呼叫對應的故事模組。待審清單可依 `shotId` 查詢。第一個欄位是 `previsPlan`；`look` 等 SPEC_19 的 `story_look.py` 合進 main 後再接。
6. **無頭算圖（R28）：決定用同一套前端程式跑在無頭 Edge／Chromium（CDP）。** 理由：不重寫一份求解與算圖；Windows 本機都有 Edge。找不到瀏覽器時，提案只存操作，由人在 3D 片場預覽。
7. **新專案的管線工人（R14）：決定由啟動器註冊一組本機工人，範圍為「這台伺服器上的所有專案」。** 新專案建立時套用預設管線（不含展示專案專用的種子）。
8. **小型常駐模型：決定預設不常駐**，只提供設定項。
9. **MCP Apps 卡片（R34）：決定做三張**：生成台摘要、成片接點、3D 預覽接觸表。
10. **R7：決定做**，與 R19 合併由同一工作包實作。

## 8. 驗收

**P0**

| # | 需求 | 驗收 | 方式 |
|---|---|---|---|
| A1 | R1 | 本機端點連不上時，同一角色連續觸發 3 次對話：每次都回明確的「模型連不上」；第 4 次照樣受理；資料庫裡這些預留不是 `uncertain`。 | DB 測試（假的連線拒絕） |
| A2 | R1 | 非本機端點回 401、429：預留結算為 `finalized`、成本 0，不佔並行名額。 | DB 測試 |
| A3 | R1 | 非本機端點逾時：預留維持 `uncertain` 並計入花費；超過保留時間後不再佔並行名額。 | DB 測試（固定時鐘） |
| A4 | R1 | 管理者對帳後 `uncertain` 變成 `finalized`，帳本多一筆調整；非管理者 403；目標不是 `uncertain` 時 409。 | API 測試 |
| A5 | R2 | 沒設任何 `OPENBENCH_*` 時，`provider_from_env()` 指向 `http://127.0.0.1:11434/v1`、`qwen3.8:27b`、effort `medium`；只設了 `OPENBENCH_API_BASE` 或 `OPENBENCH_MODEL` 時 effort 為空；設了 `OPENBENCH_REASONING_EFFORT` 時照設定。 | 單元測試 |
| A6 | R2 | `::1` 與 `localhost` 免金鑰；`https://example.com/localhost` 不算本機。 | 單元測試 |
| A7 | R2 | 背景程式沒開：就緒 API 回 `worker_not_running`；名單狀態是 `needs_setup`，不是 `online`；看板顯示修正方法。 | DB＋前端測試 |
| A8 | R2 | 本機端點連不上回 `provider_unreachable`；模型不在清單回 `model_missing`，附 `ollama pull` 指令。 | 假伺服器測試 |
| A9 | R2 | 就緒 API 的回應裡沒有金鑰；非本機端點只有主機名。 | 單元測試 |
| A10 | R3 | `git grep -n -i "chatgpt.com\|codex/auth.json"` 在程式、測試與介面文案裡為 0（文件與重新建置前的 `static/` 除外）。 | 指令 |
| A11 | R3 | `provider_config.kind` 為 `responses` 的代理：就緒 API 與中控台回 `kind_removed`，不發出任何連線。 | DB 測試 |
| A12 | R3 | 改寫後的後端測試全過；成果評分在 `openai_compat` 下照常運作。 | 完整後端測試 |
| A13 | R4 | 送出的請求不含 `tool_choice`；第 16 輪不帶 `tools`，並附 `LAST_ROUND_NOTE`。 | 假伺服器檢查請求內容 |
| A14 | R4 | 實機（GPU 空檔時）：Ollama 以 `OLLAMA_CONTEXT_LENGTH=16384` 啟動，對 `qwen3.8:27b` 送一則超過 6k token 的提示，回答能引用提示開頭的內容；`ollama ps` 的 PROCESSOR 為 100% GPU。 | 實機收據 |
| A15 | R2、R4 | 實機：預設設定下，連戲評分跑通一次（沿用 Phase 2 流程）。 | 實機收據 |
| A16 | R5 | §1.3 的 D1–D12 都已修正；文件不再把「必須建在 Comfy Developer Platform 上」寫成比賽規定（R6 已確認不是）。 | 人工核對 |
| A17 | R5 | 照 README 的「Models」一節，在乾淨環境只裝 Ollama 與模型，劇組看板顯示就緒。 | 實機收據 |
| A18 | R7 | 一鏡產生分拍提案：通過 §4.4 的驗證、`@` 標籤保留、在 ShotProposals 採用後寫入；沒有模型時回 409 且沒有任何寫入。 | DB 測試＋實機 |

**P1／P2**：各包開工前補齊。最低要求是：
- 每個劇組工作都有評測集分數（R42）；
- 工具清單檢查通過（R43）；
- 空白專案實走收據（R44）；
- MCP 用 MCP Inspector、Goose＋Ollama、Claude Code 各接一次並留收據。

## 9. 驗證與收據
- **後端：** 在一次性的 PG（埠 55471）上，全部完成後分片跑一次完整測試（`python -m unittest discover -s tests -v`，設 `OPENBENCH_TEST_DB_URI`），不碰展示資料庫（55440）。
- **前端：** `npm test --prefix ui` 與 `npm run build --prefix ui`。看板橫幅用無頭 Edge 以實際尺寸截圖檢查，不用小瀏覽器窗格。
- **實機**（A14、A15、A17）：只在使用者確認 GPU 空檔時做，用資料庫副本。
- **收據：** `docs/spec20-verification.json`，記錄 commit、測試數、實機結果與未驗證項目。

## 10. 交接提示
- **SPEC_19 正在另一個工作階段平行實作**（`feat/spec19-integration`，工作樹 `C:/ai_project/ZeroField-spec19`，測試資料庫埠 55461）。SPEC_20 以 main 為基準，盡量不碰 SPEC_19 的檔案：`project_docs/story_adoption.py`、`story_look.py`、`look_catalog.json`、`ui/src/takeModel.js`、`studio/context_compiler.py`、`studio/media_prep.py`，以及 `story_openapi.py` 的生成落地段（約 1081–1093 行）與採用、成片路由。
  - SPEC_20 的新路由放在新模組（例如 `project_docs/story_previs.py`、`project_docs/story_crew.py`），`story_openapi.py` 只加最少的註冊行。
  - 劇組入口做成獨立元件，先掛在現有的鏡頭詳情；SPEC_19 的生成台與右欄落地後再搬過去。
  - R23 的「故事 API 的 Take 自動評分」與 R18 的 `look` 提案，等 SPEC_19 對應部分合進 main 後再接。
  - SPEC_20 測試資料庫用埠 55471，不要用 55461。
- 不要動未追蹤的 `docs/specs/SPEC_17_*`、`ui/prototypes/story-planning/`、`ui/tests/storyPlanningPrototype.test.mjs`。
- 不呼叫任何付費供應商；沒有使用者提供的金鑰與明確同意，不打 OpenRouter。
- R1 與 R3 都會碰治理與帳本：先跑既有的治理測試確認基準，再改。
- 移除 `responses` 時，測試要改成走 `openai_compat` 假端點；不要為了讓測試通過，留下呼叫 chatgpt.com 的程式。
- 文件裡每一句能力敘述都要能在程式或收據裡找到出處；查不到的寫「未驗證」。
- 提交照 lean 流程：開 `fix/` 或 `docs/` 主題分支、`git add` 指定明確路徑、只在使用者要求時快轉 main，不推送。

## 11. 實作對照

狀態：**done** 是需求的內容都有程式，並有假模型或假服務的測試；**partial** 是做了一部分，缺的在備註；**deferred** 是還沒做，原因在備註。done 只代表程式與測試到位，不代表真實模型與 GPU 驗收通過（見本節末的未完成項目）。

| 需求 | 狀態 | 主要模組 | 備註 |
|---|---|---|---|
| R1 修鎖死 | done | `project_assistant/providers.py`、`execution_governance.py`（`reserve`、`finalize`、`reconcile`）、`agent_console_store.py`（`uncertain_hold_seconds`）、`project_docs/console_http.py`（對帳路由） | 測試 `tests/test_spec20_provider_core.py` |
| R2 預設本機模型與劇組就緒 | done | `providers.py`（`provider_from_env`）、`crew_readiness.py`、`agent_registry.py`（`needs_setup`）、`project_docs/http.py`（`/agents/readiness`）、`ui/src/assistant/AgentBoard.jsx` | `OPENBENCH_REASONING_EFFORT` 見 `docs/WORKERS.md` |
| R3 移除 chatgpt.com | done | `model_client.py`（只留共用型別）、`agent_runtime.py`、`outcome_grader.py`、`agent_registry.py`、`execution_governance.py` | `responses`／`direct` 回報 `kind_removed`，不發出連線 |
| R4 Ollama 相容 | done | `providers.py` | 不送 `tool_choice`，第 16 輪不帶 `tools` 並附 `LAST_ROUND_NOTE`；A14 實機通過（6.5k–11k token 的提示都引用到開頭，`ollama ps` 為 100% GPU、情境 16384）；超過情境的提示會被 Ollama 默默截斷，只有 R10 的預算擋得住 |
| R5 文件對齊 | partial | `README.md`、`AGENTS.md`、`docs/DESIGN_AND_DEV_GUIDELINES.md`、`docs/ZEROFIELD_SPEC.md`、`docs/WORKERS.md`、`docs/DEPLOYMENT.md`、`docs/STORY_WORKBENCH.md` | `docker-compose.yml` 已不預設任何模型端點，但容器裡的 `127.0.0.1` 不是主機上的 Ollama，其他主機上自架的模型又算閉源，Compose 下的劇組沒有可用的本機模型路徑、未驗證（`docs/DEPLOYMENT.md`）；A17 實測通過（2026-10-27）：內建資料庫預設埠被 Docker 占用時啟動器會當掉，已修成改用下一個空埠（`server._start_local_postgres`）；README 補上 Ollama 程式的模型資料夾要設進 `OLLAMA_MODELS` |
| R6 確認平台規定 | done | （不改程式） | 已確認不是比賽規定，見 §7 第 1 條 |
| R7 分拍提示詞提案 | done | `crew_planning.py`（`BEATS`）、`crew_jobs.py`、`project_docs/story_crew.py`（`beat-proposals`） | 沒有可用模型回 409 `DRAMA_CREW_NOT_READY`，不寫入 |
| R8 供應商目錄與能力旗標 | done | `provider_catalog.json`、`provider_catalog.py`、`providers.py` | 目錄有 Ollama、OpenRouter、OpenAI、Gemini 四筆 |
| R9 三級用量分級與政策 | done | `provider_catalog.py`、`execution_governance.py`、`console_model_matrix.py`（託管開放權重開關） | 開關在 Agent Console 的 Providers & API Keys → Roles and models |
| R10 情境預算 | done | `providers.py`（修剪歷史與工具輸出）、`crew_jobs.py`（每個工作自己的強度） | |
| R11 評分與快速建立助手走治理 | done | `take_grader.py`、`agent_console_service.py` | |
| R12 失敗分類與實際模型 | done | `model_client.py`（`FAILURE_CLASSES`，含 `gpu_busy`）、`providers.py`、`execution_governance.py`、`ui/src/assistant/providerFailures.js` | 八個類別，帳本記錄實際回應的模型 |
| R13 GPU 仲裁器 | partial | `gpu_arbiter.py`、`take_grader.py`、`studio/card_engine.py`、`studio/openapi_v2_hub.py`、`limb_worker.py` | 跨程序鎖與工作階段切換已做；沒有「規劃先於算圖」的優先序，等待者先到先得（FIFO）；4090 實走（R44）時每 5 秒取樣 344 次，語言模型從未與 ComfyUI 算圖同時常駐，算圖前卸載、評分前釋放 ComfyUI，沒有記憶體不足；中控台的 GPU 面板在算圖時也沒顯示占用者 |
| R14 新專案的管線工人 | done | `local_workers.py`、`run_studio.py`、`project_docs/service.py`（`create_project`） | |
| R15 宣告式工具登記 | done | `tool_registry.py`（`tool_specs`、`agent_policy`、`tool_host` 等由它產生） | |
| R16 情境工具 | done | `context_tools.py`（`read_episode`、`read_scene`、`read_shot`、`read_cast`、`list_takes`） | |
| R17 提案只鎖目標格 | done | `table_edits.py`、`service.py` | |
| R18 非表格提案 | partial | `shot_meta.py`、`ui/src/previs/ShotMetaReview.jsx`、`shotMetaModel.js`、`PrevisStage.jsx` | 3D 計畫（`previsPlan`）提案已做；質感（`look`）提案等 SPEC_19 的 `story_look.py` 合進 main（`crew_art.LOOK_HOOK` 留好接點） |
| R19 分拍提示詞（入口） | partial | `crew_planning.py`、`project_docs/story_crew.py`、`ui/src/CrewAsk.jsx`（鏡頭詳情「請劇組」） | 生成台提示詞區的入口等 SPEC_19 R9 |
| R20 鏡頭與運鏡 | done | `crew_planning.py`（`CAMERA`）、`shot_meta.py`、`ui/src/previs/PrevisStage.jsx`（鬼影攝影機） | |
| R21 描述與造型 | done | `crew_art.py`、`ui/src/StoryWorld.jsx`、`ui/src/CrewAsk.jsx` | 美術沒有獨立的名單角色，跑在編劇的設定上 |
| R22 出場 | done | `crew_art.py`（`appearances`） | 鏡頭與場次兩種目標；插入鏡只綁場景 |
| R23 拆鏡與改編、自動評分接故事 API | partial | `crew_writing.py`、`project_docs/story_crew.py` | 改編與拆鏡候選已做；「故事 API 的 Take 自動評分」那一半等 SPEC_19 的生成落地合進 main |
| R24 劇組前製流程 | done | `project_assistant/crew_preproduction.py`、`project_assistant/crew_continuity.py` | 三道鎖記錄內容雜湊，內容變動即停並列出變動；「誰在這鏡」改在美術段跑，避免和分拍搶同一格；連戲只查計畫、提示詞與評分，不看畫面，也不查跨場接點 |
| R25 觸發點 | partial | `ui/src/PreproductionPanel.jsx`、`ui/src/preproductionModel.js`、`ui/src/CrewAsk.jsx` | 「讓劇組前製」卡片、StoryWorld 入口與看板取消已做；生成台的「請劇組」按鈕等 SPEC_19（`GENERATION_DESK_CREW` 掛點） |
| R26 3D 計畫存後端 | done | `project_docs/story_previs.py`、`ui/src/previs/PrevisStage.jsx`、`storyPlan.js` | 欄位 `previsPlanFull`，帶版本號，衝突回 409 |
| R27 結構化操作與求解 | done | `previs_ops.py`、`ui/src/previs/ops.js`、`tests/fixtures/previs_ops_golden.json` | |
| R28 無頭算圖與看圖驗證 | partial | `headless_previs.py`、`ui/src/previs/previsRender.js`、`ui/previs-solver.html` | 只有六格接觸表，WebM 預覽沒做；看圖檢查是選用設定 `previs_vision_check` |
| R29 3D 與文字同步、角色代碼 | done | `story_previs.py`（`castOptions`）、`ui/src/previs/storyPlan.js`（`slateFromPlan`） | 同步場記是片場上的按鈕，由人按下，不是自動寫入 |
| R30 stdio MCP 伺服器 | done | `zerofield_mcp.py`、`mcp_protocol.py`、`external_tools.py` | 只用假客戶端測過；真實主機待辦 |
| R31 服務帳號權杖 | done | `service_accounts.py`、`db/164_agent_service_accounts.sql`、`project_docs/agent_http.py` | |
| R32 流程手冊 | done | `skills/`（四份手冊）、`external_tools.py`（`get_workflow`）、`setup.py`、`MANIFEST.in` | `tests/test_skills_content.py` |
| R33 Streamable HTTP | done | `project_docs/mcp_http.py` | 只收本機，用服務帳號權杖 |
| R34 MCP Apps 卡片 | partial | `mcp_apps.py`、`mcp_cards/previs_contact_sheet.html` | 只有 3D 預覽接觸表一張；生成台與成片接點兩張等 SPEC_19；只在模擬主機頁測過 |
| R35 ACP 工人加固 | done | `acp_lockdown.py`、`acp_bridge.py` | 用假 ACP 代理測；Claude Code 的 ACP adapter 未實機驗證 |
| R36 模型設定精靈與健康檢查 | done | `console_model_check.py`、`ui/src/agentConsole/ConsoleOpsViews.jsx`（`ModelSetup`） | |
| R37 角色 × 模型矩陣 | done | `console_model_matrix.py`、`ui/src/agentConsole/ConsoleModelMatrix.jsx`、`matrixModel.js` | |
| R38 顯示卡面板 | done | `console_ops.py`、`gpu_arbiter.py`（`status`）、`ConsoleOpsViews.jsx`（`GpuPanel`） | |
| R39 工作佇列與失敗 | done | `console_ops.py`、`ConsoleOpsViews.jsx`（`QueuePanel`）、`execution_governance.py`（`reconcile`） | |
| R40 自動工作總開關 | done | `automation.py`、`ConsoleOpsViews.jsx`（`AutomationSwitch`、`PausedBanner`） | |
| R41 外部代理連線頁 | partial | `ui/src/agentConsole/ConsoleExternalAgents.jsx`、`externalAgentsModel.js`、`project_docs/agent_http.py` | 工具標籤由伺服器的工具登記提供（英文），zh-TW 沒有翻譯 |
| R42 劇組評測集 | partial | `research/crew_eval/`、`scripts/crew_eval.py`、`crew_planning.py`、`crew_continuity.py`（`run_eval_job`） | 分拍、走位、接點各 8 題與評分器完成。2026-10-27 在 4090 上以本機 `qwen3.8:27b` 實跑（`research/crew_eval/reports/spec20-real-2026-10-27-*.json`）：分拍 18.56%（硬性 2/8，軟分 0.79；8 題都由模型回答，失分全在拍數：工作提示詞要每拍約 1–1.5 秒，題目允許的拍數較少，兩邊不一致，未改提示詞）；接點 24.29%（硬性 2/8，軟分 0.58；多報 5 次、漏報 3 次，一題兩次回答都因「修正沒改到文字」被擋下，規則退路什麼都沒報）。走位沒有劇組工作與轉接器（3D 走位是代理迴圈裡的 `propose_previs_ops` 工具），未跑 |
| R43 離線工具清單檢查 | done | `scripts/audit_tool_surface.py`、`tests/fixtures/tool_surface.json`、`tests/test_tool_registry.py` | 含 ACP 可見工具 |
| R44 空白專案實走 | partial | `docs/spec20-verification.json`（`real_acceptance.R44`、`R44_rewalk`）、`docs/research/screenshots/spec20/`（`r44-*`、`r44b-*`） | 2026-10-27 只用介面（無頭 Edge 1440×900）與本機模型走完一集：新專案貼三場劇本 → 劇組拆鏡（採用）→ 前製流程與三道鎖 → 審核描述、出場、分拍、運鏡與 3D 計畫 → 兩鏡的首幀與 LTX-2.5 影片 → 連戲評分 → 匯出 8.1 秒成片，兩個阻擋斷點當時靠變通繞過。2026-10-28 修正後重走（劇組與評分用 OpenRouter 的 DeepSeek V4.1 Flash 1017，`hosted_open`，花費約 0.07 美元）：貼上的編號場景劇本直接成三場、以標題命名（R44-3 關閉）；Keyframe／Cinema Shot 的 Run、Re-shoot Take 與兩鏡的 Run Pipeline 都找到這一欄的預設步驟、送到 FLUX 3 Klein 與 LTX-2.5，管線步驟面板顯示「Default step for this column」（R44-7 關閉；「拍這鏡」按鈕已被 SPEC_19 的鏡頭面板取代）。前製四段 10 秒、24 秒、1.8 分、28 秒（本機模型為 16 秒、1.5 分、6.4 分、1.7 分）。同日修正後再重走前製（`R44_rewalk2`，花費約 0.04 美元，不算圖）：從故事建立的製作只留範本的頁面、欄位與管線，貼上的劇本直接是工作劇本（R44-1、R44-2 關閉）；標準角色提示產生 Nora、Eli 角色卡，同地點的第 1、3 場共用一個場景代碼，場景標題不再重複編號（R44-4、R44-5 關閉）；預覽分配只推薦 ComfyUI 有列出模型的卡片；輪詢在請求失敗後退避重試（R44-6 實測，R44-8 共用同一輪詢工具）。新斷點：前製劇作再拆鏡會把角色提示併回段落、管線畫布一次空白、伺服器偶爾拒絕連線，見收據 |

**未完成的驗收**
- 完整後端測試在最後分片跑了一次（1237 項全過），前端 592 項與建置也通過，見 `docs/spec20-verification.json`；這些測試全部用假的模型端點、假的 ComfyUI 與 GPU 探測、假的 ACP 代理。
- 實機驗收（2026-10-27，收據的 `real_acceptance`）：A14、A15、A17 通過；R42 的分拍與接點分數低（18.56%、24.29%），走位沒跑；R44 走到成片但兩個阻擋斷點（R44-3、R44-7）與數個非阻擋斷點未修。2026-10-28 重走（`real_acceptance.R44_rewalk`）確認 R44-3、R44-7 已修好；R44-1、R44-2、R44-4、R44-5 與預覽分配推薦 MiniMax H3 當時仍未修，同日修好並以 `real_acceptance.R44_rewalk2` 驗證。
- MCP 用 MCP Inspector、Goose＋Ollama、Claude Code 各接一次的檢查沒做；MCP Apps 卡片只在模擬主機頁（無頭 Edge）看過。
- 等 SPEC_19 併入才能補的項目：R19 的生成台入口、R23 的故事 API 自動評分、R18 的質感提案、R34 的生成台與成片接點兩張卡片。
