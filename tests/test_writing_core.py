"""Behavioral SPEC16 core tests: real PG transactions and authenticated HTTP."""
import copy
import json
import os
import threading
import time
import unittest
import uuid
from unittest.mock import patch
from project_docs import writing_store as store, writing_structure as structure, repository as repo, service, story_openapi as story
import test_story_openapi as fixtures


def document(*lines):
    return {'type':'doc','content':[{'type':'heading' if text.startswith('Scene ') else 'paragraph',
        'attrs':{'bid':'b_'+uuid.uuid4().hex,**({'level':2} if text.startswith('Scene ') else {})},
        **({'content':[{'type':'text','text':text}]} if text else {})} for text in lines]}


class StructureTests(unittest.TestCase):
    def test_stable_bid_exact_and_duplicate_uncertainty(self):
        doc=store.checked_doc(document('Scene 01: Same','Repeat','Scene 02: Same','Repeat'))
        initial=structure.reconcile_structure(doc,{})
        changed=copy.deepcopy(doc);changed['content'][1]['content'][0]['text']='Changed'
        result=structure.reconcile_structure(changed,initial)
        self.assertEqual(initial['scenes'][0]['sceneKey'],result['scenes'][0]['sceneKey'])
        self.assertEqual(initial['scenes'][0]['beats'][0]['beatKey'],result['scenes'][0]['beats'][0]['beatKey'])
        rewritten=store.checked_doc(document('Scene 01: Same','Repeat','Scene 02: Same','Repeat'))
        result=structure.reconcile_structure(rewritten,initial)
        self.assertEqual(result['scenes'][0]['beats'][0]['mapping'],'unresolved')
        self.assertNotEqual(result['scenes'][0]['beats'][0]['beatKey'],initial['scenes'][0]['beats'][0]['beatKey'])
        unique=store.checked_doc(document('Scene 01: One','Unique'))
        a=structure.reconcile_structure(unique,{})
        b=structure.reconcile_structure(store.checked_doc(document('Scene 01: One','Unique')),a)
        self.assertEqual(a['scenes'][0]['sceneKey'],b['scenes'][0]['sceneKey'])


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'),'isolated PG required')
class WritingHTTPTests(unittest.TestCase):
    request=fixtures.StoryHTTPTests.request
    setUp=fixtures.StoryHTTPTests.setUp
    tearDown=fixtures.StoryHTTPTests.tearDown
    call=fixtures.StoryHTTPTests.call
    ok=fixtures.StoryHTTPTests.ok

    def writing(self,tail,method='GET',body=None,key=None):
        headers={'Idempotency-Key':key or uuid.uuid4().hex} if method=='POST' else None
        return self.ok(f'/episodes/{self.ep}/writing/'+tail,method,body,headers)

    def error(self,tail,method,body,status,key=None):
        code,data=self.call(f'/episodes/{self.ep}/writing/'+tail,method,body,{'Idempotency-Key':key or uuid.uuid4().hex})
        self.assertEqual(code,status,data)
        return data

    def init(self):
        workspace=self.writing('workspace')
        self.writing('initialize','POST',{'expectedDocHash':workspace['docHash']})
        return self.writing('workspace')

    def save_doc(self,doc):
        current=self.writing('workspace');old={structure.bid(n):n for n in current['doc']['content']};new={structure.bid(n):n for n in doc['content']}
        ops=[{'op':'del','bid':k,'base':v} for k,v in old.items() if k not in new]
        ops += [{'op':'put','bid':k,'base':old.get(k),'node':n} for k,n in new.items() if old.get(k)!=n]
        ops.append({'op':'order','bids':list(new)})
        return self.writing('script/ops','POST',{'ops':ops,'clientMutationId':uuid.uuid4().hex,'session_id':'writing-test'})

    def test_early_save_reload_sources_and_mainline(self):
        workspace=self.writing('workspace');self.assertFalse(workspace['structure']['initialized'])
        self.assertIsNone(self.writing('sources/novel'))
        source={'baseVersion':0,'clientMutationId':'novel-save','doc':document('她心裡壓著一個秘密。','  Whitespace stays.  '),'structure':{},'composition':{}}
        saved=self.writing('sources/novel','PUT',source)
        self.assertEqual(saved['version'],1)
        self.assertEqual(self.writing('sources/novel')['doc'],saved['doc'])
        self.assertEqual(self.writing('sources/novel','PUT',source)['version'],1)
        self.error('sources/novel','PUT',source|{'composition':{'mediumLens':'cinema'}},409)
        self.init()
        ack=self.save_doc(document('Scene 01: Arrival','@CAST-01 opens the door.'))
        self.assertFalse(ack['conflicts'])
        reloaded=self.writing('workspace')
        self.assertEqual(reloaded['doc'],ack['doc'])
        self.assertEqual(reloaded['docHash'],ack['docHash'])
        self.assertIn('心裡',json.dumps(self.writing('sources/novel'),ensure_ascii=False))
        print('CHECKPOINT real PG/HTTP private novel PUT→GET and mainline block save→workspace reload hashes match; no inference called')

    def test_cas_receipts_concurrent_and_private_revocation(self):
        self.init()
        source={'baseVersion':0,'clientMutationId':'create','doc':document('Draft'),'structure':{},'composition':{}}
        saved=self.writing('sources/idea','PUT',source)
        barrier=threading.Barrier(2);results=[]
        def save(number):
            body=source|{'baseVersion':1,'clientMutationId':'concurrent-'+str(number),'doc':document('Draft '+str(number))}
            barrier.wait();results.append(self.call(f'/episodes/{self.ep}/writing/sources/idea','PUT',body)[0])
        threads=[threading.Thread(target=save,args=(i,)) for i in range(2)]
        for t in threads:t.start()
        for t in threads:t.join(15)
        self.assertEqual(sorted(results),[200,409])
        branch=self.writing('branches','POST',{'sourceRef':{'kind':'source','mode':'idea'},'name':'Private','expectedSourceHash':self.writing('sources/idea')['docHash']},key='private-branch')
        from project_assistant import store as assistant_store
        replay_body={'sourceRef':{'kind':'source','mode':'idea'},'name':'Private','expectedSourceHash':self.writing('sources/idea')['docHash']}
        assistant_store.set_member_enabled(self.conn,self.slug,self.actor,False,self.actor);self.conn.commit()
        self.error('branches','POST',replay_body,403,key='private-branch')
        self.error('branches/'+branch['branchId'],'GET',None,403)

    def test_immutable_snapshot_coalesced_revision_legacy_and_conflicts(self):
        self.init();self.save_doc(document('Scene 01: Arrival','First'))
        current=self.writing('workspace')
        snapshot=self.writing('versions','POST',{'name':'First','sourceRef':{'kind':'working'},'expectedSourceHash':current['docHash'],'share':True})
        doc=copy.deepcopy(current['doc']);node=doc['content'][-1];node['content']=[{'type':'text','text':'Second'}]
        ack=self.save_doc(doc)
        self.assertEqual(ack['revision'],current['revision'])  # real repository session coalescing
        self.assertNotEqual(ack['docHash'],current['docHash'])
        self.assertEqual(self.writing('versions/'+snapshot['versionId'])['snapshot'],snapshot['snapshot'])
        stale={'ops':[{'op':'put','bid':structure.bid(node),'base':current['doc']['content'][-1],'node':node}], 'clientMutationId':'stale','session_id':'other'}
        result=self.writing('script/ops','POST',stale)
        self.assertEqual(result['applied'],0);self.assertTrue(result['conflicts'])
        # Legacy entire-script replacement changes bids; the next writing read must reconcile, not trust revision.
        self.ok(f'/episodes/{self.ep}/script','PUT',{'scriptContent':'Scene 01: Arrival\nLegacy replacement'})
        reloaded=self.writing('workspace')
        self.assertTrue(reloaded['structure']['stale'])
        self.assertEqual(reloaded['docHash'],reloaded['structure']['docHash'])
        self.assertEqual(self.writing('versions/'+snapshot['versionId'])['snapshot'],snapshot['snapshot'])

    def test_branch_adaptation_promotion_atomic_and_baseline(self):
        self.init();source=self.writing('sources/idea','PUT',{'baseVersion':0,'clientMutationId':'idea','doc':document('A keeper finds a brass dial.'),'structure':{},'composition':{}})
        current=self.writing('workspace')
        preview=self.writing('previews','POST',{'kind':'adaptation','sourceRef':{'kind':'source','mode':'idea'},'expectedSourceHash':source['docHash'],'targetDocHash':current['docHash'],'targetScenes':2})
        self.assertEqual(self.writing('workspace')['docHash'],current['docHash'])
        candidate=self.writing('branches/'+preview['candidateBranchId'])
        self.assertEqual(candidate['version'],1)
        result=self.writing('previews/'+preview['previewId']+'/apply','POST',{'expectedPreviewVersion':1,'selection':{'actions':[{'actionId':'whole','kind':'adopt_whole'}]}},key='adopt')
        self.assertEqual(self.writing('workspace')['docHash'],result['docHash'])
        replay=self.writing('previews/'+preview['previewId']+'/apply','POST',{'expectedPreviewVersion':1,'selection':{'actions':[{'actionId':'whole','kind':'adopt_whole'}]}},key='adopt')
        self.assertEqual(replay,result)
        self.assertTrue(self.writing('versions/'+result['beforeVersionId'])['snapshot'])
        self.ok(f'/episodes/{self.ep}/asset-extractions','POST',{})
        baseline=self.writing('workspace')['baseline'];self.assertTrue(baseline['retained'])
        saved=self.writing('versions/'+baseline['versionId']);self.assertTrue(saved['locked'])
        self.error('versions/'+saved['versionId'],'PATCH',{'baseCatalogVersion':1,'clientMutationId':'unlock','locked':False},409)
        # Confirmation snapshot matches actual extraction and legacy confirmedHash.
        ep=story.episode(self.conn,self.ep)
        self.assertEqual(saved['snapshot']['scriptHash'],ep['confirmedHash'])
        self.ok(f'/episodes/{self.ep}/storyboards','POST',{})

    def test_structure_move_metadata_partial_promotion_and_undo(self):
        self.init();self.save_doc(document('Scene 01: A','Alpha','Scene 02: B','Beta'))
        ws=self.writing('workspace');keys=[s['sceneKey'] for s in ws['structure']['scenes']]
        metadata=self.writing('structure/metadata','PATCH',{'baseVersion':ws['structure']['version'],'clientMutationId':'meta','scenePatches':[{'sceneKey':keys[0],'summary':'Summary'}]})
        self.assertEqual(self.writing('workspace')['docHash'],ws['docHash'])
        preview=self.writing('previews','POST',{'kind':'structure','targetDocHash':ws['docHash'],'structureVersion':metadata['version'],'operation':{'type':'move','sceneKey':keys[0],'afterSceneKey':keys[1]}})
        result=self.writing('previews/'+preview['previewId']+'/apply','POST',{'expectedPreviewVersion':1,'selection':{'actions':preview['allowedActions']}})
        self.assertEqual([s['sceneKey'] for s in result['structure']['scenes']],list(reversed(keys)))
        current=self.writing('workspace')
        restore=self.writing('previews','POST',{'kind':'structure','targetDocHash':current['docHash'],'structureVersion':current['structure']['version'],'operation':{'type':'restore','snapshotId':result['beforeVersionId']}})
        restored=self.writing('previews/'+restore['previewId']+'/apply','POST',{'expectedPreviewVersion':1,'selection':{'actions':restore['allowedActions']}})
        self.assertEqual([s['sceneKey'] for s in restored['structure']['scenes']],keys)
        branch=self.writing('branches','POST',{'sourceRef':{'kind':'working'},'name':'Alternate','expectedSourceHash':self.writing('workspace')['docHash']})
        altered=copy.deepcopy(branch['doc']);altered['content'][1]['content']=[{'type':'text','text':'New Alpha'}];altered['content'][3]['content']=[{'type':'text','text':'New Beta'}]
        branch=self.writing('branches/'+branch['branchId'],'PUT',{'baseVersion':1,'clientMutationId':'edit','doc':altered,'structure':branch['structure']})
        ws=self.writing('workspace')
        preview=self.writing('previews','POST',{'kind':'promotion','sourceRef':{'kind':'branch','id':branch['branchId']},'expectedSourceHash':branch['docHash'],'targetDocHash':ws['docHash'],'sceneKeys':[keys[0]]})
        applied=self.writing('previews/'+preview['previewId']+'/apply','POST',{'expectedPreviewVersion':1,'selection':{'actions':[{k:a[k] for k in ('actionId','kind')} for a in preview['allowedActions']]}})
        text=story.doc_text(self.writing('workspace')['doc']);self.assertIn('New Alpha',text);self.assertNotIn('New Beta',text)
        self.assertTrue(applied['beforeVersionId'])

    def test_viewer_read_post_exceptions_and_private_owner(self):
        self.init();ws=self.writing('workspace')
        branch=self.writing('branches','POST',{'sourceRef':{'kind':'working'},'name':'Private','expectedSourceHash':ws['docHash']})
        other=str(uuid.uuid4());repo.upsert_member(self.conn,other,'Other admin','admin');self.conn.commit()
        with patch.dict(os.environ,{'OPENBENCH_TOKENS':json.dumps({self.member_token:other})}):
            self.error('branches/'+branch['branchId'],'GET',None,404)
        repo.upsert_member(self.conn,self.actor,'Viewer','viewer');self.conn.commit()
        result=self.writing('compare','POST',{'leftRef':{'kind':'working'},'rightRef':{'kind':'working'},'expectedHashes':{'left':ws['docHash'],'right':ws['docHash']}})
        self.assertTrue(result['equal'])
        self.error('initialize','POST',{'expectedDocHash':ws['docHash']},403)
        self.error('previews','POST',{'kind':'structure'},403)
        self.assertEqual(self.call(f'/episodes/{self.ep}/asset-extractions','POST',{})[0],409)
        with self.conn.cursor() as cur:cur.execute('DELETE FROM projectops.member WHERE actor_id=%s',(other,))
        self.conn.commit()


if __name__=='__main__': unittest.main()
