"""SPEC_20 R34: MCP Apps (io.modelcontextprotocol/ui) and the 3D preview contact sheet card.

Protocol tests use a fake backend: negotiation with and without MCP Apps in both eras, _meta.ui.resourceUri on the
tools with a card, resources/list and resources/read, and the card's data on the tool result. The card itself is
checked as a file: self-contained, no external URL, a strict Content-Security-Policy. Database tests use the
disposable PostgreSQL in OPENBENCH_TEST_DB_URI: card data for propose_previs_ops and read_shot, how the contact sheet
reaches the card, token scope and audit, and POST /mcp against zerofield-mcp for the same token. The headless browser
is a fake (tests/test_previs_ops.fake_runner); no model, GPU or ComfyUI is called.
"""
import base64
import json
import os
import re
import tomllib
import unittest
import uuid
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

from project_assistant import mcp_apps, mcp_protocol as protocol, service_accounts, tool_registry, zerofield_mcp as mcp
from project_assistant.agent_registry import AgentError

ROOT = Path(__file__).resolve().parents[1]
CLIENT = {'name': 'apps-test', 'version': '1'}
APPS_CAPS = {'extensions': {mcp_apps.EXTENSION: {'mimeTypes': [mcp_apps.MIME]}}}
PLAIN = {protocol.META_VERSION: '2026-07-28', protocol.META_CAPABILITIES: {}, protocol.META_CLIENT: CLIENT}
APPS = {**PLAIN, protocol.META_CAPABILITIES: APPS_CAPS}
SHOT = 'sh_prod-a_b1'
ASSET = 'pa_' + 'a' * 32
SHEET_URI = mcp_apps.sheet_uri(SHOT, ASSET)
READ_SHOT = {'name': 'read_shot', 'title': 'Shot', 'description': 'Read one shot.',
             'inputSchema': {'type': 'object', 'properties': {'shot_id': {'type': 'string'}}, 'additionalProperties': False},
             '_meta': {'ui': {'resourceUri': 'ui://elsewhere/injected.html'}}}  # a backend never sets a tool's _meta
READ_PAGE = {'name': 'read_page', 'description': 'Read a page.',
             'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}}
CARD = {'kind': mcp_apps.CARD_KIND, 'version': 1, 'source': 'read_shot', 'shot': {'shotId': SHOT, 'label': 'S01'},
        'planRevision': 2, 'stored': True, 'open': {'path': '/projects/prod-a/#cinema-studio', 'label': 'Open in ZeroField'}}


def rpc(method, ident=1, meta=APPS, **params):
    if meta is not None:
        params['_meta'] = meta
    return {'jsonrpc': '2.0', 'id': ident, 'method': method, 'params': params}


class FakeBackend:
    def __init__(self, reply=None, error=None):
        self.reply = reply or {'text': '{"status": "ok"}', 'isError': False, 'images': [], 'card': CARD}
        self.error, self.calls, self.reads = error, [], []

    def list_tools(self):
        return [READ_SHOT, READ_PAGE]

    def call_tool(self, name, arguments, client=None, **options):
        self.calls.append((name, options))
        return self.reply

    def list_resources(self):
        return mcp_apps.resources_for(['read_shot'])

    def read_resource(self, uri, client=None):
        self.reads.append((uri, client))
        if self.error:
            raise self.error
        return {'contents': [{'uri': uri, 'mimeType': 'image/png', 'blob': 'AAAA'},
                             {'uri': 'zerofield://other', 'mimeType': 'image/png', 'blob': 'BBBB'}]}


class NegotiationTests(unittest.TestCase):
    def test_a_client_without_mcp_apps_sees_exactly_what_it_saw_before(self):
        for caps in ({}, {'extensions': {mcp_apps.EXTENSION: {'mimeTypes': ['text/html']}}},
                     {'extensions': {mcp_apps.EXTENSION: {}}}, {'extensions': {'io.example/ui': {'mimeTypes': [mcp_apps.MIME]}}}):
            with self.subTest(caps=caps):
                meta = {**PLAIN, protocol.META_CAPABILITIES: caps}
                backend = FakeBackend()
                server = mcp.Server(backend)
                self.assertEqual(server.handle(rpc('server/discover', meta=meta))['result']['capabilities'],
                                 {'tools': {'listChanged': False}})
                tools = server.handle(rpc('tools/list', 2, meta=meta))['result']['tools']
                self.assertEqual([t.get('_meta') for t in tools], [None, None])
                for method in ('resources/list', 'resources/templates/list', 'resources/read'):
                    self.assertEqual(server.handle(rpc(method, 3, meta=meta, uri=mcp_apps.PREVIS_CARD))['error']['code'],
                                     protocol.METHOD_NOT_FOUND)
                result = server.handle(rpc('tools/call', 4, meta=meta, name='read_shot', arguments={'shot_id': SHOT}))['result']
                self.assertEqual(backend.calls, [('read_shot', {})])  # the card is never even asked for
                self.assertEqual(result['_meta'], {protocol.META_SERVER: protocol.SERVER_INFO})
                self.assertEqual(result['structuredContent'], {'status': 'ok'})

    def test_a_modern_client_with_mcp_apps_gets_the_extension_resources_and_cards(self):
        backend = FakeBackend()
        server = mcp.Server(backend, url='http://127.0.0.1:3020')
        caps = server.handle(rpc('server/discover'))['result']['capabilities']
        self.assertEqual(caps, {'tools': {'listChanged': False}, 'resources': {'subscribe': False, 'listChanged': False},
                                'extensions': {mcp_apps.EXTENSION: {}}})
        tools = {t['name']: t for t in server.handle(rpc('tools/list', 2))['result']['tools']}
        self.assertEqual(tools['read_shot']['_meta'], {'ui': {'resourceUri': mcp_apps.PREVIS_CARD}, 'ui/resourceUri': mcp_apps.PREVIS_CARD})
        self.assertNotIn('_meta', tools['read_page'])
        self.assertEqual(set(mcp_apps.TOOL_CARDS), {'read_shot', 'propose_previs_ops'})
        self.assertEqual(protocol.tool_spec({'name': 'propose_previs_ops'}, True)['_meta']['ui']['resourceUri'], mcp_apps.PREVIS_CARD)
        result = server.handle(rpc('tools/call', 3, name='read_shot', arguments={'shot_id': SHOT}))['result']
        self.assertEqual(backend.calls[-1], ('read_shot', {'card': True}))
        card = result['_meta'][mcp_apps.CARD_META]
        self.assertEqual(card['open']['url'], 'http://127.0.0.1:3020/projects/prod-a/#cinema-studio')
        self.assertEqual(result['_meta'][protocol.META_SERVER], protocol.SERVER_INFO)  # merged, not replaced
        self.assertEqual((result['content'][0]['text'], result['structuredContent']), ('{"status": "ok"}', {'status': 'ok'}))
        server.handle(rpc('tools/call', 4, name='read_page', arguments={}))
        self.assertEqual(backend.calls[-1], ('read_page', {}))
        refused = mcp.Server(FakeBackend(reply={'text': 'NOT_FOUND: no', 'isError': True, 'card': CARD}))
        self.assertNotIn(mcp_apps.CARD_META, refused.handle(rpc('tools/call', name='read_shot', arguments={}))['result']['_meta'])
        listed = server.handle(rpc('resources/list', 5))['result']
        self.assertEqual([r['uri'] for r in listed['resources']], [mcp_apps.PREVIS_CARD])
        self.assertEqual(listed['resources'][0]['mimeType'], 'text/html;profile=mcp-app')
        self.assertEqual(server.handle(rpc('resources/templates/list', 6))['result']['resourceTemplates'], [])
        read = server.handle(rpc('resources/read', 7, uri=SHEET_URI))['result']
        self.assertEqual(read['contents'], [{'uri': SHEET_URI, 'mimeType': 'image/png', 'blob': 'AAAA'}])
        self.assertEqual(backend.reads, [(SHEET_URI, CLIENT)])

    def test_resource_read_errors(self):
        cases = [(protocol.BackendError(404, 'Resource not found.', 'RESOURCE_NOT_FOUND'), protocol.RESOURCE_NOT_FOUND),
                 (protocol.BackendError(429, 'Rate limit reached.', 'RATE_LIMITED'), protocol.RATE_LIMITED),
                 (protocol.BackendError(401, 'expired', 'TOKEN_EXPIRED'), protocol.TOKEN_REFUSED),
                 (protocol.BackendError(0, 'URLError'), protocol.SERVER_UNREACHABLE)]
        for exc, code in cases:
            with self.subTest(status=exc.status):
                error = mcp.Server(FakeBackend(error=exc)).handle(rpc('resources/read', uri=SHEET_URI))['error']
                self.assertEqual(error['code'], code)
        self.assertEqual(mcp.Server(FakeBackend(error=cases[0][0])).handle(rpc('resources/read', uri=SHEET_URI))['error']['data'],
                         {'uri': SHEET_URI})
        server = mcp.Server(FakeBackend())
        for bad in (None, '', 7, 'x' * 3000):
            with self.subTest(uri=bad):
                self.assertEqual(server.handle(rpc('resources/read', uri=bad))['error']['code'], protocol.INVALID_PARAMS)
        elsewhere = FakeBackend()
        elsewhere.read_resource = lambda uri, client=None: {'contents': [{'uri': 'zerofield://other', 'blob': 'BBBB'}]}
        self.assertEqual(mcp.Server(elsewhere).handle(rpc('resources/read', uri=SHEET_URI))['error']['code'],
                         protocol.RESOURCE_NOT_FOUND)  # contents of another uri are never passed on
        unconfigured = mcp.Server(FakeBackend(), config_error='Set ZEROFIELD_MCP_TOKEN.')
        self.assertEqual(unconfigured.handle(rpc('resources/read', uri=SHEET_URI))['error']['code'], protocol.TOKEN_REFUSED)

    def test_legacy_initialize_negotiates_where_the_transport_remembers_it(self):
        def initialize(server, caps):
            return server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                                  'params': {'protocolVersion': '2025-11-25', 'capabilities': caps}})['result']
        legacy = lambda ident, method, **params: {'jsonrpc': '2.0', 'id': ident, 'method': method, 'params': params}  # noqa: E731
        stdio = mcp.Server(FakeBackend())
        self.assertIn('extensions', initialize(stdio, APPS_CAPS)['capabilities'])
        tools = stdio.handle(legacy(2, 'tools/list'))['result']['tools']
        self.assertEqual(tools[0]['_meta']['ui']['resourceUri'], mcp_apps.PREVIS_CARD)
        self.assertEqual(stdio.handle(legacy(3, 'resources/list'))['result']['resources'][0]['uri'], mcp_apps.PREVIS_CARD)
        called = stdio.handle(legacy(4, 'tools/call', name='read_shot', arguments={}))['result']
        self.assertEqual(called['_meta'][mcp_apps.CARD_META]['open']['url'],
                         mcp.DEFAULT_URL + '/projects/prod-a/#cinema-studio')
        plain = mcp.Server(FakeBackend())
        self.assertEqual(initialize(plain, {})['capabilities'], {'tools': {'listChanged': False}})
        self.assertEqual(plain.handle(legacy(2, 'resources/list'))['error']['code'], protocol.METHOD_NOT_FOUND)
        self.assertNotIn('_meta', plain.handle(legacy(3, 'tools/call', name='read_shot', arguments={}))['result'])
        # Streamable HTTP keeps no session: its legacy handshake never offers what later requests could not honour.
        stateless = protocol.Server(FakeBackend(), legacy_apps=False)
        self.assertEqual(initialize(stateless, APPS_CAPS)['capabilities'], {'tools': {'listChanged': False}})
        self.assertEqual(protocol.Server(FakeBackend(), legacy='2025-11-25', legacy_apps=False).handle(
            legacy(2, 'resources/list'))['error']['code'], protocol.METHOD_NOT_FOUND)
        # A modern request on the same stdio process still decides by its own capabilities.
        self.assertNotIn('extensions', plain.handle(rpc('server/discover', meta=PLAIN))['result']['capabilities'])
        self.assertIn('extensions', plain.handle(rpc('server/discover'))['result']['capabilities'])

    def test_the_open_link_stays_on_this_machine(self):
        card = {'open': {'path': '/projects/prod-a/#cinema-studio'}}
        for base, url in (('http://127.0.0.1:3020', 'http://127.0.0.1:3020/projects/prod-a/#cinema-studio'),
                          ('http://localhost:3020/', 'http://localhost:3020/projects/prod-a/#cinema-studio'),
                          ('http://[::1]:3020', 'http://[::1]:3020/projects/prod-a/#cinema-studio')):
            with self.subTest(base=base):
                self.assertEqual(mcp_apps.with_link(card, base)['open']['url'], url)
        for base in (None, 'http://example.com:3020', 'https://127.0.0.1:3020', 'http://127.0.0.1.evil.example', 'http://user@127.0.0.1'):
            with self.subTest(base=base):
                self.assertNotIn('open', mcp_apps.with_link(card, base))
        self.assertNotIn('open', mcp_apps.with_link({'open': {'path': '//evil.example/x'}}, 'http://127.0.0.1:3020'))
        self.assertEqual(card, {'open': {'path': '/projects/prod-a/#cinema-studio'}})  # the backend's copy is untouched


class CardFileTests(unittest.TestCase):
    def setUp(self):
        self.html = mcp_apps.card_html()

    def policy(self):
        match = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', self.html)
        self.assertIsNotNone(match)
        return {part.split()[0]: part.split()[1:] for part in (p.strip() for p in match[1].split(';')) if part}

    def test_the_card_is_one_self_contained_html_file_with_no_external_url(self):
        self.assertTrue(self.html.lower().startswith('<!doctype html>'))
        self.assertEqual(re.findall(r'(?i)\b(?:https?|wss?|ftp|file):/', self.html), [])
        self.assertEqual(re.findall(r'(?i)(?:src|href|action|srcset|poster|data)\s*=\s*["\']?\s*/', self.html), [])
        for forbidden in ('<link', '<iframe', '<object', '<embed', '<base', '<form', '@import', '<svg', '<script src', 'innerHTML',
                          'outerHTML', 'insertAdjacentHTML', 'document.write', 'fetch(', 'XMLHttpRequest', 'WebSocket',
                          'EventSource', 'sendBeacon', 'import(', 'eval(', 'new Function', 'window.open', 'location.',
                          'localStorage', 'sessionStorage', 'document.cookie', 'Worker('):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden.lower(), self.html.lower())
        self.assertEqual(len(re.findall(r'<script\b', self.html)), 1)
        self.assertEqual(len(re.findall(r'<style\b', self.html)), 1)
        self.assertNotRegex(self.html, r'url\(\s*["\']?(?!["\']?\s*\$\{url\})')  # the only CSS url() is the data: image

    def test_a_strict_content_security_policy(self):
        policy = self.policy()
        self.assertEqual(policy['default-src'], ["'none'"])
        self.assertEqual(policy['script-src'], ["'unsafe-inline'"])
        self.assertEqual(policy['style-src'], ["'unsafe-inline'"])
        self.assertEqual(policy['img-src'], ['data:'])
        for directive in ('connect-src', 'font-src', 'media-src', 'frame-src', 'worker-src', 'form-action', 'base-uri'):
            with self.subTest(directive=directive):
                self.assertEqual(policy[directive], ["'none'"])
        self.assertEqual(mcp_apps.resource_meta(), {'ui': {'csp': {'connectDomains': [], 'resourceDomains': [], 'frameDomains': [],
                                                                    'baseUriDomains': []}, 'prefersBorder': True}})

    def test_the_card_speaks_the_mcp_apps_bridge(self):
        self.assertIn("const PROTOCOL = '2026-01-26'", self.html)
        self.assertEqual(mcp_apps.SPEC_VERSION, '2026-01-26')
        self.assertIn("window.parent.postMessage(message, '*')", self.html)
        self.assertIn('event.source !== window.parent', self.html)
        for method in ('ui/initialize', 'ui/notifications/initialized', 'ui/notifications/tool-input', 'ui/notifications/tool-result',
                       'ui/notifications/tool-cancelled', 'ui/notifications/host-context-changed', 'ui/resource-teardown',
                       'ui/notifications/size-changed', 'ui/open-link', 'resources/read', 'tools/call'):
            with self.subTest(method=method):
                self.assertIn(f"'{method}'", self.html)
        self.assertIn(f"const CARD_META = '{mcp_apps.CARD_META}'", self.html)
        self.assertIn(f"card.kind === '{mcp_apps.CARD_KIND}'", self.html)
        self.assertIn("name: 'read_shot'", self.html)  # the only tool the card calls, through the host

    def test_the_tiles_follow_the_contact_sheet_layout_of_previs_render(self):
        source = (ROOT / 'ui' / 'src' / 'previs' / 'previsRender.js').read_text(encoding='utf-8')
        match = re.search(r'export const SHEET = \{([^}]*)\}', source)
        sheet = {key.strip(): float(value) for key, value in (item.split(':') for item in match[1].split(','))}
        self.assertEqual({k: sheet[k] for k in mcp_apps.SHEET}, dict(mcp_apps.SHEET))
        self.assertEqual(mcp_apps.layout(1944, 818), {'columns': 3, 'rows': 2, 'header': 44, 'caption': 26, 'gap': 6,
                                                       'tileWidth': 640, 'tileHeight': 352})
        for size in ((1944, 819), (1945, 818), (10, 10), (None, 818), (1944.0, 818)):
            with self.subTest(size=size):
                self.assertIsNone(mcp_apps.layout(*size))

    def test_cards_name_exposed_tools_and_the_deferred_cards_are_not_served(self):
        for name in mcp_apps.TOOL_CARDS:
            with self.subTest(name=name):
                self.assertIn(name, tool_registry.ZEROFIELD_MCP)
                self.assertNotIn(name, tool_registry.GENERATION)
        everything = [t.name for t in tool_registry.all_tools()]
        self.assertEqual([r['uri'] for r in mcp_apps.resources_for(everything)], [mcp_apps.PREVIS_CARD])
        self.assertEqual(mcp_apps.resources_for(['read_page', 'request_generation']), [])
        self.assertEqual(set(mcp_apps.DEFERRED_CARDS), {'generation-desk', 'film-joins'})
        for name in mcp_apps.DEFERRED_CARDS:
            self.assertFalse(any(name in uri for uri in list(mcp_apps.CARDS) + list(mcp_apps.TOOL_CARDS.values())))
        with self.assertRaises(mcp_apps.NotFound):
            mcp_apps.read(None, {'project': 'prod-a'}, 'ui://zerofield/generation-desk.html', everything)
        package = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['tool']['setuptools']['package-data']
        self.assertIn('mcp_cards/*.html', package['project_assistant'])
        self.assertIn('recursive-include project_assistant/mcp_cards *.html', (ROOT / 'MANIFEST.in').read_text(encoding='utf-8'))

    def test_contact_sheet_uris(self):
        self.assertEqual(SHEET_URI, f'zerofield://shots/{SHOT}/previs-contact-sheets/{ASSET}.png')
        self.assertEqual(mcp_apps.CONTACT_SHEET.fullmatch(SHEET_URI).groups(), (SHOT, ASSET))
        for uri in (SHEET_URI.replace('.png', '.jpg'), SHEET_URI.replace('zerofield://', 'file://'), SHEET_URI + '?x=1',
                    f'zerofield://shots/{SHOT}/../x/previs-contact-sheets/{ASSET}.png', SHEET_URI.replace(ASSET, 'pa_' + 'A' * 32)):
            with self.subTest(uri=uri):
                self.assertIsNone(mcp_apps.CONTACT_SHEET.fullmatch(uri))
                with self.assertRaises(mcp_apps.NotFound):
                    mcp_apps.read(None, {'project': 'prod-a'}, uri, ['read_shot'])


# ---------- the database ----------

def seed_story(test):
    """A zerofield_studio production on the execution fixture's project: script, cast and storyboard (as test_previs_ops)."""
    from project_assistant import agent_registry
    from project_docs import markdown_import, repository as repo, story_openapi as story, templates
    from project_docs.doc_schema import validate_doc
    for key, title, surface, md in templates.tab_specs('zerofield_studio', 'MCP Apps Test', ''):
        doc, _ = markdown_import.markdown_to_doc(md, tab_keys=set(), image_src=lambda _: None)
        doc, _ = validate_doc(doc, slug=test.slug)
        templates.configure_doc(key, doc)
        repo.create_tab(test.conn, test.slug, key=key, title=title, parent_key=None, doc=doc, actor_id=test.actor, surface_type=surface)
    ep = f'ep_{test.slug}_01'
    for method, path, body in (('PUT', f'/episodes/{ep}/script', {'scriptContent': '## Scene 01: Observatory\n@CAST-01 turns to the dial as @CAST-02 waits.\n\n## Scene 02: Exit\n@CAST-01 leaves.'}),
                               ('POST', f'/episodes/{ep}/asset-extractions', {}), ('POST', f'/episodes/{ep}/storyboards', {})):
        story.dispatch(test.conn, test.me, method, path, body, {}, [])
    shots = [s for s in story.shots(test.conn, story.episode(test.conn, ep)) if s.get('sceneId') and s['tabKey'] == 'cinema-studio']
    agent_registry.ensure_default_agents(test.conn, test.slug)
    test.conn.commit()
    return shots


def other_png(tag):
    return b'\x89PNG\r\n\x1a\n' + tag.encode() + b'\x00' * 32


class StoryAccounts:
    """Service accounts and contact-sheet proposals on a seeded production (helpers only)."""

    def issue(self, key, tools):
        try:
            token = service_accounts.create(self.conn, self.me, self.slug, {'accountKey': key, 'tools': tools})['token']
            return service_accounts.authenticate(self.conn, token)
        finally:
            self.conn.commit()

    def solved(self, image=None):
        import test_previs_ops as previs
        result = previs.golden_result(previs.SEEDED)
        if image is not None:
            result['image'] = image
        return result

    def proposal(self, owner, image=None, shot=None):
        import test_previs_ops as previs
        from project_assistant import previs_ops
        body = {'shotId': (shot or self.shot)['shotId'], 'baseRevision': self.revision(shot), 'ops': previs.SEEDED['input']['ops']}
        proposal = previs_ops.propose_ops(self.conn, self.slug, owner, body, runner=previs.fake_runner(self.solved(image)), agent_key='sheet_ops')
        self.conn.commit()
        return proposal

    def revision(self, shot=None):
        from project_docs import story_openapi as story, story_previs
        state = story_previs.stored(story.shot_meta(self.conn, (shot or self.shot)['shotId']))
        self.conn.commit()
        return state['planRevision']

    def apply(self, proposal, me=None):
        from project_assistant import service
        code, payload = service.apply_proposal(self.conn, me or self.me, self.slug, proposal['id'], {})
        self.assertEqual(code, 200, payload)
        self.conn.commit()

    def audits(self, key):
        with self.conn.cursor() as cur:
            cur.execute('''SELECT detail FROM projectops.audit_log WHERE project_slug=%s AND action=%s AND target=%s ORDER BY id''',
                        (self.slug, service_accounts.CALL_ACTION, key))
            rows = [r[0] for r in cur.fetchall()]
        self.conn.commit()
        return rows


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'set OPENBENCH_TEST_DB_URI')
class CardDataTests(StoryAccounts, unittest.TestCase):
    def setUp(self):
        import psycopg
        import test_execution as execution_fixture
        execution_fixture.PostgreSQLExecutionTests.setUp(self)
        self.connect = lambda: psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI'])
        self.shot, self.other = seed_story(self)[:2]

    def tearDown(self):
        import test_execution as execution_fixture
        execution_fixture.PostgreSQLExecutionTests.tearDown(self)

    def read(self, account, uri):
        return service_accounts.read_resource(self.connect, account, uri, client=CLIENT)['contents'][0]

    def test_a_proposal_card_carries_the_proposal_and_its_contact_sheet_comes_in_the_result(self):
        import test_previs_ops as previs
        from project_assistant import headless_previs, store
        account = self.issue('desk', ['read_shot', 'propose_previs_ops'])
        args = {'shotId': self.shot['shotId'], 'baseRevision': 0, 'ops': previs.SEEDED['input']['ops']}
        with patch.object(headless_previs, 'run', previs.fake_runner(self.solved())):
            reply = service_accounts.call_tool(self.connect, account, 'propose_previs_ops', args, client=CLIENT, card=True)
            plain = service_accounts.call_tool(self.connect, account, 'propose_previs_ops', args)
        self.assertFalse(reply['isError'], reply)
        self.assertNotIn('card', plain)
        self.assertEqual(reply['images'], ['data:image/png;base64,' + base64.b64encode(previs.PNG).decode()])
        card = reply['card']
        proposal = store.proposal(self.conn, card['proposal']['id'])
        self.conn.commit()
        preview = proposal['target']['preview']
        self.assertEqual((card['kind'], card['source'], card['planRevision'], card['shot']['shotId'], card['shot']['tabKey']),
                         (mcp_apps.CARD_KIND, 'propose_previs_ops', 0, self.shot['shotId'], 'cinema-studio'))
        self.assertEqual(card['shot']['label'], self.shot['shotIndex'])
        self.assertEqual((card['proposal']['status'], card['proposal']['ops'], card['proposal']['summary']),
                         ('pending', args['ops'], proposal['content']))
        self.assertEqual(card['proposal']['solve']['status'], 'solved')
        self.assertIn('approves', card['note'])
        sheet = card['contactSheet']
        self.assertEqual((sheet['uri'], sheet['inContent'], len(sheet['frames']), sheet['layout']['tileWidth']),
                         (mcp_apps.sheet_uri(self.shot['shotId'], preview['assetId']), True, 6, 640))
        self.assertEqual(card['open']['path'], f'/projects/{self.slug}/#cinema-studio')
        self.assertEqual((card['plan']['lens'], card['plan']['move']), (proposal['target']['value']['lens'], proposal['target']['value']['move']))
        # The same image through resources/read, and the card itself.
        image = self.read(account, sheet['uri'])
        self.assertEqual((image['mimeType'], base64.b64decode(image['blob'])), ('image/png', previs.PNG))
        page = self.read(account, mcp_apps.PREVIS_CARD)
        self.assertEqual((page['mimeType'], page['_meta'], page['text']), (mcp_apps.MIME, mcp_apps.resource_meta(), mcp_apps.card_html()))
        rows = self.audits('desk')
        self.assertEqual([(r['tool'], r['outcome'], r.get('resource')) for r in rows],
                         [('propose_previs_ops', 'ok', None), ('propose_previs_ops', 'ok', None),
                          ('resources/read', 'ok', sheet['uri']), ('resources/read', 'ok', mcp_apps.PREVIS_CARD)])
        self.assertEqual(rows[-1]['client'], CLIENT)
        audit = service_accounts.audit_entries(self.conn, self.me, self.slug, 'desk')
        self.conn.commit()
        self.assertEqual(audit['items'][0]['resource'], mcp_apps.PREVIS_CARD)

    def test_a_read_shot_card_shows_the_stored_plans_contact_sheet_when_a_proposal_rendered_it(self):
        from project_docs import story_previs
        account = self.issue('reader', ['read_shot'])

        def card():
            reply = service_accounts.call_tool(self.connect, account, 'read_shot', {'shot_id': self.shot['shotId']}, card=True)
            self.assertFalse(reply['isError'], reply)
            self.assertEqual(json.loads(reply['text'])['data']['previs']['planRevision'], reply['card']['planRevision'])
            return reply['card']
        empty = card()
        self.assertEqual((empty['source'], empty['stored'], empty['contactSheet'], empty['planRevision']), ('read_shot', False, None, 0))
        self.assertIn('No 3D plan is stored', empty['note'])
        self.assertEqual(empty['shot']['label'], self.shot['shotIndex'])
        proposal = self.proposal(self.actor, image=other_png('stored'))
        sheet_uri = mcp_apps.sheet_uri(self.shot['shotId'], proposal['target']['preview']['assetId'])
        self.assertEqual(card()['contactSheet'], None)  # pending: the stored plan is still none
        self.apply(proposal)
        stored = card()
        self.assertEqual((stored['stored'], stored['planRevision'], stored['proposal']['id'], stored['proposal']['status']),
                         (True, 1, proposal['id'], 'applied'))
        self.assertEqual((stored['contactSheet']['uri'], stored['contactSheet']['inContent']), (sheet_uri, False))
        self.assertEqual(stored['plan']['lens'], proposal['target']['value']['lens'])
        self.assertEqual(base64.b64decode(self.read(account, sheet_uri)['blob']), other_png('stored'))
        # A plan saved in the 3D Stage afterwards has no contact sheet of its own: none is shown for it.
        story_previs.put(self.conn, self.slug, self.shot['shotId'], {**proposal['target']['value'], 'lens': 85}, 1, self.actor)
        self.conn.commit()
        saved = card()
        self.assertEqual((saved['planRevision'], saved['contactSheet'], saved['proposal']), (2, None, None))
        self.assertIn('saved in the 3D Stage', saved['note'])
        self.assertEqual(saved['plan']['lens'], 85)
        self.assertEqual(base64.b64decode(self.read(account, sheet_uri)['blob']), other_png('stored'))  # still an applied preview
        missing = service_accounts.call_tool(self.connect, account, 'read_shot', {'shot_id': f'sh_{self.slug}_bnothere'}, card=True)
        self.assertNotIn('card', missing)

    def test_resources_are_scoped_to_the_token_and_every_read_is_audited(self):
        from project_docs import repository as repo, service as docs_service
        own = self.proposal(self.actor, image=other_png('own'))
        crew = docs_service.Identity(str(uuid.uuid4()), 'Another crew member', 'admin')
        repo.upsert_member(self.conn, crew.actor_id, crew.name, crew.role)
        self.conn.commit()
        theirs = self.proposal(crew.actor_id, image=other_png('theirs'))
        uploaded = repo.put_asset(self.conn, self.slug, data=other_png('upload'), content_type='image/png', actor_id=self.actor)
        self.conn.commit()
        shot = self.shot['shotId']
        own_uri = mcp_apps.sheet_uri(shot, own['target']['preview']['assetId'])
        theirs_uri = mcp_apps.sheet_uri(shot, theirs['target']['preview']['assetId'])
        pages = self.issue('pages', ['read_page'])
        reader = self.issue('reader', ['read_shot'])
        self.assertEqual(service_accounts.visible_resources(pages), [])
        self.assertEqual([r['uri'] for r in service_accounts.visible_resources(reader)], [mcp_apps.PREVIS_CARD])

        def refused(account, uri):
            with self.assertRaises(AgentError) as caught:
                service_accounts.read_resource(self.connect, account, uri)
            self.assertEqual((caught.exception.status, caught.exception.code), (404, 'RESOURCE_NOT_FOUND'))
        for uri in (mcp_apps.PREVIS_CARD, own_uri):
            refused(pages, uri)
        self.assertEqual(base64.b64decode(self.read(reader, own_uri)['blob']), other_png('own'))  # the issuer's own proposal
        for uri in (theirs_uri,                                                       # someone else's pending proposal
                    mcp_apps.sheet_uri(self.other['shotId'], own['target']['preview']['assetId']),  # another shot
                    mcp_apps.sheet_uri(shot, uploaded),                               # an asset that is no contact sheet
                    mcp_apps.sheet_uri(f'sh_{self.slug}_bnothere', own['target']['preview']['assetId']),
                    mcp_apps.sheet_uri('sh_another-production_b1', own['target']['preview']['assetId']),
                    'ui://zerofield/generation-desk.html', 'zerofield://anything', 'https://example.com/x.png'):
            with self.subTest(uri=uri):
                refused(reader, uri)
        self.apply(theirs, crew)  # once applied, it is the stored plan's contact sheet: any token with read_shot may see it
        self.assertEqual(base64.b64decode(self.read(reader, theirs_uri)['blob']), other_png('theirs'))
        self.assertEqual([(r['tool'], r['outcome'], r['code']) for r in self.audits('pages')],
                         [('resources/read', 'denied', 'NOT_IN_SCOPE')] * 2)
        rows = self.audits('reader')
        self.assertEqual([(r['outcome'], r['code']) for r in rows],
                         [('ok', None)] + [('denied', 'NOT_FOUND')] * 8 + [('ok', None)])
        self.assertTrue(all(r['tool'] == 'resources/read' and r['resource'] for r in rows))
        self.assertEqual(service_accounts.usage(self.conn, self.slug, 'reader')['calls'], 10)
        self.conn.commit()


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'set OPENBENCH_TEST_DB_URI')
class AppsOverHttpTests(StoryAccounts, unittest.TestCase):
    """POST /mcp and zerofield-mcp (stdio over the agent API) answer an MCP Apps client the same way."""

    def setUp(self):
        import test_product_http as product_fixture
        self.fixture = product_fixture.ProductHTTPTests
        self.fixture.setUp(self)
        self.shot = seed_story(self)[0]

    def tearDown(self):
        self.fixture.tearDown(self)

    def request(self, *args, **kwargs):
        return self.fixture.request(self, *args, **kwargs)

    def agent(self, path, token, *, method='GET', data=None, headers=None):
        return self.request(path, method=method, data=data, authenticated=False,
                            headers={'Authorization': 'Bearer ' + token, **(headers or {})})

    def http(self, message, token, headers=None):
        params = message.get('params') or {}
        sent = {'Content-Type': 'application/json', 'Accept': 'application/json', 'Authorization': 'Bearer ' + token}
        if protocol.META_VERSION in (params.get('_meta') or {}):
            sent.update({'MCP-Protocol-Version': params['_meta'][protocol.META_VERSION], 'Mcp-Method': message['method']})
            if message['method'] in ('tools/call', 'resources/read'):
                sent['Mcp-Name'] = params['name' if message['method'] == 'tools/call' else 'uri']
        sent.update(headers or {})
        connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=30)
        try:
            connection.request('POST', '/mcp', body=json.dumps(message).encode(), headers=sent)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_both_transports_serve_cards_resources_and_the_same_answers(self):
        import test_previs_ops as previs
        from project_assistant import headless_previs
        proposal = self.proposal(self.actor, image=other_png('http'))
        self.apply(proposal)
        code, issued, _ = self.request(f'/projects/api/{self.slug}/service-accounts', method='POST',
                                       data={'accountKey': 'apps', 'tools': ['read_shot', 'propose_previs_ops', 'read_page']})
        self.assertEqual(code, 200, issued)
        token = issued['token']
        base = f'http://127.0.0.1:{self.server.server_port}'
        stdio = mcp.Server(mcp.HttpBackend(base, token, self.slug, timeout=30), url=base)
        sheet_uri = mcp_apps.sheet_uri(self.shot['shotId'], proposal['target']['preview']['assetId'])
        messages = [rpc('server/discover', 1), rpc('tools/list', 2), rpc('resources/list', 3),
                    rpc('tools/call', 4, name='read_shot', arguments={'shot_id': self.shot['shotId']}),
                    rpc('resources/read', 5, uri=mcp_apps.PREVIS_CARD), rpc('resources/read', 6, uri=sheet_uri),
                    rpc('resources/read', 7, uri=mcp_apps.sheet_uri(self.shot['shotId'], 'pa_' + 'b' * 32)),
                    rpc('tools/call', 8, meta=PLAIN, name='read_shot', arguments={'shot_id': self.shot['shotId']})]
        replies = {}
        for message in messages:
            with self.subTest(method=message['method'], id=message['id']):
                status, reply = self.http(message, token)
                self.assertEqual(status, 200, reply)
                self.assertEqual(reply, stdio.handle(message))
                replies[message['id']] = reply
        self.assertIn(mcp_apps.EXTENSION, replies[1]['result']['capabilities']['extensions'])
        tools = {t['name']: t for t in replies[2]['result']['tools']}
        self.assertEqual(tools['read_shot']['_meta']['ui']['resourceUri'], mcp_apps.PREVIS_CARD)
        self.assertEqual(tools['propose_previs_ops']['_meta']['ui']['resourceUri'], mcp_apps.PREVIS_CARD)
        self.assertNotIn('_meta', tools['read_page'])
        card = replies[4]['result']['_meta'][mcp_apps.CARD_META]
        self.assertEqual((card['planRevision'], card['contactSheet']['uri']), (1, sheet_uri))
        self.assertEqual(card['open']['url'], f'{base}/projects/{self.slug}/#cinema-studio')
        page = replies[5]['result']['contents'][0]
        self.assertEqual((page['mimeType'], page['text']), ('text/html;profile=mcp-app', mcp_apps.card_html()))
        self.assertEqual(base64.b64decode(replies[6]['result']['contents'][0]['blob']), other_png('http'))
        self.assertEqual((replies[7]['error']['code'], replies[7]['error']['data']),
                         (protocol.RESOURCE_NOT_FOUND, {'uri': mcp_apps.sheet_uri(self.shot['shotId'], 'pa_' + 'b' * 32)}))
        self.assertNotIn(mcp_apps.CARD_META, replies[8]['result']['_meta'])  # a client without MCP Apps gets no card
        # A proposal over HTTP brings its contact sheet as an image block next to the card.
        args = {'shotId': self.shot['shotId'], 'baseRevision': 1, 'ops': previs.SEEDED['input']['ops']}
        with patch.object(headless_previs, 'run', previs.fake_runner(self.solved(other_png('fresh')))):
            status, made = self.http(rpc('tools/call', 9, name='propose_previs_ops', arguments=args), token)
        self.assertEqual(status, 200, made)
        result = made['result']
        self.assertFalse(result['isError'], result)
        self.assertEqual(result['content'][1], {'type': 'image', 'mimeType': 'image/png', 'data': base64.b64encode(other_png('fresh')).decode()})
        fresh = result['_meta'][mcp_apps.CARD_META]
        self.assertEqual((fresh['source'], fresh['proposal']['status'], fresh['contactSheet']['inContent']), ('propose_previs_ops', 'pending', True))
        # The legacy handshake over HTTP offers no cards: no session would remember it.
        initialize = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                      'params': {'protocolVersion': '2025-11-25', 'capabilities': APPS_CAPS, 'clientInfo': CLIENT}}
        status, init = self.http(initialize, token)
        self.assertEqual((status, init['result']['capabilities']), (200, {'tools': {'listChanged': False}}))
        status, listing = self.http({'jsonrpc': '2.0', 'id': 2, 'method': 'resources/list'}, token, {'MCP-Protocol-Version': '2025-11-25'})
        self.assertEqual(listing['error']['code'], protocol.METHOD_NOT_FOUND)
        rows = [(r['tool'], r['outcome'], r.get('resource')) for r in self.audits('apps')]
        self.assertEqual(rows.count(('resources/read', 'ok', mcp_apps.PREVIS_CARD)), 2)  # HTTP, then stdio
        self.assertEqual(rows.count(('resources/read', 'ok', sheet_uri)), 2)
        self.assertEqual([r[1] for r in rows if r[0] == 'resources/read' and r[2] not in (mcp_apps.PREVIS_CARD, sheet_uri)], ['denied'] * 2)
        # The agent API's own routes: local only, token required, wrong method refused.
        self.assertEqual(self.agent('/agent-mcp/v1/resources', token)[1]['resources'][0]['uri'], mcp_apps.PREVIS_CARD)
        self.assertEqual(self.agent('/agent-mcp/v1/resources', token, headers={'Origin': 'http://evil.example'})[1]['code'], 'LOCAL_ONLY')
        self.assertEqual(self.agent('/agent-mcp/v1/resources/read', token)[0], 405)
        self.assertEqual(self.agent('/agent-mcp/v1/resources/read', token, method='POST', data={'uri': 7})[0], 400)
        self.assertEqual(self.request('/agent-mcp/v1/resources', authenticated=False)[0], 401)


if __name__ == '__main__':
    unittest.main()
