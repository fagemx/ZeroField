# SPEC 12 — 瀏覽器內動作技能編譯器、物理防穿模/防滑步 QA 與工作台控制項預算（借鏡 CozyClay）

> **狀態**：Ready for Execution（建構於 `c4a7e8e` / `SPEC_11` 已完工基底之上）
> **核心原則**：**絕不新增工作台**，100% 直接強化現有的 `PrevisStage`、`SheetWorkspace` 與 `StoryWorkbench`。
> **版權合規鐵律（Clean-Room Implementation）**：`NomaDamas/CozyClay` 為 AGPL-3.0 授權。執行代理**嚴禁複製貼上任何 CozyClay 原始碼**；必須僅依據本規格書定義的數學公式與資料契約，在 ZeroField 既有 `ui/src/previs/` 與 `ui/src/` 內以原創程式碼實作。

---

## 0. 背景與解決的具體問題

`SPEC_11`（`c4a7e8e`）已完成頂部 `Studio Engine` 收納、雙視窗 `split` 模式、2.5D `@SET` 視差背景與 `MSFlow` Direct-XYZ 空間釘點（`solvePinnedXYZ`）。
然而比對 **[CozyClay](https://github.com/NomaDamas/CozyClay)** 的兩份核心實戰文檔（`docs/motion3-agent-guide.md` 與 `docs/studio-ui-ia.md`），我們現有工作台還有 **3 個關鍵斷點**可立即升級：

1. **假人動作缺乏「防滑步 / 防穿地 / 防穿控制台」物理修正與即時 QA**：
   - 目前 `plan.js` 與 `scene.js` 雖然支援 `plan.pins` 與 `plan.acts`，但：
     - 當姿勢（如 `kneel`、`slump`）或釘點壓低身體時，腳踝/腳掌會穿入地板（`y < 0`）；
     - 當演員做 `turnreach` 轉身時，支撐腳沒有鎖定地面支點（Planted-foot pivot），產生「太空漫步滑步（Foot slide）」；
     - 當手部伸向控制台（`reach`）時，手腕或前臂可能直接穿進控制台方塊（Obstacle penetration）；
     - 導演或 M8 Agent 在送出 4090 GPU 算圖前，沒有一個 **毫秒級的動作 QA 報告（`cause` + `hint`）** 告訴他哪一幀穿模、哪一隻手差幾公分沒摸到道具。
2. **缺乏可串接的高階動作技能（Composable Skills `plan.use`）與參數區間自動搜尋（`{ range: [lo, hi] }`）**：
   - 導演在排戲時希望能直接組合 `{ skill: 'standIdle' } → { skill: 'walkTo', args: { to: [x, z] } } → { skill: 'reachGrip', args: { anchor: 'dial' } }`，並讓編譯器自動把模糊參數（如 `{ range: [0.2, 1.2] }`）搜尋到 0 穿模、0 滑步的最佳解。
3. **3D 舞台自由飛（`free` / `overhead`）時的 PiP 子母鏡頭窗與控制項閘門（UI IA R1–R6）**：
   - 在 `PrevisStage` 切到 `free` 或 `overhead` 視角時，目前看不到實際鏡頭框出的構圖（除非切去 `split` 把畫面砍半）；採用 CozyClay 的 **右下角 PiP 鏡頭子母窗 + `Look through` 一鍵切換**，可在全螢幕排走位時同時監看鏡頭構圖。
   - 右側 Inspector 中，`setStart` / `setEnd` / `resetPath` / `discard` 在非 `free` 模式或無修改時應依 **R2（選取/模式閘門）與 R3（消滅無故 Disabled 按鈕）** 按需渲染或給出明確原因，並以自動化測試鎖定畫面控制項預算（Control Budget）。

---

## 1. 檔案邊界與防呆鐵律

### 1.1 負責檔案清單
- `ui/src/previs/plan.js`（新增場景錨點 `SCENE_ANCHORS`、高階動作技能展開器 `compileMotionSkills`、物理自動修正 `applyMotionFixes`、動作 QA 檢查器 `auditMotion`、區間搜尋 `searchMotionPlan`）
- `ui/src/previs/scene.js`（將 `solvePinnedXYZ` 與 `applyMotionFixes`、`auditMotion` 串入 `stage.motion(plan)`）
- `ui/src/previs/PrevisStage.jsx`（新增右下角 PiP 子母鏡頭窗與 `Look through` 切換、Inspector 動作 QA 狀態列與一鍵 `Auto-Fix`、依 R2/R3 收斂 `framing` 按鈕、新增 `First + Last Keyframe Pack` 快速匯出）
- `ui/src/studio.css`, `ui/src/i18n/locales/en.json`, `ui/src/i18n/locales/zh-TW.json`
- `ui/tests/previs.test.mjs`, `ui/tests/uiBudget.test.mjs`（新增測試）

### 1.2 既有測試相容鐵律（Zero Regression）
1. **`defaultPlan()` 的屬性鍵（keys）不可改變**：
   - `ui/tests/previs.test.mjs` 第 77 行有 `assert.deepEqual(planFromSlate(), {...defaultPlan(), action: 'stand'})`。
   - 因此 `plan.use`、`plan.fix`、`plan.anchors` 必須與 `SPEC_11` 的 `plan.pins`、`plan.layers`、`plan.beacon` 一樣為 **選填（optional，未指定時不出現在 `defaultPlan()` 回傳物件中）**。
2. **既有 `solvePinnedXYZ(baseFrames, pins)` 簽名與精確度保持不變**：
   - `SPEC_11` 測試要求在 `fix` 未開啟或預設情況下，單純呼叫 `solvePinnedXYZ(base, pins)` 時，釘點格 `f_p` 的座標與 `pin.pos` 距離 `< 1e-6`。
   - 物理自動修正請封裝為獨立純函數 `applyMotionFixes(frames, fix, plan)`（或在 `solvePinnedXYZ(baseFrames, pins, opts)` 的第 3 個選填參數 `opts.fix` 中啟用），確保既有 `solvePinnedXYZ(base, pins)` 測試 100% 原樣通過！
3. **`ui/tests/story-ui.test.mjs` 與 `ui/tests/studio-ui.test.mjs` 不可破壞**。

---

## 2. Bundle A 詳細規格：動作技能編譯、物理自動修正（Auto-Fix）與 80ms 動作 QA（`ui/src/previs/plan.js` & `scene.js`）

### 2.1 場景互動錨點與障礙物碰撞盒（`SCENE_ANCHORS` & `SCENE_BOXES`）

在 `ui/src/previs/plan.js` 定義天文台與標準舞台的具名錨點與碰撞盒（公尺，舞台座標系：演員原點 `[0, 0, 0]`，控制台位於 `+z`）：

```js
export const SCENE_ANCHORS = {
  dial:         { pos: [-0.25, 1.03, 0.56], normal: [0, 0.7, -0.7] },  // 控制台左側黃銅轉盤
  recorder:     { pos: [0.25, 1.03, 0.56],  normal: [0, 0.7, -0.7] },  // 控制台右側類比錄音機
  console_edge: { pos: [0.0,  0.96, 0.52],  normal: [0, 0.5, -0.86] }, // 雙手撐住控制台前緣
  window_glass: { pos: [0.0,  1.45, 3.80],  normal: [0, 0, -1] },      // 遠方觀景窗方向
};

// 供 penetration 防穿模與 QA 檢查的軸對齊碰撞盒 (AABB: min [x,y,z], max [x,y,z])
export const SCENE_BOXES = {
  console: { id: 'console', min: [-0.90, 0.0, 0.58], max: [0.90, 0.98, 1.12] },
  plinth:  { id: 'plinth',  min: [-1.45, 0.0, 0.25], max: [1.45, 0.14, 1.35] },
};
```

### 2.2 高階動作技能展開器 `compileMotionSkills(plan)`

支援在 `plan.use` 中以陣列串接高階技能：
`plan.use = [{ skill: 'standIdle' | 'walkTo' | 'reachGrip' | 'turnLook' | 'kneelDown', f0?: number, frames?: number, args?: object }]`

- **`compileMotionSkills(plan)` 回傳 `{ acts, pins, checks }`**：
  1. **`standIdle`**（`args: { at?: [x, z], heading?: number, until?: number }`）：
     - 在 `f0..until` 設定站立姿勢與朝向。
  2. **`walkTo`**（`args: { from?: [x, z], to: [x, z], steps?: number, vary?: number }`）：
     - 自動產生由 `from`（或前一個技能結束位置）走向 `to` 的骨盆位移與左右腳交替抬步軌跡（起步加速、最後一步減速收腳至雙腳併攏，步幅與抬腳高度隨 `vary` 微調），並在腳掌著地期間自動產生 planted-foot 檢查區間。
  3. **`reachGrip`**（`args: { anchor: 'dial' | 'recorder' | 'console_edge' | [x,y,z], side?: 'L' | 'R', reach?: number, hold?: number, release?: number }`）：
     - 將 `wristL`（或 `wristR`）在 `f0 + reach` 時刻平滑釘至指定 `anchor` 座標（自動轉換為 `pins`），並在 `f0 + reach .. f0 + reach + hold` 期間鎖定接觸點，同時寫入 `checks.contacts`。
  4. **`kneelDown`**（`args: { duration?: number, face?: string }`）：
     - 平滑過渡至 `body: 'kneel'` 並附帶指定表情（如 `'cry'` 或 `'pain'`）。

### 2.3 三大物理自動修正器 `applyMotionFixes(frames, fix = {}, plan = {})`

輸入 `frames`（由 `solvePinnedXYZ` 產出的 `F` 格 22 關節 XYZ 陣列），根據 `fix` 設定（預設 `{ ground: true, slide: true, penetration: true, reach: true }`，`fix === false` 時全部停用）依序執行並回傳 `{ frames: fixedFrames, fixed: { ground, slide, penetration, retime } }`：

1. **防穿地板修正（`fix.ground !== false`）**：
   - 腳底厚度常數：`ANKLE_FLOOR_Y = 0.085`、`FOOT_FLOOR_Y = 0.035`、`KNEE_FLOOR_Y = 0.04`。
   - 若任一格 `f` 的 `ankleL[1] < ANKLE_FLOOR_Y` 或 `footL[1] < FOOT_FLOOR_Y`（右腳同理），計算需要上抬的差值 $\Delta y > 0$，將該側 `ankle` 與 `foot` 上抬 $\Delta y$，並重跑該腿的 `solveLimbIK` 使膝蓋自然微彎而不穿地；記錄修正格數至 `fixed.ground`。
2. **防太空漫步滑步修正（`fix.slide !== false`）**：
   - 偵測支撐腳落地段（Stance phase：當腳踝高度 `ankle[1] <= ANKLE_FLOOR_Y + 0.015` 且該格水平移動速率低於閾值 `0.025 m/frame`）。
   - 在同一段落地期間，若腳踝水平座標 `[x, z]` 發生微小漂移（`< 0.08 m`，例如轉身 `turnreach` 時上身旋轉帶動骨盆微移），將該腳踝與腳掌的 `[x, z]` **鎖死在落地首格的支點座標**，並以 `solveLimbIK` 更新膝蓋位置，徹底消除轉身滑步；記錄修正格數至 `fixed.slide`。
3. **防道具穿模修正（`fix.penetration !== false`）**：
   - 針對舞台碰撞盒（如 `plan.set !== 'empty'` 時的 `SCENE_BOXES.console`）：
   - 檢查每格的 `wristL`, `wristR`, `elbowL`, `elbowR`。若關節點落入 `console` AABB 內部（深度超過容許值 `0.005 m`），沿最近的表面法線方向（通常為上方 `+y` 或前方 `-z`）將該手腕推回表面外，並以 `solveLimbIK` 同步更新手肘位置；記錄修正格數至 `fixed.penetration`。
4. **速度突波平滑（`fix.retime === true`）**：
   - 若相鄰格關節位移速度超過物理極限（`0.28 m/frame`），對該突波鄰域（`±2` 格）做保持首尾端點的局部三次平滑，記錄至 `fixed.retime`。

### 2.4 80ms 動作 QA 檢查器 `auditMotion(frames, plan = {})`

純函數 `auditMotion(frames, plan)` 在瀏覽器或 Node 測試中毫秒級掃描整段 `[F, 22, 3]` 動作，回傳：

```js
{
  ok: boolean,        // groups.length === 0
  cost: number,       // 總違規權重分數（0 代表完全乾淨）
  groups: [
    {
      kind: 'GROUND' | 'SLIDE' | 'REACH' | 'PENETRATION' | 'SELF_CONTACT' | 'POP',
      subject: string,      // 例如 'footL', 'wristL', 'console'
      count: number,        // 違規總幀數
      first: number,        // 起始幀
      last: number,         // 結束幀
      worst: number,        // 最嚴重誤差值（公尺，四捨五入至 0.001）
      worstFrame: number,   // 最嚴重發生幀
      limit: number,        // 容許門檻
      cause: string,        // 具體原因（如 "pin wristL at f48" 或 "pose kneel at f72"）
      hint: string          // 可執行修正建議（如 "Enable fix.ground or raise pelvis +0.042m at f72"）
    }
  ]
}
```

- **六項必檢規則**：
  1. `GROUND`：`footL/R` 或 `ankleL/R` 低於地板超過 `0.005 m`。`hint`：`"Enable fix.ground or lift pelvis +X m at fN"`。
  2. `SLIDE`：支撐腳在著地期間水平漂移超過 `0.015 m`。`hint`：`"Enable fix.slide to lock planted foot at fN"`。
  3. `REACH`：`plan.pins` 指定的手/腳目標點在最終格與實際關節位置差距超過 `0.015 m`。`hint`：`"Move actor mark [dx, dz] m toward target or add spine lean at fN"`。
  4. `PENETRATION`（當 `plan.set !== 'empty'`）：手腕或手肘進入 `SCENE_BOXES.console` 內部超過 `0.01 m`。`hint`：`"Enable fix.penetration or move hand [0, +dy, -dz] m out of console at fN"`。
  5. `SELF_CONTACT`：左右手腕重疊距離 `< 0.06 m`（非雙手合握時）或手腕穿入頭/胸膠囊體內。
  6. `POP`：單格關節位移跳動 `> 0.28 m/frame`。

### 2.5 開放參數區間搜尋 `searchMotionPlan(plan, evaluateFn, budget = 24)`

當 `plan.pins` 或 `plan.use` 中的數值寫成 `{ range: [lo, hi] }`（例如演員站位 `mark: [0, { range: [-0.4, 0.4] }]` 或轉身時間點）時：
- `searchMotionPlan` 先測試中點 `(lo + hi) / 2`，再以 Halton / 等距網格與局部收縮搜尋在 `budget` 次評估內找出 `auditMotion` 的 `cost === 0`（或最低 `cost`）的具體數值，回傳 `{ plan: resolvedPlan, qa, evals, cost }`。

---

## 3. Bundle B 詳細規格：現有工作台 UI 減肥預算（R1–R6）、PiP `Look through` 子母鏡頭窗與 Keyframe Pack

### 3.1 `PrevisStage` 右下角 PiP 鏡頭子母窗 + `Look through` 切換（`ui/src/previs/PrevisStage.jsx`）

**依據**：CozyClay `docs/studio-ui-ia.md` §3 Viewport Bar（在編輯視角常駐 PiP 鏡頭預覽，點 `Look through` 進入鏡頭全畫面，按 `Esc` 返回）。

**實作規格**：
1. 當使用者處於 `view === 'free'` 或 `view === 'overhead'` 時，除了主畫面繪製自由視角／俯視圖外，預設在同一個 WebGL Canvas 的右下角（例如寬 `320`、高 `176`，距右下邊距 `16px`）使用 `renderer.setViewport` + `renderer.setScissor` 繪製 **PiP 實景鏡頭小窗（`stage.camera`，關閉屋頂與輔助線 `stage.roof(true); guides.group.visible = false`）**！
2. 在视窗右上角控制列提供：
   - **PiP 開關（`pip` 狀態，預設 `true`）** 與 **`Look through`（透過鏡頭觀看）按鈕**：
   - 在 `free` / `overhead` 點擊 `Look through` 時，記住原本視角（`returnView`）並切至 `lens` 全畫面預覽；在 `lens` 視角按鍵盤 `Esc`（或點 `Exit Look through`）即可一鍵跳回剛才的 `free` / `overhead` 視角繼續調機位！
   - **重要防呆**：呼叫 `render()` 輸出 WebM 或 Keyframe Pack 時，與 `split` 模式相同，必須強制 `setScissorTest(false)` 並重置 `setViewport(0, 0, WIDTH, HEIGHT)`，確保 PiP 框絕不會被錄進輸出的 WebM 影片內（遵守 `SPEC_09 R11` 與 CozyClay 乾淨灰模鐵律）。

### 3.2 `PrevisStage` Inspector 控制項閘門（CozyClay R1–R3）與動作 QA 面板

1. **R2/R3 條件閘門（消除無效 Disabled 按鈕噪音）**：
   - `framing` 欄位組（`setStart`、`setEnd`、`resetPath`、`discard`）：
     - 在非 `free` 視角且沒有自訂 `plan.keys` 也沒有 `drafts[shot.rid]` 時，不攤開一整排 4 個灰掉的 disabled 按鈕，而是顯示單顆引導按鈕 `Frame Custom Path (Free View)`（點擊直接切到 `view = 'free'` 開啟自由取景），一旦進入 `free` 視角或已有 `plan.keys` / `draft` 時才完整顯示 `setStart` / `setEnd` / `resetPath` / `discard`。
2. **即時動作 QA 狀態與一鍵 `Auto-Fix`（Motion QA Readout）**：
   - 在 `PrevisStage` 右側 Inspector 顯示當前鏡頭的 `auditMotion` 結果：
     - 若 `qa.ok` 為真：顯示綠色膠囊 `Motion QA: Clean (0 issues)`。
     - 若有違規（例如手穿進控制台或腳底穿地）：顯示違規摘要（如 `GROUND · footL (-0.04m at f48)` 與 `hint`），並提供一顆 **`Apply Auto-Fix`** 按鈕，點擊後將 `fix: { ground: true, slide: true, penetration: true }` 寫入該鏡 `plan` 並立即消除穿模與滑步！
3. **一鍵匯出 `Keyframe Pack`（首尾幀 PNG + 灰模描述 JSON）**：
   - 在 `PrevisStage` 新增 `Export Keyframe Pack` 動作（或整合於匯出選單）：一鍵抓取當前鏡頭在 `f = 0`（首幀）與 `f = frames - 1`（尾幀）的乾淨無輔助線 `1280×704` PNG 快照與運鏡描述，方便直接餵給首尾幀控制工作流。

### 3.3 自動化控制項預算測試（`ui/tests/uiBudget.test.mjs`）

比照 CozyClay 的 `tools/qa/studio-control-count.mjs`，新增 `ui/tests/uiBudget.test.mjs`：
1. 以 `renderToStaticMarkup` 渲染 `StoryWorkbench` 與 `PrevisStage`。
2. 計算初始可見（不含收納在未展開 `<details>` 內部）的互動控制項（`button`, `select`, `input`）數量，斷言：
   - `StoryWorkbench` 頂部常駐可見控制項 `<= 8`（`Toolbox`, `Open API`, `Agent Console` 均收納於 `<details class="story-engine-menu">` 內）。
   - 頂部常駐列中不存在重複功能的按鈕（R1：同一 `aria-label` 或文字不重複出現）。
   - `PrevisStage` 在預設 `lens` 視角且無未儲存草稿時，不渲染無效的 disabled `setStart` / `setEnd` 按鈕（R2/R3）。

---

## 4. 驗收標準與執行指令（Acceptance Criteria）

執行代理完成後，必須依序跑過以下指令並確保 **0 failures / 0 skips**：

1. **Previs 與動作 QA 單元測試**：
   ```bash
   node --test ui/tests/previs.test.mjs
   ```
   - 必測項目：
     - `applyMotionFixes`：當輸入動作的腳踝低於地面（`y = -0.05`）時，`fix.ground` 自動將腳踝抬回 `>= ANKLE_FLOOR_Y` 且 `auditMotion` 回報 `GROUND` 為 0；
     - `applyMotionFixes`：當支撐腳在落地段水平漂移 `0.04 m` 時，`fix.slide` 將其鎖定在落地支點，消除滑步；
     - `applyMotionFixes`：當 `wristL` 穿入 `SCENE_BOXES.console` 內部時，`fix.penetration` 將手腕推回控制台表面外；
     - `auditMotion`：未開 `fix` 時能準確抓出 `GROUND`、`SLIDE`、`PENETRATION`、`REACH` 並回傳 `worstFrame`、`cause` 與 `hint`；
     - `compileMotionSkills` + `searchMotionPlan`：能串接 `walkTo` + `reachGrip` 並對 `{ range: [lo, hi] }` 參數自動搜尋出 `cost === 0` 的解。
2. **工作台控制項預算與既有 UI 測試**：
   ```bash
   node --test ui/tests/uiBudget.test.mjs ui/tests/story-ui.test.mjs ui/tests/studio-ui.test.mjs ui/tests/i18n.test.mjs
   ```
3. **全套前端測試與正式編譯**：
   ```bash
   npm test --prefix ui && npm run build --prefix ui
   ```
