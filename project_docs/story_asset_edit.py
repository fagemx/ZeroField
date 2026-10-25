"""PATCH /assets/{id}: the Soul Cast cells beyond name and prompt (voice, status, notes)."""
from __future__ import annotations

from project_docs import story_openapi as story
from project_docs.doc_schema import STATUSES

VOICE, STATUS, NOTES = 4, 5, 6  # Soul Cast columns: Voice / Audio Profile, Status, Notes


def refuse(message):
    raise story.StoryError(400, "DRAMA_REQUEST_FAILED", message)


def extra_edits(row, body):
    """{cell index: text} for the voice, status and notes the request carries; nothing else is touched.

    A look variant (CAST-01:night) keeps its OUTFIT/POSE/LOOK kind in the notes cell, so a PATCH never overwrites it:
    the empty notes a look shows pass as a no-op, any other notes on a look are refused, and the kind words are not
    accepted as notes on a variant that has no kind yet (they would be read back as one).
    """
    edits = {}
    if "voice" in body:
        edits[VOICE] = story.text(body, "voice")
    if "status" in body:
        status = body["status"]
        if not isinstance(status, str) or status not in STATUSES:
            refuse("Unsupported status. Use one of: " + ", ".join(s for s in STATUSES if s.isascii()) + ".")
        edits[STATUS] = status
    if "notes" in body:
        notes, cells = story.text(body, "notes"), row["cells"]
        if story.look_kind(cells):
            if notes:
                refuse("A look variant keeps its kind in the notes cell, so its notes cannot be edited.")
        elif ":" in story.asset_code(cells[0]) and notes in story.LOOK_KINDS:
            refuse("Notes on a look variant cannot be " + ", ".join(story.LOOK_KINDS) + ": those words mark a look's kind.")
        else:
            edits[NOTES] = notes
    return edits


def with_looks(defaults, everything):
    """The default assets of an episode, each saying how many looks it has and how many of those lack a picture of their own.

    The wall's card reads "2 looks without an image" from this, so it needs no request per card. `everything` is every
    Soul Cast asset row (looks included); a look is a row whose code is the asset's code plus ":key".
    """
    looks = {}
    for item in everything:
        if not item["isDefault"]:
            counts = looks.setdefault(item["assetCode"].split(":")[0], {"total": 0, "missingImages": 0})
            counts["total"] += 1
            counts["missingImages"] += 0 if item["selectedImageUrl"] else 1
    return [{**item, "looks": looks.get(item["assetCode"], {"total": 0, "missingImages": 0})} for item in defaults]
