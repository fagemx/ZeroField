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

    def test_typed_private_checkpoint_cannot_be_forged_or_client_written(self):
        self.init()
        saved=self.writing('sources/idea','PUT',{'baseVersion':0,'clientMutationId':'source','doc':document('Before'),'structure':{},'composition':{}})
        scope=store.scope_for(self.conn,service.Identity(self.actor,'Test','admin'),self.ep,write=True)
        new_doc=store.checked_doc(document('After'),self.slug)
        changes={'doc':new_doc,'docHash':store.doc_hash(new_doc),'beforeCheckpoint':{'doc':saved['doc'],'structure':saved['structure']}}
        result=store.cas_record(self.conn,scope,'writing_source',saved['sourceId'],base_version=1,changes=changes)
        self.conn.commit()
        self.assertEqual(result['beforeCheckpoint']['ownerId'],self.actor)
        self.assertEqual(result['beforeCheckpoint']['episodeId'],self.ep)
        self.assertEqual(result['beforeCheckpoint']['resourceKind'],'writing_source')
        self.error('sources/idea','PUT',{'baseVersion':2,'clientMutationId':'forged','doc':new_doc,'structure':{},'composition':{},'beforeCheckpoint':{}},422)
        forged=copy.deepcopy(changes);forged['beforeCheckpoint']['doc']=document('Unrelated private evidence')
        with self.assertRaises(story.StoryError): store.cas_record(self.conn,scope,'writing_source',saved['sourceId'],base_version=2,changes=forged)
        self.conn.rollback()
        self.assertEqual(self.writing('sources/idea')['version'],2)
        self.assertNotIn('beforeCheckpoint',self.writing('workspace')['sources']['items'][0])

    def test_expired_receipt_never_silently_rebases(self):
        self.init()
        saved=self.writing('sources/idea','PUT',{'baseVersion':0,'clientMutationId':'create','doc':document('Before'),'structure':{},'composition':{}})
        body={'baseVersion':1,'clientMutationId':'edit','doc':document('After'),'structure':{},'composition':{}}
        ack=self.writing('sources/idea','PUT',body);self.assertEqual(ack['version'],2)
        with self.conn.cursor() as cur:
            cur.execute("UPDATE projectops.story_record SET data=jsonb_set(data,'{expiresAt}','0') WHERE kind='writing_receipt' AND project_slug=%s",(self.slug,))
        self.conn.commit()
        self.error('sources/idea','PUT',body,409)
        self.assertEqual(self.writing('sources/idea')['version'],2)
        self.writing('sources/idea','PUT',body|{'baseVersion':2,'clientMutationId':'explicit-new-action'})
        with self.conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM projectops.story_record WHERE kind='writing_receipt' AND project_slug=%s AND (data->>'expiresAt')::double precision<%s",(self.slug,time.time()))
            self.assertEqual(cur.fetchone()[0],0)

    def test_explicit_other_episode_references_are_scoped_and_computation_is_unlocked(self):
        from project_docs import writing_service, writing_versions
        self.init();ws=self.writing('workspace')
        second=self.ok(f'/projects/pj_{self.slug}/episodes','POST',{'title':'Second'})
        source={'baseVersion':0,'clientMutationId':'second-source','doc':document('Second private novel'),'structure':{},'composition':{}}
        self.ok(f'/episodes/{second["episodeId"]}/writing/sources/novel','PUT',source)
        scope=store.scope_for(self.conn,service.Identity(self.actor,'Test','admin'),self.ep)
        writing_service.authorize_references(self.conn,scope,{'scope':[{'episodeId':second['episodeId'],'sourceRef':{'kind':'source','mode':'novel'}}]})
        other=self.ok('/projects','POST',{'title':'Foreign'});self.extra_projects.append(other['slug'])
        with self.assertRaises(story.StoryError):
            writing_service.authorize_references(self.conn,scope,{'scope':[{'episodeId':f'ep_{other["slug"]}_01','sourceRef':{'kind':'working'}}]})
        self.conn.rollback()
        original=writing_versions.compare
        def unlocked(conn,scope,body):
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='advisory'")
                self.assertEqual(cur.fetchone()[0],0)
            return original(conn,scope,body)
        with patch.object(writing_versions,'compare',unlocked):
            self.assertTrue(self.writing('compare','POST',{'leftRef':{'kind':'working'},'rightRef':{'kind':'working'},'expectedHashes':{'left':ws['docHash'],'right':ws['docHash']}})['equal'])

    def test_limits_settings_and_historical_baseline_are_not_fabricated(self):
        self.init();self.save_doc(document('Scene 01: First','Before'))
        self.ok(f'/episodes/{self.ep}/asset-extractions','POST',{})
        first=self.writing('workspace')['baseline']['versionId']
        self.save_doc(document('Scene 01: First','After'))
        current=self.writing('workspace');self.assertEqual(current['baseline']['versionId'],first)
        scope=store.scope_for(self.conn,service.Identity(self.actor,'Test','admin'),self.ep,write=True)
        from project_docs import writing_versions
        with self.assertRaises(story.StoryError): writing_versions.confirm_baseline(self.conn,scope,expected_doc_hash=current['docHash'])
        self.conn.rollback()
        self.assertEqual(self.writing('workspace')['baseline']['versionId'],first)
        self.ok(f'/episodes/{self.ep}/asset-extractions','POST',{})
        second=self.writing('workspace')['baseline']['versionId'];self.assertNotEqual(first,second)
        self.error('versions/'+first,'PATCH',{'baseCatalogVersion':1,'clientMutationId':'historic-unlock','locked':False},409)
        self.error('sources/idea','PUT',{'baseVersion':0,'clientMutationId':'too-long','doc':document('x'*500001),'structure':{},'composition':{}},413)
        self.assertIsNone(self.writing('sources/idea'))

    def test_scopes_locked_branches_and_catalog_snapshot_privacy(self):
        self.init();source=self.writing('sources/novel','PUT',{'baseVersion':0,'clientMutationId':'private-original','doc':document('Private original material'),'structure':{},'composition':{'mediumLens':'cinema','genreLens':'general','choiceTrace':{'focus':'restraint','extraCondition':'private choice'}}})
        self.error('versions','POST',{'name':'Not shared','sourceRef':{'kind':'source','mode':'novel'},'expectedSourceHash':source['docHash'],'share':True},422)
        ws=self.writing('workspace');branch=self.writing('branches','POST',{'sourceRef':{'kind':'working'},'name':'Private branch','expectedSourceHash':ws['docHash']})
        locked=self.writing('branches/'+branch['branchId'],'PATCH',{'baseVersion':1,'clientMutationId':'lock','locked':True})
        self.error('branches/'+branch['branchId'],'PUT',{'baseVersion':locked['version'],'clientMutationId':'overwrite','doc':document('Forbidden'),'structure':{}},409)
        version=self.writing('versions','POST',{'name':'Shared selected script','sourceRef':{'kind':'branch','id':branch['branchId']},'expectedSourceHash':branch['docHash'],'share':True})
        self.assertNotIn('Private original material',json.dumps(version))
        self.assertNotIn('private choice',json.dumps(version))
        self.assertNotIn('snapshot',self.writing('versions')['items'][0])
        other=self.ok('/projects','POST',{'title':'Other production'});self.extra_projects.append(other['slug'])
        other_ep=f'ep_{other["slug"]}_01'
        self.assertEqual(self.call(f'/episodes/{other_ep}/writing/branches/{branch["branchId"]}')[0],404)
        self.assertEqual(self.call(f'/episodes/{other_ep}/writing/versions/{version["versionId"]}')[0],404)

    def test_browser_cookie_csrf_is_checked_before_replay(self):
        self.init();ws=self.writing('workspace')
        body={'sourceRef':{'kind':'working'},'name':'Cookie branch','expectedSourceHash':ws['docHash']}
        code,_,headers=self.request('/login',method='POST',raw=('token='+self.member_token).encode(),authenticated=False,headers={'Content-Type':'application/x-www-form-urlencoded'})
        self.assertEqual(code,303)
        cookie=headers['Set-Cookie'].split(';')[0]
        path=story.BASE+f'/episodes/{self.ep}/writing/branches'
        headers={'Cookie':cookie,'Idempotency-Key':'cookie-create'}
        code,payload,_=self.request(path,method='POST',data=body,authenticated=False,headers=headers)
        self.assertEqual(code,200,payload)
        headers['Origin']='https://foreign.invalid'
        self.assertEqual(self.request(path,method='POST',data=body,authenticated=False,headers=headers)[0],403)

    def test_readonly_gets_do_not_initialize_and_blank_saves_are_real(self):
        for tail in ('workspace','structure','sources/idea','branches','versions'):
            self.writing(tail)
        with self.conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM projectops.story_record WHERE project_slug=%s AND kind LIKE 'writing_%%'",(self.slug,))
            self.assertEqual(cur.fetchone()[0],0)
        self.init()
        ack=self.save_doc(document(''))
        self.assertEqual(story.doc_text(ack['doc']),'')
        self.assertEqual(self.writing('workspace')['docHash'],ack['docHash'])
        self.assertEqual(self.call(f'/episodes/{self.ep}/asset-extractions','POST',{})[0],422)

    def test_block_mutation_identity_and_concurrent_conflicts(self):
        self.init();self.save_doc(document('Scene 01: Room','Alpha','Beta'))
        ws=self.writing('workspace');base=ws['doc']['content'][1];node=copy.deepcopy(base);node['content'][0]['text']='Updated'
        body={'ops':[{'op':'put','bid':structure.bid(base),'base':base,'node':node}],'clientMutationId':'same-text-action','session_id':'coalesce'}
        first=self.writing('script/ops','POST',body)
        self.assertEqual(self.writing('script/ops','POST',body),first)  # distinct POST keys, same text mutation identity
        altered=copy.deepcopy(body);altered['ops'][0]['node']['content'][0]['text']='Different body'
        self.error('script/ops','POST',altered,409)
        base=self.writing('workspace')['doc']['content'][2]
        barrier=threading.Barrier(2);responses=[]
        def save(number):
            node=copy.deepcopy(base);node['content'][0]['text']='Concurrent '+str(number)
            request={'ops':[{'op':'put','bid':structure.bid(base),'base':base,'node':node}],'clientMutationId':str(number),'session_id':'parallel'}
            barrier.wait();responses.append(self.call(f'/episodes/{self.ep}/writing/script/ops','POST',request,{'Idempotency-Key':'parallel-'+str(number)}))
        threads=[threading.Thread(target=save,args=(i,)) for i in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(15)
        self.assertEqual([r[0] for r in responses],[200,200])
        self.assertEqual(sorted(r[1]['data']['applied'] for r in responses),[0,1])
        self.assertEqual(sum(bool(r[1]['data']['conflicts']) for r in responses),1)

    def test_stale_preview_and_locks_do_not_partially_adopt(self):
        self.init();self.save_doc(document('Scene 01: A','Alpha','Scene 02: B','Beta'))
        ws=self.writing('workspace');branch=self.writing('branches','POST',{'sourceRef':{'kind':'working'},'name':'Alternate','expectedSourceHash':ws['docHash']})
        edited=copy.deepcopy(branch['doc']);edited['content'][1]['content'][0]['text']='Alternate Alpha';edited['content'][3]['content'][0]['text']='Alternate Beta'
        branch=self.writing('branches/'+branch['branchId'],'PUT',{'baseVersion':1,'clientMutationId':'branch-save','doc':edited,'structure':branch['structure']})
        build={'kind':'promotion','sourceRef':{'kind':'branch','id':branch['branchId']},'expectedSourceHash':branch['docHash'],'targetDocHash':ws['docHash'],'whole':True}
        preview=self.writing('previews','POST',build)
        body={'expectedPreviewVersion':1,'selection':{'actions':[{'actionId':'whole','kind':'adopt_whole'}]}}
        from project_docs import writing_service
        original=repo.tab_locks
        def locked(conn,slug,key):
            return original(conn,slug,key)|{structure.bid(ws['doc']['content'][3]):'another-writer'}
        before_count=len(self.writing('versions')['items'])
        with patch.object(repo,'tab_locks',locked): self.error('previews/'+preview['previewId']+'/apply','POST',body,409)
        self.assertEqual(self.writing('workspace')['docHash'],ws['docHash'])
        self.assertEqual(len(self.writing('versions')['items']),before_count)
        self.assertEqual(self.writing('previews/'+preview['previewId'])['status'],'pending')
        self.ok(f'/episodes/{self.ep}/settings','PUT',{'aspectRatio':'9:16'})
        self.error('previews/'+preview['previewId']+'/apply','POST',body,409)
        self.assertTrue(self.writing('previews/'+preview['previewId'])['stale'])
        # Even direct immutable helper access cannot mutate snapshot payloads.
        version=self.writing('versions','POST',{'name':'Snapshot','sourceRef':{'kind':'working'},'expectedSourceHash':ws['docHash'],'share':True})
        scope=store.scope_for(self.conn,service.Identity(self.actor,'Test','admin'),self.ep,write=True)
        with self.assertRaises(story.StoryError): store.cas_record(self.conn,scope,'writing_version',version['versionId'],base_version=1,changes={'snapshot':{}})
        self.conn.rollback()

    def test_candidate_survives_preview_expiry_and_source_composition_stales(self):
        self.init();source=self.writing('sources/novel','PUT',{'baseVersion':0,'clientMutationId':'novel','doc':document('A keeper enters the station.'),'structure':{},'composition':{}})
        ws=self.writing('workspace')
        preview=self.writing('previews','POST',{'kind':'adaptation','sourceRef':{'kind':'source','mode':'novel'},'expectedSourceHash':source['docHash'],'targetDocHash':ws['docHash']})
        self.writing('sources/novel','PUT',{'baseVersion':1,'clientMutationId':'lens','doc':source['doc'],'structure':{},'composition':{'mediumLens':'cinema','genreLens':'suspense'}})
        self.assertTrue(self.writing('previews/'+preview['previewId'])['stale'])
        self.error('previews/'+preview['previewId']+'/apply','POST',{'expectedPreviewVersion':1,'selection':{'actions':[{'actionId':'whole','kind':'adopt_whole'}]}},409)
        with self.conn.cursor() as cur:
            cur.execute("UPDATE projectops.story_record SET data=jsonb_set(data,'{expiresAt}','0') WHERE id=%s",(preview['previewId'],))
        self.conn.commit()
        self.error('previews/'+preview['previewId'],'GET',None,409)
        self.assertEqual(self.writing('branches/'+preview['candidateBranchId'])['version'],1)

    def test_structure_add_split_merge_delete_and_legacy_reorder(self):
        self.init();self.save_doc(document('Scene 01: A','First','Second','Scene 02: B','Third'))
        def operation(value):
            ws=self.writing('workspace')
            preview=self.writing('previews','POST',{'kind':'structure','targetDocHash':ws['docHash'],'structureVersion':ws['structure']['version'],'operation':value})
            return self.writing('previews/'+preview['previewId']+'/apply','POST',{'expectedPreviewVersion':1,'selection':{'actions':[{k:a[k] for k in ('actionId','kind')} for a in preview['allowedActions']]}})
        ws=self.writing('workspace');first=ws['structure']['scenes'][0]
        result=operation({'type':'split','sceneKey':first['sceneKey'],'atBid':first['blockBids'][1],'title':'New half'})
        self.assertFalse(self.writing('workspace')['structure']['stale'])
        self.assertEqual(result['structure']['scenes'][0]['sceneKey'],first['sceneKey'])
        split_key=result['structure']['scenes'][1]['sceneKey']
        result=operation({'type':'merge','sceneKeys':[first['sceneKey'],split_key],'keepSceneKey':first['sceneKey']})
        self.assertEqual(result['structure']['scenes'][0]['sceneKey'],first['sceneKey'])
        result=operation({'type':'add','afterSceneKey':first['sceneKey'],'title':'New scene'})
        new_key=result['structure']['scenes'][1]['sceneKey']
        self.assertFalse(self.writing('workspace')['structure']['stale'])
        result=operation({'type':'remove','sceneKey':new_key})
        self.assertTrue(any(t.get('sceneKey')==new_key for t in result['structure']['tombstones']))
        before=self.writing('workspace')['structure']['scenes'];old_keys=[s['sceneKey'] for s in before]
        ep=story.episode(self.conn,self.ep)
        items=list(reversed(story.scenes(self.conn,ep)))
        story.write_scenes(self.conn,service.Identity(self.actor,'Test','admin'),ep,items)
        self.conn.commit()
        after=self.writing('workspace')['structure']
        self.assertFalse(after['stale'])
        self.assertEqual([s['sceneKey'] for s in after['scenes']],list(reversed(old_keys)))

    def test_raw_binary_feature_slots_and_successful_null_replay(self):
        import types
        import sys
        from project_docs.writing_http import BinaryResponse
        observed=[]
        def files_dispatch(conn,scope,method,tail,body,query,*,raw=None,headers=None):
            observed.append((tail,raw,dict(headers or {})))
            self.assertNotIn('Authorization',headers or {})
            if tail=='imports':
                store.lock_project(conn,scope)
                return store.create_preview(conn,scope,'import',{'uploadHash':store.hash_value(list(raw)),'allowedActions':[],'sourceFingerprints':[],'targetFingerprints':[]})
            if tail=='exports':
                store.lock_project(conn,scope)
                identifier='wexp_'+uuid.uuid4().hex
                return store.insert_record(conn,scope,'writing_export',identifier,{'exportId':identifier,'sourceRef':body['sourceRef'],'expiresAt':time.time()+1800})
            if tail.endswith('/content'):
                return BinaryResponse(b'<html><body>&lt;script&gt;</body></html>','text/html; charset=utf-8',headers={'Content-Disposition':'inline; filename="safe.html"'})
            return store.UNHANDLED
        tools_calls=[]
        def tools_dispatch(*args,**kwargs): tools_calls.append(1);return None
        modules={'project_docs.writing_files':types.SimpleNamespace(dispatch=files_dispatch),'project_docs.writing_tools':types.SimpleNamespace(dispatch=tools_dispatch)}
        self.init();ws=self.writing('workspace')
        with patch.dict(sys.modules,modules):
            path=story.BASE+f'/episodes/{self.ep}/writing/imports'
            headers={'Content-Type':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','X-File-Name':'novel.docx','X-File-Purpose':'novel','Idempotency-Key':'raw-import'}
            code,payload,_=self.request(path,method='POST',raw=b'PK synthetic raw fixture',headers=headers)
            self.assertEqual(code,200,payload);self.assertTrue(payload['data']['previewId'])
            self.assertEqual(observed[0][1],b'PK synthetic raw fixture')
            self.assertEqual(self.request(path,method='POST',raw=b'PK synthetic raw fixture',headers=headers)[0],200)
            self.assertEqual(len(observed),1)
            self.assertEqual(self.request(path,method='POST',raw=b'changed',headers=headers)[0],409)
            repo.upsert_member(self.conn,self.actor,'Viewer','viewer');self.conn.commit()
            self.assertIsNone(self.writing('search','POST',{'query':'x'},key='null-search'))
            self.assertIsNone(self.writing('search','POST',{'query':'x'},key='null-search'))
            self.assertEqual(len(tools_calls),1)
            export=self.writing('exports','POST',{'sourceRef':{'kind':'working'},'expectedHash':ws['docHash'],'format':'print','include':{}},key='export')
            code,body,headers=self.request(story.BASE+f'/episodes/{self.ep}/writing/exports/{export["exportId"]}/content')
            self.assertEqual(code,200);self.assertIsInstance(body,bytes)
            self.assertEqual(headers['Cache-Control'],'private, no-store')
            self.assertIn("default-src 'none'",headers['Content-Security-Policy'])
            from project_assistant import store as assistant_store
            assistant_store.set_member_enabled(self.conn,self.slug,self.actor,False,self.actor);self.conn.commit()
            self.assertEqual(self.request(story.BASE+f'/episodes/{self.ep}/writing/exports/{export["exportId"]}/content')[0],403)

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
