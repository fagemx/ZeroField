"""The contest entry starts with a usable English slate and compatible statuses."""
import json
import re
import unittest
import os

from project_docs import doc_schema, markdown_import, templates
from project_assistant import agent_registry, flow_runner, prompting
from project_docs import repository as repo, service
import test_execution as fixture


class ZeroFieldBaselineTests(unittest.TestCase):
    def test_studio_template_has_five_english_tabs_and_empty_media_cells(self):
        specs = templates.tab_specs('zerofield_studio', 'Test Film', '')
        self.assertEqual([s[0] for s in specs], [
            'director-brief', 'soul-cast', 'cinema-studio', 'openjutsu-lab', 'comfy-pipeline'])
        for key, title, surface, markdown in specs:
            with self.subTest(tab=key):
                self.assertIsNone(re.search(r'[\u3400-\u9fff]', title + markdown))
                doc, _ = markdown_import.markdown_to_doc(markdown, tab_keys={s[0] for s in specs}, image_src=lambda _: None)
                templates.configure_doc(key, doc)
                clean, _ = doc_schema.validate_doc(doc, slug='contest-test')
                self.assertNotIn('Approved', json.dumps(clean))
                if key in templates.COLUMN_TYPES:
                    table = next(n for n in clean['content'] if n['type'] == 'table')
                    self.assertEqual(table['attrs']['column_types'], templates.COLUMN_TYPES[key])
                self.assertNotIn('asset_url', json.dumps(clean))

    def test_studio_pipeline_targets_existing_tabs_and_requires_review(self):
        definition = templates.flow_specs('zerofield_studio')['comfy-pipeline']
        definition = flow_runner.validate_definition(definition)
        tabs = {s[0] for s in templates.tab_specs('zerofield_studio', 'Test Film', '')}
        self.assertTrue(definition['nodes'])
        for node in definition['nodes']:
            self.assertTrue(set(node['input_tabs']) <= tabs)
            self.assertIn(node['target']['tab_key'], tabs)
            self.assertEqual(node['write_mode'], 'proposal')

    def test_english_statuses_save_and_legacy_statuses_remain_valid(self):
        for label in ('Queued', 'In Progress', 'Rendering Image', 'Rendering Video',
                      'Pending Review', 'Retake', 'Blocked', 'Approved', '未開始', '已完成'):
            doc = {'type': 'doc', 'content': [{'type': 'paragraph', 'content': [
                {'type': 'status', 'attrs': {'label': label}}]}]}
            clean, _ = doc_schema.validate_doc(doc, slug='contest-test')
            self.assertIn(label, json.dumps(clean, ensure_ascii=False))

    def test_default_agents_have_english_names_and_keep_m8_keys(self):
        self.assertEqual([r[0] for r in agent_registry.ROSTER], ['coordinator', 'doc_writer', 'sheet_ops', 'qa_critic'])
        for _, name, *_ in agent_registry.ROSTER:
            self.assertIsNone(re.search(r'[\u3400-\u9fff]', name))

    def test_english_brief_criteria_are_available_to_the_assistant(self):
        criteria = prompting.question_criteria('**Question 1 — What is the production goal?**\n'
            '- Purpose: Establish the delivery.\n- Completeness:\n  1. Audience\n  2. Duration\n')
        self.assertEqual(criteria[1]['criteria'], ['Audience', 'Duration'])
        self.assertEqual(criteria[1]['use'], 'Establish the delivery.')


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'set OPENBENCH_TEST_DB_URI')
class ZeroFieldDatabaseTests(unittest.TestCase):
    setUp = fixture.PostgreSQLExecutionTests.setUp
    tearDown = fixture.PostgreSQLExecutionTests.tearDown

    def test_default_project_supports_english_and_legacy_status_updates(self):
        slug = self.slug + '-studio'
        code, result = service.create_project(self.conn, self.me, {'slug': slug, 'title': 'Test Film'})
        self.assertEqual(code, 200, result)
        tab = repo.get_tab(self.conn, slug, 'cinema-studio')
        self.assertIsNotNone(tab)
        fields, _ = doc_schema.index_doc(tab['doc'])
        fid = next(key for key, field in fields.items() if field['kind'] == 'status')
        for value in ('Pending Review', 'Approved', '已完成'):
            code, result = service.set_field(self.conn, self.me, slug,
                {'tab_key': 'cinema-studio', 'field_id': fid, 'value': value})
            self.assertEqual(code, 200, result)
            self.assertEqual(repo.field_values(self.conn, slug)['cinema-studio'][fid]['value'], value)
        with self.conn.cursor() as cur:
            cur.execute('SELECT definition FROM projectops.flow_definition WHERE project_slug=%s AND tab_key=%s', (slug, 'comfy-pipeline'))
            self.assertEqual(len(cur.fetchone()[0]['nodes']), 5)


if __name__ == '__main__':
    unittest.main()
