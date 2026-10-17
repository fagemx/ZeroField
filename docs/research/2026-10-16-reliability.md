# OpenBench：操作承諾、資料模型與恢復契約研究

研究日期：2026-10-16。依 `docs/research/2026-10-16-research-brief.md` 的 d-001，只讀研究；沒有修改產品程式、資料庫、依賴或提交。三視圖是未驗收草稿，不以新增測試數或 build 成功推論可用。本文供產品方案決策，並非本輪實作清單。

## 結論與證據邊界

現在已有可用的工程基礎：穩定的表格列 ID、原子表格提案、部分欄位級並行合併、版本／鎖定檢查、持久化 DAG、Worker 租約、審核阻擋下游及失敗重排。問題在於「使用者看到的操作」尚未共享同一份精確契約。最應先處理的不是增加視圖數，而是讓選取範圍、欄位身分、公式座標、檔案往返、提案確認、單步執行與恢復範圍一致。

四項阻斷應先於 UI 大改：

1. 篩選後貼上沒有範圍契約，實作會寫到隱藏列。
2. 欄位由位置識別，刪欄不更新公式及流程目標；「欄位型態」大多只是顯示提示。
3. 匯入 XLSX 可以在畫面增列／刪欄，直到匯出才拒絕，使用者無法完成交接。
4. 可以拒絕過期寫入，但使用者缺少就地比較、保留草稿、重套與撤回路徑；流程重試又會重新執行已產生但未獲批准的結果。

標記規則：`code`＝直接讀到的實作／測試契約；`observed`＝本輪實際操作或實驗；`hypothesis`＝需要使用者任務或故障注入驗證的影響。本文沒有瀏覽器走查證據；兩項 `observed` 僅指 Node 記憶體內純函式實驗，不是端到端驗收。舊驗收文件記錄的測試通過不等同本輪重跑。

本機 3022 的 `--no-worker` 是隔離環境限制。後端實際有 assistant Worker 與 limb Worker；不能由 3022 沒有模型回覆推斷所有部署無法執行。外部付費模型、Docker、遠端 CI 的驗證界線仍以 `docs/ACCEPTANCE.md` 為準。

## 使用者動作 → 實作 → 缺口 → 影響 → 最小必要變更

| 使用者工作 | 現有能力與證據 | 可證缺口／覆蓋程度 | 造成的體驗與必要底層變更 |
| --- | --- | --- | --- |
| 從 Excel 貼上兩列到已篩選的表格 | **部分覆蓋，code**：TSV 支援引號、換行、最多 200×100；`sheetModel.js:39–71`。`SheetSurface.jsx:115–119` 由目前格起貼。 | 可見列只是渲染過濾（134、199–200）；payload 依 `parsed.rows[startRow + offset]` 寫原始連續列，不依可見列。**observed**：可見 r1/r3，兩列貼上實際產生 r1/r2 的 payload。 | 隱藏的資料可能被改，畫面看不到第二筆變更。先明定「可見列貼上」或「實體矩形貼上」；後者至少在有篩選時拒絕／顯示完整目標。payload 應帶解析後 row IDs、column IDs、基底值；預覽、提交、undo 共用同一 command。 |
| 像試算表連續輸入、選一塊複製／刪除／填滿 | **部分覆蓋，code**：單格焦點、方向鍵、Enter/F2、雙擊、textarea 儲存；`SheetSurface.jsx:100–119,167–172,236–239`。 | 模型只有 `active:{r,c}` 與整列 checkbox Set（21–22）；沒有矩形選區／range copy／fill／多格 delete／sheet undo 命令。`nextCell` 只處理四方向（`sheetInteraction.js:1–9`）。 | 功能跑得通但每格需開關對話框；無法用熟悉的批量手勢完成整理。先建立選區模型與批量 command adapter，再比較自建／成熟 grid；避免為每個視圖另寫一條儲存路徑。 |
| 刪一欄，期待公式與流程還指向同一欄 | **部分覆蓋，code**：增刪欄及型態設定；`SheetSurface.jsx:241–243`。 | 刪欄直接 `splice` 每列 content，型態按 index；無欄位 ID。`doc_schema.py:120–131` 僅保存名稱與 types 陣列。公式是文字，Flow `target.col_index`／`row_source.status_col` 是位置（`flow_runner.py:55–56,97–98`）。 | 刪 A 欄後原 C 欄公式參照／輸出欄可能錯位；即使欄號仍在範圍，後端不能知道語義已變。最低限度增加穩定欄 ID、schema revision、依賴清單；結構 command 要原子調整引用或拒絕且說明受影響項目。 |
| 指定「數值／公式／狀態」後可靠分析 | **部分覆蓋，code**：type 影響顯示、媒體及原生匯出數字；`SheetSurface.jsx:205–212`、`file_handoff.py:459–465`。 | `table_edits.prepare` 對普通格只驗文字／數值後轉字串，不依欄 type 校驗（8–20,72–93）。公式由任何開頭 `=` 的字串觸發。狀態有兩種實體：fid capsule 限全域 `STATUSES`，一般文字欄沒有同樣限制（`table_edits.py:79–88`；`sheetViews.js:16–19`）。 | 「數值」可存非數字，「狀態」在不同視圖／來源有不同選項。先定 typed value、display、formula、validation 與每欄選項；舊資料以可見的待修正狀態接納，不靜默改值。 |
| 核對 Excel 公式、總計及第一筆資料 | **部分覆蓋，code**：算術及單欄 SUM/AVG/AVERAGE、循環保護；`sheetModel.js:100–134`。 | 無完整公式引擎；不支援跨表／常見函數的計算。任何找不到的格預設 `0`，沒有驗證 row 必須 ≥1（108、119）。**observed**：無效列座標 `=A0+1` 也回傳 `1`。UI 標 `r+1`，匯入 XLSX 計算另用 offset 1（`SheetSurface.jsx:204,209,212`），同一個 UI「A1」與原檔 A1 不等義。 | 錯誤可能顯示成可信數字；使用者無法知道是計算、不支援還是舊快取。先統一座標系，分開原公式／顯示值／計算狀態；合法空白格與無效引用必須區分。若要求廣泛試算表行為，評估成熟公式／工作簿模型。 |
| 把現有 XLSX 放進來，增列後交回同事 | **部分覆蓋，code**：母檔原始位元組、局部 OOXML patch、原內容未動時原檔返回；`file_handoff.py:261–343,430–441`。 | UI 允許增列／刪欄（`SheetSurface.jsx:193,242–243`），patch 在匯出才拒絕任何 row ID 序列／欄數改動（`file_handoff.py:288–291`）；共有／陣列公式、合併格非錨點修改亦拒絕（303–311）。現有測試刻意驗證拒絕（`test_file_handoff.py:77–100`）。 | 使用者完成整理後才發現拿不出同格式成果。需先做「原檔相容性」能力與操作預檢；明確區分保留原檔匯出與生成新工作簿。兩種輸出可源於同一權威內容，不能暗自切成兩份可寫資料。下節列決策選項。 |
| 匯入含標題列、空白列、合併儲存格的工作簿 | **部分覆蓋，code**：多 sheet 被讀取；檔案 ≤8 MB，總 cells ≤20,000，rows ≤10,000，cols ≤100（`file_handoff.py:24–28,112–151`）。 | `_table` 一律把第一實體列變 header（88–100）；XLSX 只讀 values/formula 字串，不建立原型態、合併、顯示格式的畫布模型（134–148）。`tablesOf` 會辨認真正 header（`sheetModel.js:21–28`），但 runner `_table_data` 無條件把第一列當 header 並排除（`flow_runner.py:319–326`）。 | 沒有表頭的 sheet 首筆變成欄名；有封面／多區塊的 sheet 無法直接成可靠 records。應保存 source range、header rows、data region、source cell address 與映射版本；流程僅能綁定確認過的資料區。 |
| 外部 Excel 改好拖回，保留標註對象 | **部分覆蓋，code**：目前 revision、整頁鎖、整檔替換與 reanchor 同交易；`service.py:237–289`。 | row ID 對位依唯一完整內容→唯一首欄→位置 fallback（`file_handoff.py:226–257`）；無唯一鍵時不是可靠身分。UI 直接匯入，回覆已重新對位（`TabRail.jsx:26–35`），沒有先看歧義／衝突。 | **hypothesis**：重複名稱且改內容／重排的表會讓留言黏到錯列，僅看成功訊息不會發現。需三方比較（來源基準／目前／外部檔）、匹配信心與歧義待確認；無可靠對位時保留未附著標註，不能宣稱全部重對位成功。 |
| 同事也在編輯時保存我的修改 | **現在有功能＋部分覆蓋，code**：table proposal 在受影響 cell 的 base 未變時合併不同欄，衝突全不寫；`table_edits.py:109–153`。手動普通格 API 先比整個 tab revision（`http.py:300–310`）。 | 同頁無關修改也會使手動格保存 409。fid status 直接 `/fields` 沒 expected value/version（`App.jsx:237–246`、`service.py:761–804`）；field_value 不增加 tab revision（`repository.py:385–405`）。Sheet 開編輯不取鎖，只顯示既有鎖（`SheetSurface.jsx:100–104,216`）。 | 不能概稱「已避免所有過期覆蓋」：普通格偏保守阻擋，fid 路徑可能 last writer wins。應統一 cell/field compare-and-set；衝突回覆具 before/mine/current，保留草稿並允許只重套無衝突部分。無需第一步就換 CRDT。 |
| 改錯一批內容，立即復原 | **部分覆蓋，code**：全域 History 有改回與 later-change 確認（`History.jsx:68–92,118–123,149–158`）；doc 有 undo/redo、整頁 revision restore。 | Sheet 沒有 undo stack；列歷史只讀（`SheetSurface.jsx:256`）；真正 History 的開啟 callback 在 DocSurface 路徑（`App.jsx:551–565`）。刪欄提示「可從版本紀錄復原」（Sheet:242）未把恢復入口接到當前操作。 | 使用者被迫切文件模式尋找歷史，且可能恢復整表影響別人。需 operation ID、inverse patch、同一原子操作的撤回預覽；撤回要檢查後續修改，失敗時保持目前資料和原操作可追蹤。 |
| 從總覽交代指定列，核對後跨頁寫回 | **現在有功能＋部分覆蓋，code**：`propose_table_edit` 可指定 tab/table/row，最多 200 列並審核原子套用（`tools.py:522–534`、`table_edits.py:46–106`）。 | Sheet 選列轉成只有名稱／列序的自然語言（`sheetInteraction.js:19–26`），`App.jsx:528` 沒另帶穩定 selection。提案 preview 是 `rid / 欄 N：old→new` 字串（table_edits:91），ProposalCard 只有全收／全拒及 300px 文字區（`AssistantViews.jsx:195–225`）；不能局部修正。 | 重名或資料變動後需模型重新推理選列；長表提案難核對。選取應作獨立結構化上下文；Proposal 保存 typed diff 與標籤 snapshot，逐格顯示欄名、前後值、來源、狀態。先支援接受整個可核對交易，再評估部分接受，避免破壞流程相依。 |
| 自由連線，知道上游什麼值送到哪裡 | **部分覆蓋，code**：分支、匯流、循環拒絕、位置和 revision；`flowModel.js:21–35`、`flow_runner.py:20–89,195–214`。 | edge 只有 source/target，沒有 typed ports 或資料映射；輸入以勾整個分頁，target 以欄號設定（`FlowSurface.jsx:167–172`）。`_inputs` 把上游 output／predecessor_tasks 全傳入（`flow_runner.py:601–635`）；不等於使用者定義好的參數綁定。 | 能連線不代表知道要如何消費資料；圖片 adapter 會從輸入找第一個 image（`limb_worker.py:169–178`），多參考圖時尤其易猜錯。需最小 input/output schema、具名資產／欄位綁定與 sample input 預覽；連線驗證需涵蓋相容型態而非只有無環。 |
| 先試跑某列的某一步，再決定放大量產 | **部分覆蓋；只此節點／dry-run 未實作，code**：支援 start_node_id＋row_ids。 | `start_node_id` 展開所有後代（`flow_runner.py:353–364`）；UI 已寫「起的下游」（`FlowSurface.jsx:144`）。無只此節點、sample preview、暫存結果後升格正式輸出。scoped DAG 等全部上游 tasks succeeded 才展開下游（426–444），是 stage barrier，不是逐列一路流動。 | 「重抽此格」可能繼續重跑下游；一列失敗可能讓其他已完成列也無法進下一段。需明確 run mode：只此節點／此點及下游／完整流程，執行前顯示實際節點和列、寫回位置、審核點；樣本輸入與正式 run 同編譯器。 |
| 人工審核美術成果或報表提案 | **現在有功能＋部分覆蓋，code**：proposal 寫回成功才把 task 設 succeeded，拒絕則 failed、下游不展開（`flow_runner.py:787–840`）。 | 有 target 且 write_mode=proposal 才產生審核；direct 直接寫入，無 target 中間結果直接成功（723–726,802–810）。提案 owner 是 run 發起人（809），`service._own_pending` 只允許本人（257–268）；沒有指定主美／主管／代理審核人。 | 不能宣稱團隊人工審核流程完成。中間結果也無任意 review gate；「先不要」是失敗而非暫停。先明定個人確認與指定審核兩種需求；若要多人，新增 reviewer／等待原因／提案分派，讓流程面板能直接開該審核內容。 |
| 失敗後修正資料／節點再繼續，避免重做已完成工作 | **現在有功能＋部分覆蓋，code**：immutable run definition、租約回收、成功 task 保留、失敗／取消／blocked 重排，row set 凍結；`flow_runner.py:391–397,429–443,481–535`；`test_flow_scopes.py:124–156` 有既有回歸。 | 重試用舊 run definition；UI 修改節點再重試不會套用新設定。重試清除 failed/canceled output、snapshot、proposal 並將 attempts 歸零（530–532）。輸入分頁於 claim 讀最新，只有 target_snapshot 保存，未保存完整 attempt input（546–635,677–691）。 | 舊 prompt 反覆失敗；被拒的昂貴結果要再生成而不是修訂／重審。應拆「原設定重試、修正後新 run、保留結果重新提案」，顯示實際 revision 和輸入版本，保留 append-only attempt evidence；不要先承諾 exactly-once。 |
| Worker 斷線／提交逾時後安全恢復 | **現在有功能＋需實測，code**：租約與 token 阻止過期完成；limb worker renew、停止交付；`flow_runner.py:481–485,660–694,697–713`、`limb_worker.py:370–407`。 | supplier job id 只存在 adapter 當次記憶體（ComfyUI 185–193，bridge 227–236）；`db/157_execution.sql:36–57` 無外部 job／attempt 紀錄。重領會重新呼叫 adapter。bridge 傳 task_id 但供應商是否去重並無通用保證。 | **hypothesis**：在遠端已接受但本機回覆遺失的窗口，重試可能重複生成或費用。最小驗證先用免費 fixture 注入斷線；再決定 adapter idempotency key、已提交 job checkpoint／重接查詢。取消要區分「停止本地寫回」與「遠端已確認取消」。 |
| 儲存大型表格／20 列工作時知道當前狀態 | **部分覆蓋＋需實測，code**：表格全量 map、每列 filter tasks；flow 2–4 秒 polling、tasks 輸出 JSON（`SheetSurface.jsx:65–80,197–220`；`FlowSurface.jsx:48–68,175–178`）。 | 沒有虛擬化；recent_tasks 只回最近 200 筆（`flow_runner.py:497–507`），表格按最新 run 摘要不一定有該 run 全部節點。Flow 儲存衝突只能重新載入；無圖形 undo 或 merge（195–214）。 | 大資料／多節點時效能與進度完整性未證明。先用實際規模量測，不預設慢；進度應由 server 回傳完整 run/row summary，節點 UI 的成熟元件只改善操作，不取代 run 契約。 |

上述程式路徑前綴：前端檔案在 `ui/src/`；`file_handoff.py`、`doc_schema.py`、`http.py`、`repository.py` 與未特別標明的 `service.py` 在 `project_docs/`；worker、flow_runner、table_edits、tools 及提案 service 在 `project_assistant/`。矩陣中有歧義的 `service._own_pending` 明確指 `project_assistant/service.py`。

## 最先決定：Excel 往返和自由資料表如何共存

目前把「工作簿」「有表頭的資料區」「工作台紀錄表」都塞進同一 table node，差別只有 worksheet_name 等屬性。這不是只缺漂亮匯出按鈕：第一列與座標系的假設會一路影響選列、公式、代理引用、流程輸出及 reimport。

先確立共同原則：每個可編輯內容只能有一份權威狀態；source_blob 是來源／保真底稿，不是第二份可獨立修改的資料。代理與人類必須經過同一命令和版本檢查。Office 視圖與卡片視圖若共存，後者必須是明確的投影，不能雙向盲目同步。

| 方案 | 使用者看到什麼 | 單一權威與必要模型 | 權衡與適用時機 |
| --- | --- | --- | --- |
| A. 保守往返＋明確的新檔匯出 | 同一分頁標示「可保留原檔格式」；要增列／刪欄前告知此操作超出原檔保留範圍，提供撤回或生成新工作簿；不等到下載才報錯。 | 保留現有 doc/table 作權威，加 source mapping、export capability report；兩種 export 都讀同一狀態。原檔 patch 與 clean export 是兩個明示輸出策略。 | 最小改動，可先解除最後一步才失敗。但原檔影像／複雜公式／排版的可編輯能力仍有限；對「我要完整 Office」需求不夠。須能從不相容操作撤回到可 patch 狀態。 |
| B. 工作簿權威＋資料區投影 | Excel 分頁提供完整工作簿操作；使用者選定某 sheet/range、表頭、主鍵後，才開啟資料表／圖庫／看板和工作流。 | workbook model 是唯一權威；records view 帶 source range、row identity、column identity、mapping version，編輯轉成 workbook command。反向工作簿改結構時原子更新映射或將投影標為需修復。 | 最接近辦公期待，公式與結構歸同一引擎。整合與 Office 保真成本最高；套入 SDK 不代表能把任意工作簿無歧義轉 records。必須小型驗證再選，不能把全面替換當前提。 |
| C. 明確「轉為工作台資料表」 | 匯入先預覽資料區；選擇轉換後自由增刪欄、媒體與多視圖，清楚顯示「匯出為新工作簿」。原檔保留可下載作來源。 | 同一 tab 轉成結構化 table 權威；原檔凍結為 provenance。不是另一份持續同步的可寫資料，也不自動回寫外部 Excel。保留匯入映射供追溯。 | 最適合美術資產與辦公紀錄整理，易用與一致性較可控；不能稱原檔無損往返。重匯入要走明確的版本合併，而不是再次覆蓋。 |

建議作為研究假設：近期先驗 A 的相容性預檢與 C 的資料區選擇，讓真實使用者分辨需求；只有完整工作簿編輯是主要工作時再推 B。這是模式與內容權威的決策，不是按職業硬拆產品。辦公也會需要 C，美術也可能需要 B 的規格表。

缺少的 row/header 映射至少包括：原 sheet ID／名稱、來源 cell address、表頭是否存在與行數、資料區邊界、原檔列與 record ID 對照、主鍵／歧義紀錄、欄 ID、mapping revision。不能只把 `worksheet_name ? 1 : 0` 擴充成更多例外。

## 三種技術路徑比較：什麼能買到，什麼仍要自己負責

| 路徑 | 可沿用／可改善 | 必須自己補的契約 | 研究判斷 |
| --- | --- | --- | --- |
| 保留現有 HTML table 增補 | 現有 rich cell、媒體、提案／標註／歷史整合容易延續，遷移少。 | range selection、copy/paste、IME、鍵盤、resize、虛擬化、undo、欄位身分、公式引用都需自己維護；目前 `ui/package.json` 只有 React/Tiptap，無 grid 引擎。 | 適合界限明確的小型紀錄表。若繼續宣稱熟悉 Excel 的大量日常操作，維護面很快超過「增補幾個按鈕」。先用工作任務量測，不直接判死刑。 |
| 成熟 grid＋OpenBench domain model | 可測 range／row／column 選取、鍵盤、批次 edit callbacks、custom cells；將現有媒體／提案保留作 editor 和側欄。 | grid 的座標仍需轉 stable row/column IDs；它不會自行保存、提供後端 undo、檔案保真、公式或審核。不可把每格 callback 變一次獨立 HTTP 寫入。 | 最值得優先小型驗證的通用表格路徑。用同一原子 command adapter 接入，不先重建所有視圖。 |
| Office SDK 分模式 | 完整 workbook 需要的 selection／reference／formula／command 模型有現成基礎；Office 模式可與資料區投影共存。 | SDK command 到提案／歷史／鎖／Worker 的轉譯、單一權威、來源範圍投影、Office 功能保真與部署授權仍要驗證；不要全量 JSON 雙向覆寫。 | 若真實辦公檔案需要超過紀錄表的公式／排版，值得測。不能把它當免費完成匯入匯出或共同編輯的捷徑。 |

成熟做法的具體依據：

- Glide Data Grid 官方 API 把選區分成 current range、rows、columns，並提供 `onCellsEdited`、`onPaste`；資料寫入責任留給應用。這支援「用成熟互動層、保留 OpenBench 交易」的可行性假設，但仍要自己決定越界貼上與增列。[官方 API](https://github.com/glideapps/glide-data-grid/blob/main/packages/core/API.md)
- 本機釘版 Teable 的 `packages/sdk/src/components/record-snapshot-grid/RecordSnapshotGrid.tsx:184–244`，複製邏輯明確處理 cell／row／column selection 並按可見順序取值；可借鑑的是選取契約，不是整個應用搬過來。
- 本機釘版 Univer 的 `packages/core/src/services/command/command.service.ts:35–60,108–120,234–267` 將 command、mutation、operation 分層，暴露 before/after command hook；這種模型有利於把「貼上一整塊、undo、同步」視為一個操作，而非多次任意儲存。
- Univer 官方文件明示 XLSX import/export 由服務端 `@univerjs-pro/exchange-node` 轉換，不能從開源 editor 名稱推論檔案轉換無部署／授權成本。[官方檔案交換文件](https://docs.univer.ai/server/import-export)
- React Flow 官方提供 connection validation hook；換它可改善節點互動，但 OpenBench 仍須定義資料型態和執行範圍，無法由無環檢查得到資料相容性。[官方連線驗證](https://reactflow.dev/examples/interaction/validation)

本機參考版本均記錄於 `docs/references/open-source-lock.json`。以上是特定機制的證據，不是宣稱已完成第三方相容性、效能或商用授權審查。

## 先做的小型技術驗證與決策順序

這些是下一輪驗證提案，本輪未實作、未安裝。

1. **先驗模型，不先選外觀。** 用 12 列資料與重複名稱，定 stable row/column IDs、原子 cell/structure commands、visible range→IDs 映射。驗篩選、刪欄、formula／flow binding、fid status 共用 CAS；做出一個完整 edit→conflict→recover 循環。若這一步不成立，三種 UI 路徑都不能可靠。
2. **grid 對照小樣。** 現有 grid 與一個成熟 grid 共用相同 command adapter、資料和媒體格，做 20 次連續鍵盤輸入、10×6 貼上、篩選複製、撤回、1000 列捲動。不得只比較畫面或 demo 的流暢度；重點是 IME、焦點、1 次交易、失敗保留 draft。
3. **Office 往返小樣。** 用 6 份匿名 fixture：無 header、有封面／多區塊、重複欄名、合併格、跨 sheet 公式、圖片／格式。比較 A/C 與 SDK 原型的讀入→小改→新增列→匯出。結果按功能逐項報告，不能只有「Excel 能打開」。這會決定是否值得走 B。
4. **流程編譯／單步小樣。** 文案→兩列資料、圖片→檢查、報表→彙總三種免費 fixture 共用流程定義；編譯器列出節點、輸入值、row set、target、審核點；支援明確只此節點，不能偷偷排下游。先證明資料綁定與 preview，再比較節點元件。
5. **提案與恢復小樣。** 20 列／40 格 diff、1 個外部修改、1 個人工拒絕、1 個 Worker 交付逾時。確認使用者能知道「哪些已寫、哪些沒寫、下一步重用舊結果或重跑」。只有完成此循環後，才驗多人分派與長時間執行。

依賴順序：資料身分／命令 → 選取與批次編輯 → 檔案模式及相容性 → 結構化提案／恢復 → typed flow 與單步預覽 → Worker 故障窗口／多人審核 → 規模與真實模型。圖庫看板可在已驗證共用模型之後接入，不是上述契約的替代品。

## 成功與故障恢復的驗收契約

以下是未來應執行的可重複門檻，不是已通過的結論。每次需記錄 fixture、操作、payload、before/after 狀態與恢復步驟。

| 驗收工作 | 成功條件 | 故障與恢復條件 |
| --- | --- | --- |
| 連續表格整理 | 只用鍵盤完成 20 格輸入、10×6 paste、range copy；一次 paste 對應一次歷史操作；Reload 後一致。 | 409／網路中斷不丟草稿、不半套；能比較 mine/current 後重套或取消。重送同 operation ID 不重複新增列。 |
| 有篩選的批次修改 | 使用者能在送出前看見精確 row IDs 對應的名稱；隱藏列 hash 不變；複製的順序與畫面一致。 | 目標列被刪或排序改變時，不改到其他列；撤回只還原本次改動，遇後續修改列出衝突。 |
| 欄位與公式 | 改名／移動／刪欄後，未刪除欄的 stable IDs 與 flow 綁定保持；被刪引用明確失效；公式結果與已宣告支援集合的參考軟體一致。 | 引擎不支援、缺失引用、循環不能偽裝成成功數字。結構操作無法維持引用時，提交前阻擋並給受影響項目。 |
| 檔案往返 | 未改原檔可 bitwise 相同；允許 patch 的變更只改明示 parts；新檔匯出與原檔匯出標示不同。 | 結構變更前已告知相容性影響；可撤回或輸出新檔；任何拒絕不令使用者困在無可下載成果狀態。 |
| 匯入與重匯入 | 無 header／多區塊檔先確認 mapping；record ID 對位以可解釋依據成立；原檔座標可查。 | 重複鍵、列移動又改內容時列出歧義；不把不確定匹配當成功；保留原標註與回復前一版本入口。 |
| 跨頁提案 | 40 格 diff 可讀列名／欄名／前後值；確認寫回只套用被核對交易；同時修改其他欄可合併。 | 相同格改動造成衝突時，原內容與 proposal 仍保留；不要求重跑模型才能看出差異；「拒絕」和「稍後審核」語義清楚。 |
| 任意選列與單步 | 選一列、只此節點，實際僅一個指定 task，零下游；完整／下游模式在執行前列出差異。 | 來源不足、欄位被刪、Worker 未連線、target 不匹配於排程前說明；已生成輸出留在暫存結果，確認前正式資料不變。 |
| 工作流審核 | proposal 模式在批准前不寫 target，下游不領取；有清楚 owner/reviewer 和等待原因；流程中能直達審核內容。 | 拒絕後能保留結果修改／重新提案，不必再次生成；修改節點後是新 run revision，不會誤稱原 run 已採新設定。 |
| Worker 恢復 | 成功 task 不重跑；失敗 task 保留每次輸入、設定版本、供應商 job 與輸出；run summary 與全部 tasks 一致。 | 供應商接受後斷線、complete 回覆遺失、租約到期、取消、應用重啟逐一注入。不能證明供應商去重時明示需查驗，不自動宣稱完成或零重複費用。 |
| 多人與規模 | 兩人不同格可保存，同格衝突一致；在約定設備上測 1000×20 和實際美術長文／縮圖資料；記錄編輯、捲動、儲存延遲。 | 使用者能從相同入口復原，沒有隱藏覆蓋。效能指標由比較樣本決定，不以 import 上限或測試個數冒充可用容量。 |

## 對外表述應精確更正

| 過度概括的說法 | 依目前實作可使用的說法 |
| --- | --- |
| 「Excel 無損編輯／無損交接」 | 「保留上傳原檔；未修改時可原檔下載。支援部分儲存格值／公式的保守 Patch，保留未修改的 ZIP parts。列欄結構及部分 Office 特性修改目前會拒絕；畫布與計算能力不是完整 Excel。」 |
| 「任意列單步執行」 | 「可選取最多 200 列，從指定節點開始執行該節點與下游；逐列／一次／匯總依節點設定。尚無只執行單節點的試跑模式，任意跨表列映射亦需明確設定。」 |
| 「人工審核流程已完成」 | 「有輸出目標且選擇 proposal 的任務，由發起人在自己的助理提案中確認後寫回，下游才繼續；尚無指定審核人、團隊佇列、任意中間節點審核或逐格部分接受。」 |
| 「支援多人編輯，不會覆蓋」 | 「普通表格／提案有樂觀衝突檢查和鎖保護，部分不同欄修改可合併；fid 狀態更新與手動修改仍需統一 compare-and-set 與使用者衝突恢復流程。」 |
| 「失敗可直接恢復」 | 「可重試未完成 tasks，保留成功 tasks 與已展開列集合；重試沿用舊 run 設定，可能重新生成未獲批准／交付失敗的結果。完整 attempt 輸入與外部 job 恢復尚待補足。」 |

## 本輪實驗紀錄

以現有 `ui/src/sheetModel.js` 做 Node 動態 import，在記憶體建立 r1/r2/r3（r1/r3 假設可見）。呼叫 `tableEditPayload(parsed, 0, 1, [["100"], ["300"]])`，實際 `row_edits` 為 r1、r2，證明函式本身無可見列範圍資訊。公式實驗 `evaluate("=A0+1", rows)` 得 `"1"`；`evaluate("=SUM(A1:B2)", rows)` 得 `"#ERROR"`。另測 `=Z999+1` 也得 1，但合法座標在試算表常可指向空白格，因此不能單憑此結果判為錯誤；確定缺口是無效 row 0 亦被當 0。沒有 HTTP、資料庫、付費模型或寫入測試。

此實驗沒有證明所有貼上都錯；它證明目前 UI 允許的篩選情境與 payload 語義未對齊。也沒有證明所有公式不可靠；它界定了必須讓使用者知道的支援範圍與錯誤狀態。
