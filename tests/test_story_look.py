"""SPEC_19 package B look catalog: validation, Optical Rig text and in-place #move tags."""
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


def items(kind, group=None):
    return [item for item in CATALOG["items"] if item["kind"] == kind and item.get("group") == group]


def broken(change):
    data = copy.deepcopy(CATALOG)
    change(data["items"])
    return data


class CatalogTests(unittest.TestCase):
    def test_packaged_catalog_lists_the_package_b_options_in_order(self):
        look.validate(CATALOG)
        self.assertEqual({item["kind"] for item in CATALOG["items"]}, {"camera", "move"})
        self.assertEqual([i["id"] for i in items("camera", "body")],
                         ["auto-body", "digital-cinema", "film-35mm", "film-16mm", "film-8mm", "dv-camcorder"])
        self.assertEqual([i["id"] for i in items("camera", "lens")],
                         ["auto-lens", "clean-sharp", "anamorphic", "vintage-anamorphic", "vintage-warm", "vintage-glow"])
        self.assertEqual([i["id"] for i in items("camera", "aperture")], ["auto-aperture", "f1-4", "f4", "f11"])
        self.assertEqual([i["id"] for i in items("move")],
                         ["auto", "push-in", "pull-out", "tracking", "pan", "crane-up", "crane-down", "orbit-180",
                          "handheld", "whip-pan", "rack-focus", "pov", "static"])
        self.assertEqual(look.catalog(), CATALOG["items"])

    def test_every_choice_starts_with_an_empty_auto_and_the_rest_are_english_sentences(self):
        for kind, groups in look.KINDS.items():
            for group in groups or (None,):
                options = items(kind, group)
                with self.subTest(kind=kind, group=group):
                    self.assertEqual(options[0]["promptText"], "")
                    self.assertTrue(options[0]["id"].startswith("auto"))
                    for item in options[1:]:
                        text = item["promptText"]
                        self.assertTrue(text.isascii() and text.endswith(".") and len(text.split()) >= 8, text)
                        self.assertRegex(item["labelKey"], r"^lookCatalog\.")
        self.assertEqual(len({item["labelKey"] for item in CATALOG["items"]}), len(CATALOG["items"]))

    def test_options_name_no_brands_people_or_titles_and_camera_text_names_no_equipment(self):
        for item in CATALOG["items"]:
            words = lambda text: set(re.findall(r"[a-z0-9]+", text.lower()))
            prompt = words(item["promptText"])
            with self.subTest(option=item["id"]):
                self.assertFalse((words(item["id"] + " " + item["labelKey"]) | prompt) & set(BRANDS))
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

        auto_lens, auto_move = first("camera", "lens"), first("move")
        cases = {
            "unique within a kind": add({"kind": "move", "id": "pan", "labelKey": "lookCatalog.move.pan2", "promptText": "Pan again."}),
            "unknown kind": add({"kind": "palette", "id": "teal", "labelKey": "lookCatalog.palette.teal", "promptText": "Teal."}),
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
        self.assertEqual(moves[1], {"id": "push-in", "kind": "move", "labelKey": "lookCatalog.move.pushIn", "promptText": PUSH, "preview": None})
        self.assertTrue(all("group" not in i and "hex" not in i for i in moves))

    def test_kinds_not_in_the_catalog_yet_list_nothing_and_other_kinds_are_refused(self):
        # Package C fills genre, era, tempo, palette and light; until then they are empty, not errors.
        for kind in ("genre", "era", "tempo", "palette", "light"):
            self.assertEqual(look.api_items(kind), [], kind)
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
