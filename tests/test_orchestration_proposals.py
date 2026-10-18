import copy
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from orchestration_fixture import OrchestrationFixture
from project_assistant import orchestrator as cp,orchestration_store as db,tools,store,service,proposal_output
from project_docs import repository as repo
from project_docs.doc_schema import node_text


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'),'set OPENBENCH_TEST_DB_URI')
class OrchestrationProposalTests(OrchestrationFixture,unittest.TestCase):
    def pending(self,rows=None,finish=True):
        run=self.run_record()
        task=self.task_record(run,scope=self.sheet_scope(),target={'tab_key':'shots','kind':'table'})
        child=self.task_record(run,depends_on=[task['id']],write_mode='analysis_only')
        cp.spawn_dispatch(self.conn,self.slug,task['id'],agent_key='sheet_ops',slot_key='single')
        claim=cp.claim_dispatch(self.conn,'proposal-worker',['sheet_ops'],allowed_projects=[self.slug])
        ctx=tools.ToolContext(lambda:None,self.slug,self.me,Path('.'),None,agent_key='sheet_ops',dispatch_id=claim['id'],
            admission_no=claim['admission_no'],lease_token=claim['lease_token'],worker_id='proposal-worker',run_id=run['id'])
        for rid in rows or ['b_shot1']:
            tools.propose_table_edit(ctx,self.conn,{'tab_key':'shots','table_id':'b_table','row_edits':[{'row_id':rid,'cells':{'1':'updated '+rid}}]})
        proposals=store.proposals(self.conn,self.slug,owner_id=self.actor)
        if finish:
            cp.complete_dispatch(self.conn,'proposal-worker',claim['handle'],claim['lease_token'],outcome='succeeded',output={'text':'prepared'},proposal_ids=[p['id'] for p in proposals])
        return run,task,child,claim,ctx,proposals

    def cell(self,rid):
        tab=repo.get_tab(self.conn,self.slug,'shots')
        return node_text(next(r for r in tab['doc']['content'][0]['content'] if r['attrs']['bid']==rid)['content'][1])

    def test_apply_advances_task_in_same_transaction(self):
        run,task,child,claim,ctx,proposals=self.pending()
        self.assertEqual(self.cell('b_shot1'),'original')
        self.assertEqual(db.get_task(self.conn,self.slug,task['id'])['status'],'awaiting_gate')
        code,result=service.apply_proposal(self.conn,self.me,self.slug,proposals[0]['id'],{})
        self.assertEqual(code,200,result)
        self.assertEqual(self.cell('b_shot1'),'updated b_shot1')
        self.assertEqual(db.get_task(self.conn,self.slug,task['id'])['status'],'completed')
        self.assertEqual(db.get_task(self.conn,self.slug,child['id'])['status'],'ready')

    def test_dismiss_blocks_join(self):
        run,task,child,claim,ctx,proposals=self.pending()
        self.assertEqual(service.dismiss_proposal(self.conn,self.me,self.slug,proposals[0]['id'])[0],200)
        self.assertEqual(db.get_task(self.conn,self.slug,task['id'])['status'],'failed')
        self.assertEqual(db.get_task(self.conn,self.slug,child['id'])['status'],'failed')
        self.assertEqual(self.cell('b_shot1'),'original')

    def test_multi_proposal_requires_all_applied(self):
        run,task,child,claim,ctx,proposals=self.pending(['b_shot1','b_shot2'])
        self.assertEqual(len(proposals),2)
        self.assertEqual(service.apply_proposal(self.conn,self.me,self.slug,proposals[0]['id'],{})[0],200)
        self.assertEqual(db.get_task(self.conn,self.slug,task['id'])['status'],'awaiting_gate')
        code,result=service.apply_proposal(self.conn,self.me,self.slug,proposals[1]['id'],{})
        self.assertEqual(code,200,result)
        self.assertEqual(db.get_task(self.conn,self.slug,task['id'])['status'],'completed')

    def test_orchestration_proposal_rejects_partial_groups(self):
        run,task,child,claim,ctx,proposals=self.pending()
        self.assertEqual(service.apply_proposal(self.conn,self.me,self.slug,proposals[0]['id'],{'groups':[0]})[0],400)
        self.assertEqual(self.cell('b_shot1'),'original')

    def test_cannot_apply_before_worker_finishes_the_output_group(self):
        run,task,child,claim,ctx,proposals=self.pending(finish=False)
        self.assertEqual(service.apply_proposal(self.conn,self.me,self.slug,proposals[0]['id'],{})[0],409)
        self.assertEqual(self.cell('b_shot1'),'original')

    def test_doc_output_uses_original_block_bases(self):
        doc={'type':'doc','content':[{'type':'paragraph','attrs':{'bid':key},'content':[{'type':'text','text':text}]} for key,text in [('b_first','Keep'),('b_second','Replace me'),('b_third','Keep too')]]}
        snapshot={'doc':doc,'values':{},'title':'Notes','revision':2}
        scope={'kind':'doc','target_tab':'notes','block_ids':['b_second']}
        target,preview=proposal_output.prepare_output({'tab_key':'notes','kind':'doc','mode':'replace'},snapshot,{'text':'New'},scope=scope)
        self.assertEqual([op['bid'] for op in target['ops'] if op['op']=='del'],['b_second'])
        inserted=next(op for op in target['ops'] if op['op']=='put')
        self.assertEqual(inserted['after'],'b_first')
        self.assertEqual(next(op for op in target['ops'] if op['op']=='del')['base']['content'][0]['text'],'Replace me')

    def test_canceled_dispatch_cannot_create_proposal_via_tool_host(self):
        import psycopg
        run,task,child,claim,ctx,proposals=self.pending()
        cp.cancel_dispatch(self.conn,self.me,self.slug,claim['handle'],'stop')
        self.conn.commit()
        ctx.connection_factory=lambda:psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI'])
        before=db.one(self.conn,'SELECT count(*) FROM projectops.assistant_proposal WHERE project_slug=%s',(self.slug,))
        with self.assertRaises(tools.ToolError):
            tools.call(ctx,'propose_table_edit',{'tab_key':'shots','row_edits':[{'row_id':'b_shot2','cells':{'1':'late'}}]})
        self.assertEqual(db.one(self.conn,'SELECT count(*) FROM projectops.assistant_proposal WHERE project_slug=%s',(self.slug,)),before)

    def test_hook_failure_rolls_back_canvas_and_proposal(self):
        run,task,child,claim,ctx,proposals=self.pending()
        with self.assertRaises(RuntimeError),self.conn.transaction():
            with patch.object(cp,'on_proposal_decided',side_effect=RuntimeError('injected failure')):
                service.apply_proposal(self.conn,self.me,self.slug,proposals[0]['id'],{})
        self.assertEqual(self.cell('b_shot1'),'original')
        self.assertEqual(store.proposal(self.conn,proposals[0]['id'])['status'],'pending')
        self.assertEqual(db.get_task(self.conn,self.slug,task['id'])['status'],'awaiting_gate')

    def test_dispatch_reads_original_snapshot_after_live_edit(self):
        run,task,child,claim,ctx,proposals=self.pending()
        tab=repo.get_tab(self.conn,self.slug,'shots')
        changed=copy.deepcopy(tab['doc'])
        changed['content'][0]['content'][1]['content'][1]['content'][0]['content'][0]['text']='live change'
        repo.save_tab_doc(self.conn,self.slug,'shots',doc=changed,title=tab['title'],actor_id=self.actor,session_id='changed',base_revision=tab['revision'])
        result=tools.read_page(ctx,self.conn,{'key':'shots'})
        self.assertIn('original',result)
        self.assertNotIn('live change',result)
        self.assertEqual(service.apply_proposal(self.conn,self.me,self.slug,proposals[0]['id'],{})[0],409)
