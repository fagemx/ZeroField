"""J2/J4 regressions against real authorized HTTP and the lane's isolated PostgreSQL."""
import copy
import json
import os
import unittest
import uuid
from unittest.mock import patch
import test_writing_core as core
from project_docs import writing_store as store, writing_structure as structure, story_openapi as story, repository as repo


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'isolated PG required')
class ReviewStructureHTTPTests(unittest.TestCase):
    request = core.WritingHTTPTests.request
    setUp = core.WritingHTTPTests.setUp
    tearDown = core.WritingHTTPTests.tearDown
    call = core.WritingHTTPTests.call
    ok = core.WritingHTTPTests.ok
    writing = core.WritingHTTPTests.writing
    error = core.WritingHTTPTests.error
    init = core.WritingHTTPTests.init
    save_doc = core.WritingHTTPTests.save_doc

    def prepare(self):
        self.init()
        self.save_doc(core.document('Scene 01: Same', '@CAST-01 opens the red door.',
            'Scene 02: Same', '@CAST-02 raises the blue lamp.', 'Scene 03: Same', '@CAST-03 closes the green gate.'))
        self.ok('/episodes/'+self.ep+'/asset-extractions', 'POST', {})
        self.ok('/episodes/'+self.ep+'/storyboards', 'POST', {})
        self.original = [s for s in self.shots().values() if s.get('storyOrigin')]
        self.assertEqual(len(self.original), 3)
        self.keys = [s['sceneKey'] for s in self.writing('workspace')['structure']['scenes']]
        # Two distinct persisted synthetic takes per shot, with no inference or media reads.
        for i, shot in enumerate(self.original):
            url = '/projects/api/'+self.slug+'/assets/pa_'+str(i+1)*32
            story.mutate_row(self.conn, self.me, self.slug, shot['tabKey'], shot['rowId'], {5:'[Video]('+url+')', 6:'Approved'})
            for take in (1, 2):
                story.store(self.conn, 'ca_'+uuid.uuid4().hex, 'candidate',
                    {'entityId':shot['shotId'], 'kind':'video', 'url':url+'?take='+str(take)}, self.slug)
        self.conn.commit()
        self.original = [self.shots()[s['shotId']] for s in self.original]
        self.takes = {s['shotId']:self.ok('/shots/'+s['shotId']+'/videos')['items'] for s in self.original}
        return self.original

    def shots(self):
        return {s['shotId']:s for s in self.ok('/episodes/'+self.ep+'/shots?limit=100')['items']}

    def operation(self, value, apply=True):
        ws = self.writing('workspace')
        preview = self.writing('previews', 'POST', {'kind':'structure', 'targetDocHash':ws['docHash'],
            'structureVersion':ws['structure']['version'], 'operation':value})
        if not apply:
            return preview
        return self.writing('previews/'+preview['previewId']+'/apply', 'POST', {'expectedPreviewVersion':preview['version'],
            'selection':{'actions':[{'actionId':'structure'}]}})

    def assert_preserved(self, shot, origin=True):
        current = self.shots()[shot['shotId']]
        for key in ('rowId','selectedVideoUrl','reviewStatus'):
            self.assertEqual(current[key], shot[key], key)
        if origin:
            self.assertEqual(current['storyOrigin'], shot['storyOrigin'])
        self.assertEqual(self.ok('/shots/'+shot['shotId']+'/videos')['items'], self.takes[shot['shotId']])
        return current

    def test_remove_reorder_merge_then_legacy_build_and_rebuild(self):
        a, b, c = self.prepare()
        self.operation({'type':'remove', 'sceneKey':self.keys[1]})
        active = self.writing('structure')['scenes']
        removed = self.assert_preserved(b)
        self.assertNotIn(removed.get('sceneId'), [s['legacySceneId'] for s in active],
            'removed B must not alias C, which now occupies S02')
        self.assertEqual(next(s for s in self.writing('alignment')['items'] if s['shotId']==b['shotId'])['storyAlignment']['state'], 'source_removed')
        self.operation({'type':'move', 'sceneKey':self.keys[2], 'afterSceneKey':None})
        self.assert_preserved(a); self.assert_preserved(b); self.assert_preserved(c)
        self.ok('/episodes/'+self.ep+'/asset-extractions', 'POST', {})
        self.ok('/episodes/'+self.ep+'/storyboards', 'POST', {})
        current = self.writing('structure')['scenes']
        for scene in current:
            self.ok('/scenes/'+scene['legacySceneId']+'/shot-rebuilds', 'POST', {})
        self.assertEqual(self.shots()[b['shotId']]['description'], b['description'])
        self.assert_preserved(b)
        # Explicit merge is a stable redirect, not deletion or an ordinal guess.
        pre_merge = self.shots()
        self.operation({'type':'merge', 'sceneKeys':[self.keys[0],self.keys[2]], 'keepSceneKey':self.keys[0]})
        merged = self.writing('structure')['scenes'][0]
        self.assertEqual(self.shots()[c['shotId']]['sceneId'], merged['legacySceneId'])
        for shot in (a,b,c):
            self.assertEqual(self.shots()[shot['shotId']]['storyOrigin'],pre_merge[shot['shotId']]['storyOrigin'])
        for shot in (a, b, c): self.assert_preserved(shot, origin=shot is b)
        self.ok('/episodes/'+self.ep+'/asset-extractions', 'POST', {})
        self.ok('/episodes/'+self.ep+'/storyboards', 'POST', {})
        self.ok('/scenes/'+merged['legacySceneId']+'/shot-rebuilds', 'POST', {})
        self.assertEqual(self.shots()[b['shotId']]['description'], b['description'])
        for shot in (a, b, c): self.assert_preserved(shot, origin=shot is b)

    def test_legacy_scene_order_and_merge_do_not_resurrect_a_removed_association(self):
        a,b,c = self.prepare()
        self.operation({'type':'remove','sceneKey':self.keys[1]})
        ids = [s['sceneId'] for s in self.ok('/episodes/'+self.ep+'/scenes')['items']]
        self.ok('/episodes/'+self.ep+'/scene-order','PUT',{'sceneIds':list(reversed(ids))})
        scenes = self.writing('structure')['scenes']
        self.assertEqual([s['sceneKey'] for s in scenes],[self.keys[2],self.keys[0]])
        for shot in (a,b,c): self.assert_preserved(shot)
        self.ok('/scene-merges','POST',{'sceneIds':[s['legacySceneId'] for s in scenes]})
        current = self.writing('structure')['scenes'][0]
        self.assertEqual(current['sceneKey'],self.keys[2])
        for shot in (a,b,c): self.assert_preserved(shot)
        self.ok('/episodes/'+self.ep+'/asset-extractions','POST',{})
        self.ok('/episodes/'+self.ep+'/storyboards','POST',{})
        self.ok('/scenes/'+current['legacySceneId']+'/shot-rebuilds','POST',{})
        self.assertEqual(self.shots()[b['shotId']]['description'],b['description'])
        self.assert_preserved(b)
        for shot in (a,c): self.assert_preserved(shot,origin=False)

    def test_structure_undo_restores_only_the_original_detached_source_relationship(self):
        a,b,c = self.prepare()
        removed = self.operation({'type':'remove','sceneKey':self.keys[1]})
        self.assertIsNone(self.shots()[b['shotId']]['sceneId'])
        self.operation({'type':'restore','snapshotId':removed['beforeVersionId']})
        scenes = self.writing('structure')['scenes']
        self.assertEqual([s['sceneKey'] for s in scenes],self.keys)
        for shot in (a,b,c):
            current = self.assert_preserved(shot)
            self.assertEqual(current['sceneId'],shot['sceneId'])
            self.assertNotIn('detachedScene',current)
        self.assertEqual(scenes[1]['shotIds'],[b['shotId']])

    def test_failed_detach_rolls_back_doc_sidecar_metadata_and_before_snapshot(self):
        a, b, c = self.prepare()
        before = self.writing('workspace')
        preview = self.operation({'type':'remove','sceneKey':self.keys[1]}, apply=False)
        original = repo.tab_locks
        def locked(conn, slug, key):
            return original(conn,slug,key)|({b['rowId']:'another-writer'} if key==b['tabKey'] else {})
        count = len(self.writing('versions')['items'])
        with patch.object(repo,'tab_locks',locked):
            self.error('previews/'+preview['previewId']+'/apply','POST',{'expectedPreviewVersion':1,
                'selection':{'actions':[{'actionId':'structure'}]}},409)
        after = self.writing('workspace')
        self.assertEqual((after['docHash'],after['structureHash']), (before['docHash'],before['structureHash']))
        self.assertEqual(len(self.writing('versions')['items']),count)
        self.assertEqual(self.writing('previews/'+preview['previewId'])['status'],'pending')
        for shot in (a,b,c):
            self.assertEqual(self.assert_preserved(shot)['sceneId'],shot['sceneId'])

    def test_legacy_rebuild_rejects_a_pre_fix_stale_positional_alias(self):
        a, b, c = self.prepare()
        self.operation({'type':'remove','sceneKey':self.keys[1]})
        current = self.writing('structure')['scenes'][1]
        # Simulate persisted metadata written by the reviewed candidate, before this repair.
        meta = story.shot_meta(self.conn,b['shotId'])
        meta.pop('detachedScene',None);meta['sceneId']=current['legacySceneId']
        story.store(self.conn,'meta_'+b['shotId'],'shot_meta',meta,self.slug)
        self.conn.commit()
        self.ok('/episodes/'+self.ep+'/asset-extractions','POST',{})
        self.ok('/episodes/'+self.ep+'/storyboards','POST',{})
        self.ok('/scenes/'+current['legacySceneId']+'/shot-rebuilds','POST',{})
        self.assertEqual(self.shots()[b['shotId']]['description'],b['description'])
        self.assert_preserved(b)
        self.assertEqual(next(s for s in self.writing('alignment')['items'] if s['shotId']==b['shotId'])['storyAlignment']['state'],'source_removed')

    def test_scene_only_split_is_detached_and_projected_as_uncertain_not_a_new_scene(self):
        a,b,c = self.prepare()
        doc = copy.deepcopy(self.writing('workspace')['doc'])
        new = core.document('@CAST-01 turns toward the stairs.')['content'][0]
        doc['content'].insert(2,new);self.save_doc(doc)
        meta = story.shot_meta(self.conn,a['shotId']);meta.pop('storyOrigin')
        story.store(self.conn,'meta_'+a['shotId'],'shot_meta',meta,self.slug)
        scope = store.scope_for(self.conn,self.me,self.ep,write=True)
        saved = structure.read_structure(self.conn,scope)
        saved['legacyBindings'].append({'shotId':a['shotId'],'sceneKey':self.keys[0],'mapping':'scene_only'})
        structure.persist(self.conn,scope,saved);self.conn.commit()
        self.operation({'type':'split','sceneKey':self.keys[0],'atBid':structure.bid(new),'title':'Same'})
        scenes = self.writing('structure')['scenes']
        self.assertNotIn(a['shotId'],[sid for scene in scenes for sid in scene['shotIds']])
        self.assertIsNone(self.shots()[a['shotId']]['sceneId'])
        self.assertEqual(self.shots()[a['shotId']]['detachedScene']['state'],'ambiguous')
        self.assertEqual(next(s for s in self.writing('alignment')['items'] if s['shotId']==a['shotId'])['storyAlignment']['state'],'ambiguous')
        self.assert_preserved(a,origin=False)

    def test_explicit_chained_merge_keeps_scene_only_lineage_without_fabricating_origin(self):
        a,b,c = self.prepare()
        meta = story.shot_meta(self.conn,b['shotId']);meta.pop('storyOrigin')
        story.store(self.conn,'meta_'+b['shotId'],'shot_meta',meta,self.slug)
        scope = store.scope_for(self.conn,self.me,self.ep,write=True)
        saved = structure.read_structure(self.conn,scope)
        saved['legacyBindings'].append({'shotId':b['shotId'],'sceneKey':self.keys[1],'mapping':'scene_only'})
        structure.persist(self.conn,scope,saved);self.conn.commit()
        self.operation({'type':'merge','sceneKeys':self.keys[:2],'keepSceneKey':self.keys[0]})
        self.operation({'type':'merge','sceneKeys':[self.keys[0],self.keys[2]],'keepSceneKey':self.keys[2]})
        scene = self.writing('structure')['scenes'][0]
        current = self.assert_preserved(b,origin=False)
        self.assertNotIn('storyOrigin',current)
        self.assertEqual(current['sceneId'],scene['legacySceneId'])
        self.assertIn({'shotId':b['shotId'],'mapping':'scene_only'},scene['shotLinks'])
        alignment = next(s for s in self.writing('alignment')['items'] if s['shotId']==b['shotId'])
        self.assertEqual(alignment['storyAlignment']['state'],'unbound')
        self.assertNotIn('source_removed',alignment['storyAlignment']['reasons'])
        self.assertEqual(alignment['storyOrigin']['sceneKeys'],[self.keys[1]])

    def test_workspace_and_structure_project_stable_current_references_without_persisting(self):
        a, b, c = self.prepare()
        before = self.writing('workspace')
        for tail in ('workspace','structure'):
            value = self.writing(tail)
            scenes = value['structure']['scenes'] if tail=='workspace' else value['scenes']
            self.assertEqual(scenes[0]['assetCodes'], ['CAST-01'])
            self.assertEqual(scenes[0]['shotIds'], [a['shotId']])
            self.assertEqual(scenes[0]['shotLinks'], [{'shotId':a['shotId'], 'mapping':'exact'}])
            projected = value['structure'] if tail=='workspace' else value
            self.assertEqual(structure.fingerprint(projected),projected['structureHash'])
        scope = store.scope_for(self.conn, self.me, self.ep)
        saved = store.get_record(self.conn, scope, 'writing_structure', structure.identifier(scope))
        self.assertNotIn('shotIds', saved['scenes'][0])
        self.assertNotIn('assetCodes', saved['scenes'][0])
        self.conn.rollback()
        version = self.writing('versions','POST',{'name':'Projection is not authority','sourceRef':{'kind':'working'},
            'expectedSourceHash':before['docHash'],'share':True})
        self.assertNotIn('shotIds',version['snapshot']['structure']['scenes'][0])
        self.assertNotIn('assetCodes',version['snapshot']['structure']['scenes'][0])
        story.mutate_row(self.conn, self.me, self.slug, a['tabKey'], a['rowId'],
            {5:'[Video](/projects/api/'+self.slug+'/assets/pa_'+'f'*32+')',6:'Retake'})
        self.conn.commit()
        after = self.writing('workspace')
        self.assertEqual((after['docHash'],after['structureHash'],after['structure']['version']),
            (before['docHash'],before['structureHash'],before['structure']['version']))
        meta = self.writing('structure/metadata', 'PATCH', {'baseVersion':before['structure']['version'],
            'clientMutationId':'summary', 'scenePatches':[{'sceneKey':self.keys[0], 'summary':'Keep metadata', 'storyTime':'Night'}]})
        self.error('structure/metadata','PATCH',{'baseVersion':before['structure']['version'],
            'clientMutationId':'stale-summary','scenePatches':[{'sceneKey':self.keys[0],'summary':'Lost'}]},409)
        self.operation({'type':'move','sceneKey':self.keys[0],'afterSceneKey':self.keys[2]})
        scenes = self.writing('workspace')['structure']['scenes']
        moved = next(s for s in scenes if s['sceneKey']==self.keys[0])
        self.assertEqual((moved['summary'],moved['storyTime'],moved['shotIds']), ('Keep metadata','Night',[a['shotId']]))
        self.assertEqual(meta['scenes'][0]['summary'], 'Keep metadata')
        projected = self.writing('structure')
        scope = store.scope_for(self.conn,self.me,self.ep,write=True)
        roundtrip = structure.persist(self.conn,scope,projected,base_version=projected['version'])
        self.assertNotIn('shotIds',roundtrip['scenes'][0])
        self.assertNotIn('assetCodes',roundtrip['scenes'][0])
        self.assertNotIn('shotLinks',roundtrip['scenes'][0])
        self.conn.rollback()

    def test_projection_excludes_foreign_removed_and_ambiguous_links_keeps_legacy_honest(self):
        a, b, c = self.prepare()
        # A real pre-origin legacy shot has only its frozen initialization relationship.
        meta = story.shot_meta(self.conn, a['shotId']); meta.pop('storyOrigin'); meta.pop('storyAlignment')
        story.store(self.conn, 'meta_'+a['shotId'], 'shot_meta', meta, self.slug)
        scope = store.scope_for(self.conn, self.me, self.ep, write=True)
        saved = structure.read_structure(self.conn, scope)
        saved['legacyBindings'].append({'shotId':a['shotId'],'sceneKey':self.keys[0],'mapping':'scene_only'})
        structure.persist(self.conn, scope, saved)
        # A positional ID must not override an explicit foreign origin.
        meta = story.shot_meta(self.conn, c['shotId'])
        meta['storyOrigin'] = {'sceneKeys':['wsc_foreign'], 'beatKeys':['wbt_foreign'], 'mapping':'exact'}
        story.store(self.conn, 'meta_'+c['shotId'], 'shot_meta', meta, self.slug)
        self.conn.commit()
        second = self.ok('/projects/pj_'+self.slug+'/episodes','POST',{'title':'Foreign episode'})
        foreign_scene = self.ok('/episodes/'+second['episodeId']+'/scenes','POST',{'title':'Foreign scene','content':'Private to another episode'})
        foreign_shot = self.ok('/scenes/'+foreign_scene['sceneId']+'/shots','POST',{'description':'Foreign shot'})
        foreign_meta = story.shot_meta(self.conn,foreign_shot['shotId'])|{'storyOrigin':a['storyOrigin']}
        story.store(self.conn,'meta_'+foreign_shot['shotId'],'shot_meta',foreign_meta,self.slug);self.conn.commit()
        private = self.writing('sources/novel','PUT',{'baseVersion':0,'clientMutationId':'private-projection',
            'doc':core.document('@CAST-99 private source not part of the screenplay'),'structure':{},'composition':{}})
        other = str(uuid.uuid4());repo.upsert_member(self.conn,other,'Other admin','admin');self.conn.commit()
        try:
            with patch.dict(os.environ,{'OPENBENCH_TOKENS':json.dumps({self.member_token:other})}):
                other_workspace = self.writing('workspace')
                self.assertNotIn(private['sourceId'],json.dumps(other_workspace))
                self.assertNotIn('CAST-99',json.dumps(other_workspace))
                self.assertNotIn(foreign_shot['shotId'],json.dumps(other_workspace['structure']))
        finally:
            with self.conn.cursor() as cur: cur.execute('DELETE FROM projectops.member WHERE actor_id=%s',(other,))
            self.conn.commit()
        scenes = self.writing('workspace')['structure']['scenes']
        self.assertEqual(scenes[0]['shotLinks'], [{'shotId':a['shotId'],'mapping':'scene_only'}])
        self.assertEqual(scenes[2]['shotIds'], [])
        self.operation({'type':'remove','sceneKey':self.keys[1]})
        self.assertNotIn(b['shotId'], [sid for s in self.writing('structure')['scenes'] for sid in s['shotIds']])
        from project_assistant import store as assistant_store
        assistant_store.set_member_enabled(self.conn, self.slug, self.actor, False, self.actor)
        self.conn.commit()
        self.error('workspace','GET',None,403)
        self.error('structure','GET',None,403)


if __name__ == '__main__': unittest.main()
