"""Bounded, deterministic screenplay preparation. Never calls a model or provider."""
from __future__ import annotations

import re

from project_docs.scene_headings import HEADING_LINES as HEADING, scene_name

SOURCE_MODES = {"auto", "idea", "novel", "script"}
BREAKDOWN_MODES = {"auto", "scene", "cinematic", "cinematic_multi"}
MEDIUM_LENSES = {"manju", "cinema", "storybook"}
GENRE_LENSES = {"general", "melodrama", "xianxia", "comedy", "suspense"}
CHOICE_FOCUSES = {"overall", "collision", "restraint", "reversal", "negative_space"}
TAG = re.compile(r"@?\b((?:CAST|SET|LOC|PROP|STYLE)-\d+(?:[:#][a-z0-9_-]+)?)\b", re.I)
# Lens, Premise and Constraint are composed-script context: never a shot, never a speaker.
DECLARATION = re.compile(r"^\s*(?:Character|角色|Prop|道具|Environment|Style|Lens|Premise|Constraint)\s*[:：]", re.I)
LENS_LINE = re.compile(r"^\s*Lens\s*[:：]\s*(manju|cinema|storybook)\b", re.I | re.M)
PROP = re.compile(r"\b(?:the|a|an)\s+((?:brass |analog |broken |old )?(?:dial|key|recorder|letter|book|phone|beacon|timer|map))\b", re.I)
# One known adjective at most: a free second word swallows verbs ("at the lighthouse is a countdown").
SETTING = re.compile(r"\b(?:in|at|inside)\s+(the\s+(?:old |new |abandoned |empty |dark |quiet |small |great )?[a-z]+)\b", re.I)
IDEA_STAGES = [("The discovery", "establishes the space and discovers the conflict", "We need to understand what is happening."),
               ("The pressure", "approaches the obstacle as the stakes become clear", "There is still a choice."),
               ("The decision", "reaches for @PROP-01 and makes the decisive choice", "Then we act now.")]
QUOTED = re.compile(r'["“「]([^"”」\n]+)["”」]')
# A cue tag keeps its variant or has none: "@CAST-01:night enters." must not back off to "@CAST-01" + ": night enters."
SPEAKER = re.compile(r'^\s*(@?CAST-\d+(?:[:#][\w-]+|(?![:#]\w))|[A-Za-z][A-Za-z\s\'-]{0,35}|[\u3400-\u9fff]{1,12})\s*[:：]\s*(.*)$')


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


def story_cast(raw, pair):
    """Declared or recognised people; a Witness completes the two-hander when one is needed."""
    people = character_details(raw)
    if not people:
        role = re.search(r"\b(?:a|an|the)\s+((?:lone |young |old )?[a-z]+)\b", raw, re.I)
        people = [((role[1].strip().title() if role else "Protagonist"), "", None)]
    if pair and len(people) < 2:
        people.append(("Witness", "", None))
    # Use one allocation for declarations, beat references and subsequent extraction.
    people = allocated_characters(raw, people)
    if pair and len(people) < 2:
        taken = {p[2] for p in people}
        witness_code = next(f"CAST-{i:02d}" for i in range(1, len(taken) + 2) if f"CAST-{i:02d}" not in taken)
        people.append(("Witness", "", witness_code))
    return people


def bounded(script):
    if len(script) > 500000:
        raise ValueError("Adapted screenplay exceeds 500,000 characters; shorten the source.")
    return script


def adapt_source_to_script(raw_text, mode="auto", target_scenes=3, style_name="Sci-Fi Noir Anamorphic",
                           medium_lens=None, genre_lens=None, choice_trace=None, contrast=None):
    """Without a lens or choice trace this is the SPEC_13 adaptation, unchanged; with one it composes (SPEC_14)."""
    if not isinstance(raw_text, str) or not raw_text.strip() or len(raw_text) > 500000:
        raise ValueError("sourceText must contain 1–500,000 characters.")
    if not isinstance(mode, str) or mode not in SOURCE_MODES:
        raise ValueError("Unknown sourceMode.")
    if type(target_scenes) is not int or not 1 <= target_scenes <= 12:
        raise ValueError("targetScenes must be an integer between 1 and 12.")
    if not isinstance(style_name, str) or not style_name.strip() or len(style_name) > 200:
        raise ValueError("style_name must contain 1–200 characters.")
    composed = medium_lens is not None or genre_lens is not None or choice_trace is not None
    if composed:
        medium_lens, genre_lens = composition_lenses(medium_lens, genre_lens)
        choice_trace = choice_trace_input(choice_trace) if choice_trace is not None else None
    raw = raw_text.strip().replace("\r\n", "\n").replace("\r", "\n")
    mode = source_mode(raw, mode)
    if mode == "script":
        # Each heading line becomes "## Scene NN: <name>"; its own number and Scene N label give way to NN.
        lines, index = raw.split("\n"), 0
        for position, line in enumerate(lines):
            if HEADING.match(line):
                index += 1
                lines[position] = f"## Scene {index:02d}: {scene_name(line) or 'Scene'}"
        normalized = "\n".join(lines)
        return normalized if index else "## Scene 01: Opening\n\n" + normalized
    if composed:
        return bounded(compose_script(raw, mode, target_scenes, style_name, medium_lens, genre_lens, choice_trace, contrast))
    people = story_cast(raw, mode == "idea")
    declarations = [f"Character: {name} @{code}" + (f" ({traits})" if traits else "")
                    for i, (name, traits, code) in enumerate(people, 1)]
    prop = PROP.search(raw)
    if prop or mode == "idea":
        declarations.append(f"Prop: {prop[1] if prop else 'Story object'} @PROP-01")
    if mode == "idea":
        sections = []
        for i in range(target_scenes):
            title, action, dialogue = IDEA_STAGES[min(2, i * 3 // target_scenes)]
            sections.append(f"## Scene {i + 1:02d}: {title}\n\nEnvironment: @SET-{i + 1:02d}, {style_name}, layered light and shadow.\n\n"
                            f"Shot 1: @{people[0][2]} {action}. Story premise: {raw}\n\n"
                            f'Shot 2: @{people[1][2]}: "{dialogue}"\n\n'
                            f"Shot 3: Close-up of @{people[0][2]} reacting beside @PROP-01.")
        return bounded("\n\n".join(declarations + sections))
    sections = [f"## Scene {i + 1:02d}: {title}\n\nEnvironment: @SET-{i + 1:02d}, {style_name}.\n\n" + "\n\n".join(f"Shot {j}: {beat}" for j, beat in enumerate(beats, 1))
                for i, (title, beats) in enumerate(novel_sections(raw, people, target_scenes))]
    return bounded("\n\n".join(declarations + sections))


def novel_sections(raw, people, target_scenes):
    """Prose paragraphs grouped into at most target_scenes (title, beats), speakers resolved to cast tags."""
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
        sections.append((title, beats))
    return sections


# L2 collision libraries: every card is two concrete conditions colliding, never a psychological template.
# {a}/{b} are the two leads, {p} the key prop, {s} the place; slices are the prop's P1 origin → turn → current.
GENRES = {
    "general": {"prop": "key", "setting": "the room",
        "slices": ("{p} hangs on its hook, polished", "{p} is passed hand to hand with its tag torn off", "{p} lies bent on the floor by the door"),
        "cards": [("collision", "Deadline × blocked door", "{a} must hand over {p} before the wall clock in {s} strikes the hour", "{b} stands in the only doorway of {s} and does not move"),
                  ("restraint", "Quiet rule × dropped object", "{a} may not raise their voice inside {s}", "{b} drops {p} on the floor in front of everyone"),
                  ("reversal", "Third rule × final handover", "{a} has followed the house rules of {s} three times in a row", "the next rule makes {a} give up {p} for good"),
                  ("negative_space", "Empty seat × untouched object", "the seat beside {a} in {s} has been left empty", "{p} lies on that seat and nobody picks it up")]},
    "melodrama": {"prop": "contract", "setting": "the restaurant",
        "slices": ("{p} is folded in {a}'s apron pocket, unsigned", "{p} is spotted with water from the burst pipe", "{p} lies flat on the counter, signed"),
        "cards": [("collision", "Work apron × booked-out party", "{a} is in a work apron, fixing the pipe under the counter of {s}", "{b} has booked all of {s} for a party and orders {a} to clear the floor"),
                  ("restraint", "Anonymous deed × public reading", "{a} signed {p} as an anonymous transfer with the owner line left blank", "{b} reads {p} aloud to the room and taps the blank line"),
                  ("reversal", "Refilled glass × ownership papers", "{a} has bowed and refilled {b}'s glass twice", "the manager hands {a} {p} with the owner's signature in front of {b}"),
                  ("negative_space", "Reserved chair × left contract", "{b} keeps the chair at the head of the table reserved for the owner", "{a} walks past the chair and leaves {p} on it without a word")]},
    "xianxia": {"prop": "jade token", "setting": "the mountain shrine",
        "slices": ("{p} is whole and cool to the touch", "{p} has a hairline crack across its face", "{p} is held together only by {a}'s fingers"),
        "cards": [("collision", "Incense deadline × cracking token", "{a} must carry {p} to {s} before one stick of incense burns down", "each time {a} uses spirit power, {p} cracks a little more"),
                  ("restraint", "Held seal × occupied hand", "{a} holds the seal over {s} shut with one hand", "{b} attacks while {a}'s free hand is holding {p}"),
                  ("reversal", "Sheathed sword × last finger of incense", "{a} has refused to draw the sword in front of mortals twice", "the incense is down to its last finger-width and {p} is still in the open"),
                  ("negative_space", "Empty sword rack × token in its place", "the sword rack in {s} has one empty slot", "{a} lays {p} in the empty slot instead of the sword")]},
    "comedy": {"prop": "delivery phone", "setting": "the rooftop",
        "slices": ("{p} shows a fresh order with a full timer", "{p} has a cracked screen and the timer is red", "{p} buzzes in pieces on the ground: order delivered"),
        "cards": [("collision", "Duel × 60-second delivery", "{a} is mid-duel with {b} on {s}", "{p} shows 60 seconds before the order is marked late"),
                  ("restraint", "Parcel signature × drawn blade", "{a} must sign for a stranger's parcel before drawing the blade", "{b} keeps attacking while the pen will not write"),
                  ("reversal", "Third apology × crushed phone", "{a} has apologised to {b} three times", "{b} steps on {p} and the order is marked late"),
                  ("negative_space", "Waiting rival × held-out pen", "{b} waits for {a}'s next move on {s}", "{a} holds out {p} for a signature and says nothing")]},
    "suspense": {"prop": "recorder", "setting": "the corridor",
        "slices": ("{p} reads three steps with its tape full", "{p} still reads three steps with its tape half gone", "{p} reads zero steps and its tape is empty"),
        "cards": [("collision", "Three steps left × dead end", "{p} in {a}'s hand shows three steps to the target", "{s} ends in a wall one step in front of {a}"),
                  ("restraint", "No looking back × matching footsteps", "{a} must not look back until the count ends", "{b}'s footsteps stop exactly where {a} stopped"),
                  ("reversal", "Same reading × an hour earlier", "{a} has checked {p} at every door and the reading never changed", "at this door {p} shows a time one hour earlier"),
                  ("negative_space", "Empty corridor × old belonging", "{s} is empty", "{p} from {a}'s past lies open on the floor")]},
}
OPPOSITE_FOCUS = {"restraint": "reversal", "reversal": "restraint", "collision": "negative_space", "negative_space": "collision"}
# P4 contrasts film behaviour, never a motive.
FOCUS_ACTIONS = {"overall": "keeps working on {p}", "collision": "steps straight into {b}'s path",
                 "restraint": "lowers the hand and steps back from {p}", "reversal": "sweeps {p} and everything else off the table",
                 "negative_space": "stops mid-reach and leaves the sentence unfinished"}
REVEALS = {"melodrama": "{a}:revealed takes off the apron; underneath is a tailored suit, and {p} goes down on the table.",
           "xianxia": "{a}:awakened rises as light runs along the cracks in {p}."}
MEDIUM_LOOK = {"manju": "hard key light, vertical 9:16 framing", "cinema": "layered foreground, midground and background for parallax",
               "storybook": "flat picture-book colour, clear silhouettes"}
EXCHANGES = [("Ten seconds. Decide.", "I only need five."), ("Put it down.", "Make me."), ("Last chance.", "Then watch.")]


def composition_lenses(medium_lens=None, genre_lens=None):
    medium = "manju" if medium_lens is None else medium_lens
    genre = "general" if genre_lens is None else genre_lens
    if not isinstance(medium, str) or medium not in MEDIUM_LENSES:
        raise ValueError("Unknown mediumLens.")
    if not isinstance(genre, str) or genre not in GENRE_LENSES:
        raise ValueError("Unknown genreLens.")
    return medium, genre


def choice_trace_input(trace):
    if not isinstance(trace, dict):
        raise ValueError("choiceTrace must be an object.")
    focus = trace.get("focus", "overall")
    if not isinstance(focus, str) or focus not in CHOICE_FOCUSES:
        raise ValueError("Unknown choiceTrace focus.")
    labels = {}
    for key in ("keptLabels", "uncheckedLabels"):
        value = trace.get(key, [])
        if not isinstance(value, list) or len(value) > 20 or not all(isinstance(v, str) and 0 < len(v.strip()) <= 200 for v in value):
            raise ValueError(f"{key} must be a list of at most 20 labels of 1–200 characters.")
        labels[key] = [v.strip() for v in value]
    extra = trace.get("extraCondition", "")
    if not isinstance(extra, str) or len(extra) > 500:
        raise ValueError("extraCondition must contain at most 500 characters.")
    return {"focus": focus, **labels, "extraCondition": extra.strip()}


def story_forms(raw, genre):
    """L1: the people, the key prop and the place a source names, with genre defaults where it names none."""
    prop, place = PROP.search(raw), SETTING.search(raw)
    return story_cast(raw, True), prop[1] if prop else GENRES[genre]["prop"], place[1] if place else GENRES[genre]["setting"]


def collision_cards(genre, fill):
    slices = [fill(s) for s in GENRES[genre]["slices"]]
    return [{"id": f"col_{i}", "label": label, "conditionA": fill(a), "conditionB": fill(b), "focus": focus, "propSlice": slices}
            for i, (focus, label, a, b) in enumerate(GENRES[genre]["cards"], 1)]


def propose_story_collisions(raw_text, medium_lens="manju", genre_lens="general"):
    """L1 → L2: four condition-collision cards for the creator to keep or strike out (P3)."""
    if not isinstance(raw_text, str) or not raw_text.strip() or len(raw_text) > 500000:
        raise ValueError("sourceText must contain 1–500,000 characters.")
    medium, genre = composition_lenses(medium_lens, genre_lens)
    people, prop, setting = story_forms(raw_text.strip(), genre)
    actors = [name for name, _, _ in people]
    fill = lambda value: value.format(a=actors[0], b=actors[1], p="the " + prop, s=setting)
    return {"forms": {"actors": actors, "prop": prop, "setting": setting}, "candidates": collision_cards(genre, fill),
            "mediumLens": medium, "genreLens": genre}


def compute_choice_contrast(history_traces, current_focus):
    """P4: two or more of the last five choices held one line and this one takes the opposite."""
    recent = [trace.get("focus") for trace in history_traces[-5:]]
    dominant = next((focus for focus, opposite in OPPOSITE_FOCUS.items() if opposite == current_focus and recent.count(focus) >= 2), None)
    if not dominant:
        return {"contrastDetected": False, "dominantFocus": None, "currentFocus": current_focus, "contrastCue": ""}
    return {"contrastDetected": True, "dominantFocus": dominant, "currentFocus": current_focus,
            "contrastCue": f"Prior beats held to {dominant}; this turn switches directly to {current_focus} action without explanation."}


def strike(value, labels):
    for label in labels:
        value = re.sub(re.escape(label), "", value, flags=re.I)
    return value


def compose_script(raw, mode, target_scenes, style_name, medium, genre, trace, contrast):
    """L1 form → L2 kept collisions → L3 prop time slices → L4 behaviour contrast, cut for one medium (P5)."""
    people, prop, setting = story_forms(raw, genre)
    a, b = "@" + people[0][2], "@" + people[1][2]
    fill = lambda value: value.format(a=a, b=b, p="@PROP-01", s=setting)
    cap = lambda value: value[:1].upper() + value[1:]
    cards = collision_cards(genre, fill)
    trace = trace or {"focus": "overall", "keptLabels": [], "uncheckedLabels": [], "extraCondition": ""}
    # P3: what the creator struck out never reaches the script; kept collisions and the extra condition always do.
    unchecked = [label.casefold() for label in trace["uncheckedLabels"]]
    allowed = lambda value: not any(label in value.casefold() for label in unchecked)
    known = {card["label"].casefold(): card for card in cards}
    if trace["keptLabels"]:
        kept = [known[label.casefold()] for label in trace["keptLabels"] if label.casefold() in known and allowed(label)]
        constraints = [label for label in trace["keptLabels"] if label.casefold() not in known and allowed(label)]
    else:
        kept, constraints = [card for card in cards if allowed(card["label"])][:1], []
    constraints = [strike(c, trace["uncheckedLabels"]) for c in constraints + [trace["extraCondition"]] if c]
    scenes = novel_sections(raw, people, target_scenes) if mode == "novel" else \
        [(IDEA_STAGES[min(2, i * 3 // target_scenes)][0], []) for i in range(target_scenes)]
    count, turn = len(scenes), len(scenes) // 2
    groups = [kept[0::2], kept[1::2]] if count > 1 else [kept]
    slices = cards[0]["propSlice"]
    act = lambda focus: fill(FOCUS_ACTIONS[focus])
    detected = bool(contrast and contrast.get("contrastDetected"))
    held_line = contrast["dominantFocus"] if detected else "restraint"
    broken_line = contrast["currentFocus"] if detected else OPPOSITE_FOCUS[held_line]
    declarations = [f"Lens: {medium} × {genre}"] + [f"Character: {name} @{code}" + (f" ({traits})" if traits else "") for name, traits, code in people]
    declarations.append(f"Prop: {prop} @PROP-01")
    if mode == "idea":
        declarations.append("Premise: " + strike(" ".join(raw.split()), trace["uncheckedLabels"]))
    sections = []
    for i, (title, source_beats) in enumerate(scenes):
        held = groups[i] if i < len(groups) else []
        title = strike(" / ".join(card["label"] for card in held) or title, trace["uncheckedLabels"]).strip() or f"Scene {i + 1}"
        # Dashes, not commas: "Name, traits, " reads as a character introduction to character_details.
        context = [f"Environment: @SET-{i + 1:02d} — {setting} — {MEDIUM_LOOK[medium]} — {style_name}."] + [f"Constraint: {c}" for c in constraints if i < 2]
        if medium == "manju":
            beats = [f"[Cold open] {a} and @PROP-01 dead centre of frame as {b} cuts in." if i == 0 else f"{b} squares up to {a} across @PROP-01."]
        elif medium == "cinema":
            beats = [f"Through the foreground doorway of {setting}, {a} holds the midground while {b} crosses the background." if i == 0
                     else f"Framed past a foreground pillar, {a} and {b} stay apart with @PROP-01 between them."]
        else:
            beats = [f"Narration: This is {a}, and this is @PROP-01.", f"{a} is drawn small beside a large @PROP-01 in the middle of the page."] if i == 0 \
                else [f"Narration: The next day, {a} came back to {setting}."]
        beats += [cap(card[key]) + "." for card in held for key in ("conditionA", "conditionB")] + source_beats
        if medium == "manju":
            beats += [f'{b}: "{EXCHANGES[i % 3][0]}"', f'{a}: "{EXCHANGES[i % 3][1]}"']
        beats.append("Close-up: " + slices[0 if count == 1 else round(i * 2 / (count - 1))] + ".")
        if i == turn:
            if medium == "cinema":
                beats.append(f"[Omission] The chair beside {a} stays empty; a hand stops above @PROP-01 and does not finish the reach. No dialogue.")
            if medium == "storybook":  # the rule of three is the page's P4 contrast
                beats += [f"Narration: The first time, {a} {act(held_line)}.", f"Narration: The second time, {a} {act(held_line)}.",
                          f"Narration: The third time, {a} {act(broken_line)}."]
            elif detected:
                beats.append(f"[Contrast] Twice before, {a} {act(held_line)}. This time {a} {act(broken_line)}, without a word.")
        if i == count - 1:
            beats += [fill(REVEALS[genre])] if genre in REVEALS else []
            beats.append({"manju": f"[Cliffhanger] {b} lifts @PROP-01 into frame as the door behind {a} opens; cut to black before anyone speaks.",
                          "cinema": f"Wide: {setting} framed exactly as the first shot; only @PROP-01 has changed.",
                          "storybook": f"[Page turn] The next page: {a} and {b} on either side of @PROP-01, and all of {setting} quiet around them."}[medium])
        beats = [beat for beat in beats if allowed(beat)]
        sections.append(f"## Scene {i + 1:02d}: {title}\n\n" + "\n\n".join(context + [f"Shot {j}: {beat}" for j, beat in enumerate(beats, 1)]))
    return sanitize_narrative_voice("\n\n".join(declarations + sections))


# No-label rule: abstract emotion labels and mind-reading are intercepted; each becomes something a camera can film.
BANNED_ZH = re.compile(r"心裡壓著|心裡還沒準備好|內心深處感到|心想自己|暗自決定|霸氣外露|氣氛十分緊張|感到無比絕望|我知道你心裡|根據我的記憶")
BANNED_EN = re.compile(r"\b(?:feels deep inside|secretly thinks to (?:himself|herself|themselves)|overwhelmed with raw emotion|an aura of dominance|the atmosphere is very tense|deep down in (?:his|her|their) heart)\b", re.I)
FILMABLE = {"心裡壓著": "把 @PROP-01 握在手裡沒有放下", "心裡還沒準備好": "手停在 @PROP-01 上方沒有落下", "內心深處感到": "低頭看著 @PROP-01",
            "心想自己": "看了 @PROP-01 一眼，沒有開口", "暗自決定": "把 @PROP-01 收進口袋", "霸氣外露": "將 @PROP-01 重重按在檯面上，全場停下動作",
            "氣氛十分緊張": "所有人停下手上的動作", "感到無比絕望": "鬆開手，@PROP-01 掉在地上", "我知道你心裡": "你手上一直拿著 @PROP-01",
            "根據我的記憶": "照 @PROP-01 上的紀錄", "feels deep inside": "checks the @PROP-01 indicator as the mark advances",
            "secretly thinks to": "glances at @PROP-01 and says nothing", "overwhelmed with raw emotion": "grips @PROP-01 with both hands",
            "an aura of dominance": "@PROP-01 pressed flat on the counter while the room stops", "the atmosphere is very tense": "nobody in the room moves",
            "deep down in": "without looking up from @PROP-01"}
ACTION = re.compile(r"\b(?:walk|enter|turn|reach|hold|drop|grip|set|lift|hand|step|stop|check|sign|open|clos|carr|cross|slam|block|read|pull|push|leav|run|chas|sweep|lay|lie|stand|press|tap|wait|rise)\w*|[走跑握放推拉拿按掀關開遞撕站停]", re.I)


def audit_narrative_voice(text):
    violations = [match[0] for pattern in (BANNED_ZH, BANNED_EN) for match in pattern.finditer(text)]
    sentences = [s for s in re.split(r"(?<=[.!?。！？])\s+|\n+", text) if s.strip()]
    concrete = sum(1 for s in sentences if TAG.search(s) or ACTION.search(s))
    score = round(100 * concrete / len(sentences)) - 25 * len(violations) if sentences else 0
    return {"ok": not violations, "violations": violations, "concreteScore": max(0, min(100, score))}


def sanitize_narrative_voice(text):
    """Replace each label, with the rest of its clause, by an action and object state a camera can film."""
    def filmable(match):
        value = next(v for k, v in FILMABLE.items() if match[0].lower().startswith(k))
        return value[:1].upper() + value[1:] if match[0][:1].isupper() else value
    for pattern in (BANNED_ZH, BANNED_EN):
        text = re.sub("(?:" + pattern.pattern + r")[^,.;:!?，。；：！？\n]*", filmable, text, flags=pattern.flags)
    return text


def script_medium_lens(content):
    match = LENS_LINE.search(content or "")
    return match[1].lower() if match else None


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


def infer_shot_grammar(beat_text, beat_index, total_beats, medium_lens=None):
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
    if medium_lens == "manju":  # close-ups and 50mm face-offs, always pushing
        lens, move = (85 if close else 50), ("track" if moving else "pushin")
    elif medium_lens == "cinema":  # 35mm depth; two figures or an exchange orbit, omissions and single figures push in
        figures = {m[1].upper().split(":")[0] for m in TAG.finditer(beat_text) if m[1].upper().startswith("CAST")}
        lens, move = (85 if close else 35), ("track" if running else "orbit" if orbit or dialogue or len(figures) > 1 else "pushin")
    elif medium_lens == "storybook":  # a still page, lifted on the last beat
        lens, move = (85 if close else 35), ("crane" if beat_index == total_beats - 1 else "static")
    if medium_lens in MEDIUM_LENSES:
        rig = f"ARRI Alexa 65 / {lens}mm Prime" if beat_index == 0 else {35: "RED V-Raptor XL / 35mm T1.5", 50: "Panavision Millennium DXL2 / 50mm Prime", 85: "Sony Venice 2 / 85mm Macro"}[lens]
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
