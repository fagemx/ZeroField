# SPEC_16 — 作者主導的寫作工作台、創作版本與劇本改動影響追蹤

> **Authoring Workspace, Creative Versions & Story-to-Shot Impact**
>
> **日期**：2026-10-23。
> **狀態**（2026-10-26 更新）：整合分支 `spec16-20261023-b1/integration` 已實作並經三輪獨立審查（[審查紀錄](../SPEC16_REVIEW.md)），已併入三空間版 Story & World（[SPEC_16A](SPEC_16A_INTEGRATION_INTO_THREE_SPACE_STORY_WORLD.md)）；**使用者驗收尚未給**。以下維持 2026-10-23 的原始設計（那時的外殼是兩空間），不是完成回執，也不自行授權派工、模型推論、部署或費用。
> **目標**：在既有「故事與世界／分鏡片場」雙空間內，讓創作者能安心寫作、整理故事、嘗試不同版本，並知道改稿會影響哪些鏡頭。
> **實際閱讀基準**：`e7b2ce7`，包含 SPEC_13、14、15 實作。寫規格時 `project_docs/story_adaptation.py`、`tests/test_story_openapi.py` 有既存未提交修改；它們不屬於本次文件修改，執行者不得覆蓋或假定可以接管。
> **外部參考**：[PowerWrite 首頁](https://powerwrite.app/)、[功能總覽](https://powerwrite.app/features)。參考的是公開功能與示意圖，不是登入實測、效能驗證或程式碼授權。PowerWrite 明確不提供 AI 續寫／改寫；本規格借鏡的是作者對結構、設定與版本的控制，不複製其品牌、素材或實作。

---

## 0. 執行摘要與固定決策

本次不是再造一套小說 SaaS，也不是重做影片產線。沿用現有產品，補上作者能反覆工作的上游：

```text
點子／小說原文 ── 明確改編、預覽 ──┐
                                  ▼
                        工作中劇本（可持續編輯）
                         ↕              ↕
                    情節總覽        世界設定／筆記
                         │
                  具名版本／另一種寫法
                         │ 選用版本或確認目前稿件
                         ▼
                    不可變製作基準
                         │ 變更影響預覽，選擇套用範圍
                         ▼
                  現有分鏡、預演、影片候選
```

**固定決策：**

1. 保留 SPEC_15 的兩個頂層空間、三欄骨架、劇組入口與成片疊層；不增加「寫作中心」等第三個頂層產品。
2. **儲存文字 ≠ 確認製作基準 ≠ 更新分鏡 ≠ 生成媒體**。自動儲存永遠不派發模型、不生圖、不重拍。
3. 目前工作中劇本仍以既有 `projectops.tab` 文件為唯一可編輯主線；不把第二份可編輯劇本同步存進 `story_record` 再互相覆蓋。
4. 點子、小說原文與個人另稿持久保存，但與主線劇本分開；個人來源預設私有。明確採用的劇本／具名共享版本才進入製作共享範圍。
5. 修改紀錄用來追溯與復原；創作版本用來比較不同寫法；製作基準用來固定下游來源。三者不可混為一談。
6. 新增穩定的 `sceneKey`／`beatKey` 作長期關聯；舊 `sceneId`／`shotIndex` 保持相容，不將顯示順序當永久身份。
7. 只自動判斷可證明的文字／結構／引用差異。語意相似、心理狀態、故事好壞不靠規則偽裝成理解；不確定的關聯必須明示。
8. 現有鏡頭的人工運鏡、提示詞、造型、媒體與候選歷史不因改稿被悄悄重設。
9. 原文可以有內心描寫；「無標籤／可拍攝性」檢查限於改編候選與拍攝劇本建議，不得清洗小說原稿或自動改掉作者手寫正文。
10. 本規格採一般編輯、比較與套用操作，不新增固定 AI 評審迴圈、scheduler 或必經人工閘門。既有媒體授權／提案規則照舊。

### 0.1 最終交付的三句話

- 「我寫的內容有保存，換空間、重整、斷線後都知道如何接續。」
- 「我可以比較不同寫法，選一份用來製作，不會失去其他版本。」
- 「我改第三場，只處理受影響的鏡頭；其他已經拍好的東西不會被動到。」

---

## 1. 必讀基底與實際缺口

執行前先讀專案 `AGENTS.md`，以及：

- [目前 Story Workbench](../STORY_WORKBENCH.md)
- [上游故事流程](../SPEC13_UPSTREAM_PIPELINE.md)
- [SPEC_14 構成式敘事](SPEC_14_COMPOSITIONAL_NARRATIVE_ENGINE_AND_CHOICE_TRACES.md)
- [SPEC_15 雙空間工作台](SPEC_15_UNIFIED_CREATIVE_WORKSPACE_UI_DESIGN.md)
- [既有路由／授權／分配契約](../SPEC07_STUDIO_ROUTING.md)
- [介面與開發規範](../DESIGN_AND_DEV_GUIDELINES.md)

### 1.1 實際程式盤點，不可誤判成全部缺失

| 能力 | 現況 | 本規格處理 |
|---|---|---|
| 雙空間、三欄、成片疊層 | `StudioShell.jsx`、`StoryWorld.jsx`、`ShotStage.jsx` 已存在 | 延伸，不重造導航 |
| 原文與劇本分離 | `storyImport.js` 有三種來源與 adaptation key，但主要是元件草稿 | 補持久來源、恢復與明確採用 |
| 新故事頁編輯 | `StoryWorld` 以 textarea/state 編輯，未接上 `surfaceControl` 保存契約 | 接入統一保存／離頁／衝突處理 |
| 舊文件編輯 | `DocSurface.jsx` 有 TipTap、自動儲存、區塊 base、flush、離頁防護 | 抽取／共用可靠部分，不直接移植整個舊辦公介面 |
| 修改歷史 | `History.jsx`、`page_history.py`、revisions API 已存在 | 保留，另建創作版本語意 |
| 劇本版本 API | `GET /episodes/{id}/script/versions` 回傳 tab revisions | 保持原契約，不冒充不可變命名版本 |
| 場次 CRUD／排序／重建 | `story_openapi.py` 已有 scenes、scene-order、shot-rebuilds | 補 UI、穩定身份與來源關聯 |
| 一般 storyboard build | 補缺少的 beats，保留既有鏡頭 | 不宣稱它會同步所有改稿 |
| 單場 rebuild | 可更新敘事並保留標籤、光學與媒體 | 提供更精確的差異預覽，不能把整場重建當選定 beat 更新 |
| 角色與資產 | Soul Cast、變體、圖片、使用場次／鏡頭已存在 | 同一身份補敘事設定，不再建一份角色庫 |
| DOCX 工具 | `file_handoff.py` 已有有界匯入與 DOCX／MD 匯出 | 共用解析安全與輸出能力，補寫作專用預覽 |
| 改編能力 | SPEC_13／14 主路徑為 deterministic/offline | 保留；不把本規格描述成新 LLM 寫作引擎 |

### 1.2 兩項必須在實作前理解的資料陷阱

**A. `tab.revision` 不是每次內容變更都遞增。**

`repository.save_tab_doc()` 會合併同一 session、同一作者、十分鐘內的自動儲存，修改同一筆 `tab_revision`；其 `base_revision` 也不是拒絕舊寫入的充分條件。故：

- 不可只用 revision number 判斷內容未變。
- 不可用指向某筆 mutable revision 的外鍵來代表不可變製作版本。
- 預覽、完整替換與版本採用須綁定內容雜湊；一般編輯沿用逐 block `base` 比對。

**B. 舊 `sceneId` 含順序，重新排序會改變。**

`scenes()` 依位置產生 `sc_<slug>_<episode>_Sxx`；`write_scenes()` 已有舊鏡頭關聯重映射。故：

- 新長期關聯不得只保存這個字串。
- 不能重新依標題／第幾場猜測同一場；重複標題、插場、刪場都會誤綁。
- 保留舊序號 ID 供既有 API 使用，新增獨立穩定 key；相容映射須在同交易更新。

---

## 2. 範圍與非目標

### 2.1 本次完整交付範圍

| 編號 | 功能 | 完成定義 |
|---|---|---|
| W1 | 可靠寫作與草稿恢復 | 主線劇本、點子、小說、另稿的保存／離頁／重整／斷線狀態一致可信 |
| W2 | 結構與情節總覽 | 按場編輯、摘要、故事時間、情節線、重排、拆分／合併、可復原結構變更 |
| W3 | 創作版本 | 具名快照、另稿、並排比較、鎖定、選用；固定製作來源 |
| W4 | 改稿影響 | 劇本單位到鏡頭來源可追溯；精確範圍預覽、選擇套用、保留媒體與人工修改 |
| W5 | 世界設定 | 既有資產上的角色／世界敘事資料、場次事件、出場矩陣與筆記 |
| W6 | 搜尋與安全取代 | 指定範圍、前後文、逐項選取、原子套用與衝突保護 |
| W7 | 稿件進出 | TXT／MD／DOCX 結構預覽匯入；TXT／MD／DOCX 匯出與瀏覽器列印／另存 PDF |
| W8 | 寫作體驗 | 專注模式、可收合側欄、排版偏好、字數與真實保存狀態、雙語與無障礙 |

W1～W4 是核心，先做；W5～W8 是本規格其餘交付，不可在最終回執中默默省略。可以分階段交付，但須明確列出尚未完成者。

### 2.2 明確不做

- Google Drive、OAuth、跨裝置離線同步引擎、CRDT／OT 平台或全站 PWA 改造。
- EPUB／RTF、出版封面排版、印刷色彩管理、書店或稿費系統。
- 新的通用資料庫建構器、無限巢狀章節、無限自訂欄位。
- 新模型訓練、AI 文筆評分、自動完成全書、自動角色心理推斷。
- 將手改鏡頭無聲反寫成劇本；反向跳轉本次要有，自動雙向覆寫不要做。
- 在文字變更時自動重拍、自動換模型、自動付費或取消外部供應商工作。
- 對既有已交付 API 做大破壞，或為本功能重構整個 M8／Console。
- 將所有先前版本、原文或私有另稿自動送給代理或遠端 provider。

---

## 3. 使用者流程與介面

### 3.1 工作台骨架

```text
ZF / 製作 / 集數       [ 故事與世界 ] [ 分鏡片場 ]       Ctrl K / 劇組 / 成片
┌──────────────────┬─────────────────────────────────────┬───────────────────┐
│ 集／場次清單      │ 正文 | 情節總覽                     │ 設定 | 筆記       │
│                  │ 來源：點子 / 小說 / 劇本             │                   │
│ 場 01 抵達       │ 版本：工作中劇本 ▾   比較   ⋯        │ 選中角色／場次    │
│ 場 02 訊號       │                                     │ 的資料與引用      │
│ 場 03 離開       │ 主要正文編輯區                      │                   │
│ + 場次           │                                     │                   │
│                  │                                     │                   │
├──────────────────┴─────────────────────────────────────┴───────────────────┤
│ 已儲存 23:10 · 1,240 字 · 製作基準：無對白版 · 3 鏡需查看   [查看改動影響] │
└────────────────────────────────────────────────────────────────────────────┘
```

- 版本、搜尋、匯入／匯出是同空間工具，不增加頂層站點。
- 情節總覽不是 Cinema Studio 表格的另一份鏡頭資料；它編輯的是故事結構與敘事備註。
- 主線劇本、私有來源與私有另稿有清楚的範圍標示。使用者不必猜文字是只存在本機、存在伺服器，或已成為製作依據。
- 保留點子／小說的 SPEC_14 透鏡與碰撞卡，可收合；不讓「故事發展」工具永久佔據正文上方大半螢幕。
- 共用劇組側欄開啟時保留游標、選取場次與未送出文字；同時窄螢幕只顯示一個右側面板。

### 3.2 從空白／來源開始

1. 輸入點子或貼入小說；文字即自動保存為目前作者的來源，不能先要求改編才保存。
2. 自由整理章節／段落。原文保持原樣，不先套 screenplay 的 Lens 行、情緒詞過濾或資產標籤。
3. 點「預覽改編」才呼叫既有 deterministic 編譯器；結果是候選，不立即覆蓋工作中劇本。回應同時建立本人持久 `candidateBranchId`，因此預覽到期不會丟掉候選文字。
4. 作者可以修改這份候選 branch、比較或取消；編輯後先保存 branch，再以新內容產生 promotion preview，不原地竄改 frozen preview。點「採用為工作中劇本」才寫入共享主線。若主線已有人改動，保留候選並顯示衝突。
5. 第一次建立分鏡時可在同一個明確操作中：確認目前稿件、固定製作基準、抽取資產、建立文字分鏡；**仍不生成圖片或影片**。

舊 `/script-adaptations` 的既有直接寫入行為維持相容；新工作台改走本規格的預覽路徑，不能悄悄改掉舊端點的測試契約。

### 3.3 日常修稿

- 在主線劇本直接編輯，停止輸入後自動儲存；修改不強迫切到片場。
- 已儲存但與製作基準不同時顯示「劇本有改動」，不是錯誤，也不阻止繼續寫作。
- 切換場次、來源模式、集數、兩個工作空間與瀏覽器返回，均須先把 pending 內容可靠保存或留作本機恢復；不能卸載元件就丟掉。
- 網路正常且沒有衝突時不跳確認對話框；只有保存失敗、不可恢復或需要選擇衝突內容才要求使用者處理。

### 3.4 嘗試另一種寫法

1. 對目前稿件「保存具名版本：克制版」。這是明確共享快照，不是複製整個專案。
2. 從快照「另寫一版」，建立私有可編輯另稿，例如「正面衝突版」。
3. 比較工作中劇本／兩個快照／本人另稿；左側為參考、右側為待選版本。
4. 整份採用或採用選定場次時，先預覽差異；不自動攜帶別版的媒體、鏡頭設定或製作指標。
5. 被採用前的主線保存為一份自動快照；操作者可以找回。這是文字快照，不是另開 Git 分支。

### 3.5 改稿影響與拍攝

1. 作者改第三場一句對白；保存成功後顯示來源已變。
2. 點「查看改動影響」，列出確切關聯鏡頭、人工覆寫與無法確定的項目。
3. 選擇更新文字的鏡頭；對人工覆寫預設不替換，須逐項明選。
4. 套用後保留影片、首幀與歷史候選。標示媒體「依舊稿拍攝」，不自動把舊 take 說成符合新稿。
5. 要重拍時，從現有 Shot Stage 發起正常 allocation／媒體流程。不要從寫作套用端點繞過 M8、政策、預算或提案。

### 3.6 主要操作按鈕

每個目前視圖最多一個琥珀色主要操作；自動儲存不是主要 CTA。

| 狀態 | 主要操作 |
|---|---|
| 僅有來源，尚無候選 | 預覽改編 |
| 正在查看改編／另稿差異 | 採用選定內容 |
| 已有劇本、尚未有分鏡 | 確認劇本並建立分鏡 |
| 已有分鏡且有未處理改稿 | 查看改動影響 |
| 無新變更 | 前往分鏡片場（可用一般導覽樣式，不必硬填主要按鈕） |

---

## 4. W1／W8：可靠編輯、保存與恢復

### 4.1 編輯器選擇

- 使用既有 TipTap／ProseMirror 依賴，從 `DocSurface` 抽出最小共用的文件編輯、block identity、保存與衝突處理。不得把整個舊 `DocSurface` 重寫來服務這一頁。
- 主線劇本以既有 validated doc 儲存；保留 `bid`、marks、annotations、鎖與歷史。不能每打一個字就 `markdown_to_doc()` 重新生成全頁 IDs。
- 允許先以 textarea 做短篇來源輸入，但必須接同一保存狀態機；劇本正文必須支援按場編輯與穩定區塊。
- 全文檢視與按場編輯共用同一模型；切換不是序列化成純文字後再匯入，不能丟格式或重造身份。
- 空白稿件可在寫作端保存；只有確認／改編／建立分鏡才要求非空。不得把「最後一個字刪掉」視為無法保存。

### 4.2 保存狀態機

```text
saved → dirty → saving → saved
              ↘ local_only / save_failed / conflict
local_only → reconnecting → saving → saved | conflict
conflict → 使用者比較／保留另稿／套用合併結果 → saving
```

- 停止輸入約 800 ms 後送出；持續打字最多每 5 s 保存一次 dirty batch。不要每次鍵盤事件都發 request。
- 中文 IME 組字期間不得重設 editor value、移動游標或送出半個組字結果；compositionend 後再排保存。
- 每份可編輯資源單一 in-flight 保存佇列；後續修改累積為下一批。舊 response 不得清除較新的 dirty 狀態。
- 區塊保存依既有 `base`／ops 回應處理。HTTP 200 但 `conflicts` 非空並不等於全部儲存成功。
- 收到更新時保留本地尚未套用的 ops；不要用較舊的 `ep.scriptContent` 覆蓋正在輸入的稿。
- App 的 navigation／episode change／history restore／version adoption 共用 `flush()`、`isDirty()` 與可恢復狀態契約。`StoryWorld` 必須註冊 `surfaceControl`，離開時解除自己註冊的 instance，不能清掉另一個 surface 的 control。

### 4.3 本機恢復，不冒充完整離線產品

使用 IndexedDB 建立有界 recovery journal，key 至少包含：

```text
origin / projectSlug / actorId / episodeId / resourceKind / resourceId / browserTabId
```

保存 `baseHash/baseVersion`、未確認內容或 ops、clientMutationId、localSequence、updatedAt。不要保存 credentials、模型 key、私有 session token 或媒體 blob。

- dirty 變更先做本機檢查點，再排網路保存；本機保存成功顯示「已存於此裝置」，伺服器 ACK 後才顯示「已儲存」。
- 正常切換以 flush 優先；已可靠寫入 journal 的網路失敗可保留恢復後切換，不要逼使用者一直停在原頁。
- 本機儲存也失敗時，不宣稱已備份；顯示錯誤、提供下載目前文字，離頁才警告。
- 初次重整時比較 journal 與伺服器的內容雜湊；若一樣可清理，若不同顯示恢復比較，不直接把舊本機稿覆蓋回伺服器。
- 同一作者兩個 browser tabs 用不同 tabId；用 BroadcastChannel 提示重複編輯，但資料庫 CAS 才是權威，不能靠瀏覽器主鎖保證正確。
- 已在頁面載入的文字可斷線繼續寫並保存本機；不承諾完全離線重新開啟整站或載入未下載作品。
- 登出／切換身份時清空已同步暫存；有未同步內容先讓本人下載或明確丟棄。新身份不得讀取前一身份的 journal。
- 收到 401／403／權限撤銷時立即停止自動上傳與重試，不因重連而重新提交。
- 成功同步的 journal 可清理；未同步者不得自動過期刪除。設容量上限（預設 20 MiB／origin），不足時提示，不能默默淘汰未保存稿。

### 4.4 排版與無障礙

- 專注模式收合左右側欄，保留稿件、狀態列與必要操作；Esc 離開，恢復原選取與面板。
- 字級 14–24 px、行距 1.4–2.2、稿件欄寬 560–960 px；偏好只影響顯示，不改內容或生成 prompt。
- 使用系統與現有合法字體，不在本次自動下載字型。英文預設，繁中可切換。
- 暗色工作台維持單一琥珀強調色；可選閱讀紙張底色，但不重做全站主題系統。
- 所有拖曳排序另有鍵盤「上移／下移」；主要按鈕、版本比較與衝突提示具有可見 focus、label 與 live status。
- Ctrl/Cmd+S = flush；Ctrl/Cmd+Shift+F = 目前寫作空間搜尋。聚焦編輯器時不觸發片場 A／R／G／方向鍵快捷鍵。
- 字數明示口徑：CJK 表意字逐字＋拉丁文字詞數，標點不算；另提供含空白字元數。這不是 token 數，也不是影片秒數。

---

## 5. W2：故事結構、情節總覽與穩定身份

### 5.1 最小結構

- 製作與集數沿用既有模型；拍攝劇本：`episode → scene → beat`。
- 小說來源：`source document → chapter → source section`，最多兩層；點子可只有一個 section。
- 幕（Act）在本版是可選分組欄位，不新增第三層任意樹狀文件管理器。
- beat 是可供拆鏡的敘事單位，不等於鏡頭；一個 beat 可以對應多顆鏡頭，一顆合併鏡頭也可以有多個來源 beat。
- 正文是唯一正文來源；摘要、時間、情節線是 metadata，不再保存另一份場次正文。

### 5.2 Key 與映射

新增：

- `sceneKey = wsc_<uuid>`：一場的穩定身份。
- `beatKey = wbt_<uuid>`：一個敘事單位的穩定身份。
- 既有 `sceneId` 是相容用位置 ID，`sceneIndex` 是顯示順序；新的 API 與 UI 修改用穩定 key。
- `headingBid`／`blockBids` 定位目前 doc 中的場與 beat；不得把 UTF-16 offset 當永久身份。
- 若一個 paragraph 被切成多個 beats，可保存目前版本下的 code-point range 與 exact text hash；range 只對該 docHash 有效，不可跨版盲用。

身份保留規則：

1. 移動、改名、編輯同一 block 時保留 key；顯示序號變了不算新場。
2. 複製場次產生新 keys，不自動複製媒體或掛到原鏡頭。
3. 拆分保留一個原 key，新增其他 keys，回傳 lineage；既有來源跨越拆分邊界時標 `ambiguous`，不得猜要轉給哪一半。
4. 合併保留一個指定 key，記錄被合併 keys 的 lineage；保留所有來源關聯，不能只留下第一個。
5. 刪除採 tombstone／可恢復，既有鏡頭標 `source_removed`，不刪已拍媒體或候選。
6. 舊整份文字寫入、改編、還原導致 block IDs 改變時，只允許在 episode 內做唯一且確定的 identity reconciliation：原 key 的明確 lineage、存活 bid、唯一 exact content match。重複文本或不明確映射回 `unresolved`。
7. 禁止以字串相似度、場次序號、標題相同或 LLM 猜測直接認定新舊為同一場。

### 5.3 舊專案升級

- 第一次讀取可以計算唯讀結構，但 GET 不順便寫資料，回傳 `initialized:false`。未保存的 preview keys 不可作 mutation／鏡頭 binding。第一次 writable 編輯由 UI 自動送 `POST /initialize`（帶當前 docHash）再繼續，不要求使用者額外按一個初始化鈕；此 POST 才在交易內保存 sidecar。
- 以當前 tab doc 與舊 `shot_meta.sceneId` 建立一次快照映射；在未改稿且可驗證原始生成結果時可標 `exact`，否則只到 `scene_only` 或 `unresolved`。
- 初次對應不能假稱擁有舊鏡頭生成時的精確來源；沒有證據就顯示「舊資料，尚未綁定」。
- 重新排序時在單一交易更新穩定順序、相容 sceneId 與既有 shot metadata；保留 shotId、rowId、人工標籤、媒體與預演。
- 新工作台不呼叫會將全部 heading 重造的捷徑；舊 API 保持可用，但其結果須進同一 reconciliation／失效檢查。

### 5.4 情節總覽

每場一列，固定欄位：場次標題、摘要、故事時間（自由文字）、出場角色、關聯鏡頭、製作差異狀態。可選：Act、伏筆／回收、最多 8 條具名情節線。

- 摘要與情節線由作者編寫；未填時可顯示正文節錄並標「節錄」，不能假稱模型摘要。
- 故事時間不是鏡頭 duration；例如「同日晚上」「三年前」不做虛構精確時間排序。
- 情節線是 episode 內的 `{laneId, name, order}`，各場 cell 是純文字。刪 lane 先預覽有內容的欄位，保留可復原快照。
- 重排場次移動正文與 metadata 同一場，不以剪下貼上重建全稿。
- 總覽與正文互相定位；修改 metadata 不令所有影片被標為過期。
- 結構變更可立即 Undo；跨重整可從自動結構快照恢復。Undo 必須核對基底，不能覆蓋後續別人的改動。

---

## 6. 持久化與資料契約

### 6.1 存放原則

使用既有 `projectops.story_record` 保存 API metadata、私有來源／另稿及不可變快照；主線劇本仍在 `tab`。本版不要求建立另一套文件資料庫或排程表。

新增模組須提供 typed validation、scope validation、CAS 與 immutable insert helpers；不能直接用通用 `store()` 無條件 upsert 所有新資料。

- 各 record 有 `schemaVersion: 1`、`projectSlug`、`episodeId`、`version`、`createdAt`、`updatedAt`。
- `owner_id` 私有資源必填；project-visible 資源明確標 `visibility: project`。`owner_id IS NULL` 本身不代表公開。
- `version` 為可變 sidecar 的真正 mutation counter；更新需 `baseVersion`，交易內鎖定與比對後遞增。`writing_version` 的 snapshot 除外：本體不可變，catalog 用 `catalogVersion`；preview／receipt／export 的生命周期狀態不得被當成可改寫來源正文。
- 建立單例如 owner＋episode＋sourceMode 時使用 deterministic record key／唯一插入；競爭不得產生兩份目前來源。
- JSON 索引若有實測需要，可以新增 additive migration；若使用下一號 `164_*.sql`，先確認沒有其他工作占用，更新 migration registry 與 wheel 包裝。不可修改 162／163 的既有歷史。
- 新記錄建立／更新／引用必須同時驗證 kind、slug、episode、owner，不僅驗證 ID 前綴。

### 6.2 新 record 種類

| kind | 範圍 | 內容與不可混淆之處 |
|---|---|---|
| `writing_source` | 本人、單集、idea 或 novel | 原文 doc、章節結構、來源檔 metadata、透鏡／私人取捨；不作主線權威 |
| `writing_branch` | 本人、單集 | 從主線／快照派生的可編輯另稿，含 doc、結構、base fingerprint、name、locked；尚未共享 |
| `writing_version` | 製作共享、單集 | 完整不可變 doc 與結構／設定快照；名稱等 catalog metadata 可受控修改 |
| `writing_structure` | 製作共享、單集 | 主線 stable keys、doc 定位、順序、plot lanes、摘要與 tombstones；不複製正文 |
| `writing_bible` | 製作共享 | 既有 asset 的敘事擴充，或尚未成為資產的 world/note；不能與 Soul Cast 重複擁有名稱／外觀欄位 |
| `writing_preview` | 本人、單集、有時效 | adaptation／promotion／structure／impact／replace／import 的 frozen proposal；不是執行 task |
| `writing_export` | 本人、單集、有時效 | 經授權固定的輸出內容／bytes、格式與 30 分鐘 download／print handle；不可當公開檔案 |
| `writing_receipt` | 本人、資源、mutation | 非 POST 保存的 body hash 與 bounded ACK，供 ACK 遺失重送；24h 清理，不是內容版本 |

`shot_meta` 擴充 `storyOrigin`／`storyAlignment`；episode record 擴充 `productionScriptVersionId`。不要再新增第三份鏡頭正文表。

### 6.3 Hash 定義

- `scriptHash`：沿用 `story.digest(story.script(conn, ep))` 的既有口徑，用於 `confirmedHash` 相容；不可悄悄改口徑。
- `docHash`：validated doc 的 canonical JSON SHA-256，保留內容、marks、bid、順序；不把回應時間或編輯者顯示名當內容。scope／權限仍另查，不可由 hash 授權。
- `structureHash`：stable scene／beat identity、順序、定位與結構設定之 canonical hash。
- `productionInputsHash`：生產相關版本、medium／genre／breakdown、精確引用的視覺設定版本；排除不影響產出的純筆記／排版偏好。
- `sourceTextHash`／`derivedTextHash` 分別記錄來源敘事與上次派生文字。不可只依單一 revision number 判斷 freshness。
- snapshot 同時保留本體與 hashes；hash 不是資料備份。

### 6.4 透鏡與來源文字的單一權威

- 私有來源／branch 的 `composition` 隨該資源 version 保存，重整後不能遺失。
- 主線的 medium／genre 保持以 SPEC_14 劇本 `Lens: <medium> × <genre>` 宣告為相容來源；workspace 以 typed parser 讀取該宣告，缺省即未指定。新 UI 調整透鏡透過受控 doc ops 更新宣告，不另外建立可與正文衝突的第二份 medium 設定。
- snapshot 的 composition 是當次正文宣告的凍結投影。episode 的 aspectRatio／style／breakdown 等既有 settings 也一起固定為當次 productionInputs；改觀看透鏡只提供畫幅建議，不無聲覆蓋使用者已選的畫幅。
- 小說原文中恰好出現 `Lens:` 不視為主線配置，只有拍攝劇本 adapter 解析。
- 原文匯入／貼入轉為 doc 時必須保留段落邊界、台詞換行與文字，不能套用會逐行 trim／拼接的 generic Markdown 捷徑。若保留原檔／原始 text 作可下載 archive，它是不可變來源證據，不是第二份可編輯正文；後續編輯權威仍是 source doc。

### 6.5 具名版本範例

```json
{
  "versionId": "wver_<uuid>",
  "schemaVersion": 1,
  "episodeId": "ep_example_01",
  "visibility": "project",
  "name": "Silent ending",
  "catalogVersion": 1,
  "locked": true,
  "snapshot": {
    "doc": {"type": "doc", "content": []},
    "structure": {"scenes": [], "lanes": []},
    "composition": {"mediumLens": "cinema", "genreLens": "suspense"},
    "docHash": "sha256:...",
    "scriptHash": "sha256:...",
    "structureHash": "sha256:..."
  },
  "createdBy": "actor-id",
  "createdAt": "ISO-8601"
}
```

此例示意形狀，不是可確認的空稿。所有具名版本的 `snapshot` 建立後永遠不可更新；版本名稱／archive 等 catalog metadata 用獨立 `catalogVersion` CAS，不修改 snapshot。

「鎖定」防止改名／archive 等 catalog 誤操作，不阻止閱讀、比較或選用這份定稿；未鎖定 snapshot 也不可原地改正文。要改正文一律建立 branch／新快照。未被引用的 snapshot 可由 creator／admin 明確解鎖再改 catalog；被製作基準引用者必須 locked，不能 archive、刪除、解鎖或替換本體。本版不提供永久刪除版本，只提供未被 pin 版本的 archive。

### 6.6 場次與鏡頭來源範例

```json
{
  "sceneKey": "wsc_<uuid>",
  "legacySceneId": "sc_example_01_S03",
  "headingBid": "b_existing",
  "order": 3,
  "summary": "The keeper hides the signal.",
  "storyTime": "That evening",
  "beats": [{"beatKey": "wbt_<uuid>", "blockBids": ["b_dialogue"], "textHash": "sha256:..."}]
}
```

```json
{
  "storyOrigin": {
    "versionId": "wver_<uuid>",
    "sceneKeys": ["wsc_<uuid>"],
    "beatKeys": ["wbt_<uuid>"],
    "mapping": "exact",
    "sourceTextHash": "sha256:...",
    "derivedTextHash": "sha256:...",
    "derivedFields": {"description": "...", "dialogue": "..."},
    "assetBindingsHash": "sha256:..."
  },
  "storyAlignment": {
    "state": "source_changed",
    "acknowledgedAgainstVersionId": null
  }
}
```

`storyOrigin` 描述最後一次實際建立／更新該鏡頭敘事的來源，不能僅因看過提示便改成新版。每次媒體生成的 source fingerprint 應含該次敘事／基準資訊；舊候選缺來源時標 unknown，不回填偽歷史。

---

## 7. W3：創作版本與製作基準

### 7.1 三種版本各自責任

| 類型 | 可編輯 | 用途 |
|---|---|---|
| 工作中劇本＋tab history | 是；沿用協作規則 | 日常共同修稿與事故復原 |
| 私有 branch／具名 snapshot | branch 可編輯；snapshot 不可變 | 試寫、比較、保留另一種故事走向 |
| productionScriptVersionId 指向的 snapshot | 不可編輯 | 下游可追溯的製作基準 |

- 新的「保存版本」先 flush；同名允許但以 ID 區分，UI 顯示作者／時間，避免名字被當 identity。
- 本人 branch 可以改名、鎖定、明確解鎖；其他人包括 admin 不因此獲得私有 branch 內容。
- 把來源／branch 保存成共享快照須明示「與此製作共享」。共享內容只含選定劇本、必要結構／透鏡；不夾帶私有小說原文、未採用碰撞卡、私人筆記或私聊。
- 不可變 snapshot 不受 `tab_revision` 合併或清理影響。

### 7.2 比較與採用

- 以 stable keys 對齊場次，再在場內做文字 diff；顯示新增、刪除、移動、修改。
- 重複文本／缺 lineage 的場次顯示未對應，可由作者明選；不得默默對位。
- 本版支援「整份採用」與「選定整場採用」，不要求任意跨句三向合併 IDE。
- 採用預覽固定來源版本、目標 docHash、structureHash、選定 scene keys、需要的鎖與使用者權限。
- 套用時核對全部影響區塊及來源身份；任何衝突整批不寫，保存私人候選。
- 成功套用產生原主線自動快照與 audit，保留 annotation reanchor 與現有 block ownership 規則。不直接調用 `repo.save_tab_doc()` 做 blind overwrite。
- 非採用範圍的內容、欄位與資產不得改變。完整替換也不能任意抹掉別人正在編輯的鎖。

### 7.3 確認製作基準

- `productionScriptVersionId` 與既有 `confirmedHash` 一致，對應同一次確認的完整 snapshot。
- 確認目前稿件時，從當前主線建立／重用相同內容 snapshot，再沿用現有資產抽取及確認邊界。不把只建立一筆 snapshot 當作資產抽取成功。
- 選用歷史快照作製作基準，先將其內容安全採用到主線，不能讓畫面主線是 A、下游暗中使用 B。
- 主線後續可繼續修稿，已確認 snapshot 不變；`scriptDirty` 依現有邏輯反映差異。
- 查看、比較、保存版本不改 baseline，不扣 Judge generation cap。
- 既有無 snapshot 的製作保留 `confirmedHash`。只有目前稿件確實符合 confirmedHash 才可補建基準快照；否則顯示「既有基準，內容未留存」，不能從現稿捏造舊基準。
- 舊 extract／confirm 端點成功時也應建立相容 snapshot／pointer，不能只有新 UI 才具有來源記錄。

---

## 8. W4：改稿影響與安全更新鏡頭

### 8.1 狀態不是現有製作 Status 的替代

新增獨立 `storyAlignment.state`：

- `in_sync`：可驗證來源與派生文字符合比較目標。
- `source_changed`：已綁定的來源敘事改變。
- `manual_override`：鏡頭派生欄位被導演自行修改。
- `source_removed`：來源單位已刪除／移出目前稿件。
- `unbound`：沒有可證明的來源對應。
- `ambiguous`：拆分、合併或舊稿轉換後有多個可能對應。
- `kept_intentionally`：導演明確選擇對這個版本保留鏡頭差異。

狀態可附多個 reasons；例如同時 source_changed＋manual_override。不要將這些字串加入／寫入現有 `STATUSES` 製作狀態欄。原有 Approved／Retake 等語意保留。

### 8.2 影響計算

比較的是目標製作 snapshot 與**每顆鏡頭自己的 origin**，不是只比「上一版整集劇本」。部分鏡頭更新後，下一次預覽仍能找到未處理項目。

1. 先以穩定 key 比較場與 beat 的增刪／移動／內容變更。
2. 查明確引用該 beat 或 scene 的鏡頭；多來源鏡頭任一來源改變即列出。
3. 以現有欄位值對比保存的 `derivedFields`，辨認人工覆寫。只有 hash 不同而無文字基底時，標 unknown，不假稱可安全替換。
4. 只變摘要、筆記、字體等不影響產出 metadata，不將所有鏡頭列為需要重拍。
5. Lens、拆鏡策略、實際引用的視覺資產設定變動，列為配置影響；不自動把語法推導的全新 camera 套到已人工調整鏡頭。
6. 場次重排可改播放順序與相容編號；不得據此判定全部媒體內容過期。現有電影順序依 shotIndex，必須將預期順序改動明列，而非只改左側場次清單。
7. 來源不確定只回報候選受影響範圍，不自動建立／刪除／綁定鏡頭。

### 8.3 預覽內容

每顆鏡頭顯示：shotId／顯示標籤、來源場與 beat、舊來源／新來源、目前鏡頭文字、建議文字、人工覆寫、現有媒體、可選行動。

行動集合：

- `update_text`：更新明確選定的 description／dialogue；保留鏡頭身份、camera、duration、seed、overrides、reference、previs 人工設定、候選與選片。
- `add_shot`：為沒有既有映射的新 beat 建立新的文字鏡頭；遵守 200 shots 上限，不生媒體。
- `keep_shot`：保留導演差異，記錄對哪一個版本與哪些 source hashes 作決定；來源再改即重新提示。
- `bind_source`：作者明確選擇來源 key 後建立關聯；這不證明舊 take 曾依此來源拍攝，不回寫假的 generation origin。
- `leave_unresolved`：暫不處理，不阻止繼續寫作或查看既有影片。

本版不在影響面板直接提供破壞性刪除已拍鏡頭；來源刪除後保留鏡頭，由現有管理操作另行處理。

### 8.4 套用原子性

- preview 綁定 owner、episode、目標 version、主線／結構 fingerprint、所選鏡頭各相關欄位 fingerprint、policy／current authority。
- 以 working 稿建立 impact preview 時，先在 preview 內固定其 doc／結構／settings，但不先更動 baseline。只有 preview 已固定 `confirmBaseline:true` 且使用者確認套用時，才原子建立不可變版本、執行既有資產抽取／確認並更新 pointer；apply body 不得臨時將 false 改成 true。抽取可能建立該劇本新引用的文字資產，須列在 preview，不能當作隱藏副作用；不生圖片。
- 以既有 version 作 target 時，其內容／設定必須與當前主線一致才允許確認套用；否則只能比較，先走 promotion 採用。`confirmBaseline:false` 只允許使用目前已確認且有效的 baseline 更新鏡頭，不可繞過 scriptDirty 的既有前置條件。
- apply 時重新驗證來源、權限、鎖與所有選定 targets；任一失效回 409，**整批不寫**。
- 用同一 DB transaction 寫選定文字、來源 metadata、baseline 變更（若本次同時確認）、audit；不在交易中跑模型／FFmpeg／遠端 API。
- 新的窄範圍 apply 不可直接呼叫整場 `build_shots(only_scene=...)` 然後宣稱只改了選定兩顆鏡頭。
- 更新文字令已拍媒體變為「來源已改、需查看」，但不清空 selected media、候選或先前 Approved 紀錄。新授權／重拍依現有流程重新取得。
- `keep_shot` 只記錄 intentional divergence；不修改 origin 指向，不把舊 take 標成新版本生成。
- 同一 apply 重送返回相同結果，不新增第二批鏡頭；成功狀態與回執同交易保存。
- 只有未變的鏡頭不受此次保護範圍擴大影響；不要為了局部更新把整頁永久鎖住。

### 8.5 與片場及在途工作整合

- Shot Stage 右欄增加來源 badge、回到對應場／beat 的入口、與「舊稿媒體」提示；不另開管理頁。
- 生成 dispatch 必須凍結當時鏡頭實際 origin、當時 baseline、row／source hashes 與 intentional divergence；不能把 episode 最新 baseline 自動當成每鏡 origin。晚到輸出仍依原規則作候選／拒絕覆寫，不能在完成時讀最新稿冒充當時來源。
- 改稿不自行 cancel 或 retry 在途工作；顯示「此工作使用較早稿件」。原有 lease／source fingerprint／proposal／winner／privacy 保護完整保留。
- 成片預覽可播放既有選片，但要標示哪些鏡頭來源有差異；不得阻止所有觀看，也不得把未對齊的影片默認稱為新版已完成。
- OpenJutsu 無劇本來源的鏡頭可以維持 unbound，不必為它捏造一段故事。
- 本次支援從鏡頭回到來源定位；從鏡頭改字自動反寫劇本列為非目標。

---

## 9. W5：世界設定與敘事連續性

### 9.1 沿用同一資產身份

有 Soul Cast asset 的角色／地點／道具，顯示名稱、assetCode、圖片、visual prompt、variants 仍從原有資料讀取。`writing_bible` 只補：

- aliases、角色定位、背景、行為限制、人物關係。
- 角色已知資訊、取得／失去物件、關係變動等作者記錄的 scene events。
- 地點／世界的規則、研究筆記、參考來源註記。
- 道具的物理狀態歷程與作用場次。

名稱／外觀等既有欄位在此編輯時仍走原有 asset API；不能在 bible 再放一個可獨立更動的同名欄位。別名是敘事 metadata，不自動重命名資產 ID。

尚未製作的組織、概念、筆記可以獨立存在；只有明確「建立製作資產」才建立 `@CAST/@SET/@PROP`，不因寫筆記自動生成資產或媒體。

### 9.2 場次事件與物件狀態

事件最少包含 `{eventId, subjectId, episodeId, sceneKey, kind, note, productionRelevant}`；跨集資料仍須驗證該 sceneKey 所屬集數與同一 project，不依目前開啟集數偷偷改綁。

- 作者記錄的過去／現在／轉折，不是模型推斷的內心；可記「第三場得知座標有誤」，不可系統自動宣告「他其實已原諒父親」。
- physical state 可引用 scene range；重排後依 stable key 保留，刪場顯示 orphaned event。
- `productionRelevant` 預設 false。只有作者明確把物理狀態／可見設定納入鏡頭參考時，才列入影響預覽；不能把整份私人角色筆記注入每個生成 prompt。
- 本版規則式連續性提示限於缺少引用、兩個互斥且同範圍的明確狀態、已刪場次等可驗證問題；不宣稱完整語意連戲判斷。

### 9.3 出場矩陣與右欄

- 行為角色，列為場次；提供「有明確 @引用的場次／關聯鏡頭」計數。
- 姓名／別名搜尋命中若提供，另標「文字提及」，不等於畫面出場或出鏡秒數；不要與確定引用加總成一個戲份值。
- 點 cell 跳回場次；點鏡頭數跳對應 Shot Stage 篩選。
- 右欄可切設定／筆記，寫作游標不消失；新增、改名、保存失敗有一致提示。
- 此處不是 Console Memory Store 的另一個編輯入口。不得藉此繞過專案／集數 memory 的 admin-only 寫入決策。

---

## 10. W6：全文搜尋與安全取代

### 10.1 搜尋範圍

預設搜尋目前開啟的稿件；可選本集主線、明確選定的其他集、本人來源／另稿、明確選定的具名版本、共享世界設定。

- 不預設搜尋所有歷史、所有私人來源或他人的另稿。
- 對不同 visibility 分開標示；結果含資源、sceneKey、前後文、版本與是否可編輯。
- V1 支援 literal query、大小寫選項；英文 whole-word 可選且標清楚，不假稱支援中文斷詞。
- **Regex 不在本版**，避免不必要的 ReDoS 與語意範圍。UI 不顯示假的選項。
- 搜尋只掃授權文字，不讀媒體 bytea，不掃私聊／agent traces。

### 10.2 取代

- 先 preview，逐筆或選擇全部目前範圍結果；顯示 before／after。
- match identity 綁定 resourceId、內容 hash、block key 與該版 code-point range，不依前端計算的 UTF-16 index 直接寫。
- snapshot 永遠唯讀；不能用「包含鎖定版本」開關修改 immutable payload。可改為建立另稿後取代。
- `@CAST-01` 等標籤是結構引用，普通取代預設不修改；改顯示名稱／aliases 與修改正文命中是分別明選的行動。
- 本版不提供重編 assetCode 的通用 replace；避免破壞已存在的 workflow references。
- apply 前重查各資源 version／hash／權限；選定結果任一變更則整批 409，不部分取代也不重新搜尋後擴大範圍。
- 應用順序依 frozen matches，重疊命中拒絕；不可讓第一次取代製造的字再被第二次重複匹配。
- 完成後可復原：用既有歷史與 branch/source before checkpoint；Undo 仍驗證 current base。

---

## 11. W7：稿件匯入與匯出

### 11.1 匯入格式與上限

- `.txt`、`.md`：UTF-8／UTF-8 BOM；2,000,000 bytes 上限、500,000 Unicode code points／目標文字資源。
- `.docx`：沿用 `file_handoff` 的 8 MiB 壓縮檔、64 MiB 展開、2,000 ZIP entries、10,000 paragraphs 及 XML／路徑安全檢查；抽出文字仍受 500,000 code points 上限。
- 不接受 `.docm`、巨集、外部 relationship 抓取、遠端圖片下載、路徑參數、任意 URL 匯入或密碼保護檔案。
- DOCX 在此是「文字稿轉換」而非完整 Word fidelity；表格、註腳、追蹤修訂、註解、嵌入圖／物件與特殊排版若無法支持，必須在預覽列出不保留項目，不能靜默遺失。
- 可共用現有解析器，但不能假定 `_docx()` 已保留 heading styles／所有 rich text；需補有界識別或明確警告，不寫虛假的自動辨識能力。

### 11.2 匯入預覽與確認

1. 上傳檔案，預設先進本人 `writing_preview`，不立刻改 production tabs。
2. 選擇用途：點子、小說來源、拍攝劇本；以對應 heading grammar 分析。
3. 預覽作品／章節／場次邊界、名稱與正文；可修正邊界、合併與排除。
4. 未辨識出標題時保留完整內容為一節，不自動套故事模板；長稿超界清楚要求拆集，不截斷。
5. 確認建立私有來源／另稿；直接替換主線是另一次明確的差異採用，需 target hash、before snapshot 與 scope 檢查。
6. 取消／重送不得重複建立作品或資產。上傳與確認各有自己的 idempotency identity，確認使用固定 upload hash。

舊 `/files`、`/project-imports` 契約保持；新的寫作匯入不可假冒成另一個未授權的全專案建立器。

### 11.3 匯出

可選目前主線、本人來源／另稿或一個具名版本，並選整集／指定場次；輸出順序、版本名與範圍清楚顯示。

- TXT、Markdown、DOCX：實際檔案下載；共用既有 `python-docx`／file_handoff 能力，不經外部服務。
- 劇本 packet 可選加場次摘要與相關世界設定；預設不包含私人來源、未選版本或全部 bible。
- **PDF 本版明確採「列印／另存 PDF」**：產生固定內容的乾淨列印視圖，使用瀏覽器 print。這不是後端 PDF 下載 API；按鈕不得標成已生成 PDF 或宣稱存檔成功。
- 列印視圖有版本／集數標題、場次分隔、合理 page-break、隱藏工作台控制；無外網字型、圖片抓取或執行使用者 HTML。
- 匯出前固定內容 snapshot；中途有人修改主線不改變這次檔案。二進位回應為 `private, no-store`，檔名去除路徑／控制字元。
- 生成 export 不觸發媒體工作、不變更 confirmedHash、不耗 Judge generation count。原檔下載與整理版輸出須清楚分別。
- EPUB、封面出版排版、真正伺服器 PDF renderer 如未另獲範圍授權，不能順手加進來。

---

## 12. API 契約與錯誤處理

### 12.1 命名與共同規則

新增命名空間：

```text
/aivideo/open/v1/episodes/{episodeId}/writing
```

沿用 Story `{code:0,msg:"success",errorMessages:null,data}` 成功信封。失敗用非 2xx、`DRAMA_*` code、safe message、requestId；新增可機器讀取的 `details`，只回傳目前使用者有權讀的內容。

- 所有請求由 path 解析 episode／project；body 裡不能自帶 owner、admin、project 權限或繞過 scope。
- viewer 可讀共享稿件／版本／設定、使用唯讀搜尋／比較與匯出；不可修改製作、來源或另稿，不可建立／套用寫入 preview。本人私有資料仍須本人＋目前 project 存取資格，admin 不因此可讀。
- 為相容現有 Story HTTP 的「所有 POST 要可寫」前置檢查，僅對本命名空間的 `POST /search`、`POST /compare`、`POST /exports` 建立明列的 read-authorized 例外；export 只產生本人短效 handle，不寫製作內容。其餘 writing mutation 與所有舊 POST 保持原 gate，不能把整個 `/writing` 前綴當作唯讀豁免。
- 所有 POST（包含上述唯讀計算與 export）、PUT／PATCH 保留原有 same-origin／CSRF 與 current membership 檢查。
- POST mutation 帶 `Idempotency-Key`，24h、actor＋credential＋endpoint scope；同 key 不同 body 為 409。
- **對新 writing 路由，權限／owner 檢查必須先於既有 cached idempotency response 回傳。** 不能沿用目前先 cache hit 就直接返回的路徑來洩漏已被撤銷的私有稿件。
- PUT／PATCH 的網路重試使用相同 `clientMutationId`＋相同 body；服務端用 `writing_receipt` 保存 actor＋credential＋episode＋resource＋mutationId 的 body hash 與短期 ACK，避免 ACK 遺失後重送又產生一版。同 ID 不同 body 為 409；回應失效但 receipt 已逾期時按 base/version 檢查，不把過期 base 自動改為最新版再重送。
- `storyRequest()` 增加可選 options，不破壞既有呼叫；保留 status／code／details（可用既有 `ApiError`），允許同一使用者操作重試用同 idempotency key，不能每次 retry 產生新 key。
- GET 不建立 baseline、草稿或版本；初始化另用明確 POST。
- HTTP parser 對 `POST /imports` 在 body 解析前選 raw upload 分支，使用寫作檔案上限；不要沿用目前只識別 `/files` 的 `is_file` 判斷而把 DOCX 當 JSON。其 idempotency fingerprint 包含 bytes hash、filename、用途、path／episode；download／print 另有明確 binary／HTML response 分支。
- 多資源 transaction 的鎖序統一為既有 project advisory lock → 按 key 排序的受影響 tab row locks → 按 ID 排序的 metadata／receipt locks。不要在已持有 tab lock 的 generic save hook 反過來申請 project lock；純 invalidation 可於當前保存交易標記或在下個讀取邊界驗 hash。

### 12.2 端點表

以下路徑相對於 writing base；未列出的寫入字段拒絕，不把任意 JSON merge 到內部 record。

| 方法／路徑 | 請求重點 | 結果／副作用 |
|---|---|---|
| `GET /workspace` | 無 | 主線 doc/hash、結構、共享版本摘要、本人來源／另稿摘要、baseline、保存能力；不一次載入所有全文 |
| `POST /initialize` | `expectedDocHash` | 冪等建立 stable identity sidecar，不能改正文／生成資產 |
| `GET /sources/{idea\|novel}` | 無 | 本人的來源或 null |
| `PUT /sources/{mode}` | `baseVersion,clientMutationId,doc,structure,composition` | CAS 保存私人來源；建立用 baseVersion=0 |
| `POST /script/ops` | 既有 ops/base＋`clientMutationId,session_id` | 共用 block 寫入／衝突與 audit；回 docHash、revision、applied、conflicts |
| `GET /structure` | 無 | 主線 stable keys、定位、plot metadata、structureHash |
| `PATCH /structure/metadata` | `baseVersion,clientMutationId,scenePatches,lanePatches` | 只更動 metadata，不改劇本正文 |
| `POST /previews` | tagged request，見下節 | 建 frozen preview，不變主線／鏡頭 |
| `GET /previews/{id}` | 無 | 本人、同 episode、有效 preview 與目前是否已 stale |
| `POST /previews/{id}/apply` | `selection,expectedPreviewVersion` | 重新驗證、原子套用；selection 必須是 preview 中允許的子集 |
| `GET /versions` | cursor／limit | 共享 catalog，不回整本 doc |
| `POST /versions` | `name,sourceRef,expectedSourceHash,share:true` | 建 immutable 共享 snapshot |
| `GET /versions/{id}` | 無 | 共享快照與 metadata |
| `PATCH /versions/{id}` | `baseCatalogVersion,clientMutationId,name?,locked?,archived?` | creator／admin 管理 catalog；受 pin／lock 約束 |
| `GET /branches` | cursor／limit | 本人另稿摘要 |
| `POST /branches` | `sourceRef,name,expectedSourceHash` | 建本人另稿，保留 lineage |
| `GET /branches/{id}` | 無 | 本人全文與 base/version |
| `PUT /branches/{id}` | `baseVersion,clientMutationId,doc,structure` | CAS 保存；locked 拒絕 |
| `PATCH /branches/{id}` | `baseVersion,clientMutationId,name?,locked?,archived?` | 本人管理；鎖定內容不可藉 metadata 更新 |
| `POST /compare` | `leftRef,rightRef,expectedHashes` | bounded 純比較，不寫主線／建版本 |
| `GET /bible` | filter、cursor／limit | 本製作共享、目前集關聯設定摘要 |
| `POST /bible` | discriminated `asset_extension\|world\|note` body | 新增共享設定；asset 驗證同 project |
| `GET /bible/{id}` | 無 | 完整共享設定 |
| `PATCH /bible/{id}` | `baseVersion,clientMutationId,patch` | CAS 更新允許欄位與事件 |
| `GET /appearances` | selected subjects／episode | 確定引用矩陣，與 mention count 分開 |
| `POST /search` | `query,scope,caseSensitive,cursor?` | 有界授權搜尋；不寫資料 |
| `POST /imports` | raw bytes＋檔名／用途 headers | 私有 import preview；upload request 與 JSON 分支分開限流限大小 |
| `POST /exports` | `sourceRef,expectedHash,sceneKeys?,format,include` | 固定內容並回傳本人短效 download／print handle |
| `GET /exports/{id}/content` | 無 | 再驗權限後輸出 bytes 或安全 print view；不公開靜態 URL |

`sourceRef` 為 discriminated union：`{kind:"working"}`、`{kind:"source",mode}`、`{kind:"branch",id}`、`{kind:"version",id}`。每種 ref 都由服務端解析 scope，不能接受任意 tabKey 或磁碟路徑。

普通保存回應至少含 `clientMutationId,version/docHash,savedAt`；script ops 另外保留 `applied,conflicts,doc`。客戶端只 ACK 對應 localSequence，不能把一份舊成功回應當成最新版正文。

impact apply 的最小選取示意：

```json
{
  "expectedPreviewVersion": 1,
  "selection": {
    "actions": [
      {"actionId": "act_1", "kind": "update_text", "fields": ["dialogue"]},
      {"actionId": "act_2", "kind": "keep_shot"}
    ]
  }
}
```

`act_1` 的 target shot、允許字段、新文字與基底 hashes 全部取自服務端 preview；body 不可夾帶新 shotId、任意 replacement text 或升級權限。要改建議文字，先保存本人候選並重新預覽。

### 12.3 Preview 類型

`POST /previews` 的 `kind` 只允許：

| kind | payload | apply 行為 |
|---|---|---|
| `adaptation` | 本人 sourceRef／hash、targetScenes、breakdown、透鏡與選定取捨 | 將候選採用為主線或本人 branch；主線必須具備建立 preview 時固定的 targetDocHash |
| `promotion` | sourceRef、targetDocHash、選定 sceneKeys／whole | 安全採用快照或另稿，先保存舊主線快照 |
| `structure` | target hash／structureVersion、add／move／split／merge／remove typed operation | 原子修改正文與 stable metadata；不改媒體 |
| `impact` | target version 或 expected working hash、shotIds?、breakdown options、`confirmBaseline` | 確認基準（若要求）＋僅套用被選中的鏡頭文字行動 |
| `replace` | frozen search scope／query／replacement／selected matches | 原子取代可寫資料 |
| `import` | 已存在本人 upload preview reference＋修正後結構 | 建來源／branch；主線採用仍用 promotion |

- preview 包含 `previewId,kind,owner,episodeId,version,expiresAt,sourceFingerprints,targetFingerprints,allowedActions,proposedChanges,warnings,status`；`adaptation` 另含 `candidateBranchId`。候選 branch 依第 3.2 節可繼續保存，preview 本身保持 frozen。
- 預設 30 分鐘有效；逾時只拒絕套用，已建立的候選 branch 不逾期。匯入邊界修正透過新 `kind:import` preview 引用原 upload hash，回報完整保留／明確排除區段；不在前端悄悄改 frozen 結果。
- 大檔原始 bytes／短效 export bytes 到期可在既有請求路徑有界清理，不新增常駐 scheduler；清理不得掃掉 sources、branches、versions 或使用中 references。
- 內容型大型處理在 DB transaction 外用固定輸入執行，再以 hash 驗證寫 preview；不能持有 project lock 做 DOCX 解壓、diff 或檔案生成。
- apply 使用 status CAS，成功 receipt 同交易；過期／已用／不同 body 重送有明確結果，不隱含再次生成。

### 12.4 錯誤碼

| HTTP／code | 語意與 UI |
|---|---|
| 401／既有 auth code | 停止上傳，提示重新登入；保留本人本機未保存稿 |
| 403 或既有 409／`DRAMA_OPERATION_NOT_ALLOWED` | 權限／scope／鎖拒絕，不做 force retry |
| 404／`DRAMA_NOT_FOUND` | 不洩漏他人私有資源是否存在 |
| 409／`DRAMA_WRITING_CONFLICT` | baseVersion／base blocks 已變；保留草稿、開比較 |
| 409／`DRAMA_WRITING_PREVIEW_STALE` | frozen source／target／結構已變；重新預覽，不套舊結果 |
| 409／`DRAMA_WRITING_LOCKED` | 受鎖保護或不可變 snapshot；提供另寫一版 |
| 409／`DRAMA_WRITING_MAPPING_REQUIRED` | 需明確來源對應；不猜配對 |
| 409／既有 idempotency conflict | 同 key 的另一份請求，不自動換 key 重送 |
| 413／`DRAMA_WRITING_LIMIT_EXCEEDED` | 檔案／內容／操作數超界；提供拆稿或縮小範圍 |
| 422／`DRAMA_VALIDATION_FAILED` | 格式、空 query、非法引用或不支援內容；指出可修正欄位 |

錯誤 details 不得回傳 bearer key、signed URL、磁碟路徑、其他作者私稿或未遮罩的 provider 錯誤。

---

## 13. 相容性、安全與效能邊界

### 13.1 既有協作與入口必須一起成立

- 共用 `_run_ops()`／block base、`validate_doc()`、locks、audit、annotation reanchor；新 API 不另定一套較寬鬆權限。
- 同一主線可能由 StoryWorld、舊 DocSurface、Story API、agent proposal、history restore 修改。結構 freshness 不得只依賴新 UI callback。
- 在每個寫作讀取／preview／apply／生成 admission 邊界比較目前 docHash；發現 sidecar stale 即 reconcile 或標 unresolved。實作可在共用保存 seam 加低成本 invalidation，但不能靠定時掃描才保證正確。
- `script/versions` 舊回應保持，不重命名成新 immutable IDs。
- 沒有透鏡／choiceTrace 的 SPEC_13 純函數輸出不變；SPEC_14 的 keep／strike／contrast 邏輯不因新編輯器被刪除。
- 不更改 Console 十二頁、memory admin-only、production policy、Comfy SDK／Router、Judge cap、M8 leases／race／cancel 規則。
- 已有來源範圍、資產讀取與私有媒體 principal 仍是權限上限；寫作 snapshot 不是繞過配置／費用的授權票。

### 13.2 有界操作

- 單文字資源 500,000 code points，且 validated doc 必須符合既有 `MAX_DOC_BYTES = 2,000,000`（UTF-8 JSON）與深度限制；先達任一上限就要求拆稿。emoji、marks、結構 metadata 也會占 bytes，不能只用前端 `.length` 檢查。
- API JSON 仍尊重現有 3 MiB 限制，不以提高全站上限解決。
- 不同 payload 如 `ops` 同時含 base＋new 會超限時，按獨立 block 分批；單一不可再分的 block 提示拆段，不靜默截斷。結構／取代 apply 使用服務端 preview handle，不能把所有 before／after 再塞回 request。
- storyboard 仍最多 200 planned shots；writing source 最多 1,000 結構單位，超過需拆來源／集數。
- 搜尋 query 1–200 字元；單 request 最多 20 個明選資源／合計 2,000,000 code points；結果分頁 100、preview 最多 1,000 matches，超界要求縮小範圍，不能偷偷只替換前半段。
- 比較每份最多 500,000 code points；先按 stable scene／block 對齊。大幅改寫或重複字串時使用有界 diff，必要時退化為「整段不同」；不得對整本直接跑無界 quadratic character diff。
- 資源清單與版本列表不載入全部 snapshot doc／upload blob；按需載入目前稿件與對照兩份。
- 不因文字比較而抓圖片、讀影片 bytea 或打 `/meta` blob 查詢。

### 13.3 效能與真實能力表述

- 以本機 4090 PC、production build、已載入頁面量測：5 萬字／100 場日常輸入回應目標 p95 < 100 ms；不把網路 RTT 包含為編輯器卡頓。
- 50 萬字測試使用按場載入／有界計算；第一次解析可以顯示進度，但不能長時間鎖主執行緒。若未達性能目標，回報真實數據與限制，不刪掉長稿測試假裝通過。
- readonly 搜尋與比較可以離線／本機處理已載入資料，但 server permission 仍控制新讀取與套用。
- 文字工作沒有 provider inference，但不聲稱硬體成本為零；沒有任何假評分、假摘要、假同步完成或假 PDF 成功。

---

## 14. 建議模組與檔案邊界

允許執行者依實際抽取結果調整檔名，但職責要保留；不要將全部功能堆入 `story_openapi.py` 或一個超大 React component。

| 模組／檔案 | 責任 |
|---|---|
| `project_docs/writing_store.py`（新） | scoped typed records、CAS、immutable snapshots、preview／receipt 存取 |
| `project_docs/writing_structure.py`（新） | stable keys、lineage、reconciliation、正文與情節 metadata 純邏輯 |
| `project_docs/writing_versions.py`（新） | compare、branch、promotion、baseline 快照 |
| `project_docs/writing_impact.py`（新） | source binding、影響計算、精確選定鏡頭 apply |
| `project_docs/writing_service.py`（新） | actor／episode 邊界、保存與 preview orchestration、bible／search |
| `project_docs/writing_files.py`（新） | 安全匯入預覽、輸出 packet／列印內容，重用 file_handoff |
| `project_docs/story_openapi.py` | 薄 routing／error details／新路由 pre-replay 授權、既有生成／baseline 接縫、寫作 raw upload／binary export 分流 |
| `project_assistant/story_media_adapter.py`、`project_docs/story_allocation.py`（必要時） | 將來源 provenance 納入既有 frozen admission／輸出回執；不改寫其排程、授權或計費責任 |
| `project_docs/service.py`、`repository.py` | 最小必要的共用保存／invalidation 接縫；不大改既有 doc APIs |
| `ui/src/writing/`（新） | Editor、Outline、Versions、Impact、Bible、Search、ImportExport panels 與純 model functions |
| `ui/src/writing/useWritingPersistence.js`（新） | 保存佇列、journal、衝突、flush／恢復 |
| `ui/src/StoryWorld.jsx` | 組裝三欄與選取上下文；移除自己的孤立文字 state 權威 |
| `ui/src/App.jsx`、`StudioShell.jsx` | surface control、episode／identity切換與真實狀態摘要 |
| `ui/src/storyImport.js`、`storyModel.js` | 新 preview 路徑、結構化錯誤、可重用 idempotency key；保留舊 helper 相容 |
| `ui/src/DocSurface.jsx` | 只抽取需要共用部分，維持舊頁面行為 |
| `ui/src/ShotStage.jsx` | 來源定位與差異 badge，不重做整個片場 |
| `ui/src/i18n/locales/en.json`、`zh-TW.json` | 所有新語意鍵與錯誤／狀態文案 |
| `tests/test_writing_*.py`、`ui/tests/writing*.test.mjs`、browser tests | 本規格行為與回歸 |
| `docs/WRITING_WORKSPACE.md`、`docs/spec16-verification.json`（交付時新增） | 使用方式、真正跑過的證據、限制與剩餘工作 |

新 Python 子 package 如有增加必須更新 `pyproject.toml` packages；若只新增到既有 package 仍需 installed-wheel 驗證。前端修改後必跑 `npm run build --prefix ui`，服務端使用 `static/projects/`。

---

## 15. 實作順序與交付包

這是依賴順序，不是授權自動開多代理。單一執行代理可依序完成；若另獲並行授權，同一 cwd／worktree 保持唯一 writer，共用檔由整合 owner 處理。

### 包 A — 保存與身份基礎（W1、W8 基礎）

- 先建立 scoped persistence／hash／typed records 與 stable structure 純模型。
- 將 StoryWorld 接到保存佇列、journal、surfaceControl；來源可空白、可恢復。
- 舊文件編輯、source mode 切換、App navigation 回歸。
- 到這一步使用者即能真正持續寫作；不能先做一套假版型再留保存為 TODO。

### 包 B — 場次編輯與情節總覽（W2）

- stable scene／beat identity、相容映射、結構 Undo、摘要／情節線。
- 來源章節與劇本場次分開 grammar；按場與全文共用資料。
- 舊整稿寫入與 history restore 的 invalidation／reconciliation。

### 包 C — 創作版本與基準（W3）

- immutable snapshot、私有 branch、鎖定、比較、窄範圍 promotion。
- 新改編候選不直接改主線；既有 API 相容。
- production baseline 與 confirmedHash 一致，舊 revision 合併不能改動 snapshot。

### 包 D — 改稿到鏡頭（W4）

- 新生成來源 metadata、舊資料誠實初始化、per-shot origin。
- 差異預覽／精確 apply／人工覆寫／媒體過期提示／回到來源。
- 在途媒體與部分更新的回歸；不付費驗證語意品質。

### 包 E — 設定、搜尋與稿件進出（W5、W6、W7、W8 完整）

- 同資產敘事擴充、事件／矩陣、可恢復筆記。
- 有界搜尋與取代、文字安全匯入、DOCX／MD／TXT、列印 PDF 路徑。
- 無障礙、排版、雙語、長稿性能與全流程整合。

每包結束記錄：實際修改、通過／失敗／未跑驗證、使用者可用能力、下一包阻塞。**不可用包 A 完成宣稱 SPEC_16 完成。**

---

## 16. 驗收矩陣

以下案例須以真正的資料庫／HTTP／UI 行為驗證，不只 source-code string assertion；純函數另做快測。測試 fixture 可以合成稿件／媒體，不可把它宣稱為真實模型品質驗證。

### 16.1 保存、權限與復原

- **S01**：輸入主線文字，保存後切片場再回來、重整，內容一致；無模型／生成 outbound。
- **S02**：點子／小說／劇本切換不互相覆蓋；未改編的小說原文重整仍在。
- **S03**：中文 IME、快速連續輸入、舊 ACK 晚到，游標與最新 dirty state 不丟。
- **S04**：網路斷線，明示本機保存；重連且遠端未變可同步，遠端已變則比較，不覆寫。
- **S05**：IndexedDB denied／quota full、伺服器 500、401／403 均不顯示假「已儲存」，可下載當前未保存文字。
- **S06**：兩人同 block 衝突保存兩方文字；不同 block 可依既有契約保存，不用全頁 last-write-wins。
- **S07**：同作者兩分頁回應亂序／重試，clientMutationId 冪等且不清掉另一分頁 recovery。
- **S08**：換 actor／撤權／登出後，不能讀前人的 sources／branches／journal，也不能從 idempotency cache 取回私稿。viewer 僅能走明列 search／compare／export，不能透過該例外改正文或建立 writing preview。
- **S09**：清空正文能保存；確認空稿則得到可理解的 validation error。

### 16.2 結構與版本

- **V01**：重排第 1、3 場後 stable keys 不變，舊 sceneId 相容映射正確，shotId／媒體不變。
- **V02**：重複標題與重複段落不誤綁；拆分／合併／刪除／Undo 保留 lineage 或誠實 unresolved。
- **V03**：主線與情節總覽同步，改摘要不改正文、不令全部影片過期。
- **V04**：舊 DocSurface、Story PUT、history restore、agent proposal 改稿，新面板不讀 stale metadata 冒充最新。
- **V05**：同 session 多次自動儲存沿用同 tab revision 時，已保存 snapshot 仍 byte-for-byte 不變。
- **V06**：本人另稿與其他人的讀權限分開；共享版本不夾帶小說原文／私聊／未採用取捨。
- **V07**：locked branch、不可變 snapshot、pinned baseline 的更新／刪除拒絕；可另寫新稿。
- **V08**：採用選定場次只改所選範圍；任何衝突整批不寫，原主線可從 before snapshot 找回。
- **V09**：舊 confirmedHash 與現稿不符時，不偽造舊 baseline；新確認同時有正確抽取與 immutable pointer。
- **V10**：小說中的心理描寫原樣保存；改編候選的檢查不污染原稿；未啟用新欄位的 SPEC_13 輸出相容。

### 16.3 改稿影響

- **I01**：改一個已綁定 beat，只列其實際關聯鏡頭；一對多、多對一皆正確。
- **I02**：鏡頭手改 prompt 後偵測 manual override，預設不覆寫。
- **I03**：只更新 S05 的文字，不改 S06、光學、seed、overrides、previs 人工設定、選片或候選。
- **I04**：部分鏡頭更新後再改稿，依每鏡 origin 找出尚未處理差異，不依整集單一 hash 漏報。
- **I05**：preview 後稿件／鏡頭／鎖／權限變動，apply 409 且沒有部分寫回；未選鏡頭保持原樣。
- **I06**：重送成功 apply 不重複新增鏡頭；status／receipt／資料在同交易。
- **I07**：刪來源不刪媒體，unbound／ambiguous 不靠序號猜配對；legacy take 不被加上假的 origin。
- **I08**：keep_shot 對指定版本有效，下一次來源再改又提示；不修改真正 origin。
- **I09**：在途舊版影片回來不能覆寫新版鏡頭；保留既有 proposal／race／cancel guards。
- **I10**：重排顯示與成片順序一致或有明確尚未套用提示；不是左欄變了但匯出仍偷偷舊序。
- **I11**：單純保存、比較、套用文字沒有 GPU／provider 呼叫，Judge generation debit 為零。

### 16.4 世界設定、搜尋、匯入匯出

- **F01**：同一資產的名稱／圖片／variant 無雙份權威；私有來源不經 bible 對其他人洩漏。
- **F02**：角色矩陣分清標籤引用與姓名提及；事件跨排序保留，刪場事件顯 orphan。
- **F03**：literal search 的 Unicode／emoji／大小寫與 code-point ranges 正確，token 引用不被普通 replace 破壞。
- **F04**：取代前後文可選；任何選中資料 stale 則整批不改，immutable／鎖定版本不可被旁路修改。
- **F05**：DOCX ZIP bomb／path traversal／DTD／XXE／external relationships／巨集／大檔被安全拒絕，沒有外網 fetch。
- **F06**：匯入預覽取消不改主線；標題辨識可修正；無標題稿完整保留；多次確認不重複建立。
- **F07**：TXT／MD／DOCX 實際下載可重新開啟，版本／範圍／繁中／英文字正確；不含未選私有內容。
- **F08**：列印視圖乾淨可讀、無執行使用者 HTML；PDF 入口如實稱列印／另存，不冒充直接下載。
- **F09**：download／print handle 撤權後失效，沒有公開靜態私稿 URL；preview 到期仍可保留作者候選。

### 16.5 瀏覽器旅程與效能

至少在 production build 做以下互動，保存畫面／操作結果與候選 commit：

1. 英文新製作：點子保存 → 預覽 → 修改候選 → 採用 → 建立文字分鏡。
2. 繁中小說：匯入 → 調整章節 → 重整恢復 → 改編，原文內心描寫不被改掉。
3. 已有成片：另稿比較 → 選一場 → 預覽影響 → 只更新兩鏡 → 舊影片保留。
4. 兩個瀏覽器 context 同稿衝突／斷線恢復；不能只 mock 成「成功」。
5. 全文搜尋角色改名 → 選擇取代 → `@CAST` 身份與影片引用不變。
6. 匯出指定版本 DOCX、開列印視圖、實際確認排版；取消 print 不誤報完成。
7. 1280×720、1920×1080，以及約 768 px 寬度：編輯器可用、面板不遮操作、keyboard focus 不遺失。
8. 5 萬字／100 場與 50 萬字壓力 fixture：記錄輸入、切場、比較／搜尋的實際耗時；不宣稱未量測性能。

---

## 17. 執行驗證、文件與完成回執

### 17.1 驗證指令原則

使用專案既有 Python 環境及隔離測試資料庫，勿對使用者正式製作資料跑破壞性 fixture。`tests/test_story_openapi.py` 的 HTTP 測試需要 `OPENBENCH_TEST_DB_URI`；沒有 DB 的 skip 不是通過證據。

```bash
# 新增測試檔後，以實際檔名執行針對性測試
python -m unittest discover -s tests -p 'test_writing_*.py' -v
python -m unittest tests.test_story_openapi tests.test_file_handoff -v
npm test --prefix ui
npm run build --prefix ui

# 整合候選再做既有全套；遇到環境缺件如實記錄，不偽報 zero skips
python -m unittest discover -s tests -p 'test_*.py' -v
python -m build --wheel
```

- 執行新 browser journeys；對固定候選做真正 HTTP／PG／UI 測試，source assertion 不能替代。
- 在 checkout 外安裝實際 wheel，驗證新模組、migration（若有）、static resources、基本 API 與檔案輸出。
- 測試文字流程必須可以禁止全部 provider／GPU outbound；媒體 race／late return 使用可辨識 synthetic fixtures，不啟動真實收費工作。
- 只改 Markdown 的規格撰寫回合不需要跑以上建置；這些命令是交給後續實作代理的。

### 17.2 文件交付

完成時新增 `docs/WRITING_WORKSPACE.md`，說明：

- 已儲存／本機暫存／共享／個人另稿／製作基準的差別。
- 改編預覽、比較、採用、局部更新、保留差異的操作。
- 舊專案如何識別 unbound／legacy baseline，如何手動對應。
- 支援的匯入／匯出格式、PDF 為瀏覽器列印、字數／引用統計口徑。
- 長稿、斷線、衝突與恢復限制。

更新 `docs/STORY_WORKBENCH.md` 與必要 README 的當前能力描述；不得覆寫 SPEC_06～15 的歷史證據。`docs/spec16-verification.json` 記錄實際 candidate、命令、結果、skips、browser artifacts、未驗項目與剩餘問題，不套用過去通過總數。

### 17.3 完成定義

只有以下全部成立，才可稱 SPEC_16 實作完成：

- W1～W8 的所列範圍可操作，不是只做入口、假資料或 TODO。
- 主線唯一權威、私有範圍、不可變版本、穩定身份與精確改稿影響均有行為驗證。
- 既有腳本／表格／片場／提案／媒體安全沒有被新捷徑繞過。
- Production frontend 已重建，installed-wheel 與必要 DB 測試實跑。
- 已知不支援與未驗證項目誠實記錄；整體產品接受仍由使用者決定。

---

## 18. 給執行代理的交接提示

> 你接手 ZeroField 的 SPEC_16 實作。先讀專案 AGENTS、目前工作樹與本文件第 1 節的基底；不要把歷史「下一步」當作重做指令。保全既有未提交修改並確認檔案 ownership。
>
> 目標是在現有 Story & World／Shot Stage 中提供可靠寫作、結構總覽、創作版本、製作基準、局部改稿影響、世界設定、搜尋與文字稿進出。不是新建小說 SaaS，不新增頂層導航或另一套 scheduler。
>
> 依包 A→E 推進。先解決真實保存與身份，再做版本與鏡頭關聯。不得把 tab.revision 當不可變 hash，不得把舊位置型 sceneId 當永久身份，不得用 whole-page blind overwrite 省略衝突保護。
>
> 文字自動保存不生成媒體；舊鏡頭與候選保留；原文不被 screenplay sanitization 改掉。新 API 對 replay 也重查現在的權限，私有來源與另稿不對 admin 自動開放。沿用現有 M8／allocation／policy／billing 邊界。
>
> 有正常工程選擇時在已授權範圍內自行處理並記錄；不要為每個按鈕問使用者，也不要默默擴大到雲端同步、付費 provider 或新模型。這份規格本身不要求使用 skill、不授權新增代理席位。若收到另外的執行授權，遵循該回合指定的角色與工具限制。
>
> 最終回報整批可用成果、實際驗證、未完成項目與限制。只完成某一包時明說，不把部分完工當成 SPEC_16 完成。
