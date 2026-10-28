"""SPEC_18 R12: the episode's asset list says how many looks each asset has and how many still lack a picture of their own."""
import os
import unittest

from project_docs import story_asset_edit as edit
from story_pack_b_fixture import PackBFixture


def item(code, image=None):
    return {"assetCode": code, "isDefault": ":" not in code, "selectedImageUrl": image}


class WithLooksPureTests(unittest.TestCase):
    def test_each_default_asset_counts_its_own_looks_and_the_ones_without_a_picture(self):
        everything = [item("CAST-01", "/k.png"), item("CAST-01:NIGHT", "/n.png"), item("CAST-01:LISTENING"), item("CAST-01:RAIN", None),
                      item("CAST-02"), item("SET-01:DUSK"), item("SET-01", "/s.png"), item("CAST-010:X")]
        defaults = [a for a in everything if a["isDefault"]]
        listed = {a["assetCode"]: a["looks"] for a in edit.with_looks(defaults, everything)}
        self.assertEqual(listed, {"CAST-01": {"total": 3, "missingImages": 2}, "CAST-02": {"total": 0, "missingImages": 0}, "SET-01": {"total": 1, "missingImages": 1}},
                         "CAST-010:X belongs to CAST-010, not to CAST-01")

    def test_the_asset_itself_is_otherwise_unchanged_and_an_empty_episode_is_empty(self):
        base = item("CAST-01", "/k.png") | {"name": "Kael", "voice": "low"}
        (listed,) = edit.with_looks([base], [base])
        self.assertEqual({key: value for key, value in listed.items() if key != "looks"}, base)
        self.assertEqual(edit.with_looks([], []), [])


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "set OPENBENCH_TEST_DB_URI for Story HTTP tests")
class AssetLooksHTTPTests(PackBFixture, unittest.TestCase):
    def test_the_list_carries_looks_for_default_assets_only(self):
        self.prepare()
        kael = self.asset("CAST-01")
        for name, key, kind in (("Night jacket", "night", "OUTFIT"), ("Listening", "listening", "POSE")):
            self.ok(f"/assets/{kael['assetId']}/variants", "POST", {"name": name, "key": key, "kind": kind, "prompt": "same courier"})
        listed = self.ok(f"/episodes/{self.ep}/assets?limit=100")["items"]
        self.assertFalse(any(":" in a["assetCode"] for a in listed), "looks are not cards of their own")
        self.assertEqual(next(a for a in listed if a["assetCode"] == "CAST-01")["looks"], {"total": 2, "missingImages": 2})
        self.assertTrue(all("looks" in a for a in listed))
        self.assertEqual(next(a for a in listed if a["assetCode"] == "PROP-03")["looks"], {"total": 2, "missingImages": 2})  # Updraft's lit and dead burner
        others = [a["looks"] for a in listed if a["assetCode"] not in ("CAST-01", "PROP-03")]
        self.assertTrue(others and all(looks == {"total": 0, "missingImages": 0} for looks in others))
        detail = self.ok("/assets/" + kael["assetId"])
        self.assertEqual(len(detail["variants"]), 2, "the detail still lists the looks themselves")
