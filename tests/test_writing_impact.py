"""W4 behavior through real authenticated HTTP/PG; no provider or GPU inference."""
import copy
import os
import threading
import unittest
import uuid
from unittest.mock import patch
from project_docs import writing_impact as impact, writing_store as store, writing_structure as structure
from project_docs import story_openapi as story, repository as repo, service
from project_assistant import limb_worker as worker
import test_writing_core as core
import test_story_openapi as fixture


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'isolated PG required')
class ImpactHTTPTests(unittest.TestCase):
    request = fixture.StoryHTTPTests.request
    setUp = fixture.StoryHTTPTests.setUp
    tearDown = fixture.StoryHTTPTests.tearDown
    call = fixture.StoryHTTPTests.call
    ok = fixture.StoryHTTPTests.ok
    writing = core.WritingHTTPTests.writing
    error = core.WritingHTTPTests.error
    init = core.WritingHTTPTests.init
    save_doc = core.WritingHTTPTests.save_doc

    def prepare(self, mode='auto', lines=None):
        self.init()
        self.save_doc(core.document(*(lines or ('Scene 01: Arrival', '@CAST-01 opens the door.', 'Scene 02: Signal', '@CAST-01: "Stay."'))))
        self.ok('/episodes/' + self.ep + '/settings', 'PUT', {'breakdownMode': mode})
        self.ok('/episodes/' + self.ep + '/asset-extractions', 'POST', {})
        self.ok('/episodes/' + self.ep + '/storyboards', 'POST', {})
        return self.ok('/episodes/' + self.ep + '/shots')['items']

    def preview(self, **kwargs):
        current = self.writing('workspace')
        body = {'kind': 'impact', 'targetRef': {'kind': 'working'}, 'expectedSourceHash': current['docHash'], 'confirmBaseline': True} | kwargs
        return self.writing('previews', 'POST', body)

    def apply(self, preview, choices, key=None):
        return self.writing('previews/' + preview['previewId'] + '/apply', 'POST', {'expectedPreviewVersion': preview['version'], 'selection': {'actions': choices}}, key=key)

    def change(self, index, text):
        doc = copy.deepcopy(self.writing('workspace')['doc'])
        doc['content'][index]['content'] = [{'type': 'text', 'text': text}]
        self.save_doc(doc)

    def shots(self):
        return self.ok('/episodes/' + self.ep + '/shots')['items']

    def scope(self):
        return store.scope_for(self.conn, self.me, self.ep, write=True)

    def test_exact_generated_and_legacy_honesty_no_get_write(self):
        shots = self.prepare()
        generated = [s for s in shots if s.get('storyOrigin')]
        self.assertEqual(len(generated), 2)
        for s in generated:
            self.assertEqual(s['storyOrigin']['mapping'], 'exact')
            self.assertEqual(len(s['storyOrigin']['beatKeys']), 1)
        a = self.writing('alignment')['items']
        self.assertTrue(all(i['storyAlignment']['state'] == 'in_sync' for i in a if i['shotId'] in {s['shotId'] for s in generated}))
        legacy = next(s for s in shots if not s.get('storyOrigin'))
        old = story.shot_meta(self.conn, legacy['shotId'])
        self.writing('alignment')
        self.assertEqual(story.shot_meta(self.conn, legacy['shotId']), old)
        item = next(i for i in a if i['shotId'] == legacy['shotId'])
        self.assertEqual(item['storyAlignment']['state'], 'unbound')
        candidate = story.candidate_view if hasattr(story, 'candidate_view') else impact.candidate_view
        self.assertEqual(candidate({'url': 'old'}, None)['storyProvenanceState'], 'unknown')

    def test_partial_fields_manual_override_and_per_shot_origins_preserve_media(self):
        shots = self.prepare()
        generated = [s for s in shots if s.get('storyOrigin')]
        first, second = generated
        _, row = story.find_row(self.conn, first['shotId'], 'shot')
        # A synthetic persisted take and all manually selected production metadata survive.
        url = '/projects/api/' + self.slug + '/assets/pa_' + 'a' * 32
        story.mutate_row(self.conn, self.me, self.slug, row['tabKey'], row['rid'], {1: 'Manual 85mm', 2: 'Manual orbit', 3: 'Director override', 5: '[video](' + url + ')', 6: 'Approved'})
        meta = story.shot_meta(self.conn, first['shotId']) | {'seed': 123, 'overrides': {'node.field': 'manual'}, 'previsPlan': {'directorDraft': 'keep'}}
        story.store(self.conn, 'meta_' + first['shotId'], 'shot_meta', meta, self.slug)
        self.conn.commit()
        untouched = copy.deepcopy(next(s for s in self.shots() if s['shotId'] == second['shotId']))
        self.change(1, '@CAST-01: "Leave."')
        p = self.preview(shotIds=[first['shotId'], second['shotId']])
        view = next(s for s in p['proposedChanges']['shots'] if s['shotId'] == first['shotId'])
        self.assertIn('manual_override', view['storyAlignment']['reasons'])
        update = next(a for a in p['allowedActions'] if a['kind'] == 'update_text' and a['shotId'] == first['shotId'])
        self.assertFalse(update['defaultSelected'])
        from project_assistant import execution_governance as governance
        with patch.object(story, 'generation', side_effect=AssertionError('text apply admitted generation')), patch.object(worker, 'execute_story_card', side_effect=AssertionError('inference')), patch.object(governance, 'prepare_operation', side_effect=AssertionError('Judge generation admission')):
            self.apply(p, [{'actionId': update['actionId'], 'fields': ['dialogue']}])
        with self.conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM projectops.agent_usage_ledger WHERE project_slug=%s', (self.slug,))
            self.assertEqual(cur.fetchone()[0], 0)
        current = next(s for s in self.shots() if s['shotId'] == first['shotId'])
        self.assertEqual(current['description'], 'Director override')
        self.assertEqual(current['dialogue'][0]['line'], 'Leave.')
        for key in ('opticalRig', 'cameraMotion', 'selectedVideoUrl', 'seed', 'overrides', 'previsPlan', 'reviewStatus'):
            self.assertEqual(current[key], {'opticalRig': 'Manual 85mm', 'cameraMotion': 'Manual orbit', 'selectedVideoUrl': url, 'seed': 123, 'overrides': {'node.field': 'manual'}, 'previsPlan': {'directorDraft': 'keep'}, 'reviewStatus': 'Approved'}[key])
        self.assertEqual(next(s for s in self.shots() if s['shotId'] == second['shotId']), untouched)
        a = next(s for s in self.writing('alignment')['items'] if s['shotId'] == first['shotId'])
        self.assertIn('source_changed', a['storyAlignment']['reasons'])
        self.assertTrue(a['storyAlignment']['mediaOutdated'])
        p2 = self.preview(shotIds=[first['shotId']])
        self.apply(p2, [{'actionId': 'update:' + first['shotId'], 'fields': ['description']}])
        a = next(s for s in self.writing('alignment')['items'] if s['shotId'] == first['shotId'])
        self.assertEqual(a['storyAlignment']['state'], 'in_sync')
        self.assertTrue(a['storyAlignment']['mediaOutdated'])

    def test_keep_hash_ack_bind_unresolved_and_deleted_source(self):
        shots = self.prepare(); shot = next(s for s in shots if s.get('storyOrigin')); sid = shot['shotId']
        origin = copy.deepcopy(shot['storyOrigin'])
        self.change(1, '@CAST-01 closes the door.')
        p = self.preview(shotIds=[sid]); self.apply(p, [{'actionId': 'keep:' + sid}])
        self.assertEqual(next(s for s in self.writing('alignment')['items'] if s['shotId'] == sid)['storyAlignment']['state'], 'kept_intentionally')
        self.assertEqual(story.shot_meta(self.conn, sid)['storyOrigin'], origin)
        self.change(1, '@CAST-01 runs away.')
        self.assertEqual(next(s for s in self.writing('alignment')['items'] if s['shotId'] == sid)['storyAlignment']['state'], 'source_changed')
        p = self.preview(shotIds=[sid]); before = story.shot_meta(self.conn, sid)
        self.apply(p, [{'actionId': 'unresolved:' + sid}]); self.assertEqual(story.shot_meta(self.conn, sid), before)
        legacy = next(s for s in shots if not s.get('storyOrigin'))
        u = self.writing('workspace')['structure']['scenes'][0]
        p = self.preview(shotIds=[legacy['shotId']], bindings=[{'shotId': legacy['shotId'], 'sceneKeys': [u['sceneKey']], 'beatKeys': [u['beats'][0]['beatKey']]}])
        self.apply(p, [{'actionId': 'bind:' + legacy['shotId']}])
        self.assertEqual(story.shot_meta(self.conn, legacy['shotId'])['storyOrigin']['bindingMethod'], 'explicit')
        doc = copy.deepcopy(self.writing('workspace')['doc']); del doc['content'][1]; self.save_doc(doc)
        item = next(s for s in self.writing('alignment')['items'] if s['shotId'] == sid)
        self.assertEqual(item['storyAlignment']['state'], 'source_removed')
        self.assertTrue(any(s['shotId'] == sid for s in self.shots()))

    def test_selected_rows_stale_lock_rollback_and_unselected_changes(self):
        shots = self.prepare(); selected = [s for s in shots if s.get('storyOrigin')]; a, b = selected
        self.change(1, 'Changed first.'); self.change(3, 'Changed second.')
        p = self.preview(shotIds=[a['shotId'], b['shotId']])
        original = next(s for s in self.shots() if s['shotId'] == a['shotId'])
        _, row = story.find_row(self.conn, b['shotId'], 'shot')
        story.mutate_row(self.conn, self.me, self.slug, row['tabKey'], row['rid'], {3: 'Concurrent edit'})
        self.conn.commit()
        body = {'expectedPreviewVersion': 1, 'selection': {'actions': [{'actionId': 'update:' + s['shotId']} for s in selected]}}
        self.error('previews/' + p['previewId'] + '/apply', 'POST', body, 409)
        self.assertEqual(next(s for s in self.shots() if s['shotId'] == a['shotId']), original)
        # The identical preview remains usable when only its unchanged first shot is selected.
        self.apply(p, [{'actionId': 'update:' + a['shotId']}])
        p = self.preview(shotIds=[b['shotId']])
        other = str(uuid.uuid4())
        repo.upsert_member(self.conn, other, 'Other locking crew', 'member')
        repo.take_lock(self.conn, self.slug, b['tabKey'], b['rowId'], other)
        self.conn.commit()
        before = story.shot_meta(self.conn, b['shotId'])
        error = self.error('previews/' + p['previewId'] + '/apply', 'POST', {'expectedPreviewVersion': 1, 'selection': {'actions': [{'actionId': 'keep:' + b['shotId']}]}}, 409)
        self.assertEqual(error['code'], 'DRAMA_WRITING_LOCKED')
        self.assertEqual(story.shot_meta(self.conn, b['shotId']), before)
        repo.release_lock(self.conn, self.slug, b['tabKey'], b['rowId'], other)
        self.conn.commit()

    def test_add_replay_and_baseline_false_historical_comparison(self):
        self.prepare()
        doc = copy.deepcopy(self.writing('workspace')['doc'])
        doc['content'].extend(core.document('Scene 03: New', 'New visible action.')['content'])
        self.save_doc(doc)
        p = self.preview(); adds = [a for a in p['allowedActions'] if a['kind'] == 'add_shot' and a['suggested']['description'] == 'New visible action.']
        self.assertEqual(len(adds), 1)
        self.assertTrue(p['proposedChanges']['assetChanges'])
        before = len(self.shots())
        result = self.apply(p, [{'actionId': adds[0]['actionId']}], key='add-exactly-once')
        self.assertEqual(len(self.shots()), before + 1)
        self.assertEqual(self.apply(p, [{'actionId': adds[0]['actionId']}], key='add-exactly-once'), result)
        self.assertEqual(len(self.shots()), before + 1)
        old_id = result['productionScriptVersionId']
        self.change(1, 'Dirty content.')
        p = self.preview(confirmBaseline=False)
        self.assertFalse(p['proposedChanges']['canApply'])
        self.error('previews/' + p['previewId'] + '/apply', 'POST', {'expectedPreviewVersion': 1, 'selection': {'actions': [{'actionId': p['allowedActions'][0]['actionId']}]}}, 409)
        old = self.writing('versions/' + old_id)
        p = self.preview(targetRef={'kind': 'version', 'id': old_id}, expectedSourceHash=old['snapshot']['docHash'])
        self.assertFalse(p['proposedChanges']['canApply'])

    def test_one_to_many_many_to_one_split_merge_and_reorder(self):
        shots = self.prepare('cinematic_multi', ('Scene 01: Arrival', '@CAST-01 walks.', 'Scene 02: Signal', '@CAST-01 stops.'))
        generated = [s for s in shots if s.get('storyOrigin')]
        self.assertEqual(len(generated), 4)
        first = generated[:2]
        self.assertEqual(first[0]['storyOrigin']['beatKeys'], first[1]['storyOrigin']['beatKeys'])
        self.change(1, '@CAST-01 runs.')
        p = self.preview(shotIds=[s['shotId'] for s in generated])
        self.assertEqual({a['shotId'] for a in p['allowedActions'] if a['kind'] == 'update_text'}, {s['shotId'] for s in first})
        split = self.ok('/shots/' + first[0]['shotId'] + '/splits', 'POST', {})['shots']
        self.assertEqual(split[0]['storyOrigin']['beatKeys'], split[1]['storyOrigin']['beatKeys'])
        merged = self.ok('/shot-merges', 'POST', {'shotIds': [first[0]['shotId'], generated[2]['shotId']]})
        self.assertEqual(len(merged['storyOrigin']['beatKeys']), 2)
        self.assertEqual(len(merged['storyOrigin']['mergedOrigins']), 2)
        self.change(3, '@CAST-01 turns.')
        view = next(v for v in self.writing('alignment')['items'] if v['shotId'] == merged['shotId'])
        self.assertIn('source_changed', view['storyAlignment']['reasons'])
        w = self.writing('workspace'); keys = [s['sceneKey'] for s in w['structure']['scenes']]
        p = self.writing('previews', 'POST', {'kind': 'structure', 'targetDocHash': w['docHash'], 'structureVersion': w['structure']['version'], 'operation': {'type': 'move', 'sceneKey': keys[1], 'afterSceneKey': None}})
        self.apply(p, [{'actionId': 'structure'}])
        moved = self.writing('workspace')['structure']['scenes']
        self.assertEqual([s['sceneKey'] for s in moved], list(reversed(keys)))
        self.assertEqual(next(s for s in self.shots() if s['shotId'] == first[1]['shotId'])['storyOrigin']['beatKeys'], first[1]['storyOrigin']['beatKeys'])

    def test_scene_many_to_one_and_explicit_scene_only_split_stays_ambiguous(self):
        shots = self.prepare('scene', ('Scene 01: Arrival', '@CAST-01 walks.', '@CAST-01 stops.', 'Scene 02: Signal', '@CAST-01 waits.'))
        shot = next(s for s in shots if s.get('storyOrigin'))
        self.assertEqual(len(shot['storyOrigin']['beatKeys']), 2)
        self.change(2, '@CAST-01 turns.')
        p = self.preview(shotIds=[shot['shotId']])
        suggested = next(a for a in p['allowedActions'] if a['kind'] == 'update_text')['suggested']['description']
        self.assertIn('walks', suggested); self.assertIn('turns', suggested)
        self.apply(p, [{'actionId': 'update:' + shot['shotId']}])
        legacy = next(s for s in shots if not s.get('storyOrigin'))
        w = self.writing('workspace'); scene = w['structure']['scenes'][0]
        p = self.preview(shotIds=[legacy['shotId']], bindings=[{'shotId': legacy['shotId'], 'sceneKeys': [scene['sceneKey']], 'beatKeys': []}])
        self.apply(p, [{'actionId': 'bind:' + legacy['shotId']}])
        self.assertEqual(story.shot_meta(self.conn, legacy['shotId'])['storyOrigin']['mapping'], 'scene_only')
        w = self.writing('workspace'); scene = w['structure']['scenes'][0]
        p = self.writing('previews', 'POST', {'kind': 'structure', 'targetDocHash': w['docHash'], 'structureVersion': w['structure']['version'],
                         'operation': {'type': 'split', 'sceneKey': scene['sceneKey'], 'atBid': scene['beats'][1]['blockBids'][0], 'title': 'Split'}})
        self.apply(p, [{'actionId': 'structure'}])
        items = {s['shotId']: s for s in self.writing('alignment')['items']}
        self.assertEqual(items[legacy['shotId']]['storyAlignment']['state'], 'ambiguous')
        self.assertNotIn('source_removed', items[shot['shotId']]['storyAlignment']['reasons'])
        w = self.writing('workspace'); scenes = w['structure']['scenes']
        p = self.writing('previews', 'POST', {'kind': 'structure', 'targetDocHash': w['docHash'], 'structureVersion': w['structure']['version'],
                         'operation': {'type': 'merge', 'sceneKeys': [s['sceneKey'] for s in scenes[:2]], 'keepSceneKey': scenes[0]['sceneKey']}})
        self.apply(p, [{'actionId': 'structure'}])
        self.assertEqual(story.shot_meta(self.conn, shot['shotId'])['storyOrigin']['beatKeys'], shot['storyOrigin']['beatKeys'])

    def test_frozen_source_stale_confirmed_only_apply_and_revoked_replay(self):
        shot = next(s for s in self.prepare() if s.get('storyOrigin')); sid = shot['shotId']
        self.change(1, 'First revision.')
        p = self.preview(shotIds=[sid])
        before = copy.deepcopy(next(s for s in self.shots() if s['shotId'] == sid))
        self.change(1, 'Second revision.')
        self.error('previews/' + p['previewId'] + '/apply', 'POST', {'expectedPreviewVersion': 1, 'selection': {'actions': [{'actionId': 'update:' + sid}]}}, 409)
        self.assertEqual(next(s for s in self.shots() if s['shotId'] == sid), before)
        self.ok('/episodes/' + self.ep + '/asset-extractions', 'POST', {})
        baseline_id = self.writing('workspace')['baseline']['versionId']
        p = self.preview(shotIds=[sid], confirmBaseline=False)
        self.assertTrue(p['proposedChanges']['canApply'])
        self.assertEqual(p['proposedChanges']['assetChanges'], [])
        self.apply(p, [{'actionId': 'update:' + sid}], key='confirmed-apply')
        self.assertEqual(self.writing('workspace')['baseline']['versionId'], baseline_id)
        self.apply(p, [{'actionId': 'update:' + sid}], key='confirmed-apply')
        repo.upsert_member(self.conn, self.actor, 'Now viewer', 'viewer'); self.conn.commit()
        self.error('previews/' + p['previewId'] + '/apply', 'POST', {'expectedPreviewVersion': 1, 'selection': {'actions': [{'actionId': 'update:' + sid}]}}, 403, key='confirmed-apply')

    def test_duplicate_source_never_guessed_exact(self):
        shots = self.prepare('auto', ('Scene 01: Arrival', 'Repeat.', 'Repeat.'))
        generated = [s for s in shots if s.get('storyOrigin')]
        self.assertTrue(all(s['storyOrigin']['mapping'] == 'ambiguous' for s in generated))
        p = self.preview(shotIds=[s['shotId'] for s in generated])
        self.assertFalse(any(a['kind'] == 'update_text' for a in p['allowedActions']))
        # A source-hash-only unknown take is not retroactively certified on bind.
        self.assertTrue(all(s['storyAlignment']['state'] == 'ambiguous' for s in p['proposedChanges']['shots']))

    def test_narrative_metadata_does_not_outdate_known_native_media(self):
        shot = next(s for s in self.prepare() if s.get('storyOrigin')); sid = shot['shotId']
        with patch.object(story._POOL, 'submit'):
            task = self.ok('/shots/' + sid + '/image-generations', 'POST', {'appCode': 'flux-soul-cast'})
        output = {'asset_url': '/projects/api/' + self.slug + '/assets/pa_' + 'c' * 32, 'asset_id': 'pa_' + 'c' * 32, 'content_type': 'image/png'}
        from project_assistant import execution_governance as governance
        with patch.object(worker, 'execute_story_card', return_value=output), patch.object(governance, 'run_operation', side_effect=lambda ctx, key, fn, **kw: fn()):
            story.execute_task(task['taskId'])
        self.assertEqual(story.record(self.conn, task['taskId'])['status'], 'SUCCEEDED')
        before = next(s for s in self.writing('alignment')['items'] if s['shotId'] == sid)
        self.assertFalse(before['storyAlignment']['mediaOutdated'])
        w = self.writing('workspace'); scene = w['structure']['scenes'][0]
        self.writing('structure/metadata', 'PATCH', {'baseVersion': w['structure']['version'], 'clientMutationId': 'only-a-note',
                     'scenePatches': [{'sceneKey': scene['sceneKey'], 'summary': 'Author note only.'}]})
        after = next(s for s in self.writing('alignment')['items'] if s['shotId'] == sid)
        self.assertEqual(after['storyAlignment']['state'], 'in_sync')
        self.assertFalse(after['storyAlignment']['mediaOutdated'])
        self.assertEqual(after['storyOrigin'], before['storyOrigin'])

    def test_native_admission_and_late_candidate_keeps_actual_origin(self):
        shots = self.prepare(); shot = next(s for s in shots if s.get('storyOrigin')); sid = shot['shotId']
        # Native generation admission is real; only the synthetic inference/async execution is intercepted.
        with patch.object(story._POOL, 'submit') as queued:
            task = self.ok('/shots/' + sid + '/image-generations', 'POST', {'appCode': 'flux-soul-cast'})
        task_id = task['taskId']; job = story.record(self.conn, task_id)['_job']; frozen = copy.deepcopy(job['storyProvenance'])
        self.assertEqual(frozen['storyOrigin'], shot['storyOrigin'])
        self.change(1, '@CAST-01 departs.')
        self.ok('/episodes/' + self.ep + '/asset-extractions', 'POST', {})
        current = next(s for s in self.shots() if s['shotId'] == sid)
        # The row is byte-for-byte unchanged: the old row-only late guard would
        # accept this take. The actual origin remains old, despite a newer baseline.
        self.assertEqual(current['storyOrigin'], frozen['storyOrigin'])
        self.assertEqual(store.hash_value(story.find_row(self.conn, sid, 'shot')[1]['cells']), frozen['rowHash'])
        output = {'asset_url': '/projects/api/' + self.slug + '/assets/pa_' + 'b' * 32, 'asset_id': 'pa_' + 'b' * 32, 'content_type': 'image/png'}
        from project_assistant import execution_governance as governance
        with patch.object(worker, 'execute_story_card', return_value=output), patch.object(governance, 'run_operation', side_effect=lambda ctx, key, fn, **kw: fn()):
            story.execute_task(task_id)
        saved = story.record(self.conn, task_id)
        self.assertEqual(saved['status'], 'SUCCEEDED', saved)
        self.assertFalse(saved['result']['selected'])
        candidates = self.ok('/shots/' + sid + '/images')['items']
        receipt = next(c for c in candidates if c['url'] == output['asset_url'])
        self.assertEqual(receipt['storyProvenance'], frozen)
        self.assertNotEqual(receipt['storyProvenance']['baselineVersionId'], story.episode(self.conn, self.ep)['productionScriptVersionId'])
        self.assertEqual(next(s for s in self.shots() if s['shotId'] == sid)['description'], current['description'])


import test_story_hybrid_integration as hybrid


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'isolated PG required')
class ImpactM8Tests(unittest.TestCase):
    setUpClass = classmethod(hybrid.StoryHybridIntegrationTests.setUpClass.__func__)
    tearDownClass = classmethod(hybrid.StoryHybridIntegrationTests.tearDownClass.__func__)
    setUp = hybrid.StoryHybridIntegrationTests.setUp
    tearDown = hybrid.StoryHybridIntegrationTests.tearDown
    request = fixture.StoryHTTPTests.request
    call = fixture.StoryHTTPTests.call
    ok = fixture.StoryHTTPTests.ok
    writing = core.WritingHTTPTests.writing
    error = core.WritingHTTPTests.error
    init = core.WritingHTTPTests.init
    save_doc = core.WritingHTTPTests.save_doc
    prepare = ImpactHTTPTests.prepare
    preview = ImpactHTTPTests.preview
    apply = ImpactHTTPTests.apply
    change = ImpactHTTPTests.change
    shots = ImpactHTTPTests.shots
    nested = hybrid.StoryHybridIntegrationTests.nested
    image = hybrid.StoryHybridIntegrationTests.image
    local_inference = hybrid.StoryHybridIntegrationTests.local_inference
    gate = hybrid.StoryHybridIntegrationTests.gate
    resolve = hybrid.StoryHybridIntegrationTests.resolve

    def queue(self):
        from project_assistant import story_media_adapter as adapter
        shot = next(s for s in self.prepare() if s.get('storyOrigin'))
        self.image(shot['shotId']); self.image(shot['shotId'], cast_reference=True)
        plan = self.ok(self.nested(), 'POST', {'appCode': 'ltx25-cinema', 'shotIds': [shot['shotId']]})
        saved = story.record(self.conn, plan['allocationId'])
        actions = []
        result = adapter.enqueue(self.conn, self.me, self.slug, shot['shotId'], saved['plan']['allocations'][0], {}, actions, frozen_cards=saved['cards'])
        self.runs.append(result['runId']); self.conn.commit()
        return shot, result

    def test_m8_receipt_actual_origin_stays_behind_review_gate(self):
        from project_assistant import story_media_adapter as adapter, orchestrator as cp, orchestration_store as db
        shot, run = self.queue()
        task = db.tasks(self.conn, self.slug, run['runId'])[0]
        frozen = task['input_snapshot']['story_media']['storyProvenance']
        self.assertEqual(frozen['storyOrigin'], shot['storyOrigin'])
        dispatch = cp.claim_dispatch(self.conn, adapter._PRINCIPAL, list(adapter.KEYS), allowed_projects=[self.slug]); self.conn.commit()
        with patch.object(worker, 'comfyui', side_effect=self.local_inference):
            adapter.execute(dispatch)
        completed = db.get_dispatch(self.conn, self.slug, dispatch['id'])
        self.assertEqual(completed['status'], 'awaiting_gate', completed)
        self.assertNotIn('storyProvenance', completed['output_json'])
        self.assertEqual(story.record(self.conn, 'smr_' + dispatch['id'])['storyProvenance'], frozen)
        url = completed['output_json']['asset_url']
        # Pending local receipts must NOT expose a selectable video and bypass M8 review.
        self.assertFalse(any(c['url'] == url for c in self.ok('/shots/' + shot['shotId'] + '/videos')['items']))
        gate = self.gate(run['runId']); self.resolve(gate)
        candidate = next(c for c in self.ok('/shots/' + shot['shotId'] + '/videos')['items'] if c['url'] == url)
        self.assertEqual(candidate['storyProvenance'], frozen)

    def test_m8_metadata_source_change_rejects_late_output_without_row_overwrite(self):
        from project_assistant import story_media_adapter as adapter, orchestrator as cp, orchestration_store as db
        shot, run = self.queue()
        dispatch = cp.claim_dispatch(self.conn, adapter._PRINCIPAL, list(adapter.KEYS), allowed_projects=[self.slug]); self.conn.commit()
        before = next(s for s in self.shots() if s['shotId'] == shot['shotId'])['selectedVideoUrl']
        def late(task, config, head):
            # Upload while lease is valid, then change only story acknowledgement metadata.
            result = self.local_inference(task, config, head)
            p = self.preview(shotIds=[shot['shotId']])
            self.apply(p, [{'actionId': 'keep:' + shot['shotId']}])
            return result
        with patch.object(worker, 'comfyui', side_effect=late):
            adapter.execute(dispatch)
        self.assertEqual(next(s for s in self.shots() if s['shotId'] == shot['shotId'])['selectedVideoUrl'], before)
        with self.conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM projectops.assistant_proposal WHERE dispatch_id=%s', (dispatch['id'],))
            self.assertEqual(cur.fetchone()[0], 0)
        task = db.tasks(self.conn, self.slug, run['runId'])[0]
        with self.assertRaises(cp.OrchestrationError):
            adapter.verify_task(self.conn, task)
        self.conn.rollback()


class PureImpactTests(unittest.TestCase):
    def test_duplicate_unknown_receipts_never_invent_generation_origin(self):
        evidence = {'originKnown': True, 'storyOrigin': {'versionId': 'old'}}
        records = [{'url': '/same', 'storyProvenance': evidence}, {'url': '/same'}]
        self.assertIsNone(impact.candidate_evidence(records, '/same'))
        self.assertIsNone(impact.candidate_evidence([], '/legacy'))
        self.assertIs(impact.dispatch(None, None, 'GET', 'unknown', {}, {}), store.UNHANDLED)
