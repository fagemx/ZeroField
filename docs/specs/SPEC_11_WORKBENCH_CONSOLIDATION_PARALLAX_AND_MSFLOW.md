# SPEC 11 — 工作台收斂、2.5D 視差舞台（Parallax Stage）與 Direct XYZ 動作控制（MSFlow）

> **狀態**：Ready for Execution（可拆分為平行 Worker Bundles 或單一代理依序執行）
> **目標**：
> 1. **收斂過多工作台入口（Workbench Consolidation）**：將 `SPEC_01`～`SPEC_10` 累積的多排導覽列與重複工具列收斂為「**Story & Cast → 2.5D/3D Stage（雙視窗） → Shot Review**」三段式創作主動線，次要工程工具收進 `<details>` 引擎選單，且 **100% 保持既有 SSR 與單元測試相容**。
> 2. **2.5D 視差景深舞台與 Billboard 防變形（借鏡 [80.lv Guillaume Scoffié 2.5D Parallax](https://80.lv/articles/inside-the-making-of-2-5d-parallax-animation-for-music-artist)）**：解決 `SPEC_10 §7.9` 發現的三大問題（場景寫死只有圓頂天文台、固定發光信標干擾特寫、以及 `@SET` 整張參考圖讓 Klein 照抄廣角構圖）。支援把任意 2D `@SET` 拆為前/中/後 Z 軸景深層放進 3D 攝影機空間，並提供 **Billboard 朝向鎖定**與**「俯視走位 + 鏡頭實景」雙視窗（Dual Viewport）**。
> 3. **Direct XYZ 動作空間與零樣本關節釘點控制（借鏡 [LY Corp MSFlow, CC0 1.0](https://github.com/yu1ut/MSFlow)）**：擺脫 `plan.js` 僅能靠人工硬寫弧度（`POSES`）的限制，在直接動作空間（Direct Motion Space, 22-joint XYZ）支援**空間關節釘點（Spatial Joint Pinning：`[{at, joint, pos}]`）**與雙骨解析 IK 轉向，同時補齊 `SPEC_10 §7.7` 背面抬頭/低頭的骨架方向線索。
> 4. **單一時鐘純函數互動展示窗（借鏡 [fil.design/skills/html-demo](https://fil.design/skills/html-demo)，獨立選配模組）**：固定 `1200 × 750` 舞台、單一 `t` 純函數驅動，供評審在無 GPU / 無 DB 環境一秒看懂完整流程。

---

## 0. 最高防呆鐵律（執行代理必讀）

1. **既有測試零破壞（Zero Regression on Existing Suites）**：
   - `ui/tests/story-ui.test.mjs` 會對 `StoryWorkbench` 跑 `renderToStaticMarkup`，斷言 HTML 字串內包含 `'Start Creating'`, `'My Projects'`, `'Asset Vault'`, `'Toolbox'`, `'Open API'` 且 `<button disabled="">...Start Creating` 存在。收斂頂部導覽列時，**必須使用原生 `<details className="story-engine-menu">` 收納 `Toolbox`、`Open API` 與 `Agent Console`**，不可將按鈕從初始 SSR DOM 移除！
   - `ui/tests/studio-ui.test.mjs` 會以正規表示式檢查 `ui/src/SheetWorkspace.jsx` 與 `ui/src/ShotBench.jsx` 的原始碼字串（包含 `previewAssets=previewRow?assetReferences(previewRow)`、`<ShotBench stages={rowMediaCols} assets={previewAssets}`、`if(!previewTargetValid||!guardDraft())return`、`const closePanel=()=>{if(!guardDraft())return` 等）。修改 `SheetWorkspace.jsx` 時，**嚴禁改動這些受測變數名與單行守衛寫法**。
   - `ui/tests/previs.test.mjs` 驗證 `defaultPlan()` 的預設值（`set: 'observatory', move: 'pushin', lens: 35, action: 'turnreach', facing: 'console', mood: 'grey', seconds: 4, keys: null`）以及 `planFromSlate()` 的深相等（`assert.deepEqual(planFromSlate(), {...defaultPlan(), action: 'stand'})`）。**新增的 plan 欄位（如 `layers`、`beacon`、`pins`、`xyz`）必須為選填（optional，未設定時不出現在 `defaultPlan()` 回傳物件的 keys 中）**，以免破壞 `assert.deepEqual`！
2. **雙語字典同步（Bilingual i18n）**：
   - 所有新增 UI 字串必須同時寫入 `ui/src/i18n/locales/en.json` 與 `ui/src/i18n/locales/zh-TW.json`，並跑過 `ui/tests/i18n.test.mjs`。
3. **前端編譯鐵律**：
   - 修改 `ui/src/` 後必須執行 `npm run build --prefix ui`，確保 `static/projects/` 同步更新。

---

## 1. 分工架構與檔案邊界（Worker Bundles）

本規格拆分為 **3 個核心實作包（Bundle A / B / C）＋ 1 個選配展示包（Bundle D）**，檔案邊界清楚，可由單一代理依序完成，或由 Controller 分派平行施工（Bundle B 與 Bundle C 共用 `ui/src/previs/`，若平行施工應由同一 Previs Worker 負責 B+C，UI Worker 負責 A）：

| Bundle | 名稱 | 負責檔案 | 依賴關係 |
| :--- | :--- | :--- | :--- |
| **Bundle A** | **工作台收斂與雙視窗導演舞台 UI** | `ui/src/StoryWorkbenchModals.jsx`, `ui/src/SheetWorkspace.jsx`, `ui/src/previs/PrevisStage.jsx`, `ui/src/story-workbench.css`, `ui/src/studio.css`, `ui/src/i18n/locales/en.json`, `ui/src/i18n/locales/zh-TW.json` | 可獨立先行 |
| **Bundle B** | **2.5D 視差景深佈景與 Billboard 引擎（80.lv）** | `ui/src/previs/plan.js`, `ui/src/previs/scene.js`, `ui/src/studioModel.js`, `ui/tests/previs.test.mjs` | 與 Bundle C 同屬 `previs/` |
| **Bundle C** | **Direct XYZ 動作空間、空間釘點與骨架方向強化（MSFlow）** | `ui/src/previs/plan.js`, `ui/src/previs/scene.js`, `ui/src/previs/skeleton.js`, `project_assistant/limb_worker.py`（選配 CLI 橋接）, `ui/tests/previs.test.mjs` | 與 Bundle B 同屬 `previs/` |
| **Bundle D** | **單一時鐘 HTML Live Demo 櫥窗（fil.design，選配）** | `ui/src/showcase/StepWindow.jsx`, `ui/src/showcase/step-window.css`, `ui/tests/stepWindow.test.mjs` | 完全獨立，不碰現有檔案 |

---

## 2. Bundle A 詳細規格：工作台收斂與雙視窗導演舞台 UI

### 2.1 收斂頂部 `StoryWorkbench` 導覽列（`ui/src/StoryWorkbenchModals.jsx`）

**現況問題**：頂部同時攤開 6 個按鈕（`Start Creating`, `My Projects`, `Asset Vault`, `Toolbox`, `Open API`, `Agent Console`），加上下方的 `story-macro`、表格工具列、`StoryBatchBar`，視覺噪音極高。

**實作規格**：
1. 在 `StoryWorkbench` 的 `<nav className="story-nav">` 中，將主創作入口維持在第一層：
   - `Start Creating`（`<button disabled={!writable || action.busy} onClick={() => open('import')}><Icon name="sparkle" />{t('story.startCreating')}</button>` — **保持原結構以通過 `story-ui.test.mjs` 正則**）
   - `My Projects`（主工作台切換）
   - `Asset Vault`（角色 `@CAST` 與場景 `@SET` 資產庫）
   - Episode 下拉選單
2. 將工程與進階工具收進同一個原生 `<details className="story-engine-menu">` 下拉選單：
   ```jsx
   <details className="story-engine-menu">
     <summary><Icon name="toolbox" />{t('story.studioEngine')}</summary>
     <div className="story-engine-dropdown">
       <button onClick={() => open('toolbox')}><Icon name="toolbox" />{t('story.toolbox')}</button>
       <button onClick={() => open('api')}><Icon name="code" />{t('story.openApi')}</button>
       <button onClick={onConsole}><Icon name="terminal" />{t('console.entry')}</button>
     </div>
   </details>
   ```
   - **驗證點**：`renderToStaticMarkup` 依然輸出 `Toolbox` 與 `Open API` 按鈕文字，舊測試 100% 通過；但畫面上頂部減少 3 個常駐按鈕。

### 2.2 收斂 `SheetWorkspace` 視圖切換與批次列（`ui/src/SheetWorkspace.jsx`）

**現況問題**：`StoryBatchBar` 在沒有勾選任何列時也佔據一整排；視圖切換把 5 個模式平鋪。

**實作規格**：
1. **主視圖切換（Primary vs. Secondary Views）**：
   - 主按鈕保留三段式核心視圖：`Table`（`grid`）、`3D Stage`（`stage`，當 `hasStage` 為真）、`Gallery`（`gallery`）。
   - `Canvas`（ReactFlow 節點牆）與 `Board`（Kanban）維持在同一個 `.sheet-view-switch` 群組內，但加上 `className="quiet-view"` 緊湊樣式，讓視覺焦點集中在 `Table / 3D Stage / Gallery`。
2. **`StoryBatchBar` 智慧摺疊**：
   - 當 `rowIds.length === 0`（尚未勾選任何分鏡列）時，`StoryBatchBar` 以緊湊單行顯示（或將進階 `appCode` 選擇器收在展開區），勾選列後才展開完整批次操作，消除未選取時的雙排工具列壓迫感。

### 2.3 `PrevisStage` 新增「俯視走位 + 鏡頭實景」雙視窗模式（`ui/src/previs/PrevisStage.jsx`）

**依據**：`80.lv` 2.5D 動畫工作流（上方 After Effects 3D 走位與景深層視圖、下方最終攝影機渲染視圖）與 `SPEC_09 §3`。

**實作規格**：
1. 更新 `VIEWS` 常數：
   ```js
   export const VIEWS = ['split', 'lens', 'overhead', 'free'];
   ```
   - 預設視角可保持 `'lens'` 或切換為 `'split'`（Dual Viewport）。
2. 當 `view === 'split'` 時，使用同一個 `THREE.WebGLRenderer` 的 `setViewport` 與 `setScissor`（避免建立兩個 WebGL context 浪費顯存）：
   - **左半部（或上半部）**：繪製 `top`（Orthographic 俯視攝影機 + `shotGuides` 攝影機椎體、180 度線、演員站位與 2.5D 景深層位置），支援直接拖曳滑鼠平移/縮放俯視圖。
   - **右半部（或下半部）**：繪製 `stage.camera`（當前鏡頭焦段 `24/35/50/85mm` 的實景透視畫面）。
   - **注意**：呼叫 `encodeCanvas` 渲染輸出 WebM（`Previs`、`Actor Matte`、`Pose Skeleton`）時，必須暫時關閉 `setScissorTest(false)` 並恢復全畫布 `setViewport(0, 0, WIDTH, HEIGHT)` 只渲染 `stage.camera`，確保輸出的 WebM 永遠是乾淨的 `1280 × 704` 單一鏡頭畫面！

---

## 3. Bundle B 詳細規格：2.5D 視差景深佈景與 Billboard 引擎（80.lv 作法）

### 3.1 解決的三大實戰痛點（見 `SPEC_10 §7.9`）
1. **消除寫死的天文台太陽信標**：`scene.js` 原本無條件加上 `beacon`（`(-2, 3, 28)` 發光球體），導致特寫悲傷鏡頭（如 `tears`）右上角永遠有一顆刺眼太陽。
2. **免建 3D 模型即可換景（2.5D Parallax Layers）**：任何劇本場次的 `@SET` 圖片都能直接掛進 Z 軸空間（遠景 `far`、中景 `mid`、近景 `near`），攝影機推拉搖移時自動產生真實視差（Parallax）。
3. **Billboard 永遠面向視點防變形**：當攝影機做大角度 `orbit` 或 `crane` 時，開啟 `billboard: true` 的景深層或道具卡會自動面向攝影機，不會出現紙片側邊穿幫或透視拉伸變形。

### 3.2 `ui/src/previs/plan.js` 資料契約擴充

1. **新增常數與純函數（保持 `defaultPlan()` 原有 keys 不變！）**：
   ```js
   export const SETS = ['observatory', 'parallax', 'empty'];
   // 2.5D 預設三層 Z 軸深度（相對於演員原點 (0,0,0)，+z 為背景方向、-z 為前景方向）
   export const PARALLAX_DEFAULTS = [
     { id: 'far',  role: 'far',  z: 4.8,  y: 1.8, scale: 1.0,  billboard: true,  opacity: 1.0 },
     { id: 'mid',  role: 'mid',  z: 2.2,  y: 1.5, scale: 0.85, billboard: true,  opacity: 1.0 },
     { id: 'near', role: 'near', z: -0.7, y: 1.1, scale: 0.55, billboard: true,  opacity: 0.9 },
   ];
   ```
2. **選填欄位規範（Optional Plan Fields）**：
   - `plan.beacon`：`boolean | undefined`。當 `plan.set === 'observatory'` 時，若 `plan.beacon === false` 則不加入發光信標球體；未指定（`undefined`）時預設顯示，維持舊測試相容。當 `plan.set === 'parallax'` 或 `'empty'` 時預設不顯示信標。
   - `plan.layers`：`Array<{ id: string, role?: 'far'|'mid'|'near', z?: number, x?: number, y?: number, scale?: number, billboard?: boolean, src?: string, color?: number }>`。
   - 新增 helper `parallaxLayers(plan)`：
     - 若 `plan.layers?.length` 存在，將每層與 `PARALLAX_DEFAULTS` 對應預設值合併並依 `z` 由遠到近排序。
     - 若 `plan.set === 'parallax'` 且未給 `plan.layers`，回傳 `PARALLAX_DEFAULTS` 的深拷貝。
   - 新增純函數 `billboardYaw(cameraPos, layerPos, mode = 'cylindrical')`：
     - 計算 2.5D 圖層面向攝影機的旋轉角度：
     - `'cylindrical'`（預設，水平旋轉防垂直傾倒）：`Math.atan2(cameraPos[0] - layerPos[0], cameraPos[2] - layerPos[2]) + Math.PI`（使圖層正面 `-z` 朝向攝影機）。
     - 在 Node 環境即可由 `ui/tests/previs.test.mjs` 直接做數學驗證（無需瀏覽器 DOM）。

### 3.3 `ui/src/previs/scene.js` 2.5D 舞台與 Billboard 實作

1. **新增 `parallaxStage(group, mats, plan)`**：
   - 建立乾淨的深色吸光地板（供陰影落點定位演員腳步）與 `parallaxLayers(plan)` 定義的 2.5D 平面（`THREE.PlaneGeometry`）。
   - 每個圖層平面尺寸依深度 `z` 與基準 35mm 視角（`verticalFov(35)`）自動換算視錐寬高（`frustumHeightAtZ = 2 * dist * Math.tan(fovRad / 2)`），乘上 `layer.scale`，確保在基準機位下遠景剛好填滿畫面，而推鏡（`pushin`）、橫移（`track`）、環繞（`orbit`）時遠中近三層產生真實的相對位移差（Parallax）！
   - 若 `layer.src` 有圖片 URL 且處於瀏覽器環境，以 `THREE.TextureLoader` 載入貼圖（設 `colorSpace = THREE.SRGBColorSpace`、`transparent = true`）；未載入或無圖片時，以帶景深層次感的灰階色塊（遠景較亮、中景中灰、近景深灰剪影框）繪製，讓 LTX-2.5 即使在無貼圖時也能讀到明確的 Z 軸深度結構。
   - 每個圖層 Mesh 標記 `mesh.userData.parallaxLayer = layer`。
2. **在 `pose(f, p = plan)` / `frame(f, p = plan)` 更新 Billboard 朝向**：
   - 走訪 `set.children` 中 `o.userData.parallaxLayer` 的平面：
   - 若 `layer.billboard !== false`，根據當前幀的 `sampleCamera(p, f).position` 呼叫 `billboardYaw` 更新該圖層的 `rotation.y`（若 `layer.billboard === 'full'` 則呼叫 `o.lookAt(camera.position)`）。
   - **關鍵效果**：如同 `80.lv` 文章所述，當鏡頭做 360° `orbit` 或大幅度 `track` 時，背景與中景圖層永遠正對鏡頭視線，不會因為斜角觀看 2D 平面而產生紙片穿幫或壓扁變形。
3. **`stage.matte(on)` 遮罩相容**：
   - `set.visible = !on` 本就會隱藏整個 `set` 群組（含 2.5D 圖層），確保 `Actor Matte` 算圖時背景為純黑、只有演員為純白。

### 3.4 `ui/src/studioModel.js` 自動帶入該鏡的 `@SET` 資產

- 在 `stageShots(parsed, rows, assetLookup)` 中：
  - 若傳入 `assetLookup`（或從該列文字解析出 `@SET-xx` 引用），將找到的 `@SET` 圖片 URL 附在 `shot.setAsset`（例如 `{ id: 'SET-01', url: '...' }`），讓 `PrevisStage` 切換到 `set: 'parallax'` 時，一鍵自動把該鏡的 `@SET` 圖片掛載到遠景層（`far`）。

---

## 4. Bundle C 詳細規格：Direct XYZ 動作空間與空間釘點控制（MSFlow 作法）

### 4.1 為什麼需要這一層？
`SPEC_10` 目前的 `POSES` 只有 11 個手寫弧度姿勢，且動作只有固定路徑。而 `YU1ut/MSFlow`（*MotionSpaceFlow: Representation-Aware Flow Matching in Direct Motion Space*）證明了：**直接在 22 關節的全局 XYZ 空間（Direct Motion Space）操作，不經過壓縮的 Latent VAE，才能在推論時對「任意幀、任意關節」做精準的空間座標約束（Training-Free Spatial Control / Projection Sampling）**。

我們將這套能力分成兩層落地：
1. **前端純函數層（`plan.js` + `scene.js` + `skeleton.js`，零 GPU 依賴、立即可跑）**：
   - 定義標準 22 關節 XYZ 動作軌跡格式（`plan.xyz`）與**空間關節釘點（`plan.pins`）**。
   - 實作 Direct Motion Space 的**高斯時間核空間投影求解器（`solvePinnedXYZ`）**與**雙骨解析 IK 轉向器（`retargetXYZToRig`）**。導演只要在 3D 舞台上給定釘點（例如：`{ at: 0.5, joint: 'wristL', pos: [-0.25, 1.03, 0.56] }` 要求第 50% 時刻左手精準摸到控制台轉盤，或 `{ at: 1.0, joint: 'pelvis', pos: [0.4, 0.58, -0.8] }` 要求結尾跪在指定座標），求解器就會在直接 XYZ 空間平滑變形整條動作曲線並精確滿足約束（誤差 `< 1e-6 m`）！
2. **後端 4090 Worker 橋接層（`project_assistant/limb_worker.py`，選配掛載）**：
   - 當本機安裝了 `MSFlow`（設定環境變數 `MSFLOW_ROOT` 與 `MMDiT_xyz_pretrained` 權重）時，Worker 可將分鏡的英文動作描述 + `plan.pins` 轉成 `MSFlow` 的 joint-control 採樣輸入，算完的 `[T, 22, 3]` XYZ 序列直接寫入 `plan.xyz`。

### 4.2 標準 22 關節 Direct XYZ 格式與空間釘點（`ui/src/previs/plan.js`）

1. **22 關節定義（對齊 HumanML3D / SMPL 22 joints 與現有 `figure.js` 關節）**：
   ```js
   export const MSFLOW_JOINTS = [
     'pelvis', 'hipL', 'hipR', 'spine1', 'kneeL', 'kneeR', 'spine2', 'ankleL', 'ankleR',
     'spine3', 'footL', 'footR', 'neck', 'collarL', 'collarR', 'head',
     'shoulderL', 'shoulderR', 'elbowL', 'elbowR', 'wristL', 'wristR'
   ];
   ```
2. **空間釘點（Spatial Joint Pins）資料結構**：
   ```js
   // plan.pins: 推論時／預演時的零樣本空間約束（Any-joint, any-frame spatial control）
   // at: 0..1（時間比例）, joint: MSFLOW_JOINTS 名稱, pos: [x, y, z] 舞台公尺座標, radius?: 影響時間半寬（預設 0.22）
   ```
   - 範例：
     ```js
     pins: [
       { at: 0,    joint: 'pelvis', pos: [0, 0.98, -1.8] },
       { at: 0.45, joint: 'wristL', pos: [-0.25, 1.03, 0.56] }, // 精準觸碰控制台轉盤
       { at: 0.85, joint: 'head',   pos: [0, 1.65, -0.15] }     // 受驚後仰退縮
     ]
     ```
3. **Direct Motion Space 投影求解器 `solvePinnedXYZ(baseFrames, pins)`**：
   - 輸入：`baseFrames`（長度 `F` 的陣列，每格為 `{ pelvis: [x,y,z], wristL: [x,y,z], ... }`，可由現有 `sampleActor` 正向運動學展開或由外部 `MSFlow` 模型載入）與 `pins`。
   - 演算法（對應 MSFlow 的 Inference-Time Projection Sampling 約束滿足）：
     - 對每個 `pin`（時間點 $u_p = \text{pin.at}$、目標關節 $j$、目標位置 $\mathbf{p}^*$）：
     - 在釘點格 $f_p = \text{round}(u_p \cdot (F - 1))$ 計算殘差 $\Delta \mathbf{p} = \mathbf{p}^* - \mathbf{x}_{f_p, j}$。
     - 以平滑時間核 $w(u) = \exp\left(-\frac{(u - u_p)^2}{2\sigma^2}\right)$（在 $u = u_p$ 處 $w = 1$）將位移場施加至目標關節及其運動鏈（若釘的是 `pelvis`，全身關節同步平移；若釘的是末端 `wristL`/`wristR`/`ankleL`/`ankleR` 且超出臂長/腿長，自動按比例帶動 `pelvis` 與 `spine` 前傾靠近目標）。
     - 若同一關節有多個時間釘點，使用精確插值權重確保每一個釘點格 $f_p$ 的最終座標**精確等於** $\mathbf{p}^*$（誤差 $< 10^{-6}\text{ m}$）。
4. **雙骨解析 IK（Two-Bone Analytical IK）轉回假人關節 `solveLimbIK(rootPos, midPos, endTarget, len1, len2)`**：
   - 當 `wristL` / `wristR` / `ankleL` / `ankleR` 被空間釘點或 `plan.xyz` 驅動時，利用餘弦定理算出肩/肘（或髖/膝）的彎曲角度與旋轉，寫回 `figure.joints`，確保假人手肘自然彎曲、不會脫臼或穿模。

### 4.3 補齊 `SPEC_10 §7.7` 骨架背面頭部方向線索（`ui/src/previs/skeleton.js`）

**現況問題（見 `SPEC_10 §7.7` 結論 3）**：
> 「骨架從背後看只帶得到耳朵，頭的方向訊息很弱：預演頭往後仰，成片只轉向側面。要補頭部方向（例如背面時仍畫出頭頂到頸的方向）。」

**實作規格**：
1. 在 `skeleton.js` 的 `HEAD` 常數新增頭頂點 `crown: V(0, 0.22, 0.01)`。
2. 在 `poseKeypoints(scene, camera)` 中，為每位演員多計算一個方向點 `crown: px(at(head, HEAD.crown))`（只要頭部在畫面內即標為可見 `v = 1`，不受 `face > 0.05` 背面隱藏限制）。
3. 在 `drawSkeleton(ctx, people, w, h, face)` 中：
   - 當演員背對鏡頭（`nose` 不可見 `!b[0][2]`，但頸部 `b[1][2]` 與 `p.crown?.[2]` 可見）時，畫出一條由 `neck`（`b[1]`）連往 `p.crown` 的頭部中軸肢段（使用 DWPose 頭頸色系 `COLORS[12]`），並在兩耳（`earR` / `earL`）連向 `p.crown`。
   - **關鍵效果**：當演員背對鏡頭做「抬頭仰望信標（`lookup`）」、「低頭崩潰（`slump`）」或「驚嚇後仰（`recoil`）」時，`crown` 相對於 `neck` 與兩耳的高低位移會直接在黑底骨架圖上形成清楚的俯仰幾何三角形，LTX-2.3 Union-Control 從背後也能精確讀出抬頭與低頭！
   - **相容性守衛**：`person.body` 維持原本的 18 個點（`assert.equal(person.body.length, 18)`），`crown` 放在 `person.crown` 屬性上，100% 不影響既有 `previs.test.mjs` 對 `person.body` 的解構斷言！

### 4.4 後端 `MSFlow` 動作生成橋接器（`project_assistant/limb_worker.py`）

- 新增純函數 `build_msflow_command(prompt, pins=None, seconds=4, msflow_root=None)`：
  - 若環境變數 `MSFLOW_ROOT`（或傳入參數）指向本機 `MSFlow` 目錄，組裝 `uv run python -m sample.demo_msflow_xyz name=MMDiT_xyz_pretrained` 指令與空間釘點參數。
  - 若本機未安裝 `MSFlow` 權重，回傳 `{ "mode": "builtin_xyz_solver", "frames": seconds * 24 + 1 }`，由內建 Direct XYZ 求解器產生平滑的 22 關節軌跡，確保在任何機器上都不會報錯中斷。

---

## 5. Bundle D 詳細規格（選配）：單一時鐘 HTML Live Demo 櫥窗（`fil.design/skills/html-demo` 作法）

若需要一個**免啟動 ComfyUI、免連資料庫即可在瀏覽器／GitHub Pages／評審簡報展示 ZeroField 核心價值**的互動視窗：

- **檔案**：`ui/src/showcase/StepWindow.jsx`, `ui/src/showcase/step-window.css`, `ui/tests/stepWindow.test.mjs`
- **核心契約（對齊 `fil.design/skills/html-demo`）**：
  1. **單一時鐘純函數 `View({ t, dur })`**：每個步驟畫面完全由秒數 `t` 決定，支援任意拖曳時間軸（scrub）、點擊底部步驟條跳轉、以及 `prefers-reduced-motion: reduce` 自動定格於 `t = dur` 完成幀。
  2. **固定舞台 `1200 × 750`（16:10）+ 單一 CSS Scale `--k = clientWidth / 1200`**：內部元素與擬人化游標（`<Cursor />`）座標永遠精準對齊，在手機或窄視窗下絕不跑位。
  3. **內建 3 步展示腳本（`ZEROFIELD_DEMO_STEPS`，總長 18 秒）**：
     - **Step 1 — `Script & @SET Layers`（5.5s）**：展示從劇本場次自動綁定 `@CAST-01` 與 `@SET-01` 2.5D 遠中近景深層。
     - **Step 2 — `2.5D Parallax + XYZ Stage`（6.5s）**：展示雙視窗舞台（左俯視圖拖曳機位與 `wristL` 空間釘點、右鏡頭視窗即時呈現 2.5D 視差與背面抬頭骨架）。
     - **Step 3 — `LTX-2.5 Render & Review`（6.0s）**：展示骨架與視差預演送入 LTX-2.5 產出最終電影鏡頭、顯示 Camera Fidelity `0.97` 與 Continuity Grade `89/100` 並一鍵 Approve。

---

## 6. 驗收標準與測試清單（Acceptance Criteria）

執行代理完成後，必須依序跑過以下驗證並確保 **0 failures / 0 skips**：

1. **單元測試與整合測試**：
   - `node --test ui/tests/previs.test.mjs`（含既有測試 + 新增：
     - `parallaxLayers` 與 `billboardYaw` 驗證 2.5D 圖層隨攝影機 `orbit` / `track` 永遠面向鏡頭；
     - `plan.beacon === false` 時天文台不產生發光球體；
     - `solvePinnedXYZ` 驗證任意關節在任意時間點的空間釘點誤差 `< 1e-6 m` 且帶動雙骨 IK；
     - `poseKeypoints` 驗證背面時 `person.crown` 隨 `lookup` / `slump` 改變螢幕 Y 座標，且 `person.body.length === 18` 不變。）
   - `node --test ui/tests/story-ui.test.mjs ui/tests/studio-ui.test.mjs ui/tests/i18n.test.mjs`（確保工作台收斂與雙語字典 100% 通過既有斷言）
   - 若實作 Bundle D：`node --test ui/tests/stepWindow.test.mjs`（驗證相同 `(step, t)` 輸出完全相同的 DOM markup，且 `still: true` 直接定格在 `t = dur`）
2. **前端正式環境編譯**：
   - `npm run build --prefix ui` 零錯誤完成，更新 `static/projects/`。
3. **後端測試（若有修改 `limb_worker.py`）**：
   - `pytest tests/test_studio_worker.py` 全部通過。
