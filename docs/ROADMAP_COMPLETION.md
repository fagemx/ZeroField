# Roadmap M0～M7 逐項完成對照

驗收日期：2026-10-16。以下「完成」指原始規格的實作與本機驗證交付；外部模型、Docker engine 及遠端 CI 的實測狀態另列於 [ACCEPTANCE.md](ACCEPTANCE.md)，不以設定檔取代執行證據。

後續產品方向已調整為通用文件／表格工作台，使用者要求暫不提供影片播放。下面 M2.2b 記錄原始工程驗收；現行 UI 改為影片附件下載。最新介面行為與驗證請見 [WORKSPACE_UX.md](WORKSPACE_UX.md)。

| 完成 | 原始需求 | 實作位置 | 驗證證據 |
| --- | --- | --- | --- |
| ✅ M0.1 | source_filename／mime／blob／linked_path | `db/149_project_docs_schema.sql`、`repository.py` | PostgreSQL schema／HTTP 整合 |
| ✅ M0.2 | XLSX／CSV／DOCX／MD 拖入新增；重匯入 Diff／revision／reanchor | `file_handoff.py`、`service.py`、`http.py`、`TabRail.jsx` | `test_file_handoff.py`、`test_product_http.py`；瀏覽器匯入 |
| ✅ M0.3 | 有母檔局部 Patch，無母檔乾淨匯出 | `file_handoff.py` | 15 項交接測試，含多工作表、保留 ZIP parts、公式／型態／重算旗標 |
| ✅ M0.4 | propose_table_edit 跨頁修改與新增列 | `tool_specs.py`、`tools.py`、`table_edits.py` | `test_table_proposals.py`：審核、過期、鎖定、原子寫入與並行欄位 |
| ✅ M1.1 | full_access 預設／mask_numbers 儲存及設定 | schema、`WorkspaceSettings.jsx` | 專案設定、DB／HTTP 測試 |
| ✅ M1.2 | 模型、工具、附件、歷史、遠端手腳政策分流 | `privacy.py`、`masking.py`、`service.py`、`flow_runner.py` | `test_openbench.py`、`test_execution.py`、`test_providers.py` |
| ✅ M2.1 | 四種專案範本與實際產線定義 | `templates.py`、`service.py`、`ProjectHub` | 範本測試；瀏覽器新建影劇專案；完整 HTTP 產線 |
| ✅ M2.2a | 圖片縮圖、Lightbox、上傳替換、單格重抽 | `MediaCell.jsx`、`SheetSurface.jsx` | 瀏覽器圖片上傳與重抽起點；前端 media／flow 測試 |
| ✅ M2.2b | 影片播放器、秒數、解析度；音訊播放與長度 | `MediaCell.jsx`、`media.py`、asset metadata／Range API | HTTP WAV／MP4、瀏覽器 0.5 秒／160×90 顯示 |
| ✅ M2.3 | 多列勾選、批次助理及工作流交接 | `SheetSurface.jsx`、`flowModel.js` | 前端列選取測試；瀏覽器批次交接 |
| ✅ M3.1 | 四種能力、手腳註冊／列表／指定綁定 | `db/157_execution.sql`、`flow_runner.py`、`WorkspaceSettings.jsx` | `test_execution.py`；token 雜湊、撤銷與專案範圍 |
| ✅ M3.2 | claim／renew／complete／fail／upload-cell-asset | `http.py`、`flow_runner.py` | HTTP 真實領取／續期／媒體上傳與寫回；過期租約回歸 |
| ✅ M3.3 | 實際文字、多模態與合成手腳 | `limb_worker.py`、`worker.example.json` | `test_limb_worker.py`；真實 FFmpeg；模型 API 使用隔離 fixture |
| ✅ M4.1 | Excel Ctrl+V TSV 整片貼上、多列 put_row | `sheetModel.js`、`SheetSurface.jsx` | 引號／換行／追加列測試與瀏覽器貼上 |
| ✅ M4.2 | 動態增刪欄、文字／數值／公式／媒體／狀態型態 | `SheetSurface.jsx`、`doc_schema.py` | 前端資料轉換測試；正式建置 |
| ✅ M4.3 | 單列歷史 Prompt 與媒體前後版本 | `page_history.py`、`SheetSurface.jsx` | `test_media_history.py` 保留完整歷史媒體 URL；瀏覽器歷史 |
| ✅ M4.4 | 多工作表切換、當前工作表匯出 | `file_handoff.py`、`SheetSurface.jsx` | 雙工作表瀏覽器驗收、XLSX／CSV 測試 |
| ✅ M5.1 | 自由連線、座標／版本持久化、分支／匯流 | `FlowSurface.jsx`、`flow_runner.py` | 圖形循環／分支測試；PostgreSQL DAG；切頁後版本 2 保留 |
| ✅ M5.2 | 一次拆鏡→動態逐列→僅一次匯總 | `flow_runner.py` execution／scope／row_source | `test_flow_scopes.py`；6 項任務真實 HTTP 產線 |
| ✅ M5.3 | 狀態篩選整表、指定單列／指定節點重跑 | Flow／Sheet UI、`selection_tabs`／`start_node_id` | 狀態、單列及 aggregate restart 回歸；瀏覽器單格重抽 |
| ✅ M5.4 | 即時節點／列進度、審核、取消／重試 | `FlowSurface.jsx`、`SheetSurface.jsx`、持久化 task／run | 執行測試、3 項獨立競態／權限回歸 |
| ✅ M6.1 | 成員管理彈窗、角色與職務標籤 | `members.py`、`WorkspaceSettings.jsx` | `test_auth.py`、`test_product_http.py`；最後管理者保護 |
| ✅ M6.2 | dev／token／header、登入 Cookie、角色檢查 | `auth.py`、`runtime_http.py`、`server.py` | 真實 HTTP 登入／停用／唯讀／跨站拒絕 |
| ✅ M7.1 | pyproject／wheel／sdist、資源與 CLI | `pyproject.toml`、`setup.py`、`MANIFEST.in`、`openbench_data` | 發行檔建置、資源檢查、乾淨安裝、兩個 CLI |
| ✅ M7.2 | Dockerfile／Compose | 根目錄部署檔、`DEPLOYMENT.md` | Compose config 通過；本機 engine 未就緒，容器執行未驗證 |
| ✅ M7.3 | GitHub Actions CI | `.github/workflows/ci.yml` | 已配置 Python 3.11／3.12、PG17、FFmpeg、前端、封裝、Docker；遠端尚未觸發 |

`project_docs/` 與 `ui/src/` 檔案在表中以檔名簡寫。M3 schema 以獨立可重入 migration `157_execution.sql` 實現，避免把執行引擎混入既有對話助理 migration。Office 匯出用 openpyxl／python-docx 解析，直接 Patch OOXML ZIP 成員以保存未改動內容；支援界線見驗收文件。

所有可在本環境執行的驗收：85 項 Python、41 項前端、3 項獨立回歸、正式建置及乾淨安裝均通過。審查修正紀錄見 [DAG](dag-review2.md)、[產品介面](product-review2.md)、[Worker](worker-review.md)。
