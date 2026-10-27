"""SPEC_20 R44-7: a pipeline step can be the default ("primary") step of the column it writes.

The seeded pipelines have several lanes writing Keyframe and Cinema Shot; their main lane is marked, untouched seeds from
before the marker upgrade, and a pipeline the user edited is never rewritten. Database tests never commit.
"""
import os
import unittest

import run_studio as studio
from project_assistant import flow_runner, local_workers
from project_docs import locale
from test_local_workers import _DatabaseCase


def step(identifier, target, **extra):
    return {"id": identifier, "title": identifier.title(), "capability": "image_gen", "scope": "rows",
            "row_source": {"tab_key": "cinema-studio"}, "target": {"tab_key": "cinema-studio", **target}, **extra}


class DefaultStepValidationTests(unittest.TestCase):
    def test_primary_is_an_optional_boolean_that_is_kept(self):
        graph = flow_runner.validate_definition({"nodes": [step("keyframe", {"col_index": 4}, primary=True),
            step("lookkey", {"col_index": 4}, primary=False), step("layoutkey", {"col_index": 4})], "edges": []})
        self.assertEqual([node.get("primary") for node in graph["nodes"]], [True, False, None])
        for value in ("yes", 1, None, [True]):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "^primary must be true or false.$"):
                flow_runner.validate_definition({"nodes": [step("keyframe", {"col_index": 4}, primary=value)], "edges": []})

    def test_two_default_steps_for_one_column_are_refused_in_plain_words(self):
        with self.assertRaises(ValueError) as caught:
            flow_runner.validate_definition({"nodes": [step("keyframe", {"col_index": 4}, primary=True),
                                                       step("layoutkey", {"col_index": 4}, primary=True)], "edges": []})
        message = str(caught.exception)
        self.assertEqual(message, "Only one step can be the default for a column: “Keyframe” and “Layoutkey” both write it. "
                                  "Turn the default off on one of them.")
        details = locale.error_details({"error": message})  # the interface shows it in the reader's language
        self.assertEqual((details["message_key"], details["message_params"]),
                         ("errors.onlyOneStepCanBeTheDefaultForAColumn", {"v0": "Keyframe", "v1": "Layoutkey"}))
        same = [({"column_id": "c_key", "col_index": 4}, {"column_id": "c_key", "col_index": 9}),  # the column id wins
                ({"table_id": "b_shots", "col_index": 4}, {"col_index": 4})]  # an unnamed worksheet is the page's first
        apart = [({"col_index": 4}, {"col_index": 5}),
                 ({"column_id": "c_key", "col_index": 4}, {"column_id": "c_shot", "col_index": 4}),
                 ({"table_id": "b_one", "col_index": 4}, {"table_id": "b_two", "col_index": 4}),
                 ({"col_index": 4}, {"tab_key": "soul-cast", "col_index": 4}),
                 ({"tab_key": "director-brief", "kind": "doc", "mode": "append"}, {"tab_key": "director-brief", "kind": "doc", "mode": "append"})]
        for pairs, refused in ((same, True), (apart, False)):
            for first, second in pairs:
                graph = {"nodes": [step("one", first, primary=True), step("two", second, primary=True)], "edges": []}
                with self.subTest(first=first, second=second):
                    if refused:
                        with self.assertRaisesRegex(ValueError, "^Only one step can be the default for a column"):
                            flow_runner.validate_definition(graph)
                    else:
                        self.assertEqual(len(flow_runner.validate_definition(graph)["nodes"]), 2)

    def test_the_main_lane_marker_and_the_seed_before_it(self):
        graph = {"nodes": [step("keyframe", {"col_index": 4}), step("lookkey", {"col_index": 4}),
                           dict(step("cinema", {"col_index": 5}), capability="video_gen")], "edges": []}
        marked = local_workers.mark_primary(graph)
        self.assertEqual({node["id"] for node in marked["nodes"] if node.get("primary")}, {"keyframe", "cinema"})
        self.assertNotIn("primary", graph["nodes"][0])  # the seed it was given is left as it was
        self.assertEqual(local_workers.without_primary(marked), graph)
        flow_runner.validate_definition(marked)


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "set OPENBENCH_TEST_DB_URI")
class DefaultStepSeedTests(_DatabaseCase):
    def primaries(self, slug):
        return {node["id"] for node in self.pipeline(slug)["definition"]["nodes"] if node.get("primary")}

    def save(self, slug, definition):
        current = self.pipeline(slug)
        return flow_runner.save_definition(self.conn, self.me, slug, "comfy-pipeline", {"revision": current["revision"], "definition": definition})

    def disable(self, *stages):
        with self.conn.cursor() as cur:
            cur.execute("UPDATE projectops.agent_limb SET enabled=FALSE WHERE id=ANY(%s::uuid[])",
                        ([local_workers.worker_id(stage) for stage in stages],))

    def test_a_new_production_runs_the_main_lane_on_the_local_klein_and_ltx_workers(self):
        registered = studio.register_workers(self.conn, self.configs, self.actor)
        slug = self.create()
        graph = self.pipeline(slug)["definition"]
        self.assertEqual(self.primaries(slug), {"keyframe", "cinema"})
        writers = lambda column: {node["id"] for node in graph["nodes"] if node["target"].get("tab_key") == "cinema-studio"
                                  and node["target"].get("col_index") == column}
        self.assertEqual((writers(4), writers(5)), ({"keyframe", "lookkey", "layoutkey"}, {"cinema", "motion", "look", "layout"}))
        # The default steps are bound to the launcher's FLUX 3 Klein image worker and LTX-2.5 cinema worker.
        nodes = {node["id"]: node for node in graph["nodes"]}
        self.assertEqual((nodes["keyframe"]["limb_id"], nodes["cinema"]["limb_id"]), (registered["image"]["id"], registered["cinema"]["id"]))
        self.assertTrue(self.configs["image"]["image_gen"]["workflow"].endswith("flux3_klein_soul_cast.json"))
        self.assertTrue(self.configs["cinema"]["video_gen"]["workflow"].endswith("ltx25_cinema_shot.json"))
        workers = self.connect(registered)
        row = self.queue_single_step(slug, "keyframe", self.pipeline(slug)["revision"])
        for stage in ("lookkey", "layoutkey"):
            self.assertIsNone(flow_runner.claim(self.conn, workers[stage])["task"])
        task = flow_runner.claim(self.conn, workers["image"])["task"]
        self.assertEqual((task["node_id"], task["row_id"]), ("keyframe", row))
        preview = flow_runner.preflight(self.conn, self.me, slug, "comfy-pipeline", {"start_node_id": "keyframe"})
        self.assertEqual(([entry["node_id"] for entry in preview["nodes"]], preview["errors"]), (["keyframe", "cinema", "assemble"], []))

    def test_an_untouched_production_from_before_the_marker_upgrades_and_an_edited_one_stays(self):
        registered = studio.register_workers(self.conn, self.configs, self.actor)
        untouched, edited, current = self.create(), self.create(), self.create()
        self.save(untouched, local_workers.without_primary(self.pipeline(untouched)["definition"]))
        moved = local_workers.without_primary(self.pipeline(edited)["definition"])
        moved["nodes"][0]["x"] += 25  # the user tidied the layout of a seed from before the marker
        self.save(edited, moved)
        before = {slug: self.pipeline(slug) for slug in (edited, current)}
        adopted = local_workers.adopt_template_pipelines(self.conn, self.me, registered)
        self.assertIn(untouched, adopted)
        self.assertEqual(self.pipeline(untouched)["definition"], local_workers.studio_pipeline(self.conn, untouched, registered))
        self.assertEqual(self.primaries(untouched), {"keyframe", "cinema"})
        for slug in (edited, current):
            self.assertNotIn(slug, adopted)
            self.assertEqual(self.pipeline(slug), before[slug])
        self.assertNotIn(untouched, local_workers.adopt_template_pipelines(self.conn, self.me, registered))

    def test_a_production_seeded_from_fewer_workers_before_the_marker_upgrades_to_the_current_seed(self):
        self.disable("layoutkey", "layout")
        studio.register_workers(self.conn, {k: v for k, v in self.configs.items() if k not in ("layoutkey", "layout")}, self.actor)
        slug = self.create()
        self.assertNotIn("layout", {node["id"] for node in self.pipeline(slug)["definition"]["nodes"]})
        self.save(slug, local_workers.without_primary(self.pipeline(slug)["definition"]))
        everyone = studio.register_workers(self.conn, self.configs, self.actor)
        self.assertIn(slug, local_workers.adopt_template_pipelines(self.conn, self.me, everyone))
        self.assertIn("layout", {node["id"] for node in self.pipeline(slug)["definition"]["nodes"]})
        self.assertEqual(self.primaries(slug), {"keyframe", "cinema"})

    def test_the_showcase_marks_its_main_lane_and_never_rewrites_a_rearranged_pipeline(self):
        slug = self.create("showcase")
        studio.seed_showcase_media(self.conn, slug, actor_id=self.actor)
        older = studio.register_workers(self.conn, {k: v for k, v in self.configs.items() if k not in ("motion", "lookkey", "look", "swapkey", "swap", "layoutkey", "layout")}, self.actor)
        self.assertTrue(studio.seed_showcase_pipeline(self.conn, slug, older, self.actor))
        self.assertEqual(self.primaries(slug), {"keyframe", "cinema"})
        everyone = studio.register_workers(self.conn, self.configs, self.actor)
        # A marked seed from fewer workers is still an untouched seed: it is replaced, not given appended lanes.
        self.assertTrue(studio.seed_showcase_pipeline(self.conn, slug, everyone, self.actor))
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM projectops.audit_log WHERE project_slug=%s AND action LIKE 'studio_%%_lane_seed'", (slug,))
            self.assertEqual(cur.fetchone()[0], 0)
        full = self.pipeline(slug)
        self.assertEqual(self.primaries(slug), {"keyframe", "cinema"})
        self.assertTrue({"look", "swap", "layout"} <= {node["id"] for node in full["definition"]["nodes"]})
        self.assertFalse(studio.seed_showcase_pipeline(self.conn, slug, everyone, self.actor))
        # The showcase as seeded before the marker upgrades to the same graph.
        self.save(slug, local_workers.without_primary(full["definition"]))
        self.assertTrue(studio.seed_showcase_pipeline(self.conn, slug, everyone, self.actor))
        self.assertEqual(self.pipeline(slug)["definition"], full["definition"])
        # One the user rearranged keeps its steps as they are, default or not.
        moved = local_workers.without_primary(full["definition"])
        moved["nodes"][0]["x"] += 40
        self.save(slug, moved)
        self.assertFalse(studio.seed_showcase_pipeline(self.conn, slug, everyone, self.actor))
        self.assertNotIn(slug, local_workers.adopt_template_pipelines(self.conn, self.me, everyone))
        self.assertEqual(self.pipeline(slug)["definition"], moved)


if __name__ == "__main__":
    unittest.main()
