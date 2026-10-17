# OpenBench 0.2 產品化驗收（2026-10-16）

原始 Roadmap M0～M7 的工程交付項目已實作完成，包含動態逐列產線、匯總合成及可執行 Worker。逐條對照見 [ROADMAP_COMPLETION.md](ROADMAP_COMPLETION.md)；原始產品規格保留在 [PRODUCTIZATION_ROADMAP.md](PRODUCTIZATION_ROADMAP.md)。

## 最終驗證

以下是 M0～M7 的原始工程驗收紀錄。其後通用工作台介面更新（包含暫停影片播放）另見 [WORKSPACE_UX.md](WORKSPACE_UX.md)，請以該文件判讀現行操作。

- Python 單元／整合套件：**85 項通過，0 跳過**，使用獨立真實 PostgreSQL 16。
- 前端 Node 測試：**41 項通過**；Vite 正式建置通過（125 modules）。
- 獨立執行審查專用回歸：3 項通過，涵蓋取消與提案競態、Worker 資產權限、刪除輸入分頁後的佇列處理。
- 真實產線：`test_production_pipeline.py` 經 Head HTTP、PostgreSQL、正式 Worker 執行器完成 6 項任務：一次拆鏡 → 2 列生圖 → 2 列影片 → 一次合成。實際 FFmpeg 輸出約 1.02 秒 MP4，ffprobe 確認影片與音軌，成片連結寫回文件。LLM／ComfyUI／影片 bridge 的模型端使用隔離 HTTP fixture，未呼叫付費模型。
- DAG PostgreSQL 回歸涵蓋新增列後展開、審核閘門、平行分支／匯流、空列、狀態篩選、單列起點重跑、匯總選取範圍、重試／取消及不同欄位並行套用。
- HTTP 回歸涵蓋 token／cookie／header、停用及唯讀角色、跨站寫入拒絕、XLSX 匯入→編輯→匯出→過期重匯入拒絕，以及影片／音訊上傳、metadata 與 Range。
- 瀏覽器實測：多工作表匯入／切換、Excel TSV 貼上、公式重算、媒體上傳、影片秒數／解析度、列歷史、批次交接、單格重抽自動選取生圖起點、切頁保存工作流；新建影劇範本帶入真實四節點流程。
- sdist／wheel 建置、資源完整性、乾淨 Python 3.12 環境安裝及離開 checkout 的兩個 CLI／資源讀取通過。Compose 設定解析通過。詳見 [packaging-report.md](packaging-report.md)。

獨立審查發現的範圍、匯出、媒體與租約問題均已修正並複驗：[DAG 審查](dag-review2.md)、[產品介面與匯出審查](product-review2.md)、[Worker 審查](worker-review.md)。先前的 [檔案交接審查](handoff-review.md) 與 [執行權限審查](execution-review.md) 亦保留供追溯。

## 實作與部署界線

- 內建 OpenAI-compatible、ComfyUI、HTTP bridge、speech、FFmpeg adapter；模型、ComfyUI API workflow、供應商 bridge 與帳戶憑證須按 [WORKERS.md](WORKERS.md) 配置。沒有宣稱已驗證付費模型的生成品質或所有供應商的原生 API。
- Office 採保守原檔 Patch。未修改時原始位元組直接匯出，局部修改保留其他 ZIP parts；複雜結構變更、共享／陣列公式、特殊 DOCX 欄位等不支援的修改明確拒絕。畫布不能編輯全部 Office 功能。
- XLSX 修改後設定自動完整重算，實際計算由開啟檔案的試算表軟體完成。原生匯出校正表頭造成的公式位移；前端僅支援已實作的算術／聚合函數。
- 角色是工作台層級，沒有逐專案成員 ACL；Worker 有獨立專案範圍。數字遮罩是規則式最小化，保留日期／識別碼等結構，沒有通用 DLP 保證。
- 取消會阻止後續輪詢、上傳與寫回，並終止本地 FFmpeg；已發出的遠端模型任務可能繼續至供應商完成／逾時。
- Docker Desktop 已嘗試啟動，但本機 engine 查詢未就緒，因此未實測 image build／container 啟動。GitHub Actions 已配置，尚未推送觸發遠端 CI；兩者不列為通過。正式部署的 TLS、備份、模型憑證依 [DEPLOYMENT.md](DEPLOYMENT.md) 配置。

## 本機驗收服務與重現方式

[完整影劇範本驗收專案](http://127.0.0.1:3022/projects/roadmap-acceptance/#storyboard) 使用獨立 PostgreSQL 16（55433）。原有 3020 服務維持原狀。驗收素材為本機產生的色塊圖／短影片，不是模型生成作品。

```powershell
$env:OPENBENCH_TEST_DB_URI = 'postgresql://postgres@127.0.0.1:55433/postgres'
python -m unittest discover -s tests -q
python docs/execution-review-repro.py
npm test --prefix ui
npm run build --prefix ui
uv build
python scripts/verify_wheel.py dist/openbench-0.2.0-py3-none-any.whl
```
