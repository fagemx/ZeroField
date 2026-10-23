# SPEC 14 — 構成式敘事引擎（形體→關係→世界→法則）、決策過程留痕（`choice_traces`）與多載體觀看透鏡（漫劇／電影／繪本）

> **狀態**：Ready for Execution（建構於 `e6c0f2b` / `SPEC_12` + `SPEC_13` 已完工基底之上）
> **設計哲學來源**：將 `dylan` 規格的構圖演進邏輯（**形體 → 關係 → 世界 → 世界的法則**）、**五種高階構成讀法（P1–P5）**、**決策過程痕跡（`choice_traces`）** 與 **最高判準「無標籤成立、不猜測內心戲」**，轉化為 ZeroField 進入分鏡產線前的核心故事引擎與代理判斷能力。

---

## 0. 核心構成原理與產品邊界（執行代理必讀）

本規格解決「把點子變劇本時，AI 容易套用死板的大英雄之旅模板、或寫出空洞心理獨白與情緒報幕詞」的根本問題。無論故事規模大小（60 秒日常搞笑、狗血逆襲、仙俠、懸疑，或電影短片、溫馨繪本），故事張力一律由以下 **4 個構成層次**與 **P1–P5 確定性規則**長出來：

### 0.1 故事深度的四個推進層次（L1 → L4）

| 層次 | 基本單位 | 在故事引擎裡是什麼 | 在劇本與分鏡中產生的效果 |
| :--- | :--- | :--- | :--- |
| **第一層：形體**<br>*(Form)* | **單點事實** | 孤立的點子卡：「實習仙人送外賣」「怕黑的貓頭鷹」「天文學家與黃銅轉盤」 | 基礎準確，但單獨存在時只有設定、一秒讀完，還不是故事 |
| **第二層：關係**<br>*(Relation)* | **條件交集與遮擋** | **兩筆具體限制撞在一起的取捨**：「10 分鐘內熱著送到炸雞」撞上「御劍超速食物會結冰」；「前夫包場羞辱」撞上「女主剛買下這家店正穿圍裙修水管」 | 不寫半句內心掙扎，直接讓兩個客觀條件在同一個空間相撞，戲劇張力自動成立 |
| **第三層：世界**<br>*(World)* | **跨場景物件與地景連動** | 地點（`@SET`）、人（`@CAST`）、道具（`@PROP`）跨場次留下時間痕跡（如同一只懷錶在三場戲裡的狀態變化） | 跨場次記憶自然串連，畫面有時間厚度，不靠旁白硬講背景 |
| **第四層：法則**<br>*(Law)* | **選擇慣性與行為反差** | 角色連續 2～3 次遇到狀況都維持同一行為慣性（如處處守規矩/算計），在關鍵一拍突然做出相反動作（掀桌/毀掉契約） | **只拍具體行為反差，不替角色腦補心理原因**，把想像空間留給觀眾 |

### 0.2 五種高階構成讀法（P1–P5，收斂為可程式化確定性規則）

| 編號 | 概念 | 收斂後的具體做法（不猜內心、可離線驗證） |
| :--- | :--- | :--- |
| **P1** | **時間共存**<br>（軌跡切片） | 為關鍵道具 `@PROP-01` 與場景 `@SET` 建立「起點（`origin`）→ 轉折（`turn`）→ 現況（`current`）」三段具體物理狀態切片，依序注入各場戲的分鏡描述，而非從頭到尾只寫同一個靜態道具名稱。 |
| **P2** | **缺席構成存在**<br>（留白不直說） | 支援在場次中產生「留白節拍（`omission_beat`）」：透過**缺席的物件、空著的座位、停住的手勢或未說完的半句話**構成張力，嚴禁在留白處補上「他心裡其實很痛」之類的解釋性台詞或旁白。 |
| **P3** | **形體由過程長出來**<br>（決策過程痕跡 `choice_traces`） | 創作者把點子發展成故事時，系統先根據點子提出候選「條件碰撞卡（`collision_candidates`）」。系統完整記錄創作者**手動取消勾選（劃掉 `unchecked_labels`）的套路、保留的 `kept_labels`、選擇的構成焦點 `focus` 與補上的一句限制 `extra_condition`**。故事形體由「劃掉不要的東西」長出來。 |
| **P4** | **因果倒置**<br>（選擇反差觀察） | 比對本次 `choice_trace.focus` 與過去累積的 `choice_traces`（或同一集前兩場戲的角色慣性）：當偵測到「前幾次都選 `restraint`（克制/守序），本次突改選 `reversal`（反擊/破格）」（或反之），自動在轉折場產生**行為反差鏡頭（Contrast Cue）**，只描述前後具體動作的反差，不解釋心理原因。 |
| **P5** | **觀看決定形體**<br>（載體與類型透鏡） | 同一組客觀故事骨架（L1 形體 + L2 條件碰撞 + P3 取捨痕跡 + P4 行為反差），交給不同的**載體透鏡（`mediumLens`：`manju` AI 漫劇 / `cinema` 電影 / `storybook` 繪本）**與**類型透鏡（`genreLens`：`melodrama` 狗血 / `xianxia` 仙俠 / `comedy` 搞笑 / `suspense` 懸疑 / `general` 通用）**時，切出完全不同的分鏡節奏、台詞密度與 3D Previs 運鏡。 |

### 0.3 最高驗收判準：無標籤成立（No-Label Rule）與心理腦補攔截
- **判準**：拿掉所有「他很悲傷、她很震驚、氣氛十分緊張、霸氣外露、心裡壓著這件事」等**抽象情緒標籤詞與心理腦補詞**後，單看分鏡句子裡的**具體動作、物件狀態與條件取捨**，仍能看出戲劇張力。
- **程式攔截**：新增 `audit_narrative_voice(text)` 與 `sanitize_narrative_voice(text)`，自動偵測並攔截抽象情緒報幕詞與內心戲腦補句型。

---

## 1. 既有測試零破壞鐵律（Zero Regression Guardrails）

1. **`SPEC_13` 原有 `adapt_source_to_script` 預設輸出 100% 不變**：
   - `tests/test_story_openapi.py` 的 `test_offline_adaptation_modes_and_preserved_source` 與 `test_adaptation_endpoint_is_offline_idempotent_and_validated` 會測試 `adapt_source_to_script(raw_text, mode='idea')` 與 `POST /episodes/{id}/script-adaptations`（當僅傳入 `sourceText`, `sourceMode`, `targetScenes`, `breakdownMode` 四個基礎欄位時）。
   - **防呆規則**：當未傳入 `mediumLens`、`genreLens`、`choiceTrace`（或皆為預設空值 `None`）時，`adapt_source_to_script` **必須走原有的確定性分支，回傳一字不差的相同字串**！只有當呼叫端傳入 `mediumLens`、`genreLens` 或 `choiceTrace`（或呼叫新的構成式端點）時，才啟用 L1–L4 與 P1–P5 構成式生成。
2. **`ui/tests/uiBudget.test.mjs` 與 `ui/tests/story-ui.test.mjs` 契約不變**：
   - `StoryWorkbench` 頂部常駐可見控制項維持 `<= 8`。
   - `StoryImportModal` 內原有的 `adaptStoryDraft` 與 `buildStoryFromDraft` 在未啟用構成選項時，送出的 HTTP payload 維持原樣（`{sourceText, sourceMode, targetScenes, breakdownMode}`），確保 `story-ui.test.mjs` 現有斷言 100% 通過。

---

## 2. 負責檔案清單

- `project_docs/story_adaptation.py`（核心構成引擎：L1–L4 條件碰撞產生器、P1 物件時間切片、P2 留白節拍、P3 `choice_traces` 過濾與織入、P4 行為反差計算、P5 載體×類型雙透鏡轉譯器、`audit_narrative_voice` 無標籤檢驗器）
- `project_docs/story_openapi.py`（新增 `POST /episodes/{id}/story-collisions` 候選條件碰撞與 `choice_traces` 紀錄查詢、擴充 `POST /episodes/{id}/script-adaptations` 支援 `mediumLens` / `genreLens` / `choiceTrace` 與 `voiceAudit` 回報）
- `ui/src/storyImport.js`, `ui/src/StoryWorkbenchModals.jsx`（在 `Start Creating` 彈窗整合「形式透鏡 `mediumLens` × 類型透鏡 `genreLens`」與「條件碰撞取捨器 `Choice Trace`：勾選保留、劃掉套路、補一句限制」）
- `ui/src/i18n/locales/en.json`, `ui/src/i18n/locales/zh-TW.json`
- `tests/test_story_openapi.py`, `ui/tests/story-ui.test.mjs`

---

## 3. 後端詳細規格（`project_docs/story_adaptation.py` & `story_openapi.py`）

### 3.1 常數與雙透鏡定義（P5 觀看決定形體）

在 `project_docs/story_adaptation.py` 定義：

```python
MEDIUM_LENSES = {"manju", "cinema", "storybook"}
GENRE_LENSES = {"general", "melodrama", "xianxia", "comedy", "suspense"}
CHOICE_FOCUSES = {"overall", "collision", "restraint", "reversal", "negative_space"}
```

1. **三大載體透鏡（`MEDIUM_LENSES`）的具體構成差異**：
   - **`"manju"`（AI 漫劇／豎屏短劇慣例）**：
     - **切角**：聚焦「當場條件對撞、爽脆拍板、高密度對手戲交鋒、集尾斷章（Cliffhanger）」。
     - **分鏡與 Previs 連動**：首鏡直接把「人物 + 衝突條件道具 `@PROP-01`」擺在畫面中央（禁止純空景開場）；鏡頭偏好 `50mm` 對峙與 `85mm` 反應特寫，運鏡偏好 `pushin` 與 `track`，預設建議畫面比例 `9:16`。
   - **`"cinema"`（電影短片慣例）**：
     - **切角**：聚焦「空間遮擋關係（L2）、跨場次物件時間切片（P1）、留白不直說（P2）」。
     - **分鏡與 Previs 連動**：強調前景／中景／遠景 `parallax` 遮擋，必含 1 顆 **P2 留白鏡頭（`omission_beat`，無台詞、僅拍手部動作或空位與環境物件的關係）**；運鏡偏好 `35mm` `Slow Dolly In` 與 `Orbit 45°`。
   - **`"storybook"`（繪本／視覺故事書慣例）**：
     - **切角**：聚焦「單純形體對比、三次重複後的轉折（P4 規律與打破）、翻頁揭曉（Page-turn contrast）」。
     - **分鏡與 Previs 連動**：每拍由「一句具畫面感的簡潔敘事旁白 ＋ 一個明確的視覺形體對比」構成，不寫複雜爭吵對白；運鏡偏好穩定構圖（`Static Tripod` 與尾拍 `Crane Up`）。

2. **五大類型透鏡（`GENRE_LENSES`）的條件碰撞庫（只提供「具體條件交集」，不寫心理模板）**：
   - **`"melodrama"`（狗血逆襲）**：**身分／契約條件相撞**（例如：「正在執行低調基層工作／簽下隱名轉讓書」撞上「昔日關係人帶著炫耀條件當場包場施壓」）。角色自動配置反轉變體（如 `@CAST-01:formal` 或 `@CAST-01:revealed`）。
   - **`"xianxia"`（仙俠玄幻）**：**法則／代價條件相撞**（例如：「必須在香燃盡前護送凡間物件／維持封印」撞上「每次動用靈力都會讓手上的凡間物件崩裂一分」）。角色自動配置覺醒變體（如 `@CAST-01:awakened`）。
   - **`"comedy"`（荒誕搞笑）**：**嚴肅危機撞上日常瑣碎限制**（例如：「正在進行攸關生死的決戰／機密交接」撞上「外送超時倒數 60 秒／必須先幫路人簽收包裹才能拔劍」）。
   - **`"suspense"`（懸疑燒腦）**：**時間／空間異常條件相撞**（例如：「記錄器顯示距離目標還有三步」撞上「眼前的走廊已經走到盡頭且多出一件自己的舊物」）。
   - **`"general"`（通用生活／戲劇）**：**日常處境的兩難取捨**（從輸入點子提取主體與物件，構造「時間／環境限制」撞上「眼前必須完成的動作」）。

### 3.2 候選條件碰撞產生器 `propose_story_collisions(raw_text, medium_lens="manju", genre_lens="general")`（L1 → L2）

當使用者輸入一個點子或段落（L1 形體，如 `"一個外送員其實是隱世仙尊"` 或 `"A lighthouse keeper finds the lamp attracts sea monsters"`），純函數 `propose_story_collisions` 拆解出：
1. **`forms`（L1 形體單點）**：`{ "actors": [...], "prop": "...", "setting": "..." }`
2. **`candidates`（L2 關係：4 張具體的「條件碰撞候選卡」）**：
   - 每張卡片包含 `{ "id": "col_1", "label": "...", "conditionA": "...", "conditionB": "...", "focus": "collision" | "restraint" | "reversal" | "negative_space", "propSlice": ["起點狀態", "轉折狀態", "現況狀態"] }`。
   - **關鍵原則**：每張候選卡都是兩個具體客觀條件的交集（`conditionA` 撞上 `conditionB`），創作者可以像在 `dylan` 的 `decide.py` 一樣，**勾選保留（`kept_labels`）或取消勾選劃掉（`unchecked_labels`）**！

### 3.3 決策過程痕跡 `choice_traces` 與 P3 / P4 計算

1. **資料結構（儲存於 `projectops.story_record`，`kind = "choice_trace"`，`id = "ctr_" + uuid`）**：
   ```python
   {
       "traceId": "ctr_...",
       "episodeId": ep["episodeId"],
       "mediumLens": "manju" | "cinema" | "storybook",
       "genreLens": "general" | "melodrama" | "xianxia" | "comedy" | "suspense",
       "focus": "overall" | "collision" | "restraint" | "reversal" | "negative_space",
       "keptLabels": ["..."],       # 創作者保留的條件碰撞
       "uncheckedLabels": ["..."],  # P3: 創作者明確劃掉（不要）的套路
       "extraCondition": "...",     # P3: 創作者手動補上的一句額外限制條件
       "contrastDetected": bool,    # P4: 是否與過去累積的 focus 形成反差
       "contrastCue": "...",        # P4: 客觀行為反差描述（不猜心理原因）
       "createdAt": "..."
   }
   ```
2. **P4 選擇反差規則 `compute_choice_contrast(history_traces, current_focus)`**：
   - 讀取該集（或該專案）過去最多 5 筆 `choice_traces`：
   - 若過去 5 筆中有 $\ge 2$ 筆集中於同一常態（例如 `'restraint'` 隱忍守序，或 `'collision'` 正面硬剛），而本次 `current_focus` 切換為相反路線（例如 `'reversal'` 破格掀桌，或 `'negative_space'` 突然留白收手）：
   - 回傳 `{"contrastDetected": True, "dominantFocus": ..., "currentFocus": current_focus, "contrastCue": "Prior beats held to <dominant>; this turn switches directly to <current> action without explanation."}`。
3. **P3 過程長出形體（負向排除與額外條件織入）**：
   - 當組裝最終劇本時：
     - 所有出現在 `uncheckedLabels` 的套路關鍵字或橋段**絕對不會進入劇本**；
     - `keptLabels` 的具體碰撞條件（`conditionA` × `conditionB`）與創作者手寫的 `extraCondition` **必定寫入第 1 場與第 2 場的環境與動作節拍中**；
     - `@PROP-01` 依 **P1 時間共存** 在各場戲依序呈現 `propSlice[0]`（起點）➔ `propSlice[1]`（轉折）➔ `propSlice[2]`（現況）。

### 3.4 無標籤檢驗器與報幕詞攔截 `audit_narrative_voice(text)` & `sanitize_narrative_voice(text)`

對齊 `dylan` 規格 `0.4 最高驗收判準（無標籤成立）`：
1. **禁用詞庫（Banned Label & Psychological Speculation Patterns）**：
   - 攔截中文與英文的「內心腦補詞」與「抽象情緒報幕詞」：
     - 中文：`r"心裡壓著|心裡還沒準備好|內心深處感到|心想自己|暗自決定|霸氣外露|氣氛十分緊張|感到無比絕望|我知道你心裡|根據我的記憶"`
     - 英文：`r"\b(?:feels deep inside|secretly thinks to (?:himself|herself|themselves)|overwhelmed with raw emotion|an aura of dominance|the atmosphere is very tense|deep down in (?:his|her|their) heart)\b"`
2. **`audit_narrative_voice(text)` 回傳**：
   ```python
   {
       "ok": bool,                 # violations 為空時為 True
       "violations": list[str],    # 命中的禁用標籤或心理腦補詞
       "concreteScore": int,       # 0..100，根據具體動作動詞、@CAST/@SET/@PROP 交互與無標籤程度計分
   }
   ```
3. **`sanitize_narrative_voice(text)`**：
   - 將抽象情緒標籤與心理腦補子句替換或移除為純粹的**外部可拍攝動作與物件狀態**（例如將 `"feels deep inside that time is running out"` 轉為 `"checks the @PROP-01 indicator as the mark advances"`，將 `"霸氣外露地看著眾人"` 轉為 `"將 @PROP-01 重重按在檯面上，全場停下動作"`），確保送進分鏡表的每一句話都 **100% 無標籤成立且可被鏡頭拍攝**！

### 3.5 新增與擴充 OpenAPI 端點（`project_docs/story_openapi.py`）

1. **新增 `POST /aivideo/open/v1/episodes/{episodeId}/story-collisions`**：
   - 請求 Body：`{ "sourceText": "...", "mediumLens": "manju" | "cinema" | "storybook", "genreLens": "general" | "melodrama" | "xianxia" | "comedy" | "suspense" }`
   - 回傳 `{ "forms": {...}, "candidates": [...], "mediumLens": ..., "genreLens": ..., "recentTraces": [...] }`（供前端在進入劇本前展示 4 張條件碰撞卡讓創作者勾選／劃掉）。
2. **新增 `GET /aivideo/open/v1/episodes/{episodeId}/choice-traces`**：
   - 回傳該集歷次 `choice_traces` 紀錄列表。
3. **擴充 `POST /aivideo/open/v1/episodes/{episodeId}/script-adaptations`**：
   - 除既有欄位外，支援選填欄位：
     - `mediumLens`: `"manju" | "cinema" | "storybook"`
     - `genreLens`: `"general" | "melodrama" | "xianxia" | "comedy" | "suspense"`
     - `choiceTrace`: `{ "focus": "...", "keptLabels": [...], "uncheckedLabels": [...], "extraCondition": "..." }`
   - 當提供 `choiceTrace` 時，自動寫入一筆 `ctr_...` 紀錄至 `story_record`，計算 P4 `contrastDetected`，並執行 L1–L4 + P1–P5 + `sanitize_narrative_voice` 生成劇本。
   - 回傳 payload 新增選填資訊（不影響既有 `script`, `engine`, `sourceMode`, `targetScenes`, `breakdownMode` 欄位）：
     - `voiceAudit`: `audit_narrative_voice(script)`（驗證 `ok == True`）
     - `choiceTrace`: 儲存後的 `choice_trace` 摘要（含 `keptLabels`, `uncheckedLabels`, `extraCondition`, `contrastDetected`）。
4. **`infer_shot_grammar` 支援 `medium_lens` 透鏡微調**：
   - 當劇本或場次帶有載體透鏡標記（或傳入 `medium_lens`）時：
     - `manju`：拉高特寫與中近景比例，運動更具衝擊力；
     - `cinema`：針對 P2 留白拍（`[Omission]` 或無對白環境動作拍）自動配給 `Slow Dolly In` / `Orbit 45°` 與 `parallax` 景深；
     - `storybook`：配給穩定畫框與翻頁揭曉運鏡。
   - **相容性守衛**：未指定 `medium_lens` 時，`infer_shot_grammar(beat_text, beat_index, total_beats)` 的輸出與 `SPEC_13` 完全一致！

---

## 4. 前端詳細規格（`ui/src/storyImport.js` & `ui/src/StoryWorkbenchModals.jsx`）

### 4.1 在 `StoryImportModal`（`Start Creating`）加入「形式×類型透鏡（P5）」與「條件碰撞取捨器（P3 `choice_traces`）」

為了嚴格遵守 `SPEC_12` 的控制項預算（R2 模式閘門），所有構成式控制項只在 `sourceMode !== 'script'`（即 `Idea / Logline` 或 `Novel / Story` 模式）下顯示：

1. **P5 觀看透鏡選擇列（Medium Lens × Genre Lens）**：
   - **Manifestation / Medium Lens（表現形式透鏡）**：
     - `AI Manju / Micro-Drama（AI 漫劇／豎屏短劇）`
     - `Cinema Short（電影敘事短片）`
     - `Illustrated Storybook（繪本／視覺故事書）`
   - **Collision Genre Lens（條件碰撞類型）**：
     - `General Drama（日常／通用條件交集）`
     - `Melodrama Reversal（狗血逆襲：契約／身分相撞）`
     - `Xianxia / Fantasy（仙俠玄幻：法則／代價相撞）`
     - `Absurd Comedy（荒誕搞笑：生死危機撞上日常瑣事）`
     - `Rule Suspense（懸疑燒腦：時空／物件異常相撞）`
2. **P3 條件碰撞與劃掉取捨器（`Explore Condition Collisions`）**：
   - 點擊 **`Collide Conditions (L1→L2)`** 按鈕後，呼叫 `POST /episodes/{epId}/story-collisions`，顯示 4 張具體的「條件交集卡（`conditionA` × `conditionB`）」與 `focus` 選擇器（`collision` 正面相撞 / `restraint` 隱忍遮擋 / `reversal` 破格反差 / `negative_space` 留白不語）：
   - 創作者可以：
     - **取消勾選（劃掉）不想要的套路卡**（自動記入 `uncheckedLabels`，畫面上顯示刪除線）；
     - **保留喜歡的條件交集卡**（`keptLabels`）；
     - **填寫一句 `Extra Condition（補一句限制條件）`**（例如：`"主角全程不能說破自己的真實身分"` 或 `"所有的衝突都發生在電梯關門前的 30 秒內"`）。
   - 點擊 `Adapt to Multi-Scene Script` 或 `Confirm Script & Build Storyboard` 時，若使用者已設定 `mediumLens` / `genreLens` / `choiceTrace`，將其一併帶入 `adaptStoryDraft` 請求，並在畫面上顯示 **無標籤檢驗結果（`No-Label Check: Clean`）** 與 **P4 行為反差提示**！
   - **舊測試相容守衛**：當 `adaptStoryDraft` 被舊測試以 `{epId, sourceMode, draft, targetScenes, breakdownMode, request}` 呼叫（未傳入 `mediumLens` / `genreLens` / `choiceTrace`）時，送出的 POST body **維持只有 `{sourceText, sourceMode, targetScenes, breakdownMode}` 四個鍵**，100% 不會破壞 `ui/tests/story-ui.test.mjs` 第 85 行的 `assert.deepEqual(sent, ...)`！

---

## 5. 驗收標準與執行指令（Acceptance Criteria）

執行代理完成後，必須依序跑過以下驗證並確保 **0 failures / 0 skips**：

1. **後端單元與整合測試（`tests/test_story_openapi.py`）**：
   ```bash
   pytest tests/test_story_openapi.py
   ```
   - 既有全部測試 **100% 原樣通過**。
   - 新增測試驗證：
     - **L1→L2 條件碰撞（`propose_story_collisions`）**：同一個點子在不同 `genre_lens`（如 `melodrama`, `xianxia`, `comedy`, `suspense`）下產出具體的雙條件交集卡（`conditionA`, `conditionB`）與 P1 道具三段狀態切片 `propSlice`；
     - **P3 `choice_traces` 負向排除與額外條件織入**：當創作者將某張候選卡放入 `uncheckedLabels` 並填入 `extraCondition` 時，生成的劇本**絕不包含 `uncheckedLabels` 的內容**，且**必定包含 `keptLabels` 與 `extraCondition`**；
     - **P4 選擇反差偵測（`compute_choice_contrast`）**：當連續兩次選 `'restraint'` 後第三次改選 `'reversal'`，`contrastDetected` 為 `True`，且劇本自動注入行為反差動作拍；
     - **P5 觀看決定形體（`mediumLens`）**：同一個點子分別以 `mediumLens="manju"`、`"cinema"`、`"storybook"` 生成時，產出截然不同的敘事結構（漫劇含高密度衝突與斷章、電影含 P2 留白鏡頭與空間遮擋、繪本含三次重複與翻頁對比）；
     - **無標籤判準（`audit_narrative_voice` & `sanitize_narrative_voice`）**：含「心裡壓著」「霸氣外露」「feels deep inside」的文字會被檢出（`ok == False`），經淨化或由引擎產出的劇本 `voiceAudit["ok"]` 恆為 `True`。
2. **前端測試、控制項預算與正式編譯**：
   ```bash
   node --test ui/tests/story-ui.test.mjs ui/tests/uiBudget.test.mjs ui/tests/studio-ui.test.mjs ui/tests/i18n.test.mjs
   npm test --prefix ui && npm run build --prefix ui
   ```
