# 執行實際模型與合成工作

OpenBench 的 Head 保存資料、版本、鎖與審核；Worker 在自己的機器執行模型及 FFmpeg。工作台設定 → 手腳 → 註冊，選擇能力與專案，複製只顯示一次的 token。每個 Worker 只註冊已配置的能力，勿讓尚未配置的能力領走任務。

```powershell
$env:OPENBENCH_LIMB_TOKEN = '<工作台發出的 token>'
openbench-worker --config examples/worker.example.json
```

原始碼也可用 `python -m project_assistant.limb_worker --config examples/worker.example.json`。`--once` 領取並處理一項任務後離開。工作流節點可綁定指定 Worker，或由同能力 Worker 共同消化佇列。`examples/worker.py` 保留為協定入門範例；正式執行器是 `limb_worker.py`。

複製範例設定並填上自己的端點、模型與工作流。憑證只放 Worker 環境變數，`api_key_env` 指定變數名稱；Head token 不會傳給模型或橋接服務。供應商回傳的任意 URL 不會直接當成本機檔案或 shell 指令執行。HTTP 不跟隨重新導向，遠端素材由設定的服務原站提供。

## 可用 adapter

| adapter | 能力 | 必要設定 |
| --- | --- | --- |
| `openai_compat` | llm | `base_url`（包含 `/v1`）、`model`；可選 `api_key_env`、`json_mode`、`timeout` |
| `comfyui` | image_gen / video_gen | `base_url`、ComfyUI API 格式 `workflow` 路徑、`prompt_node`；可選 `prompt_input`、`prompt_column`、`seed_node`、`seed`、`output_node`、`image_node` |
| `http_bridge` | image_gen / video_gen / media_assemble | `base_url`、可選 `api_key_env`；供應商橋接遵守下述 jobs 協定 |
| `openai_speech` | media_assemble | `/v1` `base_url`、`model`、`voice`；可選 `prompt_column`、`api_key_env` |
| `ffmpeg` | media_assemble | 系統有 `ffmpeg` 與 `ffprobe`，或明確設定其可執行檔路徑；可選 `width`、`height`、`fps`、`still_seconds` |

LLM 使用 [Chat Completions 官方協定](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)。可接 OpenAI、OpenRouter、Ollama、vLLM 或提供相容端點的服務。JSON 輸出包含文字、表格列修改或新增列；不執行模型回傳的程式碼。

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
