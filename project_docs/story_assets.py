"""SPEC_21 §2: asset-first production on the Story API.

An asset (a Soul Cast row) keeps its text locks and its panels in one ``asset_meta`` story record, ``am_<rowId>``
(``story_openapi.store``/``records``; no new table, no new column):

    {"assetCode", "rowId", "acting", "geo", "light", "lock", "change",
     "panels": {<panel>: {"url", "imageId"} | null}, "stress": [{"imageId", "url", "variation", "with", "set", "recognizable"}]}

What this module adds to the API (routed from ``story_openapi.dispatch`` and ``generation_job``):

- ``PATCH /assets/{id}/meta``, and ``meta``/``panels`` on ``GET /assets/{id}``;
- panel generations (``POST /assets/{id}/image-generations`` with ``panel``): the panel picks the card, the size and the
  source keys the compiler reads (§2.3); the request's appCode is ignored. Renders stay candidates: a panel render never
  writes the reference image cell, so the cell is always the panel a person chose;
- ``PUT /assets/{id}/panels/{panel}``: a candidate becomes a panel; a chosen front loses its head below the chin
  (``crop_front``: the front is rendered with its head, see SPEC_21 §2.3); a character's face, front and back make the
  sheet (``compose_sheet``, Pillow, no model), a scene's plate and a prop's product go straight to the reference image cell;
- stress tests (``POST|GET /assets/{id}/stress-tests``, ``PUT .../stress-tests/{imageId}``);
- the ``asset_meta`` key of every generation source (``source_meta``, §2.5) and the STATE variant prefix.
"""
from __future__ import annotations

import copy
import io
import math
import re

from project_docs import repository as repo, story_openapi as story

TEXT_FIELDS = ("acting", "geo", "light", "lock", "change")
TEXT_LIMIT = 4000
INHERITED = ("acting", "geo", "light", "lock")  # a variant's blank locks read its base asset's
PANELS = {"CHARACTER": ("face", "front", "back", "sheet"), "SCENE": ("plate", "reverse", "angle"), "PROP": ("product",)}
ALL_PANELS = ("face", "front", "back", "sheet", "plate", "reverse", "angle", "product", "stress")
SOUL_CAST, REFERENCE_KEY, KLEIN_EDIT = "flux-soul-cast", "flux-reference-key", "flux-klein-edit"
# §2.3: panel -> (card, panels of the same asset it needs first, (width, height)). A variant's panel is an edit of its
# base's same panel (KLEIN_EDIT) at the same size; "sheet" is composed, never generated.
PANEL_TABLE = {
    "face": (SOUL_CAST, (), (896, 1184)),
    "front": (REFERENCE_KEY, ("face",), (768, 1344)),
    "back": (REFERENCE_KEY, ("face",), (768, 1344)),  # the face only: with the front too the body turned to the camera
    "plate": (SOUL_CAST, (), (1344, 768)),
    "reverse": (KLEIN_EDIT, ("plate",), (1344, 768)),
    "angle": (KLEIN_EDIT, ("plate",), (1344, 768)),
    "product": (SOUL_CAST, (), (1024, 1024)),
    "stress": (REFERENCE_KEY, (), (1280, 704)),
}
COVER = {"SCENE": "plate", "PROP": "product"}  # the panel that is the reference image cell; a character's is its sheet
STRESS_COUNT, STRESS_WITH = (4, 10), 5
SHEET_HEIGHT, SHEET_GREY, FACE_SHARE = 1152, (0x8A, 0x8A, 0x8A), 0.38
# The front's head crop (§2.3, measured on four GPU renders): below the largest face the Haar cascade finds, face top +
# CHIN x face height lands at the neck; without a face, the figure's top + FIGURE_HEAD x its height. A figure pixel differs
# from the backdrop (the corners' colour) by more than FIGURE_DIFF in some channel; a figure row has FIGURE_ROW of them.
CHIN, FIGURE_HEAD, FIGURE_DIFF, FIGURE_ROW = 1.25, 0.15, 32, 0.015
REFERENCE_CELL = 3  # Soul Cast: Asset ID, Name, Locked description, Reference Image, Voice, Status, Notes
STATE_PREFIX = "Same identity as @{base}: same face, body proportions and posture. Changed: {change}."


def precondition(message):
    raise story.StoryError(409, "DRAMA_STAGE_PRECONDITION", message)


# ---------- the record ----------

def code_of(row):
    return story.asset_code(row["cells"][0])


def type_of(code):
    return "CHARACTER" if code.startswith("CAST") else "PROP" if code.startswith("PROP") else "SCENE"


def blank(row):
    code = code_of(row)
    return {"assetCode": code, "rowId": row["rid"], **{key: "" for key in TEXT_FIELDS},
            "panels": {panel: None for panel in PANELS[type_of(code)]}, "stress": []}


def meta_of(conn, row):
    """The asset's record, or a blank one (nothing is stored until something is written)."""
    found = story.record(conn, "am_" + row["rid"], required=False)
    if not found:
        return blank(row)
    return {**blank(row), **found, "panels": {**blank(row)["panels"], **(found.get("panels") or {})}}


def save(conn, slug, row, data):
    return story.store(conn, "am_" + row["rid"], "asset_meta", dict(data, assetCode=code_of(row), rowId=row["rid"]), slug)


def meta_view(data):
    return {key: data.get(key) or "" for key in TEXT_FIELDS}


def panels_view(data, code):
    panels = data.get("panels") or {}
    return {panel: dict(panels[panel]) if isinstance(panels.get(panel), dict) else None for panel in PANELS[type_of(code)]}


def asset_fields(conn, row):
    """``meta`` and ``panels`` of ``GET /assets/{id}``."""
    data = meta_of(conn, row)
    return {"meta": meta_view(data), "panels": panels_view(data, code_of(row))}


def write_meta(conn, slug, row, fields):
    """Set some of acting/geo/light/lock/change (each text up to TEXT_LIMIT characters); returns the new ``meta``."""
    if not isinstance(fields, dict) or set(fields) - set(TEXT_FIELDS):
        story.invalid("Asset meta takes acting, geo, light, lock and change only.")
    data = meta_of(conn, row)
    data.update({key: story.text(fields, key, maximum=TEXT_LIMIT) for key in fields})
    save(conn, slug, row, data)
    return meta_view(data)


def image_id(identifier, url):
    """The imageId candidate_list gives this URL on this asset."""
    return "im_" + story.digest([identifier, url])[:24]


def rows_by_code(conn, slug):
    return {code_of(row): row for row in story.table_rows(conn, slug, "soul-cast")}


def base_of(code):
    return code.split(":")[0]


# ---------- the source every generation carries (§2.5) ----------

def source_meta(conn, slug):
    """``{CODE: {acting, geo, light, lock, change, panels: {panel: url}}}`` of the assets that have a record: only the
    panels someone selected, a variant's blank locks filled from its base. {} when no asset has one."""
    rows = {row["rid"]: code_of(row) for row in story.table_rows(conn, slug, "soul-cast")}
    found = {}
    for data in story.records(conn, "asset_meta", slug):
        code = rows.get(data.get("rowId"))
        if code is None:
            continue  # the row was deleted
        panels = data.get("panels") or {}
        found[code] = {**meta_view(data), "panels": {panel: value["url"] for panel, value in panels.items()
                                                      if panel in PANELS[type_of(code)] and isinstance(value, dict) and value.get("url")}}
    for code, entry in found.items():
        base = found.get(base_of(code)) if ":" in code else None
        if base:
            entry.update({key: entry[key] or base[key] for key in INHERITED})
    return found


# ---------- panel generations (§2.3) ----------

def picture_of(data, row):
    """What a stress test can take this asset's identity from: a selected panel or its reference image."""
    return next((value["url"] for value in (data.get("panels") or {}).values() if isinstance(value, dict) and value.get("url")), None) \
        or story.media_url(row["cells"][REFERENCE_CELL])


def stress_source(conn, slug, code, request):
    """The co-stars and the set of a stress test, checked against this production's assets."""
    known = rows_by_code(conn, slug)
    with_codes = request.get("withAssets", [])
    if not isinstance(with_codes, list) or len(with_codes) > STRESS_WITH or any(not isinstance(c, str) for c in with_codes):
        story.invalid(f"withAssets lists at most {STRESS_WITH} asset codes.")
    with_codes = list(dict.fromkeys(story.asset_code(c) for c in with_codes))
    if any(c not in known or c == code for c in with_codes):
        story.invalid("withAssets must be other assets of this production.")
    set_code = request.get("setCode")
    if set_code is not None:
        if not isinstance(set_code, str) or story.asset_code(set_code) not in known or type_of(story.asset_code(set_code)) != "SCENE":
            story.invalid("setCode must be a scene asset of this production.")
        set_code = story.asset_code(set_code)
    return {"stress_with": with_codes, "stress_set": set_code}


def panel_plan(conn, slug, row, identifier, kind, body):
    """{card, size, source} of a panel generation, or a 422/409. The source keys go into the job input (the contract the
    context compiler reads): ``panel``; a stress test's ``variation`` (set per task), ``stress_with`` and ``stress_set``;
    a variant's ``base_panels`` ({panel: url}: its base's selected panels, the asked one falling back to the base's
    reference image; a front is its uncropped original) and ``change``."""
    panel = body["panel"]
    if not identifier.startswith("as_") or kind != "image":
        story.invalid("panel applies to asset image generations only.")
    code = code_of(row)
    kind_of = type_of(code)
    if not isinstance(panel, str) or panel not in ALL_PANELS:
        story.invalid("Unknown panel.")
    if panel == "sheet":
        story.invalid("The sheet is composed from the face, front and back panels; select those instead.")
    if panel == "stress" and "_stress" not in body:
        story.invalid("Run stress tests with POST /assets/{id}/stress-tests.")
    if panel != "stress" and panel not in PANELS[kind_of]:
        story.invalid(f"A {kind_of.lower()} asset has the panels {', '.join(p for p in PANELS[kind_of] if p != 'sheet')}.")
    data = meta_of(conn, row)
    card, needs, size = PANEL_TABLE[panel]
    source = {"panel": panel}
    if panel == "stress":
        if not picture_of(data, row):
            precondition("Select this asset's face panel or a reference image before stress tests.")
        source |= {"variation": 0, **body["_stress"]}
    elif ":" in code:
        base = rows_by_code(conn, slug).get(base_of(code))
        if base is None:
            precondition(f"The base asset {base_of(code)} of this variant is missing.")
        base_data = meta_of(conn, base)
        # A front is edited from its uncropped original: the edit keeps the head, the crop comes when it is chosen.
        panels = {name: value.get("originalUrl") or value["url"] for name, value in base_data["panels"].items()
                  if isinstance(value, dict) and value.get("url")}
        first = panels.get(panel) or story.media_url(base["cells"][REFERENCE_CELL])
        if not first:
            precondition(f"Give @{base_of(code)} a {panel} panel or a reference image before editing this variant from it.")
        card, source = KLEIN_EDIT, source | {"base_panels": panels | {panel: first}, "change": data.get("change") or ""}
    else:
        missing = [name for name in needs if not isinstance(data["panels"].get(name), dict)]
        if missing:
            precondition(f"Select this asset's {missing[0]} panel before generating its {panel} panel.")
    return {"card": card, "size": size, "source": source}


def apply_plan(job, plan):
    """The panel's source keys into the job input, its size into the card's width/height inputs (an explicit
    modelParams value stays). The inputs are found by fieldName, so a card without them keeps its own size."""
    job["input"].update(copy.deepcopy(plan["source"]))
    width, height = plan["size"]
    for node in job["card"]["nodes"]:
        if node["fieldName"] in ("width", "height"):
            job["values"].setdefault(f"{node['nodeId']}.{node['fieldName']}", width if node["fieldName"] == "width" else height)
    return job


def candidate_fields(job):
    """What a finished panel render's candidate record keeps of its job: the panel, and a stress test's variation,
    co-stars and set. {} for every other render."""
    source = job.get("input") or {}
    panel = source.get("panel")
    if not panel:
        return {}
    if panel != "stress":
        return {"panel": panel}
    return {"panel": panel, "variation": source.get("variation"), "with": list(source.get("stress_with") or []),
            "set": source.get("stress_set")}


def with_panels(items, stored):
    """Asset image candidates with their ``panel`` (null for history, uploads and renders before SPEC_21)."""
    panels = {}
    for item in sorted(stored, key=lambda c: c.get("createdAt") or ""):
        if item.get("panel"):
            panels[item["url"]] = item["panel"]
    return [{**item, "panel": panels.get(item["url"])} for item in items]


def only_panel(items, panel):
    if panel not in ALL_PANELS:
        story.invalid("Unknown panel.")
    return [item for item in items if item.get("panel") == panel]


# ---------- choosing a panel, the sheet (§2.4) ----------

def asset_bytes(conn, slug, url, panel):
    match = re.fullmatch(r"/projects/api/" + re.escape(slug) + r"/assets/(pa_[0-9a-f]{32})", url or "")
    found = repo.get_asset(conn, slug, match[1]) if match else None
    if not found or not found[0].startswith("image/"):
        precondition(f"The {panel} panel is not a picture of this production; select another one.")
    return found[1]


def face_line(picture):
    """Where the head ends by the face detector (OpenCV, an optional dependency): the largest face's top + CHIN x its
    height, or None (no OpenCV, no face)."""
    try:
        import cv2
        import numpy
    except ImportError:
        return None
    try:
        gray = cv2.cvtColor(numpy.array(picture), cv2.COLOR_RGB2GRAY)
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        if cascade.empty():
            return None
        faces = cascade.detectMultiScale(gray, scaleFactor=1.05, minNeighbors=5, minSize=(24, 24))
    except cv2.error:
        return None
    boxes = [tuple(int(v) for v in face) for face in faces]
    if not boxes:
        return None
    x, y, w, h = max(boxes, key=lambda box: (box[2] * box[3], box))  # the largest; ties by position, so always the same
    return int(y + CHIN * h)


def figure_line(picture):
    """Where the head ends by the figure on the backdrop (Pillow only): the figure's top + FIGURE_HEAD x its height, or
    None when nothing stands out from the corners' colour."""
    from PIL import Image, ImageChops
    width, height = picture.size
    corners = [picture.getpixel(point) for point in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1))]
    backdrop = tuple((sorted(channel)[1] + sorted(channel)[2]) // 2 for channel in zip(*corners))  # the corners' median
    difference = ImageChops.difference(picture, Image.new("RGB", picture.size, backdrop)).split()
    mask = ImageChops.lighter(ImageChops.lighter(difference[0], difference[1]), difference[2]).point(lambda v: 255 if v > FIGURE_DIFF else 0)
    rows = list(mask.resize((1, height), Image.BOX).tobytes())  # each row's share of figure pixels, 0-255
    figure = [y for y, share in enumerate(rows) if share >= 255 * FIGURE_ROW]
    if not figure:
        return None
    top, bottom = figure[0], figure[-1]
    return int(top + FIGURE_HEAD * (bottom - top))


def crop_head(raw):
    """A front rendered with its head, cut below the chin at full width: PNG bytes, or None when no cut line is found
    (the picture is kept as it is). Deterministic."""
    from PIL import Image
    with Image.open(io.BytesIO(raw)) as source:
        picture = source.convert("RGB")
    line = face_line(picture)
    if line is None:
        line = figure_line(picture)
    if line is None or not 0 < line < picture.height - 1:
        return None
    out = io.BytesIO()
    picture.crop((0, line, picture.width, picture.height)).save(out, format="PNG", optimize=False, compress_level=6)
    return out.getvalue()


def crop_front(conn, me, slug, url):
    """The chosen front without its head, stored as a new production picture: its URL (``url`` itself when no cut line
    is found). The uncropped original stays a candidate."""
    from PIL import Image
    try:
        data = crop_head(asset_bytes(conn, slug, url, "front"))
    except (OSError, ValueError, MemoryError, Image.DecompressionBombError) as exc:
        raise story.StoryError(409, "DRAMA_STAGE_PRECONDITION", "The chosen front could not be read as an image; select another one.") from exc
    if data is None:
        return url
    return f"/projects/api/{slug}/assets/" + repo.put_asset(conn, slug, data=data, content_type="image/png", actor_id=me.actor_id)


def compose(front, back, face):
    """The character sheet as PNG bytes: front (no head) | back | face, all SHEET_HEIGHT high on mid-grey, the face cell at
    least FACE_SHARE of the width (the face centred in it). Deterministic: the same three pictures give the same bytes."""
    from PIL import Image
    tiles = []
    for raw in (front, back, face):
        with Image.open(io.BytesIO(raw)) as source:
            picture = source.convert("RGB")
        width = max(1, round(picture.width * SHEET_HEIGHT / picture.height))
        tiles.append(picture.resize((width, SHEET_HEIGHT), Image.LANCZOS))
    left = tiles[0].width + tiles[1].width
    cell = max(tiles[2].width, math.ceil(FACE_SHARE * left / (1 - FACE_SHARE)))
    sheet = Image.new("RGB", (left + cell, SHEET_HEIGHT), SHEET_GREY)
    sheet.paste(tiles[0], (0, 0))
    sheet.paste(tiles[1], (tiles[0].width, 0))
    sheet.paste(tiles[2], (left + (cell - tiles[2].width) // 2, 0))
    out = io.BytesIO()
    sheet.save(out, format="PNG", optimize=False, compress_level=6)
    return out.getvalue()


def compose_sheet(conn, me, slug, identifier, panels):
    """Compose and store the sheet of a character whose face, front and back are chosen; it joins the candidates as
    panel "sheet". Returns {url, imageId}."""
    from PIL import Image
    pictures = [asset_bytes(conn, slug, panels[name]["url"], name) for name in ("front", "back", "face")]
    try:
        data = compose(*pictures)
    except (OSError, ValueError, MemoryError, Image.DecompressionBombError) as exc:  # OSError: PIL.UnidentifiedImageError
        raise story.StoryError(409, "DRAMA_STAGE_PRECONDITION", "A chosen panel could not be read as an image; select another one.") from exc
    aid = repo.put_asset(conn, slug, data=data, content_type="image/png", actor_id=me.actor_id)
    url = f"/projects/api/{slug}/assets/{aid}"
    story.store(conn, "ca_sheet_" + story.digest([identifier, url])[:32], "candidate",
                {"entityId": identifier, "kind": "image", "url": url, "createdAt": story.now(), "panel": "sheet"}, slug)
    return {"url": url, "imageId": image_id(identifier, url)}


def set_cover(conn, me, slug, row, url):
    """The reference image cell (what H3, ingredient sheets and the lookkey read) shows ``url``."""
    if story.media_url(row["cells"][REFERENCE_CELL]) != url:
        story.mutate_row(conn, me, slug, "soul-cast", row["rid"], {REFERENCE_CELL: f"[Image]({url})"})


def select_panel(conn, me, slug, row, identifier, panel, body):
    """PUT /assets/{id}/panels/{panel}: a candidate of this asset becomes the panel. A front becomes its copy cut below
    the chin ({url: the crop, imageId: the candidate's, originalUrl: the candidate's url}). A character with face, front
    and back chosen gets its sheet composed into the reference image cell; a scene's plate and a prop's product go there."""
    code = code_of(row)
    kind_of = type_of(code)
    if panel == "sheet":
        story.invalid("The sheet is composed when the face, front and back are chosen; it cannot be set by hand.")
    if panel not in PANELS[kind_of]:
        story.invalid(f"A {kind_of.lower()} asset has the panels {', '.join(p for p in PANELS[kind_of] if p != 'sheet')}.")
    wanted = story.text(body, "imageId")
    if not wanted:
        story.invalid("imageId is required: the candidate that becomes the panel.")
    chosen = next((c for c in story.candidate_list(conn, identifier, "image") if c["imageId"] == wanted), None)
    if not chosen:
        raise story.StoryError(404, "DRAMA_NOT_FOUND", "Candidate does not belong to this asset.")
    data = meta_of(conn, row)
    data["panels"][panel] = {"url": chosen["url"], "imageId": chosen["imageId"]}
    if panel == "front":
        # The front is rendered with its head; the panel is the cropped copy, the imageId stays the chosen candidate's.
        data["panels"][panel] |= {"url": crop_front(conn, me, slug, chosen["url"]), "originalUrl": chosen["url"]}
    if kind_of == "CHARACTER" and all(isinstance(data["panels"].get(name), dict) for name in ("face", "front", "back")):
        data["panels"]["sheet"] = compose_sheet(conn, me, slug, identifier, data["panels"])
        set_cover(conn, me, slug, row, data["panels"]["sheet"]["url"])
    elif COVER.get(kind_of) == panel:
        set_cover(conn, me, slug, row, chosen["url"])
    save(conn, slug, row, data)
    current = story.find_row(conn, identifier, "asset")[1]
    return {"meta": meta_view(data), "panels": panels_view(data, code), "selectedImageUrl": story.media_url(current["cells"][REFERENCE_CELL])}


# ---------- stress tests ----------

def stress_count(body):
    value = body.get("count")
    low, high = STRESS_COUNT
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        story.invalid(f"count must be a whole number from {low} to {high}.")
    return value


def schedule_stress(conn, me, identifier, body, actions):
    """POST /assets/{id}/stress-tests {count 4-10, withAssets?, setCode?}: ``count`` stress renders, render i with
    ``variation`` i (the compiler's pose and light) and its own seed. Returns {tasks, count}."""
    if set(body) - {"count", "withAssets", "setCode"}:
        story.invalid("A stress test takes count, withAssets and setCode.")
    count = stress_count(body)
    slug, row = story.find_row(conn, identifier, "asset")
    extra = stress_source(conn, slug, code_of(row), body)
    slug, job = story.generation_job(conn, me, identifier, "image", {"panel": "stress", "_stress": extra})
    first = story.takes_so_far(conn, slug, identifier, "image")
    tasks = []
    for variation in range(count):
        take = copy.deepcopy(job)
        take["input"]["variation"] = variation
        tasks.append(story.queue_task(conn, me, slug, "ASSET_IMAGE_GENERATE", story.seed_take(take, first + variation), actions))
    return {"tasks": tasks, "count": count}


def stress_results(conn, slug, row, identifier):
    """GET /assets/{id}/stress-tests: every stress render of this asset, oldest first, with the mark a person gave it."""
    marks = {item.get("imageId"): item.get("recognizable") for item in meta_of(conn, row).get("stress") or []}
    stored = sorted((c for c in story.records(conn, "candidate", slug)
                     if c.get("entityId") == identifier and c.get("kind") == "image" and c.get("panel") == "stress"),
                    key=lambda c: (c.get("createdAt") or "", c.get("variation") or 0))
    items = {}
    for item in stored:
        key = image_id(identifier, item["url"])
        items.setdefault(key, {"imageId": key, "url": item["url"], "variation": item.get("variation"), "with": list(item.get("with") or []),
                               "set": item.get("set"), "recognizable": marks.get(key)})
    return list(items.values())


def mark_stress(conn, slug, row, identifier, image, body):
    """PUT /assets/{id}/stress-tests/{imageId} {recognizable: true | false}."""
    if not isinstance(body.get("recognizable"), bool):
        story.invalid("recognizable must be true or false.")
    item = next((i for i in stress_results(conn, slug, row, identifier) if i["imageId"] == image), None)
    if not item:
        raise story.StoryError(404, "DRAMA_NOT_FOUND", "Stress test image not found.")
    item["recognizable"] = body["recognizable"]
    data = meta_of(conn, row)
    data["stress"] = [i for i in data.get("stress") or [] if i.get("imageId") != image] + [item]
    save(conn, slug, row, data)
    return item


# ---------- STATE variants ----------

def variant_text(body, base, kind):
    """(locked description, change) of a new variant. A STATE variant must say what changed, and its description opens
    with the same-identity sentence; any variant may carry a change (its edit renders read it)."""
    change = story.text(body, "change", maximum=TEXT_LIMIT).strip()
    prompt = story.text(body, "prompt")
    if kind == "STATE":
        if not change:
            story.invalid("A STATE variant needs change: what is different from the base asset.")
        prompt = STATE_PREFIX.format(base=base, change=change.rstrip(".")) + (" " + prompt.strip() if prompt.strip() else "")
        if len(prompt) > 10000:
            story.invalid("The description with its same-identity sentence must stay within 10000 characters.")
    return prompt, change


def keep_change(conn, slug, row, change):
    if change:
        data = meta_of(conn, row)
        data["change"] = change
        save(conn, slug, row, data)


# ---------- routes ----------

def route(conn, me, method, slug, identifier, row, tail, body, query, actions):
    """The asset routes of §2.2 served here; None when ``tail`` is not one of them."""
    if tail == "meta" and method == "PATCH":
        return write_meta(conn, slug, row, body)
    if tail.startswith("panels/") and tail.count("/") == 1 and method == "PUT":
        return select_panel(conn, me, slug, row, identifier, tail.split("/")[1], body)
    if tail == "stress-tests" and method == "POST":
        return schedule_stress(conn, me, identifier, body, actions)
    if tail == "stress-tests" and method == "GET":
        items = stress_results(conn, slug, row, identifier)
        return story.page(items, query) | {"total": len(items), "recognizable": sum(i["recognizable"] is True for i in items)}
    if tail.startswith("stress-tests/") and tail.count("/") == 1 and method == "PUT":
        return mark_stress(conn, slug, row, identifier, tail.split("/")[1], body)
    return None
