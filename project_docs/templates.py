"""Reusable project archetypes and executable workflow definitions."""

def tab_specs(template: str, title: str, summary: str) -> list[tuple[str, str, str, str]]:
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
        ("overview", "總覽", "doc", f"# {title}\n\n{summary or '在這裡寫下專案目標、範圍與待確認事項。'}\n"),
    ]


COLUMN_TYPES = {
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
