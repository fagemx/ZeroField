"""Real PG/HTTP impact GET freshness with the committed impact-owned domain helper.

The integration runner supplies that frozen module; no impact implementation,
row-fingerprint check, parser, store, receipt, transport or apply is mocked.
"""
import copy
import os
import unittest
from unittest.mock import patch
import test_writing_core as core_fixture
from project_docs import story_openapi as story, repository as repo, service


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'),'isolated PG required')
class ImpactPreviewProjectionHTTPTests(unittest.TestCase):
    request=core_fixture.WritingHTTPTests.request
    setUp=core_fixture.WritingHTTPTests.setUp
    tearDown=core_fixture.WritingHTTPTests.tearDown
    call=core_fixture.WritingHTTPTests.call
    ok=core_fixture.WritingHTTPTests.ok
    writing=core_fixture.WritingHTTPTests.writing
    error=core_fixture.WritingHTTPTests.error
    init=core_fixture.WritingHTTPTests.init
    save_doc=core_fixture.WritingHTTPTests.save_doc

    def prepare_impact(self):
        self.init()
        self.save_doc(core_fixture.document('Scene 01: Arrival','@CAST-01 opens the door.','Scene 02: Signal','@CAST-01 turns toward the lamp.'))
        self.ok('/episodes/'+self.ep+'/asset-extractions','POST',{})
        self.ok('/episodes/'+self.ep+'/storyboards','POST',{})
        shots=[s for s in self.ok('/episodes/'+self.ep+'/shots')['items'] if s.get('storyOrigin')]
        self.assertEqual(len(shots),2)
        doc=copy.deepcopy(self.writing('workspace')['doc'])
        doc['content'][1]['content']=[{'type':'text','text':'@CAST-01 closes the door.'}]
        doc['content'][3]['content']=[{'type':'text','text':'@CAST-01 raises the lamp.'}]
        self.save_doc(doc)
        ws=self.writing('workspace')
        preview=self.writing('previews','POST',{'kind':'impact','targetRef':{'kind':'working'},'expectedSourceHash':ws['docHash'],
            'confirmBaseline':True,'shotIds':[s['shotId'] for s in shots]})
        return shots,preview

    def test_row_only_stale_get_does_not_block_unchanged_selected_apply(self):
        shots,preview=self.prepare_impact();first,second=shots
        before=self.writing('previews/'+preview['previewId'])
        self.assertFalse(before['sharedStale']);self.assertFalse(before['stale']);self.assertEqual(before['staleActionIds'],[])
        baseline=self.writing('workspace')['baseline']['versionId']
        _,row=story.find_row(self.conn,second['shotId'],'shot')
        story.mutate_row(self.conn,service.Identity(self.actor,'Projection test','admin'),self.slug,row['tabKey'],row['rid'],{3:'Concurrent director edit.'})
        self.conn.commit()
        current=self.writing('previews/'+preview['previewId'])
        self.assertFalse(current['sharedStale']);self.assertTrue(current['stale'])
        self.assertIn('update:'+second['shotId'],current['staleActionIds'])
        self.assertNotIn('update:'+first['shotId'],current['staleActionIds'])
        self.assertEqual(current['version'],preview['version']);self.assertEqual(current['status'],'pending')
        self.assertEqual(self.writing('workspace')['baseline']['versionId'],baseline)
        both={'expectedPreviewVersion':preview['version'],'selection':{'actions':[{'actionId':'update:'+s['shotId']} for s in shots]}}
        self.error('previews/'+preview['previewId']+'/apply','POST',both,409)
        # The aggregate read label is not a new apply guard. Same frozen preview,
        # unchanged first row only: actual domain apply succeeds atomically.
        result=self.writing('previews/'+preview['previewId']+'/apply','POST',{'expectedPreviewVersion':preview['version'],
            'selection':{'actions':[{'actionId':'update:'+first['shotId'],'fields':['description']}]}})
        self.assertIsInstance(result,dict)
        current={s['shotId']:s for s in self.ok('/episodes/'+self.ep+'/shots')['items']}
        self.assertIn('closes the door',current[first['shotId']]['description'])
        self.assertEqual(current[second['shotId']]['description'],'Concurrent director edit.')

    def test_domain_authority_revocation_propagates_instead_of_false_freshness(self):
        from project_docs import writing_impact
        from project_assistant import store as assistant_store
        _,preview=self.prepare_impact()
        original=writing_impact.validate_preview
        def revoke_then_validate(conn,scope,frozen):
            # Commit revocation after the core route check, then execute the real
            # frozen helper and its current-authority check. No fake error/result.
            assistant_store.set_member_enabled(self.conn,self.slug,self.actor,False,self.actor)
            self.conn.commit()
            return original(conn,scope,frozen)
        with patch.object(writing_impact,'validate_preview',revoke_then_validate):
            self.error('previews/'+preview['previewId'],'GET',None,403)

    def test_shared_source_staleness_still_blocks_selected_apply(self):
        shots,preview=self.prepare_impact()
        doc=copy.deepcopy(self.writing('workspace')['doc']);doc['content'][1]['content']=[{'type':'text','text':'A newer screenplay revision.'}]
        self.save_doc(doc)
        current=self.writing('previews/'+preview['previewId'])
        self.assertTrue(current['sharedStale']);self.assertTrue(current['stale'])
        self.assertIsInstance(current['staleActionIds'],list)
        self.error('previews/'+preview['previewId']+'/apply','POST',{'expectedPreviewVersion':preview['version'],
            'selection':{'actions':[{'actionId':'update:'+shots[0]['shotId'],'fields':['description']}]}},409)


if __name__=='__main__': unittest.main()
