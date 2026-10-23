"""Bounded, deterministic screenplay preparation. Never calls a model or provider."""
from __future__ import annotations

import re

SOURCE_MODES = {"auto", "idea", "novel", "script"}
BREAKDOWN_MODES = {"auto", "scene", "cinematic", "cinematic_multi"}
TAG = re.compile(r"@?\b((?:CAST|SET|LOC|PROP|STYLE)-\d+(?:[:#][a-z0-9_-]+)?)\b", re.I)
HEADING = re.compile(r"^\s*(?:#{1,6}\s*)?(?:Scene\s*\d+|場景\s*[一二三四五六七八九十\d]+|场景\s*[一二三四五六七八九十\d]+|INT\.|EXT\.)", re.I | re.M)
DECLARATION = re.compile(r"^\s*(?:Character|角色|Prop|道具|Environment|Style)\s*[:：]", re.I)
QUOTED = re.compile(r'["“「]([^"”」\n]+)["”」]')
SPEAKER = re.compile(r'^\s*(@?CAST-\d+(?:[:#][\w-]+)?|[A-Za-z][A-Za-z\s\'-]{0,35}|[\u3400-\u9fff]{1,12})\s*[:：]\s*(.*)$')


def asset_code(value):
    return value.lstrip("@").upper().replace("#", ":")


def speaker_name(value):
    value = re.sub(r"(?:說道|说道|問道|问道|回答|說|说|問|问)$", "", value.strip())
    return re.sub(r"\s+(?:said|asked|whispered|replied|shouted)$", "", value, flags=re.I).strip()


def source_mode(raw_text, mode="auto"):
    if mode != "auto":
        return mode
    if HEADING.search(raw_text):
        return "script"
    return "idea" if len(raw_text) < 240 and not QUOTED.search(raw_text) and "\n\n" not in raw_text else "novel"


def character_details(content):
    """Explicit declarations and speaker cues win; prose recognition is conservative."""
    found = []
    for line in content.splitlines():
        declaration = re.match(r"\s*(?:Character|角色)\s*[:：]\s*(.+)", line, re.I)
        if declaration:
            value = declaration[1].strip()
            tag = TAG.search(value)
            code = asset_code(tag[1]).split(":")[0] if tag and tag[1].upper().startswith("CAST") else None
            value = TAG.sub("", value).strip(" -:：")
            name = re.split(r"[（(]", value, maxsplit=1)[0].strip()
            traits = re.search(r"[（(](.*?)[）)]", value)
            found.append((name or code or "Protagonist", traits[1].strip() if traits else "", code))
        elif (cue := SPEAKER.match(line)) and (QUOTED.search(cue[2]) or re.fullmatch(r"[A-Z][A-Z '\-]{1,35}", cue[1])) and not DECLARATION.match(line):
            if not TAG.fullmatch(cue[1].strip()):
                found.append((speaker_name(cue[1]), "", None))
    # Names adjacent to speech/action verbs avoid mistaking every sentence opening for a name.
    for match in re.finditer(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)?)\s*\(([^)\n]{1,300})\)\s+(?:said|asked|whispered|replied|shouted|walked|entered|turned|ran)\b|\b([A-Z][a-z]+(?: [A-Z][a-z]+)?),\s+(?:an?\s+)?([^,\n]{1,160}),\s+", content):
        found.append((match[1] or match[3], (match[2] or match[4]).strip(), None))
    for match in re.finditer(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)?)\s+(?:said|asked|whispered|replied|shouted|walked|entered|turned|ran)\b|([\u3400-\u9fff]{2,4})(?:說道|问道|說|说|問|問道|回答)[：:]?\s*[\"“「]", content):
        found.append((match[1] or match[2], "", None))
    result = {}
    for name, traits, code in found:
        key = name.casefold()
        old = result.get(key)
        if not old or traits or code:
            result[key] = (name, traits or (old[1] if old else ""), code or (old[2] if old else None))
    return list(result.values())


def allocated_characters(content, fallback=None):
    people = character_details(content) or (fallback or [])
    reserved = {code for _, _, code in people if code}
    # Anonymous explicit tags are paired by order with untagged declarations before new IDs.
    available = list(dict.fromkeys(asset_code(m[1]).split(":")[0] for m in TAG.finditer(content)
                                   if m[1].upper().startswith("CAST") and asset_code(m[1]).split(":")[0] not in reserved))
    result = []
    for name, traits, code in people:
        if code is None:
            if available:
                code = available.pop(0)
            else:
                index = 1
                while f"CAST-{index:02d}" in reserved:
                    index += 1
                code = f"CAST-{index:02d}"
            reserved.add(code)
        result.append((name, traits, code))
    return result


def screenplay_markdown(content):
    """Keep screenplay cues separate when Markdown would collapse soft line breaks."""
    result, paragraph = [], []
    def flush():
        if paragraph:
            result.append(" ".join(paragraph))
            paragraph.clear()
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            flush()
        elif HEADING.match(stripped):
            flush()
            result.append(stripped if stripped.startswith("#") else "## " + stripped)
        elif DECLARATION.match(stripped) or re.match(r"(?:Shot\s*\d+\s*[:：]|[-*]\s)", stripped, re.I) or (SPEAKER.match(stripped) and QUOTED.search(stripped)):
            flush()
            result.append(stripped)
        else:
            paragraph.append(stripped)
    flush()
    return "\n\n".join(result)


def adapt_source_to_script(raw_text, mode="auto", target_scenes=3, style_name="Sci-Fi Noir Anamorphic"):
    if not isinstance(raw_text, str) or not raw_text.strip() or len(raw_text) > 500000:
        raise ValueError("sourceText must contain 1–500,000 characters.")
    if not isinstance(mode, str) or mode not in SOURCE_MODES:
        raise ValueError("Unknown sourceMode.")
    if type(target_scenes) is not int or not 1 <= target_scenes <= 12:
        raise ValueError("targetScenes must be an integer between 1 and 12.")
    if not isinstance(style_name, str) or not style_name.strip() or len(style_name) > 200:
        raise ValueError("style_name must contain 1–200 characters.")
    raw = raw_text.strip().replace("\r\n", "\n").replace("\r", "\n")
    mode = source_mode(raw, mode)
    if mode == "script":
        index = 0
        def heading(match):
            nonlocal index
            index += 1
            title = re.sub(r"^(?:Scene\s*\d+|場景\s*[一二三四五六七八九十\d]+|场景\s*[一二三四五六七八九十\d]+)\s*[:：.-]?\s*", "", match[1], flags=re.I)
            return f"## Scene {index:02d}: {title or 'Scene'}"
        normalized = re.sub(r"^\s*(?:#{1,6}\s*)?((?:Scene\s*\d+|場景\s*[一二三四五六七八九十\d]+|场景\s*[一二三四五六七八九十\d]+|INT\.|EXT\.).*)$", heading, raw, flags=re.M | re.I)
        return normalized if index else "## Scene 01: Opening\n\n" + normalized
    people = character_details(raw)
    if not people:
        role = re.search(r"\b(?:a|an|the)\s+((?:lone |young |old )?[a-z]+)\b", raw, re.I)
        people = [((role[1].strip().title() if role else "Protagonist"), "", None)]
    if mode == "idea" and len(people) < 2:
        people.append(("Witness", "", None))
    # Use one allocation for declarations, beat references and subsequent extraction.
    people = allocated_characters(raw, people)
    if mode == "idea" and len(people) < 2:
        taken = {p[2] for p in people}
        witness_code = next(f"CAST-{i:02d}" for i in range(1, len(taken) + 2) if f"CAST-{i:02d}" not in taken)
        people.append(("Witness", "", witness_code))
    declarations = [f"Character: {name} @{code}" + (f" ({traits})" if traits else "")
                    for i, (name, traits, code) in enumerate(people, 1)]
    prop = re.search(r"\b(?:the|a|an)\s+((?:brass |analog |broken |old )?(?:dial|key|recorder|letter|book|phone|beacon|timer|map))\b", raw, re.I)
    if prop or mode == "idea":
        declarations.append(f"Prop: {prop[1] if prop else 'Story object'} @PROP-01")
    if mode == "idea":
        stages = [("The discovery", "establishes the space and discovers the conflict", "We need to understand what is happening."),
                  ("The pressure", "approaches the obstacle as the stakes become clear", "There is still a choice."),
                  ("The decision", "reaches for @PROP-01 and makes the decisive choice", "Then we act now.")]
        sections = []
        for i in range(target_scenes):
            title, action, dialogue = stages[min(2, i * 3 // target_scenes)]
            sections.append(f"## Scene {i + 1:02d}: {title}\n\nEnvironment: @SET-{i + 1:02d}, {style_name}, layered light and shadow.\n\n"
                            f"Shot 1: @{people[0][2]} {action}. Story premise: {raw}\n\n"
                            f'Shot 2: @{people[1][2]}: "{dialogue}"\n\n'
                            f"Shot 3: Close-up of @{people[0][2]} reacting beside @PROP-01.")
        result = "\n\n".join(declarations + sections)
        if len(result) > 500000:
            raise ValueError("Adapted screenplay exceeds 500,000 characters; shorten the source.")
        return result
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n(?=Meanwhile\b|Later\b|The next\b|At dawn\b|翌日|隔天|與此同時)", raw) if p.strip()]
    if len(paragraphs) == 1:
        paragraphs = [p.strip() for p in re.split(r'(?<=[.!?。！？])\s+(?=[A-Z“"「])|(?<=[。！？])(?=[\u3400-\u9fff])', raw) if p.strip()]
    count = min(target_scenes, len(paragraphs))
    sections = []
    for i in range(count):
        chunk = paragraphs[i * len(paragraphs) // count:(i + 1) * len(paragraphs) // count]
        beats = []
        for paragraph in chunk:
            speaker = next((name for name, _, _ in people if name in paragraph), people[0][0])
            cue = SPEAKER.match(paragraph)
            if cue and QUOTED.search(cue[2]):
                beats.append(speaker_name(cue[1]) + ': ' + cue[2])
            else:
                narrative = QUOTED.sub("", paragraph).strip(" ,:：")
                if narrative:
                    beats.append(narrative)
                for quote in QUOTED.finditer(paragraph):
                    preceding = paragraph[:quote.start()]
                    speaker = max(people, key=lambda person: preceding.rfind(person[0]))[0] if any(name in preceding for name, _, _ in people) else speaker
                    beats.append(f'{speaker}: "{quote[1]}"')
        for j, (name, _, code) in enumerate(people, 1):
            token = "@" + (code or f"CAST-{j:02d}")
            chinese = bool(re.fullmatch(r"[\u3400-\u9fff]+", name))
            pattern = re.escape(name) if chinese else r"(?<![\w@])" + re.escape(name) + r"(?!\w)"
            beats = [re.sub(pattern, lambda _: token + (' ' if chinese else ''), b) for b in beats]
        title = re.sub(r"[\r\n]+", " ", chunk[0]).split(".")[0][:72].strip('"“「') or "Story beat"
        sections.append(f"## Scene {i + 1:02d}: {title}\n\nEnvironment: @SET-{i + 1:02d}, {style_name}.\n\n" + "\n\n".join(f"Shot {j}: {beat}" for j, beat in enumerate(beats, 1)))
    result = "\n\n".join(declarations + sections)
    if len(result) > 500000:
        raise ValueError("Adapted screenplay exceeds 500,000 characters; shorten the source.")
    return result


def scene_shot_beats(scene_content, breakdown_mode="auto"):
    if not isinstance(breakdown_mode, str) or breakdown_mode not in BREAKDOWN_MODES:
        raise ValueError("Unknown breakdownMode.")
    content = "\n".join(line for line in scene_content.splitlines() if not DECLARATION.match(line)).strip()
    # Wrapped prose remains one beat. Blank paragraphs, explicit shots, and dialogue cues split it.
    paragraphs = re.split(r"\n\s*\n|\n(?=\s*(?:[-*]\s|Shot\s*\d+\s*[:：]|@?CAST-\d+[^\n]*[:：]\s*[\"“「]|[A-Za-z][A-Za-z '\-]{0,35}[:：]\s*[\"“「]|[\u3400-\u9fff]{1,12}[:：]\s*[\"“「]))", content, flags=re.I)
    beats = [re.sub(r"^(?:[-*]\s*(?:\[Shot\]\s*)?|Shot\s*\d+\s*[:：]\s*)", "", line, flags=re.I).strip() for line in paragraphs]
    beats = [b for b in beats if b]
    if not beats:
        return [scene_content.strip()] if scene_content.strip() else []
    if breakdown_mode == "scene":
        return ["\n".join(beats)]
    if breakdown_mode in ("cinematic", "cinematic_multi"):
        split = []
        for beat in beats:
            # Sentence boundaries outside quotes split actions without fragmenting spoken lines.
            start, closing = 0, None
            for i, char in enumerate(beat):
                boundary = False
                if closing:
                    if char == closing:
                        closing = None
                        boundary = i > 0 and beat[i - 1] in '.!?。！？'
                elif char in '"“「':
                    closing = {'"': '"', '“': '”', '「': '」'}[char]
                elif char in '.!?。！？':
                    boundary = True
                if boundary and (i + 1 == len(beat) or beat[i + 1].isspace() or '\u3400' <= beat[i + 1] <= '\u9fff'):
                    fragment = beat[start:i + 1].strip()
                    if fragment:
                        split.append(fragment)
                    start = i + 1
            if beat[start:].strip():
                split.append(beat[start:].strip())
        beats = split
    if breakdown_mode == "cinematic_multi" and len(beats) == 1:
        beats = ["Wide establishing view: " + beats[0], "Close-up detail: " + beats[0]]
    return beats


def infer_shot_grammar(beat_text, beat_index, total_beats):
    dialogue = []
    for line in beat_text.splitlines():
        cue = SPEAKER.match(line)
        speaker = speaker_name(cue[1]).lstrip("@").replace("#", ":") if cue else None
        spoken = [quote[1] for quote in QUOTED.finditer(line)]
        if not spoken and cue and not DECLARATION.match(line) and not HEADING.match(line) and (TAG.fullmatch(cue[1].strip()) or re.fullmatch(r"[A-Z][A-Z '\-]{1,35}", cue[1])):
            spoken = [cue[2].strip()] if cue[2].strip() else []
        for sentence in spoken:
            words = len(re.findall(r"[A-Za-z0-9]+|[\u3400-\u9fff]", sentence))
            dialogue.append({"speaker": speaker, "line": sentence, "estimatedSeconds": round(max(1.0, words / 2.5), 1)})
    moving = bool(re.search(r"\b(?:walk\w*|enter\w*|approach\w*|run\w*|chase\w*)\b|走|跑|進入|进入", beat_text, re.I))
    running = bool(re.search(r"\b(?:run\w*|chase\w*)\b|跑|追逐", beat_text, re.I))
    reaching = bool(re.search(r"\b(?:reach\w*|turn\w*|hand|dial)\b|伸手|轉身|转身", beat_text, re.I))
    close = bool(re.search(r"close.up|\b(?:eyes|tears|shock\w*|dial|hand)\b|特寫|特写|眼淚|眼泪", beat_text, re.I))
    orbit = bool(re.search(r"\b(?:orbit\w*|confront\w*|face.off|circle\w*)\b|對峙|对峙|環繞|环绕", beat_text, re.I))
    if beat_index == 0:
        lens, rig = (85, "ARRI Alexa 65 / 85mm Prime") if close else (35, "ARRI Alexa 65 / 35mm Anamorphic f/1.4")
    elif close:
        lens, rig = 85, "Sony Venice 2 / 85mm Macro"
    elif dialogue:
        lens, rig = 50, "Panavision Millennium DXL2 / 50mm Prime"
    else:
        lens, rig = 35, "RED V-Raptor XL / 35mm T1.5"
    if beat_index == 0:  # establishing shot: movement cues only
        move = "track" if running else "pushin" if moving else "static"
    else:
        move = "track" if running else "orbit" if orbit else ("crane" if beat_index == total_beats - 1 else "pushin") if close else "pushin" if moving or dialogue else "static"
    motion = {"track": "Handheld Tracking", "orbit": "Orbit 45°", "pushin": "Slow Dolly In", "crane": "Crane Up", "static": "Static Tripod"}[move]
    return {"opticalRig": rig, "cameraMotion": motion, "dialogue": dialogue,
            "previsPlan": {"set": "parallax", "lens": lens, "move": move, "action": "walkin" if moving else "turnreach" if reaching else "stand",
                           "facing": "console" if reaching else "room", "seconds": 4}}


def extract_asset_details(content, scenes):
    """Return source-derived descriptions; callers retain existing media and manual edits."""
    candidates = {}
    for match in TAG.finditer(content):
        code = asset_code(match[1])
        candidates.setdefault(code.split(":")[0], {"name": code.split(":")[0], "traits": ""})
        candidates.setdefault(code, {"name": code, "traits": ""})
        traits = re.match(r"\s*[（(]([^）)\n]+)[）)]", content[match.end():])
        if traits:
            candidates[code]["traits"] = traits[1].strip()
    for name, traits, code in allocated_characters(content):
        old = candidates.setdefault(code, {})
        old.update(name=name, traits=traits or old.get("traits", ""))
    for i, match in enumerate(re.finditer(r"(?m)^\s*(?:Prop|道具)\s*[:：]\s*([^\n]+)", content, re.I), 1):
        tag = TAG.search(match[1])
        code = asset_code(tag[1]) if tag and tag[1].upper().startswith("PROP") else f"PROP-{i:02d}"
        candidates[code] = {"name": TAG.sub("", match[1]).strip(), "traits": ""}
    for i, scene in enumerate(scenes, 1):
        codes = list(dict.fromkeys(asset_code(m[1]) for m in TAG.finditer(scene["content"]) if m[1].upper().startswith(("SET-", "LOC-")))) or [f"SET-{i:02d}"]
        title = re.sub(r"^Scene\s*\d+\s*[:：.-]?\s*", "", scene["title"], flags=re.I).strip()
        lines = [line.strip() for line in scene["content"].splitlines() if line.strip()]
        environment = next((re.sub(r"^Environment\s*[:：]\s*", "", line, flags=re.I) for line in lines if re.match(r"Environment\s*[:：]", line, re.I)), "")
        if not environment and lines and not re.search(r"CAST-|Character\s*:|[\"“「]", lines[0], re.I):
            environment = lines[0]
        for code in codes:
            candidates[code] = {"name": title or code, "traits": TAG.sub("", environment).strip(" ,.")}
    for code, item in candidates.items():
        name, traits = item["name"], item.get("traits", "")
        if code.startswith("CAST"):
            if ":" in code:
                base = candidates.get(code.split(":")[0], {})
                name = base.get("name", code.split(":")[0]) + " — " + code.split(":", 1)[1].lower()
                traits = ", ".join(filter(None, [base.get("traits"), traits, code.split(":", 1)[1].lower() + " wardrobe / appearance variant"]))
                item["kind"] = "OUTFIT"
            prompt = f"{name}, {traits}, cinematic character portrait, consistent facial structure, neutral studio rim lighting" if traits else name
        elif code.startswith(("SET", "LOC")):
            prompt = f"Reference for @{code} — {name}" + (f", {traits}" if traits else "") + ", wide cinematic environment plate, clear foreground/midground/background depth layers, no characters"
        elif code.startswith("PROP"):
            prompt = f"{name}, {traits}, cinematic prop reference, isolated object, readable materials and silhouette" if name != code or traits else f"Reference for @{code}, cinematic prop reference, isolated object"
        else:
            prompt = traits or f"Reference for @{code}"
        item.update(name=name, prompt=prompt)
    return candidates
