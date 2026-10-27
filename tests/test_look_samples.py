"""SPEC_19 §4.4 sample media of the look catalog (package C stills, package B move clips): files, sizes and the manifest.

No database: reads project_docs/look_catalog.json and ui/public/assets/look-samples/ (which `npm run build` copies into
static/projects/assets/, so the wheel ships them).
"""
import json
import re
import struct
import unittest
from pathlib import Path

from project_docs import story_look

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "ui" / "public"
SAMPLES = PUBLIC / "assets" / "look-samples"
MANIFEST = SAMPLES / "manifest.json"
URL_PREFIX = "/projects/"
FIELDS = ("kind", "id", "poster", "clip", "workflow", "model", "seed", "prompt", "generatedAt", "license", "author")
# A still also records which form of the option's text it shows (the 精簡版實測 rule of SPEC_19_LOOK_OPTIONS_DRAFT.md).
STILL_FIELDS = ("variant", "compact")
KIND_ORDER = story_look.API_KINDS
STILL = {"size": (640, 360), "bytes": 80 * 1024}
MOVE_POSTER = {"size": (480, 270), "bytes": 60 * 1024}
MOVE_CLIP_BYTES = 400 * 1024
FOLDER_BYTES = 15 * 1024 * 1024
# A sample shows no real person, brand or title (§4.4, DESIGN §3.2); its prompt asks for no lettering.
BRANDS = ("arri", "alexa", "panavision", "cooke", "zeiss", "leica", "canon", "sony", "nikon", "kodak", "fujifilm",
          "blackmagic", "hasselblad", "imax", "technicolor", "kodachrome", "ektachrome", "portra", "handycam", "gopro")


def local(url):
    """The file under ui/public that a /projects/... URL names."""
    return PUBLIC / url[len(URL_PREFIX):]


def webp_size(data):
    """(width, height) of a WebP (VP8, VP8L or VP8X), read from its header."""
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ValueError("not a WebP file")
    chunk = data[12:16]
    if chunk == b"VP8 ":
        width, height = struct.unpack("<HH", data[26:30])
        return width & 0x3FFF, height & 0x3FFF
    if chunk == b"VP8L":
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if chunk == b"VP8X":
        return int.from_bytes(data[24:27], "little") + 1, int.from_bytes(data[27:30], "little") + 1
    raise ValueError("unknown WebP chunk")


def catalog_items():
    return json.loads(story_look.CATALOG_PATH.read_text(encoding="utf-8"))["items"]


def manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


class LookSampleTests(unittest.TestCase):
    def test_every_catalog_preview_is_a_shipped_file(self):
        previews = [item for item in catalog_items() if item.get("preview")]
        self.assertTrue(previews, "the catalog has sample media")
        for item in previews:
            for field in ("poster", "clip"):
                url = item["preview"].get(field)
                if url is None:
                    continue
                with self.subTest(option=f"{item['kind']}:{item['id']}", field=field):
                    self.assertTrue(url.startswith(URL_PREFIX + "assets/look-samples/"), url)
                    self.assertTrue(local(url).is_file(), url)

    def test_auto_options_have_no_preview_and_every_still_kind_option_has_one(self):
        for item in catalog_items():
            with self.subTest(option=f"{item['kind']}:{item['id']}"):
                if not item["promptText"]:
                    self.assertNotIn("preview", item, "Auto is drawn as a texture")
                elif item["kind"] != "move":
                    self.assertEqual(item["preview"], {"poster": f"/projects/assets/look-samples/{item['kind']}/{item['id']}.webp"})

    def test_the_manifest_lists_every_field_and_matches_the_catalog(self):
        data = manifest()
        self.assertEqual(data["version"], 1)
        options = {(item["kind"], item["id"]): item for item in catalog_items()}
        order = list(options)
        keys = [(item["kind"], item["id"]) for item in data["items"]]
        self.assertEqual(len(keys), len(set(keys)), "one item per option")
        self.assertEqual(keys, sorted(keys, key=lambda key: (KIND_ORDER.index(key[0]), order.index(key))),
                         "ordered by kind, then catalog order")
        for item in data["items"]:
            key = (item.get("kind"), item.get("id"))
            with self.subTest(option=f"{key[0]}:{key[1]}"):
                required = set(FIELDS) | (set(STILL_FIELDS) if item.get("clip") is None else set())
                self.assertTrue(required <= set(item), sorted(required - set(item)))
                option = options.get(key)
                self.assertIsNotNone(option, "a manifest item names a catalog option")
                self.assertTrue(option["promptText"], "Auto has no sample")
                self.assertEqual(option.get("preview", {}).get("poster"), item["poster"])
                self.assertEqual(option.get("preview", {}).get("clip"), item["clip"])
                self.assertTrue((ROOT / item["workflow"]).is_file(), item["workflow"])
                self.assertIsInstance(item["seed"], int)
                self.assertEqual((item["license"], item["author"]), ("CC0-1.0", "ZeroField project (generated)"))
                self.assertRegex(item["generatedAt"], r"^\d{4}-\d{2}-\d{2}")
                prompt = item["prompt"]
                self.assertTrue(isinstance(prompt, str) and prompt)
                self.assertFalse(set(re.findall(r"[a-z0-9]+", prompt.lower())) & set(BRANDS), prompt)
                if item["clip"] is None:
                    self.assertIn("No text, no lettering, no logos", prompt)
                    self.assertIn(item["variant"], ("full", "compact"))
                    # A still: the prompt carries the catalog's text, which is the variant the manifest names.
                    shown = option["promptText"].rstrip(".")
                    self.assertIn(shown, prompt)
                    if item["variant"] == "compact":
                        self.assertEqual(option["promptText"], item["compact"])
                    else:
                        self.assertNotEqual(option["promptText"], item["compact"])

    def test_package_c_text_is_the_drafts_unless_the_compact_form_was_chosen(self):
        # SPEC_19_LOOK_OPTIONS_DRAFT.md tables: | `id` | 中文名 | English label | promptText | ... ; the 精簡版實測 rule lets the
        # side-by-side test swap an option to its compact form, which the manifest then records (and the draft lists).
        draft = (ROOT / "docs" / "specs" / "SPEC_19_LOOK_OPTIONS_DRAFT.md").read_text(encoding="utf-8")
        section, texts = None, {}
        for line in draft.splitlines():
            if line.startswith("## "):
                heading = re.match(r"^## \d\. `(\w+)`", line)
                section = heading[1] if heading else None
            row = re.match(r"^\| `([a-z0-9-]+)` \| [^|]+ \| [^|]+ \| ([^|]+) \|", line)
            if section and row and row[1] not in ("id", "auto"):  # the header row and Auto, which has no text
                texts[(section, row[1])] = row[2].strip()
        compact = {(item["kind"], item["id"]): item["compact"] for item in manifest()["items"] if item.get("variant") == "compact"}
        options = [item for item in catalog_items() if item["kind"] in ("genre", "era", "tempo", "palette", "light") and item["promptText"]]
        self.assertEqual(len(options), 36)
        self.assertEqual(set(texts), {(item["kind"], item["id"]) for item in options})
        for item in options:
            key = (item["kind"], item["id"])
            with self.subTest(option=f"{key[0]}:{key[1]}"):
                self.assertEqual(item["promptText"], compact.get(key, texts[key]))
                if key in compact:
                    self.assertIn(f"`{key[0]}:{key[1]}`", draft.split("## 8. 實測結果", 1)[-1], "the draft says why it changed")

    def test_stills_and_move_media_fit_section_4_4(self):
        for item in manifest()["items"]:
            poster = local(item["poster"]).read_bytes()
            move = item["clip"] is not None
            limits = MOVE_POSTER if move else STILL
            with self.subTest(option=f"{item['kind']}:{item['id']}"):
                self.assertTrue(item["poster"].endswith(".webp"))
                self.assertEqual(webp_size(poster), limits["size"])
                self.assertLessEqual(len(poster), limits["bytes"])
                if move:
                    clip = local(item["clip"]).read_bytes()
                    self.assertTrue(item["clip"].endswith(".mp4") and clip[4:8] == b"ftyp")
                    self.assertLessEqual(len(clip), MOVE_CLIP_BYTES)

    def test_the_look_samples_folder_stays_under_15_mb(self):
        total = sum(path.stat().st_size for path in SAMPLES.rglob("*") if path.is_file())
        self.assertLess(total, FOLDER_BYTES)  # SPEC_19 §7 item 4: shipped in the wheel


if __name__ == "__main__":
    unittest.main()
