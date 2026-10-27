"""SPEC_19 look catalog: validation, Optical Rig text and in-place #move tags (package B); genre, era, tempo, palette and
light, the episode look and a shot's override, and compile_look (package C)."""
import copy
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from project_docs import story_look as look

CATALOG = json.loads(look.CATALOG_PATH.read_text(encoding="utf-8"))
PUSH = look.option("move", "push-in")["promptText"]
PAN = look.option("move", "pan")["promptText"]
STATIC = look.option("move", "static")["promptText"]
# Real camera, lens, film-stock and gear brands, and director / title shorthand for camera moves (DESIGN §3.2).
BRANDS = ("arri", "alexa", "red", "raptor", "komodo", "bolex", "panavision", "cooke", "zeiss", "leica", "canon",
          "sony", "nikon", "kodak", "fuji", "fujifilm", "blackmagic", "hasselblad", "angenieux", "helios", "lomo",
          "steadicam", "imax", "technicolor", "cinemascope", "vistavision", "kodachrome", "ektachrome", "portra",
          "vision3", "minidv", "handycam", "gopro", "dji", "hitchcock", "vertigo", "kubrick", "spielberg", "wes",
          "anderson", "nolan", "matrix", "super")
# In a colour description "red" is a colour, not the camera brand.
COLOUR_WORDS = {"red"}
CLAUSES = ("genre", "era", "tempo", "palette", "light")
# SPEC_19_LOOK_OPTIONS_DRAFT.md, in its order (2026-10-27 final list).
PACKAGE_C = {
    "genre": ["auto", "rain-mystery", "quiet-drama", "creeping-unease", "instrument-room-sf", "distant-miles", "field-record",
              "bright-caper", "close-warmth"],
    "era": ["auto", "early-lens", "saturated-print", "grain-film", "tape-era", "clean-digital"],
    "tempo": ["auto", "still-hold", "slow-drift", "hold-then-burst", "staccato-run"],
    "palette": ["auto", "midnight-slate", "lamp-amber", "verdigris-rust", "bone-ink", "wet-glass-neon", "moss-fog",
                "sea-bleached", "cinder-glow", "floe-white", "mulberry-hour", "sugar-paper", "dry-ochre"],
    "light": ["auto", "window-side", "practical-lamp", "hard-top", "backlight-rim", "instrument-glow", "overcast-flat", "low-sun"],
}


def text(kind, item_id):
    return look.option(kind, item_id)["promptText"]


def items(kind, group=None):
    return [item for item in CATALOG["items"] if item["kind"] == kind and item.get("group") == group]


def broken(change):
    data = copy.deepcopy(CATALOG)
    change(data["items"])
    return data


class CatalogTests(unittest.TestCase):
    def test_packaged_catalog_lists_the_package_b_options_in_order(self):
        look.validate(CATALOG)
        self.assertEqual({item["kind"] for item in CATALOG["items"]}, set(look.API_KINDS))
        self.assertEqual([i["id"] for i in items("camera", "body")],
                         ["auto-body", "digital-cinema", "film-35mm", "film-16mm", "film-8mm", "dv-camcorder"])
        self.assertEqual([i["id"] for i in items("camera", "lens")],
                         ["auto-lens", "clean-sharp", "anamorphic", "vintage-anamorphic", "vintage-warm", "vintage-glow"])
        self.assertEqual([i["id"] for i in items("camera", "aperture")], ["auto-aperture", "f1-4", "f4", "f11"])
        self.assertEqual([i["id"] for i in items("move")],
                         ["auto", "push-in", "pull-out", "tracking", "pan", "crane-up", "crane-down", "orbit-180",
                          "handheld", "whip-pan", "rack-focus", "pov", "static"])
        self.assertEqual(look.catalog(), CATALOG["items"])

    def test_package_c_lists_the_final_options_in_the_drafts_order(self):
        for kind, ids in PACKAGE_C.items():
            options = items(kind)
            with self.subTest(kind=kind):
                self.assertEqual([i["id"] for i in options], ids)
                # labelKey: lookCatalog.<kind>.<camelCaseId>, "auto" for Auto
                self.assertEqual([i["labelKey"] for i in options],
                                 [f"lookCatalog.{kind}." + re.sub(r"-([a-z0-9])", lambda m: m[1].upper(), i) for i in ids])
                self.assertTrue(all("group" not in i for i in options))
                # §4.4: every option but Auto (a texture) shows its sample still (tests/test_look_samples.py checks the files).
                self.assertEqual([i.get("preview") for i in options],
                                 [{"poster": f"/projects/assets/look-samples/{kind}/{i}.webp"} if i != "auto" else None for i in ids])
        self.assertEqual(sum(len(ids) - 1 for ids in PACKAGE_C.values()), 36)  # SPEC_19 §7 decision 5
        self.assertEqual(look.option("palette", "midnight-slate")["hex"][:2], ["#2E3A4A", "#5B6F86"])  # SPEC_19 §4.3

    def test_every_choice_starts_with_an_empty_auto_and_the_rest_are_english_sentences(self):
        for kind, groups in look.KINDS.items():
            for group in groups or (None,):
                options = items(kind, group)
                with self.subTest(kind=kind, group=group):
                    self.assertEqual(options[0]["promptText"], "")
                    self.assertTrue(options[0]["id"].startswith("auto"))
                    for item in options[1:]:
                        text = item["promptText"]
                        self.assertTrue(text.isascii() and len(text.split()) >= 8, text)
                        self.assertRegex(item["labelKey"], rf"^lookCatalog\.{kind}\.")
                        if kind in CLAUSES:
                            # One clause the compiler joins: lowercase start, no full stop, no "; " of its own.
                            self.assertTrue(text[0].islower() and not text.endswith(".") and ";" not in text, text)
                        else:
                            self.assertTrue(text.endswith("."), text)
        self.assertEqual(len({item["labelKey"] for item in CATALOG["items"]}), len(CATALOG["items"]))

    def test_only_palettes_have_colours_and_every_palette_but_auto_has_them(self):
        for item in CATALOG["items"]:
            with self.subTest(option=f"{item['kind']}:{item['id']}"):
                if item["kind"] == "palette" and item["promptText"]:
                    self.assertTrue(5 <= len(item["hex"]) <= 6 and all(re.fullmatch(r"#[0-9A-F]{6}", c) for c in item["hex"]))
                else:
                    self.assertNotIn("hex", item)

    def test_options_name_no_brands_people_or_titles_and_camera_text_names_no_equipment(self):
        for item in CATALOG["items"]:
            words = lambda text: set(re.findall(r"[a-z0-9]+", text.lower()))
            prompt = words(item["promptText"])
            banned = set(BRANDS) - (COLOUR_WORDS if item["kind"] == "palette" else set())
            with self.subTest(option=item["id"]):
                self.assertFalse((words(item["id"] + " " + item["labelKey"]) | prompt) & banned)
                if item["kind"] == "camera":
                    # Stills draw named gear as props (PHASE2: "RED V-RAPTOR" lettered onto a recorder).
                    self.assertFalse(prompt & {"camera", "camcorder", "tripod", "lens", "rig"})
                    self.assertNotIn("/", item["promptText"])

    def test_validation_rejects_malformed_catalogs(self):
        def add(item):
            return lambda entries: entries.append(item)

        def first(kind, group=None):
            return next(i for i in range(len(CATALOG["items"]))
                        if CATALOG["items"][i]["kind"] == kind and CATALOG["items"][i].get("group") == group)

        auto_lens, auto_move, auto_palette = first("camera", "lens"), first("move"), first("palette")
        slate = auto_palette + 1
        teal = {"kind": "palette", "id": "teal-night", "labelKey": "lookCatalog.palette.tealNight",
                "promptText": "shadows in deep teal, highlights a pale cool grey", "hex": ["#1F4E5A", "#D8E0E8"]}
        cases = {
            "unique within a kind": add({"kind": "move", "id": "pan", "labelKey": "lookCatalog.move.pan2", "promptText": "Pan again."}),
            "unknown kind": add({"kind": "filter", "id": "mist", "labelKey": "lookCatalog.filter.mist", "promptText": "Mist."}),
            "labelKey of another kind": add({"kind": "move", "id": "drift", "labelKey": "lookCatalog.camera.drift", "promptText": "Drift."}),
            # Package C: clauses, and colours on palettes only.
            "clause with a full stop": add(dict(teal, promptText="shadows in deep teal.")),
            "clause with a capital": add(dict(teal, promptText="Shadows in deep teal")),
            "clause with a semicolon": add(dict(teal, promptText="shadows in deep teal; highlights grey")),
            "genre sentence": add({"kind": "genre", "id": "slow-noir", "labelKey": "lookCatalog.genre.slowNoir",
                                   "promptText": "Long shadows across wet streets."}),
            "palette without colours": add({k: v for k, v in teal.items() if k != "hex"}),
            "no colours": add(dict(teal, hex=[])),
            "thirteen colours": add(dict(teal, hex=[f"#{i:06X}" for i in range(13)])),
            "lowercase colour": add(dict(teal, hex=["#1f4e5a"])),
            "short colour": add(dict(teal, hex=["#1F4"])),
            "colour without #": add(dict(teal, hex=["1F4E5A"])),
            "repeated colour": add(dict(teal, hex=["#1F4E5A", "#1F4E5A"])),
            "colours as text": add(dict(teal, hex="#1F4E5A")),
            "colours on a light": add({"kind": "light", "id": "red-lamp", "labelKey": "lookCatalog.light.redLamp",
                                       "promptText": "one lamp low beside the face", "hex": ["#AA0000"]}),
            "colours on a camera": lambda entries: entries[first("camera", "body") + 1].update(hex=["#2E3A4A"]),
            "colours on auto": lambda entries: entries[auto_palette].update(hex=["#2E3A4A"]),
            "palette auto not first": lambda entries: entries.insert(auto_palette, entries.pop(slate)),
            "uppercase id": add({"kind": "move", "id": "Push", "labelKey": "lookCatalog.move.x", "promptText": "Push."}),
            "underscore id": add({"kind": "move", "id": "push_in", "labelKey": "lookCatalog.move.x", "promptText": "Push."}),
            "one-letter id": add({"kind": "move", "id": "p", "labelKey": "lookCatalog.move.x", "promptText": "Push."}),
            "trailing hyphen": add({"kind": "move", "id": "push-", "labelKey": "lookCatalog.move.x", "promptText": "Push."}),
            "missing group": add({"kind": "camera", "id": "film-70mm", "labelKey": "lookCatalog.camera.x", "promptText": "Wide."}),
            "wrong group": add({"kind": "camera", "group": "filter", "id": "mist", "labelKey": "lookCatalog.camera.x", "promptText": "Mist."}),
            "group on a move": add({"kind": "move", "group": "body", "id": "drift", "labelKey": "lookCatalog.move.x", "promptText": "Drift."}),
            "unknown key": add({"kind": "move", "id": "drift", "labelKey": "lookCatalog.move.x", "promptText": "Drift.", "brand": "x"}),
            "duplicate labelKey": add({"kind": "move", "id": "drift", "labelKey": "lookCatalog.move.pan", "promptText": "Drift."}),
            "bad labelKey": add({"kind": "move", "id": "drift", "labelKey": "drift", "promptText": "Drift."}),
            "second auto": add({"kind": "move", "id": "none", "labelKey": "lookCatalog.move.none", "promptText": ""}),
            "not a sentence": add({"kind": "move", "id": "drift", "labelKey": "lookCatalog.move.x", "promptText": "Slow drift"}),
            "not english": add({"kind": "move", "id": "drift", "labelKey": "lookCatalog.move.x", "promptText": "慢推。"}),
            "two lines": add({"kind": "move", "id": "drift", "labelKey": "lookCatalog.move.x", "promptText": "Drift.\nMore."}),
            "slash in camera text": add({"kind": "camera", "group": "aperture", "id": "f2", "labelKey": "lookCatalog.camera.x",
                                         "promptText": "Shallow focus at f/2."}),
            "auto not first": lambda entries: entries.insert(auto_lens, entries.pop(auto_lens + 1)),
            "auto with text": lambda entries: entries[auto_move].update(promptText="Anything."),
            "kind without options": lambda entries: [entries.remove(i) for i in list(entries) if i["kind"] == "move"],
        }
        for name, change in cases.items():
            with self.subTest(name), self.assertRaises(look.LookCatalogError):
                look.validate(broken(change))
        for document in ([], {"version": 2, "items": []}, {"version": 1}):
            with self.subTest(document=document), self.assertRaises(look.LookCatalogError):
                look.validate(document)

    def test_ids_are_scoped_to_their_kind_and_load_reports_unreadable_files(self):
        # The same id in another kind is a different option (catalog keys are kind:id).
        look.validate(broken(lambda entries: entries.append(
            {"kind": "move", "id": "anamorphic", "labelKey": "lookCatalog.move.anamorphic", "promptText": "The camera drifts."})))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            with self.assertRaisesRegex(look.LookCatalogError, "cannot be read"):
                look.load(path)
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaisesRegex(look.LookCatalogError, "cannot be read"):
                look.load(path)
            path.write_text(json.dumps(CATALOG), encoding="utf-8")
            self.assertEqual(look.load(path), CATALOG)


class ApiItemTests(unittest.TestCase):
    """GET /catalog/looks items: {id, kind, group?, labelKey, promptText, preview: {poster, clip} | null, hex?}."""

    def test_items_follow_the_catalog_with_groups_only_where_a_kind_has_them(self):
        listed = look.api_items()
        self.assertEqual([(i["kind"], i["id"]) for i in listed], [(i["kind"], i["id"]) for i in CATALOG["items"]])
        self.assertEqual(listed[0], {"id": "auto-body", "kind": "camera", "group": "body", "labelKey": "lookCatalog.camera.body.auto",
                                     "promptText": "", "preview": None})
        self.assertEqual([i["group"] for i in look.api_items("camera")], [i["group"] for i in items("camera", "body") +
                                                                          items("camera", "lens") + items("camera", "aperture")])
        moves = look.api_items("move")
        self.assertEqual(moves[1], {"id": "push-in", "kind": "move", "labelKey": "lookCatalog.move.pushIn", "promptText": PUSH,
                                    "preview": {"poster": "/projects/assets/look-samples/move/push-in.webp",
                                                "clip": "/projects/assets/look-samples/move/push-in.mp4"}})
        self.assertTrue(all("group" not in i and "hex" not in i for i in moves))

    def test_package_c_kinds_list_their_options_with_colours_on_palettes_and_other_kinds_are_refused(self):
        for kind in CLAUSES:
            listed = look.api_items(kind)
            with self.subTest(kind=kind):
                self.assertEqual([i["id"] for i in listed], PACKAGE_C[kind])
                self.assertEqual(listed[0], {"id": "auto", "kind": kind, "labelKey": f"lookCatalog.{kind}.auto", "promptText": "", "preview": None})
                self.assertTrue(all("group" not in i for i in listed))
                self.assertEqual(["hex" in i for i in listed], [kind == "palette" and i["id"] != "auto" for i in listed])
        slate = look.api_items("palette")[1]
        self.assertEqual(slate, {"id": "midnight-slate", "kind": "palette", "labelKey": "lookCatalog.palette.midnightSlate",
                                 "promptText": text("palette", "midnight-slate"),
                                 "preview": {"poster": "/projects/assets/look-samples/palette/midnight-slate.webp", "clip": None},
                                 "hex": ["#2E3A4A", "#5B6F86", "#1B2330", "#8FA3B8", "#D8E0E8", "#C9953F"]})
        self.assertEqual(look.API_KINDS, ("camera", "move", "genre", "era", "tempo", "palette", "light"))
        for kind in ("colour", "Camera", "", "body"):
            with self.subTest(kind=kind), self.assertRaises(look.LookCatalogError):
                look.api_items(kind)

    def test_sample_media_and_colours_are_passed_through(self):
        base = {"id": "teal-night", "kind": "palette", "labelKey": "lookCatalog.palette.tealNight", "promptText": "Teal night."}
        self.assertIsNone(look.api_item(dict(base, preview={}))["preview"])
        self.assertEqual(look.api_item(dict(base, preview={"poster": "/a.webp"}))["preview"], {"poster": "/a.webp", "clip": None})
        self.assertEqual(look.api_item(dict(base, preview={"poster": "/a.webp", "clip": "/a.mp4"}))["preview"],
                         {"poster": "/a.webp", "clip": "/a.mp4"})
        self.assertEqual(look.api_item(dict(base, hex=["#2E3A4A", "#5B6F86"]))["hex"], ["#2E3A4A", "#5B6F86"])
        self.assertNotIn("group", look.api_item(base))


class CameraTextTests(unittest.TestCase):
    def test_auto_parts_are_left_out_and_the_rest_join_in_body_lens_aperture_order(self):
        body, lens, aperture = (look.option("camera", i)["promptText"] for i in ("film-35mm", "anamorphic", "f1-4"))
        self.assertEqual(look.camera_text("film-35mm", "anamorphic", "f1-4"), f"{body} {lens} {aperture}")
        self.assertEqual(look.camera_text(aperture="f1-4", lens="anamorphic", body="film-35mm"), f"{body} {lens} {aperture}")
        self.assertEqual(look.camera_text("auto-body", "anamorphic", "auto-aperture"), lens)
        self.assertEqual(look.camera_text(None, "", "f1-4"), aperture)
        self.assertEqual(look.camera_text(), "")
        self.assertEqual(look.camera_text("auto-body", "auto-lens", "auto-aperture"), "")

    def test_unknown_or_misplaced_options_raise(self):
        for args in ({"body": "anamorphic"}, {"lens": "film-35mm"}, {"aperture": "f2"}, {"body": "push-in"},
                     {"body": "auto"}, {"lens": "auto-body"}):
            with self.subTest(args=args), self.assertRaises(look.LookCatalogError):
                look.camera_text(**args)


class LookValidationTests(unittest.TestCase):
    """The episode look {genre, era, tempo, camera: {body, lens, aperture}, palette, light} and a shot's override."""
    FULL = {"genre": "rain-mystery", "era": "grain-film", "tempo": "slow-drift",
            "camera": {"body": "film-35mm", "lens": "anamorphic", "aperture": "f1-4"}, "palette": "midnight-slate", "light": "window-side"}

    def refused(self, validate, value):
        with self.assertRaises(look.LookCatalogError) as caught:
            validate(value)
        return caught.exception.reason, caught.exception.params, str(caught.exception)

    def test_an_episode_look_takes_ids_of_each_kind_and_drops_what_sets_nothing(self):
        self.assertEqual(look.validate_episode_look(self.FULL), self.FULL)
        self.assertIsNot(look.validate_episode_look(self.FULL)["camera"], self.FULL["camera"])
        self.assertEqual(look.validate_episode_look({}), {})
        self.assertEqual(look.validate_episode_look({"palette": "auto", "genre": None, "camera": {"lens": "auto-lens", "body": None}}),
                         {"palette": "auto", "camera": {"lens": "auto-lens"}})
        self.assertEqual(look.validate_episode_look({"camera": {}, "light": None}), {})

    def test_an_episode_look_refuses_unknown_settings_and_ids_and_names_the_problem(self):
        cases = [
            ([], ("lookNotObject", {"setting": "look"}, "look must be an object of look settings.")),
            ({"camera": "film-35mm"}, ("lookNotObject", {"setting": "look.camera"}, "look.camera must be an object of look settings.")),
            ({"colour": "midnight-slate"}, ("unknownLookSetting", {"key": "colour", "keys": "genre, era, tempo, camera, palette, light"},
                                            "Unknown look setting 'colour'; use genre, era, tempo, camera, palette, light.")),
            ({"camera": {"focus": "f4"}}, ("unknownLookSetting", {"key": "camera.focus", "keys": "body, lens, aperture"},
                                           "Unknown look setting 'camera.focus'; use body, lens, aperture.")),
            ({"palette": "teal"}, ("unknownLookOption", {"setting": "palette", "id": "teal"},
                                   "Unknown palette option 'teal'; choose an option from the look catalog.")),
            ({"light": "midnight-slate"}, ("unknownLookOption", {"setting": "light", "id": "midnight-slate"},
                                           "Unknown light option 'midnight-slate'; choose an option from the look catalog.")),
            ({"camera": {"lens": "film-35mm"}}, ("unknownLookOption", {"setting": "camera lens", "id": "film-35mm"},
                                                 "Unknown camera lens option 'film-35mm'; choose an option from the look catalog.")),
            ({"genre": 3}, ("unknownLookOption", {"setting": "genre", "id": "3"}, "Unknown genre option '3'; choose an option from the look catalog.")),
            ({"tempo": "push-in"}, ("unknownLookOption", {"setting": "tempo", "id": "push-in"},
                                    "Unknown tempo option 'push-in'; choose an option from the look catalog.")),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(self.refused(look.validate_episode_look, value), expected)

    def test_a_shot_override_keeps_nulls_and_has_no_camera(self):
        value = {"palette": "lamp-amber", "light": None, "tempo": "auto"}
        self.assertEqual(look.validate_shot_look(value), value)
        self.assertEqual(look.validate_shot_look({}), {})
        self.assertEqual(self.refused(look.validate_shot_look, {"camera": {"body": "film-35mm"}})[:2],
                         ("unknownLookSetting", {"key": "camera", "keys": "genre, era, tempo, palette, light"}))
        self.assertEqual(self.refused(look.validate_shot_look, {"era": "1970s"})[:2], ("unknownLookOption", {"setting": "era", "id": "1970s"}))
        self.assertEqual(self.refused(look.validate_shot_look, None)[0], "lookNotObject")


class CompileLookTests(unittest.TestCase):
    """compile_look(episode_look, shot_look, *, still=False) -> {film, color, light, camera} (SPEC_19 §4.3)."""

    def test_film_joins_genre_era_and_tempo_in_order_and_auto_leaves_no_separator(self):
        genre, era, tempo = text("genre", "rain-mystery"), text("era", "grain-film"), text("tempo", "slow-drift")
        cases = [
            ({"genre": "rain-mystery", "era": "grain-film", "tempo": "slow-drift"}, f"{genre}; {era}; {tempo}"),
            ({"tempo": "slow-drift", "era": "grain-film", "genre": "rain-mystery"}, f"{genre}; {era}; {tempo}"),  # never key order
            ({"genre": "auto", "era": "grain-film", "tempo": "slow-drift"}, f"{era}; {tempo}"),
            ({"genre": "rain-mystery", "era": "auto", "tempo": "slow-drift"}, f"{genre}; {tempo}"),
            ({"genre": "rain-mystery", "era": "grain-film", "tempo": "auto"}, f"{genre}; {era}"),
            ({"tempo": "slow-drift"}, tempo),
            ({"genre": "auto", "era": "auto", "tempo": "auto"}, ""),
            ({}, ""),
        ]
        for episode, film in cases:
            with self.subTest(episode=episode):
                result = look.compile_look(episode, {})
                self.assertEqual(result["film"], film)
                self.assertFalse(result["film"].startswith(";") or result["film"].endswith(";") or ";;" in result["film"].replace(" ", ""))

    def test_a_still_drops_tempo_and_keeps_everything_else(self):
        episode = {"genre": "rain-mystery", "era": "grain-film", "tempo": "slow-drift", "palette": "bone-ink", "light": "hard-top",
                   "camera": {"body": "film-16mm"}}
        clip, still = look.compile_look(episode, {}), look.compile_look(episode, {}, still=True)
        self.assertEqual(still["film"], f"{text('genre', 'rain-mystery')}; {text('era', 'grain-film')}")
        self.assertEqual({k: v for k, v in still.items() if k != "film"}, {k: v for k, v in clip.items() if k != "film"})
        self.assertEqual(look.compile_look({"tempo": "staccato-run"}, {}, still=True)["film"], "")

    def test_color_is_the_palette_clause_then_its_colours_light_is_the_light_clause(self):
        result = look.compile_look({"palette": "midnight-slate", "light": "window-side"}, None)
        self.assertEqual(result["color"], text("palette", "midnight-slate") +
                         "; palette #2E3A4A, #5B6F86, #1B2330, #8FA3B8, #D8E0E8, #C9953F")
        self.assertIn(" palette #2E3A4A, #5B6F86", result["color"])  # SPEC_19 §4.3's example
        self.assertEqual(result["light"], text("light", "window-side"))
        self.assertEqual(look.compile_look({"palette": "auto", "light": "auto"}, {}), {"film": "", "color": "", "light": "", "camera": ""})
        self.assertEqual(look.compile_look(None, None), {"film": "", "color": "", "light": "", "camera": ""})

    def test_camera_is_the_episode_cameras_optical_rig_text(self):
        camera = {"body": "film-35mm", "lens": "auto-lens", "aperture": "f1-4"}
        self.assertEqual(look.compile_look({"camera": camera}, {})["camera"], look.camera_text("film-35mm", "auto-lens", "f1-4"))
        self.assertEqual(look.compile_look({"camera": {"body": "auto-body"}}, {})["camera"], "")

    def test_the_shot_override_wins_per_kind_and_null_falls_back_to_the_episode(self):
        episode = {"genre": "rain-mystery", "era": "grain-film", "palette": "midnight-slate", "light": "window-side"}
        result = look.compile_look(episode, {"genre": "quiet-drama", "palette": "lamp-amber", "light": None, "tempo": "still-hold"})
        self.assertEqual(result["film"], f"{text('genre', 'quiet-drama')}; {text('era', 'grain-film')}; {text('tempo', 'still-hold')}")
        self.assertTrue(result["color"].startswith(text("palette", "lamp-amber") + "; palette #C98A3D, "))
        self.assertEqual(result["light"], text("light", "window-side"))  # null: back to the episode
        # Auto on the shot is a choice too: this shot drops the episode's palette.
        self.assertEqual(look.compile_look(episode, {"palette": "auto"})["color"], "")

    def test_unknown_settings_or_ids_on_either_side_raise(self):
        for episode, shot in (({"palette": "teal"}, {}), ({}, {"palette": "teal"}), ({}, {"camera": {"body": "film-35mm"}}),
                              ({"colour": "auto"}, {})):
            with self.subTest(episode=episode, shot=shot), self.assertRaises(look.LookCatalogError):
                look.compile_look(episode, shot)


class SourceLookTests(unittest.TestCase):
    def test_a_task_source_carries_the_clip_lines_and_the_film_line_of_a_still(self):
        episode, shot = {"genre": "field-record", "tempo": "staccato-run", "camera": {"lens": "anamorphic"}}, {"light": "low-sun"}
        source = look.source_look(episode, shot)
        self.assertEqual(source, dict(look.compile_look(episode, shot), filmStill=look.compile_look(episode, shot, still=True)["film"]))
        self.assertEqual(source["filmStill"], text("genre", "field-record"))
        self.assertEqual(json.loads(json.dumps(source)), source)  # plain text: it travels in a task's JSON input

    def test_a_look_that_sets_nothing_is_no_look(self):
        for episode, shot in (({}, {}), ({"genre": "auto", "camera": {"body": "auto-body"}}, {"light": None}), (None, None)):
            with self.subTest(episode=episode, shot=shot):
                self.assertIsNone(look.source_look(episode, shot))


class MoveTokenTests(unittest.TestCase):
    def test_a_tag_opens_a_word_and_names_a_catalog_move(self):
        cases = {
            "@CAST-01#night walks in": [],              # wardrobe variant, not a move (§1.2 F)
            "@CAST-01#push-in walks in": [],            # even when the variant shares a move's name
            "@SET-01 at dusk": [],
            "#push-in on Kael": [(0, "push-in")],       # start of the text
            "Kael waits.\n#pan to the door": [(12, "pan")],  # start of a line
            "中文#push-in": [],                          # glued to the text before it
            "中文 #push-in": [(3, "push-in")],
            "他看著　#pan": [(4, "pan")],             # ideographic space
            "#push-in他轉身": [(0, "push-in")],          # CJK may follow the tag
            "#push-in, then #static.": [(0, "push-in"), (15, "static")],
            "#foo is not a move": [],
            "@CAST-01 #night": [],                      # unknown #word
            "#push-inward": [], "#push-inX": [], "#Push-In": [], "##pan": [], "see /#pan": [], "a-#pan": [],
            "": [],
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(look.move_tokens(text), expected)
        self.assertEqual(look.move_tokens(None), [])

    def test_a_prompt_without_a_candidate_never_reads_the_catalog(self):
        with patch.object(look, "_index", side_effect=AssertionError("catalog read")):
            self.assertEqual(look.move_tokens("@CAST-01#night enters @SET-01 at f/1.4"), [])
            self.assertEqual(look.expand_moves("中文#push-in"), "中文#push-in")


class ExpandMovesTests(unittest.TestCase):
    def test_tags_expand_where_they_stand_and_keep_the_segment_order(self):
        text = "[0-1.5s] @CAST-01 stands at the console. #push-in\n[1.5-3s] He turns the dial. #static"
        self.assertEqual(look.expand_moves(text),
                         f"[0-1.5s] @CAST-01 stands at the console. {PUSH}\n[1.5-3s] He turns the dial. {STATIC}")
        text = "#pan [0-2s] @CAST-01#night crosses the room #foo"
        self.assertEqual(look.expand_moves(text), f"{PAN} [0-2s] @CAST-01#night crosses the room #foo")

    def test_the_sentence_fits_the_character_after_the_tag(self):
        self.assertEqual(look.expand_moves("#push-in, then he stops"), PUSH[:-1] + ", then he stops")
        self.assertEqual(look.expand_moves("#push-in。他停下"), PUSH[:-1] + "。他停下")
        self.assertEqual(look.expand_moves("#push-in他轉身"), PUSH + " 他轉身")
        self.assertEqual(look.expand_moves('#push-in"Wait."'), PUSH + ' "Wait."')  # an opening quote, not a closing mark
        self.assertEqual(look.expand_moves("#push-in\nHe stops."), PUSH + "\nHe stops.")

    def test_text_without_catalog_tags_is_returned_unchanged(self):
        for text in ("@CAST-01#night enters @SET-01.", "中文#push-in", "#foo bar", "Optical f/1.4 ## #", "  indented\n"):
            with self.subTest(text=text):
                self.assertEqual(look.expand_moves(text), text)
                self.assertEqual(look.expand_moves(text, still=True), text)
        self.assertEqual(look.expand_moves(None), "")

    def test_auto_expands_to_nothing(self):
        self.assertEqual(look.expand_moves("Kael turns. #auto He walks."), "Kael turns. He walks.")
        self.assertEqual(look.expand_moves("A #push-in #auto B"), f"A {PUSH} B")

    def test_a_still_drops_catalog_tags_with_one_side_of_their_spacing(self):
        cases = {
            "Kael turns. #push-in He walks.": "Kael turns. He walks.",
            "#pan Kael walks.": "Kael walks.",
            "Kael walks. #pan": "Kael walks.",
            "他轉身 #push-in。": "他轉身。",
            "A #push-in #pan B": "A B",
            "  #pan indented": "  indented",
            "[0-1.5s] Kael stands. #push-in\n[1.5-3s] He turns the dial. #static\n  #pan\nend":
                "[0-1.5s] Kael stands.\n[1.5-3s] He turns the dial.\n\nend",
            "@CAST-01#night waits #foo. #whip-pan": "@CAST-01#night waits #foo.",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(look.expand_moves(text, still=True), expected)


if __name__ == "__main__":
    unittest.main()
