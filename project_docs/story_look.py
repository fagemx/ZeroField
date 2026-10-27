"""Look catalog (SPEC_19 §4.3): camera and camera-move options as concrete picture descriptions.

Each option stores the English sentence that goes into the prompt, never a bare name: a label alone ("Noir", "Static
Tripod") is ignored by the models or drawn as a prop. Camera options are written into a shot's ``Optical Rig`` column;
camera moves are ``#id`` tags inside the prompt, expanded where they stand because their position says when the move
happens (§1.2 G). The catalog has no real brands, people or titles; image models letter camera brands onto props.

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
# Kinds this catalog accepts, with the groups a kind is split into (one choice per group). SPEC_19 package C adds
# genre, era, tempo, palette and light together with their own rules.
KINDS = {"camera": ("body", "lens", "aperture"), "move": ()}
ITEM_KEYS = {"id", "kind", "group", "labelKey", "promptText", "preview"}
ID_PATTERN = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
LABEL_KEY_PATTERN = re.compile(r"[a-z][A-Za-z0-9]*(?:\.[A-Za-z0-9_]+)+")
# A move tag opens a word: whitespace or the start of a line before it, so the wardrobe form @CAST-01#night is never a
# move (§1.2 F). The id may be followed by CJK text or punctuation but not by more ASCII id characters.
MOVE_TAG = re.compile(r"(?<!\S)#([a-z][a-z0-9-]{1,40})(?![A-Za-z0-9_-])")
# Punctuation that may close the clause a tag ends; the sentence then drops its own full stop before it.
_CLOSING = set(".,;:!?)]}…。，、；：！？）」』】")


class LookCatalogError(ValueError):
    """A malformed catalog, or an option id the catalog does not have."""


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
        if label in labels:
            raise LookCatalogError(f"{where} reuses labelKey {label}.")
        text = item.get("promptText")
        if not isinstance(text, str) or text != text.strip() or not text.isascii() or "\n" in text:
            raise LookCatalogError(f"{where} needs promptText as one trimmed line of English.")
        if text and not text.endswith("."):
            raise LookCatalogError(f"{where} promptText must be a sentence ending with a full stop.")
        if kind == "camera" and "/" in text:
            # A still keeps only the text after the last "/" of the Optical Rig column (context_compiler).
            raise LookCatalogError(f"{where} promptText must not contain '/'.")
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
