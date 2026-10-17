"""Real PostgreSQL acceptance for dynamic row expansion and document delivery."""
import copy
import os
import unittest

import test_execution as legacy
from project_assistant import flow_runner, service as assistant_service
from project_docs import repository as repo


class ScopeValidationTests(unittest.TestCase):
    def test_invalid_scope_source_and_document_target_rejected(self):
        changes = [
            {"scope": "shell"}, {"scope": "rows"},
            {"scope": "rows", "row_source": {"tab_key": "shots", "status_col": -1}},
            {"scope": "rows", "row_source": {"tab_key": "shots", "status": [123]}},
            {"scope": "once", "target": {"tab_key": "report", "kind": "doc", "col_index": 0}},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                flow_runner.validate_definition({"nodes": [{"id": "node", "capability": "llm", **change}], "edges": []})


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "set OPENBENCH_TEST_DB_URI")
class ScopedFlowTests(unittest.TestCase):
    setUp = legacy.PostgreSQLExecutionTests.setUp
    tearDown = legacy.PostgreSQLExecutionTests.tearDown
    save = legacy.PostgreSQLExecutionTests.save
    claim = legacy.PostgreSQLExecutionTests.claim
    finish = legacy.PostgreSQLExecutionTests.finish

    def node(self, identifier, scope, **kwargs):
        return {"id": identifier, "scope": scope, "capability": "llm", **kwargs}

    def source(self, **kwargs):
        return {"tab_key": "shots", "table_id": "b_table", **kwargs}

    def start(self, nodes, edges=(), **body):
        self.save({"nodes": nodes, "edges": [{"source": s, "target": t} for s, t in edges]})
        return flow_runner.start(self.conn, self.me, self.slug, "flow", body)

    def complete(self, task, output):
        return flow_runner.complete(self.conn, self.worker, {"task_id": task["id"], "lease_token": task["lease_token"], "output": output})

    def detail(self, run):
        return flow_runner.detail(self.conn, self.slug, "flow", run["run"]["id"])

    def test_approved_split_dynamic_fork_join_and_single_ordered_aggregate(self):
        empty = copy.deepcopy(self.doc)
        empty["content"][0]["content"] = empty["content"][0]["content"][:1]
        repo.save_tab_doc(self.conn, self.slug, "shots", doc=empty, title="Shots", actor_id=self.actor, session_id="setup", base_revision=1)
        run = self.start([
            self.node("split", "once", target={"tab_key": "shots"}),
            self.node("image", "rows", row_source=self.source()),
            self.node("audio", "rows", row_source=self.source()),
            self.node("video", "rows", row_source=self.source()),
            self.node("assemble", "aggregate", input_tabs=["shots"]),
        ], [("split", "image"), ("split", "audio"), ("image", "video"), ("video", "assemble"), ("audio", "assemble")])
        self.assertEqual(len(run["tasks"]), 1)
        split = self.claim()
        self.assertEqual(split["input"]["target_tables"][0]["headers"], ["Shot", "Output"])
        done = self.complete(split, {"new_rows": [["Shot A", "first"], ["Shot B", "second"]]})
        self.assertEqual(done["status"], "awaiting_approval")
        self.assertIsNone(self.claim())
        self.assertEqual(len(self.detail(run)["tasks"]), 1)
        self.assertEqual(assistant_service.apply_proposal(self.conn, self.me, self.slug, done["proposal_id"], {})[0], 200)
        row_ids = [r["attrs"]["bid"] for r in repo.get_tab(self.conn, self.slug, "shots")["doc"]["content"][0]["content"][1:]]
        branch = [self.claim() for _ in range(4)]
        self.assertEqual({t["node_id"] for t in branch}, {"image", "audio"})
        self.assertIsNone(self.claim())
        for task in reversed(branch):
            self.assertEqual(task["input"]["rows"][0]["row_id"], task["row_id"])
            self.assertEqual(task["input"]["predecessors"]["split"]["new_rows"][0][0], "Shot A")
            self.finish(task, task["row_id"])
        videos = [self.claim(), self.claim()]
        self.assertTrue(all(t["node_id"] == "video" for t in videos))
        self.finish(videos[1])
        self.assertIsNone(self.claim())
        self.finish(videos[0])
        aggregate = self.claim()
        self.assertEqual(aggregate["node_id"], "assemble")
        self.assertEqual([r["row_id"] for r in aggregate["input"]["rows"]], row_ids)
        self.assertEqual([t["row_id"] for t in aggregate["input"]["predecessor_tasks"]], [rid for rid in row_ids for _ in range(2)])
        self.assertEqual(len(aggregate["input"]["predecessors"]["video"]), 2)
        self.finish(aggregate)
        self.assertEqual(self.detail(run)["run"]["status"], "succeeded")
        self.assertEqual(len(self.detail(run)["tasks"]), 8)
        self.assertIsNone(self.claim())

    def test_selected_restart_status_filter_and_reference_tables(self):
        repo.create_tab(self.conn, self.slug, key="reference", title="Reference", parent_key=None,
                        doc=self.doc, actor_id=self.actor, surface_type="sheet")
        run = self.start([
            self.node("split", "once"),
            self.node("image", "rows", row_source=self.source(), input_tabs=["reference"], target={"tab_key": "shots", "col_index": 1}),
            self.node("assemble", "aggregate", input_tabs=["shots"]),
        ], [("split", "image"), ("image", "assemble")], start_node_id="image", row_ids=["b_shot2", "b_shot1"],
           row_source=self.source(status_col=0, status="Shot 2"))
        task = self.claim()
        self.assertEqual(task["node_id"], "image")
        self.assertEqual(task["row_id"], "b_shot2")
        ref = next(t for t in task["input"]["tabs"] if t["tab_key"] == "reference")
        self.assertEqual(len(ref["tables"][0]["rows"]), 2)
        done = self.finish(task)
        assistant_service.apply_proposal(self.conn, self.me, self.slug, done["proposal_id"], {})
        agg = self.claim()
        self.assertEqual([r["row_id"] for r in agg["input"]["rows"]], ["b_shot2"])
        self.finish(agg)
        self.assertEqual(len(self.detail(run)["tasks"]), 2)

    def test_empty_rows_are_persisted_and_aggregate_completes_once(self):
        run = self.start([self.node("image", "rows", row_source=self.source(status="absent")),
                          self.node("video", "rows", row_source=self.source(status="absent")),
                          self.node("assemble", "aggregate", input_tabs=["shots"])], [("image", "video"), ("video", "assemble")])
        self.assertEqual(run["run"]["execution"]["expanded"]["image"], [])
        self.assertEqual(len(run["tasks"]), 1)
        task = self.claim()
        self.assertEqual(task["node_id"], "assemble")
        self.assertEqual(task["input"]["predecessor_tasks"], [])
        self.assertEqual(task["input"]["rows"], [])
        self.finish(task)
        self.assertEqual(self.detail(run)["run"]["status"], "succeeded")

    def test_failure_retry_cancel_and_reconnect_do_not_reexpand(self):
        import psycopg
        run = self.start([self.node("image", "rows", row_source=self.source()), self.node("assemble", "aggregate")], [("image", "assemble")])
        first, second = self.claim(), self.claim()
        self.finish(first)
        flow_runner.fail(self.conn, self.worker, {"task_id": second["id"], "lease_token": second["lease_token"], "retryable": False})
        self.assertEqual(self.detail(run)["run"]["status"], "failed")
        self.conn.commit()
        with psycopg.connect(os.environ["OPENBENCH_TEST_DB_URI"]) as other:
            restarted = flow_runner.control(other, self.me, self.slug, "flow", run["run"]["id"], "retry")
            self.assertEqual(len(restarted["tasks"]), 2)
        retried = self.claim()
        self.assertEqual(retried["id"], second["id"])
        flow_runner.control(self.conn, self.me, self.slug, "flow", run["run"]["id"], "cancel")
        with self.assertRaises(flow_runner.ExecutionError):
            self.finish(retried)
        flow_runner.control(self.conn, self.me, self.slug, "flow", run["run"]["id"], "retry")
        self.finish(self.claim())
        agg = self.claim()
        self.assertEqual(agg["node_id"], "assemble")
        self.finish(agg)
        self.assertEqual(len(self.detail(run)["tasks"]), 3)

    def test_source_error_is_terminal_and_retry_recovers(self):
        run = self.start([self.node("image", "rows", row_source={"tab_key": "shots", "table_id": "b_missing"})])
        self.assertEqual(run["run"]["status"], "failed")
        self.assertIn("image", run["run"]["execution"]["errors"])
        changed = copy.deepcopy(self.doc)
        changed["content"][0]["attrs"]["bid"] = "b_missing"
        repo.save_tab_doc(self.conn, self.slug, "shots", doc=changed, title="Shots", actor_id=self.actor, session_id="fix", base_revision=1)
        result = flow_runner.control(self.conn, self.me, self.slug, "flow", run["run"]["id"], "retry")
        self.assertEqual(len(result["tasks"]), 2)
        self.assertFalse(result["run"]["execution"]["errors"])

    def test_document_review_append_replace_and_revision_conflict(self):
        repo.create_tab(self.conn, self.slug, key="report", title="Report", parent_key=None,
                        doc={"type": "doc", "content": []}, actor_id=self.actor, surface_type="doc")
        run = self.start([self.node("write", "once", target={"tab_key": "report", "kind": "doc"}), self.node("next", "once")], [("write", "next")])
        done = self.finish(self.claim(), "Weekly report\nBudget 12000")
        self.assertIsNone(self.claim())
        self.assertEqual(assistant_service.apply_proposal(self.conn, self.me, self.slug, done["proposal_id"], {})[0], 200)
        self.assertIn("Weekly report", str(repo.get_tab(self.conn, self.slug, "report")["doc"]))
        self.finish(self.claim())
        self.assertEqual(self.detail(run)["run"]["status"], "succeeded")
        definition = {"nodes": [self.node("replace", "once", write_mode="direct", target={"tab_key": "report", "kind": "doc", "mode": "replace"})], "edges": []}
        flow_runner.save_definition(self.conn, self.me, self.slug, "flow", {"definition": definition, "revision": 1})
        flow_runner.start(self.conn, self.me, self.slug, "flow", {})
        task = self.claim()
        self.finish(task, "Replacement")
        self.assertNotIn("Weekly report", str(repo.get_tab(self.conn, self.slug, "report")["doc"]))
        flow_runner.start(self.conn, self.me, self.slug, "flow", {})
        task = self.claim()
        tab = repo.get_tab(self.conn, self.slug, "report")
        repo.save_tab_doc(self.conn, self.slug, "report", doc=tab["doc"], title="Changed", actor_id=self.actor, session_id="human", base_revision=tab["revision"])
        with self.assertRaises(flow_runner.ExecutionError) as error:
            self.finish(task, "Late overwrite")
        self.assertEqual(error.exception.status, 409)

    def test_current_privacy_preserves_structured_ids_and_masks_cells(self):
        run = self.start([self.node("image", "rows", row_source=self.source())])
        changed = copy.deepcopy(self.doc)
        changed["content"][0]["content"][1]["content"][1]["content"][0]["content"][0]["text"] = "12000"
        repo.save_tab_doc(self.conn, self.slug, "shots", doc=changed, title="Shots", actor_id=self.actor, session_id="change", base_revision=1)
        repo.update_project_meta(self.conn, self.slug, privacy_mode="mask_numbers")
        task = self.claim()
        self.assertEqual(task["input"]["rows"][0]["row_id"], task["row_id"])
        self.assertNotIn("12000", str(task["input"]))

    def test_parallel_distinct_cell_proposals_merge_and_gate_join(self):
        run = self.start([
            self.node("image", "rows", row_source=self.source(), target={"tab_key": "shots", "col_index": 0}),
            self.node("audio", "rows", row_source=self.source(), target={"tab_key": "shots", "col_index": 1}),
            self.node("assemble", "aggregate"),
        ], [("image", "assemble"), ("audio", "assemble")], row_ids=["b_shot1"])
        first, second = self.claim(), self.claim()
        proposal1 = self.finish(first, first["node_id"])
        proposal2 = self.finish(second, second["node_id"])
        for done in (proposal1, proposal2):
            code, result = assistant_service.apply_proposal(self.conn, self.me, self.slug, done["proposal_id"], {})
            self.assertEqual(code, 200)
            self.assertEqual(result["proposal"]["status"], "applied", result)
        self.assertIn("image", str(repo.get_tab(self.conn, self.slug, "shots")["doc"]))
        self.assertIn("audio", str(repo.get_tab(self.conn, self.slug, "shots")["doc"]))
        aggregate = self.claim()
        self.assertEqual(aggregate["node_id"], "assemble")
        self.finish(aggregate)
        self.assertEqual(self.detail(run)["run"]["status"], "succeeded")

    def test_parallel_same_cell_proposal_conflicts(self):
        run = self.start([
            self.node(n, "rows", row_source=self.source(), target={"tab_key": "shots", "col_index": 1}) for n in ("a", "b")
        ], row_ids=["b_shot1"])
        first, second = self.claim(), self.claim()
        proposals = [self.finish(t, t["node_id"]) for t in (first, second)]
        for index, done in enumerate(proposals):
            _, result = assistant_service.apply_proposal(self.conn, self.me, self.slug, done["proposal_id"], {})
            self.assertEqual(result["proposal"]["status"], "applied" if index == 0 else "failed")
        self.assertEqual(self.detail(run)["run"]["status"], "failed")

    def test_dismissed_split_never_expands_and_retry_creates_fresh_proposal(self):
        run = self.start([self.node("split", "once", target={"tab_key": "shots"}),
                          self.node("image", "rows", row_source=self.source())], [("split", "image")])
        done = self.complete(self.claim(), {"new_rows": [["Shot 3", "new"]]})
        assistant_service.dismiss_proposal(self.conn, self.me, self.slug, done["proposal_id"])
        self.assertEqual(self.detail(run)["run"]["status"], "failed")
        self.assertEqual(len(self.detail(run)["tasks"]), 1)
        flow_runner.control(self.conn, self.me, self.slug, "flow", run["run"]["id"], "retry")
        again = self.complete(self.claim(), {"new_rows": [["Shot 3", "new"]]})
        self.assertNotEqual(done["proposal_id"], again["proposal_id"])
        assistant_service.apply_proposal(self.conn, self.me, self.slug, again["proposal_id"], {})
        self.assertEqual(len(self.detail(run)["tasks"]), 4)

    def test_status_capsule_filter_and_deleted_row_fail_without_deadlock(self):
        changed = copy.deepcopy(self.doc)
        changed["content"][0]["content"][1]["content"][1]["content"][0]["content"] = [{"type": "status", "attrs": {"fid": "f_status", "label": "未開始"}}]
        repo.save_tab_doc(self.conn, self.slug, "shots", doc=changed, title="Shots", actor_id=self.actor, session_id="setup", base_revision=1)
        repo.set_field_value(self.conn, self.slug, "shots", "f_status", kind="status", value="已完成", actor_id=self.actor)
        run = self.start([self.node("image", "rows", row_source=self.source(status="已完成", status_col=1))])
        self.assertEqual(len(run["tasks"]), 1)
        current = repo.get_tab(self.conn, self.slug, "shots")
        changed = copy.deepcopy(current["doc"])
        changed["content"][0]["content"] = [r for r in changed["content"][0]["content"] if r["attrs"]["bid"] != "b_shot1"]
        repo.save_tab_doc(self.conn, self.slug, "shots", doc=changed, title="Shots", actor_id=self.actor, session_id="delete", base_revision=current["revision"])
        self.assertIsNone(self.claim())
        self.assertEqual(self.detail(run)["run"]["status"], "failed")

    def test_aggregate_restart_freezes_status_filter_even_without_row_stage(self):
        run = self.start([self.node("split", "once"), self.node("assemble", "aggregate", input_tabs=["shots"])],
                         [("split", "assemble")], start_node_id="assemble", row_source=self.source(status="absent"),
                         row_ids=["b_shot2", "b_shot1"])
        task = self.claim()
        self.assertEqual(task["node_id"], "assemble")
        self.assertEqual(task["input"]["rows"], [])
        self.assertEqual(task["input"]["tabs"][0]["tables"][0]["rows"], [])
        self.assertNotIn("Shot 1", task["input"]["tabs"][0]["text"])
        self.finish(task)
        self.assertEqual(self.detail(run)["run"]["status"], "succeeded")
        run = flow_runner.start(self.conn, self.me, self.slug, "flow", {
            "start_node_id": "assemble", "row_source": self.source(status_col=0, status="Shot 2")})
        task = self.claim()
        self.assertEqual([r["row_id"] for r in task["input"]["rows"]], ["b_shot2"])
        self.assertEqual(len(task["input"]["tabs"][0]["tables"][0]["rows"]), 1)

    def test_document_asset_proposal_persists_clickable_safe_link(self):
        from project_docs.doc_schema import safe_href
        repo.create_tab(self.conn, self.slug, key="delivery", title="Delivery", parent_key=None,
                        doc={"type": "doc", "content": []}, actor_id=self.actor, surface_type="doc")
        run = self.start([self.node("assemble", "aggregate", target={"tab_key": "delivery", "kind": "doc"})])
        asset_id = repo.put_asset(self.conn, self.slug, data=b"test-asset", content_type="image/png", actor_id=self.actor)
        url = f"/projects/api/{self.slug}/assets/{asset_id}"
        done = self.complete(self.claim(), {"text": "Final delivery", "asset_url": url})
        _, applied = assistant_service.apply_proposal(self.conn, self.me, self.slug, done["proposal_id"], {})
        self.assertEqual(applied["proposal"]["status"], "applied")
        paragraphs = repo.get_tab(self.conn, self.slug, "delivery")["doc"]["content"]
        self.assertEqual(paragraphs[-1]["content"][0]["marks"], [{"type": "link", "attrs": {"href": safe_href(url)}}])
        self.assertEqual(paragraphs[-1]["content"][0]["text"], "產出媒體")
        self.assertEqual(self.detail(run)["run"]["status"], "succeeded")

    def test_selected_aggregate_restart_filters_source_tab_but_keeps_references(self):
        repo.create_tab(self.conn, self.slug, key="assets", title="Assets", parent_key=None,
                        doc=self.doc, actor_id=self.actor, surface_type="sheet")
        self.start([self.node("image", "rows", row_source=self.source()),
                    self.node("assemble", "aggregate", input_tabs=["shots", "assets"])],
                   [("image", "assemble")], start_node_id="assemble", row_ids=["b_shot2"], target_tab="shots")
        task = self.claim()
        self.assertEqual([r["row_id"] for r in task["input"]["rows"]], ["b_shot2"])
        shots, assets = task["input"]["tabs"]
        self.assertEqual([r["row_id"] for r in shots["tables"][0]["rows"]], ["b_shot2"])
        self.assertNotIn("Shot 1", shots["text"])
        self.assertIn("Shot 2", shots["text"])
        self.assertEqual(len(assets["tables"][0]["rows"]), 2)
        self.assertIn("Shot 1", assets["text"])
