"""Look catalog (SPEC_19 §4.3): camera, camera-move, genre, era, tempo, palette and light options as concrete picture
descriptions.

Each option stores the English text that goes into the prompt, never a bare name: a label alone ("Noir", "Static
Tripod") is ignored by the models or drawn as a prop. Camera options are written into a shot's ``Optical Rig`` column;
camera moves are ``#id`` tags inside the prompt, expanded where they stand because their position says when the move
happens (§1.2 G). The catalog has no real brands, people or titles; image models letter camera brands onto props.

The two kinds of package B are whole sentences ending with a full stop. The five kinds of package C (SPEC_19 R11) are
clauses that ``compile_look`` joins into a line, so every one of them has a lowercase start, no full stop and no ``;``
(the joiner): genre, era and tempo make the ``Film`` line, in that order, joined by ``; ``; a palette clause becomes the
``Color`` line followed by ``; palette`` and its colour codes (``hex``: 1 to 12 ``#RRGGBB``, the main colour first, which
only a palette option has); a light clause is the ``Lighting`` line. Every kind starts with an Auto option whose text is
empty: it adds nothing to the prompt.

An episode's look (``validate_episode_look``) picks a genre, era, tempo, palette and light and a camera body, lens and
aperture; a shot overrides genre, era, tempo, palette and light (``validate_shot_look``). The shot has no camera
override: its camera is its own Optical Rig cell, and the episode camera only stands in when that cell is empty.

Pure text: the Studio worker's context compiler imports this module, so it reads only its own catalog file (once, and
only when a prompt holds a ``#`` candidate) and never touches the database or the network.
"""
from __future__ import annotations

import copy
import json
import re
from functools import lru_cache
from pathlib import Path

CATALOG_PATH = Path(__file__).with_name("look_catalog.json")
# Kinds this catalog accepts, with the groups a kind is split into (one choice per group).
KINDS = {"camera": ("body", "lens", "aperture"), "move": (), "genre": (), "era": (), "tempo": (), "palette": (), "light": ()}
# Every kind SPEC_19 §4.3 names: what GET /catalog/looks?kind= accepts. A kind the packaged catalog has no options for
# yet lists nothing; any other kind is an error.
API_KINDS = ("camera", "move", "genre", "era", "tempo", "palette", "light")
# Package C: kinds whose text is a clause compile_look joins into a line, and the kinds of the Film line in their order.
CLAUSE_KINDS = ("genre", "era", "tempo", "palette", "light")
FILM_KINDS = ("genre", "era", "tempo")
# What an episode look and a shot's override may set. A shot's camera is its Optical Rig cell.
EPISODE_KEYS = ("genre", "era", "tempo", "camera", "palette", "light")
SHOT_KEYS = ("genre", "era", "tempo", "palette", "light")
ITEM_KEYS = {"id", "kind", "group", "labelKey", "promptText", "preview", "hex"}
ID_PATTERN = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
LABEL_KEY_PATTERN = re.compile(r"[a-z][A-Za-z0-9]*(?:\.[A-Za-z0-9_]+)+")
HEX_PATTERN = re.compile(r"#[0-9A-F]{6}")
MAX_HEX = 12
# A move tag opens a word: whitespace or the start of a line before it, so the wardrobe form @CAST-01#night is never a
# move (§1.2 F). The id may be followed by CJK text or punctuation but not by more ASCII id characters.
MOVE_TAG = re.compile(r"(?<!\S)#([a-z][a-z0-9-]{1,40})(?![A-Za-z0-9_-])")
# Punctuation that may close the clause a tag ends; the sentence then drops its own full stop before it.
_CLOSING = set(".,;:!?)]}…。，、；：！？）」』】")


class LookCatalogError(ValueError):
    """A malformed catalog or look, or an option id the catalog does not have.

    A refused look also names its problem for a translated message: ``reason`` (``lookNotObject``,
    ``unknownLookSetting``, ``unknownLookOption``) and ``params``, the values the English message was filled with."""

    def __init__(self, message, reason=None, **params):
        super().__init__(message)
        self.reason, self.params = reason, params


def validate(data):
    """Check a catalog document and return its index {(kind, id): item}; raise LookCatalogError on the first problem."""
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("items"), list):
        raise LookCatalogError("The look catalog must be {version: 1, items: [...]}.")
    index, labels, groups = {}, set(), {}
    for position, item in enumerate(data["items"]):
        where = f"look catalog item {position}"
        if not isinstance(item, dict):
            raise LookCatalogError(f"{where} must be an object.")
        unknown = set(item) - ITEM_KEYS
        if unknown:
            raise LookCatalogError(f"{where} has unknown keys: {', '.join(sorted(unknown))}.")
        kind, item_id, group = item.get("kind"), item.get("id"), item.get("group")
        if kind not in KINDS:
            raise LookCatalogError(f"{where} has an unknown kind: {kind!r}.")
        # 2 to 41 characters: every move id must also be a whole #tag body (MOVE_TAG).
        if not isinstance(item_id, str) or not 2 <= len(item_id) <= 41 or not ID_PATTERN.fullmatch(item_id):
            raise LookCatalogError(f"{where} needs a lowercase hyphenated id of 2 to 41 characters, not {item_id!r}.")
        where = f"look option {kind}:{item_id}"
        if KINDS[kind]:
            if group not in KINDS[kind]:
                raise LookCatalogError(f"{where} needs a group from {', '.join(KINDS[kind])}.")
        elif "group" in item:
            raise LookCatalogError(f"{where} belongs to a kind without groups.")
        if (kind, item_id) in index:
            raise LookCatalogError(f"{where} is listed twice; ids are unique within a kind.")
        label = item.get("labelKey")
        if not isinstance(label, str) or not LABEL_KEY_PATTERN.fullmatch(label):
            raise LookCatalogError(f"{where} needs a dotted i18n labelKey.")
        if not label.startswith(f"lookCatalog.{kind}."):
            raise LookCatalogError(f"{where} needs a labelKey under lookCatalog.{kind}.")
        if label in labels:
            raise LookCatalogError(f"{where} reuses labelKey {label}.")
        text = item.get("promptText")
        if not isinstance(text, str) or text != text.strip() or not text.isascii() or "\n" in text:
            raise LookCatalogError(f"{where} needs promptText as one trimmed line of English.")
        if kind in CLAUSE_KINDS:
            # compile_look joins these into one line with "; ", so a clause neither opens nor closes a sentence.
            if text and (not text[0].islower() or text.endswith(".") or ";" in text):
                raise LookCatalogError(f"{where} promptText must be one clause: a lowercase start, no full stop and no ';'.")
        elif text and not text.endswith("."):
            raise LookCatalogError(f"{where} promptText must be a sentence ending with a full stop.")
        if kind == "camera" and "/" in text:
            # A still keeps only the text after the last "/" of the Optical Rig column (context_compiler).
            raise LookCatalogError(f"{where} promptText must not contain '/'.")
        if kind != "palette" and "hex" in item:
            raise LookCatalogError(f"{where} has colours; only a palette option has hex.")
        if kind == "palette" and not text and "hex" in item:
            raise LookCatalogError(f"{where} is Auto, which has no colours.")
        if kind == "palette" and text:
            colours = item.get("hex")
            if (not isinstance(colours, list) or not 1 <= len(colours) <= MAX_HEX or len(set(map(str, colours))) != len(colours)
                    or not all(isinstance(colour, str) and HEX_PATTERN.fullmatch(colour) for colour in colours)):
                raise LookCatalogError(f"{where} needs hex: 1 to {MAX_HEX} different #RRGGBB colours, the main colour first.")
        if "preview" in item and not isinstance(item["preview"], dict):
            raise LookCatalogError(f"{where} preview must be an object.")
        members = groups.setdefault((kind, group), [])
        # Every choice starts with Auto: the empty description, so nothing has to be set to generate (§3.3).
        if not members and text:
            raise LookCatalogError(f"{where} comes first in its group, which must start with an Auto option.")
        if members and not text:
            raise LookCatalogError(f"{where} is a second Auto option in its group.")
        members.append(item_id)
        index[(kind, item_id)] = item
        labels.add(label)
    for kind, kind_groups in KINDS.items():
        for group in kind_groups or (None,):
            if (kind, group) not in groups:
                raise LookCatalogError(f"The look catalog has no {kind} options" + (f" for {group}." if group else "."))
    return index


def load(path=CATALOG_PATH):
    """Read and validate a catalog file; returns the document."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise LookCatalogError(f"The look catalog cannot be read: {error}") from error
    validate(data)
    return data


@lru_cache(maxsize=1)
def _index():
    return validate(load())


def catalog():
    """The packaged catalog's options in file order, as copies the caller may change."""
    return copy.deepcopy(list(_index().values()))


def option(kind, item_id):
    """The catalog option for kind:id, or None."""
    return _index().get((kind, item_id))


def api_item(item):
    """One option as GET /catalog/looks lists it.

    ``{id, kind, group?, labelKey, promptText, preview: {poster, clip} | null, hex?}``: ``group`` only for a kind split
    into groups (camera: body, lens, aperture), ``hex`` only for an option that has colours (palette), ``preview`` null
    until the option has sample media (``clip`` null for a still sample).
    """
    preview = item.get("preview") if isinstance(item.get("preview"), dict) else None
    result = {"id": item["id"], "kind": item["kind"]}
    if "group" in item:
        result["group"] = item["group"]
    result |= {"labelKey": item["labelKey"], "promptText": item["promptText"],
               "preview": {"poster": preview.get("poster"), "clip": preview.get("clip")}
               if preview and (preview.get("poster") or preview.get("clip")) else None}
    if "hex" in item:
        result["hex"] = list(item["hex"])
    return result


def api_items(kind=None):
    """The options of GET /catalog/looks in catalog order: every kind, or one kind of API_KINDS.

    Raises LookCatalogError for a kind outside API_KINDS; a known kind without options yet is an empty list.
    """
    if kind is not None and kind not in API_KINDS:
        raise LookCatalogError(f"Unknown look kind: {kind!r}.")
    return [api_item(item) for item in _index().values() if kind is None or item["kind"] == kind]


def camera_text(body=None, lens=None, aperture=None):
    """The Optical Rig sentence for a body, lens and aperture choice; Auto (or None / '') adds nothing."""
    parts = []
    for group, value in (("body", body), ("lens", lens), ("aperture", aperture)):
        if value is None or value == "":
            continue
        item = option("camera", value)
        if item is None or item["group"] != group:
            raise LookCatalogError(f"Unknown camera {group}: {value!r}.")
        if item["promptText"]:
            parts.append(item["promptText"])
    return " ".join(parts)


# ---------- looks (SPEC_19 R11, R12) ----------

def _settings(value, keys, name):
    """value as an object whose keys are all in keys; name is the look or its part in messages."""
    if not isinstance(value, dict):
        raise LookCatalogError(f"{name} must be an object of look settings.", "lookNotObject", setting=name)
    unknown = sorted(str(key) for key in value if key not in keys)
    if unknown:
        key = (name.partition(".")[2] + "." if "." in name else "") + unknown[0]
        raise LookCatalogError(f"Unknown look setting '{key}'; use {', '.join(keys)}.", "unknownLookSetting",
                               key=key, keys=", ".join(keys))
    return value


def _option_id(kind, value, setting, group=None):
    """value as the id of a kind option (of group, for a camera); setting names it in messages."""
    item = option(kind, value) if isinstance(value, str) else None
    if item is None or item.get("group") != group:
        shown = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        raise LookCatalogError(f"Unknown {setting} option '{shown}'; choose an option from the look catalog.",
                               "unknownLookOption", setting=setting, id=shown)
    return value


def validate_episode_look(value):
    """A checked copy of an episode look ``{genre, era, tempo, camera: {body, lens, aperture}, palette, light}``.

    Every key is optional; a value is an option id of its kind (a camera value: a camera id of that group). A null
    sets nothing, like a missing key, and is left out, as is a camera without parts. Raises LookCatalogError."""
    _settings(value, EPISODE_KEYS, "look")
    result = {}
    for key in EPISODE_KEYS:
        if value.get(key) is None:
            continue
        if key == "camera":
            parts = _settings(value[key], KINDS["camera"], "look.camera")
            camera = {group: _option_id("camera", parts[group], f"camera {group}", group)
                      for group in KINDS["camera"] if parts.get(group) is not None}
            if camera:
                result[key] = camera
        else:
            result[key] = _option_id(key, value[key], key)
    return result


def validate_shot_look(value):
    """A checked copy of a shot's look override ``{genre, era, tempo, palette, light}``.

    Each value is an option id of its kind, or null for "back to the episode" (kept: a change says what it removes).
    There is no camera: a shot's camera is its Optical Rig cell. Raises LookCatalogError."""
    _settings(value, SHOT_KEYS, "look")
    return {key: None if value[key] is None else _option_id(key, value[key], key) for key in SHOT_KEYS if key in value}


def compile_look(episode_look, shot_look, *, still=False):
    """The look lines of one shot: ``{"film", "color", "light", "camera"}`` as text, "" for each part that adds nothing.

    The shot's override wins per kind (an id, Auto included); a null or missing override falls back to the episode.
    ``film`` is the genre, era and tempo clauses in that order, joined by "; " (Auto adds nothing, so no separator is
    left over); a still drops tempo, which is motion and pacing. ``color`` is the palette clause followed by
    "; palette" and its colour codes, ``light`` the light clause, and ``camera`` the episode camera's Optical Rig text
    (``camera_text``), which stands in only for an empty Optical Rig cell. Raises LookCatalogError."""
    episode = validate_episode_look(episode_look if episode_look is not None else {})
    shot = validate_shot_look(shot_look if shot_look is not None else {})
    chosen = {kind: shot.get(kind) if shot.get(kind) is not None else episode.get(kind) for kind in SHOT_KEYS}
    items = {kind: option(kind, value) if value else None for kind, value in chosen.items()}
    text = {kind: item["promptText"] if item else "" for kind, item in items.items()}
    film = "; ".join(text[kind] for kind in FILM_KINDS if text[kind] and not (still and kind == "tempo"))
    color = f"{text['palette']}; palette {', '.join(items['palette']['hex'])}" if text["palette"] else ""
    return {"film": film, "color": color, "light": text["light"], "camera": camera_text(**episode.get("camera", {}))}


def source_look(episode_look, shot_look):
    """The ``look`` a worker task source carries (SPEC_19 §1.2 H), or None when it would add nothing.

    ``compile_look`` of the clip, plus ``filmStill``: the Film line ``compile_look(..., still=True)`` writes for a still.
    One source then serves a still and a clip alike: a source is built before (and, for the Story API's quotes, apart
    from) the choice of output, and the context compiler only picks the line for its output."""
    look = dict(compile_look(episode_look, shot_look), filmStill=compile_look(episode_look, shot_look, still=True)["film"])
    return look if any(look.values()) else None


def move_tokens(text):
    """[(position of '#', move id)] for every catalog move tag in text, in order; unknown #words are not tags."""
    # A prompt without a candidate never reads the catalog.
    return [(match.start(), match[1]) for match in MOVE_TAG.finditer(str(text or "")) if option("move", match[1])]


def expand_moves(text, still=False):
    """Replace each catalog move tag with its sentence where it stands; a still drops the tags instead.

    Unknown #words and every other character stay as written, so the segment order of a timed prompt is kept.
    Auto expands to nothing, like a tag in a still: the tag goes with one side of its spacing.
    """
    text = str(text or "")
    tokens = move_tokens(text)
    if not tokens:
        return text
    out, last = [], 0
    for position, item_id in tokens:
        end = position + 1 + len(item_id)
        sentence = "" if still else option("move", item_id)["promptText"]
        before = text[last:position]
        if sentence:
            following = text[end:end + 1]
            if following and not following.isspace():
                sentence = sentence[:-1] if following in _CLOSING else sentence + " "
            out += [before, sentence]
            last = end
            continue
        kept = before.rstrip(" \t")
        if kept and not kept.endswith(("\n", "\r")):
            out.append(kept)  # "Kael turns. #push-in He walks." -> "Kael turns. He walks."
            last = end
            continue
        # The tag opens its line (or follows a dropped tag): keep the indentation, drop the space after the tag.
        after = end
        while after < len(text) and text[after] in " \t":
            after += 1
        out.append(kept if after == len(text) or text[after] in "\r\n" else before)
        last = after
    out.append(text[last:])
    return "".join(out)
