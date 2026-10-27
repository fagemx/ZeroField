"""SPEC_20 R41: what the Agent Console's external-agent page reads from the service-account admin routes.

Real HTTP and the disposable PostgreSQL in OPENBENCH_TEST_DB_URI (run with PYTHONPATH=tests). No model, GPU or
ComfyUI is called: the tools used here only read the seeded sheet or are refused before they run.
"""
import json
import os
import unittest

from project_assistant import service_accounts, tool_registry


class AvailableToolsTests(unittest.TestCase):
    def test_form_options_follow_the_registry_exposure_and_carry_labels_and_write_flags(self):
        tools = service_accounts.available_tools()
        self.assertEqual([t['name'] for t in tools], service_accounts.exposed_tools())
        by_name = {t['name']: t for t in tools}
        self.assertEqual(set(by_name['request_generation']), {'name', 'label', 'category', 'writes', 'generation'})
        self.assertTrue(by_name['request_generation']['generation'])
        self.assertTrue(by_name['request_generation']['writes'])
        self.assertEqual(by_name['read_page']['writes'], False)
        self.assertEqual(by_name['propose_table_edit']['writes'], True)
        self.assertEqual(by_name['propose_table_edit']['generation'], False)
        self.assertEqual({t['name'] for t in tools if t['generation']}, set(tool_registry.GENERATION) & set(tool_registry.ZEROFIELD_MCP))
        self.assertTrue(all(t['label'] for t in tools))


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'set OPENBENCH_TEST_DB_URI')
class AuditRouteTests(unittest.TestCase):
    def setUp(self):
        import test_product_http as product_fixture
        self.fixture = product_fixture.ProductHTTPTests
        self.fixture.setUp(self)
        self.base = f'/projects/api/{self.slug}/service-accounts'

    def tearDown(self):
        self.fixture.tearDown(self)

    def request(self, *args, **kwargs):
        return self.fixture.request(self, *args, **kwargs)

    def agent(self, path, token, *, method='GET', data=None):
        return self.request(path, method=method, data=data, authenticated=False, headers={'Authorization': 'Bearer ' + token})

    def issue(self, key='claude-code', **extra):
        body = {'accountKey': key, 'displayName': 'Claude Code', 'tools': ['list_pages', 'read_page', 'propose_table_edit'],
                'expiresInDays': 5, **extra}
        code, issued, _ = self.request(self.base, method='POST', data=body)
        self.assertEqual(code, 200, issued)
        return issued['token']

    def test_audit_lists_issue_calls_refusals_and_revoke_newest_first(self):
        token = self.issue()
        self.assertEqual(self.agent('/agent-mcp/v1/tools/read_page', token, method='POST',
                                    data={'arguments': {'key': 'shots'}, 'client': {'name': 'Claude Code', 'version': '2.1'}})[0], 200)
        self.assertEqual(self.agent('/agent-mcp/v1/tools/spawn_agent', token, method='POST', data={'arguments': {}})[0], 404)
        self.assertEqual(self.agent('/agent-mcp/v1/tools/read_page', token, method='POST', data={'arguments': {'key': 'nope-not-a-page'}})[0], 200)
        self.assertEqual(self.request(self.base + '/claude-code/revoke', method='POST', data={})[0], 200)
        self.assertEqual(self.agent('/agent-mcp/v1/tools', token)[1]['code'], 'TOKEN_REVOKED')

        code, audit, _ = self.request(self.base + '/claude-code/audit')
        self.assertEqual(code, 200, audit)
        self.assertEqual((audit['accountKey'], audit['limit']), ('claude-code', 25))
        rows = audit['items']
        self.assertEqual([r['kind'] for r in rows], ['call', 'revoked', 'call', 'call', 'call', 'issued'])
        self.assertEqual([r.get('tool') for r in rows], [None, None, 'read_page', 'spawn_agent', 'read_page', None])
        outcomes = {(r.get('tool'), r.get('outcome'), r.get('code')) for r in rows if r['kind'] == 'call'}
        self.assertIn(('spawn_agent', 'denied', 'NOT_IN_SCOPE'), outcomes)
        self.assertIn(('read_page', 'ok', None), outcomes)
        self.assertIn((None, 'denied', 'TOKEN_REVOKED'), outcomes)
        first_call = next(r for r in rows if r.get('tool') == 'read_page' and r.get('client'))
        self.assertEqual(first_call['client'], {'name': 'Claude Code', 'version': '2.1'})
        self.assertEqual(first_call['actor'], {'id': self.actor, 'name': 'Execution test'})  # the showrunner whose authority it runs under
        self.assertEqual(first_call['writeMode'], 'propose_only')
        issued = rows[-1]
        self.assertEqual((issued['kind'], issued['tools'], issued['writeMode']), ('issued', ['list_pages', 'read_page', 'propose_table_edit'], 'propose_only'))
        self.assertEqual(rows[1]['actor'], {'id': self.actor, 'name': 'Execution test'})
        stamps = [r['at'] for r in rows]
        self.assertEqual(stamps, sorted(stamps, reverse=True))
        text = json.dumps(audit)
        self.assertNotIn(token, text)
        self.assertNotIn('argsSha256', text)

    def test_limit_scope_and_admin_only(self):
        token = self.issue()
        other = self.issue('goose', displayName='Goose')
        for _ in range(3):
            self.agent('/agent-mcp/v1/tools/list_pages', token, method='POST', data={'arguments': {}})
        self.agent('/agent-mcp/v1/tools/list_pages', other, method='POST', data={'arguments': {}})
        self.assertEqual(len(self.request(self.base + '/claude-code/audit?limit=2')[1]['items']), 2)
        everything = self.request(self.base + '/claude-code/audit?limit=100')[1]['items']
        self.assertEqual(len(everything), 4)  # the issue and three calls, none of the other account's
        self.assertEqual([r['kind'] for r in self.request(self.base + '/goose/audit')[1]['items']], ['call', 'issued'])
        for bad in ('0', '101', 'x', '-3', '2.5'):
            with self.subTest(limit=bad):
                code, payload, _ = self.request(self.base + '/claude-code/audit?limit=' + bad)
                self.assertEqual((code, payload['code']), (400, 'INVALID_REQUEST'))
        self.assertEqual(self.request(self.base + '/missing/audit')[0], 404)
        self.assertEqual(self.request(self.base + '/claude-code/audit', method='POST', data={})[0], 405)
        self.assertEqual(self.request(self.base + '/claude-code/audit', authenticated=False)[0], 401)
        self.assertEqual(self.agent(self.base + '/claude-code/audit', token)[0], 401)  # an agent token is not a crew login
        from project_docs import repository as repo
        repo.upsert_member(self.conn, self.actor, 'Execution test', 'member')
        self.conn.commit()
        self.assertEqual(self.request(self.base + '/claude-code/audit')[0], 403)
        self.assertEqual(self.request(self.base)[0], 403)

    def test_listing_carries_labels_for_the_token_form(self):
        self.issue()
        code, listed, _ = self.request(self.base)
        self.assertEqual(code, 200)
        by_name = {t['name']: t for t in listed['availableTools']}
        self.assertEqual(by_name['read_page']['label'], 'Production Page')
        self.assertEqual((by_name['request_generation']['generation'], by_name['request_generation']['category']), (True, 'generation'))


if __name__ == '__main__':
    unittest.main()
