import copy
import unittest


def cell(text):
    return {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def fixture():
    header = {"type": "tableRow", "attrs": {"bid": "header"}, "content": [dict(cell("工作"), type="tableHeader"), dict(cell("優先級"), type="tableHeader")]}
    row = {"type": "tableRow", "attrs": {"bid": "row1"}, "content": [cell("整理資料"), cell("一般")]}
    table = {"type": "table", "attrs": {"bid": "table1", "column_ids": ["col1", "col2"]}, "content": [header, row]}
    return {"key": "tasks", "title": "工作清單", "revision": 3, "doc": {"type": "doc", "content": [table]}}


class RequestReviewTests(unittest.TestCase):
    def test_scope_uses_server_labels_and_rejects_stale_or_missing_ids(self):
        from project_assistant.request_scope import validate_scope
        tab = fixture()
        scope = {"target_tab": "tasks", "table_id": "table1", "base_revision": 3, "row_ids": ["row1"], "column_ids": ["col2"], "table_name": "untrusted"}
        result = validate_scope(scope, tab, {})
        self.assertEqual(result["column_indices"], [1])
        self.assertEqual(result["row_labels"], ["整理資料"])
        self.assertNotEqual(result["table_name"], "untrusted")
        for invalid in [dict(scope, base_revision=2), dict(scope, row_ids=["missing"]), dict(scope, column_ids=["missing"]), dict(scope, column_ids=[])]:
            with self.assertRaises(ValueError): validate_scope(invalid, tab, {})

    def test_scope_rejects_other_rows_columns_and_source_changes(self):
        from project_assistant.request_scope import validate_scope, guard_edits
        tab = fixture()
        scope = validate_scope({"target_tab": "tasks", "table_id": "table1", "base_revision": 3, "row_ids": ["row1"], "column_ids": ["col2"]}, tab, {})
        guard_edits(scope, tab, {}, [{"row_id": "row1", "cells": {"1": "高"}}], [], "table1")
        for edits in [[{"row_id": "other", "cells": {"1": "高"}}], [{"row_id": "row1", "cells": {"0": "高"}}]]:
            with self.assertRaises(ValueError): guard_edits(scope, tab, {}, edits, [], "table1")
        changed = copy.deepcopy(tab)
        changed["doc"]["content"][0]["content"][1]["content"][1] = cell("低")
        with self.assertRaises(ValueError): guard_edits(scope, changed, {}, [{"row_id": "row1", "cells": {"1": "高"}}], [], "table1")

    def test_review_has_named_before_after_and_selects_independent_rows(self):
        from project_assistant.proposal_review import describe, select_target
        tab = fixture()
        before = tab["doc"]["content"][0]["content"][1]
        after = copy.deepcopy(before); after["content"][1] = cell("高")
        target = {"tab_key": "tasks", "ops": [{"op": "put_row", "table": "table1", "rid": "row1", "base": before, "node": after, "edited_cols": [1]}], "field_edits": []}
        review = describe(target, tab, partial_allowed=True)
        self.assertEqual(review["groups"][0]["changes"][0]["column"], "優先級")
        self.assertEqual(review["groups"][0]["changes"][0]["before"], "一般")
        self.assertEqual(review["groups"][0]["changes"][0]["after"], "高")
        self.assertEqual(select_target(target, [0])["ops"], target["ops"])
        for selected in [[], [1], [0, 0], [True]]:
            with self.assertRaises(ValueError): select_target(target, selected)

    def test_added_rows_and_flow_results_cannot_be_partially_split(self):
        from project_assistant.proposal_review import describe, select_target
        target = {"ops": [{"op": "put_row", "base": None, "rid": "new", "node": {"content": []}}]}
        self.assertFalse(describe(target, fixture(), partial_allowed=True)["partial_allowed"])
        with self.assertRaises(ValueError): select_target(target, [0])


if __name__ == "__main__": unittest.main()
