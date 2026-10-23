"""Per-shot story lineage, bounded impact plans and frozen media provenance.

No inference, billing admission, scheduler, or destructive media operation lives here.
All persistence uses the caller's transaction and existing Story row guards.
"""
from __future__ import annotations
import copy
import re
from project_docs import writing_store as store, writing_structure as structure, repository as repo, story_openapi as story
from project_docs.doc_schema import node_text, doc_text

FIELDS = ('description', 'dialogue')


def _target(conn, scope, ref):
    if not isinstance(ref, dict) or ref.get('kind') not in ('working', 'version'):
        story.invalid('Impact targets are the working screenplay or a shared version.')
    return store.resolve_ref(conn, scope, ref)


def _units(target):
    nodes = {structure.bid(n): node_text(n) for n in target['doc']['content']}
    return [dict(sceneKey=s['sceneKey'], beatKey=b['beatKey'], text='\n'.join(nodes[k] for k in b['blockBids'] if k in nodes))
            for s in target['structure'].get('scenes', []) for b in s.get('beats', [])]


def _source(target, origin):
    """Follow surviving beats and explicit merge lineage only, never display order."""
    units = _units(target)
    beats = origin.get('beatKeys', [])
    scenes = origin.get('sceneKeys', [])
    if beats:
        selected = [next((u for u in units if u['beatKey'] == key), None) for key in beats]
        if any(u is None for u in selected):
            return [], 'source_removed'
        return selected, None
    lineage = target['structure'].get('lineage', {})
    if any(v == 'split:' + key for key in scenes for v in lineage.values()):
        return [], 'ambiguous'
    resolved = [structure.resolve_scene_key(target['structure'], k) for k in scenes]
    if not scenes or None in resolved:
        return [], 'source_removed' if scenes else 'unbound'
    return [u for u in units if u['sceneKey'] in resolved], None


def _source_hash(units):
    # Scene movement is navigation/order metadata, not a change to a beat's text.
    return store.hash_value([{'beatKey': u['beatKey'], 'text': u['text']} for u in units])


def _inputs_hash(target, units):
    inputs = copy.deepcopy(target.get('productionInputs', {}))
    codes = {m[1].upper().replace('#', ':') for u in units for m in story.ASSET_RE.finditer(u['text'])}
    codes |= {c.split(':')[0] for c in codes}
    inputs['assetBindings'] = [b for b in inputs.get('assetBindings', []) if b['assetCode'] in codes]
    return store.hash_value(inputs)


def _fields(shot):
    return {'description': shot['description'], 'dialogue': copy.deepcopy(shot.get('dialogue', []))}


def _legacy_origin(target, shot):
    saved = next((b for b in target['structure'].get('legacyBindings', []) if b['shotId'] == shot['shotId']), {})
    return {'versionId': None, 'mapping': 'scene_only' if saved.get('sceneKey') else 'unbound',
            'sceneKeys': [saved['sceneKey']] if saved.get('sceneKey') else [], 'beatKeys': []}


def _suggest(target, origin, units):
    if origin.get('mergedOrigins'):
        parts = [_suggest(target, old, [u for key in old.get('beatKeys', []) for u in units if u['beatKey'] == key]) for old in origin['mergedOrigins']]
        if any(p is None for p in parts):
            return None
        return {'description': '\n'.join(p['description'] for p in parts), 'dialogue': [v for p in parts for v in p['dialogue']]}
    recipes = origin.get('recipes') or [{'beatKeys': origin.get('beatKeys', []), 'mode': 'scene'}]
    pieces = []
    for recipe in recipes:
        subset = [u for key in recipe.get('beatKeys', []) for u in units if u['beatKey'] == key] if recipe.get('beatKeys') else units
        text = '\n\n'.join(u['text'] for u in subset)
        if recipe.get('mode') == 'scene' and origin.get('bindingMethod') == 'generated':
            text = '\n'.join(story.scene_shot_beats(text, 'scene'))
        if 'segmentIndex' in recipe:
            segments = story.scene_shot_beats(text, recipe['mode'])
            if len(segments) != recipe['segmentCount']:
                return None  # A changed segmentation is not proof of a sub-beat identity.
            text = segments[recipe['segmentIndex']]
        pieces.append(text)
    text = '\n'.join(pieces)
    grammar = story.infer_shot_grammar(text, 0, 1)
    # Explicit production references are retained; no camera/seed/previs is regenerated.
    refs = origin.get('appendedRefs', [])
    explicit = {story.asset_code(m[1]) for m in story.ASSET_RE.finditer(text)}
    prompt = text + (' ' + ' '.join('@' + c for c in refs if c not in explicit) if 'appendedRefs' in origin else '')
    if len(prompt) > 10000:
        store.fail('LIMIT_EXCEEDED', 'Split source text above the shot prompt limit.', 413)
    return {'description': prompt, 'dialogue': grammar['dialogue']}


def alignment(target, shot):
    origin = copy.deepcopy(shot.get('storyOrigin') or _legacy_origin(target, shot))
    units, missing = _source(target, origin)
    current = _fields(shot)
    manual = [f for f in FIELDS if f in origin.get('derivedFields', {}) and current[f] != origin['derivedFields'][f]]
    reasons = []
    if missing:
        reasons.append(missing)
    elif origin.get('mapping') != 'exact':
        reasons.append('ambiguous' if origin.get('mapping') == 'ambiguous' else 'unbound')
    else:
        hashes = [origin.get('fieldOrigins', {}).get(f, origin) for f in FIELDS]
        if any(h.get('sourceTextHash') != _source_hash(units) for h in hashes):
            reasons.append('source_changed')
        if any(h.get('productionInputsHash') != _inputs_hash(target, units) for h in hashes):
            reasons.append('configuration_changed')
        if not all(f in origin.get('derivedFields', {}) for f in FIELDS):
            reasons.append('unknown_derived_base')
        if _suggest(target, origin, units) is None:
            reasons.append('ambiguous')
    if origin.get('bindingMethod') == 'explicit' and not missing:
        suggested = _suggest(target, origin, units)
        manual = list(dict.fromkeys(manual + [f for f in FIELDS if suggested is not None and suggested[f] != current[f]]))
    if manual:
        reasons.append('manual_override')
    kept = shot.get('storyAlignment', {}).get('intentionalDivergence')
    acknowledged = bool(kept and kept.get('sourceState') == missing and kept.get('sourceTextHash') == _source_hash(units)
                        and kept.get('productionInputsHash') == _inputs_hash(target, units)
                        and kept.get('derivedTextHash') == store.hash_value(current))
    priority = ('source_removed', 'ambiguous', 'unbound', 'manual_override', 'source_changed')
    state = 'kept_intentionally' if acknowledged else next((r for r in priority if r in reasons),
            'source_changed' if reasons else 'in_sync')
    media = bool(shot.get('selectedImageUrl') or shot.get('selectedVideoUrl'))
    # Unknown legacy media is never certified as current even after a manual source bind.
    media_state = shot.get('storyAlignment', {}).get('mediaState', 'unknown' if media else 'none')
    result = {'state': state, 'reasons': reasons, 'manualFields': manual,
              'mediaOutdated': bool(media and (reasons or media_state != 'current')), 'mediaState': media_state}
    if kept:
        result['intentionalDivergence'] = copy.deepcopy(kept)
    return {'shotId': shot['shotId'], 'shotIndex': shot['shotIndex'], 'storyOrigin': origin,
            'sourceRef': {'sceneKey': units[0]['sceneKey'], 'beatKey': units[0]['beatKey']} if units else
                         {'sceneKey': origin['sceneKeys'][0], 'beatKey': None} if origin.get('sceneKeys') else None,
            'storyAlignment': result}


def _shot_guard(conn, shot):
    slug, row = story.find_row(conn, shot['shotId'], 'shot')
    return store.hash_value({'cells': row['cells'], 'headers': row['headers'], 'meta': story.shot_meta(conn, shot['shotId'])})


def _check_row(conn, scope, shot):
    tab = repo.get_tab(conn, scope.slug, shot['tabKey'])
    table = next(t for t in tab['doc']['content'] if t.get('type') == 'table' and any(r.get('attrs', {}).get('bid') == shot['rowId'] for r in t['content']))
    row = next(r for r in table['content'] if r.get('attrs', {}).get('bid') == shot['rowId'])
    locks = repo.tab_locks(conn, scope.slug, shot['tabKey'])
    for node in (table, row):
        attrs = node.get('attrs', {})
        if locks.get(attrs.get('bid')) not in (None, scope.actor_id) or (attrs.get('owner') not in (None, '', scope.actor_id) and not scope.me.can_edit):
            store.fail('LOCKED', 'An affected shot is owned or locked by another crew member.')


def _asset_changes(conn, scope, target):
    details = story.extract_asset_details(doc_text(target['doc']), story.scene_sections(doc_text(target['doc'])))
    if len(details) > 200:
        store.fail('LIMIT_EXCEEDED', 'An extraction supports at most 200 assets.', 413)
    existing = {a['assetCode']: a for a in story.assets(conn, scope.episode)}
    rows = {story.asset_code(r['cells'][0]): r for r in story.table_rows(conn, scope.slug, 'soul-cast')}
    changes = []
    for code, value in details.items():
        old = existing.get(code)
        action = 'create_text_asset' if old is None else 'preserve_asset'
        before = None if old is None else {'name': old['name'], 'prompt': old['prompt']}
        if old and not old['selectedImageUrl'] and rows[code]['cells'][5] in ('Queued', '待處理'):
            previous = story.record(conn, 'extracted_' + old['assetId'], required=False)
            placeholder = old['name'] in ('', code) and old['prompt'] in ('', code, 'Reference for @' + code)
            if (previous == before if previous is not None else placeholder):
                action = 'update_text_asset'
        changes.append({'assetCode': code, 'action': action, 'before': before,
                        'name': value['name'], 'prompt': value['prompt'][:10000]})
    return changes


def build_preview(conn, scope, body):
    store.reauthorize(conn, scope, write=True)
    store.fields(body, {'kind', 'targetRef', 'expectedSourceHash', 'confirmBaseline', 'shotIds', 'bindings', 'breakdownMode'},
                 {'kind', 'targetRef', 'expectedSourceHash', 'confirmBaseline'})
    if body['kind'] != 'impact' or type(body['confirmBaseline']) is not bool:
        story.invalid('Use an impact preview with boolean confirmBaseline.')
    target = _target(conn, scope, body['targetRef'])
    working = store.resolve_ref(conn, scope, {'kind': 'working'})
    if body['expectedSourceHash'] != target['docHash']:
        store.fail('PREVIEW_STALE')
    if not working['structure']['initialized'] or working['structure']['stale']:
        store.fail('MAPPING_REQUIRED', 'Initialize the current stable screenplay structure first.')
    ep = story.episode(conn, scope.episode_id)
    mode = body.get('breakdownMode', target.get('productionInputs', {}).get('breakdownMode', 'auto'))
    if not isinstance(mode, str) or mode not in story.BREAKDOWN_MODES:
        story.invalid('Unknown breakdown mode.')
    if mode != target.get('productionInputs', {}).get('breakdownMode', 'auto'):
        story.invalid('Save the breakdown setting and confirm that screenplay before applying its impact.')
    can_apply = target['docHash'] == working['docHash'] and target.get('productionInputsHash') == working['productionInputsHash']
    target_id = body['targetRef'].get('id') if body['targetRef']['kind'] == 'version' else None
    baseline_id = ep.get('productionScriptVersionId')
    if not body['confirmBaseline']:
        baseline = store.get_record(conn, scope, 'writing_version', baseline_id) if baseline_id else None
        can_apply = bool(can_apply and baseline and baseline['snapshot']['docHash'] == working['docHash']
                         and baseline['snapshot'].get('productionInputsHash') == working['productionInputsHash']
                         and ep.get('confirmedHash') == story.digest(doc_text(working['doc'])))
        target_id = baseline_id if can_apply else target_id
    items = story.shots(conn, ep)
    if len(items) > 200:
        store.fail('LIMIT_EXCEEDED', 'Inspect at most 200 shots per episode.', 413)
    ids = body.get('shotIds')
    known = {s['shotId'] for s in items}
    if ids is not None and (not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids)
                            or len(set(ids)) != len(ids) or set(ids) - known):
        story.invalid('shotIds must be unique shots in this episode.')
    bindings = body.get('bindings', [])
    if not isinstance(bindings, list) or len(bindings) > 200:
        story.invalid('Use at most 200 explicit bindings.')
    binding_map = {}
    all_units = _units(target)
    valid_scenes = {s['sceneKey'] for s in target['structure'].get('scenes', [])}
    for binding in bindings:
        store.fields(binding, {'shotId', 'sceneKeys', 'beatKeys'}, {'shotId', 'sceneKeys', 'beatKeys'})
        sid = binding['shotId']
        if not isinstance(sid, str) or sid not in known or sid in binding_map or (ids is not None and sid not in ids):
            story.invalid('Bind each selected episode shot at most once.')
        for key in ('sceneKeys', 'beatKeys'):
            values = binding[key]
            if not isinstance(values, list) or not all(isinstance(k, str) for k in values) or len(set(values)) != len(values):
                story.invalid('Binding keys must be unique stable keys.')
        if not binding['sceneKeys'] or set(binding['sceneKeys']) - valid_scenes or set(binding['beatKeys']) - {u['beatKey'] for u in all_units if u['sceneKey'] in binding['sceneKeys']}:
            store.fail('MAPPING_REQUIRED')
        binding_map[sid] = copy.deepcopy(binding)
    views, allowed, additions, guards = [], [], [], []
    for shot in items:
        if ids is not None and shot['shotId'] not in ids:
            continue
        sid = shot['shotId']
        view = _alignment_view(conn, target, shot)
        origin = view['storyOrigin']
        units, missing = _source(target, origin)
        suggested = _suggest(target, origin, units) if not missing and origin.get('mapping') == 'exact' else None
        action_ids = []
        if suggested is not None and not any(r in view['storyAlignment']['reasons'] for r in ('unbound', 'ambiguous', 'unknown_derived_base')):
            aid = 'update:' + sid
            fields = [f for f in FIELDS if suggested[f] != _fields(shot)[f] or origin.get('fieldOrigins', {}).get(f, origin).get('sourceTextHash') != _source_hash(units)]
            if fields or 'configuration_changed' in view['storyAlignment']['reasons']:
                allowed.append({'actionId': aid, 'kind': 'update_text', 'shotId': sid, 'fields': fields or list(FIELDS),
                                'defaultSelected': not bool(view['storyAlignment']['manualFields']), 'suggested': suggested})
                action_ids.append(aid)
        for kind, prefix in (('keep_shot', 'keep:'), ('leave_unresolved', 'unresolved:')):
            aid = prefix + sid
            allowed.append({'actionId': aid, 'kind': kind, 'shotId': sid})
            action_ids.append(aid)
        if sid in binding_map:
            aid = 'bind:' + sid
            allowed.append({'actionId': aid, 'kind': 'bind_source', **binding_map[sid]})
            action_ids.append(aid)
        views.append(view | {'oldSource': origin.get('sourceUnits', []), 'newSource': units, 'current': _fields(shot),
                     'suggested': suggested, 'media': {k: shot.get(k) for k in ('selectedImageUrl', 'selectedVideoUrl')}, 'actionIds': action_ids})
        guards.append({'shotId': sid, 'rowHash': _shot_guard(conn, shot)})
    bound = {key for shot in items for key in shot.get('storyOrigin', {}).get('beatKeys', [])}
    uncertain_scenes = {key for shot in items for origin in [shot.get('storyOrigin') or _legacy_origin(target, shot)]
                        if origin.get('mapping') != 'exact' for key in origin.get('sceneKeys', [])}
    if ids is None:
        for u in all_units:
            if u['beatKey'] in bound or u['sceneKey'] in uncertain_scenes:
                continue
            origin = {'sceneKeys': [u['sceneKey']], 'beatKeys': [u['beatKey']], 'mapping': 'exact'}
            suggested = _suggest(target, origin, [u])
            addition = {'actionId': 'add:' + u['beatKey'], 'kind': 'add_shot', 'sceneKeys': [u['sceneKey']], 'beatKeys': [u['beatKey']], 'suggested': suggested}
            allowed.append(addition)
            additions.append(addition)
    if len(allowed) > 1800:
        store.fail('LIMIT_EXCEEDED', 'Reduce the impact plan scope.', 413)
    result = {'sourceFingerprints': [{'sourceRef': body['targetRef'], 'docHash': target['docHash'], 'structureHash': target['structureHash']}],
            'targetFingerprints': [{'sourceRef': {'kind': 'working'}, 'docHash': working['docHash'], 'structureHash': working['structureHash']}] + guards,
            'productionInputsHash': working['productionInputsHash'], 'allowedActions': allowed,
            'proposedChanges': {'shots': views, 'additions': additions, 'assetChanges': _asset_changes(conn, scope, target) if body['confirmBaseline'] else [],
                                'confirmBaseline': body['confirmBaseline'], 'targetVersionId': target_id, 'canApply': can_apply},
            'targetRef': body['targetRef'], 'breakdownMode': mode,
            'assetGuard': store.hash_value(story.table_rows(conn, scope.slug, 'soul-cast')),
            'warnings': ([] if can_apply else ['Adopt this screenplay and confirm its production settings before applying.']) +
                        ['Shot film ordering follows shotIndex; this text-only plan does not reorder manually labeled shots.']}
    if len(store.canonical(result).encode('utf8')) > 8 * 1024 * 1024:
        store.fail('LIMIT_EXCEEDED', 'Reduce the selected shots to keep the impact preview below 8 MiB.', 413)
    return result


def _new_origin(target, version_id, old, units, fields, values):
    origin = copy.deepcopy(old)
    origin.update(versionId=version_id, mapping='exact', sceneKeys=list(dict.fromkeys(u['sceneKey'] for u in units)),
                  beatKeys=[u['beatKey'] for u in units], sourceTextHash=_source_hash(units),
                  productionInputsHash=_inputs_hash(target, units), sourceUnits=copy.deepcopy(units))
    field_origins = origin.setdefault('fieldOrigins', {})
    for f in FIELDS:
        field_origins.setdefault(f, {k: copy.deepcopy(old.get(k)) for k in ('versionId', 'sourceTextHash', 'productionInputsHash')})
    derived = origin.setdefault('derivedFields', {})
    for f in fields:
        derived[f] = copy.deepcopy(values[f])
        field_origins[f] = {k: origin[k] for k in ('versionId', 'sourceTextHash', 'productionInputsHash')}
    origin['derivedTextHash'] = store.hash_value(derived)
    return origin


def validate_preview(conn, scope, preview):
    """Readonly domain freshness hint; never a whole-preview apply gate.

    Core supplies shared-source/config staleness separately. A changed unselected
    shot must not prevent still-fresh selected actions, and temporary locks are
    checked only at apply time, not mislabeled as permanent source staleness.
    """
    store.reauthorize(conn, scope)
    frozen = store.get_preview(conn, scope, preview['previewId'])
    if frozen['kind'] != 'impact':
        story.invalid('Impact freshness requires an impact preview.')
    items = {s['shotId']: s for s in story.shots(conn, story.episode(conn, scope.episode_id))}
    guards = {g['shotId']: g['rowHash'] for g in frozen['targetFingerprints'] if 'shotId' in g}
    changed = {sid for sid, expected in guards.items() if sid not in items or _shot_guard(conn, items[sid]) != expected}
    mapped = {key for shot in items.values() for key in shot.get('storyOrigin', {}).get('beatKeys', [])}
    stale = [a['actionId'] for a in frozen['allowedActions'] if a.get('shotId') in changed
             or (a['kind'] == 'add_shot' and bool(set(a['beatKeys']) & mapped))]
    return {'stale': bool(stale), 'staleActionIds': stale}


def apply_preview(conn, scope, preview, selection):
    store.reauthorize(conn, scope, write=True)
    store.lock_project(conn, scope)
    for key in sorted({scope.episode['tabKey'], 'cinema-studio', 'soul-cast'}):
        repo.get_tab_for_update(conn, scope.slug, key)
    from project_docs import writing_service
    writing_service.validate_fingerprints(conn, scope, preview)
    proposed = preview['proposedChanges']
    if not proposed['canApply']:
        raise story.StoryError(409, 'DRAMA_STAGE_PRECONDITION', 'Adopt and confirm the target screenplay before updating shots.')
    target = _target(conn, scope, preview['targetRef'])
    ep = story.episode(conn, scope.episode_id)
    items = {s['shotId']: s for s in story.shots(conn, ep)}
    allowed = {a['actionId']: a for a in preview['allowedActions']}
    selected, seen = [], set()
    guards = {g['shotId']: g['rowHash'] for g in preview['targetFingerprints'] if 'shotId' in g}
    for choice in selection['actions']:
        action = allowed[choice['actionId']]
        sid = action.get('shotId')
        if sid in seen and sid is not None:
            story.invalid('Select at most one action per shot.')
        seen.add(sid)
        if sid is not None:
            if sid not in items or _shot_guard(conn, items[sid]) != guards[sid]:
                store.fail('PREVIEW_STALE', 'A selected shot changed.')
            if action['kind'] != 'leave_unresolved':
                _check_row(conn, scope, items[sid])
        fields = choice.get('fields', action.get('fields', []))
        if action['kind'] == 'update_text' and (not fields or len(set(fields)) != len(fields)):
            story.invalid('Select unique nonempty derived fields.')
        if action['kind'] == 'add_shot' and any(set(action['beatKeys']) & set(s.get('storyOrigin', {}).get('beatKeys', [])) for s in items.values()):
            store.fail('PREVIEW_STALE', 'A selected new source beat was already bound to a shot.')
        selected.append((action, fields))
    if len(items) + sum(a['kind'] == 'add_shot' for a, _ in selected) > 200:
        store.fail('LIMIT_EXCEEDED', 'A storyboard supports at most 200 shots.', 413)
    # Metadata-only actions must still respect screenplay locks at the confirm boundary.
    if proposed['confirmBaseline']:
        locks = repo.tab_locks(conn, scope.slug, scope.episode['tabKey'])
        if any(locks.get(structure.bid(n)) not in (None, scope.actor_id) for n in target['doc']['content']):
            store.fail('LOCKED', 'A screenplay block is currently locked.')
        if store.hash_value(story.table_rows(conn, scope.slug, 'soul-cast')) != preview['assetGuard']:
            store.fail('PREVIEW_STALE', 'The frozen asset extraction footprint changed.')
        story.extract(conn, scope.me, ep)
        ep = story.episode(conn, scope.episode_id)
        target = store.resolve_ref(conn, scope, {'kind': 'working'})
    else:
        baseline = store.get_record(conn, scope, 'writing_version', ep.get('productionScriptVersionId')) if ep.get('productionScriptVersionId') else None
        if not baseline or ep.get('productionScriptVersionId') != proposed['targetVersionId'] or baseline['snapshot']['docHash'] != target['docHash'] or baseline['snapshot'].get('productionInputsHash') != target['productionInputsHash'] or ep.get('confirmedHash') != story.digest(doc_text(target['doc'])):
            raise story.StoryError(409, 'DRAMA_STAGE_PRECONDITION', 'The current production baseline is no longer valid.')
    version_id = ep['productionScriptVersionId']
    results = []
    for action, fields in selected:
        kind = action['kind']; sid = action.get('shotId')
        if kind == 'leave_unresolved':
            results.append({'actionId': action['actionId'], 'shotId': sid, 'kind': kind})
            continue
        if kind == 'add_shot':
            units, missing = _source(target, action)
            if missing:
                store.fail('PREVIEW_STALE')
            scene = next(s for s in target['structure']['scenes'] if s['sceneKey'] == units[0]['sceneKey'])
            values = action['suggested']
            rid = story.mutate_row(conn, scope.me, scope.slug, 'cinema-studio', cells={0: 'SC%02d-W%s' % (scene['order'], units[0]['beatKey'][-8:]), 3: values['description'], 6: 'Queued'})
            sid = 'sh_' + scope.slug + '_' + rid
            meta = {'episodeId': scope.episode_id, 'sceneId': scene['legacySceneId'], 'dialogue': values['dialogue']}
            meta['storyOrigin'] = _new_origin(target, version_id, {}, units, FIELDS, values)
            meta['storyAlignment'] = {'state': 'in_sync', 'mediaState': 'none'}
        else:
            shot = items[sid]; meta = story.shot_meta(conn, sid)
            origin = shot.get('storyOrigin') or _legacy_origin(target, shot)
            units, missing = _source(target, action if kind == 'bind_source' else origin)
            if kind == 'keep_shot':
                meta['storyAlignment'] = copy.deepcopy(meta.get('storyAlignment', {})) | {'state': 'kept_intentionally', 'intentionalDivergence': {
                    'versionId': version_id, 'sourceTextHash': _source_hash(units), 'sourceState': missing, 'productionInputsHash': _inputs_hash(target, units), 'derivedTextHash': store.hash_value(_fields(shot))}}
            elif kind == 'bind_source':
                if missing:
                    store.fail('MAPPING_REQUIRED')
                # This is an explicit textual association, NOT evidence about any old take.
                meta['storyOrigin'] = _new_origin(target, version_id, {}, units, FIELDS, _fields(shot))
                meta['storyOrigin']['bindingMethod'] = 'explicit'
                if not action['beatKeys']:
                    meta['storyOrigin'].update(mapping='scene_only', beatKeys=[])
                meta['storyOrigin']['recipes'] = [{'beatKeys': action['beatKeys'], 'mode': 'scene'}]
                meta['storyAlignment'] = {'state': 'in_sync', 'mediaState': 'unknown'}
            elif kind == 'update_text':
                if missing:
                    store.fail('MAPPING_REQUIRED')
                if 'description' in fields:
                    _, row = story.find_row(conn, sid, 'shot')
                    column = next(i for i, h in enumerate(row['headers']) if re.search('prompt', h, re.I))
                    story.mutate_row(conn, scope.me, scope.slug, shot['tabKey'], shot['rowId'], {column: action['suggested']['description']})
                if 'dialogue' in fields:
                    meta['dialogue'] = copy.deepcopy(action['suggested']['dialogue'])
                meta['storyOrigin'] = _new_origin(target, version_id, origin, units, fields, action['suggested'])
                meta['storyAlignment'] = {'state': 'source_changed', 'mediaState': 'outdated'}
            else:
                story.invalid('Unknown frozen impact action.')
        if kind in ('update_text', 'bind_source', 'add_shot'):
            _, actual_row = story.find_row(conn, sid, 'shot')
            shadow = story.shot_view(conn, scope.slug, actual_row) | meta
            meta['storyAlignment'] = alignment(target, shadow)['storyAlignment']
        story.store(conn, 'meta_' + sid, 'shot_meta', meta, scope.slug)
        repo.add_audit(conn, scope.slug, action='edit', actor_id=scope.actor_id, tab_key='cinema-studio', detail={'source': 'writing-impact', 'shotId': sid, 'kind': kind, 'fields': list(fields)})
        results.append({'actionId': action['actionId'], 'shotId': sid, 'kind': kind})
    return {'episodeId': scope.episode_id, 'productionScriptVersionId': version_id, 'actions': results, 'savedAt': story.now()}


def _alignment_view(conn, target, shot):
    view = alignment(target, shot)
    selected = [(kind, shot.get('selected' + kind.title() + 'Url')) for kind in ('image', 'video')]
    slug = story.find_row(conn, shot['shotId'], 'shot')[0]
    receipts = story.records(conn, 'candidate', slug) + story.records(conn, 'story_media_receipt', slug)
    states = []
    units, missing = _source(target, shot.get('storyOrigin', {}))
    for kind, url in selected:
        if not url:
            continue
        evidence = candidate_evidence([r for r in receipts if r['entityId'] == shot['shotId'] and r['kind'] == kind], url)
        states.append('unknown' if not evidence or not evidence.get('originKnown') else
                      'current' if not missing and evidence.get('storyOrigin') == shot.get('storyOrigin') and evidence.get('sourceTextHash') == _source_hash(units)
                      and not view['storyAlignment']['reasons'] else 'outdated')
    if states:
        view['storyAlignment']['mediaState'] = 'outdated' if 'outdated' in states else 'unknown' if 'unknown' in states else 'current'
        view['storyAlignment']['mediaOutdated'] = any(s != 'current' for s in states)
    return view


def dispatch(conn, scope, method, tail, body, query, *, raw=None, headers=None):
    if method == 'GET' and tail in ('alignment', 'impact'):
        store.reauthorize(conn, scope)
        target = store.resolve_ref(conn, scope, {'kind': 'working'})
        ep = story.episode(conn, scope.episode_id)
        return {'episodeId': scope.episode_id, 'targetVersionId': ep.get('productionScriptVersionId'),
                'items': [_alignment_view(conn, target, shot) for shot in story.shots(conn, ep)]}
    return store.UNHANDLED


def bind_generated_shots(conn, scope, shot_ids, *, version_id):
    """The caller proves these rows were actually derived in this transaction."""
    store.reauthorize(conn, scope, write=True)
    target = _target(conn, scope, {'kind': 'version', 'id': version_id})
    working = store.resolve_ref(conn, scope, {'kind': 'working'})
    # Legacy builds may change density/settings after confirmation. Preserve that API:
    # retain the actual baseline pointer separately from the actual derivation settings.
    # A nonretained document cannot acquire a fabricated exact historical binding.
    baseline_doc_matches = target['docHash'] == working['docHash']
    baseline_inputs_hash = target['productionInputsHash']
    target = working
    items = {s['shotId']: s for s in story.shots(conn, scope.episode)}
    units = _units(target)
    mode = target['productionInputs'].get('breakdownMode', 'auto')
    plans = []
    for scene in story.scenes(conn, scope.episode):
        stable = next((s for s in target['structure']['scenes'] if s.get('legacySceneId') == scene['sceneId']), None)
        if not stable:
            continue
        source = [u for u in units if u['sceneKey'] == stable['sceneKey']]
        beats = story.scene_shot_beats(scene['content'], mode) or [scene['title']]
        refs = list(dict.fromkeys(story.asset_code(m[1]) for m in story.ASSET_RE.finditer(scene['content']) if m[1].upper().startswith(('SET-', 'LOC-')))) or ['SET-%02d' % scene['sceneIndex']]
        cast = {a['name'].casefold(): a['assetCode'] for a in story.assets(conn, scope.episode) if a['type'] == 'CHARACTER' and a['isDefault']}
        for index, text in enumerate(beats):
            appended = list(dict.fromkeys(refs + [code for name, code in cast.items() if re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', text, re.I)]))
            prompt = text + ' ' + ' '.join('@' + c for c in appended if c not in {story.asset_code(m[1]) for m in story.ASSET_RE.finditer(text)})
            recipes = []
            if mode == 'scene':
                matched = source
                recipes = [{'beatKeys': [u['beatKey'] for u in source], 'mode': 'scene'}]
            else:
                matches = [(u, j, parts) for u in source for parts in [story.scene_shot_beats(u['text'], mode)] for j, part in enumerate(parts) if part == text]
                matched = [matches[0][0]] if len(matches) == 1 else []
                if matched:
                    u, j, parts = matches[0]
                    recipes = [{'beatKeys': [u['beatKey']], 'mode': mode, 'segmentIndex': j, 'segmentCount': len(parts)}]
            plans.append({'sceneKey': stable['sceneKey'], 'description': prompt[:10000], 'units': matched, 'recipes': recipes, 'appendedRefs': appended})
    for sid in shot_ids:
        if sid not in items:
            store.fail('MAPPING_REQUIRED')
        shot = items[sid]
        matches = [p for p in plans if p['description'] == shot['description'] and any(s['sceneKey'] == p['sceneKey'] and s.get('legacySceneId') == shot.get('sceneId') for s in target['structure']['scenes'])]
        meta = story.shot_meta(conn, sid)
        if baseline_doc_matches and len(matches) == 1 and matches[0]['units']:
            plan = matches[0]
            meta['storyOrigin'] = _new_origin(target, version_id, {}, plan['units'], FIELDS, _fields(shot)) | {'recipes': plan['recipes'], 'appendedRefs': plan['appendedRefs'], 'bindingMethod': 'generated', 'baselineProductionInputsHash': baseline_inputs_hash}
            meta['storyAlignment'] = {'state': 'in_sync', 'mediaState': 'outdated' if shot.get('selectedImageUrl') or shot.get('selectedVideoUrl') else 'none'}
        else:
            scene = next((s for s in target['structure']['scenes'] if s.get('legacySceneId') == shot.get('sceneId')), None)
            meta['storyOrigin'] = {'versionId': version_id, 'sceneKeys': [scene['sceneKey']] if scene else [], 'beatKeys': [],
                                   'mapping': 'ambiguous' if len(matches) > 1 else 'scene_only' if scene else 'unbound'}
            meta['storyAlignment'] = {'state': 'ambiguous' if len(matches) > 1 else 'unbound', 'mediaState': 'unknown'}
        story.store(conn, 'meta_' + sid, 'shot_meta', meta, scope.slug)


def freeze_story_provenance(conn, scope, shot_id):
    """Capture actual origin separately from the episode's latest production pointer."""
    store.reauthorize(conn, scope)
    shot = next((s for s in story.shots(conn, scope.episode) if s['shotId'] == shot_id), None)
    if shot is None:
        raise story.StoryError(404, 'DRAMA_NOT_FOUND', 'Shot not found in episode.')
    working = store.resolve_ref(conn, scope, {'kind': 'working'})
    origin = copy.deepcopy(shot.get('storyOrigin'))
    units, missing = _source(working, origin or {})
    return {'schemaVersion': 1, 'episodeId': scope.episode_id, 'shotId': shot_id, 'storyOrigin': origin,
            'baselineVersionId': story.episode(conn, scope.episode_id).get('productionScriptVersionId'),
            'rowHash': store.hash_value(story.find_row(conn, shot_id, 'shot')[1]['cells']),
            'sourceTextHash': _source_hash(units) if not missing else None, 'docHash': working['docHash'],
            'structureHash': working['structureHash'], 'productionInputsHash': working['productionInputsHash'],
            'intentionalDivergence': copy.deepcopy(shot.get('storyAlignment', {}).get('intentionalDivergence')),
            'originKnown': bool(origin and origin.get('mapping') == 'exact')}


def freeze_for_shot(conn, me, identifier):
    slug, row = story.find_row(conn, identifier, 'shot')
    ep_id = story.shot_meta(conn, identifier).get('episodeId', 'ep_' + slug + '_01')
    return freeze_story_provenance(conn, store.scope_for(conn, me, ep_id), identifier)


def validate_frozen_row(evidence, cells):
    if not evidence or evidence.get('rowHash') != store.hash_value(cells):
        store.fail('PREVIEW_STALE', 'The media row changed while freezing its story provenance.')


def provenance_matches(conn, me, identifier, frozen, *, check_row=True):
    if not frozen:
        return False
    current = freeze_for_shot(conn, me, identifier)
    keys = ('storyOrigin', 'baselineVersionId', 'sourceTextHash', 'productionInputsHash', 'intentionalDivergence') + (('rowHash',) if check_row else ())
    return all(frozen.get(k) == current.get(k) for k in keys)


def allocation_source_guard(conn, shot):
    ep = story.episode(conn, shot.get('episodeId', 'ep_' + story.find_row(conn, shot['shotId'], 'shot')[0] + '_01'))
    return {'storyOrigin': shot.get('storyOrigin'), 'storyAlignment': shot.get('storyAlignment'),
            'baselineVersionId': ep.get('productionScriptVersionId'),
            'docHash': store.doc_hash(repo.get_tab(conn, ep['slug'], ep['tabKey'])['doc']),
            'settings': ep.get('settings', {}), 'breakdownMode': ep.get('breakdownMode')}


def candidate_evidence(records, url):
    matching = [r.get('storyProvenance') for r in records if r['url'] == url]
    # Content-addressed equal bytes can have different histories; do not guess one.
    return matching[0] if matching and all(v == matching[0] for v in matching) else None


def record_candidate_receipt(conn, slug, identifier, output, evidence, receipt_id):
    mime = output.get('content_type', '')
    if output.get('asset_url') and mime.startswith(('video/', 'image/')):
        # A receipt is not a selectable candidate: exposing pending race/proposal output
        # through selected-video would bypass the existing M8 winner gate.
        story.store(conn, 'smr_' + receipt_id, 'story_media_receipt', {'entityId': identifier, 'kind': mime.split('/')[0],
                    'url': output['asset_url'], 'storyProvenance': copy.deepcopy(evidence)}, slug)


def candidate_view(candidate, evidence):
    return candidate | {'storyProvenance': copy.deepcopy(evidence) if evidence else None,
                        'storyProvenanceState': 'known' if evidence and evidence.get('originKnown') else 'unknown'}


def split_lineage(conn, slug, original, other):
    # Both text rows have the same proven beat association; the new row inherits no take.
    meta = story.shot_meta(conn, other)
    meta['storyAlignment'] = copy.deepcopy(meta.get('storyAlignment', {})) | {'mediaState': 'none'}
    meta['storyLineage'] = {'operation': 'split', 'fromShotIds': [original]}
    story.store(conn, 'meta_' + other, 'shot_meta', meta, slug)


def merge_lineage(conn, slug, identifiers):
    metas = [story.shot_meta(conn, sid) for sid in identifiers]
    origins = [m.get('storyOrigin') for m in metas]
    meta = copy.deepcopy(metas[0])
    if all(o and o.get('mapping') == 'exact' for o in origins):
        origin = copy.deepcopy(origins[0])
        origin['sceneKeys'] = list(dict.fromkeys(k for o in origins for k in o.get('sceneKeys', [])))
        origin['beatKeys'] = list(dict.fromkeys(k for o in origins for k in o.get('beatKeys', [])))
        origin['sourceUnits'] = list({u['beatKey']: u for o in origins for u in o.get('sourceUnits', [])}.values())
        origin['recipes'] = [r for o in origins for r in o.get('recipes', [{'beatKeys': o['beatKeys'], 'mode': 'scene'}])]
        origin['sourceTextHash'] = _source_hash(origin['sourceUnits'])
        origin['derivedFields'] = {'description': '\n'.join(o.get('derivedFields', {}).get('description', '') for o in origins),
                                   'dialogue': [v for o in origins for v in o.get('derivedFields', {}).get('dialogue', [])]}
        # Different real source versions are retained, not disguised as the latest origin.
        leaves = [leaf for o in origins for leaf in o.get('mergedOrigins', [o])]
        origin['mergedOrigins'] = list({store.hash_value(o): copy.deepcopy(o) for o in leaves}.values())
        if len(origin['mergedOrigins']) > 200:
            store.fail('LIMIT_EXCEEDED', 'Split merged source histories above 200 origins.', 413)
        origin['versionId'] = origins[0].get('versionId') if len({o.get('versionId') for o in origins}) == 1 else None
        baseline = story.record(conn, origin['versionId'], required=False) if origin['versionId'] else None
        origin['productionInputsHash'] = _inputs_hash(baseline['snapshot'], origin['sourceUnits']) if baseline and baseline.get('episodeId') == meta.get('episodeId') and 'snapshot' in baseline else None
        origin['fieldOrigins'] = {f: {'versionId': origin['versionId'], 'sourceTextHash': origin['sourceTextHash'],
                                    'productionInputsHash': origin['productionInputsHash']} for f in FIELDS}
        meta['storyOrigin'] = origin
    else:
        meta['storyOrigin'] = {'mapping': 'unbound', 'sceneKeys': [], 'beatKeys': [], 'mergedOrigins': origins}
    meta['storyAlignment'] = {'state': 'source_changed', 'mediaState': 'outdated'}
    meta['storyLineage'] = {'operation': 'merge', 'fromShotIds': identifiers}
    story.store(conn, 'meta_' + identifiers[0], 'shot_meta', meta, slug)
