# M7 發佈驗證紀錄

驗證日期：2026-10-16。本紀錄只記錄實際執行過的發佈檢查；應用行為與瀏覽器驗收由主代理另外執行。

最終補強版已重新建置，包含 `limb_worker.py`、`openbench-worker` entry point、五種 adapter 與最新媒體／DAG 前端。資源檢查現在同時驗證兩個 CLI；sdist 包含 `examples/worker.example.json` 及完整驗收文件。相同乾淨環境重裝新 wheel，再於 checkout 外驗證兩個 CLI 與資源。

## 已實測

- `uv build` 成功建立 `dist/openbench-0.2.0.tar.gz` 和 `dist/openbench-0.2.0-py3-none-any.whl`。Wheel 從產生的 sdist 建置，證明來源封裝包含需要的建置輸入。
- `python scripts/verify_wheel.py dist/openbench-0.2.0-py3-none-any.whl` 通過。確認 6 個 SQL migration、兩份助理 prompts、console entry point、前端 index，以及 index 引用的 JS／CSS 都存在。
- 檢查 sdist 內容，包含前端 package-lock、原始碼、Python package、SQL、部署文件、驗證腳本；不含 node_modules 或 dotenv。Wheel 不依賴 repo 外的原始 SQL／static 目錄。
- 使用 `uv pip install --target .openbench_runtime/packaging-target --no-deps <wheel>` 安裝後，透過 `python -I` 僅將該安裝目錄加入 import path，確認 `SCHEMA_DIR`、`STATIC_DIR` 都指向已安裝的 `openbench_data`，全部 migration／前端／prompts 可讀取，並執行 console entry point 的 `--help`。此檢查沒有啟動新資料庫或伺服器。
- 另以 `uv venv` 建立 Python 3.12.7 的乾淨環境，完整安裝 wheel 與所有依賴，離開 repo 根目錄執行真正的 `openbench.exe --help`，並以 `python -I` 驗證所有 SQL／前端／prompts 與 psycopg、openpyxl、python-docx、Pillow、pypdf、lxml 的匯入。結果通過，未借用 checkout 的 Python package。
- `docker compose config --quiet` 使用臨時驗證用的資料庫密碼與 token map 通過；未輸出或保存真實 secret。

## 未能在本機執行

初次 `docker version` 回報 Docker client 28.4.0 可用，但 `dockerDesktopLinuxEngine` named pipe 不存在。補強階段已嘗試啟動 Docker Desktop；後續 engine／Desktop 狀態查詢逾時，仍未取得可用 daemon。因此沒有宣稱 image build、container 啟動或 Compose 執行驗證通過。

`.github/workflows/ci.yml` 已配置 Python 3.11／3.12、PostgreSQL 17 整合測試、前端測試／建置、sdist／wheel 建置、資源驗證、離開 checkout 後的 wheel 安裝驗證，以及 Docker image build。尚未觸發遠端 workflow，不能視為已通過 CI。

## 封裝方式

`setup.py` 的 build command 將 `db/*.sql` 與當次 `static/projects/` 複製至 build package 的 `openbench_data`，避免在原始碼中維護重複資產樹。原始 checkout 直接讀 repo 資源，安裝的 wheel 改讀 package 內的資源。`project_assistant/prompts/*.md` 以明確 package-data 規則封裝。缺少 SQL、前端 index 或 JS entry 時，建置明確失敗。

Dockerfile 在 `pip install .` 前完成前端並複製進 image，包含打包資源，並設定非 root 使用者可寫的 runtime cache 路徑。Compose 保留資料庫 healthcheck 與 named volume，預設 token 驗證，並將主機 HTTP 入口限制為 loopback 的 3020。

後續修改 Python、SQL、prompts 或前端時，必須重跑前端建置（若有改動）、`uv build` 和 wheel 驗證，再交付新發行檔。
