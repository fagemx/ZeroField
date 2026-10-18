"""Execution protocol tests; PostgreSQL tests opt in with OPENBENCH_TEST_DB_URI."""
import datetime as dt
import os
import unittest
import uuid

from project_assistant import flow_runner, limbs


def graph():
    return {"nodes": [{"id": n, "title": n, "capability": "llm"} for n in "abcd"],
            "edges": [{"source": s, "target": t} for s, t in [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")]]}


class GraphTests(unittest.TestCase):
    def test_fork_and_join_requires_every_predecessor(self):
        definition = flow_runner.validate_definition(graph())
        self.assertEqual(flow_runner.ready_nodes(definition, {}), ["a"])
        self.assertEqual(flow_runner.ready_nodes(definition, {"a": "succeeded"}), ["b", "c"])
        self.assertNotIn("d", flow_runner.ready_nodes(definition, {"a": "succeeded", "b": "succeeded", "c": "awaiting_approval"}))
        self.assertEqual(flow_runner.ready_nodes(definition, {"a": "succeeded", "b": "succeeded", "c": "succeeded"}), ["d"])

    def test_cycle_missing_reference_duplicate_and_unsupported_rejected(self):
        for change in ("cycle", "missing", "duplicate", "capability"):
            value = graph()
            if change == "cycle": value["edges"].append({"source": "d", "target": "a"})
            if change == "missing": value["edges"][0]["target"] = "absent"
            if change == "duplicate": value["nodes"].append(value["nodes"][0])
            if change == "capability": value["nodes"][0]["capability"] = "shell"
            with self.subTest(change=change), self.assertRaises(ValueError):
                flow_runner.validate_definition(value)

    def test_default_output_requires_review(self):
        self.assertEqual(flow_runner.validate_definition(graph())["nodes"][0]["write_mode"], "proposal")


class LeaseTests(unittest.TestCase):
    def test_rejects_wrong_worker_wrong_lease_and_expired_lease(self):
        now = dt.datetime.now(dt.timezone.utc)
        task = {"status": "running", "limb_id": "worker-a", "lease_hash": limbs.token_hash("lease"), "lease_until": now + dt.timedelta(seconds=60)}
        limbs.check_lease(task, "worker-a", "lease", now)
        for worker, token, at in [("worker-b", "lease", now), ("worker-a", "wrong", now), ("worker-a", "lease", now + dt.timedelta(seconds=61))]:
            with self.subTest(worker=worker, token=token), self.assertRaises(limbs.ExecutionError):
                limbs.check_lease(task, worker, token, at)


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "set OPENBENCH_TEST_DB_URI for PostgreSQL execution tests")
class PostgreSQLExecutionTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from project_docs import repository as repo, service
        self.conn = psycopg.connect(os.environ["OPENBENCH_TEST_DB_URI"])
        repo.ensure_schema(self.conn)
        self.conn.commit()
        self.slug = "exec-test-" + uuid.uuid4().hex[:12]
        self.actor = str(uuid.uuid4())
        self.me = service.Identity(self.actor, "Execution test", "admin")
        repo.upsert_member(self.conn, self.actor, "Execution test", "admin")
        repo.upsert_project(self.conn, self.slug, "Execution test")
        def cell(text, header=False):
            return {"type": "tableHeader" if header else "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}
        self.doc = {"type": "doc", "content": [{"type": "table", "attrs": {"bid": "b_table"}, "content": [
            {"type": "tableRow", "attrs": {"bid": "b_header"}, "content": [cell("Shot", True), cell("Output", True)]},
            {"type": "tableRow", "attrs": {"bid": "b_shot1"}, "content": [cell("Shot 1"), cell("original")]},
            {"type": "tableRow", "attrs": {"bid": "b_shot2"}, "content": [cell("Shot 2"), cell("original")]}]}]}
        repo.create_tab(self.conn, self.slug, key="shots", title="Shots", parent_key=None, doc=self.doc, actor_id=self.actor, surface_type="sheet")
        repo.create_tab(self.conn, self.slug, key="flow", title="Flow", parent_key=None, doc={"type": "doc", "content": []}, actor_id=self.actor, surface_type="flow")
        issued = limbs.register(self.conn, self.me, {"name": "Test worker", "capabilities": ["llm"], "project_slug": self.slug})
        self.token = issued["token"]
        self.worker = limbs.authenticate(self.conn, issued["token"])

    def tearDown(self):
        self.conn.rollback()
        # One persistence test deliberately commits. Remove only its unique project.
        from psycopg import sql
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM projectops.limb_task WHERE project_slug=%s", (self.slug,))
            cur.execute("DELETE FROM projectops.flow_run WHERE project_slug=%s", (self.slug,))
            cur.execute("DELETE FROM projectops.flow_definition WHERE project_slug=%s", (self.slug,))
            cur.execute("SELECT table_name FROM information_schema.columns WHERE table_schema='projectops' AND column_name='project_slug'")
            tables = [r[0] for r in cur.fetchall() if r[0] not in ("limb_task", "flow_run", "flow_definition")]
            for name in tables:
                cur.execute(sql.SQL("DELETE FROM projectops.{} WHERE project_slug=%s").format(sql.Identifier(name)), (self.slug,))
            cur.execute("DELETE FROM projectops.agent_limb WHERE created_by=%s", (self.actor,))
            cur.execute("DELETE FROM projectops.project WHERE slug=%s", (self.slug,))
            cur.execute("DELETE FROM projectops.member WHERE actor_id=%s", (self.actor,))
        self.conn.commit()
        self.conn.close()

    def save(self, value):
        return flow_runner.save_definition(self.conn, self.me, self.slug, "flow", {"definition": value, "revision": 0})

    def claim(self):
        return flow_runner.claim(self.conn, self.worker)["task"]

    def finish(self, task, output="done"):
        return flow_runner.complete(self.conn, self.worker, {"task_id": task["id"], "lease_token": task["lease_token"], "output": {"text": output}})

    def test_fan_out_join_real_queue_and_predecessor_inputs(self):
        self.save(graph())
        run = flow_runner.start(self.conn, self.me, self.slug, "flow", {})["run"]
        a = self.claim()
        self.assertEqual(a["node_id"], "a")
        self.finish(a, "draft")
        b, c = self.claim(), self.claim()
        self.assertEqual({b["node_id"], c["node_id"]}, {"b", "c"})
        self.assertEqual(b["input"]["predecessors"]["a"]["text"], "draft")
        self.finish(b)
        self.assertIsNone(self.claim())
        self.finish(c)
        d = self.claim()
        self.assertEqual(d["node_id"], "d")
        self.finish(d)
        self.assertEqual(flow_runner.detail(self.conn, self.slug, "flow", run["id"])["run"]["status"], "succeeded")

    def test_result_proposal_blocks_downstream_until_approved(self):
        from project_assistant import store, table_edits
        from project_docs import repository as repo
        value = graph()
        value["nodes"][0]["target"] = {"tab_key": "shots", "row_id": "b_shot1", "col_index": 1}
        self.save(value)
        flow_runner.start(self.conn, self.me, self.slug, "flow", {})
        a = self.claim()
        completed = self.finish(a, "approved prompt")
        self.assertEqual(completed["status"], "awaiting_approval")
        self.assertIsNone(self.claim())
        proposal = store.proposal(self.conn, completed["proposal_id"])
        status, _ = table_edits.apply(self.conn, self.me, self.slug, proposal["target"])
        self.assertEqual(status, 200)
        store.decide_proposal(self.conn, completed["proposal_id"], status="applied", by=self.actor)
        flow_runner.proposal_decided(self.conn, completed["proposal_id"], True)
        self.assertIn(self.claim()["node_id"], ("b", "c"))
        self.assertIn("approved prompt", str(repo.get_tab(self.conn, self.slug, "shots")["doc"]))

    def test_expired_lease_reclaimed_and_stale_completion_rejected(self):
        self.save(graph())
        flow_runner.start(self.conn, self.me, self.slug, "flow", {})
        old = self.claim()
        with self.conn.cursor() as cur:
            cur.execute("UPDATE projectops.limb_task SET lease_until=NOW()-INTERVAL '1 second' WHERE id=%s", (old["id"],))
        replacement = self.claim()
        self.assertEqual(old["id"], replacement["id"])
        self.assertNotEqual(old["lease_token"], replacement["lease_token"])
        with self.assertRaises(limbs.ExecutionError):
            self.finish(old)
        self.finish(replacement)

    def test_unauthorized_worker_cannot_complete(self):
        self.save(graph())
        flow_runner.start(self.conn, self.me, self.slug, "flow", {})
        task = self.claim()
        other = dict(self.worker, id=str(uuid.uuid4()))
        with self.assertRaises(limbs.ExecutionError):
            flow_runner.complete(self.conn, other, {"task_id": task["id"], "lease_token": task["lease_token"], "output": {"text": "stolen"}})

    def test_direct_result_rejects_edited_row(self):
        from project_docs import repository as repo
        import copy
        value = {"nodes": [dict(graph()["nodes"][0], write_mode="direct", target={"tab_key": "shots", "row_id": "b_shot1", "col_index": 1})], "edges": []}
        self.save(value)
        flow_runner.start(self.conn, self.me, self.slug, "flow", {})
        task = self.claim()
        changed = copy.deepcopy(self.doc)
        changed["content"][0]["content"][1]["content"][1]["content"][0]["content"][0]["text"] = "human change"
        repo.save_tab_doc(self.conn, self.slug, "shots", doc=changed, title="Shots", actor_id=self.actor, session_id="human", base_revision=1)
        with self.assertRaises(limbs.ExecutionError) as error:
            self.finish(task, "late overwrite")
        self.assertEqual(error.exception.status, 409)

    def test_selected_rows_are_separate_tasks_and_cancel_invalidates_lease(self):
        value = {"nodes": [dict(graph()["nodes"][0], input_tabs=["shots"], target={"tab_key": "shots", "col_index": 1})], "edges": []}
        self.save(value)
        run = flow_runner.start(self.conn, self.me, self.slug, "flow", {"row_ids": ["b_shot1", "b_shot2"], "target_tab": "shots"})
        self.assertEqual(len(run["tasks"]), 2)
        task = self.claim()
        self.assertEqual(task["target"]["row_id"], task["row_id"])
        text = task["input"]["tabs"][0]["text"]
        self.assertFalse("Shot 1" in text and "Shot 2" in text)
        flow_runner.control(self.conn, self.me, self.slug, "flow", run["run"]["id"], "cancel")
        with self.assertRaises(limbs.ExecutionError):
            self.finish(task)
        retried = flow_runner.control(self.conn, self.me, self.slug, "flow", run["run"]["id"], "retry")
        self.assertEqual(retried["run"]["status"], "running")
        self.assertIsNotNone(self.claim())

    def test_persists_across_connections_and_stale_graph_revision_rejected(self):
        import psycopg
        self.save(graph())
        run = flow_runner.start(self.conn, self.me, self.slug, "flow", {})
        self.conn.commit()
        with psycopg.connect(os.environ["OPENBENCH_TEST_DB_URI"]) as other:
            result = flow_runner.detail(other, self.slug, "flow", run["run"]["id"])
            self.assertEqual(len(result["tasks"]), 4)
            with self.assertRaises(limbs.ExecutionError):
                flow_runner.save_definition(other, self.me, self.slug, "flow", {"definition": graph(), "revision": 0})

    def test_http_claim_media_upload_complete_and_row_progress(self):
        import io
        import json
        import threading
        import urllib.request
        import urllib.error
        from urllib.parse import urlparse, urlencode
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from unittest.mock import patch
        from project_docs import http, runtime_http
        import psycopg
        value = {"nodes": [dict(graph()["nodes"][0], target={"tab_key": "shots", "row_id": "b_shot1", "col_index": 1})], "edges": []}
        self.save(value)
        flow_runner.start(self.conn, self.me, self.slug, "flow", {})
        self.conn.commit()
        actor = self.actor

        class Handler(BaseHTTPRequestHandler):
            def project_docs_identity(self):
                return {"actor_id": actor, "name": "Execution test", "role": "admin", "status": "active", "directory_registered": True}, None
            def send_json(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def read_json_body(self):
                return json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            def do_POST(self):
                runtime_http.handle(self, urlparse(self.path), "POST")
            def do_GET(self):
                runtime_http.handle(self, urlparse(self.path), "GET")
            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"

        def request(path, payload=None, raw=None, token=None, method="POST"):
            headers = {"Content-Type": "image/png" if raw else "application/json", "Authorization": "Bearer " + (token or self.token)}
            data = raw if raw is not None else json.dumps(payload or {}).encode() if method == "POST" else None
            req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=10) as response:
                    return response.status, json.load(response)
            except urllib.error.HTTPError as exc:
                return exc.code, json.load(exc)

        factory = lambda: psycopg.connect(os.environ["OPENBENCH_TEST_DB_URI"])
        try:
            with patch.object(http, "_CONN_FACTORY", factory):
                self.assertEqual(request("/projects/api/limbs/claim", token="invalid")[0], 401)
                code, claimed = request("/projects/api/limbs/claim")
                self.assertEqual(code, 200)
                task = claimed["task"]
                lease = {"task_id": task["id"], "lease_token": task["lease_token"]}
                self.assertEqual(request("/projects/api/limbs/renew", lease)[0], 200)
                from PIL import Image
                stream = io.BytesIO()
                Image.new("RGB", (2, 2), "blue").save(stream, "PNG")
                png = stream.getvalue()
                code, uploaded = request("/projects/api/limbs/upload-cell-asset?" + urlencode(lease), raw=png)
                self.assertEqual(code, 200, uploaded)
                code, done = request("/projects/api/limbs/complete", dict(lease, output={"asset_url": uploaded["asset_url"]}))
                self.assertEqual(code, 200, done)
                self.assertEqual(done["status"], "awaiting_approval")
                code, progress = request(f"/projects/api/{self.slug}/tasks?target_tab=shots", method="GET")
                self.assertEqual(code, 200, progress)
                self.assertEqual(progress["tasks"][0]["status"], "awaiting_approval")
                self.assertNotIn("lease_hash", progress["tasks"][0])
                self.assertEqual(request("/projects/api/limbs/complete", dict(lease, output={"text": "replay"}))[0], 409)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_current_privacy_masks_numbers_but_preserves_asset_protocol_ids(self):
        from project_docs import repository as repo
        value = graph()
        value["nodes"][0]["prompt"] = "Budget 12000"
        self.save(value)
        flow_runner.start(self.conn, self.me, self.slug, "flow", {})
        repo.update_project_meta(self.conn, self.slug, privacy_mode="mask_numbers")
        task = self.claim()
        self.assertNotIn("12000", task["input"]["prompt"])
        asset = repo.put_asset(self.conn, self.slug, data=b"asset-bytes", content_type="image/png", actor_id=self.actor)
        url = f"/projects/api/{self.slug}/assets/{asset}"
        flow_runner.complete(self.conn, self.worker, {"task_id": task["id"], "lease_token": task["lease_token"], "output": {"asset_url": url, "amount": 12000}})
        downstream = self.claim()
        self.assertEqual(downstream["input"]["predecessors"]["a"]["asset_url"], url)
        self.assertNotEqual(downstream["input"]["predecessors"]["a"]["amount"], 12000)

    def test_retry_limit_failure_and_creator_revocation(self):
        from project_docs import repository as repo
        self.save(graph())
        run = flow_runner.start(self.conn, self.me, self.slug, "flow", {})["run"]
        for attempt in range(1, 4):
            task = self.claim()
            self.assertEqual(task["attempts"], attempt)
            result = flow_runner.fail(self.conn, self.worker, {"task_id": task["id"], "lease_token": task["lease_token"], "error": "provider unavailable"})
            self.assertEqual(result["status"], "failed" if attempt == 3 else "queued")
        self.assertEqual(flow_runner.detail(self.conn, self.slug, "flow", run["id"])["run"]["status"], "failed")
        flow_runner.control(self.conn, self.me, self.slug, "flow", run["id"], "retry")
        repo.upsert_member(self.conn, self.actor, "Execution test", "viewer")
        self.assertIsNone(self.claim())
        self.assertEqual(flow_runner.detail(self.conn, self.slug, "flow", run["id"])["run"]["status"], "failed")

    def test_worker_project_scope_and_row_target_validation(self):
        self.save(graph())
        flow_runner.start(self.conn, self.me, self.slug, "flow", {})
        task = self.claim()
        scoped = dict(self.worker, allowed_projects=["some-other-project"])
        with self.assertRaises(limbs.ExecutionError) as error:
            flow_runner.complete(self.conn, scoped, {"task_id": task["id"], "lease_token": task["lease_token"], "output": {"text": "no"}})
        self.assertEqual(error.exception.status, 403)
        value = graph()
        value["nodes"][0]["target"] = {"tab_key": "shots", "row_id": "b_absent", "col_index": 1}
        flow_runner.save_definition(self.conn, self.me, self.slug, "flow", {"definition": value, "revision": 1})
        with self.assertRaises(limbs.ExecutionError) as error:
            flow_runner.start(self.conn, self.me, self.slug, "flow", {})
        self.assertEqual(error.exception.status, 400)

    def test_offline_worker_returns_actionable_error(self):
        self.save(graph())
        with self.conn.cursor() as cur:
            cur.execute("UPDATE projectops.agent_limb SET last_seen_at=NOW()-INTERVAL '6 minutes' WHERE id=%s", (self.worker["id"],))
        with self.assertRaises(limbs.ExecutionError) as error:
            flow_runner.start(self.conn, self.me, self.slug, "flow", {})
        self.assertEqual(error.exception.status, 409)
        self.assertIn("worker", str(error.exception).lower())


if __name__ == "__main__":
    unittest.main()
