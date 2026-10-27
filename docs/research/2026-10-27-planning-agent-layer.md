# 規劃代理層研究備忘（2026-10-27）

**問題。** ZeroField 的規格（SPEC_13～SPEC_19 與重設計畫布）在很多步驟假設「有代理在判斷」：改編故事、寫角色描述、拆鏡、寫分拍提示詞、選鏡頭、在 3D 排位、檢查接點。開發時這些判斷由編碼代理和腳本代做；產品執行時沒有對應的能力，使用者一用就斷。這份備忘回答寫 SPEC_20 之前要先定的四件事：架構（對內／對外）、中控台、SDK、模型供應商。

**範圍與方法。**
- 程式盤點：執行時的代理骨架、判斷步驟（J1–J14）、3D 預演流程。
- 桌面研究：Agent SDK 與互通標準（MCP、MCP Apps、ACP、Skills）、本機與託管模型。
- 競品：Higgsfield MCP。只做唯讀：讀了工作流目錄、多場景旁白影片手冊、3D Jutsu 手冊；沒有呼叫生成工具，沒有花點數。
- 參考案例：使用者前公司專案 ad_growth_data 的「主管產能判斷協作台」，只看 ACP／MCP 架構，不看業務資料。
- 標「✓」的是我親自在程式或原始網頁核對過；其餘來自研究代理的報告，未逐條核對（見 §10）。

## 0. 結論

1. **缺的不是迴圈，是「領域工具＋觸發點＋結構化計畫」。** 現有的工具呼叫迴圈、派工、提案閘門都堪用。缺的是讓代理讀得到故事、鏡頭與 3D 計畫，並寫得出提案的工具，以及介面上「什麼時候叫誰做」。
2. **對外用 MCP，對內用自家迴圈；兩邊共用同一套工具層。**
   - 對外：ZeroField 開一個 MCP 伺服器（工具＋流程手冊，之後加 MCP Apps 卡片），讓 Claude Code、Codex、Goose 這類外部代理接進來。
   - 對內：劇組跑在自家迴圈上，預設接本機開放權重模型，使用者不必自帶代理。
   - ACP 只當選配：把 Codex／Claude Code 當工人，沿用判斷台的鎖權限做法。
   - 安全放在工具層，不放在手冊：寫入一律成提案，代理沒照手冊走也越不了權。
3. **不換框架。** 保留自家迴圈與 PostgreSQL 提案閘門；重做供應商層、工具登記與情境組裝。PydanticAI 是唯一值得之後再評估的框架。
4. **預設模型：本機 Ollama＋`qwen3.8:27b`，規劃與評分共用一個模型。** 沒有顯示卡的人用 OpenRouter 上的同一個模型；閉源模型只當明確開啟的混合選項。
5. **三個要先修的問題**（§2.3）：模型呼叫失敗會把劇組鎖死；有一條路徑會打 chatgpt.com 內部端點；最後一輪送出 Ollama 不支援的 `tool_choice`。
6. **參賽截止是 10/30 太平洋時間 9:00（台灣 10/31 0:00）✓。** SPEC_20 建議分兩段：截止前只做低風險的 P0，其餘截止後做（§8）。

## 1. 規劃假設 vs 執行時實際

全新安裝時：
- 預設供應商指向 api.openai.com、模型 gpt-4.1、沒有金鑰，第一次呼叫就失敗 ✓（[providers.py:35-43](../../project_assistant/providers.py)）。
- README 的啟動指令帶 `--no-worker`，劇組對話與派工根本不會跑 ✓（[README.md:56](../../README.md)）。
- 管線工人只註冊給展示專案 ✓（[run_studio.py:524](../../run_studio.py)），使用者自己開的專案沒有。
- 劇組「在線」看的是背景程式心跳，不是模型能不能用（`orchestration_flow.profile_connected`）。

| 編號 | 判斷步驟 | 今天誰做 | 寫入路徑 | 審核介面 |
|---|---|---|---|---|
| J1 | 點子 → 劇本 | 固定三幕範本 | script-adaptations（直接覆寫）；寫作預覽 `adaptation` | AuthoringWorkspace、StartFromStory |
| J2 | 小說 → 劇本 | 依段落切 | 同上 | 同上 |
| J3 | 角色／場景／道具描述 | 只抓名字後的括號 | asset-extractions、PATCH /assets | StoryWorld、AssetEditor |
| J4 | 造型 | `@CAST:key` 範本或手動 | POST /assets/{id}/variants | StoryWorld |
| J5 | 出場 | 名字有出現才綁，「他」綁不到 | ShotBindings；PUT /shots/{id}/assets | ShotBindings |
| J6 | 拆鏡 | 依段落切，每鏡固定 4 秒 | storyboards、shot-rebuilds；寫作預覽 `impact` | BreakdownDialog、ShotProposals |
| J7 | 分拍提示詞 | **沒有**：原句加標籤；Phase 2 的分拍提示詞是手寫的 | PATCH /shots/{id} | ShotProposals |
| J8 | 鏡頭與運鏡 | 關鍵字查表 | PATCH 文字欄 | ShotProposals、3D 鬼影攝影機 |
| J9 | 3D 走位 | 預設人偶站在原點，其餘手拖 | **沒有後端寫入**：草稿在瀏覽器，計畫藏在預演影片檔 | PrevisStage |
| J10 | 3D 與文字欄同步 | 只有文字 → 3D 單向 | 只能改文字欄 | — |
| J11 | 單支評分 | ✓ 真的跑模型（qa_critic 視覺模型） | take_grade 紀錄（只供參考） | TakeGrades |
| J12 | 接點檢查 | 未實作（SPEC_19 R17） | — | — |
| J13 | 建議 → 重拍 | 一鍵改提示詞並重生，不經審核 | 直接寫入 | TakeGrades |
| J14 | 質感設定編譯 | 未實作（SPEC_19 §4.3） | — | — |

`story_adaptation.py` 第一行就寫著不呼叫模型 ✓；建立分鏡回傳 `"engine": "deterministic"` ✓（[story_openapi.py:1413](../../project_docs/story_openapi.py)）。

3D 這一塊斷得最徹底：
- 一鏡的完整計畫（站位、攝影機關鍵幀、焦段）只存在瀏覽器暫存 ✓（[PrevisStage.jsx:29-31](../../ui/src/previs/PrevisStage.jsx)）和算好的預演 WebM 檔標題裡；後端只有 6 個列舉欄位的種子。
- 沒有任何代理工具能改 3D。預演在瀏覽器裡算圖，代理要「算一張來看」得另外有無頭算圖器。
- 3D 改了焦段或運鏡，不會回寫文字欄，提示詞會和 3D 對不上。

## 2. 現有骨架盤點

### 2.1 可以留的
- 派工協調：run／task／dispatch／gate、租約、冪等日誌、依賴推進。
- 工具授權與決策閘門。閘門核准後的 `tool_action` 是寫入非表格目標最乾淨的路。
- 中控台的資料模型（`agent_*` 表、版本化資源）與排程部署。
- 遠端工人（limb）協定：持久 Bearer token、限定專案與能力、走同一套閘門與提案。這是「自帶代理」最接近的底。
- `acp_bridge`：已能用 ACP 包 Codex／Claude Code，不給檔案與終端權限。

### 2.2 要改或重做的
| 元件 | 判定 | 原因 |
|---|---|---|
| 供應商層（providers／agent_runtime） | 重做 | 沒有情境長度管理（不設 `num_ctx`，訊息只增不減）；沒有模型能力旗標（工具、JSON、視覺）；失敗會留下不確定預留 |
| 工具登記 | 改成宣告式 | 加一個工具要改約 6 個檔案；只有 studio 工具有參數驗證 |
| 情境組裝 | 重做 | 代理只能翻表格文字（每頁約 5800 字）；沒有讀場次、鏡頭 meta、3D 計畫、造型、鄰鏡的工具 |
| 提案 | 改 | 以表格為中心，沒有鏡頭提示詞、攝影機、3D 計畫、描述這類型別；新增型別要動 6 處 |
| 對話佇列 | 併入派工 | 兩條佇列重複；對話不能取消 |
| 治理 | 改 | 鎖死問題（§2.3）；商用視覺一律拒絕；上限按「每一輪」算 |
| take_grader、快速建立助手 | 納入治理 | 兩者都繞過治理直接呼叫模型 |
| GPU 鎖 | 重做成仲裁器 | 只在同一個程序內有效（[take_grader.py:36](../../project_assistant/take_grader.py)），代理的模型呼叫完全不管它；24GB 上會互搶 |
| 中控台介面 | 重做 | 多處是原始 JSON 編輯；沒有就緒檢查、顯示卡、佇列、失敗原因 |
| 劇組在線狀態 | 重做 | 心跳不等於能做事 |
| model_client（chatgpt.com） | 移出產品 | 見 §2.3 |

### 2.3 先修的三個問題（程式位置已核對 ✓，尚未用測試重現）
1. **模型呼叫失敗會把劇組鎖死。**
   - 每一輪模型呼叫結束都會執行 `admission.after({}, 'unknown')`（[providers.py:177-179](../../project_assistant/providers.py)）。失敗的那一輪（連不上、401、429、逾時）預留會停在 `uncertain`（[execution_governance.py:183-188](../../project_assistant/execution_governance.py)）。
   - `uncertain` 會計入每個角色的並行上限（預設 2）和專案的模型並行上限（預設 4）（[execution_governance.py:113-118](../../project_assistant/execution_governance.py)），而程式裡沒有任何地方會清掉它。
   - 結果：同一個角色失敗兩次就被鎖住，專案累積四次就全部停擺，畫面只說「已達並行上限」。這原本是防止付費呼叫重複扣款的設計，但本機模型連不上也會觸發。
2. **有一條路徑會打 ChatGPT 的內部端點。**
   - [model_client.py:19](../../project_assistant/model_client.py) 連 `chatgpt.com/backend-api/codex/responses`，用開發者電腦上 `~/.codex/auth.json` 的登入憑證（:72-87），並自訂標頭與 User-Agent 繞過 Cloudflare（:145-148）。
   - 代理執行（[agent_runtime.py:169](../../project_assistant/agent_runtime.py)）與成果評分（[outcome_grader.py:69](../../project_assistant/outcome_grader.py)）都會走到。
   - 程式要開源公開、又要投 Open Weights Only，這條應該移出產品路徑。
3. **最後一輪送出 `tool_choice: "none"`**（[providers.py:104](../../project_assistant/providers.py)），但 Ollama 的 OpenAI 相容介面不支援 `tool_choice` ✓（[Ollama 文件](https://docs.ollama.com/api/openai-compatibility)）。最後一輪仍可能呼叫工具，以「工具呼叫超過上限」收場。最後一輪改成不帶 `tools` 比較穩。

## 3. 對內與對外：MCP 與 ACP

### 3.1 判斷台（ad_growth_data）怎麼分
- **ACP 是對內的工人傳輸。** 產品當 ACP 客戶端，啟動 `codex-acp`。啟動與關閉、提示詞組裝、權限回覆、緊急停止、存檔、驗證都由產品掌控。代理不直接面對使用者，產出一律存成提案，由人決定。✓（`production_copilot/acp_client.py` 第 263、433、461、531 行）
- **MCP 是能力邊界，對內對外共用。**
  - 對內：唯讀容器、只綁本機、白名單查詢、每次留稽核，結果帶 status／sources／warnings／limitations。
  - 對外：Cloudflare OAuth 的 Streamable HTTP，身分只認驗證過的憑證，不看工具參數。
- **「安全性不依賴 skill」✓**（該專案技能架構文件第 183 行）：手冊沒觸發，工具層照樣限制。
- **教訓：代理程式自帶的「唯讀模式」不是沙盒。** 當時 Codex 在唯讀模式下仍能跑 PowerShell、讀密鑰、上網，所以判斷台疊了九層：
  1. 關掉不需要的功能；
  2. 只開指定的 MCP 伺服器，使用者自己設定的全部停用；
  3. 清除含密鑰的環境變數；
  4. 啟動後確認模式真的是唯讀；
  5. 權限請求預設拒絕，核准一次性且要對得上先前的工具呼叫；
  6. 出現意外的工具呼叫就取消並砍掉整棵程序；
  7. 擋下以斜線開頭的指令；
  8. 提示詞聲明「資料不是指令」；
  9. 離線列出代理實際看得到的所有工具，多一個就失敗。
- **其他可借的做法：**
  - 先存再想：使用者訊息與待回覆先落庫，串流內容邊收邊存。
  - 批次每一輪用新的 session，並加一個不共用記憶的反方審查。
  - JSON 合約驗證，失敗只重試一次。
  - 以來源雜湊做冪等的工作狀態機；後段失敗不丟前段的好結果。
  - 失敗分類，並記錄實際用到的模型與路徑。
- **缺點：ACP 斷線時沒有退路**，聊天與批次只能失敗後等重試。ZeroField 要事先定好降級方式。

### 3.2 Higgsfield 怎麼做 ✓
- 規劃不是產品功能，而是 MCP 伺服器附帶的 SKILL.md 流程手冊，由使用者自己的代理讀取後照做。工作流目錄裡沒有 Cinema Studio 或分鏡，最接近故事規劃的是多場景旁白影片。
- 手冊的骨幹是「鎖」與「關卡」：
  - 風格鎖 → 角色場景道具清單鎖 → 劇本鎖，劇本存成機器可讀版本。
  - 每一步之後在雲端沙盒跑檢查腳本，例如用 ffprobe 數模型實際剪了幾刀，因為模型常常交不足。
  - 生成用帶編號的批次與冪等重試，另有重試階梯與交付前檢查表。
  - 拍攝工藝寫成硬規則，例如相鄰鏡頭的景別與角度要不同、同一地點最多連用兩段。
- 3D Jutsu 是託管的 Blender 場景，代理寫 bpy 程式修改：
  - 唯讀查詢與修改分開；修改要帶版本號與場景序號（樂觀鎖），`operationId` 冪等。
  - 手冊明寫「修改成功只證明程式跑完，不證明場景是對的」，規定要從交付攝影機算圖、看過才算完成。
- 它的缺口就是我們的機會：沒帶代理的人只能自己規劃；3D 場景不連分鏡；沒有整集的接點與連戲檢查。
- 業界同路：研究報告指出 Runway、Comfy、Blender 也都推出了 MCP（未逐一核對）。

### 3.3 建議的分工
```
對外  外部代理（Claude Code／Desktop、Codex、Goose＋Ollama）
        │  MCP（先 stdio，之後 Streamable HTTP）＋流程手冊＋之後的 MCP Apps 卡片
        ▼
     ┌──────────────── ZeroField 工具層（同一套） ────────────────┐
     │ 讀：故事、場次、鏡頭 meta、3D 計畫、角色與造型、鄰鏡、Take、評分 │
     │ 寫：一律產生提案（描述、出場、分拍提示詞、攝影機、3D 計畫、質感） │
     │ 生成：帶冪等 requestId 與費用估計，走既有政策                     │
     │ 驗證：算預演、抽格、評分；結果帶信封並留稽核                       │
     └─────────────────────────────────────────────────┘
        ▲
對內  劇組（自家迴圈＋本機模型，預設）；選配：ACP 把 Codex／Claude Code 當工人
```
- 外部代理的身分：每個代理一個服務帳號（`agent_service_account` 表已存在但沒用），權杖限定專案、工具、寫入模式，並有到期時間。
- 現有的公開 REST API（`/aivideo/open/v1`）是產品 API，不適合當代理介面：沒有範圍限制、直接寫入、開發模式可以冒名。

## 4. 中控台要補什麼
現有 12 頁（儀表板、API 金鑰、Playground、技能、快速建立、代理、工作階段、部署、環境、記憶、用量、花費上限），多半是原始 JSON 編輯。要補：
1. **模型設定精靈與真正的健康檢查。** 現在的「測試連線」只對 `/models` 發 GET。要實際試一次對話、一次工具呼叫、一次 JSON schema、一次看圖，並確認模型名稱存在。
2. **角色 × 模型矩陣。** 從 `/models` 清單選，取代四個自由文字欄。
3. **顯示卡面板。** 剩餘 VRAM、ComfyUI 佇列、目前載入的模型。
4. **全專案工作佇列與失敗原因。** 包含對話失敗、工人失敗、不確定預留。
5. **自動工作總開關。** 目前只能用 `--no-worker` 或環境變數整個關掉。
6. **「劇組為什麼不能做事」。** 沒有模型、金鑰錯、網路政策擋、缺價格設定、被鎖死、工人沒開，逐條說明，並給一鍵修正的入口。
7. **外部代理連線頁。** 發權杖、設範圍、看稽核。

## 5. SDK 與互通標準

| 框架 | 授權 | 依賴 | 接 Ollama／vLLM | 中斷後存 DB 再恢復 | 備註 |
|---|---|---|---|---|---|
| PydanticAI 2.x | MIT | 最輕 | ✔ | ✔（deferred tools） | 唯一值得之後評估 |
| OpenAI Agents SDK | MIT | 中 | 可，但 Responses 專屬欄位會被靜默丟棄 | ✔ | 追蹤預設上傳 OpenAI |
| Claude Agent SDK | MIT（受 Anthropic 條款約束） | 內嵌 CLI | ✘ 只支援 Claude | 部分 | 強鎖廠商 |
| LangGraph | MIT | 中 | 部分 | ✔ 最成熟 | 與我們的 PG 提案表重複 |
| Google ADK、LlamaIndex | Apache-2.0／MIT | 重 | 部分 | — | 依賴太重 |

（版本與細節來自研究報告，未逐條核對。）

**建議：保留自家迴圈（選項 A）；之後再把官方 `mcp` 套件當選配擴充（選項 C）；換 PydanticAI（選項 B）暫緩。**
- 我們存在 PostgreSQL 的提案與決策閘門，本身就是持久化的「人在迴圈」，換框架多半是重複造輪。
- 本機模型唯一共通的介面是 Chat Completions，框架在這一層幫不上太多，卻會帶來依賴與供應鏈風險。研究報告指出 2026-03 LiteLLM 的 PyPI 套件曾被植入竊密程式，而多個框架的非 OpenAI 路徑會經過它（未親自核對）。

**互通標準：**
- **MCP 現行規格是 2026-07-28 ✓。** 取消初始化握手，每個請求在 `_meta` 帶協定版本，新增 `server/discover`，並保留與 2025-11-25 以前握手式版本的相容方式（[版本說明](https://modelcontextprotocol.io/specification/versioning)）。我們的 `mcp_stdio.py` 宣告 2025-06-18，它只是內部管線，不是對外介面。
- **MCP Apps ✓。** MCP 第一個官方擴充，2026-01-26 推出，建立在 MCP-UI 與 OpenAI Apps SDK 之上。推出時支援 Claude（網頁與桌面）、Goose、VS Code Insiders，ChatGPT 同週開始推送。工具用 `_meta.ui.resourceUri` 指向 `ui://` 資源（[官方部落格](https://blog.modelcontextprotocol.io/posts/2026-01-26-mcp-apps/)）。研究報告另指出：介面跑在沙盒 iframe 裡、未宣告的外連一律封鎖、Claude Code 不顯示 MCP Apps、ChatGPT 需要公網 HTTPS（這幾點未親自核對）。
- **從 MCP 提供流程手冊，有三條路：** 官方 Skills 擴充；用工具回傳 SKILL.md（Higgsfield 正式產品就這樣做 ✓）；MCP prompts。SKILL.md 資料夾已是跨廠商慣例，Claude Code、Codex、Gemini CLI、Cursor、Goose 等都支援。
- **ACP：** v1 穩定，適合對內驅動代理程式。A2A 對單機創作工具不需要投入。

## 6. 供應商與模型

### 6.1 參賽規則 ✓（[comfy.org/open-source-higgsfield](https://comfy.org/open-source-higgsfield)）
- 只有 Open Weights Only 組禁止閉源：“No partner nodes or closed-source APIs, open-weights models only.” 其他組可以用合作夥伴模型。
- 頁面完全沒提到 LLM、VLM 或代理。最保險的讀法是：投 Open Weights Only 時，規劃與評分模型也用開放權重。託管的開放權重推論（例如 OpenRouter）算不算「閉源 API」並不明確，要問主辦。
- 程式要以開源授權公開並附安裝說明；截止 10/30 9am PT。
- AGENTS.md 寫明目標是 Best Overall 與 Open Weights Only 兩組。

### 6.2 本機伺服器（Windows 11＋4090）
- **Ollama：** 原生 Windows；支援 tools、`response_format`、`reasoning_effort`、base64 圖片；**不支援 `tool_choice` 與圖片網址 ✓**。可用 `keep_alive:0` 卸載。研究報告指出需要 0.31.2 以上版本，才修好 Qwen 系列在關閉思考時忽略 `format` 的問題。
- **llama.cpp server：** 原生；用文法約束 JSON；有路由模式可卸載模型。
- **vLLM／SGLang：** 工具呼叫最完整，但在 Windows 只能走 WSL2／Docker，而且會預先佔走大部分 VRAM，不適合與 ComfyUI 同卡。
- **LM Studio：** 閉源應用程式，不建議當預設。

### 6.3 模型建議（研究報告，未逐條核對）
| 角色 | 首選 | 備選 |
|---|---|---|
| 規劃（工具＋JSON） | Qwen3.8-27B（Apache-2.0，Ollama Q4 約 18GB，可看圖與影片） | Qwen3.6-27B、Gemma 4 31B、GLM-4.7-Flash（只有文字） |
| 視覺評分 | Qwen3.8-27B（同一個模型，一次載入兩種用途） | Qwen3.6-27B、Gemma 4、MiniCPM-V 4.5 |
| 小型常駐 | Qwen3.5-4B（約 3.3GB）、Qwen3.5-9B（約 6.6GB） | Gemma 4 12B |

- 不建議：Llama 4（授權有限制）、Qwen 的閉源託管版、超過 24GB 的大模型。
- 我們只實測過 Qwen3.8-27B 評分（Phase 2）；它的規劃與工具呼叫能力還沒測。
- 開發環境用的 `qwen3.8:27b-16k` 是本機 Modelfile（`num_ctx 16384`），不是官方標籤。
- Qwen3.8 預設的思考強度很高；要輸出 JSON 時建議調到 low 或 medium。
- 公開的工具呼叫基準多半過時，**需要自建劇組評測集**，素材用正面、高張力的難例。

### 6.4 建議配置
- **預設（本機）：**
  - Ollama＋`qwen3.8:27b`，規劃兼評分。
  - Modelfile 固定 `num_ctx` 在 16k–32k。
  - 用 `response_format` 的 JSON schema，再加程式端驗證。
  - 沿用「ComfyUI /free → 等 VRAM → 呼叫 → keep_alive:0」，但改成按階段批次：規劃全部做完再算圖，同一鏡的 Take 一次評完。
  - 研究報告指出 ComfyUI 0.43 新增 `--vram-headroom`，可替其他程式預留 VRAM（未核對）。
- **沒有顯示卡：** OpenRouter 的 `qwen/qwen3.8-27b`（同模型、同提示詞），開啟零保留（ZDR）。一次典型的規劃呼叫（輸入 8k、輸出 2k）約 0.005 美元（研究報告估算）。
- **閉源：** 只當明確開啟的混合選項，不能用在 Open Weights Only 的展示路徑。

## 7. 3D 規劃的做法
- **用電影語彙的結構化操作，不讓本機模型寫程式。** 例如「把 Kael 放在控制台左前方 1 公尺、面向窗」「中景、低角度、35mm、從 K1 推到 K2」。由確定性求解器換成既有的計畫格式（`plan.js` 的 mark、cast、keys、lens 等），結果寫成提案。程式碼執行只留給明確開啟、在沙盒裡跑的前沿模型。
- **借用 3D Jutsu 的護欄：** 唯讀查詢與修改分開；修改帶版本號（樂觀鎖）與冪等的 operationId；**修改後一定要算圖、看過才算完成**，由視覺模型或人驗證。
- **前置條件：**
  1. 3D 計畫存到後端：`meta_<shotId>` 存完整計畫並帶版本號，不再只放在瀏覽器和影片檔裡。
  2. 3D 與文字欄雙向同步：`describePlan` 已經存在，只缺回寫；或讓提示詞編譯直接讀計畫。
  3. 無頭算圖器：預演現在在瀏覽器裡算；代理要驗證，就得有伺服器端算圖（同一套前端程式跑在無頭 Edge 上，或用 Blender）。
  4. 計畫要能綁 `@CAST`：現在 `cast` 只有站位，沒有角色代碼。

## 8. SPEC_20 範圍建議

**截止前（P0：低風險，直接影響參賽）**
1. 修鎖死：本機端點或連線被拒的失敗視為已終止，釋放預留；付費端點維持原設計，但加上到期與中控台的處理入口。附測試。
2. 預設供應商改為本機 Ollama，並在劇組看板顯示「為什麼不能做事」。
3. 把 chatgpt.com 路徑移出產品：刪除，或改成開發專用旗標。
4. Ollama 相容：最後一輪不帶 `tools`。
5. README 的代理說明據實：哪些功能接上本機模型真的會跑。
6. （有時間才做）一個真的會跑的規劃工作：分拍提示詞（J7）產生提案。Phase 2 的經驗顯示，這是品質槓桿最大的一步。

**截止後（P1／P2）**
- **P1：**
  - 宣告式工具登記與型別化提案。
  - 情境工具：讀故事、場次、鏡頭 meta、3D 計畫、造型、鄰鏡。
  - 3D 計畫後端化＋結構化操作＋無頭算圖。
  - 對外的 stdio MCP 伺服器，加上 repo 內的 `skills/` 流程手冊。
  - 中控台重做（§4）與 GPU 仲裁器。
  - 劇組前製流程：編劇 → 美術 → 攝影指導 → 連戲，每一步產生提案、就地審核。
- **P2：**
  - Streamable HTTP＋服務帳號權杖。
  - MCP Apps 卡片：生成台、成片視窗、3D 片場。
  - ACP 工人選配，沿用判斷台的鎖權限做法。
  - 接點檢查（SPEC_19 R17）。

**驗收方式**
- 空白專案＋只用介面＋本機模型走完一集，不准開發代理插手，記錄每個斷點。用 DB 副本，在 GPU 空檔時做。
- MCP：用 MCP Inspector、Goose＋Ollama、Claude Code 各接一次。
- 離線工具清單檢查：列出代理實際看得到的所有工具，多出來的就算失敗。
- 自建劇組評測集：難例鏡頭的分拍提示詞、走位、接點各若干題。

## 9. 待決問題
1. 是否以 Open Weights Only 為準，讓規劃與評分模型一律用開放權重？要不要向主辦確認託管的開放權重算不算閉源 API？
2. 截止前要不要動程式？建議只做 §8 的 P0 第 1–5 項。
3. chatgpt.com 路徑：刪除，還是保留成開發專用？
4. 3D：是否同意用結構化操作＋求解器，不開放任意程式碼執行？
5. 對外 MCP 先做 stdio（Claude Code／Desktop、Codex、Goose 都能接），之後再做 HTTP？

## 10. 查證狀態
- **親自核對 ✓：** §1 的供應商預設、`--no-worker`、工人只註冊給展示專案、`story_adaptation` 不呼叫模型、3D 草稿存在瀏覽器；§2.3 三個問題的程式位置；判斷台 ACP 的鎖權限關鍵行；Higgsfield 兩份手冊的內容；參賽規則；MCP 現行版本；MCP Apps 的推出資訊；Ollama 不支援 `tool_choice`。
- **未逐條核對：** 框架版本與比較、模型分數與價格、ComfyUI `--vram-headroom`、LiteLLM 事件、Runway／Comfy／Blender 的 MCP、Claude Code 不顯示 MCP Apps。
- **研究筆記**（含來源網址）留在本次工作階段的暫存資料夾，沒有放進 repo。
