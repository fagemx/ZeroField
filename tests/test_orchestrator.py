import copy
import os
import unittest
import uuid

from orchestration_fixture import OrchestrationFixture
from project_assistant import orchestrator,orchestration_store,request_scope,tools,agent_policy
from project_docs import repository as repo


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'),'set OPENBENCH_TEST_DB_URI')
class OrchestratorTests(OrchestrationFixture,unittest.TestCase):
    def test_same_request_id_creates_one_run(self):
        a=orchestrator.create_run(self.conn,self.me,self.slug,'goal',client_request_id='same-request')
        b=orchestrator.create_run(self.conn,self.me,self.slug,'goal',client_request_id='same-request')
        self.assertEqual(a['id'],b['id'])
        with self.assertRaises(orchestrator.OrchestrationError) as raised:
            orchestrator.create_run(self.conn,self.me,self.slug,'different',client_request_id='same-request')
        self.assertEqual(raised.exception.status,409)

    def test_dependency_must_be_same_run_and_acyclic(self):
        run=self.run_record()
        upstream=self.task_record(run,write_mode='analysis_only')
        child=self.task_record(run,depends_on=[upstream['id']])
        self.assertEqual([t['id'] for t in orchestrator.ready_tasks(self.conn,self.slug,run['id'])],[upstream['id']])
        self.assertEqual(child['status'],'pending')
        other=self.task_record(write_mode='analysis_only')
        for dependencies in ([other['id']],[str(uuid.uuid4())],[upstream['id'],upstream['id']]):
            with self.subTest(dependencies=dependencies),self.assertRaises(ValueError):
                self.task_record(run,depends_on=dependencies)

    def test_child_scope_cannot_expand(self):
        scope=self.sheet_scope(['b_shot1'])
        tab=repo.get_tab(self.conn,self.slug,'shots')
        parent=request_scope.validate_scope(scope,tab,{})
        child=request_scope.validate_scope(self.sheet_scope(['b_shot1','b_shot2']),tab,{})
        with self.assertRaises(ValueError):
            request_scope.guard_child_scope(parent,child)
        request_scope.guard_child_scope(parent,parent)

    def test_snapshot_is_stable_after_tab_edit(self):
        task=self.task_record(scope=self.sheet_scope(),target={'tab_key':'shots','kind':'table'})
        original=copy.deepcopy(task['target_snapshot']['doc'])
        tab=repo.get_tab(self.conn,self.slug,'shots')
        changed=copy.deepcopy(tab['doc'])
        changed['content'][0]['content'][1]['content'][1]['content'][0]['content'][0]['text']='changed'
        repo.save_tab_doc(self.conn,self.slug,'shots',doc=changed,title=tab['title'],actor_id=self.actor,
                           session_id='snapshot-test',base_revision=tab['revision'])
        saved=orchestration_store.get_task(self.conn,self.slug,task['id'])
        self.assertEqual(saved['target_snapshot']['doc'],original)
        self.assertNotEqual(saved['target_snapshot']['doc'],changed)

    def test_task_limit_and_input_validation(self):
        run=self.run_record(limits={'max_tasks_per_run':2})
        self.task_record(run)
        self.task_record(run)
        with self.assertRaises(orchestrator.OrchestrationError) as raised:
            self.task_record(run)
        self.assertEqual(raised.exception.code,'CAPACITY_EXCEEDED')
        for limits in ({'max_depth':3},{'max_depth':True},{'max_parallel_dispatches':0},{'max_tasks_per_run':201}):
            with self.assertRaises(ValueError):
                self.run_record(limits=limits)
        with self.assertRaises(ValueError):
            self.task_record(write_mode='direct')

    def test_analysis_only_cannot_propose(self):
        ctx=type('Ctx',(),{'slug':self.slug,'me':self.me,'agent_key':'sheet_ops','write_mode':'analysis_only'})()
        with self.assertRaises(tools.ToolError):
            agent_policy.authorize_tool(ctx,self.conn,'propose_table_edit',{})

    def test_doc_scope_detects_changed_or_missing_blocks(self):
        doc={'type':'doc','content':[{'type':'paragraph','attrs':{'bid':'b_paragraph'},'content':[{'type':'text','text':'Original'}]}]}
        repo.create_tab(self.conn,self.slug,key='notes',title='Notes',parent_key=None,doc=doc,actor_id=self.actor,surface_type='doc')
        tab=repo.get_tab(self.conn,self.slug,'notes')
        scope=request_scope.validate_scope({'kind':'doc','target_tab':'notes','base_revision':tab['revision'],'block_ids':['b_paragraph']},tab,{})
        self.assertEqual(scope['block_ids'],['b_paragraph'])
        changed=copy.deepcopy(tab)
        changed['doc']['content'][0]['content'][0]['text']='Modified'
        with self.assertRaises(ValueError):
            request_scope.verify_source(scope,changed,{})
