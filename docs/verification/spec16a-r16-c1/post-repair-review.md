# SPEC_16A 修後獨立複審

**總評：CHANGES REQUESTED**

工作 A 發現一項可重現的產品回歸：場次標題同段的 hardBreak 正文被排除於場次內容，且會命中 R16 劇本交接產生的文件。工作 B 的新增定向調查可評為 **OK with notes**；其測試不能證明歷史故障已修，預設並行套件也仍不能宣稱全綠。

本報告是同模型家族的全新唯讀**獨立閱讀**，不是跨供應商審查，也不替使用者驗收。

## 候選與範圍

實查符合指定條件：

- 分支：`fix/spec16a-r16-followup`
- HEAD：`b5ccca765acf1951b8adeb816cc1e397746b7157`
- `git status --short` 無輸出；暫存區為空。
- `main`：`aae5826f73e224824f5cb488e41e423e2eaaca1d`
- `aae5826..HEAD` 的產品路徑差異為空；僅十個測試／文件／日誌檔案改動。
- 工作 A 審查差異：`74a0a0b6188f193e65c37c489e6a9880d5946a0f..HEAD`。

未修改檔案、索引或 ref；未操作 PostgreSQL、DB fixture、產品模型、GPU、供應商或外網。未重跑完整套件或已知失敗檔案。

## Files Reviewed（已審查檔案）

主要程式與回歸：

- `ui/src/StoryWorld.jsx`：1–205、242–419
- `ui/src/App.jsx`：185–267、584–612、689–765
- `ui/src/storyHostModel.js`：1–37
- `ui/src/startModel.js`：1–90
- `ui/src/storyModel.js`：1–72
- `ui/src/writing/AuthoringWorkspace.jsx`：1–295
- `ui/src/writing/writingStartHandoff.js`：1–136
- `ui/src/writing/writingTransport.js`：1–43
- `ui/src/writing/writingOutlineRecovery.js`：1–193
- `ui/src/writing/writingToolControls.js`：1–42
- `project_docs/story_openapi.py`：168–219、472–657、1833–1845
- `project_docs/writing_structure.py`：1–140、191–230
- `project_docs/story_estimates.py`：1–119
- `ui/tests/storyStartRecovery.browser.test.mjs`：1–252
- `ui/tests/storyHostStrictMode.test.mjs`：1–186
- `ui/tests/writingStartHandoff.test.mjs`：1–243
- `ui/tests/storyHostModel.test.mjs`：1–76
- `tests/test_spec16a_host_browser.py`：1–182，**僅閱讀**
- `tests/test_writing_storyboard_regression.py`：1–149，**僅閱讀**

既有並行失敗的唯讀追蹤：

- `ui/tests/writingToolsRecovery.test.mjs`：1–256
- `ui/src/writing/WritingBible.jsx`：1–192
- `ui/src/writing/writingToolsRecovery.js`：1–165
- `ui/src/writing/writingToolsState.js`：1–58

已讀指定七份規範／審查／收據文件、`AGENTS.md`、設計與總體規範，並補讀相關 SPEC_16、SPEC_18 與歷史證據。舊審查結論沒有直接沿用為本次結論。

## Critical（必須修正）

### C1／P1：標題 block 內的 hardBreak 正文被當成標題，破壞劇本拆鏡

**位置：** `project_docs/story_openapi.py:204–210`  
**直接交接來源：** `ui/src/writing/writingStartHandoff.js:16–23`

**觸發：**

文件某個頂層 paragraph 以 `Scene 01:` 開頭，同一段 hardBreak 後包含動作或對白。例如：

```text
Scene 01: Room
@CAST-01 faces the lens, fighting back tears.
@CAST-02: "Tell me the truth."
```

這不是僅限人工構造：`plainDocument()` 正會把整份 R16 劇本存為**一個 paragraph 加 hardBreak**。空工作中稿可直接收到這個結構；非空稿則先存入私有另稿。

**原因與影響：**

`writing_structure.sections()` 將整個 block 分類成 heading；新 `scenes_of_doc()` 只從 `part['nodes']` 組正文，完全排除 heading block。`node_text(heading)` 又把段內換行攤平成標題文字。

親跑實際 `persistStartHandoff` → 真 `scenes_of_doc`／`beat_plans` 的無 DB 驗證，得到：

| 項目 | 修正前等價解析 | 目前解析 |
|---|---|---|
| 場次標題 | `Scene 01: Room` | 標題混入全部動作與對白 |
| `scene.content` | 動作及對白 | 空字串 |
| auto 拍點 | 2 | 1，退回使用整個標題 |

因此會遺失正文的拆鏡語意、混合對白與場名；`build_shots()` 的場景引用也只掃描 `scene.content`（`:613–614`）。**原稿沒有被刪除，但下游場次／分鏡投影已錯誤。**

**要求：**

保留 heading block 內的正文與換行，同時維持「段內 hardBreak 不另造穩定場次」的修正目的。補上：

1. 場次標題同段含 hardBreak 正文的回歸。
2. 實際 R16 helper 產生文件後，進入場次／拍點解析的跨模組回歸。

這是 V12 修正差異內的新回歸，**不是已證明的歷史小說 ACK-loss 根因**。

## 原九組發現逐項處置

| 原組別 | 本次判斷 | 獨立核對 |
|---|---|---|
| 1．資產捷徑／intent／asset focus 繞過 flush | 所指出路徑已修 | `StoryWorld:90–145,314` 統一經 `switchView()`，flush 成功才套用 view／選取。真 HTTP／PG 回歸僅讀，未親跑。 |
| 2．頁內導航漏掉工具私稿 | 所指出路徑已修 | 離開使用完整 `flush()`；`AuthoringWorkspace:103–110` 及工具 registry 保留私有 checkpoint，不把普通導航當成發布表單。 |
| 3．初次載入失敗不能離開 | 所指出機制已修 | 沒有已載稿件時普通 flush 可成功，`requireServer` 動作仍拒絕；錯誤畫面保留重試與下載。結構上限未提高。 |
| 4．來源跳轉落在角色牆 | 已修 | 宿主強制 script view，工作台完成或拒絕後回報 nonce 消費。 |
| 5．repeated A/B/A 認領及 hardBreak | **部分關閉，另有 C1 阻擋** | ambiguous 僅以穩定 scene 關係認領佔位，不補造 exact beat；detached 不認領，explicit rebuild 保留 ambiguous 鏡頭。但 hardBreak 修正漏掉標題 block 正文。 |
| 6．先刪原文／raw PUT 覆蓋非空稿 | 所指出資料保全機制已修 | 非破壞 peek、mutation 前 checkpoint、空來源 CAS、非空目的地轉另稿；ACK 及資源載入成功才消費 pending。helper 回歸親跑通過，仍有憑證及期限限制。 |
| 7．editor ref 競態／無 IDB 自動重試迴圈 | 所指出機制已移除 | 先持久化再載入，不靠 editor ref 注入；失敗需明確 Retry。本次親跑無 IndexedDB 案例通過。 |
| 8．來源 jump remount 重播／跨集 | 所指出路徑已修 | App 帶 episodeId、compare-and-clear nonce；宿主過濾他集來源，project／episode／actor keyed session 隔離。未親跑新增跨集 source-jump 旅程。 |
| 9．建立鏈未 actor-bound／無 abort | 所指出路徑已修 | settings、擷取、storyboards 及 polling 使用 bound request／signal；步驟間檢查 abort，無 actor 拒絕。Node abort 回歸親跑通過；真換 cookie 身分旅程僅讀。 |

**StrictMode 備註：** 穩定 request facade 配合 layout-effect session 建立／釋放，以及 outline `activate()`／`dispose()`，已由本次真 Chromium development StrictMode 親跑覆蓋。沒有因此擴大宣稱所有工具生命周期或真認證行為皆已驗證。

## 工作 B：R16 新調查的證據強度

新增測試沒有替換 `StoryWorld`、`AuthoringWorkspace` 或 React 生命周期；esbuild 使用 development React，真 `createRoot`／`StrictMode` 掛載，probe 確認 `setup→cleanup→setup`。

其主要聲明有相應斷言：

- readiness 檢查 episode、resource kind、精確 docHash；成功再檢查 `source:novel`、編輯器原文及 pending 消失，不只看上一個編輯器的可見文字。
- lost 案例先放行較新的 initial workspace GET，阻擋 ACK 後 workspace／source GET，確認 pending 保留到來源載入；最後放行舊 GET，確認不覆蓋來源。
- mutation 前檢查持久 checkpoint；重播比較完整 body，包含 `baseVersion`、`clientMutationId`；合成寫入數與 version 均維持 1。
- late 案例換至另一個真正掛載的 workspace，確認 episode／hash 及舊 signal aborted，再故意回傳晚到 ACK，原 pending 不被清掉。
- resource-failure、replay-failure 分別驗證 `done`、`source-save`，沒有把同一 Retry 畫面誤當同一失敗階段。

**證據界線清楚：**

- server／receipt 是 fixture sessionStorage 模擬，不是 PostgreSQL、真 cookie 授權或後端 receipt 實作。
- PUT 的重播身分主要是 body 中的 `clientMutationId`；trace 中 `Idempotency-Key=null` 的相等本身不是 receipt 證明。
- 五案例集中於小說來源，不代表所有 branch／initialize／credential 競態都有瀏覽器覆蓋。
- 七份新原始輸出、四份歷史日誌及新增測試來源的 SHA256 均親自核對吻合。

### 歷史根因仍未證實

舊失敗日誌 `spec16a-host-browser-final.log:547–591` 只足以確認第二次 reload 後等待 `source:novel` 逾時，實際停在 `working:main`。缺少同次 seedError、重播回應、資源 GET 與終態 checkpoint 關聯。

本輪注入 503 可證明不同失敗階段會產生相同症狀，**不能證明歷史曾回 503**。後續成功也不能證明歷史根因已根除；C1 同樣不能拿來解釋該次小說故障。

## Warnings（應追蹤）

### W1：預設並行失敗仍阻止「目前全綠」聲明

`docs/verification/spec16a-r16/r16-frontend-final.log:522–530` 明確記錄 **503/504、1 失敗**。單檔 4/4、序列 504/504 是不同排程證據，不能取代或消除原失敗。

這不會自動使新增測試／文件調查本身 blocking；但本候選整體另有 C1，仍需修改。

### W2：既有 Bible 測試存在具體 readiness／診斷風險，根因尚未定位

- `ui/tests/writingToolsRecovery.test.mjs:82,97–101` 的 readiness 只看累積 `statuses` 中工具狀態，沒有核對目前 episode／workspace 身分；切集後可先滿足舊 workspace 狀態。
- `:162–167` 從保存成功轉入新私稿後，只等待 UI 的 local-only 文案，未留下該次 sequence／durableSequence／IDB transaction trace。
- 畫面的 `Shared version changed` **不必然是末段新衝突**：前段測試故意製造 409；`writingToolsState.js:51–57` 將錯誤回報父層，但 `task.clear()` 只清工具自身狀態。父層 `AuthoringWorkspace.jsx:238` 可繼續顯示舊錯誤。

因此不能僅憑這張失敗畫面宣稱產品再次 CAS 衝突，也不能斷言只是並行資源壓力。

**下一步：** 先增加 episode／docHash／manager scope readiness，以及該失敗點的 sequence、durableSequence、IDB 開始／完成與請求關聯；再設計具名 gate 重現。不要僅延長 timeout 或盲目輪跑。本次沒有修改或重跑該檔。

## Suggestions（可考慮）

- `docs/verification/spec16a-r16/r16-directed-initial.log:15`、`r16-directed-diagnostic.log:16`、`r16-frontend-final.log:536` 等原始輸出帶 trailing whitespace，完整 `git diff --check` 親跑確實失敗。保留原 bytes／SHA256 是合理的；交付可分別記錄「原始證據例外」及「來源／報告 scoped whitespace 檢查通過」，不要裁剪原證據或宣稱完整檢查通過。

## 親跑與僅讀驗證

| 驗證 | 本次結果 |
|---|---|
| branch／HEAD／status／main／產品路徑 diff／暫存區 | 符合指定候選，乾淨 |
| `node --test ui/tests/storyStartRecovery.browser.test.mjs ui/tests/writingStartHandoff.test.mjs ui/tests/storyHostStrictMode.test.mjs` | **19/19 通過**；包含兩個真 Chromium 測試入口 |
| `node --test ui/tests/storyHostModel.test.mjs ui/tests/startModel.test.mjs ui/tests/storyStartHandOff.test.mjs ui/tests/shellShortcuts.test.mjs ui/tests/writingReviewAuthoringRecovery.test.mjs` | **34/34 通過** |
| 兩個無 DB inline 驗證：純場次解析、實際 handoff→解析／planner | **2/2 成功重現 C1**，不是產品通過證據 |
| 七份新日誌＋四份歷史日誌＋測試來源 SHA256 | **12/12 吻合** |
| 新測試／follow-up 文件及 JSON scoped `diff --check` | 通過 |
| 完整 `git diff --check aae5826..HEAD` | 失敗，原始日誌 whitespace |
| 預設並行 503/504、單檔 4/4、序列 504/504 | **僅讀既有輸出，未重跑** |

親跑 Node 共 **53 項通過，零失敗／略過／取消**。沒有新 build、完整後端、真 HTTP／PG、wheel、模型或 GPU 驗證。

## Summary（總結）

導航、交接保全、actor-bound 建立鏈與 StrictMode 的原指出機制大致已修，但 hardBreak 修正引入可直接命中 R16 劇本文件的正文／拆鏡回歸，故工作 A 與總評為 **CHANGES REQUESTED**。工作 B 誠實保留歷史根因未明與並行失敗，可給 **OK with notes**；仍保留 credential／24h receipt、整份文件 CAS、未覆蓋競態及真後端驗證邊界。