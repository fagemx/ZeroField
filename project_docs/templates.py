"""Reusable project archetypes and executable workflow definitions."""

import re

_TABLE_RULE = re.compile(r"^\|(?:\s*:?-{3,}:?\s*\|)+\s*$")


def _structure_only(specs):
    """The template's pages without its sample content (R44-1/R44-2): doc pages start blank, so a story start
    becomes the working screenplay, and sheet tables keep their header row and column order but no sample rows.
    Flow pages describe the pipeline itself and stay as they are."""
    result = []
    for key, title, surface, md in specs:
        if surface == "doc":
            md = ""
        elif surface == "sheet":
            kept, in_body = [], False
            for line in md.split("\n"):
                if in_body and line.startswith("|"):
                    continue  # a sample row under the header rule
                in_body = bool(_TABLE_RULE.match(line))
                kept.append(line)
            md = "\n".join(kept)
        result.append((key, title, surface, md))
    return result


def tab_specs(template: str, title: str, summary: str, *, samples: bool = True) -> list[tuple[str, str, str, str]]:
    specs = _tab_specs(template, title, summary)
    return specs if samples else _structure_only(specs)


def _tab_specs(template: str, title: str, summary: str) -> list[tuple[str, str, str, str]]:
    if template == "zerofield_studio":
        return [
            ("director-brief", "Director Brief", "doc",
             f"# {title}\n\n{summary or 'Plan an original short film, direct each shot, and review agent proposals before applying changes.'}\n\n"
             "## Production Brief\n\n"
             "- Genre: Science-fiction noir\n- Working title: The Last Signal\n"
             "- Cast: Kael, an original courier carrying an analog recorder\n"
             "- Location: A quiet observatory after the rain\n"
             "- Optical package: 35mm anamorphic, restrained camera movement\n"
             "- Pacing: Establish the space, reveal the signal, hold on the decision\n\n"
             "## Scene\n\nKael enters the observatory and finds a recorder still receiving a signal. "
             "A distant light answers as Kael reaches for the dial.\n\n"
             "## Production Notes\n\nThe slate below is a planning template. Media cells are empty. "
             "Image and video generation require configured workers and validated workflows.\n"),
            ("soul-cast", "Soul Cast", "sheet",
             "# Soul Cast & Asset Lookbook\n\n"
             "| Asset ID | Character / Set | Locked Appearance Prompt / Seed | Reference Image | Voice / Audio Profile | Status | Notes |\n"
             "| --- | --- | --- | --- | --- | --- | --- |\n"
             "| CAST-01 | Kael | original fictional courier, charcoal field jacket, analog recorder; seed 48291 | | Calm, measured delivery | {{s:Queued}} | Establish a reference before generating shots. |\n"
             "| SET-01 | Observatory | original circular observatory, rain on glass, cool dawn, warm instrument lights | | Wind and a soft radio pulse | {{s:Queued}} | Keep the lighting direction consistent. |\n"),
            ("cinema-studio", "Cinema Studio", "sheet",
             "# Cinema Studio Multi-Shot Slate\n\n"
             "| Shot | Optical Rig (Camera & Lens) | Camera Motion | Action & Audio Prompt | Keyframe | Cinema Shot | Status | Director Take Notes | Previs | Actor Matte | Pose Skeleton |\n"
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
             "| S01 | ARRI Alexa 65 / 35mm Anamorphic | Slow Dolly Push-In | Establish the empty observatory as Kael enters. Wind against the glass. @CAST-01 @SET-01 | | | {{s:Queued}} | Establish the space and light direction. | | | |\n"
             "| S02 | RED V-Raptor / 85mm Prime | Static Tripod | Kael notices the pulsing recorder. A quiet radio signal becomes audible. @CAST-01 @SET-01 | | | {{s:Queued}} | Match CAST-01 wardrobe and recorder. | | | |\n"
             "| S03 | ARRI Alexa 65 / 35mm Anamorphic | Slow Dolly Push-In | Kael reaches for the dial as a light answers outside. Hold the final frame. @CAST-01 @SET-01 | | | {{s:Queued}} | Keep the decision readable. | | | |\n"),
            ("openjutsu-lab", "OpenJutsu Lab", "sheet",
             "# OpenJutsu V2V Planning Matrix\n\n"
             "| Clip ID | Jutsu Mode | Source Driving Video | Target Cast / Swap Prompt | Remastered Video | Split-Screen MP4 | Status | Notes |\n"
             "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
             "| VFX-01 | Motion Transfer | | Restage an original source clip in the observatory while preserving its action. @CAST-01 @SET-01 | | | {{s:Queued}} | Add a self-shot or appropriately licensed source in the video development phase. |\n"),
            ("comfy-pipeline", "Comfy Pipeline", "flow",
             "# Comfy Production Pipeline\n\n"
             "This editable pipeline describes the intended production stages. Configure compatible workers before running it. "
             "The English baseline does not include generation workflows or sample renders.\n\n"
             "| Stage | Worker Capability | Delivery | Status | Setup Notes |\n"
             "| --- | --- | --- | --- | --- |\n"
             "| 1. Optical Script Compiler | LLM | Structured shot prompts | {{s:Queued}} | Configure an open-weights language model. |\n"
             "| 2. Soul Cast & Keyframes | Image | Character references | {{s:Queued}} | Configure a validated FLUX workflow. |\n"
             "| 3. Cinema Studio Shots | Video | Reviewed cinema takes | {{s:Queued}} | Video integration is planned for the next phase. |\n"
             "| 4. OpenJutsu Remaster | Video | Remastered source clips | {{s:Queued}} | Requires source video and a validated V2V workflow. |\n"
             "| 5. Director Cut | Media Assembly | Assembled delivery | {{s:Queued}} | Requires approved generated media. |\n"),
        ]
    if template == "ai_drama":
        return [
            ("script", "第一集劇本與分場", "doc",
             f"# {title} — 劇本與分場設定\n\n{summary or '本頁由編劇與導演共同標註修改，定稿後交由右側代理或產線節點拆解為分鏡量產表。'}\n\n"
             "## 第一場：雨夜霓虹街道（外景／夜）\n\n"
             "- **主角（林默）**撐著透明雨傘站在全息廣告牌下，低頭看著手腕上的倒數計時器。\n"
             "- **台詞（林默）**：「距離記憶重置，只剩最後三分鐘。」\n\n"
             "| 場次項目 | 負責角色 | 狀態 | 請填確認備註 |\n"
             "| --- | --- | --- | --- |\n"
             "| 第一場對白與情緒定稿 | 導演／編劇 | {{s:已完成}} | 台詞節奏已確認 |\n"
             "| 拆解為 30 鏡分鏡表 | AI 編劇代理 | {{s:進行中}} | 對齊角色定妝 Seed |\n"),
            ("assets", "角色與場景資產表", "sheet",
             "# 角色與場景資產表\n\n"
             "| 資產代號 | 名稱 | 固定外觀 Prompt / Seed | 定妝預覽圖 | 配音音色 | 狀態 | 請填備註 |\n"
             "| --- | --- | --- | --- | --- | --- | --- |\n"
             "| CHAR-01 | 林默（男主） | cyberpunk detective, trench coat, rain, seed:48291 | 🖼️ [定妝圖:林默_正側視圖] | 冷靜低沉男聲 | {{s:已完成}} | 全劇鎖定臉部特徵 |\n"
             "| SCENE-01 | 雨夜霓虹街口 | neon hologram alley, wet reflections, 35mm anamorphic | 🖼️ [場景圖:霓虹街口_夜] | 雨聲＋低頻環境音 | {{s:已完成}} | 第一場主場景 |\n"),
            ("storyboard", "EP01 分鏡量產表", "sheet",
             "# EP01 分鏡量產表\n\n"
             "| 鏡號 | 景別／運鏡 | 畫面與台詞 | 生圖／生影片 Prompt | 首幀圖預覽 | 影片片段預覽 | 狀態 | 請填導演標註 |\n"
             "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
             "| S01 | 特寫 Push-in | 雨滴落在手腕倒數計時器跳動 | macro shot of holographic wrist timer in rain, CHAR-01 | 🖼️ [首幀:S01_手錶特寫] | 🎬 [影片:S01_4s.mp4] | {{s:已完成}} | 光影質感佳，過 |\n"
             "| S02 | 中景 Pan | 林默抬頭看向巨大的全息看板 | medium shot, CHAR-01 looking up at cyan neon sign, SCENE-01 | 🖼️ [首幀:S02_抬頭中景] | 🎬 [影片:待生成] | {{s:進行中}} | 首幀通過，待轉影片 |\n"
             "| S03 | 遠景 Crane | 街角黑影閃過，鏡頭拉高俯瞰整條街 | high angle crane shot, silhouette running in rain alley | 🖼️ [首幀:待重抽] | 🎬 [影片:待生成] | {{s:卡住}} | 街角太亮，請加逆光重抽 |\n"),
            ("pipeline", "影劇自動化產線", "flow",
             "# 劇本→分鏡→生圖→成片產線\n\n"
             "| 節點名稱 | 負責代理／角色 | 觸發與輸入 → 輸出 | 狀態 | 請填設定 |\n"
             "| --- | --- | --- | --- | --- |\n"
             "| 1. 劇本拆解分鏡 | 🤖 OpenAI · GPT-5.4 | 讀取 script 劇本 → 自動拆列寫入 storyboard 分鏡表 | {{s:已完成}} | 綁定 assets 角色代號 |\n"
             "| 2. 批次抽首幀圖 | 🎨 Image Limb · 即夢 / Flux / ComfyUI | 掃描 storyboard 待生圖列 → 產出首幀圖填回第 E 欄 | {{s:進行中}} | 每次平行跑 4 張供導演挑圖 |\n"
             "| 3. 圖生動態影片 | 🎬 Video Limb · Seedance / Kling / Veo | 首幀審核通過列 → 生成 4~5 秒動態影片填回第 F 欄 | {{s:進行中}} | 鎖定首尾幀與運鏡參數 |\n"
             "| 4. 配音與成片合成 | 🎞️ Media Limb · FFmpeg + TTS | 匯集已完成鏡號影片＋對白配音 → 輸出初剪 MP4 | {{s:未開始}} | 全部鏡號通過後自動串接 |\n"),
        ]
    if template == "art_studio":
        return [
            ("style-guide", "美術風格與規範書", "doc",
             f"# {title} — 美術規範書\n\n{summary or '定義色彩、光影、角色比例與交付格式規範。'}\n"),
            ("asset-sheet", "資產量產與審核表", "sheet",
             "# 資產量產與審核表\n\n"
             "| 資產編號 | 類別 | 規格描述與 Prompt | 草圖預覽 | 完稿預覽 | 狀態 | 請填主美回饋 |\n"
             "| --- | --- | --- | --- | --- | --- | --- |\n"
             "| ART-001 | 角色立繪 | 森林精靈弓箭手，半身立繪 2048x2048 | 🖼️ [草圖:ART-001] | 🖼️ [完稿:ART-001] | {{s:已完成}} | 配色通過 |\n"
             "| ART-002 | 場景原畫 | 古代遺跡大廳，黃昏斜射光 | 🖼️ [草圖:ART-002] | 🖼️ [完稿:待產出] | {{s:進行中}} | 柱子細節再加強 |\n"),
            ("art-flow", "自動跑圖與審核流", "flow",
             "# 自動跑圖與審核流\n\n"
             "| 節點名稱 | 負責代理／角色 | 觸發與輸入 → 輸出 | 狀態 | 請填設定 |\n"
             "| --- | --- | --- | --- | --- |\n"
             "| 1. 規範轉 Prompt | 🤖 OpenAI · GPT-5.4 | 讀取 style-guide 產生標準化生成詞 | {{s:已完成}} | 自動補齊負向詞 |\n"
             "| 2. 批次跑草圖 | 🎨 Image Limb · 即夢 / Flux / ComfyUI | 寫入 asset-sheet 草圖欄 | {{s:進行中}} | 固定 LoRA 權重 0.8 |\n"),
        ]
    if template == "marketing":
        return [
            ("overview", "專案總覽", "doc",
             f"# {title}\n\n{summary or '跨部門數據對齊、待辦追蹤與週報總結。'}\n"),
            ("daily-sheet", "每日成效日報", "sheet",
             "# 每日成效日報\n\n"
             "| 日期 | 渠道／項目 | 花費 | 營收 | ROAS | 狀態 | 請填備註 |\n"
             "| --- | --- | --- | --- | --- | --- | --- |\n"
             "| 10/16 | Meta | 12000 | 18600 | =D1/C1 | {{s:已完成}} | 首日測試數據 |\n"
             "| 10/17 | Google | 8500 | 11900 | =D2/C2 | {{s:進行中}} | 待填寫 |\n"),
            ("agent-flow", "數據診斷工作流", "flow",
             "# 數據診斷工作流\n\n"
             "| 節點名稱 | 負責代理／角色 | 觸發與輸入 → 輸出 | 狀態 | 請填設定 |\n"
             "| --- | --- | --- | --- | --- |\n"
             "| 1. 讀取日報數據 | 🤖 OpenAI · GPT-5.4 | 讀取 daily-sheet 最新列 | {{s:已完成}} | 每日 09:30 |\n"
             "| 2. 異常診斷提案 | ✨ Google · Gemini 2.5 Pro | 產生 ProposalCard 寫回 overview | {{s:進行中}} | ROAS 低於門檻時提醒 |\n"),
        ]
    return [
        ("overview", "Overview", "doc", f"# {title}\n\n{summary or 'Define the production goal, scope, and decisions to review.'}\n"),
    ]


COLUMN_TYPES = {
    "soul-cast": ["text", "text", "text", "image", "text", "status", "text"],
    "cinema-studio": ["text", "text", "text", "text", "image", "video", "status", "text", "video", "video"],
    "openjutsu-lab": ["text", "text", "video", "text", "video", "video", "status", "text"],
    "assets": ["text", "text", "text", "image", "text", "status", "text"],
    "storyboard": ["text", "text", "text", "text", "image", "video", "status", "text"],
    "asset-sheet": ["text", "text", "text", "image", "image", "status", "text"],
    "daily-sheet": ["text", "text", "number", "number", "formula", "status", "text"],
}


def configure_doc(key, doc):
    for table in doc.get("content", []):
        if table.get("type") == "table" and key in COLUMN_TYPES:
            table.setdefault("attrs", {})["column_types"] = COLUMN_TYPES[key]
    return doc


def flow_specs(template):
    def node(identifier, title, capability, scope, prompt, inputs, target, x, source=None):
        return {"id": identifier, "title": title, "capability": capability, "scope": scope,
                "prompt": prompt, "input_tabs": inputs, "target": target,
                "write_mode": "proposal", "x": x, "y": 80,
                **({"row_source": {"tab_key": source}} if source else {})}
    def chain(nodes):
        return {"nodes": nodes, "edges": [{"source": a["id"], "target": b["id"]} for a, b in zip(nodes, nodes[1:])]}
    if template == "zerofield_studio":
        return {"comfy-pipeline": chain([
            node("script", "Optical Script Compiler", "llm", "once",
                 "Read the director brief and cast references. Propose structured shot prompts for the cinema slate. "
                 "Preserve shot IDs and cast continuity. Leave media empty and use Queued for unproduced shots. "
                 "Return table_id/row_edits/new_rows JSON for review.",
                 ["director-brief", "soul-cast", "cinema-studio"], {"tab_key": "cinema-studio"}, 40),
            node("image", "Soul Cast & Keyframes", "image_gen", "rows",
                 "Generate an original reference using the locked appearance prompt. Return asset_url for review.",
                 ["soul-cast", "director-brief"], {"tab_key": "soul-cast", "col_index": 3}, 440, "soul-cast"),
            node("cinema", "Cinema Studio Shots", "video_gen", "rows",
                 "Use the shot prompt, optical rig, and camera motion with approved cast references. Return asset_url for review.",
                 ["cinema-studio", "soul-cast"], {"tab_key": "cinema-studio", "col_index": 5}, 840, "cinema-studio"),
            node("v2v", "OpenJutsu Remaster", "video_gen", "rows",
                 "Use the source driving video and target prompt. Requires a configured V2V workflow. Return asset_url for review.",
                 ["openjutsu-lab", "soul-cast"], {"tab_key": "openjutsu-lab", "col_index": 4}, 1240, "openjutsu-lab"),
            node("assemble", "Director Cut", "media_assemble", "aggregate",
                 "Assemble approved cinema shots in slate order. Append the delivery link to the director brief for review.",
                 ["cinema-studio"], {"tab_key": "director-brief", "kind": "doc", "mode": "append"}, 1640, "cinema-studio"),
        ])}
    if template == "ai_drama":
        return {"pipeline": chain([
            node("split", "劇本拆解分鏡", "llm", "once",
                 "讀取劇本與角色設定。將劇本拆成可製作鏡頭，更新現有對應鏡號，缺少的鏡頭使用 new_rows 新增。"
                 "每列依序為鏡號、景別／運鏡、畫面與台詞、生圖／影片 Prompt、首幀圖、影片、狀態、導演備註。"
                 "媒體留空，狀態未開始。保留角色代號、Seed 與連續性。只回傳 table_id/row_edits/new_rows JSON。",
                 ["script", "assets", "storyboard"], {"tab_key": "storyboard"}, 40),
            node("image", "角色一致性首幀圖", "image_gen", "rows",
                 "依本鏡第 4 欄 Prompt 及 assets 角色固定外觀生成首幀圖。回傳 asset_url。",
                 ["storyboard", "assets"], {"tab_key": "storyboard", "col_index": 4}, 440, "storyboard"),
            node("video", "首幀轉動態影片", "video_gen", "rows",
                 "使用上游審核通過的首幀與本鏡運鏡 Prompt 生成影片片段。回傳 asset_url。",
                 ["storyboard", "assets"], {"tab_key": "storyboard", "col_index": 5}, 840, "storyboard"),
            node("assemble", "全鏡頭配音合成", "media_assemble", "aggregate",
                 "依分鏡表順序串接所有通過審核的影片。有同鏡配音時混入音軌，輸出 MP4 成片。",
                 ["storyboard"], {"tab_key": "deliverables", "kind": "doc", "mode": "append"}, 1240, "storyboard"),
        ])}
    if template == "art_studio":
        return {"art-flow": chain([
            node("prompt", "規範轉生成指令", "llm", "rows",
                 "依美術規範與主美回饋，補強本列第 3 欄生成 Prompt。回傳 text，保留資產身分與規格。",
                 ["style-guide", "asset-sheet"], {"tab_key": "asset-sheet", "col_index": 2}, 40, "asset-sheet"),
            node("image", "批次草圖與審核", "image_gen", "rows",
                 "依本列 Prompt 與美術規範生成草圖，回傳 asset_url。",
                 ["style-guide", "asset-sheet"], {"tab_key": "asset-sheet", "col_index": 3}, 440, "asset-sheet"),
        ])}
    if template == "marketing":
        return {"agent-flow": chain([
            node("diagnose", "日報異常診斷", "llm", "once",
                 "讀取日報的真實數字與公式，檢查花費、營收與 ROAS，列出需追蹤的異常。回傳 text。",
                 ["daily-sheet"], {}, 40),
            node("report", "週報與總覽提案", "llm", "once",
                 "根據上游診斷與日報，撰寫有數據佐證的繁體中文週報與下一步。回傳 text。",
                 ["daily-sheet", "overview"], {"tab_key": "overview", "kind": "doc", "mode": "append"}, 440),
        ])}
    return {}
