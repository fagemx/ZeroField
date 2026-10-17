# Task 1：完整 DAG 量產與匯流補強

2026-10-16。本次限於 `ROADMAP_COMPLETION_PLAN.md` Task 1 與主代理追加授權的平行儲存格合併；未改既有 3020 服務、未提交或重置工作樹。

## 已完成

- `flow_runner.py`：`once`／`rows`／`aggregate` 明確範圍；前序提案通過後才動態讀取新增列。每個來源第一次展開時固定 row ID 與表格順序，後續節點讀取目前欄位值。
- 逐列階段內可平行執行，分支互不阻塞；下游使用完整階段 barrier，等待每個前序節點的全部任務成功。聚合僅一個任務，收到依表格順序排列的 `predecessor_tasks`。
- `flow_run.execution` 另存展開狀態，不改 immutable definition。既有 `db/157_execution.sql` 增加可重入欄位遷移。空列集也持久化，避免重複展開；空集後的聚合仍執行一次。
- `start_node_id` 限定新 run 的起點與後代；選列和來源狀態篩選取交集。未指定 scope 的舊 graph 保持原逐列行為。
- 輸入提供穩定 ID、結構化 tables／rows、目標 headers，以及有序前序結果。來源／目標表只帶目前列，參考分頁完整保留。數值遮罩套用欄位內容，不修改結構 ID。
- `target.kind: doc` 支援文字 append／replace、媒體連結、提案審核或 direct，沿用 revision／locks／creator 驗證與歷史。
- `table_edits.py` 針對明確 edited_cols 做同列不同儲存格安全合併：只在該格 base 仍相同時合併；同格、列結構／metadata、欄位值或鎖定衝突仍拒絕。這使 image／audio 平行分支可以各自寫回同列不同欄。
- `docs/EXECUTION_API.md` 已更新精確協定、例子、生命週期及界線。

## 驗證

使用真實 PostgreSQL `127.0.0.1:55433`，測試只建立及清理各自唯一測試專案。

```powershell
$env:OPENBENCH_TEST_DB_URI='postgresql://postgres@127.0.0.1:55433/postgres'
$env:PYTHONPATH='tests'
python -m unittest test_execution test_flow_scopes test_table_proposals -v
```

結果：39 項通過、0 跳過（2026-10-16，審查修正後重跑）。其中新增 `test_flow_scopes.py` 15 項，包含：

- 真實新增列提案 → 審核後拆成 image／audio → 逐列 video → 單次、有序 aggregate。
- 單列指定起點重跑、狀態欄篩選、參考表完整讀取。
- 零列、來源錯誤、來源列刪除、dismiss、失敗／取消／重試、跨連線恢復與不重複展開。
- doc 審核、替換、revision 衝突；遮罩與 stable IDs。
- 不同格平行提案能合併，同格平行提案維持衝突。
- 直接從 aggregate 起點重跑仍套用 row_source 狀態篩選；空集不會退回選取列或整表。來源 tabs 文字／結構與 rows 使用相同篩選集合。
- aggregate 沒有 row_source、只提供 row_ids／target_tab 時，仍只在指定來源分頁傳入選列；不裁切其他美術／資產參考分頁。執行紀錄保留 selection_tabs 作為篩選分頁依據。
- doc asset 輸出使用經 safe_href 驗證的 ProseMirror link mark；真實提案套用後保留可點擊媒體連結。
- 原 16 項 execution 與 8 項 table proposal 回歸全部通過，包括實際 HTTP claim／asset／completion、lease、權限、鎖與原子失敗。

## 明確語意與界線

- 採 stage barrier，不逐列串流啟動下一節點；同一階段多列與獨立分支仍可由多 worker 平行消化。
- 單列 redraw 後的 aggregate 只聚合該新 run 選取的列。要重組整片，可從 aggregate 起點啟動全來源 run，讀已完成 sheet。
- 相同 row_source 的 ID／順序在首次使用後固定；不同來源設定各自凍結。後續新增列需要新 run。
- doc output 是純文字段落與媒體連結，不接受任意 HTML／editor JSON。文件寫入採整頁 revision 保護。
- 本報告驗證 scheduler 與 proposal 路徑；真實 provider／FFmpeg adapter 屬 Task 2，由主代理另行驗證。
- 已修復 fresh review 找到的 aggregate-only 篩選遺漏、doc 媒體連結只有純文字兩項問題；主代理／審查者仍需確認最終審查結果。
