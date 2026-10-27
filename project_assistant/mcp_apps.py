"""MCP Apps cards for external agents (SPEC_20 R34, decision 9): the 3D preview contact sheet.

MCP Apps (extension ``io.modelcontextprotocol/ui``, specification 2026-01-26) is the first official MCP extension. A
tool names a ``ui://`` resource in ``_meta.ui.resourceUri``; a host that supports the extension reads that resource
(``resources/read``, MIME type ``text/html;profile=mcp-app``) and renders it in a sandboxed iframe beside the tool's
result. The card and the host talk JSON-RPC over postMessage: ``ui/initialize``, ``ui/notifications/tool-result``,
``ui/open-link``, and the standard ``tools/call`` and ``resources/read``, which the host forwards to this server over
its own connection, so every request a card makes carries the host's service-account token and is scoped and audited
like any other.

The protocol layer (``project_assistant.mcp_protocol``) negotiates; this module is the content:

- **Negotiation.** A client supports MCP Apps when its capabilities list ``text/html;profile=mcp-app`` under
  ``extensions["io.modelcontextprotocol/ui"].mimeTypes``: per request in 2026-07-28, in ``initialize`` for the legacy
  handshake (stdio only; the stateless Streamable HTTP endpoint keeps no session to remember a legacy handshake). Only
  then does the server advertise the extension and ``resources``, attach ``_meta.ui.resourceUri`` to the tools in
  ``TOOL_CARDS``, answer ``resources/*`` and put the card's data on the tool result. Every other client gets exactly
  what it got before: text content, the image block and ``structuredContent``.
- **One card now: the 3D preview contact sheet** (``PREVIS_CARD``) for ``read_shot`` and ``propose_previs_ops``. A
  self-contained HTML page (``mcp_cards/previs_contact_sheet.html``: inline script and style, no network, a strict
  Content-Security-Policy) showing the shot label, the plan revision, the six frames, the operations and the state of
  a proposal. The card's data travels on the tool result as ``_meta["zerofield/card"]`` (MCP Apps: result ``_meta`` is
  for the view, not the model).
- **How the image reaches it.** ``propose_previs_ops`` already returns the contact sheet as an image content block,
  which the card shows as a ``data:`` URL. For ``read_shot`` the card asks the host to ``resources/read``
  ``zerofield://shots/<shotId>/previs-contact-sheets/<assetId>.png`` (a base64 ``blob``): the contact sheet the
  approved proposal rendered for the stored plan, matched by content. The sandboxed card never gets a URL of the
  ZeroField server and never loads anything by itself.
- **Scope.** A resource is served only to a token that may call one of its related tools (``RESOURCE_TOOLS``), and a
  contact sheet only when it is the preview of a 3D plan proposal for that shot in the token's production that was
  applied or belongs to the token's issuing showrunner. Reads are audited and rate limited like tool calls
  (``service_accounts.read_resource``).
- **Actions.** "Open in ZeroField" asks the host to show a link to the production's sheet (``ui/open-link``; the
  person's own sign-in applies, no token is in it); "Refresh" re-calls ``read_shot`` through the host bridge.

Deferred (``DEFERRED_CARDS``): decision 9 names three cards. The generation-desk summary and the film joins cards need
SPEC_19's generation desk and film panel, which are not on this branch; they have no URI, no resource and no tool
link until then, so no host is shown a card that cannot work.

This module imports only the standard library at load time: the zero-dependency stdio server imports it through
``mcp_protocol``. Database reads import their modules when called.
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from types import MappingProxyType

EXTENSION = 'io.modelcontextprotocol/ui'
MIME = 'text/html;profile=mcp-app'
SPEC_VERSION = '2026-01-26'
CARD_META = 'zerofield/card'          # the card's data on a tools/call result's _meta (for the view, not the model)
PREVIS_CARD = 'ui://zerofield/previs-contact-sheet.html'
CARD_KIND = 'previs_contact_sheet'
CARD_VERSION = 1

TOOL_CARDS = MappingProxyType({'read_shot': PREVIS_CARD, 'propose_previs_ops': PREVIS_CARD})
CARDS = MappingProxyType({
    PREVIS_CARD: {'file': 'previs_contact_sheet.html', 'name': 'previs-contact-sheet', 'title': '3D preview contact sheet',
                  'description': 'A shot\'s 3D previs contact sheet: six frames, the plan revision and, for a proposal, its '
                                 'operations and state. Rendered by MCP Apps hosts for read_shot and propose_previs_ops.'},
})
RESOURCE_TOOLS = MappingProxyType({PREVIS_CARD: frozenset({'read_shot', 'propose_previs_ops'})})
SHEET_TOOLS = frozenset({'read_shot', 'propose_previs_ops'})  # who may read a contact sheet image resource
# SPEC_20 decision 9's other two cards wait for SPEC_19 (see the module docstring). Documentation only: never listed,
# served or attached to a tool.
DEFERRED_CARDS = MappingProxyType({
    'generation-desk': 'Generation-desk summary: needs SPEC_19\'s shot composer (generation desk) on this branch.',
    'film-joins': 'Film joins: needs SPEC_19\'s film panel and its joins on this branch.',
})

# ui/src/previs/previsRender.js SHEET (tests/test_mcp_apps.py reads the JS and compares): how the six frames sit in the
# contact sheet, so the card can show them as tiles.
SHEET = MappingProxyType({'columns': 3, 'rows': 2, 'header': 44, 'caption': 26, 'gap': 6})
CONTACT_SHEET = re.compile(r'zerofield://shots/(sh_[a-z0-9-]{1,41}_b[A-Za-z0-9_-]{1,120})/previs-contact-sheets/(pa_[0-9a-f]{32})\.png')
ASSET_ID = re.compile(r'pa_[0-9a-f]{32}')
TAB_KEY = re.compile(r'[a-z0-9][a-z0-9-]{0,40}')
LOCAL_BASE = re.compile(r'http://(?:127\.0\.0\.1|localhost|\[::1\])(?::\d{1,5})?/?')
APPLIED = 'applied'
LOOKUP = 20  # applied 3D plan proposals of one shot searched for the stored plan's contact sheet
CARD_DIR = Path(__file__).resolve().parent / 'mcp_cards'
PROPOSAL = re.compile(r'Proposal #(\d+)')
STATE_NOTES = {
    'pending': 'Nothing is written until the director approves it in the 3D Stage.',
    'applied': 'Approved: this plan was written to the shot.',
}


class NotFound(LookupError):
    """A resource this token may not read or that does not exist; both answer the same 404."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


# ---------- negotiation ----------

def supported(capabilities) -> bool:
    """Whether client capabilities accept MCP Apps HTML views (extensions[EXTENSION].mimeTypes lists MIME)."""
    extensions = capabilities.get('extensions') if isinstance(capabilities, dict) else None
    settings = extensions.get(EXTENSION) if isinstance(extensions, dict) else None
    types = settings.get('mimeTypes') if isinstance(settings, dict) else None
    return isinstance(types, list) and MIME in types


def tool_meta(name):
    """The MCP Apps _meta of a tool with a card, else None. The flat "ui/resourceUri" key is the extension's deprecated
    form, kept for hosts that predate _meta.ui."""
    uri = TOOL_CARDS.get(name)
    return {'ui': {'resourceUri': uri}, 'ui/resourceUri': uri} if uri else None


def with_link(card, base):
    """The card with its "Open in ZeroField" link made absolute on a local http base URL; without one, no link."""
    card = json.loads(json.dumps(card))
    link = card.get('open') if isinstance(card.get('open'), dict) else None
    if link is not None:
        path = link.get('path')
        if isinstance(base, str) and LOCAL_BASE.fullmatch(base) and isinstance(path, str) and path.startswith('/projects/'):
            link['url'] = base.rstrip('/') + path
        else:
            card.pop('open')
    return card


# ---------- resources ----------

def resource_meta():
    """The card resource's _meta.ui: no external origin of any kind (the host's restrictive default CSP stands)."""
    return {'ui': {'csp': {'connectDomains': [], 'resourceDomains': [], 'frameDomains': [], 'baseUriDomains': []},
                   'prefersBorder': True}}


def card_html(uri=PREVIS_CARD) -> str:
    return (CARD_DIR / CARDS[uri]['file']).read_text(encoding='utf-8')


def resources_for(tool_names) -> list[dict]:
    """The UI resources a token that sees tool_names may list (contact sheets are found through the card, not listed)."""
    names = set(tool_names)
    return [{'uri': uri, 'name': card['name'], 'title': card['title'], 'description': card['description'], 'mimeType': MIME}
            for uri, card in CARDS.items() if names & RESOURCE_TOOLS[uri]]


def sheet_uri(shot_id, asset_id):
    return f'zerofield://shots/{shot_id}/previs-contact-sheets/{asset_id}.png'


def read(conn, account, uri, tool_names) -> list[dict]:
    """The contents of one resource for an authenticated account, else NotFound (code NOT_IN_SCOPE or NOT_FOUND)."""
    names = set(tool_names)
    if uri in CARDS:
        if not names & RESOURCE_TOOLS[uri]:
            raise NotFound('NOT_IN_SCOPE')
        return [{'uri': uri, 'mimeType': MIME, 'text': card_html(uri), '_meta': resource_meta()}]
    match = CONTACT_SHEET.fullmatch(uri) if isinstance(uri, str) else None
    if not match:
        raise NotFound('NOT_FOUND')
    if not names & SHEET_TOOLS:
        raise NotFound('NOT_IN_SCOPE')
    shot_id, asset_id = match.groups()
    if not sheet_visible(conn, account, shot_id, asset_id):
        raise NotFound('NOT_FOUND')
    from project_docs import repository as repo
    found = repo.get_asset(conn, account['project'], asset_id)
    if not found or found[0] != 'image/png' or not bytes(found[1]).startswith(b'\x89PNG\r\n\x1a\n'):
        raise NotFound('NOT_FOUND')
    return [{'uri': uri, 'mimeType': 'image/png', 'blob': base64.b64encode(bytes(found[1])).decode('ascii')}]


def sheet_visible(conn, account, shot_id, asset_id) -> bool:
    """A contact sheet is readable when it is the preview of a 3D plan proposal for this shot of the token's production,
    and that proposal was applied (the plan it shows was written) or belongs to the token's issuing showrunner."""
    from project_assistant import shot_meta
    from project_docs import story_previs
    slug = account['project']
    if shot_meta._shot_row(conn, slug, shot_id) is None:
        return False
    owner = (account.get('issuer') or {}).get('actor_id')
    with conn.cursor() as cur:
        cur.execute('''SELECT 1 FROM projectops.assistant_proposal
                       WHERE project_slug=%s AND action=%s AND target->>'shotId'=%s AND target->>'field'=%s
                         AND target->'preview'->>'assetId'=%s AND (status=%s OR owner_id::text=%s) LIMIT 1''',
                    (slug, shot_meta.ACTION, shot_id, story_previs.FIELD, asset_id, APPLIED, str(owner or '')))
        return cur.fetchone() is not None


# ---------- the card's data ----------

def layout(width, height):
    """Where the six frames sit in a contact sheet of this size (previsRender.js SHEET), or None when it does not fit."""
    if type(width) is not int or type(height) is not int:
        return None
    columns, rows, header, caption, gap = (SHEET[k] for k in ('columns', 'rows', 'header', 'caption', 'gap'))
    tile_w, rest_w = divmod(width - (columns + 1) * gap, columns)
    tile_h, rest_h = divmod(height - header - rows * caption - (rows + 1) * gap, rows)
    if tile_w <= 0 or tile_h <= 0 or rest_w or rest_h:
        return None
    return {'columns': columns, 'rows': rows, 'header': header, 'caption': caption, 'gap': gap,
            'tileWidth': tile_w, 'tileHeight': tile_h}


def _sheet(shot_id, preview, *, in_content):
    if not isinstance(preview, dict) or not isinstance(preview.get('assetId'), str) or not ASSET_ID.fullmatch(preview['assetId']):
        return None
    frames = [{'frame': f.get('frame'), 'seconds': f.get('seconds')} for f in preview.get('frames') or [] if isinstance(f, dict)]
    return {'uri': sheet_uri(shot_id, preview['assetId']), 'mimeType': 'image/png', 'inContent': in_content,
            'width': preview.get('width'), 'height': preview.get('height'), 'frames': frames[:12],
            'layout': layout(preview.get('width'), preview.get('height'))}


def _facts(plan):
    """What the card says about a plan: set, camera, length, light and who is on set (structure, never text)."""
    if not isinstance(plan, dict):
        return None
    cast = [plan.get('code')] + [m.get('code') for m in plan.get('cast') or [] if isinstance(m, dict)]
    return {'set': plan.get('set'), 'lens': plan.get('lens'), 'move': plan.get('move'), 'seconds': plan.get('seconds'),
            'mood': plan.get('mood'), 'cast': [code for code in cast if isinstance(code, str) and code][:8],
            'keys': len(plan.get('keys') or []) if isinstance(plan.get('keys'), list) else 0}


def _solve(solve):
    if not isinstance(solve, dict):
        return None
    out = {key: solve.get(key) for key in ('status', 'by', 'reason') if isinstance(solve.get(key), str)}
    out['warnings'] = [str(w)[:300] for w in solve.get('warnings') or []][:8]
    return out


def _open(slug, tab):
    return {'path': f'/projects/{slug}/' + (f'#{tab}' if isinstance(tab, str) and TAB_KEY.fullmatch(tab) else ''),
            'label': 'Open in ZeroField'}


def _proposal_card(conn, account, text):
    """The card of a propose_previs_ops result: the proposal this call made (owned by the token's issuer)."""
    from project_assistant import shot_meta, store
    match = PROPOSAL.search(text or '')
    proposal = store.proposal(conn, int(match[1])) if match else None
    owner = (account.get('issuer') or {}).get('actor_id')
    if (not proposal or proposal['slug'] != account['project'] or proposal['action'] != shot_meta.ACTION
            or str(proposal['owner_id']) != str(owner)):
        return None
    target = proposal.get('target') or {}
    shot = target.get('shot') or {}
    status = proposal.get('status')
    return {'kind': CARD_KIND, 'version': CARD_VERSION, 'source': 'propose_previs_ops',
            'shot': {'shotId': target.get('shotId'), 'label': shot.get('label') or target.get('shotId'), 'tabKey': shot.get('tabKey')},
            'planRevision': target.get('baseRevision'),
            'proposal': {'id': proposal['id'], 'status': status, 'summary': proposal.get('content') or '',
                         'baseRevision': target.get('baseRevision'), 'ops': target.get('ops') or [], 'solve': _solve(target.get('solve'))},
            'plan': _facts(target.get('value')),
            'contactSheet': _sheet(target.get('shotId'), target.get('preview'), in_content=True),
            'note': STATE_NOTES.get(status, f'This proposal is {status}.'),
            'open': _open(account['project'], shot.get('tabKey'))}


def _stored_sheet(conn, slug, shot_id, plan):
    """The newest applied 3D plan proposal of this shot whose plan is exactly the stored one, with its preview."""
    from project_assistant import shot_meta
    from project_docs import story_previs
    wanted = story_previs.canonical(plan)
    with conn.cursor() as cur:
        cur.execute('''SELECT id, content, target FROM projectops.assistant_proposal
                       WHERE project_slug=%s AND action=%s AND status=%s AND target->>'shotId'=%s AND target->>'field'=%s
                         AND target->'preview'->>'assetId' IS NOT NULL ORDER BY id DESC LIMIT %s''',
                    (slug, shot_meta.ACTION, APPLIED, shot_id, story_previs.FIELD, LOOKUP))
        rows = cur.fetchall()
    for proposal_id, content, target in rows:
        target = target if isinstance(target, dict) else json.loads(target or '{}')
        if story_previs.canonical(target.get('value')) == wanted:
            return proposal_id, content, target
    return None


def _shot_card(conn, account, args, text):
    """The card of a read_shot result: the stored plan's revision and, when an applied proposal rendered it, its sheet."""
    from project_assistant import shot_meta
    from project_docs import story_openapi as story, story_previs
    try:
        envelope = json.loads(text)
    except (TypeError, ValueError):
        return None
    data = envelope.get('data') if isinstance(envelope, dict) else None
    if not isinstance(data, dict):
        return None
    shot = data.get('shot') if isinstance(data.get('shot'), dict) else {}
    previs = data.get('previs') if isinstance(data.get('previs'), dict) else {}
    shot_id = shot.get('shotId') or args.get('shot_id')
    slug = account['project']
    if not isinstance(shot_id, str) or shot_meta._shot_row(conn, slug, shot_id) is None:
        return None
    state = story_previs.stored(story.shot_meta(conn, shot_id))
    revision = previs.get('planRevision', state['planRevision'])
    card = {'kind': CARD_KIND, 'version': CARD_VERSION, 'source': 'read_shot',
            'shot': {'shotId': shot_id, 'label': shot.get('shotIndex') or shot_id, 'tabKey': shot.get('tabKey')},
            'planRevision': revision, 'stored': bool(previs.get('stored')), 'plan': None, 'proposal': None,
            'contactSheet': None, 'note': None, 'open': _open(slug, shot.get('tabKey'))}
    if not card['stored']:
        card['note'] = 'No 3D plan is stored for this shot yet; the 3D Stage shows the storyboard seed.'
        return card
    if state['planRevision'] != revision or state['plan'] is None:
        card['note'] = 'The stored 3D plan changed after this read; read the shot again.'
        return card
    card['plan'] = _facts(state['plan'])
    found = _stored_sheet(conn, slug, shot_id, state['plan'])
    if found is None:
        card['note'] = ('No contact sheet for this revision: it was saved in the 3D Stage, not rendered from a proposal. '
                        'Open the shot in ZeroField, or propose operations to render one.')
        return card
    proposal_id, content, target = found
    card['proposal'] = {'id': proposal_id, 'status': APPLIED, 'summary': content or '', 'baseRevision': target.get('baseRevision'),
                        'ops': target.get('ops') or [], 'solve': _solve(target.get('solve'))}
    card['contactSheet'] = _sheet(shot_id, target.get('preview'), in_content=False)
    card['note'] = 'The stored plan, as rendered when its proposal was approved.'
    return card


BUILDERS = {'propose_previs_ops': lambda conn, account, args, text: _proposal_card(conn, account, text),
            'read_shot': _shot_card}


def card_for(connection_factory, account, name, args, text):
    """The card data for one successful tool result, read in its own short read-only transaction; None when the tool
    has no card or the data is not there. Never fails the tool call."""
    builder = BUILDERS.get(name)
    if builder is None:
        return None
    conn = connection_factory()
    try:
        return builder(conn, account, args if isinstance(args, dict) else {}, text)
    except Exception as exc:  # noqa: BLE001 - the text result stands without a card
        print(f'zerofield-mcp: card for {name} failed: {type(exc).__name__}: {exc}', flush=True)
        return None
    finally:
        try:
            conn.rollback()
        finally:
            conn.close()
