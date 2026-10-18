# M8 多代理編排實作與驗證紀錄

依據：[執行計畫](superpowers/plans/2026-10-18-agent-orchestration.md)、[規格](AGENT_ORCHESTRATION_SPEC.md)。使用者於 2026-10-18 授權依序完成全部階段，包含 ACP 橋接。

## 執行環境與基線

- 起點 `72670290a9c60737478f2becc89c77110948a031`；功能分支 `codex/agent-orchestration`，工作區 `C:/ai_project/OpenBench`。
- 專案內隔離 Python 3.12.14：`.superpowers/m8-venv`；PostgreSQL 16：`.superpowers/m8-pg-ready`，僅 `127.0.0.1:55583/openbench_m8_test`。
- 基線後端：116 項、0 失敗、0 跳過，104.490 秒；前端：63 項、0 失敗、0 跳過。
- UI 驗收服務 `http://127.0.0.1:3038/projects/m8-acceptance/` 使用此專用測試庫，停用背景模型 Worker。測試／操作資料均為合成資料。

## 階段進度

| 階段 | 狀態 | 已取得證據 |
| --- | --- | --- |
| M8-A 角色註冊／路由 | 已實作及本機驗證 | A1 focused 5 項；A2 最終後端回歸 130 項；A3 前端 67 項與 build 通過 |
| M8-B 編排／租約／工作流 | 已實作及本機驗證 | 後端 190 項、0 失敗／跳過；前端 68 項與 build 通過；HTTP 問題→續跑→提案→套用→結案已走通 |
| M8-C 競速／集中看板 | 已實作及本機驗證 | 後端 214 項、前端 75 項、0 失敗／跳過及 build 通過；實際 UI 文字／圖片競案與來源衝突已走通 |
| M8-D ACP 橋接 | 已實作及本機驗證 | ACP 契約 9 項；真實官方 adapter 2.2.2 經 MCP 讀頁→提案→介面確認寫回；完整後端 226 項通過 |
| 最終回歸／封裝／審查 | 已完成獨立審查與單次修正批次 | 後端 235、前端 76、build、wheel、checkout 外 MCP 通過；7 項 Important 均已修復 |

## M8-A 操作證據

1280×720，本機合成專案 `m8-acceptance`，Alex 管理者：

1. 用空白範本建立專案；開啟助理後看到四個角色，中文顯示名稱及獨立代號均可選。
2. 輸入 `@doc_writer` 時選擇器自動對應寫作代理；送出後該代理排隊，仍可改選 `sheet_ops` 並送出另一項工作。切到 QA 後可繼續編寫草稿。[兩角色排隊](research/screenshots/m8-a-personas.png)。
3. 用本機 HTTP fixture 經正式 `store.claim_next → worker.execute → agent_runtime` 完成兩則回覆；畫面顯示各自名稱、實際模型 `local-fixture` 及合成回覆。這不是付費模型品質驗證。[完成回覆與草稿](research/screenshots/m8-a-personas-done.png)。
4. 管理設定載入寫作代理的代號、Prompt 與已勾選工具；無效模型 JSON 在原處顯示錯誤並保留草稿，Escape 關閉後焦點回「成員與設定」。[錯誤保留](research/screenshots/m8-a-settings-error.png)。
5. 走查發現長設定視窗超出高度，已限制視窗高度並提供捲動；角色表單改為選角色後才展開，補上 Escape、Tab 焦點循環與返回焦點。

## 已知驗證界線

M8-B1～B5 的新增證據：同請求去重、DAG／200 任務上限、doc／sheet 固定範圍、四連線競爭兩個名額、取消後舊結果與媒體拒絕、租約過期重派、結案回報去重、問題暫停／回答續跑、工具交易日誌去重、聊天範圍傳入子代理、同交易提案核對與故障回滾、Flow 混合新舊分支、單步來源版本、明確重試及 direct Flow 啟動閘門。模型端仍為本機 fixture，未把此證據視為外部模型品質驗收。

- 真實中文輸入法候選字組合及 125% 縮放尚未實測；目前有 composition 保護，不能據此標成通過。
- A 階段支援角色對話、標註／表格提案及 Word 下載；文件正文 append／replace 與編排 Gate 屬 B 階段。
- 尚未測試外部付費模型、Docker、遠端 CI 或使用者長期日常協作；後續若驗證會明確追加，否則維持未驗證。

## M8-C 操作證據

1280×720，本機專用專案 `m8-c2-fixture`，Head 3039／模型與圖片 fixture 3040，使用真正的內建 worker 及兩個 `http_bridge` limb worker。沒有外部模型費用。

1. 勾選 `jobs/b_jobs/b_job1`，建立 coordinator 與 sheet_ops 兩候選，核對前均保留來源原值；比較畫面顯示 `fixture-coordinator`、`fixture-sheet_ops` 與各自 before/after。[並排核對](research/screenshots/m8-c-race-compare.png)。
2. 選用 B，只有第一列說明改為「候選 B：以清楚的步驟整理這項工作。」；Needs You 由 1 歸 0。[寫回結果](research/screenshots/m8-c-race-applied.png)。落選 proposal 狀態及 winner 在下方資料查核記錄。
3. 再次產生候選後，把原格改為「人工調整後的新來源，請保留。」；選舊候選回 409「資料已變更或正在編輯，請重新產生提案」。原格未被覆蓋，比較候選及錯誤仍留著。[衝突保留](research/screenshots/m8-c-source-conflict.png)。
4. 選 `assets/b_assets/b_asset1`，指定兩個圖片手腳及圖片欄；正式 worker 上傳兩份不同 PNG。核對時可見實際圖片，以 Enter 選用 A 後只有 C1 存入資產。[圖片競案](research/screenshots/m8-c-image-race.png)。
5. 文件選取一段、補充說明輸入 `@doc`，Enter 選代理完成標籤；按送出一次後，對話切到 doc_writer，保留標註來源與固定一段範圍。實際讀頁與標註提案完成後由人確認。[留言交辦](research/screenshots/m8-c-comment-routing.png)。HTTP 測試另證明讀取、普通留言及模型接受後的標註均不派發。
6. 新增明確「交給代理」選取工具列捷徑，先建立帶 `@doc_writer` 的留言草稿；使用者送出後才入既有對話佇列。輪詢不重設草稿、比較選取與錯誤。Dialog 以 Escape 關閉並把焦點返回看板。

人類留言路由採同交易「留言＋對話入列」，沒有第二套派發佇列；同角色忙碌時 409 並回滾留言，草稿保留。通用 safety prompt 與個別角色 prompt／knowledge 分離。遠端 fanout 每個 slot 僅收到自己那一列。

## M8-D 真實 adapter 證據

2026-10-18／Windows／Node，官方 `@agentclientprotocol/codex-acp` **2.2.2**，本機隔離安裝；ACP **protocolVersion=1**。不是用自製 echo 程序冒充官方 adapter。模型端明確指定本機 `127.0.0.1:3041/v1` 合成 Responses SSE，認證使用無效的 fixture 字串，沒有使用使用者登入或外部付費模型。

- 真實 initialize → api-key authenticate → session/new（stdio MCP）→ session/prompt 完成，adapter 回報 name/version。
- 真實 MCP `read_page` 讀 `jobs`，再 `propose_table_edit` 指定 `b_jobs/b_job2` 的說明欄；模型端共三個 HTTP 回合，後兩個各帶 1、2 份 function_call_output。
- Run `70ca3bf5-a384-40a4-a756-a767b05f60cb`；Task `55d17792-4f26-4c5f-b053-fc9be0bcf0c8`；Dispatch `9218bf10-6ebe-48fb-87fa-9b8f26541f0d`；Proposal **550**。工具日誌保存 propose_table_edit 結果。
- UI 核對「尚待補充 → ACP adapter verified proposal」，確認整組寫回後 B2 符合預期，B1 人工修改及第三列保留。[ACP 核對畫面](research/screenshots/m8-d-acp-proposal.png)。
- 第一輪只驗到文字轉提案，已明確取消；未列為讀頁驗收。其後依 adapter 實際 namespace tool 格式修正本機模型 fixture，再完成上述路徑。
- 契約測試 9 項包括分片、無關 response id、thought 忽略、原生檔案／終端／權限要求拒絕、無效 JSON／EOF／過大訊息、真 MCP 掛載、問題釋放、已生成後代程序取消，以及不讀 stdin 時的 deadline watchdog。

ACP 仍使用既有 `llm` 能力，不新增不相容 capability constraint。`runtime_kind=acp_stdio` 配置必須綁定受信任 Worker。部署、環境與隔離限制見 [WORKERS.md](WORKERS.md#acp-stdio-橋接)。

## 工程 gate（最終審查前）

- 隔離後端 **227/227**、0 失敗、0 跳過，184.253 秒（含 Flow 啟動修正；ACP slice 226 項為 162.711 秒）；前端 **75/75**、0 失敗／跳過；Vite 300 modules build 成功。
- `python -m build` 與 `verify_wheel.py` 通過；全新 wheel 環境在 checkout 外讀取 SQL 10／prompts 7、import ACP，並真實啟動已安裝 MCP 完成 list/call。
- 第一輪完整測試因互動 fixture worker 也掃描同一測試庫，使 51 筆工作計數變 50；另有 ACP 時間門檻僅差 44 毫秒。停止已確認的互動 fixture，保留 timeout 狀態斷言並納入程序清理成本後，focused 與完整回歸均成功。沒有因此放寬產品租約或容量檢查。

## 三條實際合成路徑

完整收據（不含 token）見 [m8-journey-receipts.json](research/m8-journey-receipts.json)，專案 `m8-journeys-3`。同步 driver 僅領取此合成專案，再呼叫正式 `worker.execute_dispatch → agent_runtime`，沒有全域背景掃描器或付費模型。

- **辦公**：固定 `b_office1/b_office2`，兩項 sheet_ops 產出各自核對；兩份通過後 QA 才執行，再由 doc_writer 產生週報並核對。Flow `a701745f-2e12-4324-9958-871467b99e43` 成功，proposal 708/709/710 已套用，第三列 `b_office3` 仍是原值。
- **美術**：`m8-c2-fixture` 的兩個真實 remote worker 上傳不同 PNG，單一 race Gate 選用圖片 A；勝出 applied、落選 dismissed，收據見 [m8-c2-receipts.json](research/m8-c2-receipts.json)。未以影片播放器作為入口。
- **自由流程**：coordinator 提問題後釋放回合；回答後新 admission 續跑，兩個 doc_writer 分支各自產生提案，確認後才執行 join，最後匯總也需確認。兩條流程的全部 limb task 均 succeeded，問題派發與續跑派發為不同 id／admission。

走查修正了一個產品缺口：Flow preflight 認得內建 profile，但 start 仍查舊的遠端能力。新增 `test_builtin_profile_flow_starts_without_a_remote_limb`，RED 重現 409，改成共用 `_node_connected` 後 11 項 Flow 測試通過。混合分支測試也明確提供內建心跳，不再讓無關遠端手腳掩蓋此檢查。

另一次手建 fixture 遺漏正式文件正規化，導致欄位引用保護拒絕提案；已在 fixture seed 使用正式 validate_doc，未放寬產品保護。失敗專案未當成成功證據。

## 故障恢復對照

| 中斷位置 | 可檢查的證據 |
| --- | --- |
| claim 後失聯 | 租約過期新 admission、舊完成／媒體拒絕、第二次失敗終結：`test_orchestration_concurrency.py` |
| proposal 建立後 | 問題 Gate 續跑保留 provenance、舊提案作廢；套用前 worker 完成及整組核對檢查：`test_orchestration_proposals.py`／`test_delegation_tools.py` |
| commit 後回覆前 | 遠端 complete 重送相同結果、worker_done 只一筆、不同結果衝突；工具 journal 防止重建提案：`test_orchestration_limbs.py`／`test_delegation_tools.py` |
| 核對交易途中 | failure injection 證明 canvas＋proposal＋task rollback：`test_hook_failure_rolls_back_canvas_and_proposal` |
| ACP 程序中斷 | 真 stdio EOF、過大訊息、deadline、已產生後代行程 lease loss、阻塞 stdin、MCP Gate 釋放：`test_acp_bridge.py` |

這些是測試程序與真實交易／stdio 的故障邊界驗證；未宣稱有做 OS 斷電或生產環境故障演練。預設 root dispatch 期限沿計畫為 240 秒，包含等待核對；需要更長時可由建立 Run API 明定 deadline，UI 目前沒有延長控制。已過期提案不能再套用，需重新交辦。

自由流程的原生結果面板顯示 **4/4 已完成**，Gate journey 為第 2 次嘗試，分支 proposal 711/712、join 713。[四步結果](research/screenshots/m8-e-branch-join.png)。此合成 fixture 未設定節點座標，截圖僅作執行收據，不能作節點排版品質證據。

## 最終審查修正與交付結果

獨立審查固定 `231f45512d9b5d63d74c14a9ab9a50078beb4d23`，提出 7 項 Important、沒有 Critical／Minor。已在一次修正批次完成：同任務來源指紋保護、排程錯誤隔離、相依 race 註冊、相依快照更新、chat Gate 日誌／脈絡移交、待核對整批取消及舊 Codex engine 相容。每項都有先失敗的對應測試；完整結論及證據見 [最終審查與裁定](research/m8-final-review.md)。

最終後端 **235/235**、零失敗／跳過（153.662秒）；前端 **76/76**，Vite300 modules build；wheel建置／資源檢查／乾淨環境checkout外真MCP呼叫均通過。原審查SHA與修正後版本分開記錄，沒有冒稱第二次獨立LGTM。

取消走查：兩候選完成後關閉比較，仍保留待裁決1，Escape焦點返回觸發按鈕；明確按「取消這批工作」後待裁決0、run canceled、兩proposal dismissed，第三列保持「需要整理」。[取消收據](research/m8-cancel-receipt.json)、[取消畫面](research/screenshots/m8-final-race-canceled.png)。
