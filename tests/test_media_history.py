import copy
import unittest
from project_docs.page_history import block_changes


class MediaHistoryTests(unittest.TestCase):
    def test_row_media_versions_keep_full_urls_outside_clipped_text_diff(self):
        old_url = "/projects/api/demo/assets/pa_" + "a" * 32
        new_url = "/projects/api/demo/assets/pa_" + "b" * 32
        before = {"type": "doc", "content": [{"type": "table", "attrs": {"bid": "table"}, "content": [
            {"type": "tableRow", "attrs": {"bid": "row"}, "content": [{"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Long prompt " * 100 + f"![image]({old_url})"}]}]}]}
        ]}]}
        after = copy.deepcopy(before)
        after["content"][0]["content"][0]["content"][0]["content"][0]["content"][0]["text"] = "Long prompt " * 100 + f"![image]({new_url})"
        change = block_changes(before, after)[0]
        self.assertEqual(change["media_before"], [old_url])
        self.assertEqual(change["media_after"], [new_url])
        self.assertEqual(change["rid"], "row")
