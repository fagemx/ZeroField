"""SPEC_20 R14: the launcher's media workers serve every production, and new productions get a bound pipeline.

Database tests never commit: committed local worker rows would bind the pipelines of productions other tests create.
"""
import contextlib
import copy
import io
import json
import os
import unittest
from unittest.mock import MagicMock, patch
import uuid

import run_studio as studio
from project_assistant import flow_runner, limbs, local_workers
from project_docs import repository as repo, service, templates


class LocalWorkerIdentityTests(unittest.TestCase):
    def test_ids_are_the_showcase_ids_and_cover_every_launcher_stage(self):
        self.assertEqual(set(local_workers.STAGES), set(studio.worker_configs("http://127.0.0.1:8188")) | {"anchor"})
        # The ids predate the server-wide scope, so pipelines bound to them keep working.
        self.assertEqual(local_workers.worker_id("cinema"),
                         str(uuid.uuid5(uuid.NAMESPACE_URL, "zerofield-studio:zerofield-showcase:cinema")))
        self.assertTrue(local_workers.is_local(local_workers.worker_id("split")))
        self.assertFalse(local_workers.is_local(str(uuid.uuid4())))
        with self.assertRaises(ValueError):
            local_workers.worker_id("anything")

    def test_an_unbound_step_does_not_count_a_local_worker_as_connected(self):
        local = {"id": local_workers.worker_id("cinema"), "capabilities": ["video_gen"]}
        remote = {"id": str(uuid.uuid4()), "capabilities": ["video_gen"]}
        step = {"id": "shot", "capability": "video_gen"}
        self.assertFalse(flow_runner._node_connected(None, "p", step, [local]))
        self.assertTrue(flow_runner._node_connected(None, "p", step, [remote]))
        self.assertTrue(flow_runner._node_connected(None, "p", dict(step, limb_id=local["id"]), [local]))
        self.assertFalse(flow_runner._node_connected(None, "p", dict(step, limb_id=local["id"]), [remote]))


class LauncherModeTests(unittest.TestCase):
    """Mode logic without a database; the SQL runs in LauncherDatabaseTests."""

    def launch(self, argv, cfg, registered=None):
        conn = MagicMock()
        with patch.dict(os.environ, {"OPENBENCH_DB_URI": "postgresql://launcher-test"}), \
                patch.object(studio.auth, "config", return_value=cfg), \
                patch.object(studio.server, "OpenBenchHTTPServer", return_value=MagicMock(server_port=3020)), \
                patch.object(studio.http, "open_connection", return_value=conn), \
                patch.object(studio.server, "seed_demo_data") as demo, \
                patch.object(studio, "seed_showcase_media"), patch.object(studio, "seed_showcase_previs"), \
                patch.object(studio.repo, "ensure_schema"), \
                patch.object(studio, "_launch_actor", return_value="00000000-0000-4000-8000-000000000001"), \
                patch.object(studio.local_workers, "register", return_value=registered or {}) as register, \
                patch.object(studio.local_workers, "existing", return_value={}), \
                patch.object(studio.local_workers, "adopt_template_pipelines") as adopt, \
                patch.object(studio, "seed_showcase_pipeline") as showcase, \
                patch.object(studio.assistant_worker, "start_in_background") as agent, \
                patch.object(studio, "start_media_workers", return_value=[]) as media, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(studio.main(argv), 0)
        return {"conn": conn, "demo": demo, "register": register, "adopt": adopt, "showcase": showcase, "agent": agent, "media": media}

    def test_no_worker_registers_nothing_in_either_mode(self):
        for cfg in ({"mode": "dev"}, {"mode": "header", "tokens": {}}):
            with self.subTest(mode=cfg["mode"]):
                calls = self.launch(["--no-worker"], cfg)
                for name in ("register", "adopt", "showcase", "agent", "media"):
                    calls[name].assert_not_called()

    def test_header_mode_registers_the_same_local_workers_without_demo_data(self):
        registered = {"cinema": {"id": local_workers.worker_id("cinema"), "token": "t", "capabilities": {}}}
        calls = self.launch([], {"mode": "header", "tokens": {}}, registered)
        conn, configs, actor = calls["register"].call_args.args
        self.assertIs(conn, calls["conn"])
        self.assertEqual(set(configs), set(studio.worker_configs("http://127.0.0.1:8188")))
        self.assertEqual(actor, "00000000-0000-4000-8000-000000000001")
        calls["demo"].assert_not_called()
        calls["showcase"].assert_not_called()
        calls["adopt"].assert_called_once()
        self.assertIs(calls["media"].call_args.args[1], registered)


class _HeldConnection:
    """The launcher's connection inside the test transaction: commit and close do nothing, tearDown rolls back."""

    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def commit(self):
        pass

    def close(self):
        pass


class _DatabaseCase(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.conn = psycopg.connect(os.environ["OPENBENCH_TEST_DB_URI"])
        repo.ensure_schema(self.conn)
        self.conn.commit()
        self.actor = str(uuid.uuid4())
        self.me = service.Identity(self.actor, "Local worker test", "admin")
        repo.upsert_member(self.conn, self.actor, "Local worker test", "admin")
        self.configs = studio.worker_configs("http://127.0.0.1:8188")

    def tearDown(self):
        self.conn.rollback()
        self.conn.close()

    def create(self, prefix="lw"):
        slug = f"{prefix}-{uuid.uuid4().hex[:12]}"
        code, result = service.create_project(self.conn, self.me, {"slug": slug, "title": "Local workers", "template": "zerofield_studio"})
        self.assertEqual(code, 200, result)
        return slug

    def local_rows(self):
        with self.conn.cursor() as cur:
            cur.execute("""SELECT id::text,allowed_projects,token_hash,enabled,capabilities FROM projectops.agent_limb
                           WHERE id=ANY(%s::uuid[]) ORDER BY id""", (list(local_workers.IDS),))
            return {row[0]: row[1:] for row in cur.fetchall()}

    def all_slugs(self):
        with self.conn.cursor() as cur:
            cur.execute("SELECT slug FROM projectops.project ORDER BY slug")
            return [row[0] for row in cur.fetchall()]

    def pipeline(self, slug):
        return flow_runner.definition(self.conn, slug, "comfy-pipeline")

    def connect(self, registered):
        return {stage: limbs.authenticate(self.conn, item["token"]) for stage, item in registered.items()}

    def queue_single_step(self, slug, node_id, revision):
        row = flow_runner._source_rows(self.conn, slug, {"tab_key": "cinema-studio"})[0]["row_id"]
        request = {"execution_mode": "single_step", "node_id": node_id, "input_mode": "current_sources",
                   "sample_row_id": row, "definition_revision": revision}
        preview = flow_runner.preflight(self.conn, self.me, slug, "comfy-pipeline", request)
        self.assertTrue(preview["ready"], preview)
        flow_runner.start(self.conn, self.me, slug, "comfy-pipeline", dict(request, source_revisions=preview["source_revisions"]))
        return row


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "set OPENBENCH_TEST_DB_URI")
class LocalWorkerDatabaseTests(_DatabaseCase):
    def test_a_new_production_joins_the_local_workers_and_gets_a_bound_pipeline(self):
        registered = studio.register_workers(self.conn, self.configs, self.actor)
        slug = self.create()
        rows = self.local_rows()
        self.assertEqual(set(rows), {item["id"] for item in registered.values()})
        for projects, *_ in rows.values():
            self.assertEqual(projects, self.all_slugs())
        graph = self.pipeline(slug)["definition"]
        nodes = {n["id"]: n for n in graph["nodes"]}
        # The showcase lanes the template's own columns support; no OpenJutsu preparation, Object Swap or script step.
        self.assertEqual(set(nodes), {"image", "keyframe", "cinema", "assemble", "v2v", "split", "motion", "lookkey",
                                      "look", "layoutkey", "layout"})
        for node_id, node in nodes.items():
            self.assertEqual(node["limb_id"], registered["image" if node_id == "keyframe" else node_id]["id"])
            self.assertEqual(node["write_mode"], "proposal")
        self.assertEqual([nodes[k]["target"]["col_index"] for k in ("image", "keyframe", "cinema", "v2v", "split", "motion", "lookkey", "look", "layoutkey", "layout")],
                         [3, 4, 5, 4, 5, 5, 4, 5, 4, 5])
        self.assertEqual(nodes["assemble"]["target"], {"tab_key": "director-brief", "kind": "doc", "mode": "append"})
        self.assertCountEqual(graph["edges"], [{"source": a, "target": b} for a, b in (
            ("keyframe", "cinema"), ("cinema", "assemble"), ("v2v", "split"), ("motion", "lookkey"), ("lookkey", "look"), ("layoutkey", "layout"))])
        # Once the launcher's workers poll, a lane passes preflight and only its own worker takes the step.
        workers = self.connect(registered)
        preview = flow_runner.preflight(self.conn, self.me, slug, "comfy-pipeline", {"start_node_id": "keyframe"})
        self.assertEqual(preview["errors"], [], preview)
        row = self.queue_single_step(slug, "motion", self.pipeline(slug)["revision"])
        for stage in ("cinema", "look", "layout"):
            self.assertIsNone(flow_runner.claim(self.conn, workers[stage])["task"])
        task = flow_runner.claim(self.conn, workers["motion"])["task"]
        self.assertEqual((task["node_id"], task["row_id"], task["limb_id"]), ("motion", row, registered["motion"]["id"]))

    def test_without_local_workers_a_production_keeps_the_unbound_template_pipeline(self):
        with self.conn.cursor() as cur:  # whatever this database holds, none of it is usable during this test
            cur.execute("UPDATE projectops.agent_limb SET enabled=FALSE WHERE id=ANY(%s::uuid[])", (list(local_workers.IDS),))
        slug = self.create()
        self.assertEqual(self.pipeline(slug)["definition"],
                         flow_runner.validate_definition(templates.flow_specs("zerofield_studio")["comfy-pipeline"]))

    def test_a_showcase_pipeline_bound_before_the_upgrade_keeps_claiming_work(self):
        slug = self.create("showcase")
        studio.seed_showcase_media(self.conn, slug, actor_id=self.actor)
        old = {}
        for stage, capabilities in self.configs.items():  # the previous launcher: the same ids, scoped to the showcase only
            identifier = str(uuid.uuid5(uuid.NAMESPACE_URL, f"zerofield-studio:zerofield-showcase:{stage}"))
            with self.conn.cursor() as cur:
                cur.execute("""INSERT INTO projectops.agent_limb(id,name,capabilities,allowed_projects,token_hash,created_by)
                    VALUES(%s,%s,%s::jsonb,%s::jsonb,%s,%s) ON CONFLICT(id) DO UPDATE SET allowed_projects=EXCLUDED.allowed_projects,
                    capabilities=EXCLUDED.capabilities,token_hash=EXCLUDED.token_hash,enabled=TRUE""",
                            (identifier, "ZeroField Studio / " + stage, json.dumps(list(capabilities)), json.dumps([slug]),
                             limbs.token_hash(uuid.uuid4().hex), self.actor))
            old[stage] = {"id": identifier}
        self.assertTrue(studio.seed_showcase_pipeline(self.conn, slug, old, self.actor))
        before = self.pipeline(slug)
        # The upgraded launcher keeps the rows, widens their scope to every production and rotates their tokens.
        registered = studio.register_workers(self.conn, self.configs, self.actor)
        self.assertEqual({k: v["id"] for k, v in registered.items()}, {k: v["id"] for k, v in old.items()})
        self.assertEqual(self.local_rows()[registered["cinema"]["id"]][0], self.all_slugs())
        self.assertFalse(studio.seed_showcase_pipeline(self.conn, slug, registered, self.actor))
        self.assertNotIn(slug, local_workers.adopt_template_pipelines(self.conn, self.me, registered))
        self.assertEqual(self.pipeline(slug), before)
        workers = self.connect(registered)
        row = self.queue_single_step(slug, "cinema", before["revision"])
        self.assertIsNone(flow_runner.claim(self.conn, workers["motion"])["task"])
        task = flow_runner.claim(self.conn, workers["cinema"])["task"]
        self.assertEqual((task["node_id"], task["row_id"], task["limb_id"]), ("cinema", row, registered["cinema"]["id"]))

    def test_a_worker_cannot_claim_or_be_bound_outside_its_scope(self):
        registered = studio.register_workers(self.conn, self.configs, self.actor)
        slug = self.create()
        workers = self.connect(registered)
        self.queue_single_step(slug, "cinema", self.pipeline(slug)["revision"])
        cinema = registered["cinema"]["id"]
        with self.conn.cursor() as cur:  # the production leaves the cinema worker's scope
            cur.execute("UPDATE projectops.agent_limb SET allowed_projects=allowed_projects-%s::text WHERE id=%s", (slug, cinema))
        outsider = limbs.authenticate(self.conn, registered["cinema"]["token"])
        self.assertIsNone(flow_runner.claim(self.conn, outsider)["task"])
        task = flow_runner.claim(self.conn, workers["cinema"])["task"]  # the stale in-memory scope still listed it
        self.assertIsNotNone(task)
        with self.assertRaises(limbs.ExecutionError) as denied:
            flow_runner.renew(self.conn, outsider, {"task_id": task["id"], "lease_token": task["lease_token"]})
        self.assertEqual(denied.exception.status, 403)
        # A production that bypassed create_project is outside the scope until the next launch: no binding there.
        other = f"lw-out-{uuid.uuid4().hex[:8]}"
        repo.upsert_project(self.conn, other, "Created without create_project")
        repo.create_tab(self.conn, other, key="flow", title="Flow", parent_key=None, doc={"type": "doc", "content": []},
                        actor_id=self.actor, surface_type="flow")
        with self.assertRaises(limbs.ExecutionError) as unbound:
            flow_runner.save_definition(self.conn, self.me, other, "flow", {"revision": 0, "definition": {
                "nodes": [{"id": "shot", "capability": "video_gen", "scope": "once", "limb_id": cinema}], "edges": []}})
        self.assertEqual(unbound.exception.status, 400)

    def test_local_workers_leave_unbound_steps_to_a_worker_the_production_chose(self):
        registered = studio.register_workers(self.conn, self.configs, self.actor)
        slug = self.create()
        workers = self.connect(registered)
        current = self.pipeline(slug)
        unbound = {"id": "shot", "title": "Unbound shot", "capability": "video_gen", "scope": "rows", "input_tabs": ["cinema-studio"],
                   "row_source": {"tab_key": "cinema-studio"}, "target": {"tab_key": "cinema-studio", "col_index": 5}}
        saved = flow_runner.save_definition(self.conn, self.me, slug, "comfy-pipeline",
                                            {"revision": current["revision"], "definition": {"nodes": [unbound], "edges": []}})
        row = flow_runner._source_rows(self.conn, slug, {"tab_key": "cinema-studio"})[0]["row_id"]
        request = {"execution_mode": "single_step", "node_id": "shot", "input_mode": "current_sources",
                   "sample_row_id": row, "definition_revision": saved["revision"]}
        preview = flow_runner.preflight(self.conn, self.me, slug, "comfy-pipeline", request)
        self.assertFalse(preview["ready"])  # local workers alone do not serve an unbound step
        issued = limbs.register(self.conn, self.me, {"name": "Chosen remote", "capabilities": ["video_gen"], "project_slug": slug})
        remote = limbs.authenticate(self.conn, issued["token"])
        self.assertEqual(remote["allowed_projects"], [slug])
        preview = flow_runner.preflight(self.conn, self.me, slug, "comfy-pipeline", request)
        self.assertTrue(preview["ready"], preview)
        flow_runner.start(self.conn, self.me, slug, "comfy-pipeline", dict(request, source_revisions=preview["source_revisions"]))
        for worker in workers.values():
            self.assertIsNone(flow_runner.claim(self.conn, worker)["task"])
        self.assertEqual(flow_runner.claim(self.conn, remote)["task"]["node_id"], "shot")


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "set OPENBENCH_TEST_DB_URI")
class LauncherDatabaseTests(_DatabaseCase):
    """run_studio.main against the real schema, inside one rolled-back transaction."""

    def launch(self, argv, cfg):
        with patch.dict(os.environ, {"OPENBENCH_DB_URI": os.environ["OPENBENCH_TEST_DB_URI"]}), \
                patch.object(studio.auth, "config", return_value=cfg), \
                patch.object(studio.server, "OpenBenchHTTPServer", return_value=MagicMock(server_port=3020)), \
                patch.object(studio.http, "open_connection", return_value=_HeldConnection(self.conn)), \
                patch.object(studio.assistant_worker, "start_in_background") as agent, \
                patch.object(studio, "start_media_workers", return_value=[]) as media, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(studio.main(argv), 0)
        return agent, media

    def assert_serving_every_production(self, media):
        registered = media.call_args.args[1]
        self.assertEqual(set(registered), set(self.configs))
        rows = self.local_rows()
        self.assertEqual(set(rows), {item["id"] for item in registered.values()})
        for projects, token_hash, enabled, _ in rows.values():
            self.assertTrue(enabled)
            self.assertEqual(projects, self.all_slugs())
        self.assertEqual({rows[item["id"]][1] for item in registered.values()}, {limbs.token_hash(item["token"]) for item in registered.values()})
        return registered

    def test_development_launch_scopes_workers_to_every_production_and_binds_untouched_pipelines(self):
        with self.conn.cursor() as cur:
            cur.execute("UPDATE projectops.agent_limb SET enabled=FALSE WHERE id=ANY(%s::uuid[])", (list(local_workers.IDS),))
        untouched, edited = self.create(), self.create()
        current = self.pipeline(edited)
        moved = copy.deepcopy(current["definition"]); moved["nodes"][0]["x"] += 25
        flow_runner.save_definition(self.conn, self.me, edited, "comfy-pipeline", {"revision": current["revision"], "definition": moved})
        agent, media = self.launch([], {"mode": "dev"})
        agent.assert_called_once()
        registered = self.assert_serving_every_production(media)
        local_ids = {item["id"] for item in registered.values()}
        showcase = self.pipeline(studio.SHOWCASE_SLUG)["definition"]["nodes"]
        self.assertTrue({"extract", "structure", "layout"} <= {node["id"] for node in showcase})
        self.assertTrue(all(node["limb_id"] in local_ids for node in showcase))
        self.assertTrue(all(node["limb_id"] in local_ids for node in self.pipeline(untouched)["definition"]["nodes"]))
        self.assertEqual(self.pipeline(edited)["definition"], moved)

    def test_header_launch_registers_the_local_workers_without_demo_accounts(self):
        before = set(m["actor_id"] for m in repo.active_members(self.conn))
        agent, media = self.launch([], {"mode": "header", "tokens": {}, "proxy_secret": "x" * 24})
        agent.assert_called_once()
        self.assert_serving_every_production(media)
        self.assertEqual(set(m["actor_id"] for m in repo.active_members(self.conn)), before)

    def test_no_worker_launch_leaves_worker_rows_untouched(self):
        studio.register_workers(self.conn, self.configs, self.actor)
        self.create()  # its slug is now in every local worker's scope
        before = self.local_rows()
        agent, media = self.launch(["--no-worker"], {"mode": "header", "tokens": {}, "proxy_secret": "x" * 24})
        agent.assert_not_called()
        media.assert_not_called()
        self.assertEqual(self.local_rows(), before)
        # Development mode: no registration or token rotation; only a showcase the launch creates joins the scope.
        showcase_existed = bool(repo.get_project(self.conn, studio.SHOWCASE_SLUG))
        agent, media = self.launch(["--no-worker"], {"mode": "dev"})
        agent.assert_not_called()
        media.assert_not_called()
        after = self.local_rows()
        self.assertEqual({k: v[1:] for k, v in after.items()}, {k: v[1:] for k, v in before.items()})
        for identifier, (projects, *_) in after.items():
            self.assertEqual(set(projects) - set(before[identifier][0]), set() if showcase_existed else {studio.SHOWCASE_SLUG})
        if not showcase_existed:  # created with the default pipeline, then upgraded to the full showcase seed
            nodes = {n["id"]: n["limb_id"] for n in self.pipeline(studio.SHOWCASE_SLUG)["definition"]["nodes"]}
            self.assertTrue({"extract", "structure", "swapkey"} <= set(nodes))
            self.assertTrue(all(local_workers.is_local(limb) for limb in nodes.values()))


if __name__ == "__main__":
    unittest.main()
