"""The one scene-heading rule every screenplay reader shares (R44-3).

A scene heading is a line that STARTS with, in order:

1. optional whitespace and a literal Markdown hash run (``#`` to ``######``), kept as text, never rendered;
2. an optional scene number: ``1.``, ``1``, ``12A.``, ``1)`` or ``#3``;
3. one of ``Scene N``, ``場景 N`` / ``场景 N`` (Chinese or Arabic numerals), ``INT.``, ``EXT.``,
   ``INT./EXT.`` (also ``INT/EXT``, ``EXT./INT.``), or the uppercase-only ``I/E`` and ``EST.``.

``INT.``/``EXT.``/``Scene`` are case-insensitive as before. ``I/E`` and ``EST.`` must be uppercase so a
prose line such as "Est. 1902, the dam ..." is not a scene. The words never count mid-line.

Users: ``writing_structure`` (block scenes), ``story_adaptation`` (adaptation, Markdown, cues),
``story_openapi`` (text scenes), ``writing_files`` (import sections). The browser copy is
``ui/src/writing/sceneHeading.js``; ``tests/fixtures/scene_heading_cases.json`` holds both to the same answers.

The title helpers below are server-only (the browser never composes a heading): ``numbered_title`` is the one
"Scene NN: name" form every writer of our own headings uses, and ``scene_location`` is the place a slugline names,
which untagged scenes share a set by (story_adaptation.scene_set_codes).
"""
from __future__ import annotations

import re

_DIGIT = "[0-9０-９]"
_LEAD = r"\s*(?:#{1,6}\s*)?"
_NUMBER = rf"(?:#?{_DIGIT}{{1,4}}[A-Za-z]{{0,2}}(?:[.)]\s*|\s+))?"
_END = r"(?![0-9A-Za-z_])"
_ANY_CASE = (rf"Scene\s*{_DIGIT}+|[場场]景\s*[一二三四五六七八九十{_DIGIT[1:-1]}]+"
             rf"|INT\.?\s*/\s*EXT{_END}\.?|EXT\.?\s*/\s*INT{_END}\.?|INT\.|EXT\.")
_UPPER = rf"EST\.|I\s*/\s*E{_END}\.?"
PATTERN = rf"^{_LEAD}{_NUMBER}(?:{_ANY_CASE}|(?-i:{_UPPER}))"

HEADING = re.compile(PATTERN, re.I)
"""``HEADING.match(line)``: does this one line (or block text) start a scene?"""
HEADING_LINES = re.compile(PATTERN, re.I | re.M)
"""``HEADING_LINES.search(text)``: does any line of this text start a scene?"""

_HASHES = re.compile(r"^\s*(?:#{1,6}\s*)?")
_LABEL = re.compile(rf"^{_NUMBER}(?:Scene\s*{_DIGIT}+(?:[A-Za-z](?![A-Za-z]))?|[場场]景\s*[一二三四五六七八九十{_DIGIT[1:-1]}]+)?\s*[:：.\-]?\s*", re.I)


def is_heading(line) -> bool:
    return isinstance(line, str) and bool(HEADING.match(line))


def heading_title(line: str) -> str:
    """The heading line as a title: literal hashes and outer whitespace removed, number and label kept."""
    return _HASHES.sub("", line, count=1).strip()


def scene_name(line: str) -> str:
    """What follows the scene number and any Scene N / 場景 N label ("1. INT. DAM" -> "INT. DAM")."""
    return _LABEL.sub("", heading_title(line), count=1).strip()


def scene_label(title) -> str:
    """A scene title without its own number or Scene N label ("1. INT. DAM" -> "INT. DAM"); other titles as they are."""
    title = (title or "").strip()
    return scene_name(title) if is_heading(title) else title


def numbered_title(index: int, title, fallback: str = "Scene") -> str:
    """The heading we write for scene ``index``: "Scene 01: INT. DAM - NIGHT", never "Scene 01: 1. INT. DAM - NIGHT"."""
    return f"Scene {index:02d}: {scene_label(title) or fallback}"


_SLUG = re.compile(rf"^(?:(?:INT\.?\s*/\s*EXT|EXT\.?\s*/\s*INT){_END}\.?|INT\.|EXT\.|(?-i:EST\.|I\s*/\s*E{_END}\.?))\s*", re.I)
_SEGMENT = re.compile(r"\s+[-–—]+\s+|\s*[–—]+\s*")
# The time-of-day words a slugline ends on ("- NIGHT", "- MOMENTS LATER", "- CONTINUOUS", "- DAY/NIGHT", "- MOVING").
_TIME = frozenset("""NIGHT DAY DAWN DUSK MORNING EVENING AFTERNOON NOON MIDNIGHT SUNSET SUNRISE TWILIGHT NIGHTFALL DAYBREAK
    PRE-DAWN LATER MOMENTS MINUTES HOURS CONTINUOUS SAME TIME SIMULTANEOUS MAGIC HOUR FIRST LIGHT LATE EARLY NEXT A FEW
    PRESENT FLASHBACK DREAM MOVING TRAVELING""".split())


def scene_location(title) -> str:
    """The place a slugline title names, as written: "1. INT. SPILLWAY CONTROL ROOM - NIGHT" -> "SPILLWAY CONTROL ROOM".

    INT./EXT./I/E/EST., a trailing "(FLASHBACK)"-style note and trailing time-of-day segments are dropped; a title that is not a slugline ("Scene 02: Dawn")
    names no place and gives "".
    """
    name = scene_label(title)
    slug = _SLUG.match(name)
    if not slug:
        return ""
    place = re.sub(r"(?:\s*\([^()]*\))+\s*$", "", name[slug.end():])
    parts = [part.strip(" .") for part in _SEGMENT.split(place)]
    while len(parts) > 1 and all(word in _TIME for word in re.split(r"[\s/]+", parts[-1].strip("() ").upper()) if word):
        parts.pop()
    return " - ".join(part for part in parts if part).strip(" .-")


def place_key(text) -> str:
    """The comparable form of a place name: case, punctuation and spacing folded ("Control Room" == "CONTROL ROOM.")."""
    return " ".join(re.findall(r"\w+", (text or "").casefold()))
