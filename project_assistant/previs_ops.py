"""Structured 3D operations for a shot, solved into a plan proposal (SPEC_20 R27, R28; decisions 6, 9, 11).

The crew never writes code for the 3D Stage. ``propose_previs_ops`` takes operations in film language (§4.6):

    {"shotId": "sh_...", "baseRevision": 7, "ops": [
      {"op": "place", "cast": "@CAST-01", "relativeTo": "console", "offset": [-1.0, 0.0], "facing": "window"},
      {"op": "camera", "size": "medium", "angle": "low", "lens": 35, "move": "pushin", "from": "K1", "to": "K2"},
      {"op": "retime", "beat": 2, "at": 0.6}]}

validates them here (strictly: closed fields, the production's cast codes, the set's own targets, LENSES/MOVES, the
move's camera keys, the plan's acting beats), refuses a stale ``baseRevision`` with 409
``DRAMA_PREVIS_REVISION_CONFLICT``, and has the 3D Stage's own JavaScript (``ui/src/previs/ops.js``) solve them into a
plan in a headless browser (``headless_previs``), which also renders a contact sheet of the solved plan. The result is a
``shot_meta`` ``previsPlan`` proposal (``shot_meta.propose``) carrying the operations, the solved plan and the preview;
nothing is written to the shot until a person approves it.

Without a headless browser (or without the built solver page) the proposal stores the operations only
(``solve.status == "ops_only"``, ``value`` null). The reviewer's 3D Stage solves them with the same module and shows the
ghost; approving first attaches that solve (``attach_solution``: validated against the cast sheet and checked against
the operations) and then applies it. ``shot_meta.write`` refuses a proposal without a solved plan, so an approval never
writes an unsolved plan.

The vocabulary below mirrors ``ops.js`` (tests/test_previs_ops.py reads the JS and compares), as
``project_docs/story_previs`` mirrors ``plan.js``. The only plan logic mirrored here is what validation needs to know about
the base plan: its set, who is on set and how many acting beats it has (``base_facts``; the golden file checks it
against the JS). The solve itself is never rewritten in Python.

An optional vision check (project setting ``previs_vision_check`` = ``on``) sends the contact sheet to the Continuity
Supervisor's vision model after the proposal is made: governed like continuity grading (``take_grader``) and under the
GPU arbiter. It only annotates the proposal (``target.vision``); the director decides.
"""
from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import math
import re
import threading

from project_assistant import headless_previs, shot_meta, store
from project_docs import repository as repo, story_openapi as story, story_previs

TOOL = 'propose_previs_ops'
OPS_VERSION = 1                       # ops.js OPS_VERSION
OP_TYPES = ('place', 'camera', 'retime')
SIZES = ('wide', 'full', 'medium', 'close', 'extreme_close')
ANGLES = ('low', 'eye', 'high', 'overhead')
FACE_LENS = ('camera', 'room')
MAX_OPS = 32
MAX_OFFSET = 8                        # metres either way
MOVE_KEYS = {'static': 1, 'pushin': 2, 'pullout': 2, 'crane': 2, 'track': 2, 'orbit': 3}
STAGE_TARGETS = {'observatory': ('console', 'plinth', 'dial', 'recorder', 'console_edge', 'window_glass'),
                 'parallax': ('far', 'mid', 'near'), 'empty': ()}
TARGET_ALIASES = {'window': 'window_glass'}
OP_FIELDS = {'place': (('op', 'cast', 'relativeTo', 'offset', 'facing'), ()),
             'camera': (('op', 'size', 'angle', 'lens', 'move'), ('from', 'to')),
             'retime': (('op', 'beat', 'at'), ())}
REQUEST_FIELDS = ('shotId', 'baseRevision', 'ops')
CAST_CODE = re.compile(r'@CAST-\d{1,4}')
CAMERA_KEY = re.compile(r'K(\d{1,2})')
VISION_SETTING = 'previs_vision_check'
VISION_TIMEOUT = 600
VISION_RUBRIC = ("You check a 3D previs contact sheet (six frames of one planned shot, grey mannequins on a blockout set) "
                 "before a director approves it. Judge only staging and camera, never looks: is the main face readable "
                 "toward the lens, is anyone cut off, inside a set piece or off screen, does the camera pass through a "
                 "person or a wall, does the last frame match the plan. Reply JSON only: "
                 '{"faceReadable": bool, "issues": [str], "note": str}.')


class OpsRefusal(ValueError):
    """A request the server refuses: status 404 (shot), 409 (revision) or 422 (operations), with the field path."""

    def __init__(self, status, message, *, code='PREVIS_OPS_INVALID', path=None, details=None):
        super().__init__(message)
        self.status, self.code, self.path, self.details = status, code, path, details


def _invalid(path, message):
    raise OpsRefusal(422, f'{path} {message}', path=path)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _whole(value):
    return isinstance(value, int) and not isinstance(value, bool)


def target_name(name):
    return TARGET_ALIASES.get(name, name) if isinstance(name, str) else name


def _keys(count):
    return ', '.join(f'K{k + 1}' for k in range(count))


def _key_index(name):
    match = CAMERA_KEY.fullmatch(name) if isinstance(name, str) else None
    return int(match[1]) - 1 if match else None


# ---------- what validation needs to know about the base plan (mirrors storyPlan.resolveShotPlan, blocking.actingBeats) ----------

def _mid(value):
    if isinstance(value, dict) and isinstance(value.get('range'), list) and len(value['range']) == 2:
        return (value['range'][0] + value['range'][1]) / 2
    return value


def _resolved(value):
    """plan.js withRanges at the midpoints."""
    if isinstance(value, dict):
        if set(value) == {'range'}:
            return _mid(value)
        return {key: _resolved(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolved(item) for item in value]
    return value


def acting_beats(plan):
    """How many acting beats the 3D Stage shows for a plan (blocking.js actingBeats: plan.use's steps that last, or the
    Walk in action's one walk). Mirrors plan.js motionBeats' timing only as far as the count needs it."""
    use = plan.get('use') or []
    if not use:
        return 1 if not plan.get('acts') and plan.get('action') == 'walkin' else 0
    count, cursor, spot = 0, 0.0, _resolved(plan.get('mark')) or [0, 0]
    for step in _resolved(use):
        args = step.get('args') or {}
        start = step['f0'] if _number(step.get('f0')) else cursor
        end = start
        skill = step.get('skill')
        if skill == 'standIdle':
            end = args['until'] if _number(args.get('until')) else start + (step['frames'] if _number(step.get('frames')) else 24)
            spot = args.get('at') or spot
        elif skill == 'walkTo' and args.get('to'):
            if _number(step.get('frames')):
                end = start + step['frames']
            else:
                origin = args.get('from') or spot
                distance = math.hypot(args['to'][0] - origin[0], args['to'][1] - origin[1])
                end = start + math.floor(distance / 1.2 * 24 + 0.5) + 8  # Math.round
            spot = args['to']
        elif skill == 'reachGrip' and (args.get('anchor') in story_previs.SCENE_ANCHORS or isinstance(args.get('anchor'), list)):
            end = start + sum(args[key] if _number(args.get(key)) else default for key, default in (('reach', 12), ('hold', 24), ('release', 12)))
        elif skill == 'turnLook':
            end = start + (step['frames'] if _number(step.get('frames')) else 16)
        elif skill == 'kneelDown':
            end = start + (step['frames'] if _number(step.get('frames')) else args['duration'] if _number(args.get('duration')) else 24)
        if end > start:
            count += 1
        cursor = end
    return count


def _slate_action(action):
    """plan.js planFromSlate's action from the slate text."""
    if re.search(r'\b(walks?|enters?|approach)', action or '', re.I):
        return 'walkin'
    if re.search(r'\b(turns?|reach|dial|press)', action or '', re.I):
        return 'turnreach'
    return 'stand'


def base_facts(stored, shot):
    """{set, onSet, actingBeats} of the plan the operations apply to: the stored plan, else the storyboard seed over the
    slate text, as storyPlan.resolveShotPlan builds it."""
    if isinstance(stored, dict):
        codes = [stored.get('code')] + [member.get('code') for member in stored.get('cast') or [] if isinstance(member, dict)]
        return {'set': stored.get('set', 'observatory'), 'onSet': [code for code in codes if code],
                'actingBeats': acting_beats(stored)}
    seed = shot.get('previsPlan') if isinstance(shot.get('previsPlan'), dict) else {}
    action = seed.get('action') if seed.get('action') in story_previs.ACTIONS else _slate_action((shot.get('slate') or {}).get('action'))
    return {'set': seed.get('set') if seed.get('set') in story_previs.SETS else 'observatory', 'onSet': [],
            'actingBeats': 1 if action == 'walkin' else 0}


# ---------- validation (mirrors ops.js validateOps; the golden file's invalid cases pin the paths) ----------

def validate_request(body):
    """(shotId, baseRevision, ops) of a well-formed request, else OpsRefusal 422."""
    if not isinstance(body, dict):
        _invalid('request', 'must be an object {shotId, baseRevision, ops}.')
    unknown = sorted(set(body) - set(REQUEST_FIELDS))
    if unknown:
        _invalid('request', 'has unknown fields: ' + ', '.join(unknown) + '.')
    if not isinstance(body.get('shotId'), str) or not body['shotId'].strip():
        _invalid('shotId', 'must name the shot (its shotId from read_shot).')
    revision = body.get('baseRevision')
    if not _whole(revision) or revision < 0:
        _invalid('baseRevision', 'must be the planRevision read with the shot (0 before the first save).')
    return body['shotId'], revision, body.get('ops')


def validate_ops(ops, *, base_set='observatory', on_set=(), acting=0, cast_codes=None):
    """Raise OpsRefusal (422, with the path ops.js names) unless ops are valid for this base plan and cast sheet."""
    if not isinstance(ops, list) or not 1 <= len(ops) <= MAX_OPS:
        _invalid('ops', f'must list 1 to {MAX_OPS} operations.')
    targets, on_set, placed = STAGE_TARGETS.get(base_set, ()), set(on_set), []
    sheet = set(cast_codes) if cast_codes is not None else None
    cameras, retimed, facings = 0, set(), []
    named = ', '.join([*targets, 'mark'])
    for index, op in enumerate(ops):
        path = f'ops[{index}]'
        if not isinstance(op, dict) or op.get('op') not in OP_TYPES:
            _invalid(path, 'must be an operation: place, camera or retime.')
        required, optional = OP_FIELDS[op['op']]
        unknown = sorted(set(op) - set(required) - set(optional))
        if unknown:
            _invalid(path, 'has unknown fields: ' + ', '.join(unknown) + '.')
        missing = [key for key in required if op.get(key) is None]
        if missing:
            _invalid(path, 'needs ' + ', '.join(missing) + '.')
        if op['op'] == 'place':
            code = op['cast']
            if not isinstance(code, str) or not CAST_CODE.fullmatch(code):
                _invalid(path + '.cast', 'must be a cast code such as @CAST-01.')
            if sheet is not None and code not in sheet:
                _invalid(path + '.cast', f'names {code}, which is not on the cast sheet.')
            if code in placed:
                _invalid(path + '.cast', f'places {code} a second time; place each person once.')
            anchor = target_name(op['relativeTo'])
            if not isinstance(anchor, str) or anchor == code or not (
                    anchor in targets or anchor == 'mark' or (CAST_CODE.fullmatch(anchor) and (anchor in on_set or anchor in placed))):
                _invalid(path + '.relativeTo', f'must be a target of the {base_set} set ({named}) or someone already on set.')
            offset = op['offset']
            if not isinstance(offset, list) or len(offset) != 2 or not all(_number(v) and abs(v) <= MAX_OFFSET for v in offset):
                _invalid(path + '.offset', f'must be [x, z] in metres, each within ±{MAX_OFFSET}.')
            if not isinstance(op['facing'], str):
                _invalid(path + '.facing', 'must be a target, a cast code, camera or room.')
            placed.append(code)
            facings.append((path + '.facing', code, target_name(op['facing'])))
        elif op['op'] == 'camera':
            cameras += 1
            if cameras > 1:
                _invalid(path, 'is a second camera operation; a shot has one camera.')
            for key, allowed, suffix in (('size', SIZES, ''), ('angle', ANGLES, ''), ('lens', story_previs.LENSES, ' (mm)'),
                                         ('move', story_previs.MOVES, '')):
                value = op[key]
                if isinstance(value, bool) or value not in allowed or (key == 'lens' and not _whole(value)):
                    _invalid(f'{path}.{key}', 'must be one of ' + ', '.join(map(str, allowed)) + suffix + '.')
            count, move = MOVE_KEYS[op['move']], op['move']
            start = 0 if op.get('from') is None else _key_index(op['from'])
            end = (start if move == 'static' else count - 1) if op.get('to') is None else _key_index(op['to'])
            for key, value in (('from', start), ('to', end)):
                if op.get(key) is not None and (value is None or not 0 <= value < count):
                    _invalid(f'{path}.{key}', f'must be a camera key of a {move} move: {_keys(count)}.')
            if move == 'static' and end != start:
                _invalid(path + '.to', 'must be the key a static camera holds (the same as from).')
            if move != 'static' and end <= start:
                _invalid(path + '.to', 'must be a later key than from.')
        else:
            beat = op['beat']
            if not _whole(beat) or not 1 <= beat <= acting:
                _invalid(path + '.beat', f'must be an acting beat from 1 to {acting}.' if acting else
                         'cannot be retimed: this plan has no acting beats.')
            if beat in retimed:
                _invalid(path + '.beat', f'retimes beat {beat} a second time.')
            if not _number(op['at']) or not 0 <= op['at'] <= 1:
                _invalid(path + '.at', 'must be a fraction of the shot from 0 to 1.')
            retimed.add(beat)
    for path, code, name in facings:
        if name == code or not (name in targets or name == 'mark' or name in FACE_LENS
                                or (CAST_CODE.fullmatch(name) and (name in on_set or name in placed))):
            _invalid(path, f'must be a target of the {base_set} set ({named}), camera, room or someone else on set.')
    return ops


def ops_hash(shot_id, base_revision, ops):
    canonical = json.dumps({'shotId': shot_id, 'baseRevision': base_revision, 'ops': ops, 'version': OPS_VERSION},
                           sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return 'sha256:' + hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def describe(ops):
    """The proposal's one-line summary, from the operations alone (the same with or without a solve)."""
    parts = []
    for op in ops:
        if op['op'] == 'place':
            x, z = op['offset']
            where = op['relativeTo'] + ('' if not (x or z) else f' {x:+g}, {z:+g} m')
            parts.append(f"{op['cast']} at {where}, facing {op['facing']}")
        elif op['op'] == 'camera':
            keys = '' if op['move'] == 'static' else f" {op.get('from') or 'K1'}→{op.get('to') or 'K' + str(MOVE_KEYS[op['move']])}"
            parts.append(f"{op['size'].replace('_', ' ')} {op['angle']}-angle {op['lens']}mm {op['move']}{keys}")
        else:
            parts.append(f"acting beat {op['beat']} at {round(op['at'] * 100)}%")
    text = '3D blocking: ' + '; '.join(parts) + '.'
    return text if len(text) <= shot_meta.MAX_SUMMARY else text[:shot_meta.MAX_SUMMARY - 1] + '…'


def consistent(ops, plan, facts, stored=None):
    """What a solved plan gets wrong about its operations (empty when it fits). Not a second solver: the facts any solve
    of these operations must show (set, lens and move, who is on set, unchanged length and light)."""
    problems = []
    if plan.get('set') != facts['set']:
        problems.append(f"the plan is on the {plan.get('set')} set, not {facts['set']}")
    codes = [plan.get('code')] + [member.get('code') for member in plan.get('cast') or [] if isinstance(member, dict)]
    missing = [op['cast'] for op in ops if op['op'] == 'place' and op['cast'] not in codes]
    missing += [code for code in facts['onSet'] if code not in codes]
    if missing:
        problems.append('nobody on set is ' + ', '.join(sorted(set(missing))))
    camera = next((op for op in ops if op['op'] == 'camera'), None)
    if camera:
        if (plan.get('lens'), plan.get('move')) != (camera['lens'], camera['move']):
            problems.append(f"the camera is {plan.get('lens')}mm {plan.get('move')}, not {camera['lens']}mm {camera['move']}")
        if not isinstance(plan.get('keys'), list) or len(plan['keys']) < 2:
            problems.append('the plan has no camera keys')
    if isinstance(stored, dict):
        for key in ('seconds', 'mood'):
            if plan.get(key) != stored.get(key):
                problems.append(f'{key} changed from {stored.get(key)} to {plan.get(key)}')
    return problems


# ---------- one request, in three steps: prepare (transaction), solve (no transaction), commit (transaction) ----------

@dataclasses.dataclass
class Prepared:
    slug: str
    shot_id: str
    label: str
    base: int
    ops: list
    stored: dict | None
    facts: dict
    codes: list
    request: dict      # the solver page's solveRequest input
    files: dict        # set images the page may load: {path: (content type, bytes)}


def _column(headers, pattern):
    return next((index for index, header in enumerate(headers) if re.search(pattern, header, re.I)), -1)


def shot_input(conn, slug, row, meta):
    """The shot as the 3D Stage seeds it (studioModel.stageShots): slate text, storyboard seed, the set image."""
    headers, cells = row['headers'], row['cells']
    text = lambda index: '' if index < 0 or index >= len(cells) else str(cells[index] or '')  # noqa: E731
    slate = {'motion': text(_column(headers, r'camera motion')), 'rig': text(_column(headers, r'optical rig|lens')),
             'action': text(_column(headers, r'action|prompt'))}
    seed = meta.get('previsPlan') if isinstance(meta.get('previsPlan'), dict) else None
    known = {}
    for cast_row in story.table_rows(conn, slug, 'soul-cast'):
        asset = story.asset_view(slug, cast_row)
        if asset['isDefault']:
            known.setdefault(asset['assetCode'], asset)
    set_asset = None
    for match in story.ASSET_RE.finditer(' '.join(map(str, cells))):
        code = match[1].upper().replace('#', ':')
        url = (known.get(code.split(':')[0]) or {}).get('selectedImageUrl')
        if code.startswith(('SET-', 'LOC-')) and url:
            set_asset = {'id': code, 'url': url}
            break
    return {'slate': slate, 'previsPlan': seed, 'setAsset': set_asset}


def _page_files(conn, slug, stored, shot):
    """This production's images the solver page may load: the set image and any card image of the stored plan."""
    urls = [((shot.get('setAsset') or {}).get('url'))]
    urls += [layer.get('src') for layer in (stored or {}).get('layers') or [] if isinstance(layer, dict)]
    files = {}
    for url in urls:
        match = re.fullmatch(r'/projects/api/' + re.escape(slug) + r'/assets/(pa_[0-9a-f]{32})', url or '')
        if match and url not in files:
            found = repo.get_asset(conn, slug, match[1])
            if found and str(found[0]).startswith('image/'):
                files[url] = (found[0], bytes(found[1]))
    return files


def prepare(conn, slug, body):
    """Validate a request against the shot and its stored plan; OpsRefusal 404/409/422 otherwise."""
    shot_id, base, ops = validate_request(body)
    row = shot_meta._shot_row(conn, slug, shot_id)
    if row is None:
        raise OpsRefusal(404, shot_meta.SHOT_NOT_FOUND, code='DRAMA_NOT_FOUND', path='shotId')
    label = shot_meta._label(row, shot_id)
    meta = story.shot_meta(conn, shot_id)
    state = story_previs.stored(meta)
    if base != state['planRevision']:
        raise OpsRefusal(409, f"The 3D plan of shot {label} is at revision {state['planRevision']}, not {base}. Read the shot "
                              'again and rebuild the operations against the current plan.', code=story_previs.CONFLICT,
                         path='baseRevision', details={'currentRevision': state['planRevision'], 'baseRevision': base})
    codes = [option['code'] for option in story_previs.cast_options(conn, slug)]
    shot = shot_input(conn, slug, row, meta)
    facts = base_facts(state['plan'], shot)
    validate_ops(ops, base_set=facts['set'], on_set=facts['onSet'], acting=facts['actingBeats'], cast_codes=codes)
    request = {'stored': state['plan'], 'shot': shot, 'ops': ops, 'castCodes': codes}
    return Prepared(slug, shot_id, label, base, ops, state['plan'], facts, codes, request, _page_files(conn, slug, state['plan'], shot))


def _title(prepared):
    return lambda plan: f"{prepared.label} · proposed 3D plan · {plan.get('lens')}mm {plan.get('move')} · {plan.get('seconds')} s"


def solve(prepared, *, runner=None, render=True):
    """Solve (and render) in the headless browser. Returns {plan, image, sheet, solve}; plan None when no browser could
    run (operations only). OpsRefusal 422 when the solver refuses the operations or its plan is not storable."""
    runner = runner or headless_previs.run
    try:
        result = runner(prepared.request, title=_title(prepared), files=prepared.files, render=render)
    except headless_previs.Refused as exc:
        raise OpsRefusal(422, str(exc), path=exc.path) from None
    except headless_previs.Unavailable as exc:
        return {'plan': None, 'image': None, 'sheet': None,
                'solve': {'status': 'ops_only', 'reason': exc.code, 'note': str(exc)[:300], 'version': OPS_VERSION}}
    solved = result['solved']
    plan = solved['plan']
    try:
        story_previs.validate(plan, set(prepared.codes))
    except story.StoryError as exc:
        raise OpsRefusal(422, f'The solved 3D plan cannot be stored: {exc}', path='ops') from None
    problems = consistent(prepared.ops, plan, prepared.facts, prepared.stored)
    if problems:
        raise OpsRefusal(422, 'The solved 3D plan does not match its operations: ' + '; '.join(problems) + '.', path='ops')
    info = {'status': 'solved', 'by': 'headless', 'version': solved.get('version', OPS_VERSION),
            'warnings': list(solved.get('warnings') or [])[:20], 'browser': result.get('browser'), 'seconds': result.get('seconds')}
    if result.get('renderError'):
        info['renderError'] = str(result['renderError'])[:300]
    return {'plan': plan, 'image': result.get('image'), 'sheet': result.get('sheet'), 'solve': info}


def commit(conn, prepared, solved, owner_id, *, ctx=None, agent_key=None, author_id=None, message_id=None):
    """Store the preview and create the proposal, after checking the stored plan did not move during the solve."""
    current = story_previs.stored(story.shot_meta(conn, prepared.shot_id))['planRevision']
    if current != prepared.base:
        raise OpsRefusal(409, f'The 3D plan of shot {prepared.label} changed while the operations were solved (revision '
                              f'{prepared.base}, now {current}). Read the shot again and rebuild the operations.',
                         code=story_previs.CONFLICT, path='baseRevision', details={'currentRevision': current, 'baseRevision': prepared.base})
    preview = None
    if solved.get('image'):
        asset = repo.put_asset(conn, prepared.slug, data=solved['image'], content_type='image/png', actor_id=owner_id)
        sheet = solved.get('sheet') or {}
        preview = {'kind': 'contact_sheet', 'assetId': asset, 'url': f'/projects/api/{prepared.slug}/assets/{asset}',
                   'width': sheet.get('width'), 'height': sheet.get('height'), 'frames': sheet.get('frames') or []}
    details = {'ops': prepared.ops, 'opsHash': ops_hash(prepared.shot_id, prepared.base, prepared.ops), 'solve': solved['solve'],
               'preview': preview}
    options = dict(field=story_previs.FIELD, base_revision=prepared.base, summary=describe(prepared.ops), details=details)
    try:
        if ctx is not None:
            return shot_meta.propose_from_tool(ctx, conn, prepared.shot_id, solved['plan'], agent_key=agent_key, **options)
        return shot_meta.propose(conn, prepared.slug, owner_id, prepared.shot_id, solved['plan'], agent_key=agent_key,
                                 author_id=author_id, message_id=message_id, **options)
    except shot_meta.ProposalError as exc:
        raise OpsRefusal(exc.status, str(exc), code='DRAMA_PREVIS_PROPOSAL') from None


def propose_ops(conn, slug, owner_id, body, *, runner=None, render=True, agent_key=None, author_id=None, message_id=None):
    """prepare, solve and commit in the caller's transaction (scripts and tests; the tool releases it for the solve)."""
    prepared = prepare(conn, slug, body)
    solved = solve(prepared, runner=runner, render=render)
    return commit(conn, prepared, solved, owner_id, agent_key=agent_key, author_id=author_id, message_id=message_id)


# ---------- the crew tool ----------

def _report(proposal, prepared, solved):
    target = proposal['target']
    lines = [f"Proposal #{proposal['id']} for shot {prepared.label}: a 3D plan from {len(prepared.ops)} operation(s) on revision "
             f"{prepared.base}. Nothing is written until the director approves it in the 3D Stage."]
    plan = solved['plan']
    if plan is not None:
        people = [f"{plan.get('code') or 'actor'} at {plan.get('mark', [0, 0])} facing {plan.get('facing')} turn {plan.get('turn', 0)}°"]
        people += [f"{m.get('code') or 'cast'} at {m.get('mark', [0, 0])} turn {m.get('turn', 0)}°" for m in plan.get('cast') or []]
        lines.append('Solved: ' + '; '.join(people) + f"; camera {plan.get('lens')}mm {plan.get('move')} over {len(plan.get('keys') or [])} keys.")
        for warning in solved['solve'].get('warnings') or []:
            lines.append('Warning: ' + warning)
        preview = target.get('preview')
        lines.append(f"Preview: contact sheet {preview['url']} ({len(preview['frames'])} frames), attached. Look at it before you present the plan."
                     if preview else 'No preview image: ' + (solved['solve'].get('renderError') or 'the render failed') + '.')
    else:
        lines.append('Operations only: no headless browser ran on this server (' + str(solved['solve'].get('reason')) + '). '
                     'The director previews and solves them in the 3D Stage; say so when you present the proposal.')
    return '\n'.join(lines)


def propose_previs_ops(ctx, conn, args):
    """The tool (external: tools.call has released its transaction). Prepare, release the transaction for the browser,
    then lock, re-authorize and commit like studio_inspect_frames."""
    from project_assistant import agent_policy, orchestrator as cp
    try:
        prepared = prepare(conn, ctx.slug, args)
    finally:
        conn.rollback()  # no transaction or lock across the headless browser
    solved = solve(prepared)
    cp.lock_project(conn, ctx.slug)
    agent_policy.authorize_tool(ctx, conn, TOOL, args)
    proposal = commit(conn, prepared, solved, ctx.me.actor_id, ctx=ctx, agent_key=getattr(ctx, 'agent_key', None))
    if solved.get('image'):
        ctx.pending_images.append('data:image/png;base64,' + base64.b64encode(solved['image']).decode('ascii'))
        if store.get_setting(conn, ctx.slug, VISION_SETTING) == 'on':
            ctx.post_commit_actions.append(lambda: start_vision_check(ctx.slug, proposal['id']))
    return _report(proposal, prepared, solved)


# ---------- the camera job's 3D camera (crew_planning.PREVIS_HOOK, SPEC_20 R20) ----------

def propose_from_job(ctx, conn, shot_id, ops):
    """The Cinematographer's camera job (crew_planning) also proposes its §4.6 camera op as a previsPlan proposal on the
    shot's current plan revision: the framed camera path shows as the ghost camera in the 3D Stage, next to the job's
    Optical Rig and Camera Motion cell proposal. Runs in a savepoint of the job's transaction, so a refusal (OpsRefusal)
    leaves nothing of this proposal behind and the cell proposal stands. Returns the proposal id."""
    state = story_previs.stored(story.shot_meta(conn, shot_id))
    with conn.transaction():
        prepared = prepare(conn, ctx.slug, {'shotId': shot_id, 'baseRevision': state['planRevision'], 'ops': ops})
        solved = solve(prepared)
        return commit(conn, prepared, solved, ctx.me.actor_id, ctx=ctx, agent_key=getattr(ctx, 'agent_key', None))['id']


# ---------- the 3D Stage's solve of an operations-only proposal ----------

def attach_solution(conn, me, slug, proposal_id, body):
    """POST /projects/api/{slug}/assistant/proposals/{id}/solution {plan, version}: the reviewer's 3D Stage solved an
    operations-only proposal; store that plan on it so approval can write it. Only the proposal's owner, a writer, while
    it is pending and the shot's plan is still at its base revision. Returns (status, payload)."""
    if not me.can_write:
        return 403, {'error': shot_meta.READ_ONLY}
    proposal = store.proposal(conn, proposal_id, for_update=True)
    if not proposal or proposal['slug'] != slug or proposal['owner_id'] != me.actor_id or proposal['action'] != shot_meta.ACTION:
        return 404, {'error': 'Proposal not found.'}
    if proposal['status'] != 'pending':
        return 409, {'error': 'This proposal has already been handled.'}
    target = proposal.get('target') or {}
    ops = target.get('ops')
    if target.get('field') != story_previs.FIELD or not isinstance(ops, list):
        return 400, {'error': SOLUTION_NOT_OPS}
    if target.get('value') is not None:
        return 409, {'error': SOLUTION_ALREADY}
    plan = body.get('plan') if isinstance(body, dict) else None
    if not isinstance(plan, dict) or body.get('version') != OPS_VERSION or set(body) - {'plan', 'version'}:
        return 400, {'error': f'Send the solved plan as {{"plan": {{...}}, "version": {OPS_VERSION}}}.'}
    row = shot_meta._shot_row(conn, slug, target.get('shotId'))
    if row is None:
        return 409, {'error': shot_meta.SHOT_DELETED.format(label=(target.get('shot') or {}).get('label') or target.get('shotId'))}
    label = shot_meta._label(row, target['shotId'])
    meta = story.shot_meta(conn, target['shotId'])
    state = story_previs.stored(meta)
    if state['planRevision'] != target.get('baseRevision'):
        return 409, {'error': shot_meta.FIELDS[story_previs.FIELD].conflict.format(label=label, base=target.get('baseRevision'),
                                                                                    current=state['planRevision'])}
    try:
        story_previs.validate(plan, {option['code'] for option in story_previs.cast_options(conn, slug)})
    except story.StoryError as exc:
        return 409, {'error': shot_meta.FIELDS[story_previs.FIELD].invalid.format(label=label, reason=str(exc))}
    problems = consistent(ops, plan, base_facts(state['plan'], shot_input(conn, slug, row, meta)), state['plan'])
    if problems:
        return 409, {'error': SOLUTION_MISMATCH.format(label=label, reason='; '.join(problems))}
    solve_info = {**(target.get('solve') or {}), 'status': 'solved', 'by': 'stage', 'actorId': me.actor_id,
                  'version': OPS_VERSION, 'at': story.now()}
    store.revise_pending_proposal(conn, proposal_id, {**target, 'value': plan, 'solve': solve_info}, proposal['content'])
    return 200, {'proposal': {'id': proposal_id, 'status': 'pending', 'shotId': target['shotId'], 'solve': solve_info}}


SOLUTION_NOT_OPS = 'Only a 3D plan proposal made of operations can take a solve from the 3D Stage.'
SOLUTION_ALREADY = 'This proposal already carries a solved 3D plan.'
SOLUTION_MISMATCH = ("The 3D Stage's solve for shot {label} does not match the proposal's operations: {reason}. "
                     'Nothing was attached; reload the proposal.')


# ---------- optional vision check (annotates only) ----------

def _annotate(conn, proposal_id, vision):
    proposal = store.proposal(conn, proposal_id, for_update=True)
    if proposal and proposal['status'] == 'pending':
        store.revise_pending_proposal(conn, proposal_id, {**proposal['target'], 'vision': vision}, proposal['content'],
                                      proposal.get('error'))
    conn.commit()


def vision_check(connect, slug, proposal_id, *, opener=None):
    """Have the Continuity Supervisor's vision model look at the proposal's contact sheet; store its note on the proposal.

    Governed like continuity grading (take_grader: the qa_critic's endpoint, ProviderAdmission, privacy) and run under
    the GPU arbiter. Never decides: the note is shown to the director next to the preview. Returns the annotation."""
    from project_assistant import agent_registry, agent_runtime, privacy, providers, take_grader
    from project_assistant import execution_governance as governance
    conn = connect()
    try:
        proposal = store.proposal(conn, proposal_id)
        target = (proposal or {}).get('target') or {}
        preview = target.get('preview') or {}
        if not proposal or proposal['slug'] != slug or proposal['status'] != 'pending' or not preview.get('assetId'):
            conn.rollback()
            return None

        def skipped(reason):
            note = {'status': 'skipped', 'reason': reason, 'checkedAt': story.now()}
            _annotate(conn, proposal_id, note)
            return note
        if privacy.mode(conn, slug) != 'full_access':
            return skipped('Numeric masking does not permit sending images to a vision model.')
        profile = agent_registry.get_agent(conn, slug, 'qa_critic')
        if not profile or not profile.get('enabled', True):
            return skipped('This production has no enabled Continuity Supervisor.')
        config = agent_runtime.provider_for(profile)
        if config.kind != 'openai_compat':
            return skipped('The Continuity Supervisor has no OpenAI-compatible vision endpoint.')
        found = repo.get_asset(conn, slug, preview['assetId'])
        if not found:
            return skipped('The preview image is gone.')
        image, comfy = bytes(found[1]), take_grader.comfy_url(conn, slug)
        conn.commit()  # no transaction across the GPU wait or inference
        job = {'gradeId': f'previs_check_{proposal_id}', 'requestedBy': proposal['owner_id'], 'slug': slug, 'startedAt': story.now()}
        admission = governance.ProviderAdmission(take_grader.grading_context(job, connect), profile, config, 'grader_check',
                                                 purpose='previs_check')
        text = 'Plan summary: ' + (proposal.get('content') or '') + '\nOperations: ' + json.dumps(target.get('ops'), ensure_ascii=False)
        with take_grader._Phase() as phase:
            phase.hold(config, comfy, on_wait=lambda: None)
            result = providers.run_openai_compat_turn(
                config=dataclasses.replace(config, effort='low'), instructions=VISION_RUBRIC, turn_text=text, timeout=VISION_TIMEOUT,
                tool_specs=[], call_tool=lambda *_: (_ for _ in ()).throw(ValueError('The previs check cannot call tools.')),
                images=['data:image/png;base64,' + base64.b64encode(image).decode('ascii')], admission=admission,
                **({'opener': opener} if opener else {}))
        if result.status != 'ok':
            raise ValueError('The vision model did not answer: ' + str(result.error or result.status))
        answer = re.sub(r'(?s)<think>.*?</think>', '', result.answer or '')
        match = re.search(r'(?s)\{.*\}', answer)
        parsed = json.loads(match[0]) if match else {}
        issues = [str(item)[:300] for item in parsed.get('issues') or [] if str(item).strip()][:8] if isinstance(parsed, dict) else []
        note = {'status': 'checked', 'model': config.model, 'checkedAt': story.now(),
                'faceReadable': parsed.get('faceReadable') if isinstance(parsed, dict) and isinstance(parsed.get('faceReadable'), bool) else None,
                'issues': issues, 'note': str((parsed or {}).get('note') or '')[:500] if isinstance(parsed, dict) else answer[:500]}
        _annotate(conn, proposal_id, note)
        return note
    except Exception as exc:  # noqa: BLE001 - an annotation, never a failure of the proposal
        conn.rollback()
        note = {'status': 'failed', 'error': str(exc)[:300], 'checkedAt': story.now()}
        try:
            _annotate(conn, proposal_id, note)
        except Exception:  # noqa: BLE001
            conn.rollback()
        return note
    finally:
        conn.close()


def start_vision_check(slug, proposal_id):
    from project_docs import http
    threading.Thread(target=vision_check, args=(http.open_connection, slug, proposal_id), name='previs-check', daemon=True).start()


from project_assistant import tool_registry  # noqa: E402  (registration lives in the declarative registry)
HANDLERS = tool_registry.handlers(__name__, globals())
