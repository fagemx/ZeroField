# SPEC 10 — Shot Grammar 表演層（設計）

> 範圍：`ui/prototypes/shot-grammar/` 的表演層。互動規則沿用 [SPEC_09](./SPEC_09_SHOT_GRAMMAR_INTERACTION.md)（R1–R11）。
> 依據：ad_growth_data「影片拍法生成器」的表演段、表演調節、表演檢查（`perf_check.js`）與假人骨架（`rig.js`），以及 ZeroField 的提示詞組裝與兩條 3D Stage 渲染路徑。

## 1. 原版怎麼做（要保留的核心）

1. **鏡頭決定空間，文字決定表演。** 分鏡圖（灰模）是基準，畫的是拍法原本的姿勢；表演的強弱靠文字往上或往下推。實測結論：「基準決定姿勢上限，文字往上推一到兩檔」。
2. **拍法帶表演宣告**：表演方式、原生尺度、可調範圍、肢體範圍、動作骨架（一定要保留的動作詞）、高峰姿勢；誇張類拍法自帶走位與姿勢。
3. **表演調節是檔位，不是自由文字**：尺度（含蓄 / 自然 / 外放 / 誇張）、肢體（只演臉 / 上半身 / 全身）、情緒色彩、情緒落點、一句話指示、分鏡貼合。每個檔位對應一句**固定的指示句**，交給代理照寫。
4. **代理寫，程式檢查，沒過重寫一次，還不行退回模板。** 檢查：鏡頭字、畫風字、畫面上的字、台詞外洩、寫反動作骨架、尺度與肢體、情緒色彩、字數。
5. **表演段有三種來源**：你改過的 > 代理寫的 > 拍法模板。檔位或取景改了就標「待重寫」；寫過的檔位組合會快取，切回來直接換上。
6. **一拍可以寫三版挑一**，左右並排看現在的和新的，按「套用」才換上。
7. **超出分鏡圖畫的幅度時自動放鬆參考**：尺度或肢體調得比基準大，分鏡參考自動從「貼著分鏡」改成「參考站位」，免得被圖拉回去。

## 2. ZeroField 的差異

| 項目 | 原版 | ZeroField |
|---|---|---|
| 表演落在哪 | 即夢提示詞的每鏡表演句 | LTX 提示詞的 **Action & Audio Prompt** 欄（`context_compiler` 組成 `Optical Rig … Camera Movement … References … <Action>`） |
| 文字格式 | 一鏡一段 | LTX 吃**依時間點的 beat sheet**（motion lab 實測：`0–1.5s: … 1.5–2.5s: …`），一列一段連續鏡頭 |
| 基準是什麼 | 分鏡圖（Codex 照灰模畫） | 3D 預演 + Layout Key（Klein 重畫的首格） |
| 誰決定姿勢 | 分鏡圖 + 文字 | 依渲染路徑不同：**Motion pass**（灰模當起始畫面）跟著假人姿勢；**Layout Render** 的演員遮罩把演員交給模型，姿勢由文字與首格決定 |
| 假人 | 全骨架、IK、19 種姿勢、身體動作疊加 | 只有一個肩關節、三種動作（轉身伸手 / 站立 / 走入） |
| 代理 | 片場模型路線（DeepSeek） | 本機開源模型（Ollama `qwen3.8:27b`，OpenAI 相容端點）；整合後走 Screenwriter / Cinematographer agent 工具 |
| 語言 | 繁中、手遊廣告 | 英文、真人電影（LTX 提示詞是英文） |

## 3. 設計

### 3.1 一條表演時間軸，同時驅動假人和文字

每一拍有一組**表演關鍵點**（acts）：`{at: 0–1, look, hands, body, beat: "一句看得到的動作"}`。

- 給 3D：同一組關鍵點驅動假人（看哪裡、手在哪、身體動作），預演和 Motion pass 照著演。
- 給文字：關鍵點切出 beat sheet 的時間段，例如 `0.0–1.4s` / `1.4–2.8s` / `2.8–4.0s`，每段寫那一段的表演。
- 結果：在時間軸上把「他抬眼」那個點往後拖，預演裡他晚一點抬眼，提示詞的時間也跟著變。原版的 acts 只寫在資料裡，沒有 UI 可以調；這裡讓它可以直接拖。

### 3.2 資料

| 層 | 欄位 |
|---|---|
| 拍法 `perf` 宣告 | `way`（表演方式）、`scale`、`range[lo, hi]`、`body`、`core[]`（動作骨架詞）、`peak`（高峰描述）、`acts[]`（預設關鍵點）、`template`（各段表演句模板，含 `{slot}`） |
| 拍的表演設定 `S.perf[beat]` | `scale`、`body`、`color`、`focus[]`、`note`、`fit`、`acts`（覆寫關鍵點）、`line {who, text}`（台詞） |
| 每拍表演段 `S.acts[beat]` | `source: template / agent / edited`、`text`（beat sheet）、`sig`（寫的時候的檔位與取景簽名，用來判斷待重寫） |

### 3.3 可調整項

| 項目 | 位置 | 手勢 | 範圍來源 | 代價 |
|---|---|---|---|---|
| 尺度 | 單鏡頁表演卡 | 分段按鈕 subtle / natural / open / heightened | 四檔都可選；超出拍法 `range` 的檔位用虛線框，選了會提示「比預演大」 | 只改文字 |
| 肢體 | 同上 | face / upper body / full body | 超出拍法 `body` 用虛線框 | 只改文字 |
| 情緒色彩 | 同上 | 無 / a hint of a smile / tears / anger / fear / defiance / tenderness | — | 只改文字 |
| 情緒落點 | 同上 | 多選 eyes / hands / posture / voice | — | 只改文字 |
| 一句話指示 | 同上 | 文字輸入，60 字內 | — | 只改文字 |
| 貼合 | 同上 | Auto / follow the previs pose / blocking only / free | 對應渲染路徑：pose → Motion pass；blocking → Layout Render + 演員遮罩；free → 只用首格與文字。Auto 跟著尺度與肢體自動決定，手動選了可以按 Auto 回到自動 | 重渲預演 |
| 表演關鍵點時間 | 單鏡頁取景列下方的表演軌 | 左右拖點；聚焦後方向鍵每次 0.1 秒 | 0–1，相鄰點至少 0.25 秒，吸附 0.05 秒；起始點不能拖 | 重渲預演 |
| 關鍵點內容 | 點一下關鍵點 | 看哪裡 / 手 / 離站位幾公尺 / 一句動作（有文字的點才切出一段）；雙擊軌道新增、Delete 刪除 | 選項由場景與假人能做的動作決定 | 重渲預演 |
| 表演段文字 | 表演卡文字區 | 直接改；「回到模板」 | 改了就是 `edited`，不會被代理蓋掉 | 只改文字 |
| 代理撰寫 | 表演卡 | 「重寫這一拍」/「寫三版挑一」/ 頂列「寫整場」 | — | 只改文字 |

**超出基準的處理**（原版第 7 點）：尺度或肢體超出拍法宣告時，貼合自動從 `pose` 放鬆成 `blocking`（Layout Render 的遮罩放開演員），並在套用說明裡寫出來。

### 3.4 代理撰寫

- **模型**：本機 Ollama `qwen3.8:27b`（`http://127.0.0.1:11434/v1`，原型頁已允許跨來源）。寫完送 `keep_alive: 0` 釋放 GPU，避免和 LTX 搶 4090（沿用評分的做法）。
- **寫法規則**（英文、真人電影；由原版 12 條改寫）：寫變化的過程不寫形容詞清單；寫潛台詞（"as if…"）；寫不要的演法並說用什麼取代（含蓄防演過頭、外放防演不開）；只寫看得到的部位（依景別給「畫面看得到什麼」）；不寫鏡頭字；台詞只寫念法；不寫畫面上的字與畫風字；字數依秒數；保留動作骨架；一定照表演指示。
- **流程**：寫 → 程式檢查 → 沒過的重寫一次 → 還不行退回模板。結果先進預覽：舊的和新的並排，按「套用」才換上（三版時可切換比較）。
- **快取**：同一拍、同一組檔位與取景寫過的，切回來直接換上，不再呼叫模型。

### 3.5 檢查（`perf_check` 英文版）

鏡頭字（camera, close-up, push in, pan, zoom, shot, frame, angle, lens…）、畫風字（CGI, 3D, render, photoreal…）、畫面上的字（caption, subtitle, title, text on screen）、台詞外洩、寫反動作骨架（否定子句裡出現模板肯定的動作或物件）、尺度（外放以上不能寫 subtle / barely / restrained；heightened 要有大動作；subtle 不能有大動作）、肢體（face 不能有 turn / step / stand / lean…；upper 不能有 walk / stand up / kneel…）、情緒色彩（要寫到對應的詞）、每段字數。

### 3.6 輸出到 Action & Audio Prompt

```
0.0–1.4s: <這一段的表演>
1.4–2.8s: <…>
2.8–4.0s: <…>
Kael says: "…" (<念法>)            ← 有台詞時
Sound: <聲音>                       ← 拍的聲音描述
```

鏡頭字由 Camera Motion 欄負責（Shot Grammar 已寫好），兩欄不重複。

## 4. 分期

| 期 | 內容 | 需要 |
|---|---|---|
| P1 文字層 | 拍法 perf 宣告、表演設定與檔位、模板 beat sheet、表演卡、代理撰寫（本機模型）、檢查、三版挑一、快取、匯出到 Action & Audio Prompt；表演關鍵點驅動**現有**假人能做的部分（看向、轉身、伸手的時間） | 不改產品假人 |
| P2 可動假人 | 依現有假人外形加關節（頸、頭、胸、雙臂、雙腿），保留 Layout-To-Render 驗證過的比例與面向線索；姿勢庫與身體動作疊加（仰頭、前傾、縮、垂肩…）；關鍵點可選姿勢 | 在 4090 上重新驗證 Layout Render 與 Motion pass |
| P3 第二演員 | 兩人走位、過肩、對話（看對方、台詞輪替） | P2 |

## 5. 驗收

- 每個調整項遵守 SPEC_09 R1–R11。
- 代理不可用時（模型沒開、逾時），表演段維持原樣並說明原因，模板仍可用。
- 檢查規則有單元測試；beat sheet 時間與關鍵點一致有單元測試。
- 在 4090 上用一拍實測：同一鏡頭、不同尺度，Layout Render 出來的表演幅度有差異。

## 6. P1 實作狀態（2026-10-21）

| 項目 | 位置 | 狀態 |
|---|---|---|
| 表演宣告、檔位、模板 beat sheet、檢查、寫法規則 | `ui/prototypes/shot-grammar/perf.js` | 完成；預設關鍵點用 n/96 時間，重播 3D Stage 的轉身伸手誤差 < 1e-9 |
| 寫、檢查、沒過的重寫一次、還不行退回模板 | `perf.js` `writeScene` / `writeVersions` | 完成；已通過的拍不會被重問 |
| 表演卡 | `app.js` `renderPerf` | 完成：檔位（超出預演的檔位虛線框）、Auto fit 與原因、逐段編輯、來源標籤、待重寫、三版並排、快取換回 |
| 表演軌 | `perftrack.js` | 完成：拖曳、方向鍵、編輯列、雙擊新增、刪除、回到預設；段數改變時說明寫好的文字暫時不套用 |
| 匯出 | Export 頁 | Action & Audio Prompt 每拍可複製，Copy all 也含在內；表演關鍵點以 plan 的 `acts` 欄位帶進 3D Stage（§7） |

本機實測（RTX 4090，`qwen3.8:27b-16k`，Ollama `/api/chat`，`think: false`、`format: json`，寫完 `keep_alive: 0`）：

- 單拍重寫 12 秒；三版 19 秒；整場 5 拍 20–26 秒。寫完 `/api/ps` 為空，GPU 已還給 LTX。
- 整場第一次 2 拍沒過（heightened 沒寫大動作、open 寫了 slightly）。把這兩條直接寫進尺度指示句後，第二次 4/5 通過；剩下一拍是檢查誤判（「tilts his head」當成鏡頭字），已把鏡頭字收窄成只認鏡頭用法。
- 4090 上的 Layout Render 尺度對照見 §7.4。

## 7. P2 / P3 與分鏡外觀（2026-10-21）

### 7.1 plan 新欄位（產品 `ui/src/previs/plan.js`、`scene.js`）

| 欄位 | 內容 | 說明 |
|---|---|---|
| `acts` | `[{at 0–1, yaw?, reach?, back?, body?}]` | 表演關鍵點。每個通道在設定它的關鍵點之間緩動；`body` 是姿勢名，第一個姿勢之前從站姿開始。有 `acts` 時取代 `action` 的三種固定動作，`yaw` 為絕對方向 |
| `mark` `[x, z]`、`turn`（度） | 主體的站位與額外轉向 | SPEC_09 §8 要的欄位，Render previs 現在會照站位擺人 |
| `figure` | `{build, outfit, hair, tone}` | 假人樣式：體型 man / woman / child / elder、服裝 jacket / longcoat / dress / robe、髮型 short / long / bun；`tone` 是這個人的顏色（分鏡外觀）與大衣色調（渲染外觀），每一鏡都一樣 |
| `cast` | `[{figure, mark, turn, acts}]` | 同框的其他人；`stage.matte()` 把所有人都畫成白色 |

全部存在 WebM 標題的 plan 裡；S03 加 `acts` 後仍遠小於 8 KB。

### 7.2 P2 可動假人

- 關節：骨盆、脊椎、頸、肩、肘、髖、膝、踝；手臂用 YXZ 旋轉順序（先往前抬再往內轉）。
- 站姿時每個部件都在原本單件假人的位置（整體外框差 9 mm；只有被切成兩段的手腳中心點不同）。
- 姿勢庫 10 種：stand、lean、recoil、slump、lookup、lookdown、face（雙手摀臉）、crossed（雙臂交叉）、open（張開雙臂）、kneel（單膝跪）。`reach` 通道從任何姿勢把左手伸向控制台。
- **4090 驗證**：同一個 s03m plan、同一個種子與首格，用有關節的假人重渲預演與遮罩再跑 Layout Render，成片和舊假人幾乎相同（同一個成年男性、同樣背對鏡頭、同樣構圖；演員動態量 5.57 對 5.64）。[對照圖](../verification/motion-lab/perf_rig_jointed_s03.jpg)

### 7.3 P3 第二演員（原型 `grammar.js` RELIEF 場）

- 兩人場的站位是整場共用的（`blocking`）：在俯視圖拖任一人，整場跟著移動，正反拍才會接得起來。
- 180 度線：俯視圖畫出兩人之間的線，鏡頭那一側打底色；每拍挑出的角度若落在另一側，會往兩邊找最接近、離線至少 0.15 m 的角度（主體轉身背對對方時，單純鏡像也可能壓在線上）。手動設定的角度不自動改，只提出越線警告；頂列可以整場換邊。
- 兩人用的拍法：Two-shot wide、Over the shoulder、Over the shoulder onto the hands、Two-shot push、Push past the shoulder、Two-shot pull-out；有對手的拍優先挑這些。過肩鏡頭依兩人距離算角度：固定的離連線 0.3 m，推進的 0.45 m（從肩旁擦過，不穿過人）。
- 互看：`look: 'partner'` 依兩人的站位算方向。
- 已知缺口：固定的過肩鏡頭在高角度時，前景演員的肩膀不一定入框；要把對焦點往前景肩膀那側偏。

### 7.4 表演文字的尺度：4090 對照

同一個 S03 預演（有關節的假人）、同一個種子與 Klein 首格，Layout Render 加演員遮罩；只換 Action & Audio Prompt。

| 版本 | 結果 |
|---|---|
| 原本的提示詞（明寫「背對鏡頭」） | 背對鏡頭轉轉盤 |
| subtle 對 heightened，beat sheet 沒寫朝向 | **兩版都把他轉過來面對鏡頭**；heightened 的表情較大（張嘴、睜大眼），身體動作量幾乎一樣（演員動態量 6.85 對 6.74）。[對照圖](../verification/motion-lab/perf_scale_s03.jpg) |
| 同上，寫給模型的說明附上每段朝向（「seen from behind」） | heightened 全程背對；subtle 寫了「eyes wide」「jaw tightens」，後半段又轉成 3/4 正面。[對照圖](../verification/motion-lab/perf_scale_s03_facing.jpg) |
| 再加上：從背後看的段落不寫臉部細節，朝向直接寫進每段時間標記（`1.4–2.8s, seen from behind:`） | **兩版都全程背對鏡頭**；身體動作量仍幾乎一樣（5.44 對 5.61）。[對照圖](../verification/motion-lab/perf_scale_s03_facing2.jpg) |

結論與修正：

1. 遮罩放開演員後，**朝向由文字決定**，而且描寫看不到的臉會讓模型把人轉過來。現在：寫給模型的說明附上每段朝向（「seen from behind / in profile / from the front」，不用 camera 這個字，模型會照抄而違反鏡頭字規則）；朝向寫進 beat sheet 每段的時間標記；檢查會攔「轉向鏡頭」和「從背後看卻描寫臉」。
2. 尺度文字主要改變表情（看得到臉時），不太改變身體幅度。身體幅度的答案見 §7.6：要的是寫清楚身體怎麼動的文字，不是尺度。

### 7.5 分鏡外觀（`ui/src/previs/board.js`）

- 編輯器預設用分鏡外觀：人偶、著色器與描邊移植自影片拍法生成器的 `rig.js`（素描人偶：蛋形頭加十字輔助線、球關節、圓潤胸腔、漸細四肢、有手指的手、粗描邊），每人一種顏色，場景是明亮的高調灰。
- 關節名稱與渲染假人相同，姿勢和表演關鍵點兩邊通用；整體放大 1.045 倍讓頭頂高度一致，取景不因外觀切換而變。
- 送給 LTX 的預演永遠用渲染外觀（灰模、無描邊）：描邊會讓 Motion pass 變卡通。頂列 Look 可切換，隨時看實際送出去的樣子。
- 預演亮度：Motion pass 會把預演的光線方向與明暗帶進成片；Layout Render 的明暗與色彩來自首格與提示詞（§7.4 的成片是黎明光，預演是灰藍）。

### 7.6 姿勢、文字與假人造型：4090 對照

同一個 S03 plan，用表演關鍵點排兩支預演：照原本走位（`s03b`），以及信標亮起後放開轉盤退縮（`s03p`，0.72→0.80 recoil）。同一個種子與 Klein 首格。演員動態量只算退縮開始（0.72）之後、演員遮罩範圍內。[數據](../verification/motion-lab/perf_pose_s03.json)

**只有姿勢，提示詞不提退縮**（[Motion](../verification/motion-lab/perf_pose_s03_motion.jpg)、[Layout](../verification/motion-lab/perf_pose_s03_layout.jpg)、[加遮罩](../verification/motion-lab/perf_pose_s03_layout_mask.jpg)、[半遮罩](../verification/motion-lab/perf_pose_s03_follow.jpg)）

| 路徑 | 姿勢帶進成片 | 演員 | 動態量（走位 → 退縮） |
|---|---|---|---|
| Motion pass（灰模起始、denoise 0.75） | 沒有，四肢與仰頭都消失；場景被重新發明 | 真人 | 4.25 → 4.50 |
| Layout，演員跟著預演（1.0） | 完整 | 變成假人 | 4.60 → 5.92 |
| Layout，演員放開（0） | 幾乎沒有 | 真人 | 4.78 → 5.70 |
| 演員跟 0.35 | 仰頭有、雙臂沒有 | 真人 | 5.09 |
| 演員跟 0.6 | 完整 | 真人，但**手臂變圓管、手變握球的拳頭** | 5.85 |

**加上詳細、有時間點的身體動作描述**（「手猛地抽開、頭往後仰、雙臂抬到胸前、上身後退半步」，標明朝向、不寫臉）（[對照圖](../verification/motion-lab/perf_pose_s03_text.jpg)）

| 預演 | 路徑 | 結果 | 動態量 |
|---|---|---|---|
| 走位（沒有退縮姿勢） | 演員放開 | 有退縮，真人 | 5.17 |
| 退縮 | 演員放開 | 有退縮，時間點對準預演 | 5.99 |
| 退縮 | Motion pass | 有退縮，但場景被重新發明 | 5.66 |
| 退縮 | 跟 0.35 | 有退縮，真人 | 5.63 |

**換成圓潤、有手指的渲染假人**（`figure.js`）（[對照圖](../verification/motion-lab/perf_pose_s03_newrig.jpg)、[手的放大](../verification/motion-lab/perf_pose_s03_hands.jpg)）：放開、0.35、0.6 三種的手都是自然張開的手指；但 0.6 時肩關節球變成鼓起的墊肩、頭變成光滑的蛋形。動態量 6.27 / 6.21 / 6.80。

結論（現行做法）：

1. **推動身體動作的是文字裡具體、有時間點的身體力學**，不是尺度形容詞，也不是預演姿勢本身。姿勢負責把動作的時間點和方向對準。每個姿勢附一句身體力學描述（`perf.js` `POSE_MECHANICS`），關鍵點設了姿勢，那一段的模板與寫給模型的說明就帶上它；寫好的文字漏掉會被檢查攔下。
2. **Layout Render 的演員跟預演 0.35**（`workflows/ltx25_layout_render.json` 的 `35`/`36` 節點：遮罩反轉前乘 0.65）。0.6 會把假人的形狀帶進成片。產品 graph 在 4090 上和 lab 的 0.35 一致（動態量 6.18 對 6.21，[對照圖](../verification/motion-lab/perf_pose_s03_product.jpg)）。
3. **假人不能是方塊或圓管**：渲染用的假人改成素描人偶的形體（連成一體的軀幹、漸細四肢、有手指的手），不畫肩關節球；生成會照著吃進去。
4. Motion pass 不適合表演：它保住運鏡與大致走位，但四肢保不住，也沒有首格就會改掉場景。

### 7.7 姿勢骨架：讓假人的表演不靠外形傳過去（4090 對照）

7.6 的限制：Layout Render 讓成片照著假人的外形畫，動作和外形綁在一起，0.35 時假人的動作幾乎傳不過去。改法是另外給模型一支**姿勢骨架影片**（DWPose／OpenPose 畫法：黑底、身體 18 點、雙手各 21 點），骨架只有關節沒有形體，沒有東西可以被畫進去。

- 骨架是精確的，不用估：`research/motion_lab/stage_render.py pose` 逐格擺好假人，把 `figure.js` 標記的關節投影成像素；鼻子和眼睛只在臉朝鏡頭時畫，耳朵依那一側是否朝鏡頭。檢查：1082 個身體點全部落在演員遮罩上。
- 模型：LTX-2.3 Union-Control（canny、depth、pose 三合一，參考畫面為輸出的一半解析度），在 LTX-2.5 上跑。
- 驅動腳本：`research/motion_lab/pose_skeleton.py`。S03 退縮 plan 用目前的渲染假人（沒有肩關節球）重渲，同一個種子與 Klein 首格。

| 做法 | 說明 |
|---|---|
| follow35 | 現行產品做法：Layout-To-Render，演員跟預演 0.35 |
| layout_pose | Layout-To-Render（演員完全放開）＋ Union-Control 骨架：兩個 IC-LoRA、兩條引導 |
| pose | 只有 Union-Control 骨架，沒有 Layout 引導 |
| follow60 | 現行做法改成 0.6，沒有肩關節球的假人 |

**提示詞不提退縮**（只寫轉轉盤、信標亮起）：這組才分得出假人的表演有沒有傳過去。[對照圖](../verification/motion-lab/perf_pose_s03_skeleton_neutral.jpg)、[另一組](../verification/motion-lab/perf_pose_s03_skeleton_neutral_b.jpg)

| 做法 | 退縮 | 演員 | 場景與運鏡 | 動態量 | 秒數 |
|---|---|---|---|---|---|
| follow35 | **沒有**，手一直在轉盤上 | 真人 | 保住，0.96 | 5.79 | 129 |
| layout_pose | **有**，雙手張開舉起；頭轉向側面，仰得不如預演 | 真人 | 保住，0.96 | 4.15 | 158 |
| pose | 有，同上 | 真人 | 運鏡 0.98，但場景走樣（控制台、圓頂和預演不同） | 3.19 | 65 |
| follow60 | 有，雙手舉起、頭往後仰 | 大致是真人；動作中的頭仍偏光滑蛋形 | 保住，0.96 | 6.66 | 123 |

**提示詞詳細描述退縮**：四支都演出退縮，差異不大（[對照圖](../verification/motion-lab/perf_pose_s03_skeleton.jpg)、[另一組](../verification/motion-lab/perf_pose_s03_skeleton_b.jpg)）。文字本身就推得動，所以這組看不出骨架的作用。

結論：

1. **骨架能把假人的表演傳過去，而且不吃外形。** 不寫退縮時，0.35 完全沒有退縮，加上骨架就有，演員仍是真人。兩個 IC-LoRA 可以疊用，成片裡沒有骨架線條。
2. **骨架要配 Layout 引導。** 只有骨架時，場景和控制台會走樣。
3. **骨架從背後看只帶得到耳朵**，頭的方向訊息很弱：預演頭往後仰，成片只轉向側面。要補頭部方向（例如背面時仍畫出頭頂到頸的方向），之後再測。
4. 沒有肩關節球的假人在 0.6 時，外形滲入比 §7.6 少很多，但動作中的頭仍偏光滑；骨架路線不需要提高跟隨比例，是比較乾淨的做法。
5. 實際使用時仍建議**骨架加上詳細的身體動作描述**：骨架負責準確的姿勢與時間點，文字負責幅度和力道。

下一步（產品化）：Render previs 多輸出一支骨架影片（和遮罩一樣，從同一個 plan 逐格產生）；`workflows/ltx25_layout_render.json` 加上 Union-Control 與第二條引導；頭部方向的畫法另外驗證。

### 7.8 骨架接進產品（`d5f48fa`）

- Render previs 在表格有 Pose Skeleton 欄時多渲一道骨架（`ui/src/previs/skeleton.js`），和遮罩一樣從同一個 plan 逐格產生。
- `workflows/ltx25_layout_render.json`：演員完全放開（不再跟預演 0.35），表演改由 Union-Control 照骨架演出，假人的外形不會滲入。
- 修正：骨架投影前要先更新攝影機矩陣，否則沒有 WebGL 渲染夾在中間時晚一格（§7.7 的 4090 測試第 0 格是空的，差 1/24 秒）。

### 7.9 高張力、正面的難題（4090 對照）

之前的表演測試都是平靜、背對鏡頭（S03 轉轉盤），避開了真正的難題。這次用 Kael 與 Mira 的對質，三拍都看得到臉，每拍 6 秒：

| 拍 | 鏡頭 | 內容 |
|---|---|---|
| tears | Kael 特寫，正面 | 忍住 → 臉崩潰、低頭 → 抬頭流淚 |
| scream | Mira 特寫，正面 | 瞪著他 → 前傾嘶吼 → 喘著回到站姿 |
| shove | 中景雙人，Kael 正面、Mira 過肩 | 她雙手把他推撞到控制台（肢體接觸） |

驅動腳本 `research/motion_lab/hard_cases.py`。角色肖像先用 Klein 文生圖畫出（Kael、Mira）。每拍都走產品的 Layout Render（Layout-To-Render 放開演員 ＋ Union-Control 骨架，Layout Key 當片外參考），同一段依時間寫的詳細提示詞與種子，比較三種推情緒的方法：

| 方法 | 說明 |
|---|---|
| text | 產品現況：Layout Key 不指定表情，骨架只有身體和手 |
| key | Layout Key 畫成這拍的情緒（Klein） |
| face | 骨架加畫 68 個臉部特徵點，依表演關鍵點的表情移動（`plan.js` `EXPRESSIONS`、`skeleton.js` `faceLandmarks`） |
| face_neutral | 只有 scream：臉部點，但提示詞完全不提嘶吼 |

評估三種：看圖；ComfyUI 內建 MediaPipe 臉部偵測量出的 ARKit 表情係數（`research/motion_lab/face_metrics.py`，逐兩格量，依劇本時間段取平均）；本機 qwen3.8 盲讀表情、比對身分、判斷肢體接觸。對照圖：[tears](../verification/motion-lab/perf_hard_tears_faces.jpg)、[scream](../verification/motion-lab/perf_hard_scream_faces.jpg)、[shove](../verification/motion-lab/perf_hard_shove_faces.jpg)，全部數據在 [perf_hard_cases.json](../verification/motion-lab/perf_hard_cases.json)。

**嘶吼（下巴張開 jawOpen，0–1）**

| 方法 | 瞪人 0–1.5 s（應該閉嘴） | 嘶吼 2.3–4.8 s | 盲讀 |
|---|---|---|---|
| text | 0.00 | **0.59** | 平靜 → 憤怒 → 憤怒，清晰度 10 |
| key | **0.67**（提早嘶吼） | 0.11 | 三格都是極度憤怒 |
| face | 0.00 | 0.66 | 平靜 → 憤怒 → 憤怒，清晰度 10 |
| face_neutral | 0.00 | 0.00 | 擔憂 |

**落淚**：三支都讀得出哭（盲讀「悲傷／哀傷」，清晰度 9）。MediaPipe 的內側眉毛上揚、嘴角下垂幾乎量不到（≤0.05），能用的是瞇眼：text 從 0.28 升到 0.59、face 從 0.28 升到 0.57；key 開場就是 0.60（提早哭）。

**推撞**（中景雙人，用遠距離偵測器）：肢體接觸三支都可信（盲讀 9/10，沒有穿模：雙手推在胸口、他的頭往後甩、背撞上控制台）。Kael 被推之後的表情：text 幾乎沒有（下巴 0.01–0.02）、face 稍微張嘴（0.09–0.14）、key 一開場就震驚（內側眉毛 0.5）。

結論：

1. **LTX-2.5 演得出高張力的臉**，前提是提示詞依時間點把表情寫清楚：嘶吼的張嘴時間和劇本對齊，哭也讀得出來。特寫比中景好推；中景雙人鏡頭裡只靠文字，臉部表情很弱。
2. **情緒不要畫進 Layout Key。** Key 是整段的片外參考，不是第 0 格：帶情緒的 key 讓整段從第一秒就在嘶吼或哭，排定的高峰反而變弱。Key 的表情應該是這拍開場的狀態；高峰要靠文字，或在高峰那一格另外加一張關鍵格引導（之後再測）。
3. **臉部特徵點本身帶不動表情。** 提示詞不提嘶吼時全程閉嘴；配合文字時只有很小的差異（嘶吼 0.66 對 0.59、推撞後稍微張嘴）。Union-Control 看起來沒有學過臉部點，或半解析度的參考太粗。產品維持不畫（`drawSkeleton` 的 `face` 預設關），表情通道留著給文字和分鏡外觀用。
4. **角色長相是最弱的一環，而且是在 Layout Key 掉的。** 成片的 Kael 和肖像不像同一個人（肖像長臉、灰綠眼睛；成片圓臉、較年輕），tears 和 shove 的 Kael 彼此也像兩個演員；Mira 在 text 那支頭髮從紅棕變成深棕。回頭比對 Klein 首格，臉在首格就換了，LTX 只是照首格畫。下一步要先解決：首格的身分編輯（臉部特寫加角色肖像，lab 的 `faceswap.py` 做法），以及能用的身分分數。
5. **qwen3.8 不能當身分檢查**：每一支都回答「同一人，信心 95」，連頭髮換了顏色的也一樣，它看的是衣服和髮型。表情盲讀和肢體接觸判斷則和量測一致，可以用。
6. 準備首格時另外發現的產品風險（[肖像與首格](../verification/motion-lab/perf_hard_keys.jpg)）：
   - **場景參考圖會讓 Klein 照抄構圖**：拿一張完整的觀測站照片當最後一張參考時，六張首格都變成那張照片的構圖（小人站在玻璃前），完全不管預演。產品的 Layout Key 也帶場景圖（第三張），特寫鏡頭要再驗證。
   - **假人在特寫時不像人**：光滑的蛋形正臉被 Klein 畫成後腦勺；長髮那塊橢圓被畫成浮著的一團頭髮（scream 的 Key 換了一次種子，5503）。提示詞寫明朝向可以繞過去；假人的臉和頭髮要另外改。
   - 天文台場景寫死的信標（`scene.js`）在每一場都會亮，tears 畫面右上角出現一顆太陽。
