import unittest
from types import SimpleNamespace
from project_docs import locale


class LocaleTests(unittest.TestCase):
    def test_explicit_preferences_default_to_english_and_are_allowlisted(self):
        self.assertEqual(locale.request_locale(SimpleNamespace(headers={}, path='/login')), 'en')
        self.assertEqual(locale.request_locale(SimpleNamespace(headers={'Cookie':'zerofield_locale=zh-TW'}, path='/login')), 'zh-TW')
        for value in ('fr', 'zh-CN', '<script>', '%0d%0aSet-Cookie:evil'):
            self.assertEqual(locale.request_locale(SimpleNamespace(headers={}, path='/login?lang='+value)), 'en')
        self.assertEqual(locale.request_locale(SimpleNamespace(headers={'Cookie':'zerofield_locale=zh-TW'}, path='/login?lang=en')), 'en')

    def test_login_and_access_pages_share_locale_and_escape_user_text(self):
        english = locale.login_html('token', 'en')
        chinese = locale.login_html('token', 'zh-TW', '<script>token</script>')
        self.assertIn('lang="en"', english)
        self.assertIn('Access Token', english)
        self.assertIn('lang="zh-TW"', chinese)
        self.assertIn('存取權杖', chinese)
        self.assertIn('&lt;script&gt;', chinese)
        self.assertNotIn('<script>token</script>', chinese)
        self.assertIn('/login?lang=en', chinese)
        status, page = locale.problem_html('membership', 'en', '<private@example.test>')
        self.assertEqual(status, 403)
        self.assertIn('&lt;private@example.test&gt;', page)

    def test_error_metadata_is_additive_preserves_policy_codes_and_handles_dynamic_parameters(self):
        source = {'error':'Read-only crew members cannot modify a production.'}
        result = locale.error_details(source)
        self.assertEqual(result['error'], source['error'])
        self.assertTrue(result['message_key'].startswith('errors.'))
        self.assertNotIn('message_key', source)
        dynamic = locale.error_details({'error':'Production slug my-film already exists.', 'code':'POLICY_DENIED'})
        self.assertEqual(dynamic['code'], 'POLICY_DENIED')
        self.assertEqual(dynamic['message_params'], {'v0':'my-film'})
        unknown = {'error':'A custom provider failed.', 'code':'PROVIDER_ERROR'}
        self.assertEqual(locale.error_details(unknown), unknown)
        self.assertEqual(locale.error_details({'status':'ok'}), {'status':'ok'})
        expired = locale.error_details({'error':'Sign in to your studio account to open this page.', 'code':'projects_login'})
        self.assertEqual(expired['code'], 'projects_login')
        self.assertEqual(expired['message_key'], 'access.login')

    @staticmethod
    def dictionaries():
        import json
        from pathlib import Path
        root = Path(__file__).resolve().parents[1] / 'ui' / 'src' / 'i18n' / 'locales'
        return [json.loads((root / name).read_text(encoding='utf-8'))['errors'] for name in ('en.json', 'zh-TW.json')]

    def test_every_catalogue_pattern_has_matching_parameters_in_both_dictionaries(self):
        import re
        from project_docs.error_messages import MESSAGES
        for text, key, pattern in MESSAGES:
            for errors in self.dictionaries():
                self.assertIn(key, errors)
                if pattern:
                    self.assertEqual(set(re.findall(r'\{\{(\w+)\}\}', errors[key])), set(re.compile(pattern).groupindex), key)

    def test_proposal_conflict_messages_are_localized(self):
        import re
        from project_assistant.table_edits import _target_name, conflict_message
        cell = lambda text, kind='tableCell': {'type': kind, 'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': text}] if text else []}]}
        row = lambda rid, label: {'type': 'tableRow', 'attrs': {'bid': rid}, 'content': [cell(label), cell('old')]}
        header = {'type': 'tableRow', 'attrs': {'bid': 'h'}, 'content': [cell('Shot', 'tableHeader'), cell('Output', 'tableHeader')]}
        table = {'type': 'table', 'content': [header, row('r1', 'Shot 1'), row('r2', 'Shot 2'), row('r3', '')]}
        gone = {'type': 'table', 'content': [header]}
        shapes = [('value_changed', _target_name(table, row('r2', 'Shot 2'), 'r2', 1), 'proposalCellChanged'),
                  ('value_changed', _target_name(table, row('r3', ''), 'r3', 1), 'proposalCellChangedUnlabeledRow'),
                  ('row_changed', _target_name(table, row('r2', 'Shot 2'), 'r2'), 'proposalRowRestructured'),
                  ('row_changed', _target_name(table, row('r3', ''), 'r3'), 'proposalUnlabeledRowRestructured'),
                  ('row_deleted', _target_name(gone, row('r2', 'Shot 2'), 'r2'), 'proposalRowDeleted'),
                  ('row_deleted', _target_name(gone, row('r3', ''), 'r3'), 'proposalRowDeleted')]
        en, zh = self.dictionaries()
        fill = lambda template, params: re.sub(r'\{\{(\w+)\}\}', lambda m: params[m[1]], template)
        rendered = {}
        for reason, target, key in shapes:
            for count, suffix in ((1, ''), (3, 'More')):
                message = conflict_message([{'reason': reason, 'target': target}] * count)
                result = locale.error_details({'error': message})
                self.assertEqual(result['message_key'], 'errors.' + key + suffix, message)
                self.assertEqual(fill(en[key + suffix], result['message_params']), message)
                rendered[message] = fill(zh[key + suffix], result['message_params'])
        self.assertEqual(rendered['Output in row 2 “Shot 2” changed after this proposal was made. Nothing was applied; generate a new proposal.'],
                         '第 2 列「Shot 2」的 Output 在提案建立後已被修改；未套用任何變更，請重新產生提案。')
        self.assertEqual(rendered['The row “r3” was deleted after this proposal was made (and 2 more). Nothing was applied; generate a new proposal.'],
                         '「r3」這一列在提案建立後已被刪除（另有 2 處）；未套用任何變更，請重新產生提案。')

    def test_unauthenticated_api_still_returns_a_response_after_page_localization(self):
        from urllib.parse import urlparse
        from project_docs import http
        replies = []
        handler = SimpleNamespace(headers={}, path='/projects/api/projects',
                                  project_docs_identity=lambda **kwargs: (None, 'login'),
                                  send_json=lambda status, body: replies.append((status, body)))
        http._api(handler, urlparse(handler.path), 'GET')
        self.assertEqual(replies[0][0], 401)
        self.assertIn('error', replies[0][1])


if __name__ == '__main__':
    unittest.main()
