import os
import unittest
from types import SimpleNamespace

import test_product_http as fixture
from project_assistant import comment_routing,store,tools,agent_registry
from project_docs import repository as repo


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'),'set OPENBENCH_TEST_DB_URI')
class AgentCommentRoutingTests(unittest.TestCase):
    setUp=fixture.ProductHTTPTests.setUp
    tearDown=fixture.ProductHTTPTests.tearDown
    request=fixture.ProductHTTPTests.request

    def post_row(self,text,**extra):
        tab=repo.get_tab(self.conn,self.slug,'shots')
        self.conn.rollback()  # First HTTP request may run DDL; do not retain an access-share lock in the fixture.
        return self.request(f'/projects/api/{self.slug}/annotations',method='POST',data={'tab_key':'shots','row':'b_shot1',
            'body':text,'source_revision':tab['revision'],**extra})

    def test_human_agent_mention_routes_once_from_published_comment(self):
        code,result,_=self.post_row('@doc_writer 請整理這一列的說明')
        self.assertEqual(code,200,result)
        routed=result['annotation']['agent_request']
        self.assertEqual(routed['agent_key'],'doc_writer')
        message=store.message(self.conn,routed['message_id'])
        self.assertTrue(message['source_ref'].startswith('activity:'))
        self.assertEqual(message['request_scope']['row_ids'],['b_shot1'])
        self.request(f'/projects/api/{self.slug}/tabs/shots')
        self.request(f'/projects/api/{self.slug}/assistant')
        self.assertEqual(len([m for m in store.thread(self.conn,self.slug,self.actor) if m['role']=='user']),1)

    def test_busy_agent_rolls_back_comment_and_keeps_input_retryable(self):
        self.assertEqual(self.post_row('@doc_writer First')[0],200)
        code,result,_=self.post_row('@doc_writer Second')
        self.assertEqual(code,409,result)
        annotations=repo.list_annotations(self.conn,self.slug)
        self.assertEqual(sum(len([m for m in a['messages'] if m['kind']=='comment']) for a in annotations),1)

    def test_reference_mentions_do_not_dispatch(self):
        for text in ('mail@example.com','`@doc_writer` 是引用','@someone_public 的文章','@{'+self.actor+'} human'):
            self.assertEqual(self.post_row(text)[0],200)
        self.assertEqual(store.thread(self.conn,self.slug,self.actor),[])

    def test_other_agent_can_be_named_while_first_is_busy(self):
        self.assertEqual(self.post_row('@doc_writer First')[0],200)
        self.assertEqual(self.post_row('@sheet_ops Second')[0],200)
        self.assertEqual({m['agent_key'] for m in store.thread(self.conn,self.slug,self.actor) if m['role']=='assistant'},
                         {'doc_writer','sheet_ops'})

    def test_public_body_cannot_spoof_trusted_source_reference(self):
        code,result,_=self.request(f'/projects/api/{self.slug}/assistant/messages',method='POST',
            data={'text':'@missing work','agent_key':'doc_writer','source_ref':'activity:1'})
        self.assertEqual(code,400,result)

    def test_model_authored_accepted_comment_never_dispatches(self):
        doc={'type':'doc','content':[{'type':'paragraph','attrs':{'bid':'b_note'},'content':[{'type':'text','text':'Unique paragraph for routing'}]}]}
        repo.create_tab(self.conn,self.slug,key='notes',title='Notes',parent_key=None,doc=doc,actor_id=self.actor,surface_type='doc')
        ctx=SimpleNamespace(slug=self.slug,me=self.me,message_id=None,agent_key='qa_critic')
        tools.propose(ctx,self.conn,{'action':'在段落加標註','page':'notes','quote':'Unique paragraph','label':'問題','content':'@doc_writer 請處理'})
        proposal=store.proposals(self.conn,self.slug,owner_id=self.actor)[0]
        self.conn.commit()
        code,result,_=self.request(f'/projects/api/{self.slug}/assistant/proposals/{proposal["id"]}/apply',method='POST',data={})
        self.assertEqual(code,200,result)
        self.assertEqual(store.thread(self.conn,self.slug,self.actor),[])

    def test_document_mention_keeps_exact_selected_top_level_blocks(self):
        from project_docs import anchoring
        from project_docs.doc_schema import doc_text
        doc={'type':'doc','content':[{'type':'paragraph','attrs':{'bid':bid},'content':[{'type':'text','text':text}]} for bid,text in
                                   [('b_first','First paragraph'),('b_second','Second paragraph for review')]]}
        repo.create_tab(self.conn,self.slug,key='notes',title='Notes',parent_key=None,doc=doc,actor_id=self.actor,surface_type='doc')
        tab=repo.get_tab(self.conn,self.slug,'notes'); self.conn.commit()
        text=doc_text(doc)
        anchor=anchoring.anchor_at(text,text.index('Second'),'Second paragraph')
        code,result,_=self.request(f'/projects/api/{self.slug}/annotations',method='POST',data={'tab_key':'notes','anchor':anchor,
            'body':'@doc_writer Review this paragraph','source_revision':tab['revision']})
        self.assertEqual(code,200,result)
        routed=result['annotation']['agent_request']
        scope=store.message(self.conn,routed['message_id'])['request_scope']
        self.assertEqual(scope['kind'],'doc')
        self.assertEqual(scope['block_ids'],['b_second'])
