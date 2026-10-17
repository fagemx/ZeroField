# OpenBench 安裝與部署

## 安裝選擇

OpenBench 需要 Python 3.11 以上及 PostgreSQL。預建 wheel 已含 SQL、前端與 prompts；使用者安裝 wheel 後不需要 Node.js。開發者修改前端或製作新發行包時，先以 Node.js 22 執行 `npm ci --prefix ui`、`npm run build --prefix ui`，再建置 Python 發行包。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install .
# 或安裝你建置／取得的 wheel：
# python -m pip install dist/openbench-0.2.0-py3-none-any.whl
```

可將 `python -m pip` 改為已安裝的 `uv pip`。預設 Python 依賴包含 PostgreSQL driver、Office 文件解析與媒體格式檢查；不包含模型 SDK、GPU 模型、Codex CLI、FFmpeg 或外部生成服務。

資料庫連線優先使用 `OPENBENCH_DB_URI`，其次 `DATABASE_URL`；兩者都沒有時使用 `OPENBENCH_DB_HOST`、`OPENBENCH_DB_PORT`（5432）、`OPENBENCH_DB_NAME`（openbench）、`OPENBENCH_DB_USER`（postgres）、`OPENBENCH_DB_PASSWORD`。請指定實際帳密。啟動會以同一個資料庫使用者套用 `db/` 的可重入 schema，因此首次啟動與更新需要建立／修改 `projectops` schema 的權限。

## 本機 dev 模式

```powershell
$env:OPENBENCH_AUTH_MODE = 'dev'
$env:OPENBENCH_DB_URI = 'postgresql://user:password@127.0.0.1:5432/openbench'
openbench --no-worker --host 127.0.0.1 --port 3020
```

`dev` 允許展示成員切換並建立展示資料；程式拒絕在此模式綁定 `0.0.0.0`。不要把此模式透過反向代理公開給其他人。`--embedded-db` 可啟動本機 PostgreSQL 工具或選用 `pgserver`；指定 `OPENBENCH_PG_BIN`、`OPENBENCH_PG_DATA` 與 `OPENBENCH_PG_PORT` 來控制工具、可寫資料目錄與連接埠。內建資料庫初始化採本機 trust 驗證，適用開發環境。

Wheel 安裝到受保護的系統目錄時，請明確指定可寫的 `OPENBENCH_PG_DATA` 和 `OPENBENCH_RUNTIME_ROOT`，或使用既有 PostgreSQL。內建工具的搜尋路徑不等於跨平台的 PostgreSQL 安裝器。

## Token 模式

每個應用登入 token 至少 24 字元，對應一個正式 UUID。以下產生新的管理者 token 與 UUID；請保存 token 供 `/login` 使用，不要放入 Git：

```powershell
$adminToken = python -c "import secrets; print(secrets.token_urlsafe(32))"
$adminId = python -c "import uuid; print(uuid.uuid4())"
$env:OPENBENCH_TOKENS = @{ $adminToken = $adminId } | ConvertTo-Json -Compress
$env:OPENBENCH_AUTH_MODE = 'token'
$env:OPENBENCH_ADMIN_ID = $adminId
$env:OPENBENCH_ADMIN_NAME = 'Administrator'
$env:OPENBENCH_SESSION_SECRET = python -c "import secrets; print(secrets.token_urlsafe(48))"
$env:OPENBENCH_DB_URI = 'postgresql://user:password@127.0.0.1:5432/openbench'
openbench --no-worker --host 127.0.0.1 --port 3020
```

空資料庫會建立 `OPENBENCH_ADMIN_ID` 指定的管理者；省略此值時 token 模式採第一個 token 的 UUID。已有成員時不會自動覆蓋其角色。開啟 `http://127.0.0.1:3020/login`，輸入 `$adminToken` 保存的值。API 可帶 `Authorization: Bearer <application-token>`；member POST 額外要求 `X-Requested-With: projects`。

管理者在工作台建立其他帳號後，將對應 UUID 加入 `OPENBENCH_TOKENS`。token 不會由成員管理 UI 自動發行。停用成員會使其後續請求失效。瀏覽器 cookie 為 HttpOnly、SameSite=Strict，時效 12 小時；正式 HTTPS 部署設定 `OPENBENCH_COOKIE_SECURE=1`。改動 `OPENBENCH_SESSION_SECRET` 可讓既有簽章 session 失效；若未設定，session 簽章使用 token 對照表衍生的金鑰。請固定並妥善保存部署用 secret。

正式環境透過具有 TLS 的反向代理提供服務，限制應用程式與資料庫的直接網路入口。服務內建的 `ThreadingHTTPServer` 不提供 TLS、登入速率限制、完整 SSO 或密碼重設功能；這些由部署層負責。

## Header 模式

```powershell
$env:OPENBENCH_AUTH_MODE = 'header'
$env:OPENBENCH_HEADER_SECRET = '<at-least-24-random-characters>'
$env:OPENBENCH_ADMIN_ID = '<new-administrator-uuid>'
openbench --no-worker --host 127.0.0.1 --port 3020
```

反向代理必須先驗證使用者，再為每個上游請求設定：

| Header | 值 |
| --- | --- |
| `X-OpenBench-Actor` | 已存在且啟用成員的 UUID，不能是任意 username |
| `X-OpenBench-Proxy-Secret` | 與 `OPENBENCH_HEADER_SECRET` 相同的 secret |

Proxy 必須覆寫／移除使用者自行帶入的這兩個 header，並限制其他人直接存取應用程式埠。缺少或不符 secret 的請求拒絕登入；此模式不使用應用登入頁交換 session。空資料庫首次啟動必須提供 `OPENBENCH_ADMIN_ID`；之後登入身分仍須存在於成員表。

## Docker Compose

Dockerfile 先用 Node.js 22 建置前端，再安裝含 runtime resources 的 Python package，以非 root 使用者執行。Compose 使用 PostgreSQL 17、named volume、資料庫 healthcheck 與 token 驗證，預設只將 HTTP port 映射至主機 `127.0.0.1:3020`。

在上方 token 產生步驟後，設定 Compose 所需的兩項值：

```powershell
$env:OPENBENCH_DB_PASSWORD = python -c "import secrets; print(secrets.token_urlsafe(32))"
# OPENBENCH_TOKENS 必須已設定為 token → UUID 的 JSON map。
docker compose config --quiet
docker compose up --build -d
docker compose ps
```

啟動後開啟 [登入頁](http://127.0.0.1:3020/login)。Compose 的新資料庫從 token 對照表第一個 UUID 建立管理者。右側對話助理預設為 `OPENBENCH_PROVIDER=openai_compat`，啟用時另設定 `OPENBENCH_API_BASE`、`OPENBENCH_API_KEY` 與 `OPENBENCH_MODEL`；未設定有效模型服務時，對話助理回報錯誤，不會自動改走 CLI。若要使用 CLI，必須明確設定 `OPENBENCH_PROVIDER=codex_cli` 並安裝／登入相應執行器。Python package 包含外部 Worker 執行器；模型、ComfyUI、FFmpeg／ffprobe 及 Codex CLI 由各 Worker 主機另外安裝。

HTTP `/healthz` 是 liveness；它回應成功不代表資料庫、登入或生成服務已完成驗證。請另外登入、建立測試分頁，並以真實 Worker 執行一次可審核的任務。Compose 設定可在未啟動 engine 時解析，但 image build／container 啟動必須有可用的 Docker daemon；目前本機驗證狀態見 [發佈驗證紀錄](packaging-report.md)。

正式公開前配置 HTTPS proxy；只有經 HTTPS 存取時才將 `OPENBENCH_COOKIE_SECURE=1`。備份 PostgreSQL named volume／`pg_dump`，因為文件、原始檔母體、資產、版本、成員與執行紀錄都存放於資料庫。更新前先備份並在測試環境檢查 schema；`docker compose down` 會保留 named volume，`down -v` 會刪除資料。應用 runtime cache 放在容器使用者的可寫家目錄，並非資料庫備份的替代品。

## Worker 與生成服務

`--no-worker` 只關閉右側對話助理的內建背景執行緒；DAG 外部 Worker 可獨立運作。管理者從工作台設定註冊能力與允許的專案，取得只顯示一次的 Worker token。保持 `OPENBENCH_LIMB_TOKEN` 與應用 token 分開。

```powershell
$env:OPENBENCH_LIMB_TOKEN = '<issued-worker-token>'
openbench-worker --config examples/worker.example.json
```

先複製並編輯範例設定，填入 Head URL、已註冊的能力及模型端點。內建 OpenAI-compatible LLM、ComfyUI、HTTP bridge、speech 與 FFmpeg adapter 的設定、供應商橋接契約及音訊合成規則見 [WORKERS.md](WORKERS.md)。若只需測試協定，可執行 `python examples/worker.py --url http://127.0.0.1:3020 --once`；此最小範例只回傳 echo 或既有媒體。

Worker 用自己的 bearer token 讀取其允許專案的資產，只能領取匹配能力／指定綁定的任務。部署時隔離 Worker 的檔案權限、網路、供應商金鑰與運算資源，並監測 provider errors。註冊本身不代表服務已連線：Worker 需持續 poll。租約失效會停止輪詢與寫回並中止本地 FFmpeg；已提交的遠端模型任務仍依供應商取消政策處理。

預設提案審核、直接寫回、鎖定／過期版本衝突、取消／重試、租約到期，以及 Office 匯出限制都保留於正常服務路徑；設定更多 provider 名稱不會移除這些限制。協定詳見 [EXECUTION_API.md](EXECUTION_API.md)，Office 保守 Patch 範圍見 [README](../README.md#本地檔案交接範圍)。

## 發行驗證

先建置前端，再執行 Python／前端測試與獨立 PostgreSQL 整合測試。設定 `OPENBENCH_TEST_DB_URI` 才會執行 PostgreSQL 測試；請勿指向正式資料庫。

```powershell
npm ci --prefix ui
npm test --prefix ui
npm run build --prefix ui
python -m unittest discover -s tests -v
python -m pip install build
python -m build
python scripts/verify_wheel.py dist/openbench-0.2.0-py3-none-any.whl
```

`uv build` 亦可產出 sdist 和 wheel。驗證腳本確認 6 個 SQL migration、兩份 prompts、console entry point，以及前端 index 所引用的 JS／CSS 都在 wheel 中。CI 另建立乾淨 venv、安裝 wheel、離開 checkout 後呼叫 CLI 和資源路徑，避免只在原始碼目錄可執行的假成功。`.github/workflows/ci.yml` 包含 Python 3.11／3.12、PostgreSQL 17 及 Docker image 建置工作；它們只有在實際 workflow 執行後才算 CI 通過。
