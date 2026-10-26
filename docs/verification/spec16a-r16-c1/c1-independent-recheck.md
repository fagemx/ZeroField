# C1／W2 修正獨立複查

**結論：OK with notes**

**Reviewed SHA：`0c0fe6edd4cab4faf352e4f72b4500846a603244`**

本次實查分支為 `fix/spec16a-r16-followup`，工作樹及 index 均乾淨；`main` 仍為 `aae5826f73e224824f5cb488e41e423e2eaaca1d`。審查範圍限定 `b5ccca765acf1951b8adeb816cc1e397746b7157..0c0fe6e`；原九組其餘處置沿用前次獨立閱讀，不重新宣稱全面驗證。

這是同模型家族的唯讀獨立複查，不是跨供應商審查或使用者驗收。未修改檔案、stage、commit 或 ref，未操作後端 DB／PostgreSQL、模型、GPU或外部供應商。

## Files Reviewed（已審查檔案）

- `project_docs/story_openapi.py`：198–220，並核對修前函式
- `tests/test_story_scene_projection.py`：1–139
- `ui/tests/writingToolsRecovery.test.mjs`：1–338，完整比對修前版本
- `project_docs/writing_structure.py`：21–30、89–150
- `project_docs/doc_schema.py`：340–371
- `project_docs/story_estimates.py`：1–119
- `ui/src/writing/WritingOutline.jsx`：64–96
- `ui/src/writing/writingJournal.js`：1–64
- `docs/SPEC16A_R16_C1_CORRECTION.md`：1–86
- `docs/spec16a-r16-c1-verification.json`：1–207
- 原獨立報告、修前／後日誌、W2 trace 與預設前端結果

實際產品差異只有 `scenes_of_doc()`；`ui/src`、穩定結構實作及前端測試排程設定沒有改動。

## Critical（必須修正）

**本次限定差異未發現新的阻擋項。原 C1／P1 關閉，範圍是 `scenes_of_doc` 的正文與場名投影缺陷。**

### C1 關閉證據

`project_docs/story_openapi.py:205–215` 現在使用保留 hardBreak 的 `doc_text()`：

1. heading block 首行作場名。
2. 其餘文字放回正文，再接後續 blocks。
3. 不修改文件、block 邊界或穩定鍵。

親跑確認：

- heading／paragraph 同 block 的正文均保留，場名為 `Scene 01: Room`，不混入動作／對白。
- 空行、尾端換行與後續 block 順序符合斷言。
- 段內 `Scene 99:` 保留為正文；legacy 與穩定結構均維持一場。
- 真正呼叫 JS `persistStartHandoff`，捕捉實際 `script/ops` node，再交給真 Python `scenes_of_doc`／`beat_plans`。不是複製 helper 或 parser。
- 真 helper 的單 paragraph／CRLF 輸入，修後正文完整、auto 拍點為動作及對白兩拍。

另將 Git 中 **b5 原函式僅載入記憶體**，對同一個新純測試類執行反證：5 methods、5 failures、0 errors／skips，重現混合場名、空正文及一拍 fallback。未 checkout 或修改舊／新檔案，證明新增回歸確實能辨識原缺陷。

repeated A/B/A 的純認領／planner 防線亦通過；這不是實際 DB repeated-build 或 takes 保存驗證。

## W2 處置

**測試 readiness 與診斷缺口已改善；歷史並行失敗的完整根因仍未證實。**

獨立比對確認原有正文、私稿恢復、身份隔離、quota 失敗、CAS、禁止自動發布與 discard 斷言保留。未延長 timeout、增加盲目輪跑或改用序列排程。

`ui/tests/writingToolsRecovery.test.mjs:63–101` 的包裝會呼叫原 manager 方法及真 journal／IndexedDB transaction，沒有替換 recovery 演算法。新 readiness（`:80–87`）核對：

- 當前 episodeId、working resource、該集專用 docHash；
- 未 dispose、已 discover 的 actor／project／episode manager；
- manager scope 與目前工具 registry 狀態。

親跑具名 gate 得到：

| 階段 | 直接觀察 |
|---|---|
| `episode-2` 未放行 | control 已是 ep-2，但 docHash=null、無新 manager；舊 predicate=true，新 readiness=false |
| `catalog-after-save` 未放行 | manager=saved、conflict=false；PATCH 為 `[409,200]`，仍顯示父層舊錯誤 |
| `private-form` 未放行 | sequence=4、durableSequence=3、不可復原，沒有新 PATCH |
| form IDB 完成 | sequence=durableSequence=4、local_only；其後原文 reload／衝突恢復斷言通過 |

因此舊 `Shared version changed` **已實證可以只是父層殘留提示**，不能當成末段新 CAS 衝突。測試現在等 accepted lifecycle 完成與真正 Subject 控制項可操作後才開始新編輯，沒有用忽略資料斷言換取成功。

## Warnings（應追蹤）

### 1．穩定 outline 標題仍可能混入正文，勿擴大 C1 關閉聲明

`project_docs/writing_structure.py:123` 仍以 `node_text(heading)` 產生非 authored scene title；`ui/src/writing/WritingOutline.jsx:76` 直接顯示該值。

對相同 hardBreak 文件親跑可見：

- 修後 legacy 場名：`Scene 01: Room`
- 穩定結構 title：仍包含後續動作／對白

這是**既有、未被本次變更處理的標籤問題**，不再造成 C1 所指出的空正文／錯誤拍點投影，故不維持原 P1 阻擋。建議另行統一顯示標題投影並補 outline label 回歸，不藉此重設穩定身份或邊界；不能宣稱所有結構場名均已正規化。

### 2．歷史故障仍不能宣稱已根除

- C1 是劇本投影缺陷，不是歷史小說 ACK-loss 的根因證據。
- W2 已證實具體 harness 缺陷，但無法唯一歸因 b5 當輪失敗。
- b5 預設並行 **503/504** 原始結果仍有效。本次候選另有一次預設 **504/504** 通過證據，不能回寫舊結果或保證偶發永久消失。
- 父層舊錯誤提示的產品行為未修，仍可能誤導使用者。

## Suggestions（可考慮）

原始日誌繼續保留原 bytes／SHA256；來源與報告的 scoped whitespace 檢查，應與完整證據日誌的 whitespace 例外分開陳述。本次沒有裁剪或覆寫任何原始輸出。

## 親跑與僅讀結果

### 本次親跑

| 命令／檢查 | 結果 |
|---|---|
| branch／HEAD／status／index／main／差異檢查 | 符合指定候選，結束後仍乾淨 |
| `python -B -X utf8 -m unittest discover -s tests -p test_story_scene_projection.py -v` | **5/5 通過** |
| `python -B -X utf8 -m unittest discover -s tests -p test_story_openapi.py -k StoryPureTests -v` | **14/14 通過** |
| `python -B -X utf8 -m unittest discover -s tests -p test_story_estimates.py -k PlannerPureTests -v` | **4/4 通過** |
| `node --test ui/tests/writingToolsRecovery.test.mjs ui/tests/storyStartRecovery.browser.test.mjs ui/tests/writingStartHandoff.test.mjs ui/tests/storyHostStrictMode.test.mjs` | **23/23 通過** |
| 記憶體載入 b5 原函式的反證 | 如預期產生 **5 failures**；不計為修後通過 |
| 收據 SHA256 核對 | **25/25 吻合**，含新檔／日誌、原報告副本及舊十一份日誌 |
| W2 摘要對原始 targeted trace | 四階段的身分、狀態與 gate 記錄吻合 |
| 三份來源／測試及新報告／JSON scoped `diff --check` | 通過 |

本次正向測試共 **Python 23＋Node 23＝46 項通過**，零失敗／略過／取消。

### 僅讀，未重跑

- writer 的修前／修後、初次 W2 matcher 失敗及中間通過日誌。
- 新候選最終預設 `npm test --prefix ui`：**504/504**。
- b5 預設 **503/504**、單檔 **4/4**、序列 **504/504**。

真 Chromium 測試使用合成／記憶體 transport；瀏覽器 IndexedDB 是 checkpoint 證據，不是真產品 HTTP、PostgreSQL、登入憑證或 receipt 驗證。未跑完整後端、真 DB 旅程、wheel、build、模型或 GPU。

## Summary（總結）

原 C1 的 `scenes_of_doc` 正文／拍點回歸已由實際修前反證、修後純測試及真 helper 跨模組測試確認關閉，W2 也沒有以弱化斷言或序列排程掩蓋問題。限定本次差異評為 **OK with notes**；穩定 outline 標題、舊錯誤提示及兩項歷史故障歸因仍須保留界線，不替使用者驗收。