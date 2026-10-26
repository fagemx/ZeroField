# SPEC_16A — 三空間整合 V12 審查與修正紀錄

日期：2026-10-26。範圍是 SPEC_16 寫作工作台進入 SPEC_18 三空間外殼，不是替使用者驗收 SPEC_16，也不是 SPEC_17。

## 審查身分、候選與證據邊界

- 使用者已批准 D1–D7；D7 要求全新的唯讀審查者看整合差異。
- V12 審查者：`claude-opus-5-5`，獨立子代理 `a580e473645ef6e1b`，閱讀候選 `74a0a0b6188f193e65c37c489e6a9880d5946a0f`。與當時整合者同模型家族，**只稱獨立閱讀，不稱跨家族審查**。
- 原審查只追程式並執行 `storyHostModel`、`storyStartHandOff`、`i18n` 三個前端測試入口；沒有跑瀏覽器、後端、CSS 或文件檢查，也未全面重審 SPEC_16 內部。
- 原報告有九組 P1/P2 發現與一組 P3 備註，**不是通過結論**。下表的修正／實證是整合者及後續分工的結果，不冒充原審查者已重新審過修正。
- 修正候選及命令、通過／失敗／略過數量另見 [整合驗證收據](spec16-integration-verification.json)。原 SPEC_16 的 [審查](SPEC16_REVIEW.md) 與 [收據](spec16-verification.json) 保留，不拿舊總數當新候選的結果。

原始本機報告位於本次 Claude 工作階段的 `subagents/agent-a580e473645ef6e1b.jsonl`，結論在 `SubagentHandback.input.message`；本文件保留可在儲存庫閱讀的摘要與處置，不要求其他人能存取該暫存逐字稿。

## 發現與處置

| # | 原發現與確認程度 | 修正及證據 | 狀態／限制 |
|---|---|---|---|
| 1 | **P1，IDB 不可寫時可成 P0；已確認。** 右欄資產捷徑、同空間選單 intent、`focus.assetCode` 直接切牆，繞過稿件儲存邊界。 | `StoryWorld.switchView` 統一所有頁內離開路徑；只有完整 `control.flush()` 成功才改 view／篩選／選取。`test_quick_asset_card_flushes_unsaved_manuscript` 用真編譯 root app／授權 HTTP／PG，輸入後立刻點卡片，直接檢查伺服器稿件。 | 已修。三條路徑都經共用邊界；真瀏覽器直接覆蓋 quick card，其他入口另以程式追蹤核對。 |
| 2 | **P1，無 IDB 可成 P0；已確認。** 「按場次／角色與場景」只做 `requireServer`，略過 outline／Bible 工具草稿 checkpoint。 | 離開一律完整 `flush()`；需要伺服器稿件的建立／預覽才用 `flushDocument({requireServer:true})`。`test_wall_toggle_and_quick_card_cannot_drop_uncheckpointed_outline` 同時拒絕 IDB 寫入與 metadata 網路保存，兩個離開入口均被擋，表單內容仍在。 | 已修。工具仍是私有草稿，導航不會暗中發布共享表單。 |
| 3 | **P1；追蹤確認。** 初始 workspace 讀取失敗時控制器永遠回 false，導致無法離開。超過 1,000 結構單位是可重現例子。 | 尚未載入任何稿件時，可安全離開；需要伺服器稿件的動作仍拒絕。載入錯誤保留重試及 `Download current draft`。真瀏覽器同時覆蓋注入 413 與實際 1,003 個 top-level blocks 的 413，下載逐字符合 episode 的伺服器文字，之後能進片場。 | 已修導航與救援，**未提高結構上限**。此類稿件仍不可宣稱能擷取／建立；legacy 匯入會正規化段落分隔，下載對照的是已儲存的 episode 文字，不是匯入前字節。 |
| 4 | **P1；已確認。** 片場的「前往來源」會恢復在角色牆而不是稿件。 | episode-bound source intent 強制 script view；跳轉成功消費 nonce。`test_source_jump_forces_script_and_is_not_replayed_after_another_visit` 從牆進片場、點有來源的生成鏡頭，回稿件後改選別場，再往返空間確認舊跳轉不重播。 | 已修。測試精確選 `SC01-S01`，不是沒有來源的範本 legacy `S01`。 |
| 5 | **P1；原為 plausible。** `[A,B,A]` 重複拍點的 ambiguous 鏡頭不被認領，反覆建立不斷增加；段內 hardBreak 後的 `Scene` 會與穩定場次邊界不一致。 | 真 HTTP／PG 先重現：三次 build 為 **3→5→6**，估算每次仍是 3；修後是 **3→3→3**，newShots **3→0→0**。`scene_claim` 可把可證明同一穩定場次的 ambiguous 生成鏡頭計為片單佔位，但不改寫來源為 exact；即使 explicit rebuild 也保留 ambiguous 鏡頭。`scenes_of_doc` 以相同 top-level blocks 劃場，保留 hardBreak 給切鏡。 | 已確認並修。新 `test_writing_storyboard_regression.py` 四項及八項關鍵既有回歸通過。foreign／detached／無法消歧 split 不認領；導演文字、光學、運鏡、秒數、takes、選片不被覆寫。人工 exact+detached 組合的 outline 投影顯示規則不在本次修正範圍。 |
| 6 | **P1；已確認。** R16 先 `takeStart` 刪唯一原文，再 raw `PUT script`；失敗丟交接，非空稿件也被覆蓋。 | 非破壞性 `peekStart`、固定 handoff ID、mutation 前 durable sessionStorage checkpoint；工作台透過 actor-bound helper 持久化，ACK＋資源載入成功後才 compare-and-delete。空來源做 CAS；既有來源／稿件保留，另開 private branch；空工作中稿使用區塊寫入，host 不再 `PUT script`。真瀏覽器覆蓋來源寫入成功但 ACK 遺失、reload 重播後 version 仍是 1；另覆蓋非空工作中稿 hash 不變且新文在另稿。 | 已修資料保全路徑；重試與憑證限制、一次未解偶發失敗另列下方，不能承諾普遍 exactly-once。 |
| 7 | **P2；編輯器 ref 競態 plausible，無 IDB 自動重試迴圈由追蹤確認。** 舊 editor 的 `setContent` 可漏接新文；依 switching 重跑造成迴圈。 | 不再靠 editor ref 注入。helper 先持久化再載入資源；`seedWork` 只啟動一次，失敗由使用者按 Retry 才重試；交接前只要求稿件伺服器邊界，不發布無關工具表單。 | 已移除所指出的機制，兩條真實交接旅程通過。完整「無 IDB＋R16」瀏覽器組合沒有新增直接實證，不以其他 IDB 測試代替。 |
| 8 | **P2；已確認。** App／宿主保留來源跳轉，remount 重播，換集後還可指向上一集。 | App 與宿主比對並消費 nonce，帶 episodeId、換集清 focus／status，StoryWorld 以 project／episode／actor keyed session。 | remount 重播有真瀏覽器證據；跨集特殊條件以程式追蹤核對，沒有聲稱新增獨立跨集瀏覽器旅程。 |
| 9 | **P2；已確認。** 建立的 settings／extract／storyboards 不用 actor-bound request、沒有 abort、無 actor 時退回 raw request。 | 建立與估算使用 bound request；signal 傳給等待與每一步，完成前檢查 mounted／abort；無 actor fail closed。伺服器在 dispatch／receipt replay 前核 supplied expected actor。`test_identity_change_during_build_stops_before_extraction_and_storyboards` 在 settings 真實完成後切換 cookie 身分，確認無後續 extraction／storyboards；Node 回歸覆蓋 abort。 | 已修建立鏈。既有資產 CRUD 仍有 raw Story 呼叫，不宣稱整個角色牆的所有寫入都改為 actor-bound。 |

## P3 備註

1. **StrictMode disposable request**：改為穩定 request facade，由 layout effect 每次建立／釋放 session；outline recovery 亦可 activate／dispose。`ui/tests/storyHostStrictMode.test.mjs` 已在真 Chromium＋React development 直接掛載 StrictMode StoryWorld，probe 觀察到 `setup→cleanup→setup`；驗證 replay 後 actor-bound 載入、鍵盤保存、outline PATCH 500 後 IndexedDB 復原、明確恢復不自動發布，以及再保存／reload。已包含在最終完整前端 **503 項通過、零失敗／零略過** 中。transport 是合成 fetch Response，不冒充真後端認證或 PG 證據。
2. **上一集 scriptStatus 殘留**：宿主改為 project／episode／actor keyed session，換集清 writingStatus；離開稿件 view 也清狀態。已修，特殊換集錯誤路徑主要是程式追蹤證據。
3. **缺頁面 h1／nested main**：**未修，保留為可及性語意後續**；沒有宣稱完成無障礙認證。
4. **每次 save ACK 重新讀 episode 與 assets**：**未優化**；沒有把合成性能測試說成網路或大專案吞吐保證。

## 重試、實證與其他殘餘限制

- **R16 一次未解偶發失敗**：某輪八項宿主回歸中，小說已寫成功、pending 保留，但 reload 後仍停在 working 稿件並顯示可重試提示。後續單項 4 次、16 次與完整八項重跑都通過，尚未捕捉到那次 seedError 的確切原因。保留失敗日誌，**不以多次成功反推成因已修**；最新完整回歸結果另見收據。
- **憑證範圍**：後端 receipts 綁 actor／credential／episode。checkpoint 綁 actor 與輸入，但目前沒有 pin credential fingerprint；同 actor 登出再登入後，曖昧 branch-create 自動重播不保證去重。24 小時過期 fail closed；換憑證或期限外應下載原文作人工復原，不聲稱跨重新登入 exactly-once。
- **空工作中稿的競爭**：GET 後其他作者插入不同 block，原子 `script/ops` 會保留兩份 block，而不是整份文件 CAS。沒有刪除或重排他人內容，但可能是協作合併，不保證仍是「只有這份開頭」。
- **source jump 拒絕**：一次性 jump 即使導航因保存／來源不存在而失敗也會消費 nonce，不會自行無限重試；使用者可再次明確點來源。
- **下載／儲存媒介**：瀏覽器下載事件及下載檔內容可驗，不能保證使用者最終 OS 存檔、跨裝置備援或瀏覽器遭強制關閉前最後幾鍵已 checkpoint。
- **性能測試的 readiness**：修正了只看「字」便把上一集 editor 當新稿的測試競態；現在等 episodeId＋docHash，再操作語意 editor locator。500k 測試是首場約 5k 字的 scene-loaded DOM，不是把 500k 全文放進 DOM 測輸入。
- **舊 Agent Console 旅程**：`ui/tests/agentConsole.browser.py::test_navigation_templates_keyboard_locale_and_production_context` 在整合前 `4e7e8e2` 也找不到舊 `.story-shot-tools`；本次沒有改它，沒有把它列為本候選通過。
- **測試層次**：真 root app／授權 HTTP／PG、真 Chromium＋合成 transport、Node mock transport 各自標示。圖片推論替身、CSS 截圖或 wheel byte identity 都不等於產品模型／GPU／計費／視覺品質驗收。

## 交付界線

保留三空間、角色牆、唯一主按鈕、BreakdownDialog、原本的 ScriptOutline 元件/API。改編目標場數預設 3。沒有採用 selection-handoff 未提交後續，沒有做 SPEC_17、呼叫產品模型、新增供應商、推送或部署；沒有修改 SPEC_16 原分支／工作樹。使用者於 2026-10-26 新授權：完成驗證後合回原開發分支 `feat/spec18-studio-revision`，保留主樹無關未提交內容；合併結果以 Git 歷史及交付回報為準。合回不等於替使用者作 SPEC_16 功能驗收。
