"""V12: repeated paragraphs and hard breaks, through authorized HTTP and isolated PG."""
import copy
import os
import unittest
import uuid

import test_writing_core as core
from project_docs import story_openapi as story, writing_store as store, writing_structure as structure


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'isolated PG required')
class StoryboardOwnershipHTTPTests(unittest.TestCase):
    request = core.WritingHTTPTests.request
    setUp = core.WritingHTTPTests.setUp
    tearDown = core.WritingHTTPTests.tearDown
    call = core.WritingHTTPTests.call
    ok = core.WritingHTTPTests.ok
    writing = core.WritingHTTPTests.writing
    init = core.WritingHTTPTests.init
    save_doc = core.WritingHTTPTests.save_doc

    def prepare(self, doc):
        self.init()
        self.save_doc(doc)
        self.ok('/episodes/'+self.ep+'/asset-extractions', 'POST', {})

    def shots(self):
        return {s['shotId']: s for s in self.ok('/episodes/'+self.ep+'/shots?limit=100')['items']
                if s['tabKey'] == 'cinema-studio' and s.get('sceneId')}

    def build_checked(self, mode, count, new):
        before = self.shots()
        estimate = self.ok('/episodes/'+self.ep+'/storyboard-estimates', 'POST',
                           {'breakdownModes': [mode]})['modes'][0]
        task = self.ok('/episodes/'+self.ep+'/storyboards', 'POST', {'breakdownMode': mode})
        after = self.shots()
        self.assertEqual((estimate['shotCount'], estimate['newShots'], estimate['keptShots']),
                         (count, new, len(before)), estimate)
        self.assertEqual(task['result']['shotsCount'], count)
        self.assertEqual(len(after), count)
        self.assertEqual(len(set(after)-set(before)), new)
        self.assertEqual(estimate['plannedSeconds'], sum(s['previsPlan']['seconds'] for s in after.values()))
        return after

    def test_repeated_paragraphs_keep_uncertain_origin_and_director_edits_across_builds(self):
        self.prepare(core.document('Scene 01: Confrontation',
            '@CAST-01 faces the lens, fighting back tears.', '@CAST-02: "Tell me the truth."',
            '@CAST-01 faces the lens, fighting back tears.'))
        shots = self.build_checked('auto', 3, 3)
        uncertain = [s for s in shots.values() if s['storyOrigin']['mapping'] == 'ambiguous']
        self.assertEqual(len(uncertain), 2)
        for shot in uncertain:
            self.assertEqual(shot['storyOrigin']['beatKeys'], [])
            url = '/projects/api/'+self.slug+'/assets/pa_'+'e'*32
            story.mutate_row(self.conn, self.me, self.slug, shot['tabKey'], shot['rowId'],
                            {1: 'Director optics', 2: 'Director motion', 3: 'Director: stay on the tearful face.',
                             5: '[Video]('+url+')', 6: 'Approved'})
            story.store(self.conn, 'ca_'+uuid.uuid4().hex, 'candidate',
                        {'entityId': shot['shotId'], 'kind': 'video', 'url': url+'?take=2'}, self.slug)
            meta = story.shot_meta(self.conn, shot['shotId'])
            meta['previsPlan']['seconds'] = 6.5
            story.store(self.conn, 'meta_'+shot['shotId'], 'shot_meta', meta, self.slug)
        self.conn.commit()
        before = self.shots()
        takes = {s['shotId']: self.ok('/shots/'+s['shotId']+'/videos')['items'] for s in uncertain}
        for mode in ('auto', 'auto', 'cinematic', 'scene', 'auto'):
            after = self.build_checked(mode, 3, 0)
            self.assertEqual(after, before)
        scene_id = next(iter(before.values()))['sceneId']
        for _ in range(2):
            self.assertEqual(self.ok('/scenes/'+scene_id+'/shot-rebuilds', 'POST', {})['result']['shotsCount'], 3)
            current = self.shots()
            self.assertEqual(set(current), set(before))
            for shot in uncertain:
                self.assertEqual(current[shot['shotId']], before[shot['shotId']])
                self.assertEqual(self.ok('/shots/'+shot['shotId']+'/videos')['items'], takes[shot['shotId']])
        self.build_checked('auto', 3, 0)

    def test_ambiguous_foreign_detached_and_split_relationships_never_rewrite_or_alias(self):
        self.prepare(core.document('Scene 01: A', '@CAST-01 confronts the camera.',
                                   'Scene 02: B', '@CAST-02: "Why did you lie?"'))
        initial = self.build_checked('auto', 2, 2)
        a, b = initial.values()
        scope = store.scope_for(self.conn, self.me, self.ep, write=True)
        saved = structure.read_structure(self.conn, scope)
        key_a, key_b = [s['sceneKey'] for s in saved['scenes']]
        protected = []
        for kind, key in (('foreign', 'wsc_foreign'), ('detached', key_a), ('split', key_b)):
            shot = self.ok('/scenes/'+a['sceneId']+'/shots', 'POST', {'description': 'Protected '+kind})
            meta = story.shot_meta(self.conn, shot['shotId'])
            meta['storyOrigin'] = {'sceneKeys': [key], 'beatKeys': [], 'mapping': 'ambiguous'}
            if kind == 'detached':
                # A stale compatibility ID and even a surviving exact origin do
                # not cancel an explicit detach marker.
                meta['storyOrigin'] = copy.deepcopy(a['storyOrigin'])
                meta['detachedScene'] = {'sceneKeys': [key], 'legacySceneId': a['sceneId'], 'state': 'ambiguous'}
            story.store(self.conn, 'meta_'+shot['shotId'], 'shot_meta', meta, self.slug)
            protected.append(shot['shotId'])
        # A split marker means even an active old scene key cannot choose a half.
        saved['lineage']['wsc_split_child'] = 'split:'+key_b
        structure.persist(self.conn, scope, saved)
        self.conn.commit()
        before = self.shots()
        metas = {sid: copy.deepcopy(story.shot_meta(self.conn, sid)) for sid in protected}
        for scene_id in (a['sceneId'], b['sceneId']):
            self.ok('/scenes/'+scene_id+'/shot-rebuilds', 'POST', {})
        self.ok('/episodes/'+self.ep+'/storyboards', 'POST', {})
        after = self.shots()
        self.assertEqual(set(after), set(before))
        for sid in protected:
            self.assertEqual(after[sid], before[sid])
            self.assertEqual(story.shot_meta(self.conn, sid), metas[sid])
        projected = self.writing('structure')['scenes']
        # Foreign and split ambiguity remain excluded from outline ownership.
        # The synthetic exact+detached row tests only the build's write guard.
        self.assertFalse({protected[0], protected[2]} & {sid for scene in projected for sid in scene['shotIds']})

    def test_hard_break_inside_a_paragraph_does_not_create_an_unowned_scene(self):
        doc = core.document('Scene 01: Confrontation', '@CAST-01 faces the lens, trembling.',
                            'Scene 02: Answer', '@CAST-02: "I was afraid."')
        doc['content'][1]['content'] += [{'type': 'hardBreak'},
                                       {'type': 'text', 'text': 'Scene 99: words inside the same paragraph'}]
        self.prepare(doc)
        legacy = self.ok('/episodes/'+self.ep+'/scenes')['items']
        stable = self.writing('structure')['scenes']
        self.assertEqual(len(legacy), len(stable))
        self.assertEqual(len(legacy), 2)
        self.assertIn('Scene 99:', legacy[0]['content'])
        self.assertEqual([s['sceneId'] for s in legacy], [s['legacySceneId'] for s in stable])
        first = self.build_checked('auto', 2, 2)
        self.assertTrue(all(s['storyOrigin']['mapping'] != 'unbound' for s in first.values()))
        for _ in range(3):
            self.assertEqual(self.build_checked('auto', 2, 0), first)

    def test_dialogue_hard_break_preserves_cutting_without_fabricating_exact_beats(self):
        doc = core.document('Scene 01: Confrontation', '@CAST-01 faces the lens, fighting back tears.')
        doc['content'][1]['content'] += [{'type': 'hardBreak'},
                                       {'type': 'text', 'text': '@CAST-02: "Tell me the truth."'}]
        self.prepare(doc)
        first = self.build_checked('auto', 2, 2)
        self.assertTrue(all(s['storyOrigin']['mapping'] == 'scene_only' for s in first.values()))
        self.assertTrue(all(s['storyOrigin']['beatKeys'] == [] for s in first.values()))
        self.assertTrue(any(s['dialogue'] for s in first.values()))
        for _ in range(3):
            self.assertEqual(self.build_checked('auto', 2, 0), first)


if __name__ == '__main__':
    unittest.main()
