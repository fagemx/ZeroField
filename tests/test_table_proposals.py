import copy
import unittest
from unittest import mock

from project_docs import blocks
from project_docs.service import Identity
from project_assistant import masking


def sample():
    def cell(value, header=False):
        return {"type": "tableHeader" if header else "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": value}]}]}
    return {"type": "doc", "content": [{"type": "table", "attrs": {"bid": "table001"}, "content": [
        {"type": "tableRow", "attrs": {"bid": "header01"}, "content": [cell("Shot", True), cell("Prompt", True)]},
        {"type": "tableRow", "attrs": {"bid": "row00001"}, "content": [cell("S01"), cell("old")]},
    ]}]}


class TableProposalTests(unittest.TestCase):
    def test_prepare_and_apply_preserves_untouched_cells(self):
        from project_assistant.table_edits import prepare
        original = sample()
        ops, fields, preview = prepare(original, [{"row_id": "row00001", "cells": {"1": "seed 48291"}}], [["S02", "new"]], {})
        result = blocks.apply_ops(original, ops, blocks.Actor("actor", False), locks={}, now="2026-10-16T00:00:00Z")
        self.assertEqual(result.applied, 2)
        self.assertEqual(result.doc["content"][0]["content"][1]["content"][0], original["content"][0]["content"][1]["content"][0])
        self.assertIn("48291", preview)
        self.assertEqual(len(original["content"][0]["content"]), 2)
        self.assertEqual(fields, [])

    def test_reject_unknown_row_column_and_ambiguous_table(self):
        from project_assistant.table_edits import prepare
        for edits, rows in [([{"row_id": "missing", "cells": {"1": "a"}}], []), ([{"row_id": "row00001", "cells": {"9": "a"}}], []), ([], [["too", "many", "cells"]])]:
            with self.assertRaises(ValueError):
                prepare(sample(), edits, rows, {})
        doc = sample()
        doc["content"].append(copy.deepcopy(doc["content"][0]))
        with self.assertRaises(ValueError):
            prepare(doc, [], [["a", "b"]], {})

    def test_apply_conflict_does_not_partially_write(self):
        from project_assistant.table_edits import apply, prepare
        doc = sample()
        ops, fields, _ = prepare(doc, [{"row_id": "row00001", "cells": {"1": "changed"}}], [], {})
        current = copy.deepcopy(doc)
        current["content"][0]["content"][1]["content"][1]["content"][0]["content"][0]["text"] = "other author"
        with mock.patch("project_assistant.table_edits.repo.get_tab_for_update", return_value={"doc": current}), mock.patch("project_assistant.table_edits.repo.tab_locks", return_value={}), mock.patch("project_assistant.table_edits.repo.field_values", return_value={}), mock.patch("project_docs.service._run_ops") as write:
            status, payload = apply(object(), Identity("actor", "Alex", "admin"), "demo", {"tab_key": "sheet", "ops": ops, "field_edits": fields})
        self.assertEqual(status, 409)
        write.assert_not_called()

    def test_single_step_source_revision_is_checked_before_target_write(self):
        from project_assistant.table_edits import apply, prepare
        doc = sample()
        ops, fields, _ = prepare(doc, [{"row_id": "row00001", "cells": {"1": "result"}}], [], {})
        tab = {"doc": doc, "revision": 2}
        with mock.patch("project_assistant.table_edits.repo.get_tab_for_update", side_effect=lambda conn, slug, key: tab if key == "sheet" else {"revision": 5}) as locked, mock.patch("project_docs.service._run_ops") as write:
            status, payload = apply(None, Identity("actor", "Alex", "admin"), "demo", {"tab_key": "sheet", "ops": ops, "field_edits": fields, "source_revisions": {"source": 4}})
        self.assertEqual(status, 409, payload)
        self.assertEqual([call.args[2] for call in locked.call_args_list], ["sheet", "source"])
        write.assert_not_called()

    def test_privacy_default_keeps_numbers(self):
        self.assertEqual(masking.guard_input("budget 128500 seed 48291", mask_numbers=False), ("budget 128500 seed 48291", []))
        self.assertNotIn("128500", masking.guard_input("budget 128500", mask_numbers=True)[0])

    def test_masked_currency_negative_and_formula_constants(self):
        for value in ["Loss -128500 dollars", "Budget USD128500", "=B2-128500", "=1000+2000", "| total | `=1000+2000` |"]:
            result, _ = masking.guard_input(value, mask_numbers=True)
            for secret in ("128500", "1000", "2000"):
                self.assertNotIn(secret, result)
        self.assertEqual(masking.mask_formula("=B2*35%+2000")[0], "=B2*35%+▢")

    def test_deleted_row_is_not_resurrected_by_stale_edit(self):
        from project_assistant.table_edits import prepare, apply
        doc = sample()
        ops, fields, _ = prepare(doc, [{"row_id": "row00001", "cells": {"1": "new"}}], [], {})
        doc["content"][0]["content"].pop()
        with mock.patch("project_assistant.table_edits.repo.get_tab_for_update", return_value={"doc": doc}), mock.patch("project_assistant.table_edits.repo.tab_locks", return_value={}), mock.patch("project_docs.service._run_ops") as write:
            status, _ = apply(None, Identity("actor", "Alex", "admin"), "demo", {"tab_key": "sheet", "ops": ops, "field_edits": fields})
        self.assertEqual(status, 409)
        write.assert_not_called()

    def test_lock_change_before_write_remains_all_or_nothing(self):
        from project_assistant.table_edits import prepare, apply
        doc = sample()
        row2 = copy.deepcopy(doc["content"][0]["content"][1])
        row2["attrs"]["bid"] = "row00002"
        doc["content"][0]["content"].append(row2)
        ops, fields, _ = prepare(doc, [{"row_id": rid, "cells": {"1": "new"}} for rid in ("row00001", "row00002")], [], {})
        with mock.patch("project_assistant.table_edits.repo.get_tab_for_update", return_value={"doc": doc, "revision": 1, "updated_at": "now"}), mock.patch("project_assistant.table_edits.repo.tab_locks", side_effect=[{}, {"row00002": "other"}]), mock.patch("project_assistant.table_edits.repo.field_values", return_value={}), mock.patch("project_assistant.table_edits.repo.save_tab_doc") as save:
            status, _ = apply(None, Identity("actor", "Alex", "admin"), "demo", {"tab_key": "sheet", "ops": ops, "field_edits": fields})
        self.assertEqual(status, 409)
        save.assert_not_called()

    def test_long_sheet_pagination_keeps_editable_row_ids(self):
        from types import SimpleNamespace
        from project_assistant import tools
        doc = sample()
        rows = doc["content"][0]["content"]
        for i in range(30):
            row = copy.deepcopy(rows[1])
            row["attrs"]["bid"] = f"row{i:05d}"
            row["content"][1]["content"][0]["content"][0]["text"] = "long prompt " * 40
            rows.append(row)
        with mock.patch.object(tools, "_find_tab", return_value={"doc": doc, "key": "shots", "title": "Shots", "surface_type": "sheet"}), mock.patch.object(tools.todo, "plain_values", return_value={}):
            first = tools._clip(tools.read_page(SimpleNamespace(slug="demo"), None, {"key": "shots"}))
            later = tools._clip(tools.read_page(SimpleNamespace(slug="demo"), None, {"key": "shots", "offset": 20}))
        self.assertIn("table_id=table001", first)
        self.assertIn("row_id=row00001", first)
        self.assertIn("row_id=row00018", later)
        self.assertIn("offset=", first)


if __name__ == "__main__":
    unittest.main()
