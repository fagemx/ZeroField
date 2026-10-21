"""Launcher contracts and idempotent, non-destructive showcase seeding."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch
import uuid

import run_studio as studio
from project_assistant import flow_runner, limbs
from project_docs import repository as repo, service


class LauncherTests(unittest.TestCase):
    def test_help_does_not_start_database_or_workers(self):
        with patch.object(studio.server, "_start_local_postgres") as start, contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as result:
                studio.main(["--help"])
            self.assertEqual(result.exception.code, 0)
            self.assertIn("--no-worker", output.getvalue())
            start.assert_not_called()

    def test_config_routes_video_workflows_separately(self):
        configs = studio.worker_configs("http://127.0.0.1:8188")
        cinema = configs["cinema"]["video_gen"]
        v2v = configs["v2v"]["video_gen"]
        self.assertEqual(cinema["image_node"], "2")
        self.assertEqual((v2v["video_node"], v2v["image_node"]), ("1", "2"))
        self.assertNotEqual(cinema["workflow"], v2v["workflow"])
        self.assertEqual(configs["split"]["media_assemble"]["layout"], "side_by_side")
        self.assertEqual(configs["extract"]["media_assemble"]["mode"], "extract_frame")
        self.assertEqual(configs["structure"]["media_assemble"]["mode"], "motion_structure")
        for key in ("image", "cinema", "v2v", "motion", "lookkey", "look", "swapkey", "swap", "layoutkey", "layout"):
            for config in configs[key].values():
                self.assertTrue(Path(config["workflow"]).is_file())

    def test_external_anchor_override_resolves_workflow_relative_to_config(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workers.json"
            path.write_text(json.dumps({"anchor": {"image_gen": {"adapter": "comfyui",
                "workflow": "external-edit.json", "input_bindings": {"first_frame": {"node": "pose", "input": "image", "upload": "image"}}}}}), encoding="utf-8")
            result = studio.load_worker_configs(path, studio.worker_configs("http://127.0.0.1:8188"))
            config = result["anchor"]["image_gen"]
            self.assertEqual(config["workflow"], str((Path(directory) / "external-edit.json").resolve()))
            self.assertEqual(config["reference_role"], "anchor_keyframe")
            self.assertIn("extract", result)

    def test_occupied_port_cannot_rotate_live_worker_credentials(self):
        with patch.object(studio.auth, "config", return_value={"mode": "dev"}), \
                patch.object(studio.server, "OpenBenchHTTPServer", side_effect=OSError("Port occupied")), \
                patch.object(studio.http, "open_connection") as connect, \
                patch.object(studio, "register_workers") as register, \
                patch.object(studio.server, "_start_local_postgres") as start:
            with self.assertRaises(OSError):
                studio.main([])
        connect.assert_not_called()
        register.assert_not_called()
        start.assert_not_called()

    def test_database_url_is_honored_and_no_worker_starts_nothing(self):
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (1,)
        http_server = MagicMock()
        http_server.server_port = 3020
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://dedicated-test", "OPENBENCH_DB_URI": ""}), \
                patch.object(studio.auth, "config", return_value={"mode": "token", "tokens": {}}), \
                patch.object(studio.server, "_start_local_postgres") as start, \
                patch.object(studio.http, "open_connection", return_value=conn), \
                patch.object(studio.repo, "ensure_schema"), \
                patch.object(studio.server, "OpenBenchHTTPServer", return_value=http_server), \
                patch.object(studio.assistant_worker, "start_in_background") as agent, \
                patch.object(studio, "start_media_workers") as media, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(studio.main(["--no-worker"]), 0)
        start.assert_not_called()
        agent.assert_not_called()
        media.assert_not_called()
        http_server.server_close.assert_called_once()


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "set OPENBENCH_TEST_DB_URI")
class ShowcaseDatabaseTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.conn = psycopg.connect(os.environ["OPENBENCH_TEST_DB_URI"])
        repo.ensure_schema(self.conn)
        self.actor = str(uuid.uuid4())
        self.slug = "studio-test-" + uuid.uuid4().hex[:12]
        self.me = service.Identity(self.actor, "Studio test", "admin")
        repo.upsert_member(self.conn, self.actor, "Studio test", "admin")
        code, result = service.create_project(self.conn, self.me, {"slug": self.slug, "title": "Test Film", "template": "zerofield_studio"})
        self.assertEqual(code, 200, result)

    def tearDown(self):
        self.conn.rollback()
        self.conn.close()

    def test_media_seed_preserves_template_ids_and_is_idempotent(self):
        before = repo.get_tab(self.conn, self.slug, "cinema-studio")
        table = next(n for n in before["doc"]["content"] if n["type"] == "table")
        row_id = table["content"][1]["attrs"]["bid"]
        result = studio.seed_showcase_media(self.conn, self.slug, actor_id=self.actor)
        self.assertTrue(result["seeded"])
        after = repo.get_tab(self.conn, self.slug, "cinema-studio")
        table = next(n for n in after["doc"]["content"] if n["type"] == "table")
        self.assertEqual(table["content"][1]["attrs"]["bid"], row_id)
        self.assertEqual(table["attrs"]["column_ids"], next(n for n in before["doc"]["content"] if n["type"] == "table")["attrs"]["column_ids"])
        self.assertIn("@CAST-01 @SET-01", studio._text(table["content"][1]))
        self.assertIn("Approved", studio._text(table["content"][1]))
        self.assertIn("Pending Review", studio._text(table["content"][2]))
        self.assertIn("Queued", studio._text(table["content"][3]))
        annotations = repo.list_annotations(self.conn, self.slug, tab_key="cinema-studio")
        self.assertEqual(len(annotations), 1)
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM projectops.asset WHERE project_slug=%s", (self.slug,))
            count = cur.fetchone()[0]
        self.assertGreaterEqual(count, 6)
        lab = repo.get_tab(self.conn, self.slug, "openjutsu-lab")
        ref_table = next(n for n in lab["doc"]["content"] if n["type"] == "table")
        self.assertEqual([studio._text(c) for c in ref_table["content"][0]["content"][-3:]], ["First Frame", "Motion Structure", "Anchor Keyframe"])
        self.assertTrue(all(studio._text(c).startswith("/projects/api/") for c in ref_table["content"][1]["content"][-3:]))
        self.assertFalse(studio.seed_showcase_media(self.conn, self.slug, actor_id=self.actor)["seeded"])
        self.assertEqual(repo.get_tab(self.conn, self.slug, "cinema-studio")["revision"], after["revision"])

    def test_existing_media_and_prompt_are_preserved(self):
        tab = repo.get_tab(self.conn, self.slug, "cinema-studio")
        table = next(n for n in tab["doc"]["content"] if n["type"] == "table")
        cells = table["content"][1]["content"]
        studio._set_text(cells[3], "Custom director prompt")
        studio._set_text(cells[4], "/projects/api/" + self.slug + "/assets/pa_" + "a" * 32)
        repo.save_tab_doc(self.conn, self.slug, "cinema-studio", doc=tab["doc"], title=tab["title"],
            actor_id=self.actor, session_id="user", base_revision=tab["revision"])
        studio.seed_showcase_media(self.conn, self.slug, actor_id=self.actor)
        saved = repo.get_tab(self.conn, self.slug, "cinema-studio")
        row = next(n for n in saved["doc"]["content"] if n["type"] == "table")["content"][1]
        self.assertEqual(studio._text(row["content"][3]), "Custom director prompt")
        self.assertTrue(studio._text(row["content"][4]).endswith("a" * 32))
        self.assertIn("Queued", studio._text(row))

    def test_workers_keep_ids_rotate_tokens_and_bind_disjoint_pipeline_branches(self):
        configs = studio.worker_configs("http://127.0.0.1:8188")
        studio.seed_showcase_media(self.conn, self.slug, actor_id=self.actor)
        first = studio.register_workers(self.conn, self.slug, configs, self.actor)
        again = studio.register_workers(self.conn, self.slug, configs, self.actor)
        self.assertEqual({k: v["id"] for k, v in first.items()}, {k: v["id"] for k, v in again.items()})
        self.assertNotEqual(first["cinema"]["token"], again["cinema"]["token"])
        self.assertTrue(studio.seed_showcase_pipeline(self.conn, self.slug, again, self.actor))
        graph = flow_runner.definition(self.conn, self.slug, "comfy-pipeline")["definition"]
        nodes = {n["id"]: n for n in graph["nodes"]}
        self.assertNotEqual(nodes["cinema"]["limb_id"], nodes["v2v"]["limb_id"])
        self.assertEqual(nodes["keyframe"]["target"]["col_index"], 4)
        self.assertNotIn({"source": "cinema", "target": "v2v"}, graph["edges"])
        self.assertTrue(all(n["write_mode"] == "proposal" for n in graph["nodes"]))
        self.assertEqual(nodes["extract"]["target"]["col_index"], 8)
        self.assertIn({"source": "structure", "target": "v2v"}, graph["edges"])
        # Previs lane: its own workers, keyframe/shot columns, and a motion -> look key -> look chain.
        self.assertEqual([nodes[k]["target"]["col_index"] for k in ("motion", "lookkey", "look")], [5, 4, 5])
        self.assertEqual(len({nodes[k]["limb_id"] for k in ("motion", "lookkey", "look", "cinema")}), 4)
        self.assertTrue({"source": "motion", "target": "lookkey"} in graph["edges"] and {"source": "lookkey", "target": "look"} in graph["edges"])
        # Layout lane: Klein key from previs frame 0 into Keyframe, then the IC-LoRA render into Cinema Shot, own workers.
        self.assertEqual([nodes[k]["target"]["col_index"] for k in ("layoutkey", "layout")], [4, 5])
        self.assertEqual(len({nodes[k]["limb_id"] for k in ("layoutkey", "layout", "lookkey", "motion")}), 4)
        self.assertIn({"source": "layoutkey", "target": "layout"}, graph["edges"])
        self.assertFalse(studio.seed_showcase_pipeline(self.conn, self.slug, again, self.actor))

    def test_three_lane_showcase_pipeline_upgrades_to_the_previs_lane(self):
        configs = studio.worker_configs("http://127.0.0.1:8188")
        studio.seed_showcase_media(self.conn, self.slug, actor_id=self.actor)
        older = {k: v for k, v in configs.items() if k not in ("motion", "lookkey", "look", "swapkey", "swap", "layoutkey", "layout")}
        self.assertTrue(studio.seed_showcase_pipeline(self.conn, self.slug, studio.register_workers(self.conn, self.slug, older, self.actor), self.actor))
        self.assertNotIn("motion", {n["id"] for n in flow_runner.definition(self.conn, self.slug, "comfy-pipeline")["definition"]["nodes"]})
        self.assertTrue(studio.seed_showcase_pipeline(self.conn, self.slug, studio.register_workers(self.conn, self.slug, configs, self.actor), self.actor))
        self.assertIn("look", {n["id"] for n in flow_runner.definition(self.conn, self.slug, "comfy-pipeline")["definition"]["nodes"]})

    def test_four_lane_pipeline_gains_the_object_swap_lane_for_swap_rows_only(self):
        configs = studio.worker_configs("http://127.0.0.1:8188")
        studio.seed_showcase_media(self.conn, self.slug, actor_id=self.actor)
        older = studio.register_workers(self.conn, self.slug, {k: v for k, v in configs.items() if k not in ("swapkey", "swap", "layoutkey", "layout")}, self.actor)
        self.assertTrue(studio.seed_showcase_pipeline(self.conn, self.slug, older, self.actor))
        everyone = studio.register_workers(self.conn, self.slug, configs, self.actor)
        self.assertTrue(studio.seed_showcase_pipeline(self.conn, self.slug, everyone, self.actor))
        graph = flow_runner.definition(self.conn, self.slug, "comfy-pipeline")["definition"]
        nodes = {n["id"]: n for n in graph["nodes"]}
        self.assertIn({"source": "swapkey", "target": "swap"}, graph["edges"])
        self.assertEqual([nodes[k]["target"]["col_index"] for k in ("swapkey", "swap")], [10, 4])  # Anchor Keyframe, Remastered Video
        self.assertEqual(len({nodes[k]["limb_id"] for k in ("swapkey", "swap", "v2v", "lookkey")}), 4)
        for key in ("swapkey", "swap"):
            self.assertEqual({k: nodes[key]["row_source"][k] for k in ("status_col", "status")}, {"status_col": 1, "status": ["Object Swap"]})
        # The seeded VFX-01 row is Motion Transfer: the restyle lane takes it, the swap lane matches nothing until a row is Object Swap.
        self.assertEqual(flow_runner._source_rows(self.conn, self.slug, nodes["swap"]["row_source"]), [])
        self.assertEqual(len(flow_runner._source_rows(self.conn, self.slug, nodes["v2v"]["row_source"])), 1)
        self.assertFalse(studio.seed_showcase_pipeline(self.conn, self.slug, everyone, self.actor))

    def test_five_lane_pipeline_gains_the_layout_lane(self):
        configs = studio.worker_configs("http://127.0.0.1:8188")
        studio.seed_showcase_media(self.conn, self.slug, actor_id=self.actor)
        older = studio.register_workers(self.conn, self.slug, {k: v for k, v in configs.items() if k not in ("layoutkey", "layout")}, self.actor)
        self.assertTrue(studio.seed_showcase_pipeline(self.conn, self.slug, older, self.actor))
        everyone = studio.register_workers(self.conn, self.slug, configs, self.actor)
        self.assertTrue(studio.seed_showcase_pipeline(self.conn, self.slug, everyone, self.actor))
        graph = flow_runner.definition(self.conn, self.slug, "comfy-pipeline")["definition"]
        nodes = {n["id"]: n for n in graph["nodes"]}
        self.assertIn({"source": "layoutkey", "target": "layout"}, graph["edges"])
        self.assertGreater(nodes["layoutkey"]["y"], nodes["swapkey"]["y"])  # its own row under the swap lane
        self.assertFalse(studio.seed_showcase_pipeline(self.conn, self.slug, everyone, self.actor))

    def test_rearranged_pipeline_gets_the_previs_lane_appended_once(self):
        configs = studio.worker_configs("http://127.0.0.1:8188")
        studio.seed_showcase_media(self.conn, self.slug, actor_id=self.actor)
        older = studio.register_workers(self.conn, self.slug, {k: v for k, v in configs.items() if k not in ("motion", "lookkey", "look", "swapkey", "swap", "layoutkey", "layout")}, self.actor)
        studio.seed_showcase_pipeline(self.conn, self.slug, older, self.actor)
        current = flow_runner.definition(self.conn, self.slug, "comfy-pipeline")
        moved = copy.deepcopy(current["definition"]); moved["nodes"][0]["x"] += 37  # the user tidied the layout
        flow_runner.save_definition(self.conn, service.Identity(self.actor, "Alex", "admin"), self.slug, "comfy-pipeline",
                                    {"revision": current["revision"], "definition": moved})
        everyone = studio.register_workers(self.conn, self.slug, configs, self.actor)
        self.assertTrue(studio.seed_showcase_pipeline(self.conn, self.slug, everyone, self.actor))
        after = flow_runner.definition(self.conn, self.slug, "comfy-pipeline")
        nodes = {n["id"]: n for n in after["definition"]["nodes"]}
        self.assertEqual(nodes[moved["nodes"][0]["id"]]["x"], moved["nodes"][0]["x"])
        self.assertGreater(nodes["motion"]["y"], max(n.get("y", 0) for n in moved["nodes"]))
        self.assertGreater(nodes["swap"]["y"], nodes["motion"]["y"])  # each missing lane lands below the last one
        self.assertGreater(nodes["layout"]["y"], nodes["swap"]["y"])
        trimmed = copy.deepcopy(after["definition"])  # the user removes the lane again: it stays removed
        trimmed["nodes"] = [n for n in trimmed["nodes"] if n["id"] not in ("motion", "lookkey", "look")]
        trimmed["edges"] = [e for e in trimmed["edges"] if e["source"] not in ("motion", "lookkey") and e["target"] not in ("lookkey", "look")]
        flow_runner.save_definition(self.conn, service.Identity(self.actor, "Alex", "admin"), self.slug, "comfy-pipeline",
                                    {"revision": after["revision"], "definition": trimmed})
        self.assertFalse(studio.seed_showcase_pipeline(self.conn, self.slug, everyone, self.actor))

    def test_previs_seed_appends_columns_once_and_keeps_user_media(self):
        studio.seed_showcase_media(self.conn, self.slug, actor_id=self.actor)
        tab = repo.get_tab(self.conn, self.slug, "cinema-studio")
        table = next(n for n in tab["doc"]["content"] if n["type"] == "table")
        if "Previs" in [studio._text(c) for c in table["content"][0]["content"]]:  # fresh template already has them: drop them to test the upgrade
            for row in table["content"]:
                row["content"] = row["content"][:-2]
            table["attrs"]["column_types"] = table["attrs"]["column_types"][:-2]; table["attrs"].pop("column_ids", None)
            repo.save_tab_doc(self.conn, self.slug, "cinema-studio", doc=tab["doc"], title=tab["title"], actor_id=self.actor,
                              session_id="old", base_revision=tab["revision"], force_revision=True)
        ids = next(n for n in repo.get_tab(self.conn, self.slug, "cinema-studio")["doc"]["content"] if n["type"] == "table")["attrs"].get("column_ids")
        self.assertTrue(studio.seed_showcase_previs(self.conn, self.slug, actor_id=self.actor)["seeded"])
        table = next(n for n in repo.get_tab(self.conn, self.slug, "cinema-studio")["doc"]["content"] if n["type"] == "table")
        self.assertEqual([studio._text(c) for c in table["content"][0]["content"][-2:]], ["Previs", "Actor Matte"])
        self.assertEqual(table["attrs"]["column_types"][-2:], ["video", "video"])
        if ids:
            self.assertEqual(table["attrs"]["column_ids"][:len(ids)], ids)
        s03 = next(r for r in table["content"][1:] if studio._text(r["content"][0]) == "S03")
        self.assertTrue(studio._text(s03["content"][-2]).startswith("/projects/api/"))
        self.assertEqual(studio._text(s03["content"][-1]), "")  # the Blender blockout has no stage matte: a stage render adds it
        self.assertFalse(studio.seed_showcase_previs(self.conn, self.slug, actor_id=self.actor)["seeded"])


if __name__ == "__main__":
    unittest.main()
