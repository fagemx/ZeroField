# SPEC_16A R16 定向調查（獨立 follow-up）

## 結論與範圍

**歷史根因未證實（`historicalRootCauseProven=false`）。本候選只新增測試與證據，沒有產品修正。**

基底：`aae5826f73e224824f5cb488e41e423e2eaaca1d`；施工限定 `C:/ai_project/ZeroField-r16-followup`／`fix/spec16a-r16-followup`。D1–D7 不重新設計，原始 [V12 審查](SPEC16A_REVIEW.md)、[歷史收據](spec16-integration-verification.json) 與原始失敗日誌不改寫。本文件不是原 reviewer 接受、修後複審或使用者驗收。新獨立複審由上層接續，目前尚未執行。

## 歷史證據能證明什麼

四份本機原始日誌 SHA256 均與舊收據相同；詳見 [本輪收據](spec16a-r16-followup-verification.json)。只讀取 `tests/test_spec16a_host_browser.py`，沒有執行其 PG fixture。

`spec16a-host-browser-final.log:547–591` 記錄小說 lost-ACK 測試在第二次 reload 後等待 `source:novel` 逾時（5 秒），實際為 `working:main`，選單曾 disabled 後恢復 enabled。測試此前已完成原文／source-save checkpoint／伺服器已持久化的斷言；但日誌**沒有**該次 seedError、重播回應碼、資源 GET、checkpoint 終態或完整請求關聯。散落的 ConnectionAbortedError 不能直接歸因至該集／該次交接。後續四次、十六次及宿主八項成功只證明那些執行通過，不證明原因或根除。

## 已追清的現行機制

- `StoryWorld.jsx` 的 episode 載入 effect 使用非破壞性 `peekStart`；宿主 `seeded` 才 `acknowledgeStart`。
- `AuthoringWorkspace.jsx:81–98` 初次載入 working；`loadSequence` 排除過時載入。`130–145` 在 workspace ready 後只啟動一次 seed，要求稿件保存，執行 helper，再 `load(ref)`，成功後才通知宿主。
- `writingStartHandoff.js:73–76,97–135` 的 source-save checkpoint 保留原 body、baseVersion、clientMutationId；ACK 遺失時不另選目的地。ACK 通過才 checkpoint 為 done，done 重進只回傳 ref，不再 mutation。
- 因此 **source PUT 已成功不等於來源已在編輯器開啟**。重播本身失敗可留在 source-save；重播 ACK 成功後的 workspace／source GET 失敗可留在 done。兩者都會進同一個 seedError／Retry 介面，仍顯示之前的 working。這是可實證的狀態機，不是那次歷史故障的已知原因。
- `writingTransport.js` 的 actor-bound session 在 disposal／abort 後拒絕晚到結果；`startModel.js:66–80` 只 compare-and-delete 同一筆 handoff。

## 新增的可重現定向測試

`ui/tests/storyStartRecovery.browser.test.mjs` 以真 Chromium、React development StrictMode 真掛載 `StoryWorld` 與 `AuthoringWorkspace`。一個 Node 測試包含五個具名案例；每案新 browser context，檢查 `setup→cleanup→setup`、episodeId／resourceRef／docHash readiness、actor 標頭、編輯器原文及 pending 清除。不是 SSR 或模型 helper 替代元件。

| 案例 | 受控事件與斷言 |
|---|---|
| lost | mutation 前 durable checkpoint；合成提交一次後丟 ACK；reload 同 body 重播。阻擋 StrictMode 兩個 initial workspace GET，先放行較新者；重播 ACK 後仍保留 done pending，另阻擋目的 source GET。來源載入後才清 pending；最後放行舊 working GET，不能覆蓋小說。version／實際合成寫入數均為 1。 |
| resource-failure | 成功 ACK 後的 source GET 精確回 503，穩定呈現 working＋Retry，checkpoint=done。reload 再失敗仍不 PUT；明確 Retry 恢復來源，無第二次寫入。**這是注入的相同症狀，不是歷史 503 證據。** |
| replay-failure | lost ACK 後重播精確回 503，checkpoint=source-save；不自行重試。解除故障並點 Retry，使用原 body／mutation 身分，寫入數仍為 1。 |
| late | 合成提交後阻擋 ACK，切到另一個 project／episode 的真正 workspace，驗 episode／hash 及原 request signal 已 aborted；刻意忽略 abort 才回的 ACK 不清原 pending，也不切回舊資源。reload 後原 checkpoint 可恢復。 |
| no-idb | 讓 IndexedDB 不可用，sessionStorage checkpoint 仍可保存且交接來源完成；不聲稱覆蓋所有 IDB quota／資料損壞組合。 |

所有時序由命名 Promise gate、請求事件與語意 readiness 推進，沒有 arbitrary sleeps 或大量盲目輪跑。兩個 animation-frame barrier 只讓已釋放 Promise 鏈與 React commit 結束，不用來猜測網路完成。每個階段輸出 checkpoint、actor／body／signal／呼叫順序；失敗另輸出當下工作台內容。

**合成 transport 邊界**：本機 HTTP 只服務測試 HTML／記憶體 bundle；產品 fetch 全由合成 `Response` 回應，伺服器狀態／receipt 以 fixture sessionStorage 模擬，並非 PostgreSQL 或真授權／憑證／receipt 實作。未知產品 fetch 直接失敗，沒有產品模型、GPU、供應商或外網。沒有執行 production root app、真首頁建立或真 DB 旅程。

## 實跑結果（不隱藏失敗）

- 最終 scoped：`node --test ui/tests/storyStartRecovery.browser.test.mjs ui/tests/writingStartHandoff.test.mjs ui/tests/storyHostStrictMode.test.mjs`：**19/19 通過**。
- 最終預設並行 `npm test --prefix ui`：**503/504 通過、1 失敗**。新 R16 案例通過；既有 `writingToolsRecovery.test.mjs` 在 `Private awaiting divergent restore` 後等待本機保存狀態失敗，畫面為 Shared version changed。本輪沒有修改該檔或 Bible 產品。
- 為區分該範圍，單檔 `node --test ui/tests/writingToolsRecovery.test.mjs`：**4/4 通過**。
- 明確改採序列排程（不是盲目重試）：`node --test --test-concurrency=1 ui/tests/*.test.mjs`：**504/504 通過**、零略過／取消。不能據此宣稱預設並行失敗已修，該失敗根因亦未證實。
- 初始新 harness 有兩次失敗：錯把所有 workspace GET 都設 gate，並假定 StrictMode 的 initial GET 一定 aborted；實際 facade／loadSequence 讓兩個 GET 使用現行 session，第三個為 ACK 後載入。修正的是 fixture gate／斷言，沒有產品修前失敗或產品修正。中間五案例通過日誌亦保留。
- 只改測試／文件，**未跑 build、完整後端、wheel、真 HTTP／PG／provider 驗證**；沒有 ui/src 變更，不需新 static/projects 產物。產品 Git diff 相對基底為空。本輪完整前端測試使用現有離線工具鏈與隔離樹 `ui/node_modules` junction；未安裝或修改原樹依賴。

原始命令輸出（包含英文工具原文）完整保留在 `docs/verification/spec16a-r16/`，SHA256／結果在本輪收據。較早一次並行 504 通過的輸出曾在終端觀察到，但當時日誌路徑後被最終並行失敗覆寫，不將其當最終可雜湊通過證據。

## 剩餘風險與交接

1. 歷史根因仍無法歸因；若真環境再次發生，需同一次的 seed checkpoint stage、actor／episode、重播 response 與 resource-load response 關聯，不能只依 UI Retry。此輪測試 trace 可直接作為定向診斷模式，不新增產品遙測或記錄私有原文的功能。
2. 真後端憑證範圍／24h receipt、跨登入、整份文件 CAS、所有資源競態、OS 持久化均未因此擴大保證；原殘餘風險保留。
3. 預設並行 Bible recovery 失敗未解；單檔及序列成功不等於根除，也不把 scoped 通過拼成該輪全綠。
4. 未推送、部署、合回 main／原開發分支；不修改原 SPEC_16 工作樹／分支；未採 selection-handoff，未做 SPEC_17／18 新功能，未操作 PostgreSQL 或權限。
5. 上層可對此只含測試／文件的 scoped 候選做新的獨立閱讀；不得宣稱原 V12 reviewer 已接受。
