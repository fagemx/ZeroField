"""Structured context tools for the crew (SPEC_20 R16): read_episode, read_scene, read_shot, read_cast, list_takes.

Before these, the crew could only page through a sheet as text with read_page (about 5800 characters at a time) and
saw nothing of the story model behind it: shot meta, scenes, the episode's structure, cast looks, the stored 3D plan,
neighbouring shots or take grades. These tools read that model through the story modules' own read functions
(story_openapi, story_previs, take_grader) and never change production data.

Every call returns the result envelope of SPEC_20 §4.5 as compact JSON:

    {"status": "ok" | "partial" | "not_found",
     "data": {...} | null,               bounded, privacy-sanitized content
     "sources": [{"kind", "id", ...}],   what was read: tabs with their revision, episode/scene/shot/asset/grade ids,
                                          a shot's meta with its 3D planRevision
     "warnings": [str],                  facts about the data worth knowing (unconfirmed script, missing references)
     "limitations": [str],               what was truncated or left out, and where to read the rest ("partial")
     "hash": "sha256:<hex>"}             of data as canonical JSON: a later proposal can pin exactly what was seen

and writes one audit_log record (action agent_context_read, the hash and sources in its detail) in the tool call's
transaction. A result never exceeds MAX_CHARS: text is cut to stated lengths and long lists are shortened, each
noted in limitations. An id of another production reads as not_found, never as that production's data.

Privacy follows the existing read tools: credentials are redacted from production text in every production, numbers
in it are masked in a mask_numbers production, structural fields (ids, codes, statuses, revisions, 3D plan geometry)
are kept, and only this production's asset URLs are returned. Project membership, the agent's grants and per-tool
policies are enforced before a handler runs (agent_policy.authorize_tool).

Default grants reach only newly seeded agents; top_up_grants gives the existing built-in crew the read-only tools of
this category, and the proposal-only crew tools (tool_registry.proposal_only), once each, and never adds a tool that
writes or spends directly. These tools are also the read surface of the MCP server (§4.7), so
they depend on nothing but the ToolContext fields every transport sets.
"""
from __future__ import annotations

import hashlib
import json
import re

from project_assistant import privacy, store, tool_registry
from project_assistant.masking import guard_input
from project_docs import repository as repo, story_openapi as story, story_previs

AUDIT_ACTION = 'agent_context_read'
TOPUP_ACTION = 'agent_tool_topup'
TOPUP_SETTING = 'crew_context_tools_offered'  # {agent_key: [tool names already offered]}
PROPOSAL_TOPUP_SETTING = 'crew_proposal_tools_offered'  # the same, for proposal-only tools (SPEC_20 R21-R23)
CATEGORY = 'context'
PROPOSAL_CATEGORY = 'proposal'  # the audit detail's category for proposal-only top-ups
MAX_CHARS = 9000      # the whole envelope as compact JSON; tools.call neither clips nor re-masks these results
PLAN_CHARS = 3000     # a stored 3D plan longer than this (as compact JSON) is summarised
TAKES_SHOWN = 20
SHOT_TABS = ('cinema-studio', 'openjutsu-lab')
CAST_TAB = 'soul-cast'

_SHOT_ID = re.compile(r'sh_([a-z0-9-]{1,41})_(b[A-Za-z0-9_-]+)')
_ASSET_ID = re.compile(r'as_([a-z0-9-]{1,41})_(b[A-Za-z0-9_-]+)')
_EPISODE_ID = re.compile(r'ep_([a-z0-9-]{1,41})_(\d+)')
_SCENE_ID = re.compile(r'sc_([a-z0-9-]{1,41})_(\d+)_S\d+')
_MEDIA_CELL = re.compile(r'\s*(?:!?\[[^\]\n]*\]\(\s*(\S+?)\s*\)|((?:/projects/api/|https?://)\S+))\s*')
_ASSET_KEY = re.compile(r'pa_[0-9a-f]{32}')  # a take's asset id, as take_grader records it
# Strings under these keys are identifiers, codes, enum values or timestamps: never masked. Everything else is
# production text and goes through the same guard as the page reader.
_STRUCTURAL = frozenset({
    'shotId', 'rowId', 'tableId', 'tabKey', 'episodeId', 'sceneId', 'assetId', 'variantId', 'gradeId', 'takeId',
    'assetCode', 'code', 'assets', 'missingAssets', 'missingAssetCodes', 'shotIds', 'sceneIds', 'previousSceneId',
    'nextSceneId', 'status', 'reviewStatus', 'kind', 'type', 'planDetail', 'updatedAt', 'updatedBy', 'requestedAt',
    'gradedAt', 'provenance', 'model', 'aspectRatio', 'stylePresetId', 'breakdownMode', 'requested'})
_PLAN_SCALARS = ('set', 'move', 'lens', 'action', 'facing', 'mood', 'seconds', 'code', 'mark', 'turn', 'easing', 'figure',
                 'fix', 'beacon', 'presentation')
_PLAN_LISTS = ('keys', 'cast', 'acts', 'pins', 'use', 'layers', 'props')


def _dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def content_hash(data):
    """sha256 of data as canonical JSON (sorted keys): equal content, equal hash."""
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    return 'sha256:' + hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _natural(label):
    """The episode film's shot order (story_openapi.film_shots): S2 before S10, S03A after S03."""
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold()) for part in re.split(r'(\d+)', str(label)))


class _Read:
    """One tool call: what it read, what it noticed and what it left out."""

    def __init__(self, ctx, conn, tool, args):
        self.ctx, self.conn, self.tool, self.args = ctx, conn, tool, args
        self.slug = ctx.slug
        self.mode = privacy.mode(conn, ctx.slug)
        self.sources, self.warnings, self.limitations = [], [], {}
        self._revisions = None
        self._assets = None

    # ---------- bookkeeping ----------

    def tab(self, key):
        if self._revisions is None:
            self._revisions = {t['key']: t['revision'] for t in repo.list_tabs(self.conn, self.slug)}
        self.source('tab', key, revision=self._revisions.get(key))

    def source(self, kind, identifier, **extra):
        entry = {'kind': kind, 'id': identifier, **extra}
        if entry not in self.sources:
            self.sources.append(entry)

    def warn(self, message):
        if message not in self.warnings:
            self.warnings.append(message)

    def limit(self, key, message):
        self.limitations[key] = message

    def text(self, value, limit, key=None, note=None):
        """Production text, sanitized first (a cut must not split a credential out of reach), then cut to limit."""
        value = self.prose('' if value is None else str(value))
        if len(value) <= limit:
            return value
        self.limit(key or 'short_fields', note or 'Some short fields (names, titles, optics, voice) were cut to fit.')
        return value[:limit].rstrip() + '…'

    def prose(self, value):
        return guard_input(value, mask_numbers=self.mode == 'mask_numbers')[0]

    def own_url(self, value):
        return value if isinstance(value, str) and re.fullmatch(
            r'/projects/api/' + re.escape(self.slug) + r'/assets/pa_[0-9a-f]{32}', value) else None

    # ---------- shared story reads ----------

    def assets(self):
        """{asset code: asset view} of the cast sheet, looks included (CAST-01:NIGHT)."""
        if self._assets is None:
            self.tab(CAST_TAB)
            self._assets = {}
            for row in story.table_rows(self.conn, self.slug, CAST_TAB):
                view = story.asset_view(self.slug, row)
                self._assets.setdefault(view['assetCode'], view)
        return self._assets

    def cast_of(self, codes):
        known, cast, unknown = self.assets(), [], []
        for code in dict.fromkeys(codes):
            asset = known.get(code)
            if asset is None:
                unknown.append(code)
                continue
            cast.append({'assetCode': code, 'name': self.text(asset['name'], 120), 'type': asset['type'],
                         'selectedImageUrl': asset['selectedImageUrl']})
        if unknown:
            self.warn('Referenced but not on the cast sheet: ' + ', '.join(unknown) + '.')
        return cast

    # ---------- the envelope ----------

    def finish(self, data, target, shrinkers=(), status=None):
        if data is not None:
            data = _sanitize(data, self)
        shrinkers = list(shrinkers)
        while True:
            envelope = self.envelope(data, status)
            text = _dumps(envelope)
            if len(text) <= MAX_CHARS or data is None:
                break
            if not shrinkers:
                data, status = None, 'partial'
                self.limitations = {'size': f'The result was larger than {MAX_CHARS} characters even after shortening; '
                                            'ask for a narrower read (one scene, one shot, one asset).'}
                continue
            outcome = shrinkers[0](data)
            if outcome is None:
                shrinkers.pop(0)
            else:
                self.limit(*outcome)
        repo.add_audit(self.conn, self.slug, action=AUDIT_ACTION, actor_id=self.ctx.me.actor_id, target=target, detail={
            'tool': self.tool, 'agentKey': getattr(self.ctx, 'agent_key', None),
            'arguments': privacy.sanitize(self.args, self.mode), 'status': envelope['status'], 'hash': envelope['hash'],
            'sources': envelope['sources'], 'limitations': len(envelope['limitations']),
            'messageId': getattr(self.ctx, 'message_id', None), 'dispatchId': getattr(self.ctx, 'dispatch_id', None),
            'runId': getattr(self.ctx, 'run_id', None)})
        return text

    def envelope(self, data, status=None):
        status = status or ('not_found' if data is None else 'partial' if self.limitations else 'ok')
        return {'status': status, 'data': data, 'sources': self.sources,
                'warnings': [self.prose(w) for w in self.warnings], 'limitations': list(self.limitations.values()),
                'hash': content_hash(data)}

    def not_found(self, target, message):
        self.warn(message)
        return self.finish(None, target, status='not_found')


def _sanitize(value, read, key=None):
    """Mask production text, keep structure, and keep only this production's asset URLs."""
    if isinstance(value, dict):
        return {k: _sanitize(v, read, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(v, read, key) for v in value]
    if isinstance(value, str) and key is not None:
        if key == 'url' or key.endswith('Url') or key == 'referenceImages':
            return read.own_url(value)
        if key in _STRUCTURAL:
            return value
    return read.prose(value) if isinstance(value, str) else value


def _halve(path, label, hint, keep=None):
    """A shrinker that halves the list at path (keys into data); keep(item) marks items that must stay."""
    seen = {}

    def shrink(data):
        items = data
        for step in path:
            items = items.get(step) if isinstance(items, dict) else None
        if not isinstance(items, list) or len(items) <= 1:
            return None
        seen.setdefault('total', len(items))
        kept = items[:len(items) // 2]
        kept += [item for item in items[len(items) // 2:] if keep and keep(item)]
        items[:] = kept
        return label, f'{label}: {len(items)} of {seen["total"]} shown; {hint}.'
    return shrink


# ---------- lookups that never read another production ----------

def _episode(read, identifier):
    match = _EPISODE_ID.fullmatch(identifier or '')
    if not match or match[1] != read.slug:
        return None
    try:
        ep = story.episode(read.conn, identifier)
    except story.StoryError:
        return None
    return ep if ep.get('slug') == read.slug else None


def _shot_row(read, identifier):
    match = _SHOT_ID.fullmatch(identifier or '')
    if not match or match[1] != read.slug:
        return None
    try:
        slug, row = story.find_row(read.conn, identifier, 'shot')
    except story.StoryError:
        return None
    return row if slug == read.slug else None


def _shot_brief(read, view, description_limit):
    return {'shotId': view['shotId'], 'shotIndex': view['shotIndex'],
            'description': read.text(view['description'], description_limit, 'descriptions',
                                     f'Shot descriptions are cut to {description_limit} characters; read_shot returns a shot in full.'),
            'opticalRig': read.text(view['opticalRig'], 200), 'cameraMotion': read.text(view['cameraMotion'], 200),
            'reviewStatus': view['reviewStatus']}


def _flags(view):
    flags = {}
    if view.get('selectedVideoUrl'):
        flags['take'] = True
    if view.get('previsPlanStored'):
        flags['plan'] = True
    return flags


# ---------- read_episode ----------

def read_episode(ctx, conn, args):
    read = _Read(ctx, conn, 'read_episode', args)
    requested = args.get('episode_id')
    ep = _episode(read, requested) if requested else _episode(read, getattr(ctx, 'episode_id', None))
    episodes = story.episodes(conn, ctx.slug)
    if ep is None and not requested:
        ep = next(filter(None, (_episode(read, e['episodeId']) for e in episodes)), None)
    if ep is None:
        return read.not_found(requested or ctx.slug, f'Episode {requested} is not in this production.' if requested
                              else 'This production has no episode yet.')
    read.source('episode', ep['episodeId'])
    for key in (ep['tabKey'], *SHOT_TABS):
        read.tab(key)
    content = story.script(conn, ep)
    scenes = story.scenes(conn, ep)
    shots = story.shots(conn, ep)
    missing, _ = story.missing_episode_assets(conn, ep)
    read.tab(CAST_TAB)
    placed = {scene['sceneId']: [] for scene in scenes}
    unplaced = []
    for view in sorted(shots, key=lambda s: (SHOT_TABS.index(s['tabKey']), _natural(s['shotIndex']))):
        entry = {'shotId': view['shotId'], 'shotIndex': view['shotIndex'], 'reviewStatus': view['reviewStatus'], **_flags(view)}
        if view.get('sceneId') in placed:
            placed[view['sceneId']].append(entry)
        else:
            unplaced.append({**entry, 'tabKey': view['tabKey']})
    settings = ep.get('settings') or {}
    dirty = ep.get('confirmedHash') != story.digest(content)
    if dirty and content.strip():
        read.warn('The script is not confirmed (or changed after Confirm Script & Extract Assets); the slate may not match it.')
    if missing:
        read.warn('Referenced cast or sets without a reference image: ' + ', '.join(missing) + '.')
    data = {
        'episode': {'episodeId': ep['episodeId'], 'episodeIndex': ep['episodeIndex'], 'title': read.text(ep.get('title'), 200),
                    'tabKey': ep['tabKey'], 'settings': settings,
                    'breakdownMode': ep.get('breakdownMode', settings.get('breakdownMode', 'auto')),
                    'scriptConfirmed': not dirty, 'scriptChars': len(content)},
        'episodes': [{'episodeId': e['episodeId'], 'episodeIndex': e['episodeIndex'], 'title': read.text(e.get('title'), 120)}
                     for e in episodes],
        'scenes': [{'sceneId': scene['sceneId'], 'sceneIndex': scene['sceneIndex'], 'title': read.text(scene['title'], 160),
                    'excerpt': read.text(scene['content'].strip(), 160, 'excerpts',
                                         'Scene text is an excerpt of up to 160 characters; read_scene returns a scene in full.'),
                    'chars': len(scene['content'].strip()), 'shots': placed[scene['sceneId']]} for scene in scenes],
        'unplacedShots': unplaced,
        'missingAssetCodes': missing,
        'counts': {'scenes': len(scenes), 'shots': len(shots),
                   'withTake': sum(1 for s in shots if s.get('selectedVideoUrl')),
                   'approved': sum(1 for s in shots if s.get('reviewStatus') in ('Approved', '已完成')),
                   'withPlan': sum(1 for s in shots if s.get('previsPlanStored'))},
    }

    def longest_scene(data):
        lists = [scene['shots'] for scene in data['scenes'] if len(scene['shots']) > 1]
        if not lists:
            return None
        items = max(lists, key=len)
        del items[len(items) // 2:]
        return 'scene_shots', 'Some scenes list only their first shots (counts has the totals); read_scene lists every shot of a scene.'

    def drop_excerpts(data):
        if not any(scene.get('excerpt') for scene in data['scenes']):
            return None
        for scene in data['scenes']:
            scene['excerpt'] = ''
        return 'excerpts', 'Scene excerpts were left out to fit; read_scene returns a scene in full.'

    return read.finish(data, ep['episodeId'], [
        _halve(('unplacedShots',), 'Unplaced shots', 'read_shot reads any shot by id'),
        longest_scene, drop_excerpts,
        _halve(('episodes',), 'Other episodes', 'pass episode_id to read one'),
        _halve(('scenes',), 'Scenes', 'read_scene reads the rest by id')])


# ---------- read_scene ----------

def read_scene(ctx, conn, args):
    read = _Read(ctx, conn, 'read_scene', args)
    identifier = args['scene_id']
    match = _SCENE_ID.fullmatch(identifier)
    try:
        ep, scene = story.locate_scene(conn, identifier) if match and match[1] == ctx.slug else (None, None)
    except story.StoryError:
        ep = scene = None
    if scene is None or ep.get('slug') != ctx.slug:
        return read.not_found(identifier, f'Scene {identifier} is not in this production.')
    read.source('episode', ep['episodeId'])
    read.source('scene', identifier)
    for key in (ep['tabKey'], *SHOT_TABS):
        read.tab(key)
    scenes = story.scenes(conn, ep)
    position = scene['sceneIndex'] - 1
    shots = sorted((s for s in story.shots(conn, ep) if s.get('sceneId') == identifier),
                   key=lambda s: (SHOT_TABS.index(s['tabKey']), _natural(s['shotIndex'])))
    content = scene['content'].strip()
    referenced = [m[1].upper().replace('#', ':') for m in story.ASSET_RE.finditer(content)]
    referenced += [code for view in shots for code in view['assets']]
    data = {
        'scene': {'sceneId': identifier, 'sceneIndex': scene['sceneIndex'], 'episodeId': ep['episodeId'],
                  'title': read.text(scene['title'], 200),
                  'content': read.text(content, 3000, 'content', f'The scene text was cut to 3000 of {len(content)} characters.'),
                  'chars': len(content)},
        'previousSceneId': scenes[position - 1]['sceneId'] if position > 0 else None,
        'nextSceneId': scenes[position + 1]['sceneId'] if position + 1 < len(scenes) else None,
        'shots': [{**_shot_brief(read, view, 280), 'tabKey': view['tabKey'], 'assets': view['assets'], **_flags(view)}
                  for view in shots],
        'cast': read.cast_of(referenced),
    }
    if not shots:
        read.warn('No shot is placed in this scene yet.')
    return read.finish(data, identifier, [_halve(('shots',), 'Shots', 'read_shot reads any shot by id'),
                                          _halve(('cast',), 'Cast', 'read_cast reads an asset by code')])


# ---------- read_shot ----------

def _cells(read, row):
    cells = []
    for index, (header, value) in enumerate(zip(row['headers'], row['cells'])):
        entry = {'col': index, 'header': read.text(header, 80)}
        media = _MEDIA_CELL.fullmatch(value or '')
        if media:
            url = media[1] or media[2]
            entry['url'] = url
            if not read.own_url(url):
                read.warn(f'Column {index} links media outside this production; the link is left out.')
        else:
            entry['value'] = read.text(value, 1000, 'cells', 'Long cells are cut to 1000 characters.')
        cells.append(entry)
    return cells


def _plan_summary(plan):
    summary = {key: plan[key] for key in _PLAN_SCALARS if key in plan}
    if isinstance(plan.get('cast'), list):
        summary['cast'] = [{k: member[k] for k in ('code', 'mark', 'turn', 'figure') if k in member}
                           for member in plan['cast'] if isinstance(member, dict)]
    if isinstance(plan.get('keys'), list) and len(plan['keys']) <= 12:
        summary['keys'] = plan['keys']
    summary['counts'] = {key: len(plan[key]) for key in _PLAN_LISTS if isinstance(plan.get(key), list)}
    return summary


def _neighbours(read, row, view):
    """The shots before and after this one in cut order: same sheet and episode, natural shot-number order."""
    mine = view.get('episodeId', f'ep_{read.slug}_01')
    same = []
    for other in story.table_rows(read.conn, read.slug, row['tabKey']):
        meta = story.shot_meta(read.conn, story.shot_id(read.slug, other))
        if meta.get('episodeId', f'ep_{read.slug}_01') == mine:
            same.append(other)
    ordered = sorted(same, key=lambda other: _natural(other['cells'][0] if other['cells'] else ''))
    at = next(i for i, other in enumerate(ordered) if other['rid'] == row['rid'])

    def brief(other):
        if other is None:
            return None
        neighbour = story.shot_view(read.conn, read.slug, other)
        read.source('shot', neighbour['shotId'], tabKey=other['tabKey'], rowId=other['rid'])
        return {**_shot_brief(read, neighbour, 240), 'sceneId': neighbour.get('sceneId'),
                'selectedImageUrl': neighbour['selectedImageUrl'], 'selectedVideoUrl': neighbour['selectedVideoUrl']}
    return brief(ordered[at - 1] if at > 0 else None), brief(ordered[at + 1] if at + 1 < len(ordered) else None)


def read_shot(ctx, conn, args):
    read = _Read(ctx, conn, 'read_shot', args)
    identifier = args['shot_id']
    row = _shot_row(read, identifier)
    if row is None:
        return read.not_found(identifier, f'Shot {identifier} is not in this production.')
    read.tab(row['tabKey'])
    read.source('shot', identifier, tabKey=row['tabKey'], rowId=row['rid'])
    meta = story.shot_meta(conn, identifier)
    view = story.shot_view(conn, ctx.slug, row)
    state = story_previs.stored(meta)
    read.source('shot_meta', 'meta_' + identifier, planRevision=state['planRevision'])
    previous, following = _neighbours(read, row, view)
    previs = {'stored': state['plan'] is not None, 'planRevision': state['planRevision'],
              'updatedAt': state['updatedAt'], 'updatedBy': state['updatedBy'], 'seed': meta.get('previsPlan')}
    if state['plan'] is not None:
        size = len(_dumps(state['plan']))
        if args.get('include_plan', True) is False:
            previs['planDetail'] = 'omitted'
        elif size <= PLAN_CHARS:
            previs.update(planDetail='full', plan=state['plan'])
        else:
            previs.update(planDetail='summary', plan=_plan_summary(state['plan']))
            read.limit('plan', f'The stored 3D plan is {size} characters; data.previs.plan is a summary (settings, cast '
                               'marks, camera keys when 12 or fewer, list counts). The whole plan: GET '
                               f'/aivideo/open/v1/shots/{identifier}/previs-plan.')
    lines = meta.get('dialogue')
    dialogue = [line for line in lines if isinstance(line, dict)] if isinstance(lines, list) else []
    readiness = view['readiness']
    if readiness.get('missingAssets'):
        read.warn('No reference image yet for: ' + ', '.join(readiness['missingAssets']) + '.')
    if meta.get('detachedScene'):
        read.warn('This shot is detached from its scene.')
    data = {
        'shot': {'shotId': identifier, 'rowId': row['rid'], 'tableId': row['tableId'], 'tabKey': row['tabKey'],
                 'shotIndex': view['shotIndex'], 'episodeId': view.get('episodeId', f'ep_{ctx.slug}_01'),
                 'sceneId': view.get('sceneId'), 'reviewStatus': view['reviewStatus'], 'assets': view['assets'],
                 'cells': _cells(read, row),
                 'dialogue': [{'speaker': line.get('speaker'), 'line': read.text(line.get('line'), 400),
                               'estimatedSeconds': line.get('estimatedSeconds')} for line in dialogue[:12]],
                 'trim': view['trim'], 'readiness': readiness,
                 'selectedImageUrl': view['selectedImageUrl'], 'selectedVideoUrl': view['selectedVideoUrl'],
                 'previsVideoUrl': view['previsVideoUrl']},
        'previs': previs,
        'previous': previous,
        'next': following,
        'cast': read.cast_of(view['assets']),
    }
    if len(dialogue) > 12:
        read.limit('dialogue', f'Dialogue lists the first 12 of {len(dialogue)} lines.')

    def summarise_plan(data):
        if data['previs'].get('planDetail') != 'full':
            return None
        data['previs'].update(planDetail='summary', plan=_plan_summary(data['previs']['plan']))
        return 'plan', ('The stored 3D plan is summarised to fit (settings, cast marks, camera keys when 12 or fewer, list '
                        f'counts). The whole plan: GET /aivideo/open/v1/shots/{identifier}/previs-plan.')

    def shorten_cells(data):
        cells = [cell for cell in data['shot']['cells'] if len(cell.get('value') or '') > 300]
        if not cells:
            return None
        for cell in cells:
            cell['value'] = cell['value'][:300].rstrip() + '…'
        return 'cells', 'Long cells are cut to 300 characters to fit; read_page reads the sheet row in full.'

    return read.finish(data, identifier, [summarise_plan, shorten_cells,
                                          _halve(('cast',), 'Cast', 'read_cast reads an asset by code')])


# ---------- read_cast ----------

def _look(read, asset, limit):
    return {'variantId': 'vr_' + asset['rowId'], 'assetId': asset['assetId'], 'assetCode': asset['assetCode'],
            'name': read.text(asset['name'], 120), 'kind': asset.get('kind'),
            'description': read.text(asset['prompt'], limit, 'looks', f'Look descriptions are cut to {limit} characters.'),
            'status': asset['status'], 'selectedImageUrl': asset['selectedImageUrl']}


def read_cast(ctx, conn, args):
    read = _Read(ctx, conn, 'read_cast', args)
    everything = list(read.assets().values())
    looks = {}
    for asset in everything:
        if not asset['isDefault']:
            looks.setdefault(asset['assetCode'].split(':')[0], []).append(asset)
    if 'asset' not in args:
        chosen = [a for a in everything if a['isDefault'] and args.get('type') in (None, a['type'])]
        data = {'assets': [{'assetId': a['assetId'], 'assetCode': a['assetCode'], 'name': read.text(a['name'], 120),
                            'type': a['type'],
                            'description': read.text(a['prompt'], 200, 'descriptions',
                                                     'Descriptions are cut to 200 characters; pass asset for one in full.'),
                            'status': a['status'], 'selectedImageUrl': a['selectedImageUrl'],
                            'looks': [{'assetCode': look['assetCode'], 'name': read.text(look['name'], 120),
                                       'kind': look.get('kind'), 'selectedImageUrl': look['selectedImageUrl']}
                                      for look in looks.get(a['assetCode'], [])]} for a in chosen],
                'counts': {'assets': len(chosen), 'looks': sum(len(looks.get(a['assetCode'], [])) for a in chosen),
                           'withoutImage': sum(1 for a in chosen if not a['selectedImageUrl'])}}
        return read.finish(data, ctx.slug, [_halve(('assets',), 'Assets', 'pass type or asset to narrow the read')])
    wanted = args['asset'].strip()
    if _ASSET_ID.fullmatch(wanted):
        base = next((a for a in everything if a['assetId'] == wanted), None)
        base = base and read.assets().get(base['assetCode'].split(':')[0])
    else:
        code = wanted.lstrip('@').upper().replace('#', ':')
        base = read.assets().get(code.split(':')[0])
    if base is None or not base['isDefault'] or args.get('type') not in (None, base['type']):
        kind = f" a {args['type']}" if args.get('type') else ''
        return read.not_found(wanted, f"{wanted} is not{kind} on this production's cast sheet.")
    read.source('asset', base['assetId'], code=base['assetCode'])
    try:
        candidates = story.candidate_list(conn, base['assetId'], 'image')
    except story.StoryError:
        candidates = []
    references = [c['url'] for c in candidates if read.own_url(c['url'])]
    if len(references) > 12:
        read.limit('references', f'referenceImages lists the 12 most recent of {len(references)} images.')
        references = references[-12:]
    usage_shots, usage_scenes = [], []
    for ep in story.episodes(conn, ctx.slug):
        try:
            shots = story.shots(conn, story.episode(conn, ep['episodeId']))
        except story.StoryError:
            continue
        for view in shots:
            if any(code == base['assetCode'] or code.startswith(base['assetCode'] + ':') for code in view['assets']):
                usage_shots.append(view['shotId'])
                if view.get('sceneId'):
                    usage_scenes.append(view['sceneId'])
    for key in SHOT_TABS:
        read.tab(key)
    if len(usage_shots) > 40:
        read.limit('usage', f'usage.shotIds lists the first 40 of {len(usage_shots)} shots.')
    data = {
        'asset': {'assetId': base['assetId'], 'assetCode': base['assetCode'], 'name': read.text(base['name'], 200),
                  'type': base['type'],
                  'description': read.text(base['prompt'], 2000, 'description', 'The description was cut to 2000 characters.'),
                  'voice': read.text(base['voice'], 300), 'status': base['status'], 'notes': read.text(base['notes'], 600),
                  'selectedImageUrl': base['selectedImageUrl'], 'referenceImages': references},
        'looks': [_look(read, look, 400) for look in looks.get(base['assetCode'], [])],
        'usage': {'shotIds': usage_shots[:40], 'sceneIds': list(dict.fromkeys(usage_scenes))},
    }
    code = wanted.lstrip('@').upper().replace('#', ':')
    if ':' in code:
        data['requested'] = code
        if code not in {look['assetCode'] for look in looks.get(base['assetCode'], [])}:
            read.warn(f'{base["assetCode"]} has no look {code}.')
    return read.finish(data, base['assetId'], [_halve(('looks',), 'Looks', 'read_cast with a look code reads its asset'),
                                               _halve(('asset', 'referenceImages'), 'Reference images', 'the newest are kept first'),
                                               _halve(('usage', 'shotIds'), 'Shots using the asset', 'read_episode lists every shot')])


# ---------- list_takes ----------

def _grade(read, grade):
    return {'gradeId': grade.get('gradeId'), 'status': grade.get('status'), 'score': grade.get('score'),
            'passed': grade.get('passed'),
            'issues': [read.text(issue, 240, 'grades', 'Grade issues and feedback are shortened.') for issue in (grade.get('issues') or [])[:6]],
            'feedback': read.text(grade.get('feedback'), 500, 'grades', 'Grade issues and feedback are shortened.'),
            'retakePrompt': read.text(grade.get('retakePrompt'), 600, 'grades', 'Grade issues and feedback are shortened.'),
            'auto': bool(grade.get('auto')), 'model': grade.get('model'), 'requestedAt': grade.get('requestedAt'),
            'gradedAt': grade.get('gradedAt'), 'error': read.text(grade.get('error'), 300) if grade.get('error') else None}


def list_takes(ctx, conn, args):
    from project_assistant import take_grader
    read = _Read(ctx, conn, 'list_takes', args)
    identifier = args['shot_id']
    row = _shot_row(read, identifier)
    if row is None:
        return read.not_found(identifier, f'Shot {identifier} is not in this production.')
    kind = args.get('kind', 'video')
    read.tab(row['tabKey'])
    read.source('shot', identifier, tabKey=row['tabKey'], rowId=row['rid'])
    try:
        candidates = story.candidate_list(conn, identifier, kind)
    except story.StoryError:
        candidates = None
        read.warn(f'This sheet has no {kind} output column.')
    grades = take_grader.grades(conn, ctx.slug, identifier) if kind == 'video' else []
    by_asset = {}
    for grade in grades:  # newest first: the first grade of an asset is its current one
        by_asset.setdefault(grade.get('assetId'), grade)
    key = 'videoId' if kind == 'video' else 'imageId'
    takes, matched = [], set()
    for candidate in candidates or []:
        asset = _ASSET_KEY.search(candidate['url'] or '')
        grade = by_asset.get(asset[0]) if asset else None
        if grade:
            matched.add(grade['gradeId'])
        takes.append({'takeId': candidate[key], 'url': candidate['url'], 'selected': bool(candidate['selected']),
                      'provenance': candidate.get('storyProvenanceState'), 'grade': _grade(read, grade) if grade else None})
    total = len(takes)
    if total > TAKES_SHOWN:
        shown = takes[-TAKES_SHOWN:]
        shown += [t for t in takes[:-TAKES_SHOWN] if t['selected']]
        takes = shown
        read.limit('takes', f'takes lists the {TAKES_SHOWN} most recent of {total} takes (and the selected one).')
    others = [{**_grade(read, grade), 'url': grade.get('assetUrl')} for grade in by_asset.values() if grade['gradeId'] not in matched]
    if len(others) > 10:
        read.limit('otherGrades', f'otherGrades lists the 10 most recent of {len(others)} grades of outputs not among the takes.')
        others = others[:10]
    if kind == 'video':
        read.source('setting', take_grader.SETTING)
    for grade in list(by_asset.values())[:TAKES_SHOWN]:
        read.source('grade', grade['gradeId'], status=grade.get('status'))
    view = story.shot_view(conn, ctx.slug, row)
    selected = view['selectedVideoUrl'] if kind == 'video' else view['selectedImageUrl']
    graded = [t['grade'] for t in takes if t['grade']]
    data = {'shotId': identifier, 'shotIndex': view['shotIndex'], 'tabKey': row['tabKey'], 'kind': kind,
            'autoGrade': take_grader.auto_enabled(conn, ctx.slug) if kind == 'video' else None, 'selectedUrl': selected,
            'takes': takes, 'otherGrades': others,
            'counts': {'takes': total, 'graded': sum(1 for g in graded if g['status'] == 'graded'),
                       'passed': sum(1 for g in graded if g['passed'] is True),
                       'failed': sum(1 for g in graded if g['passed'] is False),
                       'pending': sum(1 for g in graded if g['status'] in take_grader.ACTIVE)}}
    if candidates == []:
        read.warn(f'This shot has no {kind} take yet.')
    return read.finish(data, identifier, [_halve(('otherGrades',), 'Other grades', 'they grade outputs not among the takes'),
                                          _halve(('takes',), 'Takes', 'the most recent are kept first',
                                                 keep=lambda take: take.get('selected'))])


# ---------- grants for existing crews ----------

def top_up_grants(conn, slug):
    """Give the existing built-in crew agents the tools a newly seeded agent receives that cannot write (idempotent).

    Default grants only reach agents seeded after a tool is declared. This adds, once, to the built-in agents each
    declaration grants:
      - the read-only tools of this category (recorded in the project setting TOPUP_SETTING), and
      - the proposal-only tools (tool_registry.proposal_only: propose_shot_prompt, propose_camera,
        propose_asset_description, propose_look, propose_cast and any later propose_* tool of the same shape;
        recorded in PROPOSAL_TOPUP_SETTING).
    Every offered tool is recorded per agent, so a tool an administrator later removes is not added back, and a tool
    that writes or spends directly (studio, delegation, generation, legacy) is never added. Called by
    agent_registry.ensure_default_agents after the seed (startup and every project upsert)."""
    with conn.cursor() as cur:
        cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('crew-context-topup:' + slug,))
    _top_up(conn, slug, TOPUP_SETTING, CATEGORY,
            lambda tool: tool.category == CATEGORY and not tool.mutating)
    _top_up(conn, slug, PROPOSAL_TOPUP_SETTING, PROPOSAL_CATEGORY, lambda tool: tool.name in tool_registry.PROPOSAL_ONLY)


def _top_up(conn, slug, setting, label, eligible):
    """Add the eligible tools of each built-in role's default grants once, recording the offer in `setting`."""
    from project_assistant import agent_registry
    offers = {role: [tool.name for tool in tool_registry.all_tools() if eligible(tool) and role in tool.grants]
              for role in tool_registry.BUILTIN_ROLES}
    try:
        offered = json.loads(store.get_setting(conn, slug, setting) or '{}')
    except ValueError:
        offered = {}
    offered = offered if isinstance(offered, dict) else {}
    changed = False
    for role, names in offers.items():
        done = [name for name in offered.get(role, []) if isinstance(name, str)]
        fresh = [name for name in names if name not in done]
        if not fresh:
            continue
        profile = agent_registry.get_agent(conn, slug, role, effective=False)
        if profile is None:
            continue  # not seeded yet: the seed itself grants these
        allowed = list(profile['allowed_tools'] or [])
        missing = [name for name in fresh if name not in allowed]
        if missing and len(allowed) + len(missing) <= 128:  # agent_registry.save_agent's list limit
            with conn.cursor() as cur:
                cur.execute('UPDATE projectops.agent_profile SET allowed_tools=%s::jsonb WHERE project_slug=%s AND agent_key=%s',
                            (json.dumps(allowed + missing), slug, role))
            repo.add_audit(conn, slug, action=TOPUP_ACTION, target=role, detail={'added': missing, 'category': label})
        offered[role] = done + fresh
        changed = True
    if changed:
        store.set_setting(conn, slug, setting, json.dumps(offered, sort_keys=True))


HANDLERS = tool_registry.handlers(__name__, globals())
