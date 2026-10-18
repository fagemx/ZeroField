# 執行實際模型與合成工作

## 專家代理的模型設定

各專案可由管理者設定代理 Prompt、具體工具清單與獨立模型。空的模型設定沿用全域設定；明確指定的模型失敗會顯示錯誤，不自動轉送另一個供應商。設定只儲存 `kind/base_url/api_key_env/model/effort`，不儲存實際金鑰。

部署端以 `OPENBENCH_AGENT_KEY_ENVS` 設定允許的憑證環境變數名稱（逗號分隔），例如 `WRITER_API_KEY,SHEET_API_KEY`，實際金鑰仍只在 Worker 環境中。未列入清單的參照會被拒絕。`responses` 與 `codex_cli` 使用既有本機認證，不接受自訂 `base_url/api_key_env`。對話訊息保留當次代理名稱與設定快照，停用或撤權會阻止後續工具呼叫。

OpenBench 的 Head 保存資料、版本、鎖與審核；Worker 在自己的機器執行模型及 FFmpeg。工作台設定 → 手腳 → 註冊，選擇能力與專案，複製只顯示一次的 token。每個 Worker 只註冊已配置的能力，勿讓尚未配置的能力領走任務。

```powershell
$env:OPENBENCH_LIMB_TOKEN = '<工作台發出的 token>'
openbench-worker --config examples/worker.example.json
```

原始碼也可用 `python -m project_assistant.limb_worker --config examples/worker.example.json`。`--once` 領取並處理一項任務後離開。工作流節點可綁定指定 Worker，或由同能力 Worker 共同消化佇列。`examples/worker.py` 保留為協定入門範例；正式執行器是 `limb_worker.py`。

複製範例設定並填上自己的端點、模型與工作流。憑證只放 Worker 環境變數，`api_key_env` 指定變數名稱；Head token 不會傳給模型或橋接服務。供應商回傳的任意 URL 不會直接當成本機檔案或 shell 指令執行。HTTP 不跟隨重新導向，遠端素材由設定的服務原站提供。

## 可用 adapter

## M8 編排佇列與專家 Flow 節點

LLM profile 的結構化最終輸出也檢查畫布修改權限：表格需 `propose_table_edit`，文件需 `propose`，QA／唯讀 profile 不會藉此取得正文或數值寫入權。自訂遠端 LLM profile 也須明確配置相應工具；非 LLM 媒體 adapter 使用管理者綁定的單項產出契約。所有修改仍須核對且受固定範圍／輸出位置限制。

舊 Worker 預設只領取原 Flow 佇列。要接收專家編排任務，在設定檔加入 `"orchestration_enabled": true`；Worker 會輪替嘗試兩個佇列並沿用現有 adapter。註冊的 Worker 仍須具備該專案權限與實際配置的 capability。

管理者可建立 `runtime_kind=remote_limb` 的代理，將 `bound_limb_id` 指向已註冊手腳；Flow 步驟可選此代理，或選內建 `builtin_llm` 專家。代理綁定與 `limb_id` 二選一；代理節點先提出整組提案，不能選 direct。內建 Worker 停用時工作可排隊等待；內建在線狀態以 90 秒內 Worker 心跳判斷，外部手腳沿用原連線判斷，不把已註冊等同已連接。

每次遠端領取取得獨立 `dispatch_handle`、租約及 deadline。續約、輸出、失敗與媒體上傳都要帶回相同憑證；取消或重新派發後的舊上傳會在存入資產前拒絕。完成回覆重送相同內容會返回已保存結果，內容不同則回衝突。

Flow 仍負責節點相依與逐列展開；專家編排只負責該步執行。同一節點不會同時由兩個佇列領取。核對通過後才放行匯總；輸出欄位與輸入來源指紋分別檢查，來源改動會保留提案並要求重新核對。取消 Flow 立即阻止寫入，明確重試會建立新編排批次及 admission。

主控可呼叫 `trigger_flow_run`。若流程含 direct 或可能超出原固定範圍，先出現明確選項與輸出範圍，核准後才啟動；同一決定重送不重複排入。每個編排批次最多綁定一個 Flow，另一個流程需另行交辦。

| adapter | 能力 | 必要設定 |
| --- | --- | --- |
| `openai_compat` | llm | `base_url`（包含 `/v1`）、`model`；可選 `api_key_env`、`json_mode`、`timeout` |
| `acp_stdio` | llm（編排佇列） | 部署者指定 `command` argv；範例 `worker.acp.example.json`；只驗證下述單一 adapter |
| `comfyui` | image_gen / video_gen | `base_url`、ComfyUI API 格式 `workflow` 路徑、`prompt_node`；可選 `prompt_input`、`prompt_column`、`seed_node`、`seed`、`output_node`、`image_node` |
| `http_bridge` | image_gen / video_gen / media_assemble | `base_url`、可選 `api_key_env`；供應商橋接遵守下述 jobs 協定 |
| `openai_speech` | media_assemble | `/v1` `base_url`、`model`、`voice`；可選 `prompt_column`、`api_key_env` |
| `ffmpeg` | media_assemble | 系統有 `ffmpeg` 與 `ffprobe`，或明確設定其可執行檔路徑；可選 `width`、`height`、`fps`、`still_seconds` |

LLM 使用 [Chat Completions 官方協定](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)。可接 OpenAI、OpenRouter、Ollama、vLLM 或提供相容端點的服務。JSON 輸出包含文字、表格列修改或新增列；不執行模型回傳的程式碼。

## ACP stdio 橋接

已驗證 Windows 上的官方 [`@agentclientprotocol/codex-acp` 2.2.2](https://github.com/agentclientprotocol/codex-acp)，使用 [ACP v1](https://agentclientprotocol.com/protocol/v1/initialization)。舊 `@zed-industries/codex-acp` 已移轉，不作為本輪支援版本。測試 adapter 是本機隔離安裝，產品沒有新增 npm 或 Python 執行依賴；實際部署須自行安裝並固定 adapter 版本。

複製 `examples/worker.acp.example.json`，把 command 改為真實執行檔及絕對 script 路徑、model 改為已配置模型。Windows 使用 `node.exe` 加 JS 路徑，不能使用 `.cmd/.bat` 包裝。註冊能力仍用 `llm`；建立 `runtime_kind=acp_stdio` 的專家並綁定該手腳，明確勾選 read/propose 工具。只用於 orchestration 佇列，不能讓舊 Flow 佇列直接啟動 ACP。

模型金鑰只從部署設定的 `api_key_env` 取用，映射為此 adapter 的 `OPENAI_API_KEY`，並透過已公告的 `api-key` 方法認證。其他環境中的模型金鑰、Head Bearer、DB URI、使用者 HOME／CODEX_HOME 不繼承。每回合使用新的 HOME／CODEX_HOME 與暫存 cwd，不沿用使用者 Codex 登入。

橋接依序 initialize → authenticate（有明確金鑰時）→ session/new（掛載本次 MCP）→ session/prompt。MCP 子程序只持有單回合 loopback token；Head 憑證只留在 Worker parent。工具清單取目前權限與派發快照交集，每次工具呼叫在 Head 重查租約、角色、成員與固定範圍。問題 Gate 提交後終止此回合，回答後以新 admission 續跑並帶回 continuation。只顯示 agent_message_chunk，忽略 thought；不把 stderr／原始協定錯誤傳給使用者。

ACP 的檔案、終端、原生權限要求一律拒絕；Codex adapter 設為 read-only 並關閉既有禁止功能。逾時或 Worker 發現 lease loss 時中止子程序樹，Windows 使用 Job Object，POSIX 使用獨立 process group。Head 取消立即阻止工具和輸出；正在等待模型的遠端程序在下一次心跳察覺，正常租約心跳間隔為 40 秒。阻塞 stdin 也受獨立 watchdog 限制。

這些是工具與憑證邊界，**不是任意可執行檔的 OS 沙箱**。command 是可信部署設定，不能來自 Prompt 或 HTTP 工作內容；要執行不可信 adapter，需另用受限帳號／容器。其他 ACP CLI 尚未驗證。實際官方 adapter smoke 使用本機合成 Responses SSE，包含 MCP 讀頁、提案、介面核對；未呼叫外部付費模型。

ComfyUI 使用 [官方 API 範例](https://github.com/Comfy-Org/ComfyUI/blob/master/script_examples/websockets_api_example.py) 的 prompt/history/view 路徑。在 ComfyUI 匯出 API JSON，保持模型與 custom nodes 安裝在 Worker 所連的伺服器。`image_node` 指向 LoadImage 節點時，上游專案圖片會先上傳，再綁定其輸入；因此可跑圖生圖或圖生影片。`output_node` 指定儲存結果節點，支援 images、videos、gifs、audio 輸出陣列。工作流本身不含虛構的模型名稱或帳戶金鑰。

FFmpeg 依穩定分鏡列順序合成，優先取每列最新影片（沒有影片可用圖片定格），接上同列音訊；沒有配音時保留原影片音訊，沒有音訊時補靜音軌。提供配音時以配音替代原片音軌，長配音裁切至影片長度、短配音補靜音。所有片段先統一解析度、影格率與音訊格式再串接。輸出為 H.264/AAC MP4，媒體上限 64 MB；較長影片請降低解析度或拆成集數。不會把任何 Prompt 當成 FFmpeg 參數。

若要 TTS 與圖片平行：建立兩個 `scope=rows` 節點，分別綁定 TTS Worker 和生圖 Worker，以同一分鏡表為 `row_source`；把影片與配音節點連到 `scope=aggregate` 的合成節點即可。每個節點可要求 ProposalCard 審核，通過後下游才繼續。

## 媒體供應商 bridge 協定

不同供應商（例如即夢、Kling、Veo、Seedance）的帳戶、模型與任務 API 由部署者的 bridge 處理。OpenBench 提供可直接部署的通用 client；不假設各供應商有同一套 API。

1. `POST /jobs`：JSON `{task_id, capability, input, assets}`。`input` 包含節點指令、結構化來源列與上游結果；`assets` 是 `{url,content_type,base64}` 陣列，僅含此 Worker 有權讀取的專案素材。
2. 同步回應 `{status:"succeeded",output:{media_url:"/media/result.mp4"}}`，或非同步 `{id:"job-id",status:"queued"}`。
3. `GET /jobs/<id>`：回應 `{id,status:"running"}` 直到 `succeeded` 或 `failed`。完成時提供同源 `media_url`；文字工作也可直接給 `output:{text:"..."}`。
4. 相同 `task_id` 應去重，避免租約重領產生重複計費。Head 續約失敗後 Worker 停止輪詢與寫回；已送到供應商的工作仍依供應商取消政策處理。

429／408／5xx 與暫時網路錯誤可重試，其他失敗保留錯誤並等待人工重試。Worker 續約循環與執行工作分開；本地 FFmpeg 在租約喪失時終止。超時、來源權限、無輸出與超大檔案都會回報失敗，不填入假的媒體結果。

## 驗證

`tests/test_limb_worker.py` 使用隔離 HTTP fixture 驗證 ComfyUI、LLM 與 bridge 實際請求／回應流程，並使用系統 FFmpeg 真正輸出雙鏡頭 MP4、以 ffprobe 檢查長度／解析度／音軌。fixture 不代表外部模型生圖品質驗證；接入自己的模型後應再跑專案小樣。
