"""OpenBench core unit tests (schema validation, block ops, anchoring, masking, providers, multi-project HTTP)."""
from __future__ import annotations

import os
import unittest
from unittest import mock

from project_docs import anchoring, blocks, doc_schema, http, markdown_import
from project_assistant import masking, prompting, providers


class OpenBenchCoreTests(unittest.TestCase):
    def test_markdown_import_and_doc_validation(self):
        md = (
            "# 專案啟動計畫\n\n"
            "這是第一段說明文字。\n\n"
            "| 項目 | 狀態 | 請填備註 |\n"
            "| --- | --- | --- |\n"
            "| 資料管線 | {{s:進行中}} | 預計週五完成 |\n"
        )
        doc, fields = markdown_import.markdown_to_doc(
            md, tab_keys={"overview"}, image_src=lambda k: None
        )
        cleaned, _ = doc_schema.validate_doc(doc, slug="ad-data")
        self.assertEqual(cleaned["type"], "doc")
        self.assertTrue(len(cleaned["content"]) >= 3)
        self.assertEqual(len(fields), 1)

    def test_block_ops_and_locking(self):
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "attrs": {"bid": "b1111111111", "owner": None, "created": None},
                    "content": [{"type": "text", "text": "初始內容"}],
                }
            ],
        }
        actor = blocks.Actor(actor_id="22222222-2222-4222-8222-222222222222", is_admin=False)
        res = blocks.apply_ops(
            doc,
            [
                {
                    "op": "put",
                    "bid": "b1111111111",
                    "base": doc["content"][0],
                    "node": {
                        "type": "paragraph",
                        "attrs": {"bid": "b1111111111"},
                        "content": [{"type": "text", "text": "更新後的內容"}],
                    },
                }
            ],
            actor,
            locks={},
            now="2026-10-16T12:00:00Z",
        )
        self.assertEqual(res.applied, 1)
        self.assertEqual(res.conflicts, [])
        self.assertEqual(res.doc["content"][0]["content"][0]["text"], "更新後的內容")

    def test_anchoring_reattaches_after_prefix_edit(self):
        text_before = "每天早上十點匯出成效日報並檢查異常"
        anchor = anchoring.anchor_at(text_before, 8, "成效日報")
        self.assertEqual(anchor["quote"], "成效日報")

        text_after = "【重要】每天早上十點匯出成效日報並檢查異常"
        resolved = anchoring.resolve(text_after, anchor)
        self.assertIsNotNone(resolved)
        start, end, exact = resolved
        self.assertTrue(exact)
        self.assertEqual(text_after[start:end], "成效日報")

    def test_masking_hides_numbers_and_keeps_ratios(self):
        raw = "我們昨天的花費是 128,500 元，轉換比例是 0.65，留存天數 30 天"
        cleaned, count = masking.mask_text(raw)
        self.assertNotIn("128,500", cleaned)
        self.assertGreaterEqual(count, 1)
        self.assertIn("0.65", cleaned)
        self.assertIn("30", cleaned)

    def test_prompting_parses_generic_knowledge_criteria(self):
        system, knowledge = prompting.load()
        self.assertIn("Studio Assistant", system)
        criteria = prompting.question_criteria(knowledge)
        self.assertIn(1, criteria)
        self.assertTrue(len(criteria[1]["criteria"]) >= 3)
        self.assertTrue(bool(criteria[1]["use"]))

    def test_provider_config_from_env(self):
        with mock.patch.dict(
            os.environ,
            {
                "OPENBENCH_PROVIDER": "openai_compat",
                "OPENBENCH_API_BASE": "http://localhost:11434/v1",
                "OPENBENCH_MODEL": "qwen2.5-coder:32b",
            },
            clear=False,
        ):
            cfg = providers.provider_from_env()
            self.assertEqual(cfg.kind, "openai_compat")
            self.assertEqual(cfg.base_url, "http://localhost:11434/v1")
            self.assertEqual(cfg.model, "qwen2.5-coder:32b")

    def test_http_static_and_connection_factory(self):
        called = []
        http.set_connection_factory(lambda: called.append(True))
        http.open_connection()
        self.assertEqual(called, [True])
        http.set_connection_factory(None)


if __name__ == "__main__":
    unittest.main()
