"""Strings the server hands to the English UI are English or neutral codes; the UI words them from its locale files."""
import copy
import inspect
import re
import unittest
from pathlib import Path

CJK = re.compile(r"[一-鿿]")


def cell(text):
    return {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def table_tab(first_cells):
    header = {"type": "tableRow", "attrs": {"bid": "header"}, "content": [dict(cell("Shot"), type="tableHeader")]}
    row = {"type": "tableRow", "attrs": {"bid": "row1"}, "content": first_cells}
    table = {"type": "table", "attrs": {"bid": "table1", "column_ids": ["c1"]}, "content": [header, row]}
    return {"key": "tasks", "title": "Tasks", "revision": 1, "doc": {"type": "doc", "content": [table]}}, row


class ProposalReviewWords(unittest.TestCase):
    def test_review_groups_are_neutral_english_with_codes_for_the_ui(self):
        from project_assistant.proposal_review import describe
        tab, before = table_tab([cell("Lena runs"), cell("")])         # a second cell that the header does not name
        after = copy.deepcopy(before)
        after["content"][1] = cell("![image](/projects/api/x/assets/pa_0123456789abcdef0123456789abcdef)")
        target = {"tab_key": "tasks", "field_edits": [], "ops": [
            {"op": "put_row", "table": "table1", "rid": "row1", "base": before, "node": after, "edited_cols": [1]},
            {"op": "put_row", "table": "table1", "rid": "row1", "base": {"content": [cell("")]}, "node": {"content": [cell("")]}, "edited_cols": [0]},
            {"op": "put_block", "base": {"type": "paragraph"}, "node": {"type": "paragraph"}}]}
        groups = describe(target, tab)["groups"]
        self.assertEqual([g["kind"] for g in groups], ["row", "row", "structure"])
        self.assertEqual((groups[0]["row_number"], groups[0]["context"], groups[0]["label"]), (1, "Lena runs", "Row 1 · Lena runs"))
        self.assertEqual(groups[1]["label"], "Row 1 · New data")
        self.assertEqual(groups[2]["label"], "Structural change")
        change = groups[0]["changes"][0]
        self.assertEqual((change["column"], change["column_kind"], change["column_index"]), ("Column 2", "index", 1))
        self.assertEqual(groups[2]["changes"][0]["column"], "Document / structure")
        self.assertEqual(groups[2]["changes"][0]["column_kind"], "structure")
        for group in groups:
            self.assertFalse(CJK.search(group["label"]), group["label"])
            for item in group["changes"]:
                self.assertFalse(CJK.search(item["column"]), item["column"])

    def test_image_cells_are_labelled_in_english_not_chinese(self):
        from project_assistant import table_edits
        cell_node = {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "image", "attrs": {"src": "/projects/api/x/assets/pa_0", "alt": ""}}]}]}
        self.assertEqual(table_edits.cell_value(cell_node, {}), "![image](/projects/api/x/assets/pa_0)")
        self.assertFalse(CJK.search(inspect.getsource(__import__("project_assistant.proposal_output", fromlist=["x"]))))


class SourceHasNoChineseForTheEnglishUi(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[1]

    def test_whole_files(self):
        for name in ("project_assistant/orchestration_service.py", "project_assistant/proposal_review.py", "project_assistant/proposal_output.py"):
            self.assertIsNone(CJK.search((self.ROOT / name).read_text(encoding="utf-8")), name)

    def test_step_test_preview_and_start_errors(self):
        from project_assistant import flow_runner
        for function in (flow_runner.preflight, flow_runner._start_single_step, flow_runner.start):
            self.assertIsNone(CJK.search(inspect.getsource(function)), function.__name__)

    def test_the_two_pipeline_errors_map_to_catalogue_keys(self):
        from project_docs import locale
        for text, key in (("Save a valid pipeline first: Name is required", "saveAValidPipelineFirst"),
                          ("Create and save a valid pipeline first: Name is required", "createAndSaveAValidPipelineFirst")):
            details = locale.error_details({"error": text})
            self.assertEqual((details["message_key"], details["message_params"]), ("errors." + key, {"v0": "Name is required"}))


if __name__ == "__main__":
    unittest.main()
