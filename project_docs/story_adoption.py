"""SPEC_19 R1: adopting a take puts it in the cut.

One action replaces "pick, approve, check the film". A video take goes into the shot's video cell and the shot's status
becomes ``Approved`` in a single ``mutate_row`` (one tab lock, one revision); the trim starts over and ``meta_<shotId>``
records ``adoption: {url, at, by}``. A pipeline take still waiting for review is adopted through ``apply_proposal`` (the
M8 gate) and never through the candidate pick (SPEC_19 1.2 K); its status write follows in the same transaction. A
first-frame candidate only changes the keyframe cell and never the status (1.2 J).

Nothing here commits: the Story HTTP handler commits once or rolls the whole adoption back, so a failure anywhere leaves
neither the take, the status, the proposal decision nor the record behind (1.2 A).

Old data needs no migration (1.2 C): an ``Approved`` row without a record adopted "the take in its cell, at an unknown
time", and a candidate without ``createdAt`` is older than any adoption.
"""
from __future__ import annotations

from datetime import datetime

from project_docs import repository as repo, story_openapi as story
from project_assistant.table_edits import cell_value

# The legacy completed status reads as adopted too, as the film cut already does.
ADOPTED = ("Approved", "已完成")
CHOICES = ("videoId", "proposalId", "imageId")


def status_index(row):
    """Index of the row's Status column, or None (shot_view reads the same header)."""
    return next((i for i, header in enumerate(row["headers"]) if header.casefold() == "status"), None)


def row_status(row):
    index = status_index(row)
    return row["cells"][index] if index is not None and index < len(row["cells"]) else ""


def _instant(value):
    try:
        moment = datetime.fromisoformat(value) if isinstance(value, str) and value else None
    except ValueError:
        return None
    return moment if moment is None or moment.tzinfo else None


def latest_created(records):
    """{url: newest createdAt} of candidate records; content-addressed equal renders keep the newest time."""
    newest = {}
    for item in records:
        moment = _instant(item.get("createdAt"))
        if moment and (item["url"] not in newest or moment > _instant(newest[item["url"]])):
            newest[item["url"]] = item["createdAt"]
    return newest


def adoption_view(meta, status, video_url):
    """``{adopted, url, at, by}`` or None.

    Adopted: the row's status is ``Approved``; the take in the cut is the one in the cell. The record supplies the time and
    the crew member only while it still names that take; otherwise (legacy approval, or a sheet edit swapped the cell) both
    are unknown (None). Not adopted but a record exists (the shot was sent to Retake after an adoption): the last adoption,
    so a newer take can still be told apart. ``DELETE /adoption`` removes the record; with neither, None.
    """
    saved = meta.get("adoption") if isinstance(meta.get("adoption"), dict) else None
    if status in ADOPTED:
        known = saved if saved and saved.get("url") == video_url else {}
        return {"adopted": True, "url": video_url, "at": known.get("at"), "by": known.get("by")}
    if saved:
        return {"adopted": False, "url": saved.get("url"), "at": saved.get("at"), "by": saved.get("by")}
    return None


class Takes:
    """The video takes behind shot views, read at most once per request.

    The take list is ``GET /shots/{id}/videos``: every video the cell ever held (revision history), the cell, and the Story
    API candidates. A listing reads each sheet's history once instead of once per shot.
    """

    def __init__(self, conn, slug):
        self.conn, self.slug = conn, slug
        self._records = None
        self._history = {}

    def records(self, identifier):
        if self._records is None:
            self._records = [c for c in story.records(self.conn, "candidate", self.slug) if c.get("kind") == "video"]
        return [c for c in self._records if c.get("entityId") == identifier]

    def history(self, tab_key):
        """{rid: [video URLs in revision order]}, read exactly as candidate_list reads one row."""
        if tab_key not in self._history:
            columns = {}
            for row in story.table_rows(self.conn, self.slug, tab_key):
                try:
                    columns[row["rid"]] = story.media_column(row, "video")
                except story.StoryError:
                    pass
            urls = {rid: [] for rid in columns}
            for revision in repo.revision_rows(self.conn, self.slug, tab_key=tab_key):
                for table in revision["doc"].get("content", []):
                    if table.get("type") != "table":
                        continue
                    for old in table.get("content", [])[1:]:
                        rid = old.get("attrs", {}).get("bid")
                        column = columns.get(rid)
                        if column is not None and column < len(old.get("content", [])):
                            url = story.media_url(cell_value(old["content"][column], {}))
                            if url:
                                urls[rid].append(url)
            self._history[tab_key] = urls
        return self._history[tab_key]


def take_summary(takes, row, adoption):
    """``{total, newSinceAdoption}`` of a shot's video takes.

    total: the length of ``GET /shots/{id}/videos``. newSinceAdoption: takes other than the adopted one whose ``createdAt``
    is later than the adoption. A take without ``createdAt`` (history, uploads, older candidates) is older than any
    adoption. A legacy approval has no time: every take with a ``createdAt`` counts, because a render that arrives while a
    shot is adopted no longer enters its cell. Never adopted (no record): every take is still waiting to be chosen.
    Pending pipeline proposals are not counted here; the shot panel merges them from the reviewer's own proposals.
    """
    identifier = story.shot_id(takes.slug, row)
    try:
        current = story.media_url(row["cells"][story.media_column(row, "video")])
    except story.StoryError:
        current = None
    records = takes.records(identifier)
    urls = list(dict.fromkeys(takes.history(row["tabKey"]).get(row["rid"], []) + ([current] if current else []) +
                              [c["url"] for c in records]))
    if adoption is None:
        return {"total": len(urls), "newSinceAdoption": len(urls)}
    created, since = latest_created(records), _instant(adoption.get("at"))
    fresh = [url for url in urls if url != adoption.get("url") and url in created
             and (since is None or _instant(created[url]) > since)]
    return {"total": len(urls), "newSinceAdoption": len(fresh)}


def view(conn, slug, identifier):
    return story.shot_view(conn, slug, story.find_row(conn, identifier, "shot")[1], takes=Takes(conn, slug))


def _writable(conn, me, slug):
    if not me.can_write:
        raise story.StoryError(409, "DRAMA_OPERATION_NOT_ALLOWED", "Read-only crew members cannot adopt takes.")
    story.authorize(conn, me, slug, write=True)


def _status_column(row):
    index = status_index(row)
    if index is None:
        raise story.StoryError(409, "DRAMA_STAGE_PRECONDITION", "This production sheet has no Status column to record an adoption.")
    return index


def _not_this_shot(what="Take"):
    return story.StoryError(404, "DRAMA_NOT_FOUND", f"{what} does not belong to this shot.")


def _proposal_take(conn, slug, row, value):
    """(proposal id, kind, URL) of a pending pipeline take for this row; 404 for anything else."""
    from project_assistant import store
    if isinstance(value, bool) or not isinstance(value, (int, str)) or not str(value).isdigit() or len(str(value)) > 18:
        story.invalid("proposalId must be a proposal number.")
    proposal = store.proposal(conn, int(value))
    target = (proposal or {}).get("target") or {}
    ops = target.get("ops") or []
    if (not proposal or proposal["slug"] != slug or proposal["action"] != "table_edit" or target.get("tab_key") != row["tabKey"]
            or not ops or any(op.get("op") != "put_row" or op.get("rid") != row["rid"] or not op.get("base") for op in ops)):
        raise _not_this_shot("Proposal")

    def proposed(kind):
        try:
            column = story.media_column(row, kind)
        except story.StoryError:
            return None
        for op in ops:
            cells = (op.get("node") or {}).get("content", [])
            if column in (op.get("edited_cols") or []) and column < len(cells):
                url = story.media_url(cell_value(cells[column], {}))
                if url:
                    return url
        return None
    video, image = proposed("video"), proposed("image")
    if not video and not image:
        raise _not_this_shot("Proposal")
    return proposal["id"], "video" if video else "image", video or image


def _apply(conn, me, slug, proposal_id):
    """apply_proposal inside this transaction; anything short of an applied proposal aborts the whole adoption."""
    from project_assistant import service
    status, result = service.apply_proposal(conn, me, slug, proposal_id, {})
    if status >= 400:
        code = {400: (422, "DRAMA_VALIDATION_FAILED"), 404: (404, "DRAMA_NOT_FOUND")}.get(status, (409, "DRAMA_OPERATION_NOT_ALLOWED"))
        raise story.StoryError(*code, (result or {}).get("error") or "The proposal could not be applied.")
    decided = (result or {}).get("proposal") or {}
    if decided.get("status") != "applied":
        # A flow-bound write conflict is recorded as a failed proposal with status 200; rolling back keeps it pending instead.
        raise story.StoryError(409, "DRAMA_OPERATION_NOT_ALLOWED", decided.get("error") or "The proposal could not be applied; review it again.")


def _record(conn, me, slug, identifier, url):
    meta = story.record(conn, "meta_" + identifier, required=False, lock=True) or {}
    meta["adoption"] = {"url": url, "at": story.now(), "by": me.actor_id}
    story.store(conn, "meta_" + identifier, "shot_meta", meta, slug)


def adopt(conn, me, identifier, body):
    """POST /shots/{id}/adoptions with exactly one of videoId (candidate), proposalId (pending pipeline take) or imageId."""
    from project_docs import story_trim
    chosen = [key for key in CHOICES if key in body]
    if len(chosen) != 1:
        story.invalid("Send exactly one of videoId, proposalId or imageId.")
    key = chosen[0]
    slug, row = story.find_row(conn, identifier, "shot")
    _writable(conn, me, slug)
    if key == "imageId":
        # A first frame is chosen, not adopted: the status and the cut are unchanged.
        story.select_candidate(conn, me, identifier, "image", {"imageId": body["imageId"]})
        return view(conn, slug, identifier)
    if key == "proposalId":
        proposal_id, kind, url = _proposal_take(conn, slug, row, body["proposalId"])
        status = _status_column(row) if kind == "video" else None
        _apply(conn, me, slug, proposal_id)
        if kind == "image":
            return view(conn, slug, identifier)
        _, row = story.find_row(conn, identifier, "shot")
        if story.media_url(row["cells"][story.media_column(row, "video")]) != url:
            raise story.StoryError(409, "DRAMA_OPERATION_NOT_ALLOWED", "The proposal did not place its take in this shot.")
        story.mutate_row(conn, me, slug, row["tabKey"], row["rid"], {status: "Approved"})
    else:
        status = _status_column(row)
        take = next((c for c in story.candidate_list(conn, identifier, "video") if c["videoId"] == body["videoId"]), None)
        if not take:
            raise _not_this_shot()
        url = take["url"]
        # The take and the status land in one sheet edit: both or neither.
        story.mutate_row(conn, me, slug, row["tabKey"], row["rid"], {story.media_column(row, "video"): f"[Video]({url})", status: "Approved"})
    story_trim.reset(conn, slug, identifier)
    _record(conn, me, slug, identifier, url)
    return view(conn, slug, identifier)


def unadopt(conn, me, identifier):
    """DELETE /shots/{id}/adoption: an adopted status goes back to blank and the record goes; the cell keeps its take.

    Another status (Retake, Blocked) is not an adoption and is left as it is, so the call is safe to repeat.
    """
    slug, row = story.find_row(conn, identifier, "shot")
    _writable(conn, me, slug)
    index = _status_column(row)
    if row_status(row) in ADOPTED:
        story.mutate_row(conn, me, slug, row["tabKey"], row["rid"], {index: ""})
    meta = story.record(conn, "meta_" + identifier, required=False, lock=True)
    if meta and "adoption" in meta:
        meta.pop("adoption")
        story.store(conn, "meta_" + identifier, "shot_meta", meta, slug)
    return view(conn, slug, identifier)
