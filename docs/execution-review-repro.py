"""Regression checks for execution review; no inference/provider calls.

Run from the repository root against an isolated PostgreSQL database:
  $env:OPENBENCH_TEST_DB_URI='postgresql://postgres@127.0.0.1:55433/postgres'
  python docs/execution-review-repro.py -v

These assert corrected behavior. All three exposed failures in review baseline
4ea8fbeafbed4814273740370ccab8e666070786.
"""
import json
import os
from pathlib import Path
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests import test_execution as fixtures
from project_assistant import flow_runner, service, store
from project_docs import http, repository as repo
import server


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "isolated PostgreSQL URI required")
class ExecutionReviewRegressions(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.PostgreSQLExecutionTests()
        self.case.setUp()

    def tearDown(self):
        self.case.tearDown()

    def test_approval_cannot_write_after_cancel_commits(self):
        import psycopg
        c = self.case
        c.save({"nodes": [dict(fixtures.graph()["nodes"][0], target={"tab_key": "shots", "row_id": "b_shot1", "col_index": 1})], "edges": []})
        run = flow_runner.start(c.conn, c.me, c.slug, "flow", {})["run"]
        proposal = c.finish(c.claim(), "canceled output")["proposal_id"]
        c.conn.commit()
        read_pending, release, canceled = threading.Event(), threading.Event(), threading.Event()
        errors = []
        original = service._own_pending

        def paused_read(*args):
            result = original(*args)
            read_pending.set()
            if not release.wait(10):
                raise TimeoutError("approval barrier")
            return result

        def approve():
            try:
                with psycopg.connect(os.environ["OPENBENCH_TEST_DB_URI"]) as conn:
                    service.apply_proposal(conn, c.me, c.slug, proposal, {})
            except Exception as exc:
                errors.append(exc)

        def cancel():
            try:
                with psycopg.connect(os.environ["OPENBENCH_TEST_DB_URI"]) as conn:
                    flow_runner.control(conn, c.me, c.slug, "flow", run["id"], "cancel")
                canceled.set()
            except Exception as exc:
                errors.append(exc)

        with patch.object(service, "_own_pending", paused_read):
            approval = threading.Thread(target=approve)
            approval.start()
            self.assertTrue(read_pending.wait(5))
            cancellation = threading.Thread(target=cancel)
            cancellation.start()
            # Correct locking makes cancel wait until the approval transaction
            # finishes. The baseline instead commits cancel while approval is paused.
            cancel_won = canceled.wait(1)
            release.set()
            approval.join(10)
            cancellation.join(10)
        self.assertFalse(approval.is_alive() or cancellation.is_alive())
        self.assertFalse(errors, errors)
        self.assertTrue(canceled.is_set())
        if cancel_won:
            self.assertEqual(store.proposal(c.conn, proposal)["status"], "dismissed")
            self.assertNotIn("canceled output", str(repo.get_tab(c.conn, c.slug, "shots")["doc"]))

    def test_worker_can_fetch_project_media_with_worker_token(self):
        import psycopg
        c = self.case
        asset = repo.put_asset(c.conn, c.slug, data=b"fixture-media", content_type="image/png", actor_id=c.actor)
        c.conn.commit()
        srv = ThreadingHTTPServer(("127.0.0.1", 0), server.OpenBenchHandler)
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ, {"OPENBENCH_AUTH_MODE": "token", "OPENBENCH_TOKENS": json.dumps({"member-token-long-enough-123": c.actor})}), patch.object(http, "_CONN_FACTORY", lambda: psycopg.connect(os.environ["OPENBENCH_TEST_DB_URI"])):
                url = f"http://127.0.0.1:{srv.server_port}/projects/api/{c.slug}/assets/{asset}"
                request = urllib.request.Request(url, headers={"Authorization": "Bearer " + c.token})
                try:
                    with urllib.request.urlopen(request, timeout=5) as response:
                        status, data = response.status, response.read()
                except urllib.error.HTTPError as exc:
                    status, data = exc.code, exc.read()
                self.assertEqual(status, 200, data)
                self.assertEqual(data, b"fixture-media")

                def rejected(request_url, token, expected):
                    with self.assertRaises(urllib.error.HTTPError) as failure:
                        urllib.request.urlopen(urllib.request.Request(request_url, headers={"Authorization": "Bearer " + token}), timeout=5)
                    self.assertEqual(failure.exception.code, expected)

                rejected(url.replace(c.slug, "different-project"), c.token, 403)
                repo.update_project_meta(c.conn, c.slug, privacy_mode="mask_numbers")
                c.conn.commit()
                rejected(url, c.token, 403)
                with c.conn.cursor() as cur:
                    cur.execute("UPDATE projectops.agent_limb SET enabled=FALSE WHERE id=%s", (c.worker["id"],))
                c.conn.commit()
                rejected(url, c.token, 401)
                with patch.dict(os.environ, {"OPENBENCH_AUTH_MODE": "dev"}):
                    rejected(url, "not-a-valid-worker-token", 401)
        finally:
            srv.shutdown()
            srv.server_close()
            thread.join(2)

    def test_deleted_input_does_not_starve_later_healthy_run(self):
        c = self.case
        c.save({"nodes": [dict(fixtures.graph()["nodes"][0], input_tabs=["shots"])], "edges": []})
        broken = flow_runner.start(c.conn, c.me, c.slug, "flow", {})["run"]
        c.conn.commit()
        repo.set_tab_deleted(c.conn, c.slug, "shots", True)
        flow_runner.save_definition(c.conn, c.me, c.slug, "flow", {"definition": {"nodes": [fixtures.graph()["nodes"][0]], "edges": []}, "revision": 1})
        healthy = flow_runner.start(c.conn, c.me, c.slug, "flow", {})["run"]
        c.conn.commit()
        task = c.claim()
        self.assertIsNotNone(task)
        self.assertEqual(task["run_id"], healthy["id"])
        self.assertEqual(flow_runner.detail(c.conn, c.slug, "flow", broken["id"])["tasks"][0]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
