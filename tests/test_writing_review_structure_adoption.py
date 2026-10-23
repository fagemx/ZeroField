"""N2: adopted/direct structural saves cannot leave persisted ordinal aliases."""
import copy
import os
import time
import unittest
from unittest.mock import patch
import uuid
import test_writing_core as core
import test_writing_review_structure as fixture
from project_docs import repository as repo, story_openapi as story, writing_store as store, writing_structure as structure


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'),'isolated PG required')
class AdoptionAssociationHTTPTests(unittest.TestCase):
    request=fixture.ReviewStructureHTTPTests.request
    setUp=fixture.ReviewStructureHTTPTests.setUp
    tearDown=fixture.ReviewStructureHTTPTests.tearDown
    call=fixture.ReviewStructureHTTPTests.call
    ok=fixture.ReviewStructureHTTPTests.ok
    writing=fixture.ReviewStructureHTTPTests.writing
    error=fixture.ReviewStructureHTTPTests.error
    init=fixture.ReviewStructureHTTPTests.init
    save_doc=fixture.ReviewStructureHTTPTests.save_doc
    prepare=fixture.ReviewStructureHTTPTests.prepare
    shots=fixture.ReviewStructureHTTPTests.shots
    assert_preserved=fixture.ReviewStructureHTTPTests.assert_preserved
    operation=fixture.ReviewStructureHTTPTests.operation

    def branch_without_b(self):
        ws=self.writing('workspace')
        branch=self.writing('branches','POST',{'sourceRef':{'kind':'working'},'name':'A/C','expectedSourceHash':ws['docHash']})
        doc=copy.deepcopy(branch['doc']);del doc['content'][2:4]
        return self.writing('branches/'+branch['branchId'],'PUT',{'baseVersion':branch['version'],
            'clientMutationId':uuid.uuid4().hex,'doc':doc,'structure':branch['structure']})

    def adoption(self,whole=True,apply=True):
        branch=self.branch_without_b();ws=self.writing('workspace')
        body={'kind':'promotion','sourceRef':{'kind':'branch','id':branch['branchId']},'expectedSourceHash':branch['docHash'],
            'targetDocHash':ws['docHash'],**({'whole':True} if whole else {'sceneKeys':[self.keys[1]]})}
        preview=self.writing('previews','POST',body)
        if not apply:return preview
        return self.writing('previews/'+preview['previewId']+'/apply','POST',{'expectedPreviewVersion':preview['version'],
            'selection':{'actions':[{'actionId':a['actionId']} for a in preview['allowedActions']]}})

    def assert_no_alias(self,b):
        active=self.ok('/episodes/'+self.ep+'/scenes')['items']
        # Assert raw persisted shot metadata too: a READ projection cannot conceal N2.
        meta=story.shot_meta(self.conn,b['shotId'])
        self.assertNotIn(meta.get('sceneId'),[s['sceneId'] for s in active])
        self.assert_preserved(b)
        self.assertEqual(next(s for s in self.writing('alignment')['items'] if s['shotId']==b['shotId'])['storyAlignment']['state'],'source_removed')

    def test_whole_adoption_detaches_removed_b_and_remaps_c(self):
        a,b,c=self.prepare();self.adoption()
        self.assert_no_alias(b)
        active=self.writing('structure')['scenes']
        self.assertEqual(self.shots()[c['shotId']]['sceneId'],active[1]['legacySceneId'])
        for shot in (a,b,c):self.assert_preserved(shot)

    def test_selected_adoption_removes_b_without_rebinding_its_shot_to_c(self):
        a,b,c=self.prepare();self.adoption(whole=False)
        self.assert_no_alias(b)
        self.assertEqual(self.shots()[c['shotId']]['sceneId'],self.writing('structure')['scenes'][1]['legacySceneId'])
        for shot in (a,b,c):self.assert_preserved(shot)

    def test_direct_writing_script_ops_scene_delete_detaches_persisted_b(self):
        a,b,c=self.prepare();doc=copy.deepcopy(self.writing('workspace')['doc']);del doc['content'][2:4]
        self.save_doc(doc);self.assert_no_alias(b)
        self.assertEqual(self.shots()[c['shotId']]['sceneId'],self.writing('structure')['scenes'][1]['legacySceneId'])
        for shot in (a,b,c):self.assert_preserved(shot)

    def generic_ops(self,doc,key='director-brief',session='generic',expected=200):
        tab=repo.get_tab(self.conn,self.slug,key)
        old={structure.bid(n):n for n in tab['doc']['content']};new={structure.bid(n):n for n in doc['content']}
        ops=[{'op':'del','bid':k,'base':n} for k,n in old.items() if k not in new]
        ops += [{'op':'put','bid':k,'base':old.get(k),'node':n} for k,n in new.items() if old.get(k)!=n]
        ops += [{'op':'order','bids':list(new)}]
        code,result,_=self.request('/projects/api/'+self.slug+'/tabs/'+key+'/ops',method='POST',
            data={'ops':ops,'session_id':session,'atomic':True})
        self.assertEqual(code,expected,result)
        return result

    def test_generic_docsurface_ops_and_history_restore_share_the_atomic_seam(self):
        a,b,c=self.prepare();original=self.writing('workspace')['doc'];doc=copy.deepcopy(original);del doc['content'][2:4]
        saved=self.generic_ops(doc);self.assert_no_alias(b)
        self.generic_ops(original,session='restore-original')
        self.assertEqual(self.shots()[b['shotId']]['sceneId'],self.shots()[c['shotId']]['sceneId'].replace('S03','S02'))
        path='/projects/api/'+self.slug+'/tabs/director-brief/revisions/'+str(saved['revision'])+'/restore'
        code,result,_=self.request(path,method='POST',data={})
        self.assertEqual(code,200,result);self.assert_no_alias(b)
        for shot in (a,b,c):self.assert_preserved(shot)

    def test_adaptation_adoption_detaches_old_sources_without_fabricating_identity(self):
        a,b,c=self.prepare();ws=self.writing('workspace')
        source=self.writing('sources/idea','PUT',{'baseVersion':0,'clientMutationId':'idea','doc':core.document('A keeper opens a door and later leaves.'),'structure':{},'composition':{}})
        preview=self.writing('previews','POST',{'kind':'adaptation','sourceRef':{'kind':'source','mode':'idea'},
            'expectedSourceHash':source['docHash'],'targetDocHash':ws['docHash'],'targetScenes':2})
        self.writing('previews/'+preview['previewId']+'/apply','POST',{'expectedPreviewVersion':1,'selection':{'actions':[{'actionId':'whole'}]}})
        for shot in (a,b,c):self.assert_no_alias(shot)

    def ac_text(self):
        doc=self.writing('workspace')['doc']
        return '\n\n'.join(story.doc_text({'content':[n]}) for n in doc['content'][:2]+doc['content'][4:])

    def test_legacy_whole_script_put_and_rebuild_preserve_removed_takes(self):
        a,b,c=self.prepare()
        self.ok('/episodes/'+self.ep+'/script','PUT',{'scriptContent':self.ac_text()})
        self.assert_no_alias(b)
        self.ok('/episodes/'+self.ep+'/asset-extractions','POST',{})
        self.ok('/episodes/'+self.ep+'/storyboards','POST',{})
        for scene in self.ok('/episodes/'+self.ep+'/scenes')['items']:
            self.ok('/scenes/'+scene['sceneId']+'/shot-rebuilds','POST',{})
        self.assertEqual(self.shots()[b['shotId']]['description'],b['description'])
        for shot in (a,b,c):self.assert_preserved(shot,origin=shot is b)

    def test_legacy_async_refinement_uses_current_trusted_writer(self):
        from types import SimpleNamespace
        from project_assistant import providers
        import test_story_openapi
        a,b,c=self.prepare();text=self.ac_text()
        with patch.dict(os.environ,{'OPENBENCH_PROVIDER':'openai_compat','OPENBENCH_MODEL':'synthetic','OPENBENCH_API_BASE':'http://127.0.0.1:1/v1'}), patch.object(providers,'run_openai_compat_turn',return_value=SimpleNamespace(status='ok',answer=text)):
            task=self.ok('/episodes/'+self.ep+'/script-refinements','POST',{'instruction':'Remove B'})
            done=test_story_openapi.StoryHTTPTests.await_task(self,task)
        self.assertEqual(done['status'],'SUCCEEDED',done);self.assert_no_alias(b)
        for shot in (a,b,c):self.assert_preserved(shot)

    def test_generic_file_replacement_uses_the_same_source_history_transaction(self):
        a,b,c=self.prepare();tab=repo.get_tab(self.conn,self.slug,'director-brief')
        path='/projects/api/'+self.slug+'/tabs/import?tab_key=director-brief&base_revision='+str(tab['revision'])+'&confirm_replace=true'
        code,result,_=self.request(path,method='POST',raw=self.ac_text().encode(),
            headers={'Content-Type':'text/markdown','X-File-Name':'script.md'})
        self.assertEqual(code,200,result);self.assert_no_alias(b)
        for shot in (a,b,c):self.assert_preserved(shot)

    def test_reviewed_agent_whole_document_replacement_and_stale_guard(self):
        from project_assistant import proposal_output,store as assistant_store
        a,b,c=self.prepare();target={'tab_key':'director-brief','kind':'doc','mode':'replace'}
        snapshot=proposal_output.snapshot_target(self.conn,self.slug,target)
        prepared,preview=proposal_output.prepare_output(target,snapshot,{'text':self.ac_text()},conn=self.conn,slug=self.slug)
        proposal=assistant_store.create_proposal(self.conn,self.slug,self.actor,None,'table_edit',prepared,preview)
        self.conn.commit()
        code,result,_=self.request('/projects/api/'+self.slug+'/assistant/proposals/'+str(proposal)+'/apply',method='POST',data={})
        self.assertEqual(code,200,result);self.assert_no_alias(b)
        for shot in (a,b,c):self.assert_preserved(shot)
        stale=assistant_store.create_proposal(self.conn,self.slug,self.actor,None,'table_edit',prepared,preview);self.conn.commit()
        before=self.writing('workspace')['docHash']
        code,_,_=self.request('/projects/api/'+self.slug+'/assistant/proposals/'+str(stale)+'/apply',method='POST',data={})
        self.assertEqual(code,409)
        self.assertEqual(self.writing('workspace')['docHash'],before)

    def test_orchestrated_proposal_contention_keeps_gate_pending_then_explicit_apply_once(self):
        import psycopg
        from pathlib import Path
        from orchestration_fixture import OrchestrationFixture
        from project_assistant import orchestrator as cp,orchestration_store as db,store as assistant_store,tools
        a,b,c=self.prepare();text=self.ac_text()
        run=OrchestrationFixture.run_record(self)
        task=cp.create_task(self.conn,self.me,self.slug,run['id'],objective='Synthetic document replacement',
            agent_key='doc_writer',target={'tab_key':'director-brief','kind':'doc','mode':'replace'})
        child=cp.create_task(self.conn,self.me,self.slug,run['id'],objective='Downstream remains blocked',
            agent_key='doc_writer',depends_on=[task['id']],write_mode='analysis_only')
        cp.spawn_dispatch(self.conn,self.slug,task['id'],agent_key='doc_writer',slot_key='single')
        claim=cp.claim_dispatch(self.conn,'n2-worker',['doc_writer'],allowed_projects=[self.slug])
        ctx=tools.ToolContext(lambda:None,self.slug,self.me,Path('.'),None,agent_key='doc_writer',dispatch_id=claim['id'],
            admission_no=claim['admission_no'],lease_token=claim['lease_token'],worker_id='n2-worker',run_id=run['id'])
        proposals=cp.prepare_dispatch_output(self.conn,ctx,{'text':text})
        self.assertEqual(len(proposals),1)
        proposal=proposals[0]
        cp.complete_dispatch(self.conn,'n2-worker',claim['handle'],claim['lease_token'],outcome='succeeded',
            output={'text':'Prepared, not applied'},proposal_ids=proposals)
        self.conn.commit()
        before=self.writing('workspace');history=repo.revision_rows(self.conn,self.slug,tab_key='director-brief')
        child_status=db.get_task(self.conn,self.slug,child['id'])['status']
        receipts=db.one(self.conn,"SELECT count(*) FROM projectops.story_record WHERE project_slug=%s AND kind='writing_receipt'",(self.slug,))
        gates=db.many(self.conn,'SELECT to_jsonb(g) FROM projectops.orchestration_gate g WHERE dispatch_id=%s',(claim['id'],))
        self.conn.rollback()
        path='/projects/api/'+self.slug+'/assistant/proposals/'+str(proposal)+'/apply'
        with psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI']) as other:
            other.execute('SELECT tab_key FROM projectops.tab WHERE project_slug=%s AND tab_key=%s FOR UPDATE',(self.slug,'cinema-studio'))
            code,result,_=self.request(path,method='POST',data={})
            self.assertEqual(code,409,result);self.assertEqual(result['code'],'DRAMA_WRITING_LOCKED')
        self.assertEqual(assistant_store.proposal(self.conn,proposal)['status'],'pending')
        self.assertEqual(db.get_task(self.conn,self.slug,task['id'])['status'],'awaiting_gate')
        self.assertEqual(db.get_task(self.conn,self.slug,child['id'])['status'],child_status)
        self.assertEqual(db.many(self.conn,'SELECT to_jsonb(g) FROM projectops.orchestration_gate g WHERE dispatch_id=%s',(claim['id'],)),gates)
        self.assertEqual(db.one(self.conn,"SELECT count(*) FROM projectops.story_record WHERE project_slug=%s AND kind='writing_receipt'",(self.slug,)),receipts)
        self.assertEqual(self.writing('workspace')['docHash'],before['docHash'])
        self.assertEqual(repo.revision_rows(self.conn,self.slug,tab_key='director-brief'),history)
        for shot in (a,b,c):self.assertEqual(self.assert_preserved(shot)['sceneId'],shot['sceneId'])
        self.conn.rollback()
        code,result,_=self.request(path,method='POST',data={});self.assertEqual(code,200,result)
        self.assertEqual(assistant_store.proposal(self.conn,proposal)['status'],'applied')
        self.assertEqual(db.get_task(self.conn,self.slug,task['id'])['status'],'completed')
        self.assertEqual(db.get_task(self.conn,self.slug,child['id'])['status'],'ready')
        self.assert_no_alias(b)
        self.assertEqual(self.request(path,method='POST',data={})[0],409)
        self.assertEqual(db.one(self.conn,'SELECT count(*) FROM projectops.orchestration_dispatch WHERE task_id=%s',(task['id'],)),1)
        for shot in (a,b,c):self.assert_preserved(shot)

    def test_nowait_contention_rolls_back_generic_source_history_and_associations(self):
        import psycopg
        a,b,c=self.prepare();before=self.writing('workspace');doc=copy.deepcopy(before['doc']);del doc['content'][2:4]
        history=repo.revision_rows(self.conn,self.slug,tab_key='director-brief');self.conn.rollback()
        with psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI']) as other:
            other.execute('SELECT tab_key FROM projectops.tab WHERE project_slug=%s AND tab_key=%s FOR UPDATE',(self.slug,'cinema-studio'))
            started=time.monotonic();self.generic_ops(doc,expected=409)
            self.assertLess(time.monotonic()-started,5)
        after=self.writing('workspace')
        self.assertEqual((before['docHash'],before['structureHash']),(after['docHash'],after['structureHash']))
        self.assertEqual(repo.revision_rows(self.conn,self.slug,tab_key='director-brief'),history)
        for shot in (a,b,c):self.assertEqual(self.assert_preserved(shot)['sceneId'],shot['sceneId'])

    def test_nonstructural_keystrokes_and_unrelated_documents_do_not_lock_production(self):
        import psycopg
        a,b,c=self.prepare();before=self.writing('workspace');doc=copy.deepcopy(before['doc']);doc['content'][1]['content'][0]['text']='Changed action, same source identity.'
        repo.create_tab(self.conn,self.slug,key='unrelated',title='Other',doc=core.document('Scene 01: Not an episode','Notes'),actor_id=self.actor,parent_key=None)
        self.conn.commit()
        other_doc=core.document('Scene 01: Different','Unrelated notes')
        with psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI']) as other:
            other.execute('SELECT tab_key FROM projectops.tab WHERE project_slug=%s AND tab_key=%s FOR UPDATE',(self.slug,'cinema-studio'))
            with patch.object(structure,'lock_associations',side_effect=AssertionError('Unnecessary production lock')):
                self.generic_ops(doc)
                self.generic_ops(other_doc,key='unrelated')
        for shot in (a,b,c):self.assert_preserved(shot)

    def test_stale_or_locked_adoption_is_atomic_and_internal_deferral_unwinds(self):
        a,b,c=self.prepare();preview=self.adoption(apply=False);before=self.writing('workspace')
        original=repo.tab_locks
        def locked(conn,slug,key):return original(conn,slug,key)|({b['rowId']:'other-writer'} if key==b['tabKey'] else {})
        with patch.object(repo,'tab_locks',locked):
            self.error('previews/'+preview['previewId']+'/apply','POST',{'expectedPreviewVersion':1,
                'selection':{'actions':[{'actionId':'whole'}]}},409)
        self.assertEqual(self.writing('workspace')['docHash'],before['docHash'])
        self.assertEqual(self.writing('previews/'+preview['previewId'])['status'],'pending')
        for shot in (a,b,c):self.assertEqual(self.assert_preserved(shot)['sceneId'],shot['sceneId'])
        scope=store.scope_for(self.conn,self.me,self.ep,write=True)
        from project_docs import writing_versions
        with patch.object(repo,'tab_locks',locked),self.assertRaises(story.StoryError):
            writing_versions.apply_preview(self.conn,scope,preview,{'actions':[{'actionId':'whole'}]})
        self.assertFalse(hasattr(self.conn,'_writing_structure_deferred'))
        self.conn.rollback()
        changed=copy.deepcopy(before['doc']);changed['content'][1]['content'][0]['text']='Newer screenplay'
        self.save_doc(changed)
        self.error('previews/'+preview['previewId']+'/apply','POST',{'expectedPreviewVersion':1,
            'selection':{'actions':[{'actionId':'whole'}]}},409)
        for shot in (a,b,c):self.assert_preserved(shot)

    def test_duplicate_headers_adoption_retains_bid_identity_not_title_or_order(self):
        a,b,c=self.prepare();doc=copy.deepcopy(self.writing('workspace')['doc'])
        for index in (0,2,4):doc['content'][index]['content']=[{'type':'text','text':'Scene 01: Duplicate'}]
        self.save_doc(doc)
        self.assertEqual([s['sceneKey'] for s in self.writing('structure')['scenes']],self.keys)
        self.adoption();self.assert_no_alias(b)
        self.assertEqual([s['sceneKey'] for s in self.writing('structure')['scenes']],[self.keys[0],self.keys[2]])
        for shot in (a,b,c):self.assert_preserved(shot)

    def test_page_rename_heading_structural_effects_are_in_the_same_save_boundary(self):
        a,b,c=self.prepare();doc=copy.deepcopy(self.writing('workspace')['doc'])
        doc['content'][0]['attrs']['level']=1;self.save_doc(doc)
        title=story.node_text(doc['content'][0])
        repo.update_tab_meta(self.conn,self.slug,'director-brief',title=title);self.conn.commit()
        path='/projects/api/'+self.slug+'/tabs/director-brief/meta'
        code,result,_=self.request(path,method='POST',data={'title':'Not a scene heading'})
        self.assertEqual(code,200,result)
        self.assert_no_alias(a)
        for shot in (a,b,c):self.assert_preserved(shot)

    def test_idle_connection_boundaries_do_not_commit_the_callers_transaction(self):
        import psycopg
        from project_docs import service
        a,b,c=self.prepare();tab=repo.get_tab(self.conn,self.slug,'director-brief');doc=copy.deepcopy(tab['doc']);del doc['content'][2:4]
        ep=story.episode(self.conn,self.ep);items=story.scenes(self.conn,ep);self.conn.rollback()
        for mode in ('repository','generic','declared'):
            with self.subTest(mode=mode),psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI']) as other:
                if mode=='repository':
                    repo.save_tab_doc(other,self.slug,'director-brief',doc=doc,title=tab['title'],actor_id=self.actor,
                        session_id='outer-rollback',base_revision=tab['revision'],trusted_writer=self.me)
                elif mode=='generic':
                    ops=[{'op':'del','bid':structure.bid(n),'base':n} for n in tab['doc']['content'][2:4]]
                    code,_=service.apply_tab_ops(other,self.me,self.slug,'director-brief',{'ops':ops,'session_id':'outer-rollback'})
                    self.assertEqual(code,200)
                else:
                    story.write_scenes(other,self.me,ep,[items[0],items[2]])
                self.assertEqual(repo.get_tab(self.conn,self.slug,'director-brief')['doc'],tab['doc'])
                self.assertEqual(story.shot_meta(self.conn,b['shotId'])['sceneId'],b['sceneId'])
                self.conn.rollback();other.rollback()
        for shot in (a,b,c):self.assert_preserved(shot)

    def test_repository_requires_trusted_context_not_an_actor_id_for_derived_writes(self):
        a,b,c=self.prepare();tab=repo.get_tab(self.conn,self.slug,'director-brief');doc=copy.deepcopy(tab['doc']);del doc['content'][2:4]
        with self.assertRaises(story.StoryError):
            repo.save_tab_doc(self.conn,self.slug,'director-brief',doc=doc,title=tab['title'],actor_id=self.actor,
                session_id='no-trusted-context',base_revision=tab['revision'])
        self.assertEqual(repo.get_tab(self.conn,self.slug,'director-brief')['doc'],tab['doc'])
        self.conn.rollback()
        for shot in (a,b,c):self.assert_preserved(shot)


if __name__=='__main__':unittest.main()
