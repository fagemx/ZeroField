"""HTTP regression for frozen input scope and independently accepted rows."""
import os
from types import SimpleNamespace
import unittest

import test_product_http as fixture
from project_assistant import store, tools, proposal_review
from project_docs import repository as repo
from project_docs.doc_schema import column_ids, node_text


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "set OPENBENCH_TEST_DB_URI")
class RequestReviewHTTPTests(unittest.TestCase):
    setUp = fixture.ProductHTTPTests.setUp
    tearDown = fixture.ProductHTTPTests.tearDown
    request = fixture.ProductHTTPTests.request

    def propose(self):
        base = f"/projects/api/{self.slug}"
        status, loaded, _ = self.request(base + "/tabs/shots")
        self.assertEqual(status, 200, loaded)
        tab = loaded["tab"]
        ids = column_ids(tab["doc"]["content"][0])
        scope = {"target_tab": "shots", "table_id": "b_table", "base_revision": tab["revision"],
                 "row_ids": ["b_shot1", "b_shot2"], "column_ids": ids}
        status, sent, _ = self.request(base + "/assistant/messages", method="POST", data={"text": "Update output for selected rows", "scope": scope})
        self.assertEqual(status, 200, sent)
        self.assertEqual(sent["message"]["request_scope"]["row_ids"], scope["row_ids"])
        ctx = SimpleNamespace(slug=self.slug, me=self.me, message_id=sent["reply"]["id"])
        tools.propose_table_edit(ctx, self.conn, {"tab_key": "shots", "table_id": "b_table",
            "row_edits": [{"row_id": rid, "cells": {"1": "proposal " + rid}} for rid in scope["row_ids"]]})
        self.conn.commit()
        proposal = store.proposals(self.conn, self.slug, owner_id=self.actor)[0]
        return tab, sent, proposal

    def test_partial_acceptance_is_persisted_and_replayed_selection_cannot_apply_next_row(self):
        tab, sent, proposal = self.propose()
        path = f"/projects/api/{self.slug}/assistant/proposals/{proposal['id']}/apply"
        body = {"groups": [0], "review_version": proposal_review.version(proposal["target"])}
        status, result, _ = self.request(path, method="POST", data=body)
        self.assertEqual(status, 200, result)
        self.assertTrue(result["partial"])
        self.assertEqual(result["proposal"]["status"], "pending")
        current = repo.get_tab(self.conn, self.slug, "shots")
        self.assertEqual(node_text(current["doc"]["content"][0]["content"][1]["content"][1]), "proposal b_shot1")
        self.assertEqual(node_text(current["doc"]["content"][0]["content"][2]["content"][1]), "original")
        self.conn.commit()
        # Double-click/retry of the same UI selection must not accept a different row.
        self.assertEqual(self.request(path, method="POST", data=body)[0], 409)
        remaining = store.proposal(self.conn, proposal["id"])
        self.assertEqual(remaining["target"]["ops"][0]["rid"], "b_shot2")
        self.assertGreater(remaining["target"]["request_scope"]["base_revision"], tab["revision"])
        self.assertEqual(store.message(self.conn, sent["message"]["id"])["request_scope"], sent["message"]["request_scope"])
        self.conn.commit()
        status, result, _ = self.request(path, method="POST", data={"groups": [0], "review_version": proposal_review.version(remaining["target"])})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["proposal"]["status"], "applied")

    def test_changed_selected_source_blocks_proposal_even_when_output_cell_is_unchanged(self):
        tab, sent, proposal = self.propose()
        ids = column_ids(tab["doc"]["content"][0])
        body = {"base_revision": tab["revision"], "row_edits": [{"row_id": "b_shot1", "cells": {"0": "changed source"},
                "expected_cells": {"0": "Shot 1"}, "column_ids": {"0": ids[0]}}]}
        status, result, _ = self.request(f"/projects/api/{self.slug}/tabs/shots/table-edit", method="POST", data=body)
        self.assertEqual(status, 200, result)
        path = f"/projects/api/{self.slug}/assistant/proposals/{proposal['id']}/apply"
        status, rejected, _ = self.request(path, method="POST", data={})
        self.assertEqual(status, 409, rejected)
        self.assertIn("source", rejected["error"])
        self.assertEqual(store.proposal(self.conn, proposal["id"])["status"], "pending")
        current = repo.get_tab(self.conn, self.slug, "shots")
        self.assertEqual(node_text(current["doc"]["content"][0]["content"][1]["content"][1]), "original")


if __name__ == "__main__":
    unittest.main()
