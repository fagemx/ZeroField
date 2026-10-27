"""SPEC_19 R15/R16: a shot quoting another shot's take, ``@S02.end`` / ``@S02.start``.

A tag names a moment of another shot in the same episode: ``.end`` its cut's out point (the take's last frame when it is
not trimmed), ``.start`` its in point. On submit each tag is frozen into a snapshot (SPEC_19 1.2 L, 4.5)::

    {shotId, shotIndex, edge, takeUrl, at, frameUrl, use, adopted, lastFrameAt}

which the job and the new take's ``storyProvenance.takeRefs`` keep: which take was quoted, at which second, as what. The
take is the quoted shot's adopted take, or the newest take in its cell (``adopted: false``). An untrimmed ``.end`` needs the
take's length, so ``at`` stays null until the worker has probed the take; the worker then cuts the frame once with
``extract_frame``'s ``source_url``, stores it as an asset and records ``frameUrl``, ``at`` and ``lastFrameAt``. The
thumbnail and the picture the model received are the same file, and a retry reuses it.

Nothing upstream ever rewrites a take: ``is_stale`` only says that the quoted take, or its cut point, is no longer what the
tag resolves to now.

The text functions are pure. The Studio worker's context compiler imports this module, so the Story API (database) and the
worker runtime are imported inside the functions that need them.
"""
from __future__ import annotations

import math
from pathlib import Path
import re
import tempfile

# SPEC_19 4.5. ASCII: \w and \b mean what they mean in JavaScript, so the editor and the server agree on a tag that is
# followed or preceded by CJK text ("接續@S02.end的動作"). Asset codes always have a hyphen and never .start/.end, so
# @CAST-01:night, @CAST-01#night and @SET-01 are never take references.
TAKE_REF = re.compile(r"(?<![\w@:#-])@([A-Za-z]?\d{1,3}[A-Za-z]?)\.(start|end)\b", re.ASCII)
USE_KEY = re.compile(r"([A-Za-z]?\d{1,3}[A-Za-z]?)\.(start|end)", re.ASCII)
EDGES = ("start", "end")
USES = ("first_frame", "reference")
MAX_REFS = 6
_FRAME_URL = re.compile(r"/projects/api/[a-z0-9-]+/assets/pa_[0-9a-f]{32}")
# Punctuation that may close the clause a tag ends; the sentence then drops its own full stop before it.
_CLOSING = set(".,;:!?)]}…。，、；：！？）」』】")
_OPENING = set("([{（「『【")


def tokens(text):
    """[(start, end, code, edge)] of every take reference in text, in order."""
    return [(match.start(), match.end(), match[1], match[2]) for match in TAKE_REF.finditer(str(text or ""))]


def ref_key(code, edge):
    """The ``takeRefUses`` key of a tag: ``S02.end``."""
    return f"{str(code).strip().upper()}.{edge}"


def _same(a, b):
    return str(a or "").strip().casefold() == str(b or "").strip().casefold()


def describe(ref):
    """The sentence a tag becomes in the prompt (context_compiler; a promptOverride at submit)."""
    name = str(ref.get("shotIndex") or "").strip()
    if ref.get("use") == "first_frame":
        return (f"Continue directly from the final frame of shot {name}." if ref.get("edge") == "end"
                else f"Begin from the opening frame of shot {name}.")
    return f"Match the setting and lighting of shot {name}."


def expand(text, refs):
    """Replace each tag that has a snapshot with its sentence, where it stands; other text, and tags without a snapshot,
    stay as written."""
    text = str(text or "")
    found = tokens(text)
    if not found or not refs:
        return text
    out, last = [], 0
    for start, end, code, edge in found:
        ref = next((r for r in refs if r.get("edge") == edge and _same(r.get("shotIndex"), code)), None)
        if ref is None:
            continue
        sentence = describe(ref)
        before, following = text[start - 1:start], text[end:end + 1]
        if before and not before.isspace() and before not in _OPENING:
            sentence = " " + sentence
        if following and not following.isspace():
            sentence = sentence[:-1] if following in _CLOSING else sentence + " "
        out += [text[last:start], sentence]
        last = end
    out.append(text[last:])
    return "".join(out)


def _segment(shot):
    """(beat keys, segment index, segment count) of a shot cut from one beat of the screenplay, else None."""
    origin = shot.get("storyOrigin") or {}
    recipes = origin.get("recipes") or []
    if origin.get("mapping") != "exact" or len(recipes) != 1 or "segmentIndex" not in recipes[0]:
        return None
    recipe = recipes[0]
    return (tuple(recipe.get("beatKeys") or ()), recipe["segmentIndex"], recipe.get("segmentCount")) if recipe.get("beatKeys") else None


def default_use(edge, shot, quoted):
    """SPEC_19 §7 decision 7: the out point of the shot just before, in the same continuous action, is the first frame;
    everything else is a reference. Same continuous action means the screenplay beat both shots were cut from (adjacent
    segments of one beat), or a split of the quoted shot. Without that evidence: reference."""
    if edge != "end":
        return "reference"
    lineage = shot.get("storyLineage") or {}
    if lineage.get("operation") == "split" and quoted.get("shotId") in (lineage.get("fromShotIds") or []):
        return "first_frame"
    before, after = _segment(quoted), _segment(shot)
    if before and after and before[0] == after[0] and before[2] == after[2] and after[1] == before[1] + 1:
        return "first_frame"
    return "reference"


def parse_uses(value):
    """{``S02.end``: use} of a request's ``takeRefUses``."""
    from project_docs import story_openapi as story
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > MAX_REFS:
        story.invalid(f'takeRefUses must map at most {MAX_REFS} tags such as "S02.end" to first_frame or reference.')
    uses = {}
    for key, use in value.items():
        match = USE_KEY.fullmatch(key[1:] if isinstance(key, str) and key.startswith("@") else key) if isinstance(key, str) else None
        if not match or use not in USES:
            story.invalid('takeRefUses must map tags such as "S02.end" to first_frame or reference.')
        name = ref_key(*match.groups())
        if name in uses:
            story.invalid(f"takeRefUses names {name} twice.")
        uses[name] = use
    return uses


def resolve(text, shots, shot, uses=None):
    """Snapshots of the take references in the prompt of a generation about to be queued for ``shot``.

    ``shots`` are the shot views of the shot's episode (``story_openapi.shots``), ``shot`` the generating shot's view.
    Raises StoryError: 400 DRAMA_VALIDATION_FAILED for tags that name no shot of the episode (or several), with the tags in
    ``details``; 422 for a shot quoting itself or an invalid ``takeRefUses``; 409 DRAMA_STAGE_PRECONDITION for a quoted shot
    without any take.
    """
    from project_docs import story_openapi as story
    from project_docs.story_adoption import ADOPTED
    uses = parse_uses(uses)
    written = {}
    for start, end, code, edge in tokens(text):
        written.setdefault(ref_key(code, edge), str(text)[start:end])
    if set(uses) - set(written):
        story.invalid("takeRefUses names tags the prompt does not contain: " + ", ".join(sorted(set(uses) - set(written))) + ".")
    if len(written) > MAX_REFS:
        story.invalid(f"A prompt can quote at most {MAX_REFS} takes.")
    unknown, ambiguous, quoted = [], [], {}
    for key, tag in written.items():
        hits = [s for s in shots if _same(s.get("shotIndex"), key.rsplit(".", 1)[0])]
        if not hits:
            unknown.append(tag)
        elif len(hits) > 1:
            ambiguous.append(tag)
        else:
            quoted[key] = hits[0]
    if unknown or ambiguous:
        details = {"unknownTakeRefs": unknown, **({"ambiguousTakeRefs": ambiguous} if ambiguous else {})}
        message = "These tags name no shot of this episode: " + ", ".join(unknown) + "." if unknown else ""
        if ambiguous:
            message = (message + " " if message else "") + "These tags name several shots of this episode: " + ", ".join(ambiguous) + "."
        raise story.StoryError(400, "DRAMA_VALIDATION_FAILED", message, details)
    if any(found["shotId"] == shot["shotId"] for found in quoted.values()):
        story.invalid("A shot cannot quote its own take; quote another shot of the episode.")
    empty = [written[key] for key, found in quoted.items() if not found.get("selectedVideoUrl")]
    if empty:
        raise story.StoryError(409, "DRAMA_STAGE_PRECONDITION", "Shoot a take before quoting it: " + ", ".join(empty) + ".",
                               {"takeRefsWithoutTake": empty})
    refs = []
    for key, found in quoted.items():
        edge = key.rsplit(".", 1)[1]
        trim = found.get("trim") or {}
        at = (trim.get("in") or 0) if edge == "start" else trim.get("out")
        refs.append({"shotId": found["shotId"], "shotIndex": found["shotIndex"], "edge": edge, "takeUrl": found["selectedVideoUrl"],
                     "at": None if at is None else float(at), "frameUrl": None,
                     "use": uses.get(key) or default_use(edge, shot, found), "adopted": found.get("reviewStatus") in ADOPTED,
                     "lastFrameAt": None})
    if sum(ref["use"] == "first_frame" for ref in refs) > 1:
        story.invalid("Only one quoted take can be the first frame; quote the others as reference.")
    return refs


def edge_seconds(edge, trim, last_frame_at=None):
    """Second of a take's ``edge`` under ``trim``: ``.start`` the in point; ``.end`` the out point, never past the last frame,
    or the last frame when untrimmed (None while the take's length is unknown)."""
    trim = trim if isinstance(trim, dict) else {}
    if edge == "start":
        return float(trim.get("in") or 0)
    if trim.get("out") is None:
        return last_frame_at
    return float(trim["out"]) if last_frame_at is None else min(float(trim["out"]), last_frame_at)


def is_stale(ref, now_take_url, now_trim):
    """True once the tag no longer resolves to the frame the snapshot quoted: the quoted shot now resolves to another take
    (it adopted another one, or its newest unadopted take changed, or it is gone), or its cut moved that edge."""
    if not now_take_url or now_take_url != ref.get("takeUrl"):
        return True
    now, then = edge_seconds(ref.get("edge"), now_trim, ref.get("lastFrameAt")), ref.get("at")
    if now is None or then is None:
        return now is not then
    return abs(float(now) - float(then)) > 1e-6


def frozen(job):
    """The take reference snapshots of a queued job."""
    return list(((job or {}).get("storyProvenance") or {}).get("takeRefs") or [])


def worker_refs(refs):
    """What the context compiler needs of each prepared snapshot."""
    return [{"shotIndex": r["shotIndex"], "edge": r["edge"], "use": r["use"], "frameUrl": r["frameUrl"]} for r in refs]


def worker_input(source, refs):
    """The worker task input: the frozen row snapshot, plus ``take_refs`` when the prompt quoted takes."""
    return dict(source, take_refs=worker_refs(refs)) if refs else source


def compiler_refs(source):
    """The validated ``take_refs`` of a worker task input (context_compiler)."""
    from project_assistant.studio import runtime
    refs = source.get("take_refs") or []
    if not isinstance(refs, list) or len(refs) > MAX_REFS:
        raise runtime.WorkerError("take_refs must be a short list")
    for ref in refs:
        if (not isinstance(ref, dict) or ref.get("use") not in USES or ref.get("edge") not in EDGES
                or not isinstance(ref.get("shotIndex"), str) or not isinstance(ref.get("frameUrl"), str)
                or not _FRAME_URL.fullmatch(ref["frameUrl"])):
            raise runtime.WorkerError("Each take reference needs a shot, an edge, a use and its prepared frame asset")
    if sum(ref["use"] == "first_frame" for ref in refs) > 1:
        raise runtime.WorkerError("Only one take reference can be the first frame")
    return refs


class _OneTake:
    """The worker head with the quoted take already read: the probe and the cut use one copy of it."""

    def __init__(self, head, url, raw, mime):
        self.head, self.url, self.raw, self.mime = head, url, raw, mime

    def asset(self, task, url):
        return (self.raw, self.mime) if url == self.url else self.head.asset(task, url)

    def upload(self, task, data, mime, filename=None):
        return self.head.upload(task, data, mime, filename)

    def lease_lost(self):
        return getattr(self.head, "lease_lost", lambda: False)()


def _cut(task_id, slug, ref, head, index):
    """{at, lastFrameAt, frameUrl} of one snapshot: probe the take, settle the second, cut and store the frame."""
    from project_assistant import limb_worker as worker
    task = {"id": f"{task_id}:takeref:{index}", "project_slug": slug, "input": {}}
    raw, mime = head.asset(task, ref["takeUrl"])
    if not raw or not isinstance(mime, str) or not mime.startswith("video/"):
        raise worker.WorkerError(f"The take quoted from shot {ref['shotIndex']} is not a video.")
    config = {}
    if callable(getattr(type(head), "outbound_timeout", None)):
        config = {"timeout": head.outbound_timeout(1800), "probe_timeout": head.outbound_timeout(60)}
    with tempfile.TemporaryDirectory(prefix="zerofield-takeref-") as folder:
        path = Path(folder) / "take.mp4"
        path.write_bytes(raw)
        media = worker._probe_video(path, config)
    # The last frame's timestamp, rounded down to FFmpeg's microsecond clock so the seek lands on it, not past it.
    last = math.floor((media["frames"] - 1) / media["fps"] * 1e6) / 1e6
    at = edge_seconds(ref["edge"], {"in": ref.get("at")} if ref["edge"] == "start" else {"out": ref.get("at")}, last)
    output = worker.ffmpeg(task, dict(config, mode="extract_frame", source_url=ref["takeUrl"], timestamp_sec=at),
                           _OneTake(head, ref["takeUrl"], raw, mime))
    frame = output.get("asset_url") if isinstance(output, dict) else None
    if not isinstance(frame, str) or not _FRAME_URL.fullmatch(frame) or not str(output.get("content_type", "")).startswith("image/"):
        raise worker.WorkerError(f"The frame quoted from shot {ref['shotIndex']} could not be stored.")
    return {"at": at, "lastFrameAt": last, "frameUrl": frame}


def prepare_frames(task_id, slug, refs, head, operation=None):
    """The snapshots with their frames cut (worker preparation, before the generation is submitted).

    A snapshot that already has its ``frameUrl`` (a retry of the same job) is kept as frozen. ``operation(key, action)``
    runs each cut inside the caller's accounting boundary (``execution_governance.run_operation``).
    """
    prepared = []
    for index, ref in enumerate(refs):
        ref = dict(ref)
        if not ref.get("frameUrl"):
            cut = lambda ref=ref, index=index: _cut(task_id, slug, ref, head, index)
            ref.update(operation(f"takeref:{index}", cut) if operation else cut())
        prepared.append(ref)
    return prepared


def _receipts(conn, takes):
    """Video receipts of the production, read once per Takes (one request)."""
    from project_docs import story_openapi as story
    if getattr(takes, "_take_ref_receipts", None) is None:
        takes._take_ref_receipts = [r for r in story.records(conn, "story_media_receipt", takes.slug) if r.get("kind") == "video"]
    return takes._take_ref_receipts


def view_refs(conn, slug, identifier, adoption, takes):
    """``takeRefs`` of a shot view: the references of its adopted take, each compared with what its tag resolves to now.

    ``[{shotId, shotIndex, edge, takeUrl, at, use, stale, nowTakeUrl, frameUrl, adopted}]``; empty while nothing is
    adopted. ``nowTakeUrl`` is the take the quoted shot holds now (its adoption, else its newest take), null once the shot is
    gone; ``shotIndex`` is its current label.
    """
    if not adoption or not adoption.get("adopted") or not adoption.get("url"):
        return []
    from project_docs import story_openapi as story, story_trim, writing_impact
    url = adoption["url"]
    evidence = writing_impact.candidate_evidence([r for r in takes.records(identifier) if r.get("url") == url] +
                                                 [r for r in _receipts(conn, takes) if r.get("entityId") == identifier and r.get("url") == url], url)
    refs = (evidence or {}).get("takeRefs") or []
    now = {}
    result = []
    for ref in refs:
        if ref["shotId"] not in now:
            try:
                _, row = story.find_row(conn, ref["shotId"], "shot")
            except story.StoryError:
                now[ref["shotId"]] = (None, None, None)
            else:
                take = story_trim.take_url(row)
                now[ref["shotId"]] = (take, story_trim.view(story.shot_meta(conn, ref["shotId"]), take), row["cells"][0])
        take, trim, index = now[ref["shotId"]]
        result.append({"shotId": ref["shotId"], "shotIndex": index or ref.get("shotIndex"), "edge": ref["edge"],
                       "takeUrl": ref.get("takeUrl"), "at": ref.get("at"), "use": ref.get("use"), "stale": is_stale(ref, take, trim),
                       "nowTakeUrl": take, "frameUrl": ref.get("frameUrl"), "adopted": ref.get("adopted")})
    return result
