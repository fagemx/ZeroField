"""Crew evaluation set: case loader, validators, scorer and runner (SPEC_20 R42).

Three crew jobs are evaluated on hard cases (front-facing performances, high tension, visible emotion):

    beats       shot text -> beat sheet               (SPEC_20 4.4; R7, R19)
    blocking    shot + cast + set -> 3D operations    (SPEC_20 4.6; R20, R27)
    continuity  adjacent shots -> seam findings       (SPEC_20 R42; the seam check of SPEC_19 R17)

Cases live in research/crew_eval/cases/<type>.json (inputs as the job receives them, hard constraints, graded soft
criteria and a reference answer). A job function maps a case input to the job's JSON output; this script validates the
output, scores it and writes a JSON report. It makes no network or model calls: the model runs happen on the GPU later,
through --job (a callable) or --canned (outputs saved by an earlier run).

    python -X utf8 scripts/crew_eval.py --reference                        # the reference answers must score 100%
    python -X utf8 scripts/crew_eval.py --canned runs/qwen3.8-27b-a --report reports/qwen3.8-27b-a.json
    python -X utf8 scripts/crew_eval.py --job my_adapter:run_job --label "qwen3.8:27b prompts v2" --save runs/v2
    python -X utf8 scripts/crew_eval.py --check-cases                      # the case files are well formed

Scoring: every output is first checked against the hard constraints (JSON shape, SPEC_20 4.4 / 4.6 rules, no invented
findings). One failed hard check zeroes the case: that output would fail the job's validation and fall back to the
rule path (SPEC_20 decision 12). A case that passes scores its soft criteria, a weighted fraction in 0..1.
"""
from __future__ import annotations

import argparse
import copy
import datetime
import importlib
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = ROOT / 'research' / 'crew_eval' / 'cases'
PLAN_JS = ROOT / 'ui' / 'src' / 'previs' / 'plan.js'
TYPES = ('beats', 'blocking', 'continuity')
CASES_SCHEMA = 'zerofield.crew_eval.cases/1'
REPORT_SCHEMA = 'zerofield.crew_eval.report/1'


# ---------- vocabulary: the stage's own, read from ui/src/previs/plan.js so the two cannot drift apart ----------

def _plan_vocab(name):
    match = re.search(r'export const %s = \[([^\]]*)\]' % name, PLAN_JS.read_text(encoding='utf-8'))
    if not match:
        raise RuntimeError(f'{PLAN_JS.relative_to(ROOT).as_posix()} no longer exports {name} as a plain array')
    items = [part.strip() for part in match.group(1).split(',') if part.strip()]
    return tuple(int(item) if re.fullmatch(r'-?\d+', item) else item.strip('\'"') for item in items)


LENSES = _plan_vocab('LENSES')        # mm
MOVES = _plan_vocab('MOVES')
DURATIONS = _plan_vocab('DURATIONS')  # seconds a shot can last
SETS = _plan_vocab('SETS')            # stages the previs can build
FACINGS = _plan_vocab('FACINGS')

# What a place op may point at, per stage: the observatory's anchors and boxes (plan.js SCENE_ANCHORS, SCENE_BOXES; "window"
# is the shorthand SPEC_20 4.6 writes for window_glass), the parallax set's three card roles, nothing on the empty stage.
STAGE_TARGETS = {
    'observatory': ('console', 'plinth', 'dial', 'recorder', 'console_edge', 'window_glass', 'window'),
    'parallax': ('far', 'mid', 'near'),
    'empty': (),
}
# Camera vocabulary of the 4.6 op. 4.6 names only "medium" and "low"; the rest is this set's assumption until the solver lands.
SIZES = ('wide', 'full', 'medium', 'close', 'extreme_close')
ANGLES = ('low', 'eye', 'high', 'overhead')
FACE_CAMERA = ('camera', 'room')      # a place op's facing toward the lens (plan.js: facing "room" is the camera side)
ALIASES = {'window': 'window_glass'}  # SPEC_20 4.6 writes "window" for the observatory's window_glass anchor
MAX_OPS, MAX_OFFSET = 32, 8.0
RETIME_BEAT_BASE = 1                  # retime.beat counts the 3D Stage's acting beats from 1 (SPEC_20 4.6)
SKILLS = ('standIdle', 'walkTo', 'reachGrip', 'turnLook', 'kneelDown')  # plan.js compileMotionSkills: one acting beat each

KINDS = ('position', 'wardrobe', 'prop', 'lighting', 'gaze', 'screen_direction', 'hair_makeup', 'set_dressing', 'body_state', 'weather')
SEVERITIES = ('minor', 'major')
TRANSITIONS = ('continuous', 'time_jump', 'scene_change')

MIN_BEAT_SECONDS = 0.5
TOLERANCE = 0.005                     # seconds: beat times are written to two decimals at most

TAG = re.compile(r'@[A-Za-z][A-Za-z0-9]*(?:-\d+)?(?::[A-Za-z0-9_]+)?(?:\.[a-z]+)?')
TAKE_REF = re.compile(r'@S\d+\.(?:start|end)')
CAST_CODE = re.compile(r'@CAST-\d{1,4}')
CAMERA_KEY = re.compile(r'K\d{1,2}')
LENS_MENTION = re.compile(r'(\d{2,3})\s*mm\b', re.I)
# Camera makers and models. A video model letters them onto props (Phase 2: "RED V-RAPTOR" on a recorder), so a beat sheet
# keeps the lens look and drops the brand.
BRAND = re.compile(
    r'\b(?:ARRI|Alexa|Panavision|Panaflex|DXL2?|Sony Venice|Venice 2|V-?Raptor|RED (?:Komodo|Epic|Dragon|Monstro|Helium|Weapon|Scarlet)|'
    r'Blackmagic|URSA|Canon|Nikon|Leica|Zeiss|Cooke|Angenieux|Fujifilm|Fujinon|Kodak|Hasselblad|Bolex|Aaton|GoPro|DJI|Steadicam)\b', re.I)
# The words that read as each camera move (the keyword families plan.js planFromSlate uses for Camera Motion).
MOVE_WORDS = {
    'pushin': r'push(?:es|ed|ing)?[- ]in|dolly(?:ing|s)? in|creep(?:s|ing)? in|move[sd]? in|closes? in|zoom(?:s|ing)? in|tighten',
    'pullout': r'pull(?:s|ed|ing)?[- ](?:out|back)|dolly(?:ing|s)? out|reveal|widen|retreat',
    'orbit': r'orbit|\barc(?:s|ing)?\b|circl(?:e|es|ing)',
    'crane': r'crane|\brises?\b|\brising\b|\bjib\b|boom|tilt(?:s|ing)? up',
    'track': r'track(?:s|ing)?\b|truck(?:s|ing)?\b|\bfollow|lateral|slides? (?:left|right)',
    'static': r'static|locked[- ]off|locked down|tripod|holds? (?:steady|still|on)|does not move|steady',
}


# ---------- small helpers ----------

def _is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_int(value):
    return (isinstance(value, int) and not isinstance(value, bool)) or (isinstance(value, float) and math.isfinite(value) and value.is_integer())


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _alias(name):
    return ALIASES.get(name, name) if isinstance(name, str) else name


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def tags_in(text):
    return set(TAG.findall(text))


def _norm(text):
    text = text.translate({0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"', 0x2013: '-', 0x2014: '-'})
    return re.sub(r'\s+', ' ', text).strip().lower()


def _hit(patterns, text):
    return any(re.search(pattern, text, re.I) for pattern in patterns)


def _keys(value, required, allowed=None):
    """Problems with a dict's keys: missing ones, and any outside allowed (default: required)."""
    allowed = set(required) if allowed is None else set(allowed)
    problems = [f'missing "{key}"' for key in sorted(set(required) - set(value))]
    problems += [f'unexpected "{key}"' for key in sorted(set(value) - allowed)]
    return problems


class Checks:
    """An ordered list of named checks; every check is listed, whether it passed or not."""

    def __init__(self):
        self.items = []

    def add(self, check_id, ok, detail=''):
        self.items.append({'id': check_id, 'ok': bool(ok), 'detail': '' if ok else str(detail)[:400]})

    def skip(self, ids, why='not evaluated: the output has the wrong shape'):
        for check_id in ids:
            self.add(check_id, False, why)

    def ok(self):
        return all(item['ok'] for item in self.items)


# ---------- beats ----------

BEATS_AFTER_SCHEMA = ('starts_at_zero', 'contiguous', 'ends_at_duration', 'beat_length', 'beat_count', 'tags_kept',
                      'no_unknown_tags', 'no_camera_brands', 'lens_in_lenses')


def _beats_schema(out):
    if not isinstance(out, dict):
        return ['the output is not a JSON object']
    problems = _keys(out, ('setup', 'beats', 'sound', 'constraints'))
    if not _text(out.get('setup')):
        problems.append('"setup" is not a non-empty string')
    if not isinstance(out.get('sound'), str):
        problems.append('"sound" is not a string')
    constraints = out.get('constraints')
    if not isinstance(constraints, list) or not all(_text(item) for item in constraints):
        problems.append('"constraints" is not a list of non-empty strings')
    beats = out.get('beats')
    if not isinstance(beats, list) or not beats:
        problems.append('"beats" is not a non-empty list')
    else:
        for index, beat in enumerate(beats, 1):
            if not isinstance(beat, dict):
                problems.append(f'beat {index} is not an object')
                continue
            problems += [f'beat {index}: {item}' for item in _keys(beat, ('from', 'to', 'camera', 'action'))]
            if not (_is_num(beat.get('from')) and _is_num(beat.get('to'))):
                problems.append(f'beat {index}: "from"/"to" are not numbers')
            if not (_text(beat.get('camera')) and _text(beat.get('action'))):
                problems.append(f'beat {index}: "camera"/"action" are not non-empty strings')
    return problems


def beat_texts(out):
    return [f"{beat['camera']} {beat['action']}" for beat in out['beats']]


def beats_scope(out, scope):
    """The part of a beat sheet a soft criterion reads."""
    beats = out['beats']
    if scope == 'setup':
        return out['setup']
    if scope == 'sound':
        return out['sound']
    if scope == 'constraints':
        return '\n'.join(out['constraints'])
    if scope == 'beats':
        return '\n'.join(beat_texts(out))
    if scope in ('first', 'last'):
        return beat_texts(out)[0 if scope == 'first' else -1]
    if scope == 'actions':
        return '\n'.join(beat['action'] for beat in beats)
    if scope == 'cameras':
        return '\n'.join(beat['camera'] for beat in beats)
    one = re.fullmatch(r'beat:(\d+)', scope)
    if one:
        index = int(one.group(1)) - 1
        return beat_texts(out)[index] if 0 <= index < len(beats) else ''
    return '\n'.join([out['setup'], *beat_texts(out), out['sound'], *out['constraints']])  # "all"


def validate_beats(case, out):
    inp, hard = case['input'], case['expect']['hard']
    checks = Checks()
    problems = _beats_schema(out)
    checks.add('schema', not problems, '; '.join(problems[:5]))
    if problems:
        checks.skip(BEATS_AFTER_SCHEMA)
        return checks.items
    seconds, beats = inp['shot']['seconds'], out['beats']
    checks.add('starts_at_zero', abs(beats[0]['from']) <= TOLERANCE, f"the first beat starts at {beats[0]['from']}, not 0")
    bad = [i for i, beat in enumerate(beats, 1) if beat['to'] <= beat['from'] or (i > 1 and abs(beat['from'] - beats[i - 2]['to']) > TOLERANCE)]
    checks.add('contiguous', not bad, f'beat(s) {bad} leave a gap, overlap the one before, or end before they start')
    checks.add('ends_at_duration', abs(beats[-1]['to'] - seconds) <= TOLERANCE, f"the last beat ends at {beats[-1]['to']}, the shot lasts {seconds} s")
    short = [i for i, beat in enumerate(beats, 1) if beat['to'] - beat['from'] < MIN_BEAT_SECONDS - TOLERANCE]
    checks.add('beat_length', not short, f'beat(s) {short} are shorter than {MIN_BEAT_SECONDS} s')
    low, high = hard['beats']
    checks.add('beat_count', low <= len(beats) <= high, f'{len(beats)} beats; this shot takes {low} to {high}')
    text = beats_scope(out, 'all')
    found = tags_in(text)
    missing = sorted(tags_in(inp['shot']['text']) - found)
    checks.add('tags_kept', not missing, f'dropped the @ tag(s) {missing}')
    unknown = sorted(found - tags_in('\n'.join(_strings(inp))))
    checks.add('no_unknown_tags', not unknown, f'invented the @ tag(s) {unknown}')
    brands = sorted({match.group(0) for match in BRAND.finditer(text)})
    checks.add('no_camera_brands', not brands, f'names camera brand(s) {brands}')
    lenses = sorted({int(n) for n in LENS_MENTION.findall(text)} - set(LENSES))
    checks.add('lens_in_lenses', not lenses, f'lens(es) {lenses} mm are not among {list(LENSES)}')
    return checks.items


def detected_moves(text):
    return {move for move, pattern in MOVE_WORDS.items() if re.search(pattern, text, re.I)}


def soft_beats(case, out):
    results = []
    for spec in case['expect']['soft']:
        kind, scope = spec['check'], spec.get('scope', 'all')
        texts = beat_texts(out)
        if kind == 'contains':
            value = 1.0 if _hit(spec['any'], beats_scope(out, scope)) else 0.0
        elif kind == 'forbids':
            value = 0.0 if _hit(spec['none'], beats_scope(out, scope)) else 1.0
        elif kind == 'ordered':
            position, hits = 0, 0
            for group in spec['groups']:
                at = next((i for i in range(position, len(texts)) if _hit(group, texts[i])), None)
                if at is not None:
                    hits, position = hits + 1, at
            value = hits / len(spec['groups'])
        elif kind == 'event_time':
            beat = next((b for b, text in zip(out['beats'], texts) if re.search(spec['pattern'], text, re.I)), None)
            value = 1.0 if beat and spec['between'][0] <= beat['from'] <= spec['between'][1] else 0.0
        elif kind == 'each_beat':
            value = sum(1 for text in texts if _hit(spec['any'], text)) / len(texts)
        elif kind == 'camera_move':
            value = 1.0 if set(spec['any']) & detected_moves(beats_scope(out, scope if 'scope' in spec else 'cameras')) else 0.0
        elif kind == 'quotes':
            haystack = _norm(beats_scope(out, scope))
            value = sum(1 for quote in spec['texts'] if _norm(quote) in haystack) / len(spec['texts'])
        elif kind == 'beat_lengths':
            lengths = [beat['to'] - beat['from'] for beat in out['beats']]
            value = sum(1 for n in lengths if spec.get('min', 0) - TOLERANCE <= n <= spec.get('max', 1e9) + TOLERANCE) / len(lengths)
        else:
            raise ValueError(f'unknown beats criterion {kind!r}')
        results.append({'id': spec['id'], 'weight': spec['weight'], 'value': round(value, 4), 'desc': spec['desc']})
    return results


# ---------- blocking ----------

BLOCKING_AFTER_SCHEMA = ('shot_id', 'base_revision', 'op_schema', 'camera_lens', 'camera_move', 'camera_keys', 'retime_valid',
                         'camera_single', 'cast_known', 'cast_placed', 'targets_known', 'required_ops')
OP_FIELDS = {  # op -> (required fields, optional fields)
    'place': (('op', 'cast', 'relativeTo', 'offset', 'facing'), ()),
    'camera': (('op', 'size', 'angle', 'lens', 'move'), ('from', 'to')),
    'retime': (('op', 'beat', 'at'), ()),
}


def _blocking_shape(out):
    if not isinstance(out, dict):
        return ['the output is not a JSON object']
    problems = _keys(out, ('shotId', 'baseRevision', 'ops'))
    ops = out.get('ops')
    if not isinstance(ops, list) or not ops:
        problems.append('"ops" is not a non-empty list')
    elif len(ops) > MAX_OPS:
        problems.append(f'{len(ops)} ops; at most {MAX_OPS}')
    elif not all(isinstance(op, dict) and isinstance(op.get('op'), str) for op in ops):
        problems.append('an op is not an object with a string "op"')
    return problems


def _op_problems(op, index):
    """(category, message) for everything wrong with one op."""
    found, name = [], op['op']
    if name not in OP_FIELDS:
        return [('op_schema', f'op {index}: unknown op "{name}"')]
    required, optional = OP_FIELDS[name]
    found += [('op_schema', f'op {index} ({name}): {item}') for item in _keys(op, required, required + optional)]
    label = f'op {index} ({name})'
    if name == 'place':
        if 'cast' in op and not (isinstance(op['cast'], str) and CAST_CODE.fullmatch(op['cast'])):
            found.append(('op_schema', f'{label}: "cast" is not a cast code like @CAST-01'))
        if 'relativeTo' in op and not _text(op['relativeTo']):
            found.append(('op_schema', f'{label}: "relativeTo" is not a name'))
        if 'facing' in op and not _text(op['facing']):
            found.append(('op_schema', f'{label}: "facing" is not a name'))
        offset = op.get('offset')
        if 'offset' in op and not (isinstance(offset, list) and len(offset) == 2 and all(_is_num(v) and abs(v) <= MAX_OFFSET for v in offset)):
            found.append(('op_schema', f'{label}: "offset" is not [x, z] in metres within +-{MAX_OFFSET}'))
    elif name == 'camera':
        for field, allowed in (('size', SIZES), ('angle', ANGLES)):
            if field in op and op[field] not in allowed:
                found.append(('op_schema', f'{label}: "{field}" {op[field]!r} is not one of {list(allowed)}'))
        if 'lens' in op and not (_is_int(op['lens']) and int(op['lens']) in LENSES):
            found.append(('camera_lens', f'{label}: lens {op["lens"]!r} is not one of {list(LENSES)}'))
        if 'move' in op and op['move'] not in MOVES:
            found.append(('camera_move', f'{label}: move {op["move"]!r} is not one of {list(MOVES)}'))
        for field in ('from', 'to'):
            if field in op and not (isinstance(op[field], str) and CAMERA_KEY.fullmatch(op[field])):
                found.append(('op_schema', f'{label}: "{field}" is not a camera key like K1'))
        start, end = op.get('from'), op.get('to')
        if op.get('move') in MOVES and all(v is None or isinstance(v, str) for v in (start, end)):
            if op['move'] == 'static' and end is not None and start != end:
                found.append(('camera_keys', f'{label}: a static camera holds one key, not {start} to {end}'))
            if op['move'] != 'static' and not (start and end and start != end):
                found.append(('camera_keys', f'{label}: a {op["move"]} needs two different camera keys (from, to)'))
    else:  # retime
        if 'beat' in op and not (isinstance(op['beat'], int) and not isinstance(op['beat'], bool) and op['beat'] >= RETIME_BEAT_BASE):
            found.append(('op_schema', f'{label}: "beat" is not a whole beat number from {RETIME_BEAT_BASE}'))
        if 'at' in op and not (_is_num(op['at']) and 0 <= op['at'] <= 1):
            found.append(('retime_valid', f'{label}: "at" is not a fraction of the shot between 0 and 1'))
    return found


def validate_blocking(case, out):
    inp, hard = case['input'], case['expect']['hard']
    checks = Checks()
    problems = _blocking_shape(out)
    checks.add('schema', not problems, '; '.join(problems[:5]))
    if problems:
        checks.skip(BLOCKING_AFTER_SCHEMA)
        return checks.items
    ops = out['ops']
    checks.add('shot_id', out['shotId'] == inp['shot']['id'], f"shotId {out['shotId']!r}, the job was given {inp['shot']['id']!r}")
    revision = out['baseRevision']
    checks.add('base_revision', isinstance(revision, int) and not isinstance(revision, bool) and revision == inp['base_revision'],
               f"baseRevision {revision!r}, the job was given {inp['base_revision']}")
    found = {}
    for index, op in enumerate(ops, 1):
        for category, message in _op_problems(op, index):
            found.setdefault(category, []).append(message)
    beats = inp.get('beats')
    for op in ops:
        if op['op'] == 'retime' and beats is not None and isinstance(op.get('beat'), int) and op['beat'] - RETIME_BEAT_BASE >= len(beats):
            found.setdefault('retime_valid', []).append(f'retime beat {op["beat"]}: the plan has {len(beats)} acting beats')
    for category in ('op_schema', 'camera_lens', 'camera_move', 'camera_keys', 'retime_valid'):
        checks.add(category, category not in found, '; '.join(found.get(category, [])[:4]))
    cameras = [op for op in ops if op['op'] == 'camera']
    checks.add('camera_single', len(cameras) == 1, f'{len(cameras)} camera ops; a shot has exactly one')
    cast = [c['code'] for c in inp['cast']]
    places = [op for op in ops if op['op'] == 'place' and isinstance(op.get('cast'), str)]
    stranger = sorted({op['cast'] for op in places} - set(cast))
    checks.add('cast_known', not stranger, f'places cast code(s) {stranger} that are not in this shot')
    counts = {code: sum(1 for op in places if op['cast'] == code) for code in cast}
    lacking = [code for code, n in counts.items() if n != 1]
    checks.add('cast_placed', not lacking, 'each cast member is placed exactly once: ' + ', '.join(f'{c} x{counts[c]}' for c in lacking))
    named = set(inp['set']['targets']) | set(cast) | {'mark'}
    wrong = []
    for op in places:
        for field, allowed in (('relativeTo', named), ('facing', named | set(FACE_CAMERA))):
            value = _alias(op.get(field))
            if isinstance(value, str) and (value not in allowed or value == op['cast']):
                wrong.append(f'{op["cast"]} {field} {value!r}')
    checks.add('targets_known', not wrong, 'not on this stage (' + ', '.join(sorted(named)) + '): ' + '; '.join(wrong[:4]))
    absent = [name for name in hard.get('require_ops', []) if not any(op['op'] == name for op in ops)]
    checks.add('required_ops', not absent, f'this shot needs a {absent} op')
    return checks.items


def _good_ops(out):
    """The ops that pass their own schema; a malformed op already failed the hard checks and scores nothing."""
    return [op for index, op in enumerate(out['ops'], 1) if not _op_problems(op, index)]


def _separation(places, a, b):
    """Metres between two placed cast members when the ops say so (one relative to the other, or both to the same target)."""
    one, two = places.get(a), places.get(b)
    if not one or not two:
        return None
    if one['relativeTo'] == b:
        return math.hypot(*one['offset'])
    if two['relativeTo'] == a:
        return math.hypot(*two['offset'])
    if one['relativeTo'] == two['relativeTo']:
        return math.hypot(one['offset'][0] - two['offset'][0], one['offset'][1] - two['offset'][1])
    return None


def soft_blocking(case, out):
    ops = _good_ops(out)
    places, camera, results = {op['cast']: op for op in ops if op['op'] == 'place'}, next((op for op in ops if op['op'] == 'camera'), None), []
    for spec in case['expect']['soft']:
        kind, parts = spec['check'], []
        if kind == 'place':
            op = places.get(spec['cast'])
            for field, allowed in (('facing', spec.get('facing_any')), ('relativeTo', spec.get('relativeTo_any'))):
                if allowed is not None:
                    parts.append(bool(op) and _alias(op[field]) in allowed)
            for axis, index in (('x', 0), ('z', 1)):
                if axis in spec:
                    parts.append(bool(op) and spec[axis][0] <= op['offset'][index] <= spec[axis][1])
        elif kind == 'camera':
            for field, allowed in (('size', spec.get('size_any')), ('angle', spec.get('angle_any')),
                                   ('lens', spec.get('lens_any')), ('move', spec.get('move_any'))):
                if allowed is not None:
                    parts.append(bool(camera) and (int(camera[field]) if field == 'lens' else camera[field]) in allowed)
        elif kind == 'retime':
            low, high = spec['at']
            parts.append(any(op['op'] == 'retime' and op['beat'] == spec['beat'] and low <= op['at'] <= high for op in ops))
        elif kind == 'distance':
            gap = _separation(places, spec['a'], spec['b'])
            parts.append(gap is not None and spec.get('min', 0) <= gap <= spec.get('max', 1e9))
        else:
            raise ValueError(f'unknown blocking criterion {kind!r}')
        results.append({'id': spec['id'], 'weight': spec['weight'], 'value': round(sum(parts) / len(parts), 4), 'desc': spec['desc']})
    return results


# ---------- continuity ----------

CONTINUITY_AFTER_SCHEMA = ('critical_found', 'no_invented')


def _continuity_schema(out, shot_ids, subjects):
    if not isinstance(out, dict):
        return ['the output is not a JSON object']
    problems = _keys(out, ('score', 'findings'))
    if not (isinstance(out.get('score'), int) and not isinstance(out.get('score'), bool) and 0 <= out['score'] <= 100):
        problems.append('"score" is not a whole number from 0 to 100')
    findings = out.get('findings')
    if not isinstance(findings, list) or len(findings) > 20:
        return problems + ['"findings" is not a list of at most 20']
    for index, item in enumerate(findings, 1):
        if not isinstance(item, dict):
            problems.append(f'finding {index} is not an object')
            continue
        problems += [f'finding {index}: {text}' for text in _keys(item, ('kind', 'shots', 'subject', 'severity', 'detail'))]
        if item.get('kind') not in KINDS:
            problems.append(f'finding {index}: kind {item.get("kind")!r} is not one of {list(KINDS)}')
        if item.get('severity') not in SEVERITIES:
            problems.append(f'finding {index}: severity {item.get("severity")!r} is not one of {list(SEVERITIES)}')
        if item.get('subject') not in subjects:
            problems.append(f'finding {index}: subject {item.get("subject")!r} is not in the bible or "scene"')
        shots = item.get('shots')
        if not (isinstance(shots, list) and 1 <= len(shots) <= 3 and all(s in shot_ids for s in shots)):
            problems.append(f'finding {index}: "shots" must list 1 to 3 shot ids of this case ({shot_ids})')
        if not _text(item.get('detail')):
            problems.append(f'finding {index}: "detail" is empty')
    return problems


def _set_wide(subject):
    return subject == 'scene' or subject.startswith('@SET-')


def _subject_ok(wanted, actual):
    """An entry names one subject or a list of acceptable ones; the set and "scene" stand for each other."""
    return any(actual == option or (_set_wide(option) and _set_wide(actual)) for option in (wanted if isinstance(wanted, list) else [wanted]))


def _same(entry, finding):
    return (finding['kind'] == entry['kind'] and _subject_ok(entry['subject'], finding['subject'])
            and set(entry['shots']) <= set(finding['shots']))


def match_findings(expect, findings):
    """(planted id -> the findings that report it, [(finding, why it is invented)])."""
    found = {entry['id']: [f for f in findings if _same(entry, f)] for entry in expect['planted']}
    invented = []
    for finding in findings:
        if any(_same(entry, finding) for entry in [*expect['planted'], *expect.get('tolerated', [])]):
            continue
        decoy = next((entry for entry in expect.get('justified', []) if _same(entry, finding)), None)
        invented.append((finding, f"the change is justified: {decoy['why']}" if decoy else 'matches no planted error'))
    return found, invented


def validate_continuity(case, out):
    inp, expect = case['input'], case['expect']
    checks = Checks()
    problems = _continuity_schema(out, [s['id'] for s in inp['shots']], {b['code'] for b in inp['bible']} | {'scene'})
    checks.add('schema', not problems, '; '.join(problems[:5]))
    if problems:
        checks.skip(CONTINUITY_AFTER_SCHEMA)
        return checks.items
    found, invented = match_findings(expect, out['findings'])
    missed = [entry['id'] for entry in expect['planted'] if entry['critical'] and not found[entry['id']]]
    checks.add('critical_found', not missed, f'missed the planted error(s) {missed}')
    checks.add('no_invented', not invented, '; '.join(f"{f['kind']} {f['subject']} {f['shots']}: {why}" for f, why in invented[:3]))
    return checks.items


def soft_continuity(case, out):
    expect, results = case['expect'], []
    found, _ = match_findings(expect, out['findings'])
    for entry in expect['planted']:
        hits = found[entry['id']]
        value = 0.0
        if hits:
            severe = any(f['severity'] == entry['severity'] for f in hits)
            evident = any(_hit(entry['evidence_any'], f['detail']) for f in hits)
            value = 0.6 + (0.2 if severe else 0) + (0.2 if evident else 0)
        results.append({'id': f"planted:{entry['id']}", 'weight': entry['weight'], 'value': round(value, 4),
                        'desc': f"find the {entry['severity']} {entry['kind']} error on "
                                f"{'/'.join(entry['subject']) if isinstance(entry['subject'], list) else entry['subject']} at {'/'.join(entry['shots'])}"})
    for spec in expect.get('soft', []):
        if spec['check'] != 'score_between':
            raise ValueError(f'unknown continuity criterion {spec["check"]!r}')
        results.append({'id': spec['id'], 'weight': spec['weight'], 'desc': spec['desc'],
                        'value': 1.0 if spec['between'][0] <= out['score'] <= spec['between'][1] else 0.0})
    return results


# ---------- scoring one case ----------

VALIDATORS = {'beats': validate_beats, 'blocking': validate_blocking, 'continuity': validate_continuity}
SOFT = {'beats': soft_beats, 'blocking': soft_blocking, 'continuity': soft_continuity}


def parse_output(output):
    """(parsed value, problem): None for no output, text is parsed as JSON, anything else is taken as is."""
    if output is None:
        return None, 'the job produced no output for this case'
    if isinstance(output, (bytes, bytearray)):
        output = output.decode('utf-8', 'replace')
    if isinstance(output, str):
        try:
            return json.loads(output), ''
        except ValueError as error:
            return None, f'the output is not valid JSON ({error})'
    return output, ''


def evaluate_case(case, output):
    """Hard checks, soft criteria and the score of one job output."""
    parsed, problem = parse_output(output)
    if problem:
        hard, soft = [{'id': 'output', 'ok': False, 'detail': problem}], []
    else:
        try:
            hard = VALIDATORS[case['type']](case, parsed)
        except Exception as error:  # a validator must never take the run down with it
            hard = [{'id': 'validator', 'ok': False, 'detail': f'{type(error).__name__}: {error}'}]
        schema_ok = any(item['id'] == 'schema' and item['ok'] for item in hard)
        soft = SOFT[case['type']](case, parsed) if schema_ok else []
    hard_ok = all(item['ok'] for item in hard)
    total = sum(item['weight'] for item in soft)
    soft_score = sum(item['weight'] * item['value'] for item in soft) / total if total else (1.0 if hard_ok else 0.0)
    return {'id': case['id'], 'type': case['type'], 'title': case['title'], 'hard_ok': hard_ok, 'hard': hard, 'soft': soft,
            'soft_score': round(soft_score, 4), 'score': round(soft_score if hard_ok else 0.0, 4)}


# ---------- cases ----------

def load_cases(types=None, cases_dir=None):
    directory = Path(cases_dir) if cases_dir else CASES_DIR
    cases = []
    for name in types or TYPES:
        document = json.loads((directory / f'{name}.json').read_text(encoding='utf-8'))
        if document.get('schema') != CASES_SCHEMA or document.get('type') != name:
            raise ValueError(f'{name}.json is not a {CASES_SCHEMA} file of type {name}')
        cases += [{**case, 'type': name} for case in document['cases']]
    return cases


def _soft_problems(case_type, spec, tables):
    base = {'id', 'desc', 'weight', 'check'}
    kind = spec.get('check')
    if kind not in tables:
        return [f'soft criterion {spec.get("id")!r}: unknown check {kind!r}']
    required, optional = tables[kind]
    problems = [f'soft criterion {spec.get("id")!r}: {item}' for item in _keys(spec, base | set(required), base | set(required) | set(optional))]
    if not (_text(spec.get('id')) and _text(spec.get('desc')) and _is_num(spec.get('weight')) and spec['weight'] > 0):
        problems.append(f'soft criterion {spec.get("id")!r}: needs id, desc and a positive weight')
    patterns = []
    for key in ('any', 'none', 'pattern'):
        value = spec.get(key)
        patterns += [value] if isinstance(value, str) else value if isinstance(value, list) else []
    patterns += [p for group in spec.get('groups', []) for p in group]
    for pattern in patterns:
        try:
            re.compile(pattern)
        except re.error as error:
            problems.append(f'soft criterion {spec.get("id")!r}: bad regex {pattern!r} ({error})')
    scope = spec.get('scope', 'all')
    if case_type == 'beats' and scope not in ('all', 'setup', 'sound', 'constraints', 'beats', 'actions', 'cameras', 'first', 'last') and not re.fullmatch(r'beat:\d+', scope):
        problems.append(f'soft criterion {spec.get("id")!r}: unknown scope {scope!r}')
    for key in ('between', 'at', 'x', 'z'):
        if key in spec and not (isinstance(spec[key], list) and len(spec[key]) == 2 and all(_is_num(v) for v in spec[key]) and spec[key][0] <= spec[key][1]):
            problems.append(f'soft criterion {spec.get("id")!r}: {key} is not [low, high]')
    return problems


SOFT_TABLES = {
    'beats': {'contains': (('any',), ('scope',)), 'forbids': (('none',), ('scope',)), 'ordered': (('groups',), ()),
              'event_time': (('pattern', 'between'), ()), 'each_beat': (('any',), ()), 'camera_move': (('any',), ('scope',)),
              'quotes': (('texts',), ('scope',)), 'beat_lengths': ((), ('min', 'max'))},
    'blocking': {'place': (('cast',), ('facing_any', 'relativeTo_any', 'x', 'z')),
                 'camera': ((), ('size_any', 'angle_any', 'lens_any', 'move_any')),
                 'retime': (('beat', 'at'), ()), 'distance': (('a', 'b'), ('min', 'max'))},
    'continuity': {'score_between': (('between',), ())},
}


def _codes(items, problems, where):
    if not isinstance(items, list) or not all(isinstance(i, dict) and _text(i.get('code')) and _text(i.get('name')) and _text(i.get('look')) for i in items):
        problems.append(f'{where} is not a list of {{code, name, look}}')
        return set()
    return {i['code'] for i in items}


def check_case(case_type, case):
    """Everything wrong with how a case is written (not with any output), as readable lines."""
    problems = _keys(case, ('id', 'title', 'difficulty', 'input', 'expect', 'reference'), ('id', 'title', 'difficulty', 'input', 'expect', 'reference', 'type'))
    if problems:
        return problems
    inp, expect, name = case['input'], case['expect'], case['id']
    stray = [text[:30] for text in _strings(case) if re.search(r'[\x00-\x1f]', text)]
    if stray:
        problems.append(f'control characters in {stray[:2]} (a regex "\\b" must be written "\\\\b" in JSON)')
    if not re.fullmatch(rf'{case_type}-\d\d-[a-z0-9]+(?:-[a-z0-9]+)*', str(name)):
        problems.append(f'id {name!r} is not {case_type}-NN-slug')
    if not _text(case['title']):
        problems.append('title is empty')
    difficulty = case['difficulty']
    if not (isinstance(difficulty, dict) and difficulty.get('face') == 'front' and difficulty.get('tension') == 'high'
            and _text(difficulty.get('emotion')) and isinstance(difficulty.get('traps'), list) and difficulty['traps']
            and all(_text(t) for t in difficulty['traps']) and not _keys(difficulty, ('face', 'tension', 'emotion', 'traps'))):
        problems.append('difficulty must be {face: "front", tension: "high", emotion, traps: [..]}: cases are hard on purpose')
    if not isinstance(case['reference'], dict):
        problems.append('reference is not an object')
    if not isinstance(inp, dict) or not isinstance(expect, dict):
        return problems + ['input and expect must be objects']
    soft = expect.get('soft', [])
    if not isinstance(soft, list):
        return problems + ['expect.soft is not a list']
    for spec in soft:
        problems += _soft_problems(case_type, spec, SOFT_TABLES[case_type])
    ids = [spec.get('id') for spec in soft]
    if len(ids) != len(set(ids)):
        problems.append('soft criterion ids repeat')
    return problems + {'beats': _check_beats_case, 'blocking': _check_blocking_case, 'continuity': _check_continuity_case}[case_type](inp, expect, case)


def _check_beats_case(inp, expect, case):
    problems = _keys(inp, ('shot', 'cast', 'set', 'props', 'previous_shot', 'next_shot'))
    problems += _keys(expect, ('hard', 'soft'))
    if problems:
        return problems
    shot = inp['shot']
    problems += [f'shot: {item}' for item in _keys(shot, ('id', 'seconds', 'text'), ('id', 'seconds', 'text', 'optical_rig', 'camera_motion'))]
    if shot.get('seconds') not in DURATIONS:
        problems.append(f'shot.seconds {shot.get("seconds")!r} is not one of {list(DURATIONS)}')
    if not _text(shot.get('text')):
        problems.append('shot.text is empty')
        return problems
    codes = _codes(inp['cast'], problems, 'cast') | _codes(inp['props'], problems, 'props') | _codes([inp['set']], problems, 'set')
    for tag in tags_in(shot['text']):
        if tag.split(':')[0] not in codes and not TAKE_REF.fullmatch(tag):
            problems.append(f'shot.text tag {tag} names nothing in the input')
    for side in ('previous_shot', 'next_shot'):
        if inp[side] is not None and not (isinstance(inp[side], dict) and _text(inp[side].get('id')) and _text(inp[side].get('text'))):
            problems.append(f'{side} must be null or {{id, text}}')
    hard = expect['hard']
    if _keys(hard, ('beats',)) or not (isinstance(hard['beats'], list) and len(hard['beats']) == 2 and 1 <= hard['beats'][0] <= hard['beats'][1]):
        problems.append('expect.hard must be {beats: [min, max]}')
    return problems


def _check_blocking_case(inp, expect, case):
    problems = _keys(inp, ('shot', 'cast', 'set', 'base_revision'), ('shot', 'cast', 'set', 'base_revision', 'beats'))
    problems += _keys(expect, ('hard', 'soft'))
    if problems:
        return problems
    problems += [f'shot: {item}' for item in _keys(inp['shot'], ('id', 'seconds', 'text'))]
    if inp['shot'].get('seconds') not in DURATIONS:
        problems.append(f'shot.seconds {inp["shot"].get("seconds")!r} is not one of {list(DURATIONS)}')
    cast = _codes(inp['cast'], problems, 'cast')
    if not cast or any(not CAST_CODE.fullmatch(code) for code in cast):
        problems.append('cast needs @CAST-NN codes')
    stage = inp['set']
    problems += [f'set: {item}' for item in _keys(stage, ('code', 'name', 'stage', 'targets'))]
    if stage.get('stage') not in SETS or not set(stage.get('targets', [])) <= set(STAGE_TARGETS.get(stage.get('stage'), ())):
        problems.append(f'set.stage must be one of {list(SETS)} with targets from that stage ({STAGE_TARGETS})')
    if not (isinstance(inp['base_revision'], int) and inp['base_revision'] >= 0):
        problems.append('base_revision is not a whole number')
    beats = inp.get('beats')
    if beats is not None and not (isinstance(beats, list) and beats and all(isinstance(b, dict) and _is_num(b.get('from')) and _is_num(b.get('to')) and _text(b.get('action')) for b in beats)):
        problems.append('beats is not a list of {from, to, skill, action}')
    elif beats is not None:
        # The 3D Stage's acting beats (SPEC_20 4.6 retime): the plan's own actor's skills, in order, inside the shot.
        if any(b.get('skill') not in SKILLS for b in beats):
            problems.append(f'each beat names its 3D Stage skill, one of {list(SKILLS)}')
        if any(not 0 <= b['from'] < b['to'] <= inp['shot']['seconds'] for b in beats) or any(a['to'] > b['from'] for a, b in zip(beats, beats[1:])):
            problems.append('beats run in order inside the shot without overlapping')
    hard = expect['hard']
    problems += _keys(hard, (), ('require_ops',))
    require = hard.get('require_ops', [])
    if not (isinstance(require, list) and set(require) <= {'retime'}):
        problems.append('expect.hard.require_ops may only list "retime"')
    if 'retime' in require and beats is None:
        problems.append('a case that requires a retime op gives the shot its beats')
    for spec in expect['soft']:
        named = [spec.get('cast')] if spec.get('check') == 'place' else [spec.get('a'), spec.get('b')] if spec.get('check') == 'distance' else []
        problems += [f'soft criterion {spec["id"]!r}: {code!r} is not in this shot' for code in named if code not in cast]
        if spec.get('check') == 'retime' and beats is not None and not 1 <= spec.get('beat', 0) <= len(beats):
            problems.append(f'soft criterion {spec["id"]!r}: the shot has no beat {spec.get("beat")}')
    return problems


def _check_continuity_case(inp, expect, case):
    problems = _keys(inp, ('bible', 'shots'))
    problems += _keys(expect, ('planted', 'soft'), ('planted', 'tolerated', 'justified', 'soft'))
    if problems:
        return problems
    codes = _codes(inp['bible'], problems, 'bible')
    shots = inp['shots']
    if not (isinstance(shots, list) and len(shots) >= 2):
        return problems + ['a continuity case needs at least two shots']
    for shot in shots:
        problems += [f'shot {shot.get("id")}: {item}' for item in _keys(shot, ('id', 'take', 'seconds', 'transition', 'text', 'cast', 'set', 'first_frame', 'last_frame'))]
        if shot.get('transition') not in TRANSITIONS or shot.get('seconds') not in DURATIONS:
            problems.append(f'shot {shot.get("id")}: transition one of {list(TRANSITIONS)}, seconds one of {list(DURATIONS)}')
        if not all(_text(shot.get(k)) for k in ('id', 'take', 'text', 'first_frame', 'last_frame')) or not set(shot.get('cast', [])) <= codes:
            problems.append(f'shot {shot.get("id")}: empty text, or a cast code outside the bible')
    ids = [shot.get('id') for shot in shots]
    if len(ids) != len(set(ids)):
        problems.append('shot ids repeat')
    keys = []
    for group in ('planted', 'tolerated', 'justified'):
        for entry in expect.get(group, []):
            need = ('kind', 'subject', 'shots') + {'planted': ('id', 'severity', 'critical', 'weight', 'evidence_any'), 'tolerated': (), 'justified': ('why',)}[group]
            problems += [f'{group}: {item}' for item in _keys(entry, need)]
            subjects = entry.get('subject') if isinstance(entry.get('subject'), list) else [entry.get('subject')]
            if entry.get('kind') not in KINDS or not subjects or not set(subjects) <= codes | {'scene'} or not (isinstance(entry.get('shots'), list) and entry['shots'] and set(entry['shots']) <= set(ids)):
                problems.append(f'{group} {entry.get("id", entry.get("kind"))}: kind, subject or shots do not fit the case')
                continue
            if group == 'planted':
                if entry['severity'] not in SEVERITIES or not isinstance(entry['critical'], bool) or not (_is_num(entry['weight']) and entry['weight'] > 0):
                    problems.append(f'planted {entry["id"]}: severity, critical or weight are wrong')
                for pattern in entry['evidence_any']:
                    try:
                        re.compile(pattern)
                    except re.error as error:
                        problems.append(f'planted {entry["id"]}: bad regex {pattern!r} ({error})')
            keys.append((entry['kind'], tuple(sorted(subjects)), tuple(sorted(entry['shots']))))
    if len(keys) != len(set(keys)):
        problems.append('planted, tolerated and justified entries repeat a (kind, subject, shots)')
    if len({e['id'] for e in expect['planted']}) != len(expect['planted']):
        problems.append('planted ids repeat')
    return problems


# ---------- jobs: where the outputs come from ----------

def reference_job(cases):
    """The job that answers every case with its reference answer: the harness's own self-check."""
    answers = {case['id']: case['reference'] for case in cases}
    return lambda case_id, job_type, case_input: copy.deepcopy(answers[case_id])


def canned_job(directory):
    """The job that replays saved outputs: <directory>/<case id>.json (a missing file is a missing output)."""
    base = Path(directory)

    def job(case_id, job_type, case_input):
        path = base / f'{case_id}.json'
        return path.read_text(encoding='utf-8-sig') if path.is_file() else None
    return job


def import_job(spec):
    """MODULE:FUNCTION, called as function(case_id, job_type, case_input) -> the job's JSON output (a dict or JSON text)."""
    module_name, _, function = spec.partition(':')
    if not module_name or not function:
        raise SystemExit('--job takes MODULE:FUNCTION, for example my_adapter:run_job')
    for path in (str(ROOT), str(Path.cwd())):
        if path not in sys.path:
            sys.path.insert(0, path)
    return getattr(importlib.import_module(module_name), function)


def run(cases, job, *, label='', save_dir=None):
    """Run every case through the job, evaluate the outputs and build the report."""
    results = []
    for case in cases:
        try:
            output = job(case['id'], case['type'], copy.deepcopy(case['input']))  # the job never sees expect or reference
        except Exception as error:
            result = evaluate_case(case, None)
            result['hard'][0]['detail'] = f'the job raised {type(error).__name__}: {error}'
            output = None
        else:
            result = evaluate_case(case, output)
        if save_dir and output is not None:
            Path(save_dir).mkdir(parents=True, exist_ok=True)
            text = output if isinstance(output, str) else json.dumps(output, indent=2, ensure_ascii=False, default=str) + '\n'
            (Path(save_dir) / f"{case['id']}.json").write_text(text, encoding='utf-8', newline='\n')
        results.append(result)
    return build_report(results, label)


def _totals(results):
    count = len(results)
    points = sum(item['score'] for item in results)
    return {'cases': count, 'hard_pass': sum(1 for item in results if item['hard_ok']),
            'hard_pass_rate': round(sum(1 for item in results if item['hard_ok']) / count, 4) if count else 0.0,
            'points': round(points, 4), 'max_points': count, 'percent': round(100 * points / count, 2) if count else 0.0,
            'mean_soft': round(sum(item['soft_score'] for item in results) / count, 4) if count else 0.0}


def build_report(results, label=''):
    types = {name: {**_totals([r for r in results if r['type'] == name]), 'results': [r for r in results if r['type'] == name]}
             for name in TYPES if any(r['type'] == name for r in results)}
    return {'schema': REPORT_SCHEMA, 'label': label, 'generatedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
            'totals': _totals(results), 'types': types}


def summary(report):
    lines = [f"crew evaluation{' - ' + report['label'] if report['label'] else ''}"]
    for name, block in report['types'].items():
        lines.append(f"  {name:<11} {block['percent']:6.2f}%  hard {block['hard_pass']}/{block['cases']}  soft {block['mean_soft']:.2f}")
        for item in block['results']:
            failed = [f"{c['id']} ({c['detail']})" if c['detail'] else c['id'] for c in item['hard'] if not c['ok']]
            lines.append(f"    {'ok  ' if item['hard_ok'] else 'FAIL'} {item['id']:<44} score {item['score']:.2f} (soft {item['soft_score']:.2f})")
            lines += [f'         hard check failed: {text}' for text in failed[:6]]
    total = report['totals']
    lines.append(f"  {'TOTAL':<11} {total['percent']:6.2f}%  hard {total['hard_pass']}/{total['cases']}  soft {total['mean_soft']:.2f}")
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run the crew evaluation set (SPEC_20 R42). No network, no model calls.')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--canned', metavar='DIR', help='replay saved outputs: DIR/<case id>.json')
    source.add_argument('--job', metavar='MODULE:FUNCTION', help='call function(case_id, job_type, case_input) for every case')
    source.add_argument('--reference', action='store_true', help="answer with each case's reference answer (the harness self-check)")
    source.add_argument('--check-cases', action='store_true', help='only check that the case files are well formed')
    parser.add_argument('--type', action='append', choices=TYPES, help='only this job type (repeatable)')
    parser.add_argument('--case', action='append', metavar='ID', help='only cases whose id starts with this (repeatable)')
    parser.add_argument('--cases-dir', metavar='DIR', help=f'case files (default {CASES_DIR.relative_to(ROOT).as_posix()})')
    parser.add_argument('--label', default='', help='free text for the report: the model, the prompt version')
    parser.add_argument('--report', metavar='PATH', help='write the JSON report here')
    parser.add_argument('--save', metavar='DIR', help='also save every output as DIR/<case id>.json (a canned directory)')
    parser.add_argument('--fail-under', type=float, metavar='PERCENT', help='exit 1 when the total is lower (default 100 for --reference)')
    args = parser.parse_args(argv)
    cases = load_cases(args.type, args.cases_dir)
    if args.case:
        cases = [case for case in cases if any(case['id'].startswith(prefix) for prefix in args.case)]
    if not cases:
        print('no cases selected', file=sys.stderr)
        return 2
    if args.check_cases:
        bad = [f"{case['id']}: {text}" for case in cases for text in check_case(case['type'], case)]
        print('\n'.join(bad) if bad else f'{len(cases)} cases are well formed')
        return 1 if bad else 0
    job = reference_job(cases) if args.reference else canned_job(args.canned) if args.canned else import_job(args.job)
    report = run(cases, job, label=args.label or ('reference answers' if args.reference else ''), save_dir=args.save)
    print(summary(report))
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
        print(f'wrote {args.report}')
    floor = args.fail_under if args.fail_under is not None else 100.0 if args.reference else None
    return 1 if floor is not None and report['totals']['percent'] < floor else 0


if __name__ == '__main__':
    sys.exit(main())
