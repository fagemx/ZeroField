"""SPEC_21 §3.2–3.5: the reference plan of one generation and the prompts written around it.

Pure text work: no media, network, database or file access. ``context_compiler.resolve_studio_context`` reads the task
source (the shot row, the asset tables and their ``asset_meta``) into the plain values these functions take:

* an *asset* is ``{"code", "kind", "name", "description", "voice", "image", "acting", "geo", "light", "lock", "change",
  "panels"}``: the locked description without its seed, the reference image cell's first picture and the chosen panel
  pictures ``{panel: url}``;
* a *plan* is the list of pictures the card receives, in slot order: ``{"assetCode", "role", "panel", "url"}``. Every
  prompt numbers its pictures by this order, so "image 2" is always the plan's second entry.

The prompts follow the production method of SPEC_21 §0.2: each picture has one job, the locks are pasted word for word,
behaviour is written instead of emotion, and the image prompts say only what is in the frame.
"""
from __future__ import annotations

import os
import re

KINDS = {"CAST": "character", "CHAR": "character", "SET": "location", "LOC": "location", "SCENE": "location",
         "PROP": "prop"}
PANELS = ("face", "front", "back", "sheet", "plate", "reverse", "angle", "product", "stress")
PANEL_PROMPTS = ("face", "front", "back", "plate", "product", "stress")  # §3.4: the panels written from a template
VIEW_EDITS = ("reverse", "angle")  # §2.3: a location's other views are edits of its plate
REFERENCE_PANELS = ("front", "back", "stress")  # §2.3: the panels the reference card renders from earlier pictures
MAX_REFERENCES = 6
IMAGE_LIMIT = 2200  # GPU trial 2026-10-29: at 1500 the single light logic was dropped; Klein held 2200 well
VIDEO_BUDGET_ENV = "ZEROFIELD_VIDEO_PROMPT_BUDGET"
DEFAULT_VIDEO_BUDGET = 4000
BLOCKS = ("SCENE CONTEXT", "ACTIVE REFERENCES", "LOCATION MAP", "FIRST FRAME AND BLOCKING", "OPTICS", "CAMERA",
          "ACTION TIMING", "PHYSICS", "LIGHTING", "AUDIO", "CHARACTER ACTING", "STYLE", "POSITIVE CONSTRAINTS", "ORDER")
# §3.2: over budget, whole blocks go in this order; every other block always stays.
DROP_ORDER = ("PHYSICS", "CHARACTER ACTING", "OPTICS", "ACTIVE REFERENCES", "LOCATION MAP", "ORDER")
KEYS = ("reference_plan", "image_reference_prompt", "video_skeleton_prompt", "dropped_blocks", "asset_panel_prompt",
        "edit_prompt")

# Stress tests (§3.4): variation i takes pose, light and (for a place or an object) view i. Behaviour, never emotion.
STRESS_VARIATIONS = (
    ("sitting on a crate", "side light from a window", "seen at eye height"),
    ("walking toward camera", "overcast daylight", "seen from a low angle"),
    ("in a three-quarter back view looking over the shoulder", "low warm sun", "seen from high above"),
    ("turning to face the lens straight on, close on the face", "hard light from directly overhead", "seen close up"),
    ("kneeling on one knee, working with both hands", "a single bare bulb above", "seen from the far side"),
    ("running past the camera in profile", "bright midday sun", "seen in profile"),
    ("leaning on a rail with both forearms, looking down", "cool blue light at dusk", "seen at an angle from below"),
    ("shouting toward someone off frame, face toward the camera", "backlight with a bright rim", "seen against the light"),
    ("crouching low and looking up toward the camera", "warm lamp light from one side", "seen from directly above"),
    ("standing in a doorway, half in shadow", "soft light from a cloudy sky", "seen in half shadow"),
)

# §3.4 edit template. A character keeps the template's own list; a place or an object keeps what it is made of.
EDIT = ("Edit image 1. CHANGE: {change}. PRESERVE EXACTLY: {preserve}. "
        "Only change what is named; everything else stays identical.")
PRESERVE = {
    "character": "the face, hair, body proportions, clothing not named above, the backdrop, the light direction, "
                 "the colour and grain",
    "location": "the architecture, the materials and their wear, the objects not named above, the light direction, "
                "the colour and grain",
    "prop": "the shape, proportions, materials and markings not named above, the backdrop, the light direction, "
            "the colour and grain",
}
VIEW_PRESERVE = ("the architecture, the materials and their wear, every fixed object and its place in the space, "
                 "the light direction, the colour and grain")
VIEW_CHANGES = {
    "reverse": "the reverse angle of this place: the camera now stands at the far side of the space looking back toward "
               "where image 1 was taken, so what was in the background is now close to the camera and what was close "
               "is now in the background",
    "angle": "a side angle on this place: the camera moves a quarter turn around the space and looks across it from the "
             "side, so the side wall of image 1 is now the far wall and every object keeps its place in the room",
}

FIRST_FRAME = "The first frame is the given image; everyone stays where it places them."
STAYS_PUT = "The camera STAYS PUT: no push, no zoom, no pan."
ONLY_QUOTED = "Nobody else speaks. Only the quoted lines are spoken. Natural sound only, no music."
NOBODY_SPEAKS = "Nobody speaks. Natural sound only, no music."

CODE = r"(?:CAST|SET|LOC|PROP|CHAR|SCENE|STYLE)-\d+(?:[:#][a-z0-9_-]+)?"
_EXCLUDED_TAG = re.compile(rf"(?:!-@?|!@|-@)\b{CODE}\b", re.I)
# A closing run of bare tags ("... against the glass. @CAST-01 @SET-01") binds assets; it is not a sentence.
_TAG_RUN = re.compile(rf"(^|[.!?。])((?:[ \t,]*@{CODE}\b)+)[ \t,]*$", re.I | re.M)
_TAG = re.compile(rf"@?\b({CODE})\b(?!\.(?:start|end)\b)", re.I)
# A timed segment: "[0-2s]" anywhere, or "0.0–1.0s —" opening a line.
_TIMED = re.compile(r"\[\s*(\d+(?:\.\d+)?)\s*s?\s*[-–—~]\s*(\d+(?:\.\d+)?)\s*s?\s*\]"
                    r"|^[ \t]*(\d+(?:\.\d+)?)\s*s?\s*[-–—~]\s*(\d+(?:\.\d+)?)\s*s\b[ \t]*[—–:-]?", re.I | re.M)
_SPEECH = (r"\b(?:says?|said|asks?|asked|shouts?|shouted|whispers?|whispered|calls?|called|answers?|answered|"
           r"repl(?:y|ies|ied)|speaks?|spoke|mutters?|muttered|murmurs?|murmured|yells?|yelled|tells?|told|adds?|added)\b")
_SPEAKS = re.compile(_SPEECH, re.I)
_PRONOUN_SPEAKS = re.compile(rf"\b(?:she|he|they)\b[^.!?\n]*?{_SPEECH}", re.I)
_QUOTE = re.compile(r'"([^"\n]+)"|“([^”\n]+)”|「([^」\n]+)」')
_SECTION = re.compile(r"\b(PHYSICS|CHECK|ORDER):")
_BOUNDARY = re.compile(r"[.!?。](?=\s)|\n|\]")
_SHOT_SIZE = re.compile(r"\b(extreme close[- ]up|medium close[- ]up|close[- ]up|extreme wide shot|medium wide shot|"
                        r"wide shot|medium shot|full shot|long shot|establishing shot|two[- ]shot|insert shot|"
                        r"over[- ]the[- ]shoulder shot)\b", re.I)
_CUTS = re.compile(r"\b(?:hard cut|smash cut|cut to)\b", re.I)
_GARMENT = re.compile(r"\b(?:jacket|coat|parka|anorak|shirt|t-shirt|blouse|sweater|jumper|hoodie|cardigan|vest|"
                      r"waistcoat|trousers|pants|jeans|shorts|skirt|dress|overalls|jumpsuit|flight suit|uniform|boots|"
                      r"shoes|sneakers|sandals|gloves|scarf|hat|cap|beanie|helmet|goggles|harness|belt|apron|cloak|"
                      r"robe|suit|tie|socks|leggings|fleece|windbreaker|poncho)s?\b", re.I)
_WEARS = re.compile(r"^(?:(?:she|he|they)\s+(?:wears?|is wearing|are wearing)|wearing|dressed in)\s+", re.I)
_FOOTWEAR = re.compile(r"\b(boots|shoes|sneakers|trainers|sandals|heels|loafers|slippers|clogs)\b", re.I)
_FEMALE = re.compile(r"\b(?:woman|women|girl|she|her|female|lady)\b", re.I)
_MALE = re.compile(r"\b(?:man|men|boy|he|his|him|male)\b", re.I)


def empty_keys():
    """The SPEC_21 context keys of a generation they do not apply to: "" and [], never missing."""
    return {"reference_plan": [], "image_reference_prompt": "", "video_skeleton_prompt": "", "dropped_blocks": [],
            "asset_panel_prompt": "", "edit_prompt": ""}


def code_of(value):
    """An asset code as the compiler keys it: ``@cast-01#wet`` -> ``CAST-01:WET``."""
    return str(value or "").strip().lstrip("@").upper().replace("#", ":")


def base_of(code):
    return code_of(code).split(":")[0]


def asset_kind(code):
    """character, location or prop by the code's prefix; "" for any other code."""
    match = re.match(r"([A-Z]+)-", code_of(code))
    return KINDS.get(match[1], "") if match else ""


def video_budget(environ=None):
    """Characters a video prompt may use: ``ZEROFIELD_VIDEO_PROMPT_BUDGET``, else 4,000 (SPEC_21 §0.3 decision 5)."""
    raw = (os.environ if environ is None else environ).get(VIDEO_BUDGET_ENV, "")
    try:
        value = int(str(raw).strip())
    except ValueError:
        return DEFAULT_VIDEO_BUDGET
    return value if value > 0 else DEFAULT_VIDEO_BUDGET


# ---------- text helpers ----------

def _flat(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _clause(text):
    """text without its closing full stop, to sit inside a sentence."""
    return _flat(text).rstrip(" .;,")


def _sentence(text):
    """text as a sentence: one line, ending in a full stop unless it already ends one."""
    text = _flat(text)
    if not text:
        return ""
    return text if text[-1] in ".!?。…\"”」" else text + "."


def first_sentence(text):
    text = _flat(text)
    match = re.search(r"(?<=[.!?。])\s", text)
    return text[:match.start()] if match else text


def _fit(text, limit):
    """text cut to at most ``limit`` characters at a sentence end, else at a word end."""
    if len(text) <= limit:
        return text
    if limit <= 0:
        return ""
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind(".\n"))
    if end >= limit // 2:
        return cut[:end + 1].rstrip()
    space = max(cut.rfind(" "), cut.rfind("\n"))
    return (cut[:space] if space > 0 else cut).rstrip(" ,;:")


def name_tags(text, names):
    """text with each asset tag written as the asset's name (``names``: {code: name}; a variant without its own name
    takes its base's). ``!@`` exclusions go, and so does a closing run of bare tags, which binds assets rather than
    saying anything; every other character stays as written, line breaks included."""
    text = _EXCLUDED_TAG.sub("", str(text or ""))
    text = _TAG_RUN.sub(lambda match: match[1], text)

    def named(match):
        code = code_of(match[1])
        name = names.get(code) or names.get(base_of(match[1]))
        return (name if asset_kind(code) == "character" else the_name(name)) if name else match[0]
    text = _TAG.sub(named, text)
    text = re.sub(r"\b([Tt])he the\b", r"\1he", text)  # "the @SET-03" reads "the basket interior", not "the the …"
    return "\n".join(re.sub(r"[ \t]{2,}", " ", line).strip() for line in text.split("\n")).strip()


def bare_name(name):
    """A place or object name without its leading article, in lower case ("The Burner" -> "burner")."""
    name = re.sub(r"^the\s+", "", str(name or "").strip(), flags=re.I)
    return name[:1].lower() + name[1:]


def the_name(name):
    """A place or object as it reads inside a sentence: "the burner (firing)", never "The Burner (firing)"."""
    return "the " + bare_name(name) if name else ""


def split_sections(text):
    """(action, {"PHYSICS"|"CHECK"|"ORDER": text}) of an Action & Audio Prompt cell. A label opens a section that runs to
    the next label, a blank line or a timed line ("[2-4s] ..."); everything else is the action, its lines as written."""
    action, sections, current = [], {}, None
    for line in str(text or "").split("\n"):
        if not line.strip() or _TIMED.match(line.strip()):
            current = None
        pieces = _SECTION.split(line)
        head = pieces[0]
        if current is None:
            if head.strip() or len(pieces) == 1:
                action.append(head.rstrip())
        elif head.strip():
            sections[current].append(head.strip())
        for label, body in zip(pieces[1::2], pieces[2::2]):
            current = label
            sections.setdefault(label, [])
            if body.strip():
                sections[label].append(body.strip())
    joined = re.sub(r"\n{3,}", "\n\n", "\n".join(action)).strip()
    return joined, {label: " ".join(parts) for label, parts in sections.items() if parts}


def quoted_lines(text):
    """[(start, end, line)] of the quoted sentences in text: the only words a shot speaks."""
    return [(match.start(), match.end(), next(group for group in match.groups() if group is not None).strip())
            for match in _QUOTE.finditer(str(text or ""))]


def dialogue(text, characters):
    """[(speaker code or None, line)] for each quoted line of ``text`` (tags not yet named), in order.

    ``characters`` is [(code, name)]. Within the line's sentence the speaker is the first character named or tagged
    before a speech verb ("Ines watches Noa and says"); a "she says" is the shot's subject, the first character the
    action names; then the first character named after the quote ('"Now," Noa says'), the first named before it, and
    last the shot's subject."""
    text = str(text or "")
    quotes = quoted_lines(text)
    if not quotes:
        return []
    masked = list(text)
    for start, end, _ in quotes:
        masked[start:end] = " " * (end - start)
    masked = "".join(masked)
    refs = []
    for code, name in characters:
        refs += [(match.start(), match.end(), code) for match in _TAG.finditer(masked)
                 if base_of(match[1]) == base_of(code)]
        if name:
            refs += [(match.start(), match.end(), code)
                     for match in re.finditer(rf"(?<!\w){re.escape(name)}(?!\w)", masked)]
    refs.sort()
    subject = refs[0][2] if refs else characters[0][0] if len(characters) == 1 else None
    spoken = []
    for start, end, line in quotes:
        opening = max((match.end() for match in _BOUNDARY.finditer(masked, 0, start)), default=0)
        following = _BOUNDARY.search(masked, end)
        closing = following.start() if following else len(masked)
        before = [(stop, code) for at, stop, code in refs if opening <= at and stop <= start]
        after = [code for at, _, code in refs if end <= at < closing]
        speaker = next((code for stop, code in before if _SPEAKS.search(masked, stop, start)), None)
        if speaker is None and _PRONOUN_SPEAKS.search(masked, opening, start):
            speaker = subject
        spoken.append((speaker or next(iter(after), None) or next((code for _, code in before), None) or subject, line))
    return spoken


def still_state(action):
    """The state a still shows: the first timed segment of the action (or its first sentence), without timings or
    quoted lines."""
    text = _QUOTE.sub("", str(action or ""))
    marks = list(_TIMED.finditer(text))
    if marks:
        text = text[marks[0].end():marks[1].start() if len(marks) > 1 else len(text)]
    text = first_sentence(_TIMED.sub(" ", text))
    text = re.sub(r"\s+([,.;:!?])", r"\1", text).strip(" ,;:")
    return _sentence(text)


def timed_seconds(text):
    """The end of the last timed segment ("[2-4s]" -> 4.0), or None."""
    ends = [float(match[2] or match[4]) for match in _TIMED.finditer(str(text or ""))]
    return max(ends) if ends else None


def split_description(description):
    """(build, clothes) of a character's locked description (§3.4): its first sentence and the rest, when the rest says
    what the person wears ("She wears ..." losing its lead-in); ("", the whole description) when it does not split."""
    text = _clause(description)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"“])", text, maxsplit=1)
    if len(parts) == 2 and (_GARMENT.search(parts[1]) or re.search(r"\bwear", parts[1], re.I)):
        return _clause(parts[0]), _WEARS.sub("", _clause(parts[1]))
    return "", text


def _lower_article(text):
    """"A slight woman" reads "a slight woman" inside a sentence; a name or any other word keeps its case."""
    return re.sub(r"^(A|An|The)\b", lambda match: match[1].lower(), text)


def _figure(description):
    """(subject, possessive, footwear) the front template writes for this person: "She", "her", "boots" for the
    GPU-proven case; He / his or The person / their by the description, and the feet when no footwear is named."""
    if _FEMALE.search(description):
        subject, possessive = "She stands", "her"
    elif _MALE.search(description):
        subject, possessive = "He stands", "his"
    else:
        subject, possessive = "The person stands", "their"
    footwear = _FOOTWEAR.search(description)
    return subject, possessive, footwear[1].lower() if footwear else "feet"


def _people(count):
    if count <= 0:
        return "An empty place with nobody in it."
    return f"Exactly {count} {'person' if count == 1 else 'people'} in frame."


def _join(names):
    names = [name for name in names if name]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1] if names else ""


# ---------- §3.5 reference plan ----------

def _entry(code, role, panel, url):
    return {"assetCode": code, "role": role, "panel": panel, "url": url}


def _cap(plan, limit):
    """At most ``limit`` pictures: props go first, then character fronts, each from the last mentioned."""
    plan = list(plan)
    for role in ("prop", "character_body"):
        while len(plan) > limit and any(entry["role"] == role for entry in plan):
            plan.pop(max(i for i, entry in enumerate(plan) if entry["role"] == role))
    return plan[:limit]


def reference_plan(assets, frames=(), limit=MAX_REFERENCES):
    """§3.5: the pictures of the mentioned assets in mention order. A character sends its face and its headless front
    (its reference image when it has neither), a place its plate, an object its product photograph (each, without
    the panel, its reference image). The same picture is sent once. A quoted reference take (``frames``:
    [{code, url}]) takes a place only while one is left."""
    plan, seen = [], set()

    def add(entry):
        if entry["url"] and entry["url"] not in seen:
            seen.add(entry["url"])
            plan.append(entry)

    for asset in assets:
        code, kind, panels = asset["code"], asset.get("kind") or asset_kind(asset["code"]), asset.get("panels") or {}
        if kind == "character":
            if panels.get("face") or panels.get("front"):
                add(_entry(code, "character_face", "face", panels.get("face")))
                add(_entry(code, "character_body", "front", panels.get("front")))
            else:
                add(_entry(code, "character_face", "reference", asset.get("image")))
        elif kind in ("location", "prop"):
            panel = "plate" if kind == "location" else "product"
            add(_entry(code, kind, panel, panels[panel]) if panels.get(panel) else
                _entry(code, kind, "reference", asset.get("image")))
    plan = _cap(plan, limit)
    for frame in frames:
        if len(plan) < limit:
            add(_entry(frame["code"], "take_frame", "frame", frame.get("url")))
    return plan


def _role(kind, panel):
    if kind == "character":
        return "character_face" if panel == "face" else "character_body"
    return kind if kind in ("location", "prop") else "character_face"


def panel_plan(asset, panel, *, together=(), setting=None, base_code=None, base=None, base_panels=None):
    """§2.3: the pictures one asset panel generation sends, in order. A variant (``base_code`` with ``base_panels``)
    edits its base's same panel, or its base's reference image when that panel is not chosen."""
    code, panels = asset["code"], asset.get("panels") or {}
    if base_code is not None and panel != "stress":
        url = (base_panels or {}).get(panel)
        kind = asset_kind(base_code)
        if url:
            return [_entry(base_code, _role(kind, panel), panel, url)]
        image = (base or {}).get("image")
        return [_entry(base_code, _role(kind, panel), "reference", image)] if image else []
    if panel in ("front", "back"):
        # The back takes the face alone: with the front as well, Klein turned the body forward (GPU trial, §2.3).
        wanted = (("face", "character_face"),)
    elif panel in VIEW_EDITS:
        if not panels.get("plate"):
            return [_entry(code, "location", "reference", asset["image"])] if asset.get("image") else []
        wanted = (("plate", "location"),)
    elif panel == "stress":
        return reference_plan([asset, *together, *([setting] if setting else [])])
    else:
        return []
    return [_entry(code, role, name, panels[name]) for name, role in wanted if panels.get(name)]


# ---------- §3.3 first-frame prompt ----------

def _usage(plan, assets, frames=(), described=None):
    """One sentence per mentioned asset: a pictured one says which picture does which job, numbered by the plan
    (image k is plan[k-1]); for the codes in ``described`` (None: every asset) its locked description (and an
    object's shape lock) follows. An asset without a picture is described in words, or named."""
    by_code = {asset["code"]: asset for asset in assets}
    frame_text = {frame["code"]: frame.get("sentence", "") for frame in frames}
    groups = {}
    for number, entry in enumerate(plan, 1):
        groups.setdefault(entry["assetCode"], []).append((number, entry))
    sentences = []
    for code, entries in groups.items():
        if all(entry["role"] == "take_frame" for _, entry in entries):
            said = _clause(frame_text.get(code) or f"Match the setting and lighting of shot {code}")
            sentences.append(f"Image {entries[0][0]}: {said[:1].lower() + said[1:]}.")
            continue
        asset = by_code.get(code) or {"code": code, "kind": asset_kind(code), "name": code}
        kind, name = asset.get("kind") or asset_kind(code), asset.get("name") or code
        full = described is None or code in described
        description, lock = _sentence(asset.get("description")), _sentence(asset.get("lock"))
        numbers = [number for number, _ in entries]
        if kind == "character":
            faces = [n for n, entry in entries if entry["role"] == "character_face" and entry["panel"] != "reference"]
            bodies = [n for n, entry in entries if entry["role"] == "character_body"]
            if not faces and not bodies:
                use = f"same face and clothes as in image {numbers[0]}"
            else:
                use = ", ".join(([f"same face from image {faces[0]}"] if faces else []) +
                                ([f"same clothes from image {bodies[0]}"] if bodies else []))
            images = " and ".join(f"image {number}" for number in numbers)
            sentence = f"The person in {images} is {name}: {use}."
            sentences.append(f"{sentence} {description}".strip() if full else sentence)
        elif kind == "location":
            sentence = (f"The place is the one in image {numbers[0]}: take only its space and materials, "
                        f"with the framing and colour written here.")
            sentences.append(f"{sentence} {description}".strip() if full else sentence)
        else:
            detail = " ".join(part for part in (description, lock) if part)
            sentences.append(f"The {bare_name(name)} is the object in image {numbers[0]}: {detail}" if full and detail
                             else f"The {bare_name(name)} is the object in image {numbers[0]}.")
    for asset in assets:
        if asset["code"] in groups:
            continue
        kind, name = asset.get("kind") or asset_kind(asset["code"]), asset.get("name") or asset["code"]
        full = described is None or asset["code"] in described
        description, lock = _clause(asset.get("description")), _sentence(asset.get("lock"))
        if kind == "character":
            sentences.append(f"{name}: {description}." if full and description else f"{name} is in the frame.")
        elif kind == "location" and full and description:
            sentences.append(f"The place: {description}.")
        elif kind == "prop":
            detail = " ".join(part for part in (_sentence(description), lock) if part)
            sentences.append(f"The {bare_name(name)}: {detail}" if full and detail else f"The {bare_name(name)} is in the frame.")
    return " ".join(sentences)


def _camera_head(optical, motion):
    """``Cinematic film still.``, the shot size if the camera cells name one, and the lens without the camera body."""
    parts = ["Cinematic film still."]
    size = _SHOT_SIZE.search(f"{motion or ''} {optical or ''}")
    lens = str(optical or "").split("/")[-1].strip().rstrip(".")
    if size:
        parts.append(_sentence(size[1][:1].upper() + size[1][1:].lower()))
        lens = _clause(_SHOT_SIZE.sub("", lens))  # "85mm close-up": the size is said once
    if lens:
        parts.append(f"{lens} lens." if len(lens.split()) <= 4 else _sentence(lens))
    return " ".join(parts)


def image_reference_prompt(shot, plan, limit=IMAGE_LIMIT):
    """§3.3, for the image model: natural, positive sentences in a fixed order, at most ``limit`` characters. Over the
    limit it drops the Film and Color lines, then the light, then the locked descriptions (the usage sentences stay)."""
    names = shot.get("names") or {}
    look = shot.get("look") or {}
    assets = shot.get("assets") or []
    head = _camera_head(shot.get("optical"), shot.get("framing", shot.get("motion")))
    action, _ = split_sections(shot.get("still_action", ""))
    state = still_state(name_tags(action, names))
    place = next((asset for asset in assets if asset.get("kind") == "location" and asset.get("light")), None)
    light = " ".join(part for part in (_sentence(first_sentence(place["light"])) if place else "",
                                       f"Lighting: {_clause(look['light'])}." if look.get("light") else "") if part)
    film = look.get("filmStill", look.get("film", ""))
    style = " ".join(part for part in (f"Film: {_clause(film)}." if film else "",
                                       f"Color: {_clause(look['color'])}." if look.get("color") else "") if part)
    people = _people(len(shot.get("characters") or ()))
    frames = shot.get("frames") or ()
    full = _usage(plan, assets, frames)
    for parts in ((head, state, full, light, style, people), (head, state, full, light, people)):
        text = "\n".join(part for part in parts if part)
        if len(text) <= limit:
            return text
    for described in _fewer_descriptions(assets):
        text = "\n".join(part for part in (head, state, _usage(plan, assets, frames, described), people) if part)
        if len(text) <= limit:
            return text
    # The action alone is too long: keep as much of it as fits, in whole sentences or words.
    short = _usage(plan, assets, frames, set())
    rest = "\n".join(part for part in (head, short, people) if part)
    state = _fit(state, limit - len(rest) - 1)
    return _fit("\n".join(part for part in (head, state, short, people) if part), limit)


def _fewer_descriptions(assets):
    """The sets of assets whose locked text an over-long image prompt keeps, from all of them to none: places go first
    (their picture carries them), then objects, then characters, each from the last mentioned."""
    codes = [asset["code"] for asset in assets]
    rank = {"location": 0, "prop": 1, "character": 2}
    order = sorted(reversed(codes), key=lambda code: rank.get(asset_kind(code), -1))
    kept = list(codes)
    yield set(kept)
    for code in order:
        kept.remove(code)
        yield set(kept)


# ---------- §3.2 video skeleton ----------

def _reference_line(asset):
    line = f"@{asset['code']} ({asset.get('name') or asset['code']}) — {_clause(asset.get('description')) or 'as pictured'}."
    if asset.get("kind") == "location":
        line += " Take only the space and the materials."
    if asset.get("kind") == "prop" and asset.get("lock"):
        line += f" Shape lock: {_sentence(asset['lock'])}"
    return line


def _audio(lines, voices, names):
    if not lines:
        return NOBODY_SPEAKS
    order, said = [], {}
    for code, line in lines:
        if code not in said:
            order.append(code)
            said[code] = []
        said[code].append(line)
    sentences = []
    for code in order:
        quoted = ", then ".join(f'"{line}"' for line in said[code])
        label = "Line, and nothing else:" if len(said[code]) == 1 else "Lines, and nothing else, in this order:"
        stop = "" if said[code][-1][-1:] in ".!?。…" else "."
        if code is None:
            sentences.append(f"{label} {quoted}{stop}")
            continue
        name = names.get(code) or names.get(base_of(code)) or code
        voice = voices.get(code) or voices.get(base_of(code)) or ""
        speaker = f'{name} voice (verbatim): "{_clause(voice)}".' if voice else f"{name} speaks."
        sentences.append(f"{speaker} {label} {quoted}{stop}")
    return "\n".join(sentences + [ONLY_QUOTED])


def _render(blocks):
    return "\n\n".join(f"[ORDER: {_flat(text)}]" if name == "ORDER" else f"{name}:\n{text}" for name, text in blocks)


def fit_blocks(blocks, budget):
    """(text, dropped names): whole blocks dropped in ``DROP_ORDER`` until the text fits ``budget``; a text that
    still does not fit keeps every remaining block whole."""
    text, dropped = _render(blocks), []
    for name in DROP_ORDER:
        if len(text) <= budget:
            break
        if any(block == name for block, _ in blocks):
            blocks = [(block, body) for block, body in blocks if block != name]
            dropped.append(name)
            text = _render(blocks)
    return text, dropped


def video_skeleton(shot, budget=DEFAULT_VIDEO_BUDGET):
    """§3.2, for the video model: (prompt, dropped block names). Fixed blocks in a fixed order with upper-case titles;
    a block with nothing to say is left out, and over ``budget`` characters whole blocks are dropped (``fit_blocks``)."""
    names = shot.get("names") or {}
    look = shot.get("look") or {}
    assets = shot.get("assets") or []
    characters = list(shot.get("characters") or ())
    places = [asset for asset in assets if asset.get("kind") == "location"]
    props = [asset for asset in assets if asset.get("kind") == "prop"]
    cast = list({asset["code"]: asset for asset in assets if asset.get("kind") == "character"}.values())
    action, sections = split_sections(shot.get("video_action", ""))
    sections = {label: name_tags(text, names) for label, text in sections.items()}
    spoken = dialogue(action, characters)
    voices = {asset["code"]: asset.get("voice") or "" for asset in assets}
    people = [name for _, name in characters]
    seconds = timed_seconds(action)
    duration = shot.get("duration") or (f"{seconds:g} seconds" if seconds else "")
    label = str(shot.get("label") or "").strip()
    moves = [sentence for sentence in dict.fromkeys(shot.get("moves") or ()) if sentence]
    blocks = []

    def block(name, *lines):
        text = "\n".join(line for line in lines if line)
        if text.strip():
            blocks.append((name, text))

    block("SCENE CONTEXT",
          f"EXACT {len(people)} CHARACTER{'S' * (len(people) > 1)} — NO DUPLICATES: {', '.join(people)}."
          if people else "No people in frame.",
          # What the shot plays is the ACTION TIMING block; repeating its first segment here would only spend budget.
          f"Shot {label}." if label else "",
          f"Location: {_join([asset.get('name') for asset in places])}." if places else "",
          f"Duration: {_clause(duration)}." if duration else "",
          "Hard cuts exactly where the action timing marks them." if _CUTS.search(action) else
          "One continuous shot, no cuts.")
    block("ACTIVE REFERENCES", *[_reference_line(dict(asset, description=name_tags(asset.get("description"), names)))
                                 for asset in assets])
    block("LOCATION MAP", *[str(asset.get("geo") or "").strip() for asset in places])
    block("FIRST FRAME AND BLOCKING", FIRST_FRAME)
    block("OPTICS", _sentence(shot.get("optical")))
    block("CAMERA", " ".join(moves) if moves else _sentence(shot.get("motion")) or STAYS_PUT)
    block("ACTION TIMING", name_tags(action, names))
    block("PHYSICS", sections.get("PHYSICS", ""))
    block("LIGHTING", *[str(asset.get("light") or "").strip() for asset in places],
          f"Lighting: {_clause(look['light'])}." if look.get("light") else "")
    block("AUDIO", _audio(spoken, voices, dict(names, **{code: name for code, name in characters})))
    block("CHARACTER ACTING", *[f"{asset.get('name') or asset['code']}: {name_tags(asset['acting'], names)}"
                                for asset in cast if str(asset.get("acting") or "").strip()])
    block("STYLE", f"Film: {_clause(look['film'])}." if look.get("film") else "",
          f"Color: {_clause(look['color'])}." if look.get("color") else "")
    block("POSITIVE CONSTRAINTS",
          f"Exactly {len(people)} {'person' if len(people) == 1 else 'people'} in frame: {_join(people)}; "
          f"each appears once." if people else "The frame stays empty of people.",
          *[f"The {asset.get('name') or asset['code']} keeps its exact shape: {_sentence(asset['lock'])}"
            for asset in props if str(asset.get("lock") or "").strip()],
          sections.get("CHECK", ""))
    block("ORDER", sections.get("ORDER", ""))
    return fit_blocks(blocks, budget)


def compile_shot(shot, budget=None):
    """The SPEC_21 keys of a shot generation (``empty_keys`` shape)."""
    plan = reference_plan(shot.get("assets") or [], shot.get("frames") or ())
    video, dropped = video_skeleton(shot, video_budget() if budget is None else budget)
    return dict(empty_keys(), reference_plan=plan, image_reference_prompt=image_reference_prompt(shot, plan),
                video_skeleton_prompt=video, dropped_blocks=dropped)


# ---------- §3.4 asset panels and edits ----------

def stress_prompt(asset, plan, variation=0, together=(), setting=None, limit=IMAGE_LIMIT):
    """A stress test (§3.4): the assets' pictures used as in §3.3, in one of ``STRESS_VARIATIONS``; the characters
    tested together share the pose sentence."""
    pose, light, view = STRESS_VARIATIONS[int(variation) % len(STRESS_VARIATIONS)]
    pool = [asset, *together, *([setting] if setting else [])]
    people = [item for item in [asset, *together] if item.get("kind") == "character"]
    if asset.get("kind") == "character":
        action = f"{_join([item.get('name') or item['code'] for item in people])} {pose}, {light}."
    elif asset.get("kind") == "prop":
        action = f"The {asset.get('name') or asset['code']} {view}, {light}."
    else:
        action = f"The place {view}, {light}."
    for described in _fewer_descriptions(pool):
        text = "\n".join(part for part in ("Cinematic film still.", _usage(plan, pool, described=described), action,
                                           _people(len(people))) if part)
        if len(text) <= limit:
            return text
    return _fit(text, limit)


def asset_panel_prompt(asset, panel, plan=(), *, variation=0, together=(), setting=None):
    """§3.4: the prompt of one panel of an asset, from the LIRA-style templates; "" for a panel the asset's kind does
    not have, and for the composed sheet."""
    kind = asset.get("kind") or asset_kind(asset["code"])
    description = _clause(asset.get("description")) or asset.get("name") or asset["code"]
    if panel == "stress":
        return stress_prompt(asset, plan, variation, together, setting)
    # face, front and back: the GPU-proven texts of SPEC_21 §3.4 (2026-10-29 Klein trial), word for word around the
    # build and clothes of the description. The front keeps its head (the server crops it at selection, §2.3).
    build, clothes = split_description(description)
    if kind == "character" and panel == "face":
        collar = re.split(r",\s*", clothes)[0] if build else ""
        opening = (f"Close-up studio photograph of {_lower_article(build)}; {collar} shows at the neck." if collar else
                   f"Close-up studio photograph of {_lower_article(description)}.")
        return (f"{opening} Head and shoulders, face turned slightly in three-quarter view, eyes looking just past the "
                f"camera. Neutral mid-grey studio backdrop, soft flat light from one side, real unretouched skin with "
                f"visible pores, fine vellus hair and natural asymmetry, a small catch-light in each eye. Plain "
                f"documentary studio photograph, natural colour.")
    if kind == "character" and panel == "front":
        stands, possessive, footwear = _figure(description)
        return (f"Full-body studio photograph from the front of the person in image 1, "
                f"{_lower_article(build) + ', ' if build else ''}wearing {clothes}. {stands} straight facing the camera, "
                f"arms relaxed at {possessive} sides, feet slightly apart, the whole figure from the top of the head to "
                f"the {footwear} in frame with a margin of grey above the head and below the feet. Neutral mid-grey "
                f"studio backdrop, flat even light, real fabric texture, plain documentary studio photograph.")
    if kind == "character" and panel == "back":
        return (f"Full-body studio photograph of {_lower_article(build) or 'the person'} seen from directly behind, the "
                f"person in image 1 turned completely away from the camera. We see the back of the head and the hair, "
                f"the back of every garment — {clothes} — and the heels of the shoes. The arms hang relaxed at the "
                f"sides with the backs of the hands toward the camera, feet slightly apart, the whole figure in frame "
                f"with a margin of grey above the head and below the feet. Neutral mid-grey studio backdrop, flat even "
                f"light, real fabric texture, plain documentary studio photograph.")
    if kind == "location" and panel == "plate":
        light = _clause(first_sentence(asset.get("light")))
        return (f"Wide three-quarter view of {description}, empty of people, camera at eye height looking diagonally "
                f"across the space, {light + ', ' if light else ''}real materials, cinematic film still.")
    if kind == "prop" and panel == "product":
        return (f"Photorealistic three-quarter overhead product photograph of {description} on a neutral grey surface, "
                f"soft directional light, isolated object, plain unbranded surfaces. {_sentence(asset.get('lock'))}"
                ).strip()
    return ""


def changed_text(description):
    """The change a variant's description states after "Changed:" (the STATE prefix, §2.2), else the description."""
    match = re.search(r"\bChanged:\s*(.+?)(?:\.\s|\.?$)", _flat(description))
    return _clause(match[1]) if match else _clause(description)


def edit_prompt(asset, panel, change="", *, variant=False):
    """§3.4 edit: change one named thing in image 1 and keep the rest exactly; "" when the panel is not an edit.

    A variant names its change (else the "Changed:" of its description) and keeps what its kind is made of. A location's
    reverse or side angle names the new viewpoint and where things now stand, and keeps the place itself."""
    kind = asset.get("kind") or asset_kind(asset["code"])
    if variant:
        return EDIT.format(change=_clause(change) or changed_text(asset.get("description")),
                           preserve=PRESERVE.get(kind, PRESERVE["character"]))
    if panel in VIEW_EDITS:
        return EDIT.format(change=_clause(change) or VIEW_CHANGES[panel], preserve=VIEW_PRESERVE)
    return ""


def compile_asset(asset, panel, *, variation=0, together=(), setting=None, base_code=None, base=None,
                  base_panels=None, change=""):
    """The SPEC_21 keys of an asset panel generation (``empty_keys`` shape). A variant generation (``base_code`` and
    ``base_panels`` given) edits its base's same panel; its stress tests are its own."""
    keys = empty_keys()
    if panel not in PANELS:
        return keys
    variant = base_code is not None and base_panels is not None and panel != "stress"
    plan = panel_plan(asset, panel, together=together, setting=setting, base_code=base_code if variant else None,
                      base=base, base_panels=base_panels)
    keys["reference_plan"] = plan
    if panel in PANEL_PROMPTS:
        keys["asset_panel_prompt"] = asset_panel_prompt(asset, panel, plan, variation=variation, together=together,
                                                        setting=setting)
    if panel in REFERENCE_PANELS:
        # These panels render on the reference card (flux-reference-key), which reads image_reference_prompt.
        keys["image_reference_prompt"] = keys["asset_panel_prompt"]
    if panel in VIEW_EDITS or variant:
        keys["edit_prompt"] = edit_prompt(asset, panel, change or (asset.get("change") if variant else ""),
                                          variant=variant)
    return keys
