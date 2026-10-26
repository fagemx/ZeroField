# SPEC_16A R16：獨立複審 C1 修正與 W2 harness 診斷

## 候選與結論

本批從 `b5ccca765acf1951b8adeb816cc1e397746b7157` 接續，仍限定 `C:/ai_project/ZeroField-r16-followup`／`fix/spec16a-r16-followup`。產品與 harness 分別提交：

- `07d7110b76722ed791987afdd00fd3ff4ad6369b`：C1 最小產品修正、無 DB 回歸及修前／後原始輸出。
- `6f6763dc865ee49ec1e3cb3bd200bf28ac732b82`：W2 測試 readiness、具名 gate 與診斷；沒有 Bible 產品變更。
- `0c0fe6edd4cab4faf352e4f72b4500846a603244`：耐久複審原文、最終預設前端結果與 [新收據](spec16a-r16-c1-verification.json)，也是修後獨立複查的精確候選。
- 後續文件收尾提交只保存修後複查與結論，不變更產品或測試；最終 HEAD 以 Git 歷史與交付報告為準。

**C1 已確認並作最小修正；歷史小說 ACK-loss 根因仍未證實（`historicalRootCauseProven=false`）。** W2 已重現具體 harness readiness 缺陷並修測試，但不能宣稱它就是 b5 並行失敗的唯一原因。最終預設並行前端本輪 **504/504 通過**，不改寫 b5 的 503/504 歷史失敗。

## 新獨立複審與處置

完整 [獨立複審原文](verification/spec16a-r16-c1/post-repair-review.md) 已逐 bytes 複製保存，SHA256 為 `620b82c4d20647fa00d7c923f5a511fbc480d204ebc30d82601f887d7c0b2cb3`。它對 b5 的總評為 **CHANGES REQUESTED**，工作 B 的定向調查為 **OK with notes**，是同模型家族的全新唯讀獨立閱讀，不是跨供應商或使用者驗收。該原始報告的 CHANGES REQUESTED 不改寫為通過。

修後已由同一獨立 reviewer 重新檢查精確候選 `0c0fe6edd4cab4faf352e4f72b4500846a603244`，結論 **OK with notes**，C1／P1 在 `scenes_of_doc` 正文與拍點投影範圍確認關閉。完整 [修後獨立複查](verification/spec16a-r16-c1/c1-independent-recheck.md) 逐 bytes 保存，SHA256：`8f0a237e3c9ca696fa3e3c7075f60295039012fe557a512b8439ae6d12c8aaa9`。Reviewer 親跑 Python 23＋Node 23＝46 項通過，另在記憶體載入 b5 舊函式得到預期 5 failures，確認回歸能辨識原缺陷；最終預設前端 504 項屬讀取 writer 日誌，不冒稱 reviewer 重跑。

第一次修後複查嘗試因供應端伺服器過載失敗，沒有產出結論；已保留失敗回執，之後以同一 Pi／同一模型及 reviewer session 接續完成，未重做修正或切換執行器。這仍是同模型家族的唯讀獨立複查，不是跨供應商或使用者驗收。

| 項目 | 本批處置 |
|---|---|
| C1／P1：標題 block 的 hardBreak 正文丟失／混入場名 | 無 DB 與真 JS helper 跨模組驗證先確認，再修 `scenes_of_doc` 的文字投影。 |
| W1：b5 預設並行 503/504 不能稱全綠 | 保留 b5 文件／收據／原始日誌；本批只新增新的結果，不以序列或單檔替換舊失敗。 |
| W2：累積 statuses 可跨集誤命中，缺 sequence／IDB／request 關聯 | 命名 gate 直接重現舊 readiness 假陽性；改 episode／docHash／manager scope readiness，加入保存 lifecycle 與 journal gate 及關聯 trace。沒有重構 Bible 產品。 |
| 原始日誌 whitespace | 保留 bytes；列為證據例外，另跑 source／報告 scoped diff-check，不裁切。 |

## C1：修前證據與最小修正

`writing_structure.sections()` 以頂層 block 決定場次。當該 block 以 Scene 開頭，它整個成為 heading，之後的 `nodes` 不含它。原 `scenes_of_doc` 只以 `nodes` 組正文，且 `node_text(heading)` 把 hardBreak 轉成空白：

- 真 `persistStartHandoff` 寫空工作中稿的單一 paragraph，原解析場名變成「Scene 01: Room＋全部動作／對白」、content 為空、auto planner 回退成一個混合標題拍點。
- 新無 DB 測試在修前執行：5 個 test methods，含 subtest 的 **5 個 failure**（JS 跨模組 1、heading／paragraph 2、內嵌 Scene 字樣 2）；一般分 block 與 repeated-beat 防線原已通過。原始輸出：`c1-before.log`。

修正只在 `project_docs/story_openapi.py::scenes_of_doc`：以保留 hardBreak 的 `doc_text` 取 heading block，第一行投影為 title，其餘文字按原序、原換行放回 content，接著才接原本後續 blocks。沒有修改原文件、`sections`／`reconcile_structure`、穩定鍵／映射、CAS、手動採用或 handoff 格式。

`tests/test_story_scene_projection.py` 覆蓋：

1. heading 型與 paragraph 型標題同段正文，動作／對白保持為兩個 auto 拍點，原文件不變。
2. 空行、尾端換行、後續 block 的順序，以及 heading block 內的 `Scene 99:` 只是正文、不另造穩定場次。
3. 一般分 block 的兩場、純標題 fallback、無標題與空文件。
4. repeated `[A,B,A]` 拍點仍三個；無 DB 讀取替身下，實際 `scene_claim` 可認領同穩定場次的 ambiguous 佔位，`shot_relationship` 仍回 ambiguous、沒有補造 exact beatKeys，detached 不認領，planner 不新增已有的三個席位。**這不是本批真 DB repeated-build／take 保存證據。**
5. 真正呼叫 JS `persistStartHandoff`，捕捉其實際 `script/ops` node，直接交給 Python `scenes_of_doc`／`beat_plans`。只替代 transport 的回應，不複製 `plainDocument` 或 Python parser。修後場名回到單行、content 保留動作／對白、auto 為兩拍。CRLF 由真 helper 正規化。

修後新測試 **5/5**、既有 `StoryPureTests` **14/14**、`PlannerPureTests` **4/4**，共 **23 個無 DB test methods 通過**、零略過。這不是完整後端，也不借用舊 813 的通過數。

## W2：已證實與尚未證實的區別

修改只在 `ui/tests/writingToolsRecovery.test.mjs`。真 `AuthoringWorkspace`／`WritingBible`／`BibleFormRecovery` 仍掛載；測試層包裝 manager open／dispose 以追蹤 scope、journal put 以注入 gate、原生 IndexedDB transaction 以記錄開始／完成／錯誤。真正 IDB 寫入仍執行。fixture HTTP 只回記憶體資料，不是產品 DB／cookie 授權。

### 可重現 harness 缺陷

`episode-2` gate 精確阻擋 ep-2 的 workspace GET。在放行之前，控制器已是 ep-2 但 docHash=null、尚無該集的 manager；原 `statuses.at(-1)` predicate 卻仍為 true。新 predicate 會拒絕，須同時符合當前 episodeId、working resource、該集專用 docHash，以及未 dispose、已 discover 的 actor／project／episode manager indexScope，並確認 registry 狀態對應。

所有 reload／換集／換身分 recovery 等待都改用此 predicate，不再靠上一集累積的 statuses。原 dirty／內容／CAS／私有恢復斷言保留，未改長 timeout。

### 保存與 IDB 的具名 gate 診斷

- `catalog-after-save`：在故意 409 後明確合併並成功 PATCH 200，阻擋後續 catalog GET。此時「Saved on the server」已可見，但表單仍因 accepted callback 未完成而 disabled；測試須放行且等待當前請求結束與 Subject 可操作，才開始下一筆私稿。
- 這時確實仍可見父層 `Shared version changed`，而 manager 為 saved、conflict=false，PATCH trace 只有 `[409,200]`。**已直接證實此畫面可以只是舊錯誤殘留，不能用它判定新的 CAS 衝突。** 本輪沒有修父層錯誤提示產品，也沒有因此改 Bible 權限或保存流程。
- `private-form`：精確阻擋 `Private awaiting divergent restore` 的 form journal put；index 已可完成，但 manager 是 sequence=4、durableSequence=3、dirty／不可復原，仍只有那兩次 PATCH。放行後真正 form IDB transaction 完成，manager 才成 sequence=durableSequence=4／local_only，再驗 UI 私稿保存與 reload。

每個階段及任何失敗都輸出當前 scope、sequence／durableSequence、request id／actor／episode／status、IDB transaction id／mode／結束、journal key／sequence、父層 alerts。完整原始輸出保留；[縮要 trace](verification/spec16a-r16-c1/w2-trace-summary.json) 是從最終 targeted 原始輸出另行抽取，不取代或裁切原檔。

初次 W2 instrumented 執行失敗於把 `<fieldset disabled>` 用 Playwright `to_be_disabled()` 判斷：該 matcher 不適用於 fieldset，日誌明明顯示 disabled 屬性。改成直接驗 disabled attribute，idle 則驗真正 Subject 控制項，未改產品或放寬資料斷言。該 harness 失敗原始輸出亦保留。

**仍未證實**：b5 歷史並行失敗沒有當次 manager／IDB／request 關聯，不能把上述已證實 readiness 問題或保存 gate 唯一歸因給那次失敗，更不能說已永久消除所有偶發。最終本輪 504 通過只代表這次執行結果。

## 本批實跑／未跑

| 命令 | 結果 |
|---|---|
| `python -X utf8 -m unittest discover -s tests -p test_story_scene_projection.py -v`（修前） | 5 methods，5 failures（含 subtests）；C1 產品缺陷證據。 |
| 同上（修後） | 5/5，零失敗／略過。 |
| `python -X utf8 -m unittest discover -s tests -p test_story_openapi.py -k StoryPureTests -v` | 14/14，僅純測試類，不執行 HTTP／PG fixture。 |
| `python -X utf8 -m unittest discover -s tests -p test_story_estimates.py -k PlannerPureTests -v` | 4/4，僅純 planner 類。 |
| W2 初次 instrumented 單檔 | 3/4；fieldset matcher 的 harness 問題，保留原始輸出。 |
| W2 matcher 修正後單檔 | 4/4；中間版本，未當最終來源的唯一證據。 |
| `node --test ui/tests/writingToolsRecovery.test.mjs ui/tests/storyStartRecovery.browser.test.mjs ui/tests/writingStartHandoff.test.mjs ui/tests/storyHostStrictMode.test.mjs` | 最終 targeted **23/23**，零失敗／略過／取消。 |
| `npm test --prefix ui` | 最終預設排程只跑一次，**504/504**，零失敗／略過／取消。 |

完整命令、日誌與 SHA256 見新收據。未跑含 DB fixture 的完整後端、真 PG／HTTP 宿主旅程、wheel、供應商／模型／GPU。**ui/src 沒有修改，因此未重建 static/projects**。沒有新依賴或下載，沿用既有本機工具鏈。

## 剩餘風險與凍結界線

- 歷史小說 ACK-loss 根因未證實；C1 是新複審所確認的劇本投影回歸，與那次小說 reload 故障不得混稱。
- W2 具體 harness 問題有定向證據；b5 當輪失敗的完整歷史歸因仍未證實。舊父層錯誤提示殘留仍保留，未擴成產品重構。
- 本批沒有重跑真 DB repeated-build、跨 cookie、真 receipt／24h／換憑證或 GPU／模型，相關舊限制保留。穩定結構的原始 title／mapping 產生方式也未藉此重設計。
- b5 follow-up、舊收據與原日誌原樣保留；修後獨立複查是限定差異的 OK with notes，不代表全部情境通過或使用者驗收。
- Reviewer 另確認穩定 outline 顯示標題仍可能混入同 block 的正文（`writing_structure.py`／`WritingOutline.jsx`）；它不再造成本次 C1 的空正文／錯誤拍點，但尚未修正，不宣稱所有結構場名都已正規化。
- main、原 SPEC_16 工作樹／分支與無關未提交內容均不修改；未操作 PostgreSQL／權限，未推送、部署或合回；未用 skills、子代理、其他模型／CLI，也未做 SPEC_17／18 新功能。
