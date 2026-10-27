"""Sample stills for the SPEC_19 look catalog (package C, §4.4): one FLUX 3 Klein still per non-Auto option.

Every still shows the same original test scene (a courier in a rain-streaked circular observatory with brass consoles),
so the option is the only variable: the option's text is placed the way the context compiler places a still's look
(``Cinematic film still, ... lens look`` for a camera; ``Film:``, ``Color:`` and ``Lighting:`` lines for the rest), then
the scene. Each option is also generated in a compact (~15 words) form with the same seed (the "精簡版實測" rule of
SPEC_19_LOOK_OPTIONS_DRAFT.md); ``CHOICE`` records which form the catalog keeps.

Steps, each repeatable:

    python -X utf8 scripts/make_look_samples.py generate --work <dir>   # needs local ComfyUI on 127.0.0.1:8188
    python -X utf8 scripts/make_look_samples.py publish --work <dir>    # WebP stills, manifest, catalog preview + text
    python -X utf8 scripts/make_look_samples.py sheets --work <dir>     # full | compact contact sheets (docs only)

``generate`` skips stills already in the work folder, so a run can be resumed; raw PNGs stay in the work folder.
Camera moves are clips made from the 3D Stage (package B) and are not made here; ``publish`` keeps their manifest items.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import io
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from project_docs import story_look  # noqa: E402

CATALOG = ROOT / "project_docs" / "look_catalog.json"
WORKFLOW = "workflows/flux3_klein_soul_cast.json"  # the text-to-image FLUX 3 Klein graph; prompt, seed, size overridden
MODEL = "flux3-image-klein-base-int8-convrot"
SAMPLES = ROOT / "ui" / "public" / "assets" / "look-samples"
MANIFEST = SAMPLES / "manifest.json"
COMPARE = ROOT / "docs" / "research" / "look-samples-compare"
URL_BASE = "/projects/assets/look-samples"
KIND_ORDER = ("camera", "move", "genre", "era", "tempo", "palette", "light")
STILL_KINDS = ("camera", "genre", "era", "tempo", "palette", "light")
WIDTH, HEIGHT = 1280, 720          # generated (FLUX 3 Klein, ~0.9 MP, 16:9)
OUT_W, OUT_H, MAX_BYTES = 640, 360, 80 * 1024  # shipped (§4.4)
COMFY = "http://127.0.0.1:8188"

# One fixed, original scene for every still (the showcase's own material), then the guard against lettering.
SCENE = ("Inside a circular observatory at night, an original fictional courier in a charcoal field jacket stands at a "
         "curved brass console, one hand on its levers, looking up toward the dome; rain streaks down the tall curved "
         "windows behind them and a large brass telescope rises into the dark dome. Medium-wide shot.")
GUARD = ("No text, no lettering, no logos, no numbers: dials are plain and unmarked, screens show only soft abstract "
         "glow.")

# One seed per kind; an option that needed a new seed (lettering, a logo, a real-looking face, a broken image) is
# listed in SEED_OVERRIDES with the reason, and keeps that seed for both of its forms.
SEEDS = {"camera": 1901, "genre": 1902, "era": 1903, "tempo": 1904, "palette": 1905, "light": 1906}
SEED_OVERRIDES: dict[tuple[str, str], tuple[int, str]] = {
    ("palette", "bone-ink"): (2905, "seed 1905 drew the room inside an oval cut-out on a paper-white page (broken frame)"),
    ("palette", "sugar-paper"): (2905, "seed 1905 drew the room inside a circular cut-out over pastel blobs (broken frame)"),
}

# The compact form of every option (~15 words), written to the same rules as the full text: camera options are
# sentences ending with a full stop and without '/', the other kinds lowercase clauses without a full stop or ';'.
COMPACT = {
    ("camera", "digital-cinema"): "Clean digital cinema image, low noise, fine detail, wide dynamic range and soft highlight roll-off.",
    ("camera", "film-35mm"): "35mm film look, fine organic grain, gentle halation on highlights, rich dense color.",
    ("camera", "film-16mm"): "16mm film look, coarse visible grain, softer detail, lifted blacks, muted warm color.",
    ("camera", "film-8mm"): "8mm home-movie look, heavy grain, soft focus, faded warm color, dark vignetted corners.",
    ("camera", "dv-camcorder"): "Standard-definition digital video look, harsh edge sharpening, flat contrast, clipped highlights, cool cast.",
    ("camera", "clean-sharp"): "Crisp modern rendering, sharp edge to edge, high micro-contrast, neutral bokeh, no flare.",
    ("camera", "anamorphic"): "Anamorphic widescreen rendering, oval bokeh, horizontal streak flares, gentle falloff at the frame edges.",
    ("camera", "vintage-anamorphic"): "Vintage anamorphic rendering, soft low contrast, stretched oval bokeh, warm horizontal flares, curved edges.",
    ("camera", "vintage-warm"): "Warm vintage rendering, soft focus roll-off, gentle contrast, creamy amber tones, glowing skin.",
    ("camera", "vintage-glow"): "Glowing vintage rendering, highlights blooming into soft halos, veiling flare, dreamy hazy shadows.",
    ("camera", "f1-4"): "Very shallow depth of field, crisp subject, background melted into large soft bokeh.",
    ("camera", "f4"): "Moderate depth of field, sharp subject, nearby background readable but gently soft.",
    ("camera", "f11"): "Deep focus, foreground, subject and background all sharp and detailed.",
    ("genre", "rain-mystery"): "wet glass with small bright reflections, eye-level medium shot, mostly shadow, one small pool of light",
    ("genre", "quiet-drama"): "one or two people in a plain room, waist-up framing, faces held close, still camera",
    ("genre", "creeping-unease"): "wide frame of dark empty space, small subject off to one side, something half-hidden at the edge",
    ("genre", "instrument-room-sf"): "rows of dials, screens and cables in symmetrical lines, a small person beside large machinery",
    ("genre", "distant-miles"): "wide landscape, small figure crossing, very low horizon, road leading into the distance, dust in the air",
    ("genre", "field-record"): "shoulder-height handheld framing, available light only, people at work, heads cut off at the frame edge",
    ("genre", "bright-caper"): "evenly lit daylight set, wide lens up close, big props and gestures, centered symmetrical composition",
    ("genre", "close-warmth"): "two people close together, shallow depth of field, faces and hands filling the frame, one small lamp",
    ("era", "early-lens"): "soft glow around bright spots, dark corners, low contrast with milky blacks, small dust specks",
    ("era", "saturated-print"): "very high saturation, strong contrast between hues, soft diffusion on highlights, even bright stage lighting",
    ("era", "grain-film"): "fine film grain in the shadows, soft glow around lights, slightly lifted blacks, warm midtones",
    ("era", "tape-era"): "soft low-resolution detail, faint horizontal scan lines, color bleeding at bright edges, blooming highlights",
    ("era", "clean-digital"): "sharp detail edge to edge, no grain, full tonal range without clipping, natural skin, no flare",
    ("tempo", "still-hold"): "camera locked on a tripod, people moving slowly, long pauses, no camera movement",
    ("tempo", "slow-drift"): "camera creeping slower than walking pace, people taking small slow steps, background sliding slowly",
    ("tempo", "hold-then-burst"): "near stillness for most of the shot, then a sudden fast camera push or quick subject movement",
    ("tempo", "staccato-run"): "fast camera with quick pans and push-ins, people acting fast, tight framing, abrupt direction changes",
    ("palette", "midnight-slate"): "deep slate blue shadows, muted steel blue midtones, pale cool grey highlights, small warm lamp-lit spots",
    ("palette", "lamp-amber"): "amber and honey highlights, reddish brown mid-shadows, brown-black shadows, warm skin and wood, no blue",
    ("palette", "verdigris-rust"): "green-blue shadows and backgrounds, rust orange skin, metal and lights, pale sand highlights",
    ("palette", "bone-ink"): "black, warm paper white and greys only, large solid blacks, hard edge between light and shadow",
    ("palette", "wet-glass-neon"): "near-black blue background, magenta and cyan lights reflected on wet glass, faces split magenta and cyan",
    ("palette", "moss-fog"): "muted olive and moss green, distance fading into pale grey-green fog, dark green-black shadows",
    ("palette", "sea-bleached"): "washed-out pale sand, grey and faded blue, overexposed bright surfaces, shadows lifted to mid-grey",
    ("palette", "cinder-glow"): "black and deep maroon frame, glowing orange-red highlights like firelight, no green or blue",
    ("palette", "floe-white"): "bright pale blue and white, clear mid-blue shadows, snow-white highlights, small navy accents, cool skin",
    ("palette", "mulberry-hour"): "dusty purple background, dark violet shadows, pale pink highlights, thin peach band, no pure black",
    ("palette", "sugar-paper"): "bright pastel pink, sky blue, butter yellow and mint, white highlights, pale lilac shadows, no black",
    ("palette", "dry-ochre"): "ochre and earthy yellow-brown, burnt umber shadows, pale dusty cream sky, no green, almost no blue",
    ("light", "window-side"): "soft daylight from a side window, a single key, the far side of faces in deep soft shadow",
    ("light", "practical-lamp"): "one visible lamp as the only light, a small pool on faces and table, the room near black",
    ("light", "hard-top"): "hard light straight overhead, sharp shadows under brows and nose, dark eye sockets, black surroundings",
    ("light", "backlight-rim"): "strong backlight toward the camera, thin bright rim on hair and shoulders, face in shadow, hazy beam",
    ("light", "instrument-glow"): "faces and hands lit from below by screens and indicators, short soft light, no other source",
    ("light", "overcast-flat"): "even cloudy-sky light from all around, almost no shadows, soft gradients, no highlights or flare",
    ("light", "low-sun"): "low sun on one side, raking light, long stretched shadows, bright edges on faces, haze in the air",
}

# The form the catalog keeps, decided by looking at the side-by-side sheets: "full" unless listed here.
CHOICE: dict[tuple[str, str], str] = {
    # The full text put two faces at opposite edges with the courier between them; the compact one framed two people
    # close together with the background soft, as the option describes.
    ("genre", "close-warmth"): "compact",
    # Only the compact text drew visible colour bleeding and highlights blooming at the bright window edges.
    ("era", "tape-era"): "compact",
    # Only the compact text put the lamp in the frame as the light source; the full one gave no visible lamp.
    ("light", "practical-lamp"): "compact",
}

# The catalog's own text before this script changed any of it, so a compact choice can be undone and the full form
# stays on record.
FULL_TEXT_FILE = Path(__file__).with_name("look_samples_full_text.json")


def options():
    """[(kind, item)] of every non-Auto option this script makes a still for, in catalog order."""
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    return [(item["kind"], item) for item in data["items"] if item["kind"] in STILL_KINDS and item["promptText"]]


def full_texts():
    """{(kind, id): the full promptText}: the recorded originals, else the catalog's current text."""
    recorded = json.loads(FULL_TEXT_FILE.read_text(encoding="utf-8")) if FULL_TEXT_FILE.is_file() else {}
    return {(kind, item["id"]): recorded.get(f"{kind}:{item['id']}", item["promptText"]) for kind, item in options()}


def seed_of(kind, item_id):
    return SEED_OVERRIDES.get((kind, item_id), (SEEDS[kind], ""))[0]


def _line(label, value):
    # context_compiler: f"{label}: {value.rstrip('.')}."
    return f"{label}: {value.rstrip('.')}."


def prompt_for(kind, item, text):
    """The prompt sent for one option with text as its description, placed as the context compiler places a still.

    A camera option is the Optical Rig text: a still turns it into "Cinematic film still, <text> lens look; no camera
    equipment or brand text in frame." A tempo clause is kept in the Film line although a real still drops tempo:
    without it the tempo sample would not differ from the bare scene."""
    parts = []
    if kind == "camera":
        lens = text.split("/")[-1].strip().rstrip(".")
        parts.append(f"Cinematic film still, {lens} lens look; no camera equipment or brand text in frame.")
    elif kind in story_look.FILM_KINDS:
        parts.append(_line("Film", text))
    elif kind == "palette":
        parts.append(_line("Color", f"{text}; palette {', '.join(item['hex'])}"))
    elif kind == "light":
        parts.append(_line("Lighting", text))
    return " ".join(parts + [SCENE, GUARD])


def variants(kind, item, full):
    return {"full": full[(kind, item["id"])], "compact": COMPACT[(kind, item["id"])]}


# ---------- generate ----------

def _graph(prompt, seed, prefix):
    graph = json.loads((ROOT / WORKFLOW).read_text(encoding="utf-8"))
    graph["6"]["inputs"]["text"] = prompt
    graph["3"]["inputs"]["seed"] = seed
    graph["5"]["inputs"].update(width=WIDTH, height=HEIGHT)
    graph["9"]["inputs"]["filename_prefix"] = prefix
    return graph


def _post(path, body):
    request = urllib.request.Request(COMFY + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def _get(path):
    with urllib.request.urlopen(COMFY + path, timeout=120) as response:
        return response.read()


def render(prompt, seed, prefix, timeout=900):
    """One still from local ComfyUI: PNG bytes."""
    prompt_id = _post("/prompt", {"prompt": _graph(prompt, seed, prefix), "client_id": "zerofield-look-samples"})["prompt_id"]
    started = time.time()
    while time.time() - started < timeout:
        history = json.loads(_get(f"/history/{prompt_id}"))
        if prompt_id in history:
            entry = history[prompt_id]
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError(f"ComfyUI failed: {json.dumps(status)[:800]}")
            for output in entry.get("outputs", {}).values():
                for image in output.get("images", []):
                    query = urllib.parse.urlencode({"filename": image["filename"], "subfolder": image.get("subfolder", ""), "type": image.get("type", "output")})
                    return _get("/view?" + query)
        time.sleep(1.5)
    raise TimeoutError(f"ComfyUI prompt {prompt_id} took longer than {timeout}s")


def raw_path(work, kind, item_id, variant, seed):
    return Path(work) / kind / f"{item_id}.{variant}.{seed}.png"


def generate(work, only=None):
    work = Path(work)
    log_path = work / "log.json"
    log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.is_file() else {}
    full = full_texts()
    for kind, item in options():
        if only and f"{kind}:{item['id']}" not in only and kind not in only:
            continue
        seed = seed_of(kind, item["id"])
        for variant, text in variants(kind, item, full).items():
            target = raw_path(work, kind, item["id"], variant, seed)
            if target.is_file():
                continue
            prompt = prompt_for(kind, item, text)
            began = time.time()
            data = render(prompt, seed, f"zf_look_{kind}_{item['id']}_{variant}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            log[target.relative_to(work).as_posix()] = {"prompt": prompt, "seed": seed,
                                                         "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
            log_path.write_text(json.dumps(log, indent=1, ensure_ascii=False), encoding="utf-8")
            print(f"{kind}:{item['id']} {variant} seed {seed}: {time.time() - began:.0f}s", flush=True)


# ---------- publish ----------

def webp(png_bytes):
    """640x360 WebP of at most 80 KB: the highest quality that fits."""
    from PIL import Image
    image = Image.open(io.BytesIO(png_bytes)).convert("RGB").resize((OUT_W, OUT_H), Image.LANCZOS)
    for quality in range(88, 30, -4):
        buffer = io.BytesIO()
        image.save(buffer, "WEBP", quality=quality, method=6)
        if buffer.tell() <= MAX_BYTES:
            return buffer.getvalue()
    raise ValueError("A still does not fit in 80 KB even at quality 30.")


def poster_url(kind, item_id):
    return f"{URL_BASE}/{kind}/{item_id}.webp"


def publish(work):
    work = Path(work)
    log = json.loads((work / "log.json").read_text(encoding="utf-8"))
    full = full_texts()
    if not FULL_TEXT_FILE.is_file():
        FULL_TEXT_FILE.write_text(json.dumps({f"{k}:{i}": t for (k, i), t in full.items()}, indent=1) + "\n", encoding="utf-8")
    items = []
    chosen_text = {}
    for kind, item in options():
        key = (kind, item["id"])
        variant = CHOICE.get(key, "full")
        seed = seed_of(*key)
        raw = raw_path(work, kind, item["id"], variant, seed)
        record = log[raw.relative_to(work).as_posix()]
        target = SAMPLES / kind / f"{item['id']}.webp"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(webp(raw.read_bytes()))
        chosen_text[key] = variants(kind, item, full)[variant]
        items.append({"kind": kind, "id": item["id"], "poster": poster_url(kind, item["id"]), "clip": None, "workflow": WORKFLOW,
                      "model": MODEL, "seed": seed, "prompt": record["prompt"], "variant": variant, "compact": COMPACT[key],
                      "generatedAt": record["generatedAt"], "license": "CC0-1.0", "author": "ZeroField project (generated)"})
    # Keep the items other agents wrote (camera moves, with a clip); order by kind, then catalog order.
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    order = {(item["kind"], item["id"]): position for position, item in enumerate(catalog["items"])}
    existing = json.loads(MANIFEST.read_text(encoding="utf-8"))["items"] if MANIFEST.is_file() else []
    mine = {(item["kind"], item["id"]) for item in items}
    kept = [item for item in existing if (item.get("kind"), item.get("id")) not in mine and item.get("kind") not in STILL_KINDS]
    merged = sorted(kept + items, key=lambda item: (KIND_ORDER.index(item["kind"]), order.get((item["kind"], item["id"]), 10 ** 6)))
    MANIFEST.write_text(json.dumps({"version": 1, "items": merged}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # Catalog: the preview of every still and the promptText of the chosen form. Each option is rewritten in place in
    # the file's own two-line layout, so the rest of the file (order, blank lines between kinds) stays as it is.
    text = CATALOG.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    for kind, item in options():
        key = (kind, item["id"])
        anchor = '{"kind": "' + kind + '", ' + (f'"group": "{item["group"]}", ' if "group" in item else "") + f'"id": "{item["id"]}"'
        start = text.index(anchor)
        current, end = decoder.raw_decode(text, start)
        current = dict(current, promptText=chosen_text[key], preview={"poster": poster_url(kind, item["id"])})
        head = ", ".join(f"{json.dumps(k)}: {json.dumps(current[k])}" for k in ("kind", "group", "id", "labelKey") if k in current)
        # A palette keeps its colours on a line of their own.
        tail = (",\n     " if "hex" in current else ", ").join(
            ", ".join(f"{json.dumps(k)}: {json.dumps(current[k], ensure_ascii=False)}" for k in keys if k in current)
            for keys in (("promptText",), ("hex", "preview")) if any(k in current for k in keys))
        text = text[:start] + "{" + head + ",\n     " + tail + "}" + text[end:]
    story_look.validate(json.loads(text))
    CATALOG.write_text(text, encoding="utf-8")
    total = sum(path.stat().st_size for path in SAMPLES.rglob("*") if path.is_file())
    print(f"{len(items)} stills; look-samples folder {total / 1024:.0f} KB")


# ---------- sheets ----------

def sheets(work, thumb=(400, 225)):
    """docs/research/look-samples-compare/<kind>.jpg: full on the left, compact on the right, the option id above."""
    from PIL import Image, ImageDraw, ImageFont
    work = Path(work)
    COMPARE.mkdir(parents=True, exist_ok=True)
    font = ImageFont.load_default(size=18)
    by_kind = {}
    for kind, item in options():
        by_kind.setdefault(kind, []).append(item)
    gap, head = 8, 28
    for kind, entries in by_kind.items():
        width = thumb[0] * 2 + gap * 3
        height = head + len(entries) * (thumb[1] + head + gap)
        sheet = Image.new("RGB", (width, height), (18, 22, 28))
        draw = ImageDraw.Draw(sheet)
        draw.text((gap, 5), f"{kind}: full (left) | compact (right)", fill=(230, 230, 230), font=font)
        y = head
        for item in entries:
            seed = seed_of(kind, item["id"])
            chosen = CHOICE.get((kind, item["id"]), "full")
            draw.text((gap, y + 4), f"{item['id']}  seed {seed}  kept: {chosen}", fill=(245, 190, 90), font=font)
            for column, variant in enumerate(("full", "compact")):
                raw = raw_path(work, kind, item["id"], variant, seed)
                if raw.is_file():
                    image = Image.open(raw).convert("RGB").resize(thumb, Image.LANCZOS)
                    sheet.paste(image, (gap + column * (thumb[0] + gap), y + head))
            y += thumb[1] + head + gap
        for quality in range(82, 30, -6):
            buffer = io.BytesIO()
            sheet.save(buffer, "JPEG", quality=quality, optimize=True)
            if buffer.tell() <= 600 * 1024:
                break
        (COMPARE / f"{kind}.jpg").write_bytes(buffer.getvalue())
        print(f"{kind}.jpg {buffer.tell() / 1024:.0f} KB")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=("generate", "publish", "sheets"))
    parser.add_argument("--work", required=True, help="folder for the raw PNGs and their log")
    parser.add_argument("--only", nargs="*", help="kinds or kind:id to generate")
    args = parser.parse_args(argv)
    if args.step == "generate":
        generate(args.work, args.only)
    elif args.step == "publish":
        publish(args.work)
    else:
        sheets(args.work)


if __name__ == "__main__":
    main()
