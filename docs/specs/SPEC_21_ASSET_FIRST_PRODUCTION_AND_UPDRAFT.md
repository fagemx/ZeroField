# SPEC_21 素材優先製作法：角色三視圖、道具表、場景表、參考圖用途、固定骨架編譯，與 Updraft 高品質範例

> **狀態：** 規格定稿，實作中（2026-10-29）。整合分支 `feat/spec21-integration`（工作樹 `C:/ai_project/ZeroField-spec21`）。
> **依據：** 兩部公開製作說明的方法：Higgsfield《Hell Grind》brief（含 CINEDANCE、ACTING、LIRA 三份 skill）與《Anerneq》brief（含 SKILL v6），以及使用者的拆解研究 `AI短劇_全文件包_20261029/research/{higgsfield-anerneq,hell-grind-higgsfield}`。本專案只採用方法，不收錄對方的文字、角色或畫面。
> **相關：** SPEC_03／05（參考素材包、卡片 ref 插槽、`slot_plan`）、SPEC_18（Cast & sets 牆、角色編輯器、造型）、SPEC_19（本集質感、提示詞預覽、Take）、SPEC_20（劇組工作）。
> **截止：** 參賽截止 2026-10-30 09:00 PT（台灣 10/31 00:00）。

## 0. 目標與固定決策

### 0.1 問題
1. **鏡頭首幀不帶任何參考圖。** Story API 生成鏡頭圖片的預設卡是 `flux-soul-cast`（`project_docs/story_generation_options.py:15`），即 Klein 純文字生圖；角色、場景、道具的圖從沒進到首幀。每一鏡的臉、服裝和道具都由模型重新發明。The Last Signal 的錄音機形狀一直做不對，就是這個原因加上下一點。
2. **道具不是素材。** 錄音機只是 Kael 描述裡的「analog recorder」幾個字：沒有自己的圖、沒有形狀描述、沒有「不是什麼」的鎖。
3. **角色參考只有一張半身肖像**（`context_compiler._reference_framing`）。沒有臉部特寫、全身、背面，遠景時模型會從小人像抓臉。
4. **參考圖沒有寫用途。** 編譯出的提示詞只有一行 `References: 代號 (名字): 描述`，模型會抄構圖而不是抄臉。
5. **提示詞沒有骨架。** 場景地圖、單一光源、聲音鎖、行為檔、人數鎖、驗收句都沒有固定的位置，每鏡靠手寫。
6. **示範專案是程式畫的測試畫面**（`samples/README.md`），不是模型算圖。

### 0.2 方法（本規格要落成工具的部分）
- 素材＝**文字描述＋圖**，兩者每次一起進提示詞；文字是常數，每鏡原文貼上。
- **每個來源只負責一件事**：臉只從臉部特寫拿；服裝從沒有頭的正面全身拿；空間從場景地圖拿；光從單一光源邏輯拿；聲音從聲音鎖拿；畫面質感（鏡頭、顆粒、調色）只在場景與影片提示詞，角色表故意拍得平淡。
- **每個狀態一個素材**（濕、受傷、換裝、道具的不同版本），不混在同一段文字。
- **先壓力測試才開拍**：不同姿勢、不同光、和其他素材同框，都要認得出來。
- **參考圖寫明用途**：角色只取外觀；場景只取空間與材質，不當首幀、不繼承構圖、角度與調色；道具只取形狀與材質。
- **寫行為不寫情緒，寫狀態不寫過程**；動作逐秒；只有引號裡的台詞會被說出；只要自然聲。
- **一次改一行**，用 Take 紀錄比較。

### 0.3 固定決策
1. **不改資料表欄位。** `soul-cast` 表維持 7 欄（代號、名稱、鎖定描述、參考圖、聲音、狀態、備註）。新增的結構化資料存在 `story_record` 的 `asset_meta` 紀錄（§2.1），沿用 `store()`／`records()`。
2. **參考圖欄（第 4 欄）仍是素材的「代表圖」**：角色＝合成的三視圖表、場景＝母版、道具＝產品照。舊的程式路徑（H3、ingredients sheet、管線 lookkey）照舊讀這一欄。
3. **首幀生成一律帶參考圖。** 鏡頭圖片的預設卡改為 `flux-reference-key`（§3.1）。沒有任何有圖的素材時，它退回純文字生圖，不報錯。
4. **原始臉部特寫不再整張送進模型重畫。** 狀態變體用 Klein 編輯，從基準圖出發只改要改的地方（§2.5）；變體是新的素材列，不覆蓋基準。
5. **兩種提示詞、各自的預算**：Klein 圖片用自然語句、只寫正面描述，上限 2,200 字元（2026-10-29 GPU 生成後由 1,500 調高：1,500 時單一光源句被捨棄）；LTX 影片用固定骨架，預設上限 4,000 字元（環境變數 `ZEROFIELD_VIDEO_PROMPT_BUDGET` 可改）。超過時**整塊**依序捨棄（§3.3），不在句子中間截斷；提示詞預覽列出被捨棄的區塊。上限值由 GPU 驗收 G2 實測後定案。
6. **不新增狀態值**（`project_docs/doc_schema.py:17` 不動）；生成結果都是候選，人選定才寫入。
7. **全部開放權重**：FLUX 3 Klein（素材、首幀、編輯）、LTX-2.5（影片＋聲音）。示範路徑不出現閉源模型或 Router 卡。
8. **介面文字**一律加到 `ui/src/i18n/locales/en.json` 與 `zh-TW.json`。

## 1. 名詞
| 名詞 | 意思 |
|---|---|
| panel（面） | 素材的一張定位圖：`face`、`front`、`back`、`sheet`（角色）；`plate`、`reverse`、`angle`（場景）；`product`（道具）；`stress`（壓力測試） |
| 三視圖表（sheet） | 正面全身（**沒有頭**）｜背面全身｜大張臉部 3/4 特寫，中灰背景、平光，左右並排合成一張 |
| 鎖（locks） | 素材的文字常數：角色 `acting`（行為檔）；場景 `geo`（場景地圖）與 `light`（單一光源邏輯）；道具 `lock`（形狀鎖與「不是什麼」） |
| 參考計畫（reference plan） | 一次生成實際送進模型的參考圖清單，依序排列，每張帶用途 |
| 骨架（skeleton） | 影片提示詞的固定區塊順序（§3.2） |

## 2. 素材（後端：Story API）

### 2.1 `asset_meta` 紀錄
每個素材列一筆，`store(conn, "am_" + rowId, "asset_meta", data, slug)`：
```json
{"assetCode": "CAST-01", "rowId": "…",
 "acting": "", "geo": "", "light": "", "lock": "",
 "panels": {"face": {"url": "/projects/api/<slug>/assets/pa_…", "imageId": "im_…"}, "front": null, "back": null, "sheet": null},
 "stress": [{"imageId": "im_…", "url": "…", "variation": 0, "with": ["CAST-02"], "recognizable": null}],
 "change": ""}
```
- 文字欄各不超過 4,000 字元。`panels` 的鍵依類型：CHARACTER＝`face/front/back/sheet`；SCENE＝`plate/reverse/angle`；PROP＝`product`。
- 變體列（`CAST-01:wet`）有自己的一筆；`change` 是變體相對基準要改的地方。變體的 `acting/geo/light/lock` 空白時沿用基準。
- 沒有 `asset_meta` 的素材行為和現在一樣。

### 2.2 API（`/aivideo/open/v1`，信封與錯誤碼照 SPEC_06）
| 方法與路徑 | 內容 |
|---|---|
| `GET /assets/{id}` | 原本的欄位，加 `meta: {acting, geo, light, lock, change}` 與 `panels: {<panel>: {url, imageId} \| null}` |
| `PATCH /assets/{id}/meta` | `{acting?, geo?, light?, lock?, change?}`；需要寫入權限；回傳新的 `meta` |
| `POST /assets/{id}/image-generations` | 原本的請求，加選填 `panel`。不帶 `panel` 時行為不變。帶 `panel` 時依 §2.3 選卡與參考圖，忽略請求的 `appCode`；`count` 1–4 照 SPEC_19 B7 |
| `GET /assets/{id}/images?panel=face` | 候選清單；每筆多 `panel` 欄（舊候選為 `null`）；帶 `panel` 時只列該面 |
| `PUT /assets/{id}/panels/{panel}` | `{imageId}`：把候選設為該面。角色的 `face/front/back` 三面都選好時，伺服器合成 `sheet`（§2.4）並寫入參考圖欄；場景選 `plate`、道具選 `product` 時直接寫入參考圖欄 |
| `POST /assets/{id}/stress-tests` | `{count: 4–10, withAssets?: [代號], setCode?: 代號}`：排入 `count` 個 `panel: "stress"` 的生成，第 i 個帶 `variation: i`；回傳 `{tasks, count}` |
| `GET /assets/{id}/stress-tests` | `[{imageId, url, variation, with, recognizable}]` |
| `PUT /assets/{id}/stress-tests/{imageId}` | `{recognizable: true \| false}` |
| `POST /assets/{id}/variants` | 原本的請求，`kind` 多一個值 `STATE`（`LOOK_KINDS` 加 `"STATE"`），可帶 `change`。新變體的鎖定描述開頭自動加上 `Same identity as @<基準代號>: same face, body proportions and posture. Changed: <change>.` |
| `POST /shots/{id}/prompt-previews` | 回傳多 `referencePlan: [{assetCode, role, panel, url}]` 與 `droppedBlocks: [區塊名]` |

### 2.3 面與卡的對照
| 面 | 卡 | 參考圖（依序） | 尺寸（寬×高） |
|---|---|---|---|
| `face` | `flux-soul-cast` | 無 | 896×1184 |
| `front` | `flux-reference-key` | 本素材 `face` | 768×1344 |
| `back` | `flux-reference-key` | 本素材 `face`（只帶臉；2026-10-29 GPU 試算：同時帶正面全身時，身體會被拉成正面，出現「背面的頭、正面的身體」） | 768×1344 |
| `plate` | `flux-soul-cast` | 無 | 1344×768 |
| `reverse`、`angle` | `flux-klein-edit` | 本素材 `plate` | 1344×768 |
| `product` | `flux-soul-cast` | 無 | 1024×1024 |
| `stress` | `flux-reference-key` | 本素材的參考計畫＋`withAssets` 的參考計畫＋`setCode` 的 `plate` | 1280×704 |
| 變體的任一面 | `flux-klein-edit` | 基準素材同一面（沒有時用基準的參考圖欄） | 同該面 |

- 缺少必要的前一面時回 409 `DRAMA_STAGE_PRECONDITION`，訊息寫明先做哪一面。
- **正面全身由伺服器裁掉頭**（2026-10-29 GPU 試算：叫 Klein「頭在畫面外」時 4 張有 3 張切在鼻子或嘴巴、1 張整顆頭都在）。`front` 生成的是**有頭的全身**；`PUT /panels/front` 選定時，伺服器在下巴下方裁切，裁好的圖存成新素材檔，作為 `panels.front`；原圖仍是候選。裁切線：OpenCV 可用時用 `haarcascade_frontalface_default` 找最大的臉，取「臉框上緣＋1.25 倍臉框高」；找不到臉或沒有 OpenCV 時，用中灰背景找出人形的上緣與下緣，取「上緣＋人形高的 15%」。裁切是確定性的。
- 尺寸用卡片的寬高輸入傳入（§3.1 表）。
- 生成任務的來源（job input）多帶：`panel`、`variation`（壓力測試）、`base_panels`（變體）、`change`（變體）。

### 2.4 三視圖合成
伺服器用 Pillow 合成，不經模型：中灰底（`#8a8a8a`），三張等高排列，順序為正面全身｜背面全身｜臉部特寫；臉部那格寬度不小於整張的 38%；輸出 PNG，高 1152，寫成新的素材檔案，存為 `panels.sheet` 並寫入參考圖欄（`[Image](url)`）。合成是確定性的：同樣三張輸入得到同樣的檔案。

### 2.5 任務來源的 `asset_meta`（給編譯器的契約）
`snapshot()` 送出的來源多一個鍵：
```json
"asset_meta": {"CAST-01": {"acting": "…", "geo": "", "light": "", "lock": "", "change": "",
                           "panels": {"face": "url", "front": "url", "back": "url", "sheet": "url"}}}
```
只放有 `asset_meta` 的素材；`panels` 只放已選的面（值是 URL）。其他既有鍵不變。

## 3. 編譯與卡片

### 3.1 新卡與工作流
| 卡 | 工作流 | 內容 |
|---|---|---|
| `flux-reference-key` | `workflows/flux3_klein_reference_key.json` | Klein 文字＋最多 6 張參考圖（`ReferenceMultiLatent` 的 `images.image0…image5`，每張一個 `LoadImage`，卡片節點 `slot: "ref"`、`fieldType: "IMAGE"`），空的參考位要從圖上拔掉，零張時等於純文字生圖。`EmptyFlux2LatentImage` 的寬高開放成卡片輸入 |
| `flux-klein-edit` | `workflows/flux3_klein_edit.json` | Klein 編輯：1–3 張參考圖，第一張是要改的原圖；提示詞用「只改＿＿，其餘完全保留」格式（§3.4） |
| `flux-soul-cast`（既有） | `workflows/flux3_klein_soul_cast.json` | 寬高開放成卡片輸入，其他不變 |
| `ltx25-cinema`（既有） | `workflows/ltx25_cinema_shot.json` | 提示詞改收 §3.2 的影片骨架 |

卡片的 `engine_config.prompt_compile` 指定提示詞來源：`"reference_image"` → `ctx["image_reference_prompt"]`；`"video_skeleton"` → `ctx["video_skeleton_prompt"]`；`"asset_panel"` → `ctx["asset_panel_prompt"]`；`"edit"` → `ctx["edit_prompt"]`；沒有設定時照現在的規則。卡片的 ref 插槽在 `ctx["reference_plan"]` 存在時依它的順序填入（一個素材可以佔兩格，例如角色的臉和正面全身），否則照現在的 `slot_plan`。

### 3.2 影片骨架（`video_skeleton_prompt`，給 LTX-2.5）
區塊固定順序，標題用全大寫：
1. `SCENE CONTEXT` — 第一行固定 `EXACT N CHARACTERS — NO DUPLICATES: 名字…`（N＝本鏡提到的 CAST 數；0 時寫 `No people in frame.`），接本鏡在演什麼、時長、單一鏡頭或硬切。
2. `ACTIVE REFERENCES` — 每個提到的素材一行：`@代號 (名字) — 鎖定描述`；場景加 `take only the space and the materials`；道具加形狀鎖。
3. `LOCATION MAP` — 本鏡場景的 `geo` 原文。
4. `FIRST FRAME AND BLOCKING` — `The first frame is the given image; everyone stays where it places them.`
5. `OPTICS` — Optical Rig 欄。
6. `CAMERA` — Camera Motion 欄或 `#move` 句；沒有寫運鏡時固定 `The camera STAYS PUT: no push, no zoom, no pan.`
7. `ACTION TIMING` — Action & Audio Prompt 欄的動作部分（逐秒段落照原文）。
8. `PHYSICS` — 欄位中 `PHYSICS:` 段（有才放）。
9. `LIGHTING` — 場景 `light` 原文＋本集質感的 `Lighting:` 行。
10. `AUDIO` — 每個開口角色：`<名字> voice (verbatim): "<聲音欄原文>". Line, and nothing else: "<台詞>".`，接固定句 `Nobody else speaks. Only the quoted lines are spoken. Natural sound only, no music.`；台詞取欄位中的引號句。
11. `CHARACTER ACTING` — 提到的角色的 `acting` 原文。
12. `STYLE` — 本集質感的 `Film:`、`Color:` 行原文。
13. `POSITIVE CONSTRAINTS` — 人數鎖、道具鎖、欄位中 `CHECK:` 段（自我驗收句）。
14. `[ORDER: …]` — 欄位中 `ORDER:` 段（有才放）。

Action & Audio Prompt 欄可用的段標：`PHYSICS:`、`CHECK:`、`ORDER:`，其餘文字都是動作。**超出預算時的捨棄順序**：`ACTIVE REFERENCES` → `LOCATION MAP` → `OPTICS` → `[ORDER]` → `CHARACTER ACTING`；`SCENE CONTEXT`、`CAMERA`、`ACTION TIMING`、`PHYSICS`、`LIGHTING`、`AUDIO`、`STYLE`、`POSITIVE CONSTRAINTS` 永遠保留。首幀已經呈現參考素材、場景位置與鏡頭，這三塊文字先捨；`PHYSICS` 不捨（2026-10-29 GPU 生成：少了物理段的片段出現漂浮、滑動）。

### 3.3 首幀提示詞（`image_reference_prompt`，給 Klein）
自然語句、只寫正面描述、上限 2,200 字元，依序：
1. `Cinematic film still.` ＋景別與鏡頭（Optical Rig 的鏡頭部分；不寫機身品牌）。
2. 動作的**狀態**：Action & Audio Prompt 欄第一段（第一個逐秒段落或第一句）。
3. 每個參考圖一句用途，**編號照參考計畫的順序**：角色 `The person in image 1 and image 2 is <名字>: same face from image 1, same clothes from image 2. <鎖定描述>`；場景 `The place is the one in image k: take its space and materials only, not its framing or colour.`；道具 `The <名字> is the object in image k: <形狀鎖>`。
4. 單一光源：場景 `light` 的第一句＋本集質感 `Lighting:` 行。
5. 本集質感的 `Film:`（靜態版）與 `Color:` 行。
6. `Exactly N people in frame.`（N＝CAST 數；0 時 `An empty place with nobody in it.`）。
超過上限時依序縮短：場景與道具的鎖定描述（圖片已承載）→ 5 的質感行 → 角色的鎖定描述 → 4 的光源（最後才丟，光是最嚴的鎖）；用途句永遠保留。場景與道具在句中寫成「the＋小寫名稱」。

### 3.4 素材面提示詞（`asset_panel_prompt`）與編輯提示詞（`edit_prompt`）
依 LIRA 的模板寫成自然語句（不寫「character reference sheet」「painterly」）：
- `face`：`Close-up studio photograph of <描述>, head and shoulders, face turned slightly in three-quarter view, neutral mid-grey backdrop, soft flat light from one side, real skin with visible pores, no retouching, a small catch-light in each eye.`
- `front`（GPU 試算通過的版本）：`Full-body studio photograph from the front of the person in image 1, <體型>, wearing <服裝>. She stands straight facing the camera, arms relaxed at her sides, feet slightly apart, the whole figure from the top of the head to the boots in frame with a margin of grey above the head and below the feet. Neutral mid-grey studio backdrop, flat even light, real fabric texture, plain documentary studio photograph.`（頭由伺服器裁掉，見 §2.3。）
- `back`（GPU 試算通過的版本，只參考 image 1）：`Full-body studio photograph of <體型> seen from directly behind, the person in image 1 turned completely away from the camera. We see the back of the head and the hair, the back of every garment — <服裝> — and the heels of the shoes. The arms hang relaxed at the sides with the backs of the hands toward the camera, feet slightly apart, the whole figure in frame with a margin of grey above the head and below the feet. Neutral mid-grey studio backdrop, flat even light, real fabric texture, plain documentary studio photograph.`
- 體型與服裝取自鎖定描述：第一句是外貌、其餘句是服裝時，依句子切開；切不出來時整段描述放在服裝的位置。
- `face`（GPU 試算通過的版本）：`Close-up studio photograph of <外貌>; <服裝的領口部分> shows at the neck. Head and shoulders, face turned slightly in three-quarter view, eyes looking just past the camera. Neutral mid-grey studio backdrop, soft flat light from one side, real unretouched skin with visible pores, fine vellus hair and natural asymmetry, a small catch-light in each eye. Plain documentary studio photograph, natural colour.`
- `plate`：`Wide three-quarter view of <描述>, empty of people, camera at eye height looking diagonally across the space, <light 原文第一句>, real materials, cinematic film still.`（不寫鏡頭與景深）
- `product`：`Photorealistic three-quarter overhead product photograph of <描述> on a neutral grey surface, soft directional light, isolated object, plain unbranded surfaces. <形狀鎖>`
- `stress`：素材的 `front` 或代表圖用法同 §3.3，再依 `variation` 從固定的 10 組（姿勢×光線）取一組，例如 `sitting on a crate, side light from a window`、`walking toward camera, overcast daylight`。`withAssets` 的角色也寫進同一句。
- 編輯（變體、反打）：
  ```
  Edit image 1. CHANGE: <change 或新視角的物件新位置>. PRESERVE EXACTLY: the face, hair, body proportions, clothing not named above, the backdrop, the light direction, the colour and grain. Only change what is named; everything else stays identical.
  ```
- 鎖定描述裡的 `seed:` 片段照舊移除。

面的參考計畫：`front` → [`face`]；`back` → [`face`]；`reverse`／`angle` → [`plate`]；`stress` → 本素材＋同框素材的計畫＋場景 `plate`；變體的面 → [基準同一面]。

### 3.5 參考計畫（`reference_plan`）
依本鏡提到的素材順序：角色 → `face`、`front`（沒有面時用參考圖欄）；場景 → `plate`（沒有時用參考圖欄）；道具 → `product`（沒有時用參考圖欄）。總數上限 6，超過時先捨棄道具，再捨棄角色的 `front`。被 `!@代號` 排除的不列入。每筆 `{assetCode, role: "character_face"|"character_body"|"location"|"prop", panel, url}`。

## 4. 介面（Cast & sets 編輯器、生成台）
- **角色**：大張編輯器的圖片區改成四格面條：Face｜Front (no head)｜Back｜Sheet；每格有「生成」（count 1–4）、候選小圖、選定。Sheet 格在三面都選好後自動出現，不能手動生成。缺前一面時按鈕停用並說明原因。
- **場景**：Plate｜Reverse｜Angle；**道具**：Product。
- **鎖**：在描述欄下方，依類型顯示：角色 Acting profile；場景 Location map、Light logic；道具 Shape lock；變體另有 Change。各自一個多行輸入，失焦時 `PATCH /meta`。
- **壓力測試**：按鈕開出設定（張數 4–10、同框素材、場景），結果以格狀列出，每張可標「認得出／認不出」，上方顯示 `7 / 10 recognizable`。
- **新增狀態變體**：造型的「＋」選單多一項 State（變體種類 `STATE`），要填 Change。
- **生成台的提示詞預覽**：多一段「參考圖」列出參考計畫的縮圖與用途，被捨棄的區塊以灰字列出。
- 所有新文字加 i18n 鍵（英文與繁中）。

## 5. Updraft 範例（取代 The Last Signal）
- 片名 **Updraft**：清晨峽谷上空的熱氣球。見習駕駛 Noa 第一次單飛，教官 Ines 在籃裡只看不出手；燃燒器熄火、氣球往岩壁掉，Ines 只說「Your balloon.」；Noa 手動點火，火焰轟起，氣球擦過崖頂升進陽光。全部原創，不寫年齡。
- 內容檔：`samples/updraft/production.json`（導演簡報、素材列與鎖、狀態變體、鏡頭列；由整合者撰寫）。種子程式讀這個檔與 `samples/updraft/manifest.json`（每格媒體對應的檔案與其生成紀錄：卡、種子、提示詞）。媒體在 GPU 驗收 G3 時由產品實際生成後放入 `samples/updraft/`。
- `zerofield_studio` 範本的五頁內容、`run_studio.py` 的種子、`server.py` 的展示專案標題、`samples/README.md`、README 的 Available now 都改為 Updraft。測試中寫死 The Last Signal 的地方一起更新。舊的 `samples/*.png|mp4` 與 `samples/generate.py` 移除（3D 預演 `previs_s03_blockout.mp4` 等若仍被測試或流程引用，改用 Updraft 的對應檔）。
- 質感範例牆（`ui/public/assets/look-samples/`）不在本規格範圍，維持原樣。

## 6. 分包與檔案所有權
| 包 | 模型 | 擁有的檔案 | 依賴 |
|---|---|---|---|
| **A 卡片與工作流** | Opus | `workflows/flux3_klein_reference_key.json`、`workflows/flux3_klein_edit.json`、`workflows/flux3_klein_soul_cast.json`、`workflows/cards/flux-reference-key.json`、`workflows/cards/flux-klein-edit.json`、`workflows/cards/flux-soul-cast.json`、`workflows/cards/ltx25-cinema.json`、`project_assistant/studio/card_engine.py`（`_build_card_form_values` 的 `prompt_compile` 與 `reference_plan`；空 ref 拔除）、`workflows/README.md`、`tests/test_spec21_cards.py` | 無 |
| **B 編譯器** | Opus | `project_assistant/studio/context_compiler.py`、新檔 `project_assistant/studio/shot_skeleton.py`（§3.2–3.5）、`tests/test_spec21_compile.py` | 無（依 §2.5 契約讀來源） |
| **C 素材 API** | Opus | 新檔 `project_docs/story_assets.py`（§2 全部）、`project_docs/story_openapi.py`（只加路由、`snapshot` 的 `asset_meta`、`LOOK_KINDS`、候選 `panel`、預覽回傳）、`project_docs/story_generation_options.py`（鏡頭圖片預設卡）、`tests/test_spec21_assets.py` | 無（依 §3.1 卡片 ID） |
| **D 介面** | Opus | `ui/src/AssetEditor.jsx`、`ui/src/WorldWall.jsx`、`ui/src/worldModel.js`、`ui/src/world.css`、新檔 `ui/src/assetPanels.js`、`ui/src/composer/` 中預覽的參考圖段、`ui/src/i18n/locales/en.json`、`zh-TW.json`、`ui/tests/spec21Assets.test.mjs` | 依 §2.2 契約；可先用假資料 |
| **E 內容** | 整合者 | `samples/updraft/production.json`、`docs/examples/UPDRAFT_BIBLE.md` | 無 |
| **F 範例替換** | Sonnet | `project_docs/templates.py`、`run_studio.py`（種子）、`server.py`（展示標題）、`samples/`（移除舊檔、`samples/README.md`）、受影響的測試、README 的範例段 | E、C |

共同規則：不碰其他包的檔案；不碰使用者未追蹤的 `docs/specs/SPEC_17_*`、`ui/prototypes/story-planning/`、`ui/tests/storyPlanningPrototype.test.mjs`；測試資料庫用本規格的拋棄式 PostgreSQL（埠 55481，每個代理自己的資料庫）；只跑自己新增與直接改動檔案的測試；不呼叫真實模型、GPU 或付費服務。

## 7. 驗收
**程式驗收（假模型）**
- A1 `flux-reference-key` 在 0、1、6 張參考圖時都編出合法的 API 圖（空位拔掉、不留懸空輸入）；寬高輸入生效。
- A2 `prompt_compile` 依卡片設定取對應的編譯文字；沒設定的卡行為不變（既有卡測試全過）。
- A3 影片骨架區塊順序、人數鎖、聲音鎖原文、台詞取用、`CHECK:`／`ORDER:`／`PHYSICS:` 段落正確；超出預算時依序整塊捨棄並回報。
- A4 首幀提示詞的圖片編號與參考計畫順序一致；上限 1,500 字元；不含否定句型（`no `、`not `、`without` 只允許出現在描述原文裡）。
- A5 參考計畫：角色兩張、場景一張、道具一張、上限 6、排除規則、捨棄順序。
- A6 `asset_meta` 讀寫、權限（唯讀成員不能改）、長度上限。
- A7 面的選卡與參考圖表（§2.3）、缺前一面時 409。
- A8 三視圖合成確定性、尺寸、寫入參考圖欄。
- A9 壓力測試排程、`variation` 0…n-1、結果標記。
- A10 `STATE` 變體建立與描述前綴、變體面走編輯卡。
- A11 介面：面條、鎖欄位、壓力測試格、預覽參考圖段；英繁兩語系鍵齊全。
- A12 Updraft 種子：新專案帶 Updraft 五頁內容，媒體依 manifest 填入，只填空格、不覆蓋使用者的編輯。

**GPU 驗收（使用者確認 GPU 空閒後）**
- G1 同一角色 4 張不同鏡頭的首幀，臉與服裝一致（人工判讀並截圖）。
- G2 同一鏡用完整骨架與縮短版各跑一次 LTX，比較遵從度，定出影片預算。
- G3 Updraft 全部素材與鏡頭由產品生成：每角色臉部候選 ≥4、三視圖、壓力測試 ≥8 張；每道具產品照 ≥2；每場景母版＋至少一個反打；每鏡首幀候選 ≥3、影片 ≥4 個 Take；匯出成片。
