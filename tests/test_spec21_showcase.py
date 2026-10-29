"""SPEC_21 A12: the Updraft showcase. Template content comes from samples/updraft/production.json; the seed writes asset_meta
records and the episode look, and fills media from samples/updraft/manifest.json into empty cells only, once."""
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid

import run_studio as studio
from project_docs import repository as repo, service, story_assets, story_openapi as story, templates

PNG = b"\x89PNG\r\n\x1a\n" + b"updraft" * 16


class TemplateTests(unittest.TestCase):
    def test_tabs_are_updraft_from_the_json(self):
        production = templates.load_updraft()
        specs = {s[0]: s for s in templates.tab_specs("zerofield_studio", "Updraft", "")}
        self.assertEqual(list(specs), ["director-brief", "soul-cast", "cinema-studio", "openjutsu-lab", "comfy-pipeline"])
        self.assertIn("trainee pilot", specs["director-brief"][3])
        cast = specs["soul-cast"][3]
        for asset in production["assets"]:
            self.assertIn("| " + asset["code"] + " |", cast)
        self.assertIn("Same identity as @PROP-03: same shape, materials and proportions. Changed: ", cast)
        self.assertEqual(sum(1 for line in cast.split("\n") if line.endswith("| STATE |")), 2)
        shots = specs["cinema-studio"][3]
        for shot in production["shots"]:
            self.assertIn("| " + shot["code"] + " |", shots)
        self.assertNotIn("Kael", "".join(s[3] for s in specs.values()))

    def test_action_lines_become_hard_breaks_and_survive_the_doc(self):
        from project_docs import markdown_import
        from project_docs.doc_schema import doc_text, validate_doc
        key, _, _, md = next(s for s in templates.tab_specs("zerofield_studio", "Updraft", "") if s[0] == "cinema-studio")
        doc, _ = markdown_import.markdown_to_doc(md, tab_keys=set(), image_src=lambda _: None)
        doc, _ = validate_doc(doc, slug="x")
        templates.configure_doc(key, doc)
        text = doc_text(doc)
        first = templates.load_updraft()["shots"][0]["action"]
        self.assertIn(first.split("\n")[1], text)
        self.assertIn("\nPHYSICS:", text)
        self.assertNotIn(templates.LINE_BREAK, text)

    def test_structure_only_keeps_headers_without_rows(self):
        specs = templates.tab_specs("zerofield_studio", "Blank", "", samples=False)
        self.assertEqual(specs[0][3], "")
        self.assertNotIn("CAST-01", specs[1][3])
        self.assertIn("| Asset ID |", specs[1][3])


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "set OPENBENCH_TEST_DB_URI")
class SeedTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.conn = psycopg.connect(os.environ["OPENBENCH_TEST_DB_URI"])
        repo.ensure_schema(self.conn)
        self.actor = str(uuid.uuid4())
        self.slug = "updraft-" + uuid.uuid4().hex[:12]
        self.me = service.Identity(self.actor, "Seed test", "admin")
        repo.upsert_member(self.conn, self.actor, "Seed test", "admin")
        code, result = service.create_project(self.conn, self.me, {"slug": self.slug, "title": "Updraft", "template": "zerofield_studio"})
        self.assertEqual(code, 200, result)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.conn.rollback()
        self.conn.close()

    def seed(self):
        return studio.seed_showcase_media(self.conn, self.slug, samples_dir=self.root, actor_id=self.actor)

    def manifest(self, items):
        for item in items:
            (self.root / item["file"]).write_bytes(PNG + item["file"].encode())
        (self.root / "manifest.json").write_text(json.dumps({"items": items}), encoding="utf-8")

    def cell(self, tab, code, header):
        for table in repo.get_tab(self.conn, self.slug, tab)["doc"]["content"]:
            if table["type"] == "table":
                headers = [studio._text(c) for c in table["content"][0]["content"]]
                row = next(r for r in table["content"][1:] if studio._text(r["content"][0]) == code)
                return row["content"][headers.index(header)], row
        raise AssertionError(tab)

    def meta(self, code):
        row = next(r for r in story.table_rows(self.conn, self.slug, "soul-cast") if r["cells"][0] == code)
        return story_assets.meta_of(self.conn, row)

    def test_no_manifest_writes_meta_and_look_only(self):
        result = self.seed()
        self.assertTrue(result["seeded"])
        production = templates.load_updraft()
        noa = next(a for a in production["assets"] if a["code"] == "CAST-01")
        self.assertEqual(self.meta("CAST-01")["acting"], noa["meta"]["acting"])
        self.assertEqual(self.meta("SET-01")["geo"], next(a for a in production["assets"] if a["code"] == "SET-01")["meta"]["geo"])
        lit = self.meta("PROP-03:lit")
        self.assertTrue(lit["change"].startswith("Both coils are firing"))
        self.assertEqual(set(self.meta("PROP-03")["panels"]), {"product"})
        episode = story.episode(self.conn, f"ep_{self.slug}_01")
        self.assertEqual(episode["settings"]["look"]["camera"]["body"], "film-35mm")
        self.assertEqual(studio._text(self.cell("soul-cast", "CAST-01", "Reference Image")[0]), "")
        self.assertFalse(self.seed()["seeded"])

    def test_meta_and_look_are_not_overwritten(self):
        self.seed()
        row = next(r for r in story.table_rows(self.conn, self.slug, "soul-cast") if r["cells"][0] == "CAST-01")
        story_assets.write_meta(self.conn, self.slug, row, {"acting": "My own profile"})
        self.seed()
        self.assertEqual(self.meta("CAST-01")["acting"], "My own profile")

    def test_manifest_fills_only_empty_cells_once(self):
        self.manifest([
            {"tab": "soul-cast", "code": "CAST-01", "column": "Reference Image", "panel": "face", "file": "noa_face.png",
             "card": "flux-soul-cast", "seed": 7, "prompt": "p"},
            {"tab": "cinema-studio", "code": "S01", "column": "Keyframe", "panel": None, "file": "s01_key.png", "card": "flux-reference-key", "seed": 8, "prompt": "q"},
            {"tab": "cinema-studio", "code": "S02", "column": "Keyframe", "panel": None, "file": "s02_key.png", "card": "flux-reference-key", "seed": 9, "prompt": "r"},
        ])
        tab = repo.get_tab(self.conn, self.slug, "cinema-studio")
        for table in tab["doc"]["content"]:
            if table["type"] == "table":
                headers = [studio._text(c) for c in table["content"][0]["content"]]
                row = next(r for r in table["content"][1:] if studio._text(r["content"][0]) == "S02")
                studio._set_text(row["content"][headers.index("Keyframe")], "/projects/api/" + self.slug + "/assets/pa_" + "a" * 32)  # the user's own picture
        repo.save_tab_doc(self.conn, self.slug, "cinema-studio", doc=tab["doc"], title=tab["title"], actor_id=self.actor,
                          session_id="user", base_revision=tab["revision"])
        self.assertTrue(self.seed()["seeded"])
        face = studio._text(self.cell("soul-cast", "CAST-01", "Reference Image")[0])
        self.assertTrue(face.startswith("/projects/api/" + self.slug + "/assets/pa_"))
        self.assertTrue(studio._text(self.cell("cinema-studio", "S01", "Keyframe")[0]).startswith("/projects/api/"))
        self.assertTrue(studio._text(self.cell("cinema-studio", "S02", "Keyframe")[0]).endswith("a" * 32))
        self.assertEqual(self.meta("CAST-01")["panels"]["face"]["url"], face)
        self.assertIn("Pending Review", studio._text(self.cell("soul-cast", "CAST-01", "Status")[0]))
        # the user clears S01's keyframe: the seed never refills it
        tab = repo.get_tab(self.conn, self.slug, "cinema-studio")
        for table in tab["doc"]["content"]:
            if table["type"] == "table":
                headers = [studio._text(c) for c in table["content"][0]["content"]]
                row = next(r for r in table["content"][1:] if studio._text(r["content"][0]) == "S01")
                studio._set_text(row["content"][headers.index("Keyframe")], "")
        repo.save_tab_doc(self.conn, self.slug, "cinema-studio", doc=tab["doc"], title=tab["title"], actor_id=self.actor,
                          session_id="user", base_revision=tab["revision"])
        self.assertFalse(self.seed()["seeded"])
        self.assertEqual(studio._text(self.cell("cinema-studio", "S01", "Keyframe")[0]), "")

    def test_panel_pictures_and_earlier_candidates_need_no_cell(self):
        self.manifest([
            {"tab": "soul-cast", "code": "CAST-01", "column": None, "panel": "front", "file": "noa_front.png", "card": "server-crop", "seed": None, "prompt": None},
            {"tab": "soul-cast", "code": "CAST-01", "column": None, "panel": "face", "candidate": True, "file": "noa_face_2.png",
             "card": "flux-soul-cast", "seed": 21101, "prompt": "p"},
            {"tab": "cinema-studio", "code": "S01", "column": "Cinema Shot", "panel": None, "candidate": True, "file": "s01_take2.png",
             "card": "ltx25-cinema", "seed": 21002, "prompt": "v"},
        ])
        self.assertTrue(self.seed()["seeded"])
        self.assertTrue(self.meta("CAST-01")["panels"]["front"]["url"].startswith("/projects/api/" + self.slug + "/assets/pa_"))
        self.assertIsNone(self.meta("CAST-01")["panels"]["face"], "a candidate is listed, not chosen")
        self.assertEqual(studio._text(self.cell("cinema-studio", "S01", "Cinema Shot")[0]), "", "a candidate never fills the cell")
        _, cast = self.cell("soul-cast", "CAST-01", "Reference Image")
        faces = [c for c in story.records(self.conn, "candidate", self.slug) if c["entityId"] == f"as_{self.slug}_{cast['attrs']['bid']}"]
        self.assertEqual([(c["kind"], c["panel"]) for c in faces], [("image", "face")])
        _, shot = self.cell("cinema-studio", "S01", "Cinema Shot")
        takes = [c for c in story.records(self.conn, "candidate", self.slug) if c["entityId"] == f"sh_{self.slug}_{shot['attrs']['bid']}"]
        self.assertEqual(len(takes), 1)
        self.assertFalse(self.seed()["seeded"], "each item is applied once")

    def test_a_seeded_take_is_adopted_and_approved(self):
        self.manifest([{"tab": "cinema-studio", "code": "S01", "column": "Cinema Shot", "panel": None, "file": "s01_take.png",
                        "card": "ltx25-cinema", "seed": 1, "prompt": "v"}])
        self.seed()
        cell, shot = self.cell("cinema-studio", "S01", "Cinema Shot")
        meta = story.record(self.conn, f"meta_sh_{self.slug}_{shot['attrs']['bid']}", required=False)
        self.assertEqual(meta["adoption"]["url"], studio._text(cell))
        self.assertIn("Approved", studio._text(self.cell("cinema-studio", "S01", "Status")[0]))


if __name__ == "__main__":
    unittest.main()
