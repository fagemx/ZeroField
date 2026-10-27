# SPEC_19 附錄草稿 — 片型、年代、節奏、色調、燈光選項清單（待使用者確認）

> **狀態**：草稿（2026-10-27），等使用者確認。對應 [`SPEC_19_SHOT_COMPOSER_ADOPTION_AND_FILM_PANEL.md`](./SPEC_19_SHOT_COMPOSER_ADOPTION_AND_FILM_PANEL.md) §7 待決第 5 項。
> **確認前不做的事**：不產範例圖、不寫 `project_docs/look_catalog.json`、不加 i18n 鍵、不改任何程式。使用者回覆「刪／加／改名」後，才依定稿清單進包 C。
> **參考來源**：Higgsfield Cinema Studio 4.0 的 Genre／Era／Tempo／Color palette／Lighting 分頁（`docs/HIGGSFIELD_FEATURE_INVENTORY_2026-10-18.md` 只記錄分頁存在，沒有列出選項值）。本清單只借「分哪幾類」，選項與名稱全部自擬。

這份清單是 SPEC_19 質感目錄（§4.3）的選項草案，使用者確認之後，才會依它自製範例圖（§4.4）與寫入目錄檔。命名規則有三條：一，名稱一律原創，不使用真實電影、導演、演員、攝影師、品牌或作品名稱（`docs/DESIGN_AND_DEV_GUIDELINES.md` §3.2、SPEC_19 固定決策 11），也避開會讓人直接聯想到某部作品的字眼；二，`id` 用小寫連字號，穩定不改（存進集數設定與 `meta_<shotId>`），中文名與英文標籤可以日後調整；三，每一類的第一個選項固定是 Auto。每個選項除了名稱，還帶一句 `promptText`，寫成「看得到的畫面」：光從哪來、影子多硬、顏色怎麼分布、鏡頭怎麼動，而不是「陰鬱」「緊張」這類形容詞，也不重複類型名稱本身。原因是 Higgsfield 的 A/B 實測顯示，只送「Noir」「Contre jour」這類標籤名稱，模型不會照做，只有色碼會生效（SPEC_19 固定決策 6）；所以我們送出的是描述句，色調再另外附色碼。

## 數量一覽

| 種類 | `look` 欄位 | 含 Auto | 實際選項 | 選擇器（SPEC_19 §3.3） |
|---|---|---|---|---|
| 類型 | `genre` | 8 | 7 | 左右輪播 |
| 年代 | `era` | 6 | 5 | 刻度（表格順序即刻度順序，舊到新） |
| 節奏 | `tempo` | 5 | 4 | 左右輪播（表格順序由靜到動） |
| 色調 | `palette` | 12 | 11 | 圖卡格線加搜尋與排序 |
| 燈光 | `light` | 8 | 7 | 圖卡格線加搜尋與排序 |

## 寫法約定（實作時照這幾條）

- **Auto**：`promptText` 為空，編譯時不寫進提示詞，也沒有色碼；範例牆用抽象紋理圖表示（SPEC_19 §3.3）。
- **類型、年代、節奏三類合成 `Film:` 一行**：三段 `promptText` 都寫成小寫開頭、不含句號的子句，編譯時用 `; ` 串接（`compile_look` 回傳的 `film` 欄位，§4.3）。這個串接規則是我為了讓三段能接在一起而提的假設，SPEC_19 沒有明寫，確認後要補進 §4.3。
- **色調的 `promptText` 只寫顏色怎麼分布**；`hex` 由編譯器接在後面（`... palette #2E3A4A, #5B6F86 ...`）。`hex` 第一色是主色，指畫面中佔比最大的色，不一定最亮；最多 12 色，這份草稿每組 5–6 色。
- **燈光只寫光源位置、硬度、陰影方向，不指定色相**。光的顏色交給色調，避免「檯燈」配上「冰川藍」時，兩段文字互相打架。
- **年代只管影像質感**：只寫鏡頭與感光材料的外觀（顆粒、光暈、邊角、掃描線），不寫色相，也不寫時代物件（服裝、車輛、機器）；顏色交給色調，時代物件交給分鏡本身。
- 每段 `promptText` 約 25–50 個英文字；五類全選時合計約 150–200 字（見最後的問題 7）。

---

## 1. `genre` 類型（含 Auto 共 8 個）

類型管的是構圖習慣與鏡頭距離，不管劇情內容，所以每一條都不強迫畫面出現特定事件，只描述框怎麼取、光怎麼放、空間怎麼用。

| `id` | 中文名 | English label | `promptText` | 為什麼放這個 |
|---|---|---|---|---|
| `auto` | 自動 | Auto | （空，不寫入提示詞） | 不設定也能生成；由分鏡本身的文字決定。 |
| `rain-mystery` | 雨夜謎案 | Rain-soaked mystery | wet streets and window glass catching small bright reflections, subjects framed at eye level in medium and close shots, most of the frame left in shadow with one small pool of light, rain streaks visible against lit windows, doorways and railings crossing the foreground | 範例《The Last Signal》的雨夜段落；「大片陰影加一小塊光」是只送類型名稱時模型最不容易自己做到的構圖。 |
| `quiet-drama` | 靜默人情 | Quiet drama | one or two people in a plain room framed from the waist up, faces held in close view for long moments, everyday objects such as cups, coats and chairs behind them, almost no camera movement, a little empty space left beside whoever is speaking | 人物對話的基本盤；和雨夜謎案相比，是「亮、少動、靠臉」的一端。 |
| `creeping-unease` | 暗處不安 | Creeping unease | wide frames with large empty areas of dark space, a doorway or corridor at the far end of the image, the subject small and off to one side, something partly hidden at the very edge of the frame, few low light sources, camera moving very slowly toward the dark area | 留白與邊緣構圖；適合等待信號那一類的鏡頭。 |
| `instrument-room-sf` | 機房科幻 | Instrument-room sci-fi | rooms full of dials, screens and cables laid out in straight lines and symmetrical rows, a person small beside large machinery, light from screens falling across nearby surfaces, wide establishing frames followed by tight shots of hands and displays | 範例的天文台控制室與盤式錄音機這類儀器場景。 |
| `long-road` | 長途遠行 | Long road | wide landscapes with a small figure or vehicle crossing the frame, horizon placed very low or very high so sky or ground fills most of the image, a road or ridge line leading into the distance, camera tracking beside or behind the traveler, dust or mist in the air | 補外景與大空間；例如信使前往天文台的路上。 |
| `field-record` | 田野紀錄 | Field record | camera held at shoulder height with a slight natural sway, only the light that already exists in the place, people going about a task while the frame follows a beat late, activity visible in the background, heads sometimes cut off at the frame edge | 手持、現場光的一端，和其他幾個穩定構圖形成對比；之後有人做紀錄式短片時也用得上。 |
| `bright-caper` | 輕快鬧劇 | Bright caper | evenly lit sets in daylight, wide lens close to the subjects so edges stretch slightly, props and hand gestures large in the frame, centered or symmetrical compositions, quick small reactions held in tight shots, uncluttered backgrounds | 明亮、廣角、動作大的一端，避免整份清單都偏暗。 |

## 2. `era` 年代（含 Auto 共 6 個）

「年代」在這裡指**影像質感的年代**：鏡頭、感光材料與色彩呈現的樣子。表格順序即刻度順序（舊到新），Auto 不在刻度上，是獨立的一格。

| `id` | 中文名 | English label | `promptText` | 為什麼放這個 |
|---|---|---|---|---|
| `auto` | 自動 | Auto | （空，不寫入提示詞） | 不設定時沿用模型預設質感。 |
| `early-lens` | 老鏡頭年代 | Early-lens era | soft glow spreading from bright spots, corners darker than the center, low contrast with milky blacks, faint brightness flicker from frame to frame, small dust specks drifting across the image | 刻度最舊的一端；視覺上和「顆粒膠片」拉開距離，不依賴黑白（顏色交給色調）。 |
| `saturated-print` | 彩印年代 | Saturated-print era | colors at very high saturation with strong contrast between hues, soft diffusion on highlights, skin glowing in even bright light, stage-like lighting with few deep shadows | 和暗調、低彩度的選項相反，是高彩度、均勻打光的一端；例如回憶片段。 |
| `grain-film` | 顆粒膠片 | Grain-film era | fine film grain visible across dark areas, soft glow around bright lights, blacks slightly lifted to dark grey, gentle softening toward the frame corners, midtones leaning warm | 最多人會想要的「有質感的舊影像」，風險最低的中間選項。 |
| `tape-era` | 磁帶年代 | Tape era | soft low-resolution detail, faint horizontal scan lines, color bleeding at the edges of bright objects, highlights blooming into their surroundings, a slight wobble along the top of the frame | 錄影帶式的畫面，例如監視畫面或舊錄像；刻意不用任何格式或品牌名。 |
| `clean-digital` | 當代清透 | Clean digital era | sharp detail from edge to edge, no visible grain, full range from deep shadow to bright highlight without clipping, skin tones as the eye sees them, no lens flare | 刻度最新的一端；等於「乾淨無濾鏡」，給想自己用色調與燈光堆質感的人。 |

## 3. `tempo` 節奏（含 Auto 共 5 個）

節奏寫的是**一鏡（4–8 秒）之內看得到的動靜**，不是剪輯速度；排列順序由最靜到最動。

| `id` | 中文名 | English label | `promptText` | 為什麼放這個 |
|---|---|---|---|---|
| `auto` | 自動 | Auto | （空，不寫入提示詞） | 不設定時由分鏡的動作描述決定。 |
| `still-hold` | 靜止凝視 | Still hold | camera locked on a tripod for the whole shot, people moving slowly inside the frame, long pauses between small actions, no camera movement | 最靜的一端；等待、凝視的鏡頭。 |
| `slow-drift` | 緩慢漂移 | Slow drift | camera creeping forward or sideways slower than a walking pace, people taking small steps one at a time, background objects sliding slowly across the frame | 最常用的慢節奏，對應運鏡裡的緩推、緩移。 |
| `hold-then-burst` | 靜待突發 | Hold, then burst | almost no movement for most of the shot, then a sudden fast push of the camera or a quick movement by the subject in the last second | 單鏡內前靜後動的選項，適合 4–8 秒的短鏡頭；模型會不會照做不確定，要靠範例實測才知道。 |
| `rush` | 急促連動 | Rush | camera moving fast with quick pans and push-ins, people acting at a fast pace, a new action starting about every second, tight framing with abrupt changes of direction | 最動的一端；追逐、爭執、混亂場面。 |

## 4. `palette` 色調（含 Auto 共 12 個）

`hex` 欄第一色是主色。`promptText` 只描述顏色在畫面上的分布，色碼由編譯器附在後面。

| `id` | 中文名 | English label | `promptText` | `hex` | 為什麼放這個 |
|---|---|---|---|---|---|
| `auto` | 自動 | Auto | （空，不寫入提示詞） | — | 不設定時顏色由場景描述決定。 |
| `midnight-slate` | 午夜石板 | Midnight slate | shadows and backgrounds in deep slate blue, midtones in muted steel blue, highlights kept a pale cool grey, only small lamp-lit spots breaking the scheme | `#2E3A4A` `#5B6F86` `#1B2330` `#8FA3B8` `#D8E0E8` `#C9953F` | 《The Last Signal》雨夜天文台的首選；與介面 6C 午夜藍灰同一色系，前兩色與 SPEC_19 §4.3 的範例相同。 |
| `lamp-amber` | 燈下琥珀 | Lamp amber | lit areas in amber and honey, mid-shadows in reddish brown, deepest shadows near black with a brown tint, skin and wood carrying most of the orange, no blue anywhere in the frame | `#C98A3D` `#8A4B2A` `#3B2A24` `#E8C48A` `#1E1A1A` | 與午夜石板最大的反差；室內、控制室、檯燈場景。 |
| `verdigris-rust` | 銅綠與鏽 | Verdigris and rust | shadows and backgrounds pushed toward green-blue, skin, brick, metal and lights pushed toward rust orange, the two hues kept apart so each object reads as one or the other, highlights a pale sand | `#2F6B6B` `#B5602F` `#1C2B2E` `#D9A06A` `#6FA3A0` | 互補色分區（冷背景加暖主體）的常見配法，用我們自己的名稱與色碼。 |
| `bone-ink` | 骨白墨黑 | Bone and ink | image reduced to black, warm paper white and greys with no other hue, large areas of solid black, bright areas limited to faces and light sources, a hard boundary between lit and shadowed zones | `#1A1A1A` `#E9E4D8` `#8C8780` `#4A4742` `#B8B3A8` | 單色一格；測試「幾乎沒有彩度」時模型是否真的去色，也最適合配頂光硬影。 |
| `wet-glass-neon` | 濕玻璃霓光 | Wet-glass neon | background in near-black blue, magenta and cyan lights from signs and screens, reflections of those two colors stretched across wet ground and glass, faces split with magenta on one side and cyan on the other, small white points for lamps | `#101426` `#E0368B` `#28D3E6` `#5B3FA8` `#F2F2F7` | 雨夜街道的高彩度版本；和午夜石板形成「同一場戲的兩種拍法」。 |
| `moss-fog` | 苔霧 | Moss fog | foliage and walls in muted olive and moss green, distant areas fading to pale grey-green as if behind thin fog, shadows in dark green-black, almost no saturated color except one small detail such as a lit window | `#6E7F63` `#3F4D3F` `#AEB8A5` `#D6DACD` `#232A24` | 低彩度的綠；外景、荒地、長途遠行的底色。 |
| `salt-washed` | 鹽洗褪色 | Salt-washed | colors washed out to pale sand, grey and faded blue, bright overexposed sky and surfaces, skin slightly pale, dark areas lifted to mid-grey instead of black, thin traces of color only in clothing and objects | `#D9D6CC` `#B7B2A5` `#8E9AA0` `#5E6A70` `#E8D9B5` | 高調、褪色；和所有「暗」的選項相反，給白天、海邊、舊照片感。 |
| `ember-red` | 炭火暗紅 | Ember red | most of the frame in black and deep maroon, bright areas in glowing orange-red as if lit by fire or heater coils, faces catching red-orange on the lit side, object edges outlined in thin orange, no green or blue | `#8E1F1F` `#3A0F10` `#D9593D` `#1A0C0C` `#F0B58A` | 單一強色加黑；警報、爭執、危險場面。 |
| `glacier-blue` | 冰川藍白 | Glacier blue | bright pale blue and white across most of the frame, shadows in clear mid blue rather than grey, snow-white highlights, deep navy only in small dark objects, skin slightly cool | `#BFD9E8` `#6FA3C7` `#2E5C85` `#F2F7FA` `#0F2A43` | 冷色但明亮，和午夜石板（冷色但暗）對照；雪地、醫療、空曠室內。 |
| `plum-twilight` | 梅紫暮色 | Plum twilight | sky and background in dusty purple, shadows in dark violet, highlights in pale pink, a thin band of peach near the horizon or around lamps, no pure black anywhere | `#5A3E6B` `#2A1F3A` `#A78BB8` `#E6C9D9` `#F0A58A` | 黃昏到夜之間的過渡色；例如從日落進到雨夜的轉場鏡頭。 |
| `sugar-paper` | 糖紙日光 | Sugar-paper daylight | bright daylight with pastel pink, sky blue, butter yellow and mint in broad even areas, white highlights, soft thin shadows in pale lilac, no black areas | `#F4B6C2` `#A8D8EA` `#FFE9A8` `#FFFFFF` `#7FB7A4` | 輕快、粉彩的一格，對應輕快鬧劇；避免整份色調都偏暗偏重。 |

## 5. `light` 燈光（含 Auto 共 8 個）

只寫光源位置、硬度與陰影方向，不指定色相（見「寫法約定」）。

| `id` | 中文名 | English label | `promptText` | 為什麼放這個 |
|---|---|---|---|---|
| `auto` | 自動 | Auto | （空，不寫入提示詞） | 不設定時由場景描述決定。 |
| `window-side` | 側窗柔光 | Side-window soft light | soft daylight entering from a window on one side of the frame, a single key light, the far side of faces and objects falling into deep shadow with a soft edge, a faint bounce of light from the wall on the shadow side | 人物近景的基本打法；與 SPEC_19 §4.3 範例同一種光。 |
| `practical-lamp` | 檯燈光圈 | Practical lamp pool | one lamp visible in the frame is the only light, a small pool of light on nearby faces, hands and table, shadows softening where the pool ends, the rest of the room dropping to near black | 光源就在畫面裡，模型最容易照做；搭配雨夜謎案與燈下琥珀。 |
| `hard-top` | 頂光硬影 | Hard overhead light | a hard light directly overhead, sharp-edged shadows under brows, nose and chin, eye sockets dark, a tight circle of light on the floor or table, everything outside the circle black | 最硬的一種；質詢、審視、單人孤立的鏡頭。 |
| `backlight-rim` | 逆光輪廓 | Backlit rim | strong light placed behind the subject facing the camera, a thin bright rim along hair and shoulders, the face in shadow with only a faint fill from the front, haze or dust in the air showing the beam | 輪廓大於細節；窗前、門口、圓頂縫隙漏光的鏡頭。 |
| `instrument-glow` | 儀表面光 | Instrument glow | faces and hands lit from below and in front by screens and indicator panels, soft-edged light with a short reach, small points of indicator lights in the dark behind, no other light source in the room | 天文台控制室這類場景專用；是「光來自畫面裡的機器」的版本。 |
| `overcast-flat` | 陰天均光 | Overcast even light | even light from a cloudy sky coming from above and all around, almost no cast shadows, soft gradients on faces, surfaces readable everywhere including dark corners, no bright highlights and no lens flare | 最柔、對比最低；外景白天，也是最不會出錯的備用選項。 |
| `low-sun` | 低角日光 | Low sun | sun low near the horizon on one side, light raking across the ground and walls, long stretched shadows pointing away from the sun, bright edges on the lit side of faces, the far side in shade, haze in the air | 日出日落與長陰影；例如在天文台頂上看日落的鏡頭。 |

---

## 6. 要使用者決定的問題

1. **每類數量合適嗎？** 目前（不含 Auto）類型 7、年代 5、節奏 4、色調 11、燈光 7，合計 34 個選項，要做 34 張範例圖，另有 5 個 Auto 的抽象紋理圖（§3.3）。範例圖由 FLUX 3 Klein 自製（§4.4），張數會直接決定包 C 的工時；想少做，優先砍色調與燈光各兩個。
2. **有沒有想刪、想加、想換名字的？** 我備了幾個沒放進去的候選，要的話直接說名字，我補 `promptText` 與色碼：
   - 類型：`close-warmth`（近身暖意）——特寫、淺景深、近處暖色檯燈的親密場景，目前沒有戀愛或家庭向的類型。
   - 色調：`dry-ochre`（乾土赭黃）——乾燥日光下的赭黃與土褐，目前沒有沙漠或荒地色，`moss-fog` 與 `salt-washed` 只能勉強頂替。
   - 燈光：`sign-spill`（招牌溢光）——街邊招牌的兩種彩光從兩側打在臉上；我拿掉是因為它和 `wet-glass-neon` 重疊。
   - 節奏：`steady-walk`（平穩步行）——我拿掉是因為它跟 Auto 幾乎沒有差別。
3. **名稱好不好懂？** 我最擔心這幾個：`機房科幻`（是否太像在講類型而非構圖）、`彩印年代`、`磁帶年代`（刻意不用「膠片機型」「錄影格式」這類品牌詞，代價是第一眼看不懂）。範例圖出來之後，名稱和縮圖放在一起大概會好懂，但你可以先改。另外，中文名稱裡用「科幻」「鬧劇」這種通用類型詞是否接受？我認為通用詞不算作品名，但你可能想更嚴格。
4. **「年代」只管影像質感，不管故事年代，可以嗎？** 如果你要的是故事設定年代（戰後、近未來、舊時代），要另外列，而且會和色調、燈光互相牽動，建議放第二版。
5. **燈光不寫色相、全交給色調，可以嗎？** 好處是燈光與色調不會互相衝突；代價是「檯燈光圈」不會自帶暖色，使用者要同時選「燈下琥珀」才暖。
6. **主色定義與色票數：** 我把「第一色」定義為畫面佔比最大的色，每組 5–6 色。要不要多放幾色（上限 12）？色碼我是憑色感排的，沒有拿實際生成結果驗證；範例圖出來後，再依實際畫面微調一輪色碼比較準。
7. **提示詞長度。** 五類全選時，`Film:`、`Color:`、`Lighting:` 三行合計約 150–200 個英文字，再加上使用者自己寫的內容，LTX-2.5 的有效提示詞可能被稀釋。要不要在範例實測時，另外準備一組每條縮到 15 字左右的精簡版，由實測結果決定用哪一版？
8. **`Film:` 一行的串接規則**（寫法約定第二條）：類型、年代、節奏用 `; ` 串成一行，這是我補的假設，SPEC_19 §4.3 沒有寫，要不要照這樣定？
9. **名稱的原創性只靠我自己的比對。** 我沒有上網搜尋逐一檢查，只憑已知的作品名稱、人名、品牌名排除。你若要保險，可以在定稿前挑出最像專有名詞的幾個（例如「苔霧」「糖紙日光」「梅紫暮色」）再查一輪。
