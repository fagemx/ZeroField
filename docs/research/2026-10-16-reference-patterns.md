# 成熟工作台互動模式與採用邊界研究

日期：2026-10-16。裁定依據：[研究任務 d-001](2026-10-16-research-brief.md)。本輪只研究，不安裝依賴、不執行參考庫、不改產品、不提交。七個既有參考庫以 [lock](../references/open-source-lock.json) 的 commit 為準；新增比較僅 Glide Data Grid、AG Grid Community 兩個候選。

證據標記：`code` 表示查過原始碼、manifest 或授權文件；官方產品文件另註「文件宣告」，不等同操作實測。`hypothesis` 表示由證據推導的設計、優先序或待驗證門檻。本代理沒有執行這七個產品，因此沒有以 `observed` 宣稱其操作已實測，也不宣稱新手必然會用。

## 1. 研究結論與對初稿的修正

1. **[hypothesis] 下一個交付單位應是「能連續完成一項工作」，不是「增加一個視圖」。** Baserow 的 grid 將選取、剪貼簿、權限、貼上等待與錯誤處理接成一路；Teable 把選取狀態與編輯狀態分開，處理 Enter、F2、Escape 及中文輸入組字。[B1][T1][T2] 因而建議暫停以 U1 三視圖作首要產品化順序，先驗證匯入後直接修改、批次貼上、復原、再匯出的閉環。圖庫對美術有價值，但不能代替表格基本操作。
2. **[hypothesis] 先分清工作簿與資料表。** 任意座標、公式、合併儲存格與跨工作表引用，是 workbook 語意；每列一件工作、每欄一種型態、圖庫與看板，是 record-table 語意。Teable 的 view 有獨立 id、sort/filter/group，選取寫入則回到 recordId/fieldId；Univer 則把插列、改格、filter ranges 都納入 workbook command/mutation。[T2][T3][U1] 兩者不能只靠同一個「Excel」標籤視為可互換。應先用三類日常檔案驗證映射，再決定 grid 或 workbook 元件。
3. **[hypothesis] React Flow 可以解決畫布操作底座，不能單獨解決流程可用性。** 官方範例只把 nodes/edges 交回應用狀態，連線合法性由應用提供；Activepieces 在其上另做加步驟入口、設定驗證、樣本資料、輸入/輸出/日誌及重測。[X1][X2][A1][A2][A3] 因而 U3 應先定義完整的「建立 → 配置 → 單步 → 核對 → 執行 → 恢復」互動契約，再決定替換 SVG 的實作順序。
4. **[code → hypothesis] 免費 grid 並沒有已證實的即插即用答案。** Glide 穩定版 6.0.3 的 peer range 未包含 React 19；main 的 6.0.4-alpha25 才包含 19。AG Grid Community 是 MIT，但官方 Cell Selection、Clipboard 屬 Enterprise。[G1][G2][G3][AG1][AG2][AG3] 先做相容性與操作實驗，不能以 `--force` 安裝成功或 demo 流暢判定可採用。
5. **[hypothesis] 直接修改、代理提案、流程審核、復原應共用一套資料變更契約，但不應共用一種使用者互動。** 使用者親手改普通儲存格可直接保存；代理批次寫入需核對提案；流程審核需綁定當次 run 與資料版本。Baserow 的 undo 是具 user/session/scope 的 action；Univer 區分 view operation 與持久 mutation；Activepieces 的暫停是持久 waitpoint。[B3c][U1][A6] 因而不能用「有版本歷史」代替 Ctrl+Z，也不能用「待核准提案」概括所有流程等待。

## 2. 從完整工作來看成熟表格

| 工作中的問題 | 可證實的成熟模式 | OpenBench 的 take / adapt / avoid |
| --- | --- | --- |
| 使用者想修改一格，卻不知道是選取還是正在輸入 | **[code]** Teable 非編輯狀態下 F2 進入編輯、Delete 處理選取；Enter 在編輯中保存並移動，在非編輯中啟動編輯；`isComposing` 時不處理 Enter；Escape 離開編輯。[T1] | **[hypothesis] Take：** 明確的 active cell、range、editing 三種狀態。**Adapt：** 單擊定位、雙擊/F2 編輯、直接打字取代，Enter/Tab 提交並移動，Escape 取消未提交草稿。中文組字與多行換行需用本機輸入法驗證。**Avoid：** 每格都必須開列詳情或先找小按鈕。 |
| 排序或篩選後，改到錯列或貼到錯欄 | **[code]** Teable 將顯示位置解析為 recordId/fieldId；實際 updateCell 用 fieldId，active cell 同時保留 identity 與顯示座標。[T2] Baserow 用 row.id 與 field.id 找視圖位置。[B1] | **[hypothesis] Take：** 顯示座標與寫入 identity 分離。**Adapt：** 代理、貼上、鎖與提案都使用 table/row/column ID + revision。排序後仍追蹤同一筆。**Avoid：** 依目前陣列索引永久識別欄位，或讓圖庫/看板重新編號原資料。 |
| 從 Excel 貼入一塊資料，換行被拆成新列或型態悄悄錯誤 | **[code]** Baserow grid 對單格/多格貼上走不同入口，統一送到 pasteData；處理 readonly、權限、等待狀態與超量提示。[B1] **文件宣告：** cell-level 與 in-editor 剪貼簿不同；TSV、HTML table 與 rich clipboard 各有用途，純文字可能失去選項/關聯 ID。[B2] | **[hypothesis] Take：** 多格貼上是一個批次動作；型態由欄位解析。**Adapt：** 引號、內含 Tab/換行、空值、前導零、百分比、日期與公式要有 fixture；超出表格時顯示將增加幾列。**Avoid：** 簡單 split('\n')/split('\t')；不提示就截斷資料。Baserow 的有提示截斷亦不宜照抄為 OpenBench 預設。 |
| 一次貼錯幾十格，希望回到貼上之前 | **[code]** Baserow action 保存參數、user/session/scope/action_group；undo 依 user/session/scope 找操作，群組用 transaction.atomic 回滾。[B3c][B3m] **文件宣告：** 需檢查權限，別人刪欄導致 undo 失敗時須回報；該文件仍以 category 稱 scope，不應直接複製舊 schema 用語。[B3] Univer command 可產生正向與反向 mutation，與視窗捲動的 operation 分開。[U1] | **[hypothesis] Take：** 一次貼上/填滿/欄位轉換為一個可復原命令。**Adapt：** 復原也做權限與版本校驗；同格已被別人改過時顯示差異，不能覆蓋。**Avoid：** 只回滾 React state、整個 tab 回舊 revision、或讓 Ctrl+Z 也撤回另一人的資料。 |
| 改欄位型態後，原資料或公式消失 | **[code]** AFFiNE 以 propertyId 讀全欄內容，查 from/to converter，連同 property metadata 與 cells 更新；無 converter 的 fallback 可能產生 undefined cells。[F1] **文件宣告：** Baserow 說型態轉換可能丟值，提供 undo 建議。[B4] | **[hypothesis] Take：** 欄位有穩定 ID、型態、設定與轉換器。**Adapt：** 轉換前顯示可轉/無法轉/受影響公式與流程，整組原子提交，保留逆向資料。**Avoid：** 把改欄位型態當換顏色，或直接採用會清空資料的 fallback。 |
| 瀏覽圖片或狀態後，要回到同一筆工作 | **[code]** Baserow Gallery 用 view 的 cover field ID、可見欄位排序與 RowEditModal。[B5] Teable view options 將 stackFieldId 與 coverFieldId 分開，view schema 保存 sort/filter/group。[T3][T4] AFFiNE 同一 data source 提供多個 view presets 與 view manager。[F2] | **[hypothesis] Take：** 同一筆資料的不同投影；列詳情保留較長文字、附件、討論與歷史。**Adapt：** 視圖有名稱、用途、篩選/排序、選取範圍提示；狀態搬移仍是欄位寫入。**Avoid：** 三個按鈕只有外觀變化、切換後丟選列、所有卡片只顯示第一欄、影片播放器回流。 |

**[hypothesis] 表格的最低連續操作契約**（由上表模式推導，尚待使用者測試）：

1. 匯入後知道正在看哪份檔案、哪個 worksheet/table、多少列，以及哪些內容只保留於原檔。不要讓使用者猜目前畫面是否等於完整 Excel。
2. 不打開助理也能完成：選格、連續輸入、移動、範圍選取、貼上、清除內容、復原、重做、調欄寬、找資料、篩選、匯出。
3. 小的正常編輯就地保存；顯示保存中/已保存/失敗。失敗時保留輸入、定位失敗格並能重試；不能只彈一下通知然後把草稿丟掉。
4. 選取儲存格範圍與「把這幾列交給代理」分開；批次入口清楚顯示筆數與範圍。使用者可直接看見被篩掉的選列是否還算在內。
5. 對不可編輯欄顯示原因（公式、權限、鎖、來源限制）；Tab 不跳進死路。詳情面板用於需要較大空間的工作，不當單格編輯的必經之路。
6. 改欄位、刪欄、重匯入與代理填欄都先檢查相依；有歧義時可取消並維持完整原狀。這是表格信任基礎，先於大量擴充新視圖。

## 3. 成熟節點產品如何支持「做完一件事」

| 工作階段 | 原始碼／官方證據 | 建議互動與避免事項 |
| --- | --- | --- |
| 建立第一步、接下一步 | **[code]** Activepieces 的加步驟節點在插入位置開 PieceSelector，包含 readonly 與拖放提示處理；同一元件也使用 React Flow Handle。[A1] | **[hypothesis] Take：** 在上下文按「＋ 下一步」並自動接線。**Adapt：** 空流程先選資料來源或從已選資料建立；預設給清楚順序，自由分支/匯流按需展開。**Avoid：** 首屏要求使用者先擺卡片、填內部 ID、找很小的接點才能開始。 |
| 設定這一步要做什麼 | **[code]** Activepieces 以 essential/advanced property 分組；Advanced 預設折疊，內部有驗證錯誤時自動展開一次且不反覆強制開啟。[A4] | **[hypothesis] Take：** 固定設定面板＋必要欄位。**Adapt：** 先顯示工作名稱、來源、範圍、動作、輸出位置；供應商細項、重試、逾時等放進進階。錯誤必須可定位。**Avoid：** 所有 JSON/工程參數平鋪在節點，或用折疊把必填錯誤藏住。 |
| 把前一步產出帶進來 | **[code]** Activepieces 無樣本時明示需先測試來源步驟，且提供跳回來源的按鈕。[A2] **文件宣告：** 可展開上游輸出的欄位並插入輸入位置。[A5] | **[hypothesis] Take：** 可見樣本與欄位選擇器。**Adapt：** 呈現來源 tab/table/field、樣本值、型態、row scope；線表示先後相依，資料映射另顯示，兩者不可混淆。**Avoid：** 靠使用者手寫 `{{node.output.foo}}`，或把「已連線」當成「已完成資料配置」。 |
| 只試這一步、看懂結果 | **[code]** Activepieces 的測試頁在 invalid/loading 時禁用測試，呈現 sample input、output、last test date，提供錯誤與日誌、取消與重測。[A3][A3v] Windmill 的 Test flow 與 Test up to 是分開的入口。[W1] | **[hypothesis] Take：** 樣本輸入 → 本次輸出 → 錯誤/日誌 → 重測的工作循環。**Adapt：** 三個不同語意「只試這一步」「測到這一步」「從這裡繼續」不得混用；顯示實際選取的一列與資料版本。**Avoid：** 標作單步卻啟動下游；把沿用舊樣本標成新測試成功；把會呼叫外部服務的 test 暗示為無副作用。 |
| 人工核對後才往下 | **[code]** Activepieces waitpoint 先寫 PENDING、checkpoint 成 PAUSED，收到訊號後重建執行上下文；重複 callback 與 resume-before-pause 有處理。[A6] **文件宣告：** Windmill suspend/approval 在條件達成或取消後續行。[W2] | **[hypothesis] Take：** 持久等待、可取消、可恢復。**Adapt：** OpenBench 站內核對 run/node/row IDs、輸入輸出 revision、通過/退回理由；只繼續核准範圍。**Avoid：** 在瀏覽器保留一個 pending Promise 當審核、把秘密 URL 傳訊模式照搬、只把卡片狀態改綠就當真正續跑。 |
| 失敗後繼續工作 | **[code]** Activepieces 將 error handling 放進步驟設定，測試結果呈現 error/logs 與 retest。[A3v][A4p] **文件宣告：** Windmill 有針對步驟的測試與 retry 設定。[W3] | **[hypothesis] Take：** 把失敗發生的位置與原因留在同一工作脈絡。**Adapt：** 分清輸入錯誤、認證/供應商不可用、執行失敗、等待審核、輸出提案衝突；重試前顯示將重跑的範圍及已有產出。**Avoid：** 只有整條重跑、只有 spinner、重載即失去 run、重試導致重複寫入或生成。 |

**[hypothesis] 節點卡保持可掃讀，細節在旁面板。** 卡片只呈現名稱、來源/輸出簡述、配置狀態與最近執行狀態。選中卡片後，固定面板展示「設定／輸入輸出／執行記錄」，錯誤可直接回到相關欄位。此建議由 Activepieces 的 step settings + sample viewer 分工推導，尚未以 OpenBench 使用者測過。[A3][A4]

**[hypothesis] 新手入口應支援漸進展開，仍保留通用能力。** 在文件或表格選好範圍後，描述一次工作；成功的手動/代理工作可再存成可重複流程。初期不要求每個任務先建 DAG，也不移除進階使用者的任意 doc/sheet/flow 組合能力。範本應能預覽產生哪些分頁、資料欄與步驟，建立後全部可改；預設新專案仍空白。依據是 contextual add、sample-first、advanced disclosure 模式；不是外部產品已證明 OpenBench onboarding 的結論。[A1][A2][A4]

## 4. 三個需要明確否定的捷徑

### 4.1 「TanStack Table 就能讓 Excel 好用」

**文件宣告：** TanStack Table 是 headless，不產生 DOM，由應用提供 markup/style。[TS1] **[hypothesis]** 它適合作為排序、篩選、欄位與 row model 的組件，但選格/多格選取、輸入法、editor lifecycle、剪貼簿、填滿、快捷鍵、撤銷、保存失敗、公式語意及匯出保真仍要有人負責。這些正是本輪問題，不能以引入 table engine 替代工作體驗設計。若既有需求最後被確認只是「可排序的唯讀資料清單＋少量表單編輯」，才可把它排在前面；目前不可直接作 Excel 方案裁定。[B1][T1][U1]

### 4.2 「React Flow 裝了，節點就好用」

**[code]** SaveRestore 範例維護 nodes/edges，Validation 範例由應用傳 `isValidConnection`；它們沒有給 OpenBench 定義 input mapping、row scope、provider configuration 或 approval semantics。[X1][X2] **文件宣告：** React Flow 提供 keyboard/focus/ARIA 能力，但自訂節點需要正確配置；官方 Undo/Redo 範例標為 Pro Example。[X3][X4] **[hypothesis]** 可以採其 MIT 核心、獨立實作 command history；不能把全部網站範例都當 MIT，也不能把 browser computing flow 當持久化 Worker engine。採用門檻應包含操作完成率與資料/執行語意，不只是位置可保存。

### 4.3 「Gallery / Kanban 就是產品化」

**[code]** 成熟 view 建立在可辨識的 records/properties、視圖設定與列詳情上。[B5][T3][T4][F2] **[hypothesis]** 圖庫解決圖片掃讀，看板解決分組移動；兩者不解決直接填表、貼上、公式、保存、提案衝突或交接。可用性不能以三視圖都有畫面計分。先確立同一筆資料如何被找到、編輯、追蹤及復原，視圖再服務具體任務；圖庫可在美術驗證中較早加入，但不應在全產品路線圖壓過基本資料操作。

## 5. 元件比較：只選兩個新增候選

| 候選 | 可核對的能力與邊界 | 本輪判斷（均非已採用） |
| --- | --- | --- |
| 現有實作＋TanStack Table | 文件宣告為 headless。[TS1] OpenBench 仍需自行負責完整編輯互動。 | **[hypothesis]** 作基準組，衡量保留現有資料契約能否達門檻。不是因為「已經有程式」就預設最省成本；應把補齊 keyboard/clipboard/undo 的成本算進去。 |
| **Glide Data Grid**（新增候選 1） | **[code]** MIT；stable 6.0.3 的 React peer range 為 16/17/18，npm gitHead 為 `2abe757e65cc7c38ab4f9464c229db27be4c1a8e`；main 為 6.0.4-alpha25 並列 19。[G1][G2][G3] 文件/API 有 batch edits、paste、fill、validation、自訂 editor；資料保存由應用處理，貼超現有列數不自動增列。[G4] | **[hypothesis]** 可作 record grid 的優先實驗候選，但 React 19 穩定發布相容性是前置門檻。不能用 alpha 功能推斷 stable，也不應先降 React 來迎合元件。需證明中文 IME、焦點/鍵盤、螢幕閱讀、圖片/狀態 editor、批次保存與 rollback。公式引擎、跨版本 undo、XLSX 保真不由這份 API 證據保證。 |
| **AG Grid Community**（新增候選 2） | **[code/文件宣告]** Community MIT；Enterprise 另授權。官方 Clipboard 與 Cell Selection 文件明標 Enterprise；Undo/Redo 針對 cell edit，排序、篩選、分組與其他資料更新會清除其堆疊。[AG1][AG2][AG3][AG4] | **[hypothesis]** 作成本邊界對照，不能拿 Enterprise demo 當 Community 可交付能力。若要求免費核心且必須 Excel 範圍選取/貼上，不是即用選擇；需明確接受自行補齊，或另作商業依賴決策。現階段不建議為它重新自製核心剪貼簿。 |
| Univer（既有參考） | **[code]** 核心 Apache-2.0，command/mutation 模型涵蓋工作簿操作。[U1][L7] **文件宣告：** 官方 Office 轉換路徑使用 `@univerjs-pro/*exchange-client` 與 conversion backend；snapshot 模式不需 collaboration，但仍需 conversion backend。[U2] | **[hypothesis]** 若真實樣本證明 workbook 語意不可缺，是應認真驗證的架構候選；不能僅以「Canvas 難自訂」排除。也不能聲稱 Apache 核心等於官方 Excel 匯入匯出皆免費。先驗證既有 source_blob/OOXML patch 能否配合 command adapter；兩個引擎不可各自算出不同真實值。 |
| React Flow（既有參考） | **[code]** MIT 核心提供 nodes/edges、變更回呼、合法性接點。[X1][X2][L6] | **[hypothesis]** 適合畫布底座；保持 OpenBench DAG/Worker 為執行權威。必須連同設定、資料映射、單步、狀態與復原契約一起評估，不能只做外觀替換就宣告完成。 |

**[code] 相容性查核再現（唯讀，沒有安裝）：**

```powershell
$pkg = Invoke-RestMethod 'https://registry.npmjs.org/@glideapps%2fglide-data-grid/6.0.3'
$pkg | Select-Object name, version, license, peerDependencies, gitHead
```

上述 6.0.3 是本日查詢 latest 的結果；主線網頁與 docs 可能晚於穩定版。後續實驗必須鎖實際 tarball 版本和 checksum，而不是把本文當日後 latest 的證明。[G1][G2]

## 6. 整體架構備選與判斷條件

| 路線 | 使用者工作對應 | 架構與主要代價 | 選擇／退出條件 |
| --- | --- | --- | --- |
| A. 保留 OpenBench domain，換成熟 record-grid 互動底座 | 每列一項工作；辦公填表、資產審核、分鏡追蹤；文件、提案、跨頁代理共用 | **[hypothesis]** 保留 doc、row/column IDs、revision、proposal、source_blob、DAG。grid 座標透過 adapter 轉 ID；所有更動經命令/交易；view 只保存顯示方式。元件須支持目前 React 與自訂 cell。依據 [T2][T3][U1]。 | **[hypothesis]** 若三情境的真實樣本多為規則表，且匯入/匯出與操作門檻全過，優先選。若為支援 workbook 不斷在 grid 上重造 merge/跨 sheet/完整公式，停止擴大並評估 B。 |
| B. 明確增加 workbook surface，record-table 仍服務工作管理 | 在瀏覽器內真正編輯工作簿的人，同時有圖像資產/工作列管理 | **[hypothesis]** 以 Univer 類 workbook engine 保存 workbook identity/command；record table 是明確選出的表或映射，不雙向隱式同步。來源工作簿/衍生工作表的關係必須可理解，指定單一寫入權威。依據 [U1][U2][T2]。 | **[hypothesis]** 只有真實樣本證明 A 無法滿足、且映射/公式/匯出一致性通過才升級。不在第一輪同時開發兩套資料權威，也不把「所有 Excel 功能」列為未定義承諾。 |
| C. 以成熟產品作基底／外接完整平台 | 需求主要就是該平台工作方式，可接受其資料/權限/部署模型 | **[hypothesis]** Fork Baserow/Teable 或讓外部平台成主資料庫，會重新分配 identity、權限、revision、proposal、file handoff 的責任；與現有 OpenBench 雙寫會增加一致性問題。技術與授權範圍見 [L1]–[L5]。 | **[hypothesis]** 不預先禁止，但須先完成代表流程原型與遷移/部署/維護估算。若只是為了換 grid/flow UI，不足以支持整套平台改造；本輪不推薦直接整庫搬入。 |

**[hypothesis] 建議先評估 A 與 B 的窄範圍實驗，而不是現在做不可逆選型。** 測試矩陣相同、原始樣本相同、輸出比對相同；只有能完成工作且總成本較低的方案才進施工。元件替換與產品資料模型調整分開量測，但不能分開驗收。

**[hypothesis] A/B 都需要的共同邊界**（依 [T2][U1][B3][A6] 推導）：

- 領域物件：project、tab、source file、table/workbook、row/column identity、asset reference、revision。不要讓 grid 的 row index 或 React Flow 的 component state 成為資料權威。
- 變更：edit/paste/fill/schema/proposal-apply/undo 均產生可驗證命令；攜帶 actor、base revision、target IDs、before/after、原子群組。後端統一驗證權限/鎖/相依。
- 顯示：排序、篩選、欄寬、隱藏欄、圖庫封面、看板分組屬 view；viewport 與選取可為 session state，若保存需明示個人/共享。
- 執行：flow definition、run snapshot、step attempt、row scope、sample input/output、waitpoint/approval、artifact/proposal 分開。圖上狀態由持久 run 推得，不能靠卡片本地變色。
- 提案與審核：預覽展示來源、目標與影響；核准用原始結構化 target；同版本命令可原子套用，過期則重算或要求重新核對。

## 7. 元件技術驗證規格與通過門檻

以下全部是 **[hypothesis] 提議門檻**，目前沒有跑過，不是現成驗收結果；與可靠性代理及使用者共同校準後才實作。

### 7.1 共用樣本與錄製方式

| 樣本 | 代表工作 | 必須保留的內容 |
| --- | --- | --- |
| 辦公/行銷：1,000 列 × 20 欄、3 worksheets | 放入會議/規範文件與 Excel，修數字、貼 50 × 8 區塊、篩選、交代理新增摘要/優先級提案、核准、匯出 | 前導零、中文多行、日期、空值、百分比、公式與計算結果分別保留；非目標 worksheet 不變；不支援項目清楚標示 |
| 美術：60 筆資產、兩個圖片欄、長規格與審核狀態 | 讀規範、比較圖片、標註、修改多筆狀態、退回其中一筆、匯出交接 | 同 row ID 跨 grid/gallery；空封面/未知狀態不丟列；圖片不阻斷選格；影片僅附件/下載 |
| 自由組裝工作流（可含影劇追蹤）：60 列、5–8 個節點、分支/匯流及人工審核 | 一列單步取得樣本、修設定重測、選 10 列執行、只核准部分列、故意失敗後恢復 | 單步不觸發下游；重試不重複寫回；未核准列不通過；保留文件、表格與輸出的可追溯關係；不用影片生成/播放作通過條件 |

每個 fixture 同時跑「匯入前 → UI 操作 → API/DB → 重載 → 匯出重開」比對；結果分開記錄資料正確性、操作失誤、時間、求助次數與環境。範例庫只作能力參考，不當效能或易用性實測。

### 7.2 Grid 實驗：任一重大資料錯誤即不通過

| Gate | 操作 | 通過條件 |
| --- | --- | --- |
| G0 版本/授權 | 固定 React 19.2 與候選正式套件版本，核查 license/peer range；列傳遞依賴 | 正常解析，不靠強制忽略 peer；沒有未裁定商業模組或浮動 main。否則停止該候選，不開始大量 adapter 開發 |
| G1 連續編輯 | 全程鍵盤輸入 20 格；中文 IME、數字、長文字；F2/Enter/Tab/Shift+Tab/Escape | 不誤提交組字、不丟焦點、不跳錯格；Escape 只取消當格未提交變更；不用開 20 次列詳情 |
| G2 多格貼上 | 從真實 Excel 複製 50 × 8，含內嵌換行、引號、空白、前導零；貼在排序/篩選後的表 | 預定 target IDs 全部一致；型態失敗定位、無靜默截斷；一次批次保存，一次 undo 可恢復；增列範圍可見 |
| G3 保存與復原 | 故意 HTTP 失敗、延遲、衝突；另個 session 改同格；已保存後 undo/redo | 草稿不消失；失敗不偽裝保存；重試不重複；不能撤回他人修改；部分失敗規則可理解 |
| G4 欄位模型 | 改名、移動、隱藏、轉型、刪欄；有公式與 flow 引用；重匯入有重名欄 | 改名/移動 identity 不變；危險轉型有影響預覽；不猜錯欄；拒絕時整體保持原狀 |
| G5 自訂媒體與可及性 | 圖片、附件、狀態、長文字 editor；鍵盤走查；Windows 輸入法/瀏覽器縮放 | 圖片/附件操作可透過鍵盤完成且回焦；清晰 focus/label；120–150% 縮放仍能保存/取消；影片不渲染播放器 |
| G6 性能 | 1,000 × 20 日常表；10,000 × 50 壓力資料；記錄機器與瀏覽器 | 建議目標：日常輸入回饋 p95 < 100ms、篩選/定位 < 300ms；2,000 格貼上 < 2s 顯示結果/進度。HTTP 保存另計；壓力表不假死/丟輸入。不以平均 FPS 代替任務成功 |
| G7 交接 | 完成變更後 reload/export，以 Excel/解析器重開對比 | 支援範圍內公式、非目標資料及樣式符合契約；不支援內容不靜默改壞。任何錯格、遺失、公式語意漂移皆不通過 |

### 7.3 Flow 實驗：畫布 + 設定 + 執行一起驗證

| Gate | 操作 | 通過條件 |
| --- | --- | --- |
| F0 adapter | 匯入含未知屬性的既有 flow，移動、改名、加線、保存重載 | 未操作的 provider/limb、scope、row_source、target、edges 與未知欄位不變；readonly 不可寫 |
| F1 新手建流程 | 從選定表格建立「讀取 → 整理 → 核對」三步；再在中間插一步 | 不必先懂 node ID/JSON；接線結果可見；自動排列後仍能找到剛加的一步；可鍵盤選節點及配置 |
| F2 配置/連線 | 缺必填、型態不合、循環、失效欄位；正確選上游欄位 | 非法連線/配置不能執行，錯誤可定位；advanced 內錯誤不隱藏；使用者能說出上游資料來自哪個表/欄/列範圍 |
| F3 單步語意 | 只試一列一步，再選「測到此步」與「從此步繼續」 | 三種實際 enqueue 範圍符合標籤；可核對 sample input/output/time/revision；設定變更後舊結果標示過期；真外部呼叫需清楚表達 |
| F4 審核 | 10 列產生結果，核准 6 列、退回 4 列；重複送同次核准；審核中改輸入 | 只 6 列能續行；舊版本核准不能誤放行；重複訊號不重複執行；等待重載/服務重啟仍可恢復 |
| F5 失敗恢復 | 供應商離線、其中一列失敗、匯流有 rejected/empty set、取消後 callback 回來 | 有明確終態與修復入口；成功結果不被無故重跑；不永遠等待；取消後不產生幽靈寫回；保留 attempt/history |
| F6 編輯復原 | 刪節點/連線後 undo；重載；切換正在跑的 run | 編輯 undo 不撤回已發生的外部執行；run 使用其快照、不是偷換成當前草稿；刪除相依有清楚影響預覽 |

### 7.4 易用性門檻

**[hypothesis]** 找 6 位未參與開發的人，辦公/行銷、美術、自由組裝自動化使用者（可含影劇）各 2 位；每位都完成上述三條小型工作，不用領域範本暗示按鈕順序。第一次只給工作目的與檔案，不教點哪裡；之後再收第二次熟悉操作時間。

- 每條工作至少 5/6 人無主持人代操作完成；每人任務中求助不超過一次；任何錯格、資料遺失、未核准寫入均直接不通過。
- 每個人都要能回答「目前改了哪裡、是否保存、是否真的執行、核准會影響哪些列、錯了如何復原」。回答不出來即列入阻礙，不以畫面美觀抵銷。
- 時間先與使用者目前做法記錄基線，再設改善目標；不要在沒有基線時承諾節省百分比。G6 只是技術回應目標，不能取代整體操作時間。
- 第一次失敗後能否自行恢復是獨立分數。任務成功不能靠工程師改 DB、重新整理後重新填整表或重建整個流程。

## 8. 授權與採用範圍：以本次查閱檔案為準

以下為 **[code] 授權文件查核**，用於依賴選擇與應保存的告知；不對未知商用部署方式作總括法律結論。此次未複製任何第三方程式進 OpenBench。

| 來源 | 本次可精確指向的範圍 | 採用紀錄要求 |
| --- | --- | --- |
| Baserow | 根 LICENSE L5–17 分 docs CC BY-SA 4.0、premium/enterprise 另 LICENSE、client-side JavaScript MIT、其餘 OSE MIT；L26–27 要保留 notice。[L1] | 本文引述 grid/gallery 為 web-frontend；不能把 enterprise backend assistant 因品牌相同當 MIT。若要搬實際檔案，連同依賴及對應目錄授權逐一查。 |
| Teable | 根 LICENSE L7–15：apps/nestjs-backend、apps/nextjs-app AGPL-3.0，packages MIT；L21–37 另列品牌條款。packages/sdk/LICENSE 為 MIT notice 條款。[L2][L2a] | 此次引用的 grid/schema 位於 packages，不將整庫簡寫為單一授權；不能由 SDK MIT 推論整站 fork 可忽略 apps/品牌條款。 |
| Activepieces | 根 LICENSE L5–7：packages/ee 與 packages/server/api/src/app/ee 另 LICENSE，其他 MIT。[L3] | 本文讀取 builder/test-step、flow-canvas 與 core/waitpoint；發布流程審批功能是否落在 EE，要按實際取用檔案另查，不能等同執行中的 waitpoint。 |
| AFFiNE | 根 LICENSE L5–7 將 packages/backend、packages/common/native 指向 backend server LICENSE，其他內容 MIT；第三方各自授權。[L4] | 本文只借 blocksuite database data source 的分層；整個後端或服務不可從 blocksuite 授權推論。 |
| Windmill | 根 LICENSE L9–17 指 backend/frontend AGPL 與 enterprise 例外，clients/OpenFlow Apache；L19–31 區分自行編譯 OSS 與含非公開碼的官方 Community binary，後者另有限制。[L5] | 僅參考操作/執行語意，不把官方 image 包進 OpenBench 預設部署；任何整合需先選明確 artifact 與條件。 |
| React Flow | 鎖定 repo LICENSE L1–21 為 MIT，L12–13 notice；官方 Undo/Redo Pro Example 另顯示 xyflow Pro License。[L6][X4] | 可評估 MIT 核心，保存 notice；不可把付費 example/template 的來源納入核心授權假設。 |
| Univer | 根 LICENSE 為 Apache-2.0；§3 patent、§4 redistribution/modified notices/NOTICE、§6 trademark。[L7] 官方 import/export 顯示 Pro exchange 套件與後端需求。[U2] | 以實際 package 清單與導入功能確認 notice/授權；不把所有 Univer 功能視作同一免費邊界。 |
| Glide Data Grid | LICENSE 為 MIT；stable npm manifest license=MIT、peer range 見 G1；main 不是 stable。[G1][G2][G3] | 若採用需鎖正式版本與保留 notice；React 相容性與 Canvas 可及性仍另測。 |
| AG Grid | 官方 Community licence 為 MIT；Enterprise 另 Commercial EULA，Clipboard/Cell Selection 文件為 Enterprise。[AG1][AG2][AG3] | `ag-grid-community` 與 `ag-grid-enterprise` 分別記錄；不因免費試用可以跑就納入開源預設包。 |

## 9. 交給統整代理的決策輸入

**[hypothesis] 優先次序建議：** 先確認三類代表工作與檔案 → 定義 record table / workbook 支援界線 → 把單格與多格編輯/保存/復原跑順 → 打通代理提案核對/匯出 → 再以同一資料契約加入工作視圖與完整流程設定/單步/恢復。圖庫與 flow 可做隔離原型，不能繞過 identity、revision 和變更契約先宣布產品化。

**[hypothesis] 需要統整後才裁定的四件事：** workbook 語意在真實工作中的比例；React 19 下 grid 候選的穩定可行路徑；undo 的 session/revision/多人政策；工作流預設「有引導的順序編輯」與自由 DAG 的展開方式。這些是產品/架構選擇，不是透過多裝幾個 UI 套件就會消失的工程細節。

本次擴充的 sparse checkout 僅為讀原始碼：Baserow grid/utils、Windmill frontend flows、Activepieces test-step/flow-canvas/piece-properties。HEAD 未變；lock 未改；未執行參考庫。後續重現可直接依下列 commit permalink 讀檔。

## 來源索引

鎖定 repo 的來源標籤含檔案及行號；文件 URL 為 2026-10-16 查閱的當日內容，可能隨產品更新。

[B1]: https://github.com/baserow/baserow/blob/0d332bec4934573693ac49397480b9ecd561a761/web-frontend/modules/database/components/view/grid/GridView.vue#L1859-L1998 "Baserow GridView.vue L1859–1998：選取、貼上、權限、等待與錯誤"
[B2]: https://baserow.io/docs/technical/copy-and-paste "官方文件：Copy and paste，Mental model / Three clipboard channels"
[B3]: https://baserow.io/docs/technical/undo-redo-guide "官方文件：Actions / ActionHandler / failure；列出實際後端模型與 API"
[B3c]: https://github.com/baserow/baserow/blob/0d332bec4934573693ac49397480b9ecd561a761/backend/src/baserow/core/action/handler.py#L95-L147 "handler.py L95–147：scope/session/user/action_group 與原子回滾"
[B3m]: https://github.com/baserow/baserow/blob/0d332bec4934573693ac49397480b9ecd561a761/backend/src/baserow/core/action/models.py#L10-L25 "models.py L10–25：持久 action 與 params/scope/action_group"
[B4]: https://baserow.io/user-docs/field-customization "官方文件：field conversion 與資料遺失/undo"
[B5]: https://github.com/baserow/baserow/blob/0d332bec4934573693ac49397480b9ecd561a761/web-frontend/modules/database/components/view/gallery/GalleryView.vue#L112-L268 "GalleryView.vue L112–152 RowEditModal；L232–268 view 欄位與 cover ID"
[T1]: https://github.com/teableio/teable/blob/b91d88eeb0e923263db24b7f8d29ddb4f50a544e/packages/sdk/src/components/grid/hooks/useKeyboardSelection.ts#L175-L242 "useKeyboardSelection.ts L175–242"
[T2]: https://github.com/teableio/teable/blob/b91d88eeb0e923263db24b7f8d29ddb4f50a544e/packages/sdk/src/components/grid-enhancements/hooks/use-grid-selection.ts#L118-L185 "use-grid-selection.ts L118–185：record/field identity 與座標"
[T3]: https://github.com/teableio/teable/blob/b91d88eeb0e923263db24b7f8d29ddb4f50a544e/packages/core/src/models/view/view.schema.ts#L34-L43 "view.schema.ts L34–43"
[T4]: https://github.com/teableio/teable/blob/b91d88eeb0e923263db24b7f8d29ddb4f50a544e/packages/core/src/models/view/derivate/kanban-view-option.schema.ts#L3-L20 "kanban-view-option.schema.ts L3–20"
[F1]: https://github.com/toeverything/AFFiNE/blob/0b69a6da21e8fd35beb85667bb8496d9b3852238/blocksuite/affine/blocks/database/src/data-source.ts#L497-L537 "data-source.ts L497–537：型態轉換與 fallback"
[F2]: https://github.com/toeverything/AFFiNE/blob/0b69a6da21e8fd35beb85667bb8496d9b3852238/blocksuite/affine/blocks/database/src/data-source.ts#L174-L182 "data-source.ts L174–182 view manager；L571–619 view operations"
[A1]: https://github.com/activepieces/activepieces/blob/82300fe8029390e614f63eeac079ccc6db60eba6/packages/web/src/app/builder/flow-canvas/nodes/big-add-button-node.tsx#L59-L107 "big-add-button-node.tsx L59–107：插入位置與 PieceSelector"
[A2]: https://github.com/activepieces/activepieces/blob/82300fe8029390e614f63eeac079ccc6db60eba6/packages/web/src/app/builder/data-selector/test-step-section.tsx#L8-L30 "test-step-section.tsx L8–30"
[A3]: https://github.com/activepieces/activepieces/blob/82300fe8029390e614f63eeac079ccc6db60eba6/packages/web/src/app/builder/test-step/test-action-section.tsx#L113-L163 "test-action-section.tsx L113–163：驗證、樣本、輸入、錯誤、時間"
[A3v]: https://github.com/activepieces/activepieces/blob/82300fe8029390e614f63eeac079ccc6db60eba6/packages/web/src/app/builder/test-step/test-sample-data-viewer.tsx#L62-L190 "test-sample-data-viewer.tsx L62–190：Input/Output/Logs 與取消/重測"
[A4]: https://github.com/activepieces/activepieces/blob/82300fe8029390e614f63eeac079ccc6db60eba6/packages/web/src/app/builder/piece-properties/advanced-section.tsx#L31-L101 "advanced-section.tsx L31–101；piece-settings/index.tsx L172–198、L312–334 為分組/錯誤處理"
[A4p]: https://github.com/activepieces/activepieces/blob/82300fe8029390e614f63eeac079ccc6db60eba6/packages/web/src/app/builder/step-settings/piece-settings/index.tsx#L172-L198 "piece-settings/index.tsx L172–198：advanced 與 error handling；L312–334 為分組函式"
[A5]: https://www.activepieces.com/docs/flows/passing-data "官方文件：Passing Data / Testing Steps"
[A6]: https://github.com/activepieces/activepieces/blob/82300fe8029390e614f63eeac079ccc6db60eba6/docs/install/architecture/waitpoints.mdx#L68-L101 "waitpoints.mdx L68–101：持久 lifecycle 與 race；L116 亦列 known limitation"
[W1]: https://github.com/windmill-labs/windmill/blob/33d4049db029e1dc478b1251c562232f0127fc8a/frontend/src/lib/components/flows/header/FlowPreviewButtons.svelte#L117-L168 "FlowPreviewButtons.svelte L117–168：testUpTo / Test flow"
[W2]: https://www.windmill.dev/docs/flows/flow_approval "官方文件：Suspend & Approval / Prompts"
[W3]: https://www.windmill.dev/docs/getting_started/flows_quickstart "官方文件：Flows quickstart，test up to / retries"
[X1]: https://github.com/xyflow/xyflow/blob/654ba5a5e04f3404bc4db2eee88bfa15866d203d/examples/react/src/examples/SaveRestore/index.tsx#L23-L36 "SaveRestore/index.tsx L23–36"
[X2]: https://github.com/xyflow/xyflow/blob/654ba5a5e04f3404bc4db2eee88bfa15866d203d/examples/react/src/examples/Validation/index.tsx#L33-L106 "Validation/index.tsx L33–106"
[X3]: https://reactflow.dev/learn/advanced-use/accessibility "官方文件：Accessibility，預設 focus 與自訂節點注意事項"
[X4]: https://reactflow.dev/examples/interaction/undo-redo "官方文件：Undo/Redo，About this Pro Example / xyflow Pro License"
[U1]: https://github.com/dream-num/univer/blob/7e73a4d83edbb2c5b1996dc93bb32cb9a5c951f6/packages/core/src/services/command/command.service.ts#L37-L64 "command.service.ts L37–64：command / operation / mutation"
[U2]: https://docs.univer.ai/guides/sheets/features/import-export "官方文件：Import/export；Pro exchange、conversion backend、snapshot vs collaboration"
[TS1]: https://tanstack.com/table/v8/docs/overview "官方文件：Headless；不產生 DOM"
[G1]: https://registry.npmjs.org/@glideapps%2fglide-data-grid/6.0.3 "npm 官方 6.0.3 metadata：version/license/peerDependencies/gitHead"
[G2]: https://raw.githubusercontent.com/glideapps/glide-data-grid/main/packages/core/package.json "main package.json L2、L63–68（當日 6.0.4-alpha25；非 stable）"
[G3]: https://github.com/glideapps/glide-data-grid/blob/main/LICENSE "Glide LICENSE L1–19（當日查閱）"
[G4]: https://docs.grid.glideapps.com/api/dataeditor/editing "官方 API：onCellsEdited / onPaste / onFillPattern / validateCell"
[AG1]: https://www.ag-grid.com/eula/community/ "AG Grid 官方 Community MIT 條款與 Enterprise 分界"
[AG2]: https://www.ag-grid.com/react-data-grid/clipboard/ "官方 Clipboard 文件，Enterprise 標記與 ag-grid-enterprise ClipboardModule 範例"
[AG3]: https://www.ag-grid.com/react-data-grid/cell-selection/ "官方 Cell Selection 文件，Enterprise 標記"
[AG4]: https://www.ag-grid.com/react-data-grid/undo-redo-edits/ "官方 Undo/Redo 文件：stack clearing 與 cell edit 邊界"
[L1]: https://github.com/baserow/baserow/blob/0d332bec4934573693ac49397480b9ecd561a761/LICENSE#L5-L27 "Baserow LICENSE L5–27"
[L2]: https://github.com/teableio/teable/blob/b91d88eeb0e923263db24b7f8d29ddb4f50a544e/LICENSE#L7-L37 "Teable LICENSE L7–37"
[L2a]: https://github.com/teableio/teable/blob/b91d88eeb0e923263db24b7f8d29ddb4f50a544e/packages/sdk/LICENSE#L1-L21 "Teable SDK LICENSE L1–21"
[L3]: https://github.com/activepieces/activepieces/blob/82300fe8029390e614f63eeac079ccc6db60eba6/LICENSE#L3-L17 "Activepieces LICENSE L3–17"
[L4]: https://github.com/toeverything/AFFiNE/blob/0b69a6da21e8fd35beb85667bb8496d9b3852238/LICENSE#L3-L16 "AFFiNE LICENSE L3–16"
[L5]: https://github.com/windmill-labs/windmill/blob/33d4049db029e1dc478b1251c562232f0127fc8a/LICENSE#L9-L31 "Windmill LICENSE L9–31"
[L6]: https://github.com/xyflow/xyflow/blob/654ba5a5e04f3404bc4db2eee88bfa15866d203d/LICENSE#L1-L21 "xyflow LICENSE L1–21"
[L7]: https://github.com/dream-num/univer/blob/7e73a4d83edbb2c5b1996dc93bb32cb9a5c951f6/LICENSE#L67-L142 "Univer Apache-2.0 LICENSE §2–6，L67–142"
