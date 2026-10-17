# OpenBench 參賽專版規格書：OpenCinema & OpenJutsu Studio
**目標賽事**：ComfyUI「Open Source Higgsfield Challenge」（截止時間：2026-10-30 09:00 PT / 台北時間 2026-10-31 00:00）  
**基座專案**：[`C:\ai_project\OpenBench`](file:///C:/ai_project/OpenBench/README.md)  
**關聯規格**：[`docs/AGENT_ORCHESTRATION_SPEC.md`](file:///C:/ai_project/OpenBench/docs/AGENT_ORCHESTRATION_SPEC.md)

---

## 1. 競賽定位與「三料大獎疊加」策略（Prize Stacking Strategy）

### 1.1 產品代號與一句話Pitch
> **OpenCinema & OpenJutsu Studio（基於 OpenBench）**：  
> 100% 開源權重（`LTX-2.5` + `FLUX 3 Image Klein`）驅動的 **AI 電影多鏡頭導演工作台（Cinema Studio 重建）** 與 **批次影片動作轉移／物件替換實驗室（Genjutsu 重建）**，內建光學鏡頭編譯器、多版本並排盲測（Multi-Take Review）與 FFmpeg 一鍵成片／對比九宮格合成。

### 1.2 同時鎖定的四大獎項（符合官方 Q&A「主獎 + 模型加碼獎可同時獲獎」規則）
| 目標獎項 | 獎金／獎品 | 我們的達標設計（架構對齊點） |
| :--- | :--- | :--- |
| **1. Best Overall（總冠軍）** | **\$10,000 現金** | 同時完成官方點名的兩大旗艦產品（`Cinema Studio` + `Genjutsu / OpenJutsu`），且具備現成完整的分鏡表格、DAG 畫布、審核提案與 FFmpeg 自動成片，完整度遠超單頁套殼作品。 |
| **2. Open Weights Only（純開源權重獎）** | **GeForce RTX 5090** | 核心工作流 100% 採用開放權重模型：**`FLUX 3 Image Klein (5.6B)`**（角色定妝與首尾幀）+ **`LTX-2.5`**（音畫同步鏡頭生成與 V2V 動作轉移），**零閉源 Partner Nodes**。 |
| **3. Most Innovative / Most Viral** | **GeForce RTX 5090** | **創新點**：多代理分鏡拆解 + 多 Take 並排盲測 + DAG 工作流編排；**傳播點**：OpenJutsu 支援「一鍵輸出原片 vs. 改造後並排對比 MP4（Viral Split-Screen）」。 |
| **4. VFX Workflow Built with LTX（加碼獎）** | **\$2,000 現金** | 以 **`LTX-2.5`** 為核心影片與 VFX 引擎（涵蓋 I2V 電影運鏡 + V2V Motion Transfer / Object Swap）。 |

---

## 2. 現有資產盤點 vs. 參賽增量改造清單（Delta Map）

我們**不重寫底層系統**，直接複用 `OpenBench` 現成能力，僅針對比賽評分點做精準擴充：

| 模組 | `OpenBench` 現有基礎 | 參賽專版新增改造（12 天內完成） | 修改檔案 |
| :--- | :--- | :--- | :--- |
| **專案範本 (`templates.py`)** | `ai_drama` 已有劇本、角色資產表、EP01 分鏡表、4 節點產線 | 新增 **`open_higgsfield`（OpenCinema & OpenJutsu Studio）** 旗艦英文／雙語範本，內建 **Soul Cast 資產表**、**Cinema Studio 光學分鏡表**、**OpenJutsu V2V 矩陣改造表** 與 **5 節點 LTX-2.5 產線** | [`project_docs/templates.py`](file:///C:/ai_project/OpenBench/project_docs/templates.py) |
| **ComfyUI 執行器 (`limb_worker.py`)** | 支援單張 `image_node` 上傳、`prompt_node`、`seed_node`、輪詢 `/history` 並取回圖片／影片 | 1. 新增 **`video_node` 上傳**（支援將分鏡表原片上傳至 ComfyUI 供 `LTX-2.5` V2V / Genjutsu 使用）<br>2. 新增 **`param_bindings` 欄位參數映射**（將表格的焦段、運鏡、重繪幅度注入節點）<br>3. 支援 **Comfy Developer Platform (Comfy API / Router)** 與本地 `127.0.0.1:8188` 雙模切換 | [`project_assistant/limb_worker.py`](file:///C:/ai_project/OpenBench/project_assistant/limb_worker.py) |
| **FFmpeg 合成器 (`limb_worker.py`)** | `ffmpeg` adapter 已支援依序把多鏡影片＋音訊合成 1280x720 MP4 | 新增 **`mode: "viral_compare"`（並排對比合成）**：自動將「原片（Source Video）」與「OpenJutsu 改造影片」左右並排（`hstack`）輸出對比 MP4，直接用於 Demo 影片與社群分享 | [`project_assistant/limb_worker.py`](file:///C:/ai_project/OpenBench/project_assistant/limb_worker.py) |
| **前端導演介面 (`ui/src/`)** | 支援表格編輯、`image`/`video` 預覽、圖片多版本審核、DAG 畫布 | 1. 新增 **Director's Optical & Motion Picker（光學鏡頭與運鏡選擇器）**：點擊儲存格即可選擇相機／焦段／光圈／運鏡預設<br>2. 影片格支援像圖片格一樣的 **Multi-Take A/B/C 版本切換與預覽** | `ui/src/` 表格儲存格與工具列組件 |
| **開源 Workflow 包 (`workflows/`)** | 僅有設定範例 `workflow_api.json` | 隨附 3 個調校好的純開源權重 ComfyUI API JSON：<br>1. `flux3_klein_soul_cast.json`<br>2. `ltx25_cinema_i2v.json`<br>3. `ltx25_openjutsu_v2v.json` | `workflows/`（新增目錄） |

---

## 3. 核心功能規格設計

### 3.1 模組一：Cinema Studio 開源重建（光學控制 ＋ Soul Cast ＋ 多鏡頭組裝）

#### A. Director's Optical Compiler（光學與運鏡預設字典）
在前端與後端共享一份結構化的電影光學預設庫（儲存於表格的 `optical_preset` 與 `camera_motion` 欄，執行時自動展開為精準英文光學 Token 並注入 `FLUX 3 Klein` 與 `LTX-2.5`）：

| 控制維度 | 預設選項（UI 選單） | 自動編譯注入之 Prompt Tokens & LTX 參數 |
| :--- | :--- | :--- |
| **Camera Body（機身色彩科學）** | `ARRI Alexa 65 (LogC)` / `RED V-Raptor 8K` / `IMAX 70mm Film` / `16mm Bolex Vintage` | `"shot on ARRI Alexa 65, natural skin tones, wide dynamic range, organic film grain"` 等 |
| **Lens & Focal Length（鏡頭與焦段）** | `24mm Wide Anamorphic` / `35mm Master Prime` / `50mm Panavision Anamorphic` / `85mm Portrait f/1.4` / `100mm Macro` | `"35mm anamorphic lens, oval bokeh, subtle horizontal blue lens flare, shallow depth of field"` 等 |
| **Lighting & Atmosphere（燈光氛圍）** | `Chiaroscuro Noir` / `Cyberpunk Neon Rain` / `Golden Hour Backlit` / `High-Key Commercial` | 對應色溫、體積光（volumetric fog）、邊緣光（rim lighting）描述 |
| **Camera Motion（LTX-2.5 運鏡控制）** | `Static Tripod` / `Slow Dolly Push-In` / `Handheld Urgency` / `Crane Rise High-Angle` / `Orbit 180°` / `Whip Pan` | 注入 `LTX-2.5` 運鏡控制詞與對應 Camera LoRA / Motion Strength 參數 |

#### B. Soul Cast（跨鏡頭角色與場景資產鎖定）
對應 [`templates.py`](file:///C:/ai_project/OpenBench/project_docs/templates.py) 的 `assets`（升級為 `soul-cast` 分頁）：
1. 每位演員（如 `CAST-01`）與主場景（如 `SET-01`）擁有獨立列，包含：**固定外觀描述**、**鎖定 Seed**、**`FLUX 3 Image Klein` 生成之高清定妝參考圖**、**聲音特徵描述**。
2. 當 `cinema-storyboard` 分鏡表的畫面描述引用 `CAST-01` 時，`limb_worker.py` 自動將 `CAST-01` 的定妝圖作為 `reference_image` 傳入 ComfyUI（Redux / IP-Adapter / PulID / LTX Reference 節點），確保跨 10 個鏡頭演員臉部與服裝 100% 一致。

---

### 3.2 模組二：OpenJutsu（Genjutsu 開源重建：Motion Transfer & Object Swap 矩陣）

為了同時補足 Comfy 官方 `/hub/apps/` 上標註 `Openjutsu (Coming soon)` 的缺口，我們在同一個專案提供 **`openjutsu-lab`（OpenJutsu 批次影片改造表）**：

#### A. 兩種核心幻術模式（Jutsu Modes）
1. **`Motion Transfer`（動作與運鏡轉移 — 保留動作換角色／換世界）**
   - **輸入**：一段實拍影片（`source_video`，4–15 秒）+ 目標風格或 `Soul Cast` 角色參考圖。
   - **底層 ComfyUI 管線（`workflows/ltx25_openjutsu_v2v.json`）**：
     - `VHS_LoadVideo` 讀取實拍影片 ➔ 抽取 Depth（深度圖）/ Canny 或 Pose 骨架序列 ➔ 送入 **`LTX-2.5`** Video-to-Video / IC-LoRA 控制節點 + `FLUX 3 Klein` 重繪首幀定錨 ➔ 輸出保留原片運鏡與人物動作、但完全替換角色與場景的 1080p 影片。
2. **`Object / Product Swap`（局部物件與服裝替換 — 電商廣告神器）**
   - **輸入**：一段實拍影片（`source_video`）+ 替換目標名稱（如 `"handheld soda can"` 或 `"jacket"`）+ 新產品參考圖（`target_asset`）。
   - **底層 ComfyUI 管線**：
     - 透過文字分割（Florence-2 + SAM2 開源節點）自動產生動態遮罩（Mask Video）➔ 結合 **`LTX-2.5`** Inpainting / V2V 節點與產品參考圖重繪遮罩區域，其餘背景與人物動作 100% 保留。

#### B. 為什麼比原版 Higgsfield Genjutsu 更強？（Matrix Batching + Viral Split-Screen）
- 原版 Genjutsu 一次只能在網頁點一個任務；我們的 **`openjutsu-lab` 表格**允許使用者把同一支實拍影片複製 4 列，分別套用「動漫風」、「賽博龐克偵探」、「黏土動畫」、「替換新產品」4 種 Preset，點擊 DAG 產線**一鍵平行批次跑完**。
- 跑完後點擊 **`Viral Split-Screen Assemble`**，FFmpeg 自動產出「左邊原片、右邊 3 種幻術變體」的同步對比 MP4！

---

## 4. 後端 `limb_worker.py` 擴充規格（精準小手術）

在 [`project_assistant/limb_worker.py`](file:///C:/ai_project/OpenBench/project_assistant/limb_worker.py#L159-L210) 的 `comfyui(task, config, head)` 函式中，我們只需新增約 **45 行程式碼**即可支援完整 Cinema Studio 與 OpenJutsu：

### 4.1 支援上傳原片（`video_node`）與多參考圖（`reference_image_node`）
```python
# 擴充 project_assistant/limb_worker.py 內的 comfyui() 設定支援：
# config 新增可選欄位：
# - "video_node": 指向 VHS_LoadVideo / LoadVideo 節點 ID
# - "video_input": 預設 "video"
# - "param_bindings": {"<node_id>.<input_name>": {"column": 1, "map": {...}}}
# - "comfy_router_url": 支援 Comfy Developer Platform API / Router 端點
```

1. **上傳影片資產至 ComfyUI**：
   - 當 `config.get("video_node")` 存在時，從 `_media_urls(task["input"])` 找到 `mime.startswith("video/")` 的專案影片資產。
   - 透過 `POST {base}/upload/image`（ComfyUI 原生上傳端點支援將 `.mp4` 存入 `input/` 資料夾）上傳後，將回傳的 `uploaded["name"]` 填入 `workflow[str(config["video_node"])]["inputs"][config.get("video_input", "video")]`。
2. **結構化欄位映射（`param_bindings`）**：
   - 允許將表格特定欄位（例如第 2 欄 `Optical Rig`、第 3 欄 `Camera Motion`、或 OpenJutsu 的 `denoise_strength`）自動對應到 ComfyUI JSON 裡的指定節點參數（如 `LTXV Conditioning` 的 `frame_rate`、`KSampler` 的 `denoise`），不需寫死在 JSON 裡。

### 4.2 新增 `ffmpeg_compare`（Viral 對比影片合成模式）
在 [`project_assistant/limb_worker.py`](file:///C:/ai_project/OpenBench/project_assistant/limb_worker.py#L244-L320) 的 `ffmpeg()` 函式中：
- 當 `config.get("layout") == "side_by_side"` 時，針對 `openjutsu-lab` 每一列同時具備「原片（Col 1）」與「改造後影片（Col 5）」的鏡頭，呼叫 FFmpeg 濾鏡：
  ```text
  [0:v]scale=640:720:force_original_aspect_ratio=decrease,pad=640:720:(ow-iw)/2:(oh-ih)/2[left];
  [1:v]scale=640:720:force_original_aspect_ratio=decrease,pad=640:720:(ow-iw)/2:(oh-ih)/2[right];
  [left][right]hstack=inputs=2[v]
  ```
- 自動合成 `1280x720` 的左右同步對比影片，寫回表格第 6 欄 `Viral Comparison MP4`。

---

## 5. 參賽專版專案範本設計（`project_docs/templates.py`）

新增 `template == "open_higgsfield"`（並可設為參賽展示預設範本），包含以下 4 個核心分頁：

1. **`director-brief`（`doc`）：Director's Panel & Shot Script**
   - 集中定義全片風格（Genre: Sci-Fi Thriller）、光學套件（Optical Package: ARRI Alexa 65 + Master Anamorphic）、剪輯節奏（Montage Pacing）與分場劇本。
2. **`soul-cast`（`sheet`）：Soul Cast & Asset Lookbook（FLUX 3 Klein）**
   - 欄位：`Asset ID` | `Role / Scene` | `Optical & Appearance Prompt (Seed Locked)` | `FLUX 3 Klein Turnaround` | `Voice / Audio Stem` | `Status` | `Notes`
3. **`cinema-studio`（`sheet`）：Cinema Studio Multi-Shot Sheet（LTX-2.5 I2V）**
   - 欄位：`Shot` | `Optical Rig (Camera & Lens)` | `Camera Motion` | `Scene Action & Audio Prompt` | `Keyframe (FLUX 3)` | `LTX-2.5 Cinema Video` | `Status` | `Director Take Notes`
4. **`openjutsu-lab`（`sheet`）：OpenJutsu V2V Remaster Matrix（LTX-2.5 V2V）**
   - 欄位：`Clip ID` | `Jutsu Mode (Motion Transfer / Object Swap)` | `Source Driving Video` | `Target Cast / Style Prompt` | `LTX-2.5 Remastered Video` | `Viral Split-Screen MP4` | `Status` | `Notes`
5. **`comfy-pipeline`（`flow`）：Comfy Developer Platform DAG Pipeline**
   - 節點 1：`Optical Script Compiler (LLM)` ➔ 自動拆鏡並注入光學鏡頭參數。
   - 節點 2：`Soul Cast & Keyframe Gen (FLUX 3 Image Klein)` ➔ 批次產出鎖定角色一致性的首幀圖。
   - 節點 3：`Cinema Studio Multi-Shot (LTX-2.5 I2V)` ➔ 結合首幀、運鏡與原生音訊生成電影鏡頭（可設定 Multi-Take 跑 3 個候選版本）。
   - 節點 4：`OpenJutsu V2V Remaster (LTX-2.5 V2V)` ➔ 讀取 `openjutsu-lab` 的原片，批次執行動作轉移與物件替換。
   - 節點 5：`Director's Cut & Viral Grid Assembler (FFmpeg)` ➔ 一鍵合成完整短片＋左右對比展示片。

---

## 6. 12 天奪獎衝刺執行計畫（2026-10-18 ～ 2026-10-30）

| 階段 | 日期 | 具體交付項目（Deliverables） | 驗收標準 |
| :--- | :--- | :--- | :--- |
| **Phase 1：卡位與後端擴充** | 10/18 – 10/20 | 1. 填寫官方 Typeform 報名表領取免費 Credits<br>2. 完成 [`project_docs/templates.py`](file:///C:/ai_project/OpenBench/project_docs/templates.py) 的 `open_higgsfield` 範本<br>3. 完成 [`limb_worker.py`](file:///C:/ai_project/OpenBench/project_assistant/limb_worker.py) 的 `video_node` 上傳、`param_bindings` 與 `ffmpeg` 左右對比合成 | `python -m unittest discover -s tests -v` 全數通過，支援上傳影片至 mock ComfyUI 並合成對比片 |
| **Phase 2：開源權重 Workflow 固化** | 10/21 – 10/23 | 建立 `workflows/` 目錄並完成 3 個 100% Open-Weights API JSON：<br>- `flux3_klein_keyframe.json`<br>- `ltx25_cinema_shot.json`<br>- `ltx25_openjutsu_v2v.json` | 不含任何閉源 Partner Node，確保同時符合 **Open Weights Only (RTX 5090)** 與 **LTX VFX (\$2,000)** |
| **Phase 3：前端導演光學面板與多 Take** | 10/24 – 10/26 | 在 `ui/src/` 加入 **Optical Rig / Camera Motion 快速選單**，並讓影片欄支援切換預覽不同版本（Multi-Take A/B/C） | 瀏覽器打開 `http://127.0.0.1:3020/projects/` 點擊分鏡表可直接選取鏡頭焦段與運鏡，並播放對比影片 |
| **Phase 4：預載範例與 120 秒 Demo 錄製** | 10/27 – 10/29 | 1. 跑出 1 支 4 鏡頭科幻短片（Cinema Studio）+ 3 組實拍改造對比片（OpenJutsu）預載進 Demo 專案<br>2. 撰寫英文版 `README_CHALLENGE.md`<br>3. 錄製 120 秒 Demo 影片並於 10/30 前提交 | 評審 clone 下來 3 行指令即可打開看到完整分鏡表、DAG 與預載成片，且可隨時接上自己的 ComfyUI 重跑任意鏡頭 |
