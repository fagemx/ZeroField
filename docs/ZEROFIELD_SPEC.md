# ZeroField Studio 參賽開發規格書 (`ZEROFIELD_SPEC.md`)

**專案位置**：`C:\ai_project\ZeroField`  
**目標賽事**：ComfyUI「Open Source Higgsfield Challenge」（截止：2026-10-30 09:00 PT / 台北時間 2026-10-31 00:00）  
**品牌口號**：*“No paywalls. No closed APIs. Just pure open-weights cinema & V2V illusion.”*

---

## 1. 競賽定位與「四獎同搶」策略（Prize Stacking Strategy）

### 1.1 同時鎖定的四大獎項
| 目標獎項 | 獎金／獎品 | `ZeroField` 的達標設計 |
| :--- | :--- | :--- |
| **1. Best Overall（總冠軍）** | **\$10,000 現金** | 同時重建官方點名的兩大產品（`Cinema Studio` 光學多鏡頭工作台 + `Genjutsu / OpenJutsu` 影片動作轉移與換物），具備完整 UI、多鏡頭表格、ComfyUI DAG 畫布與 FFmpeg 自動成片。 |
| **2. Open Weights Only（純開源權重獎）** | **GeForce RTX 5090** | 100% 採用開放權重模型：**`FLUX 3 Image Klein (5.6B)`**（角色定妝與首尾幀）+ **`LTX-2.5`**（音畫同步鏡頭生成與 V2V 動作轉移），**零閉源 Partner Nodes**。 |
| **3. Most Innovative / Most Viral** | **GeForce RTX 5090** | **創新點**：多代理拆鏡 + Multi-Take 並排盲測 + DAG 工作流編排；**傳播點**：OpenJutsu 支援「一鍵輸出原片 vs. 改造後並排對比 MP4（Viral Split-Screen）」。 |
| **4. VFX Workflow Built with LTX（加碼獎）** | **\$2,000 現金** | 以 **`LTX-2.5`** 為核心影片與 VFX 引擎（涵蓋 I2V 電影運鏡 + V2V Motion Transfer / Object Swap）。 |

---

## 2. 具體施工清單（4 大核心 Tasks）

### Task 1：升級 [`project_assistant/limb_worker.py`](file:///C:/ai_project/ZeroField/project_assistant/limb_worker.py)

1. **`comfyui()` 支援上傳影片資產（`video_node`）與多參考圖（`reference_image_node`）**：
   - 當 `config.get("video_node")` 設定時，從 `_media_urls(task["input"])` 尋找 `mime.startswith("video/")` 的原片資產。
   - 透過 `POST {base}/upload/image` 將 `.mp4` 上傳至 ComfyUI `input/` 目錄，並將回傳的檔名寫入 `workflow[str(config["video_node"])]["inputs"][config.get("video_input", "video")]`（支援 `VHS_LoadVideo` / `LoadVideo`）。
2. **`comfyui()` 支援結構化欄位映射（`param_bindings`）与光學預設編譯**：
   - 讀取分鏡表中的 `Optical Rig`（如 `ARRI Alexa 65 + 35mm Anamorphic f/1.4`）與 `Camera Motion`（如 `Slow Dolly Push-In`），自動展開為標準光學英文 Prompt Tokens 並注入 `prompt_node` 與對應的 `LTX-2.5` 節點參數。
3. **`ffmpeg()` 新增 `layout: "side_by_side"`（Viral Split-Screen 對比合成）**：
   - 針對 `openjutsu-lab` 每一列同時擁有「原片（Source Driving Video）」與「LTX-2.5 改造後影片（Remastered Video）」的紀錄，使用 FFmpeg `hstack` 濾鏡合成 `1280x720` 的左右同步對比 MP4，寫回表格第 6 欄 `Viral Split-Screen MP4`。

---

### Task 2：打造 `zerofield_studio` 旗艦英文展示範本（[`project_docs/templates.py`](file:///C:/ai_project/ZeroField/project_docs/templates.py) & [`project_docs/service.py`](file:///C:/ai_project/ZeroField/project_docs/service.py)）

將預設啟動建立的展示專案改為英文／雙語的 **`ZeroField: Cinema Studio & OpenJutsu Showcase`**，包含 5 個核心分頁：

1. **`director-brief` (`doc`) — Director's Panel & Scene Script**
   - 定義全片類型（Genre: Cyberpunk Noir）、光學套件（Optical Package: ARRI Alexa 65 + 35mm Master Anamorphic）、剪輯節奏（Montage Pacing）與分場劇本。
2. **`soul-cast` (`sheet`) — Soul Cast & Asset Lookbook (FLUX 3 Klein)**
   - 欄位：`Asset ID` | `Character / Set` | `Locked Optical & Appearance Prompt (Seed)` | `FLUX 3 Turnaround` | `Voice / Audio Profile` | `Status` | `Notes`
   - `COLUMN_TYPES["soul-cast"] = ["text", "text", "text", "image", "text", "status", "text"]`
3. **`cinema-studio` (`sheet`) — Cinema Studio Multi-Shot Slate (LTX-2.5 I2V)**
   - 欄位：`Shot` | `Optical Rig (Camera & Lens)` | `Camera Motion` | `Action & Audio Prompt` | `Keyframe (FLUX 3 Klein)` | `LTX-2.5 Cinema Shot` | `Status` | `Director Take Notes`
   - `COLUMN_TYPES["cinema-studio"] = ["text", "text", "text", "text", "image", "video", "status", "text"]`
4. **`openjutsu-lab` (`sheet`) — OpenJutsu V2V Matrix (LTX-2.5 Motion Transfer & Swap)**
   - 欄位：`Clip ID` | `Jutsu Mode` | `Source Driving Video` | `Target Cast / Swap Prompt` | `LTX-2.5 Remastered Video` | `Viral Split-Screen MP4` | `Status` | `Notes`
   - `COLUMN_TYPES["openjutsu-lab"] = ["text", "text", "video", "text", "video", "video", "status", "text"]`
5. **`comfy-pipeline` (`flow`) — Comfy Developer Platform DAG**
   - 節點 1：`1. Optical Script Compiler (LLM)`
   - 節點 2：`2. Soul Cast & Keyframes (FLUX 3 Klein)`
   - 節點 3：`3. Cinema Studio Multi-Shot (LTX-2.5 I2V)`
   - 節點 4：`4. OpenJutsu V2V Remaster (LTX-2.5 V2V)`
   - 節點 5：`5. Director's Cut & Viral Grid (FFmpeg)`

---

### Task 3：前端 `ui/src/` 影視工作室體驗與播放效能升級

1. **高效能內嵌 `<video>` 播放器、快取與 Multi-Take 版本切換**：
   - **前端 `/meta` 快取**：在 [`ui/src/MediaCell.jsx`](file:///C:/ai_project/ZeroField/ui/src/MediaCell.jsx) 建立模組級 `const META_CACHE = new Map()`，避免表格滾動或切分頁時重複請求 `/meta`。
   - **按需解碼（Hover-to-Play）防解碼器崩潰**：當儲存格為 `video` 時，渲染 `<video preload="metadata" muted loop playsInline>`，預設靜止顯示首幀，**滑鼠懸停（`onMouseEnter`）才呼叫 `.play()`、移開（`onMouseLeave`）即 `.pause()`**，避免單頁超過 Chromium 硬體解碼器上限；在 `SheetReview` 審核抽屜與 Lightbox 中則支援完整音訊控制與 Multi-Take（Take 1 / Take 2 / Take 3）並排同步預覽。
   - **後端零拷貝 `/meta` 與 HTTP Range 串流**：
     - 在 [`project_docs/repository.py`](file:///C:/ai_project/ZeroField/project_docs/repository.py) 新增 `get_asset_meta(conn, slug, asset_id)`（只查 `content_type, byte_size`，不撈 `data` bytea）。
     - 在 [`project_docs/http.py`](file:///C:/ai_project/ZeroField/project_docs/http.py) 的 `asset` 路由支援 `If-None-Match` (`304`)、`.cache/assets/{asset_id}` 本地磁碟快取與 `Range: bytes=start-end` (`206 Partial Content`) 串流。
2. **Director's Optical & Motion Quick Picker**：
   - 點擊 `cinema-studio` 的 `Optical Rig` 或 `Camera Motion` 欄位（或 `openjutsu-lab` 的 `Jutsu Mode` 欄位）時，提供快速預設膠囊選單：
     - **Optical Rigs**：`ARRI Alexa 65 · 35mm Anamorphic f/1.4`、`RED V-Raptor · 85mm Prime f/1.8`、`IMAX 70mm · 24mm Wide`、`16mm Bolex Vintage Film`
     - **Camera Motions**：`Slow Dolly Push-In`、`Handheld Urgency`、`Crane Rise High-Angle`、`Orbit 180°`、`Static Tripod`、`Whip Pan`
     - **Jutsu Modes**：`Motion Transfer (Full Scene & Character)`、`Object / Product Swap (Masked)`、`Re-Shoot Camera Angle`

---

### Task 4：一鍵啟動腳本 `run_studio.py` 與開源 Workflows (`workflows/`)

1. 建立 `run_studio.py`：
   - 一行指令 `python run_studio.py --port 3020 --comfy-url http://127.0.0.1:8188` 自動啟動嵌入式資料庫（或連至現有 DB）、自動註冊內建 ComfyUI + FFmpeg Worker 並在背景執行緒領取任務，免去評審手動複製 Token 的步驟。
2. 在 `workflows/` 放入 3 個純開源權重的 ComfyUI API 格式工作流：
   - `workflows/flux3_klein_soul_cast.json`
   - `workflows/ltx25_cinema_shot.json`
   - `workflows/ltx25_openjutsu_v2v.json`
