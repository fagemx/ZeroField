# SPEC_19 — 鏡頭生成台、採用即成片與「這一鏡在成片裡」右欄

> **狀態**：規格草案（2026-10-27），尚未實作。
> **來源**：使用者對 Higgsfield Cinema Studio 4.0 的實測截圖與功能拆解（生成框上下分區、Camera／Color palette／Lighting 範例牆、播放列上的小狀態圖示），以及使用者對 ZeroField 的回饋：「容易迷航」「提示詞太小」「分類進去沒有大範例，不知道選了什麼」「核准很佔流程，標記一個小圖示就夠」。
> **視覺參考**：重設計畫布「ZeroField 工作台重設計」第 10 區：`10` 生成台總覽、`10A` 鏡頭生成台 1920×1080（範例牆開啟）、`10B` 1280×720（平常狀態）、`10C` 採用與成片。畫板是草圖；與本文不一致時以本文為準（例如 10A 的時間碼批註不在本規格範圍，見 2.2）。
> **介面原則參考**：同一份拆解文件的「UI／UX 規格」分頁：一個輸入框加摘要 chip、從生成列向上展開的面板、每組都有 Auto 與 Reset all、依資料型態換選擇器、價格寫在主按鈕上、參照以彩色標籤寫在提示詞裡。本規格採用其中適用的部分（3.3）。
> **前置**：SPEC_15 三空間、SPEC_18 的出場（R2）、階梯（R4）、共用生成列（R8）已在 `main`。本規格修改它們，不另起爐灶。

---

## 0. 執行摘要與固定決策

現在要拍好一鏡，使用者要做三件分開的事：在「審片挑片」選中一支 Take（或套用管線提案），按「核准此鏡」把狀態改成 Approved，再到成片視窗確認它有沒有進片。三件事各有自己的按鈕，「核准此鏡」還佔掉整個畫面唯一的主按鈕。同時，生成一鏡需要的設定散在三處：畫風在本集對話框、攝影機與運鏡是右欄的文字欄、提示詞在 320px 右欄的最底下。

本規格做四件事：

1. **採用即成片。** Take 上的 ✓（或按 A）＝採用這支 Take，它就是成片裡的那一段。選中、核准、進成片合成一個動作。
2. **右欄改成「這一鏡在成片裡」。** 前後鏡與「接著看」、整集進度、Take 清單（✓ 在這裡）、剪裁、劇組提案。不再有核准大按鈕。
3. **鏡頭生成台。** 選一鏡，中間就是它的生成台：上半部看質感（目前的 Take，或點開的範例牆＋五顆質感鈕），下半部寫內容（最大的提示詞框＋一排小參數）。「生成」是整個畫面唯一的主按鈕。
4. **引用與接點。** 這是 Higgsfield 最弱的一段（見 1.3）：它的生成是資料夾裡互不相干的素材。我們讓一鏡引用另一鏡採用中的 Take（`@S02.end`＝S02 成片出點那一格），並記住引用關係；上游換了 Take，下游會被標出來。成片裡每個接點都檢查接不接得上；可以只巡接點，也可以先把候選 Take 放進成片試看再決定。

**固定決策：**

1. **狀態欄的值不新增、不改名。** 採用寫 `Approved`、重拍寫 `Retake`，其餘既有值照用（`project_docs/doc_schema.py` 第 17 行與 `ui/src/format.js` 不動）。所有原本看 `Approved` 的地方（實驗室片段進成片、升級閉源 hero、證據包、劇組主控台評分標籤）不用改，自動變成「看採用」。
2. **人只寫兩種狀態，其餘用推導。** 後端今天沒有任何地方自動寫「Pending Review」，本規格也不新增自動寫入：表格寫入會產生修訂、可能與協作衝突。「生成中」「有新 Take」由任務、候選與提案推導出來，只用於顯示與篩選（見 4.1）。
3. **已採用的鏡頭，新 Take 不得覆蓋格子。** 今天故事 API 生成完成時，只要那一列沒被改過就直接覆寫格子（`project_docs/story_openapi.py` 1083–1091 行），等於換掉成片裡的那一段。改成：狀態是 `Approved` 的鏡頭，新 Take 只進候選；未採用的鏡頭維持現狀（最新的 Take 放進格子，方便預覽）。
4. **成片 API 保持 RH 相容。** `POST /episodes/{id}/films` 不帶新參數時行為不變（格子裡的影片都進片）。工作室介面明確送 `selection: "adopted"`，只把已採用的鏡頭放進成片（見 4.2）。
5. **新的質感設定照剪裁的先例存。** 片型、色調、燈光沒有表格欄位；本集預設存在集數設定，鏡頭覆寫存在 `meta_<shotId>`（與 `story_trim` 同一個紀錄）。攝影機沿用既有的 `Optical Rig` 欄，運鏡改用提示詞內的 `#` 標籤。不改 `cinema-studio` 範本欄位（見 4.3）。
6. **每個選項存「寫進提示詞的具體畫面描述」，不只送名稱。** Higgsfield 的 A/B 實測顯示，只送「Noir」「Contre jour」這類標籤不會照做，只有色碼生效。我們的選項一律有可讀的英文描述句，色調另附色碼。
7. **一個畫面一顆主按鈕。** 片場的主按鈕是生成台的「生成」（淺色實心）。✓ 與 ↻ 是小圖示；`ui/tests/uiBudget.test.mjs` 與 `story-ui.test.mjs` 的預算不放寬。
8. **不自動花錢。** Comfy Router 卡永遠不因採用或任何連動而自動送出；本機開放權重卡的連動（採用首幀後接著生影片）由設定決定（見 7 待決 1）。
9. **雙語與狀態規範照舊。** 新文案只用 `en.json`／`zh-TW.json` 的語意鍵，兩邊的鍵與參數一致；英文為首次開啟預設。邏輯用 `normalizeStatus()`。
10. **影片解碼上限照 `docs/DESIGN_AND_DEV_GUIDELINES.md` §5.3。** 範例牆只播游標所在的那一格；「接著看」在同一個播放器依序播，不同時掛三支影片。
11. **選項名稱與範例不得使用真實人名、真實片名或他人素材**（同文件 §3.2）。範例媒體必須由本專案管線自製。
12. **引用在送出當下凍結。** `@S02.end` 在送出生成時解析成「哪支 Take、第幾秒」，記進新 Take 的來源。之後上游換 Take 或改剪裁，只會標示「上游已換」，不改寫已生成的 Take，也不自動重拍。
13. **接點分數只是資訊。** 和連戲評分一樣，不擋採用、不擋匯出。

### 0.1 最終交付的三句話

- 「我按一下 ✓，這支就進成片了；不用再找核准按鈕。」
- 「右邊看得到這一鏡在整部片裡的位置，可以接著前後鏡看，知道還差幾鏡。」
- 「選攝影機、色調、燈光時看得到大範例；提示詞是最大的框，按生成前就知道選了什麼。」
- 「下一鏡直接從上一鏡的最後一格接下去；上一鏡換了，我馬上知道哪幾鏡要重看，也知道哪幾個接點接不上。」

---

## 1. 現況盤點與陷阱

### 1.1 實際程式盤點

| 能力 | 現況（檔案） | 本規格處理 |
|---|---|---|
| 核准 | `SheetWorkspace.jsx:346` 的 `approve` 只呼叫 `setShotStatus(currentRow,'Approved')`；`A`／`R` 鍵在 332 行；`primaryShotAction()`（`studioModel.js:198`）把 Pending Review 對應到 `approve` | R1、R5 |
| 選中 Take（故事 API） | `PUT /shots/{id}/selected-video` → `select_candidate()`（`story_openapi.py:687`）：寫格子並重設剪裁 | R1 沿用 |
| 管線產出 | `flow_runner.py:1020–1028`：節點預設 `write_mode: "proposal"`，產出成為提案、任務停在 `awaiting_approval`；人套用（`project_assistant/service.py:339` `apply_proposal`）後才寫格子並推進下游 | R1 沿用 |
| 故事 API 產出 | `story_openapi.py:1081–1093`：存成候選（`candidate` 紀錄，沒有時間），列沒被改過就直接寫格子 | R2 |
| 候選清單 | `candidate_list()`（`story_openapi.py:658`）：修訂歷史＋目前格子＋候選紀錄，`selected` 以格子為準 | R4 |
| 成片 | `film_shots()`（`story_openapi.py:434`）：分鏡片場的鏡頭只要格子有影片就進片，實驗室片段要 `Approved`；`fill_previs` 用預演補 | R6 |
| 成片視窗 | `StudioShell.jsx:194` `FilmOverlay`：有影片播影片，否則播預演，都沒有就停 2 秒場記板；匯出時可勾「用預演補」 | R6 |
| 成片數字 | `episodeCounts()`（`StudioShell.jsx:61`）的 `filmed` 是「格子裡有影片的鏡數」，與核准無關 | R6 |
| 剪裁 | `story_trim.py`：存在 `meta_<shotId>`，綁定 Take 的網址；換 Take 就重設 | R3、R9 沿用先例 |
| 評分與運鏡吻合 | `GET /shots/{id}/grades`（`take_grader`）；`camera_fidelity` 在 Take 落地後背景計算 | R4 顯示 |
| 依賴 `Approved` 的功能 | `story_allocation.py:313`（升級 hero）、`take_bundle.py:22`（證據包）、`agent_console_service.py:481`（評分標籤）、`film_shots`（實驗室片段） | 不改，自動接上 |
| 鏡頭右欄 | `SheetWorkspace.jsx:341–367`：狀態、缺圖、階梯 `MediaLadder`、主按鈕、`ShotProposals`、`ShotBindings`（出場）、`shotControls`（狀態下拉、比較版本、上傳替換、重拍、在管線開啟、請代理修改、各文字欄與預設片語） | R3 |
| 片場工具列 | `SheetWorkspace.jsx:373`：網格、3D、審片、並排、表格、畫布、看板七顆檢視按鈕＋搜尋＋狀態篩選＋欄位＋列＋讓劇組填寫；畫廊另有封面／分組列 | R7 |
| 攝影機與運鏡預設 | `studioModel.js:5–6` 的 `OPTICAL_PRESETS`（5 組文字）、`MOTION_PRESETS`（9 組文字），以片語標籤插進文字欄；沒有範例圖 | R8 |
| 提示詞編譯 | `context_compiler.py:342–349`：讀 `Optical Rig`、`Camera Motion`、`Mode`、`Action & Audio Prompt` 欄組成 `Optical Rig: … Camera Movement: …`；靜態圖只留鏡頭感 | R10 |
| 畫風 | `story_openapi.py:48` `STYLES` 四種＋樣張 SVG；集數設定只有 `aspectRatio`、`stylePresetId`（1302 行） | R11 |
| 共用生成列 | `generation/GenerationBar.jsx`：工作流程、比例、解析度、預估、生成；SPEC_18 決定鏡頭上「第一版唯讀」 | R9 |
| 鏡頭生成選項 | `GET /shots/{id}/generation-options`（`story_generation_options.describe`）已支援鏡頭 | R9 |

### 1.2 必須在實作前理解的陷阱

**A. 兩條生成路徑的產出長得不一樣。** 故事 API 的產出是候選紀錄（可能已寫進格子）；管線的產出是待套用的提案。Take 清單必須合併兩者，而 ✓ 的實作也不同：候選走 `select_candidate`，提案走 `apply_proposal`。兩者之後都要寫狀態 `Approved`，而且必須在同一個交易裡完成，不能只成功一半。實作前確認 `apply_proposal` 不在內部提交交易；若會提交，改成可傳入外部交易，或把狀態寫入併進同一個表格編輯。

**B. 採用要走表格的提交規則。** 格子與狀態都在協作表格裡，有鎖與修訂（SPEC_18 §1.3 B）。後端的採用端點用 `mutate_row` 一次寫兩格（媒體欄＋狀態欄），它會鎖住整個分頁再寫，所以兩格一定一起落地；但它沒有「列被別人改過」的檢查，後寫的覆蓋先寫的，與現有挑片相同。前端送出前要確認沒有未提交的編輯（沿用 `dirty` 判斷），送出後重新載入那一列，不在前端自己改格子。

**C. 「有新 Take」需要時間。** 候選紀錄今天沒有建立時間。新寫入的候選要加 `createdAt`；採用時在 `meta_<shotId>` 記 `adoption: {url, at, by}`。舊候選沒有時間，一律視為比採用早；舊的 `Approved` 鏡頭沒有 `adoption` 紀錄，視為「在不明時間採用了格子裡那支」。這樣不需要資料遷移。

**D. 已採用就不覆蓋，但未採用照舊覆蓋。** 只改 `story_openapi.py:1086` 的條件：多加「狀態不是 Approved」。`test_story_openapi.py` 裡期待 `selected: True` 的案例，要補一個已採用的對照案例，不能直接把舊斷言改掉。

**E. 成片 API 是 RH 相容介面。** `film_shots` 被 `POST /episodes/{id}/films` 使用，外部用戶端照 RunningHub 的語意送 `{}` 或 `{fillPrevis: true}`。新行為只在明確帶 `selection: "adopted"` 時生效。

**F. `#` 已經被造型代碼用了。** `assetReferences()` 接受 `@CAST-01#night` 這種寫法（`#` 前面是英數字）。運鏡標籤只認前面是空白或行首（`。#pan`、`]#pan` 都不算）、後面不接 ASCII 英數字、`_` 或 `-`（`#push-inX` 不算），而且是目錄裡的代號。這樣也避開 Python 與 JavaScript 對 `\w` 認定不同的問題；前後端必須用同一套規則（實作見 `project_docs/story_look.py` 的 `move_tokens()`）。不認得的 `#xxx` 保留原文，不畫成標籤，也不丟掉。`#auto` 是認得的標籤：展開成空字串，並讓 `Camera Movement` 那一行消失（交給模型決定）。

**G. 運鏡在提示詞裡有位置。** `#push-in` 放在哪一段時間碼，就代表那一段發生。編譯時就地展開成描述句，不能像 `PUT /shots/{id}/assets` 那樣把標籤全搬到句尾。

**H. 兩條路徑要編出同一段提示詞。** 故事 API 與管線最後都經過 `context_compiler`。新的質感文字必須由同一個函式產生（`project_docs/story_look.py` 的 `compile_look()`），由 flow_runner 建立任務來源時、以及故事 API 建立 job 時各自放進 `look` 欄位，context_compiler 只負責拼接。實作前確認故事 API 的 job 確實經過 context_compiler；若不是，在 job 建立處直接附上編好的文字。

**I. 「接著看」不能同時解碼三支影片。** 在主播放器依序播前一鏡、這一鏡、後一鏡，`onEnded` 換下一支；每支照它的剪裁播。

**J. 首幀與影片是兩種 Take。** 首幀的 ✓ 只選中首幀，不改鏡頭狀態；只有影片的 ✓ 會寫 `Approved`。

**K. 待套用的提案不能用「選中」繞過。** `writing_impact.record_candidate_receipt()` 刻意把管線、競速的待審產出存成 receipt 而不是候選，因為經由 `selected-video` 選中會繞過 M8 的勝出閘門。採用提案一律走 `apply_proposal`；Take 清單可以顯示 receipt，但它的 ✓ 呼叫的是提案路徑，不是 `select_candidate`。

**L. 引用要能重現。** `@S02.end` 解析時要記下 Take 的網址與秒數（出點，沒有剪裁就是片長減一格），新 Take 的來源與成片的 `segments` 都存這份快照。只存「S02」會讓之後無法判斷是否過期。`media_prep` 的 `extract_frame` 目前只從同一列的來源影片抽格（`timestamp_sec`），要加「指定影片網址」的參數，且只接受本專案的資產網址。

**M. 接點檢查要排隊在生成後面。** 接點檢查用連戲監督的視覺模型，和現有評分一樣要等 ComfyUI 佇列清空、先釋放模型（`take_grader` 的 GPU 交接），不能插隊打斷渲染。

### 1.3 Higgsfield 在「多 Take → 引用 → 成片」這一段的弱點

依同一份拆解文件第一頁（專案、檢視器、Extend、Trim、Publish 的實測）：

| Higgsfield 的做法 | 問題 | ZeroField 怎麼做（本規格） |
|---|---|---|
| 專案是資料夾裡的素材瀑布流；每次生成都是一個獨立素材 | 沒有「鏡頭序列」，也沒有「這支是 S03 的第幾個 Take」 | 鏡頭是序列裡的單位，Take 掛在鏡頭底下（既有），右欄看得到前後鏡（R3） |
| 選片靠收藏或搬資料夾 | 看不出哪支在成片裡 | ✓ 採用＝在成片裡（R1） |
| 一支 4.0 的生成裡由模型自己切成數個鏡頭；要改其中一鏡用 Edit | 切點的位置與數量由模型決定，跟整部片的節奏無關 | 一鏡一個機位（SPEC_18 固定決策 6），切點就是鏡頭邊界 |
| Info 的「Reference」把影片加成參考素材；「Recreate」用同設定重做 | 參考是一次性複製，不記得來自哪裡；上游那支換掉，下游不知道 | 引用另一鏡採用中的 Take，送出時凍結並記住；上游換了就標「上游已換」（R15、R16） |
| 要接上一鏡只能 Extend（同一支往前或往後長）或手動截圖當參考 | 換角度的下一鏡沒有現成的「上一鏡最後一格」可用 | `@S02.end` 一鍵引用上一鏡的出點畫面，當首幀（接續動作）或當參考（同場換角度）（R15） |
| Trim 存成新素材；Publish 是把專案快照放到社群 | Cinema Studio 裡沒有把多支生成串成片、檢查接點、匯出成片的地方（我們的拆解中沒看到） | 成片＝採用的 Take＋剪裁（既有＋R6）；每個接點檢查接不接得上（R17）；只巡接點（R18）；把候選放進成片試看（R19） |

---

## 2. 範圍與非目標

### 2.1 交付範圍

| 編號 | 包 | 功能 | 完成定義 |
|---|---|---|---|
| R1 | A | 採用動作 | Take 上的 ✓、播放列的 ✓、`A` 鍵都呼叫同一個採用端點；候選與管線提案都能採用；一次交易寫媒體與 `Approved`，並記 `adoption` |
| R2 | A | 已採用不被覆蓋 | 已採用的鏡頭，故事 API 的新 Take 只進候選；未採用的照舊放進格子 |
| R3 | A | 右欄「這一鏡在成片裡」 | 取代現在的鏡頭右欄：標題與推導狀態、前後鏡與接著看、整集進度條、Take 清單、剪裁、劇組提案、`…` 選單（卡住、取消採用、在表格開啟）；沒有核准大按鈕 |
| R4 | A | Take 清單 | 合併候選與待套用的提案，新的在上；每支有縮圖、編號、新／採用中標記、連戲分數、運鏡吻合度（有就顯示）、✓；點一下在主播放器播 |
| R5 | A | 推導狀態與鍵盤 | `shotState()` 推導生成中／有新 Take／已採用／重拍中／卡住／未拍；`A` 採用正在播的 Take 並跳到下一個有新 Take 的鏡頭，`R` 寫 `Retake` 並把焦點放到生成台提示詞；清單篩選「待選」改用推導狀態 |
| R6 | A | 成片 | 頂欄與空間選單的成片數字改成已採用鏡數；成片視窗的補位選擇（最新 Take／預演／跳過）；匯出送 `selection: "adopted"` 與補位方式，片中標出補位的鏡頭 |
| R7 | B | 片場工具列收斂 | 七個檢視收成一個「檢視」下拉；選一鏡時預設是「生成台」，沒選鏡頭時是網格總覽；封面／分組收進檢視設定 |
| R8 | B | 鏡頭生成台：參考與攝影機 | 中間區上半部是目前的 Take（或首幀），質感鈕列先有「參考」「攝影機」兩顆；點開是範例牆（左側窄分類、右側 16:9 大範例、可多選並記順序）；攝影機的機身／鏡頭／光圈寫 `Optical Rig` 欄，運鏡寫成提示詞裡的 `#` 標籤 |
| R9 | B | 鏡頭生成台：提示詞與參數列 | 提示詞是畫面最大的輸入框；`@` 叫角色場景道具、`#` 叫運鏡，都畫成行內標籤；參數列一排：輸出（首幀／影片）、工作流程、秒數、解析度、聲音、支數（1–4）、預估、主按鈕「生成 N 支」；「看送出的完整提示詞」 |
| R10 | B | 運鏡標籤編譯 | `context_compiler` 就地展開 `#` 標籤為目錄裡的描述句；沒有標籤時沿用 `Camera Motion` 欄 |
| R11 | C | 片型、色調、燈光 | 三顆質感鈕與範例牆；本集預設（集數設定 `look`）＋鏡頭覆寫（`meta_<shotId>.look`）；鈕上標「本集」或「本鏡」，「回到本集」取消覆寫；編譯成具體描述與色碼 |
| R12 | C | 本集質感 | 故事與世界左欄底部的「16:9 · 畫風」改開「本集質感」：比例、畫風樣張與五顆質感鈕的本集預設 |
| R13 | C | 範例媒體 | 依 4.4 自製運鏡（3D 灰模渲染）、攝影機、色調、燈光、片型的範例，附產生紀錄 |
| R14 | C | OpenJutsu 用同一個生成台 | 參考鈕多一格「來源影片」，模式（重繪／換主體）放參數列；取代 OpenJutsu 列的文字欄操作 |
| R15 | D | 引用其他鏡頭的 Take | 提示詞與「參考」範例牆可以引用同一集其他鏡頭採用中的 Take：`@S02.end`（出點那一格）、`@S02.start`（入點那一格）；每個引用可選「當首幀（接續動作）」或「當參考（同場換角度）」；「參考」範例牆對同場的上一鏡顯示「接上一鏡」一鍵加入 |
| R16 | D | 來源關係與「上游已換」 | 每支新 Take 記下引用快照（鏡頭、Take 網址、秒數、用法）；上游改採用別支或改剪裁出點時，下游的 Take 標「上游已換」，進度條那一段加角標，右欄說明換了什麼並提供「用新的重拍」（只是開生成台，不自動送出） |
| R17 | D | 接點檢查 | 相鄰兩鏡都有採用時，抽前一支出點與後一支入點兩格，由連戲監督的視覺模型判斷接不接得上（人物位置、服裝、道具、光向、視線方向），結果是分數與問題清單；標在進度條的接縫上；跟現有自動評分同一個開關 |
| R18 | D | 只巡接點 | 成片視窗與右欄的「接著看」多一個模式：每個接縫前後各 1 秒連播，快速巡整集；每個接縫停留時顯示接點檢查結果 |
| R19 | D | 在成片裡試看 | Take 清單每支有「放進成片試看」：「接著看」與成片視窗暫時用它取代採用中的那支（只在這個瀏覽器、不寫入），角落標「試看中」；滿意就按 ✓ 採用，按 `Esc` 或換鏡就恢復 |

包 A 是前端加小幅後端，可以先上；包 B 只在 A 之後；包 D 需要 B 的「參考」範例牆與行內標籤，排在 B 之後；包 C 需要 GPU 產範例與選項命名確認，最後做。R19 只需要包 A 的資料，可以跟包 A 一起做。

### 2.2 明確不做

- 時間碼批註、畫面畫筆標註（10A 草圖中的批註區只顯示既有的列標註，不加時間碼）。另開規格。
- 新的狀態值、自動把狀態改成 Pending Review、自動重拍、自動改用閉源卡。
- 新的表格欄位或改 `cinema-studio` 範本（運鏡標籤寫在既有提示詞欄；片型／色調／燈光存 meta）。
- 文字提案（改劇本、改提示詞）的審核改成 ✓：它們是改內容，仍然是「套用／忽略」。
- Higgsfield 的影片後製工具（Extend、Reframe、Upscale、Relight、調色）。
- 以真實片名、導演或演員命名的選項與範例。
- 改動節奏台的剪輯行為；右欄只顯示剪裁並連過去。
- 同一鏡把兩支 Take 各剪一段拼起來（那是剪輯，屬節奏台的後續規格）。
- 上游換了就自動重拍下游；接點分數低就擋採用或擋匯出。
- 跨集引用（`@S02.end` 只在同一集內解析）。

---

## 3. 使用者流程與介面

### 3.1 採用與狀態

```text
送出生成 ──► 生成中 ──► Take 送到 ──► 有新 Take ──✓──► 已採用（在成片裡）
                                           ▲                │
                                           └── 又來新 Take ◄─┘  （舊的仍在成片裡）
已採用／任何狀態 ──↻──► 重拍中（寫 Retake，開生成台）──► 生成中 …
```

| 推導狀態 | 判斷（4.1） | 誰造成 | 顯示 |
|---|---|---|---|
| 生成中 | 這一列有在途的故事任務或管線任務 | 系統 | 藍點 |
| 有新 Take | 有比採用更新的候選或待套用提案；或未採用但有 Take | 系統 | 琥珀點＋數字 |
| 已採用 | 狀態 `Approved`，且沒有更新的 Take | 人：✓／`A` | 綠點 |
| 重拍中 | 狀態 `Retake`，且還沒有新 Take | 人：↻／`R` | 空心點 |
| 卡住 | 狀態 `Blocked` | 人：`…` 選單 | 紅點 |
| 未拍 | 沒有任何 Take | — | 灰點 |

- 取消採用：`…` 選單 → 狀態改回空白（不是 Pending Review），`adoption` 紀錄刪除；格子內容不動。
- 片場裡 `Approved` 一律顯示成「已採用／Adopted」；表格的狀態欄與其他頁面照舊顯示「Approved」（見待決 2）。

### 3.2 右欄：這一鏡在成片裡（10A、10B）

```text
┌ S03 · 轉向圓頂            ● 新 Take 2  … ┐
│ 在成片裡  第 3／8 鏡          [▶ 接著看]  │
│ [S02 ✓ 5s] [S03 Take 2 4s] [S04 待選 4s]  │
│ ▮▮▮▮▮▮▯▯  已採用 4／8 · 35 秒             │
│ Take 3                       [↻ 再拍 R]   │
│ [縮圖] Take 3  新  連戲 72 · 運鏡 91%  ( ✓ )│
│ [縮圖] Take 2  採用中 · 連戲 58        (●✓)│
│ [縮圖] Take 1  連戲 35                 ( ✓ )│
│ ✂ 成片用 0.4–3.8 秒  3.4／4.0   節奏台 ↗  │
│ 劇組提案（既有 ShotProposals）            │
│ 標註（既有列標註，最多 2 則＋全部）        │
└───────────────────────────────────────────┘
```

- **在成片裡**：前、這、後三鏡的縮圖。縮圖依序用：採用中的 Take → 格子裡最新的 Take → 預演 → 空白。標籤寫鏡號、狀態與秒數。「接著看」在主播放器依序播三鏡，每支照剪裁。
- **進度條**：每鏡一段，寬度＝成片秒數（已採用照剪裁，否則用規劃秒數）；顏色依推導狀態；目前這鏡加外框；點一段就跳到那一鏡。下方一行：已採用 x／y、總長 z 秒。
- **Take 清單**：顯示目前輸出種類的 Take。生成台的輸出是「影片」時列影片；切到「首幀」時列首幀候選（✓ 只選首幀，不改狀態）。點列在主播放器播；✓ 採用。標題列有「再拍 (R)」。
- **剪裁**：沒有剪裁時寫「整支 4.0 秒」。按「節奏台」跳到節奏台並選中這一鏡。
- **出場**（SPEC_18 R2）：包 A 期間收在右欄最底下、預設收合；包 B 上線後移到生成台的「參考」鈕，右欄不再顯示。
- **拿掉**：核准大按鈕、狀態下拉（改到 `…` 選單）、「比較版本」「上傳替換」「在管線中開啟」「請代理修改」移到 `…` 選單；各文字欄的編輯移到生成台（包 B 之前暫留在 `…` →「在表格開啟」）。

### 3.3 鏡頭生成台（10A、10B）

```text
┌ S03 · 轉向圓頂  第 2 場 · 4 秒 · 成片用 Take 2          [檢視：生成台 ▾] ┐
│ ┌ 上：目前的 Take（播放列：Take 3 新 | Take 2 ✓ | Take 1   ( ✓ ) ( ↻ )）┐ │
│ │   點質感鈕時，這裡換成範例牆：左側窄分類，右側 16:9 大範例           │ │
│ └───────────────────────────────────────────────────────────────────┘ │
│ [參考 本鏡 3 個·1 缺圖][片型 本集 …][攝影機 本鏡 35mm·變形·慢推][色調][燈光] │
│ ┌ 提示詞 · 依時間寫                              看送出的完整提示詞 ▸ ┐ │
│ │ [0–1.5s] @Kael 站在 @天文台 控制台前……                               │ │
│ │ [1.5–3s] 他把 @盤式錄音機 轉向敞開的圓頂…… #慢推                     │ │
│ │ (+)(@)(#) | 影片 ▾ | LTX-2.5 影片 ▾ | 4 秒 | 1280×704 | 聲音 開 | −2 支+ │ │
│ │                                         約 40 秒（5 次）[▶ 生成 2 支]│ │
│ └──────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘
```

- **放在哪**：分鏡片場選了一鏡，中間區就是它的生成台（R7 的預設檢視）；沒選鏡頭是網格總覽。
- **質感鈕**：縮圖＋分類名＋「本集／本鏡」＋目前值（太長就截斷，滑過看全名）。包 B 只有「參考」「攝影機」；包 C 補上「片型」「色調」「燈光」。
- **範例牆**：蓋在上半部，`×` 或 `Esc` 關閉回到 Take。左側窄分類（攝影機：機身與鏡頭／運鏡）；右側網格 16:9 範例（≥1600px 寬四欄，1280 三欄），選中有琥珀外框；運鏡可多選，右上角顯示順序數字，左側列出「這一鏡依序」。範例預設只顯示靜態封面，游標停留才播。
- **參考的範例牆**：這一鏡的角色、場景、道具（主圖就是範例）；可換造型、移除、加入、補參考圖。行為與寫回規則照 SPEC_18 R2（逐字保留句子）。
- **攝影機**：機身與鏡頭（含光圈）選一個，寫進 `Optical Rig` 欄（寫入目錄裡的描述文字）；運鏡點一下＝在提示詞游標處插入 `#代號` 標籤。另有「在 3D 排鏡台調」連到 3D 片場；有預演時，鈕上顯示「依預演」。
- **提示詞**：`Action & Audio Prompt` 欄的內容，就地編輯（不需要「編輯」按鈕），`Enter` 換行、`Ctrl+Enter` 存檔；改過未存時參數列的主按鈕變成「儲存並生成」。`@`、`#` 都畫成行內標籤；找不到的 `@代碼` 照 SPEC_18 R3 畫成警示標籤。
- **參數列**：輸出（首幀／影片，各帶「已有」勾）、工作流程、秒數、解析度、聲音、支數（1–4）、預估（SPEC_18 的規則：依據次數、少於 3 次寫「時間未知」；Router 卡顯示報價並註明非價格鎖定）、主按鈕。窄於 960px 時「解析度」「聲音」收進「更多」，主按鈕永遠在最右。
- **看送出的完整提示詞**：展開唯讀的編譯結果（4.2 `prompt-previews`），讓使用者確認標籤展開成什麼。
- **借自 UI／UX 規格分頁的規則：**
  - 範例牆從質感鈕列正上方展開，寬度與生成台相同；質感鈕列與提示詞留在原位。點另一顆鈕是直接切換內容，不用先關。
  - 每組設定的第一個選項是 Auto（以抽象紋理圖表示，不是文字）；什麼都不設也能生成。範例牆右上有 Reset all；子分類有改過的，旁邊有小點。
  - 選擇器依資料型態：機身、鏡頭、光圈用三欄（每欄一個選中項，上下可捲）；片型的類型與節奏用左右輪播；年代用刻度；運鏡、色調、燈光用圖卡格線加搜尋與排序。
  - 選了立即生效，沒有「確定」鈕。
  - 主按鈕上直接寫預估：「生成 2 支 · 約 40 秒」；Router 卡寫報價。
  - 強調色照我們的 6C 規則：淺色實心只給主按鈕，琥珀只標選取與焦點（不照搬 Higgsfield 的螢光綠）。

### 3.4 成片視窗（10C）

- 標題列摘要：「已採用 x／y 鏡」，另寫「n 鏡有 Take 但未採用」。
- 補位選擇（播放用）：「空位用：最新 Take｜預演｜跳過」，預設「最新 Take」，讓整集隨時能從頭看到尾。補位的鏡頭在畫面角落標「未採用」或「預演」。
- 匯出：送 `selection: "adopted"`＋補位方式（預設「預演」；「最新 Take」也可選），補位的段落在匯出的場記清單裡標明。

### 3.5 鍵盤

| 鍵 | 作用 | 條件 |
|---|---|---|
| `A` | 採用正在主播放器播的 Take（沒有在播就採用最新的），再跳到下一個「有新 Take」的鏡頭；沒有就停在原鏡 | 可寫入、沒有未提交編輯、焦點不在輸入框 |
| `R` | 寫 `Retake`，焦點移到生成台提示詞；連戲評分有改寫建議時，詢問是否帶入 | 同上 |
| `↑`／`↓` | 換鏡（不變） | 同上 |
| `Esc` | 關閉範例牆 | 範例牆開啟時 |

### 3.6 主按鈕

| 畫面 | 唯一主按鈕 | 本規格拿掉的 |
|---|---|---|
| 分鏡片場（選了一鏡） | 生成台「生成 N 支」（或「儲存並生成」） | 「核准此鏡」「下一鏡」「拍攝此鏡」「重拍此鏡」主按鈕 |
| 分鏡片場（網格總覽） | 無主按鈕；多選後底部動作列「全部採用最新 Take」為外框按鈕 | — |
| 成片視窗 | 「匯出成片」（不變） | — |
| 本集質感（包 C） | 「套用到本集」 | 「更新分鏡」對話框裡的畫風選擇 |

`primaryShotAction()` 不再決定右欄按鈕；缺參考圖改成「參考」鈕上的紅點與範例牆裡的「補參考圖」。

### 3.7 引用與接點（包 D）

```text
提示詞：[0–1s] 接續 @S02.end（首幀），@Kael 轉身看向窗外……

參考範例牆
┌ 角色 場景 道具 │ 其他鏡頭 ┐
│ 同場的上一鏡：S02 · Take 2（已採用）                       │
│ [S02 出點畫面 3.8s]  [接上一鏡：當首幀]  [當參考]           │
│ 其他鏡頭：S01 · S04 …（只列有採用的）                       │
└──────────────────────────────────────────────────────────────┘

右欄（這一鏡在成片裡）
│ 引用  S02 Take 2 @3.8s  當首幀   ⚠ 上游已換成 Take 3  [用新的重拍] │
│ 進度條 ▮▮|▮▮●▮▮|▮▮  接縫點：綠＝接得上、黃＝有問題、灰＝還沒查    │
```

- **引用標籤**：`@S02.end`、`@S02.start` 畫成帶縮圖的行內標籤（縮圖是那一格），點標籤可切「當首幀／當參考」、看是哪支 Take 第幾秒。被引用的鏡頭還沒採用時，標籤是警示樣式：「S02 還沒採用，會用最新的 Take」。
- **接上一鏡**：同一場、鏡號緊鄰的上一鏡有採用時，「參考」範例牆最上面一列就是它的出點畫面，一鍵加入為首幀並把 `@S02.end` 插在提示詞開頭。
- **上游已換**：右欄頂部多一行「引用」，列出這支採用中 Take 用過的引用；上游已換時顯示換成了什麼，並有「用新的重拍」（打開生成台，引用改指向新的採用，不自動送出）。進度條上那一段加黃色角標。
- **接縫點**：進度條相鄰兩段之間的小點。點一下：主播放器播接縫前後各 1 秒，右欄顯示問題清單（例如「S02 結尾錄音機在左手，S03 開頭在右手」）。
- **只巡接點**：「接著看」旁的切換（整段／只看接點），成片視窗同樣有。
- **在成片裡試看**：Take 列的「試看」圖示。試看中，播放器角落與進度條那一段標「試看」，`A` 會直接採用試看中的那支。


---

## 4. 資料與介面契約

### 4.1 推導狀態（前端純函式，`ui/src/takeModel.js`）

```js
shotState({status, adoption, takes, inFlight}) →
  'blocked' | 'generating' | 'new_take' | 'retake' | 'adopted' | 'empty'
// 優先順序：blocked > generating > new_take > retake > adopted > empty
// new_take：有「採用基準」時（狀態 Approved，或狀態 Retake 且有 adoption 紀錄），createdAt 晚於 adoption.at 的影片 Take 才算新；
//           沒有基準時（從沒採用過），每一支 Take 都算新
// 按 R 只寫 Retake 狀態，不刪 adoption；只有 DELETE /shots/{id}/adoption 會刪
```

- `takes` 來自 `GET /shots/{id}/videos`（候選）與這一列的待套用媒體提案（既有 `rowProposals()`），合併、去重（以網址）、依時間新到舊排序。
- `inFlight` 只用前端已知的在途任務（本頁送出的故事任務、`/flow/runs` 中這一列的執行），不新增輪詢端點。
- `SHOT_FILTERS.review` 改成 `shotState(...) === 'new_take'`，舊資料的 `Pending Review` 也算進去。

### 4.2 後端 API

| 方法與路徑 | 新／改 | 內容 |
|---|---|---|
| `POST /shots/{id}/adoptions` | 新 | body 三擇一：`{videoId}`（候選）、`{proposalId}`（待套用的管線提案）、`{imageId}`（首幀候選）。影片：一次交易內寫媒體欄與狀態 `Approved`，重設剪裁，記 `meta.adoption = {url, at, by}`；首幀：只寫首幀欄。回傳 shot view。錯誤：Take 不屬於這一列 404 `DRAMA_NOT_FOUND`；唯讀成員 409 `DRAMA_OPERATION_NOT_ALLOWED`；製作表沒有狀態欄 409 `DRAMA_STAGE_PRECONDITION`。同一分頁的寫入由 `mutate_row` 的分頁鎖排隊，後寫的覆蓋先寫的（與現有挑片相同，沒有樂觀鎖） |
| `DELETE /shots/{id}/adoption` | 新 | 狀態改回空白、刪除 `meta.adoption`；格子不動 |
| `GET /shots/{id}`（shot view） | 改 | 多 `adoption: {adopted, url, at, by} \| null`、`takeSummary: {total, newSinceAdoption}` |
| 故事任務完成（`story_openapi.py:1081–1093`） | 改 | 候選紀錄加 `createdAt`；狀態為 `Approved` 時不寫格子、`selected: false` |
| `POST /episodes/{id}/films` | 改 | 新增 `selection: "selected"（預設）\| "adopted"`、`fill: "previs" \| "latest" \| "skip"`；舊的 `fillPrevis: true` 等於 `fill: "previs"`；不帶新參數時行為與現在完全相同。回應的 film 紀錄多 `segments: [{shotId, source: "adopted"\|"latest"\|"previs"}]` |
| `POST /shots/{id}/video-generations`、`image-generations` | 改 | 收 `count`（1–4，預設 1），建立 `count` 個任務並回傳 task group；每支依既有 take 計數換 seed |
| `POST /shots/{id}/prompt-previews` | 新（包 B） | body 同生成請求，不排隊；回傳 `{compiledPrompt, references, look}`，必須呼叫與 worker 相同的編譯函式 |
| `PUT /episodes/{id}/settings` | 改（包 C） | 多收 `look: {genre, era, tempo, camera, palette, light}`，值為目錄代號；未知代號 400 |
| `PUT /shots/{id}/look` | 新（包 C） | `{palette?: id\|null, light?: id\|null, genre?: …}`：設定或（`null`）取消這一鏡的覆寫，存 `meta_<shotId>.look` |
| `GET /catalog/looks` | 新（包 C；運鏡與攝影機在包 B） | 目錄：`[{id, kind, labelKey, promptText, preview: {poster, clip?}, hex?: [...]}]` |
| 生成請求（`video-generations`、`image-generations`） | 改（包 D） | 後端掃提示詞的 `@鏡號.end`／`.start`，加上 body 的 `takeRefUses: {"S02.end": "first_frame" \| "reference"}`；解析成快照（4.5），存進 job 與新 Take 的來源 |
| `GET /shots/{id}`（shot view） | 改（包 D） | 多 `takeRefs: [{shotId, shotIndex, edge, takeUrl, at, use, stale, nowTakeUrl}]`（採用中那支 Take 的引用，`stale` 由現在的採用與剪裁比對得出） |
| `GET /episodes/{id}/cuts` | 新（包 D） | 每個相鄰鏡頭對：`{fromShotId, toShotId, fromTakeUrl, toTakeUrl, outAt, inAt, check: {state: "none"\|"queued"\|"done"\|"failed", score, issues[], frameSheetUrl}}`；任一邊換 Take 或改剪裁，舊的檢查視為過期（`state: "none"`） |
| `POST /episodes/{id}/cut-checks` | 新（包 D） | body `{pairs?: [[fromShotId, toShotId]]}`，不給就查所有過期的接點；排進 `take_grader` 的佇列（1.2 M），回傳排了幾個 |
| `POST /episodes/{id}/films` | 改（包 D） | `segments` 每段多 `takeUrl`、`in`、`out`、`takeRefs` 快照與接點檢查結果，匯出紀錄可以說明這一版成片的每一段從哪裡來 |

### 4.3 質感目錄與編譯

- 目錄檔：`project_docs/look_catalog.json`（隨套件發佈；範例媒體在 `ui/public/assets/look-samples/`）。
- 種類：`camera`（機身＋鏡頭＋光圈，寫 `Optical Rig`）、`move`（運鏡，`#` 標籤）、`genre`、`era`、`tempo`、`palette`（`hex` 最多 12 色，第一色為主色）、`light`。
- 每個選項：`id`（小寫連字號，同一個 kind 內唯一；每組第一項是 Auto，`promptText` 為空，例如 `auto-body`、`auto-lens`、`auto-aperture`、`auto`）、`labelKey`（i18n，一律在 `lookCatalog.<kind>.…` 底下，避免和按鈕文字的 `look.*` 衝突）、`promptText`（英文具體畫面描述，例：`light:window` → `soft daylight from a side window, one cool key, deep falloff on the far side of the face`）、`preview`。
- `compile_look(episode_look, shot_look)`（`project_docs/story_look.py`）：鏡頭覆寫優先，回傳 `{"film": "...", "color": "... palette #2E3A4A, #5B6F86 ...", "light": "..."}`。
- `context_compiler`：在 `Optical Rig`／`Camera Movement` 之後加 `Film: …`、`Color: …`、`Lighting: …` 三行（有值才加）；靜態圖（`image_gen`）保留色調與燈光，不加運鏡。`#` 標籤就地展開成 `promptText`，展開後的句子仍維持原段落順序。
- 自訂調色盤與自訂燈位不在本規格（Higgsfield 有；先做預設）。

### 4.4 範例媒體（包 C，運鏡在包 B）

| 種類 | 產生方式 | 規格 |
|---|---|---|
| 運鏡 | 3D 排鏡台用同一個灰模場景與示範演員，逐一套運鏡，用既有的 WebCodecs 匯出 | 2 秒循環、480×270、MP4（H.264、`+faststart`）≤ 400 KB；封面 WebP ≤ 60 KB |
| 攝影機 | 固定測試場景（原創角色與天文台），FLUX 3 Klein 每個選項一張 | 640×360 WebP ≤ 80 KB |
| 片型、色調、燈光 | 同上；色調另附色票條 | 同上 |

- 每張範例在 `look-samples/manifest.json` 記錄工作流程、模型、seed、提示詞、產生日期，以及授權（CC0、本專案自製）。
- 範例內容不得出現真實人物、品牌或文字；選項名稱為原創描述（例：「暮色寓言」不對應任何真實作品）。

### 4.5 引用的解析與凍結（包 D）

- 語法：`(?<![\w@:#-])@([A-Za-z]?\d{1,3}[A-Za-z]?)\.(start|end)\b`，比對同一集的 `shotIndex`（不分大小寫）。和素材代碼（`CAST-`、`SET-`、`LOC-`、`PROP-`、`STYLE-`）不會撞：素材代碼一定有連字號且沒有 `.start`／`.end`。找不到的鏡號畫成警示標籤，送出時回 400 `DRAMA_VALIDATION_FAILED` 並列出找不到的代號。
- 解析：被引用的鏡頭有採用時用採用中的 Take；沒有採用時用格子裡最新的 Take，快照標 `adopted: false`；兩者都沒有就回 409 `DRAMA_STAGE_PRECONDITION`。秒數：`.end` 是剪裁出點（沒有剪裁時是片長減一格）、`.start` 是剪裁入點。
- 抽格：用 `media_prep` 的 `extract_frame`，新增 `source_url`（只接受本專案 `/projects/api/{slug}/assets/pa_…` 資產）。抽出的圖存成資產，並記在快照裡，所以縮圖與實際送進模型的是同一張。
- 用法：`first_frame` 時，抽出的圖成為這次生成的 `first_frame` 角色（覆蓋首幀欄）；`reference` 時加進參考圖，排在角色與場景之後。`context_compiler` 在提示詞裡把標籤換成一句描述（例：`Continue directly from the final frame of shot S02.`／`Match the setting and lighting of shot S02.`）。
- 凍結：快照 `{shotId, edge, takeUrl, at, frameUrl, use, adopted}` 存進新 Take 的來源（延伸 `storyProvenance`，同時存在候選紀錄與 receipt）。`stale` 判斷：快照的 `takeUrl` 不是被引用鏡頭現在的採用，或 `at` 和現在的剪裁不同。

---

## 5. 要改的檔案

### 5.1 前端（`ui/src/`）

| 檔案 | 包 | 改什麼 |
|---|---|---|
| `takeModel.js`（新） | A | `shotState()`、`mergeTakes()`、`filmNeighbors()`、`filmSegments()`、`nextNewTake()`；純函式 |
| `ShotFilmPanel.jsx`（新） | A | 右欄：標題與 `…` 選單、在成片裡、進度條、Take 清單、剪裁、劇組提案、標註摘要 |
| `SheetWorkspace.jsx` | A、B | `shotDetail` 換成 `ShotFilmPanel`；`stageKeys` 的 `A`／`R` 改呼叫採用與重拍；拿掉 `primaryShotAction` 主按鈕；工具列七顆檢視收成下拉（B） |
| `studioModel.js` | A | `SHOT_FILTERS.review` 改用推導狀態；`primaryShotAction` 只留給尚未改版的畫面或刪除（依呼叫點） |
| `StudioShell.jsx` | A | `episodeCounts()` 多 `adopted`；頂欄與 `SpaceMenu` 的成片數字改用 `adopted`；`FilmOverlay` 補位選擇、匯出參數、片段標記 |
| `ShotStage.jsx` | A | `MediaLadder` 從右欄移除；包 B 時改成參數列的輸出切換 |
| `composer/ShotComposer.jsx`（新） | B | 生成台：上半部播放器／範例牆、質感鈕列、提示詞、參數列 |
| `composer/LookTiles.jsx`、`ExampleWall.jsx`、`PromptComposer.jsx`、`lookModel.js`（新） | B、C | 質感鈕、範例牆、`@`／`#` 行內標籤編輯器、目錄與覆寫的純函式 |
| `generation/GenerationBar.jsx`、`generationModel.js` | B | 支援 `kind="shot"`、輸出切換、支數、主按鈕樣式（片場用淺色主按鈕） |
| `StoryWorld.jsx` 或左欄「16:9 · 畫風」入口 | C | 開「本集質感」 |
| `takeModel.js`、`ShotFilmPanel.jsx` | D | 引用行與「上游已換」、接縫點、只巡接點、試看狀態（試看是畫面上的暫時狀態，不寫入任何地方） |
| `composer/PromptComposer.jsx`、`ExampleWall.jsx` | D | `@鏡號.end`／`.start` 標籤、首幀／參考切換、「其他鏡頭」分類與「接上一鏡」 |
| `StudioShell.jsx`（`FilmOverlay`） | D | 只巡接點模式、試看中的段落、接縫結果 |
| `i18n/locales/en.json`、`zh-TW.json` | A–C | 新語意鍵（兩邊一致）：`take.adopt`（Adopt／採用）、`take.adopted`（Adopted／已採用）、`take.new`（New／新）、`take.retake`（Retake／再拍）、`film.inTheCut`（In the cut／在成片裡）、`film.playAround`（Play around／接著看）、`film.fill_latest`、`film.fill_previs`、`film.fill_skip`、`look.references`、`look.filmSetup`、`look.camera`、`look.palette`、`look.lighting`、`look.episode`（Episode／本集）、`look.shot`（This shot／本鏡）、`composer.promptPreview` 等 |
| `studio-shell.css` | A–C | 右欄、Take 列、進度條、生成台、範例牆樣式；沿用 6C 午夜藍灰變數 |

### 5.2 後端

| 檔案 | 包 | 改什麼 |
|---|---|---|
| `project_docs/story_adoption.py`（新） | A | `adopt()`、`unadopt()`、`adoption_view()`；候選走 `select_candidate` 的寫法、提案走 `apply_proposal`，與狀態寫入同一交易 |
| `project_docs/story_openapi.py` | A、B | 路由 `adoptions`／`adoption`／`prompt-previews`；`shot_view` 加 `adoption`、`takeSummary`；任務完成時已採用不覆寫、候選加 `createdAt`；`film_shots` 與 `films` 的 `selection`／`fill`；生成 `count` |
| `project_assistant/service.py` | A | 若 `apply_proposal` 會自行提交交易，加可傳入外部交易的參數（不改既有呼叫行為） |
| `project_docs/story_look.py`（新） | B、C | 目錄載入與驗證、`compile_look()`、集數 `look`、鏡頭覆寫 |
| `project_docs/look_catalog.json`（新） | B、C | 攝影機、運鏡（B）；片型、色調、燈光（C） |
| `project_assistant/studio/context_compiler.py` | B、C | `#` 標籤就地展開；`Film`／`Color`／`Lighting` 三行 |
| `project_assistant/flow_runner.py` | C | 建立任務來源時附 `look`（`compile_look()` 的結果） |
| `project_docs/story_take_refs.py`（新） | D | 引用語法、解析成快照、`stale` 判斷、接點清單 `cuts()` |
| `project_assistant/studio/media_prep.py` | D | `extract_frame` 加 `source_url`（限本專案資產） |
| `project_assistant/take_grader.py` | D | 第二套題目「接點」：兩格並排（前一鏡出點、後一鏡入點），回傳分數與問題；沿用佇列與 GPU 交接；結果存 `cut_check` 紀錄 |
| `project_docs/writing_impact.py` | D | `storyProvenance` 多 `takeRefs` 欄位；`candidate_evidence` 的相等判斷把它算進去 |
| `project_docs/story_trim.py` | — | 不改；採用沿用 `reset()` |
| `project_docs/doc_schema.py`、`ui/src/format.js` | — | 不改狀態清單 |

### 5.3 測試

| 檔案 | 包 | 涵蓋 |
|---|---|---|
| `tests/test_story_adoption.py`（新，需 `OPENBENCH_TEST_DB_URI`） | A | 候選採用、提案採用、首幀採用不改狀態、交易一半失敗不留痕、唯讀 409、他列 Take 404、沒有狀態欄 409、取消採用 |
| `tests/test_story_openapi.py` | A | 已採用不覆寫（新案例）、未採用照舊覆寫（保留舊斷言）、候選 `createdAt`、`films` 新舊參數相容 |
| `tests/test_story_look.py`（新） | B、C | 目錄驗證、未知代號 400、覆寫優先、`compile_look` 輸出、色碼格式 |
| `tests/test_studio_worker.py` | B、C | `#` 標籤就地展開、`@CAST-01#night` 不被當運鏡、未知 `#xxx` 保留、`Film`／`Color`／`Lighting` 三行、靜態圖不加運鏡 |
| `ui/tests/takeModel.test.mjs`（新） | A | 推導狀態優先順序、舊資料（無 `createdAt`、無 `adoption`）、合併去重、`nextNewTake` 循環 |
| `ui/tests/lookModel.test.mjs`（新） | B、C | 本集／本鏡判斷、回到本集、`#` 標籤解析與插入位置 |
| `ui/tests/uiBudget.test.mjs`、`story-ui.test.mjs` | A、B | 一畫面一顆主按鈕、頂欄控制數不增加；片場工具列控制數減少 |
| `ui/tests/i18n.test.mjs`（既有） | A–D | 新鍵兩邊一致 |
| `tests/test_story_take_refs.py`（新） | D | 語法（含 `@CAST-01:night`、`@SET-01` 不被當鏡頭引用的反例）、找不到 400、沒有 Take 409、未採用時用最新並標 `adopted: false`、剪裁出點秒數、`stale` 的三種情況（換採用、改出點、都沒變） |
| `tests/test_studio_worker.py` | D | `extract_frame` 的 `source_url` 只收本專案資產；首幀用法覆蓋 `first_frame`、參考用法排在角色之後；描述句插入位置 |
| `tests/test_take_grader.py`（既有） | D | 接點題目的輸入是兩格並排、結果存檔、任一邊換 Take 後舊結果過期；GPU 交接順序不變 |
| `ui/tests/takeModel.test.mjs` | D | 接縫狀態、試看取代採用的播放清單、試看不影響匯出參數 |

---

## 6. 實作順序與交付包

**包 A — 採用即成片與右欄（先做，不需要 GPU）**
1. 後端：`story_adoption.py`、`adoptions` 路由、shot view、任務完成不覆寫、候選時間、`films` 新參數；測試先寫。
2. 前端：`takeModel.js` 與測試；`ShotFilmPanel`；`A`／`R`；成片數字與成片視窗。
3. 實際尺寸截圖（8.4），更新 README「Available now」。

**包 B — 鏡頭生成台（參考、攝影機、提示詞、參數列）**
1. 目錄（攝影機、運鏡）與 `#` 編譯；`prompt-previews`；生成 `count`。
2. 運鏡範例：3D 排鏡台批次匯出（不需要 GPU 生成）。
3. 前端生成台、工具列收斂、`GenerationBar` 鏡頭模式；右欄移除出場。

**包 D — 引用與接點（B 之後、C 之前）**
1. 後端：`story_take_refs.py` 與測試；`extract_frame` 的 `source_url`；生成請求解析與凍結；shot view 的 `takeRefs`。
2. 接點：`take_grader` 的接點題目、`cuts`／`cut-checks`；先由人看過 Phase 2 的六鏡成片、標出接點問題，再跑一輪檢查，比對抓到了哪些。
3. 前端：引用標籤與「接上一鏡」、右欄引用行、接縫點、只巡接點、試看。
4. 成片 `segments` 擴充。

**包 C — 片型、色調、燈光、本集質感、範例、OpenJutsu**
1. 選項清單與名稱給使用者確認（待決 5）。
2. 4090 上產範例並寫 manifest。
3. 集數 `look`、鏡頭覆寫、編譯三行、`flow_runner` 附 `look`；本集質感頁；OpenJutsu 生成台。

每包獨立提交到 `fix/`／`feat/` 主題分支，不推送。

---

## 7. 待決事項（需使用者決定）

1. **採用首幀後是否自動生影片。** 建議：本機開放權重卡預設開，每個製作可關；Router 卡永遠不自動（固定決策 8）。管線路徑今天本來就會在套用首幀提案後推進到影片節點。
2. **「已採用」字樣的範圍。** 建議只在分鏡片場顯示「已採用」；表格狀態欄與其他頁面仍顯示「Approved」，避免素材的「定案」也跟著改名。
3. **時間碼批註。** 建議另開規格（Frame.io 式，釘在播放列上）；本規格只顯示既有列標註。
4. **範例媒體是否打包進 wheel。** 建議打包（總量預估 < 15 MB）；若超過，改成首次開啟時從專案內產生。
5. **片型、色調、燈光的選項清單與中文名稱。** 執行代理先提一份清單（每類 6–12 個），由使用者確認後才產範例。草稿見 `docs/specs/SPEC_19_LOOK_OPTIONS_DRAFT.md`（另附 9 個待你決定的問題）。
6. **網格總覽多選的「全部採用最新 Take」是否需要。** 建議要，但放在多選後才出現的底部動作列，外框按鈕。
7. **「接上一鏡」預設當首幀還是當參考。** 建議：劇本把這兩鏡標成同一個連續動作（同一拍拆出來的相鄰鏡頭）時預設當首幀，其他情況預設當參考。
8. **接點檢查是否在採用後自動排隊。** 建議跟現有「自動評分新 Take」用同一個開關（預設關）；開著時，任一邊採用或改剪裁就排進佇列。

---

## 8. 驗收矩陣

### 8.1 包 A

| # | 驗收項目 | 方法 |
|---|---|---|
| A1 | 候選 Take 按 ✓：格子換成那支、狀態 `Approved`、剪裁重設、`adoption` 有時間與人 | DB 測試＋瀏覽器 |
| A2 | 管線提案 Take 按 ✓：提案套用、下游任務推進、狀態 `Approved`；兩步任一失敗都不留下一半 | DB 測試（注入失敗） |
| A3 | 首幀 ✓ 只換首幀，不改狀態 | DB 測試 |
| A4 | 已採用的鏡頭收到故事 API 新 Take：格子不變、候選多一支、右欄顯示「新」 | DB 測試＋瀏覽器 |
| A5 | 未採用的鏡頭收到新 Take：照舊放進格子 | 既有測試保持通過 |
| A6 | `A` 採用正在播的 Take 並跳到下一個有新 Take 的鏡頭；`R` 寫 `Retake` 並把焦點放到提示詞 | 瀏覽器（鍵盤） |
| A7 | 右欄沒有核准大按鈕；整個片場畫面只有一顆淺色主按鈕 | `uiBudget.test.mjs`＋截圖 |
| A8 | 進度條段數＝鏡數，顏色與推導狀態一致，點一段會換鏡 | 前端測試＋瀏覽器 |
| A9 | 「接著看」依序播前、這、後三鏡，同時只有一個 `<video>` 在解碼，照剪裁播 | 瀏覽器（檢查 DOM） |
| A10 | 頂欄「成片 x／y」＝已採用鏡數；成片視窗摘要寫出「n 鏡有 Take 但未採用」 | 前端測試 |
| A11 | 成片視窗補位（最新 Take／預演／跳過）播放正確並標示；匯出送 `selection: "adopted"`，片段來源記在 `segments` | 瀏覽器＋API 測試 |
| A12 | `POST /episodes/{id}/films` 送 `{}` 或 `{fillPrevis: true}` 的結果與改版前相同 | API 回歸測試 |
| A13 | 證據包、升級 hero、主控台評分在採用後照常運作（它們讀 `Approved`） | 既有測試＋一個採用後的整合案例 |
| A14 | 舊資料：沒有 `createdAt` 的候選、沒有 `adoption` 的 `Approved` 鏡頭，推導狀態正確（已採用、無新 Take） | 前端與 DB 測試 |
| A15 | 唯讀成員看不到 ✓ 與 ↻，按 `A`／`R` 沒有作用 | 瀏覽器 |
| A16 | 英文與繁中切換後所有新文案都有翻譯，鍵與參數一致 | i18n 測試 |

### 8.2 包 B

| # | 驗收項目 | 方法 |
|---|---|---|
| B1 | 選一鏡，中間是生成台；沒選是網格；七個檢視只在「檢視」下拉裡 | 瀏覽器＋`story-ui.test.mjs` |
| B2 | 點「攝影機」：上半部換成範例牆；`Esc` 回到 Take；範例只在游標停留時播 | 瀏覽器 |
| B3 | 選機身與鏡頭：`Optical Rig` 欄寫入目錄描述，可復原（`Ctrl+Z`） | 瀏覽器＋前端測試 |
| B4 | 點運鏡：提示詞游標處插入 `#` 標籤；多選時順序數字正確 | 前端測試 |
| B5 | 編譯：`#push-in` 在原段落就地展開；`@CAST-01#night` 不被當成運鏡；未知 `#xxx` 原文保留 | worker 測試 |
| B6 | 「看送出的完整提示詞」與實際送給 worker 的文字逐字相同 | API 測試（同一函式） |
| B7 | 支數 2：建立兩個任務、seed 不同；Take 清單出現兩支「新」 | API 測試＋瀏覽器 |
| B8 | 參數列在 1280 寬一排放得下；960 寬時解析度與聲音收進「更多」，主按鈕仍在最右 | 截圖 |
| B9 | 提示詞改過未存時主按鈕是「儲存並生成」，生成用的是畫面上的文字 | 瀏覽器 |
| B10 | 運鏡範例媒體大小與格式符合 4.4，manifest 齊全 | 腳本檢查 |

### 8.3 包 C

| # | 驗收項目 | 方法 |
|---|---|---|
| C1 | 本集質感改色調：沒覆寫的鏡頭鈕上顯示新值並標「本集」；覆寫過的不變並標「本鏡」 | 瀏覽器＋前端測試 |
| C2 | 「回到本集」刪除覆寫 | API 測試 |
| C3 | 編譯出 `Film`／`Color`（含色碼）／`Lighting` 三行；兩條生成路徑文字相同 | worker＋API 測試 |
| C4 | 未知代號 400，錯誤訊息有 `message_key` | API 測試 |
| C5 | 範例 manifest 每筆有工作流程、模型、seed、提示詞、授權；無真實人物、品牌、文字 | 腳本＋人工抽查 |
| C6 | OpenJutsu 列在生成台裡可選來源影片與模式，送出內容與改版前的工作流程輸入一致 | worker 測試 |

### 8.4 包 D

| # | 驗收項目 | 方法 |
|---|---|---|
| D1 | 提示詞打 `@S02.end`：畫成帶縮圖的標籤，縮圖是 S02 採用 Take 在剪裁出點的那一格 | 瀏覽器＋前端測試 |
| D2 | 送出後新 Take 的來源有完整快照（鏡頭、Take 網址、秒數、抽出的圖、用法、是否已採用） | DB 測試 |
| D3 | 當首幀：送進 worker 的 `first_frame` 就是快照裡那張圖；當參考：排在角色與場景之後 | worker 測試 |
| D4 | S02 改採用別支（或改出點）後，S03 採用中的 Take 標「上游已換」，進度條加角標；改回原本那支後標示消失 | DB＋瀏覽器 |
| D5 | 「用新的重拍」只開生成台並把引用指到新的採用，不送出任何任務 | 瀏覽器（檢查網路請求） |
| D6 | 接點檢查用兩格並排的圖，結果出現在接縫點；任一邊換 Take 後該接縫回到「還沒查」 | DB＋瀏覽器 |
| D7 | Phase 2 六鏡成片：先由人標出接點問題，再跑接點檢查；回執列出人標的、檢查抓到的、兩者不一致的，附畫格（不要求全對，要求如實記錄） | 人工＋回執 |
| D8 | 只巡接點：每個接縫前後各 1 秒、同時只有一個 `<video>` 在解碼 | 瀏覽器（檢查 DOM） |
| D9 | 試看：接著看與成片視窗用試看中的 Take、角落標「試看」；不產生任何寫入；`A` 採用試看中那支；`Esc` 或換鏡恢復 | 瀏覽器＋前端測試 |
| D10 | 匯出成片的 `segments` 每段有 Take、入出點、引用快照與接點結果 | API 測試 |
| D11 | `@CAST-01:night`、`@SET-01` 不被當成鏡頭引用；`@S99.end` 找不到時送出回 400 並列出代號 | 後端測試 |

### 8.5 實際尺寸與鍵盤

- 在主資料庫的**複本**上，以 headless Edge 經 CDP 截 1920×1080 與 1280×720（應用內瀏覽器只有約 841×336，不能代表桌面版面）。
- 1280×720：上半部 Take、五顆鈕、提示詞與參數列都在第一屏，不捲動；右欄 300px 內容不被截斷。
- 範例牆開啟與關閉、`A`／`R`／`↑↓`／`Esc` 全部用鍵盤操作一次並錄下結果。

---

## 9. 執行驗證與完成回執

```powershell
python -m unittest discover -s tests -v
npm test --prefix ui
npm run build --prefix ui
```

- DB 整合測試用專用的測試 PostgreSQL（`OPENBENCH_TEST_DB_URI`），不要指向放展示資料的主叢集。
- 回執存 `docs/spec19-verification.json`：提交 SHA、各指令結果（通過／失敗／跳過數）、截圖路徑、未驗證項目（例如真實 GPU 生成、Router 報價）。
- README「Available now」只在功能實際完成並驗證後才加，寫明限制。

---

## 10. 給執行代理的交接提示

- 先讀 `AGENTS.md`、`docs/DESIGN_AND_DEV_GUIDELINES.md`、`docs/ZEROFIELD_SPEC.md`，再讀本文件與 SPEC_18 §1.3。
- 動 `story_openapi.py:1086` 的覆寫條件前，先寫「已採用不覆寫」的失敗測試，再改；舊的 `selected: True` 斷言保留。
- 採用的兩種路徑（候選、提案）必須同一個交易；先確認 `apply_proposal` 的交易行為（1.2 A）。待審的 receipt 只能走提案路徑（1.2 K）。
- 包 D 的引用一律在送出當下凍結成快照（1.2 L、4.5）；不要只存鏡號。
- 不新增狀態值、不自動寫 Pending Review、不改 `cinema-studio` 範本欄位。
- `#` 標籤的正規表示式要有 `@CAST-01#night` 的反例測試（1.2 F）。
- 「接著看」與範例牆遵守單一解碼（1.2 I、§5.3）。
- 不碰工作樹裡與本規格無關的未提交檔案（例如 `docs/specs/SPEC_17_*`、`ui/prototypes/story-planning/`）。
