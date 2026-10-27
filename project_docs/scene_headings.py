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
