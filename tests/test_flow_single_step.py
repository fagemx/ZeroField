"""Exact-step execution contract, using a real PostgreSQL queue and fixture worker."""
import copy
import os
import unittest

import test_execution as legacy
from project_assistant import flow_runner, service as assistant_service
from project_docs import repository as repo, service


class FlowAdapterContractTests(unittest.TestCase):
    def test_definition_retains_metadata_and_coordinates(self):
        graph = legacy.graph()
        graph["viewport"] = {"zoom": 0.8}
        graph["nodes"][0].update({"x": -30, "y": 42, "adapter_options": {"model": "fixture"}})
        graph["edges"][0]["mapping"] = {"custom": True}
        actual = flow_runner.validate_definition(graph)
        self.assertEqual(actual["viewport"], graph["viewport"])
        self.assertEqual(actual["nodes"][0]["adapter_options"], {"model": "fixture"})
        self.assertEqual(actual["nodes"][0]["x"], -30)
        self.assertEqual(actual["edges"][0]["mapping"], {"custom": True})

    def test_empty_draft_can_be_saved_but_not_executed(self):
        self.assertEqual(flow_runner.validate_definition({"nodes": [], "edges": [], "viewport": {"zoom": 1}}, allow_empty=True)["nodes"], [])
        with self.assertRaises(ValueError):
            flow_runner.validate_definition({"nodes": [], "edges": []})

    def test_headerless_source_does_not_drop_first_row(self):
        table = {"type": "table", "attrs": {"bid": "table"}, "content": [
            {"type": "tableRow", "attrs": {"bid": "r1"}, "content": [{"type": "tableCell", "content": [{"type": "text", "text": "first"}]}]},
            {"type": "tableRow", "attrs": {"bid": "r2"}, "content": [{"type": "tableCell", "content": [{"type": "text", "text": "second"}]}]},
        ]}
        actual = flow_runner._table_data({"content": [table]}, {})[0]
        self.assertEqual([row["row_id"] for row in actual["rows"]], ["r1", "r2"])
        self.assertEqual(actual["headers"], ["欄 1"])


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "set OPENBENCH_TEST_DB_URI")
class SingleStepTests(unittest.TestCase):
    setUp = legacy.PostgreSQLExecutionTests.setUp
    tearDown = legacy.PostgreSQLExecutionTests.tearDown
    save = legacy.PostgreSQLExecutionTests.save
    claim = legacy.PostgreSQLExecutionTests.claim
    finish = legacy.PostgreSQLExecutionTests.finish

    def graph(self, target=True):
        node = {"id": "selected", "title": "整理一筆", "capability": "llm", "scope": "rows",
                "prompt": "summarize", "row_source": {"tab_key": "shots", "table_id": "b_table"},
                "write_mode": "direct", "input_tabs": []}
        if target:
            node["target"] = {"tab_key": "shots", "col_index": 1}
        return {"nodes": [{"id": "upstream", "capability": "llm", "scope": "once"}, node,
                          {"id": "downstream", "capability": "llm", "scope": "once"}],
                "edges": [{"source": "upstream", "target": "selected"}, {"source": "selected", "target": "downstream"}]}

    def request(self, **overrides):
        return {"execution_mode": "single_step", "node_id": "selected", "definition_revision": 1,
                "input_mode": "current_sources", "sample_row_id": "b_shot2", "source_revisions": {"shots": 1}, **overrides}

    def test_exact_step_single_sample_forces_review_and_never_queues_descendants(self):
        self.save(self.graph())
        preview = flow_runner.preflight(self.conn, self.me, self.slug, "flow", self.request())
        self.assertTrue(preview["ready"], preview)
        self.assertEqual([node["node_id"] for node in preview["nodes"]], ["selected"])
        self.assertEqual(preview["nodes"][0]["row_ids"], ["b_shot2"])
        self.assertEqual(preview["nodes"][0]["target_column"], "Output")
        self.assertEqual(flow_runner.list_runs(self.conn, self.slug, "flow")["runs"], [])
        data = flow_runner.start(self.conn, self.me, self.slug, "flow", self.request())
        self.assertEqual(len(data["tasks"]), 1)
        task = self.claim()
        self.assertEqual((task["node_id"], task["row_id"]), ("selected", "b_shot2"))
        self.assertEqual([row["row_id"] for row in task["input"]["rows"]], ["b_shot2"])
        self.assertEqual(task["input"]["predecessors"], {})
        result = self.finish(task, "reviewed result")
        self.assertEqual(result["status"], "awaiting_approval")
        self.assertNotIn("reviewed result", str(repo.get_tab(self.conn, self.slug, "shots")["doc"]))
        self.assertIsNone(self.claim())
        self.assertEqual(assistant_service.apply_proposal(self.conn, self.me, self.slug, result["proposal_id"], {})[0], 200)
        self.assertIsNone(self.claim())
        complete = flow_runner.detail(self.conn, self.slug, "flow", data["run"]["id"])
        self.assertEqual(complete["run"]["status"], "succeeded")
        self.assertEqual(len(complete["tasks"]), 1)

    def test_result_context_retains_claimed_source_label_without_exposing_target_snapshot(self):
        self.save(self.graph(target=False))
        data = flow_runner.start(self.conn, self.me, self.slug, "flow", self.request())
        task = self.claim()
        self.assertEqual(task["source_context"], {"tab_key": "shots", "table_id": "b_table", "row_id": "b_shot2",
                                                "title": "Shots", "revision": 1, "cells": ["Shot 2", "original"]})
        doc = copy.deepcopy(self.doc)
        doc["content"][0]["content"][2]["content"][0]["content"][0]["content"][0]["text"] = "changed label"
        repo.save_tab_doc(self.conn, self.slug, "shots", doc=doc, title="Changed source", actor_id=self.actor,
                          session_id="renamed", base_revision=1)
        public = flow_runner.detail(self.conn, self.slug, "flow", data["run"]["id"])["tasks"][0]
        self.assertEqual(public["source_context"]["cells"], ["Shot 2", "original"])
        self.assertEqual(public["source_context"]["title"], "Shots")
        self.assertNotIn("target_snapshot", public)
        self.assertNotIn("lease_hash", public)

    def test_stale_definition_and_source_versions_do_not_queue(self):
        self.save(self.graph())
        for changes in ({"definition_revision": 0}, {"source_revisions": {"shots": 0}}, {"source_revisions": {}}, {"sample_row_id": "missing"}):
            with self.subTest(changes=changes), self.assertRaises(flow_runner.ExecutionError):
                flow_runner.start(self.conn, self.me, self.slug, "flow", self.request(**changes))
        self.assertEqual(flow_runner.list_runs(self.conn, self.slug, "flow")["runs"], [])

    def test_source_changed_while_executing_or_waiting_for_approval_cannot_write(self):
        self.save(self.graph())
        flow_runner.start(self.conn, self.me, self.slug, "flow", self.request())
        task = self.claim()
        result = self.finish(task, "stale source output")
        doc = copy.deepcopy(self.doc)
        doc["content"][0]["content"][1]["content"][0]["content"][0]["content"][0]["text"] = "source updated elsewhere"
        repo.save_tab_doc(self.conn, self.slug, "shots", doc=doc, title="Shots", actor_id=self.actor, session_id="changed", base_revision=1)
        code, decided = assistant_service.apply_proposal(self.conn, self.me, self.slug, result["proposal_id"], {})
        self.assertEqual(code, 200)
        self.assertEqual(decided["proposal"]["status"], "failed")
        self.assertNotIn("stale source output", str(repo.get_tab(self.conn, self.slug, "shots")["doc"]))
        flow_runner.start(self.conn, self.me, self.slug, "flow", self.request(source_revisions={"shots": 2}))
        second = self.claim()
        repo.save_tab_doc(self.conn, self.slug, "shots", doc=doc, title="Shots renamed", actor_id=self.actor, session_id="changedagain", base_revision=2)
        with self.assertRaises(flow_runner.ExecutionError) as error:
            self.finish(second, "late execution")
        self.assertEqual(error.exception.status, 409)

    def test_changed_source_before_claim_fails_in_place_without_external_execution(self):
        self.save(self.graph(target=False))
        data = flow_runner.start(self.conn, self.me, self.slug, "flow", self.request())
        doc = copy.deepcopy(self.doc)
        doc["content"][0]["content"][2]["content"][0]["content"][0]["content"][0]["text"] = "updated"
        repo.save_tab_doc(self.conn, self.slug, "shots", doc=doc, title="Shots", actor_id=self.actor, session_id="changed", base_revision=1)
        self.assertIsNone(self.claim())
        failed = flow_runner.detail(self.conn, self.slug, "flow", data["run"]["id"])
        self.assertEqual(failed["tasks"][0]["status"], "failed")
        self.assertEqual(failed["tasks"][0]["attempts"], 0)
        self.assertIn("Source shots changed", failed["tasks"][0]["error"])
        flow_runner.control(self.conn, self.me, self.slug, "flow", data["run"]["id"], "retry")
        self.assertIsNone(self.claim())

    def test_viewer_cannot_preview_start_or_retry_and_other_editor_cannot_control(self):
        self.save(self.graph())
        viewer = service.Identity(self.actor, "Viewer", "viewer")
        for action in (flow_runner.preflight, flow_runner.start):
            with self.assertRaises(flow_runner.ExecutionError) as caught:
                action(self.conn, viewer, self.slug, "flow", self.request())
            self.assertEqual(caught.exception.status, 403)
        data = flow_runner.start(self.conn, self.me, self.slug, "flow", self.request())
        import uuid
        other = service.Identity(str(uuid.uuid4()), "Other", "editor")
        for identity in (viewer, other):
            with self.assertRaises(flow_runner.ExecutionError) as caught:
                flow_runner.control(self.conn, identity, self.slug, "flow", data["run"]["id"], "cancel")
            self.assertEqual(caught.exception.status, 403)

    def test_missing_upstream_source_and_missing_cell_row_are_actionable(self):
        graph = self.graph()
        graph["nodes"][1].update({"scope": "once", "row_source": None, "input_tabs": []})
        self.save(graph)
        preview = flow_runner.preflight(self.conn, self.me, self.slug, "flow", self.request())
        self.assertFalse(preview["ready"])
        self.assertIn("upstream dependencies", str(preview["errors"]))
        full = flow_runner.preflight(self.conn, self.me, self.slug, "flow", {})
        self.assertIn("output row", str(full["errors"]))

    def test_queue_availability_is_reported_before_execution(self):
        self.save(self.graph())
        with self.conn.cursor() as cur:
            cur.execute("UPDATE projectops.agent_limb SET last_seen_at=NULL WHERE id=%s", (self.worker["id"],))
        preview = flow_runner.preflight(self.conn, self.me, self.slug, "flow", self.request())
        self.assertFalse(preview["ready"])
        self.assertIn("worker is not connected", str(preview["errors"]))
        with self.assertRaises(flow_runner.ExecutionError):
            flow_runner.start(self.conn, self.me, self.slug, "flow", self.request())

    def test_full_preflight_rejects_missing_selected_row_before_queueing(self):
        self.save(self.graph())
        preview = flow_runner.preflight(self.conn, self.me, self.slug, "flow", {"row_ids": ["missing-row"]})
        self.assertFalse(preview["ready"])
        self.assertIn("selected rows no longer exist", str(preview["errors"]))

    def test_stable_column_reference_resolves_after_reorder(self):
        from project_docs.doc_schema import column_ids
        table = self.doc["content"][0]
        ids = column_ids(table)
        table["attrs"]["column_ids"] = [ids[1], ids[0]]
        for row in table["content"]:
            row["content"] = list(reversed(row["content"]))
        repo.save_tab_doc(self.conn, self.slug, "shots", doc=self.doc, title="Shots", actor_id=self.actor, session_id="reorder", base_revision=1)
        graph = self.graph()
        graph["nodes"][1]["target"].update({"column_id": ids[1], "table_id": "b_table"})
        self.save(graph)
        data = flow_runner.start(self.conn, self.me, self.slug, "flow", self.request(source_revisions={"shots": 2}))
        self.assertEqual(data["tasks"][0]["target"]["col_index"], 0)
