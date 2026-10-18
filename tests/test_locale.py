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
