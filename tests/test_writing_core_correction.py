"""Corrected W7 layouts through actual import, save, compare and adoption APIs.

Run with the tools modules installed/merged (or explicitly on the test process's
project_docs package path); no parser, store, transport or receipt is mocked.
"""
import copy
import os
import unittest
import uuid
from unittest.mock import patch
import test_writing_core as core_fixture
from project_docs import writing_store as store, writing_structure as structure
from project_docs import story_openapi as story, repository as repo


class AuthoredPartitionPureTests(unittest.TestCase):
    def test_explicit_merge_beats_duplicate_heading_grammar_without_source_rewrite(self):
        from project_docs import writing_versions as versions
        doc=store.checked_doc({'type':'doc','content':[{'type':'paragraph','attrs':{'bid':'b_'+uuid.uuid4().hex},
            'content':[{'type':'text','text':text}]} for text in ('Scene 01: Same','First.','Scene 01: Same','Second.')]})
        identifiers=[structure.bid(n) for n in doc['content']]
        previous={'scenes':[{'sceneKey':'wsc_'+uuid.uuid4().hex,'headingBid':identifiers[0],'blockBids':identifiers[1:],
            'title':'Authored title','order':1,'beats':[{'beatKey':'wbt_'+uuid.uuid4().hex,'blockBids':[b],'textHash':store.hash_value(story.node_text(n)),
                'contentHash':structure._content_hash([n])} for b,n in zip(identifiers[1:],doc['content'][1:])],
            'contentHash':structure._content_hash(doc['content'])}],'lanes':[],'tombstones':[],'lineage':{},'docHash':store.doc_hash(doc)}
        source={'doc':doc,'structure':previous,'sourceFile':{'uploadHash':'frozen-upload'}}
        authored=versions.reference_structure(source)
        edited=copy.deepcopy(doc);edited['content'][1]['content'][0]['text']='First, edited.'
        edited['content'][1]['content'].extend([{'type':'hardBreak'},{'type':'text','text':'INT. MARKED ROOM','marks':[{'type':'bold'}]}])
        reconciled=structure.reconcile_structure(edited,authored)
        self.assertEqual(len(reconciled['scenes']),1)
        self.assertEqual(reconciled['scenes'][0]['sceneKey'],previous['scenes'][0]['sceneKey'])
        self.assertEqual(reconciled['scenes'][0]['title'],'Authored title')
        materialized,result,changes=versions.materialize_authored(edited,reconciled)
        self.assertEqual(len(story.scene_sections(story.doc_text(materialized))),1)
        self.assertEqual(result['scenes'][0]['sceneKey'],previous['scenes'][0]['sceneKey'])
        self.assertEqual(story.doc_text(edited).count('Scene 01: Same'),2)
        self.assertEqual(story.doc_text(materialized).count('> Scene 01: Same'),2)
        again,_,_=versions.materialize_authored(materialized,result)
        self.assertEqual(store.doc_hash(again),store.doc_hash(materialized))
        self.assertTrue(changes)
        self.assertIn('> INT. MARKED ROOM',story.doc_text(materialized))
        self.assertTrue(any(child.get('marks')==[{'type':'bold'}] for child in materialized['content'][2]['content']))


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'),'isolated PG required')
class CorrectedImportHTTPTests(unittest.TestCase):
    request=core_fixture.WritingHTTPTests.request
    setUp=core_fixture.WritingHTTPTests.setUp
    tearDown=core_fixture.WritingHTTPTests.tearDown
    call=core_fixture.WritingHTTPTests.call
    ok=core_fixture.WritingHTTPTests.ok
    writing=core_fixture.WritingHTTPTests.writing
    error=core_fixture.WritingHTTPTests.error
    init=core_fixture.WritingHTTPTests.init
    save_doc=core_fixture.WritingHTTPTests.save_doc

    def import_corrected(self, raw, sections):
        code,payload,_=self.request(story.BASE+f'/episodes/{self.ep}/writing/imports',method='POST',raw=raw.encode(),
            headers={'X-Filename':'corrected.txt','X-Writing-Purpose':'script','Content-Type':'application/octet-stream','Idempotency-Key':uuid.uuid4().hex})
        self.assertEqual(code,200,payload)
        upload=payload['data']
        revised=self.writing('previews','POST',{'kind':'import','uploadPreviewId':upload['previewId'],'uploadHash':upload['uploadHash'],'sections':sections})
        ack=self.writing('previews/'+revised['previewId']+'/apply','POST',{'expectedPreviewVersion':1,'selection':{'actions':[{'actionId':'import_document'}]}})
        return self.writing('branches/'+ack['sourceRef']['id'])

    def promote(self, branch, *, whole=True, keys=None):
        ws=self.writing('workspace')
        body={'kind':'promotion','sourceRef':{'kind':'branch','id':branch['branchId']},'expectedSourceHash':branch['docHash'],'targetDocHash':ws['docHash']}
        body.update({'whole':True} if whole else {'sceneKeys':keys})
        return self.writing('previews','POST',body)

    def apply(self, preview, **kwargs):
        return self.writing('previews/'+preview['previewId']+'/apply','POST',{'expectedPreviewVersion':1,
            'selection':{'actions':[{'actionId':a['actionId']} for a in preview['allowedActions']]}},**kwargs)

    def test_merged_corrected_import_save_compare_whole_adoption_retains_prose_and_identity(self):
        self.init()
        raw='Scene 01: Repeat\nFirst.\nScene 01: Repeat\nSecond.\n'
        branch=self.import_corrected(raw,[{'sectionId':'merged','title':'Authored merged scene','start':0,'end':len(raw),'included':True}])
        original=copy.deepcopy(branch['doc']);key=branch['structure']['scenes'][0]['sceneKey']
        version=self.writing('versions','POST',{'name':'Original corrected import','sourceRef':{'kind':'branch','id':branch['branchId']},'expectedSourceHash':branch['docHash'],'share':True})
        edited=copy.deepcopy(branch['doc']);edited['content'][1]['content'][0]['text']='First, edited.'
        saved=self.writing('branches/'+branch['branchId'],'PUT',{'baseVersion':branch['version'],'clientMutationId':'save-after-import','doc':edited,'structure':branch['structure']})
        self.assertEqual(len(saved['structure']['scenes']),1)
        self.assertEqual(saved['structure']['scenes'][0]['title'],'Authored merged scene')
        self.assertEqual(saved['structure']['scenes'][0]['sceneKey'],key)
        self.assertIn('Scene 01: Repeat',story.doc_text(saved['doc']))
        compared=self.writing('compare','POST',{'leftRef':{'kind':'version','id':version['versionId']},'rightRef':{'kind':'branch','id':branch['branchId']},
            'expectedHashes':{'left':version['snapshot']['docHash'],'right':saved['docHash']}})
        self.assertEqual([s['sceneKey'] for s in compared['scenes']],[key])
        self.assertEqual(compared['scenes'][0]['state'],'modified')
        preview=self.promote(saved)
        self.assertTrue(preview['proposedChanges']['materializationChanges'])
        self.assertTrue(any('quotes original Scene lines' in warning for warning in preview['warnings']))
        self.apply(preview,key='adopt-corrected')
        current=self.writing('workspace')
        self.assertEqual(len(current['structure']['scenes']),1)
        self.assertEqual(current['structure']['scenes'][0]['sceneKey'],key)
        self.assertEqual(current['structure']['scenes'][0]['title'],'Authored merged scene')
        legacy=self.ok(f'/episodes/{self.ep}')['scenes']
        self.assertEqual(len(legacy),1)
        self.assertIn('Authored merged scene',legacy[0]['title'])
        self.assertEqual(story.doc_text(self.writing('versions/'+version['versionId'])['snapshot']['doc']),story.doc_text(original))
        self.assertEqual(self.writing('branches/'+branch['branchId'])['doc'],saved['doc'])
        self.assertEqual(story.doc_text(current['doc']).count('> Scene 01: Repeat'),2)
        self.assertEqual(current['structure']['scenes'][0]['authoredOrigin']['docHash'],branch['docHash'])
        export=self.writing('exports','POST',{'sourceRef':{'kind':'version','id':version['versionId']},'expectedHash':version['snapshot']['docHash'],'sceneKeys':[key],'format':'txt'})
        code,content,_=self.request(story.BASE+f'/episodes/{self.ep}/writing/'+export['contentPath'])
        self.assertEqual(code,200);self.assertEqual(content.decode('utf8').count('Scene 01: Repeat'),2)
        restored=self.writing('previews','POST',{'kind':'promotion','sourceRef':{'kind':'version','id':version['versionId']},'expectedSourceHash':version['snapshot']['docHash'],
            'targetDocHash':current['docHash'],'whole':True})
        self.apply(restored);current=self.writing('workspace')
        self.assertEqual(current['structure']['scenes'][0]['sceneKey'],key)
        self.assertEqual(len(self.ok(f'/episodes/{self.ep}')['scenes']),1)
        self.assertNotIn('First, edited.',story.doc_text(current['doc']))
        self.assertEqual(self.writing('branches/'+branch['branchId'])['doc'],saved['doc'])
        # Further mainline block saves retain the authored partition and title.
        edited=copy.deepcopy(current['doc']);edited['content'][2]['content'][0]['text']='First, edited again.'
        self.save_doc(edited)
        self.assertEqual(self.writing('workspace')['structure']['scenes'][0]['sceneKey'],key)

    def test_split_corrected_duplicate_titles_selected_and_whole_adoption(self):
        self.init();self.save_doc(core_fixture.document('Scene 01: Existing','Untouched.'))
        raw='Scene 01: Repeat\nFirst.\nSecond.\nTail.\n';split=raw.index('Second.')
        branch=self.import_corrected(raw,[{'sectionId':'first','title':'Same title','start':0,'end':split,'included':True},
            {'sectionId':'second','title':'Same title','start':split,'end':len(raw),'included':True}])
        keys=[s['sceneKey'] for s in branch['structure']['scenes']]
        self.assertNotEqual(keys[0],keys[1])
        doc=copy.deepcopy(branch['doc']);doc['content'][2]['content'][0]['text']='Second, edited.'
        branch=self.writing('branches/'+branch['branchId'],'PUT',{'baseVersion':1,'clientMutationId':'edit-second','doc':doc,'structure':branch['structure']})
        self.assertEqual([s['sceneKey'] for s in branch['structure']['scenes']],keys)
        selected=self.promote(branch,whole=False,keys=[keys[1]])
        self.apply(selected)
        ws=self.writing('workspace');text=story.doc_text(ws['doc'])
        self.assertIn('Untouched.',text);self.assertIn('Second, edited.',text);self.assertNotIn('First.',text)
        self.assertEqual(ws['structure']['scenes'][-1]['sceneKey'],keys[1])
        self.assertEqual(len(self.ok(f'/episodes/{self.ep}')['scenes']),2)
        self.apply(self.promote(branch))
        ws=self.writing('workspace')
        self.assertEqual([s['sceneKey'] for s in ws['structure']['scenes']],keys)
        self.assertEqual([s['title'] for s in ws['structure']['scenes']],['Same title','Same title'])
        self.assertEqual(len(self.ok(f'/episodes/{self.ep}')['scenes']),2)
        self.assertNotIn('Untouched.',story.doc_text(ws['doc']))
        # A selected aligned adoption must retain its key, not manufacture a new identity.
        doc=copy.deepcopy(branch['doc']);doc['content'][2]['content'][0]['text']='Second, selected update.'
        branch=self.writing('branches/'+branch['branchId'],'PUT',{'baseVersion':branch['version'],'clientMutationId':'edit-aligned','doc':doc,'structure':branch['structure']})
        self.apply(self.promote(branch,whole=False,keys=[keys[1]]))
        self.assertEqual([s['sceneKey'] for s in self.writing('workspace')['structure']['scenes']],keys)
        self.assertIn('Second, selected update.',story.doc_text(self.writing('workspace')['doc']))

    def test_same_document_structure_and_composition_changes_invalidate_frozen_previews(self):
        self.init()
        source=self.writing('sources/idea','PUT',{'baseVersion':0,'clientMutationId':'create-idea','doc':core_fixture.document('A keeper finds a lamp.'),'structure':{},'composition':{}})
        def adaptation(saved):
            return self.writing('previews','POST',{'kind':'adaptation','sourceRef':{'kind':'source','mode':'idea'},'expectedSourceHash':saved['docHash'],'targetDocHash':self.writing('workspace')['docHash']})
        preview=adaptation(source)
        source=self.writing('sources/idea','PUT',{'baseVersion':source['version'],'clientMutationId':'composition-only','doc':source['doc'],'structure':{},'composition':{'mediumLens':'cinema','genreLens':'suspense'}})
        self.assertEqual(preview['sourceFingerprints'][0]['docHash'],source['docHash'])
        self.assertTrue(self.writing('previews/'+preview['previewId'])['stale'])
        self.error('previews/'+preview['previewId']+'/apply','POST',{'expectedPreviewVersion':1,'selection':{'actions':[{'actionId':'whole'}]}},409)
        preview=adaptation(source)
        source=self.writing('sources/idea','PUT',{'baseVersion':source['version'],'clientMutationId':'structure-only','doc':source['doc'],
            'structure':{'sections':[{'key':'section','title':'Authored source section','blockBids':[structure.bid(source['doc']['content'][0])]}]},'composition':source['composition']})
        self.assertTrue(self.writing('previews/'+preview['previewId'])['stale'])
        self.error('previews/'+preview['previewId']+'/apply','POST',{'expectedPreviewVersion':1,'selection':{'actions':[{'actionId':'whole'}]}},409)

    def test_same_document_branch_layout_and_composition_changes_invalidate_promotion(self):
        self.init()
        raw='Scene 01: Repeat\nFirst.\n'
        branch=self.import_corrected(raw,[{'sectionId':'one','title':'Title A','start':0,'end':len(raw),'included':True}])
        preview=self.promote(branch);before=self.writing('workspace')['docHash']
        version=self.writing('versions','POST',{'name':'Before title correction','sourceRef':{'kind':'branch','id':branch['branchId']},'expectedSourceHash':branch['docHash'],'share':True})
        changed=copy.deepcopy(branch['structure']);changed['scenes'][0]['title']='Title B'
        branch=self.writing('branches/'+branch['branchId'],'PUT',{'baseVersion':1,'clientMutationId':'layout-only','doc':branch['doc'],'structure':changed})
        self.assertEqual(branch['docHash'],preview['sourceFingerprints'][0]['docHash'])
        self.assertEqual(branch['structure']['scenes'][0]['title'],'Title B')
        compared=self.writing('compare','POST',{'leftRef':{'kind':'version','id':version['versionId']},'rightRef':{'kind':'branch','id':branch['branchId']},
            'expectedHashes':{'left':version['snapshot']['docHash'],'right':branch['docHash']}})
        self.assertFalse(compared['equal']);self.assertEqual(compared['scenes'][0]['state'],'modified')
        self.assertTrue(self.writing('previews/'+preview['previewId'])['stale'])
        self.error('previews/'+preview['previewId']+'/apply','POST',{'expectedPreviewVersion':1,'selection':{'actions':[{'actionId':'whole'}]}},409)
        self.assertEqual(self.writing('workspace')['docHash'],before)
        preview=self.promote(branch)
        branch=self.writing('branches/'+branch['branchId'],'PUT',{'baseVersion':branch['version'],'clientMutationId':'branch-composition-only','doc':branch['doc'],
            'structure':branch['structure'],'composition':{'mediumLens':'cinema','genreLens':'general'}})
        self.assertEqual(branch['docHash'],preview['sourceFingerprints'][0]['docHash'])
        self.assertTrue(self.writing('previews/'+preview['previewId'])['stale'])
        self.error('previews/'+preview['previewId']+'/apply','POST',{'expectedPreviewVersion':1,'selection':{'actions':[{'actionId':'whole'}]}},409)

    def test_corrected_import_stale_branch_save_and_locked_adoption_are_atomic(self):
        self.init();self.save_doc(core_fixture.document('Scene 01: Current','Current text.'))
        raw='Scene 01: Repeat\nFirst.\nScene 01: Repeat\nSecond.\n'
        branch=self.import_corrected(raw,[{'sectionId':'merged','title':'Corrected','start':0,'end':len(raw),'included':True}])
        preview=self.promote(branch);ws=self.writing('workspace');versions_before=len(ws['versions']['items'])
        original_locks=repo.tab_locks
        with patch.object(repo,'tab_locks',lambda conn,slug,key:original_locks(conn,slug,key)|{structure.bid(ws['doc']['content'][0]):'different-author'}):
            self.error('previews/'+preview['previewId']+'/apply','POST',{'expectedPreviewVersion':1,'selection':{'actions':[{'actionId':'whole'}]}},409)
        self.assertEqual(self.writing('workspace')['docHash'],ws['docHash'])
        self.assertEqual(len(self.writing('versions')['items']),versions_before)
        self.assertEqual(self.writing('previews/'+preview['previewId'])['status'],'pending')
        saved=self.writing('branches/'+branch['branchId'],'PUT',{'baseVersion':1,'clientMutationId':'new-save','doc':branch['doc'],'structure':branch['structure']})
        self.error('branches/'+branch['branchId'],'PUT',{'baseVersion':1,'clientMutationId':'stale-save','doc':branch['doc'],'structure':branch['structure']},409)
        self.assertEqual(self.writing('branches/'+branch['branchId'])['version'],saved['version'])
        self.assertTrue(self.writing('previews/'+preview['previewId'])['stale'])


if __name__=='__main__': unittest.main()
